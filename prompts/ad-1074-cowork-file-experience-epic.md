# Epic AD-1074 — Unified "Cowork-style" file & embedded-app collaboration experience

**Issue:** seangalliher/ProbOS#1010 · **Author:** Architect (Captain-directed) · **Type:** Design epic (decompose before building)

**Current highest referenced top-level AD: AD-1073.** This epic claims **AD-1074** and decomposes into sub-ADs below.

---

## Captain's directive

> Default to a **Cowork-like experience** as the **single standard experience** for collaborating with files (and embedded apps) with crew agents in ProbOS — one experience, not a Chat-vs-Cowork split.

### Landscape (what the field does today)

| Product | When a doc is produced | Output folder | Embedded split-view |
|---|---|---|---|
| **MS Copilot (Chat)** | link → open in web Word | — | — |
| **Copilot Cowork** | link | ✅ saves to an Output folder | ✅ can open a split side-pane with the doc |
| **Claude Chat** | link | — | ✅ opens the doc in a split embedded view |
| **Claude Cowork** | Cowork-like (link + folder + view) | ✅ | ✅ (dedicated desktop app) |

Anthropic and Microsoft both **started with Chat, then bolted on Cowork → two experiences** (MS now ships a **slider** to switch modes; Claude needs a **dedicated Windows app** for Cowork). The Captain uses Cowork the majority of the time.

## Decision

**ProbOS converges on ONE Cowork-first experience.** The competitive insight: ProbOS never shipped a separate "Cowork mode," so it can be **Cowork-native** without the retrofit duality (no slider, no second app). The crew-agent chat *is* the collaboration surface; files and embedded apps live in a persistent workspace beside it.

## The standard experience — three layers (all on by default)

1. **Inline artifact card / link** — *exists.* AD-797 `ArtifactStore` + the AD-1066 produced-file capture render every produced file as a downloadable card in the thread.
2. **Output workspace ("folder")** — *partially exists.* The thread's artifacts (AD-797, per `thread_id`) + the group-chat workspace + `CodeRunnerAgent` persistent workspaces. **Gap:** surface them as an always-available **"Output / Workspace" side panel** that lists the thread's files (the Cowork "Output" panel).
3. **Split-view embedded viewer** — *being built.* The AD-1022 workstation-type registry is the OSS seam; opening a file/app opens a split-pane embedded **workstation** in the HXI. **Gap:** an OSS **baseline document viewer** (open a `.docx`/`.pdf`/`.xlsx` in a side pane) + making split-view the *default* presentation for a produced doc, not just click-to-open.

**Standard flow:** a crew agent produces or edits a file → it lands in the thread's **Output workspace** → shows an **inline card** → **auto-opens in the split-view embedded viewer**, where agent + Captain collaborate on it.

## Architect take (opinionated)

- **The instinct is right and the timing is good.** ProbOS is greenfield here — it carries none of the Chat/Cowork baggage MS and Anthropic are now reconciling. Make the workspace+split-view the *default*, not a mode.
- **This is mostly UNIFICATION, not net-new infra.** ProbOS already has layers 1 + 2 and is building layer 3. The work is: a persistent Output panel, an OSS baseline doc viewer, and an "auto-open produced doc in split view" default.
- **The hard design decision is the OSS baseline renderer.** A binary `.docx`/`.pdf` needs a viewer. Options: (a) **local web viewer** — `mammoth` (docx→HTML) + `pdf.js` + a sheet renderer (free, offline, OSS-clean); (b) Office-web embed (needs M365 — not OSS/free, rejected for baseline); (c) the AD-1052a WATCH stream (the commercial immersive path). **Recommendation: (a) for the OSS baseline** — free, offline, license-clean; the commercial overlay enhances the render.
- **Keep editing agentic-first (HXI principle #11).** The split-view is a *workstation* the agent can observe/assist in; nudge toward "ask the agent to change it" over manual edits. Three tiers (Agentic / Workstation / Airlock) already encode this.

## OSS ↔ Commercial boundary (HARD)

- **OSS baseline (this epic):** the Output workspace panel + inline card + a **free local embedded viewer** (mammoth/pdf.js) + auto-open-in-split-view. This is "how the product works" → OSS. Built on the AD-1022 workstation seam.
- **Commercial enhancement (extension point only here):** the **premium immersive render** of the document workstation (the commercial `AD-C-029` Document Workstation via the AD-1052a WATCH stream; `AD-C-022` immersive cockpit). The OSS epic exposes the workstation seam; pricing/immersive-render details live in the private commercial repo. *(Commercial)*

## Proposed decomposition (sub-ADs — to be drafted)

- **AD-1074a — Output workspace panel.** A persistent "Output / Workspace" side panel in the HXI listing the active thread's artifacts/files (open / download / version history). Reuses AD-797 thread artifacts + the AD-1066 capture.
- **AD-1074b — OSS baseline embedded doc viewer.** Render `.docx` (mammoth→HTML), `.pdf` (pdf.js), `.xlsx`/`.csv` (table) in a split-pane workstation via the AD-1022 registry. License-clean local libs only.
- **AD-1074c — Auto-open produced docs in split view.** When a crew agent produces/edits a file in chat, open it in the split-view viewer by default (Cowork behavior), not just on click. Respect HXI progressive disclosure (calm default, expand on engagement).
- **AD-1074d — Round-trip edit/collaborate.** Agent edits an existing workspace file (read → modify → re-version via `run_python` / a skill) so "change the heading to bold" updates the same doc in the split view.
- **AD-1074e *(Commercial)*** — premium immersive render of the document workstation (extension point; details in the commercial repo).

## Prerequisite for the build

AD-1066 (code-exec → artifacts) is shipped, so layer 1 is live. AD-1022 (workstation registry) is the layer-3 seam. AD-1073 (loop dependency install) is independent but complementary (lets the agent acquire a renderer/generator lib on demand). Decompose AD-1074a–d into build prompts before implementation.

## Acceptance (epic-level)

A crew agent makes a Word doc in a 1:1 chat → it appears in the thread **Output panel**, shows an **inline card**, and **opens in a split-view embedded viewer** — one experience, default-on, OSS baseline (free local render), with the commercial overlay enhancing the render. Each sub-AD ships default-OFF / behavior-preserving with its own tests; verify Engineering Principles compliance.
