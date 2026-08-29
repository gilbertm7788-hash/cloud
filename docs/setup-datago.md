# 공공데이터포털(data.go.kr) 나라장터 API 설정

## 1. 인증키 발급
1. https://www.data.go.kr 회원가입 후 로그인
2. **"조달청_나라장터 입찰공고정보서비스"** 검색 (데이터 ID 15129394)
   - 직접 링크: https://www.data.go.kr/data/15129394/openapi.do
3. **활용신청** 클릭 → 활용 목적 간단히 기재 → 신청 (자동승인 유형 — 즉시 승인)
4. 마이페이지 → 오픈API → 인증키에서 **일반 인증키** 복사
   - Encoding·Decoding 어느 쪽을 넣어도 됩니다 (코드가 자동으로 원문으로 정규화 후 한 번만 인코딩)
   - ⚠️ 발급 직후 최대 1시간 정도 게이트웨이 동기화 지연으로 `SERVICE_KEY_IS_NOT_REGISTERED` 오류가 날 수 있음 — 기다렸다 재시도

## 2. GitHub Secret 등록
- `DATA_GO_KR_KEY`: 위에서 복사한 Encoding 인증키

## 3. 접근 경로 확인 (smoke-g2b)
GitHub Actions 탭 → collect → Run workflow → command: **smoke-g2b**

| 결과 | 의미 | 할 일 |
|---|---|---|
| `direct` | 러너에서 직접 호출 성공 | 없음 — 그대로 사용 |
| `relay` | 릴레이 경유 성공 | 없음 |
| `fail` | 직접 호출 차단 + 릴레이 미설정 | [setup-worker-relay.md](setup-worker-relay.md)로 릴레이 배포 |

> 배경: data.go.kr은 해외 IP 대역을 차단하는 경우가 많아 GitHub 호스티드 러너(해외 Azure IP)에서
> TCP 연결 자체가 타임아웃되는 사례가 실측 보고되어 있습니다. 이 경우 무료 Cloudflare Worker
> 릴레이로 우회합니다 (검증된 방식).

## 4. 쿼터·운영 참고
- 개발계정 일일 트래픽은 통상 1,000회 수준 (서비스 페이지에서 실제 수치 확인)
- 이 파이프라인은 하루 2회(아침·저녁) × 공사/용역 2개 오퍼레이션 × 페이지 수 회 호출 = 수십 회 수준이라 여유 있음
- 수집 기간은 증분(last sync 이후)이며 15일 초과 시 자동 분할 호출
- 파라미터 스펙 등 상세는 서비스 페이지의 활용가이드(Swagger) 참조
