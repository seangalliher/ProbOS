# Review: better-agents — Behavior Contract
**Verdict:** ✅ Approved
**Declarative YAML→TestResult adapter; reuses `QualificationStore`; clean stub-invoker discipline.**

## Required (must fix before building)
_None._

## Recommended
1. Add the working-tree integrity reminder (convention #20).
2. `_MustRule.matches` returns `True` for an empty rule (all three fields `None`). Pydantic does not currently forbid that shape. Add a `model_validator(mode="after")` requiring **exactly one** of `substring`/`substring_any`/`regex` to be set, or document the empty-rule semantics explicitly. As written, a malformed YAML silently passes every case.
3. `evaluate_contract` accumulates `error: str | None` only for the *last* exception. If any case raised, the others' results are still scored, but the returned `error` field is non-deterministic. Either record errors per-case in `details["cases"][i]["error"]` (already done) and clear the top-level `error` so it reflects "any exception happened" semantics, or rename it `last_error`.
4. CLI subcommand uses `asyncio.run(...)` inside the `for f in files:` loop — one event loop per contract file. For a directory of 50 contracts that's 50 loop spin-ups. Acceptable for v1, but consider `asyncio.run(_run_all(files))` with one outer loop. Defer to AD-708-1.

## Nits
- D2 stub invoker returns `""` — works, but a one-line comment "(Builder: do NOT replace with hot-runtime invoker in this AD)" would harden the boundary against future commits.
- `_MustRule` leading underscore + Pydantic public model is slightly unusual — Pydantic models named `_X` look private but are imported by the loader. Rename to `MustRule` (no underscore) for clarity; nothing breaks.
- `pyyaml` is already a transitive dep of several existing modules — verify-first the `pyproject.toml` claim before adding a redundant pin.

## Verified
- `src/probos/cognitive/qualification.py:40` `class QualificationTest(Protocol)` — confirmed.
- `src/probos/cognitive/qualification.py:71` `class TestResult(frozen=True)` — confirmed.
- `src/probos/cognitive/qualification.py:136` `class QualificationStore` — confirmed.
- `src/probos/__main__.py:598` `def _cmd_init(args: argparse.Namespace) -> None` — confirmed (prompt says `:599`, drift = 1).
- No existing `behavior_contract` or `qa_run_contracts` symbol — greenfield claim holds.
- Hard-constraint list correctly forbids LangWatch SDK import, scenario simulator, hot runtime invoker, separate persistence table.
- Sample contract at `config/contracts/sample_refusal.yaml` aligns with the Pydantic schema.

## Pass 2 Review (2026-05-08)

**Verdict:** ✅ Approved
**Pass-1 had 0 Required; pass-2 confirms cross-cutting items landed.**

### Required
None.

### Recommended
None new.

### Nits
None new.

### Verified Improvements (pass-2)
- ✅ Working-tree integrity reminder added to Acceptance section. No config.py touch — no Build Ordering Note required.
- ✅ No phantom-API regressions introduced.
- ✅ All previously-verified symbols still match HEAD.

### Pass-2 outcome
Held at ✅. Cleared for Builder dispatch.
