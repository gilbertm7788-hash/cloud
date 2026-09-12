import json
from datetime import date

import pytest

from src import stocks
from src.format_telegram import format_quotes, format_daily_digest
from src.models import Item


def _krx_payload(rows, result_code="00"):
    return json.dumps({"response": {
        "header": {"resultCode": result_code, "resultMsg": "OK"},
        "body": {"items": {"item": rows}},
    }}).encode()


def test_krx_picks_latest_trading_day(monkeypatch):
    rows = [
        {"basDt": "20260910", "srtnCd": "000720", "clpr": "31000", "fltRt": "-1.0"},
        {"basDt": "20260911", "srtnCd": "000720", "clpr": "32450", "fltRt": "2.1"},
    ]
    monkeypatch.setattr(stocks, "fetch_via_curl", lambda url, **kw: _krx_payload(rows))
    q = stocks._krx_quote("000720", "현대건설", "KEY", 10)
    assert (q.close, q.change_pct, q.as_of) == (32450.0, 2.1, date(2026, 9, 11))


def test_krx_ignores_other_codes_from_like_match(monkeypatch):
    """likeSrtnCd는 부분일치라 다른 종목이 섞여 온다 — 완전일치만 남아야 한다."""
    rows = [
        {"basDt": "20260911", "srtnCd": "0007201", "clpr": "999", "fltRt": "9.9"},
        {"basDt": "20260911", "srtnCd": "000720", "clpr": "32450", "fltRt": "2.1"},
    ]
    monkeypatch.setattr(stocks, "fetch_via_curl", lambda url, **kw: _krx_payload(rows))
    assert stocks._krx_quote("000720", "현대건설", "KEY", 10).close == 32450.0


def test_krx_error_code_raises(monkeypatch):
    monkeypatch.setattr(stocks, "fetch_via_curl",
                        lambda url, **kw: _krx_payload([], result_code="30"))
    with pytest.raises(RuntimeError):
        stocks._krx_quote("000720", "현대건설", "KEY", 10)


def test_one_bad_ticker_does_not_sink_the_rest(monkeypatch):
    def fake(url, **kw):
        if "000720" in url:
            raise RuntimeError("타임아웃")
        return _krx_payload([{"basDt": "20260911", "srtnCd": "028260",
                              "clpr": "154300", "fltRt": "-0.45"}])
    monkeypatch.setattr(stocks, "fetch_via_curl", fake)
    got = stocks.fetch_kr([{"code": "000720", "name": "현대건설"},
                           {"code": "028260", "name": "삼성물산"}], "KEY")
    assert [q.name for q in got] == ["삼성물산"]


def test_no_key_means_no_domestic_quotes(monkeypatch):
    called = []
    monkeypatch.setattr(stocks, "fetch_via_curl", lambda *a, **k: called.append(1))
    assert stocks.fetch_kr([{"code": "000720", "name": "현대건설"}], "") == []
    assert not called


def _finnhub(body):
    import json
    return json.dumps(body).encode(), "utf-8"


def test_finnhub_quote_carries_price_and_change(monkeypatch):
    monkeypatch.setattr(stocks, "fetch_bytes", lambda url, **kw: _finnhub(
        {"c": 412.0, "d": 12.0, "dp": 3.0, "pc": 400.0, "t": 1789171200}))
    q = stocks._finnhub_quote("CAT", "캐터필러", "KEY", 10)
    assert q.close == 412.0
    assert q.change_pct == pytest.approx(3.0)
    assert q.currency == "USD"
    assert q.as_of is not None


def test_unknown_symbol_comes_back_as_zeros_not_an_error(monkeypatch):
    """없는 심볼도 200 OK에 전부 0으로 온다 — 0원짜리 종목을 싣지 않아야 한다."""
    monkeypatch.setattr(stocks, "fetch_bytes", lambda url, **kw: _finnhub(
        {"c": 0, "d": None, "dp": None, "pc": 0, "t": 0}))
    with pytest.raises(RuntimeError):
        stocks._finnhub_quote("NOPE", "없음", "KEY", 10)


def test_finnhub_error_payload_raises(monkeypatch):
    monkeypatch.setattr(stocks, "fetch_bytes",
                        lambda url, **kw: _finnhub({"error": "Invalid API key"}))
    with pytest.raises(RuntimeError):
        stocks._finnhub_quote("CAT", "캐터필러", "KEY", 10)


def test_no_us_key_means_no_us_quotes(monkeypatch):
    monkeypatch.setattr(stocks, "fetch_bytes", lambda *a, **k: pytest.fail("호출되면 안 됨"))
    assert stocks.fetch_us([{"symbol": "CAT", "name": "캐터필러"}], "") == []


def test_one_bad_us_ticker_does_not_sink_the_rest(monkeypatch):
    def fake(url, **kw):
        if "symbol=CAT" in url:
            raise RuntimeError("429 rate limit")
        return _finnhub({"c": 300.0, "dp": -1.0, "t": 1789171200})
    monkeypatch.setattr(stocks, "fetch_bytes", fake)
    got = stocks.fetch_us([{"symbol": "CAT", "name": "캐터필러"},
                           {"symbol": "PWR", "name": "콴타서비스"}], "KEY")
    assert [q.name for q in got] == ["콴타서비스"]


def test_disabled_config_skips_everything(monkeypatch):
    monkeypatch.setattr(stocks, "fetch_via_curl", lambda *a, **k: pytest.fail("호출되면 안 됨"))
    monkeypatch.setattr(stocks, "fetch_bytes", lambda *a, **k: pytest.fail("호출되면 안 됨"))
    assert stocks.fetch_quotes({"enabled": False, "kr": [{"code": "1"}]}, {}) == ([], [])


# ── 표시 ────────────────────────────────────────────────────────────────────

def _q(name, close, pct, cur="KRW"):
    return stocks.Quote(name=name, close=close, change_pct=pct,
                        as_of=date(2026, 9, 11), currency=cur)


def test_quote_block_shows_direction_and_currency():
    blocks = format_quotes([_q("현대건설", 32450, 2.1)], [_q("캐터필러", 412.3, -1.2, "USD")])
    text = "\n".join(blocks)
    assert "현대건설 32,450 ▲2.10%" in text
    assert "캐터필러 $412.30 ▼1.20%" in text
    assert "9/11 종가" in text


def test_unknown_change_is_not_rendered_as_zero():
    assert "―" in "\n".join(format_quotes([_q("현대건설", 32450, None)], []))


def test_empty_quotes_add_nothing():
    assert format_quotes([], []) == []


def test_quotes_sit_above_the_first_section():
    items = [Item(source_id="ikld", category="news", title="테스트 기사",
                  url="https://example.com/1", author="국토일보")]
    msgs = format_daily_digest(items, date(2026, 9, 12), "https://example.com",
                               quotes=([_q("현대건설", 32450, 2.1)], []))
    first = msgs[0]
    assert first.index("현대건설") < first.index("📰 뉴스")


def test_digest_without_quotes_is_unchanged():
    items = [Item(source_id="ikld", category="news", title="테스트 기사",
                  url="https://example.com/1", author="국토일보")]
    assert "📈" not in "\n".join(format_daily_digest(items, date(2026, 9, 12), ""))
