"""type: youtube_rss / youtube_api — 유튜브 영상 큐레이션.

기본은 채널 RSS(쿼터 0): https://www.youtube.com/feeds/videos.xml?channel_id=...
youtube_api는 발굴용 search.list (YOUTUBE_API_KEY 있을 때만, 호출당 100유닛).
"""
from __future__ import annotations

import re

import feedparser
import httpx

from ..config import SourceConfig
from ..httpio import fetch_bytes
from ..models import Item
from .base import CollectError, RunContext

_HANGUL_RE = re.compile(r"[가-힣]")


def _has_hangul(text: str) -> bool:
    return bool(_HANGUL_RE.search(text))


def collect_rss(source: SourceConfig, ctx: RunContext) -> list[Item]:
    channel_id = source.options.get("channel_id")
    if not channel_id:
        raise CollectError(f"'{source.id}': youtube.channel_id 미설정")
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        content, _ = fetch_bytes(url, timeout=source.timeout)
    except Exception as exc:  # noqa: BLE001
        raise CollectError(f"'{source.id}' 채널 RSS 실패: {exc}") from exc
    feed = feedparser.parse(content)
    if feed.bozo and not feed.entries:
        raise CollectError(f"'{source.id}' RSS 파싱 실패: {feed.get('bozo_exception')}")
    channel_name = (feed.feed.get("title") or source.name) if feed.feed else source.name
    items: list[Item] = []
    for entry in feed.entries:
        video_id = getattr(entry, "yt_videoid", None)
        link = getattr(entry, "link", "")
        title = (getattr(entry, "title", "") or "").strip()
        if not video_id or not title:
            continue
        items.append(Item(
            source_id=source.id,
            category="youtube",
            title=title,
            url=link or f"https://www.youtube.com/watch?v={video_id}",
            natural_key=video_id,
            key_prefix="yt",
            author=channel_name,
            extra={"channel": channel_name,
                   "thumbnail": f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"},
        ))
    return items


def collect_api(source: SourceConfig, ctx: RunContext) -> list[Item]:
    """search.list 발굴용 — 한국어 키워드 OR 결합, 한글 미포함 제목 필터."""
    api_key = ctx.secrets.get("YOUTUBE_API_KEY")
    if not api_key:
        raise CollectError(f"'{source.id}': YOUTUBE_API_KEY 미설정 — youtube_api 소스는 건너뜀")
    query = source.options.get("query")
    if not query:
        raise CollectError(f"'{source.id}': youtube.query 미설정")
    params = {
        "key": api_key,
        "part": "snippet",
        "q": query,
        "type": "video",
        "order": source.options.get("order", "date"),
        "maxResults": "50",
        "regionCode": "KR",
        "relevanceLanguage": "ko",
    }
    store = ctx.seen_store
    last = store.get_meta(f"yt_search_after:{source.id}")
    if last:
        params["publishedAfter"] = last
    try:
        with httpx.Client(timeout=source.timeout) as client:
            resp = client.get("https://www.googleapis.com/youtube/v3/search", params=params)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise CollectError(f"'{source.id}' search.list 실패: {exc}") from exc

    items: list[Item] = []
    newest: str | None = last
    for r in data.get("items") or []:
        video_id = (r.get("id") or {}).get("videoId")
        snippet = r.get("snippet") or {}
        title = (snippet.get("title") or "").strip()
        if not video_id or not title or not _has_hangul(title):
            continue
        published = snippet.get("publishedAt") or ""
        if published and (newest is None or published > newest):
            newest = published
        items.append(Item(
            source_id=source.id,
            category="youtube",
            title=title,
            url=f"https://www.youtube.com/watch?v={video_id}",
            natural_key=video_id,
            key_prefix="yt",
            author=snippet.get("channelTitle") or source.name,
            extra={"channel": snippet.get("channelTitle"),
                   "thumbnail": f"https://img.youtube.com/vi/{video_id}/mqdefault.jpg"},
        ))
    if newest and ctx.advance_cursor:
        store.set_meta(f"yt_search_after:{source.id}", newest)
    return items
