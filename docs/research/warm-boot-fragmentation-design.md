# Warm-Boot State Fragmentation — Design (Implementation Deferred)

**AD:** AD-717
**Issue:** [#501](https://github.com/seangalliher/ProbOS/issues/501)
**Type:** Pure design AD — no production code in this AD
**Status:** Design complete. Implementation tracked as **AD-717-1**.
**Date:** 2026-05-08

---

## Background — what fragmentation looks like

When ProbOS warm-boots after an unclean shutdown — power loss mid-cycle, OOM kill, container respawn during a dream consolidation — the on-disk state can be **fragmented**: anchors written without their backing episode, dream-cycle markers missing, trust deltas applied but the corresponding `TrustEvent` not persisted. Today, the boot path treats every persisted record as ground truth and proceeds. The result: the runtime quietly carries "ghost" state forward, which corrupts trust scoring, recall, and Hebbian routing for the rest of the session.

Reed (lab notes, 2026-04) listed three concrete cases:

1. **Anchor-temporal mismatch.** An `Episode` row exists but its `AnchorFrame.source_timestamp` predates the Episode's `timestamp` by an unreasonable window (>24h). Indicates the anchor was carried forward from a previous, related episode and the new episode's anchor was never stamped.
2. **Missing dream-cycle markers.** A dream cycle's `start_marker` is present in the EventLog but the matching `end_marker` is not. The cycle was killed mid-flush. Working-memory entries (`wm_entries_flushed`) may have been only partially promoted to episodes.
3. **Stale trust deltas.** A `TrustEvent` is in the in-memory `_event_log` deque (`trust.py:128`) for the previous session, but the corresponding `TrustRecord.alpha`/`beta` write to SQLite was lost at shutdown. The deque is rebuilt from SQLite on warm boot — so the **delta is lost**, but the dampening state may have been computed against the lost delta and persisted.

Sentinel's coordination note (2026-05-01) added a fourth: cross-component drift between the AuditLog hash chain (AD-456) and the EventLog hash chain (AD-490, just shipped this wave). If both chains are intact individually but they reference different "last known good" timestamps for the same logical event, the warm boot is in a split-brain state and the recovery rule has to pick a winner.

## The design

### Fragmentation detection — three heuristics

**H1. Anchor-temporal mismatch.**
On warm boot, scan recent episodes (last `N=200` by timestamp). For each: if `anchors.source_timestamp > 0` and `abs(episode.timestamp - anchors.source_timestamp) > 86400 * 30` (30 days), flag as `ANCHOR_TIME_MISMATCH`. **Threshold reasoning:** the 30-day window is conservative. Tighter windows (e.g. 7 days) risk false positives during natural temporal-validity flows, where an anchor legitimately references a backdated artifact. Wider windows (e.g. 90+ days) miss most real fragmentation. The implementation AD MUST NOT bikeshed this number from scratch — either accept 30 days or empirically tune against fragment-recovery test fixtures.

**H2. Missing dream-cycle markers.**
Scan the EventLog for the most recent `DREAM_CYCLE_START` event. If the next event in `category="dream"` is NOT a `DREAM_CYCLE_END` AND the start event is older than 1h (typical dream cycle duration), flag as `INCOMPLETE_DREAM_CYCLE`. Record the start event's `id` for triage.

**H3. Stale trust delta.**
On warm boot, after `TrustNetwork._load_from_db()`, compare each `TrustRecord` against the EventLog's last `category="trust"` entries. If the EventLog records a trust update at timestamp `t1` for agent `A` but `TrustRecord(A).updated < t1`, flag as `STALE_TRUST_DELTA`. The EventLog hash chain (AD-490) gives us a tamper-evident witness — its timestamps are the truth.

**H4 (Sentinel addendum). Hash-chain cross-drift.**
If both `AuditLog.verify_chain()` and `EventLog.verify_chain()` return `(ok=True, broken_at=None)`, but the `AuditLog`'s most recent `entry.timestamp` and the `EventLog`'s most recent `events.timestamp` differ by more than 60 seconds for any shared correlation_id, flag as `HASH_CHAIN_CROSS_DRIFT`. **Threshold reasoning:** 60 seconds is aggressive. Wall-clock skew between the two hash-chained writers can legitimately produce a few seconds of drift; >60s implies the chains are referencing different logical events. The implementation AD MUST NOT loosen this past 5 minutes without explicit justification — the whole point is detecting split-brain.

### Triage rules — safe-discard vs. recovery

For each detected fragmentation, classify:

- **SAFE_DISCARD** — the fragment can be deleted with no information loss for the user.
  - `ANCHOR_TIME_MISMATCH` with the offending anchor entirely → discard the anchor (clear `source_timestamp`), keep the episode. The episode is still recall-able by content.
  - `INCOMPLETE_DREAM_CYCLE` whose start is > 24h old → discard the entire partial cycle's intermediate state. Schedule a fresh dream cycle on the next idle window.

- **RECOVERY** — the fragment encodes information we want to keep; reconstruct from witnesses.
  - `STALE_TRUST_DELTA` → re-apply the EventLog's recorded delta to the in-memory `TrustRecord` and re-persist. The hash-chained EventLog is the source of truth.
  - `INCOMPLETE_DREAM_CYCLE` < 1h old → checkpoint resume (see below) if we have a checkpoint; otherwise SAFE_DISCARD.
  - `HASH_CHAIN_CROSS_DRIFT` → log to a quarantine file under `data/recovery/`, refuse to use either chain's affected entries, surface to the operator. Do NOT auto-recover — drift indicates external tampering or bug.

### Minimum-stasis threshold

Warm boot must complete the fragmentation scan before any agent processes a user intent. Define `MIN_BOOT_STASIS_SECONDS=2.0` as a deliberate quiet window (the scan is fast for `N=200` records; the stasis is to ensure no race with concurrent shutdown of a sibling service). Operators can tune via `WarmBootConfig.min_stasis_seconds`.

If the scan exceeds `MAX_BOOT_STASIS_SECONDS=30.0` (default), abort recovery, log every detected fragment, and refuse to start. A human reviews `data/recovery/fragments-{timestamp}.json` and either fixes manually or runs `probos recover --force-discard`.

### Optional checkpoint-resume

For `INCOMPLETE_DREAM_CYCLE` recovery: the dream pipeline writes an idempotent `DreamCheckpoint` to disk every N working-memory entries (proposal: every 50). On warm boot, if a checkpoint exists with timestamp later than the last `DREAM_CYCLE_START`, resume from the checkpoint instead of restarting the cycle. The checkpoint format is a frozen dataclass (TBD in implementation AD); v1 design constraint: **the checkpoint carries its own SHA-256 self-hash. On warm boot, the hash is recomputed over the checkpoint body (excluding the hash field itself) and compared. If the comparison fails, the checkpoint is discarded as if it had never been written — the dream cycle restarts from the last `DREAM_CYCLE_START`. Recursive detection is bounded: the checkpoint's own SHA-256 is its only fragmentation witness; no nested fragment-of-fragment recursion is permitted.**

### Configuration shape (proposed)

```yaml
warm_boot:
  enabled: true
  min_stasis_seconds: 2.0
  max_stasis_seconds: 30.0
  scan_recent_n: 200
  anchor_mismatch_threshold_seconds: 2592000   # 30 days
  hash_chain_drift_threshold_seconds: 60
  checkpoint_dream_cycle: false                # opt-in until tested
  fragment_quarantine_dir: "data/recovery"
```

Defaults: `enabled = true` (this is a safety mechanism); `checkpoint_dream_cycle = false` (transitional; flip after the implementation AD's `-1` follow-up).

**Wave 10 convention #14 carve-out:** `warm_boot.enabled` is the **only** `enabled: true` default in Wave 130. Convention #14 normally forbids transitional `enabled: True` defaults that flip on first commit; here, the warm-boot fragmentation scan is a **safety mechanism**, not a transitional feature. A boot-time scan that's off-by-default would silently miss the very fragmentation it exists to catch. Reviewers: do not flag this as a #14 violation, and do NOT copy the `enabled: true` default as precedent for non-safety features.

### Event taxonomy (no new EventType in this design AD)

Implementation will add (deferred to AD-717-1):

- `WARM_BOOT_FRAGMENT_DETECTED` — payload includes fragment kind, target id, classification.
- `WARM_BOOT_FRAGMENT_RECOVERED` — successful recovery.
- `WARM_BOOT_FRAGMENT_QUARANTINED` — fragment written to quarantine; operator review needed.
- `WARM_BOOT_STASIS_EXCEEDED` — boot refused.

This AD names them so the implementation AD does not have to re-bikeshed.

## Out of scope (HARD)

- **Implementation.** Zero production code in this AD. The deliverable is this design document and the `DECISIONS.md` entry.
- **Cold-boot recovery** (corrupted SQLite file, deleted data dir). Cold boot is a different recovery class — separate AD.
- **Federation-side fragmentation** (foreign chain snapshots desyncing across peer ships). Separate AD.
- **HXI surface** for fragment review. Operator-CLI-only in the implementation AD.

## Status

Design complete. Implementation tracked as **AD-717-1** (filed when this design AD lands).
