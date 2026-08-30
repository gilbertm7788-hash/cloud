import re

from src.format_telegram import (
    SAFE_LIMIT,
    escape_html,
    format_digest,
    format_item,
    link_preview_for,
    split_blocks,
)
from src.models import Item


def make_item(**kw) -> Item:
    defaults = dict(
        source_id="s", category="news", title="타이틀 <A&B>", url="https://ex.com/x?a=1",
    )
    defaults.update(kw)
    return Item(**defaults)


def test_escape_html():
    assert escape_html("<b> & 'x'") == "&lt;b&gt; &amp; 'x'"


def test_format_item_escapes_and_links():
    text = format_item(make_item())
    assert "&lt;A&amp;B&gt;" in text
    assert '<a href="https://ex.com/x?a=1">원문 보기</a>' in text
    assert "<b>" in text


def test_format_item_bid_fields():
    item = make_item(category="bid", extra={"org": "조달청", "deadline": "2026-09-15",
                                            "amount": "1,000원"})
    text = format_item(item)
    assert "조달청" in text and "마감 2026-09-15" in text and "추정 1,000원" in text
    assert "공고 보기" in text


def test_format_item_length_bounded():
    item = make_item(title="가" * 6000)
    assert len(format_item(item)) <= SAFE_LIMIT


def test_split_blocks_never_cuts_a_block():
    blocks = [f"줄{i} " + "x" * 100 for i in range(100)]
    msgs = split_blocks(blocks, limit=1000)
    assert all(len(m) <= 1000 for m in msgs)
    # 모든 블록이 온전히 보존됨
    joined = "\n".join(msgs)
    for b in blocks:
        assert b in joined


def test_format_digest_multiple_messages():
    items = [make_item(title=f"공고 {i} " + "y" * 200, url=f"https://ex.com/{i}")
             for i in range(40)]
    msgs = format_digest(items, "모음")
    assert len(msgs) >= 2
    assert all(len(m) <= SAFE_LIMIT for m in msgs)


def test_link_preview():
    assert link_preview_for(make_item(category="youtube"))["prefer_large_media"] is True
    assert link_preview_for(make_item(category="bid"))["is_disabled"] is True
    assert link_preview_for(make_item(category="news")) is None


def test_escape_html_quotes():
    assert escape_html('a "b"') == "a &quot;b&quot;"


def test_overflow_fallback_no_unclosed_tags():
    """한도 초과 폴백이 태그·엔티티를 중간에서 자르지 않아야 함 (텔레그램 400 방지)."""
    item = make_item(title=("가&나<다> " * 800))
    text = format_item(item)
    assert len(text) <= SAFE_LIMIT
    assert text.count("<b>") == text.count("</b>") == 1  # 태그 균형
    assert "원문 보기</a>" in text                        # 링크 보존
    title_line = text.split("\n")[0]
    assert not re.search(r"&[a-zA-Z#0-9]*$", title_line.removesuffix("</b>"))


def test_pathological_long_url_stays_under_limit():
    """URL 자체가 한도를 넘어도 MESSAGE_TOO_LONG(400)이 나지 않아야 함."""
    item = make_item(title="공고", url="https://ex.com/?q=" + "a" * 4300)
    assert len(format_item(item)) <= SAFE_LIMIT


def test_digest_blocks_stay_under_limit_with_long_urls():
    items = [make_item(title=f"공고 {i}", url="https://ex.com/?q=" + "b" * 3000)
             for i in range(5)]
    assert all(len(m) <= SAFE_LIMIT for m in format_digest(items, "모음"))
