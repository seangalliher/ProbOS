"""AD-721i E4: utility-tier host agent for the headless Blender renderer.

``AvatarRendererAgent`` exposes a ``regenerate_avatar`` intent. Captain
approval (AD-721d) is the gate, so ``requires_consensus=False``. On render
success, the draft VRM is moved atomically (``os.replace``) into the
canonical avatar cache at ``<avatars_dir>/<agent_id>.vrm`` — overwrite is
the cache-invalidation contract; v1 has no ``.vrm.bak`` rotation.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from probos.substrate.agent import BaseAgent
from probos.types import (
    CapabilityDescriptor,
    IntentDescriptor,
    IntentMessage,
    IntentResult,
)

logger = logging.getLogger(__name__)


class AvatarRendererAgent(BaseAgent):
    """Renders an approved AvatarDSL to ``.vrm`` via the headless Blender backend."""

    agent_type: str = "avatar_renderer"
    tier = "utility"
    default_capabilities = [
        CapabilityDescriptor(
            can="regenerate_avatar",
            detail=(
                "Render an agent's approved AvatarDSL into a .vrm via headless "
                "Blender. Captain approval gates this; the renderer is deterministic."
            ),
        ),
    ]
    initial_confidence: float = 0.85
    intent_descriptors = [
        IntentDescriptor(
            name="regenerate_avatar",
            params={
                "agent_id": "agent whose avatar to (re)render",
                "dsl_dict": "AvatarDSL serialised as a dict (matching AvatarDSL.model_dump())",
            },
            description=(
                "Render an approved AvatarDSL to VRM via the headless Blender "
                "backend. Output cached at <avatars_dir>/<agent_id>.vrm via "
                "atomic os.replace. Returns IntentResult(success=False) when "
                "Blender is absent or renderer disabled — DSL is preserved by "
                "AD-721d's persistence layer regardless."
            ),
            requires_consensus=False,
            requires_reflect=False,
            tier="utility",
        ),
    ]
    _handled_intents = {"regenerate_avatar"}

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        if intent.intent not in self._handled_intents:
            return None
        observation = await self.perceive(intent.__dict__)
        if observation is None:
            return None
        plan = await self.decide(observation)
        if plan is None:
            return None
        result = await self.act(plan)
        report = await self.report(result)
        success = bool(report.get("success", False))
        self.update_confidence(success)
        return IntentResult(
            intent_id=intent.id,
            agent_id=self.id,
            success=success,
            result=report.get("data"),
            error=report.get("error"),
            confidence=self.confidence,
        )

    async def perceive(self, intent: dict[str, Any]) -> Any:
        if intent.get("intent") not in self._handled_intents:
            return None
        return {"params": intent.get("params", {}) or {}}

    async def decide(self, observation: Any) -> Any:
        params = observation["params"]
        agent_id = params.get("agent_id") or ""
        dsl_dict = params.get("dsl_dict")
        if not isinstance(agent_id, str) or not agent_id.strip():
            return None
        if not isinstance(dsl_dict, dict):
            return None
        return {"agent_id": agent_id.strip(), "dsl_dict": dsl_dict}

    async def act(self, plan: Any) -> Any:
        from probos.avatars.blender_renderer import (
            BlenderNotFoundError,
            BlenderRenderError,
            BlenderRenderer,
        )
        from probos.avatars.dsl import AvatarDSL

        runtime = self._runtime
        if runtime is None:
            return {"success": False, "error": "no runtime reference"}
        cfg = getattr(runtime, "config", None)
        avatars_cfg = getattr(cfg, "avatars", None) if cfg else None
        if avatars_cfg is None:
            return {"success": False, "error": "AvatarsConfig missing on runtime.config"}

        if not getattr(avatars_cfg, "renderer_enabled", False):
            logger.info(
                "AD-721i: regenerate_avatar requested for %s but renderer_enabled=False; "
                "DSL persists via AD-721d, no VRM produced",
                plan["agent_id"],
            )
            return {"success": False, "error": "renderer disabled"}

        # Defense-in-depth: re-validate the DSL at the intent layer too.
        try:
            dsl = AvatarDSL.model_validate(plan["dsl_dict"])
        except Exception as exc:
            logger.warning(
                "AD-721i: regenerate_avatar rejected for %s — invalid DSL: %s",
                plan["agent_id"], exc,
            )
            return {"success": False, "error": f"invalid DSL: {exc}"}

        # Resolve avatars + drafts dirs through the existing path-traversal-safe gate.
        from probos.routers.system import _resolve_avatars_dir
        avatars_dir = _resolve_avatars_dir(avatars_cfg.avatars_dir)
        drafts_dir = _resolve_avatars_dir(avatars_cfg.dsl_drafts_dir)

        renderer = BlenderRenderer(
            blender_path=avatars_cfg.blender_path or None,
            timeout_s=int(avatars_cfg.blender_render_timeout_s),
            drafts_dir=drafts_dir,
            max_vrm_size_bytes=int(avatars_cfg.max_vrm_size_bytes),
            avatars_dir=avatars_dir,
            procedural_fallback=bool(avatars_cfg.procedural_base_mesh_fallback),
        )

        try:
            draft_vrm = await renderer.render(dsl, plan["agent_id"])
        except BlenderNotFoundError as exc:
            logger.warning(
                "AD-721i: Blender not found while rendering %s — DSL preserved at drafts; "
                "operator must install Blender ≥ 4.0 + saturday06 VRM-Addon",
                plan["agent_id"],
            )
            return {"success": False, "error": f"blender_not_found: {exc}"}
        except BlenderRenderError as exc:
            logger.warning(
                "AD-721i: render failed for %s — %s; DSL preserved at drafts",
                plan["agent_id"], exc,
            )
            return {"success": False, "error": f"render_failed: {exc}"}

        # Atomic move into canonical cache. ``os.replace`` is atomic on both
        # POSIX and Windows. Cache invalidation = overwrite.
        canonical = avatars_dir / f"{plan['agent_id']}.vrm"
        try:
            avatars_dir.mkdir(parents=True, exist_ok=True)
            os.replace(draft_vrm, canonical)
        except OSError as exc:
            logger.error(
                "AD-721i: atomic replace draft→canonical failed for %s "
                "(draft=%s canonical=%s): %s",
                plan["agent_id"], draft_vrm, canonical, exc,
            )
            return {"success": False, "error": f"atomic_replace_failed: {exc}"}

        return {"success": True, "data": {"vrm_path": str(canonical)}}

    async def report(self, result: Any) -> dict[str, Any]:
        if not isinstance(result, dict):
            return {"success": False, "error": "report received non-dict result"}
        return result


__all__ = ["AvatarRendererAgent"]
