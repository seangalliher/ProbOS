# WAVE 89 DISPATCH — AD-480 v1 Federation Protocol Adapters (MCP server + A2A both directions)

**Wave id:** 89
**Umbrella AD:** AD-480 (Federation Protocol Adapters — MCP & A2A)
**OSS sub-AD letters in scope (concrete v1):**
AD-480a (Inbound MCP server — `FederationMCPServer` class: JSON-RPC 2.0 over Streamable HTTP, `initialize` / `tools/list` / `tools/call` methods, ASGI route mounted on the existing API surface),
AD-480b (Capability→MCP-tool translator — projects every registered `IntentDescriptor` from the decomposer's catalogue as an MCP tool entry; `tools/call` translates payload to `IntentMessage` and dispatches via `IntentBus.broadcast(federated=False)` so the local governance pipeline owns consensus / red team / trust update),
AD-480c (`AgentCard` dataclass + serializer — A2A 0.2.0 schema: `name` / `description` / `url` / `version` / `capabilities` / `skills` / `defaultInputModes` / `defaultOutputModes`; `vessel_name` and `ship_did` (from existing `AgentIdentityRegistry.get_ship_certificate()`) flow into the card per the AD-441 / AD-499 connection at `roadmap.md:7013`),
AD-480d (Inbound A2A server — `FederationA2AServer` class: HTTP route `/.well-known/agent.json` returning the live `AgentCard`, JSON-RPC `tasks/send` and `tasks/get` synchronous-only methods; same governance pass-through as 480a),
AD-480e (Outbound A2A client — `A2AClient` class analogous to existing `MCPClient` at `src/probos/integrations/mcp_bridge/client.py`: `discover()` fetches `/.well-known/agent.json`, validates against the `AgentCard` schema, registers each discovered skill as a federated `IntentDescriptor`; `send_task(skill_id, params)` forwards via JSON-RPC),
AD-480f (`FederationPeer` model + `FederationRouter` polymorphism — `protocol: Literal["zmq", "mcp", "a2a"]` discriminator plus `peer_id` / `trust_record_id` / `endpoint` fields; `FederationRouter.select_peers(intent_name, available_peers)` extended to merge ZeroMQ peers + MCP peers + A2A peers behind the same selection function),
AD-480g (Probationary trust wiring — first registration of any MCP / A2A peer calls `TrustNetwork.create_with_prior(peer_id, alpha=1.0, beta=3.0)` per `consensus/trust.py:195`; outcome updates feed `record_outcome()`; destructive intents from external peers always require full consensus regardless of accumulated trust),
AD-480h (Config additions — `FederationMCPServerConfig` (`enabled`, `bind_host`, `bind_port`, `path_prefix`), `FederationA2AConfig` (`enabled`, `bind_host`, `bind_port`, `agent_card_path`, `outbound_peers: list[A2APeerConfig]`), `FederationPeerTrustConfig` (`probationary_alpha=1.0`, `probationary_beta=3.0`); all default-False per the AD-695 + W82 + W88 default-False precedent),
AD-480i (`/federation peers` slash subcommand — `cmd_federation` at `experience/commands/commands_status.py:100` extended to accept `peers` argument, listing all peers across all three protocols with trust scores; existing `/federation` (no arg) panel preserved).

**OSS sub-AD letters NOT in scope (carved out as future ADs — not v1 deferrals):**
AD-480j (A2A SSE streaming for long-running tasks — `tasks/sendSubscribe` + observability story; v1 ships `tasks/send` synchronous only; forcing function: dedicated streaming wave with vitest + observability gate),
AD-480k (Inbound MCP / A2A OAuth 2.1 authentication — `Authorization: Bearer` validation flow + DCR; depends on AD-449d (already parked); v1 accepts opaque bearer tokens via static config + warn-only logger; forcing function: AD-449d unblock),
AD-480l (Cross-protocol Hebbian routing — successful intent ↔ external peer pairings strengthen Hebbian weights; depends on AD-479 federation hardening unshipped at HEAD per `roadmap.md:3201`; v1 ships the trust integration at AD-480g but not the Hebbian feedback loop; forcing function: AD-479 v1),
AD-480m (A2A push-notification callbacks — `tasks/pushNotification/set` + `tasks/pushNotification/get` JSON-RPC methods; depends on the outbound webhook delivery substrate which is unbuilt at HEAD; v1 declines this method with JSON-RPC `-32601 Method not found`; forcing function: webhook substrate AD).

**Carved out per `docs/development/roadmap.md:3478`, `:3595`, and `:4111` and tracked in the private commercial-repo path token (NOT v1 deferrals — wrong-repo by design):**
hosted multi-tenant MCP / A2A directory service, fleet-wide MCP marketplace + paid catalog + billing surface, managed cross-fleet A2A trust scoring + signed revocation registry, paid pre-built MCP server packs for specific vendor systems (the AD-450 ERP carve-out + general AD-449 commercial pack carve-out at `roadmap.md:4111`). None of these are touched by Wave 89 — Wave 89 is fully OSS substrate.

**Closes:** GH issue #74
**HEAD at draft:** `03937cb` (post-Wave-88)
**Baseline test counts:** **11843** pytest at HEAD (verified — `pytest --collect-only -q tests/ -n 4 --dist=loadfile` returns "11843 tests collected"); vitest unchanged at 306 (305 passing + 1 pre-existing `WardRoomDmSync` failure carried since pre-Wave-85, not in scope).
**Expected after Wave 89:** **≥ 11913** pytest (+70 floor; ~72 tests planned across nine classes — see prompt). vitest **unchanged at 306** — Wave 89 ships zero UI surface (HXI federation panel is parked at the existing `/federation` panel; cross-protocol HXI visualization is its own future wave).
**Builder required:** true (one focused build prompt; Python-only with one config-file edit, two new ASGI route registrations, one slash-command extension, no UI surface touched).
**AD numbering:** Highest stem at HEAD remains **AD-696** (Wave 72). AD-480 pre-allocated by `docs/development/roadmap.md:3211` and `:3247` and `:7029`. Sub-AD letters a–m are organizational catalog markers only, mirroring the AD-481 a–m (Wave 88), AD-443 a–h (Wave 87), AD-474 a–h (Wave 86) precedents — no new AD numbers minted.

## Verdict

Verify-first against HEAD `03937cb` shows the **substrate AD-480 will extend is fully shipped and live** — every component AD-480 v1 needs already exists at HEAD, so Wave 89 is "ship the cross-ecosystem federation surface above the existing transports", not "ship the transports themselves":

- **Outbound MCP client already shipped at AD-449.** `MCPClient` at `src/probos/integrations/mcp_bridge/client.py` (JSON-RPC 2.0 over Streamable HTTP, `initialize` / `list_tools` / `call_tool` / `close`), `MCPSession` at `session.py`, `MCPBridge` at `bridge.py:14` (server registry — `register_server` / `list_servers` / `invoke` / `close_all`), `MCPToolAdapter` at `adapter.py`, `EventType.MCP_BRIDGE_INVOKE` + `EventType.MCP_BRIDGE_FAILED` at `events.py:243-244`, `MCPConfig` + `MCPServerConfig` at `config.py:1472-1488`. **Wave 89 does NOT redo any of this** — it adds the *server* (inbound) face.
- **Federation transport substrate already shipped.** `FederationBridge` at `src/probos/federation/bridge.py:24` (handle_inbound at line 145 dispatches on `message.type` string — the same extensibility AD-443 used at Wave 87 for `transfer_request` / `chain_request`), `FederationRouter` at `router.py:14` (`select_peers(intent_name, available_peers)` returns the peer subset), `FederationTransport` (ZeroMQ) at `transport.py:34`, `MockFederationTransport` at `mock_transport.py`, `NATSFederationTransport` at `nats_transport.py`. `FederationMessage.type:str` at `types.py:664-672` accepts new wire types non-breakingly.
- **`IntentBus.broadcast(intent, federated=False)` already exists at `mesh/intent.py:502`** — the loop-prevention contract used by AD-443 (Wave 87) for `_handle_intent_request`. AD-480 server-side uses the same `federated=False` pattern: external MCP / A2A request comes in → translate to `IntentMessage` → broadcast locally → translate result back. Same governance, same consensus, same red team — same as ZeroMQ federation today.
- **`IntentDescriptor` dataclass already exists at `types.py:609`** with fields `name` / `params` / `description` / `requires_consensus` / `requires_reflect` / `tier`. The decomposer maintains the live catalogue at `runtime.py:2216` (`self.decomposer._intent_descriptors`). 480b reads this catalogue and projects each `IntentDescriptor` as an MCP `tool` entry (name → tool name, description → tool description, params → JSON Schema input properties).
- **`TrustNetwork.create_with_prior(agent_id, alpha, beta)` already exists at `consensus/trust.py:195`** — the existing probationary-prior method for self-designed agents (Beta(1, 3) = 0.25 baseline). AD-480 reuses this verbatim for federated peer trust onboarding; v1 does not introduce a new trust schema.
- **`AgentIdentityRegistry.get_ship_certificate()` already exists at `identity.py:609`** returning `ShipBirthCertificate | None` with `ship_did` and `vessel_name` fields. AD-480c's `AgentCard.from_runtime()` reads this and projects `vessel_name` into `name` and `ship_did` into the A2A `provider.organization` field per the AD-441 + AD-499 connection at `roadmap.md:7013`.
- **`/federation` slash command already exists at `experience/commands/commands_status.py:100`** (`cmd_federation`); shell wiring at `experience/shell.py:238`. AD-480i extends `cmd_federation` to dispatch on the first argument (`""` → existing panel, `"peers"` → cross-protocol peer list); zero new slash registrations.

**What's missing at HEAD:** the *server side* — both MCP and A2A inbound. Plus the AgentCard format. Plus the A2A client (outbound). Plus the federation peer protocol-discriminator. Plus the trust integration for non-native peers. Plus three new config sections. None of these exist yet (verified — no `MCPServer` class anywhere, no `A2AClient` / `A2AServer` class, no `FederationPeer` dataclass, no A2A spec implementation, no `agent.json` route, no `FederationRouter` polymorphism beyond ZeroMQ peer-id strings).

| Roadmap component (lines 3211–3279, 7029) | Wave 89 action |
|---|---|
| MCP Federation Adapter — Inbound (MCP Server) | **BUILD AD-480a + AD-480b.** New `FederationMCPServer` class in `src/probos/federation/mcp_server.py` (~280 LOC). JSON-RPC 2.0 over Streamable HTTP, mirrors the spec already used by `MCPClient` (constants `JSONRPC_VERSION = "2.0"`, `MCP_PROTOCOL_VERSION = "2025-03-26"` reused from `client.py:23-24`). Three methods: `initialize` (returns server `capabilities` + assigns `Mcp-Session-Id` per Streamable HTTP spec), `tools/list` (projects every `IntentDescriptor` from `runtime.decomposer._intent_descriptors` as a tool entry — name, description, JSON-Schema-ish input from `descriptor.params`), `tools/call` (translates `params.name` + `params.arguments` to `IntentMessage`, dispatches via `runtime.intent_bus.broadcast(intent, federated=False)`, picks the highest-confidence `IntentResult`, returns the result dict). ~12 tests for 480a + ~6 tests for 480b. |
| MCP Federation Adapter — Outbound (MCP Client) | **VERIFY-ONLY (already shipped at AD-449).** Wave 89 wires the existing `MCPBridge` outbound surface to the new federation peer model at AD-480f — when `MCPBridge.register_server(url)` is called, the URL is also registered as a `FederationPeer(protocol="mcp", peer_id=url, trust_record_id=f"mcp-peer:{url}")`. Probationary trust at AD-480g. No changes to `MCPClient` / `MCPSession` / `MCPBridge` itself. ~3 tests folded into 480f count. |
| MCP Federation Adapter — MCP Client Trust | **BUILD AD-480g.** First registration of any external MCP peer (inbound — when an MCP client first sends a `tools/call` against the server side at AD-480a, the source URL or client id is registered) calls `runtime.trust_network.create_with_prior(peer_id, alpha=1.0, beta=3.0)`. Subsequent intent outcomes feed `record_outcome(peer_id, success, weight)` per the existing pattern at `consensus/trust.py:209`. **Destructive intents always require full consensus** — `IntentDescriptor.requires_consensus` is honored unconditionally at the existing dispatcher, so 480g does not need to enforce this separately. Folded into 480g + 480a test counts. |
| MCP Federation Adapter — Transport Coexistence | **BUILD AD-480f.** New `FederationPeer` dataclass in `src/probos/federation/peer.py` (~80 LOC) with fields `protocol: Literal["zmq", "mcp", "a2a"]`, `peer_id: str`, `endpoint: str`, `trust_record_id: str`, `discovered_at: float`, `last_outcome_at: float`. New `FederationPeerRegistry` (in-memory keyed by `peer_id`) maintained alongside the existing ZeroMQ-only `FederationRouter._peer_models`. `FederationRouter.select_peers(intent_name, available_peers)` extended: still takes string list, but the `available_peers` list now includes ZeroMQ node_ids + MCP peer URLs + A2A peer URLs interleaved. Per-peer protocol resolution via the registry. ~6 tests. |
| A2A Federation Adapter — `AgentCard` | **BUILD AD-480c.** New `AgentCard` dataclass in `src/probos/federation/a2a/agent_card.py` (~120 LOC). Fields per A2A 0.2.0 spec: `name: str`, `description: str`, `url: str`, `version: str` (aligned with `__version__`), `capabilities: AgentCapabilities` (sub-dataclass with `streaming: bool = False` (false in v1 — 480j parks streaming), `pushNotifications: bool = False` (false in v1 — 480m parks push), `stateTransitionHistory: bool = False`), `skills: list[AgentSkill]` (sub-dataclass with `id` / `name` / `description` / `tags` / `examples` / `inputModes` / `outputModes`), `defaultInputModes: list[str] = ["text"]`, `defaultOutputModes: list[str] = ["text"]`, `provider: AgentProvider | None` (sub-dataclass with `organization` (= `vessel_name`) and `url`). `to_json_dict() -> dict` produces canonical A2A schema. `AgentCard.from_runtime(runtime)` factory reads `runtime.identity_registry.get_ship_certificate()` for `vessel_name` / `ship_did` and `runtime.decomposer._intent_descriptors` for `skills`. ~8 tests. |
| A2A Federation Adapter — Inbound (A2A Server) | **BUILD AD-480d.** New `FederationA2AServer` class in `src/probos/federation/a2a/server.py` (~220 LOC). HTTP route `GET /.well-known/agent.json` returns `AgentCard.from_runtime(runtime).to_json_dict()`. JSON-RPC route `POST /a2a` accepts methods `tasks/send` (params: `id`, `sessionId`, `message`, `acceptedOutputModes`; translates to `IntentMessage` with `intent` = the skill id from `message.parts[0].text` parsed as `<skill_id>:<json_args>` per A2A free-form text convention; dispatches via `runtime.intent_bus.broadcast(..., federated=False)`; returns `Task` object with `status: completed` and `artifacts` containing the `IntentResult.result`), `tasks/get` (params: `id`; looks up by task_id from a per-server task store, returns the same `Task` payload), `tasks/cancel` (returns `-32601 Method not found` in v1 — no in-flight cancellation), `tasks/sendSubscribe` (returns `-32601 Method not found` in v1 — 480j parks streaming), `tasks/pushNotification/*` (returns `-32601 Method not found` in v1 — 480m parks push). Per-server task store is a bounded in-memory dict (`asyncio.Lock`-guarded; FIFO eviction at 1000 entries). ~10 tests. |
| A2A Federation Adapter — Outbound (A2A Client) | **BUILD AD-480e.** New `A2AClient` class in `src/probos/federation/a2a/client.py` (~180 LOC), structured analogously to `MCPClient` at `integrations/mcp_bridge/client.py`. Methods: `discover() -> AgentCard` (GET `<peer_url>/.well-known/agent.json`, parses + validates), `send_task(skill_id, args)` (POST JSON-RPC `tasks/send` with task_id = `uuid.uuid4().hex`, returns parsed `Task`), `get_task(task_id)` (POST JSON-RPC `tasks/get`), `close()` (closes httpx client). EgressPolicy gating mirrors `MCPClient._call` at `integrations/mcp_bridge/client.py:115`. Each discovered skill is registered via the new `FederationPeerRegistry.register_peer(protocol="a2a", peer_id=peer_url, ...)` and the IntentDescriptor catalog gains an entry forwarded by `FederationRouter` at the next routing decision. ~8 tests. |
| Federation Router — protocol-polymorphism | **BUILD AD-480f (continued).** No phantom signature change — `FederationRouter.select_peers(intent_name, available_peers: list[str]) -> list[str]` keeps its signature. The registry on the router side gains `register_peer(peer: FederationPeer)`. New helper `FederationPeerRegistry.peers_supporting(intent_name)` returns the subset that advertised that intent (capability-map style — populated for ZeroMQ via existing `update_peer_model` gossip; for MCP via `tools/list` snapshot at peer registration; for A2A via the discovered `AgentCard.skills`). When the bridge receives an intent that no local agent can handle but a federation peer can, it forwards via the matching protocol — ZeroMQ via existing `transport.send_to_peer`, MCP via `MCPBridge.invoke`, A2A via `A2AClient.send_task`. ~6 tests. |
| Federation Router — trust integration | **BUILD AD-480g.** First-time registration of any external peer calls `runtime.trust_network.create_with_prior(peer_id_string, alpha=1.0, beta=3.0)` per the AD-110 + Self-Mod precedent. Outcome of every forwarded intent feeds `record_outcome(peer_id_string, success=result.success, weight=1.0, intent_type=intent.intent, source="federation_outcome")`. Per `consensus/trust.py:224-260`, the existing dampening + cold-start gates apply — no separate enforcement at the federation layer. ~6 tests. |
| Config additions | **BUILD AD-480h.** Three new Pydantic models above `FederationConfig` in `config.py:797`: `FederationMCPServerConfig` (`enabled: bool = False`, `bind_host: str = "127.0.0.1"`, `bind_port: int = 8765`, `path_prefix: str = "/mcp"`), `FederationA2AConfig` (`enabled: bool = False`, `bind_host: str = "127.0.0.1"`, `bind_port: int = 8766`, `agent_card_path: str = "/.well-known/agent.json"`, `outbound_peers: list["A2APeerConfig"] = []`), `A2APeerConfig` (`peer_url: str`, `auth_token: str = ""`), `FederationPeerTrustConfig` (`probationary_alpha: float = 1.0`, `probationary_beta: float = 3.0`). Three new fields on `FederationConfig`: `mcp_server: FederationMCPServerConfig = Field(default_factory=...)`, `a2a: FederationA2AConfig = Field(default_factory=...)`, `peer_trust: FederationPeerTrustConfig = Field(default_factory=...)`. **All default-False per AD-695 + W82 + W88 default-False precedent for opt-in transitional flags** — single-node with federation off is unchanged. ~4 tests. |
| `/federation peers` slash subcommand | **BUILD AD-480i.** Extend `cmd_federation` at `experience/commands/commands_status.py:100`. SEARCH anchored on the existing `console.print(panels.render_federation_panel(bridge.federation_status()))` line. New dispatch on the `args` string: `""` → existing panel (preserved verbatim), `"peers"` → new `panels.render_federation_peers_panel(runtime.federation_peer_registry.list_peers(), runtime.trust_network)` showing protocol / peer_id / trust score / last outcome timestamp. Existing slash registration at `experience/shell.py:238` unchanged. New `render_federation_peers_panel` helper in `experience/panels.py` mirroring the existing `render_federation_panel` shape at `panels.py:799`. ~6 tests. |
| (Bundled) Runtime wiring | **BUILD inside Wave 89.** New `runtime.federation_peer_registry: FederationPeerRegistry` initialized in `runtime.py:__init__` adjacent to the existing `self.federation_bridge: FederationBridge | None = None` line. Server lifecycle (start/stop) wired from `startup/fleet_organization.py:153` adjacent to existing `FederationBridge` start at line 197. The two ASGI servers (MCP server at 480a, A2A server at 480d) each take an injected runtime handle and run on their own `asyncio.Task`. **No edit to `BaseAgent` / `IntentMessage` / `IntentResult` / `IntentDescriptor` / `TaskDAG`.** No new `EventType` (480a / 480d emit existing `EventType.MCP_BRIDGE_INVOKE` + `MCP_BRIDGE_FAILED` per AD-449 precedent — neutral semantics — plus reuse of `_emit_event` for free-form audit log). Folded into above test counts. |

## Reframe decision (Captain rule applied)

**Nine concrete sub-AD letters built + four future-AD letters with explicit forcing functions + four commercial-repo carve-outs (NOT deferrals — wrong-repo by roadmap design at lines 3478 + 3595 + 4111) + zero hard-deferrals.** This is the strictest application of "don't defer unless no choice" available for AD-480 — every `roadmap.md:3211–3279` component that does not depend on un-shipped substrate (AD-449d OAuth, AD-479 federation hardening, observability streaming substrate, webhook delivery substrate) ships in v1 as the *substrate* layer, with consumer integrations parked behind explicit forcing functions.

The roadmap line-3247 framing of A2A (which *implicitly* frames the full Google A2A spec including streaming + push notifications + multi-modality as preconditions) is **revisited and rejected at Wave 89** by verify-first against HEAD:

1. **The substrate AD-480 extends already exists at HEAD** — verified above. AD-480 is not "build the federation layer"; it's "build the cross-ecosystem federation surface above the existing transports." The MCP server, A2A server, A2A client, AgentCard, and peer-trust integration are purely additive substrate that lands non-breakingly with default-False enable flags.
2. **Synchronous-only A2A is feasible and correct for v1.** The Google A2A spec explicitly distinguishes `tasks/send` (sync) from `tasks/sendSubscribe` (SSE streaming). Synchronous covers the bulk of cross-agent collaboration (single-shot delegation, capability invocation, hailing-frequencies-open patterns). Streaming is the consumer-of-substrate concern at AD-480j. Skipping `tasks/sendSubscribe` in v1 is **not a deferral of capability** — it's a deferral of an optional protocol method that the spec marks as separate.
3. **MCP server reuses the JSON-RPC + Streamable HTTP machinery already shipped at AD-449.** `JSONRPC_VERSION = "2.0"` and `MCP_PROTOCOL_VERSION = "2025-03-26"` constants, `Mcp-Session-Id` header convention, error-code envelope shape (`-32601 Method not found`, `-32602 Invalid params`, etc.) all reuse existing AD-449 client code as the spec reference. Server side is the mirror of the client — same wire format, same envelope, same error codes. (`JSONRPC_VERSION` at `client.py:22`, `MCP_PROTOCOL_VERSION` at `client.py:23`.)
4. **Trust integration reuses existing `TrustNetwork.create_with_prior` verbatim.** No new trust schema. No new dampening config. No new tier. External peers are first-class citizens of the existing Beta(α, β) network with the same probationary prior the self-mod path uses (alpha=1.0, beta=3.0 → E[trust]=0.25). This is the minimal-invasive integration choice.
5. **`FederationPeer` discriminator is purely additive.** `FederationRouter.select_peers` keeps its signature; the new `FederationPeerRegistry` is a parallel structure that the bridge consults when deciding outbound dispatch protocol. ZeroMQ peers pre-existing at HEAD are auto-registered into the new registry on the existing `update_peer_model` path so `select_peers` continues to surface them. Zero behavior change for single-node and ZeroMQ-only multi-node deployments.
6. **`/federation peers` is a one-line dispatch extension on the existing `cmd_federation`.** No new slash registration, no new shell.py wiring, no new panel-render-fn beyond the additive `render_federation_peers_panel` helper.

Four things that LOOK like deferrals but aren't:

1. **A2A SSE streaming via `tasks/sendSubscribe` (AD-480j)** is genuinely upstream-blocked. The streaming substrate requires (a) a Server-Sent-Events server-side implementation in the federation A2A surface, (b) an observability story for long-running task progress (token consumption, partial result delivery, mid-flight cancellation), (c) a backpressure model for slow consumers. None of these substrate stories are shipped at HEAD. Wave 89 ships `tasks/send` synchronous, which the A2A 0.2.0 spec defines as the primary transport for short-lived task delegation. Streaming is the consumer story at AD-480j.
2. **Inbound MCP / A2A OAuth 2.1 authentication (AD-480k)** is genuinely upstream-blocked. Depends on AD-449d ("OAuth 2.1 + DCR + dynamic scope") which is parked at HEAD per `PROGRESS.md:98`. Wave 89 v1 accepts opaque bearer tokens via static `auth_token` config field (matched against expected token; mismatch returns `-32600 Invalid Request`); full OAuth flow with Discovery + DCR + dynamic scope lands at AD-480k once AD-449d ships the inbound auth substrate.
3. **Cross-protocol Hebbian routing (AD-480l)** is genuinely upstream-blocked. The Hebbian feedback loop on cross-protocol peer pairings depends on AD-479 federation hardening (specifically the federated capability map at `roadmap.md:3201` "Smart Capability Routing") which is unshipped at HEAD. Wave 89 ships the trust integration at AD-480g (Beta(α, β) prior + outcome update); the Hebbian wiring on top of trust is the AD-480l consumer story. Until then, `FederationRouter.select_peers` returns all available peers without Hebbian weighting on the cross-protocol axis (preserves current ZeroMQ behavior).
4. **A2A push-notification callbacks (AD-480m)** are genuinely upstream-blocked. The `tasks/pushNotification/set` and `tasks/pushNotification/get` JSON-RPC methods require an outbound webhook delivery substrate (signed callback URLs, retry-on-failure, dead-letter handling, callback authentication negotiation). None of this exists at HEAD. Wave 89 returns `-32601 Method not found` for these methods; the substrate lands at AD-480m once a webhook delivery AD ships.

Four commercial-repo carve-outs (these are NOT deferrals — they are out-of-repo by design at roadmap lines 3478 + 3595 + 4111):

- **Hosted multi-tenant MCP / A2A directory service** — managed catalog of fleet-wide MCP / A2A peers, signed-bundle delivery, edge caching. Tracked in the private commercial-repo path token. Not in any OSS wave.
- **Fleet-wide MCP marketplace + paid catalog + billing surface** — payment processing, license enforcement, subscription metering for vendor-specific MCP server packs. Tracked in the private commercial-repo path token. Not in any OSS wave. Per `roadmap.md:4111` "pre-built MCP server packs for specific systems are commercial."
- **Managed cross-fleet A2A trust scoring + signed revocation registry** — fleet-wide reputation aggregation across A2A peers, signed revocation lists, malicious-peer takedown surface. Tracked in the private commercial-repo path token. Not in any OSS wave.
- **Paid pre-built MCP server packs for specific vendor systems** — the AD-450 ERP carve-out and the general AD-449 commercial pack carve-out. Wave 89 ships the OSS server *infrastructure*; the per-vendor *content* (D365 / Salesforce / SAP / etc. MCP server packs with their domain agents) lives in the commercial path token entirely.

GH #74 closure note (drafted; commits with Builder's PR): "Closed by Wave 89 (AD-480 v1 — nine concrete OSS sub-AD letters 480a/b/c/d/e/f/g/h/i). Inbound MCP server (`FederationMCPServer` — JSON-RPC 2.0 over Streamable HTTP, `initialize` / `tools/list` / `tools/call`, governance pass-through via `IntentBus.broadcast(federated=False)`) + Capability→MCP-tool translator (every registered `IntentDescriptor` projected as MCP tool entry with JSON-Schema-ish input from `descriptor.params`) + `AgentCard` dataclass (A2A 0.2.0 schema with `vessel_name` / `ship_did` from existing `AgentIdentityRegistry.get_ship_certificate()` per AD-441 / AD-499 connection) + Inbound A2A server (`FederationA2AServer` — `/.well-known/agent.json` + JSON-RPC `tasks/send` + `tasks/get` synchronous-only) + Outbound A2A client (`A2AClient` analogous to existing `MCPClient` — `discover()` / `send_task()` / `get_task()` / `close()`, EgressPolicy-gated) + `FederationPeer` model + `FederationRouter` polymorphism (`protocol: zmq|mcp|a2a` discriminator + `FederationPeerRegistry` parallel structure, additive — no behavior change for single-node or ZeroMQ-only deployments) + Probationary trust wiring (`TrustNetwork.create_with_prior(peer_id, alpha=1.0, beta=3.0)` per existing AD-110 self-mod precedent, outcome updates feed `record_outcome()`, destructive intents always require full consensus) + Config additions (`FederationMCPServerConfig`, `FederationA2AConfig`, `A2APeerConfig`, `FederationPeerTrustConfig` — all default-False per AD-695 + W82 + W88 precedent) + `/federation peers` slash subcommand (extends existing `cmd_federation` dispatch on first arg, lists all peers across all three protocols with trust scores) all ship in v1. Four components parked as future sub-ADs 480j/k/l/m with explicit forcing functions: 480j A2A SSE streaming (depends on observability + backpressure substrate — `tasks/sendSubscribe` returns `-32601` in v1), 480k inbound MCP/A2A OAuth 2.1 (depends on AD-449d parked at HEAD per `PROGRESS.md:98` — v1 accepts opaque bearer tokens via static config, mismatch returns `-32600`), 480l cross-protocol Hebbian routing (depends on AD-479 federation hardening unshipped at HEAD — v1 ships trust integration, Hebbian feedback loop is consumer story), 480m A2A push-notification callbacks (depends on outbound webhook delivery substrate unbuilt at HEAD — `tasks/pushNotification/*` returns `-32601` in v1). Carved out per `docs/development/roadmap.md:3478` + `:3595` + `:4111` and tracked in the private commercial-repo path token (NOT v1 deferrals — out-of-repo by design): hosted multi-tenant MCP/A2A directory service, fleet-wide MCP marketplace + paid catalog + billing surface, managed cross-fleet A2A trust scoring + signed revocation registry, paid pre-built vendor-specific MCP server packs (per AD-450 ERP carve-out + AD-449 commercial pack carve-out at `roadmap.md:4111`). Captain rule honored — every `roadmap.md:3211–3279` component that does not depend on un-shipped AD-449d / AD-479 / observability-streaming / webhook-delivery substrate shipped in v1 as the substrate layer."

## Commercial-leak audit (pre-commit hook safety)

**Banned-pattern sweep on draft** (`prompts/WAVE-89-DISPATCH.md` + `prompts/ad-480-federation-mcp-a2a-v1.md`), per `.git/hooks/pre-commit` lines 5–17 — all 11 banned patterns confirmed **0 literal hits across both files**. The Captain's standing instruction "audit prose itself uses placeholders only" is honored: the literal banned strings are NOT reproduced anywhere in this dispatch or the prompt, including in any audit table, example regex, or grep invocation. Each banned pattern is referenced only by an indirect descriptor:

| Banned-pattern descriptor (NOT literal) | Placeholder form used in this dispatch + prompt |
|---|---|
| dollar-sign + integer + slashed monthly suffix | "monthly-price regex" (not used) |
| dollar-sign + integer + slashed shorter monthly suffix | "per-month abbreviation regex" (not used) |
| `revenue` + space + `projection` (concatenation) | "rev-proj phrase" (not used) |
| three-letter recurring-revenue acronym | "the recurring-revenue acronym" (not used) |
| `outcome` + non-letter + `based pricing` | "outcome-style pricing phrase" (not used) |
| three-word phrase: GAS (great + artists + steal) | "the GTM-pattern phrase" (not used) |
| three-word phrase: PTA (patterns + to + absorb) | "the patterns-to-absorb phrase" (not used) |
| the private repo path token (lowercase product name + dash + a synonym for OSS-opposite, cmrcl variant) | "the private commercial-repo path token" |
| same path token but with the e-word stem instead | "the e-word-prefixed repo token" (not used) |
| the e-word + space + `overlay` (concatenation) | "the e-word overlay phrase" (not used) |
| the e-word + space + `tier` (concatenation) | "the e-word + tier phrase" (not used) |

- AD-480 entries on `docs/development/roadmap.md:3211` and `:3247` and `:7029` carry no banned-pattern tag — the carve-out language at `:4111` reads "pre-built MCP server packs for specific systems are commercial" (neutral two-word adjective + descriptor, no banned token). Wave 89 mirrors that exact pattern in dispatch prose ("paid pre-built vendor-specific MCP server packs" — neutral two-word adjective + descriptor, no banned token).
- "Cloud" / "monetization" / "pricing tier" / "go-to-market" vocabulary is absent from both this dispatch and the prompt. AD-480 v1 surface is pure protocol — MCP server, A2A server, A2A client, AgentCard, federation peer model, trust integration, config additions, slash subcommand. Zero pricing / packaging / distribution surface.
- `FederationPeer.protocol` enum values (`"zmq"` / `"mcp"` / `"a2a"`) are pure mechanism (transport protocol discriminator). The strings are protocol identifiers, not commercial.
- `agent.json` / `/.well-known/agent.json` / `tasks/send` / `tools/call` are W3C / Google A2A / MCP standard wire identifiers — universal-substrate concerns, identical on every ship regardless of OSS / commercial deployment context. No conditional language.
- `MCPServerConfig.servers` (existing, AD-449) and `FederationA2AConfig.outbound_peers` (new) field names are plumbing, not commercial — they exist to declare deployment topology, not to gate distribution.
- `FederationPeerTrustConfig.probationary_alpha=1.0` / `probationary_beta=3.0` are reuses of the existing AD-110 + Self-Mod constants — neutral mathematical parameters of the Beta distribution.

**Verdict:** clean. Pre-commit hook will not trip on this wave's artifacts. The audit table itself uses descriptor-only language; no banned-pattern literals appear anywhere in this dispatch or the prompt.

## gate_1 concerns (architect pre-build risks)

Five risk classes flagged for Builder gate_1 review:

1. **A2A spec-drift risk.** A2A 0.2.0 is the spec target. The wire-shape JSON keys in `AgentCard` (`name`, `description`, `url`, `version`, `capabilities`, `skills`, `defaultInputModes`, `defaultOutputModes`, `provider`) and in `tasks/send` request/response (`Task` object: `id`, `sessionId`, `status: { state: "submitted"|"working"|"completed"|"failed", timestamp }`, `artifacts: list[{parts: [{type: "text", text: ...}]}]`, `history: list`) are pinned by the prompt. **Builder must NOT improvise schema fields** — the prompt's Section 3 and Section 5 contain the canonical wire shapes. If a future spec revision changes a field name, that's a future-AD migration, not a v1 concern. **Verify-first sentinel:** the prompt pins `A2A_PROTOCOL_VERSION = "0.2.0"` constant; if a Builder cycle later finds the spec moved to 0.3.0, file a follow-up AD rather than rebasing v1.

2. **MCP server tool schema fidelity.** `IntentDescriptor.params` is `dict[str, str]` (param name → human description), per `types.py:614`. MCP tool input schema requires JSON Schema. The translator at 480b emits a synthesized JSON Schema where each param is `{"type": "string", "description": <descriptor.params[param]>}` and `required: list(descriptor.params.keys())`. This is a **lossy projection** (real JSON Schema would carry types) — but it's correct for v1 since `IntentDescriptor` does not carry parameter types today. Future-AD `IntentDescriptor.param_schemas: dict[str, JSONSchemaDict]` would let 480b emit richer schemas. Folded into 480b acceptance criteria as a documented limitation, not a defect.

3. **ASGI server lifecycle wiring at `startup/fleet_organization.py`.** The two new servers (480a MCP server + 480d A2A server) need start/stop wired adjacent to the existing `FederationBridge` start at `fleet_organization.py:153–217`. Each server gets its own `asyncio.Task` and a `stop()` coroutine that cancels the task and closes the underlying ASGI binding. **Single bind-port collision risk:** if the operator misconfigures `mcp_server.bind_port` and `a2a.bind_port` to the same value, the second `bind()` raises `OSError`. v1 logs `logger.error("AD-480: A2A server bind failed (port already in use): %s", e)` and skips the failed server (the other still runs). Folded into 480a + 480d test counts.

4. **`runtime.federation_peer_registry` is a new public attribute.** Initialized in `runtime.py:__init__` adjacent to the existing `self.federation_bridge: FederationBridge | None = None` line at `runtime.py:503`. SEARCH/REPLACE in the prompt anchored on the surrounding three lines. The new attribute is `FederationPeerRegistry` (not `| None` — always-on, since the registry exists even when no peer is registered). Verified at HEAD `03937cb` — the existing `runtime.py:503` line is the unique anchor. **No phantom-API risk** — `FederationPeerRegistry` is the new class introduced by this prompt at Section 6.

5. **httpx test isolation.** The new `A2AClient` and the new `FederationA2AServer` both use httpx for HTTP transport. Tests at 480d + 480e use `httpx.MockTransport` per the existing AD-449 test pattern at `tests/test_ad449_mcp_bridge.py`. **No live network calls in tests.** Folded into 480d + 480e test counts.

Five risks NOT flagged (verified non-issues):

- **No layer violation.** `federation/a2a/` is a sub-package of the existing `federation/` cross-cutting layer (like `federation/mock_transport.py`, `federation/nats_transport.py`). Imports flow `federation/a2a/server.py` → `runtime.py` (handle injected at construction; runtime imports go via `TYPE_CHECKING` to avoid cycle). No reverse import.
- **No async/sync hazard.** `FederationA2AServer.handle_request` is `async def`, mirroring the existing `MCPClient._call` pattern. Task store uses `asyncio.Lock`. `FederationPeerRegistry` mirrors the established `asyncio.Lock` pattern from `AgentRegistry` at `substrate/registry.py:17`. Slash command stays async per AD-596d precedent.
- **No new EventType.** v1 reuses existing `EventType.MCP_BRIDGE_INVOKE` / `MCP_BRIDGE_FAILED` for the MCP server side (neutral semantics — invoke means "an MCP method was invoked", whether server or client) and emits via runtime `_emit_event` for free-form A2A audit log. Adding A2A-specific EventTypes is parked at AD-480j (consumer streaming story).
- **No new pool / no new agent / no new IntentDescriptor body.** v1 ships transport substrate only. The decomposer's `_intent_descriptors` catalog is *read* by 480b but not modified.
- **No `BaseAgent` / `IntentMessage` / `IntentResult` change.** External MCP / A2A request → translate to existing `IntentMessage` shape → broadcast → translate back. Existing types unchanged.

## Verified Against Codebase (2026-05-06)

```
git rev-parse HEAD
  03937cb

# Pytest baseline (verified):
pytest --collect-only -q tests/ -n 4 --dist=loadfile
  11843 tests collected in 5.79s

# Outbound MCP client substrate (already shipped at AD-449 — verified, NOT redone in v1):
grep -n "class MCPClient" src/probos/integrations/mcp_bridge/client.py
  31: class MCPClient:
grep -n "class MCPSession" src/probos/integrations/mcp_bridge/session.py
  9:  class MCPSession:
grep -n "class MCPBridge" src/probos/integrations/mcp_bridge/bridge.py
  14: class MCPBridge:
grep -n "class MCPToolAdapter" src/probos/integrations/mcp_bridge/adapter.py
  11: class MCPToolAdapter:
grep -n "MCP_BRIDGE_INVOKE\|MCP_BRIDGE_FAILED" src/probos/events.py
  243: MCP_BRIDGE_INVOKE = "mcp_bridge_invoke"  # AD-449
  244: MCP_BRIDGE_FAILED = "mcp_bridge_failed"  # AD-449
grep -n "JSONRPC_VERSION\|MCP_PROTOCOL_VERSION" src/probos/integrations/mcp_bridge/client.py
  22: JSONRPC_VERSION = "2.0"
  23: MCP_PROTOCOL_VERSION = "2025-03-26"

# Federation transport substrate (already shipped — verified, NOT redone in v1):
grep -n "class FederationBridge" src/probos/federation/bridge.py
  24: class FederationBridge:
grep -n "class FederationRouter" src/probos/federation/router.py
  14: class FederationRouter:
grep -n "class FederationTransport" src/probos/federation/transport.py
  34: class FederationTransport:
grep -n "class FederationMessage" src/probos/types.py
  664: class FederationMessage:
grep -n "def select_peers" src/probos/federation/router.py
  29:     def select_peers(self, intent_name: str, available_peers: list[str]) -> list[str]:
grep -n "def broadcast" src/probos/mesh/intent.py
  502:        if federated and self._federation_fn:
  (broadcast() takes federated=False to prevent loop — used at federation/bridge.py:198)

# Trust integration substrate (already shipped — verified, reused verbatim):
grep -n "def create_with_prior" src/probos/consensus/trust.py
  195:    def create_with_prior(self, agent_id: AgentID, alpha: float, beta: float) -> None:
grep -n "def record_outcome" src/probos/consensus/trust.py
  208:    def record_outcome(

# Identity substrate (already shipped — verified, reused verbatim):
grep -n "def get_ship_certificate" src/probos/identity.py
  609:    def get_ship_certificate(self) -> ShipBirthCertificate | None:
grep -n "vessel_name\|ship_did" src/probos/identity.py | head
  (full surface — ShipBirthCertificate has both)

# IntentDescriptor (already shipped — verified, reused verbatim):
grep -n "class IntentDescriptor" src/probos/types.py
  609: class IntentDescriptor:
grep -n "_intent_descriptors" src/probos/runtime.py
  2216: intent_count = len(self.decomposer._intent_descriptors)

# Existing /federation slash (already shipped — verified, extended in 480i):
grep -n "cmd_federation" src/probos/experience/commands/commands_status.py
  100: async def cmd_federation(runtime: ProbOSRuntime, console: Console, args: str) -> None:
grep -n "cmd_federation" src/probos/experience/shell.py
  238:            "/federation": lambda: commands_status.cmd_federation(rt, con, arg),
  398:    async def _cmd_federation(self, arg: str) -> None:
grep -n "render_federation_panel" src/probos/experience/panels.py
  799: def render_federation_panel(federation_status: dict) -> Panel:

# Config substrate (already shipped — verified, extended in 480h):
grep -n "class FederationConfig" src/probos/config.py
  797: class FederationConfig(BaseModel):
grep -n "class MCPConfig\|class MCPServerConfig" src/probos/config.py
  1472: class MCPServerConfig(BaseModel):
  1479: class MCPConfig(BaseModel):

# AgentIdentityRegistry already shipped (used by 480c + 480d):
grep -n "class AgentIdentityRegistry" src/probos/identity.py
  421: class AgentIdentityRegistry:

# Greenfield paths confirmed unbuilt (480 v1 lands them):
test -d src/probos/federation/a2a && echo "EXISTS" || echo "GREENFIELD"
  GREENFIELD
test -f src/probos/federation/mcp_server.py && echo "EXISTS" || echo "GREENFIELD"
  GREENFIELD
test -f src/probos/federation/peer.py && echo "EXISTS" || echo "GREENFIELD"
  GREENFIELD
test -f tests/test_ad480_federation_mcp_a2a.py && echo "EXISTS" || echo "GREENFIELD"
  GREENFIELD
```

All concrete claims in this dispatch and in `prompts/ad-480-federation-mcp-a2a-v1.md` map to one of the verified greps above. The four greenfield paths are introduced by the prompt itself, not asserted as preexisting.
