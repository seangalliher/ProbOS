# AD-1284 (BF-779, #1242 findings 1 & 2) — make the consensus gate reachable, and make its absence declared

**Status:** Ready to build
**Dependencies:** BF-860 (`0d829f48`, finding 3 — the descriptor sets the consensus FLOOR) and `b96e3b1d` (suggested-direction bullet 3 — "consensus authorizes" claims corrected). Both shipped.
**Estimated tests:** ~26 new
**Base:** HEAD `b96e3b1d`

---

## 0. What the issue got right, and the one place it has drifted

Issue #1242 says: *"`write_file` is the only intent that gets a real gate."*

**That is no longer true, and it was re-enumerated at `b96e3b1d` before this prompt was written.** There are four `submit_*_with_consensus` methods on the runtime, and three of them commit only on APPROVED:

| runtime method | line | commits only on APPROVED |
|---|---|---|
| `submit_intent_with_consensus` (generic) | `runtime.py:3984` | **no — there is no commit phase at all** |
| `submit_write_with_consensus` | `runtime.py:4268` | yes |
| `submit_mcp_invoke_with_consensus` | `runtime.py:4318` | yes |
| `submit_device_actuate_with_consensus` | `runtime.py:4474` | yes |

`mcp_consensus_proposer.py` and `device_consensus_proposer.py` both adopted the FileWriter shape — they propose and never act — and neither needs an agent-side `commit_` method, because the runtime commits. `commit_write` (`file_writer.py:136`) remains the only agent-side commit method in the tree.

**Finding 1 stands exactly as written.** `submit_intent_with_consensus` broadcasts (agents execute), evaluates quorum, red-teams, and attributes trust. No rollback, no commit phase. The vote selects among outcomes and drives trust; it does not authorise the act.

**Finding 2 stands, and is worse than the issue states.** See §1.

---

## 1. The defect the enumeration surfaced, which neither the issue nor the reporter had

**A `mcp_invoke` node in a decomposed plan is INERT. It proposes and nothing ever commits.**

The DAG executor special-cases exactly one intent by name:

```
decomposer.py:946   if node.intent == "write_file" and node.use_consensus:
decomposer.py:947       result = await self.runtime.submit_write_with_consensus(...)
decomposer.py:966   elif node.use_consensus:
decomposer.py:967       result = await self.runtime.submit_intent_with_consensus(...)
```

`device.*` escapes this because it has a **dispatch bridge** — the one and only consensus subscriber in the tree:

```
startup/finalize.py:170   runtime.intent_bus.subscribe(
                              "device_consensus_dispatch",
                              runtime._dispatch_device_consensus_intent,
                              intent_names=sensitive_intents, ...)
runtime.py:4697           async def _dispatch_device_consensus_intent(...)
runtime.py:4709               outcome = await self.submit_device_actuate_with_consensus(...)
```

**`mcp_invoke` has neither.** It is not the name-matched case, and there is no bridge. So a plan node `{"intent": "mcp_invoke", "use_consensus": true}` takes `decomposer.py:966` → `submit_intent_with_consensus` → broadcast → `McpConsensusProposer` returns a proposal (it *never* invokes, by design) → quorum is evaluated → **and then nothing calls `MCPBridge.invoke`.** The gated method exists and is wired only into the MCP workbench (`startup/finalize.py:4327`, `consensus_invoke=runtime.submit_mcp_invoke_with_consensus`).

This fails safe — no unauthorised invocation — but it is a capability that is *built, tested, and unreachable from the planner*. That is this repo's dominant defect shape: every link correct, the chain dead.

**Do not fix this by adding a second name to the `if`.** That is what §3 replaces.

---

## 2. The decision table — every `requires_consensus=True` intent, and whether its agent can propose without acting

This table is the decision. It was built by enumerating `requires_consensus=True` across `src/probos/` and reading each agent's `handle_intent`.

| # | intent | declared at | on broadcast the agent… | gated path today | reachable from a plan? |
|---|---|---|---|---|---|
| 1 | `write_file` | `file_writer.py:36` | **proposes** (validates only) | `submit_write_with_consensus` | yes — by-name special case |
| 2 | `mcp_invoke` | `mcp_consensus_proposer.py:65` | **proposes** (never invokes) | `submit_mcp_invoke_with_consensus` | **NO — inert (§1)** |
| 3 | `device_actuate` | `device_consensus_proposer.py:70` | **proposes** (never actuates) | `submit_device_actuate_with_consensus` | via the `device.*` bridge |
| 4 | `device.location` | `device_node.py:63` | — (bridge target) | `_dispatch_device_consensus_intent` | yes — subscribe bridge |
| 5 | `device.camera` | `device_node.py:70` | — (bridge target) | same | yes |
| 6 | `device.screen` | `device_node.py:77` | — (bridge target) | same | yes |
| 7 | `run_command` | `shell_command.py:52` | **EXECUTES** — `subprocess.Popen` inside `handle_intent` | none | yes → execute-then-vote |
| 8 | `run_python` | `code_runner.py:134` | **EXECUTES** — sandboxed script run | none, **and none is wanted** (§5) | yes → execute-then-vote |
| 9 | `install_package` | `code_runner.py:141` | **EXECUTES** — pip into a venv | none | yes → execute-then-vote |
| 10 | `docx_create` | `skill_framework.py:88` | **EXECUTES** — writes the file | none | yes → execute-then-vote |
| 11 | `docx_revise` | `skill_framework.py:94` | **EXECUTES** | none | yes → execute-then-vote |
| 12 | `pptx_create` | `skill_framework.py:287` | **EXECUTES** | none | yes → execute-then-vote |
| 13 | `xlsx_update` | `skill_framework.py:457` | **EXECUTES** | none | yes → execute-then-vote |
| 14 | `build_code` | `builder.py:1725` | **EXECUTES** — git branch + writes + tests | none in the mesh; a **Captain approval** gates the merge | broadcast directly at `routers/build.py:293`, bypassing consensus entirely |

Reading the table, four distinct populations fall out — and they are **not** the same problem:

- **A — proposes, and is gated.** Rows 1, 3–6. The pattern works. Leave it.
- **B — proposes, and the gate is unreachable from the planner.** Row 2. A **wiring** gap, not a design gap. Highest value, lowest risk. Fixed here.
- **C — writes a file and could propose, but has not adopted the pattern.** Rows 10–13. Each could split validate/commit exactly as `FileWriterAgent` does. Real work, but ordinary work — **not scoped here.**
- **D — physically cannot propose without acting.** Rows 7–9. The act *is* the observation: you cannot know a command's output without running it, and a "proposal" would be a no-op announcing an intention. **No commit phase is possible.** This is the population finding 2 exists to make visible.
- **E — acts, but an external human gate authorises the landing.** Row 14. A different governance story; the mesh vote is not its control.

---

## 3. The decision

**Not a fourth special case. Not a universal propose-then-commit protocol on the agent contract.**

A universal protocol would be wrong, because population **D** cannot satisfy it. Forcing `run_command` to declare a `commit_` method would produce a ceremonial no-op proposal followed by an unconditional execution — a gate in name only, which is the exact defect BF-779 was filed about. A fourth special case would be wrong because §1 shows the special cases are already the problem: one name in one `if` statement is why `mcp_invoke` is dead.

The correction is two changes that address the two halves of the finding:

1. **Reachability (finding 2).** Replace the by-name dispatch with a **runtime-owned gated-commit table**, keyed on intent name. Register `write_file` *and* `mcp_invoke`. This closes the inert path and deletes the name check in the same move, and it makes "which intents have a real gate" a single enumerable fact instead of knowledge spread across a decomposer `if`, a subscriber list, and three method docstrings.

2. **Declaration (finding 1).** Add `IntentDescriptor.consensus_mode` so an agent that cannot propose without acting **says so**, rather than having it assumed away. The runtime **records and warns; it never refuses.**

Finding 1 is not "make the generic path roll back". It cannot: population D has nothing to roll back to. Finding 1's honest resolution is that the generic path stops implying a gate it does not provide — everything that *can* be gated is routed to a gate, and everything that cannot is declared and logged as such.

---

## 4. Implementation

### Section 1 — `IntentDescriptor.consensus_mode`

`src/probos/types.py`, in the `IntentDescriptor` dataclass. Insert after `requires_consensus` (line 869) so the two consensus fields sit together. `usage_hint` (line 883) must remain the last field.

```
===SEARCH===
    requires_consensus: bool = False
    requires_reflect: bool = False
    tier: str = "domain"  # "core", "utility", or "domain"
===REPLACE===
    requires_consensus: bool = False
    # BF-779 / #1242 finding 1: what ``requires_consensus`` actually BUYS on this
    # intent. The flag says a vote happens; this says whether the vote authorizes
    # the act. Declared, never inferred -- the point is that a missing gate is
    # visible rather than assumed.
    #   "propose_commit"     the agent proposes and does NOT act; a gated runtime
    #                        path performs the commit only on APPROVED.
    #   "execute_then_vote"  the agent ACTS on broadcast; the vote scores the
    #                        outcome and drives trust, and authorizes nothing.
    #                        There is no rollback. The DEFAULT, because it is
    #                        what most consensus intents actually do today.
    #   "external_gate"      the agent acts, but an authority outside the mesh
    #                        (a human approval) gates the effect landing.
    consensus_mode: str = "execute_then_vote"
    requires_reflect: bool = False
    tier: str = "domain"  # "core", "utility", or "domain"
===END REPLACE===
```

The default is deliberately the *unflattering* one. A new consensus intent that declares nothing is honestly reported as ungated rather than silently presumed safe, and no existing descriptor changes behaviour.

Then set the mode explicitly on the intents in populations A and E — leave populations C and D on the default, which is already correct for them:

| file | line | intent | set |
|---|---|---|---|
| `agents/file_writer.py` | 36 | `write_file` | `consensus_mode="propose_commit"` |
| `agents/mcp_consensus_proposer.py` | 65 | `mcp_invoke` | `consensus_mode="propose_commit"` |
| `agents/device_consensus_proposer.py` | 70 | `device_actuate` | `consensus_mode="propose_commit"` |
| `substrate/device_node.py` | 63, 70, 77 | `device.location` / `.camera` / `.screen` | `consensus_mode="propose_commit"` |
| `cognitive/builder.py` | 1725 | `build_code` | `consensus_mode="external_gate"` |

**Do not** add `consensus_mode` to `shell_command.py`, `code_runner.py`, or `skill_framework.py`. The default already states the truth about them, and an explicit restatement would only create a second place to drift.

### Section 2 — the gated-commit table on the runtime

`src/probos/runtime.py`. Add immediately after `submit_device_actuate_with_consensus` ends (before `_store_device_consensus_episode` / `_dispatch_device_consensus_intent`; place it adjacent to the four submit methods, not among the private helpers).

```python
    def gated_commit_for(
        self, intent: str
    ) -> Callable[..., Awaitable[dict[str, Any]]] | None:
        """Return the propose-then-commit runtime path for ``intent``, if one exists.

        BF-779 (#1242 finding 2). Which intents get a real gate used to be
        knowledge scattered across a by-name ``if`` in the DAG executor, one
        intent-bus subscriber, and three method docstrings -- and the pieces
        disagreed: ``mcp_invoke`` had a gated method that no plan could reach, so
        a decomposed ``mcp_invoke`` proposed and then committed nothing at all.

        One table, enumerable, so "does this intent have a commit phase" has
        exactly one answer. Absence is meaningful: an intent that is not here
        executes on broadcast and is voted on afterwards, which is what
        ``IntentDescriptor.consensus_mode`` declares.
        """
        return {
            "write_file": self._gated_commit_write,
            "mcp_invoke": self._gated_commit_mcp_invoke,
        }.get(intent)
```

`device.*` is intentionally **not** in the table. It already has a working bridge at `startup/finalize.py:170`, and it needs a parameter translation (`device_id` + `intent_name` are lifted out of the params) that the table's uniform `(**params)` shape cannot express. Duplicating it here would create two dispatch routes to one commit. Say so in a comment.

Add the two thin adapters next to it, which exist so the table's callables share one signature (`params: dict` → result dict):

```python
    async def _gated_commit_write(
        self, params: dict[str, Any], *, timeout: float | None = None
    ) -> dict[str, Any]:
        return await self.submit_write_with_consensus(
            path=str(params.get("path", "")),
            content=str(params.get("content", "")),
            timeout=timeout,
        )

    async def _gated_commit_mcp_invoke(
        self, params: dict[str, Any], *, timeout: float | None = None
    ) -> dict[str, Any]:
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            arguments = {}
        return await self.submit_mcp_invoke_with_consensus(
            server_url=str(params.get("server_url", "")),
            tool=str(params.get("tool", "")),
            arguments=arguments,
            timeout=timeout,
        )
```

`Callable` / `Awaitable` may need adding to the `typing` import at the top of `runtime.py` — check before adding.

### Section 3 — the DAG executor uses the table

`src/probos/cognitive/decomposer.py:946`. The behaviour for `write_file` must be **byte-for-byte identical**; the only change is how the path is selected, plus `mcp_invoke` now reaching its gate.

```
===SEARCH===
            if node.intent == "write_file" and node.use_consensus:
                result = await self.runtime.submit_write_with_consensus(
                    path=params.get("path", ""),
                    content=params.get("content", ""),
                    timeout=10.0,
                )
                node.result = result
===END SEARCH===
===REPLACE===
            # BF-779: table, not a name. A by-name check gated exactly one intent
            # and left mcp_invoke -- which HAS a gated runtime path -- proposing
            # into a void, committing nothing.
            gated = (
                self.runtime.gated_commit_for(node.intent)
                if node.use_consensus else None
            )
            if gated is not None:
                result = await gated(params, timeout=10.0)
                node.result = result
===END REPLACE===
```

Guard the lookup with `getattr(self.runtime, "gated_commit_for", None)` **only if** the test suite supplies runtime doubles that would lack it — check `tests/test_decomposer.py` and the DAG-executor tests first, and prefer no guard if the doubles are real `ProbOSRuntime` instances or already carry the attribute.

### Section 4 — record and warn, never refuse

Two touch points, both non-blocking.

**(a) Startup gap register.** Where the runtime already enumerates descriptors — reuse the `self.spawner._templates` walk that `_find_consensus_pools` (`runtime.py:5740`) uses — emit exactly one `logger.warning` at startup listing every intent that is `requires_consensus=True` **and** `consensus_mode="execute_then_vote"`. One line, sorted, deduped:

```
BF-779: %d consensus intent(s) execute on broadcast and are voted on afterwards
-- the vote scores the outcome, it does not authorize the act, and there is no
rollback: %s. Intents with a real commit gate: %s.
```

This is the visible gap register the issue asks for. It is a warning because the gap is real; it is not an error because the gap is, for population D, irreducible.

**(b) Stamp the mode into the audit trail.** In `submit_intent_with_consensus`, add `consensus_mode` to the `data={...}` of the existing `intent_resolved` event-log row (`runtime.py`, the `await self.event_log.log(category="mesh", event="intent_resolved", ...)` near the end of the method), and to the returned dict. Resolve it from the registered descriptor; when the intent is unregistered, use `"unknown"` — never fabricate a mode.

An operator reading an `intent_resolved` row can then tell whether the recorded quorum authorised the act or merely scored it. Today the row looks identical either way, which is precisely how "consensus-gated" became folklore about intents that were never gated.

**The runtime must not refuse.** Design Principle #13(c): a refusal that ends the work is a capability ceiling wearing a governance costume. `run_command` cannot propose without acting, and blocking it would remove a capability while defending nothing — the vote it would be "enforcing" never authorised anything in the first place. Record it, surface it, let it run.

---

## 5. Scope guard — `run_python` does NOT get a quorum gate

**The Captain's BF-763 decision stands and this AD must not reverse it.**

`run_python` appears in the table (row 8) as `execute_then_vote`, and it stays there. Do not add a `run_python` entry to `gated_commit_for`. Do not add a `commit_` method to `CodeRunnerAgent`. Do not add a `submit_run_python_with_consensus`.

The replacement control on that path is the **per-execution audit record**, shipped as AD-1278 and extended to the mesh path by AD-1280 (`execution/audit.py`, one shared builder). The honest statement of its guarantee is already in `agents/code_runner.py`'s module docstring — *attempted* once per `run_python` turn that reached the sandbox, when `security_infra.audit_enabled` is on, `UNCONFIRMED` if the append raises. Do not upgrade that language either.

What this AD changes for `run_python` is exactly one thing: its ungated status becomes **declared and logged** instead of assumed. That is the whole intervention.

---

## 6. Tests

New file `tests/test_ad1284_consensus_gate_reachability.py`.

**The chain, not the halves.** The dominant defect shape in this repo is a producer and a consumer that each pass their own test while the seam between them is dead — which is exactly how `mcp_invoke` shipped a working gated method that no plan could reach. At least two tests must cross the seam end to end: plan node → DAG executor → gated runtime path → commit performed / not performed.

1. `test_gated_commit_for_returns_path_for_write_file`
2. `test_gated_commit_for_returns_path_for_mcp_invoke`
3. `test_gated_commit_for_returns_none_for_run_command` — population D has no gate.
4. `test_gated_commit_for_returns_none_for_unregistered_intent`
5. **`test_dag_mcp_invoke_node_commits_on_approved`** — the regression for §1. Build a one-node DAG `{"intent": "mcp_invoke", "use_consensus": true}`, drive it through the executor with an APPROVED quorum and no failed verifications, and assert `MCPBridge.invoke` was called **exactly once**. This test fails on `b96e3b1d`.
6. **`test_dag_mcp_invoke_node_does_not_commit_on_rejected`** — zero `invoke` calls on REJECTED.
7. `test_dag_write_file_still_routes_to_write_gate` — the behaviour-preservation guard; `submit_write_with_consensus` called with the same `path` / `content` / `timeout=10.0` as before.
8. `test_dag_run_command_node_takes_generic_path` — population D is unchanged.
9. `test_descriptor_defaults_to_execute_then_vote`
10. `test_propose_commit_intents_declare_it` — parametrised over `write_file`, `mcp_invoke`, `device_actuate`, `device.location`, `device.camera`, `device.screen`.
11. `test_build_code_declares_external_gate`
12. `test_run_python_declares_execute_then_vote` — pins §5. If someone later gates `run_python`, this test is where they must argue with BF-763.
13. `test_startup_warning_names_ungated_consensus_intents` — caplog; assert `run_command`, `run_python`, `install_package`, `xlsx_update` all appear.
14. `test_startup_warning_omits_gated_intents` — assert `write_file` is not in the ungated list.
15. `test_intent_resolved_row_carries_consensus_mode`
16. `test_intent_resolved_mode_is_unknown_for_unregistered_intent` — never fabricate.
17. `test_runtime_does_not_refuse_ungated_consensus_intent` — DP#13(c): `run_command` through `submit_intent_with_consensus` still returns results; nothing raises, nothing is blocked.

**Boundary coverage:** every new public method needs happy path + error/edge + empty/None. `gated_commit_for("")` and `gated_commit_for(None)` must return `None` without raising. `_gated_commit_mcp_invoke` with `arguments=None` and with `arguments="not-a-dict"` must both degrade to `{}` rather than propagate a type error into the bridge.

**Sanity anchor for the mutation-minded:** a test that only asserts `gated_commit_for("mcp_invoke") is not None` does not prove the DAG reaches it. Tests 5 and 6 are the ones that matter; if they pass against unmodified `decomposer.py`, the harness is not exercising the executor and the result is INVALID, not green.

---

## 7. What this does NOT change

- **`run_command`, `run_python`, `install_package` gain no gate.** Population D is declared, not gated. §5.
- **`docx_create` / `docx_revise` / `pptx_create` / `xlsx_update` are not converted** to propose-then-commit. Population C is real follow-up work and deliberately out of scope; converting four skill intents is not an architectural correction, it is four adoptions.
- **`submit_intent_with_consensus` keeps its shape.** No rollback is added. It cannot roll back population D, and pretending otherwise is the defect being fixed.
- **The `device.*` subscriber bridge is untouched.** It works, and it needs a param translation the table cannot express.
- **The MCP workbench wiring is untouched** (`startup/finalize.py:4327`). It calls `submit_mcp_invoke_with_consensus` directly; the DAG now reaches the same method by a different entry point. Verify no double-commit: they are separate entry points to one commit, not two commits.
- **`build_code` is not routed through consensus.** It is broadcast directly at `routers/build.py:293` and gated by Captain approval. Declaring `external_gate` describes that; it does not change it.
- **No trust, Hebbian, Shapley, or red-team behaviour changes.** AD-1272's once-per-unit-of-work accounting in `submit_intent_with_consensus` is untouched.
- Do not modify `README.md`, `docs/architecture/federation.md`, or `docs/development/roadmap.md`.

---

## 8. Building this — the working tree is poisoned

The working tree at `b96e3b1d` carries **unrelated uncommitted work** that removes `RedirectEscalation` while `tools/browser/session.py` still imports it, breaking ~423 tests. It is not yours; do not stash it, do not revert it, do not commit it.

Gate in an isolated worktree:

```powershell
git worktree add ../probos-ad1284 b96e3b1d
git diff --cached > ../ad1284.patch     # if your work is staged
cd ../probos-ad1284
git apply ../ad1284.patch
$env:PYTHONPATH = "$PWD/src"            # shadow the editable install
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q
```

`PYTHONPATH` shadowing is required — without it pytest imports the editable install from `d:\ProbOS\src` and gates the poisoned tree instead of yours.

**Known artefact:** three `test_phantom_api_precheck_*` tests fail in any linked worktree (they shell out to repo-relative scripts) and pass in the main tree. Verify that is what you are seeing, then count them as passes.

---

## 9. Tracking

- `PROGRESS.md` — BF-779 entry: findings 1 and 2 resolved as AD-1284; note that finding 2 surfaced an inert `mcp_invoke` gate the issue had not identified.
- `docs/development/roadmap.md` Bug Tracker — **only if** the Builder is explicitly asked; §7 excludes it from this change.
- `DECISIONS.md` — AD-1284. Record the shape decision and its reasoning: a universal propose-then-commit protocol was rejected because population D cannot satisfy it, and a ceremonial proposal followed by unconditional execution is a gate in name only — the exact defect BF-779 was filed about.
- Close #1242 only after findings 1 and 2 are both verified shipped. Finding 3 (BF-860, `0d829f48`) and suggested-direction bullet 3 (`b96e3b1d`) are already closed.

---

## 10. Acceptance criteria

1. `gated_commit_for` exists on the runtime, returns a callable for `write_file` and `mcp_invoke`, and `None` for everything else including `""` and `None`.
2. The DAG executor selects the gated path from the table; no intent name appears in a dispatch conditional in `decomposer.py`.
3. A decomposed `mcp_invoke` node commits exactly once on APPROVED and zero times on REJECTED. **This is the regression that must fail on `b96e3b1d`.**
4. `write_file` DAG behaviour is unchanged — same method, same arguments, same `timeout=10.0`.
5. `IntentDescriptor.consensus_mode` defaults to `"execute_then_vote"`; the six `propose_commit` intents and `build_code`'s `external_gate` are declared; `usage_hint` is still the last field.
6. Startup emits exactly one warning naming every ungated consensus intent, and it does not name the gated ones.
7. `intent_resolved` rows and the returned dict carry `consensus_mode`; unregistered intents report `"unknown"`.
8. **No intent is refused.** `run_command` through `submit_intent_with_consensus` behaves exactly as it does today.
9. `run_python` has no gate, no `commit_` method, and no gated runtime method. §5.
10. Full suite green in an isolated worktree, modulo the three known `test_phantom_api_precheck_*` artefacts.
11. Adversarial review run on the staged diff with a different model than the author, before commit, and its findings addressed.
12. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## 11. Verified against codebase (2026-08-29, HEAD `b96e3b1d`)

Every concrete claim above maps to a hit below. The issue's line numbers are from 2026-08-15 and had drifted; these were re-run.

```
grep "def submit_\w*with_consensus" src/probos/runtime.py
  3984:    async def submit_intent_with_consensus(
  4268:    async def submit_write_with_consensus(
  4318:    async def submit_mcp_invoke_with_consensus(
  4474:    async def submit_device_actuate_with_consensus(

grep "def commit_\w+" src/probos/**            # only ONE agent-side commit method
  agents/file_writer.py:136:    async def commit_write(path, content)
  knowledge/store.py:1452:      async def commit_count(self)      # unrelated

decomposer.py 946-967                          # the by-name special case
  946:  if node.intent == "write_file" and node.use_consensus:
  947:      result = await self.runtime.submit_write_with_consensus(
  966:  elif node.use_consensus:
  967:      result = await self.runtime.submit_intent_with_consensus(

grep "intent_bus.subscribe(" src/probos/**     # ONE consensus dispatch bridge; device only
  startup/finalize.py:170   (intent_names=sensitive_intents from DEVICE_INTENT_DESCRIPTORS)
  runtime.py:4697           async def _dispatch_device_consensus_intent
  runtime.py:4709               -> submit_device_actuate_with_consensus
  (others: agent_onboarding, yeoman, perception/aggregator, perception/consumer,
   runtime:654, runtime:1091, self_mod_manager -- none consensus dispatch)

grep "McpConsensusProposer|mcp_consensus" src/probos/**   # NO bridge for mcp_invoke
  startup/finalize.py:4310  import McpConsensusProposer
  startup/finalize.py:4318  register_template("mcp_consensus_proposer", ...)
  startup/finalize.py:4321  create_pool("mcp_consensus", ..., target_size=3)
  startup/finalize.py:4327  consensus_invoke=runtime.submit_mcp_invoke_with_consensus
  -> pool registered, gated method wired ONLY into the workbench, no subscriber

requires_consensus=True descriptors (14, all read and confirmed)
  agents/file_writer.py:36              write_file        proposes
  agents/mcp_consensus_proposer.py:65   mcp_invoke        proposes
  agents/device_consensus_proposer.py:70 device_actuate   proposes
  substrate/device_node.py:63,70,77     device.*          bridge targets
  agents/shell_command.py:52            run_command       EXECUTES (subprocess.Popen, L214/220)
  agents/code_runner.py:134,141         run_python, install_package   EXECUTES
  skill_framework.py:88,94,287,457      docx_create, docx_revise, pptx_create, xlsx_update
                                                          EXECUTES (create_docx called in handle_intent)
  cognitive/builder.py:1725             build_code        EXECUTES; no handle_intent on BuilderAgent;
                                                          broadcast at routers/build.py:293

types.py:860-884                       IntentDescriptor fields
  name, params, description, requires_consensus(869), requires_reflect, tier, usage_hint(883)
  -> no consensus_mode today; usage_hint is last

runtime.py:5740                        _find_consensus_pools -- the descriptor walk to reuse in §4(a)
decomposer.py:513                      _consensus_for -- BF-860's floor, untouched by this AD
```

**AD ceiling: 1283**, enumerated from `git log --all --format='%s'` (max 1283) **and** `prompts/ad-*.md` filenames (max 1283). Nothing ≥ 1284 exists in either source, nor in any prompt filename. `ad-1280-bf-787-*.md` references BF-779 but is the shipped mesh audit-record AD, not findings 1 & 2 — so this is a fresh allocation, not a revision. **AD-1284 assigned.**
