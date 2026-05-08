# BF-505 v1 — Restore consultation delivery finalize wirer + Pydantic config

**Issue:** [#505](https://github.com/seangalliher/ProbOS/issues/505)
**Type:** Bug Fix (post-AD-594d bit-rot)
**Depends on:** AD-594a (`_wire_consultation_workspaces`, `WorkspaceRegistry`), AD-594d (`DeliveryPipeline`, `LocalFileAdapter`, `GitHubAdapter` shipped).
**Wave:** 129

## Goal

`tests/test_ad594d_delivery_pipeline.py` ships three finalize-wirer regression tests (test 28/29/30 at lines 622–664) that import `_wire_consultation_delivery` from `probos.startup.finalize` and `ConsultationDeliveryConfig` from `probos.config`. Both symbols were removed (or never landed) when AD-594d was merged — `DECISIONS.md` line 1240 records the bit-rot. This BF restores the two symbols so the three tests pass without touching the underlying `DeliveryPipeline` (which is healthy at HEAD).

## Verified Against Codebase (2026-05-08)

- ✅ `src/probos/consultation/delivery.py:584` defines `class DeliveryPipeline:` with `register_adapter()` + `list_adapters() -> list[str]` returning sorted names.
- ✅ `src/probos/consultation/delivery.py:338` defines `class LocalFileAdapter:` and `:455` defines `class GitHubAdapter:` — both expose a `name` attribute (used by `register_adapter`).
- ✅ `src/probos/consultation/workspace.py:297` defines `class WorkspaceRegistry:`.
- ✅ `tests/test_ad594d_delivery_pipeline.py:629` imports `_wire_consultation_delivery`; `:633`/`:646`/`:661` call it as `_wire_consultation_delivery(runtime=runtime, config=config)` (kwarg-only) and assert it returns a `bool`.
- ✅ `tests/test_ad594d_delivery_pipeline.py:635` asserts `runtime.consultation_delivery.list_adapters() == ["github", "local_file"]` — adapter names verified by reading `delivery.py` (`LocalFileAdapter.name == "local_file"`, `GitHubAdapter.name == "github"`).
- ✅ `tests/test_ad594d_delivery_pipeline.py:649` asserts the disabled-registry path logs `"consultation_workspaces unavailable"`.
- ✅ `tests/test_ad594d_delivery_pipeline.py:655` imports `ConsultationDeliveryConfig` from `probos.config`; `:659` constructs `ConsultationDeliveryConfig(enabled=False)` and assigns to `config.consultation_delivery`.
- ✅ `_wire_consultation_workspaces` exists in `startup/finalize.py` (sync function; AD-594a sibling pattern referenced in `decisions-era-5-unification.md:81` at `finalize.py:515`). `_wire_consultation_delivery` MUST mirror its sync `(*, runtime, config) -> bool` shape.
- ✅ `DECISIONS.md:1240` confirms: AD-594d shipped, the three tests fail "on `_wire_consultation_delivery` / `ConsultationDeliveryConfig` imports — tracked in #505".

## Scope

Restore exactly the two missing symbols so the three failing tests pass. Do NOT modify `DeliveryPipeline`, `LocalFileAdapter`, `GitHubAdapter`, `WorkspaceRegistry`, the existing `_wire_consultation_workspaces`, or any of the 27 already-passing tests in the file.

## Deliverables

### D1. `ConsultationDeliveryConfig` Pydantic model in `src/probos/config.py`

Add adjacent to `ConsultationWorkspaceConfig` (currently around `config.py:1876`–`1904`). Mirror the AD-594a precedent.

```python
class ConsultationDeliveryConfig(BaseModel):
    """AD-594d delivery pipeline config.

    ``enabled`` defaults True (same precedent as ConsultationWorkspaceConfig
    and KnowledgeEdgesConfig). The pipeline construction at boot is
    side-effect-free: instantiates an empty adapter dict and registers two
    built-in adapters (``LocalFileAdapter``, ``GitHubAdapter``) that perform
    no IO until ``deliver()`` is called.
    """

    enabled: bool = True
```

Wire onto `SystemConfig` adjacent to `consultation_workspaces`:

```python
consultation_delivery: ConsultationDeliveryConfig = Field(
    default_factory=ConsultationDeliveryConfig
)
```

### D2. `_wire_consultation_delivery` in `src/probos/startup/finalize.py`

Insert immediately after `_wire_consultation_workspaces` and before `_wire_workspace_ontology`. Sync function, kwarg-only signature, returns `bool` (matches test expectation at line 633).

Behavior:
- Return `False` and log INFO `"AD-594d: consultation_workspaces unavailable; skipping delivery pipeline"` if `runtime.consultation_workspaces` is missing or falsy. (Tests assert `"consultation_workspaces unavailable" in rec.message` at `:649`.)
- Return `False` and log INFO if `config.consultation_delivery.enabled is False`.
- Otherwise: construct `DeliveryPipeline(registry=runtime.consultation_workspaces)`, register `LocalFileAdapter()` and `GitHubAdapter()` via `register_adapter()`, assign to `runtime.consultation_delivery` (collision-free public attribute), return `True`.

```python
def _wire_consultation_delivery(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-594d: wire the consultation delivery pipeline.

    Sync; kwarg-only. Mirrors the shape of _wire_consultation_workspaces.
    Returns True iff the pipeline was constructed and assigned to
    ``runtime.consultation_delivery``.
    """
    cfg = getattr(config, "consultation_delivery", None)
    if cfg is None or not cfg.enabled:
        logger.info("AD-594d: consultation_delivery disabled; skipping pipeline")
        return False

    registry = getattr(runtime, "consultation_workspaces", None)
    if not registry:
        logger.info(
            "AD-594d: consultation_workspaces unavailable; "
            "skipping delivery pipeline"
        )
        return False

    from probos.consultation.delivery import (
        DeliveryPipeline,
        GitHubAdapter,
        LocalFileAdapter,
    )

    pipeline = DeliveryPipeline(registry=registry)
    pipeline.register_adapter(GitHubAdapter())
    pipeline.register_adapter(LocalFileAdapter())
    runtime.consultation_delivery = pipeline
    logger.info(
        "Startup [consultation_delivery]: wired DeliveryPipeline with adapters %s",
        pipeline.list_adapters(),
    )
    return True
```

### D3. Invocation in `finalize_startup`

Invoke the new wirer immediately after the existing `_wire_consultation_workspaces` invocation block, mirroring the same try/except pattern any sibling wirer uses. Tier-2 log-and-degrade — never raise.

```python
try:
    _wire_consultation_delivery(runtime=runtime, config=config)
except Exception:
    logger.warning(
        "AD-594d: _wire_consultation_delivery raised; "
        "consultation_delivery disabled",
        exc_info=True,
    )
```

## Non-Goals

- Do NOT modify `DeliveryPipeline`, `LocalFileAdapter`, `GitHubAdapter`, or any consultation/* business logic.
- Do NOT rename or move the existing 27 passing tests.
- Do NOT change `BaseAgent`, `IntentMessage`, `RuntimeProtocol`.
- Do NOT add new validators on `ConsultationDeliveryConfig` beyond `enabled: bool = True`.
- Do NOT change the order of `_wire_consultation_workspaces` or `_wire_workspace_ontology`.

## Acceptance

- Focused: `pytest tests/test_ad594d_delivery_pipeline.py -v -n 0` — all 30 tests pass (was 27 passing + 3 failing).
- Full gate: `pytest tests/ -q -n 16 --dist=loadfile` — green or only environmental flakes.
- `git diff` touches only: `src/probos/config.py`, `src/probos/startup/finalize.py`. No new files. No test edits.
- Comply with engineering principles in `.github/copilot-instructions.md`.

## Tracking

- Closes [#505](https://github.com/seangalliher/ProbOS/issues/505).
- DECISIONS.md entry stub: BF-505 — restored AD-594d wirer/config seams; no behavior change beyond test-restoration.
