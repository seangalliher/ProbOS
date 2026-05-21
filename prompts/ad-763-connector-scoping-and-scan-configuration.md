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

## Scope (v1)

### 1. Config model (backend)
Add a `ProactiveScanConfig` Pydantic block in `src/probos/config.py`, persisted per-operator in the existing settings store:

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

### 3. Connector wiring (backend)
- `OutlookAgent.list_changes()` reads `config.proactive_scan.inbox` and:
  - Queries each selected folder ID via Graph `/me/mailFolders/{id}/messages` instead of the hardcoded primary Inbox.
  - Applies `lookback_hours`, `importance_filter`, `unread_only`, and the allow/deny lists at the Graph `$filter` layer where possible, falling back to in-process filtering.
- `CalendarAgent.list_changes()` reads `config.proactive_scan.calendar` and queries each `calendar_id` via `/me/calendars/{id}/events`, applying `lookahead_hours` and `include_declined`.

### 4. Scheduler wiring (backend)
- `ProactiveHeartbeatScheduler` reads `config.proactive_scan.intervals` and registers each cron job with its per-scan-type interval instead of the single global default.
- On config update via PUT, the scheduler re-reads intervals and reschedules. (If reschedule-on-the-fly is non-trivial, log a "restart required to apply" warning — but the saved config still takes effect on next boot.)

### 5. HXI surface (UI)
Add a "Connectors" section to the Settings panel (alongside AD-762's "Proactive" section). Inside, a per-account subsection:

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
