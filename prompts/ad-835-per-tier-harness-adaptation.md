# AD-835 — Per-Tier Harness Adaptation Layer (system-prompt + sampling shaping)

**Status:** Ready
**Dependencies:** AD-732 (`_LLM_TIERS` single source of truth), AD-463 (ModelRouter), AD-720d/731 (multimodal messages + attachment refs)
**Estimated tests:** 6 pytest

## Problem

The VS Code "Coding Harness" blog (2026-05-15) makes the case that *the harness — not
the model — is the product*, and its single strongest differentiator is **per-model
adaptation**: the harness selects a different system prompt per model (Sonnet ≠ 4.5 ≠
Opus), uses different edit tools per provider, and retunes sampling/loop behavior per
checkpoint.

ProbOS's harness ([`AgenticLoop`](../src/probos/cognitive/swe_harness/agentic_loop.py),
AD-543–549) and tiered client
([`llm_client.py`](../src/probos/cognitive/llm_client.py)) already have the *seams* for
this but no adaptation layer:

- `_call_openai` composes the system message uniformly for every tier/model
  ([`llm_client.py:900-905`](../src/probos/cognitive/llm_client.py)). A `deep` (Opus-class)
  call and a `fast` (Sonnet-class) call get the identical system prompt.
- Vendor-shape adaptation already exists for one concern only — attachment refs
  (`_resolve_attachment_refs_for_openai`, BF-268) and `api_format` routing
  (openai/ollama). There is no general hook for per-tier prompt/sampling shaping.
- Tier sampling defaults (`temperature`, `top_p`, `max_tokens`) are applied ad-hoc inline
  ([`llm_client.py:586-602`](../src/probos/cognitive/llm_client.py)).

**Net:** every tier is prompted identically. There is no place for the operator to say
"the `deep` tier needs a terse, structured preamble" or "the `fast` tier needs an explicit
reminder to emit tool calls rather than narrate them" — exactly the per-model tuning the
VS Code blog identifies as the highest-leverage harness work.

## Solution

Introduce a minimal, config-driven **per-tier adaptation hook** applied at the system-
message composition point in `_call_openai`. v1 scope: a per-tier **`system_prompt_suffix`**
appended to the composed system prompt, sourced from the existing Pydantic tier config.
This is the seam; richer per-model tool-format remapping (Claude `replace_string_in_file`
vs GPT `apply_patch`) is explicitly deferred to **AD-835b**.

No change to the loop, no change to tool execution, no change to fallback semantics.

### Section 1 — Config: add `system_prompt_suffix` to the per-tier model

File: `src/probos/config.py`

Add an **optional** `system_prompt_suffix: str | None = None` field to the existing
per-tier LLM config model (the model returned/consumed by `tier_config(tier)`). Per
config standards: Pydantic field, sensible default (`None` = no-op), validated at parse
time. ProbOS must still boot with zero config.

Acceptance for this section: `config.tier_config("deep").get("system_prompt_suffix")`
returns `None` by default and the operator-supplied string when configured in
`config/system.yaml`.

### Section 2 — Apply the suffix in `_call_openai`

File: `src/probos/cognitive/llm_client.py`

At the system-message composition point (both the `request.messages is not None` branch
and the prompt-synthesis `else` branch), if the active tier's config carries a non-empty
`system_prompt_suffix`, append it to the system message content (joined by `\n\n`). The
tier is already known at the call site via the `tc` (tier config) in scope at
[`llm_client.py:576-586`](../src/probos/cognitive/llm_client.py); thread the resolved
`system_prompt_suffix` into `_call_api` → `_call_openai` alongside the existing
`effective_*` sampling params (do NOT read global state inside `_call_openai`).

Rules:
- Empty / `None` suffix → byte-identical behavior to today (regression-safe).
- Suffix applies to the composed system message only — never to user/tool messages.
- Applies per the **attempt** tier during fallback (a fallback to `standard` uses
  `standard`'s suffix, not the originally requested tier's).

### Section 3 — Document the seam for AD-835b

Add a short comment block above `_call_openai` noting that per-tier tool-format remapping
(edit-tool name/shape per model family) is the planned AD-835b extension and must hook the
same `tc`-threaded adaptation path, not a new global.

## Tests

New file: `tests/test_ad835_tier_adaptation.py`

1. **Default is no-op** — tier config without `system_prompt_suffix`; assert the posted
   system message equals the un-suffixed composition (mock the HTTP client / capture
   payload).
2. **Suffix appended (prompt-synthesis branch)** — `request.messages is None`, tier has a
   suffix; assert system message ends with `\n\n<suffix>`.
3. **Suffix appended (pre-built messages branch)** — `request.messages` provided with a
   leading system message; assert suffix appended to that system message.
4. **Suffix not applied to user/tool messages** — assert only the system message changed.
5. **Fallback uses attempt-tier suffix** — requested `deep` unreachable → fallback
   `standard`; assert `standard`'s suffix used, not `deep`'s.
6. **Config default** — `config.tier_config("deep").get("system_prompt_suffix") is None`
   on a zero-config boot.

Run: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad835_tier_adaptation.py -v -n 0`

## What This Does NOT Change

- No change to `AgenticLoop`, tool execution, or `ToolExecutor`.
- No change to the fallback chain membership (`_TIER_ORDER`) or `_LLM_TIERS`.
- No per-model **tool-format** remapping — that is AD-835b (deferred, seam documented).
- No change to `api_format` routing or attachment-ref resolution.
- No change to ModelRouter (AD-463) behavior.

## Tracking

- `PROGRESS.md` — add AD-835 CLOSED entry.
- `decisions-era-5-unification.md` — append AD-835: per-tier system-prompt adaptation hook;
  seam for AD-835b tool-format remap. Motivated by the VS Code harness-adaptation blog.

## Acceptance Criteria

1. Operator can set a per-tier `system_prompt_suffix` in `config/system.yaml` and it is
   appended to that tier's system message only.
2. Zero-config boot is byte-identical to pre-AD-835 behavior.
3. `tests/test_ad835_tier_adaptation.py` passes (6 tests).
4. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-05-31)

```
src/probos/cognitive/llm_client.py:32   _LLM_TIERS single source of truth (AD-732)
src/probos/cognitive/llm_client.py:134  self._config.tier_config(tier) -> per-tier dict
src/probos/cognitive/llm_client.py:576  tc = self._tier_configs.get(attempt_tier, ...)  (tier known at call site)
src/probos/cognitive/llm_client.py:586  inline per-tier temperature/top_p/max_tokens application
src/probos/cognitive/llm_client.py:884  async def _call_openai(...)
src/probos/cognitive/llm_client.py:900  system message inserted/composed here
```
