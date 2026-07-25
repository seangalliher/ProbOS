"""AD-1144: RFC 8785 (JCS) + RFC 7515 (detached JWS) for ARD trust manifests.

BF-287: the crypto path uses the REAL ``device_pairing`` Ed25519 primitives and,
for the interop proof, raw ``cryptography`` — a mock would hide exactly the
canonicalization/signing-input bugs these tests exist to catch. All functions
under test are pure/sync (no async, no DB, no data dir).

Run: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1144_jcs_jws.py -q -n 0 -p no:cacheprovider
"""

from __future__ import annotations

import base64
import json
import math
import re
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from probos.federation.ard import Attestation, TrustManifest
from probos.federation.ard.jcs import canonicalize
from probos.federation.ard.trust_verifier import (
    build_jws_signing_input,
    build_signing_input,
    verify_manifest_signature,
)
from probos.substrate.device_pairing import generate_keypair, sign_challenge

_ARD_DIR = Path(__file__).resolve().parents[1] / "src" / "probos" / "federation" / "ard"

# RFC 8785 section 3.2.3's own example object. Its key set is chosen precisely to
# expose the UTF-16-code-unit vs code-point divergence.
_RFC8785_SORT_INPUT: dict[str, str] = {
    "\u20ac": "Euro Sign",
    "\r": "Carriage Return",
    "\ufb33": "Hebrew Letter Dalet With Dagesh",
    "1": "One",
    "\U0001f600": "Emoji: Grinning Face",
    "\u0080": "Control",
    "\u00f6": "Latin Small Letter O With Diaeresis",
}
_RFC8785_SORT_EXPECTED = (
    # NOTE: ``\\r`` — the CR key is emitted as the two-character JSON escape,
    # not a literal carriage return.
    '{"\\r":"Carriage Return",'
    '"1":"One",'
    '"\u0080":"Control",'
    '"\u00f6":"Latin Small Letter O With Diaeresis",'
    '"\u20ac":"Euro Sign",'
    '"\U0001f600":"Emoji: Grinning Face",'
    '"\ufb33":"Hebrew Letter Dalet With Dagesh"}'
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _legacy_canonical(manifest: TrustManifest) -> str:
    """The AD-1095 hand-rolled canonical form (what the legacy issuer signed)."""
    payload = {k: v for k, v in manifest.to_dict().items() if k != "signature"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64u_decode(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def _manifest(*, signature: str = "") -> TrustManifest:
    return TrustManifest(
        identity="pub.example.com",
        identity_type="domain",
        attestations=[Attestation(type="slsa", uri="https://a/1")],
        signature=signature,
    )


def _sign_legacy(manifest: TrustManifest, private_key: Ed25519PrivateKey) -> None:
    """Issue an AD-1095 legacy bare-base64 signature in place."""
    manifest.signature = sign_challenge(private_key, _legacy_canonical(manifest))


def _sign_jws(
    manifest: TrustManifest,
    private_key: Ed25519PrivateKey,
    *,
    header: dict[str, Any] | None = None,
) -> str:
    """Issuer-side reference implementation of the AD-1144 detached JWS (DD-2)."""
    protected = header if header is not None else {"alg": "EdDSA", "crv": "Ed25519"}
    protected_b64 = _b64u(json.dumps(protected, separators=(",", ":")).encode("utf-8"))
    signing_input = build_jws_signing_input(
        protected_b64, build_signing_input(manifest)
    )
    # ``sign_challenge`` returns STANDARD base64; JWS wants base64url.
    raw_signature = base64.b64decode(
        sign_challenge(private_key, signing_input.decode("ascii"))
    )
    return f"{protected_b64}..{_b64u(raw_signature)}"


# --------------------------------------------------------------------------- #
# RFC 8785 conformance — key ordering (the whole point of the AD)
# --------------------------------------------------------------------------- #


def test_canonicalize_orders_keys_by_utf16_code_unit_per_rfc8785() -> None:
    assert canonicalize(_RFC8785_SORT_INPUT) == _RFC8785_SORT_EXPECTED.encode("utf-8")


def test_canonicalize_non_bmp_key_order_differs_from_python_sort_keys() -> None:
    # THE divergence AD-1144 exists to remove: a non-BMP key is a UTF-16
    # surrogate pair (0xD83D...), so JCS sorts it BEFORE U+FB33, while Python's
    # ``sort_keys=True`` (code-point order) puts U+1F600 last.
    jcs = canonicalize(_RFC8785_SORT_INPUT).decode("utf-8")
    legacy = json.dumps(
        _RFC8785_SORT_INPUT,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    assert jcs != legacy
    jcs_keys = list(json.loads(jcs))
    legacy_keys = list(json.loads(legacy))
    assert jcs_keys.index("\U0001f600") < jcs_keys.index("\ufb33")
    assert legacy_keys.index("\U0001f600") > legacy_keys.index("\ufb33")


def test_canonicalize_ascii_only_keys_agree_with_legacy_form() -> None:
    # The dangerous case: for ASCII keys with no floats the two schemes AGREE,
    # which is why the divergence went unnoticed. Pinned so a future change to
    # the canonicalizer cannot silently break already-issued legacy signatures.
    value = {"b": "two", "a": "one", "C": 3, "_z": [1, 2]}
    assert canonicalize(value).decode("utf-8") == json.dumps(
        value, sort_keys=True, separators=(",", ":")
    )


def test_canonicalize_sorts_nested_objects_too() -> None:
    assert canonicalize({"b": {"z": 1, "a": 2}, "a": 3}) == b'{"a":3,"b":{"a":2,"z":1}}'


# --------------------------------------------------------------------------- #
# RFC 8785 conformance — ECMAScript Number::toString
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0.0, "0"),
        (-0.0, "0"),  # ECMAScript renders -0 as "0"
        (1.0, "1"),  # differs from repr() -> "1.0"
        (-1.0, "-1"),
        (1.5, "1.5"),
        (0.1, "0.1"),
        (0.5, "0.5"),
        (100.0, "100"),  # differs from repr() -> "100.0"
        (123.456, "123.456"),
        (9e-4, "0.0009"),
        (1e-6, "0.000001"),  # differs from repr() -> "1e-06"
        (1e-7, "1e-7"),  # differs from repr() -> "1e-07"
        (1.5e-7, "1.5e-7"),
        (-1.5e-7, "-1.5e-7"),
        (1e15, "1000000000000000"),
        (1e16, "10000000000000000"),
        (1e20, "100000000000000000000"),  # differs from repr() -> "1e+20"
        (1e21, "1e+21"),  # the fixed/exponential boundary
        (5e-324, "5e-324"),  # smallest subnormal
        (1.7976931348623157e308, "1.7976931348623157e+308"),
        (333333333.33333331, "333333333.3333333"),
        (1234567890123456789.0, "1234567890123456800"),
    ],
)
def test_canonicalize_number_matches_ecmascript_tostring(
    value: float, expected: str
) -> None:
    assert canonicalize(value) == expected.encode("ascii")


@pytest.mark.parametrize("value", [1.0, 100.0, 1e-6, 1e-7, 1e20, -0.0])
def test_canonicalize_number_differs_from_python_repr(value: float) -> None:
    # Pins the second AD-1144 divergence: Python's float PRESENTATION is not
    # ECMAScript's, even though both round-trip.
    assert canonicalize(value).decode("ascii") != repr(value)


def test_canonicalize_integers_are_exact() -> None:
    assert canonicalize(0) == b"0"
    assert canonicalize(-42) == b"-42"
    assert canonicalize(2**53 - 1) == b"9007199254740991"


@pytest.mark.parametrize("value", [2**53, -(2**53), 10**30])
def test_canonicalize_integer_outside_ijson_range_raises(value: int) -> None:
    with pytest.raises(ValueError, match="I-JSON safe range"):
        canonicalize(value)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_canonicalize_nan_and_infinity_raise(value: float) -> None:
    with pytest.raises(ValueError, match="NaN and Infinity"):
        canonicalize(value)


def test_canonicalize_nan_and_infinity_raise_when_nested() -> None:
    with pytest.raises(ValueError, match="NaN and Infinity"):
        canonicalize({"a": [1, math.inf]})


# --------------------------------------------------------------------------- #
# RFC 8785 conformance — strings, literals, structure, rejection
# --------------------------------------------------------------------------- #


def test_canonicalize_string_escaping_is_minimal() -> None:
    # Two-char escapes for the ECMAScript set, lowercase \u00xx below 0x20,
    # and NOTHING else escaped -- DEL and non-ASCII pass through as UTF-8.
    assert canonicalize('a"b\\c\n\t\x08\x0c\r\x00\x1f\x7f\u00e9') == (
        b'"a\\"b\\\\c\\n\\t\\b\\f\\r\\u0000\\u001f\x7f\xc3\xa9"'
    )


def test_canonicalize_non_ascii_is_utf8_not_escaped() -> None:
    assert canonicalize("\U0001f600") == b'"\xf0\x9f\x98\x80"'


def test_canonicalize_literals_and_containers() -> None:
    assert canonicalize(None) == b"null"
    assert canonicalize(True) == b"true"
    assert canonicalize(False) == b"false"
    assert canonicalize([]) == b"[]"
    assert canonicalize({}) == b"{}"
    # Arrays preserve order; booleans must NOT fall through the int branch.
    assert canonicalize([True, False, None, 1, "a"]) == b'[true,false,null,1,"a"]'


def test_canonicalize_returns_utf8_bytes() -> None:
    result = canonicalize({"k": "\u00e9"})
    assert isinstance(result, bytes)
    assert result == b'{"k":"\xc3\xa9"}'


def test_canonicalize_non_string_key_raises() -> None:
    with pytest.raises(ValueError, match="keys MUST be strings"):
        canonicalize({1: "a"})


def test_canonicalize_unsupported_type_raises() -> None:
    with pytest.raises(ValueError, match="cannot canonicalize"):
        canonicalize({"a", "b"})


def test_canonicalize_lone_surrogate_raises_value_error() -> None:
    # A lone surrogate is not valid Unicode; UnicodeEncodeError subclasses
    # ValueError, so the documented failure contract still holds.
    with pytest.raises(ValueError):
        canonicalize({"\ud800": "x"})


# --------------------------------------------------------------------------- #
# DD-3 dual-verify
# --------------------------------------------------------------------------- #


def test_legacy_signature_still_verifies() -> None:
    private_key, public = generate_keypair()
    manifest = _manifest()
    _sign_legacy(manifest, private_key)
    assert "." not in manifest.signature  # shape dispatch: bare base64
    assert verify_manifest_signature(manifest, issuer_public_key_b64=public) is True


def test_jws_detached_signature_verifies() -> None:
    private_key, public = generate_keypair()
    manifest = _manifest()
    manifest.signature = _sign_jws(manifest, private_key)
    assert "." in manifest.signature  # shape dispatch: JWS compact
    assert verify_manifest_signature(manifest, issuer_public_key_b64=public) is True


def test_jws_signed_manifest_does_not_verify_under_legacy_key_confusion() -> None:
    # A JWS issued by one key must not verify under another (no shape shortcut
    # bypasses the signature check).
    private_key, _ = generate_keypair()
    _, other_public = generate_keypair()
    manifest = _manifest()
    manifest.signature = _sign_jws(manifest, private_key)
    assert (
        verify_manifest_signature(manifest, issuer_public_key_b64=other_public) is False
    )


def test_jws_tampered_protected_header_fails() -> None:
    private_key, public = generate_keypair()
    manifest = _manifest()
    manifest.signature = _sign_jws(manifest, private_key)
    _, payload_b64, signature_b64u = manifest.signature.split(".")
    forged = _b64u(json.dumps({"alg": "EdDSA", "kid": "attacker"}).encode("utf-8"))
    manifest.signature = f"{forged}.{payload_b64}.{signature_b64u}"
    assert verify_manifest_signature(manifest, issuer_public_key_b64=public) is False


def test_jws_tampered_payload_fails() -> None:
    private_key, public = generate_keypair()
    manifest = _manifest()
    manifest.signature = _sign_jws(manifest, private_key)
    assert verify_manifest_signature(manifest, issuer_public_key_b64=public) is True
    # Mutate a signed field AFTER issuance — the reconstructed JCS payload no
    # longer matches what was signed.
    manifest.identity = "evil.example.com"
    assert verify_manifest_signature(manifest, issuer_public_key_b64=public) is False


def test_jws_tampered_signature_segment_fails() -> None:
    private_key, public = generate_keypair()
    manifest = _manifest()
    manifest.signature = _sign_jws(manifest, private_key)
    protected_b64, _, signature_b64u = manifest.signature.split(".")
    flipped = ("A" if signature_b64u[0] != "A" else "B") + signature_b64u[1:]
    manifest.signature = f"{protected_b64}..{flipped}"
    assert verify_manifest_signature(manifest, issuer_public_key_b64=public) is False


@pytest.mark.parametrize(
    "header",
    [
        {"alg": "none"},
        {"alg": "HS256"},
        {"crv": "Ed25519"},  # ``alg`` absent entirely
        {"alg": "EdDSA", "b64": False, "crit": ["b64"]},  # RFC 7797 — not DD-2's shape
    ],
)
def test_jws_rejects_disallowed_protected_header(header: dict[str, Any]) -> None:
    private_key, public = generate_keypair()
    manifest = _manifest()
    manifest.signature = _sign_jws(manifest, private_key, header=header)
    assert verify_manifest_signature(manifest, issuer_public_key_b64=public) is False


def test_jws_with_attached_payload_segment_is_rejected() -> None:
    # Only the detached form is accepted; an attached payload would let a signer
    # choose bytes other than the canonical manifest.
    private_key, public = generate_keypair()
    manifest = _manifest()
    jws = _sign_jws(manifest, private_key)
    protected_b64, _, signature_b64u = jws.split(".")
    attached = _b64u(build_signing_input(manifest))
    manifest.signature = f"{protected_b64}.{attached}.{signature_b64u}"
    assert verify_manifest_signature(manifest, issuer_public_key_b64=public) is False


@pytest.mark.parametrize(
    "signature",
    [
        "a.b",  # two segments
        "a.b.c.d",  # four segments
        "..",  # all segments empty
        "!!!..abc",  # protected header out of the base64url alphabet
        "eyJhIjoxfQ..&&&",  # signature out of the base64url alphabet
        "bm90LWpzb24..YWJj",  # protected header decodes to non-JSON
        "IjEi..YWJj",  # protected header decodes to a JSON string, not an object
    ],
)
def test_jws_malformed_returns_false_and_never_raises(signature: str) -> None:
    _, public = generate_keypair()
    manifest = _manifest(signature=signature)
    assert verify_manifest_signature(manifest, issuer_public_key_b64=public) is False


# --------------------------------------------------------------------------- #
# DD-4 default-inert contract (unchanged from AD-1095)
# --------------------------------------------------------------------------- #


def test_jws_signature_without_issuer_key_is_default_inert() -> None:
    private_key, _ = generate_keypair()
    manifest = _manifest()
    manifest.signature = _sign_jws(manifest, private_key)
    assert verify_manifest_signature(manifest, issuer_public_key_b64=None) is False
    assert verify_manifest_signature(manifest, issuer_public_key_b64="") is False


def test_empty_signature_with_key_is_false() -> None:
    _, public = generate_keypair()
    assert (
        verify_manifest_signature(_manifest(), issuer_public_key_b64=public) is False
    )


# --------------------------------------------------------------------------- #
# DD-5 ARD purity invariant
# --------------------------------------------------------------------------- #


def test_jcs_module_has_zero_project_imports() -> None:
    # ``jcs.py`` must be vendorable verbatim by a third-party harness.
    source = (_ARD_DIR / "jcs.py").read_text(encoding="utf-8")
    assert "probos" not in source


def test_trust_verifier_project_import_count_unchanged() -> None:
    source = (_ARD_DIR / "trust_verifier.py").read_text(encoding="utf-8")
    imports = re.findall(r"^\s*(?:from|import)\s+probos\b", source, re.MULTILINE)
    assert len(imports) == 1


# --------------------------------------------------------------------------- #
# Interop shape — a stock JOSE stack must be able to verify this
# --------------------------------------------------------------------------- #


def test_emitted_signature_is_jws_compact_serialization() -> None:
    private_key, _ = generate_keypair()
    manifest = _manifest()
    jws = _sign_jws(manifest, private_key)
    segments = jws.split(".")
    assert len(segments) == 3
    assert segments[1] == ""  # RFC 7515 Appendix F detached payload
    assert all(re.fullmatch(r"[A-Za-z0-9_-]+", s) for s in (segments[0], segments[2]))


def test_protected_header_decodes_to_json_with_eddsa_alg() -> None:
    private_key, _ = generate_keypair()
    manifest = _manifest()
    protected_b64 = _sign_jws(manifest, private_key).split(".")[0]
    header = json.loads(_b64u_decode(protected_b64))
    assert isinstance(header, dict)
    assert header["alg"] == "EdDSA"
    assert header["crv"] == "Ed25519"


def test_third_party_can_verify_with_raw_ed25519_and_no_project_code() -> None:
    # The adoptability proof: reconstruct the RFC 7515 signing input from the
    # published bytes and verify with plain ``cryptography`` — no ProbOS-specific
    # quirk is required, which is precisely what AD-1144 buys.
    private_key, public = generate_keypair()
    manifest = _manifest()
    manifest.signature = _sign_jws(manifest, private_key)
    protected_b64, _, signature_b64u = manifest.signature.split(".")

    payload = canonicalize(
        {k: v for k, v in manifest.to_dict().items() if k != "signature"}
    )
    signing_input = f"{protected_b64}.{_b64u(payload)}".encode("ascii")

    public_key = private_key.public_key()
    public_key.verify(_b64u_decode(signature_b64u), signing_input)  # raises if invalid
    # ...and the same bytes satisfy the production verifier.
    assert verify_manifest_signature(manifest, issuer_public_key_b64=public) is True


def test_build_signing_input_excludes_signature_and_is_jcs() -> None:
    private_key, _ = generate_keypair()
    manifest = _manifest()
    before = build_signing_input(manifest)
    manifest.signature = _sign_jws(manifest, private_key)
    # Attaching the signature must not change what the signature covers.
    assert build_signing_input(manifest) == before
    assert b"signature" not in before
    assert before == canonicalize(
        {
            "identity": "pub.example.com",
            "identityType": "domain",
            "attestations": [{"type": "slsa", "uri": "https://a/1"}],
        }
    )


def test_build_jws_signing_input_matches_rfc7515_section_5_1() -> None:
    assert build_jws_signing_input("aGVhZGVy", b"payload") == b"aGVhZGVy.cGF5bG9hZA"
