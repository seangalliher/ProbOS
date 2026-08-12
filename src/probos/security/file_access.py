"""BF-758: one file-read floor, used by every path that can open a file.

A crew agent could read any file on the host in a single DM turn. `read_file`
is in `_MESH_READ_INTENT_POOLS`, `step_4h_mesh_read_parse` runs on every DM turn
with no config flag, and `FileReaderAgent._read_file` was a bare
`Path(path).read_text()`. `ReadFileTool` advertised "from the project tree" to
the model while `_resolve_path` passed an absolute path straight through. Two
independent readers, no bound on either, and one of them lying about it.

The allowlist that admits `read_file` to the conversational seam was reviewed
for "is this intent read-only". It is. **Read-only is not the same property as
bounded**, and nothing checked the second one.

Modelled on `url_guard`, and for the same reason: this separates *policy* from
*floor*. The floor is the credential vault and the governance databases, which
no configuration should be able to hand out. Policy is an optional operator
confinement, empty by default.

The first draft got that backwards -- it permitted only the workspace and the
project tree, which broke 24 integration tests. `read_file` on an arbitrary path
is a load-bearing core capability (it is the canonical intent in the mesh,
consensus, Hebbian and episodic suites), and confining it would also refuse
"read the file I just named" from the Captain. `url_guard` does not maintain a
list of permitted hosts; it refuses loopback whoever asked. Same shape here.

Longest-prefix-match decides overlaps, because two genuinely overlap: the agent
workspace root resolves *under* the runtime data directory, so a flat "deny the
data dir" would block the one folder agents are meant to work in.

`run_python` is deliberately NOT covered. `execution/isolation.py` states its
own boundary honestly -- "a determined script can still read host files by
absolute path" -- and raising that is Tier 2 (AD-995). This module closes the
ungoverned, unaudited, one-tag route, which is the part that was wrong.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Mirrors ``ExecutionConfig.workspace_root``. A literal, not an import, so this
# guard works for a reader that has no runtime and no config at all.
_DEFAULT_WORKSPACE_ROOT = "data/execution/workspaces"

# Belt-and-braces on top of the floor: these are refused by NAME wherever they
# are, in case an operator relocates the vault outside the data directory.
# Taken from ``CredentialVaultConfig`` defaults -- the first draft guessed
# ``vault.json``/``credentials.json``, which are not files this system has ever
# written, so the check named nothing and only looked like a guard.
PROTECTED_LEAF_NAMES = frozenset({
    "credential_vault.json",
    "credential_keyring_index.json",
})


class FileAccessDenied(Exception):
    """A read was refused by the file-access floor."""

    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(reason)


def _depth(root: Path) -> int:
    return len(root.parts)


def _longest_match(resolved: Path, roots: Iterable[Path]) -> Path | None:
    """The deepest root that contains *resolved*, or ``None``."""
    best: Path | None = None
    for root in roots:
        try:
            if resolved == root or resolved.is_relative_to(root):
                if best is None or _depth(root) > _depth(best):
                    best = root
        except (OSError, ValueError):
            continue
    return best


def resolve_read_path(
    raw: str,
    *,
    protected_roots: Sequence[Path],
    exempt_roots: Sequence[Path] = (),
    permitted_roots: Sequence[Path] | None = None,
    relative_base: Path | None = None,
) -> Path:
    """The absolute path to read, or raise :class:`FileAccessDenied`.

    Three distinct ideas, kept separate because conflating them is what the
    first two drafts got wrong:

    * ``protected_roots`` -- the FLOOR. Refused whoever asked, however
      configured. The credential vault and the governance databases.
    * ``exempt_roots`` -- carve-outs INSIDE the floor that are legitimately
      agent-owned. The agent workspace resolves under the data directory, so
      without this a flat floor blocks the one folder agents work in. An
      exemption lifts the floor; it does not confine anything.
    * ``permitted_roots`` -- POLICY. ``None`` (default) means an operator has
      not confined reads. Confining is opt-in because ``read_file`` on an
      arbitrary path is a load-bearing core capability -- it is the canonical
      intent in the mesh, consensus, Hebbian and episodic suites, and the
      Captain names arbitrary paths.

    Resolution happens BEFORE containment, so a symlink pointing into the floor
    is caught -- the same ``resolve() + is_relative_to`` order
    ``WorkspaceManager.resolve_file`` uses.
    """
    if not raw or "\x00" in raw:
        raise FileAccessDenied(raw, "empty or malformed path")
    try:
        candidate = Path(raw)
        # A relative path must keep resolving the way its caller always did.
        # ``ReadFileTool._resolve_path`` rooted relative paths at the project
        # tree; resolving them against the process CWD instead silently broke
        # every relative read the Builder makes.
        if relative_base is not None and not candidate.is_absolute():
            candidate = relative_base / candidate
        resolved = candidate.resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise FileAccessDenied(raw, f"path could not be resolved: {exc}") from exc

    if resolved.name in PROTECTED_LEAF_NAMES:
        raise FileAccessDenied(raw, "that file holds credentials and is not readable")

    protect = _longest_match(resolved, protected_roots)
    if protect is not None:
        exempt = _longest_match(resolved, exempt_roots)
        # Longest prefix wins: a deeper exemption lifts a shallower floor.
        if exempt is None or _depth(exempt) <= _depth(protect):
            raise FileAccessDenied(
                raw, "path is inside the runtime's protected data directory"
            )

    if permitted_roots and _longest_match(resolved, permitted_roots) is None:
        raise FileAccessDenied(raw, "path is outside every readable root")
    return resolved


def permitted_read_roots(runtime: Any) -> list[Path]:
    """Operator POLICY: confine reads to these roots, or ``[]`` for no limit.

    Empty by default. ``read_file`` is a core capability used across the mesh,
    and the Captain legitimately asks agents to read files anywhere -- so
    confinement is opt-in. The agent workspace is always added when a limit IS
    set, because an agent must be able to read its own working folder.
    """
    infra = getattr(getattr(runtime, "config", None), "security_infra", None)
    configured = getattr(infra, "read_roots", None) or []
    if not configured:
        return []
    roots: list[Path] = []
    for entry in configured:
        try:
            roots.append(Path(str(entry)).resolve())
        except (OSError, ValueError):
            logger.warning(
                "BF-758: configured read_roots entry %r is not a usable path; "
                "ignoring it", entry,
            )
    cfg = getattr(getattr(runtime, "config", None), "execution", None)
    workspace = getattr(cfg, "workspace_root", "") or _DEFAULT_WORKSPACE_ROOT
    try:
        from probos.execution.workspace import _resolve_workspace_root

        roots.append(_resolve_workspace_root(workspace))
    except Exception:
        logger.debug("BF-758: workspace root unresolved", exc_info=True)
    return roots


def protected_read_roots(runtime: Any) -> list[Path]:
    """The floor: the runtime data directory (vault, governance databases).

    Falls back to the platform data dir for the same reason as above -- the
    readers that need this most have no runtime.
    """
    data_dir = getattr(runtime, "data_dir", None)
    if data_dir is None:
        try:
            from probos.execution.workspace import _platform_data_dir

            return [_platform_data_dir().resolve()]
        except Exception:
            return []
    try:
        return [Path(data_dir).resolve()]
    except (OSError, ValueError):
        return []


def workspace_exempt_roots(runtime: Any) -> list[Path]:
    """The agent workspace tree, which lives under the data dir but is theirs."""
    cfg = getattr(getattr(runtime, "config", None), "execution", None)
    workspace = getattr(cfg, "workspace_root", "") or _DEFAULT_WORKSPACE_ROOT
    try:
        from probos.execution.workspace import _resolve_workspace_root

        return [_resolve_workspace_root(workspace)]
    except Exception:
        logger.debug("BF-758: workspace root unresolved", exc_info=True)
        return []


def resolve_for_runtime(
    raw: str, runtime: Any, *, relative_base: Path | None = None
) -> Path:
    """Convenience wrapper: resolve *raw* against *runtime*'s floor and policy."""
    return resolve_read_path(
        raw,
        protected_roots=protected_read_roots(runtime),
        exempt_roots=workspace_exempt_roots(runtime),
        permitted_roots=permitted_read_roots(runtime) or None,
        relative_base=relative_base,
    )
