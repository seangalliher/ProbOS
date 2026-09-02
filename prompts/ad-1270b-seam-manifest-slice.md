# AD-1270b — Seam Manifest Slice (slice 1 of 3)

**Status:** Ready to build
**Epic:** #1324 (Delegated AD Execution Mode active)
**Authority:** `docs/development/platform-maturity-program.md` § "AD-1270b — Distributed Seam Contract Catalog and Crossing Tests"
**Dependencies:** `docs/development/seams/p0-manifest.yaml` (exists), `scripts/run_test_gate.py` (exists, AD-1270f Slice 0, `6fcde788`), `src/probos/maturity/` (exists, `6378659c`)
**Estimated tests:** +26 minimum (new file `tests/test_ad1270b_seam_contracts.py`), plus 1 modified assertion in `tests/test_run_test_gate.py`

---

## Problem

`docs/development/seams/p0-manifest.yaml` is the canonical P0 denominator — seven
active Tier-A IDs, one non-gating Tier-B ID, `tombstones: []`. Nothing reads it.

That is not an oversight for the *runtime* (AD-1270a decided deliberately, in
`DECISIONS.md` D6, that the dependency must point checker→data and never
runtime→manifest, and that decision stands). It **is** an oversight for the
*tooling*: with no checker, the manifest is a text file that can be silently
edited, an ID can be deleted rather than tombstoned, and the four `seam_ids`
references already live in production declaration modules can rot against it
without any signal.

Those four references exist today and are unguarded:

```
src/probos/cognitive/maturity_declarations.py:20   seam_ids=("TA-P0-001-turn-act-evidence",)
src/probos/cognitive/maturity_declarations.py:54   seam_ids=("TA-P0-007-crew-outcome-trust",)
src/probos/infrastructure/maturity_declarations.py:18  seam_ids=("TA-P0-006-snapshot-restore-read",)
src/probos/tools/maturity_declarations.py:31       seam_ids=("TA-P0-002-tool-fault-repair",)
```

A typo in any of them, or tombstoning `TA-P0-002` without updating
`tools/maturity_declarations.py`, produces a dangling reference that no test
catches. `CapabilityDeclaration.seam_ids` is typed `tuple[str, ...]`
(`src/probos/maturity/model.py:138`) — free text by design. Free text needs an
external checker or it is not a reference at all.

The program's acceptance for this AD includes **"Catalog symbols resolve against
the live tree."** Every `producer` / `consumer` field in the manifest is
currently prose — `governed tool result`, `approval decision`. Prose does not
resolve. That gap is this slice's substance.

---

## Solution

Build `scripts/check_seam_contracts.py`: a read-only, offline, AST-based
validator over `docs/development/seams/*.yaml`. Wire it into **both** the gate
preflight and an ordinary pytest currency test. Extend the manifest schema with
machine-resolvable symbol fields and an ordinal high-water mark that makes
deletion detectable without git history or a second baseline file.

The checker lives in `scripts/`. Nothing under `src/probos/` gains an import of
the manifest, in this slice or any later one.

---

## Design decisions (made under Delegated AD Execution Mode — rationale recorded)

### D1 — What the checker enforces today, given every `crossing_test` is `null`

Options considered:

| # | Option | Verdict |
|---|---|---|
| a | Schema + ID uniqueness only | Rejected — passes unconditionally against today's manifest; a check that cannot fail is not a gate |
| b | Schema + ID stability + tombstone rules + **symbol resolution** + **declaration cross-reference** + conditional crossing-test collection | **Chosen** |
| c | Additionally require a collecting crossing test on every active Tier-A entry now | Rejected — that is slice 3; it would fail on day one with no way to pass |

Option (b) is non-vacuous **today**: it fails on a dangling `seam_ids`
reference (four live references exist), on an unresolvable symbol, on a deleted
ID, and on a malformed tombstone. It becomes progressively stricter as slice 3
lands, without rewriting.

**Exit non-zero TODAY (default mode):**

1. A `docs/development/seams/*.yaml` file does not parse, or omits a required top-level key.
2. An entry is missing a required field, or `tier` is not `A`/`B`, or `status` is not `active`/`retired`, or `evidence_status` is not one of `planned`/`proven`.
3. Two entries anywhere in `seams` + `tombstones` share an `id`.
4. An `id` does not match `^T[AB]-P0-(\d{3})-[a-z0-9-]+$`.
5. **Ordinal gap** — see D4.
6. A `tombstones` entry is missing `rationale`, `replacement`, `decision`, or `date` (ISO `YYYY-MM-DD`).
7. A `producer_symbol` or `consumer_symbol` is present but does not resolve against `src/probos/` — see D2.
8. An active Tier-A entry has `symbol_status: unresolved` **and** `evidence_status: proven` (unresolved symbols may only sit under `planned`).
9. Any `seam_ids` string in a `probos.*.maturity_declarations` module does not name an **active** manifest entry. Referencing a tombstoned ID is a failure, not a warning.
10. `crossing_test` is non-null and the node ID does not collect — see D3.
11. `evidence_status: proven` with `crossing_test: null`.

**Exit non-zero LATER (slice 3, behind `--require-crossing-tests`, default off):**

12. Any active Tier-A entry has `crossing_test: null`.

Rule 12 ships **in this slice, disabled**, with a test proving the flag flips
behaviour. Slice 3's job then becomes filling node IDs and flipping one default —
not writing new enforcement under deadline.

### D2 — How producer/consumer symbols resolve

| # | Option | Verdict |
|---|---|---|
| a | Optional `producer_symbol`/`consumer_symbol`, enforced only where present | Rejected — all eight would ship empty and rule 7 would never fire |
| b | Required on active Tier-A now, filled in this slice, with a narrow reasoned escape hatch | **Chosen** |
| c | Defer symbol resolution to a later slice | Rejected — it *is* the acceptance criterion for this slice |

Filling eight entries is bounded data work, directly named by the program's
acceptance line. It is not scope creep: the alternative is shipping a checker
whose central rule has no data to check.

**Symbols are fully-qualified dotted paths, never bare names.** Measured: a bare
`record_outcome` matches **11** production definitions across
`consensus/trust.py`, `federation/peer.py`, `mesh/department_dispatcher.py`,
`duty_schedule.py`, and seven others. A bare name resolves to everything, which
is the same as resolving to nothing.

Accepted forms:

```
probos.tools.protocol.ToolResult                       # module.Class
probos.consensus.trust.TrustNetwork.record_outcome     # module.Class.method
probos.maturity.registry.load_default_registry         # module.function
```

Resolution is **AST-only over `src/probos/`** — mirror
`scripts/phantom_api_ast_helper.py`, which walks the tree building class/method
indexes and never imports from `src/probos/` (its own docstring states the
reason: importing breaks sandboxing). Same rule here: importing production
modules to resolve a doc string would give the checker side effects and make it
non-hermetic.

The prose `producer` / `consumer` fields **stay** as human labels. They are the
readable half; the symbol fields are the checkable half.

**Escape hatch, deliberately narrow.** If a seam's producer genuinely has no
single owning symbol yet (a value assembled across a pipeline with no named
carrier), the entry sets `producer_symbol: null` **and**
`symbol_status: unresolved` **and** `symbol_note: "<why>"`. Rule 8 then forbids
that entry from ever reaching `evidence_status: proven`. Do **not** invent a
symbol to satisfy the schema — a fabricated dotted path that happens to resolve
is worse than a declared gap, because it reads as proof.

### D3 — Where the checker runs

**Both.** Preflight *and* a pytest currency test.

- **Preflight** — append one `PhaseSpec` to `_preflight_specs()` at `scripts/run_test_gate.py:1079`, following `config-reference` (line 1091) and `ad-ledger` (line 1094) exactly:
  ```python
  PhaseSpec(
      "seam-contracts",
      [python, "-P", "scripts/check_seam_contracts.py", "--check"],
  ),
  ```
  Insert it **after** `ad-ledger` and **before** `compile`. Preflight runs
  inside the materialized worktree and the wrapper fails the gate if preflight
  mutates the tree (`run_test_gate.py:1710-1718`), so `--check` must write
  nothing anywhere.

- **Currency test** — `tests/test_ad1270b_seam_contracts.py`, mirroring
  `tests/test_config_reference_current.py:41-60`: run the real script with
  `--check` in a subprocess via `[sys.executable, str(_SCRIPT), "--check"]` and
  assert `returncode == 0`.

Preflight alone is insufficient: it only runs under the gate wrapper, and the
program requires that absent data be non-passing under ordinary validation too.
The currency test alone is insufficient: it would only fail ~16 minutes into a
full gate, after preflight already said the tree was clean.

`gen_capability_truth.py` is currently guarded by a currency test **only**, not
by preflight. Do not "fix" that here — it is out of scope.

### D4 — Proving an ID was moved, not deleted

| # | Option | Verdict |
|---|---|---|
| a | Committed baseline file of known IDs | Rejected — a second copy of the same list; drift between the two is a new failure mode, and it violates DRY |
| b | Compare against git history of the manifest | Rejected — not offline; fails in a shallow clone, an sdist, or any non-git checkout, and "the checker cannot run" would then read as "the checker passed" |
| c | **Monotonic ordinal + declared high-water mark inside the manifest itself** | **Chosen** |

Every ID already carries a three-digit ordinal (`TA-P0-001` … `TA-P0-007`,
`TB-P0-001`). Add a top-level block:

```yaml
id_allocation:
  TA-P0: 7
  TB-P0: 1
```

**Rule:** for each prefix, the ordinals in `seams` ∪ `tombstones` must be exactly
the contiguous set `1..N` where `N` is the declared high-water mark. No gaps, no
duplicates, nothing above `N`.

- Delete `TA-P0-003` outright → union is `{1,2,4,5,6,7}`, `N=7` → **gap at 3, fail**.
- Move `TA-P0-003` to `tombstones` → union is still `{1..7}` → **pass**.
- Add `TA-P0-008` without bumping `N` → **above high-water, fail**.
- Delete the *highest* ID, `TA-P0-007` → union `{1..6}`, `N=7` → **gap at 7, fail**.

Fully deterministic, fully offline, no git, no second file. The high-water mark
closes the one hole plain contiguity leaves (deleting the top entry).

**Honest bound, state it in the script docstring:** this cannot stop a reviewer
who deliberately deletes an entry *and* lowers `N` in the same commit. It stops
the *silent* deletion, which is the actual failure mode — and lowering `N` is a
conspicuous line in a reviewed diff, which is exactly the "adding an ID is an
explicit reviewed manifest change" property the program asks for. Do not
overclaim it as tamper-proof.

---

## Implementation

### Section 1 — Manifest schema extension (`docs/development/seams/p0-manifest.yaml`)

Add the top-level `id_allocation` block after `tracking_issue: 1324`:

```yaml
id_allocation:
  TA-P0: 7
  TB-P0: 1
```

Add two rules to the existing `rules:` list (keep the five that are there):

```yaml
  - Producer and consumer symbols are fully-qualified dotted paths that resolve against src/probos/.
  - Ordinals are allocated monotonically per prefix; the union of active and tombstoned ordinals is contiguous to id_allocation.
```

For each of the eight entries add `producer_symbol`, `consumer_symbol`, and —
only where a symbol cannot be resolved — `symbol_status: unresolved` plus
`symbol_note`. Resolve each one against the live tree yourself; do **not** copy
guesses from this prompt. One verified anchor to start from:

```
src/probos/tools/protocol.py:69   class ToolResult
```

Preserve `id`, `tier`, `status`, `evidence_status`, `owner`, `producer`,
`consumer`, `path`, `crossing_test` on every entry, and
`tier_a_gating: false` on `TB-P0-001-federated-attachment`. Leave every
`crossing_test` as `null` and every `evidence_status` as `planned` — filling
those is slice 3.

`tombstones: []` stays empty.

### Section 2 — `scripts/check_seam_contracts.py`

Mirror the structure of `scripts/gen_config_reference.py` / `gen_ad_ledger.py`
for CLI shape (`argparse`, `--check`, `main() -> int`,
`raise SystemExit(main())`) and `scripts/phantom_api_ast_helper.py` for the AST
walk.

```python
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", ...)
    parser.add_argument("--json", metavar="PATH", ...)
    parser.add_argument("--require-crossing-tests", action="store_true", ...)
    parser.add_argument("--seams-dir", metavar="PATH", default=...)
```

Requirements:

- Load **every** `docs/development/seams/*.yaml`, not just `p0-manifest.yaml`. The program says "domain-split metadata under `docs/development/seams/*.yaml`"; a hard-coded single filename would silently ignore the second file the moment one is added. Uniqueness rules apply across the union.
- `yaml.safe_load` only. `pyyaml>=6.0` is already a runtime dependency (`pyproject.toml:26`) — add nothing.
- Symbol resolution by AST over `src/probos/`. Cache the index at module level like `phantom_api_ast_helper.py:_INDEX_CACHE`. Never `import_module` a production module.
- `seam_ids` cross-reference: read the four modules named in `probos.maturity.registry.DECLARATION_MODULES` (`src/probos/maturity/registry.py:26-31`) **by AST**, extracting `seam_ids=(...)` string literals. Do not call `load_default_registry()` — that imports production code.
- Crossing-test collection, only for non-null `crossing_test`: one subprocess, mirroring `tests/test_ad1143_ablation_gating.py:92-110`:
  ```python
  [sys.executable, "-m", "pytest", "--collect-only", "-q",
   "-o", "addopts=", "-p", "no:cacheprovider", node_id]
  ```
  `-o addopts=` is **mandatory** — `pyproject.toml:196` sets
  `addopts = "-n 16 --dist=loadfile"` and inheriting it spawns 16 xdist workers
  per node ID. Exit code `5` (`EXIT_NOTESTSCOLLECTED`) is a **failure**, not a
  pass. So is a non-zero exit from a collection error. With all eight
  `crossing_test` values `null` today, zero subprocesses run and the checker
  stays fast.
- Errors accumulate. Report **all** failures with file, entry ID, and what was expected, then return 1 — do not exit on the first. A checker that reports one problem per run costs one gate cycle per problem.
- Exceptions follow the propagate tier for data integrity: a manifest that cannot be parsed is `logger`-free `print(..., file=sys.stderr)` + `return 1`, never a swallowed default.
- Writes nothing under `--check`. Preflight fails the gate if the tree changes.

### Section 3 — Preflight wiring (`scripts/run_test_gate.py`)

Insert the `seam-contracts` `PhaseSpec` per D3 into `_preflight_specs()` (line 1079).

**Then update `tests/test_run_test_gate.py:248-258`** —
`test_preflight_contains_import_origin_generated_and_compile_checks` asserts
**exact list equality** on spec names:

```python
assert [spec.name for spec in specs] == [
    "import-origin", "config-reference", "ad-ledger", "compile",
]
```

It must become `[..., "ad-ledger", "seam-contracts", "compile"]`, plus an
`assert "scripts/check_seam_contracts.py" in flattened`. This test **will** fail
otherwise, and it fails in preflight's own suite — expect it, do not treat it as
a regression.

### Section 4 — `tests/test_ad1270b_seam_contracts.py`

New file. Use `tmp_path` for every synthetic manifest; never mutate the real one.
Structure the checker so its validation entry point is importable
(`importlib.util.spec_from_file_location`, as `tests/test_ad1184_ad_ledger.py:44`
does) so most tests need no subprocess.

Required coverage (≥26 tests):

**Live-manifest currency (3)** — script exists; real manifest passes `--check` in
a subprocess; `--require-crossing-tests` on the real manifest fails today, with
a message naming the entries that lack node IDs.

**Schema (5)** — unparseable YAML; missing top-level key; bad `tier`; bad
`evidence_status`; entry missing a required field.

**IDs (4)** — duplicate across `seams`; duplicate across `seams`/`tombstones`;
malformed ID string; ordinal above `id_allocation`.

**Ordinals / tombstones (6)** — deleted middle ID fails with a gap; deleted
highest ID fails against the high-water mark; ID moved to `tombstones` passes;
tombstone missing `rationale` fails; tombstone with a non-ISO `date` fails; a
complete tombstone with all four fields passes.

**Symbols (4)** — a resolvable dotted path passes; an unresolvable module fails;
a resolvable module with an unresolvable attribute fails;
`symbol_status: unresolved` + `evidence_status: proven` fails.

**Declaration cross-reference (3)** — a `seam_ids` value naming an active entry
passes; naming an unknown ID fails; naming a **tombstoned** ID fails.

**Crossing tests (3)** — `crossing_test: null` is skipped in default mode;
`evidence_status: proven` with `crossing_test: null` fails; a non-collecting node
ID fails (assert exit-5 is treated as failure).

**Error accumulation (1)** — a manifest with three distinct defects reports all
three, not one.

Naming: `test_{behaviour}_{scenario}_{expected}`. Each test builds its own
fixture; no shared mutable state; no ordering dependence.

---

## Do not build

- **The architecture-fitness slice.** No `scripts/check_architecture_principles.py`, no SRP/line-count report, no layer-import rule, no `asyncio.create_task` ownership scan, no baseline of reviewed violations. That is AD-1270b slice 2, its own commit and its own acceptance record. (Verified absent: `scripts/` contains no `check_architecture_principles.py`.)
- **The final Tier-A crossing closeout.** Do not author any crossing test, do not fill any `crossing_test` node ID, do not move any `evidence_status` off `planned`. That is AD-1270b slice 3 and it depends on recovery, decomposition, trace correlation, and supported-profile exercise landing first.
- **Any `src/probos/` import of the manifest.** No module under `src/probos/` may read, parse, glob, or validate against `docs/development/seams/*.yaml`. `DECISIONS.md` D6 and the program's "No central code object imports or executes the catalog" both bind. `CapabilityDeclaration.seam_ids` stays opaque free text; do not add a validator to `src/probos/maturity/model.py`.
- **A universal runtime message-bus schema.** No carrier base class, no envelope type, no serialization contract. The catalog is documentation and test-discovery metadata.
- **A replacement for domain protocols or Pydantic models.** `src/probos/protocols.py` and the config models are untouched.
- **A source-text regex that mistakes comments for behavior.** Symbol resolution and `seam_ids` extraction are AST-based. A `re.search` over file text would match a dotted path inside a docstring or a `#` comment and report it as resolved. Follow `phantom_api_ast_helper.py`, not grep.
- **`scripts/select_tests.py`** or any impact-selection work — that is AD-1270f, and it is absent by design today.
- **Touching `gen_capability_truth.py`'s wiring.** Its currency-test-only guard is out of scope.

---

## Acceptance criteria

1. `scripts/check_seam_contracts.py` exists, is read-only, imports nothing from `src/probos/`, and exits 0 against the committed manifest.
2. `python scripts/check_seam_contracts.py --check` exits 0; `--require-crossing-tests` exits non-zero today and names the eight entries lacking node IDs.
3. Every active Tier-A entry carries `producer_symbol` and `consumer_symbol` that resolve against `src/probos/`, **or** carries `symbol_status: unresolved` with a `symbol_note` explaining why — and no `unresolved` entry has `evidence_status: proven`.
4. `id_allocation` is present; deleting any entry (including the highest ordinal) fails the checker; moving it to `tombstones` with all four fields passes.
5. All four live `seam_ids` references resolve; a fifth naming an unknown or tombstoned ID fails.
6. `seam-contracts` appears in `_preflight_specs()` between `ad-ledger` and `compile`, and `tests/test_run_test_gate.py` is updated to match.
7. `tests/test_ad1270b_seam_contracts.py` adds **≥26** tests, all passing.
8. Focused gate green: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1270b_seam_contracts.py tests/test_run_test_gate.py tests/test_ad1270a_capability_truth.py -q -n 0 -p no:randomly`
9. `git diff --stat src/probos/` is **empty**. This slice ships zero production source change.
10. Broad gate green via the canonical wrapper on a committed tree: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad-1270b-seam-manifest`
11. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Tracking

- `PROGRESS.md` — one entry for the slice: what the checker proves today, what rule 12 will prove once slice 3 lands, and the honest bound on D4's tamper resistance.
- `DECISIONS.md` — one entry recording D1–D4, in particular the fully-qualified-symbol requirement (with the measured `record_outcome` ×11 ambiguity as the reason) and the ordinal high-water design in place of a git or baseline-file comparison.
- `docs/development/platform-maturity-program.md` — no edit. The program is the authority; do not amend it from a build.
- GitHub #1324 — comment with the commit hash, the checker's default-mode rule list, and confirmation that slices 2 and 3 remain open.

---

## Verified against codebase (2026-09-01)

```
list_dir scripts/
  ad_ceiling.py, gen_ad_ledger.py, gen_capability_truth.py, gen_config_reference.py,
  phantom_api_ast_helper.py, run_test_gate.py, _gate_pytest_plugin.py, ...
  ABSENT: check_seam_contracts.py, check_architecture_principles.py, select_tests.py

list_dir docs/development/seams/
  p0-manifest.yaml            (only file)

grep -n "p0-manifest|seams/|check_seam_contracts|seam_ids" (repo-wide, 25 hits / 10 files)
  DECISIONS.md:33                                    D6 non-coupling decision
  docs/development/platform-maturity-program.md:304  scripts/check_seam_contracts.py named
  docs/development/platform-maturity-program.md:307  p0-manifest.yaml is canonical denominator
  src/probos/cognitive/maturity_declarations.py:20   seam_ids=("TA-P0-001-turn-act-evidence",)
  src/probos/cognitive/maturity_declarations.py:54   seam_ids=("TA-P0-007-crew-outcome-trust",)
  src/probos/infrastructure/maturity_declarations.py:18  seam_ids=("TA-P0-006-snapshot-restore-read",)
  src/probos/tools/maturity_declarations.py:31       seam_ids=("TA-P0-002-tool-fault-repair",)
  src/probos/maturity/model.py:138                   seam_ids: tuple[str, ...] = ()
  NO hit under src/probos/ reads, parses, or opens the manifest file.

scripts/run_test_gate.py:1079   def _preflight_specs(repo_root: Path) -> list[PhaseSpec]:
scripts/run_test_gate.py:1091     PhaseSpec("config-reference", [python, "-P", "scripts/gen_config_reference.py", "--check"])
scripts/run_test_gate.py:1094     PhaseSpec("ad-ledger", [python, "-P", "scripts/gen_ad_ledger.py", "--check"])
scripts/run_test_gate.py:1710     post-preflight snapshot compare -> gate invalid if preflight mutated the tree
scripts/run_test_gate.py:115      @dataclass(frozen=True) class PhaseSpec: name: str; command: list[str]

tests/test_run_test_gate.py:248   assert [spec.name for spec in specs] == ["import-origin","config-reference","ad-ledger","compile"]
tests/test_config_reference_current.py:48  subprocess.run([sys.executable, str(_SCRIPT), "--check"], ...)
tests/test_ad1184_ad_ledger.py:44          importlib.util.spec_from_file_location("gen_ad_ledger", _SCRIPT)
tests/test_ad1143_ablation_gating.py:92-110 pytest --collect-only -q -o addopts= -p no:cacheprovider
pyproject.toml:196               addopts = "-n 16 --dist=loadfile"
pyproject.toml:26                pyyaml>=6.0   (already a runtime dependency)

src/probos/tools/protocol.py:69            class ToolResult
grep -n "^\s*(class|def|async def)\s+record_outcome" src/  -> 11 production definitions
  (consensus/trust.py:304, federation/peer.py:92, federation/hebbian_map.py:94,
   mesh/department_dispatcher.py:204, duty_schedule.py:241, protocols.py:78,
   holodeck/scenarios.py:610, strategy_advisor.py:144,
   crew_development/discovery/strength_map.py:75,
   cognitive/predictive_branching/{budget.py:109,executor.py:135})
  -> bare method names are not resolvable; dotted paths are mandatory.

src/probos/maturity/registry.py:26-31      DECLARATION_MODULES = (4 dotted module paths)
file_search **/test_ad1270*.py             only tests/test_ad1270a_capability_truth.py
                                           -> tests/test_ad1270b_seam_contracts.py is a new file
```
