#!/bin/bash
set -euo pipefail

if [ "$EUID" -ne 0 ]; then
    echo "Este instalador requiere root. Ejecutá: sudo $0" >&2
    exit 1
fi

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> Instalando dependencias del sistema..."
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    python3-venv python3-pip

echo "==> Creando directorios..."
install -d -m 755 /opt/yt-uploader
install -d -m 700 /etc/yt-uploader
install -d -m 755 /var/lib/yt-uploader
install -d -m 755 /var/lib/yt-uploader/staging

echo "==> Creando virtualenv en /opt/yt-uploader/venv..."
python3 -m venv /opt/yt-uploader/venv
/opt/yt-uploader/venv/bin/pip install --upgrade pip
echo "==> Instalando dependencias Python (esto puede tardar 2-5 minutos)..."
/opt/yt-uploader/venv/bin/pip install -e "$SRC_DIR"

echo "==> Instalando systemd unit..."
cp "$SRC_DIR/systemd/yt-uploader.service" /etc/systemd/system/yt-uploader.service
systemctl daemon-reload

echo
echo "✅ Instalación de archivos completa."
echo
echo "Siguiente paso: configurá el servicio con el wizard interactivo:"
echo
echo "    sudo /opt/yt-uploader/venv/bin/yt-uploader-setup"
echo
echo "El wizard te va a guiar por las credenciales de YouTube y Telegram."
echo
