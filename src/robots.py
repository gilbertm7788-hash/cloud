"""robots.txt 준수 — 크롤링 대상 사이트의 수집 정책을 확인하고 따른다.

법적 구속력이 명확한 규범은 아니지만, 무시했다는 사실 자체가 분쟁 시 불리하게
작용한다. 공개 게시판을 읽는 것만으로 위법이 되기는 어려워도, 사이트가 명시적으로
거부한 경로를 계속 긁는 것은 다른 문제다.

설계:
- 호스트별로 robots.txt를 1회만 받아 프로세스 내 캐시 (run 단위)
- 받지 못하면(404·타임아웃·연결 실패) 허용으로 간주 — 표준 관행
- Crawl-delay가 선언돼 있으면 그만큼, 없으면 DEFAULT_DELAY만큼 호스트별로 대기
"""
from __future__ import annotations

import logging
import time
import urllib.robotparser
from urllib.parse import urlsplit

from .httpio import DEFAULT_UA, fetch_bytes

log = logging.getLogger(__name__)

# robots.txt에 Crawl-delay가 없을 때 호스트당 최소 요청 간격 (초)
DEFAULT_DELAY = 1.0
# Crawl-delay를 그대로 따르되 이 값을 넘으면 수집이 불가능해지므로 상한을 둔다
MAX_DELAY = 10.0
ROBOTS_TIMEOUT = 10.0

_parsers: dict[str, urllib.robotparser.RobotFileParser | None] = {}
_last_request: dict[str, float] = {}


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def _parser_for(url: str, *, verify_tls: bool = True):
    """호스트의 robots.txt를 받아 파서를 돌려준다. 실패하면 None(=허용)."""
    origin = _origin(url)
    if origin in _parsers:
        return _parsers[origin]

    parser = None
    try:
        content, charset = fetch_bytes(
            f"{origin}/robots.txt", timeout=ROBOTS_TIMEOUT,
            retries=1, verify_tls=verify_tls,
        )
    except Exception as exc:  # noqa: BLE001 — 못 받으면 허용으로 간주
        log.info("robots.txt 없음/실패 (%s): %s — 허용으로 간주", origin, str(exc)[:120])
    else:
        try:
            text = content.decode(charset or "utf-8", errors="replace")
            parser = urllib.robotparser.RobotFileParser()
            parser.parse(text.splitlines())
            log.info("robots.txt 적용: %s", origin)
        except Exception as exc:  # noqa: BLE001 — 파싱 실패도 허용으로 간주
            log.warning("robots.txt 파싱 실패 (%s): %s", origin, str(exc)[:120])
            parser = None

    _parsers[origin] = parser
    return parser


def can_fetch(url: str, *, user_agent: str = DEFAULT_UA, verify_tls: bool = True) -> bool:
    """robots.txt가 이 URL의 수집을 허용하는지. 판단 불가면 True."""
    parser = _parser_for(url, verify_tls=verify_tls)
    if parser is None:
        return True
    try:
        return parser.can_fetch(user_agent, url)
    except Exception:  # noqa: BLE001
        return True


def crawl_delay(url: str, *, user_agent: str = DEFAULT_UA) -> float:
    """이 호스트에 적용할 요청 간격. robots.txt의 Crawl-delay 우선, 없으면 기본값."""
    parser = _parsers.get(_origin(url))
    if parser is not None:
        try:
            declared = parser.crawl_delay(user_agent)
        except Exception:  # noqa: BLE001
            declared = None
        if declared:
            return min(float(declared), MAX_DELAY)
    return DEFAULT_DELAY


def wait_for_host(url: str, *, user_agent: str = DEFAULT_UA) -> None:
    """같은 호스트에 연속 요청할 때 간격을 지킨다. 호스트별로 독립."""
    origin = _origin(url)
    delay = crawl_delay(url, user_agent=user_agent)
    last = _last_request.get(origin)
    if last is not None:
        remaining = delay - (time.monotonic() - last)
        if remaining > 0:
            time.sleep(remaining)
    _last_request[origin] = time.monotonic()


def reset_cache() -> None:
    """테스트용 — 호스트 캐시 초기화."""
    _parsers.clear()
    _last_request.clear()
