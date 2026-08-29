"""type: naver_news — 네이버 뉴스 검색 API (대한경제 등 RSS 없는 제휴 매체 보완).

무료 25,000회/일. Client ID/Secret은 developers.naver.com (신규는 NAVER API HUB 경유 권장).
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlsplit

import httpx

from ..config import SourceConfig
from ..httpio import normalize_url
from ..models import Item, url_hash_key
from .base import CollectError, RunContext

_TAG_RE = re.compile(r"</?b>|&quot;|&amp;|&lt;|&gt;|&apos;")

_ENTITY_MAP = {"&quot;": '"', "&amp;": "&", "&lt;": "<", "&gt;": ">", "&apos;": "'"}


def _clean(text: str) -> str:
    text = re.sub(r"</?b>", "", text or "")
    for ent, ch in _ENTITY_MAP.items():
        text = text.replace(ent, ch)
    return text.strip()


def collect(source: SourceConfig, ctx: RunContext) -> list[Item]:
    client_id = ctx.secrets.get("NAVER_CLIENT_ID")
    client_secret = ctx.secrets.get("NAVER_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise CollectError(f"'{source.id}': NAVER_CLIENT_ID/SECRET 미설정 — 소스 건너뜀")
    query = source.options.get("query")
    if not query:
        raise CollectError(f"'{source.id}': naver_news.query 미설정")
    params = {"query": query, "display": str(source.options.get("display", 50)),
              "sort": "date"}
    headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
    try:
        with httpx.Client(timeout=source.timeout) as client:
            resp = client.get("https://openapi.naver.com/v1/search/news.json",
                              params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise CollectError(f"'{source.id}' 네이버 API 실패: {exc}") from exc

    domain_include = source.options.get("domain_include") or []
    items: list[Item] = []
    for r in data.get("items") or []:
        original = r.get("originallink") or r.get("link") or ""
        if not original:
            continue
        # 호스트 기준 매칭 (경로/쿼리에 도메인 문자열이 섞인 URL 오탐 방지)
        host = urlsplit(original).netloc.lower().rsplit("@", 1)[-1].split(":", 1)[0]
        if domain_include and not any(
            host == d.lower() or host.endswith("." + d.lower()) for d in domain_include
        ):
            continue
        title = _clean(r.get("title") or "")
        if not title:
            continue
        url = normalize_url(original)
        if not url:
            continue
        published_at = None
        if r.get("pubDate"):
            try:
                published_at = datetime.strptime(r["pubDate"], "%a, %d %b %Y %H:%M:%S %z")
            except ValueError:
                pass
        items.append(Item(
            source_id=source.id,
            category=source.category,
            title=title,
            url=url,
            natural_key=url_hash_key(url).removeprefix("url:"),
            key_prefix="nvr",
            summary=_clean(r.get("description") or "") or None,
            published_at=published_at,
            author=source.name,
        ))
    return items
