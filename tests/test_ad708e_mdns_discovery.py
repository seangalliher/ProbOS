"""AD-708e: LAN mDNS service advertiser tests.

BF-287 discipline: a real ``_FakeAsyncZeroconf`` (not MagicMock) at the
zeroconf boundary, with ASYNC methods matching the real ``AsyncZeroconf``
contract — a sync fake would hide a missing ``await`` in production.
"""

from __future__ import annotations

import inspect
import logging
import socket

import probos.__main__
from probos.config import DiscoveryConfig
from probos.discovery import (
    NoOpAdvertiser,
    ZeroconfAdvertiser,
    build_advertiser,
)
from probos.discovery import advertiser as advertiser_mod

SECRET_SENTINEL = "SUPERSECRET_TOKEN_DO_NOT_LEAK"


class _FakeAsyncZeroconf:
    """Records register/unregister/close calls; async to match the real lib."""

    def __init__(self, raise_on_register: bool = False) -> None:
        self.registered: list = []
        self.unregister_count = 0
        self.close_count = 0
        self._raise_on_register = raise_on_register

    async def async_register_service(self, info) -> None:
        if self._raise_on_register:
            raise RuntimeError("simulated mDNS register failure")
        self.registered.append(info)

    async def async_unregister_service(self, info) -> None:
        self.unregister_count += 1

    async def async_close(self) -> None:
        self.close_count += 1


# --- factory (build_advertiser) ------------------------------------------


def test_factory_flag_off_returns_noop():
    cfg = DiscoveryConfig(enabled=False)
    adv = build_advertiser(cfg, host="0.0.0.0", port=18900)
    assert isinstance(adv, NoOpAdvertiser)


def test_factory_lib_absent_returns_noop(monkeypatch):
    cfg = DiscoveryConfig(enabled=True)
    monkeypatch.setattr(advertiser_mod, "_zeroconf_available", lambda: False)
    adv = build_advertiser(cfg, host="0.0.0.0", port=18900)
    assert isinstance(adv, NoOpAdvertiser)


def test_factory_flag_on_and_lib_present_returns_zeroconf(monkeypatch):
    cfg = DiscoveryConfig(enabled=True)
    monkeypatch.setattr(advertiser_mod, "_zeroconf_available", lambda: True)
    adv = build_advertiser(cfg, host="192.168.1.50", port=18900)
    assert isinstance(adv, ZeroconfAdvertiser)


# --- NoOpAdvertiser -------------------------------------------------------


async def test_noop_start_false_stop_idempotent():
    adv = NoOpAdvertiser()
    assert await adv.start() is False
    await adv.stop()
    await adv.stop()  # idempotent, no raise


# --- ZeroconfAdvertiser ---------------------------------------------------


async def test_zeroconf_registers_and_unregisters_once():
    cfg = DiscoveryConfig(enabled=True)
    fake = _FakeAsyncZeroconf()
    adv = ZeroconfAdvertiser(cfg, host="192.168.1.50", port=18900, zc_factory=lambda: fake)

    assert await adv.start() is True
    assert len(fake.registered) == 1

    await adv.stop()
    assert fake.unregister_count == 1
    assert fake.close_count == 1


async def test_loopback_host_skips(caplog):
    cfg = DiscoveryConfig(enabled=True)
    fake = _FakeAsyncZeroconf()
    adv = ZeroconfAdvertiser(cfg, host="127.0.0.1", port=18900, zc_factory=lambda: fake)

    with caplog.at_level(logging.WARNING, logger="probos.discovery.advertiser"):
        result = await adv.start()

    assert result is False
    assert len(fake.registered) == 0
    assert "loopback" in caplog.text.lower()


async def test_bind_all_resolves_lan_ip(monkeypatch):
    cfg = DiscoveryConfig(enabled=True)
    fake = _FakeAsyncZeroconf()
    monkeypatch.setattr(advertiser_mod, "resolve_lan_ipv4", lambda: "192.168.1.50")
    adv = ZeroconfAdvertiser(cfg, host="0.0.0.0", port=18900, zc_factory=lambda: fake)

    assert await adv.start() is True
    assert len(fake.registered) == 1
    recorded_addr = socket.inet_ntoa(fake.registered[0].addresses[0])
    assert recorded_addr == "192.168.1.50"


async def test_service_info_excludes_secrets():
    cfg = DiscoveryConfig(enabled=True, instance_name="ProbOS")
    fake = _FakeAsyncZeroconf()
    adv = ZeroconfAdvertiser(cfg, host="192.168.1.50", port=18900, zc_factory=lambda: fake)

    assert await adv.start() is True
    info = fake.registered[0]

    haystack = " ".join(
        [
            info.name,
            info.server,
            repr(info.properties),
            repr(info.addresses),
            str(info.port),
        ]
    )
    # The advertised record must never carry a secret-shaped string...
    assert SECRET_SENTINEL not in haystack
    # ...but it must carry the expected non-sensitive fields.
    assert "ProbOS" in info.name
    assert b"path" in info.properties


async def test_start_swallows_zeroconf_error():
    cfg = DiscoveryConfig(enabled=True)
    fake = _FakeAsyncZeroconf(raise_on_register=True)
    adv = ZeroconfAdvertiser(cfg, host="192.168.1.50", port=18900, zc_factory=lambda: fake)

    # A register failure must honest-degrade to False, never propagate.
    assert await adv.start() is False


# --- _serve wiring (source-level; no server boot) -------------------------


def test_serve_wires_advertiser():
    src = inspect.getsource(probos.__main__._serve)
    assert "build_advertiser(" in src
    assert ".stop()" in src
