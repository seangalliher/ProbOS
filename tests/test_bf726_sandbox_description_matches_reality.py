"""BF-726 (#____): the sandbox description must not advertise what it cannot do.

The tool told the agent it could produce ``a PDF (reportlab)`` and ``a chart
(matplotlib)``. Neither is installed by default — both live in the ``crew-tools``
extra — so an agent asked for either wrote exactly the script it had been told to
write, died on the import, and spent its remaining iterations recovering.

That is BF-719's defect one layer down. BF-719 fixed the NETWORK constraint by
stating it and naming the alternative, and it works: observed live 2026-08-07,
the agent declined to use the sandbox for fetching and offered ``http_fetch``
unprompted. But it fixed one constraint by hand and left the capability list
hand-written beside it — and an advertised capability the sandbox lacks is worse
than an unstated one, because the agent is not merely uninformed, it is misled
into the failing path.

So the list is DERIVED. These tests pin that it stays derived, because the
failure this closes is precisely a hand-maintained list drifting from the thing
it describes — the shape behind BF-701 (twelve actions advertised, eleven
admitted) and AD-1177.
"""
from __future__ import annotations

import importlib.util
from types import SimpleNamespace
from typing import Any

import pytest

from probos.config import ExecutionConfig
from probos.tools import code_execution_tool as mod
from probos.tools.code_execution_tool import CodeExecutionTool


class _Runtime:
    """The description property reads no runtime state; this proves that."""

    config = None
    artifact_store = None
    attachment_store = None


def _description() -> str:
    return CodeExecutionTool(runtime=_Runtime()).description


def _really_importable(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except Exception:
        return False


class TestTheDescriptionMatchesTheSandbox:
    def test_never_names_a_library_the_sandbox_cannot_import(self) -> None:
        """The headline. Fails before the fix on reportlab and matplotlib."""
        desc = _description()
        for module, pip_name, _purpose in mod._ARTIFACT_LIBRARIES:
            if not _really_importable(module):
                assert pip_name not in desc, (
                    f"description advertises {pip_name!r}, which the sandbox "
                    "cannot import — an agent taking this at its word writes a "
                    "script that fails on import"
                )

    def test_offers_every_library_the_sandbox_does_have(self) -> None:
        """The inverse. A present library left unnamed is a capability the
        agent will not reach for, which is the same drift pointed the other
        way — and is how python-pptx and Pillow went unoffered."""
        desc = _description()
        for module, pip_name, _purpose in mod._ARTIFACT_LIBRARIES:
            if _really_importable(module):
                assert pip_name in desc, (
                    f"{pip_name!r} is importable but not offered"
                )

    def test_tracks_a_library_appearing_and_disappearing(self) -> None:
        """Derived, not cached.

        AD-1073 can install a package mid-session. A description that kept
        denying a library the agent had just had installed would be the same
        lie in the other direction, so this must re-derive per call.
        """
        seen: list[str] = []

        def fake(module: str) -> bool:
            seen.append(module)
            return module == "docx"

        original = mod._importable
        mod._importable = fake  # type: ignore[assignment]
        try:
            only_docx = _description()
            assert "python-docx" in only_docx
            assert "openpyxl" not in only_docx

            mod._importable = lambda module: True  # type: ignore[assignment]
            everything = _description()
            for _module, pip_name, _purpose in mod._ARTIFACT_LIBRARIES:
                assert pip_name in everything
        finally:
            mod._importable = original  # type: ignore[assignment]

        assert seen, "the description did not consult importability at all"


class TestHonestDegrade:
    def test_no_document_library_still_yields_usable_guidance(self) -> None:
        """With nothing importable the tool is still useful for stdlib output.
        Naming no libraries beats naming absent ones."""
        original = mod._importable
        mod._importable = lambda module: False  # type: ignore[assignment]
        try:
            desc = _description()
        finally:
            mod._importable = original  # type: ignore[assignment]

        for _module, pip_name, _purpose in mod._ARTIFACT_LIBRARIES:
            assert pip_name not in desc
        assert "standard library" in desc.lower()
        assert "csv" in desc.lower()

    @pytest.mark.parametrize(
        "module", ["", "no_such_module_bf726", "broken.parent.child", "!!invalid"]
    )
    def test_a_hostile_module_name_reads_as_absent_not_as_an_exception(
        self, module: str
    ) -> None:
        """``find_spec`` RAISES for a missing parent and for a malformed name.
        A description property that can throw would take the whole tool offer
        down, so absence is the only answer this may give."""
        assert mod._importable(module) is False


class TestBf719IsNotRegressed:
    """The network guidance is the reason this description was last touched.
    It is load-bearing and observed working live; a rewrite must not lose it."""

    def test_still_states_the_constraint_and_names_the_alternative(self) -> None:
        # BF-781: was `"OUTBOUND NETWORK IS BLOCKED HERE" in desc`. That pinned
        # an enforcement claim the sandbox does not provide (proxy env vars to a
        # discard port, which a raw socket ignores). What BF-719 actually needs
        # is that the constraint is stated with force AND the alternative is
        # named -- both asserted here, against the new wording.
        desc = _description()
        assert "DO NOT FETCH URLS WITH run_python" in desc
        assert "http_fetch" in desc

    def test_still_explains_where_produced_files_go(self) -> None:
        desc = _description()
        assert "current working directory" in desc
        assert "downloadable artifact" in desc


class TestTheDescriptionIsCheapAndPure:
    def test_reads_no_runtime_state(self) -> None:
        """Guards against someone later reaching into the runtime here: the
        description is built during tool-offer assembly, before any request
        context exists.

        AD-1218 narrowed this from "touches nothing" to "touches nothing but
        static config", and the docstring above is why: the property being
        defended is *no request context*, and ``config`` is neither request
        context nor state — it is a Pydantic model fixed at boot and already
        read by ``invoke`` through the same ``_cfg()`` accessor. AD-1218 states
        the sandbox's wall clock, output and memory caps, and those are only
        knowable from config; hardcoding them instead would reintroduce exactly
        the drift BF-726 exists to end.

        The teeth are unchanged for the real risk — the stores and per-request
        objects — and that is asserted below rather than assumed.
        """

        class _ConfigOnly:
            """Explodes on anything except the static config."""

            config = SimpleNamespace(execution=ExecutionConfig())

            def __getattr__(self, name: str) -> Any:
                raise AssertionError(f"description touched runtime.{name}")

        assert CodeExecutionTool(runtime=_ConfigOnly()).description

    def test_the_guard_still_bites_on_request_scoped_state(self) -> None:
        """Proves the narrowing above did not defang the guard. Reaching for a
        store from the description must still fail loudly."""

        class _ConfigOnly:
            config = SimpleNamespace(execution=ExecutionConfig())

            def __getattr__(self, name: str) -> Any:
                raise AssertionError(f"description touched runtime.{name}")

        runtime = _ConfigOnly()
        with pytest.raises(AssertionError, match="artifact_store"):
            _ = runtime.artifact_store

    def test_is_stable_across_calls(self) -> None:
        assert _description() == _description()
