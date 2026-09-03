# 건설 인사이트 — 콘텐츠 수집·큐레이션 파이프라인

건설(토목·건축) 분야의 뉴스, 입찰공고, 위원회 모집, 유튜브 영상을 자동 수집해
**텔레그램 채널 + 자체 사이트(GitHub Pages)** 로 큐레이션하는 시스템입니다.

```
[소스]                     [GitHub Actions cron: 07:30 / 12:00 / 18:30 KST]
뉴스 RSS ────┐
나라장터 API ─┤ 수집 → 정규화 → 중복제거 → ┬→ 텔레그램 스테이징 채널(비공개) ─(검토 후 forward)→ 메인 채널(공개)
협회 게시판 ──┤   (state/seen.db)          ├→ 자체 사이트 재생성 → GitHub Pages 자동 배포
위원회 공고 ──┤                            └→ 네이버 블로그 초안 (drafts/*.md, 수동 발행용)
유튜브 RSS ──┘
```

## 시작하기
**[docs/checklist.md](docs/checklist.md)** 를 순서대로 따라가세요.
텔레그램 봇/채널 + GitHub Secrets 2개만 등록하면 뉴스 수집이 시작됩니다.

## 구성 요소
| 경로 | 역할 |
|---|---|
| `config/sources.yaml` | 모든 소스의 선언적 정의 — **코드 수정 없이** 소스 추가/제거/키워드 조정 |
| `src/collectors/` | 소스 타입별 수집기 (rss, board, eminwon, narajangteo, naver_news, youtube) |
| `src/main.py` | CLI: `collect` / `verify-sources` / `smoke-g2b` / `blog-draft` / `build-site` |
| `site/` | 자체 사이트 — 대시보드(진행중 위원회·입찰, 뉴스, 영상) + 일간 브리핑 글 + sitemap/RSS |
| `state/seen.db` | 중복제거·게시 상태 (Actions가 자동 커밋) |
| `drafts/` | 네이버 블로그(보조 채널)용 초안 |
| `worker/` | data.go.kr 해외 IP 차단 우회용 Cloudflare Worker 릴레이 |
| `.github/workflows/collect.yml` | 스케줄 실행 + state 커밋 + Pages 배포 + 실패 알림 |

## 로컬 실행
```bash
pip install -e ".[dev]"
pytest                                   # 단위 테스트
python -m src.main verify-sources        # 소스 접근성 검증 (네트워크 필요)
python -m src.main collect --dry-run     # 수집 시뮬레이션
python -m src.main build-site            # site/ 재생성
```
텔레그램 게시까지 로컬로 돌리려면 환경변수 `TELEGRAM_BOT_TOKEN`, `TELEGRAM_STAGING_CHAT_ID` 설정.

## 새 소스 추가하는 법
1. `config/sources.yaml`에 항목 추가 (기존 항목 복사 후 수정이 가장 쉬움)
   - 일반 HTML 게시판은 `type: board` + CSS 셀렉터로 대부분 커버
   - 새올(eminwon) 계열 지자체 고시공고는 `type: eminwon` + host만 교체
2. `python -m src.main verify-sources`로 실제 응답·파싱 확인
3. 확인되면 `enabled: true`로 커밋

### 셀렉터·피드 URL이 안 맞을 때: `probe`
Actions 탭 → collect → Run workflow → command **probe**, sources 칸에 대상 입력 → Summary 탭에서 결과 확인
- **소스 id** (예: `kira_news`): 게시판이면 `row_selector` 매칭 행 수와 매칭된 행 HTML, 0행이면 페이지의
  `<a>` 태그 샘플 40개를 보여줘 올바른 셀렉터를 찾을 수 있음. RSS/API 소스면 수집 결과 10건 미리보기
- **URL** (예: `https://www.korea.kr/etc/rss.do`): 응답 크기·인코딩, 페이지 안의 RSS/XML 링크 후보, 본문 앞부분
- 콤마로 여러 대상을 한 번에 지정 가능 (예: `https://a.com/rss.xml,https://a.com/feed`) — URL 후보를 한 실행으로 시험
- 로컬에서는 `python -m src.main probe --target <id 또는 URL>` (한국 사이트가 막힌 환경에서는 Actions 사용)

## 운영 원칙
- 텔레그램 시크릿이 없으면 게시만 건너뛰고 수집·사이트 빌드는 계속됩니다 (실행 결과는 Actions Summary 탭)
- 텔레그램: 스테이징 채널 검토 → 메인 채널 전달 시 **"보낸 사람 이름 숨기기"**
- 네이버 블로그: **자동 발행 금지**, 초안의 해설 빈칸을 직접 채워 발행 — [docs/setup-naver.md](docs/setup-naver.md)
- 소스가 3회 연속 실패하면 스테이징 채널로 경고가 옵니다 (게시판 구조 변경 신호)

## 문서
- [최초 가동 체크리스트](docs/checklist.md)
- [텔레그램 설정](docs/setup-telegram.md) · [나라장터 API](docs/setup-datago.md) · [Worker 릴레이](docs/setup-worker-relay.md)
- [유튜브](docs/setup-youtube.md) · [네이버 블로그 운영](docs/setup-naver.md)
