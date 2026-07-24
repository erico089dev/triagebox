"""Async transcription worker (faster-whisper).

In-memory queue, one job at a time (the VM is small, no rush). DB states:
pending → done | failed (3 attempts). A failure never blocks anything: the
ticket exists and the audio is on disk; on restart, `pending` ones get
re-enqueued. With WHISPER_ENABLED=false the worker doesn't start and
audios stay `pending` until it's enabled.
"""

from __future__ import annotations

import logging
import queue
import threading
import time

from .config import Settings
from .db import Database

log = logging.getLogger("triagebox.transcribe")

MAX_ATTEMPTS = 3


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
        segments, _info = self._get_model().transcribe(
            ticket["audio_path"], vad_filter=True
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        self.db.update_ticket(
            ticket_id, {"transcript": text or None, "transcript_status": "done"}
        )
        log.info("Transcribed %s (%d characters)", ticket_id, len(text))
