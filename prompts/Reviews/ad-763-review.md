# Review: AD-763 — Connector scoping & proactive scan configuration
**Verdict:** ❌ Not Ready — two Required findings; scope-shape concern
**The M365 Graph integration is a placeholder (returns `[]`) and the scheduler has no per-scan-type interval primitive. This AD is at least 2× larger than the prompt acknowledges.**

## Required (must fix before building)
1. **`OutlookAgent.list_changes()` and `CalendarAgent.list_changes()` are placeholders.** Verified at `src/probos/integrations/m365_connector.py:103-110` and `:303-310` — both return `[]` with a "Placeholder: actual Microsoft Graph API call would go here" comment. The prompt's §3 says "Queries each selected folder ID via Graph `/me/mailFolders/{id}/messages` instead of the hardcoded primary Inbox" — but **there is no current Graph call to modify.** Builder will need to implement the Graph integration from scratch, including `httpx` client wiring, retry/backoff, error handling, and pagination. This is a major addition the prompt frames as a one-line change. **Required fix**: either (a) split into AD-763a (Graph integration baseline) + AD-763b (scoping config) + AD-763c (UI), or (b) explicitly call out in §3 that "the Graph call does not exist today — implement it with the scoping config as the only entry point." Recommend (a).

2. **`ProactiveHeartbeatScheduler` has no per-scan-type interval primitive.** Verified at `src/probos/agents/operations/scheduler.py:22-78` — `_SCAN_TYPES = ("inbox", "calendar", "teams")` share a single `cron_expr` computed from work-hours (`*/15 {hour_range} * * {days}`). There is no per-scan-type cron customization. The prompt's §4 ("ProactiveHeartbeatScheduler reads `config.proactive_scan.intervals` and registers each cron job with its per-scan-type interval") requires:
   - Per-scan-type cron expression derivation from `intervals.{inbox,calendar,teams}_seconds` (seconds → cron is non-trivial — `300s` doesn't map cleanly to a cron expression; need `*/5` minute syntax with hour-range overlay).
   - `ensure_jobs_registered()` becomes scan-type-aware in the existing-hooks dedup check (currently dedupes by `webhook_name`; per-interval re-registration needs an update path).
   - The persistent task store's `cron_expr` field becomes per-task instead of shared.
   - **Required fix**: explicit subsection in §4 enumerating these three changes, OR defer the intervals work to a follow-up AD-763d and ship §1+§2+§3+§5 in v1 with the existing single-cron behaviour. Recommend deferring intervals.

## Recommended
1. `M365Connector` Protocol exists at `src/probos/integrations/m365_connector.py:16-32`. New `connectors.py` router should expose Graph operations via the existing token manager pattern, not duplicate. Confirm in the prompt by referencing the Protocol explicitly.
2. Settings panel wiring carries the same shape as AD-762's Required #1: add a `SectionDescriptor(section_id="connectors", ...)` to `section_registry.py` AND a `{section.section_id === 'connectors' && <ConnectorsSection />}` branch in `SettingsMain.tsx`. The current §5 just says "Add a 'Connectors' section to the Settings panel" — make this explicit.
3. Settings store pattern for per-operator config: there is no existing per-operator JSON store today (verified absence). The new `ProactiveScanConfig` should follow the standard SystemConfig Pydantic field pattern (loaded from `config/system.yaml`) until a per-operator settings store ships — which is a separate concern (AD-741 settings architecture). Clarify in §1 that the config lives in `SystemConfig`, not a new store.
4. `proactive.py` (`agent_type = "proactive_scan"`) is the agent that drives the scans (verified `src/probos/proactive.py:178-220`). The prompt mentions only OutlookAgent/CalendarAgent — confirm whether the scoping config is read in `ProactiveScanAgent` or in the connector agents themselves. Builder should trace the actual data flow before writing the filter logic.

## Nits
- Endpoint paths (`/api/connectors/m365/mail-folders`, etc.) are fine but follow the existing route naming convention — confirm against `src/probos/routers/` for plural-vs-singular conventions.
- "503 if Graph is unreachable" — Graph returns its own status codes; "503" should be reserved for ProbOS-internal unavailability. Recommend "502 Bad Gateway" or transparent passthrough with a structured error body.

## Verified
- `OutlookAgent` exists at `m365_connector.py:35`. ✓
- `CalendarAgent` exists at `m365_connector.py:245`. ✓
- `M365Connector` Protocol exists at `m365_connector.py:16`. ✓
- `ProactiveHeartbeatScheduler` exists at `agents/operations/scheduler.py:22`. ✓
- `PROACTIVE_SCAN_INTERVAL_SECONDS = 300` exists at `config.py:57`. ✓
- `ProactiveScanAgent` exists at `proactive.py:187`. ✓
- `AD-749 / AD-752 / AD-762` dependency references are real ADs in the wave history. ✓

## Re-review (2026-05-20)
Required finding #1 (placeholder Graph integration) addressed by prompt edit: §3 rewritten to call out that this AD ships the first real Graph calls (`/me/mailFolders/{id}/messages`, `/me/calendars/{id}/calendarView`) with explicit pagination, 401/429/5xx error handling, and reference to the existing `M365Connector` Protocol. Required finding #2 (no per-scan-type interval primitive) addressed by deferral: §4 explicitly removed from v1 scope and assigned to forward marker `AD-763d`; the `intervals` block stays in the config schema but the scheduler does not read it yet. Recommended #2 (Settings panel two-layer wiring) also folded into §5. Recommended #3 (config home in `SystemConfig`) folded into §1. Required findings cleared. **Ready for GATE 1** as a scope-reset v1.

**Builder caveat**: v1 is still a meaningful chunk of work (first real Graph calls + new Pydantic config block + 4 new endpoints + UI section). If the Builder finds the Graph integration alone is multi-AD-shaped after starting, surface a hard-stop and split rather than ship a half-implementation.
