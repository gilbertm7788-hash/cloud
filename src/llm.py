"""선택 모듈: Claude API로 일간 브리핑 요약 생성.

ANTHROPIC_API_KEY가 없으면 조용히 None을 반환하고 호출부가 템플릿으로 폴백한다.
anthropic 패키지는 soft dependency — 함수 내부에서 import.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5"  # LLM_MODEL 환경변수로 교체 가능

_SYSTEM = (
    "당신은 한국 건설(토목·건축) 분야 전문 에디터입니다. "
    "수집된 뉴스·공고 제목 목록을 바탕으로 독자에게 유용한 한국어 브리핑을 씁니다. "
    "원문을 복사하지 말고 자체 문장으로 씁니다. 과장·추측 없이 제목에 담긴 사실만 다룹니다."
)


def summarize_items(item_lines: list[str], *, max_chars: int = 1200) -> str | None:
    """아이템 제목 목록 → 오늘의 헤드라인 요약 문단(2~4문장) + 한줄 코멘트.

    실패·미설정 시 None (호출부 템플릿 폴백).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or not item_lines:
        return None
    try:
        import anthropic
    except ImportError:
        log.warning("anthropic 패키지 미설치 — pip install 'anthropic' 후 사용 가능")
        return None

    model = os.environ.get("LLM_MODEL", DEFAULT_MODEL)
    prompt = (
        "다음은 오늘 수집된 건설 분야 콘텐츠 제목 목록입니다.\n\n"
        + "\n".join(f"- {line}" for line in item_lines[:60])
        + "\n\n이 목록으로 '오늘의 건설 브리핑' 도입부를 작성하세요. "
        "형식: 핵심 흐름 요약 2~4문장 + 실무자 관점 한줄 코멘트. "
        f"{max_chars}자 이내, 마크다운 없이 일반 문장으로."
    )
    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        if response.stop_reason == "refusal":
            log.warning("LLM 요약 거부됨 (stop_reason=refusal)")
            return None
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        return text[:max_chars] or None
    except anthropic.RateLimitError:
        log.warning("LLM 요약 rate limit — 템플릿 폴백")
        return None
    except anthropic.APIStatusError as exc:
        log.warning("LLM 요약 API 오류(%s) — 템플릿 폴백", exc.status_code)
        return None
    except anthropic.APIConnectionError:
        log.warning("LLM 요약 네트워크 오류 — 템플릿 폴백")
        return None
    except Exception:  # noqa: BLE001 — 요약 실패가 파이프라인을 죽이면 안 됨
        log.exception("LLM 요약 예기치 못한 오류 — 템플릿 폴백")
        return None
