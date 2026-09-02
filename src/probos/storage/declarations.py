"""AD-1256: what a durable store *is*, declared as data beside its owner.

ProbOS partitions durable state across dozens of SQLite files. That
partitioning is deliberate — SQLite takes one writer per file, so separate
databases are separate lock domains, and BF-826/#1290 depends on it: an error
path escapes a failing resource by writing to a *different* file behind a
*different* lock. Nothing recorded which stores exist, who owns their
lifecycle, how long their rows live, or whether a backup contains them, so
those questions were answered by reading code, one store at a time.

This module is the value layer for those answers. It is a **leaf**: it imports
nothing from ``probos``, which is what lets a declaration module in any layer
import it without inverting the layer order. A test enforces that by
AST-scanning this file's imports.

A declaration is *data about* a store, never a use of one. Nothing here opens a
connection, and no declaration module may import the store it declares —
importing a dozen store modules at declaration-load time would drag their side
effects into every ``--check``.

Nothing consumes these fields
-----------------------------
This slice records metadata and enforces nothing with it. No boot path, no
startup ordering, no degradation policy, and no error handler reads
:class:`StoreCriticality`, :class:`StoreRetention`, ``backup`` or ``restore``. A
store declared ``REQUIRED`` boots exactly the way it boots today; the vessel's
byte-level behaviour is unchanged by this module's existence.

That is a decision, not an omission. BF-756 (#1213) was reverted because moving
three stores into a boot path silently made them boot-critical — measured as
``DatabaseError: file is not a database`` taking down a vessel that had only
asked for agent-callable tools. If editing a *declaration* could change boot
behaviour, then a metadata edit becomes a behaviour change and this AD
reproduces that defect by construction. A consumer arrives only when AD-1270c2
owns lifecycle registrations and can act on criticality during startup unwind,
in a separately reviewed slice.

Not a load-shedding tier
------------------------
``probos.degradation.registry`` already defines ``ServiceTier``
(``ESSENTIAL`` / ``COGNITIVE`` / ``NON_ESSENTIAL``), ``ServiceClassification``
and ``ServiceTierRegistry``. That axis is **what to drop under stress**.
:class:`StoreCriticality` is **whether the vessel can boot without this file**.
The vocabularies are confusably similar and the axes are unrelated: this module
does not import ``probos.degradation``, does not map onto it, and must not be
wired to it.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

__all__ = [
    "BACKUP_DISPOSITIONS",
    "RESTORE_DISPOSITIONS",
    "UNOWNED_LIFECYCLE",
    "StoreCriticality",
    "StoreDeclaration",
    "StoreRetention",
    "declaration_errors",
]


class StoreCriticality(str, Enum):
    """Whether the vessel can boot without this store.

    Boot criticality, **not** load-shedding priority — see the module
    docstring. Inert in this slice: nothing reads it to make a decision.
    """

    REQUIRED = "required"
    OPTIONAL = "optional"
    FEATURE_GATED = "feature-gated"


class StoreRetention(str, Enum):
    """How this store's rows stop accumulating, if they do.

    ``UNBOUNDED`` is legal and must be written down. The point of the field is
    that "grows forever" becomes a deliberate, reviewed claim carrying a stated
    reason rather than the default nobody noticed.
    """

    #: A delete path exists and its bound is stated in ``retention_note``.
    BOUNDED = "bounded"
    #: No delete path. ``retention_note`` must say why that is acceptable.
    UNBOUNDED = "unbounded"
    #: Rows expire only when a different store's rows do; name it in the note.
    EXTERNAL = "external"


#: What a snapshot does with this file. AD-1265 owns the semantics; this slice
#: only records which of the three a store claims.
BACKUP_DISPOSITIONS: Final[frozenset[str]] = frozenset(
    {"included", "excluded", "unknown"}
)

#: How this store comes back. AD-1266 owns the semantics.
RESTORE_DISPOSITIONS: Final[frozenset[str]] = frozenset(
    {"point-in-time", "reconstructed", "unknown"}
)

#: Sentinel ``lifecycle_owner`` meaning "nothing calls start()/stop()".
#: A declaration must opt into this **by name**: a blank ``lifecycle_owner`` is
#: an error, because an unowned lifecycle recorded as a blank is
#: indistinguishable from one nobody looked up.
UNOWNED_LIFECYCLE: Final[str] = "unowned"


@dataclass(frozen=True, slots=True)
class StoreDeclaration:
    """Static data about one durable store, declared beside its owner.

    ``canonical_path`` is the **one** spelling of this store's file. Measured
    on the tracked tree, several stores are named two ways in ``src/`` — for
    instance ``directives.db`` and ``data/directives.db`` — and a store with two
    spellings has no identity. Recording one spelling resolves that on paper;
    it moves no file and renames nothing.
    """

    id: str
    title: str
    owner_module: str
    owner_symbol: str
    canonical_path: str
    criticality: StoreCriticality
    lifecycle_owner: str
    retention: StoreRetention
    backup: str
    restore: str
    retention_note: str = ""
    reconstruction: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Render as a JSON-safe mapping."""
        return {
            "id": self.id,
            "title": self.title,
            "owner_module": self.owner_module,
            "owner_symbol": self.owner_symbol,
            "canonical_path": self.canonical_path,
            "criticality": self.criticality.value,
            "lifecycle_owner": self.lifecycle_owner,
            "retention": self.retention.value,
            "backup": self.backup,
            "restore": self.restore,
            "retention_note": self.retention_note,
            "reconstruction": self.reconstruction,
            "notes": self.notes,
        }

    @property
    def owner_path(self) -> str:
        """The dotted ``module.Symbol`` this declaration points at."""
        return f"{self.owner_module}.{self.owner_symbol}"


#: Fields that must be present and non-blank on every declaration.
_REQUIRED_TEXT_FIELDS: Final[tuple[str, ...]] = (
    "id",
    "title",
    "owner_module",
    "owner_symbol",
    "canonical_path",
    "lifecycle_owner",
)


def declaration_errors(declaration: StoreDeclaration) -> tuple[str, ...]:
    """Every schema problem with this declaration, or an empty tuple.

    Returns rather than raises, and accumulates rather than stopping at the
    first fault, so one malformed declaration reports all of its problems in a
    single pass instead of one per re-run. Validation deliberately does **not**
    live in ``__post_init__``: a raise there would make the whole declaration
    module unimportable, converting a single bad row into a silently missing
    layer.
    """
    problems: list[str] = []
    where = declaration.id.strip() or "<blank id>"

    for field_name in _REQUIRED_TEXT_FIELDS:
        value = getattr(declaration, field_name)
        if not isinstance(value, str) or not value.strip():
            problems.append(f"{where}: {field_name!r} is missing or blank")

    if not isinstance(declaration.criticality, StoreCriticality):
        problems.append(
            f"{where}: criticality {declaration.criticality!r} is not one of "
            f"{[member.value for member in StoreCriticality]}"
        )
    if not isinstance(declaration.retention, StoreRetention):
        problems.append(
            f"{where}: retention {declaration.retention!r} is not one of "
            f"{[member.value for member in StoreRetention]}"
        )
    if declaration.backup not in BACKUP_DISPOSITIONS:
        problems.append(
            f"{where}: backup {declaration.backup!r} is not one of "
            f"{sorted(BACKUP_DISPOSITIONS)}"
        )
    if declaration.restore not in RESTORE_DISPOSITIONS:
        problems.append(
            f"{where}: restore {declaration.restore!r} is not one of "
            f"{sorted(RESTORE_DISPOSITIONS)}"
        )

    # Conditional requirements. These are the mechanism by which "unbounded,
    # but deliberately and in writing" is enforced -- a blank note where the
    # enum demands one is an error, not a warning.
    if declaration.retention is not StoreRetention.BOUNDED and not (
        declaration.retention_note.strip()
    ):
        problems.append(
            f"{where}: retention is {getattr(declaration.retention, 'value', declaration.retention)!r} "
            "so 'retention_note' is required and must say why rows never expire "
            "or which store's retention governs them"
        )
    if declaration.restore == "reconstructed" and not declaration.reconstruction.strip():
        problems.append(
            f"{where}: restore is 'reconstructed' so 'reconstruction' is "
            "required and must name how the data comes back"
        )
    if declaration.restore != "reconstructed" and declaration.reconstruction.strip():
        problems.append(
            f"{where}: 'reconstruction' is set but restore is "
            f"{declaration.restore!r}; a reconstruction method only means "
            "something when restore is 'reconstructed'"
        )
    return tuple(problems)
