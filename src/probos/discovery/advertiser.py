"""AD-708e: LAN mDNS service advertiser for PADD discovery (#484).

Default-OFF, opt-in. The ``zeroconf`` import is LAZY (inside
``ZeroconfAdvertiser.start``) so a default install with the optional
``discovery`` extra absent imports this module fine and the server boots
normally. A mDNS failure NEVER blocks the server (Tier-2 honest-degrade).

SECURITY: the advertised ServiceInfo carries only non-sensitive fields —
service type, instance name, LAN IPv4, port, and a static TXT path hint.
Never a token, identity, filesystem path, or username.
"""

from __future__ import annotations

import importlib.util
import logging
import socket
from typing import TYPE_CHECKING, Any, Callable

from probos.discovery.protocol import ServiceAdvertiser

if TYPE_CHECKING:
    from probos.config import DiscoveryConfig

logger = logging.getLogger(__name__)

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_BIND_ALL_HOSTS = frozenset({"0.0.0.0", ""})


class NoOpAdvertiser:
    """A :class:`ServiceAdvertiser` that advertises nothing.

    Returned by :func:`build_advertiser` when discovery is disabled, the
    config is absent, or the optional ``zeroconf`` lib is not installed.
    """

    async def start(self) -> bool:
        return False

    async def stop(self) -> None:
        return None


def resolve_lan_ipv4() -> str | None:
    """Return the host's primary LAN IPv4 address, or ``None`` on failure.

    Uses the UDP-connect trick: opening a datagram socket and "connecting"
    to a public address makes the OS pick the egress interface without
    sending any packet. Honest-degrade to ``None`` on any socket error.
    """
    sock: socket.socket | None = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        return str(sock.getsockname()[0])
    except OSError as exc:
        logger.warning(
            "AD-708e: could not resolve LAN IPv4 (%s); mDNS advertisement skipped",
            exc,
        )
        return None
    finally:
        if sock is not None:
            sock.close()


def _resolve_advertise_address(cfg: DiscoveryConfig, host: str) -> str | None:
    """Compute the IPv4 address to advertise, or ``None`` to skip.

    - specific non-loopback host (a real IP/hostname) -> advertise as-is.
    - bind-all (``"0.0.0.0"`` / ``""``) -> resolve the LAN IPv4 (``None`` -> skip).
    - loopback (``"127.0.0.1"`` / ``"localhost"`` / ``"::1"``) -> warn + skip
      (advertising an unreachable loopback A record is worse than nothing).
    """
    if host in _LOOPBACK_HOSTS:
        logger.warning(
            "AD-708e: server bound to loopback (%s); PADD on LAN cannot connect; "
            "run `probos serve --host 0.0.0.0` to enable LAN discovery",
            host,
        )
        return None
    if host in _BIND_ALL_HOSTS:
        addr = resolve_lan_ipv4()
        if addr is None:
            logger.warning(
                "AD-708e: bind-all host (%s) but no LAN IPv4 resolved; "
                "mDNS advertisement skipped",
                host or "<empty>",
            )
        return addr
    return host


class ZeroconfAdvertiser:
    """mDNS service advertiser backed by python-zeroconf (optional extra).

    ``zc_factory`` is a DI seam: tests inject a fake ``AsyncZeroconf``;
    ``None`` (production) lazily builds the real one inside :meth:`start`.
    """

    def __init__(
        self,
        cfg: DiscoveryConfig,
        host: str,
        port: int,
        *,
        zc_factory: Callable[[], Any] | None = None,
    ) -> None:
        self._cfg = cfg
        self._host = host
        self._port = port
        self._zc_factory = zc_factory
        self._zc: Any | None = None
        self._info: Any | None = None

    async def start(self) -> bool:
        addr = _resolve_advertise_address(self._cfg, self._host)
        if addr is None:
            return False
        try:
            if self._zc_factory is not None:
                zc = self._zc_factory()
            else:
                # Lazy import: the optional `discovery` extra. Never at module top.
                from zeroconf.asyncio import AsyncZeroconf

                zc = AsyncZeroconf()
            self._zc = zc

            from zeroconf import ServiceInfo  # lazy: optional extra

            info = ServiceInfo(
                self._cfg.service_type,
                f"{self._cfg.instance_name}.{self._cfg.service_type}",
                addresses=[socket.inet_aton(addr)],
                port=self._port,
                properties={"path": self._cfg.txt_path},
                server=f"{self._cfg.hostname}.local.",
            )
            self._info = info
            await zc.async_register_service(info)
            logger.info(
                "AD-708e: advertising mDNS service %s at %s:%d as %s.local",
                self._cfg.service_type,
                addr,
                self._port,
                self._cfg.hostname,
            )
            return True
        except Exception as exc:  # noqa: BLE001 - Tier-2: mDNS never blocks the server
            logger.warning(
                "AD-708e: mDNS advertisement failed (%s); continuing without LAN discovery",
                exc,
            )
            await self.stop()
            return False

    async def stop(self) -> None:
        zc = self._zc
        info = self._info
        try:
            if zc is not None and info is not None:
                await zc.async_unregister_service(info)
            if zc is not None:
                await zc.async_close()
        except Exception as exc:  # noqa: BLE001 - idempotent teardown, never raises
            logger.warning("AD-708e: error during mDNS teardown (%s); ignoring", exc)
        finally:
            self._zc = None
            self._info = None


def _zeroconf_available() -> bool:
    """True iff the optional ``zeroconf`` lib is importable."""
    return importlib.util.find_spec("zeroconf") is not None


def build_advertiser(cfg: DiscoveryConfig | None, host: str, port: int) -> ServiceAdvertiser:
    """Return a :class:`ServiceAdvertiser` for the given config and bind target.

    Returns a :class:`NoOpAdvertiser` when discovery is disabled, the config
    is absent, or the optional ``zeroconf`` lib is not installed; otherwise a
    :class:`ZeroconfAdvertiser`.
    """
    if cfg is None or not cfg.enabled or not _zeroconf_available():
        return NoOpAdvertiser()
    return ZeroconfAdvertiser(cfg, host, port)
