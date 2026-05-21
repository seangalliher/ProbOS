# AD-763 — Connector scoping & proactive scan configuration

Status: drafted
Issue: #709
Depends on: AD-749 (M365 OAuth + connectors), AD-752 (proactive scheduler), AD-762 (Settings relocation)

## Captain bug report (2026-05-20)

> "I should also have the ability to configure the inbox and calendar that will be scanned. How will this work currently?"

The proactive scheduler currently scans **the signed-in user's primary mailbox Inbox folder** and **primary calendar only**. There is no operator surface to pick folders, calendars, scan windows, sender filters, or per-scan-type intervals. The only control is the global "Disable proactive" toggle.

## Why this matters

- **Signal-to-noise.** Most operators have a busy Inbox + several shared/group calendars. Scanning all of "Inbox" surfaces newsletters and bulk mail; scanning only the primary calendar misses team meeting context. Without scoping, the proactive feed is either too noisy or blind.
- **Privacy / scope-of-attention.** Operators legitimately want some folders excluded from agent visibility (Personal, HR, Confidential). A single global enable toggle is too coarse.
- **Operational rhythm.** Inbox scans every 5 minutes may be right; calendar scans every 5 minutes is wasteful. Per-scan-type intervals belong to the operator, not the codebase default.
- **Discoverability.** The Captain asked the question — that means today's behaviour is undocumented from the UI's perspective. The Settings surface should be the answer.

## Scope (v1) — architectural reset

**IMPORTANT (architect review, 2026-05-20)**: the Graph integration in `OutlookAgent.list_changes()` / `CalendarAgent.list_changes()` is a **placeholder today** (returns `[]`; verified at `src/probos/integrations/m365_connector.py:103-110` and `:303-310`). The per-scan-type interval primitive does **not exist** — `ProactiveHeartbeatScheduler._SCAN_TYPES` share a single cron expression (`agents/operations/scheduler.py:22-78`). The original prompt framed both as one-line edits; they are not. v1 scope is reset as follows:

- **In v1**: ship config model (§1), Graph discovery endpoints with real Graph calls (§2), real Graph integration in `OutlookAgent.list_changes()` / `CalendarAgent.list_changes()` honouring the scoping config (§3), and HXI Connectors section (§5). The first real Graph calls are part of this AD — not optional.
- **Deferred to AD-763d**: per-scan-type intervals (§4). The scheduler stays on the existing single shared cron expression for v1. The `intervals` block is still defined in the config model (so the schema is stable) but the scheduler does NOT read it yet; a `# TODO AD-763d: per-scan-type cron derivation` comment is added at the scheduler insertion site.
- **Forward marker**: file `AD-763d — per-scan-type cron intervals` as a follow-up; it requires a separate persistent-task-store migration and seconds-→-cron mapping logic out of scope for this AD.

### 1. Config model (backend)
Add a `ProactiveScanConfig` Pydantic block in `src/probos/config.py`, hung off `SystemConfig` (not a separate per-operator JSON store — per-operator settings architecture lands later under AD-741 follow-ups). Defaults must keep existing operator behaviour identical.

- `inbox`:
  - `folders: list[str]` — Graph mail folder IDs to include. Default `["Inbox"]`.
  - `lookback_hours: int` — default 24.
  - `importance_filter: Literal["any", "high"]` — default `"any"`.
  - `unread_only: bool` — default `false`.
  - `sender_allowlist: list[str]` — email addresses or domains (e.g. `@acme.com`). Default empty.
  - `sender_denylist: list[str]` — same shape. Default empty.
- `calendar`:
  - `calendar_ids: list[str]` — Graph calendar IDs to include. Default `["primary"]`.
  - `lookahead_hours: int` — default 24.
  - `include_declined: bool` — default `false`.
- `intervals`:
  - `inbox_seconds: int` — default `PROACTIVE_SCAN_INTERVAL_SECONDS` (300).
  - `calendar_seconds: int` — default 900.
  - `teams_seconds: int` — default 300.

All fields have sensible defaults so existing operators see no behaviour change. Validation at parse time (no runtime surprises).

### 2. Graph discovery endpoints (backend)
New `src/probos/api/routers/connectors.py`:

- `GET /api/connectors/m365/mail-folders` → calls Graph `/me/mailFolders` (recursive), returns `[{id, displayName, parentFolderId, totalItemCount}]`.
- `GET /api/connectors/m365/calendars` → calls Graph `/me/calendars`, returns `[{id, name, owner, canEdit, isDefaultCalendar}]`.
- `GET /api/connectors/scan-config` → returns current `ProactiveScanConfig`.
- `PUT /api/connectors/scan-config` → validates + persists. Returns the persisted shape.

All endpoints require an authenticated M365 session; return 401 if no token / 503 if Graph is unreachable. Defensive validation at the API boundary (Pydantic models, not raw dicts).

### 3. Connector wiring (backend) — first real Graph calls
**Pre-condition** — `OutlookAgent.list_changes()` and `CalendarAgent.list_changes()` are currently stubs returning `[]` (`m365_connector.py:103-110`, `:303-310`). This AD ships the first real implementations:

- `OutlookAgent.list_changes()` reads `config.proactive_scan.inbox` and:
  - For each selected folder ID, calls Graph `GET /me/mailFolders/{id}/messages?$filter=receivedDateTime ge <since>&$top=100` via `httpx.AsyncClient` with the token from `self._token_manager`.
  - Applies `lookback_hours`, `importance_filter`, `unread_only`, and the allow/deny lists at the Graph `$filter` layer where the Graph query language supports it; falls back to in-process filtering for the rest.
  - Pagination: follow `@odata.nextLink` for up to 5 pages (operator-tunable defer to AD-763d), then stop with a `logger.info("AD-763: pagination cap reached for folder=%s", folder_id)`.
  - Error handling: 401 → propagate so the token manager can refresh; 429 → honour `Retry-After`; 5xx → log warning + return whatever was collected.
- `CalendarAgent.list_changes()` reads `config.proactive_scan.calendar` and queries each `calendar_id` via `GET /me/calendars/{id}/calendarView?startDateTime=<now>&endDateTime=<now+lookahead_hours>`. Same error-handling shape as OutlookAgent.
- These are the first real Graph calls in the codebase — follow the existing `M365Connector` Protocol (`m365_connector.py:16-32`) and the established AD-731 attachment-store pattern for any binary content.

### 4. Scheduler wiring (backend) — deferred to AD-763d
**Out of scope for this AD.** `ProactiveHeartbeatScheduler` keeps the existing single shared cron expression (`agents/operations/scheduler.py:22-78`). The `intervals` block in `ProactiveScanConfig` is defined but NOT read by the scheduler yet — add a `# TODO AD-763d: per-scan-type cron derivation reads config.proactive_scan.intervals` comment at the scheduler insertion site (above `_SCAN_TYPES`). The seconds-→-cron mapping logic, per-task `cron_expr` field migration, and re-registration update path are all AD-763d.

### 5. HXI surface (UI) — schema-driven section wiring
Add a "Connectors" section to the Settings panel. **The Settings panel is schema-driven** — wiring requires BOTH layers (mirrors AD-762 ProactiveStatusSection wiring):

- **Backend**: append a `SectionDescriptor(section_id="connectors", label="Connectors", glyph=..., domain="Connectivity", description="M365 mail folders, calendars, scan windows, and filters.", fields=())` to `SECTIONS` in `src/probos/settings/section_registry.py`. `fields=()` because this is a custom panel.
- **Frontend custom-panel branch**: add `{section.section_id === 'connectors' && <ConnectorsSection />}` to `ui/src/components/settings/SettingsMain.tsx` next to the existing `perception` branch (~line 283).
- **`ConnectorsSection.tsx`** in `ui/src/components/settings/sections/` — per-account subsection layout:

  - **Microsoft 365** (only renders when the M365 OAuth session exists per AD-749):
  - **Mail folders** — multiselect populated from `/api/connectors/m365/mail-folders`. Default-checked: Inbox.
  - **Calendars** — multiselect populated from `/api/connectors/m365/calendars`. Default-checked: primary.
  - **Scan windows** — number inputs for `lookback_hours` (inbox) and `lookahead_hours` (calendar).
  - **Filters** — `importance_filter` radio (`any` / `high only`), `unread_only` checkbox, sender allow/deny text areas (one entry per line, trimmed).
  - **Intervals** — three labelled sliders or number inputs (inbox / calendar / teams), in seconds.
  - **Save** button — PUTs `/api/connectors/scan-config`, surfaces success/failure toast via the existing notification system.
- Follow HXI Design Principle #3 (no emoji; inline SVG glyphs only) and #5 (progressive disclosure — collapse subsections by default; expand on click).

### 6. Tests
- Backend:
  - `tests/test_proactive_scan_config.py` — Pydantic defaults, validation (negative intervals rejected, unknown importance value rejected).
  - `tests/test_connectors_router.py` — happy path + 401 (no auth) + 503 (Graph down) for each new endpoint; PUT round-trip persists and `GET` returns the updated shape.
  - Update `tests/test_m365_connectors.py` — `OutlookAgent.list_changes()` honours folder list; `CalendarAgent.list_changes()` honours calendar ID list; allow/deny filters are applied.
  - Update `tests/test_scheduler.py` (or equivalent) — per-scan-type intervals override the global default.
- UI:
  - `ui/src/__tests__/ConnectorsSection.test.tsx` — renders folder list from mocked endpoint; multiselect toggles update local state; Save calls PUT with the right payload; failure path surfaces the toast.

## Out of scope

- Gmail / iCloud / other providers (separate AD-764 for Gmail).
- Per-agent (not per-operator) scan scoping.
- Shared-mailbox or delegated-mailbox enumeration (Graph `/users/{id}/mailFolders`).
- Webhook / Graph change-notification subscriptions (today is poll-based; subscriptions are a future AD).
- Refactoring the existing scheduler beyond reading intervals from config.

## Acceptance signals

- Settings → Connectors → Microsoft 365 lists the operator's actual mail folders and calendars.
- Selecting non-default folders/calendars and saving causes the next proactive scan (visible in `/api/proactive/status`) to query exactly those targets — verifiable via logs or a `last_scan_scope` field on the status payload.
- Sender allow/deny filters demonstrably exclude/include messages in the next scan.
- Per-scan-type intervals demonstrably override the global default after restart.
- `npm run build` clean. `pytest tests/ -x -q` green.

## Engineering principles compliance

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

- New config in Pydantic models, not raw dicts; defaults required; validation at parse time.
- New API endpoints have ≥3 tests each (happy / error / validation).
- Public methods fully type-annotated.
- No emoji in UI; inline SVG only.
- Structured logging at info on scope change, warning on Graph failures with fallback.
- No private-attr access between connectors and config; depend on Pydantic getters.
