# BF-937 (#1678): The build-approve route and both HXI call sites say that a build is not merged and where its candidate branch is kept, and self-improvement persistence refuses a root inside the source checkout (default: the data directory)

**Drafted by:** `Architect` (GitHub Copilot fallback; the Claude Code bridge is logged out), 2026-11-12
**Revised by:** the orchestrator (amendment A1, 2026-11-13, section 16), measured on the oracle over BF-936's head `b89ae473` (BF-934 and BF-936 merged or about to merge): three misses found by applying the blocks and running the gates, none by reading; the Architect's text is otherwise unchanged.
**Status:** ready to build on `origin/main` after BF-936's merge (A1; the Architect read `430423e1`, reading tree `D:\ProbOS-worktrees\bf936-base`), in two slices. **Oracle:** (A1: superseded by section 16, where the orchestrator ran every pytest, vitest, build and regeneration gate this paragraph lists as unchecked, on a scratch chain over BF-936's head `b89ae473`; the Architect's own consult, described next, ran none.) No pytest, no UI test and no UI build was run (a read-only consult). **What I ran instead** (section 11): every block of section 7 applied in label order to the LF blobs in memory (35 blocks, each SEARCH once, line-anchored; every `.py` result parses; the TypeScript compiler API over the whole `ui/src` program (641 tracked files as roots, `node_modules` from the main checkout) reports 0 diagnostics on the base, with the M1 files only, and with every S1 block); the patched route, persistence, wiring and model substituted for the real modules, and the 7 + 14 test bodies and the six `TestDispatchAPI` cases of the updated `tests/test_dispatch_wiring.py` driven by hand without pytest: on the base every class case fails at its own `assert`, on the head all pass; the 17 Python mutants of section 9, each killed by exactly the cases listed; the transpiled helper and the store line run in Node. **What that leaves unchecked (all "expected" below):** every pytest count, every vitest case and the rendering of the two components, `npm run build`, the regeneration of the two generated artifacts, the ledger, the broad gate; the symlink case T10 itself (this account cannot create a symlink, so it skipped; its mechanism was checked by hand with a directory junction into `src`, accepted on the base and refused on the head), so that case has not run anywhere yet.
**Base blobs (`430423e1`):** S1: `src/probos/routers/build.py` `3a54c913f05623fcb6d97c3176b70dbcc99c87f0`, `tests/test_dispatch_wiring.py` `3afb2227bcbbd1445b48124a708cdb81fb886057`, `ui/src/components/IntentSurface.tsx` `033419994624933f2df4f1c6fd3b9f96affba86d`, `ui/src/components/bridge/FullKanban.tsx` `7214f58adc19a69c7bc3377caa701359529a8cfc`, `ui/src/store/useStore.ts` `b27306227c7ea3b432081e55d3dc4709430c0732`, `docs/development/deterministic-ship.md` `dc4fd0091aa6c96afb88b553e109fe3d3efe80ac`. S2: `src/probos/cognitive/self_improvement/versioning.py` `91cd36e229c4801cc4a3d1449241d03861e4524b`, `src/probos/config_models/knowledge.py` `cb630672a2558a80c04556e92b2629ac01c0cb27`, `src/probos/startup/finalize.py` `4baa2dc3a7694b8feafff7c9948b2bd46f5424a2`, `config/system.yaml` `88adeb0d4253eebd6b8fb2e6402b962f6096a762`, `tests/test_ad1270e2f_knowledge_models.py` `f13b4c52a2ed706d08e2753c6ae94581ad3fe322`, `docs/development/config-reference.md` `99a47da740aebc1b78eb89f4a81db36dcd36dc18`, `docs/development/config-facade-baseline.yaml` `3876ca2f304de1fd10603fd418cf0fa3b2c6aeb3`. Both: `PROGRESS.md` `eaf7e884c3a158b6d9c89754c3e99ab597c05ff4`, `DECISIONS.md` `1d814df5020e7b9675f2ae123e14bf5e19075b7f` (A1: every other blob above was measured equal at BF-936's head `b89ae473`; these two differ there by BF-934's and BF-936's entries. `tests/fixtures/ad1152_agentic_off_golden.json`, which P2-10 changes, is blob `5ba9ea5c6ba88b7fa4a937ec40289e94033b10ea` there, BF-936 having refreshed it first). Unchanged and pinned by BF-897: `src/probos/build_dispatcher.py` `7cb1b4862a88ddec0dc56f075c3a02fc29b84a8c`, `src/probos/worktree_manager.py` `f4d01b8eb8cd5bcc738e6aedcefeaf3519d673df`.
**Dependencies:** BF-934 (#1673) and BF-936 (#1677) merge first, each with its own gate (A1: section "Batching" and section 16; BF-936 does not share this item's gate). **Tier:** S1 M1 STANDARD (tests), M2 HIGH (a route and the HXI), M3 STANDARD; S2 M1 STANDARD, M2 HIGH (a write boundary, a config default, two generated artifacts), M3 STANDARD. **Estimated tests (expected, not measured):** S1 one Python file (7 cases: 4 pass, 3 xfail at M1), one UI file (11 cases: 4 controls, 7 expected failures), one shared fixture; S2 one Python file (14 cases: 1 passes, 13 xfail at M1). **BF number:** BF-937, held by #1678 (open, label `bug`); nothing new is allocated (section 11).

**Which text describes the head.** Before building (A1: after the merges of BF-934 and BF-936): `git rev-parse HEAD:<path>` for the paths above prints the blobs above, except `PROGRESS.md` and `DECISIONS.md` (they carry those two items' entries), `git diff --stat 430423e1 HEAD -- src/probos/routers src/probos/cognitive/self_improvement src/probos/config_models src/probos/startup ui/src config PROGRESS.md DECISIONS.md` shows only `PROGRESS.md`, `DECISIONS.md` and BF-936's `config/standing_orders/builder.md`, `engineering.md` and `ship.md` (at `b89ae473`: five files, 80 insertions, 2 deletions; none of the other paths), and none of the five new files exists (`tests/test_bf937_queue_approve.py`, `ui/e2e/fixtures/bf937-queue-approve-unavailable.json`, `ui/src/__tests__/BuildQueueApprove.bf937.test.tsx`, `ui/src/store/buildQueueApprove.ts`, `tests/test_bf937_promoted_agents_root.py`). If one fails, every SEARCH must still occur exactly once, else it is a hard stop for the Architect. Working copies are CRLF and SEARCH text is LF; this answer file is CRLF too (the writing tool's convention), so normalize line endings before applying a block. Where prose and a block differ, the block wins. Apply the pairs with the `edit` tool one at a time, whole block, in label order, slice by slice (labels restart in each slice). **Every SEARCH starts at the start of a line and is ASCII, except S1 P2-3**: the old docstring line of the route holds one U+2014 (em dash) and that line must go, so its SEARCH holds that one character (read the answer file as UTF-8; the TypeScript SEARCHes avoid every non-ASCII line).

## 1. Problem

The issue (#1678, copied at `...\files\bf937\issue-1678-copy.md`) names two leftovers of the pre-GitHub era. Its line numbers are from `21798ea8`; every one is re-derived on `430423e1`. Its live-log claim ("`build-dispatcher` starts on every boot, 2026-10-25 19:22:08") is quoted as the issue's and not verified here; the code shows no gate between the dispatcher's construction and its start (`startup/structural_services.py:118-133`).

| Issue | Re-derived on `430423e1` |
|---|---|
| `routers/build.py:195-205` | the route `:193-205`; decorator `:193`, docstring `:198`, the call `:201`, the success shape `:202-204`, the error shape `:205` |
| `build_dispatcher.py:389-400` | `approve_and_merge` `:396-421` (the call `:407`, the refusal branch `:415-419`) |
| `worktree_manager.py:153-176` | `merge_to_main` `:153-175`: no git, `(False, reason)` |
| `IntentSurface.tsx:2063`, `FullKanban.tsx:74` | the same lines; the whole `try { await fetch(...) } catch { /* ignore */ }` is `:2062-2068` and `:73-79` |
| `versioning.py:111-135`, `knowledge.py:448`, `knowledge.py:440`, `system.yaml:1998-1999` | the class `:111-165` (default `:123`, `Path(root_dir)` `:126`, writes `:141-158`); the field `:473` and the class docstring `:463-465`; `enabled: bool = False` `:468` (the model has no `persistence_enabled`: the issue's "persistence default False" is `enabled`); `system.yaml:1994` (`enabled: false`) and `:1999` (the root) |

**S1: the approve route and its two call sites.**

1. **The route.** `POST /api/build/queue/approve` (`routers/build.py:193-205`) says "Captain approves a queued build -- merge worktree to main" (`:198`, one em dash), asks `runtime.build_dispatcher.approve_and_merge` (`:201`, its only production caller: section 11), and answers `{"status": "ok", "commit": ..., "message": "Build merged: ..."}` or `{"status": "error", "message": <text>}`. Since BF-897 `merge_to_main` runs no git and returns `(False, reason)` (`worktree_manager.py:153-175`), so a build in review always answers the second shape.
2. **What the Captain sees.** Both call sites discard the answer: `await fetch(...)` with no read and `catch { /* ignore */ }` (`IntentSurface.tsx:2062-2068`, `FullKanban.tsx:73-79`). The announcement of a build in review is `Build ready for review: <title> (AD-n)` (`useStore.ts:3870-3872`): no branch, no place, no "not merged". BF-897's contract records the same reads (its Verified section, and its line 57: no HXI message for the queue-approve refusal, because `build_failure` would fire the Night Orders escalation).
3. **The sibling.** `POST /approve` (`routers/build.py:67-95`) refuses with `APPROVE_REFUSED`, a WARNING and a `build_failure` event carrying `not_executed: True`, which `watch_rotation.py:243` reads so that no escalation fires. It is the precedent for a typed refusal, and what the HXI renders for it is the event's `message` (`useStore.ts:3809-3820`, the branch without a report).
4. **The test that pins the defect.** `tests/test_dispatch_wiring.py:22` stubs `approve_and_merge` as `(True, "abc1234def")` and `:114-122` asserts `status == "ok"` and a merge commit: the route's success path, which the real chain cannot reach after BF-897.

**S2: the persistence.**

5. **The write.** `LocalDiskPersistence` (`versioning.py:111-165`) writes `{agent_type}_v{N}.py` and a `.meta.yaml` sidecar under `Path(root_dir)` (`:126`, `:141-158`), a path relative to the current directory, in a `try/except Exception` that logs and answers `""` (`:159-165`). Its default is `src/probos/agents/designed` (`:123`; the config default `knowledge.py:473`; the shipped yaml `system.yaml:1999`). `src/probos/agents/designed` is not tracked, does not exist and is not gitignored (section 11), so a write there is an untracked source file in the checkout, outside GitHub, the gate and review.
6. **Reach, measured.** The object is built (`finalize.py:2741`) and attached (`:2750`) only when `self_improvement.enabled` (`finalize.py:2626-2630`; default False `knowledge.py:468`, `system.yaml:1994`); the call site wraps the wiring (`:6039-6045`). **Nothing in `src/` calls `.promote(` or builds an `AgentVersion`, nothing reads `runtime.agent_persistence`, and nothing imports or discovers `src/probos/agents/designed`** (section 11, AB-3 and AB-4; AD-1346's census says the same, `tests/test_ad1346_admission_file_write_census.py` WF7). So turning the pipeline on today wires the object and never drives it; the issue's "would write untracked files" holds for the caller AD-482h-1 will add. This item puts the boundary in place before that caller exists.

## 2. Solution

**S1.** The route stops claiming a merge. For a build in review it answers HTTP 200 with a typed body, `status: "unavailable"`, `code: "local_merge_unavailable"`, `merged: false`, and `branch`, `worktree_path`, `commit` and a `message` that says: not merged, local merge is unavailable (BF-897), delivery goes through GitHub (AD-1336) and until that route exists the candidate branch stays unmerged, where the candidate is, and the two ways on (open a pull request from it yourself, or reject the build). It calls no dispatcher method and runs no git command; `approve_and_merge` and `merge_to_main` are untouched (BF-897's tests pin them). A dispatcher that is not running and a build that is not in review are answered as before. A new helper `ui/src/store/buildQueueApprove.ts` posts the click and returns the line to show; `IntentSurface` adds it to the chat and `FullKanban` shows it as a note under the card; the `Build ready for review` line says the candidate is not merged and where its worktree is.

**S2.** `LocalDiskPersistence` refuses a root inside the checkout ProbOS runs from, by BF-897's own predicate (`operator_checkout_refusal`), at construction (`ValueError`) and again at every write (an ERROR and `""`, nothing written); its root is resolved to an absolute path when it is built; it carries no default location. `persistence_root_dir` defaults to `""`, which `resolve_promoted_agents_dir` reads as `{data_dir}/promoted-agents` (the `resolve_records_repo_path` idiom). `_wire_self_improvement` builds the persistence first and, on a refusal, logs an ERROR and returns False before any store opens. The shipped yaml, the model docstring and the two generated artifacts follow; AD-1346's file-write census row stays true, because `promote` keeps its two writes.

## 3. Decisions

Ranked by correctness, safety, compatibility, architectural fit, reversibility and validation cost; the top row is taken. In every row: in-envelope means evidence, backward compatibility, no weakened security, governance, privacy or audit control, no OSS/commercial boundary crossed, bounded rollback.

**D1. What the route answers** (compared with BF-897's `/approve` refusal and with the `{"status":"error","message"}` shape the HXI ignores).

| # | Option | Judgement |
|---|---|---|
| 1 | HTTP 200; `status: "unavailable"`, `code`, `merged: false`, `build_id`, `branch`, `worktree_path`, `commit`, `message`; the route calls nothing (chosen) | Typed by a new `status` value, as `started` is; all 21 returns of `routers/build.py` are HTTP 200 with a `status` and `/approve`'s refusal is too, so no client meets a new transport rule; the HXI reads `message`; one-route revert |
| 2 | HTTP 409, same body | The better status for a generic client, but the router's first non-200, the browser logs a failed request for an expected answer, and no consumer reads the status line |
| 3 | HTTP 501 | Reads as a server fault to retrying proxies; the build exists, so it is a state refusal, not a missing feature |
| 4 | Keep `{"status":"error","message"}`, better text | Not typed: the issue asks for "not a generic error" |
| 5 | Keep calling `approve_and_merge` and type its refusal | It answers `(False, text)`; typing parses BF-897's text or changes its pinned contract, and each click writes two WARNINGs for a call that cannot succeed |

**D2. What the two call sites show and how.**

| # | Option | Judgement |
|---|---|---|
| 1 | Both read the body through one helper and show the `message`: a chat line in `IntentSurface` (it is the chat) and a note under the card in `FullKanban` (Mission Control, where the chat may be closed) (chosen) | The UI follows the vessel: when delivery lands the answer changes and no UI edit is needed; no static claim in the UI; one shared fixture is the seam |
| 2 | Emit a `build_failure` event with `not_executed` (BF-897's `/approve` shape) | No UI edit, but the event names a failure for a build that is fine, its handler clears the progress of any build in flight (`useStore.ts:3810`), and BF-897's contract (line 57) refused it for this route |
| 3 | Hide or disable the control with a fixed explanation | Honest now, but a static claim in the UI that child 6 reverses; no branch or path; the Captain loses the one place the answer appears |
| 4 | Both 1 and 3 | Two sources of one claim; the fixed text goes stale first |

**D3. What a dispatched build's result tells the Captain.**

| # | Option | Judgement |
|---|---|---|
| 1 | The `reviewing` announcement says the candidate is not merged and where its worktree is (the payload has `worktree_path`); the approve answer names the branch and commit (chosen) | The two places the Captain meets the result; no payload change; the branch is only in the queue item's `result`, which the route reads |
| 2 | Add `branch` to the three queue payload builders (`routers/build.py` snapshot and GET, `runtime._on_build_complete`) | Names the branch at announcement, but one dict is copied three times: a refactor beyond the issue |
| 3 | The approve answer only | The Captain learns it after a click that looks like it merges |

**D4. What happens to `approve_and_merge` and `merge_to_main`.**

| # | Option | Judgement |
|---|---|---|
| 1 | Unchanged; the route no longer calls them; whatever AD-1336 child 6 builds either re-wires `/queue/approve` to them or replaces the queue (section 12) (chosen) | BF-897's tests pin them (`test_build_dispatcher.py`, `test_bf896...:741`, `test_bf897...:412-462`); the issue's item 4 says unchanged; one fewer pair of WARNINGs per click |
| 2 | Keep the call | D1 row 5 |
| 3 | Delete them and their tests | Breaks item 4 and the seam; not reversible in effect |
| 4 | Rename or deprecate | Churn on a pinned name |

**D5. UI tests** (runner: vitest 4 with jsdom and Testing Library, `ui/package.json` scripts `test` = `vitest run`, `build` = `tsc -b && vite build`; CI job `ui-tests` runs `npm ci`, `npm run test`, `npm run build`; no existing file covers either component: AB-5).

| # | Option | Judgement |
|---|---|---|
| 1 | One new file: both components, the store line and the helper, reading the backend's fixture; `built` is `it.fails` until M2 sets it to `it` (chosen) | Covers the three edited files; the shared JSON crosses the seam (the pattern of `ui/e2e/fixtures/*.json`); matches the M1 and M2 shape |
| 2 | Playwright | Needs a backend and a browser; not in the unit gate |
| 3 | A helper unit test only | Passes with the click sites unchanged: the defect |
| 4 | A `?raw` source scan | Cannot tell a required line from the shipped one |

**D6. Where the S2 guard lives** (what each catches and misses).

| # | Option | Catches | Misses |
|---|---|---|---|
| 1 | The constructor (raises) and `promote` (re-checks) over one function (chosen) | Every construction, the wiring and a direct one; a root that became a link into the checkout after construction | A race between the check and the write (recorded, S2 L5) |
| 2 | A `field_validator` on `persistence_root_dir` | A config file at load, before wiring | The data directory and the checkout are unknown at parse time, a relative root depends on the current directory at write time, direct construction; and it fails every config that carries the old default, `enabled` or not |
| 3 | `promote` only | The write | The wiring builds an object that can never work, silently, until the caller arrives |
| 4 | The wiring only | The shipped path | Direct construction, a future caller built another way |

**D7. How "inside the repository's tracked source tree" is recognised.**

| # | Option | Judgement |
|---|---|---|
| 1 | BF-897's `operator_checkout_refusal(root, _CHECKOUT_ROOT)`: resolve (symlinks and junctions followed, a relative path against the current directory), take the nearest `.git` entry at or above, compare with the checkout's by `samefile` (case, 8.3 names), refuse on an unexaminable path; no git run; `_CHECKOUT_ROOT = Path(__file__).resolve().parents[4]` as `builder.py:50` does for its layout; an installed package has no `.git` there and nothing is protected (chosen) | One predicate, already proved over real directories (`test_bf897` T-A1); the checkout is what BF-897 and BF-904a protect; no subprocess |
| 2 | Containment in the package directory | Needs no `.git`, but misses `tests/`, `config/` and the rest of the checkout, and in an installed package forbids a directory that holds nothing tracked |
| 3 | `git check-ignore` or `ls-files` | Exact "tracked", but a subprocess in a constructor, a git dependency and the hook problem BF-904a hardened against |
| 4 | Parse `.gitignore` | A second implementation of git's rules |

It refuses more than "tracked": any directory inside the checkout, a gitignored `data/` included (S2 L2). That is the fail-closed side, and loosening it later needs git or a parser.

**D8. The new default location** (the config's existing data-directory helpers, enumerated in section 11: `resolve_records_repo_path`, `resolve_archive_db_path`, `ProbOSRuntime.data_dir`, `_platform_data_dir`; the inline `data_dir / "knowledge"` at `cognitive_services.py:545-548`).

| # | Option | Judgement |
|---|---|---|
| 1 | `persistence_root_dir` empty means `{data_dir}/promoted-agents`, resolved by one function next to the persistence, the shape of `resolve_records_repo_path` (chosen) | Outside the checkout by default (BF-265's platform data directory), zero config, operator-overridable; the function is not added to `probos.config`, whose public surface the facade baseline counts (`test_ad1270e1_config_facade.py:1515-1577` pins `public_names` and `owned`) |
| 2 | Repo-relative `data/promoted-agents` | Gitignored, but inside the checkout, so D7 row 1 refuses it; relative to the current directory |
| 3 | Turn the write into an issue or draft-PR request | The issue's alternative; needs AD-1336 child 6's delivery and a GitHub client |
| 4 | Keep `src/probos/agents/designed` behind the guard | Refused by the guard itself |

**D9. An operator whose config already names a `src/` root.**

| # | Option | Judgement |
|---|---|---|
| 1 | Refuse with a clear message: the object cannot be built, and with `enabled: true` the wiring logs an ERROR and returns False before any store opens; boot continues (chosen) | Fail closed, loud, no silent redirect; `enabled: false` configs (the shipped yaml carried the old default) are untouched; the population is empty in practice, since nothing calls `promote` |
| 2 | Migrate the legacy literal to the data directory | A silent change of where source goes, and a rewrite hidden in a validator |
| 3 | Fail boot | A refused optional feature should not stop the vessel; the call site already degrades (`finalize.py:6039-6045`) |
| 4 | A validator that rejects it | Fails configs of a feature that is off |

**D10. Slices and order.**

| # | Option | Judgement |
|---|---|---|
| 1 | Two slices, S1 then S2 (chosen) | S1 is the active, visible defect, has no generated file and ends in UI tests; S2 regenerates two generated artifacts, so doing it last keeps its conflict window short; each slice reverts alone |
| 2 | S2 then S1 | The latent defect first: smaller, but the false control waits |
| 3 | One slice | About 25 pairs and over 100 KB; one failure blocks both |

## 4. Milestones and gates

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`. **M0 (each slice):** on the head, record the collected count (`--collect-only -q`) of every existing file named in that slice's G2 (Python), and the file count of `npx vitest list` for the UI files named in S1's G2.

| Slice | M | Blocks | Gate |
|---|---|---|---|
| S1 | M1 | N1-1, N1-2, N1-3 | G1 |
| S1 | M2 | P2-1 to P2-11, then N2-1 to N2-4 (the two test updates, then the two markers) | G2 |
| S1 | M3 | P3-1 to P3-3, ledger | G3 |
| S2 | M1 | N1-1 | G1 |
| S2 | M2 | P2-1 to P2-9, then N2-1 (the pin) and N2-2 (the marker), generated artifacts, then P2-10 (a script; A1) | G2 |
| S2 | M3 | P3-1, P3-2, ledger | G3 |

**S1.**

- **G1 (Python).** `PY -m pytest tests/test_bf937_queue_approve.py -q -n 0 -p no:randomly`. **Expected: 4 passed, 3 xfailed.** The marker carries `raises=AssertionError, strict=True`: any other exception or an XPASS is a FAIL; any other count is a hard stop. Then once with `--runxfail`: each of the three failures must stop at the `assert` section 6 names, never at a premise line.
- **G1 (UI).** From `ui/`: `npx vitest run src/__tests__/BuildQueueApprove.bf937.test.tsx`. **Expected: `4 passed | 7 expected fail (11)`** (vitest's summary: the 7 are `it.fails` cases that failed as expected; 4 are controls). Then `$env:BF937_RUNXFAIL='1'; npx vitest run src/__tests__/BuildQueueApprove.bf937.test.tsx; Remove-Item Env:BF937_RUNXFAIL`: **expected 4 passed, 7 failed**, each failure at its own `expect` or at a `findBy*` timeout, or (A1: the two helper cases, as section 6 says) at the dynamic `import('../store/buildQueueApprove')` inside the test body, never at the test file's own imports or at `render` (measured on the oracle: 2 helper cases at the dynamic import, 2 at `findByRole('status')`, 2 at `findByText`, 1 at the store case's `toContain`).
- **G2 (Python, suite order).** (1) `PY -m pytest tests/test_ad1270_night_orders_recall.py tests/test_ad1346_admission_build_test_sink.py tests/test_ad1346_admission_service.py tests/test_ad521_swe_pipeline_separation.py tests/test_architect_agent.py tests/test_bf896_dispatcher_confinement_seam.py tests/test_bf896_executor_identity_and_blocks.py tests/test_bf897_build_pipeline_scale_and_checkout.py tests/test_bf904a_failed_build_restore.py tests/test_bf904b_dispatch_and_visiting.py tests/test_bf904b_sealed_core_observation.py tests/test_bf937_queue_approve.py tests/test_build_dispatcher.py tests/test_build_queue.py tests/test_builder_api.py tests/test_dispatch_wiring.py -q -n 0 -p no:randomly` (the 11 files that name `/api/build` or the router module, the dispatcher and queue tests, and the new file; section 11). (2) `PY -P scripts/check_architecture_principles.py --check`. (3) **UI**, from `ui/`: `npx vitest run src/__tests__/BuildQueueApprove.bf937.test.tsx src/__tests__/IntentSurface src/__tests__/useStore src/__tests__/App src/__tests__/ViewSwitcher src/__tests__/ComponentRendering.test.tsx`, then `npm run build` (`tsc -b && vite build`; `npx tsc -b` alone type-checks the sources and the tests). **Expected:** the new Python file 7 passed; every other file 0 failed and collected counts equal M0; the check clean; the UI files all passed and the build clean. The full `npm run test` is the broad gate's and CI's.
- **G3.** `PY -P scripts/gen_ad_ledger.py`; then `PY -P scripts/gen_ad_ledger.py --check`; then `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`.

**S2.**

- **G1.** `PY -m pytest tests/test_bf937_promoted_agents_root.py -q -n 0 -p no:randomly`. **Expected: 1 passed, 13 xfailed** (where a symlink can be created; where it cannot, the symlink case skips: 1 passed, 12 xfailed, 1 skipped). Strict marker as above; then once with `--runxfail`: each failure at the `assert` section 6 names.
- **Generated artifacts (M2, after the source pairs).** `PY -P scripts/gen_config_reference.py`, then `PY -P scripts/check_config_facade.py --update-baseline` (where the shared venv imports another checkout's source, point it at the tree: `PYTHONPATH=<tree>/src`). **Measured diff (A1: the first text said two lines in the baseline, and the baseline changes four):** `docs/development/config-reference.md` changes the one `persistence_root_dir` row (default `''` and the new description: 1 insertion, 1 deletion); `docs/development/config-facade-baseline.yaml` changes four lines (4 insertions, 4 deletions): `canonical_dump_sha256` (under `surface_counts`), the `SelfImprovementConfig` block's `schema_sha256` and its `persistence_root_dir` default line, and the `SystemConfig` block's `schema_sha256` (the parent model's schema embeds the child's default). Any other changed line is a hard stop (another change moved a model). Both files go in the M2 commit.
- **AD-1152 default-config digest (M2, after the generated artifacts; A1).** P2-10, a script (section 7.2): the AD-1152 golden pins the SHA-256 of the default `SystemConfig()` dump, which the new default moves; it refreshes the golden's `default_config_sha256` (line 17) and `observation_sha256` (line 15) by running the test's own capture, as BF-926's A1 and AD-1270's slice 4c did. Without it `test_default_off_matches_pinned_base` and `test_default_off_golden_pins_only_descriptor_owner_platform[linux, win32]` fail.
- **G2 (suite order).** (1) `PY -m pytest tests/test_ad1152_agentic_correlation.py tests/test_ad1270e1_config_facade.py tests/test_ad1270e2f_knowledge_models.py tests/test_ad1346_admission_effect_census.py tests/test_ad1346_admission_egress_census.py tests/test_ad1346_admission_file_write_census.py tests/test_ad482_self_improvement.py tests/test_bf859_qa_pool_awaits_spawn.py tests/test_bf937_promoted_agents_root.py tests/test_config_reference_current.py tests/test_layer_boundaries.py -q -n 0 -p no:randomly` (the AD-1152 golden whose default-config digest P2-10 refreshes (A1), the config surface and its pins, the three AD-1346 scans because `versioning.py` is a census row, the two files that wire the pipeline, the generated reference's currency test, the layer test). (2) `PY -P scripts/check_architecture_principles.py --check`; `PY -P scripts/gen_config_reference.py --check`; `PY -P scripts/check_config_facade.py --check`; `PY -P scripts/check_config_profiles.py --check` (the last three are what the broad gate runs, `scripts/run_test_gate.py:1101-1109`). **Expected:** the new file 14 cases (14 passed, or 13 passed and 1 skipped where a symlink cannot be created), every other file 0 failed with collected counts equal M0, every check clean.
- **G3.** As S1's.

**Harness rule.** No source change made to pass a test, no skip, no loosened assertion. A failing case of a new file at G2 (any line), or any existing test failing, goes back to the Architect. The broad gate runs once, in the main session, with `PY scripts/run_test_gate.py --label bf937 --receipt logs/gates/bf937.receipt.json` (A1: BF-936 lands first, as its own pull request; the two BF-937 slices are one batch: section 16).

## 5. Commit messages

- **S1 M1:** `BF-937 S1 M1: tests for approving a build in review answering not merged, typed, with its candidate branch, xfail until built (#1678)`
- **S1 M2:** `BF-937 S1 M2: the build-approve route answers not merged and where the candidate branch is kept; both HXI call sites show the answer (#1678)`
- **S1 M3:** `BF-937 S1 M3: trackers, ledger and the one doc line (#1678)`; its body ends with the line `Refs #1678.`
- **S2 M1:** `BF-937 S2 M1: tests for self-improvement persistence refusing a root inside the source checkout, xfail until built (#1678)`
- **S2 M2:** `BF-937 S2 M2: persistence refuses a root inside the source checkout and defaults to the data directory; config reference, facade baseline and the AD-1152 default-config digest refreshed (#1678)`
- **S2 M3:** `BF-937 S2 M3: trackers and ledger (#1678)`; its body ends with the line `Closes #1678.`

## 6. Tests

### S1 (`tests/test_bf937_queue_approve.py`, `ui/src/__tests__/BuildQueueApprove.bf937.test.tsx`, `ui/e2e/fixtures/bf937-queue-approve-unavailable.json`)

| Id | Cases | Covers | xfail until |
|---|---|---|---|
| T1 | 2 | Function: a build not in review (queued; an unknown id) is answered `{"status":"error","message":"Build <id> not in reviewing status"}` as before (`test_a_build_not_in_review_is_answered_as_before`) | none |
| T2 | 1 | Function: with no running dispatcher the answer is `Build dispatcher not running`, even when the queue holds a build in review (`test_a_dispatcher_that_is_not_running_is_answered_as_before`) | none |
| T3 | 1 | Function: reject on the same app, queue and dispatcher still discards the build (a control that the world is live) (`test_reject_still_discards_the_build_in_review`) | none |
| T4 | 1 | Class: the answer for a build in review equals the shared fixture (`test_the_answer_is_the_typed_not_merged_result_the_hxi_test_reads`) | M2 |
| T5 | 1 | Class: `approve_and_merge` and `merge_to_main` not awaited, no manager call, no process started, no event, the build still in review (`test_nothing_is_merged_and_no_process_is_started`) | M2 |
| T6 | 1 | Class: the route's description no longer says "merge worktree to main" and says "not merged" (`test_the_route_no_longer_describes_a_merge`) | M2 |
| U1-U4 | 4 | UI controls: Mission Control posts `{build_id}` to the approve route; Mission Control rejects as before; the Build Queue panel posts `{build_id}`; a build that starts building is announced as before | none |
| U5-U7 | 3 | UI (`built`): Mission Control shows the answer under the card; Mission Control says so when the vessel gives no answer; the store announces a build in review as a candidate not merged, with its place | M2 |
| U8-U9 | 2 | UI (`built`): the Build Queue panel adds the answer to the chat, and the no-answer line | M2 |
| U10-U11 | 2 | UI (`built`): the helper returns the vessel's message or the fixed line, and never rejects | M2 |

(The ids U1 to U11 label the order of the `it` and `built` calls in the file; section 4 counts them: 4 controls, 7 expected failures.)

**How each xfail case fails on the base.** T4 at `assert resp.json() == json.loads(...)`: the route answers `{"status":"error","message":"refused"}` (the real dispatcher over the manager double's refusal); the two premise asserts before it pass. T5 at `world.approve.assert_not_awaited()`: the base route awaits it. T6 at `assert "merge worktree to main" not in description`. The UI cases: no `role="status"` note and no chat line exist on the base, so each `findBy*` times out; the store case fails at `toContain('Candidate branch kept in ...')`; the helper cases fail at the dynamic `import('../store/buildQueueApprove')` (the module is new), which `it.fails` takes as the expected failure.

**Existing tests that pin the old behaviour (enumerated by `git grep -n -E "approve_and_merge|merge_to_main|approve_queued_build|queue/approve" -- tests ui/src`).**

| File | What it pins | Verdict |
|---|---|---|
| `tests/test_dispatch_wiring.py:22`, `:114-122` | the fixture stubs `approve_and_merge` as `(True, "abc1234def")`; the case asserts `status == "ok"`, a merge commit and `assert_awaited_once_with` | **pins a defect**: a merge the real chain cannot make. Updated in S1 N2-1 and N2-2, with the reason inline; the stub becomes a tripwire |
| `tests/test_dispatch_wiring.py:133-145` (`test_approve_not_running`) | `{"status": "error"}` with no dispatcher | correct, unchanged |
| `tests/test_build_dispatcher.py:249-309` | `approve_and_merge` merges and cleans up when `merge_to_main` accepts; keeps the build in review when it refuses | the dispatcher's own contract, which child 6 uses: unchanged |
| `tests/test_bf896_dispatcher_confinement_seam.py:741` | the real chain refuses and the build stays in review | unchanged |
| `tests/test_bf897_build_pipeline_scale_and_checkout.py:412-462` | `merge_to_main` refuses, runs no git, keeps the branch | unchanged |
| `ui/src` | no test names `FullKanban`, the two queue routes or the `Build ready for review` line (AB-5); no `?raw` test reads `IntentSurface.tsx`, `FullKanban.tsx` or `useStore.ts` | nothing to update |

### S2 (`tests/test_bf937_promoted_agents_root.py`)

| Id | Cases | Covers | xfail until |
|---|---|---|---|
| T1 | 1 | Function: a root outside the checkout still writes the source and the sidecar (`test_a_root_outside_the_checkout_still_writes`) | none |
| T2 | 5 | Class: a root inside the checkout is refused at construction, for the old default relative (current directory = the checkout) and absolute, a deeper `src` directory, `config/`, and the checkout itself (`test_a_root_inside_the_checkout_is_refused`) | M2 |
| T3 | 1 | Class: a root that becomes inside the checkout after construction writes nothing and logs an ERROR (`test_a_root_that_becomes_inside_the_checkout_writes_nothing`) | M2 |
| T4 | 1 | Class: a relative root is pinned when the object is built (`test_a_relative_root_is_pinned_when_the_persistence_is_built`) | M2 |
| T5 | 1 | Class: the wiring refuses a `src` root with an ERROR, before any store opens or anything is attached (`test_the_wiring_refuses_a_root_inside_the_checkout_before_it_opens_anything`) | M2 |
| T6 | 1 | Class: the chain, config default to wiring to `promote`: the files land under `{data_dir}/promoted-agents`, nothing under the old relative default (`test_the_default_root_is_under_the_data_directory_and_the_pipeline_writes_there`) | M2 |
| T7 | 1 | Class: the model default and the shipped yaml are empty (`test_the_shipped_default_is_not_a_source_path`) | M2 |
| T8 | 1 | Class: the persistence names no default location (`test_the_class_carries_no_default_location`) | M2 |
| T9 | 1 | Class, Windows: the case of the path does not matter (`test_the_case_of_the_path_does_not_matter`) | M2 |
| T10 | 1 | Class: a symlink into the checkout is refused (skipped where a link cannot be made) (`test_a_link_into_the_checkout_is_refused`) | M2 |

**How each xfail case fails on the base.** T2 at `assert refusal is not None`: the base constructor accepts every root. T3 at its premise `assert hasattr(versioning, "_CHECKOUT_ROOT")`: the module names no checkout (the premise is the first assert). T4 at `assert (here / "promoted" / ...).is_file()`: the base keeps the relative root, so the write follows the later current directory. T5 at `assert wired is False`: the base wires and attaches. T6 at `assert (promoted / "foo_agent_v1.py").is_file()`: the base wrote under `cwd/src/probos/agents/designed` (the test moves the current directory under `tmp_path`, so the base cannot write into the repository). T7 at the default. T8 at `parameter.default is inspect.Parameter.empty`. T9 and T10 at `assert refusal is not None`.

**Existing tests that pin the old behaviour (enumerated by `git grep -n -E "persistence_root_dir|agents/designed|LocalDiskPersistence" -- tests`).** `tests/test_ad1270e2f_knowledge_models.py:257` pins the old default in `EXPECTED_DUMPS['SelfImprovementConfig']` and two parametrized cases read it (`:428-452`): a snapshot of a default the item changes on purpose, updated in S2 N2-1. `tests/test_ad482_self_improvement.py:447`, `:1491-1632` and `tests/test_bf859_qa_pool_awaits_spawn.py:78` pass `tmp_path` roots and `data_dir=tmp_path`, outside the checkout: unchanged and still valid. No test constructs `LocalDiskPersistence()` without `root_dir`.

## 7. The contract

### 7.1 Slice S1 (the approve route and its two call sites)

#### S1 M1

**N1-1.** New file `tests/test_bf937_queue_approve.py`:

```python
"""BF-937 (#1678): approving a build in review answers that it is not merged, and where its candidate branch is kept.

The real route runs in the real app (``create_app``) over a real ``BuildQueue`` and a real ``BuildDispatcher``. The
worktree manager is a double that records every call, ``approve_and_merge`` is spied on, and the ways to start a
subprocess fail the case that reaches them. The answer is compared with
``ui/e2e/fixtures/bf937-queue-approve-unavailable.json``, the file the HXI test reads too. The class holds the cases the
unfixed tree fails; the functions before it pass on both. No BF-937 name is imported.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from probos.build_dispatcher import BuildDispatcher
from probos.build_queue import BuildQueue
from probos.cognitive.builder import BuildResult, BuildSpec
from probos.runtime import ProbOSRuntime
from probos.worktree_manager import WorktreeManager

FIXTURE = Path(__file__).resolve().parents[1] / "ui" / "e2e" / "fixtures" / "bf937-queue-approve-unavailable.json"
BUILD_ID = "b7d41c09e2a1"
BRANCH = "builder-b7d41c09"  # WorktreeManager.create names the branch builder-<first 8 characters of the build id>
WORKTREE = "/work/ProbOS-builders/builder-b7d41c09"
COMMIT = "9f2c1ab"
APPROVE = "/api/build/queue/approve"


def _world(status: str = "reviewing", *, dispatcher: bool = True) -> SimpleNamespace:
    """One build in the queue (in review, or still queued), the real dispatcher over a recording manager, the real app."""
    from probos.api import create_app

    queue = BuildQueue()
    build = queue.enqueue(BuildSpec(title="Candidate build", description="a change"))
    build.id = BUILD_ID  # the queue minted another id; the fixture names this one
    if status == "reviewing":
        assert queue.update_status(BUILD_ID, "dispatched"), "premise: queued -> dispatched"
        assert queue.update_status(BUILD_ID, "building", worktree_path=WORKTREE), "premise: dispatched -> building"
        assert queue.update_status(
            BUILD_ID,
            "reviewing",
            result=BuildResult(success=True, spec=build.spec, branch_name=BRANCH, commit_hash=COMMIT),
        ), "premise: building -> reviewing"
    worktrees = MagicMock(spec=WorktreeManager)
    worktrees.merge_to_main = AsyncMock(return_value=(False, "refused"))
    worktrees.remove = AsyncMock(return_value=True)
    real = BuildDispatcher(queue=queue, worktree_mgr=worktrees)
    approve = AsyncMock(wraps=real.approve_and_merge)
    real.approve_and_merge = approve
    runtime = MagicMock(spec=ProbOSRuntime)
    runtime.build_queue = queue
    runtime.build_dispatcher = real if dispatcher else None
    runtime.emit_event = MagicMock()
    app = create_app(runtime)
    return SimpleNamespace(
        client=TestClient(app), app=app, runtime=runtime, build=build, worktrees=worktrees, approve=approve,
    )


@pytest.mark.parametrize(
    ("status", "asked"),
    [("queued", BUILD_ID), ("reviewing", "no-such-build")],
    ids=["queued", "unknown-id"],
)
def test_a_build_not_in_review_is_answered_as_before(status: str, asked: str) -> None:
    world = _world(status)

    resp = world.client.post(APPROVE, json={"build_id": asked})

    assert resp.status_code == 200
    assert resp.json() == {"status": "error", "message": f"Build {asked} not in reviewing status"}


def test_a_dispatcher_that_is_not_running_is_answered_as_before() -> None:
    world = _world("reviewing", dispatcher=False)
    assert world.build.status == "reviewing", "premise: the queue holds a build in review"

    resp = world.client.post(APPROVE, json={"build_id": BUILD_ID})

    assert resp.json() == {"status": "error", "message": "Build dispatcher not running"}


def test_reject_still_discards_the_build_in_review() -> None:
    """Control: the same app, queue and dispatcher still reject a build in review, so the cases below run in a live world."""
    world = _world()

    resp = world.client.post("/api/build/queue/reject", json={"build_id": BUILD_ID})

    assert resp.json() == {"status": "ok", "message": "Build rejected"}
    world.worktrees.remove.assert_awaited_once_with(BUILD_ID)
    assert world.build.status == "failed"


@pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-937 S1 M2: the route answers not merged, typed (#1678)")
class TestApprovingABuildInReviewAnswersNotMerged:
    def test_the_answer_is_the_typed_not_merged_result_the_hxi_test_reads(self) -> None:
        world = _world()

        resp = world.client.post(APPROVE, json={"build_id": BUILD_ID})

        assert resp.status_code == 200, "premise: the route answered"
        assert resp.headers["content-type"].startswith("application/json"), "premise: a JSON body"
        assert resp.json() == json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_nothing_is_merged_and_no_process_is_started(self, monkeypatch: pytest.MonkeyPatch) -> None:
        world = _world()

        def refuse(*args: object, **kwargs: object) -> None:
            raise AssertionError("approving a build in review must start no process")

        async def refuse_async(*args: object, **kwargs: object) -> None:
            raise AssertionError("approving a build in review must start no process")

        monkeypatch.setattr(subprocess, "Popen", refuse)
        monkeypatch.setattr(asyncio, "create_subprocess_exec", refuse_async)

        resp = world.client.post(APPROVE, json={"build_id": BUILD_ID})

        assert resp.status_code == 200, "premise: the route answered"
        world.approve.assert_not_awaited()
        world.worktrees.merge_to_main.assert_not_awaited()
        assert world.worktrees.mock_calls == []
        assert world.build.status == "reviewing"
        world.runtime.emit_event.assert_not_called()

    def test_the_route_no_longer_describes_a_merge(self) -> None:
        world = _world()
        route = next(r for r in world.app.routes if getattr(r, "path", "") == APPROVE)

        description = route.description.lower()

        assert "merge worktree to main" not in description
        assert "not merged" in description
```

**N1-2.** New file `ui/e2e/fixtures/bf937-queue-approve-unavailable.json` (the answer for the build of N1-1; the backend test compares the real route's body with it and the UI test feeds it to the components):

```json
{
  "status": "unavailable",
  "code": "local_merge_unavailable",
  "build_id": "b7d41c09e2a1",
  "merged": false,
  "branch": "builder-b7d41c09",
  "worktree_path": "/work/ProbOS-builders/builder-b7d41c09",
  "commit": "9f2c1ab",
  "message": "Not merged. Local merge is unavailable (BF-897), and a build is delivered through GitHub (AD-1336): until that delivery route exists the candidate branch stays unmerged. Candidate: branch builder-b7d41c09, commit 9f2c1ab, kept in /work/ProbOS-builders/builder-b7d41c09. Push it and open a pull request yourself, or reject the build to discard its worktree and branch."
}
```

**N1-3.** New file `ui/src/__tests__/BuildQueueApprove.bf937.test.tsx`:

```tsx
/** BF-937 (#1678): approving a build in review says what it is: not merged, and where its candidate branch is kept.
 *
 * The vessel's answer is `ui/e2e/fixtures/bf937-queue-approve-unavailable.json`, the file the backend test compares the
 * real route's answer with. The cases the unfixed tree fails are `built`, which is `it.fails` until BF-937 S1 M2 sets it to
 * `it`; with BF937_RUNXFAIL=1 they run as ordinary cases, so each can be seen to stop at its own assertion. No BF-937 name
 * is imported at the top: the helper is imported inside its own cases, by a variable path, so that this file type-checks
 * and loads before the helper exists. `globalThis.fetch` is replaced per case and restored.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, fireEvent, cleanup, act } from '@testing-library/react';
import { IntentSurface } from '../components/IntentSurface';
import { FullKanban } from '../components/bridge/FullKanban';
import { useStore } from '../store/useStore';
import type { BuildQueueItem, MissionControlTask, WSEvent } from '../store/types';
import unavailable from '../../e2e/fixtures/bf937-queue-approve-unavailable.json';

const built = process.env.BF937_RUNXFAIL === '1' ? it : it.fails;
const APPROVE = '/api/build/queue/approve';
const HELPER = '../store/buildQueueApprove';
const realFetch = globalThis.fetch;

type Call = { url: string; body: unknown };

/** Every request is recorded; the approve route answers `body`, everything else answers `{}`. */
function answerWith(body: unknown): Call[] {
  const calls: Call[] = [];
  globalThis.fetch = vi.fn().mockImplementation((url: unknown, init?: { body?: string }) => {
    calls.push({ url: String(url), body: init?.body ? JSON.parse(init.body) : null });
    return Promise.resolve({ ok: true, json: () => Promise.resolve(String(url) === APPROVE ? body : {}) });
  }) as unknown as typeof fetch;
  return calls;
}

/** The approve route is unreachable (the request fails); everything else answers `{}`. */
function noAnswer(): Call[] {
  const calls: Call[] = [];
  globalThis.fetch = vi.fn().mockImplementation((url: unknown, init?: { body?: string }) => {
    calls.push({ url: String(url), body: init?.body ? JSON.parse(init.body) : null });
    return String(url) === APPROVE
      ? Promise.reject(new TypeError('network down'))
      : Promise.resolve({ ok: true, json: () => Promise.resolve({}) });
  }) as unknown as typeof fetch;
  return calls;
}

async function flush(): Promise<void> {
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  globalThis.fetch = realFetch;
});

function reviewTask(): MissionControlTask {
  return {
    id: unavailable.build_id, type: 'build', title: 'Candidate build', department: 'engineering', status: 'review',
    agent_type: 'builder', agent_id: '', started_at: 0, completed_at: 0, priority: 5, ad_number: 0, error: '',
    metadata: {},
  };
}

function queueItem(status: BuildQueueItem['status']): BuildQueueItem {
  return {
    id: unavailable.build_id, title: 'Candidate build', ad_number: 0, status, priority: 5,
    worktree_path: unavailable.worktree_path, builder_id: '', error: '', file_footprint: [],
    commit_hash: unavailable.commit,
  };
}

describe('BF-937: the Mission Control card', () => {
  beforeEach(() => {
    useStore.setState({ missionControlTasks: [reviewTask()] });
  });
  afterEach(() => {
    useStore.setState({ missionControlTasks: null });
  });

  it('posts the build id to the approve route, as before', async () => {
    const calls = answerWith(unavailable);
    render(<FullKanban />);
    fireEvent.click(screen.getByText('Approve'));
    await flush();
    expect(calls).toEqual([{ url: APPROVE, body: { build_id: unavailable.build_id } }]);
  });

  it('rejects as before', async () => {
    const calls = answerWith({ status: 'ok', message: 'Build rejected' });
    render(<FullKanban />);
    fireEvent.click(screen.getByText('Reject'));
    await flush();
    expect(calls).toEqual([{ url: '/api/build/queue/reject', body: { build_id: unavailable.build_id } }]);
  });

  built('shows the answer the vessel gave, under the card', async () => {
    answerWith(unavailable);
    render(<FullKanban />);
    fireEvent.click(screen.getByText('Approve'));
    expect(await screen.findByRole('status')).toHaveTextContent(unavailable.message);
  });

  built('says so when the vessel gives no answer', async () => {
    noAnswer();
    render(<FullKanban />);
    fireEvent.click(screen.getByText('Approve'));
    expect(await screen.findByRole('status')).toHaveTextContent(/no answer from the vessel/i);
  });
});

function openShell() {
  const pillText = screen.queryByText(/Ask ProbOS/);
  if (pillText) {
    const clickable = pillText.closest('div');
    if (clickable) fireEvent.click(clickable);
  }
}

describe('BF-937: the Build Queue panel', () => {
  beforeEach(() => {
    useStore.setState({
      chatHistory: [], activeDag: [], pendingRequests: 0, agents: new Map(), buildQueue: [queueItem('reviewing')],
    });
  });
  afterEach(() => {
    useStore.setState({ buildQueue: null, chatHistory: [] });
  });

  function openTheShell(): void {
    render(<IntentSurface />);
    openShell();
  }

  it('posts the build id to the approve route, as before', async () => {
    const calls = answerWith(unavailable);
    openTheShell();
    fireEvent.click(await screen.findByText('Approve'));
    await flush();
    expect(calls.filter((call) => call.url === APPROVE)).toEqual([{ url: APPROVE, body: { build_id: unavailable.build_id } }]);
  });

  built('adds the answer the vessel gave to the chat', async () => {
    answerWith(unavailable);
    openTheShell();
    fireEvent.click(await screen.findByText('Approve'));
    expect(await screen.findByText(unavailable.message)).toBeInTheDocument();
  });

  built('says so in the chat when the vessel gives no answer', async () => {
    noAnswer();
    openTheShell();
    fireEvent.click(await screen.findByText('Approve'));
    expect(await screen.findByText(/no answer from the vessel/i)).toBeInTheDocument();
  });
});

const GENERATION = 'b'.repeat(32);
let nextSequence = 0;

function frame(type: string, data: Record<string, unknown>): WSEvent {
  return { type, data, timestamp: Date.now() / 1000, stream: { generation: GENERATION, sequence: nextSequence++ } };
}

function lastChatText(): string {
  const history = useStore.getState().chatHistory;
  return history.length > 0 ? history[history.length - 1].text : '';
}

describe('BF-937: the announcement of a build in the queue', () => {
  beforeEach(() => {
    nextSequence = 0;
    useStore.setState({ chatHistory: [], liveGeneration: null, liveSequence: 0, liveRepairEpoch: 0, buildQueue: null });
    useStore.getState().handleEvent(frame('state_snapshot', {
      agents: [], connections: [], pools: [], system_mode: 'active', tc_n: 0, routing_entropy: 0,
    }));
  });

  it('announces a build that starts building as before', () => {
    useStore.getState().handleEvent(frame('build_queue_item', { item: queueItem('building') }));
    expect(lastChatText()).toBe('Builder started: Candidate build');
  });

  built('announces a build that reaches review as a candidate that is not merged, with its place', () => {
    useStore.getState().handleEvent(frame('build_queue_item', { item: queueItem('reviewing') }));
    const text = lastChatText();
    expect(text).toContain('Build ready for review: Candidate build');
    expect(text).toContain(`Candidate branch kept in ${unavailable.worktree_path}`);
    expect(text).toMatch(/not merged/i);
    expect(text).toContain('AD-1336');
  });
});

describe('BF-937: the helper', () => {
  built('returns the vessel message, or a fixed line when it sent none', async () => {
    const { queueApproveMessage } = await import(/* @vite-ignore */ HELPER);
    expect(queueApproveMessage(unavailable)).toBe(unavailable.message);
    expect(queueApproveMessage({ status: 'error', message: 'Build x not in reviewing status' })).toBe(
      'Build x not in reviewing status',
    );
    for (const body of [null, undefined, 'text', 7, {}, { message: '' }, { message: '   ' }, { message: 3 }]) {
      expect(queueApproveMessage(body)).toBe('Approve request failed: no answer from the vessel. Nothing was merged.');
    }
  });

  built('never rejects: a network failure and an unreadable body read as no answer', async () => {
    const { approveQueuedBuild } = await import(/* @vite-ignore */ HELPER);
    noAnswer();
    await expect(approveQueuedBuild('x')).resolves.toMatch(/no answer from the vessel/);
    globalThis.fetch = vi.fn().mockResolvedValue({ ok: false, json: () => Promise.reject(new SyntaxError('not json')) }) as unknown as typeof fetch;
    await expect(approveQueuedBuild('x')).resolves.toMatch(/no answer from the vessel/);
  });
});
```

#### S1 M2

**P2-1.** `src/probos/routers/build.py`. The anchor is the two import lines (once).
SEARCH:
```
from probos.cognitive.builder_paths import operator_checkout_refusal
from probos.events import EventType
```
REPLACE:
```
from probos.build_queue import QueuedBuild
from probos.cognitive.builder_paths import operator_checkout_refusal
from probos.events import EventType
```

**P2-2.** `src/probos/routers/build.py`. The constants and the answer builder, after the last module constant (once).
SEARCH:
```
    "the cleanup notes in the failure report, then abort and start a new build."
)


@router.post("/submit")
```
REPLACE:
```
    "the cleanup notes in the failure report, then abort and start a new build."
)
#: BF-937 (#1678): the typed answer to approving a build in review (POST /api/build/queue/approve). Since BF-897 nothing
#: merges a build locally; a build is delivered through GitHub (AD-1336, child 6).
QUEUE_APPROVE_UNAVAILABLE = "unavailable"
QUEUE_APPROVE_UNAVAILABLE_CODE = "local_merge_unavailable"
QUEUE_APPROVE_NOT_MERGED = (
    "Not merged. Local merge is unavailable (BF-897), and a build is delivered through GitHub (AD-1336): "
    "until that delivery route exists the candidate branch stays unmerged."
)


def _queue_approve_unavailable(build: QueuedBuild) -> dict[str, Any]:
    """BF-937 (#1678): the answer to approving *build*, which is in review: not merged, and where its branch is kept."""
    result = build.result
    branch = result.branch_name if result is not None else ""
    commit = result.commit_hash if result is not None else ""
    message = QUEUE_APPROVE_NOT_MERGED
    if branch:
        message += f" Candidate: branch {branch}"
        if commit:
            message += f", commit {commit[:7]}"
        if build.worktree_path:
            message += f", kept in {build.worktree_path}"
        message += ". Push it and open a pull request yourself, or reject the build to discard its worktree and branch."
    else:
        message += " Reject the build to discard it."
    return {
        "status": QUEUE_APPROVE_UNAVAILABLE,
        "code": QUEUE_APPROVE_UNAVAILABLE_CODE,
        "build_id": build.id,
        "merged": False,
        "branch": branch,
        "worktree_path": build.worktree_path,
        "commit": commit,
        "message": message,
    }


@router.post("/submit")
```

**P2-3.** `src/probos/routers/build.py`. The route. **This SEARCH holds one U+2014 (the em dash of the old docstring line, which must go).**
SEARCH:
```
@router.post("/queue/approve")
async def approve_queued_build(
    req: BuildQueueApproveRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Captain approves a queued build — merge worktree to main."""
    if not runtime.build_dispatcher:
        return {"status": "error", "message": "Build dispatcher not running"}
    ok, result = await runtime.build_dispatcher.approve_and_merge(req.build_id)
    if ok:
        _emit_queue_snapshot(runtime)
        return {"status": "ok", "commit": result, "message": f"Build merged: {result[:7]}"}
    return {"status": "error", "message": result}
```
REPLACE:
```
@router.post("/queue/approve")
async def approve_queued_build(
    req: BuildQueueApproveRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Answer the Captain's approval of a build in review: it is not merged (BF-937, #1678).

    Since BF-897 nothing merges a build into the checkout ProbOS runs from, so approving can only say that. The answer is
    typed (``status`` ``unavailable``, ``code`` ``local_merge_unavailable``, ``merged`` false) and names the candidate branch,
    the worktree that keeps it and that delivery comes through GitHub (AD-1336, child 6). No git command runs and no
    dispatcher method is called: ``approve_and_merge`` and ``merge_to_main`` keep BF-897's refusal, unchanged, for the
    delivery route that replaces it. A dispatcher that is not running, or a build that is not in review, is answered as before.
    """
    queue = runtime.build_queue
    if not runtime.build_dispatcher or queue is None:
        return {"status": "error", "message": "Build dispatcher not running"}
    build = queue.get(req.build_id)
    if build is None or build.status != "reviewing":
        return {"status": "error", "message": f"Build {req.build_id} not in reviewing status"}
    answer = _queue_approve_unavailable(build)
    logger.warning(
        "build queue approve not merged build_id=%s branch=%s: local merge is unavailable (BF-897)",
        req.build_id, answer["branch"],
    )
    return answer
```

**P2-4.** New file `ui/src/store/buildQueueApprove.ts`:

```ts
/* BF-937 (#1678): the Approve control of a build in review asks the vessel to merge it. Since BF-897 the vessel never
 * merges a build locally (a build is delivered through GitHub, AD-1336), so what the Captain needs from the click is the
 * vessel's answer, in the vessel's words: not merged, and where the candidate branch is kept. */

export const QUEUE_APPROVE_URL = '/api/build/queue/approve';

/** Shown when the vessel gave no readable answer: the click is not lost, and nothing is claimed about the build. */
export const QUEUE_APPROVE_NO_ANSWER = 'Approve request failed: no answer from the vessel. Nothing was merged.';

/** The line to show for the vessel's answer body: its `message`, or the fixed no-answer line when it sent none. */
export function queueApproveMessage(body: unknown): string {
  if (typeof body === 'object' && body !== null) {
    const message = (body as { message?: unknown }).message;
    if (typeof message === 'string' && message.trim() !== '') return message;
  }
  return QUEUE_APPROVE_NO_ANSWER;
}

/** Ask the vessel to approve the build in review `buildId`; resolves to the line to show the Captain, and never rejects. */
export async function approveQueuedBuild(buildId: string): Promise<string> {
  try {
    const response = await fetch(QUEUE_APPROVE_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ build_id: buildId }),
    });
    return queueApproveMessage(await response.json());
  } catch {
    return QUEUE_APPROVE_NO_ANSWER;
  }
}
```

**P2-5.** `ui/src/components/IntentSurface.tsx`. The file holds non-ASCII lines elsewhere; this SEARCH is one ASCII line, once.
SEARCH:
```
import { denialNotice, policyDenialOf } from '../chat/policyDenial';
```
REPLACE:
```
import { denialNotice, policyDenialOf } from '../chat/policyDenial';
import { approveQueuedBuild } from '../store/buildQueueApprove';
```

**P2-6.** `ui/src/components/IntentSurface.tsx`. The Approve click of the Build Queue panel (the Reject click below it posts to `/queue/reject` and is not touched). All lines ASCII.
SEARCH:
```
                              try {
                                await fetch('/api/build/queue/approve', {
                                  method: 'POST',
                                  headers: { 'Content-Type': 'application/json' },
                                  body: JSON.stringify({ build_id: item.id }),
                                });
                              } catch { /* ignore */ }
```
REPLACE:
```
                              addChatMessage('system', await approveQueuedBuild(item.id));
```

**P2-7.** `ui/src/components/bridge/FullKanban.tsx`. Line 1 of the file holds a non-ASCII dash; these SEARCH lines are ASCII, once.
SEARCH:
```
import { useStore } from '../../store/useStore';
import type { MissionControlTask } from '../../store/types';
```
REPLACE:
```
import { useState } from 'react';
import { useStore } from '../../store/useStore';
import { approveQueuedBuild } from '../../store/buildQueueApprove';
import type { MissionControlTask } from '../../store/types';
```

**P2-8.** `ui/src/components/bridge/FullKanban.tsx`. The card's state (once).
SEARCH:
```
function KanbanCard({ task }: { task: MissionControlTask }) {
  const deptColor = DEPT_COLORS[task.department] || '#888';
```
REPLACE:
```
function KanbanCard({ task }: { task: MissionControlTask }) {
  const deptColor = DEPT_COLORS[task.department] || '#888';
  // BF-937 (#1678): what the vessel answered to the last Approve click on this card.
  const [note, setNote] = useState('');
```

**P2-9.** `ui/src/components/bridge/FullKanban.tsx`. The Approve click (the Reject click posts to `/queue/reject` and is not touched).
SEARCH:
```
              try {
                await fetch('/api/build/queue/approve', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ build_id: task.id }),
                });
              } catch { /* ignore */ }
```
REPLACE:
```
              setNote(await approveQueuedBuild(task.id));
```

**P2-10.** `ui/src/components/bridge/FullKanban.tsx`. The note, before the failed-task line (once).
SEARCH:
```
      {task.status === 'failed' && task.error && (
```
REPLACE:
```
      {note && (
        <div role="status" style={{ color: '#d0a030', fontSize: 9, marginTop: 4, marginLeft: 12 }}>
          {note}
        </div>
      )}
      {task.status === 'failed' && task.error && (
```

**P2-11.** `ui/src/store/useStore.ts`. The file holds non-ASCII lines elsewhere; these SEARCH lines are ASCII, once. The announcement of a build in review.
SEARCH:
```
        } else if (item.status === 'reviewing') {
          get().addChatMessage('system',
            `Build ready for review: ${item.title}${item.ad_number ? ` (AD-${item.ad_number})` : ''}`);
```
REPLACE:
```
        } else if (item.status === 'reviewing') {
          // BF-937 (#1678): a build in review is a candidate branch, not a merge: say so, and where its worktree is kept.
          const kept = item.worktree_path ? ` Candidate branch kept in ${item.worktree_path}.` : '';
          get().addChatMessage('system',
            `Build ready for review: ${item.title}${item.ad_number ? ` (AD-${item.ad_number})` : ''}.${kept}`
            + ' It is not merged: local merge is unavailable, and delivery comes through GitHub (AD-1336).');
```

**N2-1.** `tests/test_dispatch_wiring.py`. The stub of the shared fixture: it pinned a merge success the real chain cannot reach (section 6); it becomes a tripwire.
SEARCH:
```
    rt.build_dispatcher.approve_and_merge = AsyncMock(return_value=(True, "abc1234def"))
```
REPLACE:
```
    # BF-937 (#1678): the route no longer asks the dispatcher to merge (since BF-897 the real chain can only refuse), so a
    # call is a defect. This stub used to answer (True, ...), a state the real chain cannot reach, and a case asserted it.
    rt.build_dispatcher.approve_and_merge = AsyncMock(
        side_effect=AssertionError("the approve route must not call approve_and_merge"),
    )
```

**N2-2.** `tests/test_dispatch_wiring.py`. The case that asserted the merge: the build is now put in review and the answer is the typed not-merged one (the full contract is `tests/test_bf937_queue_approve.py`).
SEARCH:
```
    def test_approve_queued_build(self, client) -> None:
        """POST /api/build/queue/approve calls dispatcher.approve_and_merge."""
        tc, rt = client
        resp = tc.post("/api/build/queue/approve", json={"build_id": "abc123"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "abc1234" in data["commit"]
        rt.build_dispatcher.approve_and_merge.assert_awaited_once_with("abc123")
```
REPLACE:
```
    def test_approve_queued_build(self, client) -> None:
        """POST /api/build/queue/approve answers that the build is not merged and never asks the dispatcher to merge.

        BF-937 (#1678): this case asserted ``status == "ok"`` and a merge commit from a dispatcher double that answered
        ``(True, ...)``: the route's success path, which BF-897 made unreachable (the real chain refuses). It pinned a merge
        that cannot happen. The build is now put in review and the answer is the typed not-merged one.
        """
        from probos.cognitive.builder import BuildSpec

        tc, rt = client
        build = rt.build_queue.enqueue(BuildSpec(title="Wired", description="d"))
        for step in ("dispatched", "building", "reviewing"):
            assert rt.build_queue.update_status(build.id, step), f"premise: the build moves to {step}"
        resp = tc.post("/api/build/queue/approve", json={"build_id": build.id})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "unavailable"
        assert data["merged"] is False
        rt.build_dispatcher.approve_and_merge.assert_not_awaited()
```

**N2-3.** `tests/test_bf937_queue_approve.py`. The marker, removed: the class is now an ordinary one.
SEARCH:
```
@pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-937 S1 M2: the route answers not merged, typed (#1678)")
class TestApprovingABuildInReviewAnswersNotMerged:
```
REPLACE:
```
class TestApprovingABuildInReviewAnswersNotMerged:
```

**N2-4.** `ui/src/__tests__/BuildQueueApprove.bf937.test.tsx`. The marker, removed: every `built` is now `it`.
SEARCH:
```
const built = process.env.BF937_RUNXFAIL === '1' ? it : it.fails;
```
REPLACE:
```
const built = it;
```

#### S1 M3: tracking

**P3-1.** `PROGRESS.md`. The anchor is the title line and the blank line after it (once, and unchanged by BF-934 and BF-936). Replace `DATE` with M3's date.
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**BF-937 slice 1 (DATE), #1678 -- approving a build in review says that it is not merged and where its candidate branch is kept.**
- **Base.** `POST /api/build/queue/approve` described a merge ("merge worktree to main") and asked `BuildDispatcher.approve_and_merge`, which since BF-897 always refuses; the two HXI call sites (`IntentSurface.tsx`, `bridge/FullKanban.tsx`) discarded the answer, so the Approve control did nothing the Captain could see, and the announcement of a build in review named no branch and no place. `tests/test_dispatch_wiring.py` pinned a merge success the real chain cannot reach.
- **Fix.** For a build in review the route answers HTTP 200 `{"status": "unavailable", "code": "local_merge_unavailable", "merged": false, "build_id", "branch", "worktree_path", "commit", "message"}`, the message saying: not merged, local merge unavailable (BF-897), delivery through GitHub (AD-1336), where the candidate is, and the two ways on. The route calls no dispatcher method and runs no git command; `approve_and_merge` and `merge_to_main` are unchanged. A dispatcher that is not running and a build not in review are answered as before. `ui/src/store/buildQueueApprove.ts` posts the click and returns the line; `IntentSurface` adds it to the chat, `FullKanban` shows it under the card, and the "Build ready for review" line says the candidate is not merged and where its worktree is. `docs/development/deterministic-ship.md` drops the gap this closes. Contract `prompts/bf-937-legacy-self-modification-leftovers.md`, slice 1. Refs #1678.

```

**P3-2.** `DECISIONS.md`. The anchor is the heading line of the entry that follows the BF entries (once on the BF-936 head, where it is the line BF-936's own P3-2 inserted its entry before); the entry is inserted before it, so it lands after BF-934's and BF-936's (A1: the first text anchored on the last line of BF-935's entry, which put it before both). If a later change moves that heading, anchor on the last line of the entry that then lands last. Replace `DATE` with M3's date.
SEARCH:
```
### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```
REPLACE:
```
### BF-937 slice 1 -- The build-approve route and both HXI call sites say that a build is not merged and where its candidate branch is kept (DATE, #1678)

- *Scope.* `routers/build.py` (`/queue/approve`), `ui/src/store/buildQueueApprove.ts` (new), `IntentSurface.tsx`, `bridge/FullKanban.tsx`, `store/useStore.ts` (the `reviewing` line), `tests/test_dispatch_wiring.py`, tests, one line of `docs/development/deterministic-ship.md`. Contract `prompts/bf-937-legacy-self-modification-leftovers.md`.
- *G1 (the answer).* HTTP 200, `status: "unavailable"`, `code`, `merged: false`, the branch, the worktree and the commit, and a message; the route calls nothing. Rejected: HTTP 409 or 501 (the router answers 200 everywhere and no consumer reads the status line); a `build_failure` event (it names a failure for a build that is fine, clears an unrelated build's progress, and BF-897 refused it for this route); keeping the call to `approve_and_merge` and typing its text.
- *G2 (the call sites).* One helper; a chat line in `IntentSurface`, a note under the card in `FullKanban`. Rejected: a hidden or disabled control with a fixed explanation (a static claim that AD-1336 child 6 reverses).
- *G3 (the seam).* `approve_and_merge` and `merge_to_main` are unchanged and have no production caller until AD-1336 child 6 re-wires them or replaces the queue.
- *Residual.* L1 to L9 of the contract (S1). *Reversal.* Revert the BF-937 slice 1 commits.

### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```

**P3-3.** `docs/development/deterministic-ship.md`. Line 54, the "Honest self-report" row of the invariant table, lists "a merge the UI offers that always refuses (BF-937, #1678)" as a known gap; S1 closes it, so the clause goes. The SEARCH is the whole line (it occurs once and is ASCII), because the clause sits in its middle.
SEARCH:
```
| **6. Honest self-report** | The ship states only what it observed. Unknown is reported as unknown, never as a default or a success. | Activation receipts record what startup actually wired and claim no health or exercise (`maturity/receipts.py:1-11`, `:56-68`). The maturity report answers `UNKNOWN`, never `FALSE`, for an input it cannot resolve (`maturity/report.py:13-16`). The report-only dormant-class check lists classes nothing uses (`scripts/check_dormant_classes.py:1-6`, baseline `docs/development/dormant-class-baseline.yaml`). A trust miss is reported as "no record", not as the 0.5 prior (BF-907, `DECISIONS.md:245-246`). Inert config fields say so (`config.py:2976`). | The AD-486 Birth Chamber admits almost no one and graduates no one, silently (AD-1355, #1700, Problem items 1-10). The boot-camp slot-id count above. A recall gate never bound (BF-938, #1680); verification and alert producers nothing calls (AD-1352, #1658); a merge the UI offers that always refuses (BF-937, #1678). Orientation would tell an agent with a history it "was commissioned moments ago" (`cognitive/orientation.py:352`; #1700 track E). |
```
REPLACE:
```
| **6. Honest self-report** | The ship states only what it observed. Unknown is reported as unknown, never as a default or a success. | Activation receipts record what startup actually wired and claim no health or exercise (`maturity/receipts.py:1-11`, `:56-68`). The maturity report answers `UNKNOWN`, never `FALSE`, for an input it cannot resolve (`maturity/report.py:13-16`). The report-only dormant-class check lists classes nothing uses (`scripts/check_dormant_classes.py:1-6`, baseline `docs/development/dormant-class-baseline.yaml`). A trust miss is reported as "no record", not as the 0.5 prior (BF-907, `DECISIONS.md:245-246`). Inert config fields say so (`config.py:2976`). | The AD-486 Birth Chamber admits almost no one and graduates no one, silently (AD-1355, #1700, Problem items 1-10). The boot-camp slot-id count above. A recall gate never bound (BF-938, #1680); verification and alert producers nothing calls (AD-1352, #1658). Orientation would tell an agent with a history it "was commissioned moments ago" (`cognitive/orientation.py:352`; #1700 track E). |
```

**Ledger.** Run G3. The roadmap Bug Tracker is not edited.

### 7.2 Slice S2 (persistence refuses the source checkout; the data directory is the default)

#### S2 M1

**N1-1.** New file `tests/test_bf937_promoted_agents_root.py`:

```python
"""BF-937 (#1678): self-improvement persistence never writes promoted agent source into the source checkout.

The refusals run on the real checkout the code under test lives in (its ``.git`` entry is a premise) and on the real
``operator_checkout_refusal``; the chain case wires the pipeline with its default over ``tmp_path`` and writes through it
(the evolution store is a double: no network, no database). Every case that changes the current directory or a module
attribute restores it. The class holds the cases the unfixed tree fails; the functions before it pass on both. No BF-937
name is imported at the top: the module attribute the drift case needs is read inside it, behind a premise.
"""

from __future__ import annotations

import inspect
import logging
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import yaml

from probos.cognitive.self_improvement import AgentVersion, LocalDiskPersistence, versioning
from probos.cognitive.self_improvement.versioning import compute_source_hash

CHECKOUT = Path(versioning.__file__).resolve().parents[4]  # the checkout the code under test runs from
REPO = Path(__file__).resolve().parents[1]  # the checkout this file sits in
OLD_DEFAULT = "src/probos/agents/designed"
SOURCE = "def x():\n    pass\n"


def _premise_checkout() -> None:
    assert os.path.lexists(CHECKOUT / ".git"), f"premise: {CHECKOUT} is a git checkout (a .git directory, or a linked worktree's .git file)"
    assert (CHECKOUT / "src" / "probos").is_dir(), "premise: the checkout holds the source tree"


def _version(number: int) -> AgentVersion:
    return AgentVersion(
        version=number, parent_version=None, designed_at=0.0, designer="test",
        trust_alpha_at_promotion=1.0, trust_beta_at_promotion=1.0, source_hash=compute_source_hash(f"src_v{number}"),
    )


def _record() -> SimpleNamespace:
    return SimpleNamespace(agent_type="foo_agent", source_code=SOURCE)


def _refusal(root: str) -> str | None:
    """What building a persistence over *root* answers: the refusal text, or None when it was accepted."""
    try:
        LocalDiskPersistence(root_dir=root)
    except ValueError as exc:
        return str(exc)
    return None


async def test_a_root_outside_the_checkout_still_writes(tmp_path: Path) -> None:
    root = tmp_path / "promoted"
    persistence = LocalDiskPersistence(root_dir=str(root))

    path = await persistence.promote(_record(), _version(1))

    assert path, "the write answered its path"
    assert (root / "foo_agent_v1.py").read_text(encoding="utf-8") == SOURCE
    meta = (root / "foo_agent_v1.meta.yaml").read_text(encoding="utf-8")
    assert "agent_type: foo_agent" in meta and "version: 1" in meta


@pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-937 S2 M2: persistence refuses a root inside the source checkout (#1678)")
class TestPersistenceNeverWritesIntoTheSourceCheckout:
    @pytest.mark.parametrize(
        "where",
        ["relative-old-default", "absolute-old-default", "deeper-in-src", "config-dir", "the-checkout-itself"],
    )
    def test_a_root_inside_the_checkout_is_refused(self, where: str, monkeypatch: pytest.MonkeyPatch) -> None:
        _premise_checkout()
        monkeypatch.chdir(CHECKOUT)  # a relative root is read from here
        root = {
            "relative-old-default": OLD_DEFAULT,
            "absolute-old-default": str(CHECKOUT / OLD_DEFAULT),
            "deeper-in-src": str(CHECKOUT / "src" / "probos" / "cognitive" / "a_new_directory"),
            "config-dir": str(CHECKOUT / "config" / "promoted"),
            "the-checkout-itself": str(CHECKOUT),
        }[where]

        refusal = _refusal(root)

        assert refusal is not None, f"{root!r} was accepted"
        assert "inside the checkout" in refusal and "BF-937" in refusal
        assert not (CHECKOUT / OLD_DEFAULT).exists(), "premise: building the persistence wrote nothing"

    async def test_a_root_that_becomes_inside_the_checkout_writes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        assert hasattr(versioning, "_CHECKOUT_ROOT"), "premise: the module names the checkout it runs from"
        root = tmp_path / "promoted"
        persistence = LocalDiskPersistence(root_dir=str(root))  # allowed: tmp_path is no checkout
        (tmp_path / ".git").mkdir()
        # The checkout now holds the root, as a link swapped in after construction would make it.
        monkeypatch.setattr(versioning, "_CHECKOUT_ROOT", tmp_path)

        with caplog.at_level(logging.ERROR):
            path = await persistence.promote(_record(), _version(1))

        assert path == ""
        assert not root.exists(), "nothing was written, not even the directory"
        assert "BF-937" in caplog.text

    async def test_a_relative_root_is_pinned_when_the_persistence_is_built(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        here, there = tmp_path / "here", tmp_path / "there"
        here.mkdir()
        there.mkdir()
        monkeypatch.chdir(here)
        persistence = LocalDiskPersistence(root_dir="promoted")
        monkeypatch.chdir(there)

        await persistence.promote(_record(), _version(1))

        assert (here / "promoted" / "foo_agent_v1.py").is_file(), "the write followed the directory the object was built in"
        assert not (there / "promoted").exists()

    async def test_the_wiring_refuses_a_root_inside_the_checkout_before_it_opens_anything(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        from probos.config import SystemConfig
        from probos.startup.finalize import _wire_self_improvement

        _premise_checkout()
        monkeypatch.chdir(CHECKOUT)
        runtime = SimpleNamespace(data_dir=tmp_path, emit_event=None, spawner=None, codebase_index=None)
        config = SystemConfig(self_improvement={"enabled": True, "persistence_root_dir": OLD_DEFAULT})

        with patch("probos.cognitive.self_improvement.EvolutionStore") as evolution_type, caplog.at_level(logging.ERROR):
            wired = await _wire_self_improvement(runtime=runtime, config=config)

        assert wired is False
        evolution_type.assert_not_called()
        assert not hasattr(runtime, "agent_persistence"), "nothing was attached"
        assert "BF-937" in caplog.text and "inside the checkout" in caplog.text
        assert not (CHECKOUT / OLD_DEFAULT).exists()

    async def test_the_default_root_is_under_the_data_directory_and_the_pipeline_writes_there(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from probos.config import SystemConfig
        from probos.startup.finalize import _wire_self_improvement

        data_dir, cwd = tmp_path / "data", tmp_path / "cwd"
        data_dir.mkdir()
        cwd.mkdir()
        monkeypatch.chdir(cwd)  # the unfixed default is relative to here, so the unfixed tree cannot write into the repository
        runtime = SimpleNamespace(data_dir=data_dir, emit_event=None, spawner=None, codebase_index=None)
        config = SystemConfig(self_improvement={"enabled": True})
        with patch("probos.cognitive.self_improvement.EvolutionStore") as evolution_type:
            evolution_type.return_value.record_lesson = MagicMock(return_value="lesson")
            assert await _wire_self_improvement(runtime=runtime, config=config) is True, "premise: the pipeline is wired"

        path = await runtime.agent_persistence.promote(_record(), _version(1))

        promoted = data_dir / "promoted-agents"
        assert (promoted / "foo_agent_v1.py").is_file(), "the source landed under the data directory"
        assert (promoted / "foo_agent_v1.meta.yaml").is_file()
        assert Path(path) == (promoted / "foo_agent_v1.py").resolve()
        assert not (cwd / "src").exists(), "nothing landed under the old relative default"

    def test_the_shipped_default_is_not_a_source_path(self) -> None:
        from probos.config import SelfImprovementConfig

        assert SelfImprovementConfig().persistence_root_dir == ""
        shipped = yaml.safe_load((REPO / "config" / "system.yaml").read_text(encoding="utf-8"))
        assert shipped["self_improvement"]["persistence_root_dir"] == ""

    def test_the_class_carries_no_default_location(self) -> None:
        parameter = inspect.signature(LocalDiskPersistence).parameters["root_dir"]
        assert parameter.default is inspect.Parameter.empty

    @pytest.mark.skipif(os.name != "nt", reason="paths are case-insensitive on Windows only")
    def test_the_case_of_the_path_does_not_matter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _premise_checkout()
        monkeypatch.chdir(CHECKOUT)
        varied = str(CHECKOUT / OLD_DEFAULT).swapcase()
        assert varied != str(CHECKOUT / OLD_DEFAULT), "premise: the spelling differs"

        refusal = _refusal(varied)

        assert refusal is not None, f"{varied!r} was accepted"

    def test_a_link_into_the_checkout_is_refused(self, tmp_path: Path) -> None:
        _premise_checkout()
        link = tmp_path / "link"
        try:
            os.symlink(CHECKOUT / "src", link, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("this account cannot create a symbolic link")

        refusal = _refusal(str(link / "promoted"))

        assert refusal is not None, "a root reached through a link into src was accepted"
```

#### S2 M2

**P2-1.** `src/probos/cognitive/self_improvement/versioning.py`. The module docstring's claim of the location (once).
SEARCH:
```
* `AgentPersistence` Protocol + `LocalDiskPersistence` default impl write
  promoted agent source to ``src/probos/agents/designed/{agent_type}_v{N}.py``
  plus a ``{agent_type}_v{N}.meta.yaml`` sidecar. Git PR creation is the
  AD-482h-1 follow-on (subprocess git + GitHub MCP wiring is its own AD).
```
REPLACE:
```
* `AgentPersistence` Protocol + `LocalDiskPersistence` default impl write
  promoted agent source to ``{root}/{agent_type}_v{N}.py`` (``{data_dir}/promoted-agents``
  unless configured; never inside the source checkout, BF-937) plus a
  ``{agent_type}_v{N}.meta.yaml`` sidecar. Git PR creation is the
  AD-482h-1 follow-on (subprocess git + GitHub MCP wiring is its own AD).
```

**P2-2.** `src/probos/cognitive/self_improvement/versioning.py`. The one import (once).
SEARCH:
```
from typing import Any, Callable, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from probos.cognitive.self_mod import DesignedAgentRecord
```
REPLACE:
```
from typing import Any, Callable, Protocol, TYPE_CHECKING

from probos.cognitive.builder_paths import operator_checkout_refusal

if TYPE_CHECKING:
    from probos.cognitive.self_mod import DesignedAgentRecord
```

**P2-3.** `src/probos/cognitive/self_improvement/versioning.py`. The checkout, the default and the rule, and the class's docstring and constructor (once).
SEARCH:
```
    return hashlib.sha256(source_code.encode("utf-8")).hexdigest()[:16]


class LocalDiskPersistence:
    """AD-482h v1: write promoted agent source to local disk.

    Args:
        root_dir: Directory under which agent files are written. Default
            ``src/probos/agents/designed`` per roadmap.md:3733.
        clock: Time source for sidecar metadata.
    """

    def __init__(
        self,
        *,
        root_dir: str = "src/probos/agents/designed",
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._root = Path(root_dir)
        self._clock = clock
```
REPLACE:
```
    return hashlib.sha256(source_code.encode("utf-8")).hexdigest()[:16]


#: BF-937 (#1678): the checkout this module runs from (src/probos/cognitive/self_improvement -> repository), the one
#: ``builder.py`` and ``routers/build.py`` protect with ``operator_checkout_refusal`` (BF-897). An installed package has no
#: ``.git`` entry there, and the rule then finds no checkout to protect.
_CHECKOUT_ROOT = Path(__file__).resolve().parents[4]

#: BF-937 (#1678): the directory under the data directory that promoted agent source goes to when no root is configured.
PROMOTED_AGENTS_DIRNAME = "promoted-agents"


def resolve_promoted_agents_dir(root_dir: str, data_dir: str | Path) -> Path:
    """BF-937 (#1678): where promoted agent source is written: *root_dir* when set, else ``{data_dir}/promoted-agents``.

    The one place the default is named (the shape of ``probos.config.resolve_records_repo_path``). A relative *root_dir* is
    relative to the current directory, as ``Path.mkdir`` reads it, and ``~`` is not expanded.
    """
    if root_dir:
        return Path(root_dir)
    return Path(data_dir) / PROMOTED_AGENTS_DIRNAME


def persistence_root_refusal(root_dir: str | Path) -> str | None:
    """BF-937 (#1678): why promoted agent source must not be written under *root_dir*, or None if it may be.

    A repository change goes through GitHub (AD-1336), so promoted source is never written into the checkout ProbOS runs
    from. The rule is ``operator_checkout_refusal`` (BF-897) over ``_CHECKOUT_ROOT``: *root_dir* is resolved (links and
    junctions followed, a relative path against the current directory, case and 8.3 names by file identity) and refused
    when its nearest ``.git`` entry is the checkout's; a linked worktree has its own and is allowed, and so is a directory
    outside any checkout. No git command runs. A path that cannot be examined is refused.
    """
    if operator_checkout_refusal(root_dir, _CHECKOUT_ROOT) is None:
        return None
    return (
        f"promoted agent source is not written into the source checkout: {str(root_dir)!r} is inside the checkout "
        f"ProbOS runs from ({_CHECKOUT_ROOT}), or could not be checked against it (BF-937). A repository change goes "
        "through GitHub (AD-1336). Leave self_improvement.persistence_root_dir empty to use {data_dir}/promoted-agents, "
        "or name a directory outside the checkout."
    )


class LocalDiskPersistence:
    """AD-482h v1: write promoted agent source to local disk.

    Args:
        root_dir: Directory under which agent files are written. Required: this class names no location of its own
            (BF-937: it was ``src/probos/agents/designed``, inside the checkout). A root inside the source checkout is
            refused with ``ValueError``; a relative root is resolved against the current directory when the object is built.
        clock: Time source for sidecar metadata.
    """

    def __init__(
        self,
        *,
        root_dir: str,
        clock: Callable[[], float] = time.time,
    ) -> None:
        refusal = persistence_root_refusal(root_dir)
        if refusal is not None:
            raise ValueError(refusal)
        self._root = Path(root_dir).resolve()
        self._clock = clock
```

**P2-4.** `src/probos/cognitive/self_improvement/versioning.py`. `promote` judges its root again before it writes (once).
SEARCH:
```
        Returns the persisted path on success, or "" on failure.
        """
        agent_type = getattr(record, "agent_type", "")
        source_code = getattr(record, "source_code", "")
        if not agent_type or not source_code:
            logger.warning(
                "AD-482h: promote skipped -- record missing agent_type or source_code",
            )
            return ""
        try:
            self._root.mkdir(parents=True, exist_ok=True)
```
REPLACE:
```
        Returns the persisted path on success, or "" on failure, or when the root is inside the source checkout (BF-937).
        """
        agent_type = getattr(record, "agent_type", "")
        source_code = getattr(record, "source_code", "")
        if not agent_type or not source_code:
            logger.warning(
                "AD-482h: promote skipped -- record missing agent_type or source_code",
            )
            return ""
        refusal = persistence_root_refusal(self._root)
        if refusal is not None:
            # BF-937 (#1678): the root was allowed when this object was built; a link swapped in since is judged now.
            logger.error("BF-937: LocalDiskPersistence.promote refused for %s: %s", agent_type, refusal)
            return ""
        try:
            self._root.mkdir(parents=True, exist_ok=True)
```

**P2-5.** `src/probos/startup/finalize.py`. The one import the wiring needs, inside the existing guarded import block (once).
SEARCH:
```
            SymbolExistenceProvider,
        )
    except Exception:
```
REPLACE:
```
            SymbolExistenceProvider,
        )
        from probos.cognitive.self_improvement.versioning import resolve_promoted_agents_dir
    except Exception:
```

**P2-6.** `src/probos/startup/finalize.py`. The persistence is built first, so that a refusal stops the wiring before any store opens (once).
SEARCH:
```
    emit = getattr(runtime, "emit_event", None)

    evolution_store = EvolutionStore(
        chroma_path=runtime.data_dir,
```
REPLACE:
```
    # BF-937 (#1678): the persistence is built before any store opens, so a root inside the source checkout stops the
    # wiring here, whole: nothing is opened, attached or half-wired, and the vessel boots without the pipeline.
    try:
        agent_persistence = LocalDiskPersistence(
            root_dir=str(resolve_promoted_agents_dir(cfg.persistence_root_dir, runtime.data_dir)),
        )
    except ValueError as exc:
        logger.error("BF-937: self_improvement is not wired: %s", exc)
        return False

    emit = getattr(runtime, "emit_event", None)

    evolution_store = EvolutionStore(
        chroma_path=runtime.data_dir,
```

**P2-7.** `src/probos/startup/finalize.py`. The late construction goes (once).
SEARCH:
```
    agent_version_store = AgentVersionStore(event_emit_fn=emit)
    agent_persistence = LocalDiskPersistence(root_dir=cfg.persistence_root_dir)
    shadow_deployment_policy = NoOpShadowDeploymentPolicy()
```
REPLACE:
```
    agent_version_store = AgentVersionStore(event_emit_fn=emit)
    shadow_deployment_policy = NoOpShadowDeploymentPolicy()
```

**P2-8.** `src/probos/config_models/knowledge.py`. The class docstring and the field (once).
SEARCH:
```
    new ChromaDB collection, and writes promoted agents to
    ``src/probos/agents/designed/``. AD-633 / AD-695 default-False precedent.
    """

    enabled: bool = False
    qa_pool_size: int = Field(default=3, ge=1, le=8)
    iteration_cap: int = Field(default=5, ge=1, le=20)
    evolution_half_life_seconds: float = Field(default=2592000.0, ge=1.0)  # 30 days
    evolution_collection_name: str = "self_improvement_lessons"
    persistence_root_dir: str = "src/probos/agents/designed"
```
REPLACE:
```
    new ChromaDB collection, and writes promoted agents to
    ``{data_dir}/promoted-agents/`` (BF-937: never into the source checkout).
    AD-633 / AD-695 default-False precedent.
    """

    enabled: bool = False
    qa_pool_size: int = Field(default=3, ge=1, le=8)
    iteration_cap: int = Field(default=5, ge=1, le=20)
    evolution_half_life_seconds: float = Field(default=2592000.0, ge=1.0)  # 30 days
    evolution_collection_name: str = "self_improvement_lessons"
    persistence_root_dir: str = Field(
        default="",
        description=(
            "Where promoted agent source is written. Empty means {data_dir}/promoted-agents. A directory inside the "
            "source checkout ProbOS runs from is refused (BF-937, #1678): repository changes go through GitHub."
        ),
    )
```

**P2-9.** `config/system.yaml`. The shipped value (once).
SEARCH:
```
  persistence_root_dir: src/probos/agents/designed
```
REPLACE:
```
  persistence_root_dir: ""  # BF-937 (#1678): empty = {data_dir}/promoted-agents; a directory inside the source checkout is refused
```

**N2-1.** `tests/test_ad1270e2f_knowledge_models.py`. The snapshot of the old default, a default this item changes on purpose (section 6).
SEARCH:
```
                                 'persistence_root_dir': 'src/probos/agents/designed'},
```
REPLACE:
```
                                 'persistence_root_dir': ''},  # BF-937 (#1678): was 'src/probos/agents/designed'; empty = {data_dir}/promoted-agents
```

**N2-2.** `tests/test_bf937_promoted_agents_root.py`. The marker, removed.
SEARCH:
```
@pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-937 S2 M2: persistence refuses a root inside the source checkout (#1678)")
class TestPersistenceNeverWritesIntoTheSourceCheckout:
```
REPLACE:
```
class TestPersistenceNeverWritesIntoTheSourceCheckout:
```

**Generated artifacts (after the nine pairs and the two updates; see S2's gate list).** Run `PY -P scripts/gen_config_reference.py` and `PY -P scripts/check_config_facade.py --update-baseline`; commit the two files with M2. They are generated, not edited by pair (the reference's header says so).

**P2-10 (a script, not a pair; amendment A1).** `tests/fixtures/ad1152_agentic_off_golden.json`. The golden pins the SHA-256 of the default `SystemConfig()` dump (`observation.default_config_sha256`, line 17) and the digest of the whole observation (`observation_sha256`, line 15); the new default of `self_improvement.persistence_root_dir` moves the first and so the second (BF-926's A1 and AD-1270's slice 4c met the same, and refreshed both by measurement). Run this once from the repository root, after the nine pairs, the two updates and the generated artifacts are on disk (the order does not matter to the digest; the source pairs must be). It imports the test module under its own dotted name (`tests.test_ad1152_agentic_correlation`, so that the constructor types the observation records carry the module name the golden holds: a module loaded by file path records another one), runs its `_off_observation` over a scratch directory with this tree's `src` and the repository root first on `sys.path` (it asserts that every `probos` module loaded comes from that `src`), refuses to continue unless the golden re-serialises byte for byte, belongs to the pinned base, and every key of the captured observation other than `default_config_sha256` equals the golden's, then writes the new `default_config_sha256`, asserts that the observation now equals the capture byte for byte (the test's own `_json_bytes`), recomputes `observation_sha256` and writes the file with LF endings. It changes nothing else, so it can be run again after another change has moved the default config (it prints `unchanged:` when there is nothing to do).

```python
import asyncio
import hashlib
import importlib
import json
import logging
import pathlib
import shutil
import sys
import tempfile

import pytest

ROOT = pathlib.Path.cwd().resolve()
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
GOLDEN = ROOT / "tests" / "fixtures" / "ad1152_agentic_off_golden.json"

logging.disable(logging.CRITICAL)
capture = importlib.import_module("tests.test_ad1152_agentic_correlation")
scratch = pathlib.Path(tempfile.mkdtemp())
try:
    with pytest.MonkeyPatch.context() as patch:
        actual = asyncio.run(capture._off_observation(scratch, patch))
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
assert json.dumps(golden, indent=2, ensure_ascii=True) + "\n" == before, "premise: the file re-serialises byte for byte"
assert golden["base_commit"] == capture.BASE_COMMIT, "premise: the golden is the pinned base's"
assert hashlib.sha256(capture._json_bytes(golden["observation"])).hexdigest() == golden["observation_sha256"], "premise: the stored digest is the stored observation's"
old = golden["observation"]
assert actual.keys() == old.keys(), "premise: the same observation keys"
for key in old:
    if key != "default_config_sha256":
        assert actual[key] == old[key], ("premise: only the default-config digest can differ", key)
old["default_config_sha256"] = actual["default_config_sha256"]
assert capture._json_bytes(old) == capture._json_bytes(actual), "the refreshed observation is the captured one"
golden["observation_sha256"] = hashlib.sha256(capture._json_bytes(old)).hexdigest()
after = json.dumps(golden, indent=2, ensure_ascii=True) + "\n"
GOLDEN.write_text(after, encoding="utf-8", newline="\n")
print("changed:" if after != before else "unchanged:", "default_config_sha256", old["default_config_sha256"], "observation_sha256", golden["observation_sha256"])
```

**Expected output: one line, `changed: default_config_sha256 1143f7a52db9ebe81cd85197703a227e830a4a42402bab39332f174349f8bdf8 observation_sha256 fffb4e9002e480ebdd43ffea93fda3505a5a9344d234b0dcbe1014eaf924ca32`** (measured on BF-936's head `b89ae473` with S1 and S2 applied by these blocks). After it, `git diff --numstat -- tests/fixtures/ad1152_agentic_off_golden.json` prints `2`, `2` and the path (lines 15 and 17), the file is blob `2125e8a18bebb6f9b0231c4ffcd8f8cd7654ec28`, and `tests/test_ad1152_agentic_correlation.py` passes (41 passed; before the script, on the same tree, 3 failed and 38 passed: the three tests of section 4's P2-10 bullet). Run a second time it prints `unchanged:` with the same two values and leaves the blob as it is.

#### S2 M3: tracking

**P3-1.** `PROGRESS.md`. The anchor is the title line and the blank line after it (once). Replace `DATE` with M3's date.
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**BF-937 slice 2 (DATE), #1678 -- self-improvement persistence refuses a root inside the source checkout and defaults to the data directory.**
- **Base.** `LocalDiskPersistence` wrote promoted agent source under a root that defaulted to `src/probos/agents/designed`, a relative path inside the checkout ProbOS runs from (the class, `SelfImprovementConfig`, `config/system.yaml`), so a caller would have left untracked source files outside GitHub. Nothing calls `promote` or builds an `AgentVersion` today and nothing reads the directory, so turning `self_improvement.enabled` on wired the object and never drove it.
- **Fix.** `LocalDiskPersistence` refuses a root inside the checkout (BF-897's `operator_checkout_refusal` over the checkout this module runs from) with `ValueError` when built and again, with an ERROR and no write, at every `promote`; its root is resolved when it is built and the class has no default location. `persistence_root_dir` defaults to `""`, meaning `{data_dir}/promoted-agents` (`resolve_promoted_agents_dir`). `_wire_self_improvement` builds the persistence first and on a refusal logs an ERROR and returns False before any store opens. The shipped yaml, the model docstring, `docs/development/config-reference.md`, the facade baseline and the AD-1152 golden's default-config digest follow. Contract `prompts/bf-937-legacy-self-modification-leftovers.md`, slice 2. Closes #1678.

```

**P3-2.** `DECISIONS.md`. The anchor is the last bullet of slice 1's entry, which S1 M3 appended (once at this turn; A1: S1's P3-2 lands that entry after BF-934's and BF-936's, so no re-anchor is needed). Replace `DATE` with M3's date.
SEARCH:
```
- *Residual.* L1 to L9 of the contract (S1). *Reversal.* Revert the BF-937 slice 1 commits.
```
REPLACE:
```
- *Residual.* L1 to L9 of the contract (S1). *Reversal.* Revert the BF-937 slice 1 commits.

### BF-937 slice 2 -- Self-improvement persistence refuses a root inside the source checkout (DATE, #1678)

- *Scope.* `cognitive/self_improvement/versioning.py` (`persistence_root_refusal`, `resolve_promoted_agents_dir`, `LocalDiskPersistence`), `startup/finalize.py` (`_wire_self_improvement`), `config_models/knowledge.py` (`SelfImprovementConfig.persistence_root_dir`), `config/system.yaml`, the generated config reference and facade baseline, the AD-1152 golden's default-config digest (refreshed by measurement), tests. Contract `prompts/bf-937-legacy-self-modification-leftovers.md`.
- *G1 (the rule).* BF-897's `operator_checkout_refusal` over the checkout the module runs from: anything inside it is refused, a gitignored `data/` included; an installed package has no checkout and nothing is protected. Rejected: package-directory containment, `git check-ignore`, a `.gitignore` parser.
- *G2 (where).* The constructor raises and `promote` re-checks. Rejected: a config validator (it fails every config that carries the old default, and cannot know the data directory).
- *G3 (the default).* Empty means `{data_dir}/promoted-agents`, the `resolve_records_repo_path` idiom, with the function beside the persistence so that the `probos.config` surface (counted by the facade baseline) does not grow. A config that names a `src/` root with the pipeline on is refused with an ERROR and the pipeline is not wired; it is not migrated.
- *Residual.* L1 to L10 of the contract (S2). *Reversal.* Revert the BF-937 slice 2 commits and regenerate the two artifacts (the AD-1152 digest returns with the revert of M2).
```

**Ledger.** Run G3. The roadmap Bug Tracker is not edited.

## 8. What this does NOT change

`BuildDispatcher` (`approve_and_merge`, `reject_build`, the dispatch loop) and `WorktreeManager` (`merge_to_main`, `adopt_commit`, `remove`) with BF-896's and BF-897's tests; `POST /api/build/approve`, its `APPROVE_REFUSED` text and its `build_failure` event; `/queue/reject`, `/enqueue`, `GET /queue`, `_emit_queue_snapshot`, the three queue payload dicts and `BuildQueueItem`; `BuildQueue`'s statuses and transitions; `execute_approved_build` and every guard of the build pipeline (the issue's item 4); the HXI's other Approve controls (the proposal card's, `approveBuild`), the `merged` announcement (unreachable; child 6's), `ui/src/store/types.ts`; `self_mod`'s runtime agent design and its approval, `KnowledgeStore.store_agent` and the warm-boot loader; `AgentVersionStore`, the `AgentPersistence` Protocol, `NoOpShadowDeploymentPolicy`, `AgentVersion` and `ShadowComparisonResult` (the two `wire` rows of `docs/development/dormant-class-baseline.yaml:169-172` stay as they are, as R15 of the AD-1270 contract says a guard leaves them); AD-1346's file-write census row for `versioning.py` (`promote` keeps its two `write_text` points, so `tests/fixtures/ad1346_file_write_census.py:197` and the census counts are untouched); `probos.config`'s public surface (no name is added); the other keys of `config/system.yaml`; the writers of section 12 (the native harness and its tools, `FileWriterAgent`, the shell agent, the Settings route). OSS only; no dependency; no schema change.

## 9. Mutation rows (each Line occurs once, stripped, in its file on M2's head)

The Python rows were run by hand in memory (the patched modules exec'd, the test bodies driven without pytest, the line replaced and the cases rerun: section 11); each was killed by exactly the cases named. A Builder whose files match section 7's blocks does not repeat the campaign: these are the campaign of record for the base tree `430423e1` plus slice S1 and slice S2 as written; if a file differs, rerun the rows that name it. The TypeScript rows were not run (no UI test can run in this consult): "expected".

**S1, Python (file `src/probos/routers/build.py`).**

| # | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|
| 1 | `if build is None or build.status != "reviewing":` | `if build is None:` | T1[queued] |
| 2 | `"merged": False,` | `"merged": True,` | T4 |
| 3 | `"status": QUEUE_APPROVE_UNAVAILABLE,` | `"status": "error",` | T4 |
| 4 | `answer = _queue_approve_unavailable(build)` | `answer = (await runtime.build_dispatcher.approve_and_merge(req.build_id), _queue_approve_unavailable(build))[1]` | T5 |
| 5 | `if not runtime.build_dispatcher or queue is None:` | `if queue is None:` | T2 |
| 6 | `message += f", commit {commit[:7]}"` | `message += ""` | T4 |
| 7 | `branch = result.branch_name if result is not None else ""` | `branch = ""` | T4 |
| 8 | `"""Answer the Captain's approval of a build in review: it is not merged (BF-937, #1678).` | `"""Captain approves a queued build - merge worktree to main (BF-937, #1678).` | T6 |

**S1, TypeScript (expected).**

- `ui/src/store/buildQueueApprove.ts`, ``if (typeof message === 'string' && message.trim() !== '') return message;`` to the same line ending `return QUEUE_APPROVE_NO_ANSWER;`: the helper case that returns the message, Mission Control `shows the answer`, Build Queue `adds the answer`.
- `ui/src/components/bridge/FullKanban.tsx`, ``setNote(await approveQueuedBuild(task.id));`` to ``await approveQueuedBuild(task.id);``: Mission Control `shows the answer` and `says so when the vessel gives no answer`.
- `ui/src/components/IntentSurface.tsx`, ``addChatMessage('system', await approveQueuedBuild(item.id));`` to ``await approveQueuedBuild(item.id);``: Build Queue `adds the answer` and `says so in the chat`.
- `ui/src/store/useStore.ts`, the line ``const kept = item.worktree_path ? ` Candidate branch kept in ${item.worktree_path}.` : '';`` to ``const kept = '';``: the store case `announces a build that reaches review as a candidate that is not merged, with its place`.

**S2, Python.**

| # | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|
| 1 | `src/probos/cognitive/self_improvement/versioning.py` | `if operator_checkout_refusal(root_dir, _CHECKOUT_ROOT) is None:` | `if True:` | T2 (all five), T3, T5, T9 |
| 2 | same | `_CHECKOUT_ROOT = Path(__file__).resolve().parents[4]` | `_CHECKOUT_ROOT = Path(__file__).resolve().parents[3]` | T2 (all five), T5, T9 (T3 patches the constant) |
| 3 | same | `self._root = Path(root_dir).resolve()` | `self._root = Path(root_dir)` | T4 |
| 4 | same | `refusal = persistence_root_refusal(self._root)` | `refusal = None` | T3 |
| 5 | same | `return Path(data_dir) / PROMOTED_AGENTS_DIRNAME` | `return Path(data_dir)` | T6 |
| 6 | `src/probos/startup/finalize.py` | `except ValueError as exc:` | `except KeyError as exc:` | T5 (the `ValueError` then propagates out of the wiring) |
| 7 | same | `logger.error("BF-937: self_improvement is not wired: %s", exc)` | `logger.info("BF-937: self_improvement is not wired: %s", exc)` | T5 |
| 8 | `src/probos/config_models/knowledge.py` | `default="",` | `default="src/probos/agents/designed",` | T6, T7 |
| 9 | `src/probos/cognitive/self_improvement/versioning.py` | `root_dir: str,` | `root_dir: str = "src/probos/agents/designed",` | T8 |

Not tabulated, for the cap: the sidecar and source writes (unchanged lines), the refusal text beyond `inside the checkout` and `BF-937`, and the symlink case (T10), which has not run on any account yet (its mechanism was run by hand with a junction: section 11).

## 10. Recorded limits

**S1.**

- **L1.** The route reads the queue and calls no dispatcher method, so `approve_and_merge` has no production caller (AB-2) until AD-1336 child 6 re-wires `/queue/approve` to it or replaces the queue (AD-1336's own text says the epic does not extend the in-memory queue: section 12). Its tests and BF-897's pin the contract meanwhile.
- **L2.** HTTP 200 with a non-ok `status`: a client that reads only the HTTP status sees success. Every in-repo client reads the body, and the router answers 200 everywhere (21 returns).
- **L3.** `BuildQueue._builds` is in memory: after a restart a build in review is forgotten ("not in reviewing status") though its worktree and branch stay on disk (`../ProbOS-builders/builder-<id8>`); the message is then the only record of where, and it is gone with the queue.
- **L4.** `branch` and `commit` come from the queue item's `result` (`branch_name` is set at adoption, BF-896); a build in review without a result answers the shorter message, with no place (`worktree_path` is still in the body).
- **L5.** `IntentSurface` renders a system line through Markdown, so a worktree path with Markdown punctuation may be altered in that one display, and the line scrolls out of the 30 shown; the body's `worktree_path` is exact and `FullKanban` shows plain text.
- **L6.** `FullKanban` draws Approve on every task in `review`, agent tasks included (`buildQueueToTasks` and `task_updated` share `missionControlTasks`): such a click posts a non-build id and shows "Build <id> not in reviewing status" (existing cross-wiring, unchanged).
- **L7.** No cross-language run: the shared fixture is the seam, read by both tests. The UI cases were type-checked and the helper executed in memory here; vitest and the rendering of the two components are unrun until the oracle (A1: run there, section 16).
- **L8.** The proposal card's "Approve Build" control and its "Executing build" line call `/api/build/approve`, which refuses since BF-897 (section 12): not in the issue, not changed.
- **L9 (A1).** Each of the seven cases of `tests/test_bf937_queue_approve.py` raises BF-326's `UserWarning` ("created a 'MagicMock/' directory in the repo root (auto-cleaned)"), as the six `TestDispatchAPI` cases of `tests/test_dispatch_wiring.py` do at the base: the world is `MagicMock(spec=ProbOSRuntime)` passed to `create_app`, which creates `MagicMock/mock.data_dir/<n>/silero-vad` for a runtime whose `config.data_dir` is a mock (`api.py:392`), and the BF-326 fixture removes it (the tree is clean after the run). A world that gave `runtime.config.data_dir` a `tmp_path` would end it in both files; recorded, not done (the sibling file is not this item's, and the warning is the repository's own, not a failure).

**S2.**

- **L1.** An installed package has no checkout: `operator_checkout_refusal` finds no `.git` at `parents[4]` and answers None, so nothing is protected there (nothing is tracked there either). A vendored layout whose repository root is not `parents[4]` is not protected.
- **L2.** The rule refuses more than "tracked": any directory inside the checkout, a gitignored `data/` included. A data directory inside the checkout (`PROBOS_DATA_DIR` or a `--data-dir` under it) makes the default root refused, with the message naming the way out. Loosening it needs git or a `.gitignore` parser (D7).
- **L3.** A linked worktree nested inside the checkout has its own `.git` entry and is allowed; the rule compares locations, not the repository a `.git` entry names (BF-897's recorded limit, #1523).
- **L4.** `promote` has no production caller and nothing reads what it writes (AB-3, AB-4), so with the pipeline on nothing changes today: the boundary is for the wiring and for AD-482h-1's caller.
- **L5.** The check and the write are not atomic: a link swapped in between `persistence_root_refusal` and `mkdir` is not caught (the second check narrows the window; a local attacker with write access to the data directory is outside the threat model of this item).
- **L6.** A config that names a `src/` root with `enabled: true` no longer wires the pipeline (an ERROR in the boot log, the vessel boots); with `enabled: false` nothing changes.
- **L7.** A junction is followed by `Path.resolve()` on Python 3.12 (BF-897's helper relies on it): checked by hand in this consult (a junction into `src`: a root reached through it was accepted on the base and refused on the head); no case in the test file makes one (it needs `mklink /J`). The symlink case (T10) skips where a link cannot be made, as on the account that ran this consult.
- **L8.** The other writers of section 12 are not covered; the native harness is the one that matters.
- **L9.** `~` is not expanded: `persistence_root_dir: ~/x` is a relative path named `~`, read from the current directory (guarded if that is the checkout).
- **L10 (A1).** The AD-1152 golden pins a hash of the whole default `SystemConfig()` dump, so every change to a default (or a new field that its test does not pop) makes `test_default_off_matches_pinned_base` fail until P2-10's refresh is run again (BF-926, AD-1270 slice 4c and BF-937 all met it; the broad gate is what caught them). A test that pins the default-OFF wire shape without hashing the whole config would end that class of failure; it changes AD-1152's oracle, so it is recorded, not done here.

## 11. Verified Against Codebase (2026-11-12, reading tree `D:\ProbOS-worktrees\bf936-base` at `430423e1`)

**Run by the Architect, read-only (CPython 3.12.13 and Node v24.14.0, win32; scripts piped on stdin, nothing written but scratch temporary directories under `%TEMP%`, created and removed by the S2 runs and by the junction check (the junction removed with `os.rmdir`, never its target); `-B`; no pytest and no vitest):**

```
git rev-parse HEAD and origin/main -> both 430423e14ac140f4cb8e37deffa233c9e49f730f (PR #1784's merge); git status of the reading tree: 0 entries after the runs; no __pycache__ in it; %TEMP%\bf937-consult-nodata (the PROBOS_DATA_DIR the runs named) does not exist
every block of section 7 applied in label order to the LF blobs (git show HEAD:<path>): 35 blocks; each SEARCH occurs once at its turn, starts at a line start; ASCII but S1 P2-3 (one U+2014); every .py result parses
the TypeScript compiler API (typescript 5.9.3 from D:\ProbOS\ui\node_modules; the compiler options of ui/tsconfig.json; all 641 tracked ui/src .ts and .tsx files as roots, 2334 source files in the program; an in-memory overlay of the patched and new files; bare imports resolved against D:\ProbOS\ui\node_modules): the unpatched tree 0 diagnostics (so the host is faithful: the existing tests, many of them with global.fetch, type-check); M1 (the new test and fixture only, the helper absent) 0; head (every S1 block) 0
S1: the patched routers/build.py substituted for probos.routers.build by a meta-path finder (the real app: create_app, TestClient, a real BuildQueue and BuildDispatcher over a recording WorktreeManager double); the 7 test bodies of N1-1 driven by hand, and the six TestDispatchAPI cases of tests/test_dispatch_wiring.py. Base: the 4 functions pass; T4 fails at 'assert resp.json() == json.loads(...)', T5 at 'assert_not_awaited' (Awaited 1 times), T6 at the first description assert; the six wiring cases pass. Head: all 7 pass, T4 against the fixture text of N1-2, and the six wiring cases pass, the updated test_approve_queued_build included
S2: the patched versioning.py, knowledge.py and finalize.py substituted for their modules by the same finder (so probos.config builds its models from the patched knowledge.py), the 14 test bodies driven by hand (tmp_path = mkdtemp, chdir and module attributes restored by a pytest.MonkeyPatch, caplog replaced by a small shim, the read of config/system.yaml answered with the patched text). Base: the control passes; T2 x5, T3 (at its hasattr premise), T4, T5, T6, T7, T8, T9 fail at their own assert; T10 skipped (this account cannot create a symlink). Head: 13 pass, T10 skipped
the 17 Python mutants of section 9, rerun on the final text, each in a fresh process: killed by exactly the cases named there (S2 row 6: by the ValueError that then propagates out of T5)
a directory junction into src (mklink /J in a scratch directory, removed with os.rmdir): LocalDiskPersistence(root_dir=<junction>/promoted) is accepted on the base and refused on the head ("... is inside the checkout ..."); this is the mechanism of T10, not the case
Node: the transpiled buildQueueApprove.ts (module CommonJS, a vm context, a fake fetch): queueApproveMessage over the 10 inputs of the helper case and approveQueuedBuild for an answer, a failed request and an unreadable body; the store line built from the template of P2-11 for the fixture's worktree path
```

**Facts read (path:line on `430423e1`):** `routers/build.py:193-205` (the route; `:198` holds U+2014; `:201` the call), `:29-33` (`_REPO_ROOT`, `APPROVE_REFUSED`), `:67-95` (`/approve`: warning, `build_failure` with `not_executed`), the 21 returns of the file all `{"status": ...}` with no `status_code`, `HTTPException` or `JSONResponse` (`Grep` over the file); `build_dispatcher.py:396-421`; `worktree_manager.py:153-175`; `build_queue.py:21-26` (`reviewing` goes to `merged` or `failed`), `QueuedBuild` fields; `watch_rotation.py:243` (`not_executed is True`); `startup/structural_services.py:118-133` (the dispatcher built and started with no gate); `ui/src/components/IntentSurface.tsx:98` (`addChatMessage`), `:1963-2121` (the Build Queue panel inside the open shell, not inside the thread), `:2061-2069` (the Approve click); `ui/src/components/bridge/FullKanban.tsx:72-80`; `ui/src/store/useStore.ts:3809-3829` (`build_failure`; `:3810` clears `buildProgress`), `:3841-3883` (`build_queue_item`; `:3870-3872` the `reviewing` line); `ui/src/App.tsx:112-114` (both components mounted together); `ui/package.json` (`test` = `vitest run`, `build` = `tsc -b && vite build`), `ui/vitest.config.ts` (jsdom, `globals`, `src/test/setup.ts`), `.github/workflows/ci.yml:122-163` (`ui-tests`: `npm ci`, `npm run test`, `npm run build`), vitest 4.1.0 in the main checkout (`fails` in `@vitest/runner` typings); `tests/test_dispatch_wiring.py:22`, `:114-122`, `:133-145`; `versioning.py:104-165` (`compute_source_hash`, the class), `:111-127`; `startup/finalize.py:2608` (`_wire_self_improvement`), `:2626-2630` (the `enabled` gate), `:2741`, `:2750`, `:6039-6045` (the wrapping call); `config_models/knowledge.py:460-473`; `config/system.yaml:1993-1999`; `config.py:2658` (`resolve_records_repo_path`), `:2631` (`resolve_archive_db_path`); `startup/cognitive_services.py:545-548` (`data_dir / "knowledge"`); `runtime.py:238` (`_platform_data_dir`, `PROBOS_DATA_DIR`), `:2238` (`data_dir`); `cognitive/builder_paths.py:723-756` (`operator_checkout_refusal`: no `.git` at the root answers None `:745`; `samefile` `:749`); `cognitive/builder.py:50` (`_PROJECT_ROOT`), `:3301` (its use); `.gitignore:27` (`data/*`) with `git check-ignore -v data/x src/probos/agents/designed/x_v1.py` printing only `.gitignore:27:data/*	data/x`; `tests/test_ad1270e1_config_facade.py:1515-1577` (the pinned public-name counts); `tests/test_ad1270e2f_knowledge_models.py:252-257`, `:428-452`, `:479`, `:486-541` (five bounded fields: unchanged by a `Field` without bounds); `tests/fixtures/ad1346_file_write_census.py:197` and `tests/test_ad1346_admission_file_write_census.py` WF1 and WF7; `scripts/run_test_gate.py:1085-1125` (the preflight: import origin, config reference, profiles, facade, ledger, seam contracts, architecture, store registry; no UI step).

**Absence Verified (2026-11-12)**

```
CLAIM: BF-937 is held only by #1678; the highest AD is AD-1359 and the highest BF is BF-961
RUN:   git log --all --format=%s, count of subjects naming BF-937; prompts/bf-937* in each of the 126 worktrees of git worktree list; gh issue list --state all --search "BF-937 in:title"; gh pr list --state all --search "BF-937"; git branch -a --list "*937*"; git grep -n BF-937 HEAD; docs/development/roadmap*.md; the highest BF in git subjects, in 1517 issue titles and in 6581 prompts/bf-*.md files across the worktrees; scripts/ad_ceiling.py
FOUND: 0 subjects (one commit BODY, d61025bf, names BF-937 as a relation of AD-1270's register R15); 0 prompts; #1678 only (OPEN, bug); no pull request; no branch; 2 tree hits (docs/development/deterministic-ship.md:54, prompts/ad-1270-dormant-class-check.md:1426, both references to this issue) and none in roadmap*.md; BF-961 in subjects, in issue titles and in prompt filenames (the roadmap.md Bug Tracker stops at BF-927); ad_ceiling.py: AD-1359 from all three sources, next AD-1360
HOLDS: yes (nothing new is allocated)

CLAIM: approve_and_merge has one production caller, the route
RUN:   git grep -n -E "approve_and_merge" HEAD -- src ui scripts
FOUND: src/probos/build_dispatcher.py:396 (the definition), src/probos/routers/build.py:201 (the call); tests: test_build_dispatcher.py, test_bf896_dispatcher_confinement_seam.py:741, test_dispatch_wiring.py:22,114-122
HOLDS: yes

CLAIM: nothing in src calls LocalDiskPersistence.promote or builds an AgentVersion, and nothing reads runtime.agent_persistence
RUN:   git grep -n -E "\.promote\(|AgentVersion\(|agent_persistence" HEAD -- src
FOUND: runtime.py:569 and :1336 (the attribute), finalize.py:2618 (a docstring), :2741 and :2750 (the construction and the assignment); no .promote( and no AgentVersion( anywhere in src
HOLDS: yes (tests/test_ad1346_admission_file_write_census.py WF7 says the same of AgentVersion)

CLAIM: nothing imports, loads or discovers src/probos/agents/designed or the versioned files
RUN:   git grep -n -E "agents[./]designed|designed_dir" HEAD -- src tests scripts config pyproject.toml MANIFEST.in; git ls-files src/probos/agents/designed; Test-Path src/probos/agents/designed; git grep -n -E "meta\.yaml|_v\{|_v\*|glob\([^)]*_v" HEAD -- src; git grep -n -E "iter_modules|walk_packages|pkgutil" HEAD -- src
FOUND: the default and docstrings (config/system.yaml:1999; versioning.py:10,116,123; knowledge.py:465,473) and the pin tests/test_ad1270e2f_knowledge_models.py:257; 0 tracked files; the directory does not exist; the versioned-file hits are the writer itself and consultation/ plan_v{N}.md (another feature); two pkgutil mentions in maturity/registry.py and storage/registry.py, which walk modules and do not name this directory
HOLDS: yes

CLAIM: no UI test names FullKanban, the two queue routes or the "Build ready for review" line, and no ?raw test reads the three edited TypeScript files
RUN:   git grep -n -E "FullKanban|queue/approve|queue/reject|Build ready for review" HEAD -- ui/src ui/e2e; git grep -n -E "(IntentSurface|FullKanban|useStore)(\.tsx?)?\?raw" HEAD -- ui/src
FOUND: App.tsx:8,112; IntentSurface.tsx:2063,2086; FullKanban.tsx:74,93,114; useStore.ts:3872; nothing under __tests__ or e2e; no ?raw import of the three files
HOLDS: yes

CLAIM: the tests that touch the route, the dispatcher or the queue are the files of S1's G2; the tests that touch the persistence, its config or the wiring are the files of S2's G2
RUN:   git grep -l -E "api/build|routers\.build|routers/build" HEAD -- tests; git grep -l -E "build_dispatcher|BuildDispatcher|BuildQueue|build_queue" HEAD -- tests; git grep -n -E "persistence_root_dir|agents/designed|LocalDiskPersistence|_wire_self_improvement|SelfImprovementConfig\(" HEAD -- tests
FOUND: the 11 files of the first list (ad1270_night_orders_recall, ad1346_admission_build_test_sink, ad1346_admission_service, ad521_swe_pipeline_separation, architect_agent, bf896_executor_identity_and_blocks, bf897, bf904a, bf904b_sealed_core_observation, builder_api, dispatch_wiring) plus bf896_dispatcher_confinement_seam, bf904b_dispatch_and_visiting, build_dispatcher, build_queue; for S2: test_ad1270e2f_knowledge_models.py:257, test_ad482_self_improvement.py (:447, :1485-1632, :1563), test_bf859_qa_pool_awaits_spawn.py:78, all with tmp_path roots but the one pin
HOLDS: yes for the files that name the persistence by text; **NOT for the files that hash the default config (A1, 2026-11-13).** The search looked for the field's name and the class, and `tests/test_ad1152_agentic_correlation.py` hashes the whole default `SystemConfig()` dump without naming either; `tests/fixtures/ad1152_agentic_off_golden.json:15, :17` goes stale with the new default, and three tests fail until P2-10 refreshes it (the first reading of BF-936's contract had met the same class: its L11 names this item as the other mover of that digest). `git grep -l -E "default_config_sha256|config_sha256|canonical_dump_sha256|schema_sha256" -- tests docs scripts src config` lists the golden, its test, `tests/test_ad1270e1_config_facade.py` (the baseline, regenerated) and `tests/trials` (an unrelated field name)

CLAIM: no baseline, seam catalog or architecture row names a symbol this item renames or removes
RUN:   git grep -n -E "approve_and_merge|merge_to_main|approve_queued_build|LocalDiskPersistence|_wire_self_improvement|persistence_root|build_dispatcher|self_improvement|routers\.build" HEAD -- docs/development/seams docs/development/dormant-class-baseline.yaml docs/development/architecture-baseline.yaml
FOUND: architecture-baseline.yaml:616 (EvolutionStore), dormant-class-baseline.yaml:166,169,172 (StageContract, AgentVersion, ShadowComparisonResult); none is renamed or removed; no new class is added (the dormant-class scan ignores functions)
HOLDS: yes
```

## 12. Prior Art and Blind Spots

- **Internal prior art, adopted.** BF-897 (`operator_checkout_refusal` as the one predicate for "the checkout ProbOS runs from"; `/approve`'s refusal as the precedent for a typed answer; `not_executed`; the contract's HXI reads); BF-896 (the adoption that sets `result.branch_name`); `resolve_records_repo_path` (empty means a path under the data directory, one function); the shared-fixture pattern (`ui/e2e/fixtures/*.json` read by a backend test and a UI test, e.g. `tests/test_ad1207_fault_visibility.py:801`); AD-1346's census (WF7, the same absence); R15 of `prompts/ad-1270-dormant-class-check.md` (it names this item: a guard keeps the two `wire` rows); AD-1336 (children 5 and 6, and its note that its delivery state lives in AD-1299's records and it does not extend the in-memory queue). **Rejected:** section 3. **External:** none consulted.
- **Every other path that writes under `src/` or merges outside GitHub (enumerated by command, so that this is not the first of a series of one).**
  - *Git verbs that move a ref or a tree (two commands, both run on `430423e1`).* (1) `rg -n "[\"'](merge|checkout|rebase|reset|cherry-pick|push|pull|fetch|commit|stash)[\"']\s*[,\]\)]" src/probos` finds, as git arguments, `cognitive/builder.py:1678` (`checkout -b`), `:1693` (`commit`), `:1711` and `:1713` (`checkout`), `:3854` (`reset`); `worktree_manager.py:199` (`checkout`) and `:203` (`merge --ff-only`); and `commit` in `__main__.py:3189`, `knowledge/store.py:1210`, `:1248` and `knowledge/records_store.py:730`, `:2024`; its other hits are not git arguments (a CLI and lifecycle name `reset`, the HTTP agent's `fetch` action, keyword lists). (2) `rg -n "[\"']git[\"']\s*[,\]]|_run_git\(|_cleanup_git\(|_git_run\(|self\._git\(" src/probos` lists every site that starts git: `__main__.py:3184` and `:3189` (`add -A` and `commit` in the knowledge repository during `probos reset`); `worktree_manager.py` (`_run_git` `:49`; `worktree add`, `branch -D`, `checkout`, `merge --ff-only` at `:91-214`); `cognitive/builder.py` (`_run_git` `:1597`, `_cleanup_git` `:1725`; `checkout -b` `:1678`, `add` `:1689`, `commit` `:1693`, `checkout` `:1717`, `reset` `:3854`, `branch -D` `:3873`); `knowledge/store.py` (`_git_run` `:1340`) and `knowledge/records_store.py` (`_git` `:1917`), both on data-directory repositories; and the read-only `execution/authority.py:793` (`rev-parse`, `ls-files`), `doctor/checks/records_git_check.py:45`, `cognitive/referent_gate.py:470` (`cat-file`), `builder.py:3064` and `:3078` (`rev-parse`, `status`). The shell agent allowlists `git` (`agents/shell_command.py:151`; a general writer, below). No `push`, `pull`, `fetch`, `rebase` or `cherry-pick` runs. The builder runs in a build's work directory and refuses the operator's checkout (`builder.py:3301`); the worktree manager runs in a linked worktree (`cwd=info.path`); the other commits go to the knowledge and records repositories under the data directory. The one `merge` is `worktree_manager.py:203`, a fast-forward inside a linked worktree: nothing merges into the checkout's `main` outside the route this item makes honest.
  - *A repository-relative root in config:* `rg -n extensions_dir src` finds only the field (`config_models/agentic.py:137`, default `src/probos/extensions`): no reader, so not a writer. `config.py:3166` is a deny list; `FIX_LOOP_WRITABLE_ROOT` (`builder_paths.py:551`) is an allowlist inside a build's worktree.
  - ***The native SWE harness (default off) is the real sibling of this defect.*** With `native_swe_harness.enabled` (`config/system.yaml:902-912`, shipped `false`), `BuilderAgent.perceive` passes `work_dir=str(_PROJECT_ROOT)`, the running checkout, to `NativeBuilderHarness.run_build` (`cognitive/builder.py:2553-2580`; `_PROJECT_ROOT` is `builder.py:50`); the harness's `write_file` and `edit_file` tools resolve a relative path against `_PROJECT_ROOT` (`swe_harness/tools.py:247-250`) and refuse only the Constitution (AD-1344), the Captain's documents (BF-943), the protected config (BF-911) and `blocked_paths` (`config.py:3164-3170`: `src/probos/security/`, `.env`, `config/sealed_modules.yaml`); `run_build` carries no `operator_checkout_refusal` (`rg -n "operator_checkout|checkout" cognitive/swe_harness/native_builder.py` finds nothing). A build it runs therefore writes into the live checkout's `src/`, outside GitHub. This item does not touch it (a different surface, an agentic tool loop, and outside #1678's acceptance): see "for the Captain".
  - *The same two tools:* `register_native_swe_tools` registers them unconditionally (`startup/finalize.py:1873-1880`, "Tool registration is unconditional"); an agent that holds a `write_file` grant reaches them; the grant path was not traced.
  - *Self-modification:* `cognitive/self_mod.py:590-612` compiles into a temporary file and deletes it; designed agents persist through `KnowledgeStore.store_agent` (`knowledge/store.py:258-262`, `{repo_path}/agents/{agent_type}.py`, `repo_path` defaulting to `{data_dir}/knowledge`, `cognitive_services.py:545-548`) and come back through `WarmBootService.restore` (`cognitive_services.py:554-570`): the data directory, with the Captain's approval. *The designed-agent loader for `src/probos/agents/designed`:* none (AB-4).
  - *General writers under their own policies, not traced:* `FileWriterAgent.commit_write` (`agents/file_writer.py:146-164`, after a consensus vote), `ShellCommandAgent` (`run_command`, `requires_consensus=True`, the AD-1328 command policy), `routers/config.py:149-155` (the Settings page rewrites the loaded config with `os.replace`, an operator's own edit).
- **Blind spots handled.** The issue's "turning it on would write" is false today (nothing calls `promote`): found by enumeration, so S2 is a boundary for the wiring and for the caller AD-482h-1 will add; a config validator would have broken boot for every config that carries the old default, `enabled` or not; a new `probos.config` function would have moved the facade baseline's pinned public-name counts; the default must not land inside the checkout, and when the data directory does, the refusal names the way out; a relative root is pinned when built, so a later `chdir` cannot move the write; case, 8.3 names and links are the predicate's, with a case test and a link test; the old test pinned a merge the real chain cannot make and its stub is now a tripwire; the Mission Control Approve is also drawn on non-build tasks (S1 L6); the queue is in memory (S1 L3).
- **What discards a correct result.** The approve answer: a build in review whose `result` is missing answers without a branch (S1 L4); the helper drops a body whose `message` is blank or not a string and shows the fixed line; Markdown may alter a path in the chat (S1 L5). The persistence: a correct root refused only for a data directory inside the checkout (S2 L2) or an unexaminable path (fail closed); an allowed root writes exactly as before. **Recorded:** S1 L1 to L9 and S2 L1 to L10.

## Batching

**A1 (2026-11-13): the order below is not followed. BF-936 lands first, as its own pull request with its own broad gate (its gate and review were complete before this contract's blocks were measured over BF-936's head, and BF-936's own contract recommended separate pull requests, BF-936 first); BF-937's two slices are one batch, one broad gate, one pull request (section 16).** The Architect's analysis follows, for the record:

**Yes: one broad gate and one pull request with BF-936 (#1677); BF-937 first.**

| Point | Judgement |
|---|---|
| Files | Disjoint. BF-936 changes `config/standing_orders/*.md` and the standing-orders tests; BF-937 changes the build router, three TypeScript files and a helper, `versioning.py`, `finalize.py`, one config model and yaml, and two generated artifacts. Only the tracker pairs (PROGRESS, DECISIONS, the ledger pair) collide: re-anchor them, as stated in P3-1 and P3-2 |
| Why together | They are two halves of one statement: BF-936's text says a build the Captain dispatches is a candidate branch that is not merged until the GitHub delivery route exists; S1 makes the Approve control say the same. Shipped apart, BF-936's text stands beside a control that does nothing visible, which is the contradiction #1678 names |
| Order | BF-937 S1, then S2, then BF-936: BF-936's wording cites a state the UI and the persistence then show truly. If only one can land first it is S1. S2 is independent of BF-936's claim; it goes before BF-936 only so that the two BF-937 slices stay contiguous, and last of the BF-937 pair because it regenerates two generated artifacts, which keeps its conflict window short |
| Revert | Separate commits per milestone and per slice; each slice and BF-936 revert alone |
| Cost: Python | S1 and S2 focused commands (section 4); one broad gate: `PY scripts/run_test_gate.py --label bf937 --receipt logs/gates/bf937.receipt.json` (A1: the label; its preflight runs the three config checks, the ledger, the seam, architecture and store checks; **it does not run the UI tests or the UI build**) |
| Cost: UI | S1's focused vitest command and `npm run build` (section 4, G2); CI's `ui-tests` (`npm ci`, `npm run test`, `npm run build`) runs the whole suite on the pull request |
| Cost: config | S2's two regeneration commands, three `--check` commands and P2-10; the diff to look at is one row in the reference, four lines in the baseline (A1) and two lines in the AD-1152 golden |

## Not in this issue: for the Captain

Each item is an operation on, or a measurement of, the running vessel. The build does not do it and neither does this contract.

1. **The issue's live-log claim.** Action: on the live vessel, search its log for `build-dispatcher started` (`Select-String -Path <the live vessel's log> -Pattern "build-dispatcher started"`). Source of truth: the live log. Pass: one line per boot (the code shows no gate: `startup/structural_services.py:118-133`; the date in the issue, 2026-10-25 19:22:08, is the issue's).
2. **The live config after the merge.** Action: before the first restart on the new build, print `self_improvement.enabled` and `self_improvement.persistence_root_dir` from the config the vessel loads (the checkout's `config/system.yaml`, or an override). Source of truth: that file. Pass: `enabled: false` and the root empty or outside the checkout. A live config that still names a `src/` root with `enabled: true` shows `BF-937: self_improvement is not wired` at ERROR in the next boot log: a signal to change the value, not a failure of this item.
3. **The Approve control with a real build in review.** Action: dispatch a small build from the HXI (`/api/build/enqueue`), wait for `reviewing`, click Approve in the Build Queue panel and in Mission Control. It spends model usage and creates a branch and a worktree in the live repository, so it is the Captain's. Source of truth: the HXI chat line and the card note, `GET /api/build/queue`, `git worktree list`. Pass: both show the answer of section 2 naming the branch and the worktree; the build stays in review; Reject then discards the worktree and the branch.
4. **Candidates earlier builds left.** Action: `git worktree list` and `git branch --list "builder-*"` in the live checkout. Source of truth: git. Pass: none required; a branch listed there is an unmerged candidate that only its worktree holds, and the queue no longer remembers it (S1 L3).

**Decisions that need the Captain** (recommendations, not made here):

| # | Decision required | Recommendation |
|---|---|---|
| 1 | **The native SWE harness writes into the live checkout** (section 12). Is `native_swe_harness.enabled: true` meant to patch the running checkout in place, or must it be confined to a linked worktree until AD-1336 child 5? | Confined, failing closed: file a BF (the number comes from the ceiling check, not from this contract) that refuses an in-checkout `work_dir` in `NativeBuilderHarness.run_build` with `operator_checkout_refusal`, as `execute_approved_build` does (`builder.py:3301`). It needs the Captain because it decides whether a self-patch mode exists at all |
| 2 | The proposal card's "Approve Build" control and its "Executing build: <title>..." line (`IntentSurface.tsx:921-938`, `:1419-1431`) call `/api/build/approve`, which only refuses since BF-897. Include it in this PR? | A separate follow-up of S1's shape (show the refusal where it is; drop "Executing build"); not in #1678's list, and it would add a component to S1 |
| 3 | Is "inside the checkout" (a gitignored `data/` included) the intended reading of "the repository's tracked source tree" (S2 L2)? | Yes, for now: fail closed and explainable; allow a gitignored in-checkout location only with a git-based rule if the Captain wants one |
| 4 | AD-1336's text says its epic does not extend the in-memory queue, while BF-897 and the issue say children 5 and 6 reuse it. Does `approve_and_merge` get re-wired by child 6, or does the queue's approve retire? | None needed now: S1 keeps the seam either way. If the queue retires, the route, `approve_and_merge` and their tests become removable at that point |

## 13. Diff Reviewer: properties to verify

**S1.**

1. `approve_queued_build` returns before any dispatcher method for a running dispatcher and a build in review: the typed body, HTTP 200, no `emit_event`, no git; a dispatcher that is not running and a build that is not in review answer byte-for-byte as before (T1, T2). `approve_and_merge`, `merge_to_main` and `reject_build` are unchanged.
2. The route's docstring, and so its OpenAPI description (what a client reads), no longer says "merge worktree to main" (T6).
3. `buildQueueApprove.ts`: `approveQueuedBuild` never rejects; the request is `POST`, JSON `{build_id}`, as before; the line returned is the body's `message` or the fixed text.
4. `IntentSurface.tsx` and `FullKanban.tsx`: the Reject clicks are untouched; each Approve click shows what the helper returns and nothing is discarded (no `catch { /* ignore */ }` left on Approve); `note` is per card.
5. `useStore.ts`: only the `reviewing` line changed (the lines for `building`, `merged` and `failed` are byte-identical).
6. `tests/test_dispatch_wiring.py`: the stub is a tripwire, `test_approve_not_running` is untouched, no other case changed.
7. M1: the Python file collects without importing a BF-937 name and the three class cases fail at their own `assert`; the UI file loads and type-checks on the unfixed tree (the helper is imported by a variable path) and its seven `built` cases fail at their own `expect` or `findBy*` (`BF937_RUNXFAIL=1`); N2-3 and N2-4 remove the markers only.
8. The fixture equals the route's body for the test's build (T4) and is the file the UI test reads; the message names the branch, the commit and the worktree.

**S2.**

1. `persistence_root_refusal` is `operator_checkout_refusal(root_dir, _CHECKOUT_ROOT)` and nothing else decides; `_CHECKOUT_ROOT` is the repository root (`parents[4]` of `versioning.py`); the text names the path, the checkout and the way out.
2. `LocalDiskPersistence`: `root_dir` is required; the constructor raises `ValueError` on a refusal and stores the resolved path; `promote` re-checks before `mkdir`, logs an ERROR and returns `""`; its two `write_text` calls and the sidecar are unchanged (AD-1346's census).
3. `resolve_promoted_agents_dir` answers `Path(root_dir)` or `{data_dir}/promoted-agents`; no name is added to `probos.config`.
4. `_wire_self_improvement` builds the persistence before `EvolutionStore`; a `ValueError` logs an ERROR and returns False with nothing opened or attached; the late construction is gone; the disabled path and the other stages are unchanged; `cfg.persistence_root_dir` is read by name there (the BF-926 reader check).
5. The model default is `""` with a description; the docstring no longer names `src/`; the yaml value and comment; the regenerated artifacts differ from the base in exactly the lines section 4 names (A1: the reference one row, the baseline four lines).
6. `tests/test_ad1270e2f_knowledge_models.py`: only the one pin changed.
7. M1: the file collects on the unfixed tree, imports no BF-937 name at the top, and the 13 class cases fail at their own `assert` (T3 at its `hasattr` premise); N2-2 removes the marker only.
8. (A1) The AD-1152 golden differs from the base in exactly two lines, 15 (`observation_sha256`) and 17 (`observation.default_config_sha256`); no other key of the observation moves; `tests/test_ad1152_agentic_correlation.py` passes; the P2-10 script, run again on the head, prints `unchanged:` and changes nothing (check what it does with a difference in any other key, on a throwaway copy).

## 14. Acceptance criteria

- G1, G2 and G3 of each slice pass as stated, and the batch's broad gate is green with a receipt; the UI evidence is S1's G2 UI commands and CI's `ui-tests`.
- **Honest approve (issue item 1).** `POST /api/build/queue/approve` answers HTTP 200 `status: "unavailable"` for a build in review and runs no git operation (T4, T5); its docstring no longer says "merge worktree to main" (T6); both call sites show the answer (U-cases); the announcement of a build in review and the approve answer say where the candidate branch is kept and that it is not merged, and the approve answer says what BF-936's standing orders say (a candidate, not merged until the GitHub delivery route exists).
- **No source writes under `src/` (item 2).** Persistence refuses a root inside the checkout at construction, at the wiring and at each write (S2 T2, T3, T5); the default is `{data_dir}/promoted-agents` (S2 T6, T7, T8); the generated reference, the facade baseline and the AD-1152 golden's default-config digest are refreshed by measurement (A1).
- **Tests (item 3).** The approve route's typed result with no git operation (S1 T4, T5); persistence on with a `src/` root refused (S2 T2, T5); the allowed location still works (S2 T1, T6).
- **Unchanged (item 4).** BF-897's refusal (`approve_and_merge`, `merge_to_main` and their tests), `self_mod`'s runtime agent design, the build pipeline.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 16. Amendment A1 (2026-11-13): the tracker anchor, the facade baseline's four lines and the AD-1152 default digest

**Drafted by:** the orchestrator, not the Architect: each change below is fixed by a measurement or by a precedent in the repository (BF-926's A1, `6f94608b`; AD-1270 slice 4c M1, `ebd57eb8`), so it is mechanical. The Diff Reviewer's first brief names this section as the first thing to verify.

**What was run.** The Architect's consult ran no test (Status), and BF-934 and BF-936 merged after it read `430423e1`. The orchestrator applied the 35 blocks (30 pairs and 5 new files) in label order to BF-936's head `b89ae473` (tree `88d43e8c7767f4d105ef09ccc891d576d54e11df`, which is also the tree of BF-936's merge `54a112e2`), committed them as the milestones of a scratch chain, and ran on it the gates of section 4, the mutation rows of section 9 and two wide consumer runs. Every SEARCH occurs exactly once, and the header's base blobs are equal at that head except `PROGRESS.md` and `DECISIONS.md`. Three things the text did not say came out of running, not of reading:

1. **S1's DECISIONS anchor.** BF-934 and BF-936 each inserted their entries after BF-935's and before the heading `### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)`. P3-2 anchored on the last line of BF-935's entry, which put slice 1's entry ahead of both; the file stays in the order the changes landed, and the Architect's own note said to re-anchor after their merges. P3-2 now inserts before that heading (it occurs once at the head, and BF-936's P3-2 did the same), so slice 1's entry lands after BF-936's. S2's P3-2 anchors on slice 1's last bullet and needed no change.
2. **The facade baseline moves four lines, not two.** Measured at S2 M2: `canonical_dump_sha256`, the `SelfImprovementConfig` block's `schema_sha256` and its `persistence_root_dir` default line, and the `SystemConfig` block's `schema_sha256` (the parent's schema embeds the child's default); the reference moves one row. Section 4 said two lines and made any other changed line a hard stop, which would have stopped a correct build.
3. **The AD-1152 golden goes stale, and S2's G2 did not name its test.** `tests/fixtures/ad1152_agentic_off_golden.json` pins the SHA-256 of the default `SystemConfig()` dump (`observation.default_config_sha256`, line 17) and of the whole observation (`observation_sha256`, line 15); the new default of `self_improvement.persistence_root_dir` moves the first and so the second. On S2's M2 head `tests/test_ad1152_agentic_correlation.py` had 3 failed and 38 passed (`test_default_off_matches_pinned_base` and `test_default_off_golden_pins_only_descriptor_owner_platform[linux]` and `[win32]`). The first reading searched for the field's name and the class, not for a hash of the whole dump (L10; the claim in section 11 about which tests touch the persistence is amended). BF-936's M2 refreshed the same two lines for its own change, so the golden at the head is blob `5ba9ea5c6ba88b7fa4a937ec40289e94033b10ea`; whichever of the two items merges second re-measures, which is what P2-10 (new) does.

**Measured on the scratch chain** (nothing in this section was measured on the real tree):
- **P2-10.** On S2 M2's tree it printed the one line `changed: default_config_sha256 1143f7a52db9ebe81cd85197703a227e830a4a42402bab39332f174349f8bdf8 observation_sha256 fffb4e9002e480ebdd43ffea93fda3505a5a9344d234b0dcbe1014eaf924ca32`; `git diff --numstat` for the file `2`, `2` (lines 15 and 17); blob `2125e8a18bebb6f9b0231c4ffcd8f8cd7654ec28`; `tests/test_ad1152_agentic_correlation.py` 41 passed (3 failed, 38 passed before it). Run again it printed `unchanged:` with the same two values. On a throwaway copy whose `observation.persisted` request prompt was changed and whose `observation_sha256` was recomputed to match, it stopped at `AssertionError: ('premise: only the default-config digest can differ', 'persisted')` and left the file byte for byte as it was. Its LF write turns a CRLF working copy into LF; the blob is identical (the file is `text: unspecified` and `core.autocrlf` is true on this host), so `git status` may show the file modified before the commit and nothing after it.
- **S1.** M0: 459 tests over 15 files at the base, 466 over 16 at M3 (the 15 existing files' counts equal). G1 at M1: 4 passed, 3 xfailed; with `--runxfail`: 3 failed at their own asserts and 4 passed. UI G1 at M1: `4 passed | 7 expected fail (11)`; with `BF937_RUNXFAIL=1`: 7 failed and 4 passed, at the places section 4 names. G2 at M3: the Python files 464 passed, 2 skipped (466 collected), and the same with the new file last and first in suite order; the architecture check clean; the UI files 21 passed (243 tests) and `npm run build` clean, the tree clean afterwards. The 14 warnings are 13 of BF-326's `MagicMock/` notice, 7 from the new file and 6 from the six cases of `tests/test_dispatch_wiring.py` that raise it at the base (L9), and one `importlib_metadata` deprecation notice. G3: ledger current, 33 passed. The eight Python mutation rows of section 9 each fail exactly the case the row names (8 of 8). The wide run, the 5 test files outside G2 that name `BuildDispatcher`, `build_dispatcher`, `WorktreeManager`, `worktree_manager`, `queue/approve`, `approve_queued_build`, `approve_and_merge` or `merge_to_main`: **600 passed, 2 skipped, 0 failed**.
- **S2.** M0: 521 tests collected at the base, 535 at M3 (+14, the existing files' counts equal). G1 at M1: 1 passed, 1 skipped (T10: this account cannot create a symbolic link), 12 xfailed; with `--runxfail`: 12 failed at their own asserts. G2 at M3: 534 passed, 1 skipped, and the same with the new file last and first in suite order; the four checks clean (architecture: `srp-size=92, layer-import=0, db-connect=30, unowned-task=13`; the reference current; the facade check passed; the profile check passed); G3: ledger current, 33 passed. The nine Python mutation rows of section 9 each fail exactly the cases the row names (9 of 9). The wide run, 73 test files outside G2 that a by-name search found to read the default configuration, the generated config surfaces or the source tree (the AD-1270 config-model, architecture and census tests among them): **5,541 passed, 7 skipped, 0 failed**. The selection is by name, so the broad gate is what covers the rest.

**What A1 changes.** In the header: the provenance line, Status, Dependencies, the base-blob line and the paragraph "Which text describes the head" (BF-934's and BF-936's merges, and the golden's blob). Section 4: S1's UI G1 failure kinds; S2's milestone row, generated-artifacts bullet, a bullet for P2-10 and G2's command (the AD-1152 test first); the harness rule's gate label. Section 5: S2 M2's subject. Section 7: S1's P3-2 (the anchor and the residual line); P2-10, the script and its expected output, after the generated-artifacts paragraph; S2's P3-1 and P3-2 (the digest named, the residual line). Section 10: S1 L7's note and the new L9; S2 L10. Section 11: the claim about which tests touch the persistence. Section 12: the count of recorded limits. The Batching headline and two of its rows: BF-936 landed first, as its own pull request with its own broad gate, so the two BF-937 slices are one batch with one gate (label `bf937`) and one pull request. Section 13: S2 property 5 and the new property 8. Section 14: the second bullet. This section. **Not changed:** sections 1 to 3, 6, 8 and 9, "Not in this issue", every other pair and new file of both slices, the mutation rows; nothing under `src/` beyond what the blocks say.
