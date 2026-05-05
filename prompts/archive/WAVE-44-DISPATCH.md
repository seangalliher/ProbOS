# Wave 44 Dispatch — AD-594a v1 Consultation Workspace (Full v1)

**Wave id:** 44
**AD:** AD-594a v1 — Consultation Workspace (Session-Scoped Shared Workspace in Ship's Records)
**Issue:** #160
**Prompt:** `prompts/ad-594a-consultation-workspace-v1.md`
**Baseline test count:** 11078 (post-Wave 43 commit `c0a963f`)
**Expected test count:** 11094 (+16) or floor 11092 (+14 if 2 drop targets removed)
**Mode:** Continuous build, single AD, single commit.

---

## Highest-Risk Reminders (read before starting)

1. **Northstar II Transporter Pattern is NOT the existing builder Transporter.** The roadmap's "Transporter Pattern (Northstar II) for PDF→text, image→description" is a different, future ingestion subsystem. Existing `events.py:57-62` + `cognitive/builder.py` Transporter is for **code-chunk decomposition** in builder. v1 ships the `InputProcessor` Protocol seam in `consultation/inputs.py` with `PassthroughTextProcessor`. Do NOT try to integrate with the builder Transporter — wrong domain. (Prompt DLog #2.)

2. **Ward Room has NO server-side message renderer.** `MessageStore.create_post()` at `ward_room/messages.py:153` stores raw text; rendering is HXI/client-side. v1 ships `[workspace:...]` parser + renderer as pure helpers in `consultation/refs.py`. **Do NOT touch any file under `src/probos/ward_room/`** in this AD. Integration is a separate consumer task. (Prompt DLog #3.)

3. **Workspace files are RAW (no YAML frontmatter).** `RecordsStore.write_entry` always wraps content in `---\n<frontmatter>\n---\n\n<content>`. That's the wrong shape for `manifest.yaml` / `journal.md` / `delivery.yaml` / `workitems/*.yaml`. Section 1 adds three new public methods (`write_workspace_file` / `read_workspace_file` / `append_workspace_file`) that bypass coercion. WorkspaceRegistry consumes ONLY these new public surfaces — never reach into `_safe_path` / `_git` / `_commit` from outside RecordsStore. (Prompt DLog #1.)

4. **`ConsultationWorkspaceConfig.enabled = True` is INTENTIONAL.** Registry is read-only on boot (only side-effect: `consultations/` subdir created at first init via `_SUBDIRS`). Same precedent as `KnowledgeEdgesConfig` / `EdgeBackfillConfig`. **Do NOT flip to False during build.** (Prompt DLog #6.)

5. **Sibling ADs are SEPARATE issues — do NOT smuggle their work in.** AD-594b (#161) consultation primitive, AD-594c (#162) parallel execution dispatch, AD-594d (#163) delivery pipeline. v1 ships an EMPTY `delivery.yaml` placeholder file only. `add_work_item` writes a YAML spec to `workitems/`; it does NOT register with `runtime.work_item_store`. (Prompt Section 6.)

6. **`add_plan_iteration` is filename-based versioning.** Scan `plan/` for `plan_v*.md`, parse trailing integer, write `plan_v{N+1}.md`. First → `plan_v1.md`. No metadata file. (Prompt DLog #9.)

7. **Lifecycle state machine: 7 states, validated transitions only.** `transition_to()` returns `False` on invalid transition (warning log; never raises). On success: updates manifest, refreshes `updated_at`, persists manifest.yaml, appends journal entry. PLAN_REVIEW → CONSULTING is allowed (revision back-edge). (Prompt DLog #12.)

---

## Build Order

1. **Section 1 (RecordsStore):** add `consultations` to `_SUBDIRS` + add three public raw-file methods immediately before `_parse_document`. Single multi_replace bundle if both anchors fit.
2. **Section 2 (consultation package):** create `src/probos/consultation/` with 5 files (`__init__.py`, `refs.py`, `inputs.py`, `templates.py`, `workspace.py`).
3. **Section 3 (config):** new `ConsultationWorkspaceConfig` class + `SystemConfig` field. Single multi_replace bundle.
4. **Section 4 (finalize wirer):** new `_wire_consultation_workspaces` + cascade invocation. Update `consultation/__init__.py` re-exports to include `build_input_processor`. Bundle into multi_replace.
5. **Section 5 (tests):** new `tests/test_ad594a_consultation_workspace.py` with 16 tests. Use real `RecordsStore` (no mocks for the file path); deterministic clock fixture.
6. **Trackers:** PROGRESS.md prepend (anchor on `AD-695 v1 CLOSED.` first sentence per Wave 41 lesson — full first sentence as anchor, not just keyword); roadmap.md status flip (`*(planned, OSS, depends: AD-434 Ship's Records)*` → `*(Complete, OSS, depends: AD-434 Ship's Records)*` at line ~4837); DECISIONS.md prepend at top of Era V (anchor `## Era V — Civilization (Phases 31-36)\n\n### AD-695`).
7. **Test gate:** `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad594a_consultation_workspace.py -v -n 0` first. Then full gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile` — expect **11094** (+16). Floor 11092.
8. **Single commit:** message `Wave 44 build: AD-594a v1 Consultation Workspace + RecordsStore raw-file surfaces (#160)`. Push to `origin/main`.
9. **GH issue close** is BLOCKED by EMU 403 (Waves 31-43 pattern). Captain closes #160 manually with the standard close-comment from prompt Section 7e.

---

## Hard-Stop Conditions

- A Section 1 SEARCH/REPLACE fails to match → re-grep the anchor; do NOT modify the surrounding code (the anchor is verbatim from HEAD).
- The `WorkspaceRegistry` test gate fails with a `RecordsStore` git-commit error → check `auto_commit=False` in fixture (no git init required for raw-file paths).
- `_wire_consultation_workspaces` runs but `runtime.consultation_workspaces` is missing on test boot → check that `runtime.records_store` is populated by the test fixture (or the wirer no-ops cleanly per design).
- Any test attempts to mock `RecordsStore` instead of using a real instance → drop the mock; tests should use `_make_records_store(tmp_path)` factory.
- Any code path tries to import from `src/probos/ward_room/` → reject; v1 ships the parser/renderer as pure helpers only.

---

## Phantom-API Pre-check

Run `scripts/phantom-api-precheck.ps1 -PromptPath prompts/ad-594a-consultation-workspace-v1.md` before commit. Expected:
- `runtime.consultation_workspaces` — FP (introduced by this prompt)
- `WorkspaceRegistry.create` / `.get` / `.list_active` — FP (introduced)
- `ConsultationWorkspace.add_*` / `.transition_to` / `.append_journal` / `.list_paths` — FP (introduced)
- `RecordsStore.write_workspace_file` / `read_workspace_file` / `append_workspace_file` — FP (introduced)
- `class:SimpleNamespace` — FP (stdlib test fixture; same as Waves 27-43)

**0 NEW phantoms expected.** Same FP class as prior waves.

---

## Pre-commit Sanity

- `git diff --shortstat HEAD` — expect ~1500-2000 insertions across 8 files (5 new + records_store + config + finalize + 1 test file). Max deletions per file ≤ 30 (line-level edits to records_store + config + finalize). Well below 200/file threshold. Tracker files (PROGRESS.md/roadmap.md/DECISIONS.md) edited via prepend (small adds + 1-line status flip in roadmap).
- Confirm no edits under `src/probos/ward_room/`.
- Confirm no new EventType added to `events.py`.
- Confirm no new router under `src/probos/routers/`.
- Confirm no edit to `src/probos/api.py`.
