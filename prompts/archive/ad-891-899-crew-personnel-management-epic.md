# Crew Personnel Management Epic — AD-891 → AD-901

**Status:** Drafted 2026-06-06. Ready for Architect verify-first review → Builder.
**Repo:** ProbOS (OSS) — `d:\ProbOS`. NOT the commercial repo.
**Highest shipped AD:** AD-890 (Wave 247). This epic = AD-891 → AD-901 (Waves 248-258).
**Canonical design doc:** [`docs/development/crew-personnel-management.md`](../docs/development/crew-personnel-management.md)
**GitHub issues:** AD-891 #855 · AD-892 #856 · AD-893 #857 · AD-894 #858 · AD-895 #859 · AD-896 #860 · AD-897 #861 · AD-898 #862 · AD-899 #863 · AD-900 #864 · AD-901 #865

**Forced build order:** 891 → 892 → 893 → 894 → 895 → 900 → 896 → 897 → 901 → 898 → 899.
Backend seams before the UI that consumes them. Each UI AD hard-depends on its
backend AD: 897↦892/893/894, 898↦895, 899↦894, **901↦900**, **900↦893**.

**Theme:** Give ProbOS a Workday-for-crew-agents — a **Ship's Office** personnel
management experience over the existing capability spine (AD-885 → AD-890),
grounded in how a warship runs NSIPS / ESR / PQS / the watch bill. Crew are
*personnel* (service records); tools are *assets* (certified equipment). See the
canonical doc for the full Navy grounding and capability model.

---

## Standing rules for every AD in this epic

- **One AD = one commit.** Message `AD-NNN: <title>`. Update PROGRESS.md +
  DECISIONS.md in the **same** commit. **Do NOT push** — the Captain reviews and
  pushes.
- **Verify-first.** Grep/read the live code before asserting any API. Cluster
  plans and this prompt are NOT ground truth — confirm every method shape.
- **BF-287 test discipline.** Real fixtures at substrate boundaries (real
  `AgentCapitalService`, real `ToolRegistry`, real `WorkItemStore`, real
  `SkillRegistry`). No MagicMock at the config/substrate boundary.
- **Cloud-ready storage.** Any new persisted store uses an abstract
  `typing.Protocol` connection, not a hardcoded `aiosqlite.connect()` (so the
  commercial overlay can swap backends).
- **Test gate per AD:** the new test file + adjacent importers, serial:
  `d:/ProbOS/.venv/Scripts/pytest.exe <files> -q -n 0 -p no:cacheprovider`.
  Known pre-existing failures to ignore:
  `tests/test_bf207_shutdown_episodic_integrity.py::TestShutdownOrdering::test_dream_cycle_timeout_is_2s`
  and `::test_timeout_warning_says_2s`.
- **UI test requirement.** Every UI AD (896-899) ships Vitest component tests
  (`cd ui && npx vitest run`). No HXI PR without tests.
- **HXI design law.** No emoji — stroke-only SVG glyphs from
  `ui/src/components/icons/Glyphs.tsx` (strokeWidth 1.5, amber `#f0b060` active /
  `#666680` inactive). Motion encodes state. Progressive disclosure.
- **Every AD's acceptance criteria must include:** "Verify all changes comply
  with the Engineering Principles in `.github/copilot-instructions.md`."

---

## AD-891 — Public duty-schedule accessor + duties in the lens (#855)

**Why.** AD-885 omitted duties from the consolidated profile because
`get_due_duties` is private on `runtime.proactive_loop._duty_tracker`
(`src/probos/proactive.py` L607 constructs `DutyScheduleTracker(config.schedules)`),
and reaching it is a Law-of-Demeter violation. This is the forcing function for
the whole duties facet — ship it first.

**Verify-first anchors.**
- `src/probos/duty_schedule.py` — `DutyScheduleTracker` (L147), `get_due_duties(agent_type)` (L167), `record_execution` (L211); `DutyDefinition` lives in `config.py` (L3915) with fields (`duty_id`, `description`, `cron`, `interval_seconds`, `priority`).
- `src/probos/proactive.py` L384 `self._duty_tracker: DutyScheduleTracker | None`; it is created only inside `set_duty_schedule()` (L604/L607). No public accessor exists yet.
- **Wiring site (VERIFIED):** `proactive_loop.set_duty_schedule(...)` is called at `src/probos/startup/finalize.py` L2537 — park `runtime.duty_schedule_tracker` there (and `naval/plan_of_day.py` L10 already anticipates the missing public attribute).
- `src/probos/acm.py` `get_consolidated_profile` (L277) — blocks 1-8 after AD-885/889; the `hasattr`/`try` guard pattern of blocks 5-8.

**Build.**
1. Park a public handle on the runtime: `runtime.duty_schedule_tracker` (set
   wherever the proactive loop's `_duty_tracker` is created/wired — confirm the
   exact startup site). Default `None` when proactive cognition is disabled.
   This is the **single public accessor** — no other code should reach
   `proactive_loop._duty_tracker`.
2. Add a public read on `DutyScheduleTracker` that lists an agent's configured
   duties **without** mutating execution state (e.g. `list_duties_for_agent(agent_type) -> list[DutyDefinition]`,
   returning the configured schedule, distinct from the `get_due_duties` "what's
   due right now" call). Decide and document whether the lens shows *configured*
   duties (stable) or *currently-due* duties (volatile) — configured is the
   right choice for a personnel record.
3. Append block 9 to `get_consolidated_profile`: when
   `runtime.duty_schedule_tracker` is present, `profile["duties"]` = list of
   `{duty_id, description, cron, interval_seconds, priority}` for the agent's
   `agent_type`, plus `profile["duty_count"]`. Guard exactly like blocks 5-8
   (`hasattr`/`try`, log-and-degrade).

**Do not change.** The proactive loop's existing private use of `_duty_tracker`
for execution (record_execution etc.) stays; AD-891 only *adds* a public read
handle and a non-mutating list method. Do not change duty scheduling behavior.

**Tests.** `tests/test_ad891_duty_lens.py` (real `AgentCapitalService` + real
`DutyScheduleTracker` per BF-287): public accessor returns the tracker; the lens
includes `duties`/`duty_count`; absent tracker → no `duties` key, no crash;
configured-vs-due semantics. Blast radius: `tests/test_ad885_acm_unified_lens.py`.

---

## AD-892 — Crew Service Record + Roster HTTP surface (#856)

**Why.** `get_consolidated_profile` is internal-only; the console needs it over
HTTP, plus an EDVR-style manning roster. **The roster already has a canonical
source — reuse it, do not re-derive.**

**Verify-first anchors.**
- `src/probos/routers/skills.py` (endpoint style, `Depends(get_runtime)`, `runtime.acm` guard, `routers/deps.py`).
- How routers are registered (find where `routers/skills.py`'s `router` is `include_router`'d) — mirror it for a new `routers/crew.py`.
- `src/probos/routers/agents.py` `GET /api/agent/{agent_id}/profile` — do NOT duplicate; the crew record is the *consolidated* (deeper) view.
- `src/probos/workforce.py` `WorkItemStore.list_work_items(assigned_to=...)` (L1088) — store-boundary query for "active assignments" (the `/api/work-items?assigned_to=` endpoint wraps it).
- **Roster source (VERIFIED):** `OntologyService.get_crew_manifest(department=..., watch=..., trust_network=..., callsign_registry=..., watch_manager=...)` (`src/probos/ontology/service.py` L472). This is what the live HXI roster uses via `GET /api/ontology/crew-manifest` (`routers/ontology.py` L54). It returns one dict per crew agent: `agent_type, callsign, department, post, rank, trust_score, agent_id` (+ `watch` when a manager is passed). It is **keyed per-`agent_type`** and **skips agents with no ontology assignment** (`if not assignment: continue`, `service.py` L526-528). **There is no `runtime.crew_manifest` attribute — that was a phantom; the manifest is computed by the ontology service.**
- **Full-crew enumeration source (VERIFIED):** `runtime.registry.all()` (`src/probos/substrate/registry.py` L71) returns every agent *instance* (unique `.id`, plus `.agent_type`); filter with `is_crew_agent(...)` (`src/probos/crew_utils.py` L21). This is the authoritative "who is aboard" set, including unbilleted crew the manifest drops.
- **Billet source (VERIFIED):** `runtime.billet_registry` (`runtime.py` L1438, public, delegates to `ontology.billet_registry`). `BilletHolder` (`ontology/billet_registry.py` L27) fields `billet_id, title, department, holder_agent_type, holder_callsign, holder_agent_id`; `resolve(title_or_id)` (L91, **sync**); `get_roster()` (L138, **sync**, full Watch Bill incl. vacant); `check_qualifications(billet_id, agent_type, agent_id) -> (qualified, missing)` (L167, **async**) against `QualificationStore` (AD-595d). Billet qualifications (post test-names) are a SEPARATE system from AD-894 tool grants — see §3b of the canonical doc. Read-only here; no billet mutators.
- **Async/sync (VERIFIED — get this right or the endpoint returns a coroutine):** `WorkItemStore.list_work_items(...)` is **async** (await it). `BilletRegistry.check_qualifications(...)` is **async** (await it). `BilletRegistry.resolve(...)` and `get_roster()` are **sync** (do NOT await).

**Build.** New `src/probos/routers/crew.py` (prefix `/api/crew`, registered like
the skills router):
- `GET /api/crew/roster` → **the EDVR full-crew roster.** Reconciliation (the single highest-risk step in the epic): start from `runtime.registry.all()` filtered by `is_crew_agent` — this is the complete "who is aboard" set, **per-instance**. Then call `runtime.ontology.get_crew_manifest(...)` (passing `runtime.trust_network` and `runtime.callsign_registry` for enrichment, exactly as `routers/ontology.py` does) and use it as a **by-`agent_type` enrichment map** for `post`/`department`/`rank`. Emit one roster entry per crew instance: assigned agents carry their manifest facets; **unbilleted agents (registry-present, manifest-absent) carry `post=None`/`department=None` and an explicit `assigned: false` (`billet_state: "unbilleted"`) flag** so the gap is visible, not hidden. Do NOT use the manifest alone — it drops unbilleted crew. The registry is authoritative for *who exists*; the manifest is authoritative for *org-chart facets*. Then augment each entry with `lifecycle_state` (from `acm.get_lifecycle_state`) and cheap `skill_count`/`tool_count`. Document both sources in the docstring.
- `GET /api/crew/{agent_id}/record` → `await runtime.acm.get_consolidated_profile(agent_id, runtime)`
  **plus** an `active_assignments` block (open + in_progress work items via
  `list_work_items(assigned_to=agent_id)`) **plus** a `billet` block read from
  `runtime.billet_registry` (VERIFIED public, `runtime.py` L1438): the agent's
  post (`resolve(post_id)` → `BilletHolder` title/department) and its
  **qualification standing** (`check_qualifications(billet_id, agent_type,
  agent_id)` → `{qualified: bool, missing: [test_name]}`). Honest-degrade if
  `billet_registry` is None. 503 if `runtime.acm` absent; 404 if the agent is
  unknown.

**Authority / single-source-of-truth note.** The ACM (`get_consolidated_profile`)
and the ontology (`get_crew_manifest`) are two views of one crew agent that
*overlap* on `department` and `rank` and can **drift**: the ACM reads them from
the `CrewProfileStore` (block 2), while the manifest reads `department`/`post`
from the ontology *assignment* and derives `rank` from `trust_network` via
`Rank.from_trust`. The record endpoint is **ACM-authoritative** for the
per-agent view (it is the HR record); the roster is **ontology-authoritative**
for org-chart facets (post, assignment, chain of command). Do not reconcile them
in this AD — just document which surface owns which field in the router
docstring so the drift is explicit, not silent. (See §3a of the canonical doc.)

**Do not change.** The existing `/api/agent/{id}/profile`, `/api/skills/*`,
`/api/ontology/crew-manifest`, and `/api/work-items` endpoints. AD-892 is purely
additive (a new router).

**Tests.** `tests/test_ad892_crew_record_api.py` (FastAPI `TestClient`, real
runtime fixture per the existing router tests; real `OntologyService` per
BF-287): roster wraps the manifest + carries `lifecycle_state`/`skill_count`,
**roster includes an unbilleted/unassigned agent (registry-present,
manifest-absent) carrying `assigned: false`**, record returns the consolidated
profile + assignments, 404/503 paths.

---

## AD-893 — Standing Orders read surface (#857)

**Why.** The record should show the orders the agent operates under; today
standing orders are internal system-prompt composition only.

**Verify-first anchors.**
- `src/probos/cognitive/standing_orders.py` — `compose_instructions(agent_type, hardcoded_instructions, callsign="")` (L360) **returns a single merged `str`** (`## `-prefixed sections + identity/personality), NOT four discrete tiers; `clear_cache()` (L227); `get_department(agent_type)` (L77); `_AGENT_DEPARTMENTS` (L40); 4-tier file layout `config/standing_orders/{federation,ship,<dept>,<agent_type>}.md`. The tier-file readers `_load_file`/`_DEFAULT_ORDERS_DIR` are module-private.

**Build.** Because the personnel view needs the four tiers **separately** (AD-897
renders them as distinct sections) and `compose_instructions` only returns one
merged prompt string, add a small **public tier-reader** to `standing_orders.py`
(e.g. `get_order_tiers(agent_type) -> list[dict]`) that reads the four tier files
directly via the existing private `_DEFAULT_ORDERS_DIR` + `get_department`, each
as `{tier, source_file, present: bool, text}`. Do NOT widen the private helpers —
add one public function that uses them. Then add
`GET /api/crew/{agent_id}/standing-orders` to `routers/crew.py`: resolve the
agent's `agent_type`, call `get_order_tiers`, return the four tiers. Do NOT run
the full LLM-prompt composition with personality injection — the personnel view
wants the *orders*, not the assembled prompt. Read-only.

**Do not change.** `compose_instructions` and the order files. No editing path.

**Tests.** `tests/test_ad893_standing_orders_api.py`: returns the four tiers,
missing department/agent file → `present: false` (not a crash), unknown agent →
404.

---

## AD-900 — Governed directive authoring surface (#864)

**Why.** The Captain must be able to **edit an agent's standing orders from the
ACM, governed by an approval gate** — not just read them. The governed write path
**already exists**: `DirectiveStore` (AD-386) is the evolvable runtime overlay
that `compose_instructions` already merges on top of the immutable 4-tier files.
It carries the full authorization + approval model. This AD exposes it over HTTP;
it does NOT build a new gate and does NOT edit the static `.md` tier files
(`federation.md` is immutable by design — see §6 of the canonical doc).

**Verify-first anchors (all VERIFIED 2026-06-06).**
- `runtime.directive_store` (public; wired into `standing_orders` via `set_directive_store`, AD-386). `runtime.py` L25-26.
- `src/probos/directive_store.py` — `create_directive(*, issuer_type, issuer_department, issuer_rank, target_agent_type, target_department, directive_type, content, authority=1.0, priority=3, expires_at=None) -> (RuntimeDirective | None, reason)` (L277); `approve(directive_id) -> bool` (promotes `PENDING_APPROVAL` → `ACTIVE`); `revoke(directive_id, revoked_by) -> bool`; `amend(directive_id, new_content, amended_by) -> RuntimeDirective | None`; `all_directives(include_inactive=False)`; `get_active_for_agent(agent_type, department)`. `DirectiveType` enum (`CAPTAIN_ORDER`, `COUNSELOR_GUIDANCE`, `CHIEF_DIRECTIVE`, `LEARNED_LESSON`, `PEER_SUGGESTION`); `DirectiveStatus` (`ACTIVE`, `PENDING_APPROVAL`, `REVOKED`). `authorize_directive(...)` is the gate.
- **The proven CLI pattern to mirror:** `src/probos/experience/commands/commands_directives.py` — `cmd_order` (issue `CAPTAIN_ORDER`, `issuer_rank=Rank.SENIOR`, `priority=5`), `cmd_directives` (list), `cmd_revoke`, `cmd_amend`. **Every mutation calls `clear_cache()` from `probos.cognitive.standing_orders`** to invalidate composed instructions — the HTTP endpoints MUST do the same.
- Department resolution: `runtime.ontology.get_agent_department(agent_type)` with `standing_orders.get_department(agent_type)` fallback (the `cmd_order` pattern).

**Build.** Add to `routers/crew.py`:
- `GET /api/crew/{agent_id}/directives` → resolve `agent_type`; return `all_directives(include_inactive=False)` filtered to that agent (+ `"*"` broadcast), each as `{id, directive_type, content, status, priority, issued_by, target_department}`. Includes `PENDING_APPROVAL` items so the Captain sees the approval queue.
- `POST /api/crew/{agent_id}/directives` (body `{content, priority?}`) → `create_directive(issuer_type="captain", issuer_department=None, issuer_rank=Rank.SENIOR, target_agent_type=<agent_type>, target_department=<ontology dept>, directive_type=DirectiveType.CAPTAIN_ORDER, content=..., priority=5)`. On success call `clear_cache()`. Captain orders land `ACTIVE` immediately (Captain authority). Return the directive or the authorization `reason` on failure (e.g. duplicate).
- `POST /api/crew/directives/{directive_id}/approve` → `approve(directive_id)` then `clear_cache()`. This is the **approval gate** for `PENDING_APPROVAL` directives (lower-rank `learned_lesson`/`peer_suggestion`). 404 if not found / not pending.
- `DELETE /api/crew/directives/{directive_id}` → `revoke(directive_id, revoked_by="captain")` then `clear_cache()`.
- (Optional, mirror `cmd_amend`) `PATCH /api/crew/directives/{directive_id}` (body `{content}`) → `amend(...)` + `clear_cache()`.

**Authority.** Issuing/approving/revoking a directive is a governed state change.
The authorization model lives in `authorize_directive` / `create_directive` — do
NOT bypass it. Captain-issued `CAPTAIN_ORDER`s are auto-`ACTIVE` (existing
Minimal-Authority decision); lower-authority directives stay `PENDING_APPROVAL`
until `approve`. No new consensus gate. Record the decision in DECISIONS.md.

**Do not change.** `DirectiveStore`, `authorize_directive`, the CLI commands, the
static `.md` tier files, or `compose_instructions`. AD-900 is a thin HTTP surface
over the existing store — and it must invalidate the standing-orders cache on
every mutation exactly as the CLI does.

**Tests.** `tests/test_ad900_directive_api.py` (real `DirectiveStore` per BF-287,
FastAPI `TestClient`): issue a captain_order → it appears `ACTIVE` in the list;
revoke → it disappears; a `PENDING_APPROVAL` directive can be `approve`d → becomes
`ACTIVE`; duplicate issue returns the authorization reason; unknown directive →
404; assert `clear_cache` is invoked on mutation (the composed-instruction
invalidation contract).

---

## AD-901 — Standing Orders & Directives management view (#865)

**Why.** The UI for AD-900 — the governed edit surface for an agent's standing
orders inside the Service Record.

**Verify-first anchors.**
- AD-897 `ServiceRecord` Standing Orders section (renders the AD-893 read-only tiers).
- The console's existing action/confirm patterns (mirror AD-898/899 grant/revoke confirm dialogs).
- `ui/src/components/icons/Glyphs.tsx` stroke-only glyphs; amber active state.

**Build.** Extend the Service Record's **Standing Orders** section into a
two-part view: (1) the read-only 4-tier composed orders (AD-893, unchanged
context), and (2) a **Directives** panel bound to AD-900 — list active +
pending-approval directives for the agent, **issue a new Captain's order**
(content + priority), **approve** a pending directive (the approval gate made
visible), and **revoke** with confirm. Pending-approval directives are visually
distinct (amber/awaiting). Destructive/governing actions are clearly marked and
confirmed. Stroke-only glyphs; no emoji.

**Tests.** `ui/src/components/personnel/StandingOrders.test.tsx` (Vitest): tiers
render, issuing an order calls the POST endpoint, a pending directive shows an
approve affordance, revoke confirms, no emoji.

---

## AD-894 — Tool Registry + certification surface (#858)

**Why.** "Tools they are certified to use" + the ability to manage
certifications. No HTTP surface for the tool registry or grants exists today.

**Verify-first anchors.**
- `src/probos/tools/registry.py` — `list_tools(tool_type, domain, department, tag, enabled_only)` (L147), `get(tool_id)`, `check_permission(...)`.
- `src/probos/tools/permissions.py` — `issue_grant(agent_id, tool_id, permission, *, is_restriction=False, reason="", issued_by="captain", expires_at=None) -> ToolAccessGrant`, `revoke_grant(grant_id) -> bool`, `get_active_grants_sync(agent_id, tool_id)`, `list_grants(active_only)`, `ToolPermission` enum.
- `runtime.tool_registry` (`runtime.py` L715, real attr) and `runtime.tool_permission_store` (`runtime.py` L718, real attr) — both real, not hasattr-only.
- **Async/sync (VERIFIED):** `issue_grant`, `revoke_grant`, `list_grants` are **async** (await them). `get_active_grants_sync` and `list_tools`/`get` are **sync** (do NOT await). `list_tools(*, tool_type, domain, department, tag, enabled_only)` is keyword-only — pass by keyword.

**Build.** Add to `routers/crew.py` (or a sibling `routers/tools.py` — pick one,
document why):
- `GET /api/tools` → the asset catalog: `list_tools()` mapped to
  `{tool_id, tool_type, provider, domain, department, tags, enabled}`.
- `GET /api/crew/{agent_id}/tools` → the agent's **certifications**: active
  grants (`get_active_grants_sync` / `list_grants(active_only=True)` filtered to
  the agent) joined with the registration metadata.
- `POST /api/crew/{agent_id}/tools` (body `{tool_id, permission, reason}`) →
  `issue_grant(...)`, `issued_by="captain"`. **Captain-authorized privilege
  change** — audited via the grant record.
- `DELETE /api/crew/{agent_id}/tools/{grant_id}` → `revoke_grant(grant_id)`.

**Authority.** Granting/revoking a tool is a state change. It is recorded as a
`ToolAccessGrant` (auditable) and attributed to the Captain. Do **not** add a
consensus gate (these are reversible, Captain-authority privilege edits — note
the decision in DECISIONS.md per the Minimal-Authority axiom), but do **not**
bypass the grant-record audit trail either.

**Tests.** `tests/test_ad894_tool_cert_api.py` (real `ToolRegistry` + real
`ToolPermissionStore` per BF-287): catalog list, agent certifications, grant
then it appears, revoke then it disappears, unknown tool/agent error paths.

---

## AD-895 — Skill Library CRUD (#859)

**Why.** The Captain's explicit ask: "manage all skills available for crew
members… full CRUD on skills." The skill-definition library is
`runtime.skill_registry` (`SkillRegistry`), which is **already a writable,
SQLite-backed, cloud-ready store** — it has `register_skill` (async
`INSERT OR REPLACE`), a `connection_factory: ConnectionFactory | None` Protocol
seam, and seeds its built-ins from Python constants at startup. What it is
*missing* is a **delete** verb (with safety guards) and an **HTTP surface**. This
AD adds exactly those two things — it does NOT build a parallel persisted store
(that would create a second source of truth that diverges from the registry
onboarding/commission already read).

**Verify-first anchors (corrected after Architect verification).**
- `src/probos/skill_framework.py` — `SkillRegistry.__init__(db_path, connection_factory=None)` (`connection_factory` defaults to `default_factory`, ~L990; the cloud-ready Protocol seam **already exists**); `register_skill(defn)` (~L1066, **async**, `INSERT OR REPLACE` + commit = create AND update); `start()` (~L977, async, loads cache from DB); `register_builtins()` (~L1085, seeds `BUILTIN_PCCS` + `ROLE_SKILL_TEMPLATES` from Python constants — NOT from a YAML); `get_skill` / `list_skills(category, domain)` (**sync**). `SkillDefinition` fields (`skill_id`, `name`, `category` [`SkillCategory`], `description`, `domain`, `prerequisites`, `decay_rate_days`, `origin`, `preferred_tools`).
- `runtime.skill_registry` is the real attr, constructed at `startup/communication.py` ~L346 as `SkillRegistry(db_path=skills_db)`.
- `src/probos/skill_framework.py` `AgentSkillService` — how acquired records reference `skill_id` (so a delete can check "in use").
- **NOTE:** `config/ontology/skills.yaml` is the ontology role-template / qualification-path file (`ontology/loader.py` `_load_skills_schema`, AD-429b) — a **different subsystem**. Do NOT seed the skill-definition store from it; there is nothing to re-seed (`register_builtins()` already runs at startup).

**Build.**
1. Add `delete_skill_definition(skill_id)` to `SkillRegistry` (async, mirrors
   `register_skill`'s connection handling) with **validation**:
   - reject delete of a **built-in PCC** (a skill in `BUILTIN_PCCS`) — return a
     clear error, don't cascade;
   - reject delete of any skill **in active use** by an agent (check
     `AgentSkillService`) — clear error, don't cascade.
2. `update_skill_definition(skill_id, **fields)` is a thin wrapper over the
   existing `register_skill` (the `INSERT OR REPLACE` already updates); on create
   reject a duplicate `skill_id`, and validate that `prerequisites` reference
   existing skills (no dangling prereq).
3. HTTP on `routers/skills.py`: `GET /api/skills/definitions` (→ `list_skills`),
   `POST /api/skills/definitions` (→ `register_skill`, reject duplicate),
   `PUT /api/skills/definitions/{skill_id}` (→ `register_skill` update),
   `DELETE /api/skills/definitions/{skill_id}` (→ `delete_skill_definition`).
   **Async:** `register_skill`/`delete_skill_definition` are async (await them);
   `get_skill`/`list_skills` are sync.

**Do not change.** The per-agent skill-record endpoints (`assess`/`exercise`/
`commission`), the AD-887 unified-profile path, `SkillDefinition`'s field shape,
or the existing `register_skill`/`start`/`register_builtins` behavior. AD-895
adds a delete verb + validation + HTTP over the **existing** writable registry.

**Tests.** `tests/test_ad895_skill_library_crud.py` (real `SkillRegistry(db_path=tmp)`
per BF-287): create/list/update/delete round-trip; duplicate rejected;
delete-in-use rejected; built-in PCC protected; dangling-prereq rejected;
persistence survives a `start()` reload.

---

## AD-896 — Crew Personnel Console shell (#860)

**Why.** A *separate experience* — the Ship's Office — not another profile tab.

**Verify-first anchors.**
- `ui/src/components/wardroom/WardRoomPanel.tsx` (L116/L126) — the AD-837 display-mode system (docked / floating / maximized; drag; resize; `localStorage` `probos.wardroom.mode`/`probos.wardroom.rect`). Reuse this pattern.
- `ui/src/components/CrewRosterPanel.tsx` (L44) — existing roster list (department grouping, rank/trust badges).
- `ui/src/components/profile/AgentProfilePanel.tsx` (L32) — resize-handle + `localStorage` size persistence convention.
- The store (`useStore()`), `ui/src/components/icons/Glyphs.tsx`, and the ViewSwitcher/launch surface that opens panels.

**Build.** A new `CrewPersonnelConsole` window component: resizable, draggable,
dockable (mirror WardRoom modes), `localStorage`-persisted rect/mode. Master-detail
layout — roster (left, bound to `GET /api/crew/roster`) selects an agent →
service-record detail (right, AD-897). A launch affordance to open it (consistent
with how other panels open). Stroke-only glyphs; amber active state.

**Tests.** `ui/src/components/personnel/CrewPersonnelConsole.test.tsx` (Vitest):
renders roster, selecting an agent loads the record pane, mode toggle persists,
no emoji in output.

---

## AD-897 — Service Record detail view (#861)

**Why.** The Workday-style ESR — the per-agent personnel profile inside the
console.

**Build.** A `ServiceRecord` view bound to `GET /api/crew/{agent_id}/record`,
`/standing-orders`, and `/tools`, sectioned (tabs or accordion — progressive
disclosure): **Identity & Role** (callsign, dept, rank, **post/billet title +
qualification standing** from the record's `billet` block, RoleTemplate, Big
Five) · **Skills & Proficiency** (developmental + cognitive, with proficiency
bars) · **Qualifications** — show **both** qualification homes: certified tools
(AD-894 grants) AND billet qualification standing (qualified / missing tests,
AD-595d) · **Duties & Active Assignments** (the watch bill + in-flight work) ·
**Standing Orders** (the 4 tiers) · **Experience** (trust, earned agency, episode
count). Read-only display; the grant/revoke and skill-edit actions live in
AD-898/899.

**Tests.** `ui/src/components/personnel/ServiceRecord.test.tsx` (Vitest): each
section renders from a seeded record; empty facets degrade gracefully (no
duties → "No standing duties"); no emoji.

---

## AD-898 — Skill Library management view (#862)

**Why.** The UI for AD-895 CRUD — the skill-library admin console.

**Build.** A `SkillLibrary` management view in the console: browse/filter the
definition list (`GET /api/skills/definitions`), create (`POST`), edit (`PUT`),
retire (`DELETE`) with confirm + the AD-895 validation errors surfaced inline
(in-use/built-in protected). Stroke-only glyphs; destructive actions clearly
marked and confirmed.

**Tests.** `ui/src/components/personnel/SkillLibrary.test.tsx` (Vitest): list
renders, create form validates, delete confirms, an in-use delete shows the
server error, no emoji.

---

## AD-899 — Tool certification management view (#863)

**Why.** The UI for AD-894 — the asset/certification surface.

**Build.** A `ToolCertifications` view: browse the tool registry catalog (`GET
/api/tools`), and per selected agent view certifications (`GET
/api/crew/{id}/tools`), grant (`POST`) and revoke (`DELETE`) with confirm. Frame
it as PQS-style qualification (the asset-management counterpart to the personnel
record). Stroke-only glyphs.

**Tests.** `ui/src/components/personnel/ToolCertifications.test.tsx` (Vitest):
catalog renders, grant adds a certification, revoke confirms and removes, no
emoji.

---

## Epic acceptance

- Eleven commits, AD-891 → AD-901, in build order, each with PROGRESS.md +
  DECISIONS.md updated in the same commit. Not pushed.
- Backend gates (891-895, 900) green serially; UI gates (896-899, 901) green via
  Vitest.
- The two known pre-existing `bf207` failures are the only tolerated reds.
- The Captain can open the Ship's Office, pick a crew agent, and see their full
  service record — role, skills, certified tools, duties, active assignments,
  standing orders, experience — **issue/approve/revoke standing-order directives
  through the existing DirectiveStore approval gate**, and manage the skill
  library and tool certifications.
- Verify all changes comply with the Engineering Principles in
  `.github/copilot-instructions.md`.
