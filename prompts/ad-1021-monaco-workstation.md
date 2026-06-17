# AD-1021 — Monaco code/text Workstation tier in the HXI (human-oversight surface for the autonomous build loop)

**Epic #965 — HXI Workspaces & Workstations. Issue #966. Depends on: nothing (UI-first over existing store state).**
**Repo: OSS (`d:\ProbOS`). AD ceiling at drafting: highest `### AD-` heading is AD-1019 (sub-letters a–e); AD-1020 is reserved by forward-reference for pack-`mcpServers`-wiring (PROGRESS.md AD-1015 note). This AD = AD-1021.**

A HXI **Workstation** (HXI Principle #11, middle tier: *app embedded in the HXI, agents assist*) that gives the Captain a real editing surface to **view and collaborate on what the crew is producing** — primarily the **proposed file changes** from the autonomous Architect→Builder loop — plus a **general-purpose text editor** usable beyond code. This is **not an IDE**: no LSP, no extensions, no file tree, no git ops. It is the **human-oversight surface** for the build loop and a robust scratch editor. v1 is **UI-only over existing store state** (mirrors AD-1018 / AD-1001b "UI, no backend" slices).

---

## Why / context
The autonomous build loop (Northstar I: Architect → SoftwareEngineer/BuildPipeline → test-fix → commit, AD-302–320 + AD-372/375) already produces `BuildProposal.file_changes` (path/content/mode) and queues them for the Captain's merge approval. Today the only review surface is the inline IntentSurface proposal card + `llm_output` text — there is **no real editor** to read the generated code with syntax highlighting, scroll a large change, or see a create-vs-modify diff. The HXI also has **no general text-editing surface** (`ArtifactViewer` is read-only by mime; it explicitly names Monaco a *forward marker* — `ui/src/components/artifacts/ArtifactViewer.tsx:12`). AD-1021 lands that forward marker as a **Workstation tier**, framed per HXI #11: agents observe/assist, the UX nudges toward the agentic path (the editor is where you *review and steer* the crew, not where you primarily type).

**Strategic boundary (do not drift into an IDE):** Cursor optimizes *human-codes-faster*; ProbOS optimizes *human-delegates-and-oversees*. This Workstation is the oversight/collaboration surface, NOT a coding IDE. Keep it a viewer+editor of agent output and scratch text.

**Forward-compat (epic #965 — Workspaces & Workstations):** this is *workstation type #1*. A future **Workspace container (AD-1022)** will host multiple workstations (Monaco, shared browser, chat/MCP) bound to a backing store (initially the AD-997 execution folder, reached via the runtime API). Therefore keep `MonacoSurface` a **standalone, embeddable component** — the overlay (`WorkstationPanel`) is merely *one* host; do NOT couple the editor to the global modal, so the container can host it later without rework. Do NOT build the Workspace container here.

## Pinned design decisions

### DD-1 — Monaco, lazy-loaded, MIT; one Workstation overlay mirroring the AD-1018 panel
Embed `@monaco-editor/react` (wraps `monaco-editor`; both **MIT** — clean per OSS license hygiene). New `WorkstationPanel.tsx` is a fixed full-screen overlay following the **exact** AD-1018/AD-1001b pattern: a `workstationOpen: boolean` store flag (default `false`), mounted **unconditionally** in `App.tsx`, Escape/X close, deps-injectable (`_fn = deps?.x ?? realX`), HXI-compliant (amber `#f0b060` / dim `#666680`, **inline stroke SVG icons, NO emoji**, `data-testid` on every interactive element), honest-degrade.
> ⚠️ **Monaco is ~heavy (multi-MB).** It MUST be **code-split / dynamically imported** (`React.lazy` + `Suspense`, or `@monaco-editor/react`'s built-in loader) so it never enters the main HXI bundle. A `vite` chunk-split (or dynamic `import()`) is a hard requirement — assert the main bundle does not grow materially. Configure the Monaco worker/loader for the Vite build (CDN loader or `vite-plugin-monaco-editor`); pin the version.

### DD-2 — Three content sources (the "beyond code" requirement is first-class)
The Workstation opens onto one of three `WorkstationDoc` sources, so it is genuinely a general editor, not a code-only panel:
1. **Build-review** — a `BuildProposal.file_changes[i]` (already in the store via the build-proposal chat-message meta): `{path, content, mode, after_line}`. Language inferred from the path extension. This is the **human-oversight moment**: read the crew's proposed change before approving the merge.
2. **Scratch / text** — an empty or arbitrary in-memory buffer (the general-purpose editor: notes, drafts, config, prose). Language defaults to `plaintext`/`markdown`, switchable.
3. **Artifact** — an existing artifact via the AD-797 `fetchArtifactContent(id)` path (reuse, do not re-implement), so the Workstation can edit a saved artifact, not just view it.

### DD-3 — View + local edit + Copy/Save/Download; NO write-through in v1 (the safety + non-IDE line)
The editor is **editable** (it's a real editor), but v1 **does not apply edits back** to the worktree, the build branch, or the artifact store. Output actions mirror `ArtifactViewer`: **Copy** (clipboard), **Download** (Blob → `<a download>`), and **Save-to-artifact** for scratch/edited buffers (reuse the artifact save path if present; else Download only). **Writing a human edit back into a crew build/worktree is a consensus-relevant action and a separate slice (AD-1021b)** — keeping it out of v1 preserves the governance model and the "not an IDE" boundary.

### DD-4 — Diff for `mode: 'modify'` only when the original is in hand
For `mode: 'create'` → Monaco `Editor` (read of new content). For `mode: 'modify'` → Monaco `DiffEditor` (original ↔ proposed) **iff** the original content is available in the store/proposal; otherwise fall back to a plain `Editor` on the new content with a **"modify"** badge + the `after_line` anchor shown. A true side-by-side diff against the live repo file needs a read endpoint → **deferred to AD-1021b** (named below). Do not add a backend in v1.

### DD-5 — Entry points (launch the Workstation from where the work is)
(a) An **"Open in Workstation"** action on a build-proposal chat card (`ChatMessage.buildProposal`) → opens build-review on the selected `file_changes` entry. (b) **Bridge → Engineering station** launch ("Workstation", mirrors the McpServers/Ship's-Locker launch + command-palette entry) → opens a **scratch** doc. (c) Command-palette entry. Multiple `file_changes` in one proposal → a simple left rail list of changed paths (NOT a file-tree/project-explorer — just the paths in THIS proposal).

## Build
1. **Store**: add `workstationOpen: boolean` (default `false`) + `workstationDoc: WorkstationDoc | null` and actions `openWorkstation(doc)` / `closeWorkstation()` to `ui/src/store/useStore.ts`, mirroring `mcpServersOpen` (`:370`, `:886`). Define `WorkstationDoc` (`{kind:'build'|'scratch'|'artifact', title, language, content, mode?, afterLine?, originalContent?, path?, artifactId?}`) in `ui/src/store/types.ts`.
2. **Panel**: new `ui/src/components/workstation/WorkstationPanel.tsx` — the overlay (DD-1), lazy-mounting `MonacoEditor`/`MonacoDiff` child components (DD-1 code-split). Toolbar: title, language selector (scratch), Copy / Download / Save-to-artifact, create/modify badge, left rail of paths for multi-change build docs. Honest-degrade: Monaco load failure → a `<pre>`-fallback read view + a notice (never a blank panel).
3. **Monaco wrapper**: `ui/src/components/workstation/MonacoSurface.tsx` — thin wrapper around `@monaco-editor/react` `Editor` + `DiffEditor`, dynamically imported, HXI dark theme tokens, `data-testid`. Keep ALL `monaco-editor` imports inside this lazily-loaded module so nothing leaks into the main chunk.
4. **Entry points** (DD-5): "Open in Workstation" on the build-proposal card; Engineering-station launch + palette entry (mirror `McpServersPanel` launch wiring in the Bridge panel + `paletteCommands`).
5. **Vite**: configure the Monaco loader/worker + a dedicated chunk; pin the dep version; assert the main bundle is not materially larger (DD-1).

## Acceptance
- `WorkstationPanel` renders for each `WorkstationDoc.kind` (build / scratch / artifact); Escape and X close it; deps-injectable; **no emoji** (asserted in a test, per HXI #3); `data-testid` on every control.
- Build-review: given a `BuildProposal.file_changes` entry, the editor shows its content with language inferred from the path; `mode:'modify'` with an `originalContent` renders the **DiffEditor**; without one, the plain editor + "modify" badge.
- Scratch: opens an empty editable buffer; language switch works; Copy / Download work; Save-to-artifact works if the artifact-save path exists (else Download-only, honest-degrade).
- Monaco is **dynamically imported** — a test asserts `MonacoSurface` is lazy (no static `monaco-editor` import in the panel module) and the panel renders a `Suspense` fallback before load; Monaco-load-failure renders the `<pre>` fallback, not a blank panel.
- Entry points: the build-proposal card "Open in Workstation" dispatches `openWorkstation` with the right doc; the Engineering-station launch opens a scratch doc; palette entry present.
- **Vitest component tests** (`cd ui && npx vitest run`) for the panel + entry wiring + the lazy/fallback path (mock the Monaco child so tests don't load the real editor). `npm run build` clean; **main-bundle size not materially increased** (Monaco in its own chunk).
- UI-only ⇒ no backend change; existing build/artifact flows byte-identical. Verify compliance with `.github/copilot-instructions.md` (HXI design principles, deps-injectable, no emoji, Vitest requirement).

## Do NOT build here
❌ **Write-through** of human edits to the worktree / build branch / artifact (consensus-relevant → **AD-1021b**). ❌ **True repo-file diff** against the live file (needs a read endpoint → **AD-1021b**). ❌ **Agent co-editing / presence / multiplayer** (→ AD-1021c). ❌ The **Workspace container / multi-workstation host** (epic #965, AD-1022) — this AD ships the standalone Monaco workstation only. ❌ **LSP / IntelliSense / autocomplete / extensions** — that is the IDE trap; explicitly excluded. ❌ **File tree / project explorer / multi-tab / open-arbitrary-file** — only the paths in the current proposal. ❌ **Git operations** in the Workstation. ❌ A backend endpoint of any kind in v1. ❌ A new top-level AD number — this is AD-1021. ❌ Changing `ArtifactViewer` behavior (the Workstation is additive; ArtifactViewer stays the read-only mime viewer).

## Files (verify each at build)
- `ui/src/store/types.ts` — add `WorkstationDoc`.
- `ui/src/store/useStore.ts` — add `workstationOpen` + `workstationDoc` + `openWorkstation`/`closeWorkstation` (mirror `mcpServersOpen` at `:370`/`:886` and its setter).
- `ui/src/components/workstation/WorkstationPanel.tsx` (NEW) — the overlay (mirror `components/mcp/McpServersPanel.tsx`).
- `ui/src/components/workstation/MonacoSurface.tsx` (NEW) — lazy Monaco `Editor`/`DiffEditor` wrapper (the ONLY module importing `monaco-editor`).
- `ui/src/App.tsx` — mount `<WorkstationPanel />` unconditionally (beside `<McpServersPanel />` at `:115`).
- Bridge/Engineering launch + `paletteCommands` — add the "Workstation" launch (mirror the McpServers entry).
- the build-proposal card component — add the "Open in Workstation" action.
- `ui/vite.config.*` + `ui/package.json` — add `@monaco-editor/react` (MIT), Monaco chunk-split / worker config, pinned version.
- `ui/src/components/workstation/__tests__/WorkstationPanel.test.tsx` (NEW) — Vitest (mock `MonacoSurface`).

## Done-when
All acceptance green; `cd ui && npx vitest run src/components/workstation` green + touched-suite regression unchanged; `npm run build` clean with Monaco in its own chunk (main bundle not materially larger); HXI-compliant (no emoji asserted, stroke SVG, deps-injectable, `data-testid`); **verify compliance with `.github/copilot-instructions.md`.**

---

## Pre-dispatch checklist (Architect self-audit)
**Numbering & boundary**
- [x] Highest `### AD-` heading = AD-1019; AD-1020 reserved (forward-ref, pack-mcpServers-wiring); this AD = **AD-1021** (next free, collision-avoided).
- [x] Correct repo: OSS (describes how the product *works* — a HXI surface). No commercial leak.

**Verify-first (spec vs reality)**
- [x] Overlay pattern confirmed live: `mcpServersOpen` (`useStore.ts:370`,`:886`), unconditional mount (`App.tsx:115`), Escape/X + deps-injectable + no-emoji (`McpServersPanel.tsx`).
- [x] Monaco confirmed as the named forward marker (`ArtifactViewer.tsx:12`); `fetchArtifactContent` reuse path confirmed (AD-797).
- [x] Build output shape confirmed in the store: `BuildProposal.file_changes{path,content,mode,after_line}`, `BuildQueueItem.worktree_path`, `ArchitectProposalView` (`store/types.ts`).
- [x] `@monaco-editor/react` + `monaco-editor` license = MIT (clean).

**Completeness (spec vs itself)**
- [x] Every build item maps to ≥1 acceptance criterion.
- [x] Vitest component test required (HXI UI rule); lazy/fallback path explicitly tested.
- [x] No new store needed (UI-only); no SQLite, so no real-DB test rule applies.
- [x] Default-OFF posture = the overlay is closed by default + additive; existing flows byte-identical (the byte-identical assertion is in Acceptance).
- [x] The one real risk (Monaco bundle weight) is flagged with a concrete mitigation (code-split + main-bundle-size assertion).

**Discipline**
- [x] "Do NOT build" names specific adjacent features (write-through, repo-diff, co-editing, LSP, file-tree, git) and the IDE trap by name.
- [x] Layer/boundary: UI-only, additive; ArtifactViewer untouched.
- [x] Compliance line present in Acceptance + Done-when.
- [ ] **(Open for the build)** Confirm whether a Save-to-artifact frontend path already exists; if not, v1 degrades to Download-only (already specified) — Builder verifies before wiring Save.
