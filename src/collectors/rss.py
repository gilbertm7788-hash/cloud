"""type: rss — feedparser 기반 RSS/Atom 수집."""
from __future__ import annotations

import calendar
import re
from datetime import datetime, timezone

import feedparser

from ..config import SourceConfig
from ..httpio import fetch_bytes, normalize_url
from ..models import Item
from .base import CollectError, RunContext


def _entry_datetime(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            # feedparser의 struct_time은 UTC — timegm으로 해석 (mktime은 로컬시간 가정)
            return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
    return None


def parse_feed(content: bytes, source: SourceConfig) -> list[Item]:
    feed = feedparser.parse(content)
    if feed.bozo and not feed.entries:
        raise CollectError(f"RSS 파싱 실패: {feed.get('bozo_exception')}")
    id_pattern = source.options.get("id_pattern")
    items: list[Item] = []
    for entry in feed.entries:
        link = getattr(entry, "link", "") or ""
        title = (getattr(entry, "title", "") or "").strip()
        if not link or not title or not normalize_url(link):
            continue  # 빈 링크·비 http(s) 스킴(javascript: 등)은 버림
        natural_key = None
        if id_pattern:
            m = re.search(id_pattern, link)
            if m:
                natural_key = m.group(1)
        if not natural_key:
            natural_key = getattr(entry, "id", None) or None
        summary = getattr(entry, "summary", None)
        if summary:
            summary = re.sub(r"<[^>]+>", "", summary).strip() or None
        items.append(Item(
            source_id=source.id,
            category=source.category,
            title=title,
            url=normalize_url(link),
            natural_key=natural_key,
            key_prefix=f"rss:{source.id}",
            summary=summary,
            published_at=_entry_datetime(entry),
            author=source.name,
        ))
    return items


def collect(source: SourceConfig, ctx: RunContext) -> list[Item]:
    url = source.options.get("url")
    if not url:
        raise CollectError(f"'{source.id}': rss.url 미설정")
    verify_tls = bool(source.options.get("verify_tls", True))
    try:
        content, _ = fetch_bytes(url, timeout=source.timeout, verify_tls=verify_tls)
    except Exception as exc:  # noqa: BLE001
        raise CollectError(f"'{source.id}' 피드 요청 실패: {exc}") from exc
    return parse_feed(content, source)
