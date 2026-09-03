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
import re
import sys
from datetime import date, datetime, timedelta, timezone

from .blog_draft import build_draft, write_draft
from .collectors import COLLECTORS, CollectError, RunContext
from .collectors import narajangteo
from .config import AppConfig, apply_keyword_filters, load_config
from .dedup import SeenStore
from .format_telegram import format_digest, format_item, link_preview_for
from .httpio import decode_body, fetch_bytes, redact_secrets
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
        log.warning("알림 전송 생략(텔레그램 미설정): %s", text)
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


def _is_transient(exc: TelegramError) -> bool:
    """일시적 장애(레이트리밋·네트워크·서버오류)면 True — 이때만 재시도 루프를 중단한다."""
    text = str(exc).lower()
    return ("429" in text or "네트워크" in text or "timeout" in text
            or "[50" in text or "재시도 소진" in text)


def _retry_pending(store, tg: TelegramClient, staging_chat: str, site_url: str,
                   errors: list[str]) -> int:
    """이전 run에서 게시 실패한 아이템 재시도.

    결정적 오류(잘못된 메시지 등)는 해당 건만 'failed'로 내려 큐가 막히지 않게 하고,
    일시적 장애일 때만 루프를 멈춰 다음 run에 통째로 재시도한다.
    """
    sent = 0
    for row in store.pending(limit=25):
        item = _item_from_row(row)
        if not item.title or not item.url:
            # 복원 불가 row — 'posted'로 올리면 아카이브에 빈 항목이 실리므로 종료 상태로만 내림
            store.mark_status(row["id"], "failed")
            continue
        try:
            mid = tg.send_message(staging_chat, format_item(item, site_url),
                                  link_preview_for(item))
            store.mark_posted(row["id"], mid)
            sent += 1
        except TelegramError as exc:
            errors.append(f"pending 재시도 실패({row['id']}): {exc}")
            if _is_transient(exc):
                break
            store.mark_status(row["id"], "failed")  # 영구 실패 — 큐에서 제외
    return sent


def run_collect(args: argparse.Namespace) -> int:
    cfg = load_config()
    slot = args.slot or current_slot()
    ctx = _make_ctx(cfg, slot)
    ctx.advance_cursor = not args.dry_run  # dry-run은 증분 워터마크를 움직이지 않음
    store = ctx.seen_store
    tg, staging_chat = _telegram(cfg)
    posting = not (args.dry_run or args.no_post)
    notices: list[str] = []
    if posting and tg is None:
        # 설정 전 단계 — 실패로 죽이면 cron마다 실패 메일만 쌓인다.
        # 게시만 생략하고 수집·사이트 빌드는 정상 진행해 사이트가 먼저 채워지게 한다.
        posting = False
        notices.append(
            "텔레그램 시크릿(TELEGRAM_BOT_TOKEN, TELEGRAM_STAGING_CHAT_ID) 미등록 — "
            "이번 실행은 게시 없이 수집·사이트 빌드만 수행했습니다. docs/checklist.md 1번 참조."
        )
        log.warning(notices[-1])

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
            # 예외 문자열에 요청 URL(=API 키·릴레이 주소)이 섞일 수 있어 항상 마스킹
            msg = redact_secrets(str(exc), cfg.secrets.values())[:300]
            log.warning("소스 실패 %s: %s", source.id, msg)
            errors.append(f"{source.id}: {msg}")
            health_results.append(SourceResult(source.id, source.name, False, error=msg))
            continue
        except Exception as exc:  # noqa: BLE001 — 개별 소스의 예상 못한 오류도 격리
            msg = redact_secrets(f"{type(exc).__name__}: {exc}", cfg.secrets.values())[:300]
            log.error("소스 예외 %s: %s", source.id, msg)
            errors.append(f"{source.id}: {msg}")
            health_results.append(SourceResult(source.id, source.name, False, error=msg))
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
                    errors.append(f"{source.id} 게시 실패: {exc}")
                    if _is_transient(exc):
                        break  # 일시적 장애 — pending으로 남겨 다음 run에서 재시도
                    store.mark_status(it.dedup_key, "failed")

    if not args.dry_run:
        store.prune()  # 오래된 미게시 row 정리 (state/seen.db 무한 증가 방지)
        alerts = update_health(health_results)
        for sid in alerts:
            _notify(cfg, tg, f"소스 '{sid}' 3회 연속 실패/0건 — 게시판 구조 변경 여부 확인 필요")
        # 사이트는 매 run 재생성 (LLM 요약은 evening에만 — 비용 절제)
        try:
            build_site(store, cfg.site, use_llm=(slot == "evening"))
        except Exception as exc:  # noqa: BLE001
            log.exception("사이트 빌드 실패")
            errors.append(redact_secrets(f"site_build: {exc}", cfg.secrets.values()))
        if slot == "evening":
            try:
                day = datetime.now(KST).date()
                content = build_draft(store, day, use_llm=True, site_url=cfg.site.base_url)
                write_draft(content, day)
            except Exception as exc:  # noqa: BLE001
                log.exception("블로그 초안 생성 실패")
                errors.append(redact_secrets(f"blog_draft: {exc}", cfg.secrets.values()))

    if errors and not args.dry_run:
        summary = "\n".join(f"· {e}" for e in errors[:15])
        _notify(cfg, tg, f"collect(slot={slot}) 일부 실패 {len(errors)}건:\n{summary}")
    elif errors:
        log.info("[dry-run] 오류 %d건 — 알림 생략", len(errors))
    log.info("완료: %d건 게시, %d건 오류", posted_total, len(errors))
    if tg is not None:
        tg.close()
    store.close()
    # 부분 실패는 성공으로 처리 — 전 소스 실패 시에만 실패 종료
    all_failed = bool(sources) and all(not r.ok for r in health_results)
    if not args.dry_run:
        write_github_summary(_collect_summary(slot, posting, posted_total, health_results,
                                              errors, notices))
    return 1 if all_failed else 0


def _collect_summary(slot: str, posting: bool, posted: int, results: list[SourceResult],
                     errors: list[str], notices: list[str]) -> str:
    """GitHub Actions 요약 탭용 실행 리포트 (마스킹된 문자열만 들어온다)."""
    lines = [f"# collect 실행 요약 — slot: {slot}", ""]
    for n in notices:
        lines.append(f"> ⚠️ {n}")
    lines += [
        "",
        f"- 텔레그램 게시: {'활성' if posting else '비활성'} / 게시 {posted}건",
        f"- 소스 결과: 성공 {sum(1 for r in results if r.ok)} / 실패 {sum(1 for r in results if not r.ok)}",
        "",
        "| 소스 | 상태 | 수집 건수 | 비고 |", "|---|---|---|---|",
    ]
    for r in results:
        lines.append(f"| {r.name} (`{r.source_id}`) | {'✅' if r.ok else '❌'} | {r.count} | {r.error} |")
    if errors:
        lines += ["", "## 오류", ""] + [f"- {e}" for e in errors[:20]]
    return "\n".join(lines)


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


def _probe_url(url: str, cfg, out: list[str]) -> None:
    try:
        content, charset = fetch_bytes(url, timeout=30, verify_tls=False)
    except Exception as exc:  # noqa: BLE001
        out.append(f"요청 실패: {redact_secrets(str(exc), cfg.secrets.values())}")
        return
    text = decode_body(content, charset)
    out.append(f"OK — {len(content)} bytes, charset={charset}")
    links = re.findall(r"""(?:href|src)=["']([^"']+)""", text, re.I)
    feeds = [l for l in dict.fromkeys(links) if re.search(r"rss|feed|\.xml", l, re.I)]
    out.append("--- 피드/XML 링크 후보 ---")
    out += feeds[:40] or ["(없음)"]
    out.append("--- 본문 텍스트 앞부분 ---")
    out.append(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))[:2500])
    out.append("--- HTML 앞부분 ---")
    out.append(text[:2500])


def _probe_source(source, cfg, out: list[str]) -> None:
    ctx = _make_ctx(cfg, "morning")
    ctx.advance_cursor = False
    try:
        if source.type == "board":
            from bs4 import BeautifulSoup
            o = source.options
            url = str(o.get("list_url", "")).replace("{page}", "1")
            method = (o.get("method") or "GET").upper()
            data = ({k: str(v).replace("{page}", "1") for k, v in (o.get("form_data") or {}).items()}
                    if method == "POST" else None)
            content, charset = fetch_bytes(url, timeout=source.timeout, method=method, data=data,
                                           verify_tls=bool(o.get("verify_tls", True)))
            html = decode_body(content, charset, o.get("encoding", "auto"))
            soup = BeautifulSoup(html, "html.parser")
            rows = soup.select(o.get("row_selector", ""))
            out.append(f"{url} → {len(content)} bytes, charset={charset}")
            out.append(f"row_selector={o.get('row_selector')!r} → {len(rows)}행 매칭")
            for row in rows[:3]:
                out.append("--- 매칭 행 ---")
                out.append(str(row)[:700])
            if not rows:
                out.append(f"구조 힌트: table={len(soup.find_all('table'))} ul={len(soup.find_all('ul'))} "
                           f"li={len(soup.find_all('li'))} a={len(soup.find_all('a'))}")
                out.append("--- a 태그 샘플 (최대 40) ---")
                for a in soup.find_all("a")[:40]:
                    out.append(f"  href={a.get('href')!r} onclick={a.get('onclick')!r} "
                               f"class={a.get('class')!r} | {a.get_text(' ', strip=True)[:60]}")
                out.append("--- HTML 앞부분 ---")
                out.append(html[:3000])
        else:
            items = COLLECTORS[source.type](source, ctx)
            out.append(f"{source.type} '{source.id}': {len(items)}건 수집")
            for it in items[:10]:
                out.append(f"  {it.dedup_key} | {it.title[:70]} | {it.url}")
    except Exception as exc:  # noqa: BLE001
        out.append(f"실패: {redact_secrets(str(exc), cfg.secrets.values())}")
    finally:
        ctx.seen_store.close()


def run_probe(args: argparse.Namespace) -> int:
    """소스 튜닝용 진단: URL이면 응답·피드 링크·본문 앞부분, 소스 id면 셀렉터 매칭/수집 결과.

    콤마로 여러 대상을 한 번에 지정할 수 있다 (URL 후보 여러 개를 한 실행으로 시험).
    """
    targets = [t.strip() for t in (args.target or "").split(",") if t.strip()]
    if not targets:
        print("probe --target 에 URL 또는 소스 id를 지정하세요 (콤마로 여러 개 가능)")
        return 2
    cfg = load_config()
    out: list[str] = []
    rc = 0
    for target in targets:
        if len(targets) > 1:
            out.append(f"\n===== {target} =====")
        if target.startswith(("http://", "https://")):
            _probe_url(target, cfg, out)
            continue
        source = next((s for s in cfg.sources if s.id == target), None)
        if source is None:
            out.append(f"소스 id '{target}' 없음. 사용 가능: {', '.join(s.id for s in cfg.sources)}")
            rc = 2
            continue
        _probe_source(source, cfg, out)
    text = "\n".join(out)
    print(text)
    write_github_summary(f"# probe: {', '.join(targets)}\n\n```\n{text[:60000]}\n```")
    return rc


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

    p_probe = sub.add_parser("probe", help="소스 튜닝 진단: URL 응답/피드 링크 또는 소스 셀렉터 매칭 확인")
    p_probe.add_argument("--target", help="URL(http...) 또는 sources.yaml의 소스 id")
    p_probe.set_defaults(func=run_probe)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
