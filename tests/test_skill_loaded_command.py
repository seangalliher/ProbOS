"""BF-292 / AD-728d follow-up: /skill loaded shell subcommand.

Captain asked for a /skill loaded <agent_id> [intent] subcommand so they can
verify which augmentation skills (including self-image-awareness) would load
for a specific agent on a given intent. Mirrors the existing /skill list
shape but takes an agent + intent and filters via find_augmentation_skills.
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from rich.console import Console


def _make_runtime_with_catalog(agent_id: str, *, department: str, rank: str) -> Any:
    """Real catalog (no MagicMock — BF-287) loaded from the live skills dir."""
    from probos.cognitive.skill_catalog import CognitiveSkillCatalog

    catalog = CognitiveSkillCatalog(skills_dir=Path("config/skills"))
    asyncio.run(catalog.scan_and_register())
    # Build agent stub with the structural fields find_augmentation_skills reads.
    agent = SimpleNamespace(
        agent_id=agent_id,
        agent_type="counselor",
        department=department,
        rank=SimpleNamespace(value=rank),
    )
    registry = SimpleNamespace(get=lambda _id: agent if _id == agent_id else None)
    return SimpleNamespace(
        cognitive_skill_catalog=catalog,
        registry=registry,
    )


def _run_cmd(runtime: Any, args: str) -> str:
    """Run /skill <args> and capture the rich console output."""
    from probos.experience.commands.commands_skill import cmd_skill

    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, width=160)
    asyncio.run(cmd_skill(runtime, console, args))
    return buf.getvalue()


def test_skill_loaded_lists_augmentation_skills_for_direct_message() -> None:
    """Self-image-awareness skill (AD-728d) should surface for direct_message."""
    rt = _make_runtime_with_catalog(
        "counselor_counselor_0_test",
        department="medical",
        rank="lieutenant",
    )
    out = _run_cmd(rt, "loaded counselor_counselor_0_test")
    assert "self-image-awareness" in out, (
        f"AD-728d skill must surface for direct_message intent. Output:\n{out}"
    )
    # Also: should include the header showing the resolved department/rank/intent.
    assert "department=medical" in out
    assert "rank=lieutenant" in out
    assert "intent=direct_message" in out


def test_skill_loaded_accepts_explicit_intent() -> None:
    rt = _make_runtime_with_catalog(
        "counselor_counselor_0_test",
        department="medical",
        rank="lieutenant",
    )
    out = _run_cmd(rt, "loaded counselor_counselor_0_test ward_room_notification")
    assert "intent=ward_room_notification" in out
    # self-image-awareness declares ward_room_notification as a load intent.
    assert "self-image-awareness" in out


def test_skill_loaded_unknown_agent_reports_clearly() -> None:
    rt = _make_runtime_with_catalog(
        "real_id", department="ops", rank="ensign",
    )
    out = _run_cmd(rt, "loaded missing_id")
    assert "Agent not found: missing_id" in out


def test_skill_loaded_usage_shown_when_no_args() -> None:
    rt = _make_runtime_with_catalog(
        "any", department="ops", rank="ensign",
    )
    out = _run_cmd(rt, "loaded")
    assert "Usage: /skill loaded <agent_id> [intent]" in out
    assert "Default intent: direct_message" in out


def test_skill_loaded_advertised_in_top_level_usage() -> None:
    """The unknown-subcommand help text must mention the new 'loaded' verb."""
    rt = _make_runtime_with_catalog(
        "any", department="ops", rank="ensign",
    )
    out = _run_cmd(rt, "")
    assert "loaded" in out, (
        "Top-level /skill usage must advertise the new 'loaded' subcommand."
    )
