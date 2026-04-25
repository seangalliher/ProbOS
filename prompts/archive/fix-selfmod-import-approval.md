# Fix: Self-Mod Import Approval + Design Prompt Awareness

## Problem

Self-mod agent design fails because the LLM generates code importing libraries not on the allowed_imports whitelist. The LLM doesn't know what's allowed, so it guesses — and often guesses wrong (e.g., `psutil`, `requests`). The validation correctly rejects these, but the user has no way to approve them.

## Three fixes

### Fix 1: Import approval flow in self-mod pipeline

When CodeValidator rejects an import, instead of failing immediately, give the user the choice to whitelist it.

**File:** `src/probos/cognitive/self_mod.py` — in `handle_unhandled_intent()`

After CodeValidator returns a validation failure containing "Forbidden import":

```python
validation = self._validator.validate(source_code, self._config)
if not validation.valid:
    # Check if failure is ONLY about forbidden imports
    forbidden_imports = [e for e in validation.errors if "Forbidden import" in e or "forbidden import" in e.lower()]
    other_errors = [e for e in validation.errors if e not in forbidden_imports]
    
    if forbidden_imports and not other_errors:
        # Only import issues — ask user for approval
        import_names = []
        for err in forbidden_imports:
            # Extract import name from error like "Forbidden import: psutil"
            parts = err.split(":")
            if len(parts) >= 2:
                import_names.append(parts[-1].strip())
        
        if import_names and self._import_approval_fn:
            approved = await self._import_approval_fn(import_names)
            if approved:
                # Add to config's allowed_imports and retry validation
                for name in import_names:
                    if name not in self._config.allowed_imports:
                        self._config.allowed_imports.append(name)
                # Re-validate with expanded whitelist
                validation = self._validator.validate(source_code, self._config)
                if validation.valid:
                    # Continue with sandbox testing
                    pass
                else:
                    # Still failing for other reasons
                    return DesignedAgentRecord(..., status="validation_failed", error=f"Validation: {'; '.join(validation.errors)}")
            else:
                return DesignedAgentRecord(..., status="validation_failed", error=f"User declined imports: {', '.join(import_names)}")
```

**Constructor:** Add `import_approval_fn` parameter to `SelfModificationPipeline.__init__()`, similar to existing `user_approval_fn`.

**Runtime wiring:** In `runtime.py`, wire the import approval function. For the API path, emit a WebSocket event and wait for response. For the CLI path, prompt in the terminal.

### Fix 2: HXI import approval UX

**File:** `src/probos/api.py` — in `_run_selfmod()`

When the pipeline needs import approval, emit a WebSocket event with the import names and wait for user response:

```python
runtime._emit_event("self_mod_import_approval", {
    "intent": req.intent_name,
    "imports": import_names,
    "message": f"The new agent needs these imports: {', '.join(import_names)}. Allow?",
})
```

**File:** `ui/src/store/useStore.ts` — handle `self_mod_import_approval` event

Show approval buttons in the chat thread:
```
"The new agent needs 'psutil' (system monitoring). Allow this import?"
[✅ Allow] [❌ Block]
```

Clicking Allow sends `POST /api/selfmod/approve-imports` with the import names.

**Simpler approach for now:** Instead of a back-and-forth WebSocket approval, just auto-approve imports on the allowed_imports whitelist expansion AND persist the change to config. The user already approved the agent design — approving the imports is a reasonable default. Show the user what was whitelisted:

```
"✅ Added 'psutil' to allowed imports. Retrying validation..."
```

### Fix 3: Include allowed imports in the design prompt

**File:** `src/probos/cognitive/agent_designer.py` — in `AGENT_DESIGN_PROMPT`

Add a section listing what imports are available, so the LLM designs within constraints:

```python
ALLOWED_IMPORTS_SECTION = """
## AVAILABLE IMPORTS

You may ONLY use these Python imports in your agent code:

Standard library: os, sys, json, re, math, time, datetime, pathlib, urllib, asyncio, 
    collections, dataclasses, typing, hashlib, base64, io, csv, xml.etree.ElementTree,
    html, string, textwrap, functools, itertools, copy, uuid, logging, tempfile,
    subprocess, shutil, glob, fnmatch, stat, struct, decimal, fractions, random,
    secrets, bisect, heapq, operator, contextlib, abc, enum, http

Third-party (if installed): httpx, feedparser, bs4, lxml, chardet, yaml, toml, 
    pandas, numpy, openpyxl, markdown, jinja2, dateutil, tabulate, psutil, pydantic

ProbOS internals: probos.types, probos.substrate.agent, probos.cognitive.cognitive_agent

Do NOT import anything not on this list. If you need functionality from a library 
not listed, use the mesh to dispatch a sub-intent instead (e.g., http_fetch for 
web requests, run_command for system commands).
"""
```

Inject this into the design prompt so Sonnet knows the constraints upfront. This prevents most validation failures.

**Also update the allowed_imports in config/system.yaml** to include `psutil` and other commonly needed packages.

### Fix 4: Persist whitelist changes

When a user approves a new import, save it to the config:

**File:** `config/system.yaml` — the `allowed_imports` list should be updated at runtime and persisted so the approval carries across restarts.

Store approved imports in the KnowledgeStore or a separate `~/.probos/approved_imports.json` file that's loaded at boot and merged with the config whitelist.

## Interaction Principle: Agentic First, Controls Available

**Like a cockpit: autopilot flies the plane, but all controls are within reach if the pilot needs them.**

The PRIMARY path for import approval is **conversational** — it happens naturally within the self-mod flow:
1. Validation fails on a forbidden import
2. ProbOS shows in the chat: "This agent needs 'psutil' for system monitoring. Allow?" [✅ Allow] [❌ Block]
3. User clicks Allow → import whitelisted → design continues
4. The user never has to know what a "whitelist" is or where to find it

The SECONDARY path is **direct control** — slash commands and settings for power users who want to manage things manually:
- `/imports` — view whitelisted imports
- `/imports add <name>` — manually add
- `/imports remove <name>` — manually remove
- "What imports have I approved?" works as natural language too

Both paths must exist. The user should never NEED the secondary path, but it's always there. Autopilot handles 99% of flights. The yoke is still in front of you.

1. **Fix 3 first** (include imports in design prompt) — prevents most failures, zero UX complexity
2. **Fix 4** (add psutil + common packages to system.yaml) — immediate unblock
3. **Fix 1 + Fix 2** (interactive approval) — fuller solution, more work

## After fix

1. Run tests: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
2. Test: "Monitor my CPU usage" → should either succeed (psutil now whitelisted) or show approval prompt
3. Test: "Send an email" → should trigger self-mod and either design with allowed imports or ask for approval
4. Test: `/imports` in chat → should show current whitelist
5. Test: `/imports remove psutil` → should remove it and confirm
6. Test: `/imports add psutil` → should add it back

## Fix 5: /imports command for whitelist management

**Add a `/imports` slash command** so users can see and manage their whitelist:

- **`/imports`** — list all currently whitelisted imports, grouped by category (stdlib, third-party, probos internals). Show which ones were auto-approved during self-mod vs. configured in system.yaml
- **`/imports add <name>`** — add an import to the whitelist. Persists to config
- **`/imports remove <name>`** — remove an import from the whitelist. Persists to config. Warn if any existing designed agents use this import: "Warning: removing 'psutil' — the 'monitor_system_metrics' agent uses it. Remove anyway? (y/N)"

This should work from both the CLI shell AND the HXI chat (via the slash command handler in `api.py` which delegates to the shell).

**File:** `src/probos/experience/shell.py` — add `/imports` to COMMANDS dict and implement `_cmd_imports()` handler

The whitelisted imports should be persisted to `~/.probos/approved_imports.json` or merged into the KnowledgeStore so they survive restarts.
