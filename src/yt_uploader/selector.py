import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .notifier import TelegramNotifier, esc

log = logging.getLogger(__name__)

MAX_BUTTONS = 50
NAME_MAX = 25
POLL_TIMEOUT_S = 25


class VideoSelector:
    def __init__(self, telegram: TelegramNotifier) -> None:
        self._tg = telegram

    def choose(
        self,
        items: list[tuple[Path, str]],
        mount_path: Path,
        timeout_s: int,
    ) -> list[int]:
        n = len(items)
        if n == 0:
            return []

        visible = min(n, MAX_BUTTONS)
        selected: set[int] = set()

        text = self._render_text(mount_path, items, visible, timeout_s)
        keyboard = self._render_keyboard(items, visible, selected)

        msg_id = self._tg.send_with_keyboard(text, keyboard)
        if msg_id is None:
            log.warning("Could not send selection message; falling back to upload-all")
            return list(range(n))

        offset = self._drain_pending_updates()

        deadline = time.time() + timeout_s
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                self._tg.edit_keyboard(
                    msg_id,
                    text + "\n\n⏰ Sin respuesta, subiendo todos.",
                    None,
                )
                return list(range(n))

            poll = max(0, min(POLL_TIMEOUT_S, int(remaining)))
            updates = self._tg.get_updates(offset, poll, allowed_updates=["callback_query"])
            for u in updates:
                offset = max(offset, int(u["update_id"]) + 1)
                cq = u.get("callback_query")
                if not cq:
                    continue
                if not self._is_for_us(cq, msg_id):
                    self._tg.answer_callback_query(cq["id"])
                    continue

                data = cq.get("data", "")
                self._tg.answer_callback_query(cq["id"])

                if data == "ok":
                    if not selected:
                        self._tg.edit_keyboard(
                            msg_id,
                            text + "\n\n✖️ Cancelado (no seleccionaste ningún video).",
                            None,
                        )
                        return []
                    chosen = sorted(selected)
                    self._tg.edit_keyboard(
                        msg_id,
                        text + f"\n\n✅ Subiendo {len(chosen)} de {n}.",
                        None,
                    )
                    return chosen

                if data == "cancel":
                    self._tg.edit_keyboard(
                        msg_id,
                        text + "\n\n✖️ Cancelado.",
                        None,
                    )
                    return []

                if data.startswith("tog:"):
                    try:
                        idx = int(data[4:])
                    except ValueError:
                        continue
                    if idx < 0 or idx >= visible:
                        continue
                    if idx in selected:
                        selected.remove(idx)
                    else:
                        selected.add(idx)
                    keyboard = self._render_keyboard(items, visible, selected)
                    self._tg.edit_keyboard(msg_id, text, keyboard)

    def _drain_pending_updates(self) -> int:
        updates = self._tg.get_updates(0, 0, allowed_updates=["callback_query"])
        if not updates:
            return 0
        return max(int(u["update_id"]) for u in updates) + 1

    def _is_for_us(self, cq: dict[str, Any], msg_id: int) -> bool:
        msg = cq.get("message") or {}
        if msg.get("message_id") != msg_id:
            return False
        chat = msg.get("chat") or {}
        if str(chat.get("id")) != self._tg.chat_id:
            return False
        return True

    def _render_text(
        self,
        mount_path: Path,
        items: list[tuple[Path, str]],
        visible: int,
        timeout_s: int,
    ) -> str:
        n = len(items)
        lines = [
            f"🎬 Disco detectado en <code>{esc(mount_path)}</code>",
            f"<b>{n}</b> video(s) nuevo(s). Elegí cuáles subir:",
        ]
        if visible < n:
            lines.append(
                f"\n⚠️ Mostrando los primeros {visible}. "
                "Si querés todos, no respondas (timeout)."
            )
        minutes = max(1, timeout_s // 60)
        lines.append(f"\n⏱ Sin respuesta en {minutes} min → se suben todos.")
        return "\n".join(lines)

    def _render_keyboard(
        self,
        items: list[tuple[Path, str]],
        visible: int,
        selected: set[int],
    ) -> list[list[dict[str, str]]]:
        rows: list[list[dict[str, str]]] = []
        for i in range(visible):
            path, _ = items[i]
            mark = "☑" if i in selected else "☐"
            rows.append([{
                "text": f"{mark}  {self._button_label(path)}",
                "callback_data": f"tog:{i}",
            }])
        rows.append([
            {"text": "✅ Confirmar", "callback_data": "ok"},
            {"text": "✖️ Cancelar", "callback_data": "cancel"},
        ])
        return rows

    def _button_label(self, path: Path) -> str:
        try:
            stat = path.stat()
            size_mb = stat.st_size / (1024 * 1024)
            if size_mb >= 1024:
                size_str = f"{size_mb / 1024:.1f} GB"
            else:
                size_str = f"{size_mb:.0f} MB"
            date_str = datetime.fromtimestamp(stat.st_mtime).strftime("%d-%m")
        except OSError:
            size_str = "?"
            date_str = "?"

        name = path.name
        if len(name) > NAME_MAX:
            name = name[: NAME_MAX - 1] + "…"
        return f"{name} · {size_str} · {date_str}"
