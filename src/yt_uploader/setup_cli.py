import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import httpx

ETC_DIR = Path("/etc/yt-uploader")
LIB_DIR = Path("/var/lib/yt-uploader")
CLIENT_SECRET_PATH = ETC_DIR / "client_secret.json"
TOKEN_PATH = ETC_DIR / "token.json"
CONFIG_PATH = ETC_DIR / "config.toml"
OAUTH_PORT = 8090
OAUTH_TIMEOUT_SECONDS = 600
TELEGRAM_WAIT_SECONDS = 300

C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_GREEN = "\033[32m"
C_RED = "\033[31m"
C_YELLOW = "\033[33m"
C_CYAN = "\033[36m"


def bold(s: str) -> str:
    return f"{C_BOLD}{s}{C_RESET}"


def dim(s: str) -> str:
    return f"{C_DIM}{s}{C_RESET}"


def green(s: str) -> str:
    return f"{C_GREEN}{s}{C_RESET}"


def red(s: str) -> str:
    return f"{C_RED}{s}{C_RESET}"


def yellow(s: str) -> str:
    return f"{C_YELLOW}{s}{C_RESET}"


def cyan(s: str) -> str:
    return f"{C_CYAN}{s}{C_RESET}"


def header(title: str) -> None:
    print()
    print(bold(cyan("─" * 60)))
    print(bold(cyan(f"  {title}")))
    print(bold(cyan("─" * 60)))
    print()


def ok(msg: str) -> None:
    print(green(f"✓ {msg}"))


def warn(msg: str) -> None:
    print(yellow(f"⚠ {msg}"))


def err(msg: str) -> None:
    print(red(f"✗ {msg}"))


def ask(prompt: str, default: Optional[str] = None) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        try:
            value = input(f"{prompt}{suffix}: ").strip()
        except EOFError:
            sys.exit(1)
        if value:
            return value
        if default is not None:
            return default


def confirm(prompt: str, default: bool = True) -> bool:
    suffix = "[S/n]" if default else "[s/N]"
    while True:
        try:
            value = input(f"{prompt} {suffix}: ").strip().lower()
        except EOFError:
            sys.exit(1)
        if not value:
            return default
        if value in ("s", "si", "sí", "y", "yes"):
            return True
        if value in ("n", "no"):
            return False


def choose(prompt: str, options: list[tuple[str, str]], default: int = 0) -> str:
    print(prompt)
    for i, (_, label) in enumerate(options, 1):
        marker = "*" if (i - 1) == default else " "
        print(f"  {marker} {i}. {label}")
    while True:
        try:
            raw = input(f"Elegí 1-{len(options)} [{default + 1}]: ").strip()
        except EOFError:
            sys.exit(1)
        if not raw:
            return options[default][0]
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        err(f"Entrada inválida: {raw}")


def require_root() -> None:
    if os.geteuid() != 0:
        err("Este wizard necesita root. Ejecutá: sudo yt-uploader-setup")
        sys.exit(1)


def detect_ssh_host() -> str:
    ssh_conn = os.environ.get("SSH_CONNECTION")
    if ssh_conn:
        try:
            return socket.gethostname()
        except Exception:
            pass
    return socket.gethostname()


# ---------- Step 1: YouTube ----------

GOOGLE_CLOUD_INSTRUCTIONS = """\
Para subir videos a YouTube necesitás un OAuth client de Google Cloud.

Si todavía no lo tenés, hacé esto en tu laptop (en otra ventana del browser):

  1. Andá a https://console.cloud.google.com/projectcreate y creá un proyecto.
  2. APIs & Services → Library → habilitá "YouTube Data API v3".
  3. APIs & Services → OAuth consent screen → External →
     Completá los datos mínimos.
     En "Test users" agregá el Gmail con el que vas a autenticar
     (idealmente uno dedicado con acceso de Manager al canal).
  4. APIs & Services → Credentials → Create Credentials →
     OAuth client ID → Application type: Desktop app.
  5. Descargá el JSON. Va a llamarse algo como
     client_secret_xxxx.apps.googleusercontent.com.json

Tip: copiá ese archivo a esta mini PC con scp:
  scp ~/Downloads/client_secret_*.json {host}:/tmp/cs.json
"""


def _validate_client_secret(path: Path) -> bool:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        err(f"No se pudo leer/parsear: {e}")
        return False
    if "installed" not in data and "web" not in data:
        err("El JSON no parece un OAuth client (falta 'installed' o 'web').")
        return False
    return True


def step_youtube() -> None:
    header("Paso 1/4: Cuenta de Google / YouTube")

    if CLIENT_SECRET_PATH.exists():
        ok(f"Ya hay un client_secret en {CLIENT_SECRET_PATH}")
        if not confirm("¿Querés reemplazarlo?", default=False):
            print(dim("Reusando client_secret existente."))
        else:
            CLIENT_SECRET_PATH.unlink()

    if not CLIENT_SECRET_PATH.exists():
        print(GOOGLE_CLOUD_INSTRUCTIONS.format(host=detect_ssh_host()))
        while True:
            raw = ask("Pegá la ruta al client_secret.json")
            src = Path(os.path.expanduser(raw))
            if not src.exists():
                err(f"No existe: {src}")
                continue
            if not _validate_client_secret(src):
                continue
            shutil.copy(src, CLIENT_SECRET_PATH)
            CLIENT_SECRET_PATH.chmod(0o600)
            ok(f"Copiado a {CLIENT_SECRET_PATH}")
            break

    if TOKEN_PATH.exists():
        ok(f"Ya existe un token en {TOKEN_PATH}")
        if not confirm("¿Querés generar uno nuevo (re-autenticar)?", default=False):
            print(dim("Reusando token existente."))
            return
        TOKEN_PATH.unlink()

    _run_oauth_flow()


def _run_oauth_flow() -> None:
    print()
    print(bold("Autenticación de YouTube"))
    print()
    print(
        "Como no hay browser en esta mini PC, necesitamos hacer\n"
        "un port-forward por SSH para que el redirect de Google\n"
        "vuelva acá. Sigue estos pasos:"
    )
    print()
    print(bold("  EN TU LAPTOP, abrí otra terminal y corré:"))
    print()
    print(cyan(f"    ssh -L {OAUTH_PORT}:localhost:{OAUTH_PORT} {detect_ssh_host()}"))
    print()
    print(
        "Eso te abre una segunda sesión SSH con el puerto reenviado.\n"
        "Mantenela abierta hasta que termine este paso."
    )
    print()
    input(bold("Cuando lo tengas listo, presioná Enter para continuar... "))

    from google_auth_oauthlib.flow import InstalledAppFlow

    SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
    flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), SCOPES)

    print()
    print(bold("Abrí este link en el browser de tu laptop:"))
    print()

    try:
        creds = flow.run_local_server(
            host="127.0.0.1",
            port=OAUTH_PORT,
            open_browser=False,
            authorization_prompt_message="    {url}\n",
            success_message="¡Listo! Volvé a la terminal del wizard.",
            timeout_seconds=OAUTH_TIMEOUT_SECONDS,
            access_type="offline",
            prompt="consent",
        )
    except Exception as e:
        err(f"Falló el flow OAuth: {e}")
        raise

    TOKEN_PATH.write_text(creds.to_json())
    TOKEN_PATH.chmod(0o600)
    ok(f"Token guardado en {TOKEN_PATH}")


# ---------- Step 2: Telegram ----------

TELEGRAM_INSTRUCTIONS = """\
Necesitamos un bot de Telegram para mandarte notificaciones.

Si todavía no lo tenés:
  1. Abrí Telegram en cualquier dispositivo.
  2. Buscá @BotFather y abrí el chat.
  3. Mandale /newbot y seguí los pasos para nombrarlo.
  4. Te va a dar un token tipo 1234567890:ABCdef...

Pegalo acá abajo:
"""


def step_telegram() -> tuple[str, str]:
    header("Paso 2/4: Bot de Telegram")
    print(TELEGRAM_INSTRUCTIONS)

    bot_token = _ask_bot_token()
    chat_id = _discover_chat_id(bot_token)
    return bot_token, chat_id


def _ask_bot_token() -> str:
    while True:
        token = ask("Bot token")
        try:
            r = httpx.get(
                f"https://api.telegram.org/bot{token}/getMe",
                timeout=10,
            )
            data = r.json()
        except Exception as e:
            err(f"No pude conectarme a Telegram: {e}")
            continue
        if not data.get("ok"):
            err(f"Token inválido: {data.get('description', data)}")
            continue
        bot = data["result"]
        ok(f"Bot @{bot.get('username', '?')} ({bot.get('first_name', '?')})")
        return token


def _discover_chat_id(bot_token: str) -> str:
    base = f"https://api.telegram.org/bot{bot_token}"

    try:
        r = httpx.get(f"{base}/getUpdates", timeout=10)
        existing = r.json().get("result", [])
        last_id = max((u["update_id"] for u in existing), default=0)
    except Exception:
        last_id = 0

    print()
    print(bold("Ahora abrí Telegram y mandale CUALQUIER mensaje a tu bot."))
    print(dim("Esperando hasta 5 minutos. Ctrl+C para cancelar."))
    print()

    deadline = time.time() + TELEGRAM_WAIT_SECONDS
    while time.time() < deadline:
        try:
            r = httpx.get(
                f"{base}/getUpdates",
                params={"offset": last_id + 1, "timeout": 25},
                timeout=30,
            )
            updates = r.json().get("result", [])
        except httpx.RequestError:
            time.sleep(2)
            continue

        for u in updates:
            last_id = max(last_id, u["update_id"])
            msg = u.get("message") or u.get("edited_message") or u.get("channel_post")
            if not msg or "chat" not in msg:
                continue
            chat = msg["chat"]
            chat_id = str(chat["id"])
            sender = chat.get("first_name", "")
            if chat.get("last_name"):
                sender = f"{sender} {chat['last_name']}".strip()
            sender = sender or chat.get("title") or chat.get("username") or "(sin nombre)"
            ok(f"Recibí mensaje de {bold(sender)} (chat_id: {chat_id})")
            if confirm("¿Es la cuenta donde querés recibir notificaciones?", default=True):
                return chat_id
            print(dim("OK, esperando otro mensaje..."))

    raise RuntimeError("No llegó ningún mensaje en 5 minutos. Volvé a correr el wizard.")


# ---------- Step 3: Config values ----------


def step_config_values(existing: Optional[dict] = None) -> dict:
    header("Paso 3/4: Configuración del upload")

    defaults = existing or {}

    privacy = choose(
        "Privacidad por defecto del upload:",
        [
            ("private", "Privado (recomendado — vos retocás antes de publicar)"),
            ("unlisted", "No listado (con link funciona, no aparece público)"),
            ("public", "Público inmediato"),
        ],
        default=0 if not defaults else ["private", "unlisted", "public"].index(
            defaults.get("privacy", "private")
        ),
    )

    print()
    print(dim("Plantilla de título. Variables disponibles: {date}, {datetime}, {filename}"))
    title_template = ask(
        "Plantilla de título",
        default=defaults.get("title_template", "Prédica – {date}"),
    )

    print()
    print(dim("Categoría 22 (People & Blogs) sirve para casi todo."))
    print(dim("29 = Nonprofits, requiere canal verificado como ONG."))
    category_id = ask(
        "Categoría YouTube",
        default=defaults.get("category_id", "22"),
    )

    print()
    description = ask(
        "Descripción default (vacío para ninguna)",
        default=defaults.get("description", ""),
    )

    return {
        "privacy": privacy,
        "title_template": title_template,
        "category_id": category_id,
        "description": description,
    }


# ---------- Write config file ----------


def _toml_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def write_config(
    bot_token: str,
    chat_id: str,
    values: dict,
) -> None:
    content = f"""\
# Generated by yt-uploader-setup. Re-run the wizard to update.

[youtube]
client_secret_path = "{CLIENT_SECRET_PATH}"
token_path         = "{TOKEN_PATH}"
default_privacy    = "{values['privacy']}"
title_template     = "{_toml_escape(values['title_template'])}"
description        = "{_toml_escape(values['description'])}"
category_id        = "{values['category_id']}"
made_for_kids      = false

[telegram]
bot_token = "{_toml_escape(bot_token)}"
chat_id   = "{chat_id}"

[paths]
staging_dir = "{LIB_DIR / 'staging'}"
state_file  = "{LIB_DIR / 'uploaded.json'}"

[detection]
video_extensions     = [".mp4", ".mov", ".mkv", ".m4v", ".avi", ".braw"]
mount_settle_seconds = 5
read_only_mount      = true

[upload]
chunk_size_mb     = 8
progress_step_pct = 10
max_retries       = 5
"""
    CONFIG_PATH.write_text(content)
    CONFIG_PATH.chmod(0o600)
    ok(f"Config escrito en {CONFIG_PATH}")


# ---------- Step 4: systemd ----------


def step_systemd(bot_token: str, chat_id: str) -> None:
    header("Paso 4/4: Servicio systemd")

    if not Path("/etc/systemd/system/yt-uploader.service").exists():
        warn("No encontré /etc/systemd/system/yt-uploader.service")
        warn("¿Corriste install.sh primero?")
        return

    if not confirm("¿Habilitar y arrancar el servicio ahora?", default=True):
        print(dim("Cuando estés listo: sudo systemctl enable --now yt-uploader"))
        return

    subprocess.run(
        ["systemctl", "enable", "yt-uploader"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["systemctl", "restart", "yt-uploader"],
        check=True,
        capture_output=True,
    )
    ok("Servicio habilitado y arrancado.")

    print()
    print(dim("Esperando 4 segundos para verificar que arrancó OK..."))
    time.sleep(4)

    result = subprocess.run(
        ["systemctl", "is-active", "yt-uploader"],
        capture_output=True,
        text=True,
    )
    if result.stdout.strip() == "active":
        ok("Servicio activo y corriendo.")
    else:
        err(f"El servicio no está activo: {result.stdout.strip()}")
        err("Mirá los logs con: sudo journalctl -u yt-uploader -n 50")
        return

    print()
    print(dim("Deberías haber recibido un mensaje '🟢 yt-uploader iniciado' en Telegram."))
    if not confirm("¿Lo recibiste?", default=True):
        warn("Revisá el bot_token y chat_id en /etc/yt-uploader/config.toml")
        warn("Logs: sudo journalctl -u yt-uploader -n 50")


# ---------- Main ----------


BANNER = """\
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║                yt-uploader · Setup Wizard                ║
║                                                          ║
║   Te voy a guiar para configurar el servicio en          ║
║   ~10 minutos. Podés cancelar con Ctrl+C en cualquier    ║
║   momento y volver a correrlo — guarda lo que ya está.   ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
"""


def main() -> None:
    require_root()

    print(BANNER)

    try:
        step_youtube()
        bot_token, chat_id = step_telegram()
        values = step_config_values()
        write_config(bot_token, chat_id, values)
        step_systemd(bot_token, chat_id)
    except KeyboardInterrupt:
        print()
        warn("Cancelado. Podés volver a correr el wizard cuando quieras.")
        sys.exit(130)
    except Exception as e:
        print()
        err(f"Falló el wizard: {e}")
        sys.exit(1)

    header("Listo")
    print(green(bold("✅ Setup completo.")))
    print()
    print("Para ver los logs en vivo:")
    print(cyan("  sudo journalctl -u yt-uploader -f"))
    print()
    print("Para probarlo, enchufá un pendrive con un video de prueba.")
    print("Vas a ver el progreso en Telegram en pocos segundos.")
    print()


if __name__ == "__main__":
    main()
