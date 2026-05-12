# AD-720d-2 — Per-agent `vision_capable` designation (Wave 154)

**GH:** [#564](https://github.com/seangalliher/ProbOS/issues/564). **Status:** Buildable.

## Problem

The vision-tier routing in [src/probos/routers/agents.py](src/probos/routers/agents.py) `agent_chat` (line 874) routes ALL image-bearing DMs through the vision tier without checking whether the receiving agent is allowed to receive vision. Some agent types (security-sensitive, low-trust, future commercial overlays) should be text-only.

## Scope

1. Add `vision_capable: bool = False` field to `CrewProfile` at [src/probos/crew_profile.py](src/probos/crew_profile.py) line 212. Default **False** (Wave 10 convention #14 — transitional flag default-False; flip per-agent via seed). Update `to_dict()` / `from_dict()` round-trip.
2. Add `vision_capable: true` to `config/standing_orders/crew_profiles/counselor.yaml` and `config/standing_orders/crew_profiles/architect.yaml`. Confirm `_default.yaml` does NOT set the field (so all unspecified crew inherit the dataclass default of False). Verify `load_seed_profile` at [src/probos/crew_profile.py](src/probos/crew_profile.py#L518) plumbs the new key through `from_dict` — extend that mapping if necessary.
3. In `routers/agents.py` `agent_chat`, BEFORE the `vision_messages` is constructed (i.e. before `if image_ids:` block at line ~923), resolve the agent's vision_capable flag. If False AND `image_ids` would be non-empty, fall through to the text-only `augment_prompt_with_attachment_text` path with a logger.info line: `"AD-720d-2: agent_id=%s vision_capable=False; routing image attachment through text-only fallback"`. Do NOT use honest-degrade messages here — the Captain attached the image deliberately; agent receives an attachment marker, not a refusal.
4. Same treatment in `routers/chat.py` `/api/chat` vision path — BUT only when a directed-mention callsign is present AND that callsign resolves to a `vision_capable=False` agent. Untargeted vision turns (no callsign) ALWAYS route through vision tier (the LLM is the responder, not an agent).
5. **Accessor (verified at HEAD):** the canonical crew-profile store is `runtime.acm.get_profile(agent_type)` at [src/probos/crew_profile.py:514](src/probos/crew_profile.py#L514). It returns `dict | None` — NOT a `CrewProfile` dataclass instance. Read the flag via `(prof or {}).get('vision_capable', False)`. Reference site: [src/probos/cognitive/counselor.py:784](src/probos/cognitive/counselor.py#L784) uses `self._crew_profiles.get_profile(agent_id)` (param-name discrepancy with the method signature's `agent_type` is a known cosmetic confusion — pass `agent.agent_type`). The dataclass `to_dict()`/`from_dict()` round-trip lives at [crew_profile.py:271 / 294](src/probos/crew_profile.py#L271) for serialization concerns.

## Files

- `src/probos/crew_profile.py` — `CrewProfile.vision_capable: bool = False`, update `to_dict()`/`from_dict()`.
- `src/probos/cognitive/standing_orders.py` (or wherever crew seed lives — Builder verifies) — flip Counselor + Architect to True.
- `src/probos/routers/agents.py` — gate around line 916 (`if image_ids:`).
- `src/probos/routers/chat.py` — gate inside the vision path for directed-mention case.
- `tests/test_ad720d2_vision_capable.py` (new) — 4 tests.

## Tests (≥4)

1. `test_crew_profile_vision_capable_round_trip` — round-trip via `to_dict()`/`from_dict()` preserves the field; default is False.
2. `test_agent_chat_vision_capable_false_routes_to_text_fallback` — patch a CrewProfile with `vision_capable=False`; assert image DM goes through `augment_prompt_with_attachment_text` (mocked) and `vision_messages` is never set on the IntentMessage.
3. `test_agent_chat_vision_capable_true_routes_to_vision_tier` — patch with `vision_capable=True`; assert `vision_messages` IS set and intent params carry `has_image_attachment=True`.
4. `test_default_crew_seed_counselor_and_architect_vision_capable` — load the default crew seed; assert Counselor.vision_capable is True, Architect.vision_capable is True, all others False.

## Out of scope (FORWARD MARKERS — file at wave close)

- **AD-720d-2.1: Captain approval flow** for enabling vision on a new agent (AD-718a-style propose/approve). File new GH issue at wave close.
- Cross-mesh vision capability federation.

## Acceptance

- Full test gate green. Focused gate green.
- AD-734 pre-commit hook passes.
- Engineering Principles compliance per `.github/copilot-instructions.md`.
- DECISIONS.md gets an AD-720d-2 entry.

## Commit

`AD-720d-2: per-agent vision_capable gating with Counselor+Architect default-True (Wave 154). Closes #564.`
