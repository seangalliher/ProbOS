"""AD-1047: ARD entry trust verification (verify-only; "score != trust").

DD-2 verify-only: this module VERIFIES a catalog entry's published provenance
(publisher-domain match, attestations present, signature present) and SEEDS a
probationary Beta prior into the trust network ONCE via ``create_with_prior`` —
it NEVER calls ``record_outcome`` (that is observed-execution territory,
AD-1049+). A verification is NOT an execution, so it must not move an entity's
trust the way an outcome does.

"score != trust": ``VerificationReport.score`` is a verification CONFIDENCE (the
fraction of checks that passed); the entity's TRUST value is the SEPARATE
``trust_network.get_score(id) = alpha / (alpha + beta)``. The two are different
numbers by construction — a test asserts they are not equal.

JWS honest-degrade (v1): there is NO JWS / JOSE verifier-key infrastructure in
``src/probos`` (confirmed), so ``signature_verified`` is ALWAYS ``False`` with an
explanatory note. A present-but-unverified signature does NOT raise trust. No
signature ISSUANCE here (that is commercial).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .catalog import CatalogEntry
from .urn import publisher_domain

logger = logging.getLogger(__name__)

# Evidence weights added to ``alpha`` (the Beta success pseudo-count).
_W_DOMAIN = 1.0
_W_ATTEST = 0.5
_W_SIGNATURE = 1.0


def _norm_host(host: str) -> str:
    """Lowercase + strip a trailing ``:port`` for case/port-insensitive compare."""
    h = (host or "").strip().lower()
    if ":" in h:
        h = h.split(":", 1)[0]
    return h


@dataclass
class VerificationReport:
    """The outcome of verifying one catalog entry (DD-2 verify-only)."""

    identifier: str
    publisher_domain: str
    endpoint_host: str
    domain_match: bool
    has_attestations: bool
    signature_present: bool
    signature_verified: bool
    score: float
    alpha: float
    beta: float
    notes: list[str] = field(default_factory=list)


def verify_entry(
    entry: CatalogEntry,
    *,
    endpoint_host: str,
    base_alpha: float = 1.0,
    base_beta: float = 3.0,
) -> VerificationReport:
    """Verify a catalog entry's published provenance into a report (DD-2).

    Checks (all non-raising):
      * ``domain_match`` — the URN publisher domain equals the serving
        ``endpoint_host`` (case/port-insensitive).
      * ``has_attestations`` — the trust manifest carries >= 1 attestation.
      * ``signature_present`` — the trust manifest carries a signature string.
      * ``signature_verified`` — ALWAYS ``False`` in v1 (no verifier-key infra).

    ``alpha`` accrues evidence weight above ``base_alpha`` (domain +1.0,
    attestations +0.5, verified-signature +1.0); ``beta`` stays at ``base_beta``
    (probationary). ``score`` is the fraction of the three confidence checks
    (domain, attestations, signature-VERIFIED) that passed — a verification
    confidence, distinct from the resulting trust value.
    """
    pub = publisher_domain(entry.identifier)
    tm = entry.trust_manifest

    domain_match = bool(pub) and _norm_host(pub) == _norm_host(endpoint_host)
    has_attestations = bool(tm and tm.attestations)
    signature_present = bool(tm and tm.signature)
    signature_verified = False  # DD-2 JWS honest-degrade: no verifier-key infra

    notes: list[str] = []
    if signature_present and not signature_verified:
        notes.append("signature present but unverified — no verifier key (v1)")
    if not pub:
        notes.append("no publisher domain in identifier")
    elif not domain_match:
        notes.append(
            f"publisher domain {pub!r} != endpoint host {endpoint_host!r}"
        )

    alpha = base_alpha
    if domain_match:
        alpha += _W_DOMAIN
    if has_attestations:
        alpha += _W_ATTEST
    if signature_verified:
        alpha += _W_SIGNATURE
    beta = base_beta

    checks = [domain_match, has_attestations, signature_verified]
    score = sum(1 for c in checks if c) / len(checks)

    return VerificationReport(
        identifier=entry.identifier,
        publisher_domain=pub,
        endpoint_host=endpoint_host,
        domain_match=domain_match,
        has_attestations=has_attestations,
        signature_present=signature_present,
        signature_verified=signature_verified,
        score=score,
        alpha=alpha,
        beta=beta,
        notes=notes,
    )


def seed_trust_prior(
    trust_network: Any, entity_id: str, report: VerificationReport
) -> float:
    """Seed a probationary Beta prior from a report ONCE; return the trust score.

    DD-2: uses ``create_with_prior`` (a NO-OP if the entity already has a record,
    so re-verifying NEVER resets an entity's evolved trust) — NOT
    ``record_outcome`` (verification is not an observed execution). Returns the
    resulting ``trust_network.get_score(entity_id) = alpha / (alpha + beta)``,
    which is a DIFFERENT number from ``report.score`` (the verification
    confidence) by construction.
    """
    trust_network.create_with_prior(entity_id, report.alpha, report.beta)
    return trust_network.get_score(entity_id)
