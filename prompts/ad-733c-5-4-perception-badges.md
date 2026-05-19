# AD-733c-5-4 — HXI per-agent perception badges

**Parent AD:** AD-733c-5 (per-agent perception engagement — shipped Wave 176 backend-only).
**Issue:** none (forward marker filed in `docs/development/roadmap.md` Wave 176; no GH issue per AD-722c-3 standing rule).
**Status:** GATE 1 — drafting (Wave 177).
**Depends on:** AD-733c-5 backend (per-agent `PerceptionModeController` registry + extended `GET /api/perception/mode` response).
**Estimated tests:** +3 vitest. Zero new pytest.

---

## Problem

AD-733c-5 (Wave 176) promoted `PerceptionModeController` from singleton to per-agent. The backend now reports `{per_agent: {agent_id: mode}}` in `GET /api/perception/mode`, and the `POST /api/perception/engage` endpoint routes per-agent via the new registry. But the HXI doesn't render any of it:

- `CameraLiveIndicator.tsx` shows ONE mode badge that mirrors `usePerceptionModeStore.mode` (the runtime-wide singleton state — now a back-compat pointer at the *primary* agent's controller).
- `PerceptionLivePanel.tsx` MODE section has three preset buttons (DORMANT / AMBIENT / ENGAGED) that call `POST /api/perception/mode` *without* an agent — runtime-wide override.
- Operators cannot SEE which agent is in which mode. Per AD-733c-5's user story ("Hello Counselor" → only Ezri transitions), the HXI must visualize the per-agent state or the feature is invisible.

## Solution

Extend `usePerceptionModeStore` with `perAgent: Record<string, PerceptionMode>` populated from the `json.per_agent` field already shipped by AD-733c-5. Render the per-agent state in two places:

1. **`CameraLiveIndicator.tsx`** — when `perAgent` is non-empty, render a horizontal list of compact per-agent badges (one per registered agent). When `perAgent` is empty (legacy single-controller deployments OR registry unwired), keep the existing single-mode badge unchanged.
2. **`PerceptionLivePanel.tsx`** — add a MODE TABLE row beneath the existing preset buttons. Rows: `agent_id` → `MODE` swatch. Read-only in v1 (manual per-agent override is a forward marker — operator can hit `POST /api/perception/engage {agent}` directly via the Captain DM path for testing).

## Scope

- Modify `ui/src/store/usePerceptionModeStore.ts` — add `perAgent: Record<string, PerceptionMode>` state field, populated by `refresh()` from `json.per_agent`. Default to `{}` when the field is absent (back-compat).
- Modify `ui/src/components/perception/CameraLiveIndicator.tsx` — when `perAgent` non-empty AND has 2+ entries, render the per-agent badge list INSTEAD of the single MODE badge. Single-agent case keeps the legacy single badge (no UI churn for solo-Captain deployments). Stroke colors: amber `#f0b060` for `engaged`, mid-amber `#a07840` for `ambient`, dim `#666680` for `dormant` (mirrors existing `MODE_COLOR` constant). Inline SVG glyph (no emoji). Format: `EZRI:ENG` / `ATLAS:AMB` — agent_id uppercased, mode truncated to 3 chars to keep the indicator compact.
- Modify `ui/src/components/settings/sections/PerceptionLivePanel.tsx` — add a `data-testid="perception-per-agent-table"` block beneath the existing MODE preset buttons. Renders one row per `perAgent` entry. Reuses the existing `MODE_COLOR` constant. Block is conditional: rendered only when `Object.keys(perAgent).length > 0`.

## NOT in scope

- Per-agent manual override buttons (operator picks an agent and forces ENGAGED). Forward marker AD-733c-5-4-1.
- WebSocket push for per-agent mode changes (current polling is 2s via `usePerceptionModeStore.refresh()` ticker — fine for v1). Forward marker AD-733c-5-4-2.
- Callsign rendering (badges show agent_id, not callsign). Forward marker AD-733c-5-4-3 — requires `CallsignRegistry` snapshot in the HXI.
- Backend changes — `GET /api/perception/mode` already returns `per_agent`; `POST /api/perception/engage` already routes per-agent. Builder MUST NOT modify `src/probos/routers/perception.py`.
- HXI editor for `CrewProfile.perception` block — that's AD-733c-5-1 (separate forward marker, not this prompt).

## Pre-flight grep anchors (Builder MUST verify before locking edits)

1. `src/probos/routers/perception.py:233` — `GET /api/perception/mode` is `@router.get("/mode", ...)`. Confirm response includes `"per_agent": per_agent` (currently lines ~272-281).
2. `ui/src/store/usePerceptionModeStore.ts:40` — `usePerceptionModeStore` create() block. Confirm `refresh()` already parses `json.transitions` — add `perAgent` parsing alongside it.
3. `ui/src/components/perception/CameraLiveIndicator.tsx:18-23` — `MODE_COLOR: Record<PerceptionMode, string>` constant exists. Reuse, do not duplicate.
4. `ui/src/components/perception/CameraLiveIndicator.tsx:79-100` — existing `{mode && (<span data-testid="perception-mode-badge" ...>)` block. The per-agent list replaces this span when `perAgent` has 2+ entries.
5. `ui/src/components/settings/sections/PerceptionLivePanel.tsx:146-198` — MODE section + preset-button row + transitions block. Insert per-agent table block at the bottom of the MODE section (before the closing `</div>` of the mode-section wrapper).
6. `ui/src/components/perception/__tests__/` — existing component tests directory. New test file lands here.

## Engineering-principles audit

- **HXI Principle #3 (no emoji, inline SVG, amber/dim).** Per-agent badges use the existing `MODE_COLOR` palette (amber / mid-amber / dim). Mono font (`'JetBrains Mono'`). Format `AGENT:MODE` is text-only, no glyphs.
- **HXI Principle #4 (motion communicates state).** Reuse the existing `<animate>` pulse on the camera-live dot — the per-agent badges themselves are static text (mode change is communicated by color shift). Adding per-badge animation would clutter the indicator; consistent with the existing single-badge design.
- **HXI Principle #5 (progressive disclosure).** Single-agent deployments render the legacy single badge — no new visual elements when there's only one agent. Per-agent list surfaces only when `perAgent` has 2+ entries.
- **HXI Principle #9 (alert-driven layout).** Agents in `engaged` mode get the amber swatch (full attention). `ambient` is mid-amber. `dormant` is dim. The eye is drawn to the active agent automatically.
- **HXI Principle #11 (agentic-first).** N/A — this is a read-only visualization. The agentic path (Captain says "Hello Ezri" → backend transitions Ezri's controller) is already wired by AD-733c-5; this prompt only renders the result.
- **AD-738b UI gate.** Builder MUST run `cd ui && npx vitest run` AND `cd ui && npm run build`. Stale-bundle regression (BF-279) is the canonical "shipped code that operators never saw" trap.
- **BF-274 single-replace discipline.** TSX edits use single `replace_string_in_file` per adjacent block, NOT `multi_replace_string_in_file`. Adjacent JSX is the historical regression vector.
- **BF-287 (MagicMock at substrate boundary).** Vitest mocks `fetch` (the network boundary) via `vi.fn()`. Does NOT mock the Zustand store internals (`useStore.getState` is real; the slice is real). Tests assert against real store state after a real `refresh()` call.

## Test plan (+3 vitest)

New file: `ui/src/components/perception/__tests__/CameraLiveIndicator.perAgent.test.tsx`.

1. **`renders per-agent badges when perAgent has 2+ entries`** — seed store with `perAgent = {e1: 'engaged', e2: 'ambient'}`, mount `<CameraLiveIndicator />` with `active=true`. Assert two elements with `data-testid="perception-per-agent-badge-e1"` and `data-testid="perception-per-agent-badge-e2"`. Assert e1 element has amber color via `getComputedStyle`-equivalent or inline-style assertion; e2 has mid-amber.
2. **`falls back to single mode badge when perAgent has < 2 entries`** — seed store with `perAgent = {}` and `mode = 'ambient'`. Assert the legacy `data-testid="perception-mode-badge"` element is present and reads `AMBIENT`. Assert no per-agent badges rendered.
3. **`PerceptionLivePanel renders per-agent table when registry wired`** — separate `PerceptionLivePanel.perAgent.test.tsx` extension OR a single combined file (Builder's choice; pick whichever is cleaner). Seed `perAgent = {e1: 'engaged', e2: 'dormant'}`. Assert `data-testid="perception-per-agent-table"` block visible with two rows.

All tests use **real** `usePerceptionModeStore` (no MagicMock) — seed via `usePerceptionModeStore.setState(...)` and clean up via `useStore.setState` reset in `afterEach`. The `refresh()` itself is exercised in one regression test that mocks `fetch` to return a payload with `per_agent`, then asserts `useStore.getState().perAgent` equals the parsed map.

## Tracker updates (Builder)

- `PROGRESS.md` — append AD-733c-5-4 line under the Wave 177 in-flight block.
- `docs/development/roadmap.md` — flip the existing AD-733c-5-4 row from `(forward marker, filed Wave 176)` to `**SHIPPED Wave 177** (UI per-agent badges shipped against AD-733c-5 backend)`.
- `DECISIONS.md` — append `### AD-733c-5-4 — HXI per-agent perception badges (Wave 177)` block at build time.

## Acceptance criteria

1. `usePerceptionModeStore.perAgent: Record<string, PerceptionMode>` populated from `json.per_agent` on refresh; defaults to `{}` when absent.
2. `CameraLiveIndicator` renders per-agent badges when `perAgent` has ≥ 2 entries; renders legacy single badge otherwise.
3. `PerceptionLivePanel` renders per-agent table beneath MODE preset buttons when `perAgent` non-empty.
4. All 3 new vitest pass.
5. `cd ui && npx vitest run` exits 0; `cd ui && npm run build` exits 0 (no TypeScript errors, no console warnings).
6. No emoji introduced; all icons inline SVG with `strokeWidth: 1.5` / `strokeLinecap: round` per HXI Principle #3.
7. Zero diff on `src/probos/`, `tests/`, `pyproject.toml`, `LICENSE`, `THIRD_PARTY_LICENSES.md`.
8. Zero new pip / npm deps (0-line diff on `package.json` / `package-lock.json`).
9. Single-agent deployments render bit-for-bit identical UI to HEAD (back-compat regression test in vitest).
10. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md` (especially HXI Principles #3 / #4 / #5 / #11 + AD-738b UI gate).**
