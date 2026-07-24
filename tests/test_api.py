from conftest import auth


def create(client, **data):
    data.setdefault("text", "offline mode doesn't save changes")
    data.setdefault("channel", "api")
    resp = client.post("/api/reports", data=data, headers=auth("tok-capture"))
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- auth and scopes ---


def test_no_token_401(client):
    assert client.get("/api/tickets").status_code == 401
    assert client.post("/api/reports", data={"text": "x"}).status_code == 401


def test_invalid_token_401(client):
    resp = client.get("/api/tickets", headers=auth("tok-fake"))
    assert resp.status_code == 401


def test_capture_token_cannot_read_403(client):
    resp = client.get("/api/tickets", headers=auth("tok-capture"))
    assert resp.status_code == 403


def test_other_app_token_cannot_see_tickets(client):
    ticket = create(client)
    listing = client.get("/api/tickets", headers=auth("tok-other-dev")).json()
    assert listing == []
    resp = client.get(f"/api/tickets/{ticket['id']}", headers=auth("tok-other-dev"))
    assert resp.status_code == 404


# --- create and list ---


def test_create_text_ticket(client):
    ticket = create(client, channel="telegram", context='{"device":"iPhone"}')
    assert ticket["app"] == "duna"
    assert ticket["status"] == "new"
    assert ticket["channel"] == "telegram"
    assert ticket["type"] is None and ticket["priority"] is None
    listing = client.get(
        "/api/tickets", params={"status": "new"}, headers=auth("tok-dev")
    ).json()
    assert [t["id"] for t in listing] == [ticket["id"]]


def test_empty_report_422(client):
    resp = client.post(
        "/api/reports", data={"channel": "api"}, headers=auth("tok-capture")
    )
    assert resp.status_code == 422


def test_invalid_channel_422(client):
    resp = client.post(
        "/api/reports",
        data={"text": "x", "channel": "carrier-pigeon"},
        headers=auth("tok-capture"),
    )
    assert resp.status_code == 422


def test_context_not_json_422(client):
    resp = client.post(
        "/api/reports",
        data={"text": "x", "channel": "api", "context": "this is not json"},
        headers=auth("tok-capture"),
    )
    assert resp.status_code == 422


# --- audio ---


def test_create_audio_ticket(client):
    resp = client.post(
        "/api/reports",
        data={"channel": "ios-shortcut"},
        files={"audio": ("note.m4a", b"fake-audio-bytes", "audio/mp4")},
        headers=auth("tok-capture"),
    )
    assert resp.status_code == 201, resp.text
    ticket = resp.json()
    # whisper disabled in tests → stays pending, audio is kept
    assert ticket["transcript_status"] == "pending"
    audio = client.get(f"/api/tickets/{ticket['id']}/audio", headers=auth("tok-dev"))
    assert audio.status_code == 200
    assert audio.content == b"fake-audio-bytes"


def test_unsupported_audio_format_415(client):
    resp = client.post(
        "/api/reports",
        data={"channel": "api"},
        files={"audio": ("virus.exe", b"MZ...", "application/octet-stream")},
        headers=auth("tok-capture"),
    )
    assert resp.status_code == 415


def test_audio_too_large_413(client):
    resp = client.post(
        "/api/reports",
        data={"channel": "api"},
        files={"audio": ("note.m4a", b"x" * (2 * 1024 * 1024), "audio/mp4")},
        headers=auth("tok-capture"),
    )
    assert resp.status_code == 413


# --- triage ---


def test_patch_triage(client):
    ticket = create(client)
    resp = client.patch(
        f"/api/tickets/{ticket['id']}",
        json={"status": "triaged", "type": "bug", "priority": 4, "notes": "urgent"},
        headers=auth("tok-dev"),
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["status"] == "triaged"
    assert updated["priority"] == 4
    # original text is untouched
    assert updated["text"] == ticket["text"]


def test_patch_requires_write_scope(client):
    ticket = create(client)
    resp = client.patch(
        f"/api/tickets/{ticket['id']}",
        json={"status": "done"},
        headers=auth("tok-capture"),
    )
    assert resp.status_code == 403


def test_patch_invalid_values_422(client):
    ticket = create(client)
    for body in ({"status": "made-up"}, {"priority": 9}, {"type": "nonsense"}):
        resp = client.patch(
            f"/api/tickets/{ticket['id']}", json=body, headers=auth("tok-dev")
        )
        assert resp.status_code == 422, body


# --- health ---


def test_health(client):
    create(client)
    data = client.get("/api/health").json()
    assert data["status"] == "ok"
    assert "duna" in data["apps"]
    assert data["tickets"]["new"] == 1
    assert data["transcribe"]["enabled"] is False
