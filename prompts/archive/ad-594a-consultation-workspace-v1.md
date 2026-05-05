# AD-594a v1 — Consultation Workspace (Session-Scoped Shared Workspace in Ship's Records)

**Issue:** #160 — Part of AD-594 Crew Consultation Protocol.
**Wave:** 44.
**Scope tier:** **FULL v1** (Captain "no trivial deferral" convention). Producer + workspace API + lifecycle + InputProcessor seam + templates + ref parser/renderer all ship in one Builder cycle.
**Sibling ADs are SEPARATE GH issues** — AD-594b (#161 consultation primitive), AD-594c (#162 parallel execution dispatch), AD-594d (#163 delivery pipeline). They are LEGITIMATELY out of scope here. Do NOT smuggle their work in.
**Estimated tests:** 16 (over Captain's 14 floor by 2).
**Dependencies:** AD-434 Ship's Records (`RecordsStore`) — VERIFIED SHIPPED. Northstar II Transporter Pattern for input processing — NOT SHIPPED for this domain (architect call DLog #2). AD-594a v1 ships the `InputProcessor` Protocol seam with one passthrough impl; PDF/image processors plug in here later under a separate AD.

---

## Verify-First Findings (Decision Log)

Anchors verified at HEAD `c0a963f` (post-Wave 43).

### DLog #1 — `RecordsStore` is `runtime.records_store` (public property)
- `RecordsStore` class at `src/probos/knowledge/records_store.py:46`.
- Public surfaces consumed by AD-594a: `repo_path` property `:62`, `_safe_path` `:893` (private; do NOT call from outside RecordsStore — instead consume the new public surfaces this prompt adds in **Section 1**).
- `_SUBDIRS` tuple at `:15` enumerates init-created top-level subdirs; `consultations` is NOT present. **Section 1** appends `"consultations"` to this tuple — mirrors `bills` AD-618a precedent.
- All file writes today coerce YAML frontmatter (`write_entry` `:89`). For workspace files (`manifest.yaml`, `journal.md`, `delivery.yaml`, `workitems/*.yaml`) this is the wrong shape. **Section 1** adds three new public methods to `RecordsStore` — `write_workspace_file` / `read_workspace_file` / `append_workspace_file` — that bypass frontmatter coercion, reuse `_safe_path` for traversal protection, and call the existing private `_commit` for git plumbing. WorkspaceRegistry consumes ONLY these public surfaces (Demeter clean).
- `runtime.records_store` is the public property at `runtime.py:960`; backed by `_records_store` adopted from cognitive phase at `runtime.py:1324`. Finalize phase runs after this — wirer is safe.

### DLog #2 — Northstar II / Transporter Pattern is NOT shipped for input processing
- Grep on `transporter|Transporter|InputProcessor|Northstar` returns ONLY:
  - `events.py:57-62` — `TRANSPORTER_*` EventTypes for **builder code-chunk decomposition**.
  - `cognitive/builder.py:325/343/449/643+` — `BuildChunk` / `ChunkResult` for **parallel chunk execution during code generation**.
- The roadmap text at `docs/development/roadmap.md:4837` references "Transporter Pattern (Northstar II) for PDF→text, image→description" — that's a **DIFFERENT future domain** (input ingestion) and there is NO such infrastructure shipped. Naming collision is intentional Star-Trek-flavor; ProbOS-level it's two separate concepts.
- **Decision:** AD-594a v1 ships the `InputProcessor` Protocol seam in `consultation/inputs.py` with one `PassthroughTextProcessor` impl. Future PDF/image processors (a separate AD) plug into this seam. Module docstring documents the future expansion path. NO deferral of the seam itself — it IS the integration point.

### DLog #3 — Ward Room has NO server-side message renderer
- Grep on `ward_room.*render|message_render|render_message` returns nothing for ward_room messages.
- `MessageStore.create_post()` at `ward_room/messages.py:153` stores the raw text body; rendering is **HXI/web-client side**.
- **Decision:** AD-594a ships `parse_workspace_refs` + `render_workspace_refs_md` as a pure helper module (`consultation/refs.py`). Integration into HXI message rendering is **OUT OF SCOPE for v1** (a separate consumer task on the HXI side). Module docstring documents the integration hook — a renderer wrapping `MessageStore.create_post` body strings would call `render_workspace_refs_md(body)` to produce markdown links suitable for HXI display. v1 does NOT add this wrapper.
- Do NOT modify `ward_room/messages.py` or `ward_room/service.py` in this AD.

### DLog #4 — `pyyaml>=6.0` is a hard dep
- `pyproject.toml:26`. `import yaml` already in `records_store.py:10`, `config.py:9`, `ontology/loader.py:12`, others. Use `yaml.safe_load` / `yaml.safe_dump`.

### DLog #5 — Finalize cascade slot
- `_wire_clinical_telemetry` at `startup/finalize.py:494` invoked at `:812`. **Section 4** wirer `_wire_consultation_workspaces` mirrors that shape (sync) and is invoked AFTER `_wire_clinical_telemetry` and BEFORE `_wire_workspace_ontology` (`:815`).
- `runtime.records_store` adopted at `runtime.py:1324` (cognitive phase), well before finalize. No phase-ordering risk.

### DLog #6 — Config insertion site
- `clinical_telemetry: ClinicalTelemetryConfig` at `config.py:2226` declared via `Field(default_factory=...)`. **Section 3** inserts `consultation_workspaces: ConsultationWorkspaceConfig = Field(default_factory=ConsultationWorkspaceConfig)` adjacent (immediately after `clinical_telemetry`). Config class itself defined adjacent to `ClinicalTelemetryConfig` (`config.py:1876`).
- `ConsultationWorkspaceConfig.enabled: bool = True` deviation from Wave 10 transitional-flag convention is INTENTIONAL — registry is read-only on boot (constructs an empty in-memory registry; only side-effect is `RecordsStore` ensuring `consultations/` directory exists, which is a one-line `mkdir -p`-equivalent at first init). Same precedent as `KnowledgeEdgesConfig` / `EdgeBackfillConfig`. Documented in config docstring.

### DLog #7 — No similar CRUD-over-directory registry pattern in tree
- Closest sibling is `creative/output_writer.py:46` (constructor injection of `records_store`, `_resolve_records_store` fallback). Mirrored for `WorkspaceRegistry` ctor.
- `procedure_store` and `work_item_store` are SQLite-backed, not directory-backed — different pattern.

### DLog #8 — `runtime.consultation_workspaces` collision check
- Grep confirms NO existing `consultation_workspaces` attribute on runtime. Public attribute set by wirer is collision-free.

### DLog #9 — `add_plan_iteration` versioning is filename-based
- v1 atomic versioning: scan `plan/` for files matching `plan_v*.md`, parse trailing integer, write `plan_v{N+1}.md`. No metadata file. First iteration → `plan_v1.md`.

### DLog #10 — `add_work_item` is YAML, not Markdown
- `workitems/*.yaml` files are spec dictionaries serialized via `yaml.safe_dump`. v1 does NOT integrate with `WorkItemStore` (AD-594c territory). Filename: `wi_{spec_id_or_uuid4_hex8}.yaml`.

### DLog #11 — Templates are functions, not file copies
- `consultation/templates.py` exports `TEMPLATES: dict[str, Callable[[], str]]` with three keys (`security_review`, `technical_design`, `incident_response`). Each function returns a markdown skeleton string. WorkspaceRegistry.create() calls `TEMPLATES[template]()` and writes the result to `plan/plan_v1.md` if `template` is set.
- Artifact-type render functions (`render_advisory_report`, etc.) are also pure string-returning functions in the same module. Used by convenience methods to format inputs.

### DLog #12 — Lifecycle state machine
- `WorkspaceLifecycleState` IntEnum (7 values). `ALLOWED_TRANSITIONS: dict[WorkspaceLifecycleState, frozenset[WorkspaceLifecycleState]]` adjacency map. `transition_to()` validates predecessor; on success: updates `manifest.lifecycle_state`, refreshes `manifest.updated_at`, persists manifest.yaml, appends a journal entry. Invalid → returns `False` + WARNING log; never raises.

---

## Section 0 — New EventTypes

**None.** AD-594a v1 emits no EventTypes. Activity is journaled to `journal.md` per workspace; cross-mesh observability is deferred to AD-594b/c.

---

## Section 1 — Extend `RecordsStore` with raw-file surfaces + `consultations/` subdir

### 1a — Add `consultations` to `_SUBDIRS`

File: `src/probos/knowledge/records_store.py`

```
===SEARCH===
_SUBDIRS = (
    "captains-log",
    "notebooks",
    "reports",
    "duty-logs",
    "operations",
    "manuals",
    "bills",        # AD-618a: Standard Operating Procedures (raw YAML, not markdown)
    "_archived",
)
===REPLACE===
_SUBDIRS = (
    "captains-log",
    "notebooks",
    "reports",
    "duty-logs",
    "operations",
    "manuals",
    "bills",          # AD-618a: Standard Operating Procedures (raw YAML, not markdown)
    "consultations",  # AD-594a: Session-scoped consultation workspaces (raw files; per-workspace subdirs)
    "_archived",
)
===END REPLACE===
```

### 1b — Add three public raw-file methods on `RecordsStore`

Insert IMMEDIATELY BEFORE `def _parse_document` at `records_store.py:881`. These methods bypass frontmatter coercion (workspace files are YAML/Markdown of varied shapes; the records-store frontmatter format is the wrong wrapper) and reuse existing `_safe_path` + `_commit` plumbing.

```
===SEARCH===
    def _parse_document(self, raw: str) -> tuple[dict, str]:
        """Parse YAML frontmatter + content from a markdown document."""
===REPLACE===
    # ------------------------------------------------------------------
    # AD-594a: Raw-file surfaces (no frontmatter coercion)
    # Used by ConsultationWorkspace for manifest.yaml / journal.md / plan files /
    # work-item YAML / per-advisory artifacts. Reuses _safe_path for traversal
    # protection and _commit for the git plumbing. Never raises path-traversal
    # errors silently — _safe_path raises ValueError; callers (WorkspaceRegistry)
    # treat that as a programmer error.
    # ------------------------------------------------------------------
    async def write_workspace_file(
        self,
        author: str,
        path: str,
        content: str,
        message: str,
    ) -> str:
        """AD-594a: Write a raw text file (no YAML frontmatter wrapper).

        Args:
            author: Author identity for the git commit.
            path: Repo-relative path (e.g. ``consultations/<id>/manifest.yaml``).
            content: Raw text to write (UTF-8). For binary use, encode upstream.
            message: Commit message body.

        Returns the relative path of the written file.
        """
        file_path = self._safe_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        if self._config.auto_commit:
            await self._git("add", path)
            await self._commit(f"[records] {message} — by {author}")
        logger.debug("AD-594a: workspace file written: %s by %s", path, author)
        return path

    async def read_workspace_file(self, path: str) -> str | None:
        """AD-594a: Read a raw text file. Returns None if missing."""
        file_path = self._safe_path(path)
        if not file_path.exists():
            return None
        return file_path.read_text(encoding="utf-8")

    async def append_workspace_file(
        self,
        author: str,
        path: str,
        content: str,
        message: str,
    ) -> str:
        """AD-594a: Append text to a raw file (e.g. journal.md). Creates if absent."""
        file_path = self._safe_path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with file_path.open("a", encoding="utf-8") as fh:
            fh.write(content)
        if self._config.auto_commit:
            await self._git("add", path)
            await self._commit(f"[records] {message} — by {author}")
        logger.debug("AD-594a: workspace file appended: %s by %s", path, author)
        return path

    def _parse_document(self, raw: str) -> tuple[dict, str]:
        """Parse YAML frontmatter + content from a markdown document."""
===END REPLACE===
```

---

## Section 2 — `consultation/` package: types, refs, inputs, templates, workspace

### 2a — `src/probos/consultation/__init__.py` (NEW FILE)

```python
"""AD-594a v1: Consultation workspace primitives.

Session-scoped shared workspace in Ship's Records for multi-agent advisory
consultations. See ``ConsultationWorkspace`` and ``WorkspaceRegistry``.

This module is the substrate; the consultation primitive (AD-594b), parallel
execution dispatch (AD-594c), and delivery pipeline (AD-594d) are tracked under
separate GH issues (#161, #162, #163) and are NOT in v1 scope.
"""
from __future__ import annotations

from probos.consultation.inputs import InputProcessor, PassthroughTextProcessor
from probos.consultation.refs import (
    WorkspaceRef,
    parse_workspace_refs,
    render_workspace_refs_md,
)
from probos.consultation.templates import (
    ArtifactType,
    TEMPLATES,
    render_advisory_report,
    render_decision_record,
    render_plan_document,
    render_supporting_data,
    render_work_item_spec,
)
from probos.consultation.workspace import (
    ConsultationWorkspace,
    ConsultationWorkspaceSummary,
    WorkspaceLifecycleState,
    WorkspaceRegistry,
)

__all__ = [
    "ArtifactType",
    "ConsultationWorkspace",
    "ConsultationWorkspaceSummary",
    "InputProcessor",
    "PassthroughTextProcessor",
    "TEMPLATES",
    "WorkspaceLifecycleState",
    "WorkspaceRef",
    "WorkspaceRegistry",
    "parse_workspace_refs",
    "render_advisory_report",
    "render_decision_record",
    "render_plan_document",
    "render_supporting_data",
    "render_work_item_spec",
    "render_workspace_refs_md",
]
```

### 2b — `src/probos/consultation/refs.py` (NEW FILE)

```python
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
```

### 2c — `src/probos/consultation/inputs.py` (NEW FILE)

```python
"""AD-594a v1: ``InputProcessor`` Protocol seam + passthrough text impl.

Captain ships a Protocol seam in v1 so the workspace API has a stable
integration point for future PDF / image / audio processors. v1 ships
``PassthroughTextProcessor`` only; future processors (separate AD) plug in
here. The ``Northstar II Transporter Pattern`` referenced in the AD-594
roadmap entry is a forthcoming input-ingestion subsystem; today's
``cognitive/builder.py`` Transporter Pattern is unrelated (builder code-chunk
decomposition).
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class InputProcessor(Protocol):
    """Process a staged input (filename + raw bytes) into agent-readable form.

    Implementations may rewrite the filename (e.g. ``report.pdf`` →
    ``report.pdf.txt``) and transform the bytes (e.g. PDF extraction). v1
    contract is text-bytes-in / text-bytes-out; binary outputs must be
    encoded by the implementation.
    """

    def process(self, filename: str, content: bytes) -> tuple[str, bytes]:
        ...


class PassthroughTextProcessor:
    """v1 default: returns input unchanged.

    Filename and content are passed through verbatim. Used when no real
    processor is configured. Suitable for plain-text inputs.
    """

    name = "passthrough"

    def process(self, filename: str, content: bytes) -> tuple[str, bytes]:
        return filename, content


def build_input_processor(name: str) -> InputProcessor:
    """Resolve a registered processor name to an instance.

    v1 only knows ``"passthrough"``. Unknown names log-and-degrade to
    PassthroughTextProcessor so misconfiguration cannot break the workspace.
    """
    import logging
    logger = logging.getLogger(__name__)
    if name == "passthrough":
        return PassthroughTextProcessor()
    logger.warning(
        "AD-594a: unknown input_processor=%r; falling back to passthrough", name
    )
    return PassthroughTextProcessor()
```

### 2d — `src/probos/consultation/templates.py` (NEW FILE)

```python
"""AD-594a v1: Standardized artifact-type render helpers + consultation templates.

Five artifact types (``ArtifactType``) each have a pure render function returning
a markdown skeleton string. Three consultation templates (security_review,
technical_design, incident_response) are exposed via the ``TEMPLATES`` dict;
each renders an initial ``plan_v1.md`` skeleton when a workspace is created
with ``template=<name>``.
"""
from __future__ import annotations

from enum import Enum
from typing import Callable


class ArtifactType(str, Enum):
    """v1 standardized artifact types.

    Storage layout: each type lives under a dedicated workspace subdirectory
    (advisory/, plan/, workitems/, artifacts/, outputs/). The enum values are
    the canonical short names used in journal entries and (future) HXI
    rendering.
    """
    ADVISORY_REPORT = "advisory_report"
    PLAN_DOCUMENT = "plan_document"
    WORK_ITEM_SPEC = "work_item_spec"
    SUPPORTING_DATA = "supporting_data"
    DECISION_RECORD = "decision_record"


def render_advisory_report(*, agent_id: str, summary: str, body: str) -> str:
    """Render an ADVISORY_REPORT markdown skeleton."""
    return (
        f"# Advisory Report — {agent_id}\n\n"
        f"## Summary\n\n{summary.strip()}\n\n"
        f"## Detail\n\n{body.strip()}\n"
    )


def render_plan_document(*, title: str, sections: list[tuple[str, str]]) -> str:
    """Render a PLAN_DOCUMENT markdown skeleton from (heading, body) sections."""
    lines = [f"# Plan — {title}\n"]
    for heading, body in sections:
        lines.append(f"## {heading.strip()}\n\n{body.strip()}\n")
    return "\n".join(lines)


def render_work_item_spec(*, work_item_id: str, summary: str, body: str) -> str:
    """Render a WORK_ITEM_SPEC markdown preamble (the YAML payload is separate)."""
    return (
        f"# Work Item — {work_item_id}\n\n"
        f"**Summary:** {summary.strip()}\n\n"
        f"## Details\n\n{body.strip()}\n"
    )


def render_supporting_data(*, title: str, body: str) -> str:
    """Render a SUPPORTING_DATA markdown skeleton."""
    return f"# Supporting Data — {title}\n\n{body.strip()}\n"


def render_decision_record(*, decision: str, rationale: str, dissent: str = "") -> str:
    """Render a DECISION_RECORD markdown skeleton."""
    out = (
        f"# Decision Record\n\n"
        f"## Decision\n\n{decision.strip()}\n\n"
        f"## Rationale\n\n{rationale.strip()}\n"
    )
    if dissent.strip():
        out += f"\n## Dissent\n\n{dissent.strip()}\n"
    return out


def _security_review() -> str:
    return (
        "# Security Review — Consultation Plan\n\n"
        "## Threat Model\n\n_TBD by advisor_\n\n"
        "## Attack Surface\n\n_TBD by advisor_\n\n"
        "## Controls\n\n_TBD by advisor_\n\n"
        "## Open Questions\n\n_TBD by advisor_\n"
    )


def _technical_design() -> str:
    return (
        "# Technical Design — Consultation Plan\n\n"
        "## Problem Statement\n\n_TBD by advisor_\n\n"
        "## Proposed Architecture\n\n_TBD by advisor_\n\n"
        "## Trade-offs\n\n_TBD by advisor_\n\n"
        "## Validation Plan\n\n_TBD by advisor_\n"
    )


def _incident_response() -> str:
    return (
        "# Incident Response — Consultation Plan\n\n"
        "## Incident Summary\n\n_TBD by advisor_\n\n"
        "## Containment Steps\n\n_TBD by advisor_\n\n"
        "## Root Cause Analysis\n\n_TBD by advisor_\n\n"
        "## Remediation\n\n_TBD by advisor_\n"
    )


TEMPLATES: dict[str, Callable[[], str]] = {
    "security_review": _security_review,
    "technical_design": _technical_design,
    "incident_response": _incident_response,
}
```

### 2e — `src/probos/consultation/workspace.py` (NEW FILE)

```python
"""AD-594a v1: ConsultationWorkspace + WorkspaceRegistry.

Session-scoped shared workspace in Ship's Records. Each workspace lives at
``consultations/<workspace_id>/`` with subdirectories ``inputs/``, ``advisory/``,
``plan/``, ``artifacts/``, ``outputs/``, ``workitems/`` plus ``manifest.yaml``,
``journal.md``, and ``delivery.yaml`` (placeholder until AD-594d).

All file I/O routes through ``RecordsStore.write_workspace_file`` /
``read_workspace_file`` / ``append_workspace_file`` (added by AD-594a; raw,
no frontmatter coercion).
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable

import yaml

from probos.consultation.inputs import (
    InputProcessor,
    PassthroughTextProcessor,
    build_input_processor,
)
from probos.consultation.templates import (
    ArtifactType,
    TEMPLATES,
    render_advisory_report,
)

logger = logging.getLogger(__name__)

_WORKSPACE_SUBDIRS = ("inputs", "advisory", "plan", "artifacts", "outputs", "workitems")
_MANIFEST_SCHEMA_VERSION = 1


class WorkspaceLifecycleState(IntEnum):
    INITIATED = 0
    CONSULTING = 1
    PLAN_REVIEW = 2
    APPROVED = 3
    EXECUTING = 4
    COMPLETED = 5
    ARCHIVED = 6


_ALLOWED_TRANSITIONS: dict[WorkspaceLifecycleState, frozenset[WorkspaceLifecycleState]] = {
    WorkspaceLifecycleState.INITIATED: frozenset({WorkspaceLifecycleState.CONSULTING}),
    WorkspaceLifecycleState.CONSULTING: frozenset({WorkspaceLifecycleState.PLAN_REVIEW}),
    WorkspaceLifecycleState.PLAN_REVIEW: frozenset({
        WorkspaceLifecycleState.APPROVED,
        WorkspaceLifecycleState.CONSULTING,  # back for revision
    }),
    WorkspaceLifecycleState.APPROVED: frozenset({WorkspaceLifecycleState.EXECUTING}),
    WorkspaceLifecycleState.EXECUTING: frozenset({WorkspaceLifecycleState.COMPLETED}),
    WorkspaceLifecycleState.COMPLETED: frozenset({WorkspaceLifecycleState.ARCHIVED}),
    WorkspaceLifecycleState.ARCHIVED: frozenset(),  # terminal
}


@dataclass(frozen=True)
class ConsultationWorkspaceSummary:
    """Lightweight projection used by ``WorkspaceRegistry.list_active``."""
    id: str
    title: str
    state: WorkspaceLifecycleState
    owner: str
    participant_count: int
    created_at: float
    updated_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "state": self.state.name,
            "owner": self.owner,
            "participant_count": self.participant_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _safe_filename_segment(s: str) -> str:
    """Strip path-traversal characters from a caller-supplied filename."""
    out = s.replace("\\", "/").split("/")[-1]
    out = out.replace("..", "").strip()
    if not out:
        raise ValueError(f"invalid filename segment: {s!r}")
    return out


class ConsultationWorkspace:
    """One consultation workspace under ``consultations/<workspace_id>/``."""

    def __init__(
        self,
        workspace_id: str,
        *,
        records_store: Any,
        root_path: str,
        manifest: dict[str, Any],
        clock: Callable[[], float],
        input_processor: InputProcessor | None = None,
    ) -> None:
        self._id = workspace_id
        self._records = records_store
        self._root = f"{root_path}/{workspace_id}"
        self._manifest = manifest
        self._clock = clock
        self._input_processor = input_processor or PassthroughTextProcessor()

    @property
    def id(self) -> str:
        return self._id

    @property
    def root_path(self) -> str:
        return self._root

    @property
    def manifest(self) -> dict[str, Any]:
        return dict(self._manifest)  # defensive copy

    @property
    def lifecycle_state(self) -> WorkspaceLifecycleState:
        return WorkspaceLifecycleState[self._manifest["lifecycle_state"]]

    # ------------------------------------------------------------------
    # Convenience writers (each appends a journal entry)
    # ------------------------------------------------------------------
    async def add_input(
        self, filename: str, content: bytes, *, agent_id: str = "captain"
    ) -> str:
        """Stage an input file. Routes through ``InputProcessor.process``."""
        processed_name, processed_bytes = self._input_processor.process(filename, content)
        safe = _safe_filename_segment(processed_name)
        path = f"{self._root}/inputs/{safe}"
        # Decode as utf-8 if possible; passthrough writes the raw text
        text = processed_bytes.decode("utf-8", errors="replace")
        await self._records.write_workspace_file(
            agent_id, path, text, f"AD-594a: input added to {self._id}",
        )
        await self.append_journal(f"input added: {safe}", agent_id=agent_id)
        return path

    async def add_advisory(
        self, agent_id: str, content: str, *, summary: str = ""
    ) -> str:
        """Add an advisory contribution. Filename: ``{agent_id}_{ts}.md``."""
        ts = self._clock()
        safe_agent = _safe_filename_segment(agent_id)
        ts_token = f"{int(ts * 1000):013d}"
        rendered = render_advisory_report(
            agent_id=agent_id, summary=summary or "(no summary)", body=content,
        )
        path = f"{self._root}/advisory/{safe_agent}_{ts_token}.md"
        await self._records.write_workspace_file(
            agent_id, path, rendered, f"AD-594a: advisory by {agent_id} on {self._id}",
        )
        await self.append_journal(f"advisory by {agent_id}", agent_id=agent_id)
        return path

    async def add_plan_iteration(
        self, content: str, *, agent_id: str = "captain"
    ) -> str:
        """Append the next ``plan_v{N}.md`` iteration."""
        next_n = await self._next_plan_version()
        path = f"{self._root}/plan/plan_v{next_n}.md"
        await self._records.write_workspace_file(
            agent_id, path, content, f"AD-594a: plan v{next_n} for {self._id}",
        )
        await self.append_journal(f"plan_v{next_n} written", agent_id=agent_id)
        return path

    async def add_artifact(
        self, filename: str, content: str, *, agent_id: str = "captain"
    ) -> str:
        safe = _safe_filename_segment(filename)
        path = f"{self._root}/artifacts/{safe}"
        await self._records.write_workspace_file(
            agent_id, path, content, f"AD-594a: artifact {safe} on {self._id}",
        )
        await self.append_journal(f"artifact added: {safe}", agent_id=agent_id)
        return path

    async def add_output(
        self, filename: str, content: str, *, agent_id: str = "captain"
    ) -> str:
        safe = _safe_filename_segment(filename)
        path = f"{self._root}/outputs/{safe}"
        await self._records.write_workspace_file(
            agent_id, path, content, f"AD-594a: output {safe} on {self._id}",
        )
        await self.append_journal(f"output added: {safe}", agent_id=agent_id)
        return path

    async def add_work_item(
        self, spec: dict[str, Any], *, agent_id: str = "captain"
    ) -> str:
        """Persist a work-item spec dict as YAML under ``workitems/``."""
        wi_id = str(spec.get("id") or uuid.uuid4().hex[:8])
        safe = _safe_filename_segment(f"wi_{wi_id}.yaml")
        path = f"{self._root}/workitems/{safe}"
        text = yaml.safe_dump(spec, sort_keys=False, default_flow_style=False)
        await self._records.write_workspace_file(
            agent_id, path, text, f"AD-594a: work_item {wi_id} on {self._id}",
        )
        await self.append_journal(f"work_item added: {wi_id}", agent_id=agent_id)
        return path

    # ------------------------------------------------------------------
    # State machine + journal
    # ------------------------------------------------------------------
    async def transition_to(
        self, state: WorkspaceLifecycleState, *, agent_id: str = "captain"
    ) -> bool:
        """Transition lifecycle state. Returns False on invalid transition."""
        current = self.lifecycle_state
        if state not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
            logger.warning(
                "AD-594a: invalid lifecycle transition %s -> %s for workspace %s",
                current.name, state.name, self._id,
            )
            return False
        self._manifest["lifecycle_state"] = state.name
        self._manifest["updated_at"] = self._clock()
        await self._persist_manifest(agent_id=agent_id)
        await self.append_journal(
            f"lifecycle: {current.name} -> {state.name}", agent_id=agent_id,
        )
        return True

    async def append_journal(self, message: str, *, agent_id: str) -> None:
        """Append a chronological entry to ``journal.md``."""
        ts = self._clock()
        line = f"- {ts:.3f} [{agent_id}] {message}\n"
        path = f"{self._root}/journal.md"
        try:
            await self._records.append_workspace_file(
                agent_id, path, line, f"AD-594a: journal on {self._id}",
            )
        except Exception:
            logger.warning(
                "AD-594a: failed to append journal for workspace %s", self._id,
                exc_info=True,
            )

    async def list_paths(self) -> dict[str, list[str]]:
        """Snapshot of files under each subdirectory (relative names)."""
        out: dict[str, list[str]] = {}
        repo_root = self._records.repo_path  # Path
        for sub in _WORKSPACE_SUBDIRS:
            d = repo_root / "consultations" / self._id / sub
            if not d.exists():
                out[sub] = []
                continue
            out[sub] = sorted(p.name for p in d.iterdir() if p.is_file())
        return out

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    async def _next_plan_version(self) -> int:
        repo_root = self._records.repo_path
        plan_dir = repo_root / "consultations" / self._id / "plan"
        if not plan_dir.exists():
            return 1
        max_v = 0
        for p in plan_dir.iterdir():
            if p.is_file() and p.name.startswith("plan_v") and p.name.endswith(".md"):
                try:
                    n = int(p.name[len("plan_v"):-len(".md")])
                except ValueError:
                    continue
                if n > max_v:
                    max_v = n
        return max_v + 1

    async def _persist_manifest(self, *, agent_id: str) -> None:
        text = yaml.safe_dump(self._manifest, sort_keys=False, default_flow_style=False)
        await self._records.write_workspace_file(
            agent_id,
            f"{self._root}/manifest.yaml",
            text,
            f"AD-594a: manifest update for {self._id}",
        )


class WorkspaceRegistry:
    """Create / look up consultation workspaces under ``consultations/``."""

    def __init__(
        self,
        records_store: Any,
        *,
        root_path: str = "consultations",
        clock: Callable[[], float] = time.time,
        input_processor: InputProcessor | None = None,
    ) -> None:
        if records_store is None:
            raise ValueError("WorkspaceRegistry requires a records_store")
        self._records = records_store
        self._root_path = root_path
        self._clock = clock
        self._input_processor = input_processor or PassthroughTextProcessor()
        self._cache: dict[str, ConsultationWorkspace] = {}

    async def create(
        self,
        *,
        title: str,
        owner_agent_id: str,
        participants: list[str],
        template: str | None = None,
    ) -> ConsultationWorkspace:
        """Create a new workspace; returns the live ``ConsultationWorkspace``."""
        workspace_id = uuid.uuid4().hex[:12]
        now = self._clock()
        manifest: dict[str, Any] = {
            "schema_version": _MANIFEST_SCHEMA_VERSION,
            "id": workspace_id,
            "title": title,
            "owner": owner_agent_id,
            "participants": list(participants),
            "lifecycle_state": WorkspaceLifecycleState.INITIATED.name,
            "created_at": now,
            "updated_at": now,
            "template": template or "",
        }
        ws = ConsultationWorkspace(
            workspace_id,
            records_store=self._records,
            root_path=self._root_path,
            manifest=manifest,
            clock=self._clock,
            input_processor=self._input_processor,
        )
        # Materialize subdirectories by writing a .gitkeep into each (raw write
        # creates parent dirs); manifest + journal land in the root.
        for sub in _WORKSPACE_SUBDIRS:
            await self._records.write_workspace_file(
                owner_agent_id,
                f"{self._root_path}/{workspace_id}/{sub}/.gitkeep",
                "",
                f"AD-594a: init {sub}/ for {workspace_id}",
            )
        await ws._persist_manifest(agent_id=owner_agent_id)
        # Empty delivery.yaml placeholder (AD-594d will populate)
        await self._records.write_workspace_file(
            owner_agent_id,
            f"{self._root_path}/{workspace_id}/delivery.yaml",
            "# AD-594d delivery configuration (placeholder; not in v1)\n",
            f"AD-594a: delivery placeholder for {workspace_id}",
        )
        await ws.append_journal(
            f"workspace created (template={template or 'none'})",
            agent_id=owner_agent_id,
        )
        if template and template in TEMPLATES:
            try:
                skeleton = TEMPLATES[template]()
                await ws.add_plan_iteration(skeleton, agent_id=owner_agent_id)
            except Exception:
                logger.warning(
                    "AD-594a: failed to apply template %r on workspace %s",
                    template, workspace_id, exc_info=True,
                )
        elif template:
            logger.warning(
                "AD-594a: unknown template %r on workspace %s; ignored",
                template, workspace_id,
            )
        self._cache[workspace_id] = ws
        return ws

    async def get(self, workspace_id: str) -> ConsultationWorkspace | None:
        if workspace_id in self._cache:
            return self._cache[workspace_id]
        manifest = await self._load_manifest(workspace_id)
        if manifest is None:
            return None
        ws = ConsultationWorkspace(
            workspace_id,
            records_store=self._records,
            root_path=self._root_path,
            manifest=manifest,
            clock=self._clock,
            input_processor=self._input_processor,
        )
        self._cache[workspace_id] = ws
        return ws

    async def list_active(self) -> list[ConsultationWorkspaceSummary]:
        """List workspaces whose state is not ARCHIVED."""
        repo_root = self._records.repo_path
        cons_root = repo_root / self._root_path
        if not cons_root.exists():
            return []
        out: list[ConsultationWorkspaceSummary] = []
        for entry in sorted(cons_root.iterdir()):
            if not entry.is_dir():
                continue
            manifest = await self._load_manifest(entry.name)
            if manifest is None:
                continue
            state_name = manifest.get("lifecycle_state", "INITIATED")
            try:
                state = WorkspaceLifecycleState[state_name]
            except KeyError:
                continue
            if state == WorkspaceLifecycleState.ARCHIVED:
                continue
            out.append(ConsultationWorkspaceSummary(
                id=manifest["id"],
                title=manifest.get("title", ""),
                state=state,
                owner=manifest.get("owner", ""),
                participant_count=len(manifest.get("participants", [])),
                created_at=manifest.get("created_at", 0.0),
                updated_at=manifest.get("updated_at", 0.0),
            ))
        return out

    async def _load_manifest(self, workspace_id: str) -> dict[str, Any] | None:
        path = f"{self._root_path}/{workspace_id}/manifest.yaml"
        text = await self._records.read_workspace_file(path)
        if text is None:
            return None
        try:
            return yaml.safe_load(text) or None
        except yaml.YAMLError:
            logger.warning("AD-594a: malformed manifest for %s", workspace_id)
            return None
```

---

## Section 3 — Pydantic config

File: `src/probos/config.py`

### 3a — Add `ConsultationWorkspaceConfig` adjacent to `ClinicalTelemetryConfig`

```
===SEARCH===
class ClinicalTelemetryConfig(BaseModel):
    """AD-635 v1: Clearance-gated clinical query facade (Medical / Counselor).

    Disabled by default — Captain opts in via YAML. v1 is read-only, has no
    automatic invocation, and surfaces nothing at runtime until a clinical
    agent invokes a query method on `runtime.clinical_telemetry`.
    """
    enabled: bool = False
    audit_max_entries: int = 1000
===REPLACE===
class ClinicalTelemetryConfig(BaseModel):
    """AD-635 v1: Clearance-gated clinical query facade (Medical / Counselor).

    Disabled by default — Captain opts in via YAML. v1 is read-only, has no
    automatic invocation, and surfaces nothing at runtime until a clinical
    agent invokes a query method on `runtime.clinical_telemetry`.
    """
    enabled: bool = False
    audit_max_entries: int = 1000


class ConsultationWorkspaceConfig(BaseModel):
    """AD-594a v1: Session-scoped consultation workspace registry.

    Default-True is intentional — the registry is read-only on boot (constructs
    an empty in-memory cache and ensures the ``consultations/`` subdir exists
    in Ship's Records). No automatic side effects until an agent calls
    ``runtime.consultation_workspaces.create(...)``. Same precedent as
    ``KnowledgeEdgesConfig`` / ``EdgeBackfillConfig``.
    """
    enabled: bool = True
    root_path: str = "consultations"
    input_processor: str = "passthrough"
===END REPLACE===
```

### 3b — Wire on `SystemConfig` adjacent to `clinical_telemetry`

```
===SEARCH===
    clinical_telemetry: ClinicalTelemetryConfig = Field(
        default_factory=ClinicalTelemetryConfig
    )  # AD-635
===REPLACE===
    clinical_telemetry: ClinicalTelemetryConfig = Field(
        default_factory=ClinicalTelemetryConfig
    )  # AD-635
    consultation_workspaces: ConsultationWorkspaceConfig = Field(
        default_factory=ConsultationWorkspaceConfig
    )  # AD-594a
===END REPLACE===
```

---

## Section 4 — Finalize wirer

File: `src/probos/startup/finalize.py`

### 4a — Add `_wire_consultation_workspaces` after `_wire_clinical_telemetry`

```
===SEARCH===
def _wire_clinical_telemetry(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-635 v1: Wire ClinicalTelemetryService clearance-gated query facade."""
    cfg = getattr(config, "clinical_telemetry", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.cognitive.clinical_telemetry import ClinicalTelemetryService

    runtime.clinical_telemetry = ClinicalTelemetryService(
        runtime,
        audit_max_entries=cfg.audit_max_entries,
    )
    logger.info(
        "AD-635: ClinicalTelemetryService v1 initialized "
        "(2 domains: dream_history + chain_traces; clearance gate FULL+)"
    )
    return True
===REPLACE===
def _wire_clinical_telemetry(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-635 v1: Wire ClinicalTelemetryService clearance-gated query facade."""
    cfg = getattr(config, "clinical_telemetry", None)
    if not cfg or not cfg.enabled:
        return False

    from probos.cognitive.clinical_telemetry import ClinicalTelemetryService

    runtime.clinical_telemetry = ClinicalTelemetryService(
        runtime,
        audit_max_entries=cfg.audit_max_entries,
    )
    logger.info(
        "AD-635: ClinicalTelemetryService v1 initialized "
        "(2 domains: dream_history + chain_traces; clearance gate FULL+)"
    )
    return True


def _wire_consultation_workspaces(*, runtime: Any, config: "SystemConfig") -> bool:
    """AD-594a v1: Wire WorkspaceRegistry session-scoped consultation workspaces.

    Registry is purely on-demand: nothing is materialized until an agent calls
    ``runtime.consultation_workspaces.create(...)``. Requires ``runtime.records_store``
    (AD-434) to be adopted; if missing, no-op.
    """
    cfg = getattr(config, "consultation_workspaces", None)
    if not cfg or not cfg.enabled:
        return False
    records_store = getattr(runtime, "records_store", None)
    if records_store is None:
        logger.info(
            "AD-594a: records_store unavailable; consultation_workspaces skipped"
        )
        return False

    from probos.consultation import WorkspaceRegistry, build_input_processor

    runtime.consultation_workspaces = WorkspaceRegistry(
        records_store,
        root_path=cfg.root_path,
        input_processor=build_input_processor(cfg.input_processor),
    )
    logger.info(
        "AD-594a: WorkspaceRegistry v1 initialized "
        "(root=%s, input_processor=%s)",
        cfg.root_path, cfg.input_processor,
    )
    return True
===END REPLACE===
```

### 4b — Add `build_input_processor` to the consultation re-exports

Update Section 2a `__init__.py` to ALSO export `build_input_processor` (already imported indirectly by the wirer; explicit re-export keeps `from probos.consultation import build_input_processor` working in finalize). Edit `src/probos/consultation/__init__.py` to add:

```python
from probos.consultation.inputs import build_input_processor
```

and append `"build_input_processor"` to `__all__`.

### 4c — Invoke wirer from finalize cascade

```
===SEARCH===
    if _wire_clinical_telemetry(runtime=runtime, config=config):
        logger.info("AD-635: ClinicalTelemetryService v1 wired during finalization")

    if _wire_workspace_ontology(runtime=runtime, config=config):
        logger.info("AD-478: WorkspaceOntologyRegistry v1 wired during finalization")
===REPLACE===
    if _wire_clinical_telemetry(runtime=runtime, config=config):
        logger.info("AD-635: ClinicalTelemetryService v1 wired during finalization")

    if _wire_consultation_workspaces(runtime=runtime, config=config):
        logger.info("AD-594a: WorkspaceRegistry v1 wired during finalization")

    if _wire_workspace_ontology(runtime=runtime, config=config):
        logger.info("AD-478: WorkspaceOntologyRegistry v1 wired during finalization")
===END REPLACE===
```

---

## Section 5 — Tests

Create new file: `tests/test_ad594a_consultation_workspace.py`

**16 focused tests** (over the 14 floor by 2). All tests use `tmp_path` for `RecordsStore` (real instance) — NO mocks for the records-store path. `clock` injected as a deterministic `lambda: 1700000000.0 + counter` where counter advances per call.

Required test cases:

1. `test_workspace_lifecycle_state_enum` — 7 values, integer ordering matches spec.
2. `test_parse_workspace_refs_extracts_patterns` — text with 3 refs returns 3 `WorkspaceRef`s in order; empty text → `[]`; text with no refs → `[]`.
3. `test_parse_workspace_refs_handles_duplicates_and_case` — case-insensitive match preserves duplicates.
4. `test_render_workspace_refs_md_substitutes_links` — single ref → markdown link with default `base_url`; idempotency-once contract documented in doc.
5. `test_workspace_registry_create_produces_correct_dir_structure` — after `await registry.create(title="X", owner_agent_id="captain", participants=["a","b"])`, all 6 subdirs + `manifest.yaml` + `journal.md` + `delivery.yaml` exist on disk.
6. `test_workspace_registry_create_manifest_schema` — manifest.yaml has `schema_version=1`, `id`, `title`, `owner`, `participants` (list), `lifecycle_state="INITIATED"`, `created_at`, `updated_at`, `template`.
7. `test_lifecycle_full_happy_path` — INITIATED → CONSULTING → PLAN_REVIEW → APPROVED → EXECUTING → COMPLETED → ARCHIVED all return True; manifest.lifecycle_state matches; journal.md has 7 lifecycle entries.
8. `test_lifecycle_rejects_invalid_transition` — EXECUTING → INITIATED returns False; manifest unchanged; warning logged.
9. `test_lifecycle_plan_review_can_revert_to_consulting` — PLAN_REVIEW → CONSULTING is allowed.
10. `test_add_input_routes_through_input_processor` — custom processor that uppercases content + adds `.proc` suffix to filename; verify file is named `report.txt.proc`, content is uppercased.
11. `test_add_advisory_writes_to_advisory_dir_with_agent_filename` — writes file matching `{agent_id}_{ts}.md` in `advisory/`; content includes the advisory-report skeleton.
12. `test_add_plan_iteration_creates_versioned_files` — three calls produce `plan_v1.md`, `plan_v2.md`, `plan_v3.md` (in `plan/`, in that order).
13. `test_add_artifact_and_add_output_write_to_their_dirs` — combined: write artifact + output, both files exist.
14. `test_add_work_item_serializes_yaml_under_workitems` — spec dict round-trips via `yaml.safe_load`; filename uses `wi_{spec.id}.yaml` when `id` present, falls back to uuid8 otherwise.
15. `test_journal_appended_on_every_state_change` — count lines in journal.md after a sequence of advisory + transition + add_input → equal to operation count.
16. `test_list_active_filters_archived` — create 2 workspaces, archive one (full transition cascade), `list_active()` returns 1 (the non-archived) as `ConsultationWorkspaceSummary` with correct `state`/`participant_count`.

**Templates / `list_paths` extras** (covered inside above tests, no separate test): test #5 implicitly verifies `list_paths()` returns 6 keys; test #6's manifest assertion covers `template` field; if a 17th test pad is needed, add `test_template_applied_on_creation_renders_plan_v1` (security_review template applied → plan_v1.md exists with `## Threat Model` heading).

**Drop targets if test count drifts:** #3 (covered by #2), #9 (covered by #8 mechanism). Floor = 14.

**Test file skeleton:**

```python
"""AD-594a v1: Consultation workspace tests."""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from probos.consultation import (
    ConsultationWorkspaceSummary,
    InputProcessor,
    WorkspaceLifecycleState,
    WorkspaceRegistry,
    parse_workspace_refs,
    render_workspace_refs_md,
)
from probos.knowledge.records_store import RecordsStore


def _make_records_store(tmp_path: Path) -> RecordsStore:
    cfg = SimpleNamespace(repo_path=str(tmp_path / "records"), auto_commit=False)
    return RecordsStore(cfg)


@pytest.fixture
async def records(tmp_path: Path) -> RecordsStore:
    rs = _make_records_store(tmp_path)
    await rs.initialize()
    return rs


@pytest.fixture
def clock():
    state = {"t": 1700000000.0}
    def _tick() -> float:
        state["t"] += 1.0
        return state["t"]
    return _tick


@pytest.fixture
async def registry(records: RecordsStore, clock) -> WorkspaceRegistry:
    return WorkspaceRegistry(records, clock=clock)
```

(Builder authors the remaining 16 tests against this skeleton.)

---

## Section 6 — What This AD Does NOT Change

These belong to **separate GH issues** — not deferrals:

- **AD-594b (#161) — Crew Consultation Primitive** — `consult(question, context)` on CognitiveAgent; advisor selection; multi-advisor iteration; conflict resolution. No part of v1.
- **AD-594c (#162) — Parallel Execution Dispatch** — plan decomposition into `WorkItemStore` items, dependency/conflict detection, multi-executor assignment. No part of v1.
- **AD-594d (#163) — Delivery Pipeline** — `DeliveryAdapter` (LocalFileAdapter, GitHubAdapter), Captain approval gate, format transformation, revision cycle. v1 ships an EMPTY `delivery.yaml` placeholder file only.
- **HXI message rendering integration of `[workspace:...]` refs** — out of scope (DLog #3); ship parser + renderer only. Wrapper around `MessageStore.create_post()` is NOT in v1.
- **PDF / image / audio input processors** — separate AD; v1 ships the `InputProcessor` Protocol seam + passthrough impl (DLog #2).
- **Real `WorkItemStore` integration** — `add_work_item` writes a YAML spec to `workitems/`; it does NOT register the spec with `runtime.work_item_store` (AD-594c territory).
- **No new EventType** — workspace activity is journaled to per-workspace `journal.md`; cross-mesh observability comes with AD-594b/c.
- **No HXI surface** — Captain-facing visualization deferred (separate AD).
- **No REST API endpoints** — v1 callable surface is `runtime.consultation_workspaces` only. (Roadmap mentions `/api/consultations` in `render_workspace_refs_md` default `base_url`; the URL is a future hook, not a router shipped in v1.)
- **No federation export** — workspaces are local to a single ProbOS instance.
- **Wave 10 default-False convention exception**: `ConsultationWorkspaceConfig.enabled=True` is intentional (DLog #6 / Section 3a docstring). Reviewer should NOT flag.

---

## Section 7 — Tracking Updates

### 7a — `PROGRESS.md`
Prepend AD-594a entry (single long-paragraph format; preserve the AD-695 entry below it). Anchor on the `AD-695 v1 CLOSED.` first-sentence.

### 7b — `docs/development/roadmap.md`
Flip AD-594a status from `*(planned, OSS, depends: AD-434 Ship's Records)*` to `*(Complete, OSS, depends: AD-434 Ship's Records)*` at the bullet at line ~4837.

### 7c — `DECISIONS.md`
Prepend a new AD-594a v1 entry at the top of Era V (anchor: `## Era V — Civilization (Phases 31-36)\n\n### AD-695` — same prepend pattern as Wave 43).

### 7d — `prompts/wave-orchestrator-state.json` / `prompts/wave-plan.yaml`
Wave 44 entry already pre-populated (`status: pending`). Builder should NOT modify the plan file — orchestrator handles status flip.

### 7e — Closes GH issue #160
Standard close-comment after merge: "AD-594a v1 closed in Wave 44 (commit <sha>). Consultation Workspace substrate at `src/probos/consultation/`. Sibling AD-594b (#161), AD-594c (#162), AD-594d (#163) remain open."

---

## Section 8 — Acceptance Criteria

- All 16 tests pass at `tests/test_ad594a_consultation_workspace.py`.
- Full gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile` shows test count of **11078 + 16 = 11094** (or +14 if 2 drop-target tests are removed during build, floor = 11092).
- No new EventType registered.
- `runtime.consultation_workspaces` is a public attribute exposed by the finalize wirer when `config.consultation_workspaces.enabled` is True (default).
- `RecordsStore` exposes three new public methods: `write_workspace_file`, `read_workspace_file`, `append_workspace_file`. `_SUBDIRS` includes `"consultations"`.
- Workspace files (`manifest.yaml`, `journal.md`, `delivery.yaml`, `workitems/*.yaml`) do NOT have ProbOS YAML frontmatter wrappers (raw content).
- Lifecycle transitions validated against `_ALLOWED_TRANSITIONS`; invalid transitions return `False` and never raise.
- `[workspace:...]` parser + renderer ship as pure helpers in `consultation/refs.py`. No ward_room file modified.
- `InputProcessor` Protocol + `PassthroughTextProcessor` + `build_input_processor` ship in `consultation/inputs.py`. No PDF/image processor in v1.
- 3 consultation templates (`security_review`, `technical_design`, `incident_response`) registered in `TEMPLATES` dict; applied on workspace creation when `template=<name>` passed to `WorkspaceRegistry.create`.
- 5 artifact-render functions exported (`render_advisory_report` / `_plan_document` / `_work_item_spec` / `_supporting_data` / `_decision_record`).
- **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.**

---

## Verified Against Codebase (2026-05-04, HEAD `c0a963f`)

```
grep -n "_SUBDIRS = (" src/probos/knowledge/records_store.py
  15: _SUBDIRS = (
grep -n "class RecordsStore" src/probos/knowledge/records_store.py
  46: class RecordsStore:
grep -n "def repo_path" src/probos/knowledge/records_store.py
  62:     def repo_path(self) -> Path:
grep -n "_safe_path" src/probos/knowledge/records_store.py
  893:     def _safe_path(self, user_path: str) -> Path:
grep -n "def _parse_document" src/probos/knowledge/records_store.py
  881:     def _parse_document(self, raw: str) -> tuple[dict, str]:
grep -n "def records_store" src/probos/runtime.py
  960:     def records_store(self):
grep -n "self._records_store = cog.records_store" src/probos/runtime.py
  1324:        self._records_store = cog.records_store
grep -n "class ClinicalTelemetryConfig" src/probos/config.py
  1876: class ClinicalTelemetryConfig(BaseModel):
grep -n "clinical_telemetry: ClinicalTelemetryConfig" src/probos/config.py
  2226:     clinical_telemetry: ClinicalTelemetryConfig = Field(
grep -n "def _wire_clinical_telemetry" src/probos/startup/finalize.py
  494: def _wire_clinical_telemetry(*, runtime: Any, config: "SystemConfig") -> bool:
grep -n "_wire_clinical_telemetry(runtime=runtime" src/probos/startup/finalize.py
  812:     if _wire_clinical_telemetry(runtime=runtime, config=config):
grep -n "_wire_workspace_ontology(runtime=runtime" src/probos/startup/finalize.py
  815:     if _wire_workspace_ontology(runtime=runtime, config=config):
grep -n "transporter\|Transporter" src/probos/events.py
  56:     # Transporter / builder
  57:     TRANSPORTER_ASSEMBLED = "transporter_assembled"
  58:     TRANSPORTER_VALIDATED = "transporter_validated"
  59:     TRANSPORTER_DECOMPOSED = "transporter_decomposed"
  60:     TRANSPORTER_WAVE_START = "transporter_wave_start"
  61:     TRANSPORTER_CHUNK_DONE = "transporter_chunk_done"
  62:     TRANSPORTER_EXECUTION_DONE = "transporter_execution_done"
  (Verified: existing Transporter Pattern is builder code-chunk decomposition, NOT input ingestion. AD-594a InputProcessor seam is independent.)
grep -n "MessageStore\|create_post" src/probos/ward_room/messages.py
  21: class MessageStore:
  153:     async def create_post(...)
  (Verified: MessageStore stores raw text bodies; no server-side renderer. v1 ships parser/renderer as pure helpers; HXI integration deferred.)
grep -n "consultation_workspaces" src/probos -r
  (no hits — collision-free public attribute)
grep -n "yaml" pyproject.toml
  26:     "pyyaml>=6.0",
```

All anchors held at HEAD `c0a963f`. No drift.
