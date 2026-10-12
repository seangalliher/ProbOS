"""Run the Claude Code `claude-architect` agent headless and return its answer.

Why this exists (2026-10-10): the Copilot orchestrator needs an Architect it can
call without the Captain relaying messages, and the Captain wants that Architect
to be the Claude Code `claude-architect` (Opus 5.5) billed to the Claude plan.
Copilot cannot launch Claude Code subagents, and picking `claude-architect`
from the Copilot agent picker runs the file under Copilot instead. A terminal
call to the Claude Code CLI is the bridge: the orchestrator runs this script the
way it runs `run_test_gate.py`, synchronously, and reads the answer from stdout.

The design property that matters: **a run that did not happen on the Claude plan
must never look like one that did.** So the script refuses to start when the CLI
is missing, not logged in through claude.ai, or could be redirected to an API
key or another provider by the environment, and it exits non-zero whenever the
agent did not complete. A permission the agent was denied is reported, not
hidden: an answer written without the evidence it tried to gather is a weaker
answer, and the caller must know.

Usage:
    python scripts/claude_architect.py --task-file prompts/_architect_request.md
    python scripts/claude_architect.py --task "Triage this hard stop: ..." --read-only
    python scripts/claude_architect.py --resume <session_id> --task "Follow-up: ..."

`--resume` finds the session by working directory: resume from the same worktree.

Exit codes: 0 completed, 1 agent error or incomplete run, 2 preflight refused,
3 timed out, 4 completed but the agent was denied a tool call (read the answer
and the listed denials: it may rest on evidence the agent could not gather),
5 resume refused because the session's context is above --max-resume-context
(start a fresh session with a short handoff instead; nothing ran).

Token economy (measured 2026-10-11): 34 runs used about 437M cache-read tokens,
about 80% of the spend, because resumed sessions grew to 250K-670K tokens a
call. Resume only for a direct follow-up; give `--effort` per task (read-only
runs default to medium).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

AGENT = "claude-architect"
MODEL = "claude-opus-5-5"
DEFAULT_TIMEOUT_SECONDS = 3600
EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
# Consults and option ranking do not need drafting-level effort.
DEFAULT_READ_ONLY_EFFORT = "medium"
# Measured 2026-10-11: fresh sessions ran at 30K-83K tokens a call; long
# resumed sessions averaged 250K-330K and peaked at 667K, re-sending files read
# for earlier phases on every call.
DEFAULT_MAX_RESUME_CONTEXT = 250_000
_SESSION_ID = re.compile(r"[0-9A-Fa-f][0-9A-Fa-f-]{7,63}")

# Any of these redirects the CLI away from the claude.ai login: an API key or
# token bills the API account, and the provider switches leave Anthropic
# entirely. Their presence means the run could not be guaranteed to land on the
# Claude plan, so preflight refuses rather than stripping them silently.
_REDIRECTING_ENV = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    # A base URL sends model traffic to any gateway while `auth status` still
    # reports claude.ai (measured 2026-10-10: preflight accepted it).
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_PROFILE",
    "ANTHROPIC_ORGANIZATION_ID",
    "ANTHROPIC_FEDERATION_RULE_ID",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
)
# The desktop app sets the base URL to the official endpoint for its own child
# sessions; only a different endpoint redirects the traffic.
_OFFICIAL_BASE_URL = "https://api.anthropic.com"
_AUTH_STATUS_TIMEOUT_SECONDS = 60

_READ_TOOLS = ("Read", "Grep", "Glob", "WebFetch", "WebSearch")
_WRITE_TOOLS = ("Edit", "Write")
# Shell access is the Architect's evidence-gathering surface: history, issues
# and the AD ceiling. No rule pushes, merges, commits, deletes or edits GitHub
# state; those stay with the orchestrator. The run uses `--permission-mode
# dontAsk`, so a command outside these rules is denied rather than prompted
# (measured 2026-10-10: an unlisted `rm` was denied; `acceptEdits` would have
# auto-approved rm/mv/cp inside the worktree).
_BASH_RULES = (
    "Bash(git log:*)",
    "Bash(git show:*)",
    "Bash(git diff:*)",
    "Bash(git status:*)",
    "Bash(git ls-files:*)",
    "Bash(git ls-tree:*)",
    "Bash(git rev-parse:*)",
    "Bash(git blame:*)",
    "Bash(git branch --list:*)",
    "Bash(gh issue view:*)",
    "Bash(gh issue list:*)",
    "Bash(gh pr view:*)",
    "Bash(gh pr list:*)",
    "Bash(gh pr diff:*)",
    "Bash(gh search:*)",
    # A prefix rule, not an exact command: measured 2026-10-10, the agent chained
    # `cd ... && <python> scripts/ad_ceiling.py; echo ...` and an exact rule
    # denied it. Relative path only, so the ceiling reads this worktree's prompts/.
    "Bash(d:/ProbOS/.venv/Scripts/python.exe scripts/ad_ceiling.py:*)",
    "Bash(cd:*)",
    "Bash(echo:*)",
    "Bash(ls:*)",
    "Bash(head:*)",
    "Bash(tail:*)",
    "Bash(wc:*)",
    # `git grep` is deliberately absent: `-O<cmd>` / `--open-files-in-pager`
    # runs a command (verified 2026-10-10) and can hide in combined short flags
    # (`-iO...`), so no deny pattern holds; the Grep tool covers the need.
    # Read-only filters for pipelines (measured 2026-10-10: the agent piped git
    # grep into awk and sort and lost those calls). `sort` stays out: its -o
    # output file can hide in combined short flags (`-no out`), which no deny
    # pattern catches reliably. `awk` stays out: it can write from its program.
    "Bash(grep:*)",
    "Bash(cut:*)",
)
# Focused tests execute repository code (conftest, fixtures), so they are
# granted only to runs that may also edit: triage, not read-only consults.
_TEST_RULES = ("Bash(d:/ProbOS/.venv/Scripts/pytest.exe:*)",)
# `git log`/`git diff` accept `--output=<file>`, which writes a file; deny it so
# the read rules stay read-only (measured 2026-10-10: this rule denied it).
# Shell redirection needs no rule: measured 2026-10-10 under dontAsk, `echo x >
# a.txt`, `git log -1 > b.txt`, `git show ... >> c.txt` and `ls > d.txt` were all
# denied although their commands are allowed, and no file was written.
# `git grep` is denied, not merely left unlisted. Measured 2026-10-10 under
# dontAsk: the CLI auto-approves a plain `git grep` that is not in
# --allowedTools, and refuses the `-O<cmd>`, `-iO<cmd>` and `git -C . grep -O`
# forms itself. With this rule, plain `git grep` is denied, the global-option
# forms (`git -C . grep`, `git --no-pager grep`, `git -c k=v grep`) are denied
# (not auto-approved), and `git log --grep=...` still runs. The rule matches the
# literal `git grep` prefix; the global-option forms rely on the CLI not
# auto-approving them, as measured.
_DENIED_RULES = ("Bash(git *--output*)", "Bash(git grep:*)")
# Claude Code also applies an `env` block from these settings files, so a
# redirecting variable set there counts as set.
_SETTINGS_FILES = (".claude/settings.json", ".claude/settings.local.json")

Runner = Callable[..., subprocess.CompletedProcess]


class PreflightError(RuntimeError):
    """The run cannot be guaranteed to execute as claude-architect on the Claude plan."""


@dataclass
class ArchitectResult:
    """The outcome of one headless claude-architect run."""

    exit_code: int
    text: str
    session_id: str | None = None
    models: list[str] = field(default_factory=list)
    denials: list[dict] = field(default_factory=list)
    log_path: Path | None = None
    effort: str | None = None
    resumed_context: int | None = None
    resumed: bool = False


def repo_root(cwd: Path, run: Runner | None = None) -> Path:
    """Return the git top level of `cwd`, so a call from a worktree reviews that worktree."""
    run = run or subprocess.run
    completed = run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=cwd, capture_output=True, text=True, check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise PreflightError(f"{cwd} is not inside a git checkout; run from the ProbOS worktree")
    return Path(completed.stdout.strip())


def find_cli(which: Callable[[str], str | None], home: Path) -> str | None:
    """Locate the Claude Code CLI: PATH first, then the native installer's location.

    Measured 2026-10-10: the native installer put `claude.exe` in
    `~/.local/bin` without adding that directory to the user PATH, and VS Code
    (running since before the install) could not have seen it anyway, so the
    Copilot orchestrator's preflight refused with "not on PATH".
    """
    found = which("claude")
    if found:
        return found
    # On Windows only the .exe is executable; an extensionless file would fail
    # with WinError 193 instead of a clean refusal.
    for name in ("claude.exe",) if os.name == "nt" else ("claude",):
        candidate = home / ".local" / "bin" / name
        if candidate.is_file():
            return str(candidate)
    return None


def _redirecting(env: dict) -> list[str]:
    """Names in `env` that would move the run off the claude.ai login."""
    return [
        name for name in _REDIRECTING_ENV
        if env.get(name)
        and not (name == "ANTHROPIC_BASE_URL" and str(env[name]).strip().rstrip("/") == _OFFICIAL_BASE_URL)
    ]


def settings_env(root: Path, home: Path) -> dict[str, tuple[str, Path]]:
    """Collect `env` entries from the user and project settings files: name -> (value, file)."""
    found: dict[str, tuple[str, Path]] = {}
    for path in [home / ".claude" / "settings.json"] + [root / rel for rel in _SETTINGS_FILES]:
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PreflightError(f"{path} is unreadable, so its `env` block cannot be checked") from exc
        block = data.get("env") if isinstance(data, dict) else None
        if isinstance(block, dict):
            for name, value in block.items():
                found[name] = (str(value), path)
    return found


def preflight(
    root: Path,
    env: dict[str, str],
    run: Runner | None = None,
    which: Callable[[str], str | None] | None = None,
    home: Path | None = None,
) -> str:
    """Verify the environment, the CLI, the claude.ai login and the agent file; return the CLI path."""
    run = run or subprocess.run
    which = which or shutil.which
    home = home or Path.home()
    redirecting = _redirecting(env)
    if redirecting:
        raise PreflightError(
            "refusing to run: " + ", ".join(redirecting)
            + " is set, so the call could bill an API key or another provider instead of"
            " the Claude plan; unset it for this command"
        )
    from_settings = settings_env(root, home)
    redirecting = _redirecting({name: value for name, (value, _) in from_settings.items()})
    if redirecting:
        raise PreflightError(
            "refusing to run: " + ", ".join(f"{name} (in {from_settings[name][1]})" for name in redirecting)
            + " is set in a Claude Code settings `env` block, so the call could bill an API key or"
            " another provider instead of the Claude plan"
        )
    cli = find_cli(which, home)
    if not cli:
        raise PreflightError(
            f"the Claude Code CLI (`claude`) is not on PATH or in {home / '.local' / 'bin'};"
            " the Captain must install it and run `claude` then `/login`"
        )
    if not (root / ".claude" / "agents" / f"{AGENT}.md").is_file():
        raise PreflightError(f"{root}/.claude/agents/{AGENT}.md is missing in this checkout")
    try:
        completed = run(
            [cli, "auth", "status"], cwd=root, capture_output=True, text=True, check=False, env=env,
            encoding="utf-8", errors="replace", timeout=_AUTH_STATUS_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise PreflightError("`claude auth status` did not answer within 60s") from exc
    except OSError as exc:
        raise PreflightError(f"the Claude Code CLI at {cli} could not be executed: {exc}") from exc
    try:
        status = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise PreflightError(
            f"`claude auth status` returned no readable status (exit {completed.returncode})"
        ) from exc
    if not isinstance(status, dict):
        raise PreflightError("`claude auth status` returned JSON that is not an object")
    if not status.get("loggedIn") or status.get("authMethod") != "claude.ai":
        raise PreflightError(
            "the Claude Code CLI is not logged in through claude.ai"
            f" (loggedIn={status.get('loggedIn')}, authMethod={status.get('authMethod')});"
            " the Captain must run `claude` and `/login` with the Claude account"
        )
    return cli


def bridge_preamble(*, read_only: bool) -> str:
    """Rules prepended to every task, so the agent does not spend turns on calls that will be denied.

    Measured 2026-10-10: a 91-turn run lost three calls to a `for` loop and to
    pipes into awk and sort, none of which the permission rules can allow. The
    allowed-command list is generated from the grant itself, so the two cannot drift.
    """
    rules = list(_BASH_RULES) + ([] if read_only else list(_TEST_RULES))
    allowed = ", ".join(rule[len("Bash("):].removesuffix(")").removesuffix(":*") for rule in rules)
    mode = (
        # Agent-memory writes are permitted by the CLI outside the allowlist:
        # measured 2026-10-10, a read-only run (no Edit/Write granted) wrote
        # .claude/agent-memory/claude-architect/MEMORY.md and a note beside it.
        "READ-ONLY: do not edit or create any repository file. A note in your own agent memory "
        "(.claude/agent-memory/, gitignored) is allowed; say in your answer if you wrote one."
        if read_only else
        "EDITS ALLOWED inside this worktree only. Do not edit files in any other checkout."
    )
    return (
        "[Bridge constraints: you are running headless through scripts/claude_architect.py; "
        "nobody can answer questions mid-run.]\n"
        f"- {mode}\n"
        "- Shell: one simple command per Bash call. Pipes may feed only head, tail, wc, grep or cut. "
        "No for/while loops, no awk, sed, sort, xargs, no git grep, and no output redirection; "
        "these are denied.\n"
        "- Prefer the Grep, Glob and Read tools for searching and reading code.\n"
        f"- Allowed shell commands (prefixes): {allowed}.\n"
        "- Context economy: every call re-sends the whole conversation. Grep before Read, then read "
        "line ranges; do not re-read a file you have not changed"
        + ("" if read_only else "; write a prompt in one Write, then refine it with few Edits") + ".\n"
        "- If a call is denied anyway, say what evidence you could not gather.\n"
        "[End of bridge constraints. The task follows unaltered.]\n\n"
    )


def resolve_effort(*, read_only: bool, requested: str | None) -> str | None:
    """The effort to pass: the caller's choice, else medium for read-only runs, else the CLI default."""
    if requested is not None:
        if requested not in EFFORT_LEVELS:
            raise ValueError(f"effort must be one of {', '.join(EFFORT_LEVELS)}")
        return requested
    return DEFAULT_READ_ONLY_EFFORT if read_only else None


def projects_root(env: dict[str, str], home: Path | None = None, settings: dict[str, str] | None = None) -> Path:
    """Where the Claude Code CLI keeps session transcripts: the environment, then a settings `env` block."""
    base = env.get("CLAUDE_CONFIG_DIR") or (settings or {}).get("CLAUDE_CONFIG_DIR")
    return Path(base) if base else (home or Path.home()) / ".claude"


def resumed_context_tokens(session_id: str, config_dir: Path) -> int | None:
    """Context size, in tokens, of the last main-model call in a session's transcript; None if unknown.

    The next resumed call re-sends at least this much, so it is the size the
    resume guard compares against its limit.
    """
    if not _SESSION_ID.fullmatch(session_id or ""):
        return None
    found = None
    # A session normally has one transcript; if it has several, take the largest (the conservative choice).
    for transcript in sorted((config_dir / "projects").glob(f"*/{session_id}.jsonl")):
        try:
            lines = transcript.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        last = None
        for line in lines:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = record.get("message") if isinstance(record, dict) else None
            if not isinstance(message, dict) or message.get("role") != "assistant":
                continue
            if MODEL not in str(message.get("model") or ""):
                continue
            usage = message.get("usage")
            if isinstance(usage, dict):
                try:
                    last = sum(int(usage.get(key) or 0) for key in
                               ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
                except (TypeError, ValueError):
                    continue  # an unreadable usage record is skipped, not fatal
        if last is not None:
            found = last if found is None else max(found, last)
    return found


def build_command(cli: str, *, read_only: bool, resume: str | None, effort: str | None = None) -> list[str]:
    """Return the headless CLI invocation; the task itself is sent on stdin."""
    tools = list(_READ_TOOLS) + list(_BASH_RULES)
    if not read_only:
        tools += list(_WRITE_TOOLS) + list(_TEST_RULES)
    command = [
        cli, "-p",
        "--agent", AGENT,
        "--model", MODEL,
        "--output-format", "json",
        # Listed tools run without a prompt; everything else is denied, and no
        # host is waited on for an answer that will never come.
        "--permission-mode", "dontAsk",
        "--permission-prompts", "none",
        "--allowedTools", *tools,
        "--disallowedTools", *_DENIED_RULES,
    ]
    if effort:
        command += ["--effort", effort]
    if resume:
        command += ["--resume", resume]
    return command


def interpret(raw: str | None) -> ArchitectResult:
    """Turn the CLI's JSON result into an ArchitectResult; never report an unusable run as success."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        data = None
    if not isinstance(data, dict):
        return ArchitectResult(exit_code=1, text="claude-architect returned no readable JSON result:\n" + (raw or "")[-2000:])
    completed = data.get("terminal_reason") == "completed" and not data.get("is_error")
    raw_text = data.get("result")
    text = raw_text if isinstance(raw_text, str) else ""
    usage = data.get("modelUsage")
    models = sorted(usage.keys()) if isinstance(usage, dict) else []
    raw_denials = data.get("permission_denials")
    denials = [
        item if isinstance(item, dict) else {"tool_name": repr(item), "tool_input": None}
        for item in (raw_denials if isinstance(raw_denials, list) else [])
    ]
    failure = None
    if raw_text is not None and not isinstance(raw_text, str):
        failure = f"claude-architect returned a non-text result ({type(raw_text).__name__})."
    elif not completed:
        failure = (
            f"claude-architect did not complete (terminal_reason={data.get('terminal_reason')},"
            f" is_error={data.get('is_error')})."
        )
    elif not text.strip():
        failure = "claude-architect completed but returned an empty answer."
    elif raw_denials is not None and not isinstance(raw_denials, list):
        failure = "claude-architect returned permission_denials that are not a list."
    elif MODEL not in models:
        # The answer did not come from the pinned model; helper models alongside it are fine.
        failure = f"claude-architect answered without {MODEL} (models used: {', '.join(models) or 'none'})."
    if failure:
        text = failure + (f"\n{text}" if text else "")
    return ArchitectResult(
        exit_code=1 if failure else (4 if denials else 0),
        text=text,
        session_id=data.get("session_id"),
        models=models,
        denials=denials,
    )


def _write_log(root: Path, session_id: str | None, record: dict) -> Path:
    """Keep every run's raw outcome, including timeouts, so its spend can be traced."""
    log_dir = root / "logs" / "architect"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = log_dir / f"{stamp}-{session_id or 'no-session'}.json"
    path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return path


def run_architect(
    task: str,
    *,
    root: Path,
    cli: str,
    read_only: bool,
    resume: str | None,
    timeout: float,
    env: dict[str, str],
    run: Runner | None = None,
    effort: str | None = None,
    resumed_context: int | None = None,
) -> ArchitectResult:
    """Run claude-architect once, log the raw outcome under logs/architect/, and interpret it."""
    run = run or subprocess.run
    command = build_command(cli, read_only=read_only, resume=resume, effort=effort)
    preamble = bridge_preamble(read_only=read_only)
    # The log records what the agent was told, without repeating the whole text.
    told = {"read_only": read_only, "effort": effort, "resumed_context_tokens": resumed_context,
            "preamble_sha256": hashlib.sha256(preamble.encode("utf-8")).hexdigest()}
    try:
        completed = run(
            command, cwd=root, input=preamble + task, capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False, timeout=timeout, env=env,
        )
    except subprocess.TimeoutExpired as exc:
        result = ArchitectResult(exit_code=3, text=f"claude-architect timed out after {timeout:.0f}s; no answer was produced.",
                                 effort=effort, resumed_context=resumed_context, resumed=resume is not None)
        partial = exc.stdout.decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        result.log_path = _write_log(root, None, {"command": command, **told, "timeout_seconds": timeout, "stdout": partial})
        return result
    result = interpret(completed.stdout)
    result.effort, result.resumed_context, result.resumed = effort, resumed_context, resume is not None
    if result.exit_code in (0, 4) and completed.returncode != 0:
        result.exit_code = 1
        result.text = f"claude CLI exited {completed.returncode} after reporting completion.\n{result.text}"
    result.log_path = _write_log(root, result.session_id, {
        "command": command, **told, "returncode": completed.returncode,
        "stdout": completed.stdout, "stderr": (completed.stderr or "")[-4000:],
    })
    return result


def render(result: ArchitectResult) -> str:
    """Format the answer with a short header the orchestrator can quote."""
    header = [
        f"agent (requested): {AGENT}",
        f"session_id: {result.session_id or 'none'}",
        f"models: {', '.join(result.models) or 'none'}",
        f"permission_denials: {len(result.denials)}",
        f"exit: {result.exit_code}",
        f"effort: {result.effort or 'cli default'}",
    ]
    if result.resumed_context is not None:
        header.append(f"resumed_context_tokens: {result.resumed_context:,}")
    elif result.resumed:
        header.append("resumed_context_tokens: unknown (no transcript found; the resume guard was not applied)")
    for denial in result.denials:
        header.append(f"  denied: {denial.get('tool_name')} {json.dumps(denial.get('tool_input'))[:200]}")
    if result.log_path:
        header.append(f"log: {result.log_path}")
    return "\n".join(header) + "\n----\n" + result.text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--task", help="the request for the Architect")
    source.add_argument("--task-file", type=Path, help="a UTF-8 file holding the request")
    parser.add_argument("--read-only", action="store_true", help="no Edit/Write and no test runs: consults and option ranking")
    parser.add_argument("--resume", metavar="SESSION_ID",
                        help="continue an earlier session: only for a direct follow-up to its last answer")
    parser.add_argument("--effort", choices=EFFORT_LEVELS,
                        help=f"reasoning effort (default: {DEFAULT_READ_ONLY_EFFORT} for --read-only, else the CLI default)")
    parser.add_argument("--max-resume-context", type=int, default=DEFAULT_MAX_RESUME_CONTEXT,
                        help=f"refuse --resume above this many context tokens (default {DEFAULT_MAX_RESUME_CONTEXT:,})")
    parser.add_argument("--allow-large-resume", action="store_true", help="resume even above --max-resume-context")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS, help="seconds (default 3600)")
    args = parser.parse_args(argv)

    try:
        task = args.task if args.task is not None else args.task_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        print(f"claude_architect: cannot read the task file: {exc}", file=sys.stderr)
        return 2
    if not task.strip():
        print("claude_architect: the task is empty", file=sys.stderr)
        return 2
    env = dict(os.environ)
    try:
        root = repo_root(Path.cwd())
        cli = preflight(root, env)
    except PreflightError as exc:
        print(f"claude_architect: preflight refused: {exc}", file=sys.stderr)
        return 2
    effort = resolve_effort(read_only=args.read_only, requested=args.effort)
    resumed_context = None
    if args.resume:
        try:
            settings = {name: value for name, (value, _) in settings_env(root, Path.home()).items()}
        except PreflightError:
            settings = {}
        resumed_context = resumed_context_tokens(args.resume, projects_root(env, settings=settings))
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if resumed_context is not None and resumed_context > args.max_resume_context and not args.allow_large_resume:
        refused = ArchitectResult(
            exit_code=5, session_id=args.resume, effort=effort, resumed_context=resumed_context, resumed=True,
            text=(f"Resume refused: session {args.resume} already carries about {resumed_context:,} tokens of "
                  f"context (limit {args.max_resume_context:,}), and every call would re-send all of it. Start a "
                  "fresh session with a short handoff (prompt path, findings, decision needed), or pass "
                  "--allow-large-resume for a direct follow-up that truly needs the old context. Nothing ran."),
        )
        print(render(refused))
        return refused.exit_code
    result = run_architect(
        task, root=root, cli=cli, read_only=args.read_only, resume=args.resume,
        timeout=args.timeout, env=env, effort=effort, resumed_context=resumed_context,
    )
    # The answer may contain any Unicode; stdout was reconfigured above so the console code page cannot crash it.
    print(render(result))
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
