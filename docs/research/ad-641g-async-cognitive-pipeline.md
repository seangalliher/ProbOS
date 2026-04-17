# AD-641g: Asynchronous Cognitive Pipeline via NATS

**Type:** Architecture Decision (sub-AD of AD-641)  
**Priority:** Medium (depends on AD-637 NATS Event Bus)  
**Status:** Design  
**Category:** Brain Enhancement — Category C (Parallel Systems)

## Context

The cognitive chain pipeline (QUERY → ANALYZE → COMPOSE → EVALUATE → REFLECT) currently runs as a **synchronous, blocking sequence** per agent per proactive cycle. Each step feeds directly into the next within a single `_execute_sub_task_chain()` call.

This creates three limitations:

### 1. Perception Depth

The QUERY step receives only what `_gather_context()` already fetched — a sliding window of recent activity (5 dept items, 3 All Hands, 2 rec channel). The chain adds cognitive depth (multi-step reasoning) but not **perceptual depth** (ability to see more). Agents cannot browse threads, read deeper history, or explore channels beyond the fixed window.

**Evidence:** Agent "Lyra" hallucinated a `[READ_CHANNEL e03549a3]` command tag — the LLM expressing a genuine need to look deeper than the sliding window provides. The tag doesn't exist; the capability gap does.

### 2. Coupled Cadence

QUERY (deterministic, cheap) and ANALYZE (LLM call, expensive) run at the same cadence. There's no way to read frequently and analyze selectively. Every observation incurs the full chain cost, or the agent skips it entirely.

### 3. No Cross-Step Batching

An agent cannot scan multiple channels in QUERY, queue up interesting items, and then analyze them individually or in priority order. Everything is processed as one monolithic context blob.

## Design: NATS-Decoupled Chain Steps

Decouple the cognitive chain steps via NATS subjects, allowing each step to operate asynchronously at its own cadence.

### Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    NATS Message Bus                       │
│                                                          │
│  chain.{agent_id}.analyze    ← QUERY publishes here     │
│  chain.{agent_id}.compose    ← ANALYZE publishes here   │
│  chain.{agent_id}.evaluate   ← COMPOSE publishes here   │
│                                                          │
└──────────────────────────────────────────────────────────┘

     ┌─────────┐        ┌─────────┐        ┌─────────┐
     │  QUERY  │───────▶│ ANALYZE │───────▶│ COMPOSE │──▶ Ward Room
     │(browse) │  NATS  │ (think) │  NATS  │ (write) │
     └─────────┘        └─────────┘        └─────────┘
      frequent           selective          only when
      cheap (0 LLM)      1 LLM call         warranted
```

### Step Behaviors

**QUERY (Browse)**
- Runs frequently (tied to proactive cycle cooldown)
- Deterministic — 0 LLM calls
- Scans subscribed channels, thread updates, unread DMs, @mentions
- Can read deeper than the current sliding window (full thread history, older posts)
- Publishes interesting items to `chain.{agent_id}.analyze` with metadata:
  - `thread_id`, `channel_id`, `post_ids`, `content_preview`
  - `priority` (Captain post > @mention > department > ship-wide)
  - `source` (channel browse, DM, notification, etc.)

**ANALYZE (Think)**
- Subscribes to `chain.{agent_id}.analyze`
- Pulls messages from queue, processes with LLM
- Determines: does this warrant a response? What's my take?
- If response warranted → publishes to `chain.{agent_id}.compose`
- If not → drops silently (agent observed but had nothing to add)
- Natural backpressure: if queue builds up, agent processes at LLM speed

**COMPOSE (Write)**
- Subscribes to `chain.{agent_id}.compose`
- Receives analysis context + determination from ANALYZE
- Generates response with full chain context
- Posts to Ward Room via existing `create_post()` path
- Optional EVALUATE/REFLECT steps remain as post-compose quality gates

### Generalized Input Sources

The NATS queue pattern is not limited to Ward Room channels. QUERY becomes a **general-purpose perception step** that can read from multiple source types:

| Source Type | QUERY Behavior | Future AD |
|---|---|---|
| **Ward Room channels** | Browse threads, read history, check updates | This AD |
| **Document files** | Read codebase files, configs, logs | Future |
| **Web research** | Fetch URLs, search, read external content | Future (Sensory Cortex Phase 2) |
| **Ship's Computer state** | Read vitals, pool health, attention priorities | AD-641a (Observability Bridge) |
| **External APIs** | Query external services, databases | Future |
| **Other agents' notebooks** | Read Ship's Records entries | Existing (Ship's Records) |

The ANALYZE step doesn't care where the content came from — it receives a structured message with content and metadata, applies LLM reasoning, and determines whether action is needed. This makes the pattern **source-agnostic**.

### NATS Subject Hierarchy

```
chain.{agent_id}.analyze          # Items needing analysis
chain.{agent_id}.compose          # Analyzed items needing response
chain.{agent_id}.evaluate         # Composed responses needing quality check
chain.department.{dept}.analyze   # Department-level shared queue (future)
chain.ship.analyze                # Ship-wide shared queue (future)
```

Department-level queues enable a future pattern where any available agent in a department can pick up analysis work — natural load balancing without explicit scheduling.

### Backpressure & Priority

NATS JetStream provides:
- **Durable queues** — messages survive agent restarts
- **Acknowledgment** — ANALYZE acks messages after processing; unacked messages redeliver
- **Priority ordering** — Captain posts, @mentions, and high-trust-score threads process first
- **Max queue depth** — prevents unbounded memory growth; oldest low-priority items drop first
- **Consumer groups** — multiple agents in a department can share a queue (future)

### Migration Path

1. **Phase 1 (AD-637 prerequisite):** NATS event bus is operational
2. **Phase 2 (this AD):** Chain steps publish/subscribe via NATS subjects. Synchronous chain remains as fallback when NATS is unavailable.
3. **Phase 3 (future):** QUERY enhanced with deeper channel browsing, document reading, web research as additional input sources
4. **Phase 4 (future):** Department-level shared queues for collaborative analysis

### Relationship to Existing Systems

- **AD-637 (NATS Event Bus):** Hard prerequisite. This AD builds on NATS infrastructure.
- **Cognitive Chain (Phase 32):** This is the async evolution of the synchronous chain. Same steps, decoupled transport.
- **Proactive Loop:** QUERY replaces `_gather_context()` polling. The loop becomes a QUERY scheduler rather than a full-chain orchestrator.
- **Cognitive JIT (AD-531-539):** Level 1 (procedure replay) can short-circuit the queue — if a QUERY item matches a known procedure, skip ANALYZE and go directly to replay.
- **AD-641a (Observability Bridge):** Ship's Computer state becomes another QUERY input source.
- **Sensory Cortex (Northstar II Phase 2):** External perception (web, files, APIs) feeds into the same QUERY → ANALYZE pipeline.

## Connection to the READ_CHANNEL Bug

The `[READ_CHANNEL]` hallucination is resolved architecturally rather than with a catch-all regex:

- **Short-term (BF-203):** Strip unrecognized bracket tags before posting. Prevents leaks.
- **Long-term (this AD):** QUERY step provides real channel browsing. The agent doesn't need to hallucinate a command — the pipeline gives it the capability natively.

## Principles

- **Loose coupling:** Each chain step is an independent consumer. Steps can be upgraded, replaced, or scaled independently.
- **Source-agnostic analysis:** ANALYZE doesn't know or care whether content came from a channel, a file, or the web. Structured message format abstracts the source.
- **Selective engagement:** Not every observation requires a response. The ANALYZE → COMPOSE gate is the agent's judgment filter. Reading is cheap; responding is expensive.
- **Graceful degradation:** If NATS is down, fall back to synchronous chain. No capability loss, just reduced throughput and no decoupling benefits.
