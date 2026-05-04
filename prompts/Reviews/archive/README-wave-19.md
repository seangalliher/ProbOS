# Wave 19 Review Sweep — Pass 1

**Date:** 2026-05-03
**Stage:** Stage 1 review (orchestrator-driven)
**Reviewer:** Architect agent

## Scope

Wave 19 is a single-prompt wave: **AD-530 v1 — Information Classification Enforcement (Disclosure Gate)**.

## Pass-1 verdict summary

| Prompt | Verdict | Required | Recommended | Nits | Tolerance |
|---|---|---|---|---|---|
| ad-530-classification-gate-v1.md | ❌ Not Ready | 4 | 5 | 4 | Breached (#15: ≤1 ⚠ allowed) |

**Wave gate:** Stage 2 revision required.

## Headline issues

1. **Hard-stop fired (Required #1+#2):** the prompt's own Hard-Stop #1 ("`_CLASSIFICATION_LEVELS` hierarchy keys differ from assumption") matches reality. Real keys are `private` / `department` / `ship` / `fleet` — `confidential` does not exist. Furthermore, the disclosure-direction comparison `if dst_lvl < src_lvl: BLOCK` is inverted relative to the *openness* semantics encoded in records_store.py:716 and :841. Both must be fixed together — fixing the keys without re-deriving the comparison direction will leave Section 2 semantically broken.

2. **Pattern set FP risk (Required #4):** `api_key_like = r"\b[A-Za-z0-9_-]{32,}\b"` matches UUIDs (36 chars), commit hashes (40 chars), and most opaque-token shapes used in existing fixtures. Even though v1 is observational (no message mutation), every match emits `CLASSIFICATION_DISCLOSURE_BLOCKED` — turning the event channel into noise. Recommended fix: drop from `_DEFAULT_SENSITIVE_PATTERNS` and keep available via `register_pattern()` opt-in.

3. **Unsafe-direction default for unspecified classification (Required #3):** unknown source defaults to `ship` (broadest openness). A safety gate must default unknown to MOST restricted, not least.

## Things that DID pass (worth preserving in revision)

- **Privacy invariant:** event payload's `content_length` (no content) + `blocked_phrases` (names not matched substrings). Tests #14/#15 assert both. Hold this line.
- **Pre-deferral honesty:** AD-530b/c/d are deferred cleanly. No Security Chief runtime API, no full audit trail, no message mutation in v1.
- **Sibling-pattern conformance (mostly):** module placement at `src/probos/security/classification.py`, public `runtime.classification_gate` attribute, finalize.py wiring location all correct.
- **EventType + attribute name collision-free** verified by grep.

## Recommended revision strategy

Single re-draft pass. The 4 Required findings are tightly coupled — Required #1, #2, #3 should be addressed in one Section 2 rewrite. Required #4 is independent (pattern-set tweak in `_DEFAULT_SENSITIVE_PATTERNS` tuple).

After revision:
- Pass-2 review verifies: real keys present, comparison direction grounded in records_store semantics with comment, safe-default direction, `api_key_like` removed or tightened, Verified-Against-Codebase footer states real keys verbatim.
- Tolerance gate (#15): pass-2 must come back with ≤1 ⚠ (Required + Recommended-rolled-up) to ship.

## Files

- Detailed review: `prompts/Reviews/ad-530-classification-gate-v1-review.md`
- Prompt under review: `prompts/ad-530-classification-gate-v1.md`
- Wave dispatch: `prompts/WAVE-19-DISPATCH.md`

## Next action

Stage 2: prompt author revises AD-530 v1 addressing Required #1–#4 + (ideally) Recommended #1–#5. Pass-2 review on revised prompt.
