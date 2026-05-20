"""AD-754: PII redaction helpers for logs, traces, and artifacts."""

from __future__ import annotations

import logging
import re
from typing import Iterable


class PIIRedactor:
    """Masking engine for logs, traces, and memory artifacts."""

    _EMAIL_PATTERN = re.compile(r"[\w\.-]+@[\w\.-]+\.\w+")
    _PHONE_PATTERN = re.compile(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b")
    _URL_PATTERN = re.compile(r"https?://[^\s]+")
    _DOCID_PATTERN = re.compile(r"(docid|file_id|item_id)=([A-Za-z0-9_\-]+)", re.IGNORECASE)
    _TOKEN_PATTERN = re.compile(
        r"(?i)\b(api[_-]?key|token|access_token|refresh_token|password)\s*[:=]\s*([^\s,;]+)"
    )

    @staticmethod
    def redact_email(text: str) -> str:
        """Replace email addresses."""
        return PIIRedactor._EMAIL_PATTERN.sub("***@***.***", text)

    @staticmethod
    def redact_phone(text: str) -> str:
        """Replace phone numbers."""
        return PIIRedactor._PHONE_PATTERN.sub("***-***-****", text)

    @staticmethod
    def redact_url(text: str) -> str:
        """Replace URLs including path/query components."""
        return PIIRedactor._URL_PATTERN.sub("[REDACTED_URL]", text)

    @staticmethod
    def redact_doc_ids(text: str) -> str:
        """Replace document/file/item identifiers in query-like text."""
        return PIIRedactor._DOCID_PATTERN.sub(r"\1=[REDACTED]", text)

    @staticmethod
    def redact_tokens(text: str) -> str:
        """Replace token/secret-like key-value pairs."""
        return PIIRedactor._TOKEN_PATTERN.sub(r"\1=[REDACTED]", text)

    @staticmethod
    def redact_all(text: str) -> str:
        """Apply all redaction rules."""
        text = PIIRedactor.redact_email(text)
        text = PIIRedactor.redact_phone(text)
        text = PIIRedactor.redact_url(text)
        text = PIIRedactor.redact_doc_ids(text)
        text = PIIRedactor.redact_tokens(text)
        return text


class LogRedactionFormatter(logging.Formatter):
    """Logging formatter that redacts PII and token-like values."""

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        return PIIRedactor.redact_all(message)


def apply_redaction_to_handlers(handlers: Iterable[logging.Handler]) -> None:
    """Install redaction formatter on provided handlers."""
    for handler in handlers:
        current = handler.formatter
        if current is not None:
            style = "%"
            style_obj = getattr(current, "_style", None)
            style_name = type(style_obj).__name__ if style_obj is not None else ""
            if style_name == "StrFormatStyle":
                style = "{"
            elif style_name == "StringTemplateStyle":
                style = "$"
            handler.setFormatter(
                LogRedactionFormatter(
                    fmt=current._fmt,
                    datefmt=current.datefmt,
                    style=style,
                )
            )
        else:
            handler.setFormatter(LogRedactionFormatter("%(message)s"))
