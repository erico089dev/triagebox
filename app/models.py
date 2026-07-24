"""API contract (Pydantic). Same schema as the tickets table."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Status = Literal["new", "triaged", "done", "discarded"]
TicketType = Literal["bug", "improvement", "idea"]


class Ticket(BaseModel):
    id: str
    app: str
    created_at: str
    channel: str
    status: Status
    type: TicketType | None = None
    priority: int | None = Field(default=None, ge=1, le=4)  # 4 = high, same as Duna
    user_id: str | None = None
    text: str | None = None
    transcript: str | None = None
    transcript_status: Literal["pending", "done", "failed"] | None = None
    audio_path: str | None = None
    context: str | None = None  # free-form serialized JSON
    notes: str | None = None


class TicketPatch(BaseModel):
    """Triage fields. All optional; only what's sent gets updated."""

    status: Status | None = None
    type: TicketType | None = None
    priority: int | None = Field(default=None, ge=1, le=4)
    notes: str | None = None
