"""수집기 레지스트리: sources.yaml의 type 문자열 → collect 함수."""
from __future__ import annotations

from typing import Callable

from ..config import SourceConfig
from ..models import Item
from . import board, eminwon, narajangteo, naver_news, rss, youtube
from .base import CollectError, RunContext

COLLECTORS: dict[str, Callable[[SourceConfig, RunContext], list[Item]]] = {
    "rss": rss.collect,
    "board": board.collect,
    "eminwon": eminwon.collect,
    "narajangteo": narajangteo.collect,
    "naver_news": naver_news.collect,
    "youtube_rss": youtube.collect_rss,
    "youtube_api": youtube.collect_api,
}

__all__ = ["COLLECTORS", "CollectError", "RunContext"]
