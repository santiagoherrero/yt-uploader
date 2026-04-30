# yt-uploader

Servicio para Ubuntu Server que detecta automáticamente cuando enchufás un disco
externo o pendrive a la mini PC, escanea archivos de video, los sube a YouTube
en privado y te avisa por Telegram con el progreso.

## Cómo funciona

1. Un servicio systemd corre permanentemente y escucha eventos de USB vía `pyudev`.
2. Cuando enchufás un disco/pendrive con sistema de archivos, lo monta en
   `/mnt/yt-uploader-<UUID>` (en modo solo-lectura por seguridad) si Ubuntu no
   lo montó antes.
3. Escanea recursivamente buscando archivos de video.
4. Por cada archivo calcula un fingerprint (`SHA-256` de los primeros 10 MB +
   tamaño). Si ya está en `uploaded.json`, se saltea.
5. Para los nuevos: copia a `/var/lib/yt-uploader/staging/`, sube a YouTube
   con upload resumable, registra el `video_id` y borra el archivo local.
6. Telegram: un mensaje por video que se va editando con el progreso (cada 10%)
   y termina con el link al video.

## Instalación

Todo se hace por SSH, sin browser en la mini PC.

```bash
# 1. Cloná el repo en la mini PC
git clone <URL_DEL_REPO> /opt/yt-uploader/src
cd /opt/yt-uploader/src

# 2. Corré el instalador (apt deps, venv, systemd unit)
sudo ./install.sh

# 3. Corré el wizard interactivo (guía completa para credenciales y config)
sudo /opt/yt-uploader/venv/bin/yt-uploader-setup
```

El wizard te pide:
- Path al `client_secret.json` que descargaste de Google Cloud (paso a paso te
  dice cómo crearlo si no lo tenés todavía).
- Te abre el flow OAuth con instrucciones claras para hacer port-forward por SSH
  desde tu laptop (porque la mini PC no tiene browser).
- El token del bot de Telegram (te dice cómo crearlo con @BotFather).
- **Detecta el `chat_id` solo** — solo tenés que mandarle un mensaje al bot
  desde tu cuenta y el wizard lo captura.
- Privacidad por defecto, plantilla de título, categoría, descripción.
- Habilita y arranca el servicio.

Al final tenés todo corriendo y deberías recibir un mensaje
"🟢 yt-uploader iniciado" en Telegram.

### Requisitos previos en navegador (no automatizable)

El wizard te lleva paso a paso por estos dos setups que necesariamente requieren
hacer clicks en una web:

1. **Proyecto en Google Cloud + OAuth client** — el wizard te muestra los pasos
   exactos. Recomendado: creá un Gmail dedicado y dale acceso de **Manager** al
   canal de la iglesia desde
   [YouTube Studio → Settings → Permissions](https://studio.youtube.com).
2. **Bot de Telegram** — `/newbot` en [@BotFather](https://t.me/BotFather).

> ⚠️ La app de Google Cloud queda en modo "Testing". Para el scope `youtube.upload`,
> los refresh tokens vencen cada 7 días. En la práctica, si subís al menos un
> video por semana, el token se mantiene activo. Si vence, vas a recibir un aviso
> por Telegram y volvés a correr el wizard (el setup de Telegram lo podés
> saltear, solo te re-autenticás con Google).

## Probar sin esperar a un disco real

```bash
sudo /opt/yt-uploader/venv/bin/yt-uploader \
    --config /etc/yt-uploader/config.toml \
    --scan /ruta/a/carpeta/con/un/video
```

## Operación

| Acción | Comando |
| --- | --- |
| Ver logs en vivo | `sudo journalctl -u yt-uploader -f` |
| Estado del servicio | `sudo systemctl status yt-uploader` |
| Reiniciar | `sudo systemctl restart yt-uploader` |
| Re-configurar | `sudo /opt/yt-uploader/venv/bin/yt-uploader-setup` |
| Re-autenticar YouTube | mismo wizard, te detecta lo ya hecho y solo hace el OAuth de nuevo |

## Archivos y rutas

| Qué | Dónde |
| --- | --- |
| Código fuente | `/opt/yt-uploader/src` |
| venv | `/opt/yt-uploader/venv` |
| Config | `/etc/yt-uploader/config.toml` |
| OAuth client | `/etc/yt-uploader/client_secret.json` |
| OAuth token | `/etc/yt-uploader/token.json` |
| Estado de subidos | `/var/lib/yt-uploader/uploaded.json` |
| Staging temporal | `/var/lib/yt-uploader/staging/` |
| Logs | `journalctl -u yt-uploader` |

## Notas

- El servicio corre como `root` para poder montar/desmontar discos. Los archivos
  sensibles (`token.json`, `config.toml`) están con `chmod 600`.
- Los discos se montan en **read-only** por defecto. Configurable en `config.toml`.
- Si Ubuntu (vía `udisks2`) ya monta el disco automáticamente, lo detectamos y
  reusamos ese mount point en vez de montar uno nuevo.
- El staging se borra inmediatamente después de un upload exitoso. También
  se limpia al arrancar el servicio (recovery de uploads interrumpidos).
- Cuota de YouTube API: cada upload consume ~1600 unidades; el límite por
  defecto del proyecto son 10.000/día (≈6 uploads). Más que suficiente para una
  prédica semanal.
