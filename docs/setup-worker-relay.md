# Cloudflare Worker 릴레이 배포 (5분)

`smoke-g2b`가 `fail`일 때만 필요합니다. GitHub 러너(해외 IP)가 apis.data.go.kr에
차단되는 경우 무료 Cloudflare Worker를 경유해 호출합니다.

## 1. 준비
- Cloudflare 무료 계정 가입 (https://dash.cloudflare.com/sign-up)
- 로컬에 Node.js 설치 (npx 사용)

## 2. 배포
```bash
cd worker
npx wrangler login                 # 브라우저로 Cloudflare 인증
npx wrangler secret put RELAY_SECRET
# → 긴 랜덤 문자열 입력 (예: openssl rand -hex 32 로 생성)
npx wrangler deploy
# → 출력: https://g2b-relay.<계정명>.workers.dev
```

## 3. GitHub Secrets 등록
- `G2B_RELAY_URL`: 배포 출력 URL (예: `https://g2b-relay.myaccount.workers.dev`)
- `G2B_RELAY_SECRET`: 2번에서 입력한 랜덤 문자열

## 4. 확인
Actions → Run workflow → command: **smoke-g2b** → `relay`가 나오면 성공.

## 보안 설계
- 릴레이는 `X-Relay-Secret` 헤더가 일치하는 GET 요청만, `apis.data.go.kr`의
  `/1230000/` 경로로만 전달합니다 (오픈 프록시 아님)
- data.go.kr 인증키(serviceKey)는 GitHub Secrets에만 저장되고 요청 쿼리로
  통과할 뿐 Worker에는 저장되지 않습니다
- 무료 플랜 한도(일 10만 요청)는 이 용도(하루 수십 회)에 충분합니다
