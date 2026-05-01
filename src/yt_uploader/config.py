from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class YouTubeConfig:
    client_secret_path: Path
    token_path: Path
    default_privacy: str
    title_template: str
    description: str
    category_id: str
    made_for_kids: bool


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    chat_id: str


@dataclass(frozen=True)
class PathsConfig:
    staging_dir: Path
    state_file: Path


@dataclass(frozen=True)
class DetectionConfig:
    video_extensions: frozenset[str]
    mount_settle_seconds: int
    read_only_mount: bool


@dataclass(frozen=True)
class UploadConfig:
    chunk_size_bytes: int
    progress_step_pct: int
    max_retries: int


@dataclass(frozen=True)
class SelectionConfig:
    enabled: bool
    timeout_seconds: int


@dataclass(frozen=True)
class Config:
    youtube: YouTubeConfig
    telegram: TelegramConfig
    paths: PathsConfig
    detection: DetectionConfig
    upload: UploadConfig
    selection: SelectionConfig


def load(path: Path) -> Config:
    with path.open("rb") as f:
        raw = tomllib.load(f)

    yt = raw["youtube"]
    tg = raw["telegram"]
    pa = raw["paths"]
    de = raw["detection"]
    up = raw["upload"]
    se = raw.get("selection", {})

    return Config(
        youtube=YouTubeConfig(
            client_secret_path=Path(yt["client_secret_path"]),
            token_path=Path(yt["token_path"]),
            default_privacy=yt.get("default_privacy", "private"),
            title_template=yt.get("title_template", "Prédica – {date}"),
            description=yt.get("description", ""),
            category_id=str(yt.get("category_id", "22")),
            made_for_kids=bool(yt.get("made_for_kids", False)),
        ),
        telegram=TelegramConfig(
            bot_token=tg["bot_token"],
            chat_id=str(tg["chat_id"]),
        ),
        paths=PathsConfig(
            staging_dir=Path(pa["staging_dir"]),
            state_file=Path(pa["state_file"]),
        ),
        detection=DetectionConfig(
            video_extensions=frozenset(
                e.lower() for e in de.get("video_extensions", [".mp4", ".mov", ".mkv"])
            ),
            mount_settle_seconds=int(de.get("mount_settle_seconds", 5)),
            read_only_mount=bool(de.get("read_only_mount", True)),
        ),
        upload=UploadConfig(
            chunk_size_bytes=int(up.get("chunk_size_mb", 8)) * 1024 * 1024,
            progress_step_pct=int(up.get("progress_step_pct", 10)),
            max_retries=int(up.get("max_retries", 5)),
        ),
        selection=SelectionConfig(
            enabled=bool(se.get("enabled", True)),
            timeout_seconds=int(se.get("timeout_seconds", 600)),
        ),
    )
