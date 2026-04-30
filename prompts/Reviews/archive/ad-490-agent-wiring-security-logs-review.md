# Review: AD-490 — Agent Wiring Security Logs

**Verdict:** ✅ Approved
**Headline:** Enriches agent_wired audit logs cleanly; event-log structure and Counselor integration are sound.

## Required

None.

## Recommended

1. **Log emission ordering.** Moving `agent_wired` after identity resolution (line ~350) — verify nothing downstream subscribes to the early-emission timing. Grep [runtime.py](src/probos/runtime.py) for `agent_wired` listeners; if any expect early notification, document the change in the prompt.
2. **Asset-agent enrichment.** Asset (non-crew) agents skip `did`/`sovereign_id`. Verify the wired log still includes useful context (pool, tier). Add a test for both crew and asset paths.
3. **Department resolution precedence.** Prompt resolves department twice (ontology, then standing_orders fallback). Document which wins on disagreement — current order: ontology first.

## Nits

- SEARCH block targets lines 191-197; `agent_wired` confirmed at [agent_onboarding.py:193](src/probos/agent_onboarding.py#L193). Builder should pin to the actual line.
- Red team enrichment hardcodes `department="security"`. Cross-check standing_orders classification for `red_team` agent type.
- `EventType.AGENT_WIRED` constant added but emission sites still use the string literal (acknowledged in the prompt). File a follow-up AD to migrate.

## Verified

- `agent_wired` event at [agent_onboarding.py:193](src/probos/agent_onboarding.py#L193).
- Identity resolution block [agent_onboarding.py:280-350](src/probos/agent_onboarding.py#L280); billet assignment ~line 343.
- `_spawn_red_team` at [runtime.py:1112](src/probos/runtime.py#L1112).
- `EventLog.log()` accepts `data: dict[str, Any] | None = None` at [substrate/event_log.py:94-106](src/probos/substrate/event_log.py#L94).
- `AGENT_STATE` at [events.py:76](src/probos/events.py#L76) — `AGENT_WIRED` constant insertion point confirmed.
- `standing_orders.get_department` at [cognitive/standing_orders.py:70](src/probos/cognitive/standing_orders.py#L70).
