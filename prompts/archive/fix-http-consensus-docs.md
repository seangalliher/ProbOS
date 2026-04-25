# Build Prompt: Fix HTTP Consensus Docs Drift (BF-005)

## Context

AD-150 removed consensus gating from `http_fetch` operations, but two
documentation files still describe HTTP fetches as consensus-gated. This
misleads contributors and prompt writers.

**Identified by:** GPT-5.4 code review (2026-03-21)

---

## Changes

### File: `docs/development/structure.md` (line 17)

Before:
```
│   ├── http_fetch.py        #   http_fetch (rate-limited, consensus-gated)
```

After:
```
│   ├── http_fetch.py        #   http_fetch (rate-limited)
```

### File: `docs/agents/inventory.md` (line 15)

The table row for `http` has `Yes` in the Consensus column. Change it to `No`:

Before:
```
| `http` | 3 | `http_fetch` (1MB cap, per-domain rate limiting) | Yes |
```

After:
```
| `http` | 3 | `http_fetch` (1MB cap, per-domain rate limiting) | No |
```

### File: `docs/agents/inventory.md` (line 20)

The note says "This includes file writes, shell commands, and HTTP fetches."
Remove "and HTTP fetches":

Before:
```
    Operations marked "Yes" in the Consensus column require multi-agent agreement before execution. This includes file writes, shell commands, and HTTP fetches — any operation that modifies state or reaches outside the system.
```

After:
```
    Operations marked "Yes" in the Consensus column require multi-agent agreement before execution. This includes file writes and shell commands — operations that modify state or execute arbitrary code.
```

---

## Constraints

- Modify ONLY the two documentation files listed above
- Do NOT change any source code
- Do NOT modify any other doc files
