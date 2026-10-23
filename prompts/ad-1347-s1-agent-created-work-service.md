# AD-1347 S1: the Ship's Computer service that owns agent-created work (self-tasks, chief assignments, department requests), default off, with no chain wiring

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-22

**Status:** build-ready after BF-912 (#1615) merges. Slice 1 of 4 of #1627; it does not close the issue. **Tier HIGH**: governance, because crew create and route work to each other. **AD number:** AD-1347, from `scripts/ad_ceiling.py` (ceiling AD-1347 from issue titles, next AD-1348); no new number is allocated. **Base:** `88f0e5b8` (AD-1341 S1 and BF-916, PR #1628) on `origin/main` `80456da2`. BF-912 touches only `cognitive/decomposer.py`, one new test and the three trackers. Every code SEARCH below anchors on text; the tracker SEARCHes anchor on lines BF-912 does not change.

**Tests:** M1 `tests/test_ad1347_s1_agent_work.py`, 31 functions and 57 cases (A3: tests 29 to 31, and test 28 asks the off opener with every collaborator). M2 `tests/test_ad1347_s1_wiring.py`, 2 functions (real boots; A3: the Ship's Archive is off and its path resolver is spied). Updated pins:
- `tests/test_ad1343_agent_stop.py` (T8, the seam set);
- `tests/fixtures/ad1343_seam_registry.py` (three rows);
- `tests/test_ad1270e1_config_facade.py` (six counts);
- `tests/test_ad1152_agentic_correlation.py` (the golden's popped section);
- `docs/development/config-profiles.yaml` census `default_false` (§7.10 pair 2, Amendment A1);
- `tests/test_ad1270e2i_agentic_models.py` (the true-leaf set, §7.14b, A1);
- `docs/development/config-reference.md` (generated, §7.14c, A1; read by `tests/test_config_reference_current.py`).
`tests/test_layer_boundaries.py` is not edited: §7.13 imports nothing from the consensus layer (A1).

**Line endings:** the working copies are CRLF (`core.autocrlf=true`). The SEARCH blocks here are LF; match and write with each file's own endings. New files are written LF.

**Not built here (later slices):** S2 the chain's action tags; S3 claim, execution, activation notice, report-back and notice delivery; S4 the QUERY lookup. Two requirements A3 hands on: S3 asks `claim_allowed`'s question again, with the stop at `SEAM_AGENTIC_RUN`, before it executes a claimed request, because a same-owner claim replay is a receipt and is not re-gated, and S3 decides what a claimant that lost eligibility after its claim does with the item (release, decline or the TTL); S2's tag parser treats the `ValueError` an `AgentWorkOrigin` raises as a refused tag (F2, F3).

**Mechanical repairs by the orchestrator (2026-10-23, so that the staged contract passes `scripts/phantom-api-precheck.ps1`; no decision changed):** (1) section 7.14's `_schema` helper reads `coalesce(sql, '')` in lower case (SQLite function names are case-insensitive; the capitalised spelling was read as a class call); (2) section 12's first bullet names the constructs it avoids without parentheses; (3) not a precheck repair: section 10's heading said 31 rows while its table holds 33 (A1 to C2, found when the campaign table was derived), so the heading now says 33 and no row changed.

**Amendment A1 (`claude-architect`, 2026-10-22; the oracle's stale pins at the M1 build `3496b849`):** the first hunt missed four pinned surfaces: the profile census header (§7.10 pair 2), AD-1270's true-leaf set (§7.14b), the layer-boundary scan (§7.13 types the trust parameter with `AgentIdentityTrust`, so nothing is imported from the consensus layer) and the generated config reference (§7.14c, also pinned by `tests/test_config_reference_current.py`). It also makes §10's W3 and W4 Mutate-to cells literal. No decision D1 to D14 changed.

**Amendment A2 (`claude-architect`, 2026-10-22; the build's mutation campaign on tree `49ded1b8`, at `2516c20b`):** 32 of §10's 33 rows were killed; row R1 (`if self.config.agent_work.enabled:` to `if True:` in `runtime.py`) survived test W1, because the opener's own guard (`if not config.enabled: return None`) leaves the same outcomes W1 asserted (`agent_work` None, no `agent_work_` table). Property 11 was stated but not pinned. A2 makes test W1 count the runtime's calls to the opener through a spy on the module attribute `probos.agent_work.open_agent_work_service` (the runtime imports that name inside its guarded block, so the boot reads the replaced attribute), installed with the `monkeypatch` fixture and delegating to the real opener: none while off, one while on. Production code is unchanged; the test keeps its name. It also makes §10's R1 cell name test W1 by file (§10 has a mutation row also called W1). The other 32 Killed-by cells were checked by reading and each named test kills its row; none changed. No decision D1 to D14 and nothing in A1 changed. Rerun after the build: row R1 and its baseline.

**Amendment A3 (`claude-architect`, 2026-10-23; review round 1 on the frozen candidate `8ebf10f2`, findings F1 to F4):** (F1) the wiring boots used AD-1346's `_config`, which leaves the Ship's Archive on with an empty `db_path`, so each boot opened and migrated the live vessel's `%LOCALAPPDATA%\ProbOS\archive\archive.db`. `_boot_config` now turns the archive off, and both boots take the `archive_resolutions` fixture, a spy on `probos.config.resolve_archive_db_path` that answers with a path under `tmp_path` and must stay empty. (F2) a same-owner replay returns before readiness, so the gate is not asked. That is AD-1187's receipt contract (`test_claim_replay_precedes_readiness_capacity_and_publication`: a trust requirement, TTL or dependency changed after the claim does not refuse the replay), and the replay acquires nothing, so property 6 and the docstrings now say "every new claim"; test 29 pins the receipt and row W7 is the gated replay as a mutant. No production change for F2. (F3) one helper, `_encodable`, makes `_text`, `_identifier` and the origin's id check refuse a str that UTF-8 cannot encode (a JSON-decoded lone surrogate): every text and id input of both create methods is `invalid_request` before any lookup or write, and an origin id raises the origin's own `agent_work_origin_id_invalid` (tests 30 and 31; rows A27 to A30). (F4) test 28 asks the off opener with every collaborator and spies the store's schema and gate methods (row R4). Tests 28 and 29 pass on the frozen candidate by design; their red run is rows R4 and W7. No decision D1 to D14 and nothing in A1 or A2 changed; §10 has 39 rows. Rerun after the build: every `agent_work.py` row (A1 to A30, R2, R3, R4), W7, and R1 (its test changed), each with its baseline.

---

## 0. Premise: what is present on this tree

| Clause | State | Evidence (this tree) |
|---|---|---|
| AD-1187 excludes room-linked or child items from pull by top-level metadata key and by `parent_id` | present | `workforce.py:10952-10964` (`_standalone_pull_item`) |
| Department publication needs exactly `{version, scope, department}` | present | `workforce.py:10967-10981` (`_pull_visible`), SQL `:11044-11055` |
| The store already expires TTL items in its own tick | present | `workforce.py:11745-11796` (`_tick_loop`, `_expire_ttl_items`, `transition_work_item(..., "cancelled", source="ttl_expiry")`); `_ready_for_pull` refuses an expired item before the sweep, `:11010-11013` |
| A work item may be created already assigned, without a booking (AD-1165 precedent) | present | `cognitive/turn_promotion.py:1006-1018` (`create_work_item(assigned_to=agent_id, created_by="captain", ...)`) |
| Claim through the tool passes the stop at `SEAM_TOOL`; the HXI's legacy route does not | present | `tools/registry.py:388-395` (`tool_refusal` before lookup); `tools/work_item_pull_tool.py:367`; `routers/workforce.py:398` |
| The pull authority resolves department and rank through `resolve_agentic_identity` and checks permission with `agent_types` | present | `runtime.py:4170-4249` |
| `resolve_permission` applies department scope, `restricted_to`, the rank table and the Captain's grants and restrictions | present | `tools/registry.py:292-334` |
| `event_log_query` is registered only when `agentic_dispatch.orchestrator_enabled` is on; ensign `none`, lieutenant and above `read`; engineering, science, security | present | `startup/communication.py:46-81`, `:833-838` |
| One identity facade resolves slot ids, UUIDs and DIDs, and fails closed | present | `identity_service.py:79-95` (`resolve` returns None); `identity.py:804-827` (`resolve_slot_id`) |
| Every stop check is pinned by the census | present | `tests/test_ad1343_stop_seam_inventory.py:66-81`; `tests/fixtures/ad1343_seam_registry.py:21-37, 120-123, 157-220` |
| `--full` deletes `workforce.db`; the default reset keeps it | present | `__main__.py:2669-2676` (tier 3 `files: ["ward_room.db", "workforce.db"]`); tier 2 `:2650-2668` does not list it |

## 1. Problem

Crew think through the cognitive chain. When a thought needs a fact only a governed tool can read, their only route today is to ask the Captain (#1627, live evidence 2026-10-22: Reed, Forge, Sentinel, Chapel and Ezri). The work board can already publish department-scoped work and govern its claim (AD-1187), but nothing lets an agent create durable work for itself, or ask a colleague who holds a tool it lacks. Agent-originated creation today is AD-845's Yeo `[CREATE_TASK]` and AD-1165's promotion, and both stamp `created_by="captain"` (`reply_pipeline.py:2213`, `turn_promotion.py:1011`).

## 2. Solution overview

A Ship's Computer service, `AgentWorkService`, creates three kinds of ordinary `WorkItem`:
- **self**: assigned to its creator;
- **assignment**: from a chief to a member of its own department;
- **request**: unassigned, published to one department that holds the named tool.

It enforces the chain-of-command rules, per-member tool eligibility, the Captain's stop, depth, rate, three open-item caps and dedup with watchers. Provenance goes under `metadata["agent_work"]`.

Through a fail-closed claim gate it also makes discovery and every new claim of a request (tool path and legacy path) ask the same eligibility question again; a same-owner replay of a claim already persisted is AD-1187's receipt and is not asked again (A3). Expiry stays with the store's sweep. Notices get a claim-before-send record. The runtime builds the service only when enabled. Nothing calls it in S1.

## 3. Decisions

**D1 (shape and home).** `src/probos/agent_work.py`:
- the contract types: `AgentWorkOrigin`, `CrewMember`, `AgentWorkRecord`, `AgentWorkCreated`, `AgentWorkRefusal`, `AgentWorkNotice`;
- four narrow interfaces: `AgentWorkStore`, `ToolPermissionView`, `IdentityResolver`, `CrewDirectory`;
- `AgentWorkService`, 13 methods, under the 15-method and 500-line SRP trigger in `scripts/check_architecture_principles.py:187-188`;
- `open_agent_work_service`, the one builder.

`src/probos/cognitive/crew_directory.py` holds `RuntimeCrewDirectory`, the live crew read through `resolve_agentic_identity` (the same resolver the pull authority uses) and AD-865's chief lookup. That lookup is moved to module functions `find_chief_post` and `resolve_post_agent` in `crew_delegation.py`, and `CrewDelegator` delegates to them (DRY).

The runtime builds the service after the BF-679 block of Phase 7, where the work store, tool registry, stop gate and ontology all exist, into `runtime.agent_work`. Shutdown releases it with the work store.

Ranked:
- **A** (chosen) as above.
- **B** methods on `WorkItemStore` (baselined SRP debt).
- **C** build inside `init_communication`, which has no stop gate.
- **D** a cognitive-layer service.

**D2 (authority).**
- `create_self_task(requester, ...)` makes an item assigned to the requester's slot.
- `request_work(requester, ..., tool_id, assignee=None, department=None)`:
  1. A named assignee who is the requester becomes a self-task.
  2. A named assignee in the requester's department whose `chief_slot_id` is the requester becomes an **assignment**, refused when the assignee is stopped or cannot use the tool.
  3. Any other named assignee becomes a **request** with `converted=True`, recording `assignee_requested`.
  4. A requester who holds the tool is refused with `requester_holds_tool`.
- Department chosen for a request: the explicit `department`, refused when none of its members is eligible; otherwise the converted assignee's department if eligible; otherwise the department with the most eligible members, ties broken by name.
- `notify` lists the eligible members of that department, for S3's activation notice.
- Depth is read from the `spawned_from` item's stored record: 1 with none or with a Captain parent, parent + 1 otherwise. Above `max_depth` (2) it is refused. An unknown parent is refused (`parent_unknown`).

**D3 (eligibility).** `_holds_tool(member, tool)` is `ToolRegistry.check_permission(member.slot_id, tool, READ, agent_department, agent_rank, agent_types=[agent_type])`. It is asked:
- at creation;
- in `eligible_members`, which skips stopped members (`standing_stop`);
- in `claim_allowed`, the store gate called inside `_ready_for_pull` for every item carrying agent-work provenance, on both the tool and the legacy claim path.

An unregistered or disabled tool returns `tool_unavailable` (premise 4). A registered tool nobody may use, or whose eligible members are all stopped, returns `no_eligible_member`.

**D4 (configuration and guards).** `AgentWorkConfig` in `config.py`:

| Field | Default | Bounds |
|---|---|---|
| `enabled` | False | — |
| `max_open_per_agent` | 3 | 1–50 |
| `max_open_per_department` | 8 | 1–200 |
| `max_open_ship` | 24 | 1–500 |
| `max_created_per_agent_per_hour` | 6 | 1–100 |
| `ttl_seconds` | 86 400 | 60–604 800 |
| `max_depth` | 2 | 1–5 |

A validator refuses a per-agent or per-department cap above the ship cap. Units are work items: "open" is not done, cancelled or failed; the rate counts rows created in the trailing 3600 s, whatever their status.

Order of checks: input, requester, stop, depth, authority and eligibility, then under one lock: dedup, rate, agent cap, department cap, ship cap, and the single insert. A page of `SCAN_LIMIT` (2000) rows is refused as `ship_cap_reached`, never counted short. Dedup applies to requests: a match returns the open item. A different requester becomes a watcher, idempotent; the original requester is never added as a watcher. A refused create returns `AgentWorkRefusal(code, detail)`; the codes are the module's `REFUSAL_CODES`.

**D5 (persistence).** No new column. Requests also carry `agent_pull` with department scope, which AD-1187 requires to publish them. The two new tables are created by `WorkItemStore.ensure_agent_work_schema`, which only the opener calls:
- `agent_work_watchers`, primary key `(work_item_id, agent_id)`;
- `agent_work_notices`, primary key `(work_item_id, recipient, kind)`.

`workforce.py` is the declared owner module of `workforce.work-items` (`storage_declarations.py:19-27`), so `check_store_registry --check` gains no baseline row (rule 11 applies only to baselined undeclared modules: Absence AV4). The declaration's retention note gains one sentence (§7.6).

Reset: tier 3 (`--full`) deletes `workforce.db` with every request, watcher and notice. The default tier keeps them; the TTL bounds that to 24 h, and `requester_sovereign_id` lets S3 recognise a slot now held by a new identity. AD-1341 S1's archive promotion does not read `workforce.db` (Absence AV3); work items are coordination, not culture.

**D6 (seams).**
- `agent_stop.SEAM_AGENT_WORK = "agent_work"`: one counted refusal per refused create, in `AgentWorkService._requester_stop`.
- Claim: `SEAM_TOOL`, already. Execution: `SEAM_AGENTIC_RUN`, in S3.
- Candidate questions (assignee, gate, eligible set): `standing_stop` in `AgentWorkService._stopped_now`, which counts nothing.

Pinned updates, each with its reason inline:
- `tests/test_ad1343_agent_stop.py` T8 (the literal seam set);
- `ad1343_seam_registry.STOP_CHECK_SITES`, `STANDING_STOP_SITES` and `SEAM_INDEX`.

`admission/taxonomy.py` widens automatically, because its `SEAMS` is the stop's set plus its own, and `tests/test_ad1346_admission_service.py:177-180` reads `agent_stop.SEAMS`, not a literal. S1 calls no `decide` and adds no work kind (register R5). `S1_SCOPE` is not edited, so the stop routes' bodies stay byte-identical while the feature is unreachable (register R1).

**D7 (provenance).** `created_by` is the slot id that `IdentityService.resolve` gives for the requester; when it gives None the create is refused (`requester_unresolved`). There is never a `"captain"` fallback.

`metadata["agent_work"]` holds: `version`, `kind`, `requester`, `requester_sovereign_id`, `origin` (`channel`, `thread_id`, `post_id`), `reason`, `depth`, `department`, `tool_id`, `dedup_key`, `spawned_from` and `assignee_requested`.

The origin sits under the nested key on purpose: a top-level `thread_id` or a `parent_id` would make `_standalone_pull_item` refuse the item, and the request would reach nobody. A back-reference to the asking conversation is not room ownership in AD-1187's sense: no room scopes, owns or receives the work, and the origin only says where S3 reports.

**D8 (one owner for expiry, idempotent notices).**
- Every agent-created item carries `ttl_seconds`; the store's tick is the only expiry owner. The service has no loop and calls no status transition (test 23).
- `terminal_notices_due` lists the (item, recipient) pairs not yet claimed, for the requester and every watcher. A watcher is a drop point for a correct result, so it is always listed.
- `claim_notice` returns True exactly once per pair, across restarts.
- The outcome is `expired` when a cancelled item's `updated_at` is at or past its deadline, otherwise its status.
- A claimed request keeps its creation-time TTL (register R2).

**D9 (claim gate).** `WorkItemStore.set_agent_work_claim_gate`. `_ready_for_pull` adds `_agent_work_claimable`:
- an item without the provenance key is unaffected;
- with the key and no gate, it is not ready;
- with a gate, only the gate's `True` is ready, and an exception counts as not ready, with a warning.

**D10 (byte-identical when off: what is compared, and on which path).**
1. Default-config path: `test_ad1152`'s whole-`SystemConfig()` golden, with the new `agent_work` section popped at its asserted defaults (§7.11).
2. Boot path: test W1 boots a real runtime off and on. Off has `runtime.agent_work is None`, no `agent_work_` table and no call to the opener; on calls the opener once (W1's spy, A2). On minus off is exactly the two tables.
3. Store path: test 13 (no gate means every plain item is discoverable as before) and test 28 (the opener while off leaves `sqlite_master` (type, name, sql) identical).
4. Stop routes: `S1_SCOPE` is not edited (Absence AV6).

## 4. Milestones

| Milestone | Opens at | Content | Commit |
|---|---|---|---|
| **M1** | §7.1 | The seam and its pins; the shared chief lookup; the store's agent-work methods and gate; the declaration note; the config model with its facade, profile (classification and census) and golden updates, the true-leaf pin and the regenerated config reference; the service; the directory (trust typed by protocol); the M1 tests | one |
| **M2** | §7.15 | Runtime wiring and shutdown release; the boot tests | one |
| Trackers | §8 | — | M2's commit or a docs commit |

About 150 tool calls each at most. BF-912 lands first.

## 5. Consumers of every value this changes

| Value | Consumer | Accepts it because |
|---|---|---|
| `agent_stop.SEAMS` gains `"agent_work"` | `AgentStopService.refusal` (`agent_stop.py:381`); `admission/taxonomy.SEAMS`; `admission/record.py:61`; census tests | membership check only; taxonomy unions it; T8 and the registry are updated here |
| `metadata["agent_work"]` | `_standalone_pull_item` (not a forbidden key); `_pull_visible` (reads only `agent_pull`); `_reject_reserved_metadata` (`workforce.py:1682-1696`, not reserved); `_agent_work_claimable` (new); the board's `to_dict` (verbatim) | |
| `metadata["agent_pull"]` on requests | `_pull_visible` and the SQL filter `:11044-11055` | exactly three keys |
| `created_by` = slot | `default_value_provenance_for_creator` (`workforce.py:7657`) | only when a value or stakes field is supplied, and the service supplies none |
| `ttl_seconds` | `_expire_ttl_items`; `_ready_for_pull` | |
| `assigned_to` set at insert | `_pull_candidates` (`assigned_to IS NULL`); AD-1165 precedent | |
| the store gate | `_ready_for_pull` (`list_claimable_work_items`, `claim_work_item` on both paths) | synchronous, no I/O |
| `runtime.agent_work` | S2, S3 (later); `startup/shutdown.py` release | |
| `SystemConfig.agent_work` | the runtime build block; the config facade baseline; `config-profiles.yaml` (the classification and the census `default_false`, `test_ad1185_config_profiles.py:859`); the test_ad1152 golden; the generated `config-reference.md` (`gen_config_reference.py --check`, `test_config_reference_current.py:41`); AD-1270's true-leaf pin (`test_ad1270e2i_agentic_models.py:526`) | each is updated or regenerated in M1 (§7.8 to §7.11, §7.14b, §7.14c) |
| `RuntimeCrewDirectory`'s `trust_network` is typed `AgentIdentityTrust` (A1) | `resolve_agentic_identity` (`agentic_dispatch.py:433`, the same protocol); the runtime's and the tests' `TrustNetwork` (`get_score`, `consensus/trust.py:1017`); `tests/test_layer_boundaries.py` (an AST scan that also counts `TYPE_CHECKING` imports) | structural protocol; a same-layer import; precedents `crew_assignment.py:33`, `self_telemetry_domains.py:15` |

## 6. Tests

**M1, `tests/test_ad1347_s1_agent_work.py`.** Real store, registry, permission store, stop service, ontology, agent registry and trust network. Identity is the one stand-in (`_SlotIdentities`, `IdentityService.resolve`'s contract); W2 runs the real facade. On today's tree every test here fails at import (`probos.agent_work` is absent).

| # | Test | Acceptance or premise |
|---|---|---|
| 1 | `test_premise_the_fixture_is_the_production_shape` | — |
| 2 | `test_a_self_task_is_assigned_to_its_creator_with_nested_provenance` | 6 |
| 3 | `test_an_unresolved_requester_is_refused_and_nothing_is_written` (3 cases) | premise 8 |
| 4 | `test_a_self_task_naming_a_tool_needs_its_creator_to_hold_it` | 3 |
| 5 | `test_a_chief_assigns_within_its_department` | 3 |
| 6 | `test_a_peer_or_cross_department_assignment_becomes_a_request` | 3: a non-chief cannot assign |
| 7 | `test_a_request_goes_to_the_department_with_most_eligible_members_unless_one_is_named` | — |
| 8 | `test_eligibility_is_the_registrys_own_answer_for_each_member` | premise 3 |
| 9 | `test_an_unregistered_tool_or_a_tool_nobody_may_use_is_refused_at_creation` | premise 4 |
| 10 | `test_request_is_created_published_and_claimed_by_an_eligible_member` | the S1 half of 2; 3 (ineligible claim). **S2 and S3 extend this test into acceptance 2's full chain.** |
| 11 | `test_a_request_with_a_top_level_thread_id_would_reach_nobody` | premise 6 |
| 12 | `test_the_legacy_claim_route_applies_the_same_gate` | — |
| 13 | `test_without_a_gate_agent_work_is_never_ready_and_other_work_is_unchanged` | D9, D10 |
| 14 | `test_a_stopped_requester_cannot_create_and_each_refusal_counts_at_agent_work` | 5 |
| 15 | `test_a_stopped_claimant_is_refused_at_the_tool_and_the_request_stays_open` | 5 |
| 16 | `test_depth_two_is_allowed_and_depth_three_is_refused` | 3 |
| 17 | `test_the_per_agent_cap_counts_open_items_only` | 3, boundary and one past |
| 18 | `test_the_rate_counts_every_creation_in_the_trailing_hour` | 3, boundary at 3600 s |
| 19 | `test_the_department_and_ship_caps` | 3 |
| 20 | `test_an_open_request_with_the_same_department_tool_and_title_is_returned_and_watched` | 3, premise 10 |
| 21 | `test_dedup_titles_are_compared_in_one_normal_form` (6 cases) | — |
| 22 | `test_expiry_is_the_stores_sweep_and_each_notice_is_claimed_once_across_restarts` | 3 (TTL with notice), premises 9 and 10 |
| 23 | `test_the_service_owns_no_sweep_writes_no_status_and_never_names_the_captain` | premises 8 and 9 |
| 24 | `test_invalid_input_is_a_typed_refusal_and_writes_nothing` (6 cases) | — |
| 25 | `test_the_text_limits_are_inclusive_and_an_origin_validates_itself` | — |
| 26 | `test_the_directory_reads_department_rank_and_chief_from_the_live_ship` | — |
| 27 | `test_the_configuration_defaults_off_and_validates_at_parse_time` | 7 |
| 28 | `test_the_opener_builds_nothing_while_off_or_without_its_collaborators` | 7 (A3, F4: off with every collaborator, no schema or gate call; row R4) |
| 29 | `test_a_same_owner_replay_is_the_persisted_receipt_and_a_restriction_refuses_every_new_claim` | 3; property 6 (A3, F2; row W7) |
| 30 | `test_a_value_utf8_cannot_encode_is_a_typed_refusal_and_writes_nothing` (14 cases) | A3, F3 (rows A27 to A29) |
| 31 | `test_an_origin_refuses_an_id_utf8_cannot_encode` (2 cases) | A3, F3 (rows A27 and A30) |

**M2, `tests/test_ad1347_s1_wiring.py`.**
- W1 `test_the_flag_decides_whether_the_service_and_its_two_tables_exist` (7, golden; A2: also counts the runtime's calls to the opener, none off and one on, which is what kills mutation row R1; A3: neither boot resolves the Ship's Archive path).
- W2 `test_an_enabled_boot_creates_a_self_task_under_the_agents_slot_through_the_real_identity_facade` (6, premise 8; A3: the boot never resolves the Ship's Archive path).
- Both take the `archive_resolutions` fixture (A3, F1): `_boot_config` turns the archive off, and the fixture's spy on `probos.config.resolve_archive_db_path` answers with a path under `tmp_path` and must stay empty.

**Updated pins (each fails on the M1 tree without its update):**
- `tests/test_ad1343_agent_stop.py::test_refusals_are_counted_by_seam_and_an_unknown_seam_is_a_bug` (the literal set);
- `tests/test_ad1343_stop_seam_inventory.py::test_stop_checks_are_exactly_the_inventory` and `::test_every_seam_is_checked_and_no_check_names_an_unknown_seam` (registry rows);
- `tests/test_ad1343_stop_seam_inventory.py` standing-stop set, line 202;
- `tests/test_ad1343_seam_registry.py::test_every_indexed_seam_names_a_guard_that_still_holds` (`SEAM_INDEX`);
- `tests/test_ad1270e1_config_facade.py::test_committed_baseline_records_the_measured_surface` and the CLI test (`names=`);
- `tests/test_ad1152_agentic_correlation.py` (the golden);
- `tests/test_ad1185_config_profiles.py::test_the_measured_census_matches_the_manifest_header` (the manifest's census `default_false` 223 -> 224, §7.10 pair 2; A1);
- `tests/test_ad1270e2i_agentic_models.py::test_the_remaining_true_leaf_set_is_pinned` (`AgentWorkConfig` is a true leaf, §7.14b; A1);
- `tests/test_config_reference_current.py::test_the_reference_matches_the_models` and the gate's preflight `gen_config_reference.py --check` (generated, §7.14c; A1);
- `tests/test_layer_boundaries.py::test_no_undocumented_cross_layer_imports` is NOT updated: §7.13 types trust with `AgentIdentityTrust` and imports nothing from the consensus layer (A1).

**Hunt for stale, `?raw` and AST pins.** The first pass (Absence AV1 to AV11) missed the four A1 items above, which the oracle's run found. A1 hunted again, by tool, over the config surface, the layer scan, tree scanners, docs and every `scripts/gen_*` and `--check` script (Absence AV12 to AV16). Its findings:
- The census header's other numbers are unpinned and were already stale on the base (AV12; register); only `default_false` moves.
- The only docs that name config sections are the three files covered here (AV13); no seam manifest names the moved chief lookup (AV14).
- The new modules give the tree scanners nothing to flag (AV15).
- `gen_capability_truth` reads maturity declarations, and S1 adds none. `gen_file_durations` weighs an unknown file at the mean. `gen_ad_ledger` is covered by §8.

The first pass's checks still hold:
- Nothing pins `workforce.db`'s whole table set. The two `sqlite_master` readers use `>=` or a `LIKE` subset.
- `ad1152_agent_off_golden.json`'s `base_source_blobs` are blobs of the historical base commit, not the current files.
- `S1_SCOPE` is compared by object.
- `_find_chief_post` has no other caller.
- No test pins `crew_delegation.py`, `agent_stop.py` or `shutdown.py` by text.

**Focused command per milestone:**
- M1: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1347_s1_agent_work.py tests/test_ad1343_agent_stop.py tests/test_ad1343_stop_seam_inventory.py tests/test_ad1343_seam_registry.py tests/test_ad1346_admission_service.py tests/test_ad1270e1_config_facade.py tests/test_ad1152_agentic_correlation.py tests/test_ad1187_agent_work_pull.py tests/test_ad865_crew_delegation.py tests/test_workforce.py tests/test_ad1185_config_profiles.py tests/test_ad1270e2i_agentic_models.py tests/test_layer_boundaries.py tests/test_config_reference_current.py -q -n 0 -p no:randomly`. Drop any file in that list that does not exist; `tests/test_ad865*` is named by AD, so glob it.
- M2: `tests/test_ad1347_s1_wiring.py tests/test_ad1346_admission_service_boot.py` with the same flags.

## 7. The contract

### 7.1 `src/probos/agent_stop.py` (M1)

SEARCH:
```python
SEAM_AGENTIC_RUN: Final = "agentic_run"  # A2: the shared entry of every new agentic run, and correction rounds
SEAM_DELEGATION: Final = "delegation"  # A2: a task delegated to a stopped agent
SEAMS: Final[frozenset[str]] = frozenset({
    SEAM_INTENT, SEAM_CONSULTATION, SEAM_TOOL, SEAM_PROACTIVE, SEAM_WARD_ROOM,
    SEAM_DM_ROUTE, SEAM_GROUP_FANOUT, SEAM_BROWSER_ACTION, SEAM_AGENTIC_RUN, SEAM_DELEGATION,
})
```
REPLACE:
```python
SEAM_AGENTIC_RUN: Final = "agentic_run"  # A2: the shared entry of every new agentic run, and correction rounds
SEAM_DELEGATION: Final = "delegation"  # A2: a task delegated to a stopped agent
SEAM_AGENT_WORK: Final = "agent_work"  # AD-1347 S1: work an agent creates for itself or requests from a colleague
SEAMS: Final[frozenset[str]] = frozenset({
    SEAM_INTENT, SEAM_CONSULTATION, SEAM_TOOL, SEAM_PROACTIVE, SEAM_WARD_ROOM,
    SEAM_DM_ROUTE, SEAM_GROUP_FANOUT, SEAM_BROWSER_ACTION, SEAM_AGENTIC_RUN, SEAM_DELEGATION,
    SEAM_AGENT_WORK,
})
```

### 7.2 `tests/test_ad1343_agent_stop.py` (M1: T8 pins the seam names)

SEARCH:
```python
    assert SEAMS == frozenset({
        "intent", "consultation", "tool", "proactive", "ward_room", "dm_route", "group_fanout", "browser_action_ack",
        "agentic_run", "delegation",  # A2 (F1): the run entry and correction rounds; a delegated task
    })  # the seam names the Captain reads in every answer
```
REPLACE:
```python
    assert SEAMS == frozenset({
        "intent", "consultation", "tool", "proactive", "ward_room", "dm_route", "group_fanout", "browser_action_ack",
        "agentic_run", "delegation",  # A2 (F1): the run entry and correction rounds; a delegated task
        "agent_work",  # AD-1347 S1 (#1627): a create refused for a stopped requester is counted at its own seam
    })  # the seam names the Captain reads in every answer
```

### 7.3 `tests/fixtures/ad1343_seam_registry.py` (M1: three rows, the census of the new stop questions)

Pair 1 of 3 (`STOP_CHECK_SITES`):

SEARCH:
```python
    ("src/probos/cognitive/crew_finalizer.py", "CrewSessionFinalizer._resume_synthesis", "active_stop"): "SEAM_AGENTIC_RUN",
    ("src/probos/cognitive/dm/reply_pipeline.py", "DmReplyPipeline.step_4e_action_dispatch", "active_stop"): "SEAM_TOOL",
}
```
REPLACE:
```python
    ("src/probos/cognitive/crew_finalizer.py", "CrewSessionFinalizer._resume_synthesis", "active_stop"): "SEAM_AGENTIC_RUN",
    ("src/probos/cognitive/dm/reply_pipeline.py", "DmReplyPipeline.step_4e_action_dispatch", "active_stop"): "SEAM_TOOL",
    # AD-1347 S1 (#1627): the requester's stop, asked before any agent-created work is written.
    ("src/probos/agent_work.py", "AgentWorkService._requester_stop", "active_stop"): "SEAM_AGENT_WORK",
}
```

Pair 2 of 3 (`STANDING_STOP_SITES`):

SEARCH:
```python
    ("src/probos/cognitive/crew_assignment.py", "CrewAssignmentResolver.check_eligibility"),
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier._stopped"),
})
```
REPLACE:
```python
    ("src/probos/cognitive/crew_assignment.py", "CrewAssignmentResolver.check_eligibility"),
    ("src/probos/cognitive/crew_verifier.py", "SubtaskVerifier._stopped"),
    # AD-1347 S1: a colleague's stop, asked of candidates (an assignee, the claim gate, the eligible set); counts nothing.
    ("src/probos/agent_work.py", "AgentWorkService._stopped_now"),
})
```

Pair 3 of 3 (`SEAM_INDEX`):

SEARCH:
```python
    "long_runs": ("LongRunService records runs and starts no agent work", ("none", "src/probos/execution/long_runs.py")),
}
```
REPLACE:
```python
    "long_runs": ("LongRunService records runs and starts no agent work", ("none", "src/probos/execution/long_runs.py")),
    "agent_work": (
        "work an agent creates for itself or requests from a colleague (AD-1347); its claim is a tool call (SEAM_TOOL)",
        ("at", ("src/probos/agent_work.py", "AgentWorkService._requester_stop", "active_stop")),
    ),
}
```

### 7.4 `src/probos/cognitive/crew_delegation.py` (M1: AD-865's chief lookup becomes two shared functions; behaviour unchanged)

Pair 1 of 2:

SEARCH:
```python
    order_id: str | None
    delegated: bool
    reason: str


class CrewDelegator:
```
REPLACE:
```python
    order_id: str | None
    delegated: bool
    reason: str


def find_chief_post(ontology: VesselOntologyService, worker_post: Post) -> Post | None:
    """First in-department superior whose authority_over holds the worker post (AD-865; shared with AD-1347)."""
    chain = ontology.get_chain_of_command(worker_post.id)
    for post in chain:
        if post.id == worker_post.id:
            continue
        if (
            post.department_id == worker_post.department_id
            and worker_post.id in (post.authority_over or [])
        ):
            return post
    return None


def resolve_post_agent(ontology: VesselOntologyService, post_id: str) -> str | None:
    """Live agent_id of the first assignment wired to ``post_id`` (AD-865; shared with AD-1347)."""
    for assignment in ontology.get_agents_for_post(post_id):
        if assignment.agent_id is not None:
            return assignment.agent_id
    return None


class CrewDelegator:
```

Pair 2 of 2:

SEARCH:
```python
    def _find_chief_post(self, worker_post: "Post") -> "Post | None":
        """First in-department superior whose authority_over holds the worker post."""
        chain = self._ontology.get_chain_of_command(worker_post.id)
        for post in chain:
            if post.id == worker_post.id:
                continue
            if (
                post.department_id == worker_post.department_id
                and worker_post.id in (post.authority_over or [])
            ):
                return post
        return None

    def _resolve_post_agent(self, post_id: str) -> str | None:
        """Live agent_id of the first assignment wired to ``post_id``."""
        for assignment in self._ontology.get_agents_for_post(post_id):
            if assignment.agent_id is not None:
                return assignment.agent_id
        return None
```
REPLACE:
```python
    def _find_chief_post(self, worker_post: "Post") -> "Post | None":
        """First in-department superior whose authority_over holds the worker post."""
        return find_chief_post(self._ontology, worker_post)

    def _resolve_post_agent(self, post_id: str) -> str | None:
        """Live agent_id of the first assignment wired to ``post_id``."""
        return resolve_post_agent(self._ontology, post_id)
```

### 7.5 `src/probos/workforce.py` (M1: provenance key, lazy tables, the claim gate, six store methods)

Pair 1 of 4 (module constants, after the scaffold SQL):

SEARCH:
```python
_SCAFFOLD_EXCLUSION_SQL = (
    "(item.metadata IS NULL OR NOT json_valid(item.metadata) "
    f"OR json_extract(item.metadata, '$.{SCAFFOLD_METADATA_FLAG}') IS NOT 1)"
)


def _reject_reserved_metadata(metadata: Any) -> None:
```
REPLACE:
```python
_SCAFFOLD_EXCLUSION_SQL = (
    "(item.metadata IS NULL OR NOT json_valid(item.metadata) "
    f"OR json_extract(item.metadata, '$.{SCAFFOLD_METADATA_FLAG}') IS NOT 1)"
)

# AD-1347 S1 (#1627): agent-created work. Its provenance is the object under this key, written by
# ``probos.agent_work.AgentWorkService``. Nested on purpose: a top-level ``thread_id`` or a
# ``parent_id`` would make ``_standalone_pull_item`` refuse the item, and the request would reach nobody.
AGENT_WORK_METADATA_KEY = "agent_work"

# Created only by ``ensure_agent_work_schema``, which only the agent-work service's opener calls, so a
# vessel with agent_work off keeps workforce.db's schema unchanged. A notice row records that a terminal
# notice was claimed before it was sent: deleting one could send that notice twice.
_AGENT_WORK_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_work_watchers (
    work_item_id TEXT NOT NULL,
    agent_id     TEXT NOT NULL,
    added_at     REAL NOT NULL,
    PRIMARY KEY (work_item_id, agent_id)
);
CREATE TABLE IF NOT EXISTS agent_work_notices (
    work_item_id TEXT NOT NULL,
    recipient    TEXT NOT NULL,
    kind         TEXT NOT NULL,
    claimed_at   REAL NOT NULL,
    PRIMARY KEY (work_item_id, recipient, kind)
);
"""

# The CASE keeps a hand-edited non-JSON metadata column from raising, as the pull filter does.
_AGENT_WORK_FILTER_SQL = (
    "CASE WHEN json_valid(metadata) THEN "
    f"json_type(metadata, '$.{AGENT_WORK_METADATA_KEY}') = 'object' ELSE 0 END"
)


def _agent_work_ids_valid(*values: object) -> bool:
    """AD-1347 S1: each value is an exact str of 1 to 128 characters."""
    return all(type(value) is str and 1 <= len(value) <= 128 for value in values)


def _reject_reserved_metadata(metadata: Any) -> None:
```

Pair 2 of 4 (the gate attribute):

SEARCH:
```python
        self._pull_resource_resolver = pull_resource_resolver
        self._owned_steps_authorizer = owned_steps_authorizer
        self._owned_steps_ttl_owner = owned_steps_ttl_owner
```
REPLACE:
```python
        self._pull_resource_resolver = pull_resource_resolver
        # AD-1347 S1: set only by probos.agent_work.open_agent_work_service; None while the feature is off.
        self._agent_work_claim_gate: Callable[[WorkItem, BookableResource], bool] | None = None
        self._owned_steps_authorizer = owned_steps_authorizer
        self._owned_steps_ttl_owner = owned_steps_ttl_owner
```

Pair 3 of 4 (`_ready_for_pull` asks the gate):

SEARCH:
```python
            or (agent_pull and not self._pull_visible(item, resource))
            or not self._check_eligibility(resource, item)
            or (
                item.ttl_seconds is not None
```
REPLACE:
```python
            or (agent_pull and not self._pull_visible(item, resource))
            or not self._check_eligibility(resource, item)
            or not self._agent_work_claimable(item, resource)
            or (
                item.ttl_seconds is not None
```

Pair 4 of 4 (the gate and six methods, after `list_claimable_work_items`):

SEARCH:
```python
            more = examined < len(candidates) or len(candidates) == 200
            return ReadyWorkPage(
                tuple(items), offset + examined if more else None, tuple(item_offsets),
            )

    @staticmethod
    def _prepare_claim(
```
REPLACE:
```python
            more = examined < len(candidates) or len(candidates) == 200
            return ReadyWorkPage(
                tuple(items), offset + examined if more else None, tuple(item_offsets),
            )

    # -- AD-1347 S1 (#1627): agent-created work (probos.agent_work) ------------------------

    def set_agent_work_claim_gate(
        self, gate: Callable[[WorkItem, BookableResource], bool] | None,
    ) -> None:
        """AD-1347 S1: the agent-work service's claim check, asked for every item carrying agent-work provenance.

        Without one (the feature off) such an item is never ready to pull, so provenance left by an earlier
        run cannot make a request claimable by members its named tool would refuse. Items without the
        provenance key are unaffected either way.
        """
        if gate is not None and not callable(gate):
            raise ValueError("agent_work_claim_gate_invalid")
        self._agent_work_claim_gate = gate

    def _agent_work_claimable(self, item: WorkItem, resource: BookableResource) -> bool:
        if AGENT_WORK_METADATA_KEY not in item.metadata:
            return True
        gate = self._agent_work_claim_gate
        if gate is None:
            return False
        try:
            return gate(item, resource) is True
        except Exception:
            logger.warning(
                "AD-1347: the agent-work claim gate raised for work item %s and resource %s; "
                "the item is not ready for that resource and discovery continues",
                item.id, resource.resource_id, exc_info=True,
            )
            return False

    async def ensure_agent_work_schema(self) -> None:
        """AD-1347 S1: create the watcher and notice tables (idempotent). Only the agent-work opener calls it."""
        if self._db is None:
            raise RuntimeError("agent_work_store_unavailable")
        async with self._work_item_row_write_lock:
            await self._db.executescript(_AGENT_WORK_SCHEMA)
            await self._db.commit()

    async def list_agent_work(
        self, open_only: bool, created_since: float | None, limit: int,
    ) -> list[WorkItem]:
        """AD-1347 S1: items carrying agent-work provenance, oldest first. Open means not done, cancelled or failed."""
        if (
            type(open_only) is not bool
            or (
                created_since is not None
                and (type(created_since) not in (int, float) or not math.isfinite(created_since))
            )
            or type(limit) is not int or not 1 <= limit <= 10_000
        ):
            raise ValueError("agent_work_query_invalid")
        if self._db is None:
            raise RuntimeError("agent_work_store_unavailable")
        conditions = [_AGENT_WORK_FILTER_SQL]
        params: list[Any] = []
        if open_only:
            conditions.append("status NOT IN ('done', 'cancelled', 'failed')")
        if created_since is not None:
            conditions.append("created_at >= ?")
            params.append(created_since)
        cursor = await self._db.execute(
            f"SELECT {_WORK_ITEM_PUBLIC_COLUMNS} FROM work_items WHERE {' AND '.join(conditions)} "
            "ORDER BY created_at ASC, id ASC LIMIT ?",
            (*params, limit),
        )
        return [self._row_to_work_item(row) for row in await cursor.fetchall()]

    async def add_work_watcher(self, work_item_id: str, agent_id: str, added_at: float) -> bool:
        """AD-1347 S1: add a watcher to agent-created work; True only when it was not one already."""
        if not _agent_work_ids_valid(work_item_id, agent_id) or type(added_at) not in (int, float):
            raise ValueError("agent_work_watcher_invalid")
        if self._db is None:
            raise RuntimeError("agent_work_store_unavailable")
        async with self._booking_transaction():
            cursor = await self._db.execute(
                "INSERT OR IGNORE INTO agent_work_watchers (work_item_id, agent_id, added_at) VALUES (?, ?, ?)",
                (work_item_id, agent_id, added_at),
            )
        return cursor.rowcount == 1

    async def list_work_watchers(self, work_item_id: str) -> tuple[str, ...]:
        """AD-1347 S1: the watchers of an agent-created item, in the order they were added."""
        if not _agent_work_ids_valid(work_item_id):
            raise ValueError("agent_work_watcher_invalid")
        if self._db is None:
            raise RuntimeError("agent_work_store_unavailable")
        cursor = await self._db.execute(
            "SELECT agent_id FROM agent_work_watchers WHERE work_item_id = ? ORDER BY added_at ASC, agent_id ASC",
            (work_item_id,),
        )
        return tuple(row[0] for row in await cursor.fetchall())

    async def claim_work_notice(
        self, work_item_id: str, recipient: str, kind: str, claimed_at: float,
    ) -> bool:
        """AD-1347 S1: claim one notice before sending it; True once per (item, recipient, kind), across restarts."""
        if not _agent_work_ids_valid(work_item_id, recipient, kind) or type(claimed_at) not in (int, float):
            raise ValueError("agent_work_notice_invalid")
        if self._db is None:
            raise RuntimeError("agent_work_store_unavailable")
        async with self._booking_transaction():
            cursor = await self._db.execute(
                "INSERT OR IGNORE INTO agent_work_notices (work_item_id, recipient, kind, claimed_at) VALUES (?, ?, ?, ?)",
                (work_item_id, recipient, kind, claimed_at),
            )
        return cursor.rowcount == 1

    async def list_due_work_notices(self, kind: str, limit: int) -> list[tuple[str, str]]:
        """AD-1347 S1: (item, recipient) pairs of ended agent work not yet claimed for ``kind``.

        The recipients are each item's requester and every watcher, so a deduplicated request's watchers are
        never dropped from its outcome.
        """
        if not _agent_work_ids_valid(kind) or type(limit) is not int or not 1 <= limit <= 1_000:
            raise ValueError("agent_work_notice_invalid")
        if self._db is None:
            raise RuntimeError("agent_work_store_unavailable")
        cursor = await self._db.execute(
            "SELECT w.id, r.recipient FROM work_items AS w JOIN ("
            f"SELECT id AS work_item_id, json_extract(metadata, '$.{AGENT_WORK_METADATA_KEY}.requester') "
            "AS recipient FROM work_items WHERE CASE WHEN json_valid(metadata) THEN "
            f"json_type(metadata, '$.{AGENT_WORK_METADATA_KEY}.requester') = 'text' ELSE 0 END "
            "UNION SELECT work_item_id, agent_id FROM agent_work_watchers"
            ") AS r ON r.work_item_id = w.id "
            "WHERE w.status IN ('done', 'cancelled', 'failed') "
            "AND NOT EXISTS (SELECT 1 FROM agent_work_notices AS n WHERE n.work_item_id = w.id "
            "AND n.recipient = r.recipient AND n.kind = ?) "
            "ORDER BY w.updated_at ASC, w.id ASC, r.recipient ASC LIMIT ?",
            (kind, limit),
        )
        return [(row[0], row[1]) for row in await cursor.fetchall()]

    @staticmethod
    def _prepare_claim(
```

### 7.6 `src/probos/storage_declarations.py` (M1: the retention note names the two tables)

SEARCH:
```python
            "completion_calibration_spends are likewise retained indefinitely "
            "as immutable raw calibration evidence and raw Beta counts. "
            "Deleting or compacting these identities could replay execution, "
```
REPLACE:
```python
            "completion_calibration_spends are likewise retained indefinitely "
            "as immutable raw calibration evidence and raw Beta counts. "
            "AD-1347 agent_work_watchers and agent_work_notices rows (created "
            "only when agent_work.enabled) are retained with their work items; "
            "a notice row records a claimed terminal notice, so deleting one "
            "could send that notice twice. "
            "Deleting or compacting these identities could replay execution, "
```

### 7.7 `src/probos/config.py` (M1)

Pair 1 of 2 (the model, beside `WorkforceConfig`):

SEARCH:
```python
    custom_templates: list[dict] = []
    template_config_path: str = "config/work_templates.yaml"


class QualificationConfig(BaseModel):
```
REPLACE:
```python
    custom_templates: list[dict] = []
    template_config_path: str = "config/work_templates.yaml"


class AgentWorkConfig(BaseModel):
    """AD-1347 S1 (#1627): work crew agents create for themselves and request from colleagues.

    Default off: while off the runtime builds no service and workforce.db gains no table. Every count
    is of work items; open means not done, cancelled or failed. The rate counts items created in the
    trailing hour, whatever their status. The TTL applies to every agent-created item.
    """

    enabled: bool = False
    max_open_per_agent: int = Field(default=3, ge=1, le=50)
    max_open_per_department: int = Field(default=8, ge=1, le=200)
    max_open_ship: int = Field(default=24, ge=1, le=500)
    max_created_per_agent_per_hour: int = Field(default=6, ge=1, le=100)
    ttl_seconds: int = Field(default=86_400, ge=60, le=604_800)
    max_depth: int = Field(default=2, ge=1, le=5)

    @model_validator(mode="after")
    def _validate_caps_fit_the_ship(self) -> "AgentWorkConfig":
        """A per-agent or per-department cap above the ship cap could never be reached."""
        if self.max_open_per_agent > self.max_open_ship or self.max_open_per_department > self.max_open_ship:
            raise ValueError("agent_work: max_open_per_agent and max_open_per_department cannot exceed max_open_ship")
        return self


class QualificationConfig(BaseModel):
```

Pair 2 of 2 (`SystemConfig`):

SEARCH:
```python
    communications: CommunicationsConfig = CommunicationsConfig()
    workforce: WorkforceConfig = WorkforceConfig()
    temporal: TemporalConfig = TemporalConfig()
```
REPLACE:
```python
    communications: CommunicationsConfig = CommunicationsConfig()
    workforce: WorkforceConfig = WorkforceConfig()
    agent_work: AgentWorkConfig = Field(default_factory=AgentWorkConfig)  # AD-1347 S1 (#1627)
    temporal: TemporalConfig = TemporalConfig()
```

### 7.8 `docs/development/config-facade-baseline.yaml` (M1: generated, then checked against this list)

This file carries sha256 values only the tool computes. Run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_config_facade.py --update-baseline` on the M1 tree, then `--check`. `git diff` on the file must show **exactly** the following, and anything else is a hard stop:
1. `surface_counts`:
   - `own_models` 227 → 228;
   - `owned` 295 → 296;
   - `public_names` 308 → 309;
   - `field_definitions` 1869 → 1877 (`AgentWorkConfig`'s 7 fields plus `SystemConfig.agent_work`, as AD-1315 counted, `test_ad1270e1_config_facade.py:1546`);
   - `canonical_dump_leaves` 1881 → 1888 (expected: the seven scalar leaves; record the measured value if it differs, and explain it).
2. `canonical_dump_sha256` changed.
3. In `names:`, one row `  AgentWorkConfig: {kind: model, tier: owned}`, between `AgentTierConfig` and `AgenticDispatchConfig` (lines 144-145 today).
4. In `models:`, one new `AgentWorkConfig:` block (qualname, bases `BaseModel`/`object`, its schema_sha256, seven field rows: `{default: 'False', name: enabled}`, `{default: '3', name: max_open_per_agent}`, `{default: '8', name: max_open_per_department}`, `{default: '24', name: max_open_ship}`, `{default: '6', name: max_created_per_agent_per_hour}`, `{default: '86400', name: ttl_seconds}`, `{default: '2', name: max_depth}`).
5. `SystemConfig`: its schema_sha256 changed, and the row `{default: <required>, has_default_factory: true, name: agent_work}` immediately after `{default: WorkforceConfig(...), name: workforce}`.

### 7.9 `tests/test_ad1270e1_config_facade.py` (M1: the pinned counts)

Each SEARCH line occurs once in the file.

SEARCH:
```python
    assert counts["public_names"] == 308  # AD-1341 S1 (#1569) adds resolve_records_repo_path (307 -> 308)
    assert counts["owned"] == 295  # AD-1341 S1 (#1569): resolve_records_repo_path is owned (294 -> 295)
```
REPLACE:
```python
    assert counts["public_names"] == 309  # AD-1347 S1 (#1627) adds AgentWorkConfig (308 -> 309)
    assert counts["owned"] == 296  # AD-1347 S1 (#1627): AgentWorkConfig is owned (295 -> 296)
```

SEARCH:
```python
    assert counts["own_models"] == 227
```
REPLACE:
```python
    assert counts["own_models"] == 228  # AD-1347 S1 (#1627): AgentWorkConfig (227 -> 228)
```

SEARCH:
```python
    assert counts["field_definitions"] == 1869  # AD-1206 intentionally adds github_repository.
```
REPLACE:
```python
    # AD-1347 S1 adds AgentWorkConfig's seven fields and SystemConfig.agent_work (1869 -> 1877).
    assert counts["field_definitions"] == 1877  # AD-1206 intentionally adds github_repository.
```

SEARCH:
```python
    assert len(baseline["names"]) == 308  # AD-1341 S1 (#1569): resolve_records_repo_path
    assert len(baseline["models"]) == 228
```
REPLACE:
```python
    assert len(baseline["names"]) == 309  # AD-1347 S1 (#1627): AgentWorkConfig
    assert len(baseline["models"]) == 229  # AD-1347 S1 (#1627): AgentWorkConfig
```

SEARCH:
```python
    assert "names=308" in proc.stdout  # AD-1341 S1 (#1569): resolve_records_repo_path
```
REPLACE:
```python
    assert "names=309" in proc.stdout  # AD-1347 S1 (#1627): AgentWorkConfig
```

### 7.10 `docs/development/config-profiles.yaml` (M1: a new default-off flag must be classified and counted)

Pair 1 of 2 (the flag's classification):

SEARCH:
```yaml
  requires:
  - dm_agentic.economic_judgment.continue_extension.enabled
  conflicts_with: []
ci_divergences:
```
REPLACE:
```yaml
  requires:
  - dm_agentic.economic_judgment.continue_extension.enabled
  conflicts_with: []
- path: agent_work.enabled
  kind: product-feature
  profiles: []
  evidence_to_promote: tests/test_ad1347_s1_agent_work.py tests/test_ad1347_s1_wiring.py
    -- the real store, registry, permission store and stop record govern a request from creation
    to an eligible claim; a real boot builds the service only when armed, and OFF builds nothing
    and adds no table to workforce.db.
  external_dependency: null
  requires:
  - workforce.enabled
  conflicts_with: []
ci_divergences:
```

Pair 2 of 2 (Amendment A1: the census header). `tests/test_ad1185_config_profiles.py:859` asserts that the header's `default_false` equals the checker's count of default-off flags, and `agent_work.enabled` is one more default-off flag (223 -> 224). The precedent `b6c5734d` changed this number alone. The header's other numbers are read by no test or script and were already stale on the base (Absence AV12; register), so this pair leaves them alone. The SEARCH occurs once in the file (lines 19 to 21).

SEARCH:
```yaml
  boolean_fields_reachable: 445
  default_false: 223
  default_true: 225
```
REPLACE:
```yaml
  boolean_fields_reachable: 445
  default_false: 224
  default_true: 225
```

### 7.11 `tests/test_ad1152_agentic_correlation.py` (M1: the whole-config golden absorbs the inert section)

SEARCH:
```python
    assert config["execution"].pop("command_policy")["rules"] == []
    runtime = _local_runtime()
```
REPLACE:
```python
    assert config["execution"].pop("command_policy")["rules"] == []
    # AD-1347 S1's agent-work section was added after this capture too. It is default off, and while off
    # the runtime builds no service and workforce.db gains no table; this observation creates no work.
    assert config.pop("agent_work") == {
        "enabled": False, "max_open_per_agent": 3, "max_open_per_department": 8, "max_open_ship": 24,
        "max_created_per_agent_per_hour": 6, "ttl_seconds": 86400, "max_depth": 2,
    }
    runtime = _local_runtime()
```

### 7.12 New file: `src/probos/agent_work.py` (M1)

```python
"""AD-1347 S1 (#1627): the Ship's Computer service that owns the work crew agents create.

Authority (D2). A crew agent may create work for itself. A chief may assign work to a member of its
own department. Any other target, a peer or another department, is never an assignment: it becomes
an unassigned request published to one department that holds the named tool (AD-1187 department
scope), and an eligible member claims it.

Eligibility (D3) is the tool registry's own answer for each member: ``check_permission`` at read
level with the member's id, department, rank and agent type, so AD-423b's department scope,
``restricted_to``, rank matrix and the Captain's grants and restrictions all apply. It is asked when
a request is created and again at every discovery and every new claim (``claim_allowed``, the store's
gate). A same-owner replay of a claim already persisted is AD-1187's receipt and acquires nothing, so the
store does not ask again; S3 asks before it runs anything (Amendment A3).
An unregistered or disabled tool has no eligible member.

Provenance (D7) sits under ``metadata["agent_work"]``: never a top-level ``thread_id`` and never a
``parent_id``, because ``WorkItemStore._standalone_pull_item`` refuses either and the request would
reach nobody. The origin is a back-reference that says where S3 reports, not room ownership in the
AD-1187 sense: no room scopes, owns or receives the work. Depth is read from the parent item's
stored record, never taken from the caller.

S1 creates and governs; it runs nothing, and nothing calls it until S2. Expiry is the store's own
TTL sweep (``WorkItemStore._expire_ttl_items``); this service holds no loop. It never calls AD-1346's
``decide``, issues no ticket and widens no tool's departments or ranks.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Protocol

from probos.agent_stop import SEAM_AGENT_WORK, STOP_REASON_CODE, StopRecord, active_stop, standing_stop
from probos.tools.protocol import ToolPermission
from probos.workforce import AGENT_WORK_METADATA_KEY, BookableResource, WorkItem

if TYPE_CHECKING:
    from probos.agent_stop import AgentStopService
    from probos.config import AgentWorkConfig
    from probos.identity_service import IdentityRef
    from probos.workforce import WorkItemStore

logger = logging.getLogger(__name__)

AGENT_WORK_VERSION: Final = 1
AGENT_WORK_TAG: Final = "agent_work"
KIND_SELF: Final = "self"
KIND_ASSIGNMENT: Final = "assignment"
KIND_REQUEST: Final = "request"
KINDS: Final[tuple[str, ...]] = (KIND_SELF, KIND_ASSIGNMENT, KIND_REQUEST)
NOTICE_TERMINAL: Final = "terminal"
OUTCOME_EXPIRED: Final = "expired"
ORIGIN_CHANNELS: Final[frozenset[str]] = frozenset({"ward_room", "dm", "proactive", "agent_work"})
MAX_TITLE_CHARS: Final = 200
MAX_DESCRIPTION_CHARS: Final = 4_000
MAX_REASON_CHARS: Final = 500
MAX_ID_CHARS: Final = 128
RATE_WINDOW_SECONDS: Final = 3_600
#: Rows read per volume check. A page this full means more agent work is on the board than any valid
#: configuration allows open, so the create is refused rather than counted short.
SCAN_LIMIT: Final = 2_000

REFUSAL_INVALID: Final = "invalid_request"
REFUSAL_UNRESOLVED: Final = "requester_unresolved"
REFUSAL_PARENT_UNKNOWN: Final = "parent_unknown"
REFUSAL_DEPTH: Final = "depth_exceeded"
REFUSAL_TOOL_UNAVAILABLE: Final = "tool_unavailable"
REFUSAL_REQUESTER_NOT_ELIGIBLE: Final = "requester_not_eligible"
REFUSAL_REQUESTER_HOLDS_TOOL: Final = "requester_holds_tool"
REFUSAL_ASSIGNEE_UNKNOWN: Final = "assignee_unknown"
REFUSAL_ASSIGNEE_STOPPED: Final = "assignee_stopped"
REFUSAL_ASSIGNEE_NOT_ELIGIBLE: Final = "assignee_not_eligible"
REFUSAL_DEPARTMENT_NOT_ELIGIBLE: Final = "department_not_eligible"
REFUSAL_NO_ELIGIBLE_MEMBER: Final = "no_eligible_member"
REFUSAL_RATE: Final = "rate_limited"
REFUSAL_AGENT_CAP: Final = "agent_cap_reached"
REFUSAL_DEPARTMENT_CAP: Final = "department_cap_reached"
REFUSAL_SHIP_CAP: Final = "ship_cap_reached"
#: Every code a refused create can carry (the stop's own code included), in the order the checks run.
REFUSAL_CODES: Final[tuple[str, ...]] = (
    REFUSAL_INVALID, REFUSAL_UNRESOLVED, STOP_REASON_CODE, REFUSAL_PARENT_UNKNOWN, REFUSAL_DEPTH,
    REFUSAL_TOOL_UNAVAILABLE, REFUSAL_REQUESTER_NOT_ELIGIBLE, REFUSAL_ASSIGNEE_UNKNOWN,
    REFUSAL_ASSIGNEE_STOPPED, REFUSAL_ASSIGNEE_NOT_ELIGIBLE, REFUSAL_REQUESTER_HOLDS_TOOL,
    REFUSAL_DEPARTMENT_NOT_ELIGIBLE, REFUSAL_NO_ELIGIBLE_MEMBER, REFUSAL_RATE, REFUSAL_AGENT_CAP,
    REFUSAL_DEPARTMENT_CAP, REFUSAL_SHIP_CAP,
)


def _encodable(value: str) -> bool:
    """Whether ``value`` encodes as UTF-8 (Amendment A3).

    A JSON body can decode to a str holding an unpaired surrogate. SQLite's bind and the dedup key's sha256 refuse
    such a str with an exception, and a field that reaches neither would be stored as poisoned provenance, so every
    text and id input passes this check before any lookup or write.
    """
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _text(value: object, limit: int, *, required: bool) -> str | None:
    """The stripped text, or None when it is not an exact str, is blank where required, is too long, or is not UTF-8."""
    if type(value) is not str:
        return None
    stripped = value.strip()
    if (required and not stripped) or len(stripped) > limit or not _encodable(stripped):
        return None
    return stripped


def _identifier(value: object) -> bool:
    """An exact str of 1 to 128 characters with no surrounding whitespace that encodes as UTF-8."""
    return type(value) is str and 1 <= len(value) <= MAX_ID_CHARS and value.strip() == value and _encodable(value)


def normalize_title(title: str) -> str:
    """The dedup form of a title: Unicode NFKC, case-folded, every whitespace run one space, stripped."""
    return " ".join(unicodedata.normalize("NFKC", title).casefold().split())


def dedup_key(department: str, tool_id: str, title: str) -> str:
    """sha256 over the department, the tool and the normalised title, joined by the unit separator."""
    material = "\x1f".join((department, tool_id, normalize_title(title)))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AgentWorkOrigin:
    """Where the need was found: the channel and, when there is one, the thread and post (S3 reports there)."""

    channel: str
    thread_id: str = ""
    post_id: str = ""

    def __post_init__(self) -> None:
        if type(self.channel) is not str or self.channel not in ORIGIN_CHANNELS:
            raise ValueError("agent_work_origin_channel_invalid")
        for value in (self.thread_id, self.post_id):
            if type(value) is not str or len(value) > MAX_ID_CHARS or value.strip() != value or not _encodable(value):
                raise ValueError("agent_work_origin_id_invalid")

    def to_dict(self) -> dict[str, str]:
        """The stored form, under ``metadata["agent_work"]["origin"]``."""
        return {"channel": self.channel, "thread_id": self.thread_id, "post_id": self.post_id}


@dataclass(frozen=True)
class CrewMember:
    """One live crew member as the tool registry judges it: slot id, agent type, department, rank, chief."""

    slot_id: str
    agent_type: str
    department: str
    rank: str
    chief_slot_id: str | None = None


@dataclass(frozen=True)
class AgentWorkRecord:
    """The provenance under ``metadata["agent_work"]``, as ``read_agent_work`` reads it back."""

    kind: str
    requester: str
    depth: int
    department: str
    tool_id: str | None
    dedup_key: str | None


@dataclass(frozen=True)
class AgentWorkCreated:
    """A created item, or the open request a create matched (``deduplicated``); ``notify`` is for S3's notice."""

    work_item: WorkItem
    kind: str
    deduplicated: bool = False
    converted: bool = False
    notify: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentWorkRefusal:
    """A refused create: a stable ``code`` from ``REFUSAL_CODES`` and a reason the requester may read."""

    code: str
    detail: str = ""


@dataclass(frozen=True)
class AgentWorkNotice:
    """One terminal notice due: the item, who hears it, and its outcome (``expired`` or the item's status)."""

    work_item_id: str
    recipient: str
    outcome: str


def read_agent_work(item: WorkItem) -> AgentWorkRecord | None:
    """The item's agent-work provenance, or None when it has none or it is malformed.

    Total over JSON-decoded metadata: it reads only dicts, strs and ints and never raises for them.
    """
    metadata = item.metadata if type(item.metadata) is dict else {}
    raw = metadata.get(AGENT_WORK_METADATA_KEY)
    if type(raw) is not dict or type(raw.get("version")) is not int or raw["version"] != AGENT_WORK_VERSION:
        return None
    kind, requester, depth = raw.get("kind"), raw.get("requester"), raw.get("depth")
    department, tool_id, key = raw.get("department"), raw.get("tool_id"), raw.get("dedup_key")
    if (
        type(kind) is not str or kind not in KINDS
        or not _identifier(requester)
        or type(depth) is not int or depth < 1
        or type(department) is not str or not department
        or (tool_id is not None and not _identifier(tool_id))
        or (key is not None and type(key) is not str)
    ):
        return None
    return AgentWorkRecord(kind, requester, depth, department, tool_id, key)


def _requested_by(item: WorkItem, slot_id: str) -> bool:
    record = read_agent_work(item)
    return record is not None and record.requester == slot_id


class AgentWorkStore(Protocol):
    """The ``WorkItemStore`` methods the service uses."""

    async def create_work_item(self, **kwargs: Any) -> WorkItem: ...
    async def get_work_item(self, work_item_id: str) -> WorkItem | None: ...
    async def list_agent_work(self, open_only: bool, created_since: float | None, limit: int) -> list[WorkItem]: ...
    async def add_work_watcher(self, work_item_id: str, agent_id: str, added_at: float) -> bool: ...
    async def list_work_watchers(self, work_item_id: str) -> tuple[str, ...]: ...
    async def claim_work_notice(self, work_item_id: str, recipient: str, kind: str, claimed_at: float) -> bool: ...
    async def list_due_work_notices(self, kind: str, limit: int) -> list[tuple[str, str]]: ...


class ToolPermissionView(Protocol):
    """The ``ToolRegistry`` reads eligibility needs: the registration and AD-423b's permission answer."""

    def get(self, tool_id: str) -> Any: ...

    def check_permission(
        self, agent_id: str, tool_id: str, required: ToolPermission, *,
        agent_department: str | None = None, agent_rank: str = "ensign", agent_types: list[str] | None = None,
    ) -> bool: ...


class IdentityResolver(Protocol):
    """``IdentityService.resolve`` (AD-1346 M1a): any identity form to its slot's ref, or None."""

    def resolve(self, key: str) -> IdentityRef | None: ...


class CrewDirectory(Protocol):
    """The live crew; ``probos.cognitive.crew_directory.RuntimeCrewDirectory`` in production."""

    def members(self) -> tuple[CrewMember, ...]: ...
    def member(self, slot_id: str) -> CrewMember | None: ...


def _registered(tools: ToolPermissionView, tool_id: str) -> bool:
    registration = tools.get(tool_id)
    return registration is not None and registration.enabled is True


class AgentWorkService:
    """Ship's Computer service: creates and governs the work crew agents create (AD-1347 S1)."""

    def __init__(
        self,
        *,
        config: AgentWorkConfig,
        store: AgentWorkStore,
        tools: ToolPermissionView,
        identities: IdentityResolver,
        directory: CrewDirectory,
        stop_gate: AgentStopService,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if any(value is None for value in (config, store, tools, identities, directory, stop_gate)):
            raise ValueError("agent_work_dependencies_required")
        self._config = config
        self._store = store
        self._tools = tools
        self._identities = identities
        self._directory = directory
        self._stop_gate = stop_gate
        self._clock = clock
        self._lock = asyncio.Lock()

    async def create_self_task(
        self,
        requester: str,
        *,
        title: str,
        description: str,
        reason: str,
        origin: AgentWorkOrigin,
        tool_id: str | None = None,
        spawned_from: str | None = None,
    ) -> AgentWorkCreated | AgentWorkRefusal:
        """Work an agent schedules for itself, assigned to it; it runs later in its own agentic loop (S3)."""
        admitted = await self._admit(requester, title, description, reason, origin, spawned_from)
        if isinstance(admitted, AgentWorkRefusal):
            return admitted
        member, ref, depth = admitted
        if tool_id is not None:
            if not _identifier(tool_id):
                return AgentWorkRefusal(REFUSAL_INVALID, "the tool is not a valid id")
            if not _registered(self._tools, tool_id):
                return AgentWorkRefusal(REFUSAL_TOOL_UNAVAILABLE, f"{tool_id} is not a registered, enabled tool")
            if not self._holds_tool(member, tool_id):
                return AgentWorkRefusal(REFUSAL_REQUESTER_NOT_ELIGIBLE, f"you cannot use {tool_id}; request it")
        return await self._commit(
            member, ref, KIND_SELF, depth, title, description, reason, origin, tool_id,
            department=member.department, assignee=member.slot_id, spawned_from=spawned_from,
        )

    async def request_work(
        self,
        requester: str,
        *,
        title: str,
        description: str,
        reason: str,
        origin: AgentWorkOrigin,
        tool_id: str,
        assignee: str | None = None,
        department: str | None = None,
        spawned_from: str | None = None,
    ) -> AgentWorkCreated | AgentWorkRefusal:
        """Work for a colleague: a chief's own department member is assigned it; anyone else's becomes a request.

        A request is published to one department holding ``tool_id``: ``department`` when given (refused when no
        member there is eligible), else the named assignee's department when eligible, else the department with the
        most eligible members (ties by name). An open request with the same department, tool and normalised title is
        returned instead, and the requester becomes its watcher.
        """
        admitted = await self._admit(requester, title, description, reason, origin, spawned_from)
        if isinstance(admitted, AgentWorkRefusal):
            return admitted
        member, ref, depth = admitted
        if (
            not _identifier(tool_id)
            or (assignee is not None and not _identifier(assignee))
            or (department is not None and not _identifier(department))
        ):
            return AgentWorkRefusal(REFUSAL_INVALID, "the tool, assignee or department is not a valid id")
        if not _registered(self._tools, tool_id):
            return AgentWorkRefusal(REFUSAL_TOOL_UNAVAILABLE, f"{tool_id} is not a registered, enabled tool")
        target: CrewMember | None = None
        if assignee is not None:
            named = self._identities.resolve(assignee)
            target = self._directory.member(named.slot_id) if named is not None else None
            if target is None:
                return AgentWorkRefusal(REFUSAL_ASSIGNEE_UNKNOWN, "the named colleague is not a live crew member")
            if target.slot_id == member.slot_id:
                if not self._holds_tool(member, tool_id):
                    return AgentWorkRefusal(REFUSAL_REQUESTER_NOT_ELIGIBLE, f"you cannot use {tool_id}; request it")
                return await self._commit(
                    member, ref, KIND_SELF, depth, title, description, reason, origin, tool_id,
                    department=member.department, assignee=member.slot_id, spawned_from=spawned_from,
                )
            if target.department == member.department and target.chief_slot_id == member.slot_id:
                if self._stopped_now(target.slot_id):
                    return AgentWorkRefusal(REFUSAL_ASSIGNEE_STOPPED, "the colleague is stopped by the Captain's order")
                if not self._holds_tool(target, tool_id):
                    return AgentWorkRefusal(REFUSAL_ASSIGNEE_NOT_ELIGIBLE, f"{target.slot_id} cannot use {tool_id}")
                return await self._commit(
                    member, ref, KIND_ASSIGNMENT, depth, title, description, reason, origin, tool_id,
                    department=target.department, assignee=target.slot_id, spawned_from=spawned_from,
                )
        if self._holds_tool(member, tool_id):
            return AgentWorkRefusal(REFUSAL_REQUESTER_HOLDS_TOOL, f"you can use {tool_id} yourself; create a self-task")
        eligible = self.eligible_members(tool_id)
        departments = sorted({candidate.department for candidate in eligible})
        if department is not None:
            if department not in departments:
                return AgentWorkRefusal(REFUSAL_DEPARTMENT_NOT_ELIGIBLE, f"no member of {department} can use {tool_id} now")
            chosen = department
        elif not eligible:
            return AgentWorkRefusal(REFUSAL_NO_ELIGIBLE_MEMBER, f"no live crew member can use {tool_id} now")
        elif target is not None and target.department in departments:
            chosen = target.department
        else:
            chosen = min(departments, key=lambda name: (-sum(1 for m in eligible if m.department == name), name))
        notify = tuple(sorted(candidate.slot_id for candidate in eligible if candidate.department == chosen))
        return await self._commit(
            member, ref, KIND_REQUEST, depth, title, description, reason, origin, tool_id,
            department=chosen, assignee=None, spawned_from=spawned_from,
            converted_from=target.slot_id if target is not None else None, notify=notify,
        )

    def eligible_members(self, tool_id: str) -> tuple[CrewMember, ...]:
        """Live, unstopped crew members who may use ``tool_id`` at read level; empty for an unregistered tool."""
        if not _identifier(tool_id) or not _registered(self._tools, tool_id):
            return ()
        return tuple(
            candidate for candidate in self._directory.members()
            if not self._stopped_now(candidate.slot_id) and self._holds_tool(candidate, tool_id)
        )

    def claim_allowed(self, item: WorkItem, resource: BookableResource) -> bool:
        """The store's claim gate (``WorkItemStore.set_agent_work_claim_gate``): may this resource claim this now?

        Only a well-formed request can be claimed, by a live member of its department who is not stopped and may
        use its tool. Synchronous and without I/O, because the store asks inside its claim transaction. Never raises.
        """
        try:
            record = read_agent_work(item)
            if record is None or record.kind != KIND_REQUEST or record.tool_id is None:
                return False
            claimant = self._directory.member(resource.resource_id)
            if claimant is None or claimant.department != record.department:
                return False
            return not self._stopped_now(claimant.slot_id) and self._holds_tool(claimant, record.tool_id)
        except Exception:
            logger.warning(
                "AD-1347: the claim check for work item %s failed; it is not claimable by %s now and discovery continues",
                getattr(item, "id", "?"), getattr(resource, "resource_id", "?"), exc_info=True,
            )
            return False

    async def notice_recipients(self, work_item_id: str) -> tuple[str, ...]:
        """Who hears an item's outcome: its requester, then each watcher once (S3 delivers to every one)."""
        item = await self._store.get_work_item(work_item_id)
        record = read_agent_work(item) if item is not None else None
        if record is None:
            return ()
        watchers = await self._store.list_work_watchers(work_item_id)
        return (record.requester, *(watcher for watcher in watchers if watcher != record.requester))

    async def terminal_notices_due(self, limit: int = 50) -> tuple[AgentWorkNotice, ...]:
        """Ended agent work whose requester or a watcher has not been told; S3 claims each before sending it."""
        rows = await self._store.list_due_work_notices(NOTICE_TERMINAL, limit)
        notices: list[AgentWorkNotice] = []
        for work_item_id, recipient in rows:
            item = await self._store.get_work_item(work_item_id)
            if item is None:
                continue
            expired = (
                item.status == "cancelled" and item.ttl_seconds is not None
                and item.updated_at >= item.created_at + item.ttl_seconds
            )
            notices.append(AgentWorkNotice(work_item_id, recipient, OUTCOME_EXPIRED if expired else item.status))
        return tuple(notices)

    async def claim_notice(self, work_item_id: str, recipient: str) -> bool:
        """Claim the one terminal notice to ``recipient`` before sending it: True once, False ever after."""
        return await self._store.claim_work_notice(work_item_id, recipient, NOTICE_TERMINAL, self._clock())

    async def _admit(
        self, requester: str, title: str, description: str, reason: str,
        origin: AgentWorkOrigin, spawned_from: str | None,
    ) -> tuple[CrewMember, IdentityRef, int] | AgentWorkRefusal:
        """The shared checks, in order: the input, the requester (fail closed), the Captain's stop, the depth."""
        if (
            not _identifier(requester)
            or _text(title, MAX_TITLE_CHARS, required=True) is None
            or _text(description, MAX_DESCRIPTION_CHARS, required=False) is None
            or _text(reason, MAX_REASON_CHARS, required=True) is None
            or type(origin) is not AgentWorkOrigin
            or (spawned_from is not None and not _identifier(spawned_from))
        ):
            return AgentWorkRefusal(REFUSAL_INVALID, "a title, a reason and an origin are required, within their limits")
        ref = self._identities.resolve(requester)
        member = self._directory.member(ref.slot_id) if ref is not None else None
        if member is None or ref is None:
            return AgentWorkRefusal(REFUSAL_UNRESOLVED, "the requester is not a live crew member")
        stopped = self._requester_stop(member.slot_id)
        if stopped is not None:
            return AgentWorkRefusal(STOP_REASON_CODE, stopped.sender_text())
        depth = 1
        if spawned_from is not None:
            parent = await self._store.get_work_item(spawned_from)
            if parent is None:
                return AgentWorkRefusal(REFUSAL_PARENT_UNKNOWN, "the work this was created from does not exist")
            record = read_agent_work(parent)
            depth = record.depth + 1 if record is not None else 1
        if depth > self._config.max_depth:
            return AgentWorkRefusal(REFUSAL_DEPTH, f"depth {depth} is past the limit of {self._config.max_depth}")
        return member, ref, depth

    def _requester_stop(self, slot_id: str) -> StopRecord | None:
        """AD-1343: the requester's stop, counted as one refusal at SEAM_AGENT_WORK."""
        return active_stop(self._stop_gate, slot_id, SEAM_AGENT_WORK)

    def _stopped_now(self, slot_id: str) -> bool:
        """AD-1343: whether a colleague is stopped; asked of many candidates, so nothing is counted."""
        return standing_stop(self._stop_gate, slot_id) is not None

    def _holds_tool(self, member: CrewMember, tool_id: str) -> bool:
        """The registry's own answer for this member: department scope, restricted_to, rank, the Captain's grants."""
        return self._tools.check_permission(
            member.slot_id, tool_id, ToolPermission.READ,
            agent_department=member.department, agent_rank=member.rank, agent_types=[member.agent_type],
        )

    async def _commit(
        self, member: CrewMember, ref: IdentityRef, kind: str, depth: int, title: str, description: str,
        reason: str, origin: AgentWorkOrigin, tool_id: str | None, *, department: str, assignee: str | None,
        spawned_from: str | None, converted_from: str | None = None, notify: tuple[str, ...] = (),
    ) -> AgentWorkCreated | AgentWorkRefusal:
        """Dedup (requests), the volume guards, then one insert, under one lock: this service is the only writer."""
        clean_title = title.strip()
        converted = converted_from is not None
        key = dedup_key(department, tool_id, clean_title) if kind == KIND_REQUEST and tool_id is not None else None
        async with self._lock:
            now = self._clock()
            open_items = await self._store.list_agent_work(True, None, SCAN_LIMIT)
            open_records = [read_agent_work(item) for item in open_items]
            if key is not None:
                for item, record in zip(open_items, open_records):
                    if record is not None and record.kind == KIND_REQUEST and record.dedup_key == key:
                        if record.requester != member.slot_id:
                            await self._store.add_work_watcher(item.id, member.slot_id, now)
                        return AgentWorkCreated(item, KIND_REQUEST, deduplicated=True, converted=converted, notify=notify)
            recent = await self._store.list_agent_work(False, now - RATE_WINDOW_SECONDS, SCAN_LIMIT)
            if len(open_items) >= SCAN_LIMIT or len(recent) >= SCAN_LIMIT:
                return AgentWorkRefusal(REFUSAL_SHIP_CAP, "more agent-created work is on the board than the guards count")
            mine_recent = sum(1 for item in recent if _requested_by(item, member.slot_id))
            mine_open = sum(1 for record in open_records if record is not None and record.requester == member.slot_id)
            department_open = sum(
                1 for record in open_records
                if record is not None and record.kind == KIND_REQUEST and record.department == department
            )
            if mine_recent >= self._config.max_created_per_agent_per_hour:
                return AgentWorkRefusal(REFUSAL_RATE, f"at most {self._config.max_created_per_agent_per_hour} an hour")
            if mine_open >= self._config.max_open_per_agent:
                return AgentWorkRefusal(REFUSAL_AGENT_CAP, f"at most {self._config.max_open_per_agent} open at once")
            if kind == KIND_REQUEST and department_open >= self._config.max_open_per_department:
                return AgentWorkRefusal(REFUSAL_DEPARTMENT_CAP, f"{department} already has {department_open} open requests")
            if len(open_items) >= self._config.max_open_ship:
                return AgentWorkRefusal(REFUSAL_SHIP_CAP, f"the ship already has {len(open_items)} open agent work items")
            provenance: dict[str, Any] = {
                "version": AGENT_WORK_VERSION,
                "kind": kind,
                "requester": member.slot_id,
                "requester_sovereign_id": ref.sovereign_id,
                "origin": origin.to_dict(),
                "reason": reason.strip(),
                "depth": depth,
                "department": department,
                "tool_id": tool_id,
                "dedup_key": key,
                "spawned_from": spawned_from,
                "assignee_requested": converted_from,
            }
            metadata: dict[str, Any] = {AGENT_WORK_METADATA_KEY: provenance}
            if kind == KIND_REQUEST:
                metadata["agent_pull"] = {"version": 1, "scope": "department", "department": department}
            item = await self._store.create_work_item(
                title=clean_title,
                description=description.strip() or clean_title,
                work_type="task",
                assigned_to=assignee,
                created_by=member.slot_id,
                created_at=now,
                updated_at=now,
                ttl_seconds=self._config.ttl_seconds,
                tags=[AGENT_WORK_TAG],
                metadata=metadata,
            )
        logger.info(
            "AD-1347: %s %s created by %s (depth %d, department %s, tool %s)",
            kind, item.id, member.slot_id, depth, department, tool_id,
        )
        return AgentWorkCreated(item, kind, converted=converted, notify=notify)


async def open_agent_work_service(
    *,
    config: AgentWorkConfig,
    store: WorkItemStore | None,
    tools: ToolPermissionView | None,
    identities: IdentityResolver | None,
    directory: CrewDirectory | None,
    stop_gate: AgentStopService | None,
    clock: Callable[[], float] = time.time,
) -> AgentWorkService | None:
    """The one way the runtime builds the service (D1). None while ``config.enabled`` is False, touching nothing.

    When enabled, a missing collaborator or a schema failure is logged and the feature stays off for this run
    (log-and-degrade: the vessel boots). Otherwise the watcher and notice tables are created, the store's claim
    gate is set to ``claim_allowed`` and the service is returned.
    """
    if not config.enabled:
        return None
    if store is None or tools is None or identities is None or directory is None or stop_gate is None:
        missing = [
            name for name, value in (
                ("work_item_store", store), ("tool_registry", tools), ("identity_service", identities),
                ("crew_directory", directory), ("agent_stops", stop_gate),
            ) if value is None
        ]
        logger.warning(
            "AD-1347: agent_work.enabled is set but these collaborators are missing: %s; "
            "agent-created work stays off for this run", ", ".join(missing),
        )
        return None
    try:
        await store.ensure_agent_work_schema()
    except Exception:
        logger.error(
            "AD-1347: the agent-work tables could not be created in workforce.db; "
            "agent-created work stays off for this run",
            exc_info=True,
        )
        return None
    service = AgentWorkService(
        config=config, store=store, tools=tools, identities=identities,
        directory=directory, stop_gate=stop_gate, clock=clock,
    )
    store.set_agent_work_claim_gate(service.claim_allowed)
    logger.info(
        "AD-1347: agent-created work is on (open caps: %d per agent, %d per department, %d ship-wide)",
        config.max_open_per_agent, config.max_open_per_department, config.max_open_ship,
    )
    return service
```

### 7.13 New file: `src/probos/cognitive/crew_directory.py` (M1)

```python
"""AD-1347 S1 (#1627): the live crew as the agent-work service sees it.

``CrewDirectory`` (``probos.agent_work``) over the runtime's registry, ontology and trust. Department and
rank come from ``resolve_agentic_identity``, the resolver the workforce pull authority
(``ProbOSRuntime.resolve_workforce_pull_resource``) uses, so the eligibility the service computes at
creation is the one a claim is judged by. The chief is AD-865's in-department superior (``find_chief_post``).
Synchronous and without I/O: the store's claim gate reads it inside a transaction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from probos.agent_work import CrewMember
from probos.cognitive.agentic_dispatch import (
    AgenticIdentityUnresolved,
    AgentIdentityTrust,
    resolve_agentic_identity,
)
from probos.cognitive.crew_delegation import find_chief_post, resolve_post_agent

if TYPE_CHECKING:
    from probos.ontology import VesselOntologyService
    from probos.substrate.registry import AgentRegistry


class RuntimeCrewDirectory:
    """The live crew: alive, of a crew-tier agent type, with a resolvable department and rank."""

    def __init__(
        self, *, agent_registry: AgentRegistry, ontology: VesselOntologyService,
        trust_network: AgentIdentityTrust,
    ) -> None:
        self._registry = agent_registry
        self._ontology = ontology
        self._trust = trust_network

    def members(self) -> tuple[CrewMember, ...]:
        """Every live crew member, ordered by slot id."""
        crew_types = self._ontology.get_crew_agent_types()
        found = [self._member_of(agent, crew_types) for agent in self._registry.all()]
        return tuple(sorted((member for member in found if member is not None), key=lambda member: member.slot_id))

    def member(self, slot_id: str) -> CrewMember | None:
        """The live crew member in ``slot_id``, or None."""
        if type(slot_id) is not str or not slot_id:
            return None
        agent = self._registry.get(slot_id)
        if agent is None:
            return None
        return self._member_of(agent, self._ontology.get_crew_agent_types())

    def _member_of(self, agent: Any, crew_types: set[str]) -> CrewMember | None:
        agent_type = getattr(agent, "agent_type", None)
        if getattr(agent, "is_alive", None) is not True or agent_type not in crew_types:
            return None
        try:
            identity = resolve_agentic_identity(
                agent_id=agent.id, agent_registry=self._registry,
                ontology=self._ontology, trust_network=self._trust,
            )
        except AgenticIdentityUnresolved:
            return None
        chief = None
        post = self._ontology.get_post_for_agent(identity.agent_type)
        chief_post = find_chief_post(self._ontology, post) if post is not None else None
        if chief_post is not None:
            chief = resolve_post_agent(self._ontology, chief_post.id)
        return CrewMember(identity.agent_id, identity.agent_type, identity.department, identity.rank, chief)
```

### 7.14 New file: `tests/test_ad1347_s1_agent_work.py` (M1)

```python
"""AD-1347 S1 (#1627): the Ship's Computer service that owns agent-created work, against real objects.

The real ``WorkItemStore`` on a SQLite file under ``tmp_path``; the real ``ToolRegistry`` with ``event_log_query``
registered by its production function and a real ``ToolPermissionStore``; the real ``AgentStopService``; a real
``VesselOntologyService`` over a copy of ``config/ontology``; a real ``AgentRegistry`` of started agents; a real
``TrustNetwork``. Discovery and claim run through ``ToolRegistry.check_and_invoke`` and the runtime's own
``resolve_workforce_pull_resource``. Identity resolution is the one stand-in (``_SlotIdentities``): it answers as
``IdentityService.resolve`` does (AD-1346 M1a), and ``tests/test_ad1347_s1_wiring.py`` runs the real facade on a boot.

S2 and S3 extend ``test_request_is_created_published_and_claimed_by_an_eligible_member`` into acceptance 2's chain.
"""

from __future__ import annotations

import ast
import asyncio
import contextlib
import json
import logging
import shutil
import sqlite3
import time
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import probos.agent_work as agent_work_module
from probos.agent_stop import AgentStopService
from probos.agent_work import (
    AgentWorkCreated,
    AgentWorkOrigin,
    AgentWorkRefusal,
    AgentWorkService,
    CrewMember,
    normalize_title,
    open_agent_work_service,
    read_agent_work,
)
from probos.cognitive.crew_directory import RuntimeCrewDirectory
from probos.config import AgentWorkConfig, SystemConfig
from probos.consensus.trust import TrustNetwork
from probos.identity_service import IdentityRef
from probos.ontology import VesselOntologyService
from probos.runtime import ProbOSRuntime
from probos.startup.communication import _register_event_log_query_tool, _register_work_item_pull_tools
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPermission, ToolResultPresentation
from probos.tools.registry import ToolRegistry
from probos.workforce import BookableResource, WorkItemStore
from tests.test_ad1187_agent_work_pull import _Instrument
from tests.test_ad864_crew_assignment import _make_registry

_REPO = Path(__file__).resolve().parents[1]
CREW = (
    ("engineering_officer", "laforge-1"),
    ("builder", "forge-1"),
    ("builder", "forge-2"),
    ("security_officer", "worf-1"),
    ("data_analyst", "rahda-1"),
    ("diagnostician", "bones-1"),
    ("surgeon", "pulaski-1"),
    ("pharmacist", "ogawa-1"),
)
# The chiefs' posts, and the first officer's (another department's superior, so never a chief here).
WIRED = (("engineering_officer", "laforge-1"), ("diagnostician", "bones-1"), ("architect", "numberone-1"))
ENSIGNS = ("forge-2",)
RANKS = ("ensign", "lieutenant", "commander", "senior_officer")
ORIGIN = AgentWorkOrigin("ward_room", thread_id="51d91a7d", post_id="post-1")
PRESENTATION = ToolResultPresentation(render_complete=repr)
REASON = "the EventLog shows what the thread cannot"
STOP_REASON = "CANARY-ad1347: the Captain's private reason"
LIFT_REASON = "lifted by the test"
_UNUSED = object()


class _SlotIdentities:
    """``IdentityService.resolve``'s contract (AD-1346 M1a): a slot id or its UUID resolves; anything else is None."""

    def __init__(self, slots: Iterable[str]) -> None:
        refs = {
            slot: IdentityRef(slot_id=slot, sovereign_id=f"uuid-{slot}", did=f"did:probos:test:{slot}", callsign=slot, agent_type="crew")
            for slot in slots
        }
        self._refs = {**refs, **{ref.sovereign_id: ref for ref in refs.values()}}

    def resolve(self, key: str) -> IdentityRef | None:
        return self._refs.get(key)


@dataclass
class _Ship:
    service: AgentWorkService
    store: WorkItemStore
    tools: ToolRegistry
    permissions: ToolPermissionStore
    stops: AgentStopService
    directory: RuntimeCrewDirectory
    agents: dict[str, Any]
    db_path: Path


def _section(**limits: Any) -> AgentWorkConfig:
    return AgentWorkConfig(enabled=True, **limits)


def _schema(path: Path) -> list[tuple[str, str, str]]:
    with contextlib.closing(sqlite3.connect(path)) as raw:
        return raw.execute("SELECT type, name, coalesce(sql, '') FROM sqlite_master ORDER BY type, name").fetchall()


@contextlib.asynccontextmanager
async def _ship(
    tmp_path: Path,
    *,
    section: AgentWorkConfig | None = None,
    event_log: bool = True,
    clock: Callable[[], float] | None = None,
    tick: float = 1000.0,
) -> AsyncIterator[_Ship]:
    """One vessel's worth of the real collaborators; every file is under ``tmp_path`` and is reopened on a later call."""
    ontology_dir = tmp_path / "ontology"
    if not ontology_dir.exists():
        shutil.copytree(_REPO / "config" / "ontology", ontology_dir)
    (tmp_path / "ontology-data").mkdir(exist_ok=True)
    ontology = VesselOntologyService(ontology_dir, data_dir=tmp_path / "ontology-data")
    await ontology.initialize()
    for agent_type, slot in WIRED:
        ontology.wire_agent(agent_type, slot)
    registry = await _make_registry(list(CREW))
    agents = {agent.id: agent for agent in registry.all()}
    trust = TrustNetwork()
    for slot in ENSIGNS:
        trust.create_with_prior(slot, 1.0, 3.0)  # 0.25: an ensign; the default prior (0.5) is a lieutenant
    permissions = ToolPermissionStore(db_path=str(tmp_path / "tool_permissions.db"))
    stops = AgentStopService(data_dir=tmp_path / "stops")
    runtime = object.__new__(ProbOSRuntime)  # the pull authority's attributes only, as tests/test_ad1187_agent_work_pull.py does
    store = WorkItemStore(
        db_path=str(tmp_path / "workforce.db"), tick_interval=tick,
        pull_resource_resolver=runtime.resolve_workforce_pull_resource,
    )
    tools = ToolRegistry()
    started: list[Any] = []
    try:
        for agent in agents.values():
            await agent.start()
        await permissions.start()
        started.append(permissions)
        await stops.start()
        started.append(stops)
        tools.set_permission_store(permissions)
        tools.set_stop_gate(stops)
        _register_event_log_query_tool(
            tool_registry=tools, enabled=event_log,
            event_log_reader=_UNUSED, event_log_audit_sink=_UNUSED,  # type: ignore[arg-type]  # registered, never invoked
        )
        tools.register(_Instrument("hull_survey"), allowed_departments=("engineering",), default_permissions=dict.fromkeys(RANKS, "read"))
        tools.register(_Instrument("sealed_survey"), restricted_to=["nobody"])
        runtime.registry = registry
        runtime.ontology = ontology
        runtime.trust_network = trust
        runtime.tool_registry = tools
        runtime.work_item_store = store
        for slot, agent in agents.items():
            store.register_resource(BookableResource(resource_id=slot, agent_type=agent.agent_type, department="", capacity=5, characteristics=[]))
        await store.start()
        started.append(store)
        _register_work_item_pull_tools(
            tool_registry=tools, work_item_store=store, pull_resource_resolver=runtime.resolve_workforce_pull_resource,
        )
        directory = RuntimeCrewDirectory(agent_registry=registry, ontology=ontology, trust_network=trust)
        service = await open_agent_work_service(
            config=section or _section(), store=store, tools=tools,
            identities=_SlotIdentities([*agents, "ghost-1"]), directory=directory,
            stop_gate=stops, clock=clock or time.time,
        )
        assert isinstance(service, AgentWorkService)
        yield _Ship(service, store, tools, permissions, stops, directory, agents, tmp_path / "workforce.db")
    finally:
        for resource in reversed(started):
            await resource.stop()
        for agent in agents.values():
            if agent.is_alive:
                await agent.stop()


async def _invoke(ship: _Ship, slot: str, tool_id: str, params: dict[str, Any]) -> Any:
    member = ship.directory.member(slot)
    assert member is not None, slot
    required = ToolPermission.READ if tool_id == "discover_work_items" else ToolPermission.WRITE
    return await ship.tools.check_and_invoke(
        slot, tool_id, params, required=required, agent_department=member.department,
        agent_rank=member.rank, agent_types=[member.agent_type],
        context={"agent_id": slot, "_tool_result_presentation": PRESENTATION},
    )


async def _discovered(ship: _Ship, slot: str) -> list[str]:
    result = await _invoke(ship, slot, "discover_work_items", {})
    assert not result.error, result.error
    return [entry["id"] for entry in ast.literal_eval(result.output)["items"]]


async def _claimed(ship: _Ship, slot: str, work_item_id: str) -> bool:
    result = await _invoke(ship, slot, "claim_work_item", {"work_item_id": work_item_id})
    assert not result.error, result.error
    return ast.literal_eval(result.output)["owned"] is True


async def _request(
    ship: _Ship, requester: str = "pulaski-1", *, title: str = "Read the EventLog window",
    tool_id: str = "event_log_query", **extra: Any,
) -> AgentWorkCreated | AgentWorkRefusal:
    return await ship.service.request_work(
        requester, title=title, description="", reason=REASON, origin=ORIGIN, tool_id=tool_id, **extra,
    )


async def _self_task(
    ship: _Ship, requester: str = "forge-1", *, title: str = "Check my build log", **extra: Any,
) -> AgentWorkCreated | AgentWorkRefusal:
    return await ship.service.create_self_task(
        requester, title=title, description="", reason=REASON, origin=ORIGIN, **extra,
    )


def _code(result: AgentWorkCreated | AgentWorkRefusal) -> str:
    assert isinstance(result, AgentWorkRefusal), result
    return result.code


# 1
async def test_premise_the_fixture_is_the_production_shape(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        assert {member.slot_id for member in ship.directory.members()} == {slot for _, slot in CREW}
        registration = ship.tools.get("event_log_query")
        assert registration is not None
        assert registration.allowed_departments == ("engineering", "science", "security")
        assert registration.default_permissions["ensign"] == "none" and registration.default_permissions["lieutenant"] == "read"


# 2
async def test_a_self_task_is_assigned_to_its_creator_with_nested_provenance(tmp_path: Path) -> None:
    """Acceptance 6: created_by is the slot the requester's identity resolves to, never "captain"."""
    async with _ship(tmp_path) as ship:
        created = await _self_task(ship, "uuid-forge-1")
        assert isinstance(created, AgentWorkCreated), created
        item = created.work_item
        assert (created.kind, item.created_by, item.assigned_to, item.status) == ("self", "forge-1", "forge-1", "open")
        assert item.parent_id is None and item.ttl_seconds == 86_400 and item.tags == ["agent_work"]
        assert "thread_id" not in item.metadata and "agent_pull" not in item.metadata
        assert item.metadata["agent_work"] == {
            "version": 1, "kind": "self", "requester": "forge-1", "requester_sovereign_id": "uuid-forge-1",
            "origin": {"channel": "ward_room", "thread_id": "51d91a7d", "post_id": "post-1"},
            "reason": REASON, "depth": 1, "department": "engineering", "tool_id": None,
            "dedup_key": None, "spawned_from": None, "assignee_requested": None,
        }
        stored = await ship.store.get_work_item(item.id)
        assert stored is not None and stored.metadata == item.metadata and stored.created_by == "forge-1"
        tables = {name for kind, name, _ in _schema(ship.db_path) if kind == "table"}
        assert {"agent_work_watchers", "agent_work_notices"} <= tables


# 3
@pytest.mark.parametrize("requester", ["did:probos:agent:nobody", "ghost-1", "captain"])
async def test_an_unresolved_requester_is_refused_and_nothing_is_written(tmp_path: Path, requester: str) -> None:
    """Premise 8: no identity, or no live crew member behind it, is refused; nothing falls back to "captain"."""
    async with _ship(tmp_path) as ship:
        assert _code(await _self_task(ship, requester)) == "requester_unresolved"
        assert _code(await _request(ship, requester)) == "requester_unresolved"
        assert await ship.store.list_agent_work(False, None, 10) == []


# 4
async def test_a_self_task_naming_a_tool_needs_its_creator_to_hold_it(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        held = await _self_task(ship, "forge-1", tool_id="event_log_query")
        assert isinstance(held, AgentWorkCreated) and held.work_item.metadata["agent_work"]["tool_id"] == "event_log_query"
        for requester, tool_id, code in (
            ("pulaski-1", "event_log_query", "requester_not_eligible"),  # medical: outside the tool's departments
            ("forge-2", "event_log_query", "requester_not_eligible"),  # an ensign: the rank matrix says none
            ("forge-1", "no_such_tool", "tool_unavailable"),
            ("forge-1", "", "invalid_request"),
        ):
            assert _code(await _self_task(ship, requester, title=f"{requester} {tool_id}", tool_id=tool_id)) == code


# 5
async def test_a_chief_assigns_within_its_department(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        assigned = await _request(ship, "laforge-1", assignee="forge-1")
        assert isinstance(assigned, AgentWorkCreated), assigned
        assert (assigned.kind, assigned.converted, assigned.work_item.assigned_to) == ("assignment", False, "forge-1")
        assert "agent_pull" not in assigned.work_item.metadata
        assert _code(await _request(ship, "laforge-1", title="an ensign", assignee="forge-2")) == "assignee_not_eligible"
        await ship.stops.issue_stop("forge-1", reason=STOP_REASON)
        try:
            assert _code(await _request(ship, "laforge-1", title="stopped", assignee="forge-1")) == "assignee_stopped"
        finally:
            await ship.stops.lift_stop("forge-1", reason=LIFT_REASON)


# 6
async def test_a_peer_or_cross_department_assignment_becomes_a_request(tmp_path: Path) -> None:
    """Acceptance 3: a non-chief cannot assign; a peer or cross-department assignment becomes a request."""
    async with _ship(tmp_path) as ship:
        peer = await _request(ship, "pulaski-1", assignee="ogawa-1")
        across = await _request(ship, "worf-1", title="Survey the hull", tool_id="hull_survey", assignee="forge-1")
        aimed = await _request(ship, "pulaski-1", title="Read the security log window", assignee="worf-1")
        for created, department, named in (
            (peer, "engineering", "ogawa-1"), (across, "engineering", "forge-1"), (aimed, "security", "worf-1"),
        ):
            assert isinstance(created, AgentWorkCreated), created
            assert (created.kind, created.converted, created.work_item.assigned_to) == ("request", True, None)
            record = created.work_item.metadata["agent_work"]
            assert (record["department"], record["assignee_requested"]) == (department, named)
            assert created.work_item.metadata["agent_pull"] == {"version": 1, "scope": "department", "department": department}


# 7
async def test_a_request_goes_to_the_department_with_most_eligible_members_unless_one_is_named(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        default = await _request(ship, "pulaski-1")
        assert isinstance(default, AgentWorkCreated)
        assert default.work_item.metadata["agent_pull"]["department"] == "engineering"
        assert default.notify == ("forge-1", "laforge-1")  # engineering's lieutenants; forge-2 is an ensign
        named = await _request(ship, "ogawa-1", title="Science reads it", department="science")
        assert isinstance(named, AgentWorkCreated) and named.notify == ("rahda-1",)
        assert _code(await _request(ship, "bones-1", title="Medical reads it", department="medical")) == "department_not_eligible"


# 8
async def test_eligibility_is_the_registrys_own_answer_for_each_member(tmp_path: Path) -> None:
    """Premise 3: restricted_to, the rank matrix and the Captain's grants and restrictions decide, per member."""
    async with _ship(tmp_path) as ship:
        def eligible(tool_id: str) -> set[str]:
            return {member.slot_id for member in ship.service.eligible_members(tool_id)}

        assert eligible("event_log_query") == {"laforge-1", "forge-1", "worf-1", "rahda-1"}
        await ship.permissions.issue_grant("forge-2", "event_log_query", ToolPermission.READ, reason="AD-1347 test grant")
        await ship.permissions.issue_grant(
            "forge-1", "event_log_query", ToolPermission.NONE, is_restriction=True, reason="AD-1347 test restriction",
        )
        assert eligible("event_log_query") == {"laforge-1", "forge-2", "worf-1", "rahda-1"}
        assert eligible("hull_survey") == {"laforge-1", "forge-1", "forge-2"}
        assert eligible("sealed_survey") == set()
        assert _code(await _request(ship, "rahda-1")) == "requester_holds_tool"


# 9
async def test_an_unregistered_tool_or_a_tool_nobody_may_use_is_refused_at_creation(tmp_path: Path) -> None:
    """Premise 4: event_log_query exists only when agentic_dispatch.orchestrator_enabled is on; unregistered is no department."""
    async with _ship(tmp_path / "off", event_log=False) as ship:
        assert ship.tools.get("event_log_query") is None
        assert ship.service.eligible_members("event_log_query") == ()
        assert _code(await _request(ship, "pulaski-1")) == "tool_unavailable"
    async with _ship(tmp_path / "on") as ship:
        assert _code(await _request(ship, "pulaski-1", tool_id="sealed_survey")) == "no_eligible_member"
        for slot in ("laforge-1", "forge-1", "worf-1", "rahda-1"):
            await ship.stops.issue_stop(slot, reason=STOP_REASON)
        assert _code(await _request(ship, "pulaski-1")) == "no_eligible_member"


# 10
async def test_request_is_created_published_and_claimed_by_an_eligible_member(tmp_path: Path) -> None:
    """The S1 half of acceptance 2, and acceptance 3's claim half, through the real tools and the runtime's pull authority.

    S2 and S3 extend this test into acceptance 2's chain: the chain tag before creation; the activation notice, the
    execution with event_log_query and the post in the origin thread after the claim.
    """
    async with _ship(tmp_path) as ship:
        created = await _request(ship, "pulaski-1")
        assert isinstance(created, AgentWorkCreated), created
        item_id = created.work_item.id
        assert item_id not in await _discovered(ship, "worf-1")  # security: another department's request
        assert item_id not in await _discovered(ship, "forge-2")  # engineering, but an ensign
        assert await _claimed(ship, "forge-2", item_id) is False
        assert await _discovered(ship, "forge-1") == [item_id]
        assert await _claimed(ship, "forge-1", item_id) is True
        claimed = await ship.store.get_work_item(item_id)
        assert claimed is not None and (claimed.assigned_to, claimed.status) == ("forge-1", "scheduled")
        assert item_id not in await _discovered(ship, "laforge-1")


# 11
async def test_a_request_with_a_top_level_thread_id_would_reach_nobody(tmp_path: Path) -> None:
    """Premise 6: the placement trap; the same publication with the origin at the top level is not discoverable."""
    async with _ship(tmp_path) as ship:
        created = await _request(ship, "pulaski-1")
        assert isinstance(created, AgentWorkCreated)
        assert created.work_item.metadata["agent_work"]["origin"]["thread_id"] == "51d91a7d"
        trapped = await ship.store.create_work_item(
            title="trapped", metadata={**created.work_item.metadata, "thread_id": "51d91a7d"},
        )
        assert await _discovered(ship, "forge-1") == [created.work_item.id]
        assert trapped.id not in await _discovered(ship, "laforge-1")


# 12
async def test_the_legacy_claim_route_applies_the_same_gate(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        created = await _request(ship, "pulaski-1")
        assert isinstance(created, AgentWorkCreated)
        assert await ship.store.claim_work_item("forge-2") is None  # an ensign
        assert await ship.store.claim_work_item("worf-1") is None  # another department
        issued = await ship.stops.issue_stop("forge-1", reason=STOP_REASON)
        try:
            assert await ship.store.claim_work_item("forge-1") is None  # stopped
            assert ship.stops.refused_counts(issued.record.stop_id) == {}  # a candidate question counts nothing
        finally:
            await ship.stops.lift_stop("forge-1", reason=LIFT_REASON)
        claimed = await ship.store.claim_work_item("forge-1")
        assert claimed is not None and claimed[0].id == created.work_item.id


# 13
async def test_without_a_gate_agent_work_is_never_ready_and_other_work_is_unchanged(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        created = await _request(ship, "pulaski-1")
        assert isinstance(created, AgentWorkCreated)
        plain = await ship.store.create_work_item(
            title="plain", metadata={"agent_pull": {"version": 1, "scope": "department", "department": "engineering"}},
        )
        assert set(await _discovered(ship, "forge-1")) == {created.work_item.id, plain.id}
        ship.store.set_agent_work_claim_gate(None)
        assert await _discovered(ship, "forge-1") == [plain.id]
        assert await _claimed(ship, "forge-1", created.work_item.id) is False
        ship.store.set_agent_work_claim_gate(ship.service.claim_allowed)
        assert created.work_item.id in await _discovered(ship, "forge-1")


# 14
async def test_a_stopped_requester_cannot_create_and_each_refusal_counts_at_agent_work(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        issued = await ship.stops.issue_stop("pulaski-1", reason=STOP_REASON)
        for refused in (await _self_task(ship, "pulaski-1"), await _request(ship, "pulaski-1")):
            assert _code(refused) == "agent_stopped"
            assert isinstance(refused, AgentWorkRefusal) and "CANARY" not in refused.detail
        assert ship.stops.refused_counts(issued.record.stop_id) == {"agent_work": 2}
        assert await ship.store.list_agent_work(False, None, 10) == []


# 15
async def test_a_stopped_claimant_is_refused_at_the_tool_and_the_request_stays_open(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        created = await _request(ship, "pulaski-1")
        assert isinstance(created, AgentWorkCreated)
        issued = await ship.stops.issue_stop("forge-1", reason=STOP_REASON)
        result = await _invoke(ship, "forge-1", "claim_work_item", {"work_item_id": created.work_item.id})
        assert result.error and "agent_stop" in result.metadata
        assert ship.stops.refused_counts(issued.record.stop_id) == {"tool": 1}
        still = await ship.store.get_work_item(created.work_item.id)
        assert still is not None and (still.status, still.assigned_to) == ("open", None)


# 16
async def test_depth_two_is_allowed_and_depth_three_is_refused(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        first = await _self_task(ship, "forge-1", title="depth one")
        assert isinstance(first, AgentWorkCreated)
        second = await _request(ship, "pulaski-1", title="depth two", spawned_from=first.work_item.id)
        assert isinstance(second, AgentWorkCreated)
        assert [created.work_item.metadata["agent_work"]["depth"] for created in (first, second)] == [1, 2]
        assert _code(await _self_task(ship, "forge-1", title="depth three", spawned_from=second.work_item.id)) == "depth_exceeded"
        captains = await ship.store.create_work_item(title="the Captain's task")
        under = await _self_task(ship, "forge-1", title="under the Captain", spawned_from=captains.id)
        assert isinstance(under, AgentWorkCreated) and under.work_item.metadata["agent_work"]["depth"] == 1
        assert _code(await _self_task(ship, "forge-1", title="orphan", spawned_from="no-such-item")) == "parent_unknown"


# 17
async def test_the_per_agent_cap_counts_open_items_only(tmp_path: Path) -> None:
    async with _ship(tmp_path, section=_section(max_open_per_agent=2)) as ship:
        first = await _self_task(ship, "forge-1", title="one")
        assert isinstance(first, AgentWorkCreated)
        assert isinstance(await _self_task(ship, "forge-1", title="two"), AgentWorkCreated)
        assert _code(await _self_task(ship, "forge-1", title="three")) == "agent_cap_reached"
        assert isinstance(await _self_task(ship, "laforge-1", title="another agent"), AgentWorkCreated)
        await ship.store.transition_work_item(first.work_item.id, "cancelled", source="ad1347-test")
        assert isinstance(await _self_task(ship, "forge-1", title="three"), AgentWorkCreated)


# 18
async def test_the_rate_counts_every_creation_in_the_trailing_hour(tmp_path: Path) -> None:
    now = [time.time()]
    async with _ship(tmp_path, section=_section(max_created_per_agent_per_hour=2), clock=lambda: now[0]) as ship:
        assert isinstance(await _self_task(ship, "forge-1", title="one"), AgentWorkCreated)
        assert isinstance(await _self_task(ship, "forge-1", title="two"), AgentWorkCreated)
        assert _code(await _self_task(ship, "forge-1", title="three")) == "rate_limited"
        now[0] += 3600  # the first two are exactly an hour old: still in the window
        assert _code(await _self_task(ship, "forge-1", title="three")) == "rate_limited"
        now[0] += 0.5
        assert isinstance(await _self_task(ship, "forge-1", title="three"), AgentWorkCreated)


# 19
async def test_the_department_and_ship_caps(tmp_path: Path) -> None:
    async with _ship(tmp_path / "department", section=_section(max_open_per_department=1)) as ship:
        assert isinstance(await _request(ship, "pulaski-1", title="first"), AgentWorkCreated)
        assert _code(await _request(ship, "ogawa-1", title="second")) == "department_cap_reached"
        assert isinstance(await _request(ship, "ogawa-1", title="second", department="security"), AgentWorkCreated)
    limits = _section(max_open_per_agent=2, max_open_per_department=2, max_open_ship=2)
    async with _ship(tmp_path / "ship", section=limits) as ship:
        assert isinstance(await _self_task(ship, "forge-1", title="first"), AgentWorkCreated)
        assert isinstance(await _self_task(ship, "laforge-1", title="second"), AgentWorkCreated)
        assert _code(await _self_task(ship, "worf-1", title="third")) == "ship_cap_reached"


# 20
async def test_an_open_request_with_the_same_department_tool_and_title_is_returned_and_watched(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        first = await _request(ship, "pulaski-1", title="Read the EventLog window")
        assert isinstance(first, AgentWorkCreated) and not first.deduplicated
        item_id = first.work_item.id
        for requester, title in (("ogawa-1", "  read the  EVENTLOG\twindow "), ("bones-1", "Ｒｅａｄ the EventLog window")):
            again = await _request(ship, requester, title=title)
            assert isinstance(again, AgentWorkCreated) and again.deduplicated and again.work_item.id == item_id, requester
        repeat = await _request(ship, "pulaski-1", title="Read the EventLog window")
        assert isinstance(repeat, AgentWorkCreated) and repeat.deduplicated and repeat.work_item.id == item_id
        assert set(await ship.store.list_work_watchers(item_id)) == {"ogawa-1", "bones-1"}  # never the requester
        assert await ship.store.add_work_watcher(item_id, "ogawa-1", time.time()) is False
        recipients = await ship.service.notice_recipients(item_id)
        assert recipients[0] == "pulaski-1" and set(recipients[1:]) == {"ogawa-1", "bones-1"} and len(recipients) == 3
        other_tool = await _request(ship, "pulaski-1", title="Read the EventLog window", tool_id="hull_survey")
        other_department = await _request(ship, "ogawa-1", title="Read the EventLog window", department="security")
        for created in (other_tool, other_department):
            assert isinstance(created, AgentWorkCreated) and not created.deduplicated and created.work_item.id != item_id
        await ship.store.transition_work_item(item_id, "cancelled", source="ad1347-test")
        reopened = await _request(ship, "bones-1", title="Read the EventLog window")
        assert isinstance(reopened, AgentWorkCreated) and not reopened.deduplicated


# 21
@pytest.mark.parametrize(("left", "right", "same"), [
    ("Read the log", "read  the LOG", True),
    ("Read the log", " Read\nthe\tlog ", True),
    ("Ｒｅａｄ", "read", True),
    ("Straße", "STRASSE", True),
    ("Read the log", "Read the logs", False),
    ("Read the log.", "Read the log", False),
], ids=["case-and-spaces", "whitespace-kinds", "nfkc", "casefold", "different-word", "punctuation-kept"])
def test_dedup_titles_are_compared_in_one_normal_form(left: str, right: str, same: bool) -> None:
    assert (normalize_title(left) == normalize_title(right)) is same


def _two_minutes_ago() -> float:
    return time.time() - 120


# 22
async def test_expiry_is_the_stores_sweep_and_each_notice_is_claimed_once_across_restarts(tmp_path: Path) -> None:
    """Premise 9: one owner of expiry (the store's tick), idempotent notices. Premise 10: every watcher is a recipient."""
    section = _section(ttl_seconds=60)
    async with _ship(tmp_path, section=section, clock=_two_minutes_ago) as ship:
        created = await _request(ship, "pulaski-1")
        watched = await _request(ship, "ogawa-1")
        assert isinstance(created, AgentWorkCreated) and isinstance(watched, AgentWorkCreated)
        assert watched.deduplicated and watched.work_item.id == created.work_item.id
        item_id = created.work_item.id
        assert item_id not in await _discovered(ship, "forge-1")  # past its TTL: not claimable before the sweep
        assert await ship.service.terminal_notices_due() == ()  # still open
    async with _ship(tmp_path, section=section, tick=0.05) as ship:
        expired = None
        for _ in range(200):
            expired = await ship.store.get_work_item(item_id)
            if expired is not None and expired.status == "cancelled":
                break
            await asyncio.sleep(0.05)
        assert expired is not None and expired.status == "cancelled"
        due = await ship.service.terminal_notices_due()
        assert {(notice.recipient, notice.outcome) for notice in due} == {("pulaski-1", "expired"), ("ogawa-1", "expired")}
        assert await ship.service.claim_notice(item_id, "pulaski-1") is True
        assert [notice.recipient for notice in await ship.service.terminal_notices_due()] == ["ogawa-1"]
        assert await ship.service.claim_notice(item_id, "ogawa-1") is True
        assert await ship.service.claim_notice(item_id, "ogawa-1") is False
        assert await ship.service.terminal_notices_due() == ()
    async with _ship(tmp_path, section=section) as ship:
        assert await ship.service.terminal_notices_due() == ()
        assert await ship.service.claim_notice(item_id, "pulaski-1") is False
        assert await ship.service.notice_recipients(item_id) == ("pulaski-1", "ogawa-1")


# 23
def test_the_service_owns_no_sweep_writes_no_status_and_never_names_the_captain() -> None:
    """Premises 8 and 9, on the module's syntax tree."""
    tree = ast.parse(Path(agent_work_module.__file__).read_text(encoding="utf-8"))
    called = {
        node.func.attr for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not called & {"transition_work_item", "create_task", "decide", "assign_work_item", "update_work_item"}
    assert not [node for node in ast.walk(tree) if isinstance(node, ast.Constant) and node.value == "captain"]


# 24
@pytest.mark.parametrize("change", [
    {"title": "   "}, {"title": "x" * 201}, {"reason": ""}, {"description": "d" * 4001},
    {"origin": "ward_room"}, {"spawned_from": ""},
], ids=["blank-title", "long-title", "blank-reason", "long-description", "origin-not-typed", "blank-parent"])
async def test_invalid_input_is_a_typed_refusal_and_writes_nothing(tmp_path: Path, change: dict[str, Any]) -> None:
    async with _ship(tmp_path) as ship:
        arguments: dict[str, Any] = {"title": "Check", "description": "", "reason": REASON, "origin": ORIGIN, **change}
        assert _code(await ship.service.create_self_task("forge-1", **arguments)) == "invalid_request"
        assert await ship.store.list_agent_work(False, None, 10) == []


# 25
async def test_the_text_limits_are_inclusive_and_an_origin_validates_itself(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        edge = await ship.service.create_self_task(
            "forge-1", title="t" * 200, description="d" * 4000, reason="r" * 500, origin=ORIGIN,
        )
        assert isinstance(edge, AgentWorkCreated) and edge.work_item.title == "t" * 200
    for bad in ({"channel": "telepathy"}, {"channel": "dm", "thread_id": "x" * 129}, {"channel": "dm", "post_id": " padded"}):
        with pytest.raises(ValueError):
            AgentWorkOrigin(**bad)


# 26
async def test_the_directory_reads_department_rank_and_chief_from_the_live_ship(tmp_path: Path) -> None:
    async with _ship(tmp_path) as ship:
        members = {member.slot_id: member for member in ship.directory.members()}
        assert members["forge-1"] == CrewMember("forge-1", "builder", "engineering", "lieutenant", "laforge-1")
        assert members["forge-2"] == CrewMember("forge-2", "builder", "engineering", "ensign", "laforge-1")
        assert members["laforge-1"].chief_slot_id is None  # the first officer is wired, but in another department
        assert members["pulaski-1"].chief_slot_id == "bones-1"
        assert ship.directory.member("numberone-1") is None  # wired to a post, not a live agent
        await ship.agents["ogawa-1"].stop()
        assert ship.directory.member("ogawa-1") is None
        assert _code(await _request(ship, "pulaski-1", assignee="ogawa-1")) == "assignee_unknown"


# 27
def test_the_configuration_defaults_off_and_validates_at_parse_time() -> None:
    section = AgentWorkConfig()
    assert section.model_dump() == {
        "enabled": False, "max_open_per_agent": 3, "max_open_per_department": 8, "max_open_ship": 24,
        "max_created_per_agent_per_hour": 6, "ttl_seconds": 86_400, "max_depth": 2,
    }
    assert SystemConfig().agent_work == section
    assert AgentWorkConfig(max_open_per_agent=24, max_open_per_department=24, max_open_ship=24).max_open_ship == 24
    for bad in ({"max_open_per_agent": 25}, {"max_open_per_department": 25}, {"max_depth": 0}, {"ttl_seconds": 59}, {"max_open_ship": 0}):
        with pytest.raises(ValueError):
            AgentWorkConfig(**bad)


# 28
async def test_the_opener_builds_nothing_while_off_or_without_its_collaborators(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Acceptance 7. While off the opener touches nothing even with every collaborator present, so its own guard is
    pinned apart from the missing-collaborator branch, which also returns None (A3, F4: mutation row R4)."""
    path = tmp_path / "workforce.db"
    store = WorkItemStore(db_path=str(path), tick_interval=1000)
    await store.start()
    store_calls: list[str] = []

    async def _schema_spy() -> None:
        store_calls.append("ensure_agent_work_schema")

    def _gate_spy(gate: object) -> None:
        store_calls.append("set_agent_work_claim_gate")

    monkeypatch.setattr(store, "ensure_agent_work_schema", _schema_spy)
    monkeypatch.setattr(store, "set_agent_work_claim_gate", _gate_spy)
    try:
        before = _schema(path)
        off_directory = RuntimeCrewDirectory(
            agent_registry=await _make_registry([]), trust_network=TrustNetwork(), ontology=VesselOntologyService(_REPO / "config" / "ontology"),
        )
        off_stops = AgentStopService(data_dir=tmp_path / "stops")
        off = await open_agent_work_service(
            config=AgentWorkConfig(), store=store, tools=ToolRegistry(), identities=_SlotIdentities(()),
            directory=off_directory, stop_gate=off_stops,
        )
        assert off is None and _schema(path) == before
        assert store_calls == [], "while off the opener calls neither the schema nor the gate method"
        caplog.set_level(logging.WARNING, logger="probos.agent_work")
        missing = await open_agent_work_service(
            config=_section(), store=store, tools=ToolRegistry(), identities=_SlotIdentities(()),
            directory=None, stop_gate=None,
        )
        assert missing is None and _schema(path) == before and store_calls == []
        assert "missing: crew_directory, agent_stops" in caplog.text
    finally:
        await store.stop()


# 29
async def test_a_same_owner_replay_is_the_persisted_receipt_and_a_restriction_refuses_every_new_claim(
    tmp_path: Path,
) -> None:
    """Property 6 (A3, F2). Eligibility is asked at every discovery and every new claim, on both routes. A same-owner
    replay acquires nothing: it is AD-1187's receipt of a claim already persisted and precedes readiness, as it does
    when a trust requirement, a TTL or a dependency changes after the claim
    (``tests/test_ad1187_agent_work_pull.py::test_claim_replay_precedes_readiness_capacity_and_publication``).
    S3 asks again before it runs anything. Mutation row W7 is the gated replay."""
    async with _ship(tmp_path) as ship:
        first = await _request(ship, "pulaski-1")
        second = await _request(ship, "pulaski-1", title="Read the next EventLog window")
        assert isinstance(first, AgentWorkCreated) and isinstance(second, AgentWorkCreated)
        assert await _claimed(ship, "forge-1", first.work_item.id) is True
        await ship.permissions.issue_grant("forge-1", "event_log_query", ToolPermission.NONE, is_restriction=True)
        owned = await ship.store.get_work_item(first.work_item.id)
        assert owned is not None and owned.assigned_to == "forge-1"
        assert ship.service.claim_allowed(
            owned, BookableResource(resource_id="forge-1", agent_type="builder", department="", capacity=5, characteristics=[]),
        ) is False, "premise: the gate asked directly refuses forge-1 now"
        assert await _claimed(ship, "forge-1", first.work_item.id) is True  # the receipt of what is already persisted
        assert second.work_item.id not in await _discovered(ship, "forge-1")
        assert await _claimed(ship, "forge-1", second.work_item.id) is False
        assert await ship.store.claim_work_item("forge-1") is None  # the legacy route
        assert await _claimed(ship, "laforge-1", second.work_item.id) is True  # the restriction is forge-1's alone


_SURROGATE = json.loads('"\\ud800"')  # what a JSON body's "\ud800" decodes to: a str that UTF-8 cannot encode
_SURROGATE_CASES = [
    *(("self_task", field) for field in ("requester", "title", "description", "reason", "tool_id", "spawned_from")),
    *(("request", field) for field in (
        "requester", "title", "description", "reason", "tool_id", "assignee", "department", "spawned_from",
    )),
]


# 30
@pytest.mark.parametrize(("method", "field"), _SURROGATE_CASES, ids=[f"{method}-{field}" for method, field in _SURROGATE_CASES])
async def test_a_value_utf8_cannot_encode_is_a_typed_refusal_and_writes_nothing(
    tmp_path: Path, method: str, field: str,
) -> None:
    """A3 (F3). SQLite's bind and the dedup key's sha256 raise on an unpaired surrogate, and a field that reaches
    neither would be stored as poisoned provenance. Every text and id input of both create methods is refused as
    invalid_request before any lookup or write; the same call with the clean value then creates."""
    async with _ship(tmp_path) as ship:
        parent = await ship.store.create_work_item(title="An ordinary parent")
        clean: dict[str, Any] = {
            "requester": "forge-1" if method == "self_task" else "pulaski-1", "title": "Check the window",
            "description": "", "reason": REASON, "origin": ORIGIN, "tool_id": "event_log_query",
            "spawned_from": parent.id,
        }
        if method == "request":
            clean.update(assignee="forge-1", department="engineering")
        create: Callable[..., Any] = ship.service.create_self_task if method == "self_task" else ship.service.request_work
        poisoned = {**clean, field: f"{clean[field]}{_SURROGATE}"}
        assert _code(await create(poisoned.pop("requester"), **poisoned)) == "invalid_request"
        assert await ship.store.list_agent_work(False, None, 10) == []
        assert isinstance(await create(clean.pop("requester"), **clean), AgentWorkCreated)


# 31
@pytest.mark.parametrize("field", ["thread_id", "post_id"])
def test_an_origin_refuses_an_id_utf8_cannot_encode(field: str) -> None:
    """A3 (F3). The caller builds the origin (S2's parser), so the origin's own ValueError is the refusal; the create
    methods accept only an AgentWorkOrigin (test 24), so an id that cannot be stored never reaches the service."""
    with pytest.raises(ValueError, match="agent_work_origin_id_invalid"):
        AgentWorkOrigin("ward_room", **{field: f"51d91a7d{_SURROGATE}"})
    assert AgentWorkOrigin("ward_room", **{field: "51d91a7d"}).to_dict()[field] == "51d91a7d"
```

### 7.14b `tests/test_ad1270e2i_agentic_models.py` (M1, Amendment A1: AD-1270's true-leaf pin records the new leaf)

`AgentWorkConfig` names no other module-level name of `config.py`, so `test_the_remaining_true_leaf_set_is_pinned` (line 526) measures it as a true leaf. D4 keeps it beside `WorkforceConfig`; it moves with the workforce group in AD-1270's batch 10, and the pin records it as queued work. The SEARCH occurs once in the file (lines 160 and 161).

SEARCH:
```python
REMAINING_TRUE_LEAVES: tuple[str, ...] = (
    "BootCampPhaseConfig",
```
REPLACE:
```python
REMAINING_TRUE_LEAVES: tuple[str, ...] = (
    # AD-1347 S1 (#1627): a new leaf beside WorkforceConfig; it moves with the workforce group in batch 10.
    "AgentWorkConfig",
    "BootCampPhaseConfig",
```

### 7.14c `docs/development/config-reference.md` (M1, Amendment A1: generated, then checked)

Generated from the models; never edit it by hand. On the M1 tree run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_config_reference.py`, then the same command with `--check`. `git diff --stat` on the file must show 14 insertions and 0 deletions (measured by the oracle on the contract-applied tree). The diff must be exactly one new section for `agent_work`, between the `workforce` section and the `temporal` section:
- its heading;
- `AgentWorkConfig`'s docstring as the generator renders it;
- a table of seven rows in field order (`enabled`, `max_open_per_agent`, `max_open_per_department`, `max_open_ship`, `max_created_per_agent_per_hour`, `ttl_seconds`, `max_depth`), with the defaults and bounds of §7.7.

Anything else is a hard stop. Consumers: the gate's preflight step (`scripts/run_test_gate.py:1101`) and `tests/test_config_reference_current.py::test_the_reference_matches_the_models`.

### 7.15 `src/probos/runtime.py` (M2)

Pair 1 of 4 (type-only import):

SEARCH:
```python
    from probos.admission import AdmissionService  # AD-1346 M3a
    from probos.agent_stop import AgentStopService  # AD-1343
    from probos.approval_authority import ApprovalAuthorityStore  # AD-1213
```
REPLACE:
```python
    from probos.admission import AdmissionService  # AD-1346 M3a
    from probos.agent_stop import AgentStopService  # AD-1343
    from probos.agent_work import AgentWorkService  # AD-1347 S1
    from probos.approval_authority import ApprovalAuthorityStore  # AD-1213
```

Pair 2 of 4 (class annotation):

SEARCH:
```python
    persistent_task_store: PersistentTaskStore | None
    work_item_store: WorkItemStore | None
    crew_session_service: "CrewSessionService | None"
```
REPLACE:
```python
    persistent_task_store: PersistentTaskStore | None
    work_item_store: WorkItemStore | None
    agent_work: "AgentWorkService | None"  # AD-1347 S1: built in start() only when agent_work.enabled; released with the store
    crew_session_service: "CrewSessionService | None"
```

Pair 3 of 4 (`__init__` default):

SEARCH:
```python
        # --- Workforce Scheduling Engine (AD-496) ---
        self.work_item_store: WorkItemStore | None = None

        # --- Durable Crew Sessions (AD-1124) ---
```
REPLACE:
```python
        # --- Workforce Scheduling Engine (AD-496) ---
        self.work_item_store: WorkItemStore | None = None
        # AD-1347 S1: the service that owns agent-created work; built in start() only when agent_work.enabled
        self.agent_work: "AgentWorkService | None" = None

        # --- Durable Crew Sessions (AD-1124) ---
```

Pair 4 of 4 (build, after the BF-679 block):

SEARCH:
```python
                    "ship-wide commons but not their own private records",
                    exc_info=True,
                )

        # AD-637: Update NATS subject prefix after ship commissioning assigns DID
```
REPLACE:
```python
                    "ship-wide commons but not their own private records",
                    exc_info=True,
                )

        # AD-1347 S1 (#1627): the Ship's Computer service that owns agent-created work. Built only when
        # agent_work.enabled, here, where the work store, the tool registry, the stop gate and the ontology all
        # exist; while off the attribute stays None and workforce.db gains no table. Nothing calls it in S1.
        if self.config.agent_work.enabled:
            from probos.agent_work import open_agent_work_service
            from probos.cognitive.crew_directory import RuntimeCrewDirectory

            directory = None
            if self.ontology is not None:
                directory = RuntimeCrewDirectory(
                    agent_registry=self.registry, ontology=self.ontology, trust_network=self.trust_network,
                )
            self.agent_work = await open_agent_work_service(
                config=self.config.agent_work,
                store=self.work_item_store,
                tools=self.tool_registry,
                identities=self.identity_service,
                directory=directory,
                stop_gate=self.agent_stops,
            )

        # AD-637: Update NATS subject prefix after ship commissioning assigns DID
```

### 7.16 `src/probos/startup/shutdown.py` (M2)

SEARCH:
```python
        with steps("workforce store stop", runtime.work_item_store):
            await runtime.work_item_store.stop()
        runtime.work_item_store = None
```
REPLACE:
```python
        with steps("workforce store stop", runtime.work_item_store):
            await runtime.work_item_store.stop()
        runtime.work_item_store = None
        runtime.agent_work = None  # AD-1347 S1: the service holds the store; released with it
```

### 7.17 New file: `tests/test_ad1347_s1_wiring.py` (M2)

```python
"""AD-1347 S1 (#1627) M2: the runtime builds the agent-work service only when enabled, over its own collaborators.

Real boots of ``ProbOSRuntime`` with the mock LLM, as ``tests/test_ad1346_admission_service_boot.py`` does, with the
workforce store on. W1 is the boot half of the byte-identical-when-off golden (the store half is
``tests/test_ad1347_s1_agent_work.py`` tests 13 and 28; the default-config half is ``tests/test_ad1152_agentic_correlation.py``).
"""

from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path
from typing import Any

import pytest

import probos.agent_work as agent_work_module
import probos.config as probos_config
from probos.agent_work import AgentWorkCreated, AgentWorkOrigin, AgentWorkRefusal, AgentWorkService
from probos.cognitive.llm_client import MockLLMClient
from probos.config import AgentWorkConfig, ArchiveConfig, SystemConfig, WorkforceConfig
from probos.crew_utils import is_crew_agent
from probos.runtime import ProbOSRuntime
from tests.test_ad1346_admission_service_boot import _config as _admission_boot_config

AGENT_WORK_TABLES = {"agent_work_watchers", "agent_work_notices"}


def _boot_config(*, enabled: bool) -> SystemConfig:
    """AD-1346's boot shape with the workforce store on and the Ship's Archive off (A3, F1).

    An empty ``archive.db_path`` resolves to the live vessel's archive outside ``tmp_path``, and an enabled archive
    opens and migrates that file at boot. These boots need no archive, so it is off (``lifecycle_config`` redirects it
    instead).
    """
    return _admission_boot_config().model_copy(update={
        "workforce": WorkforceConfig(enabled=True), "agent_work": AgentWorkConfig(enabled=enabled),
        "archive": ArchiveConfig(enabled=False),
    })


@pytest.fixture
def archive_resolutions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Every call a boot makes to resolve the Ship's Archive path; each test asserts there is none (A3, F1).

    The boot imports ``resolve_archive_db_path`` inside its archive block, so replacing the module attribute is what
    it calls. The spy answers with a path under ``tmp_path``, so even a boot that regresses never opens the live file.
    """
    calls: list[object] = []

    def _resolve_under_tmp(archive: object) -> Path:
        calls.append(archive)
        return tmp_path / "archive-pin" / "archive.db"

    monkeypatch.setattr(probos_config, "resolve_archive_db_path", _resolve_under_tmp)
    return calls


def _tables(path: Path) -> set[str]:
    with contextlib.closing(sqlite3.connect(path)) as raw:
        return {name for (name,) in raw.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


# W1
async def test_the_flag_decides_whether_the_service_and_its_two_tables_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, archive_resolutions: list[object],
) -> None:
    """Acceptance 7: off never calls the opener and adds no table; on calls it once, adds exactly the two tables, and a
    clean stop releases the service.

    The call count pins the runtime's own guard (mutation row R1): the opener also returns None while off, so the
    outcomes alone cannot tell a runtime that skips its block from one that runs it. The runtime imports the opener
    inside that block, so replacing the module attribute is what the boot calls; the spy delegates to the real opener.
    """
    real_opener = agent_work_module.open_agent_work_service
    opened: list[dict[str, Any]] = []

    async def _counted_opener(**kwargs: Any) -> AgentWorkService | None:
        opened.append(kwargs)
        return await real_opener(**kwargs)

    monkeypatch.setattr(agent_work_module, "open_agent_work_service", _counted_opener)
    off = ProbOSRuntime(config=_boot_config(enabled=False), data_dir=tmp_path / "off", llm_client=MockLLMClient())
    await off.start()
    try:
        assert off.work_item_store is not None, "premise: the workforce store is on"
        assert off.agent_work is None
        assert opened == [], "while off the runtime never calls the opener"
    finally:
        await off.stop()
    on = ProbOSRuntime(config=_boot_config(enabled=True), data_dir=tmp_path / "on", llm_client=MockLLMClient())
    await on.start()
    try:
        assert isinstance(on.agent_work, AgentWorkService)
        assert len(opened) == 1 and opened[0]["config"].enabled is True, opened
    finally:
        await on.stop()
    assert on.agent_work is None, "a clean stop releases the service"
    off_tables = _tables(tmp_path / "off" / "workforce.db")
    on_tables = _tables(tmp_path / "on" / "workforce.db")
    assert not off_tables & AGENT_WORK_TABLES
    assert on_tables - off_tables == AGENT_WORK_TABLES
    assert archive_resolutions == [], "neither boot resolves the Ship's Archive path (A3, F1)"


# W2
async def test_an_enabled_boot_creates_a_self_task_under_the_agents_slot_through_the_real_identity_facade(
    tmp_path: Path, archive_resolutions: list[object],
) -> None:
    """Acceptance 6 and premise 8 on the real IdentityService: a DID becomes its slot; an unknown DID is refused."""
    rt = ProbOSRuntime(config=_boot_config(enabled=True), data_dir=tmp_path / "data", llm_client=MockLLMClient())
    await rt.start()
    try:
        service = rt.agent_work
        assert isinstance(service, AgentWorkService)
        crew = next(
            (
                a for a in rt.registry.all()
                if a.did and is_crew_agent(a, rt.ontology)
                and getattr(rt.identity_service.resolve(a.did), "slot_id", None) == a.id
            ),
            None,
        )
        assert crew is not None, "premise: a certified crew agent whose DID resolves to its own slot"
        origin = AgentWorkOrigin("dm")
        created = await service.create_self_task(
            crew.did, title="Verify the boot", description="", reason="AD-1347 wiring", origin=origin,
        )
        assert isinstance(created, AgentWorkCreated), created
        assert (created.work_item.created_by, created.work_item.assigned_to) == (crew.id, crew.id)
        stored = await rt.work_item_store.get_work_item(created.work_item.id)
        assert stored is not None and stored.created_by == crew.id
        unknown = await service.create_self_task(
            "did:probos:agent:unknown", title="Nobody", description="", reason="AD-1347 wiring", origin=origin,
        )
        assert isinstance(unknown, AgentWorkRefusal) and unknown.code == "requester_unresolved"
    finally:
        await rt.stop()
    assert archive_resolutions == [], "the boot never resolves the Ship's Archive path (A3, F1)"
```

## 8. Tracking (tracker pairs; in M2's commit, or a docs-only commit after it)

Set the date to the commit date. Both anchors survive BF-912's entries:
- PROGRESS: BF-912 inserts below the title as AD-1347 will; this pair anchors on the title and the blank line only, so the AD-1347 entry lands above BF-912's (newest first).
- DECISIONS: entries are inserted before the "Explicit delegation models" heading; BF-912's lands there first, and this pair anchors on that heading alone, so AD-1347's follows BF-912's.

**`PROGRESS.md`** (title plus the blank line, verified to occur once):

SEARCH:
```markdown
# ProbOS Progress

```
REPLACE:
```markdown
# ProbOS Progress

**AD-1347 S1 (2026-10-23), #1627 slice 1 of 4 -- the Ship's Computer service that owns agent-created work: an agent can create work for itself, a chief can assign within its department, and any other ask becomes a request published to a department holding the named tool. Default off; nothing calls it yet.** New `probos/agent_work.py` (`AgentWorkService`, `open_agent_work_service`) and `probos/cognitive/crew_directory.py` (`RuntimeCrewDirectory`). `created_by` is the slot the requester's identity resolves to, and an unresolved requester is refused, never stamped "captain". Provenance (requester, origin, reason, depth, department, tool, dedup key) sits under `metadata["agent_work"]`, never a top-level `thread_id` or a `parent_id`, so a request stays discoverable. Eligibility is the tool registry's own answer for each member (department scope, `restricted_to`, rank, the Captain's grants and restrictions), asked at creation and again at every discovery and every new claim through a fail-closed store gate, on the tool and legacy claim paths (a same-owner replay is AD-1187's receipt of a claim already persisted; S3 asks again before it runs anything); every text and id input must encode as UTF-8, so a JSON-decoded lone surrogate is a typed refusal; an unregistered tool has no eligible member. Guards: caps per agent 3, per department 8 and ship-wide 24 (open items), 6 creations per agent per hour, depth 2, a 24 h TTL owned by the store's existing sweep, and dedup on (department, tool, normalised title) that adds the asker as a watcher. A stopped requester is refused at the new `agent_work` seam. `WorkItemStore` gains `set_agent_work_claim_gate`, `ensure_agent_work_schema`, `list_agent_work`, `add_work_watcher`, `list_work_watchers`, `claim_work_notice` and `list_due_work_notices`. Two tables (`agent_work_watchers`, `agent_work_notices`) are created only when enabled. New config `agent_work` (`AgentWorkConfig`). AD-865's chief lookup is now `find_chief_post` and `resolve_post_agent` in `crew_delegation.py`. New: `tests/test_ad1347_s1_agent_work.py` and `tests/test_ad1347_s1_wiring.py` (real store, registry, permission store, stop record, ontology and boots, the boots with the Ship's Archive off). Updated: `test_ad1343_agent_stop.py`, `fixtures/ad1343_seam_registry.py`, `test_ad1270e1_config_facade.py`, `test_ad1152_agentic_correlation.py`, `test_ad1270e2i_agentic_models.py` (the true-leaf set), the config-facade baseline, the config-profiles manifest (classification and census) and the generated config reference. The contract is `prompts/ad-1347-s1-agent-created-work-service.md`.

```

**`DECISIONS.md`** (anchored on the next heading, verified to occur once):

SEARCH:
```markdown
### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```markdown
### AD-1347 S1 -- The Ship's Computer service that owns agent-created work: self-tasks, chief assignments and department requests (2026-10-23, #1627 slice 1 of 4)

- *Scope.* Slice 1 of #1627, two milestone commits. Files: new `agent_work.py` and `cognitive/crew_directory.py`; `workforce.py` (provenance key, lazy tables, claim gate, six methods), `agent_stop.py` (`SEAM_AGENT_WORK`), `cognitive/crew_delegation.py` (the shared chief lookup), `config.py` (`AgentWorkConfig`), `runtime.py`, `startup/shutdown.py`, `storage_declarations.py` (a note), the config-facade baseline, the config-profiles manifest, the generated config reference and tests. Contract: `prompts/ad-1347-s1-agent-created-work-service.md`. Later: S2 the chain's action tags; S3 claim, execution, activation notice and report-back; S4 the QUERY lookup.
- *D1 (home).* A Ship's Computer service with narrow injected interfaces, built by one opener, held as `runtime.agent_work` only when enabled; nothing calls it in S1.
- *D2 (authority).* A self-task is assigned to its creator; a chief assigns only a member of its own department; any other named assignee becomes an unassigned request (never an assignment) published to one department holding the named tool. A requester who holds the tool is told to create a self-task. Depth is read from the parent's stored record; 2 is allowed, 3 refused.
- *D3 (eligibility).* `check_permission` at read level per member (department, rank, agent type and the Captain's grants and restrictions), at creation and at every discovery and every new claim through a fail-closed store gate on both claim paths; stopped members excluded. A same-owner replay is AD-1187's receipt of a claim already persisted and is not asked again; S3 asks before it runs anything (A3).
- *Input (A3).* Every text and id input, and the origin's ids, must encode as UTF-8 (one helper); a JSON-decoded lone surrogate is a typed `invalid_request` (the origin: its own `ValueError`), never an exception or stored provenance.
- *D4 (guards).* Open caps 3 per agent, 8 per department, 24 ship-wide; 6 creations per agent per trailing hour; dedup on sha256 of (department, tool, NFKC case-folded whitespace-collapsed title) adds the asker as a watcher; a refused create is a typed `AgentWorkRefusal`.
- *D5 (persistence).* `work_items` plus `metadata["agent_work"]` (requests also carry AD-1187's `agent_pull`); two tables in `workforce.db`, created only when enabled. `--full` deletes them with `workforce.db`; the default reset keeps them, bounded by the 24 h TTL; `requester_sovereign_id` lets S3 recognise a slot now held by a new identity. Archive promotion does not read `workforce.db`.
- *D6 (seams).* A new `agent_work` seam counts a refused create; claim stays at `tool`, execution at `agentic_run` (S3); candidate questions use `standing_stop`. `S1_SCOPE` is unchanged until the work is reachable (S2).
- *D7 (provenance).* The origin is nested, so `_standalone_pull_item` does not refuse the item; a back-reference to a conversation is not room ownership.
- *D8 (expiry and notices).* The store's TTL sweep is the only expiry owner; notices are claimed before sending on a unique (item, recipient, kind) row, so a restart cannot send one twice; the requester and every watcher are recipients.
- *Disclosed effects.* `SEAMS` gains a name while off (no route reports it). `SystemConfig` gains an `agent_work` section. With the feature on, an agent-created request is claimable only by members its tool admits, also on the HXI's legacy claim route.
- *Reversal.* Revert the S1 commits. The two tables, if created, stay in `workforce.db` unused; agent-created items stay as ordinary work items. With the gate code gone, any open request becomes claimable by its department regardless of rank until its TTL ends it.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

**After both edits:** run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` to regenerate `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`; commit them with the trackers. Verify with `--check` and `tests/test_ad1184_ad_ledger.py`, never by comparing bytes.

**`docs/development/roadmap.md`:** no row; AD-1347 does not appear there (Absence AV8).

## 9. What this does NOT change

- The chain: no action tag, parser, proactive action or reply-pipeline change (S2). No execution, activation notice, report-back, decline or approval-inbox path (S3). No QUERY operation (S4).
- `agentic_dispatch.py` and its tool offer (wave 2 owns it); `resolve_agentic_identity` and `AgentIdentityTrust` are only imported.
- AD-845's Yeo `[CREATE_TASK]` and AD-1165's promotion keep `created_by="captain"` and their behaviour.
- AD-1346: no `decide`, no ticket, no work kind, no admission record.
- Tools: no `allowed_departments`, rank table or registration change.
- `assign_work_item` (the Captain's push) does not consult the gate.
- `_reject_reserved_metadata`: the `agent_work` key is not write-reserved (register R4).
- `RESET_TIERS`, the reset command, the archive and the AD-1341 promotion.
- `S1_SCOPE` and the stop routes' bodies.
- `config/system.yaml`.
- `tests/test_layer_boundaries.py`: no `ALLOWED_EXCEPTIONS` entry; `crew_directory.py` imports nothing from the consensus layer (A1).
- The census header's other numbers in `config-profiles.yaml` (`boolean_fields_reachable`, `default_true`, `default_false_armed_by_system_yaml`, `default_false_never_armed`, `measured_at_commit`): no test or script reads them, and they were already stale on the base (Absence AV12; register). Only `default_false` moves.
- Where `AgentWorkConfig` lives: it stays in `config.py` (D4) and is not moved into `config_models/` here (AD-1270 batch 10).

## 10. Mutation rows (39 rows; whole stripped lines, each occurring once in its file after §7)

Tier HIGH. Run each row against the named test on the contract-applied tree, after an unmutated baseline run that passes. Restore each file before the next row. None of these has been executed; the campaign of record is the build's.

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| A1 | `src/probos/agent_work.py` | `return active_stop(self._stop_gate, slot_id, SEAM_AGENT_WORK)` | `return None` | test 14 |
| A2 | `src/probos/agent_work.py` | `return standing_stop(self._stop_gate, slot_id) is not None` | `return False` | test 12 (stopped forge-1 claims via the legacy route); test 5 (`assignee_stopped`) |
| A3 | `src/probos/agent_work.py` | `member.slot_id, tool_id, ToolPermission.READ,` | `member.slot_id, tool_id, ToolPermission.NONE,` | test 10 (the ensign discovers); test 8 |
| A5 | `src/probos/agent_work.py` | `if claimant is None or claimant.department != record.department:` | `if claimant is None:` | test 12 (worf-1 claims an engineering request) |
| A7 | `src/probos/agent_work.py` | `if target.department == member.department and target.chief_slot_id == member.slot_id:` | `if target.department == member.department:` | test 6 (the peer pulaski to ogawa becomes an assignment) |
| A9 | `src/probos/agent_work.py` | `if self._holds_tool(member, tool_id):` | `if False:` | test 8 (`requester_holds_tool`) |
| A10 | `src/probos/agent_work.py` | `chosen = min(departments, key=lambda name: (-sum(1 for m in eligible if m.department == name), name))` | `chosen = departments[-1]` | test 7 (security instead of engineering) |
| A11 | `src/probos/agent_work.py` | `elif target is not None and target.department in departments:` | `elif False:` | test 6 (the aimed request goes to engineering, not security) |
| A12 | `src/probos/agent_work.py` | `if department not in departments:` | `if False:` | test 7 (medical is created) |
| A14 | `src/probos/agent_work.py` | `depth = record.depth + 1 if record is not None else 1` | `depth = 1` | test 16 |
| A15 | `src/probos/agent_work.py` | `if depth > self._config.max_depth:` | `if depth > self._config.max_depth + 1:` | test 16 |
| A16 | `src/probos/agent_work.py` | `if record.requester != member.slot_id:` | `if False:` | test 20 (no watcher) |
| A17 | `src/probos/agent_work.py` | `return " ".join(unicodedata.normalize("NFKC", title).casefold().split())` | `return title` | tests 20 and 21 |
| A18 | `src/probos/agent_work.py` | `if mine_recent >= self._config.max_created_per_agent_per_hour:` | `if mine_recent > self._config.max_created_per_agent_per_hour:` | test 18 |
| A19 | `src/probos/agent_work.py` | `if mine_open >= self._config.max_open_per_agent:` | `if mine_open > self._config.max_open_per_agent:` | test 17 |
| A20 | `src/probos/agent_work.py` | `if kind == KIND_REQUEST and department_open >= self._config.max_open_per_department:` | `if False:` | test 19 |
| A22 | `src/probos/agent_work.py` | `metadata["agent_pull"] = {"version": 1, "scope": "department", "department": department}` | `pass` | test 10 (nothing discovered) |
| A23 | `src/probos/agent_work.py` | `created_by=member.slot_id,` | `created_by="captain",` | test 2; test 23 |
| A24 | `src/probos/agent_work.py` | `ttl_seconds=self._config.ttl_seconds,` | `ttl_seconds=None,` | tests 2 and 22 |
| A25 | `src/probos/agent_work.py` | `if member is None or ref is None:` | `if False:` | test 3 (raises instead of refusing) |
| A26 | `src/probos/agent_work.py` | `and item.updated_at >= item.created_at + item.ttl_seconds` | `and False` | test 22 (`cancelled`, not `expired`) |
| A27 | `src/probos/agent_work.py` | `value.encode("utf-8")` | `value.encode("utf-8", "surrogatepass")` | tests 30 and 31 (every case: the surrogate is accepted; A3) |
| A28 | `src/probos/agent_work.py` | `if (required and not stripped) or len(stripped) > limit or not _encodable(stripped):` | `if (required and not stripped) or len(stripped) > limit:` | test 30 (the title, description and reason cases; A3) |
| A29 | `src/probos/agent_work.py` | `return type(value) is str and 1 <= len(value) <= MAX_ID_CHARS and value.strip() == value and _encodable(value)` | `return type(value) is str and 1 <= len(value) <= MAX_ID_CHARS and value.strip() == value` | test 30 (the requester, tool_id, assignee, department and spawned_from cases; A3) |
| A30 | `src/probos/agent_work.py` | `if type(value) is not str or len(value) > MAX_ID_CHARS or value.strip() != value or not _encodable(value):` | `if type(value) is not str or len(value) > MAX_ID_CHARS or value.strip() != value:` | test 31 (A3) |
| R2 | `src/probos/agent_work.py` | `store.set_agent_work_claim_gate(service.claim_allowed)` | `pass` | test 10 (the eligible member discovers nothing) |
| R3 | `src/probos/agent_work.py` | `await store.ensure_agent_work_schema()` | `pass` | test 20 (no watcher table); test 2 |
| R4 | `src/probos/agent_work.py` | `if not config.enabled:` | `if False:` | test 28 (with every collaborator the off opener returns a service and calls the store's schema and gate methods; A3, F4) |
| W1 | `src/probos/workforce.py` | `or not self._agent_work_claimable(item, resource)` | `or False` | tests 10, 12 and 13 |
| W2 | `src/probos/workforce.py` | `if AGENT_WORK_METADATA_KEY not in item.metadata:` | `if True:` | test 13 (discoverable with no gate); test 10 |
| W3 | `src/probos/workforce.py` | `"INSERT OR IGNORE INTO agent_work_notices (work_item_id, recipient, kind, claimed_at) VALUES (?, ?, ?, ?)",` | `"INSERT OR REPLACE INTO agent_work_notices (work_item_id, recipient, kind, claimed_at) VALUES (?, ?, ?, ?)",` | test 22 (a second claim returns True) |
| W4 | `src/probos/workforce.py` | `"INSERT OR IGNORE INTO agent_work_watchers (work_item_id, agent_id, added_at) VALUES (?, ?, ?)",` | `"INSERT OR REPLACE INTO agent_work_watchers (work_item_id, agent_id, added_at) VALUES (?, ?, ?)",` | test 20 (`add_work_watcher` returns True) |
| W5 | `src/probos/workforce.py` | `conditions.append("status NOT IN ('done', 'cancelled', 'failed')")` | `pass` | test 17 (a cancelled item still counts); test 20 |
| W6 | `src/probos/workforce.py` | `"AND n.recipient = r.recipient AND n.kind = ?) "` | `"AND n.kind = ?) "` | test 22 (the watcher is no longer due after the requester's claim) |
| W7 | `src/probos/workforce.py` | `and live[0].resource_id == resource_id` | `and live[0].resource_id == resource_id and self._agent_work_claimable(item, resource)` | test 29 (forge-1's replay after the restriction is not owned). An unchanged line: this mutant is the rejected option A, so the row pins F2's decision (A3) |
| D1 | `src/probos/cognitive/crew_directory.py` | `chief = resolve_post_agent(self._ontology, chief_post.id)` | `chief = None` | tests 5 and 26 |
| X1 | `src/probos/cognitive/crew_delegation.py` | `post.department_id == worker_post.department_id` | `True` | test 26 (laforge's chief becomes numberone-1); AD-865 tests |
| R1 | `src/probos/runtime.py` | `if self.config.agent_work.enabled:` | `if True:` | test W1 (`tests/test_ad1347_s1_wiring.py`): the off boot calls the opener once, so `opened == []` fails (A2; the outcomes alone survive, because the opener also returns None while off) |
| C2 | `src/probos/config.py` | `if self.max_open_per_agent > self.max_open_ship or self.max_open_per_department > self.max_open_ship:` | `if False:` | test 27 |

## 11. Verified Against Codebase (2026-10-22, worktree at `88f0e5b8`)

```
d:/ProbOS/.venv/Scripts/python.exe scripts/ad_ceiling.py
  CEILING: AD-1347 (GitHub issue titles, all states); NEXT: AD-1348; git subjects AD-1346; prompt filenames AD-1346
grep -n "def _standalone_pull_item" src/probos/workforce.py
  10952:    def _standalone_pull_item(item: WorkItem) -> bool:   (forbidden keys :10959-10962; parent_id :10955)
grep -n "def _pull_visible" src/probos/workforce.py
  10967 (department publication needs exactly {version, scope, department} :10975-10981)
grep -n "json_extract(metadata, '\$.agent_pull.scope') = 'department'" src/probos/workforce.py
  11051 (the SQL filter :11044-11055)
grep -n "async def create_work_item\|async def _insert_work_item\|async def get_work_item\|async def list_work_items" src/probos/workforce.py
  7621, 7667, 7740, 7752
grep -n "_TERMINAL_STATUSES = \|_WORK_ITEM_PUBLIC_COLUMNS = \|^SCAFFOLD_METADATA_FLAG\|def _reject_reserved_metadata" src/probos/workforce.py
  114, 1606, 1668, 1682
grep -n "async def _booking_transaction\|async def _expire_ttl_items\|async def _tick_loop\|def _check_eligibility" src/probos/workforce.py
  10883, 11760, 11745, 11715
grep -n "async def claim_work_item\|async def list_claimable_work_items\|async def _ready_for_pull\|async def transition_work_item" src/probos/workforce.py
  11266, 11065, 10997, 10716 (transition_work_item(self, work_item_id, new_status, source="system", ...))
grep -n "self._pull_resource_resolver = pull_resource_resolver" src/probos/workforce.py
  2744
grep -n "item = await store.create_work_item" src/probos/cognitive/turn_promotion.py
  1006 (assigned_to=agent_id :1010, created_by="captain" :1011)
grep -n 'created_by="captain"' src/probos/cognitive/dm/reply_pipeline.py
  2213
grep -n "def resolve_permission\|def check_permission\|if reg.restricted_to is not None\|if self._permission_store:" src/probos/tools/registry.py
  269, 336, 305, 322
grep -n "stopped = tool_refusal" src/probos/tools/registry.py
  389
grep -n "def get(self, tool_id\|def set_stop_gate\|def set_permission_store" src/probos/tools/registry.py
  199, 131, 123
grep -n "def _register_event_log_query_tool\|allowed_departments=(\"engineering\", \"science\", \"security\")\|enabled=config.agentic_dispatch.orchestrator_enabled" src/probos/startup/communication.py
  46, 74, 835
grep -n "def _register_work_item_pull_tools" src/probos/startup/communication.py
  215 (ensign holds discover read and claim write :225-245)
grep -n "work_item_store = WorkItemStore(" src/probos/startup/communication.py
  390
grep -n "def resolve_workforce_pull_resource" src/probos/runtime.py
  4170 (resolve_agentic_identity :4213; check_permission with agent_types :4232-4236)
grep -n "self.identity_service = IdentityService\|self.agent_stops = AgentStopService\|self.tool_registry.set_stop_gate\|self.ontology = comm.ontology" src/probos/runtime.py
  2821, 2776, 3294, 3341
grep -n "def resolve(self, key\|def _ref_for_slot" src/probos/identity_service.py
  79, 115
grep -n "def resolve_slot_id" src/probos/identity.py
  804
grep -n "def resolve_agentic_identity\|class AgenticIdentityUnresolved\|class AgenticIdentity:" src/probos/cognitive/agentic_dispatch.py
  428, 423, 416
grep -n "registry.check_permission(" src/probos/cognitive/agentic_dispatch.py
  3290 (event_log offer without agent_types; register R3)
grep -n "def _find_chief_post\|def _resolve_post_agent\|class CrewDelegator" src/probos/cognitive/crew_delegation.py
  206, 219, 70
grep -n "def get_crew_agent_types\|def get_post_for_agent\|def wire_agent\|def get_agents_for_post" src/probos/ontology/departments.py
  75, 84, 91, 117
grep -n "^SEAM_AGENTIC_RUN\|^SEAM_DELEGATION\|^SEAMS\|def refusal\|def active_stop\|def standing_stop\|def refuse_new_run\|def sender_text" src/probos/agent_stop.py
  68, 69, 70, 379, 563, 588, 600, 237
grep -n "STOP_CALLEES = \|GUARD_CALLEES = \|RECORDED = \|AGENT_WORK_METHODS = " tests/fixtures/ad1343_seam_census.py
  25, 27, 35, 30
grep -n "STOP_CHECK_SITES: dict\|STANDING_STOP_SITES: frozenset\|SEAM_INDEX: dict" tests/fixtures/ad1343_seam_registry.py
  21, 120, 157
grep -n "assert found == _STOP_CHECK_SITES\|assert set(_STOP_CHECK_SITES.values()) == declared\|assert standing == _STANDING_STOP_SITES" tests/test_ad1343_stop_seam_inventory.py
  72, 81, 202
grep -n "assert SEAMS == frozenset" tests/test_ad1343_agent_stop.py
  421
grep -n "assert taxonomy.SEAMS == agent_stop.SEAMS" tests/test_ad1346_admission_service.py
  179
grep -n "SEAMS: Final\[frozenset\[str\]\] = STOP_SEAMS" src/probos/admission/taxonomy.py
  21
grep -n "RESET_TIERS = \|\"files\": \[\"ward_room.db\", \"workforce.db\"\]" src/probos/__main__.py
  2641, 2673
grep -n "id=\"workforce.work-items\"" src/probos/storage_declarations.py
  20 (owner_module probos.workforce :22)
grep -n "SRP_MAX_BODY_LINES = \|SRP_MAX_DIRECT_METHODS = " scripts/check_architecture_principles.py
  187, 188
grep -n "class WorkforceConfig\|    workforce: WorkforceConfig = WorkforceConfig()" src/probos/config.py
  3562, 4010
grep -n "own_models: 227\|owned: 295\|public_names: 308\|field_definitions: 1869\|  AgentTierConfig: {kind: model, tier: owned}" docs/development/config-facade-baseline.yaml
  53, 54, 55, 51, 144
grep -n "assert counts\[\"field_definitions\"\] == 1869\|assert len(baseline\[\"models\"\]) == 228\|names=308" tests/test_ad1270e1_config_facade.py
  1553, 1556, 1791
grep -n "^ci_divergences:" docs/development/config-profiles.yaml
  592
grep -n "pop(\"command_policy\")\[\"rules\"\] == \[\]" tests/test_ad1152_agentic_correlation.py
  301 (whole-dump golden :487, :500-502)
grep -n "runtime.work_item_store = None" src/probos/startup/shutdown.py
  1673
grep -n "# AD-637: Update NATS subject prefix after ship commissioning assigns DID" src/probos/runtime.py
  3367
grep -n "async def _make_registry\|class _CrewAgent" tests/test_ad864_crew_assignment.py
  86, 46
grep -n "class _Instrument" tests/test_ad1187_agent_work_pull.py
  150
grep -n "def _config\|def _boot" tests/test_ad1346_admission_service_boot.py
  42, 50
grep -n "^TRUST_LIEUTENANT" src/probos/config.py
  218 (0.5; TrustNetwork prior 2/2 = 0.5, consensus/trust.py:1021)
```

**How each SEARCH was checked to occur once:** each block's distinctive line was grepped on this tree (hits above), and the surrounding lines were read in the same Read call. The new lines (`conditions.append("status NOT IN`, `or not self._agent_work`, `AND n.recipient`, `INSERT OR IGNORE INTO agent_work`) returned 0 hits in `workforce.py` before the build, so each mutation line occurs once after it.

**Amendment A1 evidence (2026-10-22, at the M1 build `3496b849` on `74a389af`):**

```
grep -n "assert document" tests/test_ad1185_config_profiles.py
  859 (the census default_false must equal the checker's count of default-off flags)
grep -n "default_false: \|boolean_fields_reachable\|default_true: " docs/development/config-profiles.yaml
  19 (445), 20 (223), 21 (225)
git show b6c5734d -- docs/development/config-profiles.yaml
  one hunk: default_false 222 -> 223, nothing else (precedent)
grep -n "REMAINING_TRUE_LEAVES" tests/test_ad1270e2i_agentic_models.py
  160 (alphabetical tuple, opens with "BootCampPhaseConfig" at 161), 526 (the sorted comparison)
grep -n "ALLOWED_EXCEPTIONS = \|\"cognitive\": {\|def test_no_undocumented_cross_layer_imports" tests/test_layer_boundaries.py
  60, 51 (cognitive may import knowledge, substrate, mesh), 187 (ast.walk over every import, TYPE_CHECKING included: 176-183)
grep -n "class AgentIdentityTrust\|trust_network: AgentIdentityTrust" src/probos/cognitive/agentic_dispatch.py
  411 (one method, get_score at 412), 433
grep -n "AgentIdentityTrust" src/probos/cognitive/crew_assignment.py src/probos/cognitive/self_telemetry_domains.py
  crew_assignment 33, 56; self_telemetry_domains 15, 56, 158 (precedents)
grep -n "def get_score" src/probos/consensus/trust.py
  1017
grep -n "_OUTPUT = " scripts/gen_config_reference.py
  25 (docs/development/config-reference.md)
grep -n "gen_config_reference.py" scripts/run_test_gate.py
  1101 (preflight, --check)
grep -n "def test_the_reference_matches_the_models" tests/test_config_reference_current.py
  41 (runs the generator with --check in a subprocess)
grep -n "^## .workforce.\|^## .temporal." docs/development/config-reference.md
  2333, 2346
```

**A3 additions (2026-10-23, frozen candidate `8ebf10f2`):**

```text
src/probos/workforce.py
  11034-11059: _ready_for_pull; 11047: or not self._agent_work_claimable(item, resource)
  11493: owned_before = any(b.resource_id == resource_id for b in bookings)
  11494-11503: the same-owner replay returns item, live[0] before _ready_for_pull (:11518)
  11499: and live[0].resource_id == resource_id   (row W7's line; occurs once)
tests/test_ad1187_agent_work_pull.py
  442-461: test_claim_replay_precedes_readiness_capacity_and_publication (trust 0.99, TTL elapsed,
           missing dependency, proficiency 0.1: the replay returns the same booking)
  2245-2270: test_provider_failure_after_commit_recovers_by_exact_id_replay
src/probos/tools/work_item_pull_tool.py
  316-318: "owned=True confirms persisted ownership or same-owner replay, not execution or resume"
  367-371: claim_work_item(actor, work_item_id=wanted, agent_pull=True, prepare_claim=prepare); None -> not_claimable
src/probos/routers/workforce.py:398-402: claim_work_item(resource_id, work_type=..., department=...)  (no work_item_id)
src/probos/tools/permissions.py:110-117: async def issue_grant(self, agent_id, tool_id, permission, *, is_restriction=False, ...)
src/probos/agent_work.py (pre-A3 lines)
  92-99 _text; 102-104 _identifier; 115 material.encode("utf-8"); 126-131 AgentWorkOrigin.__post_init__
  299-301 create_self_task's tool id check; 335-340 request_work's id checks; 449-457 _admit's input check
  579: if not config.enabled:
src/probos/config_models/knowledge.py:361-362: enabled: bool = True / db_path: str = ""
src/probos/config.py:2631-2645: resolve_archive_db_path (empty db_path -> the platform default under the home directory)
src/probos/startup/cognitive_services.py:671-689: if config.archive.enabled: (lazy import :673; resolve :681; ArchiveStore initialize :689)
src/probos/infrastructure/backup_inventory.py:229-240: lazy import; resolves only when archive.enabled and backup_include_archive_root
tests/fixtures/runtime_lifecycle.py:74-90: lifecycle_config redirects archive.db_path under tmp_path
tests/test_ad1346_admission_service_boot.py:42-47: _config sets no archive field
src/probos/ontology/loader.py:48-56: OntologyLoader.__init__ stores its paths only
src/probos/cognitive/crew_directory.py:30-36: RuntimeCrewDirectory.__init__ stores its three collaborators
tests/test_ad864_crew_assignment.py:86-93: _make_registry(agents) -> a real AgentRegistry
```

## Absence Verified (2026-10-22)

| # | Claim | Run | Found | Holds |
|---|---|---|---|---|
| AV1 | No `agent_work` symbol, module or metadata key exists in `src/probos` | Grep `agent_work\b\|AgentWork\|crew_directory\|CrewMember\b\|CrewDirectory` in `src/probos` | only `AgentWorkingMemory` and `AgentWorkspace` hits | yes |
| AV2 | Only the pull tool and the HXI route call `claim_work_item` | Grep `\.claim_work_item\(` in `src/probos` | `work_item_pull_tool.py:367`, `routers/workforce.py:398` | yes; the gate covers both through `_ready_for_pull` |
| AV3 | Archive promotion does not read `workforce.db` | Grep `workforce\|work_item` in `knowledge/archive_promotion.py` | 0 | yes |
| AV4 | No test pins `workforce.db`'s whole table set; the store registry pins tables only for baselined modules | Grep `sqlite_master` in workforce-related tests; `check_store_registry.py:55-57` rule 11 | `test_ad1192_owned_steps_store.py:265` (`>=` subset), `test_ad1325_economic_calibration.py:1072` (`LIKE 'completion_calibration_%'`) | yes |
| AV5 | test_ad1152 is the only whole-`SystemConfig()` dump golden | Grep `SystemConfig\(\)\.model_dump\|default_config_sha\|canonical_dump_sha256` in tests | e2 tests compare per-field sub-dicts; facade tests use the regenerated baseline | yes |
| AV6 | No test compares `S1_SCOPE`'s text | Grep `S1_SCOPE` in `*.py` | tests compare `== S1_SCOPE` (the object) and phrase membership | yes; S1_SCOPE is untouched anyway |
| AV7 | `_find_chief_post` has no other caller | Grep `_find_chief_post\|find_chief_post` in `*.py` | `crew_delegation.py:122, :206` | yes |
| AV8 | The roadmap has no AD-1343, AD-1346 or AD-1347 row | Grep in `docs/development/roadmap.md` | 0 | yes |
| AV9 | No prompt `bf-912*` is in this tree to collide with | Glob `prompts/bf-912*.md` | none | yes; BF-912's contract lives with the orchestrator |
| AV10 | Agents have no `agent_uuid` attribute, so the pull resolver keys on `agent.id` | Grep `agent_uuid\|sovereign_id` in `substrate/agent.py` | only `sovereign_id` at :44 | yes |
| AV11 | `_stop_gate` initial value | not enumerated (registry `__init__` lines 108-121 do not show it) | — | **not held as proven**; the fixtures call `set_stop_gate` before any invoke, so the tests do not depend on it |
| AV12 (A1) | No test or script reads the census header's numbers other than `default_false` | Grep `boolean_fields_reachable\|default_true"\|never_armed\|armed_by_system_yaml` in `*.py`; Grep `\["census"\]` in `*.py` | 0; one hit, `test_ad1185_config_profiles.py:859` (`default_false` only) | yes |
| AV13 (A1) | The only docs that name config sections are the three files this contract covers | Grep `work_board_reconciler` and the backticked `workforce` in `docs/` | `config-profiles.yaml`, `config-facade-baseline.yaml`, `config-reference.md` | yes: §7.8, §7.10, §7.14c |
| AV14 (A1) | No doc or seam manifest names the moved chief lookup or `_ready_for_pull` | Grep `_find_chief_post\|_resolve_post_agent\|_ready_for_pull\|crew_delegation` in `docs/` | 0 | yes |
| AV15 (A1) | The new modules give the tree scanners nothing to flag (no quoted `*.db` literal, no event emission, no `ui_scaffold`, no `create_task`) | Grep in `agent_work.py` and in `cognitive/crew_directory.py`, one file per call | one `.db` hit, `agent_work.py:597`, inside a longer message string that `test_ad1265_backup_coverage.py:51`'s quoted-literal pattern does not match; nothing else | yes |
| AV16 (A1) | No test pins who imports `AgentIdentityTrust` | Grep `AgentIdentityTrust` in `*.py` | `agentic_dispatch.py:411, :433`; `crew_assignment.py:33, :56`; `self_telemetry_domains.py:15, :56, :158`; no test | yes |
| AV17 (A3) | Only the pull tool reaches the same-owner replay in production | Grep `\.claim_work_item\(` in `src/probos` | `work_item_pull_tool.py:367` (`work_item_id`, `agent_pull=True`); `routers/workforce.py:398` (no `work_item_id`, so never the replay branch) | yes |
| AV18 (A3) | No boot path resolves the archive path while the archive is off | Grep `resolve_archive_db_path` in `src/probos` | `config.py:2631` (definition); `startup/cognitive_services.py:673, :681` (inside `if config.archive.enabled:` at :671); `infrastructure/backup_inventory.py:229, :240` (only when `enabled`, :236); `__main__.py:3205-3227` (CLI commands, not the boot) | yes |
| AV19 (A3) | No test outside the two new files imports `probos.agent_work` | Grep `agent_work import\|probos\.agent_work\|AgentWorkOrigin` in `tests/` | `test_ad1347_s1_agent_work.py`, `test_ad1347_s1_wiring.py` | yes |

## 12. Deterministic gate checks, resolved up front

1. **Phantom precheck** (`scripts/phantom-api-precheck.ps1`).
   - Every new class and method is defined in this contract's python fences, so its symbol check skips them.
   - No line types a variable as `SystemConfig`; configuration is built through `model_copy(update=...)` and `AgentWorkConfig` locals, so `agent_work` is never read off a typed `SystemConfig` variable.
   - The contract's python fences call no `SystemExit`, no `AssertionError` and no `SimpleNamespace`, and no `unlink` with `missing_ok`.
   - The test doubles are underscored (`_SlotIdentities`, `_Instrument`, `_Ship`). Test W1's spy is a nested coroutine function, `_counted_opener`, installed with the `monkeypatch` fixture, so no new line assigns a constructed class to a name (A2).
   - New store methods are called positionally; the kwarg checker skips methods absent from `src` anyway.
   - Expected result on the built tree: clean.
   - Census safety of new names (`ad1343_seam_census.py`): `claim_allowed`, `_requester_stop`, `_stopped_now`, `_holds_tool`, `_commit`, `_admit`, `notice_recipients`, `terminal_notices_due`, `claim_notice`, `eligible_members` and the test helpers `_invoke`, `_discovered`, `_claimed`, `_request` and `_self_task`, and test W1's spy `_counted_opener` with its locals `real_opener` and `opened` (A2), are not in `STOP_CALLEES`, `GUARD_CALLEES`, `RECORDED` or `AGENT_WORK_METHODS`. The only recorded calls the new code makes are `active_stop` and `standing_stop`, registered in §7.3.
   - A3's names: `_encodable` and, in the tests, `_SURROGATE`, `_SURROGATE_CASES`, `archive_resolutions`, `_resolve_under_tmp`, `_schema_spy`, `_gate_spy` and the locals `store_calls`, `off_directory`, `off_stops`, `clean`, `poisoned` and `create` are not in `STOP_CALLEES`, `GUARD_CALLEES`, `RECORDED` or `AGENT_WORK_METHODS`; the only new call in `src` is `encode` on a str, which no set records. Test 28's collaborators are bound to `off_directory` and `off_stops`, names with no method call elsewhere, so no keyword line constructs a class.
2. **Store registry** (`check_store_registry --check`): no baseline change. The new `CREATE TABLE`s are in `probos.workforce`, the declared owner of `workforce.work-items`.
3. **Architecture** (`check_architecture_principles --check`):
   - `AgentWorkService` has 13 direct methods, under 500 lines.
   - `RuntimeCrewDirectory` has 4.
   - No direct `sqlite3.connect` or `aiosqlite.connect` in source; the tests use `sqlite3.connect` to read, which is allowed.
   - No `asyncio.create_task`.
   - Layers: `probos.agent_work` is an unranked top-level module; `probos.cognitive.crew_directory` imports it and `probos.cognitive.*`, and under `TYPE_CHECKING` the ontology (core) and the substrate registry (allowed for cognitive). It imports nothing from the consensus layer: trust is typed with `AgentIdentityTrust` (A1), so `tests/test_layer_boundaries.py` needs no `ALLOWED_EXCEPTIONS` entry. The type is an existing class, so A1 adds no new function, method or exception name to check against the census sets.
4. **Config facade:** §7.8's exact diff, then `--check`; §7.9's counts. **Config reference** (`gen_config_reference.py --check`, a preflight step, and `tests/test_config_reference_current.py`): regenerated in §7.14c. **True-leaf pin:** §7.14b.
5. **Config profiles** (`check_config_profiles --check`): `agent_work.enabled` is classified (§7.10 pair 1), not frozen; the census `default_false` is 224 (§7.10 pair 2).
6. **AD ledger:** `gen_ad_ledger.py` after §8; `--check`; `tests/test_ad1184_ad_ledger.py`.
7. **Selection:** `config.py` is a blast-radius entry, so the impact selector picks the full suite; the single receipted broad gate after review covers it.
8. **Line endings:** match CRLF on edit; new files LF.

## 13. Prior Art and Blind Spots

| Source | What it shows | Decision |
|---|---|---|
| #1627's own prior art (AD-1165, AD-1187, AD-845/846, Contract Net Protocol, CrewAI) | durable item, governed pull, announce then first eligible claim | **Absorbed as drafted** |
| A2A task lifecycle ([sim.ai](https://docs.sim.ai/integrations/a2a), [Svix glossary](https://www.svix.com/resources/glossary/a2a-protocol/)) | `canceled` (the client stopped it) is distinct from `rejected` (the agent refused it) | **Adapt:** S1 labels a TTL end `expired`, distinct from `cancelled`; decline-with-reason maps to "rejected" in S3 (noted, not built) |
| Codex CLI loop defences ([Daniel Vaughan](https://codex.danielvaughan.com/2026/07/06/infinite-agentic-loops-ial-scan-unbounded-feedback-codex-cli-rollout-budget-loop-defence/)) | `max_depth` and `max_threads` bound recursive delegation and fan-out | **Absorb:** the depth limit and the open caps |
| Waxell recursion bound ([docs](https://waxell.ai/docs/observe/governance/recursion-bound)) | a counter the runtime does not maintain makes the check a no-op | **Absorb:** depth is read from the parent's stored record, never supplied by the caller |
| Reference projects (`docs/research/reference-projects.md`, judged on 2026-10-22) | Relevant rows are all within their interval: CrewAI and AutoGen 2026-09-03, Hermes 2026-06-06 (180-day interval) | Nothing overdue to examine; no row updates |

**Blind spots handled:**
1. A requester who could use the tool itself is refused with "create a self-task" (#1627 blind spot 3).
2. Watchers are a drop point, so they are always notice recipients.
3. Ensign-only departments mean no eligible member, refused at creation.
4. Rows left by an earlier enabled run are not claimable while off (gate fails closed).
5. A slot reused after a default reset is recorded through `requester_sovereign_id`.
6. A page of `SCAN_LIMIT` rows is refused, never counted short.
7. The legacy claim route is gated too.

## 14. Diff Reviewer: properties to verify

1. No path writes `created_by="captain"` or any value other than the resolved slot; a None resolution refuses before any write.
2. The provenance is nested under `metadata["agent_work"]`; no new top-level `thread_id`, `room_id` or `session_id` key and no `parent_id` on an agent-created item.
3. A request's `agent_pull` has exactly three keys (`_pull_visible`).
4. `_agent_work_claimable` returns True for every item without the provenance key, so all existing pull behaviour is unchanged, and False with no gate.
5. The gate is synchronous and does no I/O (directory and registry reads only); it never raises into the store.
6. Eligibility always passes `agent_types` and READ, and is asked at creation, at every discovery and at every new claim on both routes (every acquisition of ownership). A same-owner replay of a claim already persisted acquires nothing and is AD-1187's receipt: it precedes readiness, as it does for a changed trust requirement, TTL or dependency, so it is not asked again (test 29; row W7 pins that choice). S3 asks again before it executes anything (A3, F2).
7. The stop: one counted `active_stop` at `SEAM_AGENT_WORK` per refused create, before any store write; candidate questions use `standing_stop`; the census rows in §7.3 match the code's (file, qualified name, callee).
8. One lock spans dedup, guards and the insert; dedup runs before the guards; a dedup hit by a different requester adds exactly one watcher.
9. The service has no loop, no `create_task` and no status transition; expiry is the store's sweep.
10. `claim_work_notice` is insert-or-ignore on a primary key; `list_due_work_notices` includes every watcher and excludes only pairs already claimed.
11. `ensure_agent_work_schema` is reached only through the opener (by reading: no other caller in `src`; row R3 pins that the opener calls it). The runtime calls the opener only when `config.agent_work.enabled` (test W1 counts the calls, none off and one on: row R1, A2), and the opener itself returns None while off, touching nothing even with every collaborator present (test 28 spies the store's schema and gate methods: row R4, A3). While off, `runtime.agent_work` is None and `workforce.db` gains no table (test W1).
12. `crew_delegation` behaviour is unchanged (pure extraction); the AD-865 tests pass unmodified.
13. `config.py` changes only by `AgentWorkConfig` and one `SystemConfig` field; the facade baseline diff is exactly §7.8.
14. No `decide`, ticket or tool permission change; `agentic_dispatch.py` is not edited.
15. Each updated pinned test records its reason inline; no pin is deleted.
16. `cognitive/crew_directory.py` imports nothing from the consensus layer, even under `TYPE_CHECKING`; its `trust_network` is typed `AgentIdentityTrust`; `tests/test_layer_boundaries.py` is unchanged.
17. Each config surface changes only by the new section: `config-reference.md` gains exactly one `agent_work` section between `workforce` and `temporal` and is byte-equal to the generator's output; the census header changes only `default_false` (223 -> 224); `REMAINING_TRUE_LEAVES` gains exactly `AgentWorkConfig`.
18. Every text and id input of both create methods, and the origin's ids, must encode as UTF-8, by one helper (`_encodable`) used by `_text`, `_identifier` and the origin's own check; a value that does not is `invalid_request` before any lookup or write, and an origin id raises `agent_work_origin_id_invalid` (tests 30 and 31; rows A27 to A30; A3, F3).
19. The wiring boots never resolve the Ship's Archive path: `_boot_config` turns the archive off and the `archive_resolutions` spy stays empty, so no boot opens the live vessel's archive (A3, F1).

Consumers that must accept the change: `WorkItemStore._ready_for_pull` (discovery and claim), `ToolRegistry.check_and_invoke`, the AD-1343 census tests, the config facade and profile checkers, and the runtime start and shutdown.

## 15. Acceptance criteria

- Every test in §6 passes with the focused commands. The updated pins pass, including the three A1 pins. The listed `--check` scripts pass, including `gen_config_reference.py --check` (§7.14c). `tests/test_layer_boundaries.py` passes with no new exception (§7.13).
- With the default configuration the runtime never calls the opener, nothing is built and `workforce.db` is unchanged (test W1's call count and tables, tests 13 and 28, test_ad1152); the off opener touches nothing even with every collaborator (test 28, A3).
- No wiring boot resolves or opens the Ship's Archive (tests W1 and W2, A3).
- Acceptance 3, 5 (the S1 half: creation and claim refused for a stopped agent), 6 and 7 of #1627 are each covered by the named tests. The S1 half of acceptance 2 is test 10, which S2 and S3 extend.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
