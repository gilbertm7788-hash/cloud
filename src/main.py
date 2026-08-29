"""파이프라인 CLI 진입점.

  python -m src.main collect [--slot morning|noon|evening] [--sources a,b] [--dry-run] [--no-post]
  python -m src.main verify-sources
  python -m src.main smoke-g2b
  python -m src.main blog-draft [--date YYYY-MM-DD]
  python -m src.main build-site
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta, timezone

from .blog_draft import build_draft, write_draft
from .collectors import COLLECTORS, CollectError, RunContext
from .collectors import narajangteo
from .config import AppConfig, apply_keyword_filters, load_config
from .dedup import SeenStore
from .format_telegram import format_digest, format_item, link_preview_for
from .models import CATEGORY_META, Item
from .report import SourceResult, render_report, update_health, verify_sources, write_github_summary
from .site_build import build_site
from .telegram_client import TelegramClient, TelegramError

log = logging.getLogger("pipeline")
KST = timezone(timedelta(hours=9))
BOOTSTRAP_POST_LIMIT = 3


def current_slot(now: datetime | None = None) -> str:
    """cron 지연에 강건하게, 실행 시각의 KST 기준으로 슬롯 결정."""
    hour = (now or datetime.now(KST)).astimezone(KST).hour
    if hour < 10:
        return "morning"
    if hour < 15:
        return "noon"
    return "evening"


def _make_ctx(cfg: AppConfig, slot: str) -> RunContext:
    return RunContext(
        seen_store=SeenStore(),
        slot=slot,
        secrets=cfg.secrets,
        site=cfg.site,
    )


def _telegram(cfg: AppConfig) -> tuple[TelegramClient | None, str]:
    token = cfg.secrets.get("TELEGRAM_BOT_TOKEN")
    chat_id = cfg.secrets.get("TELEGRAM_STAGING_CHAT_ID") or ""
    if not token or not chat_id:
        return None, chat_id
    return TelegramClient(token), chat_id


def _notify(cfg: AppConfig, tg: TelegramClient | None, text: str) -> None:
    if tg is None:
        log.error("알림 전송 불가(토큰 미설정): %s", text)
        return
    admin = cfg.secrets.get("TELEGRAM_ADMIN_CHAT_ID")
    chat_id = admin or cfg.secrets.get("TELEGRAM_STAGING_CHAT_ID") or ""
    if chat_id:
        tg.notify_error(chat_id, text)


def _item_from_row(row: dict) -> Item:
    """pending 재시도용: seen 테이블 row를 포맷팅 가능한 Item으로 복원."""
    return Item(
        source_id=row.get("source_id") or "",
        category=row.get("category") or "news",
        title=row.get("title") or "",
        url=row.get("url") or "",
        author=row.get("author"),
        extra=row.get("extra") or {},
    )


def _retry_pending(store, tg: TelegramClient, staging_chat: str, site_url: str,
                   errors: list[str]) -> int:
    """이전 run에서 게시 실패한 아이템 재시도."""
    sent = 0
    for row in store.pending(limit=25):
        item = _item_from_row(row)
        if not item.title or not item.url:
            store.mark_posted(row["id"], None)  # 복원 불가 row는 재시도 루프에서 제거
            continue
        try:
            mid = tg.send_message(staging_chat, format_item(item, site_url),
                                  link_preview_for(item))
            store.mark_posted(row["id"], mid)
            sent += 1
        except TelegramError as exc:
            errors.append(f"pending 재시도 실패({row['id']}): {exc}")
            break
    return sent


def run_collect(args: argparse.Namespace) -> int:
    cfg = load_config()
    slot = args.slot or current_slot()
    ctx = _make_ctx(cfg, slot)
    ctx.advance_cursor = not args.dry_run  # dry-run은 증분 워터마크를 움직이지 않음
    store = ctx.seen_store
    tg, staging_chat = _telegram(cfg)
    posting = not (args.dry_run or args.no_post)
    if posting and tg is None:
        log.error("TELEGRAM_BOT_TOKEN/TELEGRAM_STAGING_CHAT_ID 미설정 — --no-post로 실행하거나 시크릿을 등록하세요")
        return 1

    wanted = set(args.sources.split(",")) if args.sources else None
    sources = [
        s for s in cfg.sources
        if s.enabled and slot in s.slots and (wanted is None or s.id in wanted)
    ]
    log.info("slot=%s, 대상 소스 %d개", slot, len(sources))

    errors: list[str] = []
    health_results: list[SourceResult] = []
    posted_total = 0
    site_url = cfg.site.base_url

    # 이전 run에서 게시 실패한 아이템부터 재시도
    if posting and tg is not None:
        posted_total += _retry_pending(store, tg, staging_chat, site_url, errors)

    for source in sources:
        collector = COLLECTORS.get(source.type)
        if collector is None:
            errors.append(f"{source.id}: 알 수 없는 type {source.type}")
            continue
        try:
            items = collector(source, ctx)
        except CollectError as exc:
            log.warning("소스 실패 %s: %s", source.id, exc)
            errors.append(f"{source.id}: {exc}")
            health_results.append(SourceResult(source.id, source.name, False, error=str(exc)[:300]))
            continue
        except Exception as exc:  # noqa: BLE001 — 개별 소스의 예상 못한 오류도 격리
            log.exception("소스 예외 %s", source.id)
            errors.append(f"{source.id}: {type(exc).__name__}: {exc}")
            health_results.append(SourceResult(source.id, source.name, False, error=str(exc)[:300]))
            continue

        health_results.append(SourceResult(source.id, source.name, True, count=len(items)))
        fresh = [
            it for it in items
            if apply_keyword_filters(it.title, source.filters)
            and not store.is_seen(it.dedup_key)
        ]
        # 같은 run 안에서의 소스 내 중복 제거 (동일 키 두 번 등장 방어)
        unique: dict[str, Item] = {}
        for it in fresh:
            unique.setdefault(it.dedup_key, it)
        fresh = list(unique.values())
        if not fresh:
            continue
        fresh.sort(key=lambda it: it.published_at or it.fetched_at)

        bootstrap = not store.source_has_rows(source.id)
        cap = BOOTSTRAP_POST_LIMIT if bootstrap else source.max_new_per_run
        if cap <= 0:
            to_post, overflow = [], fresh
        else:
            to_post, overflow = fresh[-cap:], fresh[:-cap]
        if bootstrap:
            log.info("'%s' 첫 수집(bootstrap): %d건 중 최신 %d건만 게시", source.id, len(fresh), len(to_post))

        if args.dry_run:
            for it in fresh:
                log.info("[dry-run] %s | %s", it.dedup_key, it.title)
            continue

        # 수집된 아이템은 게시 성패와 무관하게 즉시 영속화 —
        # to_post는 'pending'(실패 시 다음 run에서 재시도), overflow는 digest/사이트로만 노출
        for it in overflow:
            store.mark_seen(it, status="skipped" if not bootstrap else "seen")
        for it in to_post:
            store.mark_seen(it, status="pending" if posting else "seen")

        if posting and tg is not None:
            if not bootstrap and overflow:
                label = CATEGORY_META.get(source.category, {}).get("label", source.category)
                msgs = format_digest(overflow, f"{source.name} 신규 {label} 모음", site_url)
                last_mid = None
                try:
                    for msg in msgs:
                        last_mid = tg.send_message(staging_chat, msg)
                except TelegramError as exc:
                    errors.append(f"{source.id} digest 게시 실패: {exc}")
                else:  # 전 메시지 성공 시에만 posted로 승격
                    for it in overflow:
                        store.mark_posted(it.dedup_key, last_mid)
            for it in to_post:
                try:
                    mid = tg.send_message(
                        staging_chat,
                        format_item(it, site_url),
                        link_preview_for(it),
                    )
                    store.mark_posted(it.dedup_key, mid)
                    posted_total += 1
                except TelegramError as exc:
                    # pending으로 남겨 다음 run의 _retry_pending이 재시도
                    errors.append(f"{source.id} 게시 실패: {exc}")
                    break

    if not args.dry_run:
        alerts = update_health(health_results)
        for sid in alerts:
            _notify(cfg, tg, f"소스 '{sid}' 3회 연속 실패/0건 — 게시판 구조 변경 여부 확인 필요")
        # 사이트는 매 run 재생성 (LLM 요약은 evening에만 — 비용 절제)
        try:
            build_site(store, cfg.site, use_llm=(slot == "evening"))
        except Exception as exc:  # noqa: BLE001
            log.exception("사이트 빌드 실패")
            errors.append(f"site_build: {exc}")
        if slot == "evening":
            try:
                day = datetime.now(KST).date()
                content = build_draft(store, day, use_llm=True, site_url=cfg.site.base_url)
                write_draft(content, day)
            except Exception as exc:  # noqa: BLE001
                log.exception("블로그 초안 생성 실패")
                errors.append(f"blog_draft: {exc}")

    if errors and not args.dry_run:
        summary = "\n".join(f"· {e}" for e in errors[:15])
        _notify(cfg, tg, f"collect(slot={slot}) 일부 실패 {len(errors)}건:\n{summary}")
    elif errors:
        log.info("[dry-run] 오류 %d건 — 알림 생략", len(errors))
    log.info("완료: %d건 게시, %d건 오류", posted_total, len(errors))
    store.close()
    # 부분 실패는 성공으로 처리 — 전 소스 실패 시에만 실패 종료
    all_failed = bool(sources) and all(not r.ok for r in health_results)
    return 1 if all_failed else 0


def run_verify(args: argparse.Namespace) -> int:  # noqa: ARG001
    cfg = load_config()
    ctx = _make_ctx(cfg, "morning")
    ctx.advance_cursor = False  # 검증이 수집 워터마크를 움직이면 안 됨
    enabled = [s for s in cfg.sources if s.enabled]
    report = verify_sources(enabled, ctx)
    markdown = render_report(report)
    print(markdown)
    write_github_summary(markdown)
    # update_health는 호출하지 않음 — 연속 실패 카운터는 collect 전용 (3연속 경고 무결성)
    ctx.seen_store.close()
    ok = sum(1 for r in report.results if r.ok)
    log.info("검증: %d/%d 소스 성공", ok, len(report.results))
    return 0 if ok else 1


def run_smoke_g2b(args: argparse.Namespace) -> int:  # noqa: ARG001
    cfg = load_config()
    ctx = _make_ctx(cfg, "morning")
    mode = narajangteo.smoke_test(ctx)
    print(f"g2b mode: {mode}")
    ctx.seen_store.close()
    return 0 if mode in ("direct", "relay") else 2


def run_blog_draft(args: argparse.Namespace) -> int:
    cfg = load_config()
    day = date.fromisoformat(args.date) if args.date else datetime.now(KST).date()
    store = SeenStore()
    content = build_draft(store, day, use_llm=True, site_url=cfg.site.base_url)
    path = write_draft(content, day)
    store.close()
    print(f"초안 생성: {path}")
    return 0


def run_build_site(args: argparse.Namespace) -> int:  # noqa: ARG001
    cfg = load_config()
    store = SeenStore()
    build_site(store, cfg.site, use_llm=False)
    store.close()
    print("site/ 재생성 완료")
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    parser = argparse.ArgumentParser(prog="pipeline")
    sub = parser.add_subparsers(dest="command", required=True)

    p_collect = sub.add_parser("collect", help="수집 → 스테이징 게시 → 사이트 빌드")
    p_collect.add_argument("--slot", choices=["morning", "noon", "evening"])
    p_collect.add_argument("--sources", help="콤마 구분 소스 id 필터")
    p_collect.add_argument("--dry-run", action="store_true", help="수집만, 상태 저장·게시 없음")
    p_collect.add_argument("--no-post", action="store_true", help="게시 없이 상태만 저장")
    p_collect.set_defaults(func=run_collect)

    sub.add_parser("verify-sources", help="전 소스 접근성 검증 리포트").set_defaults(func=run_verify)
    sub.add_parser("smoke-g2b", help="나라장터 direct/relay 판별").set_defaults(func=run_smoke_g2b)

    p_draft = sub.add_parser("blog-draft", help="네이버 블로그 초안 생성")
    p_draft.add_argument("--date", help="YYYY-MM-DD (기본: 오늘 KST)")
    p_draft.set_defaults(func=run_blog_draft)

    sub.add_parser("build-site", help="site/ 재생성").set_defaults(func=run_build_site)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
