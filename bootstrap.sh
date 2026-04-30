#!/bin/bash
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    echo "Este script tiene que correr como root."
    echo "Uso: curl -fsSL https://raw.githubusercontent.com/santiagoherrero/yt-uploader/main/bootstrap.sh | sudo bash"
    exit 1
fi

# When piped through curl, stdin is the pipe — re-attach to TTY so the
# interactive wizard at the end can read user input.
if [ ! -t 0 ] && [ -e /dev/tty ]; then
    exec < /dev/tty
fi

REPO_URL="${YT_UPLOADER_REPO:-https://github.com/santiagoherrero/yt-uploader.git}"
REPO_BRANCH="${YT_UPLOADER_BRANCH:-main}"
SRC_DIR="/opt/yt-uploader/src"

if ! command -v git >/dev/null 2>&1; then
    echo "==> Instalando git..."
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y git
fi

if [ -d "$SRC_DIR/.git" ]; then
    echo "==> Repo ya existe en $SRC_DIR, actualizando..."
    git -C "$SRC_DIR" fetch origin "$REPO_BRANCH"
    git -C "$SRC_DIR" checkout "$REPO_BRANCH"
    git -C "$SRC_DIR" pull --ff-only
else
    echo "==> Clonando repo en $SRC_DIR..."
    mkdir -p "$(dirname "$SRC_DIR")"
    git clone --branch "$REPO_BRANCH" --progress "$REPO_URL" "$SRC_DIR"
fi

"$SRC_DIR/install.sh"

echo
echo "==> Iniciando el wizard de configuración..."
echo
exec /opt/yt-uploader/venv/bin/yt-uploader-setup
