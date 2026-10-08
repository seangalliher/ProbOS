# Consensus Layer

The Consensus layer is ProbOS's safety and accountability mechanism: intents that declare `requires_consensus` go to a multi-agent vote, and every outcome updates the trust each agent has earned.

## Pipeline

```
broadcast → quorum evaluation → red team verification
    → Shapley attribution → trust update → Hebbian learning
```

## What a Vote Buys

Not every vote can authorize an act. Each consensus intent declares a `consensus_mode` on its `IntentDescriptor`, so the answer is stated rather than assumed:

| Mode | What happens | Intents (examples) |
|------|--------------|--------------------|
| `propose_commit` | Agents propose and do **not** act; the runtime commits only when the vote approves | `write_file`, `mcp_invoke`, device actuation |
| `external_gate` | The agent prepares the work, but an authority outside the mesh — the Captain's approval — gates the effect | `build_code` |
| `execute_then_vote` | The agent acts on broadcast; the vote scores the outcome and drives trust, but authorizes nothing and cannot roll it back | `run_command`, `run_python`, `install_package`, office-document edits |

`execute_then_vote` is the default, because some agents cannot observe without acting — a shell command must run to produce its output. At startup the runtime logs every consensus intent that has no real gate, and each consensus record in the event log carries its mode, so an operator can tell whether a quorum authorized an act or scored it afterwards. Read-only intents such as `read_file` and `http_fetch` (GET and HEAD only, SSRF-guarded) do not require consensus.

Destructive work is also governed outside the vote: tool permissions and clearance grants, the approvals center on the Bridge, chain-of-command routing for approvals, and the audit log.

## Components

### Quorum Engine

Collects confidence-weighted votes from agents. Each vote carries:

- The agent's decision (approve/reject)
- A confidence score (0.0 to 1.0)
- An optional reason string

The quorum passes when the weighted approval exceeds the configured threshold (`consensus.min_votes` and `consensus.approval_threshold`).

### Trust Network

A Bayesian trust model using Beta distributions. Each agent's reliability is tracked as Beta(α, β):

- **Success** → α increments (trust increases)
- **Failure** → β increments (trust decreases)
- **Expected trust** = α / (α + β)

The raw (α, β) parameters are stored, never just the derived mean, so the full distribution is preserved. Built-in agents start from the configured prior; self-designed agents start on probationary trust. Trust scores decay slowly over time so agents must keep performing to keep high trust.

### Trust Cascade Dampening

Three layers keep one failure from collapsing trust across the network: progressive dampening of repeated penalties, a hard trust floor, and a network circuit breaker that trips when too many agents in too many departments are affected at once.

### Shapley Attribution

After an operation completes, Shapley values determine each agent's marginal contribution to the outcome. This provides fair credit assignment — agents that contributed more to successful outcomes gain more trust.

### Escalation

A three-tier failure cascade:

1. **Retry** with a different agent from the pool
2. **LLM arbitration** — approve, reject, or modify and retry
3. **User consultation** — the Captain decides

### Red Team Verification

Red team agents (two by default) independently re-execute operations to verify results. If a red team agent disagrees with the primary result, the operation is flagged.

A test agent (`CorruptedFileReaderAgent`) deliberately returns fabricated data to verify that the consensus layer detects and rejects it.

## Source Files

| File | Purpose |
|------|---------|
| `consensus/quorum.py` | Confidence-weighted voting |
| `consensus/trust.py` | Bayesian Beta(α,β) reputation and cascade dampening |
| `consensus/shapley.py` | Shapley value attribution |
| `consensus/escalation.py` | 3-tier failure cascade |
| `types.py` | `IntentDescriptor.consensus_mode` |
