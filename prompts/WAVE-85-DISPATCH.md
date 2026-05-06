# WAVE 85 DISPATCH — AD-473 v1 Mobile PWA (HXI Installable Shell)

**Wave id:** 85
**Umbrella AD:** AD-473 (Mobile Companion — PWA & Push Notifications)
**OSS sub-AD letters in scope (concrete v1):** AD-473a (Web App Manifest), AD-473b (service worker + offline app shell), AD-473c (registration helper + `InstallPrompt` component).
**OSS sub-AD letters parked as future ADs (NOT v1 deferrals):** AD-473d (Web Push notifications — server-side VAPID + push-subscription endpoints), AD-473e (Responsive HXI mobile layout — Captain UX decisions on chat/canvas/swipe), AD-473f (mDNS auto-discovery — `zeroconf` Python dep + cross-platform startup wiring), AD-473g (native-app wrappers — explicitly future stretch in roadmap line 4205).
**Closes:** GH issue #67
**HEAD at draft:** `05989c3` (post-Wave-84)
**Baseline test counts:** 11705 pytest (no Python source touched — expected Δ 0); vitest 292 (291 passing + 1 pre-existing `WardRoomDmSync` failure, **not** introduced by this wave) → expected **≥ 305** vitest (Δ ≥ +13; 14 tests planned).
**Builder required:** true (one focused build prompt; UI-only, hand-rolled SW — no new build-system plugin).
**AD numbering:** Highest stem at HEAD remains **AD-696** (Wave 72). AD-473 pre-allocated by `docs/development/roadmap.md:4205`; sub-AD letters a–g are organizational catalog markers only, mirroring Wave 84 / AD-512 a–f precedent — no new AD numbers minted.

## Verdict

Verify-first against HEAD `05989c3` confirms the substrate AD-473 v1 needs is greenfield, the in-scope items have zero Captain UX dependency, and the parked items are blocked on inputs the Captain has not provided — exactly the configuration that warranted Wave 84's "ship the substrate, document the consumer" framing:

- **No PWA scaffold at HEAD:** `Test-Path ui/public/manifest.webmanifest` → False; `Test-Path ui/public/sw.js` → False; `grep -r "registerServiceWorker\|manifest.webmanifest\|theme-color\|apple-mobile-web-app" ui/src ui/index.html` → 0 hits. Greenfield, no collision with prior HXI work.
- **Mobile viewport meta already present:** `ui/index.html:5` carries `<meta name="viewport" content="width=device-width, initial-scale=1.0" />`. Roadmap line 1544 calls out `responsive viewport` as part of Phase 1; it is **already shipped** — no work required, just verified via a vitest assertion against the rendered `index.html`.
- **Vite build pipeline supports static `public/` assets:** `ui/vite.config.ts:1-21` is unmodified Vite 6 default config. Static files at `ui/public/*` are served at site root by Vite's dev server and copied verbatim into `ui/dist/` at build time — no plugin needed for the manifest or SW.
- **Roadmap Phase 1 framing exact-match:** `docs/development/roadmap.md:1544` — *"Progressive Web App (PWA) (Phase 1) — the existing HXI (`/ui/`) made installable as a PWA. Add `manifest.json`, service worker, responsive viewport. Zero new code for basic mobile access. Works on iOS and Android immediately."* AD-473 v1 is the literal Phase 1 shipment described by that sentence.
- **Roadmap line 4205 explicitly numbers the larger components:** *"(1) Progressive Web App, (2) Push notifications, (3) Responsive HXI, (4) mDNS auto-discovery, (5) Native apps (future stretch)."* v1 ships (1). (2)–(5) become AD-473d/e/f/g per the standard sub-AD letter convention — same shape as AD-512 v1 carving discovery learning into a–f.
- **AD-473g already framed as `(future stretch)` in roadmap text** — this wave honors that framing rather than fabricating new deferral language.
- **Captain UX dependency on (3) Responsive HXI is real and unresolved:** the HXI canvas (`ui/src/components/CognitiveCanvas.tsx`, `ui/src/canvas/animations.tsx`) is the *central* design surface. Mobile layout is a major UX decision the Captain has not specified — full-screen chat vs simplified 2D mesh vs swipe-gesture nav are mutually exclusive design directions. Shipping a guess here would violate HXI design principles #1 (system understands the human) and #5 (progressive disclosure driven by engagement). AD-473e is the right place for that conversation.
- **Web Push (2) requires Python-side substrate the Captain has not approved:** VAPID key generation, push-subscription persistence (new SQLite table or knowledge store entry), push-send endpoints, retry/backoff. Adds `pywebpush` (or hand-rolled ECDSA via `cryptography`) as a new Python dependency. Out of scope for a UI-only wave; AD-473d ships that substrate.
- **mDNS (4) requires `zeroconf` Python dep + cross-platform startup wiring** (Bonjour on macOS, Avahi on Linux, Bonjour-via-Apple service on Windows). Same shape — AD-473f handles it.

AD-473 v1 (three concrete sub-AD letters + four future-AD letters with explicit forcing functions) is **fully buildable in one wave**. Captain rule "don't defer unless no choice" is honored: the three buildable items (manifest, SW, install prompt) all ship; the four parked items are blocked on inputs the substrate cannot fabricate (Captain UX, new Python deps, OS-level integration).

| Roadmap component (line 4205) | Wave 85 action |
|---|---|
| (1) Progressive Web App — `manifest.json`, service worker, responsive viewport | **BUILD** AD-473a (Web App Manifest at `ui/public/manifest.webmanifest`), AD-473b (service worker at `ui/public/sw.js` — offline app-shell cache), AD-473c (registration helper `ui/src/pwa/register.ts` + `InstallPrompt` component listening for `beforeinstallprompt`). Viewport meta verified-only (`ui/index.html:5` already correct). |
| (2) Push notifications | **PARKED as AD-473d** — needs server-side VAPID + push-subscription endpoints + Python `pywebpush` dep. Forcing function: `ui/src/pwa/register.ts` v1 ships a `// AD-473d: Web Push integration point` comment marking the exact line where `registration.pushManager.subscribe(...)` will land. |
| (3) Responsive HXI mobile viewport | **PARKED as AD-473e** — needs Captain UX decisions on full-screen chat vs simplified 2D mesh vs swipe gestures. Forcing function: `manifest.webmanifest` v1 declares `"display": "standalone"` and `"orientation": "any"`, leaving the responsive layout decision to the consumer wave. |
| (4) mDNS auto-discovery | **PARKED as AD-473f** — needs `zeroconf` Python dep + cross-platform startup wiring. UI-only wave cannot ship the publisher side. Forcing function: install prompt copy mentions the LAN URL (whatever the Captain configured) — discovery is a connection-bootstrap concern, not a manifest concern. |
| (5) Native apps (future stretch) | **PARKED as AD-473g** — explicitly `(future stretch)` in roadmap text. No forcing function needed; the umbrella entry already documents it. |

## Reframe decision (Captain rule applied)

**Three concrete sub-AD letters built + four future-AD letters with explicit forcing functions + zero hard-deferrals.** Strictest application of "don't defer unless no choice" available for AD-473 — every item the Captain has given the substrate enough information to build, ships in v1; every parked item lists the missing input.

Three things that LOOK like deferrals but aren't:

1. **Push notifications park is a Python-side substrate dependency, not a UI choice.** AD-473d is a backend wave (VAPID key issuance, subscription storage, push-send governance through the Intent bus) plus the matching UI subscribe button. Wedging the UI half into a UI-only wave would create a half-implementation that the Captain cannot exercise — the manifest still works, the install still works, and the integration point is marked at the exact `register.ts` location for the consumer wave.
2. **Responsive HXI park is a Captain UX decision, not an architectural omission.** Mobile layout is a *visual design* call (HXI design principles #1, #5, #11) — the substrate cannot guess. The manifest's `"orientation": "any"` and `"display": "standalone"` keep the door open for whatever responsive direction the Captain picks; v1 does not paint the team into a corner.
3. **mDNS park is a Python-side OS-integration wave, not a UI feature.** UI-only wave cannot ship the publisher side. The install-prompt UX does not depend on mDNS — users can install over `https://probos.local:18900` (or whatever LAN URL they have) without any auto-discovery.

GH #67 closure note (drafted; commits with Builder's PR): "Closed by Wave 85 (AD-473 v1 — three concrete OSS sub-AD letters 473a/b/c). HXI is now an installable PWA on iOS and Android with offline app-shell, manifest, and `beforeinstallprompt`-aware install button. Components 2–5 of roadmap line 4205 (Web Push, Responsive HXI, mDNS, native apps) are parked as future sub-ADs 473d/e/f/g with explicit forcing functions in the dispatch — they are blocked on Captain UX (responsive layout) and Python-side substrate (Web Push VAPID, mDNS publisher) the v1 UI-only wave cannot fabricate. Captain rule honored — every item the substrate had enough information to build, shipped in v1."

## Commercial-leak audit (pre-commit hook safety)

**Banned-pattern sweep on draft** (`prompts/WAVE-85-DISPATCH.md` + `prompts/ad-473-mobile-pwa-v1.md`), per `.git/hooks/pre-commit` — all 11 banned patterns confirmed **0 literal hits across both files**. Patterns referenced via placeholder forms only (the e-word + tier; the private-repo path token; the GTM-pattern phrase; the recurring-revenue acronym; the price/month and price/mo regexes) so the audit text itself does not trip the hook regex. The Wave 84 audit precedent applied verbatim — Captain's request explicitly warned about this self-trip class.

- AD-473 umbrella entry on `docs/development/roadmap.md:4205` carries no `*(Commercial)*` tag — verified via `Select-String '\bAD-473\b.*Commercial' docs/development/roadmap.md` returning zero hits. Wave is fully OSS; no boundary disambiguation required.
- Native-app wrappers (AD-473g) language uses the roadmap's own `(future stretch)` phrasing — no go-to-market language needed.
- Wave is UI-only with zero pricing surface, zero packaging surface, zero distribution-channel surface — there is genuinely nothing here that would require commercial-boundary discussion even if the substrate had to grow it later.

**Verdict:** clean. Pre-commit hook will not trip on this wave's artifacts.

## Verified Against Codebase (2026-05-06)

```
git rev-parse HEAD
  05989c3

# Highest AD stem at HEAD (no new AD minted by this wave):
docs/development/roadmap.md:4205
  "AD-473: Mobile Companion — PWA & Push Notifications (planned)"
docs/development/roadmap.md:1544
  "Progressive Web App (PWA) (Phase 1) — the existing HXI (/ui/) made installable as a PWA. Add manifest.json, service worker, responsive viewport. Zero new code for basic mobile access."
# Wave 84 closure confirmed AD-696 last-assigned (Wave 72 Oracle).

# Pytest baseline (verified):
git log -1 --format=%s 05989c3
  "Wave 84 archive: AD-512 discovery learning (#94)"
# Wave 84 closure note: pytest 11705 post-build.

# Vitest baseline (verified):
cd ui && npx vitest run
  Tests  1 failed | 291 passed (292)
  # WardRoomDmSync.test.tsx pre-existing failure — NOT introduced by Wave 85.

# UI scaffold pattern source (verified):
ui/index.html:5    <meta name="viewport" content="width=device-width, initial-scale=1.0" />  # already correct
ui/index.html:7    <link rel="icon" href="data:," />                                          # placeholder; v1 leaves untouched
ui/index.html:20   <script type="module" src="/src/main.tsx"></script>
ui/src/main.tsx:5  createRoot(document.getElementById('root')!).render(<App />);
ui/vite.config.ts:1-21   default Vite 6 config, no plugin chain — public/ files served at site root
ui/package.json:6        "build": "tsc -b && vite build"                                      # standard build pipeline
ui/package.json:11       "test": "vitest run"                                                 # standard test pipeline

# Greenfield (verified absent — no collision):
ui/public/                                          # directory does not exist at HEAD
ui/public/manifest.webmanifest                      # absent
ui/public/sw.js                                     # absent
ui/public/icons/                                    # absent
ui/src/pwa/                                         # directory absent
ui/src/components/InstallPrompt.tsx                 # absent

# Existing test pattern source (vitest + @testing-library/react):
ui/src/__tests__/ComponentRendering.test.tsx:6     # render/screen/fireEvent imports — pattern source for component tests
ui/src/test/setup.ts:1                             # @testing-library/jest-dom global setup
ui/vitest.config.ts:7                              # environment: 'jsdom', globals: true
```

## Captain rule honored — full breakdown

| Wave 85 action | Captain rule status |
|---|---|
| Manifest, SW, register helper, install prompt all ship | "don't defer unless no choice" — built |
| Web Push parked → AD-473d | NO CHOICE — UI-only wave; Web Push needs Python-side VAPID + endpoints + new dep |
| Responsive HXI parked → AD-473e | NO CHOICE — Captain UX decision pending; HXI principle #1 forbids guessing |
| mDNS parked → AD-473f | NO CHOICE — UI-only wave; mDNS needs Python-side `zeroconf` + cross-platform startup wiring |
| Native apps parked → AD-473g | Roadmap already says `(future stretch)` — honoring existing framing, not adding deferral |

## What this wave does NOT change

- No Python source touched. `pytest` delta = **0**.
- No new Python dependency. `pyproject.toml` untouched.
- No new UI dependency. `ui/package.json` `dependencies` and `devDependencies` untouched. SW is hand-rolled (~50 LOC) — no `vite-plugin-pwa`, no `workbox-*`.
- No edits to `App.tsx`, `CognitiveCanvas.tsx`, `animations.tsx`, `GlassLayer.tsx`, or any HXI canvas surface (HXI design principles preserved verbatim).
- No edits to `index.html` `<style>` block or viewport meta (already correct).
- No edits to `vite.config.ts`. Static `public/*` assets are served by default Vite behavior.
- No new EventType, no new agent, no new pool, no new Intent, no router edit, no consensus change, no trust scorer touch, no episodic store touch.
- No federation, no MCP bridge, no naval-org artifact, no work-board change.
- No edits to `data/`, `config/`, or `tests/` (Python). Vitest tests live under `ui/src/__tests__/`.

## Acceptance criteria

1. `ui/public/manifest.webmanifest` validates as JSON, contains all 7 PWA-required fields (`name`, `short_name`, `start_url`, `display`, `theme_color`, `background_color`, `icons[]`), and at least one icon at `192x192` and one at `512x512` (icons may be SVG placeholders matching HXI design principle #2 — geometric, stroke-based, no fills).
2. `ui/public/sw.js` is a hand-rolled service worker that (a) caches the app-shell on `install`, (b) serves cached app-shell on `fetch` when offline, (c) cleans old caches on `activate` via versioned cache name. ~50 LOC ceiling; no Workbox.
3. `ui/src/pwa/register.ts` exports `registerServiceWorker(): Promise<ServiceWorkerRegistration | null>` — calls `navigator.serviceWorker.register('/sw.js')` if the API is available, returns `null` on unsupported browsers (no throw). Carries inline `// AD-473d: Web Push integration point` comment at the exact line where `registration.pushManager.subscribe(...)` will land.
4. `ui/src/components/InstallPrompt.tsx` listens for `beforeinstallprompt`, surfaces a stroke-based SVG install button (HXI principle #3 — no emoji), calls `prompt()` on click, dismisses on `appinstalled` and on user dismissal. Does NOT auto-render on first paint — appears only after `beforeinstallprompt` fires.
5. `ui/src/main.tsx` invokes `registerServiceWorker()` after `createRoot(...).render(...)` (one new line + one import).
6. `ui/index.html` adds `<link rel="manifest" href="/manifest.webmanifest" />` and `<meta name="theme-color" content="#0a0a12" />` and `<meta name="apple-mobile-web-app-capable" content="yes" />` and `<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />`.
7. **14 vitest tests pass:** manifest JSON shape (4) + register helper (4) + InstallPrompt component (5) + viewport-meta-already-present verify (1).
8. Vitest gate: `cd ui && npx vitest run` reports `≥ 305` passing tests (291 baseline + 14 new). The pre-existing `WardRoomDmSync` failure remains 1 failure — Wave 85 does not fix it; Wave 85 does not regress it.
9. Pytest gate: `pytest tests/ -q -n 4 --dist=loadfile` reports unchanged 11705 (no Python source touched).
10. `PROGRESS.md` updated with the Wave 85 close line. `docs/development/roadmap.md` line 4205 updated to mark `(planned)` → `(v1 shipped)` with the Wave 85 reference and a one-line summary of AD-473d/e/f/g forcing-functions for the parked components.
11. `prompts/wave-plan.yaml` carries the new `id: "85"` entry.
12. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`** (HXI principles #2, #3, #11 specifically — geometric SVG, no emoji, no auto-rendering UI element).

## Tracking & audit

- `prompts/wave-plan.yaml` — append `id: "85"` entry (next on the queue per `/memories/session/wave-queue-batch2.md` line 20).
- `PROGRESS.md` — Wave 85 close line, updated baseline.
- `docs/development/roadmap.md:4205` — `(planned)` → `(v1 shipped)` + sub-AD letter map for 473a/b/c shipped vs 473d/e/f/g parked.
- `DECISIONS.md` — no new architectural decision required (AD-473 is pre-allocated; v1 is roadmap Phase 1 shipment, not a new architectural choice).
- `prompts/WAVE-85-DISPATCH.md` + `prompts/ad-473-mobile-pwa-v1.md` — archived to `prompts/archive/` after Builder finishes (matches Wave 84 close pattern).

## Build artifact list

| File | Action | LOC budget |
|---|---|---|
| `ui/public/manifest.webmanifest` | create | ~30 |
| `ui/public/sw.js` | create | ~50 |
| `ui/public/icons/icon-192.svg` | create | ~10 (geometric, stroke-based) |
| `ui/public/icons/icon-512.svg` | create | ~10 |
| `ui/src/pwa/register.ts` | create | ~25 |
| `ui/src/components/InstallPrompt.tsx` | create | ~80 |
| `ui/src/main.tsx` | modify (1 import + 1 call + render `<InstallPrompt />` inside `<App />` or sibling) | +3 |
| `ui/index.html` | modify (4 `<link>` / `<meta>` adds in `<head>`) | +4 |
| `ui/src/__tests__/Pwa.test.tsx` | create | 14 tests |
| `PROGRESS.md` | modify | +1 line |
| `docs/development/roadmap.md` | modify (line 4205) | +6 lines |
| `prompts/wave-plan.yaml` | modify (append entry) | +12 lines |

**Total new LOC under 250.** Hand-rolled, dependency-free, HXI-aligned.

## Builder dispatch

Single prompt: `prompts/ad-473-mobile-pwa-v1.md`. UI-only build. Vitest gate is the primary signal; pytest gate is a regression check (must remain 11705).
