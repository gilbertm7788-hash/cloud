from datetime import datetime, timedelta, timezone

from src.collectors.narajangteo import KST, chunk_period, ensure_list, _row_to_item
from src.config import SourceConfig


def g2b_source() -> SourceConfig:
    return SourceConfig(id="g2b_construction", name="나라장터 공사", type="narajangteo",
                        category="bid", options={"operation": "op"})


def test_ensure_list():
    assert ensure_list(None) == []
    assert ensure_list("") == []
    assert ensure_list({"a": 1}) == [{"a": 1}]
    assert ensure_list([1, 2]) == [1, 2]


def test_chunk_period():
    begin = datetime(2026, 8, 1, tzinfo=KST)
    end = begin + timedelta(days=30)
    chunks = chunk_period(begin, end, days=14)
    assert len(chunks) == 3
    assert chunks[0][0] == begin
    assert chunks[-1][1] == end
    for a, b in chunks:
        assert (b - a) <= timedelta(days=14)


def test_row_to_item():
    row = {
        "bidNtceNo": "20260829001",
        "bidNtceOrd": "01",
        "bidNtceNm": "OO대교 건설공사",
        "ntceInsttNm": "부산광역시",
        "bidClseDt": "2026-09-15 17:00:00",
        "bidNtceDt": "2026-08-29 10:00:00",
        "presmptPrce": "1234567890",
        "bidNtceDtlUrl": "https://www.g2b.go.kr/detail?x=1",
    }
    item = _row_to_item(row, g2b_source())
    assert item is not None
    assert item.natural_key == "20260829001-01"
    assert item.dedup_key == "g2b:20260829001-01"
    assert item.extra["org"] == "부산광역시"
    assert item.extra["deadline"] == "2026-09-15 17:00"
    assert "1,234,567,890" in item.extra["amount"]
    assert item.published_at is not None
    assert item.published_at.tzinfo is not None


def test_row_to_item_missing_fields():
    assert _row_to_item({}, g2b_source()) is None
    item = _row_to_item({"bidNtceNo": "1", "bidNtceNm": "x"}, g2b_source())
    assert item is not None
    assert item.natural_key == "1-0"
    assert item.url  # 폴백 URL 생성
