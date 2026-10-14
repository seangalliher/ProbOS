# Codex Harness Absorption

*Sean Galliher, 2026-10-14*
*Source: OpenAI Codex, [github.com/openai/codex](https://github.com/openai/codex) (Apache-2.0). Read: the repository layout and the crate READMEs for `execpolicy`, `rollout-trace`, `memories`, `network-proxy`, `thread-store` and `process-hardening`, plus the module docs of `guardian-context`, `hooks` and `agent-message-board-client`.*

## Purpose

This note records which patterns from the Codex coding-agent harness ProbOS absorbs, which it rejects, and where each absorbed idea is owned. The Architect's prior-art review searches `docs/research/` before drafting a design AD, so this note is the durable link between the source and the issues below. Codex appears here only as a technical design reference.

## Absorbed

| # | Codex pattern | ProbOS gap (verified 2026-10-14) | Owner |
|---|---|---|---|
| 1 | **Process hardening** for spawned commands (`process-hardening`: dangerous variables stripped, core dumps and ptrace disabled). | `RunCommandTool` (`swe_harness/tools.py:1144`) and `ShellCommandAgent` (`agents/shell_command.py:214`, `:220`) pass no `env=`, so children inherit the runtime's whole environment. **Reproduced:** a planted variable was echoed back by `run_command`. The `run_python` sandbox already uses an allowlist (`execution/isolation.py:642`). | BF-890/#1529 |
| 2 | **Per-command execution policy** (`execpolicy`): ordered token-prefix rules with alternatives; `allow` / `prompt` / `forbidden`, strictest wins; a `justification`, naming an alternative for forbidden; program-path pinning; **`match` / `not_match` examples validated at load**. | `run_command` is governed only as a whole tool (AD-423b ladder; consensus on the intent). AD-1316's broker classifies it as a `shell` effect (`effect_broker.py:338`) but makes no per-command decision. | AD-1328/#1530. Codex's `prompt` maps to ProbOS escalation through the chain of command (Design Principle 13(c)), not to a refusal. |
| 3 | **Self-testing rule tables**: every rule carries example inputs that must or must not match, checked at startup. | No ProbOS allowlist or denylist (URL guards, MCP admission, the bridge's `_BASH_RULES`) tests itself. On 2026-10-10, the Claude CLI auto-approved `git grep` outside the bridge allowlist, which a live probe caught, not a load-time check. | AD-1328/#1530 adopts it for command rules; extend it to other rule tables as they are touched. |
| 4 | **Observe first, interpret later** (`rollout-trace`): an append-only raw event spine with payload files on the hot path (best effort, never fails the session), plus an offline deterministic reducer into a graph that separates model-visible conversation from runtime objects, with interaction edges for spawn, task, result and close. | ProbOS persists tool traces (AD-1203), lifecycle records (AD-1224) and durable events (AD-1195) but links none of them into one graph. Elastic teams (#1332) and delegation trees raise the cost. | AD-1329/#1531, a reducer over existing evidence, not a new hot-path store. |
| 5 | **Guardian review** (`guardian-context`): a separate model reviews a risky action before it runs, from a bounded context composed of registered, scope-declared sections. A contributor failure aborts, never returning partial context. The same sections can feed asynchronous scoring. | An `escalate` decision under AD-1328 would always reach the Captain, which reintroduces manual relay for routine reviewable actions. | AD-1330/#1532, an optional chain-of-command reviewer on the AD-1327/#1511 verifier tier, within authority ceilings and separation of duty. |

## Rejected or deferred

- **Enforcing network proxy** (`network-proxy`: domain allowlist, a "limited" read-only mode, MITM hooks that strip auth headers). ProbOS deliberately keeps sandbox egress soft (AD-1233, `isolation.py` `_build_env`), with AD-1221's fetch broker as the governed way out. If the threat model changes from "confused agent" to "hostile code", this is the ready design.
- **Memory pipeline** (`memories`: per-rollout extraction, then leased global consolidation over a git-baselined workspace). ProbOS's episodic memory and dream consolidation are further along. One detail worth reusing when touched: usage-ranked selection with an unused-days cut-off.
- **Thread-store split** (`thread-store`: append-only history separate from explicit metadata patches). Already consistent with ProbOS's Cloud-Ready Storage principle.
- **Managed-hooks-only mode** (`hooks` / `requirements.toml`). An enterprise administration feature, so it belongs to the commercial repository, not OSS.

## Consistent with existing ProbOS principles

- **Governance buys autonomy (DP-13).** Codex's `forbidden` + justification + alternative matches DP-13(b): prefer a governed path to a removed one. Its `prompt` becomes escalation, never a dead end, per DP-13(c).
- **Evidence over claims.** The trace reducer's rule, "runtime payloads are evidence, not proof that the model saw the same bytes", is the evidence standard applied to tracing.
- **Agents decide, services enforce (AD-1231).** The command policy and reducer are deterministic services. The Guardian-style reviewer is an agent acting within authority, not a service ranking work.
