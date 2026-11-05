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

BF-911 (#1613): the write side. ``protected_write_refusal`` refuses an agent-reachable
write to a file in :func:`protected_config_files` or to a credential vault file name
(``PROTECTED_LEAF_NAMES``), by resolved path and by ``os.stat`` identity. Its callers are
listed in ``tests/test_bf911_protected_config_write_refusal.py`` (``_EXPECTED_CALLERS``).
"""

from __future__ import annotations

import logging
import ntpath
import os
import posixpath
import re
import stat
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path, PureWindowsPath
from typing import Any

logger = logging.getLogger(__name__)

# Mirrors ``ExecutionConfig.workspace_root``. A literal, not an import, so this
# guard works for a reader that has no runtime and no config at all.
_DEFAULT_WORKSPACE_ROOT = "data/execution/workspaces"

# BF-908: the checkout's config file, mirroring ``__main__._repo_default_config_path``
# (``src/probos/security/file_access.py`` -> ``parents[3]`` is the checkout). A literal
# for the same reason: a reader with no runtime must still refuse it.
_REPO_DEFAULT_CONFIG = Path(__file__).resolve().parents[3] / "config" / "system.yaml"

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


# BF-953: the floor decides each spelling of one file as its ordinary spelling is decided. ``Path.resolve()`` keeps the
# Windows extended-length prefix it is given and reports a share spelling of a local drive as the share path, so the
# textual test below saw each as another place. On Windows the text is first reduced to its namespace-free form
# (``_namespace_free``) for every root list. The floor alone is also decided by the identity the system gives the
# file (``_file_identity``), for a path or root that still names a share or a device: identity only ever adds a
# refusal, and an exempt or permitted root is matched by text, so no spelling is admitted by one it does not
# textually name (BF-953 Amendment 1). The floor's file roots and the credential names are decided on the file the
# final component names (``_base_file``), a root's as well as a candidate's (BF-953 Amendment 2). That is a rule on
# the text that only adds refusals, not a statement that the names are one file: in the extended namespace a name that
# ends in a dot or a space is another file, and it is refused too. Elsewhere containment is the textual test.
_NAMESPACE_PREFIXES = ("\\\\?\\", "\\\\.\\")
_EXTENDED_UNC = "\\\\?\\UNC\\"
_FLOOR_UNVERIFIED = "path cannot be verified against the protected roots"


def _namespace_free(text: str) -> str:
    r"""BF-953: *text*, a path as ``str(WindowsPath)`` spells it, without its Windows namespace prefix: the form in which
    a path and a root are compared as text.

    ``\\?\UNC\host\share\x`` is ``\\host\share\x``; ``\\?\C:\x`` and ``\\.\C:\x`` are ``C:\x``, and the bare drive
    ``\\?\C:`` is ``C:``. Any other text (a volume or device name, a drive-relative form with a path, a path of another
    platform) is returned as it is. Pure: it reads nothing and does not depend on the platform it runs on. It is a form for
    comparing text, not a statement about files: in the extended namespace a name that ends in a dot or a space is another
    file than the one the ordinary spelling names (:func:`reader_spelling`).
    """
    if text[:8].upper() == _EXTENDED_UNC.upper():
        return "\\\\" + text[8:]
    if text[:4] in _NAMESPACE_PREFIXES and text[4:5].isascii() and text[4:5].isalpha() and text[5:6] == ":":
        if text[6:7] in ("", "\\"):
            return text[4:]
    return text


class _Unverifiable(Exception):
    """BF-953 (Amendment 1): the system could not say which file a path names, so the floor cannot be checked."""


def _base_name(name: str) -> str:
    """BF-953 (Amendment 1): the name of the file the final component *name* names, on Windows: without a stream suffix (the
    text from the first ``:``) and without trailing dots and spaces. A name that would be empty is returned as it is. Pure."""
    return name.split(":", 1)[0].rstrip(" .") or name


def _base_file(path: Path) -> Path:
    """BF-953 (Amendment 1): *path* with its final component reduced to the file it names (:func:`_base_name`), on Windows;
    any other path, and every path on another platform, as it is. The floor and the credential names are decided on it, so a
    stream, trailing-dot or trailing-space spelling of a floor file is decided as the file is, whether or not it is on disk;
    an admitted read keeps the path as resolved. It is a rule on the text that only adds refusals (L14). Pure: it reads
    nothing."""
    if os.name != "nt":
        return path
    base = _base_name(path.name)
    return path.with_name(base) if base != path.name else path


def _floor_roots(roots: Sequence[Path]) -> list[Path]:
    """BF-953 (Amendment 2): the floor roots *roots*, each root followed by the file its final component names where that is
    another spelling (:func:`_base_file`).

    A floor file root is compared by the file it names, as a candidate is, so a configuration loaded as
    ``loaded.yaml:settings`` refuses a read of ``loaded.yaml:settings`` and of ``loaded.yaml``. Each root stays as it is
    spelled, so no refusal a root made is lost: the result equals *roots* for every directory root a system resolves, for an
    ordinary file root and on another platform. A root spelled in the extended namespace with a trailing dot or space adds
    the directory or file its base names, a refusal only (L16). Pure: it reads nothing."""
    named = [_base_file(root) for root in roots]
    return [*roots, *(base for root, base in zip(roots, named) if base != root)]


def _protected_leaf(path: Path) -> bool:
    """Whether the final component of *path* is a credential vault file name: exactly as the base compared it
    (``PROTECTED_LEAF_NAMES``), and on Windows (BF-953 Amendment 1) as the write side compares it, in the canonical form
    (:func:`_canonical_name`), so another case is the same name."""
    return _canonical_name(path.name) in _PROTECTED_LEAF_KEYS if os.name == "nt" else path.name in PROTECTED_LEAF_NAMES


def _file_identity(path: Path) -> tuple[int, int] | None:
    """BF-953: the identity the system gives the file *path* names, ``(volume, file index)``.

    ``None`` when no such file is on disk (the system says there is none). Raises :class:`_Unverifiable` when the
    system cannot say: the read fails for any other reason, or its filesystem reports no file index (zero).
    """
    try:
        info = os.stat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except (OSError, ValueError) as exc:
        raise _Unverifiable from exc
    if not info.st_ino:
        raise _Unverifiable
    return info.st_dev, info.st_ino


def plain_spelling(path: Path) -> Path:
    """BF-953 (Amendment 1): *path* without its Windows namespace prefix, as a reader that rejects the prefix is given it.

    The extended-length and device prefixes of a drive path and the extended UNC prefix are removed
    (:func:`_namespace_free`); any other path, and every path on another platform, is returned as it is. Pure: it
    reads nothing. A component that ends in a dot or a space does not name the same file once the prefix is gone:
    :func:`reader_spelling` says whether a listing may name the file.
    """
    return Path(_namespace_free(str(path))) if os.name == "nt" else path


def reader_spelling(path: Path) -> Path | None:
    """BF-953 (Amendments 2 to 5): the spelling of *path* a listing may name, or ``None``.

    The input is a path as ``glob`` yields it: absolute, with no ``..`` part. The result is :func:`plain_spelling` of *path*
    where the verified reader's own functions admit its text, and ``None`` otherwise: :func:`validate_read_location`, called
    as it is on the file and on the file's direct parent (the two texts ``read_verified_file`` gives it), and the final-name
    rule of ``PinnedDirectory._leaf``, restated below (BF-953 D15; T31 and T36 compare it with a real pinned directory). A path
    with no final name or with a ``..`` part has no spelling: the reader decides on the candidate ``validate_read_location``
    returns, and that resolves ``..``. What the armed reader answers for a refused text is recorded in BF-953 L22; the reader
    gives its location gate no directory above the direct parent (BF-953 L21). On Windows the rule of BF-953 D14 also gives
    ``None``: it is wider than the reader's text path (BF-953 L21).

    Pure: it calls no filesystem function (BF-953 T32). It does not say that the file opens (BF-953 L18). Its cost is
    recorded in BF-953 L20."""
    shown = plain_spelling(path)
    try:
        validate_read_location(str(shown))
        validate_read_location(str(shown.parent))  # the directory read_verified_file pins is given to the gate as well
    except ValueError:  # the reader's own refusal of the text, whatever its class (UnicodeEncodeError is one): no spelling
        return None
    if not shown.name:  # a root has no child name: PinnedDirectory._leaf refuses an empty one
        return None
    if ".." in shown.parts:  # the reader decides on the candidate validate_read_location returns, and that resolves '..'
        return None
    final = shown.name
    if "\\" in final or final != final.rstrip(" ."):
        return None
    if os.name != "nt":
        return shown
    ordinary = PureWindowsPath(str(shown))
    names = ordinary.parts[1:] if ordinary.anchor else ordinary.parts
    if any(name != name.rstrip(" .") for name in names):
        return None
    if any(part.is_reserved() for part in (ordinary, *ordinary.parents)):
        return None
    return shown


class _OnDisk:
    """BF-953: the identities of a path and of each ancestor of it that is on disk, read once and only when asked.

    ``position`` is the count of parts, without a namespace prefix, of the deepest part of the path's own chain that
    has a given identity; ``reaches`` is whether the chain is on a volume other than the one its topmost part is on.
    Reading a part the system cannot say anything about raises :class:`_Unverifiable`.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._places: dict[tuple[int, int], int] | None = None
        self._crossed: frozenset[int] = frozenset()

    def _read(self) -> dict[tuple[int, int], int]:
        if self._places is None:
            places: dict[tuple[int, int], int] = {}
            volumes: list[int] = []
            for part in (self._path, *self._path.parents):
                identity = _file_identity(part)
                if identity is not None:
                    places.setdefault(identity, len(PureWindowsPath(_namespace_free(str(part))).parts))
                    volumes.append(identity[0])
            self._crossed = frozenset(volumes) - {volumes[-1]} if volumes else frozenset()
            self._places = places
        return self._places

    def position(self, identity: tuple[int, int]) -> int | None:
        return self._read().get(identity)

    def reaches(self, volume: int) -> bool:
        self._read()
        return volume in self._crossed


def _identity_position(root: Path, on_disk: _OnDisk, whole: int) -> int | None:
    """BF-953 (Amendment 1): where in the path's own chain the floor root *root* is taken to contain it, or ``None``.

    The root contains the path at the part of its chain that is the same file as the root. It also contains it, at
    the path's own depth *whole*, when the chain is on the volume the root is on only through a link, because its
    text then does not say where on that volume the file is. A root not on disk contains nothing. Raises
    :class:`_Unverifiable` when the root or a part of the chain cannot be read.
    """
    identity = _file_identity(root)
    if identity is None:
        return None
    place = on_disk.position(identity)
    if place is None and on_disk.reaches(identity[0]):
        return whole
    return place


def _match_position(
    resolved: Path, roots: Iterable[Path], on_disk: _OnDisk | None = None, *, floor: bool = False,
) -> int | None:
    """Where in *resolved*'s own chain the deepest root that contains it stands (a count of parts), or ``None``.

    A root contains a path that is under it as spelled; it stands at its own count of parts. On Windows (BF-953) it
    also contains a path that is under it once both are without a namespace prefix, standing at the count of the
    root's parts so reduced. For the floor only (*floor*), a path or root that still names a share or a device is also
    compared by identity (:func:`_identity_position`); the exempt roots and the permitted roots never are, so a
    spelling is admitted only by a root its text names. Raises :class:`_Unverifiable` for a floor that cannot be
    read. *on_disk* lets the root lists of one decision read the path's identities once.
    """
    best: int | None = None
    if on_disk is None:
        on_disk = _OnDisk(resolved)
    for root in roots:
        try:
            at = len(root.parts) if resolved == root or resolved.is_relative_to(root) else None
            if at is None and os.name == "nt" and (str(resolved).startswith("\\\\") or str(root).startswith("\\\\")):
                key = PureWindowsPath(_namespace_free(str(resolved)))
                root_key = PureWindowsPath(_namespace_free(str(root)))
                if key == root_key or key.is_relative_to(root_key):
                    at = len(root_key.parts)
                elif floor and (key.drive.startswith("\\\\") or root_key.drive.startswith("\\\\")):
                    at = _identity_position(root, on_disk, len(key.parts))
        except (OSError, ValueError):
            continue
        if at is not None and (best is None or at > best):
            best = at
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

    BF-953: the floor decides one file in every spelling the system treats as that file: for a path that
    :func:`_match_position` compares (a share or device spelling also by the identity of its own chain), and on Windows
    for the final component (a stream suffix, trailing dots and spaces, another case: :func:`_base_file`), for a floor
    file root and a credential vault name, whether or not the file is on disk. Not covered: a share or device spelling of
    a floor file root that is not on disk (L2). An exempt or a permitted root admits a share or device spelling only if
    its text names that root, and a floor that cannot be read for a share or device spelling refuses it. A floor file
    root is compared by the file its own final component names, as the candidate is (:func:`_floor_roots`). What is
    returned is the resolved path itself, as ``Path.resolve()`` spelled it, never a rewritten one: it names the file the
    decision was made on (``resolve()`` keeps a named stream's suffix and drops a trailing dot or space and the default
    stream's type from a file on disk).
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

    base_file = _base_file(resolved)  # BF-953 (Amendment 1): what the floor and the credential names are decided on
    if _protected_leaf(base_file):
        raise FileAccessDenied(raw, "that file holds credentials and is not readable")

    on_disk = _OnDisk(base_file)  # BF-953: read at most once, and only if the floor is compared by identity
    try:
        protect = _match_position(base_file, _floor_roots(protected_roots), on_disk, floor=True)
    except _Unverifiable as exc:
        logger.warning(
            "BF-953: the read floor could not be verified for a path (%s); the read is refused",
            type(exc.__cause__).__name__ if exc.__cause__ is not None else "no file index",
        )
        raise FileAccessDenied(raw, _FLOOR_UNVERIFIED) from None
    if protect is not None:
        exempt = _match_position(resolved, exempt_roots)
        # Longest prefix wins: a deeper exemption lifts a shallower floor. Both stand at a count of
        # parts of this path's own chain, not of the spelling of the root.
        if exempt is None or exempt <= protect:
            raise FileAccessDenied(
                raw, "path is protected: the runtime's data directory or a config file"
            )

    if permitted_roots and _match_position(resolved, permitted_roots) is None:
        raise FileAccessDenied(raw, "path is outside every readable root")
    return resolved


def _workspace_root(runtime: Any) -> Path | None:
    """BF-758, BF-953 (Amendment 2): the agent workspace root *runtime* configures, or ``None`` when it cannot be composed.

    It is resolved as a candidate is, so the root and a path under it are spelled alike (a configured 8.3 short path or an
    unresolved data directory would otherwise name it as no candidate does). A root the system cannot resolve (a text with
    a NUL, a link that does not end) is returned as it was composed, as before BF-953: no candidate is under it, so a
    configured read policy still refuses every path outside its other roots and the exempt list lifts nothing."""
    cfg = getattr(getattr(runtime, "config", None), "execution", None)
    workspace = getattr(cfg, "workspace_root", "") or _DEFAULT_WORKSPACE_ROOT
    try:
        from probos.execution.workspace import _resolve_workspace_root

        composed = _resolve_workspace_root(workspace)
    except Exception:
        logger.debug("BF-758: workspace root unresolved", exc_info=True)
        return None
    try:
        return composed.resolve()
    except (OSError, RuntimeError, ValueError):
        logger.debug("BF-953: workspace root %r does not resolve; it is kept as composed", workspace, exc_info=True)
        return composed


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
    workspace = _workspace_root(runtime)
    if workspace is not None:
        roots.append(workspace)
    return roots


def protected_read_roots(runtime: Any) -> list[Path]:
    """The floor: the runtime data directory (vault, governance databases) and the config files.

    Falls back to the platform data dir for the same reason as above -- the
    readers that need this most have no runtime.

    BF-908: plus every config file that can hold ``auth.crew_scope_token``
    (:func:`protected_config_files`). A file root matches that file only.
    """
    return _protected_data_dir(runtime) + protected_config_files(runtime)


def protected_config_files(runtime: Any, *, fail_closed: bool = False) -> list[Path]:
    """BF-908: the config files the floor refuses, resolved, whether or not they exist.

    The file the vessel loaded (``runtime.config_path``: ``--config``,
    ``~/.probos/config.yaml`` or the checkout's ``config/system.yaml``) and both
    defaults, since either can hold ``auth.crew_scope_token`` whichever was loaded.
    Paths, not leaf names: ``config.yaml`` is too common a name to refuse everywhere.
    Each file once, in that order: the loaded file is usually one of the defaults.
    Not covered: a copy or hard link of the file under another path, and every
    reader that does not call this floor (a shell command, ``run_python``).
    A file whose resolution raises ``OSError``, ``RuntimeError`` or ``ValueError`` is left out
    (the read floor's default); with *fail_closed* (BF-911's write rule) the error is raised,
    so the write is refused. A home directory that cannot be determined names no file and is
    left out either way.
    """
    candidates: list[object] = [getattr(runtime, "config_path", None), _REPO_DEFAULT_CONFIG]
    try:
        candidates.append(Path.home() / ".probos" / "config.yaml")
    except (RuntimeError, OSError):
        pass
    files: list[Path] = []
    for candidate in candidates:
        if not isinstance(candidate, (str, Path)) or not str(candidate):
            continue
        try:
            resolved = Path(candidate).resolve()
        except (OSError, RuntimeError, ValueError):
            if fail_closed:
                raise  # BF-911: the write floor refuses a write rather than lose a file it cannot resolve
            continue
        if resolved not in files:  # BF-908 A3: the loaded file is often a default; list each file once
            files.append(resolved)
    return files


# BF-911 (#1613): the write side of the floor. Components are compared in BF-894's canonical
# form (``builder_paths._canonical``: HFS+ ignorable code points dropped, trailing dots and
# spaces trimmed, upper-cased) with its 8.3 short-name pattern. Mirrored here so this module
# imports nothing from ``cognitive``; tests/test_bf911_protected_config_write_refusal.py T19
# pins the parity.
_HFS_IGNORABLE = re.compile("[\u200c-\u200f\u202a-\u202e\u206a-\u206f\ufeff]")
_SHORT_NAME = re.compile(r"~[0-9]")
# The Win32 file and device namespace prefixes, with separators already ``/``.
_DEVICE_PREFIXES = ("//?/", "//./")
_CONFIG_FILE = "a protected config file (the loaded --config, the checkout's config/system.yaml or ~/.probos/config.yaml)"
_VAULT_FILE = "a credential vault file"
_NOT_A_STR = "Protected write refused (BF-911): the path is not an exact str, so it is not checked"


def _canonical_name(part: str) -> str:
    """One component in the form a case-insensitive filesystem compares it (BF-894's form)."""
    return _HFS_IGNORABLE.sub("", part).rstrip(" .").upper()


_PROTECTED_LEAF_KEYS = frozenset(_canonical_name(name) for name in PROTECTED_LEAF_NAMES)


def _write_key(path_text: str) -> tuple[str, ...]:
    """BF-911: the components of *path_text* in the form the write floor compares them.

    Separators become ``/``; a ``//?/`` or ``//./`` prefix is dropped and ``//?/UNC/``
    becomes ``//``; the drive (``C:`` or ``//server/share``), upper-cased, is the first
    component; ``..`` is collapsed; each other component loses any ``:`` suffix (an NTFS
    stream) and is put in canonical form, and components then empty are dropped.
    """
    unified = path_text.replace("\\", "/")
    if unified[:4] in _DEVICE_PREFIXES:
        unified = unified[4:]
        if unified[:4].upper() == "UNC/":
            unified = "//" + unified[4:]
    drive, rest = ntpath.splitdrive(unified)
    names = [_canonical_name(part.split(":", 1)[0]) for part in posixpath.normpath(rest or "/").split("/")]
    return (drive.upper(), *(name for name in names if name))


def _same_key(candidate: tuple[str, ...], protected: tuple[str, ...]) -> bool:
    """Whether *candidate* names *protected*: each component equal, or an 8.3 short form with its first two characters."""
    return len(candidate) == len(protected) and all(
        name == expected or (_SHORT_NAME.search(name) is not None and name[:2] == expected[:2])
        for name, expected in zip(candidate, protected)
    )


def _exception_class_name(exc: BaseException) -> str:
    """The class name of *exc*, read through ``type``'s own descriptor, if it is an exact-``str`` identifier.

    ``Exception`` under another metaclass (nothing of the class is read) or for any other name.
    The body of AD-1344's ``builder_paths._exception_name``; T36 compares the two.
    """
    cls = type(exc)
    if type(cls) is not type:
        return "Exception"
    name = cls.__name__
    return name if type(name) is str and name.isidentifier() else "Exception"


def _protected_refusal(path_text: str, what: str) -> str:
    return f"Protected write refused (BF-911): {path_text!r} is {what}, which an agent does not write"


def _protected_unverifiable(path_text: str, stage: str, exc: BaseException) -> str:
    return (
        f"Protected write refused (BF-911): cannot verify that {path_text!r} is not a protected "
        f"config or credential file ({stage}: {_exception_class_name(exc)})"
    )


def protected_write_refusal(
    path: str, *, root: str | os.PathLike[str] | None = None, runtime: Any = None,
) -> str | None:
    """BF-911 (#1613): why an agent-reachable writer must not write *path*, or None if it may.

    *path* is the path as the writer received it: relative to *root*, or to the working
    directory when *root* is None, or absolute. *runtime* supplies ``config_path``; see
    :func:`protected_config_files` for the files named with and without it. Refused, with a
    one-line reason naming BF-911: a value that is not an exact ``str`` (nothing of it is
    read); a path whose resolved form names one of those files, whether or not it exists,
    or whose resolved last component is in ``PROTECTED_LEAF_NAMES`` (compared by
    :func:`_write_key`, an 8.3 short form accepted for a config file's components); an
    existing file with the ``os.stat`` identity of an existing protected config file; an
    ``os.stat`` that raises ``OSError`` or ``ValueError`` other than ``FileNotFoundError`` or
    ``NotADirectoryError``; a resolution of *path* that raises ``OSError``, ``RuntimeError``
    or ``ValueError``; and a call of ``protected_config_files(runtime, fail_closed=True)``
    that raises one of those three, such as one raised while reading ``runtime.config_path``,
    converting its value or resolving a file it names (the reason says ``config resolved``).
    Any other exception propagates. A file at another path with another identity, such as a
    worktree's ``config/system.yaml``, is not refused.
    """
    if type(path) is not str:
        return _NOT_A_STR
    target = Path(path)
    if root is not None and not target.is_absolute():
        target = Path(root) / target
    try:
        resolved = target.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        return _protected_unverifiable(path, "resolved", exc)
    key = _write_key(str(resolved))
    if key[-1] in _PROTECTED_LEAF_KEYS:
        return _protected_refusal(path, _VAULT_FILE)
    try:
        configs = protected_config_files(runtime, fail_closed=True)
    except (OSError, RuntimeError, ValueError) as exc:
        return _protected_unverifiable(path, "config resolved", exc)
    if any(_same_key(key, _write_key(str(config))) for config in configs):
        return _protected_refusal(path, _CONFIG_FILE)
    for config in configs:
        try:
            config_stat = os.stat(config)
        except (FileNotFoundError, NotADirectoryError):
            continue  # not on disk: the name comparison above is the whole check
        except (OSError, ValueError) as exc:
            return _protected_unverifiable(path, "config", exc)
        try:
            current = os.stat(target)
        except (FileNotFoundError, NotADirectoryError):
            return None  # not on disk, so not a second name of an existing config file
        except (OSError, ValueError) as exc:
            return _protected_unverifiable(path, "target", exc)
        if os.path.samestat(current, config_stat):
            return _protected_refusal(path, _CONFIG_FILE)
    return None


def _protected_data_dir(runtime: Any) -> list[Path]:
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
    workspace = _workspace_root(runtime)
    return [] if workspace is None else [workspace]


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


INSTRUCTION_FILE_BYTES = 8192


class BoundedReadStatus(str, Enum):
    OK = "ok"
    ABSENT = "absent"
    EMPTY = "empty"
    TRUNCATED = "truncated"
    INVALID_PATH = "invalid_path"
    DENIED = "denied"
    NOT_REGULAR = "not_regular"
    UNSAFE_PATH = "unsafe_path"
    CHANGED = "changed"
    IO_ERROR = "io_error"
    INVALID_UTF8 = "invalid_utf8"
    BINARY = "binary"


@dataclass(frozen=True)
class BoundedTextRead:
    """An instruction read; only ABSENT permits same-directory fallback."""

    status: BoundedReadStatus
    text: str = field(default="", repr=False)
    bytes_read: int = 0

    def __post_init__(self) -> None:
        if type(self.status) is not BoundedReadStatus or type(self.text) is not str:
            raise TypeError("bounded reads require a typed status and text")
        if type(self.bytes_read) is not int or not 0 <= self.bytes_read <= INSTRUCTION_FILE_BYTES + 1:
            raise ValueError("bounded read byte count exceeds its limit")
        if len(self.text.encode("utf-8")) > INSTRUCTION_FILE_BYTES:
            raise ValueError("bounded read text exceeds its limit")
        if any((ord(char) < 32 and char not in "\t\r\n") or 127 <= ord(char) <= 159 for char in self.text):
            raise ValueError("bounded read text contains binary controls")
        if self.text and self.status not in (
            BoundedReadStatus.OK, BoundedReadStatus.EMPTY, BoundedReadStatus.TRUNCATED,
        ):
            raise ValueError("unavailable reads must withhold content")


class _UnsafeInstructionPath(Exception):
    pass


class _ChangedInstructionPath(Exception):
    pass


class _NotRegularInstructionPath(Exception):
    pass


def validate_read_location(raw: str | Path, *, relative_base: Path | None = None) -> Path:
    """Validate a discovery location lexically, without cwd or filesystem I/O.

    This is not authorization. Bounded reads still validate policy and handles.
    """
    if isinstance(raw, Path):
        raw = str(raw)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise ValueError("invalid path")
    raw.encode("utf-8", errors="strict")
    spelling = raw.replace("/", "\\")
    drive, tail = ntpath.splitdrive(spelling)
    if (
        spelling.startswith(("\\\\?\\", "\\\\.\\"))
        or (drive and not tail.startswith("\\"))
        or ":" in tail
        or any(ord(char) < 32 for char in raw)
        or PureWindowsPath(raw).is_reserved()
    ):
        raise ValueError("invalid path")
    candidate = Path(raw)
    if os.name == "nt" and candidate.root and not candidate.drive:
        raise ValueError("device or drive-relative path")
    if not candidate.is_absolute():
        if not isinstance(relative_base, Path) or not relative_base.is_absolute():
            raise ValueError("absolute read authority required")
        candidate = validate_read_location(relative_base) / candidate
    return Path(os.path.abspath(candidate))


def _instruction_path(raw: str, root: Path) -> Path:
    root = validate_read_location(root)
    candidate = validate_read_location(raw, relative_base=root)
    if not candidate.is_relative_to(root):
        raise FileAccessDenied(raw, "path is outside the pinned root")
    return candidate


def _is_reparse(info: os.stat_result) -> bool:
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & 0x400
    )


def is_reparse_point(info: os.stat_result) -> bool:
    """Public: True for a symlink or a Windows reparse point (junction)."""
    return _is_reparse(info)


def _same_identity(before: os.stat_result, after: os.stat_result) -> bool:
    return (before.st_dev, before.st_ino, stat.S_IFMT(before.st_mode)) == (
        after.st_dev, after.st_ino, stat.S_IFMT(after.st_mode),
    )


def _same_file(
    before: os.stat_result, after: os.stat_result, *, opened: bool = False,
) -> bool:
    same_revision = (before.st_size, before.st_mtime_ns) == (
        after.st_size, after.st_mtime_ns,
    )
    # Windows lstat and CRT fstat can expose different ctime meanings. Compare
    # ctime only within the same API, including a pre/post-read handle snapshot.
    same_ctime = opened and os.name == "nt" or before.st_ctime_ns == after.st_ctime_ns
    return _same_identity(before, after) and same_revision and same_ctime


@lru_cache(maxsize=1)
def _windows_file_api() -> Any:
    import ctypes
    from ctypes import wintypes

    api = ctypes.WinDLL("kernel32", use_last_error=True)
    api.CreateFileW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    )
    api.CreateFileW.restype = wintypes.HANDLE
    api.GetFinalPathNameByHandleW.argtypes = (
        wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
    )
    api.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    api.GetFileInformationByHandleEx.argtypes = (
        wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD,
    )
    api.GetFileInformationByHandleEx.restype = wintypes.BOOL
    api.CloseHandle.argtypes = (wintypes.HANDLE,)
    api.CloseHandle.restype = wintypes.BOOL
    return api


def _windows_handle_path(handle: int) -> Path:
    import ctypes

    api = _windows_file_api()
    needed = api.GetFinalPathNameByHandleW(handle, None, 0, 0)
    if not needed:
        raise ctypes.WinError(ctypes.get_last_error())
    buffer = ctypes.create_unicode_buffer(needed + 1)
    length = api.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
    if not length or length >= len(buffer):
        raise _UnsafeInstructionPath
    name = buffer.value
    if name.startswith("\\\\?\\UNC\\"):
        name = "\\\\" + name[8:]
    elif name.startswith("\\\\?\\"):
        name = name[4:]
    return Path(name)


def _open_windows_instruction_path(path: Path, *, directory: bool) -> int:
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class AttributeTagInfo(ctypes.Structure):
        _fields_ = [("attributes", wintypes.DWORD), ("tag", wintypes.DWORD)]

    api = _windows_file_api()
    handle = api.CreateFileW(
        str(path), 0x80 if directory else 0x80000000,
        0x1 | 0x2, None, 3, 0x02000000 | 0x00200000, None,
    )
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        info = AttributeTagInfo()
        if not api.GetFileInformationByHandleEx(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        if info.attributes & 0x400 or _windows_handle_path(handle) != path:
            raise _UnsafeInstructionPath
        # No FILE_SHARE_DELETE: every ancestor and the file stay pinned until
        # the read and post-read validation finish. No directory bytes are read.
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        api.CloseHandle(handle)
        raise
    return fd


def _validate_instruction_chain(
    paths: list[Path], snapshots: list[os.stat_result], descriptors: list[int],
) -> None:
    for index, (path, before, fd) in enumerate(zip(paths, snapshots, descriptors)):
        named = path.lstat()
        opened = os.fstat(fd)
        if _is_reparse(named):
            raise _UnsafeInstructionPath
        same = (
            _same_file(before, named) and _same_file(before, opened, opened=True)
            if index == len(paths) - 1
            else _same_identity(before, named) and _same_identity(before, opened)
        )
        if not same:
            raise _ChangedInstructionPath
        if os.name == "nt":
            import msvcrt

            if _windows_handle_path(msvcrt.get_osfhandle(fd)) != path:
                raise _UnsafeInstructionPath


@dataclass(frozen=True)
class VerifiedFileRead:
    """A verified open-file observation; bytes are never part of its repr."""

    data: bytes = field(repr=False)
    identity: tuple[int, int, int]
    revision: tuple[int, int, int]


class PinnedDirectory:
    """Public handle-pinning primitive for workspace-owned I/O.

    Instances belong to ``pin_directory``'s context. POSIX operations are
    descriptor-relative; Windows ancestor handles deny delete/rename sharing.
    Every operation validates the named chain as well as the opened handles.
    """

    def __init__(self) -> None:
        self._paths: list[Path] = []
        self._snapshots: list[os.stat_result] = []
        self._descriptors: list[int] = []
        self._expected: dict[Path, tuple[int, int, int]] = {}

    def verify(self) -> None:
        if not self._descriptors:
            raise FileAccessDenied("", "closed directory authority")
        for path, before, fd in zip(self._paths, self._snapshots, self._descriptors, strict=True):
            named, opened = path.lstat(), os.fstat(fd)
            if _is_reparse(named) or not _same_identity(before, named) or not _same_identity(before, opened):
                raise FileAccessDenied("", "directory identity changed")
            expected = self._expected.get(path)
            if expected is not None and expected != (named.st_dev, named.st_ino, stat.S_IFMT(named.st_mode)):
                raise FileAccessDenied("", "previously pinned directory identity changed")
            if os.name == "nt":
                import msvcrt

                if _windows_handle_path(msvcrt.get_osfhandle(fd)) != path:
                    raise FileAccessDenied("", "opened directory moved")

    @property
    def path(self) -> Path:
        self.verify()
        return self._paths[-1]

    @property
    def identity(self) -> tuple[int, int, int]:
        self.verify()
        info = os.fstat(self._descriptors[-1])
        return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)

    @property
    def identities(self) -> tuple[tuple[Path, tuple[int, int, int]], ...]:
        self.verify()
        return tuple(
            (path, (info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)))
            for path, info in zip(self._paths, self._snapshots, strict=True)
        )

    def _leaf(self, name: str) -> Path:
        self.verify()
        if (
            type(name) is not str or not name or name in (".", "..")
            or "/" in name or "\\" in name or ":" in name
            or name.rstrip(". ") != name
        ):
            raise FileAccessDenied("", "invalid child name")
        return validate_read_location(self._paths[-1] / name)

    def list_names(self) -> tuple[str, ...]:
        self.verify()
        names = tuple(os.listdir(self._paths[-1] if os.name == "nt" else self._descriptors[-1]))
        self.verify()
        return names

    def read_bytes(self, name: str, *, max_bytes: int | None = None) -> VerifiedFileRead:
        path = self._leaf(name)
        if max_bytes is not None and (type(max_bytes) is not int or max_bytes < 0):
            raise ValueError("invalid file read limit")
        before = path.lstat()
        if _is_reparse(before) or not stat.S_ISREG(before.st_mode):
            raise FileAccessDenied("", "unsafe or non-regular file")
        if os.name == "nt":
            fd = _open_windows_instruction_path(path, directory=False)
        else:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                         dir_fd=self._descriptors[-1])
        try:
            opened = os.fstat(fd)
            if not _same_file(before, opened, opened=True):
                raise FileAccessDenied("", "opened file identity changed")
            self.verify()
            with os.fdopen(os.dup(fd), "rb") as stream:
                data = stream.read() if max_bytes is None else stream.read(max_bytes + 1)
            self.verify()
            if not _same_file(before, path.lstat()) or not _same_file(opened, os.fstat(fd)):
                raise FileAccessDenied("", "file changed during read")
            if max_bytes is not None and len(data) > max_bytes:
                raise FileAccessDenied("", "file exceeds read limit")
            return VerifiedFileRead(
                data=data,
                identity=(before.st_dev, before.st_ino, stat.S_IFMT(before.st_mode)),
                revision=(before.st_size, before.st_mtime_ns, before.st_ctime_ns),
            )
        finally:
            os.close(fd)

    def write_new(self, name: str, data: bytes) -> None:
        path = self._leaf(name)
        if type(data) is not bytes:
            raise TypeError("file writes require bytes")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if os.name == "nt":
            fd = os.open(path, flags | os.O_BINARY, 0o600)
        else:
            fd = os.open(name, flags | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600,
                         dir_fd=self._descriptors[-1])
        try:
            self.verify()
            if _is_reparse(path.lstat()) or not _same_identity(path.lstat(), os.fstat(fd)):
                raise FileAccessDenied("", "new file identity changed")
            with os.fdopen(os.dup(fd), "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            self.verify()
            if not _same_identity(path.lstat(), os.fstat(fd)):
                raise FileAccessDenied("", "written file identity changed")
        finally:
            os.close(fd)

    def make_directory(self, name: str) -> None:
        path = self._leaf(name)
        if os.name == "nt":
            os.mkdir(path, 0o700)
        else:
            os.mkdir(name, 0o700, dir_fd=self._descriptors[-1])
        self.verify()

    def publish_file(self, staged: str, name: str) -> None:
        """Atomic, no-replacement publication within this pinned directory."""
        source, target = self._leaf(staged), self._leaf(name)
        before = source.lstat()
        if _is_reparse(before) or not stat.S_ISREG(before.st_mode):
            raise FileAccessDenied("", "unsafe publication source")
        if os.name == "nt":
            os.link(source, target, follow_symlinks=False)
        else:
            os.link(staged, name, src_dir_fd=self._descriptors[-1],
                    dst_dir_fd=self._descriptors[-1], follow_symlinks=False)
        self.verify()
        if not _same_identity(before, target.lstat()) or _is_reparse(target.lstat()):
            raise FileAccessDenied("", "published identity changed")
        self.remove_file(staged)
        if os.name != "nt":
            os.fsync(self._descriptors[-1])

    def remove_file(self, name: str) -> None:
        path = self._leaf(name)
        if _is_reparse(path.lstat()) or not stat.S_ISREG(path.lstat().st_mode):
            raise FileAccessDenied("", "refusing unsafe file removal")
        if os.name == "nt":
            path.unlink()
        else:
            os.unlink(name, dir_fd=self._descriptors[-1])
        self.verify()

    def remove_directory(self, name: str) -> None:
        path = self._leaf(name)
        if _is_reparse(path.lstat()) or not stat.S_ISDIR(path.lstat().st_mode):
            raise FileAccessDenied("", "refusing unsafe directory removal")
        if os.name == "nt":
            path.rmdir()
        else:
            os.rmdir(name, dir_fd=self._descriptors[-1])
        self.verify()

    def open(
        self, path: Path, *, create: bool = False,
        expected: tuple[tuple[Path, tuple[int, int, int]], ...] = (),
    ) -> None:
        if self._descriptors:
            raise FileAccessDenied("", "directory authority already open")
        path = validate_read_location(path)
        self._expected = dict(expected)
        for candidate in (*reversed(path.parents), path):
            if self._descriptors:
                self.verify()
            try:
                info = candidate.lstat()
            except FileNotFoundError:
                if candidate in self._expected:
                    raise FileAccessDenied("", "previously pinned directory disappeared")
                if not create or not self._descriptors:
                    raise
                self.make_directory(candidate.name)
                info = candidate.lstat()
            if _is_reparse(info) or not stat.S_ISDIR(info.st_mode):
                raise FileAccessDenied("", "unsafe directory chain")
            if os.name == "nt":
                fd = _open_windows_instruction_path(candidate, directory=True)
            else:
                fd = os.open(
                    candidate.name if self._descriptors else str(candidate),
                    os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_DIRECTORY,
                    **({"dir_fd": self._descriptors[-1]} if self._descriptors else {}),
                )
            self._paths.append(candidate)
            self._snapshots.append(info)
            self._descriptors.append(fd)
            self.verify()

    def close(self) -> None:
        for fd in reversed(self._descriptors):
            os.close(fd)
        self._descriptors.clear()


@contextmanager
def pin_directory(
    path: Path, *, create: bool = False,
    expected: tuple[tuple[Path, tuple[int, int, int]], ...] = (),
) -> Iterator[PinnedDirectory]:
    """Pin an absolute lexical chain; no symlink, junction or reparse traversal."""
    directory = PinnedDirectory()
    try:
        directory.open(path, create=create, expected=expected)
        yield directory
        directory.verify()
    except (_UnsafeInstructionPath, _ChangedInstructionPath, _NotRegularInstructionPath) as exc:
        raise FileAccessDenied("", "opened path failed identity verification") from exc
    finally:
        directory.close()


def read_verified_file(
    path: Path, *, protected_roots: Sequence[Path],
    exempt_roots: Sequence[Path] = (), permitted_roots: Sequence[Path] | None = None,
) -> VerifiedFileRead:
    """Reauthorize, pin and verify a full ordinary read, without new exemptions."""
    candidate = validate_read_location(path)
    resolved = resolve_read_path(
        str(candidate), protected_roots=protected_roots, exempt_roots=exempt_roots,
        permitted_roots=permitted_roots,
    )
    if resolved != candidate:
        raise FileAccessDenied("", "source path aliases another file")
    with pin_directory(candidate.parent) as directory:
        return directory.read_bytes(candidate.name)


def _decode_instruction_bytes(data: bytes, *, truncated: bool) -> BoundedTextRead:
    payload = data[:INSTRUCTION_FILE_BYTES]
    try:
        text = payload.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        # Only the terminal partial code point of a bounded prefix is withheld.
        # Any invalid interior byte invalidates the selected file, not fallback.
        if truncated and exc.reason == "unexpected end of data" and exc.end == len(exc.object):
            try:
                text = exc.object[:exc.start].decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                return BoundedTextRead(BoundedReadStatus.INVALID_UTF8, bytes_read=len(data))
        else:
            return BoundedTextRead(BoundedReadStatus.INVALID_UTF8, bytes_read=len(data))
    if any((ord(char) < 32 and char not in "\t\r\n") or 127 <= ord(char) <= 159 for char in text):
        return BoundedTextRead(BoundedReadStatus.BINARY, bytes_read=len(data))
    status = (
        BoundedReadStatus.TRUNCATED if truncated else
        BoundedReadStatus.OK if text.strip() else BoundedReadStatus.EMPTY
    )
    return BoundedTextRead(status, text=text, bytes_read=len(data))


def read_bounded_utf8(
    raw: str,
    *,
    authorized_root: Path,
    protected_roots: Sequence[Path],
    exempt_roots: Sequence[Path] = (),
    permitted_roots: Sequence[Path] | None = None,
) -> BoundedTextRead:
    """Authorize, pin and validate a regular-file handle before any byte read.

    At most 8,192 bytes plus one detection byte are read. The caller supplies
    authority explicitly; this API never selects cwd or creates exemptions.
    An observed name/identity/size/time change withholds the snapshot. This is
    not an atomic-snapshot promise against arbitrary in-place writers.
    """
    descriptors: list[int] = []
    selected = False
    bytes_read = 0
    try:
        candidate = _instruction_path(raw, authorized_root)
        paths = [*reversed(candidate.parents), candidate]
        snapshots: list[os.stat_result] = []
        for index, path in enumerate(paths):
            info = path.lstat()
            if _is_reparse(info):
                raise _UnsafeInstructionPath
            is_file = index == len(paths) - 1
            if not (stat.S_ISREG(info.st_mode) if is_file else stat.S_ISDIR(info.st_mode)):
                raise _NotRegularInstructionPath
            snapshots.append(info)
        selected = True
        resolved = resolve_read_path(
            str(candidate), protected_roots=protected_roots,
            exempt_roots=exempt_roots, permitted_roots=permitted_roots,
        )
        if resolved != candidate or not resolved.is_relative_to(authorized_root):
            raise _UnsafeInstructionPath
        for index, path in enumerate(paths):
            directory = index != len(paths) - 1
            if os.name == "nt":
                fd = _open_windows_instruction_path(path, directory=directory)
            else:
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
                flags |= os.O_DIRECTORY if directory else os.O_NONBLOCK
                fd = os.open(
                    str(path) if index == 0 else path.name, flags,
                    **({"dir_fd": descriptors[-1]} if descriptors else {}),
                )
            descriptors.append(fd)
        _validate_instruction_chain(paths, snapshots, descriptors)
        opened_snapshot = os.fstat(descriptors[-1])
        data = os.read(descriptors[-1], INSTRUCTION_FILE_BYTES + 1)
        bytes_read = len(data)
        _validate_instruction_chain(paths, snapshots, descriptors)
        if not _same_file(opened_snapshot, os.fstat(descriptors[-1])):
            raise _ChangedInstructionPath
        if len(data) < min(snapshots[-1].st_size, INSTRUCTION_FILE_BYTES + 1):
            result = BoundedTextRead(BoundedReadStatus.IO_ERROR, bytes_read=bytes_read)
        else:
            result = _decode_instruction_bytes(data, truncated=len(data) > INSTRUCTION_FILE_BYTES)
    except FileNotFoundError:
        result = BoundedTextRead(
            BoundedReadStatus.CHANGED if selected else BoundedReadStatus.ABSENT,
            bytes_read=bytes_read,
        )
    except FileAccessDenied:
        result = BoundedTextRead(BoundedReadStatus.DENIED)
    except _UnsafeInstructionPath:
        result = BoundedTextRead(BoundedReadStatus.UNSAFE_PATH, bytes_read=bytes_read)
    except _ChangedInstructionPath:
        result = BoundedTextRead(BoundedReadStatus.CHANGED, bytes_read=bytes_read)
    except _NotRegularInstructionPath:
        result = BoundedTextRead(BoundedReadStatus.NOT_REGULAR)
    except (ValueError, UnicodeError, RuntimeError):
        result = BoundedTextRead(BoundedReadStatus.INVALID_PATH)
    except OSError:
        result = BoundedTextRead(BoundedReadStatus.IO_ERROR, bytes_read=bytes_read)
    finally:
        for fd in reversed(descriptors):
            os.close(fd)
    if result.status not in (BoundedReadStatus.OK, BoundedReadStatus.EMPTY, BoundedReadStatus.ABSENT):
        logger.warning(
            "AD-1200: bounded repository-instruction read failed or is partial "
            "(%s); applicable rules may be unknown; returning a typed notice "
            "and only a validated prefix, never fallback content",
            result.status.value,
        )
    return result
