# Self-perception framing (AD-727 / AD-722e)

## Plain summary

Some ProbOS crew (Counselor, Architect; opt-in for others) carry a deterministic, structured projection of their own avatar state into the prompt assembly pipeline. This is **denser self-state injection**, not consciousness. The agent does not "see itself" — the same digital state that drives the renderer is also rendered into English and handed to the agent's LLM context.

If you read about an AI "passing the mirror test," and the article is about ProbOS, this is the feature it is talking about. We are framing it accurately ourselves first so the press cannot frame it sensationally on our behalf.

## Architecture (v1, AD-722e)

The renderer reads an `AppearanceProfile.dsl` (body type, hair style, outfit, primary color) and an `AvatarTelemetrySnapshot` (working state, expression-resting, mouth-active, modulation rate, modulation pitch). v1 of AD-722e adds **one pure-function projector** that reads the same two structures and returns a `SelfPerceptionProjection` dataclass. The agent's LLM context already includes an INTEROCEPTION block; AD-722e adds one line — `pipeline_version: 1.0.0` — alongside the existing self-observation text.

That is the whole v1 architecture. Zero LLM calls. Zero browser canvas reads. Zero pixel bytes anywhere in the loop. Nothing leaves the process; nothing enters that was not already in the process.

## The seven hard rules

Filed in DECISIONS.md under AD-727. Code-enforced by `tests/test_ad727_safety_constraints.py`.

1. **Aesthetic self-judgment is READ-ONLY with respect to trust/Hebbian.** The projector cannot mutate trust state or Hebbian weights. AD-722a's divergence detector can — that detector is about *reasoning-vs-output*, not *image-vs-self-image*.
2. **Pipeline-version visibility.** Every projection carries a `pipeline_version`. When the renderer changes, the agent is informed explicitly via a different value of that string — not silently mutated.
3. **Asymmetric rollout is prohibited.** Enabling self-perception for one agent and not for another similarly-situated agent is a governance defect. Operators ship crew-wide or explicitly role-scoped (Counselor, visible bridge officers).
4. **Vision-LLM use, if introduced in a future AD, runs against backend-server-side render only.** Never browser-capture. v1 has no vision-LLM call at all; this rule is a permanent guard against the temptation to add one later.
5. **Browser-side capture is permanently prohibited.** Any code path that touches `getDisplayMedia`, `chrome.tabCapture`, `puppeteer`, `playwright`, `selenium`, or equivalent is a violation of AD-727 and fails CI.
6. **Aesthetic preferences are proposals, not unilateral changes.** Mirrors AD-721d's DSL approval model — the agent can ask, the Captain decides.
7. **Self-perception projection takes `self.id` as the ONLY agent parameter.** Cross-crew visual perception is a separate AD (AD-722e-3 / existing AD-729 family) with its own governance review.

## Forward markers

- **AD-722e-2** — vision-LLM verification of self-render. Runs against backend-server-side render only; per AD-727 rule #4.
- **AD-722e-3** — cross-crew visual perception. Covered by the existing AD-729 family (filed [#587](https://github.com/seangalliher/ProbOS/issues/587)).
- **AD-722e-4** — aesthetic-preference proposals (extending AD-721d to "I prefer" semantics).

## What this is not

- **Not consciousness.** The agent receives a denser self-context block during prompt assembly. It does not "experience" being seen.
- **Not a mirror.** No image is captured, no image is shown. The deterministic projection is the only artifact.
- **Not novel.** Other systems inject self-context (chain-of-thought, scratchpad, agent state summaries). ProbOS injects it from the same source-of-truth that drives the avatar renderer; the novelty is the coupling between rendered presentation and structured self-description, not the injection itself.

## Why we wrote this down

If we don't say what this is, someone else will say what they think it is. AD-727 made the joint Counselor + Architect review gate a hard rule because this is the first AD in ProbOS where a build change could plausibly cause **psychological** harm rather than operational harm. The seven rules are the constraint stack. The tests are the gate. This document is the part the press can read.
