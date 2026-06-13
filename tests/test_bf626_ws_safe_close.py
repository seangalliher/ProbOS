"""BF-626: WebSocket close must not surface a peer-disconnect race as an
unhandled ASGI exception.

The avatar-telemetry handlers ``accept()`` then ``close()`` on a gate (e.g.
``no_crew_agents`` during the boot window, before crew agents register). When
the HXI peer has already disconnected, the underlying ``websockets`` legacy
protocol raises ``AttributeError: 'WebSocketProtocol' object has no attribute
'transfer_data_task'`` from inside ``close()`` — observed live as
``ERROR: Exception in ASGI application``. ``_safe_ws_close`` swallows the
close-time race (the connection is going away regardless).
"""
from __future__ import annotations

import inspect

from probos.routers.agents import (
    _safe_ws_close,
    agent_avatar_telemetry_stream,
    fleet_avatar_telemetry_stream,
)


class _RaisingCloseWS:
    """A WebSocket stand-in whose ``close()`` raises — the reported crash."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc
        self.close_calls: list[tuple[int, str]] = []

    async def close(self, *, code: int, reason: str) -> None:
        self.close_calls.append((code, reason))
        raise self._exc


class _RecordingWS:
    def __init__(self) -> None:
        self.close_calls: list[tuple[int, str]] = []

    async def close(self, *, code: int, reason: str) -> None:
        self.close_calls.append((code, reason))


# --------------------------------------------------------------------------- #
# the reported crash — must be swallowed                                      #
# --------------------------------------------------------------------------- #


async def test_safe_ws_close_swallows_transfer_data_task_attributeerror() -> None:
    """The exact live failure: close() raises the transfer_data_task error.

    ``_safe_ws_close`` must NOT propagate it (otherwise it surfaces as
    'Exception in ASGI application' in the server log)."""
    ws = _RaisingCloseWS(
        AttributeError(
            "'WebSocketProtocol' object has no attribute 'transfer_data_task'"
        )
    )
    # Must not raise.
    await _safe_ws_close(ws, code=1008, reason="no_crew_agents")
    # The close was still attempted with the intended code/reason.
    assert ws.close_calls == [(1008, "no_crew_agents")]


async def test_safe_ws_close_swallows_runtimeerror() -> None:
    """A RuntimeError from closing an already-closed/disconnected socket is
    also swallowed (the peer is gone — nothing to deliver)."""
    ws = _RaisingCloseWS(RuntimeError("Unexpected ASGI message after close"))
    await _safe_ws_close(ws, code=1011, reason="runtime_unavailable")
    assert ws.close_calls == [(1011, "runtime_unavailable")]


# --------------------------------------------------------------------------- #
# happy path — forwards code + reason                                         #
# --------------------------------------------------------------------------- #


async def test_safe_ws_close_normal_path_forwards_code_reason() -> None:
    ws = _RecordingWS()
    await _safe_ws_close(ws, code=1008, reason="agent_not_found")
    assert ws.close_calls == [(1008, "agent_not_found")]


# --------------------------------------------------------------------------- #
# source guard — both handlers route closes through the helper                #
# --------------------------------------------------------------------------- #


def test_handlers_route_all_closes_through_safe_helper() -> None:
    """Regression guard: neither telemetry handler may call
    ``websocket.close()`` directly (that re-introduces the BF-626 crash).
    All close paths must go through ``_safe_ws_close``."""
    for fn in (agent_avatar_telemetry_stream, fleet_avatar_telemetry_stream):
        src = inspect.getsource(fn)
        assert "websocket.close(" not in src, (
            f"{fn.__name__} must route closes through _safe_ws_close (BF-626) "
            "— a raw websocket.close() can raise AttributeError("
            "transfer_data_task) when the peer disconnects during the boot "
            "window."
        )
        assert "_safe_ws_close(" in src, (
            f"{fn.__name__} should close via _safe_ws_close (BF-626)."
        )
