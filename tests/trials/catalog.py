"""AD-1186 (#1123) Ship Trials: the versioned trial catalog and its predeclared policy.

A composition over the existing evaluators, not a new evaluation framework. A task names an
instrument that already exists (an AD-713 behavior contract, an AD-566a qualification test, the
AD-1143 ablation). This module loads and validates the catalog only.
It runs nothing, starts no runtime and calls no model.

The policy is report-only. ``validate_policy`` refuses any other mode, so this catalog declares no
blocking policy until the Captain decides one on #1123; a blocking mode needs a change to this
module, and editing the data file alone cannot declare one.

The Captain's trial rules (#1123, 2026-10-20) are schema, not prose: a task whose subject is a
crew agent must carry a disclosure (what the trial is and when it ends), must label its episodes
as trial episodes, and must keep its trust outcomes apart from duty trust or not apply them.

Content-hashed as AD-1143's goal sets are (``sigma_goals.sha256_file`` hashes the same bytes): a
run records ``TrialCatalog.sha256``, and a catalog that has been run is versioned by a new file
and ``catalog_version``, never edited in place.

No production imports. No file is read at import.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DATA_DIR = Path(__file__).resolve().parent / "data"
CATALOG_V1_PATH = DATA_DIR / "catalog_v1.yaml"
SUPPORTED_VERSION = 1

#: The task categories #1123's Decision names.
CATEGORIES: frozenset[str] = frozenset(
    {
        "multi_step_tool_work",
        "cross_department_synthesis",
        "bug_localization",
        "artifact_production",
        "capability_discovery",
        "grounded_refusal",
        "correction_recovery",
        "crew_session_crash_resume",
    }
)

#: Instruments that exist today. A behavior contract's result dict carries ``TestResult``'s
#: fields exactly; a qualification test returns a ``TestResult``; an AD-1143 ``ResultRow``
#: carries ``judge_failed``, and ``sigma_report.usable`` drops such a row.
INSTRUMENTS: frozenset[str] = frozenset({"behavior_contract", "qualification_test", "sigma_ablation"})

#: Who is under test. The trial rules bind a ``crew`` subject.
SUBJECTS: frozenset[str] = frozenset({"crew", "utility", "scripted"})
TRIAL_LABELLED = "trial_labelled"
TRUST_POLICIES: frozenset[str] = frozenset({"separate", "not_applied"})

#: #1123: these runs remain non-passing (inconclusive), never a pass.
REQUIRED_NON_PASSING: frozenset[str] = frozenset(
    {
        "skipped",
        "absent_data",
        "judge_unavailable",
        "infrastructure_failure",
        "contaminated",
        "incomparable",
    }
)

#: #1123: the fields a run's fingerprint must record.
REQUIRED_FINGERPRINT: frozenset[str] = frozenset(
    {
        "code_commit",
        "config_sha256",
        "model_identity",
        "fallback_model_identity",
        "knowledge_snapshot",
        "catalog_sha256",
        "rubric_sha256",
        "total_budget",
    }
)

#: Values the v1 policy must hold exactly.
POLICY_CONSTANTS: dict[str, str] = {
    "mode": "report_only",
    "design": "paired_by_task",
    "effect_size": "cohens_dz",
    "interval": "percentile_bootstrap",
    "significance_tests": "none",
    "missing_human_effort": "unknown",
    "evidence": "retain_raw",
}

#: The Captain's trial rules (#1123, 2026-10-20), stated exactly in the catalog.
CREW_RULES: dict[str, str] = {
    "disclosure_at_entry": "required",
    "awareness": "never_penalised",
    "trial_episodes": "labelled_not_discarded",
    "trial_trust": "separate_or_not_applied",
    "naive_measurement": "disclose_and_record_priming",
}

_TOP_KEYS = frozenset({"catalog_version", "policy", "crew_rules", "entries"})
_POLICY_KEYS = frozenset(POLICY_CONSTANTS) | frozenset(
    {"iterations", "alpha", "seed", "non_passing", "fingerprint"}
)
_ENTRY_REQUIRED = frozenset({"id", "category", "instrument", "ref", "subject"})
_ENTRY_KEYS = _ENTRY_REQUIRED | frozenset({"disclosure", "episodes", "trust"})
_ENTRY_ID = re.compile(r"^[a-z0-9][a-z0-9_.-]*$")


@dataclass(frozen=True)
class TrialPolicy:
    """The predeclared statistical and reporting policy."""

    mode: str
    iterations: int
    alpha: float
    seed: int
    non_passing: frozenset[str]
    fingerprint: frozenset[str]


@dataclass(frozen=True)
class TrialEntry:
    """One catalog task: an existing instrument, its subject and, for crew, its trial terms."""

    id: str
    category: str
    instrument: str
    ref: str
    subject: str
    disclosure_what: str = ""
    disclosure_ends: str = ""
    episodes: str = ""
    trust: str = ""


@dataclass(frozen=True)
class TrialCatalog:
    """A loaded, validated, content-hashed catalog."""

    version: int
    sha256: str
    path: Path
    policy: TrialPolicy
    entries: tuple[TrialEntry, ...]


def _mapping(value: Any, allowed: frozenset[str], required: frozenset[str], where: str) -> dict[str, Any]:
    """Return ``value`` as a mapping with no unknown and no missing key."""
    if not isinstance(value, dict):
        raise ValueError(f"{where}: expected a mapping")
    # YAML admits non-string keys; ordering by ``repr`` lists keys of mixed types.
    unknown = sorted(set(value) - allowed, key=repr)
    if unknown:
        raise ValueError(f"{where}: unknown keys {unknown}")
    absent = sorted(required - set(value))
    if absent:
        raise ValueError(f"{where}: missing keys {absent}")
    return value


def _names(value: Any, where: str) -> frozenset[str]:
    """Return ``value`` as a set of names; it must be a list of strings."""
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{where} must be a list of names")
    return frozenset(value)


def _one_of(value: Any, allowed: frozenset[str]) -> bool:
    """Return whether ``value`` is a string in ``allowed``.

    A YAML list or mapping gives ``False`` here, so the caller raises its ``ValueError``; testing
    membership directly would hash it and raise ``TypeError``.
    """
    return isinstance(value, str) and value in allowed


def validate_policy(value: Any, *, source: str) -> TrialPolicy:
    """Raise ``ValueError`` on any breach of the v1 policy."""
    policy = _mapping(value, _POLICY_KEYS, _POLICY_KEYS, f"{source}: policy")
    for key, expected in POLICY_CONSTANTS.items():
        if policy[key] != expected:
            raise ValueError(f"{source}: policy.{key} must be {expected!r}, not {policy[key]!r}")
    iterations, alpha, seed = policy["iterations"], policy["alpha"], policy["seed"]
    if type(iterations) is not int or iterations < 1000:
        raise ValueError(f"{source}: policy.iterations must be an integer of at least 1000")
    if type(alpha) is not float or not 0.0 < alpha < 1.0:
        raise ValueError(f"{source}: policy.alpha must be a float between 0 and 1")
    if type(seed) is not int:
        raise ValueError(f"{source}: policy.seed must be an integer")
    non_passing = _names(policy["non_passing"], f"{source}: policy.non_passing")
    dropped = sorted(REQUIRED_NON_PASSING - non_passing)
    if dropped:
        raise ValueError(f"{source}: policy.non_passing lacks {dropped}")
    fingerprint = _names(policy["fingerprint"], f"{source}: policy.fingerprint")
    unpinned = sorted(REQUIRED_FINGERPRINT - fingerprint)
    if unpinned:
        raise ValueError(f"{source}: policy.fingerprint lacks {unpinned}")
    return TrialPolicy(
        mode=policy["mode"],
        iterations=iterations,
        alpha=alpha,
        seed=seed,
        non_passing=non_passing,
        fingerprint=fingerprint,
    )


def validate_entry(value: Any, *, source: str) -> TrialEntry:
    """Raise ``ValueError`` on any breach; a crew task must carry rule 1's and rule 3's terms.

    A shape breach (not a mapping, an unknown or a missing key) is reported without the task's
    id, and an id that is not a lower-case slug is quoted as given; every later message begins
    ``<source>: entry <id>:``.
    """
    entry = _mapping(value, _ENTRY_KEYS, _ENTRY_REQUIRED, f"{source}: entry")
    entry_id = entry["id"]
    if not isinstance(entry_id, str) or not _ENTRY_ID.match(entry_id):
        raise ValueError(f"{source}: entry id {entry_id!r} is not a lower-case slug")
    where = f"{source}: entry {entry_id}"
    if not _one_of(entry["category"], CATEGORIES):
        raise ValueError(f"{where}: unknown category {entry['category']!r}")
    if not _one_of(entry["instrument"], INSTRUMENTS):
        raise ValueError(f"{where}: unknown instrument {entry['instrument']!r}")
    ref = entry["ref"]
    if not isinstance(ref, str) or not ref.strip():
        raise ValueError(f"{where}: ref must name the instrument's contract, test or goal set")
    if not _one_of(entry["subject"], SUBJECTS):
        raise ValueError(f"{where}: unknown subject {entry['subject']!r}")
    common = {
        "id": entry_id,
        "category": entry["category"],
        "instrument": entry["instrument"],
        "ref": ref,
        "subject": entry["subject"],
    }
    if entry["subject"] != "crew":
        return TrialEntry(**common)
    disclosure = entry.get("disclosure")
    if not isinstance(disclosure, dict) or set(disclosure) != {"what", "ends"}:
        raise ValueError(f"{where}: a crew task needs a disclosure of exactly 'what' and 'ends' (rule 1)")
    what, ends = disclosure["what"], disclosure["ends"]
    if not all(isinstance(text, str) and text.strip() for text in (what, ends)):
        raise ValueError(f"{where}: the disclosure must say what the trial is and when it ends (rule 1)")
    if entry.get("episodes") != TRIAL_LABELLED:
        raise ValueError(f"{where}: a crew task's episodes must be {TRIAL_LABELLED!r} (rule 3)")
    if not _one_of(entry.get("trust"), TRUST_POLICIES):
        raise ValueError(f"{where}: a crew task's trust must be one of {sorted(TRUST_POLICIES)} (rule 3)")
    return TrialEntry(
        **common,
        disclosure_what=what,
        disclosure_ends=ends,
        episodes=entry["episodes"],
        trust=entry["trust"],
    )


def load_catalog(path: Path = CATALOG_V1_PATH) -> TrialCatalog:
    """Load, validate and hash one catalog file; the hash covers the bytes parsed."""
    raw = path.read_bytes()
    source = path.name
    document = _mapping(yaml.safe_load(raw), _TOP_KEYS, _TOP_KEYS, source)
    version = document["catalog_version"]
    if type(version) is not int or version != SUPPORTED_VERSION:
        raise ValueError(f"{source}: catalog_version must be {SUPPORTED_VERSION}")
    if document["crew_rules"] != CREW_RULES:
        raise ValueError(f"{source}: crew_rules must state the Captain's trial rules exactly (#1123)")
    policy = validate_policy(document["policy"], source=source)
    if not isinstance(document["entries"], list):
        raise ValueError(f"{source}: entries must be a list")
    entries = tuple(validate_entry(item, source=source) for item in document["entries"])
    ids = [entry.id for entry in entries]
    duplicates = sorted({entry_id for entry_id in ids if ids.count(entry_id) > 1})
    if duplicates:
        raise ValueError(f"{source}: duplicate entry ids {duplicates}")
    return TrialCatalog(
        version=version,
        sha256=hashlib.sha256(raw).hexdigest(),
        path=path,
        policy=policy,
        entries=entries,
    )
