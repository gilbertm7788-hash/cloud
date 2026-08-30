"""type: narajangteo — 나라장터 입찰공고 오픈 API (조달청_나라장터 입찰공고정보서비스).

- base: https://apis.data.go.kr/1230000/ad/BidPublicInfoService (신버전 'ad' 경로)
- GitHub 호스티드 러너에서 IP 차단 실측 보고 → smoke_test로 direct/relay 자동 판별.
  direct는 curl subprocess(TLS 지문 차단 회피), relay는 Cloudflare Worker 경유.
- 조회기간 15일 초과 제한 → 청킹, resultCode 07 → 기간 이등분 재시도.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import unquote, urlencode

import httpx

from ..config import SourceConfig
from ..httpio import fetch_via_curl, normalize_url, redact_secrets
from ..models import Item
from .base import CollectError, RunContext

log = logging.getLogger(__name__)

BASE_PATH = "/1230000/ad/BidPublicInfoService"
DIRECT_BASE = "https://apis.data.go.kr" + BASE_PATH
KST = timezone(timedelta(hours=9))
CHUNK_DAYS = 14
BOOTSTRAP_HOURS = 48
META_KEY = "last_bid_sync"  # KST YYYYMMDDHHMM


def ensure_list(x) -> list:
    """items가 단일 dict로 오는 응답 방어."""
    if x is None or x == "":
        return []
    if isinstance(x, list):
        return x
    return [x]


def _do_request(url: str, mode: str, relay_secret: str | None, timeout: float) -> bytes:
    if mode == "relay":
        headers = {"X-Relay-Secret": relay_secret or ""}
        with httpx.Client(timeout=timeout) as client:
            resp = client.get(url, headers=headers)
        resp.raise_for_status()
        return resp.content
    return fetch_via_curl(url, timeout=timeout)


def g2b_request(op: str, params: dict, ctx: RunContext, timeout: float = 30) -> dict:
    """오퍼레이션 호출 → 파싱된 body(dict) 반환. resultCode 검사 포함."""
    service_key = ctx.secrets.get("DATA_GO_KR_KEY")
    if not service_key:
        raise CollectError("DATA_GO_KR_KEY 미설정")
    # Encoding 키(%2B 등 포함)든 Decoding 키든 원문으로 통일 — urlencode가 한 번만 인코딩
    service_key = unquote(service_key)
    mode = ctx.g2b_mode
    if mode not in ("direct", "relay"):
        raise CollectError(f"g2b 모드 미확정({mode}) — smoke_test 먼저 수행")
    base = DIRECT_BASE if mode == "direct" else (
        (ctx.secrets.get("G2B_RELAY_URL") or "").rstrip("/") + BASE_PATH
    )
    qs = urlencode({"serviceKey": service_key, "type": "json", **params})
    url = f"{base}/{op}?{qs}"
    try:
        raw = _do_request(url, mode, ctx.secrets.get("G2B_RELAY_SECRET"), timeout)
    except Exception as exc:  # noqa: BLE001
        raise CollectError(
            f"g2b {op} 요청 실패({mode}): "
            f"{redact_secrets(str(exc), ctx.secrets.values())}"
        ) from exc
    text = raw.decode("utf-8", errors="replace")
    try:
        body = json.loads(text)
    except json.JSONDecodeError as exc:
        # 에러가 XML(OpenAPI_ServiceResponse 등)로 오는 경우
        m = re.search(r"<returnReasonCode>(\d+)</returnReasonCode>", text)
        code = m.group(1) if m else "?"
        raise CollectError(
            f"g2b {op} JSON 아님 (returnReasonCode={code}): {text[:200]}"
        ) from exc
    response = body.get("response") or {}
    header = response.get("header") or {}
    result_code = str(header.get("resultCode", "")).strip()
    if result_code == "07":
        raise PeriodTooWideError(op)
    if result_code != "00":
        raise CollectError(
            f"g2b {op} resultCode={result_code}: {header.get('resultMsg')}"
        )
    return response.get("body") or {}


class PeriodTooWideError(Exception):
    pass


def chunk_period(begin: datetime, end: datetime, days: int = CHUNK_DAYS) -> list[tuple[datetime, datetime]]:
    chunks: list[tuple[datetime, datetime]] = []
    cur = begin
    step = timedelta(days=days)
    while cur < end:
        nxt = min(cur + step, end)
        chunks.append((cur, nxt))
        cur = nxt
    return chunks


def _fmt(dt: datetime) -> str:
    return dt.astimezone(KST).strftime("%Y%m%d%H%M")


def _fetch_range(op: str, begin: datetime, end: datetime, extra_params: dict,
                 ctx: RunContext, timeout: float, depth: int = 0) -> list[dict]:
    """한 구간 조회. resultCode 07이면 이등분 재귀 (최대 5단계)."""
    params = {
        "inqryDiv": "1",
        "inqryBgnDt": _fmt(begin),
        "inqryEndDt": _fmt(end),
        "numOfRows": "500",
        "pageNo": "1",
        **extra_params,
    }
    rows: list[dict] = []
    try:
        while True:
            body = g2b_request(op, params, ctx, timeout)
            page_items = ensure_list((body.get("items") or {}).get("item")
                                     if isinstance(body.get("items"), dict)
                                     else body.get("items"))
            rows.extend(page_items)
            total = int(body.get("totalCount") or 0)
            page_no = int(params["pageNo"])
            if page_no * 500 >= total or not page_items:
                break
            params["pageNo"] = str(page_no + 1)
    except PeriodTooWideError:
        if depth >= 5:
            raise CollectError(f"g2b {op}: 기간 분할 한도 초과")
        # 이미 받은 페이지는 버리고 구간을 반씩 나눠 전량 재조회 (중복은 dedup이 처리)
        rows = []
        mid = begin + (end - begin) / 2
        rows += _fetch_range(op, begin, mid, extra_params, ctx, timeout, depth + 1)
        rows += _fetch_range(op, mid, end, extra_params, ctx, timeout, depth + 1)
    return rows


def _row_to_item(row: dict, source: SourceConfig) -> Item | None:
    no = str(row.get("bidNtceNo") or "").strip()
    title = str(row.get("bidNtceNm") or "").strip()
    if not no or not title:
        return None
    ord_ = str(row.get("bidNtceOrd") or "0").strip() or "0"
    # API 응답의 URL도 신뢰하지 않고 스킴 검증 (javascript: 등이 href로 새는 것 방지)
    url = normalize_url(str(row.get("bidNtceDtlUrl") or row.get("bidNtceUrl") or "").strip())
    if not url:
        url = f"https://www.g2b.go.kr:8101/ep/invitation/publish/bidInfoDtl.do?bidno={no}&bidseq={ord_}"
    extra: dict = {}
    if row.get("ntceInsttNm"):
        extra["org"] = row["ntceInsttNm"]
    if row.get("bidClseDt"):
        extra["deadline"] = str(row["bidClseDt"])[:16]
    price = row.get("presmptPrce") or row.get("asignBdgtAmt") or row.get("bdgtAmt")
    if price:
        try:
            extra["amount"] = f"{int(float(price)):,}원"
        except (ValueError, TypeError):
            extra["amount"] = str(price)
    published_at = None
    if row.get("bidNtceDt"):
        try:
            published_at = datetime.strptime(
                str(row["bidNtceDt"])[:16], "%Y-%m-%d %H:%M"
            ).replace(tzinfo=KST)
        except ValueError:
            pass
    return Item(
        source_id=source.id,
        category=source.category,
        title=title,
        url=url,
        natural_key=f"{no}-{ord_}",
        key_prefix="g2b",
        published_at=published_at,
        author=source.name,
        extra=extra,
    )


def smoke_test(ctx: RunContext, timeout: float = 12) -> str:
    """direct → relay 순서로 1건 조회 시도. 결과를 ctx.g2b_mode에 캐시."""
    if ctx.g2b_mode in ("direct", "relay", "fail"):
        return ctx.g2b_mode
    import os
    forced = os.environ.get("G2B_MODE", "auto").lower()
    now = datetime.now(KST)
    probe = {
        "inqryDiv": "1",
        "inqryBgnDt": _fmt(now - timedelta(hours=6)),
        "inqryEndDt": _fmt(now),
        "numOfRows": "1",
        "pageNo": "1",
    }
    candidates = [forced] if forced in ("direct", "relay") else ["direct", "relay"]
    for mode in candidates:
        if mode == "relay" and not ctx.secrets.get("G2B_RELAY_URL"):
            continue
        ctx.g2b_mode = mode
        try:
            g2b_request("getBidPblancListInfoCnstwkPPSSrch", probe, ctx, timeout)
            log.info("g2b smoke: %s OK", mode)
            return mode
        except CollectError as exc:
            log.warning("g2b smoke %s 실패: %s", mode, exc)
    ctx.g2b_mode = "fail"
    return "fail"


def collect(source: SourceConfig, ctx: RunContext) -> list[Item]:
    mode = smoke_test(ctx)
    if mode == "fail":
        raise CollectError(
            "나라장터 접근 불가 (direct·relay 모두 실패) — docs/setup-worker-relay.md 참조"
        )
    op = source.options.get("operation")
    if not op:
        raise CollectError(f"'{source.id}': narajangteo.operation 미설정")
    extra_params = {k: str(v) for k, v in (source.options.get("extra_params") or {}).items()}

    store = ctx.seen_store
    now = datetime.now(KST)
    last = store.get_meta(f"{META_KEY}:{source.id}")
    begin = (
        datetime.strptime(last, "%Y%m%d%H%M").replace(tzinfo=KST)
        if last else now - timedelta(hours=BOOTSTRAP_HOURS)
    )
    if begin >= now:
        return []

    rows: list[dict] = []
    for c_begin, c_end in chunk_period(begin, now):
        rows.extend(_fetch_range(op, c_begin, c_end, extra_params, ctx, source.timeout))

    items = [it for row in rows if (it := _row_to_item(row, source))]
    if ctx.advance_cursor:
        store.set_meta(f"{META_KEY}:{source.id}", _fmt(now))
    return items
