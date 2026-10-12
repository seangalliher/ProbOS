"""AD-1240: canonical admission, pinned workspace storage and legacy-route reservation.

The producer-side capture, slot and scope tests arrive with the offload core
(a later milestone). The store-level tests and the legacy-route reservation
tests (the real FastAPI routes, the real ``WorkspaceManager`` resolver and
inspection walks, a real publication) all cross the real filesystem.
"""

from __future__ import annotations

import ast
import asyncio
import errno
import hashlib
import inspect
import json
import os
import stat
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

import probos.execution.workspace as workspace_module
from probos.execution.workspace import WorkspaceManager
from probos.execution.workspace_result_store import (
    DirectoryIdentities,
    RetryPolicy,
    RetryRunner,
    WorkspaceResultStore,
)
from probos.execution.workspace_results import (
    RESULT_DIRECTORY,
    RESULT_RETENTION_SECONDS,
    CanonicalCapture,
    UnavailableWorkspaceResults,
    WorkspaceReapResult,
    WorkspaceResultError,
    WorkspaceResults,
    generation_expiry,
    generation_name,
    generation_start,
    is_workspace_result_path,
    is_workspace_results,
    resolve_workspace_results,
)
from probos.security.file_access import FileAccessDenied, is_reparse_point, pin_directory, read_verified_file
from tests.test_ad1021c_workspace_suggestions import _client
from tests.test_ad1240_tool_result_delivery import (  # noqa: F401  (the fixture is autouse here)
    _assert_provenance,
    _candidate_provenance,
)

# The hour every fixture lives in: 2026-10-11T07:00Z, with the clock mid-hour.
GEN = "20261011T07Z"
GEN_START = generation_start(GEN)
T0 = GEN_START + 1800.0


def _capture(text: str) -> CanonicalCapture:
    """A valid str-root capture, built directly.

    The producer-side ``canonical_capture`` lands with the offload core; this
    builds the identical record so the store is exercised, not a fake of it.
    """
    encoded = text.encode("utf-8")
    outline = json.dumps({
        "representation": "text", "root_type": "str", "chars": len(text),
        "utf8_bytes": len(encoded), "lines": len(text.splitlines()),
        "shape": {"slots": 1, "dicts": 0, "lists": 0, "tuples": 0, "scalars": 1, "revisits": 0},
        "omitted": ["keys", "values"],
    }, ensure_ascii=True, separators=(",", ":"))
    return CanonicalCapture(
        text=text, representation="text", source_chars=len(text), utf8_bytes=len(encoded),
        sha256=hashlib.sha256(encoded).hexdigest(), outline=outline,
    )


def _agent(agent_id: str = "agent-a", callsign: str = "Same owner") -> SimpleNamespace:
    return SimpleNamespace(id=agent_id, callsign=callsign)


@dataclass
class StoreHarness:
    """A store over a real temp root with an injected clock and recording sleep."""

    store: WorkspaceResultStore
    clock: list[float]
    tasks: list[asyncio.Task[None]]
    sleeps: list[float]


def make_store(
    root: Path, *, clock: float = T0, register: bool = True, retry: RetryPolicy | None = None,
) -> StoreHarness:
    box = [clock]
    tasks: list[asyncio.Task[None]] = []
    sleeps: list[float] = []
    store = WorkspaceResultStore(
        WorkspaceManager(root), clock=lambda: box[0],
        background_register=tasks.append if register else None,
        sleep=sleeps.append, retry=retry if retry is not None else RetryPolicy(),
    )
    return StoreHarness(store, box, tasks, sleeps)


def generation_of(payload_path: str) -> str:
    """The ``<GEN>`` segment of ``.../.tool-results/<GEN>/<digest>/<artifact>/payload.jsonl``."""
    return Path(payload_path).parents[2].name


def transient_error() -> OSError:
    """The platform's own brief sharing failure, as the retry taxonomy sees it."""
    if sys.platform == "win32":
        error = PermissionError(errno.EACCES, "fixture sharing violation")
        error.winerror = 32
        return error
    return OSError(errno.EBUSY, "fixture busy")


def _make_junction(link: Path, target: Path) -> None:
    assert link.is_absolute() and target.is_absolute() and target.is_dir()
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr


def _make_symlink(link: Path, target: Path) -> None:
    assert link.is_absolute() and target.is_absolute() and target.is_dir()
    link.symlink_to(target, target_is_directory=True)


def _directory_alias(link: Path, target: Path) -> None:
    """A symlink where permitted, else a junction (Windows without symlink rights)."""
    try:
        _make_symlink(link, target)
    except OSError:
        if os.name != "nt":
            raise
        _make_junction(link, target)
    assert link.resolve() == target.resolve() and link.resolve() != link


def _remove_alias(link: Path) -> None:
    link.unlink() if link.is_symlink() else link.rmdir()


# ---- the reserved namespace, as the legacy routes and ordinary inspection see it ----

PRIVATE_TEXT = "PRIVATE_RESULT_BYTES"
PRIVATE_BYTES = json.dumps(PRIVATE_TEXT).encode("ascii") + b"\n"
DIGEST = "0" * 64
ARTIFACT_ID = "a" * 32


def _private_artifact(owner_folder: Path) -> Path:
    """An artifact directory in the generation layout under ``owner_folder``'s namespace.

    Laid out by hand with fixed bytes: these tests are about what ordinary
    operations do with the namespace, so they need its path shape and a size
    that would show if it were counted, not a publication. The routes tests that
    need publication use the real store.
    """
    artifact = owner_folder / RESULT_DIRECTORY / GEN / DIGEST / ARTIFACT_ID
    artifact.mkdir(parents=True)
    (artifact / "payload.jsonl").write_bytes(PRIVATE_BYTES)
    (artifact / "outline.json").write_bytes(b"{}")
    (artifact / "manifest.json").write_bytes(b"{}")
    return artifact


@contextmanager
def _count_resolves() -> Iterator[Counter[Path]]:
    """Count every ``Path.resolve`` call, per path, while the block runs."""
    original = Path.resolve
    calls: Counter[Path] = Counter()

    def counted(path: Path, *args: Any, **kwargs: Any) -> Path:
        calls[path] += 1
        return original(path, *args, **kwargs)

    with patch.object(Path, "resolve", counted):
        yield calls


def _route_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, agent: SimpleNamespace,
) -> tuple[Any, Any, Any]:
    """The real FastAPI app over a real ``ExecutionConfig`` rooted at ``tmp_path / "ws"``.

    ``create_app`` imports a large part of ProbOS, so the provenance check runs
    after it: every loaded ``probos`` module must still be this worktree's.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PROBOS_DATA_DIR", str(tmp_path / "data"))
    client, runtime, suggestions = _client(tmp_path, agent=agent, write_enabled=True)
    runtime.data_dir = tmp_path / "data"
    _assert_provenance()
    return client, runtime, suggestions


def test_binding_exact_registered_identity_no_shared_fallback_or_directories(tmp_path: Path) -> None:
    store = make_store(tmp_path / "workspaces").store
    agent = _agent()
    binding = store.bind_agent(agent.id, agent)
    assert store.bind_agent(agent.id, agent) is binding
    other = store.bind_agent("agent-b", _agent("agent-b"))
    assert binding.owner_key == other.owner_key and binding.owner_digest != other.owner_digest
    assert not store.root.exists()
    for agent_id, value in (("", agent), ("wrong", agent), ("agent-a", _agent())):
        with pytest.raises(WorkspaceResultError, match="agent_identity"):
            store.bind_agent(agent_id, value)
    # An identity that sanitizes to the shared folder is never a private owner.
    with pytest.raises(WorkspaceResultError, match="agent_identity_invalid"):
        store.bind_agent("___", SimpleNamespace(id="___", callsign=""))
    assert not store.root.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("empty", [False, True])
@pytest.mark.parametrize("offset,limit", [
    (None, None), (0, 0), (17, 257), (41, 43), (-29, None), (3, -2), (-99, 40), (999999, 100),
])
async def test_workspace_read_arbitrary_unicode_crlf_slice_exact(
    tmp_path: Path, empty: bool, offset: int | None, limit: int | None,
) -> None:
    harness = make_store(tmp_path / "workspaces")
    store = harness.store
    binding = store.bind_agent("agent-a", _agent())
    text = "" if empty else ("long unbroken 😀 café\r\n\\\"\x00" * 800) + "TAIL"
    await store.start()
    try:
        assert not store.root.exists()
        reference = await store.store_tool_result(binding, _capture(text))
        result = await store.read_tool_result_slice(binding, reference.path, offset, limit)
        start = offset or 0
        end = start + limit if limit is not None else len(text)
        assert result.text == text[start:end]
        assert result.reference == reference
        lines = Path(reference.path).read_bytes().splitlines(keepends=True)
        assert all(len(line) <= 512 and line.endswith(b"\n") for line in lines)
        assert b"".join(lines).isascii()
        assert "".join(json.loads(line) for line in lines) == text
        assert {path.name for path in Path(reference.path).parent.iterdir()} == {
            "payload.jsonl", "outline.json", "manifest.json",
        }
        assert generation_of(reference.path) == GEN
        assert harness.tasks == [task for task in harness.tasks if not task.done()]
    finally:
        await store.stop()
    assert all(task.done() for task in harness.tasks)
    assert harness.sleeps == []


@pytest.mark.asyncio
async def test_workspace_binding_and_path_boundaries(tmp_path: Path) -> None:
    harness = make_store(tmp_path / "workspaces")
    store = harness.store
    binding = store.bind_agent("agent-a", _agent())
    foreign = store.bind_agent("agent-b", _agent("agent-b"))
    with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
        await store.store_tool_result(binding, _capture("text"))
    await store.start()
    try:
        reference = await store.store_tool_result(binding, _capture("payload"))
        payload = Path(reference.path)
        namespace, digest, artifact = payload.parents[3], payload.parents[1].name, payload.parent.name
        wrong_layouts = (
            # Pre-generation layout: the namespace holds no generation level.
            namespace / digest / artifact / "payload.jsonl",
            namespace / "not-a-generation" / digest / artifact / "payload.jsonl",
        )
        for owner, path in (
            (foreign, reference.path), (replace(binding), reference.path),
            (binding, str(payload.with_name("manifest.json"))),
            (binding, str(payload.parent / ".." / "payload.jsonl")),
            (binding, ""), (binding, reference.path + ":stream"),
            *((binding, str(layout)) for layout in wrong_layouts),
        ):
            with pytest.raises(WorkspaceResultError):
                await store.read_tool_result_slice(owner, path, None, None)
        # A well-formed path in another hour reaches the filesystem and finds nothing.
        other_hour = namespace / generation_name(GEN_START + 3600.0) / digest / artifact / "payload.jsonl"
        with pytest.raises(WorkspaceResultError, match="workspace_read_failed"):
            await store.read_tool_result_slice(binding, str(other_hour), None, None)
        with pytest.raises(WorkspaceResultError, match="slice_invalid"):
            await store.read_tool_result_slice(binding, reference.path, True, None)
        with pytest.raises(WorkspaceResultError, match="capture_invalid"):
            await store.store_tool_result(binding, None)
    finally:
        await store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["payload", "digest", "outline", "partial", "malformed"])
async def test_workspace_corruption_never_returns_raw_artifact(tmp_path: Path, change: str) -> None:
    store = make_store(tmp_path / "workspaces").store
    binding = store.bind_agent("agent-a", _agent())
    await store.start()
    try:
        reference = await store.store_tool_result(binding, _capture("private" * 3000))
        path = Path(reference.path)
        if change == "payload":
            path.write_bytes(b'"changed"\n')
        elif change == "outline":
            path.with_name("outline.json").write_bytes(b"{}")
        elif change == "partial":
            path.with_name("manifest.json").unlink()
        elif change == "malformed":
            path.write_bytes(b"x" * 513 + b"\n")
        else:
            manifest = json.loads(path.with_name("manifest.json").read_bytes())
            manifest["sha256"] = "0" * 64
            path.with_name("manifest.json").write_text(json.dumps(manifest), encoding="ascii")
        with pytest.raises(WorkspaceResultError):
            await store.read_tool_result_slice(binding, reference.path, 0, 10)
    finally:
        await store.stop()


def test_pin_public_io_and_atomic_no_overwrite(tmp_path: Path) -> None:
    root = tmp_path / "pin"
    with pin_directory(root, create=True) as pinned:
        pinned.make_directory("child")
        pinned.write_new("staged", b"first")
        pinned.write_new("user", b"user")
        with pytest.raises(FileExistsError):
            pinned.publish_file("staged", "user")
        assert pinned.read_bytes("user").data == b"user"
        # A second exclusive create of an existing name must fail, not truncate.
        with pytest.raises(FileExistsError):
            pinned.write_new("user", b"overwrite")
        assert pinned.read_bytes("user").data == b"user"
        pinned.publish_file("staged", "committed")
        assert pinned.read_bytes("committed", max_bytes=5).data == b"first"
        with pytest.raises(FileAccessDenied):
            pinned.read_bytes("committed", max_bytes=4)
        with pytest.raises(FileAccessDenied):
            pinned.write_new("../escape", b"no")
        pinned.remove_file("committed")
        pinned.remove_directory("child")
        assert pinned.list_names() == ("user",)
        assert pinned.identity[1] != 0
    with pytest.raises(FileAccessDenied):
        pinned.verify()
    pinned.close()


def test_verified_source_read_enforces_policy_and_identity(tmp_path: Path) -> None:
    path = tmp_path / "source.txt"
    path.write_bytes(b"alpha\r\nbeta\n")
    read = read_verified_file(path, protected_roots=(), permitted_roots=(tmp_path,))
    assert read.data == b"alpha\r\nbeta\n"
    assert read.revision[0] == len(read.data)
    assert read.identity[1] == path.stat().st_ino
    with pytest.raises(FileAccessDenied):
        read_verified_file(path, protected_roots=(tmp_path,))


@pytest.mark.asyncio
async def test_configured_root_symlink_or_junction_refused_without_target_write(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    _directory_alias(link, target)
    store = make_store(link / "workspaces").store
    try:
        with pytest.raises(WorkspaceResultError, match="workspace_reap_failed"):
            await store.start()
        assert list(target.iterdir()) == []
    finally:
        _remove_alias(link)


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value,code,lives", [
    ("version", True, "manifest_invalid", "manifest_invalid"),
    ("owner_digest", "0" * 64, "manifest_invalid", "manifest_invalid"),
    ("artifact_id", "0" * 32, "manifest_invalid", "manifest_invalid"),
    ("source_chars", True, "manifest_invalid", "manifest_invalid"),
    ("utf8_bytes", -1, "manifest_invalid", "manifest_invalid"),
    ("sha256", "not-a-digest", "manifest_invalid", "manifest_invalid"),
    ("representation", "json", "manifest_invalid", "manifest_invalid"),
    ("committed_at", float("nan"), "clock_invalid", "clock_invalid"),
    # A manifest must place its commit inside the hour of the generation it sits in. The process that committed
    # it refuses any change to what it committed first (F2); only a reader without that record catches it here.
    ("committed_at", GEN_START - 1.0, "manifest_invalid", "payload_changed"),
    ("committed_at", GEN_START + 3600.0, "manifest_invalid", "payload_changed"),
])
async def test_workspace_manifest_refuses_inconsistent_publication(
    tmp_path: Path, field: str, value: object, code: str, lives: str,
) -> None:
    assert tmp_path.is_absolute()
    store = make_store(tmp_path / "workspaces").store
    binding = store.bind_agent("agent-a", _agent())
    await store.start()
    try:
        reference = await store.store_tool_result(binding, _capture("private result"))
        manifest_path = Path(reference.path).with_name("manifest.json")
        manifest = json.loads(manifest_path.read_bytes())
        assert type(manifest[field]) is not type(value) or manifest[field] != value
        manifest[field] = value
        manifest_path.write_text(json.dumps(manifest), encoding="ascii")
        with pytest.raises(WorkspaceResultError, match=lives):
            await store.read_tool_result_slice(binding, reference.path, 0, 1)
        # A reader with no record of the commit, as after a restart, must catch it from the files alone.
        reader = make_store(tmp_path / "workspaces").store
        with pytest.raises(WorkspaceResultError, match=code):
            await reader.read_tool_result_slice(reader.bind_agent("agent-a", _agent()), reference.path, 0, 1)
        assert Path(reference.path).exists()
    finally:
        await store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [b"", b"{\n", b"{}\n", b'"body"', b'"body"\r\n'])
async def test_workspace_decoder_refuses_malformed_fragments(tmp_path: Path, payload: bytes) -> None:
    store = make_store(tmp_path / "workspaces").store
    binding = store.bind_agent("agent-a", _agent())
    await store.start()
    try:
        reference = await store.store_tool_result(binding, _capture("body"))
        Path(reference.path).write_bytes(payload)
        with pytest.raises(WorkspaceResultError, match="payload_invalid"):
            await store.read_tool_result_slice(binding, reference.path, 0, 1)
    finally:
        await store.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("clock", [True, float("nan"), float("inf"), "100", 10 ** 400])
async def test_reap_rejects_invalid_clock_without_filesystem_work(tmp_path: Path, clock: object) -> None:
    # The sweep reads its time only from the store's own clock, so the bad value is injected there.
    harness = make_store(tmp_path / "absent")
    harness.clock[0] = clock
    with pytest.raises(WorkspaceResultError) as refused:
        await harness.store.reap_tool_results()
    assert refused.value.code == "clock_invalid"
    assert not harness.store.root.exists()


@pytest.mark.parametrize("limit", [True, -1, "4"])
def test_pin_read_rejects_invalid_limit(tmp_path: Path, limit: object) -> None:
    with pin_directory(tmp_path) as pinned:
        pinned.write_new("source", b"body")
        with pytest.raises(ValueError, match="invalid file read limit"):
            pinned.read_bytes("source", max_bytes=limit)
        assert pinned.read_bytes("source").data == b"body"


@pytest.mark.parametrize("data", ["body", None, bytearray(b"body")])
def test_pin_write_rejects_nonbytes_without_creating_entry(tmp_path: Path, data: object) -> None:
    with pin_directory(tmp_path) as pinned:
        with pytest.raises(TypeError, match="file writes require bytes"):
            pinned.write_new("refused", data)
        assert pinned.list_names() == ()


@pytest.mark.parametrize("operation", [
    "read_directory", "remove_directory_as_file", "remove_file_as_directory", "publish_directory",
])
def test_pin_child_operations_refuse_wrong_entry_kind(tmp_path: Path, operation: str) -> None:
    with pin_directory(tmp_path) as pinned:
        pinned.make_directory("directory")
        pinned.write_new("file", b"retained")
        with pytest.raises(FileAccessDenied):
            if operation == "read_directory":
                pinned.read_bytes("directory")
            elif operation == "remove_directory_as_file":
                pinned.remove_file("directory")
            elif operation == "remove_file_as_directory":
                pinned.remove_directory("file")
            else:
                pinned.publish_file("directory", "not-created")
        assert set(pinned.list_names()) == {"directory", "file"}
        assert pinned.read_bytes("file").data == b"retained"


def test_pin_open_cannot_replace_live_authority(tmp_path: Path) -> None:
    with pin_directory(tmp_path) as pinned:
        assert pinned.path == tmp_path
        with pytest.raises(FileAccessDenied, match="already open"):
            pinned.open(tmp_path)
        pinned.write_new("empty", b"")
        assert pinned.read_bytes("empty", max_bytes=0).data == b""


def test_pin_missing_expected_directory_is_not_recreated(tmp_path: Path) -> None:
    root = tmp_path / "owned"
    with pin_directory(root, create=True) as pinned:
        identities = pinned.identities
    root.rmdir()
    with pytest.raises(FileAccessDenied, match="previously pinned directory disappeared"):
        with pin_directory(root, create=True, expected=identities):
            pytest.fail("lost directory authority must not be recreated")
    assert not root.exists()


@pytest.mark.parametrize("capture_change", [
    {"source_chars": 0}, {"utf8_bytes": 0}, {"sha256": "0" * 64},
    {"outline": ""}, {"outline": "x" * 1025},
])
def test_capture_contract_rejects_inconsistent_qualification(capture_change: dict[str, object]) -> None:
    with pytest.raises(WorkspaceResultError, match="capture_invalid"):
        replace(_capture("text"), **capture_change)


@pytest.mark.parametrize("kind,code", [
    ("type", "capture_invalid"), ("chars", "capture_limit"), ("bytes", "capture_limit"),
    ("encoding", "capture_encoding"), ("json", "capture_invalid"), ("outline", "capture_invalid"),
])
def test_canonical_record_constructor_checks_all_admission_boundaries(kind: str, code: str) -> None:
    changes = {
        "type": {"text": None},
        "chars": {"text": "x" * 1048577},
        "bytes": {"text": "é" * 524289},
        "encoding": {"text": "\ud800"},
        "json": {"outline": "not-json"},
        "outline": {"outline": "{}"},
    }
    with pytest.raises(WorkspaceResultError, match=code):
        replace(_capture("text"), **changes[kind])


@pytest.mark.asyncio
async def test_unavailable_owner_public_boundaries_refuse_and_stop_idempotently() -> None:
    owner = UnavailableWorkspaceResults()
    with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
        owner.bind_agent("", object())
    for operation in (
        owner.start(), owner.reap_tool_results(),
        owner.store_tool_result(None, None),
        owner.read_tool_result_slice(None, "", None, None),
    ):
        with pytest.raises(WorkspaceResultError, match="workspace_unavailable"):
            await operation
    await owner.stop()
    await owner.stop()
    assert owner.background_tasks == ()


@pytest.mark.parametrize("owner", [None, object(), SimpleNamespace(start=None)])
def test_resolver_absent_invalid_never_unarms(owner: object) -> None:
    assert type(resolve_workspace_results(SimpleNamespace(workspace_results=owner))) is UnavailableWorkspaceResults
    assert isinstance(resolve_workspace_results(object()), WorkspaceResults)


def test_store_satisfies_the_workspace_results_protocol(tmp_path: Path) -> None:
    store = make_store(tmp_path / "workspaces").store
    assert isinstance(store, WorkspaceResults) and is_workspace_results(store)
    assert resolve_workspace_results(SimpleNamespace(workspace_results=store)) is store
    assert store.background_tasks == () and store.root == tmp_path / "workspaces"


def test_neutral_public_records_and_owner_resolver_refuse_invalid_authority(tmp_path: Path) -> None:
    from probos.execution.workspace_results import (
        FreshRead, ResultDelivery, SourceRecoveryScope, SourceRef, WorkspaceReadContext,
    )

    class _BadRuntime:
        @property
        def workspace_results(self) -> object:
            raise ValueError("private resolution error")

    class _BadOwner(WorkspaceResultStore):
        @property
        def background_tasks(self) -> tuple[asyncio.Task[None], ...]:
            raise ValueError("private owner error")

    assert isinstance(resolve_workspace_results(_BadRuntime()), UnavailableWorkspaceResults)
    assert not is_workspace_results(_BadOwner(WorkspaceManager(tmp_path)))
    with pytest.raises(WorkspaceResultError, match="source_reference_invalid"):
        SourceRef("", "", "", (1, 2, 3), (1, 2, 3), "bad", 0, 0, 0, True)
    with pytest.raises(WorkspaceResultError, match="reference_unavailable"):
        WorkspaceReadContext(UnavailableWorkspaceResults(), None, SourceRecoveryScope("a", "run"), FreshRead("a", "run"))
    with pytest.raises(WorkspaceResultError, match="delivery_invalid"):
        ResultDelivery("workspace", None)
    scope = SourceRecoveryScope("a", "run")
    for path in ("", None, "relative"):
        with pytest.raises(WorkspaceResultError, match="reference_unavailable"):
            scope.select(path)
    with pytest.raises(WorkspaceResultError, match="reference_unavailable"):
        scope.reserve(None)
    with pytest.raises(WorkspaceResultError, match="reference_unavailable"):
        scope.validate(str(tmp_path / "source"), FreshRead("other", "run"))


def test_reap_result_defaults_and_deferred_field() -> None:
    assert WorkspaceReapResult() == WorkspaceReapResult(0, 0, 0, 0)
    assert WorkspaceReapResult(1, 2, 3).deferred == 0
    assert WorkspaceReapResult(deferred=4).deferred == 4


@pytest.mark.parametrize("fields", [
    {"attempts": 0}, {"attempts": True}, {"delays": [0.1]}, {"delays": (-1.0, 0.2, 0.5)},
    {"delays": (float("nan"), 0.2, 0.5)}, {"delays": (0.1,)}, {"sweep_sleep_budget": -1.0},
    {"sweep_sleep_budget": float("inf")}, {"sweep_sleep_budget": "2"},
])
def test_retry_policy_refuses_unbounded_or_malformed_values(fields: dict[str, object]) -> None:
    with pytest.raises(ValueError, match="invalid workspace result retry policy"):
        RetryPolicy(**fields)


def test_retry_policy_defaults_are_the_contracted_numbers() -> None:
    policy = RetryPolicy()
    assert (policy.attempts, policy.delays, policy.sweep_sleep_budget) == (4, (0.05, 0.2, 0.5), 2.0)
    assert RetryPolicy(attempts=1, delays=()).attempts == 1


class _Brief(Exception):
    pass


def _flaky(failures: int) -> tuple[list[int], object]:
    calls: list[int] = []

    def operation() -> str:
        calls.append(len(calls))
        if len(calls) <= failures:
            raise _Brief("fixture")
        return "done"

    return calls, operation


def _brief(exc: Exception) -> bool:
    return isinstance(exc, _Brief)


def test_retry_runner_retries_a_brief_failure_with_the_policy_delays() -> None:
    sleeps: list[float] = []
    calls, operation = _flaky(2)
    assert RetryRunner(RetryPolicy(), sleeps.append).run(operation, _brief) == "done"
    assert len(calls) == 3 and sleeps == [0.05, 0.2]


def test_retry_runner_raises_the_last_failure_when_attempts_run_out() -> None:
    sleeps: list[float] = []
    calls, operation = _flaky(99)
    with pytest.raises(_Brief):
        RetryRunner(RetryPolicy(), sleeps.append).run(operation, _brief)
    assert len(calls) == 4 and sleeps == [0.05, 0.2, 0.5]


def test_retry_runner_never_retries_what_is_not_retryable() -> None:
    sleeps: list[float] = []
    calls, operation = _flaky(99)
    with pytest.raises(_Brief):
        RetryRunner(RetryPolicy(), sleeps.append).run(operation, lambda exc: False)
    assert len(calls) == 1 and sleeps == []


def test_retry_runner_never_sleeps_past_the_budget() -> None:
    sleeps: list[float] = []
    policy = RetryPolicy(attempts=4, delays=(1.0, 1.0, 1.0), sweep_sleep_budget=1.5)
    calls, operation = _flaky(99)
    with pytest.raises(_Brief):
        RetryRunner(policy, sleeps.append).run(operation, _brief)
    assert sleeps == [1.0] and len(calls) == 2


def test_retry_runner_budget_is_shared_by_every_operation_of_one_runner() -> None:
    sleeps: list[float] = []
    policy = RetryPolicy(attempts=2, delays=(0.5,), sweep_sleep_budget=1.0)
    runner = RetryRunner(policy, sleeps.append)
    for _ in range(3):
        _, operation = _flaky(99)
        with pytest.raises(_Brief):
            runner.run(operation, _brief)
    assert sleeps == [0.5, 0.5], "the third operation defers without sleeping"


def test_directory_identities_evict_only_the_named_subtree(tmp_path: Path) -> None:
    cache = DirectoryIdentities()
    gen, sibling = tmp_path / "ns" / "gen", tmp_path / "ns" / "gen2"
    identity = (1, 2, 3)
    cache.remember([
        (tmp_path / "ns", identity), (gen, identity), (gen / "digest", identity),
        (gen / "digest" / "artifact", identity), (sibling, identity),
    ])
    assert cache.evict_under(gen) == 3
    assert cache.known() == {tmp_path / "ns", sibling}
    assert dict(cache.expected()) == {tmp_path / "ns": identity, sibling: identity}
    assert cache.evict_under(gen) == 0


def test_stale_identity_blocks_recreating_a_removed_directory(tmp_path: Path) -> None:
    """The failure mode eviction prevents: an expected path that vanished is never recreated."""
    root = tmp_path / "ns"
    with pin_directory(root / "gen" / "digest", create=True) as pinned:
        cache = DirectoryIdentities()
        cache.remember(pinned.identities)
    (root / "gen" / "digest").rmdir()
    (root / "gen").rmdir()
    with pytest.raises(FileAccessDenied, match="previously pinned directory disappeared"):
        with pin_directory(root / "gen" / "digest", create=True, expected=cache.expected()):
            pytest.fail("a stale identity must not allow silent recreation")
    cache.evict_under(root / "gen")
    with pin_directory(root / "gen" / "digest", create=True, expected=cache.expected()) as pinned:
        assert pinned.path == root / "gen" / "digest"


# ---- M2: the reserved namespace on every ordinary path (resolver, listings, sizes) ----


def test_private_namespace_includes_malformed_and_case_variants(tmp_path: Path) -> None:
    owner = Path("owner")
    reserved = [
        owner / RESULT_DIRECTORY,
        owner / ".TOOL-results" / "broken",
        owner / ".Tool-Results" / GEN / DIGEST / ARTIFACT_ID / "payload.jsonl",
        owner / RESULT_DIRECTORY / "not-a-generation" / "x",
        owner / RESULT_DIRECTORY / "2026-10-11T07:00Z" / DIGEST,
        owner / RESULT_DIRECTORY / GEN[:-1] / "x",
        owner / "sub" / RESULT_DIRECTORY / GEN / DIGEST / ARTIFACT_ID,
    ]
    ordinary = [
        owner / "tool-results" / "ordinary.txt",
        owner / ".tool-result" / GEN,
        owner / f"{RESULT_DIRECTORY}.bak" / GEN,
        owner / f"x{RESULT_DIRECTORY}" / GEN,
        owner / "generation" / GEN / DIGEST,
    ]
    assert all(is_workspace_result_path(path) for path in reserved)
    assert not any(is_workspace_result_path(path) for path in ordinary)
    # The resolver applies the same vocabulary, on every platform and whatever the case.
    manager = WorkspaceManager(tmp_path / "workspaces")
    base = manager.resolve("owner", create=True)
    for path in reserved:
        assert manager.resolve_file("owner", path.relative_to(owner).as_posix(), create_parents=True) is None
    assert sorted(entry.name for entry in base.iterdir()) == [], "refusal happens before any parent is created"
    for path in ordinary:
        assert manager.resolve_file("owner", path.relative_to(owner).as_posix()) == base / path.relative_to(owner)
    with pytest.raises(ValueError, match="invalid workspace result error"):
        WorkspaceResultError("private\nmessage")


def test_workspace_manager_stays_a_path_owner_with_no_result_lifecycle() -> None:
    """The workspace manager gains the reservation and nothing of the result lifecycle."""
    source = Path(inspect.getsourcefile(WorkspaceManager)).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    imported += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    assert not any("workspace_result_store" in name for name in imported), imported
    manager = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "WorkspaceManager")
    methods = [node for node in manager.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    assert len(methods) <= 15 and (manager.end_lineno - manager.lineno + 1) <= 500
    assert not any(isinstance(node, ast.AsyncFunctionDef) for node in methods)
    assert {node.name for node in methods}.isdisjoint({
        "bind_agent", "store_tool_result", "read_tool_result_slice", "reap_tool_results",
        "start", "stop", "background_tasks",
    })
    init = next(node for node in methods if node.name == "__init__")
    assert [arg.arg for arg in init.args.args] == ["self", "root"]
    assert not init.args.kwonlyargs and init.args.vararg is None and init.args.kwarg is None


@pytest.mark.parametrize("where", ["outside", "inside"])
def test_r1_lexical_namespace_redirect_out_is_still_reserved(tmp_path: Path, where: str) -> None:
    """An alias named ``.tool-results`` that leads somewhere harmless is still the namespace.

    Led outside the owner folder, confinement would refuse it anyway; led to a
    plain directory inside the folder, only the name keeps it reserved, in the
    resolver and in the listings and sizes alike.
    """
    manager = WorkspaceManager(tmp_path / "workspaces")
    base = manager.resolve("owner", create=True)
    (base / "ordinary.txt").write_bytes(b"ordinary")
    target = tmp_path / "ordinary-target" if where == "outside" else base / "plain-dir"
    in_layout = target / GEN / DIGEST / ARTIFACT_ID / "payload.jsonl"
    in_layout.parent.mkdir(parents=True)
    in_layout.write_bytes(b"ordinary target in the generation layout")
    (target / "file.txt").write_bytes(b"ordinary target")
    before = [(entry.name, entry.size_bytes) for entry in manager.list_files("owner")]
    total_before = manager.total_bytes("owner")
    if where == "outside":
        assert before == [("ordinary.txt", 8)] and total_before == 8  # premise
    else:
        assert ("plain-dir/file.txt", 15) in before and total_before == 8 + 15 + 40  # premise
    link = base / RESULT_DIRECTORY
    _directory_alias(link, target)
    try:
        # Premise: the redirect leads somewhere that is not reserved, yet answers to the namespace's name.
        assert not is_workspace_result_path(link.resolve()) and link.resolve().is_relative_to(base) == (where == "inside")
        assert (link / "file.txt").read_bytes() == b"ordinary target"
        for requested in (
            f"{RESULT_DIRECTORY}/file.txt", RESULT_DIRECTORY,
            f"{RESULT_DIRECTORY}/{GEN}/{DIGEST}/{ARTIFACT_ID}/payload.jsonl",
        ):
            assert manager.resolve_file("owner", requested, create_parents=True) is None, requested
        assert [(entry.name, entry.size_bytes) for entry in manager.list_files("owner")] == before
        assert manager.total_bytes("owner") == total_before
        assert (target / "file.txt").read_bytes() == b"ordinary target"
        assert in_layout.read_bytes() == b"ordinary target in the generation layout"
    finally:
        _remove_alias(link)


@pytest.mark.parametrize("opaque_alias", [False, True])
def test_r1_resolver_listing_and_sizes_exclude_private_and_intermediate_aliases(
    tmp_path: Path, opaque_alias: bool,
) -> None:
    manager = WorkspaceManager(tmp_path / "workspaces")
    base = manager.resolve("owner", create=True)
    _private_artifact(base)
    private = base / RESULT_DIRECTORY
    (private / "unowned.txt").write_bytes(b"preserve user material")
    (base / "ordinary.txt").write_bytes(b"public")
    opaque = base / ".venv"
    aliases: list[Path] = []
    if opaque_alias:
        _directory_alias(opaque, private)
        aliases.append(opaque)
    else:
        opaque.mkdir()
        nested_private = opaque / RESULT_DIRECTORY
        nested_private.mkdir()
        (nested_private / "unknown.txt").write_bytes(b"not visible or counted")
        (opaque / "ordinary.bin").write_bytes(b"venv")
    alias = base / "alias"
    _directory_alias(alias, private)
    aliases.append(alias)
    try:
        # Premises: the namespace holds bytes that would show if it were counted, an alias
        # enters it, and a later ".." leaves it again, so only the prefix reveals the entry.
        hidden = sum(path.stat().st_size for path in private.rglob("*") if path.is_file())
        assert hidden >= len(PRIVATE_BYTES) + len(b"preserve user material")
        assert is_workspace_result_path(alias.resolve())
        assert (alias / ".." / "ordinary.txt").resolve() == base / "ordinary.txt"
        in_generation = f"{GEN}/{DIGEST}/{ARTIFACT_ID}/payload.jsonl"
        for requested in (
            RESULT_DIRECTORY, f"{RESULT_DIRECTORY}/new/file", f"{RESULT_DIRECTORY}/../ordinary.txt",
            f"{RESULT_DIRECTORY}/{in_generation}", f"{RESULT_DIRECTORY}/{GEN}/new/file",
            "alias", "alias/unowned.txt", "alias/../ordinary.txt", f"alias/{in_generation}",
            ".TOOL-RESULTS/new/file",
        ):
            assert manager.resolve_file("owner", requested, create_parents=True) is None, requested
        assert not (private / "new").exists() and not (private / GEN / "new").exists()
        expected = [("ordinary.txt", 6)] if opaque_alias else [(".venv", 4), ("ordinary.txt", 6)]
        assert [(item.name, item.size_bytes) for item in manager.list_files("owner")] == expected
        assert manager.list_files("owner", limit=1)[0].name == expected[0][0]
        assert manager.total_bytes("owner") == (6 if opaque_alias else 10)
        # Pruned before descent: no directory of the namespace, nor an alias into it, is ever scanned.
        with patch.object(os, "scandir", wraps=os.scandir) as scans:
            manager.list_files("owner")
            manager.total_bytes("owner")
        scanned = [Path(call.args[0]) for call in scans.call_args_list]
        assert scanned and not any(is_workspace_result_path(path) for path in scanned), scanned
        assert manager.resolve_file("owner", "sub/new.txt", create_parents=True) == base / "sub" / "new.txt"
        assert (base / "sub").is_dir()
        assert manager.venv_dir("owner") == opaque and manager.resolve("owner") == base
        assert (private / "unowned.txt").read_bytes() == b"preserve user material"
        assert (private / GEN / DIGEST / ARTIFACT_ID / "payload.jsonl").read_bytes() == PRIVATE_BYTES
    finally:
        for link in reversed(aliases):
            _remove_alias(link)


@pytest.mark.parametrize("answers", [("ordinary", "private"), ("private", "ordinary")])
def test_resolve_file_returns_only_the_checked_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answers: tuple[str, str],
) -> None:
    """R2-2 (injected variant, every platform): a resolver whose answers change between visits.

    The candidate is resolved ONCE, that value is what is checked, and exactly that
    value is returned. A second resolution that was returned instead would hand
    ``("ordinary", "private")`` the private artifact, and without the final-value check
    ``("private", "ordinary")`` would serve it outright.
    """
    agent = _agent("agent-a", "Probe")
    manager = WorkspaceManager(tmp_path / "ws")
    owner = manager.key_for_agent(agent)
    base = manager.resolve(owner, create=True)
    private = _private_artifact(base) / "payload.jsonl"
    ordinary = base / "ordinary.txt"
    ordinary.write_text("ordinary", encoding="utf-8")
    candidate = base / "alias" / "payload.jsonl"
    values = {"ordinary": ordinary, "private": private}
    original = Path.resolve
    visits: list[Path] = []

    def changing_resolution(path: Path, *args: Any, **kwargs: Any) -> Path:
        if path == candidate:
            visits.append(path)
            return values[answers[min(len(visits), len(answers)) - 1]]
        return original(path, *args, **kwargs)

    client, runtime, _ = _route_client(tmp_path, monkeypatch, agent)
    try:
        with monkeypatch.context() as change:
            change.setattr(Path, "resolve", changing_resolution)
            # Premise: the first visit and every later one answer differently.
            assert candidate.resolve() == values[answers[0]] and candidate.resolve() == values[answers[1]]
            assert values[answers[0]] != values[answers[1]] and len(visits) == 2
            visits.clear()
            direct = manager.resolve_file(owner, "alias/payload.jsonl")
            assert len(visits) == 1, "the candidate is resolved at most once"
            visits.clear()
            response = client.get(
                f"/api/agent/{agent.id}/workspace/file", params={"path": "alias/payload.jsonl"},
            )
            assert len(visits) == 1, "the real route resolves the candidate at most once"
    finally:
        client.close()
    assert PRIVATE_TEXT not in response.text
    if answers[0] == "ordinary":
        assert direct == ordinary
        assert response.status_code == 200 and response.json()["content"] == "ordinary"
    else:
        assert direct is None and response.status_code == 400


@pytest.mark.parametrize("kind", [
    pytest.param("junction", marks=pytest.mark.skipif(
        sys.platform != "win32", reason="AD-1240: a directory junction is Windows-only",
    )),
    pytest.param("symlink", marks=pytest.mark.skipif(
        sys.platform == "win32",
        reason="AD-1240: an unprivileged directory symlink is a POSIX premise (Windows needs a privilege)",
    )),
])
def test_resolve_file_physical_swap_returns_the_checked_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str,
) -> None:
    """R2-2 (physical variant): a real alias is re-pointed into the namespace around the resolution.

    The injected variant above runs on every platform; this one proves the same
    properties with a real junction (Windows) or symlink (POSIX).

    Early swap: right after the candidate's first resolution. A later check of
    the alias prefix may see it and refuse; the swapped-in artifact must never
    be returned or served.

    Late swap: during parent creation, after every check and before the return.
    The value returned must be the checked target, which does not pass through
    the alias, so the governed write receives the ordinary file and a second,
    unchecked resolution (which would now read the artifact) cannot be the answer.
    """
    make = _make_junction if kind == "junction" else _make_symlink
    agent = _agent("agent-a", "Probe")
    manager = WorkspaceManager(tmp_path / "ws")
    owner = manager.key_for_agent(agent)
    base = manager.resolve(owner, create=True)
    private_dir = _private_artifact(base)
    ordinary_dir = base / "ordinary-dir"
    ordinary_dir.mkdir()
    (ordinary_dir / "payload.jsonl").write_bytes(b"ordinary")
    alias = base / "alias"
    make(alias, ordinary_dir)
    candidate = alias / "payload.jsonl"
    checked_value = ordinary_dir / "payload.jsonl"
    assert candidate.resolve() == checked_value and candidate.read_bytes() == b"ordinary"
    original_resolve, original_mkdir = Path.resolve, Path.mkdir
    visits: list[Path] = []
    creations: list[Path] = []

    def repoint_into_the_namespace() -> None:
        _remove_alias(alias)
        make(alias, private_dir)

    def swapping_after_the_first_resolution(path: Path, *args: Any, **kwargs: Any) -> Path:
        result = original_resolve(path, *args, **kwargs)
        if path == candidate:
            visits.append(result)
            if len(visits) == 1:
                repoint_into_the_namespace()
        return result

    def counting_resolution(path: Path, *args: Any, **kwargs: Any) -> Path:
        if path == candidate:
            visits.append(path)
        return original_resolve(path, *args, **kwargs)

    def swapping_during_parent_creation(path: Path, *args: Any, **kwargs: Any) -> None:
        original_mkdir(path, *args, **kwargs)
        if path == ordinary_dir and not creations:
            creations.append(path)
            repoint_into_the_namespace()

    def swapped_into_the_namespace() -> bool:
        return is_workspace_result_path(original_resolve(candidate)) and candidate.read_bytes() == PRIVATE_BYTES

    client, runtime, _ = _route_client(tmp_path, monkeypatch, agent)
    runtime.submit_write_with_consensus = AsyncMock(return_value={"committed": True})
    url = f"/api/agent/{agent.id}/workspace"
    try:
        # Early swap, direct call and real GET.
        with monkeypatch.context() as change:
            change.setattr(Path, "resolve", swapping_after_the_first_resolution)
            direct = manager.resolve_file(owner, "alias/payload.jsonl")
        assert len(visits) == 1 and visits[0] == checked_value and swapped_into_the_namespace()  # premise
        assert direct is None or direct == checked_value
        _remove_alias(alias)
        make(alias, ordinary_dir)
        visits.clear()
        with monkeypatch.context() as change:
            change.setattr(Path, "resolve", swapping_after_the_first_resolution)
            served = client.get(url + "/file", params={"path": "alias/payload.jsonl"})
        assert len(visits) == 1 and swapped_into_the_namespace()  # premise
        assert PRIVATE_TEXT not in served.text
        assert served.status_code == 400 or (served.status_code == 200 and served.json()["content"] == "ordinary")

        # Late swap, direct call and real POST (whose governed write is the consumer of the value).
        _remove_alias(alias)
        make(alias, ordinary_dir)
        visits.clear()
        with monkeypatch.context() as change:
            change.setattr(Path, "resolve", counting_resolution)
            change.setattr(Path, "mkdir", swapping_during_parent_creation)
            direct = manager.resolve_file(owner, "alias/payload.jsonl", create_parents=True)
        assert len(creations) == 1 and len(visits) == 1 and swapped_into_the_namespace()  # premise
        assert direct == checked_value and direct.read_bytes() == b"ordinary"
        _remove_alias(alias)
        make(alias, ordinary_dir)
        creations.clear()
        visits.clear()
        with monkeypatch.context() as change:
            change.setattr(Path, "resolve", counting_resolution)
            change.setattr(Path, "mkdir", swapping_during_parent_creation)
            written = client.post(url + "/file", json={"path": "alias/payload.jsonl", "content": "replacement"})
        assert len(creations) == 1 and len(visits) == 1 and swapped_into_the_namespace()  # premise
        assert written.status_code == 200 and written.json()["outcome"] == "committed"
        runtime.submit_write_with_consensus.assert_awaited_once()
        assert Path(runtime.submit_write_with_consensus.await_args.kwargs["path"]) == checked_value
    finally:
        client.close()
        _remove_alias(alias)


@pytest.mark.parametrize("failure", [OSError("fixture"), RuntimeError("fixture"), ValueError("fixture")])
@pytest.mark.parametrize("failing", ["candidate", "owner_folder", "prefix"])
def test_resolve_file_refuses_what_it_cannot_resolve_and_does_not_retry(
    tmp_path: Path, failure: Exception, failing: str,
) -> None:
    manager = WorkspaceManager(tmp_path / "ws")
    base = manager.resolve("owner", create=True)
    candidate = base / "sub" / "file.txt"
    target = {"candidate": candidate, "owner_folder": base, "prefix": candidate.parent}[failing]
    assert manager.resolve_file("owner", "sub/file.txt") == candidate, "premise: undisturbed, it is accepted"
    original = Path.resolve
    attempts: Counter[Path] = Counter()

    def failing_resolution(path: Path, *args: Any, **kwargs: Any) -> Path:
        if path == target:
            attempts[path] += 1
            raise failure
        return original(path, *args, **kwargs)

    with patch.object(Path, "resolve", failing_resolution):
        assert manager.resolve_file("owner", "sub/file.txt", create_parents=True) is None
    assert attempts == Counter({target: 1}), "a failed resolution is refused, not retried"
    assert not (base / "sub").exists(), "refusal happens before any parent is created"


def test_resolve_file_resolves_the_folder_and_the_target_once_each(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "ws")
    base = manager.resolve("owner", create=True)
    candidate = base / "sub" / "deeper" / "file.txt"
    with _count_resolves() as calls:
        assert manager.resolve_file("owner", "sub/deeper/file.txt") == candidate
    assert calls[base] == 1 and calls[candidate] == 1
    assert max(calls.values()) == 1, "no path is resolved twice"
    assert set(calls) == {candidate, *candidate.parents}, "the target and every lexical prefix were checked"


def _ordinary_fixture(manager: WorkspaceManager) -> Path:
    """Ten directories of a hundred files each, every file ``b"ordinary fixture\\n"`` (17 bytes)."""
    base = manager.resolve("ordinary", create=True)
    for directory in range(10):
        folder = base / f"d{directory:02}"
        folder.mkdir()
        for number in range(100):
            (folder / f"f{number:03}.txt").write_bytes(b"ordinary fixture\n")
    return base


def test_ordinary_inspection_resolve_budget(tmp_path: Path) -> None:
    """R2-5: the owner decision, one resolution per directory or link, none per plain file."""
    manager = WorkspaceManager(tmp_path / "ordinary-workspaces")
    base = _ordinary_fixture(manager)
    fixture = sorted(base.rglob("*.txt"))
    assert len(fixture) == 1000 and {path.stat().st_size for path in fixture} == {17}  # premise
    expected = (
        [f"d{directory:02}" for directory in range(10)]
        + [f"d00/f{number:03}.txt" for number in range(100)]
        + [f"d01/f{number:03}.txt" for number in range(90)]
    )
    depth = len(base.parents) + 1
    descended, links = 11, 0  # the owner folder and its ten directories; the fixture has no link
    budget = depth + 1 + descended + links  # D + 12

    with _count_resolves() as listed:
        entries = manager.list_files("ordinary")
    assert [entry.name for entry in entries] == expected
    assert [(entry.is_dir, entry.size_bytes) for entry in entries] == [(True, 0)] * 10 + [(False, 17)] * 190
    assert depth <= sum(listed.values()) <= budget
    assert max(listed.values()) == 1, "every path is resolved at most once per walk"
    assert not any(path.suffix == ".txt" for path in listed), "a plain file is never resolved"

    with _count_resolves() as sized:
        total = manager.total_bytes("ordinary")
    assert total == 17000
    assert depth <= sum(sized.values()) <= budget
    assert max(sized.values()) == 1
    assert not any(path.suffix == ".txt" for path in sized), "a plain file is never resolved"

    # An alias swapped in between calls gets a fresh decision, and so does swapping it back out.
    swap = manager.resolve("swap", create=True)
    (swap / "kept.txt").write_bytes(b"kept")
    artifact = _private_artifact(manager.resolve("victim", create=True))
    aside = tmp_path / "swap-aside"
    with patch.object(os, "scandir", wraps=os.scandir) as scans:
        assert [(item.name, item.size_bytes) for item in manager.list_files("swap")] == [("kept.txt", 4)]
        assert manager.total_bytes("swap") == 4
        assert scans.call_count == 2, "premise: an admitted folder is scanned"
    swap.rename(aside)
    _directory_alias(swap, artifact)
    try:
        assert is_workspace_result_path(swap.resolve()) and (swap / "payload.jsonl").read_bytes() == PRIVATE_BYTES
        with patch.object(os, "scandir", wraps=os.scandir) as scans:
            assert manager.list_files("swap") == [] and manager.total_bytes("swap") == 0
            scans.assert_not_called()  # refused before any of the namespace is scanned
    finally:
        _remove_alias(swap)
        aside.rename(swap)
    assert [(item.name, item.size_bytes) for item in manager.list_files("swap")] == [("kept.txt", 4)]
    assert manager.total_bytes("swap") == 4


def test_resolve_count_independent_of_file_count(tmp_path: Path) -> None:
    """What a walk costs follows its directories and links, never its files."""
    manager = WorkspaceManager(tmp_path / "ws")
    counts: dict[int, tuple[int, int]] = {}
    for owner, files in (("small", 5), ("big", 5000)):
        folder = manager.resolve(owner, create=True) / "d"
        folder.mkdir()
        for number in range(files):
            (folder / f"f{number:04}.txt").write_bytes(b"x")
        assert sum(1 for _ in folder.iterdir()) == files  # premise: the fixtures differ in file count only
        with _count_resolves() as listed:
            entries = manager.list_files(owner, limit=10_000)
        with _count_resolves() as sized:
            total = manager.total_bytes(owner)
        assert len(entries) == files + 1 and total == files  # premise: every file was reached
        counts[files] = (sum(listed.values()), sum(sized.values()))
    assert counts[5] == counts[5000], counts
    assert all(count > 0 for count in counts[5]), "premise: the walks do resolve something"


@pytest.mark.parametrize("operation", ["list", "size"])
@pytest.mark.parametrize("replacement", ["directory", "alias_into_namespace"])
def test_ordinary_walk_does_not_enter_a_directory_replaced_after_its_check(
    tmp_path: Path, operation: str, replacement: str,
) -> None:
    """The identity taken from a directory's scan entry is compared when the walk enters it."""
    manager = WorkspaceManager(tmp_path / "ws")
    base = manager.resolve("owner", create=True)
    for name, size in (("a", 3), ("b", 5)):
        (base / name).mkdir()
        (base / name / f"{name}.txt").write_bytes(b"x" * size)
    namespace_dir = _private_artifact(manager.resolve("victim", create=True))
    aside = tmp_path / "aside"
    aside.mkdir()
    original = Path.resolve
    swaps: list[bool] = []

    def swapping(path: Path, *args: Any, **kwargs: Any) -> Path:
        result = original(path, *args, **kwargs)
        if path == base / "b" and not swaps:  # "b" has just been checked, and is replaced before it is entered
            swaps.append(True)
            (base / "b").rename(aside / "b")
            if replacement == "directory":
                (base / "b").mkdir()
                (base / "b" / "intruder.txt").write_bytes(b"i" * 7)
            else:
                _directory_alias(base / "b", namespace_dir)
        return result

    try:
        with patch.object(Path, "resolve", swapping), patch.object(os, "scandir", wraps=os.scandir) as scans:
            outcome = (
                [entry.name for entry in manager.list_files("owner")]
                if operation == "list" else manager.total_bytes("owner")
            )
        # Premises: the replacement happened mid-walk, and what now sits at the path is visible.
        replacement_file = base / "b" / ("intruder.txt" if replacement == "directory" else "payload.jsonl")
        assert swaps == [True] and replacement_file.exists()
        assert replacement == "directory" or is_workspace_result_path((base / "b").resolve())
        # Outcome: only what was checked is reported ("b" was listed when it was checked), and the
        # replacement was refused before it was scanned.
        assert outcome == (["a", "b", "a/a.txt"] if operation == "list" else 3)
        scanned = {Path(call.args[0]) for call in scans.call_args_list}
        assert base / "a" in scanned and base / "b" not in scanned, scanned
        # Control: a walk that starts after the replacement decides afresh and does see it.
        if replacement == "directory":
            assert "b/intruder.txt" in [entry.name for entry in manager.list_files("owner")]
            assert manager.total_bytes("owner") == 10
    finally:
        if replacement != "directory":
            _remove_alias(base / "b")


class _HookedOs:
    """The ``os`` module, except that something happens just before one directory is scanned (once)."""

    def __init__(self, directory: Path, before_scan: Callable[[], None]) -> None:
        self._directory, self._before_scan, self.fired = directory, before_scan, False

    def __getattr__(self, name: str) -> Any:
        return getattr(os, name)

    def scandir(self, path: Any, *args: Any, **kwargs: Any) -> Any:
        if os.fspath(path) == str(self._directory) and not self.fired:
            self.fired = True
            self._before_scan()
        return os.scandir(path, *args, **kwargs)


@pytest.mark.parametrize("operation", ["list", "size"])
def test_ordinary_walk_discards_a_listing_taken_from_a_directory_replaced_during_the_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str,
) -> None:
    manager = WorkspaceManager(tmp_path / "ws")
    base = manager.resolve("owner", create=True)
    for name, size in (("a", 2), ("b", 3)):
        (base / name).mkdir()
        (base / name / f"{name}.txt").write_bytes(b"x" * size)
    aside = tmp_path / "aside"
    aside.mkdir()

    def replace_b() -> None:
        (base / "b").rename(aside / "b")
        (base / "b").mkdir()
        (base / "b" / "intruder.txt").write_bytes(b"i" * 7)

    hooked = _HookedOs(base / "b", replace_b)
    monkeypatch.setattr(workspace_module, "os", hooked)
    outcome = (
        [entry.name for entry in manager.list_files("owner")]
        if operation == "list" else manager.total_bytes("owner")
    )
    assert hooked.fired and (base / "b" / "intruder.txt").exists()  # premise: replaced after the identity was read
    assert outcome == (["a", "b", "a/a.txt"] if operation == "list" else 2)


@pytest.mark.parametrize("fault", ["reserved", "error"])
@pytest.mark.parametrize("which", [0, 1, -1])
def test_owner_decision_refuses_a_reserved_or_unresolvable_prefix(
    tmp_path: Path, which: int, fault: str,
) -> None:
    manager = WorkspaceManager(tmp_path / "ws")
    base = manager.resolve("owner", create=True)
    (base / "file.txt").write_bytes(b"ordinary")
    target = (base, *base.parents)[which]  # the owner folder, its parent, and the anchor
    with patch.object(os, "scandir", wraps=os.scandir) as scans:
        assert [entry.name for entry in manager.list_files("owner")] == ["file.txt"]  # premise
        assert manager.total_bytes("owner") == 8
        assert scans.call_count == 2, "premise: an admitted folder is scanned"
    original = Path.resolve

    def disturbed(path: Path, *args: Any, **kwargs: Any) -> Path:
        if path == target:
            if fault == "error":
                raise OSError("fixture: unresolvable")
            return tmp_path / "elsewhere" / RESULT_DIRECTORY / GEN
        return original(path, *args, **kwargs)

    with patch.object(Path, "resolve", disturbed), patch.object(os, "scandir", wraps=os.scandir) as scans:
        assert manager.list_files("owner") == []
        assert manager.total_bytes("owner") == 0
        scans.assert_not_called()  # refused before anything of it is scanned


def test_inspection_of_an_owner_path_that_is_not_a_directory_is_empty(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "ws")
    (tmp_path / "ws").mkdir()
    (tmp_path / "ws" / "owner").write_bytes(b"a file where the folder should be")
    with patch.object(os, "scandir", wraps=os.scandir) as scans:
        assert manager.list_files("owner") == [] and manager.total_bytes("owner") == 0
        scans.assert_not_called()


def test_inspection_refuses_a_root_reached_through_the_namespace_name_even_when_redirected(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real"
    (real / "ws" / "owner").mkdir(parents=True)
    (real / "ws" / "owner" / "file.txt").write_bytes(b"ordinary")
    link = tmp_path / RESULT_DIRECTORY
    _directory_alias(link, real)
    try:
        manager = WorkspaceManager(link / "ws")
        base = manager.resolve("owner")
        # Premise: nothing about the resolved folder is reserved; only the name on the way to it is.
        assert not is_workspace_result_path(base.resolve()) and (base / "file.txt").read_bytes() == b"ordinary"
        assert manager.list_files("owner") == [] and manager.total_bytes("owner") == 0
        assert manager.resolve_file("owner", "file.txt") is None
    finally:
        _remove_alias(link)


def _inspect(manager: WorkspaceManager, owner: str) -> tuple[list[tuple[str, bool, int]], int]:
    """What both inspections report for ``owner``: every listed entry, and the total."""
    listing = [(item.name, item.is_dir, item.size_bytes) for item in manager.list_files(owner, limit=10_000)]
    return listing, manager.total_bytes(owner)


@pytest.mark.parametrize("kind,fault", [
    ("directory", "reserved"), ("directory", "outside"), ("directory", "error"),
    ("link", "reserved"), ("link", "outside"), ("link", "missing"), ("link", "error"),
])
def test_ordinary_walk_drops_a_directory_or_link_it_cannot_check(tmp_path: Path, kind: str, fault: str) -> None:
    manager = WorkspaceManager(tmp_path / "ws")
    base = manager.resolve("owner", create=True)
    (base / "keep.txt").write_bytes(b"keep")
    (base / "keep-dir").mkdir()
    (base / "keep-dir" / "inner.txt").write_bytes(b"inner")
    if kind == "directory":
        target = base / "drop-dir"
        target.mkdir()
        (target / "inside.txt").write_bytes(b"dropped")
        dropped, kept_total = {"drop-dir", "drop-dir/inside.txt"}, 9
    else:
        (base / "linked").mkdir()
        (base / "linked" / "inside.txt").write_bytes(b"dropped")
        target = base / "drop-link"
        _directory_alias(target, base / "linked")
        dropped, kept_total = {"drop-link"}, 16
    try:
        everything = [name for name, _, _ in _inspect(manager, "owner")[0]]
        assert dropped <= set(everything) and manager.total_bytes("owner") == 16  # premise: listed and counted
        original = Path.resolve

        def disturbed(path: Path, *args: Any, **kwargs: Any) -> Path:
            if path == target:
                if fault == "error":
                    raise OSError("fixture: unresolvable")
                if fault == "missing":
                    return base / "no-such-entry"
                if fault == "outside":
                    return tmp_path / "elsewhere"
                return tmp_path / "elsewhere" / RESULT_DIRECTORY / GEN
            return original(path, *args, **kwargs)

        with patch.object(Path, "resolve", disturbed):
            survivors, total = _inspect(manager, "owner")
        assert [name for name, _, _ in survivors] == [name for name in everything if name not in dropped]
        assert total == kept_total
    finally:
        if kind == "link":
            _remove_alias(target)


def test_ordinary_walk_does_not_enter_a_directory_that_resolves_to_another_directory(tmp_path: Path) -> None:
    """A directory is entered only if the resolution that was checked is the very object its scan entry named."""
    manager = WorkspaceManager(tmp_path / "ws")
    base = manager.resolve("owner", create=True)
    (base / "a").mkdir()
    (base / "a" / "a.txt").write_bytes(b"aa")
    (base / "b").mkdir()
    (base / "b" / "b.txt").write_bytes(b"bbb")
    assert [name for name, _, _ in _inspect(manager, "owner")[0]] == ["a", "b", "a/a.txt", "b/b.txt"]  # premise
    original = Path.resolve

    def misdirected(path: Path, *args: Any, **kwargs: Any) -> Path:
        return original(base / "a") if path == base / "b" else original(path, *args, **kwargs)

    with patch.object(Path, "resolve", misdirected):
        listing, total = _inspect(manager, "owner")
    assert [name for name, _, _ in listing] == ["a", "b", "a/a.txt"] and total == 2


# ---- a directory replaced, between its check and its listing, by an alias to the very same object ----

_INJECTED_LSTAT = {
    # What ``os.lstat`` is made to report for the checked directory (every platform), while ``os.stat`` still
    # names the admitted object: a reparse point, another identity, or something that is not a directory.
    "injected_reparse_point": lambda fields: {**fields, "st_file_attributes": stat.FILE_ATTRIBUTE_REPARSE_POINT},
    "injected_other_identity": lambda fields: {**fields, "st_ino": fields["st_ino"] + 1},
    "injected_not_a_directory": lambda fields: {**fields, "st_mode": stat.S_IFREG | 0o644},
}
_SAME_OBJECT_KINDS = [
    pytest.param("junction", marks=pytest.mark.skipif(
        sys.platform != "win32", reason="AD-1240: a directory junction is Windows-only",
    )),
    pytest.param("symlink", marks=pytest.mark.skipif(
        sys.platform == "win32",
        reason="AD-1240: an unprivileged directory symlink is a POSIX premise (Windows needs a privilege)",
    )),
    *_INJECTED_LSTAT,
]
_SAME_OBJECT_LISTING = [
    ("ordinary", True, 0), ("plain.txt", False, 5), ("ordinary/manifest.json", False, 2),
    ("ordinary/outline.json", False, 2), ("ordinary/payload.jsonl", False, len(PRIVATE_BYTES)),
]


class _SameObjectScene:
    """An owner folder whose checked directory ``ordinary`` is replaced by an alias to that very object.

    Real kinds (a junction on Windows, a symlink on POSIX): the directory is moved into the namespace and an alias
    takes its place, so ``os.stat`` still reports the admitted identity and only ``os.lstat`` describes the alias.
    Injected kinds (every platform): nothing on disk changes; ``os.lstat`` reports what it would for such an alias,
    once per walk. ``moment`` is where the replacement happens: ``resolved`` (just after the directory was checked,
    so the alias is there when the walk first observes it) or ``scanned`` (just before its listing is taken, so
    only the observation after the listing can see it).
    """

    def __init__(self, tmp_path: Path, kind: str, moment: str, owner: str = "owner") -> None:
        self.manager = WorkspaceManager(tmp_path / "ws")
        self.base = self.manager.resolve(owner, create=True)
        self.named = self.base / "ordinary"
        self.named.mkdir()
        (self.named / "payload.jsonl").write_bytes(PRIVATE_BYTES)
        (self.named / "outline.json").write_bytes(b"{}")
        (self.named / "manifest.json").write_bytes(b"{}")
        (self.base / "plain.txt").write_bytes(b"plain")
        self.moved = self.base / RESULT_DIRECTORY / GEN / DIGEST / ARTIFACT_ID
        self.moved.parent.mkdir(parents=True)
        self.kind, self.moment = kind, moment
        self.premises: list[tuple[bool, bool]] = []
        self.scans: list[Path] = []
        info = os.lstat(self.named)
        self.admitted = (info.st_dev, info.st_ino)
        self._falsify_next = self._swapped = False

    def reported(self, info: os.stat_result) -> SimpleNamespace:
        """What ``os.lstat`` is made to report for ``ordinary`` instead of ``info`` (injected kinds)."""
        fields = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
        return SimpleNamespace(**_INJECTED_LSTAT[self.kind](fields))

    def observe(self) -> tuple[bool, bool]:
        """(``os.stat`` still names the admitted object, ``os.lstat`` still shows it as a real directory)."""
        followed, seen = os.stat(self.named), os.lstat(self.named)
        if self.kind in _INJECTED_LSTAT:
            seen = self.reported(seen)
        real_directory = stat.S_ISDIR(seen.st_mode) and not is_reparse_point(seen)
        return (
            (followed.st_dev, followed.st_ino) == self.admitted,
            real_directory and (seen.st_dev, seen.st_ino) == self.admitted,
        )

    def reach(self, moment: str) -> None:
        """The walk is at ``moment`` with ``ordinary``: replace it (real kinds, once) or arm the falsified lstat."""
        if moment != self.moment:
            return
        if self.kind in _INJECTED_LSTAT:
            self._falsify_next = True
        elif not self._swapped:
            self.named.rename(self.moved)
            (_make_junction if self.kind == "junction" else _make_symlink)(self.named, self.moved)
            self._swapped = True  # only once the alias is in place, so a failed attempt is not "undone" afterwards
        self.premises.append(self.observe())

    def lstat(self, path: Any, info: os.stat_result) -> Any:
        """``info``, or (injected kinds) what the walk's next ``lstat`` of ``ordinary`` is made to report."""
        if self._falsify_next and Path(path) == self.named:
            self._falsify_next = False
            return self.reported(info)
        return info

    @contextmanager
    def substituting(self, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
        """Run walks in which ``ordinary`` is replaced at ``moment``; a real replacement is undone afterwards."""
        original, scene = Path.resolve, self

        def resolving(path: Path, *args: Any, **kwargs: Any) -> Path:
            result = original(path, *args, **kwargs)
            if path == scene.named:
                scene.reach("resolved")
            return result

        try:
            with monkeypatch.context() as change, patch.object(Path, "resolve", resolving):
                change.setattr(workspace_module, "os", _SubstitutingOs(self))
                yield
        finally:
            if self._swapped:
                _remove_alias(self.named)
                self.moved.rename(self.named)


class _SubstitutingOs:
    """The ``os`` module as the inspection walk sees it, with ``scandir`` and ``lstat`` of ``ordinary`` watched."""

    def __init__(self, scene: _SameObjectScene) -> None:
        self._scene = scene

    def __getattr__(self, name: str) -> Any:
        return getattr(os, name)

    def scandir(self, path: Any, *args: Any, **kwargs: Any) -> Any:
        if Path(path) == self._scene.named:
            self._scene.scans.append(Path(path))
            self._scene.reach("scanned")
        return os.scandir(path, *args, **kwargs)

    def lstat(self, path: Any, *args: Any, **kwargs: Any) -> Any:
        return self._scene.lstat(path, os.lstat(path, *args, **kwargs))


@pytest.mark.parametrize("moment", ["resolved", "scanned"])
@pytest.mark.parametrize("kind", _SAME_OBJECT_KINDS)
@pytest.mark.parametrize("operation", ["list", "size"])
def test_ordinary_walk_does_not_enter_a_directory_replaced_by_an_alias_to_the_same_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str, kind: str, moment: str,
) -> None:
    """AD-1240 review A2, finding 1: ``os.stat`` follows an alias to the very object that was checked.

    That object now sits inside the namespace, so its followed identity still matches; only a no-follow
    observation shows that what is at the path is no longer the real directory that was admitted.
    """
    scene = _SameObjectScene(tmp_path, kind, moment)
    # Premise: undisturbed, the directory's files are ordinary and are listed and counted.
    assert _inspect(scene.manager, "owner") == (_SAME_OBJECT_LISTING, 5 + 2 + 2 + len(PRIVATE_BYTES))
    with scene.substituting(monkeypatch):
        outcome = (
            [entry.name for entry in scene.manager.list_files("owner")]
            if operation == "list" else scene.manager.total_bytes("owner")
        )
    # Premise: the replacement happened, and then ``os.stat`` named the admitted object while ``os.lstat`` did not.
    assert scene.premises and set(scene.premises) == {(True, False)}, scene.premises
    # Outcome: ``ordinary`` was listed when it was checked; nothing it now leads to was listed or counted. An
    # alias that was there to be seen first was refused before it was read; one that arrived just before the
    # listing was taken (read once, so the listing existed) had that listing discarded.
    assert outcome == (["ordinary", "plain.txt"] if operation == "list" else 5)
    assert scene.scans == ([] if moment == "resolved" else [scene.named]), scene.scans


@pytest.mark.parametrize("kind", _SAME_OBJECT_KINDS)
def test_overview_route_does_not_list_a_directory_replaced_by_an_alias_to_the_same_object(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str,
) -> None:
    """The same replacement, through the real FastAPI overview route (which lists and then sizes the folder)."""
    agent = _agent("agent-a", "Probe")
    client, _, _ = _route_client(tmp_path, monkeypatch, agent)
    scene = _SameObjectScene(tmp_path, kind, "resolved", WorkspaceManager(tmp_path / "ws").key_for_agent(agent))
    url = f"/api/agent/{agent.id}/workspace"
    try:
        control = client.get(url)  # premise: undisturbed, the real route lists the directory's files too
        assert control.status_code == 200 and control.json()["owner"] == scene.base.name
        assert [(item["name"], item["size_bytes"]) for item in control.json()["files"]] == [
            (name, size) for name, _, size in _SAME_OBJECT_LISTING
        ]
        with scene.substituting(monkeypatch):
            overview = client.get(url)
        assert scene.premises and set(scene.premises) == {(True, False)}, scene.premises
        assert overview.status_code == 200
        assert [(item["name"], item["size_bytes"]) for item in overview.json()["files"]] == [
            ("ordinary", 0), ("plain.txt", 5),
        ]
        assert overview.json()["total_bytes"] == 5
        assert scene.scans == [], "refused before it was read, in both of the route's walks"
    finally:
        client.close()


def test_links_leading_outside_the_owner_folder_are_pruned(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "ws")
    base = manager.resolve("owner", create=True)
    (base / "ordinary.txt").write_bytes(b"ordinary")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "big.bin").write_bytes(b"b" * 100)
    before = _inspect(manager, "owner")
    assert before == ([("ordinary.txt", False, 8)], 8)  # premise
    link = base / "shortcut"
    _directory_alias(link, outside)
    try:
        # Premise: the link works, and leads somewhere that is neither reserved nor under the owner folder.
        assert not is_workspace_result_path(link.resolve()) and not link.resolve().is_relative_to(base)
        assert (link / "big.bin").read_bytes() == b"b" * 100
        assert _inspect(manager, "owner") == before
    finally:
        _remove_alias(link)


_LINKS_INSIDE_LISTING = [
    # A link is one directory entry of size 0, whatever its name, and is never entered or sized, so its target's
    # files are reached once, through the real directory. The ``.venv`` entry used to be pinned at the size of its
    # target (12 here): a link named like an opaque directory was sized by walking its target, which scanned the
    # target tree and resolved its subdirectories a second time (AD-1240 review A2, finding 2).
    (".venv", True, 0), ("link-dir", True, 0), ("real-dir", True, 0), ("venv-real", True, 0),
    ("real-dir/inner.txt", False, 5), ("venv-real/pkg", True, 0), ("venv-real/mod.py", False, 12),
    ("venv-real/pkg/deep.py", False, 4),
]
_LINKS_INSIDE_TOTAL = 5 + 12 + 4


@contextmanager
def _links_inside_the_owner_folder(manager: WorkspaceManager) -> Iterator[Path]:
    """An owner folder holding two directory links to ordinary directories inside it (one opaquely named).

    The opaquely named link's target has a nested directory, so a second walk of it would show in the counts.
    """
    base = manager.resolve("owner", create=True)
    (base / "real-dir").mkdir()
    (base / "real-dir" / "inner.txt").write_bytes(b"inner")
    (base / "venv-real" / "pkg").mkdir(parents=True)
    (base / "venv-real" / "mod.py").write_bytes(b"m" * 12)
    (base / "venv-real" / "pkg" / "deep.py").write_bytes(b"d" * 4)
    plain_link, venv_link = base / "link-dir", base / ".venv"
    _directory_alias(plain_link, base / "real-dir")
    _directory_alias(venv_link, base / "venv-real")
    try:
        # Premise: both links work and lead to ordinary directories inside the owner folder.
        assert (plain_link / "inner.txt").read_bytes() == b"inner" and (venv_link / "mod.py").read_bytes() == b"m" * 12
        assert plain_link.resolve().is_relative_to(base) and venv_link.resolve().is_relative_to(base)
        # Premise: each is a real link (a symlink or a junction), and the opaquely named one leads to a directory
        # that has a nested directory with a file in it.
        assert is_reparse_point(os.lstat(plain_link)) and is_reparse_point(os.lstat(venv_link))
        assert venv_link.resolve() == base / "venv-real" and (venv_link / "pkg" / "deep.py").read_bytes() == b"d" * 4
        yield base
    finally:
        _remove_alias(venv_link)
        _remove_alias(plain_link)


def _assert_links_cost_nothing(manager: WorkspaceManager, base: Path) -> None:
    """Each inspection scans a link's target once overall (as the real directory) and resolves its subdirectory once."""
    target, nested = base / "venv-real", base / "venv-real" / "pkg"
    operations = {
        "list_files": lambda: manager.list_files("owner", limit=10_000),
        "total_bytes": lambda: manager.total_bytes("owner"),
    }
    for name, operation in operations.items():
        with _count_resolves() as resolved, patch.object(os, "scandir", wraps=os.scandir) as scans:
            operation()
        scanned = Counter(Path(call.args[0]) for call in scans.call_args_list)
        assert scanned[base / "real-dir"] == 1, (name, "premise: an ordinary directory is scanned once", scanned)
        assert (scanned[target], scanned[nested]) == (1, 1), (name, "a link's target is not scanned again", scanned)
        assert resolved[nested] == 1, (name, "nor are its subdirectories resolved again", resolved)


def test_links_inside_the_owner_folder_are_listed_once_and_never_entered(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "ws")
    with _links_inside_the_owner_folder(manager) as base:
        assert _inspect(manager, "owner") == (_LINKS_INSIDE_LISTING, _LINKS_INSIDE_TOTAL)
        _assert_links_cost_nothing(manager, base)


def test_links_are_never_entered_on_a_filesystem_without_identities(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No inode numbers (identity (0, 0) everywhere) must not turn a link into an enterable directory."""
    manager = WorkspaceManager(tmp_path / "ws")
    with _links_inside_the_owner_folder(manager) as base:
        monkeypatch.setattr(workspace_module, "_identity", lambda info: (0, 0))
        assert _inspect(manager, "owner") == (_LINKS_INSIDE_LISTING, _LINKS_INSIDE_TOTAL)
        _assert_links_cost_nothing(manager, base)


# ---- a directory that is something else when the walk observes it a second time ----
# A scan entry classifies a real directory first, from its own stat; the walk then reads it again with ``os.lstat``
# (a scan entry's stat carries no identity on Windows). AD-1240 review R4, finding 1: that fresh observation replaced
# ``info`` but not the classification, so a directory that had become a link, or a file, since the scan was still
# typed, sized and entered as the real directory it no longer was.

# Given the real ``os.lstat`` of the path, as a call: what the walk is told instead.
_Observed = Callable[[Callable[[], os.stat_result]], Any]


def _as_reported(info: os.stat_result, **changes: Any) -> SimpleNamespace:
    """``info`` as the same object would have reported it with ``changes``: its own ``st_*`` fields, then those."""
    fields = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
    return SimpleNamespace(**{**fields, **changes})


def _said(info: Any) -> tuple[bool, bool]:
    """What one observation of a path says: ``(a directory, a link)``, the two bits a walk classifies it by."""
    return stat.S_ISDIR(info.st_mode), is_reparse_point(info)


class _FreshObservationOs:
    """The ``os`` module as the walk sees it, with the fresh ``lstat`` of one directory handed to ``observed``.

    ``scan_said`` is what the scan entry for ``named`` said, once per walk (every walk begins by scanning the owner
    folder); ``fresh_said`` is what the walk was then told by its fresh ``lstat`` of that path (the first ``lstat`` of
    it in a walk). ``scans`` lists every directory that was scanned.
    """

    def __init__(self, folder: Path, named: Path, observed: _Observed) -> None:
        self._folder, self._named, self._observed = folder, named, observed
        self._due = False
        self.scans: list[Path] = []
        self.scan_said: list[tuple[bool, bool]] = []
        self.fresh_said: list[tuple[bool, bool]] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(os, name)

    def scandir(self, path: Any, *args: Any, **kwargs: Any) -> Any:
        with os.scandir(path, *args, **kwargs) as scanned:
            entries = list(scanned)
        self.scans.append(Path(path))
        if Path(path) == self._folder:
            self._due = True
            self.scan_said += [
                _said(entry.stat(follow_symlinks=False)) for entry in entries if entry.name == self._named.name
            ]
        return nullcontext(entries)

    def lstat(self, path: Any, *args: Any, **kwargs: Any) -> Any:
        if not (self._due and Path(path) == self._named):
            return os.lstat(path, *args, **kwargs)
        self._due = False
        fresh = self._observed(lambda: os.lstat(path, *args, **kwargs))
        self.fresh_said.append(_said(fresh))
        return fresh


_FRESH_LISTING = [
    # ``.venv`` is an opaque real directory (listed once, sized by walking it: 12 + 4, and counted in the total); the
    # others are ordinary ones, listed and entered. ``venv-real`` is what a link named ``.venv`` leads to.
    (".venv", True, 16), ("real-dir", True, 0), ("venv-real", True, 0), ("plain.txt", False, 5),
    ("real-dir/inner.txt", False, 5), ("venv-real/pkg", True, 0), ("venv-real/mod.py", False, 12),
    ("venv-real/pkg/deep.py", False, 4),
]
_FRESH_TOTAL = 16 + 5 + 5 + 16
_FRESH_LINK_KINDS = [
    "injected_reparse_point",
    pytest.param("junction", marks=pytest.mark.skipif(
        sys.platform != "win32", reason="AD-1240: a directory junction is Windows-only",
    )),
]


def _fresh_observation_folder(tmp_path: Path) -> tuple[WorkspaceManager, Path]:
    """An owner folder of real directories only: ``.venv`` and ``venv-real`` (alike but for their bytes), ``real-dir``.

    ``.venv`` and ``venv-real`` each hold ``mod.py`` (12 bytes) and a nested ``pkg/deep.py`` (4 bytes), so walking
    either is worth 16 bytes, and a second walk of it would resolve its nested directory a second time.
    """
    manager = WorkspaceManager(tmp_path / "ws")
    base = manager.resolve("owner", create=True)
    for name, fill in ((".venv", b"v"), ("venv-real", b"m")):
        (base / name / "pkg").mkdir(parents=True)
        (base / name / "mod.py").write_bytes(fill * 12)
        (base / name / "pkg" / "deep.py").write_bytes(fill * 4)
    (base / "real-dir").mkdir()
    (base / "real-dir" / "inner.txt").write_bytes(b"inner")
    (base / "plain.txt").write_bytes(b"plain")
    return manager, base


@contextmanager
def _link_at_fresh_observation(kind: str, base: Path, aside: Path) -> Iterator[_Observed]:
    """``.venv`` is a link when the walk reads it a second time: reported as one (injected), or really replaced.

    The real replacement (a junction to ``venv-real``) is made at that observation and undone on exit; the
    real directory it replaced waits in ``aside``.
    """
    named, target = base / ".venv", base / "venv-real"
    if kind != "junction":
        yield lambda lstat: _as_reported(lstat(), st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT)
        return

    def replacing(lstat: Callable[[], os.stat_result]) -> os.stat_result:
        named.rename(aside)
        _make_junction(named, target)
        assert (named / "mod.py").read_bytes() == b"m" * 12, "premise: the junction leads to the ordinary directory"
        return lstat()

    try:
        yield replacing
    finally:
        if aside.exists():
            if os.path.lexists(named):
                _remove_alias(named)
            aside.rename(named)


def _second_observation_walk(
    manager: WorkspaceManager, base: Path, name: str, operation: str, observed: _Observed,
) -> SimpleNamespace:
    """One inspection (``list`` or ``size``) in which the walk's fresh ``lstat`` of ``name`` is handed to ``observed``.

    Returns what the walk produced (``outcome``: its listing or its total), what it cost (``resolved``, ``scanned``)
    and what it was told (``scan_said``, ``fresh_said``).
    """
    view = _FreshObservationOs(base, base / name, observed)
    with patch.object(workspace_module, "os", view), _count_resolves() as resolved:
        outcome = (
            [(item.name, item.is_dir, item.size_bytes) for item in manager.list_files("owner", limit=10_000)]
            if operation == "list" else manager.total_bytes("owner")
        )
    return SimpleNamespace(
        outcome=outcome, resolved=resolved, scanned=Counter(view.scans),
        scan_said=view.scan_said, fresh_said=view.fresh_said,
    )


@pytest.mark.parametrize("operation", ["list", "size"])
@pytest.mark.parametrize("kind", _FRESH_LINK_KINDS)
def test_a_directory_seen_as_a_link_at_its_fresh_observation_is_listed_once_and_never_sized_or_entered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str, kind: str,
) -> None:
    """A real directory that is a link by the time the walk reads it again is a link, whatever the scan entry said.

    On a filesystem without inode numbers nothing else refuses to walk it: a ``.venv`` that was sized or entered
    would be a second walk of its target (a listed size of 16 instead of 0, a total of 42 instead of 26, the
    target scanned twice and its nested directory resolved twice).
    """
    manager, base = _fresh_observation_folder(tmp_path)
    named, target, nested = base / ".venv", base / "venv-real", base / "venv-real" / "pkg"
    monkeypatch.setattr(workspace_module, "_identity", lambda info: (0, 0))
    # Premise: undisturbed, ``.venv`` is an opaque real directory: listed once, sized by walking it, and counted.
    assert _inspect(manager, "owner") == (_FRESH_LISTING, _FRESH_TOTAL)
    with _link_at_fresh_observation(kind, base, tmp_path / "aside") as observed:
        walk = _second_observation_walk(manager, base, ".venv", operation, observed)
    # Premise: the scan entry said "a directory, not a link"; the fresh observation of the same path said "a link".
    assert walk.scan_said == [(True, False)] and walk.fresh_said == [(True, True)], (walk.scan_said, walk.fresh_said)
    assert walk.outcome == ([(".venv", True, 0), *_FRESH_LISTING[1:]] if operation == "list" else 5 + 5 + 16)
    assert walk.scanned[named] == 0, ("a link is never entered", walk.scanned)
    assert (walk.scanned[target], walk.scanned[nested]) == (1, 1), ("its target is scanned once", walk.scanned)
    assert (walk.resolved[named], walk.resolved[nested]) == (1, 1), ("each resolved once", walk.resolved)


@pytest.mark.parametrize("operation", ["list", "size"])
@pytest.mark.parametrize("name", [".venv", "real-dir"])
def test_a_directory_still_a_directory_at_its_fresh_observation_is_sized_and_entered_as_before(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str, name: str,
) -> None:
    """The control: the fresh observation agrees with the scan entry, and nothing about the directories changes."""
    manager, base = _fresh_observation_folder(tmp_path)
    monkeypatch.setattr(workspace_module, "_identity", lambda info: (0, 0))
    walk = _second_observation_walk(manager, base, name, operation, lambda lstat: lstat())
    # Premise: the fresh observation was reached, and what it said was what the scan entry had said.
    assert walk.scan_said == [(True, False)] and walk.fresh_said == [(True, False)], (walk.scan_said, walk.fresh_said)
    assert walk.outcome == (_FRESH_LISTING if operation == "list" else _FRESH_TOTAL)
    top_level = [base / name for name in (".venv", "real-dir", "venv-real")]
    directories = [base, *top_level, base / ".venv" / "pkg", base / "venv-real" / "pkg"]
    assert walk.scanned == Counter(directories), ("every directory is scanned once, the opaque one too", walk.scanned)
    assert max(walk.resolved.values()) == 1, ("no path is resolved twice", walk.resolved)


@pytest.mark.parametrize("operation", ["list", "size"])
def test_a_directory_seen_as_a_file_at_its_fresh_observation_is_listed_as_a_plain_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str,
) -> None:
    """A real directory that is a file by the time the walk reads it again is that file: sized from the fresh stat."""
    manager, base = _fresh_observation_folder(tmp_path)
    named = base / ".venv"
    monkeypatch.setattr(workspace_module, "_identity", lambda info: (0, 0))
    assert _inspect(manager, "owner") == (_FRESH_LISTING, _FRESH_TOTAL)  # premise: undisturbed, an opaque directory

    def as_a_file(lstat: Callable[[], os.stat_result]) -> SimpleNamespace:
        return _as_reported(lstat(), st_mode=stat.S_IFREG | 0o644, st_size=31)

    walk = _second_observation_walk(manager, base, ".venv", operation, as_a_file)
    # Premise: the scan entry said "a directory, not a link"; the fresh observation of the same path said "a file".
    assert walk.scan_said == [(True, False)] and walk.fresh_said == [(False, False)], (walk.scan_said, walk.fresh_said)
    listing = [
        ("real-dir", True, 0), ("venv-real", True, 0), (".venv", False, 31), ("plain.txt", False, 5),
        *_FRESH_LISTING[4:],
    ]
    assert walk.outcome == (listing if operation == "list" else 31 + 5 + 5 + 16)
    assert walk.scanned[named] == 0 and walk.resolved[named] == 0, (
        "a plain file is neither entered nor resolved", walk.scanned, walk.resolved,
    )


def test_dangling_links_are_dropped(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "ws")
    base = manager.resolve("owner", create=True)
    (base / "keep.txt").write_bytes(b"keep")
    gone = base / "gone-target"
    gone.mkdir()
    link = base / "dangling"
    _directory_alias(link, gone)
    try:
        assert [name for name, _, _ in _inspect(manager, "owner")[0]] == ["dangling", "gone-target", "keep.txt"]  # premise
        gone.rmdir()
        assert not link.exists(), "premise: the link now leads nowhere"
        assert _inspect(manager, "owner") == ([("keep.txt", False, 4)], 4)
    finally:
        _remove_alias(link)


@pytest.mark.parametrize("leads", ["inside", "outside", "reserved", "missing"])
def test_a_file_link_is_sized_from_its_checked_target_or_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, leads: str,
) -> None:
    """Injected (every platform): a file symlink needs a privilege on Windows, so the link is simulated."""
    manager = WorkspaceManager(tmp_path / "ws")
    base = manager.resolve("owner", create=True)
    (base / "plain.txt").write_bytes(b"p" * 4)
    (base / "target.txt").write_bytes(b"t" * 7)
    marked = base / "marked.txt"
    marked.write_bytes(b"m" * 99)
    outside = tmp_path / "outside.txt"
    outside.write_bytes(b"o" * 50)
    assert _inspect(manager, "owner") == (
        [("marked.txt", False, 99), ("plain.txt", False, 4), ("target.txt", False, 7)], 110,
    )  # premise: before it is a link, it is a plain file of its own size
    real_is_reparse_point = workspace_module.is_reparse_point
    monkeypatch.setattr(
        workspace_module, "is_reparse_point",
        lambda info: real_is_reparse_point(info) or info.st_size == 99,
    )
    resolves = {
        "inside": base / "target.txt", "outside": outside,
        "reserved": tmp_path / "elsewhere" / RESULT_DIRECTORY / GEN / "payload.jsonl",
        "missing": base / "no-such-entry",
    }
    original = Path.resolve
    resolved: list[Path] = []

    def leading(path: Path, *args: Any, **kwargs: Any) -> Path:
        if path == marked:
            resolved.append(path)
            return resolves[leads]
        return original(path, *args, **kwargs)

    with patch.object(Path, "resolve", leading):
        listing, total = _inspect(manager, "owner")
    assert len(resolved) == 2, "the link is resolved once per walk, and nothing else is"
    if leads == "inside":
        assert listing == [("marked.txt", False, 7), ("plain.txt", False, 4), ("target.txt", False, 7)]
        assert total == 18
    else:
        assert listing == [("plain.txt", False, 4), ("target.txt", False, 7)] and total == 11


@pytest.mark.parametrize("name", [".TOOL-RESULTS", ".Tool-Results"])
@pytest.mark.parametrize("kind", ["directory", "alias"])
def test_case_variants_of_the_namespace_name_are_pruned_by_name(tmp_path: Path, name: str, kind: str) -> None:
    manager = WorkspaceManager(tmp_path / "ws")
    base = manager.resolve("owner", create=True)
    (base / "ordinary.txt").write_bytes(b"ordinary")
    (base / "plain-dir").mkdir()
    (base / "plain-dir" / "file.txt").write_bytes(b"f" * 15)
    before = _inspect(manager, "owner")
    assert before == (
        [("plain-dir", True, 0), ("ordinary.txt", False, 8), ("plain-dir/file.txt", False, 15)], 23,
    )  # premise
    variant = base / name
    if kind == "directory":
        variant.mkdir()
        (variant / "inside.txt").write_bytes(b"i" * 9)
    else:
        _directory_alias(variant, base / "plain-dir")  # leads somewhere ordinary, so only its name reserves it
    try:
        assert (variant / ("inside.txt" if kind == "directory" else "file.txt")).is_file()  # premise: it holds files
        assert _inspect(manager, "owner") == before
        assert manager.resolve_file("owner", f"{name}/inside.txt") is None
    finally:
        if kind == "alias":
            _remove_alias(variant)


def test_hard_linked_files_are_listed_and_counted_as_ordinary_files(tmp_path: Path) -> None:
    """The documented residual: a hard link made outside ProbOS is an ordinary file, and uv-style venvs rely on that."""
    manager = WorkspaceManager(tmp_path / "ws")
    base = manager.resolve("owner", create=True)
    (base / "original.txt").write_bytes(b"shared")
    os.link(base / "original.txt", base / "linked.txt")
    assert (base / "original.txt").stat().st_nlink == 2  # premise
    assert _inspect(manager, "owner") == ([("linked.txt", False, 6), ("original.txt", False, 6)], 12)
    assert manager.resolve_file("owner", "linked.txt") == base / "linked.txt"


class _FaultyOs:
    """The ``os`` module, except that one directory cannot be scanned and one scan entry cannot be statted."""

    class _Scan:
        def __init__(self, scan: Any, unstattable: str) -> None:
            self._scan, self._unstattable = scan, unstattable

        def __enter__(self) -> "_FaultyOs._Scan":
            return self

        def __exit__(self, *exc: Any) -> None:
            self._scan.close()

        def __iter__(self) -> Iterator[Any]:
            for entry in self._scan:
                yield _FaultyOs._Entry(entry) if entry.name == self._unstattable else entry

    class _Entry:
        def __init__(self, entry: Any) -> None:
            self._entry = entry

        def __getattr__(self, name: str) -> Any:
            return getattr(self._entry, name)

        def stat(self, *args: Any, **kwargs: Any) -> os.stat_result:
            raise PermissionError(errno.EACCES, "fixture: cannot be statted", self._entry.path)

    def __init__(self, unreadable: Path, unstattable: str) -> None:
        self._unreadable, self._unstattable = unreadable, unstattable

    def __getattr__(self, name: str) -> Any:
        return getattr(os, name)

    def scandir(self, path: Any, *args: Any, **kwargs: Any) -> Any:
        if os.fspath(path) == str(self._unreadable):
            raise PermissionError(errno.EACCES, "fixture: cannot be scanned", os.fspath(path))
        return _FaultyOs._Scan(os.scandir(path, *args, **kwargs), self._unstattable)


def test_walk_degrades_around_a_directory_it_cannot_scan_and_an_entry_it_cannot_stat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = WorkspaceManager(tmp_path / "ws")
    base = manager.resolve("owner", create=True)
    (base / "a").mkdir()
    (base / "a" / "good.txt").write_bytes(b"g" * 3)
    (base / "a" / "bad.txt").write_bytes(b"b" * 5)
    (base / "b").mkdir()
    (base / "b" / "hidden.txt").write_bytes(b"h" * 7)
    assert _inspect(manager, "owner") == (
        [("a", True, 0), ("b", True, 0), ("a/bad.txt", False, 5), ("a/good.txt", False, 3), ("b/hidden.txt", False, 7)],
        15,
    )  # premise
    monkeypatch.setattr(workspace_module, "os", _FaultyOs(base / "b", "bad.txt"))
    assert _inspect(manager, "owner") == ([("a", True, 0), ("b", True, 0), ("a/good.txt", False, 3)], 3)


def test_ordinary_walk_skips_a_directory_that_cannot_be_examined_when_entered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = WorkspaceManager(tmp_path / "ws")
    base = manager.resolve("owner", create=True)
    for name in ("a", "b"):
        (base / name).mkdir()
        (base / name / f"{name}.txt").write_bytes(b"xx")

    class _VanishingOs:
        """The ``os`` module, except that one directory cannot be examined when it is entered.

        AD-1240 review A2: a directory is now examined at entry with ``os.lstat``, because it must be seen without
        following a link. This fixture used to inject the failure through ``os.stat``, which the walk no longer
        calls there, so it would have injected nothing. The scan entry's own ``lstat`` of the directory is the
        first call of a walk and succeeds; every later one in the same walk fails.
        """

        def __init__(self) -> None:
            self.examinations, self.failures = 0, 0

        def __getattr__(self, name: str) -> Any:
            return getattr(os, name)

        def scandir(self, path: Any, *args: Any, **kwargs: Any) -> Any:
            if os.fspath(path) == str(base):  # every walk begins with the owner folder
                self.examinations = 0
            return os.scandir(path, *args, **kwargs)

        def lstat(self, path: Any, *args: Any, **kwargs: Any) -> os.stat_result:
            if os.fspath(path) == str(base / "b"):
                self.examinations += 1
                if self.examinations > 1:
                    self.failures += 1
                    raise FileNotFoundError(errno.ENOENT, "fixture: vanished", os.fspath(path))
            return os.lstat(path, *args, **kwargs)

    assert [entry.name for entry in manager.list_files("owner")] == ["a", "b", "a/a.txt", "b/b.txt"]  # premise
    vanishing = _VanishingOs()
    monkeypatch.setattr(workspace_module, "os", vanishing)
    assert [entry.name for entry in manager.list_files("owner")] == ["a", "b", "a/a.txt"]
    assert manager.total_bytes("owner") == 2
    assert vanishing.failures == 2, "premise: the directory could not be examined in either walk when it was entered"


def test_inspection_degrades_instead_of_raising_when_the_walk_itself_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = WorkspaceManager(tmp_path / "ws")
    base = manager.resolve("owner", create=True)
    (base / "a.txt").write_bytes(b"aaa")
    (base / "b.txt").write_bytes(b"bbb")
    real = workspace_module._ordinary_entries

    def failing_after_one(*args: Any, **kwargs: Any) -> Iterator[Any]:
        yield next(real(*args, **kwargs))
        raise OSError("fixture: the walk failed")

    monkeypatch.setattr(workspace_module, "_ordinary_entries", failing_after_one)
    assert [entry.name for entry in manager.list_files("owner")] == ["a.txt"]
    assert manager.total_bytes("owner") == 3


# ---- M2: the real routes, over a real publication ----


@pytest.mark.asyncio
async def test_legacy_routes_refuse_reserved_namespace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R1-2: the legacy workspace routes never serve, write or propose inside ``.tool-results``.

    Agent B publishes a real result. Agent A shares B's owner folder (same sanitized
    key, different identity digest), so the typed reader refuses A. The four legacy
    routes must refuse the namespace for everyone, with the same 400, at the moment
    the artifact is committed, when its 24 h retention ends, and at the last instant
    before its generation may be reaped, while the bytes are still on disk.
    """
    agent_a, agent_b = _agent("agent-a"), _agent("agent-b")
    harness = make_store(tmp_path / "ws")
    store = harness.store
    binding_a = store.bind_agent(agent_a.id, agent_a)
    binding_b = store.bind_agent(agent_b.id, agent_b)
    manager = WorkspaceManager(tmp_path / "ws")
    owner = binding_a.owner_key
    base = manager.resolve(owner)
    client = None
    aliases: list[Path] = []
    await store.start()
    try:
        canonical = "PRIVATE_OWNER_B_" * 1000
        reference = await store.store_tool_result(binding_b, _capture(canonical))
        payload = Path(reference.path)
        raw = payload.read_bytes()
        relative = payload.relative_to(base).as_posix()
        # Premises: a real publication, the same owner folder for two identities, and a typed
        # reader that already refuses A, so the legacy routes are the only way in.
        assert binding_a.owner_key == binding_b.owner_key and binding_a.owner_digest != binding_b.owner_digest
        assert relative == f"{RESULT_DIRECTORY}/{GEN}/{binding_b.owner_digest}/{payload.parent.name}/payload.jsonl"
        assert "".join(json.loads(line) for line in raw.splitlines()) == canonical
        with pytest.raises(WorkspaceResultError, match="workspace_owner_invalid"):
            await store.read_tool_result_slice(binding_a, reference.path, 0, 10)
        (base / "ordinary.txt").write_text("ordinary", encoding="utf-8")
        assert len(raw) > len("ordinary"), "the namespace holds bytes that would show in a size"
        alias = base / "result-alias"
        _directory_alias(alias, payload.parent)
        aliases.append(alias)
        client, runtime, suggestions = _route_client(tmp_path, monkeypatch, agent_a)
        runtime.submit_write_with_consensus = AsyncMock(return_value={"committed": True})
        stale = suggestions.add(owner, relative, "stale replacement", "author")
        url = f"/api/agent/{agent_a.id}/workspace"
        before = sorted(str(path) for path in (tmp_path / "ws").rglob("*"))
        clocks = (
            ("committed_at", reference.committed_at),
            ("committed_at + R", reference.committed_at + RESULT_RETENTION_SECONDS),
            ("generation_expiry - 1", generation_expiry(GEN) - 1.0),
        )
        assert reference.expires_at == clocks[1][1]
        assert clocks[0][1] < clocks[1][1] < clocks[2][1] < generation_expiry(GEN)
        refused = (
            relative, "result-alias", "result-alias/payload.jsonl",
            RESULT_DIRECTORY, f"{RESULT_DIRECTORY.upper()}/{GEN}",
        )
        for label, now in clocks:
            harness.clock[0] = now
            if label == "committed_at":
                assert (await store.read_tool_result_slice(binding_b, reference.path, 0, 10)).text == canonical[:10]
            else:
                with pytest.raises(WorkspaceResultError, match="result_expired"):
                    await store.read_tool_result_slice(binding_b, reference.path, 0, 10)
            assert payload.read_bytes() == raw, "retention outlives the logical expiry on disk"
            with patch.object(suggestions, "add", wraps=suggestions.add) as add, \
                    patch.object(suggestions, "list", wraps=suggestions.list) as listing:
                for requested in refused:
                    assert client.get(url + "/file", params={"path": requested}).status_code == 400, (label, requested)
                    assert client.post(
                        url + "/file", json={"path": requested, "content": "no"},
                    ).status_code == 400, (label, requested)
                    assert client.get(
                        url + "/suggestions", params={"path": requested},
                    ).status_code == 400, (label, requested)
                    assert client.post(url + "/suggestions", json={
                        "path": requested, "content": "no", "author_id": "author",
                    }).status_code == 400, (label, requested)
                add.assert_not_called()
                listing.assert_not_called()
            runtime.submit_write_with_consensus.assert_not_awaited()
            assert suggestions.list(owner, relative) == [stale], label
            assert sorted(str(path) for path in (tmp_path / "ws").rglob("*")) == before, label
        assert [(item.name, item.size_bytes) for item in manager.list_files(owner)] == [("ordinary.txt", 8)]
        assert manager.total_bytes(owner) == 8
        overview = client.get(url)
        assert overview.status_code == 200
        assert [(item["name"], item["size_bytes"]) for item in overview.json()["files"]] == [("ordinary.txt", 8)]
        assert overview.json()["total_bytes"] == 8
        # Controls: the same routes serve ordinary files, so the refusals above are not a blanket failure.
        served = client.get(url + "/file", params={"path": "ordinary.txt"})
        assert served.status_code == 200 and served.json()["content"] == "ordinary"
        written = client.post(url + "/file", json={"path": "ordinary.txt", "content": "accepted"})
        assert written.status_code == 200 and written.json()["outcome"] == "committed"
        runtime.submit_write_with_consensus.assert_awaited_once()
        assert Path(runtime.submit_write_with_consensus.await_args.kwargs["path"]) == base / "ordinary.txt"
        proposed = client.post(url + "/suggestions", json={
            "path": "ordinary.txt", "content": "proposal", "author_id": "author",
        })
        assert proposed.status_code == 200
        assert client.get(
            url + "/suggestions", params={"path": "ordinary.txt"},
        ).json()["suggestions"] == [proposed.json()["suggestion"]]
        # Dismiss works by id and never touches a path, so a stale private suggestion can still be cleared.
        dismissed = client.post(url + f"/suggestions/{stale.id}/dismiss")
        assert dismissed.status_code == 200 and dismissed.json()["dismissed"] is True
        assert suggestions.list(owner, relative) == []
        assert payload.read_bytes() == raw
    finally:
        if client is not None:
            client.close()
        await store.stop()
        for link in reversed(aliases):
            _remove_alias(link)


@pytest.mark.asyncio
@pytest.mark.parametrize("expired", [False, True])
@pytest.mark.parametrize("public_owner", ["first", "second", "alias"])
async def test_r1_private_publication_is_confined_through_real_workspace_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, expired: bool, public_owner: str,
) -> None:
    assert tmp_path.is_absolute()
    harness = make_store(tmp_path / "ws")
    store = harness.store
    manager = WorkspaceManager(tmp_path / "ws")
    first = SimpleNamespace(id="first", callsign="Collide!")
    second = SimpleNamespace(id="second", callsign="Collide?")
    alias_agent = SimpleNamespace(id="alias", callsign="Alias owner")
    first_binding = store.bind_agent(first.id, first)
    second_binding = store.bind_agent(second.id, second)
    assert first_binding.owner_key == second_binding.owner_key
    assert first_binding.owner_digest != second_binding.owner_digest
    base = manager.resolve(second_binding.owner_key)
    assert manager.root.is_relative_to(tmp_path)
    await store.start()
    client = None
    aliases: list[Path] = []
    try:
        canonical = "private canonical body\n" * 900
        reference = await store.store_tool_result(second_binding, _capture(canonical))
        payload = Path(reference.path)
        raw_before = payload.read_bytes()
        assert "".join(json.loads(line) for line in raw_before.splitlines()) == canonical
        assert generation_of(reference.path) == GEN
        with pytest.raises(WorkspaceResultError, match="workspace_owner_invalid"):
            await store.read_tool_result_slice(first_binding, reference.path, 0, 17)
        assert (await store.read_tool_result_slice(second_binding, reference.path, 3, 91)).text == canonical[3:94]

        (base / "ordinary.txt").write_text("ordinary", encoding="utf-8")
        (base / ".venv").mkdir()
        (base / ".venv" / "visible.txt").write_bytes(b"venv")
        namespace_alias = base / "result-alias"
        _directory_alias(namespace_alias, payload.parent)
        aliases.append(namespace_alias)
        owner_alias = manager.resolve(manager.key_for_agent(alias_agent))
        _directory_alias(owner_alias, payload.parent)
        aliases.append(owner_alias)
        relative = payload.relative_to(base).as_posix()
        stale_path = "payload.jsonl" if public_owner == "alias" else relative
        agent = {"first": first, "second": second, "alias": alias_agent}[public_owner]
        client, runtime, suggestions = _route_client(tmp_path, monkeypatch, agent)
        assert Path(runtime.config.execution.workspace_root) == manager.root
        owner_key = manager.key_for_agent(agent)
        stale = suggestions.add(owner_key, stale_path, "stale replacement", "author")
        writes: list[tuple[str, str]] = []

        async def governed_write(*, path: str, content: str) -> dict[str, bool]:
            target = Path(path)
            assert target.is_absolute() and target.is_relative_to(tmp_path)
            writes.append((path, content))
            assert not is_workspace_result_path(target)
            target.write_text(content, encoding="utf-8")
            return {"committed": True}

        runtime.submit_write_with_consensus = governed_write
        if expired:
            harness.clock[0] = reference.expires_at
            with pytest.raises(WorkspaceResultError, match="result_expired"):
                await store.read_tool_result_slice(second_binding, reference.path, 0, 1)
            assert payload.exists(), "exercise logical expiry before physical deletion"
        url = f"/api/agent/{agent.id}/workspace"
        rejected = ["payload.jsonl", "new/sub/file.txt"] if public_owner == "alias" else [
            relative,
            "result-alias/payload.jsonl",
            "result-alias",
            "result-alias/../../../ordinary.txt",
            f"{RESULT_DIRECTORY}/../ordinary.txt",
            f"{RESULT_DIRECTORY}/new/sub/file.txt",
            f"{RESULT_DIRECTORY}/{GEN}/new/sub/file.txt",
        ]
        before_entries = set(manager.root.rglob("*"))
        with patch.object(suggestions, "add", wraps=suggestions.add) as add, \
                patch.object(suggestions, "list", wraps=suggestions.list) as listing:
            for requested in rejected:
                assert client.get(url + "/file", params={"path": requested}).status_code == 400, requested
                assert client.post(
                    url + "/file", json={"path": requested, "content": "no"},
                ).status_code == 400, requested
                assert client.get(url + "/suggestions", params={"path": requested}).status_code == 400, requested
                assert client.post(url + "/suggestions", json={
                    "path": requested, "content": "no", "author_id": "author",
                }).status_code == 400, requested
            add.assert_not_called()
            listing.assert_not_called()
        # Accept uses the same real file POST as the workstation; Dismiss is metadata-only.
        assert client.post(
            url + "/file", json={"path": stale.path, "content": stale.content},
        ).status_code == 400
        dismissed = client.post(url + f"/suggestions/{stale.id}/dismiss")
        assert dismissed.status_code == 200 and dismissed.json()["dismissed"] is True
        assert suggestions.list(owner_key, stale.path) == [] and writes == []
        assert payload.read_bytes() == raw_before and set(manager.root.rglob("*")) == before_entries
        overview = client.get(url)
        assert overview.status_code == 200
        if public_owner == "alias":
            assert overview.json()["files"] == [] and overview.json()["total_bytes"] == 0
        else:
            assert [(item["name"], item["size_bytes"]) for item in overview.json()["files"]] == [
                (".venv", 4), ("ordinary.txt", 8),
            ]
            assert overview.json()["total_bytes"] == 12
            ordinary = client.get(url + "/file", params={"path": "ordinary.txt"})
            assert ordinary.status_code == 200 and ordinary.json()["content"] == "ordinary"
            proposed = client.post(url + "/suggestions", json={
                "path": "ordinary.txt", "content": "accepted", "author_id": "author",
            })
            assert proposed.status_code == 200
            suggestion = proposed.json()["suggestion"]
            assert client.get(
                url + "/suggestions", params={"path": "ordinary.txt"},
            ).json()["suggestions"] == [suggestion]
            accepted = client.post(url + "/file", json={"path": suggestion["path"], "content": suggestion["content"]})
            assert accepted.status_code == 200 and accepted.json()["outcome"] == "committed"
            assert (base / "ordinary.txt").read_text(encoding="utf-8") == "accepted"
            assert writes == [(str(base / "ordinary.txt"), "accepted")]
            assert client.post(url + f"/suggestions/{suggestion['id']}/dismiss").json()["dismissed"] is True
        runtime.config.execution.enabled = False
        runtime.config.execution.workspace_write_enabled = False
        assert client.get(url + "/file", params={"path": stale_path}).json()["found"] is False
        assert client.post(url + "/file", json={"path": stale_path, "content": "no"}).status_code == 503
        assert client.get(url + "/suggestions", params={"path": stale_path}).json()["suggestions"] == []
        assert client.post(url + "/suggestions", json={
            "path": stale_path, "content": "no", "author_id": "author",
        }).status_code == 503
        assert client.post(url + f"/suggestions/{stale.id}/dismiss").status_code == 503
    finally:
        if client is not None:
            client.close()
        await store.stop()
        for link in reversed(aliases):
            _remove_alias(link)
