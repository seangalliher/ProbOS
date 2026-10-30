# GitHub Agentic Workflows (gh-aw) Absorption

*Sean Galliher, 2026-10-30*
*Source: GitHub Agentic Workflows, [github.com/github/gh-aw](https://github.com/github/gh-aw) (MIT). Read: the repository's documentation source for the job architecture, safe outputs, threat detection, protected files, `min-integrity`, the MCP gateway, audit and cost controls (through a web reader; `github.github.com` was blocked). The orchestrator's notes on those were checked against this note. Read directly by the Architect, as raw files: `docs/src/content/docs/reference/sandbox.md` and `reference/permissions.md`. Not read: `engines.md` and the ADR files.*
**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-30

## Purpose

The Captain approved absorbing gh-aw. This note records which mechanisms ProbOS takes, adapts, already has or rejects, and who owns each. The Architect's prior-art review searches `docs/research/` before drafting a design AD, so this note links the source to the issues below and stops rejected mechanisms being proposed again. gh-aw appears here only as a technical design reference.

**Outcome.** One new defect: the protected-files comparison found that ProbOS's runtime writers protect only the Constitution and the live config (BF-943, #1707). Everything else maps to an existing owner or is already in place. The main design lesson, a commit point that holds the write authority, is already ProbOS's principle (`docs/development/deterministic-ship.md` section 2). gh-aw is an independent production instance of it, worth one line of prior art there.

## What gh-aw is

gh-aw compiles a markdown workflow with frontmatter into a GitHub Actions lock file. The workflow runs a coding-agent engine: Copilot, Claude Code, Codex, Gemini or Pi. It "complements existing CI/CD; it does not replace it." Each run is a chain of jobs:

1. **Pre-activation:** role check, deadlines.
2. **Activation:** sanitizes event text and validates the lock file against its source.
3. **Agent job:** a read-only `GITHUB_TOKEN`, with write operations "handled through safe outputs" (`permissions.md`). It runs in a sandbox: a Docker network whose default profile has no route to host services; the Docker socket is hidden, so "agents cannot spawn containers"; user paths (`$HOME`, `$GITHUB_WORKSPACE`, `/tmp`) are read-write and system paths read-only (`sandbox.md`). Egress goes through the AWF firewall (iptables and Squid) with a domain allowlist. The agent writes `agent_output.json` and a patch; it changes nothing on GitHub itself.
4. **Detection job:** AI checks for `prompt_injection`, `secret_leak` and `malicious_patch` over the agent's output, patch and prompt.
5. **Safe-output jobs:** each holds one scoped write permission. Each validates a typed request (for example `{"type":"update_issue",...}`) against allowlists and sanitizes it before acting.
6. **Conclusion job.**

gh-aw states its own limits: "at your own risk"; detection is "defense in depth, not proof"; "Domain allowlisting constrains destinations, not the safety of every request to an allowed service"; the MCP gateway agent ID "is not a strong security boundary". Versions >=0.83.3 and <0.85.4 were retired after GHSA-8h78-hpm7-29gg.

## Mechanism table

Status is one of **absorb** (new work), **adapt** (fold into an existing owner), **already have** or **reject**. Anchors were checked on `main` `6f7888a2`.

| # | gh-aw mechanism | ProbOS anchor (verified) | Status | Owner |
|---|---|---|---|---|
| 1 | **Safe outputs.** The agent holds no write permission. It emits typed requests, and a separate job with scoped authority validates and performs them. | The same split: `FileWriterAgent` proposes and `commit_write` runs after the vote (`agents/file_writer.py:38`, `:146`; `runtime.py:5399-5414`); the opt-in governed effect broker classifies and authorizes each effect before it runs (`execution/effect_broker.py:243-270`, `:322-359`); principle in `deterministic-ship.md` section 2 ("commit point") | **already have** (principle and partial routes). Strict effects are opt-in: `protected_execution.enabled` and `effect_broker_enabled` default `False` (`config.py:3860`, `:3867`) | AD-1316 (effect broker); the commit-point checks in `deterministic-ship.md` section 5 |
| 2 | **Protected files**, on by default for pull-request outputs: manifests, `.github/`, `.agents/`, engine instruction files (`AGENTS.md`, `CLAUDE.md`, `.claude/`, `.codex/`), `CODEOWNERS`. Policies: `request_review` (default), `blocked`, `allowed`, `fallback-to-issue`. | Builder: `FORBIDDEN_PATHS` (`cognitive/builder_paths.py:58-63`), plus worktree isolation and the Captain's merge review (BF-897, `builder_paths.py:447`; `build_dispatcher.py:236-240`). That is gh-aw's `request_review` in effect. Fix loop: `FIX_LOOP_PROTECTED_PATHS` (`:280-291`). Runtime writers: only the Constitution (AD-1344, `:149`) and the live config and vault (BF-911, `security/file_access.py:316`) | **absorb**, for the runtime writers only. Gap verified: `write_file`/`edit_file`, `FileWriterAgent` and the office writers can rewrite the other standing-orders tiers, `config/ontology/`, `config/sealed_modules.yaml`, the instruction files and lock files in the running checkout | BF-943 (#1707), filed from this review. A review flag on a build's diff that names protected files, like `request_review`: considered, deferred |
| 3 | **Threat detection job** (prompt injection, secret leak, malicious patch) over output, patch and prompt. | Built detectors: `security/threat_detector.py` (AD-455), `cognitive/memory_security.py:60` (`PROMPT_INJECTION_PATTERNS`), `security/contagion.py:41`. Not all of them run on every path | **adapt**: run the built detectors at the seams; keep refusal, not warn (row 13) | AD-1353 (#1659) |
| 4 | **Separate detection budget** (400 credits): the checker's spend is not taken from the worker's. | Turn-cost accounting (`cognitive/turn_cost.py`) has no reviewer-specific reserve | **adapt**, when AD-1353 places a model-based check: give the checker its own budget, so a run that exhausted its own cannot also skip its review | AD-1353 (#1659) |
| 5 | **Cost ceilings**: `max-ai-credits` per run, `max-daily-ai-credits` per workflow, `max-turns`, timeouts. | Admission service in shadow mode (`admission/service.py:37`, `admission/store.py:231`); loop iteration caps (`config.py:3157`) | **adapt** the per-run and per-day ceiling shape; reject the cooperative enforcement (row 14) | AD-1346 (#1601, #1604) |
| 6 | **Pre-activation role check** (who may trigger a run). | Chain of command and the capability seam for visitors: BF-903 checks a visiting officer's capabilities where it acts (`PROGRESS.md`, BF-903 entry; `config_models/crew.py`) | **already have** | AD-701 / BF-903 |
| 7 | **`min-integrity`**: GitHub content is filtered by author trust and merge status before the engine sees it; `approved` is automatic on public repos. | Provenance and store-time screening: `cognitive/provenance.py:43`, `config_models/crew.py:159`, `cognitive/episodic.py:1464`; visitor capability names (BF-903) | **adapt**: one idea to carry into visitor intake. Untrusted authored text is filtered *before* it enters a prompt, not only flagged after | AD-701 / BF-903 (visitors); AD-1353 (#1659) for the seam |
| 8 | **Activation sanitizes event text.** | `security/input_validator.py:12-21` (validator with threat signals) | **already have** | AD-455 |
| 9 | **Lock-file validation**: the compiled workflow is checked against its source before the run. | Frozen-prompt hash rule (`config/standing_orders/architect.md:21`); command-policy digest and self-test (`execution/command_policy.py:90-93`; `probos doctor`) | **already have** (same shape: run what was reviewed, by digest) | AD-1328 (#1530) |
| 10 | **Egress firewall** (Docker network, iptables, Squid, domain allowlist; firewall logs of every request). | Soft sandbox egress by decision (AD-1233), with AD-1221's fetch broker as the governed way out; recorded in `codex-harness-absorption.md` (Rejected, network proxy) | **already have** (governed fetch). An enforcing proxy is still the ready design if the threat model becomes hostile code | AD-1221 / AD-1233 |
| 11 | **MCP gateway**: containerized servers, per-server tool allowlists. | AD-1241 bounded, authorized MCP selection per run (`cognitive/agentic_dispatch.py:3031-3034`) | **already have**. gh-aw does not claim runtime enforcement of its per-server allowlist, and says its gateway agent ID is not a strong boundary | AD-1241 |
| 12 | **Audit**: per-run artifacts (prompt, output, patch, engine and firewall logs); `gh aw audit` with stable finding codes; threat reasons kept out of finding text "because they may contain sensitive agent output"; OpenTelemetry. | Tool traces (AD-1203), durable events (AD-1195), constant refusal log lines carrying a reason code and no caller text (AD-1344 D20, BF-911 D15-D17, `DECISIONS.md:463`, `:476`) | **already have**. Stable codes plus no payload in the finding is ProbOS's reason-code practice. A run-level audit view over the existing evidence is AD-1329's reducer (`codex-harness-absorption.md` row 4) | AD-1329 (#1531) |
| 13 | **Detection in warn mode by default** (`continue-on-error: true`): findings annotate, branch pushes become review PRs, other operations abort; strict mode blocks. | ProbOS's propagate tier for security: a guard refuses (engineering principles, three-tier exceptions) | **reject** | — |
| 14 | **Cooperative admission**: external admission is "cooperative, not a hard spending cap". | AD-1346 is shadow first, then enforcing | **reject** as an end state. A ceiling ProbOS publishes must be enforced at its commit point (`deterministic-ship.md` section 5, check 6) | AD-1346 (#1601, #1604) |
| 15 | **Agent merge and approve** (experimental `merge-pull-request`, `approve-workflow-run`). | The Captain merges builds (`build_dispatcher.py:236-240`); the orchestrator never waives a gate (`.github/agents/orchestrator.agent.md`, Delegated AD Execution) | **reject** | — |

## Bearing on the deterministic ship

`docs/development/deterministic-ship.md` section 2 says a state-changing proposal passes through "a commit point: one owner, in ordinary code, that checks authority and evidence, records who did it, and keeps the history". gh-aw's safe outputs are that design applied to a CI agent:

- the agent job has no write authority (the "probabilistic crew");
- each safe-output job is one owner with one scoped permission, validating a typed request (the commit point);
- the patch, the request and the logs are kept per run (the history).

It also confirms section 5's "No side door" check (check 2) from the other direction. gh-aw has to name protected files because the agent's patch is itself a side channel into the next run's instructions. ProbOS's equivalent side door, a runtime writer reaching the instruction and governance files, is the gap this review found.

**Proposed one-line addition** to the References of `deterministic-ship.md`. Not applied here; the doc's owner decides:

> - In agent tooling, GitHub Agentic Workflows ([github/gh-aw](https://github.com/github/gh-aw)) applies the same split: the agent job holds read-only credentials and emits typed requests, and separate "safe output" jobs hold the scoped write permission, validate each request and act.

## Explicit rejections

These three were rejected for a reason. Do not propose them again without new evidence.

1. **Warn-by-default detection.** gh-aw's own docs call detection "defense in depth, not proof". Making a finding advisory by default turns a guard into a log line. ProbOS detectors that guard a write refuse it (the propagate tier). A detector too noisy to refuse with is a detector to fix, or to run in shadow and measure (the AD-1346 pattern), not to ship in warn mode.
2. **Cooperative admission as a spending cap.** A cap the caller may ignore is not a cap. AD-1346 measures in shadow first, and its enforcing mode refuses at the admission seam.
3. **Agent merge and approve.** An agent that can merge its own change or approve its own workflow run collapses proposal and commit into one actor, which section 2 of `deterministic-ship.md` forbids. The Captain's merge review stays the commit point for builds.

## Reference-project upkeep

`reference-projects.md` gains a gh-aw row under Coding-agent harnesses (90 days). Overdue rows in that section on 2026-10-30, considered and deferred (not relevant to this review): SWE-agent (2026-03-20), OpenCode (2026-05-08), Cursor (2026-06-13).
