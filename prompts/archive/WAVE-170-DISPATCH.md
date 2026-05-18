# Wave 170 — Dispatch

**Slate:** Settings/Control Panel HXI shell + Camera streaming v1
**Status:** GATE 1 (Architect review) — APPROVED for Builder
**Highest AD before wave:** AD-740 (shipped Wave 169)
**New AD numbers assigned:** AD-741 (Settings shell), AD-733 (camera v1 — pre-existing umbrella per #641)
**Budget:** ~10–12h (Captain authorized oversized wave)

## Prompts

| Order | Prompt | Closes | Est tests | Est hours |
|---|---|---|---|---|
| 1 | [ad-741-settings-control-panel.md](ad-741-settings-control-panel.md) | (new AD) | +17 pytest +9 vitest | 6–7h |
| 2 | [ad-733-camera-streaming-v1.md](ad-733-camera-streaming-v1.md) | #641 | +12 pytest +5 vitest | 4–5h |

**Dispatch order:** AD-741 first, AD-733 second. AD-733 depends on the `section_registry` AD-741 creates and inserts a `perception` section descriptor into it.

## Captain Mockup — Settings.html (reference; v1 scope refined)

Captured from the live Claude Artifact DOM (2026-05-17). v1 follows the mockup's **shape** (top bar, sidebar groups, draft buffer, APPLY ↵, status bar) but refines the **scope** per Captain's 2026-05-17 revision direction: drop the 24 stub entries (most map to internal subsystems with no operator-actionable knobs), ship 11 wired sections across 4 domains instead, add a bottom-of-sidebar `Advanced configuration → Open YAML editor` affordance for the long tail.

**Top bar (left → right):**
- View tabs: `WARD ROOM` | `CREW` | `SETTINGS` (current view highlighted)
- Search box: `⌕ Search settings…`
- Buttons: `VIEW YAML` | `DISCARD` (disabled until draft) | `APPLY ↵` (disabled until draft) | `BRIDGE`

**Left sidebar:** `⌘ CONTROL PANEL` header + subtitle `11 sections · 4 domains` (dynamic from registry).

Four domains, frequency-of-use order:
- **Core** — `◇ System`, `✺ LLM Tiers`, `◈ Memory`
- **Perception & Voice** — `▣ Perception` (added by AD-733), `≈ Voice`
- **Identity & Presentation** — `✿ Avatars`, `◊ Ward Room`
- **Connectivity** — `⊞ Federation`, `≣ Channels`, `↑ Cloud Pickers`, `⚒ Tools`

Bottom-of-sidebar: **Advanced configuration — Edit system.yaml directly** → opens VIEW YAML modal (read-only in v1; raw edit = forward marker AD-741-6). Top-of-sidebar one-line note: per-agent settings live in Crew Roster.

Status markers next to section name: `●` = active/live, `OFF` = disabled. Symbols are stroke SVG glyphs (HXI Design Principle #3 — no emoji).

**Main panel (System section example):**
- Header: section glyph + heading + machine tag `[system]`
- Setting rows: human label + `<code>field_name</code>` + control
  - `Process name / name` — textbox `ProbOS`
  - `Version / version` — readonly readout `0.4.0`
  - `Log level / log_level` — enum buttons: `TRACE DEBUG INFO WARN ERROR FATAL`
- Secret-named fields render as a read-only `Configured / Not configured` chip per AD-741's §"Secret-field rule" (e.g. `Cloud Pickers → Google Drive client_secret`).

**Right rail:** context card echoing selected section glyph + name + description.

**Bottom status bar:** `● ProbOS v0.4.0 · config system.yaml · in sync · T+20:21:46` + buttons `↻` (reload) `⇩` (export) `⏻` (power).

**Architectural read:** Settings IS `system.yaml` surfaced as a form with a drafted-change buffer that requires explicit `APPLY ↵`. The registry-driven sidebar (HXI Design Principle #8 — generative, not designed) starts at 11 entries and grows as future ADs add real operator-actionable surfaces; the long tail stays in raw YAML.

## Architect-surfaced considerations (beyond mockup + issue)

1. **No `/api/config` endpoint exists today** — verified `grep -r "api/config" src/probos/routers/` returns 0 hits. AD-741 ships both the API and the UI.
2. **Hot-reload posture in v1 = uniformly restart-required.** Most config fields can't be safely hot-changed (LLM tier base_url is the canonical example — requires re-init of the HTTP client). Mixing hot-reload and restart-required in v1 produces confusing partial-apply UX. v1 treats every field as restart-required and shows an explicit "ProbOS restart required" banner after APPLY. AD-741-1 wires per-field hot-reload later.
3. **YAML round-trip loses comments + ordering.** Pydantic `model_dump` → `yaml.safe_dump` is the cheapest path; v1 accepts the loss and stamps an `# Edited via HXI` header. Operators are warned via the VIEW YAML modal footer.
4. **CSRF.** No app-wide middleware exists. AD-741 ships an endpoint-scoped single-consume token (matches AD-720c pattern). Forward marker AD-741-5 if broader middleware lands.
4a. **Secret-field rule (new standard).** Any Pydantic field whose terminal name matches `(?i)(secret|token|password|api_key|private_key)` is auto-redacted: `GET /api/config` returns `None` with a separate `secret_present` boolean map; YAML render replaces with `"<redacted>"`; POST that targets a secret path returns 400 `secret_field_readonly`. Secrets are mutated only by direct `system.yaml` edits or the AD-706f vault for OAuth credentials. Forward marker AD-741-6 wires raw YAML editing into the HXI.
5. **The 11 sidebar entries are real surfaces, not vaporware.** v1 ships only operator-actionable knobs verified to exist in HEAD. The 24 "stub" entries from the original mockup (Mesh, Consensus, Self-Mod, NATS Bus, Circuit Breaker, etc.) are internal subsystems with no Captain-tunable knobs — they belong in `system.yaml` raw editing (forward marker AD-741-6), not as greyed sidebar placeholders. Captain spec 2026-05-17 revision applied.
6. **No stubs in v1 — long tail goes to YAML.** Bottom-of-sidebar `Advanced configuration → Open YAML editor` affordance opens the existing VIEW YAML modal (read-only in v1). Raw YAML editing with Pydantic validation on save = AD-741-6.
7. **Settings panel is an overlay panel, not a tab system.** Verified `App.tsx` uses Zustand `openX` flags for every panel (WardRoom, Crew, Notebooks, Records, Explorer, Metrics). Settings is just one more overlay. The mockup's `WARD ROOM | CREW | SETTINGS` view tabs translate to the existing NavButton row (NavButton hides itself when its own panel is active — perfect match).
8. **`vision_observation` intent has no consumer in v1 — that's intentional.** It validates the wire shape (frame → AttachmentStore SHA → bus broadcast with ref only) without committing to an inference cadence. AD-733a is the LLM consumer; AD-733b is the ObserverAgent.
9. **AD-731 invariant rigorously enforced** in the camera path. Source-scan test asserts no `b64encode` / `base64.b64` / `"blob_b64"` in `routers/perception.py`. This is the eighth-guard catalog applied to camera.
10. **Privacy story is the design.** Persistent top-bar `CAMERA LIVE` indicator (visible from every HXI view), explicit `getUserMedia` consent gate (browser-native), instant REVOKE, `beforeunload` track-release. Default-OFF on both `PerceptionConfig.enabled` AND `PerceptionConfig.camera.enabled` (two switches).
11. **HTTPS for `getUserMedia`** — localhost is exempt by browser spec; production deployment behind a public hostname needs HTTPS. Documented in the section description and surfaced as a banner.
12. **Server-side fps cap** (4 fps) prevents client-side DOS even if the operator forgets the client cap. Token-bucket per session.
13. **First-frame anchored episode** (AD-541b lineage) — defends against future confabulation: "I saw something before the camera was on" → episode anchor proves the start point.
14. **Frame retention** — AttachmentStore has no auto-GC for camera frames in v1. AD-733-1 forward marker filed for retention reaper.
15. **Browser memory** — frames are sent immediately, blob freed on GC; no client-side ring buffer needed in v1.

## Pre-flight gates (run before dispatching AD-741)

```powershell
# 1. Working-tree integrity
git status --short
git diff --numstat | Sort-Object {[int]($_.Split("`t")[1])} -Descending | Select-Object -First 5
# Expect: clean tree (or only prompts/wave-plan.yaml, prompts/wave-orchestrator-state.json staged).

# 2. Baseline gate (no surprises before wave)
& d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile
# Expect: 13951 ± known flakes. Record the exact number — wave deltas anchor here.

cd ui; npx vitest run; cd ..
# Expect: 633 passing. Record.

cd ui; npm run build; cd ..
# Expect: green dist build. (BF-279 / AD-738b standing rule.)
```

If any gate fails: STOP, classify (real regression vs environmental vs order-dependent per Hard-Stop Triage Rules), file a BF entry if needed, do NOT proceed to AD-741.

## Per-prompt quality gates

After each AD's commit:

```powershell
# Focused per-prompt gate
& d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad741_*.py -v -n 0
# (or test_ad733_*.py for the second AD)

# Full gate after each AD
& d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile
# Expected delta: +17 (AD-741), then +12 (AD-733).

# UI gates — REQUIRED per BF-279 / AD-738b
cd ui; npx vitest run; cd ..
cd ui; npm run build; cd ..
```

## Hard-stop conditions

1. **Phantom API in implementation.** If during build the Builder finds `runtime.config_path` does NOT exist on `ProbOSRuntime`, STOP and surface — AD-741 needs that attribute. Architect provides one-line fix: add `self.config_path: str | None = None` set during `_load_config` in `__main__.py`.
2. **`get_runtime` import path.** If `from probos.routers._common import get_runtime` fails, grep for the canonical name and use it; do NOT invent a new module.
3. **`_validate_and_store_attachment` return shape.** If `result["attachment_id"]` is wrong key name, find the canonical key — do NOT add a wrapper.
4. **`runtime.intent_bus.broadcast` signature.** If broadcast is sync or has a different name, adjust call site; do NOT change the bus contract.
5. **`runtime.episodic_memory.store` signature.** If method is named `add` / `add_episode` / kwargs differ, adapt call site; do NOT add a wrapper. The anchor write is Tier-2 (already wrapped in try/except).
6. **AD-741 ↔ AD-733 ordering.** AD-733 expects the `section_registry.py` from AD-741. If AD-741 lands cleanly, AD-733's insertion of the `perception` SectionDescriptor is a single grep-replace. If AD-741 hits a hard-stop, defer AD-733 to a later wave.
7. **MagicMock at config / fixture boundary** — BF-287. Every new test MUST use real `SystemConfig()`, real `PerceptionConfig()`, real `FilesystemAttachmentStore(tmp_path)`. No `MagicMock(spec=SystemConfig)`. Wave gate sentinel: `grep -n "MagicMock" tests/test_ad741_*.py tests/test_ad733_*.py` should return only assertions that the production code does NOT import MagicMock.
8. **`multi_replace_string_in_file` with adjacent blocks** — BF-274. AD-741 has long SECTIONS tuple edits; AD-733 inserts a SectionDescriptor into that tuple. Prefer single `replace_string_in_file` calls. If using `multi_replace_string_in_file`, verify file content after every call.
9. **`asyncio.create_subprocess_*`** — BF-280. Neither AD spawns subprocesses, but if the Builder reaches for one (e.g. for image processing), STOP — must use `subprocess.Popen + loop.run_in_executor` per the `shell_command.py:_run_sync` pattern.
10. **UI emoji** — HXI Principle #3. Grep new UI files for emoji codepoints; if found, replace with inline stroke SVG before commit.

## Slate summary

Wave 170 ships the operator-facing control plane for ProbOS — first a 28-section settings panel with a real APPLY-flow round-trip on 4 + 1 wired sections (plus 23 honest stubs that won't make the UI look broken), then a privacy-first camera streaming pipeline that proves the `vision_observation` wire shape without committing to an LLM consumer. The two ADs are tightly coupled by design: AD-741's section registry is the integration seam for AD-733's Perception section. Both ADs are zero-new-deps, license-clean, AD-731-compliant, and BF-287-conformant. The eight-guard catalog and the full BF lineage from Wave 153 onward are encoded as standing rules in the prompts. Estimated +26 pytest, +14 vitest, ~10–11h Builder time.

## GATE 1 verdict

**✅ APPROVED**

Both prompts pass:
- Verify-first discipline (every API / file path / signature grepped against HEAD).
- License posture (zero deps, browser-native + stdlib + already-resident packages).
- AD-731 invariant (refs only on the bus; source-scan test in AD-733).
- BF-274 (single-replace mandate documented).
- BF-279 / AD-738b (UI build gate in acceptance criteria).
- BF-280 (no async subprocess in either AD).
- BF-282 (no binary stdout — N/A; no subprocesses).
- BF-286 / BF-287 (real fixtures throughout; no MagicMock at substrate boundary).
- HXI Design Principles 1–11 (no emoji, generative section registry, alert-driven layout per drafted-change buffer, privacy as a design surface).
- Engineering Principles compliance line in both acceptance criteria.
- Forward markers per AD-722c-3 TECHNICAL trigger format.
- "What this does NOT change" explicit in both.

Builder may dispatch when wave-orchestrator advances state from `draft` to `build`.
