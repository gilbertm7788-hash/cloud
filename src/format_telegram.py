"""텔레그램 메시지 포맷팅 — 하루치를 한 통으로 묶는 일간 다이제스트."""
from __future__ import annotations

from .models import Item

TG_LIMIT = 4096  # 텔레그램 메시지 한도 (참고용, 실제 경계는 SAFE_LIMIT)
SAFE_LIMIT = 4000  # 여유분


def escape_html(s: str) -> str:
    """텔레그램 HTML 규칙 + href 속성 안전을 위한 따옴표 이스케이프."""
    return (s.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def split_blocks(blocks: list[str], limit: int = SAFE_LIMIT) -> list[str]:
    """블록(줄) 단위로만 분할 — 태그 중간에서 절대 자르지 않음."""
    messages: list[str] = []
    current: list[str] = []
    size = 0
    for block in blocks:
        add = len(block) + (1 if current else 0)
        if current and size + add > limit:
            messages.append("\n".join(current))
            current, size = [], 0
            add = len(block)
        current.append(block)
        size += add
    if current:
        messages.append("\n".join(current))
    return messages


# ── 일간 다이제스트 ──────────────────────────────────────────────────────────
# 하루 한 번, 수집분 전체를 한 통(필요 시 여러 통)으로 묶어 보낸다.
# 건별 메시지는 하루 수십 통이 되어 검토가 불가능했다.

WEEKDAYS = ("월", "화", "수", "목", "금", "토", "일")

# 섹션 순서 = 독자 가치 순. 위원회 모집은 다른 데서 찾기 어려운 정보라 맨 앞.
DIGEST_SECTIONS = (
    ("committee", "👥 위원회 모집", None),
    ("bid", "📋 입찰공고", 20),
    ("gov", "🏢 정책", 10),
    ("association", "🏛 협회 소식", 10),
    ("news", "📰 뉴스", 30),
    ("youtube", "🎬 영상", 5),
)
# 뉴스는 매체가 많아 한 매체가 지면을 독점하지 않게 제한
PER_SOURCE_CAP = 5


def _digest_meta_line(item: Item) -> str:
    """항목 아래 붙는 부가 정보 한 줄. 없으면 빈 문자열."""
    bits: list[str] = []
    org = item.extra.get("org")
    if org:
        bits.append(escape_html(str(org)))
    deadline = item.extra.get("deadline")
    if deadline:
        bits.append(f"마감 {escape_html(str(deadline))}")
    amount = item.extra.get("amount")
    if amount:
        bits.append(f"추정 {escape_html(str(amount))}")
    return " · ".join(bits)


def _digest_entry(item: Item) -> list[str]:
    title = escape_html(item.title.strip())
    if len(title) > 200:
        title = title[:197] + "..."
    href = escape_html(item.url)
    anchor = f'▶️ <a href="{href}">{title}</a>'
    if len(anchor) > SAFE_LIMIT:
        # URL 자체가 한도를 넘는 병리적 케이스 — 링크를 버리고 제목만 남긴다.
        # 한 블록이 한도를 넘으면 split_blocks도 쪼갤 수 없어 전송이 400으로 죽는다.
        anchor = f"▶️ {title}"
    lines = [anchor]
    meta = _digest_meta_line(item)
    if meta:
        lines.append(meta)
    return lines


def _group_by_source(items: list[Item]) -> dict[str, list[Item]]:
    grouped: dict[str, list[Item]] = {}
    for it in items:
        grouped.setdefault(it.author or it.source_id, []).append(it)
    return grouped


def format_daily_digest(items: list[Item], day, site_url: str = "",
                        title: str = "라벤더") -> list[str]:
    """수집분을 섹션별로 묶은 일간 다이제스트. 4096자 경계에서 여러 통으로 나뉜다."""
    date_str = f"{day.year}년 {day.month}월 {day.day}일"
    header = f"<b>[{escape_html(title)}] {date_str} ({WEEKDAYS[day.weekday()]})</b>"
    blocks: list[str] = [header]
    total = 0

    for category, label, cap in DIGEST_SECTIONS:
        bucket = [it for it in items if (it.category or "news") == category]
        if not bucket:
            continue
        shown, omitted = bucket, 0
        if cap is not None and len(bucket) > cap:
            shown, omitted = bucket[:cap], len(bucket) - cap

        blocks.append("")
        blocks.append(f"<b>{label}</b>")

        if category == "news":
            # 매체별로 묶어 출처가 드러나게 (『커버리지』식 그룹 헤더)
            for source_name, group in _group_by_source(shown).items():
                blocks.append("")
                blocks.append(f"&lt;{escape_html(source_name)}&gt;")
                for it in group[:PER_SOURCE_CAP]:
                    blocks.extend(_digest_entry(it))
                    total += 1
                if len(group) > PER_SOURCE_CAP:
                    omitted += len(group) - PER_SOURCE_CAP
        else:
            for it in shown:
                blocks.extend(_digest_entry(it))
                total += 1

        if omitted:
            blocks.append(f"…외 {omitted}건")

    if total == 0:
        return []

    blocks.append("")
    if site_url:
        blocks.append(f'전체 공고·아카이브 → <a href="{escape_html(site_url)}">{escape_html(site_url)}</a>')
    return split_blocks(blocks)
