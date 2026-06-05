# Build AD-883 — Observability: reconciliation status surface

**Repo:** OSS (`d:\ProbOS`). **Issue: #847.** **Epic:** AD-877→884 Quartermaster hardening.
**Highest committed AD: AD-876** (Wave 232). This is **AD-883**. One AD = one commit.
**Depends on:** AD-877 + AD-878 + AD-879 (the final counts-dict shape). **Build after those three.**

---

## Problem

The sweep emits `WORK_ITEM_RECONCILED` counts to the event log, but the Captain can't *see* reconciliation
activity at a glance (HXI #6: the canvas is the information; #10: the Ship's Computer reports from sensors).

## Verify-first finding (drives the surface choice — honours the epic "Do not")

- **No `/board` slash command exists** and there is no quartermaster/reconcile reference in `experience/`.
- The clean, no-new-surface path: `IntrospectionAgent._agent_info` (agents/introspect.py:271) calls
  `agent.info()` for each matched agent and is reachable via the `agent_info` intent (in `_handled_intents`,
  AD-320 introspection delegation). `BaseAgent.info()` (substrate/agent.py:159) returns a `dict[str, Any]` and
  is **overridable**.
- → **Preferred surface: override `QuartermasterAgent.info()`** to include the last-sweep summary. It then
  surfaces automatically through `agent_info quartermaster` with **no new slash command, no HTTP endpoint, and
  no `panels.py` change** — exactly what the epic's "Do not add a new HTTP endpoint unless required; prefer
  the existing introspection path" asks for.

## Build

### 1. Record last-sweep summary — `QuartermasterAgent`

- At the **end** of `reconcile()` (and `reconcile_for_agent` if AD-880 has shipped), store the summary on the
  agent: `self._last_sweep = {"counts": dict(counts), "at": time.time(), "trigger": "<periodic|reactive>"}`.
- Initialize `self._last_sweep = None` in `__init__` (never-run state).

### 2. Surface via `info()` override — `QuartermasterAgent.info()`

- Override `info()` to call `super().info()` and add a `reconciliation` block:
  - never-run: `{"last_sweep": None}`.
  - else: `{"last_sweep": {...counts...}, "age_seconds": round(time.time() - self._last_sweep["at"], 1),
    "trigger": ...}`.
- Use `counts.get(k, 0)` style access when composing any human-readable line so keys added by later ADs
  (`quarantined`, `too_fresh`, `truncated`, `stalled`, `remote_owner_skipped`) never KeyError an older renderer.

### 3. (Optional, only if trivial) human-readable line

If `_agent_info` already renders a free-form summary string per agent, contribute one line:
`"last sweep: scanned N, redispatched N, cleared N, quarantined N — Xs ago"` (or `"never run"`). **Verify-first
the actual `_agent_info` render shape before adding** — if it just returns the `info()` dict, the dict block in
§2 is sufficient and no string formatting is needed. Do **not** add a `/board` command.

## Tests (≥5) — `tests/test_ad883_reconcile_observability.py`

**BF-287:** real `WorkItemStore`; construct a real `QuartermasterAgent`.

1. After a `reconcile()`, `agent._last_sweep` holds the counts + a timestamp.
2. `agent.info()` includes the `reconciliation.last_sweep` block with the recorded counts.
3. Never-run agent: `info()` reports `last_sweep: None` (no crash).
4. `age_seconds` reflects elapsed time since the sweep (monkeypatch/`time` tolerance).
5. `info()` renders cleanly when counts contain later-AD keys (seed a counts dict with `quarantined`/`stalled`
   present) — `counts.get` access, no KeyError.

## Do not

- Add a new HTTP endpoint or a `/board` slash command (the introspection path is sufficient).
- Change `panels.py` / `shell.py` unless the chosen surface strictly requires it (it does not).
- Hard-index counts keys (use `.get`).

## Tracking

- PROGRESS.md banner → next free Wave. DECISIONS.md AD-883 newest-first under `## Era V — Civilization`
  (record: reconciliation status surfaced via `QuartermasterAgent.info()` + `agent_info`, no new command/endpoint).

## Acceptance

- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad883_reconcile_observability.py -q -n 0 -p no:cacheprovider` green.
- Corruption pre-check. Verify compliance with `.github/copilot-instructions.md`.

## Verified against codebase (2026-06-05)

- agents/introspect.py:271 `_agent_info` calls `agent.info()`; `agent_info` in `_handled_intents` (AD-320 path).
- substrate/agent.py:159 `def info(self) -> dict[str, Any]` — overridable.
- experience/shell.py / panels.py — no `/board` command, no quartermaster reference.
- quartermaster.py `reconcile()` builds the counts dict and emits `WORK_ITEM_RECONCILED`.
