"""AD-754: PII redaction tests."""

from __future__ import annotations

import io
import logging

import pytest

from probos.security.pii_redaction import LogRedactionFormatter, PIIRedactor


def test_redact_email_masks_address() -> None:
    assert PIIRedactor.redact_email("Contact alice@example.com") == "Contact ***@***.***"


def test_redact_phone_masks_number() -> None:
    assert PIIRedactor.redact_phone("Call 555-123-4567") == "Call ***-***-****"


def test_redact_url_masks_query() -> None:
    assert PIIRedactor.redact_url("open https://example.com/path?api_key=abc") == "open [REDACTED_URL]"


@pytest.mark.parametrize(
    ("text", "secret"),
    [
        ("Authorization: Bearer auth-value", "auth-value"),
        ("Bearer bare-value", "bare-value"),
        ("authorization=direct-value", "direct-value"),
        ("secret: secret-value", "secret-value"),
        ("client_secret=client-value", "client-value"),
        ("credential: credential-value", "credential-value"),
        ("credentials=credentials-value", "credentials-value"),
        ("api-key=api-value", "api-value"),
        ("token: token-value", "token-value"),
        ("access_token=access-value", "access-value"),
        ("refresh-token: refresh-value", "refresh-value"),
        ("password=password-value", "password-value"),
        ('{"secret": "sensitive-value"}', "sensitive-value"),
        ("{'client_secret': 'client-value'}", "client-value"),
        ('credentials: "two word secret"', "two word secret"),
    ],
)
def test_redact_tokens_masks_credential_forms(text: str, secret: str) -> None:
    redacted = PIIRedactor.redact_tokens(text)

    assert secret not in redacted
    assert "[REDACTED]" in redacted


@pytest.mark.parametrize(
    "text",
    [
        'Authorization: Bearer "alpha bravo charlie"',
        "Authorization : Bearer 'alpha bravo charlie'",
        'authorization = Bearer "alpha bravo charlie"',
        "authorization=Bearer 'alpha bravo charlie'",
        'Bearer "alpha bravo charlie"',
        "Bearer 'alpha bravo charlie'",
    ],
)
def test_redact_tokens_masks_every_quoted_authorization_fragment(text: str) -> None:
    redacted = PIIRedactor.redact_tokens(text)

    assert "[REDACTED]" in redacted
    for distinctive_token in ("alpha", "bravo", "charlie"):
        assert distinctive_token not in redacted


def test_logger_formatter_redacts_message_content() -> None:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(LogRedactionFormatter("%(message)s"))

    logger = logging.getLogger("test.ad754.redaction")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False

    logger.info("email=alice@example.com phone=555-123-4567 token=secret123")
    output = stream.getvalue()

    assert "alice@example.com" not in output
    assert "555-123-4567" not in output
    assert "secret123" not in output
