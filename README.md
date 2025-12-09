## Local Whisper Backend (large-v3-turbo)

Run `whisper_server.py` to host an OpenAI-compatible `/v1/audio/transcriptions` endpoint powered by [faster-whisper](https://github.com/SYSTRAN/faster-whisper). It defaults to the `large-v3-turbo` model.

### Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Optoinal: Install FFmpeg development libraries (for audio format support)

```bash
sudo apt install pkg-config libavdevice-dev libavfilter-dev libavformat-dev libavutil-dev libswscale-dev libswresample-dev libavcodec-dev
```

### Start the Whisper server

```bash
export LOCAL_WHISPER_MODEL=large-v3-turbo          # optional, defaults to large-v3-turbo
export LOCAL_WHISPER_DEVICE=auto                   # e.g. cuda, cpu, auto
export LOCAL_WHISPER_COMPUTE_TYPE=float16          # use int8/int8_float32 on CPU
uvicorn whisper_server:app --host 0.0.0.0 --port 9000
```

If a compute type is unsupported (for example `float16` on CPU), the server automatically retries with int8- or auto-based modes so transcriptions continue working. The service also aliases `large-v3-turbo` to `large-v3` because faster-whisper does not provide the OpenAI naming variant.

The server exposes:

- `POST /v1/audio/transcriptions` – accepts multipart/form-data (`file`, optional `model`) or allows `?model=` as a query parameter and returns OpenAI-style JSON with `text` and `segments`.
- `GET /healthz` – readiness probe.

### Example request (curl)

```bash
curl -sS -X POST http://127.0.0.1:9000/v1/audio/transcriptions \
  -H "Accept: application/json" \
  -F "file=@file_0.oga;filename=file_0.oga;type=audio/ogg" \
  -F "model=small"
```

### Wire it up to the main API

In the environment that runs `main.py`, point the integration to the local server:

```bash
export WHISPER_BASE_URL=http://127.0.0.1:9000/v1
export WHISPER_MODEL=large-v3-turbo
export TMP_DIR=/tmp/yt-audio
uvicorn main:app --host 0.0.0.0 --port 5005
```

Your YouTube transcription endpoint will now fall back to the self-hosted Whisper large-v3-turbo server whenever subtitles are unavailable.

### Run as a systemd service

1. Update `User=` and the absolute paths in `whisper-local-api.service` if your repo lives somewhere other than `/mnt/ssd/whisper-local-api`.
2. Optionally create `/etc/default/whisper-local-api` to override defaults (e.g. `LOCAL_WHISPER_MODEL=large-v3-turbo`, `LOCAL_WHISPER_DEVICE=auto`, `LOCAL_WHISPER_COMPUTE_TYPE=float16`).
3. Install and enable the service:
   ```bash
   sudo cp whisper-local-api.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now whisper-local-api.service
   ```
4. Check status and logs:
   ```bash
   systemctl status whisper-local-api.service
   journalctl -u whisper-local-api.service -f
   ```

### Notes and troubleshooting

- Models must already be present on disk; if a requested model is missing the API returns `503` with guidance to download it first.
- Successful requests log a short transcript preview to help spot test results in the logs.
- The server will fall back to a supported compute type if the preferred one (e.g., `float16` on CPU) fails.

### Run the test suite

Tests live in `tests/test_whisper_server.py` and use the bundled `test-speech.mp3` fixture; they mock the transcription call so they run offline and quickly.

```bash
source .venv/bin/activate
pytest
```
