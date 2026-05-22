"""AD-798/799/800: container sandbox + workspace + egress tests."""
from __future__ import annotations

import asyncio
import os
import shutil
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from probos.security.container_sandbox import (
    CommandOutcome,
    ContainerExec,
    DockerContainerSandbox,
    InProcessContainerSandbox,
    SandboxLimits,
    WorkspaceEscapeError,
    get_container_sandbox,
    resolve_thread_workspace,
)


# ---------------- AD-799 workspace resolver ----------------


def test_resolve_workspace_none(tmp_path):
    assert resolve_thread_workspace(configured_root=tmp_path, thread_workspace=None) is None
    assert resolve_thread_workspace(configured_root=tmp_path, thread_workspace="") is None


def test_resolve_workspace_creates_subdir(tmp_path):
    p = resolve_thread_workspace(configured_root=tmp_path, thread_workspace="thread-abc")
    assert p is not None
    assert p.exists() and p.is_dir()
    assert p.parent == tmp_path.resolve()


def test_resolve_workspace_rejects_traversal(tmp_path):
    with pytest.raises(WorkspaceEscapeError):
        resolve_thread_workspace(
            configured_root=tmp_path, thread_workspace="../escape"
        )


def test_resolve_workspace_rejects_absolute_escape(tmp_path):
    other = tmp_path.parent / "elsewhere"
    other.mkdir(exist_ok=True)
    try:
        with pytest.raises(WorkspaceEscapeError):
            resolve_thread_workspace(
                configured_root=tmp_path, thread_workspace=str(other)
            )
    finally:
        shutil.rmtree(other, ignore_errors=True)


# ---------------- AD-798 in-process backend ----------------


@pytest.mark.asyncio
async def test_inprocess_runs_simple_command():
    sb = InProcessContainerSandbox()
    req = ContainerExec(
        command=[sys.executable, "-c", "print('hello')"],
        limits=SandboxLimits(wall_timeout_seconds=10),
    )
    out = await sb.run(req)
    assert out.success is True
    assert out.exit_code == 0
    assert "hello" in out.stdout
    assert out.isolated is False


@pytest.mark.asyncio
async def test_inprocess_captures_stderr_and_nonzero_exit():
    sb = InProcessContainerSandbox()
    req = ContainerExec(
        command=[sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(7)"],
        limits=SandboxLimits(wall_timeout_seconds=10),
    )
    out = await sb.run(req)
    assert out.success is False
    assert out.exit_code == 7
    assert "boom" in out.stderr


@pytest.mark.asyncio
async def test_inprocess_timeout():
    sb = InProcessContainerSandbox()
    req = ContainerExec(
        command=[sys.executable, "-c", "import time; time.sleep(10)"],
        limits=SandboxLimits(wall_timeout_seconds=0.3),
    )
    out = await sb.run(req)
    assert out.success is False
    assert "timeout" in (out.error or "").lower()


@pytest.mark.asyncio
async def test_inprocess_command_not_found():
    sb = InProcessContainerSandbox()
    out = await sb.run(ContainerExec(command=["definitely-not-a-real-cmd-xyz"]))
    assert out.success is False
    assert out.error and "not found" in out.error.lower()


# AD-800: in-process rejects egress=none rather than silently weaken
@pytest.mark.asyncio
async def test_inprocess_refuses_egress_none():
    sb = InProcessContainerSandbox()
    out = await sb.run(
        ContainerExec(command=["echo", "x"], egress_policy="none")
    )
    assert out.success is False
    assert "egress_policy='none'" in (out.error or "")


@pytest.mark.asyncio
async def test_inprocess_uses_workspace_as_cwd(tmp_path):
    sb = InProcessContainerSandbox()
    out = await sb.run(
        ContainerExec(
            command=[sys.executable, "-c", "import os; print(os.getcwd())"],
            workspace_root=tmp_path,
            limits=SandboxLimits(wall_timeout_seconds=10),
        )
    )
    assert out.success is True
    assert str(tmp_path) in out.stdout


# ---------------- AD-798 docker arg-building (no live docker required) ----------------


def test_docker_args_egress_none_uses_network_none():
    sb = DockerContainerSandbox()
    args = sb._build_args(
        ContainerExec(command=["echo", "x"], egress_policy="none")
    )
    assert "--network" in args
    idx = args.index("--network")
    assert args[idx + 1] == "none"


def test_docker_args_workspace_mount(tmp_path):
    sb = DockerContainerSandbox()
    args = sb._build_args(
        ContainerExec(command=["echo", "x"], workspace_root=tmp_path)
    )
    mount = f"{tmp_path}:/workspace:rw"
    assert "-v" in args and mount in args
    assert "-w" in args and "/workspace" in args


def test_docker_args_resource_limits():
    sb = DockerContainerSandbox()
    args = sb._build_args(
        ContainerExec(
            command=["echo"],
            limits=SandboxLimits(memory_mb=256, cpu_quota=0.5),
        )
    )
    assert "--memory" in args
    assert "256m" in args
    assert "--cpus" in args
    assert "0.5" in args


def test_docker_args_env_passthrough():
    sb = DockerContainerSandbox()
    args = sb._build_args(
        ContainerExec(command=["echo"], env={"FOO": "bar", "BAZ": "qux"})
    )
    assert "-e" in args
    assert "FOO=bar" in args
    assert "BAZ=qux" in args


def test_docker_args_egress_allowlist_attaches_named_network():
    sb = DockerContainerSandbox()
    args = sb._build_args(
        ContainerExec(command=["echo"], egress_policy="allowlist")
    )
    idx = args.index("--network")
    assert args[idx + 1] == "probos-egress-allowlist"


def test_docker_args_command_at_end():
    sb = DockerContainerSandbox()
    args = sb._build_args(ContainerExec(command=["python", "-c", "print(1)"]))
    assert args[-3:] == ["python", "-c", "print(1)"]


# ---------------- Factory ----------------


def test_factory_returns_inprocess_when_docker_missing():
    with patch("probos.security.container_sandbox.shutil.which", return_value=None):
        sb = get_container_sandbox()
    assert sb.name == "inprocess"


def test_factory_returns_docker_when_available():
    with patch("probos.security.container_sandbox.shutil.which", return_value="/usr/bin/docker"):
        sb = get_container_sandbox()
    assert sb.name == "docker"


def test_factory_prefer_docker_false_always_inprocess():
    with patch("probos.security.container_sandbox.shutil.which", return_value="/usr/bin/docker"):
        sb = get_container_sandbox(prefer_docker=False)
    assert sb.name == "inprocess"
