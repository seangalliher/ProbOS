"""AD-1299 S1a (#1352): repair candidate identity and evidence binding.

Pins ``src/probos/cognitive/repair_candidate.py``. The gate-receipt tests bind a
receipt written by the REAL producer, ``scripts/run_test_gate.py``
``_write_success_receipt``, never a hand-built dict, so the producer -> consumer
seam is crossed by execution (test 10).

Premise rule: every refusal or unavailability test that mutates a real receipt
first asserts that the UNMUTATED receipt binds, then asserts the exact reason
code. The module's check order is fixed, so the reason code proves which
boundary was reached; asserting only ``status != "present"`` would prove
nothing. Where a lenient reader (the stdlib defaults) would have accepted a
fixture, the test also asserts that, so the refusal is attributable to the one
rule under test and not to some other defect in the fixture.

S1a refuses evidence that contradicts the candidate in the facts it checks and
records a sha256 per piece of evidence: a receipt's covers its raw bytes, a
review set's covers only the candidate-bound five-field projection. An edit to
an unread receipt field still binds and changes the digest (test 14); a review
re-labelled within the five fields still binds and changes it (test 40); a
review attribute outside the five does not change it (test 41). It does not
authenticate the producer.
"""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import hashlib
import importlib.util
import json
import math
import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import pytest

from probos.cognitive.repair_candidate import (
    GATE_RECEIPT_SCHEMA_VERSION,
    MAX_RECEIPT_BYTES,
    MAX_REVIEWS,
    REASON_CODES,
    REPAIR_CANDIDATE_SCHEMA_VERSION,
    EvidenceLink,
    RepairCandidate,
    ReviewAttestation,
    bind_reviews as _module_bind_reviews,
    verify_gate_receipt,
)
from probos.federation.ard.jcs import canonicalize as jcs_canonicalize

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "run_test_gate.py"
MODULE_PATH = REPO_ROOT / "src" / "probos" / "cognitive" / "repair_candidate.py"
GATE_MODULE_NAME = "probos_test_ad1299_run_test_gate"
LABEL = "ad1299-s1a"
CANDIDATE_DOMAIN = b"probos.repair_candidate/candidate/v1\x00"
REVIEW_SET_DOMAIN = b"probos.repair_candidate/review_set/v1\x00"

_FIELDS = ("base_commit", "candidate_commit", "tree", "index_tree")


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def gate() -> Iterator[ModuleType]:
    """Load ``scripts/run_test_gate.py`` under a private module name.

    Registered in ``sys.modules`` before ``exec_module`` because the script's
    dataclasses re-read their annotations out of ``sys.modules`` (PEP 563). The
    private name keeps this load from interfering with ``test_run_test_gate``,
    and the registration is removed at teardown.
    """
    spec = importlib.util.spec_from_file_location(GATE_MODULE_NAME, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[GATE_MODULE_NAME] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.modules.pop(GATE_MODULE_NAME, None)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=ProbOS Tests", "-c", "user.email=tests@probos.invalid", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _rev(repo: Path, ref: str) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", ref], cwd=repo, check=True, capture_output=True, text=True,
    )
    return completed.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(root, "add", "tracked.txt")
    _git(root, "commit", "-q", "-m", "base")
    (root / "tracked.txt").write_text("candidate\n", encoding="utf-8")
    _git(root, "add", "tracked.txt")
    _git(root, "commit", "-q", "-m", "candidate")
    return root


def _candidate(repo: Path) -> RepairCandidate:
    return RepairCandidate(
        base_commit=_rev(repo, "HEAD~1"),
        candidate_commit=_rev(repo, "HEAD"),
        tree=_rev(repo, "HEAD^{tree}"),
        index_tree=_rev(repo, "HEAD^{tree}"),
    )


def _serialize(payload: object) -> bytes:
    """The producer's own serialization (``json.dump(indent=2, sort_keys=True)`` + newline)."""
    return json.dumps(payload, indent=2, sort_keys=True).encode("utf-8") + b"\n"


def _real_receipt(gate: ModuleType, repo: Path, *, label: str = LABEL) -> bytes:
    """A receipt written by the REAL producer, ``gate._write_success_receipt``.

    Calling the script's private helpers is the precedent of ``test_run_test_gate``
    (it calls ``gate._sha256_file``) and the only way to get a real receipt without
    running pytest inside pytest. The untracked ``logs/`` files do not change
    ``write-tree``, so ``head_tree == index_tree``.
    """
    gates = repo / "logs" / "gates"
    gates.mkdir(parents=True, exist_ok=True)
    manifest = gates / f"{label}.json"
    manifest.write_text("{}\n", encoding="utf-8")
    junit = gates / f"{label}.xml"
    junit.write_text("<testsuites/>\n", encoding="utf-8")
    collection = gates / f"{label}.collection.json"
    collection.write_text("{}\n", encoding="utf-8")
    snapshot = gate._snapshot_tree(repo)
    result = gate.GateResult(
        label=label, started_at="2026-10-11T00:00:00Z", finished_at="2026-10-11T00:00:01Z",
        elapsed_seconds=1.0, wrapper_exit_code=0, preflight_exit_code=0, pytest_exit_code=0,
        preflight_only=False, interrupted=False, error="", tree_changed=False,
        snapshot_before=snapshot, snapshot_after=snapshot, command=["pytest"], phases=[],
        sanitized_pytest_environment=[], summary="", log_path="", junit_path=str(junit),
        junit_totals=gate.JUnitTotals(tests=1, failures=0, errors=0, skipped=0, time_seconds=0.1),
        collection_path=str(collection),
        collection_totals=gate.CollectionTotals(nodes=1, workers=1, sha256="0" * 64),
    )
    receipt = gates / f"{label}.receipt.json"
    gate._write_success_receipt(
        receipt, repo_root=repo, result=result, source_snapshot=snapshot,
        manifest_path=manifest, junit_path=junit, collection_path=collection,
    )
    data = receipt.read_bytes()
    # Premise of every ``_mutate``: re-serializing the real receipt reproduces it (the producer
    # writes in text mode, so its newlines are CRLF on Windows), which means
    # a mutated receipt differs from the real one only by the mutation.
    assert _serialize(json.loads(data)) == data.replace(b"\r\n", b"\n")
    return data


def _walk(payload: dict[str, object], dotted_path: str) -> tuple[dict[str, object], str]:
    *parents, leaf = dotted_path.split(".")
    node = payload
    for key in parents:
        node = node[key]  # type: ignore[assignment]
    assert leaf in node, f"{dotted_path} is not a key of the real receipt"
    return node, leaf


def _mutate(receipt_bytes: bytes, dotted_path: str, value: object) -> bytes:
    payload = json.loads(receipt_bytes)
    node, leaf = _walk(payload, dotted_path)
    node[leaf] = value
    mutated = _serialize(payload)
    assert mutated != receipt_bytes.replace(b"\r\n", b"\n"), f"mutating {dotted_path} did not change the receipt"
    return mutated


def _drop(receipt_bytes: bytes, dotted_path: str) -> bytes:
    payload = json.loads(receipt_bytes)
    node, leaf = _walk(payload, dotted_path)
    del node[leaf]
    return _serialize(payload)


def _assert_binds(candidate: RepairCandidate, receipt_bytes: bytes) -> EvidenceLink:
    """The premise rule: the unmutated receipt binds this candidate."""
    link = verify_gate_receipt(candidate, receipt_bytes)
    assert (link.status, link.reason) == ("present", "gate_receipt_bound")
    return link


@dataclass(frozen=True)
class _Review:
    """A test-local record satisfying ``ReviewAttestation``."""

    review_attempt_id: str = "attempt-1"
    reviewer_id: str = "red_team"
    assignee_id: str = "builder"
    reviewed_tree: str = "c" * 40
    accepted: bool = True


def _ids(count: int = 6, width: int = 40) -> list[str]:
    return [char * width for char in "abcdef"][:count]


def _pure_candidate() -> RepairCandidate:
    """base ``a*40``, commit ``b*40``, tree and index ``c*40`` (``_Review``'s default tree)."""
    base, commit, tree = _ids(3)
    return RepairCandidate(base_commit=base, candidate_commit=commit, tree=tree, index_tree=tree)


def _for_another_tree(candidate: RepairCandidate) -> RepairCandidate:
    """The same commits against a tree that no receipt in these tests describes."""
    other = "e" * len(candidate.tree)
    return RepairCandidate(candidate.base_commit, candidate.candidate_commit, other, other)


def _two_independent_reviews() -> list[_Review]:
    return [
        _Review(review_attempt_id="attempt-1", reviewer_id="red_team"),
        _Review(review_attempt_id="attempt-2", reviewer_id="system_qa"),
    ]


def bind_reviews(
    candidate: RepairCandidate,
    reviews: object,
    *,
    required_reviewers: int = 1,
    expected_assignee: str = "builder",
) -> EvidenceLink:
    """S1b (C8) adapter. The real binder requires ``expected_assignee``; this adapter supplies the
    campaign builder ``builder`` (the ``_Review.assignee_id`` default) unless a case passes another.
    The S1a assignee probes vary ``assignee_id`` on purpose and now see ``review_assignee_mismatch``
    for a valid non-``builder`` value. C8 itself is pinned in
    tests/test_ad1299_s1b_evidence_completion.py, never through this adapter."""
    return _module_bind_reviews(
        candidate, reviews,  # type: ignore[arg-type]
        expected_assignee=expected_assignee, required_reviewers=required_reviewers,
    )


# ---------------------------------------------------------------------------
# Candidate identity
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("width", [40, 64], ids=["sha1-40", "sha256-64"])
def test_candidate_accepts_matching_full_object_ids(width: int) -> None:
    base, commit, tree = _ids(3, width)

    candidate = RepairCandidate(
        base_commit=base, candidate_commit=commit, tree=tree, index_tree=tree,
    )

    assert len(tree) == width
    assert (
        candidate.base_commit, candidate.candidate_commit, candidate.tree, candidate.index_tree,
    ) == (base, commit, tree, tree)
    assert candidate.projection() == {
        "schema_version": REPAIR_CANDIDATE_SCHEMA_VERSION,
        "base_commit": base,
        "candidate_commit": commit,
        "tree": tree,
        "index_tree": tree,
    }
    assert len(candidate.digest()) == 64


def test_candidate_refuses_index_tree_that_differs_from_tree() -> None:
    base, commit, tree, other = _ids(4)
    # premise: the same ids are accepted when the reviewed index IS the committed tree,
    # so the refusal below can only come from the index/tree comparison
    assert RepairCandidate(base, commit, tree, tree).index_tree == tree

    with pytest.raises(ValueError) as excinfo:
        RepairCandidate(base, commit, tree, other)

    assert excinfo.value.args == ("repair_candidate_uncommitted_index",)


_MALFORMED_IDS = {
    "empty": "",
    "none": None,
    "uppercase": "A" * 40,
    "short-39": "a" * 39,
    "long-41": "a" * 41,
    "trailing-newline": "a" * 40 + "\n",
    "int": 0,
    "bytes": b"a" * 40,
}
_VALID_IDS = {
    "base_commit": "a" * 40,
    "candidate_commit": "b" * 40,
    "tree": "c" * 40,
    "index_tree": "c" * 40,
}
# One field (the plan's case); ALL four fields at once, which keeps the lengths uniform so the
# mixed-length check cannot mask a format defect (``a*41`` or a trailing newline would otherwise
# be reported by the length check even if ``fullmatch`` were ``match``); and each remaining
# field alone with a same-length defect, so every field is validated.
_MALFORMED_ID_CASES = (
    [
        pytest.param(("candidate_commit",), value, id=f"one-field-{name}")
        for name, value in _MALFORMED_IDS.items()
    ]
    + [
        pytest.param(_FIELDS, value, id=f"all-fields-{name}")
        for name, value in _MALFORMED_IDS.items()
    ]
    + [
        pytest.param((field,), "A" * 40, id=f"{field}-uppercase")
        for field in _FIELDS
        if field != "candidate_commit"
    ]
)


@pytest.mark.parametrize(("fields", "bad"), _MALFORMED_ID_CASES)
def test_candidate_refuses_malformed_ids(fields: tuple[str, ...], bad: object) -> None:
    assert RepairCandidate(**_VALID_IDS).tree == "c" * 40  # premise: the unmodified ids construct

    with pytest.raises(ValueError) as excinfo:
        RepairCandidate(**{**_VALID_IDS, **{field: bad for field in fields}})

    assert excinfo.value.args == ("repair_candidate_field_invalid",)


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"base_commit": "a" * 64}, id="odd-base"),
        pytest.param({"candidate_commit": "b" * 64}, id="odd-commit"),
        pytest.param({"tree": "c" * 64, "index_tree": "c" * 64}, id="odd-tree-and-index"),
        pytest.param({"tree": "c" * 64}, id="tree-and-index-differ-in-length"),
    ],
)
def test_candidate_refuses_mixed_hash_lengths(overrides: dict[str, str]) -> None:
    # premise: each hash family is valid on its own, and every id is individually well formed,
    # so only the mixed-length check can be what fires (the message is the same as a format defect)
    RepairCandidate(**_VALID_IDS)
    RepairCandidate(**{field: "a" * 64 for field in _FIELDS})
    assert all(len(value) in (40, 64) for value in overrides.values())

    with pytest.raises(ValueError) as excinfo:
        RepairCandidate(**{**_VALID_IDS, **overrides})

    # ``tree-and-index-differ-in-length`` also differs in value: the length check is reported first
    assert excinfo.value.args == ("repair_candidate_field_invalid",)


def test_candidate_is_frozen() -> None:
    candidate = _pure_candidate()

    with pytest.raises(dataclasses.FrozenInstanceError):
        candidate.tree = "d" * 40  # type: ignore[misc]
    # An undeclared attribute is refused too. CPython 3.12 raises TypeError here rather than
    # FrozenInstanceError (the frozen __setattr__ of a slotted dataclass calls super() on the
    # pre-slots class), so the contract asserted is only that it is refused and nothing was set.
    with pytest.raises((AttributeError, TypeError)):
        candidate.unexpected = "x"  # type: ignore[attr-defined]
    assert not hasattr(candidate, "unexpected")

    assert candidate.tree == "c" * 40
    assert not hasattr(candidate, "__dict__")  # slotted


def test_candidate_digest_is_domain_separated_sha256_of_rfc8785() -> None:
    candidate = _pure_candidate()
    canonical = jcs_canonicalize(candidate.projection())

    assert candidate.canonical_bytes() == canonical
    assert candidate.digest() == hashlib.sha256(CANDIDATE_DOMAIN + canonical).hexdigest()
    assert candidate.digest() != hashlib.sha256(candidate.canonical_bytes()).hexdigest()


def test_candidate_canonical_bytes_golden() -> None:
    # Derived from RFC 8785, not read back from the implementation: members are ordered by the
    # UTF-16 code units of their NAMES (base_commit < candidate_commit < index_tree <
    # schema_version < tree), there is no insignificant whitespace, strings are unescaped ASCII,
    # and the integer 1 is the bare token ``1``.
    candidate = RepairCandidate(
        base_commit="a" * 40, candidate_commit="b" * 40, tree="c" * 40, index_tree="c" * 40,
    )

    assert candidate.canonical_bytes() == (
        b'{"base_commit":"' + b"a" * 40
        + b'","candidate_commit":"' + b"b" * 40
        + b'","index_tree":"' + b"c" * 40
        + b'","schema_version":1,"tree":"' + b"c" * 40 + b'"}'
    )


@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({"base_commit": "d" * 40}, id="base_commit"),
        pytest.param({"candidate_commit": "d" * 40}, id="candidate_commit"),
        pytest.param({"tree": "d" * 40, "index_tree": "d" * 40}, id="tree-and-index_tree"),
    ],
)
def test_candidate_digest_changes_with_each_field(changes: dict[str, str]) -> None:
    baseline = _pure_candidate()

    changed = dataclasses.replace(baseline, **changes)

    assert changed != baseline  # premise: the change took effect
    assert changed.digest() != baseline.digest()


def _imported_modules(node: ast.AST, *, module_scope_only: bool) -> set[str]:
    """Imported module names under ``node``; ``module_scope_only`` skips function bodies."""
    names: set[str] = set()

    def visit(parent: ast.AST, inside_function: bool) -> None:
        for child in ast.iter_child_nodes(parent):
            if not (module_scope_only and inside_function):
                if isinstance(child, ast.Import):
                    names.update(alias.name for alias in child.names)
                elif isinstance(child, ast.ImportFrom):
                    names.add("." * child.level + (child.module or ""))
            visit(
                child,
                inside_function or isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)),
            )

    visit(node, False)
    return names


def test_module_import_does_not_import_federation(tmp_path: Path) -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    at_import = _imported_modules(tree, module_scope_only=True)
    anywhere = _imported_modules(tree, module_scope_only=False)

    # (a) static. Premise: the scan sees real imports, so an empty probos set means something.
    assert {"hashlib", "json", "re"} <= at_import
    assert not [name for name in at_import if name.startswith(("probos", "scripts", "."))]
    # the one permitted probos import is lazy ...
    assert {name for name in anywhere if name.startswith(("probos", "scripts", "."))} == {
        "probos.federation.ard.jcs",
    }
    # ... and lives inside ``_canonicalize`` only
    canonicalize_function = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_canonicalize"
    )
    assert _imported_modules(canonicalize_function, module_scope_only=False) == {
        "probos.federation.ard.jcs",
    }
    for forbidden in ("probos.work_item_steps", "probos.workforce", "probos.cognitive.crew_session"):
        assert forbidden not in anywhere

    # (b) dynamic. The subprocess is pointed at THIS checkout's ``src`` so it cannot import another
    # checkout's copy of the module; the probe prints the module path and a positive control (the
    # flag flips when jcs IS imported), so the ``False`` below is a measurement, not a constant.
    probe = (
        "import sys\n"
        "import probos.cognitive.repair_candidate as module\n"
        "print(module.__file__)\n"
        "print('probos.federation' in sys.modules)\n"
        "import probos.federation.ard.jcs\n"
        "print('probos.federation' in sys.modules)\n"
    )
    pythonpath = os.pathsep.join(
        part for part in (str(REPO_ROOT / "src"), os.environ.get("PYTHONPATH", "")) if part
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        env={**os.environ, "PROBOS_DATA_DIR": str(tmp_path), "PYTHONPATH": pythonpath},
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    module_file, before_jcs, after_jcs = completed.stdout.splitlines()[-3:]
    assert Path(module_file).resolve() == MODULE_PATH.resolve()
    assert before_jcs == "False"
    assert after_jcs == "True"


# ---------------------------------------------------------------------------
# Gate receipt (real producer)
# ---------------------------------------------------------------------------


def test_real_receipt_binds_its_own_candidate(gate: ModuleType, repo: Path) -> None:
    candidate = _candidate(repo)
    receipt = _real_receipt(gate, repo)

    link = verify_gate_receipt(candidate, receipt)

    # The producer read git through its own helpers and the candidate was derived by
    # ``git rev-parse`` here, so binding is not a tautology: two derivations agree.
    payload = json.loads(receipt)
    assert payload["schema_version"] == GATE_RECEIPT_SCHEMA_VERSION
    assert payload["label"] == LABEL
    assert payload["tree"]["head"] == candidate.candidate_commit
    assert payload["tree"]["head_tree"] == payload["tree"]["index_tree"] == candidate.tree
    assert link.kind == "gate_receipt"
    assert link.status == "present"
    assert link.reason == "gate_receipt_bound"
    assert link.current is True
    assert link.evidence_sha256 == hashlib.sha256(receipt).hexdigest()
    assert link.candidate_digest == candidate.digest()
    labelled = verify_gate_receipt(candidate, receipt, expected_label=LABEL)
    assert (labelled.status, labelled.reason) == ("present", "gate_receipt_bound")


def test_receipt_for_an_older_tree_is_refused_as_stale(gate: ModuleType, repo: Path) -> None:
    first = _candidate(repo)
    receipt = _real_receipt(gate, repo)
    _assert_binds(first, receipt)  # premise: the receipt binds the candidate it was issued for
    (repo / "tracked.txt").write_text("third\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-q", "-m", "third")
    second = _candidate(repo)
    assert second.tree != first.tree  # premise: the committed tree really moved

    link = verify_gate_receipt(second, receipt)

    assert (link.status, link.reason) == ("refused", "gate_receipt_tree_mismatch")
    assert link.current is False


def test_receipt_for_same_tree_other_commit_is_refused(gate: ModuleType, repo: Path) -> None:
    first = _candidate(repo)
    receipt = _real_receipt(gate, repo)
    _assert_binds(first, receipt)  # premise: the receipt binds the candidate it was issued for
    _git(repo, "commit", "-q", "--allow-empty", "-m", "again")
    assert _rev(repo, "HEAD^{tree}") == first.tree  # premise: the tree is unchanged
    second = _candidate(repo)
    assert second.candidate_commit != first.candidate_commit  # premise: another commit

    link = verify_gate_receipt(second, receipt)

    assert (link.status, link.reason) == ("refused", "gate_receipt_commit_mismatch")
    assert link.current is False


def test_receipt_with_uncommitted_index_is_refused(gate: ModuleType, repo: Path) -> None:
    candidate = _candidate(repo)
    receipt = _real_receipt(gate, repo)
    _assert_binds(candidate, receipt)  # premise: the unmutated receipt binds

    tampered = _mutate(receipt, "tree.index_tree", "d" * 40)

    link = verify_gate_receipt(candidate, tampered)

    assert (link.status, link.reason) == ("refused", "gate_receipt_uncommitted_index")
    assert link.current is False
    # Check order: an uncommitted index is judged before the tree, and only after clean success.
    elsewhere = _for_another_tree(candidate)
    assert verify_gate_receipt(elsewhere, receipt).reason == "gate_receipt_tree_mismatch"  # premise
    assert verify_gate_receipt(elsewhere, tampered).reason == "gate_receipt_uncommitted_index"
    failed = _mutate(tampered, "status.pytest_exit_code", 1)
    assert verify_gate_receipt(candidate, failed).reason == "gate_receipt_not_success"


def test_edited_receipt_changes_evidence_digest(gate: ModuleType, repo: Path) -> None:
    """Specified behaviour, not a gap (Amendment 1, F2): an edit to a field S1a does not read binds.

    The canonical statement (Amendment 2): S1a refuses a receipt or review set that contradicts the
    candidate in the facts it checks (commit, tree, status, schema and reviewer independence, plus the
    label when one is expected). It records a sha256 for each piece of evidence: for a receipt, the
    SHA-256 of the supplied raw bytes, so any change to those bytes changes it; for a review set, a
    domain-separated SHA-256 of the candidate-bound projection of five review fields (attempt id,
    reviewer id, assignee id, reviewed tree, accepted), so a change to those five fields changes it
    and a change to any other review attribute does not. A consumer that retained an earlier trusted
    digest can therefore detect a change within what each digest covers. S1a does not authenticate
    the producer, does not assert that unread fields are valid, and does not exclude a writer running
    under ProbOS's own OS identity.

    ``finished_at`` is not read, so the edited receipt still binds; the only trace of the edit is
    the different ``evidence_sha256``, which a consumer holding the earlier digest can compare.
    """
    candidate = _candidate(repo)
    receipt = _real_receipt(gate, repo)
    original = _assert_binds(candidate, receipt)  # premise: the unmutated receipt binds
    edited_bytes = _mutate(receipt, "finished_at", "2026-10-11T23:59:59Z")

    edited = verify_gate_receipt(candidate, edited_bytes)

    # a field S1a does not read: still binds (specified); only the recorded digest changes
    assert (edited.status, edited.reason) == ("present", "gate_receipt_bound")
    assert edited.evidence_sha256 == hashlib.sha256(edited_bytes).hexdigest()
    assert edited.evidence_sha256 != original.evidence_sha256
    # the digest is over the bytes: a cosmetic change moves it too
    padded = verify_gate_receipt(candidate, receipt + b"\n")
    assert padded.status == "present"
    assert padded.evidence_sha256 != original.evidence_sha256


_NOT_SUCCESS = {
    "wrapper_exit_code=1": ("status.wrapper_exit_code", 1),
    "preflight_exit_code=2": ("status.preflight_exit_code", 2),
    "pytest_exit_code=1": ("status.pytest_exit_code", 1),
    "preflight_only=True": ("status.preflight_only", True),
    "tree_changed=True": ("status.tree_changed", True),
    "tests=0": ("junit.totals.tests", 0),
    "failures=1": ("junit.totals.failures", 1),
    "errors=1": ("junit.totals.errors", 1),
}


@pytest.mark.parametrize(("path", "value"), list(_NOT_SUCCESS.values()), ids=list(_NOT_SUCCESS))
def test_receipt_not_describing_clean_success_is_refused(
    gate: ModuleType, repo: Path, path: str, value: object,
) -> None:
    candidate = _candidate(repo)
    receipt = _real_receipt(gate, repo)
    _assert_binds(candidate, receipt)  # premise: the unmutated receipt binds

    mutated = _mutate(receipt, path, value)

    link = verify_gate_receipt(candidate, mutated)

    # a receipt whose shape is otherwise intact reaches the success predicate, not the malformed one
    assert (link.status, link.reason) == ("refused", "gate_receipt_not_success")
    assert link.current is False
    # Check order: success is judged before the tree and commit the receipt names
    assert verify_gate_receipt(_for_another_tree(candidate), mutated).reason == "gate_receipt_not_success"


@pytest.mark.parametrize(
    ("version", "equals_one_loosely"),
    [
        pytest.param(2, False, id="int-2"),
        pytest.param(0, False, id="int-0"),
        pytest.param("1", False, id="str-1"),
        pytest.param(True, True, id="bool-true"),
        pytest.param(1.0, True, id="float-1.0"),
    ],
)
def test_receipt_schema_version_other_than_int_one_is_refused(
    gate: ModuleType, repo: Path, version: object, equals_one_loosely: bool,
) -> None:
    candidate = _candidate(repo)
    receipt = _real_receipt(gate, repo)
    _assert_binds(candidate, receipt)  # premise: the unmutated receipt (schema_version 1) binds
    # ``True == 1`` and ``1.0 == 1`` in Python: only an exact-int check refuses them
    assert (version == 1) is equals_one_loosely

    mutated = _mutate(receipt, "schema_version", version)

    link = verify_gate_receipt(candidate, mutated)

    assert (link.status, link.reason) == ("refused", "gate_receipt_schema_unsupported")
    assert link.current is False
    # Check order: the schema is judged before the shape, so a receipt of another schema that is
    # also missing its tree is an unsupported schema, never a malformed receipt
    assert verify_gate_receipt(candidate, _drop(mutated, "tree")).reason == "gate_receipt_schema_unsupported"


def test_receipt_label_mismatch_is_refused(gate: ModuleType, repo: Path) -> None:
    candidate = _candidate(repo)
    receipt = _real_receipt(gate, repo)
    _assert_binds(candidate, receipt)  # premise: with no expected label the receipt binds
    matching = verify_gate_receipt(candidate, receipt, expected_label=LABEL)
    assert (matching.status, matching.reason) == ("present", "gate_receipt_bound")  # premise: the right label binds

    link = verify_gate_receipt(candidate, receipt, expected_label="other")

    assert (link.status, link.reason) == ("refused", "gate_receipt_label_mismatch")
    assert link.current is False
    # Check order: the label is judged before success, so a failed gate for another label is a label mismatch
    failed = _mutate(receipt, "status.pytest_exit_code", 1)
    assert verify_gate_receipt(candidate, failed).reason == "gate_receipt_not_success"  # premise
    assert verify_gate_receipt(candidate, failed, expected_label="other").reason == "gate_receipt_label_mismatch"


def test_receipt_absent_or_empty_is_unavailable() -> None:
    candidate = _pure_candidate()

    absent = verify_gate_receipt(candidate, None)
    empty = verify_gate_receipt(candidate, b"")

    assert (absent.status, absent.reason, absent.evidence_sha256) == (
        "unavailable", "gate_receipt_absent", "",
    )
    assert (empty.status, empty.reason, empty.evidence_sha256) == (
        "unavailable", "gate_receipt_empty", "",
    )
    assert absent.candidate_digest == empty.candidate_digest == candidate.digest()
    assert absent.current is False and empty.current is False


def test_receipt_oversized_is_unavailable() -> None:
    candidate = _pure_candidate()
    # premise: a receipt of exactly the cap is read (and is merely not JSON), so the verdict
    # below is the size comparison and not an earlier or later check
    at_cap = verify_gate_receipt(candidate, b" " * MAX_RECEIPT_BYTES)
    assert (at_cap.status, at_cap.reason) == ("unavailable", "gate_receipt_malformed")

    link = verify_gate_receipt(candidate, b" " * (MAX_RECEIPT_BYTES + 1))

    assert (link.status, link.reason) == ("unavailable", "gate_receipt_oversized")
    assert link.evidence_sha256 == ""
    assert link.current is False


@dataclass(frozen=True)
class _MalformedCase:
    build: Callable[[bytes], bytes]
    premise: Callable[[bytes, bytes], None]


def _premise_differs(raw: bytes, real: bytes) -> None:
    assert raw != real


def _premise_not_json(raw: bytes, real: bytes) -> None:
    with pytest.raises(json.JSONDecodeError):
        json.loads(raw)


def _premise_array_root(raw: bytes, real: bytes) -> None:
    assert json.loads(raw) == []  # valid JSON whose root is not an object


def _premise_null_root(raw: bytes, real: bytes) -> None:
    assert json.loads(raw) is None  # valid JSON whose root is not an object, and not a container


def _premise_invalid_utf8(raw: bytes, real: bytes) -> None:
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")


def _premise_invalid_utf8_in_unread_field(raw: bytes, real: bytes) -> None:
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")
    lenient = json.loads(raw.decode("utf-8", errors="replace"))
    assert lenient["tree"] == json.loads(real)["tree"]  # a lenient decoder would read the whole receipt


def _premise_duplicate_key(raw: bytes, real: bytes) -> None:
    assert raw.count(b'"schema_version"') == 2
    assert json.loads(raw) == json.loads(real)  # last-wins parsing reads the receipt that binds


def _premise_nan_in_read_field(raw: bytes, real: bytes) -> None:
    assert math.isnan(json.loads(raw)["junit"]["totals"]["tests"])


def _premise_nan_in_unread_field(raw: bytes, real: bytes) -> None:
    lenient = json.loads(raw)
    assert math.isnan(lenient["finished_at"])
    assert {k: v for k, v in lenient.items() if k != "finished_at"} == {
        k: v for k, v in json.loads(real).items() if k != "finished_at"
    }  # ``finished_at`` is not read: only the NaN refusal can make this receipt malformed


def _premise_bom(raw: bytes, real: bytes) -> None:
    assert raw.startswith(b"\xef\xbb\xbf")
    assert json.loads(raw) == json.loads(real)  # the stdlib detects the BOM: a lenient reader binds


def _premise_false_is_zero(raw: bytes, real: bytes) -> None:
    exit_code = json.loads(raw)["status"]["wrapper_exit_code"]
    assert exit_code is False and exit_code == 0  # ``False == 0``: only a strict int check refuses it


def _premise_deep_nesting(raw: bytes, real: bytes) -> None:
    # the C scanner's recursion guard raises RecursionError, which is NOT a ValueError, so the
    # parser must catch it explicitly for "bad evidence never raises" to hold
    with pytest.raises(RecursionError):
        json.loads(raw)


def _duplicate_top_level_key(real: bytes) -> bytes:
    assert real.startswith(b"{")
    return b'{"schema_version": 1,' + real[1:]


def _nan_for_junit_tests(real: bytes) -> bytes:
    assert real.count(b'"tests": 1,') == 1
    return real.replace(b'"tests": 1,', b'"tests": NaN,')


def _nan_for_unread_field(real: bytes) -> bytes:
    marker = b'"finished_at": "2026-10-11T00:00:01Z"'
    assert real.count(marker) == 1
    return real.replace(marker, b'"finished_at": NaN')


def _invalid_utf8_in_unread_field(real: bytes) -> bytes:
    marker = b'"finished_at": "2026-10-11T00:00:01Z"'
    assert real.count(marker) == 1
    return real.replace(marker, b'"finished_at": "2026-10-11T00:00:01\xffZ"')


_MALFORMED_CASES = {
    "not-json": _MalformedCase(lambda real: b"not json", _premise_not_json),
    "array-root": _MalformedCase(lambda real: b"[]", _premise_array_root),
    "invalid-utf8": _MalformedCase(lambda real: b"\xff\xfe", _premise_invalid_utf8),
    "duplicate-top-level-key": _MalformedCase(_duplicate_top_level_key, _premise_duplicate_key),
    "nan-for-junit-tests": _MalformedCase(_nan_for_junit_tests, _premise_nan_in_read_field),
    "bom-prefixed-receipt": _MalformedCase(lambda real: b"\xef\xbb\xbf" + real, _premise_bom),
    "no-tree": _MalformedCase(lambda real: _drop(real, "tree"), _premise_differs),
    "head-is-not-an-object-id": _MalformedCase(
        lambda real: _mutate(real, "tree.head", "HEAD"), _premise_differs,
    ),
    "wrapper-exit-code-false": _MalformedCase(
        lambda real: _mutate(real, "status.wrapper_exit_code", False), _premise_false_is_zero,
    ),
    "manifest-sha256-abc": _MalformedCase(
        lambda real: _mutate(real, "manifest.sha256", "abc"), _premise_differs,
    ),
    "no-schema-version": _MalformedCase(lambda real: _drop(real, "schema_version"), _premise_differs),
    "deeply-nested-array": _MalformedCase(lambda real: b"[" * 200_000, _premise_deep_nesting),
    # Added so every refusal rule has a fixture a lenient reader would accept: NaN in a field the
    # module does not read, and invalid UTF-8 in one (the stdlib defaults would bind both).
    "nan-in-unread-field": _MalformedCase(_nan_for_unread_field, _premise_nan_in_unread_field),
    "invalid-utf8-in-unread-field": _MalformedCase(
        _invalid_utf8_in_unread_field, _premise_invalid_utf8_in_unread_field,
    ),
    "label-is-not-a-str": _MalformedCase(lambda real: _mutate(real, "label", 7), _premise_differs),
    "no-junit-tests-total": _MalformedCase(
        lambda real: _drop(real, "junit.totals.tests"), _premise_differs,
    ),
    "head-with-trailing-newline": _MalformedCase(
        lambda real: _mutate(real, "tree.head", "a" * 40 + "\n"), _premise_differs,
    ),
    "preflight-only-is-a-string": _MalformedCase(
        lambda real: _mutate(real, "status.preflight_only", "false"), _premise_differs,
    ),
    "junit-sha256-abc": _MalformedCase(
        lambda real: _mutate(real, "junit.sha256", "abc"), _premise_differs,
    ),
    "collection-sha256-abc": _MalformedCase(
        lambda real: _mutate(real, "collection.sha256", "abc"), _premise_differs,
    ),
    "null-root": _MalformedCase(
        lambda real: b"null", _premise_null_root,
    ),
}


@pytest.mark.parametrize("case", list(_MALFORMED_CASES.values()), ids=list(_MALFORMED_CASES))
def test_receipt_malformed_is_unavailable(gate: ModuleType, repo: Path, case: _MalformedCase) -> None:
    candidate = _candidate(repo)
    real = _real_receipt(gate, repo)
    _assert_binds(candidate, real)  # premise: the unmutated receipt binds
    raw = case.build(real)
    case.premise(raw, real)  # premise: this fixture reaches its own boundary

    link = verify_gate_receipt(candidate, raw)

    assert (link.status, link.reason) == ("unavailable", "gate_receipt_malformed")
    assert link.current is False
    # the bytes were read: the verdict is not absent, empty or oversized
    assert link.evidence_sha256 == hashlib.sha256(raw).hexdigest()


def test_receipt_wrong_argument_types_raise() -> None:
    candidate = _pure_candidate()
    # premise: valid arguments never raise, even for evidence that is useless
    assert verify_gate_receipt(candidate, b"{}", expected_label="x").status == "unavailable"

    for bad_receipt in ("{}", bytearray(b"{}"), memoryview(b"{}")):
        with pytest.raises(TypeError) as excinfo:
            verify_gate_receipt(candidate, bad_receipt)  # type: ignore[arg-type]
        assert excinfo.value.args == ("gate_receipt_bytes_required",)

    with pytest.raises(TypeError) as excinfo:
        verify_gate_receipt({"base_commit": "a" * 40}, b"{}")  # type: ignore[arg-type]
    assert excinfo.value.args == ("repair_candidate_required",)

    for bad_label in ("", 7):
        with pytest.raises(ValueError) as excinfo:
            verify_gate_receipt(candidate, b"{}", expected_label=bad_label)  # type: ignore[arg-type]
        assert excinfo.value.args == ("gate_receipt_label_invalid",)
    # a programming error raises whatever the evidence is, even when it is absent
    with pytest.raises(ValueError) as excinfo:
        verify_gate_receipt(candidate, None, expected_label="")
    assert excinfo.value.args == ("gate_receipt_label_invalid",)


_EXPECTED_REASON_CODES = frozenset({
    "gate_receipt_bound",
    "gate_receipt_absent",
    "gate_receipt_empty",
    "gate_receipt_oversized",
    "gate_receipt_malformed",
    "gate_receipt_schema_unsupported",
    "gate_receipt_label_mismatch",
    "gate_receipt_not_success",
    "gate_receipt_uncommitted_index",
    "gate_receipt_tree_mismatch",
    "gate_receipt_commit_mismatch",
    "review_set_bound",
    "review_set_absent",
    "review_set_oversized",
    "review_malformed",
    "review_insufficient",
    "review_attempt_duplicate",
    "review_assignee_mismatch",
    "review_not_independent",
    "review_not_accepted",
    "review_tree_mismatch",
})


def _links_for_every_reason(gate: ModuleType, repo: Path) -> list[EvidenceLink]:
    """One link per reason code, each produced by the public verifiers."""
    candidate = _candidate(repo)
    real = _real_receipt(gate, repo)
    width = len(candidate.tree)
    other_tree = _for_another_tree(candidate)
    other_commit = RepairCandidate(
        candidate.base_commit, "e" * width, candidate.tree, candidate.tree,
    )
    pure = _pure_candidate()
    first = _Review(review_attempt_id="attempt-1", reviewer_id="red_team")
    second = _Review(review_attempt_id="attempt-2", reviewer_id="system_qa")
    return [
        verify_gate_receipt(candidate, real),
        verify_gate_receipt(candidate, None),
        verify_gate_receipt(candidate, b""),
        verify_gate_receipt(candidate, b" " * (MAX_RECEIPT_BYTES + 1)),
        verify_gate_receipt(candidate, b"not json"),
        verify_gate_receipt(candidate, _mutate(real, "schema_version", 2)),
        verify_gate_receipt(candidate, real, expected_label="other"),
        verify_gate_receipt(candidate, _mutate(real, "status.pytest_exit_code", 1)),
        verify_gate_receipt(candidate, _mutate(real, "tree.index_tree", "d" * width)),
        verify_gate_receipt(other_tree, real),
        verify_gate_receipt(other_commit, real),
        bind_reviews(pure, [first, second], required_reviewers=2),
        bind_reviews(pure, None),
        bind_reviews(
            pure,
            [
                _Review(review_attempt_id=f"attempt-{n}", reviewer_id=f"reviewer-{n}")
                for n in range(MAX_REVIEWS + 1)
            ],
        ),
        bind_reviews(pure, [object()]),  # type: ignore[list-item]
        bind_reviews(pure, [first, dataclasses.replace(second, reviewer_id="red_team")], required_reviewers=2),
        bind_reviews(pure, [first, dataclasses.replace(second, review_attempt_id="attempt-1")]),
        bind_reviews(pure, [dataclasses.replace(first, reviewer_id="builder")]),
        bind_reviews(pure, [dataclasses.replace(first, accepted=False)]),
        bind_reviews(pure, [dataclasses.replace(first, reviewed_tree="e" * 40)]),
        bind_reviews(pure, [dataclasses.replace(first, assignee_id="someone_else")]),
    ]


def test_reason_codes_are_pinned(gate: ModuleType, repo: Path) -> None:
    assert len(_EXPECTED_REASON_CODES) == 21
    assert REASON_CODES == _EXPECTED_REASON_CODES
    assert (
        REPAIR_CANDIDATE_SCHEMA_VERSION, GATE_RECEIPT_SCHEMA_VERSION, MAX_RECEIPT_BYTES, MAX_REVIEWS,
    ) == (1, 1, 1_048_576, 32)

    links = _links_for_every_reason(gate, repo)

    # every code in the pinned set is reachable through the public verifiers, none outside it is
    # produced, and each link is internally consistent about its kind, status and current flag
    produced = [link.reason for link in links]
    assert len(produced) == len(set(produced)) == 21
    assert set(produced) == REASON_CODES
    for link in links:
        assert link.reason in REASON_CODES
        assert link.reason.startswith("gate_receipt_" if link.kind == "gate_receipt" else "review_")
        assert link.current is (link.status == "present")
    assert {link.reason for link in links if link.status == "present"} == {
        "gate_receipt_bound", "review_set_bound",
    }

    # EvidenceLink is a report, not an authority token: an inconsistent construction is refused.
    # premise: consistent constructions are accepted, so each refusal below is its one defect.
    digest = "0" * 64
    EvidenceLink("gate_receipt", "present", "gate_receipt_bound", digest)
    EvidenceLink("review_set", "unavailable", "review_set_absent", digest, "1" * 64)
    inconsistent = [
        ("gate_receipt", "present", "gate_receipt_not_success", digest),  # status contradicts the reason
        ("gate_receipt", "present", "review_set_bound", digest),  # a review reason on a gate_receipt kind
        ("review_set", "present", "gate_receipt_bound", digest),  # a gate reason on a review_set kind
        ("other", "present", "gate_receipt_bound", digest),  # unknown kind
        ("gate_receipt", "present", "gate_receipt_unknown", digest),  # reason outside REASON_CODES
        ("gate_receipt", "present", ["gate_receipt_bound"], digest),  # unhashable reason: ValueError, not TypeError
        ("gate_receipt", "present", "gate_receipt_bound", "0" * 63),  # candidate digest too short
        ("gate_receipt", "present", "gate_receipt_bound", "A" * 64),  # candidate digest not lowercase
        ("gate_receipt", "present", "gate_receipt_bound", digest + "\n"),  # trailing newline
        ("gate_receipt", "present", "gate_receipt_bound", None),  # candidate digest not a str
        ("gate_receipt", "present", "gate_receipt_bound", digest, "xyz"),  # evidence digest malformed
        ("gate_receipt", "present", "gate_receipt_bound", digest, "1" * 64 + "\n"),
        ("gate_receipt", "present", "gate_receipt_bound", digest, 5),  # evidence digest not a str
    ]
    for arguments in inconsistent:
        try:
            EvidenceLink(*arguments)  # type: ignore[arg-type]
        except ValueError as error:
            assert error.args == ("evidence_link_invalid",), arguments
        else:
            pytest.fail(f"an inconsistent link was accepted: {arguments!r}")


# ---------------------------------------------------------------------------
# Review set
# ---------------------------------------------------------------------------


def _review_record(review: _Review) -> dict[str, object]:
    return {
        "review_attempt_id": review.review_attempt_id,
        "reviewer_id": review.reviewer_id,
        "assignee_id": review.assignee_id,
        "reviewed_tree": review.reviewed_tree,
        "accepted": review.accepted,
    }


def test_independent_accepted_reviews_bind() -> None:
    candidate = _pure_candidate()
    reviews = _two_independent_reviews()
    assert {review.reviewer_id for review in reviews} == {"red_team", "system_qa"}
    assert {review.assignee_id for review in reviews} == {"builder"}

    link = bind_reviews(candidate, reviews, required_reviewers=2)

    assert link.kind == "review_set"
    assert (link.status, link.reason) == ("present", "review_set_bound")
    assert link.current is True
    assert len(link.evidence_sha256) == 64
    assert link.candidate_digest == candidate.digest()
    # The evidence digest, derived independently: domain + canonical JSON (ASCII keys and no
    # floats, where RFC 8785 and the stdlib's sorted compact form coincide) of the candidate
    # digest and the reviews ordered by attempt id.
    expected = hashlib.sha256(
        REVIEW_SET_DOMAIN
        + json.dumps(
            {
                "schema_version": 1,
                "candidate": candidate.digest(),
                "reviews": [_review_record(review) for review in reviews],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
    ).hexdigest()
    assert link.evidence_sha256 == expected
    # one reviewer would suffice for the default bound
    assert bind_reviews(candidate, reviews[:1]).status == "present"


def test_self_review_is_refused() -> None:
    candidate = _pure_candidate()
    independent = _Review(reviewer_id="red_team", assignee_id="builder")
    # premise: the same review by a different reviewer binds
    assert bind_reviews(candidate, [independent]).status == "present"
    self_review = dataclasses.replace(independent, reviewer_id="builder")

    link = bind_reviews(candidate, [self_review])

    assert (link.status, link.reason) == ("refused", "review_not_independent")
    assert link.current is False
    assert len(link.evidence_sha256) == 64  # the set was readable: this is a refusal, not unavailability
    # independence is judged before acceptance and tree
    worse = dataclasses.replace(self_review, accepted=False, reviewed_tree="e" * 40)
    assert bind_reviews(candidate, [worse]).reason == "review_not_independent"


def test_unaccepted_review_is_refused() -> None:
    candidate = _pure_candidate()
    accepted = _Review()
    assert bind_reviews(candidate, [accepted]).status == "present"  # premise: the accepted review binds
    unaccepted = dataclasses.replace(accepted, accepted=False)

    link = bind_reviews(candidate, [unaccepted])

    assert (link.status, link.reason) == ("refused", "review_not_accepted")
    assert link.current is False
    assert len(link.evidence_sha256) == 64
    # acceptance is judged before the tree
    wrong_tree = dataclasses.replace(unaccepted, reviewed_tree="e" * 40)
    assert bind_reviews(candidate, [wrong_tree]).reason == "review_not_accepted"


def test_review_of_another_tree_is_refused() -> None:
    candidate = _pure_candidate()
    reviewed = _Review()
    assert reviewed.reviewed_tree == candidate.tree
    assert bind_reviews(candidate, [reviewed]).status == "present"  # premise: the right tree binds
    other = dataclasses.replace(reviewed, reviewed_tree="e" * 40)

    link = bind_reviews(candidate, [other])

    assert (link.status, link.reason) == ("refused", "review_tree_mismatch")
    assert link.current is False
    assert len(link.evidence_sha256) == 64
    # the tree is judged before the reviewer count
    assert bind_reviews(candidate, [other], required_reviewers=2).reason == "review_tree_mismatch"


def test_duplicate_review_attempt_is_refused() -> None:
    candidate = _pure_candidate()
    distinct = _two_independent_reviews()
    # premise: the same two reviewers on distinct attempts bind
    assert bind_reviews(candidate, distinct, required_reviewers=2).status == "present"
    duplicated = [distinct[0], dataclasses.replace(distinct[1], review_attempt_id="attempt-1")]

    link = bind_reviews(candidate, duplicated, required_reviewers=2)

    assert (link.status, link.reason) == ("refused", "review_attempt_duplicate")
    assert link.current is False
    assert len(link.evidence_sha256) == 64
    # a repeated attempt is judged before independence
    self_review = dataclasses.replace(duplicated[1], reviewer_id="builder")
    assert bind_reviews(candidate, [duplicated[0], self_review]).reason == "review_attempt_duplicate"


def test_too_few_distinct_reviewers_is_unavailable() -> None:
    candidate = _pure_candidate()
    one_reviewer_twice = [
        _Review(review_attempt_id="attempt-1", reviewer_id="red_team"),
        _Review(review_attempt_id="attempt-2", reviewer_id="red_team"),
    ]
    # premises: this set is independent, accepted, on the right tree and on distinct attempts, so
    # it binds against a bound of one; and two distinct reviewers satisfy the bound of two
    assert bind_reviews(candidate, one_reviewer_twice, required_reviewers=1).status == "present"
    assert bind_reviews(candidate, _two_independent_reviews(), required_reviewers=2).status == "present"

    link = bind_reviews(candidate, one_reviewer_twice, required_reviewers=2)

    assert (link.status, link.reason) == ("unavailable", "review_insufficient")
    assert link.current is False
    assert len(link.evidence_sha256) == 64


@pytest.mark.parametrize("reviews", [None, [], ()], ids=["none", "empty-list", "empty-tuple"])
def test_reviews_absent_or_empty_is_unavailable(reviews: object) -> None:
    candidate = _pure_candidate()

    link = bind_reviews(candidate, reviews)  # type: ignore[arg-type]

    assert (link.status, link.reason) == ("unavailable", "review_set_absent")
    assert link.evidence_sha256 == ""
    assert link.candidate_digest == candidate.digest()
    assert link.current is False


def test_review_set_oversized_is_unavailable() -> None:
    candidate = _pure_candidate()
    reviews = [
        _Review(review_attempt_id=f"attempt-{n}", reviewer_id=f"reviewer-{n}")
        for n in range(MAX_REVIEWS + 1)
    ]
    assert len(reviews) == MAX_REVIEWS + 1
    # premise: the cap is inclusive and every record is well formed, so the verdict below is the size comparison
    at_cap = bind_reviews(candidate, reviews[:MAX_REVIEWS], required_reviewers=MAX_REVIEWS)
    assert (at_cap.status, at_cap.reason) == ("present", "review_set_bound")

    link = bind_reviews(candidate, reviews)

    assert (link.status, link.reason) == ("unavailable", "review_set_oversized")
    assert link.evidence_sha256 == ""
    assert link.current is False
    # Check order: size is judged before the per-record shape. premise: that record alone is malformed
    assert bind_reviews(candidate, [reviews[0], object()]).reason == "review_malformed"  # type: ignore[list-item]
    assert bind_reviews(candidate, [*reviews[:MAX_REVIEWS], object()]).reason == "review_set_oversized"  # type: ignore[list-item]


_MALFORMED_REVIEWS = {
    "reviewer-empty": ("reviewer_id", ""),
    "attempt-has-space": ("review_attempt_id", "has space"),
    "accepted-str": ("accepted", "yes"),
    "accepted-int": ("accepted", 1),
    "tree-uppercase": ("reviewed_tree", "C" * 40),
    "not-a-review-object": (None, None),
    # Added: defects that only a full-string match (not a prefix match) or a type check refuses.
    "attempt-too-long": ("review_attempt_id", "a" * 129),
    "assignee-leading-dash": ("assignee_id", "-builder"),
    "accepted-none": ("accepted", None),
    "tree-trailing-newline": ("reviewed_tree", "c" * 40 + "\n"),
    "tree-none": ("reviewed_tree", None),
}


@pytest.mark.parametrize(
    ("field", "bad"), list(_MALFORMED_REVIEWS.values()), ids=list(_MALFORMED_REVIEWS),
)
def test_malformed_review_is_unavailable(field: str | None, bad: object) -> None:
    candidate = _pure_candidate()
    fixed = _Review(review_attempt_id="attempt-1", reviewer_id="red_team")
    other = _Review(review_attempt_id="attempt-2", reviewer_id="system_qa")
    # premise: with the record intact the set binds, so the malformed record is the only defect
    assert bind_reviews(candidate, [fixed, other], required_reviewers=2).status == "present"
    broken = object() if field is None else dataclasses.replace(fixed, **{field: bad})

    link = bind_reviews(candidate, [broken, other], required_reviewers=2)  # type: ignore[list-item]

    assert (link.status, link.reason) == ("unavailable", "review_malformed")
    assert link.evidence_sha256 == ""
    assert link.current is False


def test_review_set_digest_is_order_independent_and_candidate_bound() -> None:
    candidate = _pure_candidate()
    reviews = _two_independent_reviews()

    forward = bind_reviews(candidate, reviews, required_reviewers=2)
    reverse = bind_reviews(candidate, list(reversed(reviews)), required_reviewers=2)

    assert forward.status == reverse.status == "present"  # premise: both orders bind
    assert list(reversed(reviews)) != reviews  # premise: the order really changed
    assert forward.evidence_sha256 == reverse.evidence_sha256
    assert bind_reviews(candidate, tuple(reviews), required_reviewers=2).evidence_sha256 == forward.evidence_sha256

    other = dataclasses.replace(candidate, base_commit="d" * 40)
    rebound = bind_reviews(other, reviews, required_reviewers=2)
    assert rebound.status == "present"  # both candidates share the tree the reviews name
    assert other.digest() != candidate.digest()
    assert rebound.candidate_digest == other.digest()
    assert rebound.evidence_sha256 != forward.evidence_sha256


def test_review_wrong_argument_types_raise() -> None:
    candidate = _pure_candidate()
    review = _Review()
    assert bind_reviews(candidate, [review]).status == "present"  # premise: valid arguments bind
    # premise: both ends of the 1..MAX_REVIEWS range are valid
    for valid in (1, MAX_REVIEWS):
        assert bind_reviews(candidate, [review], required_reviewers=valid).kind == "review_set"

    def one_review():
        yield review

    for bad_container in ("abc", {}, one_review()):
        with pytest.raises(TypeError) as excinfo:
            bind_reviews(candidate, bad_container)  # type: ignore[arg-type]
        assert excinfo.value.args == ("review_set_container_invalid",)

    for bad_required in (0, True, MAX_REVIEWS + 1, 1.0, "1"):
        with pytest.raises(ValueError) as excinfo:
            bind_reviews(candidate, [review], required_reviewers=bad_required)  # type: ignore[arg-type]
        assert excinfo.value.args == ("review_required_invalid",)
    # a programming error raises whatever the evidence is, even when it is absent
    with pytest.raises(ValueError) as excinfo:
        bind_reviews(candidate, None, required_reviewers=0)
    assert excinfo.value.args == ("review_required_invalid",)

    with pytest.raises(TypeError) as excinfo:
        bind_reviews(None, [review])  # type: ignore[arg-type]
    assert excinfo.value.args == ("repair_candidate_required",)


def test_review_attestation_fields_exist_on_owned_review_records() -> None:
    # Imported here, in the test only: the source module never imports work_item_steps.
    from pydantic import TypeAdapter, ValidationError

    from probos.work_item_steps import OwnedId, OwnedStepExecutionPermit, ReviewedStepResult

    protocol_facts = {name for name in vars(ReviewAttestation) if not name.startswith("_")}
    assert protocol_facts == {
        "review_attempt_id", "reviewer_id", "assignee_id", "reviewed_tree", "accepted",
    }
    assert {"reviewer_id", "review_attempt_id", "accepted"} <= set(ReviewedStepResult.model_fields)
    assert "assignee_id" in OwnedStepExecutionPermit.model_fields

    # The id pattern is copied, not imported, so a drift in either copy would silently break the S3
    # projection. Probe both with the same ids: an id the owned type accepts must not be reported
    # malformed, and one it rejects must be.
    adapter = TypeAdapter(OwnedId)

    def owned_accepts(value: str) -> bool:
        try:
            adapter.validate_python(value)
        except ValidationError:
            return False
        return True

    candidate = _pure_candidate()
    probes = [
        "a", "A1", "reviewer_1", "red.team:v2-x", "a" * 128, "a" * 129, "", "-x", "_x", ".x",
        "has space", "tab\t", "newline\n", "a\n", "caf\u00e9", "a/b",
    ]
    assert {owned_accepts(value) for value in probes} == {True, False}  # premise: the probes discriminate
    for field in ("review_attempt_id", "reviewer_id", "assignee_id"):
        for value in probes:
            # a reviewer that equals the assignee would be refused as a self-review, not as malformed,
            # which still shows the id was readable; only ``review_malformed`` means unreadable
            link = bind_reviews(candidate, [dataclasses.replace(_Review(), **{field: value})])
            assert (link.reason != "review_malformed") == owned_accepts(value), (field, value)


# ---------------------------------------------------------------------------
# Amendment 1 (review round 1): unreadable review evidence, non-finite numbers, and edits to
# evidence the binding does not read
# ---------------------------------------------------------------------------


class _RaisingReview:
    """A record satisfying ``ReviewAttestation`` whose ``raising`` attribute raises when read.

    Each of the five attributes is a ``@property``: the shape of an arbitrary caller-supplied object
    whose attribute read runs code. ``raising=""`` names no attribute, so nothing raises: that is the
    readable twin of the same values.
    """

    def __init__(self, review: _Review, *, raising: str, error: type[BaseException]) -> None:
        self._review = review
        self._raising = raising
        self._error = error

    def _maybe_raise(self, attribute: str) -> None:
        if attribute == self._raising:
            raise self._error("boom")

    @property
    def review_attempt_id(self) -> str:
        self._maybe_raise("review_attempt_id")
        return self._review.review_attempt_id

    @property
    def reviewer_id(self) -> str:
        self._maybe_raise("reviewer_id")
        return self._review.reviewer_id

    @property
    def assignee_id(self) -> str:
        self._maybe_raise("assignee_id")
        return self._review.assignee_id

    @property
    def reviewed_tree(self) -> str:
        self._maybe_raise("reviewed_tree")
        return self._review.reviewed_tree

    @property
    def accepted(self) -> bool:
        self._maybe_raise("accepted")
        return self._review.accepted


_RAISING_GETTERS = {
    "reviewer_id-ValueError": ("reviewer_id", ValueError),
    "reviewer_id-RuntimeError": ("reviewer_id", RuntimeError),
    "reviewer_id-KeyError": ("reviewer_id", KeyError),
    "accepted-ValueError": ("accepted", ValueError),
}


@pytest.mark.parametrize(
    ("attribute", "error"), list(_RAISING_GETTERS.values()), ids=list(_RAISING_GETTERS),
)
def test_review_getter_raising_is_unavailable(attribute: str, error: type[Exception]) -> None:
    candidate = _pure_candidate()
    values = _Review(review_attempt_id="attempt-1", reviewer_id="red_team")
    # premise: the readable twin (the same values, nothing raises) binds, so the raising getter is
    # the only defect in the record below
    twin = bind_reviews(candidate, [_RaisingReview(values, raising="", error=error)])
    assert (twin.status, twin.reason) == ("present", "review_set_bound")
    raising_record = _RaisingReview(values, raising=attribute, error=error)
    # premise: reading that attribute really raises the exception under test
    with pytest.raises(error):
        getattr(raising_record, attribute)

    link = bind_reviews(candidate, [raising_record])  # an evidence defect is returned, never raised

    assert (link.status, link.reason) == ("unavailable", "review_malformed")
    assert link.evidence_sha256 == ""
    assert link.current is False


@pytest.mark.parametrize(
    "error",
    [KeyboardInterrupt, SystemExit, asyncio.CancelledError],
    ids=["KeyboardInterrupt", "SystemExit", "CancelledError"],
)
def test_review_getter_control_flow_exception_propagates(error: type[BaseException]) -> None:
    candidate = _pure_candidate()
    values = _Review(review_attempt_id="attempt-1", reviewer_id="red_team")
    # premise: this is a BaseException that is not an Exception, so only a BaseException catch
    # could turn it into a link
    assert issubclass(error, BaseException)
    assert not issubclass(error, Exception)
    # premise: the readable twin binds, so the raising getter is the only difference
    twin = bind_reviews(candidate, [_RaisingReview(values, raising="", error=error)])
    assert (twin.status, twin.reason) == ("present", "review_set_bound")

    with pytest.raises(error):
        bind_reviews(candidate, [_RaisingReview(values, raising="reviewer_id", error=error)])


# Where tests 37-39 write a number into the real receipt. Neither field is read by the module:
# ``finished_at`` (a string in the real receipt) and ``junit.totals.time_seconds``. Each entry is
# the marker bytes in the real receipt, the key text kept in front of the substituted number, and
# the path at which a lenient reader finds the number.
_NUMBER_LOCATIONS = {
    "finished_at": (
        b'"finished_at": "2026-10-11T00:00:01Z"', b'"finished_at": ', ("finished_at",),
    ),
    "junit.totals.time_seconds": (
        b'"time_seconds": 0.1', b'"time_seconds": ', ("junit", "totals", "time_seconds"),
    ),
}


def _substitute_number(real: bytes, location: str, literal: bytes) -> bytes:
    marker, key, _ = _NUMBER_LOCATIONS[location]
    assert real.count(marker) == 1  # premise: the marker occurs once, so the substitution lands
    return real.replace(marker, key + literal)


def _number_at(raw: bytes, location: str) -> object:
    """What a lenient stdlib reader finds at ``location`` in ``raw``."""
    node: object = json.loads(raw)
    for key in _NUMBER_LOCATIONS[location][2]:
        node = node[key]  # type: ignore[index]
    return node


@pytest.mark.parametrize("location", list(_NUMBER_LOCATIONS), ids=list(_NUMBER_LOCATIONS))
@pytest.mark.parametrize("literal", [b"1e99999", b"-1e99999"], ids=["1e99999", "minus-1e99999"])
def test_receipt_non_finite_number_is_unavailable(
    gate: ModuleType, repo: Path, literal: bytes, location: str,
) -> None:
    candidate = _candidate(repo)
    real = _real_receipt(gate, repo)
    assert math.isinf(json.loads(literal))  # premise: the stdlib reads this literal as an infinity
    _assert_binds(candidate, real)  # premise: the unmutated receipt binds
    raw = _substitute_number(real, location, literal)
    # premise: a lenient reader reads this receipt with an infinity at the location, so only the
    # non-finite rule can make it malformed
    assert math.isinf(_number_at(raw, location))

    link = verify_gate_receipt(candidate, raw)

    assert (link.status, link.reason) == ("unavailable", "gate_receipt_malformed")
    assert link.current is False
    # the bytes were read: the verdict is not absent, empty or oversized
    assert link.evidence_sha256 == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize("location", list(_NUMBER_LOCATIONS), ids=list(_NUMBER_LOCATIONS))
def test_receipt_finite_underflow_number_still_binds(
    gate: ModuleType, repo: Path, location: str,
) -> None:
    literal = b"1e-99999"
    candidate = _candidate(repo)
    real = _real_receipt(gate, repo)
    assert json.loads(literal) == 0.0  # premise: the literal underflows to a finite zero
    _assert_binds(candidate, real)  # premise: the unmutated receipt binds
    raw = _substitute_number(real, location, literal)
    # premise: a lenient reader reads zero at the location, so this fixture reaches the finite check
    assert _number_at(raw, location) == 0.0

    link = verify_gate_receipt(candidate, raw)

    assert (link.status, link.reason) == ("present", "gate_receipt_bound")
    assert link.current is True


def test_receipt_oversized_integer_literal_is_unavailable(gate: ModuleType, repo: Path) -> None:
    literal = b"9" * 5000
    candidate = _candidate(repo)
    real = _real_receipt(gate, repo)
    # premise: the stdlib itself refuses this integer (Python 3.12's integer-string limit) with a
    # ValueError, which is what the parser must treat as malformed rather than let escape
    with pytest.raises(ValueError):
        json.loads(literal)
    _assert_binds(candidate, real)  # premise: the unmutated receipt binds
    raw = _substitute_number(real, "junit.totals.time_seconds", literal)

    link = verify_gate_receipt(candidate, raw)

    assert (link.status, link.reason) == ("unavailable", "gate_receipt_malformed")
    assert link.current is False


def test_edited_review_changes_evidence_digest() -> None:
    """Specified behaviour, not a gap (Amendment 1, F2): a re-labelled review still binds.

    The canonical statement (Amendment 2): S1a refuses a receipt or review set that contradicts the
    candidate in the facts it checks (commit, tree, status, schema and reviewer independence, plus the
    label when one is expected). It records a sha256 for each piece of evidence: for a receipt, the
    SHA-256 of the supplied raw bytes, so any change to those bytes changes it; for a review set, a
    domain-separated SHA-256 of the candidate-bound projection of five review fields (attempt id,
    reviewer id, assignee id, reviewed tree, accepted), so a change to those five fields changes it
    and a change to any other review attribute does not. A consumer that retained an earlier trusted
    digest can therefore detect a change within what each digest covers. S1a does not authenticate
    the producer, does not assert that unread fields are valid, and does not exclude a writer running
    under ProbOS's own OS identity.

    A reviewer or attempt id changed to another valid, independent value contradicts nothing S1a
    checks, so the set binds; the only trace of the edit is the different ``evidence_sha256``.
    Both edited fields are among the five the review-set digest covers, which is why the digest
    changes; test 41 pins that an attribute outside them does not.
    """
    candidate = _pure_candidate()
    reviews = _two_independent_reviews()
    original = bind_reviews(candidate, reviews, required_reviewers=2)
    # premise: the unedited set binds, so each edit below is the only change
    assert (original.status, original.reason) == ("present", "review_set_bound")

    for field, value in (("reviewer_id", "counselor"), ("review_attempt_id", "attempt-9")):
        assert getattr(reviews[0], field) != value  # premise: the edit really changes the record
        edited_first = dataclasses.replace(reviews[0], **{field: value})

        edited = bind_reviews(candidate, [edited_first, reviews[1]], required_reviewers=2)

        # still valid and independent: nothing S1a checks is contradicted, so it binds (specified)
        assert (edited.status, edited.reason) == ("present", "review_set_bound"), field
        # only the recorded digest changes
        assert edited.evidence_sha256 != original.evidence_sha256, field


# ---------------------------------------------------------------------------
# Amendment 2 (review round 2): what the review-set digest covers
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ReviewWithSubmission(_Review):
    """A ``_Review`` that also carries an attribute outside the five the binding projects.

    ``submission_digest`` is the analogue of ``ReviewedStepResult.submission_digest``: a real review
    record has it, and ``bind_reviews`` never projects it.
    """

    submission_digest: str = "a" * 64


def test_review_digest_ignores_attributes_outside_the_projection() -> None:
    """Specified behaviour, not a gap (Amendment 2, R2-F1): a review-set digest covers only the
    candidate-bound five-field projection, so an attribute outside it (here a submission digest)
    does not change it.

    The canonical statement (Amendment 2): S1a refuses a receipt or review set that contradicts the
    candidate in the facts it checks (commit, tree, status, schema and reviewer independence, plus the
    label when one is expected). It records a sha256 for each piece of evidence: for a receipt, the
    SHA-256 of the supplied raw bytes, so any change to those bytes changes it; for a review set, a
    domain-separated SHA-256 of the candidate-bound projection of five review fields (attempt id,
    reviewer id, assignee id, reviewed tree, accepted), so a change to those five fields changes it
    and a change to any other review attribute does not. A consumer that retained an earlier trusted
    digest can therefore detect a change within what each digest covers. S1a does not authenticate
    the producer, does not assert that unread fields are valid, and does not exclude a writer running
    under ProbOS's own OS identity.
    """
    candidate = _pure_candidate()
    first = _ReviewWithSubmission(
        review_attempt_id="attempt-1", reviewer_id="red_team", submission_digest="a" * 64,
    )
    second = dataclasses.replace(first, submission_digest="b" * 64)
    # premises: the two records differ in the attribute outside the projection and in none of the
    # five the binding reads, and each binds, so their digests are comparable
    assert first.submission_digest != second.submission_digest
    assert _review_record(first) == _review_record(second)
    bound_first = bind_reviews(candidate, [first])
    bound_second = bind_reviews(candidate, [second])
    assert (bound_first.status, bound_first.reason) == ("present", "review_set_bound")
    assert (bound_second.status, bound_second.reason) == ("present", "review_set_bound")
    assert len(bound_first.evidence_sha256) == 64  # premise: a real digest, so this is not "" == ""

    assert bound_first.evidence_sha256 == bound_second.evidence_sha256
