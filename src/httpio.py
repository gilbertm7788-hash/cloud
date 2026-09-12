"""HTTP 공통 계층: 인코딩 감지, 재시도, curl 폴백, URL 정규화."""
from __future__ import annotations

import logging
import re
import subprocess
import time
from collections.abc import Iterable
from urllib.parse import unquote, urlsplit, urlunsplit

import httpx

log = logging.getLogger(__name__)

DEFAULT_UA = (
    "Mozilla/5.0 (compatible; LavenderBot/1.0; "
    "+https://lavender-kr-official.github.io/about.html)"
)

_META_CHARSET_RE = re.compile(
    rb"""<meta[^>]+charset\s*=\s*["']?\s*([a-zA-Z0-9_-]+)""", re.IGNORECASE
)
# 세션 ID 세그먼트 (;jsessionid=... 형태, 경로 뒤에 붙음)
_JSESSIONID_PATH_RE = re.compile(r";jsessionid=[^?#/]*", re.IGNORECASE)
_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term",
                    "utm_content", "fbclid", "gclid", "igshid"}
# 세션 토큰만 — sid/sessionid는 한국 게시판에서 글 식별자로 쓰이므로 제거하지 않는다
_SESSION_PARAMS = {"jsessionid", "phpsessid", "aspsessionid"}


def decode_body(content: bytes, http_charset: str | None, encoding: str = "auto") -> str:
    """3단 인코딩 감지: 명시 오버라이드 → HTTP 헤더 → <meta charset> → cp949 → utf-8."""
    if encoding and encoding != "auto":
        return content.decode(encoding, errors="replace")
    candidates: list[str] = []
    if http_charset:
        candidates.append(http_charset)
    m = _META_CHARSET_RE.search(content[:4096])
    if m:
        candidates.append(m.group(1).decode("ascii", errors="ignore"))
    failed: list[str] = []
    for cand in candidates:
        norm = cand.strip().lower()
        if norm in ("euc-kr", "euc_kr", "ks_c_5601-1987", "ksc5601", "cp949", "ms949"):
            norm = "cp949"  # euc-kr의 확장 — 한글 커버리지가 더 넓음
        try:
            return content.decode(norm)
        except LookupError:
            continue
        except UnicodeDecodeError:
            # 다음 후보(<meta charset> 등)를 먼저 시도 — 헤더 charset이 틀린 사이트가 흔함.
            # 모든 후보가 실패하면 아래에서 첫 후보 + replace로 복구.
            failed.append(norm)
            continue
    # 후보가 모두 디코드 실패: 선언된 첫 인코딩 + replace (일부 바이트만 깨진 경우 보존율이 높음)
    if failed:
        return content.decode(failed[0], errors="replace")
    # 단서가 아예 없을 때만 utf-8 → cp949 휴리스틱
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError:
        return content.decode("cp949", errors="replace")


def fetch_bytes(
    url: str,
    *,
    timeout: float = 20,
    retries: int = 2,
    verify_tls: bool = True,
    headers: dict | None = None,
    method: str = "GET",
    data: dict | None = None,
) -> tuple[bytes, str | None]:
    """(body, http_charset) 반환. 5xx·타임아웃만 지수 백오프 재시도."""
    hdrs = {"User-Agent": DEFAULT_UA}
    if headers:
        hdrs.update(headers)
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with httpx.Client(
                timeout=timeout, verify=verify_tls, follow_redirects=True
            ) as client:
                resp = client.request(method, url, headers=hdrs, data=data)
            if resp.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"server error {resp.status_code}", request=resp.request, response=resp
                )
            resp.raise_for_status()
            return resp.content, resp.charset_encoding
        except (httpx.TimeoutException, httpx.HTTPStatusError, httpx.TransportError) as exc:
            last_exc = exc
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                raise  # 4xx는 재시도 무의미
            if attempt < retries:
                time.sleep(2 ** attempt)
    raise last_exc  # type: ignore[misc]


def fetch_text(
    url: str,
    *,
    encoding: str = "auto",
    timeout: float = 20,
    retries: int = 2,
    verify_tls: bool = True,
    headers: dict | None = None,
    method: str = "GET",
    data: dict | None = None,
) -> str:
    content, charset = fetch_bytes(
        url, timeout=timeout, retries=retries, verify_tls=verify_tls,
        headers=headers, method=method, data=data,
    )
    return decode_body(content, charset, encoding)


def fetch_via_curl(url: str, *, headers: dict | None = None, timeout: float = 30) -> bytes:
    """curl subprocess 경로 — data.go.kr TLS 지문 차단 대응. URL은 리스트 인자로만 전달."""
    cmd = ["curl", "-sS", "--fail-with-body", "--max-time", str(int(timeout)),
           "-A", DEFAULT_UA, "-L"]
    for k, v in (headers or {}).items():
        cmd += ["-H", f"{k}: {v}"]
    cmd.append(url)
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout + 10)
    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace")[:300]
        # --fail-with-body 덕분에 HTTP 4xx/5xx여도 응답 본문이 stdout에 남는다.
        # 차단 페이지인지 API 레벨 오류인지는 이 본문에만 드러나므로 함께 올린다.
        body = re.sub(r"\s+", " ", proc.stdout.decode("utf-8", errors="replace")).strip()[:300]
        detail = f"{stderr} | 응답본문: {body}" if body else stderr
        raise RuntimeError(f"curl exit {proc.returncode}: {detail}")
    return proc.stdout


def normalize_url(url: str) -> str:
    """dedup·게시용 URL 정규화: jsessionid/트래킹 파라미터 제거, fragment 제거, 쿼리 정렬.

    - 쿼리 값은 절대 언쿼트하지 않음: EUC-KR 등 비UTF-8 퍼센트 인코딩을 그대로 보존
      (parse_qsl/urlencode 왕복은 %C7%D1 같은 값을 U+FFFD로 파괴함)
    - http/https 외 스킴(javascript: 등)은 빈 문자열 반환 — 수집기가 해당 아이템을 버림
    """
    url = _JSESSIONID_PATH_RE.sub("", url.strip())
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https"):
        return ""
    raw_pairs = [f.partition("=") for f in parts.query.split("&") if f]
    kept = sorted(
        (k, sep, v) for k, sep, v in raw_pairs
        if unquote(k).lower() not in _TRACKING_PARAMS
        and unquote(k).lower() not in _SESSION_PARAMS
    )
    query = "&".join(k + sep + v for k, sep, v in kept)
    return urlunsplit((
        parts.scheme.lower(),
        parts.netloc.lower(),
        parts.path,
        query,
        "",  # fragment 제거
    ))


_CRED_PARAM_RE = re.compile(
    r"([?&](?:serviceKey|key|api_?key|access_token|token|secret|client_secret)=)[^&\s'\"]+",
    re.IGNORECASE,
)


def redact_secrets(text: str, extra_values: Iterable[str] = ()) -> str:
    """외부로 나가는 문자열(로그·알림·커밋되는 파일)에서 시크릿 마스킹.

    - extra_values: 설정된 시크릿의 실제 값들. 정규식이 예상 못한 형태도 값 자체로 잡는다.
    - 그 외 credential성 쿼리 파라미터와 봇 토큰은 패턴으로 마스킹.
    """
    for value in extra_values:
        if value and len(value) >= 8:  # 짧은 값은 오탐 위험이 커서 제외
            text = text.replace(value, "***")
    text = _CRED_PARAM_RE.sub(r"\1***", text)
    text = re.sub(r"(bot)\d+:[A-Za-z0-9_-]{30,}", r"\1***", text)
    return text
