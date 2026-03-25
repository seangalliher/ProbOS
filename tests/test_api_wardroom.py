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


# ---------------------------------------------------------------------------
# Thread management (AD-424)
# ---------------------------------------------------------------------------

def test_patch_thread_lock(client):
    """PATCH locks a thread."""
    channels = client.get("/api/wardroom/channels").json()["channels"]
    ch_id = channels[0]["id"]
    thread = client.post(f"/api/wardroom/channels/{ch_id}/threads", json={
        "author_id": "a1", "title": "T", "body": "B",
    }).json()

    resp = client.patch(f"/api/wardroom/threads/{thread['id']}", json={
        "locked": True,
    })
    assert resp.status_code == 200
    assert resp.json()["locked"] is True


def test_patch_thread_reclassify(client):
    """PATCH reclassifies inform → discuss."""
    channels = client.get("/api/wardroom/channels").json()["channels"]
    ch_id = channels[0]["id"]
    thread = client.post(f"/api/wardroom/channels/{ch_id}/threads", json={
        "author_id": "a1", "title": "Advisory", "body": "Status",
        "thread_mode": "inform",
    }).json()
    assert thread["thread_mode"] == "inform"

    resp = client.patch(f"/api/wardroom/threads/{thread['id']}", json={
        "thread_mode": "discuss",
    })
    assert resp.status_code == 200
    assert resp.json()["thread_mode"] == "discuss"

    # GET also shows updated mode
    detail = client.get(f"/api/wardroom/threads/{thread['id']}").json()
    assert detail["thread"]["thread_mode"] == "discuss"


def test_patch_thread_not_found(client):
    """PATCH nonexistent thread returns 404."""
    resp = client.patch("/api/wardroom/threads/nonexistent-id", json={
        "locked": True,
    })
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Activity feed & mark-seen (AD-425)
# ---------------------------------------------------------------------------

def test_activity_feed_returns_threads(client):
    """GET /api/wardroom/activity returns threads from multiple channels."""
    channels = client.get("/api/wardroom/channels").json()["channels"]
    ch1_id = channels[0]["id"]
    ch2_id = channels[1]["id"] if len(channels) > 1 else ch1_id
    client.post(f"/api/wardroom/channels/{ch1_id}/threads", json={
        "author_id": "a1", "title": "T1", "body": "B1",
    })
    client.post(f"/api/wardroom/channels/{ch2_id}/threads", json={
        "author_id": "a1", "title": "T2", "body": "B2",
    })
    resp = client.get("/api/wardroom/activity")
    assert resp.status_code == 200
    threads = resp.json()["threads"]
    assert len(threads) >= 2


def test_activity_feed_mode_filter(client):
    """?thread_mode=discuss filters correctly."""
    channels = client.get("/api/wardroom/channels").json()["channels"]
    ch_id = channels[0]["id"]
    client.post(f"/api/wardroom/channels/{ch_id}/threads", json={
        "author_id": "a1", "title": "Info", "body": "B",
        "thread_mode": "inform",
    })
    client.post(f"/api/wardroom/channels/{ch_id}/threads", json={
        "author_id": "a1", "title": "Talk", "body": "B",
        "thread_mode": "discuss",
    })
    resp = client.get("/api/wardroom/activity", params={
        "channel_id": ch_id, "thread_mode": "discuss",
    })
    threads = resp.json()["threads"]
    assert all(t["thread_mode"] == "discuss" for t in threads)
    assert any(t["title"] == "Talk" for t in threads)


def test_activity_feed_agent_scoped(client):
    """?agent_id=a1 returns only threads from subscribed channels."""
    channels = client.get("/api/wardroom/channels").json()["channels"]
    ch_id = channels[0]["id"]
    # Subscribe agent
    client.post(f"/api/wardroom/channels/{ch_id}/subscribe", json={
        "agent_id": "a1",
    })
    client.post(f"/api/wardroom/channels/{ch_id}/threads", json={
        "author_id": "a1", "title": "Subscribed", "body": "B",
    })
    resp = client.get("/api/wardroom/activity", params={"agent_id": "a1"})
    threads = resp.json()["threads"]
    assert any(t["title"] == "Subscribed" for t in threads)


def test_mark_channel_seen(client):
    """PUT /api/wardroom/channels/{id}/seen returns 200."""
    channels = client.get("/api/wardroom/channels").json()["channels"]
    ch_id = channels[0]["id"]
    resp = client.put(f"/api/wardroom/channels/{ch_id}/seen", params={
        "agent_id": "a1",
    })
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
