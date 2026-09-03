r"""AD-764: Gmail adapter (IMAP/SMTP, v1 scaffolding).

Inbound: polls the configured IMAP mailbox for UNSEEN messages,
normalizes each to a ``ChannelMessage`` (subject + body, sender's
address as user_id), and dispatches via the standard AD-472 +
AD-802a pairing-gate flow.

Outbound: SMTP STARTTLS, reply to the originating thread when a
Message-ID is known.

BF-803 (#1267): inbound delivery is at-least-once. Fetching mutates no
flags at all -- it uses ``BODY.PEEK[]``, because RFC 3501 6.4.5 makes
``RFC822`` and ``BODY[]`` set ``\Seen`` implicitly no matter how the
message is addressed. A message is marked Seen only once it has been
handled AND any reply has actually been accepted by the SMTP server,
addressed by the RFC 3501 UID paired with the UIDVALIDITY that was current
when it was fetched. A message whose processing or delivery fails therefore
stays UNSEEN and is retried on the next poll.

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
from dataclasses import dataclass
from email.mime.text import MIMEText
from typing import Any

from probos.channels.base import ChannelAdapter, ChannelMessage
from probos.channels.gmail_config import GmailAdapterConfig

logger = logging.getLogger(__name__)

#: BF-803: safety valve on the outstanding-acknowledgement set, not a working
#: size. A settled entry is dropped as soon as its flag sticks, so this is only
#: approached by acknowledgements that keep failing -- or by `mark_seen=False`,
#: which never settles any. Past it the oldest is evicted and answered twice.
_ACK_CACHE_MAX = 512


class GmailDeliveryError(RuntimeError):
    """A reply was never accepted by the SMTP server.

    BF-803: `_poll_loop` reads a `send_response` that returns as proof of
    delivery and marks the inbound mail Seen. Swallowing an SMTP failure
    therefore acknowledges a message the sender never got an answer to, which
    is the same silent-drop the deferred acknowledgement exists to prevent.
    """


@dataclass(frozen=True)
class _InboundMail:
    """A fetched message plus the IMAP identity used to acknowledge it.

    BF-803 keeps this module-private and out of ``ChannelMessage``: the
    acknowledgement identity is a Gmail implementation detail, and every
    other adapter shares that type.
    """

    uid: bytes
    uidvalidity: str
    message: ChannelMessage

    @property
    def ack_key(self) -> tuple[str, bytes]:
        """Identity of this mail across sessions.

        RFC 3501 makes a UID unique and non-reused only within one
        UIDVALIDITY, so neither half identifies the mail on its own.
        """
        return (self.uidvalidity, self.uid)

    @property
    def uid_text(self) -> str:
        """The UID rendered for logs; the wire value stays bytes."""
        return self.uid.decode("ascii", errors="replace")


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
        # BF-803: ack_keys of mail that was answered and whose Seen flag is
        # still OUTSTANDING. An insertion-ordered dict used as a bounded set,
        # oldest evicted first. Its job is to make a failed Seen flag retry the
        # flag alone, never the LLM turn or reply. Entries are dropped once the
        # mailbox suppresses re-delivery, so ordinary traffic cannot crowd out
        # a key that is still doing work.
        self._acknowledged: dict[tuple[str, bytes], None] = {}

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
                inbound = await loop.run_in_executor(None, self._fetch_unseen)
                for item in inbound:
                    msg = item.message
                    if item.ack_key in self._acknowledged:
                        # BF-803: this mail was already answered on an earlier
                        # poll and only its Seen flag is outstanding. Retry the
                        # flag -- never a second LLM turn, never a second email.
                        await self._try_acknowledge(loop, item)
                        await asyncio.sleep(0)
                        continue
                    # BF-802 (#1266): handle_message RETURNS the reply; it does
                    # not send it. Gmail discarded that return, so every email
                    # was reasoned about and then answered with silence.
                    #
                    # The try is PER MESSAGE, not around the batch. Adversarial
                    # review found that a batch-wide guard let one failure skip
                    # every remaining message. BF-803 additionally leaves a
                    # failed message UNSEEN, so it is retried rather than lost.
                    try:
                        reply = await self.handle_message(msg)
                        if reply:
                            await self.send_response(
                                msg.channel_id,
                                reply,
                                # ChannelMessage has no `message_id`; Gmail
                                # stores the inbound Message-ID here, and
                                # `_reply_context` is keyed by exactly that.
                                reply_to_message_id=msg.reply_to_message_id,
                            )
                    except Exception:
                        logger.warning(
                            "BF-802: handling or answering the message from "
                            "%s failed; continuing with the rest of the "
                            "batch. BF-803 leaves it unread, so the next poll "
                            "retries it -- a reply the SMTP server never "
                            "accepted counts as a failure here.",
                            msg.channel_id, exc_info=True,
                        )
                    else:
                        self._remember_acknowledged(item)
                        await self._try_acknowledge(loop, item)
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

    async def _try_acknowledge(
        self, loop: asyncio.AbstractEventLoop, item: _InboundMail
    ) -> None:
        """Run `_acknowledge` off-loop, absorb any failure, then settle the entry.

        BF-803: an unacknowledged message is re-fetched and re-flagged on the
        next poll, which is recoverable. Letting the failure reach `_poll_loop`
        would conflate it with a processing failure and cost the rest of the
        batch its BF-802 isolation.

        The entry is dropped only once the MAILBOX stops re-delivering the
        mail. A Seen message can never be fetched again, so keeping its key
        protects nothing -- and evicting a genuinely outstanding key to make
        room for it is what answers the sender twice.
        """
        try:
            acknowledged = await loop.run_in_executor(None, self._acknowledge, item)
        except Exception:
            logger.warning(
                "BF-803: acknowledging UID %s in %s raised unexpectedly; the "
                "mail stays unread and the next poll retries the flag only.",
                item.uid_text, self._gmail_config.mailbox, exc_info=True,
            )
            return
        # `_acknowledge` also returns True with `mark_seen` off, having never
        # touched the mailbox. The mail stays UNSEEN there, so this entry is the
        # only thing between the sender and a second answer, and it stays.
        if acknowledged and self._gmail_config.mark_seen:
            self._acknowledged.pop(item.ack_key, None)

    def _remember_acknowledged(self, item: _InboundMail) -> None:
        """Record that `item` was answered and its Seen flag is outstanding.

        Called BEFORE the acknowledgement is attempted, so a crash or
        cancellation between the two still leaves the next poll retrying the
        flag alone. `_try_acknowledge` drops the entry once the flag sticks;
        the eviction here is the safety valve for the ones that never do.
        """
        self._acknowledged[item.ack_key] = None
        while len(self._acknowledged) > _ACK_CACHE_MAX:
            del self._acknowledged[next(iter(self._acknowledged))]

    def _fetch_unseen(self) -> list[_InboundMail]:
        """Synchronous IMAP fetch; called inside run_in_executor.

        BF-803: UID addressing throughout, and no flag mutation on any path.
        Sequence numbers are session-scoped and renumber on expunge, so they
        cannot survive to the later session the deferred acknowledgement runs
        in.
        """
        cfg = self._gmail_config
        try:
            mail = imaplib.IMAP4_SSL(cfg.imap_host, cfg.imap_port)
            try:
                mail.login(cfg.address, cfg.app_password)
                mail.select(cfg.mailbox)
                uidvalidity = self._read_uidvalidity(mail)
                status, data = mail.uid("SEARCH", None, "UNSEEN")
                if status != "OK" or not data or not data[0]:
                    return []
                uids = data[0].split()
                out: list[_InboundMail] = []
                for uid in uids:
                    msg = self._fetch_one(mail, uid)
                    if msg is not None:
                        out.append(
                            _InboundMail(
                                uid=uid,
                                uidvalidity=uidvalidity,
                                message=msg,
                            )
                        )
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

    @staticmethod
    def _read_uidvalidity(mail: imaplib.IMAP4_SSL) -> str:
        """UIDVALIDITY from the untagged OK response SELECT just produced.

        ``imaplib`` pops that response, so this reads it exactly once per
        SELECT. An empty string means the server sent none.
        """
        _, data = mail.response("UIDVALIDITY")
        if not data or not data[0]:
            return ""
        raw = data[0]
        if isinstance(raw, bytes):
            return raw.decode("ascii", errors="replace").strip()
        return str(raw).strip()

    def _fetch_one(
        self, mail: imaplib.IMAP4_SSL, uid: bytes
    ) -> ChannelMessage | None:
        # RFC 3501 6.4.5: RFC822 is functionally equivalent to BODY[], and
        # retrieving either sets \Seen implicitly. Only the PEEK form leaves
        # the flag for `_poll_loop` to set after the mail has been answered.
        status, data = mail.uid("FETCH", uid, "(BODY.PEEK[])")
        if status != "OK" or not data:
            return None
        # The server answers BODY.PEEK[] with a BODY[] item and may carry UID
        # or FLAGS in the same untagged response, so take the first literal
        # rather than assuming it is the first element.
        raw = next(
            (part[1] for part in data if isinstance(part, tuple) and len(part) > 1),
            None,
        )
        if not isinstance(raw, bytes):
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
        return ChannelMessage(
            text=text.strip(),
            channel_id=sender,  # thread by sender
            user_id=sender,
            user_display_name=email.utils.parseaddr(parsed.get("From", ""))[0],
            reply_to_message_id=message_id or None,
        )

    def _acknowledge(self, item: _InboundMail) -> bool:
        """Mark one already-answered message Seen; runs inside an executor.

        Returns True when the mailbox reflects the acknowledgement, or when
        `mark_seen` is off and there is nothing to reflect. Every failure is
        logged and reported as False rather than raised: the mail stays
        unread, and the acknowledged-set makes the next poll retry the flag
        without re-answering the sender.

        BF-803: those two True cases are not interchangeable to the caller.
        Only the first stops the mail being fetched again, so only the first
        lets `_try_acknowledge` drop the entry.
        """
        cfg = self._gmail_config
        if not cfg.mark_seen:
            return True
        try:
            mail = imaplib.IMAP4_SSL(cfg.imap_host, cfg.imap_port)
        except (imaplib.IMAP4.error, OSError) as exc:
            logger.warning(
                "BF-803: could not open an IMAP session to acknowledge UID %s "
                "in %s (%s); the mail stays unread and the next poll retries "
                "the flag only.",
                item.uid_text, cfg.mailbox, exc,
            )
            return False
        try:
            mail.login(cfg.address, cfg.app_password)
            status, _ = mail.select(cfg.mailbox)
            if status != "OK":
                logger.warning(
                    "BF-803: re-selecting %s to acknowledge UID %s returned "
                    "%s; the mail stays unread and the next poll retries the "
                    "flag only.",
                    cfg.mailbox, item.uid_text, status,
                )
                return False
            current = self._read_uidvalidity(mail)
            if current != item.uidvalidity:
                logger.warning(
                    "BF-803: UIDVALIDITY of %s changed from %s to %s, so UID "
                    "%s may now address a different message; refusing to mark "
                    "it Seen. The mail stays unread and will be delivered "
                    "again under the new UIDVALIDITY.",
                    cfg.mailbox,
                    item.uidvalidity or "<absent>",
                    current or "<absent>",
                    item.uid_text,
                )
                return False
            status, _ = mail.uid("STORE", item.uid, "+FLAGS", r"(\Seen)")
            if status != "OK":
                logger.warning(
                    "BF-803: UID STORE for %s in %s returned %s; the mail "
                    "stays unread and the next poll retries the flag only.",
                    item.uid_text, cfg.mailbox, status,
                )
                return False
            return True
        except (imaplib.IMAP4.error, OSError) as exc:
            logger.warning(
                "BF-803: acknowledging UID %s in %s failed (%s); the mail "
                "stays unread and the next poll retries the flag only.",
                item.uid_text, cfg.mailbox, exc,
            )
            return False
        finally:
            try:
                mail.close()
            except Exception:
                pass
            try:
                mail.logout()
            except Exception:
                pass

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
        """Deliver one reply by SMTP.

        Raises:
            GmailDeliveryError: the server never accepted the message. BF-803
                requires this to surface, because returning normally is what
                `_poll_loop` treats as permission to acknowledge the mail.
        """
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
        """Send one reply synchronously; called inside run_in_executor.

        Raises:
            GmailDeliveryError: the server never accepted the message.

        A failure AFTER acceptance -- a refused QUIT, a connection dropped
        during teardown -- is logged and tolerated instead: the reply was
        delivered, so raising would leave the mail unread and send it twice.
        """
        cfg = self._gmail_config
        if not cfg.address or not cfg.app_password:
            raise GmailDeliveryError(
                f"cannot send to {to_address}: the Gmail adapter has no "
                "address / app_password configured"
            )
        msg = MIMEText(body, "plain", "utf-8")
        msg["From"] = cfg.address
        msg["To"] = to_address
        msg["Subject"] = "Re: ProbOS"  # AD-764a will preserve original subject
        if reply_to:
            msg["In-Reply-To"] = reply_to
            msg["References"] = references or reply_to
        accepted = False
        try:
            ctx = ssl.create_default_context()
            with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30) as smtp:
                smtp.ehlo()
                smtp.starttls(context=ctx)
                smtp.login(cfg.address, cfg.app_password)
                smtp.send_message(msg)
                accepted = True
        except (smtplib.SMTPException, OSError) as exc:
            if not accepted:
                logger.warning(
                    "AD-764/BF-803: SMTP delivery to %s failed (%s); the "
                    "inbound mail stays unread and the next poll retries it.",
                    to_address, exc,
                )
                raise GmailDeliveryError(
                    f"SMTP delivery to {to_address} failed: {exc}"
                ) from exc
            logger.warning(
                "BF-803: the SMTP session to %s failed while closing (%s) "
                "after the server had accepted the message; treating the "
                "reply as delivered rather than sending it a second time.",
                to_address, exc,
            )
