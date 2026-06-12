# Build AD-884 — Authority-scoping governance record (Minimal Authority axiom)

**Repo:** OSS (`d:\ProbOS`). **Issue: #847.** **Epic:** AD-877→884 Quartermaster hardening.
**Highest committed AD: AD-876** (Wave 232). This is **AD-884**. One AD = one commit.
**Depends on:** nothing structural (governance + guard test). Can land any time after AD-877.

---

## Problem

`QuartermasterAgent` can mutate any board item (unassign + re-dispatch + quarantine) with **no consensus
gate**. That is defensible — it is reversible housekeeping (Reversibility Preference axiom) — but the scoping
is currently **implicit**. The Minimal Authority axiom wants it explicit and guarded against regression.

## Verify-first findings (confirmed)

- `QuartermasterAgent` is `tier="utility"`, `agent_type="quartermaster"`, **no LLM**.
- `intent_descriptors = [IntentDescriptor(name="reconcile_board", ...)]` — a single reconcile intent.
- It declares **no** `requires_consensus=True` destructive intent. Its mutations (`unassign_work_item`,
  `dispatch_work_item`, metadata quarantine flag) are all reversible housekeeping.
- The decision to require **no** consensus gate is correct and intentional — this AD records the reasoning and
  installs a regression guard, it does **not** add a gate.

## Build (governance + guard test; minimal code)

### 1. DECISIONS.md — AD-884 entry (the substantive deliverable)

Under `## Era V — Civilization` (newest-first), record AD-884 explicitly:

> The Quartermaster's authority is **scoped to reconcile-only operations** (unassign / re-dispatch /
> quarantine-flag), all reversible board housekeeping. Per the Reversibility Preference and Minimal Authority
> axioms, no consensus gate is required: the agent performs no destructive, irreversible, or
> externally-visible side-effecting intents. It must never declare a `requires_consensus=True` destructive
> intent; if a future change needs one, that is a new AD with a consensus design, not a Quartermaster
> capability.

### 2. (Optional, only if it strengthens the guard) explicit allow-list constant

If it makes the guard test crisper, add a module-level constant on `QuartermasterAgent`, e.g.:

```python
RECONCILE_ONLY_INTENTS: frozenset[str] = frozenset({"reconcile_board"})
```

and assert the declared descriptor names are a subset of it. Keep code changes to this one constant at most —
the test is the enforcement, the constant is convenience.

### 3. Guard test (the regression lock)

Assert the capability surface is reconcile-only and consensus-free.

## Tests (≥3) — `tests/test_ad884_authority_scope.py`

**BF-287:** construct a real `QuartermasterAgent` (no LLM needed).

1. The agent's declared `intent_descriptors` names are reconcile-only (subset of `{"reconcile_board"}` /
   `RECONCILE_ONLY_INTENTS` if added).
2. No declared descriptor sets `requires_consensus=True` (iterate descriptors; assert none destructive).
3. `tier == "utility"` and `agent_type == "quartermaster"` (the agent stays a Utility-tier housekeeper).

## Do not

- Add a consensus gate, a quorum vote, or a red-team hook — the decision is that **none is needed**; record
  the reasoning instead.
- Add destructive intents to the agent.
- Create a standalone governance markdown doc — the record lives in DECISIONS.md.

## Tracking

- PROGRESS.md banner → next free Wave. DECISIONS.md AD-884 newest-first under `## Era V — Civilization` (this
  AD's primary artifact).

## Acceptance

- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad884_authority_scope.py -q -n 0 -p no:cacheprovider` green.
- Corruption pre-check. Verify compliance with `.github/copilot-instructions.md`.

## Verified against codebase (2026-06-05)

- agents/quartermaster.py — `agent_type="quartermaster"`, `tier="utility"`, no LLM,
  `intent_descriptors=[IntentDescriptor(name="reconcile_board", ...)]`, no `requires_consensus` destructive intent.
