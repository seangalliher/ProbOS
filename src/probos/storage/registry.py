"""AD-1256: collection of store declarations. Holds no connections.

This is deliberately **not** a second runtime registry and **not** a service
locator. It carries declarations — static data pointing at owners — and nothing
else: no connections, no live stores, no lifecycle, no runtime mutation, and no
module-level singleton. A registry that held open connections would be mutable
runtime state keyed by store, which is the shape AD-1270a's D1 rejected, and it
would relocate WAL and ``busy_timeout`` semantics for thirty stores in one
commit.

Connection creation is **not** here. ``probos.protocols.ConnectionFactory`` and
``probos.storage.sqlite_factory.SQLiteConnectionFactory`` have owned that seam
since AD-542, and a new store adopts it by constructor injection:

.. code-block:: python

    def __init__(
        self,
        db_path: str = "",
        connection_factory: ConnectionFactory | None = None,
    ) -> None:

``probos.tools.action_approvals.ActionApprovalStore`` is the reference shape.
AD-1256 adds declarations *about* stores; it adds no second answer to "how do I
get a connection".

``DECLARATION_MODULES`` is an explicit list of pointers rather than a glob or a
``pkgutil`` walk. Globbing ``src/probos/**`` silently yields an empty registry
when ProbOS is installed as a wheel, and walking packages imports the whole
tree and its side effects. ``scripts/check_store_registry.py`` fails the build
if a ``storage_declarations`` module exists that this tuple does not name, so
the explicit list cannot silently fall behind.

Nothing under ``src/probos/`` imports this module. That is asserted by a test:
this slice ships the inventory and its checker, and adds no runtime consumer.
"""

from __future__ import annotations

import logging
from importlib import import_module

from probos.storage.declarations import StoreDeclaration

logger = logging.getLogger(__name__)

__all__ = [
    "DECLARATION_MODULES",
    "StoreRegistry",
    "load_default_store_registry",
]

#: Dotted paths of the modules that declare stores, one per owning layer.
#: ``probos.storage_declarations`` is the top-level module's home: it sits
#: beside ``probos/workforce.py``, which is a module rather than a package and
#: therefore has no directory of its own to declare into.
DECLARATION_MODULES: tuple[str, ...] = (
    "probos.storage_declarations",
    "probos.cognitive.storage_declarations",
    "probos.security.storage_declarations",
    "probos.threads.storage_declarations",
    "probos.tools.storage_declarations",
    "probos.ward_room.storage_declarations",
)


class StoreRegistry:
    """A collection of :class:`StoreDeclaration`, keyed by declaration id."""

    def __init__(self) -> None:
        self._declarations: dict[str, StoreDeclaration] = {}
        self._paths: dict[str, str] = {}

    def register(self, declaration: StoreDeclaration) -> None:
        """Add a declaration.

        Raises ``ValueError`` on a duplicate id or a duplicate
        ``canonical_path`` rather than degrading. Either collision silently
        merges two stores' metadata into one row, and a store whose identity is
        ambiguous is exactly what this registry exists to prevent, so it
        propagates.
        """
        existing = self._declarations.get(declaration.id)
        if existing is not None:
            raise ValueError(
                f"duplicate store declaration id {declaration.id!r}: already "
                f"declared by {existing.owner_module}, redeclared by "
                f"{declaration.owner_module}"
            )
        path_claimant = self._paths.get(declaration.canonical_path)
        if path_claimant is not None:
            raise ValueError(
                f"duplicate canonical_path {declaration.canonical_path!r}: "
                f"claimed by {path_claimant!r}, reclaimed by "
                f"{declaration.id!r}; a store has exactly one canonical path"
            )
        self._declarations[declaration.id] = declaration
        self._paths[declaration.canonical_path] = declaration.id

    def declarations(self) -> tuple[StoreDeclaration, ...]:
        """Every registered declaration, sorted by id."""
        return tuple(sorted(self._declarations.values(), key=lambda item: item.id))

    def get(self, store_id: str) -> StoreDeclaration | None:
        """The declaration with this id, or ``None`` if nothing declared it."""
        return self._declarations.get(store_id)

    def by_canonical_path(self, canonical_path: str) -> StoreDeclaration | None:
        """The declaration claiming this path, or ``None``."""
        store_id = self._paths.get(canonical_path)
        return self._declarations.get(store_id) if store_id else None

    def owner_modules(self) -> frozenset[str]:
        """Every distinct ``owner_module`` in the registry."""
        return frozenset(item.owner_module for item in self._declarations.values())


def load_default_store_registry() -> StoreRegistry:
    """Build a **fresh** registry from :data:`DECLARATION_MODULES`.

    One broken declaration module must not blank the whole inventory, so an
    import failure is log-and-degrade: the module is skipped with a warning
    naming what is therefore missing, and the rest still resolve. A duplicate
    id or path still propagates — that is a correctness failure, not a missing
    layer.
    """
    registry = StoreRegistry()
    for module_name in DECLARATION_MODULES:
        try:
            module = import_module(module_name)
        except Exception:
            logger.warning(
                "AD-1256: store declaration module %s failed to import; its "
                "stores are absent from the store inventory and the remaining "
                "modules are still loaded",
                module_name,
                exc_info=True,
            )
            continue
        for declaration in getattr(module, "STORE_DECLARATIONS", ()):
            registry.register(declaration)
    return registry
