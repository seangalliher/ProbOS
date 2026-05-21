# AD-765 — Yeo gap-doc reconciliation audit

Status: drafted
Issue: #711
Depends on: AD-758 (Yeo feature-complete gate, Wave 181)

## Captain request (2026-05-20)

After surveying `Yeo_PA_Feature_Gap.md` (commercial repo, research deliverable) against ProbOS HEAD, the rough fit estimate was "~70–80% closed." That number is too soft to act on. We need a line-item reconciliation that produces either (a) a ship-evidence pointer for each capability, or (b) a follow-up child AD that closes the remaining gap.

## Why this matters

- **AD-758 covered the program rubric** (AD-749..AD-757 conformance), not a line-item match against the external gap doc. Items the gap doc lists that AD-758 didn't enumerate are silently uncounted.
- **Discovery cost in the field is high.** A missing "forget this" tool or unsigned installer surfaces as a trust failure during real use, not as a test failure. Cheaper to find these now than after the first prosumer pilot.
- **Phasing claims need evidence.** PROGRESS.md asserts Y1+Y2+Y3 + portions of Y6 shipped. Y4 (permissions + data hardening) and Y5 (M365 write) are "partially landed." Partial is not a status — each line item is either shipped (with file:line pointer) or not.
- **Commercial-vs-OSS boundary clarity.** Some gap-doc items (multi-device sync) are correctly commercial-only. The audit makes that explicit per row so we don't accidentally file an OSS AD for something that belongs in the overlay.

## Scope (audit-only — produces a document, not code)

### 1. Reconciliation matrix
Produce `docs/development/yeo-gap-reconciliation-2026-05-20.md` with one row per capability in the gap doc (every line item from sections §1–§10 of `Yeo_PA_Feature_Gap.md`). Each row has columns:

- **Capability** — verbatim from gap doc.
- **Status** — one of `shipped` / `partial` / `not-started` / `commercial-overlay-only` / `out-of-scope`.
- **Evidence** — file:line pointer to source, AD number, test reference, OR the explicit reason for `not-started`/`commercial`.
- **Follow-up** — `none`, OR a child-AD number to file (with one-line scope).

### 2. Verification method per row
For each gap-doc capability, the auditor MUST:

- `grep_search` the codebase for the symbol/concept (don't trust memory).
- Read the actual implementation file when claiming `shipped` — confirm the capability does what the gap doc describes, not just that a similarly-named function exists.
- For tests: confirm the capability has a passing test that exercises the user-visible behavior (not just constructor coverage).
- For `commercial-overlay-only`: confirm the OSS-scope boundary AD-697/AD-698 explicitly excludes the capability.
- For `partial`: enumerate exactly which sub-capabilities are missing — no hand-waving.

### 3. Child-AD backlog
For every row marked `partial` or `not-started` (that is NOT commercial-only or out-of-scope), the audit produces a one-line child-AD draft suitable for filing in a follow-up wave. The audit does NOT file the child ADs itself — that's a follow-up wave's job. Output format:

```
AD-XXX — <capability>. Builds on <existing primitive>. Scope: <one sentence>. Test plan: <one sentence>.
```

### 4. Specific high-priority spot-checks
These four were called out in the Architect summary as the highest-risk "claimed but unverified" items. The audit MUST resolve each conclusively:

1. **`autoApproveReadOnly` permission policy** (gap doc §4) — does the consensus layer actually tag intents/tools as read-only and bypass quorum? File: `src/probos/consensus/quorum.py` + capability descriptors.
2. **Tray icon + global hotkey + mini-mode** (gap doc §2) — `experience/desktop/lifecycle.py` ships auto-start; do the user-visible surface components exist? Search `pystray`, `keyboard`, mini-mode HXI variant.
3. **PII redaction in logs** (gap doc §5) — does any telemetry filter mask emails/names/URLs before logging? Search `redact`, `mask_email`, logging filters.
4. **DocxAgent / PptxAgent / XlsxAgent** (gap doc §6) — are these registered in the agent pool when M365 is connected? Search agent registry + skill tier.

### 5. Update PROGRESS.md
After the matrix lands, replace the "Yeo feature-complete gate" paragraph in PROGRESS.md with a one-line link to the reconciliation document and a numeric summary: `Yeo gap-doc reconciliation: N shipped / M partial / K not-started / J commercial / I out-of-scope`. No more "~70–80%" estimates.

## Out of scope

- **Filing child ADs.** The audit produces drafts; filing is a follow-up wave's job. (Prevents scope creep from blowing up this AD into a 20-AD program.)
- **Building anything from the backlog.** Audit only.
- **Re-litigating AD-758.** The integration gate stands. This audit is additive — it answers questions AD-758 didn't ask.
- **Sensitivity-label compliance work** (gap doc §1 last row) — flagged in the audit but Y4-tier per gap doc's own phasing; explicit AD when the work is queued.
- **Multi-device continuity build-out** (gap doc §8 last row) — commercial-overlay scope, not OSS.

## Acceptance signals

- `docs/development/yeo-gap-reconciliation-2026-05-20.md` exists with one row per gap-doc capability.
- Every `shipped` row has a verifiable file:line or AD-NNN pointer.
- Every `partial` row enumerates which sub-capabilities are missing.
- The four high-priority spot-checks (§4 above) each have a definitive verdict + evidence.
- PROGRESS.md updated with numeric summary replacing the soft estimate.
- Child-AD backlog produced as a labeled section at the bottom of the reconciliation doc; ready to drop into a future wave plan.

## Engineering principles compliance

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

- Verification-first: every claim backed by file:line or AD pointer, not memory.
- No new code; doc-only deliverable.
- OSS-scope boundary respected (AD-697/AD-698) — commercial items explicitly tagged and excluded from the OSS backlog.

## Notes for the auditor

- The gap doc is a private research deliverable (not in this repo). Read it once at audit-start; quote each line item verbatim into the matrix so the mapping is unambiguous.
- AD-749..AD-757 is the canonical "Yeo program" range. AD-763 (#709 connector scoping) and AD-764 (#710 Gmail) are downstream gap-doc-derived ADs already filed — mark them as `follow-up: filed` rather than `not-started`.
- Wave 181 just closed; don't re-open it. This AD targets Wave 182 or later.
- If during audit you discover a gap-doc capability that's actually a duplicate of a shipped ProbOS primitive under a different name, mark it `shipped` and add a one-line note explaining the rename — don't file a child AD for something that already exists.
