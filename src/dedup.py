"""SQLite 기반 중복제거·상태 추적 (state/seen.db)."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import Item

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seen(
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL,
  category TEXT,
  url TEXT,
  title TEXT,
  author TEXT,
  published_at TEXT,
  first_seen_at TEXT NOT NULL,
  posted_at TEXT,
  status TEXT NOT NULL DEFAULT 'seen',
  tg_message_id INTEGER,
  extra TEXT
);
CREATE INDEX IF NOT EXISTS idx_seen_src ON seen(source_id, first_seen_at);
CREATE INDEX IF NOT EXISTS idx_seen_posted ON seen(posted_at);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
"""


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat() if dt else None


class SeenStore:
    def __init__(self, path: Path | str = Path("state/seen.db")):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.commit()
        self.conn.close()

    # -- dedup ---------------------------------------------------------------

    def is_seen(self, key: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM seen WHERE id=?", (key,)).fetchone()
        return row is not None

    def source_has_rows(self, source_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM seen WHERE source_id=? LIMIT 1", (source_id,)
        ).fetchone()
        return row is not None

    def mark_seen(self, item: Item, status: str = "seen") -> None:
        self.conn.execute(
            """INSERT OR IGNORE INTO seen
               (id, source_id, category, url, title, author, published_at,
                first_seen_at, status, extra)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                item.dedup_key, item.source_id, item.category, item.url,
                item.title, item.author, _iso(item.published_at),
                _iso(item.fetched_at), status,
                json.dumps(item.extra, ensure_ascii=False, default=str),
            ),
        )
        self.conn.commit()

    def mark_status(self, key: str, status: str) -> None:
        """게시 불가 등 종료 상태로 전환 (재시도 큐에서 제외)."""
        self.conn.execute("UPDATE seen SET status=? WHERE id=?", (status, key))
        self.conn.commit()

    def mark_posted(self, key: str, message_id: int | None = None) -> None:
        self.conn.execute(
            "UPDATE seen SET status='posted', posted_at=?, tg_message_id=? WHERE id=?",
            (_iso(datetime.now(timezone.utc)), message_id, key),
        )
        self.conn.commit()

    # -- 조회 (블로그 초안·사이트 빌드용) ------------------------------------

    def pending(self, limit: int = 50) -> list[dict]:
        """이전 run에서 게시에 실패해 재시도 대기 중인 아이템 (오래된 순)."""
        rows = self.conn.execute(
            "SELECT * FROM seen WHERE status='pending' ORDER BY first_seen_at LIMIT ?",
            (limit,),
        ).fetchall()
        return [self._to_dict(r) for r in rows]

    def posted_between(self, start: datetime, end: datetime) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM seen WHERE posted_at >= ? AND posted_at < ? ORDER BY posted_at",
            (_iso(start), _iso(end)),
        ).fetchall()
        return [self._to_dict(r) for r in rows]

    def recent(self, days: int = 90, statuses: tuple[str, ...] = ("posted", "seen")) -> list[dict]:
        cutoff = _iso(datetime.now(timezone.utc) - timedelta(days=days))
        ph = ",".join("?" * len(statuses))
        rows = self.conn.execute(
            f"SELECT * FROM seen WHERE first_seen_at >= ? AND status IN ({ph}) "
            "ORDER BY first_seen_at DESC",
            (cutoff, *statuses),
        ).fetchall()
        return [self._to_dict(r) for r in rows]

    @staticmethod
    def _to_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        try:
            d["extra"] = json.loads(d.get("extra") or "{}")
        except (json.JSONDecodeError, TypeError):
            d["extra"] = {}
        return d

    # -- meta ----------------------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self.conn.commit()

    # -- 정리 ----------------------------------------------------------------

    def prune(self, keep_days: int = 365) -> int:
        """오래된 미게시 row 정리 (posted는 아카이브로 보존)."""
        cutoff = _iso(datetime.now(timezone.utc) - timedelta(days=keep_days))
        cur = self.conn.execute(
            "DELETE FROM seen WHERE status != 'posted' AND first_seen_at < ?", (cutoff,)
        )
        self.conn.commit()
        return cur.rowcount
