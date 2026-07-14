# BF-667 — Distinguish asserted referent identifiers from conceptual node-noun phrases

**Verdict:** APPROVED FOR BUILDER
**One-line:** Classify identifier assertion at extraction time, resolve bare alphabetic locator names before deciding actionability, and keep unresolved conceptual nouns out of AD-1119 warnings, AD-1120 cues, and AD-1121 probes.

**Status:** Ready to build
**Type:** Bug fix — **BF-667**; no new AD and no `DECISIONS.md` entry
**GitHub issue:** #1033 — https://github.com/seangalliher/ProbOS/issues/1033
**Exact base HEAD:** `5d3c1b5f682bcea8762ffac6f98e2d9abe19eca2`
**Numbering verified:** highest shipped entries at this base are **AD-1121** and **BF-666**; issue #1033 reserves BF-667
**Dependencies:** AD-1119, AD-1120, AD-1121, BF-660, BF-663, AD-970
**License disposition:** none — deterministic standard-library regex/dataclass policy only; no dependency or absorbed external code
**Estimated tests:** 13–18 additions/updates across the four existing referent/fan-out suites; no new test file

## Scope

Repair only referent extraction metadata, unresolved-versus-ambiguous policy, and the existing group-fan-out warning/central-selection seam.

The implementation must guarantee:

1. bare alphabetic `node|record|entity <noun-or-name>` phrases are recognized but marked `implicit` rather than treated as asserted absent identifiers;
2. an implicit token that any existing resolver confirms remains `RESOLVED`;
3. an implicit token that no resolver confirms is placed in `GroundingVerdict.ambiguous`, receives no cue, is absent from `verdict.unresolved`, and cannot become central or probe-eligible;
4. machine-shaped, explicitly marked, quoted, hexadecimal, and genuine service forms remain `strong` and preserve existing unresolved cue/probe behavior;
5. BF-660 grammar continuations are still rejected before confidence classification — no noun blacklist is added;
6. a later strong occurrence promotes an earlier implicit duplicate without moving its first-seen position;
7. the AD-1119 warning accurately reports central/AD-1120/AD-1121 state and no longer claims “no behavioral change” while either behavior flag is enabled;
8. central-token selection is still computed at most once per seed and reused for warning disposition, cue return, and probe scheduling;
9. default-OFF integration behavior remains byte-identical, while the Captain’s current local `config/system.yaml` opt-in values remain unchanged; and
10. Git, agent, callsign, ward-room, service, cue, probe, task-scheduling, notification, evidence, trust, consensus, and episodic authority remain unchanged.

No UI, config, dependency, resolver, probe-classifier, or storage work is authorized.

---

## Problem and verified root cause

At the exact base:

- `src/probos/cognitive/referent_gate.py:50-53` has one case-insensitive `_ENTITY_RE` for `node(?: id)?|record|entity` followed by any 2–64-character ASCII token.
- `src/probos/cognitive/referent_gate.py:54-92` has BF-660’s finite grammar stop-set. It correctly rejects continuations such as `node is`, `record shows`, and `entity was`, but every other alphabetic noun remains identifier-like.
- `src/probos/cognitive/referent_gate.py:147-156` `_is_entity_identifier()` returns one Boolean. It cannot distinguish “recognized name worth resolving” from “syntactically asserted identifier whose absence is actionable.”
- `src/probos/cognitive/referent_gate.py:159-189` extracts three kinds, sorts by source position, dedupes with first-seen wins, and stops at `_MAX_REFERENTS=20`. There is no later-evidence promotion.
- `src/probos/cognitive/referent_gate.py:109-119` frozen `Referent` carries only `token/kind/raw`; `src/probos/cognitive/referent_gate.py:122-137` frozen `GroundingVerdict` carries only `results/unresolved/cues`.
- `src/probos/cognitive/referent_gate.py:419-448` turns every all-resolver-false token into `UNRESOLVED`, appends it to `unresolved`, and creates an honest-absence cue. It has no non-actionable ambiguity lane.
- `src/probos/routers/thread_fanout.py:89-96` duplicates a downstream kind/stopword heuristic. It cannot reject open-ended conceptual nouns such as `identity`, `membership`, `provenance`, `cluster`, `set`, or `health` without becoming an ever-growing noun blacklist.
- `src/probos/routers/thread_fanout.py:966-1063` logs every `verdict.unresolved` before central selection, then computes one central token for AD-1120/1121. The log at line 1018 says `(observe-only, no behavioral change)` even when the local AD-1120/1121 flags are enabled and a central token can immediately create an injected cue and background probe.
- `src/probos/routers/thread_fanout.py:1066-1117` already computes one central token and preserves the git-availability guard for hexadecimal candidates. BF-667 must reuse, not duplicate, that helper.
- `src/probos/routers/thread_fanout.py:1247` calls the gate once before any group agent is dispatched. Both Captain turns (`src/probos/routers/threads.py:429`) and AD-970 agent-created kickoffs (`src/probos/proactive.py:4264`) reach this same seam.
- `config/system.yaml:1996-1998` locally enables all three grounding flags. Pydantic defaults at `src/probos/config.py:6055-6077` remain false. No flag or config edit belongs in this BF.

### Empirical pre-fix signatures at the pinned base

A direct import probe against the exact HEAD produced:

| Input | Current extraction / action |
|---|---|
| `node identity distribution` | entity `identity` → `UNRESOLVED` + cue; current central selector chooses `identity` |
| `node membership review` | entity `membership` → actionable |
| `node provenance analysis` | entity `provenance` → actionable |
| `node cluster topology` | entity `cluster` → actionable |
| `node set changes` | entity `set` → actionable |
| `node health status` | entity `health` → actionable |
| `node oracle` | entity `oracle` → actionable even when unknown |
| `node id oracle` | entity `oracle` → actionable (must remain so) |
| `node oracle_probe` / `node alpha-2` / `node alpha2` | actionable machine-shaped entities (must remain so) |
| `node "oracle"` / `node 'oracle'` | no extraction (BF-667 adds strong quoted assertion) |
| ``node `oracle` `` | no extraction because inline code is stripped (must remain excluded) |
| ``node id `oracle_probe` `` | currently falls back to false token `id`; BF-667 must produce no referent, not `id` |
| `e77acec7` / `node e77acec7` | strong hex `e77acec7` (must remain actionable) |
| `Node membership` | current overlap yields service `Node` plus entity `membership`; neither is a sound asserted identifier |
| `Oracle membership` / `oracle_service telemetry` | genuine service forms (must remain strong and resolver-backed) |

Read-only sampling of `%LOCALAPPDATA%\ProbOS\data\chat_threads.db` on 2026-07-14 found three persisted messages containing the exact phrase `node identity distribution`. A 5,000-message tail scan found 49 `node|record|entity + alphabetic-token` spans, including conceptual `node identity`, `node set`, `node membership`, `node provenance`, and `node cluster`, alongside BF-660 grammar continuations. This confirms the failure class is open-ended; adding those nouns to a stoplist would only move the next false positive.

### Live signatures that must not change

```text
@dataclass(frozen=True)
class Referent:
    token: str
    kind: str
    raw: str

@dataclass(frozen=True)
class GroundingVerdict:
    results: dict[str, str]
    unresolved: tuple[str, ...]
    cues: dict[str, str]

async def ReferentGroundingGate.evaluate(self, text: str) -> GroundingVerdict
async def ReferentGroundingGate._resolve_one(self, token: str) -> bool
async def GitObjectResolver.resolve(self, token: str) -> bool

async def _observe_referent_grounding(
    runtime: Any,
    thread: Any,
    seed_text: str,
) -> str | None

async def _select_central_referent(verdict: Any, seed_text: str) -> str | None
```

BF-667 appends defaulted dataclass fields but preserves every callable signature above.

---

## Issue-contract resolutions and clarifications

These are live-code clarifications of #1033; they do not weaken its required behavior.

1. **Classify at extraction, not after resolution.** Assertion strength depends on source syntax (`node id`, quotes, machine shape), which is lost if the extractor returns only token/kind/raw. Add the metadata at source; do not add a later noun filter in `thread_fanout.py`.
2. **`results` remains the resolver fact, not the actionability policy.** Preserve its established two values, `RESOLVED` and `UNRESOLVED`. For an all-resolver-false implicit token, set `results[token] = UNRESOLVED` and also append it to the new `ambiguous` tuple, while keeping it out of actionable `unresolved` and `cues`. Do not add a third result string or change resolver return contracts.
3. **The issue’s “registry-first” means resolution-first through the existing authority chain.** Every implicit token is offered to the same constructor-injected resolvers in the same order. Any `True` confirms it. No resolver is skipped, reordered, weakened, or made authoritative by kind.
4. **Backticks remain code, not quotes.** AD-1119 deliberately strips fenced and inline backtick spans before extraction. BF-667 recognizes ASCII single/double-quoted identifiers, but ``node `oracle` ``, `` `node oracle` ``, and fenced examples remain excluded. This preserves the code-span safety contract.
5. **Quoted syntax is a single identifier, not a noun phrase.** Recognize matching ASCII `'` or `"` around one existing 2–64-character token. Do not extract multiword quoted phrases, curly quotes, mismatched/unclosed quotes, or parenthesized prose.
6. **BF-660 grammar still wins over unquoted assertion syntax.** `node id oracle` is strong; `node id is` remains grammar and produces no referent. A quoted grammar-shaped token such as `node "is"` is explicit and may be strong because the quotes are the assertion evidence.
7. **Case is preserved; dedupe remains exact-token.** Locator matching is case-insensitive, token spelling is returned verbatim, and dedupe/promotion keys remain exact strings. Do not casefold identifiers or change resolver casing authority in this BF.
8. **Trailing punctuation remains accepted.** `NODE ORACLE,` is an implicit token `ORACLE`; `node id ORACLE.` and `node "ORACLE"?` are strong. Whitespace inside identifiers remains invalid; existing ASCII token/length bounds remain.
9. **Service extraction is not broadened.** Keep `_SERVICE_RE`’s exact vocabulary and token syntax. Add only a grammar-role rejection for captures that are BF-660 grammar words/determiners, entity locator keywords (`node`, `record`, `entity`), or one of the service regex's own role words (`service`, `membership`, `telemetry`, `cluster`, `node`). Thus `The node ...`, `Node membership ...`, and `Service node ...` cannot manufacture strong service names, while `Oracle membership` and `oracle_service telemetry` remain strong.
10. **Central selection is already single-computation after AD-1121.** BF-667 moves that one computation before the warning loop when either behavior flag is on, then reuses it for warning state, probe scheduling, and cue return. It does not introduce another selector.
11. **The downstream stopword set becomes redundant.** Once only strong unresolved tokens enter `verdict.unresolved`, remove `_GROUNDING_STOPWORDS` and its check. Keep `_GROUNDING_INJECT_KINDS={"hex","entity"}` and the git-availability probe: those are central-policy constraints, not duplicate extraction grammar.
12. **Default-OFF means the integration seam.** The first `referent_gate_enabled=False` early return must remain before gate construction. The local YAML opt-in stays true and therefore receives the intended BF-667 behavior after restart; model defaults stay false.

---

## Pinned design decisions

### DD-1 — Append typed, defaulted metadata; preserve constructor compatibility

In `src/probos/cognitive/referent_gate.py`, import `Literal` and append:

```text
Referent.claim_confidence: Literal["strong", "implicit"] = "strong"
GroundingVerdict.ambiguous: tuple[str, ...] = ()
```

Rules:

- append each field after all current non-default fields (frozen-dataclass ordering);
- default `Referent` to `strong` so every existing/manual constructor preserves pre-BF actionability;
- default `GroundingVerdict.ambiguous` to `()` so existing constructors stay valid;
- keep both dataclasses frozen;
- keep `has_unresolved` defined only by actionable `unresolved`; an ambiguous-only verdict returns `False`;
- do not add a mutable default, a third result label, or a new public method.

### DD-2 — Split entity grammar by assertion syntax; do not encode nouns

Keep `_HEX_RE` unchanged. Replace the monolithic entity scanner with ordered syntax categories equivalent to:

1. **Quoted locator identifier** — `node|record|entity` (and existing `node id`) followed by one matching ASCII single/double-quoted token. Confidence `strong`.
2. **Explicit ID marker** — existing `node id <bare-token>`. Confidence `strong` after BF-660 grammar rejection.
3. **Bare locator token** — `node|record|entity <bare-token>`, with the `node id` marker reserved so an incomplete/stripped explicit form cannot fall back to token `id`.
   - contains a digit, `_`, or `-` → `strong`;
   - alphabetic and not in `_ENTITY_GRAMMAR_STOP_WORDS` → `implicit`;
   - alphabetic grammar stop word → no referent.
4. **Service** — exact existing `_SERVICE_RE`; confidence `strong`, subject only to DD-3’s grammar-role name filter.

Use the existing `[A-Za-z0-9_-]{2,64}` bounds. Keep `node id` as the only explicit unquoted `id` marker promised by the existing grammar; do not silently add `record id`/`entity id` semantics. Reserve marker-shaped fallthrough so no false `id` referent is emitted.

A small private fully typed classifier may return `Literal["strong", "implicit"] | None` from token + syntax evidence. Machine-shape and syntax are evidence; nouns are not. Do not add `identity`, `membership`, `distribution`, `provenance`, `cluster`, `set`, `health`, or any other conceptual noun to a stoplist.

### DD-3 — Reuse grammar categories to suppress impossible service names

Keep `_SERVICE_RE` byte-for-byte unless a mechanically equivalent named-group form is needed. Before appending a service match:

- reject captured names whose casefolded value is already in `_ENTITY_GRAMMAR_STOP_WORDS`; and
- reject the entity locator keywords `node`, `record`, and `entity`; and
- reject a captured name that is itself one of the existing service-role keywords `service`, `membership`, `telemetry`, `cluster`, or `node`.

This is a finite reuse of words already structural in the two regex grammars, not a domain noun blacklist. It removes the known `The node` / `Node membership` overlap and same-role constructions such as `Service node`, while preserving `Oracle membership`, `Atlas telemetry`, and `oracle_service cluster`. Do not add `member`, plural forms, new service keywords, fuzzy matching, or resolver lookup during extraction.

### DD-4 — Deterministic match priority, exact dedupe, promotion, and cap

Represent each extracted candidate internally with source start plus a stable syntax priority. Sort by `(token_start, priority)` so order is deterministic across regex kinds. Preserve the existing preference for a hexadecimal interpretation when a token is independently matched by `_HEX_RE` at the same position.

Dedupe rules:

- key by exact token string, as today;
- first unique occurrence owns list position;
- a later `strong` duplicate replaces the metadata at that existing position (use the later strong `kind/raw/claim_confidence`, while token spelling is the same);
- a later implicit duplicate never downgrades strong evidence;
- once 20 unique positions are admitted, ignore later new tokens but continue scanning later matches for promotion of those admitted tokens;
- return at most `_MAX_REFERENTS`, in first-seen token order.

Required headline: `node oracle ... e77acec7 ... node id oracle` returns `[oracle(strong), e77acec7(strong)]`; `oracle` stays first and its promoted raw evidence is the later explicit form.

### DD-5 — Resolution fact and actionability are separate

In `ReferentGroundingGate.evaluate()`:

1. extract once;
2. call the existing `_resolve_one(token)` once per deduped referent, unchanged;
3. confirmed → `results[token] = RESOLVED`, no unresolved/ambiguous/cue entry;
4. unconfirmed + `claim_confidence == "strong"` → existing behavior: `results[token] = UNRESOLVED`, append to `unresolved`, add the existing `_honest_absence_cue(token)`;
5. unconfirmed + `claim_confidence == "implicit"` → `results[token] = UNRESOLVED`, append to `ambiguous`, add no cue, do not append to `unresolved`;
6. return all four fields in deterministic extraction order.

Do not modify `_resolve_one`, `ReferentResolver`, `build_default_resolvers`, `GitObjectResolver`, `AgentResolver`, `WardRoomResolver`, or `_honest_absence_cue`.

### DD-6 — Actionability flows from the verdict; remove only the duplicate stopword heuristic

In `src/probos/routers/thread_fanout.py`:

- retain `_GROUNDING_INJECT_KINDS={"hex","entity"}`;
- delete `_GROUNDING_STOPWORDS` and remove `t.lower() not in _GROUNDING_STOPWORDS` from `_select_central_referent()`;
- continue re-extracting once inside the existing selector only to recover each unresolved token’s `kind` (no resolver rerun);
- continue selecting from `verdict.unresolved`, which now contains strong claims only;
- preserve the one git-`HEAD` availability probe for hexadecimal candidates;
- preserve service exclusion from central cue/probe selection.

Do not create a shared/public central classifier. The source classifier and verdict are now the single assertion authority; kind eligibility and git availability remain router policy.

### DD-7 — Compute central once before warnings and log the truthful disposition

Restructure `_observe_referent_grounding()` after `gate.evaluate()`:

1. read `probe_on` and `b2_on` once;
2. set `central_token = None`;
3. only when `probe_on or b2_on`, call `_select_central_referent(verdict, seed_text)` exactly once;
4. then log only `verdict.unresolved` (never `verdict.ambiguous`) with the stable `AD-1119[observe]` marker and structured fields equivalent to:
   - token and cue;
   - `central=<token == central_token>`;
   - `ground_before_collaborate=<b2_on>`;
   - `confab_probe=<probe_on>`;
5. remove the literal `(observe-only, no behavioral change)` from every branch;
6. reuse `central_token` for the existing `schedule_confab_probe()` call and AD-1120 cue return.

When both behavior flags are false, do not call central selection; warnings report both flags false and `central=False`. When the gate itself is false, retain the first-line return with no gate, resolver, warning, central selection, or task work.

Do not rename/split the warning marker, add an ambiguous warning, emit a notification for ambiguity, or alter probe scheduling/lifecycle.

### DD-8 — Preserve all downstream safety contracts

- **Windows Git:** no edits to the BF-660 `Popen` worker/cancellation/reaping implementation or tests except imports/expectations directly required by dataclass metadata.
- **AD-1120:** cue text remains byte-for-byte; no new render hook/param; implicit ambiguity returns no cue.
- **AD-1121/BF-663:** no edits to `confab_probe.py`, classifier, nonces, scheduler, shutdown drain, evidence collector, or notification behavior.
- **Capability-gap safety:** every generated strong cue used in new tests must satisfy `is_capability_gap(cue) is False`; ambiguous concepts have no cue to classify.
- **Agent-created rooms:** keep the shared AD-970 seam; test it rather than adding a Captain-only restriction.
- **Default-OFF:** keep the gate’s early return and existing no-build/no-git assertions.

---

## Exact file allowlist

### Production files the Builder may modify

- `src/probos/cognitive/referent_gate.py` — assertion metadata, syntax classification, promotion, ambiguity policy.
- `src/probos/routers/thread_fanout.py` — remove redundant stopword filtering; one central computation; truthful warning fields.

### Existing tests the Builder may modify

- `tests/test_ad1119_referent_gate.py` — extraction, dataclass, resolution, ordering/dedupe/cap, service, cue regression matrix.
- `tests/test_ad1120_ground_before_collaborate.py` — implicit-no-cue and explicit-alpha-cue integration.
- `tests/test_ad1121_confab_probe.py` — all-flags conceptual no-action and enabled-warning disposition.
- `tests/test_ad970_agent_kickoff.py` — agent-created conceptual seed produces no grounding side effect.

### Already present Architect documents; retain unchanged during build

- `prompts/bf-667-referent-assertion-grammar.md`
- `prompts/bf-667-referent-assertion-grammar-execution.md`

### Conditional closeout only, and only if the orchestrator explicitly directs it

- `PROGRESS.md`

No new source or test file is authorized. No other existing source, test, config, standing-order, workflow, UI, tracker, roadmap, decision, archive, dependency, log/data, or issue file is authorized.

---

## Ordered implementation

### Section 1 — Add backward-compatible claim/ambiguity metadata

Modify only the two frozen dataclasses and typing import first. Update their docstrings to define:

- `claim_confidence` as source-syntax assertion strength, not resolver confidence;
- `unresolved` as actionable strong unconfirmed tokens;
- `ambiguous` as implicit unconfirmed tokens with no cue/action;
- `results` as the unchanged resolver result map.

Run the AD-1119 dataclass/default tests before proceeding.

### Section 2 — Implement source grammar and deterministic promotion

Split entity scanning per DD-2, add the small confidence classifier and service grammar-role filter, then update extraction aggregation per DD-4.

Preserve:

- code stripping before every scanner;
- `_HEX_RE` and `_MAX_REFERENTS`;
- exact token casing;
- stable first-seen order;
- exact-token dedupe;
- existing service vocabulary;
- empty/whitespace behavior.

Do not proceed until the conceptual/strong/quote/backtick/BF-660/service/order/cap extraction tests are green.

### Section 3 — Route implicit failures to `ambiguous`

Update only `ReferentGroundingGate.evaluate()` per DD-5. Keep resolver invocation and exception behavior untouched. Update empty/catastrophic verdict constructors explicitly or rely on the new default, but tests must prove backward-compatible construction.

Do not add ambiguous cues or logs.

### Section 4 — Simplify central selection and correct warning disposition

Modify the existing thread-fanout constants/helper only per DD-6/7:

- remove the redundant router stopword set;
- compute the central token once before warnings when a behavior flag is on;
- warn only for strong unresolved tokens;
- include truthful central + flag state;
- reuse the same central token for the existing probe/cue paths.

Do not change task creation, scheduler authority, probe body, notification, or fan-out params.

### Section 5 — Extend existing tests only

Use strict real fixtures/stubs already established in the four suites. Do not introduce MagicMock-created registry/resolver/scheduler APIs, network, live LLM, live runtime data, or arbitrary sleeps.

### Section 6 — Focused gate, then blast gate

Run only the exact serial warning-strict commands below. Do not run the full suite or broad xdist gates in this handoff.

### Section 7 — Scope/whitespace/deletion audit

Inspect every diff against the exact base and allowlist. No tracked deletion, source file outside the two authorized modules, or test file outside the four authorized suites is acceptable.

### Section 8 — Conditional `PROGRESS.md` closeout and commit

Only after Architect review and an explicit orchestrator instruction:

- prepend one concise BF-667 closeout to `PROGRESS.md` with exact focused/blast counts and #1033;
- do not edit `DECISIONS.md`, roadmap, era files, or GitHub;
- retain both BF-667 prompt documents;
- stage only allowlisted paths;
- commit exactly:

`BF-667: distinguish asserted referent identifiers (closes #1033)`

Do not push or mutate GitHub unless separately directed by the orchestrator.

---

## Required tests

### A. `tests/test_ad1119_referent_gate.py`

Add/update behaviorally named cases covering all of the following.

1. **Bare conceptual matrix is implicit** — at minimum:
   - `node identity distribution`;
   - `node membership review`;
   - `Node provenance analysis.`;
   - `node cluster topology`;
   - `node set changes`;
   - `node health status`;
   - `record retention policy`;
   - `entity relationship model`.

   Assert exact token/kind/order and `claim_confidence == "implicit"`. Include `The node membership distribution` or `Node membership distribution` and assert no bogus strong service token (`The`/`Node`) survives. Cover a same-role service phrase such as `Service node status` and assert it does not manufacture a strong `Service` referent.

2. **Strong assertion matrix** — assert `strong` for:
   - standalone and locator-adjacent hex (`e77acec7`);
   - `node id oracle` and `node id oracle_probe`;
   - `node oracle_probe`, `record alpha_1`, `entity alpha-2`, and a digit-bearing token such as `node alpha2`;
   - `node "oracle"`, `node 'oracle'`, and one quoted punctuation/case form;
   - `Oracle membership` and `oracle_service telemetry`.

3. **Bare known-name syntax is recognized but implicit** — `node oracle`, `record alpha`, and `entity atlas` remain extracted, now implicit rather than discarded.

4. **BF-660 composition** — all existing grammar continuation matrix entries remain absent. Add `node id is`, `node id was`, and `node id shows` as no-referent cases. Machine-shaped equivalents remain strong. Do not add conceptual nouns to the stop-set.

5. **Quotes versus code spans** — single/double quoted identifiers are strong; backticked token, whole inline-code phrase, fenced phrase, unmatched quote, and multiword quoted phrase produce no referent. Specifically assert ``node id `oracle_probe` `` produces no false `id` referent.

6. **Case and punctuation** — locator matching is case-insensitive; returned token casing is preserved; trailing punctuation is excluded from the token. Assert exact-token/case-sensitive dedupe behavior rather than silently normalizing resolver keys.

7. **Promotion/order/cap** — later strong duplicate promotes an earlier implicit token in place; later implicit never downgrades strong; first-seen unique order remains; first 20 unique tokens remain capped while a later strong occurrence can still promote an already-admitted token.

8. **Unconfirmed implicit becomes ambiguous** — with a strict all-false/empty resolver chain, `node identity distribution` yields:
   - `results["identity"] == UNRESOLVED`;
   - `ambiguous == ("identity",)`;
   - `unresolved == ()`;
   - `cues == {}`;
   - `has_unresolved is False`.

9. **Known implicit resolves through existing authority** — use a real `AgentRegistry` and real `_RealAgent` pool/id or a strict resolver. `node oracle` must be `RESOLVED`, with neither ambiguous nor unresolved/cue entries. Prove all-false follows the ambiguity path without changing resolver order.

10. **Strong unknown remains actionable** — explicit alphabetic `node id oracle`, quoted `node "oracle"`, machine-shaped token, and fabricated `e77acec7` remain in `unresolved` with cues and absent from `ambiguous`. Assert every cue is capability-gap-clean.

11. **Service authority regression** — a genuine existing service/pool extracted through unchanged service grammar resolves; an unknown genuine service form remains strong/actionable; conceptual `Node membership` does not manufacture service `Node`.

12. **Dataclass compatibility/frozen behavior** — old three-argument `Referent(...)` defaults strong; old three-argument `GroundingVerdict(...)` defaults `ambiguous=()`; both remain frozen.

Do not weaken or delete the 24 existing AD-1119 tests, especially Windows selector-loop, argv, timeout/cancellation reap, real Git, and default-OFF cases.

### B. `tests/test_ad1120_ground_before_collaborate.py`

13. **Implicit conceptual noun produces no cue** — G1+B2 on, strict empty resolvers, `node identity distribution` (and preferably one service-collision conceptual form) → `None`; no `grounding_cue` can be rendered.
14. **Explicit unknown alphabetic still emits a cue** — `node id oracle` and/or `node "oracle"` → non-empty exact AD-1119 cue, token present, `is_capability_gap(cue) is False`.
15. Keep the existing hex, git-unavailable, resolved, default-OFF, G1-only, hook, standing-order, and config cases green.

### C. `tests/test_ad1121_confab_probe.py`

16. **All flags on, conceptual phrase has zero action** — with real `SystemConfig`, strict empty resolvers, real `NotificationQueue`, real temporary `EvidenceCollector`, and scripted LLM:
   - seed `node identity distribution`;
   - observe returns `None`;
   - no AD-1119 unresolved WARNING;
   - zero probe tasks and zero LLM requests;
   - no cue, evidence file, or notification.

   This is the headline fail-before/pass-after integration test.

17. **Enabled strong warning reports truth** — for fabricated `e77acec7` with B2+probe enabled, make git availability deterministic, prevent/await any probe side effect, and assert the single AD-1119 warning contains the token plus `central=True`, `ground_before_collaborate=True`, and `confab_probe=True`; assert it does not contain `no behavioral change`.
18. Keep BF-663’s unique nonce, strict YES/NO/UNKNOWN, cancellation, scheduler, default-OFF, evidence, and non-blocking tests green unchanged in behavior.

### D. `tests/test_ad970_agent_kickoff.py`

19. **Agent-created conceptual kickoff has no grounding side effects** — enable all three flags on the existing real `ChatThreadStore`/`IntentBus` fixture, use an opening containing `node identity distribution`, and assert:
   - the other participant is still dispatched and the opener remains excluded;
   - no dispatched `IntentMessage.params["grounding_cue"]` exists;
   - a strict scheduler spy records zero probe scheduling calls;
   - no AD-1119 unresolved warning is emitted.

Keep the Captain and gate-off kickoff behavior unchanged. Do not solve this by restricting grounding to Captain-origin turns.

---

## Exact test gates

Run from `D:\ProbOS`. Each command uses a unique temporary data directory, local embeddings, offline model flags, serial execution, no pytest cache, a 90-second per-test timeout, short tracebacks, and `RuntimeWarning` promoted to error.

### Focused

```powershell
$gateDir = Join-Path $env:TEMP ("probos_bf667_focused_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad1119_referent_gate.py tests/test_ad1120_ground_before_collaborate.py tests/test_ad1121_confab_probe.py tests/test_ad970_agent_kickoff.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

### Blast radius

```powershell
$gateDir = Join-Path $env:TEMP ("probos_bf667_blast_" + [guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Force -Path $gateDir | Out-Null; $env:PROBOS_DATA_DIR = $gateDir; $env:PROBOS_EMBEDDINGS = 'local'; $env:HF_HUB_OFFLINE = '1'; $env:TRANSFORMERS_OFFLINE = '1'; try { & 'D:\ProbOS\.venv\Scripts\pytest.exe' tests/test_ad914_group_chat_fanout.py tests/test_ad915_turn_taking_facilitator.py tests/test_ad935_group_reactivity.py tests/test_ad454_evidence_collector.py tests/test_bf663_confab_probe_shutdown.py tests/test_config.py tests/test_ad1119_referent_gate.py tests/test_ad1120_ground_before_collaborate.py tests/test_ad1121_confab_probe.py tests/test_ad970_agent_kickoff.py -p no:cacheprovider -n 0 --timeout=90 -q --tb=short -W error::RuntimeWarning } finally { Remove-Item Env:PROBOS_DATA_DIR, Env:PROBOS_EMBEDDINGS, Env:HF_HUB_OFFLINE, Env:TRANSFORMERS_OFFLINE -ErrorAction SilentlyContinue; Remove-Item -LiteralPath $gateDir -Recurse -Force -ErrorAction SilentlyContinue }
```

Do not run full `tests/`, xdist, `-n auto`, network tests, a live LLM, or live-runtime data tests for BF-667.

---

## Acceptance criteria

1. `node identity distribution` extracts `identity` as implicit; all-resolver-false yields `ambiguous=("identity",)`, no actionable unresolved token, no cue, warning, central selection, task, evidence, or notification.
2. The conceptual noun matrix behaves by syntax, not by noun membership; no conceptual noun blacklist is introduced.
3. `node oracle` resolves when `oracle` genuinely exists; unknown bare alphabetic names remain ambiguous.
4. Hex, digit/underscore/hyphen, explicit `node id`, matching single/double quotes, and genuine service forms are strong and preserve current authority/actionability.
5. Backticked/fenced code remains excluded; ``node id `oracle_probe` `` cannot fall back to `id`.
6. BF-660 grammar continuations remain excluded, including after the explicit `node id` marker.
7. Duplicate promotion preserves first-seen order, exact-token casing, deterministic kind/raw evidence, and the 20-referent cap.
8. `GroundingVerdict.results` remains `RESOLVED|UNRESOLVED`; `ambiguous` is the non-actionability lane; old dataclass construction remains valid and frozen.
9. `_GROUNDING_STOPWORDS` is removed; `_GROUNDING_INJECT_KINDS`, git availability, resolver order, cue text, and service resolver authority remain.
10. Central selection is computed zero times when both behavior flags are off and at most once when either is on; the same result drives warning state, cue, and probe.
11. Strong unresolved warnings report central/B2/probe state and contain no false `no behavioral change` text.
12. Default-OFF first-line early return builds no gate/runs no Git; local YAML flags are not edited.
13. Captain and AD-970 agent-created seeds share the corrected deterministic gate; no origin restriction is added.
14. All new strong cues satisfy `is_capability_gap(text) is False`; ambiguous tokens produce no cue.
15. Focused and blast commands pass serially with isolated data/local embeddings and `RuntimeWarning` as error; report exact counts/skips.
16. No source/test/config/tracker change exists outside the exact allowlist; conditional closeout edits only `PROGRESS.md`.
17. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Do NOT build

- No noun stoplist expansion (`identity`, `membership`, `distribution`, `provenance`, `cluster`, `set`, `health`, etc.).
- No NER, POS tagger, parser dependency, embedding similarity, LLM extraction, or probabilistic classifier.
- No new config flag and no edits to `src/probos/config.py` or `config/system.yaml`; do not disable the Captain’s local opt-in.
- No Captain-only or user-origin-only restriction; agent-created AD-970 seeds keep using the same gate.
- No new resolver, resolver reordering, resolver kind special-casing, fuzzy lookup, or changes to Git/agent/callsign/ward-room authority.
- No edit to BF-660’s Windows-safe `GitObjectResolver`, child cleanup, timeout, cancellation, argv, or logging.
- No service vocabulary expansion (`member`, plurals, synonyms) and no service resolver change.
- No cue wording/render-hook/standing-order change and no capability-gap regex change.
- No probe classifier/sample/nonce/tier/threshold/task lifecycle/evidence/notification change.
- No trust, consensus, Hebbian, episodic, thread close/archive/delete, or self-modification change.
- No broad fan-out refactor, second grounding seam, new task, new event, new intent, or sealed protocol change.
- No casefold normalization of returned/deduped identifiers.
- No UI, dependency, schema, storage, migration, or commercial content.
- No new AD, no `DECISIONS.md`, roadmap, era-file, or GitHub edit.

---

## Hard stops

Stop and return to the Architect if any of the following occurs:

1. HEAD differs from `5d3c1b5f682bcea8762ffac6f98e2d9abe19eca2`, BF-666 CI is reported failed, or the initial tree contains anything beyond the two BF-667 prompt documents.
2. A required behavior needs a file outside the allowlist.
3. The implementation needs a third `results` status, resolver protocol/signature change, resolver reordering, or Git resolver change.
4. Single/double quoted identifiers cannot be added without extracting backticked/fenced code.
5. Conceptual precision appears to require adding nouns rather than encoding assertion syntax.
6. Service preservation appears to require broadening `_SERVICE_RE` or changing service resolver authority.
7. More than one central-token computation or a second gate/resolver pass is needed.
8. Default-OFF starts gate/Git/task work, or local flags/config would need editing.
9. A cue fails `is_capability_gap(cue) is False` and fixing it would change AD-1119 wording or the capability-gap regex.
10. Probe/evidence/notification side effects occur for an ambiguous-only seed after the scoped changes.
11. Any existing Windows Git, BF-663 lifecycle, AD-1120 cue, or AD-970 kickoff contract regresses.
12. Tests require live runtime data, network, live LLM, arbitrary sleeps, or broad xdist/full-suite execution.
13. Any deletion, unrelated reformat, private-API reach-through, or scope drift appears.

---

## Tracking and conditional commit

- **During build:** do not edit any tracker.
- **After green gates + Architect approval, only if explicitly directed:** update `PROGRESS.md` only with a concise BF-667 closeout and exact counts.
- **Never edit:** `DECISIONS.md`, roadmap, era files, issue metadata, or GitHub.
- **Authorized commit message:** `BF-667: distinguish asserted referent identifiers (closes #1033)`
- Do not stage, commit, push, close/comment on #1033, or mutate GitHub unless the orchestrator explicitly directs that operation.

---

## Verified Against Codebase (2026-07-14, exact HEAD `5d3c1b5f682bcea8762ffac6f98e2d9abe19eca2`)

```text
# Extraction + data contracts
src/probos/cognitive/referent_gate.py:48   _HEX_RE unchanged
src/probos/cognitive/referent_gate.py:50   _ENTITY_RE currently conflates every located token
src/probos/cognitive/referent_gate.py:54   _ENTITY_GRAMMAR_STOP_WORDS (BF-660)
src/probos/cognitive/referent_gate.py:97   _SERVICE_RE exact existing service grammar
src/probos/cognitive/referent_gate.py:104  fenced-code stripper
src/probos/cognitive/referent_gate.py:105  inline-backtick-code stripper
src/probos/cognitive/referent_gate.py:109  frozen Referent(token, kind, raw)
src/probos/cognitive/referent_gate.py:122  frozen GroundingVerdict(results, unresolved, cues)
src/probos/cognitive/referent_gate.py:147  _is_entity_identifier Boolean policy
src/probos/cognitive/referent_gate.py:159  extract_referents(text) -> list[Referent]
src/probos/cognitive/referent_gate.py:186  first-seen append + cap
src/probos/cognitive/referent_gate.py:405  ReferentGroundingGate
src/probos/cognitive/referent_gate.py:419  evaluate(text) -> GroundingVerdict
src/probos/cognitive/referent_gate.py:432  results/unresolved/cues accumulation

# Resolver authority (reference only; no changes)
src/probos/cognitive/referent_gate.py:214  GitObjectResolver (BF-660 Windows-safe Popen worker)
src/probos/cognitive/referent_gate.py:337  AgentResolver
src/probos/cognitive/referent_gate.py:379  WardRoomResolver
src/probos/cognitive/referent_gate.py:450  build_default_resolvers
src/probos/substrate/registry.py:58       AgentRegistry.get
src/probos/substrate/registry.py:61       AgentRegistry.get_by_pool
src/probos/crew_profile.py:711            CallsignRegistry.resolve (case-insensitive callsign key)
src/probos/ward_room/service.py:267       async get_channel_by_name

# Fan-out/cue/probe seam
src/probos/routers/thread_fanout.py:89    _GROUNDING_INJECT_KINDS={hex,entity}
src/probos/routers/thread_fanout.py:92    duplicate _GROUNDING_STOPWORDS
src/probos/routers/thread_fanout.py:966   _observe_referent_grounding
src/probos/routers/thread_fanout.py:997   first-line referent_gate_enabled early return
src/probos/routers/thread_fanout.py:1014  warning loop over verdict.unresolved
src/probos/routers/thread_fanout.py:1018  false '(observe-only, no behavioral change)' literal
src/probos/routers/thread_fanout.py:1026  probe_on read
src/probos/routers/thread_fanout.py:1027  b2_on read
src/probos/routers/thread_fanout.py:1033  current single central-token computation
src/probos/routers/thread_fanout.py:1040  stable public runtime.schedule_confab_probe call
src/probos/routers/thread_fanout.py:1066  _select_central_referent
src/probos/routers/thread_fanout.py:1082  pure re-extraction for token kinds
src/probos/routers/thread_fanout.py:1120  _probe_cascade_confab (reference only)
src/probos/routers/thread_fanout.py:1206  group_chat_fanout
src/probos/routers/thread_fanout.py:1247  one grounding call before dispatch
src/probos/runtime.py:2632               stable public schedule_confab_probe
src/probos/routers/threads.py:429         Captain group-turn caller
src/probos/proactive.py:4264              AD-970 agent-created kickoff caller

# Flags + capability-gap safety
src/probos/config.py:6035                GroundingConfig
src/probos/config.py:6055                referent_gate_enabled default False
src/probos/config.py:6059                ground_before_collaborate_enabled default False
src/probos/config.py:6068                confab_probe_enabled default False
config/system.yaml:1996                  local referent_gate_enabled true
config/system.yaml:1997                  local ground_before_collaborate_enabled true
config/system.yaml:1998                  local confab_probe_enabled true
src/probos/cognitive/decomposer.py:30     _CAPABILITY_GAP_RE
src/probos/cognitive/decomposer.py:43     is_capability_gap(response)

# All direct extraction/verdict constructors and callers
extract_referents production callers: referent_gate.py:422; thread_fanout.py:1082
Referent production constructor: referent_gate.py:186
GroundingVerdict production constructors: referent_gate.py:429,443
Manual compatibility constructors: tests/test_ad1119_referent_gate.py:584-585
_observe_referent_grounding production caller: thread_fanout.py:1247
_select_central_referent production caller: thread_fanout.py:1033

# Existing test surfaces (definition counts, no tests run during drafting)
tests/test_ad1119_referent_gate.py       24 tests
tests/test_ad1120_ground_before_collaborate.py 11 tests
tests/test_ad1121_confab_probe.py        20 tests
tests/test_ad970_agent_kickoff.py        5 tests
```

## Architect three-pass self-review

### Pass 1 — Spec completeness

**Verdict:** approved. Every build item maps to named behavioral tests and acceptance criteria; recognized/unsupported syntax, ambiguity semantics, promotion/cap, warning disposition, default-OFF, closeout, and hard stops are explicit.

### Pass 2 — Verify-first

**Verdict:** approved. Paths, signatures, flags, all production callers, manual dataclass constructors, current extraction outputs, live false-positive evidence, test counts, resolver methods, scheduler seam, and capability-gap regex were verified against the exact base.

### Pass 3 — Scope, safety, and license

**Verdict:** approved. Exactly two production files and four existing tests are authorized; `PROGRESS.md` is conditional closeout only. No AD/decision/UI/config/dependency/GitHub work, no noun blacklist, no resolver/probe authority change, and no external license input. License disposition: none.
