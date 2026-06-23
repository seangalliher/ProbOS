"""AD-841 v1: tests for the read-only desktop-integration STATUS endpoint.

READ-ONLY — reports configured ``config.desktop`` values plus a derived
"wired-this-boot" presence signal (public-attribute presence only). NOT live OS
truth, NO app/window enumeration, NO launch/start/stop control.

Two hard invariants under test:

* **Privacy:** the single-instance lock path is reduced to its BASENAME — the
  full path / home directory / OS username are NEVER in the response body
  (test #3).
* **Presence via public attrs:** liveness comes from the public runtime attrs
  wired in ``startup/finalize.py`` (``desktop_lifecycle`` / ``tray_manager`` /
  ``hotkey_listener`` / ``notification_center``).

BF-287 real-transport: the router path is exercised through a real FastAPI
``TestClient`` + a config-shaped ``SimpleNamespace`` runtime (no MagicMock at the
boundary) via ``app.dependency_overrides[get_runtime]``. The crew-scope gate is a
pass-through here because the SimpleNamespace runtime has no ``config.auth``.

Run: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad841_desktop_status.py -q -n 0
"""
from __future__ import annotations

import getpass
import os
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.routers import desktop as desktop_router
from probos.routers.deps import get_runtime


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #


def _runtime(
    *,
    enabled: bool,
    lock_file: str = "~/.probos/yeo.lock",
    wired: bool = False,
    hotkey: str = "ctrl+shift+space",
    tray_autostart: bool = True,
    notification_timeout_sec: int = 5,
    quiet_hours_start: str = "19:00",
    quiet_hours_end: str = "08:00",
    autostart_enabled: bool = False,
):
    """A config-shaped runtime (SimpleNamespace, not MagicMock) for the router.

    ``wired=True`` attaches the four PUBLIC desktop attrs (matching
    ``startup/finalize.py``) so the presence signals read non-None.
    """
    rt = SimpleNamespace(
        config=SimpleNamespace(
            desktop=SimpleNamespace(
                enabled=enabled,
                tray_autostart=tray_autostart,
                hotkey=hotkey,
                notification_timeout_sec=notification_timeout_sec,
                quiet_hours_start=quiet_hours_start,
                quiet_hours_end=quiet_hours_end,
                lock_file=lock_file,
                autostart_enabled=autostart_enabled,
            )
        )
    )
    if wired:
        rt.desktop_lifecycle = object()
        rt.tray_manager = object()
        rt.hotkey_listener = object()
        rt.notification_center = object()
    return rt


def _client(runtime) -> TestClient:
    app = FastAPI()
    app.include_router(desktop_router.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


# --------------------------------------------------------------------------- #
# 1. Desktop OFF → off shape, presence flags false, config values still present
# --------------------------------------------------------------------------- #


def test_desktop_off_shape() -> None:
    rt = _runtime(enabled=False)  # enabled False, no desktop_lifecycle wired
    with _client(rt) as client:
        resp = client.get("/api/desktop/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["active"] is False
    assert body["tray"]["active"] is False
    assert body["hotkey"]["active"] is False
    assert body["notifications"]["active"] is False
    # It's a STATUS readout: configured values are reported even when off.
    assert body["hotkey"]["binding"] == "ctrl+shift+space"
    assert body["tray"]["autostart"] is True
    assert body["notifications"]["timeout_sec"] == 5
    assert body["quiet_hours"] == {"start": "19:00", "end": "08:00"}
    assert body["autostart_enabled"] is False
    assert body["lock"]["name"] == "yeo.lock"


# --------------------------------------------------------------------------- #
# 2. Desktop ON + wired → active true, presence true, binding reported
# --------------------------------------------------------------------------- #


def test_desktop_on_active_presence_true() -> None:
    rt = _runtime(enabled=True, wired=True)
    with _client(rt) as client:
        resp = client.get("/api/desktop/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["active"] is True
    assert body["tray"]["active"] is True
    assert body["hotkey"]["active"] is True
    assert body["notifications"]["active"] is True
    assert body["hotkey"]["binding"] == "ctrl+shift+space"


# --------------------------------------------------------------------------- #
# 3. NO PATH LEAK — only the basename is exposed (the #1 privacy invariant)
# --------------------------------------------------------------------------- #


def test_no_path_leak() -> None:
    rt = _runtime(enabled=True, lock_file="~/.probos/yeo.lock")
    with _client(rt) as client:
        resp = client.get("/api/desktop/status")
    assert resp.status_code == 200
    raw = resp.text  # the serialized JSON body
    body = resp.json()
    # Basename IS present...
    assert body["lock"]["name"] == "yeo.lock"
    assert "yeo.lock" in raw
    # ...but the full path / home dir / parent dir / OS username are ABSENT.
    home = os.path.expanduser("~")
    assert home not in raw
    assert ".probos" not in raw
    assert "Users" not in raw
    username = getpass.getuser()
    if username:  # guard the degenerate empty-username case ("" in s is True)
        assert username not in raw


# --------------------------------------------------------------------------- #
# 4. Lock present (deterministic, real file in tmp_path) — dir never leaked
# --------------------------------------------------------------------------- #


def test_lock_present_deterministic(tmp_path) -> None:
    lock = tmp_path / "yeo.lock"
    lock.write_text("pid-marker", encoding="utf-8")
    rt = _runtime(enabled=True, lock_file=str(lock))
    with _client(rt) as client:
        resp = client.get("/api/desktop/status")
    assert resp.status_code == 200
    raw = resp.text
    body = resp.json()
    assert body["lock"]["present"] is True
    assert body["lock"]["name"] == "yeo.lock"
    # The containing directory is never exposed — basename only.
    assert str(tmp_path) not in raw


# --------------------------------------------------------------------------- #
# 5. Honest-degrade — runtime with no config → defaulted OFF shape, HTTP 200
# --------------------------------------------------------------------------- #


def test_honest_degrade_no_config() -> None:
    rt = SimpleNamespace()  # no `config` attribute at all
    with _client(rt) as client:
        resp = client.get("/api/desktop/status")
    assert resp.status_code == 200  # never 500
    body = resp.json()
    assert body["enabled"] is False
    assert body["active"] is False
    assert body["tray"]["active"] is False
    assert body["hotkey"]["active"] is False
    assert body["notifications"]["active"] is False
    assert body["lock"] == {"name": "", "present": False}
