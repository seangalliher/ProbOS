# Wave 150 Dispatch — AD-724 DM Sanity Gate (System-1 quality floor)

**Date filed:** 2026-05-11
**Issues closed:** #582 (AD-724)
**Wave size:** 1 prompt, backend-only, behavior-preserving migration + 3 log-only checks.

## One-line summary

Migrate three inline DM regex cleanups (BF-120 markdown strip, BF-119 challenge parse, AD-572 move parse) out of `routers/agents.py::agent_chat` into a new named, individually-testable `DmSanityGate` module, and add three log-only quality checks (length floor, repetition, orphaned tags). Zero behavior change on the migration side; three new warnings on the check side. Default-ON.

## Prompts (single-prompt wave)

1. `prompts/ad-724-dm-sanity-gate.md` — backend only.

## Pre-flight gate

1. `git status` clean; HEAD at Wave 149 commit (`2d37973`) or later.
2. `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile` — full gate green baseline. Note `-n 4` not `-n auto`.
3. `pwsh scripts/phantom-api-precheck.ps1 prompts/ad-724-dm-sanity-gate.md` — clean.
4. Confirm AD-724 is reserved-but-unbuilt: `Select-String -Path DECISIONS.md -Pattern '### AD-724'` returns the line 1741 stub entry only (no "Implementation" subsection yet).

## Hard-stop conditions

1. **Any pre-existing `test_agent_chat_*` test breaks after Section 4.** This signals the migration is NOT byte-identical. STOP. Surface to Architect with the failing assertion + the diff. Do NOT relax the test.
2. **Any `test_*recreation*` test that exercises the chat handler breaks.** Same as above — the challenge/move dispatch must work unchanged.
3. **`re` import becomes unused** in `routers/agents.py` after edits. Two of the SEARCH/REPLACE blocks (4c, 4e) intentionally keep the legacy `re.sub` in their `else:` branches so the import is still needed. If your linter flags it as unused, the `else:` branches were dropped — restore them.
4. **`DmSanityGateConfig` Pydantic validation fails on default construction.** STOP. The defaults must produce a valid config; this is enforced by the Engineering Principles ("ProbOS must boot with zero config").
5. **State-pollution between agents.** Test #11 (`test_repetition_state_is_per_agent`) failing means the cache key is wrong. STOP and re-read Section 1's cache key (must be `agent_id`, not text).

## Anti-patterns to avoid (wave-specific)

- **Centralizing the dispatch into the gate.** The gate only owns regex extraction. The `rec_svc.create_game(...)` / `rec_svc.make_move(...)` calls + the Ward Room board-update post stay in the router. Don't refactor them out — that's a separate concern.
- **Tier-3 propagate when the spec says Tier-2 log-and-degrade.** No `raise` from any check. No exception-based rejection. Ever.
- **Adding `runtime.emit_event(...)` calls in the gate.** Forward marker. The gate logs; it does not publish events in this AD.
- **Default `enabled = False`.** The three migrated regex cleanups are already running unconditionally in HEAD. Default-OFF would break them on first commit — Wave-10 default-True-on-transitional-flag anti-pattern in reverse.
- **Persisting the repetition cache** (ChromaDB, SQLite, disk). The cache is in-memory and intentionally lost on restart.
- **Splitting `DmSanityGate` / `DmSanityGateConfig` / `DmSanityResult` across multiple files.** Single new module. AD-724-1 will land in the same file.
- **Adding `_CAPABILITY_GAP_RE` integration.** Forward marker AD-724-3.
- **Adding similarity-based repetition (Levenshtein, embedding).** Forward marker AD-724-2.
- **Touching Ward Room or chain-of-reasoning paths.** Forward marker AD-724-5.

## Commit message format

```
AD-724 (Wave 150): DM sanity gate — migrate BF-120/BF-119/AD-572 regex
cleanups into a named module + add 3 log-only quality checks.

Closes #582. New module src/probos/cognitive/dm_sanity_gate.py exposes
DmSanityGate (stateful per-agent last-reply cache) and DmSanityGateConfig
(default-ON, length_floor=5, repetition_prefix_chars=100).

Three migrated behaviors are byte-identical to HEAD:
  - strip_markdown() (BF-120)
  - extract_challenge() + strip_challenge() (BF-119)
  - extract_move() + strip_move() (AD-572)

Three new Tier-2 log-and-degrade checks log warnings without blocking:
  - length floor (replies < 5 chars after strip)
  - repetition (identical first-100-char prefix as last reply per agent)
  - orphaned tags ([CHALLENGE without close, [MOVE without value, [])

Forward markers AD-724-1 through AD-724-5 stay open for retry logic,
similarity-based repetition, capability-gap regex, multi-turn coherence,
and WR/chain path coverage.

Tests: +14 backend.
```

## Tracking

- `PROGRESS.md` — close #582; increment backend test count by +14; update "most recent shipped wave" to 150.
- `docs/development/roadmap.md` — mark AD-724 shipped.
- `DECISIONS.md` — append "Implementation (Wave 150)" subsection to the existing AD-724 stub at line 1741 with module location, config defaults, and the five forward markers.
- `prompts/wave-plan.yaml` — Wave 150 entry status `shipped`.
- GH #582 closed with commit reference.

## Acceptance criteria

- All 14 new tests pass under `pytest tests/test_ad724_dm_sanity_gate.py -v -n 0`.
- Full gate green: `pytest tests/ -q -n 4 --dist=loadfile`.
- Phantom-API precheck clean.
- `RuntimeOS.dm_sanity_gate` is initialized in `__init__` (verify by introspection: import `RuntimeOS`, instantiate with a default `SystemConfig()`, assert `isinstance(runtime.dm_sanity_gate, DmSanityGate)`).
- Default-construction of `DmSanityGateConfig()` produces `enabled=True, length_floor=5, repetition_prefix_chars=100`.
- A DM reply that previously triggered BF-119 or AD-572 dispatch (manually verified via an existing test) still triggers the same dispatch path with the same arguments after migration.
- All changes comply with Engineering Principles in `.github/copilot-instructions.md`.

## Numbering audit (per AD numbering hard rule)

- **Current highest AD:** AD-729 (per PROGRESS.md line 10).
- **Current highest BF:** BF-259 (per DECISIONS.md grep).
- **This wave:** uses AD-724 — a reserved-but-unbuilt slot in the AD-722 cluster (`DECISIONS.md:1741` stub entry, see prompt's Verified section).
- **No new BF expected** — behavior-preserving migration. If a Builder uncovers a real regression (i.e. a router test breaks that was previously passing), file BF-260 and surface, do not paper over.
