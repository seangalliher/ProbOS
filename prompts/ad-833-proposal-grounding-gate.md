# AD-833 — Improvement-proposal grounding gate (DESIGN + phased build prompt)

**Status:** Design complete — build prompt ready for a future wave (NOT this wave)
**Kind:** design → bf (phased)
**Current highest AD at design time:** AD-837a (AD-833 is the pre-reserved number for this work)
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
    verified: bool | None        # True=grounded, False=contradicted, None=undetermined
    score: float                 # 0.0–1.0 contribution
    evidence: list[str]          # human-readable, surfaced in the UI

@dataclass(frozen=True)
class ProposalGroundingResult:
    score: float                 # aggregate 0.0–1.0
    verified: bool               # score >= threshold AND no provider returned False
    findings: list[GroundingFinding]
    confidence: float
```

### Provider interface (typing.Protocol)

```python
class GroundingProvider(Protocol):
    name: str
    async def check(self, proposal: CapabilityProposal) -> GroundingFinding: ...
```

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
  runs providers, aggregates (mean of contributing scores; `verified` = aggregate ≥ threshold AND
  no provider returned `verified is False`; `confidence` = fraction of providers that returned
  non-None), log-and-degrade per provider.

**`ProposalStore`** ([`proposal.py`](../src/probos/cognitive/self_improvement/proposal.py)):
- Add `_grounding: dict[str, ProposalGroundingResult]` and a public
  `attach_grounding(proposal_id: str, result: ProposalGroundingResult) -> None` +
  `get_grounding(proposal_id: str) -> ProposalGroundingResult | None`. `submit` stays sync and
  signature-unchanged.

**`ApprovalGate.list_pending`** ([`approval_gate.py`](../src/probos/cognitive/self_improvement/approval_gate.py)):
- Return proposals paired with their grounding (e.g. `list[tuple[CapabilityProposal,
  ProposalGroundingResult | None]]`, OR a small view dataclass) so the surfacing path carries the
  score. Update the Ward Room resolver/UI to render a grounding badge (separate UI sub-AD if it
  touches `ui/` — keep this AD backend-only and emit the data; do NOT change `ui/` here).

**Wiring** ([`finalize.py`](../src/probos/startup/finalize.py) near the existing
`ProposalStore` / `ApprovalGate` construction): build a `ProposalGroundingVerifier` with the
`SymbolExistenceProvider` over the runtime's `CodebaseIndex`, expose it as
`runtime.proposal_grounding_verifier`. Do NOT auto-run it inside `submit`; the authoring path
calls `verify(...)` then `proposal_store.attach_grounding(...)`.

## 4. Tests (phase 1)

`tests/test_ad833_grounding_gate.py`:
- `SymbolExistenceProvider`: proposal naming a real symbol (e.g. `vision_observation` /
  `CapabilityProposal`) → `verified=True`, score high; proposal naming a phantom
  (`FooBarNonexistentAgent`) → `verified=False`, evidence lists the unresolved token; prose-only
  proposal → `verified=None`. Use a real or lightweight stub `CodebaseIndex` (prefer real over
  MagicMock at this boundary — the Phantom-via-MagicMock memory lesson).
- `ProposalGroundingVerifier.verify`: aggregation happy path; a provider that raises is logged and
  skipped (degrade), not fatal; `confidence` reflects None returns.
- `ProposalStore.attach_grounding` / `get_grounding` round-trip; `submit` signature unchanged.
- `ApprovalGate.list_pending` surfaces grounding (None when not attached).

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
   provider plugins behind a `Protocol`, log-and-degrade per provider.
2. `ProposalStore` carries grounding via parallel store (model unchanged, `submit` sync + unchanged).
3. `ApprovalGate.list_pending` surfaces the grounding result.
4. `runtime.proposal_grounding_verifier` wired in finalize; gate is advisory (never blocks submit).
5. `tests/test_ad833_grounding_gate.py` passes.
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
