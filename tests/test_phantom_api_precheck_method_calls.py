"""AD-685b: Method-name phantom-API validation tests.

Covers:
- Historical-phantom regressions (LLMClient.chat, WorkItemStore.add,
  event_log.query event_type).
- Pattern A class resolution (AnnAssign in runtime.py priority 1;
  Assign+Call in finalize.py priority 2).
- Pattern B class resolution (var = Class(...) in prompt body).
- Conservative skip on unresolved class.
- Sync + async method walking; dunder exclusion.
- PowerShell wrapper integration (method_phantom category prefix).
- Recursive-validity self-check on AD-685b's own prompt.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).parent.parent
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
sys.path.insert(0, str(_SCRIPTS_DIR))
import phantom_api_ast_helper as helper  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_helper_caches():
    """Ensure each test starts with a clean module-level cache."""
    helper._INDEX_CACHE.clear()
    helper._CLASS_METHODS_CACHE.clear()
    helper._RUNTIME_ATTRS_CACHE.clear()
    helper._RUNTIME_CONFLICTS_CACHE.clear()
    yield
    helper._INDEX_CACHE.clear()
    helper._CLASS_METHODS_CACHE.clear()
    helper._RUNTIME_ATTRS_CACHE.clear()
    helper._RUNTIME_CONFLICTS_CACHE.clear()


def _make_src_tree(root: Path, files: dict[str, str]) -> Path:
    """Materialize a fake src tree at root/probos and return its path."""
    src = root / "probos"
    src.mkdir(parents=True, exist_ok=True)
    for relpath, content in files.items():
        target = src / relpath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return src


def _run_method_check(body: str, src: Path) -> tuple[list[dict], list[dict]]:
    class_methods = helper.build_class_method_index(src)
    attrs, conflicts = helper.build_runtime_attr_index(src)
    pb_vars, pb_unresolved = helper._resolve_pattern_b(body)
    return helper.find_method_phantoms(
        body, class_methods, attrs, conflicts, pb_vars, pb_unresolved,
    )


def test_helper_catches_llmclient_chat_phantom(tmp_path):
    """Wave 14 regression: LLMClient.chat doesn't exist (real: complete)."""
    src = _make_src_tree(tmp_path, {
        "cognitive/llm_client.py": (
            "class LLMClient:\n"
            "    async def complete(self, request): pass\n"
        ),
        "runtime.py": (
            "class ProbOSRuntime:\n"
            "    def __init__(self):\n"
            "        self.llm_client: LLMClient = LLMClient()\n"
        ),
    })
    body = "result = await runtime.llm_client.chat(prompt='hi')\n"

    phantoms, unresolved = _run_method_check(body, src)

    methods = [p for p in phantoms if p.get("category") == "method_phantom"]
    assert len(methods) == 1
    assert methods[0]["method"] == "chat"
    assert methods[0]["resolved_class"] == "LLMClient"
    assert methods[0]["obj"] == "runtime.llm_client"
    assert "complete" in methods[0]["candidates_at"]


def test_helper_catches_workitemstore_add_phantom(tmp_path):
    """Wave 10 regression: WorkItemStore.add doesn't exist (real: create_work_item)."""
    src = _make_src_tree(tmp_path, {
        "workforce.py": (
            "class WorkItemStore:\n"
            "    async def create_work_item(self, **kwargs): pass\n"
        ),
        "runtime.py": (
            "class ProbOSRuntime:\n"
            "    def __init__(self):\n"
            "        self.work_item_store: WorkItemStore = WorkItemStore()\n"
        ),
    })
    body = "await runtime.work_item_store.add(work_item)\n"

    phantoms, _ = _run_method_check(body, src)

    methods = [p for p in phantoms if p.get("category") == "method_phantom"]
    assert len(methods) == 1
    assert methods[0]["method"] == "add"
    assert methods[0]["resolved_class"] == "WorkItemStore"


def test_helper_catches_event_log_query_phantom(tmp_path):
    """Wave 9B framing regression: synthetic case where `query` is absent on EventLog (only `query_structured`)."""
    src = _make_src_tree(tmp_path, {
        "substrate/event_log.py": (
            "class EventLog:\n"
            "    async def query_structured(self, **kwargs): pass\n"
            "    async def log(self, **kwargs): pass\n"
        ),
        "runtime.py": (
            "class ProbOSRuntime:\n"
            "    def __init__(self):\n"
            "        self.event_log: EventLog = EventLog()\n"
        ),
    })
    body = "rows = await runtime.event_log.query(category='audit')\n"

    phantoms, _ = _run_method_check(body, src)

    methods = [p for p in phantoms if p.get("category") == "method_phantom"]
    assert len(methods) == 1
    assert methods[0]["method"] == "query"
    assert methods[0]["resolved_class"] == "EventLog"
    assert "query_structured" in methods[0]["candidates_at"]


def test_helper_skips_unresolvable_class_no_false_positive(tmp_path):
    """Conservative skip: class not registered → emit `no_class_resolution` unresolved record, no phantom flag."""
    src = _make_src_tree(tmp_path, {
        "runtime.py": "class ProbOSRuntime:\n    def __init__(self):\n        pass\n",
    })
    body = "await runtime.mystery_service.foo(bar=1)\n"

    phantoms, unresolved = _run_method_check(body, src)

    assert all(p.get("category") != "method_phantom" for p in phantoms)
    assert len(unresolved) == 1
    assert unresolved[0]["reason"] == "no_class_resolution"
    assert unresolved[0]["obj"] == "runtime.mystery_service"


def test_helper_resolves_runtime_attribute_via_annassign_in_runtime_py(tmp_path):
    """Pattern A priority 1: AnnAssign in runtime.py wins over conflicting Assign+Call signals."""
    src = _make_src_tree(tmp_path, {
        "service.py": (
            "class RealService:\n"
            "    def real_method(self): pass\n"
            "class FakeService:\n"
            "    def fake_method(self): pass\n"
        ),
        "runtime.py": (
            "class ProbOSRuntime:\n"
            "    def __init__(self):\n"
            "        self.svc: RealService = RealService()\n"
            "        self.svc = FakeService()\n"
        ),
    })

    attrs, conflicts = helper.build_runtime_attr_index(src)

    assert "svc" in attrs
    assert attrs["svc"] == "RealService"
    assert "svc" not in conflicts


def test_helper_resolves_runtime_attribute_via_finalize_py_assignment(tmp_path):
    """Pattern A priority 2: when no AnnAssign exists in runtime.py, Assign+Call in finalize.py resolves the class."""
    src = _make_src_tree(tmp_path, {
        "service.py": (
            "class CompService:\n"
            "    def perform(self): pass\n"
        ),
        "runtime.py": "class ProbOSRuntime:\n    def __init__(self):\n        pass\n",
        "startup/finalize.py": (
            "def finalize(runtime):\n"
            "    runtime.comp = CompService()\n"
        ),
    })

    attrs, conflicts = helper.build_runtime_attr_index(src)

    assert attrs.get("comp") == "CompService"
    assert "comp" not in conflicts


def test_helper_resolves_constructor_assignment_in_prompt(tmp_path):
    """Pattern B: `<var> = SomeClass(...)` in prompt body resolves var to that class for subsequent calls."""
    src = _make_src_tree(tmp_path, {
        "things.py": (
            "class Widget:\n"
            "    def spin(self): pass\n"
        ),
        "runtime.py": "class ProbOSRuntime:\n    def __init__(self):\n        pass\n",
    })
    body = (
        "thing = Widget()\n"
        "thing.warble(speed=3)\n"
    )

    phantoms, _ = _run_method_check(body, src)

    methods = [p for p in phantoms if p.get("category") == "method_phantom"]
    assert len(methods) == 1
    assert methods[0]["method"] == "warble"
    assert methods[0]["resolved_class"] == "Widget"


def test_helper_walks_async_and_sync_methods(tmp_path):
    """Class method index must include both `def` and `async def` definitions."""
    src = _make_src_tree(tmp_path, {
        "mixed.py": (
            "class Mixed:\n"
            "    def sync_one(self): pass\n"
            "    async def async_one(self): pass\n"
        ),
    })

    class_methods = helper.build_class_method_index(src)

    assert "Mixed" in class_methods
    assert class_methods["Mixed"] == {"sync_one", "async_one"}


def test_helper_class_method_set_excludes_dunders(tmp_path):
    """Dunders are infrastructure (not user-callable phantoms) — excluded from the method set."""
    src = _make_src_tree(tmp_path, {
        "cls.py": (
            "class Sample:\n"
            "    def __init__(self): pass\n"
            "    def __repr__(self): return ''\n"
            "    def public(self): pass\n"
            "    def _private(self): pass\n"
        ),
    })

    class_methods = helper.build_class_method_index(src)

    assert class_methods["Sample"] == {"public", "_private"}


def test_powershell_wrapper_displays_method_phantom_category(tmp_path):
    """Integration: PowerShell wrapper output renders [method_phantom] prefix and Skipped section."""
    prompt = tmp_path / "synthetic.md"
    prompt.write_text(
        "# Synthetic prompt\n\n"
        "```python\n"
        "import asyncio\n"
        "async def main(runtime):\n"
        "    await runtime.llm_client.chat(prompt='hi')\n"
        "    await runtime.unknown_thing.do_stuff()\n"
        "```\n",
        encoding="utf-8",
    )

    wrapper = _REPO_ROOT / "scripts" / "phantom-api-precheck.ps1"
    proc = subprocess.run(
        [
            "pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(wrapper), str(prompt),
        ],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        timeout=120,
    )
    combined = (proc.stdout or "") + (proc.stderr or "")

    # Wrapper displays the new category prefix on the LLMClient.chat phantom.
    assert "method_phantom" in combined, combined
    assert "LLMClient.chat" in combined, combined
    # Wrapper renders the Skipped section for the unresolved runtime.X access.
    assert "Skipped" in combined, combined
    assert "no_class_resolution" in combined, combined


def test_recursive_validity_ad685b_prompt_clean():
    """Recursive validity: AD-685b prompt itself produces 0 NEW method_phantom flags via extended pre-check.

    The wrapper's existing AD-685 v1 checks may surface 1-2 documented
    runtime.X / class:* false positives from the prompt's audit prose
    (architect-acknowledged in dispatch). This test asserts no NEW
    method_phantom flags introduced by Section 1.
    """
    # Prompt path: lives in prompts/ during active wave, then archived to
    # prompts/archive/ post-wave. Check both locations to keep test stable
    # across wave-archive lifecycle.
    candidates = [
        _REPO_ROOT / "prompts" / "ad-685b-method-call-validation.md",
        _REPO_ROOT / "prompts" / "archive" / "ad-685b-method-call-validation.md",
    ]
    prompt = next((p for p in candidates if p.is_file()), candidates[0])
    assert prompt.is_file(), f"AD-685b prompt missing in prompts/ or prompts/archive/"

    src_root = _REPO_ROOT / "src" / "probos"
    body = prompt.read_text(encoding="utf-8")

    proc = subprocess.run(
        [
            sys.executable,
            str(_SCRIPTS_DIR / "phantom_api_ast_helper.py"),
            "--src-root", str(src_root),
        ],
        input=body,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(_REPO_ROOT),
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr

    parsed = json.loads(proc.stdout)
    method_phantoms = [
        p for p in parsed.get("phantoms", [])
        if p.get("category") == "method_phantom"
    ]
    assert method_phantoms == [], (
        f"AD-685b prompt introduces method_phantom flags: {method_phantoms}"
    )
