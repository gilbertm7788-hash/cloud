"""sources.yaml + 환경변수 로드·검증."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

VALID_TYPES = {"rss", "board", "eminwon", "narajangteo", "naver_news",
               "youtube_rss", "youtube_api"}
VALID_CATEGORIES = {"news", "bid", "committee", "association", "youtube", "gov"}
VALID_SLOTS = {"morning", "noon", "evening"}

# 시크릿으로 취급하는 환경변수 목록
SECRET_ENV_KEYS = [
    "TELEGRAM_BOT_TOKEN", "TELEGRAM_STAGING_CHAT_ID", "TELEGRAM_ADMIN_CHAT_ID",
    "DATA_GO_KR_KEY", "G2B_RELAY_URL", "G2B_RELAY_SECRET",
    "NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET",
    "YOUTUBE_API_KEY", "ANTHROPIC_API_KEY",
]


class ConfigError(Exception):
    pass


@dataclass(slots=True)
class SourceConfig:
    id: str
    name: str
    type: str
    category: str
    enabled: bool = True
    slots: list[str] = field(default_factory=lambda: ["morning", "noon", "evening"])
    filters: dict = field(default_factory=dict)
    options: dict = field(default_factory=dict)  # type별 설정 블록 (rss/board/... 키의 내용)
    max_new_per_run: int = 10
    timeout: float = 20


@dataclass(slots=True)
class SiteConfig:
    base_url: str = ""
    title: str = "건설 인사이트"
    description: str = "건설·토목·건축 뉴스, 입찰공고, 위원회 모집 큐레이션"
    telegram_channel_url: str = ""  # 공개 채널 URL — 비어 있으면 버튼 미표시


@dataclass(slots=True)
class AppConfig:
    sources: list[SourceConfig]
    site: SiteConfig
    defaults: dict
    secrets: dict[str, str]
    stocks: dict  # 다이제스트 시세 섹션 설정 (종목 목록은 코드가 아니라 YAML에)


def _require(d: dict, key: str, src_label: str):
    if key not in d or d[key] in (None, ""):
        raise ConfigError(f"소스 '{src_label}': 필수 필드 '{key}' 누락")
    return d[key]


def load_config(path: Path | str = Path("config/sources.yaml")) -> AppConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    defaults = raw.get("defaults") or {}
    site_raw = raw.get("site") or {}
    site_defaults = SiteConfig()  # slots=True 클래스 속성은 디스크립터라 인스턴스에서 기본값을 읽음
    site = SiteConfig(
        base_url=(site_raw.get("base_url") or "").rstrip("/"),
        title=site_raw.get("title") or site_defaults.title,
        description=site_raw.get("description") or site_defaults.description,
        telegram_channel_url=site_raw.get("telegram_channel_url") or "",
    )

    default_exclude = [str(k) for k in (defaults.get("keyword_exclude") or [])]
    sources: list[SourceConfig] = []
    seen_ids: set[str] = set()
    for entry in raw.get("sources") or []:
        sid = _require(entry, "id", entry.get("id", "?"))
        if sid in seen_ids:
            raise ConfigError(f"소스 id 중복: '{sid}'")
        seen_ids.add(sid)
        stype = _require(entry, "type", sid)
        if stype not in VALID_TYPES:
            raise ConfigError(f"소스 '{sid}': 알 수 없는 type '{stype}' (허용: {sorted(VALID_TYPES)})")
        category = _require(entry, "category", sid)
        if category not in VALID_CATEGORIES:
            raise ConfigError(f"소스 '{sid}': 알 수 없는 category '{category}'")
        slots = entry.get("slots") or sorted(VALID_SLOTS)
        bad_slots = set(slots) - VALID_SLOTS
        if bad_slots:
            raise ConfigError(f"소스 '{sid}': 알 수 없는 slot {sorted(bad_slots)}")
        # type별 옵션 블록: 키 이름은 type과 동일 (youtube_rss/youtube_api는 'youtube' 공용)
        opt_key = "youtube" if stype.startswith("youtube") else stype
        options = entry.get(opt_key) or {}
        filters = dict(entry.get("filters") or {})
        if default_exclude:  # 전역 제외어(부고·인사 등)를 소스별 제외어 앞에 병합
            filters["keyword_exclude"] = default_exclude + list(filters.get("keyword_exclude") or [])
        sources.append(SourceConfig(
            id=sid,
            name=entry.get("name") or sid,
            type=stype,
            category=category,
            enabled=bool(entry.get("enabled", True)),
            slots=list(slots),
            filters=filters,
            options=options,
            max_new_per_run=int(entry.get("max_new_per_run",
                                          defaults.get("max_new_per_run", 10))),
            timeout=float(entry.get("timeout", defaults.get("timeout", 20))),
        ))

    secrets = {k: v for k in SECRET_ENV_KEYS if (v := os.environ.get(k))}
    return AppConfig(sources=sources, site=site, defaults=defaults, secrets=secrets,
                     stocks=raw.get("stocks") or {})


def apply_keyword_filters(title: str, filters: dict) -> bool:
    """True면 통과. include가 비어 있으면 전체 통과, exclude 우선 적용."""
    for kw in filters.get("keyword_exclude") or []:
        if kw in title:
            return False
    include = filters.get("keyword_include") or []
    if include:
        return any(kw in title for kw in include)
    return True
