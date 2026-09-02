"""AD-1270a: collection of capability declarations. Holds no capability state.

This is deliberately **not** a second runtime registry. It carries declarations
— static data pointing at owners — and nothing else: no lifecycle, no runtime
mutation, and no module-level singleton, because a mutable global keyed by
capability is exactly the object this AD forbids.

``DECLARATION_MODULES`` is an explicit list of pointers rather than a glob or a
``pkgutil`` walk. Globbing ``src/probos/**`` silently yields an empty registry
when ProbOS is installed as a wheel, and walking packages imports the whole
tree and its side effects.
"""

from __future__ import annotations

import logging
from importlib import import_module

from probos.maturity.model import CapabilityDeclaration

logger = logging.getLogger(__name__)

__all__ = ["DECLARATION_MODULES", "MaturityRegistry", "load_default_registry"]

#: Dotted paths of the modules that declare capabilities, one per owning layer.
DECLARATION_MODULES: tuple[str, ...] = (
    "probos.cognitive.maturity_declarations",
    "probos.tools.maturity_declarations",
    "probos.agents.maturity_declarations",
    "probos.infrastructure.maturity_declarations",
)


class MaturityRegistry:
    """A collection of :class:`CapabilityDeclaration`, keyed by declaration id."""

    def __init__(self) -> None:
        self._declarations: dict[str, CapabilityDeclaration] = {}

    def register(self, declaration: CapabilityDeclaration) -> None:
        """Add a declaration.

        Raises ``ValueError`` on a duplicate id rather than degrading: a
        collided id would silently merge two capabilities' evidence, which is a
        correctness failure, so it propagates.
        """
        existing = self._declarations.get(declaration.id)
        if existing is not None:
            raise ValueError(
                f"duplicate maturity declaration id {declaration.id!r}: already "
                f"declared by {existing.owner_module}, redeclared by "
                f"{declaration.owner_module}"
            )
        self._declarations[declaration.id] = declaration

    def declarations(self) -> tuple[CapabilityDeclaration, ...]:
        """Every registered declaration, sorted by id."""
        return tuple(sorted(self._declarations.values(), key=lambda d: d.id))

    def get(self, capability_id: str) -> CapabilityDeclaration | None:
        """The declaration with this id, or ``None`` if nothing declared it."""
        return self._declarations.get(capability_id)


def load_default_registry() -> MaturityRegistry:
    """Build a **fresh** registry from :data:`DECLARATION_MODULES`.

    One broken declaration module must not blank the whole inventory, so an
    import failure is log-and-degrade: the module is skipped with a warning
    naming what is therefore missing, and the rest still resolve.
    """
    registry = MaturityRegistry()
    for module_name in DECLARATION_MODULES:
        try:
            module = import_module(module_name)
        except Exception:
            logger.warning(
                "AD-1270a: maturity declaration module %s failed to import; its "
                "capabilities are absent from the capability-truth inventory and "
                "the remaining modules are still loaded",
                module_name,
                exc_info=True,
            )
            continue
        for declaration in getattr(module, "MATURITY_DECLARATIONS", ()):
            registry.register(declaration)
    return registry
