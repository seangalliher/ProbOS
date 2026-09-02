# AD-1270a — Migration Step 1: Capability-Truth Shadow Inventory (inventory-only)

**Status:** Ready to build
**Epic:** #1324 (AD-1270 Platform Maturity Program) — Wave 1, "AD-1270a capability truth shadow report"
**Authority:** [docs/development/platform-maturity-program.md](../docs/development/platform-maturity-program.md) § *AD-1270a — Capability Truth Ledger and Activation Receipts*
**Dependencies:** none. Does **not** depend on AD-1185, AD-1270b, or AD-1265/1266.
**AD number:** AD-1270a is already allocated by #1324. **Do not allocate a new AD number for this work.**
**Estimated tests:** ~26 new tests in one new file.

---

## 1. Problem

ProbOS has several incompatible meanings for "available." A class may exist, a
config flag may be enabled, a tool may be advertised in the catalog, and a
runtime may report a healthy default without any production request ever having
exercised the path. Those four facts are recorded nowhere together, so nothing
can currently tell the difference between *shipped* and *working*. That is the
root of the "built, tested, inert" defect family this program exists to close.

Nothing exists yet. Verified absence (see § 12):

- `src/probos/maturity/` does not exist; no `probos.maturity` reference anywhere in `src/` or `tests/`.
- No `capability_truth` / `CapabilityTruth` symbol anywhere in `src/` or `tests/`.

## 2. Solution

Add a **leaf, observation-only** package `src/probos/maturity/` holding the truth
model and a pure resolver, plus **static declaration modules beside each owning
subsystem**, plus one `scripts/` generator that renders a committed, `--check`-able
inventory document.

The resolver reads three *different* real authorities so the truth dimensions
cannot collapse into one another, and honestly reports `unknown` for the three
dimensions this slice cannot observe (`activated`, `exercise`, `health`).

**This slice changes zero production call sites.** No route, no startup hook, no
runtime import of the maturity package.

### 2.1 Chosen design and why

Three candidate shapes were considered:

| # | Shape | Verdict |
|---|---|---|
| 1 | **Hybrid — static declarations beside each owner; the registry only *resolves* them against live authorities.** | **CHOSEN** |
| 2 | Pull-based reader that projects the existing catalog on demand, with no declarations. | Rejected |
| 3 | Declaration registry that subsystems `register()` into at import/startup. | Rejected |

**Why #1 wins.** It is the only shape that satisfies both halves of the binding
constraint. Declarations are *new data files*, not calls into existing code, so
slice 1 lands with zero production call-site edits. And because every row is
keyed by a stable declaration `id`, slices 2 and 3 attach activation and exercise
receipts by **supplying a `ReceiptSource` to the existing resolver entry point** —
no field is added, removed, or retyped, so there is no schema break (§ 4.4).

**Why #2 loses.** If rows come only from the live catalog then everything
enumerated is by definition advertised, and the report structurally cannot
express *present but not advertised* — which is precisely the inert-capability
case the AD exists to surface. It collapses `present`/`configured`/`advertised`
into a single fact and fails the acceptance criterion that disabled and
activated-but-unexercised states be representable and tested.

**Why #3 loses.** Registration calls are production call-site changes in slice 1,
which the slice forbids; the resulting object holds mutable runtime state keyed by
capability, which is literally the "second runtime registry" in the AD's
**Do Not Build** list; and import-time registration makes the inventory depend on
import order, which is neither deterministic nor `--check`-able.

Ranking rationale across the required axes: #1 leads on correctness (only shape
that keeps the four dimensions orthogonal), safety (no runtime coupling, no
mutable state), compatibility (no call-site edits), architectural fit (`model.py`
is a zero-dependency leaf; `registry.py`/`report.py` are consumed only by a
script and tests, so no layer is inverted), reversibility (delete three files, one
script, one doc, N declaration modules — nothing else references them), and
validation cost (fully hermetic; no runtime boot, no network, no clock).

### 2.2 Where it is invoked from, and the output artifact

**Invoked from `scripts/gen_capability_truth.py` only.** Not an API route (the AD
forbids an operator API in this AD and the slice forbids any API effect), and not
a startup hook (a startup hook is a production call-site change and would make the
ledger observable to — and therefore capable of influencing — boot ordering, which
the AD forbids: *"changes no routing, permission, trust, or startup decision"*). A
`scripts/` generator is also the shape the repository already uses for exactly this
job, so the pattern, the `--check` contract, and the currency test are all
established and copyable rather than invented.

**Artifact:** `docs/development/capability-truth-inventory.md`, committed and
regenerated, following `scripts/gen_config_reference.py` byte-for-byte in
structure. **Yes, it is `--check`-able**, and a currency test runs `--check` in the
ordinary suite (§ 6.4), exactly as `tests/test_config_reference_current.py` does for
the config reference.

`--json <path>` additionally writes the machine-readable row set. Nothing writes
into `data/` and nothing is committed from `--json`.

The generator runs **offline**: it never constructs a runtime. That keeps `--check`
hermetic and deterministic, which is the whole value of a committed artifact. The
consequence is honest and visible in the document: with no runtime attached,
`advertised` is `unknown` for every row and the resolver records why. The advertised
axis is still genuinely wired — `report.py` calls the real
`routers.tools.list_capability_catalog` and tests exercise that path with a fake
runtime (§ 6.3). Attaching a live runtime is Migration step 5's job, not this one.

### 2.3 The three authorities (they may not be the same authority)

| Field | Authority | Mechanism |
|---|---|---|
| `present` | The **Python import system over the live source tree** | `importlib.util.find_spec(owner_module)`; `None` → `FALSE`. Otherwise `import_module` then `hasattr(mod, owner_symbol)`. |
| `configured` | **`probos.config.SystemConfig`** loaded from a YAML path via `load_config` | Walk the declaration's dotted `configured_when` path over the loaded config object. |
| `advertised` | **`routers.tools.list_capability_catalog(runtime)`** | Membership of `catalog_id` among the `id` values of `catalog[catalog_axis]`. |

Source tree, config file, live runtime catalog — three distinct authorities. A
capability can therefore be `present=true, configured=false` (a shipped but
disabled subsystem) or `present=true, configured=true, advertised=false` (the
inert case), and the report shows the difference.

**Hard rule — an unresolvable input is `UNKNOWN`, never `FALSE`.** If
`configured_when` names a config path that does not exist on `SystemConfig`, that
is a broken declaration, not a disabled capability: emit `UNKNOWN` plus a
`resolution_errors` entry. Same for an owner module that raises on import. This is
the `present`/`configured` form of the AD's rule that *no exercise sample means
health is `unknown`, not `available`*.

## 3. Files

**New:**

| Path | Purpose |
|---|---|
| `src/probos/maturity/__init__.py` | Package marker + narrow public re-exports. |
| `src/probos/maturity/model.py` | Frozen dataclasses, enums, and the `ReceiptSource` protocol. **Zero `probos` imports.** |
| `src/probos/maturity/registry.py` | Declaration collection only. Holds no capability state. |
| `src/probos/maturity/report.py` | Resolver + renderers. |
| `src/probos/cognitive/maturity_declarations.py` | Declarations owned by the cognitive layer. |
| `src/probos/tools/maturity_declarations.py` | Declarations owned by the tool layer. |
| `src/probos/agents/maturity_declarations.py` | Declarations owned by the agent layer. |
| `src/probos/infrastructure/maturity_declarations.py` | Declarations owned by infrastructure. |
| `scripts/gen_capability_truth.py` | Generator, `--check`-able. |
| `docs/development/capability-truth-inventory.md` | Generated artifact (commit the generated output). |
| `tests/test_ad1270a_capability_truth.py` | All tests for this slice. |

**Modified:** none in `src/`. `pyproject.toml` needs no edit —
`[tool.setuptools.packages.find] where = ["src"]` (pyproject.toml:177-178) already
auto-discovers a new subpackage that has an `__init__.py`.

## 4. Implementation

### Section 1 — `src/probos/maturity/model.py`

Frozen, slotted dataclasses and string enums. **This module must import nothing
from `probos`** — that is what makes it a true leaf that a declaration module in
any layer may import without inverting the layer order. A test enforces it (§ 6.6).

Define:

- `class TriState(str, Enum)`: `TRUE = "true"`, `FALSE = "false"`, `UNKNOWN = "unknown"`.
  Tri-state, not `bool`, because "we did not look" and "we looked and it is not
  there" are different facts and conflating them is the defect being fixed.
- `class HealthState(str, Enum)`: `UNKNOWN`, `AVAILABLE`, `DEGRADED`, `FAILING`. Default `UNKNOWN`.
- `class LiveState(str, Enum)`: `UNKNOWN`, `INERT`, `DEGRADED`, `LIVE`.
- `ALWAYS_CONFIGURED: Final[str]` — an explicit sentinel for `configured_when`
  meaning *unconditionally part of the profile*. A declaration must opt into this
  by name; a missing/empty `configured_when` is a declaration error, not an
  implicit "always."
- `@dataclass(frozen=True, slots=True) class ExerciseRecord`:
  `attempts: int = 0`, `last_success: str | None = None`, `last_failure: str | None = None`.
  Timestamps are ISO-8601 UTC **strings**, not `datetime`, so a row round-trips
  through JSON without a timezone-rendering difference between platforms.
- `@dataclass(frozen=True, slots=True) class HealthRecord`:
  `state: HealthState = HealthState.UNKNOWN`, `observed_at: str | None = None`, `source: str | None = None`.
- `@dataclass(frozen=True, slots=True) class CapabilityDeclaration`:
  `id: str`, `title: str`, `owner_module: str`, `owner_symbol: str`,
  `configured_when: str`, `catalog_axis: str | None = None`,
  `catalog_id: str | None = None`, `seam_ids: tuple[str, ...] = ()`, `notes: str = ""`.
- `@dataclass(frozen=True, slots=True) class CapabilityRow`:
  `declaration: CapabilityDeclaration`, `present: TriState`, `configured: TriState`,
  `advertised: TriState`, `activated: TriState`, `exercise: ExerciseRecord`,
  `health: HealthRecord`, `resolution_errors: tuple[str, ...] = ()`.
- `class ReceiptSource(Protocol)` with `activation_for(capability_id: str) -> TriState`,
  `exercise_for(capability_id: str) -> ExerciseRecord`,
  `health_for(capability_id: str) -> HealthRecord`. Nothing implements it in
  production in this slice; slice 2 and slice 3 do. It is defined now so those
  slices are an argument change, not a model change.

**`live` is a `@property` on `CapabilityRow`, never a stored field.** The AD says
`live` is derived and never stored; making it a property makes storing it
structurally impossible rather than merely discouraged. Total function, evaluated
in this order:

```
1. present is FALSE or configured is FALSE or advertised is FALSE  -> INERT
2. health.state is FAILING                                          -> DEGRADED
3. health.state is DEGRADED                                         -> DEGRADED
4. exercise.last_failure and not exercise.last_success              -> DEGRADED
5. activated is not TRUE                                            -> UNKNOWN
6. exercise.attempts == 0                                           -> UNKNOWN
7. health.state is AVAILABLE                                        -> LIVE
8. otherwise                                                        -> UNKNOWN
```

Step 1 first: a positive denial on any axis beats every other signal. Steps 5-6
are the AD's core rule — **no path returns `LIVE` without both an activation fact
and at least one exercise attempt**, so in this slice `live` is never `LIVE` for
any row, and that is the finding, not a bug.

`CapabilityRow.to_dict()` emits every field plus `"live": self.live.value`.

### Section 2 — `src/probos/maturity/registry.py`

```python
class MaturityRegistry:
    def register(self, declaration: CapabilityDeclaration) -> None: ...
    def declarations(self) -> tuple[CapabilityDeclaration, ...]: ...   # sorted by id
    def get(self, capability_id: str) -> CapabilityDeclaration | None: ...
```

Duplicate `id` raises `ValueError` — a collided id would silently merge two
capabilities' evidence, which is a correctness failure, so this propagates (Tier 3
of the exception policy).

Module-level `DECLARATION_MODULES: tuple[str, ...]` lists the dotted paths of the
declaration modules, and `load_default_registry() -> MaturityRegistry` imports each
lazily and reads its `MATURITY_DECLARATIONS` tuple. Import failure of one module is
**log-and-degrade** (skip that module, `logger.warning` naming the module and what
is therefore missing from the report), because one broken declaration module must
not blank the whole inventory. `load_default_registry()` returns a **fresh**
registry each call — there is no module-level singleton, because a mutable global
keyed by capability is the "second runtime registry" the AD forbids.

`DECLARATION_MODULES` is a list of *pointers to declarations*. It holds no
capability state, has no lifecycle, and is not mutated after import. It is chosen
over filesystem globbing because globbing `src/probos/**` silently yields an empty
registry when ProbOS is installed as a wheel, and over `pkgutil.walk_packages`
because that imports every package in the tree and its side effects.

### Section 3 — declaration modules (`*/maturity_declarations.py`)

Each exposes exactly one module-level constant:

```python
MATURITY_DECLARATIONS: tuple[CapabilityDeclaration, ...] = (...)
```

**A declaration module may import only from `probos.maturity.model`** (plus
`__future__`). No importing the subsystem it declares — the declaration is data
about the owner, not a use of it, and keeping it import-free is what makes reading
the inventory cheap and side-effect-free. A test enforces this by AST-scanning the
declaration modules' imports (§ 6.6).

Build these eight declarations. Every `owner_module` / `owner_symbol` pair below
was verified against the live tree (§ 12) — use them exactly:

| id | owner_module | owner_symbol | configured_when | catalog_axis / catalog_id |
|---|---|---|---|---|
| `cognitive.intent-decomposition` | `probos.cognitive.decomposer` | `IntentDecomposer` | `ALWAYS_CONFIGURED` | — / — |
| `cognitive.episodic-memory` | `probos.cognitive.episodic` | `EpisodicMemory` | `ALWAYS_CONFIGURED` | — / — |
| `cognitive.self-modification` | `probos.cognitive.self_mod` | `SelfModificationPipeline` | `self_mod.enabled` | — / — |
| `cognitive.crew-session` | `probos.cognitive.crew_orchestrator` | `CrewOrchestrator` | `workforce.enabled` | — / — |
| `tools.governed-invocation` | `probos.tools.registry` | `ToolRegistry` | `ALWAYS_CONFIGURED` | — / — |
| `tools.code-execution` | `probos.tools.code_execution_tool` | `CodeExecutionTool` | `ALWAYS_CONFIGURED` | `tools` / `run_python` |
| `agents.http-fetch` | `probos.agents.http_fetch` | `HttpFetchAgent` | `ALWAYS_CONFIGURED` | `mesh_intents` / `http_fetch` |
| `infrastructure.snapshot-manifest` | `probos.infrastructure.snapshot_manifest` | `SnapshotManifest` | `ship_state_snapshot.enabled` | — / — |

Notes for the Builder:

- `probos.tools.code_execution_tool` and `probos.agents.http_fetch` are the two
  **catalog-bound** declarations. They are what make the `advertised` axis a real
  code path rather than a field that is always `unknown`. Confirm the exact class
  names in those two modules before writing the declaration — the `tool_id`
  (`"run_python"`, code_execution_tool.py:319) and the `IntentDescriptor(name="http_fetch")`
  (agents/http_fetch.py:68) are verified; the enclosing class names are not, so
  grep them.
- `self_mod.enabled` defaults to `False` and `ship_state_snapshot.enabled` /
  `workforce.enabled` are real fields — so the shipped inventory will contain at
  least one genuinely `configured=false` row. That is deliberate: it proves the
  `configured` axis is doing work rather than returning `true` for everything.
- Populate `seam_ids` **only where truthful** (e.g. `tools.governed-invocation`
  cross-references `TA-P0-002-tool-fault-repair`). It is a free-text cross-reference
  carried as data. **Nothing in this slice reads `p0-manifest.yaml`.** See § 5.

### Section 4 — `src/probos/maturity/report.py`

```python
async def build_rows(
    registry: MaturityRegistry,
    *,
    config: Any,
    runtime: Any | None = None,
    receipts: ReceiptSource | None = None,
) -> tuple[CapabilityRow, ...]: ...

def render_markdown(rows: Sequence[CapabilityRow]) -> str: ...
def render_json(rows: Sequence[CapabilityRow]) -> dict[str, Any]: ...
```

- `runtime=None` → `advertised = UNKNOWN` for every row, with the
  `resolution_errors` entry `"advertised: no runtime attached (offline projection)"`.
- `runtime` supplied → call `list_capability_catalog` **once** for the whole run and
  resolve every catalog-bound declaration against that single result. Import it
  function-locally (`from probos.routers.tools import list_capability_catalog`),
  matching the two established in-process call sites
  (`src/probos/tools/search_capabilities_tool.py:141`,
  `src/probos/federation/ard/catalog_projector.py:163`), so `probos.maturity` never
  pulls FastAPI at import time.
- A declaration with `catalog_axis is None` → `advertised = UNKNOWN` +
  `"advertised: no catalog binding declared"`. It must not be `FALSE`.
- `receipts=None` → `activated = UNKNOWN`, `exercise = ExerciseRecord()`,
  `health = HealthRecord()`. When supplied, each per-capability lookup is wrapped
  in `try/except` and degrades to the unknown value with a `resolution_errors`
  entry.
- Every axis resolves independently behind its own `try/except`; one failure never
  aborts the run and never raises out of `build_rows`. This mirrors
  `list_capability_catalog`'s own per-axis honest-degrade contract.

`render_markdown` **must not emit a generation timestamp, an absolute path, a
`WindowsPath`/`PosixPath` repr, or any machine-local value.** A timestamp makes
`--check` fail on every run; a path repr makes the doc current on exactly one
operating system. Both mistakes have already cost this repository red CI — see the
docstring of `test_the_doc_contains_no_platform_dependent_reprs` in
`tests/test_config_reference_current.py`. Rows render sorted by `id`.

Include a short header block in the rendered doc stating: generated, how to
regenerate, that this is observation-only, and that `advertised`/`activated`/
`exercise`/`health` are `unknown` in this slice **because migration steps 2 and 3
have not landed** — so a reader does not misread `unknown` as broken.

### Section 5 — `scripts/gen_capability_truth.py`

Copy the shape of `scripts/gen_config_reference.py` exactly: module docstring with
a `Usage::` block, `_REPO_ROOT`, `_OUTPUT`, `render()`, `main() -> int`,
`raise SystemExit(main())`.

- `--check` → exit `1` with a `STALE:` message naming the regeneration command when
  the committed doc differs; exit `0` and print a one-line confirmation otherwise.
- `--json PATH` → write `render_json(rows)`.
- `--config PATH` → default `config/system.yaml`; loaded with
  `probos.config.load_config` (config.py:7832), which already returns a default
  `SystemConfig()` for a missing file.
- Drive the async resolver with `asyncio.run(...)`.
- The script constructs **no runtime** and passes `runtime=None`.

## 5. Relationship to the P0 seam manifest — deliberately NOT coupled

`docs/development/seams/p0-manifest.yaml` lists **seven Tier-A seam IDs**
(`TA-P0-001..007`) plus one non-gating Tier-B ID. The program's *Initial P0
Subsystems* prose for AD-1270a lists **capabilities**. These are different
denominators: a seam is a producer→consumer *crossing*, a maturity row is a
*capability*. One capability can span several seams and one seam can involve
several capabilities.

**Slice 1 does not couple them, in either direction.** Concretely:

- No code in `src/probos/maturity/` or `scripts/gen_capability_truth.py` reads,
  parses, imports, or validates against `p0-manifest.yaml`.
- The only linkage is `CapabilityDeclaration.seam_ids`, an opaque free-text tuple
  rendered as documentation text and validated by nothing.

Reason: AD-1270b's own acceptance states *"No central code object imports or
executes the catalog"* (platform-maturity-program.md:376). A runtime-importable
`registry.py` that read the seam manifest would violate that constraint from the
other side and would make a documentation artifact load-bearing for a runtime
package. If a cross-check is wanted later it belongs in
`scripts/check_seam_contracts.py` (AD-1270b's tool, not yet written), reading the
maturity declarations as data — dependency pointing from checker to data, never
from runtime code to manifest.

## 6. Tests — `tests/test_ad1270a_capability_truth.py`

Approximately 26 tests. Every public method gets happy path + error/edge. Tests are
hermetic: no runtime boot, no network, no clock, no writes outside `tmp_path`.

### 6.1 Model and `live` derivation (~9)

- `live` is `INERT` when `present` is `FALSE`; when `configured` is `FALSE`; when `advertised` is `FALSE` (three cases).
- `live` is `UNKNOWN` when every axis is `TRUE` but `activated` is `UNKNOWN`.
- `live` is `UNKNOWN` when `activated` is `TRUE` but `exercise.attempts == 0` — *the AD's headline rule.*
- `live` is `LIVE` only with all axes `TRUE`, `activated=TRUE`, `attempts >= 1`, `health=AVAILABLE`.
- `live` is `DEGRADED` when `health=FAILING`, and when `last_failure` is set with no `last_success`.
- **`live` cannot be stored:** `CapabilityRow` has no `live` field —
  assert `"live" not in {f.name for f in dataclasses.fields(CapabilityRow)}` and that
  assigning `row.live = ...` raises `AttributeError`.
- `to_dict()` includes a `"live"` key whose value equals `row.live.value`.

### 6.2 Registry (~4)

- `load_default_registry()` returns every declared id, sorted, with no duplicates.
- Registering a duplicate id raises `ValueError`.
- A declaration module that fails to import is skipped with a warning and the other
  modules still resolve (monkeypatch `DECLARATION_MODULES` with a bogus entry).
- Two `load_default_registry()` calls return independent objects (no shared singleton).

### 6.3 Resolution — the three authorities (~8)

- `present` is `TRUE` for a declaration naming a real module+symbol.
- `present` is `FALSE` for `owner_module="probos.does_not_exist"`.
- `present` is `FALSE` for a real module with a bogus `owner_symbol`.
- `configured` is `TRUE` for `ALWAYS_CONFIGURED`.
- `configured` is `FALSE` for `self_mod.enabled` against a default `SystemConfig()`
  (verified default is `False`).
- **`configured` is `UNKNOWN`, not `FALSE`, for a `configured_when` path absent from
  `SystemConfig`, and a `resolution_errors` entry names the path.**
- `advertised` is `UNKNOWN` with `runtime=None`, and the error string says so.
- `advertised` is `TRUE`/`FALSE` correctly against the **real**
  `routers.tools.list_capability_catalog` driven by a `_FakeRuntime` stub exposing
  `tool_registry` / `registry` / `config` — one catalog-bound declaration present in
  the fake catalog, one absent. Do **not** monkeypatch `list_capability_catalog`
  itself; the point of this test is that the real function is the authority.

### 6.4 Generator and artifact currency (~4)

Mirror `tests/test_config_reference_current.py`:

- The script file exists.
- The committed doc exists.
- Running `[sys.executable, script, "--check"]` in a subprocess (`cwd=_REPO_ROOT`,
  `timeout=180`) exits `0`; failure message names the regeneration command.
- The doc contains no platform-dependent or non-deterministic token: assert none of
  `WindowsPath`, `PosixPath`, `\\Users\\`, `/home/runner`, `C:\`, or a 4-digit-year
  date pattern appears. Also assert the doc is marked "do not edit by hand" and
  names `gen_capability_truth.py`.

### 6.5 Slice-1 honesty invariants (~2)

- **Every row in the generated inventory has `live != LIVE`.** In slice 1 ProbOS
  cannot prove any capability live, and the report must say so rather than default
  to optimism. This test is expected to *change* in slice 3, and that is correct.
- At least one row has `configured == FALSE` and at least one has `configured == TRUE`
  — proof the `configured` axis discriminates instead of returning a constant.

### 6.6 Layering and forward-compatibility (~3)

- **`model.py` imports nothing from `probos`** — AST-scan its imports.
- **Declaration modules import only `probos.maturity.model`** — AST-scan every module
  in `DECLARATION_MODULES`.
- **The `ReceiptSource` seam is exercised, not merely declared.** Pass a
  `_FakeReceipts` stub returning `activated=TRUE`, `attempts=3`,
  `last_success="2026-01-01T00:00:00Z"`, `health=AVAILABLE`, and assert the row
  reports those values and `live == LIVE`. Without this test the protocol is itself
  a built-tested-inert artifact, which would be an unusually literal way to fail
  this AD.

Run focused tests with:

```
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1270a_capability_truth.py -q -n 0 -p no:randomly
```

## 7. Do not build

Named explicitly because each is one small step away and all are out of scope:

- **Activation receipts.** No startup ownership point emits anything. Migration step 2.
- **Exercise receipts.** No ingress or consumer completion point records an attempt. Migration step 3.
- **Any API route.** No `routers/` file is created or modified. No `/api/maturity`. The AD forbids a mutable operator API in this AD, and this slice forbids any API effect at all.
- **Doctor integration.** Do not register a check in `src/probos/doctor/registry.py`. Reuse of Doctor checks is migration step 5.
- **Seam-manifest coupling.** Do not read, parse, or validate against `docs/development/seams/p0-manifest.yaml`. See § 5.
- **A health engine.** No probing, no polling, no background task, no `asyncio.create_task`. `health` is a *record shape* here, not a mechanism.
- **A second capability registry.** `MaturityRegistry` holds declarations only — no capability state, no lifecycle, no runtime mutation, no global singleton.
- **A telemetry warehouse.** No persistence, no store, no database, no `data/` writes.
- **Auto-enabling anything.** Nothing reads a row to make a decision. No routing, permission, trust, or startup behaviour may consult the ledger.
- **Startup wiring.** No file under `src/probos/startup/` is touched.
- **Editing `src/probos/activation/`.** Despite the name it is the *task* activation dispatcher (`dispatcher.py`, `task_router.py`, `task_event.py`) — unrelated to capability activation. Do not put maturity code there and do not reuse the name.
- **Widening the declaration set.** Eight declarations, exactly the ones in § 4 Section 3. Enumerating more capabilities is later work.
- **Refactoring `routers/tools.py`.** `list_capability_catalog` is consumed as-is. Its signature, shape, and honest-degrade behaviour do not change.

## 8. Acceptance criteria

1. `src/probos/maturity/{__init__,model,registry,report}.py` exist; `model.py` imports nothing from `probos`.
2. Eight declarations resolve, each with a verified `owner_module` / `owner_symbol`.
3. `present`, `configured`, `advertised` each derive from a *different* authority (source tree / `SystemConfig` / `list_capability_catalog`), and an unresolvable input yields `UNKNOWN` with a `resolution_errors` entry — never `FALSE`.
4. `activated`, `exercise`, `health` are representable and honestly `unknown`/zero-valued; a `ReceiptSource` stub fills all three with no model change, proven by test.
5. `live` is a derived property with no backing field; no row in the committed artifact evaluates to `LIVE`.
6. `scripts/gen_capability_truth.py --check` exits `0` against the committed doc and `1` when stale; the currency test runs it in the ordinary suite.
7. The generated doc is byte-identical on Windows and Linux — no timestamp, no absolute path, no `Path` repr.
8. **`git diff --stat` shows zero modified files under `src/probos/` outside the new `maturity/` package and the four new `maturity_declarations.py` files.** No route, no startup hook, no runtime import of `probos.maturity`.
9. Nothing reads `docs/development/seams/p0-manifest.yaml`.
10. ~26 new tests pass; full suite green with no new failures.
11. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 9. Tracking

- `PROGRESS.md` — add the AD-1270a slice-1 entry with the new file list and test count.
- `docs/development/platform-maturity-program.md` — Wave 1 checklist: mark "AD-1270a capability truth shadow report" delivered; note steps 2-5 remain open.
- `DECISIONS.md` — one entry recording the hybrid declaration design, the offline-generator choice, and the deliberate non-coupling to `p0-manifest.yaml`.
- GitHub #1324 — check the corresponding Wave 1 box; the epic stays open.
- **Do not allocate a new AD number.**

## 10. Gate and review

1. Focused tests (§ 6) green.
2. `Diff Reviewer` subagent on the staged diff, with a different model than the author. Frame it as: *does this slice change any production behaviour, and can slice 2 attach receipts without editing `model.py`?*
3. Repair findings, commit locally.
4. `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --preflight-only --label ad-1270a`, repair, commit.
5. `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad-1270a` — synchronous, no terminal timeout. ~15-19 min; it sits at `[ 99%]` for several minutes, which is normal.

## 11. Risks the Builder must be warned about

1. **A generation timestamp in the artifact makes `--check` fail on every run.** The most likely single cause of a red suite here. Render no clock value of any kind.
2. **`present` requires importing the owner module, and an import can have side effects.** Use `find_spec` first so a missing module never triggers an import, and wrap the import in `try/except` → `UNKNOWN` + error rather than letting a heavy module take the generator down.
3. **`src/probos/activation/` is a name trap** — it is task dispatch, not capability activation. Do not extend it.
4. **`memory` has no `enabled` field.** `memory.enabled`, `consensus.enabled`, and `crew.enabled` were checked and do **not** resolve on `SystemConfig`. Only use the predicates in § 4 Section 3; if a new one is needed, verify it resolves before writing it, or the row silently becomes `UNKNOWN`.
5. **Do not monkeypatch `list_capability_catalog` in the advertised test.** Patching it would make the test pass while proving nothing about the real authority — the exact producer-proved/consumer-proved half-chain this program exists to eliminate. Build a fake *runtime* and let the real function run.
6. **The tri-state is load-bearing.** If any axis is typed `bool`, "not looked at" collapses into "absent" and the ledger starts lying in the same way the current system does.
7. **Declaration modules importing their owner** would make the inventory expensive and side-effecting and would invert the layer order. Data only.
8. **Class names in the two catalog-bound declarations are unverified.** `run_python` (code_execution_tool.py:319) and `IntentDescriptor(name="http_fetch")` (agents/http_fetch.py:68) are verified; the enclosing class names are not. Grep them before writing, do not assume `CodeExecutionTool` / `HttpFetchAgent`.

## 12. Verified against codebase (2026-09-01)

Absence claims — enumerations actually run:

```
CLAIM: src/probos/maturity/ does not exist and nothing references it
RUN:   Get-ChildItem src\probos -Directory   +
       Select-String -Path (Get-ChildItem src,tests -Recurse -Filter *.py) `
         -Pattern 'probos\.maturity|capability_truth|CapabilityTruth' -List
FOUND: no 'maturity' directory among the 55 subpackages of src/probos;
       'NONE: no probos.maturity / capability_truth / CapabilityTruth in src or tests'
HOLDS: yes

CLAIM: no scripts/ generator boots a runtime except diagnose_llm.py
RUN:   Select-String -Path scripts\*.py -Pattern 'ProbOSRuntime|build_runtime|create_runtime' -List
FOUND: scripts\diagnose_llm.py:99 (from probos.runtime import ProbOSRuntime);
       scripts\phantom_api_ast_helper.py:1042 (def build_runtime_attr_index — AST, not a runtime)
HOLDS: yes

CLAIM: memory/consensus/crew have no `.enabled` config field
RUN:   python -c "... getattr walk over SystemConfig() for six candidate paths ..."
FOUND: self_mod.enabled -> False resolvable=True; mcp.enabled -> True resolvable=True;
       archive.enabled -> True resolvable=True;
       memory.enabled / consensus.enabled / crew.enabled -> resolvable=False
HOLDS: yes
```

Existence claims:

```
grep -n "class IntentDecomposer" src/probos/cognitive/decomposer.py
  246: class IntentDecomposer:
grep -n "class EpisodicMemory" src/probos/cognitive/episodic.py
  1180: class EpisodicMemory:
grep -n "class SelfModificationPipeline" src/probos/cognitive/self_mod.py
  47: class SelfModificationPipeline:
grep -n "class CrewOrchestrator" src/probos/cognitive/crew_orchestrator.py
  89: class CrewOrchestrator:
grep -n "class ToolRegistry" src/probos/tools/registry.py
  66: class ToolRegistry:
grep -n "class SnapshotManifest" src/probos/infrastructure/snapshot_manifest.py
  181: class SnapshotManifest:
grep -n "return \"run_python\"" src/probos/tools/code_execution_tool.py
  319:        return "run_python"          (property tool_id at :318)
grep -n 'name="http_fetch"' src/probos/agents/http_fetch.py
  68:        IntentDescriptor(name="http_fetch", params={"url": "<url>", ...})

grep -n "async def list_capability_catalog" src/probos/routers/tools.py
  44: async def list_capability_catalog(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
      returns {"tools","skills","mesh_intents","mcp_servers","counts"};
      tool rows key on "id"; mesh_intent rows key on "id" and carry no held_by/domain
grep -n "list_capability_catalog" src/probos/tools/search_capabilities_tool.py
  141: catalog = await list_capability_catalog(self._runtime)      (function-local import above it)
grep -n "list_capability_catalog" src/probos/federation/ard/catalog_projector.py
  163: locker = await list_capability_catalog(runtime)              (function-local import above it)
grep -n "def _mesh_intents" src/probos/routers/agents.py
  1198: def _mesh_intents(runtime: Any) -> list[dict[str, Any]]:    (rows: id,name,description,
        usage_hint,requires_consensus,tier,origin,reachable — no held_by, no domain)

grep -n "def load_config" src/probos/config.py
  7832: def load_config(path: str | Path) -> SystemConfig:          (missing file -> SystemConfig())
grep -n "class SystemConfig" src/probos/config.py
  7590: class SystemConfig(BaseModel):                              (192 top-level fields)
grep -n "packages.find" pyproject.toml
  177: [tool.setuptools.packages.find]
  178: where = ["src"]

grep -n '"--check"' scripts/gen_config_reference.py
  188:        "--check",                                            (pattern to copy)
grep -n '"--check"' scripts/run_test_gate.py
  695                                                                (AD-1270f Slice 0, 6fcde788)
ls tests/test_config_reference_current.py                            (currency-test pattern to copy)

grep -n "No central code object" docs/development/platform-maturity-program.md
  376: - No central code object imports or executes the catalog.    (AD-1270b acceptance; § 5)
docs/development/seams/p0-manifest.yaml                              (TA-P0-001..007, TB-P0-001, tombstones: [])

ls src/probos/doctor/     -> __init__.py, protocol.py, registry.py, runner.py   (do not touch)
ls src/probos/activation/ -> __init__.py, dispatcher.py, task_event.py, task_router.py
                             (task dispatch, NOT capability activation — name trap)
```
