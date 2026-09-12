# 🚀 최초 가동 체크리스트

파이프라인을 켜기 전에 아래 순서대로 준비하세요. 1~3번만 끝나면 뉴스 수집·게시가 시작됩니다.

## 1. 텔레그램 (필수) — [상세: setup-telegram.md](setup-telegram.md)
- [ ] @BotFather에서 봇 생성 → 토큰 확보
- [ ] **스테이징 채널**(비공개) 개설 — 봇이 여기에 자동 게시, 나만 구독
- [ ] **메인 채널**(공개) 개설 — 검토한 글을 여기로 전달(forward)
- [ ] 봇을 **스테이징 채널에만** 관리자(메시지 게시 권한)로 추가
- [ ] 스테이징 채널 chat_id(`-100...`) 확보
- [ ] GitHub 저장소 → Settings → Secrets and variables → Actions에 등록:
  - `TELEGRAM_BOT_TOKEN`, `TELEGRAM_STAGING_CHAT_ID`

## 2. GitHub 설정 (필수)
- [ ] 저장소를 **Public**으로 전환 (무료 GitHub Pages 조건 — API 키는 전부 Secrets라 코드 공개 무방)
- [ ] Settings → Pages → Source를 **GitHub Actions**로 설정
  (설정 전까지는 매 실행의 Summary 탭에 "Pages 미설정" 안내만 뜨고 배포는 건너뜀)
- [ ] `config/sources.yaml`의 `site.base_url`을 실제 Pages 주소로 확인/수정

> ℹ️ cron(07:30 / 12:00 / 18:30 KST)은 **이미 돌고 있습니다** — 이 브랜치가 저장소의 기본 브랜치입니다.
> 텔레그램 시크릿을 등록하기 전까지는 게시만 건너뛰고 수집·사이트 빌드만 수행합니다
> (Actions → 해당 실행 → Summary 탭에서 소스별 결과 확인 가능).

## 3. 첫 실행 (필수)
- [ ] Actions 탭 → collect → Run workflow → command: **verify-sources** 실행
  → Summary에서 소스별 성공/실패 확인. 실패한 소스는 `sources.yaml`에서 `enabled: false`로 끄거나 셀렉터 조정
- [ ] 텔레그램 시크릿 등록 후 command: **collect** 실행 → 스테이징 채널에 뉴스가 게시되는지 확인
  (시크릿 등록 이전에 수집된 항목은 사이트에만 실리고 텔레그램으로는 소급 게시되지 않음 — 정상)
- [ ] 한 번 더 실행 → 중복 게시가 없는지 확인 (신규 0건이어야 정상)

## 4. 나라장터 입찰공고 — [상세: setup-datago.md](setup-datago.md)
- [ ] data.go.kr 회원가입 → "조달청_나라장터 입찰공고정보서비스"(15129394) 활용신청 (즉시 자동승인)
- [ ] **Encoding 인증키**를 `DATA_GO_KR_KEY` Secret으로 등록 (발급 직후 최대 1시간 동기화 지연 가능)
- [ ] Run workflow → command: **smoke-g2b** 실행
  - `direct` → 그대로 사용 가능
  - `fail` → GitHub 러너 IP가 차단된 것 → [setup-worker-relay.md](setup-worker-relay.md)로 릴레이 배포(5분)

## 5. 검색엔진 등록 (사이트 가동 후 1회)
- [ ] 구글 서치콘솔에 사이트 등록 + `sitemap.xml` 제출
- [ ] 네이버 서치어드바이저(searchadvisor.naver.com)에 사이트 등록 + sitemap 제출

## 6. 선택 사항
- [ ] **유튜브**: 시드 채널 channel_id를 `sources.yaml`에 등록 — [setup-youtube.md](setup-youtube.md) (채널 RSS 방식은 API 키 불필요)
- [ ] **LLM 요약**: `ANTHROPIC_API_KEY` Secret 등록 시 블로그 초안·사이트 글 요약 품질 향상 (없어도 템플릿으로 동작)
- [ ] **네이버 뉴스 API**: 대한경제 등 보완 — `NAVER_CLIENT_ID/SECRET` 등록 후 `naver_construction` 소스 활성화
- [ ] **에러 알림 분리**: `TELEGRAM_ADMIN_CHAT_ID` 등록 시 오류 알림이 별도 채팅으로 감
- [ ] **커스텀 도메인**: 연결이 늦을수록 github.io 주소로 쌓인 검색 점수 리셋 폭이 커짐 — 자리 잡기 전 이른 연결 권장
- [ ] **네이버 블로그(보조 채널)**: 시작 시점에 명의 확정(계정 양도 불가) — [setup-naver.md](setup-naver.md)

## 일일 운영 루틴 (자동화 이후 사람이 하는 일)
1. 스테이징 채널에 쌓인 콘텐츠 확인 (아침/점심/저녁 자동 게시)
2. 괜찮은 항목을 선택 → 메인 채널로 **전달(forward)** — 이때 "보낸 사람 이름 숨기기" 체크
3. (네이버 블로그 운영 시) `drafts/날짜.md` 초안을 다듬어 발행 — 해설 빈칸 채우기 필수

## 운영 원칙 (법적 리스크 관리)

아래는 지금 구조가 안전한 이유이므로 바꾸지 말 것.

- **공고·기사 본문을 수집하지 않는다.** 모든 수집기는 목록/피드 응답 1회만 파싱하고 상세 페이지를 열지 않는다. 본문을 긁기 시작하면 저작권과 개인정보 리스크가 동시에 올라간다 (예: "심의위원 명단" 공고 원문에는 위원 실명이 있다)
- **담당자 연락처 필드를 저장하지 않는다.** extra에 넣는 것은 기관명·마감·추정가뿐이다
- **robots.txt를 따른다.** 게시판 수집은 `src/robots.py`를 거치며, 금지된 경로는 소스 실패로 드러난다. 해제하려면 `board.respect_robots: false`를 명시해야 한다
- **기사 요약(RSS description)을 게시하지 않는다.** 제목만으로 내용 파악이 되고,
  본문 발췌 재전송은 제목·링크만 다루는 나머지 구조와 성격이 다르다. Item.summary는
  모델에 남아 있지만 출력 경로가 없다 (src/format_telegram.py)
- **출처와 원문 링크를 항상 함께 싣는다.** 제목만 떼어 재배포하지 않는다
- **게시 중단 요청 창구를 유지한다.** `site/about.html`

수익화(광고 게재)를 시작하면 GitHub Pages 약관, 사업자등록·소득신고, 표시광고법을 다시 확인해야 한다.
