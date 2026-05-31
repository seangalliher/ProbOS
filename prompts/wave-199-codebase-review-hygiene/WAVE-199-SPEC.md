# Wave 199 — Codebase Review Hygiene (BF-325..328)

**Kind:** bf (bug-fix + hygiene cluster, small-AD fast path)
**Source:** `docs/development/codebase-review-2026-05-30.md` (Architect read-only review)
**Issues to close:** #800 (P0), #801, #802, #803
**Builder required:** yes
**Workflow:** small-AD fast path — Architect + Builder same author, single review pass, full-suite green gate before commit.

---

## Why this wave

A read-only codebase review on 2026-05-30 found four untracked engineering-quality
issues. The most serious is that **`main` is a red test gate** (#800). The other three
are repo-hygiene / test-isolation / docs-staleness items. All four are verified against
the live tree (grep + reproduction). No feature gaps — those are already covered by the
14 open forward-marker issues.

Ground-truth verification performed (do not re-litigate):
- #800 reproduced live: `pytest tests/test_ad443_mobility.py -q -n 0` → `11 failed, 46 passed`,
  `NameError: name 'TransferCertificate' is not defined` at `src/probos/identity.py:1139`.
- #801: `D:\ProbOS\MagicMock\` exists with `mock.*` subdirs (e.g. `mock.config.desktop.lock_file/`,
  `mock.data_dir/<objid>/`). Same pollution in the commercial repo.
- #802: `git ls-files` tracks `.tmp_issue160.txt`, `PROGRESS.md.new`, `tmp_test.txt`; 12 untracked
  `test_output*.txt` / `tmp_*.txt` at repo root. `.gitignore` already has `test_output*.txt` and
  `MagicMock/` but NOT `tmp_*.txt`, and the tracked scratch files predate the ignore rules.
- #803: `docs/development/open-ads-report.md` header reads "Generated 2026-03-31. 87 open ADs + 7
  open bugs" — stale by ~Wave 198 / AD-828.

---

## BF-325 — P0: fix red `main` gate (closes #800)

**File:** `src/probos/identity.py`

`TransferCertificate` is referenced at L1113 (`-> TransferCertificate`), L1139 (constructed),
and L1177 (param annotation) but **never imported**. The module uses
`from __future__ import annotations`, so the annotations are lazy strings and the module
imports cleanly — the bug only fires at runtime when
`AgentIdentityRegistry.issue_transfer_certificate()` constructs the object at L1139.

`TransferCertificate` is defined in `src/probos/mobility.py:96`. Verified: `mobility.py` does
**not** import `probos.identity`, so a top-level import has **no circular-import risk**.

**Fix:**
- Add `from probos.mobility import TransferCertificate` to the import block at the top of
  `identity.py` (alongside `from probos.captain_card.card import CaptainCard` ~L33).
- While in that block, remove the **duplicate `import hashlib`** (it appears at both L22 and L32).

**Acceptance:** `pytest tests/test_ad443_mobility.py -q -n 0` → all pass (57 tests; was 11 failed / 46 passed).

**Do NOT:** change any transfer logic, signatures, or the `TransferCertificate` dataclass. Import-only fix.

---

## BF-326 — MagicMock working-tree pollution (closes #801)

Tests that pass a bare `MagicMock()` where a real filesystem path is expected cause production
`mkdir(parents=True, exist_ok=True)` to create literal `./MagicMock/mock.<attr>/...` directories.

Verified construction/start sites that `mkdir`:
- `src/probos/artifacts/__init__.py:93` — `self._db_path.parent.mkdir(...)` in **`ArtifactStore.__init__`**
  (`Path(db_path)` where `db_path` is a mock → pollution at construction).
- `src/probos/acm.py:112` — `self._data_dir.mkdir(...)` in **`async start()`** (NOT the constructor;
  the review said "construction" — correct this in the fix notes). Pollution occurs when a test
  `await`s `start()` with a mock `_data_dir`.
- Other `mkdir(parents=True, exist_ok=True)` sites reachable with a mock path (e.g. desktop lock file
  → `mock.config.desktop.lock_file/`). Enumerate with the guard below rather than guessing.

**Fix (root-cause, test-side — do not add defensive can't-happen-in-prod guards to production code):**
1. Add an autouse guard in `tests/conftest.py` that surfaces any `MagicMock/`
   directory appearing in the repo root during/after the session.
   (If `tests/conftest.py` already exists, extend it; do not clobber existing fixtures.)
2. **Outcome of enumeration (revised during execution):** the guard, run hard-fail at first,
   revealed the pollution is NOT 3-4 tests but **~18 API test modules / 100+ tests**, each
   reaching `mkdir` through *different* path vectors (`create_app` static mounts, `finalize`
   data-dir, `DesktopLifecycle` lock-file, avatar/telemetry dirs). Per-file mock neutralization
   is therefore unbounded whack-a-mole — and was demonstrated insufficient (setting
   `_data_dir`/`data_dir` to `None` on 3 files still left them polluting via other vectors).
   **Resolution: a vector-agnostic janitor instead of per-file edits.** The autouse
   function-scoped fixture removes any `MagicMock/` dir a test creates and emits a `warning`
   (offenders stay discoverable) without failing. A `pytest_sessionfinish` hook sweeps any dir
   created during module/session-scoped teardown. Combined with the existing `MagicMock/`
   `.gitignore` rule, stray dirs can never reach the repository.
3. Delete the existing `D:\ProbOS\MagicMock\` directory. (`.gitignore` already has `MagicMock/`,
   so no gitignore change needed here.)

**Acceptance:** full suite green; no `MagicMock/` directory persists after a run; the conftest
janitor + `pytest_sessionfinish` sweep are in place. Offenders surface as warnings, not failures
(so the 100+ existing API tests stay green while the repo stays clean).

**Do NOT:** add `isinstance`/`hasattr` defensive branches in `ArtifactStore`, `acm.py`, or other
production constructors. The fix is in the tests + a guard.

---

## BF-327 — Repo hygiene: tracked scratch files + gitignore (closes #802)

**Fix:**
- `git rm` the tracked scratch files: `.tmp_issue160.txt`, `PROGRESS.md.new`, `tmp_test.txt`.
  (Confirm `PROGRESS.md.new` is genuinely a stale scratch copy of `PROGRESS.md` before removing —
  diff it against `PROGRESS.md`; if it contains unmerged content, flag instead of deleting.)
- Add a `.gitignore` rule for `tmp_*.txt` (the `test_output*.txt` and `MagicMock/` rules already exist).
- Delete the 12 untracked `test_output*.txt` / `tmp_*.txt` artifacts at repo root.

**Acceptance:** `git ls-files` no longer lists the three scratch files; `.gitignore` covers `tmp_*.txt`;
repo root clean of the artifacts.

**Do NOT:** remove any tracked file that is not one of the three named scratch files.

---

## BF-328 — Stale open-ADs report (closes #803)

**File:** `docs/development/open-ads-report.md`

The report is a 2026-03-31 snapshot ("87 open ADs + 7 bugs") that misrepresents current open work
(project is at ~Wave 198 / AD-828; most listed items have shipped).

**Fix (lowest-risk option):** prepend a prominent stale banner at the top of the file pointing readers
to `PROGRESS.md` and `DECISIONS.md` as the live source of truth, and noting the snapshot date.
Do not attempt to regenerate the full backlog by hand.

**Acceptance:** the file opens with an unmistakable "STALE — see PROGRESS.md / DECISIONS.md" banner.

---

## Wave-level acceptance criteria

1. `pytest tests/test_ad443_mobility.py -q -n 0` → all pass (BF-325).
2. Full suite green: `D:\ProbOS\.venv\Scripts\pytest.exe tests/ -q` with **no new failures**
   vs. the pre-existing baseline, and **no `MagicMock/` directory** produced by the run.
   (Pre-existing unrelated failures, if any remain after BF-325, must be enumerated and confirmed
   pre-existing by stashing this wave's changes — same protocol used for AD-735.)
3. Working tree clean of scratch artifacts (BF-327).
4. `open-ads-report.md` carries a stale banner (BF-328).
5. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
6. One commit per BF (or a single cohesive commit referencing all four BF numbers + `closes #800 #801 #802 #803`).

## Out of scope (do NOT build)

- Do not touch the 14 open forward-marker feature issues.
- Do not refactor `identity.py`, `acm.py`, or `ArtifactStore` beyond the named import/test fixes.
- Do not regenerate `open-ads-report.md` content.
- Do not change CI workflow files (branch-protection follow-up is a separate operator task noted in #800).
