# AD-1287 S2a (#1334): live skill and tool-schema digests, and a slot boundary that refuses a qualified profile whose skills or tools changed

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-14
**Status:** build-ready (slice S2a of four: S1 shipped, S2a, S2b, S3). Base `origin/main` `03e5500e`. Branch `feat/ad1287-s2-20261014-03e5500e`.
**Issue / epic:** #1334 / #1332. AD-1287 is already allocated; this slice allocates no AD or BF number (ceiling AD-1327 from all three sources, `scripts/ad_ceiling.py`, 2026-10-14).
**Depends on:** AD-1287 S1 (shipped, merge `4efabdfb`). **Dependents:** AD-1288 #1335 (commission admission calls `admit_current_qualified_attempt`, amended O-1), S2b, S3.
**Estimated tests:** about 16 (M1) + 17 (M2), several parametrized, plus one edit to an S1 test.
**Milestones:** M1 producer tests, M2 source/drift/gate tests and the chain, M3 mutation campaign of record, M4 trackers. Briefs follow `=== BUILDER BRIEFS ===`. Source is installed from this contract; Builders write tests only.

One-line summary: pure digests of a skill directory and of a tool's declared schemas, a `ProfileComponentSource` over the skill catalog and tool registry, `profile_drift`, and `admit_current_qualified_attempt` (S1's slot boundary plus a currency check between qualification and recording). Built and unwired.

---

## Problem

- S1's gate admits a qualified reference after a live component changes, because S1 has no live component source (O-2, `logs/architect/issue-1334.md:63`). The skills and tools a profile names are compared with nothing: `check_slot_qualification` reads only stored evidence (`profile_qualification_store.py:784-812`) and `admit_qualified_attempt` then records (`:815-848`).
- No owner computes a skill digest (`skill_catalog.py`: 0 hits for `hashlib|digest|sha256`) or a tool schema digest (`tools/protocol.py:126-134` exposes `input_schema`/`output_schema` only).
- `EvaluationRecord.structurally_valid` is self-reported (`execution_profile.py:214`; S1 blind spot 8). `CognitiveSkillCatalog.validate_skill` exists (`skill_catalog.py:550-627`) and nothing consults it at the slot boundary.

## Solution overview (S2a)

1. **`src/probos/cognitive/profile_components.py` (new, pure):** `skill_resource_digest(Path)` and `tool_schema_digest(input_schema, output_schema)`, each a domain-separated sha256 over RFC 8785 bytes; `ComponentDigestError`.
2. **`src/probos/cognitive/profile_currency.py` (new):** `ProfileComponentSource` protocol, `RegistryComponentSource` over two narrow ports (catalog: `get_entry`, `validate_skill`; registry: `get_tool`), `profile_drift`, `admit_current_qualified_attempt`.
3. **S1 test #16 widened** (Section 3) so the new modules are owners of the scan and the new gate is a scanned name.
4. **Chain proof (M2 #10):** a real catalog and a real `ToolRegistry` produce the digests; the profile is registered and evaluated on a real store file; both stores restart; the gate admits nothing after a skill file changes (no attempt row), and admits the exact profile once the file is restored.

Nothing constructs `RegistryComponentSource` or calls the new gate in production.

## Slicing decision

| Rank | Option | Verdict |
|---|---|---|
| 1 | **S2a** (this): skill + tool-schema producers, the source, `profile_drift` and the currency gate, as one producer-to-consumer chain. **S2b**: model and policy producers (the model has no version owner, the policy no digest owner, so each needs a design decision) and drift recording (`component_drift_<kind>` invalidations through S1's `invalidate_profile`). **S3**: outcome learning (O-3) | **Chosen.** Each slice is a whole chain. S2a is the safety half of O-2 for the two components that have a live owner. It edits no S1 source, so S1's 60-mutant campaign of record stands |
| 2 | One S2 slice: producers for all components, drift recording and the gate | Rejected: it bundles two open design questions (A7, A8) with the safety fix; AD-1326's seven rounds are the measured cost of a slice that grows under review |
| 3 | S2a = producers only, S2b = gate | Rejected: S2a would be a half-chain (a producer with no consumer) |
| 4 | S3 before S2 | Rejected: O-2 is the safety half and has to land before AD-1288 wires the gate |

**Closure.** #1334 is closable after the last of S2b and S3 lands (they are independent; S2b first is recommended). Prompts and tool implementation digests stay declared-only even then (no live owner exists, A2/A9); that is an honest limit of the acceptance item "invalidate or require requalification when any bound component changes", carried as R-5, not a gap S2b can close.

## Decisions and ranked options

### D1. Where the currency check lives

| Rank | Option | Verdict |
|---|---|---|
| 1 | A new module and a new gate, `admit_current_qualified_attempt`, composed from S1's public `check_slot_qualification` and the `TeamAttemptRecorder` port. O-1 is amended: AD-1288 calls the new gate | **Chosen.** No S1 source edit; S1's campaign of record and 16 call sites stay valid. Cost: five lines restate `admit_qualified_attempt`'s spec lookup (accepted; calling it would need a second qualification read or an S1 edit) |
| 2 | Add a required `components` argument to S1's `admit_qualified_attempt` | Rejected for now: it edits the campaigned store and every S1 gate test. Revisit in AD-1288 (R-4) |

**R-4 (new residual):** S1's `admit_qualified_attempt` stays callable with no currency check. Both gates are unwired (S1 #16, widened in Section 3); AD-1288 must call the S2a gate and may retire S1's.

### D2. Which components S2a checks

| Rank | Option | Verdict |
|---|---|---|
| 1 | **Skills** (present in the catalog, `validate_skill(name)` valid with no validation context, resource digest equal) and **tool schemas** (registered, schema digest equal). Model, prompts, tool implementation, policy and evaluation suite are declared only, and every docstring says so | **Chosen.** They are the two components with a live owner |
| 2 | Check all six; a component with no live source refuses | Rejected: no source exists for prompts or tool implementations (A2, A9), so every profile with either would be refused for ever |
| 3 | Check all six; a component with no live source passes | Rejected: it reports currency it never checked |

### D3. Skill directory digest

| Rank | Option | Verdict |
|---|---|---|
| 1 | Manifest `{"files": [{"path", "sha256", "size"}...]}`, one entry per regular file, relative POSIX path, ascending by code point, RFC 8785, `sha256(SKILL_RESOURCES_DOMAIN + bytes)`. Symlinks and junctions refused, never followed; non-regular entries refused; at most 256 files, 8 MiB, depth 8; bytes read with a bounded `read`. Directories are not entries, so an empty directory changes nothing | **Chosen.** Go's `dirhash` (per-file sha256 over sorted names) plus OCI's size-with-digest, in the in-house canonical form |
| 2 | Go `h1:` text summary | Rejected: a line format needs a newline ban on names; RFC 8785 is already the identity scheme |
| 3 | git tree hash | Rejected: needs git, hashes mode bits, and skills imported at runtime may not be in git |

### D4. Tool schema digest

| Rank | Option | Verdict |
|---|---|---|
| 1 | One digest over `{"input_schema", "output_schema"}`, both exactly `dict`; every node exactly `dict` (str keys) / `list` / `tuple` / `str` / `int` / `float` / `bool` / `None`; depth 32, 10,000 nodes; any canonicaliser `ValueError` (NaN, infinity, an int outside the I-JSON range, a lone surrogate, `jcs.py:66-71`) refused | **Chosen.** Exact types stop an enum member hashing as its text. Floats can occur in a schema (`minimum: 0.5`); they reach only the digest material, so the profile identity stays float-free |
| 2 | `isinstance` acceptance | Rejected: a `str` subclass would be digested as text (Architect standing order 4) |

### D5. Gate order and codes

`get_team_spec` -> `slot_spec_unknown`; `check_slot_qualification` -> its codes, unchanged; `profile_drift` -> the first drift's code; then `record_attempt`. Qualification runs first, so the components are read only for a profile that is otherwise admissible (M2 #12), and an unqualified profile reports S1's code. Drift codes: `component_unreadable_skill`, `component_missing_skill`, `component_structurally_invalid_skill`, `component_drift_skill`, `component_unreadable_tool`, `component_missing_tool`, `component_drift_tool_schema`. Each one matches `_REASON_RE` (`profile_qualification_store.py:84`), so S2b can record it as an invalidation reason unchanged.

### D6. Drift is refused, not recorded, in S2a

Recording needs an idempotent invalidation-id scheme and a caller that sweeps; both belong to S2b. S2a writes nothing anywhere except through `teams.record_attempt` after every check passes.

### D7. Blocking reads and cancellation

The directory digest runs in `asyncio.to_thread`. `CancelledError` propagates (nothing here catches `BaseException`); a cancelled call may leave the worker thread to finish its reads, and it writes nothing. A refusal is decided as of the gate's own reads; a component changed afterwards does not undo a recorded attempt (as S1 D5).

### D8. Authority

No field of `LiveSkill` or `ComponentDrift` has a name containing `scope`, `rank`, `lease`, `grant`, `authority` or `permission`. `profile_components` imports only `probos.cognitive.elastic_team` from ProbOS. `profile_currency` imports only `elastic_team`, `execution_profile`, `profile_components` and `profile_qualification_store`, and never `probos.tools` or `skill_catalog` (it depends on the ports). M1 #13 and M2 #16 test this.

### D9. Failure tiers

| Condition | Tier | Behaviour |
|---|---|---|
| Wrong argument type | Propagate | `TypeError` with a stable code |
| Skill tree a link, non-regular or over a bound; a schema not exactly JSON-shaped | Propagate from the producer | `ComponentDigestError(code)` |
| The source cannot digest a skill (`ComponentDigestError` or `OSError`) or a tool (any `Exception`, a tool property included) | Log-and-degrade; the degrade is a refusal | one WARNING, `ComponentUnreadable`; `profile_drift` reports `component_unreadable_<kind>` |
| A source answers a malformed value | Propagate | `TypeError("profile_component_source_invalid")` |
| Any other error from a source or the producers | Propagate | unchanged; nothing is recorded |
| A refusal at the gate | Propagate | `SlotAdmissionRefused(code)`, one INFO log, `record_attempt` not called |

---

## Section 0: Event types

None.

### Section 1 -- NEW `src/probos/cognitive/profile_components.py`

```python
"""AD-1287 S2a: digests of two execution-profile components, computed from what is on disk or registered now.

``skill_resource_digest`` digests one cognitive skill's directory: each regular file under it by relative POSIX
path, sha256 and size in bytes, ascending by path, as RFC 8785 bytes under ``SKILL_RESOURCES_DOMAIN``. A symbolic link
or junction at the root or below it, an entry that is neither a regular file nor a directory, or a tree beyond the
file-count, byte or depth bound is refused with ``ComponentDigestError``; the enumeration never follows a link. The
files are then opened by path, so a link created after the enumeration and before a file is opened is not detected,
and that read goes where the path then leads.
Directories are not entries, so an empty directory does not change the digest. Bytes are digested as stored, so a
checkout with other line endings gives another digest.

``tool_schema_digest`` digests a tool's declared ``input_schema`` and ``output_schema`` together, as RFC 8785 bytes
under ``TOOL_SCHEMA_DOMAIN``. Both must be a ``dict``. Every value inside must be exactly a ``dict`` with ``str``
keys, a ``list`` or ``tuple``, a ``str``, an ``int``, a ``float``, a ``bool`` or ``None`` (a subclass such as an
enum member is refused), within the depth and node bounds, and canonicalisable.

Nothing here stores, decides or grants anything; ``profile_currency`` is the consumer.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Final

from probos.cognitive.elastic_team import canonicalize_projection

SKILL_RESOURCES_DOMAIN: Final = b"probos.execution_profile/skill_resources/v1\x00"
TOOL_SCHEMA_DOMAIN: Final = b"probos.execution_profile/tool_schema/v1\x00"

# bounds; not Final so a test can lower them (the S1 store's ``_MAX_SCAN`` convention)
MAX_SKILL_FILES = 256
MAX_SKILL_BYTES = 8 * 1024 * 1024
MAX_SKILL_DEPTH = 8
MAX_SCHEMA_DEPTH = 32
MAX_SCHEMA_NODES = 10_000

_JSON_SCALARS: Final = (str, int, float, bool)


class ComponentDigestError(ValueError):
    """A component cannot be digested under this module's rules; ``str(exc)`` is the stable code."""


def _is_link(entry: os.DirEntry[str]) -> bool:
    return entry.is_symlink() or entry.is_junction()


def _skill_files(root: Path) -> list[tuple[str, Path]]:
    """Every regular file under ``root`` as ``(relative POSIX path, path)``, ascending by relative path."""
    found: list[tuple[str, Path]] = []
    pending: list[tuple[Path, str, int]] = [(root, "", 0)]
    while pending:
        directory, prefix, depth = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                relative = prefix + entry.name
                if _is_link(entry):
                    raise ComponentDigestError("skill_resource_link_refused")
                if entry.is_dir(follow_symlinks=False):
                    if depth + 1 > MAX_SKILL_DEPTH:
                        raise ComponentDigestError("skill_resource_limit")
                    pending.append((Path(entry.path), relative + "/", depth + 1))
                elif entry.is_file(follow_symlinks=False):
                    found.append((relative, Path(entry.path)))
                    if len(found) > MAX_SKILL_FILES:
                        raise ComponentDigestError("skill_resource_limit")
                else:
                    raise ComponentDigestError("skill_resource_not_regular")
    found.sort(key=lambda item: item[0])
    return found


def skill_resource_digest(skill_dir: Path) -> str:
    """The resource digest of the skill directory ``skill_dir``, read now (see the module docstring).

    Raises:
        TypeError: ``skill_resource_dir_invalid`` when ``skill_dir`` is not a ``Path``.
        ComponentDigestError: ``skill_resource_dir_invalid`` (not a directory, or a link),
            ``skill_resource_link_refused``, ``skill_resource_not_regular`` or ``skill_resource_limit``.
        OSError: a directory or file could not be read.
        ValueError: a path the canonicaliser cannot encode (a lone surrogate).
    """
    if not isinstance(skill_dir, Path):
        raise TypeError("skill_resource_dir_invalid")
    if skill_dir.is_symlink() or skill_dir.is_junction() or not skill_dir.is_dir():
        raise ComponentDigestError("skill_resource_dir_invalid")
    manifest: list[dict[str, Any]] = []
    total = 0
    for relative, path in _skill_files(skill_dir):
        remaining = MAX_SKILL_BYTES - total
        with path.open("rb") as handle:
            data = handle.read(remaining + 1)
        if len(data) > remaining:
            raise ComponentDigestError("skill_resource_limit")
        total += len(data)
        manifest.append({"path": relative, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)})
    return hashlib.sha256(SKILL_RESOURCES_DOMAIN + canonicalize_projection({"files": manifest})).hexdigest()


def _check_json(value: Any, depth: int, budget: list[int]) -> None:
    """Refuse ``value`` unless it is exactly JSON-shaped within the bounds; ``budget[0]`` counts the nodes left."""
    budget[0] -= 1
    if budget[0] < 0 or depth > MAX_SCHEMA_DEPTH:
        raise ComponentDigestError("tool_schema_invalid")
    kind = type(value)
    if kind is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ComponentDigestError("tool_schema_invalid")
            _check_json(item, depth + 1, budget)
    elif kind is list or kind is tuple:
        for item in value:
            _check_json(item, depth + 1, budget)
    elif kind not in _JSON_SCALARS and value is not None:
        raise ComponentDigestError("tool_schema_invalid")


def tool_schema_digest(input_schema: Any, output_schema: Any) -> str:
    """The schema digest of a tool declaring ``input_schema`` and ``output_schema`` (see the module docstring).

    Raises:
        ComponentDigestError: ``tool_schema_invalid``.
    """
    budget = [MAX_SCHEMA_NODES]
    for schema in (input_schema, output_schema):
        if type(schema) is not dict:
            raise ComponentDigestError("tool_schema_invalid")
        _check_json(schema, 1, budget)
    try:
        canonical = canonicalize_projection({"input_schema": input_schema, "output_schema": output_schema})
    except ValueError as exc:  # NaN or an infinity, an int outside the I-JSON range, or a lone surrogate
        raise ComponentDigestError("tool_schema_invalid") from exc
    return hashlib.sha256(TOOL_SCHEMA_DOMAIN + canonical).hexdigest()
```

### Section 2 -- NEW `src/probos/cognitive/profile_currency.py`

```python
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
```

### Section 3 -- `tests/test_ad1287_slot_qualification.py`

S1 #16 would fail on install: `profile_currency` imports S1 modules and calls `check_slot_qualification` (hidden pin H1). This widens the owners and the scanned gate names; no S1 mutant names #16 as its killer.

```
<<<<<<< SEARCH
# 16. Not wired
# --------------------------------------------------------------------------------------

_S1_MODULES = ("execution_profile", "profile_qualification_store")
_GATE_NAMES = ("ProfileQualificationStore", "admit_qualified_attempt", "check_slot_qualification")
=======
# 16. Not wired
# --------------------------------------------------------------------------------------

# AD-1287 S2a added two modules and a gate: the scan covers them, and spares them as owners, the same way
_S1_MODULES = ("execution_profile", "profile_qualification_store", "profile_components", "profile_currency")
_GATE_NAMES = (
    "ProfileQualificationStore",
    "admit_qualified_attempt",
    "check_slot_qualification",
    "admit_current_qualified_attempt",
    "RegistryComponentSource",
)
>>>>>>> REPLACE
```

```
<<<<<<< SEARCH
def test_nothing_in_src_constructs_the_store_or_calls_the_gate(tmp_path: Path) -> None:
    """Pins D5: no file under ``src/probos`` except the two S1 modules holds a direct syntactic reference to them (an import of an S1 module, or a call of the store or a gate function by name or attribute).

    AD-1288 (commission admission) constructs the store and routes admission through ``admit_qualified_attempt``,
=======
def test_nothing_in_src_constructs_the_store_or_calls_the_gate(tmp_path: Path) -> None:
    """Pins D5: no file under ``src/probos`` except the S1 and S2a modules (``_S1_MODULES``) holds a direct syntactic reference to them (an import of one of them, or a call of the store, a gate function or the S2a source by name or attribute).

    AD-1288 (commission admission) constructs the store and routes admission through ``admit_current_qualified_attempt``,
>>>>>>> REPLACE
```

### Section 4 -- `docs/development/roadmap.md`

```
<<<<<<< SEARCH
| AD-1287 | Evidence-Bound Skill Qualification - exact skill/model/tool/policy/eval profiles (S1 built 2026-10-12, unwired; S2/S3 remain) | [#1334](https://github.com/seangalliher/ProbOS/issues/1334) | 1 |
=======
| AD-1287 | Evidence-Bound Skill Qualification - exact skill/model/tool/policy/eval profiles (S1 built 2026-10-12, S2a skill/tool currency gate built 2026-10-14, both unwired; S2b/S3 remain) | [#1334](https://github.com/seangalliher/ProbOS/issues/1334) | 1 |
>>>>>>> REPLACE
```

---

## Tests (written by Builders against the installed source)

Run focused, serial: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1287_s2a_profile_components.py tests/test_ad1287_s2a_profile_currency.py tests/test_ad1287_slot_qualification.py -n 0 -p no:randomly -q`. Every test asserts its own premise. Doubles are hand-written `_Fake*` classes; no mock library. Never call `.read_text()` on an expression containing `__file__`, and never `inspect.getsource` (report-only `source-text-tests` category); read source with `read_bytes()`.

### M1 `tests/test_ad1287_s2a_profile_components.py`

| # | Test | Asserts |
|---|---|---|
| 1 | `test_skill_digest_known_answer` | tree `SKILL.md`, `z.md`, `references/a.md`, `assets/bin.dat` (bytes with `\r\n` and `\x00`); expected = `sha256(b"probos.execution_profile/skill_resources/v1\x00" + jcs.canonicalize({"files": [...]}))` built in the test with the literal domain, entries ascending (`SKILL.md`, `assets/bin.dat`, `references/a.md`, `z.md`), each `path`/`sha256`/`size`; premise: `z.md` sorts after the subdirectory entries but is created first |
| 2 | `test_skill_digest_is_deterministic` | two trees with equal content created in different orders give one digest; the same tree twice gives it again |
| 3 | `test_skill_digest_tracks_each_byte_path_and_size` (parametrize) | one changed byte, a renamed file, an added empty file, LF to CRLF: each gives a new digest; an added empty directory gives the same digest (pinned property) |
| 4 | `test_skill_digest_refuses_links` (parametrize) | file symlink, directory symlink, junction (win32 via `_winapi.CreateJunction`, test-only) -> `skill_resource_link_refused`; root that is a symlink or junction to a real directory -> `skill_resource_dir_invalid`; each case skips with a reason when the link cannot be created; premise `hasattr(os.DirEntry, "is_junction")` |
| 5 | `test_skill_digest_refuses_non_regular` | POSIX only (`os.mkfifo`), else skipped -> `skill_resource_not_regular` (no mutant) |
| 6 | `test_skill_digest_bounds` (parametrize) | monkeypatched `MAX_SKILL_FILES=3`: 3 files ok, 4 -> `skill_resource_limit`; `MAX_SKILL_BYTES=10`: 10 bytes total ok, 11 -> limit; real `MAX_SKILL_DEPTH`: 8 nested directories with a file ok, 9 -> limit |
| 7 | `test_skill_digest_refuses_bad_root` | missing path and a file path -> `ComponentDigestError("skill_resource_dir_invalid")`; a `str` -> `TypeError("skill_resource_dir_invalid")` |
| 8 | `test_tool_schema_digest_known_answer` | literal domain `b"probos.execution_profile/tool_schema/v1\x00"` + jcs bytes of `{"input_schema", "output_schema"}` |
| 9 | `test_tool_schema_digest_is_order_free_and_role_bound` | dict insertion order irrelevant; swapping input and output gives another digest |
| 10 | `test_tool_schema_digest_refuses_non_json` (parametrize) | exact type `ComponentDigestError`, args `("tool_schema_invalid",)`: top-level list; `StrEnum` key; `IntEnum` value; `str`-subclass value; `StrEnum` value inside a list; a `set`; `bytes`; NaN; infinity; `2**53` |
| 11 | `test_tool_schema_digest_bounds` | nesting exactly `MAX_SCHEMA_DEPTH` ok, one more refused; monkeypatched `MAX_SCHEMA_NODES` = the node count of a schema pair: ok, one node more refused; a self-referencing dict refused |
| 12 | `test_tool_schema_digest_accepts_json_scalars_and_tuples` | floats, bools, None accepted; a tuple digests equal to the same list |
| 13 | `test_components_module_imports_only_elastic_team` | AST of the module (`read_bytes`): ProbOS imports are exactly `{"probos.cognitive.elastic_team"}`; negative control: the scanner flags a snippet importing `probos.tools` |

### M2 `tests/test_ad1287_s2a_profile_currency.py`

Reuse `_World`, `_variant` (`tests/test_ad1287_slot_qualification.py`), `_evaluation` (`tests/test_ad1287_profile_qualification_store.py`), `_profile` (`tests/test_ad1287_execution_profile.py`), `_spec`, `_attempt` (`tests/test_ad1286_elastic_team_contract.py`). A real tool is a `_SchemaTool` double (`tool_id`, `name`, `tool_type=ToolType.DETERMINISTIC_FUNCTION`, `description`, distinct `input_schema`/`output_schema`, `invoke`) registered in a real `ToolRegistry`.

| # | Test | Asserts |
|---|---|---|
| 1 | `test_registry_source_reports_live_skill_state` | real `CognitiveSkillCatalog(skills_dir=...)` started: `LiveSkill(skill_resource_digest(dir), True)`; unknown name -> None |
| 2 | `test_registry_source_reports_structurally_invalid_skill` | dir `code-review-x` holding `name: code-review`; premise: `validate_skill` errors name the directory; `structurally_valid is False` |
| 3 | `test_registry_source_unreadable_skill` (parametrize) | `MAX_SKILL_BYTES=1` (digest error); directory deleted after the scan; `profile_currency.skill_resource_digest` monkeypatched to raise `PermissionError`: each -> `ComponentUnreadable` and one WARNING from `probos.cognitive.profile_currency` |
| 4 | `test_registry_source_reports_tool_schema_digest` | equals `tool_schema_digest(input, output)` and differs from the swapped call; unknown tool -> None |
| 5 | `test_registry_source_unreadable_tool` (parametrize) | `input_schema` property raises `RuntimeError`; schema is a list: `ComponentUnreadable` + one WARNING |
| 6 | `test_profile_drift_codes` (parametrize, `_FakeSource`) | current -> `()`; each of the seven codes with the full `ComponentDrift`; structurally invalid with a matching digest -> that code; structurally invalid and drifted -> one entry, the structural code |
| 7 | `test_profile_drift_reports_all_in_profile_order` | two drifted skills and a drifted tool -> three entries, skills by name then the tool; the fake was asked once per component |
| 8 | `test_profile_drift_refuses_malformed_input` (parametrize) | skill answer `"x"`; `LiveSkill` with a bad digest; `LiveSkill` with `structurally_valid=1`; tool answer `"z"*64`: `TypeError("profile_component_source_invalid")`; a profile `dict` -> `TypeError("profile_currency_type_invalid")` |
| 9 | `test_profile_drift_propagates_other_source_errors` | a fake raising `RuntimeError` -> it propagates unchanged |
| 10 | **`test_chain_real_catalog_and_tool_drift_is_refused_and_restored_profile_admitted_across_restart`** | real catalog + real registry produce the digests -> profile for slot `review` registered and evaluated on the real store; spec put; both stores and the catalog restarted (new instances); premise: `get_qualification(ref).status == "qualified"`; admit refused after one byte of `references/checklist.md` changes, `args == ("component_drift_skill",)`, `get_attempt` None, while premise: S1's status still `qualified`; file restored -> admitted, `get_attempt` holds the exact profile ref |
| 11 | `test_gate_refusal_codes` (parametrize, real stores, `_FakeSource`) | `slot_spec_unknown`; `profile_status_unevaluated` with current components; each drift code; every refusal: no attempt row and one INFO record from `probos.cognitive.profile_currency` |
| 12 | `test_gate_reads_components_only_for_a_qualified_profile` | unqualified and drifted -> S1's code, and the fake source was never asked |
| 13 | `test_gate_refuses_a_non_attempt` | `attempt.model_dump()` (a valid dict) -> `TypeError("elastic_attempt_type_invalid")` |
| 14 | `test_record_attempt_errors_propagate` | a `_FakeTeams` whose `record_attempt` raises -> the same exception object |
| 15 | `test_s1_gate_alone_still_admits_a_drifted_profile` | negative control for R-4: after a skill change, S1's `admit_qualified_attempt` records the attempt, S2a's refuses (separate stores) |
| 16 | `test_no_authority_fields_and_imports_allowlisted` | `LiveSkill`/`ComponentDrift` field names hold none of the six words (negative control: `AuthorityCeiling` from `elastic_team`); `profile_currency` ProbOS imports exactly the four D8 modules |
| 17 | `test_replay_after_drift_is_refused` | an admitted attempt replayed identically after a skill change -> `component_drift_skill` |

## Mutation campaign of record

Run ONCE, in M3, on the committed tree, serially (`-n 0 -p no:randomly`) with the M1 and M2 files. Baseline first; abort if red. Mutate in place with a `.mutbak` sibling, restore in `finally`. Count each anchor first: it must occur exactly once in its file (CRLF tree). Not found = INERT; timeout = INVALID. Record the base commit and sha256 of `profile_components.py`, `profile_currency.py` and both test files; a later edit to one invalidates only the mutants pinned to it. C10/C11 and U3/U4 share anchors; apply each alone. C18 is killed only where a junction can be created (win32): record the platform.

| Id | File | Anchor | Replacement | Killer |
|---|---|---|---|---|
| C1 | `profile_components.py` | `                if _is_link(entry):` | `                if False:` | M1 #4 |
| C2 | `profile_components.py` | `                    if depth + 1 > MAX_SKILL_DEPTH:` | `                    if False:` | M1 #6 depth |
| C3 | `profile_components.py` | `                    if len(found) > MAX_SKILL_FILES:` | `                    if False:` | M1 #6 files |
| C4 | `profile_components.py` | `    found.sort(key=lambda item: item[0])` | `    pass` | M1 #1 |
| C5 | `profile_components.py` | `        if len(data) > remaining:` | `        if False:` | M1 #6 bytes |
| C6 | `profile_components.py` | `    if skill_dir.is_symlink() or skill_dir.is_junction() or not skill_dir.is_dir():` | `    if not skill_dir.is_dir():` | M1 #4 root |
| C7 | `profile_components.py` | `SKILL_RESOURCES_DOMAIN: Final = b"probos.execution_profile/skill_resources/v1\x00"` | same with `v2` | M1 #1 |
| C8 | `profile_components.py` | `        manifest.append({"path": relative, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)})` | `        manifest.append({"path": relative, "sha256": hashlib.sha256(data).hexdigest()})` | M1 #1 |
| C9 | `profile_components.py` | `TOOL_SCHEMA_DOMAIN: Final = b"probos.execution_profile/tool_schema/v1\x00"` | same with `v2` | M1 #8 |
| C10 | `profile_components.py` | `    if budget[0] < 0 or depth > MAX_SCHEMA_DEPTH:` | `    if depth > MAX_SCHEMA_DEPTH:` | M1 #11 nodes |
| C11 | `profile_components.py` | `    if budget[0] < 0 or depth > MAX_SCHEMA_DEPTH:` | `    if budget[0] < 0:` | M1 #11 depth |
| C12 | `profile_components.py` | `            if type(key) is not str:` | `            if False:` | M1 #10 StrEnum key |
| C13 | `profile_components.py` | `    elif kind not in _JSON_SCALARS and value is not None:` | `    elif False:` | M1 #10 IntEnum value |
| C14 | `profile_components.py` | `        if type(schema) is not dict:` | `        if False:` | M1 #10 top-level list |
| C15 | `profile_components.py` | `    except ValueError as exc:  # NaN or an infinity, an int outside the I-JSON range, or a lone surrogate` | `    except TypeError as exc:  # mutant` | M1 #10 NaN, `2**53` |
| C16 | `profile_components.py` | `    elif kind is list or kind is tuple:` | `    elif False:` | M1 #12 (every list is then refused as a non-scalar) |
| C17 | `profile_components.py` | `    if kind is dict:` | `    if False:` | M1 #8 |
| C18 | `profile_components.py` | `    return entry.is_symlink() or entry.is_junction()` | `    return entry.is_symlink()` | M1 #4 junction (win32) |
| U1 | `profile_currency.py` | `        if entry is None:` | `        if False:` | M2 #1 |
| U2 | `profile_currency.py` | `        return LiveSkill(digest, validation.valid is True)` | `        return LiveSkill(digest, True)` | M2 #2 |
| U3 | `profile_currency.py` | `        except (ComponentDigestError, OSError) as exc:` | `        except OSError as exc:` | M2 #3 limit |
| U4 | `profile_currency.py` | `        except (ComponentDigestError, OSError) as exc:` | `        except ComponentDigestError as exc:` | M2 #3 PermissionError |
| U5 | `profile_currency.py` | `        if tool is None:` | `        if False:` | M2 #4 |
| U6 | `profile_currency.py` | `            return tool_schema_digest(tool.input_schema, tool.output_schema)` | `            return tool_schema_digest(tool.output_schema, tool.input_schema)` | M2 #4 |
| U7 | `profile_currency.py` | `        except Exception as exc:  # noqa: BLE001 -- log-and-degrade: a tool's schema property may raise anything; the degrade is a refusal` | `        except ComponentDigestError as exc:  # mutant` | M2 #5 RuntimeError |
| U8 | `profile_currency.py` | `    if type(profile) is not ExecutionProfile:` | `    if False:` | M2 #8 dict |
| U9 | `profile_currency.py` | `        if live is None:` | `        if False:` | M2 #6 missing skill |
| U10 | `profile_currency.py` | `        elif not _is_live_skill(live):` | `        elif False:` | M2 #8 |
| U11 | `profile_currency.py` | `        elif not live.structurally_valid:` | `        elif False:` | M2 #6 structural |
| U12 | `profile_currency.py` | `        elif live.resource_digest != declared:` | `        elif False:` | M2 #6, #10 |
| U13 | `profile_currency.py` | `        if live_schema is None:` | `        if False:` | M2 #6 missing tool |
| U14 | `profile_currency.py` | `        elif not is_sha256_ref(live_schema):` | `        elif False:` | M2 #8 tool answer |
| U15 | `profile_currency.py` | `        elif live_schema != declared:` | `        elif False:` | M2 #6 tool drift |
| U16 | `profile_currency.py` | `        if spec is None:` | `        if False:` | M2 #11 |
| U17 | `profile_currency.py` | `        qualification = await check_slot_qualification(qualifications, spec, attempt.slot_id, attempt.execution_profile_ref)` | `        qualification = await qualifications.get_qualification(attempt.execution_profile_ref)` | M2 #11 unevaluated |
| U18 | `profile_currency.py` | `        drifts = await profile_drift(qualification.profile, components)` | `        drifts = ()` | M2 #10, #11 |
| U19 | `profile_currency.py` | `        if drifts:` | `        if False:` | M2 #10, #11 |
| U20 | `profile_currency.py` | `        logger.info(` | `        logger.debug(` | M2 #11 INFO |
| U21 | `profile_currency.py` | `    if type(attempt) is not WorkerAttempt:` | `    if False:` | M2 #13 |

Total 39. Anchor uniqueness was checked by reading the Section 1-2 text (no interpreter): `logger.info(` occurs once in `profile_currency.py` (both warnings are `logger.warning(`); `if live is None:` and `if live_schema is None:` differ.

---

## What this does NOT change

- `execution_profile.py`, `profile_qualification_store.py`, `storage_declarations.py`, any AD-1286 file, `skill_catalog.py`, `tools/`, `model_registry.py`, `consensus/trust.py`. Only test #16 of the S1 test files changes (Section 3).
- Runtime, startup, config, routers, events, HXI, store registry, architecture baseline.

## Do not build

- No runtime wiring: no construction of `RegistryComponentSource` or call of either gate under `src/`.
- No model, prompt, tool-implementation or policy producer, no model version label or config field (S2b).
- No invalidation write, no `component_drift_*` invalidation, no sweep (S2b).
- No outcome table, Beta parameters or `TrustNetwork` write (S3).
- No edit to S1's `admit_qualified_attempt` or `check_slot_qualification` (R-4 is AD-1288's).
- No shared `_open` helper (R-1), no ignore list for skill files, no link following.
- No evaluator-side derivation of `EvaluationRecord.structurally_valid` (no evaluator exists in the tree).
- No signing or attestation (AD-1047). No provisioning, composition, fallback change, marketplace, Dataverse or Copilot Studio work.
- No broad gate by a Builder; no `git add -A`.

## Obligations handed on

- **O-1 (amended, AD-1288):** commission admission records attempts only through `admit_current_qualified_attempt`; it changes S1 #16 deliberately. Recovery reads `get_attempt`.
- **O-2:** discharged for skills and tool schemas; open for the model and policy (S2b). Prompts and tool implementations have no live owner (R-5).
- **O-3:** unchanged (S3).
- **R-1:** unchanged and still deferred. The request's premise that AD-1299 S2a landed is false on this base (A4); S2a adds no store, so it has no reason to extract. Recommended after S3, as its own slice with fresh campaigns for both stores (S1b X1/X2 and this store).
- **R-2, R-3:** unchanged (AD-1047 is a Captain decision).
- **R-4 (new):** S1's gate stays callable without currency (D1).
- **R-5 (new):** prompt revisions and tool implementation digests remain declared-only.

## Acceptance criteria (S2a)

1. M1 and M2 green with `-n 0 -p no:randomly`; `probos.__file__` resolves inside this worktree's `src`; S1's three test files green.
2. With the new files staged: `d:/ProbOS/.venv/Scripts/python.exe scripts/check_store_registry.py --check` and `d:/ProbOS/.venv/Scripts/python.exe scripts/check_architecture_principles.py --check` exit 0; `tests/test_layer_boundaries.py` green.
3. M2 #10 crosses the seam in one test: real catalog and registry -> real store evaluation -> restart -> drift refused with no attempt row -> restored file admitted.
4. #1334 items covered here, each with a named test: structurally invalid profiles cannot satisfy a slot, live (M2 #2, #6, #11); exact component drift refused at the slot boundary on real stores across a restart (M2 #10, #17); a source names no authority (M2 #16). #1334 stays open.
5. Every mutant KILLED by its named test in the single M3 campaign of record (C18 on win32).
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Hidden pins (enumerated)

| Id | Pin | Command | Effect here |
|---|---|---|---|
| H1 | S1 #16 not-wired scan | Read `tests/test_ad1287_slot_qualification.py:626-746` | Would fail; Section 3 edits it |
| H2 | Architecture gate: `srp-size` (500 lines / 15 methods per class), `layer-import`, `db-connect`, `unowned-task` | `scripts/check_architecture_principles.py:160-199`; `docs/development/architecture-baseline.yaml:12-17` | Classes small; no `connect`, no `create_task`; `tools` is not a ranked layer |
| H3 | Layer boundaries | `tests/test_layer_boundaries.py:16-53` | cognitive -> cognitive only |
| H4 | Store registry | `scripts/check_store_registry.py --check` | No SQL, table or `.db`: no declaration |
| H5 | Source-text tests (report-only) | `check_architecture_principles.py:711-749` | Tests use `read_bytes` |
| H6 | Identity goldens | Grep `probos.execution_profile/` in `tests/` | S1 domains untouched; two new domains |
| H7 | Config reference/profile/facade | none: no config added | n/a |
| H8 | 33 tree-wide `rglob("*.py")` scanners in `tests/` | Grep `rglob\("\*\.py"\)` in `tests/` | Not run here; the pre-Builder full-suite diagnostic is the check |

## Prior Art and Blind Spots (2026-10-14)

| Source | Idea | Decision |
|---|---|---|
| [Go `dirhash`](https://pkg.go.dev/golang.org/x/mod/sumdb/dirhash) | per-file sha256 over sorted relative names, then one hash | **Adopted** as the manifest shape; **rejected** its text line format (D3) |
| [OCI descriptor](https://github.com/opencontainers/image-spec/blob/main/descriptor.md) | a size travels with the digest | **Adopted**: `size` per file |
| [SLSA provenance v1](https://slsa.dev/provenance/v1) `resolvedDependencies` | each input pinned by digest; a verifier compares digests | **Adopted**: profile components are compared by digest only, never by name or version |
| Internal: AD-1286 identity, S1 D2/D5, `jcs.py:53-73`, `docs/research/crew-capability-architecture.md:538` (AD-566c behavioural drift) | canonical form; composition at the slot boundary; behavioural drift is a separate concern | **Adopted** the first two; AD-566c drift is score drift, not component drift: considered, not merged |

**Blind spots:** (1) the catalog caches entries from its last scan, so a frontmatter edit is not seen by `validate_skill`, but the digest reads disk, so it is still refused as drift; (2) TOCTOU after the check (D7); (3) a BOM or line-ending change refuses (conservative); (4) `__pycache__` or editor temp files inside a skill directory refuse until requalified (an ignore list was rejected: an ignored file could carry instructions); (5) a cloud placeholder file can trigger hydration when read (not handled); (6) a tool that builds its schema per instance or caches a remote MCP schema is digested as it answers now; (7) a legitimate skill over 256 files / 8 MiB / depth 8 refuses as unreadable; (8) R-4; (9) *a link swapped in between the enumeration and a file open (review round 1, F1; recorded, not changed here)*: the enumeration refuses every link it sees, but each file is then opened by path, so a directory replaced by a junction in that window is followed (reproduced on win32: the digest equals the out-of-tree content's), and a writer with the process's own identity could equally change a file right after the digest is taken (S2a's check holds only as of its own reads, D7); pinned-handle traversal is a platform-specific follow-up and the module docstring states what is and is not detected; (10) *an exact `LiveSkill` built without its fields (review round 1, F3; injected reach, recorded)* raises `AttributeError` from the answer check instead of the stable `TypeError`; the `profile_drift` docstring states it.

## Verified Against Codebase (2026-10-14, base `03e5500e`)

```
Read src/probos/cognitive/profile_qualification_store.py:175-252, :600-848
  189: class SlotAdmissionRefused(ValueError)    241: class ProfileQualificationReader(Protocol)
  247: class TeamAttemptRecorder(Protocol)        671: async def invalidate_profile(...)
  784: async def check_slot_qualification(qualifications, spec, slot_id, profile_ref)
  815: async def admit_qualified_attempt(qualifications, teams, attempt)
Grep _REASON_RE profile_qualification_store.py  -> 84: ^[a-z0-9][a-z0-9_]{0,63}$
Read src/probos/cognitive/execution_profile.py:113-191  SkillComponent(skill_name, resource_digest); ToolComponent(tool_id, schema_digest, implementation_digest); ExecutionProfile.skills/.tools sorted tuples
Read src/probos/cognitive/elastic_team.py:56-78  canonicalize_projection; is_sha256_ref; 384-396 WorkerAttemptOutcome
Read src/probos/federation/ard/jcs.py:53-145  isinstance dispatch; ValueError for NaN/inf/unsafe int/surrogate
Read src/probos/cognitive/skill_catalog.py:54-71, 151-154 (skill_dir=path.parent), 186-223 (name must match dir), 283-339 (get_entry sync), 550-627 (validate_skill async, valid=False when missing)
Read src/probos/tools/registry.py:137-192  register(...) logs tool.tool_type.value; get_tool(tool_id) -> Tool | None
Read src/probos/tools/protocol.py:15-26 (ToolType.DETERMINISTIC_FUNCTION), 106-134 (input_schema/output_schema)
Grep "alpha: float = 2" consensus/trust.py -> 66-67 (S3 prior)
Grep "async def" elastic_team_store.py -> 806 record_attempt_outcome, 874 get_attempt_outcome (S3 producer input)
Grep requires-python pyproject.toml -> 9: >=3.12 (os.DirEntry.is_junction, Path.is_junction)
Read tests/test_ad1287_slot_qualification.py:88-171, 466-503, 626-746; tests/test_ad1287_execution_profile.py:61-135; tests/test_ad1287_profile_qualification_store.py:86-99, 228-241
```

## Absence Verified (2026-10-14, base `03e5500e`)

| Id | Claim | Run | Found | Holds |
|---|---|---|---|---|
| A1 | No skill digest owner | Grep `hashlib\|digest\|sha256` in `skill_catalog.py` | 0 | yes |
| A2 | `Tool` has no implementation version | Grep `version` in `tools/protocol.py` | 0 | yes |
| A3 | New names are free | Grep `ProfileComponentSource\|admit_current_qualified_attempt\|skill_resource_digest\|tool_schema_digest\|profile_currency\|profile_components\|component_drift` repo-wide excluding `prompts/` | one S1 test name, `test_component_drift_starts_unevaluated_across_restart` | yes |
| A4 | AD-1299 S2a is not on this base | `git merge-base --is-ancestor f3445ae1 HEAD`; `git branch --list --all --contains 0440f3a4`; Glob `prompts/ad-1299-s*.md` | exit 1; only `feat/ad1299-s2-20261014-cff84495`; s1a, s1b only | yes: the request premise is false here |
| A5 | No production caller of the S1 gate | Grep `admit_qualified_attempt\|check_slot_qualification\|ProfileQualificationStore\(` in `src` | the store, `storage_declarations.py` (strings), `execution_profile.py` (docstring) | yes |
| A6 | `tools` is not a ranked/checked layer | Read baseline yaml `:12-17`; `test_layer_boundaries.py:16-27` | absent from both | yes |
| A7 | `ModelDescriptor` has no version | Read `model_registry.py:32-43` | name, provider, tier, capabilities, costs, context, available | yes |
| A8 | No policy digest owner | not enumerated beyond S1 A1 and `ToolRegistry.register` kwargs (`registry.py:137-151`) | n/a | deferred to S2b's own verification |
| A9 | No prompt-revision owner | not enumerated | n/a | R-5 is a statement about S2a's scope; S2b re-verifies |

## Not verified

- Nothing here was executed: the two modules do not exist on the base, so no known-answer vector, anchor count or test was run. The pre-Builder full-suite diagnostic is the first execution. **If a premise fails, stop and report rather than weaken an assertion.**
- That the venv's interpreter is 3.12+ (`os.DirEntry.is_junction`); M1 #4 asserts it.
- `_winapi.CreateJunction` availability on the Captain's machine (M1 #4 skips otherwise; C18 then needs another platform note).
- Whether a cancelled `asyncio.to_thread` call leaves the thread reading (D7 says "may").

## Tracking (M4, after the campaign; not installed)

- **`DECISIONS.md`**, directly above `### AD-1287 S1` (`:44`): `### AD-1287 S2a -- Live skill and tool-schema currency at the slot boundary (<date>)`, one line each for the slicing decision and D1-D9, O-1 amended, R-4, R-5, the A4 premise correction, and the campaign of record (base commit, four sha256, each mutant KILLED/INERT/INVALID with its killer, platform for C18).
- **`PROGRESS.md`**, directly under `# ProbOS Progress`: `**AD-1287 slice S2a BUILT (<date>), #1334, built and unwired -- ...**` with the files, measured per-file test counts, "no file under `src/` constructs the source or calls either gate (S1 #16)", and "S2b (model and policy producers, drift recording) and S3 (outcome learning) remain; #1334 stays open".
- Roadmap: Section 4 (installed).
- Then: `d:/ProbOS/.venv/Scripts/python.exe scripts/gen_ad_ledger.py` and `d:/ProbOS/.venv/Scripts/python.exe scripts/gen_ad_ledger.py --check`.

## Later slices

- **S2b: model and policy producers, drift recording.** Live model state (`ModelRegistry` descriptor by provider and name, plus a version label from a new config field, with its config pins), a policy digest over a definition it must first settle (candidate: the profile's tools' `ToolRegistration` permission fields), two more `ProfileComponentSource` methods and gate checks, and `record_component_drift(store, source, profile_ref)` writing `component_drift_<kind>` invalidations with an id derived from `(kind, key, live)` so a replay is idempotent. Consumer: S1's `get_qualification` reports `invalidated`. Leaves: prompts and tool implementations (R-5).
- **S3: outcome learning (O-3), as scoped in the request**, including the layout extension (accept the S1 layout and add the table in the same `BEGIN IMMEDIATE`, accept S1+S3, refuse anything else, with refusing tests). The last of S2b and S3 to land closes #1334.

=== BUILDER BRIEFS ===

### Brief M1 -- producer tests (effort: max, at most 150 calls)

Contract: `prompts/ad-1287-s2a-skill-tool-currency-gate.md`. Source is installed and frozen: do not edit anything under `src/`. Write only `tests/test_ad1287_s2a_profile_components.py`, tests M1 #1-#13 (Tests section). Each test asserts its premise first. Compute the known-answer vectors in the test from the literal domain bytes and `probos.federation.ard.jcs.canonicalize`, never by calling the function under test. Lower bounds by `monkeypatch.setattr(profile_components, "MAX_...", n)`. Links: try `os.symlink`; on win32 also `_winapi.CreateJunction(str(target), str(link))`; skip a case with a reason when its link cannot be made, and report which cases ran. Read source only with `read_bytes()`; never `.read_text()` on an expression containing `__file__`. Run `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1287_s2a_profile_components.py -n 0 -p no:randomly -q`. A premise that fails (for example the venv is not 3.12+): stop and report; do not weaken an assertion. Report counts, skips and their reasons.

### Brief M2 -- source, drift, gate and the chain (effort: max, at most 150 calls)

Contract as M1. Source frozen. Write only `tests/test_ad1287_s2a_profile_currency.py`, M2 #1-#17. Reuse helpers named in the M2 table by import; do not copy them. `_FakeSource` records each question and answers from a dict; `_SchemaTool` is a minimal `Tool` with `ToolType.DETERMINISTIC_FUNCTION`. M2 #10 is the one seam test: real `CognitiveSkillCatalog` on `tmp_path/"skills"` (a `code-review` skill with `SKILL.md` and `references/checklist.md`), real `ToolRegistry`, real `ProfileQualificationStore` and `ElasticTeamStore` via `_World`; build the profile with `_profile(**{"skills": [...live digest...], "tools": [...live schema digest...]})`, register, evaluate with `_evaluation(ref)`, put `_spec()`, restart the world and build a new catalog, then the steps in the table. Log assertions use `caplog` with the logger `probos.cognitive.profile_currency`. Run M2 plus `tests/test_ad1287_slot_qualification.py` with `-n 0 -p no:randomly`. Stop and report on a failing premise.

### Brief M3 -- mutation campaign of record (effort: high, at most 150 calls)

On the committed M1+M2 tree. Follow "Mutation campaign of record" exactly: baseline green first; count each anchor (exactly once); one mutant at a time with a `.mutbak` restore in `finally`; run the two S2a test files serially. Record base commit, the four sha256 values, platform, and per mutant KILLED / INERT / INVALID with the test that killed it. A survivor: stop and report the mutant and the test that should have killed it; do not edit source or the table.

### Brief M4 -- trackers (effort: high, at most 60 calls)

Apply "Tracking (M4)" with the measured counts and the M3 results, then run both ledger commands. Stage explicit paths only; never `git add -A`. No broad gate.
