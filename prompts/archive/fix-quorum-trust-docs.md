# Build Prompt: Fix Quorum Trust Docs Drift (BF-006)

## Context

GPT-5.4 code review found that `docs/architecture/consensus.md` contains two
inaccuracies:

1. **Line 6:** Lists "HTTP fetches" as a consensus-gated destructive operation.
   AD-150 removed consensus gating from `http_fetch`. This was already fixed in
   `docs/development/structure.md` and `docs/agents/inventory.md` (BF-005) but
   `consensus.md` was missed.

2. **Line 24:** Claims each vote carries "The agent's current trust reputation."
   The actual `Vote` dataclass (`types.py:113`) has no trust field — it has
   `agent_id`, `approved`, `confidence`, `reason`, `timestamp`. The quorum
   engine (`quorum.py:62`) weights votes by `confidence`, not trust. Trust is
   used separately in the TrustNetwork layer, not in quorum voting.

**Identified by:** GPT-5.4 code review (2026-03-21)

---

## Changes

### File: `docs/architecture/consensus.md`

**Change 1 (line 6):** Remove "HTTP fetches" from the destructive operations list.

Before:
```
Destructive operations (file writes, shell commands, HTTP fetches) follow this pipeline:
```

After:
```
Destructive operations (file writes, shell commands) follow this pipeline:
```

**Change 2 (lines 20-24):** Remove the inaccurate trust reputation bullet from
the vote description.

Before:
```
Collects confidence-weighted votes from agents. Each vote carries:

- The agent's decision (approve/reject)
- A confidence score (0.0 to 1.0)
- The agent's current trust reputation
```

After:
```
Collects confidence-weighted votes from agents. Each vote carries:

- The agent's decision (approve/reject)
- A confidence score (0.0 to 1.0)
- An optional reason string
```

---

## Constraints

- Modify ONLY `docs/architecture/consensus.md`
- Do NOT change any source code
- Do NOT modify any other doc files
