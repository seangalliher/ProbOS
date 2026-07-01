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

Signature verification (AD-1095): ``signature_verified`` is computed by
``verify_manifest_signature`` against an OPTIONAL ``issuer_public_key_b64``. It
is DEFAULT-INERT — with no issuer key supplied (the default) it stays ``False``
(byte-identical to the AD-1047 honest-degrade), so no evidence accrues. When a
key IS supplied and the detached Ed25519 signature over the canonical manifest
JSON verifies, ``signature_verified`` becomes ``True`` and the +signature
evidence weight fires. Signature ISSUANCE remains out of scope here (commercial).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from .catalog import CatalogEntry, TrustManifest
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


def verify_manifest_signature(
    manifest: TrustManifest, *, issuer_public_key_b64: str | None = None
) -> bool:
    """AD-1095: verify a manifest's detached signature against an issuer key.

    Honest-degrade / DEFAULT-INERT: returns ``False`` immediately when there is
    no signature or no ``issuer_public_key_b64`` (the default) — so a caller
    that supplies no key sees the byte-identical AD-1047 behaviour (no evidence).

    The signed payload is the CANONICAL JSON of ``manifest.to_dict()`` with the
    ``signature`` field removed, ``sort_keys=True`` and tight
    ``separators=(",", ":")``. This EXACT canonicalization is the interop
    contract a (commercial) issuer MUST reproduce to sign; the OSS side only
    VERIFIES. Reuses the substrate Ed25519 ``verify_signature`` primitive
    (AD-843b) — no new crypto dependency. Imported lazily to preserve the ARD
    package's no-cross-layer-at-load-time convention.
    """
    if not manifest.signature or not issuer_public_key_b64:
        return False
    from probos.substrate.device_pairing import verify_signature

    try:
        payload = {
            k: v for k, v in manifest.to_dict().items() if k != "signature"
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return verify_signature(issuer_public_key_b64, canonical, manifest.signature)
    except Exception:  # noqa: BLE001 — trust boundary: never raise, fail-closed
        logger.warning(
            "AD-1095: manifest signature verification errored for identity %r; "
            "degrading to unverified (no evidence)",
            getattr(manifest, "identity", "?"),
        )
        return False


def verify_entry(
    entry: CatalogEntry,
    *,
    endpoint_host: str,
    base_alpha: float = 1.0,
    base_beta: float = 3.0,
    issuer_public_key_b64: str | None = None,
) -> VerificationReport:
    """Verify a catalog entry's published provenance into a report (DD-2).

    Checks (all non-raising):
      * ``domain_match`` — the URN publisher domain equals the serving
        ``endpoint_host`` (case/port-insensitive).
      * ``has_attestations`` — the trust manifest carries >= 1 attestation.
      * ``signature_present`` — the trust manifest carries a signature string.
      * ``signature_verified`` — ``True`` iff an ``issuer_public_key_b64`` is
        supplied AND the manifest's detached signature verifies (AD-1095);
        ``False`` by default (no key supplied) — byte-identical honest-degrade.

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
    # AD-1095: verify only when an issuer key is supplied; DEFAULT-INERT → False
    # (byte-identical to the AD-1047 honest-degrade when no key is passed).
    signature_verified = (
        verify_manifest_signature(tm, issuer_public_key_b64=issuer_public_key_b64)
        if (tm and issuer_public_key_b64)
        else False
    )

    notes: list[str] = []
    if signature_present and signature_verified:
        notes.append("signature verified against issuer key (AD-1095)")
    elif signature_present and issuer_public_key_b64:
        notes.append("signature present but failed verification against issuer key")
    elif signature_present:
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
