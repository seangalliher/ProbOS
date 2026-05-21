# Review: AD-762 — Relocate ProactiveStatus from WardRoom to Settings
**Verdict:** ⚠️ Conditional — one Required finding before build
**Settings panel is schema-driven (section_registry.py + SettingsMain.tsx branch) not import-and-render; the prompt's wiring guidance is too vague.**

## Required (must fix before building)
1. **Custom-panel wiring is under-specified.** The Settings panel does NOT have a simple "add an import + render" pattern. It's two-layer:
   - Backend: `src/probos/settings/section_registry.py` declares `SECTIONS` (typed schema with `section_id`, `label`, `glyph`, `domain`, `fields`). Field-driven sections render automatically.
   - Frontend: `ui/src/components/settings/SettingsMain.tsx:283` has explicit per-section branches for custom panels: `{section.section_id === 'perception' && <PerceptionLivePanel />}`.
   - `ProactiveStatusSection` is a CUSTOM panel (status payload + toggle), NOT a field-driven section. The prompt must explicitly instruct:
     - Add a `SectionDescriptor(section_id="proactive", label="Proactive", glyph=..., domain="Core", description=..., fields=())` to `section_registry.py` `SECTIONS`.
     - Add a `{section.section_id === 'proactive' && <ProactiveStatusSection />}` branch to `SettingsMain.tsx` next to the existing `perception` branch.
     - Update `tests/test_ad741_section_registry.py` for the new section descriptor.

## Recommended
1. Domain assignment: "Core" is the safest bucket. Confirm with Captain if a new domain "Operations" is preferred — both work.
2. Glyph choice: amber/blue trust spectrum, stroke-based SVG. Reuse `SECTION_ICONS` map in `ui/src/components/settings/icons.tsx:140` rather than inventing a new one.

## Nits
- Move target file path is fine: `ui/src/components/settings/sections/ProactiveStatusSection.tsx` matches the `PerceptionLivePanel.tsx` sibling pattern.
- `ui/src/components/wardroom/index.ts` does re-export `ProactiveStatus` (verified `index.ts:2`) — remove that line as the prompt instructs.

## Verified
- `ProactiveStatus.tsx` exists at `ui/src/components/wardroom/ProactiveStatus.tsx`. ✓
- `WardRoomPanel.tsx:213` renders `<ProactiveStatus />` inside the default-view branch (line 5 import, line 213 render). ✓
- `WardRoomPanel.tsx` line numbers in prompt: prompt doesn't pin specific line numbers (good — avoids drift). ✓
- `SettingsPanel.tsx` and `SettingsMain.tsx` exist. ✓
- Section pattern with custom-panel branches verified in `SettingsMain.tsx:283`. ✓
- Phantom-API precheck hits on `ProactiveStatus.tsx`, `ProactiveStatusSection.tsx`, `WardRoomPanel.tsx`, `SettingsPanel.tsx` are false positives — script scans only `src/probos/*.py`. Documented.

## Re-review (2026-05-20)
Required finding #1 (schema-driven section wiring under-specified) addressed: prompt §2 rewritten to enumerate backend `SectionDescriptor` registration in `section_registry.py` + frontend `SettingsMain.tsx` per-section branch, with `tests/test_ad741_section_registry.py` update added to §3. Required findings cleared. **Ready for GATE 1.**
