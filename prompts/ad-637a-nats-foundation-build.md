# AD-637a: NATS Integration Layer — Foundation

**Status:** Ready for builder
**Scope:** Add NATS client abstraction, config, startup/shutdown, health monitoring. No migration of existing dispatch patterns — that's AD-637b/c/d.
**Parent design:** `prompts/ad-637-nats-event-bus.md`

---

## Overview

Create the NATS foundation layer that all subsequent migration sub-ADs (637b–637f) depend on. This AD is purely additive — no existing code changes except config and startup/shutdown wiring. When complete, ProbOS can connect to a NATS server, publish/subscribe on subjects, use JetStream for durable messaging, and gracefully degrade if NATS is unavailable.

---

## Prior Work to Absorb

- **`prompts/ad-637-nats-event-bus.md`** — Master design document. Subject hierarchy, sub-AD decomposition, engineering principles. Read sections on AD-637a and Subject Hierarchy Design.
- **`src/probos/protocols.py`** — Protocol pattern for interface segregation. `EventEmitterMixin`, `EpisodicMemoryProtocol`, `TrustNetworkProtocol`, etc. Follow this pattern for `NATSBusProtocol`.
- **`src/probos/startup/infrastructure.py`** — Phase 1 startup pattern. `boot_infrastructure()` function signature, logging convention, `InfrastructureResult` return type. Note: `identity_registry.start()` here has NO `instance_id` — ship DID is unknown at Phase 1.
- **`src/probos/startup/shutdown.py`** — Shutdown sequence. NATS drain/close goes after all publishers have stopped (after pools stop, after dream consolidation) but before working memory store and event log close. Anchor: after the `# Stop mesh and consensus services` block, before `# AD-573: Stop working memory store`.
- **`src/probos/startup/results.py`** — `TypedDict` result types for startup phases.
- **`src/probos/startup/communication.py`** — Phase 4 startup. Ship commissioning happens here (`identity_registry.start(instance_id=...)`), not in Phase 1. NATS subject prefix must be updated after ship DID is known.
- **`src/probos/config.py`** — Pydantic `BaseModel` config pattern. `SystemConfig` class with all config fields. Follow existing naming convention.
- **`src/probos/__main__.py`** — `_ensure_ollama()` pattern for pre-flight connectivity check. Follow this pattern for `_check_nats()`.
- **`config/system.yaml`** — Configuration file structure.
- **`src/probos/runtime.py`** — `_emit_event()` and `add_event_listener()` are the current dispatch mechanisms that AD-637d will eventually migrate — understand but don't modify.

---

## Changes

### 1. Add `nats-py` dependency

**File:** `pyproject.toml`

Add to `dependencies` array:
```
"nats-py>=2.9",
```

### 2. Create `NatsConfig` in config

**File:** `src/probos/config.py`

Add config class before `SystemConfig` (after `ChainTuningConfig`):

```python
class NatsConfig(BaseModel):
    """NATS event bus configuration (AD-637)."""

    enabled: bool = False
    url: str = "nats://localhost:4222"
    connect_timeout_seconds: float = 5.0
    max_reconnect_attempts: int = 60
    reconnect_time_wait_seconds: float = 2.0
    drain_timeout_seconds: float = 5.0

    # JetStream
    jetstream_enabled: bool = True
    jetstream_domain: str | None = None  # For leaf node isolation

    # Subject prefix — derived from ship DID at runtime, fallback for local
    subject_prefix: str = "probos.local"
```

Add to `SystemConfig`:
```python
nats: NatsConfig = NatsConfig()  # AD-637
```

### 3. Add NATS section to system.yaml

**File:** `config/system.yaml`

Add after the `sub_task:` section (before `qualification:`):

```yaml
# --- NATS Event Bus (AD-637) ---
nats:
  enabled: true
  url: "nats://localhost:4222"
  connect_timeout_seconds: 5.0
  max_reconnect_attempts: 60
  reconnect_time_wait_seconds: 2.0
  drain_timeout_seconds: 5.0
  jetstream_enabled: true
  subject_prefix: "probos.local"
```

### 4. Create `NATSBusProtocol` and `NATSBus`

**File (new):** `src/probos/mesh/nats_bus.py`

This is the core abstraction. Protocol-based so tests can mock.

```python
"""AD-637a: NATS event bus integration layer.

Provides a unified publish/subscribe/request-reply abstraction over NATS
with JetStream support for durable messaging.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# Type alias for subscription message callbacks
MessageCallback = Callable[["NATSMessage"], Awaitable[None]]


class NATSMessage:
    """Wrapper around a NATS message for consumer-side processing."""

    __slots__ = ("subject", "data", "reply", "headers", "_msg")

    def __init__(
        self,
        subject: str,
        data: dict[str, Any],
        reply: str = "",
        headers: dict[str, str] | None = None,
        _msg: Any = None,
    ) -> None:
        self.subject = subject
        self.data = data
        self.reply = reply
        self.headers = headers or {}
        self._msg = _msg  # Raw nats.aio.msg.Msg for ack/nak

    async def ack(self) -> None:
        """Acknowledge JetStream message."""
        if self._msg and hasattr(self._msg, "ack"):
            await self._msg.ack()

    async def nak(self, delay: float | None = None) -> None:
        """Negative-acknowledge JetStream message (redelivery)."""
        if self._msg and hasattr(self._msg, "nak"):
            await self._msg.nak(delay=delay)

    async def respond(self, data: dict[str, Any]) -> None:
        """Reply to a request-reply message."""
        if self._msg and hasattr(self._msg, "respond"):
            payload = json.dumps(data).encode()
            await self._msg.respond(payload)


# NOTE: No NATSBusProtocol defined here. The consumer-facing protocol lives in
# protocols.py (narrow interface for service consumers). NATSBus and MockNATSBus
# both structurally satisfy it — no separate "management protocol" needed.


class NATSBus:

```python
class NATSBus:
    """NATS event bus — unified messaging for ProbOS (AD-637).

    Wraps nats-py client with:
    - Automatic reconnection with backoff
    - JetStream stream management
    - Graceful drain on shutdown
    - Fallback-safe: callers check .connected before assuming delivery
    """

    def __init__(
        self,
        url: str = "nats://localhost:4222",
        connect_timeout: float = 5.0,
        max_reconnect_attempts: int = 60,
        reconnect_time_wait: float = 2.0,
        drain_timeout: float = 5.0,
        subject_prefix: str = "probos.local",
        jetstream_enabled: bool = True,
    ) -> None:
        self._url = url
        self._connect_timeout = connect_timeout
        self._max_reconnect = max_reconnect_attempts
        self._reconnect_wait = reconnect_time_wait
        self._drain_timeout = drain_timeout
        self._subject_prefix = subject_prefix
        self._jetstream_enabled = jetstream_enabled
        self._nc: Any = None  # nats.NATS client
        self._js: Any = None  # JetStream context
        self._subscriptions: list[Any] = []
        self._connected = False
        self._started = False

    @property
    def connected(self) -> bool:
        """True when NATS client is connected and not draining."""
        return self._connected and self._nc is not None and self._nc.is_connected

    @property
    def subject_prefix(self) -> str:
        return self._subject_prefix

    def set_subject_prefix(self, prefix: str) -> None:
        """Update subject prefix (e.g., after ship DID is known)."""
        self._subject_prefix = prefix

    def _full_subject(self, subject: str) -> str:
        """Prepend subject prefix if not already present."""
        if subject.startswith(self._subject_prefix + "."):
            return subject
        return f"{self._subject_prefix}.{subject}"

    async def start(self) -> None:
        """Connect to NATS server."""
        if self._started:
            return

        import nats  # Lazy import — only needed when enabled

        async def _disconnected_cb():
            self._connected = False
            logger.warning("NATS disconnected")

        async def _reconnected_cb():
            self._connected = True
            logger.info("NATS reconnected to %s", self._nc.connected_url)

        async def _error_cb(e):
            logger.error("NATS error: %s", e)

        async def _closed_cb():
            self._connected = False
            logger.info("NATS connection closed")

        try:
            self._nc = await nats.connect(
                servers=[self._url],
                connect_timeout=self._connect_timeout,
                max_reconnect_attempts=self._max_reconnect,
                reconnect_time_wait=self._reconnect_wait,
                disconnected_cb=_disconnected_cb,
                reconnected_cb=_reconnected_cb,
                error_cb=_error_cb,
                closed_cb=_closed_cb,
            )
            self._connected = True
            self._started = True

            if self._jetstream_enabled:
                self._js = self._nc.jetstream()

            logger.info(
                "NATS connected to %s (JetStream=%s)",
                self._nc.connected_url,
                "enabled" if self._js else "disabled",
            )
        except Exception as e:
            logger.error("NATS connection failed: %s", e)
            self._nc = None
            self._connected = False
            # Don't raise — NATS is optional, system degrades gracefully

    async def stop(self) -> None:
        """Drain subscriptions and close connection."""
        if not self._nc:
            return

        try:
            # Drain flushes pending messages before closing
            await asyncio.wait_for(
                self._nc.drain(),
                timeout=self._drain_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("NATS drain timed out after %.1fs", self._drain_timeout)
        except Exception as e:
            logger.warning("NATS drain error: %s", e)

        # Force close if drain didn't complete
        if self._nc and not self._nc.is_closed:
            await self._nc.close()

        self._nc = None
        self._js = None
        self._connected = False
        self._started = False
        self._subscriptions.clear()
        logger.info("NATS connection closed")

    async def publish(
        self,
        subject: str,
        data: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        """Publish a message on a core NATS subject (fire-and-forget)."""
        if not self.connected:
            return

        full_subject = self._full_subject(subject)
        payload = json.dumps(data).encode()
        await self._nc.publish(full_subject, payload, headers=headers)

    async def subscribe(
        self,
        subject: str,
        callback: MessageCallback,
        queue: str = "",
    ) -> Any:
        """Subscribe to a core NATS subject."""
        if not self.connected:
            return None

        full_subject = self._full_subject(subject)

        async def _handler(msg):
            try:
                data = json.loads(msg.data) if msg.data else {}
            except (json.JSONDecodeError, UnicodeDecodeError):
                logger.debug("NATS: invalid JSON on %s", msg.subject)
                return
            wrapped = NATSMessage(
                subject=msg.subject,
                data=data,
                reply=msg.reply or "",
                headers=dict(msg.headers) if msg.headers else {},
                _msg=msg,
            )
            try:
                await callback(wrapped)
            except Exception:
                logger.error(
                    "NATS subscriber error on %s", msg.subject, exc_info=True
                )

        sub = await self._nc.subscribe(full_subject, queue=queue, cb=_handler)
        self._subscriptions.append(sub)
        return sub

    async def request(
        self,
        subject: str,
        data: dict[str, Any],
        timeout: float = 5.0,
    ) -> NATSMessage | None:
        """Send a request and wait for a reply (request/reply pattern)."""
        if not self.connected:
            return None

        full_subject = self._full_subject(subject)
        payload = json.dumps(data).encode()

        try:
            response = await self._nc.request(
                full_subject, payload, timeout=timeout
            )
            resp_data = json.loads(response.data) if response.data else {}
            return NATSMessage(
                subject=response.subject,
                data=resp_data,
                reply=response.reply or "",
                _msg=response,
            )
        except Exception as e:
            logger.debug("NATS request to %s failed: %s", full_subject, e)
            return None

    async def js_publish(
        self,
        subject: str,
        data: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        """Publish to a JetStream subject (durable, at-least-once)."""
        if not self._js:
            # Fallback to core NATS if JetStream not available
            await self.publish(subject, data, headers=headers)
            return

        full_subject = self._full_subject(subject)
        payload = json.dumps(data).encode()

        try:
            await self._js.publish(full_subject, payload, headers=headers)
        except Exception as e:
            logger.error("JetStream publish to %s failed: %s", full_subject, e)

    async def js_subscribe(
        self,
        subject: str,
        callback: MessageCallback,
        durable: str | None = None,
        stream: str | None = None,
    ) -> Any:
        """Subscribe to a JetStream subject (durable consumer)."""
        if not self._js:
            # Fallback to core NATS subscription
            return await self.subscribe(subject, callback)

        full_subject = self._full_subject(subject)

        async def _handler(msg):
            try:
                data = json.loads(msg.data) if msg.data else {}
            except (json.JSONDecodeError, UnicodeDecodeError):
                logger.debug("JetStream: invalid JSON on %s", msg.subject)
                await msg.nak()
                return
            wrapped = NATSMessage(
                subject=msg.subject,
                data=data,
                reply=msg.reply or "",
                headers=dict(msg.headers) if msg.headers else {},
                _msg=msg,
            )
            try:
                await callback(wrapped)
                await msg.ack()
            except Exception:
                logger.error(
                    "JetStream subscriber error on %s",
                    msg.subject,
                    exc_info=True,
                )
                await msg.nak()

        try:
            sub = await self._js.subscribe(
                full_subject,
                durable=durable,
                stream=stream,
                cb=_handler,
            )
            self._subscriptions.append(sub)
            return sub
        except Exception as e:
            logger.error("JetStream subscribe to %s failed: %s", full_subject, e)
            return None

    async def ensure_stream(
        self,
        name: str,
        subjects: list[str],
        max_msgs: int = -1,
        max_age: float = 0,
    ) -> None:
        """Create or update a JetStream stream."""
        if not self._js:
            return

        from nats.js.api import StreamConfig

        full_subjects = [self._full_subject(s) for s in subjects]

        try:
            config = StreamConfig(
                name=name,
                subjects=full_subjects,
                max_msgs=max_msgs,
                max_age=max_age,
            )
            await self._js.add_stream(config)
            logger.info("JetStream stream '%s' ensured: %s", name, full_subjects)
        except Exception as e:
            # add_stream is idempotent — if stream exists with same config,
            # this succeeds. Only errors on config conflicts or server issues.
            logger.error("Failed to ensure stream '%s': %s", name, e)

    # NOTE: No _ensure_default_streams() on startup. Streams are created lazily
    # by callers via ensure_stream() when they need durable delivery. This avoids
    # the ship-DID timing problem: streams created in Phase 1 would use
    # "probos.local.*" subjects, but the real DID prefix isn't known until Phase 4.
    # Lazy creation is also more cloud-native — commercial overlay provisions
    # streams via IaC, not application code.

    def health(self) -> dict[str, Any]:
        """Return NATS health status for VitalsMonitor integration."""
        if not self._nc:
            return {
                "connected": False,
                "status": "not_started",
                "url": self._url,
            }
        return {
            "connected": self.connected,
            "status": "connected" if self.connected else "disconnected",
            "url": self._nc.connected_url or self._url,
            "reconnects": getattr(self._nc, "reconnected_count", 0),
            "jetstream": self._js is not None,
            "subscriptions": len(self._subscriptions),
        }
```

### 5. Create `MockNATSBus` for testing

Place this at the bottom of `src/probos/mesh/nats_bus.py` (same file):

```python
class MockNATSBus:
    """In-memory mock for testing without a NATS server.

    Implements NATSBusProtocol with local dispatch.
    Messages published are immediately delivered to matching subscribers.
    """

    def __init__(self, subject_prefix: str = "probos.test") -> None:
        self._subject_prefix = subject_prefix
        self._connected = False
        self._started = False
        self._subs: dict[str, list[MessageCallback]] = {}
        self._queue_subs: dict[str, dict[str, list[MessageCallback]]] = {}
        self._streams: dict[str, dict[str, Any]] = {}
        self.published: list[tuple[str, dict[str, Any]]] = []  # Test inspection

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def subject_prefix(self) -> str:
        return self._subject_prefix

    def set_subject_prefix(self, prefix: str) -> None:
        self._subject_prefix = prefix

    def _full_subject(self, subject: str) -> str:
        if subject.startswith(self._subject_prefix + "."):
            return subject
        return f"{self._subject_prefix}.{subject}"

    async def start(self) -> None:
        self._connected = True
        self._started = True

    async def stop(self) -> None:
        self._connected = False
        self._started = False
        self._subs.clear()
        self._queue_subs.clear()

    def _match_subject(self, pattern: str, subject: str) -> bool:
        """NATS subject matching: * = one token, > = one or more tokens."""
        pat_parts = pattern.split(".")
        sub_parts = subject.split(".")
        for i, pat in enumerate(pat_parts):
            if pat == ">":
                return True  # > matches remainder
            if i >= len(sub_parts):
                return False
            if pat != "*" and pat != sub_parts[i]:
                return False
        return len(pat_parts) == len(sub_parts)

    async def publish(
        self,
        subject: str,
        data: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        if not self._connected:
            return

        full = self._full_subject(subject)
        self.published.append((full, data))

        msg = NATSMessage(subject=full, data=data, headers=headers or {})
        for pattern, cbs in self._subs.items():
            if self._match_subject(pattern, full):
                for cb in cbs:
                    await cb(msg)

    async def subscribe(
        self,
        subject: str,
        callback: MessageCallback,
        queue: str = "",
    ) -> str:
        full = self._full_subject(subject)
        if full not in self._subs:
            self._subs[full] = []
        self._subs[full].append(callback)
        return full  # subscription handle

    async def request(
        self,
        subject: str,
        data: dict[str, Any],
        timeout: float = 5.0,
    ) -> NATSMessage | None:
        if not self._connected:
            return None

        full = self._full_subject(subject)
        self.published.append((full, data))

        # Find subscriber and invoke, capture respond() call
        reply_data: dict[str, Any] = {}

        class MockReplyMsg:
            async def respond(self, payload: bytes) -> None:
                reply_data.update(json.loads(payload))

        msg = NATSMessage(
            subject=full,
            data=data,
            reply=f"_INBOX.mock.{id(data)}",
            _msg=MockReplyMsg(),
        )

        for pattern, cbs in self._subs.items():
            if self._match_subject(pattern, full) and cbs:
                await cbs[0](msg)
                if reply_data:
                    return NATSMessage(
                        subject=msg.reply, data=reply_data
                    )
        return None

    async def js_publish(
        self,
        subject: str,
        data: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> None:
        await self.publish(subject, data, headers=headers)

    async def js_subscribe(
        self,
        subject: str,
        callback: MessageCallback,
        durable: str | None = None,
        stream: str | None = None,
    ) -> str:
        return await self.subscribe(subject, callback)

    async def ensure_stream(
        self,
        name: str,
        subjects: list[str],
        max_msgs: int = -1,
        max_age: float = 0,
    ) -> None:
        self._streams[name] = {
            "subjects": subjects,
            "max_msgs": max_msgs,
            "max_age": max_age,
        }

    def health(self) -> dict[str, Any]:
        return {
            "connected": self._connected,
            "status": "mock",
            "url": "mock://localhost",
            "reconnects": 0,
            "jetstream": True,
            "subscriptions": sum(len(cbs) for cbs in self._subs.values()),
        }
```

### 6. Add `NATSBusProtocol` to protocols.py

**File:** `src/probos/protocols.py`

At the end of the file, add:

```python
@runtime_checkable
class NATSBusProtocol(Protocol):
    """What services need from the NATS event bus (AD-637)."""

    @property
    def connected(self) -> bool: ...
    @property
    def subject_prefix(self) -> str: ...
    async def publish(self, subject: str, data: dict[str, Any], headers: dict[str, str] | None = None) -> None: ...
    async def subscribe(self, subject: str, callback: Any, queue: str = "") -> Any: ...
    async def request(self, subject: str, data: dict[str, Any], timeout: float = 5.0) -> Any: ...
    async def js_publish(self, subject: str, data: dict[str, Any], headers: dict[str, str] | None = None) -> None: ...
    async def js_subscribe(self, subject: str, callback: Any, durable: str | None = None, stream: str | None = None) -> Any: ...
    def health(self) -> dict[str, Any]: ...
```

Note: The protocol in `protocols.py` is a narrow consumer-side interface. The full protocol with `start()/stop()/ensure_stream()` lives in `nats_bus.py`. This follows the existing pattern where `protocols.py` defines what *consumers* need, not what *implementations* provide.

### 7. Create startup module

**File (new):** `src/probos/startup/nats.py`

```python
"""NATS event bus initialization (AD-637a).

Runs in Phase 1 (infrastructure) — NATS must be available before
communication services start.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.config import SystemConfig

logger = logging.getLogger(__name__)


async def init_nats(config: "SystemConfig"):
    """Initialize NATS bus if enabled.

    Returns NATSBus instance (connected or degraded) or None if disabled.
    """
    if not config.nats.enabled:
        logger.info("Startup [nats]: disabled")
        return None

    from probos.mesh.nats_bus import NATSBus

    logger.info("Startup [nats]: connecting to %s", config.nats.url)

    bus = NATSBus(
        url=config.nats.url,
        connect_timeout=config.nats.connect_timeout_seconds,
        max_reconnect_attempts=config.nats.max_reconnect_attempts,
        reconnect_time_wait=config.nats.reconnect_time_wait_seconds,
        drain_timeout=config.nats.drain_timeout_seconds,
        subject_prefix=config.nats.subject_prefix,
        jetstream_enabled=config.nats.jetstream_enabled,
    )

    await bus.start()

    if bus.connected:
        logger.info("Startup [nats]: connected (JetStream=%s)", config.nats.jetstream_enabled)
    else:
        logger.warning(
            "Startup [nats]: connection failed — system will operate without NATS. "
            "Install and start nats-server: https://docs.nats.io/running-a-nats-service/introduction/installation"
        )

    return bus
```

### 8. Wire NATS into runtime startup

**File:** `src/probos/runtime.py`

**8a. Add attribute initialization.** Find where `self.ward_room = None` or similar service attributes are initialized in `__init__`. Add:

```python
self.nats_bus = None  # AD-637: NATS event bus (set in startup)
```

**8b-1. Add NATS init call in Phase 1.** In the `start()` method, after `boot_infrastructure()` call and before Phase 2, add:

```python
# Phase 1b: NATS Event Bus (AD-637)
from probos.startup.nats import init_nats
self.nats_bus = await init_nats(self._config)
```

At this point NATS connects but uses the default `probos.local` prefix. The real ship DID prefix is set later.

**8b-2. Update subject prefix after ship commissioning.** The ship DID is NOT available in Phase 1 — `identity_registry.start()` runs without `instance_id` in `infrastructure.py`. Ship commissioning happens later in Phase 4 (`communication.py`). Therefore, do NOT try to set the prefix in Phase 1. Instead, add a hook in the communication startup phase. Find where `identity_registry.start(instance_id=...)` is called in `src/probos/startup/communication.py` (the "Ship Commissioning (AD-441b)" block). **After** that second `identity_registry.start()` call, add:

```python
# AD-637: Update NATS subject prefix with ship DID
if nats_bus and identity_registry:
    cert = identity_registry.get_ship_certificate()
    if cert:
        nats_bus.set_subject_prefix(f"probos.{cert.ship_did}")
        logger.info("NATS subject prefix updated to probos.%s", cert.ship_did)
```

This requires `nats_bus` to be passed into the communication startup function. Add `nats_bus` as an optional parameter to the communication boot function signature (follow the existing pattern for `identity_registry`, `ward_room`, etc.).

### 9. Wire NATS into shutdown

**File:** `src/probos/startup/shutdown.py`

Add NATS drain/close **after** pools stop AND dream consolidation — near the end of the shutdown sequence. Place it **after** the `# Stop mesh and consensus services` block (which stops gossip, signal_manager, hebbian_router, trust_network) and **before** the `# AD-573: Stop working memory store` block:

```python
# Stop NATS event bus (AD-637) — drain after all publishers have stopped
if runtime.nats_bus:
    await runtime.nats_bus.stop()
    runtime.nats_bus = None
```

### 10. Add pre-flight check

**File:** `src/probos/__main__.py`

Add a `_check_nats()` function near `_ensure_ollama()`. Unlike Ollama, we don't try to start the server — just verify connectivity and report status:

```python
async def _check_nats(config, console: Console) -> None:
    """Check NATS server connectivity if enabled."""
    if not config.nats.enabled:
        return

    import asyncio
    try:
        import nats as nats_lib
    except ImportError:
        console.print("  [yellow]⚠[/yellow] nats-py not installed — run: uv add nats-py")
        return

    try:
        nc = await nats_lib.connect(
            servers=[config.nats.url],
            connect_timeout=3.0,
            max_reconnect_attempts=0,
        )
        server_info = nc.connected_url
        js_ok = False
        try:
            js = nc.jetstream()
            await js.account_info()
            js_ok = True
        except Exception:
            pass
        await nc.close()
        js_status = "JetStream enabled" if js_ok else "JetStream disabled"
        console.print(f"  [green]✓[/green] NATS server at {server_info} ({js_status})")
    except Exception as e:
        console.print(
            f"  [yellow]⚠[/yellow] NATS at {config.nats.url} unreachable: {e}\n"
            f"    Install: https://docs.nats.io/running-a-nats-service/introduction/installation\n"
            f"    Start:   nats-server --jetstream"
        )
```

Call it in `_boot_runtime()` near the Ollama check:

```python
await _check_nats(config, console)
```

---

## Tests

**File (new):** `tests/test_ad637a_nats_foundation.py`

### Test 1: `test_mock_nats_bus_protocol_compliance`
Verify `MockNATSBus` satisfies `NATSBusProtocol`.

```python
from probos.mesh.nats_bus import MockNATSBus
from probos.protocols import NATSBusProtocol
def test_mock_nats_bus_protocol_compliance():
    bus = MockNATSBus()
    assert isinstance(bus, NATSBusProtocol)
```

### Test 2: `test_nats_bus_protocol_compliance`
Verify `NATSBus` satisfies `NATSBusProtocol`.

```python
from probos.mesh.nats_bus import NATSBus
from probos.protocols import NATSBusProtocol
def test_nats_bus_protocol_compliance():
    bus = NATSBus()
    assert isinstance(bus, NATSBusProtocol)
```

### Test 3: `test_mock_publish_subscribe_roundtrip`
Publish a message, verify subscriber receives it.

### Test 4: `test_mock_request_reply`
Send a request, subscriber responds, verify reply received.

### Test 5: `test_mock_subject_prefix`
Verify subject prefix is prepended correctly.

### Test 6: `test_mock_wildcard_matching`
Test `>` and `*` wildcard subject matching in MockNATSBus.

### Test 7: `test_mock_not_connected_noop`
Verify publish/subscribe/request are no-ops when not connected.

### Test 8: `test_mock_start_stop_lifecycle`
Verify start sets connected=True, stop clears state.

### Test 9: `test_mock_ensure_stream`
Verify stream creation is tracked.

### Test 10: `test_mock_js_publish_delegates_to_publish`
Verify `js_publish` uses the same path as `publish` in mock.

### Test 11: `test_nats_bus_not_connected_before_start`
Verify `NATSBus()` is not connected before `start()`.

### Test 12: `test_nats_bus_graceful_failure`
Verify `NATSBus.start()` with unreachable server doesn't raise — sets `connected=False`.

### Test 13: `test_nats_config_defaults`
Verify `NatsConfig()` defaults match expected values.

### Test 14: `test_nats_config_loads_from_yaml`
Verify `load_config()` parses the `nats:` section from system.yaml.

### Test 15: `test_nats_health_not_started`
Verify `.health()` returns correct status when not started.

### Test 16: `test_nats_health_connected`
Verify `.health()` returns correct status when connected (use MockNATSBus).

### Test 17: `test_init_nats_disabled`
Verify `init_nats()` returns None when `config.nats.enabled = False`.

### Test 18: `test_nats_message_wrapper`
Verify `NATSMessage` construction and attribute access.

### Test 19: `test_mock_published_inspection`
Verify `MockNATSBus.published` list captures all published messages for test inspection.

### Test 20: `test_subject_prefix_update`
Verify `set_subject_prefix()` changes the prefix for subsequent operations.

### Test 21: `test_publish_without_stream_uses_core_nats`
Verify that `js_publish()` falls back to core NATS `publish()` when JetStream is not available (i.e., `self._js is None`). Ensures no silent data loss when streams haven't been created.

---

## Verification Checklist

1. `python -m pytest tests/test_ad637a_nats_foundation.py -v` — all 21 tests pass
2. `grep -rn "NATSBus" src/probos/` — found in `mesh/nats_bus.py`, `startup/nats.py`, `runtime.py`
3. `grep -rn "NATSBusProtocol" src/probos/` — found in `protocols.py` only (consumer-facing)
4. `grep -rn "NatsConfig" src/probos/` — found in `config.py`
5. `grep -rn "nats_bus" src/probos/startup/shutdown.py` — shutdown wiring present
6. `grep -rn "_check_nats" src/probos/__main__.py` — pre-flight check wired
7. `python -c "from probos.mesh.nats_bus import NATSBus, MockNATSBus, NATSMessage"` — imports clean
8. `python -c "from probos.config import NatsConfig; print(NatsConfig())"` — config defaults work
9. Full suite: `python -m pytest tests/ -x -n auto` — no regressions

---

## Files Modified

| File | Change |
|------|--------|
| `pyproject.toml` | Add `nats-py>=2.9` dependency |
| `src/probos/config.py` | Add `NatsConfig` class + `nats` field on `SystemConfig` |
| `config/system.yaml` | Add `nats:` configuration section |
| `src/probos/mesh/nats_bus.py` | **NEW** — `NATSMessage`, `NATSBus`, `MockNATSBus` |
| `src/probos/protocols.py` | Add `NATSBusProtocol` for consumers |
| `src/probos/startup/nats.py` | **NEW** — `init_nats()` startup function |
| `src/probos/runtime.py` | Add `self.nats_bus` attribute + Phase 1b init |
| `src/probos/startup/communication.py` | Add `nats_bus` parameter + DID prefix update after ship commissioning |
| `src/probos/startup/shutdown.py` | Add NATS drain/close (after pools + dream consolidation, before working memory store) |
| `src/probos/__main__.py` | Add `_check_nats()` pre-flight check |
| `tests/test_ad637a_nats_foundation.py` | **NEW** — 21 tests |

## Engineering Principles

- **DRY**: One NATS abstraction (`NATSBus`), one config (`NatsConfig`), one startup module
- **Interface Segregation**: `NATSBusProtocol` in `protocols.py` (narrow consumer interface) + full protocol in `nats_bus.py`
- **Dependency Inversion**: Callers depend on `NATSBusProtocol`, not `nats-py` directly
- **Open/Closed**: `MockNATSBus` swaps in without changing any caller code
- **Fail Fast / Defense in Depth**: Connection failure → log warning, degrade gracefully (`.connected` check). No crash. System runs without NATS.
- **Cloud-Ready**: `url` config externalizes server location. Commercial overlay swaps embedded → managed NATS cluster.
- **Law of Demeter**: `NATSMessage` wraps raw `nats.aio.msg.Msg` — callers never touch nats-py internals
