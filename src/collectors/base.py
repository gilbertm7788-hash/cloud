"""수집기 공통: RunContext, CollectError."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..config import SiteConfig
from ..dedup import SeenStore


class CollectError(Exception):
    """소스 단위 실패 — run 전체는 계속 진행."""


@dataclass
class RunContext:
    seen_store: SeenStore
    slot: str = "morning"  # morning | noon | evening
    secrets: dict[str, str] = field(default_factory=dict)
    site: SiteConfig = field(default_factory=SiteConfig)
    g2b_mode: str | None = None  # smoke_test 결과 캐시: direct | relay | fail
    advance_cursor: bool = True  # False면 증분 수집 워터마크를 이동하지 않음 (verify/dry-run)
