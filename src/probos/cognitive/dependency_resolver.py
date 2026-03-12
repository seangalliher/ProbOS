"""DependencyResolver — detect missing packages and install via uv add."""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import importlib.util
import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

# Maps Python import names to their pip/uv package names when they differ.
IMPORT_TO_PACKAGE: dict[str, str] = {
    "bs4": "beautifulsoup4",
    "yaml": "pyyaml",
    "dateutil": "python-dateutil",
    "cv2": "opencv-python",
    "PIL": "Pillow",
    "sklearn": "scikit-learn",
    "attr": "attrs",
    "dotenv": "python-dotenv",
}


@dataclasses.dataclass
class DependencyResult:
    """Result of dependency resolution."""

    success: bool
    installed: list[str] = dataclasses.field(default_factory=list)
    declined: list[str] = dataclasses.field(default_factory=list)
    failed: list[str] = dataclasses.field(default_factory=list)
    error: str | None = None


class DependencyResolver:
    """Detects missing-but-allowed imports and installs them via uv add."""

    def __init__(
        self,
        allowed_imports: list[str],
        install_fn: Callable[[str], Awaitable[tuple[bool, str]]] | None = None,
        approval_fn: Callable[[list[str]], Awaitable[bool]] | None = None,
    ) -> None:
        """
        Args:
            allowed_imports: The whitelist from SelfModConfig
            install_fn: Optional override for package installation (for testing).
                        Signature: async (package_name: str) -> tuple[bool, str]
            approval_fn: Optional async callback for user approval.
                        Signature: async (packages: list[str]) -> bool
        """
        self._allowed_imports = set(allowed_imports)
        self._install_fn = install_fn
        self._approval_fn = approval_fn

    def detect_missing(self, source_code: str) -> list[str]:
        """Parse imports from source code and find missing-but-allowed packages.

        Returns list of import names that are on allowed_imports but not installed.
        """
        try:
            tree = ast.parse(source_code)
        except SyntaxError:
            return []

        import_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root = alias.name.split(".")[0]
                    import_names.add(root)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root = node.module.split(".")[0]
                    import_names.add(root)

        missing: list[str] = []
        for name in sorted(import_names):
            # Only check imports that are on the allowed list
            if name not in self._allowed_imports:
                # Check if a dotted form is allowed (e.g., "urllib.parse")
                in_allowed = any(
                    a.split(".")[0] == name for a in self._allowed_imports
                )
                if not in_allowed:
                    continue

            # Check if the module is actually available
            try:
                spec = importlib.util.find_spec(name)
                if spec is not None:
                    continue
            except (ModuleNotFoundError, ValueError):
                pass

            # Skip probos internal imports
            if name == "probos":
                continue

            missing.append(name)

        return missing

    async def resolve(self, source_code: str) -> DependencyResult:
        """Orchestrate detection, approval, and installation.

        Returns DependencyResult indicating what happened.
        """
        missing = self.detect_missing(source_code)
        if not missing:
            return DependencyResult(success=True, installed=[])

        # Map import names to package names
        packages = [IMPORT_TO_PACKAGE.get(m, m) for m in missing]

        # User approval
        if self._approval_fn:
            try:
                approved = await self._approval_fn(
                    [
                        f"{m} ({IMPORT_TO_PACKAGE[m]})" if m in IMPORT_TO_PACKAGE else m
                        for m in missing
                    ]
                )
            except Exception:
                approved = False
            if not approved:
                return DependencyResult(success=False, declined=packages)

        # Install each package
        installed: list[str] = []
        failed: list[str] = []
        for i, pkg in enumerate(packages):
            import_name = missing[i]
            success, output = await self._install_package(pkg)
            if success:
                # Verify installation via find_spec
                try:
                    spec = importlib.util.find_spec(import_name)
                    if spec is not None:
                        installed.append(pkg)
                    else:
                        failed.append(pkg)
                except (ModuleNotFoundError, ValueError):
                    failed.append(pkg)
            else:
                failed.append(pkg)

        if failed:
            return DependencyResult(
                success=False,
                installed=installed,
                failed=failed,
                error=f"Failed to install: {', '.join(failed)}",
            )

        return DependencyResult(success=True, installed=installed)

    async def _install_package(self, package_name: str) -> tuple[bool, str]:
        """Install a package via uv add.

        Returns (success, output).
        """
        if self._install_fn:
            return await self._install_fn(package_name)

        try:
            proc = await asyncio.create_subprocess_exec(
                "uv", "add", package_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=60.0,
            )
            output = (stdout or b"").decode() + (stderr or b"").decode()
            if proc.returncode == 0:
                return True, output
            return False, output
        except asyncio.TimeoutError:
            return False, f"Installation of {package_name} timed out after 60s"
        except Exception as e:
            return False, f"Installation error: {e}"
