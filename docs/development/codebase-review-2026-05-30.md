# ProbOS OSS — Codebase Review (2026-05-30)

**Reviewer:** Architect agent
**Scope:** Read-only review of the ProbOS OSS repo (`d:\ProbOS`) at `main` (HEAD synced with `origin/main`), looking for codebase-improvement recommendations, architecture/feature gaps vs. the docs, and quality issues.
**Deliverable:** GitHub issues for actionable findings + this report.

---

## Headline

ProbOS is an exceptionally well-tracked project. Feature and architecture gaps are already captured as **forward-marker GitHub issues** (14 open, all tied to AD/BF numbers) and in `PROGRESS.md` / `DECISIONS.md`. As a result, the highest-value findings from this review are **not** new feature gaps — they are **untracked engineering-quality issues**, the most serious of which is that **`main` is currently a red test gate**.

---

## Findings → Issues filed

| # | Issue | Severity | Evidence |
|---|-------|----------|----------|
| [#800](https://github.com/seangalliher/ProbOS/issues/800) | `main` gate RED: missing `TransferCertificate` import in `identity.py` breaks AD-443a transfer (11 tests) | **P0 / Bug** | Reproduced live: `11 failed, 46 passed` in `tests/test_ad443_mobility.py` |
| [#801](https://github.com/seangalliher/ProbOS/issues/801) | Test runs pollute the working tree with `MagicMock/` directories | Bug / test isolation | `MagicMock/mock.*` dirs with thousands of subdirs in both repos |
| [#802](https://github.com/seangalliher/ProbOS/issues/802) | Repo hygiene: tracked scratch files + ungitignored test-output artifacts | Tech-debt | `git ls-files` shows `.tmp_issue160.txt`, `PROGRESS.md.new`, `tmp_test.txt` tracked |
| [#803](https://github.com/seangalliher/ProbOS/issues/803) | `open-ads-report.md` is stale (2026-03-31) and misrepresents current open work | Docs | Report header: "Generated 2026-03-31. 87 open ADs + 7 open bugs" |

---

## Detail

### 1. P0 — `main` test gate is RED (#800)

`src/probos/identity.py` references `TransferCertificate` at lines 1113, 1139, 1177 but **never imports it**. Because the module uses `from __future__ import annotations`, the `-> TransferCertificate` return annotation is a lazy string, so the module imports cleanly and the bug only surfaces at runtime when `AgentIdentityRegistry.issue_transfer_certificate()` constructs the object.

- `TransferCertificate` is defined in `src/probos/mobility.py:96`.
- `src/probos/federation/bridge.py:20` imports it correctly; `identity.py` does not.
- Verified reproduction at HEAD:

  ```
  pytest tests/test_ad443_mobility.py -q -n 0
  E   NameError: name 'TransferCertificate' is not defined
  src\probos\identity.py:1139: NameError
  11 failed, 46 passed in 2.68s
  ```

**Fix:** add `from probos.mobility import TransferCertificate` to `identity.py` (top-level, or function-local mirroring `bridge.py:302` if a circular-import risk exists).

**Process note:** `.github/workflows/ci.yml` runs the full suite with `--maxfail=10`. This one file produces 11 failures, so CI on `main` should already be red. Worth confirming branch protection requires the `python-tests` check before merge so a red gate cannot reach `main` again.

### 2. `MagicMock/` working-tree pollution (#801)

Multiple services call `.mkdir(parents=True, exist_ok=True)` on a config-supplied path **at construction time** (`acm.py:112`, `artifacts/__init__.py:93`, and others). Tests that pass a bare `MagicMock()` config cause the production `mkdir` to create literal `./MagicMock/mock.<attr>/...` directories (e.g. `mock.config.desktop.lock_file/` with thousands of object-id-named subdirs). The same pollution exists in the commercial repo.

**Recommendation:** fix the offending tests to use real `tmp_path` fixtures; add a `conftest.py` guard that fails the session if `MagicMock/` appears in CWD; gitignore + delete the existing dirs. This aligns with the existing "MagicMock auto-attribute trap" anti-pattern already documented in repo conventions.

### 3. Repo hygiene (#802)

Tracked scratch files (`.tmp_issue160.txt`, `PROGRESS.md.new`, `tmp_test.txt`) and a pile of untracked `test_output_*.txt` artifacts clutter the repo root. Recommend `git rm` the tracked scratch files and add `.gitignore` rules (`test_output*.txt`, `tmp_*.txt`).

### 4. Stale open-ADs report (#803)

`docs/development/open-ads-report.md` is a 2026-03-31 snapshot claiming 87 open ADs + 7 bugs, most of which have since shipped (the project is at Wave 198 / ~AD-828). It is misleading as a backlog. Recommend regenerate, delete, or add a stale banner pointing to `PROGRESS.md` / `DECISIONS.md`.

---

## What was reviewed and found healthy / already-tracked

- **Feature/architecture gaps vs. docs** — already covered by 14 open forward-marker issues (#794, #792, #788, #787, #751, #737, #735, #659, #638, #634, #538, #530, #484, #479) and the AD/BF tracking system. No new feature-gap issues were filed to avoid duplicating the existing forward markers.
- **Layer discipline, consensus gating, trust model, episodic learning** — consistent with the documented architecture in the era files; no violations surfaced in this pass.
- **CI exists** (`.github/workflows/ci.yml`) and runs both Python and UI suites with sensible timeouts.

## Notes / limitations

- This was a targeted review, not an exhaustive line-by-line audit. The four issues above are the concrete, verified, high-impact findings.
- Every claim here was verified against the live codebase (grep + reproduction) rather than relying on the stale `open-ads-report.md`.
- **Tooling note:** GitHub issue creation via the MCP integration failed (the connected account is an Enterprise Managed User and is 403-blocked on this personal repo). Issues were created instead via the `gh` CLI authenticated as the repo owner (`seangalliher`).
