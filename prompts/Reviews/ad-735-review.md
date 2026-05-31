# AD-735 Architect Review — 2026-05-29

**Spec:** `prompts/ad-735/AD-735-SPEC.md` (issue #795)
**Verdict:** APPROVE (one Required fix folded in; no rewrite cycle)

## Architecture ruling (RATIFIED)
Ride the AD-725 default-OFF master gate for v1; `identity_enabled` defaults True within it.
Do NOT build an independent always-on injection now (would duplicate the AD-725 firewall =
DRY violation; would run the classifier on every DM turn against the operator's deliberate
opt-out). File **AD-735a** forward marker for always-on promotion if AD-725 stays off.

## Firewall invariants — all four preserved (≤1 lookup/turn, read-only, hard timeout, no bus).

## Classifier-first ordering — no AD-725 regression (all 5 live ladder messages re-checked; none match identity).

## Required (folded into spec)
1. Registry accessor is confirmed `registry.get(agent_id)` (`substrate/registry.py:51`).
   `get_by_id` does NOT exist — phantom hedge struck from spec.

## Recommended (folded into spec)
1. Tightened over-triggering identity patterns (anchor on `your (name|callsign)`); added
   negative test cases ("spell the name of that function", "what role do you want me to play").
2. Seed callsign from `self._resolve_callsign()` (canonical BF-101 resolver, cognitive_agent.py:4567).
3. AD-735a forward marker promoted to a contract deliverable (PROGRESS.md OPEN entry).

## Nits (folded)
- Confirm `from datetime import datetime` in module scope.
- `isinstance(cert.birth_timestamp, (int, float))` guard before float→ISO conversion.

## Verified-OK (grep evidence)
- `registry.py:51 def get(self, agent_id) -> BaseAgent | None`
- `cognitive_agent.py:4573 cert = rt._identity_registry.get_by_slot(self.id)`; `identity.py:668 get_by_slot`
- `identity.py:142 AgentBirthCertificate{agent_uuid,did,agent_type,callsign,vessel_name,birth_timestamp(float),department,certificate_hash}`
- `cognitive_agent.py:4569 self.callsign`; `:637 self.agent_type`; `:2561 from probos.cognitive.standing_orders import get_department`; `standing_orders.py:77 get_department`
- `config.py:4824 DmTargetedLookupConfig`; `:4833 enabled=False`; `:4836 enable_oracle/episodic/codebase/knowledge`
- `_is_lookup_enabled` = dict literal keyed by lookup_type read with `.get(..., False)`; add `"identity": self._cfg.identity_enabled`
- `LookupType Literal[...]` extend with `"identity"`; `TargetedLookupResult{lookup_type,query,content,elapsed_ms}` frozen
