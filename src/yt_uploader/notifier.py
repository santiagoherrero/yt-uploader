import html
import logging
from typing import Optional

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
