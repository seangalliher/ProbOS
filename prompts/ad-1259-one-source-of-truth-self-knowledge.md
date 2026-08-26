# AD-1259 — one source of truth for agent self-knowledge

**Status:** ready to build
**Issue:** [#1309](https://github.com/seangalliher/ProbOS/issues/1309)
**Dependencies:** AD-1258 (#1308) — the social domain must render before `_agent_info` reads it back
**Estimated tests:** 12–15 new, existing introspection tests amended

---

## Numbering

Allocated in the AD-1258 wave (#1308, #1309, #1310, #1311). GitHub ceiling at drafting:
**AD-1256** (#1302); prompts hold AD-1250…AD-1255, AD-1257, and this wave holds
AD-1258…AD-1261. Next free after the wave: **AD-1262**.

---

## Problem

Two code paths compute the same agent facts, differently, and neither knows the other exists.

| Fact | `IntrospectionAgent._agent_info` (`agents/introspect.py:324-347`) | `IntrospectiveTelemetryService` (`cognitive/introspective_telemetry.py`) |
|---|---|---|
| Trust score | `format_trust(rt.trust_network.get_score(agent.id))` | `round(trust_net.get_score(agent_id), 3)` (`:59`) |
| Hebbian inbound | top-3 via `all_weights_typed()`, `format_trust(w)` | top-3 via `all_weights_typed()`, `round(w, 2)` (`:132`) |
| Hebbian outbound | top-3 (`:333-337`) | **not computed** |
| Connection count | `total_connections` (`:344-346`) | **not computed** |
| Interaction breadth | not computed | distinct intents over last 20 trust events (`:139-141`) |

### The divergence is live, not latent

`format_trust` (`config.py:112`) is `round(value, TRUST_DISPLAY_PRECISION)` and
`TRUST_DISPLAY_PRECISION = 4` (`config.py:32`). The telemetry service hardcodes `3`.

Verified by execution, not by reading:

```
TRUST_DISPLAY_PRECISION = 4
format_trust: 0.5124 | service round(...,3): 0.512 | differ: True
weights: format_trust: 0.8765 | service round(...,2): 0.88
```

So for the same agent at the same instant, the Captain's introspection reports a trust score
to four decimal places and the agent's own telemetry block reports three. Hebbian weights
diverge further — 4 dp against 2 dp.

`format_trust`'s own docstring says it *"Centralizes precision."* The telemetry service
falsifies that claim by not calling it.

This is the shape BF-755 named at the tool-assembly seam — *"two assemblies that could drift
is the shape this repo keeps producing, so there is exactly one."* Here there are two, and
the drift is already measurable in the output.

### Why it matters beyond cosmetics

AD-589 cross-checks an agent's self-report against the cached telemetry snapshot
(`cognitive_agent.py:6147-6153`, `_check_introspective_faithfulness`). If an agent ever
quotes a number from the Captain-facing path and the faithfulness check compares it against
the telemetry path, a rounding disagreement is indistinguishable from confabulation. Two
sources of truth make the confabulation detector unreliable in exactly the domain it exists
to police.

---

## Solution

**`IntrospectiveTelemetryService` becomes the single source of truth for per-agent facts.
`IntrospectionAgent` reads from it.**

Direction matters and is not arbitrary: the service is already the one wired into all four
cognitive paths — DM (`cognitive_agent.py:9057`), ward room (`:9390`), sub-tasks
(`sub_tasks/query.py:381`), proactive (`proactive.py:2353`) — and after AD-1258 it also backs
the `self_query` tool. `_agent_info` has exactly one consumer surface. Moving the
smaller-fanout caller onto the larger-fanout service is the cheaper, less reversible-in-anger
direction.

### The consolidation must not lose the Captain's data

The service currently computes **less** than `_agent_info`: no outbound affinities, no
connection count. A naive "point `_agent_info` at the service" would silently narrow the
Captain's view. So the order is:

1. The service **gains** what `_agent_info` has that it lacks.
2. The service **adopts** `format_trust` so precision is centralized where the docstring
   already claims it is.
3. `_agent_info` and `_team_info` then read from the service.

Step 3 is not safe before steps 1 and 2.

### Why not the reverse direction

| Rejected | Why |
|---|---|
| Make `_agent_info` the source and have the service call it | `IntrospectionAgent` is a `BaseAgent` in a pool; the service is a stateless collaborator on the runtime. Calling into a pooled agent from four cognitive hot paths adds a registry lookup and a liveness dependency to every introspective turn. |
| Leave both and add a drift test | Pins the duplication as contract. The repo's own review flag: a test that encodes the defect as a requirement. |
| Delete `_agent_info` | It serves the Captain's third-person view, which is a real and different need. AD-1260 depends on that separation existing. |

---

## Implementation

### Section 1 — the service gains the missing facts

**`src/probos/cognitive/introspective_telemetry.py`**

In `get_social_state` (`:118`), alongside the existing inbound `routing_affinities`:

- `outbound_affinities` — top-3 where `src == agent_id`, same shape as the inbound list.
- `total_connections` — `sum(1 for (src, tgt, _rel) in all_weights if src == agent_id or tgt == agent_id)`.

Match `_agent_info:333-346` exactly in *what* is counted. Verify the key tuple shape:
`all_weights_typed()` is keyed `(src, tgt, rel)` — confirmed by
`tests/test_ad588_telemetry_introspection.py:237-241`, which uses three-tuples.

### Section 2 — precision is centralized

Replace the three hardcoded rounds with `format_trust`:

- `:59` `round(trust_net.get_score(agent_id), 3)` → `format_trust(...)`
- `:63` `round(record.uncertainty, 3)` → `format_trust(...)`
- `:132` `round(w, 2)` → `format_trust(w)`

Import from `probos.config` (`introspective_telemetry.py` currently imports stdlib only —
verify at `:14-19`; `config` is a legal import from `cognitive`, proven by
`agents/introspect.py:9`).

> This **changes the rendered telemetry string**: trust goes from 3 dp to 4 dp, weights from
> 2 dp to 4 dp. That is the point. Existing assertions in
> `tests/test_ad588_telemetry_introspection.py` that pin `0.72` / `0.5` are unaffected
> (trailing zeros are dropped by `round`), but **check each one and record inline why any
> amended assertion changed** — never delete one.

### Section 3 — `_agent_info` and `_team_info` read from the service

**`src/probos/agents/introspect.py`**

`_agent_info` (`:271`) and `_team_info` (`:359`) are currently **synchronous**. Verified:

```
_agent_info: iscoroutinefunction=False
_team_info:  iscoroutinefunction=False
act dispatch: return self._agent_info(rt, params)
act dispatch: return self._team_info(rt, params)
```

The service getters are `async`. Two options; take the first:

- **Make both handlers `async`** and `await` the service. `act` already `await`s
  `_explain_last`, `_why`, `_introspect_memory` and `_search_knowledge`, so the dispatch site
  already supports it — add `await` to the two dispatch lines shown above and leave the other
  nine branches alone.
- Do **not** add a sync shim or `run_until_complete`. That is the wrong direction and the
  dispatch site does not need it.

Then, for each agent in the result, replace the inline trust + Hebbian computation with
`await svc.get_trust_state(agent.id)` and `await svc.get_social_state(agent.id)`, mapping
into the **existing output keys** (`trust_score`, `hebbian.incoming_top3`,
`hebbian.outgoing_top3`, `hebbian.total_connections`) so the Captain-facing shape is
unchanged.

**Honest-degrade:** `runtime._introspective_telemetry` may be `None` (it is set to `None` on
init failure — `runtime.py:2661-2662`). When absent, fall back to the existing inline
computation rather than returning empty. Keep the current code as that fallback; do not
delete it.

---

## Tests

New file `tests/test_ad1259_one_source_of_truth.py`.

1. **The crossing test.** One runtime, one agent. Assert `_agent_info`'s reported
   `trust_score` and the telemetry snapshot's `trust.score` are **equal** — not merely both
   present. This is the assertion the whole AD exists to make true, and it must fail on HEAD.
2. Same for the top inbound Hebbian weight.
3. `outbound_affinities` present in `get_social_state` and matching `_agent_info`'s
   `hebbian.outgoing_top3`.
4. `total_connections` matches between the two paths.
5. `format_trust` is used: a score of `0.512375` renders as `0.5124`, not `0.512`.
6. `_agent_info` with `runtime._introspective_telemetry = None` returns the same shape via
   the fallback, and does not raise.
7. `_team_info` likewise.
8. `_agent_info` is awaitable and `act` dispatches it correctly for every one of the 11 intents
   (parametrized over `_handled_intents`).
9. Empty Hebbian router ⇒ no affinity keys, no crash, both paths agree on the absence.
10. An agent with no trust record ⇒ both paths agree.
11–15. Boundary cases per handler: absent registry, absent trust network, absent hebbian
    router, unknown agent id, `agent_type` prefix-fallback still resolving.

**Amend, do not rewrite:** any `tests/test_ad588_telemetry_introspection.py` assertion whose
expected precision changes. Record the reason inline at the assertion.

---

## Acceptance criteria

- [ ] Test #1 fails when checked out against HEAD and passes after. Demonstrate both.
- [ ] `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q` green; report count before and after.
- [ ] `grep -n "round(" src/probos/cognitive/introspective_telemetry.py` returns zero trust/weight rounds.
- [ ] The Captain-facing `_agent_info` output keys are unchanged. Prove with an assertion over the key set, not by inspection.
- [ ] Run the `Diff Reviewer` subagent on the staged diff with a different model than the author.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Adjacent, do not build

- **New domains** (wellness, authority, organs). AD-1260, AD-1261, deferred.
- **Making `IntrospectionAgent` reachable from a DM.** Explicitly out of scope — AD-1258 rejected it and AD-1260 explains the boundary.
- **Normalizing `TRUST_DISPLAY_PRECISION` itself.** Four decimal places may be more than anyone wants, but changing it touches every trust display on the ship. Separate decision, no number minted.
