"""AD-764: Gmail adapter tests (v1 IMAP/SMTP scaffolding)."""
from __future__ import annotations

import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml

from probos.channels.base import ChannelMessage
from probos.channels.gmail_adapter import GmailAdapter
from probos.channels.gmail_config import GmailAdapterConfig


class _FakeRuntime:
    pairing_service = None


def _make_adapter(**over):
    cfg = GmailAdapterConfig(
        enabled=True, address="me@gmail.com", app_password="pw", **over
    )
    return GmailAdapter(_FakeRuntime(), cfg)


# ---------------- channel_name + start/stop ----------------


def test_channel_name():
    assert GmailAdapter.channel_name == "gmail"


@pytest.mark.asyncio
async def test_start_without_credentials_does_not_poll():
    cfg = GmailAdapterConfig(enabled=True, address="", app_password="")
    a = GmailAdapter(_FakeRuntime(), cfg)
    await a.start()
    assert a._poll_task is None
    assert a._started is True
    await a.stop()


# ---------------- _extract_body ----------------


def test_extract_body_plain():
    msg = MIMEText("hello world", "plain", "utf-8")
    body = GmailAdapter._extract_body(msg)
    assert body == "hello world"


def test_extract_body_multipart_picks_text_plain():
    root = MIMEMultipart("alternative")
    root.attach(MIMEText("<p>HTML version</p>", "html", "utf-8"))
    root.attach(MIMEText("plain version", "plain", "utf-8"))
    body = GmailAdapter._extract_body(root)
    assert body == "plain version"


def test_extract_body_charset_fallback():
    msg = MIMEText("héllo", "plain", "iso-8859-1")
    body = GmailAdapter._extract_body(msg)
    assert "h" in body


# ---------------- _fetch_one logic via simulated IMAP ----------------


def _build_raw_email(*, sender, subject, body, message_id="<m1@x>"):
    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = sender
    msg["To"] = "me@gmail.com"
    msg["Subject"] = subject
    msg["Message-ID"] = message_id
    return msg.as_bytes()


def test_fetch_one_returns_channel_message():
    a = _make_adapter()
    raw = _build_raw_email(
        sender="Alice <alice@example.com>", subject="Question", body="Can you help?"
    )
    mail = MagicMock()
    mail.uid.return_value = ("OK", [(b"1 (UID 1 BODY[] {123}", raw)])
    msg = a._fetch_one(mail, b"1")
    assert msg is not None
    assert msg.user_id == "alice@example.com"
    assert "Can you help?" in msg.text
    assert "Question" in msg.text
    # BF-803: was `mail.store.assert_called_once()  # mark_seen=True default`.
    # Marking on fetch is what dropped a message whose processing failed, so
    # the fetch now issues one non-mutating FETCH and nothing else;
    # `_poll_loop` acknowledges. RFC 3501 6.4.5 makes the ITEM the load-
    # bearing half: RFC822 and BODY[] both set \Seen implicitly, so UID
    # addressing alone would not have fixed anything.
    assert mail.uid.call_args_list[0].args == ("FETCH", b"1", "(BODY.PEEK[])")
    assert [c.args[0] for c in mail.uid.call_args_list] == ["FETCH"]
    mail.store.assert_not_called()


def test_fetch_one_respects_allow_list():
    a = _make_adapter(allowed_senders=["bob@example.com"])
    raw = _build_raw_email(
        sender="alice@example.com", subject="hi", body="hi"
    )
    mail = MagicMock()
    mail.uid.return_value = ("OK", [(b"1 (UID 1 BODY[] {1}", raw)])
    assert a._fetch_one(mail, b"1") is None


def test_fetch_one_skips_empty_body():
    a = _make_adapter()
    raw = _build_raw_email(sender="alice@example.com", subject="", body="   ")
    mail = MagicMock()
    mail.uid.return_value = ("OK", [(b"1 (UID 1 BODY[] {1}", raw)])
    assert a._fetch_one(mail, b"1") is None


def test_fetch_one_no_mark_seen_when_disabled():
    a = _make_adapter(mark_seen=False)
    raw = _build_raw_email(sender="alice@example.com", subject="hi", body="hi")
    mail = MagicMock()
    mail.uid.return_value = ("OK", [(b"1 (UID 1 BODY[] {1}", raw)])

    assert a._fetch_one(mail, b"1") is not None

    # BF-803: this assertion used to hold only because mark_seen was False. It
    # now holds for every value of mark_seen -- fetching mutates no flag at all.
    mail.store.assert_not_called()
    assert not [c for c in mail.uid.call_args_list if c.args[0] == "STORE"]
    # A MagicMock cannot model the implicit \Seen that RFC 3501 6.4.5 attaches
    # to a non-PEEK body fetch, so the requested ITEM is the only thing that
    # can be asserted here. The double in tests/test_bf803_gmail_ack.py models
    # the flag itself.
    assert mail.uid.call_args_list[0].args[2] == "(BODY.PEEK[])"
    # Control: both probes above must be able to see a flag mutation, or
    # "nothing was flagged" would be indistinguishable from a blind probe.
    mail.store(b"1", "+FLAGS", r"(\Seen)")
    mail.uid("STORE", b"1", "+FLAGS", r"(\Seen)")
    mail.store.assert_called_once()
    assert [c for c in mail.uid.call_args_list if c.args[0] == "STORE"]


def test_fetch_one_records_reply_context_for_threading():
    a = _make_adapter()
    raw = _build_raw_email(
        sender="alice@example.com", subject="q", body="hi", message_id="<abc@x>"
    )
    mail = MagicMock()
    mail.uid.return_value = ("OK", [(b"1 (UID 1 BODY[] {1}", raw)])
    msg = a._fetch_one(mail, b"1")
    assert msg is not None
    assert msg.reply_to_message_id == "<abc@x>"
    assert "<abc@x>" in a._reply_context


def test_fetch_one_handles_imap_failure_status():
    a = _make_adapter()
    mail = MagicMock()
    mail.uid.return_value = ("NO", [])
    assert a._fetch_one(mail, b"1") is None


# ---------------- Doctor ----------------


@pytest.mark.asyncio
async def test_doctor_gmail_ok_when_not_configured(tmp_path):
    from probos.doctor.checks.channel_gmail_check import _ChannelGmailCheck
    from probos.doctor.protocol import CheckOutcome, DoctorContext

    ctx = DoctorContext(config=None, home_dir=tmp_path, data_dir=tmp_path, config_path=None)
    r = await _ChannelGmailCheck().run(ctx)
    assert r.outcome is CheckOutcome.OK


@pytest.mark.asyncio
async def test_doctor_gmail_fail_when_enabled_no_creds(tmp_path):
    from probos.doctor.checks.channel_gmail_check import _ChannelGmailCheck
    from probos.doctor.protocol import CheckOutcome, DoctorContext

    (tmp_path / "channels").mkdir()
    (tmp_path / "channels" / "gmail.yaml").write_text(
        yaml.safe_dump({"enabled": True, "address": "", "app_password": ""}),
        encoding="utf-8",
    )
    ctx = DoctorContext(config=None, home_dir=tmp_path, data_dir=tmp_path, config_path=None)
    r = await _ChannelGmailCheck().run(ctx)
    assert r.outcome is CheckOutcome.FAIL


@pytest.mark.asyncio
async def test_doctor_gmail_ok_when_configured(tmp_path):
    from probos.doctor.checks.channel_gmail_check import _ChannelGmailCheck
    from probos.doctor.protocol import CheckOutcome, DoctorContext

    (tmp_path / "channels").mkdir()
    (tmp_path / "channels" / "gmail.yaml").write_text(
        yaml.safe_dump(
            {"enabled": True, "address": "me@gmail.com", "app_password": "pw"}
        ),
        encoding="utf-8",
    )
    ctx = DoctorContext(config=None, home_dir=tmp_path, data_dir=tmp_path, config_path=None)
    r = await _ChannelGmailCheck().run(ctx)
    assert r.outcome is CheckOutcome.OK
    assert "enabled" in r.message
