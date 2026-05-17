# Skeletal Animation Library -- License Disposition (AD-721e, Wave 168)

**Chosen source:** Quaternius "Ultimate Animated Character Pack" v1.x
**License:** CC0 (public domain)
**Source URL:** https://quaternius.com/packs/ultimateanimatedcharacter.html
**Whitelist match:** CC0 is at the top of the Captain 2026-05-09 license whitelist (`.github/copilot-instructions.md`). No attribution required; redistribution allowed; commercial-friendly.
**Operator install:** `scripts/animations-fetch.ps1`. Operator manually extracts the pack into `data/avatars/animations/` and re-runs the script to compute SHA-256 entries for the manifest.
**Repository policy:** the `.glb` clip bytes are NOT shipped in the repo. `data/avatars/animations/` is gitignored (see `.gitignore`). Operators bring their own copy of the CC0 source, mirroring the existing AD-721g per-tier VRM precedent and the AD-738 Piper voice fetch pattern.

## Backup candidate

If Quaternius is unavailable at fetch time, **KayKit Character Animations** (CC0, https://kaykit.itch.io) provides equivalent humanoid clips. Same rigging convention (Mixamo bone names), same retargeting flow.

## REJECTED candidates

- **Mixamo (Adobe).** Mixamo redistribution terms are incompatible with OSS bundling per AD-721i-1 license whitelist (Wave 166). Operators MAY use Mixamo locally (Adobe's terms permit personal use), but the OSS repo must NOT ship Mixamo bytes and the fetch script must NOT point at Mixamo URLs. Confirmed in `scripts/animations-fetch.ps1` -- the whitelist guard rejects any non-whitelisted license value.
- **ActorCore.** Paid commercial licensing; conflicts with the OSS "free should stay free" Captain rule.
- **ReadyPlayerMe animation packs.** Closed-source service; license terms vary per pack and require attribution + service registration. Not suitable for OSS bundling.

## Bone retargeting

Quaternius/KayKit clips ship with Mixamo-prefixed bone names (`mixamorig:Hips`, `mixamorig:LeftArm`, ...). VRM Humanoid spec uses unprefixed standardized names (`hips`, `leftUpperArm`, ...). The runtime helper `ui/src/canvas/animation/retarget.ts:retargetMixamoToVRM(clip)` rewrites `THREE.KeyframeTrack.name` from `mixamorig:<X>.<channel>` to `<vrmName>.<channel>` before `mixer.clipAction(clip).play()`. Without this step the mixer silently fails to bind (ticks advance but no bones move). The retarget step preserves the CC0 source bytes verbatim on disk -- no derivative-redistribution concerns.

## Selected clips (v1)

| name | required | description |
|------|----------|-------------|
| `idle` | yes | gentle weight shift; head/chest motion only |
| `talking` | yes | hand gestures + head bob during speech |
| `listening` | yes | attentive forward lean |
| `thinking` | yes | head tilt + hand-to-chin |

## Forward markers

- **AD-721e-1** -- gesture / nod / shrug / typing animation packs. Trigger: Captain demand for more granular body language beyond the 4-state v1.
