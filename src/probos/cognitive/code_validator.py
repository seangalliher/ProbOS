"""CodeValidator — static analysis of generated agent code for safety."""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.config import SelfModConfig


class CodeValidationError(Exception):
    """Raised when generated code fails validation."""
    pass


class CodeValidator:
    """Statically validates generated agent code for safety.

    Checks:
    1. Syntax validity (ast.parse)
    2. Forbidden imports (not in allowed_imports whitelist)
    3. Forbidden patterns (regex match against source)
    4. Schema conformance (has BaseAgent subclass, has intent_descriptors,
       has handle_intent method)
    5. No module-level side effects (no bare function calls at module level
       except class/function definitions and assignments)
    """

    def __init__(self, config: SelfModConfig) -> None:
        self._allowed_imports = set(config.allowed_imports)
        # Also allow probos imports (needed for agent code)
        self._allowed_imports.update([
            "probos", "probos.substrate.agent", "probos.types",
        ])
        self._forbidden_patterns = config.forbidden_patterns

    def validate(self, source_code: str) -> list[str]:
        """Validate source code. Returns list of error strings.

        Empty list = validation passed.
        """
        errors: list[str] = []

        # 1. Syntax check
        syntax_errors = self._check_syntax(source_code)
        if syntax_errors:
            return syntax_errors  # Can't do AST analysis on invalid syntax

        tree = ast.parse(source_code)

        # 2. Import whitelist
        errors.extend(self._check_imports(tree))

        # 3. Forbidden patterns
        errors.extend(self._check_forbidden_patterns(source_code))

        # 4. Schema conformance
        errors.extend(self._check_schema(tree))

        # 5. Module-level side effects
        errors.extend(self._check_module_side_effects(tree))

        return errors

    def _check_syntax(self, source_code: str) -> list[str]:
        """Parse with ast.parse(). Returns errors if syntax is invalid."""
        try:
            ast.parse(source_code)
            return []
        except SyntaxError as e:
            return [f"Syntax error: {e.msg} (line {e.lineno})"]

    def _check_imports(self, tree: ast.Module) -> list[str]:
        """Walk AST for Import and ImportFrom nodes.

        Any import not in allowed_imports whitelist is an error.
        """
        errors: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if alias.name not in self._allowed_imports and root not in self._allowed_imports:
                        errors.append(f"Forbidden import: {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root = node.module.split(".")[0]
                    if node.module not in self._allowed_imports and root not in self._allowed_imports:
                        errors.append(f"Forbidden import: {node.module}")
        return errors

    def _check_forbidden_patterns(self, source_code: str) -> list[str]:
        """Regex scan source code for forbidden patterns."""
        errors: list[str] = []
        for pattern in self._forbidden_patterns:
            if re.search(pattern, source_code):
                errors.append(f"Forbidden pattern detected: {pattern}")
        return errors

    def _check_schema(self, tree: ast.Module) -> list[str]:
        """Verify AST contains:
        - Exactly one class that appears to subclass BaseAgent
        - Class has 'intent_descriptors' assignment
        - Class has 'handle_intent' async method
        - Class has 'agent_type' assignment
        - Class has '_handled_intents' assignment
        """
        errors: list[str] = []
        agent_classes = []

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                # Check if it subclasses BaseAgent
                for base in node.bases:
                    base_name = ""
                    if isinstance(base, ast.Name):
                        base_name = base.id
                    elif isinstance(base, ast.Attribute):
                        base_name = base.attr
                    if base_name == "BaseAgent":
                        agent_classes.append(node)

        if not agent_classes:
            errors.append("No BaseAgent subclass found")
            return errors

        cls = agent_classes[0]

        # Check required class-level attributes
        has_intent_descriptors = False
        has_agent_type = False
        has_handled_intents = False
        has_handle_intent = False

        for item in cls.body:
            # Check assignments
            if isinstance(item, ast.Assign):
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        if target.id == "intent_descriptors":
                            has_intent_descriptors = True
                        elif target.id == "agent_type":
                            has_agent_type = True
                        elif target.id == "_handled_intents":
                            has_handled_intents = True
            elif isinstance(item, ast.AnnAssign):
                if isinstance(item.target, ast.Name):
                    if item.target.id == "intent_descriptors":
                        has_intent_descriptors = True
                    elif item.target.id == "agent_type":
                        has_agent_type = True
                    elif item.target.id == "_handled_intents":
                        has_handled_intents = True
            # Check async methods
            elif isinstance(item, ast.AsyncFunctionDef):
                if item.name == "handle_intent":
                    has_handle_intent = True
            elif isinstance(item, ast.FunctionDef):
                if item.name == "handle_intent":
                    has_handle_intent = True

        if not has_intent_descriptors:
            errors.append("Missing 'intent_descriptors' class attribute")
        if not has_agent_type:
            errors.append("Missing 'agent_type' class attribute")
        if not has_handled_intents:
            errors.append("Missing '_handled_intents' class attribute")
        if not has_handle_intent:
            errors.append("Missing 'handle_intent' method")

        return errors

    def _check_module_side_effects(self, tree: ast.Module) -> list[str]:
        """Module-level statements must be: imports, class defs, function defs,
        assignments, or string expressions (docstrings).

        Bare function calls, loops, or conditionals at module level are errors.
        """
        errors: list[str] = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (
                ast.Import, ast.ImportFrom,
                ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef,
                ast.Assign, ast.AnnAssign,
            )):
                continue
            # Allow string constants (docstrings)
            if isinstance(node, ast.Expr) and isinstance(node.value, (ast.Constant,)):
                if isinstance(node.value.value, str):
                    continue
            # Everything else is a side effect
            errors.append(
                f"Module-level side effect at line {node.lineno}: "
                f"{type(node).__name__}"
            )
        return errors
