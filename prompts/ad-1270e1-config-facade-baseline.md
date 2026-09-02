# AD-1270e1 — Stable Configuration Facade Contract (characterisation slice)

**Issue:** none — already-versioned slice of [docs/development/platform-maturity-program.md](docs/development/platform-maturity-program.md) (Wave 2) · **Epic:** [#1324](https://github.com/seangalliher/ProbOS/issues/1324)
**Drafted against:** `ab37b8286f5012bf213d81748a99b610ffa3681d` (`origin/main`, `0 0` divergence at draft time)
**Mode:** Delegated AD Execution Mode active. The four decisions below are **already made**. Do not re-open them; implement them.
**AD number:** AD-1270e1 is already allocated by the program document. **Do not run `scripts/ad_ceiling.py` and do not allocate a new AD.**

Binding statement from the authority: *"Existing imports, defaults, aliases, schema, and dump order are frozen before movement."* e1 is a **characterisation** slice. It freezes the contract so e2 (leaf-domain extraction) and e3 (`SystemConfig` root extraction) can move code without silently changing behaviour. **No model moves in e1.**

---

## Read this first: four premises you will otherwise get wrong

Every number below was measured against the live tree at `ab37b828`, not recalled. Re-runnable commands are given. `$PY = d:/ProbOS/.venv/Scripts/python.exe`.

### 1. `probos.config` has no `__all__`. The public surface is 304 names, and 13 of them are import leakage.

```powershell
$env:PYTHONPATH=''; & $PY -c "import sys,types; sys.path.insert(0,r'd:\ProbOS\src'); import probos.config as C; from pydantic import BaseModel; n=[x for x in vars(C) if not x.startswith('_')]; print('__all__:',hasattr(C,'__all__'),'names:',len(n))"
```

→ `__all__: False  names: 304`. Breakdown:

| Group | Count | Notes |
|---|---:|---|
| Pydantic models | 225 | 224 defined in `probos.config`; `BaseModel` is a re-export of `pydantic.main.BaseModel` |
| Own functions | 3 | `format_trust` ([config.py:112](src/probos/config.py#L112)), `resolve_archive_db_path` ([config.py:3587](src/probos/config.py#L3587)), `load_config` ([config.py:7832](src/probos/config.py#L7832)) |
| Module-scope constants | 64 | 35 `float`, 27 `int`, 1 `frozenset` (`PROMOTION_DESTRUCTIVE_KEYWORDS`), 1 `str` (`PROMOTION_CRITICALITY_CAPTAIN_THRESHOLD`) |
| **Incidental import leakage** | **13** | `math`, `os`, `urllib`, `yaml`, `Field`, `field_validator`, `model_validator`, `AliasChoices`, `BaseModel`, `Any`, `Literal`, `Path`, `annotations` |

224 + 3 + 64 + 13 = 304. The 224 own models carry **1,784 field definitions**; `SystemConfig` alone has **192** top-level fields. **703** of 2,386 tracked `.py` files mention `probos.config` (108 under `src/`, 589 under `tests/`, 6 elsewhere) — the program's ">600" is now measured.

### 2. `a.nats is b.nats` is **False**. The reason in-process `setenv` cannot move it is not instance sharing.

You will read elsewhere that "`SystemConfig.nats` is a shared instance built at import time". The operational conclusion is right; the mechanism is not, and testing `is` identity to "prove" it will give you `False` and send you the wrong way. Measured:

```
field default object     : NatsConfig   default_factory: None
a.nats is field default  : False
a.nats is b.nats         : False
NatsConfig.model_fields['enabled'].validate_default: True
```

`validate_default=True` makes Pydantic validate the class-level default **once, at import**, when `NatsConfig()` is built as `SystemConfig.model_fields['nats'].default`. The `@field_validator(..., mode="before")` at [config.py:6123](src/probos/config.py#L6123) reads `PROBOS_NATS_ENABLED` **at that moment**. Every later `SystemConfig()` **deep-copies** that already-validated instance — new object, frozen value, validator never re-runs. So: distinct instances, and in-process `monkeypatch.setenv`/`delenv` genuinely cannot move it. **Only a fresh subprocess can.**

### 3. `model_dump(mode="json")` is **platform-dependent by value**. This exact trap has already turned CI red three commits running.

Three `Path`-valued defaults are reachable from `SystemConfig`, and they land in the JSON dump with **backslashes** on Windows:

```
naval_organization.captains_log.output_dir -> 'data\\captains_log'
naval_organization.plan_of_day.output_dir  -> 'data\\plan_of_day'
self_distillation.db_path                  -> 'data\\agent_probes.db'
backslashes present in json dump: 30
```

A raw `model_dump(mode="json")` hash baseline is **guaranteed** to differ between this host and Linux CI. [scripts/gen_config_reference.py](scripts/gen_config_reference.py) already documents this failure in `_render_value`'s docstring — *"That turned CI red three commits running while `--check` passed locally."* **Copy `_render_value`'s recursive `PurePath` → POSIX normalisation.** Top-level type is not a reliable guard; normalise inside `list`, `tuple` and `dict` too.

Separately: `model_json_schema()` emits three `PydanticJsonSchemaWarning: Default value ... is not JSON serializable; excluding default from JSON schema` for those same fields. **The schema silently drops those three defaults.** Never source defaults from the schema.

### 4. Six models are not default-instantiable, and one is not ours.

`M()` raises `ValidationError` for `A2APeerConfig`, `DutyDefinition`, `EPSDepartmentConfig`, `MCPServerConfig`, `PeerConfig`. `BaseModel.model_json_schema()` raises `PydanticUserError` ("must be called on a subclass"). Anything that reaches the baseline through `M()` or `M.model_json_schema()` must record-and-continue, never crash — and this is the first reason the frozen order is anchored on `model_fields` (Decision 1).

---

## Decision 1 — What is frozen, and in what artifact

| Option | Verdict |
|---|---|
| **(a) One committed machine-readable baseline generated by a script and `--check`-ed** | **CHOSEN** |
| (b) Golden-file snapshots per domain | Rejected — there is no domain partition today. `config_models/{core,cognition,experience,integrations,operations}` is **e2's** decision. e1 inventing it pre-commits the boundary it is supposed to be neutral about. |
| (c) Assertions inline in tests | Rejected — 1,784 field definitions are not readable as inline asserts, and a moved field then produces a *test edit* rather than a *data diff*. That is the "test pins the defect as contract" hazard from the review checklist. |

**Build `docs/development/config-facade-baseline.yaml`**, generated by `scripts/check_config_facade.py --update-baseline`, verified by `--check`. This is exactly the shape of the two shipped baselines — [architecture-baseline.yaml](docs/development/architecture-baseline.yaml) and [store-baseline.yaml](docs/development/store-baseline.yaml). Copy `store-baseline.yaml`'s header block verbatim in structure: comment banner naming the regeneration command, `schema_version`, `baseline_id`, `review: {owner, rationale, review_by}`.

Rationale for (a): e2/e3 produce large mechanical diffs. A **data** diff shows precisely which symbol, field, default or order moved. Regeneration is one command. One failure surface.

### The five dimensions, precisely

| Dimension | Captured as | Sourced from |
|---|---|---|
| **Imports** | Per public name: `kind`, `tier`. Per model additionally: `qualname`, `bases` (MRO base qualnames), `fields` (ordered tuple). Per constant: normalised value. | `vars(module)` |
| **Defaults** | Per model, per field: normalised `default`, `has_default_factory` (bool), `validate_default` | `M.model_fields[f].default` — **not** the JSON schema (premise 3), **not** an unscrubbed process (Decision 2) |
| **Aliases** | Per field carrying any alias: ordered `AliasChoices` tuple, `serialization_alias`, `alias` | `M.model_fields[f]` |
| **Schema** | Per model: `sha256` of the normalised `model_json_schema()`, plus the explicit `properties` key order | `M.model_json_schema()` |
| **Dump order** | Per model: the ordered `fields` tuple (shared with *Imports*) | `list(M.model_fields)` |

Schema is a **digest** rather than full text on purpose: 225 full schemas would be megabytes and would duplicate defaults, order and aliases, which are already explicit dimensions. The digest exists to catch what those four miss — type and constraint changes. Say this in the file header so a reader does not "improve" it into a full dump.

### Dump order — which one, and why it is the stable one

Measured across all 225 module-scope models:

```
declaration order != model_dump order          : 0   (219 instantiable models)
declaration order != schema properties order   : 0   (224 schema-able models)
model_dump() keys == model_dump(by_alias=True) : True
```

All three coincide today. **Freeze field-declaration order — `list(M.model_fields)` — and prove the other two as derived invariants at check time.** Reasons, in order of weight:

1. It needs **no instantiation**, so it covers the six models that raise on `M()` (premise 4). The other two orders cannot.
2. It needs **no environment**, so it cannot be contaminated by `PROBOS_LLM_URL` (Decision 2). `model_dump()` order requires constructing `SystemConfig()`.
3. Pydantic **derives** the other two from it — freezing the derived value instead of the source would be freezing a symptom.

So: **one stored order, three proven.** `--check` must additionally assert, for every instantiable model, `list(M().model_dump()) == stored`, and for every schema-able model, `list(M.model_json_schema()['properties']) == stored`. If those two invariants ever diverge from the stored order, that is a Pydantic-behaviour change and a hard failure, not a regeneration.

Note the distinction the program's acceptance criterion depends on: dump **order** is platform-independent; dump **values** are not (premise 3). Normalise the values; freeze the order.

---

## Decision 2 — Freezing defaults without freezing the ambient environment

This is the crux, and the place a naive baseline silently goes wrong.

| Option | Verdict |
|---|---|
| (a) Scrub known `PROBOS_*` in-process before import | Rejected — `NatsConfig.enabled` is resolved at **import** (premise 2), before any in-process scrub can act. It is also a curated denylist: a new variable walks straight past it. |
| **(b) Capture in a scrubbed subprocess; detect new readers by AST enumeration + per-variable differential** | **CHOSEN** |
| (c) AST-only declaration, reusing `check_config_profiles.env_reads_reaching_defaults` | Rejected as sufficient — it proves a read is *declared*, not that the *baseline* is environment-free, and it is pinned to one hardcoded module path (see Decision 2c). Kept as a cross-check. |

### Three gates. All three are required.

**G1 — Capture.** Produce the canonical dump in a **fresh subprocess** whose environment is constructed explicitly: copy `os.environ`, delete every name matching `PROBOS_*` **and** every name G2 enumerated, then set `PYTHONPATH` to `<repo>/src` derived from `Path(__file__).resolve().parent.parent`. **Never run the capture under pytest**: [tests/conftest.py:24](tests/conftest.py#L24) is

```python
os.environ.setdefault("PROBOS_NATS_ENABLED", "false")
```

`setdefault`, not a hard assignment — so under pytest the value is **the developer's ambient variable if it is set at all**, and only `false` otherwise. That is strictly worse than a fixed override: the baseline would vary by whose shell generated it. It happens to agree with the true default today, so the defect stays invisible until either that field default changes or someone runs with `PROBOS_NATS_ENABLED=true` (which [tests/conftest.py:208](tests/conftest.py#L208) shows is a real workflow).

**G2 — Enumerate.** AST-scan the **movement-proof path set**: `src/probos/config.py` **plus `src/probos/config_models/**/*.py` if that directory exists**. Collect every literal string argument of `os.environ.get(...)`, `os.getenv(...)` and `os.environ[...]`. A **non-literal** name — variable, f-string, concatenation — is a **hard failure**: a name that cannot be enumerated cannot be proven harmless. Scanning the future path set from day one is what stops e2 from silently escaping this guard when it moves models out.

**G3 — Differential.** For each enumerated name, run one subprocess with the G1 environment **plus only that name set to a sentinel value**. Flatten both dumps to dotted paths and require the moved-path set to **exactly equal** the set declared in the baseline. Then run one **control**: a sentinel name that nothing reads, which must move **zero** paths. The control asserts the harness's own premise — if the control moves something, the differential is broken and every other row it reported is meaningless.

Measured today:

| Variable | Mechanism | Moves | Reaches defaults |
|---|---|---|---|
| `PROBOS_NATS_ENABLED` | `field_validator(mode="before")` + `validate_default=True` ([config.py:6123](src/probos/config.py#L6123)) | `{nats.enabled}` | yes |
| `PROBOS_LLM_URL` | `model_validator(mode="after")` ([config.py:221](src/probos/config.py#L221)) | `{cognitive.llm_base_url}` | yes |
| `XDG_DATA_HOME` | module-level function `resolve_archive_db_path` ([config.py:3587](src/probos/config.py#L3587)) | `{}` | **no** |
| *(control)* | — | `{}` | — |

**Honest caveat you must carry into the code comment.** The `XDG_DATA_HOME` measurement of zero was taken on Windows, where `resolve_archive_db_path` takes the `sys.platform == "win32"` branch and the XDG line is **unreachable**. That measurement therefore does not discriminate. The load-bearing reason it is zero is **structural**: the read sits in a module-level *function*, not a validator and not a `default_factory`, so it cannot reach a `SystemConfig()` default on any platform. Record it with `reaches_defaults: false`, `mechanism: module-function`, and **still run it through G3** so the claim is re-proved on Linux CI rather than assumed.

### How a third environment-reading validator is caught

Three doors, all closed:

- **New literal name** → G2 finds it → no row in the baseline → **fails on day one**.
- **Already-declared name, widened blast radius** → G3's exact-set comparison fails.
- **Computed name** → G2's non-literal rule fails.

This is the property that makes (b) beat (a). Write it into the baseline header.

### Decision 2c — the cross-check, and the e2 hand-off

[scripts/check_config_profiles.py](scripts/check_config_profiles.py) already ships `env_reads_reaching_defaults(config_module: Path)` ([L401](scripts/check_config_profiles.py#L401)), keyed on validator **kind** rather than `validate_default` for exactly the `PROBOS_LLM_URL` reason. **Do not rewrite it and do not duplicate its logic.** Instead:

- Add one test asserting that, for `src/probos/config.py` today, your G2 enumeration and `env_reads_reaching_defaults` **agree** on the set of names that reach defaults. Two independent instruments agreeing is the evidence; one instrument is an assumption.
- `_DEFAULT_CONFIG_MODULE` at [check_config_profiles.py:81](scripts/check_config_profiles.py#L81) is pinned to `src/probos/config.py`. **After e2 moves models, that scan goes blind and its real→declared gate silently passes.** Fixing it is e2's job, not yours. Your job is to make e2 unable to forget: add a **tripwire test** that fails the moment `src/probos/config_models/` exists while `check_config_profiles._DEFAULT_CONFIG_MODULE` still resolves to a single file. Record the obligation in a `handoff_to_e2:` block in the baseline.

---

## Decision 3 — What "public import surface" means concretely

| Option | Verdict |
|---|---|
| (a) Freeze only names a consumer imports today (grep the 703 files) | Rejected — `from probos.config import X` is not the only reachable form (`config.X`, `getattr`, `importlib`), and downstream overlays that import this package live outside this repository entirely, so no grep here can see them. A grep-derived allowlist under-freezes exactly where our visibility stops. |
| (b) Freeze all 304 uniformly | Rejected — this makes `import math` a permanent public API of the facade, and would block e3's *"thin permanent facade with no domain model bodies"* if read literally. |
| **(c) Freeze all 304, tiered** | **CHOSEN** |

**Two tiers:**

- `tier: owned` — the 291 names that are ProbOS's contract (224 models, 3 functions, 64 constants). Removal, kind change, MRO change or field-tuple change is a **hard failure**.
- `tier: incidental` — the 13 import leaks. They are **recorded so nothing is invisible**, but removing one is a reviewable decision (the diff shows it), not a contract break. Mark them `removable_in: e3`.

### Existence is not the contract — identity and type are

Per model, record `qualname`, `bases` (MRO base qualnames), and `fields` (ordered tuple).

- A **re-export** after e2 — `from probos.config_models.experience import SensoriumConfig` — preserves all three, because it is the *same class object*.
- A **re-implementation** — a wrapper, a subclass, `pydantic.create_model` — breaks `bases` or `fields`.

That difference is precisely what e2 could otherwise ship silently while every `from probos.config import SensoriumConfig` still resolved. `isinstance` and subclass consumers would break; a name-only check would not notice.

### Aliases: the invariant, and what happens if it is violated

Enumerated across all 225 models: **exactly one** field carries any alias —

```
SensoriumConfig.warning_chars  AliasChoices('warning_chars', 'token_budget_warning')
```

— with `serialization_alias=None` and `alias=None`. Both spellings are accepted today (measured: `warning_chars=12345` → 12345; `token_budget_warning=54321` → 54321), because `AliasChoices` lists the field name itself. **Zero** fields have an accepted-name set that excludes the field name. Also measured: **zero** of the 225 models have a non-empty `model_config` — so `populate_by_name` is off everywhere and Pydantic's default `extra='ignore'` applies at **every** level.

**What happens if such a field appears:** with `populate_by_name` off and `extra='ignore'`, passing the **field name** would no longer match the alias, would be swallowed as an unknown key **with no error**, and the field would take its default. An existing `config/system.yaml` key would silently stop working. Therefore treat *"a field's accepted-name set does not contain the field name"* as a **hard `--check` failure**, not a recorded fact. Say why in the message.

### Mutable-default independence

Measured across two `SystemConfig()` instances: **0** shared nested model instances and **0** shared mutable containers, walked to depth 6. The property the program asks for already holds — assert it, do not fix it.

---

## Decision 4 — Where the check runs, and the bail-out threshold

**Measured cost** (`$PY`, three runs each):

| Step | Cost |
|---|---:|
| `import probos.config` | 299 ms |
| Introspect all 225 models (`model_fields` + `model_json_schema`) | 139 ms |
| `SystemConfig()` → JSON | 2 ms |
| One scrubbed dump **subprocess** (cold interpreter + import + dump) | **386 ms** (389 / 386 / 383) |
| Differential: 1 canonical + 3 declared + 1 control = 5 subprocesses | ≈ 1.93 s |
| Checker's own interpreter start | ≈ 100 ms |
| **Total** | **≈ 2.5 s** |

Preflight today is **8 phases at ~34.5 s** of a **90 s** budget — ~55 s headroom. 2.5 s is 2.8% of budget.

| Option | Verdict |
|---|---|
| (a) Preflight phase only | Chosen for the contract itself |
| (b) Pytest currency test only | Rejected as primary — `src/probos/config.py` is already a `BLAST_RADIUS_PATTERNS` entry ([select_tests.py:183](scripts/select_tests.py#L183)), so a config change selects the full suite and the test *would* always run; but it only fails **inside** the 15–19 min gate. e2/e3 are explicitly *"domain batches, not one sweep"* — many commits, each paying 18 minutes to learn about a facade break. |
| **(c) Both, split by cost** | **CHOSEN** |

- **Preflight phase `config-facade`** runs `scripts/check_config_facade.py --check` — the whole contract, ≈2.5 s. Insert it **after `config-profiles` and before `ad-ledger`**, keeping the config phases adjacent.
- **`tests/test_config_facade_baseline.py`** does **not** re-run the whole check. It covers: the baseline parses and carries `schema_version` / `baseline_id` / `review`; the checker is registered as a preflight phase; the G2↔`check_config_profiles` agreement; the `config_models` tripwires; and unit tests for the checker's own helpers (normalisation, flatten, alias rule, tiering). Keeping the expensive work out of a 26k-node suite that runs it under `-n 16` matters.

**Hard bail-out threshold.** The checker self-times and `--check` **fails with an explicit message** if its own wall time exceeds **6.0 s** (2.4× measured, room for a slower CI host). Separately: after wiring the phase, measure the preflight total. **If it exceeds 45 s, do not ship the phase** — move the check to a pytest currency test, revert the `_preflight_specs` and `test_run_test_gate.py` edits, and say so in the commit. That is a stop rule, not an aspiration.

---

## What to build

Four files. Nothing else.

### 1. `scripts/check_config_facade.py` (new)

Read-only, offline, accumulating — copy the structure of [scripts/check_store_registry.py](scripts/check_store_registry.py) and [scripts/check_config_profiles.py](scripts/check_config_profiles.py):

- Module docstring stating each gate and **why**, in the style of `check_config_profiles.py`'s docstring. Include the premise-2 mechanism and the premise-3 platform trap — the next reader must not have to rediscover them.
- `argparse` with `--check` and `--update-baseline`, mutually exclusive in effect.
- `_REPO_ROOT = Path(__file__).resolve().parent.parent`; `sys.path.insert(0, str(_REPO_ROOT / "src"))`. **Every path derived from `__file__`. Never hardcode `d:\ProbOS`** — preflight runs in a materialized *linked worktree*, not the primary checkout.
- Subprocess children get `PYTHONPATH=str(_REPO_ROOT / "src")` in an explicitly-built env dict.
- **Accumulate every error and report them all in one run.** One exit code, many lines.
- `--check` exits non-zero on any drift; `--update-baseline` rewrites the YAML and exits 0.
- Nothing under `src/probos/` may import this module — the direction is checker → data.

### 2. `docs/development/config-facade-baseline.yaml` (new, generated)

Header banner + `schema_version: 1` + `baseline_id: ad-1270e1-config-facade-v1` + `review: {owner, rationale, review_by}` + `handoff_to_e2:` + the five dimensions + `environment:` (the G2/G3 rows). Follow [store-baseline.yaml](docs/development/store-baseline.yaml) for the header shape.

### 3. `tests/test_config_facade_baseline.py` (new)

**≥ 22 tests.** Every public helper needs happy path + error/edge per the testing standards. Must include, named explicitly:

- normalisation renders `PurePath` as POSIX **recursively** through `list`, `tuple`, `dict`
- the six non-instantiable models are recorded, not crashed on
- `BaseModel`'s `model_json_schema()` failure is recorded, not crashed on
- a synthetic model whose `validation_alias` excludes its field name **fails** the alias rule
- a synthetic model with non-empty `model_config` is reported (today: zero)
- G2 rejects a **non-literal** `os.environ.get(...)` argument
- G2 enumeration agrees with `check_config_profiles.env_reads_reaching_defaults` for `src/probos/config.py`
- the differential **control** row moves zero paths
- tripwire: `config_models/` existing while `check_config_profiles._DEFAULT_CONFIG_MODULE` is a single file → fail
- tripwire: `config_models/` existing while `select_tests.BLAST_RADIUS_PATTERNS` has no matching pattern → fail
- `--check` is green on the committed baseline
- a mutated in-memory surface (dropped symbol / changed base / reordered fields) → `--check` red, one distinct message each

### 4. `scripts/run_test_gate.py` + `tests/test_run_test_gate.py` (modify)

Add `PhaseSpec("config-facade", [python, "-P", "scripts/check_config_facade.py", "--check"])` to `_preflight_specs` ([run_test_gate.py:1079](scripts/run_test_gate.py#L1079)) between `config-profiles` and `ad-ledger`. Then update the **exact-list assertion** in `test_preflight_contains_import_origin_generated_and_compile_checks` ([tests/test_run_test_gate.py:250](tests/test_run_test_gate.py#L250)) — the list goes from 8 entries to 9. Add `"scripts/check_config_facade.py" in flattened` alongside the existing three.

---

## Acceptance criteria

1. `$PY scripts/check_config_facade.py --check` exits **0** on the committed tree, in **< 6.0 s**.
2. `$PY scripts/check_config_facade.py --update-baseline` is **idempotent** — running it twice leaves the file byte-identical, and running it on a clean tree produces no diff.
3. The baseline records, for the surface measured above: **304** public names (291 `owned`, 13 `incidental`), **224** own models, **1,784** field definitions, **1** aliased field, **3** environment rows plus a control. If your generator disagrees with any of these, **stop and reconcile before proceeding** — a mismatch means one of us measured wrong, and it is not automatically me.
4. `--check` fails, with a distinct message each, for: a removed `owned` symbol; a changed model MRO; a reordered field tuple; a changed default; a changed schema digest; an alias whose accepted names exclude the field name; a new undeclared environment read; a non-literal environment read; a differential whose moved-path set differs from the declared set; a control row that moves anything.
5. Derived-invariant assertions hold: for all instantiable models `list(M().model_dump()) == stored order`; for all schema-able models `list(M.model_json_schema()['properties']) == stored order`.
6. **≥ 22** new tests in `tests/test_config_facade_baseline.py`, all green.
7. `tests/test_run_test_gate.py` exact-list assertion updated to 9 phases and green.
8. Measured preflight total after the change is reported in the commit message and is **< 45 s**. If not, apply the bail-out in Decision 4.
9. No file under `src/probos/` changes. No file under `config/` changes.
10. Focused gate green: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_config_facade_baseline.py tests/test_run_test_gate.py tests/test_config.py tests/test_config_reference_current.py -q -n 0 -p no:randomly`
11. **Predict the full-gate node total before running it and reconcile on the TOTAL** (`passed + skipped + failed + errors`), not passed-only. The last banked receipt is `ab37b828` at **26,659** — read the actual number from `d:\ProbOS\logs\gates\pr-release.receipt.json` rather than trusting this line. Expected delta: **+22 to +26**.
12. Adversarial `Diff Reviewer` on the staged diff, with a **different model than wrote the code**, before commit. Round 2 on the repair is not optional.
13. Verify all changes comply with the Engineering Principles in [.github/copilot-instructions.md](.github/copilot-instructions.md).

---

## Do not build

- **Any code movement.** No model, function or constant leaves `src/probos/config.py`. That is e2 and e3. Creating `src/probos/config_models/` in this slice is out of scope — it does not exist today (`file_search src/probos/config_models/**` → no files).
- **Any change to a default, an alias, a field name, a field order, or a validator.** e1 *characterises*. If you find a default you believe is wrong, record it and file it; do not fix it here.
- **Any edit to `config/system.yaml`, `config/node-1.yaml`, `config/node-2.yaml`,** or anything under `config/profiles/`. The authority states plainly: *"No edit to `config/system.yaml` is needed to complete the extraction."*
- **Any edit to `docs/development/architecture-baseline.yaml` or `docs/development/store-baseline.yaml`.** They belong to AD-1270b and AD-1256.
- **A baseline that captures ambient environment.** No `SystemConfig()` snapshot taken in the parent process, under pytest, or in any process whose env was not explicitly rebuilt. This is Decision 2 and it is the single most likely way to ship a wrong artifact that looks right.
- **A raw `model_dump(mode="json")` hash without POSIX normalisation.** Premise 3.
- **Any edit to `scripts/select_tests.py`.** `SELECTOR_SELF_PATTERNS` ([select_tests.py:202](scripts/select_tests.py#L202)) declares that *"changing the selector, its map, its ledger, or its own tests invalidates any claim the selector makes about that same tree."* Adding a `config_models` pattern would spend selector shadow-run budget to protect a directory that does not exist. e2 creates the directory and adds the pattern in the same commit; e1 leaves the **tripwire test** so e2 cannot forget.
- **Any rewrite of `scripts/check_config_profiles.py`.** Cross-check it; do not absorb it.
- **A new configuration format, flag cleanup, or "everything on" profile** (the authority's own Do-Not-Build list).
- **A new AD number.** AD-1270e1 is already allocated.

---

## Risks the Builder must be warned about

| # | Risk | Control |
|---|---|---|
| 1 | **Platform-dependent `Path` values** silently make the baseline Windows-only. 30 backslashes measured. Green locally, red on Linux CI — the exact failure `gen_config_reference.py` was patched for. | Recursive `PurePath` → POSIX normalisation, copied from `_render_value`. Add a test that a `dict[str, list[Path]]` normalises. |
| 2 | **Testing `a.nats is b.nats` to "prove" instance sharing returns `False`** and points you away from the real mechanism. | Premise 2. Prove environment behaviour by **subprocess differential** only. |
| 3 | **Hardcoded `d:\ProbOS\src`.** Preflight runs in a materialized linked worktree; a hardcoded path silently validates the *wrong tree* and passes. | Everything from `Path(__file__).resolve().parent.parent`. Add a test that runs the checker from a copied directory. |
| 4 | **Capture run under pytest** bakes `conftest`'s `PROBOS_NATS_ENABLED` into the baseline. Because line 24 is `setdefault`, the baked value is *the generating developer's ambient variable*, not a fixed `false` — so the artifact would vary by whose machine produced it. It agrees with the true default *today*, so the defect is invisible until the default changes or someone runs with the variable set. | G1's explicit env rebuild. Assert in a test that the capture subprocess env contains **no** `PROBOS_*` name. |
| 5 | **Sourcing defaults from `model_json_schema()`** silently loses three `Path` defaults (measured: three `PydanticJsonSchemaWarning`s). | Defaults come from `model_fields` only. Schema is a digest, nothing more. |
| 6 | **A secret is in the ambient environment.** `PROBOS_DISCORD_TOKEN` is set in the drafting shell. | Scrub `PROBOS_*` **before** the child starts. The baseline, logs and error messages carry environment variable **names only, never values** — per the logging standards. |
| 7 | **The differential proves nothing if the harness is broken.** A run that silently fails to set the variable is indistinguishable from a variable that moves nothing. | The **control row** is mandatory, and so is asserting each differential subprocess exited 0. A differential that cannot show a *known* mover (`PROBOS_NATS_ENABLED` → `nats.enabled`) has not asserted its own premise. |
| 8 | **`XDG_DATA_HOME` measuring zero does not discriminate on Windows** — that branch is unreachable here. | Keep the structural reason (module function, not validator) as the load-bearing claim; keep the row in G3 so Linux CI re-proves it. |
| 9 | **Six models raise on `M()`; `BaseModel` raises on `model_json_schema()`.** A generator that crashes on the first one produces a partial baseline that looks complete. | Record-and-continue, and assert the recorded skip list **exactly equals** the six-plus-one names. A silently-shrinking model count is the failure shape here. |
| 10 | **Preflight budget.** Eight phases at ~34.5 s of 90 s; this adds ≈2.5 s. A slower CI host, or a differential that grows a row, moves that. | 6.0 s self-timeout in the checker; 45 s preflight bail-out with a named fallback. |
| 11 | **The exact-list assertion at `test_run_test_gate.py:250` will fail before your phase runs anywhere.** | Update it in the same commit. It is 8 → 9 entries. |
| 12 | **`git add -u docs/development/`** sweeps in a concurrent session's `roadmap.md`. | Stage explicit paths only. Never `-u` on a directory. |
