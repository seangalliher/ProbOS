# Capability Affordances — How a Crew Agent Knows What It Can Use

*Status: Design analysis + recommendations. Repo: OSS (how the product works).*

*Companion to [`skills-and-tools-architecture.md`](skills-and-tools-architecture.md).
That doc covers **provisioning** — the capability spine (Role → Skills → Tools)
and how the ACM **assigns** capabilities to a crew agent. This doc covers the
layer it stops short of: the **runtime affordance** — once an agent *has* a
capability, how does it *know it has it* and *how to invoke it* at reasoning
time? That is the layer that broke when only Yeo knew how to use web search.*

---

## 1. The problem, stated precisely

ProbOS provisions capabilities well. An agent is assigned a role, skills, and
tools through the ACM, and the decomposer (the planner) sees every registered
`IntentDescriptor` when it builds a TaskDAG. The break is one level down: an
**individual crew agent, composing a conversational reply, is not reliably told
what it can invoke or how.**

The web-search incident is the canonical symptom. The `[MESH web_search ...]`
"do-and-report" seam is crew-wide infrastructure, but the *instructions for how
to use it* were authored into **one agent's standing orders** (Yeo's). Every
other agent had the capability available through the mesh and no idea how to
reach for it. The proposed fix at the time — "move it to a higher standing-order
tier" — would have spread the wrong abstraction: standing orders are *behavioral
orders an agent must follow*, not *a manual for the tools it holds*.

The right mental model is the one GitHub Copilot and Claude Code use: **a tool
carries its own manual.** You do not write a separate briefing telling the agent
how to use `read_file`; `read_file` describes itself, and that self-description
is surfaced to whoever holds the tool. ProbOS has the pieces to do this and
mostly does not.

---

## 2. The Copilot/Claude-Code harness model (the target)

Four distinct concepts, each defined by **what it is attached to** and **how it
reaches the agent**:

| Concept | Answers | Attached to | Delivery to the agent |
|---|---|---|---|
| **Tool** | "what can I do + how do I invoke it" | the capability itself | self-describing contract (name + description + param schema), in context whenever the tool is enabled |
| **Deferred tool** | (same, but for a large catalog) | the capability | lightweight **manifest** (names) always present; full schema **lazy-loaded** on demand via search |
| **Skill** (`SKILL.md`) | "what specialized knowledge exists for this domain" | a domain | **manifest** (name + 1-line description + path) always present; **body** read on demand when a task matches |
| **Instruction** | "how should I behave" | a **scope** (repo / path / user) | always applied within that scope |

Two load-bearing properties:

1. **Affordances travel with the capability, not with the agent.** The "how to
   use" lives on the tool/skill and is surfaced to *any* holder. Nobody edits an
   agent's behavior rules to teach it a tool.
2. **Progressive disclosure.** A large catalog is carried as a cheap manifest;
   detail is fetched lazily. The agent always knows *what exists*; it loads
   *how* only when relevant.

---

## 3. Concept mapping — Copilot harness ↔ ProbOS today

| Copilot concept | ProbOS mechanism today | File / AD | Alignment |
|---|---|---|---|
| **Tool contract** (self-describing: name, description, params) | `IntentDescriptor` (`name`, `params`, `description`, `tier`, `requires_consensus`) | [`types.py:717`](../../src/probos/types.py) | **Good shape, wrong audience** — the *decomposer* reads descriptors to plan; the individual conversational agent does not receive its own invocable-capability list. No agent-facing "how to invoke" text (`usage_hint`) field exists. |
| **Tool enablement** (which tools an agent has) | intent-bus subscription from `intent_descriptors` (+ cognitive-skill-catalog intents) at wire time | [`agent_onboarding.py` `wire_agent`](../../src/probos/agent_onboarding.py) | **Aligned for routing.** Determines what an agent *handles* (provider side). Does not produce a consumer-side "what can I call" view. |
| **Deferred tools** (manifest + lazy schema load) | none — the decomposer prompt is built from **all** registered descriptors every time | `decomposer.py` / `PromptBuilder` | **Gap.** Works at today's catalog size; no progressive-disclosure path as the intent catalog grows. |
| **Skill** (`SKILL.md`: domain knowledge, matched by description, lazy-loaded) | `CognitiveSkillEntry` / `SKILL.md` loaded via standing-orders tier-7 composition | AD-596, `standing_orders.py` | **Partial match.** Knowledge-as-file exists, but it's spliced into the merged instruction string rather than offered as a manifest the agent draws from on relevance. |
| **Instruction** (behavior, scoped) | Standing orders, 4 tiers: federation → ship → department → agent | [`standing_orders.py` `get_order_tiers`](../../src/probos/cognitive/standing_orders.py) | **Well-aligned.** This is the correct home for *behavior*. The bug is that *capability affordances* got smuggled in here too. |
| **Tool manual surfaced at reasoning time** | the `_conversational_*_protocol` hook family (capability block, task protocol, notebook, mesh-read) | `cognitive_agent.py` ~L1863+ | **The inconsistent layer — see §4.** This is the real "tool manual in context," and it is applied per-agent ad hoc instead of derived from capability access. |

---

## 4. The runtime-affordance layer — what exists and why it's inconsistent

At reply-composition time a crew agent's system prompt is assembled from a chain
of overridable hooks ([`cognitive_agent.py` ~L2610-2675](../../src/probos/cognitive/cognitive_agent.py)).
The affordance-bearing hooks are:

| Hook | What it teaches | Generalization | Substrate-gated? |
|---|---|---|---|
| `_conversational_capability_block` (BF-599) | "extra live-capability grounding" | **base returns `""`** — Yeo-only override | n/a (empty by default) |
| `_conversational_task_protocol` (AD-845) | `[CREATE_TASK ...]` + `[MESH ...]` how-to | **base returns `""`** — Yeo-only override | yes, in Yeo's override |
| `_conversational_notebook_protocol` (AD-912) | `[NOTEBOOK ...]` how-to | **generalized to ALL crew** | **yes** — `""` when no records store wired |
| `_conversational_deliberate_protocol` (AD-934) | `[THINK]` how-to | all crew, flag-gated | yes (config flag) |

Two of these are the **right pattern**, two are the **wrong one**, and they sit
side by side:

- **Right (`notebook`, AD-912):** the affordance is surfaced to *every* crew
  agent and **gated on whether the substrate can back it** — its docstring is
  explicit: *"returns '' when no records store is wired, so an agent is never
  told it can save notes the substrate cannot back."* That is exactly the
  Copilot model: the manual appears for anyone who holds the capability, and
  only when the capability is real.

- **Wrong (`task`/`capability_block`, AD-845/BF-599):** the same mechanism, but
  bound to **one agent** via override. Yeo knows `[MESH]`/`[CREATE_TASK]`; nobody
  else does — not because they lack the capability, but because the manual was
  written into Yeo specifically.

And critically, **the correct derivation already exists** — it is just trapped
on Yeo. [`YeomanAgent._available_mesh_read_intents()`](../../src/probos/cognitive/yeoman.py)
(AD-870) builds `{intent: param-hint}` for exactly the read pools that have a
**live agent this turn**:

```python
for pool, intent, hint in pool_intent_hint:
    if registry.get_by_pool(pool):       # only if the pool is actually live
        out[intent] = hint               # → "[MESH web_search query=<terms>]"
```

This is the Copilot model in miniature: *derive the invocable-capability list
from what is actually reachable, and emit a how-to-invoke hint for each.* It's
the right code in the wrong place (a single agent's class) surfaced through the
wrong door (a Yeo-only hook).

---

## 5. The epic — crew-agent capability parity with the Copilot harness (AD-983)

The Captain's goal: *each crew agent should match what a GitHub Copilot agent can
do when tools and skills are added — each agent independently enables different
tools/skills, and the agent automatically knows how to use them once enabled.*

Mapping that goal onto the four gaps found in §3-§4 gives a four-part epic. Next
top-level number is **AD-983**; the epic is **AD-983** with sub-ADs **AD-983a–d**.

Filed: epic **#913**; sub-issues **AD-983a #914**, **AD-983b #915**, **AD-983c #916**,
**AD-983d #917**. AD-957 (#893, crew-wide web search) is folded into AD-983a.

| Sub-AD | Gap it closes | Copilot analogue |
|---|---|---|
| **AD-983a** (#914) — affordance layer | agent doesn't know *how to invoke* what it holds (Yeo-only) | tool self-describing contract in context |
| **AD-983b** (#915) — per-agent enablement (backend) | tools per-agent ✓ but **skills are dept/rank-gated, not per-agent**; no unified grant surface | per-agent enabled toolset |
| **AD-983c** (#916) — per-agent enablement (UI) | no Captain surface to grant/revoke (CLI only) | enabling a tool/skill on an agent |
| **AD-983d** (#917) — manifest + lazy retrieval | decomposer renders **all** descriptors → context blowout + worse selection at scale | deferred tools (manifest + `tool_search`) |

### AD-983a — capability affordance layer (the tool carries its manual)
*"Automatically able to use once enabled."* Three moves, one sub-AD:
1. **`IntentDescriptor.usage_hint`** — an optional agent-facing field declared
   **once on the capability** (`usage_hint: str = ""`, e.g. *"emit [MESH
   web_search query=<terms>] to search the web"*). `description` serves the
   *decomposer* (planning); `usage_hint` serves the *agent at reply time*
   (invocation) — exactly like a Copilot tool's self-description.
2. **A derived `capability_affordances()` composer on the `CognitiveAgent`
   base** — generalize `_available_mesh_read_intents` off Yeo. Source of truth:
   the agent's **granted** capabilities (AD-983b) ∩ the **live** serving pools.
   Output: each reachable capability's `usage_hint`, rendered into the base
   `_conversational_capability_block` so **every** crew agent gets its own real,
   current manual — no override. **Substrate-gated by construction** (the AD-912
   notebook discipline): a capability whose pool is down is simply absent, so an
   agent is never told to use something the ship can't back (BF-599/AD-592).
3. **Retire the Yeo-only overrides** — fold the `[MESH]`/`[CREATE_TASK]` teaching
   into the derived composer; Yeo keeps only genuinely *role-specific judgment*
   (the delegation *threshold* stays a standing order). **Folds in AD-957
   (#893)** — generalizes it from "web search for everyone" to "every reachable
   capability, for everyone."

### AD-983b — per-agent capability enablement (backend)
*"Each crew agent is independent and can have different tools and skills enabled."*
- **Tools:** `ToolPermissionStore` (`tools/permissions.py`) already does this —
  per-agent `issue_grant` / `revoke_grant` / restrictions, persisted + enforced
  at the agentic loop (AD-856) and in `capability_triage`. Reuse as-is.
- **Skills (the gap):** `CognitiveSkillCatalog` gates only by `department` /
  `min_rank` — there is **no per-agent skill grant**. Add a per-agent skill-grant
  overlay (same shape as `ToolPermissionStore`: grant/revoke/restrict, persisted)
  so a skill can be enabled on one agent and not its department peers.
- **Unified read surface:** `GET /api/agent/{id}/capabilities` → `{tools:[...],
  skills:[...]}` each with `{id, name, description, granted, source}` (source =
  role/dept default vs explicit grant vs restriction). `POST
  /api/agent/{id}/capabilities/set` `{kind: tool|skill, id, enabled, reason}`
  (audit-logged) — the generalization of the AD-982 vision `set` endpoint.

### AD-983c — per-agent capability enablement (UI)
*The Captain surface.* Generalize the AD-982 vision toggle into a **Capability
panel** rendered in two places (the AD-982 pattern): the `AgentProfilePanel`
(a Tools/Skills tab or expandable section) and the personnel `ServiceRecord`
(a "Capabilities" section). Each lists the agent's tools + skills with
grant/restrict toggles bound to `GET/POST .../capabilities`, optimistic with
revert-on-failure, HXI-compliant (stroke SVG, no emoji). This is what makes
"add a tool/skill to an agent" a click rather than a YAML/CLI edit.

### AD-983d — manifest + lazy retrieval (scale to hundreds)
*The deferred-tool model.* Today `PromptBuilder.build_system_prompt` renders
**every** descriptor into the decomposer prompt, and the AD-983a affordance block
would render every reachable hint. At hundreds of tools that blows the context
budget **and degrades selection** (a long flat list makes the model worse at
picking). Adopt the Copilot deferred-tool shape:
- **Manifest tier (always loaded):** intent `name` + one-line description, scoped
  to **this agent's granted** capabilities (AD-983b ∩ live pools). Hundreds of
  names is cheap; hundreds of full param tables is not. Per-agent scoping is the
  **first filter** — an agent with 8 grants never sees the other 392 (governance
  AND context reduction in one mechanism).
- **Lazy detail (`find_intents(concept)`):** a retriever over the existing
  ChromaDB / FTS5 infra (the AD-979 recall stack — descriptors embed cleanly).
  The planner/agent names what it needs; full params + `usage_hint` are fetched
  only for the matched few, *then* the DAG/affordance is built. This is
  `tool_search` for ProbOS.
- **Tiering:** each agent's handful of role-core intents stay fully loaded;
  everything else is deferred behind the retriever.
- **Skill bodies lazy too:** the `SKILL.md` manifest (name + 1-line + `triggers`)
  is always present; the body is read on relevance match — the same model the
  Copilot harness uses for skills.

---

## 6. The clean separation this produces

| Layer | Question | ProbOS home (target) | Bound to |
|---|---|---|---|
| **Behavior** | "how should I act / what must I follow" | Standing orders (4 tiers) | a scope (federation/ship/dept/agent) |
| **Knowledge** | "what specialized know-how do I have" | Skill Library / `SKILL.md` (manifest + lazy) | a domain |
| **Capability affordance** | "what can I invoke and how" | `IntentDescriptor.usage_hint` → derived `capability_affordances()` block | the **capability**, surfaced by **access** |
| **Capability provisioning** | "what am I assigned / allowed" | ACM + Tool Registry + Skill Library (the spine doc) | the agent (assignment) |

The bug was that "capability affordance" had no home of its own, so it leaked
into "behavior" (standing orders) and into per-agent hooks. Giving it a distinct,
derived, substrate-gated layer is what makes adding a tool or skill to an agent
*just work*: declare the `usage_hint` on the capability, grant the agent access,
and the agent's next reply already knows it has the tool and how to use it —
nothing authored, nothing per-agent.

---

## 7. Relationship to the existing capability spine

This does not replace [`skills-and-tools-architecture.md`](skills-and-tools-architecture.md);
it completes it. That doc defines **assignment** (ACM binds Role → Skills →
Tools to an agent). This doc defines **surfacing** (the assigned capabilities
become a self-describing manual in the agent's reasoning context). The spine
answers *"what does this agent have?"*; the affordance layer answers *"and does
the agent know how to use it right now?"* — which is the half that the web-search
incident proved was missing.
