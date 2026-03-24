"""Tests for Ward Room API endpoints (AD-407a)."""

import pytest
import pytest_asyncio

from probos.ward_room import WardRoomService


@pytest_asyncio.fixture
async def ward_room_svc(tmp_path):
    """Create a WardRoomService with temp SQLite DB."""
    svc = WardRoomService(db_path=str(tmp_path / "ward_room.db"))
    await svc.start()
    yield svc
    await svc.stop()


@pytest.fixture
def mock_runtime(ward_room_svc):
    """Create a mock runtime with ward_room."""
    from unittest.mock import MagicMock
    runtime = MagicMock()
    runtime.ward_room = ward_room_svc
    runtime.add_event_listener = MagicMock()
    return runtime


@pytest.fixture
def client(mock_runtime):
    """Create a test client for the API."""
    from probos.api import create_app
    from fastapi.testclient import TestClient
    app = create_app(mock_runtime)
    return TestClient(app)


def test_get_channels(client):
    """GET /api/wardroom/channels returns default channels."""
    resp = client.get("/api/wardroom/channels")
    assert resp.status_code == 200
    data = resp.json()
    names = [c["name"] for c in data["channels"]]
    assert "All Hands" in names
    assert "Engineering" in names


def test_create_channel(client):
    """POST /api/wardroom/channels creates custom channel."""
    resp = client.post("/api/wardroom/channels", json={
        "name": "Off Duty",
        "created_by": "agent-1",
        "description": "Casual chat",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Off Duty"
    assert data["channel_type"] == "custom"


def test_create_thread(client):
    """POST creates thread, GET retrieves it."""
    # Get a channel
    channels = client.get("/api/wardroom/channels").json()["channels"]
    ch_id = channels[0]["id"]

    resp = client.post(f"/api/wardroom/channels/{ch_id}/threads", json={
        "author_id": "agent-1",
        "title": "First Post",
        "body": "Hello Ward Room!",
        "author_callsign": "Wesley",
    })
    assert resp.status_code == 200
    thread = resp.json()
    assert thread["title"] == "First Post"

    # Retrieve it
    resp2 = client.get(f"/api/wardroom/threads/{thread['id']}")
    assert resp2.status_code == 200
    detail = resp2.json()
    assert detail["thread"]["title"] == "First Post"


def test_create_post(client):
    """POST creates reply to thread."""
    channels = client.get("/api/wardroom/channels").json()["channels"]
    ch_id = channels[0]["id"]
    thread = client.post(f"/api/wardroom/channels/{ch_id}/threads", json={
        "author_id": "a1", "title": "T", "body": "B",
    }).json()

    resp = client.post(f"/api/wardroom/threads/{thread['id']}/posts", json={
        "author_id": "a2",
        "body": "Great thread!",
    })
    assert resp.status_code == 200
    post = resp.json()
    assert post["body"] == "Great thread!"


def test_endorse_post(client):
    """POST endorses a post, verify net_score changes."""
    channels = client.get("/api/wardroom/channels").json()["channels"]
    ch_id = channels[0]["id"]
    thread = client.post(f"/api/wardroom/channels/{ch_id}/threads", json={
        "author_id": "a1", "title": "T", "body": "B",
    }).json()
    post = client.post(f"/api/wardroom/threads/{thread['id']}/posts", json={
        "author_id": "a2", "body": "Post",
    }).json()

    resp = client.post(f"/api/wardroom/posts/{post['id']}/endorse", json={
        "voter_id": "a1",
        "direction": "up",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["net_score"] == 1


def test_endorse_self_rejected(client):
    """Self-endorsement returns 400."""
    channels = client.get("/api/wardroom/channels").json()["channels"]
    ch_id = channels[0]["id"]
    thread = client.post(f"/api/wardroom/channels/{ch_id}/threads", json={
        "author_id": "a1", "title": "T", "body": "B",
    }).json()
    post = client.post(f"/api/wardroom/threads/{thread['id']}/posts", json={
        "author_id": "a1", "body": "My post",
    }).json()

    resp = client.post(f"/api/wardroom/posts/{post['id']}/endorse", json={
        "voter_id": "a1",
        "direction": "up",
    })
    assert resp.status_code == 400


def test_get_credibility(client):
    """GET returns credibility for agent."""
    resp = client.get("/api/wardroom/agent/new-agent/credibility")
    assert resp.status_code == 200
    data = resp.json()
    assert data["credibility_score"] == 0.5
    assert data["total_posts"] == 0


def test_thread_not_found(client):
    """GET nonexistent thread returns 404."""
    resp = client.get("/api/wardroom/threads/nonexistent-id")
    assert resp.status_code == 404
