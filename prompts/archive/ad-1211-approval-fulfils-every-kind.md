# AD-1211: approving a request actually fulfils it

**Issue:** #1164 · **Epic:** #1162 · **Repo:** OSS (`d:\ProbOS`), branch `main`

Approving a pending `grant`, `install` or `build` records the decision and does nothing else.
The card disappears, no grant is issued, no `FULFILLED` event fires, and the linked work item
stays blocked permanently.

**#1167 (BF-722) has shipped**, so the route already reports fulfilment honestly and a failed
fulfilment is retriable. Build on that; do not re-litigate it.

---

## Verified state — enumerated, not recalled

`rg '\.mark_fulfilled\(' src/` returns exactly three call sites:

| Site | When it runs |
|---|---|
| `capability_triage.py:290` | grant fast path — **file time** |
| `capability_triage.py:315` | build route — **file time** |
| `capability_requests.py` (`_maybe_fulfil_on_approval`) | AD-1204 — gated to `continue` only |

`rg 'CAPABILITY_REQUEST_DECIDED\|CAPABILITY_REQUEST_FULFILLED' src/` shows one consumer:
`CapabilityGapDriver.on_capability_event`, which resumes on `FULFILLED` only —
`capability_gap_driver.py:224` reads `# "approved" -> no-op; resume fires on the FULFILLED event.`

`_route_grant` returns the request **pending** when the fast path declines or the permission
store is absent. Triage's own comment for install: *"always Captain-gated — leave pending."*
So no actor exists on the approval path for any of the three kinds.

## A false comment ships with this fix

`capability_requests.py` (the `_FULFIL_ON_APPROVAL_KINDS` block) currently asserts:

> *"Every other kind names something a separate fulfiller then does — a grant is applied, a
> package is installed, an agent is built — and `mark_fulfilled` is called by whoever did it."*

**That is false for the approval path** and true only for the file-time fast path. I wrote it
in AD-1204. Correct it in this commit. A wrong premise in a comment is worse than the bug —
it tells the next reader the chain exists.

---

## Required change

### 1. A fulfilment dispatcher

Replace `_FULFIL_ON_APPROVAL_KINDS` with an explicit kind → fulfiller mapping:

| Kind | Fulfiller |
|---|---|
| `continue` | approval itself — unchanged, AD-1204 |
| `grant` | `permission_store.issue_grant(...)` then `mark_fulfilled` |
| `build` | `self_mod_pipeline.handle_unhandled_intent(...)` then `mark_fulfilled` if the record is `active` |
| `action` | **no fulfiller** — see #1166. Do not invent one here. |

Keep it an explicit map, not "any kind nobody else fulfils" — Minimal Authority, so a future
kind opts in deliberately. A drift guard already asserts the AD-1204 literal agrees with
`continue_or_ask.CONTINUE_REQUEST_KIND`; keep that working.

`_maybe_fulfil_on_approval` currently takes `(store, decided, *, approve)`. It will need the
runtime for the permission store, the self-mod pipeline and dependency installation. Extend the
signature; the route already has `runtime`.

### 2. Reuse the existing fulfilment logic — do not duplicate it

`_route_grant` currently interleaves *evaluating* the fast path with *performing* the grant.
Extract the performing half — `issue_grant` + `mark_fulfilled` — into one function that both the
fast path and the approval path call. Same for `_route_build`, which is already nearly a pure
fulfiller.

Two copies of "how a grant is issued" is the defect this epic keeps finding. One function.

### 3. `install` — and the double-approval trap

`runtime.ensure_dependency(import_name)` (`runtime.py:3658`) exists and is the install path
(AD-838c). **It carries its own approval gate**: imports in `config.self_mod.allowed_imports`
auto-approve; anything else goes to `resolver._approval_fn` under the `prompt_unlisted` policy,
and when no callback is wired it refuses rather than installing silently.

So routing a Captain-approved install straight there **asks the Captain a second time for the
same thing**.

Add an additive keyword-only parameter (e.g. `pre_approved: bool = False`) so the caller can
state that human approval is already on record, and pass it from the dispatcher. Default `False`
keeps every existing caller byte-identical. Do not weaken the no-callback refusal for any other
path, and do not bypass the resolver — the install must still be logged to the event log exactly
as today.

If you find a cleaner seam, take it, but say why in the report. Silently leaving the double
prompt in place is not acceptable — the Captain would discover it live.

### 4. Failure is reported, never swallowed

A fulfiller that raises or returns falsy must **not** call `mark_fulfilled`, must log with
context, and must return "not fulfilled" so BF-722's `fulfilled` flag is honest and the retry
path works. The approval stays durably recorded; the route still returns 200.

---

## Out of scope

- No UI changes. Zero `.ts`/`.tsx` staged. #1168 owns that panel.
- Do not implement a fulfiller for `action` — that is #1166, and the contract there is
  standing-grant-only with no replay.
- Do not add delegated approval authority — that is #1170.
- Do not change the triage fast-path *evaluation* rules. Only extract its fulfilment half.

---

## Tests — `tests/test_ad1211_approval_fulfils_every_kind.py`

**One end-to-end chain test per kind.** Each must span: pending request + blocked work item →
approve through the route → fulfiller runs → `FULFILLED` emitted → work item leaves `blocked`.
A test that stops at "the fulfiller was called" does not satisfy this. The whole epic exists
because producer tests and consumer tests both passed while the chain was dead.

Also required:
- `grant` actually issues an active grant the agent can be seen to hold afterwards.
- `install` fulfilment does **not** trigger a second approval prompt — assert the approval
  callback is not invoked.
- `install` still refuses and reports honestly when the dependency subsystem is unavailable.
- `build` that returns a non-`active` record does **not** mark fulfilled, and the request stays
  retriable.
- A fulfiller raising leaves the request approved-and-unfulfilled, retriable per BF-722.
- Denial still cancels the work item via the existing `DECIDED` path.
- The triage fast path is unchanged — its existing tests must pass untouched.

**Mutation-check every fix:** revert the production change, confirm the new test fails, restore.

---

## Gates

1. Focused: the new file plus `rg -l 'capability_triage|capability_request|capability_gap_driver|ensure_dependency' tests/`.
2. Full Python gate:
   ```
   $env:PROBOS_DATA_DIR="$env:TEMP\ad1211_$(Get-Random)"; $env:PROBOS_EMBEDDINGS='local'
   & d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/ -q -n 16 --dist=loadfile --timeout=600 2>&1 | Tee-Object -FilePath d:\ProbOS\logs\ad1211-gate.log
   ```
   Never place a filter after `Tee-Object`. Baseline **22,737 nodes** (passed + skipped + failed)
   — that is post-BF-722. Reconcile `baseline + new tests`, counting parametrised cases as
   separate nodes.
3. If any config field is added, regenerate `docs/development/config-reference.md` via
   `scripts/gen_config_reference.py` and stage it in the same commit, or
   `test_config_reference_current.py` reds the whole suite.

Known flakes, not regressions: #1143 `test_ad580_alert_feedback::test_resolve_refires_after_clean_period`,
#1144 `test_ad484_ux_adoption::test_doctor_returns_zero_on_clean_setup`.

---

## Report back

- The dispatcher shape, and which existing functions you extracted rather than duplicated.
- How you solved the install double-approval, and what you verified about it.
- Reconciled gate numbers against 22,737.
- Any existing test that encoded the current behaviour as the contract — update and explain
  inline, never delete. Five such tests this week.
- **Anything in this prompt that turned out to be untrue.** Say so rather than implementing
  around it. The last two prompts each contained a wrong claim and saying so was the most
  valuable part of the report.

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
