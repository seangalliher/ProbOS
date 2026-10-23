"""BF-917 (#1625): every skill a role template names is a registered skill definition.

Reads ``config/ontology`` through the real ``OntologyLoader`` with no data
directory, so it creates and writes nothing (the loader persists an instance id
only under a data directory). Each finding is a WARN naming the post, never a FAIL,
and the check repairs nothing. An ontology the loader cannot read (a template entry
without ``min_proficiency``, say) raises instead, which the doctor runner reports as
FAIL, as it does for any check that raises. "Registered" is what ``SkillRegistry.register_builtins``
registers at boot (``builtin_skill_definitions``). The CI tests run the same audit
over the shipped ontology, so this check finds an operator's local edit.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check

# src/probos/doctor/checks/ -> the repository root, as startup/communication.py finds it.
_ONTOLOGY_DIR = Path(__file__).resolve().parents[4] / "config" / "ontology"
_REMEDIATION = (
    "Correct the skill id in config/ontology/skills.yaml, or register the skill in "
    "ONTOLOGY_TEMPLATE_SKILLS (probos/skill_framework.py), then restart ProbOS."
)


@dataclass(frozen=True)
class _RoleTemplateCheck:
    name: str = "role_templates"
    ontology_dir: Path = _ONTOLOGY_DIR

    async def run(self, ctx: DoctorContext) -> CheckResult:
        if not self.ontology_dir.is_dir():
            return CheckResult(CheckOutcome.OK, f"Role templates: no ontology at {self.ontology_dir}")
        from probos.ontology.loader import OntologyLoader
        from probos.role_template_audit import unregistered_template_skills
        from probos.skill_framework import builtin_skill_definitions

        loader = OntologyLoader(self.ontology_dir)
        await loader.initialize()
        registered = frozenset(d.skill_id for d in builtin_skill_definitions())
        findings = [
            f"{post}: template skill {skill} is not a registered skill definition"
            for post, skill in unregistered_template_skills(loader.role_templates, registered)
        ]
        if not findings:
            return CheckResult(
                CheckOutcome.OK,
                f"Role templates: {len(loader.role_templates)} templates, every template skill registered",
            )
        return CheckResult(
            CheckOutcome.WARN,
            f"Role templates: {len(findings)} problem(s) in config/ontology",
            _REMEDIATION,
            "\n".join(findings),
        )


register_check(_RoleTemplateCheck())
