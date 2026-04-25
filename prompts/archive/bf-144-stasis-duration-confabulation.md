# BF-144: Stasis Duration Confabulation — agents fabricate offline duration

**Priority:** High (Bridge officer posted fabricated "2d 22h" stasis when actual was 6 minutes)
**Estimated tests:** 6–8 new tests

## Context

After stasis recovery, agents confabulate the offline duration instead of citing the authoritative value provided in their orientation. Observed behavior:

1. Meridian (First Officer) posted "2d 22h offline period" — actual stasis was 6 minutes
2. When corrected by Captain, Meridian said "3 minutes" — still wrong (actual: ~6 minutes)
3. Echo (Counselor) correctly flagged this as temporal disorientation

The system provides the correct duration in two places:
- **Warm boot orientation** → `"You were offline for 6m 19s."`
- **Ward Room All Hands announcement** → `"Stasis duration: 6m 19s."`

Both are correct. The agent ignores them and generates its own estimate.

### Root Cause

The stasis duration is a single narrative sentence buried in prose:
```
STASIS RECOVERY:
You were offline for 6m 19s.
Your identity and memories are intact — you are still Meridian, ...
```

LLMs treat narrative prose as background context and generate their own plausible-sounding numbers. The duration needs to be presented as **structured authoritative data** that the agent is instructed to cite, not estimate.

### Why this matters

Temporal grounding is foundational. If an agent can't accurately report how long it was offline — when the answer is literally in its system prompt — every other temporal claim it makes is suspect. Echo was right to flag it.

## Engineering Principles

- **Fail Fast:** If the orientation text doesn't prevent confabulation, the format is wrong. Fix the format.
- **Defense in Depth:** Provide the duration in structured format AND add an explicit instruction not to estimate differently.
- **Westworld Principle:** Agents know what they are and what happened to them. Fabricating stasis duration violates "no fake memories."

## Fix

### File: `src/probos/cognitive/orientation.py`

**Change 1 — Add shutdown/resume timestamps to `OrientationContext`.**

Add two new fields to the `OrientationContext` dataclass (line 25):

```python
@dataclass(frozen=True)
class OrientationContext:
    """Structured orientation for agent cognitive grounding."""

    # Identity
    callsign: str = ""
    post: str = ""  # role title
    department: str = ""
    department_chief: str = ""
    reports_to: str = ""
    rank: str = ""
    # Ship context
    ship_name: str = ""
    crew_count: int = 0
    departments: list[str] = field(default_factory=list)
    # Lifecycle
    lifecycle_state: str = ""
    agent_age_seconds: float = 0.0
    stasis_duration_seconds: float = 0.0
    # BF-144: Authoritative timestamps for stasis recovery
    stasis_shutdown_utc: str = ""   # ISO format, e.g. "2026-04-10 18:15:34 UTC"
    stasis_resume_utc: str = ""     # ISO format, e.g. "2026-04-10 18:21:53 UTC"
    # Cognitive grounding
    episodic_memory_count: int = 0
    has_baseline_trust: bool = True
    anchor_dimensions: list[str] = field(
        default_factory=lambda: ["temporal", "spatial", "social", "causal", "evidential"]
    )
    social_verification_available: bool = False
    crew_names: list[str] = field(default_factory=list)
```

**Change 2 — Pass timestamps through `build_orientation()`.**

Update `build_orientation()` (line 90) to accept and pass through the timestamps:

```python
def build_orientation(
    self,
    agent: Any,
    *,
    lifecycle_state: str = "",
    stasis_duration: float = 0.0,
    stasis_shutdown_utc: str = "",    # BF-144
    stasis_resume_utc: str = "",      # BF-144
    crew_count: int = 0,
    departments: list[str] | None = None,
    episodic_memory_count: int = 0,
    trust_score: float = 0.5,
    crew_names: list[str] | None = None,
) -> OrientationContext:
```

And in the `return OrientationContext(...)` block (line 151), add:

```python
    stasis_shutdown_utc=stasis_shutdown_utc,
    stasis_resume_utc=stasis_resume_utc,
```

**Change 3 — Reformat `render_warm_boot_orientation()` stasis section.**

Replace lines 262–274 (`# Section 1: Stasis Summary`) with structured authoritative format:

```python
    # Section 1: Stasis Record (BF-144: structured authoritative data)
    dur_str = format_duration(ctx.stasis_duration_seconds) if ctx.stasis_duration_seconds > 0 else "a brief period"
    stasis_lines = [
        "STASIS RECORD (AUTHORITATIVE — cite this, do not estimate):",
        f"  Duration: {dur_str}",
    ]
    if ctx.stasis_shutdown_utc:
        stasis_lines.append(f"  Shutdown: {ctx.stasis_shutdown_utc}")
    if ctx.stasis_resume_utc:
        stasis_lines.append(f"  Resume: {ctx.stasis_resume_utc}")
    stasis_lines.extend([
        "",
        f"Your identity and memories are intact — you are still {ctx.callsign or 'yourself'}"
        f"{', ' + ctx.post + ' in ' + ctx.department if ctx.post and ctx.department else ''}.",
    ])
    if ctx.episodic_memory_count > 0:
        stasis_lines.append(
            f"You have {ctx.episodic_memory_count} episodic memories from before stasis."
        )
    parts.append("\n".join(stasis_lines))
```

Key changes from original:
- Header: `"STASIS RECOVERY:"` → `"STASIS RECORD (AUTHORITATIVE — cite this, do not estimate):"`
- Duration: `"You were offline for 6m 19s."` → `"  Duration: 6m 19s"` (structured key-value, not narrative)
- Added: shutdown and resume timestamps when available
- Preserved: identity confirmation, episodic memory count

### File: `src/probos/startup/finalize.py`

**Change 4 — Pass shutdown/resume timestamps to `build_orientation()` call.**

Update the `build_orientation()` call at line 470 to include timestamps. The data is already available — `runtime._previous_session` has `shutdown_time_utc`, and current time is the resume time.

```python
    # BF-144: Compute authoritative stasis timestamps
    _shutdown_str = ""
    _resume_str = ""
    if runtime._previous_session and "shutdown_time_utc" in runtime._previous_session:
        from datetime import datetime, timezone
        _shutdown_str = datetime.fromtimestamp(
            runtime._previous_session["shutdown_time_utc"], tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%S UTC")
        _resume_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
```

Note: `datetime` and `timezone` are already imported in finalize.py (used at line 368). If the import is inside a block scope, move it to the module level or add it where needed.

Then update the `build_orientation()` call:

```python
    _ctx = runtime._orientation_service.build_orientation(
        agent,
        lifecycle_state="stasis_recovery",
        stasis_duration=runtime._stasis_duration,
        stasis_shutdown_utc=_shutdown_str,       # BF-144
        stasis_resume_utc=_resume_str,           # BF-144
        episodic_memory_count=_ep_count,
        trust_score=_trust,
        crew_names=_crew_names,
    )
```

Compute `_shutdown_str` and `_resume_str` **once before the agent loop** (not per-agent) since these values are the same for all agents.

### No changes to other files

- `runtime.py` — already stores `_previous_session`, `_stasis_duration`, `_lifecycle_state`
- `cognitive_agent.py` — no changes; receives orientation via `set_orientation()`
- `cognitive_services.py` — correctly calculates `stasis_duration` from `session_last.json`
- `__main__.py` / `shutdown.py` — session record write path unchanged

## Tests

### File: `tests/test_orientation.py`

**Update existing `_make_context` helper** (line 55) to include new fields with defaults:

```python
def _make_context(**overrides) -> OrientationContext:
    defaults = dict(
        callsign="Vega",
        post="Security Agent",
        department="Security",
        department_chief="Worf",
        reports_to="Worf",
        rank="Ensign",
        ship_name="ProbOS",
        crew_count=12,
        departments=["Security", "Engineering", "Medical", "Science"],
        lifecycle_state="cold_start",
        agent_age_seconds=0.0,
        stasis_duration_seconds=0.0,
        stasis_shutdown_utc="",         # BF-144
        stasis_resume_utc="",           # BF-144
        episodic_memory_count=0,
        has_baseline_trust=True,
        social_verification_available=False,
    )
    defaults.update(overrides)
    return OrientationContext(**defaults)
```

**Update existing test `test_warm_boot_orientation_stasis_duration`** (line 179) — the assertion needs to match the new format:

```python
    def test_warm_boot_orientation_stasis_duration(self) -> None:
        svc = _make_service()
        ctx = _make_context(
            lifecycle_state="stasis_recovery",
            stasis_duration_seconds=3600.0,
        )
        text = svc.render_warm_boot_orientation(ctx)
        # BF-144: Structured format with "AUTHORITATIVE" header
        assert "AUTHORITATIVE" in text
        assert "Duration:" in text
        assert "1h" in text or "3600" in text
```

**Add new test class:**

```python
class TestStasisConfabulationGuardBF144:
    """BF-144: Stasis orientation must use structured authoritative format."""

    def test_authoritative_header_present(self) -> None:
        """Orientation must include AUTHORITATIVE marker to resist confabulation."""
        svc = _make_service()
        ctx = _make_context(
            lifecycle_state="stasis_recovery",
            stasis_duration_seconds=379.0,
        )
        text = svc.render_warm_boot_orientation(ctx)
        assert "AUTHORITATIVE" in text
        assert "cite this" in text.lower() or "do not estimate" in text.lower()

    def test_structured_duration_format(self) -> None:
        """Duration must be in key-value format, not narrative prose."""
        svc = _make_service()
        ctx = _make_context(
            lifecycle_state="stasis_recovery",
            stasis_duration_seconds=379.0,
        )
        text = svc.render_warm_boot_orientation(ctx)
        # Must contain "Duration: 6m 19s" not "You were offline for 6m 19s."
        assert "Duration:" in text
        assert "6m 19s" in text

    def test_shutdown_timestamp_included(self) -> None:
        """Shutdown timestamp must appear when provided."""
        svc = _make_service()
        ctx = _make_context(
            lifecycle_state="stasis_recovery",
            stasis_duration_seconds=379.0,
            stasis_shutdown_utc="2026-04-10 18:15:34 UTC",
        )
        text = svc.render_warm_boot_orientation(ctx)
        assert "Shutdown:" in text
        assert "2026-04-10 18:15:34 UTC" in text

    def test_resume_timestamp_included(self) -> None:
        """Resume timestamp must appear when provided."""
        svc = _make_service()
        ctx = _make_context(
            lifecycle_state="stasis_recovery",
            stasis_duration_seconds=379.0,
            stasis_resume_utc="2026-04-10 18:21:53 UTC",
        )
        text = svc.render_warm_boot_orientation(ctx)
        assert "Resume:" in text
        assert "2026-04-10 18:21:53 UTC" in text

    def test_timestamps_omitted_when_empty(self) -> None:
        """No Shutdown/Resume lines when timestamps are not provided."""
        svc = _make_service()
        ctx = _make_context(
            lifecycle_state="stasis_recovery",
            stasis_duration_seconds=379.0,
            stasis_shutdown_utc="",
            stasis_resume_utc="",
        )
        text = svc.render_warm_boot_orientation(ctx)
        assert "Shutdown:" not in text
        assert "Resume:" not in text
        # Duration still present
        assert "Duration:" in text

    def test_identity_still_preserved(self) -> None:
        """BF-144 format change must not remove identity confirmation."""
        svc = _make_service()
        ctx = _make_context(
            callsign="Meridian",
            lifecycle_state="stasis_recovery",
            stasis_duration_seconds=379.0,
        )
        text = svc.render_warm_boot_orientation(ctx)
        assert "Meridian" in text
        assert "identity" in text.lower() or "intact" in text.lower() or "still" in text.lower()

    def test_build_orientation_passes_timestamps(self) -> None:
        """build_orientation() must accept and forward stasis timestamps."""
        svc = _make_service()

        class FakeAgent:
            callsign = "Echo"
            agent_type = "counselor"
            rank = "Lieutenant"
            _birth_timestamp = None

        ctx = svc.build_orientation(
            FakeAgent(),
            lifecycle_state="stasis_recovery",
            stasis_duration=379.0,
            stasis_shutdown_utc="2026-04-10 18:15:34 UTC",
            stasis_resume_utc="2026-04-10 18:21:53 UTC",
        )
        assert ctx.stasis_shutdown_utc == "2026-04-10 18:15:34 UTC"
        assert ctx.stasis_resume_utc == "2026-04-10 18:21:53 UTC"
```

## Verification

```bash
# BF-144 tests
python -m pytest tests/test_orientation.py -k "BF144" -v

# Regression — existing warm boot orientation tests
python -m pytest tests/test_orientation.py -v

# Full orientation + finalize regression
python -m pytest tests/test_orientation.py tests/test_finalize.py -v
```

## Files Modified (Summary)

| File | Change |
|------|--------|
| `src/probos/cognitive/orientation.py` | Add `stasis_shutdown_utc` + `stasis_resume_utc` to `OrientationContext`; update `build_orientation()` signature; reformat stasis section in `render_warm_boot_orientation()` to structured authoritative format |
| `src/probos/startup/finalize.py` | Compute shutdown/resume timestamp strings; pass to `build_orientation()` call |
| `tests/test_orientation.py` | Update `_make_context` helper + existing stasis test; add `TestStasisConfabulationGuardBF144` (7 tests) |

**2 source files modified, 1 test file modified, ~7 tests added.**
