# BF-264 closeout — OOM crash retroactively resolved by AD-731 (Wave 154)

**GH:** [#636](https://github.com/seangalliher/ProbOS/issues/636). **Status:** Docs-only closeout.

## Resolution

The 2026-05-11 OOM crash (1 MB allocation failure after dream cycle) had AD-730 vision payloads in `IntentMessage.params['vision_messages']` flagged as the most plausible contributor. This was confirmed during the BF-265 → BF-267 → AD-731 wave-151/152 sequence:

- BF-265 stripped `vision_messages` from NATS transport as emergency mitigation (shipped Wave 151, then **reverted in Wave 152** because the inline-base64 wire shape was the root cause, not the transport.)
- AD-731 replaced inline base64 with content-addressable refs (~70 bytes/image instead of 150 KB – 1 MB). `IntentMessage.params` no longer carries image bytes — the bus carries refs; `AttachmentStore` carries blobs. This eliminates the per-process allocator pressure pattern that produced the 1 MB allocation failure.
- AD-734 (Wave 153) codified the wire-shape contract as a CI-runnable pytest so the regression cannot recur silently.

No further code change is required to close BF-264. The hypothesis-list in the BF body (divergence ring buffers, WS push snapshots, NATS retry buffers) remains a useful audit checklist for future memory regressions — those items move into the progress-era retrospective notes as known watch-points, not as open work.

## Scope

1. Append a closeout note to `progress-era-5-unification.md` under the existing AD-731 entry: one bullet referencing this BF closeout, AD number, and the three watch-points (divergence ring buffers, WS push snapshots, NATS retry buffers) as ambient health items rather than fix targets.
2. Comment on GH issue #636 with the resolution summary, link to AD-731 commit + AD-734 prompt, and close.

## Files

- `progress-era-5-unification.md` (one bullet appended).

## Out of scope

- Actual memory profiling infrastructure (separate AD if/when a real regression resurfaces).
- ChromaDB persistence migration (separate architectural AD).
- Per-agent context budget enforcement upgrade (sensorium-budget warning → rejection — separate AD).

## Acceptance

- `progress-era-5-unification.md` modified.
- GH issue #636 closed with a resolution comment that links to the AD-731 commit hash and the AD-734 prompt.
- No code change; no tests.

## Commit

`BF-264 closeout: OOM crash retroactively resolved by AD-731 wire format (Wave 154). Closes #636.`
