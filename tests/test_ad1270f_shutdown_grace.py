"""AD-1270f P1.2: bounded shutdown graces and the teardown-scoped fast stop.

Production ``stop()`` waits 1 s (AD-435) and 2 s (BF-296 Phase A) before it
quiesces anything. Those waits are now two bounded ``MemoryConfig`` fields whose
defaults are today's waits and also their maximums. The shared runtime factory
(``tests/fixtures/runtime_factory.py``) can zero both for ITS OWN TEARDOWN stop
only, and only in the files listed in ``FAST_TEARDOWN_OPT_IN_FILES``.

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
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

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
# (d) Real boot: the fast teardown skips both waits and persists the same status
# ---------------------------------------------------------------------------

async def test_fast_teardown_zeroes_both_waits_and_persists_the_production_status(
    tmp_path: Path,
) -> None:
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
    assert fast_status["status"] == production_status["status"]
    assert fast_status["consolidation_result"] == production_status["consolidation_result"]


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
# (f) Opt-in guard
# ---------------------------------------------------------------------------

_FACTORY_FILE = "tests/fixtures/runtime_factory.py"


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
    })
    assert all((_REPO_ROOT / name).is_file() for name in FAST_TEARDOWN_OPT_IN_FILES)
    assert _files_opting_in_to_fast_teardown() == set(FAST_TEARDOWN_OPT_IN_FILES)
