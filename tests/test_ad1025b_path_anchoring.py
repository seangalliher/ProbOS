"""AD-1025b (#972): sweep the remaining CWD-relative paths to the ProbOS install
root, NEVER the process CWD.

Sibling-AD of AD-1025/1025a (Piper binary/voice + rejection-cache anchoring).
These six paths each built a ``data/...`` (or ``tools/rg``) artifact relative to
the process CWD, so launching ``probos serve`` from a sibling folder silently
relocated them. The fix mirrors ``__main__.py``'s ``project_root`` and
``piper_backend._probos_root`` in-module (``Path(__file__).resolve().parents[N]``)
— it is byte-identical when launched from the repo root and correct from any CWD.

KEY FINDING (verified): ``runtime.data_dir`` is the *platform* data dir
(``%LOCALAPPDATA%\\ProbOS\\data``), NOT ``<repo>/data``. So every fix anchors to
the INSTALL ROOT, not ``runtime.data_dir`` — install-root anchoring reproduces
today's ``<repo>/data/...`` paths exactly when CWD == repo root (the
``*_byte_identical_at_repo_root`` tests below pin that contract).

BF-287: real config objects + ``SimpleNamespace`` runtimes — NO MagicMock at the
boundary; the only stubs are tiny ``lambda`` ``_install_root`` overrides and a
``shutil.which`` stub for the ripgrep PATH-first leg.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import probos.proactive as proactive
from probos.agents import code_search
from probos.cognitive import session_manager
from probos.config import (
    CaptainsLogConfig,
    DutyPolicyConfig,
    PlanOfDayConfig,
    SecurityInfraConfig,
)
from probos.duty_schedule import DutySchedule
from probos.naval import captains_log, plan_of_day
from probos.proactive import DailyBriefingScheduler
from probos.routers import security
from probos.security.audit_log import AuditLog


# ---------------------------------------------------------------------------
# Depth lock (count, don't assume — AD-458 lesson)
# ---------------------------------------------------------------------------


def test_install_root_depth_locks_all_modules() -> None:
    """Each module's ``_install_root()`` must land on the repo root that holds
    that very module under ``src/probos/...``. Locks every ``parents[N]`` count
    against future drift."""
    assert (
        code_search._install_root() / "src" / "probos" / "agents" / "code_search.py"
    ).is_file()
    assert (
        captains_log._install_root() / "src" / "probos" / "naval" / "captains_log.py"
    ).is_file()
    assert (
        plan_of_day._install_root() / "src" / "probos" / "naval" / "plan_of_day.py"
    ).is_file()
    assert (
        proactive._install_root() / "src" / "probos" / "proactive.py"
    ).is_file()
    assert (
        session_manager._install_root()
        / "src"
        / "probos"
        / "cognitive"
        / "session_manager.py"
    ).is_file()
    assert (
        security._install_root() / "src" / "probos" / "routers" / "security.py"
    ).is_file()


# ---------------------------------------------------------------------------
# PATH 1 — code_search.py ripgrep fallback (tools/rg)
# ---------------------------------------------------------------------------


def test_rg_fallback_anchors_to_install_root_not_cwd(monkeypatch, tmp_path) -> None:
    """The ``tools/rg[.exe]`` fallback resolves under the install root even when
    the CWD is an unrelated directory and ``rg`` is not on PATH."""
    root = tmp_path / "install_root"
    bindir = root / "tools"
    bindir.mkdir(parents=True)
    name = "rg.exe" if sys.platform == "win32" else "rg"
    (bindir / name).write_bytes(b"")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setattr(code_search, "_install_root", lambda: root)
    monkeypatch.setattr(code_search.shutil, "which", lambda *a, **k: None)
    monkeypatch.chdir(elsewhere)

    resolved = code_search._resolve_rg_binary()

    assert resolved == str((root / "tools" / name).resolve())


def test_rg_path_first_precedence_preserved(monkeypatch, tmp_path) -> None:
    """When ``rg`` is on PATH, ``shutil.which`` wins and the install-root
    fallback is never consulted."""
    root = tmp_path / "install_root"
    root.mkdir()

    def _boom() -> Path:  # pragma: no cover - must NOT be called
        raise AssertionError("fallback consulted despite PATH hit")

    monkeypatch.setattr(code_search, "_install_root", _boom)
    monkeypatch.setattr(code_search.shutil, "which", lambda *a, **k: "/usr/bin/rg")

    assert code_search._resolve_rg_binary() == "/usr/bin/rg"


def test_rg_byte_identical_at_repo_root(monkeypatch) -> None:
    """At the repo root the install-root candidate equals what the OLD
    CWD-relative ``Path('tools/rg')`` resolved to."""
    root = code_search._install_root()
    monkeypatch.chdir(root)
    suffix = ".exe" if sys.platform == "win32" else ""
    old_cwd_relative = (Path("tools") / f"rg{suffix}").resolve()
    new_anchored = (code_search._install_root() / "tools" / f"rg{suffix}").resolve()

    assert new_anchored == old_cwd_relative


# ---------------------------------------------------------------------------
# PATH 2 — naval/captains_log.py output_dir
# ---------------------------------------------------------------------------


def test_captains_log_output_dir_anchors_relative_to_install_root(
    monkeypatch, tmp_path
) -> None:
    root = tmp_path / "install_root"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setattr(captains_log, "_install_root", lambda: root)
    monkeypatch.chdir(elsewhere)
    cfg = CaptainsLogConfig(output_dir=Path("data/captains_log"))

    anchored = captains_log._anchor_under_root(cfg.output_dir)

    assert anchored == (root / "data" / "captains_log").resolve()


def test_captains_log_absolute_output_dir_used_as_is(monkeypatch, tmp_path) -> None:
    root = tmp_path / "install_root"
    monkeypatch.setattr(captains_log, "_install_root", lambda: root)
    abs_dir = tmp_path / "abs" / "logs"
    cfg = CaptainsLogConfig(output_dir=abs_dir)

    assert captains_log._anchor_under_root(cfg.output_dir) == abs_dir.resolve()


def test_captains_log_byte_identical_at_repo_root(monkeypatch) -> None:
    root = captains_log._install_root()
    monkeypatch.chdir(root)
    old = Path("data/captains_log").resolve()
    new = captains_log._anchor_under_root(Path("data/captains_log"))

    assert new == old


# ---------------------------------------------------------------------------
# PATH 3 — naval/plan_of_day.py output_dir
# ---------------------------------------------------------------------------


def test_plan_of_day_output_dir_anchors_relative_to_install_root(
    monkeypatch, tmp_path
) -> None:
    root = tmp_path / "install_root"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setattr(plan_of_day, "_install_root", lambda: root)
    monkeypatch.chdir(elsewhere)
    cfg = PlanOfDayConfig(output_dir=Path("data/plan_of_day"))

    anchored = plan_of_day._anchor_under_root(cfg.output_dir)

    assert anchored == (root / "data" / "plan_of_day").resolve()


def test_plan_of_day_absolute_output_dir_used_as_is(monkeypatch, tmp_path) -> None:
    root = tmp_path / "install_root"
    monkeypatch.setattr(plan_of_day, "_install_root", lambda: root)
    abs_dir = tmp_path / "abs" / "pod"
    cfg = PlanOfDayConfig(output_dir=abs_dir)

    assert plan_of_day._anchor_under_root(cfg.output_dir) == abs_dir.resolve()


def test_plan_of_day_byte_identical_at_repo_root(monkeypatch) -> None:
    root = plan_of_day._install_root()
    monkeypatch.chdir(root)
    old = Path("data/plan_of_day").resolve()
    new = plan_of_day._anchor_under_root(Path("data/plan_of_day"))

    assert new == old


# ---------------------------------------------------------------------------
# PATH 5 — proactive.py DailyBriefingScheduler briefing_state.json
# ---------------------------------------------------------------------------


def _make_duty_schedule() -> DutySchedule:
    """Real DutySchedule from default policy config (BF-287: no MagicMock)."""
    return DutySchedule(DutyPolicyConfig())


def test_briefing_state_default_anchors_to_install_root_not_cwd(
    monkeypatch, tmp_path
) -> None:
    root = tmp_path / "install_root"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setattr(proactive, "_install_root", lambda: root)
    monkeypatch.chdir(elsewhere)

    scheduler = DailyBriefingScheduler(duty_schedule=_make_duty_schedule())

    assert scheduler._state_path == root / "data" / "briefing_state.json"


def test_explicit_state_path_honored(tmp_path) -> None:
    explicit = tmp_path / "custom" / "briefing.json"
    scheduler = DailyBriefingScheduler(
        duty_schedule=_make_duty_schedule(), state_path=explicit
    )

    assert scheduler._state_path == explicit


def test_briefing_byte_identical_at_repo_root(monkeypatch) -> None:
    root = proactive._install_root()
    monkeypatch.chdir(root)
    old = (Path("data") / "briefing_state.json").resolve()
    new = (proactive._install_root() / "data" / "briefing_state.json").resolve()

    assert new == old


# ---------------------------------------------------------------------------
# PATH 6 — cognitive/session_manager.py default sessions dir
# ---------------------------------------------------------------------------


def test_default_session_dir_anchors_to_install_root_not_cwd(
    monkeypatch, tmp_path
) -> None:
    root = tmp_path / "install_root"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setattr(session_manager, "_install_root", lambda: root)
    monkeypatch.chdir(elsewhere)

    mgr = session_manager.SessionManager()

    assert mgr._dir == root / "data" / "sessions"


def test_absolute_sessions_dir_used_as_is(tmp_path) -> None:
    abs_dir = tmp_path / "abs"
    mgr = session_manager.SessionManager(abs_dir)

    assert mgr._dir == abs_dir


def test_default_resolves_at_use_time_not_import(monkeypatch, tmp_path) -> None:
    """The default is resolved on each construction (use-time), not bound at
    import — two different patched roots yield two different sessions dirs."""
    root_a = tmp_path / "root_a"
    root_b = tmp_path / "root_b"

    monkeypatch.setattr(session_manager, "_install_root", lambda: root_a)
    mgr_a = session_manager.SessionManager()
    assert mgr_a._dir == root_a / "data" / "sessions"

    monkeypatch.setattr(session_manager, "_install_root", lambda: root_b)
    mgr_b = session_manager.SessionManager()
    assert mgr_b._dir == root_b / "data" / "sessions"


def test_session_byte_identical_at_repo_root(monkeypatch) -> None:
    root = session_manager._install_root()
    monkeypatch.chdir(root)
    old = Path("data/sessions").resolve()
    new = session_manager._default_session_dir().resolve()

    assert new == old


# ---------------------------------------------------------------------------
# PATH 7 — routers/security.py assistant_audit.db
# ---------------------------------------------------------------------------


def _make_security_runtime(*, data_dir: Path | None) -> SimpleNamespace:
    """SimpleNamespace runtime with a real SecurityInfraConfig (BF-287)."""
    runtime = SimpleNamespace(
        config=SimpleNamespace(security_infra=SecurityInfraConfig()),
    )
    if data_dir is not None:
        runtime.data_dir = data_dir
    return runtime


def test_audit_log_uses_public_data_dir(tmp_path) -> None:
    """Primary leg reads the PUBLIC ``runtime.data_dir`` property (Law of
    Demeter) — the audit DB lands under that absolute dir."""
    runtime = _make_security_runtime(data_dir=tmp_path)

    log = security._get_audit_log(runtime)

    assert isinstance(log, AuditLog)
    assert log._db_path == tmp_path / "assistant_audit.db"


def test_audit_log_fallback_anchors_to_install_root(monkeypatch, tmp_path) -> None:
    """When the runtime exposes no ``data_dir``, the degenerate fallback anchors
    to the install root, not the CWD."""
    root = tmp_path / "install_root"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setattr(security, "_install_root", lambda: root)
    monkeypatch.chdir(elsewhere)
    runtime = _make_security_runtime(data_dir=None)

    log = security._get_audit_log(runtime)

    assert log._db_path == root / "data" / "assistant_audit.db"


def test_audit_log_byte_identical_at_repo_root(monkeypatch) -> None:
    root = security._install_root()
    monkeypatch.chdir(root)
    old = (Path("data") / "assistant_audit.db").resolve()
    new = (security._install_root() / "data" / "assistant_audit.db").resolve()

    assert new == old
