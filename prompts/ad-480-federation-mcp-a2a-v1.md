# AD-480 v1 — Federation Protocol Adapters (MCP server + A2A both directions)

**Wave:** 89
**Closes:** GH #74
**HEAD at draft:** `03937cb`
**Baseline pytest:** 11843 → **target ≥ 11913** (+70 floor; ~72 tests planned).
**Vitest:** 306 unchanged (no UI surface touched).
**Builder:** one commit. Read `prompts/WAVE-89-DISPATCH.md` for full reframe rationale.

## Scope (verified against HEAD `03937cb`)

Nine concrete OSS sub-AD letters:

- **480a** — `FederationMCPServer` class (inbound MCP server: JSON-RPC 2.0 over Streamable HTTP, `initialize` / `tools/list` / `tools/call`) — new file `src/probos/federation/mcp_server.py`.
- **480b** — Capability→MCP-tool translator (every registered `IntentDescriptor` projected as MCP tool entry; `tools/call` translates to `IntentMessage`, dispatches via `IntentBus.broadcast(federated=False)`, returns highest-confidence `IntentResult`) — folded into 480a file.
- **480c** — `AgentCard` dataclass + `AgentCard.from_runtime(runtime)` factory + `to_json_dict()` serializer (A2A 0.2.0 schema) — new file `src/probos/federation/a2a/agent_card.py`.
- **480d** — `FederationA2AServer` class (inbound A2A server: `GET /.well-known/agent.json` + JSON-RPC `tasks/send` + `tasks/get` synchronous-only; `tasks/sendSubscribe` / `tasks/cancel` / `tasks/pushNotification/*` return `-32601 Method not found`) — new file `src/probos/federation/a2a/server.py`.
- **480e** — `A2AClient` class (outbound A2A client: `discover()` / `send_task()` / `get_task()` / `close()`; EgressPolicy-gated mirroring AD-449 client pattern) — new file `src/probos/federation/a2a/client.py`.
- **480f** — `FederationPeer` dataclass + `FederationPeerRegistry` (`protocol: Literal["zmq", "mcp", "a2a"]` discriminator; parallel structure to existing `FederationRouter._peer_models`; auto-registers ZeroMQ peers via existing gossip path) — new file `src/probos/federation/peer.py`.
- **480g** — Probationary trust wiring (`TrustNetwork.create_with_prior(peer_id, alpha=1.0, beta=3.0)` on first peer registration; outcome of every forwarded intent feeds `record_outcome()`) — wired in `src/probos/federation/peer.py` + bridge integration.
- **480h** — Config additions (`FederationMCPServerConfig`, `FederationA2AConfig`, `A2APeerConfig`, `FederationPeerTrustConfig`; three new fields on `FederationConfig`) — `src/probos/config.py:797–826` extension.
- **480i** — `/federation peers` slash subcommand (extends existing `cmd_federation` dispatch) + `render_federation_peers_panel` helper.

Out of scope (NOT v1 deferrals — see dispatch reframe section):
- AD-480j A2A SSE streaming (`tasks/sendSubscribe`) — depends on observability streaming + backpressure substrate.
- AD-480k Inbound MCP/A2A OAuth 2.1 — depends on AD-449d (parked at HEAD per `PROGRESS.md:98`).
- AD-480l Cross-protocol Hebbian routing — depends on AD-479 federation hardening (unshipped at HEAD per `roadmap.md:3201`).
- AD-480m A2A push-notification callbacks (`tasks/pushNotification/*`) — depends on outbound webhook delivery substrate (unbuilt at HEAD).
- Hosted multi-tenant MCP/A2A directory service / fleet-wide MCP marketplace + paid catalog + billing surface / managed cross-fleet A2A trust scoring + signed revocation registry / paid pre-built vendor-specific MCP server packs — carved out per `roadmap.md:3478` + `:3595` + `:4111` to the private commercial-repo path token.

## Section 0 — Constants and shared protocol identifiers

Reuse the existing constants from AD-449 client wherever possible. Only declare new constants for A2A.

In `src/probos/federation/a2a/__init__.py` (new file, ~10 LOC):

```python
"""AD-480: A2A Federation Adapter -- ProbOS as A2A server + A2A client."""

from probos.federation.a2a.agent_card import (
    AgentCard,
    AgentCapabilities,
    AgentProvider,
    AgentSkill,
)
from probos.federation.a2a.client import A2AClient, A2AProtocolError
from probos.federation.a2a.server import FederationA2AServer

# A2A spec version we conform to.
A2A_PROTOCOL_VERSION = "0.2.0"

__all__ = [
    "AgentCard",
    "AgentCapabilities",
    "AgentProvider",
    "AgentSkill",
    "A2AClient",
    "A2AProtocolError",
    "A2A_PROTOCOL_VERSION",
    "FederationA2AServer",
]
```

## Section 1 — `src/probos/federation/peer.py` (new file, ~110 LOC)

```python
"""AD-480f: FederationPeer + FederationPeerRegistry — protocol-polymorphic peer model.

Maintains a parallel structure to FederationRouter._peer_models (which is
ZeroMQ-keyed by node_id only). Each peer carries a protocol discriminator
("zmq" | "mcp" | "a2a") and the trust_record_id used by TrustNetwork for
the Beta(alpha, beta) probationary prior wiring.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Literal


PeerProtocol = Literal["zmq", "mcp", "a2a"]


@dataclass
class FederationPeer:
    """One federated peer.

    For ZeroMQ peers, peer_id == node_id and endpoint == bind address.
    For MCP peers, peer_id == server URL and endpoint == server URL.
    For A2A peers, peer_id == peer URL and endpoint == peer URL.
    """

    protocol: PeerProtocol
    peer_id: str
    endpoint: str
    trust_record_id: str
    discovered_at: float = field(default_factory=time.time)
    last_outcome_at: float = 0.0
    capabilities: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class FederationPeerRegistry:
    """In-memory registry of federated peers across all three protocols."""

    def __init__(self, *, trust_network: Any | None = None,
                 probationary_alpha: float = 1.0,
                 probationary_beta: float = 3.0) -> None:
        self._peers: dict[str, FederationPeer] = {}
        self._lock = asyncio.Lock()
        self._trust_network = trust_network
        self._probationary_alpha = probationary_alpha
        self._probationary_beta = probationary_beta

    async def register_peer(self, peer: FederationPeer) -> bool:
        """Register a peer. Returns True if newly registered, False if already known."""
        async with self._lock:
            if peer.peer_id in self._peers:
                return False
            self._peers[peer.peer_id] = peer
        # AD-480g: probationary trust prior on first registration.
        if self._trust_network is not None:
            self._trust_network.create_with_prior(
                peer.trust_record_id,
                self._probationary_alpha,
                self._probationary_beta,
            )
        return True

    async def unregister_peer(self, peer_id: str) -> bool:
        async with self._lock:
            return self._peers.pop(peer_id, None) is not None

    def get_peer(self, peer_id: str) -> FederationPeer | None:
        return self._peers.get(peer_id)

    def list_peers(self, protocol: PeerProtocol | None = None) -> list[FederationPeer]:
        peers = list(self._peers.values())
        if protocol is not None:
            peers = [p for p in peers if p.protocol == protocol]
        return peers

    def peers_supporting(self, intent_name: str) -> list[FederationPeer]:
        return [p for p in self._peers.values() if intent_name in p.capabilities]

    def record_outcome(self, peer_id: str, success: bool, *,
                       intent_type: str = "") -> None:
        peer = self._peers.get(peer_id)
        if peer is None:
            return
        peer.last_outcome_at = time.time()
        if self._trust_network is not None:
            self._trust_network.record_outcome(
                peer.trust_record_id,
                success=success,
                weight=1.0,
                intent_type=intent_type,
                source="federation_outcome",
            )

    def __len__(self) -> int:
        return len(self._peers)
```

## Section 2 — `src/probos/federation/a2a/agent_card.py` (new file, ~120 LOC)

Implement `AgentCard` per A2A 0.2.0 schema. Key fields per spec:

```python
"""AD-480c: AgentCard — A2A 0.2.0 spec serializer.

Read at /.well-known/agent.json by A2A clients to discover this ship's
capabilities. Reads vessel_name + ship_did from AgentIdentityRegistry per
the AD-441 / AD-499 connection at roadmap.md:7013.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)


@dataclass
class AgentCapabilities:
    streaming: bool = False              # 480j parks SSE
    pushNotifications: bool = False       # 480m parks push
    stateTransitionHistory: bool = False


@dataclass
class AgentProvider:
    organization: str = ""
    url: str = ""


@dataclass
class AgentSkill:
    id: str
    name: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    inputModes: list[str] = field(default_factory=lambda: ["text"])
    outputModes: list[str] = field(default_factory=lambda: ["text"])


@dataclass
class AgentCard:
    name: str
    description: str
    url: str
    version: str
    capabilities: AgentCapabilities = field(default_factory=AgentCapabilities)
    skills: list[AgentSkill] = field(default_factory=list)
    defaultInputModes: list[str] = field(default_factory=lambda: ["text"])
    defaultOutputModes: list[str] = field(default_factory=lambda: ["text"])
    provider: AgentProvider | None = None

    def to_json_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "version": self.version,
            "capabilities": {
                "streaming": self.capabilities.streaming,
                "pushNotifications": self.capabilities.pushNotifications,
                "stateTransitionHistory": self.capabilities.stateTransitionHistory,
            },
            "skills": [
                {
                    "id": s.id,
                    "name": s.name,
                    "description": s.description,
                    "tags": list(s.tags),
                    "examples": list(s.examples),
                    "inputModes": list(s.inputModes),
                    "outputModes": list(s.outputModes),
                }
                for s in self.skills
            ],
            "defaultInputModes": list(self.defaultInputModes),
            "defaultOutputModes": list(self.defaultOutputModes),
        }
        if self.provider is not None:
            d["provider"] = {
                "organization": self.provider.organization,
                "url": self.provider.url,
            }
        return d

    @classmethod
    def from_runtime(cls, runtime: "ProbOSRuntime", *,
                     base_url: str = "",
                     version: str = "0.1.0") -> "AgentCard":
        """Build an AgentCard from the runtime's live state."""
        # Vessel identity (AD-441 / AD-499 connection per roadmap.md:7013)
        vessel_name = "ProbOS"
        ship_did = ""
        if runtime.identity_registry is not None:
            cert = runtime.identity_registry.get_ship_certificate()
            if cert is not None:
                vessel_name = cert.vessel_name
                ship_did = cert.ship_did

        # Skills derived from registered IntentDescriptors
        skills: list[AgentSkill] = []
        try:
            descriptors = list(runtime.decomposer._intent_descriptors.values())
        except Exception:
            logger.warning("AD-480c: decomposer descriptor read failed; AgentCard "
                           "has empty skills list", exc_info=True)
            descriptors = []

        for desc in descriptors:
            skills.append(AgentSkill(
                id=desc.name,
                name=desc.name,
                description=desc.description,
                tags=[desc.tier],
            ))

        provider = AgentProvider(organization=vessel_name, url=ship_did)

        return cls(
            name=vessel_name,
            description=f"ProbOS {vessel_name} (ship_did={ship_did})",
            url=base_url,
            version=version,
            skills=skills,
            provider=provider,
        )
```

## Section 3 — `src/probos/federation/a2a/server.py` (new file, ~250 LOC)

Implement `FederationA2AServer`. Key details:

- Standalone ASGI app constructed via `Starlette` (already an indirect dependency through FastAPI / uvicorn wiring used elsewhere in the runtime). If `starlette` import fails, the server logs `logger.warning("AD-480d: starlette not installed; A2A server disabled")` and `start()` is a no-op (gracefully degrade — single-node and ZeroMQ-only deployments unaffected).
- Routes:
  - `GET /.well-known/agent.json` → `AgentCard.from_runtime(runtime, base_url=server_url, version=__version__).to_json_dict()` (200 JSON)
  - `POST /a2a` → JSON-RPC dispatch
- JSON-RPC method handlers:
  - `tasks/send` — params: `{id?: str, sessionId?: str, message: {role: "user", parts: [{type: "text", text: str}, ...]}, acceptedOutputModes?: [str]}`. Parse first text part as `<skill_id>:<json_args>` (skill_id matches an `IntentDescriptor.name`; json_args is a JSON-encoded params dict). Construct `IntentMessage(intent=skill_id, params=parsed_args, context=f"a2a:{peer_id}")`. Dispatch via `runtime.intent_bus.broadcast(intent, federated=False)`. Pick highest-confidence successful `IntentResult`. Return `Task` object: `{"id": task_id, "sessionId": session_id, "status": {"state": "completed" if result.success else "failed", "timestamp": ISO8601}, "artifacts": [{"parts": [{"type": "text", "text": json.dumps(result.result)}]}], "history": []}`. Store in per-server task store keyed by `task_id` (asyncio.Lock-guarded; FIFO eviction at 1000 entries).
  - `tasks/get` — params: `{id: str}`. Returns the stored `Task` or JSON-RPC error `-32602 Invalid params: task not found`.
  - `tasks/cancel` / `tasks/sendSubscribe` / `tasks/pushNotification/set` / `tasks/pushNotification/get` — return JSON-RPC error `-32601 Method not found` (parked at AD-480j / AD-480m).
- Trust integration: on first inbound JSON-RPC call from a previously-unseen peer (identified by `X-A2A-Peer-Id` header if present, else by `request.client.host`), call `runtime.federation_peer_registry.register_peer(FederationPeer(protocol="a2a", peer_id=peer_id, endpoint=peer_id, trust_record_id=f"a2a-peer:{peer_id}"))`. After dispatch completes, call `runtime.federation_peer_registry.record_outcome(peer_id, success=result.success, intent_type=intent.intent)`.
- Auth: if `runtime.config.federation.a2a.outbound_peers` declares an `auth_token` for this peer, validate the inbound `Authorization: Bearer <token>` header. Mismatch returns JSON-RPC error `-32600 Invalid Request: authentication failed`. (Static bearer only in v1 — full OAuth at AD-480k.)
- Lifecycle:
  - `async def start()` — bind on `(bind_host, bind_port)` via `uvicorn.Server(uvicorn.Config(app, host=bind_host, port=bind_port, log_level="warning"))`. Run as `asyncio.create_task(server.serve(), name="a2a-server")`.
  - `async def stop()` — set `server.should_exit = True`, await the task with timeout, on timeout cancel.

The class signature:

```python
class FederationA2AServer:
    def __init__(self, *, runtime: "ProbOSRuntime", config: "FederationA2AConfig") -> None: ...
    @property
    def is_running(self) -> bool: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    # Internal handler methods (testable directly without ASGI):
    async def handle_agent_card_request(self) -> dict: ...
    async def handle_jsonrpc(self, payload: dict, *, peer_id: str = "",
                             auth_header: str = "") -> dict: ...
```

The two internal handlers are the test surface — tests at `TestA2AServerInbound` exercise `handle_agent_card_request` and `handle_jsonrpc` directly without spinning the uvicorn loop.

## Section 4 — `src/probos/federation/a2a/client.py` (new file, ~200 LOC)

Mirror the `MCPClient` pattern at `src/probos/integrations/mcp_bridge/client.py`:

```python
"""AD-480e: A2AClient -- outbound A2A client over JSON-RPC + HTTP."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import httpx

from probos.federation.a2a.agent_card import (
    AgentCard, AgentCapabilities, AgentProvider, AgentSkill,
)

logger = logging.getLogger(__name__)


JSONRPC_VERSION = "2.0"


class A2AProtocolError(Exception):
    """Raised on JSON-RPC error or malformed payload."""


class A2AClient:
    def __init__(
        self, *,
        peer_url: str,
        auth_token: str = "",
        egress_policy: Any | None = None,
        emit_event: Any | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._peer_url = peer_url.rstrip("/")
        self._auth_token = auth_token
        self._egress_policy = egress_policy
        self._emit_event = emit_event
        self._timeout = timeout
        self._http: httpx.AsyncClient | None = httpx.AsyncClient(timeout=timeout)
        self._discovered_card: AgentCard | None = None

    @property
    def discovered_card(self) -> AgentCard | None:
        return self._discovered_card

    async def discover(self) -> AgentCard:
        url = f"{self._peer_url}/.well-known/agent.json"
        if self._egress_policy is not None and not self._egress_policy.is_allowed(url):
            raise A2AProtocolError(f"egress denied for {url}")
        http = self._http
        if http is None:
            raise A2AProtocolError("client closed")
        try:
            response = await http.get(url)
        except httpx.HTTPError as exc:
            raise A2AProtocolError(f"transport error: {exc}") from exc
        if response.status_code >= 400:
            raise A2AProtocolError(f"HTTP {response.status_code} from {url}")
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise A2AProtocolError(f"bad JSON from {url}") from exc
        card = self._parse_agent_card(payload)
        self._discovered_card = card
        return card

    async def send_task(self, skill_id: str, args: dict[str, Any], *,
                        session_id: str = "") -> dict[str, Any]:
        text_payload = f"{skill_id}:{json.dumps(args, sort_keys=True)}"
        return await self._call(
            method="tasks/send",
            params={
                "id": uuid.uuid4().hex,
                "sessionId": session_id,
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": text_payload}],
                },
            },
        )

    async def get_task(self, task_id: str) -> dict[str, Any]:
        return await self._call(method="tasks/get", params={"id": task_id})

    async def close(self) -> None:
        http = getattr(self, "_http", None)
        if http is not None:
            await http.aclose()
        self._http = None

    async def _call(self, *, method: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._peer_url}/a2a"
        if self._egress_policy is not None and not self._egress_policy.is_allowed(url):
            raise A2AProtocolError(f"egress denied for {url}")
        http = self._http
        if http is None:
            raise A2AProtocolError("client closed")
        request_id = uuid.uuid4().hex
        payload = {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "method": method,
            "params": params,
        }
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"
        try:
            response = await http.post(url, content=json.dumps(payload), headers=headers)
        except httpx.HTTPError as exc:
            raise A2AProtocolError(f"transport error: {exc}") from exc
        if response.status_code >= 400:
            raise A2AProtocolError(f"HTTP {response.status_code} from {url}")
        try:
            envelope = response.json()
        except json.JSONDecodeError as exc:
            raise A2AProtocolError(f"bad JSON from {url}") from exc
        if not isinstance(envelope, dict):
            raise A2AProtocolError(f"bad envelope from {url}")
        if "error" in envelope:
            err = envelope.get("error") or {}
            msg = err.get("message", "unknown") if isinstance(err, dict) else "unknown"
            code = err.get("code", 0) if isinstance(err, dict) else 0
            raise A2AProtocolError(f"rpc error {code}: {msg}")
        result = envelope.get("result")
        if not isinstance(result, dict):
            raise A2AProtocolError(f"bad result from {url}")
        return result

    @staticmethod
    def _parse_agent_card(payload: dict) -> AgentCard:
        caps_raw = payload.get("capabilities") or {}
        prov_raw = payload.get("provider")
        skills_raw = payload.get("skills") or []
        skills: list[AgentSkill] = []
        for s in skills_raw:
            if not isinstance(s, dict):
                continue
            skills.append(AgentSkill(
                id=str(s.get("id", "")),
                name=str(s.get("name", "")),
                description=str(s.get("description", "")),
                tags=list(s.get("tags") or []),
                examples=list(s.get("examples") or []),
                inputModes=list(s.get("inputModes") or ["text"]),
                outputModes=list(s.get("outputModes") or ["text"]),
            ))
        return AgentCard(
            name=str(payload.get("name", "")),
            description=str(payload.get("description", "")),
            url=str(payload.get("url", "")),
            version=str(payload.get("version", "")),
            capabilities=AgentCapabilities(
                streaming=bool(caps_raw.get("streaming", False)),
                pushNotifications=bool(caps_raw.get("pushNotifications", False)),
                stateTransitionHistory=bool(caps_raw.get("stateTransitionHistory", False)),
            ),
            skills=skills,
            defaultInputModes=list(payload.get("defaultInputModes") or ["text"]),
            defaultOutputModes=list(payload.get("defaultOutputModes") or ["text"]),
            provider=(
                AgentProvider(
                    organization=str(prov_raw.get("organization", "")),
                    url=str(prov_raw.get("url", "")),
                )
                if isinstance(prov_raw, dict) else None
            ),
        )
```

## Section 5 — `src/probos/federation/mcp_server.py` (new file, ~280 LOC)

Mirror the AD-449 client wire format on the server side. Reuse `JSONRPC_VERSION = "2.0"` and `MCP_PROTOCOL_VERSION = "2025-03-26"` constants directly imported from `probos.integrations.mcp_bridge.client`.

Key structure:

```python
"""AD-480a: FederationMCPServer -- inbound MCP server.

Mirror of AD-449 outbound MCPClient on the server side. Reuses JSON-RPC
constants from the AD-449 client. Translates incoming tools/call to
IntentMessage and dispatches via IntentBus.broadcast(federated=False).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, TYPE_CHECKING

from probos.events import EventType
from probos.integrations.mcp_bridge.client import (
    JSONRPC_VERSION, MCP_PROTOCOL_VERSION,
)
from probos.types import IntentMessage

if TYPE_CHECKING:
    from probos.config import FederationMCPServerConfig
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)


class FederationMCPServer:
    def __init__(self, *, runtime: "ProbOSRuntime",
                 config: "FederationMCPServerConfig") -> None:
        self._runtime = runtime
        self._config = config
        self._task_store: dict[str, dict[str, Any]] = {}
        self._sessions: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()
        self._server_task: asyncio.Task | None = None
        self._uvicorn_server: Any | None = None

    @property
    def is_running(self) -> bool:
        return self._server_task is not None and not self._server_task.done()

    async def start(self) -> None:
        if not self._config.enabled:
            return
        try:
            from starlette.applications import Starlette
            from starlette.responses import JSONResponse
            from starlette.routing import Route
            import uvicorn
        except ImportError:
            logger.warning("AD-480a: starlette/uvicorn missing; MCP server disabled")
            return

        async def jsonrpc_endpoint(request):
            body = await request.body()
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                return JSONResponse(
                    self._error_envelope(None, -32700, "Parse error"), status_code=400,
                )
            session_id = request.headers.get("mcp-session-id", "")
            response = await self.handle_jsonrpc(payload, session_id=session_id)
            headers = {}
            if response.get("_assigned_session"):
                headers["Mcp-Session-Id"] = response.pop("_assigned_session")
            return JSONResponse(response, headers=headers)

        app = Starlette(routes=[
            Route(self._config.path_prefix or "/mcp", jsonrpc_endpoint, methods=["POST"]),
        ])
        config = uvicorn.Config(
            app, host=self._config.bind_host, port=self._config.bind_port,
            log_level="warning", lifespan="off",
        )
        self._uvicorn_server = uvicorn.Server(config)
        try:
            self._server_task = asyncio.create_task(
                self._uvicorn_server.serve(), name="mcp-server",
            )
        except OSError as exc:
            logger.error("AD-480a: MCP server bind failed (port %d): %s",
                         self._config.bind_port, exc)
            self._server_task = None
            self._uvicorn_server = None

    async def stop(self) -> None:
        if self._uvicorn_server is not None:
            self._uvicorn_server.should_exit = True
        if self._server_task is not None:
            try:
                await asyncio.wait_for(self._server_task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._server_task.cancel()
        self._server_task = None
        self._uvicorn_server = None

    # --- JSON-RPC dispatch (test surface) ---

    async def handle_jsonrpc(self, payload: dict[str, Any], *,
                             session_id: str = "") -> dict[str, Any]:
        request_id = payload.get("id")
        method = payload.get("method", "")
        params = payload.get("params") or {}
        if not isinstance(params, dict):
            return self._error_envelope(request_id, -32602, "Invalid params")
        try:
            if method == "initialize":
                return await self._handle_initialize(request_id, params)
            if method == "tools/list":
                return await self._handle_tools_list(request_id)
            if method == "tools/call":
                return await self._handle_tools_call(request_id, params, session_id)
            return self._error_envelope(request_id, -32601, f"Method not found: {method}")
        except Exception as exc:
            self._emit_failed(method, reason="server_error", detail=str(exc))
            logger.exception("AD-480a: server error handling %s", method)
            return self._error_envelope(request_id, -32000, f"Server error: {exc}")

    async def _handle_initialize(self, request_id: Any,
                                  params: dict) -> dict[str, Any]:
        sid = uuid.uuid4().hex
        self._sessions[sid] = {"created_at": time.time()}
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "result": {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "probos-mcp-server", "version": "0.1.0"},
            },
            "_assigned_session": sid,
        }

    async def _handle_tools_list(self, request_id: Any) -> dict[str, Any]:
        tools = self._project_tools_from_descriptors()
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "result": {"tools": tools},
        }

    async def _handle_tools_call(self, request_id: Any, params: dict,
                                  session_id: str) -> dict[str, Any]:
        tool_name = params.get("name", "")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return self._error_envelope(request_id, -32602, "arguments must be object")
        if not tool_name:
            return self._error_envelope(request_id, -32602, "name required")

        # Trust onboarding for this peer (session_id used as peer key)
        peer_id = f"mcp-session:{session_id}" if session_id else f"mcp-anon:{request_id}"
        await self._ensure_peer_registered(peer_id)

        intent = IntentMessage(
            intent=tool_name, params=arguments,
            context=f"mcp_server:{peer_id}",
        )
        results = await self._runtime.intent_bus.broadcast(intent, federated=False)
        if not results:
            self._record_outcome(peer_id, False, intent_type=tool_name)
            return self._error_envelope(request_id, -32000, "no agent handled tool")
        # Pick the highest-confidence successful result; fall back to highest-confidence overall.
        winning = None
        for r in sorted(results, key=lambda x: x.confidence, reverse=True):
            if r.success:
                winning = r
                break
        if winning is None:
            winning = max(results, key=lambda x: x.confidence)
        self._record_outcome(peer_id, winning.success, intent_type=tool_name)
        self._emit_invoke(method="tools/call", tool=tool_name)
        if not winning.success:
            return self._error_envelope(request_id, -32000,
                                         f"tool failed: {winning.error or 'unknown'}")
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "result": {
                "content": [{"type": "text", "text": json.dumps(winning.result)}],
                "isError": False,
            },
        }

    def _project_tools_from_descriptors(self) -> list[dict[str, Any]]:
        try:
            descriptors = list(
                self._runtime.decomposer._intent_descriptors.values()
            )
        except Exception:
            logger.warning("AD-480b: descriptor read failed; returning []",
                           exc_info=True)
            return []
        tools: list[dict[str, Any]] = []
        for desc in descriptors:
            params_schema = {
                "type": "object",
                "properties": {
                    pname: {"type": "string", "description": pdesc}
                    for pname, pdesc in desc.params.items()
                },
                "required": list(desc.params.keys()),
            }
            tools.append({
                "name": desc.name,
                "description": desc.description,
                "inputSchema": params_schema,
            })
        return tools

    async def _ensure_peer_registered(self, peer_id: str) -> None:
        # federation_peer_registry is always present (eagerly initialized in
        # ProbOSRuntime.__init__ per Section 6.3 — no defensive getattr).
        from probos.federation.peer import FederationPeer
        await self._runtime.federation_peer_registry.register_peer(FederationPeer(
            protocol="mcp", peer_id=peer_id, endpoint=peer_id,
            trust_record_id=f"mcp-peer:{peer_id}",
        ))

    def _record_outcome(self, peer_id: str, success: bool, *,
                        intent_type: str = "") -> None:
        self._runtime.federation_peer_registry.record_outcome(
            peer_id, success, intent_type=intent_type,
        )

    def _emit_invoke(self, *, method: str, tool: str) -> None:
        try:
            self._runtime.emit_event(EventType.MCP_BRIDGE_INVOKE, {
                "side": "server", "method": method, "tool": tool,
            })
        except Exception:
            logger.warning("AD-480a: MCP_BRIDGE_INVOKE emit failed", exc_info=True)

    def _emit_failed(self, method: str, *, reason: str, detail: str = "") -> None:
        try:
            self._runtime.emit_event(EventType.MCP_BRIDGE_FAILED, {
                "side": "server", "method": method, "reason": reason,
                "detail": detail[:200],
            })
        except Exception:
            logger.warning("AD-480a: MCP_BRIDGE_FAILED emit failed", exc_info=True)

    @staticmethod
    def _error_envelope(request_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "error": {"code": code, "message": message},
        }
```

## Section 6 — `src/probos/runtime.py` modification

Add the registry and (optional) servers to runtime.

### 6.1 Type-only import (TYPE_CHECKING block)

SEARCH (around `runtime.py:136`):

```python
    from probos.federation.bridge import FederationBridge
    from probos.federation.transport import FederationTransport
```

REPLACE with:

```python
    from probos.federation.bridge import FederationBridge
    from probos.federation.transport import FederationTransport
    from probos.federation.peer import FederationPeerRegistry
    from probos.federation.mcp_server import FederationMCPServer
    from probos.federation.a2a.server import FederationA2AServer
```

### 6.2 Public attribute declarations

SEARCH (around `runtime.py:222`):

```python
    federation_bridge: FederationBridge | None
```

REPLACE with:

```python
    federation_bridge: FederationBridge | None
    federation_peer_registry: "FederationPeerRegistry"
    federation_mcp_server: "FederationMCPServer | None"
    federation_a2a_server: "FederationA2AServer | None"
```

### 6.3 `__init__` initialization

SEARCH (around `runtime.py:502–504`):

```python
        # --- Federation ---
        self.federation_bridge: FederationBridge | None = None
        self._federation_transport: FederationTransport | None = None
```

REPLACE with:

```python
        # --- Federation ---
        self.federation_bridge: FederationBridge | None = None
        self._federation_transport: FederationTransport | None = None
        # AD-480f: cross-protocol peer registry — initialized eagerly so
        # ZeroMQ peers can be auto-registered via the existing gossip path.
        from probos.federation.peer import FederationPeerRegistry
        self.federation_peer_registry: FederationPeerRegistry = FederationPeerRegistry(
            trust_network=self.trust_network,
            probationary_alpha=self.config.federation.peer_trust.probationary_alpha,
            probationary_beta=self.config.federation.peer_trust.probationary_beta,
        )
        # AD-480a / AD-480d: inbound servers — None until startup wires them.
        self.federation_mcp_server: "FederationMCPServer | None" = None
        self.federation_a2a_server: "FederationA2AServer | None" = None
```

Note: this requires `self.trust_network` to be already initialized at this point in `__init__`. Verify by reading the surrounding context — if `trust_network` is initialized later, move the registry init to immediately after `self.trust_network = ...`.

## Section 7 — `src/probos/startup/fleet_organization.py` modification

Wire the two new servers adjacent to the existing FederationBridge wiring.

After the existing `await bridge.start()` call (around `fleet_organization.py:206`), add the MCP server + A2A server lifecycle:

SEARCH (around `fleet_organization.py:206–211`):

```python
            await bridge.start()
            # PATCH(AD-517): Wire federation function into intent bus
            intent_bus.set_federation_handler(bridge.forward_intent)
            federation_bridge = bridge
            federation_transport = transport
            logger.info("Federation started: node=%s", config.federation.node_id)
```

REPLACE with:

```python
            await bridge.start()
            # PATCH(AD-517): Wire federation function into intent bus
            intent_bus.set_federation_handler(bridge.forward_intent)
            federation_bridge = bridge
            federation_transport = transport
            logger.info("Federation started: node=%s", config.federation.node_id)

    # AD-480: inbound MCP / A2A servers (default-False — opt-in).
    federation_mcp_server = None
    federation_a2a_server = None
    if config.federation.mcp_server.enabled and runtime is not None:
        try:
            from probos.federation.mcp_server import FederationMCPServer
            federation_mcp_server = FederationMCPServer(
                runtime=runtime, config=config.federation.mcp_server,
            )
            await federation_mcp_server.start()
            logger.info("AD-480a: MCP server started on %s:%d",
                        config.federation.mcp_server.bind_host,
                        config.federation.mcp_server.bind_port)
        except Exception as exc:
            logger.warning("AD-480a: MCP server start failed: %s", exc)
            federation_mcp_server = None
    if config.federation.a2a.enabled and runtime is not None:
        try:
            from probos.federation.a2a.server import FederationA2AServer
            federation_a2a_server = FederationA2AServer(
                runtime=runtime, config=config.federation.a2a,
            )
            await federation_a2a_server.start()
            logger.info("AD-480d: A2A server started on %s:%d",
                        config.federation.a2a.bind_host,
                        config.federation.a2a.bind_port)
        except Exception as exc:
            logger.warning("AD-480d: A2A server start failed: %s", exc)
            federation_a2a_server = None
```

Note: the existing function signature must accept the runtime handle (or it must be available as a closure). Verify the surrounding context — if `runtime` is not in scope at the top of the function, the wiring must instead happen at a later phase (Builder: pick the phase where `runtime` is fully constructed; the AD-449 `runtime.mcp_bridge` wiring is the precedent — wherever AD-449 wires the outbound bridge, the AD-480 servers wire alongside).

If the wiring location is changed, update `FleetOrganizationResult` at `startup/results.py:84` accordingly:

SEARCH:

```python
    federation_bridge: Any  # FederationBridge | None
```

REPLACE with:

```python
    federation_bridge: Any  # FederationBridge | None
    federation_mcp_server: Any = None  # AD-480a: FederationMCPServer | None
    federation_a2a_server: Any = None  # AD-480d: FederationA2AServer | None
```

And in `runtime.py` at the corresponding `self.federation_bridge = org.federation_bridge` line (`runtime.py:1327`), add:

```python
        self.federation_bridge = org.federation_bridge
        self._federation_transport = org.federation_transport
        self.federation_mcp_server = org.federation_mcp_server
        self.federation_a2a_server = org.federation_a2a_server
```

## Section 8 — `src/probos/config.py` modifications

### 8.1 New Pydantic models

SEARCH (around `config.py:797`):

```python
class FederationConfig(BaseModel):
    """Multi-node federation configuration."""

    enabled: bool = False  # Disabled by default — single-node is still the default
```

REPLACE with:

```python
class FederationMCPServerConfig(BaseModel):
    """AD-480a: Inbound MCP server — exposes ProbOS capabilities as MCP tools."""

    enabled: bool = False  # Default-False per AD-695 + W82 + W88 precedent
    bind_host: str = "127.0.0.1"
    bind_port: int = Field(default=8765, ge=1, le=65535)
    path_prefix: str = "/mcp"


class A2APeerConfig(BaseModel):
    """AD-480e: Outbound A2A peer registration entry."""

    peer_url: str
    auth_token: str = ""


class FederationA2AConfig(BaseModel):
    """AD-480d / AD-480e: Inbound A2A server + outbound A2A clients."""

    enabled: bool = False  # Default-False per AD-695 + W82 + W88 precedent
    bind_host: str = "127.0.0.1"
    bind_port: int = Field(default=8766, ge=1, le=65535)
    agent_card_path: str = "/.well-known/agent.json"
    outbound_peers: list[A2APeerConfig] = Field(default_factory=list)


class FederationPeerTrustConfig(BaseModel):
    """AD-480g: Probationary trust prior for federated peers."""

    probationary_alpha: float = Field(default=1.0, gt=0.0)
    probationary_beta: float = Field(default=3.0, gt=0.0)


class FederationConfig(BaseModel):
    """Multi-node federation configuration."""

    enabled: bool = False  # Disabled by default — single-node is still the default
```

### 8.2 New fields on FederationConfig

After the existing `memory_policy_selective_tags: list[str] = []` line (around `config.py:815`) and BEFORE the `@field_validator("memory_policy")` line, add:

```python
    # AD-480: Cross-ecosystem federation adapters.
    mcp_server: FederationMCPServerConfig = Field(
        default_factory=FederationMCPServerConfig
    )
    a2a: FederationA2AConfig = Field(default_factory=FederationA2AConfig)
    peer_trust: FederationPeerTrustConfig = Field(
        default_factory=FederationPeerTrustConfig
    )
```

## Section 9 — `src/probos/experience/commands/commands_status.py` + `panels.py`

### 9.1 Slash subcommand dispatch

SEARCH at `commands_status.py:100`:

```python
async def cmd_federation(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Handle /federation command."""
    from probos.experience import panels

    bridge = runtime.federation_bridge
    if not bridge:
        console.print("[yellow]Federation is not enabled.[/yellow]")
        return
    console.print(panels.render_federation_panel(bridge.federation_status()))
```

REPLACE with:

```python
async def cmd_federation(runtime: ProbOSRuntime, console: Console, args: str) -> None:
    """Handle /federation command.

    AD-480i: subcommand dispatch. ``""`` (no arg) → existing federation panel.
    ``"peers"`` → cross-protocol peer list with trust scores.
    """
    from probos.experience import panels

    sub = (args or "").strip().split(maxsplit=1)
    subcommand = sub[0].lower() if sub else ""

    if subcommand == "peers":
        registry = runtime.federation_peer_registry
        trust_network = runtime.trust_network
        console.print(panels.render_federation_peers_panel(
            registry.list_peers(), trust_network,
        ))
        return

    bridge = runtime.federation_bridge
    if not bridge:
        console.print("[yellow]Federation is not enabled.[/yellow]")
        return
    console.print(panels.render_federation_panel(bridge.federation_status()))
```

### 9.2 New panel renderer

In `experience/panels.py`, after the existing `render_federation_panel` function (after line 813), add:

```python
def render_federation_peers_panel(peers: list, trust_network) -> Panel:
    """AD-480i: render cross-protocol federation peers with trust scores.

    Columns: protocol / peer_id / capabilities / trust_score / last_outcome.
    """
    from probos.federation.peer import FederationPeer  # type: ignore

    if not peers:
        return Panel(
            "[dim]No federated peers registered.[/dim]",
            title="Federation Peers", border_style="cyan",
        )
    lines = []
    lines.append(
        f"{'PROTO':<6} {'PEER':<40} {'TRUST':>6} {'OUTCOME':<14}  CAPS"
    )
    for p in peers:
        score = trust_network.get_score(p.trust_record_id) if trust_network else 0.0
        last_outcome = (
            time.strftime("%H:%M:%S", time.localtime(p.last_outcome_at))
            if p.last_outcome_at else "-"
        )
        peer_short = (p.peer_id[:38] + "..") if len(p.peer_id) > 40 else p.peer_id
        caps_short = ",".join(p.capabilities[:3])
        if len(p.capabilities) > 3:
            caps_short += f" (+{len(p.capabilities) - 3})"
        lines.append(
            f"{p.protocol:<6} {peer_short:<40} {score:>6.3f} {last_outcome:<14}  {caps_short}"
        )
    body = "\n".join(lines)
    return Panel(body, title="Federation Peers", border_style="cyan")
```

Add `import time` at the top of `panels.py` if not already present.

## Section 10 — Tests: new file `tests/test_ad480_federation_mcp_a2a.py` (~72 tests floor)

```python
"""AD-480: Federation MCP server + A2A both directions."""

from __future__ import annotations

import asyncio
import json
import pytest

# Test classes and example test names (Builder fills in bodies):

class TestFederationPeerRegistry:
    """AD-480f + 480g: ~6 tests."""
    # test_register_peer_first_time_invokes_create_with_prior
    # test_register_peer_idempotent_does_not_invoke_create_with_prior_twice
    # test_unregister_peer_removes_entry
    # test_list_peers_filtered_by_protocol
    # test_peers_supporting_returns_subset_with_capability
    # test_record_outcome_invokes_trust_record_outcome


class TestAgentCard:
    """AD-480c: ~8 tests."""
    # test_to_json_dict_minimal
    # test_to_json_dict_with_provider
    # test_to_json_dict_with_skills
    # test_capabilities_streaming_default_false
    # test_capabilities_push_default_false
    # test_from_runtime_uses_vessel_name
    # test_from_runtime_uses_ship_did_in_provider_url
    # test_from_runtime_skills_derived_from_descriptors


class TestA2AClient:
    """AD-480e: ~8 tests."""
    # test_discover_fetches_agent_json
    # test_discover_parses_capabilities
    # test_discover_parses_skills
    # test_discover_handles_missing_provider
    # test_send_task_posts_jsonrpc_envelope
    # test_send_task_with_auth_token_sets_authorization_header
    # test_get_task_correlates_by_id
    # test_close_aclose_idempotent_after_close


class TestA2AServerInbound:
    """AD-480d: ~10 tests."""
    # test_handle_agent_card_request_returns_card
    # test_handle_jsonrpc_tasks_send_dispatches_intent
    # test_handle_jsonrpc_tasks_send_returns_completed_task
    # test_handle_jsonrpc_tasks_get_correlates_by_id
    # test_handle_jsonrpc_tasks_get_unknown_returns_invalid_params
    # test_handle_jsonrpc_unknown_method_returns_method_not_found
    # test_handle_jsonrpc_streaming_method_returns_method_not_found
    # test_handle_jsonrpc_push_method_returns_method_not_found
    # test_handle_jsonrpc_auth_token_mismatch_returns_invalid_request
    # test_handle_jsonrpc_records_outcome_on_success_path


class TestMCPServerInbound:
    """AD-480a + 480b: ~12 tests."""
    # test_handle_jsonrpc_initialize_assigns_session_id
    # test_handle_jsonrpc_initialize_returns_protocol_version
    # test_handle_jsonrpc_tools_list_projects_descriptors
    # test_handle_jsonrpc_tools_list_input_schema_marks_params_required
    # test_handle_jsonrpc_tools_call_dispatches_via_intent_bus_federated_false
    # test_handle_jsonrpc_tools_call_returns_highest_confidence_success
    # test_handle_jsonrpc_tools_call_unknown_intent_returns_no_handler_error
    # test_handle_jsonrpc_tools_call_handler_failure_returns_jsonrpc_error
    # test_handle_jsonrpc_unknown_method_returns_method_not_found
    # test_handle_jsonrpc_invalid_params_returns_minus_32602
    # test_handle_jsonrpc_registers_peer_on_first_tools_call
    # test_handle_jsonrpc_records_outcome_on_each_tools_call


class TestProbationaryTrustWiring:
    """AD-480g: ~6 tests."""
    # test_first_registration_calls_create_with_prior_with_alpha_1_beta_3
    # test_repeat_registration_does_not_re_call_create_with_prior
    # test_record_outcome_success_increases_alpha
    # test_record_outcome_failure_increases_beta
    # test_destructive_intent_requires_consensus_regardless_of_trust
    # test_config_overrides_default_alpha_beta


class TestFederationRouterPolymorphism:
    """AD-480f: ~6 tests."""
    # test_select_peers_keeps_existing_signature
    # test_registry_list_peers_includes_zmq_and_mcp_and_a2a
    # test_registry_filters_by_protocol
    # test_peers_supporting_intent_filters_by_capability
    # test_zmq_peer_auto_registered_on_gossip_path
    # test_external_peer_appears_alongside_zmq_in_listings


class TestFederationConfigSchema:
    """AD-480h: ~4 tests."""
    # test_mcp_server_config_default_disabled
    # test_a2a_config_default_disabled_with_default_port
    # test_peer_trust_config_default_alpha_1_beta_3
    # test_a2a_outbound_peers_validates_url_field


class TestSlashFederationPeersCommand:
    """AD-480i: ~6 tests."""
    # test_no_arg_renders_existing_panel
    # test_peers_arg_renders_peers_panel
    # test_peers_panel_empty_when_registry_empty
    # test_peers_panel_lists_zmq_and_mcp_and_a2a_peers
    # test_peers_panel_shows_trust_score
    # test_invalid_subcommand_falls_back_to_default_panel


class TestStartupWiring:
    """Smoke test that disabled-by-default config does not start servers (~6 tests)."""
    # test_default_config_skips_mcp_server_start
    # test_default_config_skips_a2a_server_start
    # test_mcp_server_enabled_attempts_start
    # test_a2a_server_enabled_attempts_start
    # test_runtime_federation_peer_registry_initialized_eagerly
    # test_zmq_only_deployment_unchanged_behavior
```

Use `httpx.MockTransport` for client tests. Use direct method invocation (not uvicorn loop) for server tests — call `handle_jsonrpc(payload, ...)` and `handle_agent_card_request()` directly. Use a stub runtime with stub `intent_bus.broadcast`, stub `decomposer._intent_descriptors`, stub `trust_network`, stub `identity_registry`. The pattern is established by `tests/test_ad449_mcp_bridge.py`.

## Section 11 — Standing orders / docs

### 11.1 Append to `config/standing_orders/federation.md`

After the existing "## Mobility & Memory Portability (AD-443)" section (Wave 87 addendum), append:

```markdown
## Cross-Ecosystem Federation (AD-480)

ProbOS speaks three federation protocols:

- **ZeroMQ** — intra-Nooplex transport. ProbOS-to-ProbOS only. Existing.
- **MCP** — tool-boundary transport. External MCP clients invoke ProbOS capabilities; ProbOS invokes external MCP tools (already shipped at AD-449). New at AD-480: ProbOS-as-server.
- **A2A** — agent-boundary transport. External A2A agents collaborate with ProbOS agents and vice versa. New at AD-480: both directions.

All three protocols feed the same `IntentBus`. All three respect existing
governance: `IntentDescriptor.requires_consensus=True` triggers the quorum
pipeline regardless of protocol.

External peers (MCP and A2A) start with probationary trust (Beta(α=1, β=3)
prior; E[trust] = 0.25). Trust updates use the same `record_outcome`
machinery as native agents. **Destructive intents from external peers
always require full consensus regardless of accumulated trust.**

The Captain may inspect federated peers via `/federation peers`.
```

### 11.2 Roadmap status flip

In `docs/development/roadmap.md` near line 3211, change the AD-480 status indicator from `*(planned)*` to `*(partial — v1 OSS adapters ship; SSE streaming / inbound OAuth / Hebbian routing / push-notifications deferred to AD-480j/k/l/m)*`.

## What This Does NOT Change

- **No edit to `BaseAgent`, `IntentMessage`, `IntentResult`, `IntentDescriptor`, `TaskDAG`, `acm.py`, `episodic.py`, `consensus`, `trust` (beyond reusing existing methods), `attention`, `dreaming`, `decomposer`, `prompt_builder`, `cognitive/standing_orders.py`, `cognitive/builder.py`, `cognitive/architect.py`, `experience/shell.py` (slash registration unchanged), HXI.**
- **No new `EventType`, no new pool, no new agent, no new Intent, no Hebbian touch, no router transport rewrite (`FederationRouter.select_peers` signature unchanged).**
- **No edit to existing `MCPClient` / `MCPSession` / `MCPBridge` / `MCPToolAdapter` (AD-449 surface preserved verbatim).**
- **No edit to existing `FederationBridge` / `FederationRouter` / `FederationTransport` / `MockFederationTransport` / `NATSFederationTransport` (Phase 9 + Wave 87 surface preserved verbatim).**
- **No new SQLite tables.** Trust scores reuse existing `trust_scores` table. Peer registry is in-memory only (no persistence in v1 — operator-driven re-registration on boot via static config).
- **No new AD numbers minted.** Sub-AD letters a–m are organizational catalog markers only — same convention as AD-481 a–m (Wave 88), AD-443 a–h (Wave 87), AD-474 a–h (Wave 86).
- **vitest unchanged at 306.** No UI surface touched.

## Tracking

- `PROGRESS.md` — Wave 89 entry: AD-480 v1 OSS Federation Protocol Adapters; +~72 tests; closes #74.
- `docs/development/roadmap.md` — flip AD-480 status from `*(planned)*` to `*(partial — v1 OSS adapters ship; ...)*` at line 3211.
- `DECISIONS.md` — append no AD entry (no decision-level architectural change beyond the protocol surface). v1 reuses existing trust + identity + intent-bus contracts.
- `prompts/wave-plan.yaml` — wave 89 entry depends on wave 88, builder_required true, closes #74.

## Acceptance Criteria

1. Pytest count ≥ 11913 (baseline 11843 + 70 floor). Run `pytest tests/test_ad480_federation_mcp_a2a.py -v -n 0` to verify per-class counts.
2. Full parallel gate: `pytest tests/ -q -n 4 --dist=loadfile` passes with no new failures.
3. Vitest unchanged at 306 (`cd ui && npx vitest run`).
4. `python -c "import probos.federation.mcp_server, probos.federation.a2a, probos.federation.peer"` succeeds.
5. `python -c "from probos.config import FederationMCPServerConfig, FederationA2AConfig, FederationPeerTrustConfig, A2APeerConfig"` succeeds.
6. With default config, runtime boot is unchanged — no MCP server or A2A server started, no port bound, no behavior change for single-node or ZeroMQ-only deployments.
7. With `federation.mcp_server.enabled = True` and `federation.a2a.enabled = True` in config, both servers start; `curl http://127.0.0.1:8766/.well-known/agent.json` returns the live `AgentCard`.
8. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`** (SOLID, three-tier exception handling, cloud-ready storage via existing patterns, type annotations on public APIs, structured logging, async hygiene, test isolation, no layer violations).
9. Pre-commit hook passes (no banned-pattern literals across any committed file).

## Verified Against Codebase (2026-05-06)

```
git rev-parse HEAD
  03937cb

# Substrate already shipped (verified, reused):
grep -n "JSONRPC_VERSION\|MCP_PROTOCOL_VERSION" src/probos/integrations/mcp_bridge/client.py
  22: JSONRPC_VERSION = "2.0"
  23: MCP_PROTOCOL_VERSION = "2025-03-26"
grep -n "class MCPClient\|class MCPSession\|class MCPBridge\|class MCPToolAdapter" src/probos/integrations/mcp_bridge/
  client.py:31:   class MCPClient:
  session.py:9:   class MCPSession:
  bridge.py:14:   class MCPBridge:
  adapter.py:11:  class MCPToolAdapter:
grep -n "MCP_BRIDGE_INVOKE\|MCP_BRIDGE_FAILED" src/probos/events.py
  243: MCP_BRIDGE_INVOKE = "mcp_bridge_invoke"  # AD-449
  244: MCP_BRIDGE_FAILED = "mcp_bridge_failed"  # AD-449

# Federation transport (verified, untouched):
grep -n "class FederationBridge" src/probos/federation/bridge.py
  24: class FederationBridge:
grep -n "class FederationRouter\|def select_peers" src/probos/federation/router.py
  14: class FederationRouter:
  29: def select_peers(self, intent_name: str, available_peers: list[str]) -> list[str]:
grep -n "class FederationMessage" src/probos/types.py
  664: class FederationMessage:

# IntentBus federated=False loop guard (verified, reused at 480a + 480d):
grep -n "federated=False\|set_federation_handler\|def broadcast" src/probos/mesh/intent.py
  502: if federated and self._federation_fn:
  737: def set_federation_handler(self, fn: Callable) -> None:

# Trust prior method (verified, reused at 480g):
grep -n "def create_with_prior\|def record_outcome\|def get_score" src/probos/consensus/trust.py
  195: def create_with_prior(self, agent_id: AgentID, alpha: float, beta: float) -> None:
  208: def record_outcome(

# IntentDescriptor (verified, projected at 480b):
grep -n "class IntentDescriptor" src/probos/types.py
  609: class IntentDescriptor:
grep -n "_intent_descriptors" src/probos/runtime.py
  2216: intent_count = len(self.decomposer._intent_descriptors)

# Identity surface (verified, used at 480c):
grep -n "def get_ship_certificate\|class ShipBirthCertificate" src/probos/identity.py
  609: def get_ship_certificate(self) -> ShipBirthCertificate | None:
  (ShipBirthCertificate dataclass at line ~196 with vessel_name + ship_did)

# Existing /federation slash (verified, extended at 480i):
grep -n "cmd_federation" src/probos/experience/commands/commands_status.py
  100: async def cmd_federation(runtime: ProbOSRuntime, console: Console, args: str) -> None:
grep -n "render_federation_panel" src/probos/experience/panels.py
  799: def render_federation_panel(federation_status: dict) -> Panel:

# Existing config (verified, extended at 480h):
grep -n "class FederationConfig\|class MCPConfig\|class MCPServerConfig" src/probos/config.py
  797: class FederationConfig(BaseModel):
  1472: class MCPServerConfig(BaseModel):    # AD-449
  1479: class MCPConfig(BaseModel):           # AD-449

# Existing fleet org wiring (verified, extended at Section 7):
grep -n "FederationBridge\|federation_bridge" src/probos/startup/fleet_organization.py
  153: from probos.federation import FederationRouter, FederationBridge
  197: bridge = FederationBridge(

# Greenfield paths (introduced by this prompt):
test -d src/probos/federation/a2a       → GREENFIELD
test -f src/probos/federation/mcp_server.py    → GREENFIELD
test -f src/probos/federation/peer.py    → GREENFIELD
test -f tests/test_ad480_federation_mcp_a2a.py → GREENFIELD

# Pytest baseline:
pytest --collect-only -q tests/ -n 4 --dist=loadfile
  11843 tests collected in 5.79s
```

All concrete claims in this prompt map to one of the verified greps above. The four greenfield paths are introduced by this prompt itself.
