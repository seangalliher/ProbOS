"""AD-1040: ARD catalog envelope data model.

DD-8 layer discipline: this module imports NOTHING from the rest of
``probos`` — pure stdlib dataclasses. That non-import is the byte-identical
proof that AD-1040 ships types only.

Design contracts:
  * DD-4 value-or-reference (spec §3.4): a ``CatalogEntry`` carries EXACTLY
    one of ``url`` (a reference) or ``data`` (an inline payload), enforced in
    ``__post_init__``.
  * DD-5 camelCase boundary: internal fields are snake_case; ``to_dict()`` is
    the ONLY place camelCase appears. Empty optionals are omitted from the
    serialized envelope.
  * DD-7 secrets-never-in-catalog: ``TrustManifest`` is a pure DATA CARRIER.
    It holds identity, attestations, provenance and an opaque signature
    string — it has NO signing or verification logic and never holds a
    private key.

The envelope shape mirrors the public ai-catalog / A2A agent-card /
ai-plugin / JSON-LD conventions so a ProbOS catalog is consumable by generic
ARD clients.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Attestation:
    """A signed claim about an entry (e.g. an SLSA/in-toto attestation ref)."""

    type: str
    uri: str
    digest: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"type": self.type, "uri": self.uri}
        if self.digest:
            out["digest"] = self.digest
        return out


@dataclass
class ProvenanceLink:
    """A provenance edge linking this entry to a source resource."""

    relation: str
    source_id: str
    source_digest: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"relation": self.relation, "sourceId": self.source_id}
        if self.source_digest:
            out["sourceDigest"] = self.source_digest
        return out


@dataclass
class TrustManifest:
    """DD-7: a pure DATA CARRIER for trust metadata.

    Holds identity, attestations, provenance and an opaque ``signature``
    string only. It deliberately has NO ``sign`` / ``verify`` methods and
    never carries a private key — signing and verification live elsewhere.
    """

    identity: str
    identity_type: str = ""
    attestations: list[Attestation] = field(default_factory=list)
    provenance: list[ProvenanceLink] = field(default_factory=list)
    signature: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"identity": self.identity}
        if self.identity_type:
            out["identityType"] = self.identity_type
        if self.attestations:
            out["attestations"] = [a.to_dict() for a in self.attestations]
        if self.provenance:
            out["provenance"] = [p.to_dict() for p in self.provenance]
        if self.signature:
            out["signature"] = self.signature
        return out


@dataclass
class HostInfo:
    """Identifying metadata for the catalog's host (the publishing system)."""

    display_name: str
    identifier: str = ""
    documentation_url: str = ""
    logo_url: str = ""

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"displayName": self.display_name}
        if self.identifier:
            out["identifier"] = self.identifier
        if self.documentation_url:
            out["documentationUrl"] = self.documentation_url
        if self.logo_url:
            out["logoUrl"] = self.logo_url
        return out


@dataclass
class CatalogEntry:
    """A single discoverable resource in an ARD catalog.

    DD-4 value-or-reference: exactly one of ``url`` (reference) or ``data``
    (inline payload) must be provided.
    """

    identifier: str
    display_name: str
    type: str
    url: str | None = None
    data: dict | None = None
    description: str = ""
    tags: list[str] = field(default_factory=list)
    capabilities: list[str] = field(default_factory=list)
    representative_queries: list[str] = field(default_factory=list)
    version: str = ""
    updated_at: str = ""
    metadata: dict = field(default_factory=dict)
    trust_manifest: TrustManifest | None = None

    def __post_init__(self) -> None:
        # DD-4: value-or-reference — exactly one of url|data must be set.
        if (self.url is None) == (self.data is None):
            raise ValueError("CatalogEntry requires exactly one of url|data")

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "identifier": self.identifier,
            "displayName": self.display_name,
            "type": self.type,
        }
        # url/data are governed by the value-or-reference invariant: exactly
        # one is non-None, so exactly one appears in the envelope.
        if self.url is not None:
            out["url"] = self.url
        if self.data is not None:
            out["data"] = self.data
        if self.description:
            out["description"] = self.description
        if self.tags:
            out["tags"] = self.tags
        if self.capabilities:
            out["capabilities"] = self.capabilities
        if self.representative_queries:
            out["representativeQueries"] = self.representative_queries
        if self.version:
            out["version"] = self.version
        if self.updated_at:
            out["updatedAt"] = self.updated_at
        if self.metadata:
            out["metadata"] = self.metadata
        if self.trust_manifest is not None:
            out["trustManifest"] = self.trust_manifest.to_dict()
        return out


@dataclass
class AiCatalog:
    """The top-level ARD catalog envelope (``ai-catalog+json``)."""

    spec_version: str = "1.0"
    host: HostInfo | None = None
    entries: list[CatalogEntry] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"specVersion": self.spec_version}
        if self.host is not None:
            out["host"] = self.host.to_dict()
        out["entries"] = [e.to_dict() for e in self.entries]
        return out
