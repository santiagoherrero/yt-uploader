import logging
import shutil
from datetime import datetime
from pathlib import Path

from .config import Config
from .fingerprint import compute as compute_fingerprint
from .notifier import TelegramNotifier, progress_bar
from .state import State
from .youtube import AuthError, YouTubeUploader

log = logging.getLogger(__name__)


class Processor:
    def __init__(
        self,
        config: Config,
        state: State,
        youtube: YouTubeUploader,
        telegram: TelegramNotifier,
    ) -> None:
        self._cfg = config
        self._state = state
        self._yt = youtube
        self._tg = telegram

    def process_mount(self, mount_path: Path) -> None:
        videos = self._scan(mount_path)
        log.info("Found %d candidate video(s) at %s", len(videos), mount_path)

        new_items: list[tuple[Path, str]] = []
        for v in videos:
            try:
                fp = compute_fingerprint(v)
            except OSError:
                log.exception("Failed to fingerprint %s", v)
                continue
            if not self._state.is_uploaded(fp):
                new_items.append((v, fp))

        if not videos:
            self._tg.send(
                f"📂 Disco detectado en <code>{mount_path}</code>\n"
                "No se encontraron archivos de video."
            )
            return

        if not new_items:
            self._tg.send(
                f"📂 Disco detectado en <code>{mount_path}</code>\n"
                f"Todos los videos ({len(videos)}) ya están subidos."
            )
            return

        self._tg.send(
            f"📂 Disco detectado en <code>{mount_path}</code>\n"
            f"<b>{len(new_items)}</b> video(s) nuevo(s) para subir."
        )

        for idx, (path, fp) in enumerate(new_items, start=1):
            try:
                self._upload_one(path, fp, idx, len(new_items))
            except AuthError as e:
                log.exception("Auth error during upload")
                self._tg.send(
                    "🔑 <b>Error de autenticación de YouTube</b>\n"
                    f"{e}\n\n"
                    "Re-ejecutá <code>yt-uploader-auth</code> y reiniciá el servicio."
                )
                return
            except Exception as e:
                log.exception("Upload failed for %s", path)
                self._tg.send(
                    f"❌ Error subiendo <code>{path.name}</code>:\n<pre>{e}</pre>"
                )

    def _scan(self, mount_path: Path) -> list[Path]:
        exts = self._cfg.detection.video_extensions
        out: list[Path] = []
        for p in mount_path.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() not in exts:
                continue
            if any(part.startswith(".") for part in p.relative_to(mount_path).parts):
                continue
            out.append(p)
        out.sort(key=lambda p: p.stat().st_mtime)
        return out

    def _title_for(self, path: Path) -> str:
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        return self._cfg.youtube.title_template.format(
            date=mtime.strftime("%Y-%m-%d"),
            datetime=mtime.strftime("%Y-%m-%d %H:%M"),
            filename=path.stem,
        )

    def _upload_one(
        self,
        source: Path,
        fingerprint: str,
        idx: int,
        total: int,
    ) -> None:
        title = self._title_for(source)
        prefix = f"[{idx}/{total}] " if total > 1 else ""
        size_mb = source.stat().st_size / (1024 * 1024)

        msg_id = self._tg.send(
            f"🎥 {prefix}<b>{title}</b>\n"
            f"Origen: <code>{source.name}</code> ({size_mb:.0f} MB)\n"
            "Copiando del disco a la mini PC..."
        )

        staging_dir = self._cfg.paths.staging_dir
        staging_dir.mkdir(parents=True, exist_ok=True)
        staging = staging_dir / source.name
        try:
            shutil.copy2(source, staging)
        except Exception as e:
            self._tg.edit(
                msg_id,
                f"❌ {prefix}<b>{title}</b>\nFallo al copiar: <pre>{e}</pre>",
            )
            raise

        try:
            self._tg.edit(
                msg_id,
                f"🎥 {prefix}<b>{title}</b>\n"
                f"Subiendo: {progress_bar(0)} 0%",
            )

            step = max(1, self._cfg.upload.progress_step_pct)
            last_reported = {"pct": -step}

            def on_progress(pct: int) -> None:
                if pct - last_reported["pct"] >= step or pct >= 100:
                    last_reported["pct"] = pct
                    self._tg.edit(
                        msg_id,
                        f"🎥 {prefix}<b>{title}</b>\n"
                        f"Subiendo: {progress_bar(pct)} {pct}%",
                    )

            video_id = self._yt.upload(
                file_path=staging,
                title=title,
                description=self._cfg.youtube.description,
                privacy=self._cfg.youtube.default_privacy,
                category_id=self._cfg.youtube.category_id,
                made_for_kids=self._cfg.youtube.made_for_kids,
                on_progress=on_progress,
            )

            self._state.record(fingerprint, source.name, video_id, title)

            url = f"https://youtu.be/{video_id}"
            self._tg.edit(
                msg_id,
                f"✅ {prefix}<b>{title}</b>\n"
                f"Subido como <i>{self._cfg.youtube.default_privacy}</i>: {url}",
            )
        finally:
            try:
                staging.unlink(missing_ok=True)
            except OSError:
                log.exception("Failed to delete staging file %s", staging)
