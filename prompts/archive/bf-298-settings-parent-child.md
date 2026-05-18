# BF-298 — Settings parent/child toggle UX + perception status badge

**Wave:** 171
**Closes:** (BF — no GH issue; cross-references #665)
**Depends on:** AD-741 (Wave 170 Settings shell shipped). AD-733 v1 PerceptionLivePanel shipped.
**Estimated tests:** +6 vitest (no pytest)
**Risk:** low — UI-only; no server changes; no wire-format changes.

---

## Problem

Wave 170 shipped `PerceptionLivePanel.tsx` (START/STOP camera, status row, vision-tier warning) but `SettingsMain.FieldRow` has no concept of a `disabled` state. Three usability gaps:

1. **Child fields stay enabled when parent is off.** With `perception.enabled = false`, the operator can still flip `perception.camera.enabled`, `perception.camera_max_fps_server`, etc. — they take effect on next APPLY, but the subsystem master is off, so nothing happens. Confusing.
2. **No section-level status.** Operator opens Settings → Perception and has no quick read on "is anything actually running?". They must scan three rows.
3. **No aria-disabled signalling** for screen readers when a field is functionally inert.

---

## Solution

### Section 1: Add `disabled` to `FieldRow` (`ui/src/components/settings/SettingsMain.tsx`)

```
===SEARCH===
function FieldRow({
  field,
  initialValue,
  draftValue,
  secretPresent,
  errors,
  onChange,
}: {
  field: FieldDescriptorDTO;
  initialValue: any;
  draftValue: any;
  secretPresent: boolean | undefined;
  errors: { msg: string }[];
  onChange: (value: any) => void;
}) {
  const value = draftValue !== undefined ? draftValue : initialValue;
  const dirty = draftValue !== undefined;
===REPLACE===
function FieldRow({
  field,
  initialValue,
  draftValue,
  secretPresent,
  errors,
  onChange,
  disabled = false,
  disabledReason = '',
}: {
  field: FieldDescriptorDTO;
  initialValue: any;
  draftValue: any;
  secretPresent: boolean | undefined;
  errors: { msg: string }[];
  onChange: (value: any) => void;
  disabled?: boolean;
  disabledReason?: string;
}) {
  const value = draftValue !== undefined ? draftValue : initialValue;
  const dirty = draftValue !== undefined;
===END REPLACE===
```

For each control branch (bool/enum/int/float/text), thread `disabled` and `aria-disabled`. Example for the `bool` branch (apply analogously to all input branches):

```
===SEARCH===
  } else if (field.kind === 'bool') {
    control = (
      <button
        onClick={() => onChange(!value)}
        data-testid={`field-bool-${field.field_id}`}
        style={{
          background: value ? 'rgba(240,176,96,0.12)' : 'transparent',
          border: `1px solid ${value ? STROKE_AMBER : STROKE_DIM}`,
          color: value ? STROKE_AMBER : STROKE_DIM,
          padding: '3px 10px',
          fontSize: 10,
          letterSpacing: 1,
          cursor: 'pointer',
          borderRadius: 3,
        }}
      >
        {value ? 'ON' : 'OFF'}
      </button>
    );
  }
===REPLACE===
  } else if (field.kind === 'bool') {
    control = (
      <button
        onClick={() => { if (!disabled) onChange(!value); }}
        disabled={disabled}
        aria-disabled={disabled}
        title={disabled ? disabledReason : undefined}
        data-testid={`field-bool-${field.field_id}`}
        style={{
          background: value ? 'rgba(240,176,96,0.12)' : 'transparent',
          border: `1px solid ${value ? STROKE_AMBER : STROKE_DIM}`,
          color: value ? STROKE_AMBER : STROKE_DIM,
          padding: '3px 10px',
          fontSize: 10,
          letterSpacing: 1,
          cursor: disabled ? 'not-allowed' : 'pointer',
          borderRadius: 3,
          opacity: disabled ? 0.4 : 1,
        }}
      >
        {value ? 'ON' : 'OFF'}
      </button>
    );
  }
===END REPLACE===
```

Apply the same `disabled` / `aria-disabled` / `title` / `opacity: disabled ? 0.4 : 1` / `cursor: disabled ? 'not-allowed' : ...` shape to:
- the `enum` branch buttons (each option button)
- the `int` / `float` `<input type="number">` (use `disabled={disabled}` directly — native HTML)
- the `text` `<input type="text">` (use `disabled={disabled}` directly)

### Section 2: Compute `disabled` per-field in `SettingsMain`'s render loop

```
===SEARCH===
      {section.fields.map(field => {
        const initial = getNested(snapshot.config, field.field_id);
        const draftValue = draft[field.field_id];
        const secretPresent = snapshot.secret_present?.[field.field_id];
        const fieldErrors = errorsByField[field.field_id] ?? [];
        return (
          <FieldRow
            key={field.field_id}
            field={field}
            initialValue={initial}
            draftValue={draftValue}
            secretPresent={secretPresent}
            errors={fieldErrors}
            onChange={value => setDraftField(field.field_id, value)}
          />
        );
      })}
===REPLACE===
      {section.fields.map(field => {
        const initial = getNested(snapshot.config, field.field_id);
        const draftValue = draft[field.field_id];
        const secretPresent = snapshot.secret_present?.[field.field_id];
        const fieldErrors = errorsByField[field.field_id] ?? [];
        // BF-298: parent/child gating — when a section's master toggle is OFF,
        // every other field in the section is functionally inert until APPLY.
        // The master toggle itself stays enabled so the operator can flip it on.
        let disabled = false;
        let disabledReason = '';
        if (section.section_id === 'perception') {
          const masterDraft = draft['perception.enabled'];
          const masterValue = masterDraft !== undefined
            ? masterDraft
            : getNested(snapshot.config, 'perception.enabled');
          const masterOn = Boolean(masterValue);
          if (!masterOn && field.field_id !== 'perception.enabled') {
            disabled = true;
            disabledReason = 'Enable the Perception subsystem first.';
          }
        }
        return (
          <FieldRow
            key={field.field_id}
            field={field}
            initialValue={initial}
            draftValue={draftValue}
            secretPresent={secretPresent}
            errors={fieldErrors}
            onChange={value => setDraftField(field.field_id, value)}
            disabled={disabled}
            disabledReason={disabledReason}
          />
        );
      })}
===END REPLACE===
```

### Section 3: Status badge in `PerceptionLivePanel.tsx`

Add a top status row immediately under the header. Compute the badge string from live state:

```
===SEARCH===
  return (
    <div
      data-testid="perception-live-panel"
      style={{
        marginBottom: 18,
        padding: 12,
        border: `1px solid ${cameraActive ? STROKE_AMBER : STROKE_DIM}`,
        borderRadius: 4,
        background: cameraActive ? 'rgba(240,176,96,0.06)' : 'transparent',
      }}
    >
===REPLACE===
  // BF-298: status badge — compute from live snapshot + camera-store state.
  const perceptionEnabled = Boolean(
    (snapshot.config as any).perception?.enabled,
  );
  let badgeText: string;
  let badgeColor: string;
  if (!perceptionEnabled) {
    badgeText = 'subsystem: OFF';
    badgeColor = STROKE_DIM;
  } else if (cameraActive) {
    badgeText = 'subsystem: ON · camera live';
    badgeColor = STROKE_AMBER;
  } else {
    badgeText = 'subsystem: ON · 0 modalities active';
    badgeColor = STROKE_ENGINEERING;
  }

  return (
    <div
      data-testid="perception-live-panel"
      style={{
        marginBottom: 18,
        padding: 12,
        border: `1px solid ${cameraActive ? STROKE_AMBER : STROKE_DIM}`,
        borderRadius: 4,
        background: cameraActive ? 'rgba(240,176,96,0.06)' : 'transparent',
      }}
    >
      <div
        data-testid="perception-status-badge"
        style={{
          fontSize: 9,
          fontFamily: "'JetBrains Mono', monospace",
          letterSpacing: 1.5,
          color: badgeColor,
          marginBottom: 8,
          textTransform: 'uppercase',
        }}
      >
        {badgeText}
      </div>
===END REPLACE===
```

### Section 4: Tests — `ui/src/components/settings/__tests__/PerceptionParentChild.test.tsx` (NEW)

6 cases:

1. `master OFF → camera.enabled receives aria-disabled` — render Settings with `perception.enabled=false`, verify `field-bool-perception.camera.enabled` has `aria-disabled="true"`.
2. `master OFF → camera_max_fps_server number input is disabled` — same setup, assert the number input has the `disabled` attribute.
3. `master OFF → master toggle itself stays enabled` — `field-bool-perception.enabled` is NOT disabled.
4. `master ON → all children enabled` — `perception.enabled=true`, no children have aria-disabled.
5. `draft master toggle flip → children re-enable without APPLY` — operator flips master to ON in the draft; child fields immediately become enabled (uses draft, not committed snapshot).
6. `status badge reflects each of three states` — snapshot variations: (a) `enabled=false` → "subsystem: OFF"; (b) `enabled=true` + camera inactive → "subsystem: ON · 0 modalities active"; (c) `enabled=true` + camera active → "subsystem: ON · camera live".

Use the existing `useSettingsStore` and `useCameraStore` test helpers from `SettingsPanel.test.tsx`. No new mocks at the store boundary.

---

## What This Does NOT Change

- Server-side configuration shape.
- AD-741 APPLY/RESET semantics.
- PerceptionLivePanel's START/STOP behavior — only adds a status badge above existing content.
- Other sections (mcp, federation, etc.) — they don't have a master toggle, so the `section_id === 'perception'` gate keeps them unaffected.

---

## Tracking

- PROGRESS.md "Wave 171" — BF-298 row.
- DECISIONS.md not required (UX polish, no architectural decision).

---

## Acceptance Criteria

- All 6 new Vitest tests pass.
- Existing SettingsPanel / SettingsSidebar tests still pass.
- `cd ui && npx vitest run` clean. (BF-279 / AD-738b: also run `cd ui && npm run build` before commit.)
- Visual smoke: open Settings → Perception with `perception.enabled=false`. All non-master fields are visibly dimmed (opacity 0.4). Title attribute on hover reads "Enable the Perception subsystem first." Master toggle is still clickable. Flip master to ON; children un-dim instantly.
- HXI Design Principles preserved (no emoji, no Material Design, monospace + stroke-only colors).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-17)

| Claim | Verification |
|---|---|
| `FieldRow` exists in `SettingsMain.tsx` at line 21 | `ui/src/components/settings/SettingsMain.tsx:21` |
| Existing `data-testid="field-bool-${field.field_id}"` pattern | `ui/src/components/settings/SettingsMain.tsx:73` |
| `useSettingsStore` exposes `snapshot`, `draft`, `setDraftField` | `ui/src/components/settings/SettingsMain.tsx:215-218` |
| `getNested(snapshot.config, 'perception.enabled')` accessor pattern | `ui/src/components/settings/SettingsMain.tsx:268` |
| `PerceptionLivePanel.tsx` exists with `STROKE_AMBER`/`STROKE_DIM`/`STROKE_ENGINEERING` constants | `ui/src/components/settings/sections/PerceptionLivePanel.tsx:13-15` |
| `useCameraStore` provides `active`, `error`, `framesSent` | `ui/src/components/settings/sections/PerceptionLivePanel.tsx:18-21` |
| Vitest + jsdom present (existing tests) | `ui/src/components/settings/__tests__/SettingsPanel.test.tsx` |
