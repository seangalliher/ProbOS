# AD-268: AgentDesigner `_mesh_fetch()` Template — Route HTTP Through Mesh

## Problem

The `AGENT_DESIGN_PROMPT` web-fetching template teaches designed agents to use raw `httpx.AsyncClient` in `perceive()`. This creates two problems:

1. **Duplicate API calls** — the sandbox test and auto-retry both invoke `perceive()`, making 2 HTTP calls in rapid succession. With pool size > 1, it's N×2 calls. This triggers API rate limits (observed: CoinGecko 429).
2. **Governance bypass** — designed agents call external APIs directly, bypassing the mesh's consensus, trust scoring, and event logging. Bundled agents route all HTTP through `_mesh_fetch()` → `intent_bus.broadcast(IntentMessage(intent="http_fetch"))` → `HttpFetchAgent`. The designed agents should follow the same pattern.

## Design

Replace the httpx template with a `_mesh_fetch()` template. The designed agent calls `_mesh_fetch(self._runtime, url)` instead of using `httpx.AsyncClient` directly. This routes through the existing `HttpFetchAgent` pool — one request, governed, logged.

### Why this fixes the rate limit

- **Sandbox test:** agent instantiated without `runtime=` → `self._runtime is None` → `_mesh_fetch()` returns `None` → `fetched_content = "FETCH_ERROR: no runtime available"` → agent handles error gracefully → sandbox passes (structure verified)
- **Auto-retry (real execution):** agent has `runtime=self` → `_mesh_fetch()` calls `intent_bus.broadcast()` → `HttpFetchAgent` makes **one** HTTP call → result returns through mesh → agent parses it

The sandbox no longer makes real HTTP calls. The real execution routes through the existing HttpFetchAgent (which is already rate-limit safe at 8s timeout).

## Implementation

### File: `src/probos/cognitive/agent_designer.py`

Replace the web-fetching template AND the perceive() example in `AGENT_DESIGN_PROMPT`. Two sections need changing:

**1. Replace the perceive() example** (the `Example perceive() override for web-fetching agents` block):

Old:
```python
  async def perceive(self, intent) -> dict:
      import httpx
      params = intent.params if hasattr(intent, 'params') else intent.get('params', {})
      url = params.get("url", "https://example.com")
      fetched_content = ""
      try:
          async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
              resp = await client.get(url)
              resp.raise_for_status()
              fetched_content = resp.text[:8000]
      except Exception as e:
          fetched_content = f"FETCH_ERROR: {e}"
      obs = await super().perceive(intent)
      obs["fetched_content"] = fetched_content
      return obs
```

New:
```python
  async def perceive(self, intent) -> dict:
      from probos.types import IntentMessage as _IM
      params = intent.params if hasattr(intent, 'params') else intent.get('params', {})
      url = params.get("url", "https://example.com")
      fetched_content = ""
      if self._runtime and hasattr(self._runtime, 'intent_bus'):
          msg = _IM(intent="http_fetch", params={"url": url})
          results = await self._runtime.intent_bus.broadcast(msg)
          for r in results:
              if r.success and r.result:
                  body = r.result
                  if isinstance(body, dict):
                      body = body.get("body", body.get("content", str(body)))
                  fetched_content = str(body)[:8000]
                  break
      if not fetched_content:
          fetched_content = "FETCH_ERROR: runtime not available or fetch failed"
      obs = await super().perceive(intent)
      obs["fetched_content"] = fetched_content
      return obs
```

**2. Replace the web-fetching TEMPLATE** (the full `TEMPLATE (web-fetching — ...)` block):

Old template uses `import httpx` and `httpx.AsyncClient`. Replace with:

```python
TEMPLATE (web-fetching — use when the intent needs live data from the internet):

\```python
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import IntentDescriptor, IntentMessage as _IM

class {class_name}(CognitiveAgent):
    \"\"\"Cognitive agent for {intent_name} (web-fetching via mesh).\"\"\"

    agent_type = "{agent_type}"
    _handled_intents = {{"{intent_name}"}}
    instructions = (
        "You are a specialist for {intent_name} tasks. "
        "You will receive fetched_content in the observation containing "
        "real data from the internet. Parse and structure this content. "
        "If fetched_content starts with FETCH_ERROR, report the error. "
        "Respond with a clear, structured answer."
    )
    intent_descriptors = [
        IntentDescriptor(
            name="{intent_name}",
            params={param_schema},
            description="{intent_description}",
            requires_consensus={requires_consensus},
            requires_reflect=True,
            tier="domain",
        )
    ]

    async def perceive(self, intent) -> dict:
        params = intent.params if hasattr(intent, 'params') else intent.get('params', {{}})
        # Construct the URL for your data source
        url = params.get("url", "https://example.com")
        fetched_content = ""
        if self._runtime and hasattr(self._runtime, 'intent_bus'):
            msg = _IM(intent="http_fetch", params={{"url": url}})
            results = await self._runtime.intent_bus.broadcast(msg)
            for r in results:
                if r.success and r.result:
                    body = r.result
                    if isinstance(body, dict):
                        body = body.get("body", body.get("content", str(body)))
                    fetched_content = str(body)[:8000]
                    break
        if not fetched_content:
            fetched_content = "FETCH_ERROR: unable to fetch data"
        obs = await super().perceive(intent)
        obs["fetched_content"] = fetched_content
        return obs

    async def act(self, decision: dict) -> dict:
        if decision.get("action") == "error":
            return {{"success": False, "error": decision.get("reason")}}
        llm_output = decision.get("llm_output", "")
        if "FETCH_ERROR" in llm_output:
            return {{"success": False, "error": llm_output}}
        return {{"success": True, "result": llm_output}}
\```
```

**3. Update the RULES section** — change the httpx rule:

Old: `- If you need HTTP requests, use httpx (it is whitelisted)`

New: `- For HTTP requests, route through the mesh via self._runtime.intent_bus.broadcast() as shown in the web-fetching template. Do NOT use httpx directly — the mesh provides governance, rate limiting, and deduplication.`

**4. Remove `import httpx` from the web-fetching template.** The agent no longer imports httpx — it uses the mesh. Remove httpx from being mentioned as the HTTP solution. Keep httpx in the allowed imports whitelist (other code may still need it legitimately).

### File: `src/probos/cognitive/code_validator.py`

No changes needed — `probos.types` is already in the allowed imports list. The `IntentMessage` import via `from probos.types import IntentMessage as _IM` will pass validation.

### File: `src/probos/cognitive/sandbox.py`

No changes needed — the sandbox doesn't pass `runtime=` to the agent, so `self._runtime` is `None`, and the `_mesh_fetch`-style code gracefully returns `FETCH_ERROR`. The sandbox still tests that the agent handles errors and returns an IntentResult.

## Tests

### File: `tests/test_agent_designer_cognitive.py`

Update tests that check the design prompt contains httpx references. Change assertions to check for mesh-fetch pattern instead:

1. Find any test that asserts `httpx` appears in the generated code or design prompt. Update to check for `intent_bus.broadcast` or `http_fetch` instead.
2. Add 1 new test: `test_design_prompt_uses_mesh_fetch_not_httpx` — verify the AGENT_DESIGN_PROMPT contains `intent_bus.broadcast` and does NOT contain `httpx.AsyncClient` in the templates.

### File: `tests/test_self_mod.py`

Check if any test depends on httpx being in the generated agent code. The MockLLMClient's `agent_design` pattern generates source code — verify it still uses valid imports. If the mock generates `import httpx`, update it to use the mesh pattern instead.

**IMPORTANT:** Check the MockLLMClient `agent_design` pattern in `src/probos/cognitive/llm_client.py`. If it generates agents with `import httpx`, update the generated code to use the mesh pattern. If it generates pure LLM agents (no perceive override), no change needed.

## PROGRESS.md

Update:
- Status line (line 3) test count
- Add AD-268 section before `## Active Roadmap`:

```
### AD-268: AgentDesigner Mesh-Fetch Template

**Problem:** Designed web-fetching agents used raw `httpx.AsyncClient` in `perceive()`, bypassing the mesh's governance (consensus, trust, event logging) and causing duplicate API calls (sandbox + auto-retry = 2 calls). This triggered rate limits on free-tier APIs.

| AD | Decision |
|----|----------|
| AD-268 | Replaced httpx template with mesh-fetch template in `AGENT_DESIGN_PROMPT`. Designed agents now route HTTP through `self._runtime.intent_bus.broadcast(IntentMessage(intent="http_fetch"))` — same pattern as bundled agents (AD-248). Sandbox test passes without making real HTTP calls (`self._runtime` is None → graceful FETCH_ERROR). All HTTP goes through HttpFetchAgent — governed, logged, deduplicated |

**Files changed:**

| File | Change |
|------|--------|
| `src/probos/cognitive/agent_designer.py` | Replaced httpx perceive() example and web-fetching template with mesh-fetch pattern. Updated RULES to direct agents to use mesh, not httpx directly |

NNNN/NNNN tests passing (+ 11 skipped).
```

Replace NNNN with actual count.

## Constraints

- Only touch `src/probos/cognitive/agent_designer.py` (and test files + PROGRESS.md)
- Do NOT modify `sandbox.py` — the sandbox correctly doesn't pass runtime, and that's now a feature
- Do NOT modify `runtime.py`
- Do NOT modify any bundled agent files
- Do NOT remove httpx from the allowed_imports whitelist — other code may need it
- Do NOT change the pure LLM reasoning template — only the web-fetching template
- Do NOT change `code_validator.py`
- Run tests after each edit: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
- Report the final test count
