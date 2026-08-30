"""소스 검증 리포트 (verify-sources) + 소스 건강 상태 추적."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from .collectors import COLLECTORS, RunContext
from .config import SourceConfig
from .httpio import redact_secrets

HEALTH_PATH = Path("state/source_health.json")
FAIL_ALERT_THRESHOLD = 3  # 연속 실패/0건 경고 기준


@dataclass
class SourceResult:
    source_id: str
    name: str
    ok: bool
    count: int = 0
    samples: list[str] = field(default_factory=list)
    error: str = ""


@dataclass
class SourceReport:
    results: list[SourceResult] = field(default_factory=list)


def verify_sources(sources: list[SourceConfig], ctx: RunContext) -> SourceReport:
    report = SourceReport()
    for source in sources:
        collector = COLLECTORS.get(source.type)
        if collector is None:
            report.results.append(SourceResult(source.id, source.name, False,
                                               error=f"알 수 없는 type {source.type}"))
            continue
        try:
            items = collector(source, ctx)
            report.results.append(SourceResult(
                source.id, source.name, ok=True, count=len(items),
                samples=[it.title[:60] for it in items[:3]],
            ))
        except Exception as exc:  # noqa: BLE001
            # 에러 문자열에는 요청 URL(=API 키)이 섞일 수 있음 — 저장·출력 전에 마스킹
            error = redact_secrets(str(exc), ctx.secrets.values())[:300]
            report.results.append(SourceResult(source.id, source.name, False, error=error))
    return report


def render_report(report: SourceReport) -> str:
    lines = ["# 소스 검증 리포트", "", "| 소스 | 상태 | 건수 | 비고 |", "|---|---|---|---|"]
    for r in report.results:
        status = "✅" if r.ok else "❌"
        note = "; ".join(r.samples) if r.ok else r.error
        lines.append(f"| {r.name} (`{r.source_id}`) | {status} | {r.count} | {note} |")
    return "\n".join(lines)


def write_github_summary(markdown: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(markdown + "\n")


def update_health(results: list[SourceResult]) -> list[str]:
    """연속 실패/0건 카운터 갱신. 경고 대상 소스 id 목록 반환."""
    health: dict = {}
    if HEALTH_PATH.exists():
        try:
            health = json.loads(HEALTH_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            health = {}
    alerts: list[str] = []
    for r in results:
        entry = health.get(r.source_id) or {"consecutive_bad": 0}
        if r.ok and r.count > 0:
            entry["consecutive_bad"] = 0
        else:
            entry["consecutive_bad"] = int(entry.get("consecutive_bad", 0)) + 1
            if entry["consecutive_bad"] == FAIL_ALERT_THRESHOLD:
                alerts.append(r.source_id)
        entry["last_error"] = r.error if not r.ok else ""
        health[r.source_id] = entry
    HEALTH_PATH.parent.mkdir(parents=True, exist_ok=True)
    HEALTH_PATH.write_text(
        json.dumps(health, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return alerts
