"""AD-1346 M3e4c3a (#1604): the census of #1604 property 1's store-write class: its file writes.

``file_write_scan`` parses one module and reports each file write in it (D253). A point is a call whose function is:

- an attribute named in ``FILE_WRITE_METHODS`` or in ``PINNED_WRITES``, the methods of ``PinnedDirectory``
  (``security/file_access.py``) that hold a point (D278);
- ``os.<name>`` or ``shutil.<name>``, called on the module's name, for a name ``MODULE_WRITES`` gives that module;
- ``os.open``, when one of its positional arguments holds an attribute named in ``WRITE_FLAGS``, and only then;
- named in ``OPENS`` (a name or an attribute), when its ``mode`` keyword, or else one of its first two positional
  arguments, is a ``str`` constant that ``WRITE_MODE`` matches whole and that holds a character of ``WRITE_CHARS``;
- an attribute named in ``PATH_MOVES``, called with one positional argument and no keyword;

or, failing those, a call that passes as a positional argument an attribute named in ``HANDED``: a method handed to
another function to call. A point is (enclosing scope, line, the name), scoped as ``sql_write_scan`` of
``tests/fixtures/ad1346_store_census.py`` scopes one. ``file_write_points`` runs the scan over every ``src`` module.
``FILE_WRITE_FILES`` gives each file that holds a point one coverage, a ``Pending``, ``System`` or ``OutsideRuntime`` of
``tests/fixtures/ad1346_effect_census.py`` (D254); a row is a file and carries no count. A file whose row is
``Pending("M3e4d")`` is a key of ``FILE_AGENT_ATTRIBUTED_SCOPES`` or of ``FILE_AGENT_ATTRIBUTED_STATE_SCOPES``. The first
gives a scope that writes a file D239 makes agent-attributed and the name in that scope of the value the file records
as the text's author (D255). The second gives a scope, the author (a parameter of that scope, or ``<parameter>.<field>``
for a field of the class that annotates the parameter), a module-level name and the writing scope (D274).

Among what the scan cannot see (register R129, R140): a mode or a flag held in a variable, a write through a handle
opened elsewhere or through a library, a file a subprocess writes, a write inside a string another process runs, and a
primitive reached through ``getattr``.
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
#: AD-1346 M3e4c3f (D278): the methods of ``PinnedDirectory`` (``security/file_access.py``) that write, link or delete
#: a file, a point on any receiver; WF9 holds them to the class's methods that hold a point.
PINNED_WRITES: Final = frozenset({"write_new", "publish_file", "remove_file"})
#: Methods that make a call a point when handed to it, uncalled, as a positional argument.
HANDED: Final = FILE_WRITE_METHODS | PINNED_WRITES | PATH_MOVES

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
    if isinstance(func, ast.Attribute) and name in FILE_WRITE_METHODS | PINNED_WRITES:
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


_AGENT_ATTRIBUTED_FILE: Final = Pending("M3e4d", "agent-attributed (D239, D255, D274): FILE_AGENT_ATTRIBUTED_SCOPES or FILE_AGENT_ATTRIBUTED_STATE_SCOPES names its writing scope and its author (register R113)")

#: AD-1346 M3e4c3a (D254, D255): a file whose row is ``Pending("M3e4d")`` -> (a scope that writes a file D239 makes
#: agent-attributed, the name in that scope of the value the file records as the text's author).
FILE_AGENT_ATTRIBUTED_SCOPES: Final[dict[str, tuple[str, str]]] = {
    "src/probos/knowledge/records_store.py": ("RecordsStore.write_entry", "author"),
}
#: AD-1346 M3e4c3e (D274): a file whose row is ``Pending("M3e4d")`` -> (a scope that takes the author, the author: a
#: parameter of that scope, or ``<parameter>.<field>`` for a field of the class that annotates that parameter, a
#: module-level name on which that scope calls a method with that parameter, the writing scope that scope calls).
FILE_AGENT_ATTRIBUTED_STATE_SCOPES: Final[dict[str, tuple[str, str, str, str]]] = {
    "src/probos/avatars/proposal_history.py": ("append", "agent_id", "_history", "_persist_locked"),
    "src/probos/avatars/vision_proposal_history.py": ("append", "entry.agent_id", "_entries", "_persist_locked"),
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
    "src/probos/cognitive/builder.py": System(SHIP, "execute_approved_build writes the content, or its text after replacement, with no author id (D239); _restore_pre_build_files restores saved bytes and deletes created files"),
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
    "src/probos/cognitive/self_improvement/versioning.py": System(SHIP, "LocalDiskPersistence.promote writes agent source and a sidecar holding the designer of its version; no src call builds an AgentVersion (D239)"),
    "src/probos/cognitive/self_mod.py": System(SHIP, "SelfModificationPipeline.handle_add_skill deletes the temporary file it loaded the skill source from: no text"),
    "src/probos/cognitive/session_manager.py": System(SHIP, "SessionManager._write writes a Session, which has no author field (D239); close_session renames it into archive"),
    "src/probos/cognitive/skill_catalog.py": System(SHIP, "import_skill copies a skill directory, _rewrite_frontmatter adds ProbOS metadata to a SKILL.md frontmatter and remove_skill deletes a skill directory; none sets an author id (D239)"),
    "src/probos/cognitive/skill_forge.py": System(SHIP, "SkillForge._write_files writes the files a model call generated into a temporary staging directory, with no author id (D239); forge removes the directory"),
    "src/probos/cognitive/swe_harness/tools.py": System(SHIP, "WriteFileTool.invoke and EditFileTool.invoke write the text they are passed or edit, with no author id (D239); _locked_native_target opens a target read-write"),
    # AD-1346 M3e4c3d: the ship's (D239, D269).
    "src/probos/attachments/filesystem_store.py": System(SHIP, "FilesystemAttachmentStore.write writes a blob named by the content hash it is passed and an index entry of its origin, time, MIME type and size, with no author id (D239); unlink and unlink_if_unchanged delete blobs"),
    "src/probos/attachments/image_budget_store.py": System(SHIP, "save writes the timestamps and image counts of each key of the budget tracker: no text"),
    "src/probos/audio/tts/resident.py": System(SHIP, "PiperWorker._spawn opens a file in a temporary directory as the stderr of a Piper process, _request deletes the output file of a request and _release removes the directory"),
    "src/probos/avatars/blender_renderer.py": System(SHIP, "BlenderRenderer.render writes the AvatarDSL it is passed as YAML and JSON drafts named by the agent id it is passed (D239), and deletes a rejected VRM output"),
    "src/probos/avatars/rhubarb_backend.py": System(SHIP, "_convert_to_wav and generate_visemes delete the temporary WAV file that ffmpeg converts an audio file into: no text"),
    "src/probos/avatars/telemetry_history.py": System(SHIP, "TelemetryHistoryWriter appends a snapshot of an agent's avatar state to a file named by its agent_id (D239)"),
    "src/probos/captain_card/card.py": System(SHIP, "save_card writes a CaptainCard, which has no author field (D239)"),
    "src/probos/credential_store.py": System(SHIP, "CredentialStore.rotate writes the secrets store with the value it is passed under the secret name: no author id"),
    "src/probos/episodic_health.py": System(SHIP, "check_episodic_health opens a temporary file as the stderr of the episodic probe, and deletes it"),
    "src/probos/experience/desktop/lifecycle.py": System(SHIP, "DesktopLifecycle deletes its lock file, and writes or deletes a fixed autostart entry: a macOS LaunchAgent plist or a Linux .desktop file"),
    "src/probos/identity_key_store.py": System(SHIP, "PlaintextDevKeyStore.create writes a new key id and private key to a fresh file: no text"),
    "src/probos/infrastructure/backup.py": System(SHIP, "BackupService copies database files into a snapshot or hard-links them from the prior one (D218), renames a snapshot into place and removes pruned and incomplete snapshots"),
    "src/probos/infrastructure/snapshot_manifest.py": System(SHIP, "write_manifest writes a SnapshotManifest, which has no author field (D239)"),
    "src/probos/integrations/template_registry.py": System(SHIP, "TemplateRegistry.create_from_template writes a template filled with the substitutions it is passed, with no author id (D239), and rewrites the template index with its use count"),
    "src/probos/maintenance/episodic_backup.py": System(SHIP, "snapshot_episodic writes a tar of the Chroma artifacts it finds under the data directory (D218); _prune_old_snapshots deletes older snapshots"),
    "src/probos/migration/__init__.py": System(SHIP, "execute_plan copies the files of a migration plan from their source paths to their target paths: no author id"),
    "src/probos/ontology/loader.py": System(SHIP, "OntologyLoader._load_or_generate_instance_id_sync writes a new instance id: no text"),
    "src/probos/perception/identity.py": System(SHIP, "IdentityResolver.enroll writes a face embedding, a model id and a version, and revoke deletes them: no text"),
    "src/probos/perception/vision_overrides.py": System(SHIP, "_persist_locked writes a vision-capability setting for each agent type: no text"),
    "src/probos/pidfile_guard.py": System(SHIP, "_try_atomic_create writes a process id to the pidfile, _takeover_lock opens its lock file and _acquire_unlocked deletes a pidfile before a retry: no text"),
    "src/probos/proactive.py": System(SHIP, "DailyBriefingScheduler._save_state writes the briefing state (last trigger day, last reminder time, dismissed days): no text"),
    "src/probos/provider_setup.py": System(SHIP, "write_config_atomic installs the config text it is passed after a backup copy of the file it replaces, with no author id (D239)"),
    "src/probos/runtime_config_service.py": System(SHIP, "RuntimeConfigService._save writes an override value for each field id: no author id"),
    "src/probos/security/file_access.py": System(SHIP, "PinnedDirectory.write_new writes the bytes it is passed to a new file, publish_file links a staged file to a name and remove_file deletes a file, with no author id (D239)"),
    "src/probos/security/keyring_backend.py": System(SHIP, "KeyringCredentialBackend._save writes the scope, times and read count of each credential ref, and materialize_to_temp a temporary file holding a decrypted credential"),
    "src/probos/shutdown_integrity.py": System(SHIP, "mark_clean_shutdown and mark_dirty_shutdown write a ShutdownStatusPayload, which has no author field (D239), through _atomic_write"),
    "src/probos/startup/shutdown.py": System(SHIP, "shutdown writes the session record: its id, start and shutdown times, uptime, crew count and shutdown reason, with no author id (D239)"),
    "src/probos/voice/wake_word_trainer.py": System(SHIP, "WakeWordTrainer.train deletes the positive training samples directory: no text"),
    "src/probos/warm_boot.py": System(SHIP, "WarmBootService.restore and _load_skill_handler delete the temporary file they loaded restored agent or skill source from: no text"),
    # Agent-attributed (D239, D269, D274): M3e4d's (register R113, R136).
    "src/probos/avatars/proposal_history.py": _AGENT_ATTRIBUTED_FILE,
    "src/probos/avatars/vision_proposal_history.py": _AGENT_ATTRIBUTED_FILE,
    # AD-1346 M3e4c3f: the ship's (D218, D279).
    "src/probos/execution/workspace_result_store.py": System(SHIP, "ArtifactIO._publish_in writes a copy of a tool result's text (D218), its outline and a manifest of its digests and sizes, under the agent's workspace key and a SHA-256 digest of the agent's id; GenerationReaper and _drop_staged delete files"),
}
