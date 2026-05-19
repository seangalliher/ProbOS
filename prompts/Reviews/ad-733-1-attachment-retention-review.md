# GATE 1 Pass-1 Review — AD-733-1 AttachmentStore Retention + Perception-Frame Reaper

**Reviewer:** Architect (Pass-1)
**Date:** 2026-05-18
**Prompt:** `prompts/ad-733-1-attachment-retention.md`
**Closes:** #667
**Verdict:** ✅ **APPROVE** (0 Required, 2 Recommended, 3 Nits, 8 Verified)

A Pass-1 sub-pass flagged `AttachmentsConfig` as a phantom class; verification overturned that finding — the class exists at `src/probos/config.py:1758` and is wired to `Config.attachments` at line 4371. Documented under Verified to memorialize the false-positive (recurring sub-agent grep-scope hazard per `Phantom-via-MagicMock` user-memory lesson — even Pass-1 subagent reviews must be ground-truth-checked).

---

## Required

_None._

---

## Recommended

### R1. Update both `AttachmentStore` Protocol and `FilesystemAttachmentStore` signatures together

The prompt adds an `origin: str = "chat_attachment"` keyword to `FilesystemAttachmentStore.write()` but doesn't explicitly call out that the `AttachmentStore` Protocol at `src/probos/attachments/store.py:22-24` must change in the same commit. With a defaulted kwarg, lint/type-check would still pass if only one is updated, but downstream `mypy --strict` on any future alternative store impl would silently diverge. Add an explicit sub-bullet under Section 2 that names `store.py` and shows the Protocol diff.

### R2. Specify full test file paths

Section 5 lists `test_filesystem_store_origin.py`, `test_attachment_reaper.py`, `test_camera_frame_origin.py` without parent directory. Repo convention (per `tests/` listing) is flat — confirm `tests/test_attachment_reaper.py` etc., not a new `tests/attachments/` subdir. One line at the top of Section 5 fixes this.

---

## Nits

### N1. `browser_stream.py` comment lead-in

The 2026-05-18 working-tree comment reads `# BF: …` (BF-310 hotfix turn). The Builder should retitle to `# AD-733-1: …` when committing Section 4. Mentioned implicitly in the prompt; promote to an explicit Section 4 bullet.

### N2. Sidecar index race-window note

Section 2's atomic-rename pattern is correct, but a one-line note that concurrent `write()` + `unlink()` from the reaper task is serialized via an `asyncio.Lock` on the store instance would foreclose a future correctness question.

### N3. Default `max_store_bytes = 5 GiB` rationale

A one-sentence rationale ("matches typical operator dev-laptop free-space budget; honest-degrade well before disk-full") would head off the "why not 1 GiB / 10 GiB" review question on next-wave audit.

---

## Verified Improvements

✓ `FilesystemAttachmentStore.write` signature at `src/probos/attachments/filesystem_store.py:89-92` matches prompt's claim; the `origin` extension fits cleanly.
✓ `_validate_and_store_attachment` at `src/probos/routers/chat.py:699` matches prompt traceback; `origin` threadable through callers.
✓ `upload_camera_frame` at `src/probos/routers/perception.py:128` matches; reaches `_validate_and_store_attachment` on the prompt's claimed path.
✓ `PerceptionConfig` at `src/probos/config.py:1916` has every field the prompt's "extend" diff anchors against (`enabled`, `camera`, `camera_max_fps_server`, `frame_max_size_bytes`).
✓ **`AttachmentsConfig` exists** at `src/probos/config.py:1758` with `attachments_dir`, `max_attachment_bytes`, `allowed_mime_types`. Wired at `Config.attachments` (line 4371). The `max_store_bytes` extension is a clean addition.
✓ `Cache-Control: no-store` already present on `browser_stream.py` (commit `46ac734b` BF-310 hotfix). Section 4 codification is a one-line comment update + retention test.
✓ `EventType` enum extension point exists; `ATTACHMENT_REAPED` / `ATTACHMENT_STORE_DISK_FULL` fit the established pattern.
✓ Content-addressed substrate (AD-720 SHA-256 keying) preserved — origin tag in sidecar, not in hash key.

---

## Verdict reasoning

Per convention #15 relaxed tolerance: 0 Required + 2 Recommended + 3 Nits = clean APPROVE. Recommended items can be folded into the Builder dispatch as in-line clarifications without a revision pass; Nits are commit-time tidy-ups. No GATE 1 revision cycle required.

Proceed to Pass-2 (formality, single-AD wave with no Required) then GATE 1 approval and Builder dispatch.
