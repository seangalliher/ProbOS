# BF-903: visiting-officer capabilities are checked where the officer acts, and the capability names have one owner

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-22

**Mechanical repair before the contract was committed (orchestrator, 2026-10-22; no decision changed):** section 7.5's third pair no longer quotes the two lines that end in `session_ttl_seconds=0`. `scripts/phantom-api-precheck.ps1` flags that integer literal against `register`'s float annotation (`type_shape_mismatch`), and the staged contract has to pass the precheck at preflight. The pair now changes only the first `["c"]` case; the other two cases keep their text and still raise `ValueError` on their own earlier checks (no capability, a ttl of zero), which `register` runs before the new capability check. The precheck also lists thirteen candidates for the new `check` and `attach_visiting_officers` methods; they exist only once the code is built, and the check is re-run on the built tree.

**Amendment A1:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-22: M3 (sections 7.13-7.19 and 8b), recognition of a visitor by its DID or its certificate UUID, and three corrections (section 16).

**Amendment A2:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-22: the capability vocabulary is defined in `config_models/crew.py` and re-exported by `probos.visiting_officers`, because `crew.py` may import nothing from `probos`; W8 enables the Ward Room (section 17).

**Amendment A3:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-22: the M1 review's six findings (round 1). Approve checks a pending row's names before it consumes the row, a repeated request is checked before its idempotent return, the CLI prints a refused name as text, and a malformed agent DID costs no lookup; the offline issuer and the restore path are recorded for the AD that wires pairing (section 18).

**Amendment A4:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-22: the M1 review (round 2) and the M2 and M3 reviews (round 1). An expired pending row answers "expired" whatever names it holds; the assignment routes check every member before their first write and the teaching route answers 403; the MCP walk counts a container before it reads one; P2 and P3 deliver over a real bus and Q1 asserts that no peer is registered; a `str`-subclass actor id is recorded (section 19).

**Mechanical repair before A4 was committed (orchestrator, 2026-10-22; no decision changed):** section 7.12c's first pair (the import of `VisitorScopeRefused` in `routers/procedures.py`) no longer quotes the line below the imports that builds the module's router. `scripts/phantom-api-precheck.ps1` flags a call to FastAPI's router class in a python fence (it is not a ProbOS class), and the staged contract has to pass the precheck at preflight. The pair now anchors on the single `from probos.routers.deps import get_runtime` line, which occurs once in the file; the built file is the same.

**Status:** M1 and M2 are build-ready on `origin/main` `0e122174`. M3 (recognition by either key form, the channel adapters and the inbound MCP server) is sections 7.13-7.19 and 8b, in the same PR; M3 closes #1581. **Tier HIGH.** No new AD or BF number. Both flags stay off: `config/system.yaml:297` and `:933` are not edited. AD-1342 stays paused.

**Tests:** four new files.
- M1 `tests/test_bf903_visitor_scope.py`: 10 functions, 16 cases (A3 adds V9 and a third V5 case; A4 adds V10, two cases; M3 widens V7 and V8 in place, section 7.14).
- M2 `tests/test_bf903_ward_room_scope.py`: 11 functions, 38 cases (A4 adds W9-W11).
- M2 `tests/test_bf903_seam_was_open.py`: 1 case. It is written against names that exist before BF-903, so on today's tree it fails for its premise, not on an import.
- M3 `tests/test_bf903_channel_and_mcp.py`: 9 functions, 23 cases (A4 adds Q4).
- Updated, each with an inline reason: `tests/test_ad701_visiting_officers.py` (6 call sites) and `tests/test_ad802_pairing.py` (1 test) in M1; `tests/test_bf804_pairing_notification.py` (2 tests) and `tests/test_ad807_discord_refresh.py` (1 test) in M3.

**Line endings:** every edited working copy is CRLF (`core.autocrlf=true`). The SEARCH blocks are LF; match and write with the file's own line endings. New files are written LF.

---

## 0. Premise: what is present on this tree

| Clause of #1581 | State | Evidence |
|---|---|---|
| The seam is enforced on Ward Room and router paths | absent | `has_capability(` has no production caller (Absence Verified 1) |
| A path that carries a visitor's own DID into the Ward Room | none today | `runtime.pairing_service` is never assigned (AV2); `paired_did` is never read (AV3); MCP dispatches as the handling agent (`mcp_server.py:474-479`) |
| The HXI routes take actor ids from the request body | present (impersonation) | `routers/wardroom.py:282`, `:352`, `:368`, `:382`, `:396` |
| A sovereign identity is keyed by its DID or by its bare certificate UUID | present (A1) | `identity.py:152-163` (BF-907), `:804-827`; an author's Ward Room episode is stored under the id it posts as (`ward_room/threads.py:564-578`, `cognitive/episodic.py:472-483`) |
| One owner for the names | absent | `config_models/crew.py:316-318` (read by nothing, AV5) against `security/pairing/service.py:27` |
| MCP binding | absent | `mcp_server.py:198`, `:331` |
| Expiry at use | partly met | `has_capability` reads expiry (`visiting_officers.py:169`); `get` does not (`:162-163`) |

## 1. Problem

AD-701 says the registry is the enforcement seam and that consumers check `has_capability` before acting. No consumer does. A Ward Room write or read for a visiting officer's DID succeeds whatever its session holds, or with no session at all (`tests/test_bf903_seam_was_open.py`). The capability names live in two unrelated places, and nothing refuses a misspelt one.

## 2. Solution overview

- **M1.**
  - The four names are defined once, in `config_models/crew.py`, and re-exported by `probos.visiting_officers` (A2); any other name is refused at `register`, at pairing request and approve, in `probos pairing approve` and at config parse.
  - The registry gains `capability_refusal` and `check`; `get` hides an expired session.
  - The module gains `is_visiting_identity` (by certificate) and the one guard, `require_visitor_capability`.
- **M2.**
  - The Ward Room facade calls the guard at the eleven methods that act for an actor id. The twelve test cases count the DM channel twice, once per participant side.
  - (A4) `check_subscribe` makes `subscribe`'s check alone, so `AssignmentService` checks every member before its first side effect; the teaching route lets a refusal reach the 403.
  - A write needs `dm.send` in a DM channel and `ward_room.post` elsewhere.
  - Finalize attaches the registry, and the API answers a refusal with 403.
- **M3** (Amendment A1, sections 7.13-7.19).
  - A visitor is recognised by its DID or its bare certificate UUID; `require_session_capability` checks a known visitor's session.
  - A paired channel sender may send an `@callsign` DM, with `dm.send`, and nothing else; an unreadable pairing store refuses the message.
  - The inbound MCP server refuses a `tools/call` whose arguments name a visiting officer, before either dispatch branch.

## 3. Decisions

- **D1 (premise).** No visitor-identity path into the Ward Room exists today; the routers' body-supplied actor ids are the only way a visiting DID arrives. The guard covers every caller of the facade, present and future.
- **D2 (where; recognition).**
  - (A) **Chosen:** one guard function, applied at the facade now and at the edge entries in M3. A visitor is recognised by its certificate's agent type, named by its did:probos agent DID or (A1) its bare certificate UUID.
  - (B) Channel layer only: rejected; it misses the routers and future paths.
  - (C) Recognition by registry membership: rejected; it fails open at expiry.
  - (D) Recognition by DID shape: rejected; real visiting DIDs have the crew shape.
  - Entries with no actor id (`get_thread`, `list_threads`, `get_post`, `get_recent_activity`) are guarded at the visitor path's own entry (M3, AD-1342).
  - `create_channel`, `unsubscribe` and the queries that take a subject id stay unguarded (section 9; register).
- **D3 (names).**
  - (A) **Chosen:** a closed set in code; configuration chooses among the names.
  - (A2) **Where:** `config_models/crew.py` defines the four names, `VISITOR_CAPABILITIES` and the one membership test `undeclared_capabilities`. It imports nothing from `probos` (`tests/test_ad1270e2g_crew_models.py:680-690`), so the config default and validator need no import; `probos.visiting_officers` re-exports them, as `cognitive/dreaming.py:47` reads AD-1326's bound from `config_models/cognition.py:15`. Rejected: relaxing that pin (a config model would depend on a runtime module), validating only at the facade or at the consumer (the facade needs the same import; nothing consumes the list, AV5), and two copies pinned equal (two owners).
  - (B) A set configuration can extend: rejected.
  - (C) Warn only: rejected.
- **D4 (MCP, built in M3).** (A) **Chosen:** refuse arguments that name a visiting officer (any key or string value, at any depth, that is exactly its DID or certificate UUID), and refuse unread arguments of more than 10,000 values. (B) A per-visitor token: deferred to AD-1342, which should build it on the MCP authorization spec. (C) Record only: rejected.
- **D5 (the record).**
  - `VISITING_OFFICER_REFUSED` through the registry's emitter, plus a warning; with the registry off, the warning alone.
  - Reason codes: `visitor_session_unknown`, `visitor_session_expired`, `visitor_capability_missing`, `visitor_registry_off`.
  - No `EventType` member: the registry's existing events are strings too. No admission record (#1604).
- **D6 (expiry).** `capability_refusal`, `check` and `get` read the clock at use; `deregister` already removes the session.
- **D7 (M3, coupled).** `_check_pairing`'s `resolve_did` failure fails closed. Slash commands and natural language for a paired sender are refused, because no declared capability grants them. The Captain may overrule.
- **D8 (tier).** HIGH.

**Disclosed effects (M1, M2 and M3)**
1. These now raise `UnknownCapabilityError` (a `ValueError`) for an undeclared name: `register`, `request_pairing`, `approve_pairing`, `probos pairing approve` (prints the reason and returns 1) and `VisitingOfficersConfig`.
   - A `system.yaml` that lists an undeclared name under `visiting_officers.default_capabilities` no longer loads.
   - AD-802's example `--cap tool.use` is refused.
   - An unexpired pending row minted before BF-903 that holds an undeclared name is refused at approve before it is consumed, and kept: a declared `--cap` approves it (A3). An expired pending row is consumed and refused as expired (`UnknownPairingCode`), whatever names it holds (A4).
   - A repeated `request_pairing` that names an undeclared capability is refused even when the sender holds an unexpired pending row (A3).
   - `probos pairing approve` prints a refusal as text: Rich markup and emoji codes in a name are not interpreted (A3).
2. `VisitingOfficerRegistry.get` returns None for an expired session.
3. A visiting DID at a guarded entry is refused unless a live session holds the capability; with no registry attached, it is always refused. The API answers 403 `{"error": "visitor_scope_refused", "capability", "reason", "surface"}`.
   - (A4) So do `POST /api/assignments` and `POST /api/assignments/{id}/members`, which check each member's `ward_room.read` before a channel, a subscription or a row exists and then write nothing, and `POST /api/procedures/teach`, which no longer turns the refusal into 200.
   - (A4) An assignment is admitted at entry: a session that lapses between that check and its subscription is refused there, recorded, and logged by the service's existing handler (register R11).
4. Crew, Captain and system ids behave as before. A slot id, "captain" and "system" cost no lookup or query; a crew certificate's DID or bare UUID costs one in-memory certificate lookup (A1).
5. (M3) A visiting officer's bare certificate UUID is refused wherever its DID is.
6. (M3) A paired channel sender's slash command or natural language is answered with a refusal naming the reason; its `@callsign` DM needs a live `dm.send` (always refused with no registry).
7. (M3) A `resolve_did` failure refuses the message with `PairingLookupError`, a `PairingNotificationError`: Gmail leaves the mail unread and retries; Slack, Telegram, Matrix and Discord drop it with a log; Teams answers HTTP 200 with the channel-only text.
8. (M3) An MCP `tools/call` whose arguments name a visiting officer, or hold more than 10,000 values, is refused with JSON-RPC -32602 and `MCP_BRIDGE_FAILED`, through either door. (A4) The walk counts a container's children from its length before it reads them, so a refused call's wide container is never iterated; the threshold is unchanged.

## 4. Milestones

One Builder delegation and one local commit per milestone, built in order. Run each focused gate at `-n 0`. Stage explicit paths only; never `git add -A`.

| Milestone | Production files | Tests | Focused gate |
|---|---|---|---|
| **M1** | `visiting_officers.py` (7.1), `config_models/crew.py` (7.2), `security/pairing/service.py` (7.3), `__main__.py` (7.4) | new 7.7; update 7.5, 7.6 | `tests/test_bf903_visitor_scope.py tests/test_ad701_visiting_officers.py tests/test_ad802_pairing.py tests/test_ad1270e1_config_facade.py tests/test_ad1270e2g_crew_models.py tests/test_ad1346_identity_service.py tests/test_channel_base.py tests/test_bf804_pairing_notification.py` |
| **M2** and trackers | `ward_room/service.py` (7.8), `startup/finalize.py` (7.9), `api.py` (7.10), `assignment.py` (7.12b, A4), `routers/procedures.py` (7.12c, A4); trackers (section 8) | new 7.11, 7.12 | `tests/test_bf903_ward_room_scope.py tests/test_bf903_seam_was_open.py tests/test_bf903_visitor_scope.py tests/test_ward_room.py tests/test_ward_room_dms.py tests/test_ward_room_agents.py tests/test_api_wardroom.py tests/test_ad615_wardroom_db_hardening.py tests/test_ad613_wardroom_performance.py tests/test_ad1229_message_receipts.py tests/test_ad1229_receipt_facts.py tests/test_ad630_leadership_feedback.py tests/test_bf771_intent_authorization.py tests/test_assignment.py tests/test_api_assignment.py tests/test_database_hardening.py tests/test_ad486_birth_chamber.py tests/test_observational_routing.py tests/test_ad1184_ad_ledger.py` |
| **M3** and trackers | `visiting_officers.py` (7.13, on M1's text), `channels/base.py` (7.15), `federation/mcp_server.py` (7.16); trackers (section 8b) | new 7.19; update 7.14, 7.17, 7.18 | `tests/test_bf903_channel_and_mcp.py tests/test_bf903_visitor_scope.py tests/test_bf903_ward_room_scope.py tests/test_bf903_seam_was_open.py tests/test_ad701_visiting_officers.py tests/test_ad802_pairing.py tests/test_channel_base.py tests/test_bf804_pairing_notification.py tests/test_bf803_gmail_ack.py tests/test_ad764_gmail.py tests/test_ad803a_telegram.py tests/test_ad804_slack.py tests/test_ad805_teams.py tests/test_ad806_matrix.py tests/test_ad807_discord_refresh.py tests/test_ad472_channel_adapters.py tests/test_discord_adapter.py tests/test_callsign_routing.py tests/test_bf875_mcp_inbound_auth.py tests/test_ad480_federation_mcp_a2a.py tests/test_ad597_mcp_server_apps.py tests/test_bf884_sidecar_bind_failure.py tests/test_layer_boundaries.py tests/test_ad1184_ad_ledger.py` |

**Hard stops**
- `config_models/crew.py` imports nothing from `probos`, at any depth (A2; `tests/test_ad1270e2g_crew_models.py:680-690`). If a config-facade, config-model or layer test fails because `probos.visiting_officers` now imports `probos.config_models.crew` at load, stop and report; do not move the names back or import them inside a function.
- If an existing test fails because it registered or paired with an undeclared name, update it with an inline `BF-903 (#1581)` reason and never delete it. Stop and report any other failure.
- (M3) 7.13 and 7.14 edit the text M1 builds; apply them in M3's commit, never by reworking M1's. If a test not named in 7.17 or 7.18 fails because a paired sender no longer reaches natural language or a slash command, or because an unreadable pairing store no longer lets a message through, update it with an inline `BF-903 (#1581)` reason, never delete it, and report it.
- (M3) If `tests/test_layer_boundaries.py` or an import cycle names `probos.visiting_officers` in `federation/mcp_server.py`, stop and report; do not move the import into the function.

## 5. Consumers of every value this changes

| Value | Consumers | Effect |
|---|---|---|
| `VISITOR_CAPABILITIES`, `CAP_*` and `undeclared_capabilities` (defined in `config_models/crew.py`, re-exported by `visiting_officers`; A2) | `register`; `require_known_capabilities`; the pairing defaults; the config default and validator; the Ward Room facade; M3. Every importer of `visiting_officers` now also loads `probos.config_models` (`api.py` and `ward_room/service.py` already did, through `probos.config`) | one set of names; no cycle (AV15) |
| `register` refusing undeclared names | `PairingService.approve_pairing` (`:171`) and `restore_active_sessions` (`:255`, no caller, AV4) | restore catches `Exception` and logs (`:262-266`) |
| `get` hiding expired sessions | no production caller; `test_ad701` `:127`, `:169`, `:201`, `:207` | their assertions hold |
| `has_capability` delegating to `capability_refusal` | no production caller; `test_ad701:180-193` | same truth table |
| `DEFAULT_CAPABILITIES` | `security/pairing/__init__.py` re-export; `request_pairing`; `approve_pairing`; `test_ad802` | same value |
| `UnknownCapabilityError` | the CLI approve branch (7.4) | prints the reason as text (escaped, A3) and returns 1; the pending row is kept (A3) |
| `VisitorScopeRefused` (`PermissionError`) | the API handler (7.10); the routers catch `ValueError` only (`wardroom.py:289`, `:357`, `:371`, `:385`), so it reaches the handler | 403 |
| facade guards | every caller of the eleven methods: crew (slot ids), the Captain, the system | unchanged for them |
| `attach_visiting_officers` | finalize (7.9) | registry attached when AD-701 is on |
| `visiting_certificate`, either key form (7.13) | `is_visiting_identity` (M2's `_require_visitor_write`; the MCP walk), `require_visitor_capability` (the facade) | a visitor's bare certificate UUID is refused like its DID, under its DID; a crew certificate's UUID costs one in-memory lookup and passes; slot ids, "captain" and "system" cost none |
| `require_session_capability` (7.13) | `require_visitor_capability`; `_handle_paired` (7.15) | the same refusal codes and record |
| `PairingLookupError` (7.15) | every `handle_message` caller: Gmail `gmail_adapter.py:156-178` (unacknowledged, retried); Slack `receive` `slack_adapter.py:203-205` (returns ""); Slack poll `:290-297`, Telegram `telegram_adapter.py:197-204`, Matrix `matrix_adapter.py:177-184` (log, move on); Discord `discord_adapter.py:330` (log, post nothing); Teams `teams_adapter.py:141` to `routers/teams_webhook.py:41-47` (HTTP 200 with the fixed text); Webhook (no `channel_name`, never reaches `resolve_did`) | the message is refused; only Gmail retries |
| the paired-sender replies (7.15) | the same callers send a non-empty reply as they send any reply | the sender is told why |
| `visitor_argument_refusal` (7.16) | `_handle_tools_call`, reached by door A (`build_mcp_app`) and door B (the HXI bridge, `routers/system.py`; `test_bf875:592-603`) | refused before the app-tool and intent branches; `tools/list` and `resources/read` unchanged |
| `WardRoomService.check_subscribe` (A4, 7.8) | `AssignmentService.create_assignment` and `add_member` (7.12b), reached only by `routers/assignments.py:31`, `:61` with body-supplied ids (AV23) | a refused member reaches the API's handler (`except ValueError` only, `:39`, `:63`): 403, nothing written |
| `VisitorScopeRefused` re-raised by the teaching route (A4, 7.12c) | `POST /api/procedures/teach` only (AV24) | 403 instead of 200 with an error string |
| the walk's count before it reads (A4, 7.16) | `_handle_tools_call` (both doors) | the same refusals and threshold; a refused wide container is never iterated |

## 6. Tests

All tests use real objects: a real `AgentIdentityRegistry` in `tmp_path` (started as `tests/test_ad1346_admission_service.py:92-100` does), the real `VisitingOfficerRegistry` with an injected clock, the real `PairingRegistry` and `PairingService`, a real `WardRoomService` on a temporary database, the real API app and one real boot. W7's Ward Room stand-in only raises the real exception; the guard itself is W1-W6's.

Every BF-903 test errors on today's tree at its `probos.visiting_officers` imports. The **Behaviour** column says what each test asserts and which build it fails on; "guard" means it passes after the fix.

| Id | Test | Premise asserted | Behaviour |
|---|---|---|---|
| V1 | `test_one_vocabulary_names_every_visitor_capability` | registry, pairing and config share one set of names | guard |
| V2 | `test_register_refuses_an_undeclared_capability_before_a_certificate[typo, undeclared, one-of-two, a-bare-string]` | refused by name; no certificate, session or event | fails without 7.1 |
| V3 | `test_the_config_refuses_an_undeclared_default_capability` | refused at parse | fails without 7.2 |
| V4 | `test_pairing_refuses_an_undeclared_capability_before_it_is_stored` | no pending row; a repeat from a sender with a pending row is refused too (A3); the code survives a refused override; the defaults register | fails without 7.3; the repeat fails on `bfc8c98a` |
| V5 | `test_the_cli_names_an_undeclared_capability_and_keeps_the_code[undeclared-cap-flag, row-minted-before-bf903, markup-in-a-name]` | returns 1, prints the name as text, records no pairing and keeps the pending row; a retry with a declared `--cap` approves it (A3) | fails without 7.3 and 7.4; `[row-minted-before-bf903]` (the row is consumed) and `[markup-in-a-name]` (`MarkupError`) fail on `bfc8c98a` |
| V6 | `test_the_registry_refuses_by_session_capability_and_expiry_at_use` | three reasons, three events, no sweep; `get` and `has_capability` agree | fails without 7.1 |
| V7 | `test_a_visitor_is_known_by_its_certificate_and_other_ids_are_never_looked_up` | a visitor is known by its DID and its bare certificate UUID, and a certificate outlives its session; crew, ship and unknown DIDs and UUIDs and slot ids are not visitors; no lookup for an id of neither shape | fails without 7.1; the UUID cases fail without 7.13 |
| V8 | `test_the_one_guard_passes_crew_and_refuses_what_the_seam_does_not_allow` | crew pass; held served; missing refused; a certificate UUID is checked under its DID; registry off refused; an undeclared name raises, also at `require_session_capability` | fails without 7.1; the UUID and session-check cases fail without 7.13 |
| V9 | `test_a_malformed_agent_did_is_never_looked_up` | a did:probos DID whose agent part is not a lower-case certificate UUID (invalid, empty, upper-case, NUL-bearing) is not a visitor, passes the guard and costs no lookup (A3) | fails on `bfc8c98a` (looked up); the M3 form fails without A3's 7.13 line |
| V10 | `test_an_expired_pending_row_is_consumed_and_answers_expired_whatever_names_it_holds[declared, row-minted-before-bf903]` | through `probos pairing approve` without `--cap`: returns 1, prints "expired" and not the name, consumes the row (both lookups None), records no pairing (A4) | `[row-minted-before-bf903]` fails on A3's candidate `6911e258` (refused by name, kept); `[declared]` is a control |
| W0 | `test_a_visitor_without_ward_room_post_cannot_open_a_thread` (`test_bf903_seam_was_open.py`) | a reader cannot open a thread | **fails today: DID NOT RAISE**, and on the M1-only tree; passes after M2 |
| W1 | `test_a_visitor_without_the_capability_is_refused_at_each_entry[12 entries]` | each entry refuses the one missing capability, naming it and the entry, with one event | fails on M1-only (DID NOT RAISE) |
| W2 | `test_a_visitor_with_only_that_capability_is_served_at_each_entry[12 entries]` | exactly that capability is enough | guard (catches over-refusal) |
| W3 | `test_a_write_needs_dm_send_in_a_dm_channel_and_ward_room_post_elsewhere[post-in-ship-thread, post-in-dm-thread, thread-in-dm-channel, edit-in-dm-thread]` | the capability follows the channel | fails on M1-only |
| W4 | `test_a_lapsed_or_unattached_session_is_refused_at_its_next_request[expired, deregistered, registry-off]` | expired before the sweep, deregistered and registry off are all refused; crew still post | fails on M1-only |
| W5 | `test_crew_and_the_captain_are_served_as_before_without_a_lookup` | golden: every entry, registry on and off, and no certificate read | guard |
| W6 | `test_a_crew_did_is_served` | a crew certificate DID is not a visitor | guard |
| W7 | `test_the_api_answers_a_visitor_refusal_with_403_and_the_reason` | 403 with the body; the app is built in an empty working directory and leaves it empty (A4) | fails on M1-only (500) |
| W8 | `test_a_real_boot_scopes_visitors_in_the_ward_room` | finalize attaches the registry: refused for capability, then served | fails on M1-only |
| W9 | `test_an_assignment_naming_a_refused_visitor_changes_nothing_and_answers_403` | `POST /api/assignments` naming a visitor without `ward_room.read`: 403 with the envelope; no assignment, channel, subscription or deferred subscription; one event per request; a reader joins with every member subscribed (A4) | fails on M2 r1 `0a2a6026` (200, the refusal swallowed) |
| W10 | `test_adding_a_refused_visitor_to_an_assignment_writes_no_member_and_answers_403` | the members route: 403, no member row; a reader joins and is subscribed (A4) | fails on M2 r1 (200, the row written) |
| W11 | `test_the_teaching_route_answers_a_visitor_refusal_with_403` | 403 for a visitor target without `dm.receive`, no channel opened; a crew target is taught (A4) | fails on M2 r1 (200 with an error string) |
| P1 | `test_a_paired_sender_is_refused_commands_and_conversation[slash-command, natural-language, unknown-callsign]` | a paired sender's slash command and natural language get a reply naming the reason; no LLM turn, no event | fails without 7.15 |
| P2 | `test_a_paired_sender_holding_dm_send_reaches_the_crew_member` | a live `dm.send` is enough for an `@callsign` DM, delivered once to the Counselor's live agent over a real `IntentBus` (A4) | guard (catches over-refusal) |
| P3 | `test_a_paired_dm_without_a_live_dm_send_is_refused[capability-missing, session-expired, registry-off]` | refused with the code; one event, none with the registry off; nothing delivered although the agent is on duty (A4) | fails without 7.15; the delivery assertion kills C21 |
| P4 | `test_an_unreadable_pairing_store_refuses_the_message_and_its_callers_still_catch_it` | `PairingLookupError`, a `PairingNotificationError` naming only the channel; Slack's webhook returns "" | fails without 7.15 (the message is processed) |
| P5 | `test_a_sender_the_gate_does_not_pair_is_served_as_before[no-pairing-service, adapter-opted-out]` | golden: unpaired traffic is processed as before | guard |
| Q1 | `test_a_tools_call_naming_a_visitor_is_refused_before_either_branch[intent-did, intent-certificate-uuid, object-key, list-item, nested-value, deregistered-visitor, app-tool]` | -32602 with the reason; nothing dispatched; no peer registered (A4); one `MCP_BRIDGE_FAILED` | fails without 7.16; the peer assertion kills C22 |
| Q2 | `test_crew_ids_and_prose_that_mentions_a_visitor_are_dispatched[crew-did, crew-certificate-uuid, slot-id, prose-with-a-visitor-did]` | only a whole visiting id refuses; a dispatched call registers its peer (A4) | guard |
| Q3 | `test_the_argument_walk_reads_up_to_its_bound_and_refuses_past_it` | 10,000 values dispatch; 10,001 are refused unread | fails without 7.16 |
| Q4 | `test_the_argument_walk_counts_a_container_before_it_reads_one` | a container that takes the call past the bound is refused with none of its items read; under the bound every item is read; an object counts two per entry (A4) | fails on the M3 r1 candidate (10,000 items read) |

## 7. The contract

Third-party names used below, none of them ProbOS's: `TestClient` is not a ProbOS name (FastAPI's), `Namespace` is not one (argparse's), and `ValidationError` is not one (pydantic's). The tests import the first two under a leading underscore.

### 7.1 `src/probos/visiting_officers.py` (M1)

SEARCH:
```python
- **Capabilities are strings, not enums** (Open/Closed): new caps land
  via configuration, not code edits.
```
REPLACE:
```python
- **Capabilities are strings, not enums**: sessions, pairing rows and
  events carry them as strings. BF-903 (#1581) closes the set: a
  capability means something only where a checking path reads it, and
  that path is code, so a new capability lands in ``VISITOR_CAPABILITIES``
  with its check, in one change. Configuration and the Captain's
  ``--cap`` choose among the declared names; an undeclared one is refused
  by name, so a typo can neither grant nor deny in silence.
- **One guard** (BF-903): every path that acts for an actor id calls
  ``require_visitor_capability`` before acting. A crew member's id is
  never looked up; a visiting officer's DID must hold the capability in a
  live session, read at use.
```

SEARCH:
```python
from typing import Any, Callable

logger = logging.getLogger(__name__)

DEFAULT_SESSION_TTL_SECONDS: float = 3600.0
DEFAULT_SWEEP_INTERVAL_SECONDS: float = 60.0
VISITING_AGENT_TYPE: str = "visiting"
```
REPLACE:
```python
from typing import Any, Callable, Iterable

# BF-903 (#1581): the visiting-officer capability vocabulary. It is defined once, in
# ``probos.config_models.crew`` (Amendment A2): that module imports nothing from ``probos``, so the
# config default and validator read the names without an import, and this module re-exports them,
# as ``cognitive/dreaming.py`` imports AD-1326's bound from ``config_models/cognition.py``. The
# registry, the pairing defaults and every checking path import the names from here.
from probos.config_models.crew import (  # re-exported: the CAP_* names are imported from this module
    CAP_DM_RECEIVE,
    CAP_DM_SEND,
    CAP_WARD_ROOM_POST,
    CAP_WARD_ROOM_READ,
    VISITOR_CAPABILITIES,
    undeclared_capabilities,
)

logger = logging.getLogger(__name__)

DEFAULT_SESSION_TTL_SECONDS: float = 3600.0
DEFAULT_SWEEP_INTERVAL_SECONDS: float = 60.0
VISITING_AGENT_TYPE: str = "visiting"

# BF-903: why a visiting officer was refused (AD-1316's stable-code syntax). The refusal event
# and ``VisitorScopeRefused.reason`` carry one of these.
REFUSED_NO_SESSION: str = "visitor_session_unknown"
REFUSED_EXPIRED: str = "visitor_session_expired"
REFUSED_CAPABILITY: str = "visitor_capability_missing"
REFUSED_REGISTRY_OFF: str = "visitor_registry_off"


class UnknownCapabilityError(ValueError):
    """BF-903: a capability name the vocabulary does not declare."""

    def __init__(self, unknown: Iterable[str]) -> None:
        self.unknown: tuple[str, ...] = tuple(unknown)
        super().__init__(
            f"undeclared visiting-officer capabilities {list(self.unknown)!r}; "
            f"declared: {sorted(VISITOR_CAPABILITIES)!r} (BF-903)"
        )


class VisitorScopeRefused(PermissionError):
    """BF-903: a visiting officer's request that its session does not allow.

    ``reason`` is one of the ``REFUSED_*`` codes. The API answers it with 403, as it answers
    BF-771's denial (``api.py``).
    """

    def __init__(self, did: str, capability: str, reason: str, surface: str) -> None:
        self.did = did
        self.capability = capability
        self.reason = reason
        self.surface = surface
        super().__init__(
            f"BF-903: visiting officer {did} may not use {capability!r} at {surface}: {reason}"
        )


def require_known_capabilities(capabilities: Iterable[str]) -> None:
    """BF-903: raise ``UnknownCapabilityError`` naming every capability the vocabulary lacks.

    A bare string is iterated as its characters and so refused, never read as one name.
    """
    unknown = undeclared_capabilities(capabilities)
    if unknown:
        raise UnknownCapabilityError(unknown)
```

SEARCH:
```python
      - has_capability(did, capability) -> bool
      - active() -> tuple[VisitingOfficerSession, ...]
      - async start() / async stop()

    Consumers SHOULD call ``has_capability(did, "ward_room.post")`` before
    relaying a Ward Room post on behalf of a visiting officer (D4).
    """
```
REPLACE:
```python
      - has_capability(did, capability) -> bool
      - capability_refusal(did, capability) -> str | None   (BF-903)
      - check(did, capability, *, surface) -> None   (BF-903; raises on refusal)
      - active() -> tuple[VisitingOfficerSession, ...]
      - async start() / async stop()

    BF-903: consumers call the module's ``require_visitor_capability``,
    which recognises a visiting officer and then calls ``check``. ``get``,
    ``capability_refusal`` and ``check`` read expiry at use, so an expired session is
    refused before the sweep removes it.
    """
```

SEARCH:
```python
        if ttl <= 0:
            raise ValueError("session_ttl_seconds must be positive")
        cert = await self._identity.issue_birth_certificate(
```
REPLACE:
```python
        if ttl <= 0:
            raise ValueError("session_ttl_seconds must be positive")
        require_known_capabilities(capabilities)  # BF-903 (#1581): refused before a certificate is issued
        cert = await self._identity.issue_birth_certificate(
```

SEARCH:
```python
    def get(self, did: str) -> VisitingOfficerSession | None:
        return self._sessions.get(did)

    def has_capability(self, did: str, capability: str) -> bool:
        session = self._sessions.get(did)
        if session is None:
            return False
        if self._clock() >= session.expires_at:
            return False
        return capability in session.capabilities
```
REPLACE:
```python
    def get(self, did: str) -> VisitingOfficerSession | None:
        session = self._sessions.get(did)
        if session is None or self._clock() >= session.expires_at:  # BF-903: an expired session is gone at use
            return None
        return session

    def capability_refusal(self, did: str, capability: str) -> str | None:  # BF-903 A5: AD-1343's census reads any call named "refusal" as a stop check
        """BF-903: why ``did`` may not use ``capability`` now, or None when it may.

        Read at each use: a deregistered session is refused at once and an expired one before
        the sweep removes it.
        """
        session = self._sessions.get(did)
        if session is None:
            return REFUSED_NO_SESSION
        if self._clock() >= session.expires_at:
            return REFUSED_EXPIRED
        if capability not in session.capabilities:
            return REFUSED_CAPABILITY
        return None

    def has_capability(self, did: str, capability: str) -> bool:
        return self.capability_refusal(did, capability) is None

    def check(self, did: str, capability: str, *, surface: str) -> None:
        """BF-903: return when ``did`` may use ``capability``; otherwise record the refusal and raise.

        The record is a ``VISITING_OFFICER_REFUSED`` event through this registry's emitter, the
        sink its registration and deregistration events use, and a warning.
        """
        reason = self.capability_refusal(did, capability)
        if reason is None:
            return
        self._emit("VISITING_OFFICER_REFUSED", {
            "did": did, "capability": capability, "reason": reason, "surface": surface,
        })
        logger.warning("BF-903: refused visiting officer %s %r at %s: %s", did, capability, surface, reason)
        raise VisitorScopeRefused(did, capability, reason, surface)
```

SEARCH:
```python
            logger.warning(
                "AD-701: emit_event '%s' failed; continuing", event_name, exc_info=True
            )
```
REPLACE:
```python
            logger.warning(
                "AD-701: emit_event '%s' failed; continuing", event_name, exc_info=True
            )


def is_visiting_identity(identity_registry: Any, actor_id: object) -> bool:
    """BF-903: whether ``actor_id`` is the DID of a visiting officer's birth certificate.

    Only a did:probos agent DID is looked up, in the identity registry's in-memory certificate
    cache (``get_by_uuid``, which never raises), so a slot id, a callsign, "captain" or "system"
    costs no lookup and is never refused here. The certificate outlives its session, so an
    expired or deregistered visitor is still recognised and refused. BF-907's
    ``resolve_slot_id`` and AD-1346's ``IdentityService.resolve`` return None for a visitor,
    which holds no slot, so they cannot classify one; this reads the agent type AD-701 sets.
    """
    if type(actor_id) is not str or not actor_id.startswith("did:") or identity_registry is None:
        return False
    from probos.identity import is_sovereign_identity_key, parse_did  # BF-903: imported at use; at load this module reads only probos.config_models (A2)

    parsed = parse_did(actor_id)
    if parsed is None or parsed.get("type") != "agent":
        return False
    if not is_sovereign_identity_key(parsed["agent_uuid"]):  # BF-903 (A3): a malformed agent part costs no lookup
        return False
    cert = identity_registry.get_by_uuid(parsed["agent_uuid"])
    return cert is not None and cert.agent_type == VISITING_AGENT_TYPE


def require_visitor_capability(
    actor_id: str,
    capability: str,
    *,
    surface: str,
    identity_registry: Any,
    visiting_officers: VisitingOfficerRegistry | None,
) -> None:
    """BF-903 (#1581): the one check every path that acts for an actor id calls before it acts.

    A crew member, the Captain or the system passes without a lookup. A visiting officer must
    hold ``capability`` in a live session; with AD-701's registry off it holds none and is
    refused. ``surface`` names the entry in the refusal and its record. An undeclared
    ``capability`` raises ``UnknownCapabilityError`` whoever acts, so a typo in a checking
    path fails on its first call.
    """
    if capability not in VISITOR_CAPABILITIES:
        raise UnknownCapabilityError([capability])
    if not is_visiting_identity(identity_registry, actor_id):
        return
    if visiting_officers is None:
        logger.warning(
            "BF-903: refused visiting officer %s %r at %s: AD-701's registry is off, so no session exists",
            actor_id, capability, surface,
        )
        raise VisitorScopeRefused(actor_id, capability, REFUSED_REGISTRY_OFF, surface)
    visiting_officers.check(actor_id, capability, surface=surface)
```

### 7.2 `src/probos/config_models/crew.py` (M1)

SEARCH:
```python
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator
```
REPLACE:
```python
from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, Field, field_validator
```

SEARCH:
```python
class VisitingOfficersConfig(BaseModel):
    """AD-701: Visiting officer registry tunables.
```
REPLACE:
```python
# BF-903 (#1581): the visiting-officer capability vocabulary, its one owner (Amendment A2). It is
# defined in this module, which imports nothing from ``probos``, so the default and the validator
# below read it without an import; ``probos.visiting_officers`` re-exports it, and the registry, the
# pairing defaults and every checking path import it from there. AD-701 declared the two Ward Room
# capabilities and AD-802 the two DM ones; nothing else is a capability.
CAP_WARD_ROOM_POST: str = "ward_room.post"
CAP_WARD_ROOM_READ: str = "ward_room.read"
CAP_DM_SEND: str = "dm.send"
CAP_DM_RECEIVE: str = "dm.receive"
VISITOR_CAPABILITIES: frozenset[str] = frozenset({CAP_WARD_ROOM_POST, CAP_WARD_ROOM_READ, CAP_DM_SEND, CAP_DM_RECEIVE})


def undeclared_capabilities(capabilities: Iterable[str]) -> list[str]:
    """BF-903: the names in ``capabilities`` that ``VISITOR_CAPABILITIES`` lacks, once each, in order.

    The one membership test: the validator below and ``probos.visiting_officers``'s
    ``require_known_capabilities`` both call it. Iterating a bare string yields its characters,
    each of which is undeclared.
    """
    return [c for c in dict.fromkeys(capabilities) if c not in VISITOR_CAPABILITIES]


def _default_visitor_capabilities() -> list[str]:
    """BF-903 (#1581): the default is two declared names, a new list per instance."""
    return [CAP_WARD_ROOM_POST, CAP_WARD_ROOM_READ]


class VisitingOfficersConfig(BaseModel):
    """AD-701: Visiting officer registry tunables.
```

SEARCH:
```python
    default_capabilities: list[str] = Field(
        default_factory=lambda: ["ward_room.post", "ward_room.read"]
    )
```
REPLACE:
```python
    default_capabilities: list[str] = Field(default_factory=_default_visitor_capabilities)

    @field_validator("default_capabilities")
    @classmethod
    def _declared_capabilities_only(cls, value: list[str]) -> list[str]:
        """BF-903: an undeclared capability is refused when the configuration is parsed.

        The text matches ``UnknownCapabilityError``'s; pydantic wraps either as a validation error.
        """
        unknown = undeclared_capabilities(value)
        if unknown:
            raise ValueError(
                f"undeclared visiting-officer capabilities {unknown!r}; "
                f"declared: {sorted(VISITOR_CAPABILITIES)!r} (BF-903)"
            )
        return value
```

### 7.3 `src/probos/security/pairing/service.py` (M1)

SEARCH:
```python
    UnknownPairingCode,
)

logger = logging.getLogger(__name__)
```
REPLACE:
```python
    UnknownPairingCode,
)
from probos.visiting_officers import CAP_DM_RECEIVE, CAP_DM_SEND, require_known_capabilities

logger = logging.getLogger(__name__)
```

SEARCH:
```python
DEFAULT_CAPABILITIES = ("dm.send", "dm.receive")
```
REPLACE:
```python
DEFAULT_CAPABILITIES = (CAP_DM_SEND, CAP_DM_RECEIVE)  # BF-903: AD-802's defaults, named by the vocabulary's owner
```

SEARCH:
```python
        existing = self._registry.get_pending_by_raw_id(channel, raw_id)
        if existing is not None and existing.expires_at > self._clock():
            return existing.code

        caps = tuple(capabilities or DEFAULT_CAPABILITIES)
        code = self._generate_code()
```
REPLACE:
```python
        caps = tuple(capabilities or DEFAULT_CAPABILITIES)
        require_known_capabilities(caps)  # BF-903: refused before a pending row is minted
        existing = self._registry.get_pending_by_raw_id(channel, raw_id)
        if existing is not None and existing.expires_at > self._clock():
            return existing.code

        code = self._generate_code()
```

SEARCH:
```python
        pending = self._registry.consume_pending(channel, code)
        if pending is None:
            raise UnknownPairingCode(f"No pending pairing for channel={channel!r} code={code!r}")
```
REPLACE:
```python
        if capabilities_override:
            require_known_capabilities(capabilities_override)  # BF-903: refused before the code is consumed
        else:
            stored = self._registry.get_pending(channel, code)  # BF-903 (A3): read, not consumed, so a refused row is kept
            if stored is not None and stored.expires_at >= self._clock():  # BF-903 (A4): an expired row goes on to the consume and answers "expired"
                require_known_capabilities(stored.capabilities or DEFAULT_CAPABILITIES)  # BF-903 (A3): a row minted before BF-903 may hold any string
        pending = self._registry.consume_pending(channel, code)
        if pending is None:
            raise UnknownPairingCode(f"No pending pairing for channel={channel!r} code={code!r}")
```

SEARCH:
```python
        if not caps:
            caps = DEFAULT_CAPABILITIES
        ttl = session_ttl_seconds if session_ttl_seconds is not None else self._session_ttl
```
REPLACE:
```python
        if not caps:
            caps = DEFAULT_CAPABILITIES
        require_known_capabilities(caps)  # BF-903: a row minted before BF-903 may hold any string
        ttl = session_ttl_seconds if session_ttl_seconds is not None else self._session_ttl
```

### 7.4 `src/probos/__main__.py` (M1)

SEARCH:
```python
    from probos.security.pairing import (
        PairingRegistry,
        PairingService,
        UnknownPairingCode,
    )
```
REPLACE:
```python
    from probos.security.pairing import (
        PairingRegistry,
        PairingService,
        UnknownPairingCode,
    )
    from probos.visiting_officers import UnknownCapabilityError
    from rich.markup import escape  # BF-903 (A3): a refused name prints as text, never as markup
```

SEARCH:
```python
        except UnknownPairingCode as exc:
            console.print(f"[red]Approve failed:[/red] {exc}")
```
REPLACE:
```python
        except (UnknownPairingCode, UnknownCapabilityError) as exc:  # BF-903: an undeclared --cap is refused with its name
            console.print(f"[red]Approve failed:[/red] {escape(str(exc))}", emoji=False)  # BF-903 (A3): a refused name prints as text
```

### 7.5 `tests/test_ad701_visiting_officers.py` (M1: "c" was any string; it is an undeclared name now)

The pairs apply in order. After the fourth and fifth, the last `["c"]` call is unique.

SEARCH:
```python
    await reg.register(callsign="x", capabilities=["c"], origin="o")
```
REPLACE:
```python
    # BF-903 (#1581): a capability is a declared name now; "c" is refused at register.
    await reg.register(callsign="x", capabilities=["ward_room.read"], origin="o")
```

SEARCH:
```python
    assert payload["capabilities"] == ["c"]
```
REPLACE:
```python
    assert payload["capabilities"] == ["ward_room.read"]
```

SEARCH:
```python
    with pytest.raises(ValueError):
        await reg.register(callsign="", capabilities=["c"])
```
REPLACE:
```python
    # BF-903 (#1581): a declared capability, so the empty callsign is what raises. The next two
    # cases keep their text: each raises on its own earlier check (no capability, a ttl of zero)
    # before the capability check runs, so they stay ValueError cases for the reason they name.
    with pytest.raises(ValueError):
        await reg.register(callsign="", capabilities=["ward_room.read"])
```

SEARCH:
```python
    reg, _identity, emit_log, _clock = _make_registry()
    session = await reg.register(callsign="x", capabilities=["c"])
```
REPLACE:
```python
    reg, _identity, emit_log, _clock = _make_registry()
    session = await reg.register(callsign="x", capabilities=["ward_room.read"])  # BF-903: a declared name
```

SEARCH:
```python
    reg, _identity, emit_log, _ = _make_registry(clock=clock, session_ttl=10.0)
    session = await reg.register(callsign="x", capabilities=["c"])
```
REPLACE:
```python
    reg, _identity, emit_log, _ = _make_registry(clock=clock, session_ttl=10.0)
    session = await reg.register(callsign="x", capabilities=["ward_room.read"])  # BF-903: a declared name
```

SEARCH:
```python
    s1 = await reg.register(callsign="alive", capabilities=["c"])
    s2 = await reg.register(
        callsign="dying", capabilities=["c"], session_ttl_seconds=5.0
    )
```
REPLACE:
```python
    s1 = await reg.register(callsign="alive", capabilities=["ward_room.read"])  # BF-903: a declared name
    s2 = await reg.register(
        callsign="dying", capabilities=["ward_room.read"], session_ttl_seconds=5.0
    )
```

SEARCH:
```python
    )
    session = await reg.register(callsign="x", capabilities=["c"])
    assert session.did.startswith("did:probos:")
```
REPLACE:
```python
    )
    session = await reg.register(callsign="x", capabilities=["ward_room.read"])  # BF-903: a declared name
    assert session.did.startswith("did:probos:")
```

### 7.6 `tests/test_ad802_pairing.py` (M1: the test pinned "tool.use" as grantable)

SEARCH:
```python
    paired = await service.approve_pairing(
        "telegram", code,
        capabilities_override=["dm.send", "tool.use", "ward_room.post"],
    )
    assert "tool.use" in paired.capabilities
    assert "ward_room.post" in paired.capabilities
```
REPLACE:
```python
    # BF-903 (#1581): "tool.use" was AD-802's example override, but no checking path reads it, so it is
    # refused now (tests/test_bf903_visitor_scope.py). The override still replaces the requested set.
    paired = await service.approve_pairing(
        "telegram", code,
        capabilities_override=["dm.send", "ward_room.post"],
    )
    assert set(paired.capabilities) == {"dm.send", "ward_room.post"}
```

### 7.7 New file: `tests/test_bf903_visitor_scope.py` (M1)

```python
"""BF-903 (#1581) M1: one owner for the visiting-officer capability names, and AD-701's registry as the seam.

Real objects: a real ``AgentIdentityRegistry`` in ``tmp_path`` (started and commissioned as
``tests/test_ad1346_admission_service.py`` does), the real ``VisitingOfficerRegistry`` with an injected clock, the
real ``PairingRegistry`` and ``PairingService``, the real config models and the real ``probos pairing approve``.
Nothing reads the live data directory.
"""

from __future__ import annotations

from argparse import Namespace as _Namespace  # the standard library's, not a ProbOS name
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import probos.__main__ as probos_main
import probos.config_models.crew as config_crew  # A2: the vocabulary's owner, imported as test_ad1270e2g_crew_models does
from probos.config import SystemConfig, VisitingOfficersConfig
from probos.identity import AgentIdentityRegistry
from probos.security.pairing import DEFAULT_CAPABILITIES, PairingRegistry, PairingService
from probos.visiting_officers import (
    CAP_DM_RECEIVE,
    CAP_DM_SEND,
    CAP_WARD_ROOM_POST,
    CAP_WARD_ROOM_READ,
    REFUSED_CAPABILITY,
    REFUSED_EXPIRED,
    REFUSED_NO_SESSION,
    REFUSED_REGISTRY_OFF,
    VISITOR_CAPABILITIES,
    UnknownCapabilityError,
    VisitingOfficerRegistry,
    VisitorScopeRefused,
    is_visiting_identity,
    require_visitor_capability,
)

INSTANCE_ID = "bf903-m1-ship"
VESSEL_NAME = "Bf903m1"
CREW_SLOT = "counselor_counselor_0_67c601cb"
UNKNOWN_UUID = "00000000-0000-4000-8000-000000000000"
Events = list[tuple[str, dict[str, Any]]]


class _Clock:
    """The registry's injected clock."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
async def identities(tmp_path: Path) -> AsyncIterator[AgentIdentityRegistry]:
    registry = AgentIdentityRegistry(data_dir=tmp_path / "identity")
    try:
        await registry.start()
        await registry.start(instance_id=INSTANCE_ID, vessel_name=VESSEL_NAME, version="1")
        yield registry
    finally:
        await registry.stop()


def _officers(identities: AgentIdentityRegistry, clock: _Clock, events: Events) -> VisitingOfficerRegistry:
    return VisitingOfficerRegistry(
        identities,
        instance_id=INSTANCE_ID,
        vessel_name=VESSEL_NAME,
        baseline_version="1",
        emit_event=lambda name, payload: events.append((name, payload)),
        clock=clock,
    )


async def _crew(identities: AgentIdentityRegistry) -> Any:
    return await identities.resolve_or_issue(
        slot_id=CREW_SLOT, agent_type="counselor", callsign="Counselor", instance_id=INSTANCE_ID,
        vessel_name=VESSEL_NAME, department="medical", post_id="counselor", baseline_version="v1",
    )


def _refusals(events: Events) -> list[dict[str, Any]]:
    return [payload for name, payload in events if name == "VISITING_OFFICER_REFUSED"]


def test_one_vocabulary_names_every_visitor_capability() -> None:
    """V1: the registry, the pairing defaults and the config default use one set of four names, defined once in
    ``config_models/crew.py`` and re-exported by ``probos.visiting_officers`` (A2)."""
    assert (CAP_WARD_ROOM_POST, CAP_WARD_ROOM_READ, CAP_DM_SEND, CAP_DM_RECEIVE) == (
        "ward_room.post", "ward_room.read", "dm.send", "dm.receive",
    )
    assert VISITOR_CAPABILITIES == frozenset({"ward_room.post", "ward_room.read", "dm.send", "dm.receive"})
    assert VISITOR_CAPABILITIES is config_crew.VISITOR_CAPABILITIES  # one owner: the re-export is the same object
    assert DEFAULT_CAPABILITIES == (CAP_DM_SEND, CAP_DM_RECEIVE)
    assert VisitingOfficersConfig().default_capabilities == [CAP_WARD_ROOM_POST, CAP_WARD_ROOM_READ]
    assert SystemConfig().visiting_officers.default_capabilities == [CAP_WARD_ROOM_POST, CAP_WARD_ROOM_READ]


@pytest.mark.parametrize(
    ("capabilities", "unknown"),
    [
        (["ward_room.pots"], ("ward_room.pots",)),
        (["tool.use"], ("tool.use",)),
        ([CAP_DM_SEND, "tool.use", "tool.use"], ("tool.use",)),
        ("dm.send", ("d", "m", ".", "s", "e", "n")),
    ],
    ids=["typo", "undeclared", "one-of-two", "a-bare-string"],
)
async def test_register_refuses_an_undeclared_capability_before_a_certificate(
    identities: AgentIdentityRegistry, capabilities: Any, unknown: tuple[str, ...],
) -> None:
    """V2: an undeclared name is refused by name; no certificate, session or event follows."""
    events: Events = []
    officers = _officers(identities, _Clock(), events)
    births = len(identities.get_all())
    with pytest.raises(UnknownCapabilityError) as refused:
        await officers.register("visitor", capabilities)
    assert refused.value.unknown == unknown
    assert len(identities.get_all()) == births
    assert officers.active() == ()
    assert events == []


def test_the_config_refuses_an_undeclared_default_capability() -> None:
    """V3: an undeclared name in visiting_officers.default_capabilities fails when the config is parsed."""
    with pytest.raises(ValidationError, match="tool.use"):
        VisitingOfficersConfig(default_capabilities=[CAP_WARD_ROOM_POST, "tool.use"])
    assert VisitingOfficersConfig(default_capabilities=[CAP_DM_SEND]).default_capabilities == [CAP_DM_SEND]


async def test_pairing_refuses_an_undeclared_capability_before_it_is_stored(
    identities: AgentIdentityRegistry, tmp_path: Path,
) -> None:
    """V4: a request or an override naming an undeclared capability stores nothing, the refused override
    leaves the code usable, and the defaults register as declared capabilities."""
    officers = _officers(identities, _Clock(), [])
    store = PairingRegistry(tmp_path / "pairings.db")
    service = PairingService(store, officers)
    with pytest.raises(UnknownCapabilityError):
        await service.request_pairing("telegram", "tg-1", capabilities=["tool.use"])
    assert store.list_pending() == []
    code = await service.request_pairing("telegram", "tg-1")
    with pytest.raises(UnknownCapabilityError):  # A3: a repeat from a sender with a pending row is checked too
        await service.request_pairing("telegram", "tg-1", capabilities=["tool.use"])
    assert await service.request_pairing("telegram", "tg-1") == code
    with pytest.raises(UnknownCapabilityError):
        await service.approve_pairing("telegram", code, capabilities_override=[CAP_DM_SEND, "tool.use"])
    assert store.get_pending("telegram", code) is not None
    assert officers.active() == ()
    paired = await service.approve_pairing("telegram", code)
    session = officers.get(paired.did)
    assert session is not None
    assert session.capabilities == frozenset({CAP_DM_SEND, CAP_DM_RECEIVE})


@pytest.mark.parametrize(
    ("stored", "cap", "named"),
    [
        ([CAP_DM_SEND], "dm.send,tool.use", "tool.use"),
        (["tool.use"], None, "tool.use"),
        ([CAP_DM_SEND], "dm.send,[/red]tool.use", "[/red]tool.use"),
    ],
    ids=["undeclared-cap-flag", "row-minted-before-bf903", "markup-in-a-name"],
)
def test_the_cli_names_an_undeclared_capability_and_keeps_the_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    stored: list[str], cap: str | None, named: str,
) -> None:
    """V5: `probos pairing approve` prints the undeclared name as text, returns 1 and records no pairing; the
    pending row is kept, whether the name came from --cap or from a row minted before BF-903, so a retry with a
    declared --cap approves it (A3)."""
    data = tmp_path / "data"
    monkeypatch.setattr(probos_main, "_default_data_dir", lambda: data)
    store = PairingRegistry(data / "pairings.db")
    store.mint_pending("telegram", "tg-9", "ABCDEF", stored, ttl_seconds=600.0)
    status = probos_main._cmd_pairing(
        _Namespace(pairing_cmd="approve", channel="telegram", code="ABCDEF", cap=cap, ttl_days=None),
    )
    assert status == 1
    assert named in capsys.readouterr().out
    assert store.list_paired() == []
    assert store.get_pending("telegram", "ABCDEF") is not None
    retried = probos_main._cmd_pairing(
        _Namespace(pairing_cmd="approve", channel="telegram", code="ABCDEF", cap=CAP_DM_SEND, ttl_days=None),
    )
    assert retried == 0
    assert [p.capabilities for p in store.list_paired()] == [(CAP_DM_SEND,)]
    assert store.get_pending("telegram", "ABCDEF") is None


@pytest.mark.parametrize(
    "stored", [[CAP_DM_SEND], [CAP_DM_SEND, "tool.use"]], ids=["declared", "row-minted-before-bf903"],
)
def test_an_expired_pending_row_is_consumed_and_answers_expired_whatever_names_it_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], stored: list[str],
) -> None:
    """V10 (A4): `probos pairing approve` without --cap consumes an expired pending row and answers that it expired,
    whatever names the row holds: one minted before BF-903 with an undeclared name is neither refused by name nor
    kept (A3's candidate did both); the declared row is the control."""
    data = tmp_path / "data"
    monkeypatch.setattr(probos_main, "_default_data_dir", lambda: data)
    minted_long_ago = PairingRegistry(data / "pairings.db", clock=lambda: 1000.0)  # the row expires at 1600.0
    minted_long_ago.mint_pending("telegram", "tg-10", "ABCDEF", stored, ttl_seconds=600.0)
    status = probos_main._cmd_pairing(
        _Namespace(pairing_cmd="approve", channel="telegram", code="ABCDEF", cap=None, ttl_days=None),
    )
    assert status == 1
    out = capsys.readouterr().out
    assert "expired" in out
    assert "tool.use" not in out
    store = PairingRegistry(data / "pairings.db")
    assert store.get_pending("telegram", "ABCDEF") is None
    assert store.get_pending_by_raw_id("telegram", "tg-10") is None
    assert store.list_paired() == []


async def test_a_malformed_agent_did_is_never_looked_up(
    identities: AgentIdentityRegistry, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """V9 (A3): a did:probos DID whose agent part is not a lower-case certificate UUID is not a visitor, passes
    the guard and costs no certificate lookup: an invalid, empty, upper-case or NUL-bearing agent part."""
    officers = _officers(identities, _Clock(), [])
    session = await officers.register("visitor", [CAP_WARD_ROOM_READ])
    prefix, visitor_uuid = session.did.rsplit(":", 1)

    def _no_lookup(_uuid: str) -> None:
        raise AssertionError("not expected: a malformed agent DID was looked up")

    monkeypatch.setattr(identities, "get_by_uuid", _no_lookup)
    for actor in (f"{prefix}:not-a-uuid", f"{prefix}:", f"{prefix}:{visitor_uuid.upper()}", f"{prefix}:{visitor_uuid}\x00"):
        assert is_visiting_identity(identities, actor) is False
        require_visitor_capability(
            actor, CAP_WARD_ROOM_POST, surface="v9", identity_registry=identities, visiting_officers=officers,
        )


async def test_the_registry_refuses_by_session_capability_and_expiry_at_use(identities: AgentIdentityRegistry) -> None:
    """V6: check() serves a held capability and refuses a missing one, a deregistered session and an expired
    one before any sweep, each with its code and one event; get() and has_capability agree."""
    clock = _Clock()
    events: Events = []
    officers = _officers(identities, clock, events)
    reader = await officers.register("reader", [CAP_WARD_ROOM_READ], session_ttl_seconds=10.0)
    gone = await officers.register("gone", [CAP_WARD_ROOM_READ])
    officers.check(reader.did, CAP_WARD_ROOM_READ, surface="v6.read")
    with pytest.raises(VisitorScopeRefused) as missing:
        officers.check(reader.did, CAP_WARD_ROOM_POST, surface="v6.post")
    assert (missing.value.did, missing.value.capability, missing.value.reason, missing.value.surface) == (
        reader.did, CAP_WARD_ROOM_POST, REFUSED_CAPABILITY, "v6.post",
    )
    officers.deregister(gone.did)
    with pytest.raises(VisitorScopeRefused) as deregistered:
        officers.check(gone.did, CAP_WARD_ROOM_READ, surface="v6.gone")
    assert deregistered.value.reason == REFUSED_NO_SESSION
    clock.now += 10.0
    assert officers.get(reader.did) is None
    assert officers.has_capability(reader.did, CAP_WARD_ROOM_READ) is False
    with pytest.raises(VisitorScopeRefused) as expired:
        officers.check(reader.did, CAP_WARD_ROOM_READ, surface="v6.read")
    assert expired.value.reason == REFUSED_EXPIRED
    assert _refusals(events) == [
        {"did": reader.did, "capability": CAP_WARD_ROOM_POST, "reason": REFUSED_CAPABILITY, "surface": "v6.post"},
        {"did": gone.did, "capability": CAP_WARD_ROOM_READ, "reason": REFUSED_NO_SESSION, "surface": "v6.gone"},
        {"did": reader.did, "capability": CAP_WARD_ROOM_READ, "reason": REFUSED_EXPIRED, "surface": "v6.read"},
    ]
    assert [p["reason"] for n, p in events if n == "VISITING_OFFICER_DEREGISTERED"] == ["explicit"]


async def test_a_visitor_is_known_by_its_certificate_and_other_ids_are_never_looked_up(
    identities: AgentIdentityRegistry, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """V7: a visiting certificate's DID is a visitor even after its session ends; a crew DID, an unknown DID,
    the ship's DID and a missing registry are not; ids that are not DIDs are never looked up."""
    officers = _officers(identities, _Clock(), [])
    session = await officers.register("visitor", [CAP_WARD_ROOM_READ])
    crew = await _crew(identities)
    assert is_visiting_identity(identities, session.did) is True
    officers.deregister(session.did)
    assert is_visiting_identity(identities, session.did) is True
    assert is_visiting_identity(identities, crew.did) is False
    assert is_visiting_identity(identities, f"did:probos:{INSTANCE_ID}:{UNKNOWN_UUID}") is False
    assert is_visiting_identity(identities, f"did:probos:{INSTANCE_ID}") is False
    assert is_visiting_identity(None, session.did) is False

    def _no_lookup(_uuid: str) -> None:
        raise AssertionError("not expected: an id that is not a DID was looked up")

    monkeypatch.setattr(identities, "get_by_uuid", _no_lookup)
    for actor in (CREW_SLOT, "captain", "system", crew.agent_uuid, "", None):
        assert is_visiting_identity(identities, actor) is False


async def test_the_one_guard_passes_crew_and_refuses_what_the_seam_does_not_allow(
    identities: AgentIdentityRegistry,
) -> None:
    """V8: crew pass with or without the registry; a visitor is served a held capability, refused a missing
    one and refused outright with the registry off; an undeclared capability raises for anyone."""
    events: Events = []
    officers = _officers(identities, _Clock(), events)
    session = await officers.register("visitor", [CAP_WARD_ROOM_READ])
    for registry in (None, officers):
        require_visitor_capability(
            CREW_SLOT, CAP_WARD_ROOM_POST, surface="v8", identity_registry=identities, visiting_officers=registry,
        )
    require_visitor_capability(
        session.did, CAP_WARD_ROOM_READ, surface="v8", identity_registry=identities, visiting_officers=officers,
    )
    with pytest.raises(VisitorScopeRefused) as missing:
        require_visitor_capability(
            session.did, CAP_WARD_ROOM_POST, surface="v8.post", identity_registry=identities,
            visiting_officers=officers,
        )
    assert missing.value.reason == REFUSED_CAPABILITY
    with pytest.raises(VisitorScopeRefused) as off:
        require_visitor_capability(
            session.did, CAP_WARD_ROOM_READ, surface="v8.off", identity_registry=identities, visiting_officers=None,
        )
    assert (off.value.reason, off.value.surface) == (REFUSED_REGISTRY_OFF, "v8.off")
    with pytest.raises(UnknownCapabilityError):
        require_visitor_capability(
            CREW_SLOT, "ward_room.pots", surface="v8", identity_registry=identities, visiting_officers=officers,
        )
    assert [p["surface"] for p in _refusals(events)] == ["v8.post"]
```

### 7.8 `src/probos/ward_room/service.py` (M2)

SEARCH:
```python
from probos.protocols import ConnectionFactory, DatabaseConnection, EventEmitterMixin
from probos.ward_room.channels import ChannelManager
```
REPLACE:
```python
from probos.protocols import ConnectionFactory, DatabaseConnection, EventEmitterMixin
from probos.visiting_officers import (
    CAP_DM_RECEIVE,
    CAP_DM_SEND,
    CAP_WARD_ROOM_POST,
    CAP_WARD_ROOM_READ,
    is_visiting_identity,
    require_visitor_capability,
)
from probos.ward_room.channels import ChannelManager
```

SEARCH:
```python
logger = logging.getLogger(__name__)


class WardRoomService(EventEmitterMixin):
```
REPLACE:
```python
logger = logging.getLogger(__name__)

# BF-903 (#1581): the channel type a visiting officer's write lands in. Read only for a visiting
# officer, so a crew write costs no query; a DM channel needs dm.send, any other ward_room.post.
_CHANNEL_TYPE_OF_CHANNEL = "SELECT channel_type FROM channels WHERE id = ?"
_CHANNEL_TYPE_OF_THREAD = "SELECT c.channel_type FROM threads t JOIN channels c ON c.id = t.channel_id WHERE t.id = ?"
_CHANNEL_TYPE_OF_POST = "SELECT c.channel_type FROM posts p JOIN threads t ON t.id = p.thread_id JOIN channels c ON c.id = t.channel_id WHERE p.id = ?"


class WardRoomService(EventEmitterMixin):
```

SEARCH:
```python
        self._receipt_facts: DmReceiptFacts | None = None  # AD-1229: built in start()
```
REPLACE:
```python
        self._receipt_facts: DmReceiptFacts | None = None  # AD-1229: built in start()
        self._visiting_officers: Any = None  # BF-903: AD-701's registry, attached by finalize when it is on
```

SEARCH:
```python
    def set_ontology(self, ontology: Any) -> None:
        """Inject ontology reference (constructed after WardRoom)."""
        self._ontology = ontology
```
REPLACE:
```python
    def set_ontology(self, ontology: Any) -> None:
        """Inject ontology reference (constructed after WardRoom)."""
        self._ontology = ontology

    def attach_visiting_officers(self, registry: Any) -> None:
        """BF-903 (#1581): late-bind AD-701's registry, which finalize builds after the Ward Room.

        Unattached (and whenever AD-701 is off), a visiting officer's DID is refused at every
        guarded entry. A crew member's or the Captain's id is never looked up either way.
        """
        self._visiting_officers = registry

    def _require_visitor(self, actor_id: str, capability: str, entry: str) -> None:
        """BF-903: refuse a visiting officer whose session lacks ``capability`` at ``entry``; anyone else passes."""
        require_visitor_capability(
            actor_id,
            capability,
            surface=f"ward_room.{entry}",
            identity_registry=self._identity_registry,
            visiting_officers=self._visiting_officers,
        )

    async def _require_visitor_write(self, actor_id: str, entry: str, query: str, key: str) -> None:
        """BF-903: a visiting officer's write needs dm.send in a DM channel and ward_room.post elsewhere."""
        if not is_visiting_identity(self._identity_registry, actor_id):
            return
        channel_type = ""
        if self._db is not None:
            async with self._db.execute(query, (key,)) as cursor:
                row = await cursor.fetchone()
            channel_type = row[0] if row else ""
        capability = CAP_DM_SEND if channel_type == "dm" else CAP_WARD_ROOM_POST
        self._require_visitor(actor_id, capability, entry)
```

SEARCH:
```python
        return await self._channels.list_channels(agent_id)
```
REPLACE:
```python
        self._require_visitor(agent_id or "", CAP_WARD_ROOM_READ, "list_channels")  # BF-903
        return await self._channels.list_channels(agent_id)
```

SEARCH:
```python
        return await self._channels.get_or_create_dm_channel(agent_a_id, agent_b_id, callsign_a, callsign_b)
```
REPLACE:
```python
        for participant in (agent_a_id, agent_b_id):  # BF-903: a visiting officer in a DM must be able to receive it
            self._require_visitor(participant, CAP_DM_RECEIVE, "get_or_create_dm_channel")
        return await self._channels.get_or_create_dm_channel(agent_a_id, agent_b_id, callsign_a, callsign_b)
```

SEARCH:
```python
        return await self._threads.browse_threads(agent_id, channels, thread_mode, limit, since, sort)
```
REPLACE:
```python
        self._require_visitor(agent_id, CAP_WARD_ROOM_READ, "browse_threads")  # BF-903
        return await self._threads.browse_threads(agent_id, channels, thread_mode, limit, since, sort)
```

SEARCH:
```python
    ) -> WardRoomThread:
        return await self._threads.create_thread(
```
REPLACE:
```python
    ) -> WardRoomThread:
        await self._require_visitor_write(author_id, "create_thread", _CHANNEL_TYPE_OF_CHANNEL, channel_id)  # BF-903
        return await self._threads.create_thread(
```

SEARCH:
```python
        return await self._messages.create_post(thread_id, author_id, body, parent_id, author_callsign)
```
REPLACE:
```python
        await self._require_visitor_write(author_id, "create_post", _CHANNEL_TYPE_OF_THREAD, thread_id)  # BF-903
        return await self._messages.create_post(thread_id, author_id, body, parent_id, author_callsign)
```

SEARCH:
```python
        return await self._messages.edit_post(post_id, author_id, new_body)
```
REPLACE:
```python
        await self._require_visitor_write(author_id, "edit_post", _CHANNEL_TYPE_OF_POST, post_id)  # BF-903
        return await self._messages.edit_post(post_id, author_id, new_body)
```

SEARCH:
```python
        return await self._messages.endorse(target_id, target_type, voter_id, direction)
```
REPLACE:
```python
        self._require_visitor(voter_id, CAP_WARD_ROOM_POST, "endorse")  # BF-903
        return await self._messages.endorse(target_id, target_type, voter_id, direction)
```

SEARCH:
```python
        await self._messages.subscribe(agent_id, channel_id, role)
```
REPLACE:
```python
        self._require_visitor(agent_id, CAP_WARD_ROOM_READ, "subscribe")  # BF-903
        await self._messages.subscribe(agent_id, channel_id, role)

    def check_subscribe(self, agent_id: str) -> None:
        """BF-903 (A4): raise ``VisitorScopeRefused`` exactly where ``subscribe(agent_id, ...)`` would, and do nothing else.

        A caller that subscribes several members, or writes its own rows first, checks every member before its
        first side effect, so a refused visiting officer changes nothing (``AssignmentService``).
        """
        self._require_visitor(agent_id, CAP_WARD_ROOM_READ, entry="subscribe")  # BF-903 (A4): subscribe's check, with no side effect
```

SEARCH:
```python
        await self._messages.update_last_seen(agent_id, channel_id)
```
REPLACE:
```python
        self._require_visitor(agent_id, CAP_WARD_ROOM_READ, "update_last_seen")  # BF-903
        await self._messages.update_last_seen(agent_id, channel_id)
```

SEARCH:
```python
        return await self._messages.get_unread_counts(agent_id)
```
REPLACE:
```python
        self._require_visitor(agent_id, CAP_WARD_ROOM_READ, "get_unread_counts")  # BF-903
        return await self._messages.get_unread_counts(agent_id)
```

SEARCH:
```python
        return await self._messages.get_unread_dms(agent_id, limit, exchange_limit=exchange_limit)
```
REPLACE:
```python
        self._require_visitor(agent_id, CAP_DM_RECEIVE, "get_unread_dms")  # BF-903
        return await self._messages.get_unread_dms(agent_id, limit, exchange_limit=exchange_limit)
```

### 7.9 `src/probos/startup/finalize.py` (M2)

SEARCH:
```python
        await runtime.visiting_officers.start()
        logger.info(
            "AD-701: VisitingOfficerRegistry wired (ttl=%.0fs, sweep=%.0fs)",
```
REPLACE:
```python
        await runtime.visiting_officers.start()
        if runtime.ward_room is not None:  # BF-903 (#1581): the Ward Room checks visiting officers against this registry
            runtime.ward_room.attach_visiting_officers(runtime.visiting_officers)
        logger.info(
            "AD-701: VisitingOfficerRegistry wired (ttl=%.0fs, sweep=%.0fs)",
```

### 7.10 `src/probos/api.py` (M2)

SEARCH:
```python
from probos.routers.auth import verify_ws_token
from probos.ws_event_stream import WSEventStreamHub
```
REPLACE:
```python
from probos.routers.auth import verify_ws_token
from probos.visiting_officers import VisitorScopeRefused
from probos.ws_event_stream import WSEventStreamHub
```

SEARCH:
```python
                "reason": str(exc.reason),
            },
        )

    # CORS for HXI dev server (AD-260)
```
REPLACE:
```python
                "reason": str(exc.reason),
            },
        )

    # BF-903 (#1581): a visiting officer refused by AD-701's seam is a policy outcome, as BF-771's
    # denial is, so a route that reaches a guarded Ward Room entry answers 403 with the reason.
    @app.exception_handler(VisitorScopeRefused)
    async def _visitor_refused(_request: Request, exc: VisitorScopeRefused) -> JSONResponse:
        logger.info("BF-903: %s at the API boundary", exc)
        return JSONResponse(
            status_code=403,
            content={
                "error": "visitor_scope_refused",
                "capability": exc.capability,
                "reason": exc.reason,
                "surface": exc.surface,
            },
        )

    # CORS for HXI dev server (AD-260)
```

### 7.11 New file: `tests/test_bf903_ward_room_scope.py` (M2)

```python
"""BF-903 (#1581) M2: the Ward Room checks a visiting officer's capability at every entry that acts for an actor id.

Real objects: a real ``AgentIdentityRegistry`` and ``WardRoomService`` in ``tmp_path``, the real
``VisitingOfficerRegistry`` with an injected clock, the real API app for the 403, and one real boot (mock LLM).
Crew act by slot id, as ``agent.id`` does, and the Captain by "captain".
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient as _TestClient  # FastAPI's, not a ProbOS name
from httpx import ASGITransport as _ASGITransport  # httpx's names, not ProbOS's
from httpx import AsyncClient as _AsyncClient

from probos.api import create_app
from probos.assignment import AssignmentService
from probos.cognitive.llm_client import MockLLMClient
from probos.config import TEACHING_MIN_COMPILATION_LEVEL, AuthConfig, SystemConfig
from probos.identity import AgentIdentityRegistry
from probos.runtime import ProbOSRuntime
from probos.visiting_officers import (
    CAP_DM_RECEIVE,
    CAP_DM_SEND,
    CAP_WARD_ROOM_POST,
    CAP_WARD_ROOM_READ,
    REFUSED_CAPABILITY,
    REFUSED_EXPIRED,
    REFUSED_NO_SESSION,
    REFUSED_REGISTRY_OFF,
    VisitingOfficerRegistry,
    VisitorScopeRefused,
)
from probos.ward_room.service import WardRoomService

INSTANCE_ID = "bf903-m2-ship"
VESSEL_NAME = "Bf903m2"
CREW_SLOT = "counselor_counselor_0_67c601cb"
ALL = (CAP_WARD_ROOM_POST, CAP_WARD_ROOM_READ, CAP_DM_SEND, CAP_DM_RECEIVE)
Events = list[tuple[str, dict[str, Any]]]

#: entry -> (the capability a visitor needs there, the refusal's surface)
ENTRIES: dict[str, tuple[str, str]] = {
    "create_thread": (CAP_WARD_ROOM_POST, "ward_room.create_thread"),
    "create_post": (CAP_WARD_ROOM_POST, "ward_room.create_post"),
    "edit_post": (CAP_WARD_ROOM_POST, "ward_room.edit_post"),
    "endorse": (CAP_WARD_ROOM_POST, "ward_room.endorse"),
    "subscribe": (CAP_WARD_ROOM_READ, "ward_room.subscribe"),
    "update_last_seen": (CAP_WARD_ROOM_READ, "ward_room.update_last_seen"),
    "browse_threads": (CAP_WARD_ROOM_READ, "ward_room.browse_threads"),
    "list_channels": (CAP_WARD_ROOM_READ, "ward_room.list_channels"),
    "get_unread_counts": (CAP_WARD_ROOM_READ, "ward_room.get_unread_counts"),
    "get_unread_dms": (CAP_DM_RECEIVE, "ward_room.get_unread_dms"),
    "dm_channel_as_a": (CAP_DM_RECEIVE, "ward_room.get_or_create_dm_channel"),
    "dm_channel_as_b": (CAP_DM_RECEIVE, "ward_room.get_or_create_dm_channel"),
}


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@dataclass
class _Rig:
    identities: AgentIdentityRegistry
    officers: VisitingOfficerRegistry
    ward_room: WardRoomService
    clock: _Clock
    events: Events
    all_hands: str
    crew_thread: str
    crew_post: str
    dm_channel: str
    dm_thread: str
    dm_post: str


@pytest.fixture
async def rig(tmp_path: Path) -> AsyncIterator[_Rig]:
    identities = AgentIdentityRegistry(data_dir=tmp_path / "identity")
    ward_room = WardRoomService(db_path=str(tmp_path / "wr.db"), identity_registry=identities)
    try:
        await identities.start()
        await identities.start(instance_id=INSTANCE_ID, vessel_name=VESSEL_NAME, version="1")
        await ward_room.start()
        clock = _Clock()
        events: Events = []
        officers = VisitingOfficerRegistry(
            identities, instance_id=INSTANCE_ID, vessel_name=VESSEL_NAME, baseline_version="1",
            emit_event=lambda name, payload: events.append((name, payload)), clock=clock,
        )
        ward_room.attach_visiting_officers(officers)
        all_hands = await ward_room.get_channel_by_name("All Hands")
        thread = await ward_room.create_thread(all_hands.id, CREW_SLOT, "Crew thread", "crew body")
        post = await ward_room.create_post(thread.id, CREW_SLOT, "crew post")
        dm = await ward_room.get_or_create_dm_channel(CREW_SLOT, "captain")
        dm_thread = await ward_room.create_thread(dm.id, CREW_SLOT, "Crew DM", "dm body")
        dm_post = await ward_room.create_post(dm_thread.id, CREW_SLOT, "dm post")
        yield _Rig(
            identities, officers, ward_room, clock, events,
            all_hands.id, thread.id, post.id, dm.id, dm_thread.id, dm_post.id,
        )
    finally:
        await ward_room.stop()
        await identities.stop()


async def _visitor(rig: _Rig, *capabilities: str) -> str:
    session = await rig.officers.register("visitor", list(capabilities))
    return session.did


def _refusals(events: Events) -> list[dict[str, Any]]:
    return [payload for name, payload in events if name == "VISITING_OFFICER_REFUSED"]


async def _act(rig: _Rig, entry: str, actor: str, *, own: bool) -> None:
    """One call at ``entry`` as ``actor``; with ``own`` an edit targets a post the actor writes first."""
    wr = rig.ward_room
    if entry == "create_thread":
        await wr.create_thread(rig.all_hands, actor, "A visitor's thread", "body")
    elif entry == "create_post":
        await wr.create_post(rig.crew_thread, actor, "a reply")
    elif entry == "edit_post":
        target = (await wr.create_post(rig.crew_thread, actor, "mine")).id if own else rig.crew_post
        await wr.edit_post(target, actor, "edited")
    elif entry == "endorse":
        await wr.endorse(rig.crew_post, "post", actor, "up")
    elif entry == "subscribe":
        await wr.subscribe(actor, rig.all_hands)
    elif entry == "update_last_seen":
        await wr.update_last_seen(actor, rig.all_hands)
    elif entry == "browse_threads":
        await wr.browse_threads(actor)
    elif entry == "list_channels":
        await wr.list_channels(actor)
    elif entry == "get_unread_counts":
        await wr.get_unread_counts(actor)
    elif entry == "get_unread_dms":
        await wr.get_unread_dms(actor)
    elif entry == "dm_channel_as_a":
        await wr.get_or_create_dm_channel(actor, CREW_SLOT)
    elif entry == "dm_channel_as_b":
        await wr.get_or_create_dm_channel(CREW_SLOT, actor)
    else:
        raise AssertionError(f"not an entry: {entry}")


async def _write(rig: _Rig, where: str, actor: str, *, own: bool) -> None:
    wr = rig.ward_room
    if where == "post-in-ship-thread":
        await wr.create_post(rig.crew_thread, actor, "reply")
    elif where == "post-in-dm-thread":
        await wr.create_post(rig.dm_thread, actor, "reply")
    elif where == "thread-in-dm-channel":
        await wr.create_thread(rig.dm_channel, actor, "title", "body")
    elif where == "edit-in-dm-thread":
        target = (await wr.create_post(rig.dm_thread, actor, "mine")).id if own else rig.dm_post
        await wr.edit_post(target, actor, "edited")
    else:
        raise AssertionError(f"not a write: {where}")


@pytest.mark.parametrize("entry", list(ENTRIES))
async def test_a_visitor_without_the_capability_is_refused_at_each_entry(rig: _Rig, entry: str) -> None:
    """W1: each entry refuses a visitor holding every capability but the one it needs, names that capability
    and the entry, and records one refusal."""
    capability, surface = ENTRIES[entry]
    visitor = await _visitor(rig, *(c for c in ALL if c != capability))
    with pytest.raises(VisitorScopeRefused) as refused:
        await _act(rig, entry, visitor, own=False)
    assert (refused.value.did, refused.value.capability, refused.value.reason, refused.value.surface) == (
        visitor, capability, REFUSED_CAPABILITY, surface,
    )
    assert _refusals(rig.events) == [
        {"did": visitor, "capability": capability, "reason": REFUSED_CAPABILITY, "surface": surface},
    ]


@pytest.mark.parametrize("entry", list(ENTRIES))
async def test_a_visitor_with_only_that_capability_is_served_at_each_entry(rig: _Rig, entry: str) -> None:
    """W2: holding exactly the capability an entry needs is enough there."""
    capability, _surface = ENTRIES[entry]
    visitor = await _visitor(rig, capability)
    await _act(rig, entry, visitor, own=True)
    assert _refusals(rig.events) == []


@pytest.mark.parametrize(
    ("where", "granted", "needed"),
    [
        ("post-in-ship-thread", CAP_DM_SEND, CAP_WARD_ROOM_POST),
        ("post-in-dm-thread", CAP_WARD_ROOM_POST, CAP_DM_SEND),
        ("thread-in-dm-channel", CAP_WARD_ROOM_POST, CAP_DM_SEND),
        ("edit-in-dm-thread", CAP_WARD_ROOM_POST, CAP_DM_SEND),
    ],
    ids=["post-in-ship-thread", "post-in-dm-thread", "thread-in-dm-channel", "edit-in-dm-thread"],
)
async def test_a_write_needs_dm_send_in_a_dm_channel_and_ward_room_post_elsewhere(
    rig: _Rig, where: str, granted: str, needed: str,
) -> None:
    """W3: the capability a visitor's write needs follows the channel it lands in; holding it serves the write."""
    with pytest.raises(VisitorScopeRefused) as refused:
        await _write(rig, where, await _visitor(rig, granted), own=False)
    assert refused.value.capability == needed
    await _write(rig, where, await _visitor(rig, needed), own=True)


@pytest.mark.parametrize("lapse", ["expired", "deregistered", "registry-off"])
async def test_a_lapsed_or_unattached_session_is_refused_at_its_next_request(rig: _Rig, lapse: str) -> None:
    """W4: an expired session is refused before any sweep, a deregistered one at once, and with no registry a
    visitor is refused; crew post throughout."""
    session = await rig.officers.register("visitor", list(ALL), session_ttl_seconds=10.0)
    expected = {"expired": REFUSED_EXPIRED, "deregistered": REFUSED_NO_SESSION, "registry-off": REFUSED_REGISTRY_OFF}
    if lapse == "expired":
        rig.clock.now += 10.0
    elif lapse == "deregistered":
        rig.officers.deregister(session.did)
    else:
        rig.ward_room.attach_visiting_officers(None)
    with pytest.raises(VisitorScopeRefused) as refused:
        await rig.ward_room.create_post(rig.crew_thread, session.did, "late")
    assert refused.value.reason == expected[lapse]
    await rig.ward_room.create_post(rig.crew_thread, CREW_SLOT, "crew still posts")
    deregistrations = [n for n, _ in rig.events if n == "VISITING_OFFICER_DEREGISTERED"]
    assert len(deregistrations) == (1 if lapse == "deregistered" else 0)


async def test_crew_and_the_captain_are_served_as_before_without_a_lookup(
    rig: _Rig, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W5 golden: every guarded entry serves a crew slot id and "captain", with the registry attached and not,
    and reads no certificate for them (a lookup raises here)."""
    def _no_lookup(_uuid: str) -> None:
        raise AssertionError("not expected: a crew or Captain id was looked up")

    monkeypatch.setattr(rig.identities, "get_by_uuid", _no_lookup)
    wr = rig.ward_room
    for attached in (True, False):
        wr.attach_visiting_officers(rig.officers if attached else None)
        for actor, other in ((CREW_SLOT, "captain"), ("captain", CREW_SLOT)):
            thread = await wr.create_thread(rig.all_hands, actor, "t", "b")
            post = await wr.create_post(thread.id, actor, "p")
            await wr.edit_post(post.id, actor, "edited")
            await wr.endorse(post.id, "post", other, "up")
            await wr.subscribe(actor, rig.all_hands)
            await wr.update_last_seen(actor, rig.all_hands)
            await wr.browse_threads(actor)
            await wr.list_channels(actor)
            await wr.get_unread_counts(actor)
            await wr.get_unread_dms(actor)
            await wr.get_or_create_dm_channel(actor, other)
    assert _refusals(rig.events) == []


async def test_a_crew_did_is_served(rig: _Rig) -> None:
    """W6: a crew member acting by its certificate DID is looked up, found not visiting, and served."""
    crew = await rig.identities.resolve_or_issue(
        slot_id=CREW_SLOT, agent_type="counselor", callsign="Counselor", instance_id=INSTANCE_ID,
        vessel_name=VESSEL_NAME, department="medical", post_id="counselor", baseline_version="v1",
    )
    thread = await rig.ward_room.create_thread(rig.all_hands, crew.did, "t", "b")
    assert thread.author_id == crew.did
    assert _refusals(rig.events) == []


class _RefusingWardRoom:
    """Raises the real refusal from create_thread; the guard itself is W1-W4's."""

    async def create_thread(self, **_kwargs: Any) -> None:
        raise VisitorScopeRefused(
            "did:probos:ship:visitor", CAP_WARD_ROOM_POST, REFUSED_CAPABILITY, "ward_room.create_thread",
        )


def _api_runtime(ward_room: Any) -> Any:
    """The mock runtime BF-771's API test builds (tests/test_bf771_intent_authorization.py:515-534)."""
    runtime = MagicMock()
    runtime.registry = MagicMock()
    runtime.profile_store = None
    cfg = MagicMock()
    cfg.auth = AuthConfig()
    runtime.config = cfg
    runtime.callsign_registry = MagicMock()
    runtime.callsign_registry.get_callsign.return_value = ""
    runtime.callsign_registry.resolve.return_value = None
    runtime.callsign_registry.all_callsigns.return_value = {}
    runtime.hebbian_router = MagicMock()
    runtime.hebbian_router.all_weights_typed.return_value = {}
    runtime._start_time = 0.0
    runtime.episodic_memory = None
    runtime.work_item_store = None
    runtime.proactive_loop = None
    runtime.ontology = None
    runtime.add_event_listener = MagicMock()
    runtime.ward_room = ward_room
    # A4: a MagicMock data directory is truthy, and create_app would create its model folders under the working
    # directory (api.py:377-389); this double has none.
    runtime._data_dir = None
    runtime.data_dir = None
    return runtime


def test_the_api_answers_a_visitor_refusal_with_403_and_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W7: a refusal from the Ward Room reaches the client as 403 with the capability, reason and surface. The app is
    built in an empty working directory and leaves it empty: the runtime double has no data directory (A4)."""
    monkeypatch.chdir(tmp_path)
    client = _TestClient(create_app(_api_runtime(_RefusingWardRoom())), raise_server_exceptions=False)
    assert list(tmp_path.iterdir()) == []
    response = client.post(
        "/api/wardroom/channels/c1/threads",
        json={"author_id": "did:probos:ship:visitor", "title": "t", "body": "b"},
    )
    assert response.status_code == 403, response.text
    assert response.json() == {
        "error": "visitor_scope_refused",
        "capability": CAP_WARD_ROOM_POST,
        "reason": REFUSED_CAPABILITY,
        "surface": "ward_room.create_thread",
    }


_SUBSCRIBE_REFUSED = {
    "error": "visitor_scope_refused",
    "capability": CAP_WARD_ROOM_READ,
    "reason": REFUSED_CAPABILITY,
    "surface": "ward_room.subscribe",
}


class _Chamber:
    """A Birth Chamber that has graduated no one, so ``AssignmentService`` defers every subscription to it (AD-486)."""

    def __init__(self) -> None:
        self.queued: list[tuple[str, str]] = []

    def is_graduated(self, agent_id: str) -> bool:
        return False

    def queue_pending_subscription(self, agent_id: str, channel_id: str, subscribe: Any) -> None:
        self.queued.append((agent_id, channel_id))


class _Procedure:
    """The members the teaching route reads from an approved Level-5 procedure."""

    name = "bf903-procedure"
    description = "a procedure fit to teach"
    compilation_level = TEACHING_MIN_COMPILATION_LEVEL
    steps: tuple[Any, ...] = ()


class _TeachingStore:
    """The three ``ProcedureStore`` reads the teaching route makes; the store is upstream of the seam under test."""

    async def get(self, procedure_id: str) -> _Procedure:
        return _Procedure()

    async def get_promotion_status(self, procedure_id: str) -> str:
        return "approved"

    async def get_quality_metrics(self, procedure_id: str) -> dict[str, Any]:
        return {"total_completions": 10, "effective_rate": 0.9}


def _client(runtime: Any) -> _AsyncClient:
    """The real API app over an in-process ASGI transport, on the test's own event loop."""
    return _AsyncClient(transport=_ASGITransport(app=create_app(runtime)), base_url="http://bf903.test")


async def test_an_assignment_naming_a_refused_visitor_changes_nothing_and_answers_403(rig: _Rig, tmp_path: Path) -> None:
    """W9 (A4): POST /api/assignments checks every member before the channel, a subscription or a row exists, so a
    request naming a visitor without ward_room.read answers 403 with the reason and leaves no assignment, channel,
    subscription or deferred subscription; a visitor holding ward_room.read joins with every member subscribed.
    Before A4 the service swallowed the refusal: 200, every member recorded, the members after the visitor not
    subscribed."""
    service = AssignmentService(db_path=str(tmp_path / "assignments.db"), ward_room=rig.ward_room)
    await service.start()
    try:
        runtime = _api_runtime(rig.ward_room)
        runtime.assignment_service = service
        refused_visitor = await _visitor(rig, CAP_DM_SEND)
        reader = await _visitor(rig, CAP_WARD_ROOM_READ)
        channels = [c.id for c in await rig.ward_room.list_channels()]
        chamber = _Chamber()
        async with _client(runtime) as client:
            refused = await client.post(
                "/api/assignments",
                json={"name": "Away", "assignment_type": "away_team", "members": [CREW_SLOT, refused_visitor, "captain"]},
            )
            assert refused.status_code == 403, refused.text
            assert refused.json() == _SUBSCRIBE_REFUSED
            service.set_birth_chamber(chamber)
            deferred = await client.post(
                "/api/assignments",
                json={"name": "Away", "assignment_type": "away_team", "members": [CREW_SLOT, refused_visitor]},
            )
            assert deferred.status_code == 403, deferred.text
            assert chamber.queued == []
            assert await service.list_assignments() == []
            assert [c.id for c in await rig.ward_room.list_channels()] == channels
            assert [p["surface"] for p in _refusals(rig.events)] == ["ward_room.subscribe", "ward_room.subscribe"]
            service.set_birth_chamber(None)
            served = await client.post(
                "/api/assignments",
                json={"name": "Away", "assignment_type": "away_team", "members": [CREW_SLOT, reader, "captain"]},
            )
        assert served.status_code == 200, served.text
        channel = served.json()["ward_room_channel_id"]
        for member in (CREW_SLOT, reader, "captain"):
            assert channel in [c.id for c in await rig.ward_room.list_channels(member)]
    finally:
        await service.stop()


async def test_adding_a_refused_visitor_to_an_assignment_writes_no_member_and_answers_403(
    rig: _Rig, tmp_path: Path,
) -> None:
    """W10 (A4): POST /api/assignments/{id}/members checks the member before its row is written, so a visitor without
    ward_room.read answers 403 and the assignment keeps its members; a visitor holding it joins and is subscribed.
    Before A4 the row was committed, the refusal swallowed and the answer 200."""
    service = AssignmentService(db_path=str(tmp_path / "assignments.db"), ward_room=rig.ward_room)
    await service.start()
    try:
        runtime = _api_runtime(rig.ward_room)
        runtime.assignment_service = service
        assignment = await service.create_assignment("Away", "away_team", "captain", [CREW_SLOT])
        refused_visitor = await _visitor(rig, CAP_DM_SEND)
        reader = await _visitor(rig, CAP_WARD_ROOM_READ)
        async with _client(runtime) as client:
            refused = await client.post(f"/api/assignments/{assignment.id}/members", json={"agent_id": refused_visitor})
            assert refused.status_code == 403, refused.text
            assert refused.json() == _SUBSCRIBE_REFUSED
            assert set((await service.get_assignment(assignment.id)).members) == {CREW_SLOT}
            served = await client.post(f"/api/assignments/{assignment.id}/members", json={"agent_id": reader})
        assert served.status_code == 200, served.text
        assert set((await service.get_assignment(assignment.id)).members) == {CREW_SLOT, reader}
        assert assignment.ward_room_channel_id in [c.id for c in await rig.ward_room.list_channels(reader)]
    finally:
        await service.stop()


async def test_the_teaching_route_answers_a_visitor_refusal_with_403(rig: _Rig) -> None:
    """W11 (A4): POST /api/procedures/teach lets a scope refusal reach the API's handler instead of answering 200 with
    an error string, so a visitor target without dm.receive answers 403 and no DM channel is opened; a crew target is
    taught as before."""
    runtime = _api_runtime(rig.ward_room)
    runtime.procedure_store = _TeachingStore()
    visitor = await _visitor(rig, CAP_DM_SEND)
    channels = [c.id for c in await rig.ward_room.list_channels()]
    async with _client(runtime) as client:
        refused = await client.post("/api/procedures/teach", json={"procedure_id": "p1", "target_callsign": visitor})
        assert refused.status_code == 403, refused.text
        assert refused.json() == {
            "error": "visitor_scope_refused",
            "capability": CAP_DM_RECEIVE,
            "reason": REFUSED_CAPABILITY,
            "surface": "ward_room.get_or_create_dm_channel",
        }
        assert [c.id for c in await rig.ward_room.list_channels()] == channels
        served = await client.post("/api/procedures/teach", json={"procedure_id": "p1", "target_callsign": CREW_SLOT})
    assert served.status_code == 200, served.text
    assert served.json()["success"] is True


async def test_a_real_boot_scopes_visitors_in_the_ward_room(tmp_path: Path) -> None:
    """W8: with AD-701 on, a booted Ward Room refuses a reader's thread for its capability and serves a poster's."""
    config = SystemConfig()
    config.onboarding.naming_ceremony = False
    config.proactive_cognitive.enabled = False
    config.qa.enabled = False
    config.visiting_officers.enabled = True
    config.ward_room.enabled = True  # WardRoomConfig.enabled is off by default, so runtime.ward_room is None without it
    runtime = ProbOSRuntime(config=config, data_dir=tmp_path / "data", llm_client=MockLLMClient())
    await runtime.start()
    try:
        reader = await runtime.visiting_officers.register("boot-reader", [CAP_WARD_ROOM_READ])
        poster = await runtime.visiting_officers.register("boot-poster", [CAP_WARD_ROOM_POST])
        all_hands = await runtime.ward_room.get_channel_by_name("All Hands")
        with pytest.raises(VisitorScopeRefused) as refused:
            await runtime.ward_room.create_thread(all_hands.id, reader.did, "t", "b")
        assert refused.value.reason == REFUSED_CAPABILITY
        thread = await runtime.ward_room.create_thread(all_hands.id, poster.did, "t", "b")
        assert thread.author_id == poster.did
    finally:
        await runtime.stop()
```

### 7.12 New file: `tests/test_bf903_seam_was_open.py` (M2)

```python
"""BF-903 (#1581): the seam was open. Written against names that exist before BF-903, so on that tree this test
fails for its premise (a visiting officer without ward_room.post opens a thread), not on an import. After BF-903
the Ward Room has no registry attached here, so the visitor is refused with ``visitor_registry_off``."""

from __future__ import annotations

from pathlib import Path

import pytest

from probos.identity import AgentIdentityRegistry
from probos.visiting_officers import VisitingOfficerRegistry
from probos.ward_room.service import WardRoomService


async def test_a_visitor_without_ward_room_post_cannot_open_a_thread(tmp_path: Path) -> None:
    identities = AgentIdentityRegistry(data_dir=tmp_path / "identity")
    ward_room = WardRoomService(db_path=str(tmp_path / "wr.db"), identity_registry=identities)
    try:
        await identities.start()
        await identities.start(instance_id="bf903-open-ship", vessel_name="Bf903open", version="1")
        await ward_room.start()
        officers = VisitingOfficerRegistry(
            identities, instance_id="bf903-open-ship", vessel_name="Bf903open", baseline_version="1",
        )
        reader = await officers.register("reader", ["ward_room.read"])
        channel = await ward_room.get_channel_by_name("All Hands")
        before = await ward_room.count_threads(channel.id)
        with pytest.raises(PermissionError):
            await ward_room.create_thread(channel.id, reader.did, "Not allowed", "body")
        assert await ward_room.count_threads(channel.id) == before
    finally:
        await ward_room.stop()
        await identities.stop()
```

### 7.12b `src/probos/assignment.py` (M2, A4: every member is checked before the first side effect)

`create_assignment` and `add_member` treat any Ward Room failure as optional (`except Exception`, `assignment.py:202`, `:339`). A refused subscribe therefore skipped the members after it and the route answered 200 (M2 review, finding 1). Each now checks every member with `check_subscribe` (7.8) before the channel, any subscription or any row, and only where a subscription would follow. The refusal reaches the API's handler through the router's `except ValueError`. The handlers themselves are unchanged (R11).

SEARCH:
```python
        now = time.time()
        assignment_id = str(uuid.uuid4())
        ward_room_channel_id = ""
```
REPLACE:
```python
        if self._ward_room:
            # BF-903 (#1581, A4): the subscription loop below swallows a refusal, so every member is checked before
            # the channel, any subscription or any row exists; a refusal reaches the API's 403 with nothing written.
            for agent_id in members:
                self._ward_room.check_subscribe(agent_id)  # BF-903 (A4): every member is checked before the channel or any row exists

        now = time.time()
        assignment_id = str(uuid.uuid4())
        ward_room_channel_id = ""
```

SEARCH:
```python
        if agent_id in assignment.members:
            raise ValueError(f"Agent {agent_id} is already a member")

        now = time.time()
```
REPLACE:
```python
        if agent_id in assignment.members:
            raise ValueError(f"Agent {agent_id} is already a member")
        if self._ward_room and assignment.ward_room_channel_id:
            self._ward_room.check_subscribe(agent_id)  # BF-903 (A4): checked before the member row is written

        now = time.time()
```

### 7.12c `src/probos/routers/procedures.py` (M2, A4: the teaching route lets a scope refusal through)

The route's `except Exception` (`:207-208`) turned a refusal for a body-supplied `target_callsign` into HTTP 200 with an error string (M2 review, finding 2). The refusal now reaches the API's 403 handler. Other failures keep their answer.

SEARCH:
```python
from probos.routers.deps import get_runtime
```
REPLACE:
```python
from probos.routers.deps import get_runtime
from probos.visiting_officers import VisitorScopeRefused
```

SEARCH:
```python
            author_callsign="captain",
        )
    except Exception as e:
        return {"success": False, "error": f"Teaching DM failed: {e}"}
```
REPLACE:
```python
            author_callsign="captain",
        )
    except VisitorScopeRefused:  # BF-903 (A4): a scope refusal reaches the API's 403 handler, not this route's error string
        raise
    except Exception as e:
        return {"success": False, "error": f"Teaching DM failed: {e}"}
```

### 7.13 `src/probos/visiting_officers.py` (M3: a visitor is named by its DID or its certificate UUID; applies to the text 7.1 builds)

SEARCH:
```python
- **One guard** (BF-903): every path that acts for an actor id calls
  ``require_visitor_capability`` before acting. A crew member's id is
  never looked up; a visiting officer's DID must hold the capability in a
  live session, read at use.
```
REPLACE:
```python
- **One guard** (BF-903): every path that acts for an actor id calls
  ``require_visitor_capability`` before acting. A crew member's slot id is
  never looked up; a visiting officer, named by its DID or its bare
  certificate UUID, must hold the capability in a live session, read at
  use. A path that already knows its sender is a visitor (a paired channel
  sender) calls ``require_session_capability``.
```

SEARCH:
```python
def is_visiting_identity(identity_registry: Any, actor_id: object) -> bool:
    """BF-903: whether ``actor_id`` is the DID of a visiting officer's birth certificate.

    Only a did:probos agent DID is looked up, in the identity registry's in-memory certificate
    cache (``get_by_uuid``, which never raises), so a slot id, a callsign, "captain" or "system"
    costs no lookup and is never refused here. The certificate outlives its session, so an
    expired or deregistered visitor is still recognised and refused. BF-907's
    ``resolve_slot_id`` and AD-1346's ``IdentityService.resolve`` return None for a visitor,
    which holds no slot, so they cannot classify one; this reads the agent type AD-701 sets.
    """
    if type(actor_id) is not str or not actor_id.startswith("did:") or identity_registry is None:
        return False
    from probos.identity import is_sovereign_identity_key, parse_did  # BF-903: imported at use; at load this module reads only probos.config_models (A2)

    parsed = parse_did(actor_id)
    if parsed is None or parsed.get("type") != "agent":
        return False
    if not is_sovereign_identity_key(parsed["agent_uuid"]):  # BF-903 (A3): a malformed agent part costs no lookup
        return False
    cert = identity_registry.get_by_uuid(parsed["agent_uuid"])
    return cert is not None and cert.agent_type == VISITING_AGENT_TYPE


def require_visitor_capability(
    actor_id: str,
    capability: str,
    *,
    surface: str,
    identity_registry: Any,
    visiting_officers: VisitingOfficerRegistry | None,
) -> None:
    """BF-903 (#1581): the one check every path that acts for an actor id calls before it acts.

    A crew member, the Captain or the system passes without a lookup. A visiting officer must
    hold ``capability`` in a live session; with AD-701's registry off it holds none and is
    refused. ``surface`` names the entry in the refusal and its record. An undeclared
    ``capability`` raises ``UnknownCapabilityError`` whoever acts, so a typo in a checking
    path fails on its first call.
    """
    if capability not in VISITOR_CAPABILITIES:
        raise UnknownCapabilityError([capability])
    if not is_visiting_identity(identity_registry, actor_id):
        return
    if visiting_officers is None:
        logger.warning(
            "BF-903: refused visiting officer %s %r at %s: AD-701's registry is off, so no session exists",
            actor_id, capability, surface,
        )
        raise VisitorScopeRefused(actor_id, capability, REFUSED_REGISTRY_OFF, surface)
    visiting_officers.check(actor_id, capability, surface=surface)
```
REPLACE:
```python
def visiting_certificate(identity_registry: Any, actor_id: object) -> Any:
    """BF-903: the birth certificate of the visiting officer ``actor_id`` names, or None.

    A sovereign identity takes two key shapes (BF-907's ``is_sovereign_identity_key``): a
    did:probos agent DID and its bare certificate UUID. Both name the visitor, because downstream
    stores key an identity by whichever id it acts as (an author's Ward Room episode is stored
    under the id it posts as). Only those two shapes are looked up, in the identity registry's
    in-memory certificate cache (``get_by_uuid``, which never raises); a slot id, a callsign,
    "captain", "system" or a 32-hex agent id matches neither and costs no lookup. A crew
    certificate's DID or UUID is looked up and is not a visitor. The certificate outlives its
    session, so an expired or deregistered visitor is still recognised and refused. BF-907's
    ``resolve_slot_id`` and AD-1346's ``IdentityService.resolve`` return None for a visitor, which
    holds no slot, so they cannot classify one; this reads the agent type AD-701 sets.
    """
    if type(actor_id) is not str or identity_registry is None:
        return None
    from probos.identity import is_sovereign_identity_key, parse_did  # BF-903: imported at use; at load this module reads only probos.config_models (A2)

    if not is_sovereign_identity_key(actor_id):
        return None
    agent_uuid = actor_id
    if actor_id.startswith("did:"):
        parsed = parse_did(actor_id)
        if parsed is None or parsed.get("type") != "agent":
            return None
        agent_uuid = parsed["agent_uuid"]
        if not is_sovereign_identity_key(agent_uuid):  # BF-903 (A3): a malformed agent part costs no lookup
            return None
    cert = identity_registry.get_by_uuid(agent_uuid)
    return cert if cert is not None and cert.agent_type == VISITING_AGENT_TYPE else None


def is_visiting_identity(identity_registry: Any, actor_id: object) -> bool:
    """BF-903: whether ``actor_id`` names a visiting officer, by its DID or its certificate UUID."""
    return visiting_certificate(identity_registry, actor_id) is not None


def require_session_capability(
    did: str,
    capability: str,
    *,
    surface: str,
    visiting_officers: VisitingOfficerRegistry | None,
) -> None:
    """BF-903 (#1581): a known visiting officer's DID must hold ``capability`` in a live session.

    For a caller that already knows its sender is a visitor (a paired channel sender, AD-802),
    and for ``require_visitor_capability`` once it has recognised one. With AD-701's registry off
    no session exists, so the visitor is refused. An undeclared ``capability`` raises
    ``UnknownCapabilityError``.
    """
    require_known_capabilities((capability,))  # BF-903: a typo in a checking path fails on its first call
    if visiting_officers is None:
        logger.warning(
            "BF-903: refused visiting officer %s %r at %s: AD-701's registry is off, so no session exists",
            did, capability, surface,
        )
        raise VisitorScopeRefused(did, capability, REFUSED_REGISTRY_OFF, surface)
    visiting_officers.check(did, capability, surface=surface)


def require_visitor_capability(
    actor_id: str,
    capability: str,
    *,
    surface: str,
    identity_registry: Any,
    visiting_officers: VisitingOfficerRegistry | None,
) -> None:
    """BF-903 (#1581): the one check every path that acts for an actor id calls before it acts.

    A crew member's slot id, the Captain or the system passes without a lookup. A visiting
    officer, named by its DID or its certificate UUID, must hold ``capability`` in a live
    session, checked under its DID (the registry's key); with AD-701's registry off it holds
    none and is refused. ``surface`` names the entry in the refusal and its record. An
    undeclared ``capability`` raises ``UnknownCapabilityError`` whoever acts, so a typo in a
    checking path fails on its first call.
    """
    if capability not in VISITOR_CAPABILITIES:
        raise UnknownCapabilityError([capability])
    cert = visiting_certificate(identity_registry, actor_id)
    if cert is None:
        return
    require_session_capability(cert.did, capability, surface=surface, visiting_officers=visiting_officers)
```

### 7.14 `tests/test_bf903_visitor_scope.py` (M3: V7 and V8 cover the certificate UUID; applies to the text 7.7 builds)

SEARCH:
```python
    is_visiting_identity,
    require_visitor_capability,
)
```
REPLACE:
```python
    is_visiting_identity,
    require_session_capability,
    require_visitor_capability,
)
```

SEARCH:
```python
    """V7: a visiting certificate's DID is a visitor even after its session ends; a crew DID, an unknown DID,
    the ship's DID and a missing registry are not; ids that are not DIDs are never looked up."""
    officers = _officers(identities, _Clock(), [])
    session = await officers.register("visitor", [CAP_WARD_ROOM_READ])
    crew = await _crew(identities)
    assert is_visiting_identity(identities, session.did) is True
    officers.deregister(session.did)
    assert is_visiting_identity(identities, session.did) is True
    assert is_visiting_identity(identities, crew.did) is False
    assert is_visiting_identity(identities, f"did:probos:{INSTANCE_ID}:{UNKNOWN_UUID}") is False
    assert is_visiting_identity(identities, f"did:probos:{INSTANCE_ID}") is False
    assert is_visiting_identity(None, session.did) is False

    def _no_lookup(_uuid: str) -> None:
        raise AssertionError("not expected: an id that is not a DID was looked up")

    monkeypatch.setattr(identities, "get_by_uuid", _no_lookup)
    for actor in (CREW_SLOT, "captain", "system", crew.agent_uuid, "", None):
        assert is_visiting_identity(identities, actor) is False
```
REPLACE:
```python
    """V7: a visiting certificate is a visitor by its DID and by its bare certificate UUID, even after its session
    ends; a crew DID or UUID, an unknown DID or UUID, the ship's DID and a missing registry are not; an id of
    neither shape is never looked up (BF-903 A1)."""
    officers = _officers(identities, _Clock(), [])
    session = await officers.register("visitor", [CAP_WARD_ROOM_READ])
    crew = await _crew(identities)
    visitor_uuid = session.did.rsplit(":", 1)[1]
    assert is_visiting_identity(identities, session.did) is True
    assert is_visiting_identity(identities, visitor_uuid) is True
    officers.deregister(session.did)
    assert is_visiting_identity(identities, session.did) is True
    assert is_visiting_identity(identities, visitor_uuid) is True
    assert is_visiting_identity(identities, crew.did) is False
    assert is_visiting_identity(identities, crew.agent_uuid) is False
    assert is_visiting_identity(identities, UNKNOWN_UUID) is False
    assert is_visiting_identity(identities, f"did:probos:{INSTANCE_ID}:{UNKNOWN_UUID}") is False
    assert is_visiting_identity(identities, f"did:probos:{INSTANCE_ID}") is False
    assert is_visiting_identity(None, session.did) is False

    def _no_lookup(_uuid: str) -> None:
        raise AssertionError("not expected: an id that is neither a DID nor a certificate UUID was looked up")

    monkeypatch.setattr(identities, "get_by_uuid", _no_lookup)
    # A slot id, the Captain, the system, a BaseAgent default id (uuid4().hex) and an upper-case UUID match neither shape.
    for actor in (CREW_SLOT, "captain", "system", "0123456789abcdef0123456789abcdef", visitor_uuid.upper(), "", None):
        assert is_visiting_identity(identities, actor) is False
```

SEARCH:
```python
    """V8: crew pass with or without the registry; a visitor is served a held capability, refused a missing
    one and refused outright with the registry off; an undeclared capability raises for anyone."""
```
REPLACE:
```python
    """V8: crew pass with or without the registry; a visitor is served a held capability, refused a missing
    one and refused outright with the registry off; its certificate UUID is checked under its DID (A1); an
    undeclared capability raises for anyone, and at ``require_session_capability`` too."""
```

SEARCH:
```python
    assert missing.value.reason == REFUSED_CAPABILITY
    with pytest.raises(VisitorScopeRefused) as off:
```
REPLACE:
```python
    assert missing.value.reason == REFUSED_CAPABILITY
    visitor_uuid = session.did.rsplit(":", 1)[1]
    require_visitor_capability(
        visitor_uuid, CAP_WARD_ROOM_READ, surface="v8", identity_registry=identities, visiting_officers=officers,
    )
    with pytest.raises(VisitorScopeRefused) as by_uuid:
        require_visitor_capability(
            visitor_uuid, CAP_WARD_ROOM_POST, surface="v8.uuid", identity_registry=identities,
            visiting_officers=officers,
        )
    assert (by_uuid.value.did, by_uuid.value.reason) == (session.did, REFUSED_CAPABILITY)
    with pytest.raises(UnknownCapabilityError):
        require_session_capability(session.did, "ward_room.pots", surface="v8", visiting_officers=officers)
    with pytest.raises(VisitorScopeRefused) as off:
```

SEARCH:
```python
    assert [p["surface"] for p in _refusals(events)] == ["v8.post"]
```
REPLACE:
```python
    assert [p["surface"] for p in _refusals(events)] == ["v8.post", "v8.uuid"]
```

### 7.15 `src/probos/channels/base.py` (M3)

SEARCH:
```python
    # AD-802a: DID attached by `_check_pairing` for paired senders.
    # Stays None when the sender is not yet paired, when the adapter has no
    # `channel_name` and so opts out of pairing, when the runtime has no
    # pairing service, and on the `resolve_did` fail-open path -- so
    # `handle_message` can legitimately run with this unset.
    paired_did: str | None = None
```
REPLACE:
```python
    # AD-802a: DID attached by `_check_pairing` for paired senders.
    # Stays None when the sender is not yet paired, when the adapter has no
    # `channel_name` and so opts out of pairing, or when the runtime has no
    # pairing service -- so `handle_message` can legitimately run with this
    # unset. BF-903 (#1581): once set, the sender is a visiting officer and
    # `handle_message` serves it only an @callsign direct message, with dm.send.
    paired_did: str | None = None
```

SEARCH:
```python
    `GmailAdapter._poll_loop` already declines to acknowledge when
    `handle_message` raises, so this leaves the mail UNSEEN and re-fetched on
    the next poll without any edit to that adapter.
    """


class ChannelAdapter(ABC):
```
REPLACE:
```python
    `GmailAdapter._poll_loop` already declines to acknowledge when
    `handle_message` raises, so this leaves the mail UNSEEN and re-fetched on
    the next poll without any edit to that adapter.
    """


#: BF-903 (#1581): the entire text of a `PairingLookupError`. Like BF-804's
#: notice it names the channel and nothing else: Teams echoes it into an HTTP
#: body (`routers/teams_webhook.py`).
_PAIRING_LOOKUP_FAILED = (
    "the pairing state could not be read on channel {channel}"
)

#: BF-903 (#1581): the replies a paired sender -- a visiting officer -- gets for
#: what its visit does not allow. They name the reason and nothing internal.
_PAIRED_NO_COMMANDS = (
    "Slash commands are not available to a paired visitor; send @callsign "
    "<message> to reach a crew member (BF-903)."
)
_PAIRED_NO_CONVERSATION = (
    "A paired visitor may send @callsign <message> to a crew member and "
    "nothing else (BF-903)."
)
_PAIRED_DM_REFUSED = (
    "Your message was not delivered: your visit does not allow direct "
    "messages ({reason}) (BF-903)."
)


class PairingLookupError(PairingNotificationError):
    """BF-903 (#1581): `resolve_did` failed, so whether the sender is paired is unknown.

    AD-802a let such a message through (fail-open). A paired sender is a
    visiting officer, so an unclassified one reaching the slash-command and
    natural-language paths could be granted what pairing refuses. This is a
    `PairingNotificationError`, so every caller's existing handling applies
    unchanged: Gmail withholds its acknowledgement and retries on the next
    poll; Slack's webhook returns "" and its poll, Telegram and Matrix log and
    move on; Discord logs and posts nothing; Teams answers HTTP 200 with this
    text. On all but Gmail the sender must send again.
    """


class ChannelAdapter(ABC):
```

SEARCH:
```python
                - returns a DID -> attach to `message.paired_did`, return True.
                - raises        -> fail open, return True.
```
REPLACE:
```python
                - returns a DID -> attach to `message.paired_did`, return True.
                - raises        -> raise `PairingLookupError` (BF-903: fail
                                   closed; a `PairingNotificationError`).
```

SEARCH:
```python
        try:
            did = pairing_service.resolve_did(self.channel_name, message.user_id)
        except Exception:
            logger.warning(
                "AD-802a: resolve_did failed for channel=%s user_id=%s; "
                "allowing message (fail-open)",
                self.channel_name, message.user_id, exc_info=True,
            )
            return True
```
REPLACE:
```python
        try:
            did = pairing_service.resolve_did(self.channel_name, message.user_id)
        except Exception as exc:
            logger.error(
                "AD-802a/BF-903: resolve_did failed for channel=%s user_id=%s; "
                "refusing the message (fail-closed): a sender whose pairing "
                "cannot be read may be a visiting officer. Raising "
                "PairingLookupError, which each caller handles as it handles "
                "PairingNotificationError.",
                self.channel_name, message.user_id, exc_info=True,
            )
            raise PairingLookupError(_PAIRING_LOOKUP_FAILED.format(channel=self.channel_name)) from exc
```

SEARCH:
```python
        an acknowledgement gate (Gmail) leaves the message for the next poll
        instead of recording it as handled.
        """
        from probos.utils.response_formatter import extract_response_text
```
REPLACE:
```python
        an acknowledgement gate (Gmail) leaves the message for the next poll
        instead of recording it as handled.

        BF-903 (#1581): a paired sender is a visiting officer; `_handle_paired`
        serves it an @callsign direct message, with dm.send, and refuses the
        rest with a reply naming the reason.
        """
        from probos.utils.response_formatter import extract_response_text
```

SEARCH:
```python
        text = message.text.strip()
        if not text:
            return ""

        if text.startswith("/"):
            from probos.api import _handle_slash_command
```
REPLACE:
```python
        text = message.text.strip()
        if not text:
            return ""

        if message.paired_did is not None:  # BF-903 (#1581): a paired sender is a visiting officer
            return await self._handle_paired(message.paired_did, text)

        if text.startswith("/"):
            from probos.api import _handle_slash_command
```

SEARCH:
```python
        return response_text

    async def _handle_callsign_resolved(self, resolved: dict, callsign: str, message_text: str) -> str:
```
REPLACE:
```python
        return response_text

    async def _handle_paired(self, did: str, text: str) -> str:
        """BF-903 (#1581): what a paired sender may do here -- an @callsign direct message, with dm.send.

        Pairing registered the sender as a visiting officer (AD-802), so its
        session is checked directly, at use, in AD-701's registry; with no
        registry attached the message is refused. No declared capability grants
        a slash command or a natural-language turn, so each is refused with a
        reply naming the reason. The AD that wires pairing declares what more a
        paired sender may do.
        """
        from probos.crew_profile import extract_callsign_mention
        from probos.visiting_officers import CAP_DM_SEND, VisitorScopeRefused, require_session_capability

        if text.startswith("/"):  # BF-903: no declared capability grants a slash command
            logger.warning(
                "BF-903: refused a slash command from paired sender %s on channel %s",
                did, self.channel_name,
            )
            return _PAIRED_NO_COMMANDS
        mention = extract_callsign_mention(text)
        resolved = None if mention is None else self.runtime.callsign_registry.resolve(mention[0])
        if mention is None or resolved is None:
            logger.warning(
                "BF-903: refused a natural-language turn from paired sender %s on channel %s",
                did, self.channel_name,
            )
            return _PAIRED_NO_CONVERSATION
        try:
            require_session_capability(
                did, CAP_DM_SEND, surface=f"channel.{self.channel_name}.dm",
                visiting_officers=getattr(self.runtime, "visiting_officers", None),
            )
        except VisitorScopeRefused as refused:
            return _PAIRED_DM_REFUSED.format(reason=refused.reason)
        callsign, message_text = mention
        return await self._handle_callsign_resolved(resolved, callsign, message_text)

    async def _handle_callsign_resolved(self, resolved: dict, callsign: str, message_text: str) -> str:
```

### 7.16 `src/probos/federation/mcp_server.py` (M3)

SEARCH:
```python
from probos.types import IntentDescriptor, IntentMessage

if TYPE_CHECKING:
```
REPLACE:
```python
from probos.types import IntentDescriptor, IntentMessage
from probos.visiting_officers import is_visiting_identity

if TYPE_CHECKING:
```

SEARCH:
```python
_BIND_FAILED = "AD-480a: MCP server bind failed (port %d): %s; the MCP server is not listening and ProbOS carries on (BF-884)"


def bearer_token_matches(authorization: str, expected: str) -> bool:
```
REPLACE:
```python
_BIND_FAILED = "AD-480a: MCP server bind failed (port %d): %s; the MCP server is not listening and ProbOS carries on (BF-884)"
MAX_ARGUMENT_VALUES = 10_000  # BF-903: values the visitor walk counts, queues and reads in one tools/call, a container counted from its length before its children are read (A4); cost: a call with more is refused (the HXI games send a handful)
REFUSED_VISITOR_UNBOUND = "visitor_unbound"
REFUSED_ARGUMENTS_UNWALKED = "arguments_unwalked"
_VISITOR_REFUSALS = {
    REFUSED_VISITOR_UNBOUND: (
        "Tool {name!r} was refused over MCP (BF-903): its arguments name a visiting officer, and "
        "this server cannot bind a call to a visiting officer's session (AD-1342 will)"
    ),
    REFUSED_ARGUMENTS_UNWALKED: (
        f"Tool {{name!r}} was refused over MCP (BF-903): its arguments hold more than "
        f"{MAX_ARGUMENT_VALUES} values, so they could not be checked for a visiting officer"
    ),
}


def visitor_argument_refusal(arguments: dict[str, Any], identity_registry: Any) -> str | None:
    """BF-903 (#1581): why a tools/call's arguments may not be dispatched, or None when they may.

    The server dispatches as the handling agent and holds no visitor's session (BF-875's token is
    a federation peer's), so a call whose arguments name a visiting officer is refused rather than
    run unscoped. Every key and every string value counts, at any depth in objects and arrays,
    when the whole string is a visiting officer's DID or certificate UUID
    (``is_visiting_identity``); text that merely contains one is not an actor id. The walk is
    iterative, so nesting costs no stack. It counts an object's keys and values, or an array's
    items, from its length before it reads or queues any of them, so it reads, queues and looks up
    at most ``MAX_ARGUMENT_VALUES`` values (A4); a call holding more is refused rather than
    dispatched with values nobody read. A call that both holds more and names a visiting officer is
    refused for whichever the walk meets first; either way it is refused. With no identity registry
    no visiting certificate exists.
    """
    if identity_registry is None:
        return None
    pending: list[Any] = [arguments]
    counted = 1  # the arguments object itself
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            width = 2 * len(value)  # BF-903 (A4): a key and a value per entry, counted before either is read
        elif isinstance(value, list):
            width = len(value)
        elif is_visiting_identity(identity_registry, value):
            return REFUSED_VISITOR_UNBOUND
        else:
            continue
        counted += width
        if counted > MAX_ARGUMENT_VALUES:  # BF-903 (A4): refused before a container's children are read or queued
            return REFUSED_ARGUMENTS_UNWALKED
        if isinstance(value, dict):
            pending.extend(value.keys())
            pending.extend(value.values())
        else:
            pending.extend(value)
    return None


def bearer_token_matches(authorization: str, expected: str) -> bool:
```

SEARCH:
```python
        if not isinstance(tool_name, str) or not tool_name:  # BF-875: a name is a non-empty string
            return self._error_envelope(request_id, -32602, "name required")

        peer_id = (
```
REPLACE:
```python
        if not isinstance(tool_name, str) or not tool_name:  # BF-875: a name is a non-empty string
            return self._error_envelope(request_id, -32602, "name required")
        refusal = visitor_argument_refusal(arguments, getattr(self._runtime, "identity_registry", None))
        if refusal is not None:  # BF-903 (#1581): checked before either dispatch branch
            logger.warning(
                "BF-903: refused MCP tools/call %r from session %r: %s",
                str(tool_name)[:80], str(session_id)[:80], refusal,
            )
            self._emit_failed("tools/call", reason=refusal, detail=str(tool_name))
            return self._error_envelope(
                request_id, -32602, _VISITOR_REFUSALS[refusal].format(name=str(tool_name)[:80])
            )

        peer_id = (
```

### 7.17 `tests/test_bf804_pairing_notification.py` (M3: two controls pinned a paired sender's LLM turn)

SEARCH:
```python
from probos.channels.base import (
    _PAIRING_NOTICE_FAILED,
    ChannelMessage,
    PairingNotificationError,
)
```
REPLACE:
```python
from probos.channels.base import (
    _PAIRED_NO_CONVERSATION,
    _PAIRING_NOTICE_FAILED,
    ChannelMessage,
    PairingNotificationError,
)
```

SEARCH:
```python
    * carol is PAIRED -> processed, answered, UID flagged.
```
REPLACE:
```python
    * carol is PAIRED -> answered (BF-903: with the refusal of natural
      language a paired visitor gets), UID flagged.
```

SEARCH:
```python
    assert len(runtime.processed) == 1 and "status" in runtime.processed[0], (
        "control: the paired sender was processed past the gate"
    )
```
REPLACE:
```python
    # BF-903 (#1581): a paired sender is a visiting officer and no declared
    # capability grants a natural-language turn, so carol's answer is the
    # refusal, not an LLM reply. Her answer and her acknowledged UID remain
    # the control that the probe sees a paired sender settle.
    assert runtime.processed == [], (
        "control: a paired sender's natural language is refused before any LLM turn"
    )
    assert [text for _, text, _ in notifier.answers()] == [_PAIRED_NO_CONVERSATION], (
        "control: the paired sender was answered past the gate"
    )
```

SEARCH:
```python
        paired = SlackAdapter(_PairedRuntime(_Paired()), cfg, client=client)
        answered = await paired.receive(text="hi", channel_id="C1", user_id="U42")
        assert answered == "acknowledged, Captain", (
```
REPLACE:
```python
        paired = SlackAdapter(_PairedRuntime(_Paired()), cfg, client=client)
        answered = await paired.receive(text="hi", channel_id="C1", user_id="U42")
        # BF-903 (#1581): a paired sender's natural language is refused with a
        # reply naming the reason -- still a non-empty answer from receive(),
        # which is all this control needs.
        assert answered == _PAIRED_NO_CONVERSATION, (
```

### 7.18 `tests/test_ad807_discord_refresh.py` (M3: the control pinned a paired sender's LLM turn)

SEARCH:
```python
    above is a real refusal, not a blind spot.
    """
    service = _FakePairingService()
    service.resolved[("discord", "42")] = "did:probos:ro"
    runtime = _OnMessageRuntime(
```
REPLACE:
```python
    above is a real refusal, not a blind spot.

    BF-903 (#1581): this control used a paired sender, but a paired sender is
    a visiting officer and its natural language is now refused before any LLM
    turn, so it can no longer reach the failing turn. With no pairing service
    the gate passes the sender through to processing, the path this control
    needs.
    """
    service = None  # BF-903: no pairing service, so the gate passes the sender through
    runtime = _OnMessageRuntime(
```

### 7.19 New file: `tests/test_bf903_channel_and_mcp.py` (M3)

```python
"""BF-903 (#1581) M3: a paired channel sender and an inbound MCP call are scoped like any visiting officer.

Real objects: a real ``AgentIdentityRegistry`` in ``tmp_path``, the real ``VisitingOfficerRegistry`` with an
injected clock, the real ``PairingRegistry`` and ``PairingService``, a real ``CallsignRegistry`` loaded from a
profile in ``tmp_path``, a ``ChannelAdapter`` subclass whose only code is the platform I/O, the real
``SlackAdapter``, and the real ``FederationMCPServer`` driven through ``build_mcp_app`` over an in-process ASGI
transport with a real ``IntentBus`` and ``MCPAppRegistry``. The trust network behind ``FederationPeerRegistry`` is
BF-875's double; it is not under test. Nothing reads the live data directory.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from sqlite3 import OperationalError as _OperationalError  # the standard library's, not a ProbOS name
from typing import Any

import pytest
from httpx import ASGITransport as _ASGITransport  # httpx's names, not ProbOS's
from httpx import AsyncClient as _AsyncClient
from httpx import MockTransport as _MockTransport
from httpx import Response as _Response

from probos.channels.base import (
    _PAIRED_DM_REFUSED,
    _PAIRED_NO_COMMANDS,
    _PAIRED_NO_CONVERSATION,
    _PAIRING_LOOKUP_FAILED,
    ChannelAdapter,
    ChannelConfig,
    ChannelMessage,
    PairingLookupError,
    PairingNotificationError,
)
from probos.channels.slack_adapter import SlackAdapter
from probos.config import FederationMCPServerConfig, SlackConfig
from probos.crew_profile import CallsignRegistry
from probos.events import EventType
from probos.federation.mcp_server import (
    _VISITOR_REFUSALS,
    MAX_ARGUMENT_VALUES,
    REFUSED_ARGUMENTS_UNWALKED,
    REFUSED_VISITOR_UNBOUND,
    FederationMCPServer,
    build_mcp_app,
    visitor_argument_refusal,
)
from probos.federation.peer import FederationPeerRegistry
from probos.identity import AgentIdentityRegistry
from probos.mcp_apps.registry import MCPAppRegistry
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.security.pairing import PairingRegistry, PairingService
from probos.types import IntentDescriptor, IntentMessage, IntentResult
from probos.visiting_officers import (
    CAP_DM_RECEIVE,
    CAP_DM_SEND,
    REFUSED_CAPABILITY,
    REFUSED_EXPIRED,
    REFUSED_REGISTRY_OFF,
)
from tests.test_bf903_visitor_scope import (
    CREW_SLOT,
    INSTANCE_ID,
    VESSEL_NAME,
    Events,
    _Clock,
    _crew,
    _officers,
    _refusals,
)

CHANNEL = "bf903chan"
SESSION_TTL = 60.0
DM_TEXT = "@Counselor are you free?"
STATUS_TEXT = "what is the ship's status?"
ECHO_INTENT = "bf903_echo"
MOVE_TOOL = "bf903-move"
TOKEN = "bf903" * 8  # synthetic: 40 visible characters
CSP = "default-src 'self'"


@pytest.fixture
async def identities(tmp_path: Path) -> AsyncIterator[AgentIdentityRegistry]:
    registry = AgentIdentityRegistry(data_dir=tmp_path / "identity")
    try:
        await registry.start()
        await registry.start(instance_id=INSTANCE_ID, vessel_name=VESSEL_NAME, version="1")
        yield registry
    finally:
        await registry.stop()


# ---------------------------------------------------------------- channels


class _Runtime:
    """The runtime members ``handle_message`` and ``SlackAdapter.receive`` read, holding the real registries."""

    def __init__(
        self, pairing_service: Any, visiting_officers: Any, callsign_registry: CallsignRegistry, processed: list[str],
        intent_bus: IntentBus,
    ) -> None:
        self.pairing_service = pairing_service
        self.visiting_officers = visiting_officers
        self.callsign_registry = callsign_registry
        self.processed = processed
        self.intent_bus = intent_bus  # A4: the real bus, so a resolved DM reaches a live receiver

    async def process_natural_language(self, text: str, **kwargs: Any) -> dict[str, Any]:
        self.processed.append(text)
        return {"response": "all systems nominal"}

    def emit_event(self, event: Any, data: Any = None) -> None:
        return None


class _Adapter(ChannelAdapter):
    """A pairing adapter whose only code is the platform I/O; ``handle_message`` is the base class's."""

    channel_name = CHANNEL

    def __init__(self, runtime: Any) -> None:
        super().__init__(runtime, ChannelConfig(enabled=True))
        self.sent: list[tuple[str, str]] = []

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False

    async def send_response(self, channel_id: str, response: str, **kwargs: Any) -> None:
        self.sent.append((channel_id, response))


class _OptedOut(_Adapter):
    """An adapter with no ``channel_name``: the supported opt-out of pairing (``WebhookAdapter``)."""

    channel_name = ""


class _OnDuty:
    """The two members ``CallsignRegistry.resolve`` reads from a live agent (A4)."""

    def __init__(self, agent_id: str) -> None:
        self.id = agent_id
        self.is_alive = True


class _Roster:
    """The agent registry's one method ``resolve`` calls: the Counselor's pool holds one live agent (A4)."""

    def get_by_pool(self, agent_type: str) -> list[_OnDuty]:
        return [_OnDuty(CREW_SLOT)] if agent_type == "counselor" else []


class _Rig:
    """The real registries and pairing service behind one ``_Adapter``; the Counselor is on duty and receives its
    direct messages over a real ``IntentBus`` (A4)."""

    def __init__(self, identities: AgentIdentityRegistry, tmp_path: Path) -> None:
        self.clock = _Clock()
        self.events: Events = []
        self.processed: list[str] = []
        self.delivered: list[IntentMessage] = []
        self.officers = _officers(identities, self.clock, self.events)
        self.store = PairingRegistry(tmp_path / "pairings.db")
        self.pairing = PairingService(self.store, self.officers)
        profiles = tmp_path / "profiles"
        profiles.mkdir()
        (profiles / "counselor.yaml").write_text("callsign: Counselor\ndepartment: medical\n", encoding="utf-8")
        callsigns = CallsignRegistry()
        callsigns.load_from_profiles(str(profiles))
        callsigns.bind_registry(_Roster())
        bus = IntentBus(SignalManager())
        bus.subscribe(CREW_SLOT, self._receive, intent_names=["direct_message"])
        self.runtime = _Runtime(self.pairing, self.officers, callsigns, self.processed, bus)
        self.adapter = _Adapter(self.runtime)

    async def _receive(self, intent: IntentMessage) -> IntentResult:
        """The Counselor's direct-message handler: records what reached the crew member (A4)."""
        self.delivered.append(intent)
        return IntentResult(intent_id=intent.id, agent_id=CREW_SLOT, success=True, result="aye", confidence=0.9)

    async def pair(self, user_id: str, capabilities: list[str] | None = None) -> str:
        """Pair ``user_id`` as the Captain would: a pending code, then approval."""
        code = await self.pairing.request_pairing(CHANNEL, user_id)
        paired = await self.pairing.approve_pairing(
            CHANNEL, code, capabilities_override=capabilities, session_ttl_seconds=SESSION_TTL,
        )
        return paired.did


@pytest.fixture
async def rig(identities: AgentIdentityRegistry, tmp_path: Path) -> _Rig:
    return _Rig(identities, tmp_path)


def _message(user_id: str, text: str) -> ChannelMessage:
    return ChannelMessage(text=text, channel_id="room-1", user_id=user_id)


@pytest.mark.parametrize(
    ("text", "reply"),
    [
        ("/status", _PAIRED_NO_COMMANDS),
        (STATUS_TEXT, _PAIRED_NO_CONVERSATION),
        ("@Nobody are you there?", _PAIRED_NO_CONVERSATION),
    ],
    ids=["slash-command", "natural-language", "unknown-callsign"],
)
async def test_a_paired_sender_is_refused_commands_and_conversation(rig: _Rig, text: str, reply: str) -> None:
    """P1: a paired sender is a visiting officer; no declared capability grants a slash command or a turn with the
    ship's computer, so each gets a reply naming the reason, and nothing runs."""
    did = await rig.pair("u-1")
    message = _message("u-1", text)
    assert await rig.adapter.handle_message(message) == reply
    assert message.paired_did == did
    assert rig.processed == []
    assert _refusals(rig.events) == []


async def test_a_paired_sender_holding_dm_send_reaches_the_crew_member(rig: _Rig) -> None:
    """P2: AD-802's default capabilities hold dm.send, which is enough for an @callsign direct message. The
    Counselor is on duty (A4), so the DM is delivered once, over the real bus, to its live agent, and its answer is
    the reply."""
    did = await rig.pair("u-2")
    session = rig.officers.get(did)
    assert session is not None and CAP_DM_SEND in session.capabilities
    assert await rig.adapter.handle_message(_message("u-2", DM_TEXT)) == "Counselor: aye"
    assert [(i.intent, i.target_agent_id) for i in rig.delivered] == [("direct_message", CREW_SLOT)]
    assert rig.processed == []
    assert _refusals(rig.events) == []


@pytest.mark.parametrize("lapse", ["capability-missing", "session-expired", "registry-off"])
async def test_a_paired_dm_without_a_live_dm_send_is_refused(rig: _Rig, lapse: str) -> None:
    """P3: the DM is checked against the sender's session at use: a session without dm.send, one that has expired
    (before any sweep) and a registry that is not attached each refuse it with the code; nothing reaches the crew."""
    expected = {
        "capability-missing": REFUSED_CAPABILITY, "session-expired": REFUSED_EXPIRED,
        "registry-off": REFUSED_REGISTRY_OFF,
    }
    await rig.pair("u-3", [CAP_DM_RECEIVE] if lapse == "capability-missing" else None)
    if lapse == "session-expired":
        rig.clock.now += SESSION_TTL
    elif lapse == "registry-off":
        rig.runtime.visiting_officers = None
    assert rig.runtime.callsign_registry.resolve("Counselor")["agent_id"] == CREW_SLOT  # A4: deliverable if allowed
    reply = await rig.adapter.handle_message(_message("u-3", DM_TEXT))
    assert reply == _PAIRED_DM_REFUSED.format(reason=expected[lapse])
    assert rig.delivered == []  # A4: nothing reached the crew member, before the check or after it
    assert rig.processed == []
    surfaces = [p["surface"] for p in _refusals(rig.events)]
    assert surfaces == ([] if lapse == "registry-off" else [f"channel.{CHANNEL}.dm"])


async def test_an_unreadable_pairing_store_refuses_the_message_and_its_callers_still_catch_it(
    rig: _Rig, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P4: when the pairing store cannot be read the message is refused, not admitted: PairingLookupError is a
    PairingNotificationError naming only the channel, with the cause chained, so the callers that catch the parent
    (here Slack's webhook, which returns "") still catch it. Nothing is processed and nothing is sent."""
    def _unreadable(_channel: str, _raw_id: str) -> None:
        raise _OperationalError("database is locked")

    monkeypatch.setattr(rig.store, "lookup_by_raw_id", _unreadable)
    message = _message("u-4", STATUS_TEXT)
    with pytest.raises(PairingLookupError) as refused:
        await rig.adapter.handle_message(message)
    assert isinstance(refused.value, PairingNotificationError)
    assert str(refused.value) == _PAIRING_LOOKUP_FAILED.format(channel=CHANNEL)
    assert isinstance(refused.value.__cause__, _OperationalError)
    assert message.paired_did is None
    assert rig.adapter.sent == []
    async with _AsyncClient(transport=_MockTransport(lambda _r: _Response(200, json={"ok": True}))) as client:
        slack = SlackAdapter(rig.runtime, SlackConfig(enabled=True, bot_token="xoxb-test"), client=client)
        assert await slack.receive(text="hi", channel_id="C1", user_id="U42") == ""
    assert rig.processed == []


@pytest.mark.parametrize("gate", ["no-pairing-service", "adapter-opted-out"])
async def test_a_sender_the_gate_does_not_pair_is_served_as_before(rig: _Rig, gate: str) -> None:
    """P5 golden: with no pairing service, or on an adapter that opts out of pairing, a sender is not paired and its
    natural language is processed exactly as before BF-903."""
    if gate == "no-pairing-service":
        rig.runtime.pairing_service = None
        adapter: _Adapter = rig.adapter
    else:
        adapter = _OptedOut(rig.runtime)
    message = _message("u-5", STATUS_TEXT)
    assert await adapter.handle_message(message) == "all systems nominal"
    assert message.paired_did is None
    assert rig.processed == [STATUS_TEXT]


# ---------------------------------------------------------------- MCP


class _Trust:
    """BF-875's trust-network double: the members ``FederationPeerRegistry`` calls. Not under test."""

    def create_with_prior(self, agent_id: str, alpha: float, beta: float) -> None:
        return None

    def record_outcome(
        self, agent_id: str, success: bool, weight: float = 1.0, intent_type: str = "",
        episode_id: str = "", verifier_id: str = "", source: str = "verification",
    ) -> float:
        return 0.5

    def get_score(self, agent_id: str) -> float:
        return 0.5


class _McpRuntime:
    """The runtime members the MCP server reads: the real bus, peer registry and app registry, and the identities."""

    def __init__(
        self, identities: AgentIdentityRegistry, apps: MCPAppRegistry, events: list[tuple[Any, dict[str, Any]]],
    ) -> None:
        self.identity_registry = identities
        self.intent_bus = IntentBus(SignalManager())
        self.federation_peer_registry = FederationPeerRegistry(trust_network=_Trust())
        self.mcp_app_registry = apps
        self.recorded = events

    def emit_event(self, event: Any, data: Any = None) -> None:
        self.recorded.append((event, dict(data or {})))


class _Mcp:
    """The real inbound MCP server with one exposed intent and one app tool, each recording what it is sent."""

    def __init__(self, identities: AgentIdentityRegistry) -> None:
        self.calls: list[dict[str, Any]] = []
        self.moves: list[dict[str, Any]] = []
        self.events: list[tuple[Any, dict[str, Any]]] = []
        apps = MCPAppRegistry(internal_default_csp=CSP, external_default_csp=CSP)
        apps.register_app_tool(name=MOVE_TOOL, description="", input_schema={}, ui_resource_uri="", handler=self._move)
        self.runtime = _McpRuntime(identities, apps, self.events)
        self.runtime.intent_bus.subscribe("bf903-echo", self._echo, intent_names=[ECHO_INTENT])
        echo = IntentDescriptor(name=ECHO_INTENT, params={"note": "any value"}, description="records its arguments")
        self.server = FederationMCPServer(
            runtime=self.runtime,
            config=FederationMCPServerConfig(auth_token=TOKEN, exposed_intents=[ECHO_INTENT]),
            collect_intent_descriptors_fn=lambda: [echo],
        )

    async def _move(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self.moves.append(arguments)
        return {"isError": False, "content": [{"type": "text", "text": "moved"}]}

    async def _echo(self, intent: IntentMessage) -> IntentResult:
        self.calls.append(dict(intent.params))
        return IntentResult(intent_id=intent.id, agent_id="bf903-echo", success=True, result={"ok": True}, confidence=0.9)

    async def call(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """One authenticated tools/call through the app ``start()`` serves (door A)."""
        app = build_mcp_app(path="/mcp", auth_token=TOKEN, handle_jsonrpc=self.server.handle_jsonrpc)
        request = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}
        async with _AsyncClient(transport=_ASGITransport(app=app), base_url="http://mcp.test") as client:
            response = await client.post("/mcp", json=request, headers={"Authorization": f"Bearer {TOKEN}"})
        return response.json()

    def failures(self) -> list[dict[str, Any]]:
        return [data for event, data in self.events if event == EventType.MCP_BRIDGE_FAILED]


_NAMING: dict[str, tuple[str, Any]] = {
    "intent-did": (ECHO_INTENT, lambda did, uuid: {"note": did}),
    "intent-certificate-uuid": (ECHO_INTENT, lambda did, uuid: {"note": uuid}),
    "object-key": (ECHO_INTENT, lambda did, uuid: {"note": {did: "post"}}),
    "list-item": (ECHO_INTENT, lambda did, uuid: {"note": ["crew", uuid]}),
    "nested-value": (ECHO_INTENT, lambda did, uuid: {"note": {"on_behalf": {"of": [1, {"actor": did}]}}}),
    "deregistered-visitor": (ECHO_INTENT, lambda did, uuid: {"note": did}),
    "app-tool": (MOVE_TOOL, lambda did, uuid: {"player": did}),
}


@pytest.mark.parametrize("shape", list(_NAMING))
async def test_a_tools_call_naming_a_visitor_is_refused_before_either_branch(
    identities: AgentIdentityRegistry, shape: str,
) -> None:
    """Q1: a visiting officer's DID or certificate UUID anywhere in the arguments, as a value, a key or a list item,
    at any depth, refuses the call before the intent and app-tool branches; a deregistered visitor is still one."""
    mcp = _Mcp(identities)
    officers = _officers(identities, _Clock(), [])
    session = await officers.register("visitor", [CAP_DM_SEND])
    if shape == "deregistered-visitor":
        officers.deregister(session.did)
    tool, arguments = _NAMING[shape]
    reply = await mcp.call(tool, arguments(session.did, session.did.rsplit(":", 1)[1]))
    assert reply["error"] == {
        "code": -32602, "message": _VISITOR_REFUSALS[REFUSED_VISITOR_UNBOUND].format(name=tool),
    }
    assert (mcp.calls, mcp.moves) == ([], [])
    assert len(mcp.runtime.federation_peer_registry) == 0  # A4: the refusal registers no peer
    assert mcp.failures() == [
        {"side": "server", "method": "tools/call", "reason": REFUSED_VISITOR_UNBOUND, "detail": tool},
    ]


@pytest.mark.parametrize("shape", ["crew-did", "crew-certificate-uuid", "slot-id", "prose-with-a-visitor-did"])
async def test_crew_ids_and_prose_that_mentions_a_visitor_are_dispatched(
    identities: AgentIdentityRegistry, shape: str,
) -> None:
    """Q2: only a whole value that is a visiting officer's id refuses; a crew DID or certificate UUID (looked up, not
    a visitor), a slot id (never looked up) and prose that mentions a visitor's DID are dispatched."""
    mcp = _Mcp(identities)
    session = await _officers(identities, _Clock(), []).register("visitor", [CAP_DM_SEND])
    crew = await _crew(identities)
    note = {
        "crew-did": crew.did, "crew-certificate-uuid": crew.agent_uuid, "slot-id": CREW_SLOT,
        "prose-with-a-visitor-did": f"ask {session.did} to stand by",
    }[shape]
    reply = await mcp.call(ECHO_INTENT, {"note": note})
    assert json.loads(reply["result"]["content"][0]["text"]) == {"ok": True}
    assert mcp.calls == [{"note": note}]
    assert len(mcp.runtime.federation_peer_registry) == 1  # A4: a dispatched call registers its peer, so Q1's zero is observable
    assert mcp.failures() == []


async def test_the_argument_walk_reads_up_to_its_bound_and_refuses_past_it(identities: AgentIdentityRegistry) -> None:
    """Q3: the walk counts the object, its key, the list and each item. At the bound the arguments pass; one value
    past it they are refused unread rather than dispatched with values nobody checked."""
    at_bound = {"items": list(range(MAX_ARGUMENT_VALUES - 3))}
    past_bound = {"items": list(range(MAX_ARGUMENT_VALUES - 2))}
    assert visitor_argument_refusal(at_bound, identities) is None
    assert visitor_argument_refusal(past_bound, identities) == REFUSED_ARGUMENTS_UNWALKED
    mcp = _Mcp(identities)
    reply = await mcp.call(ECHO_INTENT, past_bound)
    assert reply["error"] == {
        "code": -32602, "message": _VISITOR_REFUSALS[REFUSED_ARGUMENTS_UNWALKED].format(name=ECHO_INTENT),
    }
    assert mcp.calls == []
    assert [f["reason"] for f in mcp.failures()] == [REFUSED_ARGUMENTS_UNWALKED]


class _CountingList(list[int]):
    """A JSON array that counts the items read from it; ``list.extend`` iterates a list subclass through ``__iter__``."""

    def __init__(self, items: range) -> None:
        super().__init__(items)
        self.read = 0

    def __iter__(self) -> Any:
        for item in super().__iter__():
            self.read += 1
            yield item


async def test_the_argument_walk_counts_a_container_before_it_reads_one(identities: AgentIdentityRegistry) -> None:
    """Q4 (A4): the walk counts an array's items and an object's keys and values from their length before it reads
    them, so a container that takes the call past the bound is refused with none of its items read or queued; under
    the bound every item is read, which shows the counter sees the walk. Before A4 all 10,000 items were enumerated
    and queued before the refusal."""
    wide = _CountingList(range(MAX_ARGUMENT_VALUES))
    assert visitor_argument_refusal({"items": wide}, identities) == REFUSED_ARGUMENTS_UNWALKED
    assert wide.read == 0
    narrow = _CountingList(range(MAX_ARGUMENT_VALUES - 3))
    assert visitor_argument_refusal({"items": narrow}, identities) is None
    assert narrow.read == MAX_ARGUMENT_VALUES - 3
    wide_object = {f"k{i}": i for i in range(MAX_ARGUMENT_VALUES // 2)}
    assert visitor_argument_refusal(wide_object, identities) == REFUSED_ARGUMENTS_UNWALKED
```

## 8. Tracking (tracker pairs, in M2's commit; Amendment A1 updates both for M3)

**`PROGRESS.md`**, anchored on the title, the blank line and the bold lead of BF-904b's line 3:

SEARCH:
```markdown
# ProbOS Progress

**BF-904b (2026-10-22), closes #1585 -- the sealed-core observation can fire, a syntax error a repair fixed no longer blocks the commit, a build in review holds its files, and the visiting builder works from whole files.**
```
REPLACE:
```markdown
# ProbOS Progress

**BF-903 (2026-10-22), #1581, M1 and M2 of three -- a visiting officer's capabilities are checked where it acts, and the capability names have one owner.** AD-701 called its registry the enforcement seam, but nothing called `has_capability`. M1: `probos.visiting_officers` owns the four names AD-701 and AD-802 declared (`ward_room.post`, `ward_room.read`, `dm.send`, `dm.receive`); `register`, the pairing service, `probos pairing approve` and `visiting_officers.default_capabilities` refuse any other name before a certificate, a pending row or a consumed code. The registry gains `refusal` and `check`, which read expiry at use (`get` hides an expired session), and the module gains the one guard every path calls, `require_visitor_capability`: it recognises a visiting officer by its birth certificate's agent type and never looks up a crew member's, the Captain's or the system's id. M2: the Ward Room facade calls it at the eleven entries that act for an actor id (a write needs `dm.send` in a DM channel and `ward_room.post` elsewhere); finalize attaches the registry; the API answers a refusal with 403 and the reason. A refusal is a `VISITING_OFFICER_REFUSED` event through the registry's emitter and a warning. Both flags stay off. M3 (the channel adapters and the inbound MCP server) follows in the same PR. New: `tests/test_bf903_visitor_scope.py`, `tests/test_bf903_ward_room_scope.py`, `tests/test_bf903_seam_was_open.py`. Updated: `test_ad701_visiting_officers.py`, `test_ad802_pairing.py`. The contract is `prompts/bf-903-visitor-capability-seam.md`.

**BF-904b (2026-10-22), closes #1585 -- the sealed-core observation can fire, a syntax error a repair fixed no longer blocks the commit, a build in review holds its files, and the visiting builder works from whole files.**
```

**`DECISIONS.md`**, after BF-904b's entry, anchored on its *Reversal* bullet (line 559, unique), the blank line and the heading that follows:

SEARCH:
```markdown
- *Reversal.* Revert the three BF-904b commits. Nothing persisted changes; the observation stops firing, refusals and syntax share one list again, a build in review stops holding its files and the visiting builder is seeded with excerpts again.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```markdown
- *Reversal.* Revert the three BF-904b commits. Nothing persisted changes; the observation stops firing, refusals and syntax share one list again, a build in review stops holding its files and the visiting builder is seeded with excerpts again.

### BF-903 -- Visiting-officer capabilities are checked where the officer acts, and the names have one owner (2026-10-22, #1581)

- *Scope.* M1 and M2 of three, one gate and one PR; M3 (the channel adapters and the inbound MCP server) is Amendment A1. `visiting_officers.py`, `config_models/crew.py`, `security/pairing/service.py`, `__main__.py` (M1); `ward_room/service.py`, `startup/finalize.py`, `api.py` (M2); tests. Contract: `prompts/bf-903-visitor-capability-seam.md`.
- *D1 (premise).* No path carries a visitor's own identity into the Ward Room today: `runtime.pairing_service` is never assigned, so `paired_did` is never set, and nothing reads it; the MCP server dispatches as the handling agent. The HXI routes take actor ids from the request body, so a body naming a visiting DID reached the Ward Room unchecked.
- *D2 (where).* One guard, `require_visitor_capability`, in the registry's module, applied at every Ward Room facade entry that takes an actor id and, in M3, at the channel and MCP entries. A visitor is a did:probos agent DID whose certificate's agent type is `visiting`, read from the identity registry's cache; the certificate outlives the session. Crew ids return before any lookup or query. BF-907's resolver and AD-1346's `IdentityService` return None for a slotless visitor and cannot classify one. Rejected: guarding only the channel layer, recognising a visitor by registry membership (fails open at expiry), and by DID shape (real visiting DIDs have the crew shape).
- *D3 (names).* A closed set in code, chosen among by configuration and `--cap`. AD-701's "new caps via configuration" is narrowed: a capability without a checking path grants nothing, and that path is code. The names are defined in `config_models/crew.py`, which imports nothing from ProbOS, so the config validator needs no import; `probos.visiting_officers` re-exports them.
- *D4 (MCP, built in M3).* A tools/call whose arguments name a visiting DID is refused with a reason; the shared token stays BF-875's federation-peer credential. A per-visitor binding is AD-1342's, on the MCP authorization spec.
- *D5 (record).* `VISITING_OFFICER_REFUSED` through the registry's emitter and a warning (with the registry off, the warning alone); reason codes in AD-1316's syntax. No `EventType` member and no admission record (#1604 owns admission).
- *D7 (M3, coupled).* `_check_pairing` fails closed when the pairing store cannot be read. A paired sender's slash commands and natural language are refused: no declared capability grants them. The AD that wires pairing declares what a paired sender may do.
- *Disclosed effects.* An undeclared capability is refused at `register`, pairing, `probos pairing approve` and config parse; a `system.yaml` naming one no longer loads; a pending row minted before BF-903 with one is consumed and refused at approve. `get` hides an expired session. A visiting DID at a guarded entry is refused unless a live session holds the capability (always, with no registry attached); the API answers 403. Crew, Captain and system ids are unchanged.
- *Reversal.* Revert the BF-903 commits. Nothing persisted changes; the facade stops checking visitors and any capability string is accepted again.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

**After both edits:** run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`. Both outputs go in M2's commit. Verify with `--check` and `tests/test_ad1184_ad_ledger.py`, never by byte comparison.

**Docs-only commit after M3's code commit:** add a *Validation of record* bullet in BF-903's entry, before its *Reversal* line: the mutation campaign of record (base tree, the sha256 of each file in section 10 and of the new test files, and each row's first failing test). Add a matching closing section to this contract, then regenerate the ledger.

**`docs/development/roadmap.md`:** no row (`BF-903` count is 0; BF-904b added none).

## 8b. Tracking for M3 (tracker pairs, in M3's commit)

These apply to the text section 8's pairs produce. After them, regenerate the ledger in M3's commit as section 8 says, and verify with `--check` and `tests/test_ad1184_ad_ledger.py`. They also correct the contract's filename, which section 8's text gets wrong.

**`PROGRESS.md`**, the BF-903 line M2 wrote:

SEARCH:
```markdown
**BF-903 (2026-10-22), #1581, M1 and M2 of three -- a visiting officer's capabilities are checked where it acts, and the capability names have one owner.** AD-701 called its registry the enforcement seam, but nothing called `has_capability`. M1: `probos.visiting_officers` owns the four names AD-701 and AD-802 declared (`ward_room.post`, `ward_room.read`, `dm.send`, `dm.receive`); `register`, the pairing service, `probos pairing approve` and `visiting_officers.default_capabilities` refuse any other name before a certificate, a pending row or a consumed code. The registry gains `refusal` and `check`, which read expiry at use (`get` hides an expired session), and the module gains the one guard every path calls, `require_visitor_capability`: it recognises a visiting officer by its birth certificate's agent type and never looks up a crew member's, the Captain's or the system's id. M2: the Ward Room facade calls it at the eleven entries that act for an actor id (a write needs `dm.send` in a DM channel and `ward_room.post` elsewhere); finalize attaches the registry; the API answers a refusal with 403 and the reason. A refusal is a `VISITING_OFFICER_REFUSED` event through the registry's emitter and a warning. Both flags stay off. M3 (the channel adapters and the inbound MCP server) follows in the same PR. New: `tests/test_bf903_visitor_scope.py`, `tests/test_bf903_ward_room_scope.py`, `tests/test_bf903_seam_was_open.py`. Updated: `test_ad701_visiting_officers.py`, `test_ad802_pairing.py`. The contract is `prompts/bf-903-visitor-capability-seam.md`.
```
REPLACE:
```markdown
**BF-903 (2026-10-22), closes #1581 -- a visiting officer's capabilities are checked where it acts, and the capability names have one owner.** AD-701 called its registry the enforcement seam, but nothing called `has_capability`. M1: `config_models/crew.py` owns the four names AD-701 and AD-802 declared (`ward_room.post`, `ward_room.read`, `dm.send`, `dm.receive`), re-exported by `probos.visiting_officers`; `register`, the pairing service, `probos pairing approve` and `visiting_officers.default_capabilities` refuse any other name before a certificate, a pending row or a consumed code. The registry gains `capability_refusal` and `check`, which read expiry at use (`get` hides an expired session), and the module gains the one guard every path calls, `require_visitor_capability`: it recognises a visiting officer by its birth certificate's agent type, named by its DID or its bare certificate UUID, and never looks up a slot id, the Captain's or the system's id. M2: the Ward Room facade calls it at the eleven entries that act for an actor id (a write needs `dm.send` in a DM channel and `ward_room.post` elsewhere); finalize attaches the registry; the API answers a refusal with 403 and the reason. M3: a paired channel sender is a visiting officer, so its slash commands and natural language are refused with a reply naming the reason and an `@callsign` DM needs a live `dm.send`; a pairing store that cannot be read refuses the message (`PairingLookupError`) instead of letting it through; the inbound MCP server refuses a `tools/call` whose arguments name a visiting officer, before either dispatch branch. A refusal is a `VISITING_OFFICER_REFUSED` event through the registry's emitter and a warning (MCP: `MCP_BRIDGE_FAILED`, reason `visitor_unbound`). Both flags stay off. New: `tests/test_bf903_visitor_scope.py`, `tests/test_bf903_ward_room_scope.py`, `tests/test_bf903_seam_was_open.py`, `tests/test_bf903_channel_and_mcp.py`. Updated: `test_ad701_visiting_officers.py`, `test_ad802_pairing.py`, `test_bf804_pairing_notification.py`, `test_ad807_discord_refresh.py`. The contract is `prompts/bf-903-visiting-officer-capability-seam.md`.
```

**`DECISIONS.md`**, BF-903's entry as M2 wrote it:

SEARCH:
```markdown
- *Scope.* M1 and M2 of three, one gate and one PR; M3 (the channel adapters and the inbound MCP server) is Amendment A1. `visiting_officers.py`, `config_models/crew.py`, `security/pairing/service.py`, `__main__.py` (M1); `ward_room/service.py`, `startup/finalize.py`, `api.py` (M2); tests. Contract: `prompts/bf-903-visitor-capability-seam.md`.
```
REPLACE:
```markdown
- *Scope.* M1, M2 and M3, one gate and one PR. `visiting_officers.py`, `config_models/crew.py`, `security/pairing/service.py`, `__main__.py` (M1); `ward_room/service.py`, `startup/finalize.py`, `api.py` (M2); `visiting_officers.py` (recognition), `channels/base.py`, `federation/mcp_server.py` (M3, Amendment A1); tests. Contract: `prompts/bf-903-visiting-officer-capability-seam.md`.
```

SEARCH:
```markdown
- *D2 (where).* One guard, `require_visitor_capability`, in the registry's module, applied at every Ward Room facade entry that takes an actor id and, in M3, at the channel and MCP entries. A visitor is a did:probos agent DID whose certificate's agent type is `visiting`, read from the identity registry's cache; the certificate outlives the session. Crew ids return before any lookup or query. BF-907's resolver and AD-1346's `IdentityService` return None for a slotless visitor and cannot classify one. Rejected: guarding only the channel layer, recognising a visitor by registry membership (fails open at expiry), and by DID shape (real visiting DIDs have the crew shape).
```
REPLACE:
```markdown
- *D2 (where).* One guard, `require_visitor_capability`, in the registry's module, applied at every Ward Room facade entry that takes an actor id and, in M3, at the channel and MCP entries. A visitor is a certificate whose agent type is `visiting`, named by its did:probos agent DID or by its bare certificate UUID (the two key shapes BF-907 gives a sovereign identity; an author's Ward Room episode is stored under the id it posts as), read from the identity registry's cache; the certificate outlives the session. A slot id, "captain" and "system" match neither shape and return before any lookup or query; a crew certificate's DID or UUID costs one in-memory lookup. BF-907's resolver and AD-1346's `IdentityService` return None for a slotless visitor and cannot classify one. Rejected: guarding only the channel layer, recognising a visitor by registry membership (fails open at expiry), by DID shape (real visiting DIDs have the crew shape), and by the DID alone (a visitor's UUID would pass as an unknown id).
```

SEARCH:
```markdown
- *D4 (MCP, built in M3).* A tools/call whose arguments name a visiting DID is refused with a reason; the shared token stays BF-875's federation-peer credential. A per-visitor binding is AD-1342's, on the MCP authorization spec.
```
REPLACE:
```markdown
- *D4 (MCP, built in M3).* A tools/call whose arguments name a visiting officer (any key or string value, at any depth, that is exactly its DID or certificate UUID) is refused with JSON-RPC -32602 and `MCP_BRIDGE_FAILED` reason `visitor_unbound`, before the app-tool and intent branches and through both doors; arguments of more than 10,000 values are refused unread (`arguments_unwalked`). The shared token stays BF-875's federation-peer credential. A per-visitor binding is AD-1342's, on the MCP authorization spec.
```

SEARCH:
```markdown
- *D7 (M3, coupled).* `_check_pairing` fails closed when the pairing store cannot be read. A paired sender's slash commands and natural language are refused: no declared capability grants them. The AD that wires pairing declares what a paired sender may do.
- *Disclosed effects.* An undeclared capability is refused at `register`, pairing, `probos pairing approve` and config parse; a `system.yaml` naming one no longer loads; a pending row minted before BF-903 with one is consumed and refused at approve. `get` hides an expired session. A visiting DID at a guarded entry is refused unless a live session holds the capability (always, with no registry attached); the API answers 403. Crew, Captain and system ids are unchanged.
- *Reversal.* Revert the BF-903 commits. Nothing persisted changes; the facade stops checking visitors and any capability string is accepted again.
```
REPLACE:
```markdown
- *D7 (M3, coupled).* `_check_pairing` fails closed when the pairing store cannot be read: it raises `PairingLookupError`, a `PairingNotificationError`, so every adapter's existing handling applies (Gmail leaves the mail unread and retries; the others drop it with a log; Teams answers 200). A paired sender's slash commands and natural language are refused with a reply naming the reason: no declared capability grants them. Its `@callsign` DM needs a live `dm.send`, checked against the paired DID's session directly, since pairing registered it as a visitor. The AD that wires pairing declares what more a paired sender may do.
- *Disclosed effects.* An undeclared capability is refused at `register`, pairing (a repeated request included), `probos pairing approve` and config parse; a `system.yaml` naming one no longer loads; an unexpired pending row minted before BF-903 with one is refused at approve before it is consumed and kept, so a declared `--cap` approves it, and an expired one is consumed and answers that it expired; the CLI prints a refused name as text. `get` hides an expired session. A visiting officer, named by its DID or its certificate UUID, is refused at a guarded entry unless a live session holds the capability (always, with no registry attached); the API answers 403, the assignment routes check every member before they write anything, and the teaching route lets the refusal through; a did:probos DID whose agent part is not a certificate UUID costs no lookup. A paired channel sender is refused slash commands and natural language, and an unreadable pairing store refuses the message; an MCP tools/call naming a visiting officer, or with more than 10,000 argument values, is refused, and a wide container is counted before it is read. Pairing is not wired and MCP is off in production, so no live sender is affected. Crew, Captain and system ids are unchanged; a crew certificate's UUID costs one in-memory lookup.
- *Reversal.* Revert the BF-903 commits. Nothing persisted changes; the facade stops checking visitors, any capability string is accepted again, a channel admits a sender whose pairing cannot be read and serves paired senders natural language again, and MCP dispatches whatever arguments it is sent.
```

## 9. What this does NOT change

- Both flags in `config/system.yaml`. AD-1342 and the visitor-to-crew path.
- AD-802's pairing flow apart from the name checks and, in approve, a read of the pending row before its consume (A3): `resolve_did`, `revoke_pairing`, `restore_active_sessions` (register R1), the CLI's offline issuer (R2, R5), `consume_pending` (R8) and the other pairing CLI output (R9).
- The adapter subclasses: each keeps its own handling of `PairingNotificationError`, which `PairingLookupError` inherits (section 5). `routers/teams_webhook.py`. The MCP server's bearer check, `tools/list`, `resources/read` and dispatch. The A2A server (register R4).
- What a paired sender's DM carries: it still reaches the crew member as `from: "channel"`, not as the visitor's DID (register R7).
- These Ward Room entries: `create_channel`, `unsubscribe`, `update_thread`, the reads with no actor id (`get_thread`, `list_threads`, `get_post`, `get_recent_activity`, `get_posts_by_author`), and the subject-id queries (`get_credibility`, `get_agent_comm_stats`, `count_posts_by_author`, `dm_receipt_facts`).
- `admission/`, `identity_service.py`, `identity.py` and `EventType`.
- The routers' acceptance of body-supplied actor ids (register R6).
- (A4) `AssignmentService`'s `except Exception` handlers, which still log a Ward Room failure and a refusal that arrives after the entry check (R11); `remove_member`, `complete_assignment` and `dissolve_assignment`. The shell's `procedure teach` (`commands_procedure.py:444-461`), which prints a refusal as "Teaching failed" and writes nothing (AV24).
- (A4) Recognition's exact-type check (`type(actor_id) is not str`): a `str` subclass is recorded, not changed (R10).

## 10. Mutation rows

There are 86 rows, as whole stripped lines, each occurring once in its file after section 7 (A1 corrected the count: the table held 50 before A1; A2 moved A1 and A2 to `config_models/crew.py`, rewrote A21 and added A33; A3 rewrote A25 and added A34-A36; A4 added A37, B24-B27 and C19-C22 and rewrote C11).

Tier HIGH: every changed production file has rows.
- Run A1-A37 against `tests/test_bf903_visitor_scope.py`, B1-B27 against `tests/test_bf903_ward_room_scope.py`, and C1-C22 against `tests/test_bf903_channel_and_mcp.py`.
- Start each group with an unmutated run of its file that passes.
- Restore the file after each row.
- "First failing" is in file order. Where another test fails first, run the named test alone against the mutant.

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| A1 | `src/probos/config_models/crew.py` | `VISITOR_CAPABILITIES: frozenset[str] = frozenset({CAP_WARD_ROOM_POST, CAP_WARD_ROOM_READ, CAP_DM_SEND, CAP_DM_RECEIVE})` | `VISITOR_CAPABILITIES: frozenset[str] = frozenset({CAP_WARD_ROOM_POST, CAP_WARD_ROOM_READ, CAP_DM_SEND})` | V1 (the re-export is the same object) |
| A2 | `src/probos/config_models/crew.py` | `return [c for c in dict.fromkeys(capabilities) if c not in VISITOR_CAPABILITIES]` | `return []` | V2 `[typo]` |
| A3 | `src/probos/visiting_officers.py` | `raise UnknownCapabilityError(unknown)` | `pass` | V2 `[typo]` |
| A4 | `src/probos/visiting_officers.py` | `require_known_capabilities(capabilities)  # BF-903 (#1581): refused before a certificate is issued` | `pass` | V2 `[typo]` |
| A5 | `src/probos/visiting_officers.py` | `if session is None or self._clock() >= session.expires_at:  # BF-903: an expired session is gone at use` | `if session is None:` | V6 (`get` after expiry) |
| A6 | `src/probos/visiting_officers.py` | `return REFUSED_NO_SESSION` | `return None` | V6 (deregistered) |
| A7 | `src/probos/visiting_officers.py` | `if self._clock() >= session.expires_at:` | `if False:` | V6 (`has_capability` after expiry) |
| A8 | `src/probos/visiting_officers.py` | `return REFUSED_EXPIRED` | `return None` | V6 |
| A9 | `src/probos/visiting_officers.py` | `if capability not in session.capabilities:` | `if False:` | V6 (missing) |
| A10 | `src/probos/visiting_officers.py` | `return self.capability_refusal(did, capability) is None` | `return True` | V6 (A5 renamed the method) |
| A11 | `src/probos/visiting_officers.py` | `"did": did, "capability": capability, "reason": reason, "surface": surface,` | `"did": did,` | V6 (event equality) |
| A12 | `src/probos/visiting_officers.py` | `raise VisitorScopeRefused(did, capability, reason, surface)` | `return` | V6 |
| A13 | `src/probos/visiting_officers.py` | `if parsed is None or parsed.get("type") != "agent":` | `if parsed is None:` | V7 (the ship DID raises `KeyError`) |
| A14 | `src/probos/visiting_officers.py` | `return cert if cert is not None and cert.agent_type == VISITING_AGENT_TYPE else None` | `return cert` | V7 (crew DID) |
| A15 | `src/probos/visiting_officers.py` | `if capability not in VISITOR_CAPABILITIES:` | `if False:` | V8 (undeclared) |
| A16 | `src/probos/visiting_officers.py` | `if cert is None:` | `if False:` | V8 (crew with no registry: `cert.did` on None) |
| A17 | `src/probos/visiting_officers.py` | `if visiting_officers is None:` | `if False:` | V8 (registry off) |
| A18 | `src/probos/visiting_officers.py` | `raise VisitorScopeRefused(did, capability, REFUSED_REGISTRY_OFF, surface)` | `return` | V8 |
| A19 | `src/probos/visiting_officers.py` | `visiting_officers.check(did, capability, surface=surface)` | `pass` | V8 (missing) |
| A20 | `src/probos/config_models/crew.py` | `return [CAP_WARD_ROOM_POST, CAP_WARD_ROOM_READ]` | `return [CAP_WARD_ROOM_POST]` | V1 |
| A21 | `src/probos/config_models/crew.py` | `unknown = undeclared_capabilities(value)` | `unknown = []` | V3 |
| A22 | `src/probos/security/pairing/service.py` | `DEFAULT_CAPABILITIES = (CAP_DM_SEND, CAP_DM_RECEIVE)  # BF-903: AD-802's defaults, named by the vocabulary's owner` | `DEFAULT_CAPABILITIES = (CAP_DM_SEND,)` | V1 |
| A23 | `src/probos/security/pairing/service.py` | `require_known_capabilities(caps)  # BF-903: refused before a pending row is minted` | `pass` | V4 |
| A24 | `src/probos/security/pairing/service.py` | `require_known_capabilities(capabilities_override)  # BF-903: refused before the code is consumed` | `pass` | V4 (the code-survives assertion) |
| A25 | `src/probos/security/pairing/service.py` | `require_known_capabilities(stored.capabilities or DEFAULT_CAPABILITIES)  # BF-903 (A3): a row minted before BF-903 may hold any string` | `pass` | V5 `[row-minted-before-bf903]`: the backstop then refuses after the consume, so the row is gone. A3 moved this row from the post-consume check, now a backstop with no row. |
| A26 | `src/probos/__main__.py` | `except (UnknownPairingCode, UnknownCapabilityError) as exc:  # BF-903: an undeclared --cap is refused with its name` | `except UnknownPairingCode as exc:` | V5 `[undeclared-cap-flag]` |
| A27 | `src/probos/visiting_officers.py` | `if type(actor_id) is not str or identity_registry is None:` | `if type(actor_id) is not str:` | V7 (`None` registry raises `AttributeError`) |
| A28 | `src/probos/visiting_officers.py` | `if not is_sovereign_identity_key(actor_id):` | `if False:` | V7 (a slot id is looked up) |
| A29 | `src/probos/visiting_officers.py` | `if actor_id.startswith("did:"):` | `if False:` | V7 (the visitor's DID is not recognised) |
| A30 | `src/probos/visiting_officers.py` | `return visiting_certificate(identity_registry, actor_id) is not None` | `return False` | V7 |
| A31 | `src/probos/visiting_officers.py` | `require_session_capability(cert.did, capability, surface=surface, visiting_officers=visiting_officers)` | `require_session_capability(actor_id, capability, surface=surface, visiting_officers=visiting_officers)` | V8 (the certificate UUID is served) |
| A32 | `src/probos/visiting_officers.py` | `require_known_capabilities((capability,))  # BF-903: a typo in a checking path fails on its first call` | `pass` | V8 (`require_session_capability` with an undeclared name) |
| A33 | `src/probos/visiting_officers.py` | `unknown = undeclared_capabilities(capabilities)` | `unknown = []` | V2 `[typo]` |
| A34 | `src/probos/security/pairing/service.py` | `stored = self._registry.get_pending(channel, code)  # BF-903 (A3): read, not consumed, so a refused row is kept` | `stored = None` | V5 `[row-minted-before-bf903]` (the backstop refuses after the consume; the kept-row assertion fails) |
| A35 | `src/probos/__main__.py` | `console.print(f"[red]Approve failed:[/red] {escape(str(exc))}", emoji=False)  # BF-903 (A3): a refused name prints as text` | `console.print(f"[red]Approve failed:[/red] {exc}")` | V5 `[markup-in-a-name]` (`MarkupError`) |
| A36 | `src/probos/visiting_officers.py` | `if not is_sovereign_identity_key(agent_uuid):  # BF-903 (A3): a malformed agent part costs no lookup` | `if False:` | V9 (the malformed DID is looked up) |
| A37 | `src/probos/security/pairing/service.py` | `if stored is not None and stored.expires_at >= self._clock():  # BF-903 (A4): an expired row goes on to the consume and answers "expired"` | `if stored is not None:` | V10 `[row-minted-before-bf903]` (refused by name and kept) |
| B1 | `src/probos/ward_room/service.py` | `_CHANNEL_TYPE_OF_CHANNEL = "SELECT channel_type FROM channels WHERE id = ?"` | `_CHANNEL_TYPE_OF_CHANNEL = "SELECT channel_type FROM channels WHERE id = ? AND 0"` | W3 `[thread-in-dm-channel]` |
| B2 | `src/probos/ward_room/service.py` | `_CHANNEL_TYPE_OF_THREAD = "SELECT c.channel_type FROM threads t JOIN channels c ON c.id = t.channel_id WHERE t.id = ?"` | `_CHANNEL_TYPE_OF_THREAD = "SELECT c.channel_type FROM threads t JOIN channels c ON c.id = t.channel_id WHERE t.id = ? AND 0"` | W3 `[post-in-dm-thread]` |
| B3 | `src/probos/ward_room/service.py` | `_CHANNEL_TYPE_OF_POST = "SELECT c.channel_type FROM posts p JOIN threads t ON t.id = p.thread_id JOIN channels c ON c.id = t.channel_id WHERE p.id = ?"` | `_CHANNEL_TYPE_OF_POST = "SELECT c.channel_type FROM posts p JOIN threads t ON t.id = p.thread_id JOIN channels c ON c.id = t.channel_id WHERE p.id = ? AND 0"` | W3 `[edit-in-dm-thread]` |
| B4 | `src/probos/ward_room/service.py` | `self._visiting_officers = registry` | `self._visiting_officers = None` | W1 `[create_thread]` (reason is registry off) |
| B5 | `src/probos/ward_room/service.py` | `surface=f"ward_room.{entry}",` | `surface=entry,` | W1 `[create_thread]` |
| B6 | `src/probos/ward_room/service.py` | `visiting_officers=self._visiting_officers,` | `visiting_officers=None,` | W1 `[create_thread]` |
| B7 | `src/probos/ward_room/service.py` | `channel_type = row[0] if row else ""` | `channel_type = ""` | W3 `[post-in-dm-thread]` |
| B8 | `src/probos/ward_room/service.py` | `capability = CAP_DM_SEND if channel_type == "dm" else CAP_WARD_ROOM_POST` | `capability = CAP_WARD_ROOM_POST` | W3 `[post-in-dm-thread]` |
| B9 | `src/probos/ward_room/service.py` | `self._require_visitor(agent_id or "", CAP_WARD_ROOM_READ, "list_channels")  # BF-903` | `pass` | W1 `[list_channels]` |
| B10 | `src/probos/ward_room/service.py` | `for participant in (agent_a_id, agent_b_id):  # BF-903: a visiting officer in a DM must be able to receive it` | `for participant in (agent_a_id,):` | W1 `[dm_channel_as_b]` |
| B11 | `src/probos/ward_room/service.py` | `self._require_visitor(participant, CAP_DM_RECEIVE, "get_or_create_dm_channel")` | `pass` | W1 `[dm_channel_as_a]` |
| B12 | `src/probos/ward_room/service.py` | `self._require_visitor(agent_id, CAP_WARD_ROOM_READ, "browse_threads")  # BF-903` | `pass` | W1 `[browse_threads]` |
| B13 | `src/probos/ward_room/service.py` | `await self._require_visitor_write(author_id, "create_thread", _CHANNEL_TYPE_OF_CHANNEL, channel_id)  # BF-903` | `pass` | W1 `[create_thread]` |
| B14 | `src/probos/ward_room/service.py` | `await self._require_visitor_write(author_id, "create_post", _CHANNEL_TYPE_OF_THREAD, thread_id)  # BF-903` | `pass` | W1 `[create_post]` |
| B15 | `src/probos/ward_room/service.py` | `await self._require_visitor_write(author_id, "edit_post", _CHANNEL_TYPE_OF_POST, post_id)  # BF-903` | `pass` | W1 `[edit_post]` (raises the author `ValueError` instead) |
| B16 | `src/probos/ward_room/service.py` | `self._require_visitor(voter_id, CAP_WARD_ROOM_POST, "endorse")  # BF-903` | `pass` | W1 `[endorse]` |
| B17 | `src/probos/ward_room/service.py` | `self._require_visitor(agent_id, CAP_WARD_ROOM_READ, "subscribe")  # BF-903` | `pass` | W1 `[subscribe]` |
| B18 | `src/probos/ward_room/service.py` | `self._require_visitor(agent_id, CAP_WARD_ROOM_READ, "update_last_seen")  # BF-903` | `pass` | W1 `[update_last_seen]` |
| B19 | `src/probos/ward_room/service.py` | `self._require_visitor(agent_id, CAP_WARD_ROOM_READ, "get_unread_counts")  # BF-903` | `pass` | W1 `[get_unread_counts]` |
| B20 | `src/probos/ward_room/service.py` | `self._require_visitor(agent_id, CAP_DM_RECEIVE, "get_unread_dms")  # BF-903` | `pass` | W1 `[get_unread_dms]` |
| B21 | `src/probos/startup/finalize.py` | `runtime.ward_room.attach_visiting_officers(runtime.visiting_officers)` | `pass` | W8 (reason is registry off) |
| B22 | `src/probos/api.py` | `@app.exception_handler(VisitorScopeRefused)` | `@app.exception_handler(LookupError)` | W7 (500) |
| B23 | `src/probos/api.py` | `"error": "visitor_scope_refused",` | `"error": "intent_denied",` | W7 |
| B24 | `src/probos/ward_room/service.py` | `self._require_visitor(agent_id, CAP_WARD_ROOM_READ, entry="subscribe")  # BF-903 (A4): subscribe's check, with no side effect` | `pass` | W9 (200: the subscribe refusal is swallowed) |
| B25 | `src/probos/assignment.py` | `self._ward_room.check_subscribe(agent_id)  # BF-903 (A4): every member is checked before the channel or any row exists` | `pass` | W9 (200: the assignment is written) |
| B26 | `src/probos/assignment.py` | `self._ward_room.check_subscribe(agent_id)  # BF-903 (A4): checked before the member row is written` | `pass` | W10 (200: the member row is written) |
| B27 | `src/probos/routers/procedures.py` | `except VisitorScopeRefused:  # BF-903 (A4): a scope refusal reaches the API's 403 handler, not this route's error string` | `except LookupError:` | W11 (200 with an error string) |
| C1 | `src/probos/channels/base.py` | `class PairingLookupError(PairingNotificationError):` | `class PairingLookupError(RuntimeError):` | P4 |
| C2 | `src/probos/channels/base.py` | `raise PairingLookupError(_PAIRING_LOOKUP_FAILED.format(channel=self.channel_name)) from exc` | `return True` | P4 |
| C3 | `src/probos/channels/base.py` | `if message.paired_did is not None:  # BF-903 (#1581): a paired sender is a visiting officer` | `if False:` | P1 `[slash-command]` |
| C4 | `src/probos/channels/base.py` | `if text.startswith("/"):  # BF-903: no declared capability grants a slash command` | `if False:` | P1 `[slash-command]` |
| C5 | `src/probos/channels/base.py` | `if mention is None or resolved is None:` | `if mention is None:` | P1 `[unknown-callsign]` |
| C6 | `src/probos/channels/base.py` | `did, CAP_DM_SEND, surface=f"channel.{self.channel_name}.dm",` | `did, CAP_DM_RECEIVE, surface=f"channel.{self.channel_name}.dm",` | P3 `[capability-missing]` |
| C7 | `src/probos/channels/base.py` | `visiting_officers=getattr(self.runtime, "visiting_officers", None),` | `visiting_officers=None,` | P2 |
| C8 | `src/probos/channels/base.py` | `except VisitorScopeRefused as refused:` | `except LookupError as refused:` | P3 `[capability-missing]` |
| C9 | `src/probos/channels/base.py` | `return _PAIRED_DM_REFUSED.format(reason=refused.reason)` | `return _PAIRED_DM_REFUSED.format(reason="")` | P3 `[capability-missing]` |
| C10 | `src/probos/federation/mcp_server.py` | `if identity_registry is None:` | `if True:` | Q1 `[intent-did]` |
| C11 | `src/probos/federation/mcp_server.py` | `if counted > MAX_ARGUMENT_VALUES:  # BF-903 (A4): refused before a container's children are read or queued` | `if False:` | Q3 |
| C12 | `src/probos/federation/mcp_server.py` | `return REFUSED_ARGUMENTS_UNWALKED` | `return None` | Q3 |
| C13 | `src/probos/federation/mcp_server.py` | `pending.extend(value.keys())` | `pass` | Q1 `[object-key]` |
| C14 | `src/probos/federation/mcp_server.py` | `pending.extend(value.values())` | `pass` | Q1 `[intent-did]` |
| C15 | `src/probos/federation/mcp_server.py` | `pending.extend(value)` | `pass` | Q1 `[list-item]` |
| C16 | `src/probos/federation/mcp_server.py` | `elif is_visiting_identity(identity_registry, value):` | `elif False:` | Q1 `[intent-did]` |
| C17 | `src/probos/federation/mcp_server.py` | `refusal = visitor_argument_refusal(arguments, getattr(self._runtime, "identity_registry", None))` | `refusal = None` | Q1 `[intent-did]` |
| C18 | `src/probos/federation/mcp_server.py` | `self._emit_failed("tools/call", reason=refusal, detail=str(tool_name))` | `pass` | Q1 `[intent-did]` (the event) |
| C19 | `src/probos/federation/mcp_server.py` | `width = 2 * len(value)  # BF-903 (A4): a key and a value per entry, counted before either is read` | `width = len(value)` | Q4 (the wide object is dispatched) |
| C20 | `src/probos/federation/mcp_server.py` | `width = len(value)` | `width = 0` | Q4 (the wide array is read and dispatched) |
| C21 | `src/probos/channels/base.py` | `require_session_capability(` | `await self._handle_callsign_resolved(resolved, mention[0], mention[1]) and require_session_capability(` | P3 `[capability-missing]` (one delivery before the refusal) |
| C22 | `src/probos/federation/mcp_server.py` | `if refusal is not None:  # BF-903 (#1581): checked before either dispatch branch` | `if refusal is not None and not await self._ensure_peer_registered(f"mcp-session:{session_id}"):` | Q1 `[intent-did]` (one peer registered before the refusal) |

**Lines without a row**
- `_require_visitor_write`'s `if not is_visiting_identity(...)`: equivalent, since removing it only adds a query for crew.
- `identity_registry=self._identity_registry,`: not unique in `service.py`; `start()` has two.
- `if self._db is not None:`: only the in-memory mode has no database.
- `agent_uuid = parsed["agent_uuid"]` and `agent_uuid = actor_id`: removing either breaks the same lookups A29 and A28 kill.
- `return _PAIRED_NO_COMMANDS` and `return _PAIRED_NO_CONVERSATION`: P1 asserts each reply by equality.
- `if refusal is not None:  # BF-903 (#1581): checked before either dispatch branch` is C22's line; its `if False:` mutant is equivalent to C17.
- (A4) `counted += width`: removing it never refuses, which Q3 kills as it kills C11. `counted = 1  # the arguments object itself`: `counted = 0` moves the bound by one, which Q3 pins on both sides. `continue`: removing it sends a leaf to `counted += width` (`UnboundLocalError`, or a stale width that extends a string by its characters), and Q2 fails.
- `MAX_ARGUMENT_VALUES = 10_000`: Q3 pins both sides of the bound.
- The walk's `if identity_registry is None:` short-circuit with a mutant that removes it: only a runtime with no identity registry, which production never has (`runtime.py:1203`, `:2766`), would then refuse past the bound.
- `if unknown:` (in `visiting_officers.py` and in `crew.py`'s validator) and the validator's `raise ValueError(`: equivalent to A3 and A21.
- `if runtime.ward_room is not None:`: equivalent to B21.
- `status_code=403,`: not unique in `api.py`.
- A3: `require_known_capabilities(caps)  # BF-903: a row minted before BF-903 may hold any string` is a backstop. It matters only when a request re-mints the same code between approve's read and its consume, and that row holds declared names (AV19); `register` checks again on the runtime path. Equivalent to A25 otherwise.
- A3/A4: the pre-read's guard is A37. Dropping its `stored is not None and` makes an unknown code raise `AttributeError`, which `test_ad802_pairing.py:174` catches outside the campaign's file. `from rich.markup import escape`: removing it raises `NameError` at A35's line, the same kill. `from probos.visiting_officers import VisitorScopeRefused` in `routers/procedures.py`: removing it raises `NameError` at B27's line when the route fails, the same kill.
- A3: M1's `if not is_sovereign_identity_key(parsed["agent_uuid"]):` is replaced by 7.13 and is not in the final tree; A36 is its M3 form. The reorder in `request_pairing` is not a single-line mutant; V4's repeat fails on `bfc8c98a`.
- Log lines and docstrings.

## 11. Verified Against Codebase (2026-10-22, HEAD `0e122174`)

**How uniqueness was checked.** Each SEARCH's distinctive line was grepped without a `$` anchor and counted once, or read in a whole-file or whole-region read: `visiting_officers.py` (whole), `pairing/service.py` (whole), `test_ad701` (whole), `ward_room/service.py:1-454`, `__main__.py:1895-2030`, `finalize.py:4915-4974`, `api.py:120-190`, `crew.py:295-330`, `test_ad802:1-214`.

```
src/probos/visiting_officers.py   17-18 docstring | 31 from typing import Any, Callable | 37 VISITING_AGENT_TYPE
  55-64 class docstring | 105 async def register | 118-119 ttl check | 120 issue_birth_certificate
  140 / 154 / 191 _emit("VISITING_OFFICER_*") | 151 deregister pops | 162-163 get | 165-171 has_capability
  173-175 active | 197-205 _emit and its warning
src/probos/config_models/crew.py  10 field_validator import | 303 class VisitingOfficersConfig | 316-318 default_capabilities
src/probos/config.py              152 VisitingOfficersConfig re-export | 3916 visiting_officers field
src/probos/security/pairing/service.py  15-16 UnknownPairingCode,) | 27 DEFAULT_CAPABILITIES | 101-102 caps/code
  153-155 consume_pending | 162-165 caps | 171 register | 238-267 restore (re-mints a DID) | 269-283 resolve_did
src/probos/security/pairing/store.py    76-85 __init__(db_path, *, clock) | 101-109 mint_pending | 159 get_pending | 179 list_pending
src/probos/__main__.py            1908-1912 pairing import | 1952-1956 offline stub | 1974-1975 except | 2022 stub DID shape
src/probos/identity.py            92-100 generate_did | 120-149 parse_did | 773 get_by_uuid | 804-827 resolve_slot_id
  893-937 issue_birth_certificate (new uuid each call) | 587 cache load at start | 1004 resolve_or_issue
src/probos/identity_service.py    79-95 resolve -> None without a slot
src/probos/ward_room/service.py   14-15 imports | 27 logger | 30 class | 41 identity_registry | 60 _receipt_facts
  238-240 set_ontology | 246-247 list_channels | 258-262 dm channel | 340-345 browse | 362-368 create_thread
  405-409 create_post | 414-415 edit_post | 417-420 endorse | 425-426 subscribe | 431-432 update_last_seen
  434-435 get_unread_counts | 445-446 get_unread_dms
src/probos/ward_room/models.py    95-104 channels(id, channel_type) | 106-123 threads(id, channel_id) | 125-129 posts(id, thread_id)
src/probos/ward_room/messages.py  487 "Only the original author can edit" | 532-533 self-endorse | 561 "up"
src/probos/ward_room/channels.py  28 dm_channel_name 8-char prefix | 224-261 get_or_create_dm_channel
src/probos/startup/communication.py 465-471 WardRoomService(..., identity_registry=identity_registry)
src/probos/startup/finalize.py    4926-4970 AD-701 wiring; 4963 start(); vo_cfg reads 4930, 4960-4967
src/probos/runtime.py             1063 self.ward_room | 1974 emit_event(event: BaseEvent | str | EventType, ...)
src/probos/api.py                 22 IntentAuthorizationDenied import | 23 verify_ws_token | 165-181 BF-771 handler | 183 CORS
src/probos/routers/wardroom.py    20 prefix /api/wardroom | 276-290 create_thread (except ValueError) | 351-358 | 366-372 | 380-386 | 396
src/probos/api_models.py          211-217 CreateThreadRequest
src/probos/channels/base.py       37 paired_did | 159-175 _check_pairing (fail-open 164-170) | 238-269 handle_message
src/probos/federation/mcp_server.py 196-207 bearer check | 331 authenticated | 425-429 peer id | 435-455 app tools | 457-479 intents
src/probos/config_models/integrations.py 34-41 exposed_intents default []
src/probos/execution/authority.py 109 _REASON_CODE_RE | src/probos/admission/taxonomy.py 66-73 DEFERRED_CHECKS
src/probos/mesh/pre_intent_auth.py 65 IntentAuthorizationDenied(PermissionError)
config/system.yaml                297 mcp enabled: false | 933 visiting enabled: false | 936-938 default caps
pyproject.toml                    181 asyncio_mode = "auto"
tests/test_bf771_intent_authorization.py 515-538 mock-runtime create_app pattern
tests/test_ad1346_admission_service.py   92-100 identity registry fixture; 131-137 resolve_or_issue
tests/test_ad630_leadership_feedback.py  302/321/339 __new__ services call only get_agent_comm_stats (unguarded)

A1 (2026-10-22): production files at 0e122174; visiting_officers.py and the M1 test as M1 builds them (0d3042eb)
src/probos/routers/agents.py      3842 author_id=agent_id inside _thread_store.append_message (no ward_room call; anchor removed)
src/probos/visiting_officers.py   24-27 One guard docstring | 304-322 is_visiting_identity | 325-351 require_visitor_capability
src/probos/identity.py            152-163 is_sovereign_identity_key (_SOVEREIGN_UUID, lower-case hex) | 773-785 get_by_uuid | 804-827 resolve_slot_id
src/probos/substrate/identity.py  17-27 slot id {type}_{pool}_{index}_{hash8} | substrate/agent.py 42 default id uuid4().hex (no hyphens)
src/probos/ward_room/threads.py   564-578 author episode under resolve_sovereign_id_from_slot(author_id) | cognitive/episodic.py 472-483 returns the id when no slot
src/probos/startup/trust_identity.py 55-57 both key shapes are sovereign keys
src/probos/channels/base.py       32-37 paired_did comment | 40-62 notice text and PairingNotificationError | 104-219 _check_pairing (fail-open 162-170)
  221-281 handle_message (slash 246-249, mention 251-258, natural language 260-281) | 283-316 _handle_callsign_resolved ("not currently on duty" 289)
src/probos/channels/gmail_adapter.py 91 channel_name | 156-178 per-message try; an exception leaves the mail unread
src/probos/channels/slack_adapter.py 50 | 203-205 receive catches PairingNotificationError | 290-297 poll catches Exception
src/probos/channels/telegram_adapter.py 47 | 197-204 ; matrix_adapter.py 34 | 177-184 ; discord_adapter.py 62 | 321, 330 ; teams_adapter.py 40 | 141
src/probos/routers/teams_webhook.py 41-47 HTTP 200 {"status": "error", "message": str(exc)}
src/probos/channels/webhook_adapter.py no channel_name (base default "" at base.py:78)
src/probos/crew_profile.py        660-667 CallsignRegistry | 669-703 load_from_profiles | 709-732 resolve (agent_id None when unbound) | 851-863 extract_callsign_mention
src/probos/security/pairing/service.py (M1-built) 43-51 __init__ | 84-103 request_pairing | 137-189 approve_pairing | 274-288 resolve_did
src/probos/federation/mcp_server.py 25 types import | 39-41 constants | 81-86 _jsonrpc_error | 316-351 handle_jsonrpc | 372-407 tools/list, resources/read
  409-512 _handle_tools_call (arguments 417-421, name 422-423, app branch 435-455, intent branch 457-512) | 566-582 _emit_failed
src/probos/mcp_apps/registry.py   139-141 has_tool | 143-164 list_tools | 191-216 read_resource | 244-268 call_tool
src/probos/mesh/intent.py         40 IntentHandler | 457-464 subscribe | 1293-1302 broadcast
src/probos/types.py               58-68 IntentMessage (id) | 78-86 IntentResult | 961-971 IntentDescriptor
src/probos/config_models/integrations.py 17-56 FederationMCPServerConfig
src/probos/runtime.py             1203 identity_registry declared | finalize.py 4954, 4972 runtime.visiting_officers set
tests/test_bf875_mcp_inbound_auth.py 84-99 trust double | 115-116 subscribe | 150-152 ASGI client | 592-603 two doors
tests/test_bf804_pairing_notification.py 36-40 imports | 166 | 184-200 Gmail control | 421-434 Slack control
tests/test_ad807_discord_refresh.py 193-215 control | tests/test_bf803_gmail_ack.py 1122-1135 ChannelMessage fields
tests/test_layer_boundaries.py    152-165 a top-level probos module is importable from any layer

A2 (2026-10-22): production files at 0e122174; crew.py, visiting_officers.py and the M1 test as M1 builds them (c78264fa)
tests/test_ad1270e2g_crew_models.py 54 imports probos.config_models.crew | 680-690 no probos import at any depth in crew.py
tests/test_ad1270e2_config_models.py 295-306 the core module's narrower pin (no probos.config import), option B's form
src/probos/config_models/crew.py  1-5 "self-contained" docstring | 8-10 imports | 276 WardRoomConfig.enabled False | 303-335 as M1 builds them
src/probos/config_models/cognition.py 15 PROCEDURE_EVOLUTION_EPISODE_LIMIT | 179 its field bound ; cognitive/dreaming.py 47 imports it
src/probos/config_models/agentic.py 18 valid_github_repository | 901 its validator ; fault_issue_filings.py 14 imports it
src/probos/config_models/__init__.py 3-4 "Import from there" | 9-179 sibling imports only
src/probos/config.py              129 names imported from config_models.crew one by one (the facade gains no constant)
scripts/check_config_facade.py    1015-1041 the surface is the public names of probos.config
docs/development/architecture-baseline.yaml 12-17 ranks substrate, mesh, consensus, cognitive, experience only
scripts/check_architecture_principles.py 521-523, 586-605 layer-import needs both ends ranked
src/probos/cognitive/codebase_index.py 725-727 the config schema reads class definitions only
src/probos/ward_room/service.py   12 from probos.config import format_trust
src/probos/federation/mcp_server.py 20-26 module-level imports
src/probos/visiting_officers.py   42-57 imports and vocabulary | 95-102 require_known_capabilities | 300-316 _emit's warning, is_visiting_identity (M1-built)

A3 (2026-10-22): M1 as built (bfc8c98a); M3's visiting_officers.py and channels/base.py as built (0b961ac0). Uniqueness: each SEARCH was checked against the contract's grep counts (`def is_visiting_identity` 374, 1664, 1745; `from probos.identity import parse_did` 386, 1676; `request_pairing("telegram", "tg-1")` 862 only; `"ABCDEF"` 887-894 only) and against whole-file reads of service.py and M1's test file.
src/probos/security/pairing/service.py  98-100 idempotent return before the check at 103 | 155-169 approve (consume 157, stored names 169) | 243-272 restore_active_sessions (register at 260 mints a new DID) | 274-288 resolve_did returns the stored DID
src/probos/security/pairing/store.py    159-177 get_pending (one SELECT) | 206-220 consume_pending (get_pending, then DELETE on a second connection) | 222 sweep_expired_pending
src/probos/security/pairing/types.py    18, 35 capabilities: tuple[str, ...]
src/probos/__main__.py                  320, 1299 and 13 more: from rich.markup import escape at use | 1908-1913 pairing imports | 1953-1957 offline service | 1975-1976 refusal print | 1996-2029 _OfflinePairingVOStub (did:probos:visiting:<hex16>, no certificate)
src/probos/identity.py                  117 generate_agent_uuid = str(uuid.uuid4()) | 142-148 parse_did returns parts[3] unchecked | 154 _SOVEREIGN_UUID | 157-163 is_sovereign_identity_key
src/probos/visiting_officers.py         192 register checks names before issuing (M1) | 309-327 is_visiting_identity (M1-built) | 311-338 visiting_certificate, 346-367 require_session_capability (M3-built)
src/probos/channels/base.py             198 pairing_service read by getattr | 220-223 request_pairing with the defaults | 343-365 a paired DM checks the session by DID (M3)
tests/test_ad802_pairing.py             62-84 real PairingRegistry fixture | 174 unknown code
tests/test_bf903_visitor_scope.py       136-155 V4 | 158-179 V5 (179 pinned the consumed row) | 214 V7 | 238 V8 (M1-built)
```

A4 (2026-10-22), on scratch `58900dee` (M1', M2' and M3' as `47acc253` holds them; contract blob `3aa9bfe8`). Uniqueness: each A4 SEARCH was grepped in the contract (`stored is not None` 571 only as a code line; `assert retried == 0` 926; `"subscribe")  # BF-903` 1214 and row B17; `runtime.add_event_listener = MagicMock()` 1614; `assert response.status_code == 403, response.text` 1626; `MAX_ARGUMENT_VALUES = 10_000  # BF-903` 2206; `read = 0` 2236; `The real registries and pairing service behind one` 2515; `self.runtime = _Runtime(` 2529; `handle_message(_message("u-3"` 2594; `(mcp.calls, mcp.moves)` 2740; `mcp.calls == [{"note": note}]` 2761; `== [REFUSED_ARGUMENTS_UNWALKED]` 2778) and read in the whole-file or whole-region reads below.

```
src/probos/security/pairing/service.py  98-102 request_pairing (live is `>`) | 155-160 A3 pre-read | 161-163 consume | 165 expiry `<` | 173 backstop
src/probos/security/pairing/store.py    76-85 __init__(db_path, *, clock=time.time) | 101-137 mint_pending (expires = clock() + ttl) | 159-177 get_pending (no expiry filter) | 206-220 consume_pending | 222-231 sweep `expires_at < now`
src/probos/__main__.py                  1955-1958 the CLI's service (default clock) | 1976-1978 refusal print | 1979-1983 approve output
src/probos/assignment.py                79-96 __init__(ward_room) | 146-241 create_assignment (channel try 181-203, rows 216-231) | 303-351 add_member (INSERT 316-322, subscribe try 325-340)
src/probos/routers/assignments.py       26-40 create (except ValueError) | 53-64 members (except ValueError)
src/probos/api_models.py                512-522 CreateAssignmentRequest, ModifyMembersRequest
src/probos/routers/procedures.py        1-13 imports | 148-215 teach_procedure (except Exception 207-208)
src/probos/config.py                    289 TEACHING_MIN_COMPILATION_LEVEL
src/probos/ward_room/service.py         257-285 attach, _require_visitor(actor_id, capability, entry), _require_visitor_write | 478-483 subscribe, unsubscribe
src/probos/ward_room/channels.py        129-147 list_channels(agent_id) filters by membership
src/probos/api.py                       184-197 VisitorScopeRefused handler | 376-394 data-directory model mounts (mkdir)
src/probos/runtime.py                   640 self._data_dir ; experience/commands/commands_wake_word.py 65 runtime.data_dir
src/probos/federation/mcp_server.py     43 MAX_ARGUMENT_VALUES | 58-86 visitor_argument_refusal | 469-478 refusal before peer_id 480 | 492, 528 _ensure_peer_registered | 591-601
src/probos/federation/peer.py           59-72 register_peer | 122-123 __len__
src/probos/channels/base.py             332-367 _handle_paired (check 359-365, the only require_session_capability( line 360) | 369-402 _handle_callsign_resolved (on duty 374-375, send 385, reply 402)
src/probos/crew_profile.py              705-707 bind_registry | 709-732 resolve (get_by_pool, is_alive, id)
src/probos/mesh/intent.py               457-474 subscribe | 1133-1197 send (local handler 1180-1194)
src/probos/dm_reply.py                  898-912 DmReply.from_intent_result (body = result.result) | 816-840 render (the body unchanged with no disclosure)
tests/test_bf903_visitor_scope.py       162-194 V5 | 197 V9
tests/test_bf903_ward_room_scope.py     84-111 rig | 114-116 _visitor | 282-303 _api_runtime | 306-319 W7
tests/test_bf903_channel_and_mcp.py     98-114 _Runtime | 142-166 _Rig | 198-226 P2, P3 | 287-300 _McpRuntime | 352-371 Q1 | 374-390 Q2 | 393-406 Q3
tests/test_assignment.py                25-48 real WardRoomService fixture | 263-292 membership read
tests/test_observational_routing.py     66-95 the teaching route's existing test (a MagicMock Ward Room)
```

## Absence Verified (2026-10-22)

```
AV1 CLAIM: no production caller of has_capability
    RUN:   rg -n 'has_capability\(' src
    FOUND: visiting_officers.py:10, :59, :63 (docstrings), :165 (def); federation/router.py:70, :91 (peer_has_capability)
    HOLDS: yes
AV2 CLAIM: runtime.pairing_service is never assigned
    RUN:   rg -n 'pairing_service' src
    FOUND: channels/base.py:131,134,159,160,163,178; discord_adapter.py:61; slack_adapter.py:49; __main__.py:1904
    HOLDS: yes (reads and comments only)
AV3 CLAIM: nothing reads paired_did
    RUN:   rg -n 'paired_did' src/probos
    FOUND: base.py:32,37 (field), :135 (docstring), :173 (write)
    HOLDS: yes
AV4 CLAIM: restore_active_sessions has no production caller
    RUN:   rg -n 'restore_active_sessions\(' src
    FOUND: security/pairing/service.py:238 (def)
    HOLDS: yes
AV5 CLAIM: VisitingOfficersConfig.default_capabilities is read by nothing
    RUN:   rg -n 'vo_cfg\.' src ; rg -n 'default_capabilities' src
    FOUND: finalize.py:4930,4960,4961,4966,4967 (enabled, ttl, sweep); crew.py:316 is the only visitor one
    HOLDS: yes
AV6 CLAIM: no BF-903 symbol or test file exists yet
    RUN:   rg -l 'VisitorScopeRefused|is_visiting_identity|require_visitor_capability|VISITOR_CAPABILITIES|attach_visiting_officers|UnknownCapabilityError|require_known_capabilities|CAP_WARD_ROOM|VISITING_OFFICER_REFUSED' ; glob tests/test_bf903*
    FOUND: none ; none
    HOLDS: yes
AV7 CLAIM: no visitor consumer in the Ward Room or the routers
    RUN:   rg -i 'visiting|visitor' src/probos/ward_room ; rg -i 'visiting_officer|visitor' src/probos/routers
    FOUND: 0 ; 0
    HOLDS: yes
AV8 CLAIM: only three existing tests drive a paired sender through handle_message
    RUN:   rg -n 'resolve_did|resolved\[|paired=' tests ; rg -n '_check_pairing\(|handle_message\(|receive\(|on_message\(' tests/test_ad80[3-7]*.py
    FOUND: paired fakes at test_ad803a_telegram.py:169, test_ad804_slack.py:174, test_ad806_matrix.py:169, test_ad807_discord_refresh.py:44
           call _check_pairing only (unchanged for a paired sender); test_ad807_discord_refresh.py:205 (on_message, 7.18);
           test_bf804_pairing_notification.py:184 (Gmail poll) and :421-430 (Slack receive) (7.17);
           test_channel_base.py:550, test_ad805_teams.py:29 and test_bf804:398 resolve None
    HOLDS: yes
AV9 CLAIM: no test pins the resolve_did fail-open
    RUN:   rg -n -i 'fail.open' tests
    FOUND: no hit in test_channel_base, test_bf803*, test_bf804*, test_ad764*, test_ad80[2-7]*; the hits are other subsystems
    HOLDS: yes
AV10 CLAIM: the MCP server reads no identity registry and no visitor today
    RUN:   rg -n 'identity_registry|is_visiting|visiting' src/probos/federation/mcp_server.py
    FOUND: 0
    HOLDS: yes
AV11 CLAIM: tools/list and resources/read take no actor id
    RUN:   read mcp_server.py:333-342, :372-407 ; mcp_apps/registry.py:143-164, :191-216
    FOUND: tools/list ignores its params; resources/read passes only uri, a resource key, to a lookup or an external read
    HOLDS: yes
AV12 CLAIM: no production code passes a bare certificate UUID as a Ward Room actor id today
    RUN:   rg -n '(author_id|agent_id|voter_id)\s*=\s*[^,)]*(sovereign|agent_uuid|\.did\b)' src/probos
    FOUND: experience/commands/commands_clearance.py:71, experience/commands/session.py:75, routers/memory_graph.py:213,
           cognitive/thought_store.py:108; none is a Ward Room call
    HOLDS: yes; a UUID reaches the Ward Room only as a body-supplied router id (R6) or an MCP argument
AV13 CLAIM: no adapter overrides _check_pairing; only Discord and Slack's receive name PairingNotificationError
    RUN:   rg -n 'def _check_pairing|def handle_message' src/probos/channels ; rg -n 'PairingNotificationError|handle_message\(' src/probos
    FOUND: base.py:104, :221 ; discord_adapter.py:20, :330 ; slack_adapter.py:37, :205 ; callers gmail:157, discord:321,
           matrix:178, slack:204, :291, teams:141, telegram:198, webhook:80
    HOLDS: yes
AV14 CLAIM: no layer rule forbids federation from importing probos.visiting_officers
    RUN:   read tests/test_layer_boundaries.py:137-165
    FOUND: a top-level module (parts[1] not in LAYER_MAP) returns None, always allowed (:165)
    HOLDS: yes
AV15 CLAIM: probos.config_models imports nothing outside itself once A2 removes crew.py's two imports, so
            visiting_officers -> config_models.crew cannot form a cycle
    RUN:   rg -n '^\s*(from|import) probos' src/probos/config_models
    FOUND: __init__.py:9,26,36,54,74,98,123,150,179 (siblings); crew.py:308,332 (probos.visiting_officers, removed by A2)
    HOLDS: yes
AV16 CLAIM: no test other than test_ad1270e2g_crew_models.py:680-690 pins the shape of an edited file in a way the contract breaks
    RUN:   rg -n '(visiting_officers|pairing.service|__main__|ward_room.service|finalize|api|channels.base|mcp_server|crew)\.py' tests ;
           rg -n 'getsource\((api_module|api|finalize|...)' tests ; rg -n 'signature\((VisitingOfficer|PairingService|WardRoomService|...)' tests ;
           rg -l 'rglob\("\*\.py' tests (45 files; read those that scan an edited file or a pattern the contract adds) ;
           rg -n 'setattr\([^)]*(VISITOR_CAPABILITIES|visiting_officers)|patch\([^)]*visiting_officers'
    FOUND: crew.py: test_ad1270e2g:680-690 (A2 satisfies it; :290 bound count, :434 ClassDef schema, EXPECTED_DUMPS unchanged).
           ward_room/service.py: test_ad615:58,68; test_bf164:47 (get_unread_dms keeps exchange_limit). __main__.py: test_bf781:376,
           test_ad1340_s1:325, test_bf207:301,309 (timeouts, EpisodicMemory calls). finalize.py: test_ad1130:1568, test_ad1198:583,
           test_bf753:121,155, test_bf875:611, test_bf876:765, test_counselor_therapeutic:559,569, test_bf106:86,
           test_ad1248_slice_a_gaps:231,387, test_ad1273:584, test_ad1278:792,1519, test_ad541d:530, test_bf745:597 (each pins
           other text). api.py: test_bf771:567 (presence), test_ad1203:526, test_self_mod:1044. Tree scans:
           test_ad1346_admission_service:504 (the string admission_service; no contract code holds it),
           test_ad1346_identity_service:475 (IdentityRef calls), test_ad680:110 (runtime private access),
           test_ad1195_eventlog_pair_freeze:331 (EventLog.log sites; the contract adds none). No signature pin; no patch of the vocabulary.
    HOLDS: yes, by reading; not run in A2's consult
AV17 CLAIM: runtime.pairing_service is still never assigned (AV2, re-run on 0b961ac0)
    RUN:   rg -n 'pairing_service\s*=[^=]' src ; rg -n "\"pairing_service\"|'pairing_service'" src
    FOUND: channels/base.py:198 (a local variable read through getattr), both searches
    HOLDS: yes
AV18 CLAIM: restore_active_sessions has no production caller (AV4, re-run on 0b961ac0)
    RUN:   rg -n 'restore_active_sessions\(' src
    FOUND: security/pairing/service.py:243 (def)
    HOLDS: yes
AV19 CLAIM: the only writer of pending rows is request_pairing, which refuses undeclared names before it mints
    RUN:   rg -n 'mint_pending\(' src
    FOUND: security/pairing/store.py:101 (def); security/pairing/service.py:106 (request_pairing)
    HOLDS: yes; a row minted between approve's read and its consume holds declared names
AV20 CLAIM: the CLI's offline stub is constructed only by _cmd_pairing
    RUN:   rg -n '_OfflinePairingVOStub\(' src
    FOUND: __main__.py:1953
    HOLDS: yes
AV21 CLAIM: nothing sweeps expired pending rows in production
    RUN:   rg -n 'sweep_expired_pending\(' src
    FOUND: security/pairing/store.py:222 (def)
    HOLDS: yes
AV22 CLAIM: no test drives approve_pairing through a store that lacks get_pending
    RUN:   rg -n 'approve_pairing\(|PairingService\(' tests
    FOUND: test_ad802_pairing.py:79, :218 (real PairingRegistry, :62-64); test_bf903_visitor_scope.py:144; test_bf903_channel_and_mcp.py:151;
           the rest are _FakePairingService doubles (test_ad803a, test_ad804, test_ad806, test_ad807, test_bf804), which never reach the service
    HOLDS: yes
```

A4 (2026-10-22), on `58900dee`:

```
AV23 CLAIM: the assignment service is reached only through the HTTP router, whose member ids come from the request body
     RUN:   Grep '\.(create_assignment|add_member|remove_member|complete_assignment)\(' src/probos
     FOUND: routers/assignments.py:31 (create, req.members), :59 (remove), :61 (add, req.agent_id), :72 (complete)
     HOLDS: yes; no shell command, startup path or agent calls them
AV24 CLAIM: of the teaching DM's three callers, only the HTTP route turned a scope refusal into success
     RUN:   Grep 'teach_procedure|/teach' src/probos ; read commands_procedure.py:444-461
     FOUND: routers/procedures.py:148-149 (the route); commands_procedure.py:62, :381 (prints "Teaching failed: ..." and writes nothing);
            cognitive/cognitive_agent.py:2813 (an agent's own action; log-and-degrade is the intended outcome)
     HOLDS: yes
AV25 CLAIM: no production code catches VisitorScopeRefused by name except the paired-DM reply; check_subscribe does not exist yet
     RUN:   Grep 'except VisitorScopeRefused|check_subscribe' src/probos
     FOUND: channels/base.py:364
     HOLDS: yes
AV26 CLAIM: no test enumerates WardRoomService's methods or names the guard outside the BF-903 files, and none pins assignment.py or routers/procedures.py
     RUN:   Grep 'getmembers\(WardRoomService|dir\(WardRoomService|vars\(WardRoomService|WardRoomService\.__dict__' tests ;
            Grep 'require_visitor|_require_visitor|check_subscribe|VisitorScopeRefused' tests (files) ;
            Grep 'assignment\.py|routers/procedures|procedures\.py|getsource\(.*(assignment|procedures)' tests
     FOUND: none ; test_bf903_visitor_scope.py, test_bf903_ward_room_scope.py ; cognitive/crew_assignment.py and cognitive/procedures.py only (other files)
     HOLDS: yes
AV27 CLAIM: every AssignmentService built with a Ward Room is given the real WardRoomService
     RUN:   Grep 'AssignmentService\(' (repository) ; Grep 'queue_pending_subscription|set_birth_chamber' tests
     FOUND: startup/communication.py:568; test_assignment.py:15 (no Ward Room), :40 (real WardRoomService); test_api_assignment.py:13 and
            test_database_hardening.py:34 (no Ward Room) ; test_ad486_birth_chamber.py:485-486 (the chamber alone)
     HOLDS: yes
AV28 CLAIM: the client-facing consumers that turned a facade refusal into success were the assignment service and the teaching route
     RUN:   the orchestrator's bf903_swallow_probe.py (AST over 1,057 files: every try around a guarded facade call on a ward|wr|room receiver whose
            handler catches Exception, BaseException, OSError or PermissionError, or is bare); not re-run in this consult; its output was read
     FOUND: 59 handlers, all swallowing; reachable with a body-supplied actor id: assignment.py:182, :326 (AV23) and routers/procedures.py:195;
            routers/recreation.py:109 and recreation/service.py:196 post as "captain"; the other 54 act as crew slots, "captain" or the system
     HOLDS: yes, within the filter: a facade held under a receiver name outside ward|wr|room is not listed
```

## 12. Deterministic gate checks, resolved up front

- **Precheck** (`scripts/phantom-api-precheck.ps1`):
  - `TestClient` and `Namespace` are imported under a leading underscore.
  - `JSONResponse` exists (`api.py:166`, `-> JSONResponse:`).
  - `MagicMock` and `Path` are stdlib-listed.
  - The new classes are defined in this contract.
  - Each `AssertionError(` message begins with "not".
  - The `runtime.X` names used (`ward_room`, `visiting_officers`, `identity_registry`, `start`, `stop`, `callsign_registry`, `registry`, `hebbian_router`, `ontology`) exist in `src`.
  - The SQL uses one-letter aliases only.
  - A1: `_AsyncClient`, `_ASGITransport`, `_MockTransport`, `_Response` (httpx's) and `_OperationalError` (sqlite3's) are imported under a leading underscore.
  - A1: `SlackAdapter`, `SlackConfig`, `ChannelConfig`, `CallsignRegistry`, `FederationMCPServer`, `FederationMCPServerConfig`, `FederationPeerRegistry`, `MCPAppRegistry`, `IntentBus`, `SignalManager`, `IntentDescriptor`, `IntentResult` and `PairingLookupError` are ProbOS classes; `EventType.MCP_BRIDGE_FAILED` exists (`mcp_server.py:571`).
  - A1: the test runtimes keep their recorders as their own attributes (`self.processed`, `self.events`) and the tests read them from the rig, so no `runtime.<name>` outside `src` appears.
  - A1: the only float parameter given a constant is `session_ttl_seconds=SESSION_TTL` (`60.0`); 7.18's SEARCH stops before the existing `RuntimeError(...)` line.
  - A3: `escape` is rich.markup's lower-case function, imported as `__main__.py` already does; V9's `AssertionError` message begins with "not"; V5 passes `ttl_seconds=600.0`.
  - A4: 7.11 imports httpx's `ASGITransport` and `AsyncClient` under a leading underscore; `AssignmentService` is a ProbOS class; `runtime._data_dir` (`runtime.py:640`), `runtime.data_dir` (`commands_wake_word.py:65`), `runtime.assignment_service` (`routers/assignments.py:28`), `runtime.procedure_store` (`routers/procedures.py:154`), `runtime.intent_bus` and `runtime.federation_peer_registry` exist in `src`; `check_subscribe` is defined by 7.8 and is a candidate until built; `_Chamber`, `_Procedure`, `_TeachingStore`, `_OnDuty`, `_Roster` and `_CountingList` are defined in the contract; the only float parameters given constants are `clock=lambda: 1000.0` and `ttl_seconds=600.0`.
- **Import cycle:** `visiting_officers.py` imports the standard library and, at load, `probos.config_models.crew` (A2), which loads the `probos.config_models` package; nothing in that package imports from outside it (AV15), so no cycle can pass through it. `config_models/crew.py` imports nothing from `probos` (`tests/test_ad1270e2g_crew_models.py:680-690`). `parse_did` and `is_sovereign_identity_key` are imported at call time.
- **CRLF:** match the working copy's line endings; never anchor a grep with `$`.
- **The deletion check** before each commit: `git diff --cached --stat`.

## 13. Not verified here, and prior art

- **Not run:** any test, the precheck or ruff.
- **Not confirmed:**
  - that Rich's 80-column wrap keeps `tool.use` intact in V5's output (it wraps at spaces);
  - that the BF-771 mock runtime serves `/api/wardroom` (the same app);
  - that W8's boot posts as a visitor without side effects beyond Ward Room routing to crew (proactive is off).
- **Prior art:**
  - **Adopted:** the MCP authorization spec (2026-07-28 revision: an MCP server is an OAuth 2.1 resource server with audience-bound tokens; Client ID Metadata Documents replace Dynamic Client Registration). This is the design AD-1342's binding should take; D4 defers it there instead of a bespoke per-visitor token.
  - **Absorbed:** BF-771's `PermissionError`-plus-app-handler pattern for policy refusals (`api.py:147-181`).
  - **Reference projects** (date used 2026-10-22): MCP Apps was overdue (2026-04-08, interval 180 days). Checked: it is now an official extension in the 2026-07-28 spec, with nothing for BF-903. Update the row to `2026-10-22 | checked | BF-903 (#1581) Prior Art`. AG-UI (never reviewed) was considered and deferred: it is a UI protocol and not relevant.
  - **Blind spots folded in:** the restore path's DID mismatch, the DM-name collision and the A2A inbound door (register).
- **A1, not run here:** any test, the precheck, ruff and the apply of A1's pairs. Not confirmed: that `IntentBus.broadcast` serves a plain coroutine subscriber with no pre-intent authorizer configured (BF-875's tests subscribe agent methods the same way, `test_bf875:115-116`); that `SlackAdapter.receive` reads only `pairing_service` and `emit_event` from its runtime before `handle_message` (BF-804's `_Runtime` holds only those, `test_bf804:390-395`).
- **A1 prior art:** none sought. The amendment is ProbOS-specific plumbing; the JSON-RPC code follows BF-875's refusal (`mcp_server.py:469-472`), and the reference projects were reviewed above on the same date.
- **A3, not run here:** any test, the precheck, ruff and the apply of A3's pairs. Not confirmed: that Rich's escape leaves `[/red]tool.use` printed literally at 80 columns (the name holds no space, so it does not wrap); that no M2 or M3 test uses a four-part DID with a non-UUID agent part as a visitor (the BF-903 tests use real certificates; `test_bf903_ward_room_scope.py:278` only raises the refusal). Prior art: none sought; the repair is ProbOS plumbing.
- **A4, not run here:** any test, the precheck, ruff, the swallow probe and the apply of A4's pairs. Not confirmed:
  - that `create_app` with `_api_runtime` writes nothing else under the working directory (W7's emptiness rests on the M2 reviewer's interception, which saw only the two model `mkdir` calls);
  - that the httpx ASGI client serves the assignment and teaching routes on the test's loop with the rig's aiosqlite connections (7.19 drives `build_mcp_app` the same way);
  - that a fresh `IntentBus` with no pre-intent hooks delivers `direct_message` to a coroutine subscriber (the M3 reviewer's probe did, with a real bus);
  - that the M2 reviewer's probes and the M3 reviewer's ordering mutant reproduce on these tests.

  Prior art: none sought. The repair is check-before-side-effect ordering in ProbOS plumbing; BF-771's per-recipient refusal was weighed and rejected (section 19).

## 14. Diff Reviewer: properties to verify

1. A crew, Captain or system id causes no certificate lookup and no database query at any guarded entry.
2. Each of the eleven facade methods calls the guard before it delegates, with the capability in ENTRIES. (A4) `check_subscribe` makes `subscribe`'s check, with the same capability and surface, and nothing else.
3. A visiting DID is refused when the registry is unattached, the session is missing, the session has expired (`clock >= expires_at`) or the capability is absent, each with the matching code.
4. `VisitorScopeRefused` is not a `ValueError`, so the routers' `except ValueError` cannot turn it into a 400; the app handler returns 403.
5. `register`, `request_pairing` (a repeat from a sender with a pending row included), an approve override, an unexpired pending row's stored names and config parse refuse an undeclared name before any certificate, row or consume; a refused approve leaves the pending row in place (A3). An expired pending row is consumed and answers "expired", whatever names it holds; the pre-read's guard is the complement of the post-consume check's `<` (A4).
6. `visiting_officers.py` imports at load only the standard library and `probos.config_models.crew`; `config_models/crew.py` imports nothing from `probos`, at any depth (A2).
7. `config/system.yaml` is unchanged; no `EventType` is added; `admission/` is untouched.
8. `has_capability` keeps its truth table (`test_ad701:180-193`).
9. A slot id, "captain" and "system" cause no certificate lookup; a did:probos agent DID whose agent part is a lower-case UUID, or a lower-case UUID, causes exactly one `get_by_uuid`, and any other DID causes none (A3); either form of a visiting certificate is checked and refused under its DID.
10. Once `paired_did` is set, `handle_message` runs no slash command and no `process_natural_language`; an `@callsign` DM reaches `_handle_callsign_resolved` only after `require_session_capability(..., CAP_DM_SEND, ...)` returns. (A4) P2 and P3 run with a bound agent and a real `IntentBus`: one delivery when served, none when refused.
11. A `resolve_did` failure raises `PairingLookupError` (a `PairingNotificationError`) whose text names the channel only; no message proceeds.
12. `_handle_tools_call` calls `visitor_argument_refusal` after validating `arguments` and `name` and before the app-tool and intent branches; a refusal dispatches nothing, registers no peer and emits one `MCP_BRIDGE_FAILED`.
13. The walk is iterative and counts a container's keys and values or items from its length before it reads or queues any of them, so it reads, queues and looks up at most `MAX_ARGUMENT_VALUES` values and refuses past that; 10,000 counted values dispatch and 10,001 refuse; when a call is both past the bound and names a visitor, the reason is the one the walk meets first (A4).
14. `federation/mcp_server.py` imports `probos.visiting_officers` at module level, which loads no ProbOS module outside `probos.config_models` (property 6).
15. (A3) `probos pairing approve` prints a refusal's names literally (no Rich markup or emoji code is interpreted) and returns 1.
16. (A4) An assignment create or member add that names a visiting officer without `ward_room.read` answers 403 with the envelope and writes nothing: no assignment row, member row, channel, subscription or deferred subscription; a visitor holding it joins and is subscribed; a crew-only request behaves as before.
17. (A4) `POST /api/procedures/teach` answers 403 for a refused target and opens no channel; its other failures keep their 200 answer.
18. (A4) No `src/` path other than the assignment service and the teaching route turns a facade refusal into a client-visible success (AV23, AV24, AV28).

## 15. Acceptance criteria

- Sections 7.1-7.19, with 7.12b and 7.12c (A4), are applied (7.13 and 7.14 on the text 7.1 and 7.7 build), all of sections 6 and 10 pass and are killed, and the focused gates in section 4 are green.
- The tracker pairs and the ledger are regenerated and pass `--check`.
- One broad gate after M3, with a receipt.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Amendment A1 (2026-10-22): M3, recognition by either key form, and three corrections

**Amended by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-22, on the orchestrator's dry run of `5efd1acf` (scratch state `0d3042eb`).

- **M3** is sections 7.13-7.19 and 8b: `channels/base.py` (7.15), `federation/mcp_server.py` (7.16), the new `tests/test_bf903_channel_and_mcp.py` (7.19) and the pinned-test updates (7.17, 7.18). Of the pinned files section 16 named, only `test_bf804_pairing_notification.py` and `test_ad807_discord_refresh.py` drive a paired sender past the gate (AV8); no test pins the fail-open (AV9). M3 closes #1581.
- **Recognition (option B).** A visiting officer is recognised by its DID or by its bare certificate UUID, the two key shapes BF-907 gives a sovereign identity (`identity.py:152-163`). A DID-only guard let a visitor's UUID pass as an unknown id at every facade entry and in every MCP argument, and the Ward Room stores an author's episode under the id it posts as (`ward_room/threads.py:564-578`). 7.13 changes M1's functions on M1's text (`visiting_certificate`, `require_session_capability`); 7.14 widens V7 and V8. Slot ids, "captain" and "system" match neither shape and still cost no lookup; a crew certificate's UUID costs one in-memory lookup. Rejected: (A) DID only, which leaves the alias; (C) resolving ids through `resolve_slot_id` or `IdentityService.resolve`, which return None for a slotless visitor; (D) callsigns, which are not actor ids at the facade.
- **Corrections.** Section 0 cited `routers/agents.py:3842`, a thread-store write (`author_id=agent_id` inside `_thread_store.append_message`), not a Ward Room call; removed. Section 10 said 51 rows and held 50; it now holds 73. Section 8's tracker text names the contract `prompts/bf-903-visitor-capability-seam.md`; the file is `prompts/bf-903-visiting-officer-capability-seam.md`, and 8b rewrites both entries with that name.
- **Envelope.** M3 strengthens two controls (a paired sender gets only what a declared capability grants; an unreadable pairing store refuses instead of admitting) on paths no production sender reaches: `runtime.pairing_service` is never assigned (AV2) and the MCP server is off (`config/system.yaml:297`) with no exposed intents by default. No "Still requires the Captain" condition applies; D7 records that the Captain may overrule.

## 17. Amendment A2 (2026-10-22): the vocabulary moves to the config leaf, and W8 enables the Ward Room

**Amended by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-22, on the M1 Builder's hard stop (a) and the orchestrator's dry run of `8862dccf`.

- **Defect 1.** `tests/test_ad1270e2g_crew_models.py:680-690` walks all of `config_models/crew.py` and refuses a `probos` import at any depth; 7.2's two function-level imports of `probos.visiting_officers` failed it. `check_architecture_principles.py` cannot see that edge: neither `config_models` nor `visiting_officers` is a ranked layer (`architecture-baseline.yaml:12-17`), so the test is its only guard.
- **Decision (option A).** `config_models/crew.py` defines the four names, `VISITOR_CAPABILITIES` and the one membership test `undeclared_capabilities`; `probos.visiting_officers` imports and re-exports them, so every `from probos.visiting_officers import CAP_...` in M2, M3 and the tests is unchanged. Precedent: AD-1326's bound (`config_models/cognition.py:15`, read by `cognitive/dreaming.py:47`) and `valid_github_repository` (`config_models/agentic.py:18`, used by its validator at `:901` and by `fault_issue_filings.py:14`). `UnknownCapabilityError` and `require_known_capabilities` stay in `visiting_officers.py`; the validator raises a `ValueError` with the same text, since pydantic wraps either as a validation error. Rejected: (B) relaxing the pin to the core module's form (`test_ad1270e2_config_models.py:295-306`), which leaves a config model depending on a runtime module against `crew.py`'s "self-contained" docstring; (C) dropping the validator, which loses refusal at parse because nothing reads the list (AV5), or moving it to the facade, which needs the same inverted import; (D) two copies pinned equal, two owners.
- **Load and cycles.** `visiting_officers.py` now loads `probos.config_models`, whose modules import nothing from outside the package (AV15), so no cycle can pass through it. `api.py` and `ward_room/service.py` already loaded it through `probos.config`; `security/pairing/service.py` and (M3) `federation/mcp_server.py` now load it through `visiting_officers`. Section 12 and properties 6 and 14 say so, and the `parse_did` comments in 7.1 and 7.13 no longer claim the module loads no other ProbOS module.
- **Defect 2.** W8 booted with `WardRoomConfig.enabled` at its default `False` (`config_models/crew.py:276`), so `runtime.ward_room` was None. 7.11 enables it; the orchestrator ran the repaired test on `e87f7009` (passes). No mutation row: B21 already removes the attach W8 proves, and the repair makes B21's kill real. A mutant that loses the Ward Room is boot configuration, not BF-903's surface.
- **Rows.** A1 and A2 move to `crew.py`; A21 is the validator's call to the shared test; A33 is `require_known_capabilities`'s. 74 rows.
- **Other shape pins.** None found beyond defect 1 (AV16). M1's focused gate gains `tests/test_ad1270e2g_crew_models.py`.
- **Trackers.** Section 8's D3 bullet and 8b's final PROGRESS line name the owner. Section 8's interim PROGRESS line, which 8b replaces in M3's commit of the same PR, is left as is so 8b's SEARCH keeps matching.
- **A1 anchors.** 7.13's second SEARCH changes only in its `parse_did` comment, the edit 7.1 receives; 7.13's first SEARCH, 7.14's SEARCH blocks (A2 edits the head of the test's import block and V1 only), 7.17-7.19 and 8b's SEARCH blocks are unchanged.
- **Not run in this consult:** any test, the precheck, ruff and the apply of A2's pairs.
- **Envelope.** A2 moves where four constants are defined and keeps every check; no "Still requires the Captain" condition applies.

## 18. Amendment A3 (2026-10-22): the M1 review, round 1

**Amended by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-22, on `gpt-6.1-sol`'s NOT READY review of `bfc8c98a` (six findings, all executed).

- **Finding 1 (P2, regression): fixed.** With no override, approve reads the row with `get_pending` (`store.py:159`, a SELECT), checks its names, then consumes it. A row minted before BF-903 with an undeclared name is refused and kept. A declared `--cap` approves it, since an override replaces the stored names. The post-consume check stays as a backstop with no row. Rejected: a check-and-delete store method (new API for a row no supported writer makes, AV19); refusing and deleting (the defect). If a concurrent approve consumes between the read and the consume, this one gets `UnknownPairingCode`. Two approvals that both pass `consume_pending`'s read-then-delete (two connections) are older than BF-903 and recorded (R8). V5 pinned the defect; it now requires the kept row and a retry that succeeds.
- **Finding 4 (P2): fixed.** `request_pairing` checks before its idempotent return; A23's line is unchanged.
- **Finding 5 (P3): fixed.** The refusal prints through `escape` (the file's pattern) with `emoji=False`. The other pairing CLI output is older and recorded (R9).
- **Finding 6 (P3): fixed in M1 (7.1) and M3 (7.13).** A DID's agent part must pass `is_sovereign_identity_key`, which a colon-free string passes only as a lower-case UUID; certificate UUIDs are `str(uuid4())` (`identity.py:117`).
- **Findings 2 and 3 (P2, not regressions): recorded** as R2/R5 and R1, with the requirement on the AD that wires pairing. Neither file is changed by this PR. No production path carries either DID to a guard (AV17, AV18), and M3's paired path checks the session by DID, so it refuses an unrestored DID. #1581's Do Not Build list keeps AD-802's flow out of this PR.
- **Tests and rows.** V4 gains the repeat; V5 has three cases; V9 is new, placed after V5 so 7.14's anchors hold: 9 functions, 14 cases. A25 is rewritten, A34-A36 added: 77 rows.
- **Trackers.** 8b's final DECISIONS line changes. Section 8's interim lines, which 8b replaces in M3's commit of the same PR, are left as they are so 8b's SEARCH keeps matching. 8b's PROGRESS text ("before a certificate, a pending row or a consumed code") is now accurate.
- **A1 and A2 anchors.** 7.1's sixth SEARCH, 7.13's first SEARCH, 7.14's SEARCH blocks, 7.15-7.19 and every SEARCH in 8 and 8b are unchanged. 7.13's second SEARCH follows M1's new text; 7.13's REPLACE gains two lines.
- **Envelope.** A3 moves a destructive step after its checks and closes three refusal gaps; no control weakens; no "Still requires the Captain" condition applies.

## 19. Amendment A4 (2026-10-22): the M1 review (round 2) and the M2 and M3 reviews (round 1)

**Amended by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-22, on `gpt-6.1-sol`'s NOT READY reviews of `6911e258` (M1 r2, one finding), `0a2a6026` (M2 r1, three) and the M3 r1 candidate (four), all confirmed by execution, read on scratch `58900dee`.

- **M1-1 (P2, injected-only, a regression A3 introduced): fixed (7.3, V10, A37).**
  - Approve's pre-read checks the stored names only while the row is unexpired: `stored.expires_at >= self._clock()`, the complement of the post-consume check's `<` and of the sweep's.
  - An expired row therefore goes on to `consume_pending` and answers `UnknownPairingCode(... expired)` whatever names it holds, as round 1 did. An unexpired row with an undeclared name is still refused and kept.
  - A row that expires between the read and the consume is consumed and answers expired (round 1).
  - The two checks read the clock separately. If the clock steps back between them, the backstop refuses an expired-at-read row by name after the consume: round 1's outcome, with no row kept.
  - A3's disclosure that an expired row "is refused by name too, and stays" is withdrawn.
- **M2-1 (P2, ordinary, regression): fixed with option (A) (7.8, 7.12b, W9, W10, B24-B26).**
  - `WardRoomService.check_subscribe(agent_id)` makes `subscribe`'s check and nothing else, so it gives the same 403 body and the same event.
  - `create_assignment` checks every member before the channel, any subscription, any deferred subscription or any row. `add_member` checks the member before its row. Both check only where a subscription would follow.
  - Rejected:
    - (B) subscribe the authorised members and report the refused ones: an API shape change, and an assignment whose members differ from the request. BF-771's per-recipient refusal fits a fan-out whose other recipients were already served; here nothing has happened yet.
    - (C) re-raise after the side effects: leaves partial state, and a retry meets the existing channel.
    - (D) refuse visitors as members: over-refuses a visitor holding `ward_room.read`.
  - The facade now has 48 public signatures, 19 actor-like, 12 guarded and 7 exempt. No test enumerates it (AV26).
  - Admission is decided at entry: a session that lapses between the check and its subscription is refused there and logged by the existing handler (R11).
- **M2-2 (P2, ordinary, regression): fixed (7.12c, W11, B27).** The teaching route re-raises `VisitorScopeRefused` before its generic handler.
- **M2-3 (P3, test isolation): fixed (7.11).** `_api_runtime` sets `_data_dir` and `data_dir` to None. W7 builds the app in an empty working directory and asserts it stays empty. No mutation row: the assertion is the guard.
- **M3-1 (P2, ordinary, regression): fixed (7.16, Q4, C11, C19, C20).**
  - The walk adds a container's width (`2 * len` for an object, `len` for an array) before any child is read or queued, and refuses when the count passes the budget.
  - The count is the old one for a complete walk, so the threshold is unchanged.
  - The docstring and the constant's comment now say what is bounded.
- **M3-2 and M3-3 (P2 and P3, coverage): fixed (7.19, C21, C22).**
  - The rig binds a live Counselor (a roster stand-in; the bus and receiver are real). P2 asserts one delivery; P3 asserts none, with a non-null resolved id.
  - Q1 asserts the peer registry stays empty; Q2's one peer is the control.
  - C21 (delivery before the guard) and C22 (a peer registered before the refusal) are the reviewers' mutants as single-line rows.
- **M3-4 (P2, injected-only, not a regression): recorded (R10).** It needs a direct Python caller passing a `str` subclass; JSON decoding yields plain strings, and `AgentID = str`.
- **Absence.** AV23-AV28. The client-facing consumers that turned a refusal into success were the assignment service and the teaching route. The shell's `procedure teach` reports a refusal as a failure. The rest act as internal actors and log and degrade.
- **Tests and rows.** M1 has 10 functions and 16 cases, M2 11 and 38, M3 9 and 23. A37, B24-B27 and C19-C22 are added and C11 is rewritten: 86 rows. M2's focused gate gains the assignment, birth-chamber and teaching-route tests.
- **Trackers.** 8b's DECISIONS line and the repository's `DECISIONS.md` change, in M3's commit; regenerate the ledger there. Section 8's interim lines stay as they are, so 8b's SEARCH keeps matching.
- **A1, A2 and A3 anchors.**
  - Changed: 7.3's fourth REPLACE (A3's pre-read line), 7.7's text between V5 and V9 (A3's; V10 is inserted), 7.8's subscribe REPLACE (appended), 7.11, 7.16's REPLACE, 7.19 and 8b's DECISIONS REPLACE line.
  - Unchanged: every SEARCH a Builder applies (7.1-7.19, 8 and 8b) and the A1-A3 SEARCHes. 7.14 anchors on the import block and on V7 and V8, which A4 does not touch.
- **Not run in this consult:** any test, the precheck, ruff, the swallow probe and the apply of A4's pairs.
- **Envelope.** A4 restores round 1's expired-row outcome, moves two consumers' refusal ahead of their first side effect, and lets a refusal reach the 403. No control weakens and no authority widens; no "Still requires the Captain" condition applies.

## 20. Validation of record (2026-10-22, win32)

Written by the orchestrator after the build, from the campaign's own output. It records what was run on the tree that ships; it changes no decision.

**Review history.** M1: round 1 NOT READY (six findings; Amendment A3), round 2 NOT READY (one P2 regression that A3 introduced, injected-only; Amendment A4), round 3 READY. M2: round 1 NOT READY (two P2 regressions and one P3; Amendment A4), round 2 READY. M3: round 1 NOT READY (one P2 regression, two coverage gaps and one P2 injected-only finding, recorded as R10; Amendment A4), round 2 READY. Every round by `gpt-6.1-sol` on CPython 3.12.13 (round minutes: M1 23.4, 15.4 and 14.5; M2 39.4 and 23.6; M3 29.2 and 15.9). The Architect (`claude-architect`, Opus 5.5) answered five read-only consults for this item (the contract and A1 to A4) and a short sixth on filing: BF-914 (#1621) holds the latent channel exposure, and R8 and R9 sit in the register item for the AD that wires pairing.

**Orchestrator decisions.** The two mechanical repairs in the header (the third pair of 7.5 and the first pair of 7.12c, each so that the staged contract passes `scripts/phantom-api-precheck.ps1`; no decision changed) and the choice not to file R8 and R9 as their own issue under the filing policy, which the Architect confirmed on 2026-10-22. Every other decision is the Architect's (the contract, A1 to A4 and the filing ruling).

**Mutation campaign.** The 86 rows of section 10 ran one at a time in four groups on three checkouts of one tree, commit `08d517ee`, tree `59ce0f0392eb9a91954b5fe98cd8241999aa2d0b` (the batch's code and tests as committed; the commit after it changes documents only): A (37 rows) against `tests/test_bf903_visitor_scope.py`, unmutated baseline 16 passed; B (27 rows, in two halves) against `tests/test_bf903_ward_room_scope.py`, baseline 38 passed; C (22 rows) against `tests/test_bf903_channel_and_mcp.py`, baseline 23 passed. Each row was restored before the next. **86 of 86 killed.** First failing test per row: `test_one_vocabulary_names_every_visitor_capability` A1, A20, A22; `test_register_refuses_an_undeclared_capability_before_a_certificate[typo]` A2, A3, A4, A33; `test_the_registry_refuses_by_session_capability_and_expiry_at_use` A5 to A12; `test_a_visitor_is_known_by_its_certificate_and_other_ids_are_never_looked_up` A13, A14, A27, A28, A30; `test_the_one_guard_passes_crew_and_refuses_what_the_seam_does_not_allow` A15, A17, A18, A19, A31, A32; `test_a_malformed_agent_did_is_never_looked_up` A16, A29, A36; `test_the_config_refuses_an_undeclared_default_capability` A21; `test_pairing_refuses_an_undeclared_capability_before_it_is_stored` A23, A24; `test_the_cli_names_an_undeclared_capability_and_keeps_the_code` `[row-minted-before-bf903]` A25, A34, `[undeclared-cap-flag]` A26, `[markup-in-a-name]` A35; `test_an_expired_pending_row_is_consumed_and_answers_expired_whatever_names_it_holds[row-minted-before-bf903]` A37; `test_a_write_needs_dm_send_in_a_dm_channel_and_ward_room_post_elsewhere` `[thread-in-dm-channel]` B1, `[post-in-dm-thread]` B2, B7, B8, `[edit-in-dm-thread]` B3; `test_a_visitor_without_the_capability_is_refused_at_each_entry` `[create_thread]` B4, B5, B6, B13, `[list_channels]` B9, `[dm_channel_as_b]` B10, `[dm_channel_as_a]` B11, `[browse_threads]` B12, `[create_post]` B14, `[edit_post]` B15, `[endorse]` B16, `[subscribe]` B17, `[update_last_seen]` B18, `[get_unread_counts]` B19, `[get_unread_dms]` B20; `test_a_real_boot_scopes_visitors_in_the_ward_room` B21; `test_the_api_answers_a_visitor_refusal_with_403_and_the_reason` B22, B23; `test_an_assignment_naming_a_refused_visitor_changes_nothing_and_answers_403` B24, B25; `test_adding_a_refused_visitor_to_an_assignment_writes_no_member_and_answers_403` B26; `test_the_teaching_route_answers_a_visitor_refusal_with_403` B27; `test_an_unreadable_pairing_store_refuses_the_message_and_its_callers_still_catch_it` C1, C2; `test_a_paired_sender_is_refused_commands_and_conversation` `[slash-command]` C3, C4, `[unknown-callsign]` C5; `test_a_paired_sender_holding_dm_send_reaches_the_crew_member` C6, C7, C21; `test_a_paired_dm_without_a_live_dm_send_is_refused[capability-missing]` C8, C9; `test_a_tools_call_naming_a_visitor_is_refused_before_either_branch` `[intent-did]` C10, C14, C16, C17, C18, C22, `[object-key]` C13, `[list-item]` C15; `test_the_argument_walk_reads_up_to_its_bound_and_refuses_past_it` C11, C12, C19, C20. Where the first failing test is not the one the contract names, the named test was run alone against the mutant and killed it: A16 (V8), A29 (V7), C6 and C21 (P3 `[capability-missing]`), C19 and C20 (Q4). Every other row was killed first by the test the contract names. sha256 of that tree's working copies (the same on every checkout): `src/probos/__main__.py` `b1bba162a22c91083ea62d2c3d1bed72fc5a8c6acd3fb563b31c07c26d7ad0c9`, `src/probos/api.py` `3f3d09fd959280e3387b5a11a737f40eee54e9721fc6c452fc654f62827e1714`, `src/probos/assignment.py` `917042231a4649ff0d3415a4705237643c4976de98635a9a5efdfc08e44d6ea3`, `src/probos/channels/base.py` `4877d4b381aa9eb77f4c03c01d2eba65565778d1d6901ef4c42def0772860422`, `src/probos/config_models/crew.py` `2e8a27e9aa04237c4de6a947192f6cdecc936a23fac00ae85dc4ce7e6de6e1bc`, `src/probos/federation/mcp_server.py` `66b0435757aa6c0a7d6040c1cbbb4808536a3e9ca6087f507ae8d1614493df1b`, `src/probos/routers/procedures.py` `5ad644fbd77f8d606d37a089fd626bd1216c5f0cd16942cde0aa6773f91c193f`, `src/probos/security/pairing/service.py` `8fccf553fe32afea2a6b2de266b680ba1a25f3563a5db1cd1a74d9e6fa893872`, `src/probos/startup/finalize.py` `9373233f794b84304c2cc4183270301562e16e187641d490953b02fac1958403`, `src/probos/visiting_officers.py` `6b4fe48e5edfb1e1dfb583e49912512cd998023c197fabee259051ecbe3e07b5`, `src/probos/ward_room/service.py` `eec0e522b341b630233ef72c88d613deda8eab923edf9ddea0965b323beb2db8`, `tests/test_ad701_visiting_officers.py` `8f8d346cc8c35297ae62af84694198dc0a9e6890000b4e4cf5f1dae22209b822`, `tests/test_ad802_pairing.py` `358c84f00c8cef8abfda26f68a3f47c9db68a89ad96d9c56d0ccabc11f2e3845`, `tests/test_ad807_discord_refresh.py` `19c8c5edbcca62baa8f07be089eff864791a479007f0bdd9fab38cbb8799cc4b`, `tests/test_bf804_pairing_notification.py` `296dd88ee894c7d5d50aa94fecd37520318772c76cb5dc441113ec43761fa29b`, `tests/test_bf903_channel_and_mcp.py` `1221f6b8a76c2995a15965c01010db59f729e9b829675c51824cdaecbcf0a339`, `tests/test_bf903_seam_was_open.py` `c9dea2ba03d3ef3296d8ddc28a8bc7776a963f8120bec699e43a8f8e49d98e53`, `tests/test_bf903_visitor_scope.py` `1b891d80690d6a75547d8fbbf5b26f1c4a86ed3690e30b3466c463298f3b5ac8`, `tests/test_bf903_ward_room_scope.py` `b415f9590ab8bdb58d674d76158f5974e37c500e4b0d766e858c25efb724dd2c`.

**Consolidated focused checks** (the test files that name a changed surface, scrubbed environment at `-n 8`, then the three tree-scanning files unscrubbed at `-n 0`): M1's frozen candidate (round 3, 51 files) 1,843 passed, 2 skipped, 0 failed (44 passed unscrubbed); M2's (round 2, 53 files) 1,882 passed, 1 skipped, 0 failed (44 unscrubbed); M3's (round 2, 73 files) 2,838 passed, 2 skipped, 0 failed (44 unscrubbed); the whole contract applied by tool to a scratch tree gave the same 2,838 and 2. The broad gate's receipt and CI are recorded on #1581, not here.

**Register.** F-272 to F-285 are on #1523 (comment 6342228448); BF-914 (#1621) holds the latent channel exposure found while building this.

## 21. Amendment A5 (2026-10-22): the broad gate, and a method name the AD-1343 census reads

**Amended by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-22, on the red broad gate of `560e01b5` (one failure: `tests/test_ad1343_stop_seam_inventory.py::test_stop_checks_are_exactly_the_inventory`), read on a detached tree at that head.

- **Cause (regression, ordinary reach: every checkout fails the guard).** The AD-1343 census (`tests/fixtures/ad1343_seam_census.py`) records any call whose bare callee name is `refusal` as a stop check, with its second argument as the seam. 7.1's registry method was named `refusal`, so `has_capability` and `check` were read as two stop checks naming the seam `capability`. It is a name collision; there is no behaviour fault.
- **Fix: the method is renamed `capability_refusal`** (7.1, A10), the repo's `<noun>_refusal` convention for a reason-or-None. AD-1343's guard and tables are unchanged. Rejected: exempting the file or the receiver in the census (it leaves a hole for a real stop check added there), pinning the two sites as stop checks (`capability` is not a stop seam), and keeping the name behind a private helper (a public method nothing calls).
- **Text.** Sections 2, 3 (D6), 5 and 8b's REPLACE, and `PROGRESS.md`, name the new method. Section 8's interim text and 8b's SEARCH stay as M2 wrote them, so 8b still matches 8. The ledger carries no method name; it is regenerated and checked with `--check`.
- **Mutation.** Group A (37 rows) reruns, because the sha256 of `src/probos/visiting_officers.py` changes. Groups B and C stand on tree `59ce0f0392eb9a91954b5fe98cd8241999aa2d0b`: their files and test files are unchanged, and the rename changes no behaviour.
- **Lesson for validation.** A new method name is an input to the name-based censuses. Before naming one, check it against `STOP_CALLEES`, `GUARD_CALLEES` and `RECORDED`, and put every test that imports `tests.fixtures.ad1343_seam_census` or `tests.fixtures.ad1343_seam_registry` in each focused list.
