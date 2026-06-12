# AD-833 — Improvement-proposal grounding gate (DESIGN + phased build prompt)

**Status:** Ready — Architect-reviewed (revisions applied); build prompt for the current wave (v1)
**Kind:** design → bf (phased)
**Current highest shipped:** AD-839 (Wave 203). AD-833 is the pre-reserved number — this prompt consumes it for the v1 build. Sub-letters AD-833a / AD-833b stay deferred.
**Motivating evidence:** 2026-05-31 Ward Room "Improvement Proposals" validation — **0 of 18**
agent-authored proposals were verifiable bugs. AD-832 fixed ONE misread telemetry event; this
designs the *general* gate.
**Analogous prior pattern:** AD-734 capability-claim verification
([`observable_state.py`](../src/probos/cognitive/observable_state.py), `ObservableStateVerifier.verify_claims`).
**Target repo:** OSS (`d:\ProbOS`)

---

## 1. Problem (failure-mode taxonomy)

Agent-authored improvement proposals fail validation through a **confabulation cascade** —
the agent forms a fault hypothesis and files a proposal without verifying it against the
codebase or trackers. The 18-proposal sample showed five recurring classes:

1. **Phantom symbol** — names an event / intent / duty / file / class / method that does not exist.
2. **Already-shipped** — re-files work that is already CLOSED in DECISIONS.md / roadmap.md.
3. **Benign-telemetry-as-fault** — cites a telemetry event that is explicitly marked
   `data["benign"]=True` / `data["expected"]=True` (the exact AD-832 case) and reads it as a bug.
4. **Conflated subsystem** — references a similarly-named-but-different module/agent.
5. **Confabulated calculation** — treats LLM-generated prose ("this adds ~30ms latency") as a
   measured fact.

Today nothing verifies a proposal before it surfaces for crew/Captain review
([`ProposalStore.submit`](../src/probos/cognitive/self_improvement/proposal.py) just timestamps,
stores, and emits `CAPABILITY_PROPOSAL_CREATED`). The Captain pays the verification cost manually,
18 times, with a ~0% yield.

## 2. Design — a provider-based grounding verifier (mirror AD-734)

Introduce a **`ProposalGroundingVerifier`** that mirrors `ObservableStateVerifier`'s shape:
constructor-injected list of narrow `GroundingProvider` plugins (Interface Segregation), each
independently inspects a proposal and returns structured evidence with a partial score and a
`verified: bool | None` (None = "provider can't determine"). Results aggregate into one
`ProposalGroundingResult` attached to the proposal. Log-and-degrade per provider — a provider
exception is caught, logged at WARNING, and skipped (it never blocks submission; a low/None score
is information, not a veto).

```python
@dataclass(frozen=True)
class GroundingFinding:
    provider_name: str
    verified: bool | None        # True=grounded, False=contradicted, None=undetermined/abstain
    score: float                 # 0.0–1.0 contribution
    evidence: list[str]          # human-readable, surfaced in the UI

@dataclass(frozen=True)
class ProposalGroundingResult:
    score: float                 # aggregate 0.0–1.0 (mean of finding scores; 1.0 when empty)
    verified: bool               # see aggregation rule in §3 (threshold + no-False)
    findings: list[GroundingFinding]
    confidence: float            # fraction of findings whose verified is not None
```

### Provider interface (typing.Protocol)

```python
class GroundingProvider(Protocol):
    name: str
    async def check(self, proposal: CapabilityProposal) -> GroundingFinding: ...
```

> A provider **abstains** by returning `GroundingFinding(verified=None, score=0.0, evidence=[...])`
> — NOT by returning `None`. This is an intentional divergence from the AD-583f template
> (`check(...) -> VerificationResult | None`): with a single provider in v1, always returning a
> finding keeps the aggregation math simple and makes `confidence` meaningful (it counts findings
> that actually made a determination).

### Three providers — phased, because only one has a clean existing API

| Provider | Checks failure class | Reuses | Phase |
|----------|---------------------|--------|-------|
| `SymbolExistenceProvider` | 1 (phantom), 4 (conflated) | `CodebaseIndex.query` / `find_callers` / `get_full_api_surface` — **all exist today** | **AD-833 (v1)** |
| `TrackerCrossRefProvider` | 2 (already-shipped) | needs a new `CodebaseIndex` method to scan DECISIONS.md / roadmap.md for CLOSED/SHIPPED entries — **no API today** | **AD-833a** |
| `BenignTelemetryProvider` | 3 (benign-as-fault) | needs an event-log query by `event` name returning recent `data` dicts to read the `benign` marker — **no query API today** | **AD-833b** |

This phasing follows the standing lesson "ship the part with a clean seam first, defer the
entangled consumers." v1 (AD-833) ships the verifier scaffold + the one provider whose
dependencies already exist. AD-833a/b add the other two once their query capabilities land.

### Why NOT inside `ProposalStore.submit`

`ProposalStore.submit(proposal) -> str` is **synchronous**; `verify_claims` (the AD-734 analog)
is **async**, and the CodebaseIndex calls are I/O-ish. Making `submit` async ripples to every
caller (anti-pattern: 6+ call-site migrations = defer). Instead:

- The verifier runs at the **async proposal-authoring boundary** — wherever the agent constructs
  the `CapabilityProposal` and is already in an async context — and attaches the
  `ProposalGroundingResult` to the proposal **before** calling `submit`.
- `ProposalStore` gains an optional `grounding: ProposalGroundingResult | None` association
  (a parallel `_grounding: dict[str, ProposalGroundingResult]` keyed by proposal id, NOT a new
  field on the frozen `CapabilityProposal` dataclass — keeps the model immutable and the store
  the single owner of derived state). `submit` stays sync and signature-stable.
- `ApprovalGate.list_pending()` is extended to surface the grounding result alongside each
  proposal so the Ward Room "Improvement Proposals" UI can render a grounding badge / score and
  sort/deprioritize low-grounding proposals.

### `SymbolExistenceProvider` (the v1 substance)

1. Extract candidate symbol tokens from `proposal.summary` + `proposal.fit_assessment` — match
   identifier-shaped tokens (CamelCase, snake_case, dotted intents like `vision_observation`,
   event names like `CAPABILITY_PROPOSAL_CREATED`). Use a conservative regex; over-extraction is
   fine because un-resolvable common English words simply lower the score slightly — so weight by
   token "symbol-likeness" (has `_`, `.`, or interior capital) to avoid penalising prose.
2. For each weighted candidate, resolve via `CodebaseIndex`: a hit in `query(token)["matching_*"]`,
   a non-empty `find_callers(token)`, or presence in `get_full_api_surface()` counts as resolved.
3. `score` = weighted fraction of symbol-like tokens that resolve. `verified=True` if every
   symbol-like token resolves; `False` if a high-weight token resolves to nothing (likely phantom);
   `None` if there were no symbol-like tokens to check (prose-only proposal — can't ground it this
   way). `evidence` lists each token + resolved/unresolved + where it resolved.

## 3. Phase-1 build scope (AD-833)

**New file** `src/probos/cognitive/self_improvement/grounding.py`:
- `GroundingFinding`, `ProposalGroundingResult` dataclasses (frozen, fully typed).
- `GroundingProvider` Protocol.
- `SymbolExistenceProvider` (constructor takes a `CodebaseIndex`; `name="symbol_existence"`).
- `ProposalGroundingVerifier(providers: list[GroundingProvider])` with
  `async def verify(self, proposal: CapabilityProposal) -> ProposalGroundingResult` —
  runs providers with a per-provider `try/except Exception` (log at `debug`/`warning` with
  `exc_info=True`, skip the provider — exact mirror of
  [`observable_state.py:75-78`](../src/probos/cognitive/observable_state.py#L75)), then aggregates:
  - `score` = mean of finding `score` values (empty findings → `1.0`).
  - `verified` = `aggregate_score >= _GROUNDING_VERIFIED_THRESHOLD` **AND** no finding has
    `verified is False`. Define a module constant `_GROUNDING_VERIFIED_THRESHOLD: float = 0.5`
    (single source of truth — do not inline the literal).
  - `confidence` = fraction of findings whose `verified is not None` (i.e. providers that made a
    determination; `0.0` when there are no findings).

**`ProposalStore`** ([`proposal.py`](../src/probos/cognitive/self_improvement/proposal.py)):
- Add `_grounding: dict[str, ProposalGroundingResult]` (init in `__init__`, which ends at
  [`proposal.py:127`](../src/probos/cognitive/self_improvement/proposal.py#L127)) and a public
  `attach_grounding(proposal_id: str, result: ProposalGroundingResult) -> None` (insert after
  `list_pending`, ~L165; unknown id → `logger.warning(...)` + return, never raise) +
  `get_grounding(proposal_id: str) -> ProposalGroundingResult | None`. `submit` stays sync and
  signature-unchanged. Use a `TYPE_CHECKING` import of `ProposalGroundingResult` from `.grounding`
  (annotation only) to avoid a runtime import cycle (`grounding.py` imports `CapabilityProposal`
  from `proposal.py`).

**`ApprovalGate`** ([`approval_gate.py:30`](../src/probos/cognitive/self_improvement/approval_gate.py#L30)):
- Do **NOT** change `list_pending` — it has zero external callers but must stay
  `list[CapabilityProposal]` to mirror `ProposalStore.list_pending`. Add an additive sibling:
  ```python
  def list_pending_grounded(self) -> list[tuple[CapabilityProposal, ProposalGroundingResult | None]]:
      return [(p, self._proposals.get_grounding(p.id)) for p in self._proposals.list_pending()]
  ```
- Add an optional constructor param `grounding_verifier: ProposalGroundingVerifier | None = None`
  (default `None` → behavior byte-identical to today; store as `self._grounding_verifier`) and an
  **async authoring seam** — the concrete home for verify→submit→attach:
  ```python
  async def enqueue_grounded(self, proposal: CapabilityProposal) -> str:
      pid = self._proposals.submit(proposal)
      if self._grounding_verifier is not None:
          try:
              result = await self._grounding_verifier.verify(proposal)
              self._proposals.attach_grounding(pid, result)
          except Exception:
              logger.warning("AD-833: grounding verify failed for %s; submit stands", pid, exc_info=True)
      return pid
  ```
  Grounding stays advisory — a verifier fault degrades to a plain submit, never blocks authoring.
  Use a `TYPE_CHECKING` import of `ProposalGroundingVerifier` from `.grounding`.

**Wiring** ([`finalize.py`](../src/probos/startup/finalize.py) near the existing
`ProposalStore` / `ApprovalGate` construction at
[`finalize.py:1509-1517`](../src/probos/startup/finalize.py#L1509)): build a
`ProposalGroundingVerifier` with a `SymbolExistenceProvider` over `getattr(runtime,
"codebase_index", None)` (set at [`runtime.py:1759`](../src/probos/runtime.py#L1759) during the
fleet phase, which runs before finalize). If the index is absent (config-disabled / degraded
boot), build `ProposalGroundingVerifier(providers=[])` and log-and-degrade — never crash finalize.
**Pass the verifier into `ApprovalGate(grounding_verifier=...)`** (the authoring seam) **and**
expose it as `runtime.proposal_grounding_verifier` for introspection/UI. Declare the attribute
per convention in `runtime.py` next to `approval_gate`: add `proposal_grounding_verifier: Any |
None  # AD-833` to the annotation block (~[`runtime.py:280`](../src/probos/runtime.py#L280)) and
`self.proposal_grounding_verifier: Any | None = None` (~[`runtime.py:825`](../src/probos/runtime.py#L825)).
Do NOT auto-run the verifier inside `submit`; only `enqueue_grounded` runs it.

## 4. Tests (phase 1)

`tests/test_ad833_grounding_gate.py`:
- `SymbolExistenceProvider`: proposal naming a real symbol (e.g. `vision_observation` /
  `CapabilityProposal`) → `verified=True`, score high; proposal naming a phantom
  (`FooBarNonexistentAgent`) → `verified=False`, evidence lists the unresolved token; prose-only
  proposal → `verified=None`. Use a real or lightweight stub `CodebaseIndex` (prefer real over
  MagicMock at this boundary — the Phantom-via-MagicMock memory lesson).
- `ProposalGroundingVerifier.verify`: aggregation happy path; a provider that raises is logged and
  skipped (degrade), not fatal; `confidence` reflects findings whose `verified is not None`.
- `ProposalStore.attach_grounding` / `get_grounding` round-trip; unknown-id `attach_grounding` is a
  no-op warning (no raise); `get_grounding` on unknown id returns `None`; `submit` signature unchanged.
- `ApprovalGate.list_pending_grounded` surfaces grounding (None when not attached) and
  `ApprovalGate.list_pending` remains `list[CapabilityProposal]` (unchanged).
- `ApprovalGate.enqueue_grounded`: with a wired verifier, submits AND attaches a retrievable
  grounding result; with `grounding_verifier=None`, submits normally and `get_grounding` is `None`;
  with a verifier whose `verify` raises, the proposal is still submitted (id returned), grounding absent.

Run serial: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad833_grounding_gate.py -v -n 0`.

## 5. Explicitly NOT in scope (this AD)

- `TrackerCrossRefProvider` (AD-833a) and `BenignTelemetryProvider` (AD-833b) — they need new
  CodebaseIndex / event-log query APIs; design them as separate ADs once those queries exist.
- Any `ui/` change (grounding badge rendering) — separate UI sub-AD (BF-279 dual gate applies there).
- Auto-running the gate inside `submit` or making `submit` async.
- An auto-reject / veto policy — v1 is **advisory** (score + evidence). Gating policy is a later AD.
- Changing the `CapabilityProposal` frozen dataclass shape.

## 6. Acceptance criteria

1. `ProposalGroundingVerifier` + `SymbolExistenceProvider` + result dataclasses exist, fully typed,
   provider plugins behind a `Protocol`, log-and-degrade per provider; `verified` uses the
   `_GROUNDING_VERIFIED_THRESHOLD = 0.5` rule and `confidence` counts determinations.
2. `ProposalStore` carries grounding via parallel store (model unchanged, `submit` sync + unchanged).
3. `ApprovalGate.list_pending` is unchanged; a new `list_pending_grounded` surfaces the grounding
   result, and async `enqueue_grounded` runs verify→submit→attach (advisory; degrades to plain
   submit on verifier fault or when no verifier is wired).
4. The verifier is constructed from `runtime.codebase_index` in finalize, injected into
   `ApprovalGate`, and also exposed as `runtime.proposal_grounding_verifier`; absent index → empty
   provider list, never crashes finalize. The gate is advisory (never blocks submit).
5. `tests/test_ad833_grounding_gate.py` passes; the full gate (`pytest tests/ -q -n 0`) shows no regressions.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 7. Verified against codebase (2026-05-31)

```
self_improvement/proposal.py:48-65    CapabilityProposal frozen dataclass (fields)
self_improvement/proposal.py:132-154  ProposalStore.submit(proposal)->str  [SYNC]
self_improvement/approval_gate.py:51  list_pending()->list[CapabilityProposal]
cognitive/codebase_index.py:158       query(concept)->dict (matching_files/agents/methods/layer)
cognitive/codebase_index.py:339       find_callers(method_name,max_results)->list[dict]
cognitive/codebase_index.py:390       get_full_api_surface()->dict[class,list[sig]]
cognitive/observable_state.py:63-80   ObservableStateVerifier.verify_claims (AD-734 template)
ward_room_pipeline.py:361-381         data["benign"]=True / data["expected"]=True marker (AD-832)
startup/finalize.py:1509,1563         ProposalStore / ApprovalGate construction (wiring seam)
```

> NOTE: There is **no** programmatic "already-shipped" tracker check and **no** event-log
> query-by-event-name API in the codebase today (confirmed). That is why TrackerCrossRef and
> BenignTelemetry are deferred to AD-833a / AD-833b rather than attempted in v1.
