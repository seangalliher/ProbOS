# Wave 173 — Builder Dispatch (AD-733-1 AttachmentStore retention + reaper)

**Status:** GATE 1 approved (Pass-1 + Pass-2, 0 Required). Ready for Builder.
**Closes:** #667.
**Starting SHA:** `61c6b375` (Wave 172 close, pushed).
**Estimated:** ~4 h, single commit (or 2 logical sub-commits), +14 pytest.

## Build dispatch

  Build Wave 173 — single-AD continuous build mode.

  Read first (in order):
    - prompts/BUILDER-EXECUTION-PLAN.md
    - .github/copilot-instructions.md
    - DECISIONS.md (Wave 5/5-7/8 retrospectives — 19 standing conventions; AD-720 entry)
    - prompts/Reviews/README-wave-173-pass-2.md (GATE 1 verdict: APPROVE)
    - prompts/Reviews/ad-733-1-attachment-retention-review.md (full review)
    - prompts/ad-733-1-attachment-retention.md (the build prompt)

  Pre-flight:
    cd D:\ProbOS
    git pull --ff-only
    git status --short                                                # must be empty (after stashing the GATE 1 reviews if not yet committed)
    git rev-parse HEAD                                                # expect 61c6b375 (or descendant)
    d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile # green baseline (~14108 tests)

  Implementation order (per prompt sections):
    1. Section 1 — Config knobs. PerceptionConfig.frame_retention_seconds (300s default),
       PerceptionConfig.reaper_interval_seconds (60s default), AttachmentsConfig.max_store_bytes
       (5 GiB default, 0=disabled).
    2. Section 2 — AttachmentStore Protocol + FilesystemAttachmentStore with origin tag
       (chat_attachment | perception_frame | browser_screenshot | avatar_render),
       sidecar .index.json, atomic rename, asyncio.Lock serialization, new unlink/
       list_by_origin/total_size_bytes methods, AttachmentStoreFullError on ENOSPC.
       ** Both Protocol AND impl in same commit (Architect R1).**
    3. Section 3 — New src/probos/attachments/reaper.py AttachmentReaper. start/stop/sweep_once.
       Two policies (age-TTL for perception_frame, LRU cap for store-total). Honest-degrade
       on filesystem errors. Emits ATTACHMENT_REAPED.
    4. Section 4 — browser_stream.py: retitle comment from "# BF:" to "# AD-733-1:"
       (Architect N1). Working-tree already has Cache-Control: no-store from BF-310 (commit 46ac734b).
       Add a test asserting the header presence if not already present.
    5. Section 5 — EventType additions (ATTACHMENT_REAPED, ATTACHMENT_STORE_DISK_FULL).
       Replace bare 500 in upload_camera_frame / _validate_and_store_attachment with 503 + Retry-After
       on OSError(errno=ENOSPC).
    6. Wiring — startup/finalize.py constructs AttachmentReaper when
       (perception.enabled or attachments.max_store_bytes > 0). startup/shutdown.py mirrors
       the recording_reaper pattern (2s grace stop).
    7. Threading — _validate_and_store_attachment accepts origin kwarg;
       upload_camera_frame passes "perception_frame"; chat callers default to "chat_attachment".

  Architect clarifications (already folded into prompt; restate at code-review):
    R1: Update AttachmentStore Protocol (src/probos/attachments/store.py:22-24) AND
        FilesystemAttachmentStore (src/probos/attachments/filesystem_store.py:89-92) in same commit.
    R2: Tests live flat under tests/ (no tests/attachments/ subdir):
          tests/test_filesystem_store_origin.py    (+5)
          tests/test_attachment_reaper.py          (+7)
          tests/test_camera_frame_origin.py        (+2)
    N1: browser_stream.py comment lead-in retitled from "# BF:" to "# AD-733-1:".
    N2: One-line note in Section 2 implementation: concurrent write/unlink serialized via
        asyncio.Lock on the store instance.
    N3: One-sentence rationale comment beside max_store_bytes = 5 GiB
        ("matches typical operator dev-laptop free-space budget; honest-degrade well before disk-full").

  Tests (target +14 pytest):
    tests/test_filesystem_store_origin.py   — origin round-trip, sidecar persistence,
                                              concurrent write serialization, unlink+index sync,
                                              corrupt .index.json recovery (5)
    tests/test_attachment_reaper.py         — age-TTL sweep (perception_frame only),
                                              parametrized retention seconds,
                                              LRU cap evicts perception first then chat,
                                              max_store_bytes=0 disables LRU,
                                              FileNotFoundError mid-sweep no-raise,
                                              PermissionError mid-sweep no-raise,
                                              start/stop round-trip <2s (7)
    tests/test_camera_frame_origin.py       — upload_camera_frame tags perception_frame,
                                              chat paste tags chat_attachment (2)

  Per-section gate (focused):
    d:/ProbOS/.venv/Scripts/pytest.exe tests/test_filesystem_store_origin.py tests/test_attachment_reaper.py tests/test_camera_frame_origin.py -q -n 0

  Post-build gate (full):
    d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile

  Expected: 0 net failures, test count strictly greater than baseline.

  UI gate: This AD does NOT touch ui/src/**. If the diff shows any UI file changed,
  hard-stop and surface.

  Commit shape — single commit preferred:
    git add -A
    git commit -m "AD-733-1: AttachmentStore retention + perception-frame reaper (closes #667)"

  If logically two commits feel cleaner, split:
    1. AD-733-1: AttachmentStore origin tagging + sidecar index + ENOSPC handling
    2. AD-733-1: AttachmentReaper janitor + wiring + tests (closes #667)

  Hard-stop conditions (do NOT push; surface):
    - Phantom API discovered (revise prompt before continuing).
    - Test count would decrease.
    - Pre-existing test breaks.
    - Architectural change required outside prompt scope.
    - ui/src/** touched (this AD shouldn't).

  DO NOT push. Stop after post-build gate is green. Report:
    1. Commit SHA(s) created.
    2. Test count before / after.
    3. `git diff --stat origin/main..HEAD`.
    4. Any deviations from prompt or this dispatch (with rationale).
    5. Confirmation each Architect clarification (R1, R2, N1, N2, N3) applied.

  GATE 2 (Architect inspection of diffs) happens after the Builder reports back.
  Push and GATE 3 (close #667) follow GATE 2 approval.

## Notes for Architect at GATE 2

- Verify `data/attachments/.index.json` is in `.gitignore` (or that the test fixture
  writes to a tmp path so the index doesn't leak into commits).
- Confirm `ATTACHMENT_REAPED` event emission threading goes through the runtime's
  configured event bus, not a direct file write.
- Spot-check that `_validate_and_store_attachment` callers all default to
  `chat_attachment` if they don't explicitly pass `origin`.
- The single failing wave file (if any environmental flake) should be re-run at `-n 0`
  to confirm.
