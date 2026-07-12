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

        # 4. Schema conformance: exactly one top-level async handler with a
        # signature compatible with handler(intent, llm_client=<client>).
        expected_name = f"handle_{intent_name}"
        async_functions = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef)
        ]
        exact_definitions = [
            node for node in tree.body
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
            and node.name == expected_name
        ]
        if (
            len(exact_definitions) != 1
            or not isinstance(exact_definitions[0], ast.AsyncFunctionDef)
        ):
            errors.append(
                "Missing async function or duplicate exact handler: "
                f"Expected exactly one top-level async function '{expected_name}', "
                f"found {len(exact_definitions)} exact definitions; async functions: "
                f"{[f.name for f in async_functions]}"
            )
        else:
            signature_error = self._validate_handler_signature(exact_definitions[0])
            if signature_error is not None:
                errors.append(signature_error)

        # 5. No module-level side effects
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom, ast.AsyncFunctionDef,
                                 ast.FunctionDef, ast.ClassDef,
                                 ast.Assign, ast.AnnAssign)):
                continue
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
                continue  # docstrings are fine
            errors.append(
                f"Module-level side effect: {type(node).__name__} at line {node.lineno}"
            )

        return errors

    @staticmethod
    def _validate_handler_signature(handler: ast.AsyncFunctionDef) -> str | None:
        """Validate the non-executing AST call shape used by ``SkillBasedAgent``."""
        args = handler.args
        positional = [*args.posonlyargs, *args.args]
        positional_defaults = len(args.defaults)
        required_positional = positional[: len(positional) - positional_defaults]

        intent_is_positional = bool(positional) or args.vararg is not None
        if not intent_is_positional:
            return "Handler signature does not accept intent positionally"

        if positional:
            consumed_intent_name = positional[0].arg
        else:
            consumed_intent_name = None
        if consumed_intent_name == "llm_client":
            return "Handler signature does not accept distinct intent and llm_client values"

        positional_only_llm_client = any(
            parameter.arg == "llm_client" for parameter in args.posonlyargs
        )
        if positional_only_llm_client:
            return "Handler signature requires positional-only llm_client"

        unsupplied_required_positional = [
            parameter.arg
            for parameter in required_positional
            if parameter.arg != consumed_intent_name
            and not (
                parameter.arg == "llm_client"
                and any(parameter is named for named in args.args)
            )
        ]
        if unsupplied_required_positional:
            return (
                "Handler signature has unsupplied required positional parameters: "
                f"{unsupplied_required_positional}"
            )

        named_llm_client = next(
            (parameter for parameter in args.args if parameter.arg == "llm_client"),
            None,
        )
        keyword_llm_client = (
            named_llm_client is not None
            or any(parameter.arg == "llm_client" for parameter in args.kwonlyargs)
            or args.kwarg is not None
        )
        if not keyword_llm_client:
            return "Handler signature does not accept llm_client by keyword"

        required_keyword_only = [
            parameter.arg
            for parameter, default in zip(args.kwonlyargs, args.kw_defaults)
            if default is None and parameter.arg != "llm_client"
        ]
        if required_keyword_only:
            return (
                "Handler signature has unsupplied required keyword-only parameters: "
                f"{required_keyword_only}"
            )
        return None
