# AD-1261 — the authority domain: an agent can read its own ceiling

**Status:** ready to build
**Issue:** [#1311](https://github.com/seangalliher/ProbOS/issues/1311)
**Dependencies:** AD-1258 (#1308, `self_query`), AD-1259 (#1309, the service is the single source of truth)
**Estimated tests:** 14–16 new

---

## Numbering

Allocated in the AD-1258 wave (#1308, #1309, #1310, #1311). Next free after the wave: **AD-1262**.

---

## Problem

An agent knows what it was *offered* this turn. It does not know what it *holds*.

Those are different, and the difference is exactly where DP 13 lives.

### What the agent can see today

The AD-1065 loop hands the model a tool array assembled from thirteen groups
(`agentic_dispatch.py:1999-2006`). Each group is gated by some combination of a config flag,
a registry lookup, and `registry.check_permission(...)`. A tool the agent is denied is
**silently absent** — that is the documented, deliberate honest-degrade at every one of those
blocks ("an agent whose department/rank is denied simply does not see the tool").

So from inside the turn, three very different situations are indistinguishable:

| Situation | What the agent observes |
|---|---|
| The capability does not exist on this ship | nothing in the array |
| It exists but the config flag is off | nothing in the array |
| It exists, is on, and **this agent is denied it** | nothing in the array |

`search_capabilities` (AD-1072) closes the first gap — it indexes tools, skills and mesh
intents, so an agent can learn a thing exists. It does not report **whether the caller holds
it**. Discovery answers *what is on the ship*; it does not answer *what am I permitted to do*.

### Why that is a DP 13 defect and not a missing nicety

DP 13(c): *"Authority routes capability; it does not ration it. An agent whose rank or
department cannot authorise something escalates it to one that can; it does not answer 'you
may not.' A refusal that ends the work is a capability ceiling wearing a governance
costume."*

**An agent that cannot see its own ceiling cannot escalate against it.** Escalation requires
naming what is needed and who could authorise it. With a silently-absent tool the agent has
nothing to name, so the only reachable behaviours are (a) confabulate a verb — the BF-651 /
AD-1064 class — or (b) refuse. Both are the failure DP 13 exists to prevent, and the
mechanism producing them is an information gap, not a policy gap.

DP 13(a): *"A capability ceiling must be a decision, never an inheritance."* A ceiling nobody
can observe cannot be a decision. It is inherited by definition.

### The data is already assembled, for a different consumer

`acm.py:362-380` resolves exactly this today, for the ACM profile:

```python
granted_tools = [
    reg.tool_id
    for reg in runtime.tool_registry.list_tools()
    if runtime.tool_registry.check_permission(
        agent_id, reg.tool_id, ToolPermission.READ,
        agent_department=agent_department, agent_rank=agent_rank,
    )
]
```

`ToolRegistry.resolve_permission` (`tools/registry.py:227`) returns the **effective level**
rather than a boolean, through the documented five-layer chain (scope → restriction → rank
gate → Captain override). Identity resolves through the same path the loop already uses:
`_resolve_agentic_identity` (`agentic_dispatch.py:~310`) reads department from
`ontology.get_agent_department(agent_type)` (falling back to
`standing_orders.get_department`) and rank from `Rank.from_trust(trust_network.get_score(id))`.

Every input exists. Nothing surfaces it to the subject.

---

## Solution

**A `authority` domain on the telemetry service, reporting what *this* agent holds.**

Three parts, and the third is the one that matters:

1. **Identity** — department, rank, and the trust score the rank derives from. Rank is
   trust-derived, so an agent that can see the number can see why the ceiling sits where it
   does rather than experiencing it as arbitrary.
2. **Held capabilities** — tool ids with their **effective permission level**, from
   `resolve_permission`. Not a boolean; `read` versus `write` versus `none` is the whole
   point.
3. **Withheld capabilities** — registered, enabled tools that resolve to `NONE` for this
   agent, **named**. This is the inversion of the silent-absence default and the reason the
   AD exists.

Part 3 must be paired with the escalation route, in the same breath, or it becomes a list of
grievances. The domain therefore also carries the department's authorising billet where the
ontology can supply one, so the agent knows who to ask.

### Why not the alternatives

| Rejected | Why |
|---|---|
| Extend `search_capabilities` to report holder status | It is a ship-wide catalog search with its own ranking and result cap; folding per-caller permission resolution into it would make a discovery tool answer an identity question, and the cap would silently truncate the withheld list. Separate question, separate surface. |
| Have the loop annotate the offered array with what was withheld | Bloats every turn's tool payload with information almost no turn needs, and the offer is assembled per-turn from thirteen scattered blocks. Reading the registry once, on request, is cheaper and lives in one place. |
| Grant more tools instead | Not the defect. The ceiling may be entirely correct; the problem is that it is unobservable. DP 13(b): the fix is a governed path, not a removed control. |
| Emit an event when a tool is withheld | Telemetry for the Captain, not knowledge for the agent. The agent needs it *during* the turn it is blocked, which is a pull. |
| Report withheld tools to every agent by default | See the scope note below — the withheld list is opt-in for a reason. |

### Scope note — why `authority` is opt-in like `wellness`

`resolve_permission` across the full catalog is O(tools) per call and the result is a wall of
text on a ship with a large registry. Collecting it on every turn that trips
`_is_introspective_query` would be waste. It joins `wellness` (AD-1260) as an
`extra_domains` member, absent from `get_full_snapshot`'s default five.

---

## Implementation

### Section 1 — `get_authority_state`

**`src/probos/cognitive/introspective_telemetry.py`**

```python
    async def get_authority_state(self, agent_id: str) -> dict[str, Any]:
        """AD-1261: what this agent is permitted to do, and what it is not.

        Withheld capabilities are named rather than silently absent: an agent that
        cannot see its own ceiling can only refuse, never escalate (DP 13(c)).
        """
```

- Resolve `agent_type` from `self._resolve_agent(agent_id)` (`:29`), then department via
  `runtime.ontology.get_agent_department(agent_type)` with the
  `probos.cognitive.standing_orders.get_department` fallback, then rank via
  `Rank.from_trust(trust_network.get_score(agent_id)).value`. **Mirror
  `_resolve_agentic_identity`'s resolution order** so the reported authority matches the
  authority the loop actually applies. Do not re-derive it differently — that is the AD-1259
  divergence class.
- Walk `registry.list_tools()`, call `resolve_permission(...)` per tool, and partition:
  `held` = `[{tool_id, permission}]` for anything above `NONE`; `withheld` = tool ids at
  `NONE`.
- **Cap both lists** (suggest 25 each) and report the truncation count explicitly — marked,
  not silent (AD-1148/DD-3). A registry larger than the cap must not produce a quietly
  partial answer.
- `escalation_route`: the authorising billet for the agent's department where
  `runtime.ontology` can supply one; otherwise the string identifying the Captain as the
  authority. Never empty — an escalation route that resolves to nothing is the refusal this
  AD is trying to prevent.
- Any resolution failure ⇒ omit that key, return what did resolve. Never raise.
- **Fail toward visibility, not toward silence:** if permission resolution fails wholesale,
  return `{}` and log a WARNING naming the consequence. Do not return an empty `withheld`
  list — that asserts "nothing is withheld", which is a claim, not a degradation.

### Section 2 — opt-in collection

`get_full_snapshot`'s default domain tuple stays at five. `"authority"` joins `"wellness"`
as a valid `extra_domains` member (the parameter added in AD-1260).

### Section 3 — the renderer

An `Authority:` block, rendered only when the domain is present and non-empty. Order:
identity → held → withheld → escalation route. The withheld line must sit adjacent to the
escalation line; a withheld list without a route is the grievance failure mode.

Gap-regex-safe — and this block needs the check more than any other in the wave, because its
natural phrasing ("not available to you", "you lack") is exactly what
`_CAPABILITY_GAP_RE` (`decomposer.py:50`) matches. Verify every string against the **real
imported** `probos.cognitive.decomposer.is_capability_gap`. Phrase withheld entries as a
plain list under a neutral heading plus the route, never as a sentence about what the agent
is unable to do.

### Section 4 — `self_query` accepts the domain

Add `"authority"` to the tool's `domains` enum and getter map. Not in the default set.

The tool `description` gains one sentence naming the act: read your own permissions and your
escalation route before reporting that something is out of reach.

---

## Tests

New file `tests/test_ad1261_authority_domain.py`.

**Collection**
1. Held tools carry their **effective level**, not a boolean.
2. A tool resolving to `NONE` appears in `withheld`, not in `held`.
3. Department and rank match what `_resolve_agentic_identity` produces for the same runtime.
   **Assert equality against that function's output**, not against a hand-written expectation
   — this is the anti-divergence test.
4. Rank reflects trust: two agents with different trust scores get different ranks.
5. Registry larger than the cap ⇒ both lists capped and the truncation count reported.
6. `escalation_route` is non-empty for a department with a billet.
7. `escalation_route` is non-empty for a department **without** one (Captain fallback).
8. No tool registry ⇒ `{}`, no raise.
9. No ontology ⇒ department falls back to `standing_orders.get_department`, still resolves.
10. `resolve_permission` raising ⇒ `{}` and a WARNING; **not** an empty `withheld` list.
    Assert the key is absent rather than present-and-empty.

**Opt-in**
11. `get_full_snapshot(agent_id)` ⇒ no `authority` key.
12. `extra_domains=("authority",)` ⇒ present. `("wellness", "authority")` ⇒ both.

**Renderer**
13. Present ⇒ `Authority:` block with held, withheld and route.
14. Absent ⇒ no `Authority:` substring; existing renderings byte-identical.
15. **Every rendered authority string returns `False` from the real `is_capability_gap`.**
    Parametrize over a withheld list, an empty withheld list, and a truncated one.

**Crossing**
16. A runtime with one granted and one restricted tool → `self_query(domains=["authority"])`
    → the rendered string names the restricted tool **and** the escalation route. Resolve →
    render → offer, in one test.

---

## Acceptance criteria

- [ ] `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q` green; report count before and after.
- [ ] Test #3 fails if the identity resolution here is changed to differ from `_resolve_agentic_identity`.
- [ ] Test #15 fails if any withheld phrasing trips the gap regex.
- [ ] Test #11 proves the default snapshot is unchanged for every existing caller.
- [ ] Run the `Diff Reviewer` subagent on the staged diff with a different model than the author. Ask it specifically whether the withheld list can ever be reported as empty when resolution failed.
- [ ] Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Adjacent, do not build

- **Acting on the escalation route** — actually filing a capability request from the loop. `capability_request_store` and the AD-855 gap driver exist; wiring the agent to file one is a real AD and is not this one. This AD makes escalation *possible* by making the ceiling *legible*.
- **Changing any permission default, rank matrix, or config flag.** This AD reports the ceiling. It does not move it.
- **Reporting another agent's authority.** Same boundary as AD-1260: `self_query` is self-scoped by schema.
- **Skills and mesh intents in the authority domain.** v1 is tools, because tools are where `resolve_permission` gives a real answer. Extending to the other two axes is a follow-on; no number minted.
