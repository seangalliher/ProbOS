"""Issue #1375 bridge: real WSEventStreamHub frames and production REST bodies.

Invocation (from the repository root, PYTHONPATH=<root>/src;<root>):
    python -u tests/fixtures/issue1375_work_state_bridge.py <root> <scenario> <url-templates-json>

Writes one JSON object to stdout:
    {python, origins, ids, checkpoints: [{name, frames: [text], rest: {url: {status, body}}}]}
Frames are the exact texts the hub sent to a fake socket. REST bodies are the
exact texts the production app served over ``httpx.ASGITransport``. URL
templates may name the scenario's ids: ``{X}`` (the work item under test) and,
for ``native_failed``, ``{P}`` (its crew-session parent) and ``{T}`` (its room).
``restart`` closes the hub between its checkpoints, fails X while no client is
connected, and serves the second checkpoint from a new hub generation.
Exits 3 when a wait or the whole run exceeds its wall-clock budget.
"""

from __future__ import annotations

import time

_PROCESS_STARTED = time.monotonic()

import asyncio  # noqa: E402
import dataclasses  # noqa: E402
import inspect  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any, Awaitable, Callable  # noqa: E402

import httpx  # noqa: E402
from starlette.websockets import WebSocketDisconnect  # noqa: E402

import probos  # noqa: E402
from probos import api as probos_api  # noqa: E402
from probos import crew_session_live  # noqa: E402
from probos import workforce as probos_workforce  # noqa: E402
from probos import ws_event_stream  # noqa: E402
from probos.api import create_app  # noqa: E402
from probos.cognitive import crew_executor, turn_promotion  # noqa: E402
from probos.events import EventType  # noqa: E402
from probos.routers import workforce as workforce_router  # noqa: E402
from probos.workforce import WorkItemStore  # noqa: E402
from probos.ws_event_stream import WSEventStreamHub  # noqa: E402
from ui.e2e.fixtures import ad1192_backend  # noqa: E402
from ui.e2e.fixtures.ad1192_backend import FixtureState, _build_state  # noqa: E402

BUDGET_SECONDS = 8.0
WAIT_SECONDS = 5.0
BUDGET_EXIT_CODE = 3
SCENARIOS = ("promoted_failed", "native_failed", "restart")
AGENT_ID = "worker-a"
THREAD_ID = "issue1375-thread"
REQUEST_TEXT = "Survey the aft sensor array"
_URL_PREFIXES = ("/api/work-items", "/api/crew-tasks")


class BridgeBudgetExceeded(Exception):
    """A bounded wait or the whole bridge run exceeded its wall-clock budget."""


class _FrameSocket:
    """The hub-facing socket surface of test_ad1133's ``_FakeWebSocket``."""

    def __init__(self) -> None:
        self.query_params: dict[str, str] = {}
        self.accepted = asyncio.Event()
        self.closed = asyncio.Event()
        self.sent: list[str] = []
        self.close_code: int | None = None

    async def accept(self) -> None:
        self.accepted.set()

    async def send_text(self, payload: str) -> None:
        self.sent.append(payload)

    async def receive_text(self) -> str:
        await self.closed.wait()
        raise WebSocketDisconnect(code=self.close_code or 1000)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        del reason
        self.close_code = code
        self.closed.set()


class _HubRuntime:
    """The runtime surface the hub reads, with test_ad1133 ``_Runtime``'s snapshot base."""

    def __init__(self, runtime: Any) -> None:
        self.work_item_store = runtime.work_item_store
        self.crew_session_service = runtime.crew_session_service
        self.chat_thread_store = runtime.chat_thread_store
        self.artifact_store = runtime.artifact_store

    def build_bounded_hxi_snapshot_base(self) -> dict[str, Any]:
        return {
            "agents": [],
            "connections": [],
            "pools": [],
            "system_mode": "active",
            "tc_n": 0.0,
            "routing_entropy": 0.0,
            "fresh_boot": False,
            "temporal": {
                "current_time_utc": "2026-07-23T00:00:00+00:00",
                "uptime_seconds": 0.0,
                "lifecycle_state": "running",
                "stasis_duration": None,
                "session_id": "test-session",
            },
            "pool_groups": {},
            "pool_to_group": {},
            "directives": {"active": 0, "pending": 0},
            "notifications": [],
            "unread_count": 0,
            "scheduled_tasks": [],
            "ward_room_stats": None,
            "skill_framework": False,
            "acm": False,
        }


class _EventRelay:
    """Forwards the fixture store's emitted events to the hub in ``_emit_event``'s envelope."""

    def __init__(self, events: list[tuple[Any, dict[str, Any]]], hub: WSEventStreamHub) -> None:
        self._events = events
        self._hub = hub
        self._cursor = len(events)
        self.forwarded = 0

    def has_next(self) -> bool:
        return self._cursor < len(self._events)

    def forward_next(self) -> str:
        event_type, data = self._events[self._cursor]
        self._cursor += 1
        name = event_type.value if isinstance(event_type, EventType) else event_type
        self._hub.ingress({"type": name, "data": data or {}, "timestamp": time.time()})
        self.forwarded += 1
        return str(name)

    def forward(self) -> int:
        count = 0
        while self.has_next():
            self.forward_next()
            count += 1
        return count


def module_origins() -> dict[str, str]:
    modules = (
        probos, probos_api, probos_workforce, ws_event_stream, crew_session_live,
        turn_promotion, crew_executor, workforce_router, ad1192_backend, sys.modules[__name__],
    )
    return {module.__name__: str(Path(inspect.getfile(module)).resolve()) for module in modules}


def assert_candidate_origins(root: Path) -> None:
    # The origin assertion of tests/test_ad1132_crew_session_api.py's owned_projection_case.
    assert Path(inspect.getfile(WorkItemStore)).resolve() == root / "src/probos/workforce.py"
    assert Path(inspect.getfile(_build_state)).resolve() == root / "ui/e2e/fixtures/ad1192_backend.py"
    allowed = (root / "src", root / "tests" / "fixtures", root / "ui" / "e2e" / "fixtures")
    for name, origin in module_origins().items():
        if not any(Path(origin).is_relative_to(parent) for parent in allowed):
            raise AssertionError(f"module {name} resolved outside the candidate tree: {origin}")


async def _wait_until(predicate: Callable[[], bool], what: str) -> None:
    limit = time.monotonic() + WAIT_SECONDS
    while not predicate():
        if time.monotonic() >= limit:
            raise BridgeBudgetExceeded(f"{what} did not arrive within {WAIT_SECONDS:.0f}s")
        await asyncio.sleep(0.005)


def _resolve(template: str, ids: dict[str, str]) -> str:
    if (
        type(template) is not str
        or len(template) > 512
        or not template.startswith(_URL_PREFIXES)
        or ".." in template
        or "\\" in template
    ):
        raise ValueError(f"issue1375_url_template_invalid: {template!r}")
    url = template
    for name, value in ids.items():
        url = url.replace("{" + name + "}", value)
    if "{" in url or "}" in url:
        raise ValueError(f"issue1375_url_template_unresolved: {template!r}")
    return url


class _Stream:
    """One hub generation serving one fake socket; ``open`` again starts a new generation."""

    def __init__(self, runtime: Any, events: list[tuple[Any, dict[str, Any]]]) -> None:
        self._runtime = runtime
        self._events = events
        self.socket = _FrameSocket()
        self.relay: _EventRelay | None = None
        self._hub: WSEventStreamHub | None = None
        self._connection: asyncio.Task[None] | None = None

    async def open(self) -> None:
        # A new relay starts at the current event cursor: nothing emitted while closed is sent.
        self._hub = WSEventStreamHub(_HubRuntime(self._runtime))
        self.socket = _FrameSocket()
        await self._hub.start()
        self.relay = _EventRelay(self._events, self._hub)
        self._connection = asyncio.create_task(
            self._hub.serve(self.socket), name="issue1375-bridge-socket",
        )
        await _wait_until(lambda: len(self.socket.sent) == 1, "state snapshot")

    async def close(self) -> None:
        hub, connection = self._hub, self._connection
        self._hub = self._connection = None
        if hub is not None:
            await hub.stop()
        if connection is not None:
            await asyncio.gather(connection, return_exceptions=True)


class _Recorder:
    def __init__(
        self,
        stream: _Stream,
        client: httpx.AsyncClient,
        templates: list[str],
    ) -> None:
        self._stream = stream
        self._client = client
        self._templates = templates
        self._socket = stream.socket
        self._frame_cursor = 0
        self.checkpoints: list[dict[str, Any]] = []

    async def checkpoint(self, name: str, ids: dict[str, str]) -> None:
        relay, socket = self._stream.relay, self._stream.socket
        if relay is None:
            raise AssertionError(f"{name}: the stream is closed")
        if socket is not self._socket:
            self._socket, self._frame_cursor = socket, 0
        # One event at a time, so no crew projection coalesces with the next event. An event
        # with no frame times out; the count check below catches any extra frame sent before it.
        while relay.has_next():
            sent = len(socket.sent)
            event_type = relay.forward_next()
            await _wait_until(lambda: len(socket.sent) > sent, f"{name} frame for {event_type}")
        expected = 1 + relay.forwarded
        rest: dict[str, dict[str, Any]] = {}
        for template in self._templates:
            url = _resolve(template, ids)
            response = await self._client.get(url)
            rest[url] = {"status": response.status_code, "body": response.text}
        if relay.forward() or len(socket.sent) != expected:
            raise AssertionError(f"{name}: the hub sent frames the relay did not account for")
        frames = socket.sent[self._frame_cursor:]
        self._frame_cursor = len(socket.sent)
        self.checkpoints.append({"name": name, "frames": frames, "rest": rest})

    async def restart(self, while_down: Callable[[], Awaitable[None]]) -> None:
        """Close the hub, run ``while_down`` with no client connected, then open a new generation."""
        await self._stream.close()
        await while_down()
        await self._stream.open()


async def _stop_state(state: FixtureState) -> None:
    # The teardown of tests/test_ad1132_crew_session_api.py's owned_projection_case.
    tasks = tuple(state.running_executions.values()) + tuple(state.scheduled.values())
    for task in tasks:
        if not task.done():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await state.orchestrator.stop()
    await state.route_agent.stop()
    await state.trust.stop()
    await state.secondary_store.stop()
    await state.store.stop()


async def _promoted_failed(
    state: FixtureState, recorder: _Recorder, client: httpx.AsyncClient,
) -> dict[str, str]:
    del client
    item = await turn_promotion._create_promoted_work_item(
        runtime=state.runtime,
        agent_id=AGENT_ID,
        thread_id=THREAD_ID,
        request_text=REQUEST_TEXT,
    )
    if item is None:
        raise RuntimeError("issue1375_promoted_work_item_not_created")
    ids = {"X": item.id}
    await recorder.checkpoint("promoted", ids)
    # The terminal call turn_promotion._close_expired_unconfirmed_turn makes.
    await state.runtime.work_item_store.transition_work_item(item.id, "failed", source=AGENT_ID)
    await recorder.checkpoint("failed", ids)
    return ids


async def _adopt(client: httpx.AsyncClient, parent_id: str) -> None:
    # The production adopt path of tests/test_ad1132_crew_session_api.py's _OwnedProjectionCase.apply.
    base = f"/api/work-items/{parent_id}/owned-steps"
    observed = await client.get(base)
    if observed.status_code != 200:
        raise AssertionError(f"issue1375 owned-steps view failed: {observed.status_code} {observed.text}")
    preview = await client.post(f"{base}/preview", json={
        "version": 1, "kind": "adopt_existing", "preparation_id": "issue1375-adopt-prepare",
        "reference": observed.json()["reference"],
    })
    if preview.status_code != 200:
        raise AssertionError(f"issue1375 adoption preview failed: {preview.status_code} {preview.text}")
    adopted = await client.post(f"{base}/adopt", json={
        "version": 1, "operation_id": "issue1375-adopt-apply",
        "reference": preview.json()["proposal"]["reference"],
    })
    if adopted.status_code != 200:
        raise AssertionError(f"issue1375 adoption failed: {adopted.status_code} {adopted.text}")


def _fail_worker_for(state: FixtureState, child_id: str) -> list[str]:
    """Wrap the fixture worker so ``child_id``'s run ends ``stopped_reason="error"``."""
    original = state.worker.run
    failed: list[str] = []

    async def run(**kwargs: Any) -> Any:
        outcome = await original(**kwargs)
        if kwargs["owned_steps_execution_permit"].child_id != child_id:
            return outcome
        failed.append(child_id)
        return dataclasses.replace(outcome, stopped_reason="error")

    state.worker.run = run
    return failed


async def _native_failed(
    state: FixtureState, recorder: _Recorder, client: httpx.AsyncClient,
) -> dict[str, str]:
    setup = await state.create_canonical()
    parent_id, child_id = setup["parent_id"], setup["child_id"]
    await _adopt(client, parent_id)
    ids = {"P": parent_id, "X": child_id, "T": setup["thread_id"]}
    await recorder.checkpoint("adopted", ids)
    failed = _fail_worker_for(state, child_id)
    # The real executor maps the worker's error outcome to a failed child.
    results = await state.executor.run(parent_id)
    if failed != [child_id] or [(r.work_item_id, r.status) for r in results] != [(child_id, "failed")]:
        raise AssertionError(f"issue1375 native child did not fail through the executor: {results!r}")
    await recorder.checkpoint("failed", ids)
    return ids


async def _restart(
    state: FixtureState, recorder: _Recorder, client: httpx.AsyncClient,
) -> dict[str, str]:
    del client
    item = await turn_promotion._create_promoted_work_item(
        runtime=state.runtime,
        agent_id=AGENT_ID,
        thread_id=THREAD_ID,
        request_text=REQUEST_TEXT,
    )
    if item is None:
        raise RuntimeError("issue1375_promoted_work_item_not_created")
    ids = {"X": item.id}
    await recorder.checkpoint("in_progress", ids)

    async def fail_while_down() -> None:
        await state.runtime.work_item_store.transition_work_item(item.id, "failed", source=AGENT_ID)

    await recorder.restart(fail_while_down)
    await recorder.checkpoint("restarted", ids)
    return ids


_SCENARIO_RUNNERS = {
    "promoted_failed": _promoted_failed,
    "native_failed": _native_failed,
    "restart": _restart,
}


async def run_scenario(
    scenario: str,
    url_templates: list[str],
    storage_root: Path,
) -> dict[str, Any]:
    """Run one scenario against a real hub and the production app; return its capture."""
    if scenario not in SCENARIOS:
        raise ValueError(f"issue1375_scenario_unknown: {scenario!r}")
    if type(url_templates) is not list or not url_templates:
        raise ValueError("issue1375_url_templates_invalid")
    state = await _build_state(storage_root)
    stream = _Stream(state.runtime, state.events)
    try:
        await stream.open()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(state.runtime)),
            base_url="http://test",
        ) as client:
            recorder = _Recorder(stream, client, url_templates)
            ids = await _SCENARIO_RUNNERS[scenario](state, recorder, client)
        return {"ids": ids, "checkpoints": recorder.checkpoints}
    finally:
        await stream.close()
        await _stop_state(state)


async def _run_bounded(scenario: str, templates: list[str], remaining: float) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="probos-issue1375-", ignore_cleanup_errors=True) as storage:
        return await asyncio.wait_for(run_scenario(scenario, templates, Path(storage)), timeout=remaining)


def main(argv: list[str]) -> int:
    if len(argv) != 4:
        sys.stderr.write("usage: issue1375_work_state_bridge.py <root> <scenario> <url-templates-json>\n")
        return 2
    root = Path(argv[1]).resolve()
    if root != Path(__file__).resolve().parents[2]:
        sys.stderr.write(f"issue1375 bridge root mismatch: {root}\n")
        return 2
    assert_candidate_origins(root)
    templates = json.loads(argv[3])
    remaining = BUDGET_SECONDS - (time.monotonic() - _PROCESS_STARTED)
    try:
        if remaining <= 0:
            raise BridgeBudgetExceeded("imports consumed the whole budget")
        capture = asyncio.run(_run_bounded(argv[2], templates, remaining))
    except (BridgeBudgetExceeded, TimeoutError) as exc:
        sys.stderr.write(f"issue1375 bridge exceeded its {BUDGET_SECONDS:.0f}s budget: {exc!r}\n")
        return BUDGET_EXIT_CODE
    elapsed = time.monotonic() - _PROCESS_STARTED
    if elapsed > BUDGET_SECONDS:
        sys.stderr.write(f"issue1375 bridge took {elapsed:.2f}s, over its {BUDGET_SECONDS:.0f}s budget\n")
        return BUDGET_EXIT_CODE
    sys.stdout.write(json.dumps({
        "python": sys.executable,
        "origins": module_origins(),
        "elapsed_seconds": round(elapsed, 3),
        **capture,
    }, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
