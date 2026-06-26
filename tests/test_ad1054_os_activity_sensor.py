"""AD-1054: OS-activity sensor (desktop foreground-window watcher -> os.activity).

OSS plumbing. A default-OFF, consent-gated, local-only desktop watcher POSTs
active-window METADATA ONLY to ``POST /api/os-activity``, which (when consent is
on) emits a new ``OS_ACTIVITY`` runtime event. Pure sensor -- no intelligence,
no suggestions, nothing in OSS consumes the event. Additive + default OFF ->
byte-identical behavior when the consent flag is off.

Privacy guarantees asserted here:
  - ``OSActivityConfig.enabled`` defaults False (no capture without consent).
  - ``POST /api/os-activity`` OFF -> no-op, NO event emitted (the emit sink
    captures nothing).
  - Active-window metadata only (app/title/path/url) -- no keystroke/screen/
    clipboard fields exist on the event or the ingest model.

BF-287: real fixtures only. Real ``SystemConfig`` (flip the consent flag), the
real ``OSActivityEvent`` (real ``BaseEvent.to_dict``), and a thin recorder for
``emit_event`` (the only sink that is a stand-in). No ``MagicMock`` at the
substrate boundary.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from probos.config import OSActivityConfig, SystemConfig
from probos.events import EventType, OSActivityEvent
from probos.routers.deps import get_runtime
from probos.routers.system import router


def _client_for(runtime: Any) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


def _runtime(config: SystemConfig, captured: list[Any]) -> SimpleNamespace:
    """A thin runtime stand-in: real config + a recording emit sink."""
    return SimpleNamespace(config=config, emit_event=captured.append)


# --- 1. config default ------------------------------------------------------

def test_os_activity_config_defaults_off() -> None:
    cfg = OSActivityConfig()

    assert cfg.enabled is False
    assert cfg.poll_interval_seconds == 5


# --- 2. mounted on SystemConfig, default OFF -------------------------------

def test_system_config_mounts_os_activity_default_off() -> None:
    sys_cfg = SystemConfig()

    assert isinstance(sys_cfg.os_activity, OSActivityConfig)
    assert sys_cfg.os_activity.enabled is False
    assert sys_cfg.os_activity.poll_interval_seconds == 5


# --- 3. poll_interval bounds (ge=1, le=60) ---------------------------------

def test_poll_interval_seconds_rejects_out_of_bounds() -> None:
    with pytest.raises(ValidationError):
        OSActivityConfig(poll_interval_seconds=0)
    with pytest.raises(ValidationError):
        OSActivityConfig(poll_interval_seconds=61)
    # In-bounds endpoints are accepted.
    assert OSActivityConfig(poll_interval_seconds=1).poll_interval_seconds == 1
    assert OSActivityConfig(poll_interval_seconds=60).poll_interval_seconds == 60


# --- 4. EventType value -----------------------------------------------------

def test_os_activity_event_type_value() -> None:
    assert EventType.OS_ACTIVITY.value == "os_activity"


# --- 5. OSActivityEvent serializes per the BaseEvent contract --------------

def test_os_activity_event_to_dict() -> None:
    ev = OSActivityEvent(
        active_app="Code.exe",
        window_title="events.py - ProbOS",
        app_path="C:\\code\\Code.exe",
        url="",
        ts=123.5,
    )

    d = ev.to_dict()

    assert d["type"] == "os_activity"
    assert d["data"] == {
        "active_app": "Code.exe",
        "window_title": "events.py - ProbOS",
        "app_path": "C:\\code\\Code.exe",
        "url": "",
        "ts": 123.5,
    }
    assert isinstance(d["timestamp"], float)
    # Metadata only -- no keystroke/screen/clipboard fields leak into the event.
    for forbidden in ("keystrokes", "screen", "clipboard", "content"):
        assert forbidden not in d["data"]


# --- 6. GET /api/os-activity OFF (default) ---------------------------------

def test_get_os_activity_consent_off_by_default() -> None:
    client = _client_for(_runtime(SystemConfig(), []))

    r = client.get("/api/os-activity")

    assert r.status_code == 200
    assert r.json() == {"enabled": False, "poll_interval_seconds": 5}


# --- 7. GET /api/os-activity ON reflects the flag --------------------------

def test_get_os_activity_consent_on_reflects_config() -> None:
    cfg = SystemConfig()
    cfg.os_activity.enabled = True
    cfg.os_activity.poll_interval_seconds = 10
    client = _client_for(_runtime(cfg, []))

    r = client.get("/api/os-activity")

    assert r.status_code == 200
    assert r.json() == {"enabled": True, "poll_interval_seconds": 10}


# --- 8. POST OFF -> no-op, NO event (byte-identical) -----------------------

def test_post_os_activity_off_is_noop_no_event() -> None:
    captured: list[Any] = []
    client = _client_for(_runtime(SystemConfig(), captured))

    r = client.post("/api/os-activity", json={"active_app": "Code.exe"})

    assert r.status_code == 200
    assert r.json() == {"ingested": False, "reason": "disabled"}
    # The whole point: consent off -> the sensor signal is dropped, nothing emitted.
    assert captured == []


# --- 9. POST ON -> emits exactly one OSActivityEvent with mapped fields -----

def test_post_os_activity_on_emits_event() -> None:
    cfg = SystemConfig()
    cfg.os_activity.enabled = True
    captured: list[Any] = []
    client = _client_for(_runtime(cfg, captured))

    r = client.post(
        "/api/os-activity",
        json={
            "active_app": "chrome.exe",
            "window_title": "ProbOS - GitHub",
            "app_path": "/usr/bin/chrome",
            "url": "https://github.com/probos",
            "ts": 42.0,
        },
    )

    assert r.status_code == 200
    assert r.json() == {"ingested": True}
    assert len(captured) == 1
    ev = captured[0]
    assert isinstance(ev, OSActivityEvent)
    assert ev.active_app == "chrome.exe"
    assert ev.window_title == "ProbOS - GitHub"
    assert ev.app_path == "/usr/bin/chrome"
    assert ev.url == "https://github.com/probos"
    assert ev.ts == 42.0


# --- 10. POST ON, ts omitted -> server fallback ts > 0 ---------------------

def test_post_os_activity_on_ts_omitted_uses_server_fallback() -> None:
    cfg = SystemConfig()
    cfg.os_activity.enabled = True
    captured: list[Any] = []
    client = _client_for(_runtime(cfg, captured))

    r = client.post("/api/os-activity", json={"active_app": "Terminal"})

    assert r.status_code == 200
    assert r.json() == {"ingested": True}
    assert len(captured) == 1
    # Server stamps a fallback capture time when the client omits ts.
    assert captured[0].ts > 0


# --- 11. POST bad payload -> 422, no event ---------------------------------

def test_post_os_activity_bad_payload_422_no_event() -> None:
    cfg = SystemConfig()
    cfg.os_activity.enabled = True
    captured: list[Any] = []
    client = _client_for(_runtime(cfg, captured))

    # Missing required active_app.
    assert client.post("/api/os-activity", json={"window_title": "x"}).status_code == 422
    # Empty active_app (min_length=1).
    assert client.post("/api/os-activity", json={"active_app": ""}).status_code == 422
    # Over-length active_app (max_length=256).
    assert (
        client.post("/api/os-activity", json={"active_app": "a" * 257}).status_code
        == 422
    )
    # Wrong type for active_app.
    assert (
        client.post("/api/os-activity", json={"active_app": ["not", "a", "str"]}).status_code
        == 422
    )
    # No event ever emitted for a rejected payload.
    assert captured == []


# --- 12. POST ON, emit raises -> honest-degrade HTTP-200 -------------------

def test_post_os_activity_emit_raises_honest_degrade() -> None:
    cfg = SystemConfig()
    cfg.os_activity.enabled = True

    def _raise(_ev: Any) -> None:
        raise RuntimeError("emit blew up")

    runtime = SimpleNamespace(config=cfg, emit_event=_raise)
    client = _client_for(runtime)

    r = client.post("/api/os-activity", json={"active_app": "Code.exe"})

    # Honest-degrade: never a 500; the sample is dropped with a reason.
    assert r.status_code == 200
    assert r.json() == {"ingested": False, "reason": "emit_error"}


# --- 13. default-OFF round-trips through model_dump/model_validate ----------

def test_os_activity_config_round_trips_off() -> None:
    dumped = SystemConfig().os_activity.model_dump()

    assert dumped == {"enabled": False, "poll_interval_seconds": 5}
    # Re-validating the dumped default yields the same OFF consent state.
    restored = OSActivityConfig.model_validate(dumped)
    assert restored.enabled is False
    assert restored.poll_interval_seconds == 5
