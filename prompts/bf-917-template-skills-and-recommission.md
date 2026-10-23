# BF-917 and BF-915: the role templates' skills are registered definitions, a changed role template re-commissions a crew member once without loss, and the Yeoman and the Training Officer get templates

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-22

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-23 (Amendment A1, review round 1)

**Status:** build-ready after the orchestrator's verification and the §16 live checks. Batch: M1 = BF-917 (#1625), M2 = BF-915 (#1623), one gate, one PR, closing both. **Tier HIGH** (raised from STANDARD by the Architect: the re-commission rewrites live crew commissioning records at boot, and their skill proficiencies must survive; never lowered without the Captain). **Base:** this tree `88f0e5b8` (AD-1341 S1 and BF-916 as they will land) on `origin/main` `80456da2`. BF-912 (#1615) is built and merged before this batch. It touches only `cognitive/decomposer.py`, one new test and the trackers; §8 anchors survive its entries (stated there). **Source:** the Architect's next-wave ruling (A2, 2026-10-22) and this consult.

**Tests:** M1 adds `tests/test_bf917_template_skills_and_recommission.py` (16 functions, 17 cases; A1 added E5 and E6) and `tests/fixtures/crew_template_world.py`. M2 adds `tests/test_bf915_yeoman_and_training_templates.py` (4 functions, 5 cases). M2 updates `tests/test_ontology_skills.py` (template count) and `tests/test_bf906_crew_enrollment_boot.py` (T-B1's yeoman tail).

**Line endings:** working copies are CRLF (`core.autocrlf=true`). The SEARCH blocks are LF; match and write with the file's own endings. New files are written LF.

**Re-verification and a mechanical repair by the orchestrator (2026-10-23; no decision changed):** (1) re-verified by tool on `origin/main` `6b950acf` (AD-1347 S1 and S4 merged on top of BF-912; the base statement above is historical): all 31 code pairs and both tracker pairs apply exactly once, the 20 new tests pass five of five runs, every mutation row's line occurs exactly once, and the phantom precheck is clean; (2) the "Mutate to" cells of rows M1-R2, M1-R3 and M2-R4 stated the mutation as prose ("the same line with ..."), which the campaign runner cannot parse (it parsed 19 of 22 rows); they now carry the literal mutated line, so this contract is itself the campaign's table.

**Amendment A1 (2026-10-23, review round 1 on candidate `22b179c5`, tree `4bb80970`).** F1: `enroll` is serialized by one lock per enroller (§7.3 pair 6a and pair 6), because the `IS NOT ?` guard protects only the commissioning record, and the chain's skill writes are fresh-record upserts after a snapshot. F2: a re-commission that leaves a PCC missing is not recorded and is retried (§7.3 pair 8), the rule `_commission` already keeps. F3: recorded, not fixed; the doctor check's text now says what it does. F4: the fingerprint's comment no longer says the chain never acquires an optional id. Tests: E4 asserts each guard's own message, and E5 and E6 are new, so the batch adds 22 tests. Mutation table: M1-R6 is rewritten so the missing guard, not a binding error, kills it; M1-R19 and M1-R20 are added, for 24 rows. Code pairs: 32. Campaign of record: rerun M1-R6, M1-R9 to M1-R16, M1-R18, M1-R19 and M1-R20; every other row keeps the round-1 result when its file and the M2 test file are byte-equal to that candidate.

---

## 0. Premise: what is present on this tree

| Clause | State | Evidence |
|---|---|---|
| 14 role templates, 67 required entries, 39 of them name 22 unregistered ids; all 14 optional entries resolve | present | `config/ontology/skills.yaml:44-261`; §3 D1 table |
| `register_builtins` registers only the PCCs and the legacy `ROLE_SKILL_TEMPLATES` | present | `skill_framework.py:1118-1124` |
| `acquire_skill` checks prerequisites only when a definition exists | present | `skill_framework.py:1310-1321` |
| `get_profile` files a record with no definition under acquired skills | present | `skill_framework.py:1498-1507` |
| Decay gives an undefined record 14 days; `check_decay` has no production caller | present | `skill_framework.py:1456`; Absence AV1 |
| The enroller never commissions an agent with a record again | present | `crew_enrollment.py:177-181` |
| The chain's step 3 runs only when the context has a tool registry, a permission store and a skill registry | present | `commissioning.py:112-120` |
| `AgentCapitalService` is at 15/15 direct methods, pinned | present | `acm.py:132-548` (15 defs); `tests/test_bf906_acm_commissioning.py:540-580`; `check_architecture_principles.py:187-188` |
| Yeo and Tucker have no template and no legacy role skills | present | `skills.yaml` (no `yeoman`/`chief_training` key); `skill_framework.py:874-941` keys |
| Live: each templated crew member holds its orphan ids at template floors; Yeo and Tucker hold the 9 PCCs; one tool grant in total | taken from #1625 and #1623 (live reads 2026-10-22) | §16 re-verifies before the build |

## 1. Problem

The role templates in `config/ontology/skills.yaml` name 22 skill ids that no definition registers. Commissioning writes records under them anyway (`commissioning.py:81-97`, `skill_framework.py:1310-1333`). The profile then files those records as acquired skills, not role skills (`:1498-1507`), and the AD-888 tool step skips them silently (`commissioning.py:125-127`). Nothing detects an unregistered template id.

The Ship's Yeoman (`yeoman`) and the Training Officer (`chief_training`) have no template at all. BF-906 commissioned them with the nine PCCs and `role_template=None` (`crew_enrollment.py:299-315`). Adding templates now would change nothing for them: once a record exists, the enroller never commissions that agent again (`:177-181`). The Captain's re-commission routes would not help either. They run with `preserve_existing=False` and would reset each PCC to FOLLOW (`routers/crew.py:631`, `routers/skills.py:140`).

## 2. Solution overview

- **M1 (BF-917).**
  - Register the 22 ids as role-skill definitions in a new list, through one function that `register_builtins` and the doctor both use.
  - Give each commissioning record a fingerprint of the template it was commissioned under.
  - When the template an agent resolves now has a different fingerprint, the enroller re-commissions it once:
    - it uses `preserve_existing=True`, so every existing record keeps its proficiency, exercise count and history;
    - it runs on a context with no tool services, so it grants no tool;
    - it records the new fingerprint and a "re-commissioned" history row, only after the chain has succeeded.
  - A doctor check WARNs for any unregistered template id.
- **M2 (BF-915).**
  - Add the `yeoman` and `chief_training` templates and their eight skill definitions.
  - The doctor also WARNs for an assigned crew post that has no template.
  - M1's trigger applies the new templates to Yeo and Tucker, because going from no template to a template changes the fingerprint.

## 3. Decisions

**D1: the registration** (in the envelope).

| ID | Required entries in `skills.yaml` (line) | Domain | Legacy role skills already in that domain for these posts' agent types |
|---|---|---|---|
| `architecture_review` | 53 | science | architect: `design_review` |
| `pattern_recognition` | 55, 115, 129, 145, 161 | science | architect, scout, data_analyst, systems_analyst, research_specialist |
| `trend_analysis` | 117, 131, 147 | science | scout, data_analyst, systems_analyst |
| `data_processing` | 133 | science | data_analyst |
| `quantitative_analysis` | 135 | science | data_analyst |
| `cross_department_synthesis` | 149 | science | systems_analyst |
| `emergence_analysis` | 151 | science | systems_analyst |
| `technical_writing` | 165 | science | research_specialist |
| `evidence_analysis` | 167 | science | research_specialist |
| `wellness_assessment` | 69 | medical | counselor: `cognitive_health_eval` |
| `personality_analysis` | 71 | medical | counselor |
| `crew_counseling` | 73 | medical | counselor |
| `diagnostic_analysis` | 179, 193, 207, 221 | medical | diagnostician, surgeon, pharmacist, pathologist |
| `health_monitoring` | 181, 195, 209, 223 | medical | the same four |
| `treatment_planning` | 183, 197, 211, 225 | medical | the same four |
| `systems_analysis` | 85, 101 | engineering | engineering_officer, builder |
| `architecture_implementation` | 89, 105 | engineering | engineering_officer, builder |
| `threat_assessment` | 237 | security | security_officer |
| `access_control` | 239 | security | security_officer |
| `vulnerability_analysis` | 241 | security | security_officer |
| `workflow_optimization` | 255 | operations | operations_officer |
| `system_monitoring` | 257 | operations | operations_officer |

That is 39 entries and 22 ids. The other 28 required entries and all 14 optional entries already resolve.

Every definition has: category ROLE, origin `role`, a name and a one-line description, no prerequisites, no `preferred_tools`, no composite or synergy partners, and `decay_rate_days=14`. No id is left unregistered.

Options, ranked:

1. **A new `ONTOLOGY_TEMPLATE_SKILLS` list plus `builtin_skill_definitions()` (chosen).** It changes no acquisition path, and one function serves both the registry and the doctor.
2. Add the ids under `ROLE_SKILL_TEMPLATES` agent-type keys. Rejected: `commission_agent` would then also acquire them at FOLLOW (`:1368-1378`), and `pattern_recognition` alone would be listed five times.
3. Declare them in a `skill_definitions:` section of `skills.yaml`, loaded by the ontology. Rejected for this BF: it needs a new loader and registry wiring (considered, deferred).
4. Rename the three near-names. Rejected: the live records under the template ids would be orphaned.

**Guard 1 (no tool).** The resolver returns tools only through `preferred_tools` (empty here) or through `list_tools(tag=skill.domain)`, a case-insensitive substring match (`registry.py:252-254`). Every new domain is one that some legacy role skill already has, and for the M1 ids it is one that each post's own agent type already holds (table above). So for every agent and every registry, a new skill resolves exactly what a legacy skill of its domain resolves, and commissioning asks no new tag question. G3 proves this twice: against the tools startup seeds from the ontology (`startup/communication.py:804-821`), and against a probe tool tagged with each domain. The M2 ids use `operations`, a legacy domain. `bridge` was considered for the Yeoman and rejected: it would be a tag question no crew member asks today.

**Guard 2 (decay and acquisition).**
- `check_decay` has no production caller (AV1).
- Where it does run, an undefined record already gets 14 days (`:1456`), and 14 is what every new definition sets.
- No new definition has a prerequisite, so `acquire_skill` behaves exactly as it does with no definition (`:1311-1321`).
- Re-commission preserves every held record (D2).
- No live proficiency can drop. G4 and E1 pin this.

**D2: the trigger** (in the envelope).

*What is compared.* `template_fingerprint(template)` is the sha256 of canonical JSON `{"post_id", "required": sorted [skill_id, min_proficiency]}`. "No template" has its own digest, so gaining or losing a template is a change. Optional skills are left out because the chain reads only `required_skills`. An optional id can still be held (a PCC or a legacy role skill is acquired by the chain's base step), but a change to the optional list changes nothing the chain does, so it does not trigger.

*Where it is stored.* A new nullable column, `commissioning_records.template_fingerprint`. `AgentCapitalService.start` adds it when `PRAGMA table_info` does not show it. That is the migration: additive and idempotent. Old rows need nothing: NULL means "commissioned before BF-917", which compares unequal and causes one re-commission.

*Where it runs.* `CrewEnrollmentService.enroll`, which is reached by the boot pass and by the joining path. The doctor does not run it.

*What it does:*
- Template unchanged: nothing is called, nothing is written.
- Agent decommissioned: nothing.
- Template changed:
  1. read the profile;
  2. run `acm.commission(..., preserve_existing=True)` on a `_RecommissionContext` that has the skill service and the ontology but no tool registry, permission store or skill registry, so step 3 cannot run;
  3. require a non-empty `skills_acquired` (the chain returns an empty list when its own snapshot failed, `commissioning.py:53-62`; `test_bf906_acm_commissioning.py:525`), and require that it names every PCC in `BUILTIN_PCCS` (A1: the rule `_commission` keeps, BF-906 A3; the chain logs a failed base step at DEBUG and still returns the profile it read, `commissioning.py:66-73`);
  4. then `record_commissioning(..., recommission=True)`. This is one guarded write: `UPDATE ... SET role_template, template_fingerprint WHERE agent_id = ? AND template_fingerprint IS NOT ?`, plus a "re-commissioned" history row, in one commit, rolled back together on any failure.
- **Failure:** when the chain raised, read no profile or left the agent without a PCC, nothing is recorded, an ERROR naming the cause is logged, and the next enrollment (the next boot at the latest) retries. A required skill the chain skips because its prerequisite is unmet is AD-889's expected case and does not block the record. Skills acquired before a refused or failed record write are preserved, so the retry acquires only what is still missing.
- **Idempotence:** a second boot finds the fingerprint equal and does nothing. The `IS NOT ?` guard makes a repeated attempt write no second record and no second history row. It does not protect skill records.
- **Overlap (A1).** The chain snapshots the profile and then writes each skill it found missing as a fresh record (`acquire_skill` through `_upsert_record`, `skill_framework.py:1383-1392, 1738-1751`). Two overlapping enrollments of one agent would therefore both acquire a missing skill, and the later write would reset a record the earlier one had already advanced. `enroll` holds one `asyncio.Lock` per enroller from the onboarding step to the recording, around both `_commission` and the re-commission. An overlapping enrollment waits, then reads the record the first wrote, finds the fingerprint equal and returns `commissioned=False, recommissioned=False` (E6). The lock is always taken outside ACM's `_write_lock`, and nothing reachable while it is held calls the enroller, so there is no cycle and no re-entry. Startup builds one enroller (`startup/crew_enrollment.py:26`); two instances over the same stores are not serialized against each other (F-348 on #1523).

Options for overlap (A1), ranked:

1. **One lock per enroller around the body of `enroll` (chosen).** One object with nothing to clean up, and it serializes onboarding too. Enrollments of different agents also wait for each other; the boot pass is serial already, and a join costs a few SQLite statements.
2. A per-agent lock map. The same guarantee for one agent, plus a map to bound or clean up, with no measured need for concurrent enrollments of different agents.
3. A lock around the two commission bodies only. It leaves the record read and onboarding outside, so it is the same fix with a narrower scope and no gain.
4. Insert-if-absent skill writes under `preserve_existing`. It changes `acquire_skill` and AD-889, which the Captain's `preserve_existing=False` routes share; recorded as the direction on F-348.
5. Record it and weaken the claim. Rejected: this contract promised overlap safety, AD-1273 requires a double-wire to be harmless (`agent_onboarding.py:126-127`), and the fix is about ten lines.
- **What `preserve_existing=True` keeps:** every record the agent holds, at its current proficiency, exercise count, timestamps and history, including any proficiency above the template's floor. Only skills the agent lacks are acquired, at the template floor.
- **What the record keeps:** its skills, tools, source and timestamp stay those of the first commissioning.
- **A skill dropped from a template** is never deleted.

Options for the storage, ranked:

1. **Column (chosen).**
2. A separate table. Rejected: the store declaration notes would need changes, and a second row per agent would have to be kept consistent.
3. Stateless "a required skill is not held". Rejected: chief_engineer and builder can never hold `performance_optimization` (its prerequisite chain fails at FOLLOW, `:882-883`), so the rule would fire and write a history row on every boot.
4. Compare only the post id. Rejected: it misses content changes, which is the point of BF-917.

Options for the tool step, ranked:

1. **Narrowed context (chosen).** Least authority, and no AD-889 signature change.
2. A `grant_tools=False` parameter on `commission`/`commission_chain`. Rejected: it changes the AD-889 seam, and the precheck flags the new kwarg at every call site.
3. Run the full chain. Rejected: it re-walks step 3 for all 16 crew and would grant any tool a tag matches today. That crosses the envelope; #1625's tool question stays with the Captain.

The ACM write goes through `record_commissioning`'s `recommission` mode because the class is at its method ceiling. A module function reaching into `acm._db` was rejected (private access).

**D3: decay and live data.** Resolved in Guard 2. Disclosed effects are in §8.

**D4: the doctor** (in the envelope).
- One check, `role_templates`, registered after `token_accounting` (`test_bf901_s3_token_accounting_view.py:457` pins `crew_enrollment` → `token_accounting`).
- It reads `config/ontology` through `OntologyLoader(dir)` with no data directory, so it creates nothing (`loader.py:153-162`). "Registered" means `builtin_skill_definitions()`, the boot set.
- **M1 rule:** a template skill id that is not registered → WARN, one detail line per `post: skill`.
- **M2 rule:** an assigned crew-tier post with no template → WARN, `post (agent_type)`.
- Severity is WARN, matching the issues. It reports only; no repair and no write (D2 test).
- **No startup WARNING.** Both inputs ship in the repo, so CI (G1, B1) fails before any boot could show one, and the doctor finds a local edit. The issue's "startup WARNING" acceptance line is replaced by this decision. A boot-time audit would also need ontology access that the stubbed `enroll_boot_crew` runtimes in `test_bf906_acm_commissioning.py:1274-1334` do not provide.

**D5: tests against real objects.** See §6.

**D6: mutation rows.** See §10.

**D7: tier and shape.** HIGH. M1 is §7.1–§7.9 and M2 is §7.10–§7.16, about 150 tool calls each at most. One broad gate and one PR, closing #1625 and #1623. The only Captain matter is #1625's tool question (should AD-889 step 3 grant tools at all?). It is carried, not decided, and does not block. Hard stop: §16 L1.

## 4. Milestones

| Milestone | Issue | Sections | Commit |
|---|---|---|---|
| M1 | BF-917 (#1625) | §7.1 to §7.9 | `BF-917: register the role templates' skills; a changed template re-commissions once without loss` |
| M2 | BF-915 (#1623) | §7.10 to §7.16 and §8 | `BF-915: templates for the Yeoman and the Training Officer; doctor reports a crew post without one` |
| docs | both | the *Validation of record* bullets (§8) | docs-only |

M1 opens at §7.1 and M2 opens at §7.10. M2's sections anchor on text M1 creates, so M1 must be built first.

## 5. Consumers of every value this changes

| Value | Consumers | Effect |
|---|---|---|
| 30 new definitions (`skill_definitions`) | `get_profile` (`:1498`), `acquire_skill` (`:1312`), `check_decay` (`:1455`, no caller), AD-888 resolver (`commissioning.py:125`, `routers/crew.py:519`), Skill Library and `/api/skills` (`routers/skills.py:30,102,438`), `readiness_reporter.py:79`, `skill_readiness.py:109`, `skill_bridge.py:53,244`, `commands_skill.py:310` | Formerly orphan records become role skills. Readiness denominators grow. `skill_bridge.resolve_skill_for_gap` maps intent `emergence_analysis` to the registered skill (`systems_analyst.py:60`). No tool. No prerequisite. |
| `commissioning_records.template_fingerprint` | `get_commissioning_record` (only reader of the row, plus the enroller); doctor `_COMMISSIONED_SQL` reads `agent_id` only | Additive. BF-906's statements name their columns. |
| "re-commissioned" history rows (from == to) | `get_transition_history`, HR history API; `_same_state` test helpers | One per template change per agent. |
| `CrewEnrollment.recommissioned` (default False) | `enroll_wired_crew` (counts `commissioned` only; pinned log line unchanged); `test_bf906_acm_commissioning.py:1026` (equality holds at the default) | None outside the enroller. |
| New templates `yeoman`, `chief_training` | `get_role_template_for_agent` (chain, enroller, `routers/ontology.py:170`, `routers/crew.py:556` roles view), `ontology/service.py:409` crew manifest | Yeo and Tucker resolve templates. |

## 6. Tests

**Focused gate (each milestone, Builder; the main session runs it once on the frozen candidate):**

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest -q -n 0 tests/test_bf917_template_skills_and_recommission.py tests/test_bf915_yeoman_and_training_templates.py tests/test_bf906_acm_commissioning.py tests/test_bf906_crew_enrollment_boot.py tests/test_bf906_doctor_check.py tests/test_ad889_commission_chain.py tests/test_acm.py tests/test_database_abstraction.py tests/test_skill_framework.py tests/test_ad895_skill_library_crud.py tests/test_ad428b_skill_advanced.py tests/test_ad566i_role_skill_template_expansion.py tests/test_ontology_skills.py tests/test_science_team.py tests/test_ad628_crew_skill_readiness.py tests/test_ad648_post_capability_profiles.py tests/test_ad801_doctor.py tests/test_ad1137_doctor.py tests/test_ad1137_quickstart_chain.py tests/test_bf901_s3_token_accounting_view.py tests/test_ad1328_s2a_startup_and_doctor.py tests/test_ad1195_eventlog_pair_freeze.py tests/test_ad1009_roles.py tests/test_ad892_crew_record_api.py tests/test_ad1256_store_registry.py tests/test_ad1343_seam_registry.py tests/test_ad1343_stop_seam_inventory.py tests/test_ad1184_ad_ledger.py
```

Plus `scripts/check_architecture_principles.py`, `scripts/check_store_registry.py --check` and `scripts/phantom-api-precheck.ps1 prompts/bf-917-template-skills-and-recommission.md`. M1's own run omits the M2 test file.

**New, M1:** `tests/test_bf917_template_skills_and_recommission.py`. On today's tree every test fails at import (the new names do not exist). G1, G5 and E1 also fail on the behaviour itself. On the round-1 candidate `22b179c5` (A1), E5 and E6 fail on the behaviour: the degraded re-commission is recorded, and `code_review` is acquired twice and its advanced record reset.

| Id | Test | Proves |
|---|---|---|
| G1 | `test_every_role_template_skill_is_a_registered_definition` | Real loader plus real `register_builtins`. No template id is unregistered. `(39, 22)`. Every new definition is named by some template. |
| G2 | `test_the_template_skills_change_no_acquisition_decay_or_tool_route` | Guards 1 and 2 on the data: ROLE, no prerequisite, preferred tool, composite or synergy; decay 14; legacy domain; unique ids. |
| G3 | `test_the_resolver_gives_a_template_skill_no_tool_its_domain_does_not_already_get` | Guard 1 behaviourally: startup's ontology-seeded tools give no new skill a tool; the probe registry shows the new skill resolves exactly what a legacy skill of its domain resolves. |
| G4 | `test_a_formerly_undefined_record_decays_exactly_as_before` | Guard 2: the same records decay identically at 13 days (none) and 20 days (one level) with and without the definitions. |
| G5 | `test_a_record_under_a_newly_registered_id_becomes_a_role_skill_unchanged` | An orphan record (LEAD, exercised) becomes a role skill with every field unchanged. |
| A1 | `test_a_bf906_acm_db_gains_the_fingerprint_column_and_keeps_its_rows` | Migration on BF-906's schema; row intact; NULL fingerprint; a second start is idempotent. |
| A2 | `test_a_recommission_replaces_only_the_template_and_writes_one_history_row` | `recommission=True`: False with no record or the same fingerprint; True replaces only role template and fingerprint; one history row. |
| E1 | `test_a_changed_role_template_is_applied_once_keeping_every_record_and_granting_no_tool` | **The seam.** Real ontology copy → birth → template edited → next boot re-commissions once, keeps every record (one above its floor), adds the new skill at its floor, updates the record, writes one history row, grants no tool although a full chain would; a third pass changes nothing. |
| E2 | `test_a_record_written_before_bf917_is_recommissioned_once_and_acquires_nothing` | The live first-boot path: a NULL fingerprint is re-commissioned once, acquires nothing, then is stable. |
| E3 | `test_a_decommissioned_crew_member_is_not_recommissioned` | Decommissioned agents are left alone. |
| E4 | `test_a_failed_recommission_records_nothing_and_the_next_boot_applies_it[raises\|no-profile]` | Fail closed and retry; each guard logs its own cause (A1). |
| E5 | `test_a_recommission_that_leaves_a_pcc_missing_records_nothing_and_the_next_boot_retries` | A1 (F2): a PCC missing after a failed base step is not recorded; one ERROR names the PCC; the next pass acquires it and records, keeping the record the degraded pass wrote. |
| E6 | `test_overlapping_enrollments_of_one_agent_acquire_a_missing_skill_once_and_keep_its_record` | A1 (F1): two overlapping enrollments acquire the new skill once, the advanced record survives, one result re-commissions, one history row. Bounded wait (2 s) on the passing run. |
| D1 | `test_the_doctor_reports_ok_for_the_shipped_templates` | OK; no data directory created. |
| D2 | `test_the_doctor_warns_for_an_unregistered_template_skill_and_writes_nothing` | WARN naming the post and the skill; the tree is unchanged. |
| D3 | `test_the_role_template_check_is_registered_once_after_token_accounting` | Fresh interpreter on this tree (PYTHONPATH asserted through `probos.__file__`); the neighbours are kept. |

**New, M2:** `tests/test_bf915_yeoman_and_training_templates.py`. B1, B2 and B4 fail on today's tree on the behaviour.

| Id | Test | Proves |
|---|---|---|
| B1 | `test_every_assigned_crew_post_resolves_a_role_template` | Real loader and service: no assigned crew post lacks a template. |
| B2 | `test_the_yeoman_and_training_templates_name_only_registered_operations_skills` | The two templates; four new role skills each; all registered `operations` definitions. |
| B3 | `test_the_doctor_warns_for_an_assigned_crew_post_without_a_template` | WARN naming `yeoman (yeoman)`. |
| B4 | `test_a_crew_member_commissioned_without_a_template_gains_it_keeping_its_pccs[yeoman\|training_officer]` | **The seam for BF-915.** PCCs-only commissioning → this change's template → re-commissioned once, PCCs unchanged (one at LEAD), four template skills at their floors, record names the post, no tool, stable afterwards. |

**Existing tests this makes stale, updated in M2:**
- `tests/test_ontology_skills.py::TestSkillsSchemaLoading::test_skills_yaml_loaded` (14 → 16 templates).
- `tests/test_bf906_crew_enrollment_boot.py::test_every_boot_wired_crew_member_is_onboarded_and_commissioned` (lines 185-197 pinned "the yeoman has no template").

**Readers that could trip, checked and unchanged; all are in the focused list:**
- PCC count 9: `test_skill_framework.py:180,193`.
- `ROLE_SKILL_TEMPLATES` has 3 per role: `test_ad566i_role_skill_template_expansion.py:48-53`.
- ACM SRP span and methods: `test_bf906_acm_commissioning.py:540` (15 methods unchanged; span about 456 ≤ 500).
- Pinned pass log line: `:1069`, unchanged.
- `CrewEnrollment` equality at defaults: `:1026`.
- `_a3_key` statement prefixes: `:1545-1553`, unchanged.
- AsyncMock connection: `test_database_abstraction.py:205` (the migration uses `await db.execute` and `await cursor.fetchall()`, so it works on an AsyncMock).
- Event-log pair freeze: `test_ad1195_eventlog_pair_freeze.py:106-111` (no new event-log write).
- Doctor neighbours: `test_bf906_doctor_check.py:349-350`, `test_bf901_s3_token_accounting_view.py:457`, `test_ad1328_s2a_startup_and_doctor.py:705`.
- Doctor import rule: `test_ad1137_doctor.py:1415-1437` (no `src` module imports `probos.doctor`).
- `skills.yaml` keys: `test_science_team.py:318-332`.
- `tool_count`: the roster counts grants (`routers/crew.py:135-139`), which do not change.

## 7. The contract

### 7.1 `src/probos/skill_framework.py` (M1)

Pair 1 of 2: the template skills and the one list of built-in definitions, after `ROLE_SKILL_TEMPLATES`.

SEARCH:
```python
        SkillDefinition(skill_id="experimental_design", name="Experimental Design", category=SkillCategory.ROLE, domain="science", prerequisites=["hypothesis_testing"], decay_rate_days=7, origin="role"),
    ],
}
```
REPLACE:
```python
        SkillDefinition(skill_id="experimental_design", name="Experimental Design", category=SkillCategory.ROLE, domain="science", prerequisites=["hypothesis_testing"], decay_rate_days=7, origin="role"),
    ],
}

# ── BF-917 (#1625): the skills the ontology role templates name ─────
# config/ontology/skills.yaml's role templates (keyed by post) name skill ids that
# neither the PCCs nor ROLE_SKILL_TEMPLATES (keyed by agent type, the legacy
# commissioning step) define. They are registered here and never acquired by
# ``commission_agent``. Each is a ROLE skill with no prerequisite (acquisition is
# unchanged), no preferred tool and no composite, the 14 days of decay a record
# with no definition already had (``check_decay``), and a domain a legacy role
# skill already has, so the AD-888 resolver's tag fallback asks nothing new.
ONTOLOGY_TEMPLATE_SKILLS: list[SkillDefinition] = [
    # Science (first officer, scout, data analyst, systems analyst, research specialist)
    SkillDefinition(skill_id="architecture_review", name="Architecture Review", category=SkillCategory.ROLE, description="Review system architecture, identify patterns and verify implementation paths.", domain="science", decay_rate_days=14, origin="role"),
    SkillDefinition(skill_id="pattern_recognition", name="Pattern Recognition", category=SkillCategory.ROLE, description="Recognise recurring structure across code, telemetry and reports.", domain="science", decay_rate_days=14, origin="role"),
    SkillDefinition(skill_id="trend_analysis", name="Trend Analysis", category=SkillCategory.ROLE, description="Detect and explain change over time in ship metrics and findings.", domain="science", decay_rate_days=14, origin="role"),
    SkillDefinition(skill_id="data_processing", name="Data Processing", category=SkillCategory.ROLE, description="Clean, transform and summarise data for analysis.", domain="science", decay_rate_days=14, origin="role"),
    SkillDefinition(skill_id="quantitative_analysis", name="Quantitative Analysis", category=SkillCategory.ROLE, description="Apply measurement and statistics to answer a question.", domain="science", decay_rate_days=14, origin="role"),
    SkillDefinition(skill_id="cross_department_synthesis", name="Cross-Department Synthesis", category=SkillCategory.ROLE, description="Combine findings from several departments into one picture.", domain="science", decay_rate_days=14, origin="role"),
    SkillDefinition(skill_id="emergence_analysis", name="Emergence Analysis", category=SkillCategory.ROLE, description="Identify behaviour that arises from interactions rather than from one component.", domain="science", decay_rate_days=14, origin="role"),
    SkillDefinition(skill_id="technical_writing", name="Technical Writing", category=SkillCategory.ROLE, description="Write clear, accurate technical reports and documentation.", domain="science", decay_rate_days=14, origin="role"),
    SkillDefinition(skill_id="evidence_analysis", name="Evidence Analysis", category=SkillCategory.ROLE, description="Weigh evidence and sources before drawing a conclusion.", domain="science", decay_rate_days=14, origin="role"),
    # Medical (counselor, chief medical officer, surgeon, pharmacist, pathologist)
    SkillDefinition(skill_id="wellness_assessment", name="Wellness Assessment", category=SkillCategory.ROLE, description="Assess a crew member's cognitive wellness from their signals.", domain="medical", decay_rate_days=14, origin="role"),
    SkillDefinition(skill_id="personality_analysis", name="Personality Analysis", category=SkillCategory.ROLE, description="Read personality traits and drift from a crew member's behaviour.", domain="medical", decay_rate_days=14, origin="role"),
    SkillDefinition(skill_id="crew_counseling", name="Crew Counseling", category=SkillCategory.ROLE, description="Counsel crew members through cognitive and social difficulty.", domain="medical", decay_rate_days=14, origin="role"),
    SkillDefinition(skill_id="diagnostic_analysis", name="Diagnostic Analysis", category=SkillCategory.ROLE, description="Trace a fault or symptom to its cause.", domain="medical", decay_rate_days=14, origin="role"),
    SkillDefinition(skill_id="health_monitoring", name="Health Monitoring", category=SkillCategory.ROLE, description="Watch system and crew health signals for change.", domain="medical", decay_rate_days=14, origin="role"),
    SkillDefinition(skill_id="treatment_planning", name="Treatment Planning", category=SkillCategory.ROLE, description="Plan a remedy for a diagnosed condition and its follow-up.", domain="medical", decay_rate_days=14, origin="role"),
    # Engineering (chief engineer, builder); distinct from the pathologist's medical system_analysis
    SkillDefinition(skill_id="systems_analysis", name="Systems Analysis", category=SkillCategory.ROLE, description="Analyse how the ship's systems fit together and where they fail.", domain="engineering", decay_rate_days=14, origin="role"),
    SkillDefinition(skill_id="architecture_implementation", name="Architecture Implementation", category=SkillCategory.ROLE, description="Turn an architecture into working, maintainable components.", domain="engineering", decay_rate_days=14, origin="role"),
    # Security (chief of security)
    SkillDefinition(skill_id="threat_assessment", name="Threat Assessment", category=SkillCategory.ROLE, description="Judge the likelihood and impact of a threat.", domain="security", decay_rate_days=14, origin="role"),
    SkillDefinition(skill_id="access_control", name="Access Control", category=SkillCategory.ROLE, description="Decide and verify who may use which capability.", domain="security", decay_rate_days=14, origin="role"),
    SkillDefinition(skill_id="vulnerability_analysis", name="Vulnerability Analysis", category=SkillCategory.ROLE, description="Find and rank weaknesses an attacker could use.", domain="security", decay_rate_days=14, origin="role"),
    # Operations (chief of operations)
    SkillDefinition(skill_id="workflow_optimization", name="Workflow Optimization", category=SkillCategory.ROLE, description="Improve how work flows between crew and systems.", domain="operations", decay_rate_days=14, origin="role"),
    SkillDefinition(skill_id="system_monitoring", name="System Monitoring", category=SkillCategory.ROLE, description="Track operational readiness and resource health.", domain="operations", decay_rate_days=14, origin="role"),
]


def builtin_skill_definitions() -> list[SkillDefinition]:
    """BF-917: every definition ``SkillRegistry.register_builtins`` registers, in order.

    The PCCs, the legacy role skills and the ontology template skills. The
    ``probos doctor`` role-template check reads the same list, so "registered"
    means one thing.
    """
    definitions = list(BUILTIN_PCCS)
    for role_skills in ROLE_SKILL_TEMPLATES.values():
        definitions.extend(role_skills)
    definitions.extend(ONTOLOGY_TEMPLATE_SKILLS)
    return definitions
```

Pair 2 of 2: `register_builtins` registers that list.

SEARCH:
```python
    async def register_builtins(self) -> None:
        """Register all built-in PCCs and role skill templates."""
        for pcc in BUILTIN_PCCS:
            await self.register_skill(pcc)
        for role_skills in ROLE_SKILL_TEMPLATES.values():
            for skill in role_skills:
                await self.register_skill(skill)
```
REPLACE:
```python
    async def register_builtins(self) -> None:
        """Register the built-in PCCs, the legacy role skills and the ontology template skills (BF-917)."""
        for defn in builtin_skill_definitions():
            await self.register_skill(defn)
```

### 7.2 `src/probos/acm.py` (M1)

Pair 1 of 6: the record carries its template fingerprint.

SEARCH:
```python
    initiated_by: str
    reason: str
    timestamp: float


# ── SQLite schema
```
REPLACE:
```python
    initiated_by: str
    reason: str
    timestamp: float
    template_fingerprint: str | None = None  # BF-917: the role template last applied; None before BF-917


# ── SQLite schema
```

Pair 2 of 6: the additive migration, a module function (the service is at its SRP method ceiling).

SEARCH:
```python
_COMMISSIONING_HISTORY_SQL = (
    "INSERT INTO lifecycle_transitions (agent_id, from_state, to_state, reason, initiated_by, timestamp) "
    "VALUES (?, ?, ?, ?, ?, ?)"
)
```
REPLACE:
```python
_COMMISSIONING_HISTORY_SQL = (
    "INSERT INTO lifecycle_transitions (agent_id, from_state, to_state, reason, initiated_by, timestamp) "
    "VALUES (?, ?, ?, ?, ?, ?)"
)


async def _add_template_fingerprint_column(db: DatabaseConnection) -> None:
    """BF-917: add ``commissioning_records.template_fingerprint`` where it is absent.

    A module function, as ``capability_request._migrate_payload_column`` is, to keep
    the service within its SRP budget. Idempotent. Existing rows read NULL: a
    commissioning recorded before BF-917, which the crew enroller re-commissions once.
    """
    cursor = await db.execute("PRAGMA table_info(commissioning_records)")
    columns = {row[1] for row in await cursor.fetchall()}
    if "template_fingerprint" not in columns:
        await db.execute("ALTER TABLE commissioning_records ADD COLUMN template_fingerprint TEXT")
```

Pair 3 of 6: `start` runs it before its commit.

SEARCH:
```python
        await self._db.execute("PRAGMA foreign_keys = ON")
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
```
REPLACE:
```python
        await self._db.execute("PRAGMA foreign_keys = ON")
        await self._db.executescript(_SCHEMA)
        await _add_template_fingerprint_column(self._db)
        await self._db.commit()
```

Pair 4 of 6: the reader selects the column.

SEARCH:
```python
            "initiated_by, reason, timestamp FROM commissioning_records WHERE agent_id = ?",
```
REPLACE:
```python
            "initiated_by, reason, timestamp, template_fingerprint FROM commissioning_records WHERE agent_id = ?",
```

Pair 5 of 6: the reader fills the field. This block starts mid-call.

SEARCH:
```python
            initiated_by=row[6], reason=row[7], timestamp=row[8],
        )
```
REPLACE:
```python
            initiated_by=row[6], reason=row[7], timestamp=row[8], template_fingerprint=row[9],
        )
```

Pair 6 of 6: `record_commissioning` stores the fingerprint, and gains the re-commission mode. This pair has three blocks, in file order.

SEARCH (6a):
```python
        initiated_by: str = "system",
        reason: str = "",
    ) -> bool:
        """BF-906: record an agent's commissioning once; False when one already exists.
```
REPLACE (6a):
```python
        initiated_by: str = "system",
        reason: str = "",
        template_fingerprint: str | None = None,
        recommission: bool = False,
    ) -> bool:
        """BF-906: record an agent's commissioning once; False when one already exists.
```

SEARCH (6b):
```python
        and any failure, cancellation included, rolls both back, so the next call
        records again.
        """
```
REPLACE (6b):
```python
        and any failure, cancellation included, rolls both back, so the next call
        records again.

        BF-917: the record keeps ``template_fingerprint``, the digest of the role
        template it was commissioned under. With ``recommission=True`` the existing
        record's ``role_template`` and ``template_fingerprint`` are replaced instead,
        in the same section and commit as a "re-commissioned" history row; False when
        there is no record or it already holds this fingerprint. The record's skills,
        tools, source and timestamp stay those of the first commissioning.
        """
```

SEARCH (6c):
```python
            try:
                cursor = await self._db.execute(
                    "INSERT OR IGNORE INTO commissioning_records (agent_id, agent_type, source, "
                    "role_template, skills_json, tools_json, initiated_by, reason, timestamp) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (agent_id, agent_type, source, role_template, json.dumps(list(skills)),
                     json.dumps(list(tools)), initiated_by, reason, now),
                )
                if cursor.rowcount == 0:
                    await self._db.commit()
                    return False
                state = (await self.get_lifecycle_state(agent_id)).value
                history_reason = (
                    f"{reason}: commissioned, role_template={role_template or 'none'}; "
```
REPLACE (6c):
```python
            try:
                if recommission:
                    cursor = await self._db.execute(
                        "UPDATE commissioning_records SET role_template = ?, template_fingerprint = ? "
                        "WHERE agent_id = ? AND template_fingerprint IS NOT ?",
                        (role_template, template_fingerprint, agent_id, template_fingerprint),
                    )
                else:
                    cursor = await self._db.execute(
                        "INSERT OR IGNORE INTO commissioning_records (agent_id, agent_type, source, "
                        "role_template, skills_json, tools_json, initiated_by, reason, timestamp, "
                        "template_fingerprint) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (agent_id, agent_type, source, role_template, json.dumps(list(skills)),
                         json.dumps(list(tools)), initiated_by, reason, now, template_fingerprint),
                    )
                if cursor.rowcount == 0:
                    await self._db.commit()
                    return False
                state = (await self.get_lifecycle_state(agent_id)).value
                action = "re-commissioned" if recommission else "commissioned"
                history_reason = (
                    f"{reason}: {action}, role_template={role_template or 'none'}; "
```

### 7.3 `src/probos/crew_enrollment.py` (M1)

Pair 1 of 8: the module docstring.

SEARCH:
```python
and memory are never touched. Commissioning's tool grants cover only tools the
AD-888 resolver already finds readable at ensign level.
"""
```
REPLACE:
```python
and memory are never touched. Commissioning's tool grants cover only tools the
AD-888 resolver already finds readable at ensign level.

BF-917 (#1625): the record keeps a fingerprint of the role template it was
commissioned under. When the template an agent resolves has changed since (a
record written before BF-917 has none, and gaining a template is a change), the
agent is re-commissioned once, keeping every record it holds and without the
Skills -> Tools step, so a re-commission grants no tool.
"""
```

Pair 2 of 8: the imports.

SEARCH:
```python
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
```
REPLACE:
```python
import asyncio
import hashlib
import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any
```

Pair 3 of 8: the reason text.

SEARCH:
```python
ENROLLMENT_REASON = "BF-906 (#1594) crew enrollment"
```
REPLACE:
```python
ENROLLMENT_REASON = "BF-906 (#1594) crew enrollment"
RECOMMISSION_REASON = "BF-917 (#1625) role template changed"
```

Pair 4 of 8: the result field.

SEARCH:
```python
    skills_granted: tuple[str, ...] = ()
    tools_granted: tuple[str, ...] = ()
```
REPLACE:
```python
    skills_granted: tuple[str, ...] = ()
    tools_granted: tuple[str, ...] = ()
    recommissioned: bool = False  # BF-917: a changed role template was applied to an existing record
```

Pair 5 of 8: the fingerprint and the re-commission context.

SEARCH:
```python
async def _has_skills(skill_service: Any, agent_id: str) -> bool:
```
REPLACE:
```python
def template_fingerprint(template: Any) -> str:
    """BF-917: a digest of what AD-889 commissioning reads from a role template.

    The post id and each required skill's id and floor, in a canonical order: the
    same template always gives the same digest, and any change to what the chain
    would acquire gives a new one. Optional skills are left out because the chain
    reads only ``required_skills``: an optional id that is a PCC or a legacy role
    skill is still acquired, by the chain's base step, but a change to the optional
    list changes nothing the chain does. No template has a digest of its own, so
    gaining or losing a template is a change too.
    """
    if template is None:
        payload: dict[str, Any] = {"post_id": None, "required": []}
    else:
        payload = {
            "post_id": template.post_id,
            "required": sorted([r.skill_id, r.min_proficiency] for r in template.required_skills),
        }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class _RecommissionContext:
    """BF-917: the services a template re-commission may use.

    AD-889's chain reads its subsystems from this object by name. It has the skill
    service and the ontology and no ``tool_registry``, ``tool_permission_store`` or
    ``skill_registry``, so the chain's Skills -> Tools step does not run and a
    re-commission grants no tool. Whether that step should grant tools at all is
    the Captain's open question on #1625.
    """

    skill_service: Any
    ontology: Any


async def _has_skills(skill_service: Any, agent_id: str) -> bool:
```

Pair 6a (A1): the enrollment lock, at the end of `__init__`.

SEARCH:
```python
        self._commission_context = commission_context
        self._boot_started_at = boot_started_at
```
REPLACE:
```python
        self._commission_context = commission_context
        self._boot_started_at = boot_started_at
        # BF-917 A1: serializes ``enroll`` (see there). One lock per enroller, like ACM's
        # ``_write_lock``; startup builds one enroller. It is always taken outside ACM's lock.
        self._enroll_lock = asyncio.Lock()
```

Pair 6 of 8: `enroll` routes an existing record to the trigger.

SEARCH:
```python
        onboarded = await self._onboard_if_unrecorded(agent, source=source)
        if await self._acm.get_commissioning_record(agent.id) is not None:
            return CrewEnrollment(
                agent_id=agent.id, agent_type=agent.agent_type, source=source,
                onboarded=onboarded, commissioned=False,
            )
        return await self._commission(agent, source=source, onboarded=onboarded)
```
REPLACE:
```python
        # BF-917 A1: one enrollment at a time. The chain snapshots the profile and then
        # writes each skill it found missing as a fresh record, so two overlapping
        # enrollments of one agent would both acquire it, and the later write would reset
        # a record the earlier one had already advanced. Under the lock the second reads
        # the record the first wrote and finds nothing to do.
        async with self._enroll_lock:
            onboarded = await self._onboard_if_unrecorded(agent, source=source)
            record = await self._acm.get_commissioning_record(agent.id)
            if record is not None:
                return await self._recommission_if_template_changed(
                    agent, record.template_fingerprint, source=source, onboarded=onboarded,
                )
            return await self._commission(agent, source=source, onboarded=onboarded)
```

Pair 7 of 8: the first commissioning records the fingerprint. This block starts mid-call.

SEARCH:
```python
            role_template=role_template, skills=skills, tools=tools,
            initiated_by=ENROLLMENT_INITIATED_BY, reason=reason,
        )
        if recorded:
```
REPLACE:
```python
            role_template=role_template, skills=skills, tools=tools,
            initiated_by=ENROLLMENT_INITIATED_BY, reason=reason,
            template_fingerprint=template_fingerprint(template),
        )
        if recorded:
```

Pair 8 of 8: the trigger.

SEARCH:
```python
    async def _log_commissioning(
        self, agent: Any, *, source: str, role_template: str | None,
```
REPLACE:
```python
    async def _recommission_if_template_changed(
        self, agent: Any, recorded_fingerprint: str | None, *, source: str, onboarded: bool,
    ) -> CrewEnrollment:
        """BF-917: re-run commissioning once when the agent's role template has changed.

        The record's fingerprint (None on a record written before BF-917) is compared
        with the template the ontology resolves now. When they differ, the chain runs
        with ``preserve_existing=True``, so every record the agent holds keeps its
        proficiency, exercise count and history and only skills it lacks are acquired,
        on a context without the tool services, so no tool is granted. The new
        fingerprint is recorded only when the chain returned, read a profile and left
        the agent holding every PCC (the rule ``_commission`` keeps); otherwise nothing
        is recorded and the next enrollment retries. A required skill the chain skips
        because its prerequisite is unmet (AD-889's expected case) does not block the
        record. ``enroll`` holds the enroller's lock around this, so an overlapping
        enrollment of the same agent waits and then finds the fingerprint equal.
        A decommissioned agent is left alone.
        """
        agent_id, agent_type = agent.id, agent.agent_type
        unchanged = CrewEnrollment(
            agent_id=agent_id, agent_type=agent_type, source=source,
            onboarded=onboarded, commissioned=False,
        )
        template = (
            self._ontology.get_role_template_for_agent(agent_type)
            if self._ontology is not None else None
        )
        fingerprint = template_fingerprint(template)
        if recorded_fingerprint == fingerprint:
            return unchanged
        if await self._acm.get_lifecycle_state(agent_id) is LifecycleState.DECOMMISSIONED:
            return unchanged
        if self._skill_service is None:
            logger.error(
                "BF-917: no skill service; the changed role template of %s (%s) is not "
                "applied, and the next boot retries", agent_id, agent_type,
            )
            return unchanged
        before = await self._skill_ids(agent_id)
        if before is None:
            return unchanged
        context = _RecommissionContext(skill_service=self._skill_service, ontology=self._ontology)
        try:
            summary = await self._acm.commission(
                agent_id, agent_type, context,
                preserve_existing=True, grant_issued_by=ENROLLMENT_INITIATED_BY,
            )
        except Exception:
            logger.error(
                "BF-917: re-commissioning failed for %s (%s); the template change is not "
                "recorded, so the next boot retries", agent_id, agent_type, exc_info=True,
            )
            return unchanged
        if not summary.get("skills_acquired"):
            logger.error(
                "BF-917: re-commissioning of %s (%s) read no skill profile; the template "
                "change is not recorded, so the next boot retries", agent_id, agent_type,
            )
            return unchanged
        missing_pccs = [pcc.skill_id for pcc in BUILTIN_PCCS if pcc.skill_id not in summary["skills_acquired"]]
        if missing_pccs:
            # BF-917 A1: the rule a first commissioning keeps (BF-906 A3). The chain logs a
            # failed base step at DEBUG and still returns the profile it read, so a
            # re-commission that left a PCC missing is not recorded, and the next boot retries.
            logger.error(
                "BF-917: re-commissioning left %s (%s) without the PCCs %s; the template change "
                "is not recorded, so the next boot retries", agent_id, agent_type, ", ".join(missing_pccs),
            )
            return unchanged
        held_before = set(before)
        skills = tuple(s for s in summary["skills_acquired"] if s not in held_before)
        role_template = template.post_id if template is not None else None
        recorded = await self._acm.record_commissioning(
            agent_id=agent_id, agent_type=agent_type, source=source,
            role_template=role_template, skills=skills, tools=(),
            initiated_by=ENROLLMENT_INITIATED_BY, reason=f"{RECOMMISSION_REASON}, source={source}",
            template_fingerprint=fingerprint, recommission=True,
        )
        if recorded:
            logger.info(
                "BF-917: re-commissioned %s (%s) under role template %s; acquired %s",
                agent_id, agent_type, role_template or "none", ", ".join(skills) or "nothing",
            )
        return replace(
            unchanged, recommissioned=recorded, role_template=role_template, skills_granted=skills,
        )

    async def _log_commissioning(
        self, agent: Any, *, source: str, role_template: str | None,
```

### 7.4 `src/probos/storage_declarations.py` (M1)

SEARCH:
```python
            "per state change and one per BF-906 commissioning, kept as the agent's record. Growth is bounded by "
            "crew size and HR actions. `probos reset` (tier 2, Recommissioning) deletes the whole file."
```
REPLACE:
```python
            "per state change, one per BF-906 commissioning and one per BF-917 role-template re-commissioning, "
            "kept as the agent's record. Growth is bounded by crew size, HR actions and role-template changes. "
            "`probos reset` (tier 2, Recommissioning) deletes the whole file."
```

### 7.5 New file: `src/probos/role_template_audit.py` (M1)

```python
"""BF-917 (#1625): the role templates audited against the skill catalog.

Pure functions over what ``OntologyLoader`` loads. ``probos doctor``'s
``role_templates`` check reports what they find, and the tests run them over the
shipped ``config/ontology``, so a template that names a skill no definition
registers fails CI before a vessel boots it. They read; they never write.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def unregistered_template_skills(
    role_templates: Mapping[str, Any], registered: frozenset[str],
) -> tuple[tuple[str, str], ...]:
    """Each ``(post_id, skill_id)`` a template requires or offers that no registered definition has, sorted."""
    missing = {
        (post_id, req.skill_id)
        for post_id, template in role_templates.items()
        for req in [*template.required_skills, *template.optional_skills]
        if req.skill_id not in registered
    }
    return tuple(sorted(missing))
```

### 7.6 New file: `src/probos/doctor/checks/role_template_check.py` (M1)

```python
"""BF-917 (#1625): every skill a role template names is a registered skill definition.

Reads ``config/ontology`` through the real ``OntologyLoader`` with no data
directory, so it creates and writes nothing (the loader persists an instance id
only under a data directory). Each finding is a WARN naming the post, never a FAIL,
and the check repairs nothing. An ontology the loader cannot read (a template entry
without ``min_proficiency``, say) raises instead, which the doctor runner reports as
FAIL, as it does for any check that raises. "Registered" is what ``SkillRegistry.register_builtins``
registers at boot (``builtin_skill_definitions``). The CI tests run the same audit
over the shipped ontology, so this check finds an operator's local edit.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check

# src/probos/doctor/checks/ -> the repository root, as startup/communication.py finds it.
_ONTOLOGY_DIR = Path(__file__).resolve().parents[4] / "config" / "ontology"
_REMEDIATION = (
    "Correct the skill id in config/ontology/skills.yaml, or register the skill in "
    "ONTOLOGY_TEMPLATE_SKILLS (probos/skill_framework.py), then restart ProbOS."
)


@dataclass(frozen=True)
class _RoleTemplateCheck:
    name: str = "role_templates"
    ontology_dir: Path = _ONTOLOGY_DIR

    async def run(self, ctx: DoctorContext) -> CheckResult:
        if not self.ontology_dir.is_dir():
            return CheckResult(CheckOutcome.OK, f"Role templates: no ontology at {self.ontology_dir}")
        from probos.ontology.loader import OntologyLoader
        from probos.role_template_audit import unregistered_template_skills
        from probos.skill_framework import builtin_skill_definitions

        loader = OntologyLoader(self.ontology_dir)
        await loader.initialize()
        registered = frozenset(d.skill_id for d in builtin_skill_definitions())
        findings = [
            f"{post}: template skill {skill} is not a registered skill definition"
            for post, skill in unregistered_template_skills(loader.role_templates, registered)
        ]
        if not findings:
            return CheckResult(
                CheckOutcome.OK,
                f"Role templates: {len(loader.role_templates)} templates, every template skill registered",
            )
        return CheckResult(
            CheckOutcome.WARN,
            f"Role templates: {len(findings)} problem(s) in config/ontology",
            _REMEDIATION,
            "\n".join(findings),
        )


register_check(_RoleTemplateCheck())
```

### 7.7 `src/probos/doctor/checks/__init__.py` (M1)

SEARCH:
```python
    token_accounting_check,
    security_check,
```
REPLACE:
```python
    token_accounting_check,
    role_template_check,  # BF-917/BF-915: after token_accounting, which stays next to crew_enrollment
    security_check,
```

### 7.8 New file: `tests/fixtures/crew_template_world.py` (M1)

```python
"""BF-917 (#1625) / BF-915 (#1623): a crew-enrollment world on real stores and a copy of the shipped ontology.

Real ``SkillRegistry`` + ``AgentSkillService``, ``ToolPermissionStore``, ``ToolRegistry`` and
``AgentCapitalService`` on SQLite files under ``tmp_path``; the ontology is the real
``VesselOntologyService`` over a copy of ``config/ontology`` that a test may edit, and each
``boot_enroller`` call builds what one boot builds. The only stand-in is the wired agent.
"""

from __future__ import annotations

import contextlib
import json
import shutil
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace as _Namespace
from typing import Any

from probos.acm import AgentCapitalService
from probos.crew_enrollment import CrewEnrollmentService
from probos.ontology import VesselOntologyService
from probos.skill_framework import AgentSkillService, SkillRegistry
from probos.tools.adapters import DirectServiceAdapter
from probos.tools.permissions import ToolPermissionStore
from probos.tools.registry import ToolRegistry

ONTOLOGY_DIR = Path(__file__).resolve().parents[2] / "config" / "ontology"
PROBE_TOOL = "engineering_probe"


async def _noop(**kwargs: Any) -> None:
    return None


@dataclass(frozen=True)
class CrewAgent:
    """The attributes crew enrollment reads from a wired agent."""

    id: str
    agent_type: str
    pool: str = "bf917_pool"
    sovereign_id: str = ""


@dataclass(frozen=True)
class CrewWorld:
    tmp_path: Path
    ontology_dir: Path
    skill_registry: SkillRegistry
    skill_service: AgentSkillService
    permission_store: ToolPermissionStore
    tool_registry: ToolRegistry
    acm: AgentCapitalService


@contextlib.asynccontextmanager
async def crew_world(tmp_path: Path) -> AsyncIterator[CrewWorld]:
    """The stores, started and stopped; the tool registry holds one readable tool tagged ``engineering``."""
    ontology_dir = tmp_path / "ontology"
    shutil.copytree(ONTOLOGY_DIR, ontology_dir)
    skills_db = str(tmp_path / "skills.db")
    skill_registry = SkillRegistry(db_path=skills_db)
    skill_service = AgentSkillService(db_path=skills_db, registry=skill_registry)
    permission_store = ToolPermissionStore(db_path=str(tmp_path / "tool_permissions.db"))
    acm = AgentCapitalService(data_dir=tmp_path / "acm")
    await skill_registry.start()
    await skill_registry.register_builtins()
    await skill_service.start()
    await permission_store.start()
    await acm.start()
    tool_registry = ToolRegistry()
    tool_registry.set_permission_store(permission_store)
    tool_registry.register(
        DirectServiceAdapter(tool_id=PROBE_TOOL, name="Engineering probe", description="BF-917 test tool", handler=_noop),
        provider="bf917", tags=["engineering"],
    )
    try:
        yield CrewWorld(
            tmp_path=tmp_path, ontology_dir=ontology_dir, skill_registry=skill_registry,
            skill_service=skill_service, permission_store=permission_store,
            tool_registry=tool_registry, acm=acm,
        )
    finally:
        await acm.stop()
        await permission_store.stop()
        await skill_service.stop()
        await skill_registry.stop()


async def boot_enroller(world: CrewWorld) -> tuple[CrewEnrollmentService, VesselOntologyService]:
    """What one boot builds over the world's stores: the ontology from its copy, and an enroller over it."""
    ontology = VesselOntologyService(world.ontology_dir, data_dir=world.tmp_path / "ontology_data")
    await ontology.initialize()
    context = _Namespace(
        skill_service=world.skill_service, skill_registry=world.skill_registry,
        tool_registry=world.tool_registry, tool_permission_store=world.permission_store,
        ontology=ontology,
    )
    enroller = CrewEnrollmentService(
        acm=world.acm, ontology=ontology, skill_service=world.skill_service, identity_registry=None,
        event_log=None, commission_context=context, boot_started_at=0.0,
    )
    return enroller, ontology


def edit_skills_yaml(world: CrewWorld, old: str, new: str) -> None:
    """Replace the one occurrence of ``old`` in the world's copy of skills.yaml."""
    path = world.ontology_dir / "skills.yaml"
    text = path.read_text(encoding="utf-8")
    assert text.count(old) == 1, f"premise: {old!r} occurs once in the copied skills.yaml"
    path.write_text(text.replace(old, new), encoding="utf-8")


async def skill_records(skill_service: AgentSkillService, agent_id: str) -> dict[str, tuple[Any, ...]]:
    """Each record's proficiency, exercise count, timestamps, source, suspension and history."""
    return {
        r.skill_id: (
            r.proficiency, r.exercise_count, r.acquired_at, r.last_exercised,
            r.acquisition_source, r.suspended, json.dumps(r.assessment_history, sort_keys=True),
        )
        for r in await skill_service.get_all_records(agent_id)
    }


def recommission_rows(before: list[Any], after: list[Any]) -> list[Any]:
    """The re-commission history rows ``after`` adds to ``before``, picked by predicate."""
    return [
        t for t in after
        if t not in before and t.from_state == t.to_state and "re-commissioned" in t.reason
    ]
```

### 7.9 New file: `tests/test_bf917_template_skills_and_recommission.py` (M1)

```python
"""BF-917 (#1625): the role templates' skills are registered, and a changed role template re-commissions a crew member once without loss.

Real objects throughout: the real ``OntologyLoader``/``VesselOntologyService`` over the shipped
``config/ontology`` or a copy a test edits; the real ``SkillRegistry``, ``AgentSkillService``,
``AgentCapitalService``, ``ToolPermissionStore`` and ``ToolRegistry`` on SQLite files under
``tmp_path``; and the real AD-889 chain reached through ``CrewEnrollmentService.enroll``. The only
stand-ins are the wired agent, E4's failing ``commission``, E5's failing base step and E6's gate
around the real ``acquire_skill``. History rows are picked by predicate. Only E6 waits on a clock:
a bounded wait for a second caller that, under the enroller's lock, never arrives.

- G1-G5 the registration (guard 1: no tool; guard 2: no faster decay, no changed acquisition)
- A1-A2 ACM: the fingerprint column and the re-commission write
- E1-E6 the trigger, end to end (E5: a missing PCC; E6: overlapping enrollments)
- D1-D3 the doctor's ``role_templates`` check
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from probos.acm import AgentCapitalService
from probos.crew_enrollment import template_fingerprint
from probos.doctor.checks.role_template_check import _RoleTemplateCheck
from probos.doctor.protocol import CheckOutcome, DoctorContext
from probos.ontology.loader import OntologyLoader
from probos.role_template_audit import unregistered_template_skills
from probos.skill_framework import (
    BUILTIN_PCCS,
    ONTOLOGY_TEMPLATE_SKILLS,
    ROLE_SKILL_TEMPLATES,
    AgentSkillService,
    ProficiencyLevel,
    SkillCategory,
    SkillRegistry,
    builtin_skill_definitions,
)
from probos.tools.adapters import DirectServiceAdapter
from probos.tools.registry import ToolRegistry
from probos.tools.skill_tool_resolver import resolve_tools_for_skill
from tests.fixtures.crew_template_world import (
    ONTOLOGY_DIR,
    PROBE_TOOL,
    CrewAgent,
    boot_enroller,
    crew_world,
    edit_skills_yaml,
    recommission_rows,
    skill_records,
)

# The 22 ids #1625 found unregistered (skills.yaml:44-261 on 80456da2).
_BF917_IDS = frozenset({
    "architecture_review", "pattern_recognition", "wellness_assessment", "personality_analysis",
    "crew_counseling", "systems_analysis", "architecture_implementation", "trend_analysis",
    "data_processing", "quantitative_analysis", "cross_department_synthesis", "emergence_analysis",
    "technical_writing", "evidence_analysis", "diagnostic_analysis", "health_monitoring",
    "treatment_planning", "threat_assessment", "access_control", "vulnerability_analysis",
    "workflow_optimization", "system_monitoring",
})
_VULNERABILITY = "      - skill_id: vulnerability_analysis\n        min_proficiency: 4\n"
_ADD_CODE_REVIEW = _VULNERABILITY + "      - skill_id: code_review\n        min_proficiency: 3\n"
_DAY = 86400.0
# E6: how long the first caller waits for a second. Without the enroller's lock the second arrives within
# milliseconds; with it, it never does, so the passing run pays this wait once.
_SECOND_CALLER_WAIT = 2.0


async def _noop(**kwargs: Any) -> None:
    return None


def _legacy_role_skills() -> list[Any]:
    return [defn for skills in ROLE_SKILL_TEMPLATES.values() for defn in skills]


async def _shipped_loader() -> OntologyLoader:
    loader = OntologyLoader(ONTOLOGY_DIR)
    await loader.initialize()
    return loader


# --- G1 to G5: the registration ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_role_template_skill_is_a_registered_definition(tmp_path: Path) -> None:
    """G1: every id a shipped template requires or offers is registered at boot; BF-917's ids are 39 references to 22."""
    loader = await _shipped_loader()
    assert len(loader.role_templates) >= 14  # premise: the shipped templates loaded
    skill_registry = SkillRegistry(db_path=str(tmp_path / "skills.db"))
    await skill_registry.start()
    try:
        await skill_registry.register_builtins()
        named = [
            (post_id, req.skill_id)
            for post_id, template in loader.role_templates.items()
            for req in [*template.required_skills, *template.optional_skills]
        ]
        assert [pair for pair in named if skill_registry.get_skill(pair[1]) is None] == []
        registered = frozenset(d.skill_id for d in builtin_skill_definitions())
        assert unregistered_template_skills(loader.role_templates, registered) == ()
        bf917_refs = [
            req.skill_id for template in loader.role_templates.values()
            for req in template.required_skills if req.skill_id in _BF917_IDS
        ]
        assert (len(bf917_refs), len(set(bf917_refs))) == (39, 22)
        assert {d.skill_id for d in ONTOLOGY_TEMPLATE_SKILLS} <= {skill for _, skill in named}
    finally:
        await skill_registry.stop()


def test_the_template_skills_change_no_acquisition_decay_or_tool_route() -> None:
    """G2 (guards 1 and 2): role skills with no prerequisite, preferred tool or composite; 14 days; a legacy domain."""
    ids = [d.skill_id for d in builtin_skill_definitions()]
    assert len(ids) == len(set(ids))
    assert _BF917_IDS <= {d.skill_id for d in ONTOLOGY_TEMPLATE_SKILLS}
    legacy_domains = {d.domain for d in _legacy_role_skills()}
    assert legacy_domains == {"security", "engineering", "operations", "medical", "science"}  # premise
    for defn in ONTOLOGY_TEMPLATE_SKILLS:
        assert (defn.category, defn.origin) == (SkillCategory.ROLE, "role"), defn.skill_id
        assert defn.prerequisites == [] and defn.preferred_tools == [], defn.skill_id
        assert defn.composite_skill_ids == [] and defn.synergy_partners == [], defn.skill_id
        assert defn.decay_rate_days == 14, defn.skill_id  # check_decay's value for a record with no definition
        assert defn.domain in legacy_domains, defn.skill_id
        assert defn.name and defn.description, defn.skill_id


@pytest.mark.asyncio
async def test_the_resolver_gives_a_template_skill_no_tool_its_domain_does_not_already_get() -> None:
    """G3 (guard 1): startup's ontology-seeded tools give no template skill a tool, and against any registry a
    template skill resolves exactly what a legacy role skill of its domain resolves."""
    loader = await _shipped_loader()
    seeded = ToolRegistry()
    for capability in loader.tool_capabilities:  # startup/communication.py's seeding, tags and all
        seeded.register(
            DirectServiceAdapter(tool_id=capability.id, name=capability.name, description=capability.description, handler=_noop),
            provider=capability.provider, tags=[capability.id, capability.provider],
        )
    assert seeded.list_tools()  # premise: there are readable tools to find
    legacy_by_domain = {d.domain: d for d in _legacy_role_skills()}
    probe = ToolRegistry()
    for domain in sorted(legacy_by_domain):
        probe.register(
            DirectServiceAdapter(tool_id=f"probe_{domain}", name=domain, description="BF-917 probe", handler=_noop),
            provider="bf917", tags=[domain],
        )
    for defn in ONTOLOGY_TEMPLATE_SKILLS:
        assert resolve_tools_for_skill(defn, agent_id="crew-g3", tool_registry=seeded) == [], defn.skill_id
        resolved = [r.tool_id for r in resolve_tools_for_skill(defn, agent_id="crew-g3", tool_registry=probe)]
        legacy = legacy_by_domain[defn.domain]
        assert resolved == [r.tool_id for r in resolve_tools_for_skill(legacy, agent_id="crew-g3", tool_registry=probe)]
        assert resolved == [f"probe_{defn.domain}"], defn.skill_id  # the probe is live: the domain is the question


@pytest.mark.asyncio
async def test_a_formerly_undefined_record_decays_exactly_as_before(tmp_path: Path) -> None:
    """G4 (guard 2): the same records decay identically with and without the template definitions."""
    bare_registry = SkillRegistry(db_path=str(tmp_path / "bare.db"))
    full_registry = SkillRegistry(db_path=str(tmp_path / "full.db"))
    await bare_registry.start()
    await full_registry.start()
    for defn in [*BUILTIN_PCCS, *_legacy_role_skills()]:
        await bare_registry.register_skill(defn)
    await full_registry.register_builtins()
    bare_service = AgentSkillService(db_path=str(tmp_path / "bare.db"), registry=bare_registry)
    full_service = AgentSkillService(db_path=str(tmp_path / "full.db"), registry=full_registry)
    await bare_service.start()
    await full_service.start()
    try:
        ids = [d.skill_id for d in ONTOLOGY_TEMPLATE_SKILLS]
        for skill_id in ids:
            await bare_service.acquire_skill("crew-g4", skill_id, source="commission", proficiency=ProficiencyLevel.ADVISE)
            await full_service.acquire_skill("crew-g4", skill_id, source="commission", proficiency=ProficiencyLevel.ADVISE)
        records = await full_service.get_all_records("crew-g4")
        base = max(r.last_exercised for r in records)
        assert await bare_service.check_decay(now=base + 13 * _DAY) == []
        assert await full_service.check_decay(now=base + 13 * _DAY) == []
        await bare_service.check_decay(now=base + 20 * _DAY)
        await full_service.check_decay(now=base + 20 * _DAY)
        bare = {r.skill_id: r.proficiency for r in await bare_service.get_all_records("crew-g4")}
        full = {r.skill_id: r.proficiency for r in await full_service.get_all_records("crew-g4")}
        assert full == bare == {skill_id: ProficiencyLevel.ENABLE for skill_id in ids}
    finally:
        await bare_service.stop()
        await full_service.stop()
        await bare_registry.stop()
        await full_registry.stop()


@pytest.mark.asyncio
async def test_a_record_under_a_newly_registered_id_becomes_a_role_skill_unchanged(tmp_path: Path) -> None:
    """G5: an orphan record (above its floor, exercised) is a role skill after registration, every field unchanged."""
    db = str(tmp_path / "skills.db")
    before_registry = SkillRegistry(db_path=db)
    await before_registry.start()
    for defn in [*BUILTIN_PCCS, *_legacy_role_skills()]:
        await before_registry.register_skill(defn)
    before_service = AgentSkillService(db_path=db, registry=before_registry)
    await before_service.start()
    await before_service.acquire_skill("crew-g5", "threat_assessment", source="commission", proficiency=ProficiencyLevel.ADVISE)
    await before_service.update_proficiency("crew-g5", "threat_assessment", ProficiencyLevel.LEAD, source="bf917-test")
    await before_service.record_exercise("crew-g5", "threat_assessment")
    orphan = await before_service.get_profile("crew-g5")
    assert ([r.skill_id for r in orphan.acquired_skills], orphan.role_skills) == (["threat_assessment"], [])  # premise
    held = await skill_records(before_service, "crew-g5")
    await before_service.stop()
    await before_registry.stop()

    after_registry = SkillRegistry(db_path=db)
    await after_registry.start()
    await after_registry.register_builtins()
    after_service = AgentSkillService(db_path=db, registry=after_registry)
    await after_service.start()
    try:
        profile = await after_service.get_profile("crew-g5")
        assert ([r.skill_id for r in profile.role_skills], profile.acquired_skills) == (["threat_assessment"], [])
        assert await skill_records(after_service, "crew-g5") == held
    finally:
        await after_service.stop()
        await after_registry.stop()


# --- A1, A2: ACM ---------------------------------------------------------------------------------

# BF-906's commissioning_records exactly as it shipped: the live vessel's shape.
_BF906_TABLE = """
CREATE TABLE commissioning_records (
    agent_id TEXT PRIMARY KEY,
    agent_type TEXT NOT NULL,
    source TEXT NOT NULL,
    role_template TEXT,
    skills_json TEXT NOT NULL DEFAULT '[]',
    tools_json TEXT NOT NULL DEFAULT '[]',
    initiated_by TEXT NOT NULL DEFAULT 'system',
    reason TEXT NOT NULL DEFAULT '',
    timestamp REAL NOT NULL
);
INSERT INTO commissioning_records (agent_id, agent_type, source, role_template, skills_json, tools_json,
    initiated_by, reason, timestamp)
VALUES ('crew-a1', 'scout', 'backfill', 'scout_officer', '["communication"]', '[]', 'system', 'BF-906', 5.0);
"""


@pytest.mark.asyncio
async def test_a_bf906_acm_db_gains_the_fingerprint_column_and_keeps_its_rows(tmp_path: Path) -> None:
    """A1: the migration adds the column once, keeps the row, and reads its fingerprint as None."""
    with contextlib.closing(sqlite3.connect(tmp_path / "acm.db")) as conn:
        conn.executescript(_BF906_TABLE)
        conn.commit()
    for _ in range(2):  # the second start is a later boot: idempotent
        acm = AgentCapitalService(data_dir=tmp_path)
        await acm.start()
        try:
            record = await acm.get_commissioning_record("crew-a1")
            assert record is not None
            assert (record.agent_type, record.source, record.role_template, record.skills, record.timestamp) == (
                "scout", "backfill", "scout_officer", ("communication",), 5.0,
            )
            assert record.template_fingerprint is None
        finally:
            await acm.stop()
    with contextlib.closing(sqlite3.connect(tmp_path / "acm.db")) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(commissioning_records)")]
    assert columns.count("template_fingerprint") == 1


@pytest.mark.asyncio
async def test_a_recommission_replaces_only_the_template_and_writes_one_history_row(tmp_path: Path) -> None:
    """A2: recommission=True is False without a record or with the same fingerprint, and otherwise replaces only
    the role template and fingerprint, with one re-commission history row."""
    acm = AgentCapitalService(data_dir=tmp_path)
    await acm.start()
    try:
        assert await acm.record_commissioning(
            agent_id="crew-a2", agent_type="scout", source="join", role_template=None, skills=(), tools=(),
            reason="BF-917 test", template_fingerprint="fp-1", recommission=True,
        ) is False
        assert await acm.get_transition_history("crew-a2") == []
        assert await acm.record_commissioning(
            agent_id="crew-a2", agent_type="scout", source="join", role_template=None,
            skills=("communication",), tools=(), reason="BF-917 test", template_fingerprint="fp-1",
        ) is True
        first = await acm.get_commissioning_record("crew-a2")
        history = await acm.get_transition_history("crew-a2")
        assert first is not None and first.template_fingerprint == "fp-1"
        assert await acm.record_commissioning(
            agent_id="crew-a2", agent_type="scout", source="backfill", role_template="scout_officer", skills=(),
            tools=(), reason="BF-917 test", template_fingerprint="fp-1", recommission=True,
        ) is False
        assert await acm.record_commissioning(
            agent_id="crew-a2", agent_type="scout", source="backfill", role_template="scout_officer",
            skills=("pattern_recognition",), tools=(), reason="BF-917 test", template_fingerprint="fp-2",
            recommission=True,
        ) is True
        second = await acm.get_commissioning_record("crew-a2")
        assert second is not None
        assert (second.role_template, second.template_fingerprint) == ("scout_officer", "fp-2")
        assert (second.source, second.skills, second.tools, second.timestamp) == (
            first.source, first.skills, first.tools, first.timestamp,
        )
        rows = recommission_rows(history, await acm.get_transition_history("crew-a2"))
        assert len(rows) == 1
        assert "role_template=scout_officer" in rows[0].reason and "pattern_recognition" in rows[0].reason
    finally:
        await acm.stop()


# --- E1 to E4: the trigger -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_changed_role_template_is_applied_once_keeping_every_record_and_granting_no_tool(tmp_path: Path) -> None:
    """E1 (the seam): template v1 -> commissioned; v2 adds a skill -> the next boot re-commissions once, keeps every
    record (one above its floor), grants no tool; the same template again -> nothing."""
    async with crew_world(tmp_path) as world:
        agent = CrewAgent("security-e1", "security_officer")
        enroller, ontology = await boot_enroller(world)
        first = await enroller.enroll(agent, source="birth")
        assert first is not None and first.commissioned is True
        record = await world.acm.get_commissioning_record(agent.id)
        assert record is not None
        assert record.template_fingerprint == template_fingerprint(ontology.get_role_template_for_agent("security_officer"))
        steady = await enroller.enroll(agent, source="backfill")
        assert steady is not None and (steady.commissioned, steady.recommissioned) == (False, False)

        await world.skill_service.update_proficiency(agent.id, "threat_assessment", ProficiencyLevel.LEAD, source="bf917-test")
        await world.skill_service.record_exercise(agent.id, "communication")
        held = await skill_records(world.skill_service, agent.id)
        assert held["threat_assessment"][0] == ProficiencyLevel.LEAD  # premise: above the template's floor of 5
        assert "code_review" not in held
        history = await world.acm.get_transition_history(agent.id)
        assert await world.permission_store.list_grants(active_only=True) == []

        edit_skills_yaml(world, _VULNERABILITY, _ADD_CODE_REVIEW)
        enroller, ontology = await boot_enroller(world)  # the next boot reads the changed template
        again = await enroller.enroll(agent, source="backfill")

        assert again is not None and (again.commissioned, again.recommissioned) == (False, True)
        assert (again.role_template, again.skills_granted, again.tools_granted) == ("chief_security", ("code_review",), ())
        after = await skill_records(world.skill_service, agent.id)
        assert {skill: after[skill] for skill in held} == held
        assert set(after) - set(held) == {"code_review"}
        assert after["code_review"][0] == ProficiencyLevel.APPLY  # the new skill at the template's floor
        changed = await world.acm.get_commissioning_record(agent.id)
        assert changed is not None and changed.role_template == "chief_security"
        assert changed.template_fingerprint == template_fingerprint(ontology.get_role_template_for_agent("security_officer"))
        assert changed.template_fingerprint != record.template_fingerprint
        assert (changed.agent_type, changed.source, changed.skills, changed.tools, changed.timestamp) == (
            record.agent_type, record.source, record.skills, record.tools, record.timestamp,
        )
        rows = recommission_rows(history, await world.acm.get_transition_history(agent.id))
        assert len(rows) == 1
        assert "BF-917" in rows[0].reason and "code_review" in rows[0].reason
        # A full AD-889 chain would grant the probe tool for code_review; the re-commission grants nothing.
        code_review = world.skill_registry.get_skill("code_review")
        assert code_review is not None
        resolvable = resolve_tools_for_skill(code_review, agent_id=agent.id, tool_registry=world.tool_registry)
        assert [r.tool_id for r in resolvable] == [PROBE_TOOL]
        assert await world.permission_store.list_grants(active_only=True) == []

        settled = (after, changed, await world.acm.get_transition_history(agent.id))
        third = await enroller.enroll(agent, source="backfill")
        assert third is not None and third.recommissioned is False
        assert (
            await skill_records(world.skill_service, agent.id),
            await world.acm.get_commissioning_record(agent.id),
            await world.acm.get_transition_history(agent.id),
        ) == settled


@pytest.mark.asyncio
async def test_a_record_written_before_bf917_is_recommissioned_once_and_acquires_nothing(tmp_path: Path) -> None:
    """E2: the live vessel's first boot: a NULL fingerprint is re-commissioned once, changes no record, then is stable."""
    async with crew_world(tmp_path) as world:
        agent = CrewAgent("security-e2", "security_officer")
        enroller, _ = await boot_enroller(world)
        await enroller.enroll(agent, source="birth")
        held = await skill_records(world.skill_service, agent.id)
        await world.acm.stop()
        with contextlib.closing(sqlite3.connect(tmp_path / "acm" / "acm.db")) as conn:
            conn.execute("UPDATE commissioning_records SET template_fingerprint = NULL")
            conn.commit()
        await world.acm.start()  # the next boot reopens the file
        record = await world.acm.get_commissioning_record(agent.id)
        assert record is not None and record.template_fingerprint is None  # premise: as BF-906 wrote it
        history = await world.acm.get_transition_history(agent.id)

        enroller, ontology = await boot_enroller(world)
        again = await enroller.enroll(agent, source="backfill")

        assert again is not None and (again.recommissioned, again.skills_granted) == (True, ())
        assert await skill_records(world.skill_service, agent.id) == held
        changed = await world.acm.get_commissioning_record(agent.id)
        assert changed is not None
        assert changed.template_fingerprint == template_fingerprint(ontology.get_role_template_for_agent("security_officer"))
        rows = recommission_rows(history, await world.acm.get_transition_history(agent.id))
        assert len(rows) == 1 and "skills=none" in rows[0].reason
        third = await enroller.enroll(agent, source="backfill")
        assert third is not None and third.recommissioned is False


@pytest.mark.asyncio
async def test_a_decommissioned_crew_member_is_not_recommissioned(tmp_path: Path) -> None:
    """E3: a changed template leaves a decommissioned agent's records and commissioning untouched."""
    async with crew_world(tmp_path) as world:
        agent = CrewAgent("security-e3", "security_officer")
        enroller, _ = await boot_enroller(world)
        await enroller.enroll(agent, source="birth")
        await world.acm.decommission(agent.id, reason="BF-917 test", initiated_by="captain")
        record = await world.acm.get_commissioning_record(agent.id)
        held = await skill_records(world.skill_service, agent.id)
        edit_skills_yaml(world, _VULNERABILITY, _ADD_CODE_REVIEW)
        enroller, _ = await boot_enroller(world)

        result = await enroller.enroll(agent, source="backfill")

        assert result is not None and result.recommissioned is False
        assert await world.acm.get_commissioning_record(agent.id) == record
        assert await skill_records(world.skill_service, agent.id) == held


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["raises", "no-profile"])
async def test_a_failed_recommission_records_nothing_and_the_next_boot_applies_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, failure: str,
) -> None:
    """E4: a chain that raises, or reads no profile, records nothing and logs one ERROR; the next pass applies it."""
    async with crew_world(tmp_path) as world:
        agent = CrewAgent("security-e4", "security_officer")
        enroller, _ = await boot_enroller(world)
        await enroller.enroll(agent, source="birth")
        record = await world.acm.get_commissioning_record(agent.id)
        history = await world.acm.get_transition_history(agent.id)
        edit_skills_yaml(world, _VULNERABILITY, _ADD_CODE_REVIEW)
        enroller, _ = await boot_enroller(world)

        async def _failing(*args: Any, **kwargs: Any) -> dict[str, Any]:
            if failure == "raises":
                raise OSError("BF-917 test: the commissioning chain failed")
            return {"agent_id": agent.id, "agent_type": agent.agent_type, "skills_acquired": [], "tools_granted": []}

        with monkeypatch.context() as patched:
            patched.setattr(world.acm, "commission", _failing)
            with caplog.at_level(logging.ERROR, logger="probos.crew_enrollment"):
                failed = await enroller.enroll(agent, source="backfill")

        assert failed is not None and failed.recommissioned is False
        assert await world.acm.get_commissioning_record(agent.id) == record
        assert await world.acm.get_transition_history(agent.id) == history
        assert "code_review" not in await skill_records(world.skill_service, agent.id)
        errors = [r for r in caplog.records if r.name == "probos.crew_enrollment" and r.levelno == logging.ERROR]
        assert len(errors) == 1
        assert "BF-917" in errors[0].getMessage() and agent.id in errors[0].getMessage()
        # A1: each guard names its own cause, so the profile guard is not masked by the PCC check after it.
        assert ("read no skill profile" if failure == "no-profile" else "re-commissioning failed") in errors[0].getMessage()

        retried = await enroller.enroll(agent, source="backfill")
        assert retried is not None and (retried.recommissioned, retried.skills_granted) == (True, ("code_review",))


@pytest.mark.asyncio
async def test_a_recommission_that_leaves_a_pcc_missing_records_nothing_and_the_next_boot_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """E5 (A1): a PCC added after the agent's commissioning, and a base step that fails. AD-889 logs the failure at
    DEBUG and returns the profile it read; the re-commission records nothing and logs one ERROR naming the PCC, the
    rule a first commissioning keeps (BF-906 A3). The next pass acquires the PCC and records the template."""
    async with crew_world(tmp_path) as world:
        agent = CrewAgent("security-e5", "security_officer")
        enroller, _ = await boot_enroller(world)
        await enroller.enroll(agent, source="birth")
        await world.skill_service.stop()
        with contextlib.closing(sqlite3.connect(tmp_path / "skills.db")) as conn:
            conn.execute("DELETE FROM agent_skills WHERE agent_id = ? AND skill_id = ?", (agent.id, "duty_execution"))
            conn.commit()
        await world.skill_service.start()  # the next boot reopens the file
        assert "duty_execution" not in await skill_records(world.skill_service, agent.id)  # premise: a PCC is missing
        record = await world.acm.get_commissioning_record(agent.id)
        history = await world.acm.get_transition_history(agent.id)
        edit_skills_yaml(world, _VULNERABILITY, _ADD_CODE_REVIEW)
        enroller, _ = await boot_enroller(world)

        async def _failing_base_step(*args: Any, **kwargs: Any) -> None:
            raise OSError("BF-917 test: the base commissioning step failed")

        with monkeypatch.context() as patched:
            patched.setattr(world.skill_service, "commission_agent", _failing_base_step)
            with caplog.at_level(logging.ERROR, logger="probos.crew_enrollment"):
                degraded = await enroller.enroll(agent, source="backfill")

        assert degraded is not None and degraded.recommissioned is False
        assert await world.acm.get_commissioning_record(agent.id) == record
        assert await world.acm.get_transition_history(agent.id) == history
        held = await skill_records(world.skill_service, agent.id)
        assert "code_review" in held and "duty_execution" not in held  # premise: the chain ran past its failed base step
        errors = [r for r in caplog.records if r.name == "probos.crew_enrollment" and r.levelno == logging.ERROR]
        assert len(errors) == 1
        assert "BF-917" in errors[0].getMessage() and "without the PCCs duty_execution" in errors[0].getMessage()

        retried = await enroller.enroll(agent, source="backfill")
        assert retried is not None and (retried.recommissioned, retried.skills_granted) == (True, ("duty_execution",))
        assert (await skill_records(world.skill_service, agent.id))["code_review"] == held["code_review"]


@pytest.mark.asyncio
async def test_overlapping_enrollments_of_one_agent_acquire_a_missing_skill_once_and_keep_its_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """E6 (A1): two enrollments of one agent overlap after a template change. The first to reach ``acquire_skill``
    for the new skill waits, bounded, for a second; the record it writes is then advanced. Without the enroller's
    lock the second has passed its snapshot too and its write resets that record. With it, the second waits, reads
    the new fingerprint and acquires nothing."""
    async with crew_world(tmp_path) as world:
        agent = CrewAgent("security-e6", "security_officer")
        enroller, _ = await boot_enroller(world)
        await enroller.enroll(agent, source="birth")
        history = await world.acm.get_transition_history(agent.id)
        edit_skills_yaml(world, _VULNERABILITY, _ADD_CODE_REVIEW)
        enroller, ontology = await boot_enroller(world)

        real_acquire = world.skill_service.acquire_skill
        callers: list[str] = []
        second_arrived = asyncio.Event()
        release_second = asyncio.Event()

        async def _gated_acquire(agent_id: str, skill_id: str, *args: Any, **kwargs: Any) -> Any:
            if skill_id == "code_review":
                callers.append(agent_id)
                if len(callers) == 1:
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(second_arrived.wait(), _SECOND_CALLER_WAIT)
                else:
                    second_arrived.set()
                    await release_second.wait()
            return await real_acquire(agent_id, skill_id, *args, **kwargs)

        monkeypatch.setattr(world.skill_service, "acquire_skill", _gated_acquire)
        tasks = [asyncio.create_task(enroller.enroll(agent, source="backfill")) for _ in range(2)]
        try:
            done, _pending = await asyncio.wait(tasks, timeout=60, return_when=asyncio.FIRST_COMPLETED)
            assert done, "premise: one enrollment finished"
            assert "code_review" in await skill_records(world.skill_service, agent.id)  # premise: the first write ran
            await world.skill_service.update_proficiency(agent.id, "code_review", ProficiencyLevel.ADVISE, source="bf917-test")
            await world.skill_service.record_exercise(agent.id, "code_review")
            advanced = (await skill_records(world.skill_service, agent.id))["code_review"]
            assert (advanced[0], advanced[1]) == (ProficiencyLevel.ADVISE, 1)  # premise: the record moved on
        finally:
            release_second.set()
            results = await asyncio.wait_for(asyncio.gather(*tasks), 60)

        assert callers == [agent.id]  # the missing skill was acquired once
        assert (await skill_records(world.skill_service, agent.id))["code_review"] == advanced
        assert sorted((r.commissioned, r.recommissioned) for r in results if r is not None) == [(False, False), (False, True)]
        changed = await world.acm.get_commissioning_record(agent.id)
        assert changed is not None
        assert changed.template_fingerprint == template_fingerprint(ontology.get_role_template_for_agent("security_officer"))
        assert len(recommission_rows(history, await world.acm.get_transition_history(agent.id))) == 1


# --- D1 to D3: probos doctor ------------------------------------------------------------------------


def _context(tmp_path: Path) -> DoctorContext:
    return DoctorContext(config=None, home_dir=tmp_path, data_dir=tmp_path / "data", config_path=None)


def _tree(root: Path) -> dict[str, tuple[int, int]]:
    return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns) for p in sorted(root.rglob("*"))}


@pytest.mark.asyncio
async def test_the_doctor_reports_ok_for_the_shipped_templates(tmp_path: Path) -> None:
    """D1: the shipped ontology passes, and the check creates no data directory."""
    result = await _RoleTemplateCheck().run(_context(tmp_path))
    assert result.outcome is CheckOutcome.OK, result.detail
    assert "templates" in result.message
    assert not (tmp_path / "data").exists()


@pytest.mark.asyncio
async def test_the_doctor_warns_for_an_unregistered_template_skill_and_writes_nothing(tmp_path: Path) -> None:
    """D2: one unregistered id is one WARN line naming the post and the skill; nothing on disk changes."""
    copy = tmp_path / "ontology"
    shutil.copytree(ONTOLOGY_DIR, copy)
    path = copy / "skills.yaml"
    text = path.read_text(encoding="utf-8")
    assert text.count("      - skill_id: access_control\n") == 1  # premise
    path.write_text(text.replace("      - skill_id: access_control\n", "      - skill_id: access_kontrol\n"), encoding="utf-8")
    before = _tree(tmp_path)

    result = await _RoleTemplateCheck(ontology_dir=copy).run(_context(tmp_path))

    assert result.outcome is CheckOutcome.WARN
    assert result.detail.splitlines() == [
        "chief_security: template skill access_kontrol is not a registered skill definition",
    ]
    assert "skills.yaml" in result.remediation
    assert _tree(tmp_path) == before


def test_the_role_template_check_is_registered_once_after_token_accounting() -> None:
    """D3: a fresh interpreter on this tree registers the check once, after token_accounting, next to crew_enrollment."""
    import probos

    src_dir = Path(probos.__file__).resolve().parents[1]  # the tree this test runs against
    probe = (
        "import json, probos; from probos.doctor import checks; from probos.doctor.registry import iter_checks; "
        "print(json.dumps({'src': probos.__file__, 'names': [c.name for c in iter_checks()]}))"
    )
    done = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, timeout=120, check=False,
        env={**os.environ, "PYTHONPATH": str(src_dir)},
    )
    assert done.returncode == 0, done.stderr
    seen = json.loads(done.stdout.strip().splitlines()[-1])
    assert Path(seen["src"]).resolve().is_relative_to(src_dir)  # the child imported this tree
    names = seen["names"]
    assert names.count("role_templates") == 1
    assert names[names.index("crew_enrollment") + 1] == "token_accounting"
    assert names[names.index("token_accounting") + 1] == "role_templates"
```

### 7.10 `config/ontology/skills.yaml` (M2)

SEARCH:
```yaml
      - skill_id: duty_execution
        min_proficiency: 3

# Qualification paths: structured requirements for rank transitions
```
REPLACE:
```yaml
      - skill_id: duty_execution
        min_proficiency: 3

  # BF-915 (#1623): Bridge -- the Ship's Yeoman, from the post's capabilities in organization.yaml
  # (daily briefing, schedule lookup, inbox triage, delegation, standing-order relay)
  yeoman:
    required:
      - skill_id: communication
        min_proficiency: 4
      - skill_id: chain_of_command
        min_proficiency: 4
      - skill_id: captain_briefing
        min_proficiency: 4
      - skill_id: schedule_coordination
        min_proficiency: 3
      - skill_id: correspondence_triage
        min_proficiency: 3
      - skill_id: crew_delegation
        min_proficiency: 3
    optional:
      - skill_id: duty_execution
        min_proficiency: 3

  # BF-915 (#1623): Operations -- the Training Officer, from the post's capabilities in organization.yaml
  # and AD-628 (drills, readiness reports, onboarding mentorship, limited-duty recommendations)
  chief_training:
    required:
      - skill_id: communication
        min_proficiency: 4
      - skill_id: collaboration
        min_proficiency: 4
      - skill_id: drill_planning
        min_proficiency: 4
      - skill_id: readiness_assessment
        min_proficiency: 4
      - skill_id: onboarding_mentorship
        min_proficiency: 4
      - skill_id: limited_duty_planning
        min_proficiency: 3
    optional:
      - skill_id: knowledge_stewardship
        min_proficiency: 3

# Qualification paths: structured requirements for rank transitions
```

### 7.11 `src/probos/skill_framework.py` (M2: the eight definitions)

SEARCH:
```python
    SkillDefinition(skill_id="system_monitoring", name="System Monitoring", category=SkillCategory.ROLE, description="Track operational readiness and resource health.", domain="operations", decay_rate_days=14, origin="role"),
]
```
REPLACE:
```python
    SkillDefinition(skill_id="system_monitoring", name="System Monitoring", category=SkillCategory.ROLE, description="Track operational readiness and resource health.", domain="operations", decay_rate_days=14, origin="role"),
    # BF-915 (#1623): the Ship's Yeoman and the Training Officer. Operations, a legacy domain: the Yeoman's
    # Bridge would be a resolver tag question no crew member asks today.
    SkillDefinition(skill_id="captain_briefing", name="Captain Briefing", category=SkillCategory.ROLE, description="Assemble the Captain's daily briefing from inbox, calendar and ship highlights.", domain="operations", decay_rate_days=14, origin="role"),
    SkillDefinition(skill_id="schedule_coordination", name="Schedule Coordination", category=SkillCategory.ROLE, description="Answer and coordinate the Captain's schedule questions.", domain="operations", decay_rate_days=14, origin="role"),
    SkillDefinition(skill_id="correspondence_triage", name="Correspondence Triage", category=SkillCategory.ROLE, description="Summarise unread mail and flag what needs the Captain.", domain="operations", decay_rate_days=14, origin="role"),
    SkillDefinition(skill_id="crew_delegation", name="Crew Delegation", category=SkillCategory.ROLE, description="Route a request to the right specialist and relay standing orders.", domain="operations", decay_rate_days=14, origin="role"),
    SkillDefinition(skill_id="drill_planning", name="Drill Planning", category=SkillCategory.ROLE, description="Schedule qualification drills for the crew.", domain="operations", decay_rate_days=14, origin="role"),
    SkillDefinition(skill_id="readiness_assessment", name="Readiness Assessment", category=SkillCategory.ROLE, description="Report ship-wide and per-department skill readiness.", domain="operations", decay_rate_days=14, origin="role"),
    SkillDefinition(skill_id="onboarding_mentorship", name="Onboarding Mentorship", category=SkillCategory.ROLE, description="Mentor newly named crew through onboarding.", domain="operations", decay_rate_days=14, origin="role"),
    SkillDefinition(skill_id="limited_duty_planning", name="Limited Duty Planning", category=SkillCategory.ROLE, description="Co-author limited-duty recommendations with Medical.", domain="operations", decay_rate_days=14, origin="role"),
]
```

### 7.12 `src/probos/role_template_audit.py` (M2)

Pair 1 of 3:

SEARCH:
```python
"""BF-917 (#1625): the role templates audited against the skill catalog.
```
REPLACE:
```python
"""BF-917 (#1625) and BF-915 (#1623): the role templates audited against the skill catalog and the crew posts.
```

Pair 2 of 3:

SEARCH:
```python
from collections.abc import Mapping
```
REPLACE:
```python
from collections.abc import Iterable, Mapping
```

Pair 3 of 3:

SEARCH:
```python
        if req.skill_id not in registered
    }
    return tuple(sorted(missing))
```
REPLACE:
```python
        if req.skill_id not in registered
    }
    return tuple(sorted(missing))


def crew_posts_without_template(
    posts: Mapping[str, Any], assignments: Iterable[Any], role_templates: Mapping[str, Any],
) -> tuple[tuple[str, str], ...]:
    """BF-915: each ``(post_id, agent_type)`` assigned to a crew-tier post that has no role template, sorted.

    A crew-tier post with no assignment is not reported: no agent is commissioned under it.
    """
    gaps = {
        (assignment.post_id, assignment.agent_type)
        for assignment in assignments
        if (post := posts.get(assignment.post_id)) is not None and post.tier == "crew"
        and assignment.post_id not in role_templates
    }
    return tuple(sorted(gaps))
```

### 7.13 `src/probos/doctor/checks/role_template_check.py` (M2)

Pair 1 of 4:

SEARCH:
```python
"""BF-917 (#1625): every skill a role template names is a registered skill definition.
```
REPLACE:
```python
"""BF-917 (#1625) and BF-915 (#1623): every template skill is registered, and every assigned crew post has a template.
```

Pair 2 of 4:

SEARCH:
```python
_REMEDIATION = (
    "Correct the skill id in config/ontology/skills.yaml, or register the skill in "
    "ONTOLOGY_TEMPLATE_SKILLS (probos/skill_framework.py), then restart ProbOS."
)
```
REPLACE:
```python
_REMEDIATION = (
    "Correct the skill id in config/ontology/skills.yaml, or register the skill in "
    "ONTOLOGY_TEMPLATE_SKILLS (probos/skill_framework.py); give an assigned crew post a "
    "role_templates entry in skills.yaml; then restart ProbOS."
)
```

Pair 3 of 4:

SEARCH:
```python
        from probos.role_template_audit import unregistered_template_skills
```
REPLACE:
```python
        from probos.role_template_audit import crew_posts_without_template, unregistered_template_skills
```

Pair 4 of 4:

SEARCH:
```python
            for post, skill in unregistered_template_skills(loader.role_templates, registered)
        ]
        if not findings:
            return CheckResult(
                CheckOutcome.OK,
                f"Role templates: {len(loader.role_templates)} templates, every template skill registered",
            )
```
REPLACE:
```python
            for post, skill in unregistered_template_skills(loader.role_templates, registered)
        ]
        findings += [
            f"{post} ({agent_type}): an assigned crew post has no role template"
            for post, agent_type in crew_posts_without_template(
                loader.posts, loader.assignments.values(), loader.role_templates,
            )
        ]
        if not findings:
            return CheckResult(
                CheckOutcome.OK,
                f"Role templates: {len(loader.role_templates)} templates, every template skill registered "
                "and every assigned crew post templated",
            )
```

### 7.14 `tests/test_ontology_skills.py` (M2: the pinned template count)

SEARCH:
```python
        assert len(service._loader.role_templates) == 14
```
REPLACE:
```python
        # BF-915 (#1623): the Yeoman's and the Training Officer's templates join the fourteen.
        assert len(service._loader.role_templates) == 16
```

### 7.15 `tests/test_bf906_crew_enrollment_boot.py` (M2: T-B1 pinned "the yeoman has no template")

SEARCH:
```python
        # A type with no role template is commissioned with its PCCs, recorded without one, and named in a WARNING.
        yeomen = [a for a in crew if a.agent_type == "yeoman"]
        assert len(yeomen) == 1, f"premise: exactly one yeoman among the crew, got {len(yeomen)}"
        assert rt.ontology.get_role_template_for_agent("yeoman") is None
        yeoman_record = await rt.acm.get_commissioning_record(yeomen[0].id)
        assert yeoman_record is not None and yeoman_record.role_template is None
        warnings = [
            r for r in caplog.records
            if r.name == "probos.crew_enrollment" and r.levelno == logging.WARNING
            and yeomen[0].id in r.getMessage()
        ]
        assert len(warnings) == 1
        assert "no role template" in warnings[0].getMessage()
```
REPLACE:
```python
        # BF-915 (#1623): every crew type now resolves a role template, so the yeoman is commissioned under its own
        # and no 'no role template' WARNING is logged. The WARNING itself stays pinned by
        # test_bf906_acm_commissioning.py's HA8, with a type that has no template.
        yeomen = [a for a in crew if a.agent_type == "yeoman"]
        assert len(yeomen) == 1, f"premise: exactly one yeoman among the crew, got {len(yeomen)}"
        assert rt.ontology.get_role_template_for_agent("yeoman") is not None
        yeoman_record = await rt.acm.get_commissioning_record(yeomen[0].id)
        assert yeoman_record is not None and yeoman_record.role_template == "yeoman"
        assert [
            r for r in caplog.records
            if r.name == "probos.crew_enrollment" and "no role template" in r.getMessage()
        ] == []
```

### 7.16 New file: `tests/test_bf915_yeoman_and_training_templates.py` (M2)

```python
"""BF-915 (#1623): the Yeoman and the Training Officer have role templates, the doctor reports a crew post without
one, and BF-917's trigger applies a new template to a crew member commissioned without one, keeping its PCCs.

Real loader, ontology service, stores and AD-889 chain (``tests/fixtures/crew_template_world.py``).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from probos.crew_enrollment import template_fingerprint
from probos.doctor.checks.role_template_check import _RoleTemplateCheck
from probos.doctor.protocol import CheckOutcome, DoctorContext
from probos.ontology import VesselOntologyService
from probos.ontology.loader import OntologyLoader
from probos.role_template_audit import crew_posts_without_template, unregistered_template_skills
from probos.skill_framework import (
    BUILTIN_PCCS,
    ONTOLOGY_TEMPLATE_SKILLS,
    ProficiencyLevel,
    builtin_skill_definitions,
)
from tests.fixtures.crew_template_world import (
    ONTOLOGY_DIR,
    CrewAgent,
    boot_enroller,
    crew_world,
    edit_skills_yaml,
    recommission_rows,
    skill_records,
)

_NEW_ROLE_SKILLS = {
    "yeoman": {"captain_briefing", "schedule_coordination", "correspondence_triage", "crew_delegation"},
    "chief_training": {"drill_planning", "readiness_assessment", "onboarding_mentorship", "limited_duty_planning"},
}
_PCC_IDS = frozenset(p.skill_id for p in BUILTIN_PCCS)


@pytest.mark.asyncio
async def test_every_assigned_crew_post_resolves_a_role_template(tmp_path: Path) -> None:
    """B1: no assigned crew-tier post lacks a template, through the loader and through the ontology service."""
    loader = OntologyLoader(ONTOLOGY_DIR)
    await loader.initialize()
    assert crew_posts_without_template(loader.posts, loader.assignments.values(), loader.role_templates) == ()
    ontology = VesselOntologyService(ONTOLOGY_DIR, data_dir=tmp_path)
    await ontology.initialize()
    crew = ontology.get_crew_agent_types()
    assert {"yeoman", "training_officer"} <= crew and len(crew) >= 16  # premise: the assigned crew
    assert [t for t in sorted(crew) if ontology.get_role_template_for_agent(t) is None] == []


@pytest.mark.asyncio
async def test_the_yeoman_and_training_templates_name_only_registered_operations_skills() -> None:
    """B2: each template has its four new role skills plus PCCs; all are registered operations definitions."""
    loader = OntologyLoader(ONTOLOGY_DIR)
    await loader.initialize()
    by_id = {d.skill_id: d for d in ONTOLOGY_TEMPLATE_SKILLS}
    for post_id, new in _NEW_ROLE_SKILLS.items():
        required = {r.skill_id for r in loader.role_templates[post_id].required_skills}
        assert required - _PCC_IDS == new, post_id
        assert all(by_id[s].domain == "operations" for s in new), post_id
    registered = frozenset(d.skill_id for d in builtin_skill_definitions())
    assert unregistered_template_skills(loader.role_templates, registered) == ()


@pytest.mark.asyncio
async def test_the_doctor_warns_for_an_assigned_crew_post_without_a_template(tmp_path: Path) -> None:
    """B3: the yeoman's post without its template is one WARN line naming the post and the agent type."""
    copy = tmp_path / "ontology"
    shutil.copytree(ONTOLOGY_DIR, copy)
    path = copy / "skills.yaml"
    text = path.read_text(encoding="utf-8")
    assert text.count("  yeoman:\n") == 1  # premise
    path.write_text(text.replace("  yeoman:\n", "  yeoman_retired:\n"), encoding="utf-8")
    context = DoctorContext(config=None, home_dir=tmp_path, data_dir=tmp_path / "data", config_path=None)

    result = await _RoleTemplateCheck(ontology_dir=copy).run(context)

    assert result.outcome is CheckOutcome.WARN
    assert result.detail.splitlines() == ["yeoman (yeoman): an assigned crew post has no role template"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("agent_type", "post_id"),
    [("yeoman", "yeoman"), ("training_officer", "chief_training")],
    ids=["yeoman", "training_officer"],
)
async def test_a_crew_member_commissioned_without_a_template_gains_it_keeping_its_pccs(
    tmp_path: Path, agent_type: str, post_id: str,
) -> None:
    """B4 (the seam): PCCs-only commissioning -> this change's template -> re-commissioned once, PCCs unchanged,
    the four role skills at their floors, the record names the post, no tool; stable afterwards."""
    async with crew_world(tmp_path) as world:
        shipped = (world.ontology_dir / "skills.yaml").read_text(encoding="utf-8")
        edit_skills_yaml(world, f"  {post_id}:\n", f"  {post_id}_before_bf915:\n")
        agent = CrewAgent(f"{agent_type}-b4", agent_type)
        enroller, ontology = await boot_enroller(world)
        assert ontology.get_role_template_for_agent(agent_type) is None  # premise: the vessel before BF-915
        first = await enroller.enroll(agent, source="birth")
        assert first is not None and first.commissioned is True and first.role_template is None
        await world.skill_service.update_proficiency(agent.id, "communication", ProficiencyLevel.LEAD, source="bf915-test")
        held = await skill_records(world.skill_service, agent.id)
        assert set(held) == _PCC_IDS  # premise: the nine PCCs only
        history = await world.acm.get_transition_history(agent.id)

        (world.ontology_dir / "skills.yaml").write_text(shipped, encoding="utf-8")  # this change's templates
        enroller, ontology = await boot_enroller(world)
        template = ontology.get_role_template_for_agent(agent_type)
        assert template is not None
        again = await enroller.enroll(agent, source="backfill")

        assert again is not None and again.recommissioned is True
        assert set(again.skills_granted) == _NEW_ROLE_SKILLS[post_id]
        after = await skill_records(world.skill_service, agent.id)
        assert {skill: after[skill] for skill in held} == held  # communication stays at LEAD, every PCC as it was
        floors = {r.skill_id: r.min_proficiency for r in template.required_skills}
        assert {s: after[s][0] for s in _NEW_ROLE_SKILLS[post_id]} == {s: floors[s] for s in _NEW_ROLE_SKILLS[post_id]}
        record = await world.acm.get_commissioning_record(agent.id)
        assert record is not None and record.role_template == post_id
        assert record.template_fingerprint == template_fingerprint(template)
        assert len(recommission_rows(history, await world.acm.get_transition_history(agent.id))) == 1
        assert await world.permission_store.list_grants(active_only=True) == []
        third = await enroller.enroll(agent, source="backfill")
        assert third is not None and third.recommissioned is False
```

## 8. Tracking (tracker pairs; in M2's commit)

Each pair anchors on one line that occurs once in its file and that BF-912's entries do not change. BF-912 inserts its `PROGRESS.md` entry directly under the title line and its `DECISIONS.md` entry before the same heading used below, so after it lands both anchor lines are still present exactly once. In `PROGRESS.md` (newest first) these two entries land above BF-912's. In `DECISIONS.md` (chronological) BF-912's entry precedes them. Set the date to the commit date.

**`PROGRESS.md`** (anchored on the title line):

SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**BF-915 (2026-10-22), closes #1623 -- the Ship's Yeoman and the Training Officer have role templates, and `probos doctor` reports an assigned crew post without one.** `config/ontology/skills.yaml` gains `yeoman` (communication, chain of command, captain_briefing, schedule_coordination, correspondence_triage, crew_delegation) and `chief_training` (communication, collaboration, drill_planning, readiness_assessment, onboarding_mentorship, limited_duty_planning), derived from each post's capabilities and AD-628. The eight new role skills are registered `operations` definitions. Yeo and Tucker, whom BF-906 commissioned with the nine PCCs only, are re-commissioned once by BF-917's trigger: every PCC keeps its level, and each gains four role skills at the template's floor. The `role_templates` doctor check also WARNs for an assigned crew-tier post with no template. New: `tests/test_bf915_yeoman_and_training_templates.py`. Updated: `tests/test_ontology_skills.py` (16 templates) and `tests/test_bf906_crew_enrollment_boot.py` T-B1 (the yeoman now has a template). The contract is `prompts/bf-917-template-skills-and-recommission.md`.

**BF-917 (2026-10-22), closes #1625 -- the role templates' 22 unregistered skill ids are registered definitions, and a changed role template re-commissions a crew member once without loss.** The 14 templates named 39 required entries over 22 ids that no definition registered, so every templated crew member held 2 to 4 records that profiles filed as acquired skills. `ONTOLOGY_TEMPLATE_SKILLS` registers them through `builtin_skill_definitions()` as role skills with no prerequisite, no preferred tool, 14 days of decay (what an undefined record already had) and a legacy domain, so the AD-888 resolver's tag fallback asks nothing new and no tool is granted. `commissioning_records` gains a nullable `template_fingerprint`. When the template an agent resolves has changed since its commissioning (a record from before BF-917 counts as changed once), the enroller re-runs AD-889 with `preserve_existing=True` on a context without the tool services, records the new fingerprint with a "re-commissioned" history row only after the chain succeeds and leaves every PCC held, and leaves decommissioned agents alone. Enrollments run one at a time per enroller, so two overlapping enrollments of one crew member cannot reset a skill record the first had advanced. The new `role_templates` doctor check WARNs for an unregistered template id and only reports. New: `src/probos/role_template_audit.py`, `src/probos/doctor/checks/role_template_check.py`, `tests/fixtures/crew_template_world.py` and `tests/test_bf917_template_skills_and_recommission.py` (real loader, stores and chain). #1625's question, whether AD-889 step 3 should grant tools at all, stays with the Captain. The contract is `prompts/bf-917-template-skills-and-recommission.md`.
```

**`DECISIONS.md`** (inserted before the heading below; BF-912's entry already precedes it):

SEARCH:
```markdown
### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```markdown
### BF-917 -- The role templates' skills are registered definitions, and a changed role template re-commissions a crew member once without loss (2026-10-22, #1625)

- *Scope.* `skill_framework.py` (`ONTOLOGY_TEMPLATE_SKILLS`, `builtin_skill_definitions`), `acm.py` (the `template_fingerprint` column and `record_commissioning(recommission=True)`), `crew_enrollment.py` (`template_fingerprint`, the trigger), `storage_declarations.py` (retention note), new `role_template_audit.py` and `doctor/checks/role_template_check.py`. Tests: new `tests/test_bf917_template_skills_and_recommission.py` and `tests/fixtures/crew_template_world.py`. Batched with BF-915 (#1623), one PR. Contract: `prompts/bf-917-template-skills-and-recommission.md`. Tier HIGH (live commissioning records are rewritten at boot).
- *D1 (register, do not rename).* A separate list, not `ROLE_SKILL_TEMPLATES`, whose agent-type keys feed the legacy FOLLOW acquisition. Renaming the three near-names would orphan the live records. Each definition is ROLE, has no prerequisite, preferred tool or composite, decays at 14 days and uses a domain a legacy role skill already has (guard 1: the resolver's tag fallback asks no new question; guard 2: decay and acquisition unchanged, and `check_decay` has no production caller).
- *D2 (the trigger).* A sha256 of the post id plus each required skill's id and floor, stored in an additive nullable column. NULL means a record from before BF-917, re-commissioned once. The comparison runs in `CrewEnrollmentService.enroll`. A re-commission keeps every record it finds, acquires only missing skills, runs without the tool registry and permission store (so it grants no tool), and records the fingerprint and a history row in one commit only after the chain succeeded and left every PCC held (BF-906 A3's rule; AD-889 swallows a failed base step). A raised chain, an unread profile or a missing PCC is retried next boot. Enrollments are serialized by one lock per enroller: the `IS NOT ?` guard protects only the record, and the chain's skill writes are fresh-record upserts after a snapshot, so an overlapping enrollment of the same agent would otherwise reset a record the first had advanced (review round 1). Decommissioned agents are skipped. Rejected: a stateless "a required skill is missing" rule (prerequisite-blocked skills never settle, so it would fire every boot), a separate table, comparing the post id only, and a `grant_tools` parameter on the AD-889 seam. The write uses `record_commissioning`'s new mode because `AgentCapitalService` is at its 15-method SRP limit.
- *D4 (detection).* One doctor check, `role_templates`: each finding is a WARN, and it repairs nothing. An ontology the loader cannot read raises, which the doctor runner reports as FAIL, as for any check. CI fails first, because templates and definitions both ship; no startup WARNING is added.
- *Disclosed effects.* The first boot re-commissions each of the 16 crew once: one "re-commissioned" history row each and a fingerprint on each record; no existing skill record changes. There are 30 more skill definitions (83 in total): the Skill Library and `/api/skills` list them, profiles show the formerly orphan records as role skills, AD-628's department readiness denominators grow (science +9, medical +6, operations +10, security +3, engineering +2), and AD-596c maps the `emergence_analysis` intent to its now-registered skill instead of `duty_execution`. No tool is granted and `tool_count` is unchanged.
- *Reversal.* Revert the commits. The column stays: BF-906's statements name their columns, so they ignore it. Records keep their updated role template. The registered definitions persist in `skills.db` (the registry loads its rows at start) until the Captain retires them; added skill records stay (never deleted).

### BF-915 -- The Ship's Yeoman and the Training Officer have role templates, and the doctor reports an assigned crew post without one (2026-10-22, #1623)

- *Scope.* `config/ontology/skills.yaml` (`yeoman`, `chief_training`), eight `operations` definitions in `ONTOLOGY_TEMPLATE_SKILLS`, `role_template_audit.crew_posts_without_template`, and the second rule of the `role_templates` doctor check. Tests: new `tests/test_bf915_yeoman_and_training_templates.py`; updated `tests/test_ontology_skills.py` and T-B1 in `tests/test_bf906_crew_enrollment_boot.py`. Contract: `prompts/bf-917-template-skills-and-recommission.md` (M2).
- *Templates.* Derived from each post's capabilities (`organization.yaml`) and AD-628 for the Training Officer, which has no personal standing orders. Each template has two PCCs and four new role skills, plus one optional PCC. The Yeoman's skills use `operations`, not `bridge`: `bridge` would be a resolver tag question no crew member asks today.
- *Re-commission.* BF-917's trigger applies the new templates: "no template → a template" changes the fingerprint. PCC levels are kept, and the four role skills are acquired at the template's floors.
- *Detection.* WARN for each assigned crew-tier post with no template. Unassigned crew-tier posts (`engineering_officer`, `chief_science`) are not reported.
- *Correction recorded.* The issue's qualification impact is latent: `evaluate_qualification` has no production caller.
- *Reversal.* Revert the M2 commit. Yeo's and Tucker's role-skill records and their re-commissioned records stay; the next boot under the old templates re-commissions them once more to no template, which deletes nothing.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

**After both edits:** `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` regenerates `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`; both go in M2's commit. Verify with `--check` and `tests/test_ad1184_ad_ledger.py`, never by byte comparison.

**Docs-only commit after M2:** add a *Validation of record* bullet before each entry's *Reversal* line: the mutation campaign of record (§10), its base tree, the sha256 of each §10 file and each new test file, and each row's first failing test. Add the same as a closing section of this contract, then regenerate the ledger.

**`docs/development/roadmap.md`:** no row (the Bug Tracker has no `BF-9xx` rows; BF-916's precedent).

## 9. What this does NOT change

- AD-889's chain (`commissioning.py`) and `AgentCapitalService.commission`'s signature. Step 3 is unchanged for every caller that passes the runtime. F-157 (DEBUG on a failed grant step) stays on #1523.
- `preferred_tools` of any skill, the resolver's tag-versus-domain match and its permission context, and any tool grant. `tool_count`. #1625's tool question stays with the Captain.
- Template ids (no rename); the 14 existing templates' contents; `ROLE_SKILL_TEMPLATES`; `BUILTIN_PCCS`.
- `apply-role` and `POST /api/skills/commission` (`preserve_existing=False`); `ToolContext`.
- `check_decay`, `acquire_skill`, `get_profile`, `commission_agent`; the BF-906 invariant and its doctor check; the enrollment pass's log line; the event log (no new row).
- `startup/*`: no startup audit.
- `engineering_officer` and `chief_science` assignments.

## 10. Mutation rows

Tier HIGH: every changed production file has rows. Run each row on the contract-applied tree after an unmutated baseline run passes, and restore the file before the next row. Rows M1-* run against `tests/test_bf917_template_skills_and_recommission.py`; rows M2-* against it plus `tests/test_bf915_yeoman_and_training_templates.py`. Each Line cell occurs exactly once in its file after §7, as a substring as well as a whole line. The two YAML rows edit text, which the campaign tool can apply as a line replacement.

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| M1-R1 | `src/probos/skill_framework.py` | `definitions.extend(ONTOLOGY_TEMPLATE_SKILLS)` | `pass` | G1; G5; D1 |
| M1-R2 | `src/probos/skill_framework.py` | `SkillDefinition(skill_id="trend_analysis", name="Trend Analysis", category=SkillCategory.ROLE, description="Detect and explain change over time in ship metrics and findings.", domain="science", decay_rate_days=14, origin="role"),` | `SkillDefinition(skill_id="trend_analysis", name="Trend Analysis", category=SkillCategory.ROLE, description="Detect and explain change over time in ship metrics and findings.", domain="science", decay_rate_days=7, origin="role"),` | G4 (20 days drops two levels, not one); G2 |
| M1-R3 | `src/probos/skill_framework.py` | `SkillDefinition(skill_id="threat_assessment", name="Threat Assessment", category=SkillCategory.ROLE, description="Judge the likelihood and impact of a threat.", domain="security", decay_rate_days=14, origin="role"),` | `SkillDefinition(skill_id="threat_assessment", name="Threat Assessment", category=SkillCategory.ACQUIRED, description="Judge the likelihood and impact of a threat.", domain="security", decay_rate_days=14, origin="role"),` | G5 (not a role skill); G2 |
| M1-R4 | `src/probos/acm.py` | `await _add_template_fingerprint_column(self._db)` | `pass` | A1 (no such column); E1 |
| M1-R5 | `src/probos/acm.py` | `if "template_fingerprint" not in columns:` | `if False:` | A1 |
| M1-R6 | `src/probos/acm.py` | `"WHERE agent_id = ? AND template_fingerprint IS NOT ?",` | `"WHERE agent_id = ? AND ? IS NOT NULL",` | A2 (same fingerprint returns True; A1: the mutant keeps four placeholders for the four bindings, so the missing guard kills it, not a binding error) |
| M1-R7 | `src/probos/acm.py` | `action = "re-commissioned" if recommission else "commissioned"` | `action = "commissioned"` | A2; E1 (`recommission_rows` finds none) |
| M1-R8 | `src/probos/acm.py` | `initiated_by=row[6], reason=row[7], timestamp=row[8], template_fingerprint=row[9],` | `initiated_by=row[6], reason=row[7], timestamp=row[8],` | E1 (fingerprint reads None); A1 |
| M1-R9 | `src/probos/crew_enrollment.py` | `if recorded_fingerprint == fingerprint:` | `if True:` | E1 (never re-commissions); E2 |
| M1-R10 | `src/probos/crew_enrollment.py` | `if await self._acm.get_lifecycle_state(agent_id) is LifecycleState.DECOMMISSIONED:` | `if False:` | E3 |
| M1-R11 | `src/probos/crew_enrollment.py` | `context = _RecommissionContext(skill_service=self._skill_service, ontology=self._ontology)` | `context = self._commission_context` | E1 (the probe tool is granted) |
| M1-R12 | `src/probos/crew_enrollment.py` | `if not summary.get("skills_acquired"):` | `if False:` | E4 `[no-profile]` (A1: by the cause in the message; the PCC check after it would also refuse) |
| M1-R13 | `src/probos/crew_enrollment.py` | `template_fingerprint=fingerprint, recommission=True,` | `template_fingerprint=fingerprint, recommission=False,` | E1; E2 (INSERT OR IGNORE writes nothing) |
| M1-R14 | `src/probos/crew_enrollment.py` | `template_fingerprint=template_fingerprint(template),` | `template_fingerprint=None,` | E1 (the unchanged second pass re-commissions) |
| M1-R15 | `src/probos/crew_enrollment.py` | `"required": sorted([r.skill_id, r.min_proficiency] for r in template.required_skills),` | `"required": [],` | E1 (the edit is not seen) |
| M1-R16 | `src/probos/crew_enrollment.py` | `skills = tuple(s for s in summary["skills_acquired"] if s not in held_before)` | `skills = ()` | E1 (`skills_granted`, history row); E4 |
| M1-R17 | `src/probos/role_template_audit.py` | `if req.skill_id not in registered` | `if req.skill_id in registered` | D1; D2; G1 |
| M1-R18 | `src/probos/doctor/checks/role_template_check.py` | `if not findings:` | `if True:` | D2 |
| M1-R19 | `src/probos/crew_enrollment.py` | `async with self._enroll_lock:` | `if True:` | E6 (`code_review` acquired twice; the advanced record is reset) |
| M1-R20 | `src/probos/crew_enrollment.py` | `missing_pccs = [pcc.skill_id for pcc in BUILTIN_PCCS if pcc.skill_id not in summary["skills_acquired"]]` | `missing_pccs = []` | E5 (the degraded re-commission is recorded) |
| M2-R1 | `src/probos/role_template_audit.py` | `and assignment.post_id not in role_templates` | `and assignment.post_id in role_templates` | B1; B3 |
| M2-R2 | `config/ontology/skills.yaml` | `- skill_id: drill_planning` | `- skill_id: drill_planing` | G1 (unregistered); B2; D1 |
| M2-R3 | `config/ontology/skills.yaml` | `yeoman:` | `yeoman_post:` | B1; B4 `[yeoman]` |
| M2-R4 | `src/probos/skill_framework.py` | `SkillDefinition(skill_id="captain_briefing", name="Captain Briefing", category=SkillCategory.ROLE, description="Assemble the Captain's daily briefing from inbox, calendar and ship highlights.", domain="operations", decay_rate_days=14, origin="role"),` | `SkillDefinition(skill_id="captain_briefing", name="Captain Briefing", category=SkillCategory.ROLE, description="Assemble the Captain's daily briefing from inbox, calendar and ship highlights.", domain="bridge", decay_rate_days=14, origin="role"),` | G2 and G3 (not a legacy domain); B2 |

The `if recorded_fingerprint == fingerprint:` → `if False:` mutant is equivalent at the database level: the `IS NOT ?` guard makes every repeated attempt write nothing. It is therefore deliberately not a row. It is recorded here as defence in depth.

## 11. Verified Against Codebase (2026-10-22, HEAD `88f0e5b8`, tree `0115bea4`)

```
Read config/ontology/skills.yaml:1-311   templates 45-261 (14 keys); required/optional lists as in §3 D1; qualification_paths 265
Read src/probos/skill_framework.py:570-650  SkillCategory 573; ProficiencyLevel 580 (LEAD=6); SkillDefinition 597-613 (decay_rate_days=14 default, preferred_tools, composite_skill_ids, synergy_partners)
Grep "^    \"[a-z_]+\": \[" skill_framework.py  874 security_officer ... 941 research_specialist (14 keys; no yeoman, training_officer)
Read skill_framework.py:940-946   experimental_design line 944 then "    ]," "}"
Read skill_framework.py:1100-1124  register_skill INSERT OR REPLACE 1108; register_builtins 1118-1124
Read skill_framework.py:1299-1380  acquire_skill prereq check 1311-1321, upsert 1333; commission_agent skip_skill_ids 1346-1380
Read skill_framework.py:1439-1508  check_decay 1450-1456 (decay_days = ... else 14); get_profile 1498-1507
Read src/probos/commissioning.py:19-155  preserve snapshot 52-63; template step 77-97; step 3 guard 112-120; skip None def 125-127
Read src/probos/crew_enrollment.py:1-349  docstring 16-20; imports 23-32; ENROLLMENT_REASON 42; CrewEnrollment 47-57; _has_skills 79; enroll 170-182; _commission 258-327 (record_commissioning 313-317); _log_commissioning 329
Read src/probos/acm.py:1-240, 320-390, 540-563  CommissioningRecord 64-75; _SCHEMA commissioning_records 105-115; _COMMISSIONING_HISTORY_SQL 118-121; start 150-156; get_commissioning_record 206-222; record_commissioning 331-380; commission 548-562
Grep "^    (async )?def " acm.py   15 defs: 132,146,150,158,167,179,197,206,226,294,331,382,392,411,548
Grep "SRP_MAX_BODY_LINES\s*=|SRP_MAX_DIRECT_METHODS\s*=" scripts/check_architecture_principles.py  187: 500; 188: 15
Read tests/test_bf906_acm_commissioning.py:540-580 (SRP pin), 970-1035 (second enroll == CrewEnrollment(...)), 1221-1334, 1500-1628 (_GatedConnection; _a3_key prefixes)
Read tests/test_bf906_crew_enrollment_boot.py:1-200  T-B1 yeoman tail 185-197
Read tests/test_ontology_skills.py:40-110  line 55 "== 14"
Read src/probos/tools/skill_tool_resolver.py:32-98  fallback list_tools(tag=skill.domain) 83-84
Read src/probos/tools/registry.py:108-125, 151-255, 269-319, 336-353  register(tags=), list_tools substring tag match 252-254, default READ 317-319, set_permission_store 123
Read src/probos/startup/communication.py:691-700 (register_builtins at 698), 786-821 (ontology dir, tool seeding tags=[tc.id, tc.provider] 820), 826-831
Read config/ontology/resources.yaml (tool ids/providers: ward_room_*, self_modification, knowledge_query, episodic_recall; providers ward_room, dreaming_engine, ship_computer)
Read src/probos/ontology/loader.py:45-60, 84-162, 215-233, 343-351  data_dir None -> uuid, no write (153-162); role_templates 224-233; tool_capabilities 343-351
Grep "class RoleTemplate|class SkillRequirement|class Assignment|class Post" ontology/models.py  33 Post(tier), 47 Assignment, 74 SkillRequirement, 81 RoleTemplate
Read src/probos/ontology/service.py:48-77, 153-167  VesselOntologyService(config_dir, data_dir=None); get_crew_agent_types 162
Read config/ontology/organization.yaml:1-110, 340-443  yeoman post 76-102 (bridge), chief_training 354-373 (operations), assignments 378-442
Read src/probos/doctor/protocol.py:1-80; doctor/checks/__init__.py:9-34; doctor/runner.py:184-199 (a raising check = FAIL); doctor/checks/crew_enrollment_check.py:1-102
Grep "def register_check|def iter_checks|def _reset_for_tests" doctor/registry.py  21, 36, 41
Read tests/test_bf906_doctor_check.py:328-350; tests/test_bf901_s3_token_accounting_view.py:456-457; tests/test_ad1328_s2a_startup_and_doctor.py:701-705; tests/test_ad1137_doctor.py:1415-1437
Read src/probos/storage_declarations.py:206-229  retention_note 215-220
Read src/probos/capability_request.py:557 (_migrate_payload_column, module function "to keep the store within its SRP budget")
Read tests/test_database_abstraction.py:205-217 (AsyncMock connection through start)
Read tests/test_ad1195_eventlog_pair_freeze.py:87-118
Read tests/fixtures/ad1343_seam_census.py:25-39
Read scripts/phantom-api-precheck.ps1 (fences, masking, patterns 1-3); scripts/phantom_api_ast_helper.py:89-125, 222-259, 598-667, 873-991, 1142-1270
Grep "^# ProbOS Progress" PROGRESS.md -> 1; "^### Explicit delegation models" DECISIONS.md -> 598 (one each)
Read src/probos/tools/adapters.py:101-118 DirectServiceAdapter(tool_id, name, description, handler, tool_type)
Read src/probos/tools/permissions.py:53-77, 203 ToolPermissionStore(db_path); list_grants(active_only)
Read src/probos/crew_utils.py:69-76 is_crew_agent via ontology.get_crew_agent_types
git rev-parse HEAD HEAD^{tree}  88f0e5b8da06a0e28741910898ef56e7f2f63add 0115bea4d384d59f06a24f9faf6b93cdd283bfb3
```

**SEARCH uniqueness (how checked):** Grep with line numbers on this tree, plus full reads of each target region.
- `crew_enrollment.py`: `and memory are never touched` 19; `ENROLLMENT_REASON = ` 42; `tools_granted: tuple[str, ...] = ()` 57; `async def _has_skills` 79; `if await self._acm.get_commissioning_record(agent.id) is not None:` 177; `initiated_by=ENROLLMENT_INITIATED_BY, reason=reason,` 316; `async def _log_commissioning(` 329, one each.
- `acm.py`: `    initiated_by: str` / `    reason: str` / `    timestamp: float` in that order only at 73-75 (59-61 has reason before initiated_by); `_COMMISSIONING_HISTORY_SQL = (` 118; `executescript(_SCHEMA)` 155; `timestamp FROM commissioning_records WHERE` 212; `initiated_by=row[6]` 221; `record an agent's commissioning once` 343; `records again.` 352; `INSERT OR IGNORE INTO commissioning_records` 360, one each.
- `skill_framework.py`: `experimental_design` 944 and `async def register_builtins` 1118, one each.
- `skills.yaml`: `# Qualification paths` once; `vulnerability_analysis` once; `access_control` once.
- `storage_declarations.py:218-219` once.
- `doctor/checks/__init__.py:19-20` once.
- Test files: `test_ontology_skills.py:55` once; the T-B1 block 185-197 once.
- The M2 SEARCHes anchor on text §7.1, §7.5 and §7.6 create, each once.

## Absence Verified (2026-10-22)

```
AV1 CLAIM: check_decay has no production caller (guard 2)
    RUN:   Grep "check_decay|decay_rate_days" src/
    FOUND: skill_framework.py:1439 (def) and :1456 (its default); no call site
    HOLDS: yes
AV2 CLAIM: none of the 30 new ids is defined anywhere in src (no definition collision)
    RUN:   Grep '"(architecture_review|...|limited_duty_planning)"' src/  (all 30 ids)
    FOUND: agents/science/systems_analyst.py:60,75 (intent name emergence_analysis); creative/skills_registry.py:64 (a creative
           skill id technical_writing); holodeck/team_simulations.py:144; sop/builtin/research_consultation.yaml:22 (a
           qualification-test name); cognitive/thought_store.py:26 (an enum value). None is a SkillDefinition
    HOLDS: yes (the live skills.db is checked in §16 L1)
AV3 CLAIM: only acm.py, the BF-906 doctor check and the store declaration name commissioning_records in src
    RUN:   Grep "commissioning_records" src/probos
    FOUND: acm.py:105,212,360; doctor/checks/crew_enrollment_check.py:30 (agent_id only); storage_declarations.py:216,226
    HOLDS: yes
AV4 CLAIM: no test reads crew_enrollment.py, commissioning.py or skills.yaml as source text beyond the listed readers
    RUN:   Grep "skills\.yaml|role_templates|crew_enrollment\.py|commissioning\.py|get_role_template" tests/
    FOUND: test_ontology_skills.py:55 (count, §7.14), test_bf906_crew_enrollment_boot.py:188 (§7.15), test_science_team.py:322-332
           (keys present), stubs in test_ad1009/test_ad889/test_bf906/test_bf244/test_ontology_callsign_sync
    HOLDS: yes
AV5 CLAIM: no production code calls evaluate_qualification or proficiency_promotion_eligibility (role_skills consumers latent)
    RUN:   Grep "proficiency_promotion_eligibility\(|evaluate_qualification" src/
    FOUND: earned_agency.py:169 (def), skill_framework.py:1708 (def)
    HOLDS: yes
AV6 CLAIM: no new helper or source name is in an AD-1343 census set
    RUN:   Read tests/fixtures/ad1343_seam_census.py:25-39
    FOUND: STOP {active_stop, tool_refusal, refusal, refuse_new_run}; GUARD + {standing_stop, _stopped}; RECORDED adds invoke, issue_stop,
           lift_stop, WorkItemAgenticExecutor, CrewAssignmentResolver, CrewSessionFinalizer, complete, CrewRecoveryTransientError, finalize, run_crew_task
    HOLDS: yes (template_fingerprint, _recommission_if_template_changed, builtin_skill_definitions, unregistered_template_skills,
           crew_posts_without_template, _add_template_fingerprint_column, crew_world, boot_enroller, edit_skills_yaml, skill_records,
           recommission_rows, _shipped_loader, _legacy_role_skills, _context, _tree)
AV7 CLAIM: no src module imports probos.doctor (the new audit lives outside it)
    RUN:   Read tests/test_ad1137_doctor.py:1415-1437 (the rule); the new role_template_audit.py imports only collections.abc and typing
    HOLDS: yes
```

**A1 verification and absences (2026-10-23, candidate `22b179c5`, tree `4bb80970`):**

```text
Read src/probos/crew_enrollment.py:190-468   __init__ 193-213 (no lock); enroll 215-227 unserialized; _commission all-PCC check 334-343; re-commission accepts any non-empty skills_acquired 424-429
Read src/probos/commissioning.py:20-107      snapshot 52-63; base step swallowed at DEBUG 66-73; template step 79-97 (ValueError skipped); profile 100-107
grep skill_framework.py "async def acquire_skill" 1358; fresh record (exercise_count=0) 1383-1391; _upsert_record 1392; def _upsert_record 1738; INSERT OR REPLACE 1742
grep acm.py "_write_lock"                    154 (created in __init__), 175, 253, 317, 378
Read src/probos/doctor/runner.py:184-205     a raising check is rendered FAIL
Read src/probos/ontology/loader.py:224-233   s["min_proficiency"] raises on a missing key
grep pyproject.toml requires-python          >=3.12 (asyncio.Lock binds to the running loop on first use)
grep src "\bLock\s*[:=]"                     avatars/telemetry_history.py:58 and others (the precheck resolves Lock)
grep src "\bEvent\s*[:=]"                    avatars/events.py:45 and others (the precheck resolves Event)
CLAIM: only the enroller passes preserve_existing=True
RUN:   rg -n "preserve_existing=True" src/
FOUND: crew_enrollment.py:321, :382 (docstring), :416
HOLDS: yes; the enroller's lock covers every preserving caller
CLAIM: nothing reachable while the lock is held calls the enroller
RUN:   rg -n "enroll_joining|enroll_wired_crew|\.enroll\(|CrewEnrollmentService\(" src/ ; rg -n "\.wire_agent\(|on_agent_spawned\(" src/
FOUND: crew_enrollment.py:231, :238; startup/crew_enrollment.py:26, :36, :39; runtime.py:2623; substrate/pool.py:88 (ontology/service.py:169 and startup/communication.py:796 are the department ontology's wire_agent)
HOLDS: yes; the enroller is reached from onboarding's wire_agent and the boot pass only
CLAIM: no test or script pins crew_enrollment.py's source or the enroller's attributes
RUN:   rg -n "crew_enrollment\.py|getsource\((crew_enrollment|CrewEnrollmentService)|CrewEnrollmentService\.__init__|_enroll_lock|signature\(CrewEnrollment" tests/ ; rg -n "crew_enrollment|CrewEnrollmentService" scripts/
FOUND: none; none
CLAIM: no enroller is shared across event loops in the BF-906/907/908 tests
RUN:   rg -n 'scope="(module|session|class)"' tests/test_bf90[678]*.py
FOUND: none
```

## 12. Deterministic gate checks, resolved up front

| Check | Result |
|---|---|
| Phantom precheck, pattern 3 (`Name(`) | Capitalised calls are ProbOS classes, or classes this contract defines with `class` (`CrewAgent`, `CrewWorld`). `SimpleNamespace` is imported as `_Namespace`. The only builtin exception called is `OSError(`. `_RecommissionContext(` and `_RoleTemplateCheck(` begin with an underscore. |
| Kwarg and field checks | Calls that pass a kwarg this contract adds appear only in blocks that start mid-call (§7.2 pair 5, §7.3 pair 7), or with a parenthesised argument (`tools=()`). `CrewEnrollment` is extended through `replace(...)`. No test constructs a `CommissioningRecord`. The bare name `unchanged` is never reused in a test (pattern B types it as `CrewEnrollment`). |
| Pattern B | `skill_registry`/`before_registry`/`after_registry`/`bare_registry`/`full_registry` (SkillRegistry), `*_service` (AgentSkillService), `acm`, `seeded`/`probe`/`tool_registry` (ToolRegistry), `permission_store`, `loader`, `ontology`, `enroller` are each bound to one class and call only that class's methods. No `unlink(missing_ok=` is used. |
| AD-1343 census | AV6. |
| Architecture checker | `AgentCapitalService` stays at 15 methods, span about 456 of 500. `CrewEnrollmentService` gains one method and, in A1, one private lock attribute: 11 methods and a body of about 300 lines, under the 15 and 500 triggers. No layer import upward: `role_template_audit` imports nothing from probos; the doctor check imports it lazily. |
| Store registry | No `CREATE TABLE` is added (a column via `ALTER TABLE`); `check_store_registry --check` is unaffected. The `acm.agent-capital` retention note is updated. |
| Doctor import rule | No `src` module imports `probos.doctor` (AV7). |
| Config | No new field. |
| Child process | D3 runs `sys.executable` with `PYTHONPATH` set to this tree and asserts `probos.__file__` lies under it. No pid is compared. |
| Ledger | Regenerated in M2's commit. |
| Sizes | Production: about +120 lines (M1), +20 for A1, and +40 (M2). Tests: about 470 (M1, with the fixture), +100 for A1's E5 and E6, and 150 (M2). |

## 13. Prior Art and Blind Spots

- **Bug fix; the standing rule applies.** `docs/research/reference-projects.md` was not reviewed. Internal precedent: BF-906's contract predicted the Yeoman and Training Officer gap (`prompts/bf-906-crew-enrollment-boot-order.md:1305`). The issues' own decisions on register-not-rename and preserve-existing re-commission are adopted. The Captain's "optimize, never delete" rule is honoured: a skill dropped from a template keeps its record.
- **External, one search.** Deriving a change trigger from a content hash of the configuration is the Helm `checksum/config` annotation pattern. Its documented limit is that it reacts only to changes in the hashed source ([Stakater: Reloader vs checksum annotations](https://docs.stakater.com/reloader/1.4/concepts/comparisons/reloader-vs-checksum-annotations.html)). Adopted: the fingerprint hashes exactly what the chain reads (post and required skills with floors). Changes outside it (optional skills, the legacy dict) deliberately do not trigger.
- **Blind spot absorbed.** `register_builtins` writes with `INSERT OR REPLACE`, so a Captain-designed definition already holding one of the 30 ids would be overwritten at boot. §16 L1 makes that a hard stop.
- **Blind spot absorbed.** A stateless trigger would never settle for prerequisite-blocked skills (`performance_optimization`), so the fingerprint is stored.
- **Blind spot absorbed.** The tag fallback is a substring match, so any new domain is a new question. Guard 1 is satisfied by construction (legacy domains only) and proved by G3.
- **Blind spot absorbed (A1, review round 1).** `IS NOT ?` makes a repeated re-commission write no second record or history row, but it does not protect skill records: the chain snapshots the profile, then writes each missing skill as a fresh record, so two overlapping enrollments of one agent could reset a record the first had advanced. `enroll` is serialized per enroller. Production reach was not shown (a pool serializes its own wirings, and the join hook is installed after the boot pass), but AD-1273 requires a double-wire to be harmless.
- **Blind spot absorbed (A1).** AD-889 swallows a failed base step at DEBUG, so a re-commission is held to the all-PCC rule a first commissioning keeps.
- **Blind spot disclosed.** Raising the floor of a skill the agent already holds is a fingerprint change, but it raises nothing (records are preserved). The history row says so.
- **Considered, deferred.** Fingerprinting the legacy `ROLE_SKILL_TEMPLATES` too; data-driven definitions in `skills.yaml`; a startup audit WARNING.

## 14. Diff Reviewer: properties to verify

1. No existing skill record is rewritten by a re-commission, serial or overlapping. Every pre-existing record keeps its proficiency, exercise count, timestamps, source and history (E1, B4). Only missing skills are inserted, and an overlapping enrollment of the same agent inserts nothing (E6).
2. A re-commission cannot grant a tool. `_RecommissionContext` exposes no `tool_registry`, `tool_permission_store` or `skill_registry`, and `commissioning.py:112-120` therefore skips step 3. Birth commissioning still passes the runtime unchanged.
3. The fingerprint is written only after the chain returned, read a profile and left every PCC held, together with its history row in one commit, rolled back together. A failure leaves the record and history unchanged, logs one ERROR naming its cause, and the next pass retries (E4, E5).
4. An unchanged fingerprint calls nothing, and a second pass writes nothing (E1, E2). A NULL fingerprint is re-commissioned exactly once.
5. Every new definition: ROLE; no prerequisite, preferred tool, composite or synergy; `decay_rate_days == 14`; a legacy domain; ids unique across `builtin_skill_definitions()`.
6. `register_builtins` registers exactly `builtin_skill_definitions()`, and the doctor uses the same list.
7. The migration is additive and idempotent, works through the ConnectionFactory connection (an AsyncMock as well), and runs before `start`'s commit.
8. `AgentCapitalService` still has 15 direct methods. No private attribute is read across a module boundary.
9. The doctor check writes nothing; each finding is a WARN, never a FAIL. An ontology the loader cannot read raises, which the doctor runner reports as FAIL, as for any check (F-347 on #1523; the shipped ontology loads, D1). It is registered once, after `token_accounting`.
10. **The consumer that must accept the change:** `CrewEnrollmentService.enroll_wired_crew` and BF-906's tests. The pass log line is byte-identical. `CrewEnrollment` equality at its defaults holds (`test_bf906_acm_commissioning.py:1026`). T-B1, T-B3 and T-B4 hold on a fresh boot.
11. The two updated tests record why inline; no test is deleted.
12. **Serialization (A1).** `CrewEnrollmentService.enroll` holds the private `_enroll_lock` (one `asyncio.Lock` per enroller, created in `__init__`) from the onboarding step through the recording, covering `_commission` and the re-commission; the source and crew checks stay outside it. It is always taken outside ACM's `_write_lock`, and nothing it covers calls the enroller. An overlapping enrollment of one agent waits and returns `commissioned=False, recommissioned=False` (E6). `__init__`'s parameters, `enroll`'s signature and `CrewEnrollment` are unchanged.

## 15. Acceptance criteria

- §7.1 to §7.16 and §8 applied in milestone order. Each milestone's focused gate passes at `-n 0`; `gen_ad_ledger.py --check` reports current; the precheck is clean.
- G1, G5, E1, B1, B2 and B4 fail on the pre-change tree because of the behaviour itself. Every new test fails on the pre-change tree.
- All 24 §10 rows (M1-R1 to M1-R20, M2-R1 to M2-R4) are killed by the named tests; E5 and E6 fail on the round-1 candidate because of the behaviour (§6). The campaign of record is recorded in the docs-only commit.
- After the first live boot, §16's post-boot checks hold.
- The broad gate runs once for the batch, by the orchestrator, with `--receipt`. One PR closes #1625 and #1623.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Live checks for the orchestrator (read-only, `%LOCALAPPDATA%\ProbOS\data`, SQLite `mode=ro`; never the repo's `data/`)

**Before the build:**
- **L1 (hard stop).** `skills.db`: `SELECT skill_id, category, origin FROM skill_definitions WHERE skill_id IN (<the 30 ids of §7.1 and §7.11>)`. Expect 0 rows. Any row is a Captain-designed (or otherwise existing) definition that `register_builtins` would overwrite. If there is one, stop and escalate.
- **L2.** `skills.db`: snapshot `SELECT agent_id, skill_id, proficiency, exercise_count, acquired_at, last_exercised, acquisition_source, suspended, assessment_history FROM agent_skills ORDER BY agent_id, skill_id` and store it outside the repo. Report, per crew member, the orphan ids among the 22 and their proficiencies (expected: 2 to 4 each for the 14 templated crew, at template floors or above; none for Yeo and Tucker). Confirm no record exists for any of the 8 M2 ids.
- **L3.** `acm.db`:
  - `SELECT agent_id, agent_type, role_template FROM commissioning_records` (16 rows; `yeoman` and `training_officer` NULL);
  - `PRAGMA table_info(commissioning_records)` (no `template_fingerprint`);
  - per-agent count of `lifecycle_transitions` rows with `from_state = to_state` (expect 1);
  - any crew member in state `decommissioned`.
- **L4.** `tool_permissions.db`: `SELECT COUNT(*) FROM tool_access_grants` (expect 1) and the count of rows with `reason='commission'` (expect 0).
- **L5.** `GET /api/tools`: no tag contains `security`, `engineering`, `medical`, `science` or `operations` (case-insensitive substring).

**After the first boot on the merged code:**
- L2 again: every pre-existing row identical; new rows only for Yeo (4) and Tucker (4).
- L3 again: every record has a non-NULL fingerprint; `role_template` is `yeoman` and `chief_training` for the two; each crew member has exactly one more same-state row whose reason contains `re-commissioned`.
- L4 unchanged.
- `skill_definitions` holds 83 rows plus any Captain-created ones.
- `probos doctor` shows `role_templates` OK.
- The roster's `skill_count` is 13 for Yeo and Tucker and unchanged for the other 14; `tool_count` is unchanged.
