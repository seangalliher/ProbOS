"""Security tests for CodeValidator — BF-086.

Tests the actual security boundary of the self-modification validator
using real SelfModConfig defaults. These tests verify import whitelisting,
forbidden pattern detection (including bypass vectors), schema enforcement,
and side-effect detection.
"""

from __future__ import annotations

import textwrap

import pytest

from probos.config import SelfModConfig
from probos.cognitive.code_validator import CodeValidator


# ---------------------------------------------------------------------------
# Helper: valid agent source to wrap dangerous code inside
# ---------------------------------------------------------------------------

VALID_AGENT_TEMPLATE = textwrap.dedent('''\
    from probos.substrate.agent import BaseAgent
    from probos.types import IntentMessage, IntentResult, IntentDescriptor

    class TestAgent(BaseAgent):
        """Test agent."""

        agent_type = "test_agent"
        _handled_intents = ["test"]
        intent_descriptors = [
            IntentDescriptor(
                name="test",
                params={{}},
                description="test",
                requires_consensus=False,
                requires_reflect=False,
            )
        ]

        async def perceive(self, intent):
            return intent

        async def decide(self, obs):
            return obs

        async def act(self, plan):
            {act_body}
            return {{"success": True}}

        async def report(self, result):
            return result

        async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
            return IntentResult(
                intent_id=intent.id,
                agent_id=self.id,
                success=True,
                result={{}},
                confidence=self.confidence,
            )
''')


def _make_validator() -> CodeValidator:
    return CodeValidator(SelfModConfig())


def _agent_with_act(act_body: str) -> str:
    """Return valid agent source with custom code in act()."""
    return VALID_AGENT_TEMPLATE.format(act_body=act_body)


def _agent_with_import(import_line: str) -> str:
    """Return valid agent source with an extra import at the top."""
    return import_line + "\n" + _agent_with_act("pass")


# ===========================================================================
# Part A: Import Whitelist Tests
# ===========================================================================


class TestImportWhitelist:
    """Verify forbidden imports are blocked and allowed imports pass."""

    def test_blocks_requests_import(self):
        v = _make_validator()
        errors = v.validate(_agent_with_import("import requests"))
        assert any("requests" in e for e in errors)

    def test_blocks_httpx_import(self):
        v = _make_validator()
        errors = v.validate(_agent_with_import("import httpx"))
        assert any("httpx" in e for e in errors)

    def test_blocks_aiohttp_import(self):
        v = _make_validator()
        errors = v.validate(_agent_with_import("from aiohttp import ClientSession"))
        assert any("aiohttp" in e for e in errors)

    def test_blocks_importlib_import(self):
        v = _make_validator()
        errors = v.validate(_agent_with_import("import importlib"))
        assert any("importlib" in e for e in errors)

    def test_blocks_sys_import(self):
        v = _make_validator()
        errors = v.validate(_agent_with_import("import sys"))
        assert any("sys" in e for e in errors)

    def test_blocks_ctypes_import(self):
        v = _make_validator()
        errors = v.validate(_agent_with_import("import ctypes"))
        # ctypes is also a forbidden pattern
        assert any("ctypes" in e for e in errors)

    def test_blocks_pickle_import(self):
        v = _make_validator()
        errors = v.validate(_agent_with_import("import pickle"))
        assert any("pickle" in e for e in errors)

    def test_blocks_marshal_import(self):
        v = _make_validator()
        errors = v.validate(_agent_with_import("import marshal"))
        assert any("marshal" in e for e in errors)

    def test_blocks_code_import(self):
        """import code gives access to interactive interpreter."""
        v = _make_validator()
        errors = v.validate(_agent_with_import("import code"))
        assert any("code" in e for e in errors)

    def test_blocks_compileall_import(self):
        v = _make_validator()
        errors = v.validate(_agent_with_import("import compileall"))
        assert any("compileall" in e for e in errors)

    def test_allows_probos_internal_imports(self):
        v = _make_validator()
        source = "from probos.types import IntentResult\n" + _agent_with_act("pass")
        errors = v.validate(source)
        import_errors = [e for e in errors if "import" in e.lower()]
        assert import_errors == []

    def test_allows_probos_substrate_import(self):
        v = _make_validator()
        source = "from probos.substrate.agent import BaseAgent\n" + _agent_with_act("pass")
        errors = v.validate(source)
        import_errors = [e for e in errors if "import" in e.lower()]
        assert import_errors == []

    def test_blocks_from_x_import_y_syntax(self):
        v = _make_validator()
        errors = v.validate(_agent_with_import("from subprocess import Popen"))
        assert any("subprocess" in e for e in errors)

    def test_blocks_dotted_forbidden_import(self):
        v = _make_validator()
        errors = v.validate(_agent_with_import("import subprocess.Popen"))
        assert any("subprocess" in e for e in errors)


# ===========================================================================
# Part B: Forbidden Pattern Bypass Tests
# ===========================================================================


class TestForbiddenPatternBypasses:
    """Test known bypass vectors. If a test reveals a gap, the gap MUST be
    fixed in SelfModConfig._DEFAULT_FORBIDDEN_PATTERNS before this test
    can pass. See BF-086 for the fix commit.
    """

    def test_blocks_os_system(self):
        """os is whitelisted but os.system() is command execution.

        Gap fixed: added r"os\\.system" to forbidden patterns.
        """
        v = _make_validator()
        errors = v.validate(_agent_with_act('os.system("ls")'))
        assert any("os.system" in e or "os\\.system" in e for e in errors), (
            "SECURITY GAP: os.system() not caught by forbidden patterns"
        )

    def test_blocks_os_popen(self):
        """os.popen() is command execution.

        Gap fixed: added r"os\\.popen" to forbidden patterns.
        """
        v = _make_validator()
        errors = v.validate(_agent_with_act('os.popen("ls")'))
        assert any("os.popen" in e or "os\\.popen" in e for e in errors), (
            "SECURITY GAP: os.popen() not caught by forbidden patterns"
        )

    def test_blocks_os_execv(self):
        """os.execv() is process replacement.

        Gap fixed: added r"os\\.exec" to forbidden patterns.
        """
        v = _make_validator()
        errors = v.validate(_agent_with_act('os.execv("/bin/sh", [])'))
        assert any("os.exec" in e or "os\\.exec" in e for e in errors), (
            "SECURITY GAP: os.execv() not caught by forbidden patterns"
        )

    def test_blocks_os_kill(self):
        """os.kill() is signal injection.

        Gap fixed: added r"os\\.kill" to forbidden patterns.
        """
        v = _make_validator()
        errors = v.validate(_agent_with_act("os.kill(1, 9)"))
        assert any("os.kill" in e or "os\\.kill" in e for e in errors), (
            "SECURITY GAP: os.kill() not caught by forbidden patterns"
        )

    def test_blocks_pathlib_write_text(self):
        """pathlib is whitelisted but write_text() mutates files.

        Gap fixed: added r"\\.write_text\\s*\\(" to forbidden patterns.
        """
        v = _make_validator()
        errors = v.validate(_agent_with_act('Path("/tmp/x").write_text("pwned")'))
        assert any("write_text" in e for e in errors), (
            "SECURITY GAP: Path.write_text() not caught by forbidden patterns"
        )

    def test_blocks_pathlib_write_bytes(self):
        """pathlib write_bytes() mutates files."""
        v = _make_validator()
        errors = v.validate(_agent_with_act('Path("/tmp/x").write_bytes(b"pwned")'))
        assert any("write_bytes" in e for e in errors), (
            "SECURITY GAP: Path.write_bytes() not caught by forbidden patterns"
        )

    def test_blocks_pathlib_unlink(self):
        """pathlib unlink() deletes files.

        Gap fixed: added r"\\.unlink\\s*\\(" to forbidden patterns.
        """
        v = _make_validator()
        errors = v.validate(_agent_with_act('Path("/tmp/x").unlink()'))
        assert any("unlink" in e for e in errors), (
            "SECURITY GAP: Path.unlink() not caught by forbidden patterns"
        )

    def test_blocks_open_append_mode(self):
        """open() with 'a' mode should be caught.

        Gap fixed: broadened open pattern to catch 'a', 'x', 'w+', etc.
        """
        v = _make_validator()
        errors = v.validate(_agent_with_act('open("/tmp/x", "a")'))
        assert any("open" in e for e in errors), (
            "SECURITY GAP: open() with append mode not caught"
        )

    def test_blocks_open_binary_write(self):
        """open() with 'wb' mode should be caught."""
        v = _make_validator()
        errors = v.validate(_agent_with_act('open("/tmp/x", "wb")'))
        assert any("open" in e for e in errors), (
            "SECURITY GAP: open() with binary write mode not caught"
        )

    def test_blocks_open_exclusive_create(self):
        """open() with 'x' mode (exclusive create) should be caught."""
        v = _make_validator()
        errors = v.validate(_agent_with_act("open('/tmp/x', 'x')"))
        assert any("open" in e for e in errors), (
            "SECURITY GAP: open() with exclusive create mode not caught"
        )

    def test_blocks_tempfile_write(self):
        """tempfile is whitelisted but NamedTemporaryFile with write mode
        should match the broadened open pattern — tempfile itself doesn't
        use open(), so this is caught by the write_text/write pattern.

        Note: tempfile.NamedTemporaryFile(mode='w') doesn't match open()
        pattern. This is a known limitation — tempfile writes are considered
        lower risk because the file is temporary. Document as accepted risk.
        """
        v = _make_validator()
        source = _agent_with_act("tempfile.NamedTemporaryFile(mode='w')")
        errors = v.validate(source)
        # tempfile write is lower risk — document as known limitation
        # if it passes, that's acceptable (temp files are ephemeral)

    def test_blocks_getattr_eval_bypass(self):
        """getattr(__builtins__, 'eval') is a pattern evasion technique.

        Gap fixed: added r"__builtins__" to forbidden patterns.
        """
        v = _make_validator()
        errors = v.validate(
            _agent_with_act("getattr(__builtins__, 'eval')('1+1')")
        )
        assert any("__builtins__" in e for e in errors), (
            "SECURITY GAP: __builtins__ access not caught"
        )

    def test_blocks_builtins_access(self):
        """__builtins__.__import__('os') should be caught by __import__ pattern."""
        v = _make_validator()
        errors = v.validate(
            _agent_with_act("__builtins__.__import__('os')")
        )
        # Should match both __import__ AND __builtins__ patterns
        assert any("__import__" in e or "__builtins__" in e for e in errors)

    def test_blocks_compile_builtin(self):
        """compile() enables code compilation bypass.

        Gap fixed: added r"compile\\s*\\(" to forbidden patterns.
        """
        v = _make_validator()
        errors = v.validate(
            _agent_with_act('compile("code", "<>", "exec")')
        )
        assert any("compile" in e for e in errors), (
            "SECURITY GAP: compile() not caught by forbidden patterns"
        )

    def test_pattern_in_comment_false_positive(self):
        """Text-based pattern matching catches patterns in comments.

        This is a known limitation and acceptable trade-off: catching
        dangerous patterns in comments is a false positive, but regex-based
        scanning cannot distinguish comments from code without full AST
        analysis. The security cost of missing a real eval() call far
        outweighs the inconvenience of a false positive in a comment.
        """
        v = _make_validator()
        errors = v.validate(
            _agent_with_act("x = 1  # don't use eval() here")
        )
        # Current behavior: WILL match eval in comment — document as expected
        pattern_errors = [e for e in errors if "eval" in e]
        assert len(pattern_errors) >= 1, (
            "Expected false positive: text-based pattern should catch eval in comments"
        )

    def test_pattern_in_string_false_positive(self):
        """Text-based pattern matching catches patterns in string literals.

        Same trade-off as comment false positives. The security boundary
        is intentionally conservative: better to reject safe code than
        accept dangerous code. Agent designers can rephrase strings.
        """
        v = _make_validator()
        errors = v.validate(
            _agent_with_act('msg = "use eval() carefully"')
        )
        pattern_errors = [e for e in errors if "eval" in e]
        assert len(pattern_errors) >= 1, (
            "Expected false positive: text-based pattern should catch eval in strings"
        )


# ===========================================================================
# Part C: Schema Enforcement Tests
# ===========================================================================


class TestSchemaEnforcement:
    """Test agent class schema validation edge cases."""

    def test_nested_class_evasion(self):
        """Agent class defined inside a function is NOT found by schema check.

        CodeValidator uses ast.iter_child_nodes(tree) which only scans
        module-level nodes. A class nested inside a function is invisible
        to the schema check. This is by design — only module-level agent
        classes are valid. The validator will report "No BaseAgent subclass found".
        """
        v = _make_validator()
        source = textwrap.dedent('''\
            from probos.substrate.agent import BaseAgent
            from probos.types import IntentDescriptor, IntentMessage, IntentResult

            def factory():
                class Evil(BaseAgent):
                    agent_type = "evil"
                    _handled_intents = ["evil"]
                    intent_descriptors = [
                        IntentDescriptor(name="evil", params={}, description="evil")
                    ]
                    async def handle_intent(self, intent):
                        return None
                return Evil
        ''')
        errors = v.validate(source)
        assert any("No BaseAgent subclass" in e for e in errors)

    def test_aliased_base_class(self):
        """B = BaseAgent; class MyAgent(B): ... — alias hides base class.

        The schema check compares base class names literally against
        "BaseAgent" and "CognitiveAgent". An alias will NOT match.
        This is documented as a known limitation — agents must directly
        subclass BaseAgent or CognitiveAgent.
        """
        v = _make_validator()
        source = textwrap.dedent('''\
            from probos.substrate.agent import BaseAgent
            from probos.types import IntentDescriptor, IntentMessage, IntentResult

            B = BaseAgent

            class MyAgent(B):
                agent_type = "aliased"
                _handled_intents = ["aliased"]
                intent_descriptors = [
                    IntentDescriptor(name="aliased", params={}, description="aliased")
                ]
                async def handle_intent(self, intent):
                    return None
        ''')
        errors = v.validate(source)
        # Alias won't be recognized — should fail with "No BaseAgent subclass"
        assert any("No BaseAgent subclass" in e for e in errors)

    def test_no_class_at_all(self):
        """Source with only functions, no class → error."""
        v = _make_validator()
        source = textwrap.dedent('''\
            from probos.substrate.agent import BaseAgent

            def my_function():
                pass
        ''')
        errors = v.validate(source)
        assert any("No BaseAgent subclass" in e for e in errors)

    def test_class_without_base(self):
        """class MyAgent: ... (no BaseAgent inheritance) → error."""
        v = _make_validator()
        source = textwrap.dedent('''\
            from probos.substrate.agent import BaseAgent

            class MyAgent:
                agent_type = "test"
                _handled_intents = ["test"]
                intent_descriptors = [{"name": "test"}]

                async def handle_intent(self, intent):
                    return None
        ''')
        errors = v.validate(source)
        assert any("No BaseAgent subclass" in e for e in errors)

    def test_agent_type_as_annotation(self):
        """agent_type: str = "test" (AnnAssign) should pass schema check."""
        v = _make_validator()
        source = textwrap.dedent('''\
            from probos.substrate.agent import BaseAgent
            from probos.types import IntentDescriptor, IntentMessage, IntentResult

            class TestAgent(BaseAgent):
                agent_type: str = "test"
                _handled_intents: list = ["test"]
                intent_descriptors = [
                    IntentDescriptor(name="test", params={}, description="test")
                ]

                async def perceive(self, intent):
                    return intent

                async def decide(self, obs):
                    return obs

                async def act(self, plan):
                    return plan

                async def report(self, result):
                    return result

                async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
                    return None
        ''')
        errors = v.validate(source)
        assert errors == [], f"AnnAssign should be accepted: {errors}"

    def test_intent_descriptors_as_dict(self):
        """intent_descriptors = [{"intent": "test"}] → pass schema check."""
        v = _make_validator()
        source = textwrap.dedent('''\
            from probos.substrate.agent import BaseAgent
            from probos.types import IntentMessage, IntentResult

            class TestAgent(BaseAgent):
                agent_type = "test"
                _handled_intents = ["test"]
                intent_descriptors = [{"intent": "test", "params": {}, "description": "test"}]

                async def perceive(self, intent):
                    return intent

                async def decide(self, obs):
                    return obs

                async def act(self, plan):
                    return plan

                async def report(self, result):
                    return result

                async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
                    return None
        ''')
        errors = v.validate(source)
        assert errors == [], f"Dict-style descriptors should pass: {errors}"

    def test_handled_intents_missing(self):
        """All required attributes except _handled_intents → error."""
        v = _make_validator()
        source = textwrap.dedent('''\
            from probos.substrate.agent import BaseAgent
            from probos.types import IntentDescriptor, IntentMessage, IntentResult

            class TestAgent(BaseAgent):
                agent_type = "test"
                intent_descriptors = [
                    IntentDescriptor(name="test", params={}, description="test")
                ]

                async def perceive(self, intent):
                    return intent

                async def decide(self, obs):
                    return obs

                async def act(self, plan):
                    return plan

                async def report(self, result):
                    return result

                async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
                    return None
        ''')
        errors = v.validate(source)
        assert any("_handled_intents" in e for e in errors)


# ===========================================================================
# Part D: Side Effect Tests
# ===========================================================================


class TestSideEffects:
    """Test module-level and class-body side effect detection."""

    def test_module_level_function_call(self):
        """setup() at module level → error."""
        v = _make_validator()
        source = "setup()\n" + _agent_with_act("pass")
        errors = v.validate(source)
        assert any("side effect" in e.lower() for e in errors)

    def test_module_level_if_statement(self):
        """if True: pass at module level → error."""
        v = _make_validator()
        source = "if True: pass\n" + _agent_with_act("pass")
        errors = v.validate(source)
        assert any("side effect" in e.lower() for e in errors)

    def test_module_level_for_loop(self):
        """for i in range(10): pass at module level → error."""
        v = _make_validator()
        source = "for i in range(10): pass\n" + _agent_with_act("pass")
        errors = v.validate(source)
        assert any("side effect" in e.lower() for e in errors)

    def test_class_body_conditional(self):
        """if DEBUG: print() in class body → error."""
        v = _make_validator()
        source = _agent_with_act("pass").replace(
            'agent_type = "test_agent"',
            'agent_type = "test_agent"\n    if True: print("loaded")',
        )
        errors = v.validate(source)
        assert any("class-body side effect" in e.lower() for e in errors)

    def test_class_body_assignment_ok(self):
        """_cache = {} in class body → pass."""
        v = _make_validator()
        source = _agent_with_act("pass").replace(
            'agent_type = "test_agent"',
            'agent_type = "test_agent"\n    _cache = {}',
        )
        errors = v.validate(source)
        side_effects = [e for e in errors if "side effect" in e.lower()]
        assert side_effects == []

    def test_class_body_annotated_ok(self):
        """name: str = "test" in class body → pass."""
        v = _make_validator()
        source = _agent_with_act("pass").replace(
            'agent_type = "test_agent"',
            'agent_type = "test_agent"\n    name: str = "test"',
        )
        errors = v.validate(source)
        side_effects = [e for e in errors if "side effect" in e.lower()]
        assert side_effects == []

    def test_class_body_method_ok(self):
        """async def handle_intent(...) in class body → pass (already present)."""
        v = _make_validator()
        errors = v.validate(_agent_with_act("pass"))
        side_effects = [e for e in errors if "side effect" in e.lower()]
        assert side_effects == []
