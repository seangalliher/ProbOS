# Avatar Assets (AD-721i-1)

ProbOS's avatar renderer (`src/probos/avatars/_blender/render_avatar.py`)
reads operator-installed Blender assets from `data/avatar-assets/`. The
**bytes are operator-fetched**, not bundled in the repo. The audit ledger
is `data/avatar-assets/MANIFEST.md`.

## License policy

Per `.github/copilot-instructions.md` license whitelist:

- ✅ CC0 / MIT / Apache-2.0 / BSD / CC-BY (attribution preserved).
- ❌ GPL / AGPL / CC-BY-SA / CC-BY-NC / proprietary.

Anything outside the whitelist is rejected at the
`probos.avatars.asset_manifest.validate_license` boundary.

## Workflow

### Propose a new asset

1. Open a PR adding a row to `data/avatar-assets/MANIFEST.md` under the
   correct section (Base meshes / Hair styles / Outfits / Materials).
2. Set `disposition: RESEARCH`. Populate `source_url`, `license`,
   `attribution`. `sha256` and `version` may be `TBD` until the asset is
   actually downloaded.
3. Captain reviews. If the license is on the whitelist and the source is
   reputable, Captain flips the row to `APPROVED`.

### Operator: fetch APPROVED assets

```pwsh
./scripts/avatar-assets-fetch.ps1
```

The script:

- Filters the manifest to `APPROVED` rows only.
- Downloads each via `Invoke-WebRequest`.
- Verifies SHA-256 against the manifest. On mismatch, deletes the file and
  exits non-zero.
- Writes attribution to `data/avatar-assets/ATTRIBUTION.txt` (one line per
  asset for CC-BY compliance).

### Revoke an asset

1. Flip the row's `disposition` from `APPROVED` to `REJECTED` in a PR.
2. Document the reason in the PR body.
3. Operators manually delete the corresponding files from
   `data/avatar-assets/_<category>/`.
4. Re-running the fetcher rebuilds `ATTRIBUTION.txt` without the removed
   asset.

## What This Does NOT Do (yet)

- No assets are bundled in v1 — every row is `RESEARCH` until Captain ruling.
- No AttachmentStore promotion of avatar assets.
- No per-asset versioning / pinning beyond the SHA-256 verification.
- No per-asset license file capture (the attribution string is the audit
  trail; the upstream license file is referenced by URL).
