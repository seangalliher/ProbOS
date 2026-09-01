"""AD-1265 / BF-838: does the inventory actually cover what the code declares?

Measured on the live vessel 2026-08-24 (``%LOCALAPPDATA%\\ProbOS\\data``), and
recorded here because BF-838's own arithmetic was wrong and the correction is
the useful artifact:

* Of BF-838's 22 "unprotected" databases, **14 were already top-level** and
  inside AD-466's glob, 1 was nested (``procedures/procedures.db``), and 7 do
  not exist on this vessel at all.
* Its headline risk ``schema_versions.db`` is declared at
  ``cognitive_services.py:389`` and **has never been created**; it is covered
  by the recursive glob the moment it is.
* The four grant stores plus ``action_approvals`` are genuine authorization
  state and hold **one row between them** -- ``clearance_grants=0``,
  ``intent_access_grants=0``, ``skill_access_grants=0``,
  ``tool_access_grants=1``, ``action_approvals=0``. The hazard is real in
  shape but presently near-empty, and all five are top-level: their fix was
  the scheduler (BF-842), not coverage.
* Real coverage at HEAD was **0 of 49, because nothing ran**.

**Caveat -- this repo has been bitten four times by source scans.** A source
scan cannot distinguish "this is required" from "this is what shipped". The
scan below is acceptable *only* because it asserts against
:data:`EXCLUDED_DATABASES`, a deliberate human-authored table with a written
reason per entry, rather than against observed behaviour. If a future change
touches it, **update the assertion and record why inline. Never delete it to
make a build green.**
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

import pytest

from probos.infrastructure import backup_inventory
from probos.infrastructure.backup_inventory import (
    EXCLUDED_DATABASES,
    BackupRoot,
    BackupTier,
    build_default_roots,
    classify,
    discover,
    is_excluded,
    prune_backup_root,
)

_SRC = PurePosixPath("src/probos")
#: ``"foo.db"`` / ``'foo.db'`` / ``"sub/foo.db"`` in a Python source literal.
_DB_LITERAL_RE = re.compile(r"""['"]([A-Za-z0-9_./\\-]+\.db)['"]""")


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "src" / "probos").is_dir():
            return parent
    raise AssertionError("could not locate the repository root from the test file")


def _declared_db_literals() -> dict[str, set[str]]:
    """``relative literal -> {source files that name it}`` for every ``*.db``."""
    root = _repo_root()
    found: dict[str, set[str]] = {}
    for path in sorted((root / "src" / "probos").rglob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in _DB_LITERAL_RE.finditer(text):
            literal = match.group(1).replace("\\", "/").lstrip("/")
            # Absolute-ish or traversal literals are not vessel-relative names.
            if ".." in PurePosixPath(literal).parts or not literal:
                continue
            found.setdefault(literal, set()).add(path.relative_to(root).as_posix())
    return found


def test_every_declared_db_literal_is_discoverable_or_excluded_with_a_reason(
    tmp_path: Path,
) -> None:
    """BF-838's real question, asked by execution rather than by inspection.

    Every ``*.db`` literal in ``src/`` is planted under a declared root and
    ``discover()`` is actually run, so this crosses the seam from "the code
    names this file" to "a snapshot would contain it". A literal that is not
    discovered has to be a deliberate exclusion carrying a written reason.
    """
    literals = _declared_db_literals()
    assert len(literals) >= 20, (
        f"the scan found only {len(literals)} *.db literals; it is not working"
    )

    data_dir = tmp_path / "data"
    backup_root = data_dir / "backups"
    backup_root.mkdir(parents=True)
    for literal in literals:
        planted = data_dir / literal
        planted.parent.mkdir(parents=True, exist_ok=True)
        planted.write_bytes(b"")

    discovered = {
        str(entry.relative_path)
        for entry in discover(
            [BackupRoot("data", data_dir)], backup_root=backup_root,
        )
    }

    unaccounted: list[str] = []
    for literal, sources in sorted(literals.items()):
        if literal in discovered:
            continue
        reason = is_excluded(PurePosixPath(literal))
        if reason and reason.strip():
            continue
        unaccounted.append(
            f"  {literal} -- declared in {', '.join(sorted(sources))}; it is "
            f"neither discovered under a declared root nor listed in "
            f"EXCLUDED_DATABASES with a reason. Fix: add it to "
            f"EXCLUDED_DATABASES with a written justification, or confirm it "
            f"lives under a declared root."
        )
    assert unaccounted == [], "\n" + "\n".join(unaccounted)


def test_every_exclusion_states_a_non_empty_reason() -> None:
    """An exclusion without a stated reason is indistinguishable from an
    oversight, which is the rot BF-838 recorded."""
    blank = [pattern for pattern, reason in EXCLUDED_DATABASES.items() if not reason.strip()]
    assert blank == []


def test_activation_tracker_is_excluded_and_says_why() -> None:
    """D1's largest decision by bytes -- 986 MiB per tick.

    If a future change reinstates it, that is a capacity decision someone must
    make deliberately: update this assertion and record why inline.
    """
    reason = is_excluded(PurePosixPath("activation_tracker.db"))
    assert reason is not None
    assert "episode_access_log" in reason
    assert "ChromaDB" in reason


def test_the_four_rejected_exclusion_candidates_are_still_included() -> None:
    """Exclusion is a stronger claim than AD-1262's ``bulk`` demotion was.

    None of these four has a reconstructibility argument, so size alone must
    not move them.
    """
    for name in (
        "semantic_work.db",
        "cognitive_journal.db",
        "eviction_audit.db",
        "episode_fts.db",
    ):
        assert is_excluded(PurePosixPath(name)) is None, name
        assert classify(PurePosixPath(name)) is BackupTier.INCLUDED, name


def test_included_is_the_default_for_an_unknown_database() -> None:
    """A store added tomorrow lands in the tier that is always protected."""
    assert classify(PurePosixPath("brand_new_store.db")) is BackupTier.INCLUDED
    assert classify(PurePosixPath("deep/nested/brand_new_store.db")) is BackupTier.INCLUDED


def test_ward_room_archives_classify_immutable() -> None:
    assert classify(PurePosixPath("archives/ward_room_001.db")) is BackupTier.IMMUTABLE


def test_no_bulk_tier_exists_anywhere_in_the_inventory() -> None:
    """Regression guard on D1, not decoration.

    ``bulk`` was a tier a tick could skip, resolved by naming a sibling
    snapshot. Retention deleted the sibling and restore then reported success
    with the database simply absent.
    """
    assert {t.name for t in BackupTier} == {"INCLUDED", "IMMUTABLE"}
    assert not hasattr(backup_inventory, "BULK_DATABASES")
    assert not hasattr(BackupTier, "BULK")
    assert "bulk" not in {t.value for t in BackupTier}


def test_snapshot_manifest_exposes_no_carry_forward_or_opacity() -> None:
    """The three deleted concepts, asserted absent by name."""
    from probos.infrastructure import snapshot_manifest

    assert not hasattr(snapshot_manifest, "STATE_DEFERRED")
    assert not hasattr(snapshot_manifest, "is_sqlite_file"), (
        "is_sqlite_file chose a verification path from the artifact's own "
        "bytes; nothing may reintroduce it"
    )
    field_names = set(snapshot_manifest.SnapshotManifest.__dataclass_fields__)
    assert "bulk_source" not in field_names
    assert "included_bulk" not in field_names
    assert "opaque" not in set(snapshot_manifest.ManifestEntry.__dataclass_fields__)


def test_schema_versions_db_would_be_covered_the_moment_it_is_created() -> None:
    """BF-838's headline risk. Declared at cognitive_services.py:389, never
    created on the live vessel (measured 2026-08-24)."""
    assert is_excluded(PurePosixPath("schema_versions.db")) is None
    assert classify(PurePosixPath("schema_versions.db")) is BackupTier.INCLUDED


def test_the_five_authorization_stores_are_included() -> None:
    """One row between them on 2026-08-24, but the shape is what matters:
    restoring with stale authorization state is a real hazard."""
    for name in (
        "clearance_grants.db",
        "intent_access_grants.db",
        "skill_access_grants.db",
        "tool_access_grants.db",
        "action_approvals.db",
    ):
        assert is_excluded(PurePosixPath(name)) is None, name
        assert classify(PurePosixPath(name)) is BackupTier.INCLUDED, name


# ---------------------------------------------------------------------------
# roots and discovery boundaries
# ---------------------------------------------------------------------------


def test_backup_root_name_is_validated_because_it_becomes_a_path_segment() -> None:
    BackupRoot("data", Path("/tmp"))
    BackupRoot("a" * 32, Path("/tmp"))
    for bad in ("", "Data", "has space", "../escape", "a" * 33, "with/slash"):
        with pytest.raises(ValueError, match="snapshot directory"):
            BackupRoot(bad, Path("/tmp"))


def test_a_missing_root_contributes_zero_entries_rather_than_raising(
    tmp_path: Path,
) -> None:
    """A fresh vessel is not an error."""
    backup_root = tmp_path / "backups"
    backup_root.mkdir()
    entries = discover(
        [BackupRoot("data", tmp_path / "does_not_exist")], backup_root=backup_root,
    )
    assert entries == []


def test_discovery_is_deterministically_ordered(tmp_path: Path) -> None:
    """Two runs against an unchanged tree must produce identical manifests."""
    data = tmp_path / "data"
    other = tmp_path / "other"
    backup_root = data / "backups"
    backup_root.mkdir(parents=True)
    for rel in ("z.db", "a.db", "nested/m.db"):
        (data / rel).parent.mkdir(parents=True, exist_ok=True)
        (data / rel).write_bytes(b"")
    (other / "b.db").parent.mkdir(parents=True, exist_ok=True)
    (other / "b.db").write_bytes(b"")

    roots = [BackupRoot("data", data), BackupRoot("archive", other)]
    first = [str(e.snapshot_relative_path) for e in discover(roots, backup_root=backup_root)]
    second = [str(e.snapshot_relative_path) for e in discover(roots, backup_root=backup_root)]

    assert first == second
    assert first == ["archive/b.db", "data/a.db", "data/nested/m.db", "data/z.db"]


def test_build_default_roots_reads_the_effective_configured_archive_path(
    tmp_path: Path,
) -> None:
    """An operator override must not silently go unbacked.

    The archive path is read through ``resolve_archive_db_path`` rather than
    recomputed from the platform branch, which is why this asserts on an
    override rather than on the default.
    """
    from probos.config import SystemConfig

    override = tmp_path / "elsewhere" / "archive.db"
    config = SystemConfig()
    config.archive.enabled = True
    config.archive.db_path = str(override)
    config.infrastructure.backup_include_archive_root = True

    roots = build_default_roots(tmp_path / "data", config)
    assert [r.name for r in roots] == ["data", "archive"]
    assert roots[1].path == override.parent


def test_build_default_roots_omits_the_archive_when_the_flag_is_off(
    tmp_path: Path,
) -> None:
    from probos.config import SystemConfig

    config = SystemConfig()
    config.archive.enabled = True
    config.infrastructure.backup_include_archive_root = False

    roots = build_default_roots(tmp_path / "data", config)
    assert [r.name for r in roots] == ["data"]


def test_the_backup_root_prune_is_unconditional_and_resolves_symlinks(
    tmp_path: Path,
) -> None:
    """A typo must not be able to re-arm recursive self-inclusion."""
    data = tmp_path / "data"
    backup_root = data / "backups"
    backup_root.mkdir(parents=True)
    (data / "keep.db").write_bytes(b"")
    (backup_root / "old.db").write_bytes(b"")

    kept = prune_backup_root(sorted(data.rglob("*.db")), backup_root)
    assert [p.name for p in kept] == ["keep.db"]
    # And via a traversal path pointing back into the backup root.
    traversal = backup_root / ".." / "backups" / "old.db"
    assert prune_backup_root([traversal], backup_root) == []
