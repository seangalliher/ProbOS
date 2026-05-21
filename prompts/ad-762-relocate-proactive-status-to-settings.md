# AD-762 — Relocate ProactiveStatus panel from WardRoom to Settings

Status: drafted
Issue: #708
Depends on: AD-752 (ProactiveStatus component)

## Captain bug report (2026-05-20)

The PROACTIVE STATUS panel (next inbox scan, next calendar scan, work-hours, quiet-hours, last scan findings, "Disable proactive" toggle) is currently rendered inside the WardRoom panel. It belongs in Settings.

## Why this is wrong

- **HXI surface intent.** WardRoom is for channels and 1:1 DMs — communication. ProactiveStatus is a runtime configuration/status surface (scheduler state + a global enable toggle). Mixing surface intents adds cognitive load and violates HXI Design Principle #5 (progressive disclosure) and #9 (alert-driven layout) — proactive status is never the thing the Captain is trying to act on in WardRoom.
- **Discoverability.** Captains looking for "is proactive on? when does it next scan?" will instinctively go to Settings, not WardRoom.
- **Toggle placement.** The "Disable proactive" checkbox is a global behaviour flag. Global flags live in Settings alongside other runtime toggles.

## Scope (v1)

### 1. Move the component
- Move `ui/src/components/wardroom/ProactiveStatus.tsx` to `ui/src/components/settings/sections/ProactiveStatusSection.tsx`.
- Remove the export from `ui/src/components/wardroom/index.ts`.
- Remove the import + render site from `ui/src/components/wardroom/WardRoomPanel.tsx`.

### 2. Add it to the Settings panel (two-layer wiring)
The Settings panel is schema-driven — adding a custom panel section requires BOTH backend registry AND frontend branch wiring (mirrors the existing `perception` section):

- **Backend** — `src/probos/settings/section_registry.py`: append a `SectionDescriptor(section_id="proactive", label="Proactive", glyph="◐", domain="Core", description="Next inbox/calendar scan, work-hours, quiet-hours, and the global enable toggle.", fields=())` to the `SECTIONS` tuple. `fields=()` because this is a custom panel, not a field-driven section.
- **Frontend custom-panel branch** — `ui/src/components/settings/SettingsMain.tsx` already has a per-section branch pattern at line ~283: `{section.section_id === 'perception' && <PerceptionLivePanel />}`. Add a sibling branch `{section.section_id === 'proactive' && <ProactiveStatusSection />}` next to it, with the corresponding `import ProactiveStatusSection from './sections/ProactiveStatusSection';` at the top.
- The section renders the same payload (`/api/proactive/status`) the WardRoom panel showed: next inbox scan, next calendar scan, work-hours, quiet-hours, last scan findings, and the global enable toggle.
- Reuse `SECTION_ICONS` in `ui/src/components/settings/icons.tsx` if a new glyph is needed; do not invent ad-hoc icons. No emoji.
- Update `tests/test_ad741_section_registry.py` to expect the new section descriptor (this test guards against phantom field references and section drift).

### 3. Tests
- Move `ui/src/__tests__/ProactiveStatus.test.tsx` references from `../components/wardroom/ProactiveStatus` to the new path.
- Add a Vitest test that `SettingsMain` renders `ProactiveStatusSection` when `section_id === 'proactive'` is selected.
- Add/update `tests/test_ad741_section_registry.py` to assert the new `SectionDescriptor` is registered with the expected `section_id`, `label`, `domain`, and empty `fields` tuple.
- Remove (or update) any WardRoom test that asserted ProactiveStatus was present in the WardRoom DOM.
- Existing payload-rendering and toggle-behaviour assertions stay identical.

## Out of scope

- Changing the proactive scheduler behaviour itself.
- Adding new fields to the status payload.
- AD-759, AD-760, AD-761 (other in-flight UX work).

## Acceptance signals

- Opening WardRoom shows only channels and DMs — no PROACTIVE STATUS block.
- Opening Settings shows a "Proactive" section with the same content (status fields + Disable toggle).
- All existing payload + toggle assertions still pass under the new path.
- `npm run build` clean.

## Engineering principles compliance

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
- Same component shape; no new public APIs.
- No emoji.
- Test coverage preserved.
- One reason to change per surface (SRP): WardRoom = comms, Settings = configuration.
