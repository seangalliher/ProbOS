"""AD-754: PII redaction tests."""

from __future__ import annotations

import io
import logging

from probos.security.pii_redaction import LogRedactionFormatter, PIIRedactor


def test_redact_email_masks_address() -> None:
    assert PIIRedactor.redact_email("Contact alice@example.com") == "Contact ***@***.***"


def test_redact_phone_masks_number() -> None:
    assert PIIRedactor.redact_phone("Call 555-123-4567") == "Call ***-***-****"


def test_redact_url_masks_query() -> None:
    assert PIIRedactor.redact_url("open https://example.com/path?api_key=abc") == "open [REDACTED_URL]"


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
