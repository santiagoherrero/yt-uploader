import argparse
import logging
import sys
from pathlib import Path

from . import config as config_mod
from .daemon import DiskWatcher
from .notifier import TelegramNotifier
from .processor import Processor
from .state import State
from .youtube import AuthError, YouTubeUploader

DEFAULT_CONFIG = Path("/etc/yt-uploader/config.toml")


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def _cleanup_staging(staging_dir: Path, log: logging.Logger) -> None:
    if not staging_dir.exists():
        return
    cleaned = 0
    for entry in staging_dir.iterdir():
        if not entry.is_file():
            continue
        try:
            size = entry.stat().st_size
            entry.unlink()
            cleaned += 1
            log.info("Cleaned stale staging file: %s (%.0f MB)", entry.name, size / (1024 * 1024))
        except OSError:
            log.exception("Failed to clean staging file %s", entry)
    if cleaned:
        log.info("Removed %d stale staging file(s)", cleaned)


def main() -> None:
    parser = argparse.ArgumentParser(description="YouTube auto-uploader daemon")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help=f"Path to config.toml (default: {DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--scan",
        type=Path,
        default=None,
        help="Process a single mount path immediately and exit (for manual testing)",
    )
    args = parser.parse_args()

    _setup_logging()
    log = logging.getLogger("yt-uploader")

    if not args.config.exists():
        log.error("Config not found at %s", args.config)
        sys.exit(1)

    cfg = config_mod.load(args.config)

    state = State(cfg.paths.state_file)
    telegram = TelegramNotifier(cfg.telegram.bot_token, cfg.telegram.chat_id)

    try:
        youtube = YouTubeUploader(
            token_path=cfg.youtube.token_path,
            chunk_size_bytes=cfg.upload.chunk_size_bytes,
            max_retries=cfg.upload.max_retries,
        )
    except AuthError as e:
        log.error("YouTube auth error: %s", e)
        telegram.send(f"🔑 yt-uploader no pudo arrancar: {e}")
        sys.exit(2)

    processor = Processor(cfg, state, youtube, telegram)

    if args.scan is not None:
        processor.process_mount(args.scan)
        return

    _cleanup_staging(cfg.paths.staging_dir, log)

    telegram.send(
        "🟢 <b>yt-uploader iniciado</b>\n"
        "Listo para procesar discos USB / tarjetas SD."
    )

    watcher = DiskWatcher(
        processor=processor,
        telegram=telegram,
        settle_seconds=cfg.detection.mount_settle_seconds,
        read_only=cfg.detection.read_only_mount,
    )
    watcher.run()


if __name__ == "__main__":
    main()
