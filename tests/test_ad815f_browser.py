"""AD-815f: Playwright runner tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from probos.task_sessions.browser import (
    BrowserTask,
    build_container_command,
    render_script,
    write_script,
)


def test_render_url_mode_contains_goto():
    task = BrowserTask(mode="url", url="https://example.com", instructions="grab")
    script = render_script(task)
    assert "https://example.com" in script
    assert "page.goto" in script
    # mode is baked in as a string literal; URL mode embeds 'url'
    assert "mode = 'url'" in script


def test_render_cdp_mode_connects_over_cdp():
    task = BrowserTask(
        mode="cdp",
        cdp_url="ws://127.0.0.1:9222",
        url="https://example.com",
        instructions="reuse captain's logged-in session",
    )
    script = render_script(task)
    assert "connect_over_cdp" in script
    assert "ws://127.0.0.1:9222" in script


def test_render_url_mode_rejects_missing_url():
    with pytest.raises(ValueError):
        render_script(BrowserTask(mode="url", instructions="x"))


def test_render_cdp_mode_rejects_missing_cdp_url():
    with pytest.raises(ValueError):
        render_script(BrowserTask(mode="cdp", instructions="x"))


def test_render_includes_extra_steps():
    task = BrowserTask(
        mode="url",
        url="https://example.com",
        instructions="login then extract",
        extra_steps=[
            {"op": "fill", "selector": "#user", "value": "alice"},
            {"op": "click", "selector": "button[type=submit]"},
            {"op": "extract", "selector": ".result", "save_as": "result.txt"},
        ],
    )
    script = render_script(task)
    assert '"#user"' in script and "alice" in script
    assert "button[type=submit]" in script
    assert "result.txt" in script


def test_render_capture_flags_respected():
    task = BrowserTask(
        mode="url",
        url="https://example.com",
        instructions="x",
        capture_screenshot=False,
        capture_html=True,
        capture_har=True,
    )
    script = render_script(task)
    # The script has runtime conditionals; the flags are baked in.
    assert "False" in script  # screenshot disabled
    assert "page.content()" in script


def test_write_script_lands_in_scratch(tmp_path):
    task = BrowserTask(mode="url", url="https://example.com", instructions="x")
    path = write_script(task, scratch_dir=tmp_path / "scratch")
    assert path.exists()
    assert path.name == "playwright_task.py"


def test_build_container_command_uses_workspace_path(tmp_path):
    workspace = tmp_path / "ws"
    (workspace / "scratch").mkdir(parents=True)
    script = workspace / "scratch" / "playwright_task.py"
    script.write_text("print(1)\n")
    cmd = build_container_command(script, workspace_mount=workspace)
    assert cmd == ["python", "/workspace/scratch/playwright_task.py"]
