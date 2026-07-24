import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

APPS_YML = """
apps:
  duna:
    name: "Duna"
    tokens:
      - token: "tok-capture"
        scopes: [capture]
      - token: "tok-dev"
        scopes: [capture, read, write]
  other:
    name: "Other"
    tokens:
      - token: "tok-other-dev"
        scopes: [capture, read, write]
"""


@pytest.fixture()
def client(tmp_path):
    apps_file = tmp_path / "apps.yml"
    apps_file.write_text(APPS_YML, encoding="utf-8")
    settings = Settings(
        data_dir=tmp_path / "data",
        apps_file=apps_file,
        whisper_enabled=False,
        max_audio_mb=1,
    )
    with TestClient(create_app(settings)) as client:
        yield client


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
