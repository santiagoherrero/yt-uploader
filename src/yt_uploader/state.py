import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock


class State:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(json.dumps({"uploads": []}, indent=2))
        self._data = json.loads(self.path.read_text() or '{"uploads": []}')
        if "uploads" not in self._data:
            self._data["uploads"] = []

    def is_uploaded(self, fingerprint: str) -> bool:
        with self._lock:
            return any(u["fingerprint"] == fingerprint for u in self._data["uploads"])

    def record(
        self,
        fingerprint: str,
        source_filename: str,
        video_id: str,
        title: str,
    ) -> None:
        with self._lock:
            self._data["uploads"].append(
                {
                    "fingerprint": fingerprint,
                    "source_filename": source_filename,
                    "video_id": video_id,
                    "title": title,
                    "uploaded_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            self._save_locked()

    def _save_locked(self) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._data, indent=2))
        tmp.replace(self.path)
