"""Transcription worker: provider dispatch and the Groq path (no network)."""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.db import Database
from app.transcribe import GROQ_TRANSCRIBE_URL, Transcriber


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


def _ticket_with_audio(db: Database, tmp_path) -> str:
    audio = tmp_path / "01.ogg"
    audio.write_bytes(b"fake-audio-bytes")
    db.insert_ticket(
        {
            "id": "01",
            "app": "duna",
            "created_at": "2026-08-02T00:00:00+00:00",
            "channel": "ios-shortcut",
            "status": "new",
            "transcript_status": "pending",
            "audio_path": str(audio),
        }
    )
    return "01"


def test_groq_provider_transcribes_and_marks_done(tmp_path, monkeypatch):
    db = Database(tmp_path / "t.db")
    ticket_id = _ticket_with_audio(db, tmp_path)
    settings = Settings(
        transcribe_provider="groq",
        groq_api_key="test-key",
        groq_whisper_prompt="ctx",
        groq_whisper_language="es",
    )
    tr = Transcriber(db, settings)

    captured: dict = {}

    def fake_post(url, headers=None, data=None, files=None, timeout=None):
        captured.update(url=url, headers=headers, data=data, files=files)
        return _FakeResponse(200, {"text": "  hola mundo  "})

    monkeypatch.setattr(httpx, "post", fake_post)
    tr._transcribe(ticket_id)

    row = db.get_ticket(ticket_id)
    assert row["transcript"] == "hola mundo"
    assert row["transcript_status"] == "done"
    # Sent to Groq with the key, model, and optional prompt/language.
    assert captured["url"] == GROQ_TRANSCRIBE_URL
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["data"]["model"] == "whisper-large-v3"
    assert captured["data"]["prompt"] == "ctx"
    assert captured["data"]["language"] == "es"
    assert captured["files"]["file"][0] == "01.ogg"


def test_groq_provider_without_key_raises(tmp_path):
    db = Database(tmp_path / "t.db")
    ticket_id = _ticket_with_audio(db, tmp_path)
    tr = Transcriber(db, Settings(transcribe_provider="groq", groq_api_key=""))
    with pytest.raises(RuntimeError, match="GROQ_API_KEY"):
        tr._transcribe(ticket_id)


def test_unknown_provider_raises(tmp_path):
    db = Database(tmp_path / "t.db")
    ticket_id = _ticket_with_audio(db, tmp_path)
    tr = Transcriber(db, Settings(transcribe_provider="bogus"))
    with pytest.raises(RuntimeError, match="Unknown TRANSCRIBE_PROVIDER"):
        tr._transcribe(ticket_id)
