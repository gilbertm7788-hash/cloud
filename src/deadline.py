"""마감일 추출: 입찰은 API 필드 직접, 위원회·게시판 공고는 제목 텍스트에서 best-effort.

정확도보다 재현율 우선 — 미추출 건은 사이트에서 "마감 확인 필요" 배지로 표시.
"""
from __future__ import annotations

import re
from datetime import date, datetime

# "~9.15", "~ 9/15", "9월 15일까지", "9.15.까지", "접수기간: 8.20 ~ 9.15", "~2026.9.15"
_PATTERNS = [
    # 연도 포함: 2026.9.15 / 2026-09-15 / 2026년 9월 15일
    re.compile(r"(20\d{2})[.\-/년]\s*(\d{1,2})[.\-/월]\s*(\d{1,2})"),
    # "~9.15" / "~ 9/15" / "~9.15." (물결표 뒤)
    re.compile(r"[~∼～]\s*(\d{1,2})[.\-/월]\s*(\d{1,2})"),
    # "9월 15일까지" / "9.15까지" / "9.15.까지"
    re.compile(r"(\d{1,2})[.\-/월]\s*(\d{1,2})\s*일?\s*\.?\s*까지"),
]


def _valid(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def extract_deadline(text: str, *, today: date | None = None) -> date | None:
    """제목/본문 텍스트에서 마감일 추출.

    - 연도 포함 날짜 중 마지막 유효 매치를 기준 후보로 잡되,
      그 뒤에 오는 연도 없는 마감 표기("~9.15", "9월 15일까지")가 있으면 그것이 우선
      (기간 표기 "2026.8.20 ~ 9.15"에서 시작일이 아니라 종료일을 잡기 위함)
    - 연도가 없으면 기준일(연도 매치 또는 오늘)로 추정, 6개월 이상 과거면 해 넘김 처리
    """
    if not text:
        return None
    today = today or date.today()

    year_candidate: date | None = None
    year_end = -1
    for m in reversed(list(_PATTERNS[0].finditer(text))):
        y, mo, d = (int(g) for g in m.groups())
        parsed = _valid(y, mo, d)
        if parsed is not None:  # 무효한 연도 날짜는 건너뛰고 이전 매치·다른 패턴으로 폴백
            year_candidate = parsed
            year_end = m.end()
            break

    anchor = year_candidate or today
    for pattern in _PATTERNS[1:]:
        matches = [m for m in pattern.finditer(text) if m.start() >= year_end]
        if not matches:
            continue
        mo, d = (int(g) for g in matches[-1].groups())
        candidate = _valid(anchor.year, mo, d)
        if candidate is None:
            continue
        if (anchor - candidate).days > 180:  # 과거로 크게 밀리면 해 넘김으로 판단
            candidate = _valid(anchor.year + 1, mo, d) or candidate
        return candidate
    return year_candidate


def parse_deadline_str(value: str) -> date | None:
    """extra.deadline 문자열(예: '2026-09-15 17:00', '2026.9.15') → date."""
    if not value:
        return None
    value = str(value).strip()
    m = re.match(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})", value)
    if m:
        y, mo, d = (int(g) for g in m.groups())
        return _valid(y, mo, d)
    try:
        return datetime.fromisoformat(value[:10]).date()
    except ValueError:
        return None
