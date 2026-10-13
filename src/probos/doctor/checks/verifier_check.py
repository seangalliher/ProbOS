"""AD-1327 (#1511): does the crew verifier judge with a model the crew also runs on?

Reads the configuration only and sends no request (``llm_tiers`` probes the
verifier tier when ``cognitive.llm_model_verifier`` is set). With the crew
orchestrator off the verifier never runs, so the result is OK and says so. With
it on: OK when the judge model is of a different family from every crew tier's
model; WARN for the same model, the same family, or a family not known. Never
FAIL: a shared judge weakens verification, it does not break the installation.
Each configured key's forms are redacted from the message, as in ``llm_tiers``.
"""

from __future__ import annotations

from dataclasses import dataclass

from probos import provider_setup as ps
from probos.cognitive.verifier_independence import (
    VERIFIER_REMEDIATION,
    VerifierJudgePolicy,
    verifier_independence_report,
)
from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check


@dataclass(frozen=True)
class _VerifierIndependenceCheck:
    name: str = "verifier_independence"

    async def run(self, ctx: DoctorContext) -> CheckResult:
        if ctx.config is None:
            return CheckResult(
                outcome=CheckOutcome.WARN,
                message="Crew verifier independence: skipped (config unavailable)",
            )
        cognitive = ctx.config.cognitive
        independence, detail = verifier_independence_report(VerifierJudgePolicy.from_cognitive(cognitive))
        detail = ps.redact_keys(detail, ps.configured_api_keys(cognitive))
        if not ctx.config.agentic_dispatch.orchestrator_enabled:
            return CheckResult(
                outcome=CheckOutcome.OK,
                message=f"Crew verifier: not in use (agentic_dispatch.orchestrator_enabled is off); configured: {detail}",
            )
        if independence == "independent":
            return CheckResult(outcome=CheckOutcome.OK, message=f"Crew verifier: {detail}")
        return CheckResult(
            outcome=CheckOutcome.WARN,
            message=f"Crew verifier: {detail}",
            remediation=VERIFIER_REMEDIATION,
        )


register_check(_VerifierIndependenceCheck())
