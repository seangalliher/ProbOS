# AD-721d-2c — HXI button + Vitest tests for Counselor-mediated avatar revision

**Status:** Draft for Wave 163
**Dependencies:** AD-721d-2 ✅ (Wave 162, ships server-side mediation + `POST /api/agent/{agent_id}/appearance/mediate`).
**Closes:** #658
**Estimated tests:** 3 Vitest (NEW), 0 pytest (server-side covered by AD-721d-2).
**Build order:** Independent of the peer-observation cluster — can build anytime in Wave 163.

## Problem

AD-721d-2 (Wave 162) shipped the server-side Counselor-mediated avatar revision flow: `CounselorAgent` handler + `POST /api/agent/{agent_id}/appearance/mediate` endpoint. The HXI button was explicitly deferred. AD-721d-2c wires the button into the existing avatar revision UI surface.

## Solution overview

Add a "Counselor-mediate revision" button to the existing `CrewAvatarPopout.tsx` (or whichever component owns AD-721d-1's revision flow — verify before edit; the file `CrewAvatarPopout.revision.test.tsx` exists per Wave 163 pre-flight). Button appears only when the Captain is providing a revision hint AND a Counselor agent is online. Clicking it routes the hint through the mediation endpoint instead of directly through `propose_appearance`.

## Section 0: UI integration

**Builder verify-first** before drafting:
1. `grep -rn "propose_appearance\|revision" ui/src/avatars/` to locate the existing Captain-driven revision UI (likely `CrewAvatarPopout.tsx`).
2. Read the existing revision button JSX + state management.
3. Identify the existing API client that calls `propose_appearance` — likely `ui/src/api/agents.ts` or similar.

## Section 1: API client

Add to the existing avatars API client module (verify exact path):

```typescript
export async function mediateAppearanceRevision(
  agentId: string,
  hint: string
): Promise<MediateAppearanceResponse> {
  // POST /api/agent/{agentId}/appearance/mediate
  // Body: { captain_note: hint }
  // Returns: { ok: boolean, refined_note?: string, iteration_count?: number, error?: string }
}
```

Response shape MUST be verified against the actual `POST /api/agent/{agent_id}/appearance/mediate` response — confirm by reading `src/probos/routers/agents.py` for the mediate endpoint Pydantic response model.

## Section 2: Button + UX

Add to the revision panel inside `CrewAvatarPopout.tsx` (or owning component):

- New button: "Counselor-mediate" (inline SVG glyph per HXI Design Principle #3 — stroke-based, no emoji, amber active state).
- Shown when: revision hint is non-empty AND a Counselor agent in the crew has `agent.status === 'online'` (verified by Architect grep: `ui/src/store/types.ts:590` defines `status: 'online' | 'offline' | 'degraded'`).
- Disabled while in-flight (loading state).
- On click: calls `mediateAppearanceRevision`. On success, shows the refined hint in a small panel ("Counselor refined: ...") and the iteration-count chip. The button does NOT auto-submit the refined hint — the Captain reviews, then optionally clicks the standard "Submit" / "Propose" button.
- On error: surface the error message inline, do NOT replace the Captain's original hint.

## Section 3: Vitest tests (≥3)

`ui/src/avatars/CrewAvatarPopout.mediate.test.tsx`:

1. **Button visible when conditions met** — rendered when (a) revision hint non-empty AND (b) Counselor online in crew fixture.
2. **Happy path** — click button → `mediateAppearanceRevision` called → refined hint rendered → iteration-count chip shown.
3. **Error handling** — server returns error → error surface displayed → Captain's original hint preserved.

Use the existing test scaffolding pattern from `CrewAvatarPopout.revision.test.tsx` and `CrewAvatarPopout.diff.test.tsx`. NO MagicMock at the API boundary — use proper `vi.mock` of the API client (TypeScript Vitest equivalent of the BF-287 real-config principle).

## Section 4: Builder Standing Rules

- BF-274: single replace for adjacent edits.
- BF-280: n/a (no subprocess in UI).
- BF-282: n/a (no binary stdout in UI).
- BF-286: test scaffolding mirrors production component shape (use existing test pattern).
- BF-287: no MagicMock at API boundary — use `vi.mock`.
- **AD-738b: REQUIRED `npm run build` GATE.** This AD touches `ui/src/`. Per-commit gate MUST run BOTH:
  - `cd ui ; npx vitest run` (component tests)
  - `cd ui ; npm run build` (catches `tsc -b` errors that Vitest skips — BF-279 root cause)
- AD-731 invariant: n/a (no image-byte flows).
- HXI Design Principle #3: inline SVG glyphs, no emoji. Verify any new icon is stroke-based.
- HXI Design Principle #10: this is workstation-tier, not agentic — but the button itself helps the Captain delegate to the Counselor, which is the right direction.

## What this does NOT change

- Server-side `mediate_appearance_revision` handler (Wave 162 AD-721d-2 is canonical).
- The `POST /api/agent/{agent_id}/appearance/mediate` endpoint.
- The existing AD-721d-1 `propose_appearance` flow.
- The avatar DSL.
- Any non-revision flow in `CrewAvatarPopout.tsx`.

## Tracking

- `PROGRESS.md`: CLOSED entry referencing #658.
- `docs/development/roadmap.md`: move AD-721d-2c from forward markers to shipped.
- `DECISIONS.md`: append AD-721d-2c entry — HXI completion of Wave 162 AD-721d-2.

## Acceptance Criteria

1. Button visible per Section 2 conditions.
2. ≥3 Vitest tests pass: `cd ui ; npx vitest run` green.
3. **`cd ui ; npm run build` green** (BF-279 / AD-738b standing rule).
4. Full pytest gate still green (no server-side regressions).
5. No emoji in new UI code; inline SVG glyph used per HXI Design Principle #3.
6. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Verified Against Codebase (2026-05-15)

```
grep -n "mediate_appearance_revision" src/probos/cognitive/counselor.py
  489 (handler), 813 (docstring referencing AD-721d-1 propose_appearance path)

ls ui/src/avatars/
  CrewAvatarPopout.tsx, CrewAvatarPopout.diff.test.tsx, CrewAvatarPopout.revision.test.tsx
  (revision UI shipped per AD-721d-1; this AD extends with mediate button)
```

**Builder verify-first flags:**
- Exact API client module owning `propose_appearance` POST — VERIFY.
- `POST /api/agent/{agent_id}/appearance/mediate` response Pydantic model — VERIFY in `src/probos/routers/agents.py`.
- Online-crew detection pattern — VERIFIED: `agent.status === 'online'` per `ui/src/store/types.ts:590`.
