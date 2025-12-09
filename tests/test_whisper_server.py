from __future__ import annotations

from pathlib import Path
import logging
import sys

from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import whisper_server
from whisper_server import app

TEST_AUDIO = ROOT_DIR / "test-speech.mp3"


def test_transcription_endpoint_accepts_local_audio(monkeypatch, caplog):
    if not TEST_AUDIO.exists():
        raise AssertionError(f"Missing bundled audio fixture: {TEST_AUDIO}")

    caplog.set_level(logging.INFO, logger="local-whisper")
    fake_segments = [
        {
            "id": 0,
            "seek": 0,
            "start": 0.0,
            "end": 1.0,
            "text": "stub",
            "tokens": [0],
            "temperature": 0.0,
            "avg_logprob": 0.0,
            "compression_ratio": 0.0,
            "no_speech_prob": 0.0,
        }
    ]

    def fake_run_transcription(audio_path: Path, model_name: str):
        assert Path(audio_path).exists()
        assert model_name == "base"
        return "stub transcript", fake_segments

    monkeypatch.setattr("whisper_server.run_transcription", fake_run_transcription)

    client = TestClient(app)
    with TEST_AUDIO.open("rb") as audio_bytes:
        response = client.post(
            "/v1/audio/transcriptions",
            files={"file": (TEST_AUDIO.name, audio_bytes, "audio/mpeg")},
            data={"model": "base"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["model"] == "base"
    assert payload["text"] == "stub transcript"
    assert payload["segments"] == fake_segments
    assert any("stub transcript" in record.getMessage() for record in caplog.records)


def test_get_model_falls_back_when_float16_not_supported(monkeypatch):
    whisper_server._MODEL_CACHE.clear()
    attempts: list[str] = []

    class FakeModel:
        def __init__(self, name: str, device: str, compute_type: str):
            attempts.append(compute_type)
            if compute_type == "float16":
                raise ValueError("float16 unsupported")
            self.name = name
            self.device = device
            self.compute_type = compute_type

    monkeypatch.setattr(whisper_server, "WhisperModel", FakeModel)
    monkeypatch.setattr(whisper_server, "WHISPER_COMPUTE_TYPE", "float16", raising=False)

    model = whisper_server.get_model("base")

    assert attempts[:2] == ["float16", "int8_float32"]
    assert model.compute_type == "int8_float32"
    whisper_server._MODEL_CACHE.clear()


def test_normalize_model_name_uses_alias(monkeypatch):
    monkeypatch.setattr(whisper_server, "DEFAULT_MODEL_NAME", "large-v3-turbo", raising=False)
    normalized = whisper_server.normalize_model_name("large-v3-turbo")
    assert normalized == "large-v3"

    normalized_default = whisper_server.normalize_model_name(None)
    assert normalized_default == "large-v3"


def test_transcription_returns_503_when_model_missing(monkeypatch):
    if not TEST_AUDIO.exists():
        raise AssertionError(f"Missing bundled audio fixture: {TEST_AUDIO}")

    def fake_run_transcription(audio_path: Path, model_name: str):
        raise whisper_server.ModelNotAvailableError("model missing")

    monkeypatch.setattr("whisper_server.run_transcription", fake_run_transcription)

    client = TestClient(app)
    with TEST_AUDIO.open("rb") as audio_bytes:
        response = client.post(
            "/v1/audio/transcriptions",
            files={"file": (TEST_AUDIO.name, audio_bytes, "audio/mpeg")},
            data={"model": "base"},
        )

    assert response.status_code == 503
    assert "not available locally" in response.json()["detail"]
