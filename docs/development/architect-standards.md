# Architect Standards

## Architect: Review Checklist

When reviewing PROGRESS.md or evaluating changes, check for:
- **Layer violations**: Does new code respect the Substrate -> Mesh -> Consensus -> Cognitive -> Experience layering?
- **Agent contract adherence**: CognitiveAgent subclasses must use `instructions`-first design (LLM reasons via instructions, not hardcoded logic in `decide()`).
- **Self-modification safety**: The validation chain must be preserved: static analysis -> sandbox test -> probationary trust -> QA smoke tests -> behavioral monitoring. On warm boot: CodeValidator must validate restored agent code before `importlib` loading.
- **Consensus integrity**: New destructive intents must require consensus.
- **Trust/Hebbian coherence**: The learning loop must remain intact: trust influences consensus -> outcomes update trust + Hebbian -> Hebbian influences routing. Trust must store raw `(alpha, beta)` parameters.
- **Test coverage**: Check the test count in `PROGRESS.md` line 2. New features need tests. Flag untested code paths. New public methods must have boundary tests (happy path + error + edge case).
- **Episodic completeness**: Every execution path should store an episode, or the learning loop breaks.
- **Agent tier correctness**: Is this agent classified as core/utility/domain appropriately? Domain agents should not have direct access to internal system state. Utility agents operate on the system, not for the user.
- **Governance axioms**: Evaluate against the three axioms — Safety Budget (risk-proportional consensus), Reversibility Preference (prefer reversible strategies), Minimal Authority (scoped capabilities, earned trust).
- **Nooplex alignment**: Does this change close a gap, maintain alignment, or introduce a regression against the Nooplex paper (`Vibes/Nooplex_Final.md`)?
- **Type annotations**: All new public methods must have full type annotations. Missing return types or untyped parameters on public APIs are a review blocker.
- **Logging quality**: Log messages must include context (what, why, what next). Bare `logger.warning("error")` or `logger.error("failed")` are review blockers.
- **Async hygiene**: `create_task()` calls must store the reference. `ensure_future()` usage is flagged. Cancellation must be handled in long-running loops.

### Common Review Flags

- **Layer violation**: "X in the experience layer is importing from cognitive internals -- use the runtime API instead."
- **Missing consensus gate**: "This new intent modifies state but doesn't set `requires_consensus=True`."
- **Hardcoded behavior in CognitiveAgent**: "This agent has logic in `decide()` instead of using `instructions`. Move the reasoning to the instructions string."
- **Untested self-mod path**: "The new validation check in CodeValidator has no test for the rejection case."
- **Trust bypass**: "This code path skips trust scoring for designed agents."
- **Prompt drift**: "The decomposer prompt was manually edited instead of going through PromptBuilder."
- **Missing episodic storage**: "This execution path doesn't store an episode, breaking the learning loop."
- **Tier misclassification**: "This domain agent is accessing internal system state directly -- it should go through the runtime API or be reclassified as utility."
- **Warm boot security gap**: "This restore path loads agent code without CodeValidator validation."
- **Scope creep**: "This change adds [feature] which was not in the prompt. Revert and keep to the stated deliverables."
- **Prompt text triggering gap regex**: "This response/example text contains phrases ('can't', 'don't have', 'unable to') that match `_CAPABILITY_GAP_RE`. Review all prompt example text against the gap regex before shipping."
- **IntentBus fan-out side effects**: "This change adds HTTP calls in agent code. Remember: `IntentBus.broadcast()` fans out to ALL subscribers. 3 HttpFetchAgents × N broadcasts = 3N HTTP calls. Use `_mesh_fetch()` for designed agents — rate limiter handles the rest."
- **Inline blob in IntentMessage.params**: "ANY new code path that puts >4 KB into `IntentMessage.params` should be flagged. Use a content-addressable ref to `AttachmentStore` (AD-731 pattern). The bus carries refs; the store carries bytes. The 2026-05-11 OOM crash (#636) and the BF-265 → BF-267 → AD-731 wave-151/152 sequence is the canonical lesson on why inline blobs in RPC messages is the wrong shape."
- **LLM tier tuple duplication**: "New tier added to LLM client: every `(\"fast\", \"standard\", \"deep\")` tuple in the file must be replaced by the single-source-of-truth constant `_LLM_TIERS`. The fallback chain `_TIER_ORDER` is a separate concern — vision does NOT join it (standard/deep cannot see images, so falling back to them is silent failure). AD-732 (wave 153) is the canonical example: 12 tuple sites grep-replaced, only `_TIER_ORDER` retained the 3-tier shape."
- **HXI Canvas regression**: "This UI change touches agents.tsx, animations.tsx, or CognitiveCanvas.tsx. Verify tooltips, bloom position, and raycasting still work after the change."
- **HXI emoji violation**: "This UI code uses emoji (👍, 🔊, ✨, etc.) instead of inline SVG glyphs. Replace with stroke-based SVG icons per HXI Design Principle #3 in `docs/development/architecture-reference.md`."
- **Missing type annotations**: "This public method has no return type annotation. All public APIs must be fully typed."
- **Bare log message**: "This log message has no context. Include what failed and what the system did about it."
- **Fire-and-forget task**: "This `create_task()` doesn't store the task reference. Exceptions will be silently lost."
- **Test isolation violation**: "This test relies on state from a previous test. Each test must create its own fixtures."
- **Missing boundary test**: "This public method has a happy-path test but no error/edge case test."
- **Circular import risk**: "This import creates a cycle between [X] and [Y]. Use `TYPE_CHECKING` guard for type-only imports."
- **Raw config access**: "This reads configuration from a raw dict/env var instead of using the Pydantic models in config.py."
- **Half-chain evidence**: "A test proves the producer fires and another proves the consumer works, but nothing crosses the seam. That is the signature of this repo's most common defect — every link correct, the chain dead. Require one test spanning file → approve → fulfil → resume."
- **Test pinning the defect as contract**: "This assertion encodes the buggy behaviour as a requirement — highest risk in `?raw` source scans, which cannot tell 'required' from 'what shipped'. Update the assertion and record why inline; never delete it."
- **Unverified absence**: "This asserts something does not exist / is not wired without showing the enumeration that proves it. Run the search and paste it."

## Architect: Claude Code Prompt Drafting

When asked to draft implementation prompts for Claude Code sessions:
- Each prompt should target a single AD (Architecture Decision) or a small group of related ADs.
- Reference specific files, line numbers, and existing patterns.
- Include acceptance criteria (test expectations with counts, integration points, milestone end-to-end test).
- Specify what NOT to change (avoid scope creep).
- **Include explicit "Do not build" constraints** for adjacent features that are tempting to add. Name them specifically. Example: "Do not build federation routing in this phase. Do not refactor the intent bus."
- Produce two files: (1) the spec in `prompts/` that Claude Code reads by path reference, and (2) a separate execution instructions document with the highest-risk constraints stated redundantly.
- Follow the pattern: "Phase X, Step Y: [title]. Implement [specific thing] in [specific file]. It should [behavior]. Wire it from [caller]. Add tests in [test file]. Do not change [boundaries]."
- **Every build prompt must include this line in its acceptance criteria:** "Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`."
- **Verify all references against the live codebase before marking a prompt ready.** Never draft from memory — always grep/read the actual code. Check: (1) import paths exist, (2) constructor/function signatures match (parameter names, types), (3) interface patterns match reality (e.g. `_emit_event_fn` callable, not `event_bus.emit()`), (4) startup wiring location is correct (check which `startup/*.py` module has the analogous pattern), (5) enum vs string constants, casing. AD-566a lesson: 4 would-break-build errors from assumed patterns.
- **Prior art and blind spots (design ADs):** before drafting, ask whether there is anything not yet considered, or prior work that should be leveraged: `docs/research/`, the Nooplex paper, related decisions, and a bounded search of open-source implementations and research papers. The Architect decides what to absorb, adapt or reject and records it in the prompt's **Prior Art and Blind Spots** section; this does not pause for the Captain. Describe other projects only as technical design references, never as competitive analysis (OSS boundary).

## Architect: Strategy

When asked about project direction, evaluate:
- The roadmap items in PROGRESS.md (look for "Roadmap" or "What's Next" sections).
- Architectural gaps relative to the Nooplex paper (`Vibes/Nooplex_Final.md`).
- The three governance axioms (Safety Budget, Reversibility Preference, Minimal Authority) -- does the proposed work respect or advance these?
- Competitive positioning vs projects like OpenClaw, AutoGPT, CrewAI.
- Open-source readiness (what needs cleanup before public release).
