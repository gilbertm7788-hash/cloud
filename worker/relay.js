/**
 * Cloudflare Worker 릴레이 — apis.data.go.kr 전용.
 *
 * GitHub 호스티드 러너(해외 IP)가 data.go.kr에 차단될 때의 우회 경로.
 * 보안:
 *  - X-Relay-Secret 헤더가 RELAY_SECRET(wrangler secret)과 일치해야 통과
 *  - 업스트림 호스트 하드코딩 + /1230000/ 경로 프리픽스 화이트리스트
 *  - GET 전용
 * serviceKey는 GitHub Secrets에서 쿼리로 전달되며 이 Worker에는 저장하지 않는다.
 *
 * 배포: docs/setup-worker-relay.md 참조.
 */
export default {
  async fetch(request, env) {
    if (request.method !== "GET") {
      return new Response("method not allowed", { status: 405 });
    }
    const secret = request.headers.get("X-Relay-Secret");
    if (!env.RELAY_SECRET || secret !== env.RELAY_SECRET) {
      return new Response("forbidden", { status: 403 });
    }
    const url = new URL(request.url);
    if (!url.pathname.startsWith("/1230000/")) {
      return new Response("bad request", { status: 400 });
    }
    const upstream = "https://apis.data.go.kr" + url.pathname + url.search;
    const resp = await fetch(upstream, {
      headers: { Accept: "application/json" },
    });
    return new Response(resp.body, {
      status: resp.status,
      headers: { "Content-Type": resp.headers.get("Content-Type") || "application/json" },
    });
  },
};
