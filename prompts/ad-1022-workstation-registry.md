# AD-1022 — Workstation-type registry + tiered (OSS baseline / commercial overlay) registration seam

**Epic #965 — HXI Workspaces & Workstations. Issue: TBD. Depends on: AD-1021 (Monaco workstation, drafted #966), AD-697/698 (overlay seam, shipped), AD-597 (MCP App Host, partial — verify at build).**
**Repo: OSS (`d:\ProbOS`) primary + a small commercial-overlay demo (`probos_enterprise`). AD ceiling: highest `### AD-` heading is AD-1019; AD-1020 reserved (pack-`mcpServers`-wiring, PROGRESS.md); AD-1021 = Monaco workstation (drafted, #966). This = AD-1022.**

The keystone that makes the **mode toggle visibly change the experience**: a backend **`WorkstationTypeRegistry`** where a workstation type can have an **OSS baseline** render **and** an **`is_commercial_loaded()`-gated commercial overlay** render. OSS registers baseline types (monaco / browser / chat); the commercial overlay (`probos_enterprise`) registers premium types/variants via the **existing AD-697 finalize-hook seam**. The HXI lists *available* workstation types from an API gated on the commercial flag — so flipping `scripts/probos-mode.ps1 oss ↔ overlay` (+ restart) changes what the Captain sees, with **zero commercial code in the OSS bundle**.

---

## Why / context
The OSS↔Commercial overlay infra is shipped and live (AD-697/698: entry-point discovery, finalize hooks, `is_commercial_loaded()`, `/api/system/extensions`, `CommercialOverlayBadge`, `probos-mode.ps1`). But the overlay is a **sentinel** — flipping modes flips a flag, nothing visible changes. AD-1022 makes the toggle *do* something: it defines the seam where a UI surface (a workstation type) has an OSS baseline and an optional commercial overlay, resolved by the flag. This is the generalized mechanism behind the Workspaces & Workstations unification (epic #965) and the Immersive App Experience (commercial overlay on the `browser` workstation).

## Pinned design decisions

### DD-1 — `WorkstationTypeRegistry` (OSS) + a frozen `WorkstationType` descriptor
New OSS `runtime.workstation_type_registry` (a plain in-memory registry, NOT SQLite — it is boot-built, like the tool registry). A `WorkstationType` descriptor: `{id, label, tier: "oss"|"commercial", render: WorkstationRender, min_provider: str = ""}`. `register(descriptor)` (last-wins per `(id, tier)`), `list_available(*, commercial_loaded: bool) -> list[WorkstationType]` where a type is available iff `tier == "oss"` **or** `commercial_loaded`. OSS registers the baseline types at startup (monaco/browser/chat — `tier="oss"`). Log-and-degrade; a duplicate/invalid registration never aborts boot.

### DD-2 — Tiered resolution: same `id`, OSS baseline + commercial overlay
A type id (e.g. `browser`) may be registered **twice**: an OSS baseline (`tier="oss"`) and a commercial overlay (`tier="commercial"`, by `probos_enterprise`). `resolve(id, *, commercial_loaded) -> WorkstationType` returns the **commercial** variant when `commercial_loaded` and one is registered, else the OSS baseline. This is the dual-experience switch: `browser` → embedded-browser baseline (OSS) vs immersive cockpit (commercial). The OSS baseline ALWAYS exists so OSS-only mode is fully functional.

### DD-3 — Render strategy keeps commercial UI OUT of the OSS bundle (`WorkstationRender`)
`WorkstationRender` is a tagged union: `{kind: "native", component_key}` (an OSS-shipped React component, keyed by string — monaco/browser/chat) **or** `{kind: "iframe", url, csp?}` (a sandboxed iframe to an overlay-served URL). **The OSS HXI never imports commercial React** — commercial workstations render via the iframe seam, reusing the **AD-597 MCP App Host sandboxed-iframe + JSON-RPC postMessage pattern**.
> ⚠️ **Verify AD-597 at build.** `_wire_mcp_app_host`, the `mcp_apps/` package, and `config.mcp_app_host` exist, but a DECISIONS verify-first note says the `McpAppFrame` React host "does not exist" in one context — its current build state is ambiguous. If a reusable sandboxed-iframe host component exists, reuse it; if not, v1 renders `kind:"iframe"` types via a minimal self-contained sandboxed `<iframe sandbox>` wrapper (no postMessage tool-proxying yet — that is a follow-on). Do NOT build the full MCP App Host here.

### DD-4 — API: extend the existing extensions surface, don't invent a parallel one
`GET /api/workstations/types` → `[{id, label, tier, available, render_kind}]` (availability computed from `is_commercial_loaded()`; **never** leak a commercial `url` to an OSS-mode client — only `render_kind`). Mirror the `/api/system/extensions` shape/handler (`routers/system.py`). The HXI reads this exactly like `CommercialOverlayBadge` reads `/api/system/extensions`.

### DD-5 — Commercial proof: `probos_enterprise` registers a demo premium type via the finalize hook
In the commercial repo, `probos_enterprise.register()`'s finalize hook calls `runtime.workstation_type_registry.register(...)` to add ONE demo commercial workstation type (e.g. `id="immersive-demo"`, `tier="commercial"`, `render={kind:"iframe", url:<overlay-served stub>}`) — proving the seam end-to-end: in OSS mode it is absent from `/api/workstations/types`; in overlay mode it appears. **This is the visible mode-change proof.** Real immersive cockpit registration is AD-C-022 commercial work, not here.

### DD-6 — Naming, layer discipline, default-OFF
- **Naming:** settle the overloaded term — the Experience-layer concept is **"Workstation"** (and the future container **"Workspace"**); the AD-997 disk concept stays **"execution work folder"**, reached only via the runtime API. Add a one-paragraph glossary to the registry module docstring.
- **Layer discipline:** the registry is Experience/runtime plumbing; it must NOT import `execution.workspace` or any commercial symbol.
- **Default-OFF:** a `WorkstationsConfig.enabled = False` flag. Off ⇒ the API returns `[]`/404 and the HXI surface is dormant ⇒ byte-identical. (The registry may still be constructed; it just isn't surfaced.)

## Build
1. **Registry + descriptors** — `src/probos/workstations/registry.py` (NEW): `WorkstationType`, `WorkstationRender`, `WorkstationTypeRegistry` (`register` / `resolve` / `list_available`). Frozen dataclasses; full type annotations.
2. **Baseline registration** — OSS registers monaco/browser/chat (`tier="oss"`, `kind="native"`) at startup (a `_wire_workstation_types` in `startup/finalize.py`, gated on `WorkstationsConfig.enabled`). Construct `runtime.workstation_type_registry`; stop/clear in `shutdown.py` if needed.
3. **API** — `GET /api/workstations/types` in `routers/system.py` (or a new `routers/workstations.py`), gated on enabled, availability from `is_commercial_loaded()`, never emits a commercial `url` to an unauthorized client.
4. **HXI surface** — a minimal `WorkstationLauncher` (or extend the AD-1021 Workspace overlay): fetch `/api/workstations/types`, list available types, open a `native` type via its OSS component (wire AD-1021 Monaco for `monaco`), render an `iframe` type via a sandboxed `<iframe>` (DD-3, honest-degrade if no host). HXI-compliant (stroke SVG, no emoji, deps-injectable, `data-testid`).
5. **Commercial demo (commercial overlay repo)** — `probos_enterprise` finalize hook registers the demo commercial type (DD-5). Separate commit in the private commercial overlay repo.

## Acceptance
- `WorkstationTypeRegistry`: `register`/`resolve`/`list_available` unit-tested incl. **tiered resolution** (same id: commercial wins iff `commercial_loaded`, else OSS baseline) and availability gating.
- `GET /api/workstations/types`: OSS-mode returns only `tier=="oss"` types; with a registered commercial type + `is_commercial_loaded()` true, the commercial type appears; **a commercial `url` is never serialized to an OSS-mode response** (asserted).
- **Mode-toggle proof (the headline):** with the `probos_enterprise` demo registered, `is_commercial_loaded()==False` ⇒ demo absent; `==True` ⇒ demo present. A test drives both via the AD-697 `reset_for_tests()` + a fake registration (real registry, BF-287 — no MagicMock at the overlay boundary).
- HXI `WorkstationLauncher`: lists available types from the API; opens a `native` type; renders an `iframe` type sandboxed (or honest-degrades). **Vitest** component test (mock fetch + the iframe/native children). `npm run build` clean.
- `WorkstationsConfig.enabled=False` ⇒ API dormant + surface hidden ⇒ byte-identical.
- Verify compliance with `.github/copilot-instructions.md` (layer discipline — no `execution`/commercial imports in OSS plumbing; HXI principles; type annotations; log-and-degrade).

## Do NOT build here
❌ The **rich Workspace container** (multi-pane layout, persistence, **AD-997 execution-folder backing-store binding**) → **AD-1023**. ❌ The **actual immersive cockpit** commercial render (it registers through THIS seam later, in the commercial repo / AD-C-022). ❌ The full **MCP App Host / `McpAppFrame`** + postMessage tool-proxying (AD-597) — only a minimal sandboxed `<iframe>` if needed. ❌ **Hosting AD-1021 Monaco inside a container** (wire it as a `native` type only; container integration is AD-1023). ❌ A new overlay-registration primitive — reuse the AD-697 finalize hook. ❌ A SQLite store (the registry is boot-built, in-memory). ❌ Any new top-level AD number — this is AD-1022. ❌ Commercial detail in the OSS repo (the demo type's real URL/feature lives commercial-side).

## Files (verify each at build)
- `src/probos/workstations/registry.py` (NEW) — registry + descriptors + glossary docstring.
- `src/probos/config.py` — `WorkstationsConfig(enabled=False)` + `SystemConfig` field.
- `src/probos/startup/finalize.py` — `_wire_workstation_types` (baseline registration, gated); `shutdown.py` teardown if needed.
- `routers/system.py` (or NEW `routers/workstations.py`) — `GET /api/workstations/types` (mirror `/api/system/extensions`).
- `ui/src/components/workstation/WorkstationLauncher.tsx` (NEW, or extend AD-1021's panel) — list + open; `ui/src/store/useStore.ts` flag if needed.
- `tests/test_ad1022_workstation_registry.py` (NEW) — registry + tiered resolution + API gating + mode-toggle proof (real registry + AD-697 reset).
- `ui/src/components/workstation/__tests__/WorkstationLauncher.test.tsx` (NEW) — Vitest.
- **(commercial repo)** `src/probos_enterprise/__init__.py` — finalize hook registers the demo commercial type (separate commit).

## Done-when
All acceptance green; `-k "workstation or ad1022 or ad697"` (OSS) + `cd ui && npx vitest run src/components/workstation` green; default-OFF byte-identical; **the mode-toggle proof passes**; no commercial/`execution` imports in OSS plumbing; **verify compliance with `.github/copilot-instructions.md`.**

---

## Pre-dispatch checklist (Architect self-audit)
**Numbering & boundary**
- [x] Highest heading AD-1019; AD-1020 reserved; AD-1021 = Monaco (#966); this = **AD-1022** (next free).
- [x] OSS plumbing (registry/API/baseline) in OSS; the commercial demo registration in `probos_enterprise`. No commercial detail leaks into OSS.

**Verify-first (spec vs reality)**
- [x] Overlay seam live: `register_finalize_hook`/`is_commercial_loaded`/`reset_for_tests` (overlay.py); `/api/system/extensions` (system.py:82) + `CommercialOverlayBadge` consume it; `probos-mode.ps1` toggles `PROBOS_DISABLE_OVERLAY`. Verified this session.
- [x] AD-597 MCP App Host: `_wire_mcp_app_host`/`mcp_apps/`/`config.mcp_app_host` exist BUT `McpAppFrame` build state is ambiguous (DECISIONS verify-first note) → spec says **verify at build**, minimal `<iframe>` fallback, do not build the host.
- [x] AD-1021 Monaco is the `monaco` native type (drafted, #966) — wired as a native type, not hosted-in-container here.

**Completeness (spec vs itself)**
- [x] Every build item maps to ≥1 acceptance criterion; the headline (mode-toggle proof) has a dedicated test using a real registry (BF-287).
- [x] No SQLite (boot-built registry) ⇒ real-DB rule N/A; Vitest required for the UI surface.
- [x] Default-OFF flag + byte-identical assertion.
- [x] Security: commercial `url` never serialized to an OSS-mode client (explicit acceptance criterion).

**Discipline**
- [x] "Do NOT build" names the specific deferrals (AD-1023 container/AD-997 binding, immersive cockpit, full MCP App Host, Monaco-in-container) + the IDE/over-scope traps.
- [x] Layer discipline called out (no `execution`/commercial imports in OSS plumbing).
- [x] Compliance line in Acceptance + Done-when.
- [ ] **(Open for build)** Confirm `routers/system.py` vs a new `routers/workstations.py` — Builder picks based on file size/cohesion; either satisfies the API criterion.
