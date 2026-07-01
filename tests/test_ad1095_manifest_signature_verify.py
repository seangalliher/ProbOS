"""AD-1095: tests for ARD detached-signature verification (real Ed25519, no mocks).

BF-287: uses the REAL ``device_pairing`` keypair/sign primitives so the verify
path exercises live cryptography — a MagicMock would hide a broken
canonicalization or a mis-wired verify call. ``verify_entry`` /
``verify_manifest_signature`` are pure/sync (no async, no DB, no data dir).

Run: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1095_manifest_signature_verify.py -q -n 0 -p no:cacheprovider
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from probos.federation.ard import (
    MT_PROBOS_TOOL,
    Attestation,
    CatalogEntry,
    TrustManifest,
    verify_entry,
)
from probos.federation.ard.trust_verifier import verify_manifest_signature
from probos.substrate.device_pairing import generate_keypair, sign_challenge

_HOST = "pub.example.com"
_URN = "urn:air:pub.example.com:tools:x"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _canonical(manifest: TrustManifest) -> str:
    """The documented AD-1095 canonicalization — the interop contract an issuer
    MUST reproduce: manifest.to_dict() minus ``signature``, sorted keys, tight
    separators.
    """
    payload = {k: v for k, v in manifest.to_dict().items() if k != "signature"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _manifest(
    *,
    identity: str = _HOST,
    attestations: Sequence[Attestation] = (),
    signature: str = "",
) -> TrustManifest:
    return TrustManifest(
        identity=identity, attestations=list(attestations), signature=signature
    )


def _entry(*, manifest: TrustManifest | None) -> CatalogEntry:
    return CatalogEntry(
        identifier=_URN,
        display_name="X",
        type=MT_PROBOS_TOOL,
        data={"a": 1},
        trust_manifest=manifest,
    )


def _sign_manifest(manifest: TrustManifest, private_key) -> None:
    """Sign the manifest's canonical payload and attach the signature in place."""
    manifest.signature = sign_challenge(private_key, _canonical(manifest))


# --------------------------------------------------------------------------- #
# verify_entry with an issuer key — evidence now counts
# --------------------------------------------------------------------------- #


def test_verify_entry_valid_signature_verified_and_evidence_counts() -> None:
    private_key, public = generate_keypair()
    manifest = _manifest()
    _sign_manifest(manifest, private_key)
    report = verify_entry(
        _entry(manifest=manifest), endpoint_host=_HOST, issuer_public_key_b64=public
    )
    assert report.signature_present is True
    assert report.signature_verified is True
    # base 1.0 + domain 1.0 + signature 1.0 — the +_W_SIGNATURE evidence fired.
    assert report.alpha == 3.0
    assert any("verified against issuer key" in n for n in report.notes)


def test_verify_entry_signature_evidence_exceeds_no_key_baseline() -> None:
    private_key, public = generate_keypair()
    manifest = _manifest()
    _sign_manifest(manifest, private_key)
    entry = _entry(manifest=manifest)
    with_key = verify_entry(entry, endpoint_host=_HOST, issuer_public_key_b64=public)
    no_key = verify_entry(entry, endpoint_host=_HOST)
    assert with_key.alpha == no_key.alpha + 1.0  # exactly _W_SIGNATURE more
    assert with_key.signature_verified is True
    assert no_key.signature_verified is False


def test_verify_entry_no_issuer_key_is_backward_compatible() -> None:
    # Backward-compat: no key → signature_verified stays False, byte-identical to
    # the AD-1047 honest-degrade (alpha = base + domain only, "unverified" note).
    private_key, _public = generate_keypair()
    manifest = _manifest()
    _sign_manifest(manifest, private_key)
    report = verify_entry(_entry(manifest=manifest), endpoint_host=_HOST)
    assert report.signature_present is True
    assert report.signature_verified is False
    assert report.alpha == 2.0  # base 1.0 + domain 1.0 only
    assert any("unverified" in n for n in report.notes)


def test_verify_entry_wrong_public_key_fails() -> None:
    private_key, _ = generate_keypair()
    _, other_public = generate_keypair()  # a DIFFERENT keypair's public key
    manifest = _manifest()
    _sign_manifest(manifest, private_key)
    report = verify_entry(
        _entry(manifest=manifest),
        endpoint_host=_HOST,
        issuer_public_key_b64=other_public,
    )
    assert report.signature_verified is False
    assert report.alpha == 2.0  # no signature evidence
    assert any("failed verification" in n for n in report.notes)


def test_verify_entry_tampered_signature_fails() -> None:
    private_key, public = generate_keypair()
    manifest = _manifest()
    _sign_manifest(manifest, private_key)
    # Corrupt the (valid) signature — flip its first base64 char to a different
    # (still valid) base64 char so it decodes to 64 wrong bytes → InvalidSignature.
    sig = manifest.signature
    manifest.signature = ("Z" if sig[0] != "Z" else "Y") + sig[1:]
    report = verify_entry(
        _entry(manifest=manifest), endpoint_host=_HOST, issuer_public_key_b64=public
    )
    assert report.signature_verified is False
    assert report.alpha == 2.0


# --------------------------------------------------------------------------- #
# verify_manifest_signature — unit
# --------------------------------------------------------------------------- #


def test_verify_manifest_signature_valid_true() -> None:
    private_key, public = generate_keypair()
    manifest = _manifest()
    _sign_manifest(manifest, private_key)
    assert verify_manifest_signature(manifest, issuer_public_key_b64=public) is True


def test_verify_manifest_signature_empty_signature_false() -> None:
    _, public = generate_keypair()
    manifest = _manifest(signature="")
    assert verify_manifest_signature(manifest, issuer_public_key_b64=public) is False


def test_verify_manifest_signature_empty_key_false() -> None:
    private_key, _ = generate_keypair()
    manifest = _manifest()
    _sign_manifest(manifest, private_key)
    assert verify_manifest_signature(manifest, issuer_public_key_b64=None) is False
    assert verify_manifest_signature(manifest, issuer_public_key_b64="") is False


def test_verify_manifest_signature_with_attestations_valid() -> None:
    # Attestations are part of the canonical payload — signing the full manifest
    # (incl. attestations) still verifies under the documented canonicalization.
    private_key, public = generate_keypair()
    manifest = _manifest(attestations=[Attestation(type="slsa", uri="https://a/1")])
    _sign_manifest(manifest, private_key)
    assert verify_manifest_signature(manifest, issuer_public_key_b64=public) is True


# --------------------------------------------------------------------------- #
# Canonicalization interop contract — the commercial issuer MUST reproduce it
# --------------------------------------------------------------------------- #


def test_canonical_documented_form_verifies() -> None:
    private_key, public = generate_keypair()
    manifest = _manifest(attestations=[Attestation(type="slsa", uri="https://a/1")])
    # Sign the DOCUMENTED canonical form (sorted keys, tight separators, no sig).
    manifest.signature = sign_challenge(private_key, _canonical(manifest))
    assert verify_manifest_signature(manifest, issuer_public_key_b64=public) is True


def test_canonical_unsorted_serialization_does_not_verify() -> None:
    private_key, public = generate_keypair()
    manifest = _manifest(attestations=[Attestation(type="slsa", uri="https://a/1")])
    # Sign a DIFFERENT serialization (default separators, NOT sort_keys) — this
    # is NOT the interop contract, so verification MUST fail. Proves the exact
    # canonical form (sorted keys + tight separators) is load-bearing.
    payload = {k: v for k, v in manifest.to_dict().items() if k != "signature"}
    non_canonical = json.dumps(payload)  # spaced separators, insertion order
    assert non_canonical != _canonical(manifest)
    manifest.signature = sign_challenge(private_key, non_canonical)
    assert verify_manifest_signature(manifest, issuer_public_key_b64=public) is False
