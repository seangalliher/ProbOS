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

Standards adoption (AD-1144, DD-1/DD-2/DD-3): the hand-rolled AD-1095 scheme is
superseded by RFC 8785 (JCS) canonicalization plus an RFC 7515 detached-payload
JWS, so any stock JOSE implementation can verify an ARD manifest. Both forms
verify during the transition (DD-3) and dispatch is on SHAPE, not a version
field — a JWS compact serialization carries ``.`` separators; the legacy bare
base64 signature never does. That self-description is why no ``specVersion``
bump is required. DD-4: the default-inert contract above is unchanged.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .catalog import CatalogEntry, TrustManifest
from .jcs import canonicalize
from .urn import publisher_domain

logger = logging.getLogger(__name__)

# Evidence weights added to ``alpha`` (the Beta success pseudo-count).
_W_DOMAIN = 1.0
_W_ATTEST = 0.5
_W_SIGNATURE = 1.0

# AD-1144 DD-2: the ONLY JWS algorithm this verifier accepts. Pinning it (rather
# than trusting the header) is the algorithm-confusion defense — ``none``,
# ``HS256`` and friends are rejected before any key material is touched.
_JWS_ALG = "EdDSA"

# RFC 7515 section 2 base64url alphabet, unpadded. Validated explicitly because
# ``base64.urlsafe_b64decode`` SILENTLY DISCARDS out-of-alphabet characters,
# which would let a tampered segment decode instead of failing at this boundary.
_B64URL_RE = re.compile(r"^[A-Za-z0-9_-]+$")


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


def _b64url_encode(data: bytes) -> str:
    """RFC 7515 section 2 BASE64URL: urlsafe base64 with the padding stripped."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(segment: str) -> bytes:
    """Decode one unpadded base64url segment, rejecting out-of-alphabet input.

    Raises ``ValueError`` on a malformed segment (the caller's trust boundary
    converts that to ``False``).
    """
    if not _B64URL_RE.match(segment):
        raise ValueError("RFC 7515: segment is not valid unpadded base64url")
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def _manifest_payload(manifest: TrustManifest) -> dict[str, Any]:
    """The signed payload: ``manifest.to_dict()`` with ``signature`` removed.

    Shared by BOTH verify paths (DD-3) so "what is covered by the signature" has
    exactly one definition; only the CANONICALIZATION of it differs between the
    legacy AD-1095 form and the AD-1144 JCS form.
    """
    return {k: v for k, v in manifest.to_dict().items() if k != "signature"}


def _legacy_canonical(manifest: TrustManifest) -> str:
    """AD-1095's hand-rolled canonical JSON, retained for dual-verify (DD-3).

    Superseded by :func:`build_signing_input`; kept verbatim so signatures
    already issued under the old scheme keep verifying until the issuer has
    migrated. Do NOT "fix" this to match JCS — that would break exactly the
    signatures it exists to accept.
    """
    return json.dumps(
        _manifest_payload(manifest), sort_keys=True, separators=(",", ":")
    )


def build_signing_input(manifest: TrustManifest) -> bytes:
    """AD-1144 (DD-1): the RFC 8785 canonical bytes of the manifest minus signature.

    This is the ONE definition of the signed payload, shared by the verify path
    here and by any issuer, so the two cannot drift. Pure and side-effect-free.

    Args:
        manifest: The trust manifest to canonicalize.

    Returns:
        The RFC 8785 (JCS) canonical UTF-8 serialization of the manifest's
        dictionary form with the ``signature`` member removed.

    Raises:
        ValueError: If the manifest carries a value RFC 8785 cannot canonicalize.
    """
    return canonicalize(_manifest_payload(manifest))


def build_jws_signing_input(protected_b64: str, payload: bytes) -> bytes:
    """RFC 7515 section 5.1 JWS Signing Input for a detached payload.

    ``ASCII(BASE64URL(UTF8(protected header)) || '.' || BASE64URL(payload))``.

    Args:
        protected_b64: The already-base64url-encoded protected header segment.
        payload: The raw payload bytes — for ARD, :func:`build_signing_input`.

    Returns:
        The ASCII bytes an Ed25519 signature is computed over / verified against.
    """
    return f"{protected_b64}.{_b64url_encode(payload)}".encode("ascii")


def _verify_jws_detached(
    manifest: TrustManifest,
    jws: str,
    issuer_public_key_b64: str,
    verify_signature: Callable[[str, str, str], bool],
) -> bool:
    """AD-1144 (DD-2): verify an RFC 7515 detached-payload JWS over the JCS bytes.

    Chosen shape — plain detached JWS, no RFC 7797 ``b64``/``crit``:
    the wire value is the compact serialization with an EMPTY payload segment
    (RFC 7515 Appendix F), ``BASE64URL(protected) || '..' || BASE64URL(sig)``,
    while the signing input reconstructs the payload segment locally from
    :func:`build_signing_input`. That is the most widely supported detached
    form, so a stock JOSE verifier needs no extension support.

    ``verify_signature`` is injected rather than imported so this module keeps
    its single lazy cross-layer import (DD-5).

    Raises on malformed input; the caller converts that to ``False``.
    """
    parts = jws.split(".")
    if len(parts) != 3:
        return False
    protected_b64, payload_b64, signature_b64url = parts
    if payload_b64:
        # Detached only: an attached payload is a different scheme, and honouring
        # it would let a signer choose bytes other than the canonical manifest.
        return False

    header = json.loads(_b64url_decode(protected_b64))
    if not isinstance(header, dict):
        return False
    if header.get("alg") != _JWS_ALG:
        return False
    if "crit" in header:
        # RFC 7515 section 4.1.11: a recipient MUST reject a JWS carrying a
        # critical header parameter it does not understand — this verifier
        # understands none. This also rejects the RFC 7797 ``b64: false``
        # variant, which DD-2 deliberately did not choose.
        return False

    signing_input = build_jws_signing_input(
        protected_b64, build_signing_input(manifest)
    )
    # ``verify_signature`` speaks STANDARD base64 for the signature; JWS speaks
    # base64url. Re-encode across that boundary rather than duplicating the
    # Ed25519 primitive.
    signature_b64 = base64.b64encode(_b64url_decode(signature_b64url)).decode("ascii")
    return verify_signature(
        issuer_public_key_b64, signing_input.decode("ascii"), signature_b64
    )


def verify_manifest_signature(
    manifest: TrustManifest, *, issuer_public_key_b64: str | None = None
) -> bool:
    """AD-1095/AD-1144: verify a manifest's detached signature against an issuer key.

    Honest-degrade / DEFAULT-INERT (DD-4): returns ``False`` immediately when
    there is no signature or no ``issuer_public_key_b64`` (the default) — so a
    caller that supplies no key sees the byte-identical AD-1047 behaviour (no
    evidence). It never raises.

    AD-1144 dual-verify (DD-3) dispatches on the signature's SHAPE:

    * Contains ``.`` → an RFC 7515 detached JWS whose payload is the RFC 8785
      (JCS) canonicalization of the manifest minus ``signature``. This is the
      standards-based form; any stock JOSE stack can produce it.
    * No ``.`` → the legacy AD-1095 bare-base64 signature over
      ``json.dumps(..., sort_keys=True, separators=(",", ":"))``. Retained until
      the issuer has migrated; do not remove it.

    Both reuse the substrate Ed25519 ``verify_signature`` primitive (AD-843b) —
    no new crypto dependency. It is imported lazily, ONCE, to preserve this
    package's no-cross-layer-at-load-time convention (DD-5).
    """
    if not manifest.signature or not issuer_public_key_b64:
        return False
    from probos.substrate.device_pairing import verify_signature

    try:
        if "." in manifest.signature:
            return _verify_jws_detached(
                manifest,
                manifest.signature,
                issuer_public_key_b64,
                verify_signature,
            )
        return verify_signature(
            issuer_public_key_b64, _legacy_canonical(manifest), manifest.signature
        )
    except Exception:  # noqa: BLE001 — trust boundary: never raise, fail-closed
        logger.warning(
            "AD-1095/AD-1144: manifest signature verification errored for identity "
            "%r; degrading to unverified (no evidence)",
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
