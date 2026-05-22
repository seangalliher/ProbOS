"""AD-801: per-tier LLM reachability (preserves AD-484 behavior).

Emits one result *per configured tier*. The runner is general-purpose
(one CheckResult per check), so this single check yields a roll-up
result; per-tier detail is included in the message body.
"""

from __future__ import annotations

from dataclasses import dataclass

from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check

# AD-732 + AD-742a: vision / vision_fast tiers are honest-degrade — unset
# `model` means the tier is intentionally disabled, not broken.
_LLM_TIERS = ("fast", "standard", "deep", "vision", "vision_fast")


@dataclass(frozen=True)
class _LLMCheck:
    name: str = "llm_tiers"

    async def run(self, ctx: DoctorContext) -> CheckResult:
        if ctx.config is None:
            return CheckResult(
                outcome=CheckOutcome.WARN,
                message="LLM tiers: skipped (config unavailable)",
            )
        try:
            from probos.cognitive.llm_client import OpenAICompatibleClient
            client = OpenAICompatibleClient(config=ctx.config.cognitive)
            connectivity = await client.check_connectivity()
            await client.close()
        except Exception as exc:
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message=f"LLM connectivity probe failed: {type(exc).__name__}",
                remediation=f"Check LLM endpoints in config.cognitive ({exc})",
            )

        unreachable: list[str] = []
        configured_count = 0
        for tier in _LLM_TIERS:
            tc = ctx.config.cognitive.tier_config(tier)
            if not tc.get("model"):
                continue
            configured_count += 1
            if not connectivity.get(tier):
                unreachable.append(f"{tier}@{tc['base_url']}")

        if not configured_count:
            return CheckResult(
                outcome=CheckOutcome.WARN,
                message="LLM tiers: none configured",
            )
        if unreachable:
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message=f"LLM tiers unreachable: {', '.join(unreachable)}",
                remediation="Verify the endpoint URLs in config.cognitive and that the provider is running.",
            )
        return CheckResult(
            outcome=CheckOutcome.OK,
            message=f"LLM tiers reachable ({configured_count} configured)",
        )


register_check(_LLMCheck())
