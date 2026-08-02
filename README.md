# Triagebox — self-hosted ticket/report inbox service

Small, reusable service whose sole purpose is to **receive reports**
(bugs, improvements, ideas) from any app or device — text or audio — and
turn them into **tickets** with status that an AI agent (Claude Code)
later consumes from the dev environment ("check the new tickets").

> The full architecture plan currently lives in the Duna repo:
> `Duna/docs/inbox/00-plan-inbox.md`. Once this project has its own repo,
> that document moves here.

## Design in one line

SQLite + disk as the source of truth, REST API with per-app and per-scope
tokens, async transcription with local Whisper, exposed only within the
tailnet (Tailscale Serve). No Git in the write path, no SaaS.

## Structure

```
app/
├── main.py        # FastAPI, routes (/api/reports, /api/tickets, /api/health)
├── auth.py        # bearer tokens per app and scope (capture | read | write)
├── config.py      # .env + apps.yml (project registry, hot reload)
├── db.py          # SQLite (schema, queries)
├── models.py      # Pydantic: API contract
├── transcribe.py  # async faster-whisper worker
└── util.py        # ULID
apps.yml           # app registry and tokens (gitignored; see apps.yml.example)
infra/             # deploy.sh, backup.sh, systemd unit
skill-template/    # /tickets skill to copy into each consuming project
tests/
```

## Local setup (development)

```bash
python -m venv .venv
.venv/Scripts/activate            # Windows  (Linux: source .venv/bin/activate)
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
cp apps.yml.example apps.yml       # and change the tokens (openssl rand -hex 24)
python -m uvicorn app.main:create_app --factory --port 8080
```

Tests: `python -m pytest`

## Production (VM)

```bash
pip install -r requirements.txt          # groq provider: no heavy ML deps
sudo cp infra/triagebox.service /etc/systemd/system/ && sudo systemctl enable --now triagebox
bash infra/deploy.sh               # on each update
sudo tailscale serve --bg --https=443 http://127.0.0.1:8080
```

### Transcription

Two engines, selected by `TRANSCRIBE_PROVIDER`:

- **`groq`** (default) — a small multipart call to Groq's Whisper API. No ML
  on the VM, tiny RAM; ideal when co-hosting with another service. Set
  `GROQ_API_KEY` (same account/key as Duna's backend works). Needs only
  `requirements.txt`.
- **`local`** — faster-whisper in-process. Needs `pip install -r
  requirements-transcribe.txt` and enough RAM (`base` int8 + swap on a 1 GB
  VM). Set `WHISPER_MODEL`.

With `WHISPER_ENABLED=false` the worker doesn't start: audios stay
`transcript_status=pending` and get processed once it's enabled (nothing is
lost). If exposing over a tailnet that already uses `:443` for another
service, give Triagebox its own HTTPS port instead
(`sudo tailscale serve --bg --https=8443 http://127.0.0.1:8080`).

## Registering a new project

Add a block to `apps.yml` (see `apps.yml.example`) with a name and tokens
generated via `openssl rand -hex 24`. The file hot-reloads — no restart
needed. Copy `skill-template/SKILL.md` into the project's repo so its
Claude Code knows how to consume the tickets.

## API (summary)

| Method & route | Scope | Description |
|---|---|---|
| `POST /api/reports` | `capture` | Multipart: `text` and/or `audio`, `channel`, optional `context` |
| `GET /api/tickets?status=&since=&limit=` | `read` | Tickets for the token's app |
| `GET /api/tickets/{id}` | `read` | Detail |
| `GET /api/tickets/{id}/audio` | `read` | Original audio |
| `PATCH /api/tickets/{id}` | `write` | `status`, `type`, `priority`, `notes` |
| `GET /api/health` | — | Status + transcription queue |

Statuses: `new → triaged → done | discarded`. Priority `1..4` (4 = high).
`type` and `priority` start out `NULL`: capture doesn't classify; triage is
done by the AI back home.
