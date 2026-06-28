# Epic AD-1065→AD-1072 — Conversational tool-calling + Skills for crew agents

**Status:** Architect-drafted, ready for Builder sequencing.
**Goal (north star):** The Captain asks Ezri in a 1:1 chat to "prepare a Word document," and she just does it — no hallucinated verbs, no reply-tag guessing — producing a real, downloadable `.docx`.
**Decision (Captain-approved):** always-loop (one mechanism), tool schemas are the self-describing manual, writes gated-but-reachable, behavior-preserving migration (default-OFF first), voice streaming as a fast-follow.
**Current highest landed top-level AD: AD-1064.** These are AD-1065 through AD-1072.

> Every build prompt below must include in its acceptance criteria: "Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`." Verify every file/symbol reference against the live codebase before starting (AD-566a lesson).

---

## The capability model (3 layers)

1. **Native tools (primitives).** A small, stable set offered to the agentic loop: file I/O (`read_file`/`write_file`/`list_directory`/`search_files`/`search_content`), web (`web_search`/`read_page`/`http_fetch`), shell (`run_command`), **code execution (`run_python`) — the keystone**, and `create_artifact` (downloadable output). Almost all EXIST as mesh intents; the work is exposing them as loop tools.
2. **Skills (the breadth).** `SKILL.md` packages (ProbOS already has the catalog — AD-596). Two kinds: *cognitive* (prompt-injected instructions — exist) and *executable* (instructions + bundled scripts run via code execution — NEW). Document creation = the **docx skill**. This is how Claude/Cowork do documents — code execution + a docx skill, NOT a hardcoded docx tool.
3. **MCP tools (external).** Already wired (AD-1019c).

**Why this shape:** the harnesses (Codex, gbrain/OpenClaw, Claude, Cowork) do NOT have a "docx tool." They have one code-execution tool + a docx skill. So "what other native tools do we need" has a small answer — the breadth comes from skills, which ProbOS already has the substrate for.

## Verified infrastructure (already in ProbOS)

| Piece | Location | Note |
|---|---|---|
| `AgenticLoop` | [swe_harness/agentic_loop.py](../src/probos/cognitive/swe_harness/agentic_loop.py) `:47` | Multi-turn tool loop; no-tool turn = single pass. |
| `WorkItemAgenticExecutor` | [agentic_dispatch.py](../src/probos/cognitive/agentic_dispatch.py) `:443` | Assembles grants+mesh+MCP tools, runs loop, persists trace. |
| `DispatchToolExecutor` | agentic_dispatch.py `:44` | Governance-checked execution; captures denied tools. |
| `register_mesh_intent_tools` / `_MESH_TOOL_SPECS` | agentic_dispatch.py `:387` | Mesh-intent→Tool adapters (today: web_search/read_page/http_fetch only). |
| `tool_registration_to_llm_definition` | swe_harness/tool_call.py `:96` | Tool → OpenAI function schema. |
| LLM tool-calling | [llm_client.py](../src/probos/cognitive/llm_client.py) `:1043` | Forwards `tools`/`tool_choice`, parses `tool_calls`. Confirmed working through the Copilot proxy. |
| DM reply path | `routers/agents.py::agent_chat` → `direct_message` → `cognitive_agent._decide_via_llm` → `DmReplyPipeline` | The 1:1 turn the loop must hook into. |
| `CognitiveSkillCatalog` | [skill_catalog.py](../src/probos/cognitive/skill_catalog.py) | AD-596a — SKILL.md discovery, progressive disclosure, SQLite catalog. |
| `CodeRunnerAgent` (`run_python`) | `agents/code_runner.py`, `config.py::ExecutionConfig` | AD-994 — default-OFF, sandboxed; the code-exec keystone. |
| `ArtifactStore` | `src/probos/artifacts.py` | AD-797 — versioned, downloadable cards. |

## Licensing verdict (HARD — OSS repo)

- **Anthropic example skills** (algorithmic-art, frontend-design, mcp-builder, skill-creator, …) = **Apache 2.0** → may be adapted with attribution.
- **Anthropic document skills** (docx/pdf/pptx/xlsx) = **Proprietary / "source-available, not open source"** (`license: Proprietary` in their frontmatter). **DO NOT vendor into ProbOS.** Pattern-absorb only: read as reference, write ProbOS-own `SKILL.md` + scripts, cite as research.
- **Document libraries** (write our own skill on these): `python-docx` (MIT), `docx` / docx-js (MIT), `openpyxl` (MIT), `reportlab` (BSD). **Avoid `pandoc` (GPL)** and bundling LibreOffice in the core path.

---

## AD-1065 — Conversational agentic turn (always-loop in chat) **[spine]**

**Goal.** Route the 1:1 DM turn through `AgenticLoop` so an agent can call tools mid-conversation. No-tool turn = single pass = byte-identical to today.

**Approach.**
- New `ConversationalAgenticExecutor` (or a chat-mode of `WorkItemAgenticExecutor`): agent `instructions` as the loop `system_prompt` (persona preserved), a LOW iteration cap (`~5`, vs. the task path's 25), a FAST tier (sonnet, not deep), the agent's granted + mesh-read tools as the tool set.
- Invoke from the DM path behind a new default-OFF flag `config.dm_agentic.enabled = False` (`CognitiveConfig` or a new `DmAgenticConfig`). When OFF → the existing single-pass `_decide_via_llm` path is unchanged. When ON → the turn runs the loop; the loop's `final_text` becomes the reply, then continues into the existing `DmReplyPipeline` post-processing (so artifact/episodic/TTS steps still fire).
- Governance: reuse `DispatchToolExecutor` (grants/restrictions). Tool calls are gated exactly as the task path.

**Behavior-preserving guarantee.** With the flag OFF, every existing test + the AD-1028 byte-for-byte golden must pass unchanged. With the flag ON and a no-tool turn, the reply must equal the single-pass reply (assert in a test).

**Acceptance.** Flag default-OFF; `test_ad1065_*`: (1) flag-off path unchanged, (2) flag-on no-tool turn = single pass, (3) flag-on tool turn executes a stub tool + feeds the result back + final text is the reply, (4) iteration cap honored, (5) persona/system_prompt = agent instructions. AD-1028 golden green. Verify Engineering Principles compliance.

**Do NOT change.** The task path (`WorkItemAgenticExecutor` callers), the group fan-out, the `_decide_via_llm` single-pass body (only ADD the branch), the reply-tag extractors (still run during migration).

## AD-1066 — Expose core mesh capabilities as loop tools **[primitives]**

**Goal.** The loop's tool set covers what the harnesses offer.

**Approach.** Extend `_MESH_TOOL_SPECS` / the tool registration so the loop can offer: `read_file`, `write_file`, `list_directory`, `search_files`, `search_content`, `run_command`, and **`run_python`** — each with a JSON schema + a clear, example-rich description (Anthropic ACI guidance: absolute paths, examples, poka-yoke). Reads stay reachable; writes (`write_file`, `run_command`, `run_python`) gate through the existing grant/restriction + consensus/risk tiers. **`run_python` requires `execution.enabled=True`** (AD-994) — it is the keystone for skills; the loop must offer it only when enabled (honest-degrade per AD-592).

**Acceptance.** `test_ad1066_*`: each new tool registers with a valid schema; the loop offers exactly the granted+enabled subset; a restricted/disabled tool is absent; `run_python` present only when `execution.enabled`. Verify Engineering Principles compliance.

**Do NOT change.** The read-only `[MESH]` conversational allowlist (`_MESH_READ_INTENT_POOLS`) — that is a separate, deliberate reply-tag surface (kept until AD-1070).

## AD-1067 — `create_artifact` output tool **[output primitive]**

**Goal.** A universal "surface a deliverable to the Captain" tool: write produced bytes/text to `ArtifactStore` → downloadable card (reuse AD-797).

**Approach.** A real `Tool` (`name`, `content` or a path produced by `run_python`, `mime`) that does the AD-797 two-call write (`attachment_store.write(origin="agent_artifact")` → `artifact_store.add_version(thread_id, …)`). Low risk tier (sandboxed, versioned) → reachable for crew without heavy consensus. This is what a skill calls to hand back the finished `.docx`.

**Acceptance.** `test_ad1067_*`: writes an artifact, returns a ref, surfaces a card; honest-degrade when stores absent. Verify Engineering Principles compliance.

## AD-1068 — Executable-skill invocation **[skills bridge]**

**Goal.** An agent in the loop can LOAD a skill (its `SKILL.md` body) and RUN its bundled scripts via `run_python`/`run_command`, with the scripts + deps available in the execution sandbox and the output surfaced via `create_artifact`.

**Approach.** Bridge `CognitiveSkillCatalog` (AD-596) → the loop: a `use_skill(name)` tool (or progressive-disclosure injection) that returns the SKILL.md body into context; ensure the skill's `skill_dir` scripts are reachable from the `run_python` sandbox (AD-994 scratch dir) + declared deps are installable/available. Executable skills get `origin="internal"`, `activation="discovery"`.

**Acceptance.** `test_ad1068_*`: a fixture executable skill loads, its script runs via run_python, output becomes an artifact. Verify Engineering Principles compliance.

## AD-1069 — ProbOS document skills (docx first) **[the deliverable]**

**Goal.** Ezri reliably produces a polished `.docx`.

**Approach.** Author ProbOS's OWN `config/skills/docx/SKILL.md` + scripts using a permissive lib (`python-docx` MIT or docx-js MIT), **pattern-absorbed** from Anthropic's proprietary docx skill (cited as research, NOT vendored — see Licensing verdict). Encode the gotchas (page size, headings/TOC, tables with dual widths, lists via numbering, images). Then pdf (reportlab BSD), pptx (python-pptx MIT), xlsx (openpyxl MIT) as follow-ons. End-to-end: chat → loop → `use_skill("docx")` → `run_python` → `.docx` → `create_artifact` → downloadable card.

**Acceptance.** `test_ad1069_*` + a live demo: "Ezri, write up these recommendations as a Word doc" → a valid, openable `.docx` artifact. License disposition documented. Verify Engineering Principles compliance.

## AD-1070 — Retire reply-tag hooks / unify self-description

Migrate `<artifact>` / `[NOTEBOOK]` / `[CREATE_TASK]` to tools+skills; the schema / SKILL.md description becomes the manual; remove the `_conversational_*` teaching hooks once the tools are validated. Behavior-preserving (keep extractors during migration, then deprecate).

## AD-1071 — Streaming reply → TTS (voice edge)

Stream the loop's final assistant text to the avatar/TTS pipeline at sentence boundaries (Codex `agentMessage/delta`, gbrain `ClaudeStreamAdapter` pattern) so Ezri speaks in real time while fire-and-forget tool side-effects resolve. Fast-follow, not a blocker.

## AD-1072 (forward) — Tool search + sub-agent delegation tool

When the tool/skill set grows, use `capability_retriever` for lazy tool discovery (Codex `ToolSearchInfo` pattern). Expose a `delegate`/`create_task` tool so Ezri can hand a large job to a worker (orchestrator-workers).

---

## Goal-critical chain

**AD-1065 → AD-1066 (incl. `run_python` + `create_artifact` via AD-1067) → AD-1068 → AD-1069.** After AD-1066, Ezri can already make a `.docx` by writing python-docx inline + running it; AD-1068/1069 make it reliable and polished. AD-1070–1072 are unification + polish.

## Prerequisite the Captain must decide

**Code execution (`run_python`, AD-994) is default-OFF and is the keystone for the skills/document model.** Enabling it (sandboxed) is required. Every harness has sandboxed code execution; this is the same posture. The epic assumes `execution.enabled=True` for the document path.
