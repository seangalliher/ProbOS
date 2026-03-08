"""SkillValidator — validates generated skill handler code."""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.config import SelfModConfig


class SkillValidator:
    """Validates generated skill handler code.

    Checks (similar to CodeValidator):
    1. Syntax validity
    2. Forbidden imports (not in whitelist)
    3. Forbidden patterns (regex)
    4. Schema conformance: has exactly one async function named handle_{intent_name}
    5. Function signature: takes (intent, llm_client=None) or similar
    6. No module-level side effects beyond imports and the function def
    """

    def __init__(self, config: SelfModConfig) -> None:
        self._allowed_imports = set(config.allowed_imports)
        # Always allow probos.types
        self._allowed_imports.add("probos")
        self._forbidden_patterns = config.forbidden_patterns

    def validate(self, source_code: str, intent_name: str) -> list[str]:
        """Validate skill source code. Returns list of error strings.

        Empty list = validation passed.
        """
        errors: list[str] = []

        # 1. Syntax check
        try:
            tree = ast.parse(source_code)
        except SyntaxError as e:
            errors.append(f"Syntax error: {e}")
            return errors  # Can't continue without valid AST

        # 2. Forbidden imports
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    if root not in self._allowed_imports:
                        errors.append(f"Forbidden import: {alias.name}")
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root = node.module.split(".")[0]
                    if root not in self._allowed_imports:
                        errors.append(f"Forbidden import: {node.module}")

        # 3. Forbidden patterns
        for pattern in self._forbidden_patterns:
            if re.search(pattern, source_code):
                errors.append(f"Forbidden pattern found: {pattern}")

        # 4. Schema conformance: has async function named handle_{intent_name}
        expected_name = f"handle_{intent_name}"
        async_functions = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef)
        ]

        matching = [f for f in async_functions if f.name == expected_name]
        if not matching:
            errors.append(
                f"Missing async function: expected '{expected_name}', "
                f"found: {[f.name for f in async_functions]}"
            )

        # 5. No module-level side effects
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom, ast.AsyncFunctionDef,
                                 ast.FunctionDef, ast.ClassDef)):
                continue
            if isinstance(node, ast.Expr) and isinstance(node.value, (ast.Constant, ast.Str)):
                continue  # docstrings are fine
            errors.append(
                f"Module-level side effect: {type(node).__name__} at line {node.lineno}"
            )

        return errors
