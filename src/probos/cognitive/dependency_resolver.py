"""DependencyResolver — detect missing packages and install via pip/uv."""

from __future__ import annotations

import ast
import asyncio
import dataclasses
import importlib.util
import logging
import shutil
import subprocess
import sys
from collections.abc import Awaitable, Callable
from typing import Any, Literal

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
    """Detects missing-but-allowed imports and installs them via pip/uv."""

    def __init__(
        self,
        allowed_imports: list[str],
        install_fn: Callable[[str], Awaitable[tuple[bool, str]]] | None = None,
        approval_fn: Callable[[list[str]], Awaitable[bool]] | None = None,
        policy: Literal["whitelist", "prompt_unlisted"] = "whitelist",
        deny_imports: list[str] | None = None,
    ) -> None:
        """
        Args:
            allowed_imports: The whitelist from SelfModConfig
            install_fn: Optional override for package installation (for testing).
                        Signature: async (package_name: str) -> tuple[bool, str]
            approval_fn: Optional async callback for user approval.
                        Signature: async (packages: list[str]) -> bool
            policy: AD-838c — "whitelist" (default; only allowed_imports are
                    offerable, preserving AD-213 behavior) or "prompt_unlisted"
                    (unlisted missing imports are also offerable for approval).
            deny_imports: AD-838c — imports that are never offerable under
                    "prompt_unlisted" (silently skipped). Ignored in whitelist
                    mode since unlisted imports are skipped there anyway.
        """
        self._allowed_imports = set(allowed_imports)
        self._install_fn = install_fn
        self._approval_fn = approval_fn
        self._policy = policy
        self._deny_imports = set(deny_imports or [])

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
            # Determine whether this import is on the allowlist (direct match or
            # a dotted form such as "urllib.parse" listed for "urllib").
            in_allowed = name in self._allowed_imports or any(
                a.split(".")[0] == name for a in self._allowed_imports
            )
            if not in_allowed:
                if self._policy != "prompt_unlisted":
                    # whitelist mode (AD-213): only allowlisted imports offerable
                    continue
                # prompt_unlisted mode (AD-838c): unlisted imports are offerable
                # for approval unless explicitly denied
                if name in self._deny_imports:
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

    async def resolve(
        self, source_code: str, *, pre_approved: bool = False
    ) -> DependencyResult:
        """Orchestrate detection, approval, and installation.

        Returns DependencyResult indicating what happened.

        AD-1211: ``pre_approved`` states that a human has ALREADY approved this
        install on the record — the Captain approving an ``install`` capability
        request is the only caller today. It skips the approval callback so the
        same human is not asked a second time for the same package, and nothing
        else: detection, the policy, the deny-list, installation and
        verification all run exactly as they do for any other caller. It is
        deliberately NOT a way to install something the policy excludes — a
        denied or unlisted-under-``whitelist`` import is still never offered,
        because ``detect_missing`` decides that before approval is reached.
        """
        missing = self.detect_missing(source_code)
        if not missing:
            return DependencyResult(success=True, installed=[])

        # Map import names to package names
        packages = [IMPORT_TO_PACKAGE.get(m, m) for m in missing]

        # User approval
        if pre_approved:
            logger.info(
                "AD-1211: installing %s without a fresh approval prompt — "
                "approval is already on record for this request",
                ", ".join(packages),
            )
        elif self._approval_fn:
            try:
                approved = await self._approval_fn(
                    [
                        f"{m} ({IMPORT_TO_PACKAGE[m]})" if m in IMPORT_TO_PACKAGE else m
                        for m in missing
                    ]
                )
            except Exception:
                logger.warning("Approval callback failed", exc_info=True)
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
        """Install a package using the best available method.

        Fallback chain:
        1. sys.executable -m pip install (uses the running venv Python)
        2. uv pip install (if uv is available)
        3. uv add (if uv is available and we're in a uv project)

        Returns (success, output).
        """
        if self._install_fn:
            return await self._install_fn(package_name)

        loop = asyncio.get_running_loop()

        # Method 1: pip via the running Python (most reliable)
        try:
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    [sys.executable, "-m", "pip", "install", package_name],
                    capture_output=True, encoding="utf-8", errors="replace", timeout=120,
                ),
            )
            if result.returncode == 0:
                return True, result.stdout + result.stderr
            logger.warning("pip install failed for %s: %s", package_name, result.stderr[:200])
        except Exception as e:
            logger.warning("pip install exception for %s: %s", package_name, e)

        # Method 2: uv pip install (faster if available)
        uv_path = shutil.which("uv")
        if uv_path:
            try:
                result = await loop.run_in_executor(
                    None,
                    lambda: subprocess.run(
                        [uv_path, "pip", "install", package_name],
                        capture_output=True, encoding="utf-8", errors="replace", timeout=120,
                    ),
                )
                if result.returncode == 0:
                    return True, result.stdout + result.stderr
            except Exception as e:
                logger.debug("uv pip install failed for %s: %s", package_name, e)

            # Method 3: uv add (for uv-managed projects)
            try:
                result = await loop.run_in_executor(
                    None,
                    lambda: subprocess.run(
                        [uv_path, "add", package_name],
                        capture_output=True, encoding="utf-8", errors="replace", timeout=120,
                    ),
                )
                if result.returncode == 0:
                    return True, result.stdout + result.stderr
            except Exception:
                logger.debug("Dependency resolution context failed", exc_info=True)

        return False, f"All installation methods failed for {package_name}"
