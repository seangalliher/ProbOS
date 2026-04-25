# Phase 17 — Self-Mod Dependency Resolution

## Context

You are building Phase 17 of ProbOS, a probabilistic agent-native OS runtime. Read `PROGRESS.md` for full architectural context. Current state: **1187/1187 tests passing + 11 skipped. Latest AD: AD-209.**

ProbOS's self-modification pipeline can design agents that import third-party packages (if on the `allowed_imports` whitelist). But the pipeline doesn't check whether those packages are actually *installed*. The `CodeValidator` checks if the import is *allowed*, the `SandboxRunner` catches the `ImportError` at test time — but the failure is opaque. The user sees "sandbox failed" with no indication that a missing package is the cause, and no way to fix it.

This phase adds a **dependency resolution step** between validation and sandbox: detect missing-but-allowed packages, prompt the user for install approval, install via `uv add`, and retry the sandbox. It also expands the `allowed_imports` whitelist to cover common stdlib and third-party packages that agents will need for real-world tasks.

---

## Pre-Build Audit

Before writing any code, verify:

1. **Latest AD number in PROGRESS.md** — confirm AD-209 is the latest. Phase 17 AD numbers start at **AD-210**. If AD-209 is NOT the latest, adjust all AD numbers in this prompt upward accordingly.
2. **Test count** — confirm 1187 tests pass before starting: `uv run pytest tests/ -v`
3. **Pre-build cleanup (carried from Phase 16):** Verify `StrategyRecommender._compute_text_similarity()` in `src/probos/cognitive/strategy.py`. If it reimplements bag-of-words instead of using the shared `compute_similarity()` from `probos.cognitive.embeddings` (or `probos.mesh.capability`), replace it with the shared function. This is a bug fix, not a new AD. Run tests after this fix.
4. **Pre-build cleanup (carried from Phase 16):** Add the **MCP Federation Adapter** roadmap entry to PROGRESS.md. Place it after the existing "Multi-Participant Federation" entry and before "Abstract Representation Formation". Use the following text verbatim:

> - [ ] **MCP Federation Adapter — Protocol Bridge at the Mesh Boundary.** ProbOS federation currently uses ZeroMQ for node-to-node communication — fast, programmatic, but requires both endpoints to be ProbOS instances. An MCP (Model Context Protocol) adapter layer would expose each node's capabilities as MCP tool definitions, enabling discovery and invocation by any MCP-speaking system (VS Code extensions, other agent frameworks, third-party meshes). The principle: programmatic inside the brain, protocol between brains. The mesh boundary is the skull boundary.
>   - **`MCPServer` capability exposure** — maps `NodeSelfModel` capabilities to MCP tool schemas. Each `IntentDescriptor` becomes an MCP tool with its params, description, and consensus requirements as metadata. The mapping is mechanical: ProbOS already broadcasts structured capability profiles via Ψ gossip; MCP tool definitions are a different serialization of the same information. The server refreshes tool definitions when the runtime's intent descriptors change (new designed agents, new skills).
>   - **Inbound intent translation** — MCP tool calls are translated to `IntentMessage` and dispatched through `intent_bus.broadcast(federated=True)`. The existing loop prevention flag prevents re-federation. MCP-originated intents go through the same governance pipeline as any federated intent: consensus, red team verification, escalation. The MCP adapter is a transport, not a trust bypass.
>   - **MCP client trust** — MCP clients are treated as federated peers with configurable trust. New MCP clients start with probationary trust (same `Beta(alpha, beta)` prior as new agents — AD-110). Trust updates based on outcome quality of intents they submit. Destructive intents (write_file, run_command) from MCP clients always require full consensus regardless of accumulated trust. The `validate_remote_results` config flag applies.
>   - **Outbound MCP client** — allows ProbOS to discover and invoke capabilities on external MCP servers. External tool definitions are translated to `IntentDescriptor` and registered as federated capabilities. The `FederationRouter` can then route intents to MCP-connected systems alongside ZeroMQ-connected ProbOS nodes, using the same scoring logic. External capabilities carry federated trust discount (same δ factor from Trust Transitivity roadmap item).
>   - **Transport coexistence** — ZeroMQ remains the primary intra-Noöplex transport (fast, binary, low-latency). MCP serves the boundary between independent cognitive ecosystems. Both transports feed into the same `FederationRouter` and `intent_bus`. A node can simultaneously connect to ProbOS peers via ZeroMQ and to external systems via MCP. The `FederationBridge` becomes transport-polymorphic: a transport interface with ZeroMQ and MCP implementations.
>   - **Noöplex alignment** — this directly implements §3.2's embedding alignment at the protocol level: MCP tool schemas are the shared vocabulary, each mesh's internal representation is sovereign. §4.3.4's governance negotiation maps to MCP capability exposure: meshes choose what to expose (tool definitions), what trust to extend (authentication), and what constraints apply (consensus metadata). The long-term vision: if the Noöplex scales to heterogeneous meshes across organizations, MCP (or its successor) becomes the lingua franca for Layer 3/4 cross-mesh communication.

5. **Read these files thoroughly:**
   - `src/probos/cognitive/self_mod.py` — understand the full pipeline flow: config check → user approval → AgentDesigner → CodeValidator → SandboxRunner → register. The dependency resolution step inserts between CodeValidator and SandboxRunner
   - `src/probos/cognitive/code_validator.py` — understand AST import extraction, `allowed_imports` checking
   - `src/probos/cognitive/sandbox.py` — understand SandboxRunner flow, how ImportError manifests
   - `src/probos/cognitive/skill_designer.py` and `src/probos/cognitive/skill_validator.py` — the skill pipeline has the same gap (skills can import allowed packages that aren't installed)
   - `src/probos/config.py` — understand `SelfModConfig.allowed_imports`
   - `config/system.yaml`, `config/node-1.yaml`, `config/node-2.yaml` — current allowed_imports lists
   - `src/probos/experience/renderer.py` — understand user approval UX pattern (self-mod approval AD-123, escalation Tier 3 AD-93)

---

## What To Build

### Step 1: Expand `allowed_imports` in Config Files (AD-210)

**Files:** `config/system.yaml`, `config/node-1.yaml`, `config/node-2.yaml`

**AD-210: Expanded allowed_imports whitelist.** Replace the `allowed_imports` list in all three config files with the expanded list below. The list is organized by purpose with inline comments. The `allowed_imports` whitelist serves as both the code validation gate AND the install approval gate — if an import is allowed in code, it's allowed to be installed.

```yaml
  allowed_imports:
    # === Standard library — always available, no install needed ===
    # Core
    - asyncio
    - pathlib
    - json
    - os
    - sys
    - re
    - copy
    - enum
    - abc
    - typing
    - dataclasses
    - contextlib
    - functools
    - itertools
    - collections
    - logging
    - pprint
    # Strings & text
    - string
    - textwrap
    - difflib
    # Numbers & math
    - math
    - statistics
    - struct
    - decimal
    - fractions
    - random
    # Date & time
    - datetime
    - time
    - calendar
    # File & path
    - io
    - csv
    - tempfile
    - shutil
    - glob
    - fnmatch
    # Encoding & hashing
    - hashlib
    - base64
    - secrets
    - uuid
    # Web & parsing
    - urllib
    - urllib.parse
    - urllib.request
    - html
    - html.parser
    - xml
    - xml.etree
    - xml.etree.ElementTree
    # Data formats
    - tomllib
    - configparser
    # === Third-party — may need install via uv add ===
    # Web & HTTP
    - httpx
    - feedparser
    - bs4               # package: beautifulsoup4
    - lxml
    - chardet
    # Data formats
    - yaml              # package: pyyaml
    - toml
    # Data processing
    - pandas
    - numpy
    - openpyxl
    # Text & templates
    - markdown
    - jinja2
    # Date parsing
    - dateutil          # package: python-dateutil
    # Table formatting
    - tabulate
```

**Run tests: all 1187 must pass. Config changes should not affect test behavior.**

---

### Step 2: Dependency Resolver (AD-211, AD-212)

**File:** `src/probos/cognitive/dependency_resolver.py` (new)

**AD-211: `DependencyResolver` — detect missing packages and install via `uv add`.** A new module that sits between `CodeValidator` and `SandboxRunner` in the self-mod pipeline.

```python
class DependencyResolver:
    """Detects missing-but-allowed imports and installs them via uv add."""
    
    def __init__(self, allowed_imports: list[str], install_fn=None, approval_fn=None):
        """
        Args:
            allowed_imports: The whitelist from SelfModConfig
            install_fn: Optional override for package installation (for testing).
                        Signature: async (package_name: str) -> tuple[bool, str]
            approval_fn: Optional async callback for user approval.
                        Signature: async (packages: list[str]) -> bool
        """
```

Core methods:

- `detect_missing(source_code: str) -> list[str]` — parse imports from source code via AST, cross-reference each against `importlib.util.find_spec()`. Return list of import names that are on `allowed_imports` but not installed. Stdlib modules always pass `find_spec()`, so they never appear in the missing list. Handle dotted imports correctly: `from bs4 import BeautifulSoup` → check `bs4`; `from xml.etree import ElementTree` → check `xml` (top-level).

- `async resolve(source_code: str) -> DependencyResult` — orchestrates detection, approval, and installation:
  1. Call `detect_missing(source_code)` to get missing packages
  2. If none missing, return `DependencyResult(success=True, installed=[])`
  3. Map import names to package names via `IMPORT_TO_PACKAGE` (see below)
  4. Call `approval_fn(packages)` — if user declines, return `DependencyResult(success=False, declined=packages)`
  5. Install each via `_install_package(package_name)` — if any install fails, return with failure details
  6. Verify installation succeeded via `find_spec()` again
  7. Return `DependencyResult(success=True, installed=packages)`

- `async _install_package(self, package_name: str) -> tuple[bool, str]` — runs `uv add <package_name>` via `asyncio.create_subprocess_exec`. Returns `(success, output)`. Timeout: 60 seconds. Captures both stdout and stderr for error reporting.

**AD-212: Import-to-package name mapping.** A constant dict that maps Python import names to their `uv add` package names for cases where they differ. This is a Python ecosystem fact, not user config.

```python
IMPORT_TO_PACKAGE: dict[str, str] = {
    "bs4": "beautifulsoup4",
    "yaml": "pyyaml",
    "dateutil": "python-dateutil",
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "sklearn": "scikit-learn",
    "attr": "attrs",
    "dotenv": "python-dotenv",
}
# If an import name is NOT in this dict, the package name equals the import name
# (e.g., "feedparser" → "feedparser", "pandas" → "pandas")
```

**`DependencyResult` dataclass:**

```python
@dataclasses.dataclass
class DependencyResult:
    success: bool
    installed: list[str] = dataclasses.field(default_factory=list)
    declined: list[str] = dataclasses.field(default_factory=list)
    failed: list[str] = dataclasses.field(default_factory=list)
    error: str | None = None
```

**Run tests: all 1187 must pass.**

---

### Step 3: Wire into Self-Modification Pipeline (AD-213)

**File:** `src/probos/cognitive/self_mod.py`

**AD-213: Dependency resolution between validation and sandbox.** Insert `DependencyResolver.resolve()` into the `SelfModificationPipeline` flow for both agent design and skill design:

**Agent design flow (updated):**
1. Config check (max_designed_agents)
2. User approval for agent creation (AD-123) — existing
3. AgentDesigner generates code
4. CodeValidator static analysis
5. **NEW: DependencyResolver.resolve(source_code)** — detect missing packages, prompt user, install
6. SandboxRunner functional test
7. Register agent type, create pool

**Skill design flow (updated):**
1. SkillDesigner generates code
2. SkillValidator static analysis
3. **NEW: DependencyResolver.resolve(source_code)** — same step
4. importlib compilation
5. Skill object creation, add_skill_fn callback

If dependency resolution fails (user declined or install failed), abort the pipeline with a clear error message. Do NOT proceed to sandbox — it will just fail with ImportError.

**Constructor change:** `SelfModificationPipeline.__init__` accepts an optional `dependency_resolver: DependencyResolver` parameter. The runtime creates and passes it. If not provided (backward compat), the pipeline skips dependency resolution (same as current behavior).

**Approval callback wiring:** The `DependencyResolver`'s `approval_fn` should use the same async callback pattern as the existing agent creation approval (AD-123). The runtime passes the shell's user prompt callback to the resolver, same way it passes it to the pipeline.

**Run tests: all 1187 must pass. Existing self-mod tests must not break — they use MockLLMClient which generates code that only imports allowed stdlib packages, so `detect_missing()` returns an empty list and the pipeline proceeds as before.**

---

### Step 4: User Approval UX (AD-214)

**File:** `src/probos/experience/renderer.py` (or wherever the self-mod UX lives)

**AD-214: Dependency install approval prompt.** When `DependencyResolver` detects missing packages, the user sees a clear prompt:

```
This agent requires packages that are not installed:
  • feedparser
  • bs4 (beautifulsoup4)

Install with uv add? [y/n]:
```

The format is: `import_name (package_name)` — showing both so the user knows what the code imports and what gets installed. If import name equals package name, show just the name: `feedparser`. If they differ, show both: `bs4 (beautifulsoup4)`.

Use the same Rich console interaction pattern as the existing self-mod approval (AD-123) and escalation Tier 3 (AD-93) — the `pre_user_hook` pattern for Rich Live conflict avoidance if applicable.

After installation completes, display the result:

```
✓ Installed: feedparser, beautifulsoup4
Continuing with agent creation...
```

Or on failure:

```
✗ Failed to install: beautifulsoup4
  Error: [uv error output]
Agent creation aborted.
```

**Run tests: all 1187 must pass.**

---

### Step 5: Event Log Integration (AD-215)

**File:** `src/probos/cognitive/self_mod.py` or `src/probos/runtime.py`

**AD-215: Dependency resolution events.** Log to the event log:

- `dependency_check` — when `detect_missing()` runs. Data: `{source: "agent"|"skill", missing_count: int, missing: list[str]}`
- `dependency_install_approved` — when user approves installation. Data: `{packages: list[str]}`
- `dependency_install_declined` — when user declines. Data: `{packages: list[str]}`
- `dependency_install_success` — per-package success. Data: `{package: str, import_name: str}`
- `dependency_install_failed` — per-package failure. Data: `{package: str, error: str}`

Category: `"self_mod"` (same as other self-modification events).

**Run tests: all 1187 must pass.**

---

### Step 6: Tests (target: 1220+ total)

Write comprehensive tests across these test files:

**`tests/test_dependency_resolver.py`** (new) — ~25 tests:

*Detection:*
- `detect_missing()` returns empty list when all imports are stdlib
- `detect_missing()` returns empty list when third-party package is installed
- `detect_missing()` returns import name when package is not installed
- `detect_missing()` handles `import X` and `from X import Y` forms
- `detect_missing()` handles dotted imports (`from xml.etree import ElementTree` → checks `xml`)
- `detect_missing()` only checks imports on the `allowed_imports` list (not random imports)
- `detect_missing()` handles multiple missing packages
- `detect_missing()` with empty source code returns empty list
- `detect_missing()` with syntax-invalid code returns empty list (don't crash)

*Package name mapping:*
- `IMPORT_TO_PACKAGE` maps `bs4` → `beautifulsoup4`
- `IMPORT_TO_PACKAGE` maps `yaml` → `pyyaml`
- `IMPORT_TO_PACKAGE` maps `dateutil` → `python-dateutil`
- Import name not in mapping uses import name as package name
- Mapping is used during install step

*Resolution flow:*
- `resolve()` returns success with empty installed list when nothing missing
- `resolve()` calls `approval_fn` when packages are missing
- `resolve()` returns declined when user says no
- `resolve()` calls `_install_package()` after approval
- `resolve()` returns installed packages on success
- `resolve()` returns failed packages on install failure
- `resolve()` verifies installation via `find_spec()` after install

*Installation:*
- `_install_package()` calls `uv add <package_name>` (via mock)
- `_install_package()` returns `(False, error)` on subprocess failure
- `_install_package()` respects timeout

*DependencyResult:*
- `DependencyResult` default values are correct
- `success=True` when nothing to install
- `success=True` with installed list when packages installed
- `success=False` with declined list when user declines
- `success=False` with failed list when install fails

**Note on testing:** Do NOT actually run `uv add` in tests. Use the `install_fn` constructor parameter to inject a mock installer. Similarly, use `approval_fn` to inject mock user approval. All tests must be deterministic and offline.

**`tests/test_self_mod_deps.py`** (new) — ~8 tests:
- Pipeline skips dependency resolution when no `DependencyResolver` provided (backward compat)
- Pipeline calls `resolver.resolve()` after CodeValidator and before SandboxRunner
- Pipeline aborts on `DependencyResult(success=False, declined=...)`
- Pipeline aborts on `DependencyResult(success=False, failed=...)`
- Pipeline continues to sandbox on `DependencyResult(success=True)`
- Skill design pipeline also calls dependency resolution
- Event log records `dependency_check` event
- End-to-end: detect → approve → install → sandbox passes

**Update existing tests if needed** — check:
- `tests/test_self_mod.py` — ensure `SelfModificationPipeline` constructor still works without `dependency_resolver` param
- `tests/test_code_validator.py` — ensure expanded `allowed_imports` don't break existing validation tests

**Run final test suite: `uv run pytest tests/ -v` — target 1220+ tests passing (1187 existing + ~33 new). All 11 skipped tests remain skipped.**

---

## AD Summary

| AD | Decision |
|----|----------|
| AD-210 | Expanded `allowed_imports` whitelist: ~50 stdlib modules + 12 third-party packages covering web/parsing, data processing, text/templates, and date handling. `allowed_imports` is the single gate for both code validation and install approval |
| AD-211 | `DependencyResolver`: detects missing-but-allowed packages via `importlib.util.find_spec()`, orchestrates user approval and `uv add` installation. Async `install_fn` and `approval_fn` callbacks for testability |
| AD-212 | `IMPORT_TO_PACKAGE` constant dict maps import names to package names where they differ (`bs4` → `beautifulsoup4`, `yaml` → `pyyaml`, `dateutil` → `python-dateutil`). If not in dict, import name = package name |
| AD-213 | Dependency resolution inserted between CodeValidator and SandboxRunner in both agent and skill design flows. Pipeline aborts if resolution fails. Optional `dependency_resolver` param on `SelfModificationPipeline` for backward compat |
| AD-214 | User approval prompt shows import name + package name. Same interaction pattern as existing self-mod approval (AD-123). Success/failure feedback after install |
| AD-215 | Event log entries: `dependency_check`, `dependency_install_approved`, `dependency_install_declined`, `dependency_install_success`, `dependency_install_failed`. Category: `self_mod` |

---

## Do NOT Build

- **Auto-install without user approval** — every install requires explicit user consent
- **Package version pinning** — `uv add` handles version resolution; the resolver doesn't specify versions
- **Package removal / rollback** — if an agent is pruned, its installed packages stay. Cleanup is a future concern
- **Sandbox retry loop** — if sandbox fails after install for a non-import reason, the pipeline fails normally. No automatic retry
- **Changes to `CodeValidator`** — import allowlist checking is unchanged. The validator says "is this import allowed?" — the resolver says "is this import installed?"
- **Changes to `SandboxRunner`** — sandbox behavior is unchanged. It just won't hit ImportError anymore because dependencies are resolved first
- **Changes to the decomposer or PromptBuilder** — unchanged
- **New slash commands** — no new shell commands. Dependency resolution is part of the self-mod flow, not a standalone command
- **`pip install` support** — uv only. The project toolchain is uv throughout

---

## Milestone

Demonstrate the following end-to-end:

1. `allowed_imports` in system.yaml includes `feedparser` and `bs4`
2. `feedparser` is NOT currently installed (or simulate via mock)
3. User asks ProbOS something that triggers self-mod (e.g., "get me the latest news headlines")
4. AgentDesigner generates a CognitiveAgent that imports `feedparser`
5. CodeValidator passes (feedparser is on the allowed list)
6. DependencyResolver detects `feedparser` is not installed
7. User sees: `"This agent requires packages that are not installed: feedparser. Install with uv add? [y/n]:"`
8. User approves → `uv add feedparser` runs → success
9. SandboxRunner tests the agent → passes (feedparser now available)
10. Agent is registered and handles the intent
11. Event log shows: `dependency_check` (1 missing), `dependency_install_approved`, `dependency_install_success`

---

## Update PROGRESS.md When Done

Add Phase 17 section with:
- AD decisions (AD-210 through AD-215)
- Files changed/created table
- Test count (target: 1220+)
- Update the Current Status line at the top
- Update the What's Been Built tables for new/changed files
- Update the self_mod section description to mention dependency resolution
- Update the config.py description to mention expanded allowed_imports
- Note in the self-mod roadmap area that the pipeline now handles dependency installation
