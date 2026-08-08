"""AD-1066: CodeExecutionTool — sandboxed Python execution that captures any
produced files as downloadable artifacts (the Claude Cowork / Codex model).

This is the keystone tool for crew-agent task execution: an agent in the
conversational AgenticLoop (AD-1065) writes a Python script (e.g. python-docx to
build a Word document, matplotlib for a chart, openpyxl for a spreadsheet), runs
it here, and every file the script writes into the working directory is persisted
to the AD-797 ArtifactStore and surfaced to the Captain as a downloadable card.

Governance: offered to the loop ONLY when ``config.execution.enabled`` (the
operator opt-in, AD-994). Execution runs through the AD-993 ``SubprocessSandbox``
(process isolation, time/output/memory bounds, network OFF). The tool never
raises out of ``invoke`` — every failure becomes an error ``ToolResult`` the loop
can reason over.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import logging
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from probos.execution.fetch_broker import (
    SANDBOX_HELPER_FILENAME,
    SANDBOX_HELPER_SOURCE,
    SandboxFetchBroker,
)
from probos.execution.isolation import ExecutionRequest, SubprocessSandbox
from probos.tools.protocol import ToolResult, ToolType

logger = logging.getLogger(__name__)

# The sandbox writes the submitted source to ``script.py`` (see
# execution/isolation.py ExecutionRequest docstring) — never surface it.
_SCRIPT_NAME = "script.py"
# AD-1221: the ship also generates the fetch helper and, when the workdir must
# be importable, a launcher. Both are machinery, not work products — without
# this the Captain would be handed `ship.py` as a "file the agent produced".
_GENERATED_NAMES = {_SCRIPT_NAME, SANDBOX_HELPER_FILENAME, "_probos_launch.py"}
# Directories that are machinery, not deliverables.
_SKIP_DIR_PARTS = {".venv", "venv", "__pycache__", ".git", "node_modules", ".pytest_cache"}
# Per-file cap so a runaway script can't push a huge blob into the store.
_MAX_ARTIFACT_BYTES = 25 * 1024 * 1024  # 25 MiB

# BF-726: what the tool may ADVERTISE, checked against what the sandbox can
# actually import rather than hand-listed in the description.
#
# The description used to name reportlab and matplotlib as examples. Neither is
# installed by default — they live in the ``crew-tools`` extra — so an agent
# asked for a PDF or a chart wrote exactly the script it had been told to write,
# died on the import, and spent its remaining iterations recovering. That is the
# same defect BF-719 fixed for the network, one layer down: a stated capability
# the sandbox does not have costs more than an unstated one, because the agent
# does not merely lack the option, it is actively misled into it.
#
# Deriving it also retires the enumeration. A hand-written list beside the thing
# it describes is the shape behind BF-701 (a tool advertising twelve actions
# while its gate held eleven) and AD-1177 — authored correct, then frozen while
# the thing it describes moved.
#
# Checking here is valid because the sandbox runs the submitted script under
# ``sys.executable`` (``isolation.py`` — ``python_executable or sys.executable``,
# and this tool never sets it), so this process's import table IS the sandbox's.
# If that ever stops being true, this derivation becomes a new false premise and
# must move into the sandbox.
_ARTIFACT_LIBRARIES: tuple[tuple[str, str, str], ...] = (
    # (import name, pip name, what an agent would use it for)
    ("docx", "python-docx", "a Word document"),
    ("openpyxl", "openpyxl", "a spreadsheet"),
    ("pptx", "python-pptx", "a slide deck"),
    ("reportlab", "reportlab", "a PDF"),
    ("matplotlib", "matplotlib", "a chart"),
    ("PIL", "Pillow", "an image"),
)

# AD-1219 (#1180): libraries that do not AUTHOR a downloadable artifact but that
# an agent reaches for constantly while producing one. Kept separate from
# `_ARTIFACT_LIBRARIES` because the two answer different questions -- "what can
# I hand the Captain" versus "what can I work with on the way there" -- and the
# description states them as separate clauses for that reason.
#
# These are advertised on the same terms as the artifact set: derived from real
# importability, and required to be declared core dependencies. Installing a
# library the agent is never told about is only half the Captain's request; an
# unnamed capability is one the agent will not reach for, which BF-726 already
# established is the same drift pointed the other way.
_ANALYSIS_LIBRARIES: tuple[tuple[str, str, str], ...] = (
    ("pandas", "pandas", "tabular data"),
    ("numpy", "numpy", "numerics"),
    ("bs4", "beautifulsoup4", "HTML parsing"),
    ("tabulate", "tabulate", "text tables"),
)


def _importable(module: str) -> bool:
    """Whether ``module`` can be imported in the interpreter the sandbox uses.

    ``find_spec`` raises rather than returning None for a missing PARENT package
    and for a malformed name, so the call is contained: an unimportable library
    must read as absent, never as an exception out of a description property.
    """
    try:
        return importlib.util.find_spec(module) is not None
    except Exception:  # noqa: BLE001 — absent is the only meaningful answer here
        return False


def _available_artifact_libraries() -> list[tuple[str, str]]:
    """The (pip name, purpose) pairs the sandbox can actually satisfy.

    Recomputed per call rather than cached: AD-1073 can install a package
    mid-session, and a description that keeps denying a library the agent just
    had installed would be the same lie in the opposite direction. Six
    ``find_spec`` calls is not a cost worth caching against that.
    """
    return [
        (pip_name, purpose)
        for module, pip_name, purpose in _ARTIFACT_LIBRARIES
        if _importable(module)
    ]


def _available_analysis_libraries() -> list[tuple[str, str]]:
    """AD-1219: the (pip name, purpose) processing libraries actually present.

    Same derivation and same rationale as :func:`_available_artifact_libraries`;
    separate list because the description states the two as separate clauses.
    """
    return [
        (pip_name, purpose)
        for module, pip_name, purpose in _ANALYSIS_LIBRARIES
        if _importable(module)
    ]

# Extension → mime for the produced-file cards. Unknown → octet-stream (still
# downloadable). Covers the document/data formats crew skills generate.
_MIME_BY_EXT: dict[str, str] = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".csv": "text/csv",
    ".json": "application/json",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".html": "text/html",
    ".htm": "text/html",
    ".xml": "application/xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".svg": "image/svg+xml",
}


def _mime_for(name: str) -> str:
    return _MIME_BY_EXT.get(Path(name).suffix.lower(), "application/octet-stream")


# AD-1178: what the model is told when an import in its script cannot resolve.
# Written as a REQUEST, never as a limitation: it names the module, states that
# the Captain can approve installing it, and says what to do meanwhile. It is
# authored to NOT match ``cognitive/decomposer._CAPABILITY_GAP_RE`` — a match
# would misread a routine "this needs a library" report as a capability gap and
# trip self-mod. ``tests/test_ad1178_missing_dependency.py`` asserts that through
# the real ``is_capability_gap`` (the assertion lives in the test so the tools
# layer keeps no import of the cognitive layer). Single ``{names}`` slot, phrased
# so it reads correctly for one module or several.
_DEPENDENCY_GUIDANCE = (
    "This script imports {names} — absent from the runtime environment, so the "
    "import failed. The Captain can approve installing {names} into the runtime "
    "venv; say plainly which module is needed and why, and ask for that approval. "
    "Meanwhile, retry using a module that is already present, or report the "
    "request to the Captain and stop."
)


def detect_unimportable(source_code: str) -> list[str]:
    """AD-1178: return the sorted, deduplicated root module names imported by
    ``source_code`` that this interpreter is unable to resolve to a spec.

    Deliberately NOT ``DependencyResolver.detect_missing``, and deliberately with
    no dependency on the resolver existing:

    * ``detect_missing`` answers *"which allowlisted packages are missing"*. Its
      ``__init__`` defaults ``policy="whitelist"`` and ``startup/
      cognitive_services.py`` constructs it WITHOUT a policy when dynamic install
      is off, so it ``continue``s past every import that is not on
      ``self_mod.allowed_imports`` **before** it checks availability. Verified on
      the reference vessel: ``detect_missing("import reportlab\\nimport
      matplotlib\\nimport json")`` returns ``[]``.
    * ``runtime.dependency_resolver`` is only constructed when
      ``self_mod.enabled or dependency.dynamic_install_enabled``, so an operator
      with both off has ``None``.

    This helper therefore has no allowlist, no policy and no runtime lookup. It
    answers the different question: *"which imports in this script will fail"*.

    The AD-993 sandbox runs the script under ``sys.executable`` in this same
    venv, so this process is a sound proxy for what that subprocess can import.

    No config flag gates this. It fires only when an import is genuinely
    unresolvable — already a failure the model is being shown a traceback for —
    so it adds information on an error path and removes none. A default-OFF flag
    would leave it inert for every operator, which is the failure mode AD-1175 /
    AD-1177 / AD-1180 were each correcting. The tool already returns ``stderr``
    unconditionally; this is the same category.

    Unparseable source returns ``[]`` — the run reports the ``SyntaxError``
    itself. Relative imports are skipped: they resolve against the workdir, not
    site-packages.
    """
    try:
        tree = ast.parse(source_code)
    except SyntaxError:
        return []

    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # ``from . import x`` / ``from ..pkg import y`` — workdir-relative.
            if getattr(node, "level", 0):
                continue
            if node.module:
                roots.add(node.module.split(".")[0])

    unimportable: list[str] = []
    for name in sorted(roots):
        if not name:
            continue
        try:
            resolved = importlib.util.find_spec(name) is not None
        except Exception:
            # find_spec raises ModuleNotFoundError for a missing parent package
            # and ValueError for some malformed names. Either way the import
            # fails, which is exactly what is being reported.
            resolved = False
        if not resolved:
            unimportable.append(name)
    return unimportable


class CodeExecutionTool:
    """AD-1066: run Python in a sandbox; files the script writes become
    downloadable artifacts on the chat thread (Cowork parity).

    Satisfies the AD-423a ``Tool`` protocol (duck-typed — no inheritance).
    Constructed with the runtime so it can read ``config.execution`` and the
    AD-797 stores. The chat ``thread_id`` arrives via the invocation ``context``
    (threaded from the AgenticLoop) so produced artifacts attach to the right
    conversation.
    """

    def __init__(self, *, runtime: Any) -> None:
        self._runtime = runtime

    # ── Tool protocol ─────────────────────────────────────────────
    @property
    def tool_id(self) -> str:
        return "run_python"

    @property
    def name(self) -> str:
        return "Run Python"

    @property
    def tool_type(self) -> ToolType:
        return ToolType.UTILITY_AGENT

    @property
    def description(self) -> str:
        # BF-726: the examples are DERIVED from what the sandbox can import, so
        # this cannot advertise a library the script would then fail to import.
        available = _available_artifact_libraries()
        if available:
            examples = ", ".join(f"{purpose} ({pip})" for pip, purpose in available)
            opening = (
                "Run a Python script in an isolated sandbox to produce a file — "
                f"e.g. {examples}. "
            )
        else:
            # Honest-degrade: no document library present. Still useful for
            # stdlib output (csv, json, text), and saying so beats naming
            # libraries that are not there.
            opening = (
                "Run a Python script in an isolated sandbox to produce a file. "
                "Only the standard library is available, so write formats it "
                "supports directly — CSV, JSON or plain text. "
            )
        # AD-1219: the processing libraries, derived on the same terms. Stated
        # as its own clause so it reads as "what you can work with" rather than
        # "what you can hand over", and omitted entirely when none are present
        # so the honest-degrade path stays clean.
        analysis = _available_analysis_libraries()
        if analysis:
            opening += (
                "Also available for working with data on the way there: "
                + ", ".join(f"{pip} ({purpose})" for pip, purpose in analysis)
                + ". "
            )
        # AD-1218: state the limits the agent can actually hit, derived from
        # config rather than written down, so a re-tuned sandbox cannot start
        # lying about itself the way BF-726's library list did. A limit an
        # agent can hit should be a limit it is told about, in the tool that
        # imposes it. The wall clock is the sharpest of these: a script looping
        # over fifteen URLs has no way to know it has 30 seconds, so it writes
        # something reasonable, gets killed mid-run, and has to diagnose a
        # truncation it was never warned about.
        cfg = self._cfg()
        limits = ""
        if cfg is not None:
            timeout = getattr(cfg, "timeout_seconds", None)
            out_bytes = getattr(cfg, "max_output_bytes", None)
            memory_mb = getattr(cfg, "max_memory_mb", None)
            parts: list[str] = []
            if timeout:
                parts.append(f"{float(timeout):.0f}s wall clock")
            if out_bytes:
                parts.append(f"{int(out_bytes) // 1024} KB of captured output")
            if memory_mb:
                parts.append(f"{int(memory_mb)} MB memory")
            if parts:
                limits = (
                    "Limits: " + ", ".join(parts) + ". Work that will not fit "
                    "inside those should be split into steps rather than run "
                    "until it is cut off. "
                )
        network = self._network_clause()
        return (
            opening
            + "Any file the "
            "script writes into the current working directory is saved and shown "
            "to the Captain as a downloadable artifact. Write files to the "
            "current directory by plain filename, e.g. "
            "doc.save('report.docx'). Returns stdout, stderr, the exit code, and "
            "the names of the files produced. "
            # BF-719: the constraint has to name the alternative, or it does not
            # change the choice. This previously read "Network is off; required
            # libraries must already be installed" as a trailing clause after an
            # opening that invited general use ("to perform a task or produce a
            # file"). Measured on the reference vessel 2026-08-05: an agent asked
            # to fetch fifteen web pages wrote a Python script to do it, every
            # request died against the blackhole proxy, and the turn produced
            # nothing. The agent HAD this description and still chose wrong.
            #
            # AD-1217: the routing guidance is kept verbatim in force — BF-719's
            # effect was re-observed live on 2026-08-07 — but the claim is no
            # longer phrased as an enforcement guarantee. `isolation.py`
            # `_build_env` sets blackhole PROXY variables and says so in its own
            # comment: "Soft deterrent only ... Hard network isolation is Tier
            # 2." requests/httpx honour them, which is why it holds in practice;
            # a raw socket would not. The risk was never an agent breaking out,
            # it was a reviewer or a later AD treating "HAS NO NETWORK ACCESS"
            # as an enforced boundary and building on it — the same class as the
            # false comment corrected in AD-1211. The sandbox docstring already
            # admits "a determined script can still read host files by absolute
            # path"; the filesystem limit was described honestly and the network
            # limit was not. Whether Tier 1 should actually enforce this is a
            # security-posture decision that belongs with the Captain (#1177),
            # and is deliberately NOT settled here.
            + limits
            + network
        )

    def _network_clause(self) -> str:
        """AD-1221: describe the network posture this run ACTUALLY has.

        The clause is derived from config at call time rather than written as a
        constant, because a constant is how AD-1217 went wrong: the description
        asserted a boundary that had stopped matching the code. When the relay
        is on, "OUTBOUND NETWORK IS BLOCKED" is simply false, and an agent that
        believes it will not use the capability the operator turned on — the
        BF-728 failure mode, where the work succeeded and the agent disbelieved
        its own result.
        """
        if getattr(self._cfg(), "fetch_broker_enabled", False):
            return (
                "Direct network access is blocked here, but you can fetch "
                "through the ship: `import ship; r = ship.fetch(url)` "
                "returns a dict with `body`, `status_code`, `truncated` and "
                "`total_bytes`. The ship performs the request under its normal "
                "SSRF checks and rate limits. PREFER THIS over http_fetch when "
                "you need to extract a small answer from a large document — "
                "fetch it and parse it here, and only print what you need, "
                "instead of carrying the whole document through the "
                "conversation. It raises ship.FetchError if the ship "
                "declines. Required libraries must already be installed."
            )
        return (
            "OUTBOUND NETWORK IS BLOCKED HERE — requests fail. To "
            "fetch a URL use the http_fetch tool instead, then pass the result "
            "into this tool if you need to process it. Required libraries must "
            "already be installed."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "The Python source to execute.",
                },
                "timeout": {
                    "type": "number",
                    "description": "Optional max seconds (default from config; capped at 300).",
                },
            },
            "required": ["code"],
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    # ── Execution ─────────────────────────────────────────────────
    def _cfg(self) -> Any:
        return getattr(getattr(self._runtime, "config", None), "execution", None)

    def _governed_fetcher(self) -> Any:
        """The registered agent that can perform a governed HTTP fetch, if any.

        Resolved by capability (does it expose ``fetch_governed``?) rather than
        by pool name or class, so the broker keeps working if the HTTP agent is
        renamed, re-pooled, or replaced by a differently-implemented one.
        """
        registry = getattr(self._runtime, "registry", None)
        if registry is None:
            return None
        try:
            agents = registry.all()
        except Exception:  # noqa: BLE001 — registry unavailable
            return None
        for agent in agents:
            if callable(getattr(agent, "fetch_governed", None)):
                return agent
        return None

    async def _start_fetch_broker(
        self, cfg: Any, workdir: Path,
    ) -> tuple[dict[str, str], SandboxFetchBroker | None]:
        """AD-1221: mint a per-run loopback fetch relay and the helper the
        script imports to use it.

        Returns ``({}, None)`` — the byte-identical pre-AD-1221 path — whenever
        the capability is off or unavailable. Every failure here degrades to
        "no relay this run" rather than failing the execution: the script can
        still do everything it could yesterday.
        """
        if not getattr(cfg, "fetch_broker_enabled", False):
            return {}, None

        fetcher = self._governed_fetcher()
        if fetcher is None:
            logger.warning(
                "AD-1221: execution.fetch_broker_enabled is on but no registered "
                "agent exposes fetch_governed; this run gets no fetch relay and "
                "probos.fetch() will report it is unavailable"
            )
            return {}, None

        cap = int(getattr(cfg, "fetch_broker_max_body_bytes", 8 * 1024 * 1024))

        async def _fetch(url: str, method: str) -> dict[str, Any]:
            return await fetcher.fetch_governed(url, method, max_body_bytes=cap)

        broker = SandboxFetchBroker(fetch=_fetch)
        try:
            host, port, token = await broker.start()
            (workdir / SANDBOX_HELPER_FILENAME).write_text(
                SANDBOX_HELPER_SOURCE, encoding="utf-8"
            )
        except Exception:  # noqa: BLE001 — degrade, do not fail the run
            logger.warning(
                "AD-1221: could not start the sandbox fetch relay; this run "
                "proceeds without it", exc_info=True,
            )
            try:
                await broker.stop()
            except Exception:  # noqa: BLE001
                pass
            return {}, None

        return (
            {
                "PROBOS_FETCH_HOST": host,
                "PROBOS_FETCH_PORT": str(port),
                "PROBOS_FETCH_TOKEN": token,
            },
            broker,
        )

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        t0 = time.monotonic()
        cfg = self._cfg()
        if cfg is None or not getattr(cfg, "enabled", False):
            return ToolResult(
                error="Code execution is disabled (set config.execution.enabled).",
            )
        code = str((params or {}).get("code") or "")
        if not code.strip():
            return ToolResult(error="No code provided.")

        ctx = context or {}
        thread_id = str(ctx.get("thread_id") or "")
        created_by = str(ctx.get("agent_id") or "agent")
        # AD-1220: attribution for an install ask needs the REAL agent, not the
        # "agent" placeholder `created_by` falls back to for artifact authorship.
        # A request the Captain cannot trace to a requester cannot answer the
        # only question that matters when approving one.
        requesting_agent = str(ctx.get("agent_id") or "")

        scratch_root = Path(getattr(cfg, "scratch_dir", "data/execution/scratch"))
        workdir = scratch_root / f"exec-{uuid.uuid4().hex}"
        broker: SandboxFetchBroker | None = None
        try:
            workdir.mkdir(parents=True, exist_ok=True)
            # AD-1074d: stage the thread's current documents into the workdir so
            # the script can read + modify them in place (the Cowork round-trip).
            staged: dict[str, str] = {}
            if getattr(cfg, "stage_thread_artifacts", False):
                staged = await self._stage_thread_artifacts(workdir, thread_id, cfg)
            # AD-1073: detect missing imports and (approval-gated) install them
            # BEFORE the run, reusing runtime.ensure_dependency. Default-OFF and
            # byte-identical to AD-1066 when dependency.dynamic_install_enabled is
            # False (returns None => no behavior change, no extra output key).
            dep_summary = await self._maybe_install_missing(
                code, requested_by=requesting_agent
            )
            sandbox = SubprocessSandbox(scratch_root=str(scratch_root))
            timeout = self._resolve_timeout(
                (params or {}).get("timeout"), getattr(cfg, "timeout_seconds", 30),
            )
            # AD-1221: stand up a loopback fetch relay for THIS run only, so the
            # script can fetch and extract in one process. Returns ({}, None)
            # when the capability is off, which is the byte-identical old path.
            broker_env, broker = await self._start_fetch_broker(cfg, workdir)
            res = await sandbox.run(
                ExecutionRequest(
                    code=code,
                    workdir=workdir,
                    timeout_seconds=timeout,
                    max_output_bytes=getattr(cfg, "max_output_bytes", 65536),
                    max_memory_mb=getattr(cfg, "max_memory_mb", 512),
                    allow_network=False,
                    env=(broker_env or None),
                    import_workdir=bool(broker_env),
                )
            )
            produced = await self._capture_artifacts(
                workdir, thread_id, created_by, staged,
            )
            output: dict[str, Any] = {
                "stdout": res.stdout,
                "stderr": res.stderr,
                "exit_code": res.exit_code,
                "success": res.success,
                "timed_out": res.timed_out,
                "artifacts": [a["name"] for a in produced],
                "artifact_details": produced,
            }
            if dep_summary is not None:
                output["dependencies"] = dep_summary
            else:
                # AD-1178: the install path is off (or found nothing), so a
                # genuinely unresolvable import would otherwise reach the model
                # as a bare traceback. Only reached when dep_summary is None, so
                # the AD-1073 enabled path above is untouched.
                unimportable = self._unimportable_summary(code)
                if unimportable is not None:
                    output["dependencies"] = unimportable
            return ToolResult(
                output=output,
                error=(res.error or None),
                duration_ms=(time.monotonic() - t0) * 1000.0,
            )
        except Exception as exc:
            logger.warning(
                "AD-1066: code execution tool failed for agent=%s: %s",
                created_by, exc, exc_info=True,
            )
            return ToolResult(error=f"execution failed: {exc}")
        finally:
            # AD-1221: the relay must not outlive the script it was minted for.
            # Closed here rather than after `sandbox.run` so a timeout, an
            # exception, or a cancelled turn all still take the socket down.
            if broker is not None:
                try:
                    await broker.stop()
                except Exception:  # noqa: BLE001 — teardown, run already over
                    logger.warning(
                        "AD-1221: sandbox fetch broker failed to close cleanly; "
                        "the listener may linger until process exit",
                        exc_info=True,
                    )
            shutil.rmtree(workdir, ignore_errors=True)

    def _unimportable_summary(self, code: str) -> dict[str, Any] | None:
        """AD-1178: turn an unresolvable import into a structured request the
        model can act on, instead of a bare ``ModuleNotFoundError`` traceback.

        Returns ``None`` when every import resolves, so a run with nothing
        missing carries no ``dependencies`` key — byte-identical to AD-1066.
        Never touches ``runtime.dependency_resolver``: it is ``None`` whenever
        ``self_mod.enabled`` and ``dependency.dynamic_install_enabled`` are both
        off. ``install_enabled`` is read from config rather than hardcoded, so
        the one case where this branch runs with the flag ON (the flag is set but
        ``detect_missing``'s whitelist filtered the import out) reports the
        operator's real setting instead of a false ``False``.
        """
        missing = detect_unimportable(code)
        if not missing:
            return None
        dep_cfg = getattr(getattr(self._runtime, "config", None), "dependency", None)
        return {
            "missing": missing,
            "install_enabled": bool(
                getattr(dep_cfg, "dynamic_install_enabled", False)
            ),
            "guidance": _DEPENDENCY_GUIDANCE.format(names=", ".join(missing)),
        }

    async def _maybe_install_missing(
        self, code: str, *, requested_by: str = ""
    ) -> dict | None:
        """AD-1073: detect missing third-party imports in ``code`` and, when the
        operator has opted in (``dependency.dynamic_install_enabled``), route them
        through ``runtime.ensure_dependency`` - the existing approval-gated
        detect -> approve -> install -> verify path (AD-838c). Installing into the
        runtime venv (which the AD-1066 sandbox shares via ``sys.executable``)
        means the very next run can import the package.

        Returns a summary dict (``missing`` / ``installed`` / ``declined`` /
        ``error``) for the tool output, or ``None`` when the feature is OFF or
        nothing is missing - keeping the default-OFF path byte-identical.

        AD-1220: ``requested_by`` carries the calling agent through to
        ``ensure_dependency`` so a no-approver decline files an ``install``
        capability request the Captain can approve in the HXI, attributed to
        whoever needs the library. Before this, the honest-degrade below was
        the whole story on an API vessel: the only approval callback is a Rich
        console prompt wired in the interactive shell, so the request was
        declined and nobody was ever asked."""
        dep_cfg = getattr(getattr(self._runtime, "config", None), "dependency", None)
        if dep_cfg is None or not getattr(dep_cfg, "dynamic_install_enabled", False):
            return None
        resolver = getattr(self._runtime, "dependency_resolver", None)
        ensure = getattr(self._runtime, "ensure_dependency", None)
        if resolver is None or ensure is None:
            return None
        try:
            missing = resolver.detect_missing(code)
        except Exception:
            logger.warning("AD-1073: detect_missing failed", exc_info=True)
            return None
        if not missing:
            return None
        try:
            res = await ensure(missing, requested_by=requested_by)
        except Exception:
            logger.warning(
                "AD-1073: ensure_dependency raised for %s", missing, exc_info=True,
            )
            return {
                "missing": missing, "installed": [], "declined": [],
                "error": "install attempt failed",
            }
        return {
            "missing": missing,
            "installed": list(getattr(res, "installed", []) or []),
            "declined": (
                list(getattr(res, "declined", []) or [])
                + list(getattr(res, "failed", []) or [])
            ),
            "error": getattr(res, "error", None),
        }

    async def _stage_thread_artifacts(
        self, workdir: Path, thread_id: str, cfg: Any,
    ) -> dict[str, str]:
        """AD-1074d: copy the thread's current artifacts (latest version of each
        name) into ``workdir`` so a script can read + modify them in place (the
        Cowork round-trip). Returns ``{name: content_hash}`` of what was staged
        so ``_capture_artifacts`` can skip unchanged inputs. Honest-degrade: no
        stores / no thread / a missing blob => stage what it can, never raise."""
        artifact_store = getattr(self._runtime, "artifact_store", None)
        attachment_store = getattr(self._runtime, "attachment_store", None)
        if artifact_store is None or attachment_store is None or not thread_id:
            return {}
        try:
            latest = artifact_store.list_thread_latest(thread_id)
        except Exception:
            logger.warning(
                "AD-1074d: could not list artifacts for thread %s; staging skipped",
                thread_id, exc_info=True,
            )
            return {}
        cap = max(0, int(getattr(cfg, "max_staged_artifacts", 20)))
        staged: dict[str, str] = {}
        for art in latest[:cap]:
            name = getattr(art, "name", "")
            # Never stage the sandbox's own script, or a name that would escape
            # the workdir (path traversal / nested paths).
            if not name or name in _GENERATED_NAMES or "/" in name or "\\" in name:
                continue
            if getattr(art, "size_bytes", 0) > _MAX_ARTIFACT_BYTES:
                continue
            try:
                blob = await attachment_store.read(art.content_hash)
            except Exception:
                logger.warning(
                    "AD-1074d: blob missing for staged artifact %s; skipping it",
                    name,
                )
                continue
            try:
                (workdir / name).write_bytes(blob)
            except OSError:
                continue
            staged[name] = art.content_hash
        return staged

    async def _capture_artifacts(
        self, workdir: Path, thread_id: str, created_by: str,
        staged: dict[str, str] | None = None,
    ) -> list[dict]:
        """Persist every file the script produced (except the sandbox script)
        to the AD-797 stores and return their metadata. Honest-degrade: no
        stores or no thread_id => nothing captured (stdout still returns).

        AD-1074d: ``staged`` maps ``name -> content_hash`` for documents copied
        into the workdir before the run; a produced file whose name+hash matches
        a staged input is an unchanged read and is NOT re-versioned."""
        artifact_store = getattr(self._runtime, "artifact_store", None)
        attachment_store = getattr(self._runtime, "attachment_store", None)
        if artifact_store is None or attachment_store is None or not thread_id:
            return []
        staged = staged or {}
        out: list[dict] = []
        for p in sorted(workdir.rglob("*")):
            if not p.is_file():
                continue
            rel_parts = p.relative_to(workdir).parts
            if any(part in _SKIP_DIR_PARTS for part in rel_parts):
                continue
            if len(rel_parts) == 1 and p.name in _GENERATED_NAMES:
                continue  # the sandbox's own script, not a deliverable
            try:
                blob = p.read_bytes()
            except OSError:
                continue
            if not blob or len(blob) > _MAX_ARTIFACT_BYTES:
                continue
            name = p.name
            content_hash = hashlib.sha256(blob).hexdigest()
            # AD-1074d: a staged input the script left untouched - don't create a
            # spurious new version of a document the agent only read.
            if staged.get(name) == content_hash:
                continue
            mime = _mime_for(name)
            try:
                await attachment_store.write(
                    content_hash, blob, mime, origin="agent_artifact",
                )
                art = artifact_store.add_version(
                    thread_id=thread_id,
                    name=name,
                    content_hash=content_hash,
                    mime=mime,
                    size_bytes=len(blob),
                    created_by=created_by,
                )
                out.append(
                    {
                        "artifact_id": art.id,
                        "content_hash": art.content_hash,
                        "thread_id": art.thread_id,
                        "name": art.name,
                        "mime": art.mime,
                        "size_bytes": art.size_bytes,
                        "version": art.version,
                    }
                )
            except Exception:
                logger.warning(
                    "AD-1066: failed to capture produced file %s as an artifact",
                    name, exc_info=True,
                )
        return out

    @staticmethod
    def _resolve_timeout(requested: Any, default: Any) -> float:
        try:
            t = float(requested) if requested is not None else float(default)
        except (TypeError, ValueError):
            t = float(default) if isinstance(default, (int, float)) else 30.0
        return max(1.0, min(t, 300.0))
