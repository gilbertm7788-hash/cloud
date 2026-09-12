"""건설 관련 종목 시세 — 다이제스트 머리에 붙는 시황 한 토막.

국내는 공공데이터포털(금융위원회_주식시세정보), 미국은 Finnhub를 쓴다.
아침 7시 30분에 보내는 다이제스트에는 장중 시세가 아니라 '직전 장이 어떻게
끝났나'가 맞는 정보다 — 국내는 전일 종가, 미국은 그날 새벽에 끝난 정규장이다.

미국 시세로 Stooq(키 불필요)를 먼저 썼으나 GitHub 러너에서 봇 차단 페이지가
돌아온다(실측 2026-09). 차단을 우회하는 대신 무료 API 키를 쓰기로 했다.

시세는 부가 정보다. 못 받아온 종목은 조용히 빠지고, 전부 실패하면 섹션이
통째로 사라진다 — 주가 때문에 공고·뉴스 배달이 멈추면 안 된다.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from urllib.parse import unquote, urlencode

from .httpio import fetch_bytes, fetch_via_curl

log = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))

KRX_URL = ("https://apis.data.go.kr/1160100/service/GetStockSecuritiesInfoService"
           "/getStockPriceInfo")
FINNHUB_URL = "https://finnhub.io/api/v1/quote"
# 국내 시세는 날짜 지정 조회라, 연휴·주말을 건너뛰고 최근 거래일을 찾을 구간이 필요하다
# (설·추석 연휴가 가장 길다)
LOOKBACK_DAYS = 12


@dataclass
class Quote:
    name: str
    close: float
    change_pct: float | None
    as_of: date | None
    currency: str = "KRW"


def _to_float(raw) -> float | None:
    try:
        return float(str(raw).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


# ── 국내: 공공데이터포털 금융위원회_주식시세정보 ─────────────────────────────
# DATA_GO_KR_KEY를 재사용하지만 나라장터와는 별개의 활용신청이 필요하다.
# 신청 전이면 SERVICE_KEY_IS_NOT_REGISTERED_ERROR가 오고, 그때는 국내 구간만 빠진다.

def _krx_quote(code: str, name: str, service_key: str, timeout: float) -> Quote | None:
    begin = (datetime.now(KST).date() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y%m%d")
    params = {
        "serviceKey": unquote(service_key),
        "resultType": "json",
        "numOfRows": "20",
        "pageNo": "1",
        "likeSrtnCd": code,
        "beginBasDt": begin,
    }
    raw = fetch_via_curl(f"{KRX_URL}?{urlencode(params)}", timeout=timeout)
    body = json.loads(raw.decode("utf-8", errors="replace"))
    resp = body.get("response") or {}
    result_code = ((resp.get("header") or {}).get("resultCode") or "").strip()
    if result_code not in ("00", "0"):
        msg = (resp.get("header") or {}).get("resultMsg") or result_code
        raise RuntimeError(f"주식시세 API 오류: {msg}")
    items = ((resp.get("body") or {}).get("items") or {}).get("item") or []
    if isinstance(items, dict):
        items = [items]
    # likeSrtnCd는 부분일치라 다른 종목이 섞일 수 있다 — 단축코드 완전일치만 남긴다
    rows = [r for r in items if str(r.get("srtnCd", "")).strip() == code]
    if not rows:
        return None
    row = max(rows, key=lambda r: str(r.get("basDt", "")))
    close = _to_float(row.get("clpr"))
    if close is None:
        return None
    as_of = None
    try:
        as_of = datetime.strptime(str(row.get("basDt")), "%Y%m%d").date()
    except (TypeError, ValueError):
        pass
    return Quote(name=name, close=close, change_pct=_to_float(row.get("fltRt")),
                 as_of=as_of, currency="KRW")


def fetch_kr(tickers: list[dict], service_key: str, timeout: float = 20,
             errors: list[str] | None = None) -> list[Quote]:
    if not service_key:
        log.info("DATA_GO_KR_KEY 없음 — 국내 시세 생략")
        if errors is not None:
            errors.append("국내: DATA_GO_KR_KEY 미설정")
        return []
    quotes: list[Quote] = []
    for t in tickers:
        code, name = str(t.get("code") or "").strip(), str(t.get("name") or "").strip()
        if not code:
            continue
        try:
            q = _krx_quote(code, name or code, service_key, timeout)
        except Exception as exc:  # noqa: BLE001 — 종목 하나가 전체를 막지 않는다
            log.warning("국내 시세 실패 %s: %s", code, str(exc)[:200])
            if errors is not None:
                errors.append(f"국내 {code}: {str(exc)[:200]}")
            continue
        if q:
            quotes.append(q)
    return quotes


# ── 미국: Finnhub /quote (무료 키, 분당 60회) ────────────────────────────────
# 한 번 호출로 현재가와 전일 종가가 같이 오므로 등락률을 바로 계산할 수 있다.
# FINNHUB_API_KEY가 없으면 미국 구간만 조용히 빠진다.

def _finnhub_quote(symbol: str, name: str, api_key: str, timeout: float) -> Quote | None:
    url = f"{FINNHUB_URL}?{urlencode({'symbol': symbol.upper(), 'token': api_key})}"
    content, _ = fetch_bytes(url, timeout=timeout, retries=1)
    body = json.loads(content.decode("utf-8", errors="replace"))
    if isinstance(body, dict) and body.get("error"):
        raise RuntimeError(str(body["error"])[:200])
    close = _to_float(body.get("c"))
    if not close:  # 없는 심볼은 200 OK에 전부 0으로 온다
        raise RuntimeError(f"시세 없음(심볼 확인): {symbol}")
    change = _to_float(body.get("dp"))
    as_of = None
    stamp = _to_float(body.get("t"))
    if stamp:
        as_of = datetime.fromtimestamp(stamp, tz=timezone.utc).astimezone(KST).date()
    return Quote(name=name, close=close, change_pct=change, as_of=as_of, currency="USD")


def fetch_us(tickers: list[dict], api_key: str = "", timeout: float = 20,
             errors: list[str] | None = None) -> list[Quote]:
    if not api_key:
        log.info("FINNHUB_API_KEY 없음 — 미국 시세 생략")
        if errors is not None:
            errors.append("미국: FINNHUB_API_KEY 미설정 (docs/setup-datago.md)")
        return []
    quotes: list[Quote] = []
    for t in tickers:
        symbol = str(t.get("symbol") or "").strip()
        name = str(t.get("name") or "").strip() or symbol
        if not symbol:
            continue
        try:
            q = _finnhub_quote(symbol, name, api_key, timeout)
        except Exception as exc:  # noqa: BLE001
            log.warning("미국 시세 실패 %s: %s", symbol, str(exc)[:200])
            if errors is not None:
                errors.append(f"미국 {symbol}: {str(exc)[:200]}")
            continue
        if q:
            quotes.append(q)
    return quotes


def fetch_quotes(cfg: dict, secrets: dict, timeout: float = 20,
                 errors: list[str] | None = None) -> tuple[list[Quote], list[Quote]]:
    """(국내, 미국) 시세. 설정이 꺼져 있으면 빈 목록.

    errors를 넘기면 종목별 실패 사유가 담긴다 — 진단(smoke-stocks)에서만 쓴다.
    수집 경로에서는 실패를 로그로만 남기고 조용히 지나간다.
    """
    if not cfg or not cfg.get("enabled", True):
        return [], []
    kr = fetch_kr(list(cfg.get("kr") or []), secrets.get("DATA_GO_KR_KEY", ""), timeout, errors)
    us = fetch_us(list(cfg.get("us") or []), secrets.get("FINNHUB_API_KEY", ""),
                  timeout, errors)
    return kr, us
