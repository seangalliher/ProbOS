"""AD-594a v1: ``[workspace:<id>/<path>]`` artifact-reference parser + renderer.

Pure string helpers — no I/O, no runtime, no records_store. Used by HXI message
rendering (consumer side, NOT in v1) to convert workspace refs into clickable
links. ``parse_workspace_refs`` extracts refs; ``render_workspace_refs_md``
substitutes refs with markdown links.

Integration hook (NOT shipped in v1): a HXI-side wrapper around
``MessageStore.create_post()`` body strings would call
``render_workspace_refs_md(body)`` before serving the body to the client. v1
ships the parser + renderer only; integration is a separate consumer task.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Match [workspace:<id>/<path>]. id = lowercase alphanumeric + hyphen + underscore.
# path = anything except ']' and whitespace.
_WORKSPACE_REF_RE = re.compile(
    r"\[workspace:([a-z0-9_-]+)/([^\]\s]+)\]",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class WorkspaceRef:
    """A parsed ``[workspace:<workspace_id>/<path>]`` reference."""
    workspace_id: str
    path: str

    def to_dict(self) -> dict[str, str]:
        return {"workspace_id": self.workspace_id, "path": self.path}


def parse_workspace_refs(text: str) -> list[WorkspaceRef]:
    """Extract all ``[workspace:<id>/<path>]`` refs from ``text``.

    Returns refs in the order they appear. Duplicates preserved.
    """
    if not text:
        return []
    return [
        WorkspaceRef(workspace_id=m.group(1), path=m.group(2))
        for m in _WORKSPACE_REF_RE.finditer(text)
    ]


def render_workspace_refs_md(text: str, *, base_url: str = "/api/consultations") -> str:
    """Replace each ``[workspace:<id>/<path>]`` ref with a markdown link.

    Output form: ``[<id>/<path>](<base_url>/<id>/files/<path>)``. Idempotent
    only on text containing no refs; calling twice on the same text rewrites
    already-rendered links (caller responsibility to apply once per body).
    """
    if not text:
        return text

    def _sub(m: "re.Match[str]") -> str:
        ws_id = m.group(1)
        path = m.group(2)
        return f"[{ws_id}/{path}]({base_url}/{ws_id}/files/{path})"

    return _WORKSPACE_REF_RE.sub(_sub, text)
