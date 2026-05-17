# AD-721i-2 — VRoid Studio CLI alternative backend evaluation (research)

**Status:** ready-to-build (research-only)
**Closes:** #543
**Estimated tests:** 0 pytest, 0 vitest (research deliverable, no code shipped)
**Depends on:** AD-721i (shipped Wave 134)
**Independent of:** AD-721d-3, AD-721g, AD-721h, AD-720b

---

## Problem

AD-721i picked Blender + saturday06 VRM-Addon as the headless backend (`src/probos/avatars/blender_renderer.py`). Issue #543 (forward marker filed at Wave 134 gate-3) asks: is VRoid Studio's CLI a better default for the procedural-humanoid use case ProbOS is targeting? VRoid Studio is purpose-built for stylized humanoid VRMs — exactly our use case — whereas Blender is general-purpose and we're using it via a third-party add-on.

The hesitation in #543 is license: VRoid Studio's output VRMs carry per-file licensing metadata, and the CLI tooling itself may be paid/proprietary. The Captain wants a research answer before any code lands.

## Solution

Deliver a **research-only** disposition document. No code. No new pip/npm deps. No new config. The deliverable is a single markdown file under `docs/research/` and a forward-marker AD entry (close or open). The decision tree is:

- VRoid Studio CLI: **paid / proprietary / closed-source** → close #543 as "rejected — Blender + saturday06 stays the v1 backend." Log the finding so future research doesn't re-derive it.
- VRoid Studio CLI: **OSS-licensed, suitable** → keep #543 open with a follow-up implementation forward marker (AD-721i-3). Specify the swap point: `AvatarRendererAgent` already abstracts the backend boundary (`agents/utility/avatar_agents.py:30+`); the renderer impl is the swap unit.
- VRoid Studio CLI: **no headless mode** → close #543 as "not viable — Blender + saturday06 stays the v1 backend." Log.

---

## Section 1 — Research scope

The Builder must answer, with citations:

1. **Does VRoid Studio have a CLI / headless mode?** If yes, what's the invocation shape? (Common pattern: `vroidstudio.exe --import config.json --export-vrm output.vrm`.) If no, the option is dead.
2. **Is the CLI tool OSS, freeware, or paid?** Cite the license file in the official Pixiv/VRoid repo, or the EULA on https://vroid.com if no repo exists. If "freeware with non-commercial restriction" → treat as paid for ProbOS's purposes (commercial users absorb Apache 2.0 terms).
3. **Output VRMs license metadata.** What does the spec produce by default? Specifically: does a VRoid Studio export ship VRM1.0 `meta.licenseUrl` / `meta.commercialUssageName` (sic) populated, or are those operator-set? If operator-set, document the operator-friendly defaults.
4. **Deterministic parameter-driven output.** Can the CLI accept a parameter file (JSON / YAML) and produce a VRM **deterministically** (same input → same output bytes)? Determinism matters because ProbOS's `AvatarDSL` is the input contract. Non-deterministic backends complicate caching.
5. **Platform support.** Windows / macOS / Linux? VRoid Studio is Windows-first; if Linux/macOS aren't supported, this kills the OSS-cross-platform story.
6. **OS-level subprocess shape compatibility.** Does the CLI play with the BF-280 rule (no `asyncio.create_subprocess_exec` under SelectorEventLoop)? The answer is "yes if invoked via `subprocess.Popen` in a thread executor" — same pattern as `shell_command.py:154` `_run_sync`. Document.

For each: cite primary sources (official docs, official repo). If a source can't be found in 15 minutes of search, document the gap and treat the question as "unknown."

## Section 2 — Deliverable

**Single file:** `docs/research/vroid-cli-evaluation.md`. Suggested structure:

```markdown
# VRoid Studio CLI evaluation for AD-721i renderer backend

## Disposition (one-line verdict)

[ADOPT / REJECT / DEFER / UNKNOWN]

## Summary
- CLI mode available: yes/no
- License: [SPDX or "proprietary/paid/freeware-NC"]
- Output license metadata: [operator-set / hardcoded]
- Deterministic: yes/no/unknown
- Platforms: [Windows/macOS/Linux]
- Subprocess pattern compatible: yes/no

## Citations
[primary sources only]

## Recommendation
[2-3 sentences]

## If ADOPT — implementation outline
[paragraph: swap point at `AvatarRendererAgent.act()`; new `VroidRenderer`
mirrors `BlenderRenderer` interface; `cfg.avatars.renderer_backend:
'blender' | 'vroid'` selector; AD-721i-3 builds the renderer; AD-721i-4
ports tests]

## If REJECT — rationale
[paragraph: which constraint failed]
```

## Section 3 — Tracking

Update `docs/development/roadmap.md` Research section: append a one-line entry with the disposition. If REJECT, mark the line "(closed 2026-05-NN — see vroid-cli-evaluation.md)." If ADOPT, append a forward marker `AD-721i-3` line (`(forward)`) without filing a GitHub issue until Captain rules.

If REJECT or DEFER: **close #543** with a comment linking to `docs/research/vroid-cli-evaluation.md`.

If ADOPT: **leave #543 open** and update the title to `AD-721i-3: implement VRoid CLI renderer backend (parent AD-721i-2 evaluation ADOPT)`.

PROGRESS.md: append AD-721i-2 line noting "(research; no test delta)".

DECISIONS.md: one paragraph recording the disposition.

---

## Section 4 — License hygiene (must do regardless of disposition)

ProbOS OSS license policy (Apache 2.0): never absorb paid-license deps. If VRoid Studio CLI is freeware-with-NC-restriction, that's a paid license for ProbOS's purposes. Don't install it; don't ship instructions to install it as a default; document it as an *operator-elected* path **if** ADOPT.

If REJECT: confirm the existing Blender + saturday06 backend stays Apache 2.0 compatible. Blender is GPL-3.0 but we treat it as an OS-level subprocess (BYOL) per the existing `blender_renderer.py:3-10` comment block — that pattern is correct and stays.

---

## What This Does NOT Change

- Existing `BlenderRenderer` — untouched.
- `AvatarRendererAgent` — untouched. The "swap point" described in Section 1 is hypothetical and only lands in AD-721i-3 if Captain approves ADOPT.
- `cfg.avatars.blender_path`, `cfg.avatars.renderer_enabled` — untouched.
- AD-721h, AD-721g, AD-721d-3 — independent. No coupling.
- pip / npm dependencies — zero new.

## Acceptance Criteria

- Single new file `docs/research/vroid-cli-evaluation.md` with the structure above. Verdict and citations are mandatory; everything else is "best effort, document gaps."
- PROGRESS.md + DECISIONS.md + roadmap.md updated per Section 3.
- #543 closed (REJECT/DEFER) or retitled (ADOPT) per disposition.
- Zero code changes outside docs and the three trackers.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md` (mostly inapplicable here — but the "no new pip deps for OSS" rule is the load-bearing one).

---

## Verified Against Codebase (2026-05-17)

```
grep -n "class BlenderRenderer" src/probos/avatars/blender_renderer.py
  68: class BlenderRenderer:
  113:    async def render(self, dsl: "AvatarDSL", agent_id: str) -> Path:

grep -n "renderer_enabled" src/probos/config.py
  1175:    renderer_enabled: bool = False

grep -n "class AvatarRendererAgent" src/probos/agents/utility/avatar_agents.py
  29: class AvatarRendererAgent(BaseAgent):

grep -n "GPL-3.0\|BYOL" src/probos/avatars/blender_renderer.py
  3: Async-only. Blender is a GPL-3.0 program — we treat it as an OS-level
  4: subprocess (BYOL). Apache 2.0 boundary preserved: this module never

grep -n "_run_sync" src/probos/agents/shell_command.py
  154-157: (BF-280 reference pattern for SelectorEventLoop compatibility)
```
