# AD-1270f — Impact Selector in Shadow Mode (Slice 1 of N)

**Epic:** #1324 (AD-1270 Platform Maturity Program)
**Authority:** `docs/development/platform-maturity-program.md`, section *AD-1270f — Fail-Broad Impact Selection and Balanced Full Gate*
**Predecessor:** Slice 0 (canonical gate wrapper) shipped in `6fcde788`. Latest green gate: `b70c2026`, 26,312 passed / 28 skipped, 26,340 collected nodes, 16 workers.
**Mode:** Delegated AD Execution Mode is active. In-envelope decisions below are already made — implement them, do not re-open them.

---

## Why this exists

The full gate is ~15.4 minutes over 26,340 nodes. Running it after every small issue caps throughput. Filename-only selection cannot see fixtures, dynamic imports, indirect consumers or seam contracts, so it produces false confidence instead of speed.

This slice builds `scripts/select_tests.py` as an **acceleration tool that has no release authority whatsoever**, and runs it in **shadow mode**: it changes nothing, and it accumulates the evidence needed to later prove it would not have missed anything.

`scripts/select_tests.py` is **absent** today — verified: `file_search` for `scripts/select_tests.py` returned no files, and `git ls-files 'scripts/*.py'` filtered to `check_|gen_|gate|select` returns only `_gate_process_supervisor.py`, `_gate_pytest_plugin.py`, `check_architecture_principles.py`, `check_seam_contracts.py`, `gen_ad_ledger.py`, `gen_capability_truth.py`, `gen_config_reference.py`, `run_test_gate.py`.

---

## The house pattern you are copying

Two shipped checkers define the idiom. Read both before writing a line:

- `scripts/check_seam_contracts.py`
- `scripts/check_architecture_principles.py`

Copy these exact idioms:

1. **Indexed from `git ls-files`, never a disk walk.** Both use
   `subprocess.run(["git","ls-files","-z","--","*.py"], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)`
   and return `None` when git cannot answer so the caller degrades **loudly** — see `_tracked_python_files` in both files. An empty measurement reading as "nothing to select" is the worst possible failure mode here; for this script an empty measurement must mean **fail-broad**, never "select nothing".
2. **AST only, never regex over source text.** A dotted path inside a docstring or a `#` comment must not read as code. This is a program-level *Do Not Build* item.
3. **Accumulate every error, then report.** Neither checker stops at the first problem.
4. **`--check` writes nothing.** The gate wrapper fails the run if preflight mutates the tree. This script's read-only modes must be genuinely read-only.
5. **`main(argv: list[str] | None = None) -> int`** with `argparse`, returning `0`/`1`. See `check_architecture_principles.py:1192`.
6. **Every subprocess pytest call passes `-o addopts=`.** `pyproject.toml:196` sets `addopts = "-n 16 --dist=loadfile"`; inheriting it spawns sixteen xdist workers per invocation. See the docstring on `_collects` in `check_seam_contracts.py:393` and the `-p no:cacheprovider` it pairs with.
7. **Names stay POSIX and dotted.** `repr()` of a `Path` is `WindowsPath('x')` on Windows and `PosixPath('x')` on Linux, and that drift has already turned this repository's CI red while `--check` passed locally. Normalise with `.replace("\\", "/")` at every boundary.
8. **Docstring states honest bounds.** Both checkers carry an explicit "what this does NOT catch" section. Yours must too, and the bounds are enumerated below — they are measured, not guessed.

---

## Decision 1 — Where the per-test map comes from, and what makes it stale

### Chosen: hybrid, with capture **off the release-gate path**

Coverage contexts are the primary signal; static imports are the fallback for the unmeasured remainder; **absence or staleness of the map forces fail-broad**.

**The map is NOT captured during the canonical gate.** Measured, not assumed:

| Measurement | Command | Result |
|---|---|---|
| Baseline, 466 nodes | `.venv\Scripts\pytest.exe tests/test_decomposer.py tests/test_workforce.py tests/test_builder_agent.py -q -n 0 -p no:randomly -o addopts=` | **23.91 s** |
| Same, `--cov --cov-config=<rc>` with `dynamic_context = test_function` | as above plus `--cov --cov-report= --cov-config=$rc` | **41.58 s** → **1.74×** |
| Same, with `COVERAGE_CORE=sysmon` | as above, env var set | **41.58 s** — **no speedup** |
| Coverage data size | `Get-ChildItem $tmp -Filter '.coverage*'` | 499,712 bytes for 466 tests |

Versions: Python 3.12.13, coverage 7.13.5, pytest 9.0.2, xdist 3.8.0 (`.venv\Scripts\python.exe -c "import sys,coverage,pytest,xdist; ..."`).

The `sysmon` result is the decisive one: coverage silently falls back to the slow tracer when dynamic contexts are requested, so the fast Python 3.12 core buys nothing here. Extrapolating 1.74× onto the measured 923.795 s gate gives roughly **26.8 minutes, a +11-minute cost on release authority**. That is a naive upper-ish bound — coverage overhead scales with executed bytecode, not wall time, so sleep- and I/O-bound tests will inflate it less. Do not quote a suite-wide multiplier you have not measured; quote the subset figure and say it is a subset.

Making the frozen release gate ~74% slower in order to accelerate non-release runs is self-defeating, and it puts an acceleration tool on the critical path of release authority — the exact boundary this AD draws. So:

- `scripts/select_tests.py --capture-map` runs the instrumented suite **out of band**, on demand, at a known-green commit. It is never invoked by `run_test_gate.py`.
- Output: `logs/gates/testmap-<base_tree_short>.json`, plus a tracked digest row (Decision 2).

**Rejected (a) — coverage captured inside the canonical gate:** +11 min measured on release authority, and it changes the frozen gate's plugin set.
**Rejected (b) — static import graph only:** cannot see fixtures, `conftest.py` wiring, or dynamic construction. The program names precisely this as why filename-only selection fails.

### Staleness is bound to tree identity, never a timestamp

Copy the receipt idiom from `_write_success_receipt` in `scripts/run_test_gate.py:1484` — it binds `head`, `head_tree`, `index_tree` and SHA-256 of each artifact. The map header carries `base_commit`, `base_tree`, `schema_version`, `selector_version`, `map_version`.

The map is **usable** only when all of these hold; any failure is fail-broad:

| Check | Command | Verified behaviour |
|---|---|---|
| base commit exists | `git cat-file -e <base_commit>^{commit}` | exit 0 |
| base is an ancestor of HEAD | `git merge-base --is-ancestor <base_commit> HEAD` | exit **0** for ancestor, exit **1** for non-ancestor — both confirmed on this tree |
| declared tree matches | `git rev-parse <base_commit>^{tree}` equals `base_tree` | `HEAD` → `b70c2026…`, `HEAD^{tree}` → `eebfd903…` |
| schema/selector version match | header fields | — |

A difference between `base_tree` and the current tree is **not** staleness — it is the normal case, and it is exactly what the selector is for. Staleness means the map cannot be *related* to the current tree: unknown base, rebased/unrelated history, or a version drift.

---

## Decision 2 — Shadow mode's output contract, and where it lives

### Chosen: split — bulky record in `logs/gates/shadow/`, immutable digest row in a **tracked** ledger

`logs/gates/` is git-ignored. Verified: `.gitignore:120` is `/logs/*` with `!/logs/.gitkeep` on line 121. The gate's janitor also removes materialized worktrees. Evidence for a fixed-enrollment 20-run series must by definition outlive any single machine state, so `logs/gates/` alone is the wrong home.

But a full record contains 26,340 node IDs; the live `.collection.json` is **5,512,962 bytes**. Twenty of those is ~110 MB and does not belong in git.

So:

- **Bulky per-run record** → `logs/gates/shadow/<utc>-<tree_short>-<pid>.shadow.json`: full selected node list, full collected node list, full changed-path list, every fail-broad reason fired.
- **Durable ledger** → `docs/development/test-selection-shadow-ledger.jsonl`, tracked, **append-only**, one JSON object per line:

```
{"schema_version":1,"kind":"run","recorded_at_utc":"...","head":"<sha>","head_tree":"<sha>",
 "tree_fingerprint":"<sha256 of status+staged diff, receipt idiom>",
 "changed_paths":["..."],"changed_path_count":N,
 "selector":{"verdict":"selected|fail-broad","reasons":["..."],"node_count":N,"nodes_sha256":"..."},
 "full":{"node_count":26340,"nodes_sha256":"...","source":"logs/gates/....collection.json"},
 "miss":{"detected":false,"missed_node_count":0,"missed_nodes_sha256":null},
 "selector_version":"...","map_version":"...","map_base_commit":"...",
 "record":{"path":"logs/gates/shadow/...","sha256":"..."}}
```

The `nodes_sha256` uses the same digest shape as `_node_digest` in `run_test_gate.py` (JSON dump of the sorted tuple, `ensure_ascii=True`, `separators=(",",":")`) — see `_digest` in `scripts/_gate_pytest_plugin.py:20`. This is what makes a later miss detectable: the selected set and the full set are both hash-pinned to a tree, so a claim that the selector "would have caught it" can be recomputed rather than believed.

### Fixed enrollment is declared before observation

The first line of the ledger is a **header record** written once by `--declare-enrollment`:

```
{"schema_version":1,"kind":"enrollment","series":"selector-shadow-v1","target_runs":20,
 "cutoff_utc":"<recorded before any run>","enrollment_commit":"<sha>","declared_at_utc":"..."}
```

`--declare-enrollment` **fails** if a header already exists. Rows are eligible only when `recorded_at_utc > cutoff_utc` and the tree fingerprint is source-changing and not already present. Same-tree retries are appended and remain visible as cost but are marked `eligible: false` and cannot pad the sample. Extending, restarting or excluding a series requires a Captain-ratified decision recorded before the replacement series runs — the tool must refuse to rewrite or truncate the ledger.

**Rejected (a) — `logs/gates/` only:** not durable; git-ignored and janitor-swept.
**Rejected (b) — tracked full records:** ~110 MB in git.

---

## Decision 3 — The fail-broad rule set, made testable

Every rule carries a stable string ID. `select_tests.py` exposes `FAIL_BROAD_RULES: tuple[str, ...]` as the single source of truth.

| Rule ID | Trigger | Detection |
|---|---|---|
| `map-missing` | map file absent or unreadable | file open |
| `map-schema` | `schema_version` / `selector_version` / `map_version` drift | header compare |
| `map-base-unknown` | base commit not in repo | `git cat-file -e <sha>^{commit}` |
| `map-not-ancestor` | base commit not an ancestor of HEAD | `git merge-base --is-ancestor` exit != 0 |
| `map-tree-mismatch` | `git rev-parse <base>^{tree}` != declared `base_tree` | compare |
| `change-deleted` | a `D` status letter in the diff | `git diff --name-status --find-renames -M` |
| `change-renamed` | an `R…` status letter in the diff | same |
| `blast-radius` | changed path matches a blast-radius pattern | path match (below) |
| `unknown-module` | a changed `src/probos/**.py` module is absent from the map's measured file set | set membership |
| `dynamic-import` | a changed file calls `importlib.import_module(...)` / `__import__(...)` with a non-`ast.Constant` argument | AST |
| `uncontexted-test` | a collected test node reachable from no coverage context | context→node resolution |
| `selector-self-change` | any change under `scripts/select_tests.py`, its map, or its ledger | path match |

### Blast-radius patterns — verified against the live tree

`Test-Path` / `git ls-files` results, so the pattern list claims nothing that does not exist:

| Path | Exists |
|---|---|
| `src/probos/runtime.py` | yes |
| `src/probos/startup/` | yes |
| `src/probos/config.py` | yes |
| `src/probos/types.py` | yes |
| `src/probos/protocols.py` | yes |
| `src/probos/events.py` | yes |
| `pyproject.toml` | yes |
| `tests/conftest.py` | yes |
| `tests/ablation/conftest.py` | yes |
| `scripts/run_test_gate.py`, `scripts/_gate_pytest_plugin.py` | yes |
| root `conftest.py` | **no** — do not pattern for it as a literal; use a glob so one appearing later is caught |
| `requirements.txt` | **no** — dependency manifest here is `pyproject.toml` |

`git ls-files '*conftest.py'` returns exactly `tests/ablation/conftest.py` and `tests/conftest.py`. Use `**/conftest.py`, not a hardcoded pair.

`git ls-files 'src/probos/*protocol*' 'src/probos/*event*'` also returns per-domain protocol/event modules (`src/probos/discovery/protocol.py`, `src/probos/avatars/events.py`, and others). Decide deliberately whether the blast-radius rule covers only the two root modules or every `**/protocol*.py` / `**/event*.py`; **choose the broader glob** — any uncertainty selects more tests, never fewer — and say so in the docstring.

### Seam tests are an input, and that input is empty today

`git ls-files 'docs/development/seams/*'` returns exactly `docs/development/seams/p0-manifest.yaml`, and every `crossing_test` in it is `null` — **8 occurrences, all `crossing_test: null`**. AD-1270b slice 3 has not shipped.

So the seam-test input contributes zero node IDs right now. That is a correctness trap: a rule whose input is empty looks identical to a rule that works. Read the manifest, union in every non-null `crossing_test`, and **prove the union works with a fixture manifest carrying non-null values**. A test that only exercises the live manifest proves nothing about this path.

### Proving each rule fires — and that it is not stuck on

This is the acceptance property that matters most. For every ID in `FAIL_BROAD_RULES`:

1. one test constructing a **real** input that fires it, asserting both `verdict == "fail-broad"` **and** that the ID appears in `reasons`;
2. one test on a benign input asserting that ID is **absent** from `reasons` — a rule permanently on is not a safety property, it is a broken selector that merely looks safe;
3. one aggregate test asserting `set(FAIL_BROAD_RULES) == set(ids_covered_by_firing_tests)`, so adding a rule without a firing test fails the suite.

Use **synthetic temporary git repositories** for the git-dependent rules (`map-not-ancestor`, `change-deleted`, `change-renamed`, `map-base-unknown`) — an unrelated-history or genuine rename cannot be faked against the live tree. Use the live tree for blast-radius path matching, so the patterns are proven against real files. `tests/test_run_test_gate.py` already builds temp git repos with a `_git(tmp_path, "init", "-q")` helper — copy that shape.

---

## Decision 4 — What ships now, what accrues later

### Ships in this slice

- `scripts/select_tests.py` with `--capture-map`, `--select`, `--shadow`, `--declare-enrollment`, `--json`.
- `docs/development/test-selection-shadow-ledger.jsonl` with its enrollment header.
- The full fail-broad rule set and its firing/non-firing/completeness tests.
- **The balanced full-gate manifest as a measurement artifact only.** `--gate-balance <collection.json> <junit.xml>` reads a shipped gate's artifacts and reports per-worker node counts and per-node durations, with union equality and duplicate detection. The imbalance is already measurable from the live green run: `worker_execution_counts` in `logs/gates/20260902T090204.252960Z-af-rel-b70c20266aa4-p106116-10eebad1.collection.json` ranges from **gw11 = 109** to **gw14 = 4,367** — a ~40× spread under `--dist=loadfile`, against a maximum single-file node count of 308 (`tests/test_knowledge_store.py`). Report it. **Do not change the distribution.**
- `DECISIONS.md` entries recording Decisions 1–4 with the measured numbers above.

### Accrues later — and this slice must not imply otherwise

- **The 20-run shadow series cannot complete in this session.** It requires 20 distinct eligible source-changing tree fingerprints after the cutoff. Ship the enrollment header and the machinery; ship **zero or one** rows. Any text — prompt, commit message, issue comment, docstring — that describes the series as complete, or the "zero misses" acceptance as met, is false.
- The predeclared historical BF mutation corpus.
- The p95 < 90 s leaf-feedback measurement over a predeclared 20-case corpus on a pinned host.
- Actually rebalancing the gate's worker distribution.
- Any promotion of the selector out of shadow mode.

### Promotion condition

The selector may stop being shadow-only when **all** hold: the enrollment series reaches 20 eligible rows with zero detected misses; the BF mutation corpus is predeclared, hashed and scores zero misses; and a Captain-ratified decision records the change. Until then `--select` output is advisory and no workflow may consume it as authority. Write this condition into the module docstring so it cannot be quietly dropped.

---

## Do not build

- **Any path by which selection authorizes release, push, or issue closure.** No workflow, script, doc, or instruction may treat `select_tests.py` output as gate evidence. Only a validated canonical receipt from `run_test_gate.py` is release authority.
- **A preflight phase for the selector.** `_preflight_specs` in `scripts/run_test_gate.py:1079` currently yields exactly `["import-origin","config-reference","ad-ledger","seam-contracts","architecture-fitness","compile"]`, and `tests/test_run_test_gate.py` asserts that list by **exact equality**. Do not add a phase, do not edit that assertion. An acceleration tool on the gate's critical path makes the gate slower and gives selection a foothold in release authority.
- **Any modification of the frozen gate's collected node set**, its distribution, its plugin set, or `_validate_collection_manifests`.
- **Claiming the 20-run series, the BF corpus, or the p95 measurement is complete.**
- Test prioritization based only on filenames or historical pass frequency.
- Quarantine, deletion, skipping, deselection, or timeout weakening of slow tests as a performance strategy.
- A regex over source text that mistakes a comment or docstring for behaviour.
- Any import or execution of `select_tests.py` or its artifacts from `src/probos/` — the AD-1270a `DECISIONS.md` D6 direction is checker → data, never runtime → tool.

---

## Honest bounds the docstring must state

These are measured on this tree, not speculative:

1. **Parametrized tests collapse to one coverage context.** Verified: of 414 non-empty contexts, **0** carried a `[param]` suffix, and 4 contexts fanned out to 8, 16 and 4 collected nodes respectively. Fan-out is conservative — one context selects every parameterisation — which satisfies "any uncertainty selects more tests, never fewer". Say so; do not present it as precision.
2. **A test that executes no `src/probos` line produces no context and is invisible to the map.** Verified: 466 tests executed, 441 nodes reachable from contexts — **25 tests had no context**. Rule `uncontexted-test` exists because of this; it is a real class, not a hypothetical.
3. **Context→node-ID translation is dotted, not a node ID.** Contexts render as `tests.test_builder_agent.TestAct.test_act_parses_file_blocks`. Verified against the live 26,340-node collection: **414 of 414 non-empty contexts resolved to at least one collected node; 0 unresolvable.** Translation is `path[:-3].replace("/",".") + "." + rest.split("[")[0].replace("::",".")`. Any context that fails to resolve must fail broad, not be dropped.
4. **Static AST only.** A binding rebound at runtime, a helper that wraps an import, or a fixture resolved by name at collection time is not seen. Resolve import aliases the way `import_aliases` / `canonical_callee` in `check_architecture_principles.py` do — review proved an attribute-only matcher let ordinary `import x as y` style straight through.
5. **Untracked files are invisible by construction**, because the file list comes from `git ls-files`. That is the point: the canonical gate materializes `HEAD`, so anything satisfied by uncommitted work would pass locally and fail in the gate.
6. **The 1.74× coverage multiplier is a 466-node subset figure**, not a suite-wide measurement.

---

## Acceptance criteria

- `scripts/select_tests.py` exists, is read-only in `--select`/`--shadow`/`--check` modes, indexes from `git ls-files`, is AST-only, accumulates all errors, and returns `0`/`1` from `main(argv) -> int`.
- Every subprocess pytest invocation passes `-o addopts=` and `-p no:cacheprovider`.
- **New tests: at least 45**, in `tests/test_ad1270f_impact_selector.py`:
  - ≥ 12 firing tests, one per `FAIL_BROAD_RULES` ID, each asserting `verdict == "fail-broad"` and the specific reason ID;
  - ≥ 12 non-firing tests, one per ID, asserting that ID is absent on a benign input;
  - 1 completeness test asserting `set(FAIL_BROAD_RULES)` equals the set of IDs covered by firing tests;
  - ≥ 4 context→node-ID translation tests, including a parametrized fan-out case and an unresolvable-context case that must fail broad;
  - ≥ 4 seam-manifest union tests using a **fixture** manifest with non-null `crossing_test` values, plus one against the live all-null manifest;
  - ≥ 6 ledger tests: header written once, second `--declare-enrollment` refused, append-only enforced, same-tree retry marked ineligible, digest recomputation, truncation refused;
  - ≥ 3 map staleness tests using synthetic temp git repos (non-ancestor, unknown base, tree mismatch);
  - ≥ 3 `--gate-balance` tests: union equality, duplicate detection, per-worker count reporting.
- `--declare-enrollment` produces the header; the ledger contains **at most one** run row at commit time.
- `_preflight_specs` and `tests/test_run_test_gate.py`'s exact-equality phase assertion are **unchanged**. Prove it: `git diff --name-only` must not list `scripts/run_test_gate.py`.
- `DECISIONS.md` records Decisions 1–4 with the measured figures.
- Focused: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1270f_impact_selector.py tests/test_run_test_gate.py tests/test_ad1270b_seam_contracts.py -q -n 0 -p no:randomly` green.
- Preflight: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --preflight-only --label ad-1270f` green, and preflight duration still inside the 90 s target. **Measure it yourself and record the number.** The Architect could not: on `b70c2026` the wrapper correctly refused at 2.3 s with `PREFLIGHT FAIL: Tracked unstaged changes are present` and untracked `exercise.py`, `probe_test1.py`, `src/probos/infrastructure/restore.py` from a concurrent session. The last reported figure, 29.8 s after the architecture-fitness phase landed, is second-hand — do not repeat it as measured.
- Adversarial review by `Diff Reviewer` on a **different model than wrote the code**, findings repaired before the broad gate.
- One canonical gate on the frozen tree: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad-1270f --receipt logs/gates/ad-1270f-release.receipt.json`. Predict the node total before the run (26,340 + new tests) and reconcile exactly. Bank the receipt and its manifest/JUnit/collection artifacts into `logs/gates/` and recompute every SHA-256 before pushing.
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Risks for the Builder

1. **The seam-test input is empty and will look correct while doing nothing.** All 8 `crossing_test` values are `null`. Without a fixture manifest carrying non-null values, this code path ships untested and unproven.
2. **Do not let `--capture-map` drift onto the gate path.** Measured +11 minutes on release authority. It is a separate, on-demand command.
3. **Context resolution is a translation, and translations rot.** 414/414 resolved today. Assert the resolution rate in a test against the live collection artifact; a silent drop of an unresolvable context is a miss the ledger cannot detect afterwards.
4. **`logs/gates/` is swept.** Anything the 20-run series depends on must be in the tracked ledger before the worktree disappears.
5. **Appending to a tracked JSONL from a tool that also reads it invites a rewrite bug.** Open in append mode only; never read-modify-write the whole file.
6. **The 5.5 MB collection artifact will tempt an in-memory full-set diff on every run.** Hash first, compare hashes, and only materialise the difference when the hashes disagree.
7. **`--dist=loadfile` means the balance report is about durations, not node counts.** Max single-file node count is 308 but gw14 executed 4,367 nodes; the imbalance comes from grouping, not from one huge file. Report duration from the JUnit `time` attributes, not from node counts alone.
8. **The tree currently carries another session's in-progress work.** At `b70c2026` the wrapper refuses preflight on tracked unstaged changes plus untracked `exercise.py`, `probe_test1.py`, `src/probos/infrastructure/restore.py`. Do not stash, revert, or delete any of it. Either wait for the tree to clear or gate from a separate linked worktree (`git worktree add` + apply your own staged patch + `PYTHONPATH=<wt>/src`). Expect the known artefact that tests shelling out to repo-relative scripts fail in a linked worktree and pass in the main one — verify, then count as passes.
