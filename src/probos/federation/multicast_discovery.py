"""AD-479h: MulticastDiscovery — UDP multicast peer announce + listen.

Opt-in (default-False) per the AD-695 + W82 + W88 default-False precedent.
Raw UDP multicast on the local broadcast domain. Cross-LAN mDNS via the
``zeroconf`` package is parked as AD-479j with explicit forcing function.

When a new peer announcement is received, calls
``on_peer_discovered(node_id, bind_address)`` so the caller can register
the peer at runtime via ``FederationBridge.add_peer(peer_config)`` without
a config reload.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import struct
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


def _multicast_available() -> bool:
    """Best-effort check: can we bind a UDP multicast socket?

    Used by the AD-479h tests to skip on CI runners without IPv4 multicast.
    """
    sock: socket.socket | None = None
    try:
        sock = socket.socket(
            socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP,
        )
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        return True
    except OSError:
        return False
    finally:
        if sock is not None:
            sock.close()


class MulticastDiscovery:
    """UDP multicast announce + listen for federation peer discovery."""

    def __init__(
        self,
        *,
        node_id: str,
        bind_address: str,
        multicast_group: str,
        multicast_port: int,
        announce_interval_seconds: float,
        on_peer_discovered: Callable[[str, str], Awaitable[Any]] | None = None,
    ) -> None:
        self._node_id = node_id
        self._bind_address = bind_address
        self._multicast_group = multicast_group
        self._multicast_port = multicast_port
        self._announce_interval = announce_interval_seconds
        self._on_peer_discovered = on_peer_discovered
        self._announce_task: asyncio.Task[None] | None = None
        self._listen_task: asyncio.Task[None] | None = None
        self._send_socket: socket.socket | None = None
        self._recv_socket: socket.socket | None = None
        self._stopped = False
        self._known_peer_ids: set[str] = {node_id}

    async def start(self) -> None:
        """Bind sockets and start the announce + listen loops.

        On bind failure (OSError) the loops are NOT started and the caller
        observes a no-op discovery instance — discovery is best-effort.
        """
        self._stopped = False
        try:
            self._send_socket = socket.socket(
                socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP,
            )
            self._send_socket.setsockopt(
                socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2,
            )
            self._recv_socket = socket.socket(
                socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP,
            )
            self._recv_socket.setsockopt(
                socket.SOL_SOCKET, socket.SO_REUSEADDR, 1,
            )
            self._recv_socket.bind(("", self._multicast_port))
            mreq = struct.pack(
                "4sl",
                socket.inet_aton(self._multicast_group),
                socket.INADDR_ANY,
            )
            self._recv_socket.setsockopt(
                socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq,
            )
            self._recv_socket.setblocking(False)
        except OSError as exc:
            logger.warning(
                "AD-479h: multicast bind failed (%s); discovery disabled", exc,
            )
            if self._send_socket is not None:
                self._send_socket.close()
            if self._recv_socket is not None:
                self._recv_socket.close()
            self._send_socket = None
            self._recv_socket = None
            return

        self._announce_task = asyncio.create_task(
            self._announce_loop(), name="federation-multicast-announce",
        )
        self._listen_task = asyncio.create_task(
            self._listen_loop(), name="federation-multicast-listen",
        )

    async def stop(self) -> None:
        """Cancel loops and close sockets cleanly."""
        self._stopped = True
        for task in (self._announce_task, self._listen_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._announce_task = None
        self._listen_task = None
        if self._send_socket is not None:
            self._send_socket.close()
            self._send_socket = None
        if self._recv_socket is not None:
            self._recv_socket.close()
            self._recv_socket = None

    async def _announce_loop(self) -> None:
        payload = {
            "node_id": self._node_id,
            "bind_address": self._bind_address,
        }
        body = json.dumps(payload).encode("utf-8")
        while not self._stopped:
            try:
                if self._send_socket is not None:
                    self._send_socket.sendto(
                        body, (self._multicast_group, self._multicast_port),
                    )
                await asyncio.sleep(self._announce_interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("Multicast announce error: %s", exc)
                await asyncio.sleep(self._announce_interval)

    async def _listen_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while not self._stopped:
            try:
                if self._recv_socket is None:
                    return
                data = await loop.sock_recv(self._recv_socket, 4096)
                msg = json.loads(data.decode("utf-8"))
                node_id = str(msg.get("node_id", ""))
                bind_address = str(msg.get("bind_address", ""))
                if not node_id or node_id in self._known_peer_ids:
                    continue
                self._known_peer_ids.add(node_id)
                if self._on_peer_discovered is not None:
                    try:
                        await self._on_peer_discovered(node_id, bind_address)
                    except Exception as exc:
                        logger.warning(
                            "AD-479h: on_peer_discovered raised: %s", exc,
                        )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("Multicast listen error: %s", exc)
                await asyncio.sleep(0.5)
