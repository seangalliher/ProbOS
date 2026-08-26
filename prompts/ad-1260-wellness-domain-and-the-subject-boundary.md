# AD-1260 — the wellness domain, and the line between first person and third

**Status:** ready to build
**Issue:** [#1310](https://github.com/seangalliher/ProbOS/issues/1310)
**Dependencies:** AD-1258 (#1308, `self_query`), AD-1259 (#1309, the service is the single source of truth)
**Estimated tests:** 14–18 new

---

## Numbering

Allocated in the AD-1258 wave (#1308, #1309, #1310, #1311). Next free after the wave: **AD-1262**.

---

## Problem

The Ship's Counselor assesses the cognitive wellness of the crew. Those assessments persist.
She cannot read her own.

Asked to describe herself in a 1:1 chat, she reported — accurately — that her wellness score,
her drift from baseline, and her collaboration patterns relative to that baseline were not
available to her. Every one of those values exists, for her, in a table she owns.

### The data is one call away

`CounselorAgent.get_profile(agent_id)` (`cognitive/counselor.py:715`) is a **synchronous
in-memory dict lookup** returning a `CognitiveProfile`. From it:

| Value | Location |
|---|---|
| `wellness_score` (0.0–1.0), `fit_for_duty`, `concerns`, `recommendations`, `notes` | `CounselorAssessment` (`:83-90`), via `profile.latest_assessment()` (`:212`) |
| `trust_drift`, `confidence_drift`, `hebbian_drift`, `personality_drift` — **drift from baseline** | `CounselorAssessment` (`:78-82`) |
| Rolling drift over the last N assessments | `profile.drift_trend(metric, window)` (`:215`) |
| `alert_level`, `confabulation_rate`, `memory_integrity_score`, `self_corrections`, `peer_catches` | `CognitiveProfile` (`:255-270`) |

The access pattern is already precedented in the codebase, at AD-568d
(`cognitive_agent.py:10040-10046`):

```python
_counselor_agents = self._runtime.registry.get_by_pool("counselor")
if _counselor_agents:
    _counselor = _counselor_agents[0]
    if hasattr(_counselor, 'get_profile'):
        _profile = _counselor.get_profile(self.id)
```

An agent already reaches into the Counselor's profile for its own `confabulation_rate` to
tune episodic retrieval. It simply never surfaces any of it to the agent itself.

---

## The governance question this AD must settle

**Wellness is the first telemetry domain where the subject matters.**

Trust scores, Hebbian weights and episode counts are operational facts about a mesh node.
A wellness assessment is a clinical judgement about a crew member — `concerns` is
free-text written by the Counselor's LLM about that agent's condition, and `fit_for_duty` is
a determination with consequences for promotion (`COUNSELOR_WELLNESS_PROMOTION`,
`config.py:38`).

### The rule

**First-person: allowed and default-on. Third-person: not on any agent-reachable path.**

- `self_query` (AD-1258) is self-scoped *by schema* — its input has no subject field and
  the subject comes from the run's authoritative `context["agent_id"]`
  (`agentic_dispatch.py:2165-2172`). Adding a `wellness` domain there exposes an agent only
  to itself.
- `IntrospectionAgent._agent_info` is third-person and parameterized. After AD-1259 it reads
  from the same service. **It must not gain the wellness domain**, because its output is
  Captain-facing *and* it is the surface a future change could accidentally expose to the
  mesh.
- The Captain reads crew wellness through the existing `routers/counselor.py` endpoints
  (`:49`, `:93`) and the Counselor's own `counselor_wellness_report` intent. That path is
  unchanged and is where it belongs.

This is Minimal Authority applied to a data class rather than to an action: the first-person
and third-person surfaces are the same *service* but must not be the same *offer*.

### Why this is not over-caution

If wellness rides into the generic snapshot, then the moment anyone adds a third-person
lookup to the agentic loop — which AD-1258's rejected-alternatives table shows is a
recurring temptation — a crew agent reads a colleague's clinical assessment with no gate,
because the gate was never where the data was. Put the boundary at the domain, once.

---

## Solution

**A. The service gains a `wellness` domain, collected only when explicitly requested.**

Unlike the five existing domains, `wellness` is **not** included in `get_full_snapshot`'s
default iteration. It is opt-in per call. This keeps the passive injection block
(four cognitive paths, every introspective turn) byte-identical unless a caller asks, and it
means the expensive/sensitive domain is never collected by accident.

**B. `self_query` accepts `"wellness"` in its `domains` array.**

**C. Nothing else changes.** `_agent_info` does not gain it. The `[MESH …]` allowlist does
not gain it. No new intent is registered.

### Why not the alternatives

| Rejected | Why |
|---|---|
| Add `wellness` to `get_full_snapshot`'s default domain list | Every introspective turn on four paths would collect a clinical assessment nobody asked for, and the passive block would stop being byte-identical. Opt-in is both cheaper and safer. |
| Register a `counselor_assess` mesh tool so an agent can request a *fresh* assessment | A fresh assessment is an LLM call the Counselor owns and rate-limits (AD-503 sweep). Reading the latest stored one is a read; commissioning a new one is work. Different AD if ever wanted. |
| Let an agent read a colleague's wellness when same-department | Department is not a clinical relationship. The Counselor is the relationship. |
| Gate on rank instead of on subject | Rank is trust-derived; a struggling agent would be denied its own wellness data precisely when it matters most. Subject-scoping is the correct axis. |

---

## Implementation

### Section 1 — `get_wellness_state`

**`src/probos/cognitive/introspective_telemetry.py`**

```python
    async def get_wellness_state(self, agent_id: str) -> dict[str, Any]:
        """AD-1260: the Counselor's latest assessment of this agent.

        Opt-in — deliberately absent from ``get_full_snapshot``'s default domains,
        because a clinical assessment should be collected when asked for and not
        on every turn that mentions the word "you".
        """
```

- Resolve the Counselor via `self._runtime.registry.get_by_pool("counselor")`, first
  element, `hasattr(..., 'get_profile')` — mirroring AD-568d verbatim. Absent pool, empty
  pool, or missing method ⇒ return `{}`. Never raise.
- From `profile.latest_assessment()`: `wellness_score`, `fit_for_duty`, `concerns`
  (**capped at 3 entries**), `trust_drift`, `confidence_drift`, `hebbian_drift`.
- From the profile: `alert_level`, `confabulation_rate`, `memory_integrity_score`.
- From `profile.drift_trend("trust_drift")`: `trust_drift_trend`.
- `assessed_at` from the assessment timestamp, so a stale assessment is visibly stale rather
  than silently presented as current.
- Apply `format_trust` (post-AD-1259 convention) to every float.
- **Do not include `recommendations` or `notes`.** Those are the Counselor's advice *to the
  Captain* about the agent. Surfacing them to the subject changes what the Counselor can
  safely write down. Record this reasoning inline, in one line.

### Section 2 — opt-in collection

`get_full_snapshot` (`:146`) keeps its five-domain tuple **unchanged**. Add an optional
parameter:

```python
    async def get_full_snapshot(
        self, agent_id: str, *, extra_domains: tuple[str, ...] = (),
    ) -> dict[str, Any]:
```

Default `()` ⇒ byte-identical to AD-1259. `("wellness",)` ⇒ the wellness getter runs too,
through the same per-domain `try/except` so one failing domain never sinks the others.

### Section 3 — the renderer

Add a `Wellness:` line to `render_telemetry_context`, rendered **only** when the domain is
present and non-empty — the same discipline as the AD-1258 social block. Absent domain ⇒ no
line, so every existing caller's output is unchanged.

Include the assessment age in the line. A wellness score with no date is a claim about the
present made from the past.

Gap-regex-safe: verify the rendered strings against the real imported
`probos.cognitive.decomposer.is_capability_gap` before committing.

### Section 4 — `self_query` accepts the domain

**`src/probos/tools/self_query_tool.py`** — add `"wellness"` to the `domains` enum in
`input_schema` and to the getter map. The tool's `description` gains one sentence: this
reports the Counselor's latest assessment **of you**.

**Do not** add `wellness` to the tool's default (all-domains) behaviour. Omitting `domains`
must continue to mean the five operational domains. Asking for a clinical assessment should
be an act, not a default.

---

## Tests

New file `tests/test_ad1260_wellness_domain.py`.

**Collection**
1. Populated profile ⇒ `wellness_score`, `fit_for_duty`, `alert_level`, drift fields present.
2. `concerns` longer than 3 ⇒ capped at 3.
3. `recommendations` and `notes` are **absent** from the returned dict. Assert over keys.
4. No counselor pool ⇒ `{}`, no raise.
5. Empty counselor pool ⇒ `{}`, no raise.
6. Counselor present, no profile for this agent ⇒ `{}`, no raise.
7. Profile present, zero assessments ⇒ profile-level fields only, no crash on `latest_assessment()` returning `None`.
8. `get_profile` raising ⇒ `{}`, no propagation.

**Opt-in**
9. `get_full_snapshot(agent_id)` ⇒ exactly the five AD-1259 domains, **no** `wellness` key.
10. `get_full_snapshot(agent_id, extra_domains=("wellness",))` ⇒ six keys.
11. The wellness getter raising during an `extra_domains` call ⇒ other five still returned.

**Renderer**
12. Wellness present ⇒ `Wellness:` line with score and assessment age.
13. Wellness absent ⇒ **no** `Wellness:` substring. Existing snapshots render byte-identically.
14. Rendered wellness strings return `False` from the real `is_capability_gap`.

**Boundary — the point of the AD**
15. `_agent_info` output contains **no** wellness key, with the domain fully wired. Assert
    over the key set. This test is the boundary; it must be readable as such.
16. `self_query` with `domains=["wellness"]` returns it; with `domains` omitted, does not.
17. `self_query` still cannot name a subject: `params={"agent_id": "other"}` with
    `domains=["wellness"]` returns the *caller's* wellness.
18. **Crossing test:** a Counselor with a real stored profile → `self_query` → rendered
    string contains that agent's actual `wellness_score`. Collect → render → offer, one test.

---

## Acceptance criteria

- [ ] `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q` green; report count before and after.
- [ ] Test #9 proves the passive injection block is unchanged for every existing caller.
- [ ] Test #15 fails if anyone later adds wellness to `_agent_info`.
- [ ] `tests/test_ad588_telemetry_introspection.py` and `tests/test_ad1259_*.py` pass unmodified.
- [ ] Run the `Diff Reviewer` subagent on the staged diff with a different model than the author. Ask it specifically whether a crew agent can reach another agent's wellness by any path.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Adjacent, do not build

- **Commissioning a fresh assessment from an agent turn.** That is work the Counselor owns and rate-limits, not a read.
- **Surfacing `recommendations` / `notes` to the subject.** Deliberately excluded above.
- **A wellness view in the HXI for the Captain.** `routers/counselor.py` already serves it.
- **AD-589 confabulation-drift as a domain.** Related and tempting; it is a different question (is my self-report faithful?) with a different consumer. No number minted.
