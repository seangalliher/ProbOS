"""AD-1270f P1.2: bounded shutdown graces and the teardown-scoped fast stop.

Production ``stop()`` waits 1 s (AD-435, before the periodic flush and the
remaining write-holding services are quiesced) and 2 s (BF-296 Phase A, after
the intent bus closes to new dispatches and before consolidation). Those
waits are now two bounded ``MemoryConfig`` fields whose defaults are today's
waits and also their maximums. The shared runtime factory
(``tests/fixtures/runtime_factory.py``) can zero both for a runtime's FINAL stop
only: a fixture's teardown or the last action of a test. Three guards pin who gets
that and where it may sit: ``FAST_TEARDOWN_OPT_IN_FILES`` (files that ask for it),
``FAST_TEARDOWN_EFFECTIVE_MODULES`` (test modules that receive it through a fixture
they define or import from any fixture source) and a final-action guard (a request
may only be the last action of a fixture or of a test, so no assertion follows it).

No opted-in test body observes what ``stop()`` leaves behind, with one
intentional exception: this file. Its real-boot test (d) reads the persisted
shutdown marker after a fast teardown, on purpose.

The two real-boot tests are separate tests that each run to completion: two live
runtimes in one process share the YeomanAgent singleton, so they must never
overlap.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
import logging
import math
import re
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml
from fastapi.testclient import TestClient
from pydantic import ValidationError

from probos.api import create_app
from probos.cognitive.llm_client import MockLLMClient
from probos.config import MemoryConfig, SystemConfig, load_config
from probos.startup.shutdown import (
    SHUTDOWN_DISPATCH_GRACE_S,
    SHUTDOWN_WRITE_GRACE_S,
    _grace_seconds,
    _memory_field,
    shutdown,
)
from tests.fixtures import runtime_factory
from tests.fixtures.runtime_factory import (
    FAST_TEARDOWN_EFFECTIVE_MODULES,
    FAST_TEARDOWN_OPT_IN_FILES,
    FAST_TEARDOWN_OVERRIDES,
    make_runtime,
    started_runtime,
    stop_runtime,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SHUTDOWN_LOGGER = "probos.startup.shutdown"

_GRACE_FIELDS = (
    ("shutdown_write_grace_s", SHUTDOWN_WRITE_GRACE_S, 1.0),
    ("shutdown_dispatch_grace_s", SHUTDOWN_DISPATCH_GRACE_S, 2.0),
)
_GRACE_FIELD_PARAMS = [
    pytest.param(field, default, id=field) for field, default, _ in _GRACE_FIELDS
]


def _write_grace_message(seconds: str) -> str:
    return f"Shutdown grace period ({seconds}s)..."


def _dispatch_grace_message(seconds: str) -> str:
    return (
        "BF-296 Phase A: intent dispatch closed; "
        f"{seconds}s grace for in-flight handlers complete"
    )


# ---------------------------------------------------------------------------
# (a) Config fields
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(("field", "constant", "expected"), _GRACE_FIELDS)
def test_field_default_equals_shutdown_constant_and_todays_wait(
    field: str, constant: float, expected: float,
) -> None:
    assert MemoryConfig.model_fields[field].default == constant == expected
    assert getattr(MemoryConfig(), field) == expected
    assert getattr(SystemConfig().memory, field) == expected


_BAD_FIELD_VALUES = [
    pytest.param(field, value, id=f"{field}-{label}")
    for field, default, _ in _GRACE_FIELDS
    for label, value in (
        ("negative", -0.1),
        ("above-default", default + 0.1),
        ("nan", math.nan),
        ("inf", math.inf),
        ("minus-inf", -math.inf),
    )
]


@pytest.mark.parametrize(("field", "value"), _BAD_FIELD_VALUES)
def test_field_bounds_reject_negative_above_default_nan_and_inf(
    field: str, value: float,
) -> None:
    with pytest.raises(ValidationError):
        MemoryConfig(**{field: value})
    with pytest.raises(ValidationError):
        SystemConfig.model_validate({"memory": {field: value}})


@pytest.mark.parametrize(("field", "default"), _GRACE_FIELD_PARAMS)
def test_field_bounds_accept_zero_a_lower_value_and_the_default(
    field: str, default: float,
) -> None:
    for value in (0.0, default / 2, default):
        assert getattr(MemoryConfig(**{field: value}), field) == value


def test_config_without_the_keys_loads_with_todays_waits() -> None:
    memory = MemoryConfig.model_validate({"collection_name": "legacy"})

    assert memory.shutdown_write_grace_s == 1.0
    assert memory.shutdown_dispatch_grace_s == 2.0


@pytest.mark.parametrize("name", ["system.yaml", "node-1.yaml", "node-2.yaml"])
def test_shipped_configs_load_with_todays_waits(name: str) -> None:
    memory = load_config(_REPO_ROOT / "config" / name).memory

    assert memory.shutdown_write_grace_s == 1.0
    assert memory.shutdown_dispatch_grace_s == 2.0


# ---------------------------------------------------------------------------
# (a2) Coercion: the real config producers refuse a non-number
#
# Pydantic's lax float parsing turns a YAML or facade ``false`` into 0.0 (the
# wait is skipped), ``true`` into 1.0 and "0.5" or Decimal("0.5") into 0.5, and
# all of them were then persisted. MemoryConfig's before-validator admits only a
# plain int or float. The producers below are the real ones: the model, the
# project's YAML loader and the facade's POST handler.
# ---------------------------------------------------------------------------

_GRACE_FIELD_NAMES = [field for field, _, _ in _GRACE_FIELDS]
_GRACE_DEFAULTS = {field: default for field, default, _ in _GRACE_FIELDS}

_NON_NUMBERS = [
    pytest.param(False, id="bool-false"),
    pytest.param(True, id="bool-true"),
    pytest.param("0.5", id="str"),
    pytest.param(Decimal("0.5"), id="decimal"),
    pytest.param(None, id="none"),
    pytest.param([], id="list"),
]

_NUMBERS = [  # (field, value as written, value as stored)
    pytest.param("shutdown_write_grace_s", 0, 0.0, id="write-int-zero"),
    pytest.param("shutdown_write_grace_s", 1, 1.0, id="write-int-max"),
    pytest.param("shutdown_write_grace_s", 0.5, 0.5, id="write-float"),
    pytest.param("shutdown_dispatch_grace_s", 0, 0.0, id="dispatch-int-zero"),
    pytest.param("shutdown_dispatch_grace_s", 2, 2.0, id="dispatch-int-max"),
    pytest.param("shutdown_dispatch_grace_s", 1.5, 1.5, id="dispatch-float"),
]


@pytest.mark.parametrize("field", _GRACE_FIELD_NAMES)
@pytest.mark.parametrize("value", _NON_NUMBERS)
def test_system_config_refuses_a_non_number_grace_instead_of_coercing_it(
    field: str, value: Any,
) -> None:
    with pytest.raises(ValidationError) as raised:
        SystemConfig.model_validate({"memory": {field: value}})

    first = raised.value.errors()[0]
    assert first["loc"] == ("memory", field)
    assert first["type"] == "value_error"
    assert "plain number" in first["msg"]


@pytest.mark.parametrize("field", _GRACE_FIELD_NAMES)
@pytest.mark.parametrize("literal", ["false", "true", '"0.5"'])
def test_system_config_json_refuses_a_non_number_grace(
    field: str, literal: str,
) -> None:
    with pytest.raises(ValidationError):
        SystemConfig.model_validate_json(
            f'{{"memory": {{"{field}": {literal}}}}}',
        )


@pytest.mark.parametrize(("field", "value", "stored"), _NUMBERS)
def test_system_config_accepts_an_int_or_float_grace_and_stores_a_float(
    field: str, value: float, stored: float,
) -> None:
    memory = SystemConfig.model_validate({"memory": {field: value}}).memory

    assert getattr(memory, field) == stored
    assert type(getattr(memory, field)) is float


@pytest.mark.parametrize("field", _GRACE_FIELD_NAMES)
@pytest.mark.parametrize("literal", ["false", "true", "yes", "off", "'0.5'", '"0.5"'])
def test_load_config_refuses_a_yaml_non_number_grace(
    tmp_path: Path, field: str, literal: str,
) -> None:
    text = f"memory:\n  {field}: {literal}\n"
    path = tmp_path / "system.yaml"
    path.write_text(text, encoding="utf-8")
    # Premise: YAML itself reads the literal as a bool or a str, not a number.
    assert type(yaml.safe_load(text)["memory"][field]) in (bool, str)

    with pytest.raises(ValidationError) as raised:
        load_config(path)

    first = raised.value.errors()[0]
    assert first["loc"] == ("memory", field)
    assert "plain number" in first["msg"]


@pytest.mark.parametrize(("field", "value", "stored"), _NUMBERS)
def test_load_config_accepts_a_yaml_number_grace(
    tmp_path: Path, field: str, value: float, stored: float,
) -> None:
    path = tmp_path / "system.yaml"
    path.write_text(yaml.safe_dump({"memory": {field: value}}), encoding="utf-8")

    assert getattr(load_config(path).memory, field) == stored


def _facade_client(tmp_path: Path) -> tuple[TestClient, MagicMock]:
    # The tests/test_ad741_config_api.py pattern: a real SystemConfig and a
    # real config_path behind a MagicMock runtime. _data_dir is real too, so
    # create_app does not mkdir a MagicMock path in the repo root (BF-326).
    config_path = tmp_path / "system.yaml"
    config_path.write_text(yaml.safe_dump({}), encoding="utf-8")
    runtime = MagicMock()
    runtime.config = SystemConfig()
    runtime.config_path = str(config_path)
    runtime._data_dir = tmp_path / "data"
    runtime._start_time = 0.0
    return TestClient(create_app(runtime)), runtime


def _post_memory_patch(client: TestClient, memory_patch: dict[str, Any]) -> Any:
    csrf = client.get("/api/config").json()["csrf_token"]
    return client.post(
        "/api/config",
        json={"patch": {"memory": memory_patch}},
        headers={"X-Probos-CSRF": csrf},
    )


@pytest.mark.parametrize("field", _GRACE_FIELD_NAMES)
@pytest.mark.parametrize(
    "value",
    [
        pytest.param(False, id="bool-false"),
        pytest.param(True, id="bool-true"),
        pytest.param("0.5", id="str"),
        pytest.param(None, id="null"),
    ],
)
def test_facade_post_refuses_a_non_number_grace_with_422_and_persists_nothing(
    tmp_path: Path, field: str, value: Any,
) -> None:
    client, runtime = _facade_client(tmp_path)

    response = _post_memory_patch(client, {field: value})

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["error"] == "validation_failed"
    first = body["errors"][0]
    assert first["loc"] == ["memory", field]
    assert first["type"] == "value_error"
    assert "plain number" in first["msg"]
    assert yaml.safe_load(Path(runtime.config_path).read_text(encoding="utf-8")) == {}
    assert getattr(runtime.config.memory, field) == _GRACE_DEFAULTS[field]


@pytest.mark.parametrize(("field", "value", "stored"), _NUMBERS)
def test_facade_post_accepts_an_int_or_float_grace_and_persists_it(
    tmp_path: Path, field: str, value: float, stored: float,
) -> None:
    client, runtime = _facade_client(tmp_path)

    response = _post_memory_patch(client, {field: value})

    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True
    on_disk = yaml.safe_load(Path(runtime.config_path).read_text(encoding="utf-8"))
    assert on_disk["memory"][field] == stored


# ---------------------------------------------------------------------------
# (b) Strict reader: _grace_seconds
# ---------------------------------------------------------------------------

class _Runtime:
    def __init__(self, config: Any) -> None:
        self.config = config


class _RaisingConfigRuntime:
    @property
    def config(self) -> Any:
        raise RuntimeError("config unavailable")


class _RaisingMemoryConfig:
    @property
    def memory(self) -> Any:
        raise RuntimeError("memory unavailable")


class _RaisingFieldMemory:
    @property
    def shutdown_write_grace_s(self) -> float:
        raise RuntimeError("field unavailable")

    @property
    def shutdown_dispatch_grace_s(self) -> float:
        raise RuntimeError("field unavailable")


class _HostileMemory:
    def __getattr__(self, name: str) -> Any:
        raise ValueError(f"hostile lookup of {name}")


def _runtime_with(field: str, value: Any) -> _Runtime:
    return _Runtime(SimpleNamespace(memory=SimpleNamespace(**{field: value})))


_FALLBACK_CASES: dict[str, Callable[[str, float], Any]] = {
    "no-config-attribute": lambda field, default: SimpleNamespace(),
    "config-is-none": lambda field, default: _Runtime(None),
    "no-memory-attribute": lambda field, default: _Runtime(SimpleNamespace()),
    "memory-is-none": lambda field, default: _Runtime(SimpleNamespace(memory=None)),
    "missing-field": lambda field, default: _Runtime(
        SimpleNamespace(memory=SimpleNamespace()),
    ),
    "raising-config": lambda field, default: _RaisingConfigRuntime(),
    "raising-memory": lambda field, default: _Runtime(_RaisingMemoryConfig()),
    "raising-field": lambda field, default: _Runtime(
        SimpleNamespace(memory=_RaisingFieldMemory()),
    ),
    "hostile-getattr": lambda field, default: _Runtime(
        SimpleNamespace(memory=_HostileMemory()),
    ),
    "magicmock-runtime": lambda field, default: MagicMock(),
    "magicmock-memory": lambda field, default: _Runtime(
        SimpleNamespace(memory=MagicMock()),
    ),
    "bool-true": lambda field, default: _runtime_with(field, True),
    "bool-false": lambda field, default: _runtime_with(field, False),
    "nan": lambda field, default: _runtime_with(field, math.nan),
    "inf": lambda field, default: _runtime_with(field, math.inf),
    "minus-inf": lambda field, default: _runtime_with(field, -math.inf),
    "negative-float": lambda field, default: _runtime_with(field, -0.1),
    "negative-int": lambda field, default: _runtime_with(field, -1),
    "above-default": lambda field, default: _runtime_with(field, default + 0.1),
    "far-above-default": lambda field, default: _runtime_with(field, 60.0),
    "int-above-default": lambda field, default: _runtime_with(field, int(default) + 1),
    "huge-int": lambda field, default: _runtime_with(field, 10**400),
    "string": lambda field, default: _runtime_with(field, "0.5"),
    "decimal": lambda field, default: _runtime_with(field, Decimal("0.5")),
    "none-value": lambda field, default: _runtime_with(field, None),
}


@pytest.mark.parametrize(("field", "default"), _GRACE_FIELD_PARAMS)
@pytest.mark.parametrize("case", list(_FALLBACK_CASES))
def test_grace_seconds_falls_back_to_the_default_without_raising(
    case: str, field: str, default: float,
) -> None:
    runtime = _FALLBACK_CASES[case](field, default)

    assert _grace_seconds(runtime, field, default) == default


@pytest.mark.parametrize(("field", "default"), _GRACE_FIELD_PARAMS)
def test_grace_seconds_honours_zero_a_lower_value_and_the_default(
    field: str, default: float,
) -> None:
    for value in (0, 0.0, 0.25, default / 2, default, int(default)):
        result = _grace_seconds(_runtime_with(field, value), field, default)

        assert result == float(value)
        assert type(result) is float


def test_grace_seconds_reads_a_real_system_config() -> None:
    config = SystemConfig(memory=MemoryConfig(shutdown_dispatch_grace_s=0.5))
    runtime = _Runtime(config)

    assert _grace_seconds(runtime, "shutdown_dispatch_grace_s", 2.0) == 0.5
    assert _grace_seconds(runtime, "shutdown_write_grace_s", 1.0) == 1.0


def test_float_of_a_mock_would_have_shortened_the_dispatch_grace() -> None:
    # Premise of the MagicMock fallback cases above: a float()-converting reader
    # (the BF-291 _memory_field) reports 1.0 for a mock, so the strict reader
    # is what keeps a mock-config runtime at today's 2.0 s.
    assert float(MagicMock()) == 1.0
    assert _memory_field(MagicMock(), "shutdown_dispatch_grace_s", 2.0) == 1.0
    assert _grace_seconds(MagicMock(), "shutdown_dispatch_grace_s", 2.0) == 2.0


@pytest.mark.parametrize(("field", "default"), _GRACE_FIELD_PARAMS)
def test_grace_seconds_logs_the_fallback_at_debug_only(
    caplog: pytest.LogCaptureFixture, field: str, default: float,
) -> None:
    with caplog.at_level(logging.DEBUG, logger=_SHUTDOWN_LOGGER):
        _grace_seconds(_runtime_with(field, 0.0), field, default)
        assert not [r for r in caplog.records if "AD-1270f" in r.getMessage()]

        _grace_seconds(_runtime_with(field, default + 1.0), field, default)

    fallbacks = [r for r in caplog.records if "AD-1270f" in r.getMessage()]
    assert len(fallbacks) == 1
    assert fallbacks[0].levelno == logging.DEBUG
    assert field in fallbacks[0].getMessage()


# ---------------------------------------------------------------------------
# shutdown(): both waits follow the validated config
# ---------------------------------------------------------------------------

def _shutdown_runtime(tmp_path: Path, memory: Any | None) -> MagicMock:
    runtime = MagicMock()
    runtime._started = True
    runtime._shutdown_started = False  # BF-598: a MagicMock attribute is truthy
    runtime._session_id = "s1"
    runtime._start_time_wall = time.time()
    runtime._start_time = time.monotonic()
    runtime._data_dir = tmp_path
    runtime.registry.all.return_value = []
    runtime.ontology = MagicMock()
    runtime.event_log.log = AsyncMock()
    runtime.ward_room = None
    runtime.dream_scheduler = None
    runtime.episodic_memory = None
    runtime.intent_bus = MagicMock()
    if memory is not None:
        runtime.config.memory = memory
    return runtime


@pytest.mark.parametrize(
    ("memory", "write", "dispatch"),
    [
        pytest.param(
            SimpleNamespace(shutdown_write_grace_s=0.25, shutdown_dispatch_grace_s=0.5),
            0.25, 0.5, id="lower-values-are-honoured",
        ),
        pytest.param(
            SimpleNamespace(shutdown_write_grace_s=0.0, shutdown_dispatch_grace_s=0.0),
            0.0, 0.0, id="zero-is-honoured",
        ),
        pytest.param(
            SimpleNamespace(shutdown_write_grace_s=60.0, shutdown_dispatch_grace_s=60.0),
            1.0, 2.0, id="above-default-keeps-todays-waits",
        ),
        pytest.param(None, 1.0, 2.0, id="mock-config-keeps-todays-waits"),
    ],
)
async def test_shutdown_waits_follow_the_validated_config_at_both_sites(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    memory: Any | None,
    write: float,
    dispatch: float,
) -> None:
    runtime = _shutdown_runtime(tmp_path, memory)

    with (
        caplog.at_level(logging.INFO, logger=_SHUTDOWN_LOGGER),
        patch("probos.startup.shutdown.asyncio.sleep", new_callable=AsyncMock) as sleep,
    ):
        try:
            await shutdown(runtime, reason="test")
        except Exception:
            pass  # steps after the two waits may raise on a MagicMock runtime

    delays = [call.args[0] for call in sleep.await_args_list]
    messages = [record.getMessage() for record in caplog.records]
    assert delays[:2] == [write, dispatch], delays
    assert _write_grace_message(f"{write:g}") in messages
    assert _dispatch_grace_message(f"{dispatch:g}") in messages


# ---------------------------------------------------------------------------
# Real-boot helpers
# ---------------------------------------------------------------------------

Event = tuple[str, Any]


class _EventHandler(logging.Handler):
    def __init__(self, events: list[Event]) -> None:
        super().__init__(level=logging.INFO)
        self._events = events

    def emit(self, record: logging.LogRecord) -> None:
        self._events.append(("log", record.getMessage()))


class _ShutdownTrace:
    """Ordered ("log", message) and ("sleep", delay) events from one task's stop().

    Log records come from ``probos.startup.shutdown``. Sleeps are recorded only
    for the watched task, because background loops call ``asyncio.sleep``
    constantly. Both go into one list so their relative order is observable.
    """

    def __init__(self) -> None:
        self.events: list[Event] = []
        self._watched: asyncio.Task[Any] | None = None

    def watch_current_task(self) -> None:
        self._watched = asyncio.current_task()

    @contextmanager
    def installed(self) -> Iterator[None]:
        real_sleep = asyncio.sleep

        async def _recording_sleep(delay: float, result: Any = None) -> Any:
            if self._watched is not None and asyncio.current_task() is self._watched:
                self.events.append(("sleep", delay))
            return await real_sleep(delay, result)

        handler = _EventHandler(self.events)
        logger = logging.getLogger(_SHUTDOWN_LOGGER)
        previous_level = logger.level
        logger.setLevel(logging.INFO)
        logger.addHandler(handler)
        try:
            with patch.object(asyncio, "sleep", _recording_sleep):
                yield
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous_level)


def _index_of_log(events: list[Event], message: str) -> int:
    for index, (kind, payload) in enumerate(events):
        if kind == "log" and payload == message:
            return index
    raise AssertionError(f"no shutdown log record {message!r} in {events!r}")


def _assert_sleep_right_after(events: list[Event], message: str, delay: float) -> None:
    index = _index_of_log(events, message)
    assert events[index + 1:index + 2] == [("sleep", delay)], events


def _assert_sleep_right_before(events: list[Event], message: str, delay: float) -> None:
    index = _index_of_log(events, message)
    assert index > 0
    assert events[index - 1] == ("sleep", delay), events


def _read_status(base: Path) -> dict[str, Any]:
    path = base / "data" / "shutdown_status.json"
    assert path.is_file(), "stop() did not write shutdown_status.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _phase1_elapsed_seconds(status: dict[str, Any]) -> float:
    match = re.fullmatch(r"phase1_elapsed=(\d+(?:\.\d+)?)s", str(status.get("note", "")))
    assert match, f"the shutdown marker note has no phase1_elapsed: {status!r}"
    return float(match.group(1))


# ---------------------------------------------------------------------------
# (c) Real boot: a stop in the test body keeps production timing
# ---------------------------------------------------------------------------

async def test_stop_in_the_body_keeps_production_timing_and_teardown_is_a_noop(
    tmp_path: Path,
) -> None:
    config = SystemConfig()
    trace = _ShutdownTrace()

    with trace.installed():
        async with started_runtime(
            tmp_path, config=config, fast_teardown=True,
        ) as runtime:
            trace.watch_current_task()
            await runtime.stop()
            body_events = list(trace.events)
        teardown_events = trace.events[len(body_events):]

    _assert_sleep_right_after(body_events, _write_grace_message("1"), 1.0)
    _assert_sleep_right_before(body_events, _dispatch_grace_message("2"), 2.0)
    assert _index_of_log(body_events, _write_grace_message("1")) < _index_of_log(
        body_events, _dispatch_grace_message("2"),
    )
    reentries = [
        payload for kind, payload in teardown_events
        if kind == "log" and "BF-598: shutdown() re-entered" in payload
    ]
    assert len(reentries) == 1, teardown_events
    assert not [event for event in teardown_events if event[0] == "sleep"]
    assert runtime.config is config  # the factory did not rebind an already-stopped runtime


# ---------------------------------------------------------------------------
# (d) Real boot: the fast teardown skips both waits and keeps the verdict
# ---------------------------------------------------------------------------

async def test_fast_teardown_zeroes_both_waits_and_keeps_status_and_consolidation_result(
    tmp_path: Path,
) -> None:
    """The one intentional post-stop observer among the opted-in files.

    It reads the shutdown marker after a fast teardown. The marker is NOT
    identical to a production-timing stop's: ``status`` and
    ``consolidation_result`` must match, while ``note`` records ``phase1_elapsed``,
    which includes the BF-296 wait, so it drops by about that wait.
    """
    production_config = SystemConfig()
    production_trace = _ShutdownTrace()
    with production_trace.installed():
        async with started_runtime(
            tmp_path / "production", config=production_config,
        ) as production:
            production_trace.watch_current_task()
            await production.stop()
    production_status = _read_status(tmp_path / "production")

    fast_config = SystemConfig()
    fast_trace = _ShutdownTrace()
    with fast_trace.installed():
        async with started_runtime(
            tmp_path / "fast", config=fast_config, fast_teardown=True,
        ) as fast:
            fast_trace.watch_current_task()  # the teardown is the one real stop
    fast_status = _read_status(tmp_path / "fast")

    _assert_sleep_right_after(production_trace.events, _write_grace_message("1"), 1.0)
    _assert_sleep_right_before(production_trace.events, _dispatch_grace_message("2"), 2.0)
    _assert_sleep_right_after(fast_trace.events, _write_grace_message("0"), 0.0)
    _assert_sleep_right_before(fast_trace.events, _dispatch_grace_message("0"), 0.0)
    assert fast.config is not fast_config  # stop() ran on the private copy
    assert fast_config.memory.shutdown_write_grace_s == 1.0
    assert fast_config.memory.shutdown_dispatch_grace_s == 2.0
    # Must match: the persisted verdict.
    assert fast_status["status"] == production_status["status"]
    assert fast_status["consolidation_result"] == production_status["consolidation_result"]
    # Must differ: phase 1 no longer contains the 2 s BF-296 wait.
    production_elapsed = _phase1_elapsed_seconds(production_status)
    fast_elapsed = _phase1_elapsed_seconds(fast_status)
    assert production_elapsed >= SHUTDOWN_DISPATCH_GRACE_S
    assert production_elapsed - fast_elapsed >= 1.0


# ---------------------------------------------------------------------------
# (e) Factory without a boot
# ---------------------------------------------------------------------------

class _FakeRuntime:
    """Just enough runtime for stop_runtime: a config, the BF-598 flag, stop()."""

    def __init__(self, config: Any, *, shutdown_started: bool = False) -> None:
        self.config = config
        self._shutdown_started = shutdown_started
        self.config_at_stop: Any = None
        self.calls: list[str] = []

    async def start(self) -> None:
        self.calls.append("start")

    async def stop(self, reason: str = "") -> None:
        self.calls.append("stop")
        self.config_at_stop = self.config


def _differing_paths(before: Any, after: Any, prefix: str = "") -> set[str]:
    if isinstance(before, dict) and isinstance(after, dict):
        paths: set[str] = set()
        for key in before.keys() | after.keys():
            path = f"{prefix}.{key}" if prefix else str(key)
            if key in before and key in after:
                paths |= _differing_paths(before[key], after[key], path)
            else:
                paths.add(path)
        return paths
    return set() if before == after else {prefix}


@pytest.mark.parametrize("function", [stop_runtime, started_runtime])
def test_fast_teardown_is_keyword_only_and_off_by_default(
    function: Callable[..., Any],
) -> None:
    parameter = inspect.signature(function).parameters["fast_teardown"]

    assert parameter.default is False
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY


async def test_stop_runtime_default_stops_with_the_same_config_object() -> None:
    config = SystemConfig()
    runtime = _FakeRuntime(config)

    await stop_runtime(runtime)

    assert runtime.calls == ["stop"]
    assert runtime.config_at_stop is config
    assert runtime.config is config


async def test_stop_runtime_fast_teardown_zeroes_exactly_the_two_graces_on_a_copy() -> None:
    config = SystemConfig()
    before = config.model_dump()
    runtime = _FakeRuntime(config)

    await stop_runtime(runtime, fast_teardown=True)

    seen = runtime.config_at_stop
    assert runtime.calls == ["stop"]
    assert seen is not config
    assert seen.memory is not config.memory
    assert _differing_paths(before, seen.model_dump()) == {
        "memory.shutdown_write_grace_s",
        "memory.shutdown_dispatch_grace_s",
    }
    assert seen.memory.shutdown_write_grace_s == 0.0
    assert seen.memory.shutdown_dispatch_grace_s == 0.0
    assert config.model_dump() == before  # the caller's config is never mutated


async def test_stop_runtime_fast_teardown_does_not_rebind_after_a_stop_has_started() -> None:
    config = SystemConfig()
    runtime = _FakeRuntime(config, shutdown_started=True)

    await stop_runtime(runtime, fast_teardown=True)

    assert runtime.config_at_stop is config
    assert runtime.config is config


@pytest.mark.parametrize(
    "foreign_config",
    [
        pytest.param(None, id="none"),
        pytest.param(MagicMock(), id="magicmock"),
        pytest.param(
            SimpleNamespace(memory=SimpleNamespace(shutdown_write_grace_s=1.0)),
            id="namespace",
        ),
    ],
)
async def test_stop_runtime_fast_teardown_with_a_foreign_config_keeps_production_timing(
    foreign_config: Any,
) -> None:
    runtime = _FakeRuntime(foreign_config)

    await stop_runtime(runtime, fast_teardown=True)

    assert runtime.calls == ["stop"]
    assert runtime.config_at_stop is foreign_config


def test_fast_teardown_overrides_are_exactly_the_two_graces_and_read_only() -> None:
    assert dict(FAST_TEARDOWN_OVERRIDES) == {
        "shutdown_write_grace_s": 0.0,
        "shutdown_dispatch_grace_s": 0.0,
    }
    assert set(FAST_TEARDOWN_OVERRIDES) <= set(MemoryConfig.model_fields)
    with pytest.raises(TypeError):
        FAST_TEARDOWN_OVERRIDES["shutdown_write_grace_s"] = 1.0  # type: ignore[index]


def test_make_runtime_builds_an_unstarted_runtime_with_the_given_collaborators(
    tmp_path: Path,
) -> None:
    llm = MockLLMClient()
    config = SystemConfig()

    runtime = make_runtime(tmp_path, llm=llm, config=config)

    assert runtime.llm_client is llm
    assert runtime.config is config
    assert runtime.data_dir == tmp_path / "data"


def test_make_runtime_defaults_to_a_mock_llm_client(tmp_path: Path) -> None:
    runtime = make_runtime(tmp_path)

    assert isinstance(runtime.llm_client, MockLLMClient)
    assert isinstance(runtime.config, SystemConfig)


@pytest.fixture
def lifecycle_runtime(monkeypatch: pytest.MonkeyPatch) -> _FakeRuntime:
    runtime = _FakeRuntime(SystemConfig())
    monkeypatch.setattr(
        runtime_factory, "make_runtime", lambda tmp_path, **kwargs: runtime,
    )
    return runtime


async def test_started_runtime_starts_before_the_body_and_stops_after_it(
    tmp_path: Path, lifecycle_runtime: _FakeRuntime,
) -> None:
    async with started_runtime(tmp_path) as runtime:
        assert runtime is lifecycle_runtime
        assert lifecycle_runtime.calls == ["start"]

    assert lifecycle_runtime.calls == ["start", "stop"]
    assert lifecycle_runtime.config_at_stop is lifecycle_runtime.config


async def test_started_runtime_stops_even_when_the_body_raises(
    tmp_path: Path, lifecycle_runtime: _FakeRuntime,
) -> None:
    with pytest.raises(RuntimeError, match="body failed"):
        async with started_runtime(tmp_path):
            raise RuntimeError("body failed")

    assert lifecycle_runtime.calls == ["start", "stop"]


async def test_started_runtime_does_not_stop_a_runtime_that_failed_to_start(
    tmp_path: Path, lifecycle_runtime: _FakeRuntime,
) -> None:
    async def _failing_start() -> None:
        lifecycle_runtime.calls.append("start")
        raise RuntimeError("boot failed")

    lifecycle_runtime.start = _failing_start  # type: ignore[method-assign]

    with pytest.raises(RuntimeError, match="boot failed"):
        async with started_runtime(tmp_path):
            pytest.fail("the body must not run when start() raised")

    assert lifecycle_runtime.calls == ["start"]


async def test_started_runtime_passes_fast_teardown_to_the_teardown_stop(
    tmp_path: Path, lifecycle_runtime: _FakeRuntime,
) -> None:
    original = lifecycle_runtime.config

    async with started_runtime(tmp_path, fast_teardown=True):
        assert lifecycle_runtime.config is original

    assert lifecycle_runtime.config_at_stop is not original
    assert lifecycle_runtime.config_at_stop.memory.shutdown_write_grace_s == 0.0
    assert original.memory.shutdown_write_grace_s == 1.0


# ---------------------------------------------------------------------------
# (f) Opt-in guards: who asks for fast teardown, who receives it, and where
#
# FAST_TEARDOWN_OPT_IN_FILES pins the call sites: files with a ``fast_teardown``
# keyword that is not False. That is not the reach: any test module may define
# a fast fixture, and every module that defines one or imports one gets fast
# teardown with no keyword of its own. FAST_TEARDOWN_EFFECTIVE_MODULES pins
# those recipients, so a new one fails here until someone has checked that none
# of its test bodies observe what stop() leaves behind. The final-action guard
# pins WHERE a request may sit: only on the last action of a fixture or test,
# so no assertion can follow a fast stop.
# ---------------------------------------------------------------------------

_FACTORY_FILE = "tests/fixtures/runtime_factory.py"
_FIXTURE_SOURCE_DIR = "tests/fixtures/"
_SHARED_FIXTURE_FILE = "tests/fixtures/experience_shell.py"
_SHARED_FIXTURE_NAME = "experience_shell"
_GUARD_FILE = Path(__file__).resolve().relative_to(_REPO_ROOT).as_posix()


def _is_fast_teardown_opt_in(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.keyword)
        and node.arg == "fast_teardown"
        and not (isinstance(node.value, ast.Constant) and node.value.value is False)
    )


def _files_opting_in_to_fast_teardown() -> set[str]:
    found: set[str] = set()
    for path in sorted((_REPO_ROOT / "tests").rglob("*.py")):
        relative = path.relative_to(_REPO_ROOT).as_posix()
        if relative == _FACTORY_FILE:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if "fast_teardown" not in text:
            continue
        try:
            tree = ast.parse(text, filename=relative)
        except SyntaxError:
            found.add(relative)  # cannot prove it never opts in
            continue
        if any(_is_fast_teardown_opt_in(node) for node in ast.walk(tree)):
            found.add(relative)
    return found


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param("f(fast_teardown=True)", True, id="constant-true"),
        pytest.param("f(fast_teardown=flag)", True, id="variable"),
        pytest.param("f(fast_teardown=False)", False, id="constant-false"),
        pytest.param("f(other=True)", False, id="other-keyword"),
        pytest.param("f()", False, id="no-keyword"),
    ],
)
def test_opt_in_detector_flags_only_a_keyword_not_bound_to_false(
    source: str, expected: bool,
) -> None:
    tree = ast.parse(source)

    assert any(_is_fast_teardown_opt_in(node) for node in ast.walk(tree)) is expected


def test_fast_teardown_opt_in_files_are_exactly_the_allowlist() -> None:
    assert FAST_TEARDOWN_OPT_IN_FILES == frozenset({
        "tests/fixtures/experience_shell.py",
        "tests/test_experience_panels.py",
        "tests/test_ad1270f_shutdown_grace.py",
        "tests/test_runtime.py",
        "tests/test_consensus_integration.py",
        "tests/test_distribution.py",
        "tests/test_dag_proposal.py",
        "tests/test_system_qa.py",
        "tests/test_escalation.py",
        "tests/test_self_mod.py",
        "tests/test_emergent_detector.py",
        "tests/test_semantic_knowledge.py",
        "tests/test_scaling.py",
    })
    assert all((_REPO_ROOT / name).is_file() for name in FAST_TEARDOWN_OPT_IN_FILES)
    assert _files_opting_in_to_fast_teardown() == set(FAST_TEARDOWN_OPT_IN_FILES)


def _is_pytest_fixture(node: ast.AST) -> bool:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
        if name == "fixture":
            return True
    return False


def _asks_for_fast_teardown(node: ast.AST) -> bool:
    return any(_is_fast_teardown_opt_in(child) for child in ast.walk(node))


def _fast_teardown_fixtures_defined_in(tree: ast.AST) -> set[str]:
    """Fixtures in ``tree`` whose own body asks for fast teardown."""
    return {
        node.name
        for node in ast.walk(tree)
        if _is_pytest_fixture(node) and _asks_for_fast_teardown(node)
    }


def _fast_teardown_fixture_names(tree: ast.AST) -> set[str]:
    """Module-level fixtures of ``tree`` that give fast teardown.

    Directly (their own body asks for it) or by requesting a fixture that does,
    as ``shell`` requests ``runtime``. Only a module-level name can be imported
    by another module, so a class fixture is a recipient but never a source.
    """
    fixtures = {
        node.name: node
        for node in getattr(tree, "body", [])
        if _is_pytest_fixture(node)
    }
    fast = {name for name, node in fixtures.items() if _asks_for_fast_teardown(node)}
    grew = True
    while grew:
        grew = False
        for name, node in fixtures.items():
            requested = {
                arg.arg
                for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
            }
            if name not in fast and requested & fast:
                fast.add(name)
                grew = True
    return fast


def _imports_fast_teardown_fixture(
    tree: ast.AST, sources: Mapping[str, set[str]],
) -> bool:
    """True when ``tree`` brings a fast-teardown fixture in from a fixture source.

    ``sources`` maps a source module's name, its last dotted segment, to the names
    of its fast-teardown fixtures. A star import, a module import and a
    ``pytest_plugins`` registration bring in every fixture, so they count too.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names = {alias.name for alias in node.names}
            module = (node.module or "").rsplit(".", 1)[-1]
            if module in sources and ("*" in names or names & sources[module]):
                return True
            if names & sources.keys():
                return True
        elif isinstance(node, ast.Import):
            if any(alias.name.rsplit(".", 1)[-1] in sources for alias in node.names):
                return True
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(
                isinstance(target, ast.Name) and target.id == "pytest_plugins"
                for target in targets
            ) and any(
                isinstance(child, ast.Constant)
                and isinstance(child.value, str)
                and child.value.rsplit(".", 1)[-1] in sources
                for child in ast.walk(node)
            ):
                return True
    return False


def _test_module_texts(root: Path) -> Iterator[tuple[str, str]]:
    """Repo-relative path and text of every tests/**/*.py except the factory."""
    for path in sorted((root / "tests").rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        if relative != _FACTORY_FILE:
            yield relative, path.read_text(encoding="utf-8", errors="replace")


def _fast_teardown_sources(root: Path = _REPO_ROOT) -> dict[str, set[str]]:
    """Module name -> its fast-teardown fixture names, for every module that has one.

    Any tests/**/*.py but the factory can be a source: a fast fixture defined in
    a test module and imported elsewhere spreads fast teardown as surely as one
    in tests/fixtures/.
    """
    sources: dict[str, set[str]] = {}
    for relative, text in _test_module_texts(root):
        if "fast_teardown" not in text:
            continue
        try:
            tree = ast.parse(text, filename=relative)
        except SyntaxError:
            continue  # the receiving scan reports an unparsable module
        names = _fast_teardown_fixture_names(tree)
        if names:
            sources.setdefault(Path(relative).stem, set()).update(names)
    return sources


def _modules_receiving_fast_teardown(root: Path = _REPO_ROOT) -> set[str]:
    """Test modules that define a fast-teardown fixture or import one from a source.

    The factory is the mechanism, and a fixture-only module under tests/fixtures/
    is a source: both are pinned by FAST_TEARDOWN_OPT_IN_FILES instead. Such a
    module is still a recipient if it imports a fast fixture from another source.
    """
    sources = _fast_teardown_sources(root)
    found: set[str] = set()
    for relative, text in _test_module_texts(root):
        if "fast_teardown" not in text and not any(name in text for name in sources):
            continue
        try:
            tree = ast.parse(text, filename=relative)
        except SyntaxError:
            found.add(relative)  # cannot prove it does not receive fast teardown
            continue
        defines = bool(_fast_teardown_fixtures_defined_in(tree)) and not relative.startswith(
            _FIXTURE_SOURCE_DIR,
        )
        if defines or _imports_fast_teardown_fixture(tree, sources):
            found.add(relative)
    return found


_FAST_FIXTURE_SOURCE = (
    "import pytest\n"
    "@pytest.fixture\n"
    "async def {name}(tmp_path):\n"
    "    async with started_runtime(tmp_path, fast_teardown={flag}) as rt:\n"
    "        yield rt\n"
)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(_FAST_FIXTURE_SOURCE.format(name="f", flag="True"), {"f"}, id="true"),
        pytest.param(_FAST_FIXTURE_SOURCE.format(name="f", flag="flag"), {"f"}, id="variable"),
        pytest.param(_FAST_FIXTURE_SOURCE.format(name="f", flag="False"), set(), id="false"),
        pytest.param(
            "async def f(tmp_path):\n    started_runtime(tmp_path, fast_teardown=True)\n",
            set(),
            id="not-a-fixture",
        ),
        pytest.param(
            "class C:\n"
            "    @pytest.fixture\n"
            "    def f(self):\n"
            "        return started_runtime(fast_teardown=True)\n",
            {"f"},
            id="method-fixture",
        ),
        pytest.param(
            "@pytest_asyncio.fixture(scope='function')\n"
            "async def f():\n"
            "    started_runtime(fast_teardown=True)\n",
            {"f"},
            id="called-decorator",
        ),
    ],
)
def test_definer_detector_flags_only_a_fixture_that_asks_for_fast_teardown(
    source: str, expected: set[str],
) -> None:
    assert _fast_teardown_fixtures_defined_in(ast.parse(source)) == expected


_FAST_FIXTURE_SOURCES = {
    _SHARED_FIXTURE_NAME: {"runtime", "shell"},
    "test_runtime": {"runtime"},
}


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        pytest.param(
            "from tests.fixtures.experience_shell import runtime", True, id="runtime",
        ),
        pytest.param(
            "from tests.fixtures.experience_shell import console, shell, get_output",
            True,
            id="shell",
        ),
        pytest.param(
            "from tests.fixtures.experience_shell import console, get_output",
            False,
            id="non-fast-names-only",
        ),
        pytest.param("from tests.fixtures.experience_shell import *", True, id="star"),
        pytest.param("from tests.fixtures import experience_shell", True, id="package"),
        pytest.param("import tests.fixtures.experience_shell", True, id="module"),
        pytest.param("from .fixtures.experience_shell import runtime", True, id="relative"),
        pytest.param(
            "pytest_plugins = ['tests.fixtures.experience_shell']", True, id="plugins",
        ),
        pytest.param(
            "MODULE = 'tests.fixtures.experience_shell'", False, id="bare-string",
        ),
        pytest.param("from tests.fixtures.other import runtime", False, id="other-module"),
        pytest.param(
            "from tests.test_runtime import runtime", True, id="test-module-fixture",
        ),
        pytest.param(
            "from tests.test_runtime import TestRuntimeSubstrate",
            False,
            id="test-module-non-fixture-name",
        ),
        pytest.param("from tests.test_runtime import *", True, id="test-module-star"),
        pytest.param("from tests import test_runtime", True, id="test-module-package"),
        pytest.param("import tests.test_runtime as runtime_tests", True, id="test-module-alias"),
        pytest.param(
            "pytest_plugins = ('tests.test_runtime',)", True, id="test-module-plugins",
        ),
        pytest.param(
            "from tests.test_other import runtime", False, id="module-with-no-fast-fixture",
        ),
        pytest.param(
            "from tests.test_runtime_extra import runtime",
            False,
            id="module-name-must-match-exactly",
        ),
    ],
)
def test_importer_detector_flags_only_a_fast_teardown_fixture_import(
    source: str, expected: bool,
) -> None:
    tree = ast.parse(source)

    assert _imports_fast_teardown_fixture(tree, _FAST_FIXTURE_SOURCES) is expected


def test_shared_fixture_names_follow_a_request_for_a_fast_fixture() -> None:
    tree = ast.parse(
        _FAST_FIXTURE_SOURCE.format(name="base", flag="True")
        + "@pytest.fixture\ndef dependent(base):\n    pass\n"
        + "@pytest.fixture\ndef unrelated():\n    pass\n"
    )

    assert _fast_teardown_fixture_names(tree) == {"base", "dependent"}


def test_a_class_fixture_is_never_a_source_because_no_module_can_import_it() -> None:
    tree = ast.parse(
        "class C:\n"
        "    @pytest.fixture\n"
        "    async def f(self, tmp_path):\n"
        "        async with started_runtime(tmp_path, fast_teardown=True) as rt:\n"
        "            yield rt\n"
    )

    assert _fast_teardown_fixtures_defined_in(tree) == {"f"}
    assert _fast_teardown_fixture_names(tree) == set()


def test_shared_fixture_module_gives_fast_teardown_through_runtime_and_shell_only() -> None:
    tree = ast.parse((_REPO_ROOT / _SHARED_FIXTURE_FILE).read_text(encoding="utf-8"))

    assert _fast_teardown_fixture_names(tree) == {"runtime", "shell"}


def test_fast_teardown_effective_modules_are_exactly_the_pinned_set() -> None:
    assert FAST_TEARDOWN_EFFECTIVE_MODULES == frozenset({
        "tests/test_experience.py",
        "tests/test_experience_commands.py",
        "tests/test_experience_nl_memory.py",
        "tests/test_experience_panels.py",
        "tests/test_runtime.py",
        "tests/test_consensus_integration.py",
        "tests/test_distribution.py",
        "tests/test_dag_proposal.py",
        "tests/test_escalation.py",
    })
    assert all((_REPO_ROOT / name).is_file() for name in FAST_TEARDOWN_EFFECTIVE_MODULES)

    found = _modules_receiving_fast_teardown()

    assert found == set(FAST_TEARDOWN_EFFECTIVE_MODULES), (
        "The test modules that receive fast teardown through a fixture "
        f"changed. New: {sorted(found - FAST_TEARDOWN_EFFECTIVE_MODULES)}; gone: "
        f"{sorted(FAST_TEARDOWN_EFFECTIVE_MODULES - found)}. Check that no test "
        "body in a new module observes what stop() leaves behind, then update "
        "FAST_TEARDOWN_EFFECTIVE_MODULES in tests/fixtures/runtime_factory.py "
        "and this test."
    )


def test_fast_teardown_sources_in_the_tree_are_the_modules_with_a_module_level_fast_fixture() -> None:
    assert _fast_teardown_sources() == {
        "experience_shell": {"runtime", "shell"},
        "test_runtime": {"runtime"},
        "test_consensus_integration": {"runtime"},
        "test_distribution": {"runtime", "runtime_no_utility", "owned_steps_create_app"},
    }


def _write_tests(root: Path, files: dict[str, str]) -> None:
    for relative, text in files.items():
        path = root / "tests" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


_CLASS_FAST_FIXTURE_SOURCE = (
    "class C:\n"
    "    @pytest.fixture\n"
    "    async def f(self, tmp_path):\n"
    "        async with started_runtime(tmp_path, fast_teardown=True) as rt:\n"
    "            yield rt\n"
)
_PLAIN_FIXTURE_SOURCE = "import pytest\n\n@pytest.fixture\ndef runtime():\n    pass\n"


def test_any_test_module_can_be_a_fast_fixture_source(tmp_path: Path) -> None:
    _write_tests(tmp_path, {
        "test_defines.py": _FAST_FIXTURE_SOURCE.format(name="runtime", flag="True"),
        "fixtures/shared.py": _FAST_FIXTURE_SOURCE.format(name="shell", flag="True"),
        "fixtures/runtime_factory.py": _FAST_FIXTURE_SOURCE.format(name="runtime", flag="True"),
        "test_class_only.py": _CLASS_FAST_FIXTURE_SOURCE,
        "test_plain.py": _PLAIN_FIXTURE_SOURCE,
    })

    assert _fast_teardown_sources(tmp_path) == {
        "test_defines": {"runtime"},
        "shared": {"shell"},
    }


def test_receiving_scan_flags_a_module_that_defines_or_imports_a_fast_fixture(
    tmp_path: Path,
) -> None:
    _write_tests(tmp_path, {
        "test_defines.py": _FAST_FIXTURE_SOURCE.format(name="runtime", flag="True"),
        "test_class_fixture.py": _CLASS_FAST_FIXTURE_SOURCE,
        "test_imports_from_a_test_module.py": "from tests.test_defines import runtime\n",
        "fixtures/shared.py": _FAST_FIXTURE_SOURCE.format(name="shell", flag="True"),
        "test_imports_from_fixtures.py": "from tests.fixtures.shared import shell\n",
        "test_unparsable.py": "async def f(:\n    fast_teardown = True\n",
        "test_imports_a_non_fixture.py": "from tests.test_defines import helper\n",
        "test_imports_a_plain_fixture.py": "from tests.test_plain import runtime\n",
        "test_plain.py": _PLAIN_FIXTURE_SOURCE,
    })

    assert _modules_receiving_fast_teardown(tmp_path) == {
        "tests/test_defines.py",
        "tests/test_class_fixture.py",
        "tests/test_imports_from_a_test_module.py",
        "tests/test_imports_from_fixtures.py",
        "tests/test_unparsable.py",
    }


# ---------------------------------------------------------------------------
# (g) Final-action guard: a fast stop is the last thing a fixture or test does
#
# Fast teardown only skips the two fixed waits of a runtime's FINAL stop. A
# request is accepted in exactly these places, so nothing can run after it that
# could observe what stop() leaves behind:
#   fixture: the context of the async with that is its last statement and holds
#            the yield; or an awaited call that is its last statement after the
#            yield; or the last statement of the finally of its last try, whose
#            body holds the yield.
#   test_*:  the context of the async with that is its last statement; or an
#            awaited call that is its last statement; or the last statement of
#            the finally of its last try.
# Anything else (a helper, a stop before the yield, a statement after the stop)
# fails, naming file:line and function.
# ---------------------------------------------------------------------------

_FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
_DEFINED_FUNCTIONS = (ast.FunctionDef, ast.AsyncFunctionDef)


def _parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    return {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }


def _enclosing_function(
    node: ast.AST, parents: Mapping[ast.AST, ast.AST],
) -> ast.AST | None:
    current = parents.get(node)
    while current is not None and not isinstance(current, _FUNCTION_NODES):
        current = parents.get(current)
    return current


def _yields(statements: list[ast.stmt]) -> bool:
    """True when ``statements`` yield, not counting a nested function's own yield."""
    stack: list[ast.AST] = list(statements)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.Yield, ast.YieldFrom)):
            return True
        if not isinstance(node, _FUNCTION_NODES):
            stack.extend(ast.iter_child_nodes(node))
    return False


def _is_awaited(statement: ast.stmt, call: ast.Call) -> bool:
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Await)
        and statement.value.value is call
    )


def _is_async_context_of(statement: ast.stmt, call: ast.Call) -> bool:
    return isinstance(statement, ast.AsyncWith) and any(
        item.context_expr is call for item in statement.items
    )


def _is_final_in_finally(statement: ast.stmt, call: ast.Call) -> bool:
    return (
        isinstance(statement, ast.Try)
        and bool(statement.finalbody)
        and _is_awaited(statement.finalbody[-1], call)
    )


def _is_final_action_of_a_fixture(
    fixture: ast.FunctionDef | ast.AsyncFunctionDef, call: ast.Call,
) -> bool:
    body = fixture.body
    last = body[-1]
    if _is_async_context_of(last, call):
        return _yields(last.body)
    if _is_awaited(last, call):
        return _yields(body[:-1])
    if _is_final_in_finally(last, call):
        return _yields(last.body)
    return False


def _is_final_action_of_a_test(
    test: ast.FunctionDef | ast.AsyncFunctionDef, call: ast.Call,
) -> bool:
    last = test.body[-1]
    return (
        _is_async_context_of(last, call)
        or _is_awaited(last, call)
        or _is_final_in_finally(last, call)
    )


def _fast_teardown_final_action_report(
    source: str, filename: str,
) -> tuple[int, list[str]]:
    """Count the fast-teardown requests in ``source`` and name those not a final action."""
    tree = ast.parse(source, filename=filename)
    parents = _parent_map(tree)
    requests = sorted(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and any(_is_fast_teardown_opt_in(keyword) for keyword in node.keywords)
        ),
        key=lambda node: (node.lineno, node.col_offset),
    )
    problems: list[str] = []
    for call in requests:
        owner = _enclosing_function(call, parents)
        if isinstance(owner, _DEFINED_FUNCTIONS) and _is_pytest_fixture(owner):
            final = _is_final_action_of_a_fixture(owner, call)
        elif isinstance(owner, _DEFINED_FUNCTIONS) and owner.name.startswith("test_"):
            final = _is_final_action_of_a_test(owner, call)
        else:
            final = False
        if not final:
            if isinstance(owner, _DEFINED_FUNCTIONS):
                where = owner.name
            else:
                where = "<lambda>" if owner is not None else "<module>"
            problems.append(f"{filename}:{call.lineno} in {where}")
    return len(requests), problems


def _src(text: str) -> str:
    return inspect.cleandoc(text) + "\n"


_FINAL_ACTION_ACCEPTED = [
    pytest.param(_src("""
        @pytest.fixture
        async def runtime(tmp_path):
            async with started_runtime(tmp_path, fast_teardown=True) as rt:
                yield rt
    """), id="fixture-async-with-around-the-yield"),
    pytest.param(_src("""
        @pytest.fixture
        async def env(self, tmp_path):
            llm = MockLLMClient()
            async with started_runtime(tmp_path, llm=llm, fast_teardown=True) as rt:
                console = object()
                yield rt, console
    """), id="fixture-async-with-after-setup-before-the-yield"),
    pytest.param(_src("""
        @pytest_asyncio.fixture(scope="function")
        async def runtime(tmp_path):
            async with started_runtime(tmp_path, fast_teardown=True) as rt:
                yield rt
    """), id="fixture-called-decorator"),
    pytest.param(_src("""
        @pytest.fixture
        async def runtime(tmp_path):
            rt = make_runtime(tmp_path)
            await rt.start()
            yield rt
            await stop_runtime(rt, fast_teardown=True)
    """), id="fixture-stop-as-the-last-code-after-the-yield"),
    pytest.param(_src("""
        @pytest.fixture
        async def runtime(tmp_path):
            rt = make_runtime(tmp_path)
            await rt.start()
            try:
                yield rt
            finally:
                await stop_runtime(rt, fast_teardown=True)
    """), id="fixture-finally-around-the-yield"),
    pytest.param(_src("""
        async def test_x(tmp_path):
            async with started_runtime(tmp_path, fast_teardown=True) as rt:
                assert rt.pools
    """), id="test-async-with-as-the-last-statement"),
    pytest.param(_src("""
        async def test_x(tmp_path):
            rt = make_runtime(tmp_path)
            await rt.start()
            assert rt.pools
            await stop_runtime(rt, fast_teardown=True)
    """), id="test-final-await"),
    pytest.param(_src("""
        async def test_x(runtime):
            await runtime.start()
            try:
                assert runtime.pools
            finally:
                await stop_runtime(runtime, fast_teardown=True)
    """), id="test-finally-of-the-last-try"),
    pytest.param(_src("""
        class TestX:
            async def test_x(self, tmp_path):
                rt = make_runtime(tmp_path)
                await rt.start()
                await stop_runtime(rt, fast_teardown=True)
    """), id="test-method-final-await"),
    pytest.param(_src("""
        async def test_x(tmp_path, flag):
            rt = make_runtime(tmp_path)
            await rt.start()
            await stop_runtime(rt, fast_teardown=flag)
    """), id="keyword-bound-to-a-variable"),
]

_FINAL_ACTION_REJECTED = [
    pytest.param(_src("""
        async def test_x(tmp_path):
            rt = make_runtime(tmp_path)
            await rt.start()
            await stop_runtime(rt, fast_teardown=True)
            assert rt.registry.count == 0
    """), "4 in test_x", id="assertion-after-the-stop"),
    pytest.param(_src("""
        async def test_x(tmp_path):
            async with started_runtime(tmp_path, fast_teardown=True) as rt:
                pass
            assert tmp_path.exists()
    """), "2 in test_x", id="statement-after-the-with"),
    pytest.param(_src("""
        async def test_x(runtime):
            await runtime.start()
            try:
                pass
            finally:
                await stop_runtime(runtime, fast_teardown=True)
                assert runtime.config
    """), "6 in test_x", id="statement-after-the-stop-in-finally"),
    pytest.param(_src("""
        async def _stop(rt):
            await stop_runtime(rt, fast_teardown=True)


        async def test_x(tmp_path):
            rt = make_runtime(tmp_path)
            await rt.start()
            await _stop(rt)
    """), "2 in _stop", id="call-in-a-helper"),
    pytest.param(_src("""
        async def test_x(tmp_path):
            rt = make_runtime(tmp_path)

            async def inner():
                await stop_runtime(rt, fast_teardown=True)

            await inner()
    """), "5 in inner", id="call-in-a-nested-helper"),
    pytest.param(_src("""
        @pytest.fixture
        async def runtime(tmp_path):
            rt = make_runtime(tmp_path)
            await stop_runtime(rt, fast_teardown=True)
            yield rt
    """), "4 in runtime", id="fixture-stop-before-its-yield"),
    pytest.param(_src("""
        @pytest.fixture
        async def runtime(tmp_path):
            async with started_runtime(tmp_path, fast_teardown=True) as rt:
                yield rt
            assert tmp_path.exists()
    """), "3 in runtime", id="fixture-statement-after-the-with"),
    pytest.param(_src("""
        @pytest.fixture
        async def runtime(tmp_path):
            async with started_runtime(tmp_path, fast_teardown=True) as rt:
                return rt
    """), "3 in runtime", id="fixture-with-that-never-yields"),
    pytest.param(_src("""
        @pytest.fixture
        async def runtime(tmp_path):
            rt = make_runtime(tmp_path)
            yield rt
            await stop_runtime(rt, fast_teardown=True)
            assert tmp_path.exists()
    """), "5 in runtime", id="fixture-statement-after-the-stop"),
    pytest.param(_src("""
        async def test_x(runtime):
            await runtime.start()
            try:
                pass
            finally:
                await stop_runtime(runtime, fast_teardown=True)
            assert runtime
    """), "6 in test_x", id="finally-of-a-try-that-is-not-last"),
    pytest.param(_src("""
        async def test_x(runtime):
            try:
                await stop_runtime(runtime, fast_teardown=True)
            finally:
                pass
    """), "3 in test_x", id="stop-in-the-try-body"),
    pytest.param(_src("""
        async def test_x(runtime):
            try:
                pass
            except Exception:
                await stop_runtime(runtime, fast_teardown=True)
    """), "5 in test_x", id="stop-in-an-except-handler"),
    pytest.param(_src("""
        async def test_x(runtime, flag):
            if flag:
                await stop_runtime(runtime, fast_teardown=True)
    """), "3 in test_x", id="stop-in-a-conditional"),
    pytest.param(_src("""
        async def test_x(runtime):
            await asyncio.gather(stop_runtime(runtime, fast_teardown=True))
    """), "2 in test_x", id="call-wrapped-in-another-await"),
    pytest.param(_src("""
        async def test_x(tmp_path):
            with started_runtime(tmp_path, fast_teardown=True) as rt:
                pass
    """), "2 in test_x", id="sync-with-is-not-an-async-context"),
    pytest.param(_src("""
        rt = stop_runtime(make_runtime(), fast_teardown=True)
    """), "1 in <module>", id="module-level-call"),
    pytest.param(_src("""
        stop = lambda rt: stop_runtime(rt, fast_teardown=True)
    """), "1 in <lambda>", id="call-in-a-lambda"),
]


@pytest.mark.parametrize("source", _FINAL_ACTION_ACCEPTED)
def test_final_action_detector_accepts_a_request_that_is_the_last_action(
    source: str,
) -> None:
    examined, problems = _fast_teardown_final_action_report(source, "f.py")

    assert examined == 1
    assert problems == []


@pytest.mark.parametrize(("source", "where"), _FINAL_ACTION_REJECTED)
def test_final_action_detector_rejects_a_request_that_is_not_the_last_action(
    source: str, where: str,
) -> None:
    examined, problems = _fast_teardown_final_action_report(source, "f.py")

    assert examined == 1
    assert problems == [f"f.py:{where}"]


def test_final_action_detector_ignores_a_keyword_bound_to_false() -> None:
    source = _src("""
        async def _helper(rt):
            await stop_runtime(rt, fast_teardown=False)
    """)

    assert _fast_teardown_final_action_report(source, "f.py") == (0, [])


def test_every_fast_teardown_request_is_the_final_action_of_its_fixture_or_test() -> None:
    problems: list[str] = []
    for relative in sorted(FAST_TEARDOWN_OPT_IN_FILES - {_GUARD_FILE}):
        text = (_REPO_ROOT / relative).read_text(encoding="utf-8")
        examined, found = _fast_teardown_final_action_report(text, relative)
        assert examined >= 1, f"{relative} is opted in but no request was examined"
        problems.extend(found)

    assert not problems, (
        "A fast-teardown request must be the last action of its fixture or test, "
        "so nothing can observe what stop() leaves behind. Not final: "
        + "; ".join(problems)
    )
