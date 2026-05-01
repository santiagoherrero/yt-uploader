import html
import logging
from typing import Any, Optional

import httpx

log = logging.getLogger(__name__)


def progress_bar(pct: int, width: int = 10) -> str:
    pct = max(0, min(100, pct))
    filled = pct * width // 100
    return "█" * filled + "░" * (width - filled)


def esc(value: object) -> str:
    return html.escape(str(value), quote=False)


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._base = f"https://api.telegram.org/bot{bot_token}"
        self._chat_id = chat_id
        self._client = httpx.Client(timeout=10.0)

    def send(self, text: str) -> Optional[int]:
        try:
            r = self._client.post(
                f"{self._base}/sendMessage",
                json={
                    "chat_id": self._chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False,
                },
            )
            r.raise_for_status()
            return r.json()["result"]["message_id"]
        except Exception:
            log.exception("Telegram send failed")
            return None

    def edit(self, message_id: Optional[int], text: str) -> None:
        if message_id is None:
            self.send(text)
            return
        try:
            r = self._client.post(
                f"{self._base}/editMessageText",
                json={
                    "chat_id": self._chat_id,
                    "message_id": message_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False,
                },
            )
            r.raise_for_status()
        except Exception:
            log.exception("Telegram edit failed")

    def send_with_keyboard(
        self,
        text: str,
        inline_keyboard: list[list[dict[str, str]]],
    ) -> Optional[int]:
        try:
            r = self._client.post(
                f"{self._base}/sendMessage",
                json={
                    "chat_id": self._chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                    "reply_markup": {"inline_keyboard": inline_keyboard},
                },
            )
            r.raise_for_status()
            return r.json()["result"]["message_id"]
        except Exception:
            log.exception("Telegram send_with_keyboard failed")
            return None

    def edit_keyboard(
        self,
        message_id: Optional[int],
        text: str,
        inline_keyboard: Optional[list[list[dict[str, str]]]],
    ) -> None:
        if message_id is None:
            return
        body: dict[str, Any] = {
            "chat_id": self._chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if inline_keyboard is not None:
            body["reply_markup"] = {"inline_keyboard": inline_keyboard}
        try:
            r = self._client.post(f"{self._base}/editMessageText", json=body)
            r.raise_for_status()
        except Exception:
            log.exception("Telegram edit_keyboard failed")

    def answer_callback_query(
        self,
        callback_query_id: str,
        text: Optional[str] = None,
    ) -> None:
        body: dict[str, Any] = {"callback_query_id": callback_query_id}
        if text is not None:
            body["text"] = text
        try:
            r = self._client.post(f"{self._base}/answerCallbackQuery", json=body)
            r.raise_for_status()
        except Exception:
            log.exception("Telegram answerCallbackQuery failed")

    def get_updates(
        self,
        offset: int,
        timeout_s: int,
        allowed_updates: Optional[list[str]] = None,
    ) -> list[dict[str, Any]]:
        body: dict[str, Any] = {"offset": offset, "timeout": timeout_s}
        if allowed_updates is not None:
            body["allowed_updates"] = allowed_updates
        try:
            r = self._client.post(
                f"{self._base}/getUpdates",
                json=body,
                timeout=timeout_s + 10,
            )
            r.raise_for_status()
            return r.json().get("result", [])
        except Exception:
            log.exception("Telegram getUpdates failed")
            return []

    @property
    def chat_id(self) -> str:
        return self._chat_id
