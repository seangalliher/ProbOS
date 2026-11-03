"""AD-1346 M3e1 (#1604): the sink set of property 1 and the census of its subprocess effect point; AD-1346 M3e3a: and of its egress point.

#1604 property 1 asks that every effect-point primitive (model call, tool call, subprocess, egress, store write) call the
shadow ``decide()`` or the shadow sink check, or hold a pinned ``system`` principal from a pinned allowlist. ``EFFECT_CLASSES`` names those five
classes and the slice that covers each; ``DELIVERED`` names the ones a member of ``TICKET_EFFECTS`` covers.

The subprocess class is read from BF-892's launch scan (``_scan_tree`` in ``tests/test_bf892_spawn_env_guard.py``, whose
module docstring lists what a static scan cannot see). Each (file, enclosing function) that scan finds is a row of
``SUBPROCESS_SITES`` with its launch count and one coverage:

- ``Sink(check, presented, service, via)``: the function ``check`` of the same file holds a ``check_at`` call for
  ``EFFECT_SUBPROCESS`` with ``service`` (by default ``SERVICE_EXPR``) as its service and ``presented`` as its presented
  id; ``via`` names, in call order, the functions between ``check`` and the launching one (AD-1346 M3e2a);
- ``System(principal, reason)``: a launch in a Ship's Computer service, under ``principal``;
- ``OutsideRuntime(reason)``: a launch in a module under ``OUTSIDE_RUNTIME``;
- ``Pending(owner, reason)``: a launch whose sink the slice ``owner`` adds;
- ``Unreached(names, reason)``: a launch that no other ``src`` code reaches through ``names`` (AD-1346 M3e2a).

``tests/test_ad1346_admission_effect_census.py`` checks the rows against the code (the Unreached rows' reach,
``unreached_references``: ``tests/test_ad1346_admission_subprocess_plumbing.py``, SP1), and SK7
(``tests/test_ad1346_admission_ticket_sinks.py``) reads ``subprocess_sink_functions`` and, from AD-1346 M3e3b, ``egress_check_functions``.

AD-1346 M3e3a: the egress class is read from a scan of its own, ``egress_points``, which parses every ``src`` module. A
call whose callee is a name of ``EGRESS_PRIMITIVES``, as the module's absolute imports bind it, is one point; a call
whose callee is not is one point for each argument, positional or keyword, that is. A name that no absolute import in
the module binds is not resolved. Points are grouped by (file, enclosing scope), scoped as BF-892 scopes a launch, into
the rows of ``EGRESS_SITES``, each with its count and one coverage: ``Sink`` (AD-1346 M3e3b: its check function holds
one ``check_at`` call for ``EFFECT_EGRESS``), ``Pending``, ``System``, ``OutsideRuntime``, ``OtherClass`` or
``ReachedOnlyFrom``. Among what the scan cannot see: a request made on a client built at another
point, a client a caller passes in, a name bound by anything but an absolute import, and a call inside a third-party
library. ``imported_modules`` reads the same imports; ``IMPORTS_WITHOUT_PRIMITIVE`` lists the top-level modules among
them, other than ``probos`` and the standard library's, that are the first component of no primitive's name.
``tests/test_ad1346_admission_egress_census.py`` checks the rows and those modules against the code.
"""

from __future__ import annotations

import ast
import functools
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import probos
from probos.admission.taxonomy import SYSTEM_PRINCIPAL_PREFIX
from tests.test_bf892_spawn_env_guard import _scan_tree

PACKAGE = Path(probos.__file__).resolve().parent
ROOT = PACKAGE.parents[1]
SHIP: Final = "system:ship_computer"
#: The service a subprocess sink hands ``check_at``: its runtime's, read with ``getattr`` defaults as the M3c sites read it.
SERVICE_EXPR: Final = "getattr(getattr(self, '_runtime', None), 'admission_service', None)"
#: The operator's command line: ``probos.__main__`` and the doctor package (D167).
OUTSIDE_RUNTIME: Final = ("src/probos/__main__.py", "src/probos/doctor/")
_OUTSIDE_MODULES: Final = ("probos.__main__", "probos.doctor")
_SEAM_HELPERS: Final = frozenset({"shadow_at", "hold_at", "check_at"})

#: #1604 property 1's five classes and what covers each (D168).
EFFECT_CLASSES: Final[dict[str, str]] = {
    "model_call": "AD-1346 M3d3a: OpenAICompatibleClient.complete (SK7, SK8)",
    "tool": "AD-1346 M3d3a: ToolRegistry.check_and_invoke (SK7)",
    "subprocess": "AD-1346 M3e1, M3e2a and M3e2b: SUBPROCESS_SITES",
    "egress": "AD-1346 M3e3a: EGRESS_SITES; its sinks, AD-1346 M3e3b and M3e3c",
    "store_write": "AD-1346 M3e4a: STORE_WRITE_FILES; AD-1346 M3e4b, M3e4d1, M3e4d2 and M3e4d3: STORE_WRITE_SCOPES and its checks (tests/fixtures/ad1346_store_census.py); AD-1346 M3e4c2: VECTOR_WRITE_SCOPES and BUS_WRITE_SCOPES (tests/fixtures/ad1346_store_family_census.py); AD-1346 M3e4c3a: FILE_WRITE_FILES (tests/fixtures/ad1346_file_write_census.py)",
}
#: The classes a member of ``TICKET_EFFECTS`` covers.
DELIVERED: Final = frozenset({"model_call", "tool", "subprocess", "egress", "store_write"})


@dataclass(frozen=True)
class Sink:
    check: str
    presented: str
    service: str = SERVICE_EXPR  # AD-1346 M3e2a: a component handed its service passes ``self._admission`` (D175)
    via: tuple[str, ...] = ()  # AD-1346 M3e2a: the functions between ``check`` and the launching one, in call order (D179)


@dataclass(frozen=True)
class System:
    principal: str
    reason: str


@dataclass(frozen=True)
class OutsideRuntime:
    reason: str


@dataclass(frozen=True)
class Pending:
    owner: str
    reason: str


@dataclass(frozen=True)
class Unreached:
    names: tuple[str, ...]
    reason: str


_TOOL_PRESENTED: Final = "context.get('agent_id') if type(context) is dict else None"

#: AD-1346 M3e2a (D175): the service a component handed it passes to ``check_at``.
_COMPONENT_SERVICE: Final = "self._admission"
#: AD-1346 M3e2b (D187): the executor of an approved build passes its own parameter to ``check_at``.
_PARAMETER_SERVICE: Final = "admission_service"
#: AD-1346 M3e2a (D177): the names by which other src code could reach the container sandboxes' launches.
_CONTAINER_NAMES: Final = ("container_sandbox", "InProcessContainerSandbox", "DockerContainerSandbox", "get_container_sandbox")

#: (file, enclosing function as BF-892 scopes it) -> (launches there, coverage). D163; AD-1346 M3e2a: D174 to D178.
SUBPROCESS_SITES: Final[dict[tuple[str, str], tuple[int, Sink | System | OutsideRuntime | Pending | Unreached]]] = {
    # Sinks: a launch an agent or model text directs, as that agent's work.
    ("src/probos/agents/shell_command.py", "ShellCommandAgent._run_sync"): (2, Sink("ShellCommandAgent._run_command", "None")),
    ("src/probos/agents/red_team.py", "RedTeamAgent._run_verify_sync"): (2, Sink("RedTeamAgent._verify_run_command", "None")),
    ("src/probos/agents/code_search.py", "CodeSearchAgent._search_rg"): (1, Sink("CodeSearchAgent._search_rg", "None")),
    ("src/probos/cognitive/scout.py", "ScoutAgent._search_github"): (1, Sink("ScoutAgent._search_github", "self.id")),
    ("src/probos/cognitive/swe_harness/tools.py", "RunCommandTool.invoke"): (1, Sink("RunCommandTool.invoke", _TOOL_PRESENTED)),
    # AD-1346 M3e2a: two components handed the service (D175, D176).
    ("src/probos/execution/isolation.py", "SubprocessSandbox._run_sync_inner"): (1, Sink("SubprocessSandbox.run", "None", service=_COMPONENT_SERVICE, via=("SubprocessSandbox._run_sync",))),
    ("src/probos/cognitive/dependency_resolver.py", "DependencyResolver._install_package"): (3, Sink("DependencyResolver._install_package", "None", service=_COMPONENT_SERVICE)),
    # AD-1346 M3e2b: the executor of an approved build, handed the service by the three src calls of it (D185 to D187).
    ("src/probos/cognitive/builder.py", "_run_targeted_tests._sync_run"): (1, Sink("execute_approved_build", "None", service=_PARAMETER_SERVICE, via=("_run_targeted_tests",))),
    # Unreached: no other src code reaches the launch through its names (D177).
    ("src/probos/cognitive/builder.py", "_run_tests._sync_run"): (1, Unreached(("_run_tests",), "the whole suite; no build path calls it since BF-897")),
    ("src/probos/security/container_sandbox.py", "InProcessContainerSandbox.run"): (1, Unreached(_CONTAINER_NAMES, "a thread workspace command; no other src module names the module")),
    ("src/probos/security/container_sandbox.py", "DockerContainerSandbox.run"): (1, Unreached(_CONTAINER_NAMES, "a thread workspace command; no other src module names the module")),
    # System: a launch in a Ship's Computer service.
    ("src/probos/cognitive/builder.py", "_run_git._sync_run"): (1, System(SHIP, "the build pipeline's git verbs, hardened (BF-904a); names and messages are data")),
    ("src/probos/cognitive/builder.py", "_is_dirty_working_tree"): (2, System(SHIP, "git rev-parse and status of the build tree, fixed argv")),
    ("src/probos/audio/tts/resident.py", "PiperWorker._spawn"): (1, System(SHIP, "resident piper; text on stdin")),
    ("src/probos/avatars/blender_renderer.py", "BlenderRenderer.render"): (1, System(SHIP, "blender running ProbOS's own script")),
    ("src/probos/avatars/rhubarb_backend.py", "_convert_to_wav._run_sync"): (1, System(SHIP, "ffmpeg, fixed argv")),
    ("src/probos/avatars/rhubarb_backend.py", "probe_version._probe_sync"): (1, System(SHIP, "rhubarb --version")),
    ("src/probos/avatars/rhubarb_backend.py", "_run_rhubarb._run_sync"): (1, System(SHIP, "rhubarb, fixed argv")),
    ("src/probos/cognitive/dm/artifact_extractor.py", "_to_docx_libreoffice"): (1, System(SHIP, "soffice convert; the text is data")),
    ("src/probos/cognitive/referent_gate.py", "GitObjectResolver._resolve_sync"): (1, System(SHIP, "git cat-file -e -- <token>, the gate's own check")),
    ("src/probos/credential_store.py", "CredentialStore._resolve"): (1, System(SHIP, "a registered credential helper")),
    ("src/probos/episodic_health.py", "check_episodic_health"): (1, System(SHIP, "ProbOS's own probe module")),
    ("src/probos/execution/authority.py", "_ManifestPreparer._repository_binding"): (3, System(SHIP, "the protected execution authority's manifest git")),
    ("src/probos/integrations/mcp_bridge/transport.py", "StdioTransport.start"): (1, System(SHIP, "an operator-approved MCP server")),
    ("src/probos/knowledge/records_store.py", "RecordsStore._git_sync"): (1, System(SHIP, "git on the records repo")),
    ("src/probos/knowledge/store.py", "KnowledgeStore._git_run"): (1, System(SHIP, "git on the knowledge repo")),
    ("src/probos/worktree_manager.py", "WorktreeManager._run_git"): (1, System(SHIP, "git worktree verbs")),
    # The operator's command line.
    ("src/probos/__main__.py", "_ensure_ollama"): (1, OutsideRuntime("ollama serve")),
    ("src/probos/__main__.py", "_check_nats"): (1, OutsideRuntime("nats-server")),
    ("src/probos/__main__.py", "_cmd_reset"): (2, OutsideRuntime("git add and commit during probos reset")),
    ("src/probos/doctor/checks/sandbox_check.py", "_docker_info_sync"): (1, OutsideRuntime("docker info for probos doctor")),
}

#: AD-1346 M3e3a (D194): the callees the egress census counts, by the dotted name a module's absolute imports give them.
EGRESS_PRIMITIVES: Final = frozenset({
    "httpx.AsyncClient", "httpx.Client", "httpx.get", "httpx.post", "httpx.put", "httpx.patch", "httpx.delete",
    "httpx.head", "httpx.options", "httpx.request", "httpx.stream",
    "requests.get", "requests.post", "requests.put", "requests.patch", "requests.delete", "requests.head",
    "requests.options", "requests.request", "requests.Session",
    "aiohttp.ClientSession", "aiohttp.request", "urllib.request.urlopen", "websockets.connect", "websockets.client.connect",
    "socket.socket", "socket.create_connection", "asyncio.open_connection",
    "smtplib.SMTP", "smtplib.SMTP_SSL", "imaplib.IMAP4", "imaplib.IMAP4_SSL",
    "nats.connect", "discord.Client", "zeroconf.Zeroconf", "zeroconf.asyncio.AsyncZeroconf",
    "playwright.async_api.async_playwright", "playwright.sync_api.sync_playwright",
    "zmq.Context", "zmq.asyncio.Context",
})

#: AD-1346 M3e3a (D201): the top-level modules ``src`` imports, other than ``probos`` and the standard library's, that are
#: the first component of no name of ``EGRESS_PRIMITIVES``.
IMPORTS_WITHOUT_PRIMITIVE: Final = frozenset({
    "PIL", "aiosqlite", "bpy", "chromadb", "copilot", "croniter", "cryptography", "docx", "dotenv", "facenet_pytorch",
    "fastapi", "jsonschema", "keyring", "msal", "openpyxl", "pptx", "pydantic", "pypdf", "rich", "starlette", "torch",
    "uvicorn", "yaml",
})


@dataclass(frozen=True)
class OtherClass:
    """AD-1346 M3e3a (D195): a client whose agent-attributed requests the delivered class ``effect_class`` checks in
    the function ``check``, a (file, qualified name) pair."""

    effect_class: str
    check: tuple[str, str]
    reason: str


@dataclass(frozen=True)
class ReachedOnlyFrom:
    """AD-1346 M3e3a (D195): a point whose ``names`` ``unreached_references`` finds only in files under ``allowed``."""

    names: tuple[str, ...]
    allowed: tuple[str, ...]
    reason: str


_MODEL_GATEWAY_CHECK: Final = ("src/probos/cognitive/llm_client.py", "OpenAICompatibleClient.complete")

#: (file, enclosing scope) -> (egress points there, coverage). AD-1346 M3e3a: D194, D195.
EGRESS_SITES: Final[dict[tuple[str, str], tuple[int, Sink | Pending | System | OutsideRuntime | OtherClass | ReachedOnlyFrom]]] = {
    # Sinks (AD-1346 M3e3b, D203 to D205): agent or model text picks the destination; the check function holds the check.
    ("src/probos/agents/http_fetch.py", "HttpFetchAgent._follow_and_fetch"): (1, Sink("HttpFetchAgent._fetch_url", "None", service=_COMPONENT_SERVICE, via=("HttpFetchAgent._fetch_url_uncoalesced",))),
    ("src/probos/agents/red_team.py", "RedTeamAgent._verify_http_fetch"): (1, Sink("RedTeamAgent._verify_http_fetch", "None")),
    # Sinks (AD-1346 M3e3c, D211 to D214): the browser tool's engine; the check function holds the check, before the engine starts or connects.
    ("src/probos/tools/browser/session.py", "BrowserSession._start_impl"): (1, Sink("BrowserSession.start", "self._agent_id", via=("BrowserSession._start_and_record",))),
    ("src/probos/tools/browser/session.py", "BrowserSession._connect_impl"): (1, Sink("BrowserSession.connect", "self._agent_id")),
    # Another delivered class checks the client's agent-attributed requests.
    ("src/probos/cognitive/llm_client.py", "OpenAICompatibleClient._build_client"): (1, OtherClass("model_call", _MODEL_GATEWAY_CHECK, "the model gateway's tier client; its endpoint probe is register R48's")),
    ("src/probos/cognitive/image_gen_dispatch.py", "dispatch_image_gen"): (1, OtherClass("model_call", ("src/probos/cognitive/image_gen_dispatch.py", "dispatch_image_gen"), "an agent's prompt to the operator's image_gen tier, which bypasses the model gateway")),
    # System.
    ("src/probos/integrations/mcp_bridge/transport.py", "HttpTransport.__init__"): (1, System(SHIP, "an operator-approved MCP server over HTTP")),
    ("src/probos/integrations/mcp_bridge/mcp_oauth.py", "McpOAuthProvider.__init__"): (1, System(SHIP, "an MCP server's OAuth flow")),
    ("src/probos/channels/matrix_client.py", "MatrixClient.__init__"): (1, System(SHIP, "the operator's Matrix channel")),
    ("src/probos/channels/slack_client.py", "SlackClient.__init__"): (1, System(SHIP, "the operator's Slack channel")),
    ("src/probos/channels/teams_client.py", "TeamsClient.__init__"): (1, System(SHIP, "the operator's Teams channel")),
    ("src/probos/channels/telegram_client.py", "TelegramClient.__init__"): (1, System(SHIP, "the operator's Telegram channel")),
    ("src/probos/channels/gmail_adapter.py", "GmailAdapter._fetch_unseen"): (1, System(SHIP, "the operator's Gmail inbox")),
    ("src/probos/channels/gmail_adapter.py", "GmailAdapter._acknowledge"): (1, System(SHIP, "the operator's Gmail inbox")),
    ("src/probos/channels/gmail_adapter.py", "GmailAdapter._send_sync"): (1, System(SHIP, "the operator's Gmail SMTP")),
    ("src/probos/channels/discord_adapter.py", "DiscordAdapter.start"): (1, System(SHIP, "the operator's Discord bot")),
    ("src/probos/channels/discord_adapter.py", "DiscordAdapter._run_with_error_handling"): (1, System(SHIP, "the operator's Discord bot")),
    ("src/probos/consultation/delivery.py", "GitHubAdapter._default_http_post"): (1, System(SHIP, "a consultation delivery")),
    ("src/probos/startup/finalize.py", "_wire_repair_dispatcher"): (1, System(SHIP, "the repair pipeline's GitHub issue client")),
    ("src/probos/federation/attachment_fetch.py", "fetch_remote_attachment"): (1, System(SHIP, "a federation peer's attachment")),
    ("src/probos/federation/attachment_fetch.py", "fetch_remote_attachment_signed"): (1, System(SHIP, "a federation peer's attachment")),
    ("src/probos/federation/ard/client.py", "ArdClient._get_bytes"): (1, System(SHIP, "an ARD request")),
    ("src/probos/federation/ard/client.py", "ArdClient._post_bytes"): (1, System(SHIP, "an ARD request")),
    ("src/probos/federation/ard/publication.py", "publish_catalog"): (1, System(SHIP, "ARD catalog publication")),
    ("src/probos/packs/marketplace.py", "fetch_marketplace_index"): (1, System(SHIP, "the marketplace index")),
    ("src/probos/cloud_pickers/google_drive.py", "GoogleDriveProvider.__init__"): (1, System(SHIP, "the Captain's Google Drive picker")),
    ("src/probos/integrations/m365_connector.py", "_graph_get"): (1, System(SHIP, "Microsoft Graph")),
    ("src/probos/mesh/nats_bus.py", "NATSBus.start"): (1, System(SHIP, "the ship's NATS bus")),
    ("src/probos/federation/transport.py", "FederationTransport.start"): (1, System(SHIP, "the operator's configured federation peers, over the ZeroMQ fallback transport")),
    ("src/probos/discovery/advertiser.py", "resolve_lan_ipv4"): (1, System(SHIP, "the LAN address lookup")),
    ("src/probos/discovery/advertiser.py", "ZeroconfAdvertiser.start"): (1, System(SHIP, "mDNS advertisement")),
    ("src/probos/federation/multicast_discovery.py", "_multicast_available"): (1, System(SHIP, "federation multicast discovery")),
    ("src/probos/federation/multicast_discovery.py", "MulticastDiscovery.start"): (2, System(SHIP, "federation multicast discovery")),
    # Named only in the files under ``allowed``.
    ("src/probos/federation/a2a/client.py", "A2AClient.__init__"): (1, ReachedOnlyFrom(("A2AClient",), ("src/probos/federation/a2a/__init__.py",), "no src module but its package names it")),
    ("src/probos/provider_setup.py", "_probe_client"): (1, ReachedOnlyFrom(("provider_setup",), OUTSIDE_RUNTIME, "the setup and doctor probes")),
    # The operator's command line (D167).
    ("src/probos/__main__.py", "_ensure_ollama"): (3, OutsideRuntime("the Ollama, before boot")),
    ("src/probos/__main__.py", "_check_nats._probe"): (1, OutsideRuntime("the NATS server, before boot")),
    ("src/probos/__main__.py", "_detect_llm_providers"): (1, OutsideRuntime("probos init's provider detection")),
    ("src/probos/doctor/checks/federation_check.py", "_FederationCheck.run"): (1, OutsideRuntime("probos doctor's federation check")),
    ("src/probos/doctor/checks/nats_check.py", "_NATSCheck.run"): (1, OutsideRuntime("probos doctor's NATS check")),
}


@functools.lru_cache(maxsize=1)
def src_sources() -> dict[str, str]:
    """Every module under ``src/probos`` by repo-relative path, as text (do not mutate the cached dict)."""
    return {path.relative_to(ROOT).as_posix(): path.read_text(encoding="utf-8-sig") for path in sorted(PACKAGE.rglob("*.py"))}


def launch_counts() -> dict[tuple[str, str], int]:
    """BF-892's launches by (file, enclosing function)."""
    return dict(Counter((launch.path, launch.scope) for launch in _scan_tree()))


def launch_lines() -> dict[tuple[str, str], list[int]]:
    """BF-892's launch lines by (file, enclosing function)."""
    lines: dict[tuple[str, str], list[int]] = {}
    for launch in _scan_tree():
        lines.setdefault((launch.path, launch.scope), []).append(launch.line)
    return lines


def subprocess_sink_functions() -> set[tuple[str, str]]:
    """(file, function) of each subprocess sink's check."""
    return {(path, cover.check) for (path, _scope), (_count, cover) in SUBPROCESS_SITES.items() if isinstance(cover, Sink)}


def egress_check_functions() -> set[tuple[str, str]]:
    """AD-1346 M3e3b: (file, function) of each egress sink's check and of each other-class row's check."""
    sinks = {(path, cover.check) for (path, _scope), (_count, cover) in EGRESS_SITES.items() if isinstance(cover, Sink)}
    return sinks | {cover.check for _count, cover in EGRESS_SITES.values() if isinstance(cover, OtherClass)}


def census_problems(found: dict[tuple[str, str], int], listed: dict[tuple[str, str], tuple[int, object]]) -> list[str]:
    """What differs between launches found and rows listed: unlisted sites, stale rows, then differing counts."""
    problems = [f"unlisted launch site {site}" for site in sorted(found.keys() - listed.keys())]
    problems += [f"stale row {site}" for site in sorted(listed.keys() - found.keys())]
    problems += [
        f"{site}: {found[site]} launches, the row says {listed[site][0]}"
        for site in sorted(found.keys() & listed.keys())
        if found[site] != listed[site][0]
    ]
    return problems


def references_outside(tree: ast.Module, name: str, allowed: tuple[str, ...]) -> list[tuple[str, int]]:
    """(enclosing function, line) of each reference to ``name``, as an attribute or a bare name, outside ``allowed``."""
    found: list[tuple[str, int]] = []

    def walk(node: ast.AST, scope: tuple[str, ...]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                walk(child, (*scope, child.name))
                continue
            qualname = ".".join(scope)
            named = (isinstance(child, ast.Attribute) and child.attr == name) or (isinstance(child, ast.Name) and child.id == name)
            if named and qualname not in allowed:
                found.append((qualname or "<module>", child.lineno))
            walk(child, scope)

    walk(tree, ())
    return found


def system_principal_literals(sources: dict[str, str]) -> set[str]:
    """The ``system:`` strings a ``shadow_at``, ``hold_at`` or ``check_at`` call passes as a literal ``presented_id``."""
    found: set[str] = set()
    for rel, source in sources.items():
        if not any(helper in source for helper in _SEAM_HELPERS):
            continue
        for node in ast.walk(ast.parse(source, filename=rel)):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            callee = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
            if callee not in _SEAM_HELPERS:
                continue
            for keyword in node.keywords:
                value = keyword.value
                if (
                    keyword.arg == "presented_id" and isinstance(value, ast.Constant) and isinstance(value.value, str)
                    and value.value.startswith(SYSTEM_PRINCIPAL_PREFIX)
                ):
                    found.add(value.value)
    return found


def outside_importers(sources: dict[str, str]) -> list[tuple[str, int]]:
    """(file, line) of each absolute import of ``probos.__main__`` or the doctor package by a module not under
    ``OUTSIDE_RUNTIME``."""
    found: list[tuple[str, int]] = []
    for rel, source in sources.items():
        if rel.startswith(OUTSIDE_RUNTIME) or ("__main__" not in source and "doctor" not in source):
            continue
        for node in ast.walk(ast.parse(source, filename=rel)):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module is not None:
                names = [node.module] + ([f"probos.{alias.name}" for alias in node.names] if node.module == "probos" else [])
            else:
                continue
            if any(name == module or name.startswith(f"{module}.") for name in names for module in _OUTSIDE_MODULES):
                found.append((rel, node.lineno))
    return found


def _reaching(node: ast.AST, outer: str, own: bool, wanted: frozenset[str], found: list[int]) -> None:
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            _reaching(child, outer or child.name, own, wanted, found)
            continue
        if isinstance(child, (ast.Import, ast.ImportFrom)):
            dotted = [alias.name for alias in child.names] + [getattr(child, "module", None) or ""]
            hit = any(part in wanted for name in dotted for part in name.split("."))
        elif isinstance(child, ast.Attribute):
            hit = child.attr in wanted and (own or not (isinstance(child.value, ast.Name) and child.value.id == "self"))
        else:
            hit = isinstance(child, ast.Name) and child.id in wanted
        if hit and not (own and outer in wanted):
            found.append(child.lineno)
        _reaching(child, outer, own, wanted, found)


def unreached_references(sources: dict[str, str], path: str, names: tuple[str, ...]) -> list[tuple[str, int]]:
    """(file, line) of references to ``names`` in ``sources`` (AD-1346 M3e2a, D177)."""
    wanted = frozenset(names)
    found: list[tuple[str, int]] = []
    for rel, source in sources.items():
        text = unicodedata.normalize("NFKC", source)
        if any(name in text for name in wanted):
            lines: list[int] = []
            _reaching(ast.parse(source, filename=rel), "", rel == path, wanted, lines)
            found += [(rel, line) for line in lines]
    return found


def _import_aliases(tree: ast.Module) -> dict[str, frozenset[str]]:
    """AD-1346 M3e3a: the dotted names each name is bound to by the module's absolute imports, in any scope."""
    names: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                names.setdefault(bound, set()).add(alias.name if alias.asname else bound)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            for alias in node.names:
                names.setdefault(alias.asname or alias.name, set()).add(f"{node.module}.{alias.name}")
    return {name: frozenset(targets) for name, targets in names.items()}


def _primitive(node: ast.AST, aliases: dict[str, frozenset[str]]) -> str | None:
    """The first name of ``EGRESS_PRIMITIVES``, in sorted order, that ``node`` may denote, or None."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    heads = aliases.get(node.id, frozenset()) if isinstance(node, ast.Name) else frozenset()
    tail = "".join(f".{part}" for part in reversed(parts))
    matches = sorted(head + tail for head in heads if head + tail in EGRESS_PRIMITIVES)
    return matches[0] if matches else None


class _EgressScan(ast.NodeVisitor):
    def __init__(self, aliases: dict[str, frozenset[str]]) -> None:
        self.aliases = aliases
        self.scope: list[str] = []
        self.points: list[tuple[str, int, str, str]] = []

    def _enter(self, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_ClassDef = visit_FunctionDef = visit_AsyncFunctionDef = _enter

    def visit_Call(self, node: ast.Call) -> None:
        where = ".".join(self.scope) or "<module>"
        callee = _primitive(node.func, self.aliases)
        if callee is not None:
            self.points.append((where, node.lineno, callee, "direct"))
        else:
            for arg in [*node.args, *(keyword.value for keyword in node.keywords)]:
                passed = _primitive(arg, self.aliases)
                if passed is not None:
                    self.points.append((where, node.lineno, passed, "by-reference"))
        self.generic_visit(node)


def egress_scan(source: str, filename: str = "<egress>") -> list[tuple[str, int, str, str]]:
    """(scope, line, primitive, shape) of each egress point in one module's source (AD-1346 M3e3a, D194)."""
    tree = ast.parse(source, filename=filename)
    scan = _EgressScan(_import_aliases(tree))
    scan.visit(tree)
    return scan.points


@functools.lru_cache(maxsize=1)
def egress_points() -> tuple[tuple[str, str, int, str, str], ...]:
    """(file, scope, line, primitive, shape) of each egress point in ``src``."""
    return tuple((rel, *point) for rel, source in src_sources().items() for point in egress_scan(source, rel))


def egress_counts() -> dict[tuple[str, str], int]:
    """The egress points by (file, enclosing scope)."""
    return dict(Counter((path, scope) for path, scope, _line, _primitive, _shape in egress_points()))


@functools.lru_cache(maxsize=1)
def imported_modules() -> frozenset[str]:
    """The first component of each dotted name ``_import_aliases`` reads from a ``src`` module (AD-1346 M3e3a, D201)."""
    return frozenset(
        target.split(".")[0]
        for rel, source in src_sources().items()
        for targets in _import_aliases(ast.parse(source, filename=rel)).values()
        for target in targets
    )
