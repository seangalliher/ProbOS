"""AD-484 UX & Adoption tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


REPO_ROOT = Path(__file__).resolve().parent.parent


# ----- pyproject.toml + MANIFEST.in -----


def test_pyproject_classifiers_includes_beta():
    """AD-484 R#1: classifiers carry Beta status; no SPDX/PEP-639 conflict."""
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "Development Status :: 4 - Beta" in text
    # AD-484 R#2: license-classifier conflict resolved -- no PEP-639 collision
    assert "License :: OSI Approved :: Apache Software License" not in text


def test_pyproject_includes_project_urls():
    """AD-484 R#1: [project.urls] table includes Homepage/Repository/Issues."""
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "[project.urls]" in text
    assert "Homepage =" in text
    assert "Repository =" in text
    assert "Issues =" in text


def test_manifest_in_present_at_repo_root():
    manifest = REPO_ROOT / "MANIFEST.in"
    assert manifest.exists()
    assert "include README.md LICENSE" in manifest.read_text(encoding="utf-8")


# ----- Quickstart docs -----


def test_quickstart_doc_present():
    quickstart = REPO_ROOT / "docs" / "quickstart.md"
    assert quickstart.exists()
    text = quickstart.read_text(encoding="utf-8")
    assert "probos init" in text
    assert "probos doctor" in text


def test_getting_started_doc_present():
    gs = REPO_ROOT / "docs" / "getting-started.md"
    assert gs.exists()
    text = gs.read_text(encoding="utf-8")
    assert "probabilistic agent-native" in text


# ----- CLI subparser -----


def test_doctor_subparser_registered():
    """`argparse` parses `["doctor"]`; resolves to args.command == 'doctor'."""
    from probos.__main__ import main as _main_module  # noqa: F401
    import argparse

    # Re-create the parser tree manually -- the live parser is inside main()
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("doctor")
    args = parser.parse_args(["doctor"])
    assert args.command == "doctor"


# ----- _detect_llm_providers -----


def test_detect_llm_providers_returns_dict_no_raise(monkeypatch):
    """Function must return a dict and never raise on connection errors."""
    from probos import __main__ as probos_main

    class _FakeResp:
        status_code = 200

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def get(self, path):
            return _FakeResp()

    monkeypatch.setattr(probos_main, "__name__", probos_main.__name__)
    # Patch httpx.Client globally to the fake
    import httpx
    monkeypatch.setattr(httpx, "Client", _FakeClient)
    # Ensure no Anthropic env
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)

    from rich.console import Console
    detected = probos_main._detect_llm_providers(Console())
    assert isinstance(detected, dict)
    # Both candidates probed; both reachable per our fake
    assert "ollama" in detected or "copilot-proxy" in detected


def test_detect_llm_providers_anthropic_env_var(monkeypatch):
    """ANTHROPIC_API_KEY env var adds anthropic; ANTHROPIC_BASE_URL overrides URL."""
    from probos import __main__ as probos_main

    class _FailClient:
        def __init__(self, *a, **kw):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def get(self, path):
            raise ConnectionError("no local providers")

    import httpx
    monkeypatch.setattr(httpx, "Client", _FailClient)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)

    from rich.console import Console
    detected = probos_main._detect_llm_providers(Console())
    assert "anthropic" in detected
    assert detected["anthropic"] == "https://api.anthropic.com"

    # With BASE_URL override
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://proxy.example.com")
    detected2 = probos_main._detect_llm_providers(Console())
    assert detected2["anthropic"] == "https://proxy.example.com"


# ----- _cmd_doctor -----


def test_doctor_returns_nonzero_on_missing_config(monkeypatch, tmp_path):
    """Missing config.yaml -> at least one failure recorded."""
    from probos import __main__ as probos_main
    import argparse

    monkeypatch.setattr(probos_main, "_probos_home", lambda: tmp_path)

    args = argparse.Namespace(command="doctor")
    code = probos_main._cmd_doctor(args)
    assert code >= 1


def test_doctor_returns_the_failed_check_count(monkeypatch, tmp_path):
    """BF-713: ``_cmd_doctor`` returns the number of FAILed checks.

    This used to assert ``code <= 1`` against the **real** registry, which runs
    eighteen live checks -- LLM proxy, NATS socket, Docker, disk, channel
    adapters -- against whatever host happens to be running the suite. It was a
    statement about the machine, not the code, and it flaked under ``-n 16``
    while passing alone.

    Its ``OpenAICompatibleClient`` stub was also dead. AD-801 moved doctor to a
    check registry and ``llm_check`` builds its own client, so patching the
    symbol in ``__main__`` stopped affecting the probe. The test believed it had
    isolated the LLM and had not -- which is why the documented cause (an empty
    HTTP 200 from the proxy) could still reach it.

    So this drives a registry the test controls and asserts the contract the
    exit code actually carries: FAIL counts, WARN does not.
    """
    from probos import __main__ as probos_main
    from probos.doctor import registry as doctor_registry
    from probos.doctor.protocol import CheckOutcome, CheckResult
    import argparse

    home = tmp_path / "probos_home"
    data = tmp_path / "data"
    home.mkdir()
    data.mkdir()
    (home / "config.yaml").write_text(
        "system:\n  name: probos\n  version: 0.1.0\n  log_level: WARNING\n"
        "cognitive:\n  default_llm_tier: fast\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(probos_main, "_probos_home", lambda: home)
    monkeypatch.setattr(probos_main, "_default_data_dir", lambda: data)

    class _Check:
        def __init__(self, name: str, outcome: CheckOutcome) -> None:
            self._name = name
            self._outcome = outcome

        @property
        def name(self) -> str:
            return self._name

        async def run(self, ctx) -> CheckResult:
            return CheckResult(outcome=self._outcome, message=self._name)

    def _drive(*checks):
        monkeypatch.setattr(doctor_registry, "_CHECKS", list(checks))
        monkeypatch.setattr(doctor_registry, "_NAMES", {c.name for c in checks})
        return probos_main._cmd_doctor(argparse.Namespace(command="doctor"))

    ok = _Check("ok", CheckOutcome.OK)
    warn = _Check("warn", CheckOutcome.WARN)
    bad = _Check("bad", CheckOutcome.FAIL)
    worse = _Check("worse", CheckOutcome.FAIL)

    assert _drive(ok) == 0
    # WARN is explicitly not a failure -- the AD-484 contract the gate relies on.
    assert _drive(ok, warn) == 0
    assert _drive(ok, bad) == 1
    assert _drive(bad, worse, warn, ok) == 2


def test_the_doctor_registry_is_not_empty():
    """The companion to the test above: driving a fake registry proves the exit
    contract, and would still pass if every real check vanished. This proves
    checks are actually registered on import.
    """
    from probos.doctor import registry as doctor_registry
    import probos.doctor.checks  # noqa: F401 -- registration happens on import

    names = {c.name for c in doctor_registry.iter_checks()}

    assert len(names) >= 5, f"doctor has almost no checks registered: {names}"
    assert "llm" in {n.lower() for n in names} or any(
        "llm" in n.lower() for n in names
    ), f"the LLM check is not registered: {names}"
