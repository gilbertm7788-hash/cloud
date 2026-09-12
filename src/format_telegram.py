"""텔레그램 메시지 포맷팅 (HTML, 4096자 분할, 링크 프리뷰)."""
from __future__ import annotations

import re

from .models import CATEGORY_META, Item

TG_LIMIT = 4096
SAFE_LIMIT = 4000  # 여유분

_PARTIAL_ENTITY_RE = re.compile(r"&[a-zA-Z#0-9]{0,8}$")


def escape_html(s: str) -> str:
    """텔레그램 HTML 규칙 + href 속성 안전을 위한 따옴표 이스케이프."""
    return (s.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _meta(category: str) -> dict[str, str]:
    return CATEGORY_META.get(category, {"emoji": "🔔", "label": category, "hashtag": ""})


def format_item(item: Item, site_url: str = "") -> str:
    """카테고리별 템플릿. 블록(줄) 리스트를 조립해 태그 절단이 불가능한 구조로 생성."""
    m = _meta(item.category)
    title = escape_html(item.title.strip())
    lines: list[str] = [f"{m['emoji']} [{m['label']}] <b>{title}</b>"]

    info_bits: list[str] = []
    org = item.extra.get("org") or item.author
    if org:
        info_bits.append(escape_html(str(org)))
    deadline = item.extra.get("deadline")
    if deadline:
        info_bits.append(f"마감 {escape_html(str(deadline))}")
    amount = item.extra.get("amount")
    if amount:
        info_bits.append(f"추정 {escape_html(str(amount))}")
    if info_bits:
        lines.append(" | ".join(info_bits))

    # 기사 요약(RSS description)은 싣지 않는다. 제목만으로 내용 파악이 되고,
    # 본문 발췌를 공개 채널로 재전송하는 것은 제목·링크만 다루는 나머지 구조와
    # 성격이 달라 저작권상 유일하게 남아 있던 회색지대였다 (docs/checklist.md 운영 원칙).

    link_label = {"bid": "공고 보기", "committee": "공고 보기", "youtube": "영상 보기"}.get(
        item.category, "원문 보기"
    )
    link_line = f'<a href="{escape_html(item.url)}">{link_label}</a>'
    lines.append(link_line)

    tags = [m["hashtag"]] if m["hashtag"] else []
    if site_url:
        tags.append(f'<a href="{escape_html(site_url)}">전체 공고·아카이브</a>')
    if tags:
        lines.append(" · ".join(tags))

    text = "\n".join(lines)
    if len(text) > SAFE_LIMIT:
        # 단일 아이템이 한도를 넘는 극단 케이스: 제목·링크만 남기되 태그·엔티티는 절대 자르지 않음
        budget = SAFE_LIMIT - len(link_line) - 100
        if budget < 0:
            # URL 자체가 한도를 넘는 병리적 케이스 — 링크를 앵커 없이 잘라 넣어
            # MESSAGE_TOO_LONG(400)로 아이템이 영구 실패하는 것을 막는다
            return escape_html(item.title.strip())[:200] + "\n" + escape_html(item.url)[:SAFE_LIMIT - 250]
        short = _PARTIAL_ENTITY_RE.sub("", escape_html(item.title.strip())[:budget])
        text = f"{m['emoji']} [{m['label']}] <b>{short}</b>\n{link_line}"
    return text


def format_digest(items: list[Item], title: str, site_url: str = "") -> list[str]:
    """캡 초과분 묶음 게시: 제목+링크 목록. 4096자 경계에서 메시지 분할."""
    blocks: list[str] = [f"<b>{escape_html(title)}</b>"]
    for it in items:
        t = it.title.strip()
        if len(t) > 300:  # 단일 블록이 분할 한도를 넘지 않게 원문 단계에서 자름
            t = t[:297] + "..."
        url = it.url
        if len(url) > 1500:  # 비정상적으로 긴 URL은 링크 없이 제목만 (한도 초과 방지)
            blocks.append(f"· {escape_html(t)}")
        else:
            blocks.append(f'· <a href="{escape_html(url)}">{escape_html(t)}</a>')
    if site_url:
        blocks.append(f'<a href="{escape_html(site_url)}">전체 보기</a>')
    return split_blocks(blocks)


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


def link_preview_for(item: Item) -> dict | None:
    """유튜브는 큰 썸네일 카드, 입찰·위원회는 프리뷰 끔, 뉴스는 기본."""
    if item.category == "youtube":
        return {"url": item.url, "prefer_large_media": True}
    if item.category in ("bid", "committee"):
        return {"is_disabled": True}
    return None
