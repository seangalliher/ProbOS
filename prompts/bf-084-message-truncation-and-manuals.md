# BF-084: Ward Room Message Truncation Fix + Manual Seeding

## Problem

Ward Room messages are truncated at multiple layers before agents can read them. The crew independently identified this issue:
- Cortez wrote a `message-truncation-analysis.md` notebook documenting "clean cuts at specific character boundaries"
- Chapel escalated to the Captain: "Truncated messages pose operational safety risk"

### Truncation layers (current limits):

| Location | What | Current Limit |
|---|---|---|
| `ward_room.py:860` | `get_recent_activity()` thread title | 100 chars |
| `ward_room.py:861` | `get_recent_activity()` thread body | 200 chars |
| `ward_room.py:881` | `get_recent_activity()` reply body | 200 chars |
| `proactive.py:619` | dept channel context injection | **150 chars** (bottleneck) |
| `proactive.py:650` | All Hands context injection | **150 chars** (bottleneck) |
| `ward_room.py:1160` | episode user_input recording | 200 chars |
| `ward_room.py:1171` | episode reflection recording | 120 chars |

### Additional deliverable: Manual seeding

Ship's Manuals are reference documentation managed as code in `config/manuals/`. They need to be seeded into `ship-records/manuals/` at startup so agents can read them via `RecordsStore.read_entry()`.

The first manual already exists: `config/manuals/ward-room.md`

## Changes Required

### 1. Raise truncation limits in `proactive.py`

**File:** `src/probos/proactive.py`

- Line 619: Change `[:150]` to `[:500]` — dept channel context body
- Line 650: Change `[:150]` to `[:500]` — All Hands context body

These are the primary bottleneck. 500 chars is ~2-3 sentences, enough for substantive messages without blowing up context budgets.

### 2. Raise truncation limits in `ward_room.py`

**File:** `src/probos/ward_room.py`

- Line 860: Change `row[2][:100]` to `row[2][:200]` — thread title in `get_recent_activity()`
- Line 861: Change `row[3][:200]` to `row[3][:500]` — thread body in `get_recent_activity()`
- Line 881: Change `row[2][:200]` to `row[2][:500]` — reply body in `get_recent_activity()`
- Line 1160: Change `body[:200]` to `body[:500]` — episode user_input
- Line 1171: Change `body[:120]` to `body[:300]` — episode reflection

Do NOT change `title[:100]` on line 971 (episode reflection thread title) — that's fine as-is.
Do NOT change `title[:60]` on line 1171 — thread title in reflection context is fine short.

### 3. Seed manuals from `config/manuals/` into Ship's Records

**File:** `src/probos/knowledge/records_store.py`

Add a `seed_manuals()` method to `RecordsStore`:

```python
async def seed_manuals(self, source_dir: Path) -> int:
    """Seed manuals from source directory into ship-records/manuals/.

    Copies files from config/manuals/ to ship-records/manuals/ with
    ship-classified frontmatter. Overwrites existing manuals (shipyard-managed).
    Returns count of seeded manuals.
    """
```

Logic:
1. Iterate `*.md` files in `source_dir`
2. For each file, read its content
3. Write to `manuals/{filename}` using `write_entry()` with:
   - `author="shipyard"`
   - `classification="ship"` (all crew can read)
   - `status="published"`
   - `department=""` (ship-wide)
   - `topic=` stem of filename (e.g., "ward-room")
   - `tags=["manual"]`
4. Return count of files seeded
5. If `source_dir` doesn't exist, log info and return 0

Important: The manual content in `config/manuals/ward-room.md` does NOT have YAML frontmatter — it starts with `# Ward Room Manual`. The `write_entry()` method adds frontmatter automatically, so just pass the file content as-is.

### 4. Call `seed_manuals()` during startup

**File:** `src/probos/startup/communication.py` (or wherever `RecordsStore.initialize()` is called)

After `records_store.initialize()`, call:

```python
manuals_dir = Path(__file__).resolve().parent.parent.parent.parent / "config" / "manuals"
seeded = await records_store.seed_manuals(manuals_dir)
if seeded:
    logger.info("Seeded %d manual(s) into Ship's Records", seeded)
```

Find where `RecordsStore` is initialized in the startup sequence and add the seeding call right after. Search for `records_store` or `RecordsStore` in `startup/` modules.

### 5. Tests

**File:** `tests/test_bf084_truncation_and_manuals.py`

Tests needed:

1. **test_proactive_ward_room_body_not_truncated_at_150** — Verify that a 400-char message body survives context injection without being cut to 150.

2. **test_get_recent_activity_body_limit_raised** — Verify `get_recent_activity()` returns body content up to 500 chars (not truncated at 200).

3. **test_seed_manuals_copies_files** — Create a temp dir with a manual file, call `seed_manuals()`, verify the file appears in `ship-records/manuals/` with correct frontmatter (author=shipyard, classification=ship, tags=["manual"]).

4. **test_seed_manuals_empty_dir** — Call `seed_manuals()` on an empty/nonexistent dir, verify returns 0, no errors.

5. **test_seed_manuals_overwrites_existing** — Seed a manual, modify it, seed again — verify it's overwritten with the source version (shipyard-managed, not crew-managed).

6. **test_agents_can_read_seeded_manual** — After seeding, call `read_entry("manuals/ward-room.md", reader_id="any_agent")` and verify content is returned (ship classification = readable by all).

## Validation

1. All new + existing tests pass: `pytest tests/ -x -q`
2. `grep -rn "150" src/probos/proactive.py` should show no Ward Room body truncation at 150
3. Manual file exists in ship-records after startup

## Context

- Crew independently diagnosed this issue (Cortez notebook, Sinclair observation, Chapel CMO escalation)
- Standing orders (`config/standing_orders/ship.md`) already updated to tell agents about the limit
- First manual exists at `config/manuals/ward-room.md`
- `RecordsStore` already has `read_entry()` and `list_entries()` — agents can read manuals once they're seeded
- Manuals retention policy: permanent (in `.shiprecords.yaml`)
