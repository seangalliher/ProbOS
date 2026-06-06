# Skills & Tools Architecture — The Capability Spine

*Status: Canonical. Supersedes the fragmented capability narrative spread across
AD-422/423, AD-428, AD-429b, AD-441c, AD-531+, AD-543, AD-596, and the orphaned
`unified-tool-layer.md`. Read this first before touching anything that calls
itself a "skill" or a "tool".*

*Repo: OSS. This document describes **how the product works**. The commercial
overlay (Agent Services Automation) builds on this spine — see
[Commercial Overlay Connection](#commercial-overlay-connection) — but its
pricing/PSA/billing layers live in the private repo.*

---

## 1. Why this document exists

ProbOS shipped a lot of capability infrastructure across many ADs, and three
unrelated things ended up being called a **"skill"**:

1. The legacy self-mod `Skill` ([`types.py`](../../src/probos/types.py) — a
   Python code handler attached to a `SkillBasedAgent`).
2. The developmental `SkillDefinition` (AD-428 — a competency an agent acquires
   and grows from proficiency 1→7).
3. The AgentSkills.io `CognitiveSkillEntry` (AD-596 — a `SKILL.md` instruction
   file loaded into an agent's context).

Meanwhile the **Tool Registry** (AD-423), the **ACM** (AD-427, "HR for agents"),
the **Role/Qualification** ontology (AD-429b), the **Duty/Workforce** scheduling
(AD-419, AD-496–498), and the **skill→tool binding** design (`unified-tool-layer.md`)
were each built in isolation. The pieces exist; the **edges between them** were
never wired. This document defines the coherent target and the convergence
sequence (AD-885 → AD-890) that finishes the wiring.

---

## 2. The two-concept model (industry-aligned)

The naming collision dissolves once we adopt the same split that Claude Code and
GitHub Copilot use:

| Concept | Means | The thing the agent... | Lives in |
|---|---|---|---|
| **Tool** | A deterministic capability that executes | ...*invokes* to act | **Tool Registry** (master) |
| **Skill** | A competency / knowledge that shapes reasoning | ...*has* (knows how to do) | **Skill Library** (master) |

**The dividing line:** a tool *runs* (code executes, returns a result); a skill is
*loaded* (instructions/knowledge that change how the agent reasons, or a
proficiency record that gates what it's trusted to do).

### How the three "skills" resolve

| Current thing | What it actually is | Belongs in |
|---|---|---|
| Legacy self-mod `Skill` ([`types.py`](../../src/probos/types.py)) | Deterministic Python the agent *invokes* | **Tool Registry** (`ToolType.UTILITY_AGENT` / `DETERMINISTIC_FUNCTION`, `origin="designed"`) |
| `SkillDefinition` (AD-428) | Developmental competency (Dreyfus 1–7) | **Skill Library** (the proficiency dimension) |
| `CognitiveSkillEntry` (AD-596, `SKILL.md`) | Natural-language instruction knowledge | **Skill Library** (the instruction dimension) |

So the self-mod pipeline does not "design skills" — it **designs tools**. The
Skill Library is a single master with two *kinds* of competency record
(developmental proficiency + cognitive instruction file), not two registries.

> This is the Navy model in
> [`crew-capability-architecture.md`](../research/crew-capability-architecture.md):
> NEC/PQS qualifications (**skills**) certify a sailor to operate
> authorized equipment (**tools**).

---

## 3. The capability spine

The user-authoritative model, mapped onto real code:

```
            ┌─────────────────────────────────────────────────┐
            │   ACM  —  "HR for agents" (assignment + lens)    │  AD-427  acm.py
            │   onboard · lifecycle · ASSIGN role/skills/tools │
            └─────────────────────────────────────────────────┘
                 │ assigns                       │ reads (consolidated profile)
                 ▼                               ▼
   ROLE ───────────────── defines ──────────────── DUTIES / PROCESSES
   Ontology Post +                                 DutyScheduleTracker  (AD-419)
   RoleTemplate (AD-429b)                          Workforce WorkItems  (AD-496–498)
   Standing Orders (T1)                            (the "processes/duties" tier)
        │ requires                                       │ performed via
        ▼                                                ▼
   ┌──────────────── SKILL LIBRARY (master) ──────────────────┐
   │  competency = what an agent KNOWS HOW to do              │
   │  • Developmental skills  AD-428  skill_framework.py (SQL) │
   │  • Cognitive skills      AD-596  skill_catalog.py (.md)   │
   │  Proficiency (Dreyfus 1–7) · prerequisites · decay        │
   └──────────────────────────────────────────────────────────┘
        │ may require  (SkillDefinition.preferred_tools — AD-423a)
        ▼
   ┌──────────────── TOOL REGISTRY (master) ──────────────────┐
   │  capability = what an agent USES to act                   │
   │  • Native SWE tools, browser, MCP, Oracle  AD-423/448/449 │
   │  • Legacy self-mod "skills"  → RECLASSIFIED AS TOOLS      │  (AD-886)
   │  Permissions (CRUD+O) · LOTO locks · rank-gated grants    │
   └──────────────────────────────────────────────────────────┘
```

**The chain, in one sentence:** *An agent is assigned a **Role**; the Role
defines a scope of **Duties/Processes**; performing a process exercises **Skills**;
a Skill may require **Tools** to act. The **Tool Registry** and **Skill Library**
are the masters; **ACM** is the assignment surface that binds them to a crew agent.*

---

## 4. The identity axis already drew this line (AD-441c)

The crew/tool split is not new — it already exists on the **identity** axis. The
capability axis just never caught up:

| | **Crew agent** (domain/cognitive) | **Tool agent** (infrastructure/utility) |
|---|---|---|
| Identity | Sovereign **birth certificate** (W3C VC, Identity Ledger) | Lightweight **`AssetTag`** (serial number) |
| Onboarded via ACM? | Yes | No |
| Capability model | Assigned **Skills** | Catalogued as **Tools** |
| The principle | *"a person"* | *"A microwave with a name tag isn't a person. But it still has a serial number."* |

`AssetTag` fields: `asset_uuid, asset_type, slot_id, installed_at, pool_name,
tier`. The fork lives in `crew_utils.is_crew_agent()`.

**Implication:** the legacy self-mod `Skill` is produced by an agent the system
*already tags as inventory, not crew*. The identity layer already says it's a
tool — AD-886 simply brings the capability layer into agreement.

---

## 5. Shipped inventory (what exists today, where)

| Layer | Shipped as | File | Status |
|---|---|---|---|
| Assignment / HR | ACM (AD-427) | [`acm.py`](../../src/probos/acm.py) | Lifecycle + partial consolidated profile |
| Role → skills | `RoleTemplate` (AD-429b) | [`ontology/models.py`](../../src/probos/ontology/models.py) | Exists; not yet driving assignment |
| Duties / processes | `DutyScheduleTracker` (AD-419), Workforce (AD-496–498) | `config.py`, [`workforce.py`](../../src/probos/workforce.py) | Exists; not linked to RoleTemplate |
| Skill Library (developmental) | `SkillRegistry` / `AgentSkillService` (AD-428) | [`skill_framework.py`](../../src/probos/skill_framework.py) | `skills.db`, proficiency 1–7 |
| Skill Library (cognitive) | `CognitiveSkillCatalog` (AD-596) | [`cognitive/skill_catalog.py`](../../src/probos/cognitive/skill_catalog.py) | `SKILL.md` scan + progressive disclosure |
| Tool Registry | `ToolRegistry` (AD-423a/b) | [`tools/registry.py`](../../src/probos/tools/registry.py) | In-memory, permissions + LOTO |
| Native tools | SWE harness (AD-543–549), browser (AD-706), MCP (AD-449), Oracle (AD-696) | [`tools/executor.py`](../../src/probos/tools/executor.py) | Registered at startup |
| Skill→Tool link | `SkillDefinition.preferred_tools` / `ToolPreference` (AD-423a) | [`tools/protocol.py`](../../src/probos/tools/protocol.py) | Field exists; **no resolver** |
| Legacy self-mod skill | `Skill` dataclass | [`types.py`](../../src/probos/types.py) | The third, unconverged "skill" |

---

## 6. The data model (verified field shapes)

```
RoleTemplate (ontology/models.py)
  post_id: str
  required_skills: list[SkillRequirement]   # SkillRequirement(skill_id, min_proficiency 1-7)
  optional_skills: list[SkillRequirement]

SkillDefinition (skill_framework.py)        # the Skill Library master record
  skill_id, name, category, description, domain
  prerequisites: list[str]                  # skill_ids required at APPLY+
  decay_rate_days: int
  origin: "built_in" | "role" | "acquired" | "designed"
  preferred_tools: list[ToolPreference]     # ← the skill→tool edge (AD-423a)
  composite_skill_ids, synergy_partners

ToolPreference (tools/protocol.py)
  tool_id: str
  priority: int                             # lower = higher priority
  context: str                              # "when offline", "for large files", ...

ToolRegistration (tools/protocol.py)
  tool: Tool                                # Protocol: tool_id/name/tool_type/description/invoke
  tool_type: ToolType                       # UTILITY_AGENT | DETERMINISTIC_FUNCTION | MCP_SERVER | ...
  domain, department, tags, provider, enabled
  default_permissions: dict[rank → ToolPermission]   # NONE<OBSERVE<READ<WRITE<FULL
  concurrency: "concurrent" | "exclusive"   # LOTO

CognitiveSkillEntry (cognitive/skill_catalog.py)
  name, description, skill_dir, department
  skill_id, min_proficiency, min_rank, intents, origin, activation, triggers

AssetTag (AD-441c)                          # tool-agent identity
  asset_uuid, asset_type, slot_id, installed_at, pool_name, tier
```

Note the spine is **already half-modelled in fields**: `RoleTemplate.required_skills`
(Role→Skill), `SkillDefinition.preferred_tools` (Skill→Tool), and
`DutyDefinition.required_skills` (Duty→Skill) all exist. The convergence is
mostly about making code **traverse** these edges, not inventing new ones.

---

## 7. The fragmentation seams (and the fix)

| # | Seam | Today | Convergence AD | Issue |
|---|---|---|---|---|
| 1 | ACM is blind to most capabilities | `get_consolidated_profile` reads AD-428 skills only — not cognitive skills, tools, or duties | **AD-885** | [#849](https://github.com/seangalliher/ProbOS/issues/849) |
| 2 | "Skill" means three things | Legacy `Skill` is a parallel island next to `SkillDefinition` and `CognitiveSkillEntry` | **AD-886** | [#850](https://github.com/seangalliher/ProbOS/issues/850) |
| 3 | Two skill registries | AD-428 `SkillRegistry` and AD-596 `CognitiveSkillCatalog` are separate stores (bridged by AD-596c, not merged) | **AD-887** | [#851](https://github.com/seangalliher/ProbOS/issues/851) |
| 4 | Skill→Tool never resolves | `preferred_tools` field exists but nothing turns "exercise skill X" into "invoke tool Y" | **AD-888** | [#852](https://github.com/seangalliher/ProbOS/issues/852) |
| 5 | Role→Skill→Tool never traversed | `commission_agent` reads a hardcoded `ROLE_SKILL_TEMPLATES` dict, not the ontology `RoleTemplate`; tools are never granted from skills | **AD-889** | [#853](https://github.com/seangalliher/ProbOS/issues/853) |
| 6 | Stale design docs | `unified-tool-layer.md` claims "AD-543" (reused by the Native SWE Harness), orphaning its skill→tool design | **AD-890** | [#854](https://github.com/seangalliher/ProbOS/issues/854) |

---

## 8. Convergence sequence (AD-885 → AD-890)

Ordered smallest-blast-radius first. Each AD is a single commit; no behavior break.

1. **AD-885 — ACM becomes the true single lens.** Extend
   `ACM.get_consolidated_profile` to also read the Cognitive Skill Catalog
   (AD-596), the agent's Tool Registry grants (AD-423), and duty schedule
   (AD-419). Pure read-aggregation — makes the fragmentation *queryable* before
   any behavior changes. Lowest risk, highest clarifying value.

2. **AD-886 — Reclassify the legacy self-mod `Skill` as a Tool.** The self-mod
   pipeline registers designed deterministic handlers into the **Tool Registry**
   (`ToolType.UTILITY_AGENT` / `DETERMINISTIC_FUNCTION`, `origin="designed"`)
   instead of attaching ad-hoc `Skill` objects. Brings the capability layer into
   agreement with the AD-441c identity layer; designed capabilities gain
   persistence, permissions, and LOTO governance.

3. **AD-887 — One Skill Library master.** AD-428 `SkillRegistry` is the single
   front door; AD-596 `CognitiveSkillCatalog` becomes an *input source* (a skill
   *kind*), not a parallel store. Builds on the existing AD-596c bridge.

4. **AD-888 — Skill→Tool binding (finishes the orphaned `unified-tool-layer.md`
   Part 4).** Add a resolver: exercising a skill resolves
   `SkillDefinition.preferred_tools` → `ToolRegistry.list_tools()` ranked by
   Hebbian routing, with a capability-tag fallback. The literal "missing link."

5. **AD-889 — ACM assignment chain: Role → Duties → Skills → Tools.** The
   capstone. `commission_agent` reads the ontology `RoleTemplate` (not the
   hardcoded dict) → grants required skills → grants the tools those skills
   require → registers duties. *This is the unification that was intended and
   never happened.*

6. **AD-890 — Supersede the stale docs.** Retire/redirect `unified-tool-layer.md`
   (the AD-543 number collision) and mark this document + `crew-capability-architecture.md`
   as the canonical capability spine.

---

## 9. Glossary

- **Tool** — a deterministic instrument an agent *invokes* (`ToolRegistry`).
- **Skill** — a competency an agent *has*: a developmental proficiency record
  (AD-428) and/or a cognitive instruction file (AD-596, `SKILL.md`).
- **Role / Post** — an agent's job, defined by an ontology `RoleTemplate`
  (`required_skills`).
- **Duty / Process** — recurring work a role is responsible for
  (`DutyScheduleTracker`, Workforce `WorkItem`).
- **ACM** — Agent Capital Management; the HR/assignment surface. Onboards crew,
  assigns skills, grants tools, and is the single consolidated lens.
- **AssetTag** — a tool agent's lightweight identity (serial number), distinct
  from a crew agent's sovereign birth certificate (AD-441c).

---

## Commercial Overlay Connection

ACM, the Skill Library, and Workforce Scheduling (AD-496–498) are the **OSS
plumbing** for the commercial **Agent Services Automation (ASA)** vision. The
boundary holds:

- **OSS (this spine):** how capability assignment, scheduling, and execution
  *work* — `BookableResource`, `WorkItem`, `Booking`, the capability matching,
  ACM lifecycle and consolidated profile.
- **Commercial (private repo):** how it *makes money* — PSA financials
  (contracts, billing, revenue recognition), utilization dashboards, portfolio
  rollup, and ASA's advanced optimization. These build *on top of* the OSS
  entities; they do not fork them.

The convergence ADs in this document strengthen the OSS plumbing that ASA
depends on (a single consolidated capability lens, a real Role→Skill→Tool
assignment chain), without adding any commercial-tier logic to the OSS repo.
