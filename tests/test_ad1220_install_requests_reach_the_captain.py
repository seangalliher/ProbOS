"""AD-1220 (#1181): a missing library files an install request the Captain can see.

The Captain asked why the sandbox cannot install other Python libraries. The
machinery was already complete — AD-838c built approval-gated install, AD-1073
wired it into the sandbox, AD-1178 made the missing set legible, and AD-1211
made ``fulfil_install`` call straight back into ``ensure_dependency`` with
``pre_approved=True``. Every piece worked. Nothing connected them.

``runtime.dependency_resolver._approval_fn`` is assigned in exactly ONE place —
``experience/shell.py:163`` — and what it wires is a **Rich console prompt**.
On the HXI/API vessel the callback is ``None``, so ``ensure_dependency`` took
the hard-decline branch and stopped. No ``install`` capability request was ever
filed, so the Captain was never shown the choice that ``fulfil_install`` was
waiting to act on.

That is this repo's most-repeated defect shape: the producer fires, the
consumer works, and nothing crosses the seam. So the headline test here is the
CROSSING one — missing import, request filed, Captain approves, package
installs — not a test of either half.

Design points worth pinning:

* **Attribution is required, not defaulted.** An unattributed install request
  cannot answer the only question that matters when approving one: who wants
  this, and for what. With no requester the ask is skipped and the previous
  decline-only behaviour stands.
* **Dedup by (agent, target).** A script that fails the same import on every
  run must not bury the Captain under identical cards.
* **``pre_approved`` must never file.** That is ``fulfil_install`` re-entering
  after the Captain already said yes; filing there would loop.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from probos.capability_request import CapabilityRequestStore
from probos.cognitive.dependency_resolver import DependencyResult
from probos.runtime import ProbOSRuntime


class _Resolver:
    """Stands in for DependencyResolver with no approval callback wired —
    the state of every API/HXI vessel."""

    def __init__(self, missing: list[str], *, approval_fn: Any = None) -> None:
        self._missing = missing
        self._approval_fn = approval_fn
        self.resolved: list[str] = []

    def detect_missing(self, source: str) -> list[str]:
        return list(self._missing)

    async def resolve(self, source: str, *, pre_approved: bool = False):
        self.resolved.append(source)
        return DependencyResult(success=True, installed=list(self._missing))


def _runtime(store: CapabilityRequestStore | None, resolver: Any) -> Any:
    """Minimal stand-in carrying only what ensure_dependency reads."""
    return SimpleNamespace(
        config=SimpleNamespace(
            dependency=SimpleNamespace(
                dynamic_install_enabled=True,
                # AD-1222: the auto-approve tier is declared here now, not
                # borrowed from self_mod.allowed_imports.
                auto_approve_imports=["json", "os"],
            ),
            self_mod=SimpleNamespace(allowed_imports=["json", "os"]),
        ),
        dependency_resolver=resolver,
        capability_request_store=store,
        event_log=None,
    )


async def _store(tmp_path) -> CapabilityRequestStore:
    store = CapabilityRequestStore(db_path=str(tmp_path / "reqs.db"))
    await store.start()
    return store


# ── (1) the gap this closes: the ask is filed, not swallowed ───────────────
@pytest.mark.asyncio
async def test_no_approver_files_an_install_request(tmp_path) -> None:
    """The headline. Before AD-1220 this branch declined and told nobody."""
    store = await _store(tmp_path)
    rt = _runtime(store, _Resolver(["matplotlib"]))

    result = await ProbOSRuntime.ensure_dependency(
        rt, "matplotlib", requested_by="counselor_0"
    )

    assert not result.success
    assert result.declined == ["matplotlib"]
    pending = await store.list_pending()
    assert [(r.kind, r.target, r.agent_id) for r in pending] == [
        ("install", "matplotlib", "counselor_0")
    ]


@pytest.mark.asyncio
async def test_the_error_says_approval_was_requested_not_unavailable(
    tmp_path,
) -> None:
    """The old wording ('approval callback unavailable') described the vessel's
    plumbing. The agent needs to know an ask is now pending, because that is
    what determines whether waiting is worth anything."""
    store = await _store(tmp_path)
    rt = _runtime(store, _Resolver(["matplotlib"]))

    result = await ProbOSRuntime.ensure_dependency(
        rt, "matplotlib", requested_by="counselor_0"
    )

    assert result.error == "approval requested"


@pytest.mark.asyncio
async def test_one_request_per_missing_package(tmp_path) -> None:
    store = await _store(tmp_path)
    rt = _runtime(store, _Resolver(["matplotlib", "seaborn"]))

    await ProbOSRuntime.ensure_dependency(
        rt, ["matplotlib", "seaborn"], requested_by="counselor_0"
    )

    pending = await store.list_pending()
    assert sorted(r.target for r in pending) == ["matplotlib", "seaborn"]


# ── (2) the guards ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_a_repeated_failure_does_not_file_a_duplicate(tmp_path) -> None:
    """A script re-run must not produce a second identical card. The one
    pending request already IS the ask."""
    store = await _store(tmp_path)
    rt = _runtime(store, _Resolver(["matplotlib"]))

    await ProbOSRuntime.ensure_dependency(rt, "matplotlib", requested_by="counselor_0")
    await ProbOSRuntime.ensure_dependency(rt, "matplotlib", requested_by="counselor_0")
    await ProbOSRuntime.ensure_dependency(rt, "matplotlib", requested_by="counselor_0")

    pending = await store.list_pending()
    assert len(pending) == 1


@pytest.mark.asyncio
async def test_a_different_agent_wanting_the_same_library_does_file(
    tmp_path,
) -> None:
    """Dedup is per (agent, target), not per target. Two agents blocked on the
    same library are two facts the Captain may want to act on separately —
    and collapsing them would hide the second agent entirely."""
    store = await _store(tmp_path)
    rt = _runtime(store, _Resolver(["matplotlib"]))

    await ProbOSRuntime.ensure_dependency(rt, "matplotlib", requested_by="counselor_0")
    await ProbOSRuntime.ensure_dependency(rt, "matplotlib", requested_by="scout_0")

    pending = await store.list_pending()
    assert sorted(r.agent_id for r in pending) == ["counselor_0", "scout_0"]


@pytest.mark.asyncio
async def test_without_a_requester_nothing_is_filed(tmp_path) -> None:
    """Default-OFF byte-identity: every caller that does not name an agent
    behaves exactly as it did before AD-1220."""
    store = await _store(tmp_path)
    rt = _runtime(store, _Resolver(["matplotlib"]))

    result = await ProbOSRuntime.ensure_dependency(rt, "matplotlib")

    assert not result.success
    assert result.error == "approval callback unavailable"
    assert await store.list_pending() == []


@pytest.mark.asyncio
async def test_pre_approved_never_files_a_request(tmp_path) -> None:
    """`fulfil_install` re-enters here with pre_approved=True after the Captain
    has already said yes. Filing there would ask for permission to do the
    thing permission was just granted for — and each approval would mint the
    next request."""
    store = await _store(tmp_path)
    resolver = _Resolver(["matplotlib"])
    rt = _runtime(store, resolver)

    result = await ProbOSRuntime.ensure_dependency(
        rt, "matplotlib", pre_approved=True, requested_by="counselor_0"
    )

    assert result.success
    assert resolver.resolved, "pre_approved should reach the resolver"
    assert await store.list_pending() == []


@pytest.mark.asyncio
async def test_an_allowlisted_package_is_not_asked_about(tmp_path) -> None:
    """The whitelist tier auto-approves. Only the prompt tier becomes an ask."""
    store = await _store(tmp_path)
    rt = _runtime(store, _Resolver(["json"]))

    await ProbOSRuntime.ensure_dependency(rt, "json", requested_by="counselor_0")

    assert await store.list_pending() == []


# ── (3) honest-degrade: filing must never cost the turn ────────────────────
@pytest.mark.asyncio
async def test_no_store_still_declines_cleanly(tmp_path) -> None:
    rt = _runtime(None, _Resolver(["matplotlib"]))

    result = await ProbOSRuntime.ensure_dependency(
        rt, "matplotlib", requested_by="counselor_0"
    )

    assert not result.success
    assert result.declined == ["matplotlib"]


@pytest.mark.asyncio
async def test_a_failing_store_does_not_raise(tmp_path) -> None:
    """Losing the ask is bad; losing the agent's partial work because the ask
    failed to write would be worse."""

    class _Exploding:
        async def list_pending(self):
            raise RuntimeError("db is gone")

    rt = _runtime(_Exploding(), _Resolver(["matplotlib"]))

    result = await ProbOSRuntime.ensure_dependency(
        rt, "matplotlib", requested_by="counselor_0"
    )

    assert not result.success
    assert result.declined == ["matplotlib"]


# ── (4) THE CROSSING TEST: missing import → ask → approve → installed ──────
@pytest.mark.asyncio
async def test_the_whole_chain_from_missing_import_to_installed(tmp_path) -> None:
    """One test spanning the seam that was dead.

    Deliberately NOT four tests of four links. Every link here was already
    correct and individually covered before AD-1220 — that is precisely why
    the feature could be complete and inert at the same time. Only an
    assertion that crosses the whole chain can tell the two apart.
    """
    from probos.cognitive.capability_triage import fulfil_install

    store = await _store(tmp_path)
    resolver = _Resolver(["matplotlib"])
    rt = _runtime(store, resolver)

    # 1. an agent's script needs a library the sandbox does not have
    first = await ProbOSRuntime.ensure_dependency(
        rt, "matplotlib", requested_by="counselor_0"
    )
    assert not first.success

    # 2. the Captain is shown an ask (this is the step that did not exist)
    pending = await store.list_pending()
    assert len(pending) == 1
    request = pending[0]
    assert request.kind == "install"
    assert request.target == "matplotlib"

    # 3. the Captain approves it
    await store.decide(request.id, approve=True, decided_by="captain")

    # 4. approval fulfils — installing without asking a second time
    rt.ensure_dependency = lambda *a, **k: ProbOSRuntime.ensure_dependency(rt, *a, **k)
    fulfilled = await fulfil_install(
        request.id, store=store, target=request.target, runtime=rt
    )

    assert fulfilled is not None, "the approved install did not fulfil"
    assert fulfilled.status == "fulfilled"
    assert resolver.resolved, "nothing was ever actually installed"

    # 5. and the queue is clear — the ask is answered, not re-filed
    assert await store.list_pending() == []
