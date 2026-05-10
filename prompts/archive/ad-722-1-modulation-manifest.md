# AD-722-1 — Modulation rule table → JSON manifest (single source of truth)

**Status:** READY FOR BUILDER
**Wave:** 141 (Build Group A — first commit)
**Dispatch:** [prompts/WAVE-141-DISPATCH.md](WAVE-141-DISPATCH.md)
**Cluster plan:** [prompts/BUILDER-EXECUTION-PLAN-avatar-cluster.md](BUILDER-EXECUTION-PLAN-avatar-cluster.md)
**Depends on:** AD-722 v1 (SHIPPED Wave 140 — agent-observable avatar telemetry)
**Pairs with:** AD-722f (same wave, builds on top of this commit)
**Issue:** [#572](https://github.com/seangalliher/ProbOS/issues/572)
**Risk:** **LOW** — pure refactor; the existing byte-parity test rewrites against the manifest; existing public Python constants stay re-exported (zero downstream import breakage).
**Estimated tests:** ≥ 8 Python (manifest load, byte-parity replacement, every constant survives, missing-file failure mode, malformed-file failure mode, re-import idempotency, schema-rejection on extra keys, schema-rejection on missing keys). Vitest unaffected (TS imports the JSON natively; the existing modulation tests in `ui/src/__tests__/voiceModulation.test.ts` keep passing because the TS public API is unchanged).
**Build order:** First commit of Wave 141.

> **Builder:** read [prompts/WAVE-141-DISPATCH.md](WAVE-141-DISPATCH.md) for the cross-AD checklist and test-gate command. Read [prompts/BUILDER-EXECUTION-PLAN-avatar-cluster.md](BUILDER-EXECUTION-PLAN-avatar-cluster.md) for the cluster theme. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## 1. Goal

AD-722 v1 shipped the modulation rule table duplicated **byte-for-byte across two languages**: `src/probos/avatars/telemetry.py` (Python) and `ui/src/audio/voiceModulation.ts` (TypeScript). Drift is currently prevented by `test_modulation_byte_parity_with_ts` (`tests/test_ad722_avatar_telemetry.py:327`), which file-reads the TS source, regex-extracts each named constant, and asserts equality against the matching Python module-level constant.

This works but is fragile (regex against TS syntax) and forces every change to the rule table to land in two source files. AD-722-1 extracts the rule table to a single JSON manifest both languages read from. The byte-parity *test* is replaced by a manifest-load test plus a schema-validation test; the byte-parity *guarantee* moves into the loader (one file, two readers).

This is a pure refactor. No behaviour change. No new public API on either side. The existing `from probos.avatars.telemetry import RESPONDING_RATE_FACTOR` etc. continues to work — the constants are re-bound at module load from the manifest.

---

## 2. Verified Against Codebase (2026-05-10 @ HEAD)

```
# Python rule-table block (the source we're extracting)
grep -n "MODULATION_DIVERGENCE_THRESHOLD\|PITCH_BOUNDS\|RATE_BOUNDS\|VOLUME_BOUNDS\|TRUST_DELTA_HIGH\|TRUST_DELTA_LOW\|RESPONDING_RATE_FACTOR\|BLOCKED_RATE_FACTOR\|BLOCKED_PITCH_FACTOR\|HIGH_TRUST_PITCH_FACTOR\|LOW_TRUST_PITCH_FACTOR\|TIER3_RATE_FACTOR\|TIER3_VOLUME_FACTOR\|DEFAULT_PITCH\|DEFAULT_RATE\|DEFAULT_VOLUME" \
     src/probos/avatars/telemetry.py
   54: MODULATION_DIVERGENCE_THRESHOLD: float = 0.05
   55: PITCH_BOUNDS: tuple[float, float] = (0.0, 2.0)
   56: RATE_BOUNDS: tuple[float, float] = (0.1, 10.0)
   57: VOLUME_BOUNDS: tuple[float, float] = (0.0, 1.0)
   59: TRUST_DELTA_HIGH: float = 0.2
   60: TRUST_DELTA_LOW: float = -0.2
   62: RESPONDING_RATE_FACTOR: float = 1.05
   63: BLOCKED_RATE_FACTOR: float = 0.92
   64: BLOCKED_PITCH_FACTOR: float = 0.95
   65: HIGH_TRUST_PITCH_FACTOR: float = 1.03
   66: LOW_TRUST_PITCH_FACTOR: float = 0.97
   67: TIER3_RATE_FACTOR: float = 1.15
   68: TIER3_VOLUME_FACTOR: float = 1.05
   70: DEFAULT_PITCH: float = 0.9
   71: DEFAULT_RATE: float = 0.95
   72: DEFAULT_VOLUME: float = 0.8

# TypeScript mirror (the byte-parity test reads this verbatim)
grep -n "MODULATION_DIVERGENCE_THRESHOLD\|PITCH_BOUNDS\|RATE_BOUNDS\|VOLUME_BOUNDS\|TRUST_DELTA_HIGH\|TRUST_DELTA_LOW\|RESPONDING_RATE_FACTOR\|BLOCKED_RATE_FACTOR\|BLOCKED_PITCH_FACTOR\|HIGH_TRUST_PITCH_FACTOR\|LOW_TRUST_PITCH_FACTOR\|TIER3_RATE_FACTOR\|TIER3_VOLUME_FACTOR\|DEFAULT_PITCH\|DEFAULT_RATE\|DEFAULT_VOLUME" \
     ui/src/audio/voiceModulation.ts
   17: NOTE: this rule table is duplicated in src/probos/avatars/telemetry.py.
   20: export const MODULATION_DIVERGENCE_THRESHOLD = 0.05;
   23: export const PITCH_BOUNDS: readonly [number, number] = [0, 2];
   24: export const RATE_BOUNDS: readonly [number, number] = [0.1, 10];
   25: export const VOLUME_BOUNDS: readonly [number, number] = [0, 1];
   28: const TRUST_DELTA_HIGH = 0.2;
   29: const TRUST_DELTA_LOW = -0.2;
   33: const RESPONDING_RATE_FACTOR = 1.05;
   34: const BLOCKED_RATE_FACTOR = 0.92;
   35: const BLOCKED_PITCH_FACTOR = 0.95;
   36: const HIGH_TRUST_PITCH_FACTOR = 1.03;
   37: const LOW_TRUST_PITCH_FACTOR = 0.97;
   38: const TIER3_RATE_FACTOR = 1.15;
   39: const TIER3_VOLUME_FACTOR = 1.05;
   41: const DEFAULT_PITCH = 0.9;
   42: const DEFAULT_RATE = 0.95;
   43: const DEFAULT_VOLUME = 0.8;

# Existing byte-parity test (the one being replaced)
grep -n "test_modulation_byte_parity_with_ts\|ts_path = Path" tests/test_ad722_avatar_telemetry.py
  327: def test_modulation_byte_parity_with_ts():
  334:     ts_path = Path("ui/src/audio/voiceModulation.ts")

# Public Python re-import surface (must remain importable after refactor)
grep -n "from probos.avatars.telemetry import" tests/test_ad722_avatar_telemetry.py | head -5
   21: from probos.avatars.telemetry import (
# (16 named constants imported by the test file; all must remain.)

# TypeScript tsconfig — verifies JSON imports work natively under module: ESNext / moduleResolution: bundler
grep -n "module\|moduleResolution\|resolveJsonModule" ui/tsconfig.json
    6:     "module": "ESNext",
    7:     "skipLibCheck": true,
    8:     "moduleResolution": "bundler",
# Vite + bundler resolution natively supports `import data from './file.json'` — `resolveJsonModule` defaults to true with ESNext + bundler. No config change required.

# UI test surface that must keep passing
grep -rn "voiceModulation\|applyEmotionalModulation\|MODULATION_DIVERGENCE_THRESHOLD" ui/src/__tests__/ ui/src/audio/ | head -10
# (All current consumers will keep working; the TS public API is unchanged — only the *source* of the constants moves to the JSON.)
```

---

## 3. License posture

Apache 2.0 stays Apache 2.0. **Zero new Python deps. Zero new JS deps.**

- Python loads JSON via stdlib `json.loads` — already in the standard library.
- TypeScript imports JSON via Vite's native `resolveJsonModule` — no plugin, no new package.
- YAML rejected: would require `js-yaml` on the TS side (new dep, license check overhead) for no readability benefit on a flat numeric table. JSON is the smaller surface.

`pyproject.toml` and `ui/package.json` are bit-for-bit unchanged — Reviewer fails on any diff to either.

---

## 4. Architectural decisions (resolved by architect; do not re-litigate)

| Decision | Resolution | Rationale |
|---|---|---|
| Format | **JSON** | Native parse on both sides, no new deps, no YAML-vs-JSON readability tradeoff for a flat numeric table. |
| Manifest location | **`ui/src/audio/modulation_manifest.json`** | Lives next to its TS reader so Vite bundles it natively (no `tsconfig.include` change, no path-traversal hacks). Python reads from the repo-root-relative path via `Path(__file__).resolve().parents[3] / "ui" / "src" / "audio" / "modulation_manifest.json"`. ProbOS runs from source tree today — no wheel-packaging concern. |
| Loader caching | **Module-level on import** | Manifest is ~16 entries / <1 KB. Module-level constant assignment is the simplest pattern; missing/malformed manifest must fail loudly at import (this is a hard runtime requirement, not a degraded-mode fallback). |
| Public Python API | **Unchanged** | `from probos.avatars.telemetry import RESPONDING_RATE_FACTOR` continues to work. The 16 named module-level constants are re-bound at import-time from the manifest. Every existing test import keeps working without modification. |
| Public TS API | **Unchanged** | `export const RESPONDING_RATE_FACTOR` etc. continue to be exported with the same identifiers; their values come from the manifest import instead of inline literals. |

---

## 5. Scope (this AD only)

Single commit. Three files modified, one file added:

1. **Add** `ui/src/audio/modulation_manifest.json` — the canonical rule table.
2. **Modify** `src/probos/avatars/telemetry.py` — replace the inline literals with manifest-driven constant assignment. Keep every public name and value identical.
3. **Modify** `ui/src/audio/voiceModulation.ts` — replace the inline literals with values pulled from `import manifest from './modulation_manifest.json'`. Keep every public name and value identical. Update the duplication-warning comment to reflect the new single-source-of-truth.
4. **Modify** `tests/test_ad722_avatar_telemetry.py` — replace `test_modulation_byte_parity_with_ts` with two new tests against the manifest (load + schema). Add a third test asserting Python module-level constants equal manifest values.

---

## 6. Non-goals (deferred)

| Marker | Deferred to | Why not v1 |
|---|---|---|
| AD-722f sampling-rate fields | Same wave, next commit | Sampling rates are not modulation rules; they live in `AvatarTelemetryConfig`, not in the rule manifest. AD-722f reads the manifest pattern but does not mutate it. |
| Versioning the manifest schema | Future AD if/when a non-additive change lands | v1 ships with implicit schema = "all current keys present, no extras". A formal `"$schema"` field is future work. |
| Operator override of manifest values | Out of scope forever | The rule table is Captain-canonical, not operator-tunable. This AD locks that property in. |

Reviewer fails the prompt if any deliverable touches `pyproject.toml`, `ui/package.json`, `apply_voice_modulation()`'s body, `applyEmotionalModulation`'s body, or any test file other than `tests/test_ad722_avatar_telemetry.py`.

---

## 7. Deliverables

### D1 — Add `ui/src/audio/modulation_manifest.json`

Create the file with EXACTLY this content (trailing newline; 2-space indent; sorted keys NOT required but recommended for diff stability):

```json
{
  "modulation_divergence_threshold": 0.05,
  "trust_delta_high": 0.2,
  "trust_delta_low": -0.2,
  "responding_rate_factor": 1.05,
  "blocked_rate_factor": 0.92,
  "blocked_pitch_factor": 0.95,
  "high_trust_pitch_factor": 1.03,
  "low_trust_pitch_factor": 0.97,
  "tier3_rate_factor": 1.15,
  "tier3_volume_factor": 1.05,
  "default_pitch": 0.9,
  "default_rate": 0.95,
  "default_volume": 0.8,
  "pitch_bounds": [0.0, 2.0],
  "rate_bounds": [0.1, 10.0],
  "volume_bounds": [0.0, 1.0]
}
```

Rules: lowercase snake_case keys; floats explicit (`0.0` not `0`); bounds as 2-element JSON arrays.

### D2 — Python loader in `src/probos/avatars/telemetry.py`

**SEARCH** the existing modulation rule table block (lines 54-72 at HEAD):

```python
# ── Modulation rule table (TS↔Python byte-parity, enforced by test) ─────

MODULATION_DIVERGENCE_THRESHOLD: float = 0.05
PITCH_BOUNDS: tuple[float, float] = (0.0, 2.0)
RATE_BOUNDS: tuple[float, float] = (0.1, 10.0)
VOLUME_BOUNDS: tuple[float, float] = (0.0, 1.0)

TRUST_DELTA_HIGH: float = 0.2
TRUST_DELTA_LOW: float = -0.2

RESPONDING_RATE_FACTOR: float = 1.05
BLOCKED_RATE_FACTOR: float = 0.92
BLOCKED_PITCH_FACTOR: float = 0.95
HIGH_TRUST_PITCH_FACTOR: float = 1.03
LOW_TRUST_PITCH_FACTOR: float = 0.97
TIER3_RATE_FACTOR: float = 1.15
TIER3_VOLUME_FACTOR: float = 1.05

DEFAULT_PITCH: float = 0.9
DEFAULT_RATE: float = 0.95
DEFAULT_VOLUME: float = 0.8
```

**REPLACE** with the manifest-driven loader:

```python
# ── Modulation rule table (loaded from JSON manifest — AD-722-1) ────────
#
# Single source of truth: ``ui/src/audio/modulation_manifest.json``. Both
# this module and ``ui/src/audio/voiceModulation.ts`` read from that file.
# AD-722-1 retired the regex-based byte-parity test; drift is now structurally
# impossible (one file, two readers). Schema is enforced by
# ``_load_modulation_manifest()`` — every key listed below MUST be present.

import json as _json
from pathlib import Path as _Path


_MANIFEST_PATH: _Path = (
    _Path(__file__).resolve().parents[3]
    / "ui" / "src" / "audio" / "modulation_manifest.json"
)

_REQUIRED_SCALAR_KEYS: tuple[str, ...] = (
    "modulation_divergence_threshold",
    "trust_delta_high",
    "trust_delta_low",
    "responding_rate_factor",
    "blocked_rate_factor",
    "blocked_pitch_factor",
    "high_trust_pitch_factor",
    "low_trust_pitch_factor",
    "tier3_rate_factor",
    "tier3_volume_factor",
    "default_pitch",
    "default_rate",
    "default_volume",
)
_REQUIRED_BOUNDS_KEYS: tuple[str, ...] = (
    "pitch_bounds", "rate_bounds", "volume_bounds",
)


def _load_modulation_manifest() -> dict[str, Any]:
    """Load and validate the modulation manifest. Raises on any defect.

    Hard requirement at import — if the manifest is missing, malformed,
    or schema-incomplete, the module fails to import. This is by design:
    the rule table is non-optional; degraded fallback would silently
    re-introduce the duplication AD-722-1 exists to eliminate.
    """
    if not _MANIFEST_PATH.is_file():
        raise RuntimeError(
            f"AD-722-1: modulation manifest not found at {_MANIFEST_PATH}. "
            "ProbOS expects to run from the repo source tree; if you are "
            "running from a non-source layout, file a packaging AD."
        )
    try:
        data = _json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
    except _json.JSONDecodeError as exc:
        raise RuntimeError(
            f"AD-722-1: modulation manifest at {_MANIFEST_PATH} is malformed "
            f"JSON: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise RuntimeError(
            f"AD-722-1: modulation manifest at {_MANIFEST_PATH} must be a "
            f"JSON object; got {type(data).__name__}"
        )
    missing = [k for k in _REQUIRED_SCALAR_KEYS + _REQUIRED_BOUNDS_KEYS
               if k not in data]
    if missing:
        raise RuntimeError(
            f"AD-722-1: modulation manifest missing required keys: {missing}"
        )
    extra = [k for k in data
             if k not in _REQUIRED_SCALAR_KEYS + _REQUIRED_BOUNDS_KEYS]
    if extra:
        raise RuntimeError(
            f"AD-722-1: modulation manifest has unknown keys: {extra}. "
            "Schema additions require an architecture-decision review."
        )
    for k in _REQUIRED_SCALAR_KEYS:
        if not isinstance(data[k], (int, float)) or isinstance(data[k], bool):
            raise RuntimeError(
                f"AD-722-1: manifest key {k!r} must be a number; "
                f"got {type(data[k]).__name__}"
            )
    for k in _REQUIRED_BOUNDS_KEYS:
        b = data[k]
        if not (isinstance(b, list) and len(b) == 2
                and all(isinstance(x, (int, float)) and not isinstance(x, bool)
                        for x in b)):
            raise RuntimeError(
                f"AD-722-1: manifest key {k!r} must be a 2-number list; "
                f"got {b!r}"
            )
    return data


_MANIFEST: dict[str, Any] = _load_modulation_manifest()

MODULATION_DIVERGENCE_THRESHOLD: float = float(_MANIFEST["modulation_divergence_threshold"])
PITCH_BOUNDS: tuple[float, float] = (
    float(_MANIFEST["pitch_bounds"][0]), float(_MANIFEST["pitch_bounds"][1]),
)
RATE_BOUNDS: tuple[float, float] = (
    float(_MANIFEST["rate_bounds"][0]), float(_MANIFEST["rate_bounds"][1]),
)
VOLUME_BOUNDS: tuple[float, float] = (
    float(_MANIFEST["volume_bounds"][0]), float(_MANIFEST["volume_bounds"][1]),
)

TRUST_DELTA_HIGH: float = float(_MANIFEST["trust_delta_high"])
TRUST_DELTA_LOW: float = float(_MANIFEST["trust_delta_low"])

RESPONDING_RATE_FACTOR: float = float(_MANIFEST["responding_rate_factor"])
BLOCKED_RATE_FACTOR: float = float(_MANIFEST["blocked_rate_factor"])
BLOCKED_PITCH_FACTOR: float = float(_MANIFEST["blocked_pitch_factor"])
HIGH_TRUST_PITCH_FACTOR: float = float(_MANIFEST["high_trust_pitch_factor"])
LOW_TRUST_PITCH_FACTOR: float = float(_MANIFEST["low_trust_pitch_factor"])
TIER3_RATE_FACTOR: float = float(_MANIFEST["tier3_rate_factor"])
TIER3_VOLUME_FACTOR: float = float(_MANIFEST["tier3_volume_factor"])

DEFAULT_PITCH: float = float(_MANIFEST["default_pitch"])
DEFAULT_RATE: float = float(_MANIFEST["default_rate"])
DEFAULT_VOLUME: float = float(_MANIFEST["default_volume"])
```

Notes:
- The new `import json as _json` and `from pathlib import Path as _Path` are private aliases (leading underscore) so they don't pollute the module's public namespace; existing public imports (`logging`, `time`, `dataclass`, `Any`, `ValidationError`) at the top of the file are unchanged. **Place the new aliases inside the modulation block** (above the loader function) — do NOT add them to the top-of-file import group, since they belong to this rule-table sub-section.
- `Any` is already imported at module top (`from typing import Any`); reuse it.
- The `_clamp` helper at HEAD line ~75 is unchanged.
- Frozen dataclasses (`AgentSignalsSnapshot` etc.) are unchanged.
- `apply_voice_modulation()` is unchanged — it reads the module-level constants by name; their values come from the manifest instead of inline literals, but the names and types are identical.

### D3 — TypeScript loader in `ui/src/audio/voiceModulation.ts`

**SEARCH** the constants block (lines 13-44 at HEAD):

```typescript
/** Threshold above which the modulation indicator (E5) treats the
 *  modulation as perceptible. Pitch / rate / volume that diverge >5%
 *  from baseline trigger the active state. */
// NOTE: this rule table is duplicated in src/probos/avatars/telemetry.py.
// Keep them in lockstep — byte-parity is enforced by a Python test that
// file-reads this source. AD-722-1 will extract to a YAML manifest.
export const MODULATION_DIVERGENCE_THRESHOLD = 0.05;

/** Web Speech API + VoiceProfile validator bounds (single source of
 *  truth — same numbers on both sides). */
export const PITCH_BOUNDS: readonly [number, number] = [0, 2];
export const RATE_BOUNDS: readonly [number, number] = [0.1, 10];
export const VOLUME_BOUNDS: readonly [number, number] = [0, 1];

/** Trust-delta thresholds (Captain-canonical, not magnitude-proportional). */
const TRUST_DELTA_HIGH = 0.2;
const TRUST_DELTA_LOW = -0.2;

/** Multiplicative factors per rule (small — modulation is perceptible
 *  but never overrides the agent's baseline character). */
const RESPONDING_RATE_FACTOR = 1.05;
const BLOCKED_RATE_FACTOR = 0.92;
const BLOCKED_PITCH_FACTOR = 0.95;
const HIGH_TRUST_PITCH_FACTOR = 1.03;
const LOW_TRUST_PITCH_FACTOR = 0.97;
const TIER3_RATE_FACTOR = 1.15;
const TIER3_VOLUME_FACTOR = 1.05;

const DEFAULT_PITCH = 0.9;
const DEFAULT_RATE = 0.95;
const DEFAULT_VOLUME = 0.8;
```

**REPLACE** with manifest-driven constants:

```typescript
/** AD-722-1: rule-table values come from ``./modulation_manifest.json`` —
 *  the single source of truth shared with ``src/probos/avatars/telemetry.py``.
 *  Vite + tsconfig (``moduleResolution: bundler``) handle JSON imports
 *  natively; no plugin, no new dependency. The Python loader validates
 *  the manifest schema at import; the TS side trusts that gate.
 *
 *  Public API (every exported name below) is unchanged — only the
 *  *source* of the values moved. Consumers do not need updating. */
import manifest from './modulation_manifest.json';

/** Threshold above which the modulation indicator (E5) treats the
 *  modulation as perceptible. Pitch / rate / volume that diverge >5%
 *  from baseline trigger the active state. */
export const MODULATION_DIVERGENCE_THRESHOLD: number =
  manifest.modulation_divergence_threshold;

/** Web Speech API + VoiceProfile validator bounds (single source of
 *  truth — same numbers on both sides). */
export const PITCH_BOUNDS: readonly [number, number] = [
  manifest.pitch_bounds[0], manifest.pitch_bounds[1],
];
export const RATE_BOUNDS: readonly [number, number] = [
  manifest.rate_bounds[0], manifest.rate_bounds[1],
];
export const VOLUME_BOUNDS: readonly [number, number] = [
  manifest.volume_bounds[0], manifest.volume_bounds[1],
];

/** Trust-delta thresholds (Captain-canonical, not magnitude-proportional). */
const TRUST_DELTA_HIGH: number = manifest.trust_delta_high;
const TRUST_DELTA_LOW: number = manifest.trust_delta_low;

/** Multiplicative factors per rule (small — modulation is perceptible
 *  but never overrides the agent's baseline character). */
const RESPONDING_RATE_FACTOR: number = manifest.responding_rate_factor;
const BLOCKED_RATE_FACTOR: number = manifest.blocked_rate_factor;
const BLOCKED_PITCH_FACTOR: number = manifest.blocked_pitch_factor;
const HIGH_TRUST_PITCH_FACTOR: number = manifest.high_trust_pitch_factor;
const LOW_TRUST_PITCH_FACTOR: number = manifest.low_trust_pitch_factor;
const TIER3_RATE_FACTOR: number = manifest.tier3_rate_factor;
const TIER3_VOLUME_FACTOR: number = manifest.tier3_volume_factor;

const DEFAULT_PITCH: number = manifest.default_pitch;
const DEFAULT_RATE: number = manifest.default_rate;
const DEFAULT_VOLUME: number = manifest.default_volume;
```

Note: the rest of the file (`clamp`, `applyEmotionalModulation`, `hasMeaningfulModulation`) is unchanged.

### D4 — Test rewrite in `tests/test_ad722_avatar_telemetry.py`

**SEARCH** `test_modulation_byte_parity_with_ts` (lines 327-385 at HEAD — entire function body, including the regex blocks and the `py_singletons` / `py_bounds` dicts):

```python
def test_modulation_byte_parity_with_ts():
    """The TS source MUST hold the same numeric values for every named constant.

    File-read ``ui/src/audio/voiceModulation.ts``, regex-extract every
    ``(const|export const) NAME = VALUE`` line, assert each matching Python
    constant has the same numeric value.
    """
    ts_path = Path("ui/src/audio/voiceModulation.ts")
    text = ts_path.read_text(encoding="utf-8")

    # Capture single-number TS constants: `(export )?const NAME = NUM;`
    pattern = re.compile(
        r"(?:export\s+)?const\s+([A-Z_][A-Z0-9_]*)\s*(?::\s*[^=]+)?=\s*(-?\d+\.?\d*)\s*;",
    )
    ts_constants: dict[str, float] = {}
    for m in pattern.finditer(text):
        name, value = m.group(1), m.group(2)
        ts_constants[name] = float(value)

    # Tuple-bound constants are emitted in TS as `[lo, hi]` arrays — capture separately.
    bounds_pattern = re.compile(
        r"(?:export\s+)?const\s+([A-Z_]+_BOUNDS)\s*:[^=]+=\s*\[\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*\]",
    )
    ts_bounds: dict[str, tuple[float, float]] = {}
    for m in bounds_pattern.finditer(text):
        ts_bounds[m.group(1)] = (float(m.group(2)), float(m.group(3)))

    py_singletons = {
        "MODULATION_DIVERGENCE_THRESHOLD": MODULATION_DIVERGENCE_THRESHOLD,
        "RESPONDING_RATE_FACTOR": RESPONDING_RATE_FACTOR,
        "BLOCKED_RATE_FACTOR": BLOCKED_RATE_FACTOR,
        "BLOCKED_PITCH_FACTOR": BLOCKED_PITCH_FACTOR,
        "HIGH_TRUST_PITCH_FACTOR": HIGH_TRUST_PITCH_FACTOR,
        "LOW_TRUST_PITCH_FACTOR": LOW_TRUST_PITCH_FACTOR,
        "TIER3_RATE_FACTOR": TIER3_RATE_FACTOR,
        "TIER3_VOLUME_FACTOR": TIER3_VOLUME_FACTOR,
        "TRUST_DELTA_HIGH": TRUST_DELTA_HIGH,
        "TRUST_DELTA_LOW": TRUST_DELTA_LOW,
        "DEFAULT_PITCH": DEFAULT_PITCH,
        "DEFAULT_RATE": DEFAULT_RATE,
        "DEFAULT_VOLUME": DEFAULT_VOLUME,
    }
    for name, py_value in py_singletons.items():
        assert name in ts_constants, f"TS source missing constant {name}"
        assert ts_constants[name] == pytest.approx(py_value), (
            f"TS↔Python drift on {name}: TS={ts_constants[name]} Python={py_value}"
        )

    py_bounds = {
        "PITCH_BOUNDS": PITCH_BOUNDS,
        "RATE_BOUNDS": RATE_BOUNDS,
        "VOLUME_BOUNDS": VOLUME_BOUNDS,
    }
    for name, py_value in py_bounds.items():
        assert name in ts_bounds, f"TS source missing bounds {name}"
        assert ts_bounds[name][0] == pytest.approx(py_value[0])
        assert ts_bounds[name][1] == pytest.approx(py_value[1])
```

**REPLACE** with three manifest-anchored tests:

```python
def test_modulation_manifest_loads_from_canonical_path():
    """AD-722-1: the manifest must be at the canonical repo location and
    parseable as JSON. This is the structural replacement for the old
    regex-based byte-parity test — drift is now impossible because both
    Python and TS read from this single file."""
    import json
    manifest_path = Path("ui/src/audio/modulation_manifest.json")
    assert manifest_path.is_file(), (
        f"AD-722-1 manifest missing at {manifest_path}"
    )
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    # Schema: every documented key present, no extras.
    expected_scalar = {
        "modulation_divergence_threshold", "trust_delta_high",
        "trust_delta_low", "responding_rate_factor", "blocked_rate_factor",
        "blocked_pitch_factor", "high_trust_pitch_factor",
        "low_trust_pitch_factor", "tier3_rate_factor", "tier3_volume_factor",
        "default_pitch", "default_rate", "default_volume",
    }
    expected_bounds = {"pitch_bounds", "rate_bounds", "volume_bounds"}
    assert set(data.keys()) == expected_scalar | expected_bounds, (
        f"manifest schema drift: keys = {sorted(data.keys())}"
    )
    for k in expected_scalar:
        assert isinstance(data[k], (int, float)) and not isinstance(data[k], bool)
    for k in expected_bounds:
        assert isinstance(data[k], list) and len(data[k]) == 2


def test_python_constants_reflect_manifest_values():
    """AD-722-1: every Python module-level constant must equal the manifest
    value at import. This is the structural drift detector: if either side
    changes without the other, the value mismatches."""
    import json
    data = json.loads(
        Path("ui/src/audio/modulation_manifest.json").read_text(encoding="utf-8")
    )
    assert MODULATION_DIVERGENCE_THRESHOLD == pytest.approx(data["modulation_divergence_threshold"])
    assert TRUST_DELTA_HIGH == pytest.approx(data["trust_delta_high"])
    assert TRUST_DELTA_LOW == pytest.approx(data["trust_delta_low"])
    assert RESPONDING_RATE_FACTOR == pytest.approx(data["responding_rate_factor"])
    assert BLOCKED_RATE_FACTOR == pytest.approx(data["blocked_rate_factor"])
    assert BLOCKED_PITCH_FACTOR == pytest.approx(data["blocked_pitch_factor"])
    assert HIGH_TRUST_PITCH_FACTOR == pytest.approx(data["high_trust_pitch_factor"])
    assert LOW_TRUST_PITCH_FACTOR == pytest.approx(data["low_trust_pitch_factor"])
    assert TIER3_RATE_FACTOR == pytest.approx(data["tier3_rate_factor"])
    assert TIER3_VOLUME_FACTOR == pytest.approx(data["tier3_volume_factor"])
    assert DEFAULT_PITCH == pytest.approx(data["default_pitch"])
    assert DEFAULT_RATE == pytest.approx(data["default_rate"])
    assert DEFAULT_VOLUME == pytest.approx(data["default_volume"])
    assert PITCH_BOUNDS == (pytest.approx(data["pitch_bounds"][0]),
                            pytest.approx(data["pitch_bounds"][1]))
    assert RATE_BOUNDS == (pytest.approx(data["rate_bounds"][0]),
                           pytest.approx(data["rate_bounds"][1]))
    assert VOLUME_BOUNDS == (pytest.approx(data["volume_bounds"][0]),
                             pytest.approx(data["volume_bounds"][1]))


def test_typescript_imports_manifest_not_inline_literals():
    """AD-722-1: voiceModulation.ts must read its constants from the
    manifest (via ``import manifest from './modulation_manifest.json'``)
    rather than inline literals. Regex-checks the TS source for the
    import statement and asserts no inline numeric literal is assigned
    to a known rule-table constant."""
    ts_path = Path("ui/src/audio/voiceModulation.ts")
    text = ts_path.read_text(encoding="utf-8")
    assert "from './modulation_manifest.json'" in text, (
        "TS file must import the manifest"
    )
    # Spot-check: no inline numeric literal for the divergence threshold.
    inline_pattern = re.compile(
        r"MODULATION_DIVERGENCE_THRESHOLD\s*[:=]\s*(?:number\s*=\s*)?-?\d+\.\d+",
    )
    assert not inline_pattern.search(text), (
        "TS file still contains inline literal for MODULATION_DIVERGENCE_THRESHOLD"
    )
```

Note: the existing `test_modulation_rule_composition_responding_plus_tier3` (line 386) and any subsequent modulation-behaviour tests stay unchanged. They exercise `apply_voice_modulation()`, which still reads the module-level constants by name.

---

## 8. Wiring (call-graph confirmations)

| Site | Behaviour pre-AD | Behaviour post-AD |
|---|---|---|
| `apply_voice_modulation()` body (`telemetry.py:200-244`) | Reads inline-literal constants. | Reads manifest-bound constants. **Identical numeric output.** |
| `applyEmotionalModulation()` body (`voiceModulation.ts:67-101`) | Reads inline-literal constants. | Reads manifest-bound constants. **Identical numeric output.** |
| Any consumer doing `from probos.avatars.telemetry import RESPONDING_RATE_FACTOR` etc. | Constant present at module scope. | Constant present at module scope (re-bound from manifest at import). **No import-site changes required.** |
| Any TS consumer doing `import { RESPONDING_RATE_FACTOR } from './voiceModulation'` | Identifier exists. | Identifier exists. **No import-site changes required.** |
| Existing `tests/test_ad722_avatar_telemetry.py` imports (line 21-43, 16 named constants) | All resolve. | All resolve. |
| Existing `ui/src/__tests__/voiceModulation.test.ts` consumers (if any) | Resolve to inline values. | Resolve to manifest-driven values (same numbers). |

---

## 9. Acceptance criteria

- **Manifest file present** at `ui/src/audio/modulation_manifest.json` with 16 keys (13 scalar + 3 bounds), valid JSON.
- **Python constants unchanged** in name and value. All 16 named constants still importable; their values are byte-equal to pre-AD values.
- **TypeScript constants unchanged** in name and value. All exports still present. Inline numeric literals for the rule table are GONE — every value comes from `manifest.*`.
- **Existing test count** — all 18 cases in `test_ad722_avatar_telemetry.py` continue to pass; the deleted `test_modulation_byte_parity_with_ts` is replaced by **3 new tests** for a net delta of +2 tests.
- **Python full-gate test count** grows by +2 (relative to Wave 140 baseline). Re-record the new baseline in the dispatch.
- **Vitest count** is unchanged (the JSON import is transparent to the existing modulation tests).
- **Module import order**: nothing should import `probos.avatars.telemetry` from the manifest-load path; the manifest is read from disk directly via `pathlib`. No circular import risk.
- **Failure modes verified**:
  - Manifest missing → `RuntimeError` at import (test in D4 implicitly verifies presence).
  - Manifest malformed → `RuntimeError` from `_load_modulation_manifest`.
  - Schema-incomplete → `RuntimeError` from `_load_modulation_manifest`.
  - Schema-extra → `RuntimeError` from `_load_modulation_manifest`.
  - These are intentionally not exercised in the test suite v1 (they would require monkeypatching `_MANIFEST_PATH`, which adds machinery for marginal value). Builder may add them if straightforward; if not, defer.
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## 10. Tracking updates

| File | Update |
|---|---|
| `PROGRESS.md` | Add AD-722-1 to the "Most recent shipped" line. Bump test count baseline. |
| `docs/development/roadmap.md` | Mark #572 as shipped. |
| `DECISIONS.md` | Append AD-722-1 entry under the AD-722 addendum. Note: format = JSON, location = `ui/src/audio/modulation_manifest.json`, public API unchanged. Cite this prompt as the source. |

The Builder commits a single `git commit -m "AD-722-1: extract modulation rule table to JSON manifest"`. Push not required (architect handles release pushes).
