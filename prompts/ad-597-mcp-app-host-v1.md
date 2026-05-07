# AD-597 v1 — MCP App Host Infrastructure + Interactive Games

**Status:** scoped (Wave 102)
**Dependencies:** AD-449 (Outbound MCP client — `MCPClient`/`MCPBridge`), AD-480a (Inbound MCP server — `FederationMCPServer`), AD-526a (RecreationService + GameEngine Protocol), AD-526b (`GamePanel.tsx`), AD-695 (transitional-flag default-False precedent)
**GH issue:** #167
**Estimated tests:** ~80 pytest + ~25 vitest (floor 70 + 20)
**Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

## Problem

The AD-597 spec at `decisions-era-4-evolution.md:3596` and `docs/development/roadmap.md:5026` documents three converging gaps in the HXI surface:

1. **No general-purpose interactive UI in conversations.** HXI chat displays text, markdown, and the AD-526b custom `GamePanel.tsx` React component. Every new interactive feature requires a hardcoded panel.
2. **Games locked to ProbOS crew.** The AD-526a `RecreationService` only supports ProbOS agents playing via Ward Room slash commands. External agents (Claude Desktop, VS Code Copilot, ChatGPT) cannot participate.
3. **No chess engine.** Crew members organically requested chess. The `GameEngine` Protocol supports extensibility but only `TicTacToeEngine` exists at HEAD `c6f39c8`.

The MCP Apps standard solves all three: a sandboxed iframe + JSON-RPC postMessage bridge + `_meta.ui.resourceUri` tool metadata + `ui://` resource scheme. Adoption status: Claude Desktop, VS Code GitHub Copilot, ChatGPT (via OpenAI Apps SDK superset), Goose, Postman. ProbOS implementing this standard makes ProbOS an MCP App host AND lets ProbOS consume apps from those ecosystems.

## Solution overview

Build the MCP App host surface as one connected v1: registry + ProbOS Game MCP Server tools + Chess engine + MCP App HTML bundles + HXI `<McpAppFrame>` component + external discovery glue. All six AD-597 sub-ADs ship in this single prompt:

- **AD-597a (HXI App Host / AppBridge):** `<McpAppFrame>` React component, `McpAppBridge` JSON-RPC dispatcher (6 ui/* methods), iframe sandbox flag, `/api/mcp/jsonrpc` + `/api/mcp/resource` REST endpoints.
- **AD-597b (ProbOS Game MCP Server):** `MCPAppRegistry` Python class, `register_game_tools()` wraps `RecreationService` games as MCP App tools, `register_game_resources()` registers HTML bundles as `ui://` resources, `FederationMCPServer` extension with `resources/read` JSON-RPC method.
- **AD-597c (Chess Engine):** `ChessEngine` implementing `GameEngine` Protocol with full FIDE rules minus threefold repetition (deferred AD-597c-1).
- **AD-597d (Chess MCP App UI):** vite-singlefile HTML/JS/CSS bundle at `src/probos/mcp_apps/bundles/chess/index.html`.
- **AD-597e (Tic-Tac-Toe migration):** vite-singlefile bundle at `src/probos/mcp_apps/bundles/tictactoe/index.html`; `GamePanel.tsx` feature-detects to `<McpAppFrame>`.
- **AD-597f (External MCP App Consumption):** `discover_external_apps()` scans `MCPBridge` connected servers via `MCPClient.list_tools()`, `MCPClient.read_resource()` method, external sandbox flag.

Default-False per AD-695. Operator opts in via `mcp_app_host.enabled=True` plus `federation.mcp_server.enabled=True`.

---

## Section 0: New EventType values

Append to `src/probos/events.py` immediately after the existing `MCP_BRIDGE_FAILED` value (verify the existing cluster grouping; the new values must remain in the MCP_BRIDGE_* / MCP_APP_* logical group):

```python
# AD-597: MCP App Host events
MCP_APP_TOOL_REGISTERED = "mcp_app_tool_registered"
MCP_APP_RESOURCE_READ = "mcp_app_resource_read"
MCP_APP_TOOL_INVOKED = "mcp_app_tool_invoked"
MCP_APP_EXTERNAL_DISCOVERED = "mcp_app_external_discovered"
```

---

## Section 1: `MCPAppRegistry` — `src/probos/mcp_apps/registry.py`

Greenfield package. Public API (Wave-5 convention #1: no leading underscore on public names):

```python
"""AD-597a: MCP App registry — internal + external app tool/resource catalog."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from probos.events import EventType

logger = logging.getLogger(__name__)

# Strict ui:// path validation (Section 4 in dispatch gate_1 #4)
_UI_PATH_RE = re.compile(r"^[a-z0-9_-]+(/[a-z0-9_.-]+)*$")
# CSP header validation (Section 5 in dispatch gate_1 #5)
_CSP_RE = re.compile(r"^[a-zA-Z0-9 ;:'\"_/-]+$")

ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class AppToolRegistration:
    name: str
    description: str
    input_schema: dict[str, Any]
    ui_resource_uri: str
    csp: str
    handler: ToolHandler
    external: bool = False
    server_id: str = ""  # populated for external apps


@dataclass(frozen=True)
class AppResourceRegistration:
    uri: str
    mime_type: str
    content: bytes
    csp: str = ""


class MCPAppRegistry:
    """In-memory registry of MCP App tools and ui:// resources."""

    def __init__(
        self,
        *,
        internal_default_csp: str,
        external_default_csp: str,
    ) -> None:
        if not _CSP_RE.match(internal_default_csp):
            raise ValueError("AD-597a: invalid internal_default_csp")
        if not _CSP_RE.match(external_default_csp):
            raise ValueError("AD-597a: invalid external_default_csp")
        self._tools: dict[str, AppToolRegistration] = {}
        self._resources: dict[str, AppResourceRegistration] = {}
        self._external_clients: dict[str, Any] = {}  # server_id -> MCPClient
        self._internal_default_csp = internal_default_csp
        self._external_default_csp = external_default_csp
        self._emit_event_fn: Callable[..., None] | None = None

    def set_event_callback(self, emit_fn: Callable[..., None]) -> None:
        self._emit_event_fn = emit_fn

    # --- Tool registration ---

    def register_app_tool(
        self,
        *,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        ui_resource_uri: str,
        handler: ToolHandler,
        csp: str = "",
    ) -> None:
        if not name:
            raise ValueError("AD-597a: tool name required")
        if csp and not _CSP_RE.match(csp):
            raise ValueError(f"AD-597a: invalid CSP for tool {name}")
        if name in self._tools:
            logger.warning("AD-597a: replacing app tool %s", name)
        reg = AppToolRegistration(
            name=name,
            description=description,
            input_schema=input_schema,
            ui_resource_uri=ui_resource_uri,
            csp=csp or self._internal_default_csp,
            handler=handler,
            external=False,
        )
        self._tools[name] = reg
        self._emit(EventType.MCP_APP_TOOL_REGISTERED, {"name": name, "external": False})

    def register_external_app(
        self,
        *,
        server_id: str,
        tool_dict: dict[str, Any],
        csp: str,
        mcp_client: Any,
    ) -> None:
        if not server_id:
            raise ValueError("AD-597a: server_id required")
        if csp and not _CSP_RE.match(csp):
            raise ValueError(f"AD-597a: invalid external CSP for server {server_id}")
        name = tool_dict.get("name", "")
        if not name:
            raise ValueError("AD-597a: external tool missing name")
        ui_uri = (
            tool_dict.get("_meta", {})
            .get("ui", {})
            .get("resourceUri", "")
        )
        async def _external_handler(args: dict[str, Any]) -> dict[str, Any]:
            return await mcp_client.call_tool(name, args)
        reg = AppToolRegistration(
            name=name,
            description=tool_dict.get("description", ""),
            input_schema=tool_dict.get("inputSchema", {}),
            ui_resource_uri=ui_uri,
            csp=csp or self._external_default_csp,
            handler=_external_handler,
            external=True,
            server_id=server_id,
        )
        self._tools[name] = reg
        self._external_clients[server_id] = mcp_client
        self._emit(
            EventType.MCP_APP_EXTERNAL_DISCOVERED,
            {"server_id": server_id, "name": name},
        )

    def unregister_app(self, name: str) -> bool:
        return self._tools.pop(name, None) is not None

    def has_tool(self, name: str) -> bool:
        return name in self._tools

    def list_tools(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for reg in self._tools.values():
            entry = {
                "name": reg.name,
                "description": reg.description,
                "inputSchema": reg.input_schema,
                "_meta": {
                    "ui": {
                        "resourceUri": reg.ui_resource_uri,
                        "csp": reg.csp,
                    },
                    "probos": {
                        "external": reg.external,
                        "server_id": reg.server_id,
                    },
                },
            }
            out.append(entry)
        return out

    # --- Resource registration ---

    def register_app_resource(
        self,
        *,
        uri: str,
        mime_type: str,
        content: bytes,
        csp: str = "",
    ) -> None:
        path = self._extract_ui_path(uri)
        if path is None or not _UI_PATH_RE.match(path):
            raise ValueError(f"AD-597a: invalid ui:// uri {uri!r}")
        if csp and not _CSP_RE.match(csp):
            raise ValueError(f"AD-597a: invalid CSP for resource {uri}")
        self._resources[uri] = AppResourceRegistration(
            uri=uri,
            mime_type=mime_type,
            content=content,
            csp=csp or self._internal_default_csp,
        )

    async def read_resource(self, uri: str) -> dict[str, Any] | None:
        # Internal: in-memory lookup.
        reg = self._resources.get(uri)
        if reg is not None:
            self._emit(EventType.MCP_APP_RESOURCE_READ, {"uri": uri, "external": False})
            return {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": reg.mime_type,
                        "blob": None,
                        "text": reg.content.decode("utf-8", errors="replace"),
                    }
                ],
                "_meta": {"ui": {"csp": reg.csp}},
            }
        # External: ui://external/<server_id>/<inner_uri> -> route via MCPClient.read_resource.
        # AD-597f: external lookup is async because MCPClient.read_resource is async.
        if uri.startswith("ui://external/"):
            remainder = uri[len("ui://external/"):]
            server_id, _sep, _rest = remainder.partition("/")
            client = self._external_clients.get(server_id)
            if client is None:
                return None
            # Find the originally-registered tool's ui_resource_uri to route to.
            for reg_tool in self._tools.values():
                if reg_tool.external and reg_tool.server_id == server_id and reg_tool.ui_resource_uri == uri:
                    inner = reg_tool.ui_resource_uri
                    break
            else:
                inner = uri
            try:
                external_result = await client.read_resource(inner)
            except Exception as exc:
                logger.warning(
                    "AD-597f: external read_resource failed for %s: %s", uri, exc,
                )
                return None
            self._emit(EventType.MCP_APP_RESOURCE_READ, {"uri": uri, "external": True})
            return external_result
        return None

    def get_resource_csp(self, uri: str) -> str:
        reg = self._resources.get(uri)
        return reg.csp if reg else ""

    def get_resource_mime(self, uri: str) -> str:
        reg = self._resources.get(uri)
        return reg.mime_type if reg else ""

    # --- Tool invocation ---

    async def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        reg = self._tools.get(name)
        if reg is None:
            return {
                "isError": True,
                "content": [
                    {"type": "text", "text": f"unknown app tool: {name}"}
                ],
            }
        try:
            result = await reg.handler(arguments)
            self._emit(EventType.MCP_APP_TOOL_INVOKED, {"name": name})
            return result
        except Exception as exc:
            logger.warning(
                "AD-597a: app tool %s handler failed: %s", name, exc
            )
            return {
                "isError": True,
                "content": [
                    {"type": "text", "text": f"tool {name} failed: {exc}"}
                ],
            }

    # --- Helpers ---

    @staticmethod
    def _extract_ui_path(uri: str) -> str | None:
        if not uri.startswith("ui://"):
            return None
        return uri[len("ui://"):]

    def _emit(self, event_type: EventType, payload: dict[str, Any]) -> None:
        if self._emit_event_fn is None:
            return
        try:
            self._emit_event_fn(event_type, payload)
        except Exception:
            logger.warning("AD-597a: event emit failed", exc_info=True)
```

---

## Section 2: `ChessEngine` — `src/probos/recreation/chess_engine.py`

Greenfield. Implements `GameEngine` Protocol from `recreation/engine.py:9`. UCI move syntax (`"e2e4"`, `"e7e8q"` for promotion). v1 ships full FIDE rules MINUS threefold-repetition draw detection (forcing function: AD-597c-1 — needs Zobrist hashing or canonical FEN-string position-history tracking; orthogonal scope).

State dict shape:
```python
{
    "board": list[list[str]],  # 8x8, rank 0 = white back rank, file 0 = a-file
                                # piece codes: "P","N","B","R","Q","K" (white) /
                                # "p","n","b","r","q","k" (black) / "" (empty)
    "current_player": str,      # callsign of side to move
    "player_a": str,            # white callsign
    "player_b": str,            # black callsign
    "status": str,              # "in_progress" | "won" | "draw"
    "winner": str,              # callsign of winner or ""
    "castling_rights": dict[str, bool],  # {"WK": True, "WQ": True, "BK": True, "BQ": True}
    "en_passant_target": str,   # algebraic square ("e3") available for capture, or ""
    "halfmove_clock": int,      # plies since last capture or pawn move (50-move rule)
    "fullmove_number": int,     # increments after black moves
    "last_move": str,           # UCI string of most recent move
    "result_reason": str,       # "" | "checkmate" | "stalemate" | "50_move" | "insufficient_material"
}
```

Public API (Protocol-conforming):

```python
"""AD-597c: ChessEngine — full FIDE rules minus threefold repetition.

Threefold-repetition draw detection is deferred to AD-597c-1 (needs Zobrist
hashing or canonical FEN-string position-history tracking). v1 ships:

- Move generation per piece (P/N/B/R/Q/K)
- Castling kingside + queenside (blocked-square + king-in-check + path-attacked)
- En passant (single-ply window after 2-square pawn advance)
- Pawn promotion (UCI suffix: e7e8q, e7e8r, e7e8b, e7e8n)
- Check + checkmate + stalemate detection
- 50-move-rule draw (halfmove_clock resets on capture or pawn move)
- Insufficient-material draw (K-K, K-B-K, K-N-K, K-BB-same-colour)
"""

from __future__ import annotations

from typing import Any


class ChessEngine:
    @property
    def game_type(self) -> str:
        return "chess"

    def new_game(self, player_a: str, player_b: str) -> dict[str, Any]:
        ...

    def make_move(
        self, state: dict[str, Any], player: str, move: str
    ) -> dict[str, Any]:
        ...

    def get_valid_moves(self, state: dict[str, Any]) -> list[str]:
        ...

    def render_board(self, state: dict[str, Any]) -> str:
        ...

    def is_finished(self, state: dict[str, Any]) -> bool:
        ...

    def get_result(self, state: dict[str, Any]) -> dict[str, str]:
        ...
```

Implementation guidance for the Builder:

- **Pseudo-legal then legal-filter ordering.** Generate pseudo-legal moves first (ignoring check), then filter those that leave the moving side's king in check after the move. This is the canonical correctness pattern; reverse ordering produces subtle bugs around pinned pieces.
- **Castling validation.** Check king-not-in-check + king-not-passing-through-attacked-square + king-not-ending-on-attacked-square + path-clear + king-and-rook-not-moved (`castling_rights` flag).
- **En passant clearing.** Set `en_passant_target` to the skipped square only on a 2-square pawn move; clear on every other move.
- **Halfmove clock.** Reset to 0 on capture or pawn move; increment otherwise.
- **Insufficient material.** Match: (a) K-K only; (b) K-K + one bishop; (c) K-K + one knight; (d) K-K + bishops where every bishop sits on the same colour square. Two knights vs lone king is technically draw-by-rule but ship as non-draw per common engine convention (document in module docstring).
- **`get_valid_moves` returns UCI strings.** Pawn promotion produces 4 entries per promoting move (`e7e8q`, `e7e8r`, `e7e8b`, `e7e8n`). Non-promotion moves produce 1 entry.
- **`render_board` Unicode.** White: ♔♕♖♗♘♙. Black: ♚♛♜♝♞♟. Empty: `·` (middle-dot). Include rank/file labels.

Add `ChessEngine` re-export to `src/probos/recreation/__init__.py`.

Also register the engine alongside `TicTacToeEngine` in `RecreationService.__init__` — verify the existing `register_engine(TicTacToeEngine())` call at `src/probos/recreation/service.py:53` and add a sibling `register_engine(ChessEngine())` line directly after. Wave-5 convention #1.

---

## Section 3: Game MCP App glue — `src/probos/mcp_apps/game_app.py`

Greenfield. Wraps `RecreationService` async methods as MCP App tool handlers and registers the bundled HTML resources.

```python
"""AD-597b: ProbOS Game MCP Server — wraps RecreationService as MCP App tools."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from probos.mcp_apps.registry import MCPAppRegistry

logger = logging.getLogger(__name__)


def register_game_tools(
    registry: MCPAppRegistry,
    recreation_service: Any,
) -> None:
    """Register 5 game tools backed by RecreationService."""

    available = recreation_service.get_available_games()

    async def _challenge(args: dict[str, Any]) -> dict[str, Any]:
        game_type = args.get("game_type", recreation_service.default_game)
        challenger = args.get("challenger", "")
        opponent = args.get("opponent", "")
        thread_id = args.get("thread_id", "")
        info = await recreation_service.create_game(
            game_type, challenger, opponent, thread_id
        )
        return {
            "isError": False,
            "content": [
                {"type": "text", "text": json.dumps(info, default=str)}
            ],
        }

    async def _move(args: dict[str, Any]) -> dict[str, Any]:
        info = await recreation_service.make_move(
            args.get("game_id", ""),
            args.get("player", ""),
            args.get("move", ""),
        )
        return {
            "isError": False,
            "content": [
                {"type": "text", "text": json.dumps(info, default=str)}
            ],
        }

    async def _state(args: dict[str, Any]) -> dict[str, Any]:
        game_id = args.get("game_id", "")
        info = recreation_service._active_games.get(game_id)
        if info is None:
            return {
                "isError": True,
                "content": [
                    {"type": "text", "text": f"unknown game_id {game_id}"}
                ],
            }
        return {
            "isError": False,
            "content": [
                {"type": "text", "text": json.dumps(info, default=str)}
            ],
        }

    async def _forfeit(args: dict[str, Any]) -> dict[str, Any]:
        await recreation_service.forfeit_game(
            args.get("game_id", ""), args.get("player", "")
        )
        return {"isError": False, "content": [{"type": "text", "text": "ok"}]}

    async def _valid_moves(args: dict[str, Any]) -> dict[str, Any]:
        moves = recreation_service.get_valid_moves(args.get("game_id", ""))
        return {
            "isError": False,
            "content": [{"type": "text", "text": json.dumps(moves)}],
        }

    # Per-game-type tool registration; ui_resource_uri maps to each game type
    for game_type in available:
        ui_uri = f"ui://probos/games/{game_type}/index.html"
        registry.register_app_tool(
            name=f"game-{game_type}-challenge",
            description=f"Challenge to a {game_type} game",
            input_schema={
                "type": "object",
                "properties": {
                    "challenger": {"type": "string"},
                    "opponent": {"type": "string"},
                    "thread_id": {"type": "string"},
                },
                "required": ["challenger", "opponent"],
            },
            ui_resource_uri=ui_uri,
            handler=_challenge,
        )

    # Generic game-* tools (game_id-driven; no game_type-specific UI URI)
    registry.register_app_tool(
        name="game-move",
        description="Make a move in an active game",
        input_schema={
            "type": "object",
            "properties": {
                "game_id": {"type": "string"},
                "player": {"type": "string"},
                "move": {"type": "string"},
            },
            "required": ["game_id", "player", "move"],
        },
        ui_resource_uri="",  # generic — UI resolved by GamePanel via game_type
        handler=_move,
    )
    registry.register_app_tool(
        name="game-state",
        description="Get current state of a game",
        input_schema={
            "type": "object",
            "properties": {"game_id": {"type": "string"}},
            "required": ["game_id"],
        },
        ui_resource_uri="",
        handler=_state,
    )
    registry.register_app_tool(
        name="game-forfeit",
        description="Forfeit an active game",
        input_schema={
            "type": "object",
            "properties": {
                "game_id": {"type": "string"},
                "player": {"type": "string"},
            },
            "required": ["game_id", "player"],
        },
        ui_resource_uri="",
        handler=_forfeit,
    )
    registry.register_app_tool(
        name="game-valid-moves",
        description="List valid moves for the current player",
        input_schema={
            "type": "object",
            "properties": {"game_id": {"type": "string"}},
            "required": ["game_id"],
        },
        ui_resource_uri="",
        handler=_valid_moves,
    )


def register_game_resources(
    registry: MCPAppRegistry,
    bundles_dir: Path,
) -> None:
    """Register HTML bundles under bundles_dir/<game_type>/index.html as ui:// resources."""
    if not bundles_dir.is_dir():
        logger.warning(
            "AD-597b: bundles dir missing: %s — skipping resource registration",
            bundles_dir,
        )
        return
    for game_dir in sorted(bundles_dir.iterdir()):
        if not game_dir.is_dir():
            continue
        index_path = game_dir / "index.html"
        if not index_path.is_file():
            logger.warning(
                "AD-597b: bundle missing index.html: %s", game_dir.name
            )
            continue
        try:
            content = index_path.read_bytes()
        except OSError as exc:
            logger.warning(
                "AD-597b: failed to read %s: %s", index_path, exc
            )
            continue
        uri = f"ui://probos/games/{game_dir.name}/index.html"
        registry.register_app_resource(
            uri=uri, mime_type="text/html", content=content
        )
```

---

## Section 4: External app discovery — `src/probos/mcp_apps/external_discovery.py`

Greenfield. Scans connected MCPClients for tools carrying `_meta.ui.resourceUri`.

```python
"""AD-597f: External MCP App discovery via existing AD-449 MCPBridge."""

from __future__ import annotations

import logging
from typing import Any

from probos.mcp_apps.registry import MCPAppRegistry

logger = logging.getLogger(__name__)


async def discover_external_apps(
    registry: MCPAppRegistry,
    mcp_bridge: Any,
) -> int:
    """Iterate connected MCP servers, discover app tools, register them.

    Returns count of external app tools registered. Tier-2 log-and-degrade:
    per-server failure logs WARNING and skips that server.
    """
    if mcp_bridge is None:
        return 0
    count = 0
    try:
        # AD-449 MCPBridge.list_servers() returns list[str] of server URLs;
        # use get_client(server_url) to resolve to MCPClient.
        server_urls = mcp_bridge.list_servers()
    except Exception as exc:
        logger.warning("AD-597f: list_servers failed: %s", exc)
        return 0
    for server_url in server_urls:
        client = mcp_bridge.get_client(server_url)
        if client is None:
            continue
        try:
            tools = await client.list_tools()
        except Exception as exc:
            logger.warning(
                "AD-597f: list_tools failed for %s: %s", server_url, exc
            )
            continue
        for tool in tools:
            ui = tool.get("_meta", {}).get("ui", {})
            if not ui.get("resourceUri"):
                continue
            csp = ui.get("csp", "")
            try:
                registry.register_external_app(
                    server_id=server_url,
                    tool_dict=tool,
                    csp=csp,
                    mcp_client=client,
                )
                count += 1
            except ValueError as exc:
                logger.warning(
                    "AD-597f: skipping %s/%s: %s",
                    server_url, tool.get("name", "?"), exc,
                )
    return count
```

---

## Section 5: Federation MCP server extension — `src/probos/federation/mcp_server.py`

Add `_handle_resources_read` JSON-RPC method. Extend `_handle_tools_list` and `_handle_tools_call`.

In `handle_jsonrpc()` at line 126, ADD an `elif` for `"resources/read"`:

```
===MODIFY: src/probos/federation/mcp_server.py===
===SEARCH===
            if method == "tools/list":
                return await self._handle_tools_list(request_id)
            if method == "tools/call":
                return await self._handle_tools_call(
                    request_id, params, session_id
                )
            return self._error_envelope(
                request_id, -32601, f"Method not found: {method}"
            )
===REPLACE===
            if method == "tools/list":
                return await self._handle_tools_list(request_id)
            if method == "tools/call":
                return await self._handle_tools_call(
                    request_id, params, session_id
                )
            if method == "resources/read":
                return await self._handle_resources_read(request_id, params)
            return self._error_envelope(
                request_id, -32601, f"Method not found: {method}"
            )
===END REPLACE===
```

Extend `_handle_tools_list` to merge intent-derived tools with app registry tools:

```
===SEARCH===
    async def _handle_tools_list(self, request_id: Any) -> dict[str, Any]:
        tools = self._project_tools_from_descriptors()
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "result": {"tools": tools},
        }
===REPLACE===
    async def _handle_tools_list(self, request_id: Any) -> dict[str, Any]:
        tools = self._project_tools_from_descriptors()
        # AD-597b: merge app-registry tools (internal + external)
        registry = getattr(self._runtime, "mcp_app_registry", None)
        if registry is not None:
            tools.extend(registry.list_tools())
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "result": {"tools": tools},
        }
===END REPLACE===
```

Extend `_handle_tools_call` to route app tools BEFORE IntentBus broadcast (precedence per gate_1 #3):

```
===SEARCH===
        peer_id = (
            f"mcp-session:{session_id}"
            if session_id
            else f"mcp-anon:{request_id}"
        )
        await self._ensure_peer_registered(peer_id)

        intent = IntentMessage(
===REPLACE===
        peer_id = (
            f"mcp-session:{session_id}"
            if session_id
            else f"mcp-anon:{request_id}"
        )
        await self._ensure_peer_registered(peer_id)

        # AD-597b: app-registry tools take precedence over intent dispatch.
        # App tools use hyphenated names (game-move, game-state) which never
        # collide with IntentDescriptor.name (system_status, file_read, ...).
        registry = getattr(self._runtime, "mcp_app_registry", None)
        if registry is not None and registry.has_tool(tool_name):
            try:
                app_result = await registry.call_tool(tool_name, arguments)
            except Exception as exc:
                self._record_outcome(peer_id, False, intent_type=tool_name)
                return self._error_envelope(
                    request_id, -32000, f"app tool failed: {exc}"
                )
            self._record_outcome(
                peer_id, not app_result.get("isError", False), intent_type=tool_name,
            )
            self._emit_invoke(method="tools/call", tool=tool_name)
            return {
                "jsonrpc": JSONRPC_VERSION,
                "id": request_id,
                "result": app_result,
            }

        intent = IntentMessage(
===END REPLACE===
```

Add `_handle_resources_read` immediately after `_handle_tools_list`:

```
===SEARCH===
    async def _handle_tools_call(
        self,
        request_id: Any,
        params: dict,
        session_id: str,
    ) -> dict[str, Any]:
===REPLACE===
    async def _handle_resources_read(
        self, request_id: Any, params: dict
    ) -> dict[str, Any]:
        # AD-597a: ui:// resource lookup via runtime.mcp_app_registry
        uri = params.get("uri", "")
        if not uri:
            return self._error_envelope(request_id, -32602, "uri required")
        registry = getattr(self._runtime, "mcp_app_registry", None)
        if registry is None:
            return self._error_envelope(
                request_id, -32000, "mcp_app_registry not available"
            )
        result = await registry.read_resource(uri)
        if result is None:
            return self._error_envelope(
                request_id, -32000, f"resource not found: {uri}"
            )
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "result": result,
        }

    async def _handle_tools_call(
        self,
        request_id: Any,
        params: dict,
        session_id: str,
    ) -> dict[str, Any]:
===END REPLACE===
```

---

## Section 6: `MCPClient.read_resource()` — `src/probos/integrations/mcp_bridge/client.py`

Add a single method. Pattern matches existing `list_tools()` / `call_tool()`. Insert immediately after the existing `call_tool` method (Builder must locate the exact insertion point and add):

```python
async def read_resource(self, uri: str) -> dict[str, Any]:
    """Issue resources/read JSON-RPC call. Returns the result envelope."""
    response = await self._call(
        method="resources/read",
        params={"uri": uri},
    )
    if "error" in response:
        raise MCPProtocolError(
            f"resources/read failed: {response['error']}"
        )
    return response.get("result", {})
```

---

## Section 7: Pydantic config — `src/probos/config.py`

Add `MCPAppHostConfig` adjacent to `FederationMCPServerConfig`. Wire on `SystemConfig`:

```python
class MCPAppHostConfig(BaseModel):
    """AD-597 — MCP App Host configuration."""

    enabled: bool = False
    serve_internal_games: bool = True
    discover_external_apps: bool = False
    internal_default_csp: str = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'"
    )
    external_default_csp: str = (
        "default-src 'none'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'"
    )
    bundles_dir: str = ""  # empty = auto-resolve to <package>/mcp_apps/bundles
```

Wire on `SystemConfig`:

```python
mcp_app_host: MCPAppHostConfig = Field(default_factory=MCPAppHostConfig)
```

Builder must locate `class FederationMCPServerConfig` and `class SystemConfig` in `config.py` (verified present at HEAD per dispatch verify-first); insert the new model adjacent to `FederationMCPServerConfig` and add the field to `SystemConfig` adjacent to `mcp` field. SEARCH/REPLACE blocks must include 3 lines of context before/after for unique anchoring.

---

## Section 8: Finalize wirer — `src/probos/startup/finalize.py`

Insert `_wire_mcp_app_host` adjacent to the AD-480a federation MCP server start at `:2450`. The wirer must run AFTER the federation MCP server starts (so `runtime.federation_mcp_server` exists) and AFTER recreation_service init at `:2961` — which means the wirer cannot run inline at `:2450`. The correct insertion point is AFTER the recreation service is set, so add the wirer call adjacent to the recreation service wiring at `finalize.py:2959-2961`. Verify via Builder pre-check.

```python
def _wire_mcp_app_host(*, runtime, config) -> bool:
    """AD-597: install MCPAppRegistry, register internal games, schedule external discovery."""
    cfg = config.mcp_app_host
    if not cfg.enabled:
        return False
    from pathlib import Path
    from probos.mcp_apps.registry import MCPAppRegistry
    from probos.mcp_apps.game_app import (
        register_game_tools,
        register_game_resources,
    )
    registry = MCPAppRegistry(
        internal_default_csp=cfg.internal_default_csp,
        external_default_csp=cfg.external_default_csp,
    )
    if hasattr(runtime, "emit_event"):
        registry.set_event_callback(runtime.emit_event)
    runtime.mcp_app_registry = registry

    if cfg.serve_internal_games and getattr(runtime, "recreation_service", None):
        try:
            register_game_tools(registry, runtime.recreation_service)
        except Exception:
            logger.warning("AD-597b: register_game_tools failed", exc_info=True)
        bundles_dir = (
            Path(cfg.bundles_dir)
            if cfg.bundles_dir
            else Path(__file__).resolve().parent.parent / "mcp_apps" / "bundles"
        )
        try:
            register_game_resources(registry, bundles_dir)
        except Exception:
            logger.warning("AD-597b: register_game_resources failed", exc_info=True)

    if cfg.discover_external_apps and getattr(runtime, "mcp_bridge", None):
        from probos.mcp_apps.external_discovery import discover_external_apps
        async def _bg() -> None:
            try:
                await discover_external_apps(registry, runtime.mcp_bridge)
            except Exception:
                logger.warning("AD-597f: external discovery failed", exc_info=True)
        task = asyncio.create_task(_bg(), name="mcp-app-external-discovery")
        runtime._mcp_app_external_discovery_task = task
    return True
```

Invoke from `finalize_startup` AFTER the recreation_service block at `:2959-2961`. Builder must locate the exact line.

---

## Section 9: Runtime attributes — `src/probos/runtime.py`

Add two instance attributes. Match the existing `federation_mcp_server: "FederationMCPServer | None" = None` pattern at `runtime.py:552`.

In the type annotations block (around line 258-260):
```python
mcp_app_registry: "MCPAppRegistry | None"
```

In `__init__` (around line 552):
```python
# AD-597: MCP App Host registry — installed by _wire_mcp_app_host.
self.mcp_app_registry: "MCPAppRegistry | None" = None
self._mcp_app_external_discovery_task: asyncio.Task | None = None
```

Add a `TYPE_CHECKING` import at the top:
```python
if TYPE_CHECKING:
    from probos.mcp_apps.registry import MCPAppRegistry
```

---

## Section 10: REST endpoints — `src/probos/routers/system.py`

Add two routes. Builder must locate the existing router patterns in `system.py` and add adjacent.

```python
@router.post("/mcp/jsonrpc")
async def mcp_jsonrpc(request: Request, runtime: Any = Depends(get_runtime)):
    """AD-597a: forward MCP JSON-RPC payload to FederationMCPServer."""
    if runtime.federation_mcp_server is None:
        raise HTTPException(status_code=503, detail="MCP server not running")
    payload = await request.json()
    session_id = request.headers.get("mcp-session-id", "")
    response = await runtime.federation_mcp_server.handle_jsonrpc(
        payload, session_id=session_id
    )
    headers: dict[str, str] = {}
    assigned = response.pop("_assigned_session", None)
    if assigned:
        headers["Mcp-Session-Id"] = assigned
    return JSONResponse(response, headers=headers)


@router.get("/mcp/resource")
async def mcp_resource(uri: str, runtime: Any = Depends(get_runtime)):
    """AD-597a: serve ui:// resource as HTTP for iframe embedding."""
    if runtime.mcp_app_registry is None:
        raise HTTPException(status_code=503, detail="MCP App registry not running")
    result = await runtime.mcp_app_registry.read_resource(uri)
    if result is None:
        raise HTTPException(status_code=404, detail=f"resource not found: {uri}")
    contents = result.get("contents", [])
    if not contents:
        raise HTTPException(status_code=404, detail="empty resource")
    body = contents[0].get("text", "")
    mime = runtime.mcp_app_registry.get_resource_mime(uri) or "text/html"
    csp = runtime.mcp_app_registry.get_resource_csp(uri)
    headers = {"Content-Security-Policy": csp} if csp else {}
    return Response(content=body, media_type=mime, headers=headers)
```

Builder must verify `Request` / `Response` / `JSONResponse` / `HTTPException` are imported and add as needed.

---

## Section 11: HXI components

### `ui/src/mcpApps/types.ts` (new)

```typescript
export interface McpAppFrameProps {
  resourceUri: string;
  toolName: string;
  toolInput?: unknown;
  toolResult?: unknown;
  external?: boolean;
}

export interface JsonRpcEnvelope {
  jsonrpc: '2.0';
  id?: string | number;
  method?: string;
  params?: Record<string, unknown>;
  result?: unknown;
  error?: { code: number; message: string };
}
```

### `ui/src/mcpApps/bridge.ts` (new)

`McpAppBridge` class with 6 ui/* method support. Listens for postMessage from iframe; forwards `tools/call` to `/api/mcp/jsonrpc`; dispatches `ui/initialize`, `ui/notifications/tool-input`, `ui/notifications/tool-result` from host to iframe. ~150 LOC. Builder writes per types.

### `ui/src/components/McpAppFrame.tsx` (new)

React component. Props per `McpAppFrameProps`. Renders `<iframe src={'/api/mcp/resource?uri=' + encodeURIComponent(resourceUri)} sandbox={external ? 'allow-scripts' : 'allow-scripts allow-same-origin'} />`. Wires `McpAppBridge`. Lifecycle: `useEffect` mounts bridge on `iframe.onload`, posts `ui/initialize`, posts `tool-input`/`tool-result` on prop change; cleanup on unmount. ~200 LOC.

### `ui/src/components/GamePanel.tsx` (modify)

Feature-detect via `useStore(s => s.mcpAppHostEnabled)`. When true, render `<McpAppFrame resourceUri={'ui://probos/games/' + gameType + '/index.html'} toolName="game-state" toolInput={{ game_id: gameId }} />`. When false, render the existing TTT board (preserved as fallback).

### `ui/src/store/types.ts` (modify)

Add to state shape:
```typescript
mcpAppHostEnabled: boolean;
pendingAppFrames: Record<string, {
  resourceUri: string;
  toolName: string;
  toolInput: unknown;
  toolResult: unknown;
}>;
```

### `ui/src/store/useStore.ts` (modify)

Initial state `mcpAppHostEnabled: false`, `pendingAppFrames: {}`. Setters: `setMcpAppHostEnabled(boolean)`, `setPendingAppFrame(id, frame)`, `clearPendingAppFrame(id)`.

### `ui/src/App.tsx` (modify)

On boot, fetch `/api/system/info` and call `setMcpAppHostEnabled(json.mcp_app_host?.enabled === true)`. Integrate adjacent to existing boot fetches.

---

## Section 12: MCP App HTML bundles

### `src/probos/mcp_apps/bundles/chess/index.html` (new)

Single-file vite-singlefile bundle (committed source). Click-to-select + click-to-move + valid-move highlighting (yellow squares for current piece's legal targets) + move history sidebar (algebraic) + captured pieces row + check/checkmate visual indicator (red king square) + responsive sizing. Calls parent `tools/call` for `game-move` and `game-valid-moves` via `parent.postMessage({ jsonrpc: '2.0', method: 'tools/call', params: { name: 'game-move', arguments: {...} } }, '*')`. Renders board on incoming `ui/notifications/tool-result` from parent.

### `src/probos/mcp_apps/bundles/tictactoe/index.html` (new)

Single-file bundle. Click-to-place. 3×3 grid. Functional parity with existing `GamePanel.tsx` rendering. Same postMessage protocol as chess bundle.

If `vite-plugin-singlefile` is unavailable, Builder may hand-write self-contained HTML with inline `<script>` and `<style>` (gate_1 #1 in dispatch). Either is acceptable.

---

## Section 13: Tests

### `tests/test_ad597_mcp_app_registry.py` (~15 tests)

1. `test_register_app_tool_happy_path`
2. `test_register_app_tool_duplicate_replace_with_warning`
3. `test_register_app_tool_invalid_csp_raises`
4. `test_register_app_resource_happy_path`
5. `test_register_app_resource_invalid_path_raises`
6. `test_read_resource_hit`
7. `test_read_resource_miss_returns_none`
8. `test_call_tool_happy_path`
9. `test_call_tool_unknown_returns_isError`
10. `test_call_tool_handler_exception_log_and_degrade`
11. `test_register_external_app_emits_discovered_event`
12. `test_list_tools_merges_internal_and_external`
13. `test_unregister_app`
14. `test_event_callback_fires_on_register`
15. `test_external_app_handler_routes_through_mcp_client`

### `tests/test_ad597_chess_engine.py` (~45 tests)

Cover at minimum: pawn moves (1-sq, 2-sq, diagonal capture, blocked), knight, bishop, rook, queen, king (single-square + castling); castling kingside happy + queenside happy + path-blocked + king-in-check + path-attacked + king-moved-loses-rights + rook-moved-loses-side-rights; en passant happy + window-closed; promotion to Q/R/B/N + invalid-piece; check from each piece type; checkmate (Fool's Mate, Scholar's Mate); stalemate fixture; 50-move-rule + reset-on-capture + reset-on-pawn-move; insufficient-material K-K + K-B-K + K-N-K + K-BB-same-colour + non-draw K-N-N-K; UCI parser invalid-syntax; render_board Unicode snapshot; new_game initial state; status transitions; ChessEngine registered alongside TicTacToeEngine via service init.

### `tests/test_ad597_game_app.py` (~10 tests)

`register_game_tools` registers 5 generic tools + 1 challenge tool per game type; each tool's handler routes to RecreationService method; tool-call returns MCP-shaped content array; `_meta.ui.resourceUri` carries correct game_type; `register_game_resources` reads bundle files; missing bundles_dir log-and-degrade.

### `tests/test_ad597_external_discovery.py` (~8 tests)

`discover_external_apps` with mock MCPBridge having 0/1/2 servers; per-tool filter on `_meta.ui.resourceUri` presence; per-server failure log-and-degrade; external CSP propagated; `external=True` flag set on registration; `mcp_bridge=None` returns 0; `list_servers` exception returns 0.

### `tests/test_ad597_mcp_server_apps.py` (~6 tests)

`resources/read` JSON-RPC method dispatches to registry; `resources/read` with missing uri returns -32602; `resources/read` with unknown uri returns -32000; `tools/list` merges intent + app tools; `tools/call` routes app tool names to registry before IntentBus; `tools/call` for app tool emits MCP_BRIDGE_INVOKE.

### `tests/test_ad597_mcp_app_routes.py` (~4 tests)

`POST /api/mcp/jsonrpc` 200 happy + 503 when server not running; `GET /api/mcp/resource` 200 with CSP header + 404 for unregistered URI.

### `tests/test_ad597_finalize.py` (~2 tests)

`_wire_mcp_app_host` installs registry + registers internal games when `serve_internal_games=True`; skips entirely when `enabled=False`.

### `ui/src/__tests__/McpAppFrame.test.tsx` (~12 vitest tests)

Component renders iframe with sandbox attribute matching internal/external flag; src URL encodes resource URI; bridge posts ui/initialize on iframe load; bridge posts ui/notifications/tool-input on prop change; bridge posts ui/notifications/tool-result on prop change; tools/call message forwarded to /api/mcp/jsonrpc; ui/message dispatched to chat store; ui/update-model-context dispatched to store; cleanup on unmount removes message listener; external sandbox excludes allow-same-origin; internal sandbox includes allow-same-origin; iframe src omits ui:// scheme prefix when encoding.

### `ui/src/__tests__/McpAppBridge.test.ts` (~8 vitest tests)

Bridge dispatches ui/initialize; bridge round-trips tools/call → /api/mcp/jsonrpc → result; bridge dispatches ui/notifications/tool-result; bridge ignores messages from non-iframe sources; bridge cleans up listener on dispose; bridge serializes JSON-RPC envelope correctly; bridge handles JSON-RPC error envelope.

### `ui/src/__tests__/GamePanel.test.tsx` (modify; existing tests retained + 2 new)

Feature-detection routes to `<McpAppFrame>` when `mcpAppHostEnabled`; falls back to existing TTT renderer when flag false.

---

## What this AD does NOT change (out of scope by design)

- No new agent / pool / IntentDescriptor (transport substrate + UI rendering only)
- No `GameEngine` Protocol change (`ChessEngine` implements existing Protocol verbatim)
- No `BaseAgent` / `IntentMessage` / `IntentResult` change
- No federation MCP server replacement (extends, doesn't replace)
- No threefold-repetition draw detection (deferred AD-597c-1; forcing function: ≥10 completed chess games persisted AND first operator-reported "draw should have been detected" incident)
- No HXI `CrewRosterPanel` migration to MCP App (mentioned as future candidate in AD spec; orthogonal scope)
- No native-shell packaging (out-of-repo, fleet-level surface)
- No fleet-wide MCP App distribution (out-of-repo, fleet-level surface)
- No new public REST endpoints beyond `/api/mcp/jsonrpc` + `/api/mcp/resource`
- No `ward_room/service.py` modification
- No modification to `RecreationService.create_game` / `make_move` / `forfeit_game` signatures (game_app.py wraps them)

---

## Tracking

- `PROGRESS.md` — Wave 102 close header (post-build)
- `docs/development/roadmap.md:5026` — flip `(planned, OSS)` → `(complete, OSS)` for AD-597
- `decisions-era-4-evolution.md:3596` — flip status marker (post-build)
- `prompts/wave-plan.yaml` — append W102 entry

## Acceptance criteria

- All ~80 new pytest tests pass (floor 70).
- All ~25 new vitest tests pass (floor 20).
- Full pytest gate at `-n 4 --dist=loadfile` shows ≥12431 passing (baseline 12361 + 70 floor; target 12441 +80 stretch).
- Existing 12361 passing tests continue to pass.
- Pre-commit hook simulation exits 0 (no banned-pattern hits).
- All changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-05-07)

```
git rev-parse HEAD
  c6f39c8

# Pytest baseline (verified):
d:/ProbOS/.venv/Scripts/pytest.exe --collect-only -q tests/
  12377 tests collected (12361 passing per Captain summary; 16 known skips)

# AD-449 outbound MCP client substrate (verified — extended in this AD):
Select-String -Path src\probos\integrations\mcp_bridge\__init__.py -Pattern "MCPBridge|MCPClient|MCPSession|MCPProtocolError"
  src/probos/integrations/mcp_bridge/__init__.py:7:  MCPBridge
  src/probos/integrations/mcp_bridge/__init__.py:8:  MCPClient, MCPProtocolError
  src/probos/integrations/mcp_bridge/__init__.py:9:  MCPSession

# AD-480a inbound MCP server (verified — extended in this AD):
Select-String -Path src\probos\federation\mcp_server.py -Pattern "^class FederationMCPServer|async def handle_jsonrpc|async def _handle_initialize|async def _handle_tools_list|async def _handle_tools_call|_project_tools_from_descriptors"
  src/probos/federation/mcp_server.py:31:  class FederationMCPServer
  src/probos/federation/mcp_server.py:125: async def handle_jsonrpc
  src/probos/federation/mcp_server.py:155: async def _handle_initialize
  src/probos/federation/mcp_server.py:174: async def _handle_tools_list
  src/probos/federation/mcp_server.py:182: async def _handle_tools_call
  src/probos/federation/mcp_server.py:244: def _project_tools_from_descriptors

# AD-526a Recreation framework (verified — wrapped, not modified):
Select-String -Path src\probos\recreation\engine.py -Pattern "^class GameEngine|^class TicTacToeEngine"
  src/probos/recreation/engine.py:9:  class GameEngine (Protocol)
  src/probos/recreation/engine.py:56: class TicTacToeEngine

Select-String -Path src\probos\recreation\service.py -Pattern "^class RecreationService|register_engine\(TicTacToeEngine"
  src/probos/recreation/service.py:15: class RecreationService
  src/probos/recreation/service.py:53: self.register_engine(TicTacToeEngine())

# Existing federation MCP server wiring (verified — sibling wirer added):
Select-String -Path src\probos\startup\finalize.py -Pattern "FederationMCPServer|federation_mcp_server|RecreationService"
  src/probos/startup/finalize.py:2450: from probos.federation.mcp_server import FederationMCPServer
  src/probos/startup/finalize.py:2451: runtime.federation_mcp_server = FederationMCPServer(
  src/probos/startup/finalize.py:2454: await runtime.federation_mcp_server.start()
  src/probos/startup/finalize.py:2960: from probos.recreation.service import RecreationService
  src/probos/startup/finalize.py:2961: runtime.recreation_service = RecreationService(

# Runtime attributes (verified — siblings added):
Select-String -Path src\probos\runtime.py -Pattern "federation_mcp_server|mcp_bridge"
  src/probos/runtime.py:259: federation_mcp_server: "FederationMCPServer | None"
  src/probos/runtime.py:552: self.federation_mcp_server: "FederationMCPServer | None" = None

# Greenfield path verification (verified non-existence):
git ls-files src/probos/mcp_apps/
  (no output — package does not exist; greenfield in v1)
git ls-files src/probos/recreation/chess_engine.py
  (no output — file does not exist; greenfield in v1)
git ls-files ui/src/components/McpAppFrame.tsx
  (no output — file does not exist; greenfield in v1)
git ls-files ui/src/mcpApps/
  (no output — directory does not exist; greenfield in v1)

# AD-526b GamePanel migration source (verified):
Test-Path ui/src/components/GamePanel.tsx
  True
(Get-Content ui/src/components/GamePanel.tsx | Measure-Object -Line).Lines
  202

# AD numbering verification:
# Highest stem: AD-696 (per Wave 101 archive prompts/archive/WAVE-101-DISPATCH.md)
# AD-597 pre-allocated: decisions-era-4-evolution.md:3596 + docs/development/roadmap.md:5026
# Wave 102 mints zero new AD numbers.
# Highest BF stem: BF-265 (per Wave 101 archive). Wave 102 mints zero new BF numbers.
```
