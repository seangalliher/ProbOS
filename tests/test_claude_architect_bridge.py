from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
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


# --- token economy (2026-10-11) -----------------------------------------------


def _transcript(config_dir: Path, session: str, contexts: list[tuple[str, int]]) -> None:
    project = config_dir / "projects" / "D--ProbOS-worktrees-x"
    project.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}}), "not json"]
    for model, ctx in contexts:
        lines.append(json.dumps({"message": {"role": "assistant", "model": model, "usage": {
            "input_tokens": 10, "cache_read_input_tokens": ctx - 110, "cache_creation_input_tokens": 100}}}))
    (project / f"{session}.jsonl").write_text("\n".join(lines), encoding="utf-8")


_SID = "558bcee4-1168-4647-81a5-ee7b7f7d1410"


def test_resumed_context_is_the_last_main_model_call(bridge, tmp_path):
    # The helper-model call comes last, so ignoring the model filter would return 900,000.
    _transcript(tmp_path, _SID, [("claude-opus-5-5", 40_000), ("claude-opus-5-5", 300_000),
                                 ("claude-haiku-5-5", 900_000)])
    assert bridge.resumed_context_tokens(_SID, tmp_path) == 300_000


def test_resumed_context_skips_unreadable_usage_values(bridge, tmp_path):
    _transcript(tmp_path, _SID, [("claude-opus-5-5", 50_000)])
    path = tmp_path / "projects" / "D--ProbOS-worktrees-x" / f"{_SID}.jsonl"
    bad = json.dumps({"message": {"role": "assistant", "model": "claude-opus-5-5",
                                  "usage": {"input_tokens": "lots", "cache_read_input_tokens": 1}}})
    path.write_text(path.read_text(encoding="utf-8") + "\n" + bad, encoding="utf-8")
    assert bridge.resumed_context_tokens(_SID, tmp_path) == 50_000


def test_resumed_context_takes_the_largest_of_duplicate_transcripts(bridge, tmp_path):
    _transcript(tmp_path, _SID, [("claude-opus-5-5", 50_000)])
    other = tmp_path / "projects" / "a-earlier-slug"
    other.mkdir(parents=True)
    (other / f"{_SID}.jsonl").write_text(json.dumps({"message": {"role": "assistant", "model": "claude-opus-5-5",
        "usage": {"input_tokens": 400_000}}}), encoding="utf-8")
    assert bridge.resumed_context_tokens(_SID, tmp_path) == 400_000


@pytest.mark.parametrize("session", ["", "not-a-session", "../../etc/passwd", "*", "558bcee4/../x"])
def test_resumed_context_rejects_non_session_ids(bridge, tmp_path, session):
    _transcript(tmp_path, _SID, [("claude-opus-5-5", 300_000)])
    assert bridge.resumed_context_tokens(session, tmp_path) is None


def test_resumed_context_unknown_session_is_none(bridge, tmp_path):
    assert bridge.resumed_context_tokens(_SID, tmp_path) is None


def test_projects_root_honours_claude_config_dir(bridge, tmp_path):
    assert bridge.projects_root({"CLAUDE_CONFIG_DIR": str(tmp_path)}) == tmp_path
    assert bridge.projects_root({}, home=tmp_path) == tmp_path / ".claude"
    assert bridge.projects_root({}, home=tmp_path, settings={"CLAUDE_CONFIG_DIR": str(tmp_path / "s")}) == tmp_path / "s"
    # the environment wins over settings, as for the CLI
    assert bridge.projects_root({"CLAUDE_CONFIG_DIR": str(tmp_path / "e")}, settings={"CLAUDE_CONFIG_DIR": "x"}) == tmp_path / "e"


@pytest.mark.parametrize("read_only, requested, expected", [
    (True, None, "medium"), (False, None, None), (True, "high", "high"), (False, "low", "low"),
])
def test_resolve_effort(bridge, read_only, requested, expected):
    assert bridge.resolve_effort(read_only=read_only, requested=requested) == expected


def test_resolve_effort_rejects_unknown_level(bridge):
    with pytest.raises(ValueError):
        bridge.resolve_effort(read_only=False, requested="turbo")


def test_build_command_passes_effort_only_when_set(bridge):
    assert bridge.build_command("claude", read_only=True, resume=None, effort="medium")[-2:] == ["--effort", "medium"]
    assert "--effort" not in bridge.build_command("claude", read_only=False, resume=None, effort=None)


def test_preamble_states_context_economy(bridge):
    edit_text = bridge.bridge_preamble(read_only=False)
    read_text = bridge.bridge_preamble(read_only=True)
    for text in (edit_text, read_text):
        assert "Grep before Read" in text and "do not re-read a file you have not changed" in text
    assert "one Write" in edit_text and "one Write" not in read_text  # read-only runs have no Write tool


def test_run_architect_logs_effort_and_resumed_context(bridge, tmp_path):
    fake = _FakeRun(auth=_PLAN_LOGIN, agent_stdout=_agent_json())
    result = bridge.run_architect("x", root=_checkout(tmp_path), cli="claude", read_only=True, resume=_SID,
                                  timeout=60, env={}, run=fake, effort="medium", resumed_context=120_000)
    command = fake.calls[-1][0]
    assert command[command.index("--effort") + 1] == "medium"
    logged = json.loads(result.log_path.read_text(encoding="utf-8"))
    assert logged["effort"] == "medium" and logged["resumed_context_tokens"] == 120_000
    out = bridge.render(result)
    assert "effort: medium" in out and "resumed_context_tokens: 120,000" in out


def _main_env(bridge, monkeypatch, tmp_path, context: int | None):
    root = _checkout(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bridge, "repo_root", lambda cwd: root)
    monkeypatch.setattr(bridge, "preflight", lambda root, env: "claude")
    monkeypatch.setattr(bridge, "session_cache_state", lambda session, config_dir: (context, None))
    calls = []

    def fake_run_architect(task, **kwargs):
        calls.append(kwargs)
        return bridge.ArchitectResult(exit_code=0, text="ok", session_id=_SID, models=["claude-opus-5-5"],
                                      effort=kwargs["effort"], resumed_context=kwargs["resumed_context"])

    monkeypatch.setattr(bridge, "run_architect", fake_run_architect)
    return calls


def test_main_refuses_large_resume_with_exit_5_and_runs_nothing(bridge, monkeypatch, tmp_path, capsys):
    calls = _main_env(bridge, monkeypatch, tmp_path, context=400_000)
    assert bridge.main(["--task", "follow up", "--resume", _SID]) == 5
    out = capsys.readouterr().out
    assert calls == [] and "Resume refused" in out and "exit: 5" in out and "400,000" in out


def test_main_large_resume_allowed_when_asked(bridge, monkeypatch, tmp_path):
    calls = _main_env(bridge, monkeypatch, tmp_path, context=400_000)
    assert bridge.main(["--task", "x", "--resume", _SID, "--allow-large-resume"]) == 0
    assert calls and calls[0]["resumed_context"] == 400_000


@pytest.mark.parametrize("context", [None, 250_000, 10_000])
def test_main_small_or_unknown_resume_runs(bridge, monkeypatch, tmp_path, context):
    calls = _main_env(bridge, monkeypatch, tmp_path, context=context)
    assert bridge.main(["--task", "x", "--resume", _SID]) == 0  # at the limit is allowed; unknown is not blocked
    assert len(calls) == 1


def test_main_guard_reads_the_real_transcript_via_claude_config_dir(bridge, monkeypatch, tmp_path, capsys):
    # End to end through main: env -> projects_root -> resumed_context_tokens -> refusal (not stubbed).
    root = _checkout(tmp_path)
    config = tmp_path / "cfg"
    _transcript(config, _SID, [("claude-opus-5-5", 400_000)])
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bridge, "repo_root", lambda cwd: root)
    monkeypatch.setattr(bridge, "preflight", lambda root, env: "claude")
    monkeypatch.setattr(bridge, "run_architect", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ran")))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    assert bridge.main(["--task", "x", "--resume", _SID]) == 5
    assert "400,000" in capsys.readouterr().out


def test_render_reports_unknown_resume_size(bridge):
    out = bridge.render(bridge.ArchitectResult(exit_code=0, text="a", models=["claude-opus-5-5"], resumed=True))
    assert "resumed_context_tokens: unknown" in out
    fresh = bridge.render(bridge.ArchitectResult(exit_code=0, text="a", models=["claude-opus-5-5"]))
    assert "resumed_context_tokens" not in fresh


def test_main_read_only_defaults_to_medium_effort(bridge, monkeypatch, tmp_path):
    calls = _main_env(bridge, monkeypatch, tmp_path, context=None)
    bridge.main(["--task", "x", "--read-only"])
    bridge.main(["--task", "x"])
    bridge.main(["--task", "x", "--read-only", "--effort", "high"])
    assert [c["effort"] for c in calls] == ["medium", None, "high"]


# --- cache-aware resume (2026-10-11) ---------------------------------------------

_NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)


def _refusal(bridge, context, minutes_ago):
    last = None if minutes_ago is None else _NOW - timedelta(minutes=minutes_ago)
    return bridge.resume_refusal(context, last, now=_NOW, max_context=250_000, stale_minutes=55, stale_context=60_000)


def test_resume_refusal_over_size_limit(bridge):
    assert "carries about 300,000 tokens" in _refusal(bridge, 300_000, 1)


def test_resume_refusal_expired_cache_on_large_session(bridge):
    why = _refusal(bridge, 200_000, 80)
    assert why and "80 minutes ago" in why and "twice the input price" in why


@pytest.mark.parametrize("context, minutes_ago", [
    (200_000, 30),    # cache still warm
    (40_000, 300),    # expired, but small: a cold rewrite costs about a fresh start
    (None, 300),      # unknown size never blocks
    (200_000, None),  # unknown age: only the size limit applies
])
def test_resume_refusal_allows(bridge, context, minutes_ago):
    assert _refusal(bridge, context, minutes_ago) is None


def test_session_cache_state_returns_last_main_model_context_and_time(bridge, tmp_path):
    project = tmp_path / "projects" / "slug"
    project.mkdir(parents=True)
    lines = [
        {"timestamp": "2026-10-12T10:00:00Z", "message": {"role": "assistant", "model": "claude-opus-5-5",
                                                       "usage": {"input_tokens": 5, "cache_read_input_tokens": 100_000}}},
        {"timestamp": "2026-10-12T11:00:00Z", "message": {"role": "assistant", "model": "claude-haiku-5-5",
                                                       "usage": {"input_tokens": 999_999}}},
    ]
    (project / f"{_SID}.jsonl").write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    context, at = bridge.session_cache_state(_SID, tmp_path)
    assert context == 100_005 and at == datetime(2026, 10, 12, 10, 0, tzinfo=timezone.utc)


def _bridge_log(root: Path, session: str, stamp: str, record: dict) -> None:
    logs = root / "logs" / "architect"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / f"{stamp}-{session}.json").write_text(json.dumps(record), encoding="utf-8")


def test_session_effort_reads_latest_log(bridge, tmp_path):
    root = _checkout(tmp_path)
    assert bridge.session_effort(root, _SID) == (False, None)
    _bridge_log(root, _SID, "20261011T000000Z", {"effort": "high"})
    _bridge_log(root, _SID, "20261012T000000Z", {"effort": "medium"})
    assert bridge.session_effort(root, _SID) == (True, "medium")


def test_session_effort_absent_key_means_cli_default(bridge, tmp_path):
    root = _checkout(tmp_path)
    _bridge_log(root, _SID, "20261010T000000Z", {"command": []})  # logged before efforts were recorded
    assert bridge.session_effort(root, _SID) == (True, None)


def test_cache_stats_parses_main_model_usage(bridge):
    raw = _agent_json(modelUsage={"claude-opus-5-5": {"cacheReadInputTokens": 900, "cacheCreationInputTokens": 50,
                                                      "inputTokens": 7}, "claude-haiku-5-5": {"inputTokens": 1}})
    assert bridge.cache_stats(raw) == {"cache_read": 900, "cache_write": 50, "input": 7}
    assert bridge.cache_stats("not json") == {} and bridge.cache_stats(_agent_json(modelUsage={})) == {}


def test_render_shows_cache_line_and_notes(bridge):
    out = bridge.render(bridge.ArchitectResult(exit_code=0, text="a", models=["claude-opus-5-5"],
                                               cache={"cache_read": 1000, "cache_write": 20, "input": 3},
                                               notes=["effort high differs"]))
    assert "cache: read 1,000 / write 20 / uncached 3 tokens" in out and "note: effort high differs" in out


def _resume_env(bridge, monkeypatch, tmp_path, *, context, minutes_ago, logged_effort):
    root = _checkout(tmp_path)
    if logged_effort is not ...:
        _bridge_log(root, _SID, "20261011T000000Z", {} if logged_effort is None else {"effort": logged_effort})
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(bridge, "repo_root", lambda cwd: root)
    monkeypatch.setattr(bridge, "preflight", lambda root, env: "claude")
    last = None if minutes_ago is None else datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    monkeypatch.setattr(bridge, "session_cache_state", lambda session, config_dir: (context, last))
    calls = []

    def fake_run_architect(task, **kwargs):
        calls.append(kwargs)
        return bridge.ArchitectResult(exit_code=0, text="ok", session_id=_SID, models=["claude-opus-5-5"],
                                      effort=kwargs["effort"], resumed=True)

    monkeypatch.setattr(bridge, "run_architect", fake_run_architect)
    return calls


def test_main_refuses_stale_large_resume(bridge, monkeypatch, tmp_path, capsys):
    calls = _resume_env(bridge, monkeypatch, tmp_path, context=200_000, minutes_ago=90, logged_effort="high")
    assert bridge.main(["--task", "x", "--resume", _SID]) == 5
    assert calls == [] and "1-hour prompt cache has expired" in capsys.readouterr().out


def test_main_resume_inherits_session_effort_even_when_read_only(bridge, monkeypatch, tmp_path):
    calls = _resume_env(bridge, monkeypatch, tmp_path, context=50_000, minutes_ago=5, logged_effort="high")
    assert bridge.main(["--task", "x", "--resume", _SID, "--read-only"]) == 0
    assert calls[0]["effort"] == "high"  # not the read-only default: a change would rewrite the cache


def test_session_cache_state_treats_naive_timestamps_as_utc(bridge, tmp_path):
    project = tmp_path / "projects" / "slug"
    project.mkdir(parents=True)
    (project / f"{_SID}.jsonl").write_text(json.dumps({"timestamp": "2026-10-12T10:00:00", "message": {
        "role": "assistant", "model": "claude-opus-5-5", "usage": {"input_tokens": 200_000}}}), encoding="utf-8")
    context, at = bridge.session_cache_state(_SID, tmp_path)
    assert at.tzinfo is not None
    # and the guard can compare it without raising
    assert "minutes ago" in bridge.resume_refusal(context, at, now=at + timedelta(minutes=90), max_context=250_000,
                                                  stale_minutes=55, stale_context=60_000)


def test_session_cache_state_age_is_latest_across_transcripts(bridge, tmp_path):
    for slug, stamp, ctx in (("a", "2026-10-12T11:50:00Z", 5_000), ("b", "2026-10-12T02:00:00Z", 100_000)):
        project = tmp_path / "projects" / slug
        project.mkdir(parents=True)
        (project / f"{_SID}.jsonl").write_text(json.dumps({"timestamp": stamp, "message": {
            "role": "assistant", "model": "claude-opus-5-5", "usage": {"input_tokens": ctx}}}), encoding="utf-8")
    context, at = bridge.session_cache_state(_SID, tmp_path)
    assert context == 100_000 and at == datetime(2026, 10, 12, 11, 50, tzinfo=timezone.utc)


def test_session_effort_rejects_unknown_logged_level(bridge, tmp_path):
    root = _checkout(tmp_path)
    _bridge_log(root, _SID, "20261011T000000Z", {"effort": "turbo"})
    assert bridge.session_effort(root, _SID) == (False, None)


def test_main_resume_with_unknown_effort_uses_cli_default_and_says_so(bridge, monkeypatch, tmp_path, capsys):
    calls = _resume_env(bridge, monkeypatch, tmp_path, context=50_000, minutes_ago=5, logged_effort=...)
    bridge.main(["--task", "x", "--resume", _SID, "--read-only"])
    assert calls[0]["effort"] is None  # not the read-only default: that could change the session's effort
    assert "the session's effort is unknown" in capsys.readouterr().out


@pytest.mark.parametrize("flag", ["--stale-resume-minutes", "--stale-resume-context", "--max-resume-context"])
@pytest.mark.parametrize("value", ["0", "-5"])
def test_main_rejects_non_positive_limits(bridge, flag, value):
    with pytest.raises(SystemExit):
        bridge.main(["--task", "x", flag, value])


def test_main_resume_of_pre_effort_session_keeps_cli_default(bridge, monkeypatch, tmp_path):
    calls = _resume_env(bridge, monkeypatch, tmp_path, context=50_000, minutes_ago=5, logged_effort=None)
    bridge.main(["--task", "x", "--resume", _SID, "--read-only"])
    assert calls[0]["effort"] is None


def test_main_explicit_effort_change_on_resume_is_noted(bridge, monkeypatch, tmp_path, capsys):
    calls = _resume_env(bridge, monkeypatch, tmp_path, context=50_000, minutes_ago=5, logged_effort="high")
    bridge.main(["--task", "x", "--resume", _SID, "--effort", "low"])
    assert calls[0]["effort"] == "low"
    assert "note: effort low differs from the session's high" in capsys.readouterr().out
