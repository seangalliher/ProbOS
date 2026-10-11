from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "claude_architect.py"


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("claude_architect", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def bridge() -> ModuleType:
    return _load_module()


@pytest.fixture(autouse=True)
def _isolated_home(monkeypatch, tmp_path):
    # Preflight reads ~/.claude/settings.json; never let a test see the real one.
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))


def _checkout(tmp_path: Path, *, with_agent: bool = True) -> Path:
    root = tmp_path / "repo"
    agents = root / ".claude" / "agents"
    agents.mkdir(parents=True)
    if with_agent:
        (agents / "claude-architect.md").write_text("---\nname: claude-architect\n---\n", encoding="utf-8")
    return root


class _FakeRun:
    """Records calls and answers `claude auth status` and the agent run with canned output."""

    def __init__(self, *, auth: dict | str, agent_stdout: str = "", agent_returncode: int = 0,
                 timeout: bool = False) -> None:
        self.auth = auth
        self.agent_stdout = agent_stdout
        self.agent_returncode = agent_returncode
        self.timeout = timeout
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, command, **kwargs):
        self.calls.append((list(command), kwargs))
        if command[1:3] == ["auth", "status"]:
            out = self.auth if isinstance(self.auth, str) else json.dumps(self.auth)
            return subprocess.CompletedProcess(command, 0, stdout=out, stderr="")
        if self.timeout:
            raise subprocess.TimeoutExpired(command, kwargs.get("timeout"))
        return subprocess.CompletedProcess(command, self.agent_returncode, stdout=self.agent_stdout, stderr="")


_PLAN_LOGIN = {"loggedIn": True, "authMethod": "claude.ai"}


def _agent_json(**overrides) -> str:
    data = {
        "result": "Current highest: AD-1325",
        "is_error": False,
        "terminal_reason": "completed",
        "session_id": "sess-1",
        "modelUsage": {"claude-opus-5-5": {}},
        "permission_denials": [],
    }
    data.update(overrides)
    return json.dumps(data)


# --- preflight -------------------------------------------------------------


def test_preflight_plan_login_returns_cli_path(bridge, tmp_path):
    root = _checkout(tmp_path)
    cli = bridge.preflight(root, {}, run=_FakeRun(auth=_PLAN_LOGIN), which=lambda _: "/bin/claude")
    assert cli == "/bin/claude"


@pytest.mark.parametrize("name", [
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_PROFILE",
    "ANTHROPIC_ORGANIZATION_ID", "ANTHROPIC_FEDERATION_RULE_ID", "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
])
def test_preflight_redirecting_env_refuses(bridge, tmp_path, name):
    root = _checkout(tmp_path)
    fake = _FakeRun(auth=_PLAN_LOGIN)
    with pytest.raises(bridge.PreflightError, match=name):
        bridge.preflight(root, {name: "x"}, run=fake, which=lambda _: "/bin/claude")
    assert fake.calls == []  # refused before touching the CLI


def test_preflight_empty_redirecting_env_is_ignored(bridge, tmp_path):
    root = _checkout(tmp_path)
    assert bridge.preflight(root, {"ANTHROPIC_API_KEY": ""}, run=_FakeRun(auth=_PLAN_LOGIN),
                            which=lambda _: "/bin/claude")


@pytest.mark.parametrize("url", ["https://api.anthropic.com", "https://api.anthropic.com/"])
def test_preflight_official_base_url_is_allowed(bridge, tmp_path, url):
    assert bridge.preflight(_checkout(tmp_path), {"ANTHROPIC_BASE_URL": url}, run=_FakeRun(auth=_PLAN_LOGIN),
                            which=lambda _: "/bin/claude")


@pytest.mark.parametrize("url", ["http://127.0.0.1:9", "https://api.anthropic.com.evil.test", "https://gateway.example/anthropic"])
def test_preflight_other_base_url_refuses(bridge, tmp_path, url):
    with pytest.raises(bridge.PreflightError, match="ANTHROPIC_BASE_URL"):
        bridge.preflight(_checkout(tmp_path), {"ANTHROPIC_BASE_URL": url}, run=_FakeRun(auth=_PLAN_LOGIN),
                         which=lambda _: "/bin/claude")


def test_preflight_auth_status_decodes_with_replacement(bridge, tmp_path):
    fake = _FakeRun(auth=_PLAN_LOGIN)
    bridge.preflight(_checkout(tmp_path), {}, run=fake, which=lambda _: "/bin/claude", home=tmp_path)
    kwargs = fake.calls[0][1]
    assert kwargs["encoding"] == "utf-8" and kwargs["errors"] == "replace"


def _settings(path: Path, env: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"env": env}), encoding="utf-8")


@pytest.mark.parametrize("where", ["home", "project", "local"])
def test_preflight_redirect_in_settings_env_refuses(bridge, tmp_path, where):
    root, home = _checkout(tmp_path), tmp_path / "home"
    target = {
        "home": home / ".claude" / "settings.json",
        "project": root / ".claude" / "settings.json",
        "local": root / ".claude" / "settings.local.json",
    }[where]
    _settings(target, {"ANTHROPIC_API_KEY": "sk-test"})
    fake = _FakeRun(auth=_PLAN_LOGIN)
    with pytest.raises(bridge.PreflightError, match="settings `env` block"):
        bridge.preflight(root, {}, run=fake, which=lambda _: "/bin/claude", home=home)
    assert fake.calls == []


def test_preflight_harmless_settings_env_is_allowed(bridge, tmp_path):
    root, home = _checkout(tmp_path), tmp_path / "home"
    _settings(home / ".claude" / "settings.json", {"ANTHROPIC_BASE_URL": "https://api.anthropic.com", "FOO": "1"})
    assert bridge.preflight(root, {}, run=_FakeRun(auth=_PLAN_LOGIN), which=lambda _: "/bin/claude", home=home)


def test_preflight_unreadable_settings_refuses(bridge, tmp_path):
    root, home = _checkout(tmp_path), tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(bridge.PreflightError, match="unreadable"):
        bridge.preflight(root, {}, run=_FakeRun(auth=_PLAN_LOGIN), which=lambda _: "/bin/claude", home=home)


def test_preflight_missing_cli_refuses(bridge, tmp_path):
    with pytest.raises(bridge.PreflightError, match="not on PATH or in .*empty-home"):
        bridge.preflight(_checkout(tmp_path), {}, run=_FakeRun(auth=_PLAN_LOGIN), which=lambda _: None,
                         home=tmp_path / "empty-home")


_CLI_NAME = "claude.exe" if os.name == "nt" else "claude"


def test_preflight_finds_cli_in_local_bin_when_not_on_path(bridge, tmp_path):
    # A home distinct from the autouse fixture's, so ignoring `home` cannot pass.
    home = tmp_path / "explicit-home"
    cli = home / ".local" / "bin" / _CLI_NAME
    assert not (Path.home() / ".local" / "bin" / _CLI_NAME).exists()
    cli.parent.mkdir(parents=True)
    cli.write_bytes(b"")
    fake = _FakeRun(auth=_PLAN_LOGIN)
    found = bridge.preflight(_checkout(tmp_path), {}, run=fake, which=lambda _: None, home=home)
    assert found == str(cli)
    assert fake.calls[0][0][0] == str(cli)  # auth status ran through the found CLI


@pytest.mark.skipif(os.name != "nt", reason="Windows executes only .exe")
def test_find_cli_ignores_extensionless_file_on_windows(bridge, tmp_path):
    home = tmp_path / "explicit-home"
    (home / ".local" / "bin").mkdir(parents=True)
    (home / ".local" / "bin" / "claude").write_bytes(b"")
    assert bridge.find_cli(lambda _: None, home) is None


def test_preflight_unexecutable_cli_refuses(bridge, tmp_path):
    def run(command, **kwargs):
        raise OSError(193, "%1 is not a valid Win32 application")
    with pytest.raises(bridge.PreflightError, match="could not be executed"):
        bridge.preflight(_checkout(tmp_path), {}, run=run, which=lambda _: "/bin/claude")


def test_find_cli_prefers_path(bridge, tmp_path):
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    (home / ".local" / "bin" / _CLI_NAME).write_bytes(b"")
    assert bridge.find_cli(lambda _: "/on/path/claude", home) == "/on/path/claude"


def test_preflight_missing_agent_file_refuses(bridge, tmp_path):
    root = _checkout(tmp_path, with_agent=False)
    with pytest.raises(bridge.PreflightError, match="claude-architect.md is missing"):
        bridge.preflight(root, {}, run=_FakeRun(auth=_PLAN_LOGIN), which=lambda _: "/bin/claude")


@pytest.mark.parametrize("auth", [
    {"loggedIn": False, "authMethod": "none"},
    {"loggedIn": True, "authMethod": "api_key"},
    {"loggedIn": True},
])
def test_preflight_not_plan_login_refuses(bridge, tmp_path, auth):
    with pytest.raises(bridge.PreflightError, match="not logged in through claude.ai"):
        bridge.preflight(_checkout(tmp_path), {}, run=_FakeRun(auth=auth), which=lambda _: "/bin/claude")


def test_preflight_unreadable_auth_status_refuses(bridge, tmp_path):
    with pytest.raises(bridge.PreflightError, match="no readable status"):
        bridge.preflight(_checkout(tmp_path), {}, run=_FakeRun(auth="not json"), which=lambda _: "/bin/claude")


def test_preflight_non_object_auth_status_refuses(bridge, tmp_path):
    with pytest.raises(bridge.PreflightError, match="not an object"):
        bridge.preflight(_checkout(tmp_path), {}, run=_FakeRun(auth="null"), which=lambda _: "/bin/claude")


def test_preflight_auth_status_timeout_refuses(bridge, tmp_path):
    def run(command, **kwargs):
        assert kwargs.get("timeout"), "auth status must be bounded"
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])
    with pytest.raises(bridge.PreflightError, match="did not answer"):
        bridge.preflight(_checkout(tmp_path), {}, run=run, which=lambda _: "/bin/claude")


def test_repo_root_from_linked_worktree_subdirectory_is_worktree_top(bridge, tmp_path):
    main = tmp_path / "main"
    main.mkdir()

    def git(*arguments: str) -> None:
        subprocess.run(["git", *arguments], cwd=main, check=True, capture_output=True)

    git("init", "-q")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init")
    linked = tmp_path / "linked"
    git("worktree", "add", "-q", "--detach", str(linked))
    nested = linked / "src" / "pkg"
    nested.mkdir(parents=True)
    assert bridge.repo_root(nested).resolve() == linked.resolve()


def test_repo_root_outside_git_refuses(bridge, tmp_path):
    def run(command, **kwargs):
        return subprocess.CompletedProcess(command, 128, stdout="", stderr="fatal")
    with pytest.raises(bridge.PreflightError, match="not inside a git checkout"):
        bridge.repo_root(tmp_path, run=run)


# --- command ---------------------------------------------------------------


def _allowed(command: list[str]) -> set[str]:
    start = command.index("--allowedTools") + 1
    end = command.index("--disallowedTools")
    return set(command[start:end])


_READ_ONLY_ALLOWED = {
    "Read", "Grep", "Glob", "WebFetch", "WebSearch",
    "Bash(git log:*)", "Bash(git show:*)", "Bash(git diff:*)", "Bash(git status:*)",
    "Bash(git ls-files:*)", "Bash(git ls-tree:*)", "Bash(git rev-parse:*)",
    "Bash(git blame:*)", "Bash(git branch --list:*)",
    "Bash(gh issue view:*)", "Bash(gh issue list:*)", "Bash(gh pr view:*)", "Bash(gh pr list:*)",
    "Bash(gh pr diff:*)", "Bash(gh search:*)",
    "Bash(d:/ProbOS/.venv/Scripts/python.exe scripts/ad_ceiling.py:*)",
    "Bash(cd:*)", "Bash(echo:*)", "Bash(ls:*)", "Bash(head:*)", "Bash(tail:*)", "Bash(wc:*)",
    "Bash(grep:*)", "Bash(cut:*)",
}


def test_build_command_default_pins_agent_model_and_permissions(bridge):
    command = bridge.build_command("claude", read_only=False, resume=None)
    assert command[:2] == ["claude", "-p"]
    assert command[command.index("--agent") + 1] == "claude-architect"
    assert command[command.index("--model") + 1] == "claude-opus-5-5"
    assert command[command.index("--permission-mode") + 1] == "dontAsk"
    assert command[command.index("--permission-prompts") + 1] == "none"
    assert _allowed(command) == _READ_ONLY_ALLOWED | {
        "Edit", "Write", "Bash(d:/ProbOS/.venv/Scripts/pytest.exe:*)",
    }
    assert command[command.index("--disallowedTools") + 1:] == ["Bash(git *--output*)", "Bash(git grep:*)"]
    assert "--resume" not in command


def test_build_command_read_only_allows_exactly_the_read_set(bridge):
    command = bridge.build_command("claude", read_only=True, resume=None)
    assert _allowed(command) == _READ_ONLY_ALLOWED  # no Edit/Write, no test execution
    assert command[command.index("--permission-mode") + 1] == "dontAsk"


def test_build_command_resume_passes_session(bridge):
    command = bridge.build_command("claude", read_only=True, resume="sess-9")
    assert command[command.index("--resume") + 1] == "sess-9"
    assert "sess-9" not in _allowed(command)  # not swallowed by the variadic tool list


def test_build_command_grants_no_state_changing_shell(bridge):
    allowed = _allowed(bridge.build_command("claude", read_only=False, resume=None))
    gh_rules = {rule for rule in allowed if rule.startswith("Bash(gh ")}
    assert gh_rules == {
        "Bash(gh issue view:*)", "Bash(gh issue list:*)", "Bash(gh pr view:*)",
        "Bash(gh pr list:*)", "Bash(gh pr diff:*)", "Bash(gh search:*)",
    }
    git_verbs = {rule[len("Bash(git "):].split(":")[0] for rule in allowed if rule.startswith("Bash(git ")}
    assert git_verbs == {
        "log", "show", "diff", "status", "ls-files", "ls-tree", "rev-parse", "blame", "branch --list",
    }


# --- interpret / run -------------------------------------------------------


def test_interpret_completed_run_succeeds(bridge):
    result = bridge.interpret(_agent_json())
    assert result.exit_code == 0
    assert result.text == "Current highest: AD-1325"
    assert result.session_id == "sess-1" and result.models == ["claude-opus-5-5"]


def test_interpret_completed_with_denials_returns_4(bridge):
    denial = {"tool_name": "Bash", "tool_input": {"command": "cd d:/ProbOS && python scripts/ad_ceiling.py"}}
    result = bridge.interpret(_agent_json(permission_denials=[denial]))
    assert result.exit_code == 4
    assert result.denials == [denial]


def test_build_command_ceiling_rule_is_a_relative_prefix(bridge):
    rules = bridge.build_command("claude", read_only=True, resume=None)
    assert "Bash(d:/ProbOS/.venv/Scripts/python.exe scripts/ad_ceiling.py:*)" in rules
    assert not any("d:/ProbOS/scripts/" in rule for rule in rules)  # the worktree's own copy
    assert "Bash(cd:*)" in rules  # the measured form chains `cd` first


@pytest.mark.parametrize("overrides", [{"is_error": True}, {"terminal_reason": "api_error"}, {"terminal_reason": None}])
def test_interpret_incomplete_run_fails_and_says_why(bridge, overrides):
    result = bridge.interpret(_agent_json(**overrides))
    assert result.exit_code == 1
    assert "did not complete" in result.text


def test_interpret_empty_answer_fails(bridge):
    result = bridge.interpret(_agent_json(result="  "))
    assert result.exit_code == 1 and "empty answer" in result.text


def test_interpret_answer_without_pinned_model_fails(bridge):
    result = bridge.interpret(_agent_json(modelUsage={"claude-sonnet-5-5": {}}))
    assert result.exit_code == 1 and "without claude-opus-5-5" in result.text


def test_interpret_helper_model_alongside_pinned_model_succeeds(bridge):
    result = bridge.interpret(_agent_json(modelUsage={"claude-opus-5-5": {}, "claude-haiku-5-5": {}}))
    assert result.exit_code == 0


@pytest.mark.parametrize("overrides", [
    {"result": ["a"]},
    {"result": {"a": 1}},
    {"modelUsage": ["claude-opus-5-5"]},
    {"permission_denials": "rm x"},
])
def test_interpret_wrong_nested_types_fail_without_raising(bridge, overrides):
    result = bridge.interpret(_agent_json(**overrides))
    assert result.exit_code == 1
    bridge.render(result)  # renders without raising


def test_interpret_non_dict_denial_is_reported_not_raised(bridge):
    result = bridge.interpret(_agent_json(permission_denials=["Bash"]))
    assert result.exit_code == 4
    assert "denied: 'Bash'" in bridge.render(result)


@pytest.mark.parametrize("raw", ["", "partial {", None, "null", "[1]", '"text"'])
def test_interpret_unreadable_output_fails(bridge, raw):
    assert bridge.interpret(raw).exit_code == 1


def test_run_architect_sends_task_on_stdin_and_logs(bridge, tmp_path):
    root = _checkout(tmp_path)
    fake = _FakeRun(auth=_PLAN_LOGIN, agent_stdout=_agent_json())
    result = bridge.run_architect("Report the AD ceiling.", root=root, cli="claude", read_only=True,
                                  resume=None, timeout=60, env={}, run=fake)
    command, kwargs = fake.calls[-1]
    assert kwargs["input"] == bridge.bridge_preamble(read_only=True) + "Report the AD ceiling."
    assert kwargs["cwd"] == root
    assert kwargs["encoding"] == "utf-8" and kwargs["errors"] == "replace"
    assert "Report the AD ceiling." not in command  # not on the command line
    assert result.exit_code == 0
    assert result.log_path is not None and result.log_path.parent == root / "logs" / "architect"
    logged = json.loads(result.log_path.read_text(encoding="utf-8"))
    assert logged["returncode"] == 0 and logged["read_only"] is True
    import hashlib
    assert logged["preamble_sha256"] == hashlib.sha256(bridge.bridge_preamble(read_only=True).encode("utf-8")).hexdigest()


@pytest.mark.parametrize("read_only", [True, False])
def test_bridge_preamble_states_the_permission_rules(bridge, read_only):
    text = bridge.bridge_preamble(read_only=read_only)
    assert "one simple command per Bash call" in text
    for denied in ("for/while loops", "awk", "sed", "sort", "xargs", "redirection"):
        assert denied in text
    assert ("READ-ONLY" in text) is read_only
    assert ("pytest.exe" in text) is (not read_only)  # matches what build_command grants


@pytest.mark.parametrize("read_only", [True, False])
def test_bridge_preamble_offers_exactly_the_granted_shell(bridge, read_only):
    # The preamble's command list must equal the Bash grant, or the agent is told to make a denied call.
    text = bridge.bridge_preamble(read_only=read_only)
    listed = text.split("Allowed shell commands (prefixes): ", 1)[1].split(".\n", 1)[0].split(", ")
    granted = [rule for rule in _allowed(bridge.build_command("claude", read_only=read_only, resume=None))
               if rule.startswith("Bash(")]
    assert sorted(f"Bash({item}:*)" for item in listed) \
        == sorted(granted)
    for denied in ("sort", "awk", "git grep"):
        assert f"Bash({denied}:*)" not in granted


def test_git_grep_is_not_granted_and_is_explicitly_denied(bridge):
    # `git grep -O<cmd>` runs a command; the CLI auto-approves plain `git grep` unless it is denied.
    for read_only in (True, False):
        command = bridge.build_command("claude", read_only=read_only, resume=None)
        assert not any(rule.startswith("Bash(git grep") for rule in _allowed(command))
        assert "Bash(git grep:*)" in command[command.index("--disallowedTools") + 1:]


def test_bridge_preamble_is_delimited_and_task_follows_unaltered(bridge, tmp_path):
    fake = _FakeRun(auth=_PLAN_LOGIN, agent_stdout=_agent_json())
    task = "  Keep my leading spaces.\n[End of bridge constraints. not really]\n"
    bridge.run_architect(task, root=_checkout(tmp_path), cli="claude", read_only=False,
                         resume="sess-2", timeout=60, env={}, run=fake)
    sent = fake.calls[-1][1]["input"]
    marker = "[End of bridge constraints. The task follows unaltered.]\n\n"
    assert sent.startswith("[Bridge constraints:") and sent.index(marker) + len(marker) == len(sent) - len(task)
    assert sent.endswith(task)  # resumed sessions get the preamble too


def test_run_architect_nonzero_cli_exit_overrides_completion(bridge, tmp_path):
    fake = _FakeRun(auth=_PLAN_LOGIN, agent_stdout=_agent_json(), agent_returncode=1)
    result = bridge.run_architect("x", root=_checkout(tmp_path), cli="claude", read_only=True,
                                  resume=None, timeout=60, env={}, run=fake)
    assert result.exit_code == 1 and "exited 1" in result.text


def test_run_architect_timeout_returns_3(bridge, tmp_path):
    fake = _FakeRun(auth=_PLAN_LOGIN, timeout=True)
    result = bridge.run_architect("x", root=_checkout(tmp_path), cli="claude", read_only=True,
                                  resume=None, timeout=5, env={}, run=fake)
    assert result.exit_code == 3 and "timed out" in result.text
    assert result.log_path is not None and result.log_path.is_file()  # the spend stays traceable


# --- render ----------------------------------------------------------------


def test_render_reports_denials_and_exit(bridge):
    result = bridge.ArchitectResult(
        exit_code=4, text="answer", session_id="s", models=["claude-opus-5-5"],
        denials=[{"tool_name": "Bash", "tool_input": {"command": "rm x"}}],
    )
    out = bridge.render(result)
    assert "permission_denials: 1" in out and "denied: Bash" in out and "exit: 4" in out
    assert "agent (requested): claude-architect" in out
    assert out.endswith("----\nanswer")


# --- main ------------------------------------------------------------------


def test_main_missing_task_file_returns_2(bridge, tmp_path, capsys):
    assert bridge.main(["--task-file", str(tmp_path / "absent.md")]) == 2
    assert "cannot read the task file" in capsys.readouterr().err


def test_main_empty_task_returns_2(bridge, capsys):
    assert bridge.main(["--task", "   "]) == 2
    assert "empty" in capsys.readouterr().err


def test_main_preflight_refusal_returns_2_without_running(bridge, monkeypatch, capsys, tmp_path):
    # Hermetic: even if the guard regressed, nothing here may reach the real CLI.
    root = _checkout(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bridge, "repo_root", lambda cwd: root)
    monkeypatch.setattr(bridge.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(bridge.shutil, "which", lambda _: "/bin/claude")

    def no_run(*args, **kwargs):
        raise AssertionError("main() reached the CLI despite the preflight refusal")

    monkeypatch.setattr(bridge.subprocess, "run", no_run)
    monkeypatch.setattr(bridge, "run_architect", no_run)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert bridge.main(["--task", "hello"]) == 2
    assert "preflight refused" in capsys.readouterr().err
