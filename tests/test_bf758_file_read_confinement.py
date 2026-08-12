"""BF-758: a crew agent cannot read any file on the host.

`read_file` is in `_MESH_READ_INTENT_POOLS`, `step_4h_mesh_read_parse` runs on
every DM turn with no config flag, and `FileReaderAgent._read_file` was a bare
`Path(path).read_text()`. One tag read the credential vault.

The attack paths named in #1215 are asserted directly, so a regression is
described in the terms the defect was reported in rather than in terms of the
fix.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from probos.agents.file_reader import FileReaderAgent
from probos.security.file_access import (
    FileAccessDenied,
    resolve_read_path,
)


def _runtime(tmp_path: Path) -> SimpleNamespace:
    data = tmp_path / "data"
    (data / "execution" / "workspaces" / "agent-1").mkdir(parents=True)
    return SimpleNamespace(
        data_dir=data,
        config=SimpleNamespace(
            execution=SimpleNamespace(workspace_root=str(data / "execution" / "workspaces")),
            security_infra=SimpleNamespace(extra_read_roots=[]),
        ),
    )


def _roots(tmp_path: Path) -> dict:
    data = tmp_path / "data"
    return {
        "protected_roots": [data],
        "exempt_roots": [data / "execution" / "workspaces"],
    }


def _confined(tmp_path: Path) -> dict:
    data = tmp_path / "data"
    return {
        "protected_roots": [data],
        "exempt_roots": [data / "execution" / "workspaces"],
        "permitted_roots": [data / "execution" / "workspaces", tmp_path / "project"],
    }


# ---------------------------------------------------------------------------
# The floor
# ---------------------------------------------------------------------------

def test_the_credential_vault_is_not_readable(tmp_path: Path) -> None:
    """#1215's sharpest case. AD-1017 keeps secrets off the record and behind
    ``credential_ref`` precisely so a record leak is not a secret leak; an
    unconfined read walked around that design entirely."""
    _runtime(tmp_path)
    vault = tmp_path / "data" / "credential_vault.json"
    vault.write_text("{}", encoding="utf-8")

    with pytest.raises(FileAccessDenied):
        resolve_read_path(str(vault), **_roots(tmp_path))


def test_a_governance_database_is_not_readable(tmp_path: Path) -> None:
    _runtime(tmp_path)
    db = tmp_path / "data" / "tool_permissions.db"
    db.write_bytes(b"SQLite")

    with pytest.raises(FileAccessDenied):
        resolve_read_path(str(db), **_roots(tmp_path))


def test_a_path_outside_every_root_is_refused(tmp_path: Path) -> None:
    """Only when an operator has SET a confinement. By default ``read_file`` is
    a core capability the Captain uses on arbitrary paths, so the floor is a
    denylist and this is opt-in policy."""
    _runtime(tmp_path)
    outside = tmp_path / "elsewhere" / "id_rsa"
    outside.parent.mkdir(parents=True)
    outside.write_text("KEY", encoding="utf-8")

    assert resolve_read_path(str(outside), **_roots(tmp_path)) == outside.resolve()

    with pytest.raises(FileAccessDenied):
        resolve_read_path(str(outside), **_confined(tmp_path))


# ---------------------------------------------------------------------------
# The overlap that makes a flat deny wrong
# ---------------------------------------------------------------------------

def test_the_workspace_is_readable_even_though_it_sits_under_the_data_dir(
    tmp_path: Path,
) -> None:
    """The workspace root resolves UNDER the data directory, so a flat "deny
    the data dir" would block the one folder agents are meant to work in.
    Longest-prefix-match is what makes both rules hold at once."""
    _runtime(tmp_path)
    target = tmp_path / "data" / "execution" / "workspaces" / "agent-1" / "notes.md"
    target.write_text("work", encoding="utf-8")

    assert resolve_read_path(str(target), **_confined(tmp_path)) == target.resolve()


def test_the_project_tree_stays_readable(tmp_path: Path) -> None:
    """The Builder harness reads source across the project tree; confinement
    must not cost it its working capability."""
    _runtime(tmp_path)
    src = tmp_path / "project" / "module.py"
    src.parent.mkdir(parents=True)
    src.write_text("x = 1", encoding="utf-8")

    assert resolve_read_path(str(src), **_confined(tmp_path)) == src.resolve()


# ---------------------------------------------------------------------------
# Escapes
# ---------------------------------------------------------------------------

def test_a_traversal_escape_is_refused(tmp_path: Path) -> None:
    _runtime(tmp_path)
    escape = tmp_path / "project" / ".." / "data" / "credential_vault.json"

    with pytest.raises(FileAccessDenied):
        resolve_read_path(str(escape), **_roots(tmp_path))


@pytest.mark.skipif(
    not hasattr(Path, "symlink_to"), reason="symlinks unsupported"
)
def test_a_symlink_escape_is_refused(tmp_path: Path) -> None:
    """Resolution happens BEFORE the containment test, which is the whole
    reason that ordering matters -- a link inside a permitted root pointing
    out of it would otherwise pass a string check."""
    _runtime(tmp_path)
    secret = tmp_path / "data" / "credential_vault.json"
    secret.write_text("{}", encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir(parents=True, exist_ok=True)
    link = project / "innocent.txt"
    try:
        link.symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation requires privilege on this host")

    with pytest.raises(FileAccessDenied):
        resolve_read_path(str(link), **_roots(tmp_path))


def test_it_fails_closed_on_the_floor_regardless_of_policy(tmp_path: Path) -> None:
    """No configuration should be able to hand out the vault."""
    vault = tmp_path / "data" / "credential_vault.json"
    vault.parent.mkdir(parents=True, exist_ok=True)
    vault.write_text("{}", encoding="utf-8")

    with pytest.raises(FileAccessDenied):
        resolve_read_path(
            str(vault),
            protected_roots=[tmp_path / "data"],
            permitted_roots=[tmp_path],  # an operator permitting the whole tree
        )


def test_an_exemption_cannot_lift_a_deeper_floor(tmp_path: Path) -> None:
    """Longest prefix wins in BOTH directions: an exemption at or above the
    floor must not open it."""
    data = tmp_path / "data"
    data.mkdir(parents=True, exist_ok=True)
    secret = data / "tool_permissions.db"
    secret.write_bytes(b"x")

    with pytest.raises(FileAccessDenied):
        resolve_read_path(
            str(secret), protected_roots=[data], exempt_roots=[tmp_path]
        )


@pytest.mark.parametrize("bad", ["", "\x00evil"])
def test_a_malformed_path_is_refused(bad: str, tmp_path: Path) -> None:
    with pytest.raises(FileAccessDenied):
        resolve_read_path(bad, **_roots(tmp_path))


# ---------------------------------------------------------------------------
# CROSSING: through the agent that the [MESH] seam actually reaches
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_the_mesh_reachable_agent_refuses_the_vault(tmp_path: Path) -> None:
    """The helper being correct proves nothing about the agent. This drives
    ``FileReaderAgent`` itself -- the object ``[MESH read_file]`` resolves to."""
    runtime = _runtime(tmp_path)
    vault = tmp_path / "data" / "credential_vault.json"
    vault.write_text("SECRET-TOKEN", encoding="utf-8")
    agent = FileReaderAgent(agent_id="fr-1", runtime=runtime)

    result = await agent._read_file(str(vault))

    assert result["success"] is False
    assert "SECRET-TOKEN" not in str(result), "the refusal leaked the contents"


@pytest.mark.asyncio
async def test_the_mesh_reachable_agent_still_reads_its_workspace(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    target = tmp_path / "data" / "execution" / "workspaces" / "agent-1" / "n.md"
    target.write_text("hello", encoding="utf-8")
    agent = FileReaderAgent(agent_id="fr-1", runtime=runtime)

    result = await agent._read_file(str(target))

    assert result["success"] is True
    assert result["data"] == "hello"


@pytest.mark.asyncio
async def test_an_ordinary_file_is_still_readable(tmp_path: Path) -> None:
    """``read_file`` is the canonical intent across the mesh, consensus,
    Hebbian and episodic suites, and the Captain names arbitrary paths. The
    floor must not cost that."""
    runtime = _runtime(tmp_path)
    ordinary = tmp_path / "notes.txt"
    ordinary.write_text("plain", encoding="utf-8")
    agent = FileReaderAgent(agent_id="fr-1", runtime=runtime)

    result = await agent._read_file(str(ordinary))

    assert result["success"] is True
    assert result["data"] == "plain"


@pytest.mark.asyncio
async def test_stat_is_confined_too(tmp_path: Path) -> None:
    """Existence and size are themselves information; an unbounded stat
    enumerates the host."""
    runtime = _runtime(tmp_path)
    vault = tmp_path / "data" / "credential_vault.json"
    vault.write_text("{}", encoding="utf-8")
    agent = FileReaderAgent(agent_id="fr-1", runtime=runtime)

    result = await agent._stat_file(str(vault))

    assert result["success"] is False


# ---------------------------------------------------------------------------
# The description must match the boundary
# ---------------------------------------------------------------------------

def test_the_tool_description_matches_what_it_enforces() -> None:
    """It advertised "from the project tree" while passing absolute paths
    through -- a false claim in an agent-facing surface, which is what makes
    the model trust a boundary that was not there. Superseded in scope by
    ``test_the_tool_description_does_not_claim_confinement_that_is_off``; kept
    because the original false claim is what this file exists to prevent."""
    from probos.cognitive.swe_harness.tools import ReadFileTool

    description = ReadFileTool.description.lower()

    assert "project tree" in description, "relative resolution must be stated"
    assert "not readable" in description or "refused" in description


def test_the_name_guard_names_files_this_system_actually_writes() -> None:
    """The first draft guarded ``vault.json``/``credentials.json``. Neither has
    ever been written by this system -- the real names come from
    ``CredentialVaultConfig``. A guard listing files that do not exist is not a
    guard, and it reads exactly like one. Derived from the config here so it
    cannot drift back into decoration."""
    from probos.config import CredentialVaultConfig
    from probos.security.file_access import PROTECTED_LEAF_NAMES

    cfg = CredentialVaultConfig()

    for field in ("file_path", "keyring_index_path"):
        assert Path(getattr(cfg, field)).name in PROTECTED_LEAF_NAMES, field


# ---------------------------------------------------------------------------
# The siblings: same allowlist, same seam
# ---------------------------------------------------------------------------

def test_every_filesystem_intent_on_the_mesh_seam_is_confined() -> None:
    """Confining ``read_file`` alone would have MOVED the leak, not closed it.
    ``list_directory`` still enumerated the data directory and ``search_content``
    ran ripgrep over it -- and ripgrep returns matching LINES, so a content
    search was a way to grep the credential store.

    Derived from ``_MESH_READ_INTENT_POOLS`` rather than hardcoded, so a new
    filesystem intent added to that allowlist fails here instead of shipping
    unbounded.
    """
    import inspect

    from probos.agents.code_search import CodeSearchAgent
    from probos.agents.directory_list import DirectoryListAgent
    from probos.agents.file_reader import FileReaderAgent
    from probos.agents.file_search import FileSearchAgent
    from probos.cognitive.dm.reply_pipeline import _MESH_READ_INTENT_POOLS

    by_pool = {
        "filesystem": FileReaderAgent,
        "directory": DirectoryListAgent,
        "search": FileSearchAgent,
        "code_search": CodeSearchAgent,
    }
    network_pools = {"web", "browser", "http"}

    for intent, pool in _MESH_READ_INTENT_POOLS.items():
        agent = by_pool.get(pool)
        if agent is None:
            assert pool in network_pools or intent in {"read_page", "web_search"}, (
                f"{intent!r} routes to pool {pool!r}, which this test does not "
                "know about -- if it touches the filesystem it needs confining"
            )
            continue
        assert "resolve_for_runtime" in inspect.getsource(agent), (
            f"{intent!r} -> {agent.__name__} reads the filesystem from "
            "agent-authored text without confinement"
        )


@pytest.mark.asyncio
async def test_listing_the_data_directory_is_refused(tmp_path: Path) -> None:
    from probos.agents.directory_list import DirectoryListAgent

    runtime = _runtime(tmp_path)
    agent = DirectoryListAgent(agent_id="dl-1", runtime=runtime)

    result = await agent._list_directory(str(tmp_path / "data"))

    assert result["success"] is False


@pytest.mark.asyncio
async def test_content_search_over_the_data_directory_is_refused(
    tmp_path: Path,
) -> None:
    """The sharpest sibling: ripgrep returns matching lines."""
    from probos.agents.code_search import CodeSearchAgent

    runtime = _runtime(tmp_path)
    agent = CodeSearchAgent(agent_id="cs-1", runtime=runtime)

    result = await agent.act(
        {"action": "search", "path": str(tmp_path / "data"), "pattern": "token"}
    )

    assert result["success"] is False


# ---------------------------------------------------------------------------
# Review findings
# ---------------------------------------------------------------------------

def test_the_configurable_root_actually_exists_on_the_config() -> None:
    """REVIEW FINDING. ``permitted_read_roots`` read ``security_infra.read_roots``
    via ``getattr``, and no such field existed -- so the policy layer was
    permanently empty and could not be configured, while the tool description
    told the model paths outside those roots were refused. A guard reading a
    field that does not exist is the same defect as a docstring claiming a
    property the code lacks; ``getattr`` with a default hides it perfectly."""
    from probos.config import SecurityInfraConfig

    cfg = SecurityInfraConfig()

    assert "read_roots" in type(cfg).model_fields
    assert cfg.read_roots == [], "confinement must be opt-in"


def test_confinement_engages_once_configured(tmp_path: Path) -> None:
    """The knob has to do something, not merely exist."""
    from probos.config import SecurityInfraConfig
    from probos.security.file_access import permitted_read_roots

    runtime = SimpleNamespace(
        data_dir=tmp_path / "data",
        config=SimpleNamespace(
            security_infra=SecurityInfraConfig(read_roots=[str(tmp_path / "allowed")]),
            execution=SimpleNamespace(workspace_root=str(tmp_path / "ws")),
        ),
    )

    roots = permitted_read_roots(runtime)

    assert (tmp_path / "allowed").resolve() in roots
    assert any("ws" in str(r) for r in roots), "the workspace is always readable"


def test_a_relative_path_still_resolves_against_the_project_tree() -> None:
    """REVIEW FINDING. ``ReadFileTool._resolve_path`` rooted relative paths at
    the project tree. Resolving against the process CWD instead silently broke
    every relative read the Builder makes -- it holds this tool alongside
    write_file and run_command, and a security fix must not cost it that."""
    from probos.cognitive.swe_harness.tools import _PROJECT_ROOT
    from probos.security.file_access import resolve_read_path

    resolved = resolve_read_path(
        "probos/security/file_access.py",
        protected_roots=[],
        relative_base=_PROJECT_ROOT,
    )

    assert resolved == (_PROJECT_ROOT / "probos/security/file_access.py").resolve()


def test_the_tool_description_does_not_claim_confinement_that_is_off(
    tmp_path: Path,
) -> None:
    """REVIEW FINDING, and the second time on the same line. The original said
    "from the project tree" while passing absolute paths through. My first fix
    said "paths outside those roots are refused", which is only true once an
    operator sets ``read_roots`` -- so by default it was equally false. The
    description must describe the DEFAULT."""
    from probos.cognitive.swe_harness.tools import ReadFileTool

    description = ReadFileTool.description.lower()

    assert "data directory" in description
    assert "workspace" not in description or "read_roots" in description


@pytest.mark.skipif(not hasattr(__import__("os"), "link"), reason="no hard links")
def test_a_hard_link_into_the_floor_is_a_known_limitation(tmp_path: Path) -> None:
    """REVIEW FINDING, pinned as a LIMITATION rather than silently unknown.

    ``Path.resolve()`` follows symlinks and junctions but NOT hard links -- a
    hard link is a second directory entry for the same inode, and there is no
    "where does this really live" to resolve. So a hard link created inside an
    exempt root pointing at a protected file reads that file.

    Scope: creating a hard link requires WRITE access, which the ``[MESH]`` seam
    (read/list/search only) does not have. The only agent path that can create
    one is ``run_python``, which ``execution/isolation.py`` documents as able to
    read host files by absolute path anyway -- so this grants nothing that path
    did not already have. That is why it is recorded rather than blocking, and
    why closing it belongs with AD-995 Tier-2 isolation.

    This test asserts the CURRENT behaviour. If it starts failing, the
    limitation has been closed and the docstring should go with it.
    """
    import os

    from probos.security.file_access import resolve_read_path

    data = tmp_path / "data"
    workspace = data / "execution" / "workspaces" / "agent"
    workspace.mkdir(parents=True)
    secret = data / "tool_permissions.db"
    secret.write_text("SECRET", encoding="utf-8")
    alias = workspace / "innocent.txt"
    try:
        os.link(secret, alias)
    except (OSError, NotImplementedError, AttributeError):
        pytest.skip("hard links unsupported on this host")

    resolved = resolve_read_path(
        str(alias),
        protected_roots=[data],
        exempt_roots=[data / "execution" / "workspaces"],
    )

    assert resolved == alias.resolve(), (
        "if this now raises, the hard-link limitation is closed -- update the "
        "docstring and the BF-758 issue"
    )
