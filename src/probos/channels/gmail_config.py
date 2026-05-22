"""AD-764: Gmail connector configuration.

v1 substrate uses **IMAP/SMTP with an app password** (operator generates
one at https://myaccount.google.com/apppasswords; requires 2FA enabled
on the Google account). This is intentionally the simplest possible
authentication path for the v1 scaffold.

Full Gmail API + OAuth 2.0 (Google Cloud project, OAuth consent screen,
refresh tokens) is AD-764a. It's the production path — but it requires
significant operator setup (project creation, consent screen review for
verified scopes, token storage) that v1 substrate cannot scaffold
without producing security pitfalls. Operators with the bandwidth for
Google Cloud setup should wait for AD-764a; operators who just want
ProbOS to read their personal Gmail can use the IMAP path here.
"""

from __future__ import annotations

from pydantic import Field

from probos.channels.base import ChannelConfig


class GmailAdapterConfig(ChannelConfig):
    """Gmail IMAP/SMTP adapter config (AD-764 v1)."""

    imap_host: str = Field(default="imap.gmail.com")
    imap_port: int = Field(default=993, ge=1, le=65535)
    smtp_host: str = Field(default="smtp.gmail.com")
    smtp_port: int = Field(default=587, ge=1, le=65535)
    address: str = Field(
        default="",
        description="Gmail address (e.g. you@gmail.com)",
    )
    app_password: str = Field(
        default="",
        description=(
            "Google account app password (prefer env var "
            "PROBOS_GMAIL_APP_PASSWORD). Generate at "
            "https://myaccount.google.com/apppasswords"
        ),
    )
    mailbox: str = Field(
        default="INBOX",
        description="IMAP folder to poll for unread mail.",
    )
    allowed_senders: list[str] = Field(
        default_factory=list,
        description="Empty = respond to all senders; populate with addresses to restrict.",
    )
    poll_interval_s: float = Field(
        default=60.0,
        ge=10.0,
        description="Seconds between IMAP polls. Default 60s; Gmail rate-limits "
                    "aggressive polling.",
    )
    mark_seen: bool = Field(
        default=True,
        description="Mark mail as Seen after processing. False keeps it unread.",
    )
