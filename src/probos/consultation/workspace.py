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
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Callable

import yaml

from probos.consultation.inputs import (
    InputProcessor,
    PassthroughTextProcessor,
)
from probos.consultation.templates import (
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
    # AD-594d v1: revision cycle — COMPLETED can return to CONSULTING (re-deliberation)
    # or EXECUTING (re-work plan items) on captain feedback before final ARCHIVE.
    WorkspaceLifecycleState.COMPLETED: frozenset({
        WorkspaceLifecycleState.ARCHIVED,
        WorkspaceLifecycleState.CONSULTING,
        WorkspaceLifecycleState.EXECUTING,
    }),
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
