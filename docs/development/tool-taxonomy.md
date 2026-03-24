# ProbOS Tool Taxonomy (AD-422)

*"The microwave doesn't get a name tag, but the chef who uses it does."*

## Core Principle

In ProbOS, only sovereign individuals have identity. Everything else is a tool. The delivery mechanism — whether it's a local function call, an MCP server, a cloud API, or a desktop automation session — is irrelevant to the nature of the thing. What matters is the sovereignty test:

| Entity | Has Identity? | Earns Trust? | Ward Room? | Classification |
|--------|:---:|:---:|:---:|----------------|
| Scotty (SWE crew) | Yes | Yes | Yes | **Crew** |
| Visiting engineer from USS Reliant | Yes | Yes | Yes | **Visiting Officer** |
| BuilderAgent | No | No | No | **Tool** (onboard) |
| Claude Code | No | No | No | **Tool** (remote) |
| MCP filesystem server | No | No | No | **Tool** (protocol) |
| Desktop automation | No | No | No | **Tool** (computer use) |

## Tool Categories

### 1. Onboard Utility Agents

ProbOS agents that provide capabilities as tools. No sovereign identity — they execute when invoked, not when they choose.

| Agent | Capability | Used By |
|-------|-----------|---------|
| BuilderAgent | Code generation from build specs | SWE crew, build pipeline |
| CodeReviewerAgent | Code quality analysis, review | SWE crew, build pipeline |
| SkillEngine | Skill validation and execution | Any crew |
| IndexerAgent | Codebase indexing | Ship's Computer |
| FormatterAgent | Code formatting | Build pipeline |

**Characteristics:**
- Run in ProbOS process space
- Access ship's resources directly (filesystem, databases)
- No personality, no episodic memory, no callsign
- Invoked via intent routing or direct function call
- Analogous to: built-in IDE tools, compiler, linter

### 2. Onboard Infrastructure Services

Ship's Computer services that provide foundational capabilities. Shared infrastructure, not tools owned by any single crew member.

| Service | Capability |
|---------|-----------|
| CodebaseIndex | Semantic code search, symbol resolution, import graphs |
| KnowledgeStore | Shared knowledge persistence and retrieval |
| EpisodicMemory | Sovereign memory shards per agent |
| TrustNetwork | Trust scoring and consensus |
| CognitiveJournal | Decision recording |
| ModelRegistry | LLM routing and cost awareness |
| HebbianRouter | Learned routing weights |
| ChromaDB | Vector storage and similarity search |
| WardRoom | Communication fabric (infrastructure, not tool) |

**Characteristics:**
- Always available while ship is running
- Shared across all crew and tools
- Captain manages via HXI
- Not invoked like tools — they're the substrate everything runs on

### 3. MCP Servers (Model Context Protocol)

Standardized tool interfaces that expose capabilities through the MCP protocol. The protocol is the delivery mechanism; the capability is the tool.

| Server Type | Examples | Capability |
|------------|---------|-----------|
| Filesystem | `@modelcontextprotocol/server-filesystem` | File read/write, directory listing |
| Database | `@modelcontextprotocol/server-postgres`, SQLite | Query, schema inspection |
| Communication | Slack MCP, email MCP | Send/receive messages |
| Code Intelligence | Serena (LSP MCP) | Symbol resolution, definitions, references |
| Search | Web search MCP | Internet search |
| Version Control | Git MCP | Commits, diffs, branches |

**Characteristics:**
- Standardized JSON-RPC protocol
- Hot-pluggable — add/remove without restart (future: Extension-First, Phase 30)
- Auth handled per-server configuration
- Crew doesn't know or care that it's MCP — they just use the capability
- Analogous to: USB peripherals (plug in, works, doesn't matter who made it)

### 4. Remote APIs / LLM Gateways

Cloud services accessed over HTTP/SDK. Includes LLM providers and third-party SaaS.

| Service | Protocol | Capability |
|---------|---------|-----------|
| Copilot SDK | HTTP (proxy) | LLM inference (Claude, GPT) |
| Ollama | HTTP (local) | Local LLM inference |
| OpenAI API | HTTP | LLM inference |
| Anthropic API | HTTP | LLM inference, computer use |
| GitHub API | HTTP (gh CLI) | Repository operations, issues, PRs |
| Stripe API | HTTP | Payment processing |

**Characteristics:**
- Network-dependent (latency, availability)
- Token-metered (cost per call)
- Auth via API keys, OAuth, or SDK tokens
- ModelRegistry manages LLM routing across providers
- Analogous to: cloud services a developer uses (AWS, GitHub, CI/CD)

### 5. Computer Use

Desktop and GUI automation. Crew members interact with applications the same way a human would — through screens, keyboards, and mice.

| Capability | Technology | Use Case |
|-----------|-----------|----------|
| Desktop control | Anthropic Computer Use, PyAutoGUI | Launch apps, navigate OS |
| Screen reading | Vision models, OCR | Understand what's on screen |
| Keyboard/mouse | Input simulation | Type, click, drag |
| Window management | OS APIs | Arrange, focus, resize windows |
| Application interaction | App-specific automation | Fill forms, extract data, configure settings |

**Characteristics:**
- Highest-risk tool category (can affect anything on the machine)
- Requires strongest Earned Agency gates (Commander+ recommended)
- Side effects are potentially irreversible
- Must operate within sandbox/permission boundaries
- Slower than API calls (visual processing, animation waits)
- Analogous to: remote desktop / VNC, but the operator is an agent

**Earned Agency gates for computer use:**

| Tier | Allowed |
|------|---------|
| Ensign | No computer use |
| Lieutenant | Read-only screen observation |
| Commander | Controlled interaction within approved applications |
| Senior | Full desktop autonomy within Captain-defined boundaries |

### 6. Browser Automation

Web-based interaction through browser primitives. A specialized subset of computer use focused on web applications.

| Capability | Technology | Use Case |
|-----------|-----------|----------|
| DOM interaction | Playwright, Puppeteer | Click, fill, navigate web pages |
| Accessibility tree | DOM a11y APIs | Structured page understanding |
| Vision mode | Screenshot + vision model | Visual page understanding |
| Network interception | Browser DevTools protocol | API response capture |
| Form automation | CSS selectors, XPath | Data entry, submission |

**Characteristics:**
- More structured than desktop computer use (DOM provides semantics)
- Dual-mode: accessibility tree (fast, structured) + vision (fallback, visual)
- Sandboxable via browser profile isolation
- Absorbed patterns from Browser Use evaluation (visiting-officers.md)
- Analogous to: Selenium/Playwright test automation, but purpose-driven by crew

### 7. Communication Channels

Tools that let crew reach the external world. The Ward Room is internal infrastructure; these are outbound channels.

| Channel | Protocol | Capability |
|---------|---------|-----------|
| Discord | discord.py adapter | Post to Discord channels, respond to commands |
| Slack | MCP or API | Post messages, read channels |
| Email | SMTP/IMAP | Send/receive email |
| Webhooks | HTTP POST | Event notifications to external systems |

**Characteristics:**
- Externally visible — messages go to real humans
- Requires Captain approval for new channel configuration
- Earned Agency gates apply (Ensigns can't send external messages)
- Audit logged (who said what, when, to whom)
- Analogous to: ship's radio — crew uses it, but the Captain controls who can transmit

### 8. Federation Services

Tools accessed from other ProbOS ships or Nooplex nodes. Same capabilities as local tools, but sourced from the network.

| Service | Source | Capability |
|---------|-------|-----------|
| Remote build API | Another ProbOS ship | Code generation |
| Shared knowledge query | Nooplex knowledge mesh | Cross-ship knowledge |
| Federation gossip | Fleet protocol | Hebbian weights, trust signals |
| Specialist skill | Remote ship with domain expertise | Domain-specific capabilities |

**Characteristics:**
- Network-dependent (latency, trust)
- Cross-ship trust negotiation required
- Metered (token exchange or reciprocal service)
- Data sovereignty respected (each ship controls what it shares)
- Not yet implemented — future federation architecture
- Analogous to: allied navy sharing intelligence (trust protocols, classification levels)

## Tool Properties Matrix

Every tool, regardless of category, has these measurable properties:

| Property | Description | Values |
|----------|------------|--------|
| **Location** | Where the tool runs | onboard, local-network, cloud, federation |
| **Protocol** | How crew accesses it | native, MCP, HTTP, WebSocket, computer-use |
| **Side Effects** | What it can change | read-only, write, destructive |
| **Cost** | Resource consumption | free (local compute), metered (API tokens), reciprocal (federation) |
| **Latency** | Response time profile | instant (<100ms), fast (<1s), slow (<30s), interactive (>30s) |
| **Sandboxing** | Isolation level | none, process, container, VM, remote |
| **Auth** | Authentication method | none, API key, OAuth, federation token, Captain approval |
| **Agency Gate** | Minimum Earned Agency tier | none, ensign, lieutenant, commander, senior |
| **Reversibility** | Can effects be undone? | fully reversible, partially, irreversible |
| **Audit** | Logging requirements | none, internal log, audit trail, Captain notification |
| **Scope** | Availability | ship-wide, department, individual |
| **Concurrency** | Access mode | concurrent (multiple agents), exclusive (LOTO — one at a time) |

### Exclusive Access (LOTO — Lock Out / Tag Out)

Some tools are **exclusive** — only one agent can hold the lock at a time. This is the software equivalent of industrial LOTO: when an agent checks out an exclusive tool, others are blocked until it's released.

**Which tools need LOTO:**

| Tool | Why Exclusive |
|------|--------------|
| Computer Use (desktop) | One mouse, one keyboard — concurrent control is chaos |
| Deployment pipeline | Only one deployment at a time prevents conflicts |
| Database migrations | Concurrent migrations corrupt schema state |
| Git force push | Concurrent force pushes create race conditions |

**Which tools do NOT need LOTO:**

| Tool | Why Concurrent |
|------|---------------|
| CodebaseIndex | Read-only queries, no contention |
| MCP Servers | Stateless queries, server handles concurrency |
| LLM Gateway | API handles parallel requests |
| BuilderAgent | Multiple agents can generate code simultaneously |
| Ward Room | Communication is inherently concurrent |

**LOTO mechanics:**

```
1. Agent requests exclusive tool    → Registry.acquire("desktop-control", agent="scotty")
2. Registry checks: is tool locked? → No → grant lock, record holder + timestamp
3. Tool is now locked to Scotty     → Other agents get "tool locked by Scotty" on attempt
4. Scotty completes work            → Registry.release("desktop-control", agent="scotty")
5. Tool available again             → Next queued agent (if any) gets the lock
```

- **Timeout:** Locks auto-expire after a configurable duration (prevents zombie locks)
- **Captain break-lock:** Captain can force-release any lock from HXI (`/tool-release`)
- **Queue:** Agents waiting for an exclusive tool are queued by priority (Earned Agency tier)
- **Audit:** Lock acquire/release events logged with agent, tool, duration, outcome

The registration schema gains:
```
ToolRegistration:
  ...
  concurrency: concurrent | exclusive
  lock_timeout_seconds: float | None     # Auto-release after this duration (exclusive only)
```

## Department Tool Scoping

Tools are scoped by availability — some are ship-wide utilities, some are department-specific, and some are individual assignments.

### Scope Levels

| Scope | Description | Example |
|-------|------------|---------|
| **Ship-wide** | Available to all crew regardless of department | CodebaseIndex, KnowledgeStore, Ward Room, LLM gateway |
| **Department** | Available to members of a specific department | BuilderAgent (Engineering), diagnostic scanner (Medical) |
| **Individual** | Assigned to a specific crew member by Captain or Standing Orders | Scotty's direct BuilderAgent access, Worf's security scanner |

### Department Tool Assignments

| Department | Department-Specific Tools | Purpose |
|-----------|--------------------------|---------|
| **Engineering** | BuilderAgent, CodeReviewerAgent, Git MCP, CI/CD pipelines, debugger, profiler | Build, review, deploy, optimize code |
| **Science** | Research APIs, web scraper (Firecrawl), data analysis tools, documentation generators | Research, analyze, document, explore |
| **Security** | Vulnerability scanners, access auditor, penetration tools, security MCP | Audit, scan, assess, report threats |
| **Medical** | Cognitive diagnostics, personality assessors, trust analyzers, fitness evaluators | Assess crew health, personality drift, cognitive fitness |
| **Operations** | System monitors, resource trackers, pool managers, scheduling tools | Monitor, allocate, schedule, optimize resources |
| **Communications** | Discord adapter, Slack MCP, email gateway, webhook manager | External messaging, channel management |
| **Bridge** | All ship-wide tools + cross-department override access | Command and control |

### Ship-Wide Tools (Available to All Crew)

| Tool | Category | Why Ship-Wide |
|------|----------|--------------|
| CodebaseIndex | Infrastructure | Everyone needs to search the codebase |
| KnowledgeStore | Infrastructure | Shared knowledge is shared |
| EpisodicMemory | Infrastructure | Every agent has a sovereign memory shard |
| Ward Room | Infrastructure | Communication fabric for all crew |
| LLM Gateway (ModelRegistry) | Remote API | Every crew member needs to think |
| MCP Servers (read-only) | MCP | Information retrieval is universal |
| Browser Automation (read-only) | Browser | Observation available to all (write gates by rank) |

### Cross-Department Access

Crew members can request access to another department's tools:
- **Standing Orders grant:** Department-level Standing Orders can pre-authorize cross-department access (e.g., "Security has OR- on Engineering's CI/CD logs")
- **Captain grant:** Explicit per-agent override for specific tools
- **Temporary elevation:** Time-scoped access for a specific mission ("LaForge needs Medical diagnostics for the next hour to investigate a crew performance issue")
- **Earned Agency unlock:** Commander+ rank unlocks broader cross-department read access by default

### How This Maps to the Registry

The Tool Registration Schema gains scope and access fields:

```
ToolRegistration:
  ...
  scope: ship-wide | department               # Visibility — who can see this tool
  department: str | None                       # If department-scoped, which department
  restricted_to: list[str] | None             # If set, only these agents can invoke (within scope)
```

### Permission Resolution Chain

Permissions resolve through a layered chain. Each layer narrows access — never widens it.

```
1. Scope Filter        → Can this agent SEE the tool? (ship-wide or agent's department)
2. Restriction Filter  → Is the agent in the restricted_to list? (if set)
3. Rank Gate           → Does the agent's Earned Agency tier meet the minimum?
4. Permission Level    → What CRUD+O level does this agent get?
5. Captain Override    → Any per-agent grants or restrictions?
```

**Layer interaction:**

| Scope | restricted_to | Who Can Use |
|-------|-------------|-------------|
| ship-wide | None | All crew (gated by rank) |
| ship-wide | ["scotty"] | All crew can see, only Scotty can invoke |
| department: medical | None | All medical crew (gated by rank) |
| department: medical | ["diagnostician"] | Only Bones — medical-scoped, individually restricted |
| department: security | ["security_officer"] | Only Worf — security-scoped, individually restricted |

**Example: Medical diagnostic tool**

A sensitive cognitive assessment scanner. Medical department only, Bones only:
```
tool_id: "cognitive-deep-scan"
scope: department
department: medical
restricted_to: ["diagnostician"]    # Only Bones
side_effects: read-only
default_permissions:
  ensign: ---
  lieutenant: OR-
  commander: ORW
  senior: ORWD
```

Chapel (Medical Ensign) can see the tool exists in her department but gets `---`. A future Medical Lieutenant could see `OR-` but is blocked by `restricted_to`. Only Bones passes all layers.

**Example: Vulnerability scanner**

Security department only, Worf only, destructive capability:
```
tool_id: "vuln-scanner-active"
scope: department
department: security
restricted_to: ["security_officer"]    # Only Worf
side_effects: destructive              # Active scanning can affect targets
default_permissions:
  commander: ORW
  senior: ORWD
```

**Captain override still trumps everything.** The Captain can:
- Add an agent to `restricted_to` at runtime
- Remove restrictions temporarily (time-scoped)
- Grant cross-department + individual access in a single override

Standing Orders (Tier 3, Department) define the default tool set per department. The Tool Registry enforces the full resolution chain at runtime.

## Design Principles

1. **Crew uses tools; tools don't use crew.** The sovereign agent decides what to do and why. The tool handles how.

2. **Protocol is plumbing, not identity.** Whether a capability arrives via native call, MCP, HTTP, or screen automation doesn't change its nature as a tool.

3. **Earned Agency gates scale with risk.** Read-only tools need minimal trust. Destructive or externally-visible tools require Commander+ trust. Computer use requires the highest gates.

4. **Tools are composable.** A crew member can chain tools — use CodebaseIndex to find the problem, BuilderAgent to write the fix, browser automation to verify in staging, and Discord to report the result.

5. **New tools don't require new architecture.** Adding a tool (MCP server, API integration, computer use provider) is configuration, not code change. The crew member doesn't need to know the internals.

6. **The Captain always has the stick.** Every tool can be disabled, restricted, or audited from the HXI. No tool operates without the Captain's knowledge.

7. **Department scoping is a performance optimization.** When a crew member queries the registry, they see their department's tools + ship-wide tools — not the full catalog. Bones doesn't evaluate BuilderAgent. Scotty doesn't evaluate cognitive diagnostics. Smaller tool set = faster discovery, fewer irrelevant options in the LLM context window, lower token cost per decision. The right tools for the right crew.

## Relationship to Entity Classification (AD-398)

| AD-398 Tier | Identity? | Examples | Tool Taxonomy Role |
|-------------|:---------:|---------|-------------------|
| Core Infrastructure | No | CodebaseIndex, KnowledgeStore | Infrastructure services (Category 2) |
| Utility Agents | No | BuilderAgent, CodeReviewerAgent | Onboard utility tools (Category 1) |
| Crew | **Yes** | Scotty, LaForge, Worf | **Tool consumers** — they use tools |

The tool taxonomy extends AD-398 by classifying *all* non-sovereign capabilities, not just ProbOS agents. MCP servers, cloud APIs, computer use, and federation services are all tools — they just weren't part of AD-398's scope because they lived outside the agent classification.

## Tool Registry (AD-423)

As the tool ecosystem grows, ProbOS needs a **Tool Registry** — a runtime catalog of all available tools across all categories. This is the natural evolution of ModelRegistry (which already does this for LLM providers) generalized to all tool types.

### Registry Responsibilities

| Function | Description |
|----------|------------|
| **Catalog** | What tools are registered, their category, location, capabilities |
| **Discovery** | "What tools can do X?" — crew queries registry by capability, not by name |
| **Health** | Is this tool responding? Latency? Error rate? Last successful call? |
| **Cost** | Token/API consumption per tool, per agent, per time period |
| **Access Control** | Who can use what, at what permission level (see below) |
| **Audit** | Full log of tool invocations — who called what, when, with what result |
| **Lifecycle** | Register, deregister, enable/disable tools at runtime |

### Access Control Model (CRUD + Observe)

Tools support fine-grained permission levels. Each crew member gets a permission set per tool, gated by Earned Agency tier and Captain overrides.

#### Permission Levels

| Level | Code | Description | Example |
|-------|------|------------|---------|
| **None** | `---` | Tool not accessible | Ensign can't use computer use |
| **Observe** | `O--` | Read-only, passive monitoring | Watch screen activity, read browser DOM |
| **Read** | `OR-` | Query/retrieve data, no mutations | Search codebase, read database, view files |
| **Write** | `ORW` | Create and modify | Write files, send messages, fill forms |
| **Full** | `ORWD` | Delete, destructive operations | Drop tables, delete files, force push |

#### Default Permission Matrix

| Tool Category | Ensign | Lieutenant | Commander | Senior |
|--------------|--------|-----------|-----------|--------|
| Onboard infrastructure | `OR-` | `OR-` | `ORW` | `ORWD` |
| Onboard utility agents | `OR-` | `ORW` | `ORW` | `ORWD` |
| MCP Servers (read-only) | `OR-` | `OR-` | `OR-` | `OR-` |
| MCP Servers (read-write) | `---` | `OR-` | `ORW` | `ORWD` |
| Remote APIs / LLM | `OR-` | `ORW` | `ORW` | `ORWD` |
| Computer Use | `---` | `O--` | `ORW` | `ORWD` |
| Browser Automation | `---` | `OR-` | `ORW` | `ORWD` |
| Communication Channels | `---` | `OR-` | `ORW` | `ORW` |
| Federation Services | `---` | `OR-` | `ORW` | `ORW` |

#### Captain Overrides

The Captain can override any default:
- **Grant up:** Give Wesley (Ensign) `ORW` on BuilderAgent for a specific task
- **Restrict down:** Lock Worf (Commander) to `OR-` on communication channels during an investigation
- **Blanket disable:** Turn off all computer use ship-wide
- **time-scoped:** Grant elevated access for a window ("Wesley can use browser automation for the next 2 hours")

Overrides are managed via HXI (Tool Registry panel) or `/tool-access` command.

### Tool Registration Schema

```
ToolRegistration:
  tool_id: str                    # Unique identifier (e.g., "builder", "mcp-filesystem", "copilot-sdk")
  display_name: str               # Human-readable name
  category: ToolCategory          # One of the 8 taxonomy categories
  location: onboard | local | cloud | federation
  protocol: native | mcp | http | websocket | computer-use | browser
  capabilities: list[str]         # Semantic tags: ["code-generation", "file-write", "llm-inference"]
  side_effects: read-only | write | destructive
  cost_model: free | metered | reciprocal
  scope: ship-wide | department   # Visibility level
  department: str | None          # If department-scoped, which department
  restricted_to: list[str] | None # If set, only these agents can invoke (within scope)
  default_permissions: dict[Rank, PermissionLevel]
  health_check: HealthCheckConfig | None
  sandbox: SandboxConfig | None
  enabled: bool                   # Captain kill switch
  concurrency: concurrent | exclusive  # LOTO — exclusive tools need lock acquisition
  lock_timeout_seconds: float | None   # Auto-release for exclusive tools (prevents zombie locks)
  registered_at: float            # When this tool was added
  last_healthy: float | None      # Last successful health check
```

### Discovery Flow

When a crew member needs a capability:

```
1. Crew member: "I need to read database records"
2. Registry.discover(capability="database-read") →
   [
     {tool: "mcp-postgres", permission: "OR-", status: "healthy"},
     {tool: "mcp-sqlite", permission: "ORW", status: "healthy"},
     {tool: "codebase-index", permission: "OR-", status: "healthy"},
   ]
3. Agent selects appropriate tool based on context
4. Registry checks permission → allow/deny
5. Tool invoked, result returned
6. Audit log records: agent, tool, operation, result, tokens, duration
```

### Integration Points

| System | Integration |
|--------|------------|
| **ModelRegistry** | Absorb into Tool Registry — LLM providers are just another tool category |
| **Earned Agency** | Permission levels derived from trust tier + Captain overrides |
| **HebbianRouter** | Tool selection can be Hebbian-weighted — agents learn which tools work best |
| **Event Log** | Tool invocations emit events for monitoring and dream consolidation |
| **HXI** | Tool Registry panel — view all tools, health, permissions, cost; Captain management |
| **Standing Orders** | Department-level tool access rules (e.g., "Engineering has ORW on all build tools") |
| **Extension-First (Phase 30)** | Extensions register their tools through this registry |
| **MCP Protocol** | MCP servers auto-register on connection, deregister on disconnect |

### What This Replaces / Evolves

- **ModelRegistry** (current) → becomes the LLM subset of Tool Registry
- **Implicit tool access** (current) → explicit, audited, permission-gated access
- **Ad-hoc MCP wiring** (future) → standardized registration and discovery
- **Extension config** (Phase 30) → extensions declare tools, registry manages access

*Connects to: AD-357 (Earned Agency), AD-398 (three-tier classification), AD-421 (Scotty as SWE crew), AD-422 (tool taxonomy), Phase 30 (Extension-First), ModelRegistry.*

