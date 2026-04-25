# BF-004: Fix Verification False Positive on Per-Pool Agent Counts

## Problem

`_verify_response()` in `src/probos/runtime.py` (line 1498) uses a regex
`(\d+)\s+agents?\b` that matches **any** number followed by "agent(s)" and
compares it against the **system-wide total** (`self_model.agent_count`).

When the LLM describes per-pool or per-department agent counts (e.g. "the
medical pool has 3 agents"), the verifier flags `agents: claimed 3, actual 53`
— a false positive. The same issue affects Check 1 (`(\d+)\s+pools?\b`).

Real log output showing the problem:
```
Response verification found 5 violation(s): agents: claimed 18, actual 53;
agents: claimed 20, actual 53; agents: claimed 5, actual 53;
agents: claimed 2, actual 53; agents: claimed 3, actual 53
```

These numbers (18, 20, 5, 2, 3) are per-department breakdowns — all valid.
The verification appends an unnecessary correction footnote.

## Fix

Modify Check 1 and Check 2 in `_verify_response()` to distinguish **total
system claims** from **per-pool/per-department claims**.

### Check 2 (agent counts) — new logic:

1. **Keep the existing regex** `(\d+)\s+agents?\b` to find all numeric agent
   references.
2. For each match, examine the **surrounding context** (e.g. 80 chars before
   the match) to determine if the claim is pool-specific or department-specific.
3. **Skip the match** (do not flag as violation) if the preceding context
   contains any of:
   - A known pool name from `self_model.pools` (e.g. "medical pool has 3 agents")
   - A known department name from `self_model.departments` (e.g. "Engineering has 18 agents")
   - Contextual words indicating a subset: "pool", "department", "team", "group",
     "division", "each", "per"
4. **Only flag** matches that appear to claim a system-wide total — i.e. the
   surrounding context contains words like "total", "all", "system", "ship",
   "across", "overall", or lacks any pool/department qualifier.
5. Also add a **known-count whitelist**: if the claimed number matches any
   individual `pool.agent_count` from `self_model.pools`, skip it — it's
   likely referring to that pool even without explicit context.

### Check 1 (pool counts) — same logic:

Apply the same contextual-awareness approach. Skip matches where surrounding
context indicates a subset (e.g. "3 pools in Engineering"). Only flag when the
claim appears system-wide.

### Implementation notes:

- Use `match.start()` from `re.finditer()` (not `re.findall()`) to get match
  positions for context window extraction.
- Context window: `response_lower[max(0, start-80):start]` is sufficient.
- Keep the method zero-LLM — all checks are regex/string-based.
- Keep the existing footnote behavior (append correction, never suppress response).

## Files to modify

- `src/probos/runtime.py` — `_verify_response()` method (lines 1498-1582)

## Files to read first

- `src/probos/runtime.py` — full `_verify_response()` method
- `src/probos/cognitive/self_model.py` — `SystemSelfModel` and `PoolSnapshot` dataclasses
- `tests/test_decomposer.py` — existing `TestPreResponseVerification` tests (line 1051+)

## Tests

Update existing tests in `tests/test_decomposer.py` `TestPreResponseVerification`:

1. **Add test: per-pool agent count not flagged** — response mentions
   "the medical pool has 3 agents" where actual total is 53. Verify no
   violations logged and no footnote appended.

2. **Add test: per-department breakdown not flagged** — response lists
   "Engineering has 18 agents, Science has 5 agents, Medical has 3 agents".
   Verify no violations.

3. **Add test: wrong system-wide total still caught** — response says
   "the system has 100 agents" when actual is 53. Verify violation IS flagged.

4. **Add test: ambiguous count matching a known pool size not flagged** —
   response mentions "3 agents" without explicit pool qualifier, but 3 matches
   `medical_pool.agent_count`. Verify no violation.

5. **Preserve existing tests** — all current verification tests must continue
   to pass.

## Acceptance criteria

- Per-pool and per-department agent/pool counts no longer trigger false positives
- System-wide incorrect claims are still caught
- All existing tests pass
- New tests cover the scenarios above
- Zero LLM calls in verification (regex/string only)
