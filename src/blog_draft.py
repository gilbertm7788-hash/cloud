"""네이버 블로그(보조 채널)용 초안 생성 — drafts/YYYY-MM-DD.md.

원칙: 기사 본문 복붙 절대 금지 (유사문서 배제 방지). 제목·메타·자체 요약만 담고,
사용자가 채울 "한 줄 해설" 빈칸을 제공한다. 텔레그램 링크는 넣지 않는다 (운영 초기 정책).
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timezone, timedelta
from pathlib import Path

from .dedup import SeenStore
from .llm import summarize_items
from .models import CATEGORY_META

KST = timezone(timedelta(hours=9))
DRAFTS_DIR = Path("drafts")


def _cell(value: object) -> str:
    """마크다운 표 셀 이스케이프 — 스크래핑한 값이 표를 깨거나 마크업을 주입하지 못하게."""
    text = str(value) if value not in (None, "") else "-"
    text = re.sub(r"\s+", " ", text).strip()  # 개행 제거 (표 구조 보호)
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")


def _day_range_utc(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=KST)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def build_draft(store: SeenStore, day: date, *, use_llm: bool = True,
                site_url: str = "") -> str:
    start, end = _day_range_utc(day)
    items = store.posted_between(start, end)
    by_category: dict[str, list[dict]] = {}
    for it in items:
        by_category.setdefault(it.get("category") or "news", []).append(it)

    date_str = day.strftime("%Y년 %m월 %d일")
    lines: list[str] = [
        f"<!-- 네이버 블로그 초안 · {day.isoformat()} · 발행 전 검토 필수 -->",
        "<!-- 원칙: 이 초안을 그대로 붙여넣지 말고, [한 줄 해설]을 직접 채우고 문장을 다듬어 발행 -->",
        "",
        "# 제목 후보",
        f"1. {date_str} 건설업계 브리핑 — 오늘 꼭 봐야 할 소식",
        f"2. 오늘의 건설 뉴스·입찰·위원회 모집 정리 ({day.strftime('%m/%d')})",
        f"3. 건설 실무자를 위한 {day.strftime('%m월 %d일')} 핵심 소식 모음",
        "",
        "## 오늘의 요약",
    ]

    titles = [f"[{it.get('category')}] {it.get('title')}" for it in items]
    summary = summarize_items(titles) if (use_llm and titles) else None
    if summary:
        lines.append(summary)
    elif titles:
        counts = ", ".join(
            f"{CATEGORY_META.get(cat, {}).get('label', cat)} {len(lst)}건"
            for cat, lst in by_category.items()
        )
        lines.append(f"오늘은 {counts}을 정리했습니다. 아래에서 자세한 내용을 확인하세요.")
        lines.append("[한 줄 해설: 오늘 흐름에 대한 본인 코멘트를 여기에 작성]")
    else:
        lines.append("(오늘 게시된 콘텐츠가 없습니다)")

    order = ["news", "gov", "bid", "committee", "association", "youtube"]
    for cat in order:
        cat_items = by_category.get(cat)
        if not cat_items:
            continue
        meta = CATEGORY_META.get(cat, {"emoji": "", "label": cat})
        lines += ["", f"## {meta['emoji']} {meta['label']}", ""]
        lines.append("| 제목 | 기관/출처 | 마감 | 링크 |")
        lines.append("|---|---|---|---|")
        for it in cat_items:
            extra = it.get("extra") or {}
            url = str(it.get("url") or "")
            link = f"[바로가기]({url})" if url.startswith(("http://", "https://")) else "-"
            lines.append(
                f"| {_cell(it.get('title'))} | {_cell(extra.get('org') or it.get('author'))} "
                f"| {_cell(extra.get('deadline'))} | {link} |"
            )
        lines.append("")
        lines.append("[한 줄 해설: 이 섹션에서 주목할 항목과 이유를 직접 작성]")

    lines += ["", "---", ""]
    if site_url:
        lines.append(f"더 많은 공고와 지난 소식은 아카이브에서 볼 수 있습니다: {site_url}")
    lines.append("※ 각 항목의 자세한 내용은 링크된 원문(출처)을 확인해 주세요.")
    return "\n".join(lines)


def write_draft(content: str, day: date) -> Path:
    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    path = DRAFTS_DIR / f"{day.isoformat()}.md"
    path.write_text(content, encoding="utf-8")
    return path
