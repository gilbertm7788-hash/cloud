"""텔레그램 봇 API 클라이언트: 스로틀·429 재시도·plain 폴백·에러 알림."""
from __future__ import annotations

import json
import logging
import re
import time

import httpx

log = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_ANCHOR_RE = re.compile(r'<a href="([^"]*)">([^<]*)</a>')


def _to_plain(html: str) -> str:
    """HTML 파싱 실패 폴백용: 링크 URL을 보존하며 태그 제거 + 엔티티 복원."""
    text = _ANCHOR_RE.sub(r"\2: \1", html)
    text = _TAG_RE.sub("", text)
    return (text.replace("&lt;", "<").replace("&gt;", ">")
            .replace("&quot;", '"').replace("&amp;", "&"))


class TelegramError(Exception):
    pass


class TelegramClient:
    def __init__(self, token: str, *, min_interval: float = 1.05, timeout: float = 20):
        self.base = f"https://api.telegram.org/bot{token}"
        self.min_interval = min_interval
        self.timeout = timeout
        self._last_sent = 0.0
        # 메시지마다 새 커넥션을 여는 대신 하나를 재사용 (TLS 핸드셰이크 절감)
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "TelegramClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def _throttle(self) -> None:
        wait = self._last_sent + self.min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)

    def _post(self, method: str, payload: dict, retries: int = 3) -> dict:
        for attempt in range(retries + 1):
            self._throttle()
            try:
                resp = self._client.post(f"{self.base}/{method}", json=payload)
                self._last_sent = time.monotonic()
                body = resp.json()
            except (httpx.TransportError, json.JSONDecodeError) as exc:
                if attempt < retries:
                    time.sleep(2 ** attempt)
                    continue
                raise TelegramError(f"{method} 네트워크 실패: {exc}") from exc
            if body.get("ok"):
                return body["result"]
            if resp.status_code == 429:
                retry_after = (body.get("parameters") or {}).get("retry_after", 5)
                log.warning("텔레그램 429 — %ss 대기", retry_after)
                if attempt < retries:
                    time.sleep(retry_after + 1)
                    continue
            raise TelegramError(
                f"{method} 실패 [{resp.status_code}]: {body.get('description')}"
            )
        raise TelegramError(f"{method}: 재시도 소진")

    def send_message(
        self, chat_id: str, html: str, link_preview: dict | None = None
    ) -> int:
        payload: dict = {"chat_id": chat_id, "text": html, "parse_mode": "HTML"}
        if link_preview is not None:
            payload["link_preview_options"] = link_preview
        try:
            result = self._post("sendMessage", payload)
        except TelegramError as exc:
            # HTML 파싱 오류에 한해서만 plain 폴백 (링크 URL은 본문에 보존)
            if "can't parse" in str(exc).lower():
                log.warning("HTML 파싱 실패, plain 폴백: %s", exc)
                result = self._post(
                    "sendMessage", {"chat_id": chat_id, "text": _to_plain(html)}
                )
            else:
                raise
        return int(result.get("message_id", 0))

    def notify_error(self, chat_id: str, text: str) -> None:
        """파이프라인 오류 알림 — 알림 실패가 run을 죽이지 않게 삼킴."""
        try:
            plain = f"⚠️ [파이프라인 오류]\n{text[:3500]}"
            self._post("sendMessage", {"chat_id": chat_id, "text": plain}, retries=1)
        except Exception:  # noqa: BLE001
            log.exception("에러 알림 전송 실패")
