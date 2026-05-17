# AD-721a — Captain's Avatar Editor UI

**Status:** Medium UI. **Closes:** #528. **Tests:** +8 vitest. **Wave:** 168. **UI gate required.**

## Problem

Issue #528 (AD-721a) — Captain wants to edit appearance.json (vrm_url, expression overrides, color hint) without touching JSON, with live-preview within the popout.

Today the Captain can:
- View an agent's current avatar in `CrewAvatarPopout`.
- Trigger LLM-driven `propose_appearance` via AD-721d D7 and AD-721d-1 (Counselor-mediated revision).
- Preview a proposed DSL via AD-721d-3 (Wave 167, `POST /agents/{agent_id}/appearance/preview`).

What's missing: **direct Captain-driven edits**. The Captain wants to nudge color palette, body type, hair, outfit by hand — not via Counselor revision iterations. The plumbing already exists (`propose_appearance` returns a DSL, `preview` renders a DSL, `PUT /appearance` persists a DSL). This AD adds the **inline editor UI** that surfaces the DSL fields as form controls and routes the edited DSL through the same preview → approve path.

## Solution

Add an "Edit appearance" mode to `CrewAvatarPopout.tsx`:

1. Captain clicks an "Edit" button → existing popout overlays an editor pane.
2. Editor renders the current `AvatarDSL` as form controls (color pickers, body-type select, hair select, outfit select, expression overrides).
3. On every meaningful change (debounced), the editor calls `POST /agents/{id}/appearance/preview` with the modified DSL → receives a `attachment_id` SHA → swaps the popout VRM viewer to render the preview.
4. Captain clicks **Approve** → calls `PUT /agents/{id}/appearance` to persist.
5. Captain clicks **Cancel** → editor closes, popout reverts to the canonical persisted VRM.

**Critical invariants:**
- Preview path is the AD-721d-3 endpoint — **does NOT consume AD-721d-1 iteration slots** (Captain hand-edits should not exhaust Counselor revision budget).
- DSL bytes flow through `AttachmentStore` SHA-256 refs (AD-731). Editor never inlines VRM bytes.
- Editor honest-degrades when `renderer_enabled=False` → preview path returns 503 → editor shows "Preview unavailable; commit blindly?" message; Captain can still approve a hand-edited DSL without a preview.
- Counselor-mediated revision path (AD-721d-1 `propose_appearance` POST) remains untouched and accessible from a separate button.

## Implementation

### Section 1: API surface check (server-side)

**No new server endpoints required.** Reuse:
- `POST /agents/{agent_id}/appearance/preview` (AD-721d-3, `routers/agents.py:532`).
- `PUT /agents/{agent_id}/appearance` (existing, `routers/agents.py:630`).

**Current DSL is prop-passed from parent, not fetched.** `CrewAvatarPopout` already holds the agent's appearance via the existing profile data path. The editor receives `currentDsl: AvatarDSL` as a prop from the popout — no new round-trip, no new `GET /agents/{agent_id}/appearance` endpoint to maintain. Grep confirmed (2026-05-17): only POST/PUT/DELETE endpoints exist on the appearance path; there is no GET to reuse. If the popout's profile payload does not yet carry the canonical DSL, the popout (not the editor) is responsible for surfacing it from the data it already loads.

### Section 2: New `ui/src/components/profile/CrewAvatarEditor.tsx`

A modal/overlay component mounted from `CrewAvatarPopout`. Props: `agentId: string`, `currentDsl: AvatarDSL` (prop-passed from popout per Section 1, NOT fetched), `onApproved: () => void`, `onCancelled: () => void`.

Controls (subset of `AvatarDSL` schema — verify in pre-flight from `src/probos/avatars/dsl.py`):

- **Body type** — select (slim / average / athletic / etc., per DSL enum).
- **Skin tone** — color picker.
- **Hair style** — select.
- **Hair color** — color picker.
- **Outfit** — select.
- **Outfit color** — color picker.
- **Expression overrides** — sliders for the AD-721d expression channels (happy, surprised, etc.).

Each form change debounced at 500 ms → POSTs preview → swaps VRM viewer source.

### Section 3: Integration into `CrewAvatarPopout.tsx`

Add an "Edit appearance" button next to the existing Counselor "Propose" button. Mount `CrewAvatarEditor` on click. While the editor is mounted:

- The popout's `CrewVRM` component reads its `vrmUrl` from the editor's preview attachment (when present) or from the canonical persisted VRM (when no preview yet).
- Counselor "Propose" button is disabled while editor is open (prevent dual-edit collision).

### Section 4: API client helpers

Add to `ui/src/api/avatars.ts` (or equivalent — verify path in pre-flight):

```typescript
export async function previewAvatar(agentId: string, dsl: unknown): Promise<{attachment_id: string; size_bytes: number}> { ... }
export async function commitAvatar(agentId: string, dsl: unknown): Promise<void> { ... }
```

These wrap the existing endpoints (no `getAvatarDsl` helper — the current DSL is prop-passed from `CrewAvatarPopout`; see Section 1). Error handling:
- 503 → show "Preview unavailable" but allow commit.
- 422 → show schema error inline at the offending field.
- 413 → "Preview too large; reduce model complexity."

### Section 5: Honest-degrade matrix

| Condition | Behavior |
|---|---|
| `renderer_enabled=False` | Preview path 503; editor shows banner "Preview unavailable; commit will apply without preview." |
| Blender unavailable | Preview path 503 (same as above). |
| `propose_appearance` not supported by agent | Captain editor still works (DSL persistence path doesn't go through `propose_appearance`). |
| Schema violation in Captain's edit | 422 from preview; editor shows field-level error; commit button disabled until valid. |

## Tests

`ui/src/components/profile/__tests__/CrewAvatarEditor.test.tsx` (+8 vitest):

1. `mounts with initial DSL populated into form controls` — assert color pickers, selects, sliders reflect the DSL.
2. `debounced preview POST on field change` — change body_type → wait 500 ms → assert exactly one fetch to `/preview`.
3. `swaps VRM viewer to preview attachment on successful preview` — mock 200 response with `attachment_id=abc123`, assert popout `CrewVRM` props now point at the preview URL.
4. `honest-degrade banner on 503` — preview returns 503, banner visible, commit button still enabled.
5. `field-level error on 422` — schema violation in skin tone, error shown next to the picker.
6. `Approve calls PUT /appearance with the edited DSL` — assert exact body shape.
7. `Cancel reverts popout to canonical VRM` — assert `CrewVRM.vrmUrl` props reset.
8. `Counselor Propose button disabled while editor is open` — assert disabled attribute.

## What this does NOT change

- AD-721d-1 Counselor revision iteration counter — Captain edits NEVER increment it (preview endpoint is separate by design).
- `propose_appearance` LLM path — untouched.
- Persistence schema (`AvatarDSL`) — extensions only via new fields, no rename/removal.
- `CrewVRM.tsx` — untouched (used as-is by the editor's preview viewer).

## Tracking

- `DECISIONS.md` — append AD-721a shipped entry.
- `PROGRESS.md` — bump highest-AD line if needed.
- `docs/development/roadmap.md` — mark AD-721a shipped.
- `gh issue close 528 --comment "Shipped Wave 168 (AD-721a). Captain-driven inline avatar editor in CrewAvatarPopout; uses AD-721d-3 preview path; persistence via existing PUT /appearance. See DECISIONS.md."`

## Acceptance Criteria

1. New file: `ui/src/components/profile/CrewAvatarEditor.tsx`.
2. New API helpers in `ui/src/api/avatars.ts` (or existing module).
3. `CrewAvatarPopout.tsx` mounts the editor and disables Counselor Propose while open.
4. 8 vitest pass.
5. `cd ui; npm run build` succeeds (AD-738b gate).
6. `cd ui; npx vitest run` green.
7. Full Python gate green: `pytest tests/ -q -n 4 --dist=loadfile`.
8. Zero new pip / npm deps.
9. Captain hand-edits do NOT consume AD-721d-1 iteration slots — verify by mock-counting `iteration_count(agent_id)` is not called in the editor path.
10. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-05-17)

```
ls ui/src/components/profile/
  CrewVRM.tsx              (component to wrap)
  CrewAvatarPopout.tsx     (modify to add Edit button + mount editor)

grep "/appearance/preview" src/probos/routers/agents.py
  line 532: @router.post("/{agent_id}/appearance/preview")
  line 533: async def preview_agent_appearance(
  line 605: # AD-731 invariant: bytes through AttachmentStore SHA-256 refs.
  line 627: return {"agent_id": agent_id, "attachment_id": sha, "size_bytes": len(blob)}

grep "/appearance" src/probos/routers/agents.py | head -5
  line 426: @router.post("/{agent_id}/appearance/propose", ...)
  line 532: @router.post("/{agent_id}/appearance/preview")
  line 631: @router.put("/{agent_id}/appearance")
  # NO GET /appearance endpoint exists — current DSL flows in as a prop
  # from CrewAvatarPopout (which already holds the profile payload).
  # All 6 endpoints on this path: POST propose:426, POST preview:532,
  # PUT:630, POST vrm:711, DELETE proposal-history:804, POST mediate:974.

ls src/probos/avatars/dsl.py
  6103 bytes (AvatarDSL Pydantic model — Captain editor mirrors these fields)

ls src/probos/avatars/proposal_history.py
  7052 bytes (iteration counter — Captain edits MUST NOT call append())

grep "max_proposal_iterations" src/probos/routers/agents.py
  line 471: cfg_max = int(getattr(runtime.config.avatars, "max_proposal_iterations", 3))
  # ^ Confirms iteration cap lives on propose path only, NOT preview path
```
