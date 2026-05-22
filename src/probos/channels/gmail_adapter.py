"""AD-764: Gmail adapter (IMAP/SMTP, v1 scaffolding).

Inbound: polls the configured IMAP mailbox for UNSEEN messages,
normalizes each to a ``ChannelMessage`` (subject + body, sender's
address as user_id), and dispatches via the standard AD-472 +
AD-802a pairing-gate flow.

Outbound: SMTP STARTTLS, reply to the originating thread when a
Message-ID is known.

Per the WindowsSelectorEventLoop convention all IMAP/SMTP work runs in
``loop.run_in_executor`` (synchronous imaplib/smtplib wrapped in a
thread).
"""

from __future__ import annotations

import asyncio
import email
import email.message
import imaplib
import logging
import smtplib
import ssl
from email.mime.text import MIMEText
from typing import Any

from probos.channels.base import ChannelAdapter, ChannelMessage
from probos.channels.gmail_config import GmailAdapterConfig

logger = logging.getLogger(__name__)


class GmailAdapter(ChannelAdapter):
    """Gmail IMAP/SMTP adapter."""

    channel_name = "gmail"

    def __init__(self, runtime: Any, config: GmailAdapterConfig) -> None:
        super().__init__(runtime, config)
        self._gmail_config = config
        self._poll_task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        # message_id -> (from_address, thread_references)
        self._reply_context: dict[str, tuple[str, str]] = {}

    async def start(self) -> None:
        if self._started:
            return
        if not self._gmail_config.address or not self._gmail_config.app_password:
            logger.warning(
                "AD-764: GmailAdapter has no address / app_password; not polling"
            )
            self._started = True
            return
        self._stop.clear()
        self._poll_task = asyncio.create_task(self._poll_loop())
        self._started = True

    async def stop(self) -> None:
        if not self._started:
            return
        self._stop.set()
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except (asyncio.CancelledError, Exception):
                pass
            self._poll_task = None
        self._started = False

    async def _poll_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while not self._stop.is_set():
            try:
                messages = await loop.run_in_executor(None, self._fetch_unseen)
                for msg in messages:
                    await self.handle_message(msg)
                    # avoid swamping LLM if a flurry arrived at once
                    await asyncio.sleep(0)
            except Exception:
                logger.warning("AD-764: Gmail poll iteration failed", exc_info=True)
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self._gmail_config.poll_interval_s,
                )
            except asyncio.TimeoutError:
                continue

    def _fetch_unseen(self) -> list[ChannelMessage]:
        """Synchronous IMAP fetch; called inside run_in_executor."""
        cfg = self._gmail_config
        try:
            mail = imaplib.IMAP4_SSL(cfg.imap_host, cfg.imap_port)
            try:
                mail.login(cfg.address, cfg.app_password)
                mail.select(cfg.mailbox)
                status, data = mail.search(None, "UNSEEN")
                if status != "OK" or not data or not data[0]:
                    return []
                msg_ids = data[0].split()
                out: list[ChannelMessage] = []
                for mid in msg_ids:
                    msg = self._fetch_one(mail, mid)
                    if msg is not None:
                        out.append(msg)
                return out
            finally:
                try:
                    mail.close()
                except Exception:
                    pass
                mail.logout()
        except (imaplib.IMAP4.error, OSError) as exc:
            logger.warning("AD-764: IMAP login/fetch failed: %s", exc)
            return []

    def _fetch_one(
        self, mail: imaplib.IMAP4_SSL, mid: bytes
    ) -> ChannelMessage | None:
        status, data = mail.fetch(mid, "(RFC822)")
        if status != "OK" or not data or not data[0]:
            return None
        raw = data[0][1] if isinstance(data[0], tuple) else None
        if raw is None:
            return None
        parsed: email.message.Message = email.message_from_bytes(raw)
        sender = email.utils.parseaddr(parsed.get("From", ""))[1]
        if not sender:
            return None
        # Allow-list filter
        if (
            self._gmail_config.allowed_senders
            and sender not in self._gmail_config.allowed_senders
        ):
            return None
        subject = parsed.get("Subject", "")
        body = self._extract_body(parsed)
        if not body.strip():
            return None
        message_id = parsed.get("Message-ID", "")
        text = f"{subject}\n\n{body}" if subject else body
        self._reply_context[message_id] = (sender, parsed.get("References", message_id))
        if self._gmail_config.mark_seen:
            try:
                mail.store(mid, "+FLAGS", r"(\Seen)")
            except Exception:
                pass
        return ChannelMessage(
            text=text.strip(),
            channel_id=sender,  # thread by sender
            user_id=sender,
            user_display_name=email.utils.parseaddr(parsed.get("From", ""))[0],
            reply_to_message_id=message_id or None,
        )

    @staticmethod
    def _extract_body(parsed: email.message.Message) -> str:
        if parsed.is_multipart():
            for part in parsed.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if isinstance(payload, bytes):
                        charset = part.get_content_charset() or "utf-8"
                        try:
                            return payload.decode(charset, errors="replace")
                        except LookupError:
                            return payload.decode("utf-8", errors="replace")
        else:
            payload = parsed.get_payload(decode=True)
            if isinstance(payload, bytes):
                charset = parsed.get_content_charset() or "utf-8"
                try:
                    return payload.decode(charset, errors="replace")
                except LookupError:
                    return payload.decode("utf-8", errors="replace")
        return ""

    async def send_response(
        self, channel_id: str, response: str, **kwargs: Any
    ) -> None:
        loop = asyncio.get_running_loop()
        reply_to = kwargs.get("reply_to_message_id")
        references = ""
        if reply_to and reply_to in self._reply_context:
            _, references = self._reply_context[reply_to]
        await loop.run_in_executor(
            None,
            lambda: self._send_sync(channel_id, response, reply_to, references),
        )

    def _send_sync(
        self,
        to_address: str,
        body: str,
        reply_to: str | None,
        references: str,
    ) -> None:
        cfg = self._gmail_config
        if not cfg.address or not cfg.app_password:
            logger.warning("AD-764: cannot send (no address/app_password)")
            return
        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = cfg.address
        msg["To"] = to_address
        msg["Subject"] = "Re: ProbOS"  # AD-764a will preserve original subject
        if reply_to:
            msg["In-Reply-To"] = reply_to
            msg["References"] = references or reply_to
        try:
            ctx = ssl.create_default_context()
            with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30) as smtp:
                smtp.ehlo()
                smtp.starttls(context=ctx)
                smtp.login(cfg.address, cfg.app_password)
                smtp.send_message(msg)
        except (smtplib.SMTPException, OSError) as exc:
            logger.warning("AD-764: SMTP send failed: %s", exc)
