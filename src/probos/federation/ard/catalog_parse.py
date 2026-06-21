"""AD-1046: pure ARD catalog deserialization (dict -> AiCatalog/CatalogEntry).

DD-8 layer discipline + AD-1040 purity: this module imports ONLY stdlib + the
sibling pure ``catalog`` types. It is the INVERSE of ``catalog.to_dict()`` kept
OUT of ``catalog.py`` so that module stays byte-identical (AD-1040 invariant).

DD-6 honest-degrade: every parser NEVER raises. A malformed entry degrades to
``None`` (and is dropped from the discovery path); a malformed catalog degrades
to an empty-but-well-formed envelope. The ``data`` payload and the
``trustManifest.signature`` are treated as OPAQUE carriers — never dereferenced,
never mined for secrets — so the parser keeps only the public envelope shape.
"""

from __future__ import annotations

import logging
from typing import Any

from .catalog import (
    AiCatalog,
    Attestation,
    CatalogEntry,
    HostInfo,
    ProvenanceLink,
    TrustManifest,
)

logger = logging.getLogger(__name__)


def _str(value: Any, default: str = "") -> str:
    """Coerce to ``str`` defensively, degrading non-strings to ``default``."""
    return value if isinstance(value, str) else default


def _str_list(value: Any) -> list[str]:
    """Coerce to a list of strings, dropping any non-string member."""
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str)]


def _as_list(value: Any) -> list[Any]:
    """Return ``value`` if it is a list, else an empty list (honest-degrade)."""
    return value if isinstance(value, list) else []


def _attestation_from_dict(d: Any) -> Attestation | None:
    if not isinstance(d, dict):
        return None
    type_ = _str(d.get("type"))
    uri = _str(d.get("uri"))
    if not type_ or not uri:
        return None
    return Attestation(type=type_, uri=uri, digest=_str(d.get("digest")))


def _provenance_from_dict(d: Any) -> ProvenanceLink | None:
    if not isinstance(d, dict):
        return None
    relation = _str(d.get("relation"))
    source_id = _str(d.get("sourceId"))
    if not relation or not source_id:
        return None
    return ProvenanceLink(
        relation=relation,
        source_id=source_id,
        source_digest=_str(d.get("sourceDigest")),
    )


def _trust_manifest_from_dict(d: Any) -> TrustManifest | None:
    """Parse a ``trustManifest`` block; ``signature`` is kept as an opaque string."""
    if not isinstance(d, dict):
        return None
    identity = _str(d.get("identity"))
    if not identity:
        return None
    attestations = [
        a
        for a in (_attestation_from_dict(x) for x in _as_list(d.get("attestations")))
        if a is not None
    ]
    provenance = [
        p
        for p in (_provenance_from_dict(x) for x in _as_list(d.get("provenance")))
        if p is not None
    ]
    return TrustManifest(
        identity=identity,
        identity_type=_str(d.get("identityType")),
        attestations=attestations,
        provenance=provenance,
        # DD-7: opaque carrier — never dereferenced, never treated as a secret.
        signature=_str(d.get("signature")),
    )


def _host_from_dict(d: Any) -> HostInfo | None:
    if not isinstance(d, dict):
        return None
    display_name = _str(d.get("displayName"))
    if not display_name:
        return None
    return HostInfo(
        display_name=display_name,
        identifier=_str(d.get("identifier")),
        documentation_url=_str(d.get("documentationUrl")),
        logo_url=_str(d.get("logoUrl")),
    )


def entry_from_dict(d: Any) -> CatalogEntry | None:
    """Deserialize one catalog entry; honest-degrade to ``None`` if malformed.

    Reads the camelCase envelope keys (``displayName`` / ``representativeQueries``
    / ``updatedAt`` / ``trustManifest``) and coerces every field defensively.
    Catches the AD-1040 value-or-reference ``__post_init__`` raise (both OR
    neither of ``url`` | ``data``) plus any coercion error, so a bad row is
    DROPPED from the discovery path rather than crashing the whole parse.
    """
    if not isinstance(d, dict):
        return None
    identifier = _str(d.get("identifier"))
    display_name = _str(d.get("displayName"))
    type_ = _str(d.get("type"))
    if not identifier or not display_name or not type_:
        return None

    url = d.get("url")
    if url is not None and not isinstance(url, str):
        url = None
    data = d.get("data")
    if data is not None and not isinstance(data, dict):
        data = None
    metadata = d.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}

    try:
        return CatalogEntry(
            identifier=identifier,
            display_name=display_name,
            type=type_,
            url=url,
            data=data,
            description=_str(d.get("description")),
            tags=_str_list(d.get("tags")),
            capabilities=_str_list(d.get("capabilities")),
            representative_queries=_str_list(d.get("representativeQueries")),
            version=_str(d.get("version")),
            updated_at=_str(d.get("updatedAt")),
            metadata=metadata,
            trust_manifest=_trust_manifest_from_dict(d.get("trustManifest")),
        )
    except (ValueError, TypeError, KeyError):
        logger.debug(
            "AD-1046: dropping malformed catalog entry %r (value-or-reference)",
            identifier,
        )
        return None


def catalog_from_dict(d: Any) -> AiCatalog:
    """Deserialize a full catalog envelope; NEVER raises (DD-6).

    Drops malformed entries, parses the optional ``host`` block, and defaults
    ``specVersion`` to ``"1.0"``. A non-dict input degrades to an empty catalog.
    """
    if not isinstance(d, dict):
        return AiCatalog()
    spec_version = _str(d.get("specVersion"), "1.0") or "1.0"
    host = _host_from_dict(d.get("host"))
    entries = [
        e
        for e in (entry_from_dict(x) for x in _as_list(d.get("entries")))
        if e is not None
    ]
    return AiCatalog(spec_version=spec_version, host=host, entries=entries)
