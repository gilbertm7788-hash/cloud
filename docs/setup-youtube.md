# 유튜브 영상 큐레이션 설정

## 방식 1: 채널 RSS (기본, API 키 불필요) ✅ 권장
우량 건설 채널의 channel_id만 있으면 쿼터 0으로 최신 영상을 수집합니다.

### channel_id 찾는 법
1. 유튜브에서 채널 페이지 열기
2. 채널 홈 → 더보기(정보) → 공유 → 채널 ID 복사, 또는
3. 페이지 소스에서 `"channelId":"UC..."` 검색 (`UC`로 시작하는 24자)

### sources.yaml에 추가
```yaml
  - id: yt_civil_story
    name: 토목공사 이야기          # 표시용 이름
    type: youtube_rss
    category: youtube
    enabled: true
    slots: [noon]
    youtube:
      channel_id: "UCxxxxxxxxxxxxxxxxxxxxxx"
```
채널 하나당 위 블록 하나 — 코드 수정 없이 추가/제거 가능.

### 시드 채널 발굴 팁
- 유튜브에서 "건설현장", "토목시공", "교량공사", "터널공사", "스마트건설" 등으로 검색해
  꾸준히 올라오는 채널을 3~5개 고르세요
- 국내 건설 영상 큐레이션 사이트(컨핏 contech.ai.kr 등)도 참고

### 한계
채널 RSS는 최신 약 15개 영상만 제공 — 하루 1회 폴링이면 놓칠 일 없습니다.

## 방식 2: 검색 API (선택 — 새 채널 발굴용)
1. https://console.cloud.google.com → 새 프로젝트 → API 라이브러리에서
   "YouTube Data API v3" 사용 설정 → 사용자 인증 정보 → API 키 생성 (무료, 카드 불필요)
2. 키 제한 설정: API 제한을 YouTube Data API v3로 한정 (보안)
3. GitHub Secret `YOUTUBE_API_KEY` 등록
4. sources.yaml에 `type: youtube_api` 소스 추가:
```yaml
  - id: yt_discover
    name: 유튜브 발굴 검색
    type: youtube_api
    category: youtube
    enabled: true
    slots: [noon]
    youtube:
      query: "건설현장|토목시공|교량공사"   # 파이프(|)로 OR 결합
```
- 쿼터: 검색 1회 = 100유닛, 일 한도 10,000유닛 — 하루 1~2회 검색이면 충분
- 검색 결과 중 제목에 한글이 없는 영상은 자동 필터링됩니다
