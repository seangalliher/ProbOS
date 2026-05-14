# Wave 159 — Sweep Summary, Pass 2

**Date:** 2026-05-14. **Reviewer:** Architect. **Prompts reviewed:** 5 (3 revised + 2 unchanged). **New Required findings:** 0.

---

## Per-prompt pass-2 verdict

| # | Prompt | AD | Pass-1 | Pass-2 | One-line justification |
|---|---|---|---|---|---|
| 1 | `prompts/ad-722c-telemetry-history.md` | AD-722c | ✅ | ✅ | Unchanged; verdict re-affirmed. |
| 2 | `prompts/ad-722d-records-auto-write.md` | AD-722d | ⚠️ | ✅ | Section 2 `_classify` is single canonical impl using `self._prior_div_mag`; no `_last_div_mag` residue; sketch + design-note paragraph removed. |
| 3 | `prompts/ad-722b-3-snapshot-diff.md` | AD-722b-3 | ✅ | ✅ | Unchanged; verdict re-affirmed. |
| 4 | `prompts/ad-720e-audio-attachments.md` | AD-720e + AD-738e-2 | ❌ | ✅ | Section 2 uses existing `_ANY_OF` (verified mime.py:32); Section 5 ProfileChatTab removed; Section 4 paste-filter only; forward marker AD-720e-3 documented. |
| 5 | `prompts/ad-725-dm-subintent-dispatch.md` | AD-725 | ⚠️ | ✅ | `runtime.oracle.query(query_text, *, agent_id=...)` matches live signature at `oracle_service.py:285`; zero remaining `runtime.oracle_service` references. |

---

## Verify-first checks (pass-2 deltas)

### AD-722d (Section 2 canonical impl)

- `self._prior_div_mag: dict[str, float] = {}` declared in `__init__` (prompt line 135).
- `_classify` reads `prior_mag = self._prior_div_mag.get(snap.agent_id, 0.0)` (line 178) and writes `self._prior_div_mag[snap.agent_id] = float(latest.magnitude)` (line 183).
- `grep -n "_last_div_mag" prompts/ad-722d-records-auto-write.md` → no matches outside the Revision footer's self-check ("`_last_div_mag` is no longer referenced in the prompt body").
- BF-274/278 footgun (sketch-then-correct on a frozen dataclass) is structurally impossible: there is only one impl.

### AD-720e (mime + UI scope-collapse + forward marker)

- `src/probos/attachments/mime.py:32`: `_ANY_OF: frozenset[str] = frozenset({"image/gif"})` confirmed live. Prompt's Section 2 "Edit 2 — extend `_ANY_OF` frozenset (`mime.py:32`)" SEARCH block matches exactly.
- `src/probos/attachments/mime.py:18`: `_SIGNATURES` dict; `validate_image_bytes` at line 36 consults `_ANY_OF` at line 48. The any-of mechanism is established prior art (`image/gif`). Audio MP3 (4 sync-byte variants) and MP4 (3 `ftyp` brands) fit the same shape; `audio/ogg` stays out (single signature, all-of default works).
- Prompt section structure now 5 sections: (1) AttachmentsConfig defaults, (2) Magic-byte signatures + `_ANY_OF` extension, (3) IntentSurface audio render, (4) WardRoomThreadDetail paste filter (MIME-only, no render extension), (5) BUILDER-EXECUTION-PLAN fold. The old Section 5 (ProfileChatTab mirror) is excised; the old Section 6 (plan fold) is renumbered to 5.
- Section 4 title: "WardRoomThreadDetail paste filter (MIME-only; no render extension)". Files-to-Modify table row says "**No render extension** — chip-only rendering preserved".
- Forward marker `AD-720e-3` at prompt line 259: "inline `<audio>` player inside WardRoomThreadDetail and ProfileChatTab chip surfaces (post-scope-collapse, 2026-05-14 revision)". Captures deferred chip→render extension.
- Vitest count 3 (audio / image / fallback in IntentSurface); pytest count 4 (magic-byte + allow-list). AD-738b UI gate (`npm run build`) retained.

### AD-725 (oracle attribute correction)

- Live `OracleService.query` signature (`src/probos/cognitive/oracle_service.py:285`):
  ```
  async def query(
      self,
      query_text: str,
      *,
      agent_id: str = "",
      intent_type: str = "",
      k_per_tier: int = 5,
      tiers: list[str] | None = None,
      caller_sovereign_id: str = "",
      access_policy: Any = None,
  ) -> list[OracleResult]:
  ```
- `self.oracle = cog.oracle_service` (AD-686 public alias) at `runtime.py:1537` — confirmed.
- Prompt's Builder-verification footnote at line 347 cites exactly: `runtime.oracle.query(query_text, *, agent_id="", intent_type="", k_per_tier=5, tiers=None, ...) -> list[OracleResult]`. Matches.
- `grep "runtime\.oracle_service" prompts/ad-725-dm-subintent-dispatch.md` → 0 hits (rename is global). Every oracle reference cites AD-686 in-line.

---

## Cross-prompt re-checks (pass-2)

1. **Build Group A ordering preserved.** Prompts 1→2→3 still modify the same `_publish_loop` block at distinct insertion points. Dispatch's "AD-722d hook MUST go after AD-722c history-append" instruction unchanged. No dependency drift from the revisions.
2. **AD-738e-2 numbering renumber unchanged.** DECISIONS.md edit point still `AD-738e-1:2569`; renumber target `AD-738e-2-prosody` survives the revision pass. AD-720e revision didn't touch this part of the prompt.
3. **AD-738b UI gate (BF-279).** AD-720e revision keeps `npm run build` in verification commands (UI-touching). AD-722b-3 unchanged (UI-touching, keeps the gate). Other three correctly omit.
4. **HXI Principle #3 (no emoji).** AD-720e Section 3 unchanged — inline SVG file-icon + native `<audio controls>`. Compliant.
5. **No new tracked-file modifications.** `git status` clean pre-review (modulo this pass-2 review artifact). No working-tree integrity flag.

---

## Wave verdict per Convention #15 (relaxed)

**APPROVE.** All five prompts ✅; zero ❌; zero ⚠️ on highest-risk. The relaxed threshold (5✅ OR ≤1⚠️ on highest-risk only, no ❌) is exceeded — full sweep clean.

---

## Recommendation

**ADVANCE to GATE 1 (Builder dispatch).**

Dispatch order per `WAVE-159-DISPATCH.md` unchanged:
1. AD-722c (JSONL history hook)
2. AD-722d (records auto-write hook AFTER AD-722c hook)
3. AD-722b-3 (WS snapshot diff wrapping)
4. AD-720e (audio attachments — IntentSurface playback)
5. AD-725 (DM sub-intent dispatch)

No RESET required. Pass-1 Required findings (5) are all resolved by surgical revisions; pass-2 introduced zero new Required findings. Pass-1 Recommended/Nits remain on the table for Captain's discretion pre-dispatch.

---

## Audit trail

- AD numbering unchanged. Current highest top-level AD: **AD-739**. Next free: **AD-740**. Wave 159 consumes zero top-level AD numbers (sub-slots and forward-marker renumber only).
- Working tree clean before this pass. Live-grep confirmed every concrete claim in this summary.
- Pass-2 review files appended (not rewritten); pass-1 audit trail preserved in each.
