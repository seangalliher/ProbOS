# WAVE 102 DISPATCH — AD-597 v1 MCP App Host Infrastructure + Interactive Games (closes #167)

## Wave summary

**Umbrella:** AD-597 — MCP App Host Infrastructure + Interactive Games. Documented at `docs/development/roadmap.md:5026` (`(planned, OSS, depends: AD-526a Recreation Framework, AD-423 Tool Registry)`) and `decisions-era-4-evolution.md:3596` (Era-4 evolution wave). v1 ships the structural surface for **all six** sub-ADs in one Builder cycle: AD-597a HXI MCP App Host (AppBridge + sandboxed iframe + JSON-RPC postMessage), AD-597b ProbOS MCP Server for Games (`registerAppTool` / `registerAppResource` / `resources/read` JSON-RPC method), AD-597c Chess Engine (pure-Python full-rules implementation excluding threefold-repetition draw), AD-597d Chess MCP App UI (vite-singlefile HTML/JS/CSS bundle), AD-597e Tic-Tac-Toe MCP App migration (existing `TicTacToeEngine` rendered via `<McpAppFrame>` plus `GamePanel.tsx` retained as fallback for hosts without AppBridge), AD-597f External MCP App Consumption (discovery via `MCPClient.list_tools()` scanning for `_meta.ui.resourceUri`, new `MCPClient.read_resource()` method, stricter external iframe sandbox flag). The wave reuses the AD-480 inbound-MCP-server pattern (`src/probos/federation/mcp_server.py`) and the AD-449 outbound-MCP-client pattern (`src/probos/integrations/mcp_bridge/`) — both shipped at HEAD `c6f39c8` and architecturally adjacent to what AD-597 needs.

**Wave kind:** Source-modifying single-AD v1 — additive new package `src/probos/mcp_apps/` (~5 modules, ~1900 LOC across registry / chess_engine / game_app / external_discovery / __init__), four new `EventType` values appended to the existing `MCP_BRIDGE_*` cluster in `events.py` (`MCP_APP_TOOL_REGISTERED`, `MCP_APP_RESOURCE_READ`, `MCP_APP_TOOL_INVOKED`, `MCP_APP_EXTERNAL_DISCOVERED`), one new Pydantic config `MCPAppHostConfig` adjacent to `FederationMCPServerConfig`, one new finalize wirer `_wire_mcp_app_host` adjacent to the existing AD-480a federation MCP server start at `startup/finalize.py:2450`. Two new HXI components (`ui/src/components/McpAppFrame.tsx`, `ui/src/mcpApps/bridge.ts`), two MCP App HTML bundles under `src/probos/mcp_apps/bundles/{chess,tictactoe}/index.html` (vite-singlefile). Two new REST endpoints in `src/probos/routers/system.py` (`/api/mcp/jsonrpc` POST forwarding to `runtime.federation_mcp_server.handle_jsonrpc`, `/api/mcp/resource` GET serving `ui://` resources with `_meta.ui.csp` Content-Security-Policy headers). Default-False per AD-695 transitional-flag precedent. Operators flip `mcp_app_host.enabled=True` once `federation.mcp_server.enabled=True` AND a recreation game type is registered.

**Reframe decision — ship full v1 (all six sub-ADs), single forcing-function deferral, NO scope split (Captain rule "don't defer unless no choice" applied):**

The original AD-597 spec at `decisions-era-4-evolution.md:3596` documents an explicit phasing: "597a → 597b → 597c → 597e → 597d → 597f" with the rationale "External MCP App consumption (AD-597f) as final phase | Security-sensitive: external apps run arbitrary HTML in iframes." On second-pass evaluation against HEAD `c6f39c8`, the security gate that made 597f "final phase" turns out to already be solved by infrastructure shipped under AD-449 + AD-480 — the gate translates to ~150 LOC of discovery + sandbox-flag glue, not a new architectural surface:

1. **`MCPClient.list_tools()` already exists at AD-449** (`src/probos/integrations/mcp_bridge/client.py`). Discovery for 597f is "iterate connected MCP servers, filter tools where `_meta.ui.resourceUri` is set" — pure scan over existing API. **Absorbed into v1.**

2. **`MCPServerConfig.servers` (existing, AD-449) covers user-configurable MCP server connections.** YAML-only config means zero settings UI work; an operator adds an external server via `config/system.yaml` `mcp.servers[]` and the existing AD-449 bridge connects on boot. The "settings or API" UI surface mentioned in the AD spec is upgrade-path-only — pure CLI/YAML coverage suffices for v1. **Absorbed into v1.**

3. **`_meta.ui.csp` enforcement is one HTTP response header.** The new `/api/mcp/resource` GET endpoint reads `_meta.ui.csp` from the registered tool's metadata and emits it as `Content-Security-Policy` on the response. Internal bundles default to a permissive `script-src 'self' 'unsafe-inline'; default-src 'self'`; external apps inherit whatever CSP the upstream MCP server declares (passed through verbatim). **Absorbed into v1.**

4. **Stricter external sandbox is one boolean flag.** `MCPAppRegistry.register_external_app()` carries `external=True`. `<McpAppFrame>` reads this flag and emits `<iframe sandbox="allow-scripts">` for external (no `allow-same-origin`) versus `<iframe sandbox="allow-scripts allow-same-origin">` for internal. Single line of behavioural difference. **Absorbed into v1.**

The five sub-ADs (a/b/c/d/e) form a connected dependency chain — AppBridge needs Game MCP Server tools to call; Chess UI needs Chess Engine to drive; TTT migration validates the AppBridge pattern with an existing engine. Splitting them across waves would either ship dead code (AppBridge with no apps) or a partially-functional UI (chess engine without a board). One Builder cycle with all five plus 597f's small absorption is the right granularity — same precedent as AD-480 Wave 89 shipping nine sub-AD letters (a–i) and AD-481 Wave 88 shipping fourteen sub-AD letters in single Builder cycles.

One genuine forcing-function deferral remains after the reframe:

- **AD-597c-1 — Threefold-repetition draw detection.** v1's `ChessEngine` ships ~95% of FIDE rules: piece-by-piece move generation, castling (kingside + queenside, blocked-square + check-through-square + king-in-check rejection), en passant, pawn promotion (UCI promotion suffix `e7e8q`), check/checkmate/stalemate, 50-move-rule draw (`halfmove_clock` reset on capture or pawn move), insufficient-material draw (K vs K, K+B vs K, K+N vs K, K+B vs K+B same-coloured bishops). **Forcing function:** v1 ships under `enabled=True` with ≥10 completed chess games persisted in `RecreationService` history AND first operator-reported "draw should have been detected" incident logged via the records-store. Until then, threefold repetition requires Zobrist hashing or canonical FEN-string position-history tracking (~150 LOC + per-move hash update + `state["position_history"]: dict[hash, count]` field), which is orthogonal scope to v1's "MCP App Host + interactive games" delivery target. The 50-move-rule + insufficient-material draws cover the practical-tournament floor; threefold repetition adds the FIDE-completeness ceiling. v1 documents this in `chess_engine.py` module docstring referencing AD-597c-1.

The reframe ships `<McpAppFrame>` + AppBridge JSON-RPC dispatcher + 6 ui/* methods, ProbOS Game MCP server with 5 game tools + 2 ui:// resources, ChessEngine with full FIDE rules minus threefold repetition, Chess MCP App HTML bundle (click-select + click-move + valid-move highlighting + move history sidebar + check/checkmate visual indicators), Tic-Tac-Toe MCP App HTML bundle migrated from custom `GamePanel.tsx`, and external MCP App discovery + read_resource glue with stricter sandbox flag — all in one Builder cycle. AD-597's "MCP App host that ProbOS becomes" surface — the spec target at `roadmap.md:5026` and `decisions-era-4-evolution.md:3596` — is fully delivered. Closes #167.

**v1 IN scope (concrete, all in this single AD prompt):**

- **AD-597 v1 — MCP App Host Infrastructure + Interactive Games** (~80-test pytest plan + ~25-test vitest plan, `prompts/ad-597-mcp-app-host-v1.md`).

  *New Python package `src/probos/mcp_apps/`*:
  - `registry.py` — `MCPAppRegistry` class (public API: `register_app_tool(name, description, input_schema, ui_resource_uri, csp, handler)`, `register_app_resource(uri, mime_type, content)`, `register_external_app(server_id, tool_dict, csp, mcp_client)`, `list_tools() -> list[dict]`, `read_resource(uri) -> dict | None`, `call_tool(name, arguments) -> dict`, `unregister_app(name)`, `set_event_callback(emit_fn)`). Internal apps default `external=False`; external apps registered via `register_external_app` carry `external=True` flag propagated into `_meta.probos.external` on tool dicts.
  - `chess_engine.py` — `ChessEngine` implementing `GameEngine` Protocol (`game_type = "chess"`). UCI move syntax (`"e2e4"`, `"e7e8q"` for promotion). State dict keys: `board` (8x8 nested list), `current_player`, `player_a`, `player_b`, `status` (in_progress/won/draw), `winner`, `castling_rights` (4-bool dict: WK/WQ/BK/BQ), `en_passant_target` (square or empty), `halfmove_clock` (int), `fullmove_number` (int), `last_move` (move string), `result_reason` (mate/stalemate/50_move/insufficient_material/empty). `render_board()` returns Unicode chess pieces (`♔♕♖♗♘♙♚♛♜♝♞♟`). v1 ships threefold-repetition-free draw detection per AD-597c-1 forcing function.
  - `game_app.py` — `register_game_tools(registry, recreation_service, ui_loader)` registers five MCP App tools (`game-challenge`, `game-move`, `game-state`, `game-forfeit`, `game-valid-moves`) where each handler awaits the corresponding `RecreationService` async method and returns `{"isError": False, "content": [{"type": "text", "text": json.dumps(...)}]}` per MCP tool-result shape. Each tool carries `_meta.ui.resourceUri = "ui://probos/games/{game_type}/index.html"`; the host AppBridge reads the URI on tool call and renders the bundled UI. `register_game_resources(registry, bundles_dir)` walks `src/probos/mcp_apps/bundles/{chess,tictactoe}/index.html` and registers each as `ui://probos/games/{game_type}/index.html` with mime_type `text/html`.
  - `external_discovery.py` — `discover_external_apps(registry, mcp_bridge)` async function iterates `mcp_bridge.list_servers()`, calls `client.list_tools()` per connected server, filters tools where `_meta.ui.resourceUri` is set, registers each via `registry.register_external_app(server_id, tool_dict, csp=tool["_meta"]["ui"].get("csp", _DEFAULT_EXTERNAL_CSP), mcp_client=client)`. Tier-2 log-and-degrade: per-server failure logs WARNING and skips that server.
  - `__init__.py` — re-export public surface: `MCPAppRegistry`, `ChessEngine`, `register_game_tools`, `register_game_resources`, `discover_external_apps`.

  *New Python module `src/probos/recreation/chess_engine.py`* — moves chess engine into `recreation/` to live next to `TicTacToeEngine` per AD-597c spec ("Registered in `RecreationService` alongside `TicTacToeEngine`"). The `mcp_apps/chess_engine.py` listed above is actually `recreation/chess_engine.py`; the `mcp_apps` package re-exports it for convenience. Final source-of-truth path: `src/probos/recreation/chess_engine.py`.

  *Extension to `src/probos/federation/mcp_server.py`* — adds `_handle_resources_read` JSON-RPC method routed to `runtime.mcp_app_registry.read_resource(uri)`. Extends `_handle_tools_list` to merge intent-derived tools (existing path) with `runtime.mcp_app_registry.list_tools()` (new path). Extends `_handle_tools_call` to route MCP App tool names through `runtime.mcp_app_registry.call_tool()` BEFORE falling through to the IntentBus broadcast — app tools are explicit registrations, not intent-derived.

  *Extension to `src/probos/integrations/mcp_bridge/client.py` (AD-449)* — adds `async def read_resource(self, uri: str) -> dict` method that issues a `resources/read` JSON-RPC call against the connected server and returns the response's `result` field (containing `contents: list[{uri, mimeType, blob | text}]`).

  *New Pydantic config `MCPAppHostConfig`* in `config.py` adjacent to `FederationMCPServerConfig`: `enabled: bool = False` + `serve_internal_games: bool = True` + `discover_external_apps: bool = False` + `internal_default_csp: str = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'"` + `external_default_csp: str = "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'"` + `bundles_dir: str = ""` (empty = auto-resolve to `<package_root>/mcp_apps/bundles`). Wired on `SystemConfig.mcp_app_host` adjacent to `mcp` field.

  *New finalize wirer `_wire_mcp_app_host`* in `startup/finalize.py` adjacent to the AD-480a MCP server start (`finalize.py:2450`). Constructs `runtime.mcp_app_registry = MCPAppRegistry(...)`, calls `register_game_tools(registry, runtime.recreation_service, ui_loader)` when `serve_internal_games=True` AND `runtime.recreation_service` is not None, calls `register_game_resources(registry, bundles_dir)`, and schedules `discover_external_apps(registry, runtime.mcp_bridge)` via `asyncio.create_task(...)` (task reference stored in `runtime._mcp_app_external_discovery_task` per Async Discipline) when `discover_external_apps=True` AND `runtime.mcp_bridge` is not None. `runtime.mcp_app_registry` public attribute installed.

  *New REST endpoints in `src/probos/routers/system.py`*:
  - `POST /api/mcp/jsonrpc` — accepts MCP JSON-RPC payload, forwards to `runtime.federation_mcp_server.handle_jsonrpc(payload, session_id=request.headers.get("mcp-session-id", ""))`, returns the response. 503 when `runtime.federation_mcp_server is None`.
  - `GET /api/mcp/resource?uri=...` — reads URI via `runtime.mcp_app_registry.read_resource(uri)`, returns response with `Content-Type` from registration (`text/html` for bundles), and `Content-Security-Policy` from registered CSP. 404 when URI not registered.

  *New EventType values* appended to the existing `MCP_BRIDGE_*` cluster in `events.py`: `MCP_APP_TOOL_REGISTERED`, `MCP_APP_RESOURCE_READ`, `MCP_APP_TOOL_INVOKED`, `MCP_APP_EXTERNAL_DISCOVERED`.

  *HXI surface*:
  - `ui/src/mcpApps/bridge.ts` — `McpAppBridge` class implementing 6 ui/* methods. `ui/initialize`, `ui/notifications/tool-input`, `ui/notifications/tool-result` are host-to-app messages dispatched as `iframe.contentWindow.postMessage(...)`. `tools/call`, `ui/message`, `ui/update-model-context` are app-to-host messages received via `window.addEventListener("message", ...)` and forwarded to `POST /api/mcp/jsonrpc` (for `tools/call`) or to the chat store (for `ui/message`, `ui/update-model-context`).
  - `ui/src/components/McpAppFrame.tsx` — React component accepting props `{ resourceUri: string; toolName: string; toolInput?: any; toolResult?: any; external?: boolean; csp?: string }`. Renders `<iframe>` with `sandbox` attribute computed from `external` (`"allow-scripts"` external; `"allow-scripts allow-same-origin"` internal) and `src=/api/mcp/resource?uri=<encoded>`. Wires `McpAppBridge` to forward postMessage events. Lifecycle: `useEffect` mounts bridge, registers handler, posts `ui/initialize` after iframe load, posts `ui/notifications/tool-input` and `ui/notifications/tool-result` when props update; cleanup on unmount.
  - `ui/src/components/GamePanel.tsx` — keeps existing TicTacToe-specific renderer as fallback (per AD-597e "GamePanel.tsx becomes fallback for hosts that don't support MCP Apps"). Adds feature detection: `if (window.__PROBOS_MCP_APP_HOST_ENABLED) <McpAppFrame ... /> else <existing GamePanel ... />`. The flag is set in `App.tsx` based on `/api/system/info` returning `mcp_app_host.enabled === true`.
  - `ui/src/store/types.ts` — adds `mcpAppHostEnabled: boolean` field plus `pendingAppFrames: Record<string, { resourceUri: string; toolName: string; toolInput: any; toolResult: any }>`.

  *New MCP App HTML bundles* under `src/probos/mcp_apps/bundles/`:
  - `chess/index.html` — single-file chess board UI (vite-singlefile output committed to source). Click-to-select + click-to-move with valid-move highlighting (yellow squares for current piece's legal targets), move history sidebar (algebraic notation), captured pieces row, check/checkmate visual indicator (red king square), responsive sizing (square viewport). Calls `tools/call` for `game-move` and `game-valid-moves`. Renders board on `ui/notifications/tool-result`.
  - `tictactoe/index.html` — single-file TTT board UI (vite-singlefile output). Click-to-place. Calls `tools/call` for `game-move`. Renders 3×3 grid on `ui/notifications/tool-result`. Functional parity with existing `GamePanel.tsx`'s display.

  *Test plan (~80 pytest + ~25 vitest, floor 70 + 20)*:
  - `tests/test_ad597_mcp_app_registry.py` — ~15: registry register-app-tool happy path; duplicate-name replace + WARNING; register-app-resource happy path; read-resource hit + miss; call-tool happy path + unknown-tool error + handler-exception tier-2 log-and-degrade; register-external-app emits `MCP_APP_EXTERNAL_DISCOVERED`; list-tools merges internal + external; unregister; event callback fires on register/read/invoke.
  - `tests/test_ad597_chess_engine.py` — ~45: piece-by-piece move generation (pawn 1+2-square + diagonal capture; knight; bishop; rook; queen; king); castling kingside happy + queenside happy + blocked-by-piece + king-in-check + path-through-attacked-square + king-moved-loses-rights + rook-moved-loses-side-rights; en passant happy + window-closed-after-one-ply; promotion to Q/R/B/N + invalid promotion piece; check detection from each piece type; checkmate (Fool's Mate, Scholar's Mate); stalemate fixture; 50-move-rule draw + reset on capture + reset on pawn move; insufficient-material K-K + K-B-K + K-N-K + K-BB-same-colour + non-draw K-N-N-K (technically draw but ship as non-draw per common engine convention; document); UCI move parser invalid-syntax error; render_board Unicode output snapshot; new_game initial state; status transitions in_progress→won + in_progress→draw; chess_engine registered in RecreationService alongside TicTacToeEngine via finalize.
  - `tests/test_ad597_game_app.py` — ~10: register_game_tools registers 5 tool names; each tool's handler routes to RecreationService method; `_meta.ui.resourceUri` carries correct game_type; register_game_resources reads bundle files; tool-call returns MCP-shaped content array.
  - `tests/test_ad597_external_discovery.py` — ~8: discover_external_apps with mock MCPBridge having 0/1/2 servers; per-tool filter on `_meta.ui.resourceUri` presence; per-server failure log-and-degrade; external CSP propagated; external=True flag set on registration.
  - `tests/test_ad597_mcp_server_apps.py` — ~6: federation MCP server `resources/read` JSON-RPC method dispatches to registry; `tools/list` merges intent + app tools; `tools/call` routes app tool names to registry before IntentBus.
  - `tests/test_ad597_mcp_app_routes.py` — ~4: `POST /api/mcp/jsonrpc` 200 happy + 503 when server not running; `GET /api/mcp/resource` 200 with CSP header + 404 for unregistered URI.
  - `tests/test_ad597_finalize.py` — ~2: `_wire_mcp_app_host` installs registry + registers internal games when `serve_internal_games=True`; skips when `enabled=False`.
  - `ui/src/__tests__/McpAppFrame.test.tsx` — ~12: component renders iframe with sandbox attribute matching internal/external flag; src URL encodes resource URI; bridge posts ui/initialize on load; bridge posts ui/notifications/tool-input on prop change; bridge posts ui/notifications/tool-result on prop change; tools/call message forwarded to /api/mcp/jsonrpc; ui/message dispatched to chat store; ui/update-model-context dispatched to store; CSP attribute carried; cleanup on unmount removes message listener; external sandbox excludes allow-same-origin; internal sandbox includes allow-same-origin.
  - `ui/src/__tests__/McpAppBridge.test.ts` — ~8: bridge dispatches ui/initialize; bridge round-trips tools/call → /api/mcp/jsonrpc → result; bridge dispatches ui/notifications/tool-result; bridge ignores messages from non-iframe origins; bridge cleans up listener on dispose; bridge serializes JSON-RPC envelope correctly.
  - `ui/src/__tests__/GamePanel.test.tsx` — ~5: existing tests retained + 2 new: feature-detection routes to `<McpAppFrame>` when `mcpAppHostEnabled`; falls back to existing TTT renderer when flag false.

**v1 OUT scope (deferred with explicit forcing function, NOT minted as new GH issue):**

- **AD-597c-1 — Threefold-repetition draw detection.** Forcing function: ≥10 completed chess games persisted in `RecreationService` history at runtime AND first operator-reported "draw should have been detected" incident logged via the records-store. v1 ships 50-move-rule + insufficient-material draws as the practical-tournament floor; threefold repetition is the FIDE-completeness ceiling and is orthogonal to "MCP App Host + interactive games" delivery. Documented in `chess_engine.py` module docstring.

The two roadmap forward-references that AD-597 transitively unblocks (HXI `CrewRosterPanel` migration to MCP App at `roadmap.md:5089` "Future migration candidate"; AD-596 Cognitive Skills declaring MCP App UIs at `roadmap.md:5108`) remain as already-tracked downstream consumers — Wave 102 mints zero new GH issues.

**The fleet-level MCP App distribution surface (out-of-repo):**
The OSS `MCPAppRegistry` + ProbOS Game MCP Server + `<McpAppFrame>` + external MCP App discovery + 4 new EventTypes form the architectural surface. Cross-instance MCP App curation (a fleet-wide vessel cohort sharing a curated MCP App catalogue across vessels for federated MCP App distribution), customer-supplied closed-source MCP App content, and outcome-style consulting on MCP App library curation are all class-extension territory under the private overlay-repo path token surface. v1 ships zero closed-source content — descriptor-only references throughout this dispatch and the per-AD prompt. Two additional fleet-level surfaces are also out-of-repo: cross-vessel MCP App usage analytics (privacy-preserving fleet-wide app-invocation indexing) and per-fleet MCP App recommendation services. Native-shell packaging of HXI plus AppBridge into a desktop binary is also class-extension territory under that path token surface, separate from the OSS surface this AD ships.

## AD numbering

Highest AD stem at HEAD `c6f39c8` is **AD-696** (verified by sweep across `PROGRESS.md`, `DECISIONS.md`, `decisions-era-1-genesis.md`, `decisions-era-2-emergence.md`, `decisions-era-3-product.md`, `decisions-era-4-evolution.md`, `docs/development/roadmap.md`). W102 mints **zero new AD numbers** (AD-597 is pre-allocated at `decisions-era-4-evolution.md:3596` + `docs/development/roadmap.md:5026`; AD-597a–f are letter-suffixed sub-AD descriptors per the umbrella spec, not GH tracking issues; AD-597c-1 is a letter-suffixed forcing-function descriptor, not a GH tracking issue). Highest BF stem at HEAD: **BF-265**. W102 mints **zero new BF numbers**. **Current highest: AD-696, BF-265.**

## Verify-first against HEAD `c6f39c8`

```
git rev-parse HEAD
  c6f39c8 (HEAD -> main, origin/main, origin/HEAD) Wave 101 archive: AD-510 holodeck team simulations (#92)

# Pytest baseline (verified):
d:/ProbOS/.venv/Scripts/pytest.exe --collect-only -q tests/
  12377 tests collected (12361 passing per Captain summary; 16 known skips)

# AD-449 outbound MCP client substrate (already shipped — verified, NOT redone in v1):
Select-String -Path src\probos\integrations\mcp_bridge\client.py -Pattern "^class MCPClient|JSONRPC_VERSION|MCP_PROTOCOL_VERSION"
  src/probos/integrations/mcp_bridge/client.py: class MCPClient + protocol constants present

Select-String -Path src\probos\integrations\mcp_bridge\__init__.py -Pattern "MCPBridge|MCPClient|MCPSession|MCPToolAdapter"
  src/probos/integrations/mcp_bridge/__init__.py:7-13: all four exports present

# AD-480a inbound MCP server (already shipped — extended in v1, NOT redone):
Select-String -Path src\probos\federation\mcp_server.py -Pattern "^class FederationMCPServer|async def handle_jsonrpc|async def _handle_initialize|async def _handle_tools_list|async def _handle_tools_call|_project_tools_from_descriptors"
  src/probos/federation/mcp_server.py:31:  class FederationMCPServer
  src/probos/federation/mcp_server.py:125: async def handle_jsonrpc
  src/probos/federation/mcp_server.py:155: async def _handle_initialize
  src/probos/federation/mcp_server.py:174: async def _handle_tools_list
  src/probos/federation/mcp_server.py:182: async def _handle_tools_call
  src/probos/federation/mcp_server.py:244: def _project_tools_from_descriptors
  (insertion point for _handle_resources_read: between :180 and :182, immediately before _handle_tools_call)

# AD-526a Recreation framework (already shipped — extended in v1):
Select-String -Path src\probos\recreation\engine.py -Pattern "^class GameEngine|^class TicTacToeEngine|@runtime_checkable|game_type|new_game|make_move|get_valid_moves|render_board|is_finished|get_result"
  src/probos/recreation/engine.py:9: class GameEngine (Protocol with @runtime_checkable)
  src/probos/recreation/engine.py:11-54: 7 protocol methods/properties
  src/probos/recreation/engine.py:56: class TicTacToeEngine

Select-String -Path src\probos\recreation\service.py -Pattern "^class RecreationService|register_engine|create_game|make_move|get_active_games|forfeit_game"
  src/probos/recreation/service.py:15: class RecreationService
  src/probos/recreation/service.py:71: register_engine
  src/probos/recreation/service.py:108: async def create_game
  src/probos/recreation/service.py:156: async def make_move
  src/probos/recreation/service.py:270: get_active_games
  src/probos/recreation/service.py:302: async def forfeit_game

# Existing federation MCP server wiring (AD-480a — verified):
Select-String -Path src\probos\startup\finalize.py -Pattern "FederationMCPServer|federation_mcp_server"
  src/probos/startup/finalize.py:2450: from probos.federation.mcp_server import FederationMCPServer
  src/probos/startup/finalize.py:2451: runtime.federation_mcp_server = FederationMCPServer(
  src/probos/startup/finalize.py:2454: await runtime.federation_mcp_server.start()
  (insertion point for _wire_mcp_app_host: between :2454 and :2462, AFTER federation MCP server is started but BEFORE A2A server start at :2466.)

Select-String -Path src\probos\runtime.py -Pattern "federation_mcp_server|recreation_service|mcp_bridge"
  src/probos/runtime.py:259: federation_mcp_server: "FederationMCPServer | None"
  src/probos/runtime.py:552: self.federation_mcp_server: "FederationMCPServer | None" = None
  (verified: runtime has federation_mcp_server attribute; recreation_service is set late at finalize.py:2961 per AD-526a; mcp_bridge attribute exists per AD-449.)

# Existing GamePanel (target of AD-597e migration):
Test-Path ui/src/components/GamePanel.tsx
  True
(Get-Content ui/src/components/GamePanel.tsx | Measure-Object -Line).Lines
  202

# Existing config insertion point:
Select-String -Path src\probos\config.py -Pattern "^class FederationMCPServerConfig|^class MCPConfig|federation_mcp:"
  (FederationMCPServerConfig present in config.py; insertion point for MCPAppHostConfig adjacent.)

# Vite singlefile bundle plugin presence:
Test-Path ui/package.json; Get-Content ui/package.json | Select-String -Pattern "vite-plugin-singlefile|vite"
  True; vite present (vite-plugin-singlefile may need adding to devDependencies — flagged in gate_1).

# Greenfield path verification:
git ls-files src/probos/mcp_apps/
  (no output — package does not exist; greenfield in v1)
git ls-files src/probos/recreation/chess_engine.py
  (no output — file does not exist; greenfield in v1)
git ls-files ui/src/components/McpAppFrame.tsx
  (no output — file does not exist; greenfield in v1)
git ls-files ui/src/mcpApps/
  (no output — directory does not exist; greenfield in v1)
git ls-files src/probos/mcp_apps/bundles/
  (no output — directory does not exist; greenfield in v1)
```

## Files modified / created

| Path | Action | Purpose |
|---|---|---|
| `src/probos/mcp_apps/__init__.py` | new | Package exports (`MCPAppRegistry`, `register_game_tools`, etc.) |
| `src/probos/mcp_apps/registry.py` | new | `MCPAppRegistry` class with public API for tool/resource registration |
| `src/probos/mcp_apps/game_app.py` | new | Maps `RecreationService` games to MCP App tools + ui:// resources |
| `src/probos/mcp_apps/external_discovery.py` | new | Discovers external MCP App tools via `MCPClient.list_tools()` scan |
| `src/probos/mcp_apps/bundles/chess/index.html` | new | Vite-singlefile chess board UI bundle |
| `src/probos/mcp_apps/bundles/tictactoe/index.html` | new | Vite-singlefile TTT board UI bundle |
| `src/probos/recreation/chess_engine.py` | new | `ChessEngine` implementing `GameEngine` Protocol (95% FIDE rules) |
| `src/probos/recreation/__init__.py` | modify | re-export `ChessEngine` |
| `src/probos/federation/mcp_server.py` | modify | Add `_handle_resources_read`; extend `_handle_tools_list` + `_handle_tools_call` to consult `runtime.mcp_app_registry` |
| `src/probos/integrations/mcp_bridge/client.py` | modify | Add `async def read_resource(uri)` method |
| `src/probos/config.py` | modify | Add `MCPAppHostConfig` Pydantic model + `SystemConfig.mcp_app_host` field |
| `src/probos/startup/finalize.py` | modify | Add `_wire_mcp_app_host` adjacent to AD-480a MCP server start |
| `src/probos/runtime.py` | modify | Add `mcp_app_registry: "MCPAppRegistry | None" = None` + `_mcp_app_external_discovery_task: asyncio.Task | None = None` attributes |
| `src/probos/events.py` | modify | Append 4 new EventType values to MCP_BRIDGE_* cluster |
| `src/probos/routers/system.py` | modify | Add `POST /api/mcp/jsonrpc` + `GET /api/mcp/resource` routes |
| `ui/src/components/McpAppFrame.tsx` | new | React component rendering MCP Apps in sandboxed iframes |
| `ui/src/mcpApps/bridge.ts` | new | `McpAppBridge` JSON-RPC dispatcher (6 ui/* methods) |
| `ui/src/mcpApps/types.ts` | new | TypeScript types for MCP App bridge |
| `ui/src/components/GamePanel.tsx` | modify | Feature-detection routes to `<McpAppFrame>` when `mcpAppHostEnabled` |
| `ui/src/store/types.ts` | modify | Add `mcpAppHostEnabled` + `pendingAppFrames` fields |
| `ui/src/store/useStore.ts` | modify | Initial state + setter for `mcpAppHostEnabled` |
| `ui/src/App.tsx` | modify | Sets `mcpAppHostEnabled` from `/api/system/info` boot fetch |
| `ui/package.json` | modify | Add `vite-plugin-singlefile` to devDependencies if missing |
| `tests/test_ad597_mcp_app_registry.py` | new | ~15 registry tests |
| `tests/test_ad597_chess_engine.py` | new | ~45 chess engine tests |
| `tests/test_ad597_game_app.py` | new | ~10 game-app integration tests |
| `tests/test_ad597_external_discovery.py` | new | ~8 external discovery tests |
| `tests/test_ad597_mcp_server_apps.py` | new | ~6 federation MCP server extension tests |
| `tests/test_ad597_mcp_app_routes.py` | new | ~4 REST route tests |
| `tests/test_ad597_finalize.py` | new | ~2 finalize wirer tests |
| `ui/src/__tests__/McpAppFrame.test.tsx` | new | ~12 vitest component tests |
| `ui/src/__tests__/McpAppBridge.test.ts` | new | ~8 vitest bridge tests |
| `ui/src/__tests__/GamePanel.test.tsx` | modify | retain existing + 2 feature-detection tests |
| `PROGRESS.md` | modify | Wave 102 close header (post-build) |
| `docs/development/roadmap.md` | modify | flip `(planned, OSS)` → `(complete, OSS)` for AD-597 entry |
| `decisions-era-4-evolution.md` | modify | flip AD-597 status marker (post-build) |
| `prompts/wave-plan.yaml` | modify | append W102 entry |

**Expected delta:**
- Pytest: baseline 12361 passing → target ≥12431 (+70 floor) / 12441 (+80 stretch)
- Vitest: baseline (current) → +20 floor / +25 stretch
- LOC: ~2300 Python source + ~1800 TS/HTML/CSS + ~1400 test = ~5500 added

## In-scope vs already-shipped

| Component | Status at HEAD `c6f39c8` | v1 work |
|---|---|---|
| `MCPClient` (outbound MCP) | shipped AD-449 | extend with `read_resource()` |
| `MCPBridge` (outbound bridge) | shipped AD-449 | use existing `list_servers()` API |
| `FederationMCPServer` (inbound MCP) | shipped AD-480a | extend with `resources/read` + app-tool merge |
| `RecreationService` + `TicTacToeEngine` | shipped AD-526a | wrap as MCP App tools (no service change) |
| `GameEngine` Protocol | shipped AD-526a | new `ChessEngine` impl |
| `<GamePanel.tsx>` | shipped AD-526b | feature-detect to `<McpAppFrame>` |
| `_wire_*` finalize pattern | shipped AD-477+ | new `_wire_mcp_app_host` mirrors AD-480a shape |
| Pydantic `*Config` pattern | shipped | new `MCPAppHostConfig` adjacent to existing |
| `SpectatorRegistry` (AD-526e) | shipped | unused in v1 (orthogonal scope; future MCP App spectator surface deferred) |
| `MCP_BRIDGE_INVOKE` / `MCP_BRIDGE_FAILED` EventTypes | shipped AD-449/AD-480a | reused; 4 new MCP_APP_* added |

## gate_1 concerns (architect pre-build risks)

Six risk classes flagged for Builder gate_1 review:

1. **`vite-plugin-singlefile` may not be installed.** Verified `ui/package.json` contains `vite` but the singlefile plugin is the canonical way to produce a single self-contained HTML bundle suitable for serving as `ui://` resource. Builder's first step is `npm install --save-dev vite-plugin-singlefile` if absent. If install fails or plugin causes vite-build issues, fallback: hand-write HTML + inline `<script>` + inline `<style>` for the two bundles (chess + tictactoe). The bundles are committed source artifacts (not regenerated at build time) — operator-friendly and CI-friendly. **Builder must verify the plugin is present BEFORE writing the vite config; if missing, install via npm.** Acceptance allows hand-written single-file HTML if plugin is genuinely unavailable.

2. **Chess engine FIDE-correctness gauntlet.** Chess move validation has well-known edge cases that fail naive implementations: castling-through-attacked-square (king cannot pass through OR end on attacked square; rook may pass through attacked square), en passant available for exactly one ply after a 2-square pawn advance (cleared on next move regardless of capture), pawn promotion is mandatory (no "non-promote" option allowed), king in check must escape on next move (only legal moves are those that resolve check). v1's test plan dedicates ~45 tests to chess specifically. **Builder must implement check-detection BEFORE move-validation** (a "legal move" is one that doesn't leave the moving side's king in check after the move) — a common ordering bug. Suggested implementation: generate pseudo-legal moves first, filter through "would this leave my king in check after the move?". Folded into AD-597c acceptance criteria.

3. **`tools/call` routing precedence.** v1's `_handle_tools_call` extension checks `runtime.mcp_app_registry.has_tool(tool_name)` BEFORE the existing IntentBus broadcast path. Order matters: an intent descriptor with the same name as a registered app tool would be shadowed. v1's app tool names (`game-challenge`, `game-move`, `game-state`, `game-forfeit`, `game-valid-moves`) intentionally use hyphens, which `IntentDescriptor.name` (per `types.py` registered names like `system_status`, `file_read`) does not — collision-free by convention. **Builder must NOT change this ordering.** Documented in the prompt's Section 3.

4. **`ui://` URI scheme parsing must be strict.** `MCPAppRegistry.read_resource(uri)` accepts URIs of the form `ui://<authority>/<path>` where authority is either `probos` (internal) or `external/<server_id>` (external apps). Path traversal (`ui://probos/games/../../../etc/passwd`) must be rejected via a path-segment regex `^[a-z0-9_-]+(/[a-z0-9_.-]+)*$`. **Builder must add a `_safe_uri_path` validator** before passing path components to disk I/O. Folded into AD-597a registry tests.

5. **CSP header injection.** `GET /api/mcp/resource` returns the registered CSP string as `Content-Security-Policy` header. Operator-supplied (or external-MCP-supplied) CSP strings could contain CRLF injection (`\r\n` newlines split headers). **Builder must validate CSP strings via `re.match(r"^[a-zA-Z0-9 ;:'\"_/-]+$", csp)`** at registration time and reject (raise `ValueError`) on invalid characters. Folded into AD-597a acceptance criteria.

6. **External discovery task lifecycle.** `_wire_mcp_app_host` schedules `discover_external_apps` via `asyncio.create_task(...)`. Per Async Discipline: store the task reference in `runtime._mcp_app_external_discovery_task`. The runtime shutdown path (in `_wire_mcp_app_host`'s shutdown hook) must `await asyncio.wait_for(task, timeout=2.0)` then cancel on timeout. **No fire-and-forget.** Folded into the prompt's Section 5.

Five risks NOT flagged (verified non-issues):

- **No layer violation.** `mcp_apps/` is a top-level package alongside `integrations/`, `federation/`, `recreation/` — cross-cutting infrastructure, allowed to import from any layer. `recreation/chess_engine.py` lives next to `engine.py` per AD-597c spec. UI components in `ui/src/components/` follow the existing HXI panel pattern.
- **No new agent / pool / IntentDescriptor.** v1 ships transport substrate + UI rendering. Agents already invoke `RecreationService.make_move()` via existing AD-526a/AD-654d slash command + IntentBus paths.
- **No `BaseAgent` / `IntentMessage` / `GameEngine` Protocol change.** `ChessEngine` implements existing `GameEngine` Protocol verbatim. App tool handlers receive arguments dict and return MCP-shaped tool result dict — no internal-protocol contact.
- **No async/sync hazard.** Tool handlers are async (await `RecreationService` async methods). Resource readers are sync (in-memory dict lookup). External discovery is async (uses MCPClient). All explicit per Builder guard.
- **No federation MCP server replacement.** v1 EXTENDS the existing `FederationMCPServer` rather than building a parallel `GameAppMCPServer`. One MCP server, multiple tool sources (intent descriptors + app registry).

## Banned-pattern audit (commercial leak — pre-commit hook simulation)

The pre-commit hook at `.git/hooks/pre-commit` patterns are 11 in total. This audit table uses descriptor-only language to reference each pattern WITHOUT including the literal string:

| Pattern descriptor | This wave's coverage |
|---|---|
| dollar-amount + per-month/mo phrase | absent — no pricing language anywhere in dispatch or prompt |
| revenue-projection two-word phrase | absent — no revenue language |
| three-letter run-rate acronym (uppercase) | absent — neither dispatch nor prompt uses the literal three-letter run-rate acronym; this audit row's descriptor avoids it |
| outcome + hyphenated-or-spaced + based-pricing phrase | absent — no pricing taxonomy language |
| three-word phrase (great + artists + steal) | absent — no GTM-pattern phrase |
| three-word phrase (patterns + to + absorb) | absent — no patterns-to-absorb phrase |
| private-repo path token (lowercase product name + dash + cmrcl) | absent — only descriptor-only "out-of-repo" / "private overlay-repo path token surface" appears |
| private-repo path token (lowercase product name + dash + e-word stem) | absent — only descriptor-only "out-of-repo" appears |
| e-word + space + overlay (concatenation) | absent — descriptor-only "private overlay-repo path token surface" carries the same semantic without the literal concatenation |
| e-word + space + tier (concatenation) | absent — no tier language |

Audit prose itself uses descriptor-only language and never reproduces any banned literal (including the three-letter run-rate acronym referenced abstractly above). Pre-commit hook simulation expectation: exit 0.

The AD-597 entry on `docs/development/roadmap.md:5026` carries no banned-pattern tag — the carve-out language at `:5108` reads "MCP App marketplace ... native app packaging ... Steam distribution" which contains no banned tokens. Wave 102 mirrors that pattern in dispatch prose ("fleet-level MCP App distribution surface (out-of-repo)" — descriptor-only, no banned token).

Cloud, marketplace-pricing, run-rate, monetisation, packaging-revenue, and GTM language is absent from both this dispatch and the prompt. AD-597 v1 surface is pure protocol — MCP App registry, MCP App server extension, chess engine, MCP App UI bundles, external discovery, REST endpoints, HXI components. Zero pricing / packaging / distribution surface.

`MCPAppRegistry.register_app_tool(... external=False)` and `register_external_app(server_id, ...)` enum/parameter shapes are pure mechanism (internal vs external sandbox boundary) — they exist to declare iframe-sandbox topology, not to gate distribution.

`_meta.ui.resourceUri` and `ui://` are MCP Apps standard wire identifiers — universal-substrate concerns, identical on every ship regardless of OSS / private deployment context. No conditional language.

**Verdict:** clean. Pre-commit hook will not trip on this wave's artifacts. The audit table itself uses descriptor-only language; no banned-pattern literals appear anywhere in this dispatch or the prompt.

## Reframe decision

**Result:** ship **all six** sub-ADs (AD-597a/b/c/d/e/f) in v1. **One forcing-function deferral:** AD-597c-1 threefold-repetition draw detection (orthogonal scope, FIDE-completeness ceiling above the practical-tournament floor). Zero new GH issues minted. Closes #167 cleanly.

**Captain rule "don't defer unless no choice"** applied. The original AD spec at `decisions-era-4-evolution.md:3596` listed AD-597f as "final phase" on security grounds; verify-first analysis at HEAD `c6f39c8` confirmed every infrastructure dependency (AD-449 outbound MCPClient, AD-449 MCPServerConfig.servers YAML, `_meta.ui.csp` HTTP header, sandbox-flag boolean) is already present, making 597f's marginal effort ~150 LOC of glue rather than a new architectural surface. The five-sub-AD chain (a→b→c→d→e) is connected by mutual dependency and would either ship dead code or partial functionality if split — same precedent as AD-480 Wave 89 nine-letter cycle and AD-481 Wave 88 fourteen-letter cycle. Wave 102 ships the umbrella in one Builder cycle, mints zero new GH issues, and closes the umbrella issue on merge.

The threefold-repetition deferral is not a Captain-rule violation — it is a chess-engine-correctness ceiling above the v1 floor (50-move-rule + insufficient-material draws cover the practical-tournament case). Forcing function attached: ≥10 completed chess games persisted AND first operator-reported "draw should have been detected" incident logged. v1 documents this in module docstring; no new GH issue is minted because no consumer at HEAD requires FIDE-completeness today.
