# ProbOS — Claude Code Instructions

The repository's standing orders live in `.github/copilot-instructions.md`. Read it at the start of every session; it applies to Claude Code exactly as it does to Copilot. This file only adds what Claude Code needs on top of it: the subagent workflow and the Claude Code equivalents of Copilot-only mechanics. Where the two disagree on anything else, `.github/copilot-instructions.md` wins.

For current state (latest AD/BF, test counts, what's next) read `PROGRESS.md` and `DECISIONS.md`.

## Subagents

| Agent | File | Model | Role |
|---|---|---|---|
| `probos-architect` | `.claude/agents/probos-architect.md` | Opus 5.5 | Drafts and reviews build prompts, triages failures, makes architectural decisions, updates trackers. Does not write production code. |
| `probos-builder` | `.claude/agents/probos-builder.md` | Sonnet 5.5 | Executes one build prompt from `prompts/`: code, focused tests, section audit, tracker updates. Makes no architectural decisions. |
| `diff-reviewer` | `.claude/agents/diff-reviewer.md` | Haiku 5.5 | Adversarial pre-commit review: does the next component accept this change? Read-only. |

`.gitignore` excludes `.claude/`; these agent files are force-added. Add new agent files with `git add -f`.

## Workflow (one issue, or a batch of up to three)

1. **Architect** drafts or reviews the build prompt in `prompts/` (verify-first, grep evidence, AD/BF number via `scripts/ad_ceiling.py`).
2. **Builder** implements it section by section, running only the **focused tests** for each changed slice and its immediate consumers. No full suite.
3. **Diff Reviewer** reviews the staged or working-tree diff. Tell it what the change claims to do and name the consumer that must accept it. Repair its findings before committing; anything that would break the next run is a blocker.
4. **Commit locally** — after the pre-commit deletion check (`git diff --cached --stat`; stop on any unexpected file with more than 200 deletions). Never `git add -A`.
5. **Broad gate, once** for the issue or batch: `scripts/run_test_gate.py --label <issue-or-wave>`. It refuses an index that differs from `HEAD`, which is why step 4 comes first. The main session runs it, not the Builder. A change after the gate invalidates it — rerun.
6. **Push and verify closure** only after a green gate.

If the Builder hits a hard stop, hand its report to the Architect for triage; relay any question that needs the Captain.

## Claude Code equivalents of Copilot-only rules

**Running a subagent when the next step needs the result** (Copilot `mode: "sync"`): launch it with `run_in_background: false`. A failure then comes back as the tool result and is handled at once.

**Watchdog for background agents** (Copilot `Start-Sleep` + `read_agent`): never end a turn waiting on a background agent without a watchdog. Start a background Bash command such as `sleep 900` (`run_in_background: true`); its exit wakes the idle session. On wake, check the agent: if it failed, recover at once; if it is still running, start another `sleep`. Report a failure by when it happened, not by elapsed time since launch.

**Reviewer model independence.** The Copilot `Diff Reviewer` pins GPT models so the reviewer is a different model family from a Claude author. Claude Code subagents run Claude models only, so `diff-reviewer` runs Haiku against a Sonnet Builder: a fresh read, not a different family. For security, data-integrity or other high-risk changes, also run the Copilot `Diff Reviewer` (`.github/agents/diff-reviewer.agent.md`). Brief either reviewer with properties to verify, not attack scenarios.

## Environment

The test commands in `.github/copilot-instructions.md` and `.github/supervised-worker.json` use the Captain's Windows paths (`d:/ProbOS/.venv/Scripts/...`). In any other environment (Linux, a cloud session), use the interpreter that environment has and say which one you used. The running vessel's data lives under `%LOCALAPPDATA%\ProbOS\data` on the Captain's machine; live-system claims must come from the live system, never from the repo's `data/`.
