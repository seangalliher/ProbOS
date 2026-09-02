# AD-1270b — Architecture Fitness Slice (slice 2 of 3)

**Owner:** AD-1270b (existing). **Allocate no new AD number** — the program states
"This program assigns no new top-level AD"
(`docs/development/platform-maturity-program.md`, Allocation status).

**Tracking issue:** [#1324](https://github.com/seangalliher/ProbOS/issues/1324) — parent epic, stays open.
This is a **parent-backed slice**: bank the reviewed commit, the durable canonical gate
receipt, and the parent checklist/evidence update. Do **not** close #1324.

**Authority:** `docs/development/platform-maturity-program.md`, section
**AD-1270b — Distributed Seam Contract Catalog and Crossing Tests**, delivery
slice 2 ("Architecture fitness slice: versioned baseline and
`scripts/check_architecture_principles.py`, with explicit reviewed exceptions
rather than hidden thresholds").

**Baseline of record:** `docs/development/platform-maturity-baseline-2026-08-30.md`,
pinned at `bf6c9981151cafbc44b3bb8599d69b797f543fde`.

---

## 1. Verified ground truth

Everything below was measured against the live tree before this prompt was written.
The command that produced each number is given. Re-measure if you doubt one; do not
assume it.

### 1.1 What exists

| Fact | Evidence |
|---|---|
| `scripts/check_seam_contracts.py` exists (slice 1, shipped `a9bc216b`) | `file_search scripts/*.py` |
| It is wired as preflight `PhaseSpec("seam-contracts", ...)` | `scripts/run_test_gate.py:1097-1100` |
| `tests/test_ad1270b_seam_contracts.py` is the currency-test pattern | `git ls-files -- "tests/*seam*"` |
| `tests/test_config_reference_current.py` is the second currency-test precedent | `git ls-files -- "tests/*current*"` |
| `docs/development/` already hosts checker data | `ad-ledger-snapshot.json`, `seams/p0-manifest.yaml` |
| `probos.protocols` exists; `ConnectionFactory` is a `Protocol` | `src/probos/protocols.py:362` |
| Interpreter | Python 3.12.13 (`.venv/Scripts/python.exe -V`) |

### 1.2 What is absent

`scripts/check_architecture_principles.py` is **ABSENT**.
`scripts/select_tests.py` is **ABSENT**.
No architecture-fitness artifact of any name exists.

Enumerations run:

```
file_search d:\ProbOS\scripts\*.py
  -> 12 files: _gate_pytest_plugin, _gate_process_supervisor, run_test_gate,
     probe_rpm, phantom_api_ast_helper, gen_config_reference, gen_capability_truth,
     gen_ad_ledger, diagnose_llm, check_seam_contracts,
     bf735_retire_room_workspace_rows, ad_ceiling
     (neither check_architecture_principles.py nor select_tests.py is present)

git ls-files | Select-String 'architecture_principles|arch_fitness|architecture-fitness|arch-fitness'
  -> no output
```

### 1.3 Measured category counts (live tree, today)

All measured by parsing every **git-tracked** `src/**/*.py` with `ast`, mirroring the
baseline's stated predicates (`platform-maturity-baseline-2026-08-30.md`,
"Architecture Discovery"). Small positive drift from `bf6c998` is expected and is
itself evidence the measurement method matches the baseline's.

| Category | Today | Baseline `bf6c998` |
|---|---:|---:|
| Tracked `src/**/*.py` | **915** | 908 |
| Classes with body span > 500 lines | **67** | 66 |
| Classes with > 15 direct methods | **78** | 77 |
| …**deduped unique class keys** (52 both, 15 lines-only, 26 methods-only) | **93** | — |
| `sqlite3.connect` / `aiosqlite.connect` calls | **31** (21 files) | 30 |
| `create_task` calls, broad predicate | **180** | 180 |
| `create_task`, narrowed callee **and** bare `ast.Expr` parent | **26** | 26 (broad callee) |
| External private-attribute candidates | **1,129** | 1,110 |
| Lower→higher imports, **5 ranked layers only** | **2** | "Not established" |
| …after excluding `TYPE_CHECKING` blocks | **0** | — |
| Test files using `inspect.getsource` | **125 files / 235 lines** | not measured |

Counts agree with the baseline; **set identity was not verified** for the 26.
State it that way if you cite it.

### 1.4 Two measurements that decide the design

**(a) The naive package rank is not merely imprecise — it is 100% noise at the head.**
`cross_layer_analysis.py` is a *tracked* root-level script encoding an
`ALLOWED_IMPORTS` map over 11 layers. Running it today:

```
d:/ProbOS/.venv/Scripts/python.exe cross_layer_analysis.py
  -> Found 1981 violation(s)
  -> first rows: [activation] -> [core]  activation/__init__.py:8
                   import probos.activation.task_event
```

The first reported "violation" is a package importing **its own sibling module**.
The cause: `src/probos` has **54 packages**, of which that map ranks **10**; unranked
packages fall through `ALLOWED_IMPORTS.get(src_layer, set())` to *"may import
nothing"*, so every import they make is reported. This is the concrete content of the
baseline's line "the naive package-rank scan is rejected". **Freezing 1,981 rows would
be freezing garbage.**

**(b) The domain-aware predicate independently reproduces the baseline's conclusion.**
Restricted to the five documented layers (`substrate < mesh < consensus < cognitive <
experience`, per `.github/copilot-instructions.md`), scoring only cross-layer edges and
excluding `TYPE_CHECKING` blocks: **2 raw, 0 after exclusion**, over 353 in-scope files.
That is exactly the baseline's "two initial candidates were allowed `TYPE_CHECKING` +
DI edges". The layer category therefore ships **gating with an empty frozen baseline**.

### 1.5 Measured cost (for the placement decision)

```
ast.parse of every tracked src/**/*.py   -> 915 files, 1.414 / 1.378 / 1.625 s (3 trials)
ast.parse of every tracked tests/**/*.py -> 1440 files, 1.92 s
```

Bare parsing of both trees is **~3.4 s**. Preflight is currently **15.4 s** against a
**90 s** budget. A single-pass walk with several visitors over the same trees is
affordable in preflight. This is a measured floor, not the checker's runtime — see
§7 for your obligation to measure the real figure.

---

## 2. Architect decisions (delegated authority, #1324)

These are **decided**. Implement them. Rationale is recorded here because the prompt is
the reviewed artifact; carry a condensed form into `DECISIONS.md` at commit time.

### D1 — Baseline format: committed YAML of reviewed rows, keyed by symbol identity

Ranked:

1. **(chosen) Committed YAML baseline at `docs/development/architecture-baseline.yaml`.**
   Machine-readable, diffable, one place, and it can carry the `owner` / `rationale` /
   `review_by` fields the acceptance criteria demand. It sits beside the existing
   checker data (`seams/p0-manifest.yaml`, `ad-ledger-snapshot.json`), so the
   convention already exists.
2. **Generated markdown `--check`-ed like `gen_config_reference.py`.** Rejected as the
   *authority* for two reasons: markdown is a poor carrier for structured exception
   metadata, and a regenerate-then-commit workflow trains the reflex to regenerate
   rather than review — which erases the distinction between "I fixed a violation" and
   "I added one". **Adopt its `--check` idiom for the human-readable report only.**
3. **Inline `# arch-fitness: allow(...)` pragmas.** Rejected. Three reasons, the last
   decisive: the denominator becomes invisible in aggregate, so "each decomposition
   slice must reduce its relevant denominator" is unmeasurable; recording an
   architecture decision requires editing production source, inverting AD-1270a's D6
   checker→data direction; and a pragma **is a comment the checker must read as
   behavior**, which is the program's own "Do Not Build" item.

**The crux — what identity survives refactoring.** Never a line number, never a content
hash. A line-keyed baseline churns when anything above it moves; a content hash churns
when anything *inside* the construct is edited, so fixing an unrelated line in a
600-line class would rewrite the baseline. Identity is the **enclosing named symbol
plus the semantic tuple of the violation**:

| Category | Baseline key | Frozen payload |
|---|---|---|
| `srp-size` | `<module.dotted>::<ClassName>` | which trigger(s) fired: `lines`, `methods`, or both |
| `layer-import` | `(<source module.dotted>, <imported module.dotted>)` | — (the edge is the fact) |
| `db-connect` | `<module.dotted>::<enclosing symbol>` | `callee` render + occurrence `count` |
| `unowned-task` | `<module.dotted>::<enclosing symbol>` | `callee` render + occurrence `count` |

`<enclosing symbol>` is the dotted chain of enclosing `ClassDef`/`FunctionDef`/
`AsyncFunctionDef` names, or `<module>` at module scope.

Two consequences you must implement deliberately:

- **Magnitudes are never in the baseline key or payload.** `CognitiveAgent` is frozen as
  `probos.cognitive.cognitive_agent::CognitiveAgent` with triggers `[lines, methods]` —
  **not** with `10598`. Storing the line count would rewrite the baseline on every edit
  to the file. Current magnitudes belong in the JSON report, which is not gated.
- **Occurrence `count` is payload, not key.** Collapsing to the enclosing symbol makes
  the row line-independent; carrying the count keeps a *second* `sqlite3.connect` added
  to an already-frozen function visible. Key set difference alone would miss it.

### D2 — "New violation" is decidable by symmetric set difference, with per-key count equality

Ranked:

1. **(chosen) Exact set difference, failing in both directions, plus per-key count
   equality.**
   - key in current, not in baseline → **FAIL** ("new violation").
   - key in baseline, not in current → **FAIL** ("stale baseline row; the violation is
     gone — delete the row in this commit"). This is the acceptance criterion
     "reductions update the reviewed baseline in the same commit", enforced. Without it
     the baseline rots into a list of things that used to be true.
   - key in both, `count` differs → **FAIL** in either direction, for the same reasons.
2. **Count-only.** Rejected outright: it permits fixing one violation and adding
   another with the count unchanged — precisely the program's "existing debt … may not
   be copied into a new module".
3. **Per-owner budgets.** Rejected: a budget is a hidden threshold, and the slice
   mandate is "explicit reviewed exceptions rather than hidden thresholds".

Provide `--update-baseline` to rewrite the file. It must be **impossible to reach from
the gate** (preflight passes only `--check`), and the resulting diff is the reviewed
artifact. On any failure, the error text must name the exact command and print the
exact rows to add or delete — a symmetric gate that does not tell you how to satisfy it
is a tax.

**`review_by` is required as a field and is never time-enforced.** Every `disposition:
debt` row must carry a non-empty `owner`, `rationale`, and `review_by` (an ISO date
*or* a removal condition). The checker fails when the field is **missing or blank**. It
does **not** fail because a date has passed: a gate that turns red at midnight with no
code change is non-deterministic and would break an unrelated commit. Expiry is
surfaced in the report and on stderr as a warning. Say this in the docstring so nobody
"fixes" it later.

### D3 — Four categories gate; two ship report-only with a stated promotion condition

Ranked options were: (i) all six gating, (ii) all six report-only, (iii) split by
whether the candidate set is *classifiable in this slice*. **(iii) chosen.** (i) would
require freezing 1,129 unreviewed private-access rows and 125 unreviewed test files as
"reviewed", which is a lie the format would then make permanent. (ii) forfeits the
acceptance criterion "new violations fail immediately" for four categories whose
predicates are already exact.

**GATING (frozen baseline, symmetric difference):**

| Category | Expected frozen rows | Why it can gate now |
|---|---:|---|
| `srp-size` | **93** (measured, deduped by class: 52 fire both triggers, 15 lines-only, 26 methods-only; 67 + 78 = 145 undeduped) | The predicate *is* the repository's stated review trigger. Rows carry `owner: AD-1270c` / `AD-1270d` where those ADs already own decomposition. |
| `layer-import` | **0** | Measured §1.4(b). Zero debt is the strongest possible position; any new lower→higher runtime import fails immediately. |
| `db-connect` | ~31 | Callee render is exact; the only judgement is *approved vs debt*, which the `disposition` field carries. AD-1256 owns the debt rows. |
| `unowned-task` | ~26 | The narrowed callee plus a bare `ast.Expr` parent is a genuine ownership fact: the reference is discarded at that statement. |

**REPORT-ONLY (in the JSON report, never in the gated baseline):**

| Category | Size | Promotion condition |
|---|---:|---|
| `private-access` | 1,129 broad | The program itself says AD-1270b "must classify before gating". Measured composition: **502 of 1,129 (44.5%) are dunder attributes** — `__name__` 193, `__getitem__` 107, `__init__` 75, `__len__` 35 — and the top receivers are builtins: `type()` 182, `dict` 121, `super()` 78, `list` 28, `str` 17. **Promote when** the narrowed predicate (drop dunders, drop builtin/stdlib receivers) has a reviewed classification. Emit that narrowed count in the report so the next slice knows its size. The real signal is already visible in it: `runtime._x` 185, `agent._x` 45, `rt._x` 35, `episodic_memory._x` 26. |
| `source-text-tests` | 125 files / 235 `inspect.getsource` lines | The program asks for these to be *classified* as "architectural/security invariants or candidates for behavioral replacement" — a classification deliverable, not a gate. Freezing 125 files as `unclassified` would be freezing unreviewed rows under a field named `reviewed`. **Promote when** every row carries `classification: invariant \| replace-with-behavioral`; then gate the delta so a new source-text test cannot be added silently. |

Do not pretend a report-only category is empty. See the `categories` honesty
requirement in §5.

### D4 — Runs in both preflight and a pytest currency test

Ranked: (i) preflight only, (ii) currency test only, (iii) **both**, (iv) separate
opt-in. **(iii) chosen — it is exactly what slice 1 did, and slice 1 is the house
pattern for this slice.**

- **Preflight** satisfies "new violations fail immediately": a violation fails in ~20 s
  instead of ~16 min. Insert `PhaseSpec("architecture-fitness", ...)` **after
  `seam-contracts`, before `compile`**.
- **A pytest currency test** covers the developer running focused tests without the gate
  wrapper, and is where the injected-violation tests live.
- (iv) rejected: an opt-in check is one nobody runs.

**This breaks the exact-list assertion in `tests/test_run_test_gate.py:250-256` again.**
That is a **deliberate contract update, not a regression** — update the list to
`["import-origin", "config-reference", "ad-ledger", "seam-contracts",
"architecture-fitness", "compile"]` and add the corresponding
`assert "scripts/check_architecture_principles.py" in flattened`. Say so in the commit
message. Do not weaken the assertion to a subset check; its exactness is the reason a
silently added phase is visible.

---

## 3. Pattern to copy: `scripts/check_seam_contracts.py`

Read it in full before writing a line. Mirror these idioms **exactly**:

1. **`git ls-files`, never a disk walk** — `_tracked_python_files()` (line 169). An
   untracked file must never satisfy a check: the gate materializes `HEAD` into a fresh
   worktree, so a check satisfied by uncommitted work passes locally and fails in the
   gate. That developer-local/gate seam is the defect class this program exists to
   close. Keep the same fallback shape: return `None` when git cannot answer, and
   **print a warning to stderr** naming the degradation rather than silently indexing
   nothing.
2. **AST only, never regex over source text** — `build_symbol_index()` (line 196). A
   dotted path inside a docstring or a `#` comment must not read as code. This is also
   the program's "Do Not Build" item.
3. **Accumulate every error, return a list, never fail on the first** — `validate()`
   (line 604) and its docstring: "a checker that reports one problem per run costs one
   gate cycle per problem."
4. **Skip a file that does not parse rather than dying** — `build_symbol_index()`: an
   unparseable file is the `compile` preflight phase's failure to report; duplicating
   it here produces two errors for one defect.
5. **Cache the parse.** `_INDEX_CACHE` keyed by resolved root. You walk two trees and
   run six visitors — parse once, visit many.
6. **`main()` shape** — `argparse` with `--check` / `--json PATH`, `return 1` on
   failure, and an honest-bounds section in the module docstring stating what the
   checker does **not** catch.
7. **Writes nothing under `--check`.** The gate wrapper fails the run if preflight
   mutates the tree.

For tests, copy `tests/test_ad1270b_seam_contracts.py`: `importlib.util.
spec_from_file_location` to import the script (`scripts/` is not a package), in-process
`validate()` calls against synthetic fixtures under `tmp_path`, **plus** a subprocess
test that the committed artifact passes.

---

## 4. Deliverables

| Path | Status | Contents |
|---|---|---|
| `scripts/check_architecture_principles.py` | **new** | The checker. |
| `docs/development/architecture-baseline.yaml` | **new** | Reviewed frozen rows + exceptions. |
| `tests/test_ad1270b_architecture_fitness.py` | **new** | Focused tests incl. injected violations. |
| `scripts/run_test_gate.py` | modify | Add the `architecture-fitness` `PhaseSpec`. |
| `tests/test_run_test_gate.py` | modify | Update the exact phase list (D4). |
| `DECISIONS.md` | append | Condensed D1–D4 rationale at commit time. |
| `docs/development/platform-maturity-program.md` | modify | Mark slice 2 shipped; leave slices 1/3 text intact. |

**No file under `src/probos/` may change.** `git diff --stat src/probos/` must be empty
at commit. This is AD-1270a D6: checker → data, never runtime → checker.

---

## 5. Checker specification

### 5.1 CLI

```
python scripts/check_architecture_principles.py --check
python scripts/check_architecture_principles.py --check --json report.json
python scripts/check_architecture_principles.py --update-baseline
```

`--check` validates and returns 1 on any failure, writing nothing.
`--json PATH` additionally writes the machine-readable report (acceptance criterion
"emits a machine-readable report"). Also accept `--baseline PATH`, `--src-root PATH`,
and `--tests-root PATH` so tests can point at `tmp_path` fixtures.

### 5.2 The report is a document about its own coverage

The JSON report must carry a top-level `categories` object naming every category and its
mode, so a consumer **cannot mistake an absent category for an empty one**:

```json
{
  "schema_version": 1,
  "generated_by": "scripts/check_architecture_principles.py",
  "src_root": "src",
  "categories": {
    "srp-size":          {"mode": "gating",      "current": 93,  "baseline": 93},
    "layer-import":      {"mode": "gating",      "current": 0,   "baseline": 0},
    "db-connect":        {"mode": "gating",      "current": 31,  "baseline": 31},
    "unowned-task":      {"mode": "gating",      "current": 26,  "baseline": 26},
    "private-access":    {"mode": "report-only", "current": 1129, "narrowed": 627,
                          "promotion": "classify the narrowed set"},
    "source-text-tests": {"mode": "report-only", "current": 235,
                          "promotion": "classify each row invariant|replace-with-behavioral"}
  },
  "findings": [ /* every row, every category, with file, line, magnitudes */ ],
  "errors":   [ /* the same strings printed to stderr */ ]
}
```

`findings` rows carry `file`, `line`, and magnitudes **for humans**; those fields are
never compared against the baseline (D1).

`narrowed: 627` above is illustrative arithmetic (1,129 − 502 dunders). **Measure and
emit the real narrowed figure**; do not copy that number.

### 5.3 Category predicates

Parse every **git-tracked** `src/**/*.py` (and `tests/**/*.py` for
`source-text-tests`) once.

**`srp-size`** — for each `ast.ClassDef`: body span `end_lineno - lineno + 1 > 500`, or
`> 15` direct `FunctionDef`/`AsyncFunctionDef` children of `ClassDef.body`. Nested
functions and methods of nested classes are excluded (this is the baseline's stated
rule — keep it identical or the counts stop being comparable). One row per class, with
the trigger set.

**`layer-import`** — ranks come from the **baseline YAML**, not from constants in the
checker, so adding a package to a layer is a reviewed data diff:

```yaml
layers:
  substrate: 0
  mesh: 1
  consensus: 2
  cognitive: 3
  experience: 4
```

Rules, in order:
- A module's layer is the first path segment under `probos/`. A segment absent from
  `layers` is **unranked**: it is neither a source nor a target of any rule. 44 of 54
  packages are unranked today, and that limitation must be stated in both the docstring
  and the report.
- An import is in scope only when **both** ends are ranked and the layers **differ**.
  Intra-package imports are never violations — that artifact alone accounts for the
  head of `cross_layer_analysis.py`'s 1,981.
- Violation: `rank(target) > rank(source)`.
- **Exclude any import statement lexically inside an `if TYPE_CHECKING:` block.** Detect
  the block by AST (`ast.If` whose test is `Name('TYPE_CHECKING')` or
  `Attribute(attr='TYPE_CHECKING')`) and mark its descendants, exactly as measured in
  §1.4(b). Without this the two allowed DI edges reappear as violations.
- Relative imports (`node.level > 0`) cannot cross a package boundary upward in this
  layout; skip them and say so.

Expect **0 rows**. If you measure non-zero, **stop and report it** — that contradicts
both the baseline and my independent measurement, and one of the three is wrong.

**`db-connect`** — `ast.Call` whose callee renders exactly `sqlite3.connect` or
`aiosqlite.connect`. Key by enclosing symbol; payload carries callee and count.
Approved adapter sites take `disposition: approved`; the rest take `disposition: debt,
owner: AD-1256`.

**`unowned-task`** — `ast.Call` whose callee renders as `asyncio.create_task`, or ends
in `.create_task` where the receiver chain contains `loop`, **and** whose direct parent
is `ast.Expr`. The bare-`Expr` requirement is what makes it an ownership fact rather
than syntax: `asyncio.create_task(f()).add_done_callback(g)` has an `Attribute` parent
and correctly does not match, and `t = asyncio.create_task(...)` is not an `Expr`. The
broad "any attribute named `create_task`" predicate over-matches domain store methods —
report the broad count for continuity with the baseline, gate only the narrowed set.

**`private-access` (report-only)** — the baseline predicate: `ast.Attribute` whose
`attr` starts with `_` and whose immediate receiver is not the name `self`. Emit both
the broad count and the narrowed count (drop `__dunder__` attrs; drop receivers that are
builtin calls or names such as `type`, `dict`, `list`, `str`, `super`, `cls`).

**`source-text-tests` (report-only)** — in `tests/**/*.py`: `ast.Attribute`/`ast.Call`
resolving to `inspect.getsource`, plus `read_text()` calls whose receiver expression
mentions `probos.__file__`. Row identity `tests/<path>::<enclosing test symbol>`, with
a `classification: null` placeholder.

### 5.4 Baseline schema

```yaml
schema_version: 1
baseline_id: ad-1270b-architecture-fitness-v1
owner: AD-1270b
tracking_issue: 1324
source_commit: <commit the rows were reviewed against>

layers: {substrate: 0, mesh: 1, consensus: 2, cognitive: 3, experience: 4}

gating_categories: [srp-size, layer-import, db-connect, unowned-task]
report_only_categories:
  private-access:
    reason: "1,129 broad candidates, 502 dunder; program requires classification first"
    promotion: "narrowed predicate classified and reviewed"
    owner: AD-1270b
  source-text-tests:
    reason: "125 files unclassified; freezing them as reviewed would be false"
    promotion: "every row carries classification: invariant|replace-with-behavioral"
    owner: AD-1270b

violations:
  - category: srp-size
    key: "probos.cognitive.cognitive_agent::CognitiveAgent"
    triggers: [lines, methods]
    disposition: debt
    owner: AD-1270d
    rationale: "Material god object; AD-1270d owns decomposition."
    review_by: "AD-1270d3 completion"
  - category: db-connect
    key: "probos.<module>::<symbol>"
    callee: sqlite3.connect
    count: 1
    disposition: approved
    owner: AD-1256
    rationale: "Approved connection adapter."
    review_by: "n/a — approved, not debt"
```

Validate the schema itself: unknown category, missing/blank `owner`, `rationale` or
`review_by` on a `debt` row, a `disposition` outside `{approved, debt}`, or a duplicate
`key` within a category are all failures. **Sort every emitted list deterministically**
by `(category, key)`.

---

## 6. Acceptance criteria

Program criteria for this slice, made concrete:

- [ ] `scripts/check_architecture_principles.py --check` exits 0 against the committed
      tree and baseline.
- [ ] **Deterministic on Windows and Linux.** All paths rendered POSIX
      (`Path.as_posix()`); module keys are dotted, never path-shaped. Every list sorted.
      No dict/set iteration order in output. No content hashing of source (this is a
      CRLF tree).
- [ ] **An injected-violation test per gating category — four tests, each proving the
      checker rejects it.** Build each against a synthetic `tmp_path` src root:
      - `srp-size`: a class with 501 body lines, and a class with 16 methods.
      - `layer-import`: `probos/substrate/x.py` doing `from probos.cognitive.y import Z`
        at module scope.
      - `db-connect`: a function calling `sqlite3.connect(":memory:")`.
      - `unowned-task`: a bare-statement `asyncio.create_task(f())`.
- [ ] **A negative control per gating category**, proving the predicate discriminates
      rather than always firing:
      - a 499-line class and a 15-method class do **not** fire;
      - the same `substrate → cognitive` import **inside `if TYPE_CHECKING:`** does
        **not** fire (this one is mandatory — it is the exact edge the baseline
        allowed);
      - an intra-package import does **not** fire;
      - `t = asyncio.create_task(f())` (assigned) and
        `work_store.create_task(...)` (domain method) do **not** fire.
- [ ] **Stale-row rejection is tested:** a baseline row whose violation no longer exists
      fails, with a message naming the row to delete.
- [ ] **Count-drift rejection is tested:** a frozen `db-connect` key whose occurrence
      count rises from 1 to 2 fails.
- [ ] `--json` emits the report, including the `categories` block with correct `mode`
      for all six.
- [ ] The two report-only categories appear in the report and **do not** gate; a new
      `private-access` occurrence does **not** fail the checker.
- [ ] Untracked files are invisible: a planted **untracked** `.py` containing an
      injected violation does **not** change the result. (Slice 1's review found exactly
      this defect; do not reintroduce it.)
- [ ] Preflight phase list updated and its exact-list assertion updated (D4).
- [ ] **Measure and report actual checker wall time.** Budget **≤ 8 s**; measured
      parse floor is ~3.4 s (§1.5). If you exceed 8 s, report it rather than silently
      shipping a slower preflight.
- [ ] Focused tests green:
      `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1270b_architecture_fitness.py tests/test_run_test_gate.py tests/test_ad1270b_seam_contracts.py -q -n 0 -p no:randomly`
- [ ] Preflight green:
      `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --preflight-only --label ad-1270b-slice2`
- [ ] Canonical gate green on the reviewed, committed tree:
      `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad-1270b-slice2`
      — synchronous, no terminal timeout, unique log name, receipt banked to
      `logs/gates/` and every referenced hash recomputed from the durable copies before
      push.
- [ ] `git diff --stat src/probos/` is empty.
- [ ] **Verify all changes comply with the Engineering Principles in
      `.github/copilot-instructions.md`.**

---

## 7. Do not build

- **The seam-manifest slice (AD-1270b slice 1).** Shipped in `a9bc216b`. Do not modify
  `scripts/check_seam_contracts.py`, `docs/development/seams/*.yaml`, or
  `tests/test_ad1270b_seam_contracts.py` except where §4 requires it.
- **The crossing-test closeout (AD-1270b slice 3).** Do not fill `crossing_test` node
  IDs and do not flip `--require-crossing-tests`.
- **`scripts/select_tests.py` / any impact selection.** That is AD-1270f. Absent today;
  keep it absent here.
- **Any `src/probos/` import, parse, or execution of the checker or the baseline.**
  AD-1270a D6 fixes the direction as checker → data.
- **Auto-fixing.** The checker reports and fails. It never edits production source,
  never splits a class, never rewrites an import. `--update-baseline` rewrites *only*
  the baseline file and is unreachable from the gate.
- **Comment-matching or any regex over source text as a violation predicate.** AST only.
  This is the program's own "Do Not Build" item, and it is why inline pragmas were
  rejected in D1.
- **A universal runtime message bus schema** (program constraint).
- **A replacement for domain protocols or Pydantic models** (program constraint).
- **Do not modify or delete `cross_layer_analysis.py`.** It is tracked, root-level,
  untested prior art whose output is unusable (§1.4a). Deleting a tracked file is a
  separate reviewed decision. Add one line to your docstring recording that it is
  superseded so a future reader does not trust its 1,981.
- **Do not widen the layer ranking to all 54 packages.** Ranking the other 44 is a
  design decision with no current authority, and doing it wrong is what produces 1,981
  false rows.
- **Do not promote a report-only category to gating in this slice.**

---

## 8. Risks — read before you start

1. **The untracked-file trap. This exact defect was found in slice 1's review.** The
   Builder avoided *referencing* an untracked module by hand, and review proved by
   execution that a planted untracked file still satisfied resolution. Avoiding a trap
   by hand is not the same as making it unreachable. Build the file list from
   `git ls-files` and **write the test that plants an untracked violation and proves it
   is invisible.**
2. **Windows/Linux path drift has already turned this repo's CI red.**
   `scripts/gen_config_reference.py:76-80` records it: `repr()` of a `Path` is
   `WindowsPath('data')` on Windows and `PosixPath('data')` on Linux, so "a doc
   generated on one platform is permanently stale on the other. That turned CI red three
   commits running while `--check` passed locally." My own measurement scripts printed
   `src\probos\...`. **Every path in the baseline and the report must go through
   `as_posix()`**, and module keys should be dotted, not path-shaped, so the question
   cannot arise.
3. **Do not put magnitudes in the baseline.** The single most likely way to ship a
   baseline that churns on every commit is to store `10598` next to `CognitiveAgent`.
   Triggers, not sizes. Counts only where the count is the fact (D1).
4. **Symmetric difference will fail commits that *fix* things.** That is the acceptance
   criterion, not a bug — but if the failure message does not print the exact rows to
   delete and the exact command to run, it becomes a tax that gets disabled. Spend real
   effort on the message.
5. **Do not equate syntax with ownership.** The program says AD-1270b "must classify
   retained references, callbacks, and cancellation/drain behavior instead of equating
   syntax with ownership." The bare-`Expr` requirement is the justification for calling
   the narrowed 26 "unowned". If you widen the predicate beyond that, you lose the
   justification. Any row you cannot justify this way is report-only.
6. **Subprocess pytest must neutralize `addopts`.** `pyproject.toml:196` sets
   `addopts = "-n 16 --dist=loadfile"`. Any test that shells out to pytest must pass
   `-o addopts=` or it will fork 16 workers inside a test. (Slice 1's `_collects()` hits
   this; copy its handling.)
7. **`tests/test_run_test_gate.py` will fail until you update it.** Expected (D4). Do
   not "fix" it by weakening the assertion to a subset check.
8. **The report-only categories must not read as clean.** A consumer that sees no
   `private-access` failures must be able to tell that the category was *not gated*, not
   that it was *empty*. That is what the `categories` block in §5.2 is for, and it is a
   direct application of the repository's unverified-absence rule.
9. **Report a contradiction rather than absorbing it.** If your measured `layer-import`
   count is not 0, or `srp-size` is far from 93 deduped keys, or the narrowed
   `create_task` set is not ~26 — stop and report. My numbers, the baseline's numbers, and yours should
   agree within the small drift shown in §1.3. A silent disagreement means one of the
   three predicates is wrong, and shipping it freezes the wrong thing.
