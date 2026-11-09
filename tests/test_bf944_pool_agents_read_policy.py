"""BF-944 (#1717): a pool-built file reader, directory list and file search agent apply the runtime's read policy.

The real ``ProbOSRuntime.create_pool`` (unbound, over a runtime double after ``tests/test_ad1346_admission_sink_wiring.py``'s) builds the
pools; the agents and the policy are real; files and links are made under ``tmp_path``; no network is opened. The functions before the
class pass on both trees. T13 imports BF-961's ``read_stored_list``; no BF-944 name is imported.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

import probos.security.file_access as file_access
from probos.agents.directory_list import DirectoryListAgent
from probos.agents.file_reader import FileReaderAgent
from probos.agents.file_search import FileSearchAgent
from probos.agents.utility.stored_list import ReadStatus, read_stored_list
from probos.cognitive.dm_sanity_gate import DmSanityGate
from probos.config import TRUST_DEFAULT, ExecutionConfig, PoolConfig, SecurityInfraConfig, SystemConfig, format_trust
from probos.consensus.trust import TrustNetwork
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.runtime import ProbOSRuntime
from probos.substrate.registry import AgentRegistry
from probos.substrate.spawner import AgentSpawner
from probos.types import AgentState, IntentMessage
from tests.test_ad869_mesh_read_inline import _make_pipeline

_OUTSIDE = "path is outside every readable root"
_PROTECTED = "path is protected: the runtime's data directory or a config file"
_POOL = {"file_reader": "filesystem", "directory_list": "directory", "file_search": "search"}
_CLASS = {"file_reader": FileReaderAgent, "directory_list": DirectoryListAgent, "file_search": FileSearchAgent}
TYPES = list(_POOL)


def _scene(tmp_path):
    """allowed/, outside/ and vessel_data/ (not named ``data``, which the default walk prunes)."""
    root = tmp_path.resolve()
    scene = SimpleNamespace(root=root, allowed=root / "allowed", outside=root / "outside", data=root / "vessel_data")
    scene.workspace = scene.data / "workspaces"
    for name, text in {
        "allowed/ok.txt": "ok", "allowed/sub/inner.txt": "inner", "outside/secret.txt": "outside contents",
        "outside/deep/deeper.txt": "deeper", "vessel_data/trust.db": "governance", "vessel_data/workspaces/scratch.txt": "scratch",
    }.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    return scene


async def _no_log(**kwargs):
    return None


def _runtime(scene, read_roots):
    """A runtime double for ``create_pool``: a real config, registry, spawner and trust network, the three templates, and the
    vessel's own data directory (not the platform's)."""
    config = SystemConfig(
        pools=PoolConfig(default_pool_size=2, min_pool_size=1, max_pool_size=3),
        security_infra=SecurityInfraConfig(read_roots=[str(root) for root in read_roots]),
        execution=ExecutionConfig(workspace_root=str(scene.workspace)),
    )
    registry = AgentRegistry()
    runtime = SimpleNamespace(config=config, data_dir=scene.data, pools={}, registry=registry, spawner=AgentSpawner(registry),
                              trust_network=TrustNetwork(), event_log=SimpleNamespace(log=_no_log))
    for agent_type, cls in _CLASS.items():
        runtime.spawner.register_template(agent_type, cls)
    return runtime


@asynccontextmanager
async def _fleet(scene, read_roots):
    """The three pools through the real factory, as ``create_agent_fleet`` calls it (no ``runtime`` keyword), and a member of each."""
    runtime = _runtime(scene, read_roots)
    try:
        for agent_type, pool in _POOL.items():
            await ProbOSRuntime.create_pool(runtime, pool, agent_type, target_size=2)
        yield runtime, {agent_type: runtime.registry.get_by_pool(pool)[0] for agent_type, pool in _POOL.items()}
    finally:
        for pool in list(runtime.pools.values()):
            await pool.stop()


def _control(agent_type, runtime=None):
    """An agent built as the unfixed factory builds it (no runtime) or, given one, as BF-758's tests build theirs."""
    return _CLASS[agent_type](agent_id=f"ad944-{agent_type}", runtime=runtime)


async def _ask(agent, intent, **params):
    result = await agent.handle_intent(IntentMessage(intent=intent, params=params))
    assert result is not None, "premise: the agent handles the intent"
    return result


def _call(agent_type, where, name="secret.txt"):
    """The intent that reaches *where* through *agent_type*: a read of *name* there, or a listing or a search of it."""
    if agent_type == "file_reader":
        return "read_file", {"path": str(where / name)}
    if agent_type == "directory_list":
        return "list_directory", {"path": str(where)}
    return "search_files", {"path": str(where), "pattern": "*.txt"}


async def _entries(agent, where):
    return {item["name"]: item for item in (await _ask(agent, "list_directory", path=str(where))).result}


def _names(result, base):
    return sorted(Path(match).relative_to(base).as_posix() for match in result.result)


@contextmanager
def _linked(link, target):
    """A directory junction on Windows (no privilege needed) or a symlink elsewhere; a file link needs a symlink and skips where the
    host grants none."""
    directory = target.is_dir()
    if directory and os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError):
            pytest.skip("a symlink needs a privilege this host does not grant")
    try:
        yield link
    finally:
        if directory and os.name == "nt":
            link.rmdir()
        else:
            link.unlink()


@pytest.mark.parametrize("agent_type", TYPES)
async def test_with_empty_roots_a_pooled_member_answers_as_an_agent_with_no_runtime(tmp_path, agent_type):
    """G1: the control round first, so the equality is about the empty setting and not a policy that is off."""
    scene = _scene(tmp_path)
    intent, params = _call(agent_type, scene.outside)
    confined = await _ask(_control(agent_type, _runtime(scene, [scene.allowed])), intent, **params)
    assert (confined.success, confined.error) == (False, _OUTSIDE), "premise: set roots refuse the outside directory"
    async with _fleet(scene, []) as (_rt, members):
        for where, name in ((scene.outside, "secret.txt"), (scene.allowed, "ok.txt")):
            intent, params = _call(agent_type, where, name)
            pooled, bare = await _ask(members[agent_type], intent, **params), await _ask(_control(agent_type), intent, **params)
            assert bare.success is True, "premise: an agent with no runtime serves it"
            assert (pooled.success, pooled.result, pooled.error) == (bare.success, bare.result, bare.error)


@pytest.mark.parametrize("kind", ["directory", "file"])
async def test_a_link_to_a_target_inside_the_roots_is_unchanged(tmp_path, kind):
    """G2: listed with its target's kind and size, and named by a search."""
    scene = _scene(tmp_path)
    target = scene.allowed / ("sub" if kind == "directory" else "ok.txt")
    with _linked(scene.allowed / "inside", target):
        async with _fleet(scene, [scene.allowed]) as (_rt, members):
            entry = (await _entries(members["directory_list"], scene.allowed))["inside"]
            assert entry == {"name": "inside", "type": "dir" if kind == "directory" else "file", "size": target.stat().st_size}
            named = await _ask(members["file_search"], "search_files", path=str(scene.allowed), pattern="inside", include_ignored=True)
            assert _names(named, scene.allowed) == ["inside"]


async def test_a_callers_own_runtime_wins(tmp_path):
    """G3: the factory's runtime has no roots, the caller's confines, and the member keeps the caller's."""
    scene = _scene(tmp_path)
    factory = _runtime(scene, [])
    try:
        await ProbOSRuntime.create_pool(factory, "filesystem", "file_reader", target_size=1, runtime=_runtime(scene, [scene.allowed]))
        (member,) = factory.registry.get_by_pool("filesystem")
        intent, params = _call("file_reader", scene.outside)
        refused = await _ask(member, intent, **params)
        assert (refused.success, refused.error) == (False, _OUTSIDE)
    finally:
        for pool in list(factory.pools.values()):
            await pool.stop()


class TestAPoolBuiltAgentAppliesTheRuntimesReadPolicy:
    # BF-944 M1: xfail until M2 builds it (M2 removes this line and the next).
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-944 M2 builds it")

    @pytest.mark.parametrize("agent_type", TYPES)
    async def test_a_member_refuses_a_base_outside_read_roots_and_serves_one_inside(self, tmp_path, agent_type):
        """T1."""
        scene = _scene(tmp_path)
        intent, params = _call(agent_type, scene.outside)
        assert (await _ask(_control(agent_type), intent, **params)).success is True, "premise: an agent with no runtime serves it"
        async with _fleet(scene, [scene.allowed]) as (_rt, members):
            refused = await _ask(members[agent_type], intent, **params)
            assert (refused.success, refused.error) == (False, _OUTSIDE)
            intent, params = _call(agent_type, scene.allowed, "ok.txt")
            served = await _ask(members[agent_type], intent, **params)
            assert (served.success, served.error) == (True, None)

    async def test_with_empty_roots_the_floor_is_the_vessels_own_data_directory(self, tmp_path):
        """T2: the runtime's data directory is refused; its workspace and any other path read, as before."""
        scene = _scene(tmp_path)
        governance = {"path": str(scene.data / "trust.db")}
        assert (await _ask(_control("file_reader"), "read_file", **governance)).success is True, "premise: the platform's floor is not this vessel's"
        async with _fleet(scene, []) as (_rt, members):
            refused = await _ask(members["file_reader"], "read_file", **governance)
            assert (refused.success, refused.error) == (False, _PROTECTED)
            listed = await _ask(members["directory_list"], "list_directory", path=str(scene.data))
            assert (listed.success, listed.error) == (False, _PROTECTED)
            scratch = await _ask(members["file_reader"], "read_file", path=str(scene.workspace / "scratch.txt"))
            assert (scratch.success, scratch.result) == (True, "scratch")
            elsewhere = await _ask(members["file_reader"], "read_file", path=str(scene.outside / "secret.txt"))
            assert (elsewhere.success, elsewhere.result) == (True, "outside contents")

    @pytest.mark.parametrize("kind", ["directory", "file"])
    async def test_the_lister_reports_no_kind_or_size_for_a_link_out_of_the_roots(self, tmp_path, kind):
        """T3."""
        scene = _scene(tmp_path)
        with _linked(scene.allowed / "door", scene.outside if kind == "directory" else scene.outside / "secret.txt"):
            through = scene.allowed / "door" / ("secret.txt" if kind == "directory" else "")
            reader = _control("file_reader", _runtime(scene, [scene.allowed]))
            assert (await _ask(reader, "read_file", path=str(through))).error == _OUTSIDE, "premise: a read through the link is refused"
            async with _fleet(scene, [scene.allowed]) as (_rt, members):
                entries = await _entries(members["directory_list"], scene.allowed)
                assert entries["door"] == {"name": "door", "type": "unknown", "size": 0}
                assert entries["ok.txt"] == {"name": "ok.txt", "type": "file", "size": 2}

    async def test_a_link_to_the_floor_is_an_entry_that_cannot_be_read_with_empty_roots(self, tmp_path):
        """T4."""
        scene = _scene(tmp_path)
        with _linked(scene.allowed / "vessel", scene.data):
            assert (await _entries(_control("directory_list"), scene.allowed))["vessel"]["type"] == "dir", "premise: with no runtime it is followed"
            async with _fleet(scene, []) as (_rt, members):
                assert (await _entries(members["directory_list"], scene.allowed))["vessel"] == {"name": "vessel", "type": "unknown", "size": 0}

    async def test_a_pattern_with_a_dotdot_part_names_nothing_outside_the_roots(self, tmp_path):
        """T5."""
        scene = _scene(tmp_path)
        reach = {"path": str(scene.allowed), "pattern": "../outside/*.txt", "include_ignored": True}
        reached = await _ask(_control("file_search"), "search_files", **reach)
        assert [Path(match).resolve() for match in reached.result] == [scene.outside / "secret.txt"], "premise: the pattern reaches the outside file"
        async with _fleet(scene, [scene.allowed]) as (_rt, members):
            found = await _ask(members["file_search"], "search_files", **reach)
            assert (found.success, found.result) == (True, [])

    @pytest.mark.parametrize("include_ignored", [False, True], ids=["walk", "rglob"])
    @pytest.mark.parametrize("kind", [
        pytest.param("directory", marks=pytest.mark.skipif(os.name != "nt", reason="rglob and os.walk follow a directory junction on Windows only")),
        "file",
    ])
    async def test_a_link_out_of_the_roots_lists_nothing_outside_them(self, tmp_path, kind, include_ignored):
        """T6: a directory junction on Windows, or a file symlink where the host grants one."""
        scene = _scene(tmp_path)
        params = {"path": str(scene.allowed), "pattern": "*.txt", "include_ignored": include_ignored}
        link, target = (scene.allowed / "door", scene.outside) if kind == "directory" else (scene.allowed / "peek.txt", scene.outside / "secret.txt")
        with _linked(link, target):
            reached = _names(await _ask(_control("file_search"), "search_files", **params), scene.allowed)
            assert set(reached) > {"ok.txt", "sub/inner.txt"}, "premise: the link leads outside"
            async with _fleet(scene, [scene.allowed]) as (_rt, members):
                found = await _ask(members["file_search"], "search_files", **params)
                assert _names(found, scene.allowed) == ["ok.txt", "sub/inner.txt"]

    @pytest.mark.parametrize("include_ignored", [False, True], ids=["walk", "rglob"])
    async def test_with_empty_roots_a_search_still_drops_what_the_floor_refuses(self, tmp_path, include_ignored):
        """T7."""
        scene = _scene(tmp_path)
        params = {"path": str(scene.root), "pattern": "*.db", "include_ignored": include_ignored}
        reached = await _ask(_control("file_search"), "search_files", **params)
        assert _names(reached, scene.root) == ["vessel_data/trust.db"], "premise: the platform's floor does not hold the vessel's data directory"
        async with _fleet(scene, []) as (_rt, members):
            found = await _ask(members["file_search"], "search_files", **params)
            assert (found.success, found.result) == (True, [])

    @pytest.mark.parametrize("agent_type", TYPES)
    async def test_a_member_the_pool_adds_or_refills_applies_the_policy(self, tmp_path, agent_type):
        """T8: the add path (``pool.py:620``) and the refill path (``:533``)."""
        scene = _scene(tmp_path)
        intent, params = _call(agent_type, scene.outside)
        async with _fleet(scene, [scene.allowed]) as (runtime, members):
            pool = runtime.pools[_POOL[agent_type]]
            added = runtime.registry.get(await pool.add_agent())
            assert added is not None, "premise: the pool grew"
            assert (await _ask(added, intent, **params)).error == _OUTSIDE
            pool.target_size, before = pool.current_size, set(pool.get_agent_ids())
            members[agent_type].state = AgentState.RECYCLING
            await pool.check_health()
            (refilled,) = [runtime.registry.get(agent_id) for agent_id in pool.get_agent_ids() if agent_id not in before]
            assert (await _ask(refilled, intent, **params)).error == _OUTSIDE

    @pytest.mark.parametrize("agent_type", TYPES)
    async def test_a_member_the_refusals_degrade_is_replaced_by_one_that_still_refuses(self, tmp_path, agent_type):
        """T9: the recycle path (``pool.py:209``). A refusal is a failure outcome; a run of them degrades the member."""
        scene = _scene(tmp_path)
        intent, params = _call(agent_type, scene.outside)
        async with _fleet(scene, [scene.allowed]) as (runtime, members):
            member, pool = members[agent_type], runtime.pools[_POOL[agent_type]]
            for _attempt in range(20):
                assert (await _ask(member, intent, **params)).error == _OUTSIDE
                if member.state is AgentState.DEGRADED:
                    break
            assert member.state is AgentState.DEGRADED, "premise: a run of refusals degrades the member"
            await pool.check_health()
            replacement = runtime.registry.get(member.id)
            assert replacement is not None and replacement is not member, "premise: the pool recycled it"
            assert (await _ask(replacement, intent, **params)).error == _OUTSIDE

    @pytest.mark.parametrize("agent_type", TYPES)
    async def test_a_pool_built_members_info_reads_the_runtimes_trust_network(self, tmp_path, agent_type):
        """T10."""
        scene = _scene(tmp_path)
        assert _control(agent_type).info()["trust_score"] == format_trust(TRUST_DEFAULT), "premise: with no runtime info() reports the default"
        async with _fleet(scene, []) as (runtime, members):
            runtime.trust_network.create_with_prior(members[agent_type].id, 9.0, 1.0)
            assert members[agent_type].info()["trust_score"] == format_trust(0.9)

    @pytest.mark.parametrize("agent_type", TYPES)
    async def test_a_mesh_read_tag_reaches_the_policy_through_the_real_bus(self, tmp_path, agent_type):
        """T11: the AD-869 seam, a DM turn's tag to the pool's agent the registry names."""
        scene = _scene(tmp_path)
        async with _fleet(scene, [scene.allowed]) as (runtime, _members):
            bus, name = IntentBus(SignalManager()), _call(agent_type, scene.outside)[0]
            for member in runtime.registry.get_by_pool(_POOL[agent_type]):
                bus.subscribe(member.id, member.handle_intent, [name])

            async def turn(where, file):
                intent, params = _call(agent_type, where, file)
                tag = " ".join(f"{key}={value}" for key, value in params.items())
                seen = SimpleNamespace(intent_bus=bus, registry=runtime.registry)
                pipeline = _make_pipeline(runtime=seen, response_text=f"Looking. [MESH {intent} {tag}]", sanity_gate=DmSanityGate())
                await pipeline.step_4h_mesh_read_parse()
                return pipeline.ctx.response_text

            outside = await turn(scene.outside, "secret.txt")
            assert f"(The {name} lookup came back empty ({_OUTSIDE}).)" in outside
            assert "outside contents" not in outside and "secret.txt" not in outside
            inside = await turn(scene.allowed, "ok.txt")
            assert "came back empty" not in inside
            assert inside.endswith("\n\nok") if agent_type == "file_reader" else "ok.txt" in inside

    async def test_a_policy_that_cannot_decide_fails_closed(self, tmp_path, monkeypatch):
        """T12: the search fails whole and names nothing; the lister reports the entry it could not decide as unreadable."""
        scene = _scene(tmp_path)
        real = file_access.resolve_read_path

        def undecided(raw, **kwargs):
            if Path(raw).name in {"inner.txt", "door"}:
                raise OSError("probe")
            return real(raw, **kwargs)

        with _linked(scene.allowed / "door", scene.outside):
            async with _fleet(scene, [scene.allowed]) as (_rt, members):
                monkeypatch.setattr(file_access, "resolve_read_path", undecided)
                searched = await _ask(members["file_search"], "search_files", path=str(scene.allowed), pattern="*.txt")
                assert (searched.success, searched.result) == (False, None)
                assert (await _entries(members["directory_list"], scene.allowed))["door"] == {"name": "door", "type": "unknown", "size": 0}

    async def test_a_stored_list_read_through_the_pools_readers_fails_closed(self, tmp_path):
        """T13: a read through BF-961's ``read_stored_list`` fails outside the roots, an absent path included (the refusal comes before
        the existence check); inside the roots a file is found or missing."""
        scene = _scene(tmp_path)
        async with _fleet(scene, [scene.allowed]) as (runtime, _members):
            bus = IntentBus(SignalManager())
            for member in runtime.registry.get_by_pool("filesystem"):
                bus.subscribe(member.id, member.handle_intent, ["read_file"])
            seen = SimpleNamespace(intent_bus=bus)
            for name in ("secret.txt", "absent.json"):
                assert (await read_stored_list(seen, str(scene.outside / name))).status is ReadStatus.FAILED
            found = await read_stored_list(seen, str(scene.allowed / "ok.txt"))
            assert (found.status, found.text) == (ReadStatus.FOUND, "ok")
            assert (await read_stored_list(seen, str(scene.allowed / "absent.json"))).status is ReadStatus.MISSING
