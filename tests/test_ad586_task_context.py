"""AD-586: Tests for task-contextual standing orders."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from probos.cognitive import standing_orders
from probos.cognitive.standing_orders import clear_cache, compose_instructions
from probos.cognitive.task_context import TaskContext
from probos.config import TaskContextConfig
from probos.startup.finalize import _wire_task_context


def _context(tmp_path: Path, *, max_tokens: int = 500) -> TaskContext:
    config = TaskContextConfig(orders_dir=str(tmp_path), max_tokens=max_tokens)
    return TaskContext(config=config, orders_dir=tmp_path)


def test_classify_build_task(tmp_path: Path) -> None:
    ctx = _context(tmp_path)

    assert ctx.classify_task("build_code") == "build"


def test_classify_analyze_task(tmp_path: Path) -> None:
    ctx = _context(tmp_path)

    assert ctx.classify_task("proactive_think") == "analyze"


def test_classify_communicate_task(tmp_path: Path) -> None:
    ctx = _context(tmp_path)

    assert ctx.classify_task("ward_room_notification") == "communicate"


def test_classify_diagnose_task(tmp_path: Path) -> None:
    ctx = _context(tmp_path)

    assert ctx.classify_task("diagnose") == "diagnose"


def test_classify_general_default(tmp_path: Path) -> None:
    ctx = _context(tmp_path)

    assert ctx.classify_task("unknown_intent_xyz") == "general"


def test_get_task_orders(tmp_path: Path) -> None:
    (tmp_path / "build.md").write_text("Build-specific orders", encoding="utf-8")
    ctx = _context(tmp_path)

    assert ctx.get_task_orders("build") == "Build-specific orders"


def test_render_task_context(tmp_path: Path) -> None:
    (tmp_path / "build.md").write_text("Build-specific orders", encoding="utf-8")
    ctx = _context(tmp_path)

    rendered = ctx.render_task_context("build")

    assert "## Task Context (build)" in rendered
    assert "Build-specific orders" in rendered


def test_compose_instructions_with_task(tmp_path: Path) -> None:
    (tmp_path / "build.md").write_text("Build-specific orders", encoding="utf-8")
    ctx = _context(tmp_path)
    clear_cache()

    result = compose_instructions(
        "builder",
        "I am the Builder.",
        orders_dir=tmp_path,
        task_type="build",
        task_context=ctx,
    )

    assert "## Task Context (build)" in result
    assert "Build-specific orders" in result


def test_tier_ordering(tmp_path: Path) -> None:
    (tmp_path / "builder.md").write_text("Builder learned rules", encoding="utf-8")
    (tmp_path / "build.md").write_text("Build-specific orders", encoding="utf-8")
    ctx = _context(tmp_path)

    class _FakeDirectiveStore:
        def get_active_for_agent(self, agent_type: str, department: str | None) -> list[object]:
            return [
                SimpleNamespace(
                    directive_type=SimpleNamespace(value="temporary"),
                    content="Active directive text",
                )
            ]

    old_store = standing_orders._directive_store
    try:
        standing_orders._directive_store = _FakeDirectiveStore()
        clear_cache()
        result = compose_instructions(
            "builder",
            "I am the Builder.",
            orders_dir=tmp_path,
            task_type="build",
            task_context=ctx,
        )
    finally:
        standing_orders._directive_store = old_store

    assert result.index("## Personal Standing Orders") < result.index("## Task Context (build)")
    assert result.index("## Task Context (build)") < result.index("## Active Directives")


def test_config_disabled() -> None:
    runtime = SimpleNamespace()
    config = SimpleNamespace(task_context=TaskContextConfig(enabled=False))

    assert _wire_task_context(runtime=runtime, config=config) == 0


def test_missing_task_file_graceful(tmp_path: Path) -> None:
    ctx = _context(tmp_path)

    assert ctx.get_task_orders("nonexistent") == ""


def test_max_tokens_truncation(tmp_path: Path) -> None:
    (tmp_path / "build.md").write_text("abcdef", encoding="utf-8")
    ctx = _context(tmp_path, max_tokens=3)

    assert ctx.get_task_orders("build") == "abc"