import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from .config import Config
from .fingerprint import compute as compute_fingerprint
from .notifier import TelegramNotifier, esc, progress_bar
from .selector import VideoSelector
from .state import State
from .youtube import AuthError, YouTubeUploader

log = logging.getLogger(__name__)

COPY_CHUNK = 4 * 1024 * 1024


class Processor:
    def __init__(
        self,
        config: Config,
        state: State,
        youtube: YouTubeUploader,
        telegram: TelegramNotifier,
        selector: VideoSelector,
    ) -> None:
        self._cfg = config
        self._state = state
        self._yt = youtube
        self._tg = telegram
        self._selector = selector

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
                f"📂 Disco detectado en <code>{esc(mount_path)}</code>\n"
                "No se encontraron archivos de video."
            )
            return

        if not new_items:
            self._tg.send(
                f"📂 Disco detectado en <code>{esc(mount_path)}</code>\n"
                f"Todos los videos ({len(videos)}) ya están subidos."
            )
            return

        if self._cfg.selection.enabled:
            selected_idx = self._selector.choose(
                new_items,
                mount_path,
                self._cfg.selection.timeout_seconds,
            )
            if not selected_idx:
                return
            to_upload = [new_items[i] for i in selected_idx]
        else:
            self._tg.send(
                f"📂 Disco detectado en <code>{esc(mount_path)}</code>\n"
                f"<b>{len(new_items)}</b> video(s) nuevo(s) para subir."
            )
            to_upload = new_items

        for idx, (path, fp) in enumerate(to_upload, start=1):
            try:
                self._upload_one(path, fp, idx, len(to_upload))
            except AuthError as e:
                log.exception("Auth error during upload")
                self._tg.send(
                    "🔑 <b>Error de autenticación de YouTube</b>\n"
                    f"<pre>{esc(e)}</pre>\n"
                    "Re-ejecutá <code>yt-uploader-auth</code> y reiniciá el servicio."
                )
                return
            except Exception as e:
                log.exception("Upload failed for %s", path)
                self._tg.send(
                    f"❌ Error subiendo <code>{esc(path.name)}</code>:\n"
                    f"<pre>{esc(e)}</pre>"
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
        size_bytes = source.stat().st_size
        size_mb = size_bytes / (1024 * 1024)

        msg_id = self._tg.send(
            f"🎥 {esc(prefix)}<b>{esc(title)}</b>\n"
            f"Origen: <code>{esc(source.name)}</code> ({size_mb:.0f} MB)\n"
            f"Copiando: {progress_bar(0)} 0%"
        )

        staging_dir = self._cfg.paths.staging_dir
        staging_dir.mkdir(parents=True, exist_ok=True)

        free = shutil.disk_usage(staging_dir).free
        if free < size_bytes + 256 * 1024 * 1024:
            need_mb = size_bytes / (1024 * 1024)
            free_mb = free / (1024 * 1024)
            self._tg.edit(
                msg_id,
                f"❌ {esc(prefix)}<b>{esc(title)}</b>\n"
                f"Sin espacio en la mini PC para staging.\n"
                f"Necesarios: {need_mb:.0f} MB · Libres: {free_mb:.0f} MB",
            )
            raise OSError(
                f"Insufficient disk space at {staging_dir}: "
                f"need {size_bytes}, have {free}"
            )

        staging = staging_dir / source.name
        try:
            self._copy_with_progress(
                source,
                staging,
                self._make_progress_reporter(
                    msg_id,
                    label=f"🎥 {esc(prefix)}<b>{esc(title)}</b>\nCopiando",
                ),
            )
        except Exception as e:
            self._tg.edit(
                msg_id,
                f"❌ {esc(prefix)}<b>{esc(title)}</b>\n"
                f"Fallo al copiar: <pre>{esc(e)}</pre>",
            )
            staging.unlink(missing_ok=True)
            raise

        try:
            self._tg.edit(
                msg_id,
                f"🎥 {esc(prefix)}<b>{esc(title)}</b>\n"
                f"Subiendo: {progress_bar(0)} 0%",
            )

            video_id = self._yt.upload(
                file_path=staging,
                title=title,
                description=self._cfg.youtube.description,
                privacy=self._cfg.youtube.default_privacy,
                category_id=self._cfg.youtube.category_id,
                made_for_kids=self._cfg.youtube.made_for_kids,
                on_progress=self._make_progress_reporter(
                    msg_id,
                    label=f"🎥 {esc(prefix)}<b>{esc(title)}</b>\nSubiendo",
                ),
            )

            self._state.record(fingerprint, source.name, video_id, title)

            url = f"https://youtu.be/{video_id}"
            self._tg.edit(
                msg_id,
                f"✅ {esc(prefix)}<b>{esc(title)}</b>\n"
                f"Subido como <i>{esc(self._cfg.youtube.default_privacy)}</i>: {url}",
            )
        finally:
            try:
                staging.unlink(missing_ok=True)
            except OSError:
                log.exception("Failed to delete staging file %s", staging)

    def _make_progress_reporter(
        self,
        msg_id: Optional[int],
        label: str,
    ) -> Callable[[int], None]:
        step = max(1, self._cfg.upload.progress_step_pct)
        last = {"pct": -step}

        def report(pct: int) -> None:
            if pct - last["pct"] >= step or pct >= 100:
                last["pct"] = pct
                self._tg.edit(msg_id, f"{label}: {progress_bar(pct)} {pct}%")

        return report

    def _copy_with_progress(
        self,
        src: Path,
        dst: Path,
        on_progress: Callable[[int], None],
    ) -> None:
        size = src.stat().st_size
        copied = 0
        with src.open("rb") as fs, dst.open("wb") as fd:
            while True:
                buf = fs.read(COPY_CHUNK)
                if not buf:
                    break
                fd.write(buf)
                copied += len(buf)
                if size > 0:
                    on_progress(int(copied * 100 / size))
        shutil.copystat(src, dst)
