# AD-735 — Verified self-identity grounding on the DM path (`whoami`)

**Issue:** [#795](https://github.com/seangalliher/ProbOS/issues/795)
**AD number:** AD-735 (reserved forward-marker — NOT new; current highest shipped is AD-828, Wave 198)
**Risk:** LOW (additive; rides the existing AD-725 read-only pre-LLM lookup seam)
**Target repo:** OSS (`d:\ProbOS`)

---

## 0. Problem & the architectural correction (READ FIRST)

Issue #795 was filed after an agent (Ezri) **confabulated** the spelling/age of her own
identity in a DM, then self-corrected once the AD-592 confabulation guard + AD-588/589
telemetry-grounded introspection kicked in. The desire: when an agent is asked about its
**own** name spelling, callsign, department, or age, it should answer from **literal
verified fact**, not from generation.

The issue proposes "expose a `whoami` **tool** the LLM **calls**, registered via the
**AD-720b tool-grant pattern**." **This premise does not match the architecture and must
not be built as written.** Ground-truth verification (2026-05-29) found:

1. **The crew-agent DM path has no LLM function-calling loop.** `routers/agents.py:agent_chat`
   → `direct_message` intent → a **one-shot** instructions-based LLM call →
   `DmReplyPipeline`. There is no place for the LLM to "call a tool" mid-turn.
2. **The only agentic tool-calling loop is `cognitive/swe_harness/agentic_loop.py`**
   (`AgenticLoop` / `AgenticResult`), used by the **Builder / SWE harness only** — not the
   chat path.
3. **AD-720b is a capability/permission grant** (`api_models.ChatToolGrantRequest` L327;
   `routers/chat.py:chat_tool_grant` L1020 emits `tool_grant_issued`). It is **not** LLM
   function/tool registration.

**The architecturally honest realization of the issue's intent is the AD-725 seam.**
AD-725 (`cognitive/dm_targeted_lookup.py`) already implements exactly the RAG-style shape
needed: a fast classifier detects a retrieval-like sub-intent in the incoming DM, runs **at
most one read-only lookup before the LLM call**, and prepends the result as a
`--- Targeted Recall (<type>) ---` block into `message_text`. Adding a new `"identity"`
lookup type makes the verified self-identity facts arrive as a **high-salience, fact-shaped
block immediately before generation** — tool-grounded-equivalent, without inventing a
function-calling loop that does not exist.

### Phantom-API corrections (issue #795 → reality)

| Issue #795 says | Reality (verified at HEAD) |
|---|---|
| `self._callsign` | `self.callsign` (public; set by naming ceremony; `_resolve_callsign()` ~L4567 falls back via `runtime._identity_registry.get_by_slot(self.id)`) |
| `self._agent_type` | `self.agent_type` (public) |
| `self._birth_certificate` (attr) | No such attr. Fetch the cert via `runtime._identity_registry.get_by_slot(self.id)` → `AgentBirthCertificate | None` |
| cert `created_at_iso` | cert `birth_timestamp` (float epoch; format with `datetime.fromtimestamp(...).isoformat()`) |
| cert `sha` | cert `certificate_hash` (SHA-256 hex) |
| "register via AD-720b tool-grant" | N/A — AD-720b is a permission grant. Use the AD-725 lookup seam. |

`AgentBirthCertificate` (real fields, `identity.py:142`): `agent_uuid`, `did`, `agent_type`,
`callsign`, `instance_id`, `vessel_name`, `birth_timestamp` (float), `department`,
`post_id`, `baseline_version`, `certificate_hash`.

---

## 1. Deliverables

### 1.1 `whoami()` data-assembly method on `CognitiveAgent`

File: `src/probos/cognitive/cognitive_agent.py`

Add a public method (full type annotations) that assembles verified identity facts from
**authoritative sources only**, with Tier-2 log-and-degrade (never raises):

```python
def whoami(self) -> dict[str, str]:
    """AD-735: assemble verified self-identity facts for fact-grounded DM replies.

    Sources are authoritative (birth certificate + public identity attrs), never
    generated. Honest-degrade: missing cert yields the public-attr subset.
    """
```

Resolution rules (use ONLY verified sources — no phantom fields):
- `callsign`: seed from `self._resolve_callsign()` (canonical resolver at
  `cognitive_agent.py:4567`; applies the BF-101 cert fallback — keeps ONE resolution path).
  If empty, `self.agent_type`.
- `agent_type`: `self.agent_type`.
- Fetch cert: `rt = getattr(self, "_runtime", None)`; if `rt` and
  `getattr(rt, "_identity_registry", None)`: `cert = rt._identity_registry.get_by_slot(self.id)`
  (wrap in try/except → `cert = None` on failure, log `debug`).
- If `cert` is not None, prefer cert values: `callsign=cert.callsign`,
  `department=cert.department`, `did=cert.did`,
  `birth_iso = datetime.fromtimestamp(cert.birth_timestamp).isoformat()` — **guard the float**:
  only convert when `isinstance(cert.birth_timestamp, (int, float))`, else omit `birth`
  (a malformed cert must not raise inside the conversion). Confirm `from datetime import datetime`
  is in module scope before use.
  `certificate_hash=cert.certificate_hash[:12]` (short prefix for display),
  `vessel_name=cert.vessel_name`.
- If `cert` is None: `department` falls back to `get_department(self.agent_type)` from
  `standing_orders` (import already used in this module); `did`/`birth_iso`/`certificate_hash`
  omitted (do NOT fabricate).
- Return a `dict[str, str]` containing only the keys that resolved (drop empty/None).

Also add a small formatter used by the lookup dispatcher (keep it here so the canonical
spelling lives next to the data):

```python
def whoami_block(self) -> str:
    """AD-735: render whoami() as a compact verified-fact block for prompt injection."""
```

Format (one fact per line; spell the callsign explicitly so name-spelling questions are
grounded):

```
Callsign: Ezri (spelled E-z-r-i)
Role / agent_type: counselor
Department: Medical
Commissioned: 2026-03-14T09:21:07
Identity hash: 4f1a9c2b8d03
```

The "spelled X-y-z" expansion must be derived from the resolved callsign with `"-".join(callsign)`.

### 1.2 New `"identity"` lookup type in AD-725

File: `src/probos/cognitive/dm_targeted_lookup.py`

- Extend the `LookupType` `Literal` with `"identity"`.
- Add `_IDENTITY_PATTERNS` (compiled, `re.I`). Cover: name spelling, "who are you",
  callsign, department, age/birth. Suggested:
  ```python
  _IDENTITY_PATTERNS = [
      re.compile(r"\b(your|whats?\s+your)\s+(name|callsign)\b", re.I),
      re.compile(r"\bhow\s+(is|do you spell)\b.*\byour\s+(name|callsign)\b", re.I),
      re.compile(r"\bspell(ed|ing)?\b.*\byour\s+(name|callsign)\b", re.I),
      re.compile(r"\bwho\s+are\s+you\b", re.I),
      re.compile(r"\bwhat\s+(is\s+)?your\s+(department|role|rank)\b", re.I),
      re.compile(r"\b(how\s+old\s+are\s+you|when\s+were\s+you\s+(born|commissioned))\b", re.I),
  ]
  ```
  **Pattern discipline (Architect Recommended):** anchor on `your\s+(name|callsign)` rather
  than bare `name`/`role`. The originally-drafted `r"\bspell(ed|ing)?\b.*\bname\b"` and
  `r"\bwhat\s+(department|role)\b.*\byou\b"` over-trigger on *"how do you spell the name of
  that function"* and *"what role do you want me to play"* — the tightened forms above fix that.
- In `RegexSubintentClassifier.classify`, add `identity` to the ladder. **Place it FIRST**
  (before episodic) — it is cheap, highly specific, and self-identity should win over a
  generic "did we talk" episodic match when both fire.
- In `LookupDispatcher`: add `identity` to the `_is_lookup_enabled` dict (real shape is a
  dict literal keyed by `lookup_type` read with `.get(..., False)`) — add
  `"identity": self._cfg.identity_enabled`. Gate by the new config flag (see 1.3).
- Add an `identity` dispatch branch in `maybe_lookup` (mirror the existing branch structure;
  stay inside the same firewall — one lookup/turn, read-only, hard timeout, **no intent_bus**):
  - Resolve the target agent: `agent = self._runtime.registry.get(agent_id)`. **The accessor
    is confirmed `.get(agent_id)`** (`substrate/registry.py:51`,
    `def get(self, agent_id) -> BaseAgent | None`). **`get_by_id` does NOT exist — do not use
    it.** Tier-2 degrade to a `None` result if the agent is not found.
  - `content = agent.whoami_block()` (guard: only call if the attribute exists, since the bus
    can carry non-CognitiveAgent targets — `if hasattr(agent, "whoami_block")`).
  - Return `TargetedLookupResult(lookup_type="identity", query=message, content=content, elapsed_ms=...)`.

### 1.3 Config flag

File: `src/probos/config.py`

Add `identity_enabled: bool = True` to `DmTargetedLookupConfig` (Pydantic `BaseModel` at
`config.py:4824`; mirrors the existing `enable_oracle/episodic/codebase/knowledge` fields).
It is cheap, in-memory, zero-IO, so default-on **within** the AD-725 master gate
(`DmTargetedLookupConfig.enabled`, `config.py:4833`, which remains default `False`). Wire it
into the `_is_lookup_enabled` dict in `dm_targeted_lookup.py`.

### 1.4 Instruction nudge (small — do NOT replace the existing identity block)

File: `src/probos/cognitive/standing_orders.py` (the `_build_personality_block` /
`compose_instructions` area, AD-393/BF-083 identity line).

Append **one or two lines** (keep it terse) instructing the agent to defer to the injected
block when present:

> When a `--- Targeted Recall (identity) ---` block is present, those are your verified
> commissioning facts (callsign spelling, department, age). Answer self-identity questions
> from that block verbatim; never guess your own name spelling or age.

Do **not** remove or restructure the existing "You are {callsign}..." identity block — the
issue is attention/recall under questioning, not absence.

### 1.5 Tests

File: `tests/test_ad735_whoami_identity.py` (new). Use real fixtures where practical
(real `SystemConfig`, a real or minimally-faithful birth-certificate object) — **avoid
MagicMock at substrate boundaries** (user-memory BF-287 phantom-via-MagicMock lesson).

Required cases (each Arrange-Act-Assert, one behavior each):
1. `whoami()` happy path — agent with a cert returns canonical `callsign`, `department`,
   `birth` ISO, `certificate_hash` prefix from the cert (not from public attrs).
2. `whoami()` honest-degrade — no cert / no `_identity_registry` → returns the public-attr
   subset (`callsign`, `agent_type`, derived `department`) and omits `did`/`birth`/`hash`
   (asserts no fabricated keys).
3. `whoami_block()` spells the callsign — assert `"E-z-r-i"`-style expansion appears for a
   known callsign.
4. Classifier detects identity — `RegexSubintentClassifier().classify("how is your name spelled?", agent_id="a1")`
   returns `("identity", ...)`. **Plus explicit negative cases (Architect Recommended) so the
   tightened patterns are enforced:** *"how do you spell the name of that function"* must NOT
   return `"identity"`; *"what role do you want me to play"* must NOT return `"identity"`. Also
   assert the five existing AD-725 ladder messages ("what time is it?", "what did we discuss
   last time?", "which file is FooBar defined in?", "according to the manual…", "hi") keep
   their prior classifications (no identity over-trigger regression).
5. Dispatcher injects the block — with `enabled=True, identity_enabled=True`, `maybe_lookup`
   returns a `TargetedLookupResult(lookup_type="identity", content=<block>)`; with
   `identity_enabled=False` it returns `None` for an identity message.
6. Firewall preserved — identity lookup performs no intent_bus broadcast and respects the
   timeout (mirror an existing AD-725 firewall test).

Run focused first, then the full suite:
- `D:\ProbOS\.venv\Scripts\pytest.exe tests/test_ad735_whoami_identity.py -q`
- `D:\ProbOS\.venv\Scripts\pytest.exe tests/test_ad725_dm_targeted_lookup.py tests/test_hxi_chat_integration.py -q`
- Full gate: `D:\ProbOS\.venv\Scripts\pytest.exe tests/ -x -q`

---

## 2. Acceptance criteria

- `CognitiveAgent.whoami()` and `whoami_block()` exist, are fully type-annotated, and pull
  ONLY from verified sources (cert via `_identity_registry.get_by_slot`, `self.callsign`,
  `self.agent_type`, `get_department` fallback). No phantom fields.
- `dm_targeted_lookup.py` has an `"identity"` `LookupType`, `_IDENTITY_PATTERNS`, a
  classifier branch (checked first), and a read-only dispatch branch that calls
  `agent.whoami_block()` and stays inside the AD-725 firewall (one lookup/turn, no bus, hard
  timeout).
- `DmTargetedLookupConfig.identity_enabled: bool = True` added and honored.
- One/two-line instruction nudge added; the pre-existing identity block is unchanged.
- `tests/test_ad735_whoami_identity.py` passes (6 cases above), and the existing AD-725 +
  agent_chat / HXI chat tests still pass. Report the full-suite test count before/after.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## 3. Scope boundaries — do NOT

- Do **NOT** add an LLM function-calling / tool loop to the crew chat path. There is none;
  do not create one.
- Do **NOT** replace, move, or restructure the existing `compose_instructions` /
  `_build_personality_block` identity line.
- Do **NOT** touch `IntrospectionAgent`, build a general introspection API, or add a slash
  command. (`agent_info` etc. are out of scope.)
- Do **NOT** modify AD-720b, `BaseAgent`, or `IntentMessage` protocols.
- Do **NOT** change `swe_harness/agentic_loop.py`.
- Do **NOT** flip the AD-725 master `enabled` flag default (stays `False`).

---

## 4. Architecture decision — RATIFIED by Architect review (2026-05-29)

**AD-725 coupling.** Because identity-lookup rides the AD-725 dispatcher, it only fires when
`dm_targeted_lookup.enabled=True` (default **OFF**). The Architect ratified shipping v1 on
the AD-725 seam: the AD-725 firewall (one-lookup/turn, read-only, hard timeout, no-bus) is
exactly the envelope this injection needs; an independent always-on path would duplicate
that firewall machinery (DRY violation) and force the regex classifier to run on every DM
turn even where the operator deliberately disabled targeted-lookup cost. `identity_enabled`
defaults `True` **within** the master gate, so grounding rides for free the moment AD-725 is
enabled.

**Required deliverable (part of the contract, not just prose):** file the **AD-735a** forward
marker — add an OPEN entry to `PROGRESS.md` (and `docs/development/roadmap.md` if a row is
warranted): *"AD-735a — promote identity-lookup to an always-on independent pre-LLM
injection, decoupled from the AD-725 master gate, if AD-725 remains default-off long-term."*

---

## 5. Files touched (anticipated)

- `src/probos/cognitive/cognitive_agent.py` — `whoami()` + `whoami_block()` (~40 LOC)
- `src/probos/cognitive/dm_targeted_lookup.py` — `"identity"` type + patterns + classifier +
  dispatch branch (~30 LOC)
- `src/probos/config.py` — `DmTargetedLookupConfig.identity_enabled` field (1 line)
- `src/probos/cognitive/standing_orders.py` — 1–2 line nudge
- `tests/test_ad735_whoami_identity.py` — new (~6 tests)
- `PROGRESS.md` — AD-735 shipped entry + AD-735a OPEN forward marker
