# AD-730-5 — Per-agent_type vision tier override (Wave 154)

**GH:** [#635](https://github.com/seangalliher/ProbOS/issues/635). **Status:** Buildable.

**Depends on AD-720d-2 (#564)** — must land first (uses the same `vision_capable` lookup site as the override resolution point).

## Problem

AD-730 routes all agents through `runtime.config.attachments.vision_tier` (a single global tier). A future Imaging Officer / Diagnostician variant may want a medical-imaging or satellite-imagery specialist model. We need a per-agent_type override map.

## Scope

1. Extend `AttachmentsConfig` (locate via `grep -rn "class AttachmentsConfig" src/probos/config.py`) with:
   ```python
   vision_tier_overrides: dict[str, str] = Field(default_factory=dict)
   ```
   Maps `agent_type` (e.g. `"Counselor"`, `"Diagnostician"`) to a tier name registered in the LLM client (`"vision"`, `"vision_medical"`, etc.). Empty default = no overrides; behavior identical to today.
2. Add a helper at module scope of `src/probos/cognitive/vision_dispatch.py`:
   ```python
   def resolve_vision_tier_for_agent(
       attach_cfg: Any, agent_type: str, default_tier: str
   ) -> str:
       """AD-730-5: resolve the vision tier for a specific agent_type.

       Returns the override from ``attach_cfg.vision_tier_overrides[agent_type]``
       when present; otherwise ``default_tier``. Pure function.
       """
   ```
3. Call site update — three places must use this helper instead of reading `cfg_attach.vision_tier` directly:
   - `routers/agents.py` `agent_chat` (line ~925 where `tier = cfg_attach.vision_tier` happens) — pass `agent.agent_type` as the second arg.
   - `routers/chat.py` `/api/chat` vision path (line ~310 where `tier = cfg_attach.vision_tier`) — for directed-mention case, pass the resolved target's `agent_type`; for untargeted, pass `""` (helper returns default).
   - `cognitive/cognitive_agent.py` `_decide_*` vision routing (line 2124 where `_resolved_vision_tier` is assigned) — pass `self.agent_type` (BaseAgent attribute) as the second arg.
4. Health-status probe: when override tier is configured but not registered in `runtime.llm_client.get_health_status()["tiers"]`, log a warning and fall back to the default. Tier-2 log-and-degrade.

## Files

- `src/probos/config.py` — `AttachmentsConfig.vision_tier_overrides`.
- `src/probos/cognitive/vision_dispatch.py` — `resolve_vision_tier_for_agent`.
- `src/probos/routers/agents.py` — use helper.
- `src/probos/routers/chat.py` — use helper for directed-mention case.
- `src/probos/cognitive/cognitive_agent.py` — use helper at the `_resolved_vision_tier` site.
- `tests/test_ad730_5_vision_tier_override.py` (new) — 3 tests.

## Tests (≥3)

1. `test_resolve_vision_tier_no_override_returns_default` — empty overrides dict, returns `default_tier`.
2. `test_resolve_vision_tier_override_hits` — `vision_tier_overrides={"Diagnostician": "vision_medical"}`, agent_type="Diagnostician" → returns `"vision_medical"`.
3. `test_resolve_vision_tier_override_for_unmapped_agent_type` — overrides has `Counselor` but not `Diagnostician`; resolving Diagnostician returns default. (Validates dict lookup, not regex.)

## Out of scope

- Adding a second LLM endpoint to `system.yaml` (ops decision; v1 only adds the config plumbing).
- Registering a `vision_medical` tier in the LLM client (separate AD when a real model lands).

## Acceptance

- Full test gate green.
- AD-734 pre-commit hook passes (no shape changes).
- DECISIONS.md gets an AD-730-5 entry.

## Commit

`AD-730-5: per-agent_type vision tier override (Wave 154). Closes #635.`
