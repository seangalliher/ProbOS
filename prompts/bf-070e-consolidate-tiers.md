# BF-070e: Consolidate Reset Tiers (4 → 3)

## Context

BF-070 implemented a 4-tier reset system. Post-implementation design review identified that **Shore Leave (Tier 2 / `--keep-identity`) creates a broken temporal context** — agents would have identity (birth cert, DID) but zero memories, violating the Westworld Principle ("don't hide the seams"). This is the Blade Runner problem: an identity with amnesia.

The Clean Room / Severance concept is valid but belongs in the **commercial mobility feature** (agent transfers between ProbOS instances), not as a local reset tier.

Additionally, `session_last.json` must move OUT of `--soft` (Tier 1). Soft reset preserves the timeline — stasis recovery should still fire. Only a Recommissioning (new crew) should break the timeline.

## Changes Required

### 1. Remove Shore Leave tier, merge files into Recommissioning

**Before (4 tiers):**
```
Tier 1: Reboot (--soft)         → transients
Tier 2: Shore Leave (--keep-identity) → cognition
Tier 3: Recommissioning (default)     → identity
Tier 4: Maiden Voyage (--full)        → institutional
```

**After (3 tiers):**
```
Tier 1: Reboot (--soft)         → transients (timeline intact)
Tier 2: Recommissioning (default)     → cognition + identity (maiden voyage)
Tier 3: Maiden Voyage (--full)        → + institutional knowledge
```

### 2. Update `RESET_TIERS` data structure

```python
RESET_TIERS = {
    1: {
        "name": "Reboot",
        "flag": "--soft",
        "description": "Runtime transients — safe, timeline intact",
        "files": ["scheduled_tasks.db", "events.db"],
        "dirs": ["checkpoints"],
        # NOTE: session_last.json is NOT here — soft reset preserves stasis detection
    },
    2: {
        "name": "Recommissioning",
        "flag": "(default)",
        "description": "New ship, new crew — maiden voyage",
        "files": [
            # Former Shore Leave (cognition)
            "session_last.json", "chroma.sqlite3", "cognitive_journal.db",
            "hebbian_weights.db", "trust.db", "service_profiles.db",
            # Identity
            "identity.db", "acm.db", "skills.db", "directives.db",
        ],
        "dirs": ["semantic"],
        "special": ["chromadb_uuid_dirs", "knowledge_subdirs", "ontology_instance_id"],
    },
    3: {
        "name": "Maiden Voyage",
        "flag": "--full",
        "description": "Institutional knowledge — organizational memory lost",
        "files": ["ward_room.db", "workforce.db"],
        "dirs": ["ship-records", "scout_reports"],
        "archive_first": ["ward_room.db"],
    },
}
```

### 3. Update `_resolve_tier()`

```python
def _resolve_tier(args: argparse.Namespace) -> int:
    """Determine effective tier from CLI flags."""
    if getattr(args, 'soft', False):
        return 1
    elif getattr(args, 'full', False) or getattr(args, 'wipe_records', False):
        return 3
    else:
        return 2  # default: Recommissioning
```

### 4. Remove `--keep-identity` CLI argument

In the argparse section, remove the `--keep-identity` argument entirely:
```python
# DELETE this line:
reset_parser.add_argument("--keep-identity", action="store_true", help="Tier 2: Shore Leave — wipe cognition, keep identity")
```

### 5. Update all `tier_names` dicts

Every occurrence of the tier_names mapping must change from 4 entries to 3:

```python
# Before:
tier_names = {1: "Reboot", 2: "Shore Leave", 3: "Recommissioning", 4: "Maiden Voyage"}

# After:
tier_names = {1: "Reboot", 2: "Recommissioning", 3: "Maiden Voyage"}
```

Search for ALL occurrences — there are at least 3 (confirmation prompt, dry-run output, summary output).

### 6. Update confirmation prompt "Preserved" section

Since ward_room.db and workforce.db are now only cleared at Tier 3, the preserved list for Tier 2 (default) should show them as preserved. The existing logic should handle this correctly since it iterates tiers above the current tier — just verify it works after renumbering.

### 7. Update tests

All tests referencing tier numbers, `--keep-identity`, or Shore Leave need updating:

- `test_distribution.py::TestProbOSReset` — Remove any `--keep-identity` tests. Update tier assertions:
  - `--soft` → tier 1 (unchanged)
  - Default → tier 2 (was tier 3)
  - `--full` → tier 3 (was tier 4)
  - `--wipe-records` → tier 3 (was tier 4)
- `test_proactive.py::TestResetScope` — Update any tier references
- `test_identity_deterministic.py::TestResetIdentityCleanup` — Update if tier numbers referenced

### 8. Temporal context validation

After the changes, verify these scenarios produce correct lifecycle states:

| Command | Files Surviving | Lifecycle State |
|---------|----------------|-----------------|
| `probos reset -y --soft` then boot | Everything except transients; `session_last.json` SURVIVES | `stasis_recovery` (timeline intact) |
| `probos reset -y` then boot | Nothing cognitive or identity survives | `first_boot` (maiden voyage) |
| `probos reset -y --full` then boot | Nothing survives | `first_boot` (maiden voyage) |

The key test: after `--soft`, the system MUST show stasis recovery, not maiden voyage. The `session_last.json` file must survive a soft reset.

## What NOT to change

- The `_get_file_size()` helper — unchanged
- The `_ALWAYS_PRESERVED` list — unchanged
- The `archive_first` mechanism — unchanged, just at tier 3 instead of tier 4
- The ChromaDB UUID directory cleanup logic — unchanged, just in tier 2 instead of former tier 2
- The git commit logic — unchanged
- `runtime.py` — no changes needed
- The `--dry-run` feature — unchanged (just reflects new tier structure)
- The `--wipe-records` deprecated alias — still works, maps to tier 3 (was tier 4)

## Run tests

```bash
uv run python -m pytest tests/test_distribution.py tests/test_proactive.py tests/test_identity_deterministic.py -x -q
```

All tests must pass. Then run the full suite:

```bash
uv run python -m pytest tests/ -x -q
```
