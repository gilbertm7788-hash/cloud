# 텔레그램 봇·채널 설정 가이드

## 1. 봇 생성
1. 텔레그램에서 **@BotFather** 검색 (공식 인증 마크 확인)
2. `/newbot` 입력 → 봇 이름 지정 → username 지정 (`...bot`으로 끝나야 함, 예: `construction_curator_bot`)
3. 발급된 **HTTP API 토큰**을 복사 — 이 토큰은 봇의 비밀번호입니다. 절대 저장소에 커밋하거나 공유하지 마세요.
4. 유출이 의심되면 BotFather에서 `/revoke`로 즉시 재발급

## 2. 채널 2개 개설
| 채널 | 공개 설정 | 용도 |
|---|---|---|
| 스테이징 채널 | **비공개** | 봇이 수집 콘텐츠를 자동 게시. 나(운영자)만 구독 |
| 메인 채널 | **공개** (username 지정) | 구독자용. 검토한 콘텐츠만 전달 |

- 새 채널 만들기 → 채널 이름 입력 → 비공개/공개 선택
- 메인 채널의 공개 username(예: `t.me/구조물이야기`)이 확정되면 `config/sources.yaml`의 `site.telegram_channel_url`에 입력

## 3. 봇을 스테이징 채널 관리자로 추가
1. 스테이징 채널 → 상단 채널명 클릭 → 관리자(Administrators) → 관리자 추가
2. 봇 username 검색 → 추가 → **"메시지 게시(Post messages)"** 권한만 켜면 충분
3. ⚠️ 메인 채널에는 봇을 추가하지 않습니다 (실수 방지)

## 4. 스테이징 채널 chat_id 확보
1. 스테이징 채널에 아무 글이나 하나 게시
2. 브라우저에서 열기 (TOKEN을 실제 토큰으로 교체):
   ```
   https://api.telegram.org/bot<TOKEN>/getUpdates
   ```
3. 응답 JSON에서 `channel_post.chat.id` 값 확인 → `-100`으로 시작하는 숫자 (예: `-1001234567890`)
4. ⚠️ 응답이 빈 배열(`"result":[]`)이면:
   - 봇에 webhook이 설정된 경우입니다 → 먼저 `https://api.telegram.org/bot<TOKEN>/deleteWebhook` 호출 후 다시 시도
   - 또는 채널에 새 글을 다시 게시한 뒤 재시도

## 5. GitHub Secrets 등록
저장소 → Settings → Secrets and variables → Actions → New repository secret:
- `TELEGRAM_BOT_TOKEN`: 봇 토큰
- `TELEGRAM_STAGING_CHAT_ID`: `-100...` 숫자 (따옴표 없이)
- (선택) `TELEGRAM_ADMIN_CHAT_ID`: 오류 알림을 받을 별도 채팅 id

## 6. 일일 운영: 스테이징 → 메인 전달
1. 스테이징 채널에서 게시할 메시지들을 길게 눌러 선택 (복수 선택 가능)
2. 전달(Forward) → 메인 채널 선택
3. **"보낸 사람 이름 숨기기(Hide sender name)"를 반드시 체크** — 안 하면 비공개 스테이징 채널명이 공개 채널 구독자에게 노출됩니다
4. 나중에 원클릭 승인 버튼(copyMessage 기반 자동 전달)으로 업그레이드 가능

## 참고: 무료 한도
봇 API는 무료입니다. 채팅당 초당 1건 수준의 속도 제한이 있고 파이프라인이 자동으로 지켜줍니다. 하루 수십 건 큐레이션에는 전혀 문제없습니다.
