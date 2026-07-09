# Cascade-Confabulation Prevention — AD-1119 / AD-1120 / AD-1121 (OSS)

**Status:** DRAFT ADs (planned, OSS). Awaiting Architect build-prompt drafting → Builder implementation.
**Highest landed AD at drafting:** AD-1118. These three are the next sequential top-level ADs.
**Tracking issues:** AD-1119 → #1022 · AD-1120 → #1023 · AD-1121 → #1024.
**Epic theme:** Prevent (not just post-hoc classify) the `CASCADE_CONFAB` anti-pattern already coded in `src/probos/cognitive/emergence_taxonomy.py` (refs BF-237/AD-453).

---

## Forensic basis (why we are building this)

Live-runtime trace (2026-07-08) of the crew "Oracle Health Check" group chat:

- The crew ran a multi-agent investigation into node **`e77acec7`** and its "Oracle membership" health. `e77acec7` is **fabricated** — not a git object, not in any source file, DB, or artifact.
- Recovered seed from the live `chat_threads` store (`GET /api/threads/{id}/messages` on `127.0.0.1:18900`): the real origin is a **2026-06-10** thread investigating a "3-node/0.995 **cooperation cluster**" — built on a benign `EmergentDetector` `cooperation_cluster` pattern event — with a **real** anchor: *"the **bf237** node identity data is the key unlock."* (**BF-237** = the real `pipeline_post_budget_exceeded` ward-room pipeline fix.)
- That thread **"hit its limit"** (context truncation) → the real anchor was stripped → the decontextualized frame ("node membership", "provisioning", "two-population", "gate") survived and was **re-instantiated a month later** with a hallucinated ID (`bf237` → `e77acec7`) and a grafted subject (`oracle_service.py` recall + AD-695 health tier → fictional "Oracle membership retrieval").
- When an agent "pulled Oracle telemetry," it received real-but-unrelated `DECISIONS.md` memory-tier hits and **read them as confirmation** with no relevance check.

**Root-cause mechanisms:** (1) benign emergence telemetry over-interpreted as a threat; (2) **no referent-grounding gate** — no agent verifies an identifier/entity exists before reasoning about it; (3) hallucination-snowball + context-truncation; (4) shared poisoned context makes peer "verification" confirmatory, not independent (AD-506b peer-repetition can't fire — each message is novel); (5) tool results accepted as confirmation without a relevance check.

**Research basis (absorb):** MAST — *Why Do Multi-Agent LLM Systems Fail?* (arXiv 2503.13657, "task verification" failure class); *How LM Hallucinations Snowball* (arXiv 2305.13534); Chain-of-Verification (arXiv 2309.11495, independent verification); SelfCheckGPT (arXiv 2303.08896, sample-divergence detection); NeMo Guardrails (exec/output rails); Guardrails AI (custom validators).

**Recommendation: guards AND behavioral, layered (defense in depth).** Guards catch it deterministically at the boundary (can't be prompted away); behavioral changes stop the crew generating it and make "unresolvable" a rewarded outcome.

**Build order:** AD-1119 (foundation) → AD-1120 (behavioral, depends on 1119's resolver) → AD-1121 (detection, depends on 1119's resolver + transcript persistence).

---

## AD-1119 — Referent-Grounding Gate (guard G1) — BUILD FIRST

**Context.** The single highest-leverage fix. Before the crew treats an identifier or named entity as real, it must be resolved against ground truth. `e77acec7` would have been caught at first mention.

**Decision.** A new, default-OFF, additive `ReferentGroundingGate` (cognitive layer) that:
1. **Extracts candidate referents** from a proposed message / room-seed text: (a) bare hex identifiers (7–40 hex chars, the git-SHA / node-id shape), (b) explicit `"<node|record|entity|node id> <token>"` patterns, (c) capitalized service names asserted as live systems.
2. **Resolves** each via pluggable `typing.Protocol` resolvers (DIP — constructor-injected, no hard imports of concretions): git-object existence (via the existing codebase/git seam), `AgentRegistry` (agent/pool/callsign), ward-room `memberships`, and an extensible list. First resolver that confirms → RESOLVED; none → UNRESOLVED.
3. Returns a verdict `{referent → RESOLVED | UNRESOLVED}` plus, for UNRESOLVED central referents, an **honest-absence cue** string (reuse the AD-979a "Heidi" honest-absence pattern) the caller can inject: *"No referent resolves for `<X>` — treat as structurally unresolvable, do not build an investigation on it."*

**Scope — DO:** new module (e.g. `src/probos/cognitive/referent_gate.py`), `ReferentResolver` Protocol + 2–3 concrete resolvers, a Pydantic `config.grounding.referent_gate_enabled: bool = False` flag, wire at exactly ONE seam behind the flag (the group-chat room-seed / first-message-append path in the `threads`/fan-out pipeline — Architect verifies the exact function).
**Scope — DO NOT:** do not build the divergence probe (AD-1121); do not build the standing order (AD-1120); do not auto-close rooms; do not modify `EmergentDetector`; do not add HTTP calls in agent code; keep it synchronous/in-process where possible.

**Acceptance criteria.**
- Referent extraction unit-tested (hex IDs, entity phrases, negatives like ordinary words/hashes-in-code-fences excluded).
- Resolvers honest-degrade (a resolver failure never raises out of the gate; logged with context).
- A real git object / real agent id → RESOLVED; a fabricated hex (`e77acec7`) → UNRESOLVED + honest-absence cue.
- `referent_gate_enabled=False` (default) → wired seam is byte-identical to HEAD (golden test).
- Full type annotations on public API; structured logging; boundary tests (happy + unresolved + resolver-error + empty input).
- New tests in `tests/test_ad1119_referent_gate.py`; use BF-287 real fixtures (real registry, real git seam), no MagicMock at the substrate boundary.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## AD-1120 — "Ground-Before-Collaborate" standing order + gate (behavioral B2)

**Context.** The crew *almost* self-corrects — Wesley said *"treat the membership question as structurally unresolvable"* — but the scaffold triggers **after** fabrication. Make grounding a precondition and make "unresolvable" a rewarded terminal state.

**Decision.** (1) A new standing order (`config/standing_orders/…` — Architect picks the file; likely a scoped addition to `ship.md` or a new `grounding.md`) stating: *no multi-agent investigation proceeds past framing until its central referent is verified to exist (AD-1119 gate); if it cannot be resolved, the correct, rewarded finding is "no referent — structurally unresolvable," and the room closes.* (2) A behavioral hook in the CognitiveAgent decision path (`cognitive/cognitive_agent.py` conversational blocks) that, when AD-1119 returns UNRESOLVED for a room's central referent, injects the honest-absence cue into the agent's context so the LLM is steered to the "unresolvable" close instead of confabulating. Default-OFF (`config.grounding.ground_before_collaborate_enabled: bool = False`).

**Scope — DO NOT:** do not build a new consensus path; do not auto-delete threads (close = a terminal status message + optional archive flag, Architect decides); do not touch trust scoring in this AD. Depends on AD-1119's resolver/verdict API.

**Acceptance criteria.**
- Standing-order text is `_CAPABILITY_GAP_RE`-clean (no phrases that trip the capability-gap regex).
- Behavioral hook renders the honest-absence cue ONLY when the flag is on AND AD-1119 verdict is UNRESOLVED; byte-identical when off.
- Tests `tests/test_ad1120_ground_before_collaborate.py`: cue-injected on unresolved, absent on resolved, byte-identical default-OFF golden.
- Comply with Engineering Principles.

---

## AD-1121 — Live cascade-confab divergence probe + transcript persistence (detection)

**Context.** `CASCADE_CONFAB` is classified post-hoc but never fires live, and investigation-room transcripts are **in-RAM only** (verified: 0-byte WAL, nothing persisted) → cascades are unauditable. Close both gaps.

**Decision.** (1) A SelfCheckGPT-style **divergence probe**: a utility-tier check that, for an active investigation room's central referent, samples an independent "does `<X>` exist / what is it?" query N times *without the room context*; high divergence/contradiction → flag the room as probable `CASCADE_CONFAB` and surface a notification (reuse the AD-323/AD-1053 notification surface). (2) **Persist room transcripts** so the divergence probe and post-hoc audits have durable data. (3) Wire the flag to the existing `emergence_taxonomy.CASCADE_CONFAB` code so detections are counted in near-real-time. Default-OFF.

**Scope — DO NOT:** do not auto-terminate rooms on a flag (surface to the Captain); do not re-architect the notification system; do not build new LLM tiers. Depends on AD-1119 (referent extraction) and a transcript-persistence seam.

**Acceptance criteria.**
- Divergence probe is context-free (must not receive the room transcript — that's the load-bearing independence property, per CoVe/SelfCheckGPT).
- Probe honest-degrades (LLM/probe failure → no false CASCADE_CONFAB flag).
- Transcript persistence is additive + default-OFF byte-identical.
- Tests `tests/test_ad1121_confab_probe.py`: divergence→flag, consistency→no-flag, context-free assertion, honest-degrade, default-OFF byte-identical.
- Comply with Engineering Principles.

---

## Handoff notes for the Architect

- Verify EVERY reference against the live codebase before drafting build prompts (import paths, function signatures, the exact wiring seam in the `threads`/fan-out pipeline, the AD-979a honest-absence precedent, the `config.py` Pydantic pattern, the standing-order file set). Do not draft from this doc's assumptions.
- Produce one build prompt per AD in `prompts/ad-1119-*.md`, `prompts/ad-1120-*.md`, `prompts/ad-1121-*.md`, each single-AD-focused with explicit "Do not build" boundaries naming the adjacent ADs.
- Each build prompt's acceptance criteria must include: "Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`."
- Confirm AD numbers against PROGRESS.md at draft time (highest was AD-1118).
