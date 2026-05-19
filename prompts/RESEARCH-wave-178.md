# Prior-Art Research — Wave 178 (see → discuss → act)

**Drafted:** 2026-05-19 (architect-only, pre-build).
**Scope:** Architectural inputs for AD-733-2 (passive screen sensing), AD-744
(interactive share-to-agent), AD-745 (conversation → action handoff).
**Posture:** **Pattern absorption.** Zero deps land in this wave. Every code
patterns reference here translates into ProbOS-native code written from
scratch in subsequent ADs.

---

## 1. License-Aware Absorption Table

| Project | License | What it does | Absorb (pattern) | Do NOT absorb | Why |
|---|---|---|---|---|---|
| **Anthropic computer-use API + `anthropic-quickstarts/computer-use-demo`** | MIT (quickstart repo) / Anthropic Terms (API) | Reference loop: screenshot → tool-call (`computer({action,coordinate,text})`) → execute → screenshot → repeat. Linux X11 reference impl. | Tool-call grammar shape; screenshot cadence; per-step ACK ladder; "thinking" + "tool_use" loop; Docker sandbox pattern for OS scope. | Tool-call vendor lock-in (we already use OpenAI-shape multimodal per BF-268); X11-specific binaries; the SDK package itself. | Canonical reference. The `{action, coordinate?, text?}` shape is the de-facto baseline. Our v1 uses an equivalent JSON-tool envelope under our `_HANDLERS` registry. |
| **browser-use (`browser-use/browser-use`)** | MIT | Playwright wrapper for LLM agents. Indexed-element accessibility tree (`get_clickable_elements_dom_tree`), action vocabulary (`click_element`, `input_text`, `scroll_down`, `extract_content`), self-correcting loop. | Indexed-element DOM-tree approach (already mirrored in AD-706 `state()`); action vocabulary parity check; `extract_content` LLM read-out pattern. | The `browser_use.Agent` orchestrator (we have CognitiveAgent + Tool layer); their `BrowserSession` (we have `tools/browser/session.py`); LangChain-shaped prompt scaffolding. | The architectural overlap with AD-706 is ~80%; the gap is the agent-orchestration loop. Their indexed-element pattern is the canonical "DOM-tree + index for LLM" model — we already implement it. |
| **OpenAI Operator / CUA (Computer-Using Agent)** | Closed product; published technical blog + system card | Hosted browser-sandbox agent. CUA model emits screen coordinates against a screenshot (no DOM). Step-execution verification via second model call. Confirmation modals for "consequential" actions (purchases, deletes, account changes). | Two-model verification handshake (already in AD-706c-2 Guard #9 — `action_verify`); the "consequential action" classification (maps to our tier-3); the screenshot-then-act primary mode. | No code; closed-source. | Anthropic's open peer is the primary reference; OpenAI's blog confirms the shape converges. The "consequential action gate" language gives us governance vocabulary for the AD-745 destructive-pattern allow-list. |
| **OmniParser (Microsoft Research)** | MIT | Vision-only screen parser: detects UI elements + emits bounding boxes + per-region semantic descriptions ("Submit button," "Login form"). Pure VLM — no accessibility tree. | The "set-of-marks" overlay pattern (number every detectable element 1..N, LLM clicks by index instead of coordinate); the captioning-pipeline architecture (detect → caption → ground). | The model weights themselves (operator-pullable; not bundled); the inference pipeline (we honest-degrade to compute_use VLM-only in v1). | The strongest v2 forward marker. v1 ships VLM-direct-coordinate (compute_use_click pattern); v2 (forward marker AD-745-3) layers OmniParser SOM overlay to shrink the error rate. MIT — pattern + future-absorption candidate. |
| **SeeAct (OSU NLP Group)** | Apache 2.0 | "Find this element" two-stage pipeline: VLM proposes element by description → execution layer grounds via DOM/AX/coords. | Two-stage grounding (describe-then-locate) — separates VLM reasoning from grounding mechanism. | The web-only DOM-grounding code (overlaps with browser-use); the dataset. | The conceptual model — "the LLM describes intent; the grounding layer decides whether DOM/AX/coordinates win" — is the right v2 architecture for AD-745. v1 ships VLM-direct; v2 adds an intermediate grounding step. |
| **Playwright MCP (`microsoft/playwright-mcp`)** | Apache 2.0 | Microsoft's official MCP server exposing Playwright over MCP tools. Action vocabulary: `browser_click`, `browser_type`, `browser_navigate`, etc. Accessibility-tree-grounded by default. | Tool naming convention; ax-tree-first grounding; the auto-snapshot pattern (every action returns a fresh snapshot for the next decision). | MCP-as-transport (we use our own IntentBus + Tool dispatch); the snapshot serialization format. | Aligns the AD-745 verb names with the broader MCP ecosystem (if/when we expose ProbOS tools via MCP per AD-449, naming parity is free). Auto-snapshot reinforces our "screenshot after action" idea. |
| **Khoj (`khoj-ai/khoj`)** | AGPL-3.0 | Self-hosted assistant w/ desktop screen-share + voice + chat. The "AI sees your screen" UX is mature. | UX patterns ONLY: how the screen-share indicator surfaces, how the operator revokes, how the agent annotates what it saw. | Zero code. AGPL would propagate. | Pure UX reference for HXI surfaces. |
| **Open Interpreter (`OpenInterpreter/open-interpreter`)** | AGPL-3.0 | Local code-execution agent with computer-use mode. Pioneered "LLM emits Python that runs locally" pattern. | Pattern-only: the explicit-confirmation prompt before destructive code; the "stop" affordance during long-running actions. | Zero code. AGPL would propagate. | Reference for the operator-confirmation ladder. Their UX has the cleanest "agent is about to do X, confirm/skip/stop" pattern in the OSS ecosystem. |
| **WebArena / VisualWebArena** | Apache 2.0 (code), MIT (benchmarks) | Sandboxed web environments + reference agents for benchmarking. | The benchmark task taxonomy (information-seeking, transactional, multi-tab) — informs how we classify AD-745 actions by consequence. | The sandbox infrastructure itself (we don't need synthetic environments for v1). | Useful for designing the AD-745 destructive-pattern allow-list — they enumerate the action categories that need confirmation. |
| **CogAgent / ShowUI / LLaVA-Next** | Apache 2.0 (CogAgent, ShowUI) / multiple (LLaVA-Next per checkpoint) | Open VLMs specialized for GUI grounding. CogAgent specifically outputs `(x, y)` for grounding queries. | Model selection guidance for the `compute_use` tier — these are operator-pullable alternatives to Anthropic Claude vision. | No code lift. Models are operator-pullable. | Validates the v1 "VLM-direct-coordinate" approach — purpose-built models exist. Forward marker AD-745-4 ships the operator config for choosing one. |
| **MultiOn / Adept ACT-1 / Rabbit LAM** | Closed products | Hosted "AI does web tasks for you" agents. | Architectural posture from public papers/talks: action history, undo support, task-completion verification. | Zero code; no public weights. | Confirms the "task → many actions → verify" loop is the industry-converged shape. |
| **LiveKit Agents / Pipecat** | Apache 2.0 (both) | Real-time A/V SDKs for agents (voice, video, screen). | Lifecycle pattern: track-subscribe, track-unsubscribe, "agent is watching" indicator; per-track ACL. | Zero code in v1 (we use browser-native `getDisplayMedia` + multipart POST — no WebRTC). | Forward marker for AD-733-2-1 (real-time WebRTC screen track instead of multipart frames) — preserves the audit trail for when scale forces it. |
| **MakeHuman / VRoid Studio / "AI sees your screen" desktop apps** | AGPL / proprietary / mixed | Reference UX implementations. | UX patterns only. | Zero code. | Confirms the design space; nothing to absorb beyond what Khoj covers. |

**Default disposition for every project above:** pattern absorption. We
write our own code. The OSS repo stays clean MIT/Apache-only. **Zero
deps land in Wave 178.**

---

## 2. Action Grammar — Industry Comparison

| System | Shape | Example | Grounding |
|---|---|---|---|
| **Anthropic computer** | Tool-use JSON | `{"action":"left_click","coordinate":[420,310]}` | Pixel coords (from screenshot) |
| **Anthropic str_replace_editor** | Tool-use JSON | `{"action":"create","path":"...","file_text":"..."}` | Path-addressed |
| **browser-use** | Pydantic action model | `ClickElementAction(index=7)` | DOM element index |
| **Playwright MCP** | MCP tool call | `browser_click(element="Submit button",ref="...")` | AX-tree ref + human description |
| **SeeAct** | Two-stage: describe → ground | "Click the green Save button" → AX/coord/DOM resolver | Hybrid |
| **OmniParser SOM** | Numbered-overlay | `click(7)` where 7 is overlay marker | VLM-detected element index |
| **OpenAI Operator (inferred)** | Coordinates | `{x, y}` against screenshot | Pixel coords |

**ProbOS Wave 178 choice:** **Hybrid, built on AD-706 `_HANDLERS` vocabulary
already shipped.**

- DOM/AX-tree-grounded path: `click(selector=...)` / `type(selector=..., text=...)` — already in AD-706e.
- VLM-direct-coordinate path: `compute_use_click(intent=...)` — already in AD-706c-2 (Guard #9 verification handshake).
- New in AD-745: tool-dispatch wrapper that lets a CognitiveAgent emit a JSON action envelope inside its DM reply; ProbOS parses it, classifies via existing `classify_action`, gates via existing tier-1/2/3 ladder.

**Forward marker AD-745-3:** OmniParser-style SOM overlay grounding (v2).
**Forward marker AD-745-4:** Operator-configurable grounding strategy
(coordinate vs SOM vs AX-tree vs hybrid) — mirrors the AD-742d
pluggable-supervisor-strategy pattern.

---

## 3. Screen-Grounding Strategies — v1 Decision

| Strategy | Pros | Cons | Disposition |
|---|---|---|---|
| Pixel coordinates (VLM-direct) | Simple. Works on any surface (canvas, video, native apps). No browser/OS coupling. Already shipped via AD-706c-2 `compute_use_click`. | Fragile to resolution / DPI / window resize. Higher VLM error rate without overlays. | **V1.** Reuse AD-706c-2 pattern. |
| Accessibility tree (AX) | Robust on conformant apps. Stable across resizes. | OS-coupled (UIA/AX/AT-SPI per platform). Fails on canvas/video/games. Browser scope only buys us the browser's AX tree — already covered by Playwright `aria-snapshot`. | Forward marker AD-745-1 (OS scope) + AD-745-3 (improved grounding). |
| DOM (browser-only) | Robust on standards-compliant sites. Already in AD-706 `state()`. | Browser scope only. Fails on canvas/embeds/PDFs. | **V1** for browser-rendered surfaces (already shipped). |
| OmniParser SOM overlay | Best VLM accuracy. Visual + semantic. | Adds model dependency. Slower. | Forward marker AD-745-3. |
| Hybrid (SeeAct describe-then-ground) | Best of all worlds. | Two LLM calls per action. | Forward marker AD-745-4. |

**v1 decision:** Browser surfaces use DOM-first (AD-706 `state()` + `click(selector=...)`); when `state()` returns no candidates, fall back to `compute_use_click` (AD-706c-2 VLM coordinates). This is the existing AD-706 ladder; AD-745 adds the dispatch from a DM-reply parser.

---

## 4. Lifecycle / Consent UX — Patterns

| Project | Indicator | Revoke | Action distinguishes |
|---|---|---|---|
| **Khoj** | Persistent "Screen shared" badge w/ stop button. | One-click stop. | Read-only by default; "act on screen" is a separate toggle. |
| **Playwright MCP** | None client-side (operator runs it). | Process kill. | Per-tool ACL via MCP. |
| **browser-use** | None (CLI). | Ctrl-C. | None. |
| **Anthropic computer-use demo** | Docker container badge. Activity log. | Stop button. | Every tool_use logged + can be paused. |
| **OpenAI Operator** | Persistent "Operator is active" indicator. Per-step confirmations for "consequential" actions. | One-click pause. | Tier ladder (auto / ack / consequential). |

**ProbOS pattern (Wave 178):**

- **AD-733-2 (passive screen sensing)**: Persistent `SCREEN LIVE` indicator
  alongside `CAMERA LIVE` (extending `CameraLiveIndicator.tsx` per HXI #3 —
  no emoji, stroke-only SVG). Per-source toggle in `PerceptionLivePanel.tsx`
  (extending the AD-742c-6 multiplexer panel pattern). Revoke = one-click
  stop on the indicator.
- **AD-744 (interactive share)**: Modal "Share screen to {agent}" with
  monitor/window picker (browser-native `getDisplayMedia({video:true})`
  surfaces the picker for free). The share is a one-shot (or
  time-bounded) operation, NOT a long-lived stream — distinct from the
  AD-733-2 ambient mode. UX phrase: "Sharing to Counselor for this DM."
- **AD-745 (action handoff)**: Three-state badge per agent: `OBSERVING`
  (vision describe only), `PROPOSING` (agent has emitted an action; awaiting
  Captain ACK), `ACTING` (action in flight; pulse per HXI #4). Action log
  collapsed by default (HXI #5 progressive disclosure). Per-action stop
  affordance always reachable.

---

## 5. Safety / Governance — Patterns to Absorb

| Pattern | Source | ProbOS mapping |
|---|---|---|
| Per-action consent ladder (auto / ACK / consequential) | Anthropic, OpenAI Operator, AD-706e | **Already shipped** via `classify_action` tier 1/2/3. AD-745 reuses verbatim. |
| Destructive-pattern allow-list (financial, auth, admin URLs) | OpenAI Operator system card | **New in AD-745.** URL-pattern + DOM-pattern matchers map to tier-3 + `requires_consensus=True`. Three-axiom Safety Budget evaluation: pattern match raises consensus threshold. |
| Two-model verification handshake | Anthropic, AD-706c-2 Guard #9 | **Already shipped** via `action_verify`. AD-745 reuses. |
| Per-session trust budget (consecutive-autonomous + total caps) | OpenAI Operator (inferred), AD-706c-2 Guard #10 | **Already shipped** via `BrowserSession._compute_use_consecutive_autonomous`. AD-745 extends to non-compute-use actions. |
| Action history + undo audit | Anthropic computer-use demo, OpenAI Operator | **New in AD-745.** Every action writes an Episode with `AnchorFrame(channel="action", trigger_type="agent_action_executed")` per AD-541b. Episode stores frame ref + action JSON + result. |
| Sandbox isolation (Docker / VM / browser profile) | Anthropic demo (Docker), Playwright MCP (Chromium profile) | **V1 inherits AD-706 isolation** — Playwright launches a separate Chromium context with `BrowserSession.user_data_dir`. NOT the Captain's logged-in profile. Forward marker AD-745-5 for explicit profile-clone-with-consent. |
| Operator stop button | Khoj, Anthropic demo, OpenAI Operator | **New in AD-745.** Per-session abort on the action-log surface (HXI). Sets `BrowserSession.aborted=True` and re-raises `CancelledError` per Async Discipline. |
| "Consequential action" confirmation modal | OpenAI Operator | **New in AD-745.** When `classify_action` returns tier 3 OR pattern matches destructive allow-list, the HXI surfaces a confirmation modal in-thread alongside the agent's proposed action. Captain ACK = explicit click, NOT silent timeout. |

---

## 6. Multi-Step Task Patterns

| Project | Context across screenshots | Completion verification |
|---|---|---|
| **Anthropic computer-use demo** | Full conversation history with image attachments (latest screenshot per step). | LLM declares done; can be cross-checked. |
| **browser-use** | DOM-tree snapshot per step + LLM short-term memory. | LLM declares done; "extract_content" final-state read-out. |
| **OpenAI Operator** | Hosted long-context conversation. Hidden "scratchpad" for planning. | LLM declares done + operator can correct. |
| **SeeAct** | Per-step DOM/AX-tree + screenshot. | Per-step verification model call. |
| **WebArena agents** | Variable; benchmark allows full-context replay. | Reference programmatic checker. |

**ProbOS Wave 178 choice:** Single-action-per-LLM-turn in v1. The agent
emits ONE action per DM reply. Captain ACKs (or not); next DM turn includes
a fresh "screenshot after action" attachment. Multi-step orchestration is a
forward marker AD-745-6 (chained actions inside one DM reply with a
declared "plan" + step-by-step ACK). This preserves the Captain's
moment-by-moment control — the v1 cost is verbosity; the safety dividend
is locality.

---

## 7. Recommendation Matrix — Architectural Decisions

| # | Decision | v1 choice | Forward marker |
|---|----------|-----------|----------------|
| 1 | Action grammar | Reuse AD-706 `_HANDLERS` vocabulary. Agent emits `[ACTION: <json>]` bracket-marker in DM reply (mirrors AD-728d / AD-730-3 / AD-743 family). Parser dispatches to existing tool. | AD-745-3 OmniParser SOM grounding. |
| 2 | Screen grounding | DOM-first via AD-706 `state()`; fallback to `compute_use_click` (AD-706c-2). | AD-745-3 (SOM), AD-745-4 (pluggable grounding strategy). |
| 3 | Tool agents | BrowserTool only in v1. NEW `DesktopActionTool` (OS scope) deferred. Verbs are Tool actions, NOT sibling CognitiveAgents — Tools are the right substrate per AD-423a ToolType.COMPUTER_USE. | AD-745-1 (DesktopActionTool OS scope). |
| 4 | Browser vs OS scope | **Browser only.** AD-745 v1 acts inside a Playwright session targeting the Captain's shared URL. If Captain shares a non-browser surface, the agent honest-degrades to describe-only. | AD-745-1 (OS pointer control). |
| 5 | Sandbox / safety | Agent's Playwright session uses a SEPARATE Chromium context (`BrowserSession.user_data_dir`). NOT the Captain's logged-in profile. The shared screen is the PERCEPTION channel; the action surface is the agent's mirror session. | AD-745-5 (consensual profile clone). |
| 6 | Per-agent screen scoping | One screen-source per agent at a time. NEW sibling `useScreenMultiplexerStore` (NOT a merger with `useCameraMultiplexerStore` — same SRP rationale as AD-742c-6). | (none needed — pattern proven in AD-742c-6). |
| 7 | AD-721j (Blender) overlap | **AD-745 ships the generic computer-use action tier; AD-721j becomes a downstream consumer** (Blender = target application of the same dispatch substrate, not a separate Tool class). This avoids parallel scaffolding. | AD-721j re-scoped post-AD-745 ship. |

---

## 8. Anti-Patterns to Avoid (Top 3)

1. **Letting the agent emit raw Playwright code.** Open Interpreter (AGPL) and several smaller projects do this. It collapses the consent ladder — once you `eval` agent-emitted Python, you can no longer classify or gate individual actions. AD-706e learned this with `eval_js` (always tier-3, length-capped at 4096 chars, JSON-result-only). AD-745 must keep the action grammar as discrete tool calls, NOT executable code.
2. **Single-tool-agent god class.** Some projects model "the computer-use agent" as one autonomous loop that owns screenshot + reasoning + action. This violates SOLID (S) and prevents granular consent. Our split: BrowserTool owns the page; the CognitiveAgent emits a `[ACTION: ...]` bracket; the runtime dispatches. Three responsibilities, three modules.
3. **Hidden context across surfaces.** browser-use and similar projects feed full DOM snapshots into the next-step LLM call WITHOUT operator visibility. This is a privacy and audit gap. AD-745 stores every step's frame + action + result as an AD-541b anchored Episode, visible in the standard recall path; the HXI action log surface (forward marker AD-745-7) makes the audit trail first-class.

---

## 9. Top 3 Absorption Sources (Final)

1. **Anthropic computer-use** — tool-call shape, screenshot-loop architecture, destructive-action gate vocabulary. License-clean (MIT quickstart).
2. **browser-use** — indexed-element + action vocabulary parity, self-correcting loop. License-clean (MIT).
3. **OmniParser / SeeAct** — forward-marker v2 grounding strategies. License-clean (MIT / Apache 2.0).

## 10. Cross-AD Dependency Graph

```
                  ┌─────────────────────────────────────┐
                  │ Existing infra (already shipped)    │
                  │ • AD-706 BrowserTool                │
                  │ • AD-706c-2 compute_use_click       │
                  │ • AD-706e action vocab v2           │
                  │ • AD-720/731 AttachmentStore        │
                  │ • AD-733/733a vision_observation    │
                  │ • AD-742c-6 multiplexer panel       │
                  └────────────────┬────────────────────┘
                                   │
            ┌──────────────────────┼──────────────────────┐
            │                      │                      │
            ▼                      ▼                      ▼
   ┌────────────────┐    ┌────────────────┐    ┌────────────────┐
   │ AD-733-2       │    │ AD-744         │    │ AD-745         │
   │ passive screen │    │ interactive    │    │ action handoff │
   │ sensing        │    │ share-to-agent │    │ (browser v1)   │
   └────────┬───────┘    └────────┬───────┘    └────────┬───────┘
            │                      │                     │
            │   AD-744 depends     │  AD-745 depends     │
            │   on AD-733-2        │  on AD-744          │
            │   attachment plumbing│  DM-frame contract  │
            │   (source="screen")  │                     │
            └──────────────────────┴─────────────────────┘
```

Build order: **AD-733-2 → AD-744 → AD-745**.

- AD-733-2 introduces `source="screen"` on `vision_observation`. Reused by AD-744.
- AD-744 introduces the DM-attached frame contract (frame ref inline with Captain's DM turn). Reused by AD-745 as the "what the agent sees" input.
- AD-745 introduces the action-dispatch path. Consumes AD-744's DM-frame and emits actions back into the existing AD-706 BrowserTool surface.

---

## 11. Open Questions for Captain (Surface Before Builder Dispatch)

1. **AD-721j re-scope** — Per §7, AD-745 absorbs the generic computer-use dispatch and AD-721j (Blender) becomes a downstream consumer. Captain ruling required: re-scope AD-721j to "Blender as an application target of DesktopActionTool" (AD-745-1 forward marker) OR ship AD-721j as a separate Tool class with its own action vocabulary? Default recommendation: re-scope. (See AD-745 §"Overlap with AD-721j".)
2. **AD-745 v1 OS-scope honest-degrade** — When the Captain shares a non-browser surface (Photoshop, native IDE), AD-745 v1 honest-degrades to describe-only. Is that acceptable for v1, or does v1 ship a minimal OS-pointer fallback (riskier)? Default recommendation: honest-degrade. OS scope = AD-745-1 forward marker.
3. **Consensus on destructive actions** — Should AD-745 destructive-pattern matches (financial/auth/admin URLs) require multi-agent quorum vote (`requires_consensus=True` on the action verb), OR is Captain-ACK-only sufficient for v1? Default recommendation: Captain ACK only in v1; document quorum as AD-745-2 forward marker once we have action-volume data.
4. **Per-action vs per-DM ACK** — Captain ACKs every individual action, OR Captain ACKs the agent's whole "plan" at the start of a multi-step task? Default recommendation: per-action ACK in v1 (locality of control); multi-step plan = AD-745-6 forward marker.

---

**Verification posture for this research deliverable:** every license posture and architectural claim above is sourced from public docs / repos accessed via `mcp_microsoftdocs_microsoft_docs_search` / `fetch_webpage` / `github_repo` / `github_text_search` during the Wave 178 drafting session OR from the live ProbOS codebase grepped at HEAD `27dccc8` (post-wave-177). Every code claim referencing ProbOS modules (AD-706/706c-2/706e/733/733a/742c-6) is confirmed present at HEAD — see per-prompt Verified-Against-Codebase blocks for grep evidence.
