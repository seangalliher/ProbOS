"""AD-1219 (#1180): a tool may not advertise a library that is not a declared
dependency of the package that ships the tool.

The Captain asked why the sandbox could not install other Python libraries. The
answer turned out to be that the intent had been there since AD-1066, which
declared a ``crew-tools`` extra containing matplotlib, seaborn, reportlab and
pandas -- and that extra was never installed on the reference vessel. Meanwhile
``_ARTIFACT_LIBRARIES`` advertised all six artifact libraries unconditionally.

So three layers agreed with each other and disagreed with reality:

* the tool description offered ``a PDF (reportlab)`` and ``a chart (matplotlib)``
* the AD-1177 disposition prose promised ``.pdf`` and ``chart`` (BF-727)
* the venv could author neither -- ``pypdf`` is present but only READS PDFs

BF-726 and BF-727 each repaired a *narration*. This repairs the *cause*: the
advertised surface and the dependency set were maintained independently, so they
drifted. The tests below are the coupling.

The guard is the durable part. Installing the missing packages fixes today; a
test that fails when the advertised surface outruns the declared dependencies is
what stops the third recurrence. BF-701, AD-1177 and BF-727 were each one
enumeration going stale against reality, and each fix retired one instance
without making the class unrepeatable.
"""

from __future__ import annotations

import pathlib
import re
import tomllib

import probos.tools.code_execution_tool as cet

_PYPROJECT = pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml"

# PEP 503 name normalisation: pip treats Pillow / pillow / PILLOW as one project,
# and `_ARTIFACT_LIBRARIES` spells it "Pillow" while pyproject spells it
# "pillow". Comparing raw strings would fail on a dependency that IS declared.
_NORMALISE = re.compile(r"[-_.]+")
# A requirement string is "name", "name>=1.2", "name[extra]>=1", "name; marker".
_REQ_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _normalise(name: str) -> str:
    return _NORMALISE.sub("-", name).lower()


def _pyproject() -> dict:
    return tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))


def _declared(requirements: list[str]) -> set[str]:
    names = set()
    for req in requirements:
        match = _REQ_NAME.match(req)
        if match:
            names.add(_normalise(match.group(1)))
    return names


def _core_dependencies() -> set[str]:
    return _declared(_pyproject()["project"]["dependencies"])


def _advertised() -> tuple[tuple[str, str, str], ...]:
    """Everything the description can name, both clauses."""
    return cet._ARTIFACT_LIBRARIES + cet._ANALYSIS_LIBRARIES


# ── (1) the coupling: advertised ⊆ declared ────────────────────────────────
class TestAdvertisedImpliesDeclared:
    def test_every_advertised_library_is_a_declared_core_dependency(self) -> None:
        """The headline guard.

        Deliberately asserted against the CORE dependency list, not against
        core-plus-extras: a library reachable only through `pip install
        .[crew-tools]` is exactly the state that produced BF-726 and BF-727. An
        operator running a default install must be able to satisfy every claim
        the tool makes.
        """
        declared = _core_dependencies()
        for _module, pip_name, purpose in _advertised():
            assert _normalise(pip_name) in declared, (
                f"the sandbox description offers {purpose!r} via {pip_name!r}, "
                "which is not a declared core dependency. Either declare it or "
                "stop advertising it — the one thing that must not happen is "
                "the tool promising it and the venv lacking it, which is how "
                "the Captain came to be told the sandbox could author PDFs."
            )

    def test_the_parse_actually_found_dependencies(self) -> None:
        """Guards the guard.

        If the pyproject layout changed and `_core_dependencies()` silently
        returned an empty set, every assertion above would pass vacuously —
        a green test proving nothing, which is worse than no test.
        """
        declared = _core_dependencies()
        assert len(declared) > 20, f"parsed only {len(declared)} dependencies"
        assert "fastapi" in declared, "known core dependency missing from parse"

    def test_normalisation_is_actually_exercised(self) -> None:
        """`Pillow` vs `pillow` is the case that makes normalisation load-
        bearing. If the advertised surface ever spells every name exactly as
        pyproject does, this test fails and the normalisation can go."""
        raw = {pip for _m, pip, _p in _advertised()}
        assert any(
            pip != _normalise(pip) for pip in raw
        ), "no advertised name needs normalising — simplify the comparison"


# ── (2) the declaration is satisfied in this interpreter ───────────────────
class TestDeclaredImpliesInstalled:
    def test_every_advertised_library_actually_imports(self) -> None:
        """Declaring is not installing. The sandbox runs under `sys.executable`
        in this same venv (AD-993), so this interpreter is a sound proxy for
        what a script will be able to import."""
        for module, pip_name, purpose in _advertised():
            assert cet._importable(module), (
                f"{pip_name!r} is advertised for {purpose!r} and declared as a "
                f"dependency, but `import {module}` fails here"
            )

    def test_pdf_authoring_is_not_confused_with_pdf_reading(self) -> None:
        """The specific trap that made the original defect hard to see.

        `pypdf` was a core dependency all along, so a reader checking whether
        the venv 'had PDF support' would find one and stop. `pypdf` reads;
        nothing in the venv could author until AD-1219 added `reportlab`.
        """
        declared = _core_dependencies()
        assert "reportlab" in declared, "no PDF author declared"
        assert cet._importable("reportlab"), "no PDF author installed"


# ── (3) one declaration, not two ───────────────────────────────────────────
def test_no_advertised_library_is_declared_in_both_core_and_the_extra() -> None:
    """Two declarations of one dependency is the drift class itself.

    AD-1066 put these in `crew-tools`; AD-1219 moved them to core. Leaving them
    in both would mean two places to keep in step, which is precisely the
    condition that let the advertised surface and the installed set diverge.
    """
    extras = _pyproject()["project"]["optional-dependencies"]
    crew_tools = _declared(extras["crew-tools"])
    for _module, pip_name, _purpose in _advertised():
        assert _normalise(pip_name) not in crew_tools, (
            f"{pip_name!r} is declared in BOTH core dependencies and the "
            "crew-tools extra — one of them will go stale"
        )


# ── (4) the description reflects the broadened set ─────────────────────────
def test_the_description_names_the_analysis_libraries_it_has() -> None:
    """The Captain asked for more libraries by default. Installing them without
    telling the agent delivers half of that: an unnamed library is one the
    agent will not reach for."""

    class _Runtime:
        config = None

    desc = cet.CodeExecutionTool(runtime=_Runtime()).description
    for module, pip_name, _purpose in cet._ANALYSIS_LIBRARIES:
        if cet._importable(module):
            assert pip_name in desc, f"{pip_name!r} installed but not offered"


def test_the_analysis_clause_disappears_when_nothing_is_present() -> None:
    """Honest-degrade, same contract as the artifact clause: naming nothing
    beats naming what is absent."""

    class _Runtime:
        config = None

    original = cet._importable
    cet._importable = lambda module: False  # type: ignore[assignment]
    try:
        desc = cet.CodeExecutionTool(runtime=_Runtime()).description
    finally:
        cet._importable = original  # type: ignore[assignment]

    assert "Also available for working with data" not in desc
    for _module, pip_name, _purpose in cet._ANALYSIS_LIBRARIES:
        assert pip_name not in desc
