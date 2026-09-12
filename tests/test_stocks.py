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


def test_stooq_computes_change_from_last_two_sessions(monkeypatch):
    csv_text = ("Date,Open,High,Low,Close,Volume\n"
                "2026-09-10,400,410,399,400.00,100\n"
                "2026-09-11,401,415,400,412.00,120\n")
    monkeypatch.setattr(stocks, "fetch_bytes", lambda url, **kw: (csv_text.encode(), "utf-8"))
    q = stocks._stooq_quote("CAT", "캐터필러", 10)
    assert q.close == 412.0
    assert q.change_pct == pytest.approx(3.0)
    assert q.as_of == date(2026, 9, 11)
    assert q.currency == "USD"


def test_stooq_single_session_leaves_change_unknown(monkeypatch):
    csv_text = "Date,Open,High,Low,Close,Volume\n2026-09-11,401,415,400,412.00,120\n"
    monkeypatch.setattr(stocks, "fetch_bytes", lambda url, **kw: (csv_text.encode(), "utf-8"))
    assert stocks._stooq_quote("CAT", "캐터필러", 10).change_pct is None


def test_stooq_non_csv_response_is_an_error(monkeypatch):
    """한도 초과·없는 심볼은 200 OK에 안내 문구로 돌아온다 — 조용히 통과하면 안 된다."""
    monkeypatch.setattr(stocks, "fetch_bytes",
                        lambda url, **kw: (b"Exceeded the daily hits limit", "utf-8"))
    with pytest.raises(RuntimeError):
        stocks._stooq_quote("CAT", "캐터필러", 10)


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
