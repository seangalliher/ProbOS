# AD-1258 — the telemetry snapshot renders every domain it collects, and the agent can ask for it

**Status:** ready to build
**Issue:** [#1308](https://github.com/seangalliher/ProbOS/issues/1308)
**Dependencies:** AD-588 (`IntrospectiveTelemetryService`), AD-1065 (conversational agentic loop), AD-1072 (the tool-registration pattern this copies)
**Estimated tests:** 18–22 new, one existing file amended

---

## Numbering

`d:\ProbOS\.venv\Scripts\python.exe scripts/gen_ad_ledger.py --check` → `AD/BF ledger is current`

| Authority | AD ceiling |
|---|---|
| GitHub, all states (authoritative) | **AD-1256** filed (#1302); highest issue #1307 (BF-841) |
| Untracked in-flight prompts | **AD-1250 … AD-1257** claimed (`prompts/ad-125{0..5,7}-*.md`) |
| Ledger (`docs/development/open-ads-report.md`) | **AD-1250** allocated — its issue layer cannot see the untracked prompts, so its "next free" is STALE |

- **This work is AD-1258** (#1308). Next free AD after this one: AD-1259 (claimed by the follow-on prompt in this wave).
- This wave allocates **AD-1258** (#1308), **AD-1259** (#1309), **AD-1260** (#1310), **AD-1261** (#1311). Next free after the wave: **AD-1262**.

---

## Problem

The Captain asked the Ship's Counselor to describe herself in a 1:1 chat. She answered
accurately about her age, trust score, cognitive zone and episode count — and then said,
correctly, that she could not speak to her wellness score, her Hebbian weights, or how her
collaboration patterns compare to her baseline.

She was not confabulating. She was reading a context block that is missing a domain the
system had already computed for her, on a turn where she had no way to ask for anything else.

### 1 — the renderer drops a domain the snapshot collects

`get_full_snapshot` (`introspective_telemetry.py:146`) iterates five domains, including
`("social", self.get_social_state)` at `:154`. `get_social_state` (`:118`) computes
`routing_affinities` (top-3 Hebbian weights inbound to the agent) and `interaction_breadth`
(count of distinct intent types across the last 20 trust events).

`render_telemetry_context` (`:164`) renders memory, trust, cognitive zone and temporal.
It never reads `snapshot["social"]`.

Verified by execution, not by reading:

```
$ .venv/Scripts/python.exe -c "..."   # snapshot with a populated social domain
=== RENDERED TELEMETRY ===
--- Your Telemetry (ground self-referential claims in these metrics) ---
Memory: 124 episodes (cosine similarity retrieval, no offline processing)
Trust: 0.512 (0 observations, uncertainty ±0.221)
Cognitive zone: GREEN
Uptime: 1.0h | Age: 3096.0h
...
=== CHECKS ===
social_rendered: False
breadth_rendered: False
```

`grep -n "social" src/probos/cognitive/introspective_telemetry.py` returns exactly five
hits: the `def` at `:118`, three lines inside it, and the domain tuple at `:154`. Zero in
the renderer.

So the Hebbian query runs on every introspective turn, at real cost, and the result is
discarded before it reaches the agent. **This is the precise thing the Counselor said she
could not see.**

### 2 — why the tests did not catch it

`tests/test_ad588_telemetry_introspection.py::TestRenderTelemetryContext` (`:524`). Every
case passes `"social": {}` — including the one named `test_renders_full_snapshot` (`:526`).
The domain is in the fixture and empty in every one of them. No assertion pins the defect
as contract, so nothing here needs to be un-asserted; the seam was simply never crossed.

### 3 — the agent cannot ask for anything else

The telemetry block is a **push**. It appears only when
`CognitiveAgent._is_introspective_query` (`:8548`) matches one of six regexes (`:8538`).
There is no **pull**. Enumerated:

| Route | Verified state |
|---|---|
| Agentic-loop tools | `tool_ids` (`agentic_dispatch.py:1999-2006`) unions 13 groups; `mesh_ids` resolves to `['web_search', 'read_page', 'http_fetch']` (`_MESH_TOOL_SPECS:1354`). No introspection tool exists in the registry — `grep "registry.register("` across `src/` returns zero introspection registrations. |
| AD-869 `[MESH …]` seam | `_MESH_READ_INTENT_POOLS` (`dm/reply_pipeline.py:41`) = `list_directory, read_file, read_page, search_content, search_files, stat_file, web_search`. Intersection with the 11 `IntrospectionAgent` intents: **empty**. |
| Capability affordances | `IntrospectionAgent.intent_descriptors` (`agents/introspect.py:35-47`) declare `usage_hint=""` on all 11, so `capability_affordances()` (`cognitive_agent.py:2752`) never advertises them. |
| `delegate_task` | Resolves by callsign (`delegate_task_tool.py:142-144`). `CallsignRegistry.load_from_profiles()` yields 15 types; `introspect` is not among them (no `config/standing_orders/crew_profiles/introspect.yaml`). |

`search_capabilities` **can** surface these intents — it indexes a `mesh_intents` axis
(`search_capabilities_tool.py:37-42`). So an agent can discover that `system_health` exists
and then have no path to call it. Discovery without invocation is DP 13(c): a refusal where
there should be a result.

### What this AD does *not* claim

It does not claim `IntrospectionAgent` should be reachable from a DM. It should not be —
see AD-1259 and AD-1260 for why the first-person and third-person surfaces must stay
separate. This AD builds the first-person surface that does not exist yet.

---

## Solution

Two moves. Each leaves the tree green on its own.

**A. The renderer renders every domain the snapshot collects.** A domain that is collected
and dropped is worse than one that is never collected: it costs the query and returns
nothing, and the absence is invisible.

**B. A `self_query` tool, self-scoped by construction.** The agent pulls its own telemetry
on demand, by domain, inside the AD-1065 loop — instead of receiving a fixed push only when
a regex happens to fire.

### Why `self_query` is structurally safe

`WorkItemAgenticExecutor.run` writes the run's **authoritative identity** into the tool
context (`agentic_dispatch.py:2165-2172`):

```
        # AD-1129: accepted compatibility extras are copied first; the run's
        # authoritative identity and explicit thread provenance always win.
        _context.update({"agent_id": agent_id, ...})
```

`SelfQueryTool.invoke` reads `context["agent_id"]` and **takes no agent identifier in its
input schema at all**. An agent therefore cannot name a subject. Self-scope is a property of
the schema, not of a check that could be forgotten — which is what makes this the cheapest
governance case in the tool catalog and why it needs no new gate.

### Why not the alternatives

| Rejected | Why |
|---|---|
| Add the introspect intents to `_MESH_READ_INTENT_POOLS` | Those intents are third-person and parameterized (`agent_type` / `agent_id`). Admitting them to a DM hands every crew agent a read on a colleague's trust score. That is AD-1260's boundary question, not a line in an allowlist. |
| Add `usage_hint` to `IntrospectionAgent.intent_descriptors` | Same objection, plus it advertises a capability the seam still refuses — the affordance and the allowlist would disagree. |
| Give `introspect` a callsign so `delegate_task` reaches it | Makes a utility-tier substrate agent a crew member to work around a missing tool. Tier misclassification (`copilot-instructions.md`, "Agent tier correctness"). |
| Widen `_INTROSPECTIVE_PATTERNS` so the push fires more often | Treats the symptom. A regex cannot anticipate what the agent needs to know, which is exactly why the pull is the fix. |
| Put wellness / authority / organs in this AD | Each is its own domain with its own dependency and its own governance question. AD-1260, AD-1261, and the deferred list below. |

---

## Implementation

### Section 1 — the renderer renders `social`

**`src/probos/cognitive/introspective_telemetry.py`**

SEARCH anchor — the temporal block and the trailer, at the end of
`render_telemetry_context`:

```
        if time_parts:
            lines.append(" | ".join(time_parts))

        lines.append("")
        lines.append(
            "When discussing yourself, cite these numbers. You may express warmth and"
        )
```

Insert a social block **between** `if time_parts:` and the `lines.append("")` trailer, so
the domain order matches `get_full_snapshot`'s iteration order:

```python
        # AD-1258: the fifth domain get_full_snapshot collects. Rendering it is
        # what makes the collection observable -- before this it was queried and
        # dropped.
        soc = snapshot.get("social", {})
        soc_parts = []
        affinities = soc.get("routing_affinities")
        if affinities:
            rendered = ", ".join(
                f"{a.get('intent', '?')} {a.get('weight', 0)}" for a in affinities
            )
            soc_parts.append(f"routing affinities — {rendered}")
        if "interaction_breadth" in soc:
            soc_parts.append(f"interaction breadth: {soc['interaction_breadth']} intent types")
        if soc_parts:
            lines.append(f"Collaboration: {' | '.join(soc_parts)}")
```

Constraints on this block:

- **Empty social renders nothing.** `{}` must produce no `Collaboration:` line, so the four
  existing `TestRenderTelemetryContext` cases (all of which pass `"social": {}`) stay green
  unchanged. Do not amend them.
- **Gap-regex safe.** Verified against the real imported
  `probos.cognitive.decomposer.is_capability_gap`: both the populated and the empty-state
  strings return `safe`. Re-run that check if you reword.
- Do **not** add a "no affinities recorded yet" line. An absent line is honest; a line
  asserting absence invites the model to narrate it.

### Section 2 — `SelfQueryTool`

**New file: `src/probos/tools/self_query_tool.py`**

Duck-typed to the AD-423a `Tool` protocol — no inheritance, mirroring
`tools/search_capabilities_tool.py`, which is the closest existing sibling (read-only,
runtime-constructed, `ToolType.UTILITY_AGENT`).

```python
class SelfQueryTool:
    """AD-1258: read your own live telemetry, by domain.

    Self-scoped by construction: the subject is ``context["agent_id"]``, the run's
    authoritative identity, and the input schema has no agent field. There is no
    argument an agent could pass to name a different subject.
    """

    def __init__(self, *, runtime: Any) -> None: ...
```

- `tool_id` → `"self_query"`; `tool_type` → `ToolType.UTILITY_AGENT`.
- `input_schema`: one optional property, `domains`, an array of strings from
  `["memory", "trust", "cognitive", "temporal", "social"]`. Omitted ⇒ all five. **No
  `agent_id`, no `agent_type`, no `callsign`.**
- `invoke(params, context)`:
  1. `agent_id = (context or {}).get("agent_id", "")`. Empty ⇒ honest-degrade `ToolResult`
     with an `error`, never a raise, never a fallback to some other subject.
  2. Resolve `runtime._introspective_telemetry`. Absent ⇒ honest-degrade `ToolResult`.
  3. Requested domains ⇒ call the matching per-domain getters directly
     (`get_memory_state` / `get_trust_state` / `get_cognitive_state` /
     `get_temporal_state` / `get_social_state`), so a narrow request pays for one query
     rather than five. All five requested ⇒ call `get_full_snapshot`.
  4. Unknown domain names are dropped, and the dropped names are named back in the result
     so the miss is visible rather than silent (AD-1148/DD-3 marking, not eliding).
  5. Output: `{"agent_id": ..., "domains": {...}, "rendered": <render_telemetry_context>}`.
     Both shapes — structured for reasoning, rendered for quoting.
- **Never raises out of `invoke`.** Every failure becomes a `ToolResult` with `error` set
  (AD-592), matching `SearchCapabilitiesTool`.
- The `description` property is the model's only instruction. It must say: this reports your
  own telemetry and nothing about another crew member; use it before describing your own
  state. Gap-regex-safe.

### Section 3 — registration and the flag

**`src/probos/cognitive/agentic_dispatch.py`**

SEARCH anchor — the AD-1072 `search_ids` block (`:1815-1838`), which is the pattern to
copy verbatim in shape:

```
        search_ids: list[str] = []
        if (
            getattr(agentic_tools_cfg, "tool_search_enabled", False)
            and registry is not None
        ):
```

Add a sibling `self_query_ids` block **after** the `delegate_ids` block, gated on
`getattr(agentic_tools_cfg, "self_query_enabled", False)`, registering idempotently with
`provider="AD-1258"`, `tags=["self_query", "introspection"]`, and honest-degrading to `[]`
inside `except Exception` with a WARNING that names the consequence.

Then extend the union (`:1999-2006`) — append `*self_query_ids` **last**, so with the flag
off `tool_ids` is byte-identical to HEAD:

```
                *publish_ids, *browser_ids, *self_query_ids,
```

**`src/probos/config.py`** — add to `AgenticToolsConfig` (`:6442`):

```python
    self_query_enabled: bool = False  # AD-1258
```

Default **False**. Extend the class docstring with a short AD-1258 paragraph in the existing
style.

**`config/system.yaml`** — under `agentic_tools:` (`:617`), add `self_query_enabled: true`
with a comment stating what it buys and that the tool is self-scoped by schema. The ship
turns it on; the code default stays off.

> No permission block. The tool registers with empty `default_permissions`, so the
> registry's Layer-3 ship-wide default grants READ to every rank — the same posture as the
> AD-909 mesh reads. A per-agent off-switch remains available through the AD-423/894
> `ToolAccessGrant` restriction path. Do not add a rank matrix: rank is trust-derived, and
> denying a probationary agent the ability to read its *own* trust score is the opposite of
> what the ladder is for.

---

## Tests

New file `tests/test_ad1258_self_knowledge.py`.

**Renderer (Section 1)**
1. Populated `social` ⇒ `Collaboration:` line present, with the intent name and weight.
2. Populated `routing_affinities`, absent `interaction_breadth` ⇒ affinity segment only.
3. Absent `routing_affinities`, present `interaction_breadth` ⇒ breadth segment only.
4. `"social": {}` ⇒ **no** `Collaboration:` substring anywhere in the output.
5. `social` key entirely missing ⇒ no crash, no `Collaboration:` line.
6. Malformed affinity entries (missing `intent` / `weight` keys) ⇒ renders placeholders, does not raise.
7. **Crossing test:** build a runtime whose `hebbian_router` and `trust_network` return
   real-shaped data, call `get_full_snapshot` then `render_telemetry_context` on its
   output, and assert the Hebbian intent name appears in the rendered string. This is the
   seam the AD-588 tests never crossed — it must be a single test spanning collect → render,
   not two tests either side of it.
8. Both the populated and empty renderings return `False` from the **real imported**
   `probos.cognitive.decomposer.is_capability_gap`.

**`SelfQueryTool` (Section 2)**
9. Happy path, no `domains` ⇒ all five domains present in `output["domains"]`.
10. `domains=["trust"]` ⇒ only `trust` present, and the four unrequested getters were **not** awaited.
11. `context` missing `agent_id` ⇒ `ToolResult.error` set, `success` False, nothing queried.
12. `runtime._introspective_telemetry` is `None` ⇒ honest-degrade `ToolResult`, no raise.
13. A getter raising ⇒ `invoke` returns a `ToolResult`, never propagates.
14. Unknown domain name ⇒ dropped, and named in the output.
15. **`input_schema` contains no property whose name contains `agent`, `id`, `callsign` or
    `subject`.** Assert over the parsed schema dict, not over source text — a source scan
    cannot tell a requirement from a mention of it.
16. A subject-naming key in `params` (`{"agent_id": "someone-else"}`) is ignored: the result's
    `agent_id` equals the one from `context`.
17. `output["rendered"]` equals `render_telemetry_context(output["domains"])` for a full query.

**Registration (Section 3)**
18. Flag off ⇒ `self_query` absent from the assembled `tool_ids`.
19. Flag on ⇒ `self_query` present, and present in the offered LLM definitions post-dedupe.
20. Registration raising ⇒ the run still assembles its other tools (honest-degrade).
21. Config default is `False` on a bare `AgenticToolsConfig()`.
22. Idempotency: two assemblies in one process register once.

**Amend, do not rewrite:** `tests/test_ad588_telemetry_introspection.py` — add one case to
`TestRenderTelemetryContext` proving a populated social domain renders. Leave the four
existing `"social": {}` cases exactly as they are; they are the byte-identity guarantee.

---

## Acceptance criteria

- [ ] `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q` green; report the count before and after.
- [ ] `tests/test_ad588_telemetry_introspection.py` passes **unmodified except for the one added case**.
- [ ] With `self_query_enabled: false`, `tool_ids` is byte-identical to HEAD for a run with every other flag at its shipped value. Prove it with an assertion, not by inspection.
- [ ] `tests/test_layer_boundaries.py` green — `probos.tools.self_query_tool` imports from `probos.tools.protocol` only; it must **not** import `cognitive.*` at module level.
- [ ] The seam test (#7) fails if the Section 1 block is reverted. Verify by reverting it locally and watching that specific test go red.
- [ ] Run the `Diff Reviewer` subagent on the staged diff with a different model than the author, and address blockers before committing.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Adjacent, do not build

- **Wellness in the snapshot.** AD-1260. It needs the Counselor and it needs a confidentiality decision.
- **Authority in the snapshot** ("what am I permitted to do"). AD-1261.
- **`_agent_info` reading from the service.** AD-1259. Do not touch `agents/introspect.py` in this AD.
- **Organs (`Spine.organs()`), per-agent episodic breakdown, trust-event causes, assigned work.** Deferred; no numbers minted. Each is a domain on the same service once AD-1259 makes that service the single source of truth.
- **Widening `_INTROSPECTIVE_PATTERNS`.** Explicitly rejected above.
- **A `self_query` equivalent for the ward-room / proactive paths.** Those run the single-pass path, not the tool loop. The renderer fix (Section 1) already reaches them, which is most of the value.
