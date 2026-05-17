# Avatar Assets Manifest (AD-721i-1)

This file is the **audit ledger** for every asset bundled into ProbOS's avatar
renderer (`src/probos/avatars/_blender/render_avatar.py`). The renderer reads
``<avatars_dir>/_base_meshes/<body_type>.blend`` (and the hair / outfit /
material counterparts); when missing, the procedural-capsule E10 fallback
keeps the pipeline alive but the result is intentionally crude.

This AD ships **zero asset bytes**. Every candidate below is `RESEARCH` until
Captain ruling flips it to `APPROVED`, at which point an operator runs
``scripts/avatar-assets-fetch.ps1`` to download the asset locally. The
gitignore at ``data/avatar-assets/_*/`` keeps the bytes out of the repo.

## License policy

CC0 / MIT / Apache-2.0 / BSD / CC-BY only. GPL / AGPL / CC-BY-SA / CC-BY-NC
and proprietary licenses are rejected at the validator boundary
(``probos.avatars.asset_manifest.validate_license``).

## Schema

Each section is a pipe-delimited markdown table with these columns:

| name | source_url | license | version | sha256 | attribution | disposition |

- ``disposition`` is one of ``APPROVED`` / ``RESEARCH`` / ``REJECTED``.
- ``sha256`` may be ``TBD`` for ``RESEARCH`` rows; ``APPROVED`` rows MUST
  carry the verified SHA-256 of the downloaded asset.
- ``attribution`` is the exact string the fetcher writes to
  ``data/avatar-assets/ATTRIBUTION.txt`` for CC-BY compliance.

## Base meshes (body_type)

| name | source_url | license | version | sha256 | attribution | disposition |
|------|------------|---------|---------|--------|-------------|-------------|
| quaternius_humanoid | https://quaternius.com/packs/ultimatemodularcharacters.html | CC0 | TBD | TBD | Quaternius (CC0) | RESEARCH |
| kaykit_character | https://kaylousberg.itch.io/kaykit-adventurers | CC0 | TBD | TBD | Kay Lousberg (CC0) | RESEARCH |
| khronos_brainstem | https://github.com/KhronosGroup/glTF-Sample-Assets/tree/main/Models/BrainStem | CC0 | TBD | TBD | Khronos Group (CC0) | RESEARCH |
| makehuman_community | https://github.com/makehumancommunity/makehuman | AGPL-3.0 | n/a | n/a | n/a | REJECTED |
| mixamo | https://www.mixamo.com/ | Proprietary (Adobe TOS) | n/a | n/a | n/a | REJECTED |
| ready_player_me | https://readyplayer.me/ | Proprietary | n/a | n/a | n/a | REJECTED |
| vroid_studio_outputs | https://vroid.com/en/studio | Per-file metadata (VRM) | n/a | n/a | n/a | REJECTED |

REJECTED rationale:
- **MakeHuman Community**: AGPL-3.0 propagates copyleft into anything that
  redistributes the assets. Pattern-only absorption (study the rig conventions)
  is acceptable; absorbing the binaries is not.
- **Mixamo**: Adobe Terms of Service restrict redistribution and tie usage to
  an Adobe account. Not OSS-compatible.
- **Ready Player Me**: Proprietary API + commercial overlay license.
- **VRoid Studio outputs**: VRM files carry per-file licensing metadata; every
  exported avatar has its author's terms baked in. See the 2026-05-09 license
  hygiene note in user memory.

## Hair styles

| name | source_url | license | version | sha256 | attribution | disposition |
|------|------------|---------|---------|--------|-------------|-------------|
| quaternius_hair_pack | https://quaternius.com/packs/ultimatemodularcharacters.html | CC0 | TBD | TBD | Quaternius (CC0) | RESEARCH |

## Outfits

| name | source_url | license | version | sha256 | attribution | disposition |
|------|------------|---------|---------|--------|-------------|-------------|
| quaternius_outfit_starter | https://quaternius.com/packs/ultimatemodularcharacters.html | CC0 | TBD | TBD | Quaternius (CC0) | RESEARCH |

## Materials / Textures

| name | source_url | license | version | sha256 | attribution | disposition |
|------|------------|---------|---------|--------|-------------|-------------|
| polyhaven_starter | https://polyhaven.com/ | CC0 | TBD | TBD | Poly Haven (CC0) | RESEARCH |

## Audit trail

- Every change to this file is reviewed in PR.
- ``APPROVED`` rows MUST carry the verified SHA-256.
- Removing an asset: flip the row to ``REJECTED`` and document the reason in
  the PR body. The operator manually deletes the corresponding files; the
  fetcher will not re-download.
