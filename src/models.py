"""정규화된 콘텐츠 아이템 모델."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

Category = Literal["news", "bid", "committee", "association", "youtube", "gov"]

# 카테고리별 dedup 키 프리픽스와 표시용 이모지/라벨
CATEGORY_META: dict[str, dict[str, str]] = {
    "news": {"emoji": "📰", "label": "뉴스", "hashtag": "#건설뉴스"},
    "bid": {"emoji": "📋", "label": "입찰", "hashtag": "#입찰공고"},
    "committee": {"emoji": "👥", "label": "위원회", "hashtag": "#위원회모집"},
    "association": {"emoji": "🏛", "label": "협회소식", "hashtag": "#협회소식"},
    "youtube": {"emoji": "🎬", "label": "영상", "hashtag": "#건설영상"},
    "gov": {"emoji": "🏢", "label": "정책", "hashtag": "#정책소식"},
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def url_hash_key(normalized_url: str) -> str:
    return "url:" + hashlib.sha1(normalized_url.encode("utf-8")).hexdigest()[:16]


@dataclass(slots=True)
class Item:
    source_id: str
    category: str
    title: str
    url: str  # normalize_url()을 통과한 절대 URL
    natural_key: str | None = None  # 소스별 고유키 (idxno, bidNtceNo-Ord, videoId 등)
    key_prefix: str = ""  # collector가 지정 (예: "rss:ikld", "g2b", "yt")
    summary: str | None = None
    published_at: datetime | None = None  # tz-aware UTC
    author: str | None = None  # 언론사/기관/채널명
    extra: dict = field(default_factory=dict)  # deadline, org, amount, channel, thumbnail...
    fetched_at: datetime = field(default_factory=_utcnow)

    @property
    def dedup_key(self) -> str:
        if self.natural_key and self.key_prefix:
            return f"{self.key_prefix}:{self.natural_key}"
        if self.natural_key:
            return f"{self.source_id}:{self.natural_key}"
        return url_hash_key(self.url)
