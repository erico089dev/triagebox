"""SQLite: source of truth for tickets. Audio files go to disk (data/audio)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
  id          TEXT PRIMARY KEY,
  app         TEXT NOT NULL,
  created_at  TEXT NOT NULL,
  channel     TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'new',
  type        TEXT,
  priority    INTEGER,
  user_id     TEXT,
  text        TEXT,
  transcript  TEXT,
  transcript_status TEXT,
  audio_path  TEXT,
  context     TEXT,
  notes       TEXT
);
CREATE INDEX IF NOT EXISTS idx_tickets_app_status ON tickets(app, status);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def insert_ticket(self, ticket: dict) -> None:
        cols = ", ".join(ticket)
        marks = ", ".join("?" for _ in ticket)
        with self._conn() as conn:
            conn.execute(
                f"INSERT INTO tickets ({cols}) VALUES ({marks})", list(ticket.values())
            )

    def get_ticket(self, ticket_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM tickets WHERE id = ?", (ticket_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_tickets(
        self,
        app: str,
        status: str | None = None,
        since: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        query = "SELECT * FROM tickets WHERE app = ?"
        params: list = [app]
        if status:
            query += " AND status = ?"
            params.append(status)
        if since:
            query += " AND created_at >= ?"
            params.append(since)
        query += " ORDER BY id LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def update_ticket(self, ticket_id: str, fields: dict) -> dict | None:
        if fields:
            assign = ", ".join(f"{col} = ?" for col in fields)
            with self._conn() as conn:
                conn.execute(
                    f"UPDATE tickets SET {assign} WHERE id = ?",
                    [*fields.values(), ticket_id],
                )
        return self.get_ticket(ticket_id)

    def pending_transcriptions(self) -> list[str]:
        """Ids with audio still waiting to be transcribed (to re-enqueue on startup)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT id FROM tickets WHERE transcript_status = 'pending' ORDER BY id"
            ).fetchall()
        return [r["id"] for r in rows]

    def count_by_status(self) -> dict[str, int]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS n FROM tickets GROUP BY status"
            ).fetchall()
        return {r["status"]: r["n"] for r in rows}
