"""AD-1287 S2a: the slot boundary with a currency check, refusing a qualified profile whose skills or tools changed.

``admit_current_qualified_attempt`` runs, in order: the stored team spec (``slot_spec_unknown``), S1's
``check_slot_qualification`` (its codes, unchanged), ``profile_drift`` on the qualified profile (the first drift's
code), and only then ``teams.record_attempt``. A refusal raises ``SlotAdmissionRefused``, is logged at INFO and
records nothing.

``profile_drift`` compares each skill and tool a profile declares with what a ``ProfileComponentSource`` reports
now. ``RegistryComponentSource`` reads a skill catalog and a tool registry through two narrow ports: a skill must
still be in the catalog, pass ``validate_skill`` with no validation context (layer 1 only) and digest to its
declared ``resource_digest``; a tool must still be registered, and its schemas must digest to its declared
``schema_digest``.

Checked: skills and tool schemas. Not checked (declared only): the model, prompts, tool implementation digests,
the policy digest and the evaluation suite, so a change to one of those leaves a qualified reference admissible
here. The check holds as of its own reads: a component changed after them does not undo a recorded attempt, and
the two stores share no transaction (S1 D5). Nothing here records an invalidation or grants anything. Not wired:
AD-1288 commission admission is the intended caller.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from probos.cognitive.elastic_team import WorkerAttempt, is_sha256_ref
from probos.cognitive.execution_profile import ExecutionProfile
from probos.cognitive.profile_components import ComponentDigestError, skill_resource_digest, tool_schema_digest
from probos.cognitive.profile_qualification_store import (
    ProfileQualificationReader,
    SlotAdmissionRefused,
    TeamAttemptRecorder,
    check_slot_qualification,
)

logger = logging.getLogger(__name__)

ComponentKind = Literal["skill", "tool"]


class ComponentUnreadable(ValueError):
    """A live component exists but could not be digested; ``profile_drift`` reports it as unreadable."""


@dataclass(frozen=True)
class LiveSkill:
    """One skill as the catalog holds it now: its resource digest and whether ``validate_skill`` passes."""

    resource_digest: str
    structurally_valid: bool


@dataclass(frozen=True)
class ComponentDrift:
    """One declared component that is not current. ``live`` is None when it is missing or unreadable."""

    kind: ComponentKind
    key: str
    code: str
    declared: str
    live: str | None


class ProfileComponentSource(Protocol):
    """The live state ``profile_drift`` compares a profile with: one lookup per checked component kind."""

    async def skill_state(self, skill_name: str) -> LiveSkill | None: ...

    async def tool_schema_digest(self, tool_id: str) -> str | None: ...


class SkillCatalogPort(Protocol):
    """The two ``CognitiveSkillCatalog`` operations ``RegistryComponentSource`` reads."""

    def get_entry(self, name: str) -> Any: ...

    async def validate_skill(self, name: str, validation_context: dict | None = None) -> Any: ...


class ToolLookupPort(Protocol):
    """The one ``ToolRegistry`` operation ``RegistryComponentSource`` reads."""

    def get_tool(self, tool_id: str) -> Any: ...


class RegistryComponentSource:
    """A ``ProfileComponentSource`` over a skill catalog and a tool registry. It reads both and writes nothing."""

    def __init__(self, skills: SkillCatalogPort, tools: ToolLookupPort) -> None:
        self._skills = skills
        self._tools = tools

    async def skill_state(self, skill_name: str) -> LiveSkill | None:
        """``skill_name``'s live state, or None when the catalog holds no entry by that name.

        The directory is digested in a worker thread.

        Raises:
            ComponentUnreadable: the directory could not be digested (``ComponentDigestError`` or ``OSError``).
        """
        entry = self._skills.get_entry(skill_name)
        if entry is None:
            return None
        validation = await self._skills.validate_skill(skill_name)
        try:
            digest = await asyncio.to_thread(skill_resource_digest, Path(entry.skill_dir))
        except (ComponentDigestError, OSError) as exc:
            logger.warning(
                "AD-1287: skill %s could not be digested (%s); the slot boundary refuses profiles naming it",
                skill_name,
                exc,
            )
            raise ComponentUnreadable(skill_name) from exc
        return LiveSkill(digest, validation.valid is True)

    async def tool_schema_digest(self, tool_id: str) -> str | None:
        """``tool_id``'s live schema digest, or None when the registry holds no such tool.

        Raises:
            ComponentUnreadable: reading or digesting its schemas raised.
        """
        tool = self._tools.get_tool(tool_id)
        if tool is None:
            return None
        try:
            return tool_schema_digest(tool.input_schema, tool.output_schema)
        except Exception as exc:  # noqa: BLE001 -- log-and-degrade: a tool's schema property may raise anything; the degrade is a refusal
            logger.warning(
                "AD-1287: tool %s schemas could not be digested (%s); the slot boundary refuses profiles naming it",
                tool_id,
                exc,
            )
            raise ComponentUnreadable(tool_id) from exc


def _is_live_skill(value: object) -> bool:
    """True when ``value`` is exactly a ``LiveSkill`` with a 64-hex digest and a bool validity."""
    return (
        type(value) is LiveSkill
        and is_sha256_ref(value.resource_digest)
        and type(value.structurally_valid) is bool
    )


async def profile_drift(profile: ExecutionProfile, source: ProfileComponentSource) -> tuple[ComponentDrift, ...]:
    """Each skill, then each tool, of ``profile`` (in the profile's key order) that ``source`` reports as not current.

    Per skill, the first that applies: ``component_unreadable_skill``, ``component_missing_skill``,
    ``component_structurally_invalid_skill``, ``component_drift_skill`` (another resource digest). Per tool:
    ``component_unreadable_tool``, ``component_missing_tool``, ``component_drift_tool_schema``. Empty when every
    checked component is current. Asks ``source`` once per component and writes nothing.

    Raises:
        TypeError: ``profile_currency_type_invalid`` when ``profile`` is not an ``ExecutionProfile``;
            ``profile_component_source_invalid`` when ``source`` answers anything but None, a well-formed
            ``LiveSkill`` or a 64-hex digest (an exact ``LiveSkill`` built without its fields raises
            ``AttributeError`` instead).
        Any other error ``source`` raises, unchanged.
    """
    if type(profile) is not ExecutionProfile:
        raise TypeError("profile_currency_type_invalid")
    drifts: list[ComponentDrift] = []
    for skill in profile.skills:
        name, declared = skill.skill_name, skill.resource_digest
        try:
            live = await source.skill_state(name)
        except ComponentUnreadable:
            drifts.append(ComponentDrift("skill", name, "component_unreadable_skill", declared, None))
            continue
        if live is None:
            drifts.append(ComponentDrift("skill", name, "component_missing_skill", declared, None))
        elif not _is_live_skill(live):
            raise TypeError("profile_component_source_invalid")
        elif not live.structurally_valid:
            drifts.append(
                ComponentDrift("skill", name, "component_structurally_invalid_skill", declared, live.resource_digest)
            )
        elif live.resource_digest != declared:
            drifts.append(ComponentDrift("skill", name, "component_drift_skill", declared, live.resource_digest))
    for tool in profile.tools:
        tool_id, declared = tool.tool_id, tool.schema_digest
        try:
            live_schema = await source.tool_schema_digest(tool_id)
        except ComponentUnreadable:
            drifts.append(ComponentDrift("tool", tool_id, "component_unreadable_tool", declared, None))
            continue
        if live_schema is None:
            drifts.append(ComponentDrift("tool", tool_id, "component_missing_tool", declared, None))
        elif not is_sha256_ref(live_schema):
            raise TypeError("profile_component_source_invalid")
        elif live_schema != declared:
            drifts.append(ComponentDrift("tool", tool_id, "component_drift_tool_schema", declared, live_schema))
    return tuple(drifts)


async def admit_current_qualified_attempt(
    qualifications: ProfileQualificationReader,
    teams: TeamAttemptRecorder,
    components: ProfileComponentSource,
    attempt: WorkerAttempt,
) -> WorkerAttempt:
    """Record ``attempt`` only when its exact profile is qualified for its slot and its skills and tools are current.

    In order: ``teams.get_team_spec`` (``slot_spec_unknown``), ``check_slot_qualification`` (its codes, unchanged),
    ``profile_drift`` on the qualified profile (the first drift's code), then ``teams.record_attempt``, which applies
    AD-1286's own rules. A refusal records nothing and is logged at INFO. The checks run on every call, an identical
    replay included, so recovery reads ``get_attempt`` rather than re-admitting (S1 O-1).

    Raises:
        TypeError: ``elastic_attempt_type_invalid``, or what ``profile_drift`` raises.
        SlotAdmissionRefused: ``slot_spec_unknown``, a ``check_slot_qualification`` code or a drift code.
        Whatever ``teams.record_attempt`` raises, unchanged.
    """
    if type(attempt) is not WorkerAttempt:
        raise TypeError("elastic_attempt_type_invalid")
    attempt = WorkerAttempt.model_validate(attempt)
    try:
        spec = await teams.get_team_spec(attempt.team_spec_ref)
        if spec is None:
            raise SlotAdmissionRefused("slot_spec_unknown")
        qualification = await check_slot_qualification(qualifications, spec, attempt.slot_id, attempt.execution_profile_ref)
        drifts = await profile_drift(qualification.profile, components)
        if drifts:
            raise SlotAdmissionRefused(drifts[0].code)
    except SlotAdmissionRefused as refused:
        logger.info(
            "AD-1287: slot %s refused execution profile %s (%s); no worker attempt was recorded",
            attempt.slot_id,
            attempt.execution_profile_ref,
            refused,
        )
        raise
    return await teams.record_attempt(attempt)
