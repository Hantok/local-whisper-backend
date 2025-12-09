from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Dict, List, Tuple

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from faster_whisper import WhisperModel

logger = logging.getLogger("local-whisper")
logging.basicConfig(level=logging.INFO)

DEFAULT_MODEL_NAME = os.getenv("LOCAL_WHISPER_MODEL", "large-v3-turbo")
WHISPER_DEVICE = os.getenv("LOCAL_WHISPER_DEVICE", "auto")
WHISPER_COMPUTE_TYPE = os.getenv("LOCAL_WHISPER_COMPUTE_TYPE", "auto")
WHISPER_BEAM_SIZE = int(os.getenv("LOCAL_WHISPER_BEAM_SIZE", "5"))

app = FastAPI(
    title="Local Whisper Server",
    version="1.0.0",
    description="OpenAI-compatible /v1/audio/transcriptions endpoint backed by faster-whisper.",
)

_MODEL_CACHE: Dict[str, WhisperModel] = {}
_MODEL_LOCK = threading.Lock()

MODEL_ALIASES = {
    "large-v3-turbo": "large-v3",
}

class ModelNotAvailableError(RuntimeError):
    """Raised when a requested model is not available locally."""


def _compute_type_candidates() -> List[str]:
    configured = (WHISPER_COMPUTE_TYPE or "auto").strip() or "auto"
    configured_lower = configured.lower()
    candidates: List[str] = []

    def add(candidate: str) -> None:
        if candidate and candidate not in candidates:
            candidates.append(candidate)

    add(configured)
    if configured_lower == "float16":
        add("int8_float32")
        add("int8")
    add("auto")
    return candidates


def normalize_model_name(requested_name: str | None) -> str:
    normalized = (requested_name or "").strip()
    normalized = normalized or DEFAULT_MODEL_NAME
    alias = MODEL_ALIASES.get(normalized.lower())
    if alias:
        logger.info("Model alias mapping applied: '%s' -> '%s'", normalized, alias)
        normalized = alias
    return normalized


def get_model(model_name: str) -> WhisperModel:
    normalized_name = normalize_model_name(model_name)
    with _MODEL_LOCK:
        if normalized_name in _MODEL_CACHE:
            return _MODEL_CACHE[normalized_name]

        last_error: Exception | None = None
        for compute_type in _compute_type_candidates():
            try:
                logger.info(
                    "Loading Whisper model '%s' (device=%s, compute_type=%s)",
                    normalized_name,
                    WHISPER_DEVICE,
                    compute_type,
                )
                model = WhisperModel(
                    normalized_name,
                    device=WHISPER_DEVICE,
                    compute_type=compute_type,
                )
                _MODEL_CACHE[normalized_name] = model
                return model
            except ValueError as exc:
                last_error = exc
                logger.warning(
                    "Failed to load Whisper model '%s' with compute_type=%s: %s",
                    normalized_name,
                    compute_type,
                    exc,
                )
                continue

        message = f"Unable to load Whisper model '{normalized_name}' with any compute type."
        if last_error:
            error_text = str(last_error).lower()
            missing = any(
                phrase in error_text
                for phrase in ["not found", "no such file", "could not be found"]
            )
            if missing:
                raise ModelNotAvailableError(
                    f"{message} Model files are not available locally."
                ) from last_error
            raise last_error
        raise RuntimeError(message)


def run_transcription(audio_path: Path, model_name: str) -> Tuple[str, List[Dict]]:
    model = get_model(model_name)
    segments_generator, _info = model.transcribe(
        str(audio_path),
        beam_size=WHISPER_BEAM_SIZE,
        vad_filter=True,
    )
    segments: List[Dict] = []
    collected_text: List[str] = []
    for index, segment in enumerate(segments_generator):
        text = (segment.text or "").strip()
        if text:
            collected_text.append(text)
        segments.append(
            {
                "id": index,
                "seek": 0,
                "start": segment.start,
                "end": segment.end,
                "text": segment.text,
                "tokens": segment.tokens,
                "temperature": 0.0,
                "avg_logprob": segment.avg_logprob,
                "compression_ratio": segment.compression_ratio,
                "no_speech_prob": segment.no_speech_prob,
            }
        )
    full_text = " ".join(collected_text).strip()
    return full_text, segments


@app.post("/v1/audio/transcriptions")
async def create_transcription(
    request: Request,
    file: UploadFile = File(...),
    model: str | None = Form(None, alias="model"),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Uploaded file must include a filename.")

    try:
        file_bytes = await file.read()
    except Exception as exc:
        logger.exception("Failed to read upload: %s", exc)
        raise HTTPException(status_code=400, detail="Unable to read uploaded file.")

    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    suffix = Path(file.filename).suffix or ".mp3"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
        tmp_file.write(file_bytes)
        temp_path = Path(tmp_file.name)

    selected_model = normalize_model_name(model or request.query_params.get("model"))
    logger.info(
        "Received transcription request file=%s size=%.2f MB model=%s",
        file.filename,
        len(file_bytes) / (1024 * 1024),
        selected_model,
    )

    try:
        start_time = time.monotonic()
        full_text, segments = run_transcription(temp_path, selected_model)
        elapsed = time.monotonic() - start_time
        preview = (full_text or "")[:200]
        logger.info(
            "Completed transcription file=%s model=%s duration=%.2fs text_preview=%r",
            file.filename,
            selected_model,
            elapsed,
            preview,
        )
    except ModelNotAvailableError as exc:
        logger.exception("Whisper model not available locally: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=f"Model '{selected_model}' is not available locally. Download it before retrying.",
        )
    except Exception as exc:
        logger.exception("Whisper transcription failed: %s", exc)
        raise HTTPException(status_code=500, detail="Whisper transcription failed.")
    finally:
        try:
            temp_path.unlink()
        except OSError:
            logger.warning("Failed to remove temporary file %s", temp_path)

    response_payload = {
        "id": f"transcription-{uuid.uuid4().hex}",
        "object": "transcription",
        "created": int(time.time()),
        "model": selected_model,
        "text": full_text,
        "segments": segments,
    }
    return response_payload


@app.get("/healthz")
def health_check() -> Dict[str, str]:
    return {"status": "ok"}
