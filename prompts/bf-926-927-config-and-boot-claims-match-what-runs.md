# BF-926 + BF-927: config fields and boot claims say what runs (#1656, #1657): unread config fields are marked inert or removed, a report-only check lists fields nothing reads, and the boot log and docs stop calling uninvoked security and verification services "wired"

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-25

**Amendment A1 (2026-10-25, `claude-architect`; on `origin/main` `5e3cc991`, after BF-924's PR #1665).** §7.12's deletion of `security.memory.enforce_leak_guard` moves the default `SystemConfig()` dump, which the AD-1152 OFF golden pins (`tests/fixtures/ad1152_agentic_off_golden.json:17` `default_config_sha256`, `:15` `observation_sha256`; `tests/test_ad1152_agentic_correlation.py:215-218`, `:500`, `:514-516`, `:569-570`). The draft missed it: section 12's census grepped counts, not digests. Added: §7.24 (the two derived digests, refreshed by tool), the AD-1152 file on M2's focused list, its three cases in M2's tests-first count (45 to 48), a row in section 5(d), a digest census in section 12 and R9. Binding control, campaign of record (`logs/bf926r1/`, base `5e3cc991`): the base source with exactly `config["security"]["memory"]["enforce_leak_guard"]` popped passes the three cases against §7.24's values; `main`'s fixture fails them at `default_config_sha256`; the unmodified test fails them against §7.24's values. Applied by tool with no review round (BF-924 brake 6, option B), in M2's commit. No other pair changes.

**Status:** build-ready. Two BFs, one batch, two milestones, one PR, one gate; #1656 and #1657 close with it. **Numbers:** BF-926 (#1656), BF-927 (#1657); this contract allocates nothing. **Tier:** M1 **STANDARD** (BF-927: log text, docstrings, roadmap status words, one new test); M2 **STANDARD** (BF-926: field descriptions, one field deleted, yaml keys, a report-only script). **No behaviour change:** no gate, detector, check or listener starts or stops; the only executable additions are a script nothing gates on and two test files. **Base:** `7ffbda5a` (`origin/main` `8f9fd379` plus BF-924's contract applied); BF-924 (#1654) merges first; the orchestrator re-verifies every SEARCH on the merge SHA, and a changed REPLACE returns to the Architect. **Line endings:** working copies are CRLF (`core.autocrlf=true`); every SEARCH here is LF; match and write with each file's own endings; new files are LF. **Fragment SEARCHes:** the roadmap entries (§7.9, §7.10) are single lines of up to 10,000 characters; their SEARCH is a fragment of the line and occurs once in the file.

**Amendment A2 (2026-10-25, `claude-architect`; round 1 of the whole review: F1 P1, F2-F6 resolver, F7 wording).** F1: the AD/BF ledger is regenerated in a third commit, generated files only, after both milestone commits and after any merge of the base (§8, §14.8; BF-924 `34df056c` precedent). F3 fixed in §7.11: a literal `getattr(holder, "entry")(...)` is a call, and an entry method passed or assigned uncalled is an escape; three fixture cases (34 to 37 cases) and rows A7-A9. F5: wording only (an escape cannot make an invoked service less invoked). F2, F4, F6: disclosed in the test docstring, D7 and §14.3, and recorded as R10. F7: the 23 markers say "reads this field/section to act on it", by substitutions S-A/S-B (the marker substring is unchanged); the yaml comments (S-C) and the script's docstring and argparse text say the same; the config API (`routers/config.py:191`, `:211`, `:246`, `:267`) is named as generic I/O. No production behaviour, default, row or pin outside §6's list changes. Applied by tool; round 2 is a delta review.

**Tests:**
- New `tests/test_bf927_boot_claims.py` (M1: 6 functions, 37 cases).
- New `tests/test_bf926_config_readers.py` (M2: 6 functions, 49 cases).
- New `scripts/check_config_readers.py` (M2, report-only).
- Updated pins (M2): `tests/test_ad607_memory_security.py` (default of the deleted field), `tests/test_ad1270e2g_crew_models.py` (pre-move dump of `MemorySecurityConfig`), `tests/test_ad1185_config_profiles.py` (two tests that used the manifest's only conflict edge), `tests/test_ad1270e1_config_facade.py` (field-count pin 1876 to 1875), `tests/fixtures/ad1152_agentic_off_golden.json` (the default-config and observation digests, §7.24, A1).

## 0. Premise: what is present on this tree

| Claim | On `7ffbda5a` | Holds |
|---|---|---|
| F17 fields have one definition and 0 readers | `config.py:611` `use_consensus_for_writes`; `:2488` `memory_policy` (+ `:2491` `memory_policy_selective_tags`, found here); `:2513` `min_peer_trust_score`; `:2517` `shared_trust_min_score`; `config_models/crew.py:122` `enforce_leak_guard` | yes (section 12) |
| `apply_memory_policy` (`mobility.py:58`) has no production caller | def only; 9 test calls (`test_ad443_mobility.py:486-510`) | yes; the module docstring already says "v1 only provides the policy enum and the filter primitive" (`mobility.py:17-19`): unchanged |
| F16 sections promise `enabled: true` with no reader | `config/system.yaml:1967-2023`; models `cognition.py:278-389`; only `config.working_memory.stale_threshold_hours` is read (`finalize.py:6289`) | yes; `working_memory` has **13** fields, 12 unread (the issue said 11) |
| **Found here:** two F16 sections have a consumer seam nobody feeds | `CognitiveAgent` reads `kwargs.get("memory_budget_config")` (`cognitive_agent.py:1415`, `:3747-3750`); `AgentWorkingMemory(pinned_config=...)` (`agent_working_memory.py:294`, `:334-341`); the only construction is `AgentWorkingMemory()` (`cognitive_agent.py:1365`) and nothing passes `memory_budget_config=` | inert all the same; the wording names the unfed seam |
| F26 `captain_card_refresh_min_interval_seconds` in tracked yaml | `config/system.yaml:106`; field removed by AD-1234 (`test_ad739_captain_card.py:138`, `test_ad1234_*:42`) | yes |
| Config models ignore unknown keys | `model_config` occurs nowhere in `config.py` and only at `config_models/operations.py:166`, `:215` (the two `CommandPolicy*` models, `extra="forbid"`, not touched); `config_profiles.py:10-11` documents `extra="ignore"` at every level | an operator yaml that still sets a deleted key loads |
| BF-927 boot lines | `finalize.py:255`, `:1210`, `:4098`, `:4101` (AD-530, AD-511); `:4328` AD-676; `:4336` AD-679; `:4374` AD-451; `:4558` AD-455; `:4727` AD-528b; `:4765` AD-528 | yes; AD-753 has **no** boot line |
| **Found here:** AD-455's fourth service runs | `RedTeamLead.start()` is awaited at `finalize.py:4557` and loops a pool-health check (`red_team_lead.py:58-61`, `:80-130`) | the AD-455 line splits: one "running", one "built, not invoked" |
| **Found here:** the manifest's only conflict edge names the deleted flag | `config-profiles.yaml:462-468` (`social_verification.expose_episode_content` conflicts with `security.memory.enforce_leak_guard`); every other row has `conflicts_with: []` | two AD-1185 tests are re-based on a fixture edge (D3) |
| **Found here:** the reference generator never renders `security.memory` | `gen_config_reference.py:136-138` dedups sections by field **name**; top-level `memory` renders first (`config-reference.md:168`) | deleting `enforce_leak_guard` changes no reference row (R1) |
| #1324's producer/consumer check | proposed in #1324's comment ("2. Work item: an event producer/consumer audit, then a check ... a **report-only** producer/consumer check, beside `check_seam_contracts.py`"), **not built** (section 12) | the config check mirrors the existing report-only precedents instead (D5) |

## 1. Problem

- **F16/F17 (#1656).** Thirty-nine config fields, plus the leak guard, promise behaviour nothing reads; the reference shows them with empty descriptions as if they work. `security.memory.enforce_leak_guard` promises redaction; the leak guard only emits `MEMORY_LEAK_SUSPECTED` and "never mutates the response" (`cognitive_agent.py:12309-12311`).
- **F26 (#1656).** A yaml key whose field was removed is silently ignored.
- **F01/F07/F08/F09 + three from #1658 (#1657).** Ten boot-log lines say `wired` or `initialized` for services nothing calls; config summaries and roadmap statuses say the same; the Captain reads "inbound input is screened".

## 2. Solution overview

- **M1 (BF-927).** Each boot line says `built, not invoked` (AD-455 splits into a "RedTeamLead running" line and a "not invoked" line). The six config models' reference summaries, eight roadmap status markers, `vote_on_intent`'s docstring and a Yeoman comment say the same. A new test traces every caller of each service over `src/probos` with the AST (from each construction or typed parameter, not by method name; its approximations are listed, R10) and pins every claim against that state in both directions, on the real boot code, the real models and the real files, plus one booted runtime.
- **M2 (BF-926).** `enforce_leak_guard` is deleted (model, tracked yaml, the profile manifest row and its conflict edge). Thirty-nine fields carry one phrase, `Inert: no production code reads this`, in their `Field(description=...)` or in their model's docstring summary, so the generated reference shows it. The stale F26 key leaves the tracked yaml. `scripts/check_config_readers.py` lists unread fields, inert fields and yaml keys with no field, and always exits 0. The generated config reference and facade baseline are regenerated once, for both milestones.

## 3. Decisions (for #1656 and #1657)

**D1, how a field is marked inert.** Ranked: (1, chosen) one constant phrase, `Inert: no production code reads this`, opening the field's `Field(description=...)` (`... this field to act on it (BF-926, #1656). <what is true>`) or the first paragraph of the model's docstring (`... this section to act on it ...`) when every field of the model is unread; "to act on it" (A2) excludes generic config I/O, which dumps and rewrites every field (`routers/config.py:191`, `:211`, `:246`, `:267`); the generator renders exactly those two places (`gen_config_reference.py:145-149`, `:160`), and the report-only check and the guard test find the phrase as a substring; (2) a `json_schema_extra={"inert": True}` flag: the reference would not show it; (3) a comment: invisible to the reference and to any check. The phrase is written literally in each description: a shared constant in `config_models/` would add a module to the facade's surface for a doc string (DRY is held by the guard test instead, which fails on any drift of the phrase).

**D2, mark rather than remove (F17 except the leak guard, F16, AD-753's two fields).** Ranked: (1, chosen) keep each field and mark it: the five F17 fields and the two AD-753 fields describe governance behaviour that #1659 (paused) is meant to build, and the F16 sections describe AD-573/579/670 machinery #1324 tracks; removal would delete the design intent and every operator's value, and would move the facade surface (field count, dump) for no runtime gain. Unknown keys are ignored (section 0), so removal would also load, silently: marking is the visible choice. (2) Remove all: loses the record of what #1659 must wire. (3) Wire: new enforcement capability, #1659's scope and paused. **Candidates for #1659** (the orchestrator posts this list on #1659): `cognitive.use_consensus_for_writes`, `federation.memory_policy` (+ `memory_policy_selective_tags`, and `mobility.apply_memory_policy`, which has no caller), `federation.min_peer_trust_score`, `federation.shared_trust_min_score`, `security.permission_mode`, `security.policy_engine_class` (with `consensus.quorum.vote_on_intent`).

**D3, the leak guard: delete (the issue forbids marking it inert).** Deleted from `MemorySecurityConfig`, the tracked yaml (`system.yaml:977`) and the manifest (`config-profiles.yaml:225-233`, its classified row). Its conflict edge with `social_verification.expose_episode_content` (`:462-468`) goes with it: a row naming a removed path fails the manifest check, and the edge guarded against arming a flag that redacted nothing. That edge was the manifest's only conflict, so two AD-1185 tests lose their fixture. Ranked: (1, chosen) re-base both on a fixture edge between two real booleans (`federation.enabled` conflicts with `federation.tls.enabled`, the pair `test_ad1185_*:750-759` already uses): `test_a_conflicting_profile_raises_at_parse` writes a one-row manifest and passes `manifest_path=` (`config_profiles.py:571-587`); `test_an_unexplained_conflict_fails` adds an edge with no rationale in its mutation; the parse-time conflict check stays proven, and the committed manifest declares no conflict (true of the data); (2) re-point the committed conflict at another flag: invents a policy; (3) keep the row: `check_config_profiles.py --check` fails on an unresolved path. Wiring the redaction is #1659. **Not a weakened control:** nothing read the flag (section 12); arming it changed nothing.

**D4, F26 and the tracked yaml.** Remove `cognitive.captain_card_refresh_min_interval_seconds` from the tracked `config/system.yaml`; the F16 sections and the F17/AD-753 keys gain one-line comments that say what the description says. Every `config/system.yaml` pair edits the tracked file in this worktree; the Captain's local uncommitted hunks (about lines 34, 261, 1753, another checkout) are untouched, and none of this contract's hunks is within 50 lines of them. `config/node-1.yaml:56` and `config/node-2.yaml:56` also set `use_consensus_for_writes: true`: unchanged (inert, loads; R5).

**D5, the report-only check: shape, home and where it runs.** #1324's check is not built (section 12), so the shape mirrors the two report-only precedents that exist: `run_test_gate.py`'s `DURATION BUDGET (report-only): ` prefix (`:1616`) and the scripts that insert their own tree's `src` and run with `-P` (`check_config_profiles.py:60-62`). It is name-based, the shape of vulture's dead-code scan (scope-free, so it under-reports; a generic name counts as read), and says so in its docstring. Where it runs, ranked: (1, chosen) a separate command only: every `run_test_gate.py` preflight phase gates on its exit code (`:1856-1872`), so adding it there needs either a new advisory-phase kind in the gate (a gate change) or trusts the script never to crash; neither is worth it for a report the Captain has not asked to see per run; (2) a preflight phase: makes the gate's success depend on a new script; (3) a pytest-only report: the tests prove its behaviour, not a place to read it. **Exit status:** `main` returns 0 on every path (a yaml it cannot read and a source file it cannot parse are warnings; argparse's `SystemExit` is caught; any other exception is printed); the tests prove it on six classes of bad input and one real process (§7.19). When #1324's event check is built, it should share this output shape.

**D6, BF-927 wording.** One phrase, `built, not invoked`, in every claim over a service with no production caller, followed by what is true ("nothing calls check_authorization"); "wired", "initialized", "active" and "enforc..." never appear in such a line. The AD-455 line becomes two lines (`RedTeamLead running` and the three uninvoked services), because one line cannot be true of both states. Ranked: (1, chosen) reword in place, lines kept; (2) remove the lines: hides that the services exist; (3) "observational, no seam wired" for the three detectors: a second phrase the pin would have to know. The finalization summary lines for AD-530 and AD-511 (`finalize.py:4098`, `:4101`) are reworded too: they repeat the claim.

**D7, BF-927's pin: how callers are found.** Ranked: (1, chosen) receiver tracing over `src/probos` with the AST, excluding the service's own module: an instance is followed from its construction (`X = Service(...)`) and from every parameter annotated with its class, through assignments (`runtime.attr = local`, `getattr(runtime, "attr")`) to a holder set; a call is `holder.entry(...)` or `getattr(holder, "entry")(...)` with a literal name (A2); a hand-off it cannot type (a holder passed as an argument to anything but a keyword parameter annotated with the class, or an entry method passed or assigned uncalled, A2) is an **escape**, which, for a service with no resolved caller, fails the test rather than counting as "not invoked" (for an invoked service an escape could only add callers and changes nothing); a call made inside another service's entry method counts only once that service is invoked (so `ThreatDetector.scan`, called only inside `InputValidator.check`, `input_validator.py:60`, stays not invoked). RedTeamLead is the invoked control, so the "says not invoked over a caller" direction is exercised on the real tree, and a fixture package proves the resolver finds a caller and a literal-getattr caller, a typed hand-off, an escape, and an entry method handed on or aliased, and ignores a decoy `.check(` (§7.11). (2) Name-matching `.check(` / `.scan(`: 70 unrelated hits (section 11). (3) A hand-kept table of call sites: drifts as soon as any unrelated `.check(` is added. **What it cannot see** (in the test's docstring): a method name built at run time, an instance or bound entry method stored in a container, tuple target, `setattr`, `return` or `**kwargs` (a `**holder` argument is an escape), an instance returned from a function, a local captured by a nested function, calls inside the service's own module (except the declared `via` delegation, used for `GroundTruthVerifier`, reached only through `GroundTruthRejectionGate.evaluate` in the same module), and callers in `ui/`, `scripts/`, tests or plugins. **Known approximations** (A2, R10): a holder attribute is matched by name, not owner (a false caller, which fails loudly); a positional argument is an escape even into an annotated parameter (fails loudly); a typed parameter is keyed by its callable's short name and the parameter name (a keyword hand-off to another callable with both names alike is exempt: the one silent form left).

**D8, which docs change (BF-927).** Living status claims only: the six config models' summaries (the reference renders them), `roadmap.md:730` (AD-753) and seven status markers in `roadmap-era-5-completed.md` (AD-451, AD-455, AD-511, AD-528, AD-530, AD-676, AD-679; the issue's "roadmap entries that mark them complete" live there, not in `roadmap.md`), status wording only: no number, no row. Not changed, ranked by the alternative of rewriting them: dated records (`progress-era-5-unification.md`, `decisions-era-5-unification.md`, `DECISIONS.md`, `PROGRESS.md` history, `docs/development/yeo-gap-reconciliation-2026-05-20.md:53`, `:177`) are records of what was believed on their date; the Phase 31 design list (`roadmap-era-5-completed.md:307-310`) describes intent, not status (R8). AD-528b's roadmap entry already says *Scoped*.

**D9, scope and milestones.** One batch. M1 = BF-927 (first heading `### 7.1 \`src/probos/startup/finalize.py\` (M1)`); M2 = BF-926 plus the regeneration (first heading `### 7.12 \`src/probos/config_models/crew.py\` (M2: the leak guard)`), last because the generated files must follow all model text: M1 changes six docstrings, so **M1's commit leaves `config-reference.md` and `config-facade-baseline.yaml` stale on purpose**; M1's focused list omits the two tests that check them, and M2 regenerates for both.

## 4. Interaction with the queue

- **BF-924 (#1654)** is applied in this tree and merges first. It changed `config_models/emergence.py` (`CounselorConfig`), the yaml `counselor` block, the manifest's `census:` header and `unclassified_flags`, the generated files and the field-count pin (1880 to 1876). This contract's `emergence.py` pair anchors on `GroundTruthConfig`'s head (`:30-31`), not `CounselorConfig`; its census pair replaces BF-924's header text; its count pin replaces BF-924's pin lines.
- **#1626 M6+M7** edits `ui/`, the BF-918 paragraph of `PROGRESS.md` and BF-918 D7 in `DECISIONS.md`: no pair here touches them.
- **Tracker anchors:** `PROGRESS.md`'s title line (once, `:1`) and `DECISIONS.md`'s heading `### BF-924 -- Trust inputs read through APIs that exist (2026-10-25, #1654)` (`:739`, once).
- **PR text (this batch):** "BF-926 (#1656) and BF-927 (#1657). What the ship says about itself now matches what runs. BF-927: ten boot-log lines said AD-455's Security Team, AD-676 risk tiers, AD-679 disclosure routing, AD-511 and AD-530's detectors, AD-451 reconciliation and AD-528/528b ground-truth verification were wired or initialized; nothing calls them, so each line now says 'built, not invoked' (the AD-455 RedTeamLead health monitor does run and says so); their config summaries, roadmap statuses and AD-753's gate docstring say the same, and a test traces production callers with the AST and fails if a claim and its caller state disagree either way (its known approximations are in its docstring). BF-926: `security.memory.enforce_leak_guard` promised redaction nothing performed and is deleted (old configs still load); 39 other fields nothing acts on carry 'Inert: no production code reads this field to act on it' in the generated config reference (the config API still exports them); a stale yaml key is removed; `scripts/check_config_readers.py` lists unread fields and yaml keys with no field, and never fails. No gate, detector or check starts or stops."

## 5. Consumers of every value this changes

**(a) Boot-log lines (M1).** Readers, enumerated: no test matches any old text (section 12); no script, `ui/` string or doc quotes them; the live `probos.log` (the Captain, the orchestrator's live check, section 16). The new lines print at the same points under the same conditions (section 6 tests the boot).

**(b) Descriptions and docstrings (M1, M2).** Readers: `gen_config_reference.py` (summary paragraph and `Field(description=...)`; regenerated); `check_config_facade.py` (`model_json_schema()` includes both, `:976-981`, so each changed model's and each container's `schema_sha256` moves; regenerated); the report-only check and both new tests (the phrases). No runtime reader: `model_json_schema` and `.description` occur nowhere in `src/probos` (section 12). The facade's per-field `default` is rendered from `model_fields` (`:950-953`), so `x: int = 3000` becoming `Field(default=3000, ...)` leaves every field entry unchanged.

**(c) `enforce_leak_guard` (M2).** Readers before: none in `src` (section 12). Pins: `tests/test_ad607_memory_security.py:165`, `tests/test_ad1270e2g_crew_models.py:185` (dump), `tests/test_ad1185_config_profiles.py:680` (the conflict fixture), `docs/development/config-profiles.yaml:225-233`, `:462-468`, the facade baseline (`:2441`, regenerated), `config/system.yaml:977`, `cognitive/memory_security.py:10` (docstring). Each is changed in §7.12-§7.23. `DECISIONS.md:1555` mentions it historically: unchanged.

**(d) Counts and hashes this moves (every pin, enumerated in section 12).**

| Pin | Base | After | Pair |
|---|---|---|---|
| `test_ad1270e1_*:1558` `field_definitions` | 1876 | 1875 | §7.23 |
| facade `surface_counts.field_definitions` / `canonical_dump_leaves` | 1876 / 1887 | 1875 / 1886 | regenerated |
| facade `canonical_dump_sha256`, 15 `schema_sha256` (section 6) | | moved | regenerated |
| manifest `census:` (`config-profiles.yaml:21-25`) | 449 / 225 / 224 / 85 / 140 | 448 / 224 / 224 / 85 / 139 (only `default_false` is test-pinned, `test_ad1185_*:857-859`) | §7.17 pair 3, re-measured by the orchestrator |
| `test_ad1270e2g_*` `EXPECTED_DUMPS["MemorySecurityConfig"]` | 6 keys | 5 | §7.20 |
| `ad1152_agentic_off_golden.json` `default_config_sha256` / `observation_sha256` (`:17` / `:15`; `test_ad1152_*:514`, `:516`, `:569-570`) | `4fde4128…` / `649c58d0…` | `16cbb4bc…` / `7361f61b…` | §7.24 (A1) |
| `test_ad1270e2*` bound tables (`EXPECTED_BOUND_COUNTS`) | | unchanged (a description is not a bound; `enforce_leak_guard` had none) | none |

**(e) The report-only script (M2).** No consumer: nothing imports or gates on it; the two tests load it by path.

## 6. Milestones and tests

**M1 (STANDARD), §7.1 to §7.11.** First heading: `### 7.1 \`src/probos/startup/finalize.py\` (M1)`. Commit "BF-927: boot log and docs say which security and verification services nothing calls (part of #1657)", body ending "Ten boot lines said wired or initialized for services with no production caller; they now say 'built, not invoked', and the AD-455 RedTeamLead monitor, which runs, says running. The config summaries, roadmap statuses, AD-753's gate docstring and a Yeoman comment say the same. tests/test_bf927_boot_claims.py resolves callers with the AST and pins each claim in both directions. No behaviour change. The generated config files are regenerated in the next commit."

Before editing, grep the pins: `grep -rn "Security Team wired\|ActionRiskRegistry initialized\|DisclosureRouter initialized\|ValidationFramework wired\|GroundTruthVerifier wired\|GroundTruthRejectionGate wired\|ClassificationGate initialized\|ClassificationGate v1 wired\|Autonomy Boundaries v1" tests/ scripts/ ui/src docs/` (expected 0 hits; section 12).

**Doubles (M1): none.** The boot-line and description tests read the real `finalize.py`, the real models through `probos.config`, the real roadmap files; the boot test starts a real `ProbOSRuntime` on `tmp_path` and captures `probos.startup.finalize`'s records with a handler it removes in `finally`. It sets `ground_truth.active_rejection_enabled=True`, which no tracked config sets (`config/system.yaml:1335` is false): **said inline**, the flag only makes the AD-528b line print; the gate is constructed and never called (that is the claim). The resolver's fixture package is a controlled input, not a stand-in for production code.

**Tests first:** with §7.11 applied and §7.1 to §7.10 not, exactly **18** cases fail:
- `test_each_boot_line_says_what_its_services_do` (9): `[AD-455-red-team]` and `[AD-455-screening]` fail on `assert texts` ("no finalize.py log call starts with ('AD-455: RedTeamLead',)" / `('AD-455: InputValidator',)`); `[AD-676]`, `[AD-679]`, `[AD-511]`, `[AD-530]`, `[AD-451]`, `[AD-528b]`, `[AD-528]` fail on `assert (NOT_INVOKED in text) is quiet` with the old text;
- `test_each_description_says_what_its_services_do` (8: AD-455-screening, AD-676, AD-679, AD-753, AD-511, AD-530, AD-451, AD-528): the same assertion with the old summary, roadmap head or docstring;
- `test_the_booted_vessel_prints_the_reworded_lines` (1): "the boot printed no line starting ('AD-455: RedTeamLead',)".

The 12 `test_each_service_state_is_resolved` cases and the 7 resolver fixture cases pass on both sides (the premise: the states are measured, not edited). A failure for another reason, or any `escapes` state, is a hard stop for the Architect. **A2 control:** with §7.11's three new fixture cases applied and its two A2 resolver pairs not, exactly 3 cases fail: `[a literal getattr call]` (`'not invoked' == 'invoked'`), `[an entry handed on]` and `[an entry aliased]` (`'not invoked' == 'escapes'`). Focused check:

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf927_boot_claims.py tests/test_ad455_security_team.py tests/test_ad511_autonomy_boundaries.py tests/test_ad530_classification_gate.py tests/test_ad679_selective_disclosure_routing.py tests/test_ad676_action_risk_tiers.py tests/test_ad451_validation_framework.py tests/test_ad528_ground_truth.py tests/test_ad528b_active_rejection.py tests/test_ad528c_trust_feedback.py tests/test_permission_model.py tests/test_quorum_with_permissions.py tests/test_ad1270e2e_operations_models.py tests/test_ad1270e2g_crew_models.py tests/test_ad1270e2h_emergence_models.py tests/test_ad1270e2i_agentic_models.py tests/test_yeoman_agent.py -n 0 -q
```

(Collected here without the new file: 1,115; not run. Expect 1,152 collected, all passing (A2: the measured 1,149 plus three fixture cases); the orchestrator's measured counts supersede these.) `tests/test_config_reference_current.py` and `tests/test_ad1270e1_config_facade.py` are deliberately outside M1's list (D9).

**M2 (STANDARD), §7.12 to §7.24.** First heading: `### 7.12 \`src/probos/config_models/crew.py\` (M2: the leak guard)`. After applying §7.12 to §7.24, regenerate and check, in this order:

```
d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_config_reference.py
d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_config_facade.py --update-baseline
d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_config_facade.py --check
d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_config_profiles.py --check
d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_config_readers.py
```

The last is the report itself: record its first line in the commit body (it must exit 0). The regenerated `docs/development/config-reference.md` and `docs/development/config-facade-baseline.yaml` go in M2's commit. **Expected generated diff, by hunk** (the orchestrator measures the exact diff and corrects this list; no hash is asserted here):
- `config-reference.md`, summary lines replaced (six from M1, five from M2): `## \`security\`` (`:1021`), `## \`validation_framework\`` (`:1391`), `## \`ground_truth\`` (`:1485`), `## \`risk_tiers\`` (`:2944`), `## \`classification_gate\`` (`:3027`), `## \`autonomy_boundaries\`` (`:3035`), `## \`working_memory\`` (`:2451`), `## \`memory_budget\`` (`:2502`), `## \`metabolism\`` (`:2515`), `## \`pinned_knowledge\`` (`:2530`), `## \`temporal_validity\`` (`:2541`); each new line is the docstring's first line in §7.4-§7.8 and §7.14;
- the same file, rows whose Description cell is filled (Type, Default and Bounds cells unchanged): `cognitive.use_consensus_for_writes` (`:156`); `federation.memory_policy`, `memory_policy_selective_tags`, `min_peer_trust_score`, `shared_trust_min_score` (`:359-363`); `security.permission_mode`, `policy_engine_class` (`:1034-1035`); the 13 `working_memory` rows (`:2455-2467`); no row added or removed (`security.memory` does not render, R1);
- `config-facade-baseline.yaml`, `surface_counts`: `canonical_dump_leaves` 1887 to 1886, `field_definitions` 1876 to 1875, the other counts unchanged; `canonical_dump_sha256` moves;
- the same file, `MemorySecurityConfig`'s field line `- {default: 'False', name: enforce_leak_guard}` (`:2441`) deleted;
- the same file, `schema_sha256` moves for exactly these 15 models: `SystemConfig`, `CognitiveConfig`, `FederationConfig`, `SecurityConfig`, `MemorySecurityConfig`, `WorkingMemoryConfig`, `MemoryBudgetConfig`, `MetabolismConfig`, `PinnedKnowledgeConfig`, `TemporalValidityConfig`, `RiskTierConfig`, `ClassificationGateConfig`, `AutonomyBoundariesConfig`, `ValidationFrameworkConfig`, `GroundTruthConfig` (each changed model, plus `SystemConfig` and `SecurityConfig` as containers; section 12 found no other container). Any other file, model, field line or count, or a `--check` failure, is a hard stop for the Architect.

Commit "BF-926: unread config fields are marked inert or removed, with a report-only reader check (part of #1656)", body ending "security.memory.enforce_leak_guard promised redaction nothing performed and is deleted from the model, the tracked yaml and the profile manifest (its one conflict edge went with it; old configs still load). Thirty-nine fields nothing acts on (cognitive.use_consensus_for_writes, four federation fields, security.permission_mode and policy_engine_class, twelve working_memory fields and the memory_budget, metabolism, pinned_knowledge and temporal_validity sections) say 'Inert: no production code reads this field to act on it' (or 'this section') in the generated reference; the config API still exports and rewrites them. The stale cognitive.captain_card_refresh_min_interval_seconds key is removed. scripts/check_config_readers.py reports unread fields and yaml keys with no field and always exits 0. The config reference and facade baseline are regenerated for both commits. <the report's first line>". The tracker entries (section 8) go in this commit; the ledger goes in the third commit (§8).

Before editing, grep the pins: `grep -rn "enforce_leak_guard\|captain_card_refresh_min_interval_seconds\|use_consensus_for_writes\|min_peer_trust_score\|shared_trust_min_score\|memory_policy\|permission_mode\|policy_engine_class\|field_definitions\|conflict" tests/` and confirm the hits are those of section 12.

**Doubles (M2): none.** The real-tree cases run the check on `SystemConfig`, `src/probos` and the tracked `config/system.yaml`. The fixture model, source tree and yaml are the check's inputs. The re-based AD-1185 tests use a fixture manifest through `load_profile`'s real `manifest_path` parameter (`config_profiles.py:575`), not a patched reader.

**Tests first:** with §7.18 to §7.24 applied (the script is needed to collect the new file) and §7.12 to §7.17 not, exactly **48** cases fail:
- `test_the_real_config_reports_each_bf926_field_as_inert` (39): `assert path in report.inert` (no marker yet);
- `test_the_leak_guard_flag_is_gone_and_a_config_that_sets_it_still_loads`: `assert "enforce_leak_guard" not in MemorySecurityConfig.model_fields`;
- `test_the_tracked_yaml_carries_no_key_bf926_removed`: `assert "cognitive.captain_card_refresh_min_interval_seconds" not in report.orphan_yaml_keys`;
- `test_memory_security_config_defaults_observational` (`test_ad607_*:161`): the new `not in model_fields` line;
- `test_system_config_dump_is_unchanged_for_the_moved_model[MemorySecurityConfig]` and `test_constructing_with_no_arguments_matches_the_pre_move_dump[MemorySecurityConfig]` (`test_ad1270e2g_*:443`, `:544`): the dump still has the key;
- `test_committed_baseline_records_the_measured_surface` (`test_ad1270e1_*`): `assert 1876 == 1875`.
- `test_default_off_matches_pinned_base` (`test_ad1152_*:506`): `AssertionError: default_config_sha256` at `:514`; `test_default_off_golden_pins_only_descriptor_owner_platform[linux]` and `[win32]` (`:521`): the `_json_bytes` comparison at `:569` (first difference at byte 26, inside the digest). The dump still has the field; from §7.12 on, all three pass (A1).

The fixture report case, the 7 exit-status cases and both re-based AD-1185 tests pass on both sides. After §7.12-§7.17 and before regeneration, `test_identity_matches_the_e1_baseline[MemorySecurityConfig]` and the e1 checks fail until the baseline is regenerated; after regeneration everything passes. Focused check:

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf926_config_readers.py tests/test_ad607_memory_security.py tests/test_ad1270e2g_crew_models.py tests/test_ad1185_config_profiles.py tests/test_ad1270e1_config_facade.py tests/test_ad1152_agentic_correlation.py tests/test_config_reference_current.py tests/test_ad1270e2b_cognition_models.py tests/test_ad1270e2i_agentic_models.py tests/test_ad443_mobility.py tests/test_ad573_memory_budget.py tests/test_ad579a_pinned_knowledge.py tests/test_ad579b_temporal_validity.py tests/test_ad670_memory_metabolism.py tests/test_ad1234_captain_card_contract.py tests/test_ad739_captain_card.py -n 0 -q
```

(Collected here without the new file: 1,116 with A1's 41 AD-1152 cases; not run. Expect 1,165 collected, all passing after regeneration.) `test_ad1270e2i_*::test_the_remaining_true_leaf_set_is_pinned` scans `config.py` class bodies with docstrings and comments stripped but **string literals kept** (`:496-519`): a description that names a module-level `config.py` identifier (`yaml`, `os`, `math`, `Path`, a config class or constant) could change a class's leaf status. The three `config.py` classes edited here (`CognitiveConfig`, `FederationConfig`, `SecurityConfig`) are not in `REMAINING_TRUE_LEAVES` (`:160-177`), and adding identifiers can only remove a leaf, so the pin holds; the descriptions in §7.13 avoid those identifiers anyway.

**The broad gate is run once for the batch by the main session, not by the Builder.** New tests must pass alone, in file order and shuffled: both new files hold only read-only process caches (`functools.lru_cache` over parsed source and one report) and restore the one logger they touch.

## 7. The contract

### 7.1 `src/probos/startup/finalize.py` (M1)

Pair 1 (AD-530, `_wire_classification_gate`):

SEARCH:
````python
    logger.info(
        "AD-530: ClassificationGate initialized (%d patterns)",
        runtime.classification_gate.pattern_count,
    )
````
REPLACE:
````python
    logger.info(
        "AD-530: ClassificationGate built, not invoked (%d patterns): nothing calls check_disclosure (BF-927, #1657)",
        runtime.classification_gate.pattern_count,
    )
````

Pair 2 (AD-511, `_wire_autonomy_boundaries`):

SEARCH:
````python
    logger.info(
        "AD-511: Autonomy Boundaries v1 initialized (%d boundaries; %d patterns; observational)",
        len(registry.list_boundaries()),
````
REPLACE:
````python
    logger.info(
        "AD-511: Autonomy Boundaries v1 built, not invoked (%d boundaries; %d patterns): nothing calls the detector's scan (BF-927, #1657)",
        len(registry.list_boundaries()),
````

Pair 3 (the finalization summaries):

SEARCH:
````python
    if _wire_classification_gate(runtime=runtime, config=config):
        logger.info("AD-530: ClassificationGate v1 wired during finalization")

    if _wire_autonomy_boundaries(runtime=runtime, config=config):
        logger.info("AD-511: Autonomy Boundaries v1 wired during finalization")
````
REPLACE:
````python
    if _wire_classification_gate(runtime=runtime, config=config):
        logger.info("AD-530: ClassificationGate v1 built, not invoked (BF-927, #1657)")

    if _wire_autonomy_boundaries(runtime=runtime, config=config):
        logger.info("AD-511: Autonomy Boundaries v1 built, not invoked (BF-927, #1657)")
````

Pair 4 (AD-676):

SEARCH:
````python
        logger.info(
            "AD-676: ActionRiskRegistry initialized with %d actions",
            len(risk_registry.list_actions()),
        )
````
REPLACE:
````python
        logger.info(
            "AD-676: ActionRiskRegistry built, not invoked (%d actions): nothing calls check_authorization (BF-927, #1657)",
            len(risk_registry.list_actions()),
        )
````

Pair 5 (AD-679):

SEARCH:
````python
    runtime._disclosure_router = disclosure_router
    logger.info("AD-679: DisclosureRouter initialized")
````
REPLACE:
````python
    runtime._disclosure_router = disclosure_router
    logger.info("AD-679: DisclosureRouter built, not invoked: nothing calls filter_permitted; /system shows its clearance map only (BF-927, #1657)")
````

Pair 6 (AD-451):

SEARCH:
````python
            metadata_threshold=config.validation_framework.metadata_threshold,
        )
        logger.info("AD-451: ValidationFramework wired (ReconciliationEscalator)")
````
REPLACE:
````python
            metadata_threshold=config.validation_framework.metadata_threshold,
        )
        logger.info("AD-451: ValidationFramework's ReconciliationEscalator built, not invoked: nothing calls reconcile (BF-927, #1657)")
````

Pair 7 (AD-455, split in two):

SEARCH:
````python
        await red_team_lead.start()
        logger.info("AD-455: Security Team wired (4 services)")
````
REPLACE:
````python
        await red_team_lead.start()
        logger.info("AD-455: RedTeamLead running (red-team pool health every %.0fs)", config.security.campaign_interval_seconds)
        logger.info(
            "AD-455: InputValidator, ThreatDetector and TrustIntegrityMonitor built, not invoked: "
            "nothing screens inbound input or analyzes trust integrity (BF-927, #1657)"
        )
````

Pair 8 (AD-528b):

SEARCH:
````python
            logger.info(
                "AD-528b: GroundTruthRejectionGate wired (metadata_key=%s)",
                config.ground_truth.quarantine_metadata_key,
````
REPLACE:
````python
            logger.info(
                "AD-528b: GroundTruthRejectionGate built, not invoked (metadata_key=%s): its caller is AD-528b-2 (BF-927, #1657)",
                config.ground_truth.quarantine_metadata_key,
````

Pair 9 (AD-528):

SEARCH:
````python
        logger.info(
            "AD-528: GroundTruthVerifier wired (threshold=%.2f, window=%.0fs)",
            config.ground_truth.threshold,
````
REPLACE:
````python
        logger.info(
            "AD-528: GroundTruthVerifier built, not invoked (threshold=%.2f, window=%.0fs): only the uncalled rejection gate calls verify (BF-927, #1657)",
            config.ground_truth.threshold,
````

### 7.2 `src/probos/consensus/quorum.py` (M1)

SEARCH:
````python
) -> QuorumResult:
    """Apply AD-753 permission gates before running standard quorum voting."""
    scope = str(intent.params.get("scope") or "unspecified")
````
REPLACE:
````python
) -> QuorumResult:
    """Apply AD-753 permission gates before running standard quorum voting.

    BF-927 (#1657): built, not invoked. No production code calls this function, so
    ``security.permission_mode`` and the tenant policy engine gate no intent today;
    wiring it is #1659.
    """
    scope = str(intent.params.get("scope") or "unspecified")
````

### 7.3 `src/probos/cognitive/yeoman.py` (M1, unpinned comment)

SEARCH:
````python
# Intent names that are pure reads — Yeoman publishes them as
# ``autoApproveReadOnly`` so AD-753/AD-765 unattended modes do not gate them
# behind quorum on every proactive run.
````
REPLACE:
````python
# Intent names that are pure reads — Yeoman publishes them as
# ``autoApproveReadOnly`` for the AD-753/AD-765 unattended modes. BF-927 (#1657):
# the AD-753 gate (``consensus.quorum.vote_on_intent``) has no production caller
# and nothing reads ``read_only_intents``, so this set gates nothing today.
````

### 7.4 `src/probos/config.py` (M1: `SecurityConfig`'s summary)

SEARCH:
````python
class SecurityConfig(BaseModel):
    """Security Team configuration (AD-455).
````
REPLACE:
````python
class SecurityConfig(BaseModel):
    """Security Team configuration (AD-455). The RedTeamLead pool-health monitor runs; InputValidator, ThreatDetector and TrustIntegrityMonitor are built, not invoked, so nothing screens inbound input (BF-927, #1657).
````

(One physical line on purpose: the generator joins a multi-line summary with the continuation indentation, `config-reference.md:572`.)

### 7.5 `src/probos/config_models/crew.py` (M1: `RiskTierConfig`'s summary)

SEARCH:
````python
class RiskTierConfig(BaseModel):
    """Action Risk Tier configuration (AD-676)."""
````
REPLACE:
````python
class RiskTierConfig(BaseModel):
    """Action Risk Tier configuration (AD-676). The ActionRiskRegistry is built, not invoked: nothing calls check_authorization (BF-927, #1657)."""
````

### 7.6 `src/probos/config_models/agentic.py` (M1)

Pair 1:

SEARCH:
````python
class ClassificationGateConfig(BaseModel):
    """Configuration for AD-530 v1 disclosure gate."""
````
REPLACE:
````python
class ClassificationGateConfig(BaseModel):
    """Configuration for AD-530 v1 disclosure gate. The ClassificationGate is built, not invoked: nothing calls check_disclosure (BF-927, #1657)."""
````

Pair 2:

SEARCH:
````python
class AutonomyBoundariesConfig(BaseModel):
    """AD-511 v1: Agent Autonomy Boundaries (registry + observational detector)."""
````
REPLACE:
````python
class AutonomyBoundariesConfig(BaseModel):
    """AD-511 v1: Agent Autonomy Boundaries (registry + observational detector). The detector is built, not invoked: nothing calls its scan, so it observes nothing (BF-927, #1657)."""
````

### 7.7 `src/probos/config_models/operations.py` (M1)

SEARCH:
````python
class ValidationFrameworkConfig(BaseModel):
    """Validation framework configuration (AD-451)."""
````
REPLACE:
````python
class ValidationFrameworkConfig(BaseModel):
    """Validation framework configuration (AD-451). The ReconciliationEscalator is built, not invoked: nothing calls reconcile (BF-927, #1657)."""
````

### 7.8 `src/probos/config_models/emergence.py` (M1)

SEARCH:
````python
class GroundTruthConfig(BaseModel):
    """Ground-truth task verification configuration (AD-528, AD-528b, AD-528c)."""
````
REPLACE:
````python
class GroundTruthConfig(BaseModel):
    """Ground-truth task verification configuration (AD-528, AD-528b, AD-528c). The GroundTruthVerifier is built, not invoked: only the rejection gate calls verify, and nothing calls the gate (BF-927, #1657)."""
````

### 7.9 `docs/development/roadmap.md` (M1: AD-753's status)

SEARCH:
````markdown
| AD-753 | Unattended permissions modes (`autoApproveReadOnly` + approval cards + tenant policy hook) — SHIPPED Wave 181 gate-verified |
````
REPLACE:
````markdown
| AD-753 | Unattended permissions modes (`autoApproveReadOnly` + approval cards + tenant policy hook) — SHIPPED Wave 181 gate-verified; built, not invoked: nothing calls `vote_on_intent` (BF-927, #1657) |
````

### 7.10 `docs/development/roadmap-era-5-completed.md` (M1: seven status markers, fragment SEARCHes)

Pair 1 (`:3856`):

SEARCH:
````markdown
**AD-451: Validation Framework Hardening** *(complete)*
````
REPLACE:
````markdown
**AD-451: Validation Framework Hardening** *(complete; the ReconciliationEscalator is built, not invoked: nothing calls reconcile, BF-927 #1657)*
````

Pair 2 (`:3879`):

SEARCH:
````markdown
**AD-455: Security Team — Threat Detection & Trust Integrity** *(complete)*
````
REPLACE:
````markdown
**AD-455: Security Team — Threat Detection & Trust Integrity** *(complete; InputValidator, ThreatDetector and TrustIntegrityMonitor are built, not invoked: nothing screens inbound input, BF-927 #1657)*
````

Pair 3 (`:6146`):

SEARCH:
````markdown
**AD-511: Agent Autonomy Boundaries — Self-Protection & Unlawful Order Refusal** *(v1 partial — registry + observational detector shipped Wave 22;
````
REPLACE:
````markdown
**AD-511: Agent Autonomy Boundaries — Self-Protection & Unlawful Order Refusal** *(v1 partial — registry + observational detector shipped Wave 22, the detector built, not invoked: nothing calls its scan, BF-927 #1657;
````

Pair 4 (`:6245`):

SEARCH:
````markdown
**AD-528: Ground-Truth Task Verification** *(complete, OSS)*
````
REPLACE:
````markdown
**AD-528: Ground-Truth Task Verification** *(complete, OSS; the verifier is built, not invoked: nothing calls verify, BF-927 #1657)*
````

Pair 5 (`:6273`):

SEARCH:
````markdown
**AD-530: Information Classification Enforcement** *(partial — v1 ships ClassificationGate observational disclosure gate;
````
REPLACE:
````markdown
**AD-530: Information Classification Enforcement** *(partial — v1 ships ClassificationGate observational disclosure gate, built, not invoked: nothing calls check_disclosure, BF-927 #1657;
````

Pair 6 (`:6906`):

SEARCH:
````markdown
**AD-676: Action Risk Tiers** *(Complete, OSS, Issue #364)*
````
REPLACE:
````markdown
**AD-676: Action Risk Tiers** *(Complete, OSS, Issue #364; built, not invoked: nothing calls check_authorization, BF-927 #1657)*
````

Pair 7 (`:6912`):

SEARCH:
````markdown
**AD-679: Selective Disclosure Routing** *(Complete, OSS, Issue #367)*
````
REPLACE:
````markdown
**AD-679: Selective Disclosure Routing** *(Complete, OSS, Issue #367; built, not invoked: nothing calls filter_permitted, BF-927 #1657)*
````

### 7.11 New file: `tests/test_bf927_boot_claims.py` (M1)

````python
"""BF-927 (#1657): what the ship says about its security and verification services matches
whether production code calls them.

Each claim (a boot-log line in ``startup/finalize.py``, a config model's reference summary, a
roadmap status, a docstring) carries ``NOT_INVOKED`` exactly when the services it names have no
production caller. Callers are found by tracing each instance over ``src/probos`` with the AST from
its construction or a parameter annotated with its class, not by matching a method name, so a
``.check(`` or ``.scan(`` on an untraced receiver does not count. The pin
fails in both directions: a service that gains a caller while its claim still says it is not
invoked, and a claim that drops the phrase (or says "wired") over a service nothing calls.
``RedTeamLead``, which does run, is the invoked control on the real tree.

What the resolver cannot see, by construction: a method name built at run time
(``getattr(obj, name)()`` with a computed ``name``); an instance or a bound entry method kept in a
container, a tuple target, ``setattr`` or a ``return``; an instance returned from a function; a
local captured by a nested function; calls inside the service's own module, except the declared
``via`` delegation; callers in ``ui/``, ``scripts/``, tests or a plugin loaded at run time.

A hand-off it cannot type is an escape: a holder passed as an argument (``**holder`` included), or
an entry method passed or assigned uncalled (``sink(holder.check)``, ``hook = getattr(holder,
"check")``); ``getattr(holder, "check")()`` with a literal name is a call. For a service with no
resolved caller an escape fails the test rather than counting as "not invoked"; for an invoked
service it changes nothing, because it could only add callers.

Known approximations (BF-926/927 review round 1; follow-up R10): a holder attribute is matched by
its name, not its owner, so once ``runtime.gate`` holds the service any ``other.gate.check()``
counts as a call (a false caller fails the test; it cannot hide one); a positional argument is an
escape even into a parameter annotated with the class (spell a typed hand-off as a keyword); a
typed parameter is keyed by its callable's short name (the class for ``__init__``) and the
parameter name, so a keyword hand-off to another callable with the same two names is exempt as if
typed, which can hide a hand-off.
"""

from __future__ import annotations

import ast
import functools
import importlib
import inspect
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from probos.config import GroundTruthConfig, SystemConfig

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC_ROOT = _REPO_ROOT / "src" / "probos"
_FINALIZE = _SRC_ROOT / "startup" / "finalize.py"
_ERA5 = "docs/development/roadmap-era-5-completed.md"

NOT_INVOKED = "built, not invoked"
_ACTIVE_WORDS = ("wired", "initialized", "active", "enforc")
_LOG_METHODS = frozenset({"debug", "info", "warning", "error", "exception", "critical"})
_NON_INVOKING = frozenset({"getattr", "hasattr", "isinstance", "id", "type", "repr", "bool", "len", "str"})
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z_0-9]*")


@dataclass(frozen=True)
class Service:
    module: str
    name: str
    entries: tuple[str, ...]  # methods whose call invokes it; () for a module-level function
    via: tuple[str, ...] = ()  # services that invoke it from inside its own module


@dataclass(frozen=True)
class Site:
    path: str
    line: int
    scope: str


@dataclass
class Resolution:
    state: str  # "invoked", "not invoked" or "escapes"
    calls: list[Site] = field(default_factory=list)
    escapes: list[Site] = field(default_factory=list)


@dataclass(frozen=True)
class _Module:
    name: str
    path: str
    tree: ast.Module


SERVICES: tuple[Service, ...] = (
    Service("probos.security.red_team_lead", "RedTeamLead", ("start", "run_campaign_now")),
    Service("probos.security.input_validator", "InputValidator", ("check",)),
    Service("probos.security.threat_detector", "ThreatDetector", ("scan",)),
    Service("probos.security.trust_integrity", "TrustIntegrityMonitor", ("analyze",)),
    Service("probos.governance.risk_tiers", "ActionRiskRegistry", ("check_authorization",)),
    Service("probos.mesh.disclosure", "DisclosureRouter", ("check_recipients", "filter_permitted")),
    Service("probos.consensus.quorum", "vote_on_intent", ()),
    Service("probos.security.autonomy_boundaries", "BoundaryViolationDetector", ("scan",)),
    Service("probos.security.classification", "ClassificationGate", ("check_disclosure",)),
    Service("probos.cognitive.validation_framework", "ReconciliationEscalator", ("reconcile",)),
    Service("probos.cognitive.ground_truth", "GroundTruthRejectionGate", ("evaluate",)),
    Service("probos.cognitive.ground_truth", "GroundTruthVerifier", ("verify",), via=("GroundTruthRejectionGate",)),
)
# Measured, not wished: a change here must come with the caller that justifies it.
EXPECTED_STATE = {service.name: "not invoked" for service in SERVICES} | {"RedTeamLead": "invoked"}


@dataclass(frozen=True)
class Claim:
    key: str
    services: tuple[str, ...]
    boot_prefixes: tuple[str, ...] = ()
    documents: tuple[str, ...] = ()  # "module:qualname"; a class is judged by its reference summary
    roadmap: tuple[tuple[str, str], ...] = ()  # (file, the start of the entry's line)


CLAIMS: tuple[Claim, ...] = (
    Claim("AD-455-red-team", ("RedTeamLead",), ("AD-455: RedTeamLead",)),
    Claim(
        "AD-455-screening", ("InputValidator", "ThreatDetector", "TrustIntegrityMonitor"), ("AD-455: InputValidator",),
        ("probos.config:SecurityConfig",), ((_ERA5, "**AD-455: Security Team"),),
    ),
    Claim("AD-676", ("ActionRiskRegistry",), ("AD-676:",), ("probos.config:RiskTierConfig",), ((_ERA5, "**AD-676: Action Risk Tiers**"),)),
    Claim("AD-679", ("DisclosureRouter",), ("AD-679:",), (), ((_ERA5, "**AD-679: Selective Disclosure Routing**"),)),
    Claim("AD-753", ("vote_on_intent",), (), ("probos.consensus.quorum:vote_on_intent",), (("docs/development/roadmap.md", "| AD-753 |"),)),
    Claim(
        "AD-511", ("BoundaryViolationDetector",), ("AD-511:",), ("probos.config:AutonomyBoundariesConfig",),
        ((_ERA5, "**AD-511: Agent Autonomy Boundaries"),),
    ),
    Claim(
        "AD-530", ("ClassificationGate",), ("AD-530:",), ("probos.config:ClassificationGateConfig",),
        ((_ERA5, "**AD-530: Information Classification Enforcement**"),),
    ),
    Claim(
        "AD-451", ("ReconciliationEscalator",), ("AD-451:",), ("probos.config:ValidationFrameworkConfig",),
        ((_ERA5, "**AD-451: Validation Framework Hardening**"),),
    ),
    Claim("AD-528b", ("GroundTruthRejectionGate",), ("AD-528b:",)),
    Claim(
        "AD-528", ("GroundTruthVerifier",), ("AD-528:",), ("probos.config:GroundTruthConfig",),
        ((_ERA5, "**AD-528: Ground-Truth Task Verification**"),),
    ),
)
BOOT_CLAIMS = tuple(claim for claim in CLAIMS if claim.boot_prefixes)
DOC_CLAIMS = tuple(claim for claim in CLAIMS if claim.documents or claim.roadmap)


# --- the resolver -------------------------------------------------------------------------------


def _parse_package(root: Path, package: str) -> tuple[_Module, ...]:
    modules = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        parts = [package, *relative.with_suffix("").parts]
        if parts[-1] == "__init__":
            parts.pop()
        modules.append(_Module(".".join(parts), relative.as_posix(), ast.parse(path.read_text(encoding="utf-8"))))
    return tuple(modules)


def _index(modules: tuple[_Module, ...]) -> tuple[list, list, list]:
    """Assignments, calls and functions of every module, each with its enclosing scope."""
    assigns: list = []
    calls: list = []
    functions: list = []
    for module in modules:
        stack: list[tuple[ast.AST, str]] = [(module.tree, "")]
        while stack:
            node, scope = stack.pop()
            for child in ast.iter_child_nodes(node):
                inner = scope
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if not isinstance(child, ast.ClassDef):
                        functions.append((module, scope, child))
                    inner = f"{scope}.{child.name}" if scope else child.name
                elif isinstance(child, (ast.Assign, ast.AnnAssign)):
                    assigns.append((module, scope, child))
                elif isinstance(child, ast.Call):
                    calls.append((module, scope, child))
                stack.append((child, inner))
    return assigns, calls, functions


def _callee(expr: ast.AST | None) -> str:
    if isinstance(expr, ast.Name):
        return expr.id
    if isinstance(expr, ast.Attribute):
        return expr.attr
    return ""


def _resolve_function(service: Service, index: tuple[list, list, list]) -> tuple[list[Site], list[Site]]:
    assigns, calls, _ = index
    sites: list[Site] = []
    escapes: list[Site] = []
    for module, scope, node in calls:
        if module.name == service.module:
            continue
        if _callee(node.func) == service.name:
            sites.append(Site(module.path, node.lineno, scope))
        handed = [*node.args, *(keyword.value for keyword in node.keywords)]
        if any(isinstance(arg, (ast.Name, ast.Attribute)) and _callee(arg) == service.name for arg in handed):
            escapes.append(Site(module.path, node.lineno, scope))  # the function handed on as a value
    for module, scope, node in assigns:
        value = node.value
        if module.name != service.module and isinstance(value, (ast.Name, ast.Attribute)) and _callee(value) == service.name:
            escapes.append(Site(module.path, node.lineno, scope))  # the function aliased
    return sites, escapes


def _resolve(service: Service, index: tuple[list, list, list]) -> tuple[list[Site], list[Site]]:
    """Calls of the service's entry methods on a resolved receiver, and untyped hand-offs."""
    if not service.entries:
        return _resolve_function(service, index)
    assigns, calls, functions = index
    attr_holders: set[str] = set()
    name_holders: set[tuple[str, str, str]] = set()
    typed: set[tuple[str, str]] = set()  # (callable, parameter) annotated with the service class

    for module, scope, node in functions:
        inner = f"{scope}.{node.name}" if scope else node.name
        owner = scope.rsplit(".", 1)[-1] if node.name == "__init__" and scope else node.name
        for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
            if arg.annotation is not None and service.name in _IDENTIFIER.findall(ast.unparse(arg.annotation)):
                typed.add((owner, arg.arg))
                if module.name != service.module:
                    name_holders.add((module.name, inner, arg.arg))

    def is_read(module: str, scope: str, expr: ast.AST) -> bool:
        if isinstance(expr, ast.Name):
            return (module, scope, expr.id) in name_holders
        if isinstance(expr, ast.Attribute):
            return expr.attr in attr_holders
        if isinstance(expr, ast.Call) and _callee(expr.func) == "getattr" and len(expr.args) >= 2:
            key = expr.args[1]
            return isinstance(key, ast.Constant) and key.value in attr_holders
        return False

    def is_entry(module: str, scope: str, expr: ast.AST) -> bool:
        """An entry method on a resolved receiver, called or not: ``holder.check`` or ``getattr(holder, "check")``."""
        if isinstance(expr, ast.Attribute):
            return expr.attr in service.entries and is_read(module, scope, expr.value)
        if isinstance(expr, ast.Call) and _callee(expr.func) == "getattr" and len(expr.args) >= 2:
            key = expr.args[1]
            return isinstance(key, ast.Constant) and key.value in service.entries and is_read(module, scope, expr.args[0])
        return False

    changed = True
    while changed:
        changed = False
        for module, scope, node in assigns:
            value = node.value
            if module.name == service.module or value is None:
                continue
            if not (_callee(getattr(value, "func", None)) == service.name or is_read(module.name, scope, value)):
                continue
            for target in node.targets if isinstance(node, ast.Assign) else [node.target]:
                if isinstance(target, ast.Name) and (module.name, scope, target.id) not in name_holders:
                    name_holders.add((module.name, scope, target.id))
                    changed = True
                elif isinstance(target, ast.Attribute) and target.attr not in attr_holders:
                    attr_holders.add(target.attr)
                    changed = True

    sites: list[Site] = []
    escapes: list[Site] = []
    for module, scope, node in calls:
        if module.name == service.module:
            continue
        func = node.func
        if is_entry(module.name, scope, func):
            sites.append(Site(module.path, node.lineno, scope))  # a resolved call
        callee = _callee(func)
        if callee in _NON_INVOKING:
            continue
        handed = [*node.args, *(keyword.value for keyword in node.keywords if (callee, keyword.arg) not in typed)]
        if any(is_read(module.name, scope, arg) for arg in handed):
            escapes.append(Site(module.path, node.lineno, scope))  # an untyped hand-off
        if any(is_entry(module.name, scope, arg) for arg in (*node.args, *(keyword.value for keyword in node.keywords))):
            escapes.append(Site(module.path, node.lineno, scope))  # an entry method handed on
    for module, scope, node in assigns:
        if module.name != service.module and node.value is not None and is_entry(module.name, scope, node.value):
            escapes.append(Site(module.path, node.lineno, scope))  # an entry method aliased
    return sites, escapes


def _blocked(services: tuple[Service, ...], invoked: set[str]) -> tuple[str, ...]:
    return tuple(f"{service.name}.{entry}" for service in services if service.name not in invoked for entry in service.entries)


def _inside(scope: str, blocked: tuple[str, ...]) -> bool:
    return any(scope == entry or scope.startswith(entry + ".") for entry in blocked)


def _classify(modules: tuple[_Module, ...], services: tuple[Service, ...]) -> dict[str, Resolution]:
    index = _index(modules)
    raw = {service.name: _resolve(service, index) for service in services}
    invoked: set[str] = set()
    changed = True
    while changed:
        changed = False
        blocked = _blocked(services, invoked)
        for service in services:
            sites, _ = raw[service.name]
            reached = any(not _inside(site.scope, blocked) for site in sites) or any(name in invoked for name in service.via)
            if service.name not in invoked and reached:
                invoked.add(service.name)
                changed = True
    blocked = _blocked(services, invoked)
    result: dict[str, Resolution] = {}
    for service in services:
        sites, escapes = raw[service.name]
        open_escapes = [site for site in escapes if not _inside(site.scope, blocked)]
        if service.name in invoked:
            state = "invoked"
        elif open_escapes:
            state = "escapes"
        else:
            state = "not invoked"
        result[service.name] = Resolution(state, sites, open_escapes)
    return result


@functools.lru_cache(maxsize=1)
def _production_states() -> dict[str, Resolution]:
    """Parsed and resolved once per process; every test only reads the result."""
    return _classify(_parse_package(_SRC_ROOT, "probos"), SERVICES)


def _quiet(claim: Claim) -> bool:
    """True when every service of the claim is not invoked; a mixed claim must be split."""
    states = {_production_states()[name].state for name in claim.services}
    assert "escapes" not in states, f"{claim.key}: classify the escape(s) before wording the claim"
    assert len(states) == 1, f"{claim.key}: its services are in different states {states}; split the claim"
    return states == {"not invoked"}


def _finalize_log_texts(prefixes: tuple[str, ...]) -> list[str]:
    tree = ast.parse(_FINALIZE.read_text(encoding="utf-8"))
    texts = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.args):
            continue
        logger_call = node.func.attr in _LOG_METHODS and isinstance(node.func.value, ast.Name) and node.func.value.id == "logger"
        first = node.args[0]
        if logger_call and isinstance(first, ast.Constant) and isinstance(first.value, str) and first.value.startswith(prefixes):
            texts.append(first.value)
    return texts


# --- the tests ----------------------------------------------------------------------------------


@pytest.mark.parametrize("service", SERVICES, ids=lambda service: service.name)
def test_each_service_state_is_resolved(service: Service) -> None:
    resolution = _production_states()[service.name]

    assert resolution.state == EXPECTED_STATE[service.name], (resolution.calls, resolution.escapes)


_FIXTURE = {
    "svc.py": "class Gate:\n    def check(self):\n        return True\n",
    "boot.py": "from pkg.svc import Gate\n\n\ndef boot(runtime):\n    gate = Gate()\n    runtime.gate = gate\n",
    "decoy.py": "def other(thing):\n    return thing.check()\n",
}
_FIXTURE_CASES = {
    "a decoy only": ({}, "not invoked"),
    "a resolved caller": ({"user.py": "def use(runtime):\n    held = getattr(runtime, 'gate', None)\n    return held.check()\n"}, "invoked"),
    "a typed hand-off": (
        {
            "holder.py": (
                "from pkg.svc import Gate\n\n\nclass Holder:\n    def __init__(self, gate: Gate):\n"
                "        self._held = gate\n\n    def run(self):\n        return self._held.check()\n"
            ),
            "wire.py": "from pkg.holder import Holder\n\n\ndef wire(runtime):\n    return Holder(gate=runtime.gate).run()\n",
        },
        "invoked",
    ),
    "an untyped hand-off": ({"hand.py": "def hand(runtime, sink):\n    sink(runtime.gate)\n"}, "escapes"),
    "a literal getattr call": ({"lit.py": "def use(runtime):\n    return getattr(runtime.gate, 'check')()\n"}, "invoked"),
    "an entry handed on": ({"cb.py": "def wire(runtime, bus):\n    bus.subscribe(runtime.gate.check)\n"}, "escapes"),
    "an entry aliased": ({"alias.py": "def wire(runtime):\n    hook = runtime.gate.check\n    return hook\n"}, "escapes"),
}


@pytest.mark.parametrize("case", sorted(_FIXTURE_CASES))
def test_the_resolver_tells_a_caller_from_a_decoy_and_an_escape(case: str, tmp_path: Path) -> None:
    extra, expected = _FIXTURE_CASES[case]
    package = tmp_path / "pkg"
    package.mkdir()
    for name, text in {**_FIXTURE, **extra}.items():
        (package / name).write_text(text, encoding="utf-8")

    resolution = _classify(_parse_package(package, "pkg"), (Service("pkg.svc", "Gate", ("check",)),))["Gate"]

    assert resolution.state == expected


@pytest.mark.parametrize("claim", BOOT_CLAIMS, ids=lambda claim: claim.key)
def test_each_boot_line_says_what_its_services_do(claim: Claim) -> None:
    quiet = _quiet(claim)
    texts = _finalize_log_texts(claim.boot_prefixes)

    assert texts, f"no finalize.py log call starts with {claim.boot_prefixes}"
    for text in texts:
        assert (NOT_INVOKED in text) is quiet, text
        if quiet:
            assert not any(word in text.lower() for word in _ACTIVE_WORDS), text


@pytest.mark.parametrize("claim", DOC_CLAIMS, ids=lambda claim: claim.key)
def test_each_description_says_what_its_services_do(claim: Claim) -> None:
    quiet = _quiet(claim)
    for target in claim.documents:
        module_name, _, qualname = target.partition(":")
        documented = getattr(importlib.import_module(module_name), qualname)
        doc = inspect.getdoc(documented) or ""
        text = doc.split("\n\n")[0] if inspect.isclass(documented) else doc  # the reference shows a model's summary
        assert (NOT_INVOKED in text) is quiet, f"{target}: {text!r}"
    for relative, head in claim.roadmap:
        lines = [line for line in (_REPO_ROOT / relative).read_text(encoding="utf-8").splitlines() if line.startswith(head)]
        assert len(lines) == 1, f"{relative}: {len(lines)} entries start {head!r}"
        assert (NOT_INVOKED in lines[0][:400]) is quiet, lines[0][:400]


@pytest.mark.asyncio
async def test_the_booted_vessel_prints_the_reworded_lines(tmp_path: Path) -> None:
    """The production path: a real boot prints each line, and its wording matches the callers."""
    from probos.runtime import ProbOSRuntime

    records: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    finalize_logger = logging.getLogger("probos.startup.finalize")
    handler, previous_level = _Capture(level=logging.INFO), finalize_logger.level
    finalize_logger.addHandler(handler)
    finalize_logger.setLevel(logging.INFO)
    # active_rejection_enabled is set only so the AD-528b line prints; no tracked config sets it
    # (system.yaml:1335 is false), and the gate it builds is never called, which is the claim.
    rt = ProbOSRuntime(config=SystemConfig(ground_truth=GroundTruthConfig(active_rejection_enabled=True)), data_dir=tmp_path)
    try:
        await rt.start()
    finally:
        await rt.stop()
        finalize_logger.removeHandler(handler)
        finalize_logger.setLevel(previous_level)

    for claim in BOOT_CLAIMS:
        printed = [message for message in records if message.startswith(claim.boot_prefixes)]
        assert printed, f"the boot printed no line starting {claim.boot_prefixes}"
        for message in printed:
            assert (NOT_INVOKED in message) is _quiet(claim), message
````

### 7.12 `src/probos/config_models/crew.py` (M2: the leak guard)

SEARCH:
````python
    enforce_provenance: bool = False    # AD-607b opt-in: reject provenance-gap episodes from recall
    enforce_leak_guard: bool = False    # AD-607d opt-in: redact response when leak suspected
    enforce_store: bool = False         # AD-607h opt-in: reject prompt-injection at store time
````
REPLACE:
````python
    enforce_provenance: bool = False    # AD-607b opt-in: reject provenance-gap episodes from recall
    # BF-926 (#1656): enforce_leak_guard (AD-607d) is deleted. Nothing read it and the leak guard
    # never redacts (it only emits MEMORY_LEAK_SUSPECTED); a config that still sets it loads.
    enforce_store: bool = False         # AD-607h opt-in: reject prompt-injection at store time
````

### 7.13 `src/probos/config.py` (M2: F17 and AD-753's fields)

Pair 1 (`CognitiveConfig`):

SEARCH:
````python
    dag_execution_timeout_seconds: float = 60.0
    use_consensus_for_writes: bool = True
    max_concurrent_tasks: int = 8
````
REPLACE:
````python
    dag_execution_timeout_seconds: float = 60.0
    use_consensus_for_writes: bool = Field(default=True, description="Inert: no production code reads this field to act on it (BF-926, #1656). Whether a write needs consensus is decided per intent (IntentDescriptor.requires_consensus); a candidate for #1659.")
    max_concurrent_tasks: int = 8
````

Pair 2 (`FederationConfig`, memory portability):

SEARCH:
````python
    memory_policy: str = "clean_room"
    # AD-443c: Tag whitelist for SELECTIVE memory policy. Ignored for the
    # other two policies. Empty list with SELECTIVE means no episodes pass.
    memory_policy_selective_tags: list[str] = []
````
REPLACE:
````python
    memory_policy: str = Field(default="clean_room", description="Inert: no production code reads this field to act on it (BF-926, #1656). No transfer path applies it (apply_memory_policy has no caller); the validator still rejects an unknown policy. A candidate for #1659.")
    # AD-443c: Tag whitelist for SELECTIVE memory policy. Ignored for the
    # other two policies. Empty list with SELECTIVE means no episodes pass.
    memory_policy_selective_tags: list[str] = Field(default=[], description="Inert: no production code reads this field to act on it (BF-926, #1656); it belongs to memory_policy, which nothing applies. A candidate for #1659.")
````

(`default=[]` keeps the existing default form, which the facade baseline records; Pydantic copies a mutable default per instance. A `default_factory` would be a facade contract change outside this BF.)

Pair 3 (`FederationConfig`, trust floors):

SEARCH:
````python
    min_peer_trust_score: float = 0.0
    # AD-607g federation outbound privacy filter. Default ``shared_trust``
    # honors the AD-479b peer-trust ranking surface that W91 shipped.
    memory_access_policy: str = "shared_trust"
    shared_trust_min_score: float = Field(default=0.5, ge=0.0, le=1.0)
````
REPLACE:
````python
    min_peer_trust_score: float = Field(default=0.0, description="Inert: no production code reads this field to act on it (BF-926, #1656). This floor ranks or refuses no peer; a candidate for #1659.")
    # AD-607g federation outbound privacy filter. Default ``shared_trust``
    # honors the AD-479b peer-trust ranking surface that W91 shipped.
    memory_access_policy: str = "shared_trust"
    shared_trust_min_score: float = Field(default=0.5, ge=0.0, le=1.0, description="Inert: no production code reads this field to act on it (BF-926, #1656). The shared_trust policy filters by episode classification only, with no trust floor; a candidate for #1659.")
````

Pair 4 (`SecurityConfig`, AD-753):

SEARCH:
````python
    # AD-753: unattended permission posture for personal-desktop scope.
    permission_mode: Literal["manual", "autopilot"] = "manual"
    policy_engine_class: str = "NullPolicyEngine"
````
REPLACE:
````python
    # AD-753: unattended permission posture for personal-desktop scope.
    permission_mode: Literal["manual", "autopilot"] = Field(default="manual", description="Inert: no production code reads this field to act on it (BF-926, BF-927; #1656, #1657). The AD-753 gate (vote_on_intent) has no caller, so no mode gates any intent; a candidate for #1659.")
    policy_engine_class: str = Field(default="NullPolicyEngine", description="Inert: no production code reads this field to act on it (BF-926, BF-927; #1656, #1657). No engine is loaded from it and the AD-753 gate has no caller; a candidate for #1659.")
````

### 7.14 `src/probos/config_models/cognition.py` (M2: F16)

Pair 1 (`WorkingMemoryConfig`, 12 of 13 fields unread):

SEARCH:
````python
class WorkingMemoryConfig(BaseModel):
    """AD-573: Unified agent working memory configuration."""

    token_budget: int = 3000  # Max tokens for working memory context
    max_recent_actions: int = 10  # Ring buffer capacity
    max_recent_observations: int = 5
    max_recent_conversations: int = 5
    max_events: int = 10
    proactive_budget: int = 1500  # Lower budget for proactive (supplemental)
    stale_threshold_hours: float = 24.0  # Entries older than this pruned on restore
    conclusion_ttl_seconds: float = 1800.0
    max_conclusions: int = 20
    duty_budget: int = 600
    social_budget: int = 800
    ship_budget: int = 800
    engagement_budget: int = 800
````
REPLACE:
````python
class WorkingMemoryConfig(BaseModel):
    """AD-573: Unified agent working memory configuration. BF-926 (#1656): only stale_threshold_hours is read; AgentWorkingMemory uses its own defaults for everything else."""

    token_budget: int = Field(default=3000, description="Inert: no production code reads this field to act on it (BF-926, #1656); AgentWorkingMemory uses its own default.")
    max_recent_actions: int = Field(default=10, description="Inert: no production code reads this field to act on it (BF-926, #1656); AgentWorkingMemory uses its own default.")
    max_recent_observations: int = Field(default=5, description="Inert: no production code reads this field to act on it (BF-926, #1656); AgentWorkingMemory uses its own default.")
    max_recent_conversations: int = Field(default=5, description="Inert: no production code reads this field to act on it (BF-926, #1656); AgentWorkingMemory uses its own default.")
    max_events: int = Field(default=10, description="Inert: no production code reads this field to act on it (BF-926, #1656); AgentWorkingMemory uses its own default.")
    proactive_budget: int = Field(default=1500, description="Inert: no production code reads this field to act on it (BF-926, #1656); AgentWorkingMemory uses its own default.")
    stale_threshold_hours: float = Field(default=24.0, description="Read at warm boot: restored working-memory entries older than this are dropped.")
    conclusion_ttl_seconds: float = Field(default=1800.0, description="Inert: no production code reads this field to act on it (BF-926, #1656); AgentWorkingMemory uses its own default.")
    max_conclusions: int = Field(default=20, description="Inert: no production code reads this field to act on it (BF-926, #1656); AgentWorkingMemory uses its own default.")
    duty_budget: int = Field(default=600, description="Inert: no production code reads this field to act on it (BF-926, #1656); AgentWorkingMemory uses its own default.")
    social_budget: int = Field(default=800, description="Inert: no production code reads this field to act on it (BF-926, #1656); AgentWorkingMemory uses its own default.")
    ship_budget: int = Field(default=800, description="Inert: no production code reads this field to act on it (BF-926, #1656); AgentWorkingMemory uses its own default.")
    engagement_budget: int = Field(default=800, description="Inert: no production code reads this field to act on it (BF-926, #1656); AgentWorkingMemory uses its own default.")
````

Pair 2:

SEARCH:
````python
class MemoryBudgetConfig(BaseModel):
    """AD-573: Memory budget accounting across recall tiers."""
````
REPLACE:
````python
class MemoryBudgetConfig(BaseModel):
    """AD-573: Memory budget accounting across recall tiers. Inert: no production code reads this section to act on it (BF-926, #1656): nothing passes it to CognitiveAgent's memory_budget_config, so enabled and the budgets change nothing (#1324)."""
````

Pair 3:

SEARCH:
````python
class MetabolismConfig(BaseModel):
    """AD-670: Working memory metabolism — active lifecycle management."""
````
REPLACE:
````python
class MetabolismConfig(BaseModel):
    """AD-670: Working memory metabolism — active lifecycle management. Inert: no production code reads this section to act on it (BF-926, #1656): nothing constructs MemoryMetabolism, so enabled and every threshold change nothing (#1324)."""
````

Pair 4:

SEARCH:
````python
class PinnedKnowledgeConfig(BaseModel):
    """AD-579a: Pinned knowledge buffer configuration."""
````
REPLACE:
````python
class PinnedKnowledgeConfig(BaseModel):
    """AD-579a: Pinned knowledge buffer configuration. Inert: no production code reads this section to act on it (BF-926, #1656): nothing passes it to AgentWorkingMemory's pinned_config, so no pinned-knowledge buffer is built (#1324)."""
````

Pair 5:

SEARCH:
````python
class TemporalValidityConfig(BaseModel):
    """AD-579b: Temporal validity windows for episodic memory."""
````
REPLACE:
````python
class TemporalValidityConfig(BaseModel):
    """AD-579b: Temporal validity windows for episodic memory. Inert: no production code reads this section to act on it (BF-926, #1656): enabled and default_validity_hours change nothing (#1324)."""
````

### 7.15 `src/probos/cognitive/memory_security.py` (M2, unpinned docstring)

SEARCH:
````python
v1 is OBSERVATIONAL by default. Opt-in enforcement via MemorySecurityConfig
flags (enforce_recall / enforce_provenance / enforce_store / enforce_leak) —
all default-False per the AD-695 + W82 + W88 + W91 default-False precedent.
````
REPLACE:
````python
v1 is OBSERVATIONAL by default. Opt-in enforcement via MemorySecurityConfig
flags (enforce_recall / enforce_provenance / enforce_store) — all default-False
per the AD-695 + W82 + W88 + W91 default-False precedent. The leak guard has no
enforce flag (BF-926, #1656): it only emits MEMORY_LEAK_SUSPECTED.
````

### 7.16 `config/system.yaml` (M2: the tracked file only)

Pair 1 (F17, `cognitive`):

SEARCH:
````yaml
  use_consensus_for_writes: true
  max_concurrent_tasks: 8
````
REPLACE:
````yaml
  use_consensus_for_writes: true  # BF-926 (#1656): inert, no production code reads it
  max_concurrent_tasks: 8
````

Pair 2 (F26):

SEARCH:
````yaml
  captain_card_max_tokens: 500
  captain_card_refresh_min_interval_seconds: 3600
health_probe_interval_seconds: 30.0
````
REPLACE:
````yaml
  captain_card_max_tokens: 500
health_probe_interval_seconds: 30.0
````

Pair 3 (`federation`, memory portability):

SEARCH:
````yaml
  memory_policy: clean_room
  memory_policy_selective_tags: []
````
REPLACE:
````yaml
  memory_policy: clean_room  # BF-926 (#1656): inert, no production code reads it
  memory_policy_selective_tags: []  # BF-926 (#1656): inert, no production code reads it
````

Pair 4 (`federation`, trust floors):

SEARCH:
````yaml
  min_peer_trust_score: 0.0
  memory_access_policy: shared_trust
  shared_trust_min_score: 0.5
````
REPLACE:
````yaml
  min_peer_trust_score: 0.0  # BF-926 (#1656): inert, no production code reads it
  memory_access_policy: shared_trust
  shared_trust_min_score: 0.5  # BF-926 (#1656): inert, no production code reads it
````

Pair 5 (`security.memory`, the deleted key):

SEARCH:
````yaml
    enforce_provenance: false
    enforce_leak_guard: false
    enforce_store: false
````
REPLACE:
````yaml
    enforce_provenance: false
    enforce_store: false
````

Pair 6 (`security`, AD-753):

SEARCH:
````yaml
  permission_mode: manual
  policy_engine_class: NullPolicyEngine
````
REPLACE:
````yaml
  permission_mode: manual  # BF-926 (#1656): inert, no production code reads it
  policy_engine_class: NullPolicyEngine  # BF-926 (#1656): inert, no production code reads it
````

Pair 7 (F16, `working_memory`):

SEARCH:
````yaml
working_memory:
  token_budget: 3000
````
REPLACE:
````yaml
# BF-926 (#1656): only stale_threshold_hours is read; the other keys change nothing.
working_memory:
  token_budget: 3000
````

Pair 8 (F16, the four sections):

SEARCH:
````yaml
memory_budget:
  enabled: true
  total_budget_tokens: 4650
````
REPLACE:
````yaml
# BF-926 (#1656): inert. No production code acts on this section; enabled: true turns nothing on (#1324).
memory_budget:
  enabled: true
  total_budget_tokens: 4650
````

SEARCH:
````yaml
metabolism:
  enabled: true
  decay_half_life_seconds: 3600.0
````
REPLACE:
````yaml
# BF-926 (#1656): inert. No production code acts on this section; enabled: true turns nothing on (#1324).
metabolism:
  enabled: true
  decay_half_life_seconds: 3600.0
````

SEARCH:
````yaml
pinned_knowledge:
  enabled: true
  max_tokens: 150
````
REPLACE:
````yaml
# BF-926 (#1656): inert. No production code acts on this section; enabled: true turns nothing on (#1324).
pinned_knowledge:
  enabled: true
  max_tokens: 150
````

SEARCH:
````yaml
temporal_validity:
  enabled: true
  default_validity_hours: 0.0
````
REPLACE:
````yaml
# BF-926 (#1656): inert. No production code acts on this section; enabled: true turns nothing on (#1324).
temporal_validity:
  enabled: true
  default_validity_hours: 0.0
````

### 7.17 `docs/development/config-profiles.yaml` (M2)

Pair 1 (the classified row of the deleted flag):

SEARCH:
````yaml
- path: security.memory.enforce_leak_guard
  kind: security-control
  profiles: []
  evidence_to_promote: Needs a test that constructs MemorySecurityConfig(enforce_leak_guard=True)
    and shows a response redacted. TestMemoryLeakageGuard exercises detection; no test arms
    the enforcement flag. Enumerated 2026-09-02.
  external_dependency: null
  requires: []
  conflicts_with: []
- path: security_infra.credential_tier_enforcement
````
REPLACE:
````yaml
- path: security_infra.credential_tier_enforcement
````

Pair 2 (its conflict edge, the manifest's only one):

SEARCH:
````yaml
  conflicts_with:
  - security.memory.enforce_leak_guard
  conflict_rationale: 'The leak guard redacts a response when memory leakage is suspected;
    this flag publishes raw episode content across the social-verification boundary. Arming
    both asserts two contradictory postures over the same data, which is the ''mutually exclusive
    research and security modes'' case #1121 names. Declared one-directionally from the exposing
    flag, so an operator who arms only the guard is unaffected.'
````
REPLACE:
````yaml
  # BF-926 (#1656): its conflict with security.memory.enforce_leak_guard went with that flag,
  # which redacted nothing.
  conflicts_with: []
````

Pair 3 (the census header; `test_ad1185_*:857-859` pins `default_false`):

SEARCH:
````yaml
  measured_at_commit: ba45c61f5550e110aab4b00441d78f3f590ba513 plus the BF-924 candidate, every count
    re-measured (the base measured 452, 226, 226, 85 and 141 with this instrument; three of the
    figures kept since AD-1198 had drifted)
  instrument: scripts/check_config_profiles.py default_false_flags() -- walks the nested Pydantic
    model tree from SystemConfig, each model type visited once per path, cycle-guarded. Armed
    counts compare against config/system.yaml loaded through load_config.
  boolean_fields_reachable: 449
  default_false: 225
  default_true: 224
  default_false_armed_by_system_yaml: 85
  default_false_never_armed: 140
````
REPLACE:
````yaml
  measured_at_commit: the BF-924 merge plus the BF-926/BF-927 candidate, every count re-measured
    with this instrument (BF-926 deletes security.memory.enforce_leak_guard, a default-False
    boolean no tracked config arms; BF-924's candidate measured 449, 225, 224, 85 and 140)
  instrument: scripts/check_config_profiles.py default_false_flags() -- walks the nested Pydantic
    model tree from SystemConfig, each model type visited once per path, cycle-guarded. Armed
    counts compare against config/system.yaml loaded through load_config.
  boolean_fields_reachable: 448
  default_false: 224
  default_true: 224
  default_false_armed_by_system_yaml: 85
  default_false_never_armed: 139
````

(The orchestrator re-measures the five figures with BF-924's probe on the applied tree and corrects them before commit; a differing figure is not a hard stop, but the header must hold measured values.)

### 7.18 New file: `scripts/check_config_readers.py` (M2)

````python
"""BF-926 (#1656): report config fields no production code reads to act on, and yaml keys no field declares.

REPORT-ONLY: this check warns and never fails. Its exit status is 0 on every input -- a missing
or malformed yaml file, a source file that does not parse, an unknown or incomplete argument --
because nothing may gate on it until the Captain decides to enforce it (#1656). It is a separate
command; ``scripts/run_test_gate.py`` does not run it.

A field counts as read when its name occurs in ``src/probos`` outside the declaring modules
(``config.py`` and ``config_models/``) as an attribute name, a string constant or a call keyword.
That is a name match, not a resolved receiver (the shape of vulture's dead-code scan), so it
under-reports: a generic name such as ``enabled`` counts as read wherever any object has that
attribute. It cannot see a name built at run time, a dump read by key in ``ui/``, or a model
nested inside a list or dict field. Generic config I/O is not a reader here: the config API
(``routers/config.py``) dumps and rewrites every field without naming one, so "unread" and
"inert" mean that no code names the field to act on it, not that no code touches its value.

A field is inert when its ``Field(description=...)`` or the first paragraph of its model's
docstring contains ``INERT_MARKER``. Inert fields are listed apart from the unread ones; an inert
field whose name does occur is listed again for a check by hand.

Usage::

    python -P scripts/check_config_readers.py [--yaml PATH] [--src PATH]
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

INERT_MARKER = "Inert: no production code reads this"
PREFIX = "CONFIG READERS (report-only): "
DEFAULT_YAML = _REPO_ROOT / "config" / "system.yaml"
DEFAULT_SOURCE = _SRC / "probos"
DECLARING = ("config.py", "config_models")


@dataclass
class Report:
    """What one run found, in model and file order."""

    unread: list[str] = field(default_factory=list)
    inert: list[str] = field(default_factory=list)
    inert_referenced: list[str] = field(default_factory=list)
    orphan_yaml_keys: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _is_model(annotation: Any) -> bool:
    return isinstance(annotation, type) and hasattr(annotation, "model_fields")


def _summary(model: type) -> str:
    return (model.__doc__ or "").strip().split("\n\n")[0]


def iter_leaves(model: type, prefix: str = "", seen: tuple[type, ...] = ()) -> list[tuple[str, str, bool]]:
    """``(dotted path, field name, inert)`` for every leaf field reachable from ``model``."""
    leaves: list[tuple[str, str, bool]] = []
    section_inert = INERT_MARKER in _summary(model)
    for name, info in model.model_fields.items():
        path = f"{prefix}{name}"
        if _is_model(info.annotation) and info.annotation not in (*seen, model):
            leaves.extend(iter_leaves(info.annotation, f"{path}.", (*seen, model)))
            continue
        inert = section_inert or INERT_MARKER in (info.description or "")
        leaves.append((path, name, inert))
    return leaves


def referenced_names(source_root: Path, declaring: tuple[str, ...] = DECLARING) -> tuple[set[str], list[str]]:
    """Every attribute name, string constant and call keyword outside the declaring modules."""
    names: set[str] = set()
    warnings: list[str] = []
    if not source_root.is_dir():
        warnings.append(f"source root {source_root.as_posix()} is not a directory")
    for path in sorted(source_root.rglob("*.py")):
        relative = path.relative_to(source_root)
        if relative.parts[0] in declaring:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, ValueError, UnicodeDecodeError, OSError) as exc:
            warnings.append(f"skipped {relative.as_posix()}: {type(exc).__name__}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                names.add(node.attr)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                names.add(node.value)
            elif isinstance(node, ast.keyword) and node.arg:
                names.add(node.arg)
    return names, warnings


def _accepted(info: Any, name: str) -> set[str]:
    """The yaml keys a field accepts: its name and any alias."""
    accepted = {name}
    validation_alias = getattr(info, "validation_alias", None)
    for alias in (getattr(info, "alias", None), validation_alias):
        if isinstance(alias, str):
            accepted.add(alias)
    accepted.update(choice for choice in getattr(validation_alias, "choices", None) or () if isinstance(choice, str))
    return accepted


def orphan_keys(model: type, document: Any, prefix: str = "") -> list[str]:
    """Dotted yaml keys under ``model`` that no field of it accepts."""
    if not isinstance(document, dict):
        return []
    fields_by_key = {key: info for name, info in model.model_fields.items() for key in _accepted(info, name)}
    orphans: list[str] = []
    for key, value in document.items():
        path = f"{prefix}{key}"
        info = fields_by_key.get(key)
        if info is None:
            orphans.append(path)
        elif _is_model(info.annotation):
            orphans.extend(orphan_keys(info.annotation, value, f"{path}."))
    return orphans


def build_report(model: type, source_root: Path, yaml_document: Any, declaring: tuple[str, ...] = DECLARING) -> Report:
    report = Report()
    names, report.warnings = referenced_names(Path(source_root), declaring)
    for path, name, inert in iter_leaves(model):
        if inert:
            report.inert.append(path)
            if name in names:
                report.inert_referenced.append(path)
        elif name not in names:
            report.unread.append(path)
    report.orphan_yaml_keys = orphan_keys(model, yaml_document)
    return report


def render(report: Report) -> str:
    lines = [
        f"{PREFIX}{len(report.unread)} unread field(s), {len(report.inert)} inert, "
        f"{len(report.orphan_yaml_keys)} yaml key(s) with no field; this check warns and never fails"
    ]
    for label, items in (
        ("unread", report.unread),
        ("inert", report.inert),
        ("inert, name referenced (check by hand)", report.inert_referenced),
        ("yaml key with no field", report.orphan_yaml_keys),
        ("warning", report.warnings),
    ):
        lines.extend(f"  {label}: {item}" for item in items)
    return "\n".join(lines)


def _read_yaml(path: Path, warnings: list[str]) -> Any:
    import yaml

    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        warnings.append(f"yaml not read ({path.as_posix()}): {type(exc).__name__}")
        return None


def main(argv: list[str] | None = None) -> int:
    """Print the report. Returns 0 on every path: a check that cannot run says so and passes."""
    try:
        parser = argparse.ArgumentParser(description="Report config fields no production code names to act on (report-only).")
        parser.add_argument("--yaml", default=str(DEFAULT_YAML), help="config file whose keys are checked")
        parser.add_argument("--src", default=str(DEFAULT_SOURCE), help="source tree searched for readers")
        args, unknown = parser.parse_known_args(argv)
    except SystemExit as exc:  # argparse exits on a malformed command line; this check never does
        if exc.code not in (0, None):
            print(f"{PREFIX}could not parse the arguments (argparse exit {exc.code}); nothing checked")
        return 0
    try:
        from probos.config import SystemConfig

        yaml_warnings: list[str] = []
        document = _read_yaml(Path(args.yaml), yaml_warnings)
        report = build_report(SystemConfig, Path(args.src), document)
        report.warnings.extend(yaml_warnings)
        report.warnings.extend(f"ignored argument {item!r}" for item in unknown)
        print(render(report))
    except Exception as exc:  # report-only: a failure to report is itself only reported
        print(f"{PREFIX}could not run: {type(exc).__name__}: {exc}")
    return 0  # report-only: the status never reflects the findings


if __name__ == "__main__":
    raise SystemExit(main())
````

### 7.19 New file: `tests/test_bf926_config_readers.py` (M2)

````python
"""BF-926 (#1656): config fields that promise behaviour nothing reads are marked inert or removed,
and a report-only check lists fields no production code reads and yaml keys no field declares.

The check is loaded by path, as it is run. The fixture model, source tree and yaml are the check's
inputs, not doubles of production code; the real-tree cases run it on ``SystemConfig``,
``src/probos`` and the tracked ``config/system.yaml``, so each inert marker is pinned on the model
that carries it.
"""

from __future__ import annotations

import functools
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel, Field

from probos.config import MemorySecurityConfig, SystemConfig

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "check_config_readers.py"


def _load_checker():
    spec = importlib.util.spec_from_file_location("_bf926_config_readers", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


checker = _load_checker()
MARK = checker.INERT_MARKER


class _Leaf(BaseModel):
    read_field: int = 1
    unread_field: int = 2
    inert_field: int = Field(default=3, description=f"{MARK} field. Fixture.")
    inert_but_named: int = Field(default=4, description=f"{MARK} field. Fixture.")


class _DormantSection(BaseModel):
    """Fixture section. Inert: no production code reads this section."""

    knob: int = 5


class _Root(BaseModel):
    leaf: _Leaf = _Leaf()
    dormant: _DormantSection = _DormantSection()


def test_the_report_separates_read_unread_inert_and_orphan_keys(tmp_path: Path) -> None:
    assert MARK in (_DormantSection.__doc__ or "")  # premise: the fixture section carries the marker
    source = tmp_path / "src"
    (source / "pkg").mkdir(parents=True)
    (source / "pkg" / "reader.py").write_text(
        "def use(cfg):\n    return cfg.leaf.read_field, getattr(cfg, 'inert_but_named')\n", encoding="utf-8"
    )
    # A declaring module: a mention here is the declaration, not a reader.
    (source / "config.py").write_text("def declare(cfg):\n    return cfg.unread_field\n", encoding="utf-8")
    document = {"leaf": {"read_field": 1, "ghost": 2}, "dormant": {"knob": 5}, "stray_section": {"x": 1}}

    report = checker.build_report(_Root, source, document)

    assert report.unread == ["leaf.unread_field"]
    assert report.inert == ["leaf.inert_field", "leaf.inert_but_named", "dormant.knob"]
    assert report.inert_referenced == ["leaf.inert_but_named"]
    assert report.orphan_yaml_keys == ["leaf.ghost", "stray_section"]
    assert report.warnings == []


_EXIT_CASES = {
    "the real tree": [],
    "a missing yaml file": ["--yaml", "{tmp}/absent.yaml"],
    "a malformed yaml file": ["--yaml", "{tmp}/broken.yaml"],
    "a source file that does not parse": ["--src", "{tmp}/src"],
    "an unknown argument": ["--strict"],
    "an argument without its value": ["--yaml"],
}


@pytest.mark.parametrize("case", sorted(_EXIT_CASES))
def test_the_check_exits_zero_on_every_input(case: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "broken.yaml").write_text("leaf: [unclosed\n", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "broken.py").write_text("def (:\n", encoding="utf-8")
    argv = [part.format(tmp=tmp_path.as_posix()) for part in _EXIT_CASES[case]]

    assert checker.main(argv) == 0

    assert capsys.readouterr().out.startswith(checker.PREFIX)


def test_the_command_line_exit_status_is_zero(tmp_path: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "-P", str(_SCRIPT), "--yaml", str(tmp_path / "absent.yaml")],
        capture_output=True, text=True, timeout=300, cwd=_REPO_ROOT,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.startswith(checker.PREFIX)


_WORKING_MEMORY_INERT = (
    "token_budget", "max_recent_actions", "max_recent_observations", "max_recent_conversations", "max_events",
    "proactive_budget", "conclusion_ttl_seconds", "max_conclusions", "duty_budget", "social_budget", "ship_budget",
    "engagement_budget",
)
_SECTIONS_INERT = {
    "memory_budget": ("enabled", "total_budget_tokens", "l0_budget", "l1_budget", "l2_budget", "l3_budget"),
    "metabolism": (
        "enabled", "decay_half_life_seconds", "forget_threshold", "min_entries_per_buffer", "audit_enabled",
        "cycle_interval_seconds", "triage_fullness_threshold", "triage_base_score",
    ),
    "pinned_knowledge": ("enabled", "max_tokens", "max_pins", "default_ttl_seconds"),
    "temporal_validity": ("enabled", "default_validity_hours"),
}
BF926_INERT = (
    "cognitive.use_consensus_for_writes",
    "federation.memory_policy",
    "federation.memory_policy_selective_tags",
    "federation.min_peer_trust_score",
    "federation.shared_trust_min_score",
    "security.permission_mode",
    "security.policy_engine_class",
    *(f"working_memory.{name}" for name in _WORKING_MEMORY_INERT),
    *(f"{section}.{name}" for section, names in _SECTIONS_INERT.items() for name in names),
)


@functools.lru_cache(maxsize=1)
def _real_report():
    """Built once per process from the real model, source and tracked yaml; tests only read it."""
    document = yaml.safe_load(checker.DEFAULT_YAML.read_text(encoding="utf-8"))
    return checker.build_report(SystemConfig, checker.DEFAULT_SOURCE, document)


@pytest.mark.parametrize("path", BF926_INERT)
def test_the_real_config_reports_each_bf926_field_as_inert(path: str) -> None:
    report = _real_report()

    assert path in report.inert
    assert path not in report.unread


def test_the_leak_guard_flag_is_gone_and_a_config_that_sets_it_still_loads() -> None:
    assert "enforce_leak_guard" not in MemorySecurityConfig.model_fields

    cfg = SystemConfig.model_validate({
        "security": {"memory": {"enforce_leak_guard": True, "enforce_store": True}},
        "cognitive": {"captain_card_refresh_min_interval_seconds": 60},
    })

    assert cfg.security.memory.enforce_store is True
    assert "enforce_leak_guard" not in cfg.security.memory.model_dump()


def test_the_tracked_yaml_carries_no_key_bf926_removed() -> None:
    report = _real_report()

    assert "cognitive.captain_card_refresh_min_interval_seconds" not in report.orphan_yaml_keys
    assert "security.memory.enforce_leak_guard" not in report.orphan_yaml_keys
    assert "working_memory.stale_threshold_hours" not in report.inert  # the one read field is not marked
````

### 7.20 `tests/test_ad1270e2g_crew_models.py` (M2: the pre-move dump)

SEARCH:
````python
    'MemorySecurityConfig': {   'enforce_recall': False,
                                'enforce_provenance': False,
                                'enforce_leak_guard': False,
                                'enforce_store': False,
````
REPLACE:
````python
    'MemorySecurityConfig': {   'enforce_recall': False,
                                'enforce_provenance': False,
                                # BF-926 (#1656): enforce_leak_guard is deleted; it promised redaction nothing performed.
                                'enforce_store': False,
````

### 7.21 `tests/test_ad607_memory_security.py` (M2: the deleted field's default)

SEARCH:
````python
        assert cfg.enforce_provenance is False
        assert cfg.enforce_leak_guard is False
        assert cfg.enforce_store is False
````
REPLACE:
````python
        assert cfg.enforce_provenance is False
        # BF-926 (#1656): the leak-guard flag is deleted (nothing read it; the guard only observes).
        assert "enforce_leak_guard" not in MemorySecurityConfig.model_fields
        assert cfg.enforce_store is False
````

### 7.22 `tests/test_ad1185_config_profiles.py` (M2: the conflict fixture, D3)

Pair 1:

SEARCH:
````python
def test_a_conflicting_profile_raises_at_parse(tmp_path: Path) -> None:
    _write_profile(
        tmp_path,
        "probe",
        {
            "profile": {
                "id": "probe",
                "version": 1,
                "description": "deliberate conflict",
                "arm": "experiment",
            },
            "overrides": {
                "social_verification": {"expose_episode_content": True},
                "security": {"memory": {"enforce_leak_guard": True}},
            },
        },
    )
    with pytest.raises(ProfileConflictError) as excinfo:
        load_profile("probe", profile_dir=tmp_path)
    assert "conflicts with" in str(excinfo.value)
````
REPLACE:
````python
def test_a_conflicting_profile_raises_at_parse(tmp_path: Path) -> None:
    # BF-926 (#1656): the committed manifest's only conflict edge named
    # security.memory.enforce_leak_guard, which is deleted (it enforced nothing). The parse-time
    # conflict check is still proven, on a one-row fixture manifest joining two real booleans,
    # read through load_profile's own manifest_path.
    manifest = tmp_path / "manifest" / "config-profiles.yaml"
    manifest.parent.mkdir()
    manifest.write_text(
        yaml.safe_dump({"flags": [{"path": "federation.enabled", "conflicts_with": ["federation.tls.enabled"]}]}),
        encoding="utf-8",
    )
    _write_profile(
        tmp_path,
        "probe",
        {
            "profile": {
                "id": "probe",
                "version": 1,
                "description": "deliberate conflict",
                "arm": "experiment",
            },
            "overrides": {"federation": {"enabled": True, "tls": {"enabled": True}}},
        },
    )
    with pytest.raises(ProfileConflictError) as excinfo:
        load_profile("probe", profile_dir=tmp_path, manifest_path=manifest)
    assert "conflicts with" in str(excinfo.value)
````

Pair 2:

SEARCH:
````python
    def mutate(document: dict[str, Any]) -> None:
        for row in document["flags"]:
            if row.get("conflicts_with"):
                row.pop("conflict_rationale", None)
````
REPLACE:
````python
    def mutate(document: dict[str, Any]) -> None:
        # BF-926 (#1656): the committed manifest declares no conflict any more, so the mutation
        # adds one with no rationale; the check must still refuse an unexplained conflict.
        row = document["flags"][0]
        row["conflicts_with"] = ["federation.tls.enabled"]
        row.pop("conflict_rationale", None)
````

### 7.23 `tests/test_ad1270e1_config_facade.py` (M2: the measured field count)

SEARCH:
````python
    # BF-924 (#1654) removes CounselorConfig's four unread fields: enabled, profile_retention_days,
    # alert_on_red and alert_on_yellow (1880 -> 1876).
    assert counts["field_definitions"] == 1876  # AD-1206 intentionally adds github_repository.
````
REPLACE:
````python
    # BF-924 (#1654) removes CounselorConfig's four unread fields: enabled, profile_retention_days,
    # alert_on_red and alert_on_yellow (1880 -> 1876).
    # BF-926 (#1656) removes security.memory.enforce_leak_guard, which nothing read (1876 -> 1875).
    assert counts["field_definitions"] == 1875  # AD-1206 intentionally adds github_repository.
````

### 7.24 `tests/fixtures/ad1152_agentic_off_golden.json` (M2: the default-config digest, A1)

The AD-1152 OFF golden pins the SHA-256 of `SystemConfig().model_dump()` (`test_ad1152_*:215-218`, `:500`) and of the whole observation (`:516`, `:570`); §7.12's deletion moves both. Each test-side addition is popped at `:220-314`; a deleted field is refreshed here, as BF-924 did. Both values are derived and the test checks them in full: applied by tool, no review round, in M2's commit (not M1's: M1 keeps the field). Only lines 15 and 17 change; `base_commit` (`:510`, asserted against a constant) and `base_source_blobs` (read by no test) are capture records, unchanged. Before committing, against the scratch tree's `src`: `tests/test_ad1152_agentic_correlation.py -n 0 -q` gives 41 passed on M1 with `main`'s fixture and 41 passed on M2 plus this section (the base-source control cannot see keys that the first-key failure masked). Either failing is a hard stop for the Architect.

SEARCH:
````json
  "observation_sha256": "649c58d03cc796ba45e8d36e0f0c93c3836a3ab2b733a985f714e0dc06e28e9e",
````
REPLACE:
````json
  "observation_sha256": "7361f61b2a6b2a71b248b68beffdb032f35e4fca923d54856890ab8a10eb8083",
````

SEARCH:
````json
    "default_config_sha256": "4fde4128e18d3d45b60aa4bfba99d10cd62c39d330ce580ee15fd4c1beb64589",
````
REPLACE:
````json
    "default_config_sha256": "16cbb4bc1731a561deb81bed945bb15a20269c6988e6e20c10a022722ee248e4",
````

## 8. Tracking

Anchors: `PROGRESS.md`'s title line and `DECISIONS.md`'s heading `### BF-924 -- Trust inputs read through APIs that exist (2026-10-25, #1654)`. The entries go in M2's commit. Set the date to the commit date.

**`PROGRESS.md`:**

SEARCH:
````markdown
# ProbOS Progress
````
REPLACE:
````markdown
# ProbOS Progress

**BF-926 and BF-927 (2026-10-25), #1656 and #1657 -- config fields and boot claims say what runs.** BF-927: ten boot-log lines said AD-455's Security Team, AD-676 risk tiers, AD-679 disclosure routing, AD-511 and AD-530's detectors, AD-451 reconciliation and AD-528/528b ground-truth verification were wired or initialized; nothing calls them, so each line now says "built, not invoked" (the AD-455 RedTeamLead health monitor runs and says so). Their config summaries, roadmap statuses and AD-753's gate docstring say the same, and a test traces production callers with the AST and fails if a claim and its caller state disagree in either direction, within the approximations its docstring lists. BF-926: `security.memory.enforce_leak_guard` promised redaction nothing performed and is deleted (old configs still load; its manifest conflict edge went with it); 39 other fields nothing acts on say "Inert: no production code reads this field to act on it" (or "this section") in the generated config reference, and the config API still exports them; the stale `cognitive.captain_card_refresh_min_interval_seconds` key is removed; `scripts/check_config_readers.py` reports unread fields and yaml keys with no field and always exits 0. No behaviour change. New: `tests/test_bf927_boot_claims.py`, `tests/test_bf926_config_readers.py`, `scripts/check_config_readers.py`. The contract is `prompts/bf-926-927-config-and-boot-claims-match-what-runs.md`.
````

**`DECISIONS.md`:**

SEARCH:
````markdown
### BF-924 -- Trust inputs read through APIs that exist (2026-10-25, #1654)
````
REPLACE:
````markdown
### BF-926 and BF-927 -- Config fields and boot claims say what runs (2026-10-25, #1656, #1657)

- *Inert, not removed.* A field nothing acts on that describes behaviour another issue is meant to build (#1659 governance, #1324 memory machinery) is kept and marked with one phrase, "Inert: no production code reads this field (or section) to act on it", in its field description or its model's docstring summary, the two places the reference renders; generic config I/O, which exports and rewrites every field, does not count as acting on it. Unknown keys are ignored, so removal would also load, silently; marking is the visible choice and keeps the operator's value and the design intent.
- *Leak guard deleted.* It promised redaction the guard never performs and the issue forbids marking it inert; its manifest conflict, the only one, went with it, and the parse-time conflict check is proven on a fixture manifest instead.
- *Report-only reader check.* A separate command, name-based (it under-reports), exit 0 on every input; not a gate phase, because every preflight phase gates on its exit code. Enforcing it is the Captain's decision.
- *Boot claims pinned to callers.* "Built, not invoked" appears exactly when the AST finds no production caller, traced from each service's construction or typed parameters and not matched by method name; for a service with no caller, an instance or entry method handed somewhere the resolver cannot type fails the test. The resolver's known approximations are listed in the test's docstring and followed up separately. Dated records (era files, reconciliation reports) are not rewritten.
- *Reversal.* Revert the commits; the lines say wired again, the fields lose their marker, the leak-guard flag and its conflict return, and the script and tests go.

### BF-924 -- Trust inputs read through APIs that exist (2026-10-25, #1654)
````

**After both milestone commits, and again after any merge of the base (A2):** run `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py`, which captures HEAD's commit subjects, then its `--check` and `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_ad1184_ad_ledger.py -n 0 -q`; commit `docs/development/ad-ledger-snapshot.json` and `docs/development/open-ads-report.md` only, as "BF-926 and BF-927 ledger: regenerate the AD and BF ledger (part of #1656 and #1657)" (BF-924's `34df056c` precedent). Any other file in that diff is a hard stop for the Architect. **`docs/development/roadmap.md` Bug Tracker:** no row (BF-916, BF-921, BF-923, BF-924 precedent); §7.9's edit is AD-753's status wording only.

**#1656 checklist text** (the orchestrator records it on the issue):
- [ ] (F17) `enforce_leak_guard` deleted from the model, tracked yaml and profile manifest; old configs load (M2).
- [ ] (F17) `use_consensus_for_writes`, `memory_policy` (+ selective tags), `min_peer_trust_score`, `shared_trust_min_score`, `permission_mode`, `policy_engine_class` marked inert in the reference; named as #1659 candidates on #1659 (M2).
- [ ] (F16) `working_memory` (12 fields), `memory_budget`, `metabolism`, `pinned_knowledge`, `temporal_validity` marked inert, linked to #1324; yaml comments say the same (M2).
- [ ] (F26) the stale captain-card key removed from the tracked yaml (M2).
- [ ] Report-only `scripts/check_config_readers.py`; exit 0 proven on every input class; its first line recorded in the M2 commit (M2).
- [ ] Config reference and facade baseline regenerated; field count 1875; census re-measured (M2).

**#1657 checklist text:**
- [ ] (F01) AD-455 says RedTeamLead running and the other three built, not invoked (M1).
- [ ] (F07, F08, F09) AD-676, AD-679, AD-511, AD-530 boot lines; AD-753's docstring and the two config descriptions (M1, M2).
- [ ] (#1658 F03, F15) AD-451, AD-528b, AD-528 boot lines (M1).
- [ ] Config summaries and roadmap statuses say the same (M1).
- [ ] A test pins every claim against AST-resolved callers in both directions, with a booted runtime (M1).
- [ ] First live session after merge: section 16's line counts recorded on #1657.

## 9. What this does NOT change

- No service, gate, detector, listener or check starts, stops or changes: `InputValidator`, `ThreatDetector`, `TrustIntegrityMonitor`, `RedTeamLead`, `ActionRiskRegistry`, `DisclosureRouter`, `vote_on_intent`, `BoundaryViolationDetector`, `ClassificationGate`, `ReconciliationEscalator`, `GroundTruthVerifier`, `GroundTruthRejectionGate`, `GroundTruthTrustFeedback` (AD-528c's line is literally true and unchanged, R3) are constructed exactly as before.
- No field's default, type or bound changes; no field other than `enforce_leak_guard` is added or removed; `memory_policy`'s validator still rejects unknown values.
- `/api/system/disclosure-clearances` still answers `"status": "active"` (R2).
- `scripts/run_test_gate.py` and every existing check are unchanged; nothing gates on the new script.
- `mobility.py`, `config/node-1.yaml`, `config/node-2.yaml`, `DECISIONS.md`/`PROGRESS.md` history, the era files and dated reports are unchanged (D8, R5, R6).

## 10. Mutation rows (whole stripped lines, each occurring once in its file after section 7; "F" marks a roadmap fragment row)

Run each row on the applied, regenerated tree after an unmutated baseline run passes; restore each file before the next row. M1 command:

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf927_boot_claims.py -n 0 -x -q
```

M2 command:

```
d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf926_config_readers.py -n 0 -x -q
```

**M1 rows (killer: `tests/test_bf927_boot_claims.py`).** For the nine finalize rows the mutation restores the base wording; each is killed by `test_each_boot_line_says_what_its_services_do[<key>]` and `test_the_booted_vessel_prints_the_reworded_lines` (AD-528b and AD-530/511 included).

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| B1 | `finalize.py` | `"AD-530: ClassificationGate built, not invoked (%d patterns): nothing calls check_disclosure (BF-927, #1657)",` | `"AD-530: ClassificationGate initialized (%d patterns)",` | `[AD-530]` |
| B2 | `finalize.py` | `"AD-511: Autonomy Boundaries v1 built, not invoked (%d boundaries; %d patterns): nothing calls the detector's scan (BF-927, #1657)",` | the base text | `[AD-511]` |
| B3 | `finalize.py` | `logger.info("AD-530: ClassificationGate v1 built, not invoked (BF-927, #1657)")` | `logger.info("AD-530: ClassificationGate v1 wired during finalization")` | `[AD-530]` |
| B4 | `finalize.py` | `logger.info("AD-511: Autonomy Boundaries v1 built, not invoked (BF-927, #1657)")` | `... v1 wired during finalization")` | `[AD-511]` |
| B5 | `finalize.py` | `"AD-676: ActionRiskRegistry built, not invoked (%d actions): nothing calls check_authorization (BF-927, #1657)",` | `"AD-676: ActionRiskRegistry initialized with %d actions",` | `[AD-676]` |
| B6 | `finalize.py` | `logger.info("AD-679: DisclosureRouter built, not invoked: nothing calls filter_permitted; /system shows its clearance map only (BF-927, #1657)")` | `logger.info("AD-679: DisclosureRouter initialized")` | `[AD-679]` |
| B7 | `finalize.py` | `logger.info("AD-451: ValidationFramework's ReconciliationEscalator built, not invoked: nothing calls reconcile (BF-927, #1657)")` | `logger.info("AD-451: ValidationFramework wired (ReconciliationEscalator)")` | `[AD-451]` |
| B8 | `finalize.py` | `"AD-455: InputValidator, ThreatDetector and TrustIntegrityMonitor built, not invoked: "` | `"AD-455: InputValidator, ThreatDetector and TrustIntegrityMonitor wired: "` | `[AD-455-screening]` |
| B9 | `finalize.py` | `logger.info("AD-455: RedTeamLead running (red-team pool health every %.0fs)", config.security.campaign_interval_seconds)` | `logger.info("AD-455: RedTeamLead built, not invoked (every %.0fs)", config.security.campaign_interval_seconds)` | `[AD-455-red-team]` (the invoked direction) |
| B10 | `finalize.py` | `"AD-528b: GroundTruthRejectionGate built, not invoked (metadata_key=%s): its caller is AD-528b-2 (BF-927, #1657)",` | `"AD-528b: GroundTruthRejectionGate wired (metadata_key=%s)",` | `[AD-528b]` |
| B11 | `finalize.py` | `"AD-528: GroundTruthVerifier built, not invoked (threshold=%.2f, window=%.0fs): only the uncalled rejection gate calls verify (BF-927, #1657)",` | `"AD-528: GroundTruthVerifier wired (threshold=%.2f, window=%.0fs)",` | `[AD-528]` |
| D1 | `config.py` | `"""Security Team configuration (AD-455). The RedTeamLead pool-health monitor runs; InputValidator, ThreatDetector and TrustIntegrityMonitor are built, not invoked, so nothing screens inbound input (BF-927, #1657).` | `"""Security Team configuration (AD-455).` | `test_each_description_says_what_its_services_do[AD-455-screening]` |
| D2 | `crew.py` | `"""Action Risk Tier configuration (AD-676). The ActionRiskRegistry is built, not invoked: nothing calls check_authorization (BF-927, #1657)."""` | `"""Action Risk Tier configuration (AD-676)."""` | `[AD-676]` |
| D3 | `agentic.py` | `"""Configuration for AD-530 v1 disclosure gate. The ClassificationGate is built, not invoked: nothing calls check_disclosure (BF-927, #1657)."""` | the base docstring | `[AD-530]` |
| D4 | `agentic.py` | `"""AD-511 v1: Agent Autonomy Boundaries (registry + observational detector). The detector is built, not invoked: nothing calls its scan, so it observes nothing (BF-927, #1657)."""` | the base docstring | `[AD-511]` |
| D5 | `operations.py` | `"""Validation framework configuration (AD-451). The ReconciliationEscalator is built, not invoked: nothing calls reconcile (BF-927, #1657)."""` | the base docstring | `[AD-451]` |
| D6 | `emergence.py` | `"""Ground-truth task verification configuration (AD-528, AD-528b, AD-528c). The GroundTruthVerifier is built, not invoked: only the rejection gate calls verify, and nothing calls the gate (BF-927, #1657)."""` | the base docstring | `[AD-528]` |
| D7 | `quorum.py` | `BF-927 (#1657): built, not invoked. No production code calls this function, so` | `BF-927 (#1657): No production code calls this function, so` | `[AD-753]` |
| R1 (F) | `roadmap.md` | in the `\| AD-753 \|` row: `; built, not invoked: nothing calls` | delete `built, not invoked: ` | `[AD-753]` |
| R2-R8 (F) | `roadmap-era-5-completed.md` | in each of the seven entries of §7.10: `built, not invoked` | `wired` | `[AD-451]`, `[AD-455-screening]`, `[AD-511]`, `[AD-528]`, `[AD-530]`, `[AD-676]`, `[AD-679]` |
| A1 | test | `return tuple(f"{service.name}.{entry}" for service in services if service.name not in invoked for entry in service.entries)` | `return ()` | `test_each_service_state_is_resolved[ThreatDetector]` (its only call is inside `InputValidator.check`) |
| A2 | test | `typed.add((owner, arg.arg))` | `pass` | `[ThreatDetector]` (the typed hand-off into `InputValidator` becomes an escape) |
| A3 | test | `name_holders.add((module.name, inner, arg.arg))` | `pass` | `test_the_resolver_tells_a_caller_from_a_decoy_and_an_escape[a typed hand-off]` |
| A4 | test | `return isinstance(key, ast.Constant) and key.value in attr_holders` | `return False` | `[a resolved caller]` |
| A5 | test | `sites.append(Site(module.path, node.lineno, scope))  # a resolved call` | `pass` | `test_each_service_state_is_resolved[RedTeamLead]` |
| A6 | test | `escapes.append(Site(module.path, node.lineno, scope))  # an untyped hand-off` | `pass` | `[an untyped hand-off]` |
| A7 | test | `return isinstance(key, ast.Constant) and key.value in service.entries and is_read(module, scope, expr.args[0])` | `return False` | `[a literal getattr call]` (A2) |
| A8 | test | `escapes.append(Site(module.path, node.lineno, scope))  # an entry method handed on` | `pass` | `[an entry handed on]` (A2) |
| A9 | test | `escapes.append(Site(module.path, node.lineno, scope))  # an entry method aliased` | `pass` | `[an entry aliased]` (A2) |

Unpinned text, no row: the Yeoman comment (§7.3), the `memory_security.py` docstring (§7.15), the yaml comments (§7.16), the manifest comment (§7.17). The resolver's `via` clause survives a mutation on this tree (no service reached through `via` is invoked today): disclosed, no row.

**M2 rows (killer: `tests/test_bf926_config_readers.py`).** For every field and section row, the mutation replaces `Inert: no production code reads this` with `Unread` in that line; the killer is `test_the_real_config_reports_each_bf926_field_as_inert[<path>]` for that path (a section row kills every case of its section).

| # | File | Line (stripped, its start) | Killed by `[...]` |
|---|---|---|---|
| F1 | `config.py` | `use_consensus_for_writes: bool = Field(default=True, description="Inert:` | `cognitive.use_consensus_for_writes` |
| F2 | `config.py` | `memory_policy: str = Field(default="clean_room", description="Inert:` | `federation.memory_policy` |
| F3 | `config.py` | `memory_policy_selective_tags: list[str] = Field(default=[], description="Inert:` | `federation.memory_policy_selective_tags` |
| F4 | `config.py` | `min_peer_trust_score: float = Field(default=0.0, description="Inert:` | `federation.min_peer_trust_score` |
| F5 | `config.py` | `shared_trust_min_score: float = Field(default=0.5, ge=0.0, le=1.0, description="Inert:` | `federation.shared_trust_min_score` |
| F6 | `config.py` | `permission_mode: Literal["manual", "autopilot"] = Field(default="manual", description="Inert:` | `security.permission_mode` |
| F7 | `config.py` | `policy_engine_class: str = Field(default="NullPolicyEngine", description="Inert:` | `security.policy_engine_class` |
| F8-F19 | `cognition.py` | the 12 `WorkingMemoryConfig` lines `<name>: <type> = Field(default=..., description="Inert:` (`token_budget` ... `engagement_budget`) | `working_memory.<name>` |
| F20 | `cognition.py` | `"""AD-573: Unified agent working memory configuration. BF-926 (#1656): only stale_threshold_hours is read; AgentWorkingMemory uses its own defaults for everything else."""` → mutate to append ` Inert: no production code reads this section.` | `test_the_tracked_yaml_carries_no_key_bf926_removed` |
| F21 | `cognition.py` | `"""AD-573: Memory budget accounting across recall tiers. Inert:` | `memory_budget.*` (6) |
| F22 | `cognition.py` | `"""AD-670: Working memory metabolism — active lifecycle management. Inert:` | `metabolism.*` (8) |
| F23 | `cognition.py` | `"""AD-579a: Pinned knowledge buffer configuration. Inert:` | `pinned_knowledge.*` (4) |
| F24 | `cognition.py` | `"""AD-579b: Temporal validity windows for episodic memory. Inert:` | `temporal_validity.*` (2) |
| F25 | `config-profiles.yaml` | `default_false: 224` → `default_false: 225` | `tests/test_ad1185_config_profiles.py::test_the_measured_census_matches_the_manifest_header` (run alone) |
| S1 | script | `section_inert = INERT_MARKER in _summary(model)` → `section_inert = False` | `test_the_report_separates_read_unread_inert_and_orphan_keys`, `[memory_budget.enabled]` |
| S2 | script | `inert = section_inert or INERT_MARKER in (info.description or "")` → `inert = section_inert` | the fixture case, `[cognitive.use_consensus_for_writes]` |
| S3 | script | `if relative.parts[0] in declaring:` → `if False:` | the fixture case (`unread_field` counts as read) |
| S4 | script | `elif name not in names:` → `elif True:` | the fixture case |
| S5 | script | `report.inert_referenced.append(path)` → `pass` | the fixture case |
| S6 | script | `orphans.append(path)` → `pass` | the fixture case |
| S7 | script | `elif _is_model(info.annotation):` → `elif False:` | the fixture case (`leaf.ghost`) |
| S8 | script | `return 0  # report-only: the status never reflects the findings` → `return 1` | `test_the_check_exits_zero_on_every_input`, `test_the_command_line_exit_status_is_zero` |
| S9 | script | `except SystemExit as exc:  # argparse exits on a malformed command line; this check never does` → `except ValueError as exc:` | `[an argument without its value]` |

The deleted field, the removed yaml keys and the removed manifest rows cannot be mutated back in one line; `test_the_leak_guard_flag_is_gone_and_a_config_that_sets_it_still_loads`, `test_the_tracked_yaml_carries_no_key_bf926_removed` and `check_config_profiles.py --check` pin them. The script's outer `except Exception` is a backstop no input reaches (every expected failure is handled earlier): disclosed, no row.

## 11. Verified Against Codebase (2026-10-25, worktree `bf926-draft` at `7ffbda5a`)

```
git log --oneline -1   -> 7ffbda5a bf924 oracle gen after contract b (scratch)
read prompts/bf-924-trust-inputs-through-real-apis.md: 1-250, 793-887, 1273-1578 (shape, §6, §7.11-7.13, §7.22, §8-18)
grep finalize.py "AD-455|AD-676|AD-753|AD-451|AD-528|AD-511|AD-530|AD-679|wired"
  255 AD-530 initialized; 1210 AD-511 initialized; 4098, 4101 "wired during finalization"; 4328 AD-676 initialized;
  4336 AD-679 initialized; 4374 AD-451 wired; 4558 AD-455 wired (4 services); 4727 AD-528b wired; 4758 AD-528c wired; 4765 AD-528 wired
read finalize.py 240-258, 1193-1214, 4082-4104, 4296-4377, 4525-4558, 4688-4769, 6282-6293; logger = logging.getLogger(__name__) :27; finalize_startup :4055
grep "AD-753" src -> config.py:2975; quorum.py:196, 210, 218, 221; policy_engine.py:1; destructive_ops.py:1, 28; permission_model.py:1; permission_card.py:1; yeoman.py:120 (no boot line)
read quorum.py 186-223 (vote_on_intent, module function); yeoman.py 116-123; red_team_lead.py 1-130 (start -> task, campaign loop)
grep "^class |    def" risk_tiers.py, disclosure.py, validation_framework.py, ground_truth.py, security/*.py -> check_authorization :102; check_recipients :83, filter_permitted :111, get_clearance_map :126; reconcile :225; evaluate :318, verify :73, verifier: GroundTruthVerifier :308; analyze trust_integrity.py:64; check input_validator.py:48; scan threat_detector.py:53, autonomy_boundaries.py:182; check_disclosure classification.py:98
read routers/system.py 204-213 (getattr(runtime, "_disclosure_router"); get_clearance_map; "status": "active"); shutdown.py 1288-1291
grep config fields (repo, prompts excluded): see section 12; config.py:611, 2488, 2491, 2513, 2517, 2976-2977; crew.py:122; system.yaml:98, 106, 294-295, 324, 326, 977, 985-986; node-1/2.yaml:56
read config.py 604-612, 2474-2565, 2940-2977, 4036-4049; crew.py 95-125, 376-381; cognition.py 276-390; agentic.py 54-63; operations.py 535-540; emergence.py 30-56
read federation_recall_agent.py 128-172 (shared_trust filters by classification only; dp_min from fed_config)
read memory_security.py 1-30; grep check_memory_leakage -> cognitive_agent.py:7551, 12305-12311 ("never mutates the response"), memory_security.py:310
read system.yaml 92-111, 286-330, 965-990, 1960-2029; grep active_rejection_enabled -> system.yaml:1335 false, emergence.py:44
read config-profiles.yaml 1-40, 70-94, 205-240, 440-470; grep conflict -> only :462 is a non-empty conflicts_with
read config_profiles.py 330-455, 457-597 (load_profile(manifest_path=), validate_override_keys, read_manifest_rules)
read tests: test_ad1185 76-95, 650-804, 845-864, 970-990; test_ad1270e2g 58-61, 90-117, 170-200, 255-281, 386-449, 526-547, 700-749; test_ad607 155-174; test_ad1270e1 1540-1561; test_ad1270e2i 145-188, 455-531; test_ad1270e2b 440-479; test_ad1130 1562-1571; test_ad1152 48-52, 505-531; test_bf924_trust_inputs 216-249; test_ad739 125-139; test_ad1234 14, 42
read gen_config_reference.py 134-178 (summary = first paragraph; Field description; seen keyed by name); check_config_facade.py 237-272, 334-337, 896-1009, 1230-1300 (schema digest includes descriptions); run_test_gate.py 1088-1154 (preflight phases gate), 1551-1616 (report-only budget)
read gen_ad_ledger.py 107-231 (heads: DECISIONS headings, PROGRESS bold lines; connector "and"); roadmap files are not parsed
grep config-reference.md: 1-40, 1019-1036, 2449-2547; summaries at 1021, 1391, 1485, 2944, 3027, 3035; "## `memory`" :168 (security.memory never rendered); multi-line summary rendering :572
grep roadmap.md "AD-753" -> 730 only; roadmap-era-5-completed.md heads 3856 AD-451, 3879 AD-455, 6146 AD-511, 6245 AD-528, 6257 AD-528b (Scoped), 6273 AD-530, 6906 AD-676, 6912 AD-679
grep PROGRESS.md "^# ProbOS Progress" -> 1; DECISIONS.md "^### BF-924" -> 739
grep pyproject.toml -> requires-python ">=3.12"; no ruff config
pytest --collect-only (M1 sixteen files) -> 1115; (M2 fourteen files) -> 1075 (not run; imported the venv's editable src, section 17)
gh issue view 1656, 1657 (+ comments), 1658, 1324 (comments: work item 2, the proposed report-only producer/consumer check)
```

## 12. Absence Verified (2026-10-25)

```
CLAIM: the F17 and AD-753 fields have no production reader
RUN:   Grep "use_consensus_for_writes|enforce_leak_guard|min_peer_trust_score|shared_trust_min_score|memory_policy|apply_memory_policy|captain_card_refresh_min_interval_seconds|permission_mode|policy_engine_class" over the repo (prompts excluded)
FOUND: src: definitions only (config.py:611, 2488, 2491, 2513, 2517, 2555-2562 validator, 2976-2977; crew.py:122; mobility.py:14, 58 the def); quorum.py:13 imports permission_model's PermissionConfig (unrelated)
       yaml: system.yaml:98, 106, 294-295, 324, 326, 977, 985-986; node-1.yaml:56, node-2.yaml:56; docs: config-reference/facade/profiles rows; tests: test_ad1185:680, test_ad1270e2g:185, test_ad607:165, test_ad443 (apply_memory_policy, FederationConfig().memory_policy), test_ad1234:42, test_ad739:138
HOLDS: yes

CLAIM: the F16 sections have no production reader except working_memory.stale_threshold_hours
RUN:   Grep "(config|cfg|_config|settings)\.(working_memory|memory_budget|metabolism|pinned_knowledge|temporal_validity)\b|\"(memory_budget|metabolism|pinned_knowledge|temporal_validity)\"" src/probos
FOUND: finalize.py:6289 only
RUN:   Grep "memory_budget_config|pinned_config" src; Grep "AgentWorkingMemory\(|MemoryMetabolism\(|MemoryBudgetManager\(" src
FOUND: cognitive_agent.py:1415, 3747 (kwargs.get; nothing passes it); agent_working_memory.py:294, 334-338 (the parameter); constructions: cognitive_agent.py:1365 AgentWorkingMemory() with no args, :3750 behind the unpassed kwarg; no MemoryMetabolism(
RUN:   Grep the F16/F17 names in ui/src -> 0
HOLDS: yes

CLAIM: nothing at run time reads a field description or a model schema
RUN:   Grep "model_json_schema|model_fields\[.*\]\.description" src/probos
FOUND: 0
HOLDS: yes

CLAIM: no config model forbids unknown keys except two untouched ones
RUN:   Grep "model_config|extra=" src/probos/config.py; src/probos/config_models
FOUND: config.py 0; operations.py:166, :215 (extra="forbid", frozen; the CommandPolicy models)
HOLDS: yes

CLAIM: each BF-927 service is constructed only in finalize.py, and its holder is read nowhere that calls an entry method
RUN:   Grep "\b(InputValidator|TrustIntegrityMonitor|ThreatDetector|ActionRiskRegistry|BoundaryViolationDetector|ClassificationGate|DisclosureRouter|ReconciliationEscalator|GroundTruthRejectionGate|GroundTruthVerifier)\(" src/probos
FOUND: finalize.py:253, 1206, 4325, 4334, 4368, 4532, 4533, 4540, 4699, 4720 only
RUN:   Grep "input_validator|trust_integrity_monitor|threat_detector|red_team_lead|_risk_registry|risk_registry|boundary_detector|classification_gate|_disclosure_router|disclosure_router|reconciliation_escalator|ground_truth_rejection_gate|ground_truth_verifier" src/probos
FOUND: finalize.py assignments; input_validator.py:12, 33, 40 (the ThreatDetector parameter, self._threat); shutdown.py:1289-1291 (red_team_lead.stop); routers/system.py:207-212 (get_clearance_map); degradation/registry.py:50 (a string label); config.py:4110 (the config field classification_gate)
RUN:   Grep "\.(check_authorization|vote_on_intent|check_disclosure|filter_permitted)\(" and "vote_on_intent|check_recipients" src/probos
FOUND: 0 calls (definitions only; check_recipients :119 inside filter_permitted)
RUN:   Grep "\.(reconcile|analyze|evaluate|verify|scan|check)\(" src/probos (70 hits)
FOUND: none on a BF-927 receiver: input_validator.py:60 self._threat.scan (inside InputValidator.check); contagion.py:164 self._scanner (ContagionScanner, :150); ground_truth.py:328 the gate's own verify; thread_fanout.py:1294 ReferentGroundingGate; the rest are other classes (quartermaster, trust_identity, board reconciler, crew verifier, novelty gate, egress, ...)
HOLDS: yes; the test re-derives this with the resolver (D7)

CLAIM: no test, script, ui string or doc quotes an old boot line
RUN:   Grep "Security Team wired|ActionRiskRegistry initialized|DisclosureRouter initialized|ValidationFramework wired|GroundTruthVerifier wired|GroundTruthRejectionGate wired|ClassificationGate initialized|ClassificationGate v1 wired|Autonomy Boundaries v1|4 services" (repo, prompts excluded)
FOUND: finalize.py only, and progress-era-5-unification.md:165 (a dated record)
HOLDS: yes

CLAIM: Yeoman's read-only set and the permission auto-approval have no reader outside the uncalled gate
RUN:   Grep "_YEOMAN_READ_ONLY_INTENTS|autoApproveReadOnly|auto_approve_read_only|read_only_intents|should_auto_approve" src/probos
FOUND: yeoman.py:120, 122, 144; permission_model.py:38, 43, 49; quorum.py:13, 208, 214
HOLDS: yes

CLAIM: #1324's producer/consumer check is not built
RUN:   Grep "no producer|no consumer|ruff.{0,40}(report|advisory|non-blocking)" scripts (-i)
FOUND: 0
HOLDS: yes (the #1324 comment proposes it as a work item)

CLAIM: the manifest declares one conflict, the one D3 removes
RUN:   Grep "conflict" docs/development/config-profiles.yaml
FOUND: every row "conflicts_with: []" except :462-468
HOLDS: yes

CLAIM: only the facade test pins the counts this moves (counts only; digests and dumps are the next claim, A1)
RUN:   Grep "\b(1876|1887|1875|1886|449|448|225|224|140|139)\b" tests/test_ad1*.py; Grep "census|[0-9]{3,4} fields" docs/development/config-reference.md
FOUND: test_ad1270e1_config_facade.py:1557-1558 only (others are unrelated numbers); the reference has no census
HOLDS: yes (BF-924's A1-3/A1-4 enumeration of the facade and census pins still applies)

CLAIM (A1): the only digest, schema or whole-model-dump pins this contract moves are the facade baseline (regenerated), test_ad1270e2g's EXPECTED_DUMPS (§7.20) and the AD-1152 golden (§7.24)
RUN:   Grep "enforce_leak_guard" over the repo (prompts excluded)
FOUND: system.yaml:977, DECISIONS.md:1557 (history), config-facade-baseline.yaml:2441, config-profiles.yaml:225, 228, 463, crew.py:122, test_ad1185:680, test_ad1270e2g:185, test_ad607:165; each changed in §7.12-§7.23
RUN:   Grep -i "sha256\(.*(dump|schema|config)|(dump|schema)_sha|config_sha|digest\(.*config" over tests, scripts, src, docs, config
FOUND: check_config_facade.py and config-facade-baseline.yaml (regenerated); test_ad1152:500 and its fixture :17 (§7.24); test_ad1135_setup_cli:690-1028 and test_ad1135_setup_chain:340-351 (one file's bytes before and after one run); test_ad1196:234 (a helper over its own values); command_policy.py:1875 (CommandPolicyConfig, untouched)
RUN:   Grep "model_json_schema" over tests, scripts, src (*.py)
FOUND: check_config_facade.py:976 (regenerated); test_ad1270e1:184-185, test_ad666:1020, test_config.py:75, test_ad1192_owned_steps_store:2027, 2032: none over a model touched here
RUN:   Grep "SystemConfig\(\)\.model_dump|config\.model_dump\(" tests; Grep "_golden\.json|_baseline\.json" tests
FOUND: test_ad1270e2*: per-model sub-dicts (only e2g owns MemorySecurityConfig); test_ad1185:104-107, 124-127 (pairs computed in one process, :99-102); test_ad1206:1091 (RepairConfig); test_ad1258:1384 and test_ad1270f:732 (before and after in one process); test_ad1152:217 (§7.24); goldens ad1179, ad1200, ad1240 x2 pin tool definitions and request bodies, which no field description reaches (claim above) and no default but the deleted field changes
HOLDS: yes, given §7.24's two confirming runs

CLAIM: no other model nests a model whose schema changes
RUN:   Grep "WorkingMemoryConfig|MemoryBudgetConfig|MetabolismConfig|PinnedKnowledgeConfig|TemporalValidityConfig|MemorySecurityConfig|FederationConfig\b" src/probos
FOUND: config.py:2971 (SecurityConfig.memory), 3906, 4041-4047 (SystemConfig); the rest are imports and re-exports
HOLDS: yes for these; the orchestrator's regenerated diff is the check for the M1 models

CLAIM (A2): no production code references a service entry uncalled or through a literal getattr, so A2's new call and escape forms move no real-tree state
RUN:   Grep "\.(check_authorization|check_disclosure|filter_permitted|check_recipients|reconcile|run_campaign_now)[^(\w]|getattr\([^)]*[\"'](check|scan|analyze|evaluate|verify|reconcile|check_authorization|check_disclosure|filter_permitted|check_recipients)[\"']" src/probos; Grep "\.(check|scan|analyze|evaluate|verify)[^(\w]" src/probos *.py; Grep "\.(<every entry>|start)\s*$" src/probos *.py
FOUND: board_reconciler_ticker.py:3 (docstring); admission/service.py:68 `check=found.check` (`found` is an IfExp of module constants, not a holder); ward_room/content_firewall.py:199 `rec.scan.reasons` (an attribute chain, not an argument or assigned value); the rest docstrings, comments, imports; end of line: none
HOLDS: yes; the 12 state cases confirm it on the built tree (any `escapes` is a hard stop)

CLAIM (A2, F7): production code reads every marked field only through generic config I/O, and no test pins the description text
RUN:   Grep "model_dump|@router\.(get|put|post)" src/probos/routers/config.py; Grep "reads this|AgentWorkingMemory uses its own default|a candidate for #1659" tests
FOUND: routers/config.py:191, :211 (GET dumps), :246, :267 (POST dumps and rewrites the yaml); tests: only test_bf926_config_readers.py:49 (a fixture docstring, left)
HOLDS: yes

CLAIM (A2): S-A/S-B/S-C touch only these occurrences, and the words added name no config.py module identifier (§6 true-leaf scan)
RUN:   Grep "code reads this field \(" / "code reads this section \(BF" / "No production code reads this section" over the repo; Grep "^(to|act|on|it|acts)\b|^(def|class) (to|act|on|it|acts)\b|import .*\b(to|act|on|it|acts)\b" src/probos/config.py
FOUND: config.py 7, cognition.py 12 + 4, config/system.yaml 4, config-reference.md 19 + 4 (regenerated), this contract §7.13/§7.14 19 + 4 and §7.16 4; identifiers: none
HOLDS: yes
```

## 13. Prior Art and Blind Spots

- **External (one search, 2026-10-25).** vulture finds dead code by recording defined and used names over the AST, ignoring scopes, at 60 % confidence for attributes; it under-reports for the same reason this check does, and its whitelist is the analogue of the inert marker. Adapted: the check is a scope-free name match and says so; the BF-927 pin, where a false "not invoked" would be a false claim, resolves receivers instead. ([vulture](https://pypi.org/project/vulture/2.9))
- **`docs/research/reference-projects.md` (date used 2026-10-25):** no listed project addresses dead configuration or boot-claim truth; none was examined, so no row changes. AG-UI (*never*) is not relevant: considered, deferred.
- **Internal:** #1324's work item 2 (the event producer/consumer check, D5); AD-1270a's capability-truth inventory (`gen_capability_truth.py`), which separates *present* from *activated* for declared capabilities; this BF does the same for config fields and boot lines without touching its declarations. AD-1234 (#1117), the precedent for deleting a field whose mechanism does not exist.
- **Blind spots addressed:** RedTeamLead does run (the AD-455 line could not just be negated); the manifest's only conflict depended on the deleted flag (D3); the reference never rendered `security.memory` (R1); string literals in `config.py` descriptions feed the true-leaf scan (section 6); multi-line docstring summaries render with runs of spaces (§7.4); the `/disclosure-clearances` route reports "active" (R2); AD-528c's subscribed listener (R3).
- **Considered, deferred:** making the reader check receiver-resolved (R7); a gate phase for it (D5).

## 14. Diff Reviewer: properties to verify

1. No production behaviour changes: every edited production line is a log format string, a docstring, a comment, a `Field(description=...)` beside an unchanged default, or the deletion of `enforce_leak_guard`; no constructor, call, condition or default changes.
2. Each boot line, config summary, roadmap status and docstring that names one of the services says `built, not invoked` exactly when the AST finds no production caller, and the RedTeamLead line, whose service runs, does not; the test fails if either side drifts.
3. The resolver counts a call (`holder.entry(...)` or a literal `getattr(holder, "entry")(...)`) only on a receiver it traced from a construction or a parameter typed with the class; for a service with no resolved caller, a holder or an uncalled entry method handed to anything it cannot type makes the test fail; a `.check(` / `.scan(` on an untraced receiver never counts; the approximations the test docstring lists (R10) are the only known exceptions, and each is stated there with its direction.
4. Every field the contract marks carries the one phrase in the place the reference renders (field description, or the first paragraph of a docstring that is one physical line), and the one read `working_memory` field does not.
5. A config that still sets `enforce_leak_guard` or the captain-card key loads; neither key remains in the tracked `config/system.yaml`, the manifest or the model; no other tracked yaml line changes except comments.
6. The manifest declares no conflict, both AD-1185 conflict tests still prove the mechanism through a fixture edge and `load_profile(manifest_path=...)`, and the census header holds measured figures.
7. `scripts/check_config_readers.py` returns 0 on every input and is not invoked by the gate or any existing check.
8. The generated reference and facade baseline differ from the base exactly by section 6's hunks; the field-count pin is 1875; the AD/BF ledger is regenerated after the milestone commits (§8), and `gen_ad_ledger.py --check` and `tests/test_ad1184_ad_ledger.py` pass on the final tree.
9. Every changed test says inline why; no test was deleted; both new test files pass alone, in file order and shuffled.

## 15. Acceptance criteria

- Through the real `finalize.py`, a real boot and the real models and roadmap files, every BF-927 claim matches its services' AST-resolved caller state, in both directions; RedTeamLead is reported running.
- Through the real `SystemConfig`, the 39 BF-926 field paths are reported inert; `enforce_leak_guard` is gone and old configs load; the tracked yaml carries no removed key.
- The report-only check lists unread fields, inert fields and yaml keys with no field on a fixture, and exits 0 on six classes of bad input and as a process.
- The config reference and facade baseline are regenerated once for both milestones and checked; the manifest check passes.
- The #1659 candidate list (D2) is posted on #1659.
- Before editing, the tests that pin current behaviour were grepped, and each updated pin says why inline.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Live acceptance (read-only)

After the first session on the merged build, from the vessel log under `%LOCALAPPDATA%\ProbOS\data` (the orchestrator reads it; the Builder never does), record on #1657:
- the count of `AD-455: Security Team wired (4 services)` lines before the merge (the issue says 8 of 8 boots; the source prints it whenever `security.enabled`, `system.yaml:966` true, and finalization reaches `finalize.py:4558`), and after it the counts of `AD-455: RedTeamLead running` and `AD-455: InputValidator, ThreatDetector and TrustIntegrityMonitor built, not invoked` (expected one each per boot);
- that no `wired` or `initialized` line remains for AD-451, AD-511, AD-528, AD-528b (only when its flag is on), AD-530, AD-676 or AD-679;
- the first line of `python -P scripts/check_config_readers.py` against the Captain's local `config/system.yaml` (`--yaml`), for the Captain's information.

## 17. Not verified

- **Which source the tests import.** The collection counts here used the venv's editable install, which points at `D:\ProbOS\src` (BF-924, section 17). Run every focused check, tests-first run and mutation row against the scratch tree's `src` (for example `PYTHONPATH` set to it).
- Nothing was run: the new tests, the script, the resolver's states on the real tree (expected section 12's; any `escapes` is a hard stop for the Architect), its run time over `src/probos` (several seconds expected), and the boot test (that a default boot with `active_rejection_enabled=True` reaches every line and stops cleanly).
- The census figures (448 / 224 / 224 / 85 / 139) are derived from BF-924's measured figures less one default-False boolean; the orchestrator measures them (§7.17).
- The generated diff (section 6) is reasoned from the generators' code, not measured; in particular, the list of 15 models whose `schema_sha256` moves.
- The real-tree report's other contents (how many fields it lists as unread, which yaml keys have no field): measured by the orchestrator, recorded in the M2 commit body, not asserted.
- That `inspect.getdoc` and the generator agree on each summary (both split at the first blank line; §7.4-§7.8 and §7.14 keep each summary on one physical line).
- The live `probos.log` count (section 16): read by the orchestrator only.

## 18. For the register (found here, not fixed by this change)

- **R1.** `gen_config_reference.py:136-138` keys its `seen` set on the field **name**, so a nested model whose name an earlier section used never renders: `security.memory` (`MemorySecurityConfig`, the `enforce_*` flags) is absent from the reference because top-level `memory` came first. A path-keyed set changes the reference broadly: a separate change.
- **R2.** `/api/system/disclosure-clearances` answers `"status": "active"` (`routers/system.py:211`, pinned by `test_ad679_*`) for a router that filters nothing. Changing the value is a wire-contract change, not wording.
- **R3.** AD-528c's `GroundTruthTrustFeedback` is subscribed (its "wired" line is literally true) to `VERIFICATION_PASSED`/`FAILED`, which nothing emits while `verify` has no caller; it is live only when #1658 wires the verifier (default off, `system.yaml:1337`).
- **R4.** `MemorySecurityConfig.dp_min_cohort_size` (`crew.py:125`) looks unread (the federation path reads `FederationConfig.dp_min_cohort_size`, `federation_recall_agent.py:164`); the name-based report counts it as read because the names match. A hand check for #1659.
- **R5.** `config/node-1.yaml:56` and `config/node-2.yaml:56` set the inert `use_consensus_for_writes: true`.
- **R6.** `docs/development/yeo-gap-reconciliation-2026-05-20.md:53`, `:177` record AD-753's read-only bypass as shipped "at the gate"; the gate has no caller. Dated reports are not rewritten (D8).
- **R7.** The reader check under-reports (name match); a receiver-resolved version, like BF-927's resolver, is the follow-up if the Captain decides to enforce it.
- **R8.** `roadmap-era-5-completed.md:307-310` (Phase 31 design list) describes the Security Team in the present tense; design text, left (D8).
- **R9.** The AD-1152 OFF golden is no longer the pristine capture its lineage describes. `docs/development/agentic-event-correlation.md:133-139` calls it immutable and says only AD-1152's own leaf is removed before the digest is compared, but BF-924 (A9) and this contract (A1) refreshed `default_config_sha256` for deleted fields. Every added field is popped in the test with a comment (`test_ad1152_*:220-314`); a deleted field leaves no trace in the test. Choosing one rule for a deleted field (refresh plus a test comment naming it, or re-insert its captured default in the test and restore the pristine digest) and correcting the doc is a separate change.
- **R10.** BF-927's resolver approximations (round 1 F2, F4, F6; disclosed in the test docstring, A2). (a) P2, silent: a typed parameter is keyed by its callable's short name and the parameter name, so a keyword hand-off to a different callable with both names alike is exempt as if typed. (b) P3, loud: holder attributes are matched by name, not owner, so `other.gate.check()` counts once any `runtime.gate` holds the service. (c) P3, loud: a positional argument into an annotated parameter is an escape. One follow-up fixes all three: resolve callees and attribute owners to their definitions through imports, then bind positional arguments by index; it carries the reviewer's six round-1 probes as fixture cases.
