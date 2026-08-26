# AD-1184: a reconciled AD/BF lifecycle view generated from the live authorities

**Issue:** #1120 · Wave 0 of `prompts/build-plan-2026-08-03.md` · **Repo:** OSS `d:\ProbOS`, branch `main`

---

## The defect this prevents

A recursive tree scan reports the highest AD as **AD-1180** and the highest BF as
**BF-706**. Both are wrong. Numbers get assigned by audits and reviews that file a
GitHub issue *before* any code exists, so the working tree cannot see them.

As of this build the true ceiling is **AD-1202** and **BF-712**. The issue text
itself says AD-1183/BF-710 — it went stale within hours of being written, because
AD-1201, AD-1202, BF-711 and BF-712 were filed after it. **That staleness is the
bug, demonstrated on itself.** A builder following the documented three-source
procedure would collide with any of them.

Second failure mode: **AD-1152** (#1079) is open, titled
`AD-1152: Agentic-loop span correlation (OpenTelemetry prerequisite)`, with no
retirement comment. Local trackers describe it only as a historical "next free"
number. It is intentionally allocated unfinished work, and a tree scan reads it as
free.

## The precedent to follow exactly

`scripts/gen_config_reference.py` is the established generator idiom in this repo:

- Module docstring states *why* it is generated rather than hand-written
- `python scripts/<name>.py` writes the artifact
- `python scripts/<name>.py --check` exits non-zero when stale
- A test (`tests/test_config_reference_current.py`) runs `--check`, so drift turns
  the existing suite red instead of needing a new CI workflow step
- A `_HEADER` written into the output tells a reader who lands on it from search
  that it is generated and where to change it

Follow all six. Do **not** add a new `.github/workflows` step — the test is the
enforcement point, and it already runs in the gate.

## The four authorities

| Authority | Source | Availability |
|---|---|---|
| Git history | `git log` commit subjects | always |
| `DECISIONS.md` + `decisions-era-*.md` | AD entries | always |
| `PROGRESS.md` + `progress-era-*.md` | status lines | always |
| **GitHub issues** | `gh issue list --state all` | **network + auth** |

## The constraint that will otherwise break CI

The fourth authority is the whole point of this build **and** it is a network
call. `gen_config_reference.py` reads Pydantic models in-process and is
deterministic; this generator is not. A `--check` that hard-depends on the GitHub
API will fail on a fork, offline, without a token, or under rate limiting — red
for a reason unrelated to the code.

**Required design:**

- The generated artifact is **committed**, and includes the issue layer as a
  captured snapshot with the timestamp it was taken.
- `--check` verifies the artifact against the **three local authorities always**,
  offline, with no network call. This is what the test runs.
- The issue layer is refreshed only under an explicit flag (`--online` or
  equivalent). When `gh` is absent or fails, degrade with a clear warning and a
  non-failing exit for the local-only checks — never a traceback.
- The test must **not** require network. If you cannot make the test hermetic, the
  design is wrong; say so rather than shipping a flaky gate. (We already have one
  flaky test — BF-712 #1143 — and it costs a re-litigation on every build.)

## Lifecycle states

Every number resolves to exactly one:

| State | Meaning |
|---|---|
| `allocated-open` | assigned, issue open, no shipped code |
| `deferred` | assigned, explicitly postponed |
| `shipped` | code in history |
| `superseded` | replaced by a later number |
| `retired` | abandoned, number not reusable |

**No number may be classified `free` merely because the tree does not mention it.**
That inference is the defect.

## Acceptance

- [ ] Generator producing the view from all four authorities
- [ ] `--check` mode, hermetic and offline, enforced by a test
- [ ] Correctly classifies audit-assigned-but-uncoded numbers as `allocated-open` —
      derive them; do not hard-code the list, it is already stale
- [ ] Correctly classifies **AD-1152 (#1079)** as `allocated-open`, not free
- [ ] Reports the true ceiling for both AD and BF, and it must come out
      **≥ AD-1202 / ≥ BF-712**
- [ ] **Replaces** `docs/development/open-ads-report.md` (a stale 2026-03-31
      snapshot) rather than editing it
- [ ] Amends `prompts/audit-dormant-code.md` step 1 to list GitHub issues as a
      fourth ceiling source
- [ ] Verify compliance with the Engineering Principles in
      `.github/copilot-instructions.md`

## Constraints

- **Do not renumber, retire or edit any existing AD/BF entry.** This build
  *observes* the ledger; it does not correct it. Anything it finds inconsistent is
  reported in the artifact, not silently fixed.
- **Do not edit `PROGRESS.md`, `DECISIONS.md` or the era files.** They are inputs.
- **Do not close, comment on, or relabel any GitHub issue.**
- Parsing must tolerate malformed and historical entry formats — a single
  unparseable line must not abort the run. Count and report skips.
- **str-replace end-anchor trap:** whatever appears at either END of `oldString`
  must reappear in `newString`. `prompts/audit-dormant-code.md` step 1 is a
  numbered list of near-identical lines. Verify neighbours survived.
- Do not stage `config/system.yaml` (skip-worktree) or this prompt file.

## Tests

New module. Minimum:

1. `--check` passes against the freshly generated artifact.
2. `--check` fails when the artifact is stale (mutate a copy).
3. `--check` makes **no network call** — assert it, do not assume it.
4. A number with an open issue and no code classifies `allocated-open`.
5. AD-1152 specifically classifies `allocated-open`, not free.
6. Malformed entries are skipped and counted, not fatal.
7. Ceiling derivation returns ≥ AD-1202 / ≥ BF-712.

## Gate

ONE full Python gate, **SYNCHRONOUS — do not background it and return.** Pipe
through `Tee-Object -FilePath d:\ProbOS\logs\ad1184-gate.log`; **never
`Select-Object`** (buffering silences the stream and the harness backgrounds a
healthy run).

**Baseline: 22,603 NODES** = 22,568 passed + 34 skipped + 1 failed. Carry NODES,
not passed — skip counts drift between identical runs.

The 1 failure is the known BF-712 flake
(`test_ad580_alert_feedback::test_resolve_refires_after_clean_period`, a 10 ms
margin under `-n 16`). If you see exactly that one failure it is not yours. Any
*other* failure is.

## Do not commit

Leave staged. Report:

1. The four-authority merge strategy, and precedence when they disagree.
2. How `--check` stays hermetic, and the test proving no network call.
3. The derived ceilings, and the full `allocated-open` list.
4. Anything the reconciliation found inconsistent that you deliberately did not fix.
5. Gate numbers with reconciliation arithmetic.
