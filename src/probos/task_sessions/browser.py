"""AD-815f: Playwright runner for TaskSessions.

Generates a Playwright script the agent can run inside the AD-815d
cowork-base container. Two modes:

* **URL mode** — Captain pastes a URL; the agent navigates headless
  Chromium in the container, captures screenshot + HTML + (optionally)
  HAR, and writes them to ``{session.root_dir}/outputs/``.
* **CDP mode** — Captain shares a browser by exposing a Playwright CDP
  endpoint (default ``ws://127.0.0.1:9222``); the container connects
  via ``playwright.connect_over_cdp(url)`` and uses the Captain's
  logged-in session. v1 supports the connection plumbing; OAuth-style
  cookie copy is operator's responsibility (forward marker AD-815f-a).

The runner does not execute Playwright in-process — Playwright lives in
the cowork-base image. The runner emits a ``BrowserTask`` value object
that the AD-815a TaskSession run pipeline wraps into a
``ContainerExec`` (AD-798).
"""

from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

BrowserMode = Literal["url", "cdp"]


@dataclass(frozen=True)
class BrowserTask:
    """Description of a single Playwright run inside a TaskSession."""

    mode: BrowserMode
    instructions: str
    url: str | None = None
    cdp_url: str | None = None
    capture_screenshot: bool = True
    capture_html: bool = True
    capture_har: bool = False
    extra_steps: list[dict] = field(default_factory=list)


def render_script(task: BrowserTask) -> str:
    """Render the Playwright script that executes ``task``.

    The script reads ``/workspace/outputs`` (mounted from the
    TaskSession root) and writes screenshots / HTML / HAR there. It is
    intentionally synchronous; the agent reads stdout / outputs/* on
    completion.
    """
    if task.mode == "url" and not task.url:
        raise ValueError("URL mode requires a url")
    if task.mode == "cdp" and not task.cdp_url:
        raise ValueError("CDP mode requires a cdp_url")

    extra_json = json.dumps(task.extra_steps)
    body = textwrap.dedent(
        f"""
        from __future__ import annotations

        import json
        from pathlib import Path
        from playwright.sync_api import sync_playwright

        OUTPUTS = Path("/workspace/outputs")
        OUTPUTS.mkdir(parents=True, exist_ok=True)
        EXTRA_STEPS = {extra_json}

        def run_steps(page) -> None:
            for step in EXTRA_STEPS:
                op = step.get("op")
                if op == "click":
                    page.click(step["selector"])
                elif op == "fill":
                    page.fill(step["selector"], step.get("value", ""))
                elif op == "wait":
                    page.wait_for_selector(step["selector"], timeout=step.get("timeout", 5000))
                elif op == "extract":
                    text = page.locator(step["selector"]).inner_text()
                    Path("/workspace/outputs", step.get("save_as", "extract.txt")).write_text(text, encoding="utf-8")

        with sync_playwright() as p:
            mode = {task.mode!r}
            if mode == "cdp":
                browser = p.chromium.connect_over_cdp({task.cdp_url!r})
                context = browser.contexts[0] if browser.contexts else browser.new_context()
                page = context.pages[0] if context.pages else context.new_page()
                page.goto({(task.url or "about:blank")!r})
            else:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context()
                page = context.new_page()
                page.goto({task.url!r})
            try:
                run_steps(page)
                if {task.capture_screenshot!r}:
                    page.screenshot(path=str(OUTPUTS / "screenshot.png"), full_page=True)
                if {task.capture_html!r}:
                    (OUTPUTS / "page.html").write_text(page.content(), encoding="utf-8")
                if {task.capture_har!r} and mode != "cdp":
                    # HAR requires a context option; record once and dump on close.
                    har_path = OUTPUTS / "session.har"
                    # Best-effort: re-create page with HAR recording.
                    har_context = browser.new_context(record_har_path=str(har_path))
                    har_page = har_context.new_page()
                    har_page.goto({task.url!r})
                    har_context.close()
                print(json.dumps({{"status": "ok", "instructions": {task.instructions!r}}}))
            finally:
                if mode == "cdp":
                    browser.close()
                else:
                    context.close()
                    browser.close()
        """
    ).strip()
    return body + "\n"


def write_script(task: BrowserTask, *, scratch_dir: Path) -> Path:
    """Write the rendered script into the TaskSession's scratch dir."""
    scratch_dir.mkdir(parents=True, exist_ok=True)
    path = scratch_dir / "playwright_task.py"
    path.write_text(render_script(task), encoding="utf-8")
    return path


def build_container_command(
    script_path: Path, *, workspace_mount: Path
) -> list[str]:
    """Build the command ContainerSandbox runs (``python /workspace/...``)."""
    # The TaskSession root is mounted at /workspace inside the container, so
    # the script lives at /workspace/scratch/playwright_task.py.
    relative = script_path.relative_to(workspace_mount)
    return ["python", f"/workspace/{relative.as_posix()}"]
