"""BF-937 (#1678): self-improvement persistence never writes promoted agent source into the source checkout.

The refusals run on the real checkout the code under test lives in (its ``.git`` entry is a premise) and on the real
``operator_checkout_refusal``; the chain case wires the pipeline with its default over ``tmp_path`` and writes through it
(the evolution store is a double: no network, no database). Every case that changes the current directory or a module
attribute restores it. The class holds the cases the unfixed tree fails; the functions before it pass on both. No BF-937
name is imported at the top: the module attribute the drift case needs is read inside it, behind a premise.
"""

from __future__ import annotations

import inspect
import logging
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import yaml

from probos.cognitive.self_improvement import AgentVersion, LocalDiskPersistence, versioning
from probos.cognitive.self_improvement.versioning import compute_source_hash

CHECKOUT = Path(versioning.__file__).resolve().parents[4]  # the checkout the code under test runs from
REPO = Path(__file__).resolve().parents[1]  # the checkout this file sits in
OLD_DEFAULT = "src/probos/agents/designed"
SOURCE = "def x():\n    pass\n"


def _premise_checkout() -> None:
    assert os.path.lexists(CHECKOUT / ".git"), f"premise: {CHECKOUT} is a git checkout (a .git directory, or a linked worktree's .git file)"
    assert (CHECKOUT / "src" / "probos").is_dir(), "premise: the checkout holds the source tree"


def _version(number: int) -> AgentVersion:
    return AgentVersion(
        version=number, parent_version=None, designed_at=0.0, designer="test",
        trust_alpha_at_promotion=1.0, trust_beta_at_promotion=1.0, source_hash=compute_source_hash(f"src_v{number}"),
    )


def _record() -> SimpleNamespace:
    return SimpleNamespace(agent_type="foo_agent", source_code=SOURCE)


def _refusal(root: str) -> str | None:
    """What building a persistence over *root* answers: the refusal text, or None when it was accepted."""
    try:
        LocalDiskPersistence(root_dir=root)
    except ValueError as exc:
        return str(exc)
    return None


async def test_a_root_outside_the_checkout_still_writes(tmp_path: Path) -> None:
    root = tmp_path / "promoted"
    persistence = LocalDiskPersistence(root_dir=str(root))

    path = await persistence.promote(_record(), _version(1))

    assert path, "the write answered its path"
    assert (root / "foo_agent_v1.py").read_text(encoding="utf-8") == SOURCE
    meta = (root / "foo_agent_v1.meta.yaml").read_text(encoding="utf-8")
    assert "agent_type: foo_agent" in meta and "version: 1" in meta


class TestPersistenceNeverWritesIntoTheSourceCheckout:
    @pytest.mark.parametrize(
        "where",
        ["relative-old-default", "absolute-old-default", "deeper-in-src", "config-dir", "the-checkout-itself"],
    )
    def test_a_root_inside_the_checkout_is_refused(self, where: str, monkeypatch: pytest.MonkeyPatch) -> None:
        _premise_checkout()
        monkeypatch.chdir(CHECKOUT)  # a relative root is read from here
        root = {
            "relative-old-default": OLD_DEFAULT,
            "absolute-old-default": str(CHECKOUT / OLD_DEFAULT),
            "deeper-in-src": str(CHECKOUT / "src" / "probos" / "cognitive" / "a_new_directory"),
            "config-dir": str(CHECKOUT / "config" / "promoted"),
            "the-checkout-itself": str(CHECKOUT),
        }[where]

        refusal = _refusal(root)

        assert refusal is not None, f"{root!r} was accepted"
        assert "inside the checkout" in refusal and "BF-937" in refusal
        assert not (CHECKOUT / OLD_DEFAULT).exists(), "premise: building the persistence wrote nothing"

    async def test_a_root_that_becomes_inside_the_checkout_writes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        assert hasattr(versioning, "_CHECKOUT_ROOT"), "premise: the module names the checkout it runs from"
        root = tmp_path / "promoted"
        persistence = LocalDiskPersistence(root_dir=str(root))  # allowed: tmp_path is no checkout
        (tmp_path / ".git").mkdir()
        # The checkout now holds the root, as a link swapped in after construction would make it.
        monkeypatch.setattr(versioning, "_CHECKOUT_ROOT", tmp_path)

        with caplog.at_level(logging.ERROR):
            path = await persistence.promote(_record(), _version(1))

        assert path == ""
        assert not root.exists(), "nothing was written, not even the directory"
        assert "BF-937" in caplog.text

    async def test_a_relative_root_is_pinned_when_the_persistence_is_built(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        here, there = tmp_path / "here", tmp_path / "there"
        here.mkdir()
        there.mkdir()
        monkeypatch.chdir(here)
        persistence = LocalDiskPersistence(root_dir="promoted")
        monkeypatch.chdir(there)

        await persistence.promote(_record(), _version(1))

        assert (here / "promoted" / "foo_agent_v1.py").is_file(), "the write followed the directory the object was built in"
        assert not (there / "promoted").exists()

    async def test_the_wiring_refuses_a_root_inside_the_checkout_before_it_opens_anything(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    ) -> None:
        from probos.config import SystemConfig
        from probos.startup.finalize import _wire_self_improvement

        _premise_checkout()
        monkeypatch.chdir(CHECKOUT)
        runtime = SimpleNamespace(data_dir=tmp_path, emit_event=None, spawner=None, codebase_index=None)
        config = SystemConfig(self_improvement={"enabled": True, "persistence_root_dir": OLD_DEFAULT})

        with patch("probos.cognitive.self_improvement.EvolutionStore") as evolution_type, caplog.at_level(logging.ERROR):
            wired = await _wire_self_improvement(runtime=runtime, config=config)

        assert wired is False
        evolution_type.assert_not_called()
        assert not hasattr(runtime, "agent_persistence"), "nothing was attached"
        assert "BF-937" in caplog.text and "inside the checkout" in caplog.text
        assert not (CHECKOUT / OLD_DEFAULT).exists()

    async def test_the_default_root_is_under_the_data_directory_and_the_pipeline_writes_there(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from probos.config import SystemConfig
        from probos.startup.finalize import _wire_self_improvement

        data_dir, cwd = tmp_path / "data", tmp_path / "cwd"
        data_dir.mkdir()
        cwd.mkdir()
        monkeypatch.chdir(cwd)  # the unfixed default is relative to here, so the unfixed tree cannot write into the repository
        runtime = SimpleNamespace(data_dir=data_dir, emit_event=None, spawner=None, codebase_index=None)
        config = SystemConfig(self_improvement={"enabled": True})
        with patch("probos.cognitive.self_improvement.EvolutionStore") as evolution_type:
            evolution_type.return_value.record_lesson = MagicMock(return_value="lesson")
            assert await _wire_self_improvement(runtime=runtime, config=config) is True, "premise: the pipeline is wired"

        path = await runtime.agent_persistence.promote(_record(), _version(1))

        promoted = data_dir / "promoted-agents"
        assert (promoted / "foo_agent_v1.py").is_file(), "the source landed under the data directory"
        assert (promoted / "foo_agent_v1.meta.yaml").is_file()
        assert Path(path) == (promoted / "foo_agent_v1.py").resolve()
        assert not (cwd / "src").exists(), "nothing landed under the old relative default"

    def test_the_shipped_default_is_not_a_source_path(self) -> None:
        from probos.config import SelfImprovementConfig

        assert SelfImprovementConfig().persistence_root_dir == ""
        shipped = yaml.safe_load((REPO / "config" / "system.yaml").read_text(encoding="utf-8"))
        assert shipped["self_improvement"]["persistence_root_dir"] == ""

    def test_the_class_carries_no_default_location(self) -> None:
        parameter = inspect.signature(LocalDiskPersistence).parameters["root_dir"]
        assert parameter.default is inspect.Parameter.empty

    @pytest.mark.skipif(os.name != "nt", reason="paths are case-insensitive on Windows only")
    def test_the_case_of_the_path_does_not_matter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _premise_checkout()
        monkeypatch.chdir(CHECKOUT)
        varied = str(CHECKOUT / OLD_DEFAULT).swapcase()
        assert varied != str(CHECKOUT / OLD_DEFAULT), "premise: the spelling differs"

        refusal = _refusal(varied)

        assert refusal is not None, f"{varied!r} was accepted"

    def test_a_link_into_the_checkout_is_refused(self, tmp_path: Path) -> None:
        _premise_checkout()
        link = tmp_path / "link"
        try:
            os.symlink(CHECKOUT / "src", link, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("this account cannot create a symbolic link")

        refusal = _refusal(str(link / "promoted"))

        assert refusal is not None, "a root reached through a link into src was accepted"
