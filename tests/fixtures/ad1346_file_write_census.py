"""AD-1346 M3e4c3a (#1604): the census of #1604 property 1's store-write class: its file writes.

``file_write_scan`` parses one module and reports each file write in it (D253). A point is a call whose function is:

- an attribute named in ``FILE_WRITE_METHODS``;
- ``os.<name>`` or ``shutil.<name>``, called on the module's name, for a name ``MODULE_WRITES`` gives that module;
- ``os.open``, when one of its positional arguments holds an attribute named in ``WRITE_FLAGS``, and only then;
- named in ``OPENS`` (a name or an attribute), when its ``mode`` keyword, or else one of its first two positional
  arguments, is a ``str`` constant that ``WRITE_MODE`` matches whole and that holds a character of ``WRITE_CHARS``;
- an attribute named in ``PATH_MOVES``, called with one positional argument and no keyword;

or, failing those, a call that passes as a positional argument an attribute named in ``HANDED``: a method handed to
another function to call. A point is (enclosing scope, line, the name), scoped as ``sql_write_scan`` of
``tests/fixtures/ad1346_store_census.py`` scopes one. ``file_write_points`` runs the scan over every ``src`` module.
``FILE_WRITE_FILES`` gives each file that holds a point one coverage, a ``Pending``, ``System`` or ``OutsideRuntime`` of
``tests/fixtures/ad1346_effect_census.py`` (D254); a row is a file and carries no count. ``FILE_AGENT_ATTRIBUTED_SCOPES``
gives, for each file whose row is ``Pending("M3e4d")``, a scope that writes a file D239 makes agent-attributed and the
name in that scope of the value the file records as the text's author (D255).

Among what the scan cannot see (register R129): a mode or a flag held in a variable, a write through a handle opened
elsewhere or through a library, a file a subprocess writes, a write inside a string another process runs, the callers
of a function that wraps a primitive, and a primitive reached through ``getattr``.
``tests/test_ad1346_admission_file_write_census.py`` checks the rows against the code.
"""

from __future__ import annotations

import ast
import functools
import re
from typing import Final

from tests.fixtures.ad1346_effect_census import SHIP, OutsideRuntime, Pending, System, src_sources

#: AD-1346 M3e4c3a (D253): methods that write, copy or delete a file, a point on any receiver.
FILE_WRITE_METHODS: Final = frozenset({"write_text", "write_bytes", "unlink", "rmtree", "copyfile", "copy2", "copytree"})
#: A module's functions that write, move, link or delete a file, a point when called on the module's name.
MODULE_WRITES: Final[dict[str, frozenset[str]]] = {
    "os": frozenset({"replace", "rename", "remove", "link", "write"}),
    "shutil": frozenset({"copy", "move"}),
}
#: ``os.open`` flags that open a file to write it or create it.
WRITE_FLAGS: Final = frozenset({"O_WRONLY", "O_RDWR", "O_CREAT", "O_APPEND", "O_TRUNC"})
#: The functions whose mode makes a call a point.
OPENS: Final = frozenset({"open", "fdopen"})
#: A ``str`` mode, matched whole.
WRITE_MODE: Final = re.compile(r"[rwxabt+]{1,3}")
#: A mode that holds one of these characters writes.
WRITE_CHARS: Final = frozenset("wax+")
#: ``Path`` moves: a point with one positional argument and no keyword (``str.replace`` takes two).
PATH_MOVES: Final = frozenset({"replace", "rename"})
#: Methods that make a call a point when handed to it, uncalled, as a positional argument.
HANDED: Final = FILE_WRITE_METHODS | PATH_MOVES

#: (file, scope, line, the name).
Point = tuple[str, str, int, str]


def _attribute(node: ast.AST) -> str:
    """``node``'s attribute name when ``node`` is an attribute, else the empty string."""
    return node.attr if isinstance(node, ast.Attribute) else ""


def _write_mode(node: ast.Call) -> bool:
    """Whether ``node``'s ``mode`` keyword, or else one of its first two positional arguments, is a ``str`` constant
    that ``WRITE_MODE`` matches whole and that holds a character of ``WRITE_CHARS``."""
    modes = [keyword.value for keyword in node.keywords if keyword.arg == "mode"] or node.args[:2]
    return any(
        isinstance(mode, ast.Constant)
        and isinstance(mode.value, str)
        and WRITE_MODE.fullmatch(mode.value) is not None
        and not WRITE_CHARS.isdisjoint(mode.value)
        for mode in modes
    )


def _file_write(node: ast.Call) -> str:
    """The name that makes ``node`` a file write (D253), else the empty string."""
    func = node.func
    name = func.id if isinstance(func, ast.Name) else _attribute(func)
    module = func.value.id if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) else ""
    if isinstance(func, ast.Attribute) and name in FILE_WRITE_METHODS:
        return name
    if name in MODULE_WRITES.get(module, frozenset()):
        return name
    if module == "os" and name == "open":
        return name if any(_attribute(part) in WRITE_FLAGS for argument in node.args for part in ast.walk(argument)) else ""
    if name in OPENS and _write_mode(node):
        return name
    if isinstance(func, ast.Attribute) and name in PATH_MOVES and len(node.args) == 1 and not node.keywords:
        return name
    for argument in node.args:
        if _attribute(argument) in HANDED:
            return _attribute(argument)
    return ""


class _FileWriteScan(ast.NodeVisitor):
    def __init__(self) -> None:
        self.scope: list[str] = []
        self.points: list[tuple[str, int, str]] = []

    def _enter(self, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_ClassDef = visit_FunctionDef = visit_AsyncFunctionDef = _enter

    def visit_Call(self, node: ast.Call) -> None:
        name = _file_write(node)
        if name:
            self.points.append((".".join(self.scope) or "<module>", node.lineno, name))
        self.generic_visit(node)


def file_write_scan(source: str, filename: str = "<file>") -> list[tuple[str, int, str]]:
    """(scope, line, name) of each file write in one module's source (AD-1346 M3e4c3a, D253)."""
    scan = _FileWriteScan()
    scan.visit(ast.parse(source, filename=filename))
    return scan.points


@functools.lru_cache(maxsize=1)
def file_write_points() -> tuple[Point, ...]:
    """(file, scope, line, name) of each file write in ``src``."""
    return tuple((rel, *point) for rel, source in src_sources().items() for point in file_write_scan(source, rel))


def file_write_files() -> frozenset[str]:
    """The ``src`` files that hold a file write."""
    return frozenset(path for path, _scope, _line, _name in file_write_points())


_AGENT_ATTRIBUTED_FILE: Final = Pending("M3e4d", "agent-attributed (D239, D255): FILE_AGENT_ATTRIBUTED_SCOPES names a scope and its author (register R113)")
_UNCLASSIFIED: Final = Pending("M3e4c3d", "not yet classified under D239 and D218 (register R130)")

#: AD-1346 M3e4c3a (D254, D255): each file whose row is ``Pending("M3e4d")`` -> (a scope that writes a file D239 makes
#: agent-attributed, the name in that scope of the value the file records as the text's author).
FILE_AGENT_ATTRIBUTED_SCOPES: Final[dict[str, tuple[str, str]]] = {
    "src/probos/knowledge/records_store.py": ("RecordsStore.write_entry", "author"),
}

#: AD-1346 M3e4c3a (D254): each ``src`` file that holds a file write -> its coverage.
FILE_WRITE_FILES: Final[dict[str, Pending | OutsideRuntime | System]] = {
    # Agent-attributed (D239, D255): M3e4d's (register R113, R131).
    "src/probos/knowledge/records_store.py": _AGENT_ATTRIBUTED_FILE,
    # The operator's command line (D167).
    "src/probos/__main__.py": OutsideRuntime("the operator's command line (D167)"),
    "src/probos/doctor/checks/data_dir_check.py": OutsideRuntime("probos doctor's data-directory check: a probe file it writes and deletes (D167)"),
    # AD-1346 M3e4c3b: the ship's (D218, D239, D259).
    "src/probos/agents/file_writer.py": System(SHIP, "the text FileWriterAgent.commit_write is passed, written with no author id (D239)"),
    "src/probos/agents/utility/avatar_agents.py": System(SHIP, "a rendered VRM moved to <agent_id>.vrm, keyed by the agent it is about (D239)"),
    "src/probos/consultation/delivery.py": System(SHIP, "the content of a DeliveryArtifact, which has no author field (D239), and LocalFileAdapter.rollback's delete of the file a URI names"),
    "src/probos/execution/isolation.py": System(SHIP, "a sandbox run's script.py and launcher, and the removal of a work directory; ExecutionRequest has no author field (D239)"),
    "src/probos/knowledge/erasure.py": System(SHIP, "_unlink_attachments: the unlink of each attachment id on the store it is passed: no text"),
    "src/probos/knowledge/records_snapshot.py": System(SHIP, "the Ship's Records snapshot: a ZIP copy of Ship's Records files (D218)"),
    "src/probos/knowledge/store.py": System(SHIP, "the knowledge repo, among them episode copies (D218), designed agent and skill source, and the trust snapshot"),
    "src/probos/naval/captains_log.py": System(SHIP, "the Captain's Log Markdown that CaptainsLogService.generate_for_date composes"),
    "src/probos/naval/plan_of_day.py": System(SHIP, "the Plan of the Day Markdown that PlanOfDayService.generate_for_date composes"),
    "src/probos/routers/agents.py": System(SHIP, "an uploaded VRM written to <agent_id>.vrm, keyed by the agent it is about (D239)"),
    "src/probos/routers/browser_recordings.py": System(SHIP, "delete_recording removes a session's recording directory: no text"),
    "src/probos/routers/config.py": System(SHIP, "_write_yaml_atomic: a YAML dump of the data it is passed, under a timestamp header"),
    "src/probos/routers/voice.py": System(SHIP, "a wake-word training WAV from the request, named by its SHA-256 prefix"),
    "src/probos/task_sessions/browser.py": System(SHIP, "the Playwright script render_script builds from a BrowserTask, which has no author field (D239)"),
    "src/probos/tools/browser/actions.py": System(SHIP, "_action_upload_file deletes the temporary file a credential vault returned: no text"),
    "src/probos/tools/browser/credentials.py": System(SHIP, "the credential vault file, and a temporary file holding a decrypted credential"),
    "src/probos/tools/browser/recording_reaper.py": System(SHIP, "RecordingReaper._reap_sync deletes recordings past retention or over the size cap: no text"),
    "src/probos/tools/code_execution_tool.py": System(SHIP, "a code run's work directory: its sandbox helper, staged thread attachments and its removal"),
    "src/probos/ward_room/threads.py": System(SHIP, "the Ward Room JSONL archive: prune_old_threads appends copies of the thread and post rows it prunes (D218)"),
    # AD-1346 M3e4c3c: the ship's (D239, D264).
    "src/probos/cognitive/agent_patcher.py": System(SHIP, "AgentPatcher._patch_skill deletes the temporary file it loaded the patched skill source from: no text"),
    "src/probos/cognitive/builder.py": System(SHIP, "execute_approved_build writes the content of each file change, or its text after replacement, with no author id (D239); _restore_pre_build_files restores saved bytes and deletes created files"),
    "src/probos/cognitive/chain_checkpoint.py": System(SHIP, "ChainCheckpointStore.save writes a ChainCheckpoint, which has no author field (D239); delete removes it"),
    "src/probos/cognitive/checkpoint.py": System(SHIP, "write_checkpoint writes the source text, node states and serialized form of a DAG, with no author key (D239); delete_checkpoint removes it"),
    "src/probos/cognitive/copilot_adapter.py": System(SHIP, "seed_session_directory writes the non-empty file contents it is passed into a build session directory, with no author id (D239)"),
    "src/probos/cognitive/dm/artifact_extractor.py": System(SHIP, "_to_docx_libreoffice writes the text it is passed, wrapped as HTML, into a temporary directory for LibreOffice, with no author id (D239)"),
    "src/probos/cognitive/dream_manifest.py": System(SHIP, "DreamManifest._save writes a timestamp for each episode id and step marked processed: no text"),
    "src/probos/cognitive/dreaming.py": System(SHIP, "DreamingEngine.dream_cycle renames each non-primary entry of a consolidated cluster into an _archived directory beside it: no text"),
    "src/probos/cognitive/evidence_collector.py": System(SHIP, "EvidenceCollector._persist writes behaviour codes, a confidence and reasoning, with the author_id it observes (D239)"),
    "src/probos/cognitive/peer_observation_monitor.py": System(SHIP, "PeerObservationMonitor._save_state writes a count and a last tier for each detector and observer pair: no text"),
    "src/probos/cognitive/ready_room/idea_store.py": System(SHIP, "IdeaCaptureStore._save writes the title, body and captured_by of each idea; WF7: no src call outside the file passes captured_by (D239)"),
    "src/probos/cognitive/sandbox.py": System(SHIP, "SandboxRunner.test_agent deletes the temporary file it loaded the generated agent source from: no text"),
    "src/probos/cognitive/scout.py": System(SHIP, "_save_seen writes the repositories seen and their dates, and _scout_step_persist_report a daily report of findings; ScoutFinding has no author field (D239)"),
    "src/probos/cognitive/self_improvement/versioning.py": System(SHIP, "LocalDiskPersistence.promote writes agent source and a sidecar holding the designer of its version; WF7: no src call builds an AgentVersion (D239)"),
    "src/probos/cognitive/self_mod.py": System(SHIP, "SelfModificationPipeline.handle_add_skill deletes the temporary file it loaded the skill source from: no text"),
    "src/probos/cognitive/session_manager.py": System(SHIP, "SessionManager._write writes a Session, which has no author field (D239); close_session renames it into archive"),
    "src/probos/cognitive/skill_catalog.py": System(SHIP, "import_skill copies a skill directory, _rewrite_frontmatter adds ProbOS metadata to a SKILL.md frontmatter and remove_skill deletes a skill directory; none sets an author id (D239)"),
    "src/probos/cognitive/skill_forge.py": System(SHIP, "SkillForge._write_files writes the files a model call generated into a temporary staging directory, with no author id (D239); forge removes the directory"),
    "src/probos/cognitive/swe_harness/tools.py": System(SHIP, "WriteFileTool.invoke and EditFileTool.invoke write the text they are passed or edit, with no author id (D239); _locked_native_target opens a target read-write"),
    # Not yet classified: M3e4c3d's (register R130, R133, R135).
    "src/probos/attachments/filesystem_store.py": _UNCLASSIFIED,
    "src/probos/attachments/image_budget_store.py": _UNCLASSIFIED,
    "src/probos/audio/tts/resident.py": _UNCLASSIFIED,
    "src/probos/avatars/blender_renderer.py": _UNCLASSIFIED,
    "src/probos/avatars/proposal_history.py": _UNCLASSIFIED,
    "src/probos/avatars/rhubarb_backend.py": _UNCLASSIFIED,
    "src/probos/avatars/telemetry_history.py": _UNCLASSIFIED,
    "src/probos/avatars/vision_proposal_history.py": _UNCLASSIFIED,
    "src/probos/captain_card/card.py": _UNCLASSIFIED,
    "src/probos/credential_store.py": _UNCLASSIFIED,
    "src/probos/episodic_health.py": _UNCLASSIFIED,
    "src/probos/experience/desktop/lifecycle.py": _UNCLASSIFIED,
    "src/probos/identity_key_store.py": _UNCLASSIFIED,
    "src/probos/infrastructure/backup.py": _UNCLASSIFIED,
    "src/probos/infrastructure/snapshot_manifest.py": _UNCLASSIFIED,
    "src/probos/integrations/template_registry.py": _UNCLASSIFIED,
    "src/probos/maintenance/episodic_backup.py": _UNCLASSIFIED,
    "src/probos/migration/__init__.py": _UNCLASSIFIED,
    "src/probos/ontology/loader.py": _UNCLASSIFIED,
    "src/probos/perception/identity.py": _UNCLASSIFIED,
    "src/probos/perception/vision_overrides.py": _UNCLASSIFIED,
    "src/probos/pidfile_guard.py": _UNCLASSIFIED,
    "src/probos/proactive.py": _UNCLASSIFIED,
    "src/probos/provider_setup.py": _UNCLASSIFIED,
    "src/probos/runtime_config_service.py": _UNCLASSIFIED,
    "src/probos/security/file_access.py": _UNCLASSIFIED,
    "src/probos/security/keyring_backend.py": _UNCLASSIFIED,
    "src/probos/shutdown_integrity.py": _UNCLASSIFIED,
    "src/probos/startup/shutdown.py": _UNCLASSIFIED,
    "src/probos/voice/wake_word_trainer.py": _UNCLASSIFIED,
    "src/probos/warm_boot.py": _UNCLASSIFIED,
}
