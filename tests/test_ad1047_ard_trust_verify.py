"""AD-1047: tests for ARD entry trust verification (verify-only; score != trust).

DD-2: ``verify_entry`` + ``seed_trust_prior`` are pure/sync (no async, no marker).
A real ``TrustNetwork`` (no DB) is used so ``create_with_prior`` / ``get_score``
exercise the live consensus substrate (not a mock).

Run: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1047_ard_trust_verify.py -q -n 0 -p no:cacheprovider
"""

from __future__ import annotations

from collections.abc import Sequence

from probos.consensus.trust import TrustNetwork
from probos.federation.ard import (
    MT_PROBOS_TOOL,
    Attestation,
    CatalogEntry,
    TrustManifest,
    seed_trust_prior,
    verify_entry,
)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _manifest(
    *, identity: str = "pub.example.com", attestations: Sequence[Attestation] = (), signature: str = ""
) -> TrustManifest:
    return TrustManifest(identity=identity, attestations=list(attestations), signature=signature)


def _entry(
    *, identifier: str = "urn:air:pub.example.com:tools:x", manifest: TrustManifest | None = None
) -> CatalogEntry:
    return CatalogEntry(
        identifier=identifier, display_name="X", type=MT_PROBOS_TOOL, data={"a": 1}, trust_manifest=manifest
    )


# --------------------------------------------------------------------------- #
# verify_entry scoring
# --------------------------------------------------------------------------- #


def test_domain_match_raises_alpha() -> None:
    report = verify_entry(_entry(), endpoint_host="pub.example.com")
    assert report.domain_match is True
    assert report.publisher_domain == "pub.example.com"
    assert report.alpha == 2.0  # base 1.0 + domain 1.0
    assert report.beta == 3.0


def test_domain_match_is_case_and_port_insensitive() -> None:
    report = verify_entry(_entry(), endpoint_host="PUB.example.com:443")
    assert report.domain_match is True


def test_domain_mismatch_notes_and_no_alpha_bump() -> None:
    report = verify_entry(_entry(), endpoint_host="other.example.org")
    assert report.domain_match is False
    assert report.alpha == 1.0  # base only
    assert any("!=" in n for n in report.notes)


def test_no_publisher_domain_notes() -> None:
    report = verify_entry(_entry(identifier="not-a-urn"), endpoint_host="pub.example.com")
    assert report.publisher_domain == ""
    assert report.domain_match is False
    assert any("no publisher domain" in n for n in report.notes)


def test_has_attestations_raises_alpha_by_half() -> None:
    manifest = _manifest(attestations=[Attestation(type="slsa", uri="https://a/1")])
    report = verify_entry(_entry(manifest=manifest), endpoint_host="pub.example.com")
    assert report.has_attestations is True
    assert report.alpha == 2.5  # base 1.0 + domain 1.0 + attest 0.5


def test_signature_present_but_always_unverified_v1() -> None:
    manifest = _manifest(signature="opaque-sig")
    report = verify_entry(_entry(manifest=manifest), endpoint_host="pub.example.com")
    assert report.signature_present is True
    assert report.signature_verified is False  # DD-2 JWS honest-degrade
    assert any("unverified" in n for n in report.notes)
    # An unverified signature does NOT raise alpha.
    assert report.alpha == 2.0  # base 1.0 + domain 1.0 only


def test_score_is_fraction_of_three_checks() -> None:
    manifest = _manifest(attestations=[Attestation(type="slsa", uri="https://a/1")], signature="sig")
    report = verify_entry(_entry(manifest=manifest), endpoint_host="pub.example.com")
    # domain True + attestations True + signature_verified False → 2/3.
    assert report.score == 2 / 3


def test_no_manifest_no_attestations_no_signature() -> None:
    report = verify_entry(_entry(manifest=None), endpoint_host="pub.example.com")
    assert report.has_attestations is False
    assert report.signature_present is False
    assert report.score == 1 / 3  # only domain_match


# --------------------------------------------------------------------------- #
# seed_trust_prior — verify-only, score != trust
# --------------------------------------------------------------------------- #


def test_seed_trust_prior_creates_with_prior_and_returns_score() -> None:
    tn = TrustNetwork()
    entry = _entry()
    report = verify_entry(entry, endpoint_host="pub.example.com")
    trust = seed_trust_prior(tn, entry.identifier, report)
    # Beta(alpha, beta) mean = alpha / (alpha + beta) = 2.0 / 5.0 = 0.4.
    assert trust == report.alpha / (report.alpha + report.beta)
    assert tn.get_score(entry.identifier) == trust


def test_report_score_differs_from_trust_score() -> None:
    tn = TrustNetwork()
    manifest = _manifest(attestations=[Attestation(type="slsa", uri="https://a/1")])
    entry = _entry(manifest=manifest)
    report = verify_entry(entry, endpoint_host="pub.example.com")
    trust = seed_trust_prior(tn, entry.identifier, report)
    # report.score (verification confidence = 2/3) != trust (alpha/(a+b) = 2.5/5.5).
    assert report.score != trust


def test_seed_trust_prior_is_idempotent_no_op_if_exists() -> None:
    tn = TrustNetwork()
    entry = _entry()
    report = verify_entry(entry, endpoint_host="pub.example.com")
    first = seed_trust_prior(tn, entry.identifier, report)
    # A second seed with a DIFFERENT (higher-alpha) report must be a no-op.
    bigger = verify_entry(
        _entry(manifest=_manifest(attestations=[Attestation(type="slsa", uri="https://a/1")])),
        endpoint_host="pub.example.com",
    )
    second = seed_trust_prior(tn, entry.identifier, bigger)
    assert second == first  # create_with_prior is a no-op for existing entities


def test_reverify_does_not_reset_evolved_trust() -> None:
    tn = TrustNetwork()
    entry = _entry()
    seed_trust_prior(tn, entry.identifier, verify_entry(entry, endpoint_host="pub.example.com"))
    before = tn.get_score(entry.identifier)
    # Simulate later OBSERVED execution evolving the trust upward (this is
    # record_outcome territory — used here only to set up the regression).
    tn.record_outcome(entry.identifier, success=True, weight=5.0)
    evolved = tn.get_score(entry.identifier)
    assert evolved > before
    # Re-verifying + re-seeding must NOT reset the evolved trust.
    seed_trust_prior(tn, entry.identifier, verify_entry(entry, endpoint_host="pub.example.com"))
    assert tn.get_score(entry.identifier) == evolved
