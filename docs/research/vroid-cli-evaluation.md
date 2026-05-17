# VRoid Studio CLI evaluation for AD-721i renderer backend

**Date:** 2026-05-17. **Author:** Builder (Wave 167, AD-721i-2). **Closes:** #543.

## Disposition (one-line verdict)

**REJECT** — VRoid Studio has no public headless / CLI mode and is published under a proprietary EULA. The existing AD-721i Blender + saturday06 VRM-Addon backend remains the v1 renderer for ProbOS.

## Summary

| Dimension | Finding |
|---|---|
| CLI / headless mode available | **No** — VRoid Studio is a GUI-only application; no documented `--export` / `--import` / batch invocation in the official 1.x line. |
| License | **Proprietary** — Pixiv's VRoid Studio is distributed under a closed EULA (free-to-use binary, source not published). The EULA permits commercial use of *output VRMs* on operator-set terms but does NOT grant rights to embed, redistribute, or script the application itself. |
| Output VRM license metadata | **Operator-set** at export time via the in-app metadata panel (avatar permission UI). Default unset; the operator must populate `meta.licenseUrl` and the `meta.allowedUser` / `meta.commercialUssageName` (sic) fields BEFORE export, otherwise the VRM ships with empty license metadata — a recurring source of downstream licensing ambiguity flagged in the user memory `License hygiene (2026-05-09)` notes. |
| Deterministic parameter-driven output | **Unknown / N/A** — without a CLI there is no way to feed a parameter file. The GUI-driven export pipeline embeds session state (cursor positions, undo history) into intermediate files and is not byte-deterministic in the AD-721i sense. |
| Platform support | **Windows + macOS only.** No Linux build. This alone disqualifies it as the OSS-default backend (ProbOS targets Linux servers as a first-class deployment target). |
| BF-280 subprocess compatibility | **N/A** — no subprocess to evaluate. If a CLI mode were added by Pixiv in a future release, the standing `_run_sync` pattern from `shell_command.py:154-157` would handle it. |

## Citations

1. **VRoid Studio download / docs landing page** (Pixiv-operated) lists only GUI installer binaries for Windows and macOS, with no command-line flag documentation. Confirmed at the canonical `https://vroid.com/en/studio` product page (accessed 2026-05-17).
2. **VRoid Studio EULA** linked from the application's About panel and reproduced on `https://vroid.com/en/license` — distributes the binary under a Pixiv-controlled EULA, not an OSI-recognized license. No source repository is published (Pixiv's `pixiv/` org on GitHub does not include a VRoid Studio repo).
3. **VRM 1.0 spec metadata fields** (`meta.licenseUrl`, `meta.allowedUser`, `meta.commercialUssageName`) — defined in the Khronos VRM 1.0 schema at `https://github.com/vrm-c/vrm-specification`. Confirmed that defaults are unset; populating them is the exporter's responsibility.
4. **AD-721i Blender + saturday06 backend** — current `src/probos/avatars/blender_renderer.py:3-10` comment block correctly captures the BYOL pattern. Blender is GPL-3.0; ProbOS invokes it as an OS-level subprocess. Apache 2.0 boundary preserved because no GPL code is linked, embedded, or shipped — same shape as the rhubarb / piper / ffmpeg subprocess patterns elsewhere in the codebase.

## Recommendation

Keep **Blender + saturday06 VRM-Addon** as the v1 renderer. The three blocking constraints (no CLI; proprietary license; Linux-incompatible) are independent — any one of them would be sufficient to reject. Together they make VRoid Studio a non-starter for the OSS-default code path.

VRoid Studio remains a perfectly reasonable option for the *operator* to produce baseline VRMs locally and install them via AD-721h's upload UI or under the AD-721g `_baselines/` directory. Both surfaces are operator-driven and consume the bytes the operator chooses to install; they impose no license claim on the produced VRMs. This is the right tier-up path — operator-elected, never default.

## If ADOPT — implementation outline (not applicable for REJECT)

For future reference: had the disposition been ADOPT, the swap point would be `AvatarRendererAgent.act()` in `src/probos/agents/utility/avatar_agents.py`. A new `VroidRenderer` class would mirror the `BlenderRenderer.render(dsl, agent_id) -> Path` contract; a new `cfg.avatars.renderer_backend: 'blender' | 'vroid'` selector would dispatch between them; AD-721i-3 would build the renderer; AD-721i-4 would port the tests. None of this lands today.

## Forward markers

None. AD-721i-3 is NOT filed — re-evaluation only triggers if Pixiv publishes a CLI or open-source release of VRoid Studio. Operators can still use VRoid Studio output via the manual install paths (AD-721g / AD-721h) at any time.

## Operator note

Operators who choose to use VRoid Studio output VRMs locally MUST populate the in-app license metadata fields before export. ProbOS's AD-721i-1 manifest whitelist (CC0 / MIT / Apache / BSD / CC-BY) does not validate VRoid-produced files automatically — the operator certifies the disposition by adding the file to `data/avatar-assets/MANIFEST.md`. Empty / proprietary metadata = REJECTED disposition.
