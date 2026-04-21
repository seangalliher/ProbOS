# Standing Order Decomposition for Cognitive Chains

**Date:** 2026-04-20  
**Author:** Sean Galliher (Architect)  
**Related:** AD-647 (Process Chains), AD-632 (Cognitive Chain), AD-646 (Universal Baseline), AD-641g (NATS Pipeline), BF-213 (Analyze Silence Bias)

---

## Observation

BF-213 revealed that the cognitive chain's proactive path produces zero improvement proposals despite standing orders containing a complete Ward Room Action Vocabulary with decision tree ("When to act vs. observe"). Investigation traced the failure to the ANALYZE step's framing ("Silence is professionalism") overriding the action vocabulary in standing orders.

This exposed a deeper architectural question: **standing orders were designed for a one-shot world where a single LLM call played every cognitive role simultaneously.** The chain decomposes cognition into discrete steps (QUERY → ANALYZE → COMPOSE → EVALUATE → REFLECT), but standing orders are injected as a monolithic block — the same ~2K token document appears in both ANALYZE and COMPOSE via `compose_instructions()`.

## The One-Shot vs. Chain Asymmetry

In the **one-shot path**, the model receives everything in one context window: identity, standing orders, situation data, and the composition task. The "When to act vs. observe" decision tree directly influences what the model writes because assessment and composition happen in the same inference call. Standing orders work because they're present at the moment of decision.

In the **chain path**, standing orders appear at ANALYZE and COMPOSE, but:

1. **ANALYZE sees standing orders but its step-specific framing overrides them.** The "Silence is professionalism" instruction is in the ANALYZE step prompt — it's closer to the task instruction and carries more weight than a buried section in a ~2K token standing orders document. The model follows the proximal instruction.

2. **COMPOSE sees standing orders but may never run.** When ANALYZE returns `["silent"]`, the compose short-circuit fires. Standing orders' action vocabulary exists in compose but compose never executes.

3. **Neither step receives standing orders *decomposed for its role*.** ANALYZE gets the full document including composition guidance it doesn't need. COMPOSE gets the full document including assessment guidance it doesn't need. Both are searching a large document for the few paragraphs relevant to their specific cognitive function.

## The Billet Model

AD-647 (Process-Oriented Cognitive Chains) already frames chain steps as distinct roles with their own prompt templates. BF-209 (Scout chain bypass) demonstrated that the communication chain is wrong for process work — scout reports need a data pipeline, not a communication pipeline.

Extending this thinking: **each chain step is a billet** — a defined role in a cognitive process. A billet has:

- **Task-specific instructions** — what this step does (assess, compose, evaluate)
- **Decision space** — what outputs this step can produce
- **Operational context** — what this step needs to know to do its job

Standing orders in their current form conflate all three across all billets. The action vocabulary is an assessment rubric (ANALYZE's decision space), communication discipline is a composition rule (COMPOSE's instructions), and the chain of command is scope context (ANALYZE's operational context).

## Decomposition Proposal

Instead of injecting monolithic standing orders at each step, decompose them into **step-relevant operational instructions** baked into each step's prompt:

### What moves INTO step prompts:

| Standing Order Section | Belongs To | Rationale |
|---|---|---|
| "When to act vs. observe" decision tree | ANALYZE | This is an assessment rubric, not a composition instruction |
| Action vocabulary (PROPOSAL, REPLY, DM, etc.) | ANALYZE `intended_actions` descriptions | These define the decision space for assessment |
| Communication discipline (register, formality) | COMPOSE | Composition rules for output quality |
| Action tag syntax ([PROPOSAL], [DM], etc.) | COMPOSE | Output formatting for the composition step |
| Quality standards ("be specific, actionable") | EVALUATE/REFLECT | Evaluation criteria |
| Chain of command / authority scope | ANALYZE | Scope constraints for what's in-lane |
| Department expertise framing | ANALYZE + COMPOSE | Assessment lens + voice |

### What STAYS in standing orders:

| Standing Order Section | Rationale |
|---|---|
| Identity / Character | Who you are — transcends any single cognitive step |
| Federation tier (values, principles) | Constitutional — applies to all behavior |
| Ship tier (mission, culture) | Environmental — applies to all behavior |
| Active directives (Captain's orders) | Authority — applies to all behavior |
| Personality seed / Big Five expression | Voice — but only relevant at COMPOSE |

### The result:

Standing orders shrink to **identity-level behavioral guidance** — who you are, how you carry yourself, what your values are. The operational instructions get decomposed into the steps that need them as **billet instructions**.

## Relationship to AD-647 (Process Chains)

AD-647 proposes process-oriented chains with their own step types (QUERY, TRANSFORM, STORE, NOTIFY). If standing orders are decomposed into billet instructions, process chains benefit directly:

- A scout report TRANSFORM step gets classification rubrics, not communication discipline
- An incident response NOTIFY step gets escalation rules, not assessment guidance
- Each process defines its own step sequence AND each step carries only its relevant instructions

AD-647 depends on AD-618 (Bills/SOPs) for declarative YAML process definitions. The Bill YAML could specify per-step instruction overrides — a Bill for "duty_status_report" might include ANALYZE instructions like "focus on department activity since last report" and COMPOSE instructions like "use structured format: highlights, concerns, recommendations."

## Token Budget Impact

Current state: `compose_instructions()` injects ~2K tokens at ANALYZE and COMPOSE = ~4K total per chain execution.

Decomposed state: Each step gets only its relevant section. Rough estimates:
- ANALYZE: decision tree (~300 tokens) + scope (~200 tokens) = ~500 tokens
- COMPOSE: action tag syntax (~400 tokens) + communication discipline (~300 tokens) + identity (~500 tokens) = ~1,200 tokens
- EVALUATE: quality criteria (~200 tokens) = ~200 tokens

Total: ~1,900 tokens — slight reduction, but more importantly each token is *relevant* to the step consuming it. No more ANALYZE parsing through composition guidance looking for assessment rubrics.

## Connection to NATS (AD-641g)

The NATS message envelope (AD-641g) already defines a structure:

```
baseline: {temporal, working_memory, ontology, metrics}
intent_context: {varies by path}
prior_results: {query_results}
```

Decomposed standing orders fit naturally as a new envelope field:

```
billet_instructions: {step-specific operational guidance}
```

This would be assembled by the chain orchestrator based on the step type and the agent's standing orders. The NATS message carries the instructions — the step consumer doesn't need to call `compose_instructions()` at all.

## Risk: Over-Decomposition

The one-shot path works partly because the model sees everything at once and can make holistic judgments. Over-decomposing standing orders risks creating steps that are too narrowly scoped — an ANALYZE step that doesn't know about communication discipline might approve a response that COMPOSE then struggles to make appropriate. The identity and values sections of standing orders provide a "constitutional" baseline that should remain available at every step.

**Mitigation:** Keep identity/values/federation/ship tiers as a universal "constitutional preamble" at every step. Only decompose the *operational* sections (action vocabulary, communication rules, quality standards) into step-specific instructions.

## Recommendation

This should be an AD (not a BF) because it's architectural — it changes how the chain consumes standing orders, affects all agents, and intersects with AD-647 (process chains) and AD-641g (NATS). However, it's not urgent — BF-213's targeted fix (rebalancing analyze framing) addresses the immediate behavioral gap. This AD should land after AD-647 and AD-641g because the NATS envelope and process chain infrastructure provide the right abstraction layer for per-step instruction delivery.

**Phasing:**
1. **Phase 1 (near-term, post BF-213):** Extract the "When to act vs. observe" decision tree from standing orders into ANALYZE's step prompt. This is the highest-impact single change — the decision tree belongs at assessment, not composition.
2. **Phase 2 (with AD-647):** Define billet instruction format in Bill YAML. Process chains carry per-step instructions natively.
3. **Phase 3 (with AD-641g):** NATS message envelope includes `billet_instructions` field. Chain orchestrator assembles step-specific instructions from decomposed standing orders.

## Literature / Analogies

- **Navy watch bills**: Each watch station has a binder with station-specific procedures, not a copy of the entire ship's standing orders. The watch stander knows the ship's rules (general orders) but their binder tells them what to do at *this* station.
- **Microservice architecture**: Each service has its own configuration, not a monolithic config file. Shared configuration (env vars, secrets) is separate from service-specific configuration.
- **Cognitive task analysis (CTA)**: Decomposes expert performance into decision points with their own knowledge requirements. Each decision point needs specific knowledge, not the expert's entire knowledge base.
