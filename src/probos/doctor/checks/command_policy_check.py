"""AD-1328 S2a (#1530): the command execution policy -- rules loaded, self-test, digest."""

from __future__ import annotations

from dataclasses import dataclass

from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check
from probos.execution.command_gate import describe_command_policy


@dataclass(frozen=True)
class _CommandPolicyCheck:
    name: str = "command_policy"

    async def run(self, ctx: DoctorContext) -> CheckResult:
        execution = getattr(ctx.config, "execution", None) if ctx.config is not None else None
        if execution is None:
            return CheckResult(
                outcome=CheckOutcome.WARN,
                message="Command policy: not checked, because the configuration did not load",
                remediation="Fix the configuration error reported above, then run probos doctor again.",
            )
        report = describe_command_policy(getattr(execution, "command_policy", None))
        if report.error is not None:
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message=f"Command policy: could not be checked ({report.error})",
                remediation="Correct execution.command_policy in the configuration file.",
            )
        if report.rule_count == 0:
            return CheckResult(
                outcome=CheckOutcome.OK,
                message="Command policy: none configured; run_command runs every command as it would without one",
            )
        dialects = ", ".join(r.dialect for r in report.reports)
        failures = [(r.dialect, failure) for r in report.reports for failure in r.failures]
        if failures:
            shown = "; ".join(f"under {dialect}: {failure.message}" for dialect, failure in failures[:3])
            more = f" (and {len(failures) - 3} more)" if len(failures) > 3 else ""
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message=f"Command policy: {report.rule_count} rules; self-test failed -- {shown}{more}",
                remediation=(
                    "Correct each named rule's pattern, example or host_executable path in execution.command_policy; "
                    f"ProbOS will not start until every rule's examples and pinned paths hold under {dialects}."
                ),
            )
        checked = sum(r.examples_checked for r in report.reports)
        return CheckResult(
            outcome=CheckOutcome.OK,
            message=(
                f"Command policy: {report.rule_count} rules, self-test passed under {dialects} "
                f"({checked} examples), digest {report.digest}"
            ),
        )


register_check(_CommandPolicyCheck())
