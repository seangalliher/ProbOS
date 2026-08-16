"""BF-763: the execution subsystem must not name controls it does not have.

``isolation.py`` listed "the consensus gate (every execution is
quorum-authorized)" as the FIRST of four things constituting the Tier-1
boundary. Neither ``run_python`` path is quorum-approved before it runs: the
agentic tool is permission-resolved but nothing votes on the script, and the
mesh intent's ``CodeRunnerAgent`` executes in ``act()`` while quorum is
evaluated on the results afterwards (BF-779).

A security rationale naming a control the live path lacks is worse than no
rationale -- it stops the next reader looking, which is how this survived from
AD-993 until an audit of the live traces found 60 ungated executions.

These are source assertions because the claims are prose; there is no runtime
value to check. Most pin the exact historical sentence rather than banning a
phrase, because a substring ban cannot tell an assertion from its denial -- an
earlier version of this file failed on the corrected text's own "not
quorum-approved". Some assertions DO ban a short phrase outright; each of those
is a case where a correction and its contradiction could otherwise sit side by
side, which mutation testing showed was the way through every earlier guard.
"""

from __future__ import annotations

from pathlib import Path


def _text(relative: str) -> str:
    """Whitespace-normalised source, so a reflowed docstring is not a failure."""
    return " ".join(Path(relative).read_text(encoding="utf-8").split())


def test_isolation_does_not_claim_a_consensus_gate() -> None:
    source = _text("src/probos/execution/isolation.py")

    assert "(a) the consensus gate (every execution is quorum-authorized)" not in source
    assert "governed by consensus" not in source
    # Replaced, not merely deleted -- and scoped to this module rather than
    # summarising what callers do, which is what produced the false claim.
    assert "Callers, not this module, decide what else applies" in source
    assert "BF-779" in source
    # An earlier fix asserted the inventory was complete ("precisely, and
    # nothing more") and it was not -- it omitted RLIMIT_CPU, RLIMIT_FSIZE,
    # env scrubbing and `-I`. Exhaustive framing is banned here: it is the same
    # defect as the original false claim, just in the opposite direction.
    assert "precisely, and nothing more" not in source
    assert "deliberately not written as exhaustive" in source
    # ...and the explanation of WHY must not itself be a miscount. An earlier
    # version said the draft "omitted three rlimits"; it omitted two, since
    # RLIMIT_AS was already named. A counted claim inside the sentence about
    # false counted claims is the pattern at its purest.
    assert "omitting three rlimits" not in source
    assert "presenting an incomplete inventory as complete" in source
    # Two claims that were themselves false in earlier revisions of the fix:
    # the POSIX memory bound is best-effort, and a separate address space does
    # not stop same-user code touching the runtime's files.
    assert "best-effort ``RLIMIT_AS``" in source
    assert "runs as the same user" in source
    # A separate address space does NOT prevent OS-mediated access: a probe
    # opened the parent and read a live CPython object out of its memory.
    assert "cannot reach into the runtime's own objects" not in source
    assert "ReadProcessMemory" in source
    # ...but scoped to the host it was observed on. OpenProcess access depends
    # on the target DACL and requested rights, and these APIs are Windows-only,
    # so stating it as a universal invariant is the opposite over-correction.
    assert "tested Windows host" in source
    assert "OS-policy dependent, not universal" in source
    # Presence of the hedge is not enough: a mutation that ADDS a universalising
    # clause alongside it left both guards green. Ban the universalising forms
    # outright, or the correction and its contradiction coexist -- which is the
    # defect class this whole file exists to catch.
    assert "every supported platform" not in source
    assert "always reaches" not in source
    assert "this always succeeds" not in source
    # The timeout is a trigger, not a return deadline: a surviving descendant
    # can hold the pipe open (200 ms request seen at ~1.3 s). Earlier fixes
    # described the kill mechanics in prose and were wrong twice -- once by
    # stating Windows' direct-child kill universally, once by ignoring that the
    # POSIX killpg falls back to proc.kill(). The module now points at `_kill`
    # instead of summarising it, which is the only description that stays true.
    assert "kills the DIRECT CHILD only" not in source
    assert "with a wall-clock timeout" not in source
    assert "timeout TRIGGER, which is not a return deadline" in source
    assert "read it rather than trusting a summary here" in source
    # Ban guarantee wording outright: mutations that ADDED a guarantee alongside
    # the hedge survived twice (M40 "guarantees run returns by the configured
    # deadline", M41 "Every timed-out run terminates all descendants before
    # returning"). Presence of a hedge does not exclude its contradiction.
    assert "guarantees the call returns" not in source
    assert "guarantees run returns" not in source
    assert "terminates all descendants" not in source
    assert "all descendants before returning" not in source
    # Quorum evaluation is itself conditional on the model-chosen flag.
    assert "which defaults false" in source
    # Same stale framing as the other two files' summary lines.
    assert "governed ephemeral code execution" not in source
    # AD-1247 built the agentic record, so the "scope not settled" hedge is
    # itself now stale. What must stay is that the module does not restate its
    # callers' conclusions -- it links them.
    assert "scope across the two paths is not yet settled there" not in source
    assert "the mesh path's absence is BF-787" in source
    # And the tool is permission-resolved -- "ungoverned" would be the opposite
    # overclaim to the one being fixed.
    assert "NEITHER is quorum-approved" in source
    # "attributable" was false -- ExecutionRequest/ExecutionResult carry no
    # actor, intent or correlation field.
    assert "bounded and attributable" not in source
    # And the permission check must not read as stronger than it is: the tool is
    # registered with ship-wide READ, so with no permission store it passes.
    assert "do check a grant" not in source
    assert "grants it ship-wide READ" in source


def test_code_runner_does_not_claim_a_gate_it_lacks() -> None:
    """The same false claim lived in a third file, in three places.

    The header said "every execution is quorum-authorized, exactly like
    ``run_command``" -- and ``run_command`` is not gated either, so the
    comparison was accidentally accurate. The class docstring and the
    pip-install comment repeated it.
    """
    source = _text("src/probos/agents/code_runner.py")

    assert "every execution is quorum-authorized" not in source
    assert "confinement-by-convention governed by consensus" not in source
    assert "Consensus-gated + default-OFF" not in source
    assert "so this is consensus-gated and the package names" not in source
    assert "NOT consensus-gated, despite the descriptors" in source
    assert "BF-779" in source
    # The workspace is not ephemeral by default; persistent_workspaces is True.
    # Both halves asserted: a correction that merely sits alongside the old
    # claim leaves the file saying two contradictory things, and the positive
    # assertion alone passes in that state.
    assert "a fresh ephemeral working folder per task" not in source
    assert "throwaway per-task venv" not in source
    assert "throwaway venv" not in source
    # The module title and class docstring led with "governed ephemeral" and
    # "Execute ephemeral Python" -- the first lines any reader or LLM sees, and
    # both false. Tightening this guard is what surfaced them.
    assert "governed ephemeral Python execution" not in source
    assert "Execute ephemeral Python" not in source
    assert "not** ephemeral by default" in source
    assert "That venv is REUSED across runs" in source
    # `allow_network=False` sets a discard-port proxy, which a raw socket walks
    # straight past -- verified by execution. Advertising it as "network off"
    # is a false security claim, which is this issue's whole defect class.
    assert "network-off-by-default" not in source
    assert "is **not** a network block" in source
    # Memory bounds are POSIX-only and best-effort; "resource bounds" implied
    # more than the sandbox delivers.
    assert "POSIX-only and best-effort" in source
    # "Not audited" was too broad in the other direction: the agentic path CAN
    # persist a generic tool trace. What is missing is a mandatory dedicated
    # record, so the claim has to be narrowed rather than reversed.
    assert "**Not audited.**" not in source
    assert "No dedicated execution audit" in source
    # AD-1247: the agentic path now has a MANDATORY per-execution record, so
    # "can persist a generic tool trace, optionally" understates it. What this
    # file exists to prevent is THIS path claiming a control it lacks, so the
    # assertion moves to the distinction that is still load-bearing: the mesh
    # path has no execution-specific record and must not imply one.
    assert "can persist a generic tool trace, optionally" not in source
    assert "No dedicated execution audit on THIS path" in source
    assert "BF-787 tracks" in source
    assert "always persists" not in source
    # The reason it is optional must survive too, or "optionally" degrades into
    # a word with no stated cause.
    #
    # AD-1247: this sentence described the AGENTIC path's optional tool trace,
    # in the MESH path's module. That cross-reference is gone -- code_runner.py
    # now states what THIS path does and links BF-787 for what it lacks -- so
    # the qualifier moved with the claim it qualified.
    assert "skipped when no store is configured or the write" not in source
    # The deferred issue's scope is not settled; do not write it as decided.
    assert "AD-1247 will add one" not in source
    # AD-1247 settled it: the record covers the AGENTIC path only, and this
    # module now says which side of that line it is on rather than deferring.
    assert "is not settled there" not in source
    # The header must not claim to enumerate every constraint.
    assert "under these constraints, and no" not in source
    # The timeout bounds nothing reliably: it is a trigger, and on POSIX it
    # targets the process group rather than the direct child.
    assert "subprocess isolation, wall-clock timeout" not in source
    assert "a timeout that kills the direct child only" not in source
    assert "a timeout trigger that does not guarantee the call" in source
    assert "terminates all descendants" not in source
    # The mesh path is not audit-free; it writes generic intent/quorum rows.
    # But it also must not be described as recording nothing of the run at all:
    # the DAG checkpoint transiently serializes params and results. Scope the
    # claim to the event-log ROWS, which is what is actually true of them.
    assert "THIS path has nothing" not in source
    assert "nothing carrying the source that ran" not in source
    # "No ingress records the submitted source" was FALSE and this guard pinned
    # it: a live probe recovered both `arguments.code` and `stdout` from the
    # agentic tool trace in the attachment store, the sandbox leaves `script.py`
    # in a persistent workdir, and the DAG checkpoint serializes both. Scope the
    # claim to the runtime ROWS and say plainly that other stores do carry it.
    assert "No ingress records the submitted source" not in source
    # AD-1247 reshaped this bullet: it used to describe the AGENTIC path's
    # optional trace and the other stores that can hold source, from inside the
    # MESH path's module. Now it states what THIS path does and links BF-787 for
    # what it lacks, so the cross-path inventory moved to config.py where the
    # comparison belongs. The negative guards below stay -- they ban the wrong
    # claims regardless of which module makes them.
    assert "None of those rows carries the submitted source" in source
    assert "This means the source is never stored" not in source
    assert "never includes source or output" not in source
    assert "all contain both" not in source
    # The rows DO carry correlation ids; a mutation denying it survived once.
    assert "carry no correlation identifier" not in source
    # ...and quorum_evaluated is CONDITIONAL: use_consensus comes from the
    # decomposer's model JSON and defaults false, so listing it unconditionally
    # alongside the always-written rows was an overstatement.
    assert "``quorum_evaluated`` only when the plan's model-chosen" in source
    # The descriptor's requires_consensus does NOT force use_consensus true.
    assert "every run_python plan sets use_consensus" not in source
    # And the ingress list must not be written as closed: a third route (the
    # federation MCP server) broadcasts straight to the bus and writes no rows
    # at all. "on both submission paths" was the fourth exhaustive claim this
    # fix has had to retract, so the text names ingress variation explicitly.
    assert "on both submission paths" not in source
    assert "nothing at all on" in source
    # The MCP route writing NO rows is the concrete counterexample that makes
    # the ingress variation real; without it the sentence is a hedge with no
    # content, and a mutation deleting it survived.
    assert "broadcasts straight to the bus" in source


def test_execution_config_does_not_claim_authorization() -> None:
    source = _text("src/probos/config.py")

    assert "attributable through a per-execution audit record" not in source
    assert "neither** ``run_python`` path is quorum-approved" in source
    # The audit absence must be stated as NARROW. "Neither path writes an audit
    # record today" was flatly false -- the agentic path's `_persist_tool_trace`
    # can persist the request and a bounded/elidable output when the store write
    # succeeds, and the mesh path writes intent/quorum event-log rows. An earlier
    # version of this guard PINNED that false sentence as contract, which is the
    # exact failure mode this file exists to prevent.
    assert "Neither path writes an audit record today" not in source
    # AD-1247 rewrote this stanza: the old "neither path writes a mandatory
    # record" sentence became false for the agentic path, and leaving it beside
    # the new paragraph made the docstring say two contradictory things. The
    # guard now pins the CONDITIONAL claim, which is the only true one.
    assert "mandatory execution-specific audit record" not in source
    assert "MANDATORY record, not any record" not in source
    assert "ATTEMPTED once per run that reached the" in source
    assert "security_infra.audit_enabled" in source
    # An unconditional claim is the original BF-763 defect returning, so the
    # failure modes are named explicitly rather than implied. And the record is
    # NOT written only for confirmed launches -- an unconfirmed teardown writes
    # one too, labelled `unknown`, so "per LAUNCHED run" would undercount.
    assert "never an\n    unconditional guarantee".replace("\n    ", " ") in source
    assert "launch_state" in source
    assert "UNCONFIRMED" in source
    # ...and the mesh path is not empty either; saying so was the over-correction.
    assert "the mesh path has nothing" not in source
    assert "no execution-specific record at all (BF-787)" in source
    assert "quorum row only when the plan's model-chosen" in source
    assert "No ingress records the source or its" not in source
    assert "none of those rows\n    carries the source".replace("\n    ", " ") in source
    assert "carry no correlation identifier" not in source
    # `persistent_workspaces` defaults True, so the summary line must not call
    # the default execution ephemeral -- the same phrase this file already
    # rejects in code_runner.py.
    assert "governed ephemeral code execution" not in source
    # The install comment claimed an ephemeral venv and a consensus gate.
    assert "per-task ephemeral venv" not in source
    assert "surfaced in the consensus-gated intent" not in source
    # Kept within one comment line: `_text` collapses whitespace but leaves the
    # `#` markers, so a phrase spanning a line break would never match.
    assert "the owner's workspace venv, which is REUSED" in source
