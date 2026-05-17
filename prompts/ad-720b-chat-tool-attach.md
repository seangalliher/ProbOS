# AD-720b — Chat tool attach (BrowserTool, MCP)

**Status:** ready-to-build
**Closes:** #550
**Estimated tests:** +10 pytest +4 vitest
**Depends on:** AD-423a/AD-423b/AD-423c (tool permission stack — shipped), AD-706 (BrowserTool), AD-449 (MCP bridge — shipped)
**Independent of:** AD-721d-3, AD-721g, AD-721h, AD-721i-2

---

## ⚠️ Scope clarification (Required — read first)

**The Architect's pre-flight uncovered a brief-vs-issue mismatch.** The Wave 167 dispatch brief described AD-720b as "Captain attaches a tool output (browser session screenshot, MCP resource) to a DM via attachment marker." **The actual issue #550 body says:**

> Lets the Captain attach AD-706 BrowserTool / AD-449 MCP tools to a chat surface as **scoped capability grants**. Permission-layer change via AD-423a/AD-423c.

These are different features. The screenshot-attach path **already works** today (BrowserTool writes screenshots to AttachmentStore via `tools/browser/compute_use.py:174-176` and they ride existing `attachment_ids` in chat). The real gap is **in-chat capability granting** — letting the Captain say "give Echo BrowserTool read access for the next 2 hours" without leaving the chat surface.

This prompt builds **per the issue body**, not per the dispatch brief paraphrase. If the Captain wants the attachment-marker feature, that should be a separate AD (probably AD-720c). Flag to Captain in pass-1 review.

---

## Problem

`ToolPermissionStore.issue_grant` (`src/probos/tools/permissions.py:110`) is the persistence layer. The Captain interacts with it today via the `/tool-access grant ...` slash command in the shell (`experience/commands/commands_tool_access.py:29`). In the HXI DM surface, there is no equivalent — the Captain has to drop out of the chat to grant a tool to the agent they're chatting with.

## Solution

Two-part wire:

1. **API endpoint** `POST /api/chat/tool-grant` — accepts `{agent_id, tool_id, permission, duration_hours?, reason?}`, calls `ToolPermissionStore.issue_grant(...)`, returns the grant record. Captain identity is `issued_by="captain"` (matches the existing slash-command pattern; HXI runs in the Captain's process context).
2. **HXI surface** — a slash-command-like input `/grant <tool_id> <permission> [hours]` inside the DM composer, parsed client-side; on submit, POSTs to the new endpoint with the DM's target agent as `agent_id`. Renders the resulting grant inline as a system-styled message bubble ("Granted BrowserTool read to Echo for 2h").

MCP tools follow the same pattern. Their `tool_id` shape is `mcp:<server_name>` (existing convention — grep to confirm in `federation/mcp_server.py` references; if not formalized, this AD introduces the namespace).

This is a **permission-layer** change, not an attachment-vocabulary change. AD-720 (attachments) is unrelated.

---

## Section 1 — Config

No new config. Reuse:
- `cfg.tools.permissions_enabled` (gate — grep `src/probos/config.py` for the exact field; if absent, the endpoint always operates because `ToolPermissionStore` runs unconditionally today)
- `cfg.chat.enabled` (DM surface gate)

If permissions feature is not gated by a config flag today, this AD does **not** introduce one. Grant issuance is already audited and reversible.

## Section 2 — Pydantic model

In `src/probos/api_models.py`:

```python
class ChatToolGrantRequest(BaseModel):
    """AD-720b: in-chat tool capability grant.

    Captain grants an agent scoped access to a registered tool (BrowserTool
    via AD-706, MCP servers via AD-449) from inside a DM, without leaving
    the chat surface.
    """
    agent_id: str = Field(..., min_length=1)
    tool_id: str = Field(..., min_length=1)
    permission: str = Field(..., description="one of ToolPermission enum values")
    duration_hours: float | None = Field(default=None, ge=0.0, le=720.0)
    reason: str = Field(default="", max_length=500)
```

## Section 3 — Endpoint

In `src/probos/routers/chat.py` (or a new `routers/tools.py` — grep first; if `routers/tools.py` doesn't exist, putting it in `chat.py` keeps the chat-surface coupling explicit):

```python
@router.post("/chat/tool-grant")
async def chat_tool_grant(
    req: ChatToolGrantRequest,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """AD-720b: Captain issues a scoped tool grant from inside a DM."""
    from probos.tools.permissions import ToolPermission

    # Agent must be registered (real registry, not MagicMock — BF-287).
    if runtime.registry.get(req.agent_id) is None:
        raise HTTPException(status_code=404, detail=f"Agent {req.agent_id} not found")

    # Permission must be a valid enum value.
    try:
        perm = ToolPermission(req.permission)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail={"reason": "invalid_permission", "valid": [p.value for p in ToolPermission]},
        )

    # Tool must be registered (BrowserTool, MCP, or a configured tool_id).
    # If the tool registry doesn't exist on runtime yet, accept any non-empty
    # tool_id but log a warning — the grant is still useful as an audit
    # artifact, and ToolPermissionStore.issue_grant doesn't validate either.
    tool_registry = getattr(runtime, "tool_registry", None)
    if tool_registry is not None and not tool_registry.has(req.tool_id):
        raise HTTPException(
            status_code=404,
            detail={"reason": "tool_not_found", "tool_id": req.tool_id},
        )

    store = getattr(runtime, "tool_permission_store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="tool_permission_store_unavailable")

    expires_at: float | None = None
    if req.duration_hours is not None and req.duration_hours > 0:
        import time
        expires_at = time.time() + req.duration_hours * 3600.0

    grant = await store.issue_grant(
        agent_id=req.agent_id,
        tool_id=req.tool_id,
        permission=perm,
        reason=req.reason,
        issued_by="captain",
        expires_at=expires_at,
    )

    try:
        runtime.emit_event(
            "tool_grant_issued",
            {
                "grant_id": grant.id,
                "agent_id": grant.agent_id,
                "tool_id": grant.tool_id,
                "permission": grant.permission.value,
                "expires_at": grant.expires_at,
                "issued_by": grant.issued_by,
                "source": "chat",
            },
        )
    except Exception:
        logger.warning("AD-720b: emit_event('tool_grant_issued') failed", exc_info=True)

    return {
        "grant_id": grant.id,
        "agent_id": grant.agent_id,
        "tool_id": grant.tool_id,
        "permission": grant.permission.value,
        "expires_at": grant.expires_at,
        "issued_at": grant.issued_at,
    }
```

**Verify-first pre-build:** confirm `runtime.tool_permission_store` is the actual attribute name on `ProbOSRuntime`. Grep `src/probos/runtime.py` for `tool_permission_store|ToolPermissionStore`. If the attribute name differs, use the real one — do NOT assume.

## Section 4 — HXI surface

In `ui/src/components/IntentSurface.tsx` (the DM composer):

- Parse `/grant <tool_id> <permission> [hours]` client-side BEFORE the normal "send DM" path. Recognized format: leading `/grant ` (note trailing space).
- On match: POST `/api/chat/tool-grant` with `agent_id` taken from the current DM target. Don't send the slash command as a chat message.
- Render the response inline as a system-styled message ("Granted `BrowserTool` `read` to `Echo` (expires in 2h)") — a new message type or a sentinel sender (e.g. `sender_id="__system__"`).
- On 422 (invalid permission) or 404 (tool/agent not found): inline error message; the typed text stays in the composer so the Captain can correct it.

Existing example of slash-command parsing in the HXI: grep `IntentSurface.tsx` for any `/` prefix handling. If none, AD-720b introduces the pattern.

## Section 5 — Tests

Pytest (`tests/test_ad720b_chat_tool_grant.py`, +10):
1. happy path — valid request → 200, grant persisted, `expires_at` set
2. happy path no duration → grant persisted with `expires_at=None`
3. agent missing → 404
4. invalid permission → 422 with `valid` enum list
5. tool_id missing from registry (when registry available) → 404
6. tool_id valid but registry absent → 200 with warning logged
7. permission_store missing → 503
8. duration > 720 hours → 422 from Pydantic validator
9. reason >500 chars → 422 from Pydantic validator
10. emit_event raises → grant still returned, warning logged (degraded audit, not blocking)

Use real `ToolPermissionStore` (with `:memory:` SQLite) per BF-287 — no MagicMock. Use real `AgentRegistry` with a single fake agent registered.

Vitest (`ui/src/__tests__/IntentSurface.toolGrant.test.tsx`, +4):
1. types `/grant BrowserTool read 2` + send → POSTs to `/api/chat/tool-grant` with `duration_hours=2`
2. types `/grant BrowserTool read` (no hours) + send → POSTs with `duration_hours=null`
3. 422 response → inline error rendered; composer text preserved
4. successful POST → system-styled inline message rendered

Per AD-738b: `cd ui; npm run build` must succeed and bundle hash must change.

---

## Section 6 — MCP tool_id namespace

If MCP `tool_id` shape isn't yet formalized: this AD introduces the convention `mcp:<server_name>[:<resource_path>]`. The `ToolPermissionStore` doesn't validate `tool_id` shape today, so this is purely a convention. Document in `docs/architecture/tool-permissions.md` (grep — if the doc exists, append; if not, defer the doc to a forward marker AD-720b-1 rather than create a new top-level doc).

---

## What This Does NOT Change

- `ToolPermissionStore` (`src/probos/tools/permissions.py`) — schema and method signatures untouched.
- `commands_tool_access.py` shell command — unchanged; both surfaces (shell + chat) call the same `issue_grant`.
- AD-720 attachment vocabulary — explicitly unrelated. The dispatch brief's "attachment marker" framing is wrong (see scope clarification above). If Captain wants that feature, file a new AD.
- BrowserTool / MCP server internals — unchanged. They consume grants via the existing `get_active_grants_sync` cache.
- DM message persistence — system-styled inline messages are client-side only in v1 (not persisted to ward-room threads). Persistence is a forward marker AD-720b-2.

## Tracking

- PROGRESS.md: append AD-720b, increment test count.
- DECISIONS.md: append AD-720b record (in-chat capability grants; reuses ToolPermissionStore; MCP namespace convention introduced; scope clarified vs. dispatch brief).
- Close #550 on merge with a comment noting the scope clarification.
- If Captain wants the attachment-output feature from the brief: file new issue, new AD number (probably AD-720c).

## Acceptance Criteria

- 10 new pytest + 4 new vitest tests pass under `-n 4 --dist=loadfile` AND `-n 0`.
- `cd ui; npm run build` succeeds — bundle hash changes (per AD-738b).
- Real `ToolPermissionStore`, real `AgentRegistry`, real `Config()` in tests — no MagicMock for OS-substrate APIs (BF-287).
- A grant issued via the chat endpoint is indistinguishable on disk from one issued via `/tool-access grant` — both have `issued_by="captain"`.
- No new pip / npm dependencies.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-17)

```
grep -n "class ToolPermissionStore" src/probos/tools/permissions.py
  39: class ToolPermissionStore:

grep -n "async def issue_grant" src/probos/tools/permissions.py
  110:    async def issue_grant(

grep -n "tool_access_grants" src/probos/tools/permissions.py
  20: CREATE TABLE IF NOT EXISTS tool_access_grants (

grep -n "/tool-access" src/probos/experience/shell.py
  300: "/tool-access": lambda: commands_tool_access.cmd_tool_access(rt, con, arg),

grep -n "cmd_tool_access" src/probos/experience/commands/commands_tool_access.py
  29: async def cmd_tool_access(runtime: Any, console: Any, args: str) -> None:

grep -n "screenshot" src/probos/tools/browser/compute_use.py
  154:     png_bytes = await page.screenshot()
  174:     screenshot_ref = hashlib.sha256(png_bytes).hexdigest()
  176:     await store.write(screenshot_ref, png_bytes, "image/png")
  (^ confirms screenshot-to-AttachmentStore already works; brief's "attach" feature is redundant)

grep -n "MCPServerConfig\|mcp_server" src/probos/config.py
  1889:    mcp_server: FederationMCPServerConfig = Field(
  2580: class MCPServerConfig(BaseModel):
  2581:    """One MCP server registration entry (AD-449)."""

grep -n "class MCPServer\|mcp_app_registry" src/probos/federation/mcp_server.py
  179:        registry = getattr(self._runtime, "mcp_app_registry", None)
  195:        registry = getattr(self._runtime, "mcp_app_registry", None)
```
