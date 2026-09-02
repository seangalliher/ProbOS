# AD-1270e2 — Leaf-Domain Config Extraction (Batch 1: `core`)

Create `src/probos/config_models/` and move eight self-contained leaf models out of `config.py` into `config_models/core.py`, re-exported so every existing import keeps working. This is the first of five domain batches; it is deliberately the smallest one, because it is the batch that must prove the mechanism.

**Status:** Ready · **Depends on:** AD-1270e1 (`c6a4dc25`, `37b1c7d6`) · **Epic:** #1324 · **Estimated tests:** 14–18 new

---

## Scope Authority

`docs/development/platform-maturity-program.md` §"AD-1270e2 — Leaf-Domain Extraction" (line 508) is the scope owner. It says, verbatim:

- Move leaf models in bounded batches into `config_models/{core,cognition,experience,integrations,operations}.py`.
- Re-export each class from `probos.config` before moving the next batch.
- Run focused importer/config tests and the affected supported-profile smoke after each batch.

Line 778 adds: *"AD-1270e2/e3 by domain batches, not one sweep."*

This prompt is **batch 1 of 5**: `core.py` only. `config.py` has **224 owned models across 7,842 lines**; 204 of them reference no other config model. Moving all 204 in one commit is the thing the program explicitly forbids. Batches 2–5 (`cognition`, `experience`, `integrations`, `operations`) are separate builds under the same AD number and are **not in scope here**.

---

## Problem

`config.py` is a 7,842-line module that is simultaneously the domain-model store, the root composition, and the permanent public import surface for 600+ files. AD-1270e1 froze that public surface so a move can be *checked*; it moved nothing. Until a first batch actually lands, the facade baseline is a contract with no counterparty and the two tripwires e1 installed have never fired.

---

## Solution

Create the package, move eight provably self-contained models, re-export them, and satisfy both tripwires **in the same commit**.

### Why these eight

Each was verified to reference **no other config model** and **no module-level helper, constant, or enum** in `config.py`. Their only free names are imports (`BaseModel`, `Field`, `Any`, `field_validator`, `math`) plus validator-local variables. Each is referenced in exactly two places: its own definition and its `SystemConfig` field.

| Model | Current lines | `SystemConfig` field | Non-import deps |
|---|---|---|---|
| `SystemInfo` | 6034–6039 | `system:` (7593) | none |
| `PoolConfig` | 117–140 | `pools:` (7594) | none |
| `MeshConfig` | 143–182 | `mesh:` (7595) | `math`, `field_validator`, `Any` |
| `ConsensusConfig` | 185–195 | `consensus:` (7596) | none |
| `ScalingConfig` | 1430–1440 | `scaling:` (7602) | none |
| `CircuitBreakerConfig` | 5471–5487 | `circuit_breaker:` (7668) | none |
| `ConcurrencyConfig` | 5496–5510 | `concurrency:` (7670) | none |
| `EventLogConfig` | 5600–5604 | `event_log:` (7720) | none |

Every one of these is substrate/mesh/consensus/runtime-core — a coherent `core` domain, not a convenience grab-bag.

---

## Section 1 — `src/probos/config_models/__init__.py`

New package. Keep it a **namespace-only re-export**, no model bodies:

```python
"""Domain-partitioned configuration models (AD-1270e2).

``probos.config`` remains the permanent public facade. Import from there, not
from here; this package exists so ``config.py`` can stop being 7,842 lines.
"""

from __future__ import annotations

from probos.config_models.core import (
    CircuitBreakerConfig,
    ConcurrencyConfig,
    ConsensusConfig,
    EventLogConfig,
    MeshConfig,
    PoolConfig,
    ScalingConfig,
    SystemInfo,
)

__all__ = [
    "CircuitBreakerConfig",
    "ConcurrencyConfig",
    "ConsensusConfig",
    "EventLogConfig",
    "MeshConfig",
    "PoolConfig",
    "ScalingConfig",
    "SystemInfo",
]
```

`config_models/` must not import `probos.config`. The direction is facade → package, one way. A cycle here is a build failure, not a style note.

## Section 2 — `src/probos/config_models/core.py`

New file. Move the eight class bodies **byte-for-byte** — same docstrings, same field order, same defaults, same aliases, same validators, same inline comments. Do not reformat, do not "tidy" a default, do not add a type annotation that was not there.

Header imports needed by this batch:

```python
from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, Field, field_validator
```

`from __future__ import annotations` is required: `config.py` has it at line 3, and dropping it changes how Pydantic resolves the annotations it is about to rebuild.

## Section 3 — `src/probos/config.py`

Delete the eight class bodies. Add one import near the top, after the existing pydantic import block (line 12):

```python
from probos.config_models.core import (
    CircuitBreakerConfig,
    ConcurrencyConfig,
    ConsensusConfig,
    EventLogConfig,
    MeshConfig,
    PoolConfig,
    ScalingConfig,
    SystemInfo,
)
```

`from probos.config import PoolConfig` must keep working, and must yield the **same class object** — not a subclass, not a wrapper, not an alias to a re-declared copy. The e1 baseline compares identity by qualname, MRO bases and ordered fields; a wrapper or partial clone fails four ways.

`config.py` has **no `__all__`** (verified). Do not add one — introducing `__all__` would itself change the public surface e1 froze.

Leave the `SystemConfig` field declarations exactly as they are. `pools: PoolConfig = PoolConfig()` still constructs its default at class-body evaluation inside `config.py`; the class simply lives elsewhere now.

## Section 4 — Tripwire 1: selector blast radius

`scripts/select_tests.py` line 183, `BLAST_RADIUS_PATTERNS`. Add, adjacent to the existing `"src/probos/config.py"` entry:

```python
    "src/probos/config_models/*.py",
```

The tripwire probes the literal `src/probos/config_models/example.py` against every pattern via `fnmatch`, so the glob must match a file directly inside the directory. This lands **in the same commit that creates the directory** — a config-model change that does not select the full suite is the failure this exists to prevent.

## Section 5 — Tripwire 2: config-profiles environment scan

**This is the tripwire the author must not discover by running the checker.** `scripts/check_config_facade.py::tripwire_problems` emits, verbatim:

> `facade-tripwire-config-profiles-scan: src/probos/config_models/ exists but check_config_profiles._DEFAULT_CONFIG_MODULE still resolves to a single file, so its real->declared environment gate now scans a module the models have left and passes blind. AD-1270e2 owns this fix; widen it to the package in the same commit.`

Detection is by AST, not import: `config_profiles_scan_is_single_file()` reads the module-level assignment to `_DEFAULT_CONFIG_MODULE` and returns `True` if **any** string literal in that expression ends in `.py`.

Two changes in `scripts/check_config_profiles.py`:

1. **Line 81** — `_DEFAULT_CONFIG_MODULE = _REPO_ROOT / "src" / "probos" / "config.py"` must stop resolving to one file. Point it at the package root (`_REPO_ROOT / "src" / "probos"`) and rename if the name becomes misleading. No `.py` literal may remain in that assignment.
2. **Line 401** — `env_reads_reaching_defaults(config_module: Path)` does `ast.parse(config_module.read_text(...))` on a single file. Widen it to parse `config.py` **and** every `config_models/*.py`, merging the `{env_var: mechanism}` results. Its semantics do not change: a read still reaches a default only via `model_validator`, or via `field_validator` on a `validate_default=True` field. The `PROBOS_LLM_URL` row must still be measured — that is the row proving the instrument discriminates.

Also update the call site at **line 793** in `main()`, which passes the same single-file path explicitly. It is not tripwire-detected, so it will silently keep the old narrow scan if you fix only line 81.

`tests/test_ad1270e1_config_facade.py` asserts the two instruments agree. Keep it green **without editing its assertions** — if it goes red, the widening is wrong, not the test.

## Section 6 — Tests: `tests/test_ad1270e2_config_models.py`

New file. Required cases:

**Identity and re-export (the contract)**
1. For all eight: `probos.config.X is probos.config_models.core.X` — the same object, not an equal one.
2. For all eight: `X.__qualname__`, MRO bases, and `list(X.model_fields)` in order are unchanged from the e1 baseline entry.
3. `from probos.config import PoolConfig, MeshConfig, ...` succeeds for all eight (the literal consumer spelling).
4. Each moved class's `__module__` is `probos.config_models.core`, and `check_config_facade.owns()` returns `True` for it. This is the assertion that would have caught the round-1 e1 defect; it is cheap and it is the one that matters.

**Behaviour preserved (boundary cases)**
5. `SystemConfig().model_dump(mode="json")` sub-dicts for `system`, `pools`, `mesh`, `consensus`, `scaling`, `circuit_breaker`, `concurrency`, `event_log` equal the pre-move values. Assert against literals, not against a re-derived dump.
6. `MeshConfig` is the only model in this batch with a validator: test its happy path, its rejection path, and the boundary value the validator turns on.
7. Mutable-default independence: `SystemConfig().pools is not SystemConfig().pools`. e1 measured that `validate_default=True` makes every `SystemConfig()` deep-copy the class default; moving the class must not change that.
8. Empty/None: constructing each of the eight with no arguments succeeds and every field equals its declared default.

**Structural**
9. `src/probos/config_models/core.py` does not import `probos.config` (AST assertion — no cycle).
10. `check_config_facade.tripwire_problems(repo_root)` returns `[]` on this tree. A test that only asserts the checker is green is weaker than one that asserts *this specific list* is empty; assert the list.

Run with `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1270e2_config_models.py tests/test_ad1270e1_config_facade.py tests/test_ad1270f_impact_selector.py -q -n 0 -p no:randomly`.

---

## What This Does NOT Change

**Do not build any of the following. Each is a separate slice or an explicit program prohibition.**

- **Do not move any non-leaf model.** `CognitiveConfig`, `MemoryConfig`, `FederationConfig`, `SecurityConfig`, `ChannelsConfig`, `SystemConfig` and every other model that references another config model stay in `config.py`. `SystemConfig` composition is **AD-1270e3**, not this slice.
- **Do not move batches 2–5.** No `cognition.py`, `experience.py`, `integrations.py`, `operations.py` in this commit. Eight models, one file.
- **Do not change any default, alias, field name, field order, validator, or docstring.** A move that also edits a value is not a move, and the e1 baseline will not distinguish the two for you.
- **Do not regenerate `docs/development/config-facade-baseline.yaml`.** The baseline compares identity by qualname, MRO and ordered fields and *never* by `__module__` (baseline header, line 45), so a pure re-export passes unchanged. If `--check` demands a regeneration, **stop and report it** — that means the move was not pure, and regenerating would erase the evidence rather than fix it.
- **Do not touch `config/system.yaml`** or any file under `config/`. The program's acceptance states no YAML edit is needed to complete the extraction; needing one is a defect signal.
- **Do not add `extra="forbid"`.** `SystemConfig.model_config == {}`, so Pydantic's default `extra='ignore'` is in force and unknown keys are silently dropped. Tightening that is a behaviour change affecting every deployed YAML, and it is not this slice.
- **Do not add `__all__` to `config.py`**, reorder its imports, or reformat untouched regions. Keep the diff to: eight deletions, one import, plus the new files.
- **Do not create a `config_models/` subpackage layout**, a registry, a plugin loader, or a base class for config models.

---

## Acceptance Criteria

1. `d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_facade.py --check` exits 0 with the baseline **unmodified** (`git diff --exit-code docs/development/config-facade-baseline.yaml` is clean).
2. `d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_profiles.py --check` exits 0, and its report still shows the `PROBOS_LLM_URL` environment-read row.
3. Full preflight green: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --preflight-only --label ad-1270e2`. The `config-facade` phase must pass, and its advisory `facade-slow` line (6.0s soft / 60.0s hard) must not have become a hard error.
4. **Predict the gate node total before running the gate.** State the predicted number and the arithmetic (current total plus the count of new test functions in `tests/test_ad1270e2_config_models.py`) in the build report *before* invoking the canonical wrapper. A prediction that misses is a finding to explain, not a number to quietly correct afterwards.
5. Full canonical gate on the committed tree: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad-1270e2`, exit 0, receipt banked and re-verified against the durable artifacts. Report `junit.tests == collection.nodes`, `head_tree == index_tree`, and `tree_changed: false`.
6. Adversarial review on the staged diff before commit, per the standing order — with a different model than the author. Scope it to the re-export seam and to `check_config_profiles`'s widened scan, which is the change most likely to pass blind.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Tracking

- `PROGRESS.md` — AD-1270e2 batch 1 entry.
- `docs/development/platform-maturity-program.md` — mark batch 1 of 5 complete under the e2 section; the epic and the AD both stay open.
- `DECISIONS.md` — AD-1270e2 entry recording the `core` batch membership and why these eight.
- Issue #1324 — comment only; do not close.

---

## Working-Tree Warning

Another session holds uncommitted work in `README.md`, `docs/architecture/federation.md`, `docs/development/roadmap.md`, and `src/probos/infrastructure/restore.py`. Do not stage, commit, stash, revert, or edit those four files. If `git status` shows anything else unexpected, stop and report before committing.

---

## Verified Against Codebase (2026-09-02)

```
grep -n "CONFIG_MODELS_PACKAGE\|def owns\|def _classify" scripts/check_config_facade.py
  185: CONFIG_MODELS_PACKAGE = ".".join(CONFIG_MODELS_RELDIR.split("/")[1:])
  816: def owns(module: str | None) -> bool:
  841:     if module == FACADE_MODULE or module == CONFIG_MODELS_PACKAGE:
  843:     return module.startswith(f"{CONFIG_MODELS_PACKAGE}.")
  846: def _classify(obj: Any) -> tuple[str, str]:

# owns() docstring, verbatim: "Ownership cannot be __module__ == probos.config:
# that is the one predicate a legitimate AD-1270e2 extraction is guaranteed to
# break." -> a move to config_models/ stays tier: owned.

grep -n "def tripwire_problems\|facade-tripwire" scripts/check_config_facade.py
  1124: def tripwire_problems(repo_root: Path) -> list[str]:
  1132:     "facade-tripwire-config-profiles-scan: ..."
  1151:     "facade-tripwire-selector-blast-radius: ..."
  1126:     if not (repo_root / CONFIG_MODELS_RELDIR).is_dir(): return problems

grep -n "def config_profiles_scan_is_single_file" scripts/check_config_facade.py
  1089:   reads _module_assignment(source, "_DEFAULT_CONFIG_MODULE");
  1100:   returns True if any string literal ends in ".py"

grep -n "_DEFAULT_CONFIG_MODULE\|def env_reads_reaching_defaults" scripts/check_config_profiles.py
    81: _DEFAULT_CONFIG_MODULE = _REPO_ROOT / "src" / "probos" / "config.py"
   401: def env_reads_reaching_defaults(config_module: Path) -> dict[str, str]:
   411:     tree = ast.parse(config_module.read_text(encoding="utf-8"))
   644:     config_module: Path = _DEFAULT_CONFIG_MODULE,
   793:     config_module=repo_root / "src" / "probos" / "config.py",

grep -n "BLAST_RADIUS_PATTERNS" scripts/select_tests.py
   183: BLAST_RADIUS_PATTERNS: tuple[str, ...] = (
   186:     "src/probos/config.py",          # no config_models/ entry today

test -d src/probos/config_models        -> False (does not exist)
grep -c "^class " src/probos/config.py  -> 224 owned models, 7,842 lines
grep -n "__all__" src/probos/config.py  -> no match

# Batch membership, verified self-contained (free names are imports only):
#   PoolConfig 117-140 deps=[BaseModel, Field]
#   MeshConfig 143-182 deps=[Any, BaseModel, Field, field_validator, math]
#   ConsensusConfig 185-195, ScalingConfig 1430-1440, CircuitBreakerConfig
#   5471-5487, ConcurrencyConfig 5496-5510, EventLogConfig 5600-5604,
#   SystemInfo 6034-6039 -- all deps=[BaseModel] or [BaseModel, Field]
# Each referenced exactly twice: own definition + SystemConfig field.

grep -n "PoolConfig\|MeshConfig" docs/development/config-facade-baseline.yaml
   298:  MeshConfig: {kind: model, tier: owned}
   344:  PoolConfig: {kind: model, tier: owned}
  2346:  MeshConfig: {qualname, bases, schema_sha256, fields}
    45: "Identity is compared by qualname, MRO bases and ordered fields, never
        by __module__, so a re-export passes"   <- no regeneration needed
```
