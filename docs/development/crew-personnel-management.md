# Crew Personnel Management — The Ship's Office

> **Status:** Architecture spec (2026-06-06). Drafted as the design hub for the
> **Crew Personnel Management** epic (AD-891 → AD-901, GitHub #855-865). This is
> the canonical reference; the per-AD build spec lives in
> [`prompts/ad-891-899-crew-personnel-management-epic.md`](../../prompts/ad-891-899-crew-personnel-management-epic.md).

*"The crew member is the sovereign constant; everything else is infrastructure."*

---

## 1. Why this exists

ProbOS has spent six waves (AD-885 → AD-890) building the **capability spine** —
the Role → Skills → Tools commissioning chain, with the ACM
(`AgentCapitalService`) as the single front door (see
[`skills-and-tools-architecture.md`](skills-and-tools-architecture.md)). That
work made the data *correct and unified*. It did **not** give the Captain a place
to **see and manage** it.

Today a Captain who wants to answer "what is this crew member qualified for, what
are they assigned to, what may they touch, and what are their standing orders?"
has no single surface. The data exists across the ACM, the skill framework, the
tool registry, the work board, the duty schedule, and the standing-orders
composer — but it is scattered, partly private (duties), and almost entirely
invisible to the HXI. There is also **no way to manage the skill library itself**:
`SkillDefinition`s load from YAML at startup and are immutable at runtime.

This epic closes that gap. It gives ProbOS a **personnel management experience** —
a Workday-for-crew-agents — modeled on how a warship actually manages the people
aboard.

---

## 2. The Navy grounding

Warships do not "manage users." They run a **Ship's Office** (the personnel
office, run by the Personnel Officer and the PS — Personnel Specialist — rating).
The real-world systems map cleanly onto what ProbOS already has:

| US Navy system | What it does | ProbOS analogue |
|----------------|--------------|-----------------|
| **NSIPS** (Navy Standard Integrated Personnel System) | The single web-enabled personnel system of record | **Crew Personnel Console** — the new HXI experience (this epic) |
| **ESR** (Electronic Service Record) | The per-sailor record inside NSIPS: identity, history, qualifications, awards, administrative remarks | **Crew Service Record** — the per-agent personnel profile view |
| **NEC** (Navy Enlisted Classification) | Coded skill identifiers a sailor holds | **Skill Library** (`SkillDefinition` / `SkillRegistry`) |
| **PQS** (Personnel Qualification Standard) | Formal qualification to *operate equipment* / *stand a watch* | **Tool certifications** — the per-agent tool grants (`ToolAccessGrant`) |
| **WQSB / Watch Bill** (Watch, Quarter & Station Bill) | The onboard bill: who does what, where, when (watches, battle stations) | **Duties + active assignments** (duty schedule + work board) |
| **EDVR** (Enlisted Distribution & Verification Report) | Monthly manning snapshot for a command — billets authorized vs. filled | **Crew roster / manning view** |
| **Manpower Authorization** (OPNAV billets) | The authorized billet structure a command is manned to | **Role templates / posts** (`RoleTemplate`, ontology) |
| **Standing Orders** (Captain's / XO's standing orders, departmental orders) | The layered written orders every watch-stander operates under | **Standing-orders composer** (`compose_instructions`, 4-tier) |
| **Division Officer's Notebook** | The manager's per-sailor tracking of quals and PQS progress | **The Captain's view** — the console itself |

The key insight ProbOS already encodes (AD-441c): **crew agents carry a birth
certificate (a sovereign DID); tool agents carry an AssetTag.** Personnel and
equipment are different kinds of thing. So:

- **Crew** get a **Service Record** (this epic — a personnel system).
- **Tools/equipment** get an **Asset Registry** (the existing `ToolRegistry`).

The Personnel Console is the *people* counterpart to the *asset* registry — two
sister "ship's systems," not one merged blob. The Captain's request for "an asset
management system experience for the ship" is satisfied by treating crew as
personnel (service records) and tools as certified equipment (PQS-style grants),
each with its own management surface inside one console.

---

## 3. The capability model (what a Service Record contains)

A crew agent's **Service Record** is the union of seven facets, every one of
which already has a backing store:

```
Crew Service Record
├── Identity & Lifecycle   callsign, display_name, department, rank,
│                          lifecycle_state, onboarded_at, Big Five personality   [ACM]
├── Role / Post            RoleTemplate (post_id, required/optional skills)       [ontology]
├── Skills & Proficiency   developmental skills (PCC/role/acquired) +
│                          cognitive skills (SKILL.md), with proficiency          [skill framework + catalog]
├── Qualifications (Tools) tools the agent is *certified* to use (grants)         [tool registry + permissions]
├── Duties                 recurring scheduled responsibilities (the watch bill)  [duty schedule]   ← PRIVATE today
├── Active Assignments     current/in-flight work items                           [work board]
├── Standing Orders        the 4-tier composed orders the agent operates under    [standing-orders composer]
└── Experience             trust (α,β), earned agency, episode count              [trust + earned agency + episodic]
```

The ACM's `get_consolidated_profile(agent_id, runtime)` already aggregates most
of this (13 keys after AD-885/AD-889). The two missing facets are **duties**
(deliberately omitted in AD-885 — see §4) and **active assignments** (queryable
from the work board but not yet folded into the lens).

---

## 3a. How the ACM and the ontology relate (two views, one crew agent)

The personnel system draws from **two identity subsystems that overlap but are
not the same store**, and the console must compose them without silently
preferring one over the other:

| | **ACM** (`acm.py`) | **Ontology** (`ontology/service.py`) |
|---|---|---|
| Mental model | The HR department — the agent's *record* | The org chart — the agent's *billet* |
| Keyed on | `agent_id` (sovereign DID, AD-441c) | `agent_type` (role) |
| Owns | lifecycle, trust, skills, tools, personality, episodes, earned agency | department, **post/billet**, assignment, chain of command, `RoleTemplate` |
| Roster call | `get_consolidated_profile` (per-agent) | `get_crew_manifest` (ship-wide) |
| `department` | from `CrewProfileStore` (block 2) | from the ontology *assignment* |
| `rank` | from `CrewProfile.rank` (stored) | derived from `trust_network` via `Rank.from_trust` |

**The overlap is real and can drift.** Both surfaces report `department` and
`rank`, computed from different sources. Today the ACM already *consumes* the
ontology in one direction — `commission()` walks
`ontology.get_role_template_for_agent(agent_type)` to acquire role skills
(`acm.py` L426, AD-889) — but `get_consolidated_profile` does **not** pull
`post`/billet from the ontology, so the per-agent lens currently has no post/
chain-of-command facet at all.

**Resolution for this epic (no new reconciliation layer):**

- The **Service Record** (`/api/crew/{id}/record`) is **ACM-authoritative** —
  it is the HR record. AD-897 enriches it with the ontology's `post` /
  `RoleTemplate` for the *Role / Post* section (display-only read of
  `get_crew_context` / `get_role_template_for_agent`).
- The **Roster** (`/api/crew/roster`) is **ontology-authoritative** — it wraps
  `get_crew_manifest`, the same source the live HXI roster already uses.
- Each endpoint's docstring states which surface owns which field, so the
  ACM↔ontology drift is **explicit, not silent**. A future AD (out of scope
  here) may unify `rank`/`department` to a single source; this epic only
  documents the seam.

> **Architectural note for the Architect review:** the long-term direction is
> for the ACM to treat the ontology as the *authority for org-chart facets*
> (post, department, assignment) and own only the *earned/learned* facets
> (trust, skills, tools, lifecycle). `get_consolidated_profile` reading
> `department` from `CrewProfileStore` instead of the ontology assignment is a
> latent dual-source smell — flagged here, deliberately not fixed in AD-892 to
> keep the blast radius small.

---

## 3b. Billets — the Watch Bill the personnel system must surface

A **billet** is a permanent *position* (a post); agents *rotate through* it. This
is the Navy Watch Bill model, and ProbOS already implements it end-to-end
(AD-595a–e) — but it is **invisible to both the ACM lens and the personnel
console plan**, which is the gap this question exposes.

**What exists (verified 2026-06-06):**

- **`BilletRegistry`** (`ontology/billet_registry.py`, AD-595a) — the
  authoritative Watch Bill. A facade over `DepartmentService` (which remains the
  source of truth for posts/assignments). It is **already publicly exposed**:
  `runtime.billet_registry` (`runtime.py` L1438) delegates to
  `ontology.billet_registry`. No forcing-function accessor needed (unlike
  duties).
- **`BilletHolder`** snapshot: `billet_id, title, department,
  holder_agent_type, holder_callsign, holder_agent_id`. Holder fields are `None`
  when the billet is **vacant** — so the roster shows *authorized vs. filled*,
  the true EDVR value.
- **`get_roster()` / `get_department_roster(dept)`** — the full Watch Bill
  including vacant billets. This is the *manpower-authorization* lens (every
  post, manned or gapped), distinct from `get_crew_manifest` (only assigned
  agents).
- **A second qualification system.** `Post.required_qualifications` is a list of
  **test names** (AD-595d), checked by
  `BilletRegistry.check_qualifications(billet_id, agent_type, agent_id) ->
  (qualified, missing)` against a `QualificationStore` of pass/fail test results.
  This is **PQS in its truest form** — distinct from tool certifications.

**Two homes for "qualification" — the personnel system must show both:**

| | **Tool certifications** (AD-894) | **Billet qualifications** (AD-595d) |
|---|---|---|
| Store | `ToolPermissionStore` (grants) | `QualificationStore` (test results) |
| Question answered | "What equipment may this agent operate?" | "Is this agent qualified to *hold this post*?" |
| Navy analogue | Equipment/system PQS sign-off | Watchstation PQS / billet qualification |
| Gate | Captain-issued grant | Pass the post's required tests |

**How billets wire into task / work management today (verified):**

- **Onboarding** assigns the billet at the naming ceremony
  (`agent_onboarding.py` L416 `billet_registry.assign(post_id, agent_type, ...)`).
- **SOP bills** (`sop/runtime.py` L541, AD-618b) — the strongest billet→work
  link. `_assign_role` filters candidates by `get_department_roster(dept)` then
  `check_qualifications(...)` before assigning an agent to a bill role.
  **Qualification-gated work assignment already exists — but only for SOP bills.**
- **Consultation routing** (`cognitive/consultation.py` L331) uses
  `get_roster()` to find expertise holders.
- **An agent reads its own billet standing** (`cognitive_agent.py` L615,
  `proactive.py` L472 `get_qualification_standing`).
- **Intent→department routing** (`activation/task_router.py`) routes by
  department via posts/assignments — but does **not** consult billet
  qualifications.

**The gap (and the scope line):**

1. The **ACM `get_consolidated_profile` has no billet facet at all** — no post,
   no chain of command, no qualification standing. The personnel record is
   incomplete without it.
2. The **general work board (`WorkItemStore.assign`) does NOT gate on billet
   qualifications** — only SOP bills do. `transition_requires_assignment` is the
   only gate. So a work item can be assigned to an agent who hasn't qualified for
   the relevant post. Whether to extend qualification-gating from SOP bills to
   the general work board is a **real architectural decision, deferred** (see
   §6) — this epic *surfaces* billets and qualification standing in the record
   (read-only); it does not change work-assignment gating.

**Where billets land in this epic:** AD-892's record endpoint adds the agent's
billet (post + qualification standing) read from `runtime.billet_registry`; the
roster MAY offer a Watch-Bill mode (`get_roster`, incl. vacant billets) as the
manpower-authorization lens; AD-897 renders both in the *Role / Post* and
*Qualifications* sections. No new billet mutators — assignment stays with the
onboarding/naming ceremony.

---

## 4. The seam table — what exists, what's missing

Verified against the live codebase (2026-06-06). Each gap row maps to an AD.

| # | Facet | Backing store | State | Gap → AD | Issue |
|---|-------|---------------|-------|----------|-------|
| 0 | Crew roster | `OntologyService.get_crew_manifest` (live HXI source, `/api/ontology/crew-manifest`) + registry crew enumeration | EXISTS | `/api/crew/roster` wraps it + adds lifecycle/skill/tool counts + **includes unbilleted crew** (`assigned: false`) so the EDVR shows everyone aboard | AD-892 | #856 |
| 1 | Consolidated profile | `acm.py get_consolidated_profile` | EXISTS (13 keys) | Not exposed over HTTP | AD-892 | #856 |
| 2 | Duties | `DutyScheduleTracker.get_due_duties` | **PRIVATE** (`proactive.py` `_duty_tracker`) | No public accessor; not in lens | **AD-891** | #855 |
| 3 | Active assignments | `WorkItemStore` + `/api/work-items?assigned_to=` | EXISTS | Fold into record/UI | AD-892/AD-897 | #856/#861 |
| 4 | Standing orders (read) | `standing_orders.compose_instructions` | EXISTS (internal only) | No read API | AD-893 | #857 |
| 5 | Tool certifications | `ToolRegistry` + `ToolPermissionStore` | EXISTS | No HTTP surface; no grant/revoke UI | AD-894 | #858 |
| 6 | Skill library CRUD | `SkillRegistry` (`SkillDefinition`) | **READ-ONLY** (YAML at startup, immutable) | No create/update/delete; not persisted | **AD-895** | #859 |
| 7 | Roles / posts | `ontology RoleTemplate` | EXISTS | Display only | AD-892/AD-897 | #856/#861 || 8 | Console window | HXI panels (`WardRoomPanel` mode system) | PARTIAL | No personnel console experience | AD-896 | #860 |
| 9 | Service Record view | `AgentProfilePanel` (6 tabs) | PARTIAL | No HR-style record view | AD-897 | #861 |
| 10 | Skill mgmt UI | — | MISSING | No skill-library admin surface | AD-898 | #862 |
| 11 | Tool cert mgmt UI | — | MISSING | No certification admin surface | AD-899 | #863 |
| 12 | Billet / Watch Bill | `BilletRegistry` (`runtime.billet_registry`, public) | EXISTS, public | Not in ACM lens; not in record/roster | AD-892/AD-897 | #856/#861 |
| 13 | Billet qualifications | `QualificationStore` + `check_qualifications` | EXISTS | Standing not surfaced in record | AD-892/AD-897 | #856/#861 |
| 14 | Standing-order editing (governed) | `DirectiveStore` (`runtime.directive_store`, AD-386) | EXISTS, CLI only | No HTTP surface; not in console | AD-900/AD-901 | #864/#865 |

Two **forcing functions** fall out of the verify-first pass:

- **Duties are blocked behind a Law-of-Demeter violation.** `get_due_duties` is
  private on `runtime.proactive_loop._duty_tracker` (`proactive.py` L607). AD-885
  explicitly omitted duties for this reason. **AD-891 must ship a public
  `runtime.duty_schedule_tracker` first** — it is the forcing function for the
  whole duties facet and runs first in the epic.

- **The skill library is immutable at runtime.** `SkillRegistry` loads
  `SkillDefinition`s from `config/ontology/skills.yaml` at startup with no
  create/update/delete and no write-back. The Captain's "full CRUD on skills"
  requires a **writable, persisted skill-definition store** (AD-895) — the
  largest single new backend capability in the epic. It must follow the
  cloud-ready storage convention (abstract `typing.Protocol`, not a hardcoded
  SQLite call) so the commercial overlay can swap backends.

---

## 5. The AD convergence sequence

Smallest-blast-first; backend seams before the UI that consumes them. Each UI AD
hard-depends on its backend AD.

**Backend / API layer**

1. **AD-891 — Public duty accessor + duties in the lens** (#855). Park the
   `DutyScheduleTracker` (or a thin read-only view of it) on
   `runtime.duty_schedule_tracker`; add a public `list_duties_for_agent`-style
   read; append a `duties` block to `get_consolidated_profile`. Closes the
   AD-885 NO-SEAM. Forcing function — runs first.
2. **AD-892 — Crew Service Record + Roster HTTP surface** (#856). New
   `routers/crew.py`: `GET /api/crew/roster` (the EDVR-style manning list) and
   `GET /api/crew/{agent_id}/record` (the consolidated profile + active
   assignments over HTTP). Read-only. The single surface the console binds to.
3. **AD-893 — Standing Orders read surface** (#857). `GET
   /api/crew/{agent_id}/standing-orders` returns the 4-tier composed orders for
   display. Read-only preview; no mutation of the order files.
4. **AD-894 — Tool Registry + certification surface** (#858). `GET /api/tools`
   (the asset catalog), `GET /api/crew/{agent_id}/tools` (certifications =
   active grants), and Captain-authorized grant/revoke
   (`POST`/`DELETE`) over `ToolPermissionStore.issue_grant` /`revoke_grant`.
   Granting a tool is a privilege change — Captain authority, audited.
5. **AD-895 — Skill Library CRUD** (#859). A writable, persisted
   skill-definition store behind a `typing.Protocol`; `create`/`update`/`delete`
   on `SkillDefinition` with validation (protect built-in PCCs and any skill in
   active use); `GET/POST/PUT/DELETE /api/skills/definitions`. Full CRUD on the
   skill library from the ACM.

**HXI / experience layer**

6. **AD-896 — Crew Personnel Console (shell)** (#860). A new resizable /
   draggable / dockable HXI window — the **Ship's Office** — reusing the AD-837
   WardRoom display-mode pattern (docked / floating / maximized). Master-detail:
   roster on the left, service record on the right. A *separate experience*, not
   another tab on the profile panel.
7. **AD-897 — Service Record detail view** (#861). The Workday-style personnel
   profile inside the console: Identity & Role, Skills & Proficiency,
   Qualifications (certified tools), Duties & Active Assignments, Standing
   Orders, Experience. Binds to AD-892/893/894 endpoints.
8. **AD-898 — Skill Library management view** (#862). The UI for AD-895: browse,
   create, edit, retire skill definitions; the skill-library admin console.
9. **AD-899 — Tool certification management view** (#863). The UI for AD-894:
   browse the tool registry (asset catalog), view and grant/revoke per-agent
   certifications.

**Governed standing-order editing (the approval-gated write path)**

10. **AD-900 — Governed directive authoring surface** (#864). HTTP surface over
    the existing `DirectiveStore` (AD-386) — the evolvable runtime overlay that
    `compose_instructions` already merges on top of the immutable 4-tier files.
    `GET/POST /api/crew/{agent_id}/directives`, `POST .../directives/{id}/approve`,
    `DELETE .../directives/{id}`. Captain orders land `ACTIVE` immediately;
    lower-authority directives stay `PENDING_APPROVAL` until approved — **the
    approval gate already exists; this AD exposes it, it does not build it.**
    Does NOT edit the static `.md` tier files. Every mutation invalidates the
    standing-orders cache (`clear_cache`), exactly as the `/order` CLI does.
11. **AD-901 — Standing Orders & Directives management view** (#865). The UI for
    AD-900 inside the Service Record: read-only 4-tier orders (AD-893) plus a
    Directives panel to issue a Captain's order, approve a pending directive, and
    revoke — the approval gate made visible.

---

## 6. Design boundaries (do NOT build)

- **No HR/payroll/leave/evaluation cruft.** This is crew *capability and
  assignment* management, not a human-resources benefits system. No
  compensation, no leave balances, no performance-review workflow.
- **No new identity model.** Crew identity is AD-441c (sovereign DID / birth
  cert). The console *reads and displays* it; it does not mint or re-issue it.
- **No editing of the static standing-order tier files in this epic.** AD-893 is
  read-only. The governed *write* path is the **`DirectiveStore` overlay**
  (AD-900/901): the Captain issues/approves/revokes **directives**, which
  `compose_instructions` already merges on top of the 4-tier files. The static
  `.md` files (`federation.md` is immutable by design) and the self-mod /
  directive-store-internals governance path are NOT edited from the console.
- **No consensus bypass.** Tool grant/revoke (AD-894), skill
  create/update/delete (AD-895), and directive issue/approve/revoke (AD-900) are
  state changes — they go through the existing authority models (Captain
  authority / `authorize_directive`, audited via grant records / directive
  status / event log). Do not add a back door that mutates a store without its
  existing authorization path and audit trail.
- **No merge of the asset registry and the personnel record.** Crew = service
  records; tools = assets. They share the console as sister surfaces but remain
  distinct stores (per AD-441c).
- **No windowing-framework rewrite.** AD-896 reuses the existing WardRoom mode
  pattern. Splitter columns, snap-to-edge tiling, and OS-detached windows remain
  the existing forward markers (AD-837b/c/d), out of scope here.
- **No new billet mutators, and no change to work-assignment gating.** Billets
  are assigned at the onboarding/naming ceremony (AD-595b); the console *reads*
  the Watch Bill and qualification standing, it does not create/assign billets.
  Extending billet-qualification gating from SOP bills (`sop/runtime.py`, where
  it already exists) to the general work board (`WorkItemStore.assign`) is a
  **separate future AD** — surfaced as a smell in §3b, deliberately not built
  here.

---

## 7. Commercial boundary

This epic is **OSS** — it is "how the product works" (a personnel management
surface over the existing capability spine). The crew-as-personnel /
agent-services model connects to the **Agent Services Automation (ASA)** vision
in the commercial repo (`research/agent-services-automation-vision.md`), but ASA
financials, billing, PSA, and customer-facing positioning stay commercial. The
console is an OSS extension point; reference ASA only as a downstream consumer,
never inline its monetization details here.
