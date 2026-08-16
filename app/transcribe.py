"""Async transcription worker.

In-memory queue, one job at a time (the VM is small, no rush). DB states:
pending → done | failed (3 attempts). A failure never blocks anything: the
ticket exists and the audio is on disk; on restart, `pending` ones get
re-enqueued. With WHISPER_ENABLED=false the worker doesn't start and
audios stay `pending` until it's enabled.

Two engines, selected by TRANSCRIBE_PROVIDER:
  - "groq"  (default): a multipart call to Groq's Whisper API. No ML on the
     VM, tiny RAM — same approach as Duna's backend/bot.
  - "local": faster-whisper in-process (needs requirements-transcribe.txt).
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from pathlib import Path

from .config import Settings
from .db import Database

log = logging.getLogger("triagebox.transcribe")

MAX_ATTEMPTS = 3

GROQ_TRANSCRIBE_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

# Content-type per stored extension, so Groq can decode the file.
_MIME_BY_EXT = {
    "m4a": "audio/mp4",
    "mp3": "audio/mpeg",
    "ogg": "audio/ogg",
    "wav": "audio/wav",
    "webm": "audio/webm",
}


class Transcriber:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings
        self.queue: queue.Queue[str] = queue.Queue()
        self._model = None
        self._thread: threading.Thread | None = None

    @property
    def enabled(self) -> bool:
        return self.settings.whisper_enabled

    @property
    def provider(self) -> str:
        return self.settings.transcribe_provider

    def start(self) -> None:
        if not self.enabled or self._thread:
            return
        for ticket_id in self.db.pending_transcriptions():
            self.queue.put(ticket_id)
        self._thread = threading.Thread(target=self._loop, daemon=True, name="whisper")
        self._thread.start()

    def enqueue(self, ticket_id: str) -> None:
        if self.enabled:
            self.queue.put(ticket_id)

    def pending(self) -> int:
        return self.queue.qsize()

    # --- internal ---

    def _get_model(self):
        if self._model is None:
            from faster_whisper import WhisperModel  # lazy import: heavy dep

            log.info("Loading whisper model '%s' (int8)", self.settings.whisper_model)
            self._model = WhisperModel(
                self.settings.whisper_model, device="cpu", compute_type="int8"
            )
        return self._model

    def _loop(self) -> None:
        while True:
            ticket_id = self.queue.get()
            for attempt in range(1, MAX_ATTEMPTS + 1):
                try:
                    self._transcribe(ticket_id)
                    break
                except Exception:
                    log.exception(
                        "Failed transcribing %s (attempt %d/%d)",
                        ticket_id,
                        attempt,
                        MAX_ATTEMPTS,
                    )
                    if attempt == MAX_ATTEMPTS:
                        self.db.update_ticket(ticket_id, {"transcript_status": "failed"})
                    else:
                        time.sleep(5 * attempt)

    def _transcribe(self, ticket_id: str) -> None:
        ticket = self.db.get_ticket(ticket_id)
        if not ticket or not ticket.get("audio_path"):
            return
        if ticket.get("transcript_status") == "done":
            return
        provider = self.settings.transcribe_provider
        if provider == "groq":
            text = self._transcribe_groq(ticket["audio_path"])
        elif provider == "local":
            text = self._transcribe_local(ticket["audio_path"])
        else:
            raise RuntimeError(
                f"Unknown TRANSCRIBE_PROVIDER '{provider}' (use 'groq' or 'local')"
            )
        self.db.update_ticket(
            ticket_id, {"transcript": text or None, "transcript_status": "done"}
        )
        log.info("Transcribed %s via %s (%d characters)", ticket_id, provider, len(text))

    def _transcribe_groq(self, audio_path: str) -> str:
        import httpx  # light dep; only the groq path needs it

        api_key = self.settings.groq_api_key
        if not api_key:
            raise RuntimeError("TRANSCRIBE_PROVIDER=groq but GROQ_API_KEY is not set")
        path = Path(audio_path)
        ext = path.suffix.lower().lstrip(".")
        mime = _MIME_BY_EXT.get(ext, "application/octet-stream")
        data = {"model": self.settings.groq_whisper_model}
        # `prompt` gives bilingual (ca/es) context; `language` pins it if set.
        if self.settings.groq_whisper_prompt:
            data["prompt"] = self.settings.groq_whisper_prompt
        if self.settings.groq_whisper_language:
            data["language"] = self.settings.groq_whisper_language
        with path.open("rb") as fh:
            resp = httpx.post(
                GROQ_TRANSCRIBE_URL,
                headers={"Authorization": f"Bearer {api_key}"},
                data=data,
                files={"file": (path.name, fh, mime)},
                timeout=120.0,
            )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Groq transcription returned {resp.status_code}: {resp.text[:300]}"
            )
        return (resp.json().get("text") or "").strip()

    def _transcribe_local(self, audio_path: str) -> str:
        segments, _info = self._get_model().transcribe(audio_path, vad_filter=True)
        return " ".join(s.text.strip() for s in segments).strip()
