# AD-1287 S2b (#1334): record a qualified profile's live skill and tool drift as S1 invalidations

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-14
**Status:** build-ready (slice S2b of four: S1 shipped, S2a built on this branch, S2b, S3). Base: the S2a branch head `f431dd0f` (`feat/ad1287-s2b-20261014-f431dd0f`); `origin/main` `1001f3b7` does not hold S2a yet.
**Issue / epic:** #1334 / #1332. AD-1287 is already allocated; this slice allocates no AD or BF number (ceiling AD-1327 from all three sources, `scripts/ad_ceiling.py`, 2026-10-14).
**Depends on:** AD-1287 S1 (`invalidate_profile`, `get_qualification`) and S2a (`profile_drift`, `ProfileComponentSource`, `admit_current_qualified_attempt`). **Dependents:** AD-1288 #1335 (O-4 below), S3 (independent).
**Estimated tests:** 16 in one new file (several parametrized), plus a widened S1 test #16.
**Milestones:** M1 tests, M2 mutation campaign of record, M3 trackers. Briefs follow `=== BUILDER BRIEFS ===`. Source is installed from this contract; Builders write tests only.

One-line summary: `record_component_drift(store, source, profile_ref)` turns the drifts S2a already detects (skill content, skill structure, tool schema) into S1 invalidations with an id bound to the deciding evaluation, so `get_qualification` reports `invalidated` across a restart and the S2a gate refuses until the profile is evaluated again. The model and the policy stay declared-only (D2, D3). Built and unwired.

---

## Problem

- S2a refuses a drifted profile at the gate but records nothing (S2a D6; `profile_currency.py:17` "Nothing here records an invalidation"). `get_qualification` keeps reporting `qualified` for a profile whose skill changed (pinned by S2a M2 #10: `tests/test_ad1287_s2a_profile_currency.py:596-597`), so the acceptance line "Real-store restart tests cover ... invalidation, and exact component drift" (`logs/architect/issue-1334.md:43`) and "Invalidate or require requalification when any bound component changes" (`:21`) are met only as a transient refusal.
- S1's `invalidate_profile` (`profile_qualification_store.py:671-721`) exists and nothing calls it (Absence A8).
- S2a's sketch of the id, "derived from `(kind, key, live)`" (`prompts/ad-1287-s2a-skill-tool-currency-gate.md:748`), is unsafe: `invalidate_profile` answers an existing id with the old row and writes nothing (`:702-707`), and an invalidation applies only to evaluations with a lower sequence (`_assess`, `:430-436`). So drift to L, requalify, drift to L again would hit the old id, write nothing, and leave the new evaluation `qualified` (D4).

## Solution overview (S2b)

1. **`src/probos/cognitive/profile_drift_recorder.py` (new):** `DRIFT_INVALIDATION_DOMAIN`, `RECORDED_DRIFT_CODES`, the `DriftInvalidationStore` port, `drift_invalidation_id` and `record_component_drift`.
2. **S1 test #16 widened** (Section 2): the module is an owner of the scan, and `record_component_drift` is a scanned name.
3. **Chain proof (M1 #15):** a real catalog and a real `ToolRegistry` give the digests. The profile is registered and evaluated on the real store, a skill byte changes, and the recorder writes. Both stores restart. `get_qualification` reports `invalidated` with the reason, and the S2a gate refuses `profile_status_invalidated` even after the file is restored, with no attempt row. A new evaluation then admits the exact profile.

Nothing constructs a source or calls the recorder or either gate in production.

## Slicing decision

| Rank | Option | Verdict |
|---|---|---|
| 1 | **S2b = drift recording for the components S2a checks (skill content, skill structure, tool schema).** Model and policy stay declared-only, with an obligation on AD-1288 (O-4) | **Chosen.** It is a whole chain on existing producers: detect (S2a), record (new), `get_qualification` says `invalidated` (S1), gate refuses (S2a). It adds one module and edits no S1 or S2a source, so both campaigns of record stand. It settles no contested definition |
| 2 | Rank 1 plus a policy digest over the profile's tools' `ToolRegistration` permission fields | Rejected (D3): it covers only the registration defaults of a per-agent permission chain, and it would fix "policy" before AD-1288 settles the lease, risking a v2 re-hash |
| 3 | S2a's sketch: rank 1 plus a model producer (descriptor by provider and name plus a new config version label) and the policy producer | Rejected (D2, D3): two contested definitions and the config reference/profile/facade pins in one slice. AD-1326's seven rounds are the measured cost |
| 4 | The S2a gate records on refusal; no separate recorder | Rejected: it would make admission a writer, write on every refused attempt including transient ones, and reverse S2a D6 inside a campaigned file |

**After S2b:** #1334 still needs S3 (outcome learning, O-3; independent). #1334 closes when S3 lands. The closing comment must state the honest limit of `:21`: skills and tool schemas are detected, recorded and refused. The model and the policy are carried by O-4 (bound at provisioning, AD-1288). Prompts and tool implementations stay declared-only (R-5), and so do the model version and the policy (R-6).

## Decisions and ranked options

### D1. Who records, and when

| Rank | Option | Verdict |
|---|---|---|
| 1 | A function a sweeper calls: `record_component_drift(store, source, profile_ref)`. It reads the qualification and writes only when the status is `qualified` | **Chosen.** One writer. It reads components only for a profile that a drift could still un-qualify (as S2a D5), and after it records, a replay finds `invalidated` and does nothing. No sweeper is wired (O-4) |
| 2 | Record for any evaluated profile | Rejected: it adds rows to profiles that are already not admissible, and the row count grows with every sweep that sees a new state |

### D2. The model: declared-only

| Rank | Option | Verdict |
|---|---|---|
| 1 | **Declared-only.** AD-1288 must provision the worker on the profile's declared provider and name, or refuse (O-4). The provider's per-reply model id (`llm_client.py:135-142`, `answered_model` at `:2431`, `:2491`) is a post-hoc signal for S3 or AD-1288 (R-6) | **Chosen.** No honest live owner of a version exists (A2, A3) |
| 2 | Name presence in `ModelRegistry`, no version | Rejected: it reports currency it never checked. `from_tier_models` registers every non-catalog name with provider `"unknown"` (`model_registry.py:191-193`), so a provider comparison would refuse every such model, and the registry is reachable only on the runtime (`startup/finalize.py:3883`) |
| 3 | A new Pydantic config field per tier holding a version label | Rejected: operator-asserted, not live (a provider alias moves without a config change; Prior Art), and eight tier fields plus the config reference, profile and facade pins |

### D3. The policy: declared-only

| Rank | Option | Verdict |
|---|---|---|
| 1 | **Declared-only.** The worker's authority is leased by AD-1288 (`execution_profile.py:17-18`). O-4 asks AD-1288 to lease under the profile's declared policy, or refuse | **Chosen.** Effective tool permission is per agent: department, rank, the agent allowlist and Captain grants (`tools/registry.py:255-320`). A profile is per role and task class |
| 2 | Digest of the profile's tools' `ToolRegistration` fields (`domain`, `department`, `allowed_departments`, `enabled`, `default_permissions`, `restricted_to`; `tools/protocol.py:219`, `registry.py:161-173`) | Rejected: layers 1-3 defaults only, named as "the policy" |
| 3 | The admission-policy file digest (`execution/authority.py:724-725`) | Rejected: it binds the execution authority manifest for a selected agent source, not a worker's profile policy |

### D4. The invalidation id

`drift-` plus `sha256(DRIFT_INVALIDATION_DOMAIN + RFC 8785 bytes of {"code", "evidence_ref", "key", "kind", "live", "profile_ref"})`: 70 characters, a valid `ElasticId` (`elastic_team.py:35`). `evidence_ref` is the deciding evaluation's, so:

- a replay or a concurrent recorder holding the same evaluation gets the same id, and the store answers the row it already has (`profile_qualification_store.py:702-707`);
- the same drift seen after a requalification gets a new id and is recorded against the new evaluation (M1 #13; mutant R10).

`code` is in the material because one live digest can carry two recorded codes (structurally invalid, later valid with the same bytes), and a shared id would raise `profile_invalidation_conflict`. `declared` is not, because `profile_ref` fixes it. Floats are never in the material.

### D5. What is recorded

Only drifts whose live state was read: `component_drift_skill`, `component_structurally_invalid_skill` and `component_drift_tool_schema` (`RECORDED_DRIFT_CODES`; each one matches `_REASON_RE`, `profile_qualification_store.py:84`). `component_missing_*` and `component_unreadable_*` are logged at INFO and not recorded. An absent catalog or registry entry can be startup ordering, and a failed read can be a locked file, while an invalidation is durable until a new evaluation. The S2a gate still refuses both at admission (M1 #6 cross-checks this).

### D6. Failure tiers

| Condition | Tier | Behaviour |
|---|---|---|
| Malformed `profile_ref` | Propagate | `ValueError("execution_profile_ref_invalid")` before the store is asked |
| Unknown profile | Propagate | `ProfileQualificationConflict("profile_unknown")`, the code `invalidate_profile` uses |
| Store answers for another profile | Propagate | `ValueError("profile_evidence_mismatch")`; nothing written, source not asked |
| Store answers `qualified` with no deciding evaluation | Degrade | treated as not qualified: `()`, nothing written |
| Bad id input | Propagate | `TypeError("drift_invalidation_input_invalid")` |
| `profile_drift` or `invalidate_profile` raises | Propagate | unchanged; earlier drifts stay recorded, and a rerun finds the profile `invalidated` and records nothing more (the gate refuses it until a new evaluation; review round 1, F2, pinned by M1 #18) |

### D7. Authority and imports

Nothing is granted. `profile_drift_recorder` imports from ProbOS exactly `elastic_team`, `profile_currency` and `profile_qualification_store` (M1 #16). The module defines no class with fields.

---

## Section 0: Event types

None.

### Section 1 -- NEW `src/probos/cognitive/profile_drift_recorder.py`

```python
"""AD-1287 S2b: record a qualified profile's live skill and tool drift as S1 invalidations.

``record_component_drift`` reads a profile's qualification. Only when the status is ``qualified`` does it ask a
``ProfileComponentSource`` (S2a) for drift through ``profile_drift``. Each drift whose live state was read --
``RECORDED_DRIFT_CODES``: a skill whose resources digest differently, a skill that fails ``validate_skill``, a tool
whose schemas digest differently -- is recorded through ``invalidate_profile`` with its code as the reason. So
``get_qualification`` reports ``invalidated`` until a new evaluation is recorded. A missing or unreadable component is
logged at INFO and not recorded: an absent catalog or registry entry, or a failed read, can be transient, and an
invalidation is durable. The slot boundary (``admit_current_qualified_attempt``) still refuses both at admission.

The invalidation id binds the profile, the deciding evaluation's evidence reference and the drift's kind, key, code
and live digest. A replay or a concurrent recorder holding the same evaluation gets the same id, and the store
answers the row it already holds; the same drift seen after a requalification is recorded again, against the new
evaluation.

Checked and recorded: skills and tool schemas, as S2a checks them. Not checked or recorded (declared only): the
model, the policy, prompts, tool implementation digests and the evaluation suite. The record holds as of its own
reads: the qualification read, the component reads and each write are separate operations. A newly inserted
invalidation applies to every evaluation recorded before it, including one recorded between the reads and the write;
an id the store already holds answers its existing row, which applies only to the evaluations recorded before that
row, so a duplicate replay does not invalidate a later evaluation. If a write raises, the drifts recorded before it
stay recorded; a rerun then finds the profile ``invalidated`` and records nothing more, and the slot boundary refuses
the profile until a new evaluation is recorded. Nothing here grants anything, and nothing calls it: no sweeper is wired.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Final, Protocol

from probos.cognitive.elastic_team import canonicalize_projection, is_sha256_ref
from probos.cognitive.profile_currency import ComponentDrift, ProfileComponentSource, profile_drift
from probos.cognitive.profile_qualification_store import (
    ProfileQualification,
    ProfileQualificationConflict,
    RecordedInvalidation,
)

logger = logging.getLogger(__name__)

DRIFT_INVALIDATION_DOMAIN: Final = b"probos.execution_profile/drift_invalidation/v1\x00"
RECORDED_DRIFT_CODES: Final = frozenset(
    {
        "component_drift_skill",
        "component_structurally_invalid_skill",
        "component_drift_tool_schema",
    }
)


class DriftInvalidationStore(Protocol):
    """The two ``ProfileQualificationStore`` operations the recorder uses; ``ProfileQualificationStore`` satisfies it."""

    async def get_qualification(self, profile_ref: str) -> ProfileQualification | None: ...

    async def invalidate_profile(
        self, profile_ref: str, invalidation_id: str, reason_code: str,
    ) -> RecordedInvalidation: ...


def drift_invalidation_id(profile_ref: str, evidence_ref: str, drift: ComponentDrift) -> str:
    """The invalidation id for ``drift`` of ``profile_ref`` observed against the evaluation ``evidence_ref``.

    ``drift-`` followed by the sha256 hex of ``DRIFT_INVALIDATION_DOMAIN`` plus the RFC 8785 bytes of the profile
    reference, the evidence reference and the drift's kind, key, code and live digest: 70 characters.

    Raises:
        TypeError: ``drift_invalidation_input_invalid`` when either reference is not a 64-hex digest, ``drift`` is
            not exactly a ``ComponentDrift``, or its live digest is not a 64-hex digest (an exact ``ComponentDrift``
            built without its fields raises ``AttributeError`` instead).
    """
    if (
        not is_sha256_ref(profile_ref)
        or not is_sha256_ref(evidence_ref)
        or type(drift) is not ComponentDrift
        or not is_sha256_ref(drift.live)
    ):
        raise TypeError("drift_invalidation_input_invalid")
    material = {
        "code": drift.code,
        "evidence_ref": evidence_ref,
        "key": drift.key,
        "kind": drift.kind,
        "live": drift.live,
        "profile_ref": profile_ref,
    }
    digest = hashlib.sha256(DRIFT_INVALIDATION_DOMAIN + canonicalize_projection(material)).hexdigest()
    return f"drift-{digest}"


async def record_component_drift(
    store: DriftInvalidationStore, source: ProfileComponentSource, profile_ref: str,
) -> tuple[RecordedInvalidation, ...]:
    """Record each live skill or tool drift of a qualified profile as an S1 invalidation; the records in drift order.

    Reads ``store.get_qualification(profile_ref)``. Unless its status is ``qualified`` with a deciding evaluation, it
    returns an empty tuple, asks ``source`` nothing and writes nothing. Otherwise it runs ``profile_drift``, records
    each drift whose code is in ``RECORDED_DRIFT_CODES`` through ``store.invalidate_profile`` (id
    ``drift_invalidation_id`` over the deciding evaluation, reason the drift's code), and logs each other drift at
    INFO without recording it. Returns what the store answered for each recorded drift; an id the store already
    holds answers its existing row.

    Raises:
        ValueError: ``execution_profile_ref_invalid`` for a malformed reference, before the store is asked;
            ``profile_evidence_mismatch`` when the store answers for another profile (nothing is written).
        ProfileQualificationConflict: ``profile_unknown`` when the store holds no such profile.
        What ``profile_drift`` or ``store.invalidate_profile`` raises, unchanged. Drifts recorded before a write
        that raises stay recorded, and a rerun then finds the profile ``invalidated`` and records nothing more.
    """
    if not is_sha256_ref(profile_ref):
        raise ValueError("execution_profile_ref_invalid")
    qualification = await store.get_qualification(profile_ref)
    if qualification is None:
        raise ProfileQualificationConflict("profile_unknown")
    if qualification.profile_ref != profile_ref or qualification.profile.content_ref() != profile_ref:
        raise ValueError("profile_evidence_mismatch")
    if qualification.status != "qualified" or qualification.deciding is None:
        return ()
    evidence_ref = qualification.deciding.evidence_ref
    recorded: list[RecordedInvalidation] = []
    for drift in await profile_drift(qualification.profile, source):
        if drift.code not in RECORDED_DRIFT_CODES:
            logger.info(
                "AD-1287: %s %s of execution profile %s is %s; not recorded as an invalidation (it may be "
                "transient), and the slot boundary still refuses the profile",
                drift.kind,
                drift.key,
                profile_ref,
                drift.code,
            )
            continue
        invalidation_id = drift_invalidation_id(profile_ref, evidence_ref, drift)
        recorded.append(await store.invalidate_profile(profile_ref, invalidation_id, drift.code))
    return tuple(recorded)
```

### Section 2 -- `tests/test_ad1287_slot_qualification.py`

S1 #16 would fail on install: the new module imports `profile_currency` and `profile_qualification_store` (hidden pin H1). This widens the owners and the scanned names. No S1 or S2a mutant names #16 as its killer.

```
<<<<<<< SEARCH
# AD-1287 S2a added two modules and a gate: the scan covers them, and spares them as owners, the same way
_S1_MODULES = ("execution_profile", "profile_qualification_store", "profile_components", "profile_currency")
_GATE_NAMES = (
    "ProfileQualificationStore",
    "admit_qualified_attempt",
    "check_slot_qualification",
    "admit_current_qualified_attempt",
    "RegistryComponentSource",
)
=======
# AD-1287 S2a added two modules and a gate, and S2b a module and a recorder: the scan covers them, and spares them
# as owners, the same way
_S1_MODULES = (
    "execution_profile",
    "profile_qualification_store",
    "profile_components",
    "profile_currency",
    "profile_drift_recorder",
)
_GATE_NAMES = (
    "ProfileQualificationStore",
    "admit_qualified_attempt",
    "check_slot_qualification",
    "admit_current_qualified_attempt",
    "RegistryComponentSource",
    "record_component_drift",
)
>>>>>>> REPLACE
```

### Section 3 -- `docs/development/roadmap.md`

```
<<<<<<< SEARCH
| AD-1287 | Evidence-Bound Skill Qualification - exact skill/model/tool/policy/eval profiles (S1 built 2026-10-12, S2a skill/tool currency gate built 2026-10-14, both unwired; S2b/S3 remain) | [#1334](https://github.com/seangalliher/ProbOS/issues/1334) | 1 |
=======
| AD-1287 | Evidence-Bound Skill Qualification - exact skill/model/tool/policy/eval profiles (S1 built 2026-10-12, S2a skill/tool currency gate and S2b drift recording built 2026-10-14, all unwired; S3 remains) | [#1334](https://github.com/seangalliher/ProbOS/issues/1334) | 1 |
>>>>>>> REPLACE
```

---

## Tests (written by Builders against the installed source)

Run focused, serial: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1287_s2b_drift_recorder.py tests/test_ad1287_s2a_profile_currency.py tests/test_ad1287_slot_qualification.py -n 0 -p no:randomly -q`. Every test asserts its own premise. Doubles are hand-written `_Fake*` classes; no mock library. Read source only with `read_bytes()`; never `.read_text()` on an expression containing `__file__`, never `inspect.getsource`.

### M1 `tests/test_ad1287_s2b_drift_recorder.py`

Reuse by import (do not copy): `_World`, `_variant`, `_in_state` (`tests/test_ad1287_slot_qualification.py`); `_evaluation` (`tests/test_ad1287_profile_qualification_store.py`); `_FakeSource`, `_SchemaTool`, `_codebase_query_tool`, `_write_skill`, `_started_catalog`, `_fixture`, `_current_source`, `_qualified`, `_CHANGED`, `_DECLARED_SKILL`, `_DECLARED_TOOL`, `_CHECKLIST`, `_CHECKLIST_CHANGED` (`tests/test_ad1287_s2a_profile_currency.py`); `_spec`, `_attempt` (`tests/test_ad1286_elastic_team_contract.py`); `_probos_imports` (`tests/test_ad1287_execution_profile.py`). Define a local `world` fixture as S2a does. `_FakeStore` notes each call and answers from what the test gives it. To make a fake answer, `dataclasses.replace` a real `ProfileQualification` read from a real store. Logger: `probos.cognitive.profile_drift_recorder`.

| # | Test | Asserts |
|---|---|---|
| 1 | `test_drift_invalidation_id_known_answer` | expected = `"drift-" + sha256(b"probos.execution_profile/drift_invalidation/v1\x00" + jcs.canonicalize({...six fields...}))`, built in the test with the literal domain; `len == 70`; `TypeAdapter(ElasticId).validate_python(id)` accepts it |
| 2 | `test_drift_invalidation_id_binds_every_field` (parametrize: `profile_ref`, `evidence_ref`, `kind`, `key`, `code`, `live`) | changing that one input gives another id; the same inputs twice give one id |
| 3 | `test_drift_invalidation_id_refuses_bad_input` (parametrize) | bad `profile_ref`; bad `evidence_ref`; `live=None`; a dict in place of the drift: exact `TypeError`, `args == ("drift_invalidation_input_invalid",)` |
| 4 | `test_records_skill_and_tool_drift_as_invalidations` | real store; `_FakeSource` answers `LiveSkill(_CHANGED, True)` for `code-review`, current for `audit-trail`, `_CHANGED` for the tool. Returns two `RecordedInvalidation`s, skill then tool; each `invalidation_id == drift_invalidation_id(ref, deciding.evidence_ref, drift)` and `reason_code` is the drift code. `get_qualification`: `invalidated`, `invalidation_reasons == ("component_drift_skill", "component_drift_tool_schema")` |
| 5 | `test_records_structurally_invalid_skill` | `LiveSkill(_DECLARED_SKILL, False)` -> one record with reason `component_structurally_invalid_skill`; status `invalidated` |
| 6 | `test_missing_and_unreadable_are_not_recorded` (parametrize: the four `component_missing_*` / `component_unreadable_*` answers) | returns `()`; status still `qualified`, reasons `()`; exactly one INFO record from the recorder's logger naming the code; with a spec put, `admit_current_qualified_attempt` refuses with that code (cross-check D5) |
| 7 | `test_mixed_drift_records_only_the_read_ones` | skill missing and tool drifted -> one record (the tool), one INFO record |
| 8 | `test_current_profile_records_nothing` | `_current_source` -> `()`; reasons `()`; the fake was asked once per component |
| 9 | `test_non_qualified_profile_is_not_read_or_written` (parametrize over `_in_state` states other than `qualified`) | `()`; the fake source was never asked; status and reasons unchanged |
| 10 | `test_unknown_and_malformed_references` | a valid unregistered ref -> exact `ProfileQualificationConflict`, `args == ("profile_unknown",)`, source not asked; `"x"` with a `_FakeStore` -> `ValueError("execution_profile_ref_invalid")` and the fake store was never asked |
| 11 | `test_store_answer_checks` (`_FakeStore`) | an answer whose `profile_ref` is another profile's -> `ValueError("profile_evidence_mismatch")`, no `invalidate_profile` call, source not asked; status `qualified` with `deciding=None` -> `()`, no call |
| 12 | `test_stale_replay_writes_nothing_new` | the first call records (seq `s`). A plain replay on the real store -> `()`. A `_StaleStore` (real `invalidate_profile`, `get_qualification` answering the qualification captured before the first call) -> the same `RecordedInvalidation` (id, seq `s`, time); reasons still length 1 |
| 13 | `test_same_drift_after_requalification_is_recorded_again` | E1, drift L recorded (id A); `_evaluation(ref, "eval-2")` recorded -> `qualified` (premise); same drift L -> id B != A, its seq > E2's seq, status `invalidated`; negative control: `drift_invalidation_id(ref, E1.evidence_ref, drift) == A` |
| 14 | `test_errors_propagate` | source raising `RuntimeError` -> the same object, nothing written; a `_FakeStore` whose second `invalidate_profile` raises -> the same object, and the first call was made |
| 15 | **`test_chain_real_drift_recorded_survives_restart_and_gate_refuses_until_requalified`** | real catalog + real registry produce the digests; profile for slot `review` registered and evaluated (E1) on the real store; spec put. One byte of `references/checklist.md` changes. `record_component_drift(world.qualifications, RegistryComponentSource(catalog, registry), ref)` -> one record `component_drift_skill`. Restart: new store instances and a new catalog; the old instance raises `ProfileQualificationStoreUnavailable` (premise). `get_qualification`: `invalidated`, reasons `("component_drift_skill",)`. The file is restored and `profile_drift == ()` (premise); the gate still refuses, `args == ("profile_status_invalidated",)`, and `get_attempt` is None. A replay of the recorder -> `()`. `_evaluation(ref, "eval-2")` recorded -> the gate admits, and `get_attempt` holds the exact ref |
| 16 | `test_imports_allowlisted_and_unwired` | ProbOS imports of the module (AST of `read_bytes`) are exactly `{elastic_team, profile_currency, profile_qualification_store}` under `probos.cognitive`; negative control: the walker flags a snippet importing `probos.tools`; premise: S1 #16's `_S1_MODULES` holds `profile_drift_recorder` and `_GATE_NAMES` holds `record_component_drift` |
| 17 | `test_duplicate_replay_does_not_invalidate_a_later_evaluation` | (review round 1, F1) real stores; E1 qualified, drift recorded (id I1); `_evaluation(ref, "eval-2")` recorded -> `qualified` (premise); `_StaleStore` answering the E1 qualification, same drift: returns the existing row (same id and `seq`), the status stays `qualified`, `invalidation_reasons == ()`, one invalidation row. Control: a stale recorder whose live digest differs writes a NEW row whose `seq` is greater than E2's, and the status becomes `invalidated` (a newly inserted row does apply to an evaluation recorded between the reads and the write) |
| 18 | `test_partial_failure_then_rerun_records_nothing_more` | (review round 1, F2) real store; skill and tool both drifted; a wrapper over the real store that raises `RuntimeError` on the second write -> the same exception object; after a restart the first row is durable and the status `invalidated` (premise); a rerun returns `()` with the source never asked; the S2a gate refuses `profile_status_invalidated`; after `_evaluation(ref, "eval-2")` a rerun records both live drifts against E2 |

## Mutation campaign of record

Run once, in M2, on the committed tree, serially (`-n 0 -p no:randomly`) with `tests/test_ad1287_s2b_drift_recorder.py`. Baseline first; abort if red. Mutate in place with a `.mutbak` sibling and restore in `finally`. Count each anchor first: it must occur exactly once in its file (CRLF tree). Not found = INERT; timeout = INVALID. Record the base commit and the sha256 of `profile_drift_recorder.py` and of the test file. A later edit to either invalidates only the mutants pinned to it. R4/R5 share an anchor; apply each alone.

| Id | File | Anchor | Replacement | Killer |
|---|---|---|---|---|
| R1 | `profile_drift_recorder.py` | `    if not is_sha256_ref(profile_ref):` | `    if False:` | M1 #10 |
| R2 | `profile_drift_recorder.py` | `    if qualification is None:` | `    if False:` | M1 #10 |
| R3 | `profile_drift_recorder.py` | `    if qualification.profile_ref != profile_ref or qualification.profile.content_ref() != profile_ref:` | `    if False:` | M1 #11 |
| R4 | `profile_drift_recorder.py` | `    if qualification.status != "qualified" or qualification.deciding is None:` | `    if qualification.deciding is None:` | M1 #9, #15 |
| R5 | `profile_drift_recorder.py` | `    if qualification.status != "qualified" or qualification.deciding is None:` | `    if qualification.status != "qualified":` | M1 #11 |
| R6 | `profile_drift_recorder.py` | `    evidence_ref = qualification.deciding.evidence_ref` | `    evidence_ref = profile_ref` | M1 #4 |
| R7 | `profile_drift_recorder.py` | `        if drift.code not in RECORDED_DRIFT_CODES:` | `        if False:` | M1 #6 |
| R8 | `profile_drift_recorder.py` | `            logger.info(` | `            logger.debug(` | M1 #6 |
| R9 | `profile_drift_recorder.py` | `        recorded.append(await store.invalidate_profile(profile_ref, invalidation_id, drift.code))` | `        recorded.append(await store.invalidate_profile(profile_ref, invalidation_id, "component_drift"))` | M1 #4 |
| R10 | `profile_drift_recorder.py` | `        "evidence_ref": evidence_ref,` | `        "evidence_ref": profile_ref,` | M1 #13 |
| R11 | `profile_drift_recorder.py` | `        "code": drift.code,` | `        "code": "x",` | M1 #2 |
| R12 | `profile_drift_recorder.py` | `        "live": drift.live,` | `        "live": None,` | M1 #2 |
| R13 | `profile_drift_recorder.py` | `        "kind": drift.kind,` | `        "kind": "",` | M1 #2 |
| R14 | `profile_drift_recorder.py` | `        "key": drift.key,` | `        "key": "",` | M1 #2 |
| R15 | `profile_drift_recorder.py` | `        "profile_ref": profile_ref,` | `        "profile_ref": evidence_ref,` | M1 #2 |
| R16 | `profile_drift_recorder.py` | `DRIFT_INVALIDATION_DOMAIN: Final = b"probos.execution_profile/drift_invalidation/v1\x00"` | same with `v2` | M1 #1 |
| R17 | `profile_drift_recorder.py` | `    return f"drift-{digest}"` | `    return digest` | M1 #1 |
| R18 | `profile_drift_recorder.py` | `        not is_sha256_ref(profile_ref)` | `        False` | M1 #3 |
| R19 | `profile_drift_recorder.py` | `        or not is_sha256_ref(evidence_ref)` | `        or False` | M1 #3 |
| R20 | `profile_drift_recorder.py` | `        or type(drift) is not ComponentDrift` | `        or False` | M1 #3 |
| R21 | `profile_drift_recorder.py` | `        or not is_sha256_ref(drift.live)` | `        or False` | M1 #3 |
| R22 | `profile_drift_recorder.py` | `        "component_drift_skill",` | `        "component_not_recorded_skill",` | M1 #4 |
| R23 | `profile_drift_recorder.py` | `        "component_structurally_invalid_skill",` | `        "component_not_recorded_structural",` | M1 #5 |
| R24 | `profile_drift_recorder.py` | `        "component_drift_tool_schema",` | `        "component_not_recorded_tool",` | M1 #4 |

Total 24. Anchor uniqueness was checked by reading the Section 1 text (no interpreter). The docstrings never put a code inside double quotes at an 8-space indent. `logger.info(` occurs once. `        not is_sha256_ref(profile_ref)` (8 spaces, then `not`) is not a substring of `    if not is_sha256_ref(profile_ref):`.

---

## What this does NOT change

- `execution_profile.py`, `profile_qualification_store.py` (no layout, table or method change), `profile_components.py`, `profile_currency.py`, `storage_declarations.py`, any AD-1286 file, `skill_catalog.py`, `tools/`, `model_registry.py`, `llm_client.py`, `config.py`.
- Runtime, startup, routers, events, HXI, store registry, architecture baseline. In the S1 and S2a test files, only S1 #16's two tuples change (Section 2).

## Do not build

- No sweeper, scheduler, startup wiring or call of the recorder or either gate under `src/` (S1 #16 pins it).
- No model or policy producer, no `ProfileComponentSource` method for them, no model version config field (D2, D3).
- No recording in `admit_current_qualified_attempt`; no edit to S1 or S2a source (both campaigns of record stand).
- No store method that enumerates profiles (A7); no layout change; no new table.
- No prompt or tool-implementation digests (R-5), no AD-1288 wiring, no signing (AD-1047), no R-1 `_open` extraction, no outcome learning (S3).
- No broad gate by a Builder; no `git add -A`.

## Obligations handed on

- **O-1 (AD-1288):** unchanged as amended by S2a: admission through `admit_current_qualified_attempt`.
- **O-2:** discharged for skills and tool schemas: detected (S2a), recorded and refused (S2b).
- **O-4 (new, AD-1288 #1335):** provision a worker only on the profile's declared model (provider, name) and under a lease matching its declared policy, or refuse. If drift should be recorded continuously, AD-1288 owns a sweeper that calls `record_component_drift` for the profile refs it holds (pinned or candidate refs; there is no enumerator, A7). It changes S1 #16 deliberately. The orchestrator records O-4 on #1335.
- **O-3:** unchanged (S3).
- **R-4, R-5, R-1, R-2, R-3:** unchanged.
- **R-6 (new):** the model version and the policy are declared-only. A provider alias can move under an unchanged name (Prior Art). The per-reply `answered_model` (`llm_client.py:2431`) is a post-hoc signal S3 or AD-1288 may compare.

## Acceptance criteria (S2b)

1. M1 green with `-n 0 -p no:randomly`; `probos.__file__` resolves inside this worktree's `src`; the S2a M2 file and S1's three test files green.
2. With the new file staged: `d:/ProbOS/.venv/Scripts/python.exe scripts/check_store_registry.py --check` and `d:/ProbOS/.venv/Scripts/python.exe scripts/check_architecture_principles.py --check` exit 0; `tests/test_layer_boundaries.py` green.
3. M1 #15 crosses the seam in one test: real catalog and registry -> real store evaluation -> drift recorded -> restart -> `invalidated` -> gate refuses even after restore -> requalification admits.
4. #1334 items covered, each with a named test: real-store restart tests cover invalidation by exact component drift (M1 #15); requalification is required after a bound skill or tool schema changes (M1 #13, #15); invalidated profiles cannot satisfy a slot (M1 #15). #1334 stays open for S3.
5. Every mutant KILLED by its named test in the single M2 campaign of record.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Hidden pins (enumerated)

| Id | Pin | Command | Effect here |
|---|---|---|---|
| H1 | S1 #16 not-wired scan | Read `tests/test_ad1287_slot_qualification.py:622-753` | Would fail on install (the new module imports two owned modules); Section 2 edits it |
| H2 | Architecture gate: `srp-size`, `layer-import`, `db-connect`, `unowned-task` | `scripts/check_architecture_principles.py:160-165` | One Protocol, no class over size, no `connect`, no `create_task` |
| H3 | Layer boundaries | `tests/test_layer_boundaries.py` | cognitive -> cognitive only |
| H4 | Store registry | `scripts/check_store_registry.py --check` | No SQL, table or `.db`: no declaration |
| H5 | Source-text tests (report-only) | `check_architecture_principles.py:168` | Tests use `read_bytes` |
| H6 | Identity goldens | Grep `probos\.execution_profile/` in `*.py` | Four existing domains untouched; one new domain, pinned by M1 #1 |
| H7 | Config reference/profile/facade | none: no config added (D2) | n/a |
| H8 | 37 `rglob("*.py")` scanners in 34 test files | Grep `rglob\("\*\.py"\)` in `tests/` (count) | Not run here; the pre-Builder full-suite diagnostic is the check |
| H9 | S2a's chain asserts the gate records nothing | `tests/test_ad1287_s2a_profile_currency.py:596-597` | Unchanged: the gate still writes nothing |
| H10 | S1 layout contract | `prompts/ad-1287-s1-execution-profile-qualification.md` D3a | Untouched: no table added |

## Prior Art and Blind Spots (2026-10-14)

| Source | Idea | Decision |
|---|---|---|
| [Kubernetes `Condition.observedGeneration`](https://v1-36.docs.kubernetes.io/docs/reference/kubernetes-api/definitions/condition-v1-meta/); [KEP-1623](https://www.kubernetes.dev/resources/keps/1623/) | a status names the generation it was computed against, so a stale one is detectable | **Adopted** as D4: the invalidation id binds the deciding evaluation |
| [Gateway API troubleshooting](https://gateway-api.sigs.k8s.io/docs/concepts/troubleshooting/) | observed generation lower than the current one means stale | **Adopted**: a replay against a superseded evaluation writes nothing new (M1 #12) |
| [Pay-i: managing model versions](https://docs.pay-i.com/docs/managing-model-versions); [MLflow aliases](https://mlflow.org/docs/latest/ml/model-registry) | a provider- or registry-controlled alias moves without a client change; pin a version, not an alias | **Adopted** as the reason D2 rejects a config label: it would assert, not observe. R-6 records the gap |
| Internal: S2a D5/D6 (`prompts/ad-1287-s2a-skill-tool-currency-gate.md:74-80`), S1 `invalidate_profile` idempotency (`profile_qualification_store.py:671-721`), AD-1327 `answered_model` | codes are already valid reasons; insert-only idempotency by id | **Adopted** |

**Blind spots:** (1) a missing or unreadable component is not recorded (D5), so `find_slot_candidates` can still list the profile; the gate refuses it. (2) A newly inserted invalidation applies to every evaluation recorded before it, including one recorded between the recorder's read and its write (conservative; a new evaluation requalifies); an id the store already holds answers its existing row, which applies only to the evaluations recorded before that row, so a duplicate replay does not invalidate a later evaluation (review round 1, F1; reproduced on real stores, pinned by M1 #17). (3) Concurrent recorders that saw different live states each write one row against the same evaluation. Growth is bounded because a recorder writes only to a `qualified` profile. (4) Restoring a component does not undo a recorded invalidation: requalification is required (intended; pinned in M1 #15). (5) A structurally invalid verdict comes from the catalog's cached entry (S2a blind spot 1) and is recorded durably. (6) There is no enumerator of profiles; a sweeper must hold refs (A7, O-4). (7) An id hash collision would surface as `profile_invalidation_conflict` (propagated). (8) The model and the policy can change undetected (R-6, O-4). (9) *After a durable partial prefix a rerun records nothing more (review round 1, F2; reproduced, pinned by M1 #18):* the first write makes the profile `invalidated`, so the guard exits before reading components; the remaining drifts are recorded only after a new evaluation qualifies the profile again and a rerun still sees them. (10) *An exact `ComponentDrift` built without its fields (review round 1, F3; injected reach, recorded)* raises `AttributeError` from `drift_invalidation_id` instead of the stable `TypeError`; the docstring states it.

## Verified Against Codebase (2026-10-14, base `f431dd0f`)

```
git log --oneline -5  -> f431dd0f chore(ledger)... ; d87fb2ad feat(profile-qualification): AD-1287 S2a ...
Read src/probos/cognitive/profile_currency.py:1-236 (whole)
  44 class ComponentUnreadable   56-64 ComponentDrift(kind, key, code, declared, live)
  67-72 ProfileComponentSource   148 async def profile_drift(profile, source)   199 admit_current_qualified_attempt
  17 "Nothing here records an invalidation or grants anything"
Read src/probos/cognitive/profile_qualification_store.py
  84 _REASON_RE = ^[a-z0-9][a-z0-9_]{0,63}$     180 ProfileQualificationConflict   205-212 RecordedInvalidation
  216-224 ProfileQualification(profile_ref, profile, status, deciding, invalidation_reasons, assessed_at_ms)
  420-440 _assess: invalidations with seq > deciding.seq   671-721 invalidate_profile (702-707 existing id answered)
  723-734 get_qualification   784-812 check_slot_qualification (status_<status>)   582/606/618/671/723/736 the only async methods
Read src/probos/cognitive/elastic_team.py:35 _ID_RE ^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$ ; 56-65 canonicalize_projection ; 76-78 is_sha256_ref
Read src/probos/cognitive/execution_profile.py:17-18 (AD-1288 leases authority), 120-146 ModelComponent/PolicyComponent
Read src/probos/cognitive/model_registry.py:32-43 ModelDescriptor ; 175-196 from_tier_models ("unknown" provider at 193)
Grep model_registry src -> startup/finalize.py:3883 runtime.model_registry = router.registry
Read src/probos/cognitive/llm_client.py:135-142 _echoed_model ; Grep -> 2431, 2491 answered_model=
Read src/probos/tools/registry.py:137-176 register(...) fields ; 255-320 resolve_permission (per agent, Captain grants)
Grep policy_digest|PolicyComponent|permission_profile src -> execution_profile.py:143,146,182 ; execution/authority.py:725,742
Read tests/test_ad1287_slot_qualification.py:88-163 (_World, _variant, _in_state), 622-753 (#16)
Read tests/test_ad1287_s2a_profile_currency.py:1-237 (helpers), 519-605 (chain), 596-597 (records nothing)
Grep async def (get_attempt|put_team_spec) elastic_team_store.py -> 537, 767
Read scripts/check_architecture_principles.py:160-168
scripts/ad_ceiling.py -> CEILING AD-1327 (three sources)
```

## Absence Verified (2026-10-14, base `f431dd0f`)

| Id | Claim | Run | Found | Holds |
|---|---|---|---|---|
| A1 | New names are free | Grep `record_component_drift\|profile_drift_recorder\|drift_invalidation\|DRIFT_INVALIDATION\|ProfileDriftStore` repo-wide excluding `prompts/` | 0 | yes |
| A2 | `ModelDescriptor` has no version | Grep `version` in `model_registry.py` (count) | 0 | yes |
| A3 | No model version in config | Grep `version` (case-insensitive) in `config.py` | 877, 879 (schema version tracking), 1292, 3771 (comments) | yes |
| A4 | No digest owner for a worker policy | Grep `policy_digest\|PolicyComponent\|permission_profile` in `src` | the S1 model fields; `execution/authority.py:725,742` (admission-policy file of the execution authority manifest) | yes |
| A5 | New domain is free | Grep `probos\.execution_profile/` in `*.py` | profile, evaluation, skill_resources, tool_schema only | yes |
| A6 | Nothing calls `invalidate_profile` | Grep `invalidate_profile\(` in `src` | the definition (671) and its docstring line (451) | yes |
| A7 | No enumerator of all profiles | Grep `def \|async def` in the store | `register_profile`, `get_profile`, `record_evaluation`, `invalidate_profile`, `get_qualification`, `find_slot_candidates` (per slot) | yes |

## Not verified

- Nothing was executed: the module does not exist on the base, so no known-answer vector, anchor count or test ran. The pre-Builder full-suite diagnostic is the first execution. **If a premise fails, stop and report rather than weaken an assertion.**
- That `jcs.canonicalize` accepts the six-string dict unchanged (it does for S2a's string-keyed dicts; M1 #1 asserts it).

## Tracking (M3, after the campaign; not installed)

- **`DECISIONS.md`**, directly above `### AD-1287 S2a` (`:44`): `### AD-1287 S2b -- Drift recorded as invalidations; model and policy declared-only (<date>, #1334)`. One line each for the slicing decision, D1-D7, O-4, R-6, and the campaign of record (base commit, two sha256, each mutant KILLED/INERT/INVALID with its killer).
- **`PROGRESS.md`**, directly under `# ProbOS Progress`: `**AD-1287 slice S2b BUILT (<date>), #1334, built and unwired -- ...**` with the file, the measured test count, "no file under `src/` calls the recorder or either gate (S1 #16)", and "S3 (outcome learning) remains; #1334 stays open".
- Roadmap: Section 3 (installed).
- Then: `d:/ProbOS/.venv/Scripts/python.exe scripts/gen_ad_ledger.py` and `d:/ProbOS/.venv/Scripts/python.exe scripts/gen_ad_ledger.py --check`.

=== BUILDER BRIEFS ===

### Brief M1 -- recorder tests and the chain (effort: max, at most 150 calls)

Contract: `prompts/ad-1287-s2b-drift-recording.md`. Source is installed and frozen: edit nothing under `src/` and no existing test. Write only `tests/test_ad1287_s2b_drift_recorder.py`, tests M1 #1-#16 (Tests section). Reuse the helpers listed there by import; do not copy them. Each test asserts its premise first. Compute the known-answer id in the test from the literal domain bytes and `probos.federation.ard.jcs.canonicalize`, never by calling the function under test. `_FakeStore` and `_StaleStore` are hand-written: they note calls, and they answer `dataclasses.replace`d copies of a real `ProfileQualification`. M1 #15 is the one seam test. It uses a real `CognitiveSkillCatalog` on `tmp_path/"skills"` (`_write_skill`), a real `ToolRegistry` holding `_codebase_query_tool()`, and `_World`. The digests are computed from the live objects, as in `tests/test_ad1287_s2a_profile_currency.py:530-545`. Restart with `world.stop()` / `world.start()` and a new catalog, then run the steps in the table. Log assertions use `caplog` with the logger `probos.cognitive.profile_drift_recorder`. Run the three files named under Tests with `-n 0 -p no:randomly`. A premise that fails: stop and report; do not weaken an assertion. Report counts and any skips with reasons.

### Brief M2 -- mutation campaign of record (effort: high, at most 150 calls)

On the committed M1 tree. Follow "Mutation campaign of record" exactly. Run the baseline green first. Count each anchor (exactly once). Apply one mutant at a time, with a `.mutbak` restore in `finally`, and run `tests/test_ad1287_s2b_drift_recorder.py` serially. Record the base commit, the two sha256 values, and per mutant KILLED / INERT / INVALID with the test that killed it. A survivor: stop and report the mutant and the test that should have killed it; do not edit source or the table.

### Brief M3 -- trackers (effort: high, at most 60 calls)

Apply "Tracking (M3)" with the measured counts and the M2 results, then run both ledger commands. Stage explicit paths only; never `git add -A`. No broad gate.
