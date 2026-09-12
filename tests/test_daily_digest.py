from datetime import date

from src.format_telegram import PER_SOURCE_CAP, format_daily_digest
from src.models import Item


def item(category, title, *, author="출처", url=None, **extra):
    return Item(source_id="s", category=category, title=title,
                url=url or f"https://ex.com/{abs(hash(title)) % 10**6}",
                natural_key=title[:8], key_prefix="k", author=author, extra=extra)


DAY = date(2026, 9, 11)  # 금요일


def test_header_has_date_and_weekday():
    msgs = format_daily_digest([item("news", "뉴스")], DAY, title="라벤더")
    assert msgs[0].startswith("<b>[라벤더] 2026년 9월 11일 (금)</b>")


def test_empty_input_produces_no_message():
    assert format_daily_digest([], DAY) == []


def test_sections_ordered_by_reader_value():
    items = [item("news", "뉴스"), item("bid", "입찰"), item("committee", "위원회")]
    body = "\n".join(format_daily_digest(items, DAY))
    assert body.index("위원회 모집") < body.index("입찰공고") < body.index("뉴스")


def test_bid_metadata_line_is_rendered():
    items = [item("bid", "OO공사", org="부산청", deadline="2026-09-20 17:00", amount="12억")]
    body = "\n".join(format_daily_digest(items, DAY))
    assert "부산청 · 마감 2026-09-20 17:00 · 추정 12억" in body


def test_item_without_metadata_has_no_empty_meta_line():
    body = "\n".join(format_daily_digest([item("news", "제목만")], DAY))
    assert " · " not in body


def test_news_grouped_by_outlet():
    items = [item("news", "가", author="국토일보"), item("news", "나", author="한국건설신문"),
             item("news", "다", author="국토일보")]
    body = "\n".join(format_daily_digest(items, DAY))
    assert "&lt;국토일보&gt;" in body and "&lt;한국건설신문&gt;" in body


def test_per_outlet_cap_and_omitted_count():
    items = [item("news", f"기사{i}", author="국토일보") for i in range(PER_SOURCE_CAP + 3)]
    body = "\n".join(format_daily_digest(items, DAY))
    assert body.count("▶️") == PER_SOURCE_CAP
    assert "외 3건" in body


def test_bid_section_cap():
    items = [item("bid", f"공사{i}") for i in range(25)]
    body = "\n".join(format_daily_digest(items, DAY))
    assert body.count("▶️") == 20 and "외 5건" in body


def test_committee_section_is_uncapped():
    items = [item("committee", f"위원회{i}") for i in range(40)]
    body = "\n".join(format_daily_digest(items, DAY))
    assert body.count("▶️") == 40 and "외 " not in body


def test_title_is_the_link_and_html_is_escaped():
    items = [item("news", "제목 <b>&amp;</b> 특수문자", url="https://ex.com/a?x=1&y=2")]
    body = "\n".join(format_daily_digest(items, DAY))
    assert '<a href="https://ex.com/a?x=1&amp;y=2">' in body
    assert "&lt;b&gt;" in body


def test_long_title_is_truncated():
    body = "\n".join(format_daily_digest([item("news", "가" * 300)], DAY))
    assert "..." in body and "가" * 250 not in body


def test_splits_across_messages_within_telegram_limit():
    items = [item("committee", f"아주 긴 위원회 공고 제목입니다 {i}" * 4) for i in range(200)]
    msgs = format_daily_digest(items, DAY)
    assert len(msgs) > 1
    assert all(len(m) <= 4096 for m in msgs)


def test_site_link_appended_only_when_configured():
    with_url = "\n".join(format_daily_digest([item("news", "가")], DAY, "https://site.example"))
    without = "\n".join(format_daily_digest([item("news", "가")], DAY, ""))
    assert "전체 공고·아카이브" in with_url
    assert "전체 공고·아카이브" not in without


def test_pathological_url_falls_back_to_plain_title():
    """URL 하나가 한도를 넘어도 메시지가 4096자를 넘지 않아야 한다."""
    from src.format_telegram import SAFE_LIMIT
    huge = "https://ex.com/?q=" + "x" * (SAFE_LIMIT + 500)
    msgs = format_daily_digest([item("news", "정상 제목", url=huge)], DAY)
    body = "\n".join(msgs)
    assert all(len(m) <= 4096 for m in msgs)
    assert "정상 제목" in body and huge not in body
