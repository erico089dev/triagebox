"""Authentication: bearer tokens defined in apps.yml, with per-token scopes.

The token determines the app: a token only sees/creates tickets for its own app.
"""

from __future__ import annotations

from fastapi import Header, HTTPException, Request

from .config import TokenInfo


def require_scope(scope: str):
    """FastAPI dependency: requires a valid bearer token with the given scope."""

    def dependency(
        request: Request, authorization: str | None = Header(default=None)
    ) -> TokenInfo:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(401, "Missing token (Authorization: Bearer ...)")
        token = authorization.removeprefix("Bearer ").strip()
        info = request.app.state.registry.resolve(token)
        if info is None:
            raise HTTPException(401, "Invalid token")
        if scope not in info.scopes:
            raise HTTPException(403, f"The token doesn't have the '{scope}' scope")
        return info

    return dependency
