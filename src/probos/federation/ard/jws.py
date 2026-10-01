"""RFC 7515 compact JWS with a detached payload (RFC 7515 Appendix F).

Generic over the signed bytes: the caller supplies the payload, and the
Ed25519 sign/verify primitives are injected callables. Extracted from the ARD
trust verifier (AD-1144) so a second signer reuses one implementation rather
than growing its own (AD-1196). Like ``jcs.py`` beside it, this module imports
only the standard library, so a third-party harness can vendor it verbatim.

Wire form: ``BASE64URL(protected) || '..' || BASE64URL(signature)`` -- an EMPTY
payload segment. The signing input is reconstructed locally from the payload
bytes the verifier already holds, so a signer can never choose the bytes a
verifier checks.
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Callable, Mapping
from typing import Any, NamedTuple

__all__ = [
    "JWS_ALG",
    "DetachedJws",
    "b64url_decode",
    "b64url_encode",
    "compact_detached",
    "encode_protected_header",
    "parse_detached",
    "signing_input",
    "verify_detached",
    "verify_parsed",
]

# AD-1144 DD-2: the ONLY JWS algorithm this verifier accepts. Pinning it (rather
# than trusting the header) is the algorithm-confusion defense — ``none``,
# ``HS256`` and friends are rejected before any key material is touched.
JWS_ALG = "EdDSA"

# RFC 7515 section 2 base64url alphabet, unpadded. Validated explicitly because
# ``base64.urlsafe_b64decode`` SILENTLY DISCARDS out-of-alphabet characters,
# which would let a tampered segment decode instead of failing at this boundary.
_B64URL_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class DetachedJws(NamedTuple):
    """A structurally valid detached JWS: the protected segment, its header, the raw signature."""

    protected_b64: str
    header: dict[str, Any]
    signature: bytes


def b64url_encode(data: bytes) -> str:
    """RFC 7515 section 2 BASE64URL: urlsafe base64 with the padding stripped."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(segment: str) -> bytes:
    """Decode one unpadded base64url segment, rejecting out-of-alphabet input.

    Raises ``ValueError`` on a malformed segment (the caller's trust boundary
    converts that to ``False``).
    """
    if not _B64URL_RE.match(segment):
        raise ValueError("RFC 7515: segment is not valid unpadded base64url")
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def signing_input(protected_b64: str, payload: bytes) -> bytes:
    """RFC 7515 section 5.1 JWS Signing Input for a detached payload.

    ``ASCII(BASE64URL(UTF8(protected header)) || '.' || BASE64URL(payload))``.

    Args:
        protected_b64: The already-base64url-encoded protected header segment.
        payload: The raw payload bytes.

    Returns:
        The ASCII bytes an Ed25519 signature is computed over / verified against.
    """
    return f"{protected_b64}.{b64url_encode(payload)}".encode("ascii")


def encode_protected_header(header: Mapping[str, Any]) -> str:
    """Encode a protected header for signing: compact, key-sorted, ASCII JSON in base64url.

    Raises ``ValueError`` for a header this module's own verifier would refuse:
    an ``alg`` other than :data:`JWS_ALG`, or any ``crit`` member.
    """
    if header.get("alg") != JWS_ALG or "crit" in header:
        raise ValueError("RFC 7515: the protected header must use EdDSA and carry no crit member")
    text = json.dumps(dict(header), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return b64url_encode(text.encode("ascii"))


def compact_detached(protected_b64: str, signature: bytes) -> str:
    """The detached compact serialization: protected segment, empty payload segment, signature."""
    return f"{protected_b64}..{b64url_encode(signature)}"


def parse_detached(jws: str, *, expected_typ: str | None = None) -> DetachedJws | None:
    """Parse a detached JWS, returning ``None`` for any shape this module does not accept.

    Accepted shape -- plain detached JWS, no RFC 7797 ``b64``/``crit``: three
    segments, an EMPTY payload segment (RFC 7515 Appendix F), a JSON-object
    protected header whose ``alg`` is :data:`JWS_ALG`. When ``expected_typ`` is
    given the header's ``typ`` must equal it, so a signature issued for one
    purpose cannot be replayed as another.

    Raises ``ValueError`` on malformed base64url or JSON; the caller's trust
    boundary converts that to ``False``.
    """
    parts = jws.split(".")
    if len(parts) != 3:
        return None
    protected_b64, payload_b64, signature_b64url = parts
    if payload_b64:
        # Detached only: an attached payload is a different scheme, and honouring
        # it would let a signer choose bytes other than the canonical manifest.
        return None

    header = json.loads(b64url_decode(protected_b64))
    if not isinstance(header, dict):
        return None
    if header.get("alg") != JWS_ALG:
        return None
    if "crit" in header:
        # RFC 7515 section 4.1.11: a recipient MUST reject a JWS carrying a
        # critical header parameter it does not understand — this verifier
        # understands none. This also rejects the RFC 7797 ``b64: false``
        # variant, which DD-2 deliberately did not choose.
        return None
    if expected_typ is not None and header.get("typ") != expected_typ:
        return None
    return DetachedJws(protected_b64, header, b64url_decode(signature_b64url))


def verify_parsed(
    parsed: DetachedJws,
    payload: bytes,
    public_key_b64: str,
    verify: Callable[[str, str, str], bool],
) -> bool:
    """Verify a parsed detached JWS over ``payload`` with the injected Ed25519 ``verify``.

    ``verify`` speaks STANDARD base64 for the signature; JWS speaks base64url.
    The signature is re-encoded across that boundary rather than duplicating
    the Ed25519 primitive.
    """
    message = signing_input(parsed.protected_b64, payload).decode("ascii")
    signature_b64 = base64.b64encode(parsed.signature).decode("ascii")
    return verify(public_key_b64, message, signature_b64)


def verify_detached(
    jws: str,
    payload: bytes,
    public_key_b64: str,
    verify: Callable[[str, str, str], bool],
    *,
    expected_typ: str | None = None,
) -> bool:
    """Parse then verify; ``False`` for a refused shape. Raises ``ValueError`` on malformed input."""
    parsed = parse_detached(jws, expected_typ=expected_typ)
    if parsed is None:
        return False
    return verify_parsed(parsed, payload, public_key_b64, verify)
