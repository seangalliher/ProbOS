# Build Prompt: Rename /model to /models and Add /registry Command (AD-356)

## Context

ProbOS currently has a `/model` command that shows the 3 LLM tiers (fast,
standard, deep) with their endpoints, models, and connection status. We want to:

1. **Rename** `/model` → `/models` (shows active tier configuration — what's currently wired up)
2. **Add** `/registry` — shows ALL available models across all sources with provider/hosting info

This gives the Captain two views: "what am I using right now" (`/models`) and
"what could I use" (`/registry`).

---

## Issue 1: Rename `/model` to `/models`

**Files:** `src/probos/experience/shell.py`

In the `COMMANDS` dict (around line 60), rename the entry:
```python
# Before:
"/model":     "Show LLM client type, endpoint, and tier config",
# After:
"/models":    "Show active LLM tier configuration (endpoints, models, status)",
```

In the `_dispatch_slash()` handler dict (around line 188), rename the entry:
```python
# Before:
"/model":   self._cmd_model,
# After:
"/models":  self._cmd_models,
```

Rename the method `_cmd_model` → `_cmd_models` (around line 766). Keep the
implementation identical — just rename the method.

---

## Issue 2: Add `/registry` Command

**Files:** `src/probos/experience/shell.py`, `src/probos/cognitive/copilot_adapter.py`

### 2a. Add `list_available_models()` to CopilotBuilderAdapter

Add an async method to `CopilotBuilderAdapter` in `copilot_adapter.py`:

```python
async def list_available_models(self) -> list[dict[str, str]]:
    """List all models available through the Copilot SDK.

    Returns a list of dicts with keys: id, name, provider, source.
    Requires the adapter to be started.
    """
    if not self._started or not self._client:
        return []
    try:
        raw_models = await self._client.list_models()
        results = []
        for m in raw_models:
            model_id = getattr(m, "id", "") or str(m)
            results.append({
                "id": model_id,
                "provider": _classify_provider(model_id),
                "source": "GitHub Copilot",
                "hosting": "external",
            })
        return results
    except Exception:
        logger.debug("Failed to list Copilot SDK models")
        return []
```

Also add a module-level helper function `_classify_provider()`:

```python
def _classify_provider(model_id: str) -> str:
    """Classify a model ID to its provider name."""
    model_lower = model_id.lower()
    if "claude" in model_lower:
        return "Anthropic"
    if "gpt" in model_lower:
        return "OpenAI"
    if "gemini" in model_lower:
        return "Google"
    if "qwen" in model_lower or "deepseek" in model_lower:
        return "Local/OSS"
    return "Unknown"
```

### 2b. Add `_cmd_registry()` to Shell

Register in `COMMANDS` dict:
```python
"/registry": "Show all available models across all sources (tiers, Copilot SDK, local)",
```

Register in `_dispatch_slash()` handler dict:
```python
"/registry": self._cmd_registry,
```

Implement the method. It should:

1. Collect **tier models** from the existing `llm_client.tier_info()` — these are
   the "Active" models. For each tier, create an entry with:
   - `id`: the model name from tier config
   - `provider`: use `_classify_provider()` from copilot_adapter
   - `source`: the base_url (endpoint), or "ProbOS Tier" generically
   - `hosting`: "proxy" if localhost, "external" otherwise
   - `tier`: which tier is using it (fast/standard/deep)
   - `status`: "active"

2. Collect **Copilot SDK models** — if `CopilotBuilderAdapter.is_available()`,
   create a temporary adapter, start it, call `list_available_models()`, stop it.
   Wrap in try/except. Mark these as `status: "available"`.

3. Render a Rich Panel with two sections:
   - **Active Models (Tier System)** — table with columns: Tier, Model, Provider, Endpoint, Status
   - **Available Models (Copilot SDK)** — table with columns: Model, Provider, Source, Hosting

   Use Rich `Table` for clean formatting.

Here's the implementation skeleton:

```python
async def _cmd_registry(self, arg: str) -> None:
    """Show all available models across all sources."""
    from rich.panel import Panel
    from rich.table import Table
    from probos.cognitive.copilot_adapter import CopilotBuilderAdapter, _classify_provider

    # Section 1: Active tier models
    client = self.runtime.llm_client
    tier_table = Table(title="Active Models (Tier System)", show_header=True, header_style="bold cyan")
    tier_table.add_column("Tier", style="bold")
    tier_table.add_column("Model")
    tier_table.add_column("Provider")
    tier_table.add_column("Endpoint")
    tier_table.add_column("Status")

    if isinstance(client, OpenAICompatibleClient):
        info = client.tier_info()
        for tier in ("fast", "standard", "deep"):
            ti = info[tier]
            reachable = ti.get("reachable")
            if reachable is True:
                status = "[green]connected[/green]"
            elif reachable is False:
                status = "[red]unreachable[/red]"
            else:
                status = "[dim]unknown[/dim]"
            tier_table.add_row(
                tier,
                ti["model"],
                _classify_provider(ti["model"]),
                ti["base_url"],
                status,
            )
    else:
        tier_table.add_row("—", "MockLLMClient", "—", "—", "[dim]mock[/dim]")

    self.console.print(tier_table)
    self.console.print("")

    # Section 2: Copilot SDK models
    if CopilotBuilderAdapter.is_available():
        sdk_table = Table(title="Available Models (Copilot SDK)", show_header=True, header_style="bold yellow")
        sdk_table.add_column("Model")
        sdk_table.add_column("Provider")
        sdk_table.add_column("Source")
        sdk_table.add_column("Hosting")

        try:
            adapter = CopilotBuilderAdapter()
            await adapter.start()
            try:
                models = await adapter.list_available_models()
            finally:
                try:
                    await adapter.stop()
                except Exception:
                    pass

            if models:
                for m in models:
                    sdk_table.add_row(m["id"], m["provider"], m["source"], m["hosting"])
            else:
                sdk_table.add_row("[dim]No models found[/dim]", "—", "—", "—")
        except Exception as e:
            sdk_table.add_row(f"[red]Error: {e}[/red]", "—", "—", "—")

        self.console.print(sdk_table)
    else:
        self.console.print("[dim]Copilot SDK not installed — no external models available[/dim]")
```

---

## Test Requirements

### New Tests (add to `tests/test_experience.py`)

1. **`test_help_includes_models_and_registry`** — Verify that `COMMANDS` dict
   contains `/models` and `/registry` but NOT `/model`.

2. **`test_cmd_models_shows_tier_info`** — Call `_cmd_models("")` on a shell
   with a mock runtime and verify it prints a Panel. (Adapt from the existing
   `/model` test if one exists.)

3. **`test_cmd_registry_mock_client`** — Call `_cmd_registry("")` with a mock
   runtime (MockLLMClient). Should print the tier table with "MockLLMClient".

### Update Existing Tests

4. Any test that references `/model` should be updated to `/models`.

---

## Files to Modify

- `src/probos/experience/shell.py` — Rename /model → /models, add /registry
- `src/probos/cognitive/copilot_adapter.py` — Add list_available_models(), _classify_provider()
- `tests/test_experience.py` — Update existing /model tests, add new tests

## Constraints

- Do NOT modify any other files
- Do NOT change the existing tier system or LLM client
- Use Rich Table for the /registry output (cleaner than manual string formatting)
- The /registry Copilot SDK section should fail gracefully if the SDK isn't installed or auth fails
- Keep _classify_provider() simple — it's a display helper, not a critical path
- Remember: shell commands need BOTH `COMMANDS` dict AND `_dispatch_slash()` handler dict entries
