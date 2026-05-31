# AD-764 — Gmail connector (Google Workspace + consumer Gmail)

Status: drafted
Issue: #710
Depends on: AD-749 (M365 OAuth pattern), AD-752 (proactive scheduler), AD-763 (connector scoping & scan config)

## Captain request (2026-05-20)

> "Add support for Gmail."

ProbOS today integrates with Microsoft 365 only (AD-749: Outlook, Teams, Calendar, SharePoint, OneDrive via Graph API). Operators on Google Workspace or consumer Gmail have no path to surface email/calendar context to the mesh.

## Why this matters

- **Coverage.** Half the prosumer / SMB market is Workspace-first. M365-only positions ProbOS as enterprise-Windows-only by default.
- **Symmetric capability.** Every proactive scan / RAG ingestion / agent skill that consumes Outlook + Calendar should accept Gmail + Google Calendar with the same shape. Operators shouldn't lose capability for switching email providers.
- **Connector pattern validation.** AD-749 established a `ConnectorBase` ABC with `refresh_token`, `list_changes`, `get_audit_entry`. Gmail is the second implementation — it stress-tests the abstraction and surfaces any M365-specific leakage in the base interface.

## Scope (v1)

### 1. Google OAuth (backend)
Mirror the AD-749 M365 OAuth flow:

- `src/probos/integrations/google_token_manager.py` — OAuth 2.0 with PKCE against `https://accounts.google.com/o/oauth2/v2/auth`. Persist refresh tokens encrypted at rest using the same key/strategy as `M365TokenManager`.
- `src/probos/api/routers/auth_google.py` — `/api/auth/google/start`, `/api/auth/google/callback`, `/api/auth/google/status`, `/api/auth/google/signout`. Same shape as `auth_m365`.
- Scopes (minimum):
  - `https://www.googleapis.com/auth/gmail.readonly` (or `gmail.modify` if we want to mark-read)
  - `https://www.googleapis.com/auth/calendar.readonly` (or `calendar.events` for write)
  - `https://www.googleapis.com/auth/userinfo.email` + `openid`
- Config block in `config.py`:
  - `google.client_id`, `google.client_secret` (encrypted), `google.redirect_uri`, `google.tenant_hint` (optional Workspace domain).
  - Defaults: empty; feature gracefully disabled when unconfigured.

### 2. Gmail + Google Calendar connectors (backend)
New `src/probos/integrations/google_connector.py`:

- `GmailAgent(CognitiveAgent)` — mirrors `OutlookAgent`:
  - `agent_type = "gmail"`, `callsign = "Gmail"` (or merge under a single "Mail" agent identity — open question for review).
  - Capabilities: `gmail_read_messages`, `gmail_search`, `gmail_send` (gated by scope).
  - `list_changes(since)` → Gmail API `users.messages.list` with `q="newer_than:Nd"` derived from `since`.
- `GoogleCalendarAgent(CognitiveAgent)` — mirrors `CalendarAgent`:
  - Capabilities: `gcal_list_events`, `gcal_find_time`, `gcal_book_meeting`.
  - `list_changes(since)` → Calendar API `events.list` with `updatedMin=since`.
- Both honour AD-763 `ProactiveScanConfig` (folders ↔ Gmail labels; calendar IDs ↔ Google calendar IDs).

### 3. Runtime wiring (backend)
- `runtime.py` registers `GmailAgent` + `GoogleCalendarAgent` in the connector pool when Google OAuth is configured AND has a valid token (parallel to `_collect_m365_connectors_for_semantic_sync` pattern).
- Semantic mapper (`integrations/semantic_mapper.py`) treats Gmail messages and Google Calendar events as first-class indexable entities alongside their M365 counterparts.
- Scheduler (AD-752) `proactive_scan_inbox` / `proactive_scan_calendar` cron jobs fan out to ALL configured providers — if both M365 and Google are connected, both are scanned. Per-provider intervals deferred to a follow-up AD if needed; v1 uses the AD-763 interval config for the scan type globally.

### 4. AD-763 scan-config extension
Extend `ProactiveScanConfig` to be provider-aware. Two shape options for review:

- **Option A (flat with provider tag):** Each folder/calendar entry carries `{provider: "m365" | "google", id: str}`. Simple but mixes provider data.
- **Option B (per-provider dicts):** `inbox.m365.folders: list[str]`, `inbox.google.labels: list[str]`. More structured.

**Recommendation: Option B** — clearer separation, easier UI rendering, lets each provider evolve its own filter schema.

### 5. HXI surface (UI)
Extend the AD-763 Settings → Connectors section with a Google account subsection:

- **Connect Google account** button (only shows when not yet authenticated) → triggers `/api/auth/google/start` in a popup, handles callback.
- Once connected: identical UX to the M365 subsection — labels multiselect (populated from `gmail.users.labels.list`), calendar multiselect (`calendar.calendarList.list`), scan windows, filters.
- "Disconnect" button calls `/api/auth/google/signout`.
- Status indicator: green dot when connected & token fresh, amber when refresh needed, red when revoked/expired (matches AD-749 M365 status pattern).
- No emoji; inline SVG glyphs only.

### 6. Tests
- Backend:
  - `tests/test_auth_google.py` — OAuth flow happy path, callback validation, signout, token persistence round-trip.
  - `tests/test_google_token_manager.py` — refresh logic, expiry handling, encrypted storage round-trip.
  - `tests/test_google_connectors.py` — `GmailAgent.list_changes()` and `GoogleCalendarAgent.list_changes()` honour `ProactiveScanConfig`; capability declarations are correct; intent routing works.
  - `tests/test_runtime_google_wiring.py` — runtime registers Google agents only when configured + authenticated.
  - `tests/test_google_security_baseline.py` — mirrors `test_m365_security_baseline.py` (scope validation, no broader scopes than declared, token never logged).
- UI:
  - `ui/src/__tests__/ConnectorsSection.google.test.tsx` — disconnected state shows Connect button; connected state shows label/calendar multiselects populated from mocked endpoints; save round-trips.

## Out of scope

- Google Drive / Google Docs (separate AD when needed — different semantic mapper requirements).
- Google Chat / Hangouts (Teams equivalent — separate AD).
- Service account / domain-wide delegation (admin-managed Workspace install — separate AD; v1 is per-user OAuth).
- Push notifications via Gmail watch / Calendar watch (poll-based parity with AD-749 v1).
- Migrating M365 token storage to a shared abstraction (the duplication is fine for v1; refactor when a third provider lands).

## Acceptance signals

- Settings → Connectors shows both Microsoft 365 AND Google account subsections.
- Captain can connect a Gmail account via OAuth without leaving the HXI.
- Proactive inbox scans surface Gmail messages alongside (or instead of) Outlook messages based on which providers are connected.
- Proactive calendar scans surface Google Calendar events alongside M365 events.
- Per-label / per-calendar scoping from AD-763 works for Google identically to M365.
- Disconnecting Google removes its agents from the next runtime tick without restart.
- `npm run build` clean. `pytest tests/ -x -q` green.

## Engineering principles compliance

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

- New config in Pydantic models with sensible defaults; feature off when unconfigured.
- New API endpoints have ≥3 tests each (happy / error / validation).
- Connector classes implement `ConnectorBase` Protocol exactly — no M365-specific leakage in the base.
- OAuth tokens encrypted at rest; never logged; redacted in error messages.
- No bare `try/except Exception` around imports (BF-274 lesson).
- Public methods fully type-annotated.
- No emoji in UI; inline SVG only.

## Open questions for Architect review

1. **Agent identity merging.** Should Gmail + Outlook be a single "Mail" agent that routes by provider, or two distinct agents (`GmailAgent` + `OutlookAgent`)? Two agents is simpler today; one unified agent is the right end state but requires more design.
2. **Scope minimization.** `gmail.readonly` is the safest starting scope but blocks "mark as read" and "draft reply" — both of which the agent ecosystem will want eventually. Recommend `gmail.modify` from day one with audit logging on every write.
3. **Verification/publishing.** Google OAuth apps need Google verification for any scope that touches user data in production. v1 ships unverified (operator self-installs their own OAuth client); future commercial overlay would ship a verified app. Document this in the README/setup guide.
