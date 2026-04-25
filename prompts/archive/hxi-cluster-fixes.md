# AD-296: HXI Cluster Label Billboarding + Security Pool Group

## Objective

Two follow-up fixes from the AD-294 HXI crew cluster build:

1. **Text labels must billboard** — Team name labels currently rotate with the scene, becoming unreadable. Labels should always face the camera like a gyroscope (billboard behavior).

2. **Red team agents are ungrouped** — The `red_team` pool has no pool group, so red team agents float in an "_ungrouped" cluster instead of being part of the Security/Tactical crew team.

## Pre-read

- `ui/src/canvas/clusters.tsx` — current TeamClusters component with Text labels
- `src/probos/runtime.py` — pool group registration (search for `pool_groups.register`)

## Step 1: Billboard Text Labels

### `ui/src/canvas/clusters.tsx`

Import `Billboard` from `@react-three/drei`:

```typescript
import { Text, Billboard } from '@react-three/drei';
```

Wrap each `<Text>` component inside a `<Billboard>`:

```tsx
<Billboard follow lockX={false} lockY={false} lockZ={false}>
  <Text
    position={[0, radius * 1.3, 0]}
    fontSize={0.25}
    color={tintHex}
    anchorX="center"
    anchorY="bottom"
    fillOpacity={0.5}
    font={undefined}
  >
    {displayName}
  </Text>
</Billboard>
```

The `Billboard` component from drei makes its children always face the camera regardless of orbit controls rotation. The `follow` prop ensures continuous tracking.

## Step 2: Security Pool Group

### `src/probos/runtime.py`

Find the pool group registrations (search for `pool_groups.register`). After the existing groups (core, bundled, medical, self_mod), add:

```python
self.pool_groups.register(PoolGroup(
    name="security",
    display_name="Security",
    pool_names={"red_team"},
    exclude_from_scaler=False,
))
```

The red_team pool should NOT be excluded from the scaler — red team agents scale with demand like other agents.

### `ui/src/canvas/scene.ts`

The `red_team` pool already has a tint color (`'#c85068'`), so no changes needed here.

### `ui/src/store/useStore.ts`

Add `security` to the `GROUP_TINT_HEXES` map (if it exists in useStore.ts — it was added in AD-294):

```typescript
security: '#c85068',   // red — tactical (matches red_team pool tint)
```

## Testing

### `ui/src/__tests__/useStore.test.ts`

1. `test('red_team agents are in security group')` — Verify agents in the red_team pool get positioned within the security cluster, not in _ungrouped.

### Existing tests

Run all tests to verify no regressions:
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
- `cd ui && npx vitest run`

## Constraints

- `Billboard` is already available in `@react-three/drei` (installed dependency) — no new packages
- The security PoolGroup follows the same pattern as the other 4 groups
- Red team should NOT be excluded from the scaler (unlike medical)

## Success Criteria

- Team name labels always face the camera as the scene rotates — readable from any angle
- Red team agents appear in a "Security" cluster with the red tint color, not in "_ungrouped"
- The canvas shows 5 crew team clusters: Core, Bundled, Medical, Self-Mod, Security
- All existing tests pass
