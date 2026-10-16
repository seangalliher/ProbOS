# AD-1328 S2a -- Command execution policy wiring: one gate per runtime, judged at every place run_command executes, before broker admission, recorded, reported by `probos doctor`, with an opt-in starter policy

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-16

**Status:** Ready for build (slice S2a of AD-1328, #1530; S2b follows, below). No new AD or BF number: AD-1328 is allocated by the issue title.
**Base:** `26250c9c` plus the S1 candidate staged in this worktree (`git status`: `operations.py` modified, `execution/command_policy.py` and the three `tests/test_ad1328_s1_*.py` added). Branch `feat/ad1328-s1-20261016-26250c9c`.
**Dependencies:** S1 (`prompts/ad-1328-s1-command-policy-core.md`, its Amendments A1-A5). S1's public API is used by name only: `CommandPolicy`, `CommandEvaluation`, `CanonicalCommand`, `SelfTestReport`, `Dialect`, `ProgramResolver`, `default_dialect`, `policy_digest`, `self_test`, `CommandPolicyConfig`, `CommandDecisionName`, `COMMAND_DECISION_RANK`.
**Estimated tests:** about 70 test functions in four new files, plus deliberate edits to seven existing tests (three named below, four found at install: see "Amendments after install").

One-line summary: `ProbOSRuntime.__init__` builds one `CommandPolicyGate` from `execution.command_policy` (a self-test failure under any dialect a call site uses stops startup, naming the rule); the gate is injected into the three places a `run_command` executes -- `RunCommandTool`, `ShellCommandAgent` and the red team's re-run -- and into the AD-1316 shell adapter's preflight, so a `forbid` or `escalate` is decided before the broker reserves anything; with no rules nothing is evaluated and every path is byte-identical; refusals tell the agent each cause (rule and justification, the alternative, or the reason when no rule decided); the decision is recorded on the AD-1224 tool record and as the AD-1316 denial reason; `probos doctor` reports the policy; an opt-in starter policy ships as data. S2a refuses an `escalate` truthfully without filing; S2b files it, resumes it exactly once and adds approval reuse.

---

## Problem

S1 built the policy and nothing calls it (`tests/test_ad1328_s1_policy_evaluation.py::test_nothing_in_src_constructs_the_policy`). #1530 requires it in front of every `run_command`, before broker admission, recorded, and reported by `probos doctor`. Reading the live code for this slice found:

1. **Three places execute a `run_command`, not two.** `RunCommandTool.invoke` (`src/probos/cognitive/swe_harness/tools.py:1151`, `create_subprocess_shell`), `ShellCommandAgent._run_sync` (`src/probos/agents/shell_command.py:250` PowerShell on Windows, `:259-261` `shell=True` elsewhere), and `RedTeamAgent._verify_run_command`, which re-runs the claimed command (`src/probos/agents/red_team.py:312-316`) **before** it looks at `claimed.success` (`:336`). A policy in the first two only would be bypassed by the third: a forbidden command the shell agent refused is executed by its verifier.
2. **"Before broker admission" is not inside the tool.** With the AD-1316 broker on, `ToolExecutor.invoke` reserves the effect (`src/probos/tools/executor.py:886`, `effect_broker.py:468`) and the registry starts it (`src/probos/tools/registry.py:457`) before `tool.invoke` runs. The shell adapter refuses every shell effect preflight today (`src/probos/execution/effect_adapters.py:205`, `shell_isolation_unproven`), so with the broker on the policy would never run. The adapter's preflight (`effect_broker.py:252-258`, `:525-546`) is the seam that is before admission; precedent `_NativeFileEffectAdapter` asking its tool (`effect_adapters.py:95`).
3. **S1's `CommandPolicy` is bound to one dialect** (`CommandPolicy.__init__(config, *, dialect)`), and on Windows the call sites use two (`cmd` for `RunCommandTool`, PowerShell for the shell agent and the red team).
4. **The AD-1224 record carries no tool output** (`executor.py:1200-1206`: metadata, duration, error category; "Neither sink receives raw errors, results or parameters", `:1170-1171`), so the decision needs a narrow, validated channel and must not carry the command text.

## Solution

1. `ExecutionConfig.command_policy` (default: no rules), re-exported (O-S1-1).
2. NEW `src/probos/execution/command_gate.py`: `CommandPolicyGate` (one per runtime; one self-tested `CommandPolicy` per dialect its call sites use), `CommandGateVerdict` (runs / refusal message / causes / bounded record / AD-1316 reason code), the call-site dialect map, the program resolver, the record validator for the AD-1224 sink, and `describe_command_policy` for `doctor`.
3. `ProbOSRuntime.__init__` builds the gate; constructor injection into `RunCommandTool` (via `register_native_swe_tools`), `ShellCommandAgent` (via the shell pool's spawn kwargs, BF-890's path) and `RedTeamAgent` (`_spawn_red_team`).
4. Seams: each call site judges the command as it will run, in its dialect; the shell adapter's preflight asks `RunCommandTool.command_policy_preflight`.
5. Records: `ToolResult.metadata["command_policy"]` -> AD-1224 completion record field `command_policy`; the AD-1316 denial reason `command_policy_forbid` / `command_policy_escalate` / `command_policy_unavailable`.
6. `probos doctor` check `command_policy`; starter policy `config/command_policy/starter.yaml` (data only, opt-in by copying).

### Slicing of AD-1328 (decided 2026-10-16)

Four slices in two PRs (decided 2026-10-16, after the S1 repair rounds): PR 1 is S1 + S2a with no closing keyword; PR 2 is S2b + S2c, which closes #1530. **S1** the pure core (built); **S2a** (this) everything except the approval round trip; **S2b** escalation to the AD-1154 inbox, approved-runs-exactly-once, approval reuse; **S2c** resume and the closure tracker work (`prompts/ad-1328-s2b-command-policy-escalation.md`). Why split: the approval round trip is the riskiest and least-precedented part (AD-1154 approval deliberately does **not** replay an action, `src/probos/capability_request.py:34`, `:794-802`; `src/probos/routers/capability_requests.py:247-256`), it needs a new store (approval reuse), and it differs between the tool path (an `AgenticLoop` with an inbox) and the mesh path (a pool broadcast, `src/probos/startup/agent_fleet.py:52` pool of 3; `_MeshIntentTool.invoke` broadcasts, `src/probos/cognitive/agentic_dispatch.py:1480`). S2a is reviewable alone and leaves a coherent tree: an escalation is refused truthfully, never silently and never run.

### Decisions (S2a)

- **D1 -- Slicing.** As above. S2a milestones M1-M4 (below). Obligations to S2b: O-S2a-1..O-S2a-8 (below).
- **D2 -- Config surface.** `ExecutionConfig.command_policy: CommandPolicyConfig = Field(default_factory=CommandPolicyConfig, description=...)`, after `command_env_passthrough`. Default: no rules, so `no_policy`. `CommandPolicyConfig` and `CommandPolicyRule` are re-exported from `probos.config` and `probos.config_models` (`__all__`); `CommandDecisionName`, `COMMAND_DECISION_RANK` and `windows_program_stem` are not (they are not config models). No boolean is added, so the profiles manifest (`check_config_profiles.py` gate 3) gains no row. Regenerated: `docs/development/config-facade-baseline.yaml` (`check_config_facade.py --update-baseline`), `docs/development/config-reference.md` (`gen_config_reference.py`). Test updates: `tests/test_ad1270e2e_operations_models.py` `EXPECTED_DUMPS["ExecutionConfig"]` gains `command_policy`; S1 M1 #13 is inverted (M4).
- **D3 -- One gate per runtime, per-dialect policies (O-S1-2, refined).** `CommandPolicyGate(config, *, platform=None, which=shutil.which)` builds `CommandPolicy(config, dialect=d)` for each `d` in `serving_dialects(platform)` -- `("cmd", "powershell")` on `win32`, `("posix",)` elsewhere -- so every rule's examples must hold under every dialect a call site uses there (D5 of S1 applied per site). With no rules it builds no `CommandPolicy` and computes no digest, because S1's digest imports `probos.federation.ard.jcs`, which runs the federation package's `__init__` (`src/probos/federation/__init__.py:3-9`, NATS transport included): a runtime without a policy must not gain that import. One config, one digest, one gate; "exactly one `CommandPolicy`" (O-S1-2) becomes "exactly one gate", because S1's frozen `CommandPolicy` is single-dialect. Built in `ProbOSRuntime.__init__` right after the config and data directory are set, so a wrong example raises `CommandPolicySelfTestError` (naming dialect, rule, example) before any I/O and stops startup. Held as `runtime.command_policy_gate`. Only that line constructs a gate (pinned by an AST scan, M4).
- **D4 -- Injection (Law of Demeter, constructor injection).** `RunCommandTool(..., command_policy_gate=)` through `register_native_swe_tools(..., command_policy_gate=)` from `_wire_native_swe_harness` (`src/probos/startup/finalize.py:1776`). `ShellCommandAgent` pops `command_policy_gate` from its kwargs; `ProbOSRuntime.create_pool` adds it to a shell pool's spawn kwargs beside BF-890's names (the pool keeps them, so respawned and added members get it; a caller's own value wins). `RedTeamAgent` pops it; `_spawn_red_team` passes it. `create_pool` and `_spawn_red_team` read `getattr(self, "command_policy_gate", None)` because the BF-890 tests call both on runtime doubles without the attribute (`tests/test_bf890_shell_agent_env.py:463-492`, `:387`); same precedent as `getattr(self, "onboarding", None)` at `runtime.py:2543`. A real runtime always has the gate (D3), so the `None` branch is test-double-only and means "no policy".
- **D5 -- The seams.**
  - *Dialect* (O-S1-3): `call_site_dialect("run_command_tool")` = `default_dialect()`; `call_site_dialect("shell_command_agent")` = `"powershell"` on `win32` else `"posix"`, used by both `ShellCommandAgent` and the red team (`red_team.py:416`, `:423` start the same shells). The gate takes `platform` so tests choose dialects without touching the host.
  - *As it will run* (O-S1-3): `ShellCommandAgent._run_command` judges after `_strip_ps_wrapper` and `_rewrite_python_interpreter`; the red team judges `params["command"]`, the text it re-runs unmodified; `RunCommandTool` judges `str(command)`, the text it spawns.
  - *Resolver* (O-S1-5): `make_program_resolver(dialect, search_path, cwd, which)` -- `which(name, path=...)` over the child's `PATH` from `build_command_env(self._command_env_passthrough)` (the owner that builds the child's environment), with `cwd` (or this process's directory, which the child inherits) first for `cmd`, because `cmd.exe` searches its working directory first. Memoised per judgement, so `evaluate` and `canonical` see one answer per name. Symlinks are not followed: a pin names the path PATH yields. Every miss or odd answer is `None`, which a pinned `allow` refuses (fail closed). The child's environment is built a second time for the resolver rather than threaded into the launch: the launch lines stay byte-identical, which keeps the BF-892 launch guard's inventory (`tests/test_bf892_spawn_env_guard.py:82-108`) and BF-893's 3-argument `_run_sync` stand-in (`tests/test_bf893_process_tree.py:1015-1018`) valid; both calls use the same owner and inputs.
  - *No policy* (O-S1-4): each site returns before any extra work when the gate is `None` or `not gate.configured`; `judge` itself returns `NO_POLICY` before parsing or resolving. Golden tests (M2, M3) pin the spawn call, the result and "nothing else was called".
  - *Refusal shape per consumer.* `RunCommandTool`: `ToolResult(error=message, metadata={"command_policy": record})`, the error-shaped refusal `AgenticLoop` already turns into an is-error tool result. `ShellCommandAgent`: `{"success": False, "error": message}`, the shape `decide()`'s not-found refusal already uses (`shell_command.py:119-125`), so `handle_intent`, `_MeshIntentTool.invoke` (`agentic_dispatch.py:1492-1496`) and the red team accept it unchanged. Red team: a `VerificationResult` without re-running: verified exactly when the agent claimed failure. Broker preflight: the reason code (`EffectDispatchResult` has no result, so `ToolExecutor.invoke` reports the code as the error, `executor.py:892-895`).
  - *Judgement errors fail closed*: the command is not run (tool: the existing `except Exception` returns `run_command failed: ...`; shell agent: `COMMAND_POLICY_UNAVAILABLE_MESSAGE`; red team: unverified, not re-run; preflight: `command_policy_unavailable`).
- **D6 -- Escalate in S2a.** `escalate` is refused with a message naming every cause and saying, truthfully, that no approval was requested from here. S2b replaces the frame with the AD-1154 filing (O-S2a-1). Never silent, never run.
- **D7 -- Causes and messages (O-S1-6, O-S1-11).** A verdict's causes are: each governing rule match (rule, justification, alternative); the whole-line unparseable reason, if any; each segment whose decision equals the command's and whose basis is `unmatched` (names the program and `unmatched_decision`) or `unparseable` (its reason). So an `escalate` from an unmatched or unparseable segment carries its reason although `governing` is empty. The agent message shows up to five causes, then `(and N more)`. The fixed frames are checked against `probos.cognitive.decomposer._CAPABILITY_GAP_RE` (they must not read as a capability gap, AD-1154 DD-2); the S1 reason text inside them is quoted as is.
- **D8 -- Records (O-S1-7).** `CommandGateVerdict.record` (schema `probos.command_policy.record/v1`): call site, decision, dialect, policy digest, canonical key and kind, matched rule names (at most 8, then a count), causes as `{kind, segment, rule}` (at most 8, then a count). **No command text, no justification, no reason text**: the AD-1224 sinks receive no raw parameters (`executor.py:1170-1171`), and the canonical key identifies the command. Rule names come from operator config. The record is at most 2,048 JSON characters (the AD-1224 record budget is 4,096 bytes, `executor.py:52`). Written: (a) on `RunCommandTool`'s result metadata when evaluated (allow, refusal and timeout), and the non-strict AD-1224 completion record copies it after re-validation (`command_policy_record_of`), so a record without a policy is unchanged; (b) as the AD-1316 denial reason when the broker is on (the only free field on an effect record; rule names stay in the gate's INFO log line, which carries no command text). The strict AD-1224 projection is not extended: under the broker `RunCommandTool` is always denied preflight, so it never produces a strict tool record. The mesh path's durable record is O-S2a-4; S2a logs it. No second source of truth: the gate computes the record once, the tool carries it, the sink copies it.
- **D9 -- `probos doctor` and the starter policy.** A registered check `command_policy` (after `sandbox`): no rules -> OK; passing -> OK with rule count, dialects, examples checked and the full digest; failing -> FAIL naming each failing rule and example per dialect (first three) with remediation; an invalid value -> FAIL; config not loaded -> WARN. It calls `describe_command_policy`, which never raises (O-S1-2). The starter policy is data, `config/command_policy/starter.yaml`: not loaded unless the operator copies it under `execution:`; a deny-list (`unmatched_decision: allow`) that forbids shell downloads (`curl`, `wget`, `Invoke-WebRequest`, `iwr`, `Invoke-RestMethod`, `irm`; alternative `http_fetch`) and escalates `git push`; its examples are tested under `posix`, `cmd` and `powershell` (O-S1-10). No boolean flag, no profile (`config/profiles/` is a closed set, `scripts/check_config_profiles.py:6`).
- **D10 -- Tests, mutation, milestones.** Below. All new tests pass `platform=`/dialects explicitly or patch the spawn; none starts a real shell.

### Obligations carried to S2b

- **O-S2a-1** Route `escalate` to the AD-1154 approval inbox from both paths, carrying the causes (D7), and replace `_ESCALATE_FRAME`; decide what the agent sees while pending, after approval and after denial.
- **O-S2a-2** Approved command runs exactly once. AD-1154 approval of an `action` does not replay it (`capability_request.py:34`, `:794-802`; `routers/capability_requests.py:247-256`); design the resume (expected: the approval issues a scoped grant the re-issued call consumes), cross the whole chain in one test (file -> approve -> re-issue -> runs once), and cover the `p0-manifest.yaml` seam "approval -> fulfilment -> resumed turn".
- **O-S2a-3** Approval reuse (O-S1-8): a new store (`scripts/check_store_registry.py`), keyed on `CanonicalCommand.key` + policy digest + agent + scope (work item or DM turn) + approver authority; never upgrades `forbid`; each reuse recorded with the original approval's reference (extend the record schema deliberately: `_RECORD_KEYS` and `RECORD_SCHEMA` in `command_gate.py`).
- **O-S2a-4** Mesh path: who the requester is (the pool member or the agent that issued the intent), how many pool members execute one broadcast `run_command` (measure; pool of 3), the consensus and red-team interplay with an approved command, a durable record for this path, and whether `_MeshEffectAdapter` should consult the gate for intent `run_command` (today the mesh path judges after mesh admission when the broker is on).
- **O-S2a-5** Decide whether a policy refusal on the mesh path counts against the shell agent's confidence (`shell_command.py:86-87`) and consensus trust.
- **O-S2a-6** With the broker on, the agent sees only the reason code (`executor.py:892-895`); decide whether the justification should reach it.
- **O-S2a-7** Change `tests/test_ad1328_s2a_startup_and_doctor.py::test_only_the_runtime_builds_the_gate` deliberately if S2b constructs a gate elsewhere (it should not).
- **O-S2a-8** The closing tracker work for #1530 (`DECISIONS.md` closure entry, `PROGRESS.md`, roadmap check).

---

### Section 1 -- `src/probos/config_models/operations.py`

Three edits; each SEARCH occurs exactly once.

<<<<<<< SEARCH
"""Operations, quality and engineering configuration models (AD-1270e2).

Batch 5 of the ``config.py`` extraction. Every model here is self-contained:
it references no other config model and no module-level helper in
``config.py``. Import these from ``probos.config``, which re-exports them.
"""
=======
"""Operations, quality and engineering configuration models (AD-1270e2).

Batch 5 of the ``config.py`` extraction. Every model here is self-contained:
it references no config model outside this module (``ExecutionConfig`` holds
``CommandPolicyConfig``, defined here; AD-1328) and no module-level helper in
``config.py``. Import these from ``probos.config``, which re-exports them.
"""
>>>>>>> REPLACE

<<<<<<< SEARCH
# AD-1328 S1 (#1530): the command execution policy's models. They sit beside
# ExecutionConfig because S2 attaches them as ExecutionConfig.command_policy and
# this module may not import probos. S1 neither attaches nor re-exports them: their
# only reader is probos.execution.command_policy, which no file under src/ imports
# yet (tests/test_ad1328_s1_policy_evaluation.py pins that).
=======
# AD-1328 (#1530): the command execution policy's models. They sit beside
# ExecutionConfig, which holds one as ExecutionConfig.command_policy, because this
# module may not import probos. probos.config re-exports the two models; the
# engine is probos.execution.command_policy and the runtime's one gate is
# probos.execution.command_gate (built in ProbOSRuntime.__init__).
>>>>>>> REPLACE

<<<<<<< SEARCH
    command_env_passthrough: list[str] = Field(default_factory=list)

    @field_validator("command_env_passthrough")
=======
    command_env_passthrough: list[str] = Field(default_factory=list)
    # AD-1328 (#1530): the command execution policy for run_command. No rules (the
    # default) is no policy: every command runs exactly as without one.
    command_policy: CommandPolicyConfig = Field(
        default_factory=CommandPolicyConfig,
        description=(
            "AD-1328: ordered token-prefix rules that decide allow, escalate or forbid for "
            "each command run_command executes (the native tool, the shell agent and the red "
            "team's re-run). The strictest matching rule wins; a forbid rule names its "
            "alternative. Every rule's match / not_match examples are checked at startup under "
            "each shell dialect this platform's run_command paths use, and a failing example "
            "stops startup naming the rule. No rules (the default) means no policy. An opt-in "
            "starter policy is config/command_policy/starter.yaml; probos doctor reports the "
            "loaded policy, its self-test and its digest."
        ),
    )

    @field_validator("command_env_passthrough")
>>>>>>> REPLACE

### Section 2 -- `src/probos/config_models/__init__.py`

<<<<<<< SEARCH
from probos.config_models.operations import (
    AnomalyWindowConfig,
    ConfidenceConfig,
=======
from probos.config_models.operations import (
    AnomalyWindowConfig,
    CommandPolicyConfig,
    CommandPolicyRule,
    ConfidenceConfig,
>>>>>>> REPLACE

<<<<<<< SEARCH
    "CognitiveJournalConfig",
    "CommunicationBenchmarksConfig",
=======
    "CognitiveJournalConfig",
    "CommandPolicyConfig",
    "CommandPolicyRule",
    "CommunicationBenchmarksConfig",
>>>>>>> REPLACE

### Section 3 -- `src/probos/config.py`

<<<<<<< SEARCH
from probos.config_models.operations import (
    AnomalyWindowConfig,
    ConfidenceConfig,
=======
from probos.config_models.operations import (
    AnomalyWindowConfig,
    CommandPolicyConfig,
    CommandPolicyRule,
    ConfidenceConfig,
>>>>>>> REPLACE

### Section 4 -- NEW `src/probos/execution/command_gate.py`

```python
"""AD-1328 S2a (#1530): the command execution policy where ``run_command`` executes.

One ``CommandPolicyGate`` per runtime (``ProbOSRuntime.command_policy_gate``), built
in ``ProbOSRuntime.__init__`` from ``execution.command_policy`` and injected into
every place a ``run_command`` executes: ``RunCommandTool`` (``create_subprocess_shell``:
``cmd.exe`` on Windows, ``/bin/sh`` elsewhere), ``ShellCommandAgent`` and the red
team's re-run (Windows PowerShell on Windows, ``/bin/sh`` elsewhere), and, through
``RunCommandTool.command_policy_preflight``, the AD-1316 shell adapter before the
broker reserves anything. Building it runs every rule's examples under each dialect
those sites use (``probos.execution.command_policy.CommandPolicy``), so a wrong
example is a startup error naming the rule.

``judge`` answers for one command as its call site will run it. With no rules it
returns ``NO_POLICY`` at once: nothing is parsed, resolved or recorded, and the
caller takes the path it took before the policy existed. Otherwise it evaluates the
command, computes its canonical approval key with the same memoised resolver (a PATH
lookup on the child's environment; for ``cmd.exe`` its working directory first), and
returns a ``CommandGateVerdict``: whether the command runs, the refusal the agent is
told (each cause: rule and justification, the alternative for ``forbid``, or the
reason when no rule decided it), the AD-1316 reason code, and a bounded record for
the AD-1224 tool record that carries no command text.

AD-1328 S2a refuses an ``escalate`` truthfully without asking anyone; S2b routes it
to the AD-1154 approval inbox. The policy only adds gates: it never admits a command
that the permission ladder, consensus or the effect broker would refuse.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final, Literal

from probos.config_models.operations import (
    COMMAND_DECISION_RANK,
    CommandDecisionName,
    CommandPolicyConfig,
)
from probos.execution.command_policy import (
    CanonicalCommand,
    CommandEvaluation,
    CommandPolicy,
    Dialect,
    ProgramResolver,
    SelfTestReport,
    default_dialect,
    policy_digest,
    self_test,
)

logger = logging.getLogger(__name__)

CallSite = Literal["run_command_tool", "shell_command_agent"]
#: The shells a run_command executes in, by call site; ``shell_command_agent`` also
#: names the red team's re-run, which starts the same shell.
CALL_SITES: Final[tuple[CallSite, ...]] = ("run_command_tool", "shell_command_agent")
#: The version of the record a run_command result carries to the AD-1224 tool record.
RECORD_SCHEMA: Final = "probos.command_policy.record/v1"
#: A record's JSON text is at most this long; one AD-1224 record is at most 4,096 bytes.
MAX_RECORD_CHARS: Final = 2048
#: The AD-1316 reason code when the policy could not judge a command before admission.
COMMAND_POLICY_UNAVAILABLE: Final = "command_policy_unavailable"
COMMAND_POLICY_UNAVAILABLE_MESSAGE: Final = (
    "The command policy could not judge this command, so it was not run. "
    "Do not repeat this call; report that the command policy failed on it."
)
_FORBID_FRAME: Final = (
    "The command policy forbids this command, so it was not run. {causes} "
    "Do not repeat it; use the alternative named, or report that this step is blocked."
)
#: AD-1328 S2a: refused without asking anyone. S2b replaces this with the approval inbox.
_ESCALATE_FRAME: Final = (
    "The command policy requires approval from the chain of command before this command "
    "runs, and no approval was requested from here, so it was not run. {causes} Do not "
    "repeat this call; continue with the rest of your task and report that this command "
    "needs approval."
)
_MAX_RECORDED: Final = 8
_MAX_SHOWN: Final = 5
_MAX_REASON_CHARS: Final = 300
_RECORD_KEYS: Final = frozenset({
    "schema", "call_site", "decision", "dialect", "policy_digest", "canonical_key",
    "canonical_kind", "matched_rules", "matched_rules_omitted", "causes", "causes_omitted",
})


def run_command_tool_dialect(platform: str | None = None) -> Dialect:
    """The shell ``asyncio.create_subprocess_shell`` starts: ``cmd`` on Windows, else ``posix``."""
    return default_dialect(platform)


def shell_command_agent_dialect(platform: str | None = None) -> Dialect:
    """The shell ``ShellCommandAgent`` and the red team's re-run start: Windows PowerShell
    (``powershell -NoProfile -Command``) on Windows, else ``/bin/sh`` (``shell=True``)."""
    return "powershell" if (sys.platform if platform is None else platform) == "win32" else "posix"


def call_site_dialect(site: CallSite, platform: str | None = None) -> Dialect:
    """The dialect ``site`` runs a command in on ``platform`` (default: this one)."""
    if site == "run_command_tool":
        return run_command_tool_dialect(platform)
    if site == "shell_command_agent":
        return shell_command_agent_dialect(platform)
    raise ValueError("command_policy_call_site_invalid")


def serving_dialects(platform: str | None = None) -> tuple[Dialect, ...]:
    """Every dialect a run_command call site uses on ``platform``, once each, in site order."""
    found: list[Dialect] = []
    for site in CALL_SITES:
        dialect = call_site_dialect(site, platform)
        if dialect not in found:
            found.append(dialect)
    return tuple(found)


def make_program_resolver(
    *,
    dialect: Dialect,
    search_path: str | None,
    cwd: str | None,
    which: Callable[..., Any] = shutil.which,
) -> ProgramResolver:
    """A PATH lookup as the child's shell makes it, memoised for one judgement.

    ``search_path`` is the child's ``PATH`` (from ``build_command_env``). ``cmd.exe``
    looks in its working directory first, so for the ``cmd`` dialect ``cwd`` -- or this
    process's directory, which a child given no ``cwd`` inherits -- leads the search.
    Symlinks are not followed: a pinned ``allow`` rule names the path PATH yields. A
    miss, or an answer that is not a string, is ``None``, which a pinned rule refuses.
    """
    entries: list[str] = []
    if dialect == "cmd":
        entries.append(cwd if cwd else os.getcwd())
    if search_path:
        entries.append(search_path)
    path = os.pathsep.join(entries)
    found: dict[str, str | None] = {}

    def resolve(name: str) -> str | None:
        if name not in found:
            answer = which(name, path=path) if path else None
            found[name] = answer if type(answer) is str else None
        return found[name]

    return resolve


@dataclass(frozen=True)
class CommandPolicyCause:
    """One reason a command took its decision: a rule, or a segment no rule decided."""

    kind: Literal["rule", "unmatched", "unparseable"]
    segment: int | None  # None: the whole line could not be read
    rule: str | None
    text: str  # the justification, or the reason; told to the agent, never recorded
    alternative: str | None


def _causes(evaluation: CommandEvaluation) -> tuple[CommandPolicyCause, ...]:
    causes = [
        CommandPolicyCause("rule", match.segment, match.rule, match.justification, match.alternative)
        for match in evaluation.governing
    ]
    if evaluation.unparseable is not None:
        causes.append(CommandPolicyCause(
            "unparseable", None, None, f"the policy could not read the command: {evaluation.unparseable}", None,
        ))
    for verdict in evaluation.segments:
        if verdict.decision != evaluation.decision or verdict.basis == "rule":
            continue
        if verdict.basis == "unparseable":
            text = f"the policy could not read part {verdict.index + 1}: {verdict.segment.unparseable}"
        else:
            program = verdict.segment.tokens[0] if verdict.segment.tokens else ""
            text = f"no rule covers {program!r}, and commands no rule covers are set to {verdict.decision}"
        causes.append(CommandPolicyCause(verdict.basis, verdict.index, None, text, None))
    return tuple(causes)


def _sentence(text: str) -> str:
    stripped = text.strip()[:_MAX_REASON_CHARS]
    return stripped if stripped.endswith((".", "!", "?")) else f"{stripped}."


def _describe(causes: tuple[CommandPolicyCause, ...]) -> str:
    parts: list[str] = []
    for cause in causes[:_MAX_SHOWN]:
        if cause.kind == "rule":
            text = f"Rule {cause.rule!r}: {_sentence(cause.text)}"
            if cause.alternative:
                text = f"{text} Instead: {_sentence(cause.alternative)}"
        else:
            text = _sentence(cause.text[0].upper() + cause.text[1:] if cause.text else cause.text)
        parts.append(text)
    if len(causes) > _MAX_SHOWN:
        parts.append(f"(and {len(causes) - _MAX_SHOWN} more)")
    return " ".join(parts)


@dataclass(frozen=True)
class CommandGateVerdict:
    """The gate's answer for one command at one call site."""

    status: Literal["no_policy", "evaluated"]
    call_site: CallSite | None
    evaluation: CommandEvaluation | None
    canonical: CanonicalCommand | None

    @property
    def decision(self) -> CommandDecisionName | None:
        return None if self.evaluation is None else self.evaluation.decision

    @property
    def runs(self) -> bool:
        """Whether the caller runs the command: no policy, or ``allow``."""
        return self.status == "no_policy" or self.decision == "allow"

    @property
    def causes(self) -> tuple[CommandPolicyCause, ...]:
        return () if self.evaluation is None else _causes(self.evaluation)

    @property
    def denial_reason(self) -> str:
        """The AD-1316 reason code for a refusal; empty when the command runs."""
        return "" if self.runs else f"command_policy_{self.decision}"

    @property
    def refusal_message(self) -> str | None:
        """What the agent is told when the command does not run; None when it runs."""
        if self.runs:
            return None
        frame = _FORBID_FRAME if self.decision == "forbid" else _ESCALATE_FRAME
        return frame.format(causes=_describe(self.causes))

    @property
    def record(self) -> dict[str, Any] | None:
        """The bounded decision record (no command text); None with no policy."""
        if self.evaluation is None or self.canonical is None:
            return None
        names = list(dict.fromkeys(match.rule for match in self.evaluation.matched_rules))
        causes = self.causes
        return {
            "schema": RECORD_SCHEMA,
            "call_site": self.call_site,
            "decision": self.decision,
            "dialect": self.evaluation.dialect,
            "policy_digest": self.evaluation.policy_digest,
            "canonical_key": self.canonical.key,
            "canonical_kind": self.canonical.kind,
            "matched_rules": names[:_MAX_RECORDED],
            "matched_rules_omitted": max(len(names) - _MAX_RECORDED, 0),
            "causes": [
                {"kind": cause.kind, "segment": cause.segment, "rule": cause.rule}
                for cause in causes[:_MAX_RECORDED]
            ],
            "causes_omitted": max(len(causes) - _MAX_RECORDED, 0),
        }


#: No rules: nothing was evaluated and the command runs as it would without a policy.
NO_POLICY: Final = CommandGateVerdict("no_policy", None, None, None)


def policy_result_metadata(verdict: CommandGateVerdict | None) -> dict[str, Any]:
    """The ``ToolResult.metadata`` a run_command result carries: empty with no policy."""
    record = None if verdict is None else verdict.record
    return {} if record is None else {"command_policy": record}


def command_policy_record_of(result: object) -> dict[str, Any] | None:
    """The decision record a tool result carries, re-validated for the AD-1224 sink.

    Exact keys, the schema tag, a known decision and call site, JSON-serialisable and
    at most ``MAX_RECORD_CHARS``; returns a JSON copy, else None. A tool result is
    untrusted input to the record: anything else is dropped, never repaired.
    """
    metadata = getattr(result, "metadata", None)
    if type(metadata) is not dict:
        return None
    record = metadata.get("command_policy")
    if type(record) is not dict or set(record) != _RECORD_KEYS or record.get("schema") != RECORD_SCHEMA:
        return None
    decision, call_site = record["decision"], record["call_site"]
    if type(decision) is not str or type(call_site) is not str:
        return None  # a list or dict value would raise in the membership tests below
    if decision not in COMMAND_DECISION_RANK or call_site not in CALL_SITES:
        return None
    try:
        encoded = json.dumps(record, sort_keys=True, allow_nan=False)
    except (TypeError, ValueError):
        return None
    if len(encoded) > MAX_RECORD_CHARS:
        return None
    copied: dict[str, Any] = json.loads(encoded)
    return copied


@dataclass(frozen=True)
class CommandPolicyReport:
    """What ``probos doctor`` reports about the configured policy."""

    rule_count: int
    digest: str | None
    reports: tuple[SelfTestReport, ...]
    error: str | None

    @property
    def passed(self) -> bool:
        return self.error is None and all(report.passed for report in self.reports)


def describe_command_policy(config: object, *, platform: str | None = None) -> CommandPolicyReport:
    """The policy's rule count, digest and self-test under each serving dialect. Never raises."""
    if type(config) is not CommandPolicyConfig:
        return CommandPolicyReport(
            0, None, (), f"execution.command_policy is a {type(config).__name__}, not a command policy",
        )
    if not config.rules:
        return CommandPolicyReport(0, None, (), None)
    try:
        reports = tuple(self_test(config, dialect=dialect) for dialect in serving_dialects(platform))
        return CommandPolicyReport(len(config.rules), policy_digest(config), reports, None)
    except Exception as exc:  # doctor reports; it never raises
        return CommandPolicyReport(len(config.rules), None, (), f"{type(exc).__name__}: {exc}")


class CommandPolicyGate:
    """The runtime's one command policy, self-tested under each dialect its call sites use.

    Construction raises ``CommandPolicySelfTestError`` naming the dialect, each failing
    rule and example; ``ProbOSRuntime.__init__`` builds it, so that stops startup.
    ``which`` is the program lookup (``shutil.which``); tests inject one.
    """

    def __init__(
        self,
        config: CommandPolicyConfig,
        *,
        platform: str | None = None,
        which: Callable[..., Any] = shutil.which,
    ) -> None:
        if type(config) is not CommandPolicyConfig:
            raise TypeError("command_policy_config_type_invalid")
        self._config = config
        self._platform = sys.platform if platform is None else platform
        self._which = which
        self._policies: dict[Dialect, CommandPolicy] = {}
        self._digest: str | None = None
        # No rules: nothing to self-test and no digest. Building a CommandPolicy computes
        # the digest, which imports the federation package (probos.federation.ard.jcs), so
        # a runtime without a policy must not build one.
        if config.rules:
            self._policies = {
                dialect: CommandPolicy(config, dialect=dialect) for dialect in serving_dialects(self._platform)
            }
            self._digest = policy_digest(config)
            logger.info(
                "AD-1328: command policy loaded: %d rules, digest %s, examples hold under %s",
                len(config.rules), self._digest, ", ".join(self._policies),
            )

    @property
    def config(self) -> CommandPolicyConfig:
        return self._config

    @property
    def configured(self) -> bool:
        """False with no rules: every command runs as it would without a policy."""
        return bool(self._config.rules)

    @property
    def digest(self) -> str | None:
        """The policy digest; None with no rules."""
        return self._digest

    @property
    def dialects(self) -> tuple[Dialect, ...]:
        """The dialects this gate's call sites use on its platform."""
        return serving_dialects(self._platform)

    @property
    def self_test_reports(self) -> tuple[SelfTestReport, ...]:
        return tuple(policy.self_test_report for policy in self._policies.values())

    def dialect_for(self, site: CallSite) -> Dialect:
        return call_site_dialect(site, self._platform)

    def judge(
        self, command: str, *, site: CallSite, search_path: str | None, cwd: str | None = None,
    ) -> CommandGateVerdict:
        """Judge ``command`` as ``site`` will run it: in its dialect, resolving programs on
        ``search_path`` (the child's PATH) and, for ``cmd``, ``cwd`` first."""
        if not self._config.rules:  # no policy: nothing is parsed, resolved or recorded
            return NO_POLICY
        dialect = self.dialect_for(site)
        policy = self._policies[dialect]
        resolve = make_program_resolver(dialect=dialect, search_path=search_path, cwd=cwd, which=self._which)
        verdict = CommandGateVerdict(
            "evaluated",
            site,
            policy.evaluate(command, resolve_program=resolve),
            policy.canonical(command, resolve_program=resolve),
        )
        if not verdict.runs:
            record = verdict.record or {}
            logger.info(
                "AD-1328: command policy %s a %s command (rules=%s, key=%s, digest=%s)",
                "forbids" if verdict.decision == "forbid" else "escalates",
                site,
                ",".join(record.get("matched_rules", [])) or "-",
                str(record.get("canonical_key", ""))[:16],
                str(self._digest)[:16],
            )
        return verdict
```

### Section 5 -- `src/probos/runtime.py`

Four edits.

<<<<<<< SEARCH
from probos.execution.workspace_results import UnavailableWorkspaceResults, WorkspaceResults  # AD-1240
=======
from probos.execution.command_gate import CommandPolicyGate  # AD-1328 S2a
from probos.execution.workspace_results import UnavailableWorkspaceResults, WorkspaceResults  # AD-1240
>>>>>>> REPLACE

<<<<<<< SEARCH
        self._data_dir = Path(data_dir) if data_dir else _platform_data_dir()
        self._checkpoint_dir = self._data_dir / "checkpoints"
=======
        self._data_dir = Path(data_dir) if data_dir else _platform_data_dir()
        self._checkpoint_dir = self._data_dir / "checkpoints"

        # AD-1328 S2a (#1530): the one command execution policy of this runtime, injected
        # into every place a run_command executes. Building it checks every rule's
        # examples under each shell dialect those places use here and raises
        # CommandPolicySelfTestError naming the rule, which stops startup before any I/O.
        # With no rules (the default) it is inert.
        self.command_policy_gate: CommandPolicyGate = CommandPolicyGate(
            self.config.execution.command_policy,
        )
>>>>>>> REPLACE

<<<<<<< SEARCH
            execution = getattr(self.config, "execution", None)
            spawn_kwargs["command_env_passthrough"] = tuple(
                getattr(execution, "command_env_passthrough", ()),
            )

=======
            execution = getattr(self.config, "execution", None)
            spawn_kwargs["command_env_passthrough"] = tuple(
                getattr(execution, "command_env_passthrough", ()),
            )

        if agent_type == ShellCommandAgent.agent_type and "command_policy_gate" not in spawn_kwargs:
            # AD-1328 S2a (#1530): every member judges commands against this runtime's one
            # policy; the pool keeps its spawn kwargs, so respawned and added members do too.
            # A caller's own value wins. A runtime double without a gate hands none, and its
            # members run without a policy (a real runtime always has one).
            gate = getattr(self, "command_policy_gate", None)
            if gate is not None:
                spawn_kwargs["command_policy_gate"] = gate

>>>>>>> REPLACE

<<<<<<< SEARCH
            agent = RedTeamAgent(
                pool="red_team", agent_id=agent_id,
                command_env_passthrough=tuple(self.config.execution.command_env_passthrough),
            )
=======
            agent = RedTeamAgent(
                pool="red_team", agent_id=agent_id,
                command_env_passthrough=tuple(self.config.execution.command_env_passthrough),
                # AD-1328 S2a (#1530): a command the policy would not run is not re-run.
                command_policy_gate=getattr(self, "command_policy_gate", None),
            )
>>>>>>> REPLACE

### Section 6 -- `src/probos/cognitive/swe_harness/tools.py`

Six edits.

<<<<<<< SEARCH
from probos.execution.command_env import build_command_env
from probos.execution.process_tree import ProcessTree, process_tree_popen_kwargs
=======
from probos.execution.command_env import build_command_env
from probos.execution.command_gate import (
    COMMAND_POLICY_UNAVAILABLE,
    CommandGateVerdict,
    CommandPolicyGate,
    policy_result_metadata,
)
from probos.execution.process_tree import ProcessTree, process_tree_popen_kwargs
>>>>>>> REPLACE

<<<<<<< SEARCH
    def __init__(
        self, runtime: "ProbOSRuntime", *, command_env_passthrough: tuple[str, ...] = (),
    ) -> None:
        self._runtime = runtime
        # BF-890 (#1529): names from execution.command_env_passthrough, injected
        # at registration; input_schema declares no such parameter.
        self._command_env_passthrough: tuple[str, ...] = tuple(command_env_passthrough)

    async def invoke(
=======
    def __init__(
        self,
        runtime: "ProbOSRuntime",
        *,
        command_env_passthrough: tuple[str, ...] = (),
        command_policy_gate: CommandPolicyGate | None = None,
    ) -> None:
        self._runtime = runtime
        # BF-890 (#1529): names from execution.command_env_passthrough, injected
        # at registration; input_schema declares no such parameter.
        self._command_env_passthrough: tuple[str, ...] = tuple(command_env_passthrough)
        # AD-1328 S2a (#1530): the runtime's command policy (ProbOSRuntime.command_policy_gate),
        # injected at registration. None: no policy.
        self._command_policy_gate = command_policy_gate

    def _policy_verdict(self, command: str, cwd: object) -> CommandGateVerdict | None:
        """AD-1328 S2a: the policy's verdict on ``command`` as this tool spawns it, or None
        with no policy (no gate, or no rules), in which case nothing else is done."""
        gate = self._command_policy_gate
        if gate is None or not gate.configured:
            return None
        # The child's PATH, from the owner that builds the child's environment below.
        child_env = build_command_env(self._command_env_passthrough)
        return gate.judge(
            command,
            site="run_command_tool",
            search_path=child_env.get("PATH"),
            cwd=cwd if type(cwd) is str else None,
        )

    def command_policy_preflight(self, params: dict[str, Any]) -> str:
        """AD-1328 S2a: the AD-1316 shell adapter's question, asked before the broker reserves
        the effect. The policy's reason code for refusing this call, or "" when it does not
        refuse it (the adapter still refuses an unproven shell)."""
        command = params.get("command") if type(params) is dict else None
        if type(command) is not str or not command.strip():
            return ""
        try:
            verdict = self._policy_verdict(command, params.get("working_directory"))
        except Exception:
            logger.warning(
                "AD-1328: the command policy could not judge a run_command call before broker "
                "admission; it is refused", exc_info=True,
            )
            return COMMAND_POLICY_UNAVAILABLE
        return "" if verdict is None or verdict.runs else verdict.denial_reason

    async def invoke(
>>>>>>> REPLACE

<<<<<<< SEARCH
        timeout = float(params.get("timeout", 30.0))
        cwd = params.get("working_directory")
        try:
            # Cross-platform: use shell=True via create_subprocess_shell
=======
        timeout = float(params.get("timeout", 30.0))
        cwd = params.get("working_directory")
        verdict: CommandGateVerdict | None = None
        try:
            # AD-1328 S2a (#1530): the command policy judges the command before it runs. With
            # no policy the verdict is None and nothing else here changes. A judgement that
            # raises lands in the handler below: the command is not run.
            verdict = self._policy_verdict(str(command), cwd)
            if verdict is not None and not verdict.runs:
                return ToolResult(
                    error=verdict.refusal_message,
                    metadata=policy_result_metadata(verdict),
                )
            # Cross-platform: use shell=True via create_subprocess_shell
>>>>>>> REPLACE

<<<<<<< SEARCH
            except _asyncio.TimeoutError:
                tree.kill()
                return ToolResult(error=f"run_command timed out after {timeout}s")
=======
            except _asyncio.TimeoutError:
                tree.kill()
                return ToolResult(
                    error=f"run_command timed out after {timeout}s",
                    metadata=policy_result_metadata(verdict),
                )
>>>>>>> REPLACE

<<<<<<< SEARCH
            return ToolResult(
                output={
                    "stdout": stdout,
                    "stderr": stderr,
                    "exit_code": proc.returncode if proc.returncode is not None else -1,
                }
            )
        except Exception as exc:
=======
            return ToolResult(
                output={
                    "stdout": stdout,
                    "stderr": stderr,
                    "exit_code": proc.returncode if proc.returncode is not None else -1,
                },
                metadata=policy_result_metadata(verdict),
            )
        except Exception as exc:
>>>>>>> REPLACE

<<<<<<< SEARCH
    command_env_passthrough: tuple[str, ...] = (),
) -> int:
=======
    command_env_passthrough: tuple[str, ...] = (),
    command_policy_gate: CommandPolicyGate | None = None,
) -> int:
>>>>>>> REPLACE

<<<<<<< SEARCH
        (RunCommandTool(runtime, command_env_passthrough=command_env_passthrough), shell_perms),
=======
        (
            RunCommandTool(
                runtime,
                command_env_passthrough=command_env_passthrough,
                # AD-1328 S2a: the runtime's command policy.
                command_policy_gate=command_policy_gate,
            ),
            shell_perms,
        ),
>>>>>>> REPLACE

### Section 7 -- `src/probos/startup/finalize.py`

<<<<<<< SEARCH
        count = register_native_swe_tools(
            registry, runtime,
            command_env_passthrough=tuple(config.execution.command_env_passthrough),
        )
=======
        count = register_native_swe_tools(
            registry, runtime,
            command_env_passthrough=tuple(config.execution.command_env_passthrough),
            # AD-1328 S2a (#1530): the runtime's one command policy (ProbOSRuntime.__init__).
            command_policy_gate=getattr(runtime, "command_policy_gate", None),
        )
>>>>>>> REPLACE

### Section 8 -- `src/probos/agents/shell_command.py`

Four edits.

<<<<<<< SEARCH
from probos.execution.command_env import build_command_env
=======
from probos.execution.command_env import build_command_env
from probos.execution.command_gate import COMMAND_POLICY_UNAVAILABLE_MESSAGE, CommandPolicyGate
>>>>>>> REPLACE

<<<<<<< SEARCH
        self._command_env_passthrough: tuple[str, ...] = tuple(kwargs.pop("command_env_passthrough", ()))
        super().__init__(pool, **kwargs)
=======
        self._command_env_passthrough: tuple[str, ...] = tuple(kwargs.pop("command_env_passthrough", ()))
        # AD-1328 S2a (#1530): the runtime's command policy, injected through the shell
        # pool's spawn kwargs (ProbOSRuntime.create_pool). None: no policy.
        self._command_policy_gate: CommandPolicyGate | None = kwargs.pop("command_policy_gate", None)
        super().__init__(pool, **kwargs)
>>>>>>> REPLACE

<<<<<<< SEARCH
        command = self._rewrite_python_interpreter(command)

        loop = asyncio.get_running_loop()
=======
        command = self._rewrite_python_interpreter(command)

        # AD-1328 S2a (#1530): judged as it will run -- after the two rewrites above, in the
        # dialect of the shell _run_sync starts. With no policy this returns None at once.
        refusal = self._command_policy_refusal(command)
        if refusal is not None:
            return refusal

        loop = asyncio.get_running_loop()
>>>>>>> REPLACE

<<<<<<< SEARCH
    @staticmethod
    def _strip_ps_wrapper(command: str) -> str:
=======
    def _command_policy_refusal(self, command: str) -> dict[str, Any] | None:
        """AD-1328 S2a: the refusal to return instead of running ``command``, or None to run it.

        No gate or no rules: None, and nothing else is done. A judgement that raises is a
        refusal: the command is not run.
        """
        gate = self._command_policy_gate
        if gate is None or not gate.configured:
            return None
        try:
            # The child's PATH, from the owner _run_sync builds the child's environment with.
            child_env = build_command_env(self._command_env_passthrough)
            verdict = gate.judge(command, site="shell_command_agent", search_path=child_env.get("PATH"))
        except Exception:
            logger.warning(
                "AD-1328: the command policy could not judge a run_command intent; it was not run",
                exc_info=True,
            )
            return {"success": False, "error": COMMAND_POLICY_UNAVAILABLE_MESSAGE}
        if verdict.runs:
            return None
        return {"success": False, "error": verdict.refusal_message}

    @staticmethod
    def _strip_ps_wrapper(command: str) -> str:
>>>>>>> REPLACE

### Section 9 -- `src/probos/agents/red_team.py`

Four edits.

<<<<<<< SEARCH
from probos.execution.command_env import build_command_env
=======
from probos.execution.command_env import build_command_env
from probos.execution.command_gate import CommandPolicyGate
>>>>>>> REPLACE

<<<<<<< SEARCH
        self._command_env_passthrough: tuple[str, ...] = tuple(kwargs.pop("command_env_passthrough", ()))
        super().__init__(pool, **kwargs)
=======
        self._command_env_passthrough: tuple[str, ...] = tuple(kwargs.pop("command_env_passthrough", ()))
        # AD-1328 S2a (#1530): the runtime's command policy (ProbOSRuntime._spawn_red_team).
        # The re-run is a place a command executes, so the policy gates it too. None: no policy.
        self._command_policy_gate: CommandPolicyGate | None = kwargs.pop("command_policy_gate", None)
        super().__init__(pool, **kwargs)
>>>>>>> REPLACE

<<<<<<< SEARCH
        command = params.get("command", "")
        try:
            loop = asyncio.get_running_loop()
            deadline = time.monotonic() + _RERUN_TIMEOUT_S
=======
        command = params.get("command", "")
        # AD-1328 S2a (#1530): a command the policy would not run is not re-run here either;
        # the verdict alone answers the claim. With no policy this returns None at once.
        refused = self._command_policy_verification(target_agent_id, intent, claimed, command)
        if refused is not None:
            return refused
        try:
            loop = asyncio.get_running_loop()
            deadline = time.monotonic() + _RERUN_TIMEOUT_S
>>>>>>> REPLACE

<<<<<<< SEARCH
    @staticmethod
    def _run_verify_sync(
=======
    def _command_policy_verification(
        self,
        target_agent_id: str,
        intent: IntentMessage,
        claimed: IntentResult,
        command: Any,
    ) -> VerificationResult | None:
        """AD-1328 S2a: answer a run_command claim without re-running a command the policy refuses.

        None with no policy, or when the policy lets the command run (re-run as before). A
        refused command is consistent only with a claimed failure. A judgement that raises
        is not a re-run: the claim is left unverified.
        """
        gate = self._command_policy_gate
        if gate is None or not gate.configured:
            return None
        try:
            child_env = build_command_env(self._command_env_passthrough)
            verdict = gate.judge(str(command), site="shell_command_agent", search_path=child_env.get("PATH"))
        except Exception:
            logger.warning(
                "AD-1328: the command policy could not judge a run_command re-run; it was not re-run",
                exc_info=True,
            )
            return VerificationResult(
                verifier_id=self.id,
                target_agent_id=target_agent_id,
                intent_id=intent.id,
                verified=False,
                discrepancy="The command policy could not judge the command, so it was not re-run",
                confidence=self.confidence,
            )
        if verdict.runs:
            return None
        self.update_confidence(True)
        return VerificationResult(
            verifier_id=self.id,
            target_agent_id=target_agent_id,
            intent_id=intent.id,
            verified=not claimed.success,
            discrepancy=(
                ""
                if not claimed.success
                else f"Agent claims success but the command policy refuses this command ({verdict.decision})"
            ),
            confidence=self.confidence,
        )

    @staticmethod
    def _run_verify_sync(
>>>>>>> REPLACE

### Section 10 -- `src/probos/execution/effect_adapters.py`

<<<<<<< SEARCH
class _ShellEffectAdapter(_BaseEffectAdapter):
    kind = "opaque"

    def prepare(
        self,
        *,
        tool_id: str,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> PreparedEffect:
        return PreparedEffect(
=======
class _ShellEffectAdapter(_BaseEffectAdapter):
    kind = "opaque"

    def __init__(self, tool: Tool) -> None:
        self._tool = tool

    def _policy_denial(self, params: dict[str, Any]) -> str:
        """AD-1328 S2a (#1530): the command policy's reason code, asked before the broker
        reserves anything; "" when the policy does not refuse the call.

        The tool owns the judgement (``RunCommandTool.command_policy_preflight``). A
        preflight that raises or answers oddly is ``command_policy_unavailable``.
        """
        preflight = getattr(self._tool, "command_policy_preflight", None)
        if preflight is None:
            return ""
        try:
            reason = preflight(params)
        except Exception:
            return "command_policy_unavailable"
        return reason if type(reason) is str else "command_policy_unavailable"

    def prepare(
        self,
        *,
        tool_id: str,
        params: dict[str, Any],
        context: dict[str, Any],
    ) -> PreparedEffect:
        # A policy refusal is the more specific reason; otherwise an unproven shell is refused.
        policy_denial = self._policy_denial(params)
        return PreparedEffect(
>>>>>>> REPLACE

<<<<<<< SEARCH
            retry_disposition="blocked",
            denial_reason="shell_isolation_unproven",
        )
=======
            retry_disposition="blocked",
            denial_reason=policy_denial or "shell_isolation_unproven",
        )
>>>>>>> REPLACE

<<<<<<< SEARCH
            return _ShellEffectAdapter()
=======
            return _ShellEffectAdapter(tool)
>>>>>>> REPLACE

### Section 11 -- `src/probos/tools/executor.py`

<<<<<<< SEARCH
        if payload is None:
            payload = _bounded_record({
                **metadata,
                "duration_ms": duration,
                "timestamp": time.time(), "is_error": result.error is not None,
                "error_category": category,
            })
=======
        if payload is None:
            fields: dict[str, Any] = {
                **metadata,
                "duration_ms": duration,
                "timestamp": time.time(), "is_error": result.error is not None,
                "error_category": category,
            }
            # AD-1328 S2a (#1530): the command policy's decision, when the tool reports one
            # (RunCommandTool's ToolResult.metadata), re-validated; it never holds the command.
            from probos.execution.command_gate import command_policy_record_of

            policy_record = command_policy_record_of(result)
            if policy_record is not None:
                fields["command_policy"] = policy_record
            payload = _bounded_record(fields)
>>>>>>> REPLACE

### Section 12 -- NEW `src/probos/doctor/checks/command_policy_check.py`

```python
"""AD-1328 S2a (#1530): the command execution policy -- rules loaded, self-test, digest."""

from __future__ import annotations

from dataclasses import dataclass

from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check
from probos.execution.command_gate import describe_command_policy


@dataclass(frozen=True)
class _CommandPolicyCheck:
    name: str = "command_policy"

    async def run(self, ctx: DoctorContext) -> CheckResult:
        execution = getattr(ctx.config, "execution", None) if ctx.config is not None else None
        if execution is None:
            return CheckResult(
                outcome=CheckOutcome.WARN,
                message="Command policy: not checked, because the configuration did not load",
                remediation="Fix the configuration error reported above, then run probos doctor again.",
            )
        report = describe_command_policy(getattr(execution, "command_policy", None))
        if report.error is not None:
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message=f"Command policy: could not be checked ({report.error})",
                remediation="Correct execution.command_policy in the configuration file.",
            )
        if report.rule_count == 0:
            return CheckResult(
                outcome=CheckOutcome.OK,
                message="Command policy: none configured; run_command runs every command as it would without one",
            )
        dialects = ", ".join(r.dialect for r in report.reports)
        failures = [(r.dialect, failure) for r in report.reports for failure in r.failures]
        if failures:
            shown = "; ".join(f"under {dialect}: {failure.message}" for dialect, failure in failures[:3])
            more = f" (and {len(failures) - 3} more)" if len(failures) > 3 else ""
            return CheckResult(
                outcome=CheckOutcome.FAIL,
                message=f"Command policy: {report.rule_count} rules; self-test failed -- {shown}{more}",
                remediation=(
                    "Correct each named rule's pattern or example in execution.command_policy; "
                    f"ProbOS will not start until every example holds under {dialects}."
                ),
            )
        checked = sum(r.examples_checked for r in report.reports)
        return CheckResult(
            outcome=CheckOutcome.OK,
            message=(
                f"Command policy: {report.rule_count} rules, self-test passed under {dialects} "
                f"({checked} examples), digest {report.digest}"
            ),
        )


register_check(_CommandPolicyCheck())
```

### Section 13 -- `src/probos/doctor/checks/__init__.py`

<<<<<<< SEARCH
    sandbox_check,
    pairing_check,
=======
    sandbox_check,
    command_policy_check,
    pairing_check,
>>>>>>> REPLACE

### Section 14 -- NEW `config/command_policy/starter.yaml`

```yaml
# AD-1328 (#1530): the opt-in starter command policy for run_command.
#
# Not loaded by default. With no rules every command runs exactly as it would
# without a policy. To adopt this one, copy the mapping under `command_policy:`
# into config/system.yaml under `execution:` (as `execution.command_policy`),
# review each rule, run `probos doctor` (it reports the rule count, the digest
# and the self-test under each shell dialect your platform's run_command paths
# use), and restart.
#
# A deny-list: a command no rule names runs (unmatched_decision: allow); a
# download started from a shell is forbidden in favour of the governed fetch;
# a push waits for the chain of command; a command the policy cannot read waits
# for approval too (unparseable_decision: escalate). Every example below holds
# under the posix, cmd and powershell dialects
# (tests/test_ad1328_s2a_startup_and_doctor.py).
command_policy:
  unmatched_decision: allow
  unparseable_decision: escalate
  rules:
    - name: shell-download
      pattern: [[curl, wget, Invoke-WebRequest, iwr, Invoke-RestMethod, irm]]
      decision: forbid
      justification: A download started from a shell bypasses the ship's governed fetch path
      alternative: use http_fetch, the ship's governed fetch
      match: ["curl -sS example.com", "wget example.com", "Invoke-WebRequest example.com"]
      not_match: ["git status", "curlie example.com"]
    - name: git-push
      pattern: [git, push]
      decision: escalate
      justification: A push publishes the ship's work, so the chain of command approves each one
      match: ["git push", "git push origin main"]
      not_match: ["git pull", "git status"]
```

### Section 15 -- `DECISIONS.md`

<<<<<<< SEARCH
- Contract `prompts/ad-1328-s1-command-policy-core.md`.
=======
- Contract `prompts/ad-1328-s1-command-policy-core.md`.

### AD-1328 S2a -- Command execution policy wiring: one gate per runtime, judged wherever run_command executes, before broker admission (2026-10-16, #1530)

- *Slicing.* S1 the core, S2a (this) the wiring, S2b the approval round trip (escalation to the AD-1154 inbox, approved command runs exactly once, approval reuse); one PR.
- *One gate per runtime.* `ProbOSRuntime.__init__` builds `CommandPolicyGate` from `execution.command_policy`; it holds one self-tested `CommandPolicy` per dialect the call sites use on this platform (`cmd` and PowerShell on Windows, `posix` elsewhere), so a wrong example stops startup naming the rule. Constructor injection into `RunCommandTool`, `ShellCommandAgent` (shell pool spawn kwargs) and `RedTeamAgent`.
- *Three call sites.* The red team's run_command verification re-ran the claimed command before reading the claim, so it would have executed a command the shell agent refused; it now answers from the verdict without re-running. Each site judges the command as it will run (after the shell agent's rewrites) in its own dialect, resolving programs on the child's PATH (`cmd`: working directory first).
- *Before broker admission.* The AD-1316 shell adapter asks `RunCommandTool.command_policy_preflight` before the broker reserves the effect; a policy refusal is the recorded denial reason (`command_policy_forbid`, `command_policy_escalate`, `command_policy_unavailable`), otherwise `shell_isolation_unproven` as before.
- *No policy.* No rules: nothing is evaluated, resolved or recorded; golden tests pin each path's spawn and result.
- *Refusals and records.* A refusal names each cause (rule, justification and alternative, or the unmatched or unparseable reason when no rule decided). The AD-1224 completion record gains a validated `command_policy` record (decision, dialect, digest, canonical key, rule names, cause kinds; never the command text). An `escalate` is refused truthfully in S2a; S2b files it.
- *Doctor and starter.* `probos doctor` check `command_policy`; opt-in starter policy `config/command_policy/starter.yaml`, its examples tested under every dialect.
- Contract `prompts/ad-1328-s2a-command-policy-wiring.md`.
>>>>>>> REPLACE

### Section 16 -- `PROGRESS.md`

The first 120 characters carry no ledger status keyword (`scripts/gen_ad_ledger.py:126-139`).

<<<<<<< SEARCH
# ProbOS Progress
=======
# ProbOS Progress

**AD-1328 slice S2a (2026-10-16), #1530 -- the command policy is wired wherever run_command executes; no new AD or BF number.** `ProbOSRuntime.__init__` builds one `CommandPolicyGate` from the new `execution.command_policy` field (no rules by default, which is no policy), self-testing every example under each shell dialect this platform's call sites use, so a wrong example stops startup naming the rule. `RunCommandTool`, `ShellCommandAgent` and the red team's re-run judge each command as it will run; the AD-1316 shell adapter asks before the broker reserves the effect. A refusal names every cause; the decision is recorded on the AD-1224 tool record (no command text) and as the AD-1316 denial reason. `probos doctor` reports the policy; an opt-in starter policy is `config/command_policy/starter.yaml`. The red team's verification used to re-run a command before reading the claim, which would have run a refused command; it no longer does. S2b (escalation to the approval inbox, approved command runs exactly once, approval reuse) completes #1530 in the same PR. Contract `prompts/ad-1328-s2a-command-policy-wiring.md`.
>>>>>>> REPLACE

**Regenerate after installing Sections 1-16** (orchestrator, in this order):

```
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_facade.py --update-baseline
d:/ProbOS/.venv/Scripts/python.exe scripts/gen_config_reference.py
d:/ProbOS/.venv/Scripts/python.exe scripts/gen_ad_ledger.py
```

Then each `--check` (acceptance 9). If `check_config_profiles.py --check` reports the new field, stop and report: the field adds no boolean, so it should not.

---

## Tests (written by Builders against the installed source; tests only)

Rules for every file: never edit `src/`. No real shell: spawns are recorded by monkeypatching (`asyncio.create_subprocess_shell` for the tool, `ShellCommandAgent._run_sync` / `RedTeamAgent._run_verify_sync` for the agents); `ProcessTree` is replaced where the tool path needs it. Build gates with `CommandPolicyGate(cfg, platform="win32" | "linux", which=fake_which)` so dialects do not depend on the host; the only host-dependent rows are named. Configs come from `CommandPolicyConfig.model_validate({...})`. Each test asserts its premise and a negative control. Copy the S1 `_policy` / `_rule` helpers (`prompts/ad-1328-s1-command-policy-core.md`, Tests) rather than importing across test files. Check fixed refusal text against the real `probos.cognitive.decomposer._CAPABILITY_GAP_RE`.

### M1 `tests/test_ad1328_s2a_gate.py` (the gate alone)

1. `test_dialect_per_call_site[win32, linux, darwin]`: `call_site_dialect("run_command_tool", p)` is `cmd`/`posix`/`posix`; `"shell_command_agent"` is `powershell`/`posix`/`posix`; `serving_dialects("win32") == ("cmd", "powershell")`, `("linux") == ("posix",)`; an unknown site raises `ValueError("command_policy_call_site_invalid")`. Kills G9.
2. `test_gate_self_tests_every_serving_dialect`: a rule `["echo", "a&b"]` with match example `echo a^&b` holds under `cmd` and not under `powershell`, so `CommandPolicyGate(cfg, platform="win32")` raises `CommandPolicySelfTestError` whose text names `powershell`, the rule and the example; a rule whose examples hold in all three builds under both platforms; `gate.dialects` and `len(gate.self_test_reports)` match `serving_dialects`. Kills G8.
3. `test_no_rules_is_inert`: with `probos.execution.command_gate.CommandPolicy` and `probos.execution.command_gate.policy_digest` monkeypatched to raise, `CommandPolicyGate(CommandPolicyConfig(), which=spy)` still builds (it builds no policy and computes no digest: S1's digest imports the federation package), `digest is None`, `self_test_reports == ()`, `configured is False`, `judge("(((", site=..., search_path="/bin")` is `NO_POLICY` (`runs`, `record is None`, `refusal_message is None`, `denial_reason == ""`), and `spy` was never called; with `CommandPolicy.evaluate` monkeypatched to raise, still `NO_POLICY`. Kills G1.
4. `test_resolver_search_order[cmd_with_cwd, cmd_without_cwd, posix, powershell, no_path]`: a recording `which` sees `path == os.pathsep.join([cwd, "P"])` for `cmd` with `cwd`, `os.pathsep.join([os.getcwd(), "P"])` without, `"P"` for `posix` and `powershell`; with no `search_path` and not `cmd`, `which` is not called and the answer is `None`; a non-string answer is `None`. Kills G3.
5. `test_resolver_is_memoised_within_one_judgement`: a pinned allow rule (`host_executable=["/usr/bin/git"]`) and `git status`: one `judge` calls `which("git", ...)` exactly once although both evaluation and canonical key use it; two judgements call it twice. Kills G5.
6. `test_pinned_allow_follows_the_child_path`: posix gate; `which` answers `/usr/bin/git` for `search_path="/usr/bin"` -> `allow`, `runs`; answers `/tmp/evil/git` -> `forbid` with the path in the message; answers `None` -> `forbid`.
7. `test_verdict_runs_only_for_allow[allow, escalate, forbid]`: `runs`, `denial_reason` (`""`, `command_policy_escalate`, `command_policy_forbid`). Kills G2.
8. `test_forbid_message_names_rule_justification_and_alternative`: contains the rule name, justification and alternative; starts with the forbid frame; does not match `_CAPABILITY_GAP_RE` (rules with plain justifications). Kills G6 (with #9).
9. `test_escalate_message_names_the_rule_or_the_reason[rule, unmatched, unparseable_line, unparseable_segment]`: rule -> name and justification; allow-list `unmatched_decision="escalate"` and `ls` -> the message names `'ls'` and the cause kind is `unmatched` (`governing == ()`, O-S1-11); `echo "x` -> the whole-line reason; `eval x` -> the segment reason; each says no approval was requested; none matches `_CAPABILITY_GAP_RE` in its frame text. Kills G4.
10. `test_causes_list_every_non_rule_segment_at_the_decision`: `git push; ls` under escalate `git push`, `unmatched="escalate"` -> two causes (rule, unmatched) in segment order; with an allow rule for every segment of `git status; ls` the causes are the allow matches only; `git push; ls` with `unmatched="allow"` escalates with the rule cause alone. (As installed, D7 also lists a segment no rule covers whose decision equals the command's: `git status; ls` with an allow rule for `git status` and `unmatched="allow"` gives the rule cause and an `unmatched` cause for `ls`; one commented test pins that literal behaviour, `test_causes_at_an_allow_decision_also_list_a_segment_no_rule_covers`.)
11. `test_message_shows_five_causes_then_a_count`: seven forbidden segments -> five `Rule '` and `(and 2 more)`.
12. `test_record_shape_and_no_command_text`: keys equal the documented set; `schema == "probos.command_policy.record/v1"`; `policy_digest == gate.digest`; `canonical_key == policy.canonical(cmd).key` computed in the test from `CommandPolicy(cfg, dialect=...)`; a command containing a sentinel word (`curl SENTINEL-7Q`) whose rule justification does not contain it: `json.dumps(record)` does not contain the sentinel or the justification. Kills G7.
13. `test_record_is_bounded`: 20 matched rules with 64-character names over 20 segments -> `matched_rules` has 8, `matched_rules_omitted == 12`, causes 8 with a count, `len(json.dumps(record, sort_keys=True)) <= MAX_RECORD_CHARS`.
14. `test_record_validator[gate_record, extra_key, missing_key, wrong_schema, bad_decision, bad_site, unhashable_decision, unhashable_site, not_json, too_long, metadata_not_dict]`: only the first returns a copy equal to the input (and not the same object); a list or dict `decision` or `call_site` is dropped, never raises (found by M1 at install). Kills G10.
15. `test_policy_result_metadata`: `None` and `NO_POLICY` -> `{}`; an evaluated verdict -> `{"command_policy": record}`.
16. `test_describe_command_policy[none, passing, failing, wrong_type]`: never raises; counts, digest, `passed`, per-dialect reports under `platform=` given; the failing report names the rule.

### M2 `tests/test_ad1328_s2a_run_command_tool.py` (tool path, broker preflight, AD-1224 record)

Spawn recorder: `asyncio.create_subprocess_shell` replaced by an async fake that records `(args, kwargs)` and returns a process whose `communicate()` gives `(b"out", b"")` and `returncode == 0`; `probos.cognitive.swe_harness.tools.ProcessTree` replaced by a fake whose `attach()` returns an object with `kill()` and `close()`.

1. `test_no_policy_is_byte_identical[no_gate, unconfigured_gate]`: `RunCommandTool(runtime, command_policy_gate=...)`.invoke(`{"command": "echo hi"}`): one spawn with args `("echo hi",)` and kwargs exactly `{"stdout": PIPE, "stderr": PIPE, "cwd": None, "env": build_command_env(()), **process_tree_popen_kwargs()}`; result `== ToolResult(output={"stdout": "out", "stderr": "", "exit_code": 0})` and `metadata == {}`; the two variants are equal; with the gate unconfigured, `build_command_env` is called exactly once (the spawn's) and `which` never. Kills T3 and the unconfigured-gate mutant of `_policy_verdict`.
2. `test_allow_runs_once_and_records[posix_gate, cmd_gate]`: allow `echo` -> one spawn, unchanged kwargs, `metadata["command_policy"]["decision"] == "allow"`, dialect per gate platform.
3. `test_forbid_is_not_spawned_and_tells_the_alternative`: no spawn; `error` holds rule, justification and alternative; `metadata["command_policy"]["decision"] == "forbid"`. Kills T1.
4. `test_escalate_is_not_spawned_and_names_its_cause[rule, unmatched]`: no spawn; rule case names the rule; unmatched case names the program (O-S1-11).
5. `test_compound_with_one_forbidden_segment_is_forbidden[posix: "git status && curl x", cmd: "git status & curl x"]`.
6. `test_judgement_error_does_not_spawn`: gate `judge` monkeypatched to raise -> no spawn, `error` starts `run_command failed:`.
7. `test_resolver_uses_the_child_path_and_working_directory`: `cmd` gate, pinned rule; recording `which`; `params["working_directory"] = "C:\\work"`: `which` saw `path` starting `C:\\work` + `os.pathsep` + the `PATH` of `build_command_env(())`; posix gate: `path` equals that `PATH`.
8. `test_timeout_still_records_the_decision`: `communicate` never finishes, `timeout=0.01`: error `run_command timed out after 0.01s`, `metadata["command_policy"]["decision"] == "allow"`.
9. `test_preflight_reason_codes[no_gate, unconfigured, allow, forbid, escalate, raises, blank_command]`: `command_policy_preflight(params)` returns `""`, `""`, `""`, `command_policy_forbid`, `command_policy_escalate`, `command_policy_unavailable`, `""`. Kills T2.
10. `test_shell_adapter_uses_the_policy_reason[...]`: `_EffectAdapterRegistry().for_tool(tool, "run_command").prepare(tool_id="run_command", params=..., context={})`.denial_reason is `command_policy_forbid` for a forbidden command, `shell_isolation_unproven` for allowed or no policy, `command_policy_unavailable` when the tool's preflight raises (monkeypatched). Kills A1.
11. `test_broker_denies_before_admission_with_the_policy_reason`: follow `tests/test_ad1316_governed_effect_broker.py` `strict_runtime`, `_register`, `_invoke` (`:879-891`; copy the helpers): register a real `RunCommandTool(SimpleNamespace(), command_policy_gate=forbid_gate)` and invoke `run_command` with a forbidden command: the operation is `denied` with `reason_code == "command_policy_forbid"`, the result error is that code, and the spawn recorder never ran; with an allowed command the reason is `shell_isolation_unproven` (the broker still refuses an unproven shell -- the policy only adds gates). This test crosses tool -> adapter -> broker -> effect record.
12. `test_ad1224_record_carries_the_decision`: a real `ToolExecutor` over a real `ToolRegistry` holding `RunCommandTool` (shell permission granted), with `make_audit_hook(emit_fn)` as a post-hook (bus-only form): a forbidden call emits `TOOL_INVOKED` whose payload `command_policy` equals the tool result's record, holds no command text, and the payload JSON is at most 4,096 bytes; a no-policy call's payload has no `command_policy` key; a tool result whose metadata carries an invalid record (a stand-in tool) yields no key. Kills X1. This test crosses tool -> executor hook -> record.

### M3 `tests/test_ad1328_s2a_shell_agent.py` (shell agent and red team)

Recorder: `monkeypatch.setattr(ShellCommandAgent, "_run_sync", lambda self, command, deadline=None, slot=None: rec(command))` returning `{"success": True, "data": {"stdout": "ok", "stderr": "", "exit_code": 0, "command": command}}`.

1. `test_no_policy_is_byte_identical[no_gate, unconfigured_gate]`: `_run_command("git status")` calls `_run_sync` once with `"git status"` and returns the recorder's dict unchanged; `probos.agents.shell_command.build_command_env` (spied) is not called by `_run_command`. Kills S2m.
2. `test_forbid_and_escalate_are_not_run[forbid, escalate]`: `_run_sync` not called; result `{"success": False, "error": ...}` with the rule and justification (and alternative for forbid). Kills S1m.
3. `test_through_handle_intent`: an `IntentMessage(intent="run_command", params={"command": "git push"})` with escalate `git push` -> `IntentResult.success is False`, `error` names the rule; `_run_sync` not called. (`git` is in `_command_exists`'s builtins, so `decide()` passes on any host.)
4. `test_shell_agent_judges_at_its_own_call_site`: wrap `CommandPolicyGate.judge` (monkeypatch a delegating recorder) and assert the agent passes `site="shell_command_agent"`; for a gate built with `platform="win32"`, `gate.dialect_for("shell_command_agent") == "powershell"`, with `platform="linux"` `"posix"`. Behavioural control: under either gate, allow `["git", "status"]` runs `git status`.
5. `test_judged_after_the_python_rewrite` (host-dependent mechanism, same outcome on every host; gate built with the host's platform): allow `["python"]`, `unmatched="escalate"`: `python -c "print(1)"` is rewritten to the interpreter's path, which an unpinned `allow` does not match, so the result is an escalation whose cause is `unmatched` and `_run_sync` is not called. Control: allow `["git"]` runs `git status`.
6. `test_judged_after_the_powershell_unwrap`: `monkeypatch.setattr("probos.agents.shell_command.sys.platform", "win32")`; gate `platform="win32"`; allow `["git", "status"]`, `unmatched="escalate"`: `powershell -Sta -Command "git status"` -> `_run_sync` called with `git status` (the strip removed `-Sta`, which S1 would otherwise read as an unwrappable shell, escalating). Control: the same command with `_strip_ps_wrapper` monkeypatched to identity -> escalated.
7. `test_judgement_error_is_a_refusal`: `judge` raises -> `{"success": False, "error": COMMAND_POLICY_UNAVAILABLE_MESSAGE}`, `_run_sync` not called.
8. `test_red_team_does_not_rerun_a_refused_command[claimed_failure, claimed_success]`: `RedTeamAgent(pool="red_team", command_policy_gate=forbid_gate)` with `_run_verify_sync` replaced by a recorder: `_verify_run_command` for a forbidden command does not call the recorder; `verified is True` for a claimed failure, `False` with a discrepancy naming the policy for a claimed success. Control: an allowed command is re-run once. Kills R1.
9. `test_red_team_without_policy_reruns_as_before[no_gate, unconfigured]`: recorder called once with `(command, env, deadline, slot)` as today.
10. `test_red_team_judgement_error_does_not_rerun`: `judge` raises -> unverified, discrepancy names the policy, no re-run.

### M4 `tests/test_ad1328_s2a_startup_and_doctor.py` (wiring, startup, doctor, starter, config surface) and the deliberate edits

1. `test_runtime_builds_the_gate_and_a_wrong_example_stops_startup`: `ProbOSRuntime(config=SystemConfig(), data_dir=tmp_path)` has `command_policy_gate.configured is False`; with `execution.command_policy` holding a rule whose `match` example cannot match under any dialect, construction raises `CommandPolicySelfTestError` whose text names the rule and the example.
2. `test_only_the_runtime_builds_the_gate`: AST scan of `src/probos/**/*.py`: exactly one call of `CommandPolicyGate`, inside `ProbOSRuntime.__init__` in `src/probos/runtime.py`; non-vacuity in `tmp_path` (a scratch module calling it is flagged).
3. `test_create_pool_hands_the_gate_to_shell_members`: reuse the `_FakePoolRuntime` shape of `tests/test_bf890_shell_agent_env.py:463-482` (copy it) plus `command_policy_gate = gate`: `ProbOSRuntime.create_pool(fake, "shell", "shell_command", target_size=2)` -> every member's policy refusal is observable (forbid -> refused through `_run_command`); a caller's own `command_policy_gate=other` wins; a non-shell recorder pool receives no `command_policy_gate`; a fake without the attribute builds members that run with no policy. Kills RT1.
4. `test_spawn_red_team_hands_the_gate`: as `tests/test_bf890_shell_agent_env.py:387-414`: the spawned agent does not re-run a forbidden command. Kills RT2.
5. `test_native_swe_registration_hands_the_gate`: `register_native_swe_tools(registry, runtime, command_policy_gate=gate)` -> the registered `run_command` tool refuses a forbidden command (through `registry.get_tool("run_command").invoke`), and `_wire_native_swe_harness` passes `runtime.command_policy_gate` (call it with a runtime stand-in exposing `tool_registry`, the gate, and the config the function reads; if that stand-in needs more than five attributes, assert on `register_native_swe_tools` being called with the gate via monkeypatch instead). Kills F1.
6. `test_doctor_reports_the_policy[none, passing, failing, no_config, wrong_type]`: `_CommandPolicyCheck().run(ctx)` -> OK / OK (rule count, digest, dialects) / FAIL (rule and example named, remediation) / WARN / FAIL; the check is registered as `command_policy` and `iter_checks()` order keeps `extras` immediately before `verifier_independence`. Kills D1.
7. `test_starter_policy_holds_under_every_dialect[posix, cmd, powershell]`: `yaml.safe_load(config/command_policy/starter.yaml)["command_policy"]` validates; `self_test(cfg, dialect=d).passed` for each; `curl -sS example.com` forbids with the `http_fetch` alternative and `git push origin main` escalates under each; `ExecutionConfig().command_policy.rules == ()` (opt-in). (O-S1-10)
8. `test_policy_models_are_on_the_config_surface`: `probos.config.CommandPolicyConfig is probos.config_models.operations.CommandPolicyConfig` (same for `CommandPolicyRule`); both in `probos.config_models.__all__`; `ExecutionConfig.model_fields["command_policy"]` defaults to `CommandPolicyConfig()`; `windows_program_stem` is not on `probos.config`; `SystemConfig.model_validate({"execution": {"command_policy": {...}}})` round-trips a rule.

**Deliberate edits to existing tests** (each with a one-line comment naming AD-1328 S2a):

- `tests/test_ad1328_s1_policy_models.py::test_s1_models_are_off_the_config_surface` (`:647`): replace with M4 #8's assertions under the name `test_policy_models_are_on_the_config_surface` there (and drop M4 #8 from the new file if the Builder prefers one home; keep exactly one).
- `tests/test_ad1328_s1_policy_evaluation.py::test_nothing_in_src_constructs_the_policy` (`:866`, O-S1-9): rename `test_only_the_gate_constructs_the_policy`; spare exactly: imports of a module named `command_policy` in `execution/command_gate.py`; names `CommandPolicyConfig` / `CommandPolicyRule` in `config_models/operations.py`, `execution/command_policy.py`, `execution/command_gate.py`, `config.py`, `config_models/__init__.py`; names `CommandPolicy`, `evaluate_command`, `canonical_command`, imported `policy_digest` in `command_policy.py` and `command_gate.py`; calls of `CommandPolicy` in `command_gate.py` only. Keep every non-vacuity case.
- `tests/test_ad1270e2e_operations_models.py` `EXPECTED_DUMPS["ExecutionConfig"]` (`:133-155`): add after `command_env_passthrough`, with a `# AD-1328:` comment, `"command_policy": {"rules": [], "unmatched_decision": None, "unparseable_decision": "escalate", "max_command_chars": 8192, "max_segments": 32, "max_nesting": 3},`.
- (found at install) `tests/test_ad1270e1_config_facade.py`: `test_committed_baseline_records_the_measured_surface` literals become `public_names` 307, `owned` 294, `own_models` 227, `field_definitions` 1868 (1853 + `ExecutionConfig.command_policy` + the 14 fields of the two models), `len(names)` 307, `len(models)` 228, with the AD-1328 S2a line in its field-count ledger; `test_committed_baseline_records_the_awkward_models`: `non_instantiable` gains `CommandPolicyRule` (it has required fields) and `models_with_model_config` becomes `["CommandPolicyConfig", "CommandPolicyRule"]` (frozen and closed on purpose, S1 D-models; found when the focused check reached the second assertion after M4's report); `test_check_is_green_on_the_committed_baseline`: `names=307`. These are the regenerated baseline's numbers (`scripts/check_config_facade.py --update-baseline`).
- (found at install) `tests/test_ad490_agent_wiring_security_logs.py::_FakeRedTeamAgent`: accepts and stores `command_policy_gate: object = None`, because `_spawn_red_team` now hands the gate the way BF-890 handed `command_env_passthrough`.

## What This Does NOT Change

- No approval filing, resume, standing rule or reuse store (S2b); the AD-1154 wrapper (`cognitive/agentic_dispatch.py`), `ActionApprovalStore` and `CapabilityRequestStore` are untouched.
- The permission ladder, consensus, LOTO and the broker's own decisions: the policy only refuses. `RunCommandTool.input_schema`, the shell agent's `decide()`, `_run_sync`, the red team's `_run_verify_sync`, every launch line and every BF-890/BF-892/BF-893 contract are byte-identical.
- The mesh path's broker adapter (`_MeshEffectAdapter`), the strict AD-1224 projection and the effect record schema.
- `config/system.yaml` (never edited; the starter is a separate file), the profiles manifest, `__main__.py` (doctor delegates to the registry).
- S1's module `execution/command_policy.py` and its public API.

## Do Not Build

OS-level sandboxing, network egress control (AD-1233's posture stands), an LLM reviewer (AD-1330, #1532), environment scrubbing (BF-890, #1529), a policy language beyond prefix rules, a boolean switch for the starter policy, a profile, anything of S2b.

## Acceptance Criteria

1. Sections 1-16 install mechanically; each SEARCH occurs exactly once; the three regenerations run.
2. With no rules every path is byte-identical (M2 #1, M3 #1, M3 #9) and every existing `run_command`, `ShellCommandAgent`, red-team, BF-890/892/893, AD-1316 and AD-1224 test passes unchanged.
3. `allow`, `forbid` and S2a's `escalate` produce their documented outcome through `RunCommandTool`, `ShellCommandAgent` and the red team's re-run (M2, M3); a compound command with one forbidden segment is forbidden (M2 #5).
4. A refusal names each cause, including the reason when no rule decided (M1 #8-#10, M2 #4).
5. The policy runs before broker admission and its refusal is the effect's recorded denial reason (M2 #10-#11); the AD-1224 record carries the decision and never the command (M2 #12).
6. A wrong example stops startup naming the rule (M4 #1); `probos doctor` reports the policy, its self-test, rule count and digest (M4 #6); the starter policy holds under every dialect (M4 #7).
7. Every test passes on Windows and Linux.
8. Focused gate: `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1328_s2a_gate.py tests/test_ad1328_s2a_run_command_tool.py tests/test_ad1328_s2a_shell_agent.py tests/test_ad1328_s2a_startup_and_doctor.py tests/test_ad1328_s1_policy_models.py tests/test_ad1328_s1_command_parse.py tests/test_ad1328_s1_policy_evaluation.py -q -n 0`; then `tests/test_ad544_native_tools.py tests/test_ad1179_tool_schema_golden.py tests/test_ad1316_governed_effect_broker.py tests/test_bf890_run_command_env.py tests/test_bf890_shell_agent_env.py tests/test_bf890_command_env.py tests/test_bf890_config.py tests/test_bf892_spawn_env_guard.py tests/test_bf893_process_tree.py tests/test_ad801_doctor.py tests/test_ad484_ux_adoption.py tests/test_ad1327_verifier_independence.py tests/test_ad1137_doctor.py tests/test_ad1270e2e_operations_models.py tests/test_ad1270e1_config_facade.py tests/test_config_reference_current.py tests/test_layer_boundaries.py tests/test_ad1270b_architecture_fitness.py tests/test_runtime.py tests/test_ad1184_ad_ledger.py -q -n 0`, plus every test file that matches `grep -l "AD-1224\|make_audit_hook" tests/` and `grep -l "RedTeamAgent" tests/`.
9. `scripts/check_config_facade.py --check`, `scripts/check_config_profiles.py --check`, `scripts/gen_config_reference.py --check`, `scripts/check_architecture_principles.py --check`, `scripts/check_seam_contracts.py --check`, `scripts/check_store_registry.py --check` and `scripts/gen_ad_ledger.py --check` each exit 0.
10. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Hidden Pins (enumerated)

| Pin | Evidence | Effect on S2a |
|---|---|---|
| `operations.py` imports no `probos` (`tests/test_ad1270e2e_operations_models.py:572-582`) | Section 1 adds no import | Holds. |
| `EXPECTED_DUMPS["ExecutionConfig"]` (`:133-155`, `model_dump(mode="json")`, `:398`, `:420`) | new field | Deliberate edit (Tests). |
| `config_models.__all__` equals its imports (`:606-618`) | Section 2 adds both to each | Holds. |
| Facade baseline (`scripts/check_config_facade.py:1020`, `vars(probos.config)`) | two re-exports | Regenerate (`--update-baseline`, `:1716`). |
| Config reference (`scripts/gen_config_reference.py:10`, `tests/test_config_reference_current.py`) | new field with description | Regenerate. |
| Profiles gate 3 (`scripts/check_config_profiles.py:12`) | no boolean added | Unchanged; `--check`. |
| S1 unwired scan (`tests/test_ad1328_s1_policy_evaluation.py:866`) and off-surface test (`tests/test_ad1328_s1_policy_models.py:647`) | S2a wires | Deliberate edits (O-S1-9). |
| BF-892 launch guard (`tests/test_bf892_spawn_env_guard.py:82-108`, inventory) | no launch line changes; new `build_command_env` calls feed no launch | Unchanged. |
| BF-890 spawn-env scan (`tests/test_bf890_command_env.py:111-137`) | every spawn keeps `env=` | Unchanged. |
| BF-890 runtime doubles without a gate (`tests/test_bf890_shell_agent_env.py:463-492`, `:387`; source lines cited in its mutation docstrings `:534`, `:593`, `:649-650`) | `getattr(self, "command_policy_gate", None)`; the cited lines are untouched | Unchanged. |
| BF-893 3-argument `_run_sync` stand-in (`tests/test_bf893_process_tree.py:1015-1018`) | `_run_sync` call unchanged | Unchanged. |
| Tool schema golden (`tests/test_ad1179_tool_schema_golden.py:61`, `:137`) | `input_schema` unchanged; constructor kwarg optional | Unchanged. |
| Doctor registry order (`tests/test_ad1327_verifier_independence.py:911-912`) | new check after `sandbox` | Unchanged. |
| AD-1224 record budget (`src/probos/tools/executor.py:52`, `_RECORD_MAX_BYTES = 4096`) | record at most 2,048 characters | M2 #12 asserts the payload size. |
| Architecture fitness (`scripts/check_architecture_principles.py:187-188`: 500 lines, 15 methods) | `ShellCommandAgent` 11 -> 12 methods, `RedTeamAgent` 12 -> 13, `RunCommandTool` 2 -> 4, `CommandPolicyGate` 8, `CommandGateVerdict` 6; `ProbOSRuntime` already a debt row (`docs/development/architecture-baseline.yaml:871-875`) | No new row expected; `--check`. |
| Layer boundaries (`tests/test_layer_boundaries.py`) | `execution` is outside `LAYER_MAP` (S1 Hidden Pins) | No violation expected. |
| Seam manifest (`docs/development/seams/p0-manifest.yaml`) | no seam file is touched | Unchanged (S2b touches "approval -> fulfilment -> resumed turn", `:56`). |
| Store registry | no store | Unchanged (S2b adds one). |
| AD ledger (`tests/test_ad1184_ad_ledger.py`; head window `scripts/gen_ad_ledger.py:126-139`) | Section 16's first 120 characters carry no keyword | Regenerate. |
| Facade baseline literals (`tests/test_ad1270e1_config_facade.py:1515-1554`, `:1557-1570`, `:1776-1787`) | Section 2's two re-exports and the new field/models change the measured surface (307 names, 294 owned, 227 own models, 1868 fields, 228 models; `CommandPolicyRule` non-instantiable) | Deliberate edits (found at install). |
| `_FakeRedTeamAgent` signature (`tests/test_ad490_agent_wiring_security_logs.py:33-39`) | `_spawn_red_team` passes `command_policy_gate=` | Deliberate edit (found at install). |

## Verified Against Codebase (2026-10-16, `26250c9c` + staged S1)

```
gh issue view 1530                                  -> acceptance and amendment quoted in Problem/Decisions
prompts/ad-1328-s1-command-policy-core.md:48-59     -> O-S1-1..O-S1-10;  :1991 -> O-S1-11 (A4)
src/probos/execution/command_policy.py:60-63        -> Dialect, DIALECTS, ProgramResolver
  :1208-1254  CommandPolicy(config, *, dialect); evaluate/canonical(command, *, resolve_program)
  :1144-1161  evaluate_command; :1186 self_test(config, *, dialect); :1271 policy_digest
  :207-233    CommandEvaluation(status, decision, dialect, policy_digest, segments, unparseable); matched_rules, governing
  :176-203    RuleMatch(rule, decision, justification, alternative, matched_prefix, segment, ...); SegmentVerdict(index, segment, decision, basis, matches)
  :250-260    SelfTestReport(dialect, examples_checked, failures).passed;  :237-247 SelfTestFailure.message
  :274-294    CanonicalCommand(kind, dialect, parts).key;  :751 default_dialect(platform=None)
src/probos/config_models/operations.py:1-6 docstring; :28-32 S1 comment; :33-35 CommandDecisionName, COMMAND_DECISION_RANK
  :233 class ExecutionConfig; :377-379 command_env_passthrough then its validator
src/probos/config_models/__init__.py:74-76 operations import; :230-231 __all__ neighbours
src/probos/config.py:80-82 operations import; :3870 execution: ExecutionConfig = ExecutionConfig()
src/probos/runtime.py:39-40 RedTeamAgent/ShellCommandAgent imports; :155 workspace_results import
  :621-632 __init__ sets config, _data_dir, _checkpoint_dir; :2531-2540 BF-890 shell spawn kwargs; :2543 getattr(self, "onboarding", None)
  :2618-2628 _spawn_red_team builds RedTeamAgent(command_env_passthrough=...)
src/probos/startup/agent_fleet.py:52 ("shell", "shell_command", 3)
src/probos/startup/finalize.py:1740 _wire_native_swe_harness; :1764 getattr(runtime, "tool_registry", None); :1776-1779 register_native_swe_tools(...)
src/probos/cognitive/swe_harness/tools.py:23-24 imports; :56-58 TYPE_CHECKING; :1101 RunCommandTool; :1126-1132 __init__
  :1141 refuse_undeclared_params; :1147-1160 spawn with env=build_command_env(...); :1166-1168 timeout; :1176-1185 result/except
  :1193-1198 register_native_swe_tools signature; :1235 RunCommandTool(runtime, command_env_passthrough=...)
src/probos/agents/shell_command.py:14 import; :67-71 __init__; :86-87 update_confidence; :117-125 decide not-found shape
  :168-175 strip/rewrite then loop; :183 run_in_executor(None, self._run_sync, command, deadline, slot); :199-200 _strip_ps_wrapper; :248-261 env + shells
src/probos/agents/red_team.py:16 import; :26 logger; :75-79 __init__; :294-336 _verify_run_command re-runs (:312-316) before claimed.success (:336)
  :397-398 _run_verify_sync; :416 powershell; :423 shell=True
src/probos/types.py:263-274 VerificationResult(verifier_id, target_agent_id, intent_id, verified, expected, actual, discrepancy, confidence)
src/probos/execution/effect_adapters.py:19 Tool import; :75-100 native adapter asks its tool (getattr resolve_effect_target); :182-206 _ShellEffectAdapter; :340-341 for_tool -> _ShellEffectAdapter()
src/probos/execution/effect_broker.py:252-258 adapter.prepare in prepare_tool; :318 preflight_denial_reason; :525-546 denied before invoke; :338-339 run_command -> shell
src/probos/execution/authority.py:109 _REASON_CODE_RE = [a-z][a-z0-9_]{0,127}
src/probos/tools/executor.py:52 _RECORD_MAX_BYTES = 4096; :886 broker.dispatch; :892-895 result None -> error=reason_code; :1160-1206 make_audit_hook non-strict payload
src/probos/tools/registry.py:455-467 start_permitted_effect before tool.invoke
src/probos/execution/command_env.py:98-122 build_command_env (keys from the allowlist, "PATH" at :29)
src/probos/doctor/protocol.py:14-55 CheckOutcome, CheckResult, DoctorContext; doctor/registry.py:21 register_check, :36 iter_checks; doctor/checks/__init__.py:9-30; checks/sandbox_check.py pattern
src/probos/cognitive/decomposer.py:50-57 _CAPABILITY_GAP_RE
src/probos/cognitive/agentic_dispatch.py:1458-1496 _MeshIntentTool.invoke broadcasts; :1111 inbox only for _APPROVAL_INBOX_TOOL_IDS = {"browser"} (:222)
src/probos/capability_request.py:34, :794-802 approval does not replay an action;  routers/capability_requests.py:247-256 same
src/probos/agents/http_fetch.py:93 intent http_fetch (starter alternative)
scripts/gen_ad_ledger.py:126-139 status keywords, 120-char head window
config/profiles/ (minimal, supported, experimental-approval-standing-rules) closed set
```

## Absence Verified (2026-10-16)

```
CLAIM: nothing under src/ but S1 names the policy today
RUN:   Grep "command_policy|CommandPolicy|command_gate" src/
FOUND: src/probos/execution/command_policy.py, src/probos/config_models/operations.py
HOLDS: yes

CLAIM: RunCommandTool and register_native_swe_tools each have one production caller
RUN:   Grep "register_native_swe_tools\(|RunCommandTool\(" src/
FOUND: finalize.py:1776, tools.py:1193 (definition), tools.py:1235
HOLDS: yes

CLAIM: ShellCommandAgent is constructed only through the spawner
RUN:   Grep "\"shell_command\"|ShellCommandAgent" src/
FOUND: runtime.py:1538 register_template; runtime.py:2531 create_pool; no constructor call
HOLDS: yes

CLAIM: no test pins the shell adapter's denial text or class
RUN:   Grep "shell_isolation_unproven|_ShellEffectAdapter" tests/
FOUND: none
HOLDS: yes

CLAIM: no test source-scans the AD-1224 completion dict
RUN:   Grep "error_category\": category|_bounded_record\(\{" tests/
FOUND: none
HOLDS: yes

CLAIM: no test pins the doctor check count or the full order
RUN:   Grep "iter_checks|\"sandbox\"" tests/ (doctor tests)
FOUND: test_ad1327_verifier_independence.py:911-912 (extras -> verifier_independence adjacency), test_ad484_ux_adoption.py:229 (>= 5), test_ad801_doctor.py:75 (protocol only)
HOLDS: yes

CLAIM: the red team re-runs before reading the claim
RUN:   Read red_team.py:294-345
FOUND: run_in_executor(..._run_verify_sync...) at :312-316; `if not claimed.success` at :336
HOLDS: yes (a refused command would be executed by its verifier)

CLAIM: no seam manifest entry names the files S2a edits
RUN:   Grep "src/probos/(runtime|execution/effect|tools/executor|doctor|config_models/operations)" docs/development/seams/
FOUND: none
HOLDS: yes

CLAIM: tests that construct ProbOSRuntime pass a real config
RUN:   Grep "ProbOSRuntime\((config=)?(MagicMock|Mock|SimpleNamespace...)" tests/
FOUND: none (54 calls pass a named config; sampled tests/test_channel_base.py:423-426, SystemConfig())
HOLDS: as far as the pattern reaches; a Builder who finds a runtime built on a config without `execution` stops and reports (do not add a getattr)
```

## Prior Art and Blind Spots

- **Internal.** `docs/research/codex-harness-absorption.md` rows 2-3 (S1's citation) and AD-1154's DD-2 voice rules (`agentic_dispatch.py:243-262`): refusals are error-shaped, truthful, final and must not read as a capability gap -- adopted for both frames. `_NativeFileEffectAdapter` asking its tool before admission (`effect_adapters.py:95`) -- adopted for the shell adapter. BF-890's spawn-kwarg injection -- adopted for the gate.
- **OpenAI Codex execpolicy.** A commit adding `justification` to `prefix_rule()` shows the rejected command's error carrying the rule's justification, where the model previously got a generic policy message ([execpolicy tests](https://forge.lthn.ai/core/core-agent-ide/src/branch/dev/codex-rs/cli/tests/execpolicy.rs), via search 2026-10-16); the [rules docs](https://developers.openai.com/de-DE/docs/agent-configuration/rules) state `forbidden` blocks without asking. **Adopted:** the refusal names the rule, its justification and the alternative. **Adapted:** causes also cover unmatched and unparseable segments (O-S1-11), which Codex leaves undecided. Codex's "Accept for session" ([approvals](https://www.mintlify.com/openai/codex/concepts/approvals)) is S2b's reuse; considered, deferred to S2b.
- **Claude Code permission prompts** (S1 fetched the docs 2026-10-16): ask/deny rules are evaluated before the command runs, never by the command's runner -- the same placement as S2a's preflight; "don't ask again" is S2b.
- **Reference projects** (`docs/research/reference-projects.md`, date used 2026-10-16): S1 examined Cline and re-checked Claude Code today; none re-examined here; SWE-agent, Aider, Cursor, Goose remain considered, deferred.
- **Blind spots raised by this slice.** (1) The red team's re-run is a third execution path and ran before reading the claim (fixed here). (2) With the broker on, the agent sees only the reason code (O-S2a-6). (3) A mesh `run_command` reaches every subscribed shell pool member (O-S2a-4: measure before S2b designs "exactly once"). (4) `shutil.which` on Windows reads `PATHEXT` from this process and may consult this process's directory; every misresolution fails closed for a pinned rule. (5) The child's environment is built twice (evaluation, launch) from one owner and one set of inputs; a change to this process's `PATH` between the two is not modelled. (6) S1 reason text inside a refusal may contain words the capability-gap regex matches (`cannot`); only the fixed frames are pinned. (7) A refusal on the mesh path lowers the shell agent's confidence (O-S2a-5).

## Mutation campaign of record

Run once by the orchestrator on the committed S2a tree after M1-M4 pass. Anchors are single lines that occur exactly once in the named file; replacements are literal. Record the base commit and the sha256 of each named file; a later candidate reruns only rows whose file changed.

| Id | File | Anchor | Replacement | Killer |
|---|---|---|---|---|
| G1 | execution/command_gate.py | `if not self._config.rules:  # no policy: nothing is parsed, resolved or recorded` | `if False:` | M1 #3 |
| G2 | execution/command_gate.py | `return self.status == "no_policy" or self.decision == "allow"` | `return self.status == "no_policy"` | M1 #7, M2 #2 |
| G3 | execution/command_gate.py | `entries.append(cwd if cwd else os.getcwd())` | `pass` | M1 #4, M2 #7 |
| G4 | execution/command_gate.py | `if verdict.decision != evaluation.decision or verdict.basis == "rule":` | `if True:` | M1 #9, M2 #4 |
| G5 | execution/command_gate.py | `if name not in found:` | `if True:` | M1 #5 |
| G6 | execution/command_gate.py | `frame = _FORBID_FRAME if self.decision == "forbid" else _ESCALATE_FRAME` | `frame = _ESCALATE_FRAME` | M1 #8 |
| G7 | execution/command_gate.py | `"canonical_key": self.canonical.key,` | `"canonical_key": "",` | M1 #12 |
| G8 | execution/command_gate.py | `dialect: CommandPolicy(config, dialect=dialect) for dialect in serving_dialects(self._platform)` | `dialect: CommandPolicy(config, dialect=dialect) for dialect in serving_dialects(self._platform)[:1]` | M1 #2 |
| G9 | execution/command_gate.py | `return "powershell" if (sys.platform if platform is None else platform) == "win32" else "posix"` | `return "cmd" if (sys.platform if platform is None else platform) == "win32" else "posix"` | M1 #1 |
| G10 | execution/command_gate.py | `if type(record) is not dict or set(record) != _RECORD_KEYS or record.get("schema") != RECORD_SCHEMA:` | `if type(record) is not dict:` | M1 #14 |
| G11 | execution/command_gate.py | `if config.rules:` | `if True:` | M1 #3 (construction raises through the patched `CommandPolicy`) |
| T1 | cognitive/swe_harness/tools.py | `if verdict is not None and not verdict.runs:` | `if False:` | M2 #3 |
| T2 | cognitive/swe_harness/tools.py | `return "" if verdict is None or verdict.runs else verdict.denial_reason` | `return ""` | M2 #9, #11 |
| T3 | cognitive/swe_harness/tools.py | `if gate is None or not gate.configured:` | `if gate is None:` | M2 #1 (`build_command_env` called twice) |
| S1m | agents/shell_command.py | `if refusal is not None:` | `if False:` | M3 #2 |
| S2m | agents/shell_command.py | `if gate is None or not gate.configured:` | `if gate is None:` | M3 #1 |
| R1 | agents/red_team.py | `if refused is not None:` | `if False:` | M3 #8 |
| A1 | execution/effect_adapters.py | `denial_reason=policy_denial or "shell_isolation_unproven",` | `denial_reason="shell_isolation_unproven",` | M2 #10, #11 |
| X1 | tools/executor.py | `if policy_record is not None:` | `if False:` | M2 #12 |
| RT1 | src/probos/runtime.py | `spawn_kwargs["command_policy_gate"] = gate` | `pass` | M4 #3 |
| RT2 | src/probos/runtime.py | `command_policy_gate=getattr(self, "command_policy_gate", None),` | `command_policy_gate=None,` | M4 #4 |
| F1 | startup/finalize.py | `command_policy_gate=getattr(runtime, "command_policy_gate", None),` | `command_policy_gate=None,` | M4 #5 |
| D1 | doctor/checks/command_policy_check.py | `if failures:` | `if False:` | M4 #6 |

Equivalent-mutant notes: T3 and S2m are observable only through the extra `build_command_env` call (the gate still answers `NO_POLICY`), so their killers must spy on it. No mutant can loop.

## Milestones

| M | Scope | Calls (about) |
|---|---|---|
| Install | Sections 1-16 by script; the three regenerations (orchestrator) | n/a |
| M1 | `tests/test_ad1328_s2a_gate.py` | 90 |
| M2 | `tests/test_ad1328_s2a_run_command_tool.py` | 110 |
| M3 | `tests/test_ad1328_s2a_shell_agent.py` | 80 |
| M4 | `tests/test_ad1328_s2a_startup_and_doctor.py`, the three deliberate edits, then the focused gate (acceptance 8-9) | 110 |
| Campaign | the table above, once, on the committed tree | n/a |

=== BUILDER BRIEFS ===

### Brief M1 -- `tests/test_ad1328_s2a_gate.py`

Write tests only; never edit `src/`. Target: `probos.execution.command_gate` (`CommandPolicyGate`, `CommandGateVerdict`, `NO_POLICY`, `call_site_dialect`, `serving_dialects`, `make_program_resolver`, `policy_result_metadata`, `command_policy_record_of`, `describe_command_policy`, `RECORD_SCHEMA`, `MAX_RECORD_CHARS`). Implement M1 #1-16 from `prompts/ad-1328-s2a-command-policy-wiring.md` ("Tests"). Build gates with an explicit `platform=` and an injected recording `which`; never touch the real PATH. Check fixed message frames against `probos.cognitive.decomposer._CAPABILITY_GAP_RE`. Mutants to kill: G1-G10. Run `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1328_s2a_gate.py -q -n 0`. Stop and report if a test cannot pass against the installed source; do not weaken it.

### Brief M2 -- `tests/test_ad1328_s2a_run_command_tool.py`

Write tests only. Target: `RunCommandTool` (`src/probos/cognitive/swe_harness/tools.py`), `_EffectAdapterRegistry` (`src/probos/execution/effect_adapters.py`), `make_audit_hook` / `ToolExecutor` (`src/probos/tools/executor.py`). Implement M2 #1-12. Record spawns by monkeypatching `asyncio.create_subprocess_shell` and `probos.cognitive.swe_harness.tools.ProcessTree`; no real shell. #11 copies the `strict_runtime` / `_register` / `_invoke` helpers from `tests/test_ad1316_governed_effect_broker.py` (`:879-891` shows their use). #1 is the golden: pin the exact spawn args and kwargs and the exact `ToolResult`. Mutants to kill: T1-T3, A1, X1. Run the file with `-n 0`. Stop and report rather than weaken.

### Brief M3 -- `tests/test_ad1328_s2a_shell_agent.py`

Write tests only. Target: `ShellCommandAgent._run_command`, `handle_intent`, `RedTeamAgent._verify_run_command`. Implement M3 #1-10. Replace `_run_sync` with a 3-parameter recorder (`lambda self, command, deadline=None, slot=None: ...`) and `RedTeamAgent._run_verify_sync` with a `staticmethod` recorder of `(command, env, deadline=None, slot=None)` (shape: `tests/test_bf893_process_tree.py:1015-1035`). #5 is the one host-dependent mechanism (its outcome is the same on every host); #6 patches `probos.agents.shell_command.sys.platform`. Mutants to kill: S1m, S2m, R1. Run the file with `-n 0`.

### Brief M4 -- `tests/test_ad1328_s2a_startup_and_doctor.py` and three deliberate edits

Write tests only. Implement M4 #1-8; then make the deliberate edits listed under "Deliberate edits to existing tests" (the contract named three; four more were found at install), each with a one-line `# AD-1328 S2a:` comment saying why. Copy the BF-890 fake runtimes (`tests/test_bf890_shell_agent_env.py:438-492`, `:387-414`) rather than importing them. Load the starter policy from `config/command_policy/starter.yaml` relative to the repository root. Mutants to kill: RT1, RT2, F1, D1. Then run the focused gate (acceptance 8) and the seven `--check` scripts (acceptance 9) and report every count and exit code.

## Amendments after install (2026-10-16, orchestrator; none changes a decision)

- **A1 (source).** `command_policy_record_of` (Section 4) type-checks `decision` and `call_site` as `str` before the membership tests. A list or dict value raised `TypeError`; `make_audit_hook` would then raise before `_bounded_record` and the post-hook wrapper would swallow it as `observer_failed`, losing that call's TOOL_INVOKED record. Found by the M1 Builder. Reach: injected-only (a tool's own metadata). Test ids `unhashable_decision` and `unhashable_site` were added to M1 #14 (red before the fix, green after).
- **A2 (M1 #10).** The contract's second clause for `git status; ls` did not match D7 as installed; corrected above.
- **A3 (deliberate edits).** Four more than the three named: the facade-baseline literals (three tests) and `_FakeRedTeamAgent`; two Hidden Pins rows added.
- **A4 (slicing).** Two PRs, not one (see Slicing).
- **A5 (citations).** Line numbers cited into S1's module drifted with the S1 repairs (r1 to r1e) and will again: read S1 symbols by name.
- **Observations kept for S2b and review (nothing changed for them):** (1) `ToolExecutor.match_operation_handle` also calls the shell adapter's `prepare`, so the policy preflight and its INFO line run on the matching path too; only the continuation binding, which does not depend on the params, is compared there, so behaviour is unchanged. (2) S1's pin-violation text shows the found path through `repr` (doubled backslashes on Windows); M2 #7 asserts a fragment. (3) `strict_runtime` in the AD-1316 tests is not self-contained: M2 copied seven AD-1315 helpers and its #11 needs `git` on PATH. (4) The shell agent and the red team judge different texts by design (D5): `powershell -Sta -Command "git status"` runs on the agent (the wrapper is stripped) but the red team judges the raw text and reports a policy discrepancy; a bare `python -c` is the reverse (the agent rewrites it to an interpreter path and escalates, while a bare `["python"]` allow rule allows the raw text the red team re-runs). (5) `shell_isolation_unproven` had no test before M2 #10 and #11.
