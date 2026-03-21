# Consensus Layer

The Consensus layer ensures safety — destructive operations require multi-agent agreement before execution.

## Pipeline

Destructive operations (file writes, shell commands) follow this pipeline:

```
broadcast → quorum evaluation → red team verification
    → Shapley attribution → trust update → Hebbian learning
```

A single corrupted agent cannot cause damage.

## Components

### Quorum Engine

Collects confidence-weighted votes from agents. Each vote carries:

- The agent's decision (approve/reject)
- A confidence score (0.0 to 1.0)
- An optional reason string

The quorum passes when the weighted approval exceeds the configured threshold.

### Trust Network

A Bayesian trust model using Beta distributions. Each agent's reliability is tracked as Beta(α, β):

- **Success** → α increments (trust increases)
- **Failure** → β increments (trust decreases)
- **Expected trust** = α / (α + β)

Trust scores decay slowly over time so agents must maintain performance to keep high trust.

### Shapley Attribution

After an operation completes, Shapley values determine each agent's marginal contribution to the outcome. This provides fair credit assignment — agents that contributed more to successful outcomes gain more trust.

### Escalation

A 3-tier failure cascade:

1. **Retry** with different agent selection
2. **Escalate** to broader quorum
3. **Reject** with explanation to the user

### Red Team Verification

Two red team agents independently re-execute operations to verify results. If a red team agent disagrees with the primary result, the operation is flagged.

A test agent (`CorruptedFileReaderAgent`) deliberately returns fabricated data to verify that the consensus layer detects and rejects it.

## Source Files

| File | Purpose |
|------|---------|
| `consensus/quorum.py` | Confidence-weighted voting |
| `consensus/trust.py` | Bayesian Beta(α,β) reputation |
| `consensus/shapley.py` | Shapley value attribution |
| `consensus/escalation.py` | 3-tier failure cascade |
