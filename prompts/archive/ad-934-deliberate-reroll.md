# AD-934 (Option C) — In-chat `[THINK]` / `[DELIBERATE]` deep-tier re-roll

**Target repo:** OSS (`d:\ProbOS`). **This AD = AD-934.** Highest committed+pushed: AD-933b (`b1a17a38`).
**Mode:** Builder. Code + tests + gates + commit local. No push.
**Captain decision:** Option C from [prompts/ad-934-in-chat-deliberate.md](ad-934-in-chat-deliberate.md) —
redefine `[THINK]` as a flag-gated deep-tier re-roll of the agent's own draft reply. **NOT** the AD-632 chain.
Options A/B (chain re-dispatch + DM templates) are explicitly NOT built (they remain a hard-stop fork in the
design doc).

## What it does (verified vs HEAD)
An agent may emit `[THINK]` or `[DELIBERATE]` in its draft reply when it judges a turn warrants deeper
reasoning. A new **flag-gated** post-LLM pipeline step parses the marker and, when the flag is ON, makes a
single **deep-tier** LLM pass that reconsiders + improves the draft, replacing the reply text. Marker is
always stripped (never leaks to the Captain). Default OFF → zero behavior change out of the box.

Mechanics confirmed against HEAD:
- `runtime.llm_client.complete(LLMRequest(prompt=, system_prompt=, tier="deep", max_tokens=)) -> LLMResponse`
  with `.content` (e.g. `routers/chat.py:1152`). The `deep` tier exists (`config/system.yaml`).
- Marker parse/strip pattern: mirror `DmSanityGate.extract_create_task`/`strip_create_task` +
  `_CREATE_TASK_RE`/`_CREATE_TASK_STRIP_RE` (`cognitive/dm_sanity_gate.py:51/58`,
  `r"\[CREATE_TASK\b[^\]\n]*\]?"`).
- Config mounting: top-level `SystemConfig` fields `dm_sanity_gate` / `dm_targeted_lookup`
  (`config.py:5243-5244`) — add `dm_deliberate` alongside.
- Teaching hook precedent: `_conversational_task_protocol` (base returns "", Yeo overrides) and
  `_conversational_notebook_protocol` (universal-when-substrate-present) at `cognitive_agent.py:1869+`,
  appended in the conversational branch at `cognitive_agent.py:2368-2378`.
- Pipeline step registration: `DmReplyPipeline._full_steps()` (1:1, 17 steps) and `_escalation_steps()`
  (group, 6 steps after AD-933b) in `cognitive/dm/reply_pipeline.py`.

## Changes

### 1. `src/probos/config.py` — new flag-gated config (default OFF)
Add a new Pydantic model near `DmTargetedLookupConfig`:
```python
class DmDeliberateConfig(BaseModel):  # AD-934
    """AD-934 (Option C): flag-gated [THINK]/[DELIBERATE] deep-tier re-roll.
    Default OFF — opt-in because the re-roll adds a full deep-tier LLM pass
    (latency + cost) per marker-bearing reply."""
    enabled: bool = False
    tier: str = "deep"
    max_tokens: int = 800
```
Mount on `SystemConfig` right after `dm_targeted_lookup` (~line 5244):
`dm_deliberate: DmDeliberateConfig = Field(default_factory=DmDeliberateConfig)  # AD-934`
Zero-config boot must stay byte-identical (default OFF).

### 2. `src/probos/cognitive/dm_sanity_gate.py` — marker parse/strip
Add module-level constants near `_CREATE_TASK_RE` (~line 51):
```python
_DELIBERATE_RE = re.compile(r"\[(?:THINK|DELIBERATE)\b[^\]\n]*\]")
_DELIBERATE_STRIP_RE = re.compile(r"\[(?:THINK|DELIBERATE)\b[^\]\n]*\]?")
```
Add two methods on `DmSanityGate` (mirror `extract_create_task`/`strip_create_task`):
```python
def extract_deliberate(self, text: str) -> bool:
    """AD-934: True iff a well-formed [THINK]/[DELIBERATE] marker is present."""
    return bool(text) and _DELIBERATE_RE.search(text) is not None

def strip_deliberate(self, text: str) -> str:
    """AD-934: remove all [THINK]/[DELIBERATE] markers (well-formed + malformed)
    from Captain-visible text, including the trailing .strip() (AD-572/AD-845 contract)."""
    if not text:
        return text
    return _DELIBERATE_STRIP_RE.sub("", text).strip()
```

### 3. `src/probos/cognitive/dm/reply_pipeline.py` — new step + registration
New method `step_4j_deliberate_parse` (place the method body next to `step_4g_create_task_parse`):
```python
async def step_4j_deliberate_parse(self) -> None:
    """AD-934 (Option C): on a [THINK]/[DELIBERATE] marker, make ONE deep-tier
    LLM pass that reconsiders + improves the agent's draft reply, replacing the
    reply text. Flag-gated (config.dm_deliberate.enabled, default OFF). The
    marker is ALWAYS stripped (even when disabled) so it never leaks. Tier-2
    honest-degrade: a missing client / disabled tier / empty or raised response
    keeps the draft unchanged. NEVER raises."""
    if not self.ctx.response_text or self.ctx.sanity_gate is None:
        return
    cfg = getattr(getattr(self.ctx.runtime, "config", None), "dm_deliberate", None)
    enabled = bool(getattr(cfg, "enabled", False))
    # Always strip the marker first so it never leaks, even disabled.
    has_marker = self.ctx.sanity_gate.extract_deliberate(self.ctx.response_text)
    if not enabled or not has_marker:
        if has_marker:
            self.ctx.response_text = self.ctx.sanity_gate.strip_deliberate(self.ctx.response_text)
        return
    draft = self.ctx.sanity_gate.strip_deliberate(self.ctx.response_text)
    client = getattr(self.ctx.runtime, "llm_client", None)
    if client is None:
        self.ctx.response_text = draft
        return
    try:
        from probos.cognitive.llm_client import LLMRequest
        callsign = self.ctx.callsign or self.ctx.agent_id
        question = (self.ctx.req_message or self.ctx.message_text or "").strip()
        resp = await client.complete(LLMRequest(
            prompt=(
                f"The message you are replying to:\n{question}\n\n"
                f"Your draft reply:\n{draft}\n\n"
                "Reconsider your draft carefully and produce a more thorough, "
                "well-reasoned version. Output ONLY the improved reply text — "
                "no tags, no preamble, no meta-commentary."
            ),
            system_prompt=(
                f"You are {callsign}. You flagged this turn for deeper "
                "deliberation. Improve your own draft reply: tighten the "
                "reasoning, fill gaps, and keep your natural voice. Output only "
                "the final reply."
            ),
            tier=str(getattr(cfg, "tier", "deep")),
            max_tokens=int(getattr(cfg, "max_tokens", 800)),
        ))
        refined = (resp.content or "").strip() if resp else ""
        # Strip any stray marker the re-roll might echo, then adopt or degrade.
        refined = self.ctx.sanity_gate.strip_deliberate(refined)
        self.ctx.response_text = refined or draft
    except Exception:
        logger.warning(
            "AD-934: deliberate re-roll failed for agent=%s; keeping draft",
            self.ctx.agent_id, exc_info=True,
        )
        self.ctx.response_text = draft
```
Register the step:
- In `_full_steps()`: insert `self.step_4j_deliberate_parse,  # AD-934` **between**
  `self.step_4g_create_task_parse` and `self.step_5_episodic_store` (so the refined reply is what gets
  stored / divergence-checked / emitted). This makes `run()` an **18-step** chain — the intended change.
- In `_escalation_steps()`: append `self.step_4j_deliberate_parse,  # AD-934` **after**
  `self.step_4g_create_task_parse` (so a group `[THINK]` reply is also re-rolled). Subset becomes 7 steps.
- Update both docstrings (add 4j to the Included lists; note AD-934).

### 4. `src/probos/cognitive/cognitive_agent.py` — teach the marker (flag-gated, universal)
Add an overridable hook next to `_conversational_task_protocol` (~1869):
```python
def _conversational_deliberate_protocol(self, observation: dict) -> str:
    """AD-934 (Option C): teach the [THINK] reply marker to all crew agents
    WHEN config.dm_deliberate.enabled is True (default OFF -> ""). The agent
    emits [THINK] anywhere in its reply when a turn warrants deeper reasoning;
    DmReplyPipeline.step_4j_deliberate_parse then makes one deep-tier pass to
    improve the draft. Honest-degrade: returns "" when the flag is off or no
    runtime/config is wired. Overridable (Open/Closed)."""
    runtime = getattr(self, "_runtime", None)
    cfg = getattr(getattr(runtime, "config", None), "dm_deliberate", None)
    if not getattr(cfg, "enabled", False):
        return ""
    return (
        "\n\nDeeper reasoning: when a question genuinely warrants more careful "
        "thought than a quick reply, place the marker [THINK] anywhere in your "
        "response. The system will take one extra pass to sharpen your reply "
        "before it is sent. Use it sparingly — only for hard or high-stakes "
        "turns, not routine chat."
    )
```
Invoke it in the conversational branch next to `_task_proto` / `_nb_proto` (~2368-2378):
```python
_delib_proto = self._conversational_deliberate_protocol(observation)
if _delib_proto:
    composed += _delib_proto
```
**Gap-regex safety (memory: `_CAPABILITY_GAP_RE`):** the protocol string above must NOT contain phrases like
"can't", "cannot", "don't have", "unable to", "not able to". The text above is already phrased to avoid them
— keep it that way. Verify the final string against the gap regex before shipping.

## Tests — `tests/test_ad934_deliberate.py` (BF-287: real fixtures, a real-but-fake LLM client stub), floor +10
A `_FakeLLMClient` exposing `async def complete(self, request, *, priority=...)` returning a small object
with `.content` (NOT MagicMock). A real `DmSanityGate`. Build `DmReplyContext` directly (the 7+ existing
constructions in tests are the precedent) with a `SimpleNamespace` runtime carrying `config` +
`llm_client`. For the hook test, a minimal CognitiveAgent-like with `_runtime`.
1. **`extract_deliberate`** — True for `[THINK]`, `[THINK be rigorous]`, `[DELIBERATE]`; False for no marker / empty.
2. **`strip_deliberate`** — removes the marker + trailing whitespace; idempotent on no-marker text.
3. **Flag OFF + marker** — `step_4j` strips the marker, makes NO llm call (fake client asserts 0 calls),
   `response_text` == draft-minus-marker.
4. **Flag ON + marker + refined content** — fake client returns `"refined reply"`; `response_text` ==
   `"refined reply"`, marker gone, client called exactly once with `tier == "deep"`.
5. **Flag ON + NO marker** — no llm call, `response_text` unchanged.
6. **Flag ON + marker + client returns empty** — honest-degrade: `response_text` == draft (marker stripped).
7. **Flag ON + marker + client raises** — honest-degrade: `response_text` == draft, no exception propagates.
8. **Flag ON + `llm_client is None`** — degrade to draft, no crash.
9. **`run()` now invokes 18 steps incl. 4j in order** (4g → 4j → 5); **`run_escalation_only()` now invokes
   {4c,4e,4i,4h,4f,4g,4j}** — update the AD-933 / AD-933b step-membership tests accordingly (obsolete-contract
   updates, the same pattern AD-933/933a/933b used).
10. **`_conversational_deliberate_protocol`** — returns "" when flag off; non-empty when on; the returned
    string contains NO `_CAPABILITY_GAP_RE` phrase (assert against the actual regex if importable, else assert
    the banned substrings are absent). `DmDeliberateConfig` defaults: `enabled is False`, `tier == "deep"`.

## Gates (run both, report exact counts)
- Focused: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad934_deliberate.py -q -n 0 -p no:cacheprovider`
- Blast: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -k "dm or reply or pipeline or sanity or deliberate or escalat or cognitive_agent or config" -q -p no:cacheprovider`
  (large suite ~3 min; `-q`, tail output, NO `-x`. Pre-existing `test_skill_agent.py::TestSkillPipeline`
  serial-isolation flakes are KNOWN — if they appear, re-run that file alone with `-n 0` to confirm green
  in isolation and report them as pre-existing, not a regression.)
No UI change → no Vitest.

## Acceptance
- Default OFF → zero behavior change; zero-config boot byte-identical.
- Flag ON + `[THINK]` → one deep-tier re-roll replaces the draft; marker never leaks; honest-degrade keeps
  the draft on any failure.
- `run()` = 18 steps (4j between 4g and 5); `run_escalation_only()` = 7 steps (4j last). 1:1 and group both
  gain the capability behind the flag.
- The teaching protocol is gap-regex-safe and only appears when the flag is ON.
- Both gates green (modulo the known skill-pool isolation flakes). Verify Engineering-Principles compliance
  (`.github/copilot-instructions.md`).

## Do NOT (scope fence)
- Do **not** build Option A or B: no AD-632 chain wiring, no `_pending_sub_task_chain`, no
  `_build_chain_for_intent` DM branch, no new chain prompt templates, no two-turn re-dispatch.
- Do **not** change `DmSanityGateConfig` (the duplicated cluster-invariant class) — add the SEPARATE
  `DmDeliberateConfig` instead.
- Do **not** change `run()`'s existing 17 steps' order/bodies, `DmReplyContext` fields, `build_response`,
  the AD-933a episodic write, the AD-933b ref surfacing, the facilitator, `IntentMessage`, or the Ward Room.
- Do **not** teach the marker when the flag is OFF (the hook must return "").
- Forward markers: **AD-934a** (per-agent opt-in / richer teaching + use the `[THINK reason]` focus hint in
  the re-roll prompt), **AD-934b** (surface a subtle "deliberated" indicator in the HXI).
- No push. Stage explicit paths (NOT `git add -A`); deletion-audit before commit.

## Trackers (after gates green)
- `docs/development/roadmap.md`: AD-934 row, SHIPPED + 2026-06-08 + gate note.
- `PROGRESS.md`: prepend an AD-934 block.
- `DECISIONS.md` (match where AD-933b went): AD-934 entry — Option C chosen over A/B (why: agentic loop
  already serves deep tool-work; this is the contained tool-free inline-deliberation increment), flag default
  OFF, the 4-file mechanism, forward markers AD-934a/AD-934b.
