from __future__ import annotations

import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "wave-close-precheck.ps1"


@pytest.fixture(scope="session")
def worker_id() -> str:
    """Fallback worker id when pytest-xdist plugin is not active."""
    return "master"


def _write_stub_exe(bin_dir: Path, name: str, body: str) -> None:
    script_path = bin_dir / f"{name}.ps1"
    script_path.write_text(body, encoding="utf-8")

    wrapper_path = bin_dir / f"{name}.cmd"
    wrapper_path.write_text(
        "@echo off\r\n"
        "pwsh -NoProfile -ExecutionPolicy Bypass -File \"%~dp0"
        f"{name}.ps1\" %*\r\n"
        "exit /b %errorlevel%\r\n",
        encoding="utf-8",
    )
    wrapper_path.chmod(wrapper_path.stat().st_mode | stat.S_IEXEC)


def _make_repo_tree(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    (repo / "ui" / "src" / "audio").mkdir(parents=True)
    (repo / "ui" / "src" / "store").mkdir(parents=True)
    (repo / "tests").mkdir(parents=True)

    # Required modules for check 2 static list.
    (repo / "ui" / "src" / "audio" / "voice.ts").write_text(
        "export const getServerPiperVoices = () => []\n",
        encoding="utf-8",
    )
    (repo / "ui" / "src" / "audio" / "wakeWord.ts").write_text(
        "export const startWakeWord = () => {}\n",
        encoding="utf-8",
    )
    (repo / "ui" / "src" / "audio" / "speechInput.ts").write_text(
        "export const startSpeechInput = () => {}\n",
        encoding="utf-8",
    )
    (repo / "ui" / "src" / "store" / "useStore.ts").write_text(
        "export const useStore = () => ({})\n",
        encoding="utf-8",
    )
    (repo / "ui" / "src" / "api.ts").write_text(
        "export const getApi = () => ({})\n",
        encoding="utf-8",
    )

    # One happy-path test mock per module.
    (repo / "ui" / "src" / "sample.test.tsx").write_text(
        textwrap.dedent(
            """
            vi.mock('../audio/voice', () => ({
              getServerPiperVoices: vi.fn(),
            }))
            vi.mock('../audio/wakeWord', () => ({
              startWakeWord: vi.fn(),
            }))
            vi.mock('../audio/speechInput', () => ({
              startSpeechInput: vi.fn(),
            }))
            vi.mock('../store/useStore', () => ({
              useStore: vi.fn(),
            }))
            vi.mock('../api', () => ({
              getApi: vi.fn(),
            }))
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    (repo / "ui" / "package.json").write_text("{}\n", encoding="utf-8")
    (repo / "ui" / "package-lock.json").write_text("{}\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text(
        "[tool.pytest.ini_options]\ntimeout = 180\n",
        encoding="utf-8",
    )
    (repo / "tests" / "test_sample.py").write_text(
        "def test_ok():\n    assert True\n",
        encoding="utf-8",
    )

    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()

    _write_stub_exe(
        fake_bin,
        "npm",
        "param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Args)\n"
        "$mode = $env:PRECHECK_NPM_MODE\n"
        "if ($mode -eq 'fail') { Write-Output 'npm failed'; exit 1 }\n"
        "if ($mode -eq 'lock-drift') { Write-Output 'package-lock.json would update'; exit 0 }\n"
        "Write-Output 'npm dry-run ok'; exit 0\n",
    )
    _write_stub_exe(
        fake_bin,
        "npx",
        "param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Args)\n"
        "if ($env:PRECHECK_NPX_MODE -eq 'fail') { Write-Output 'vitest failed'; exit 1 }\n"
        "Write-Output 'vitest ok'; exit 0\n",
    )
    _write_stub_exe(
        fake_bin,
        "pytest",
        "param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Args)\n"
        "Write-Output 'pytest ok'; exit 0\n",
    )

    return repo, fake_bin


def _run_precheck(repo: Path, fake_bin: Path, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PATH"] = str(fake_bin) + os.pathsep + env.get("PATH", "")
    env["WAVE_CLOSE_FAST"] = "1"
    env["PRECHECK_NPM_MODE"] = "ok"
    env["PRECHECK_NPX_MODE"] = "ok"
    if extra_env:
        env.update(extra_env)

    return subprocess.run(
        [
            "pwsh",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-RepoRoot",
            str(repo),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        env=env,
    )


@pytest.mark.skipif(not SCRIPT.exists(), reason="wave-close precheck script not present")
def test_wave_close_precheck_all_pass_exits_zero(tmp_path: Path) -> None:
    repo, fake_bin = _make_repo_tree(tmp_path)

    proc = _run_precheck(repo, fake_bin)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Summary: FAIL=0" in proc.stdout


@pytest.mark.skipif(not SCRIPT.exists(), reason="wave-close precheck script not present")
def test_wave_close_precheck_fails_when_lock_check_command_fails(tmp_path: Path) -> None:
    repo, fake_bin = _make_repo_tree(tmp_path)

    proc = _run_precheck(repo, fake_bin, {"PRECHECK_NPM_MODE": "fail"})

    assert proc.returncode == 1
    assert "Check 1: lock-file sync" in proc.stdout
    assert "FAIL:" in proc.stdout


@pytest.mark.skipif(not SCRIPT.exists(), reason="wave-close precheck script not present")
def test_wave_close_precheck_fails_when_lock_dry_run_reports_drift(tmp_path: Path) -> None:
    repo, fake_bin = _make_repo_tree(tmp_path)

    proc = _run_precheck(repo, fake_bin, {"PRECHECK_NPM_MODE": "lock-drift"})

    assert proc.returncode == 1
    assert "package-lock.json appears out of sync" in proc.stdout


@pytest.mark.skipif(not SCRIPT.exists(), reason="wave-close precheck script not present")
def test_wave_close_precheck_fails_when_mock_export_missing(tmp_path: Path) -> None:
    repo, fake_bin = _make_repo_tree(tmp_path)
    # Add a second export to create mismatch in sample.test.tsx mock object.
    (repo / "ui" / "src" / "audio" / "voice.ts").write_text(
        "export const getServerPiperVoices = () => []\n"
        "export const getServerWhisperModels = () => []\n",
        encoding="utf-8",
    )

    proc = _run_precheck(repo, fake_bin)

    assert proc.returncode == 1
    assert "missing export 'getServerWhisperModels'" in proc.stdout


@pytest.mark.skipif(not SCRIPT.exists(), reason="wave-close precheck script not present")
def test_wave_close_precheck_reports_tight_timeout_info(tmp_path: Path) -> None:
    repo, fake_bin = _make_repo_tree(tmp_path)
    (repo / "tests" / "test_timeout.py").write_text(
        "import pytest\n\n@pytest.mark.timeout(60)\ndef test_x():\n    assert True\n",
        encoding="utf-8",
    )

    proc = _run_precheck(repo, fake_bin)

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "local timeout 60 is tighter than global 180" in proc.stdout
    assert "Tight-timeout findings: 1" in proc.stdout


@pytest.mark.skipif(not SCRIPT.exists(), reason="wave-close precheck script not present")
def test_wave_close_precheck_fails_when_vitest_exit_nonzero(tmp_path: Path) -> None:
    repo, fake_bin = _make_repo_tree(tmp_path)

    proc = _run_precheck(repo, fake_bin, {"PRECHECK_NPX_MODE": "fail"})

    assert proc.returncode == 1
    assert "Check 5: vitest unhandled-error gate" in proc.stdout
    assert "vitest run exited" in proc.stdout
