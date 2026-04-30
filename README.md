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

## Setup

### 1. Cuenta de YouTube y proyecto en Google Cloud

Recomendado: creá un Gmail dedicado (ej. `iglesia.uploader@gmail.com`) y dale
acceso de **Manager** al canal de la iglesia desde
[YouTube Studio → Settings → Permissions](https://studio.youtube.com).

Después, con ese Gmail:

1. Andá a [Google Cloud Console](https://console.cloud.google.com) y creá un proyecto.
2. APIs & Services → **Library** → habilitá **YouTube Data API v3**.
3. APIs & Services → **OAuth consent screen** → User Type **External** → completá
   los datos mínimos. Agregá tu Gmail como **Test user**.
4. APIs & Services → **Credentials** → **Create Credentials** → **OAuth client ID**
   → Application type **Desktop app**. Descargá el JSON como `client_secret.json`.

> ⚠️ La app queda en modo "Testing". Para el scope `youtube.upload` (sensitive),
> los refresh tokens vencen cada 7 días. En la práctica, si usás el servicio al
> menos una vez por semana, el token se mantiene activo. Si vence, vas a recibir
> un aviso por Telegram y tenés que correr `yt-uploader-auth` de nuevo.

### 2. Bot de Telegram

1. Abrí [@BotFather](https://t.me/BotFather), `/newbot`, seguí los pasos. Anotá el **token**.
2. Mandale un mensaje cualquiera a tu nuevo bot desde tu cuenta personal.
3. Conseguí tu `chat_id`:

```bash
curl "https://api.telegram.org/bot<TOKEN>/getUpdates" | python3 -m json.tool
```

   Buscá `"chat":{"id":...}` en la respuesta.

### 3. Instalar en la mini PC (Ubuntu Server)

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip git

sudo mkdir -p /opt/yt-uploader /etc/yt-uploader /var/lib/yt-uploader/staging
sudo git clone <ESTE_REPO> /opt/yt-uploader/src
sudo python3 -m venv /opt/yt-uploader/venv
sudo /opt/yt-uploader/venv/bin/pip install -e /opt/yt-uploader/src
```

### 4. Generar el token OAuth

El flujo OAuth necesita un browser. Tenés dos opciones:

**A) Hacerlo en otra máquina con browser** (recomendado):

```bash
# en tu laptop/desktop con browser
git clone <ESTE_REPO> /tmp/yt-uploader
cd /tmp/yt-uploader
python3 -m venv .venv && . .venv/bin/activate
pip install -e .
yt-uploader-auth ./client_secret.json ./token.json
# Se abre el browser, autorizás, vuelve a la terminal con "Token saved to ./token.json"
```

Después copiá los dos archivos a la mini PC:

```bash
scp client_secret.json token.json minipc:/tmp/
ssh minipc 'sudo mv /tmp/client_secret.json /tmp/token.json /etc/yt-uploader/ && sudo chmod 600 /etc/yt-uploader/{client_secret,token}.json'
```

**B) Directo en la mini PC vía SSH con port-forward**:

```bash
# desde tu laptop
ssh -L 8080:localhost:8080 minipc

# en la mini PC, dentro del venv:
sudo /opt/yt-uploader/venv/bin/yt-uploader-auth \
    /etc/yt-uploader/client_secret.json \
    /etc/yt-uploader/token.json \
    --port 8080
```

Copiá el link que imprime y abrilo en tu browser local.

### 5. Configurar

```bash
sudo cp /opt/yt-uploader/src/config.example.toml /etc/yt-uploader/config.toml
sudo nano /etc/yt-uploader/config.toml
# Pegá bot_token y chat_id de Telegram, ajustá lo que quieras.
sudo chmod 600 /etc/yt-uploader/config.toml
```

### 6. Instalar y arrancar el servicio

```bash
sudo cp /opt/yt-uploader/src/systemd/yt-uploader.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now yt-uploader
sudo systemctl status yt-uploader
journalctl -u yt-uploader -f
```

## Probar

Sin esperar a un disco real, podés correr una pasada manual contra cualquier
carpeta para verificar que los uploads funcionan:

```bash
sudo /opt/yt-uploader/venv/bin/yt-uploader \
    --config /etc/yt-uploader/config.toml \
    --scan /ruta/a/carpeta/con/un/video
```

## Archivos y rutas

| Qué | Dónde |
| --- | --- |
| Código | `/opt/yt-uploader/src` |
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
- El staging se borra inmediatamente después de un upload exitoso.
- Cuota de YouTube API: cada upload consume ~1600 unidades; el límite por
  defecto del proyecto son 10.000/día (≈6 uploads). Más que suficiente para una
  prédica semanal.
