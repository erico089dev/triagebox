"""Triagebox API. Listens on loopback only; exposed via Tailscale Serve."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from .auth import require_scope
from .config import CHANNELS, AppsRegistry, Settings, TokenInfo
from .db import Database
from .models import Ticket, TicketPatch
from .transcribe import Transcriber
from .util import ulid

logging.basicConfig(level=logging.INFO)

# Supported audio extensions and their content-types (whitelist)
EXT_BY_MIME = {
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/m4a": "m4a",
    "audio/aac": "m4a",
    "audio/mpeg": "mp3",
    "audio/ogg": "ogg",
    "application/ogg": "ogg",
    "audio/opus": "ogg",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
}
MIME_BY_EXT = {
    "m4a": "audio/mp4",
    "mp3": "audio/mpeg",
    "ogg": "audio/ogg",
    "wav": "audio/wav",
}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.transcriber.start()
        yield

    app = FastAPI(title="Triagebox", lifespan=lifespan)
    app.state.settings = settings
    app.state.registry = AppsRegistry(path=settings.apps_file)
    app.state.db = Database(settings.data_dir / "triagebox.db")
    app.state.audio_dir = settings.data_dir / "audio"
    app.state.audio_dir.mkdir(parents=True, exist_ok=True)
    app.state.transcriber = Transcriber(app.state.db, settings)

    def _audio_ext(audio: UploadFile) -> str:
        ext = EXT_BY_MIME.get((audio.content_type or "").split(";")[0].strip())
        if not ext and audio.filename:
            suffix = Path(audio.filename).suffix.lower().lstrip(".")
            if suffix == "opus":
                suffix = "ogg"
            if suffix in MIME_BY_EXT:
                ext = suffix
        if not ext:
            raise HTTPException(
                415,
                f"Unsupported audio format ({audio.content_type or 'unknown'}); "
                f"use {sorted(MIME_BY_EXT)}",
            )
        return ext

    async def _save_audio(audio: UploadFile, dest: Path) -> None:
        max_bytes = settings.max_audio_mb * 1024 * 1024
        written = 0
        try:
            with dest.open("wb") as fh:
                while chunk := await audio.read(64 * 1024):
                    written += len(chunk)
                    if written > max_bytes:
                        raise HTTPException(
                            413, f"Audio too large (limit {settings.max_audio_mb} MB)"
                        )
                    fh.write(chunk)
        except HTTPException:
            dest.unlink(missing_ok=True)
            raise

    @app.post("/api/reports", status_code=201, response_model=Ticket)
    async def create_report(
        request: Request,
        text: str | None = Form(default=None),
        channel: str = Form(default="api"),
        context: str | None = Form(default=None),
        audio: UploadFile | None = File(default=None),
        token: TokenInfo = Depends(require_scope("capture")),
    ):
        if channel not in CHANNELS:
            raise HTTPException(422, f"channel must be one of {sorted(CHANNELS)}")
        text = (text or "").strip() or None
        if not text and audio is None:
            raise HTTPException(422, "The report needs 'text' and/or 'audio'")
        if context is not None:
            try:
                json.loads(context)
            except ValueError:
                raise HTTPException(422, "'context' must be valid JSON")

        ticket_id = ulid()
        audio_path: Path | None = None
        if audio is not None:
            audio_path = request.app.state.audio_dir / f"{ticket_id}.{_audio_ext(audio)}"
            await _save_audio(audio, audio_path)

        ticket = {
            "id": ticket_id,
            "app": token.app,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "channel": channel,
            "status": "new",
            "text": text,
            "transcript_status": "pending" if audio_path else None,
            "audio_path": str(audio_path) if audio_path else None,
            "context": context,
        }
        request.app.state.db.insert_ticket(ticket)
        if audio_path:
            request.app.state.transcriber.enqueue(ticket_id)
        return request.app.state.db.get_ticket(ticket_id)

    @app.get("/api/tickets", response_model=list[Ticket])
    def list_tickets(
        request: Request,
        status: str | None = Query(default=None),
        since: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=1000),
        app_param: str | None = Query(default=None, alias="app"),
        token: TokenInfo = Depends(require_scope("read")),
    ):
        if app_param and app_param != token.app:
            raise HTTPException(403, "The token doesn't belong to that app")
        return request.app.state.db.list_tickets(
            token.app, status=status, since=since, limit=limit
        )

    def _owned_ticket(request: Request, ticket_id: str, token: TokenInfo) -> dict:
        ticket = request.app.state.db.get_ticket(ticket_id)
        if not ticket or ticket["app"] != token.app:
            raise HTTPException(404, "Ticket not found")
        return ticket

    @app.get("/api/tickets/{ticket_id}", response_model=Ticket)
    def get_ticket(
        request: Request,
        ticket_id: str,
        token: TokenInfo = Depends(require_scope("read")),
    ):
        return _owned_ticket(request, ticket_id, token)

    @app.get("/api/tickets/{ticket_id}/audio")
    def get_audio(
        request: Request,
        ticket_id: str,
        token: TokenInfo = Depends(require_scope("read")),
    ):
        ticket = _owned_ticket(request, ticket_id, token)
        if not ticket.get("audio_path") or not Path(ticket["audio_path"]).is_file():
            raise HTTPException(404, "This ticket has no audio")
        ext = Path(ticket["audio_path"]).suffix.lstrip(".")
        return FileResponse(
            ticket["audio_path"],
            media_type=MIME_BY_EXT.get(ext, "application/octet-stream"),
            filename=f"{ticket_id}.{ext}",
        )

    @app.patch("/api/tickets/{ticket_id}", response_model=Ticket)
    def patch_ticket(
        request: Request,
        ticket_id: str,
        patch: TicketPatch,
        token: TokenInfo = Depends(require_scope("write")),
    ):
        _owned_ticket(request, ticket_id, token)
        fields = patch.model_dump(exclude_unset=True)
        return request.app.state.db.update_ticket(ticket_id, fields)

    @app.get("/api/health")
    def health(request: Request):
        return {
            "status": "ok",
            "apps": request.app.state.registry.app_names(),
            "tickets": request.app.state.db.count_by_status(),
            "transcribe": {
                "enabled": request.app.state.transcriber.enabled,
                "provider": request.app.state.transcriber.provider,
                "queue": request.app.state.transcriber.pending(),
            },
        }

    return app
