# Yeo gap-doc reconciliation (2026-05-20)

**AD-765 deliverable.** Filename frozen at `2026-05-20` per AD-765 review recommendation 1 — not retroactively renamed if landing date slides.

Line-item audit of `Yeo_PA_Feature_Gap.md` (private commercial-repo research deliverable) against ProbOS HEAD (commit at audit time: post-AD-762 wave-184 close, highest AD `AD-766`). Replaces the "~70–80%" soft estimate in PROGRESS.md with hard numeric verdicts grounded in `file:line` / AD pointers.

**Status legend.** `shipped` = real implementation verified at file:line; `partial` = primitive exists but the gap-doc capability is not fully realized (missing sub-capabilities enumerated inline); `not-started` = no implementation found; `commercial-overlay-only` = explicitly excluded from OSS scope per AD-697/AD-698 boundary; `out-of-scope` = gap-doc's own non-goals section §10.

**Summary line:** `24 shipped / 11 partial / 12 not-started / 1 commercial / 4 out-of-scope` across 52 capabilities.

---

## §1 — Microsoft 365 / WorkIQ parity (7)

| Capability | Status | Evidence | Follow-up |
|---|---|---|---|
| M365 Auth Service (MSAL + WAM token broker, multi-tenant caching, refresh, sensitivity-label awareness) | partial | `src/probos/integrations/m365_token_manager.py:1-200` ships MSAL device-code flow + keyring-backed refresh; AD-749 covers the OSS scope. **Missing**: WAM (Web Account Manager) broker integration, multi-tenant caching (single-tenant only), sensitivity-label awareness (no MIP/IRM hooks). | AD-767 |
| OutlookAgent (list/read/search/draft mail; flag triage) | shipped | `src/probos/integrations/m365_connector.py:35` `class OutlookAgent`; registered at `src/probos/runtime.py:1006` `spawner.register_template("outlook", OutlookAgent)`. | none |
| TeamsAgent (chats, channels, mentions, presence) | shipped | `src/probos/integrations/m365_connector.py:146` `class TeamsAgent`; registered at `src/probos/runtime.py:1007`. | none |
| CalendarAgent (read/find-time/book, conflict detection, focus blocks) | shipped | `src/probos/integrations/m365_connector.py:245` `class CalendarAgent`; registered at `src/probos/runtime.py:1008`. | none |
| SharePointAgent / OneDriveAgent (search, fetch, upload, link) | shipped | `src/probos/integrations/m365_connector.py:344` `class SharePointAgent` + `:443` `class OneDriveAgent`; both registered at `src/probos/runtime.py:1009-1010`. | none |
| WorkIQ-style semantic layer (unified find_relevant_documents across mail/files/chat) | partial | `src/probos/integrations/semantic_mapper.py:96` `class SemanticMapper` provides `bootstrap_from_episodic()` + `sync_m365_to_semantic()` (AD-750). **Missing**: single unified `find_relevant_documents(query)` entry point that fans out across mail+files+chat in one call; today the consumer must drive each connector separately. | AD-768 |
| Information-barrier & sensitivity-label compliance | not-started | `src/probos/integrations/sharepoint_routing.py:18` has `sensitivity_label: str | None` field but it is `None` by default with no enforcement and no IRM/MIP integration. AD-765 prompt itself flagged this as deferred to a Y4-tier explicit AD when queued. | AD-769 |

## §2 — Desktop / OS surface (8)

| Capability | Status | Evidence | Follow-up |
|---|---|---|---|
| Native tray icon with status colors (idle/running/urgent) | partial | `src/probos/experience/desktop/tray.py:14` `class TrayManager` exists with `set_status()` accepting `idle`/`running`/`urgent`. **Critical gap**: file never imports `pystray` (only mentions it in docstring at line 18); `set_status()` only updates an internal field + logs (line 47); no actual OS tray icon is drawn. Reference confirmed: `grep -n "import pystray\|from pystray"` in `src/probos/` returns 0 matches. AD-759 is the drafted prompt to ship the real packaged tray host. | AD-770 (closes via AD-759 dispatch) |
| OS notifications with click-through to action | partial | `src/probos/experience/desktop/notifications.py:14` `class NotificationCenter.notify_with_action()` exists. **Critical gap**: implementation is `logger.info(...)` + `return actions[0]["label"] if actions else None` (line 47) — never invokes `win10toast`/`pyobjc`/`plyer`. No real OS toast or click-through. | AD-771 |
| Global quick-capture hotkey (Ctrl-Shift-Space) | partial | `src/probos/experience/desktop/hotkey.py:15` `class HotkeyListener.start_listening("ctrl+shift+space")` exists. **Critical gap**: `_listen_loop()` (line 57) is `while self._listening: await asyncio.sleep(1.0)` — placeholder; `pynput`/`keyboard` library never imported. No actual global hotkey registration. | AD-772 |
| Mini-mode always-on-top compact window | not-started | No `MiniMode`/`MiniWindow`/`compact_mode` component in `ui/src/`; `grep -rn "MiniMode\|MiniWindow" ui/src` returns 0 matches. `hotkey.py:on_hotkey_pressed` logs "would activate mini-mode window" — never wired. | AD-773 |
| Auto-start at login + single-instance lock | shipped | `src/probos/experience/desktop/lifecycle.py:31-67` `acquire_lock()` real `os.O_EXCL` impl; `register_autostart()` at line 73 with real Windows registry (line 91 `winreg.SetValueEx`), macOS LaunchAgent (line 102 plist write), Linux `.desktop` file (line 137). | none |
| Code-signed installer (MSIX/DMG/NSIS) | not-started | No installer manifest in repo. `grep -i "msix\|nsis\|codesign\|code_sign\|dmg"` returns no production-code matches. AD-759 spec drafts this requirement but is not yet built. | AD-774 (subsumed by AD-759) |
| Auto-update with channel rollout + crash-loop rollback | not-started | No `auto_update`/`crash_loop`/update-channel code in `src/probos/`. | AD-775 |
| Power management (prevent-sleep / mouse-wiggle during proactive runs) | not-started | No `SetThreadExecutionState`/`prevent_sleep`/`inhibit_sleep` references in `src/probos/`. | AD-776 |

## §3 — Proactive scheduling (6)

| Capability | Status | Evidence | Follow-up |
|---|---|---|---|
| ProactiveScanAgent emitting scan_inbox/scan_calendar/scan_teams intents on schedule | shipped | `src/probos/proactive.py:184` `class ProactiveScanAgent(CognitiveAgent)`; intent emission at `:201` (`intent="proactive_scan"` with `tagged_as="heartbeat"` at `:204`). Scheduled via `src/probos/agents/operations/scheduler.py:39` `proactive_scan_{scan_type}` hook. | none |
| Work-hours gate (Mon-Fri 08:00-18:00 default, configurable) | shipped | `src/probos/proactive.py:247` `if not self._duty_schedule.work_hours.is_active(now): return ...`; configurable via `DutyScheduleConfig.work_hours` in `config/system.yaml:646`. AD-752. | none |
| Urgency classifier agent with trust-weighted confidence | not-started | `urgency: float` field exists on `IntentMessage` (`src/probos/types.py:55`) but there is no dedicated `UrgencyClassifierAgent` and no trust-weighted confidence pipeline. `grep -i "UrgencyClassif"` returns 0 matches. | AD-777 |
| Heartbeat session tagging (isProactiveSession) | shipped | `src/probos/proactive.py:204` `params={"tagged_as": "heartbeat", ...}` on every proactive_scan intent. Naming differs from gap-doc's `isProactiveSession` but the routing/episodic concept is identical. | none |
| /yeo enable\|pause\|status\|interval N shell commands | not-started | `grep "/yeo\b\|cmd_yeo"` in `src/probos/experience/commands/` returns 0 matches. No Captain-facing shell command surface for proactive toggle. | AD-778 |
| Quiet hours / focus mode integration | partial | Quiet hours shipped: `src/probos/proactive.py:344` `quiet_hours_active=duty_schedule.quiet_hours.is_active(now)`; config at `config/system.yaml:655`. **Missing**: focus-mode integration (no `focus_mode`/`focus_block`/`focus_period` references in `src/probos/`); macOS Focus mode + Windows Focus Assist APIs not wired. | AD-779 |

## §4 — Permissions for unattended runs (5)

| Capability | Status | Evidence | Follow-up |
|---|---|---|---|
| autoApproveReadOnly policy (tag intents/tools as read-only, bypass quorum) | shipped | **Spot-check #1 verdict**: `src/probos/security/permission_model.py:38` `auto_approve_read_only: bool = False`; consensus bypass at `src/probos/consensus/quorum.py:194` `return QuorumResult(approved=True, reason="auto_approve_read_only")`. AD-753. Tests: `tests/test_permission_model.py:14` `test_should_auto_approve_read_only_intent_in_autopilot_returns_true`. | none |
| Per-tool / per-server allow-deny lists scoped to ProactiveScan sessions | not-started | No allow/deny list scoped to `tagged_as="heartbeat"` proactive sessions. `auto_approve_read_only` is a global per-intent flag, not a session-scoped per-tool list. | AD-780 |
| Pattern-allowlist for shell (PA tier) | not-started | `src/probos/agents/shell_command.py` has `requires_consensus=True` (default deny) but no pattern-based allowlist. `grep "allowlist\|allow_list\|allowed_patterns"` in `shell_command.py` returns 0 matches. | AD-781 |
| Permission card UI (inline Allow / Allow All read-only / Deny with audit log) | shipped | Backend: `src/probos/security/permission_card.py:16` `class PermissionCard` + `:28` `class PermissionCardManager` + `:114` `card_from_intent()`. Frontend: `ui/src/components/wardroom/PermissionCard.tsx:39` `export function PermissionCard({card, onApprove, onReject, onReviewMore})`. Wired via `src/probos/consensus/quorum.py:11` `from probos.security.permission_card import card_from_intent`. | none |
| Tenant-policy hook (disableYeo, disableM365Read, allowed-tool list) | partial | `src/probos/governance/policy_engine.py:10` `class TenantPolicyEngine(Protocol)` + `:20` `class NullPolicyEngine` (no-op default impl). Roadmap (AD-753 row) explicitly marks "tenant policy hook is extension-point only" — the seam is shipped, no real engine is provided in OSS. This is the AD-697/AD-698 commercial-overlay boundary working as intended for hooks; the Protocol surface is shipped. | none (boundary intentional) |

## §5 — Personal data hardening (6)

| Capability | Status | Evidence | Follow-up |
|---|---|---|---|
| Encryption at rest for tokens, cached M365 content, episodic excerpts with PII | partial | Tokens encrypted: `src/probos/security/credential_encryption.py:12` `class CredentialEncryptor` (system keyring / DPAPI / Keychain / libsecret); used by `src/probos/integrations/m365_token_manager.py:40`. **Missing**: cached M365 content (raw mail/file bodies) is not encrypted at rest; episodic ChromaDB excerpts containing PII are not encrypted. | AD-782 |
| PII redaction in logs (emails, names, doc URLs masked) | shipped | **Spot-check #3 verdict**: `src/probos/security/pii_redaction.py:9` `class PIIRedactor` with `_EMAIL_PATTERN` / `_PHONE_PATTERN` / `_URL_PATTERN` / `_DOCID_PATTERN` / `_TOKEN_PATTERN` regexes; `LogRedactionFormatter` at `:58` + `apply_redaction_to_handlers()` at `:66`. AD-754. Used by `src/probos/security/audit_log.py:11` `from probos.security.pii_redaction import PIIRedactor`. Names per se are not masked (the gap-doc mentions "names" but the implementation covers email/phone/URL/doc-IDs/tokens — name redaction would require NER which is not present). | (sub-gap AD-783 — name NER) |
| Conditional-access compatibility | not-started | No conditional-access (CA policy evaluation, device-compliance check) code in `src/probos/`. MSAL handles CA challenges in-flight but no first-class compatibility surface. | AD-784 |
| Cert pinning for Graph + token endpoints | not-started | `grep "cert_pin\|certificate_pinning"` returns 0 matches. HTTP clients use system trust store. | AD-785 |
| "Forget this" tool (purge specific episodes/knowledge artifacts on user demand) | shipped | `src/probos/routers/security.py:49` `@router.post("/forget")` `async def request_erasure`; backed by `src/probos/knowledge/erasure.py` `ErasureManager.forget_episode()` / `forget_resource()` / `forget_agent_memory()`. AD-754. | none |
| Audit log of every M365 read | partial | `AuditLog` primitive exists at `src/probos/security/audit_log.py:25` + `src/probos/security/audit.py:39` (hash-chained, AD-456). **Missing**: not wired into every `m365_connector.py` read path — `grep "audit.*m365\|m365.*audit"` returns 0 matches in `src/probos/`. Each `OutlookAgent.list_messages` / `SharePointAgent.fetch_file` etc. must emit an AuditLog row. | AD-786 |

## §6 — Office-document skills (3)

| Capability | Status | Evidence | Follow-up |
|---|---|---|---|
| DocxAgent / PptxAgent / XlsxAgent | shipped | **Spot-check #4 verdict**: `src/probos/skill_framework.py:27` `class DocxAgent(SkillBasedAgent)`; `:130` `class PptxAgent`; `:216` `class XlsxAgent`. Registered at `src/probos/runtime.py:1016-1018` `spawner.register_template("office_docx", DocxAgent)` etc. AD-755. | none |
| SharePoint upload routing (online edit vs Graph API upload) | shipped | `src/probos/integrations/sharepoint_routing.py:30` `class SharePointRouter` with `route_for_read()` (`:41`) returning online-edit URL vs Graph API URL based on `_infer_source()`; `upload_to_personal()` at `:61` returns Graph upload URL. | none |
| Template library (resumes, meeting notes, status reports) | shipped | `src/probos/integrations/template_registry.py:31` `class TemplateRegistry` with `list_templates()` + `create_from_template()`. AD-755. | none |

## §7 — Conversational front door (5)

| Capability | Status | Evidence | Follow-up |
|---|---|---|---|
| Welcome screen + suggested prompts | shipped | `ui/src/components/WelcomeOverlay.tsx:6` `export function WelcomeOverlay()` with first-visit gate (`hxi_seen_intro` localStorage key) and two suggested prompts at line 71 (`Try: "What's the weather in Tokyo?" or "Summarize a URL"`). | none |
| Personalities (work / casual / focus) as Captain-selectable profiles | not-started | `personality: Record<string, number>` field on agent profile is per-agent Big Five traits (`ui/src/components/profile/ProfileInfoTab.tsx:198`), NOT Captain-selectable work/casual/focus presets. No `personality_profile_selector` or work/casual/focus mode switcher in UI. | AD-787 |
| Suggested actions panel (Yeo proposes 3-5 things based on inbox/calendar) | shipped | `ui/src/components/wardroom/SuggestedActionsPanel.tsx:39` `export const SuggestedActionsPanel` with `fetchSuggestedActions()` at `:28`. Test: `ui/src/__tests__/SuggestedActionsPanel.test.tsx:11`. | none |
| Cross-crew delegation UI (Yeo @-mentions specialists in chat) | partial | Backend chain-of-command delegation shipped (AD-440 `OrderManager.issue_order`); `@mentions` exist in WardRoom (per DECISIONS.md AD-654d "WardRoom @mentions"). **Missing**: explicit DM-thread UI affordance for Yeo to insert a `@SpecialistName` token that triggers cross-crew delegation; the UI shape for "Yeo proposes this should go to Architect" is not built. | AD-788 |
| Yeo daily briefing at first interaction of the day | shipped | `ui/src/components/wardroom/DailyBriefingPanel.tsx:20` `export const DailyBriefingPanel` with `fetchDailyBriefing()` at `:14`. Test: `ui/src/__tests__/DailyBriefingPanel.test.tsx:5`. | none |

## §8 — Identity & continuity (3)

| Capability | Status | Evidence | Follow-up |
|---|---|---|---|
| Captain Card adoption for personalization | shipped | `src/probos/captain_card/card.py:42` `class CaptainCard(BaseModel)`; `default_captain_card()` at `:98`; `load_card()` at `:103`; wired in `src/probos/runtime.py` via `captain_card_enabled` config field (`src/probos/config.py:444`). AD-757. | none |
| Yeo personality + voice profile | partial | `CaptainCard` model supports personality fields; voice binding goes through avatar telemetry. **Missing**: Yeo-specific personality binding distinct from generic CrewProfile — AD-766 (drafted Wave 184, not yet shipped) instantiates the YeomanAgent on the Bridge with explicit CaptainCard-driven persona. | none (AD-766 dispatch closes the gap) |
| Multi-device continuity (laptop + PWA on phone same state) | commercial-overlay-only | OSS scope per AD-697/AD-698 boundary is local-only single-device runtime. Multi-device state sync (Yeo state mirrored across laptop + phone PWA) is in commercial overlay territory. | none |

## §9 — Backstop: heartbeat-style learning (5)

All five are gap-doc "gets for free" items — existing primitives proactive runs benefit from automatically.

| Capability | Status | Evidence | Follow-up |
|---|---|---|---|
| Hebbian-learned proactive routing | shipped | `src/probos/mesh/routing.py` Hebbian connection weights; proactive_scan intents flow through the same router as user intents. | none |
| Trust-decay on noisy classifiers | shipped | `src/probos/consensus/trust.py` Bayesian Beta(alpha, beta) trust scoring; bad classifier outcomes decay trust, eligible classifiers re-route. | none |
| Dreaming consolidation of yesterday's interactions | shipped | `src/probos/cognitive/dreaming.py` idle-time episodic consolidation; proactive_scan episodes consolidated alongside user-driven ones. | none |
| Correction loop ("this wasn't urgent" patches the classifier) | shipped | `src/probos/cognitive/correction_detector.py` + `src/probos/cognitive/agent_patcher.py` — corrections detected, agents hot-patched, episodic memory updated. | none |
| /why for every Yeo suggestion | shipped | `IntrospectionAgent` exposes `why` intent (per runtime.py registration); slash command resolves through introspection. | none |

## §10 — Explicit non-goals (4)

All four are gap-doc's own §10 non-goals.

| Capability | Status | Evidence | Follow-up |
|---|---|---|---|
| Loki-style server-side memory store | out-of-scope | Gap-doc §10. ProbOS uses ChromaDB + Git-backed knowledge — explicit architectural choice not to ship a Loki-style server. | none |
| In-house extraction pipeline | out-of-scope | Gap-doc §10. Leverages M365 Graph + episodic — no bespoke extractor. | none |
| Reliability machinery (DLQs, coalescing) for memory | out-of-scope | Gap-doc §10. Memory uses ChromaDB + episodic — DLQ patterns are NATS-side, not memory-side. | none |
| Bespoke skill bundler | out-of-scope | Gap-doc §10. Skills land via `SkillBasedAgent` pattern, not a bundler. | none |

---

## Child-AD backlog

**Current highest AD: AD-766** (per `prompts/wave-plan.yaml:4024` Wave 184 dispatch). Child ADs below sequenced AD-767 → AD-789 (23 entries, one per `partial`/`not-started` row excluding commercial/out-of-scope/already-covered-by-existing-prompt rows).

Format: `AD-XXX — <capability>. Builds on <existing primitive>. Scope: <one sentence>. Test plan: <one sentence>. License disposition: <OSS / commercial-only / pattern-absorption>.`

```
AD-767 — M365 Auth: WAM broker + multi-tenant cache + sensitivity-label awareness. Builds on m365_token_manager.py (MSAL device-code). Scope: add WAM token broker for Windows-native interactive flow, per-tenant cache partitioning, and MIP sensitivity-label propagation into IntentMessage.params. Test plan: tests/test_m365_wam_broker.py covers Windows WAM happy path + tenant-isolation regression + label-on-fetch round-trip. License disposition: OSS (msal/msal-extensions both MIT).

AD-768 — WorkIQ unified find_relevant_documents API. Builds on integrations/semantic_mapper.py (SemanticMapper.sync_m365_to_semantic). Scope: add SemanticMapper.find_relevant_documents(query, owner) single-call fan-out across mail+files+chat returning ranked SemanticEntity list with provenance. Test plan: tests/test_semantic_mapper_unified_search.py covers cross-source recall + ranking + empty-corpus degrade. License disposition: OSS.

AD-769 — Information-barrier + sensitivity-label enforcement. Builds on sharepoint_routing.py (sensitivity_label field). Scope: enforce MIP labels at SharePointRouter.route_for_read (refuse + audit when label disallows current user/agent). Test plan: tests/test_sharepoint_label_enforcement.py covers public/confidential/restricted with allow + deny + audit-row assertions. License disposition: OSS.

AD-770 — Real pystray-backed tray icon. Builds on experience/desktop/tray.py (TrayManager stub). Scope: replace stub with real pystray icon + set_status() drawing amber/pulse/red glyphs across Win/macOS/Linux. Test plan: tests/test_tray_icon_smoke.py covers platform-conditional import + status-state transitions (mock pystray). License disposition: OSS (pystray LGPL is a copyleft risk — prefer pattern-absorption or rumps/PyQt alternative; license disposition Required-resolve before build).

AD-771 — Real OS notifications with click-through. Builds on experience/desktop/notifications.py (NotificationCenter stub). Scope: wire win10toast (Win), pyobjc UserNotifications (macOS), notify-send (Linux); register intent-callback for click-through. Test plan: tests/test_notification_center.py covers per-platform dispatch + callback resolution + quiet-hours suppression. License disposition: OSS (win10toast MIT, pyobjc MIT, libnotify LGPL via subprocess only).

AD-772 — Real global hotkey listener (Ctrl-Shift-Space). Builds on experience/desktop/hotkey.py (HotkeyListener placeholder). Scope: wire pynput global hotkey on all three platforms; activate mini-mode on press. Test plan: tests/test_hotkey_listener.py uses pynput Controller to simulate keypress + asserts on_hotkey_pressed callback fires. License disposition: OSS (pynput LGPL — same caveat as pystray; consider keyboard library MIT or platform-native fallback).

AD-773 — Mini-mode always-on-top compact HXI variant. Builds on ui/src/HXI canvas (full-mode). Scope: add Mini-Mode React variant (200x300px compact view, single-line intent input, recent results) opened by global hotkey via window.electron.openMiniMode() or PWA always-on-top fallback. Test plan: ui/src/__tests__/MiniMode.test.tsx covers render + intent submit + close. License disposition: OSS.

AD-774 — Code-signed installer (NSIS / DMG / MSIX). Builds on AD-759 native-desktop-tray-app spec. Scope: build NSIS (Win), DMG (macOS), MSIX (Win Store) installers with code-signing pipeline. Test plan: scripts/installer/test_installer_smoke.sh checks installer + signature on each OS. License disposition: OSS (NSIS zlib, mkdmg MIT). Subsumed by AD-759 dispatch — file as AD-759-1 if AD-759 takes a phased approach.

AD-775 — Auto-update with channel rollout + crash-loop rollback. Builds on installer (AD-774). Scope: Squirrel-style update service polling a release channel, with crash-loop detector that rolls back to previous version after 3 consecutive crashes within 5 min. Test plan: tests/test_updater.py mocks release server + crash sequence + asserts rollback. License disposition: OSS (squirrel.windows MIT, sparkle BSD).

AD-776 — Power management (prevent-sleep during proactive runs). Builds on proactive.py (proactive_scan loop). Scope: wrap proactive-scan window in SetThreadExecutionState (Win), caffeinate (macOS), systemd-inhibit (Linux) to prevent sleep. Test plan: tests/test_power_management.py mocks platform API + asserts inhibitor entered/exited around scan window. License disposition: OSS (platform-native API calls only).

AD-777 — Urgency classifier agent with trust-weighted confidence. Builds on consensus/trust.py + IntentMessage.urgency field. Scope: new UrgencyClassifierAgent (CognitiveAgent) that scores incoming inbox/calendar items 0.0-1.0 with trust-decay on miscalibrated outputs. Test plan: tests/test_urgency_classifier.py covers classification accuracy on synthetic corpus + trust-decay regression on systematic over/under-call. License disposition: OSS.

AD-778 — /yeo enable|pause|status|interval shell commands. Builds on experience/commands/ slash-command surface. Scope: register /yeo subcommands that toggle ProactiveScanAgent enabled-flag, set interval, and report status (next scan, last finding, work-hours active). Test plan: tests/test_yeo_commands.py covers each subcommand happy path + invalid-arg error. License disposition: OSS.

AD-779 — Focus-mode integration (macOS Focus, Win Focus Assist). Builds on proactive.py quiet_hours gate. Scope: detect OS-level Focus mode + add to gate predicate alongside quiet_hours. Test plan: tests/test_focus_mode_gate.py mocks platform Focus-state API + asserts scan suppressed when focus active. License disposition: OSS (platform-native APIs).

AD-780 — Per-tool/per-server allow-deny lists scoped to ProactiveScan sessions. Builds on security/permission_model.py (auto_approve_read_only). Scope: extend PermissionConfig with proactive_allow_tools / proactive_deny_tools / proactive_allow_servers arrays; gate at quorum entry for heartbeat-tagged intents. Test plan: tests/test_proactive_scoped_permissions.py covers allow + deny + default-fallback paths. License disposition: OSS.

AD-781 — Pattern-allowlist for shell (PA tier). Builds on agents/shell_command.py (requires_consensus=True default). Scope: ShellConfig.allow_patterns: list[str] (glob/regex) that bypasses consensus when intent.params.command matches; deny-list overrides allow. Test plan: tests/test_shell_pattern_allowlist.py covers match + non-match + deny-overrides-allow. License disposition: OSS.

AD-782 — Encryption at rest for cached M365 content + episodic PII excerpts. Builds on security/credential_encryption.py. Scope: extend CredentialEncryptor pattern to wrap ChromaDB writes containing PII tags + cached SharePoint/Outlook bodies with platform-keyring-derived key. Test plan: tests/test_episodic_encryption.py covers round-trip + key-rotation + lookup-by-tag. License disposition: OSS (keyring MIT).

AD-783 — Name redaction via lightweight NER. Builds on security/pii_redaction.py (regex-based redactors). Scope: add PIIRedactor.redact_names() using spaCy en_core_web_sm or regex-based fallback (titles + capitalized-pair heuristic) for "John Smith"-shape names. Test plan: tests/test_pii_name_redaction.py covers common-name + uncommon-name + false-positive (locations/orgs) cases. License disposition: OSS if regex-only; spaCy MIT + model CC-BY-SA — prefer regex/heuristic if model license blocks.

AD-784 — Conditional-access compatibility surface. Builds on integrations/m365_token_manager.py (MSAL CA challenge handling). Scope: surface CA challenges as first-class events (capability_blocked_by_ca) with required-claim + remediation-link in payload; UI toast guiding Captain through device-compliance step. Test plan: tests/test_conditional_access_flow.py mocks MSAL CA-challenge response + asserts event emitted + UI guidance shown. License disposition: OSS.

AD-785 — Cert pinning for Graph + Microsoft token endpoints. Builds on httpx client config. Scope: pin Microsoft Graph + login.microsoftonline.com cert SPKI hashes in httpx Transport layer; fail fast on mismatch + log security_event. Test plan: tests/test_cert_pinning.py covers valid-pin pass + mismatched-pin reject + emergency-override config. License disposition: OSS.

AD-786 — Audit-log wiring for every M365 read. Builds on security/audit_log.py + integrations/m365_connector.py. Scope: emit AuditLog row at every OutlookAgent / TeamsAgent / CalendarAgent / SharePointAgent / OneDriveAgent read entry-point with (agent, resource, sensitivity_label, outcome). Test plan: tests/test_m365_read_audit.py covers each connector + asserts audit row hash-chained + redaction applied. License disposition: OSS.

AD-787 — Captain-selectable personality profiles (work/casual/focus). Builds on captain_card/card.py + HXI overlay. Scope: PersonalityProfile enum + CaptainCard.active_profile field + UI selector in Settings → Profile; agents read profile to shape tone/verbosity/proactivity. Test plan: tests/test_personality_profile.py covers selector persistence + agent tone-shaping + default fallback. License disposition: OSS.

AD-788 — Cross-crew delegation UI (Yeo @-mentions specialists in DM). Builds on AD-440 OrderManager + WardRoom @mention surface. Scope: when YeomanAgent (AD-766) determines a request belongs to a specialist, render a UI affordance in the DM that previews the delegation target + Captain confirms before fan-out. Test plan: ui/src/__tests__/CrossCrewDelegationCard.test.tsx covers preview + confirm + cancel + audit row. License disposition: OSS.

AD-789 — Suggested actions ranking + dismiss-feedback loop. Builds on SuggestedActionsPanel.tsx. Scope: track which suggested actions Captain accepts / dismisses; surface signal to trust + Hebbian; re-rank future suggestions. Test plan: tests/test_suggested_actions_feedback.py + vitest covers dismiss → trust-decay + re-rank + persistence. License disposition: OSS. (Bonus: tightens the §9 "for free" learning loop on suggested-actions surface.)
```

## Spot-check verdicts (the four high-priority §4 items from the AD-765 spec)

1. **`autoApproveReadOnly` permission policy** — **SHIPPED**. `security/permission_model.py:38` + `consensus/quorum.py:194`. The policy genuinely tags intents read-only and bypasses quorum at the gate. The §4 row corresponds 1:1 to AD-753.
2. **Tray icon + global hotkey + mini-mode** — **PARTIAL (stub-only)**. `experience/desktop/lifecycle.py` lock/autostart is real. `tray.py`, `notifications.py`, `hotkey.py` are import-free stubs with logger-only side effects — `pystray`/`pynput`/`win10toast`/`pyobjc` are never imported anywhere in `src/probos/`. The user-visible surface (tray icon drawing, OS toast, global key capture, mini-window) does not exist. AD-759 drafts the real packaged tray host; AD-770/771/772/773 cover the per-component gaps.
3. **PII redaction in logs** — **SHIPPED (with one sub-gap)**. `security/pii_redaction.py` covers email/phone/URL/doc-IDs/tokens via regex + `LogRedactionFormatter`. Name redaction is the one gap-doc sub-capability not covered (would require NER); filed as AD-783.
4. **DocxAgent / PptxAgent / XlsxAgent** — **SHIPPED**. `skill_framework.py:27,130,216` + `runtime.py:1016-1018` registration. All three are real `SkillBasedAgent` subclasses with template registration in the spawner.
