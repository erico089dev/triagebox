"""Configuration: .env (service settings) + apps.yml (project registry).

apps.yml hot-reloads by checking its mtime on every token lookup, so
registering a new project doesn't require a restart.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

CHANNELS = {"ios-shortcut", "telegram", "pwa", "api"}
STATUSES = {"new", "triaged", "done", "discarded"}
TYPES = {"bug", "improvement", "idea"}
SCOPES = {"capture", "read", "write"}


@dataclass(frozen=True)
class Settings:
    port: int = 8080
    data_dir: Path = Path("./data")
    apps_file: Path = Path("./apps.yml")
    whisper_enabled: bool = False
    whisper_model: str = "base"
    max_audio_mb: int = 20

    @staticmethod
    def from_env() -> "Settings":
        return Settings(
            port=int(os.getenv("PORT", "8080")),
            data_dir=Path(os.getenv("DATA_DIR", "./data")),
            apps_file=Path(os.getenv("APPS_FILE", "./apps.yml")),
            whisper_enabled=os.getenv("WHISPER_ENABLED", "false").lower() == "true",
            whisper_model=os.getenv("WHISPER_MODEL", "base"),
            max_audio_mb=int(os.getenv("MAX_AUDIO_MB", "20")),
        )


@dataclass(frozen=True)
class TokenInfo:
    app: str
    scopes: frozenset[str]


@dataclass
class AppsRegistry:
    """Loads apps.yml and resolves token → (app, scopes), reloading by mtime."""

    path: Path
    _mtime: float = -1.0
    _tokens: dict[str, TokenInfo] = field(default_factory=dict)
    _apps: dict[str, dict] = field(default_factory=dict)

    def _load(self) -> None:
        raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        apps = raw.get("apps") or {}
        tokens: dict[str, TokenInfo] = {}
        for app_key, app_cfg in apps.items():
            for entry in (app_cfg or {}).get("tokens") or []:
                token = str(entry.get("token", "")).strip()
                scopes = frozenset(entry.get("scopes") or [])
                if not token:
                    continue
                if not scopes <= SCOPES:
                    raise ValueError(
                        f"apps.yml: unknown scopes {scopes - SCOPES} in app '{app_key}'"
                    )
                if token in tokens:
                    raise ValueError(f"apps.yml: duplicate token in app '{app_key}'")
                tokens[token] = TokenInfo(app=app_key, scopes=scopes)
        self._tokens = tokens
        self._apps = apps

    def _refresh(self) -> None:
        try:
            mtime = self.path.stat().st_mtime
        except FileNotFoundError:
            self._tokens, self._apps, self._mtime = {}, {}, -1.0
            return
        if mtime != self._mtime:
            self._load()
            self._mtime = mtime

    def resolve(self, token: str) -> TokenInfo | None:
        self._refresh()
        return self._tokens.get(token)

    def app_names(self) -> list[str]:
        self._refresh()
        return sorted(self._apps)
