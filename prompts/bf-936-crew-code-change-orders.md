# BF-936 (#1677): The standing orders say what crew can do about code changes: crew propose, review, specify and verify; Forge builds a candidate only on a build the Captain dispatches; no one records build work as their own

**Drafted by:** `Architect` (GitHub Copilot fallback; the Claude Code bridge was logged out), 2026-11-12
**Status:** ready to build on `origin/main` `430423e1` once BF-934 (#1673) has merged (reading tree `D:\ProbOS-worktrees\bf936-base`). **Oracle:** no test run (a read-only consult: I cannot run pytest here). In-memory scripts (piped to the interpreter, `-B`, nothing written) applied every block of this file to the LF blobs, composed the real loader over the patched text for 23 agent types, drove the new file's functions by hand against the base text and the head text, ran the mutants of section 9 and ran the P2-5 script over the head text (section 11). Every pytest count below is "expected"; what that leaves unchecked is in L13.
**Base blobs (`430423e1`):** `config/standing_orders/ship.md` `e34b885af6e642a9658da61f6b9976f458dbc2a8`, `builder.md` `a75139b070bf3a09bfb924dd071114827411fc45`, `engineering.md` `fdc8cbf2baaa55f4f73628ef4a144941c9829730`, `tests/fixtures/ad1152_agentic_off_golden.json` `4bff3440e55f4d07bf00bc8e9f2085d643f7078a`, `tests/fixtures/ad1200_no_instructions_golden.json` `0c6e86af50ef572db1d578875cfa244231f92ab4` (A1), `PROGRESS.md` `eaf7e884c3a158b6d9c89754c3e99ab597c05ff4`, `DECISIONS.md` `1d814df5020e7b9675f2ae123e14bf5e19075b7f`.
**Dependencies:** BF-934 (#1673) merges first (by the requester's list of its changed files it changes none of the files this contract changes except `PROGRESS.md`, `DECISIONS.md` and the ledger pair, around which the trackers below anchor); BF-937 (#1678) is independent (D5). **Tier:** M1 STANDARD (tests); M2 STANDARD (prompt text that reaches every cognitive agent, plus two fixture refreshes; one revert undoes it); M3 STANDARD. **Estimated tests:** one new file, 40 cases (expected: 9 pass and 31 xfail at M1). **BF number:** BF-936, held by #1677; nothing new is allocated (section 11).

**Which text describes the head.** Before building, after BF-934's merge: `git rev-parse HEAD:<path>` for the five config and fixture paths prints the blobs above (BF-934 changes nothing under `config/`, and the list of its changed files that the requester gave names no fixture), `PROGRESS.md` and `DECISIONS.md` differ from the blobs above by BF-934's entries, and the new test file does not exist. If a config or fixture blob differs, every SEARCH must still occur exactly once, else it is a hard stop for the Architect (P2-5 recomputes from the golden it finds). Working copies are CRLF and SEARCH text is LF. Where prose and a block differ, the block wins. Apply the pairs with the `edit` tool one at a time, whole block, in label order.

## 1. Problem

1. **No order says who changes ProbOS's code.** The ship tier (`ship.md`) is composed for every agent (`standing_orders.py:491-494`) and says nothing about it; the Constitution has only the general "Cannot implement? Research thoroughly." (`federation.md:81`). The 27 `config/standing_orders/*.md` files were enumerated (D2): 39 lines match a pattern for building, implementing, committing, merging, deploying or shipping as a verb; none states the rule. The issue's evidence, not verified here: in one review thread a crew member offered to make an approved change to ProbOS's own code itself (the thread is quoted in #1677).
2. **Two files say the Software Engineer builds, without a condition.** `builder.md:6` ("...and build solutions that work"), `:62` ("You've built enough to know where the pitfalls are."), `:63` ("...evidence from builds you've run."), and `engineering.md:54-60` ("Build Pipeline Standards"). They are true only for a build the Captain dispatches.
3. **What is true today (re-derived on `430423e1`).** (a) `WorktreeManager.merge_to_main` runs no git command and returns `(False, reason)` (`worktree_manager.py:153-175`, BF-897); `BuildDispatcher.approve_and_merge` calls it (`build_dispatcher.py:396-407`). (b) The dispatcher is built and started on every boot, with no condition (`startup/structural_services.py:121-132`; it logs `build-dispatcher started max_concurrent=%d`, `build_dispatcher.py:96`, default 2). (c) `self_mod.enabled: true` and `require_user_approval: true` (`config/system.yaml:327-329`). (d) Crew do write and run code in their own workspaces for a task they are given: `dm_agentic.enabled: true` (`config/system.yaml:469-470`), `execution.workspace_root: data/execution/workspaces` (`:436-438`).
4. **The text reaches the building agent too.** `NativeBuilderHarness._compose_system_prompt` composes the builder's orders (`native_builder.py:227-237`) and so does the visiting builder (`copilot_adapter.py:482-493`).
5. **Two fixtures pin the composed text** (D3, A1), and **the orders are cached per process**: `_load_file` is an `lru_cache` (`standing_orders.py:151`), cleared at boot (`startup/finalize.py:4171`) and by a directive mutation, not by an edit of a file.

## 2. Solution

`ship.md` gains a section "What Crew Can Do About Code Changes", first in the file and under the universal tag `core_directives`, carrying the issue's four elements with the Captain's Forge sentence in place of item 2's, and one clause that keeps the crew's workspace work out of the rule (P2-1). `builder.md` says the same in one paragraph after its role paragraph, and its two personality bullets that claimed a build history point to the record instead (P2-2, P2-3). `engineering.md`'s build section opens with the dispatch condition (P2-4). The AD-1152 golden, which embeds all of it, and the AD-1200 request fingerprints, which hash it, are refreshed by measurement in the same commit (P2-5, P2-6). A new test file composes the real orders through the real loader, and through the real step router, and checks the three files against each other and the 27 against one claim shape (M1, N2-1). Nothing in `src/` changes.

## 3. Decisions

All five are inside the delegated envelope: each cites its evidence, the change is text and two fixtures (backward compatible), no refusal, approval, audit or privacy control is touched (D3), only OSS files change, and the rollback is one revert of M2 (the three files, the two fixtures and the marker's removal together).

### D1. Placement and composition

The loader (`standing_orders.py:445-558`) composes, in order: (1) the agent's hardcoded identity; (1.5) the crew personality block from the seed profile; (2) `federation.md`; (3) `ship.md`; (4) `{department}.md`; (5) `{agent_type}.md`; (5.5) task-contextual orders (`config/task_orders/*.md`, only with a `task_type` and a wired task context); (6) active directives; (7) `<available_skills>`; the parts are joined by `\n\n---\n\n` and `{Billet Title}` templates are resolved last when a registry is wired. The docstring puts the Constitution highest, then ship, department, agent (`:6-9`). There is no size or token check in the loader. `ship.md` is loaded for every agent type with no condition (`:491-494`): on the base 23 of 23 composed texts hold the Ship tier, and on the head each holds the new section, the Software Engineer, Architect, Counselor and Yeoman (each with a personal file) and a type with no orders file included. The step router (AD-651) filters the composed text by `<!-- category: x -->` tags when `step_instruction.enabled` is true (`config/system.yaml:2243-2244`, off today), and keeps `identity`, `chain_of_command`, `core_directives` and `encoding_safety` in every step (`knowledge.py:227-232`).

| # | Option | Judgement |
|---|---|---|
| 1 | `ship.md`, first section, tag `core_directives` (chosen) | Reaches every composed prompt (measured), outranks the department and personal tiers in the loader's own order, and stays in every step the router is configured for when it is on (T2; today only ANALYZE and COMPOSE call `get_step_instructions`: `rg -l`), and the ship tier stays writable by the build boundary (D3); +1,139 bytes |
| 2 | `ship.md`, last section, with a new tag or none | A tag outside `universal_categories` is dropped from the steps that do not list it (`step_instruction_router.py:107`); an untagged section inherits the last marker, `duty_reporting` (`:159-176`), and analyze, evaluate and reflect lose it |
| 3 | `engineering.md` only | Reaches three of the 18 crew types (`builder`, `code_reviewer`, `engineering_officer`); the issue asks for a crew-wide rule |
| 4 | A new orders file | The loader reads fixed names (`federation.md`, `ship.md`, `{department}.md`, `{agent_type}.md`: `:487-503`); a new name needs a loader change this fix does not need |

Chosen: option 1 (it is the only one that is crew-wide, survives the router and needs no code). **Cost, in bytes of the composed text (UTF-8, measured in memory over the head text):** +1,139 for every agent type; +352 more for the Engineering department (`builder`, `code_reviewer`, `engineering_officer` and the SWE specialists mapped to it, `standing_orders.py:42-50`); +474 more for `builder`.

| agent_type | before | after | delta | share |
|---|---|---|---|---|
| training_officer (the smallest real type) | 46,511 | 47,650 | +1,139 | 2.45% |
| architect | 54,681 | 55,820 | +1,139 | 2.08% |
| code_reviewer | 51,756 | 53,247 | +1,491 | 2.88% |
| engineering_officer | 54,656 | 56,147 | +1,491 | 2.73% |
| builder (the largest) | 59,524 | 61,489 | +1,965 | 3.30% |

The other 18 types measured gain 1,139 each (2.05% to 2.47%). **Which caps or gates count the composed prompt:** none caps it. The loader and `_decide_via_llm` hold no length check (section 11). Two places count it: the DM turn's context manifest records `system_prompt_chars` (`context_manifest.py:388`, recorded and never compared), and the SWE harness's tier eligibility estimates `len(system_prompt) // 4` tokens against the model's window (`loop_tier_steps.py:229-236`, `tier_policy.py:194-228`; `LONG_CONTEXT_THRESHOLD = 100_000`, `:37`): +285 tokens (+491 for the builder) on prompts of about 11,600 to 15,400 tokens at that estimate, far under both. The text reaches utility agents' prompts too: there is no crew-only tier (L5).

### D2. Wording, and what the 27 files say

| # | Option | Judgement |
|---|---|---|
| 1 | The issue's four elements, the Captain's Forge sentence, and one clause: code written in the member's own workspace for a task they were given is not a change to ProbOS (chosen) | Crew do write and run code for the Captain's tasks (`dm_agentic.enabled`, `execution.workspace_root`); without the clause "Crew do not build ... code" can be read as a refusal of that work; 75 bytes; the clause is the first bullet's second sentence and can be deleted alone |
| 2 | The four elements only | Smallest; risks over-refusal of workspace tasks, which the live check as written would not catch |
| 3 | A manual under `config/manuals/` and a pointer | Not composed into the prompt: the crew would not read it unless they look it up; a second place to keep true |

Chosen: option 1. The wording is short, imperative, names no model, is ASCII and names no issue number (T5). **The enumeration**, run on `430423e1` from the repository root:

```
rg -n -i "\b(build|builds|built|building|implement|implements|implemented|implementing|ship|ships|shipped|shipping|commit|commits|committed|committing|merge|merges|merged|merging|deploy|deploys|deployed|deploying)\b" --glob "config/standing_orders/*.md" .
  -> 122 lines in 17 of the 27 files; 85 of them hold only the noun "ship"/"ships" (the vessel); the other 10 files have no hit
rg -n -i "\b(build|builds|built|building|implement|implements|implemented|implementing|implementation|commit|commits|committed|committing|merge|merges|merged|merging|deploy|deploys|deployed|deploying|shipped|shipping)\b|\bship (it|a|the (code|change|fix|feature))\b" --glob "config/standing_orders/*.md" .
  -> 39 lines in 11 files (architect 7, builder 9, counselor 2, engineering_officer 2, engineering 3, federation 8, introspect 1, pathologist 1, research_specialist 1, ship 4, system_qa 1)
rg -n -i "\b(fix|fixes|fixed|patch|modify|modifies|modified|write code|code change|pull request|repository|branch|git|self-modif\w*)\b" over the same files (read for the same shape)
```

| File:lines | What it says | Verdict | Reason |
|---|---|---|---|
| builder.md:6 | "...and build solutions that work." | CHANGE (P2-2) | True only for a dispatched build; the line holds a non-ASCII character, so no pair can name it, and P2-2 qualifies it in the paragraph after it (L3) |
| builder.md:62, :63 | "You've built enough to know where the pitfalls are."; "...evidence from builds you've run." | CHANGE (P2-3) | A build history the record may not show: the very claim item 3 forbids; the personal tier is read after the ship tier |
| builder.md:9, :10, :17, :19, :21, :49 | spec before you build; before implementing; learn from every build; the evidence and portability rules; the spec's file footprint | LEAVE | Duties during a build, conditional on a spec (a dispatch); `:9` holds the sentence AD-1359's test pins |
| engineering.md:54 (bullets :56-60) | "Build Pipeline Standards" | CHANGE (P2-4) | The standards of a dispatched build; one bullet states the condition and the bullets stay |
| engineering.md:27 | "When implementing a `typing.Protocol`..." | LEAVE | A code standard for whoever writes the code |
| ship.md:36, :49 | "the crew builds a multi-agent investigation" | LEAVE | Figurative; AD-1120's test slices this section |
| ship.md:62 | "build dispatcher" (the startup list) | LEAVE | States the dispatch path the new section relies on |
| ship.md:97 | "Every write is a git commit." | LEAVE | Ship's Records is a separate store; the section says "the ProbOS repository" to keep them apart |
| architect.md:12-13, :19, :22, :41, :44, :46 | build prompts; dispatching a dependency group of prompts; "You do NOT write code. You write specifications and build prompts." | KEEP | The Architect specifies, a crew role in the rule; `:44` already states it. "Dispatching" there is the prompt hand-off, not the Captain's dispatch of a build |
| research_specialist.md:24 | "You do NOT implement changes -- implementation flows through Engineering..." | KEEP | Already the rule for its role |
| introspect.md:8 | "Distinguish between what is implemented and what is planned." | KEEP | The honesty the future-capability line asks for |
| federation.md:81 | "Cannot implement? Research thoroughly." | KEEP | Prior art that agrees; the Constitution is not edited (D3) |
| federation.md:42, :65, :117, :292, :294, :369, :458; counselor.md:12, :98; engineering_officer.md:14, :29; pathologist.md:12; system_qa.md:6 | figurative builds; a quoted example of counselling; the Chief's spec check before a build; the word "implementation"; "ship A" | LEAVE | Not a statement that crew build code (`engineering_officer.md:14` is a review duty) |
| the other 85 lines of the first command | the noun "ship" | LEAVE | The vessel |
| read for the same shape: engineering_officer.md:6, :9, :33; diagnostician.md:13; red_team.md:13 | "then act"; "the next engineer to touch this code might be you"; "hands-on"; "You do NOT modify code directly. You prescribe fixes."; "You do NOT modify the systems you verify." | LEAVE for the first three (L4); KEEP for the other two | Principles and personality, not capability claims; the last two already say the rule |

### D3. What pins the standing orders today

| Pin | Where | Does this change break it? | What the contract does |
|---|---|---|---|
| **Golden text:** the AD-1152 OFF golden holds the native builder's composed prompt, 59,753 characters, with `federation.md`, `ship.md`, `engineering.md` and `builder.md` verbatim once each, and a digest of the whole observation | `tests/fixtures/ad1152_agentic_off_golden.json:15, :760`; compared by `test_default_off_matches_pinned_base` and `test_default_off_golden_pins_only_descriptor_owner_platform[linux, win32]` (`test_ad1152_agentic_correlation.py:528-595`) | **Yes: three tests** (by reading, not run) | P2-5 refreshes the string and the digest by measurement in the M2 commit (the AD-1359 precedent, `b647032a`); two lines change; `default_config_sha256` is untouched; the golden's only other consumer, `test_ad1152_crew_token_usage.py:1229-1230`, reads the field names of one result, which do not change (it is in G2). Rejected: composing the harness without orders (weakens the oracle); regenerating the golden from the code under test (not an oracle); quarantine |
| **AD-1200 request fingerprints** (A1; the first reading missed them: they hold hashes, not text): the byte count and sha256 of each request the native builder sends, which embed `federation.md`, `ship.md`, `engineering.md` and `builder.md` | `tests/fixtures/ad1200_no_instructions_golden.json` (ten `requests` values: the `native/*` cases repository (two requests), missing, unscoped and installed, in the legacy and the structured mode); compared by `test_no_instructions_actual_requests_match_pinned_base` (`test_ad1200_repository_instruction_wire.py:324-328`) | **Yes: one test** (the oracle's G2 on M2's head failed it) | P2-6 refreshes the ten values in the M2 commit by running the test's own capture, as AD-1359 did after its gate caught the same test (`182d79ff`: "the native builder's requests embed builder.md and engineering.md"). Measured on the oracle: each of the ten grows by 1,987 bytes, which is exactly the JSON-escaped length of the 1,965 characters M2 adds to the three files (ship +1,139, builder +474, engineering +352), so nothing but the orders moved; the work-item, result and trace values are unchanged. Rejected: leaving it red for the broad gate (M2 must leave no failing test); decoupling the test from the real orders (a change to AD-1200's oracle: L14) |
| AD-1359's key phrases on the composed Builder prompt | `test_ad1359_agent_size_rules.py:44` | No | The three phrases (`builder.md:9`, `:12`, `:13`) are untouched |
| Phrase pins on the real `ship.md`: DM self-monitoring, Cognitive Zones, Self-Monitoring, the `peer_observation.md` and `AD-729a` cross-reference, the router's ten markers | `test_ad614...:207`, `test_graduated_zones.py:588`, `test_self_monitoring.py:723`, `test_ad729a...:73-75`, `test_ad651...:224-237` | No | Nothing is removed; one `core_directives` marker is added |
| AD-1120's slice of "Ground Before You Collaborate" must be capability-gap clean | `test_ad1120_ground_before_collaborate.py:357-375` (sliced to the next `\n##` or `\n<!--`) | No | The new section sits before it; T6 gives the new section the same check |
| Size budgets | none for `config/standing_orders`: `INSTRUCTION_FILE_BYTES = 8192` and `CONSTITUTION_CAP_BYTES = 18_000` govern the `.github` instruction files (`security/file_access.py:676`, `test_standing_orders_layout.py:61, 312-339`) | No | None; `ship.md` is 17,381 bytes in git and `federation.md` 28,404, so no cap applies |
| A digest or hash of the orders (at boot, in a store, a ledger, a manifest) | none: the seven `src` files that name the orders and a hash function hash other things (section 11); `file_durations.json`'s `collection_sha256` is a measurement record, not a gate | No | None |
| **AD-1344**, the Constitution write refusal | `constitution_write_refusal` names `federation.md` only (`standing_orders.py:110-111`, `builder_paths.py:158`) | No: `ship.md` is not protected; `test_ad1344...:481-488` (T20) pins that the native build still modifies the ship tier, `:160-162` lists `ship.md` and `engineering.md` as neighbours that stay writable, and `test_bf894...:30-32` lists both as legitimate paths | The engineering pipeline's change meets neither refusal: no refused writer is in its path (D3 note), and the diff names no `federation.md`; `test_ad1344`'s autouse guard compares `federation.md`'s bytes and mode, and Diff Reviewer property 3 checks the diff |
| **BF-943**, the Captain-document refusal | `CAPTAIN_DOCUMENT_PATHS` lists `config/standing_orders/` (`builder_paths.py:210-212`) | No | It is applied by `FileWriterAgent`, the SWE harness `write_file` and `edit_file` and the docx, pptx and xlsx writers (section 11), and its text says the other files change "through a build the Captain reviews": this change is that route (a pull request) |

D3 note: the refusals are called from `file_writer.py:112-116, :159-163`, `skill_framework.py:210-214, :270-274, :425-429, :558-562`, `swe_harness/tools.py:1065-1069, :1162-1166`, `builder_paths.py:523` (the native build, constitution only) and `copilot_adapter.py:322`; the Builder agent edits the worktree with its own file tools and none of these is in its path. Chosen for the golden: P2-5, because the fixture is a measurement of the real prompt and a measurement is refreshed by measuring. Chosen for the AD-1200 values: P2-6, which measures the real requests with the test's own capture and refuses any change that is not a native request value.

### D4. The pin tests

| # | Option | Judgement |
|---|---|---|
| 1 | The real loader over the repository's orders: the section in each crew member's Ship tier (T1), through the real step router (T2), the three files against each other by key phrases (T3), a claim scan over all 27 with controls (T4), hygiene (T5, T6), and a control per premise (chosen) | Crosses the seams the crew use (`compose_instructions`, `get_step_instructions`, the router, `standing_order_names`); no mock of the loader or of a read; the controls make each check able to fail |
| 2 | A golden of the section's whole prose | Any edit of a word breaks it, and it cannot tell a required line from the shipped one |
| 3 | A substring test of `ship.md` alone | No composition seam: it passes with the section mis-tagged (dropped under the router) or in a file the loader does not read |

Chosen: option 1. **T4's discrimination:** on the base the scan flags exactly two sentences in the 27 files, `builder.md:62` and `:63` (measured), and none on the head; C1 plants four claims and spares three near misses (a qualified sentence, a duty, a quoted example); rows 6, 7 and 9 of section 9 re-plant a claim, in `builder.md` and in `security_officer.md`, and T4 alone fails. The five lessons of BF-935's contract, applied: (1) every pytest count is "expected" and L13 says what is unchecked; (2) the assignments to the loader's module globals and the setters in `tests/` were listed with `rg` (section 11): those read restore with `try/finally` or `monkeypatch` or reset to `None` afterwards, and the one that is never undone is `register_department("new_test_agent...")` (`test_standing_orders.py:150`, `test_ad429e_dict_migration.py:170`), a key no case here uses; I did not read every teardown, so the new file's autouse fixture points the loader at the repository's directory and unwires every module global with `monkeypatch` (which restores them), `conftest.py:199-215` clears the loader's caches before each test, and G2 is named in suite order; (3) every SEARCH is whole lines starting at a line start; (4) each mutation row names a line that occurs once on M2's head and kills a case of the new file alone; (5) the tests build their own world: the repository's orders, `tmp_path` for the controls, no network, no clock, no model, and no assertion on a double set up by the test.

### D5. Batching

| # | Option | Judgement |
|---|---|---|
| 1 | Separate pull requests, BF-936 first, BF-937 rebased on it, each with its own gate (chosen) | BF-936 is text and two fixtures, with no `src/` and no UI build, and nothing in it waits for BF-937: its Forge sentence is true today (`worktree_manager.py:153-175`). A failure in BF-937's route, UI or persistence guard cannot hold it, and one revert undoes it. It corrects the crew's self-model sooner; the legacy approve control's false claim exists today, so BF-936 first adds no falsehood |
| 2 | One gate and one pull request for both | Saves one broad gate and the one conflict they share (both change `observation_sha256`, golden line 15; BF-937 also moves `default_config_sha256`, line 17, if it changes the persistence default). Costs: BF-936 waits for BF-937's build and review rounds, the UI gates become BF-936's, and a revert is wider |
| 3 | BF-937 first | No dependency requires it; it is the larger change and leaves the false self-model in place longer |

Recommendation: option 1. If the Captain wants one broad gate anyway, stack BF-937's commits on BF-936's M3 head (not the reverse) and run the gate once on the stack, keeping two pull requests. Whichever merges second re-runs P2-5's script (it recomputes `observation_sha256` from the golden it finds) and re-measures on the merged tree; the tracker pairs are applied in merge order. My tracker anchors for BF-937's re-anchoring: `PROGRESS.md`, the title line and the blank line after it; `DECISIONS.md`, the heading line of the entry that follows BF-935's (P3-2).

## 4. Milestones and gates

| M | Blocks | Gate |
|---|---|---|
| M1 | N1-1 | G1 |
| M2 | P2-1 to P2-4, P2-5 and P2-6 (scripts), then N2-1 (removing the marker) | G2 |
| M3 | P3-1, P3-2, ledger | G3 |

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`. **Size:** one slice (M1 one new file; M2 four pairs, two scripts and one marker pair; M3 two pairs), far below 25 pairs a milestone: no split. **M0:** on the head, record the collected count (`--collect-only -q`) of every existing file named in G2.

- **G1.** `PY -m pytest tests/test_bf936_crew_code_change_orders.py -q -n 0 -p no:randomly`. **Expected: 9 passed** (C1 to C3), **31 xfailed** (T1 to T6). The marker carries `raises=AssertionError, strict=True`: any other exception, or an XPASS, is a FAIL; any other count is a hard stop. Then once with `--runxfail`: each of the 31 must stop at the `assert` section 6 names, never at a premise line.
- **G2.** After P2-5 and P2-6 (the two golden tests fail before them), where the shared venv imports another checkout's source point it at the tree: `PYTHONPATH=<tree>/src`. `PY -m pytest tests/test_ad1120_ground_before_collaborate.py tests/test_ad1152_agentic_correlation.py tests/test_ad1152_crew_token_usage.py tests/test_ad1200_repository_instruction_wire.py tests/test_ad1344_constitution_write_refusal.py tests/test_ad1359_agent_size_rules.py tests/test_ad443_mobility.py tests/test_ad546_native_builder_harness.py tests/test_ad586_task_context.py tests/test_ad614_dm_conversation_termination.py tests/test_ad625_comm_discipline.py tests/test_ad631_skill_effectiveness.py tests/test_ad651_step_instruction_router.py tests/test_ad729a_peer_observation_standing_orders.py tests/test_ad893_standing_orders_api.py tests/test_ad910_yeoman_standing_orders.py tests/test_bf186_compose_standing_orders.py tests/test_bf213_proactive_action_vocabulary.py tests/test_bf894_builder_write_boundary.py tests/test_bf910_standing_orders_lookup.py tests/test_bf936_crew_code_change_orders.py tests/test_bf943_captain_document_write_refusal.py tests/test_cognitive_skill_596b.py tests/test_copilot_adapter.py tests/test_graduated_zones.py tests/test_memory_integrity.py tests/test_personality_wiring.py tests/test_provenance_boundary.py tests/test_self_monitoring.py tests/test_standing_orders.py tests/test_standing_orders_layout.py -q -n 0 -p no:randomly` (the files in alphabetical order, the new file at its place: the files that read or compose the real orders, the golden, the write refusals that name them, the router and the layout test: section 11). **Expected:** the new file 40 passed; every other file 0 failed and collected counts equal M0.
- **G3.** `PY -P scripts/gen_ad_ledger.py`; then `PY -P scripts/gen_ad_ledger.py --check`; then `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`.
- **Harness rule.** No source change made to pass a test, no skip, no loosened assertion. A failing case of the new file at G2 (any line), or any existing test failing, goes back to the Architect. The broad gate runs once, in the main session, with `--receipt`. There is no `src/` change, so the architecture check is not part of G2.

## 5. Commit messages

- **M1:** `BF-936 M1: tests that the standing orders tell the crew what they can do about code changes, xfail until written (#1677)`
- **M2:** `BF-936 M2: the ship, builder and engineering orders say crew propose, review, specify and verify and build only on a Captain-dispatched build; the AD-1152 and AD-1200 fixtures are refreshed (#1677)`
- **M3:** `BF-936 M3: trackers and ledger (#1677)`; its body ends with the line `Closes #1677.` (the closure comment hands over section 15).

## 6. Tests (`tests/test_bf936_crew_code_change_orders.py`)

| Id | Cases | Covers (function) | xfail until |
|---|---|---|---|
| C1 | 7 | Control: the scan flags a claim with no dispatch and spares the rest (`test_the_scan_flags_a_claim_with_no_dispatch_and_spares_the_rest`) | none |
| C2 | 1 | Control: the real loader over a directory of its own, orders without and with the section (`test_the_check_fails_on_orders_without_the_section_and_holds_on_orders_with_it`) | none |
| C3 | 1 | Control: step routing is on and filters (`test_step_routing_drops_a_section_whose_tag_the_step_does_not_list`) | none |
| T1 | 20 | Class: the section is in each crew member's Ship tier through `compose_instructions`: the 18 crew types of the seed profiles and the tier list, the Yeoman, and a type with no orders file (`test_the_section_is_composed_into_each_crew_members_ship_tier`) | M2 |
| T2 | 4 | Class: the section survives `get_step_instructions` with the router on, in each step the router is configured for (analyze, compose, evaluate, reflect) (`test_the_section_survives_step_routing_when_it_is_on`) | M2 |
| T3 | 2 | Class: `builder.md` and `engineering.md` agree with the section, by key phrases (`test_the_builder_and_engineering_orders_agree_with_the_crew_wide_section`) | M2 |
| T4 | 1 | Class: none of the 27 files claims a build with no dispatch (`test_no_standing_order_claims_a_build_with_no_dispatch`) | M2 |
| T5 | 3 | Class: the new text is ASCII and names no issue number, in the three files (`test_the_new_text_is_ascii_and_names_no_issue_number`) | M2 |
| T6 | 1 | Class: the section is capability-gap clean (`test_the_section_is_capability_gap_clean`) | M2 |

**How each xfail case fails on the base.** T1 at `assert _carries(tier), ...` (the premise before it, that the Ship tier is composed, holds); T2 at `assert _carries(routed), ...`; T3 at `assert not missing, ...`; T4 at `assert not found, found` (the two sentences of `builder.md:62-63`); T5 at `assert added, ...` (the new text is absent from each file); T6 at `assert section, ...`. The three controls pass on the base: C1 and C2 build their own input, and C3 reads `ship.md`'s existing `situation_assessment` section.

## 7. The contract

Every SEARCH below occurs exactly once in its file at its turn, starts at a line start and is ASCII; I checked this by applying the blocks in memory to the LF blobs, in label order, under both readings of a block's final newline (kept and dropped), which give identical files (section 11).

### 7.1 M1

**N1-1.** New file `tests/test_bf936_crew_code_change_orders.py`:

```python
"""BF-936 (#1677): the standing orders tell the crew what they can do about code changes.

The real loader (``compose_instructions`` and ``get_step_instructions``) runs over this repository's own
``config/standing_orders``, the files the crew are composed from: no mock of the loader, of a file read or of the
composition, and no model is called. The class holds the cases the unwritten orders fail; the functions before it pass
on both trees (they are the controls). No BF-936 name is imported.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from probos.cognitive import standing_orders
from probos.cognitive.decomposer import is_capability_gap
from probos.cognitive.standing_orders import compose_instructions, get_step_instructions, standing_order_names
from probos.cognitive.step_instruction_router import StepInstructionRouter
from probos.config import AgentTierConfig, StepInstructionConfig

ORDERS = Path(__file__).resolve().parents[1] / "config" / "standing_orders"
HEADING = "## What Crew Can Do About Code Changes"
_PROFILES = sorted(p.stem for p in (ORDERS / "crew_profiles").glob("*.yaml") if not p.stem.startswith("_"))
# Every crew type the product names (the seed profiles and the tier list), the Yeoman (a personal file and no profile) and a
# type that has no orders file at all.
CREW = sorted({*_PROFILES, *AgentTierConfig().crew_types, "yeoman"}) + ["a_type_with_no_orders_file"]
# The steps the router is configured for ("query" is deterministic and takes no orders). Today ANALYZE and COMPOSE are the
# steps that call get_step_instructions; EVALUATE and REFLECT list categories but build their own prompts.
STEPS = [step for step in StepInstructionConfig().step_categories if step != "query"]
PHRASES = (  # one for each part of the rule; a text is flattened to single spaces before they are looked for
    "propose improvements, review designs, specify acceptance tests",
    "Crew do not build, commit or merge code to the ProbOS repository on their own initiative",
    "Changes to the ProbOS repository are made by the engineering pipeline under the Captain's direction",
    "Forge can build a candidate when the Captain dispatches a build; it is not merged until the GitHub delivery route exists",
    "Agent self-modification requires the Captain's approval",
    "only when the record shows you did it",
    "a direction, not a date",
)
_CLAIM = re.compile(r"you've built|builds you've run|\bi(?:'ll| will) (?:implement|build|merge|ship|commit)\b", re.IGNORECASE)


def _flat(text: str) -> str:
    return " ".join(text.split())


def _sentences(text: str) -> list[str]:
    return re.split(r"(?<=[.!?])\s+", _flat(text))


def _section(text: str) -> str:
    """The section's text, flattened, from its heading to the next category marker or heading; "" when there is none."""
    start = text.find(HEADING)
    if start < 0:
        return ""
    rest = text[start + len(HEADING):]
    cuts = [i for i in (rest.find("\n<!--"), rest.find("\n## ")) if i != -1]
    return _flat(rest[: min(cuts)] if cuts else rest)


def _carries(text: str) -> bool:
    section = _section(text)
    return all(phrase in section for phrase in PHRASES)


def _unqualified_claims(text: str) -> list[str]:
    """The sentences that claim a build, or promise one, with no dispatch in the same sentence (a quoted example is no claim)."""
    claims = []
    for sentence in _sentences(text):
        unquoted = re.sub(r'"[^"]*"', " ", sentence)
        if _CLAIM.search(unquoted) and "dispatch" not in unquoted.lower():
            claims.append(sentence)
    return claims


@pytest.fixture(autouse=True)
def _the_repository_orders_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """The loader reads this repository's orders, and nothing that another test wired into the module is in the way."""
    monkeypatch.setattr(standing_orders, "_DEFAULT_ORDERS_DIR", ORDERS)
    for name in ("_directive_store", "_skill_catalog", "_billet_registry", "_task_context", "_step_router"):
        monkeypatch.setattr(standing_orders, name, None)
    standing_orders.clear_cache()


@pytest.mark.parametrize(
    ("sentence", "flagged"),
    [
        ("You've built enough to know where the pitfalls are.", True),
        ("You back your opinions with evidence from builds you've run.", True),
        ("I will merge the change myself.", True),
        ("I'll implement it tonight, and then I'll ship it.", True),
        ("You build only when the Captain dispatches a build, and you've built nothing else.", False),
        ("Understand the spec before you build.", False),
        ('Say "I\'ll implement it" only when the record shows you did.', False),
    ],
)
def test_the_scan_flags_a_claim_with_no_dispatch_and_spares_the_rest(sentence: str, flagged: bool) -> None:
    assert bool(_unqualified_claims(sentence)) is flagged


def test_the_check_fails_on_orders_without_the_section_and_holds_on_orders_with_it(tmp_path: Path) -> None:
    """Control: the same real loader over a directory of its own, so a pass in the class cannot come from the check."""
    bare, full = tmp_path / "bare", tmp_path / "full"
    for directory, text in (
        (bare, "# Ship Standing Orders\n\nOther orders only.\n"),
        (full, f"{HEADING}\n\n" + "\n".join(PHRASES) + "\n"),
    ):
        directory.mkdir()
        (directory / "ship.md").write_text(text, encoding="utf-8")
    composed_bare = compose_instructions("builder", "", orders_dir=bare)
    composed_full = compose_instructions("builder", "", orders_dir=full)
    assert "Other orders only." in composed_bare and not _carries(composed_bare)
    assert _carries(composed_full)


def test_step_routing_drops_a_section_whose_tag_the_step_does_not_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """Control: with the router on, a section survives a step only through its tag, so T2 is not vacuous."""
    assert "core_directives" in StepInstructionConfig().universal_categories, "premise: the tag the section carries is universal"
    monkeypatch.setattr(standing_orders, "_step_router", StepInstructionRouter(StepInstructionConfig(enabled=True)))
    kept = get_step_instructions(agent_type="builder", hardcoded_instructions="", step_name="analyze")
    dropped = get_step_instructions(agent_type="builder", hardcoded_instructions="", step_name="compose")
    assert "## Startup Sequence" in kept and "## Startup Sequence" not in dropped


class TestTheCrewKnowWhatTheyMayDoAboutCodeChanges:
    # BF-936 M1: xfail until M2 writes the orders (M2 removes this line and the next).
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-936 M2 writes the orders")

    @pytest.mark.parametrize("agent_type", CREW)
    def test_the_section_is_composed_into_each_crew_members_ship_tier(self, agent_type: str) -> None:
        composed = compose_instructions(agent_type=agent_type, hardcoded_instructions="")
        assert "## Ship Standing Orders\n\n" in composed, "premise: the ship tier is composed"
        tier = composed.split("## Ship Standing Orders\n\n", 1)[1].split("\n\n---\n\n", 1)[0]
        assert _carries(tier), f"{agent_type}: the ship tier lacks the section or one of its phrases"

    @pytest.mark.parametrize("step", STEPS)
    def test_the_section_survives_step_routing_when_it_is_on(self, monkeypatch: pytest.MonkeyPatch, step: str) -> None:
        monkeypatch.setattr(standing_orders, "_step_router", StepInstructionRouter(StepInstructionConfig(enabled=True)))
        routed = get_step_instructions(agent_type="builder", hardcoded_instructions="", step_name=step)
        assert _carries(routed), f"step {step}: the routed orders lack the section or one of its phrases"

    @pytest.mark.parametrize(
        ("name", "phrases"),
        [
            (
                "builder",
                (
                    "You build only when the Captain dispatches a build",
                    "not merged until the GitHub delivery route exists",
                    "only when the record shows you did it",
                ),
            ),
            (
                "engineering",
                (
                    "a build the Captain dispatches",
                    "not merged until the GitHub delivery route exists",
                    "Engineering crew propose, review, specify and verify changes",
                ),
            ),
        ],
    )
    def test_the_builder_and_engineering_orders_agree_with_the_crew_wide_section(
        self, name: str, phrases: tuple[str, ...],
    ) -> None:
        text = _flat((ORDERS / f"{name}.md").read_text(encoding="utf-8"))
        missing = [phrase for phrase in phrases if phrase not in text]
        assert not missing, f"{name}.md lacks {missing}"

    def test_no_standing_order_claims_a_build_with_no_dispatch(self) -> None:
        names = standing_order_names(ORDERS)
        assert {"builder", "engineering", "ship"} <= set(names), "premise: the scan reads the orders the crew are composed from"
        found = {
            name: hits
            for name in names
            if (hits := _unqualified_claims((ORDERS / f"{name}.md").read_text(encoding="utf-8")))
        }
        assert not found, found

    @pytest.mark.parametrize("name", ["ship", "builder", "engineering"])
    def test_the_new_text_is_ascii_and_names_no_issue_number(self, name: str) -> None:
        text = (ORDERS / f"{name}.md").read_text(encoding="utf-8")
        added = (
            _section(text)
            if name == "ship"
            else " ".join(s for s in _sentences(text) if "dispatch" in s or "the record" in s)
        )
        assert added, f"{name}.md: the new text is absent"
        assert added.isascii(), f"{name}.md: the new text is not ASCII"
        assert not re.search(r"\b(?:AD|BF)-\d+\b|#\d+", added), f"{name}.md: the new text names an issue number"

    def test_the_section_is_capability_gap_clean(self) -> None:
        section = _section((ORDERS / "ship.md").read_text(encoding="utf-8"))
        assert section, "the section is absent"
        assert is_capability_gap(section) is False
```

### 7.2 M2

**P2-1.** `config/standing_orders/ship.md`
SEARCH:
```
These orders apply to all agents aboard this ProbOS instance.

<!-- category: core_directives -->
## Import Conventions
```
REPLACE:
```
These orders apply to all agents aboard this ProbOS instance.

<!-- category: core_directives -->
## What Crew Can Do About Code Changes

What crew do today: propose improvements, review designs, specify acceptance tests and how success will be measured, and verify changes after they land.

What crew do not do yet:
- Crew do not build, commit or merge code to the ProbOS repository on their own initiative. Code you write in your own workspace for a task you were given is not that.
- Changes to the ProbOS repository are made by the engineering pipeline under the Captain's direction.
- Forge can build a candidate when the Captain dispatches a build; it is not merged until the GitHub delivery route exists.
- Agent self-modification requires the Captain's approval.

Do not record build work as your own. Say or note that you implemented, fixed or shipped a change only when the record shows you did it. Offer specifications and review instead: "the change should ...", not "I'll implement ...".

Self-build is a direction, not a date. Crew review, acceptance and building of approved proposals is coming under graduated authority; treat it as a future capability until the Captain announces it.

<!-- category: core_directives -->
## Import Conventions
```

**P2-2.** `config/standing_orders/builder.md`
SEARCH:
```
## Your Standards
```
REPLACE:
```
You build only when the Captain dispatches a build. A dispatched build ends as a candidate branch, and it is not merged until the GitHub delivery route exists. Outside a dispatched build you propose, review, specify and verify, like the rest of the crew, and you say or note that you implemented, fixed or shipped a change only when the record shows you did it.

## Your Standards
```

**P2-3.** `config/standing_orders/builder.md`
SEARCH:
```
- You share practical experience. You've built enough to know where the pitfalls are.
- You have opinions about code quality and you back them with evidence from builds you've run.
```
REPLACE:
```
- You share practical experience. You know where the pitfalls are from the builds and reviews the record shows you took part in; where it shows none, say so.
- You have opinions about code quality and you back them with evidence you can point to in the record: builds, reviews, test results.
```

**P2-4.** `config/standing_orders/engineering.md`
SEARCH:
```
## Build Pipeline Standards

```
REPLACE:
```
## Build Pipeline Standards

- These standards apply to a build the Captain dispatches. A dispatched build ends as a candidate branch, and it is not merged until the GitHub delivery route exists. Outside a dispatched build, Engineering crew propose, review, specify and verify changes; the engineering pipeline makes changes to the ProbOS repository under the Captain's direction.
```

**P2-5 (a script, not a pair).** `tests/fixtures/ad1152_agentic_off_golden.json`. The golden's one prompt string (line 760) holds the three files verbatim, once each, and line 15 holds the digest of the whole observation. Run this once from the repository root, after P2-1 to P2-4 are applied on disk and before M2 is committed (`HEAD` must still hold the old files). It asserts its premises, makes one replacement per file, recomputes the digest the test computes (`_json_bytes`, `test_ad1152_agentic_correlation.py:59-60`) and rewrites the file with the serialisation that reproduces the current file byte for byte. It never writes `default_config_sha256`, so it can be run again after another change has moved the observation.

```python
import hashlib
import json
import pathlib
import subprocess

GOLDEN = pathlib.Path("tests/fixtures/ad1152_agentic_off_golden.json")
NAMES = ("ship", "builder", "engineering")


def loaded(text: str) -> str:
    """What standing_orders._load_file returns for a file: LF newlines, stripped."""
    return text.replace("\r\n", "\n").strip()


def observation_bytes(value: object) -> bytes:
    """The test's own _json_bytes."""
    return json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("ascii")


old = {
    name: loaded(
        subprocess.run(
            ["git", "show", f"HEAD:config/standing_orders/{name}.md"],
            capture_output=True, check=True, text=True, encoding="utf-8",
        ).stdout
    )
    for name in NAMES
}
new = {name: loaded(pathlib.Path(f"config/standing_orders/{name}.md").read_text(encoding="utf-8")) for name in NAMES}
assert all(old[name] != new[name] for name in NAMES), "premise: P2-1 to P2-4 are on disk and HEAD holds the old files"
before = GOLDEN.read_text(encoding="utf-8").replace("\r\n", "\n")
golden = json.loads(before)
assert json.dumps(golden, indent=2, ensure_ascii=True) + "\n" == before, "premise: the file re-serialises byte for byte"
assert (
    hashlib.sha256(observation_bytes(golden["observation"])).hexdigest() == golden["observation_sha256"]
), "premise: the stored digest is the stored observation's"
replaced = dict.fromkeys(NAMES, 0)


def walk(value):
    if isinstance(value, str):
        for name in NAMES:
            replaced[name] += value.count(old[name])
            value = value.replace(old[name], new[name])
        return value
    if isinstance(value, dict):
        return {key: walk(item) for key, item in value.items()}
    if isinstance(value, list):
        return [walk(item) for item in value]
    return value


golden = walk(golden)
assert replaced == dict.fromkeys(NAMES, 1), replaced
golden["observation_sha256"] = hashlib.sha256(observation_bytes(golden["observation"])).hexdigest()
GOLDEN.write_text(json.dumps(golden, indent=2, ensure_ascii=True) + "\n", encoding="utf-8", newline="\n")
print("observation_sha256:", golden["observation_sha256"])
```

After it, `git diff -U0 -- tests/fixtures/ad1152_agentic_off_golden.json` must show two hunks only, at lines 15 and 760 (expected: 2 insertions, 2 deletions). On `430423e1` with these pairs the in-memory run gave the digest `ecdfcbba071f402ecfcdb53b6462c120bf1afb22adaca2c4e615d298f72dd754` (expected on the head; it moves with any other change to the observation, L11).

**P2-6 (a script, not a pair; amendment A1).** `tests/fixtures/ad1200_no_instructions_golden.json`. `test_no_instructions_actual_requests_match_pinned_base` pins the byte count and sha256 of the requests the native builder sends, which embed `federation.md`, `ship.md`, `engineering.md` and `builder.md`; ten of its values (the `requests` of the five `native/*` cases in each of the two modes) change when the orders change, as they did for AD-1359 (`182d79ff`). They are hashes, so they are refreshed by running the test's own capture, not by editing text. Run this once from the repository root, after P2-1 to P2-4 are applied on disk (P2-5 does not matter to it). It imports the test file's `_capture_no_instructions`, runs it over a scratch directory with this tree's `src` first on `sys.path` (it asserts that every `probos` module loaded comes from that `src`), refuses to continue unless every key of the file other than `cases` equals the capture, and then replaces, in the file's own text, each `{"bytes": N, "sha256": "..."}` whose value differs from the capture (one occurrence each; it refuses any difference that is not a native request), asserts that the result parses to the capture, and writes it with LF endings. It touches no other character, so it can be run again after another change has moved the native builder's prompt.

```python
import asyncio
import importlib.util
import json
import logging
import pathlib
import shutil
import sys
import tempfile

import pytest

ROOT = pathlib.Path.cwd().resolve()
sys.path.insert(0, str(ROOT / "src"))
GOLDEN = ROOT / "tests" / "fixtures" / "ad1200_no_instructions_golden.json"
TEST = ROOT / "tests" / "test_ad1200_repository_instruction_wire.py"

logging.disable(logging.CRITICAL)
spec = importlib.util.spec_from_file_location("ad1200_wire_capture", TEST)
wire = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = wire
spec.loader.exec_module(wire)
scratch = pathlib.Path(tempfile.mkdtemp())
try:
    with pytest.MonkeyPatch.context() as patch:
        observed = asyncio.run(wire._capture_no_instructions(scratch, patch))
finally:
    shutil.rmtree(scratch, ignore_errors=True)
loaded = [
    pathlib.Path(module.__file__).resolve()
    for name, module in tuple(sys.modules.items())
    if (name == "probos" or name.startswith("probos.")) and getattr(module, "__file__", None)
]
assert loaded and all(path.is_relative_to(ROOT / "src") for path in loaded), "premise: this tree's own source ran"

before = GOLDEN.read_text(encoding="utf-8").replace("\r\n", "\n")
golden = json.loads(before)
assert {k: v for k, v in observed.items() if k != "cases"} == {k: v for k, v in golden.items() if k != "cases"}, "premise: only the case fingerprints can differ"
assert observed["cases"].keys() == golden["cases"].keys(), "premise: the same cases"
text = before
replaced = 0
for case, want in observed["cases"].items():
    for key, value in want.items():
        old = golden["cases"][case][key]
        pairs = list(zip(old, value, strict=True)) if isinstance(value, list) else [(old, value)]
        for was, now in pairs:
            if was == now:
                continue
            assert case.startswith("native/") and key == "requests", ("premise: only a native request embeds the orders", case, key)
            assert text.count(json.dumps(was)) == 1, ("premise: the old fingerprint occurs once", case)
            text = text.replace(json.dumps(was), json.dumps(now))
            replaced += 1
assert json.loads(text) == observed, "the refreshed file is the observation"
GOLDEN.write_text(text, encoding="utf-8", newline="\n")
print("replaced fingerprints:", replaced)
```

**Expected output: one line, `replaced fingerprints: 10`.** After it, `git diff --numstat -- tests/fixtures/ad1200_no_instructions_golden.json` must print `10`, `10` and the path (eight hunks, ten lines changed), every changed value is a `native/*` request, and each of the ten `bytes` has grown by exactly 1,987: the 1,965 characters M2 adds to the three files, JSON-escaped (ship 1,158, builder 476, engineering 353), so nothing but the orders moved. The file is then blob `214261292aa2c4574eceeb3e79bae53144c4e357` (measured on `340d97fe` with these blocks), and `tests/test_ad1200_repository_instruction_wire.py` passes (56 passed).

**N2-1.** `tests/test_bf936_crew_code_change_orders.py`
SEARCH:
```
    # BF-936 M1: xfail until M2 writes the orders (M2 removes this line and the next).
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-936 M2 writes the orders")

    @pytest.mark.parametrize("agent_type", CREW)
```
REPLACE:
```
    @pytest.mark.parametrize("agent_type", CREW)
```

### 7.3 M3: tracking

**P3-1.** `PROGRESS.md`. The anchor is the title line and the blank line after it (once; it survives BF-934's merge, which puts its entry in the same place). Replace `DATE` with M3's date.
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**BF-936 (DATE), #1677 -- the standing orders say what crew can do about code changes.**
- **Base.** No order said who builds ProbOS's code: `builder.md` said the Software Engineer builds ("build solutions that work", "You've built enough", "builds you've run") and `engineering.md` described the build pipeline, both true only for a build the Captain dispatches, so crew offered to implement approved changes themselves and could record them as their own.
- **Fix.** `ship.md`, composed for every agent, gains the section "What Crew Can Do About Code Changes": crew propose, review, specify and verify; they do not build, commit or merge code to ProbOS on their own initiative; Forge can build a candidate when the Captain dispatches a build, not merged until the GitHub delivery route exists; no build work is recorded as one's own unless the record shows it; self-build is a direction, not a date. `builder.md` and `engineering.md` say the same. The AD-1152 golden, which embeds the three files in the native builder's prompt, and the AD-1200 request fingerprints, which hash that prompt, are refreshed by measurement. Contract `prompts/bf-936-crew-code-change-orders.md`. Closes #1677; the check on the running vessel is the Captain's.

```

**P3-2.** `DECISIONS.md`. The anchor is the heading line of the entry that follows BF-935's (once on `430423e1`); the entry is inserted before it, so it lands after BF-935's. **After BF-934's merge the requester re-anchors it**: if BF-934's entry was placed by the same heading, this SEARCH still occurs once and the entry lands after BF-934's; if BF-934 moved or edited that heading, anchor on the last bullet of the BF-934 entry instead. Replace `DATE` with M3's date.
SEARCH:
```
### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```
REPLACE:
```
### BF-936 -- The standing orders say what crew can do about code changes (DATE, #1677)

- *Scope.* `config/standing_orders/ship.md` (a section, first in the file, tagged `core_directives`), `builder.md`, `engineering.md`, the AD-1152 golden and the AD-1200 request fingerprints (both refreshed by measurement), one new test file. Contract `prompts/bf-936-crew-code-change-orders.md`.
- *G1 (where).* The ship tier, first, under the universal tag: every composed prompt carries it (23 types measured), the step router keeps it in every step, and it outranks the department and personal tiers. Rejected: the end of the file (a tag outside the universal list drops it under AD-651, and an untagged section inherits the last marker); `engineering.md` alone (three of 18 crew types); a new orders file (the loader reads fixed names).
- *G2 (what).* The issue's four elements, its Forge sentence replaced by the Captain's wording (a candidate when the Captain dispatches a build, not merged until the GitHub delivery route exists), and one clause: code written in the member's own workspace for a task given to them is not a change to ProbOS. Rejected: the four elements alone (an over-refusal of the Captain's workspace tasks is possible); a manual (not composed).
- *G3 (the other files).* `builder.md` gets a paragraph that states the dispatch condition and two personality bullets that claimed a build history now point to the record; `engineering.md`'s build section opens with the condition. `engineering_officer.md`, `architect.md`, `research_specialist.md` and the other files are left (the contract lists each of the 39 lines that use a build verb); the one follow-up bullet for the Chief Engineer is recorded (L4).
- *G4 (the pins).* The AD-1152 golden embeds the native builder's whole composed prompt; it is refreshed by the AD-1359 procedure, one replacement per file, two lines changed. The AD-1200 fixture holds the byte counts and digests of the native builder's requests; its ten values are refreshed by running the test's own capture (the AD-1359 precedent), and each grew by exactly the JSON-escaped length of the added text. Rejected: composing the harness without orders; regenerating the AD-1152 golden from the code under test.
- *Residual.* L1 to L14 of the contract. *Reversal.* Revert the BF-936 M2 commit (the three files, the two fixtures and the marker's removal together); the tests return to xfail.

### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```

**Ledger.** Run G3. The roadmap Bug Tracker is not edited (`git grep BF-936` finds nothing; it holds no row for the recent BFs, and the generated report's next-free row moves by itself).

## 8. What this does NOT change

`config/standing_orders/federation.md` (AD-1344: the Constitution is not edited by an agent or by this change), the other 24 files of `config/standing_orders` (D2), the crew profiles under `crew_profiles/`, `config/task_orders/`, the skills and the manuals; the loader, the step router and `step_instruction.enabled` (off), the personality block, billet templating; `NativeBuilderHarness` and the visiting builder's prompts (they receive the new text through the loader); `WorktreeManager`, `BuildDispatcher`, the approve route and its UI, and self-improvement versioning (BF-937); the proactive, DM and Ward Room prompts and the proposal block (BF-934); `self_mod` configuration; `builder_paths` and every write refusal (AD-1344, BF-943); `.github/` instruction files; `config/ontology/operations.yaml`'s description of tier 3; the roadmap; the live vessel (section 15). OSS only; no dependency.

## 9. Mutation rows (each Line occurs once, stripped, in its file on M2's head)

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| 1 | config/standing_orders/ship.md | `- Crew do not build, commit or merge code to the ProbOS repository on their own initiative. Code you write in your own workspace for a task you were given is not that.` | `- Crew build, commit and merge code to the ProbOS repository when they judge it right. Code you write in your own workspace for a task you were given is not that.` | T1 (20), T2 (4) |
| 2 | config/standing_orders/ship.md | `- Forge can build a candidate when the Captain dispatches a build; it is not merged until the GitHub delivery route exists.` | `- Forge builds and merges when the work is ready.` | T1 (20), T2 (4) |
| 3 | config/standing_orders/ship.md | `## What Crew Can Do About Code Changes` | the marker line directly above it, `<!-- category: core_directives -->`, becomes `<!-- category: duty_reporting -->` | T2[analyze, evaluate, reflect] only (compose lists `duty_reporting`; T1 reads with the router off) |
| 4 | config/standing_orders/ship.md | `Self-build is a direction, not a date. Crew review, acceptance and building of approved proposals is coming under graduated authority; treat it as a future capability until the Captain announces it.` | delete the line | T1 (20), T2 (4) |
| 5 | config/standing_orders/builder.md | `You build only when the Captain dispatches a build. A dispatched build ends as a candidate branch, and it is not merged until the GitHub delivery route exists. Outside a dispatched build you propose, review, specify and verify, like the rest of the crew, and you say or note that you implemented, fixed or shipped a change only when the record shows you did it.` | delete the line | T3[builder] only (the bullets of "Your Personality" still hold "the record", so T5[builder] stays green) |
| 6 | config/standing_orders/builder.md | `- You share practical experience. You know where the pitfalls are from the builds and reviews the record shows you took part in; where it shows none, say so.` | `- You share practical experience. You've built enough to know where the pitfalls are.` | T4 alone |
| 7 | config/standing_orders/builder.md | `- You have opinions about code quality and you back them with evidence you can point to in the record: builds, reviews, test results.` | `- You have opinions about code quality and you back them with evidence from builds you've run.` | T4 alone |
| 8 | config/standing_orders/engineering.md | `- These standards apply to a build the Captain dispatches. A dispatched build ends as a candidate branch, and it is not merged until the GitHub delivery route exists. Outside a dispatched build, Engineering crew propose, review, specify and verify changes; the engineering pipeline makes changes to the ProbOS repository under the Captain's direction.` | delete the line | T3[engineering], T5[engineering] |
| 9 | config/standing_orders/security_officer.md | `You are the Chief of Security.` | `You are the Chief of Security. You've built enough to know where the pitfalls are.` | T4 alone (the scan reads files other than `builder.md`) |
| 10 | src/probos/cognitive/standing_orders.py | `ship = _load_file(d / "ship.md")` | `ship = ""` | C2, C3, T1 (20), T2 (4) (the check crosses the real loader) |

Hand-driven in memory against the head text (no pytest; the functions of N1-1 executed with a virtual `tmp_path`): each mutant fails exactly the cases its row names and no other, with an `AssertionError` and no other exception; on the unmutated head all 40 pass, and on the base text the 9 controls pass and the 31 class cases fail, each at the assertion section 6 names (section 11). No campaign of record: the Builder runs the ten rows once, on M2's head, with the new file alone; a mutated file is restored before the next row.

## 10. Recorded limits

- **L1.** The text is a prompt: nothing makes a model comply, and the live check (section 15) measures a few prompts, not the rule. The enforcement that exists is in the write boundaries (`merge_to_main` refuses; the AD-1344 and BF-943 refusals) and is untouched.
- **L2.** T4 scans for a closed set of claim shapes (the two sentences of `builder.md:62-63`, and a first-person promise: `I'll` or `I will` followed by implement, build, merge, ship or commit); a build claim in other words, or in a new file, is not caught. The 39 verb lines of D2 were classified by reading, on `430423e1`.
- **L3.** `builder.md:6` still reads "...and build solutions that work." Its line holds a non-ASCII character, so no ASCII pair can name it; P2-2 states the condition in the paragraph right after it, and T3 pins that paragraph.
- **L4.** `engineering_officer.md:6, :9, :33` ("then act", "the next engineer to touch this code might be you", "hands-on") are left. If the live check shows the Chief Engineer answering inconsistently, add under his "Your Boundaries": `- You do not build or merge changes yourself: you review, specify and verify, and a build runs when the Captain dispatches it.` (not applied here).
- **L5.** The section reaches every cognitive agent, crew or not (utility agents and the Captain-dispatched builder included), +1,139 bytes each; there is no crew-only tier.
- **L6.** "Forge" is the seed callsign (`crew_profiles/builder.yaml`); a renamed Software Engineer reads it as another name. Billet templates are not used: with no registry wired (this golden, these tests) a template would stay literal.
- **L7.** "Agent self-modification requires the Captain's approval" is as true as `self_mod.require_user_approval: true` (`config/system.yaml:329`); an operator who sets it false makes the sentence untrue.
- **L8.** The "GitHub delivery route" does not exist yet (AD-1336 child 6). The three sentences say "until it exists" and must change in that AD's change, with the golden.
- **L9.** The router is off in `config/system.yaml:2244`; T2 turns it on with the config model's defaults (`knowledge.py:188-232`), not the vessel's file. An operator who removes `core_directives` from `universal_categories` would filter the section out of the steps that do not list it.
- **L10.** "Propose improvements" is true only once BF-934 (the issue's prerequisite: crew proposals are silently dropped) has merged; this contract assumes it has.
- **L11.** The golden's `observation_sha256` is a function of the whole observation: any other merge that moves it (BF-937's config default moves `default_config_sha256`) needs P2-5 run again on the merged tree. The AD-1200 values are a function of the four orders files and of the native builder's own prompt text: a merge that changes any of them needs P2-6 run again (it is idempotent).
- **L12.** Nothing here is a live-system claim: no vessel and no model was used.
- **L13.** Unchecked, because pytest was not run: collection and the parametrisation ids; the strictness of the xfail marker; the `--dist=loadfile` suite order; `test_ad1152_agentic_correlation.py` against the refreshed golden (a whole-runtime scenario; only its string and its digest were recomputed); the 29 existing files of G2 (only the phrases they pin were checked by hand against the head text); the broad gate. **A1 (2026-11-12):** the oracle has since run the 31 files of G2 on M2's head and 50 further files that name the orders machinery; the only failure was `test_ad1200_repository_instruction_wire.py` (A1, P2-6); the rest of this list is still unmeasured.
- **L14 (A1).** The AD-1200 golden pins the hash of the real orders' text, so every change to the four orders files, or to the native builder's own prompt text, makes `test_no_instructions_actual_requests_match_pinned_base` fail until its ten values are refreshed (AD-1359 and BF-936 both met it, and the broad gate was what caught AD-1359's). A test that pins AD-1200's no-instructions wire shape without the real orders (a fixture orders directory) would end that class of failure; it changes AD-1200's oracle, so it is recorded, not done here.

## 11. Verified Against Codebase (2026-11-12, reading tree `D:\ProbOS-worktrees\bf936-base` at `430423e1`)

**Run by the Architect, read-only (CPython 3.12.13, win32; scripts piped to the interpreter on stdin with `-B` and `PYTHONPATH` the reading tree's `src`; nothing written anywhere but this answer file; no pytest and no test function run by a runner):**

```
git rev-parse HEAD (bf936-base) and origin/main -> both 430423e14ac140f4cb8e37deffa233c9e49f730f; git status of the reading tree empty; git rev-parse HEAD:<path> -> the six blobs of the header
the loader read in full (standing_orders.py:445-558): tiers at :476 (identity), :480, :487, :492, :498, :503, :507-515, :517-525, :527-550, the join at :552, templates at :555-556; get_order_tiers (:164-205) lists the same four file tiers; _load_file is lru_cache(maxsize=32) (:151)
23 agent types composed (compose_instructions(agent_type=t, hardcoded_instructions="")) over the base text and over the head text, with the loader's _load_file replaced in the process; every composed text holds "## Ship Standing Orders" and, on the head, the section: 23 of 23; sizes in D1; the section has no brace, no "---" line, no issue number, and is_capability_gap is False for it and for each new line of builder.md and engineering.md
the golden: json.loads; whole-file occurrences of the tier files inside observation/persisted/native_requests[0]/request/system_prompt: federation 1, ship 1, engineering 1, builder 1, architect 0, counselor 0; that string equals compose_instructions("builder", "", department="engineering") (59,140 characters) plus a 613-character suffix; the file re-serialises byte for byte with json.dumps(indent=2, ensure_ascii=True) + "\n"; the stored digest equals the digest of the stored observation
the P2-5 script text, run in memory over the head text (reads and the golden write intercepted): one replacement per file, lines 15 and 760 the only lines that differ, the prompt string 59,753 -> 61,718 characters (+1,965), the file 97,790 -> 99,777 bytes (LF), `default_config_sha256` unchanged, and the new string equals compose_instructions over the head files plus the old suffix
this file's pairs and new file applied in label order to the LF blobs, in memory: every SEARCH once and at a line start, every block ASCII, every result parses (the test file compiles); the test file's functions driven by hand against the base text (9 controls pass, 31 class cases fail at the assertion named in section 6) and against the head text (all 40 pass); the ten mutants of section 9 as listed there
the pins read in section 3: test_ad1359 (the three phrases are in builder.md at :9, :12, :13), test_ad614, test_graduated_zones, test_self_monitoring, test_ad729a, test_ad651 (markers), test_ad910 (yeoman) -> their phrases are present in the head text
```

**Absence Verified (2026-11-12)**

```
CLAIM: no other open or merged work claims BF-936
RUN:   git log --all --format=%s, matched for BF-936; git grep -n BF-936 on HEAD and on origin/main; prompts/bf-936* in each of the 126 worktrees of git worktree list; git branch -a --list "*936*"; gh issue list --state all --search "BF-936 in:title"; gh issue list --state all --search "BF-936 in:title,body"; gh pr list --state all --search BF-936; rg -n BF-936 over docs/development/roadmap*.md (roadmap.md, roadmap-completed.md, roadmap-era-5-completed.md, roadmap-research.md)
FOUND: 0; 0 and 0; 0; none; #1677 only (OPEN, label bug); #1677, #1678 (BF-937, which names BF-936 as related), #1558 (AD-1336) and three closed ADs matched by words; []; no hit
HOLDS: yes. Highest BF in the tree is not needed: no number is allocated

CLAIM: nothing hashes, budgets or snapshots the orders
RUN:   git grep -l -i standing_orders HEAD -- src, intersected with hashlib|sha256|digest|blake2; the same over tests; rg -n "config/standing_orders" over src scripts config .github ui/src; rg -n "INSTRUCTION_FILE_BYTES" src tests scripts; rg -n "ship\.md|engineering\.md|builder\.md" over src scripts ui/src config (non-md)
FOUND: src: agentic_dispatch, cognitive_agent, swe_harness/tools, crew_enrollment, proactive, routers/agents, runtime; each hashes something else (the user message and the response for the journal at cognitive_agent.py:4645 and :4675, a file snapshot at swe_harness/tools.py:352, a blob at agentic_dispatch.py:4586, a role template at crew_enrollment.py:91-109, Ward Room post ids at proactive.py:1712, an attachment at routers/agents.py:777, the captain card at runtime.py:2825). tests: file_durations.json (a measurement record: collection_sha256 is the digest of the measured run, read by tests/fixtures/duration_scheduler.py and scripts/ci_shards.py as a schema check) and test_ad1229_message_receipts.py (a table digest). INSTRUCTION_FILE_BYTES: security/file_access.py:676, :705-707, :1142, :1215-1223 and test_standing_orders_layout.py (the .github files). The orders are named by the loader, config/ontology/operations.yaml:30, commands_directives.py:51 (display) and three UI test fixtures
HOLDS: yes

CLAIM: nothing caps or gates the composed system prompt on a crew call
RUN:   rg -n "len\(composed\)|len\(system_prompt\)|composed_len|system_prompt_budget|prompt_budget|context_budget" src/probos/cognitive/cognitive_agent.py; rg -n "len\(.*system_prompt|system_prompt_chars|system_prompt.*(truncate|budget|exceed)" src; rg -n "eligibility\.assess\(|prompt_tokens_estimate" src
FOUND: no hit in cognitive_agent.py; context_manifest.py:388 (a recorded count); swe_harness/loop_tier_steps.py:236 (len(system_prompt) // 4 in the SWE harness's tier eligibility) and the callers of RouterEligibility.assess (tier_policy.py:204-228); nothing in the chain steps
HOLDS: yes

CLAIM: no other fixture embeds the orders' text, and no other test pins the files' prose
RUN:   git grep -l -E on distinctive phrases of the three files and of ship.md's sections ("Preserve unrelated Captain work", "Build Evidence and Portability", "Ownership Checks", "Treat wire input as hostile", "Anti-Pattern Awareness", "Ground Before You Collaborate", "Cognitive Zones", "All imports use full module paths") over tracked files outside prompts/ and the trackers; rg for builder.md|engineering.md|ship.md in tests; the tests that call compose_instructions( or get_step_instructions(; rg -l system_prompt tests/fixtures, then a walk over every string of the second file it names for the whole text of each of the four files and the headers "Ship Standing Orders", "Federation Constitution", "Personal Standing Orders" and "Department Protocols"
FOUND: the files themselves, tests/fixtures/ad1152_agentic_off_golden.json, test_ad1120 and test_graduated_zones (their own phrases) and dashboard.html (an unrelated label); the other golden that holds system prompts, tests/fixtures/ad1325_ad1324_flag_off_base.json, holds none of the four files and no tier header (checked in memory); the other tests write tmp copies, read the live file dynamically (test_bf910:803-805, :1287; test_bf943 snapshots bytes and compares) or pin the phrases of section 3
HOLDS: yes for the text; **NOT for the hashes (A1, 2026-11-12).** The walk looked for the files' text, and `tests/fixtures/ad1200_no_instructions_golden.json` holds only the byte count and sha256 of requests that embed it. The oracle's G2 on M2's head failed `test_no_instructions_actual_requests_match_pinned_base`; P2-6 refreshes its ten values.

CLAIM: the rule is not stated in the orders, the skills, the manuals or the task orders
RUN:   rg -n -i "dispatch|candidate branch|delivery route|graduated authority|self-build|own initiative|engineering pipeline|self-modification" config/standing_orders config/skills config/manuals config/task_orders; git grep -n -i "What Crew Can Do About Code Changes|GitHub delivery route" HEAD outside prompts/
FOUND: architect.md:22 ("dispatching" a dependency group of prompts), ship.md:60 and :62 (the startup list), and the self-image-awareness skill (an unrelated dispatch); no hit for the heading or the Forge sentence
HOLDS: yes

CLAIM: neither write refusal is in the engineering pipeline's path
RUN:   rg -n "constitution_write_refusal\(|captain_document_write_refusal\(|builder_write_refusal\(|fix_loop_write_refusal\(" src
FOUND: file_writer.py:112, :116, :159, :163; skill_framework.py:210, :214, :270, :274, :425, :429, :558, :562; swe_harness/tools.py:1065, :1069, :1162, :1166; builder_paths.py:523, :612, :715; builder.py:3396, :3639; copilot_adapter.py:322. The Builder agent edits the worktree with its own file tools; the native build's boundary (builder_write_refusal) refuses federation.md and lets ship.md and engineering.md through (test_bf894:30-32)
HOLDS: yes

CLAIM: ship.md is reached by every composed prompt, the Captain-dispatched builder's included
RUN:   rg -n "compose_instructions\(|get_step_instructions\(" src
FOUND: cognitive_agent.py:4071, :4093, :4365 (the three branches of _decide_via_llm); sub_tasks/analyze.py:63, :241, :466 and sub_tasks/compose.py:82, :204, :247 (chain steps; rg -l get_step_instructions src lists these two modules and the loader only: evaluate.py never calls the loader, and reflect.py calls only _build_personality_block, :113, :201, :283); code_reviewer.py:85; copilot_adapter.py:490; swe_harness/native_builder.py:233
HOLDS: yes

CLAIM: no test leaves a loader global changed in a way that alters the new file's reads (not read teardown by teardown: the new file's fixture makes it independent)
RUN:   rg -n "_DEFAULT_ORDERS_DIR|standing_orders\._(billet_registry|directive_store|skill_catalog|task_context|step_router|load_file|build_personality_block)|_AGENT_DEPARTMENTS" tests; rg -n "set_billet_registry\(|set_directive_store\(|set_skill_catalog\(|set_task_context\(|set_step_router\(|register_department\(" tests; tests/conftest.py:199-215
FOUND: monkeypatch of _DEFAULT_ORDERS_DIR in test_ad1344:287, :300 and test_bf943:96; try/finally restores in test_ad586:98-110, test_ad595c:156-212, test_ad651:178-216; set_skill_catalog(None) in test_ad631:148 and test_cognitive_skill_596b; resets to None in test_issue1419:832-834, :2654-2656; register_department("new_test_agent_429e") and ("new_test_agent") at test_ad429e_dict_migration.py:170 and test_standing_orders.py:150, never undone; set_directive_store is called by no test; the autouse fixture _ad682_clear_module_caches clears _load_file and _build_personality_block before each test
HOLDS: yes for the globals the file reads, as far as read; the fixture of the new file sets every one of them
```

**Read, not run:** `step_instruction_router.py` in full (`:48-122`, `:125-190`); `knowledge.py:188-232`; `crew_utils.py:69-120`; `config_models/emergence.py:401-410`; `builder_paths.py:58-72`, `:158-208`, `:210-250`, `:473-523`; `swe_harness/tools.py:1065-1069`; `native_builder.py:227-250`; `copilot_adapter.py:81-125`, `:129`, `:482-495`; `decomposer.py:30-75` (`is_capability_gap`); `agent_work_tags.py:379-382`; `routers/crew.py:336-349` (the route of section 15); `startup/finalize.py:4171`, `:5477-5482`; `build_dispatcher.py:92-96`, `:396-407`; `worktree_manager.py:153-175`; `sub_tasks/reflect.py:270-315`; `cognitive_agent.py:4040-4200`, `:4340-4470`; the tests named in section 3. **Not measured:** a live vessel; a real model; pytest.

## 12. Prior Art and Blind Spots

- **Already in the orders, and agreeing: so the new text is not a second statement of the same thing.** `federation.md:81` ("Cannot implement? Research thoroughly."), `:140` ("Your job is to notice and communicate, not to fix everything yourself."), the Code of Conduct's Honesty and Accountability (`:151-153`, `:163-165`); `ship.md:273` (source attribution: an unsupported "I've observed" is confabulation), `:112` and `:199` (proposals so that "the Captain can track and act on it"); `yeoman.md:21-25` ("Never claim to have done something you did not do", pinned by `test_ad910...`): the new item 3 is the build-specific, crew-wide sibling of that clause and is not merged with it; the role files that already say the rule (`architect.md:44`, `research_specialist.md:24`, `diagnostician.md:13`, `red_team.md:13`). **Contradicting, fixed here:** `builder.md:6, :62, :63`, `engineering.md:54`. **Contradicting or ambiguous, left:** `engineering_officer.md:6, :9, :33` (L4); `ship.md`'s Import Conventions, Testing Standards and Code Patterns, written as orders to "all agents" ("Run tests with: pytest tests/ -x -q"): the new section sits directly above them and frames them as what applies to whoever builds, and no sentence says so (a one-line lead-in is possible, not required); `architect.md:22` uses "dispatching" for the Architect's prompt hand-off, near the Captain's dispatch of a build.
- **Counterparts elsewhere.** The rule reaches every call without one: all three branches of `_decide_via_llm` compose `ship.md` before they append their own text, the proactive branch's `[PROPOSAL]` teaching ends "so the Captain can track and act on the finding" (`cognitive_agent.py:4158-4172`), the ANALYZE and COMPOSE steps get it through `get_step_instructions` (universal tag, T2), and no chain step's own prompt says anything about building or implementing (`rg` over `sub_tasks/*.py`). **The EVALUATE and REFLECT steps carry no orders at all**: `evaluate.py` never calls the loader and `reflect.py:277-310` asks "Does it follow standing orders?" with the personality block and a short checklist, not the orders; the rule therefore reaches a draft only through the model call that writes it, and nothing re-checks it afterwards (as for every other order; not changed here; a follow-up if the live check finds a draft that slips through). A counterpart in the proposal billets would be a second place to keep true (DRY). BF-934's billet and proposal-block modules are not on this tree and were not read: if its billet text promises implementation, that is for its review. No Forge skill text exists (the four tracked skills mention no build). The Captain-dispatched native build adds "You are the SWE crew agent executing a build" (`native_builder.py:247`) and the visiting builder "You write code for ProbOS build tasks" (`copilot_adapter.py:129`): both are dispatched builds, consistent with the section, which is why it says "on their own initiative". The approve route and its UI are BF-937. **Agent work (AD-1347):** crew can ask a department to run a tool or take a work item (`agent_work_tags.py:379-382`, taught in COMPOSE at `sub_tasks/compose.py:682-687`); I did not enumerate which tools such a request can name, and the section does not forbid it (it is about code to the ProbOS repository); if a tool could write there, its own write boundary is what stops it (L1).
- **Blind spots handled.** The router dropping a correct section (T2 and its control); the loader reading a different directory (the autouse fixture); a personal file contradicting the ship tier (T3, T4); the Captain-dispatched builder reading a rule that forbids it (the wording); a cached loader (section 15); the golden (P2-5); crew workspace work refused by over-reading the rule (the clause).
- **What discards a correct result.** A correct section lost: a router tag outside the universal list (T2), a type whose orders directory is not the repository's (the fixture), a stale cache on the running vessel (restart). A correct claim refused: a Captain-dispatched build whose agent reads the section; the sentences name the dispatch for that reason.
- **Needs the Captain (decisions, with my recommendation).** (1) **The live check** (section 15): an operation on the running vessel; no decision, an action. (2) **The workspace clause** (my addition to the issue's text): recommended. If the Captain prefers the four elements only, delete the second sentence of the first bullet of P2-1 (`Code you write in your own workspace for a task you were given is not that.`); no test depends on it, and only mutation row 1's text and the D2 row 1 then change. (3) **"Forge" in a prompt every crew member reads:** the Captain's own wording; the exact decision required only if the Software Engineer has been renamed on the live vessel: keep "Forge" or change the sentence to the new callsign. (4) **If the live check fails for the Chief Engineer:** apply L4's bullet (a one-line change; recommended on that evidence only). (5) **When AD-1336 child 6 ships:** its change must update the three "not merged until the GitHub delivery route exists" sentences and the golden; recommended: add that line to that child's acceptance. No boundary is crossed: `config/standing_orders/` is a Captain document (BF-943) and changes through a build the Captain reviews, which is the pull request this contract becomes.

## 13. Diff Reviewer: properties to verify

1. M2 changes exactly three config files, the two fixtures and the test file's marker: `git diff --name-only` for M2 lists `config/standing_orders/{ship,builder,engineering}.md`, `tests/fixtures/ad1152_agentic_off_golden.json`, `tests/fixtures/ad1200_no_instructions_golden.json` and `tests/test_bf936_crew_code_change_orders.py`, and nothing under `src/`.
2. `ship.md`: the section is the first after the intro line, preceded by `<!-- category: core_directives -->`, has no `---` line and no brace, and each of the issue's four elements is present with the Captain's Forge sentence (not item 2's old wording); `Import Conventions` follows it unchanged with its own marker.
3. `federation.md` is not in the diff (AD-1344); `builder.md:9, :12, :13` (the AD-1359 phrases) are byte-identical; the AD-729a cross-reference and the other pinned phrases of `ship.md` are unchanged.
4. `builder.md`: the new paragraph is directly before `## Your Standards`; the two changed bullets are the fourth and fifth of "Your Personality"; no other line changed. `engineering.md`: one bullet, directly under `## Build Pipeline Standards`.
5. The golden diff is two lines (15 and 760); `default_config_sha256` (line 17) and `base_commit` are unchanged; the prompt string equals `compose_instructions("builder", "", department="engineering")` over the head files plus the old 613-character suffix. The AD-1200 fixture diff (A1) is ten lines, each a `requests` value of a `native/*` case, each `bytes` grown by exactly 1,987 (the 1,965 added characters, JSON-escaped), and no other key moves.
6. T1 to T6 call the real loader and the real router over `config/standing_orders`; no case mocks a read; the controls pass on the base; the class marker is removed by N2-1 and by nothing else; no case asserts the whole prose of any file.
7. The text of the three files names no issue number, is ASCII, and does not tell the Captain-dispatched builder that it cannot build (read it as `native_builder.py:233` composes it).

## 14. Acceptance criteria

- G1, G2 and G3 pass as stated, and the batch's broad gate is green with a receipt.
- **The orders say it:** `ship.md` carries the section (T1, T2), and `builder.md` and `engineering.md` are consistent with it, with Forge on Captain-dispatched builds only and a candidate not merged until the GitHub delivery route exists (T3); no file claims a build with no dispatch (T4).
- **The pins hold:** the AD-1152 golden and the AD-1200 request fingerprints are refreshed by measurement (P2-5, P2-6), the standing-orders layout and composition tests pass, and a test pins that the crew-wide section is composed into a crew member's standing orders through the loader the crew use (T1).
- **Live check after merge: not part of the build.** It is section 15, for the Captain, and the closure comment hands it over.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 15. Not in this issue: for the Captain

The issue's last live acceptance item: a crew member asked whether they can implement an approved proposal answers consistently with the rule. It is an operation on the running vessel; the build does not do it and neither did I. Do not mark it done on the strength of the tests.

- **Action.** After the merge, restart the vessel (the orders are read once per process and cached, `standing_orders.py:151`; a directive mutation also clears the cache, but a restart is the plain step). Then, for three crew members (the Software Engineer, the Chief Engineer and one outside Engineering, for example the Counselor): (1) read `GET /api/crew/{agent_id}/standing-orders` (`routers/crew.py:336`). (2) Ask each, in a DM, the same question: "An approved proposal is waiting. Can you implement it?" (3) Recommended addition, for the clause I added (not in the issue): ask one crew member, with agentic DMs on, to write a small script in their own workspace for a task you name.
- **Source of truth.** (1) The `ship` tier's `text` returned by the route, which is what the running process loaded: it holds the heading `## What Crew Can Do About Code Changes`, and the `agent` tier of the Software Engineer holds "You build only when the Captain dispatches a build". (2) The reply text in each DM thread. (3) The script in the workspace.
- **Pass condition.** (1) Every route answer shows the section. (2) No reply says or implies that the crew member will implement, build, commit or merge the change on their own; each says the engineering pipeline makes the change under your direction (the Software Engineer: only when you dispatch a build, as a candidate that is not merged yet), offers a specification, review or verification instead, and claims no past build work unless the record shows it. (3) The script is written: the clause keeps workspace work outside the rule. **Fail:** any reply promises or reports an implementation, a commit or a merge, or a route answer lacks the section. On a fail, record the crew member, the question and the reply, and file a bug; do not edit the text on the spot (for the Chief Engineer, L4's bullet is the first remedy).
- **Which acceptance items it is.** The issue's third acceptance bullet ("Live check after merge"); the first, second and fourth are the build's (T1 to T6, the two fixtures, the Engineering Principles line).

## 16. Amendment A1 (2026-11-12): the AD-1200 request fingerprints

**Drafted by:** the orchestrator, not the Architect: the choice is fixed by a precedent in the repository (AD-1359, `182d79ff`) and every number below was measured, so the change is mechanical. The Diff Reviewer's first brief names this section as the first thing to verify.

**Finding.** The orchestrator's oracle ran G2 on M2's head (a scratch tree at `340d97fe` with this contract's blocks applied): 31 files, 1 failed, 1,734 passed, 7 skipped. The failure is `tests/test_ad1200_repository_instruction_wire.py::test_no_instructions_actual_requests_match_pinned_base`. The first reading missed it for two reasons: D3 named the AD-1152 golden as the one fixture that pins the composed text, and the Absence Verified walk looked in the fixtures for the files' text, which a fixture of byte counts and digests does not hold; L13 had listed the 29 existing files of G2 as unmeasured.

**Measured on the scratch tree** (nothing in this section was measured on the real tree):
- The ten `native/*` request values of the AD-1200 fixture (repository: two requests, missing, unscoped, installed; in the legacy and the structured mode) each grow by 1,987 bytes; the work-item, result and trace values do not move. M2 adds 1,965 characters to the three files (ship 1,139, builder 474, engineering 352), which are 1,987 bytes as JSON (1,158, 476, 353): the whole growth is the orders' text.
- P2-6, run after P2-1 to P2-5: the one line `replaced fingerprints: 10`; `git diff --numstat` `10`, `10` for the file, in eight hunks (lines 9-10, 16, 22, 28, 48-49, 55, 61, 67, the same lines AD-1359 changed); blob `214261292aa2c4574eceeb3e79bae53144c4e357`; `test_ad1200_repository_instruction_wire.py` then passes (56 passed).
- The 50 test files outside G2 that name the orders machinery (`standing_orders`, `compose_instructions`, `_compose_system_prompt` or one of the three file names in the file) all passed on M2's head: 2,194 passed, 5 skipped, 0 failed.

**What A1 changes.** The base blobs and the tier line in the header; Problem 1 (the issue's evidence is no longer quoted: a vessel's thread id and a crew member's words do not belong in a public file); Problem 5 and the Solution paragraph; the decisions' lead-in; D3 (one row added, its closing sentence extended); D5's option 1; the milestone table, the size line, the G2 bullet and M2's commit subject; P2-6 (new, between P2-5 and N2-1); the REPLACE text of P3-1 and P3-2 (the fixtures named); L11, L13 and L14 (new); the fourth Absence Verified claim; properties 1 and 5; the "pins hold" acceptance line; this section. N1-1, P2-1 to P2-4, N2-1, the mutation rows, G1 and G3 are untouched, and nothing under `src/` changes.
