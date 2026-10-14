"""AD-1287 S2a: digests of two execution-profile components, computed from what is on disk or registered now.

``skill_resource_digest`` digests one cognitive skill's directory: each regular file under it by relative POSIX
path, sha256 and size in bytes, ascending by path, as RFC 8785 bytes under ``SKILL_RESOURCES_DOMAIN``. A symbolic link
or junction at the root or below it, an entry that is neither a regular file nor a directory, or a tree beyond the
file-count, byte or depth bound is refused with ``ComponentDigestError``; the enumeration never follows a link. The
files are then opened by path, so a link created after the enumeration and before a file is opened is not detected,
and that read goes where the path then leads.
Directories are not entries, so an empty directory does not change the digest. Bytes are digested as stored, so a
checkout with other line endings gives another digest.

``tool_schema_digest`` digests a tool's declared ``input_schema`` and ``output_schema`` together, as RFC 8785 bytes
under ``TOOL_SCHEMA_DOMAIN``. Both must be a ``dict``. Every value inside must be exactly a ``dict`` with ``str``
keys, a ``list`` or ``tuple``, a ``str``, an ``int``, a ``float``, a ``bool`` or ``None`` (a subclass such as an
enum member is refused), within the depth and node bounds, and canonicalisable.

Nothing here stores, decides or grants anything; ``profile_currency`` is the consumer.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Final

from probos.cognitive.elastic_team import canonicalize_projection

SKILL_RESOURCES_DOMAIN: Final = b"probos.execution_profile/skill_resources/v1\x00"
TOOL_SCHEMA_DOMAIN: Final = b"probos.execution_profile/tool_schema/v1\x00"

# bounds; not Final so a test can lower them (the S1 store's ``_MAX_SCAN`` convention)
MAX_SKILL_FILES = 256
MAX_SKILL_BYTES = 8 * 1024 * 1024
MAX_SKILL_DEPTH = 8
MAX_SCHEMA_DEPTH = 32
MAX_SCHEMA_NODES = 10_000

_JSON_SCALARS: Final = (str, int, float, bool)


class ComponentDigestError(ValueError):
    """A component cannot be digested under this module's rules; ``str(exc)`` is the stable code."""


def _is_link(entry: os.DirEntry[str]) -> bool:
    return entry.is_symlink() or entry.is_junction()


def _skill_files(root: Path) -> list[tuple[str, Path]]:
    """Every regular file under ``root`` as ``(relative POSIX path, path)``, ascending by relative path."""
    found: list[tuple[str, Path]] = []
    pending: list[tuple[Path, str, int]] = [(root, "", 0)]
    while pending:
        directory, prefix, depth = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                relative = prefix + entry.name
                if _is_link(entry):
                    raise ComponentDigestError("skill_resource_link_refused")
                if entry.is_dir(follow_symlinks=False):
                    if depth + 1 > MAX_SKILL_DEPTH:
                        raise ComponentDigestError("skill_resource_limit")
                    pending.append((Path(entry.path), relative + "/", depth + 1))
                elif entry.is_file(follow_symlinks=False):
                    found.append((relative, Path(entry.path)))
                    if len(found) > MAX_SKILL_FILES:
                        raise ComponentDigestError("skill_resource_limit")
                else:
                    raise ComponentDigestError("skill_resource_not_regular")
    found.sort(key=lambda item: item[0])
    return found


def skill_resource_digest(skill_dir: Path) -> str:
    """The resource digest of the skill directory ``skill_dir``, read now (see the module docstring).

    Raises:
        TypeError: ``skill_resource_dir_invalid`` when ``skill_dir`` is not a ``Path``.
        ComponentDigestError: ``skill_resource_dir_invalid`` (not a directory, or a link),
            ``skill_resource_link_refused``, ``skill_resource_not_regular`` or ``skill_resource_limit``.
        OSError: a directory or file could not be read.
        ValueError: a path the canonicaliser cannot encode (a lone surrogate).
    """
    if not isinstance(skill_dir, Path):
        raise TypeError("skill_resource_dir_invalid")
    if skill_dir.is_symlink() or skill_dir.is_junction() or not skill_dir.is_dir():
        raise ComponentDigestError("skill_resource_dir_invalid")
    manifest: list[dict[str, Any]] = []
    total = 0
    for relative, path in _skill_files(skill_dir):
        remaining = MAX_SKILL_BYTES - total
        with path.open("rb") as handle:
            data = handle.read(remaining + 1)
        if len(data) > remaining:
            raise ComponentDigestError("skill_resource_limit")
        total += len(data)
        manifest.append({"path": relative, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)})
    return hashlib.sha256(SKILL_RESOURCES_DOMAIN + canonicalize_projection({"files": manifest})).hexdigest()


def _check_json(value: Any, depth: int, budget: list[int]) -> None:
    """Refuse ``value`` unless it is exactly JSON-shaped within the bounds; ``budget[0]`` counts the nodes left."""
    budget[0] -= 1
    if budget[0] < 0 or depth > MAX_SCHEMA_DEPTH:
        raise ComponentDigestError("tool_schema_invalid")
    kind = type(value)
    if kind is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ComponentDigestError("tool_schema_invalid")
            _check_json(item, depth + 1, budget)
    elif kind is list or kind is tuple:
        for item in value:
            _check_json(item, depth + 1, budget)
    elif kind not in _JSON_SCALARS and value is not None:
        raise ComponentDigestError("tool_schema_invalid")


def tool_schema_digest(input_schema: Any, output_schema: Any) -> str:
    """The schema digest of a tool declaring ``input_schema`` and ``output_schema`` (see the module docstring).

    Raises:
        ComponentDigestError: ``tool_schema_invalid``.
    """
    budget = [MAX_SCHEMA_NODES]
    for schema in (input_schema, output_schema):
        if type(schema) is not dict:
            raise ComponentDigestError("tool_schema_invalid")
        _check_json(schema, 1, budget)
    try:
        canonical = canonicalize_projection({"input_schema": input_schema, "output_schema": output_schema})
    except ValueError as exc:  # NaN or an infinity, an int outside the I-JSON range, or a lone surrogate
        raise ComponentDigestError("tool_schema_invalid") from exc
    return hashlib.sha256(TOOL_SCHEMA_DOMAIN + canonical).hexdigest()
