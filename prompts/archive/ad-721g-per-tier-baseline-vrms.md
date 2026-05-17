# AD-721g — Per-tier baseline VRMs

**Status:** ready-to-build
**Closes:** #534
**Estimated tests:** +9 pytest
**Depends on:** AD-721d-1 (default-VRM resolution), AD-721i-1 (license-audited manifest)
**Independent of:** AD-721d-3, AD-721h, AD-721i-2, AD-720b

---

## Problem

Today every crew member without a custom VRM either (a) inherits a seed `vrm_url` from `crew_profiles/*.yaml` or (b) falls back to a parametric capsule. There is no notion of "the default avatar for an Ensign in Engineering" vs "the default avatar for a Senior Officer in Medical." Forward marker #534 calls for **four** tier-keyed baseline VRMs (ensign / lieutenant / commander / senior).

The Wave 166 AD-721i-1 license-audited asset manifest is the precedent: ProbOS OSS never ships .vrm/.glb/.png bytes (per-file license metadata propagates). The manifest declares **what is acceptable**; operators bring the bytes locally; the manifest tells ProbOS how to resolve them.

## Solution

A **per-tier baseline VRM manifest** that maps `Rank` (and optionally department) → relative filename under `<avatars_dir>/_baselines/`. The resolver consults the manifest only when (a) `crew.appearance.vrm_url` is empty AND (b) no seed-profile `vrm_url` was present. v1 keys on **rank only** to keep the matrix tractable; department keying lands as a transitional default-False flag for a future AD.

No new bytes ship in the repo. The manifest itself ships (config). The operator installs four `.vrm` files (their own or licensed CC0/MIT/Apache/BSD/CC-BY per AD-721i-1) under `<platform_data_dir>/avatars/_baselines/`.

---

## Section 1 — Config

In `src/probos/config.py` extend `AvatarsConfig`:

```python
class BaselineVRMManifest(BaseModel):
    """AD-721g: per-rank baseline VRM filenames. Resolved against
    <avatars_dir>/_baselines/<filename>. Missing file → parametric fallback.
    """
    ensign: str = ""           # "" disables tier baseline; resolver falls back
    lieutenant: str = ""
    commander: str = ""
    senior: str = ""


class AvatarsConfig(BaseModel):
    # ... existing fields ...
    baseline_vrms: BaselineVRMManifest = Field(
        default_factory=BaselineVRMManifest,
        description=(
            "AD-721g: per-rank baseline VRM filenames resolved under "
            "<avatars_dir>/_baselines/. Empty string per rank → no tier "
            "baseline; resolver falls back to seed profile then parametric."
        ),
    )
```

`config/system.yaml` ships empty strings (`""`) for all four. No bytes leave the repo.

## Section 2 — Resolver

New module `src/probos/avatars/baseline_resolver.py` (~80 lines):

```python
"""AD-721g: per-rank baseline VRM resolver. License-clean — no bytes ship
in the repo; operator installs files under <avatars_dir>/_baselines/.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.config import BaselineVRMManifest
    from probos.crew_profile import Rank

logger = logging.getLogger(__name__)

_BASELINES_SUBDIR = "_baselines"


def resolve_baseline_vrm_filename(
    rank: "Rank",
    manifest: "BaselineVRMManifest",
) -> str:
    """Return the manifest entry for the rank, or "" if unset.

    Pure mapping. Does NOT touch the filesystem — callers do the existence
    check via the avatar-serve route.
    """
    from probos.crew_profile import Rank
    mapping = {
        Rank.ENSIGN: manifest.ensign,
        Rank.LIEUTENANT: manifest.lieutenant,
        Rank.COMMANDER: manifest.commander,
        Rank.SENIOR: manifest.senior,
    }
    return (mapping.get(rank, "") or "").strip()


def resolve_baseline_vrm_path(
    rank: "Rank",
    manifest: "BaselineVRMManifest",
    avatars_dir: Path,
) -> Path | None:
    """Return absolute Path if the tier baseline exists on disk, else None."""
    filename = resolve_baseline_vrm_filename(rank, manifest)
    if not filename:
        return None
    # Defense-in-depth: filename must be a bare name, not a path.
    if "/" in filename or "\\" in filename or ".." in filename:
        logger.warning(
            "AD-721g: baseline VRM filename %r contains path separators; rejecting",
            filename,
        )
        return None
    target = (avatars_dir / _BASELINES_SUBDIR / filename).resolve()
    try:
        target.relative_to(avatars_dir.resolve())
    except ValueError:
        logger.warning("AD-721g: baseline %s escapes avatars_dir; rejecting", filename)
        return None
    if not target.exists() or not target.is_file():
        return None
    return target
```

## Section 3 — Wire into the appearance read path

In `src/probos/routers/agents.py` find the existing fallback chain that produces `appearance_dict["vrm_url"]` (search for `"AD-721d D8: synthesise vrm_url"` block, ~line 160). After the seed-profile fallback and **before** the parametric fallback (the `appearance_dict["vrm_url"] = ""` line), insert a baseline-resolver step:

```python
# AD-721g: per-rank baseline VRM fallback (between seed and parametric).
if not appearance_dict.get("vrm_url"):
    try:
        from probos.avatars.baseline_resolver import resolve_baseline_vrm_filename
        from probos.crew_profile import Rank
        trust_score = float(getattr(crew, "trust_score", 0.0))
        rank = Rank.from_trust(trust_score)
        manifest = runtime.config.avatars.baseline_vrms
        baseline_filename = resolve_baseline_vrm_filename(rank, manifest)
        if baseline_filename:
            # The avatar-serve route (routers/system.py:/system/avatars/{filename})
            # only serves files directly under avatars_dir, not subdirectories.
            # Use a sentinel prefix so the serve route can dispatch.
            appearance_dict["vrm_url"] = f"_baselines/{baseline_filename}"
    except Exception:
        logger.debug("AD-721g: baseline resolution failed", exc_info=True)
```

In `src/probos/routers/system.py:get_avatar` extend the path-traversal guard to permit one specific subdirectory:

```python
# AD-721g: the _baselines/ subdir is allowed; everything else stays flat.
target = (avatars_dir / filename).resolve()
try:
    target.relative_to(avatars_dir.resolve())
except ValueError:
    raise HTTPException(status_code=400, detail="invalid path")
# (existing exists/size checks unchanged)
```

The existing `target.relative_to(avatars_dir)` check already permits subdirectories, so no logic change is needed — but **add a comment** noting AD-721g now uses `_baselines/`.

In `ui/src/components/profile/CrewVRM.tsx:250` the bare-filename resolver already prepends `/api/system/avatars/`; the `_baselines/foo.vrm` path is just an extended filename — confirm Vitest covers this.

## Section 4 — Tests

`tests/test_ad721g_baseline_vrms.py` (+9 pytest):
1. empty manifest → resolver returns `""` for all ranks
2. populated manifest, file present on disk → path returned
3. populated manifest, file missing → `None`
4. filename containing `/` → rejected, logged warning
5. filename containing `..` → rejected
6. filename `_baselines/escape.vrm` (with subdir) → rejected
7. `Rank.from_trust(0.45)` → ENSIGN → maps to `manifest.ensign`
8. `Rank.from_trust(0.92)` → SENIOR → maps to `manifest.senior`
9. integration: agent with empty `vrm_url`, empty seed profile, populated manifest, file present → `GET /appearance` returns `_baselines/<filename>` in `vrm_url`

Use real `AvatarsConfig` and real filesystem via `tmp_path` (no MagicMock — BF-287).

## Section 5 — Docs

`docs/architecture/avatars.md` (or whichever existing doc owns AD-721 — grep first; do **not** create a new doc): add a "Per-tier baseline VRMs" subsection listing the four manifest fields and the operator install location.

`config/system.yaml`: add the `baseline_vrms` block with all four fields set to `""` and a comment block describing the operator install location and the AD-721i-1 license whitelist (CC0/MIT/Apache/BSD/CC-BY).

---

## What This Does NOT Change

- `AppearanceProfile.vrm_url` (`crew_profile.py:266`) shape — still a string.
- Seed-profile fallback (existing `routers/agents.py:79+`) — runs **before** baseline resolution.
- Parametric capsule fallback — runs after baseline resolution when the file is missing.
- Department-aware baselines — explicitly deferred. Rank-only in v1. File a forward marker if Captain wants AD-721g-2.
- AD-721i-1 manifest format — independent. Baselines are a separate, simpler manifest because they're per-rank, not per-crew.

## Tracking

- PROGRESS.md: append AD-721g, increment test count.
- DECISIONS.md: append AD-721g record (per-rank baselines; no bytes shipped; operator installs under `_baselines/`; license whitelist matches AD-721i-1).
- Close #534 on merge.

## Acceptance Criteria

- 9 new pytest tests pass under `-n 4 --dist=loadfile` AND `-n 0`.
- No new files under `data/`, `src/probos/avatars/_baselines/`, or anywhere else that would land .vrm bytes in the repo.
- The four manifest defaults are `""` — ProbOS still boots and operates with zero config.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-17)

```
grep -n "class Rank" src/probos/crew_profile.py
  30: class Rank(Enum):
  31:     ENSIGN = "ensign"
  32:     LIEUTENANT = "lieutenant"
  33:     COMMANDER = "commander"
  34:     SENIOR = "senior_officer"
  39:     def from_trust(cls, trust_score: float) -> "Rank":

grep -n "class AvatarsConfig" src/probos/config.py
  1166: class AvatarsConfig(BaseModel):
  1170:    avatars_dir: str = "data/avatars"

grep -n "class AppearanceProfile" src/probos/crew_profile.py
  266:    vrm_url: str = ""  # "" = parametric fallback

grep -n "synthesise vrm_url" src/probos/routers/agents.py
  160: # AD-721d D8: synthesise vrm_url from rendered cache when DSL is set but

grep -n "/system/avatars" src/probos/routers/system.py
  639: @router.get("/system/avatars/{filename}")
  669: def _resolve_avatars_dir(configured: str) -> Path:

grep -n "load_seed_profile_async" src/probos/crew_profile.py
  761: async def load_seed_profile_async(agent_type: str, profiles_dir: str = "") -> dict[str, Any]:
```
