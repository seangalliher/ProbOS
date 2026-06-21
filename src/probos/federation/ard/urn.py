"""AD-1040: ARD URN (``urn:air:...``) construction and parsing.

DD-8 layer discipline: this module imports NOTHING from the rest of
``probos`` — pure stdlib string handling. DD-6 honest-degrade: ``parse_urn``
and ``publisher_domain`` NEVER raise; malformed input degrades to ``None`` /
``""`` so callers on the discovery path can skip a bad URN without a try/except
wrapper at every site.
"""

from __future__ import annotations


def build_urn(publisher: str, namespace: str, name: str) -> str:
    """Build an ``urn:air:<publisher>:<namespace>:<name>`` ARD URN."""
    return f"urn:air:{publisher}:{namespace}:{name}"


def parse_urn(urn: str) -> tuple[str, str, str] | None:
    """Parse an ARD URN into ``(publisher, namespace, name)``.

    Requires the ``urn:air:`` prefix and at least five colon-separated
    segments. The ``name`` segment may itself contain colons and is rejoined
    verbatim. DD-6: any malformed input returns ``None`` — this function never
    raises.
    """
    if not isinstance(urn, str) or not urn.startswith("urn:air:"):
        return None
    segments = urn.split(":")
    if len(segments) < 5:
        return None
    publisher = segments[2]
    namespace = segments[3]
    name = ":".join(segments[4:])
    return (publisher, namespace, name)


def publisher_domain(urn: str) -> str:
    """Return the publisher (FQDN) segment of an ARD URN.

    DD-6 honest-degrade: returns ``""`` on any malformed URN rather than
    raising.
    """
    parsed = parse_urn(urn)
    return parsed[0] if parsed else ""
