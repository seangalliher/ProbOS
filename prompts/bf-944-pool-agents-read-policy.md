# BF-944 (#1717): Pool-built file reader, directory list and file search agents get the runtime, so an operator's security_infra.read_roots confines them; their link entries and search matches are decided by the read policy

**Drafted by:** `Architect` (GitHub Copilot fallback for the unavailable Claude Code Architect), 2026-11-08; v2, re-anchored on BF-961's head, 2026-11-08
**Status:** ready to build on `origin/main` once BF-961 (#1774) has merged; anchored on its head `ae0cdd12` (`D:\ProbOS-worktrees\bf961-build`, read only; the head moved from `d9b2a9da` during this consult, note 1). **Oracle:** no pytest run (a read-only consult); section 11 lists what a script measured.
**Base blobs (`ae0cdd12`):** `runtime.py` `2f09a088044844ef826b4f5efe2809d6274d878a`; `security/file_access.py` `885f94e66b71d08ccab451ca56b6d857bef44235`; `agents/file_search.py` `6e3ce74ca7e481cbd60fce680c54fe1e447a4e78`; `agents/directory_list.py` `eba694305f5ef616f0f535f5df507d73f825ec4b`; `config.py` `71d1841b4b6bfe51ef90a4863dc8c82ed5268023`; `PROGRESS.md` `ce07328547e1eab733d3881cec689f3aee4a787f`; `DECISIONS.md` `db30997c9eddd437a5428498147d4115d2909e26`; `tests/test_hebbian_source_key.py` `fad01150d530e5d6774d22606dcd17085367d779`; `tests/test_escalation.py` `dca22b5c0249b1a39ac320b686884c023edd6c62`; `tests/test_runtime_discovery.py` `0087140bd72b5585a95c3e96ab58d55cf69d2c6b`. `agents/utility/stored_list.py` (`e5900eb3e41f45e59aca2e48623a092c6e7bcd63`) must exist: T13 imports it. Before building, `git rev-parse HEAD:<path>` prints these; if one differs, each SEARCH must still occur exactly once, else a hard stop for the Architect.
**Orchestrator oracle and amendments (2026-11-09):** BF-961 has merged (`origin/main` `8dced555`, PR #1776); the build tree is that commit, and the eleven base blobs above, listed on BF-961's head `ae0cdd12`, are equal on it (`git rev-parse origin/main:<path>`; BF-961's later commit changed a test comment and its own contract only). The worktree named in the Status line and in section 11 (`D:\ProbOS-worktrees\bf961-build`) is removed; its content is in `8dced555`. Every block (the seven pairs of P2-1 to P2-5, N2-1, the three pairs N2-2 to N2-4, the two tracker pairs and the new test file) was applied by tool, each SEARCH matching exactly once. G1 at M1: 5 passed, 4 skipped (the four symlink cases, WinError 1314) and 25 xfailed; with `--runxfail` the 25 fail at 13 lines of the file, each an effect assert and none a premise line (the file has 14 premise asserts, which pass on the base). M0: the collected counts of the 27 files of G2 are equal on the M1 and M3 trees (884 cases; the new file 34). G2 on the M3 head: 865 passed, 19 skipped (`-n 0`); the new file 30 passed and 4 skipped; `check_architecture_principles.py --check`, the ledger generator's `--check` and the ledger test (33 passed) are clean. A census of section 9's ten rows (the new file alone; baseline 30 passed and 4 skipped) killed all ten. **Two text changes** after the Architect's decision of 2026-11-09 on note 5 (recorded on #1717): L3's premise is corrected (the search has no `await`, so the 5 s TTL cannot cut it; the cost is accepted as drafted, and the cache is a follow-up recorded in #1754, not filed as an issue), and section 13 gains property 7.
**Amendment A1 (2026-11-09, after review round 1 by `gpt-6.1-sol`, verdict READY, no finding in the diff):** the review qualified two statements of this contract; it found nothing in the code, the tests or the trackers. L7 said a consensus-verified read the policy refuses reads `Agent claims failure but file exists and is readable`; the runtime's consensus path builds its verification tasks from successful results only (`runtime.py:4810`), so an ordinary refused read does not reach a verifier there (a verifier called directly gives that answer): L7 now says so. Section 13's property 7 said no test counts `Path.resolve` calls, which is false for the unchanged workspace tests (`test_ad1240_workspace_results.py:182-191`): it now speaks of the tests BF-944 adds or changes. Both are corrected in the commit `BF-944 A1`; no code, test or tracker changes.
**Dependencies:** BF-961 (merged first), BF-758 (the read policy), BF-908, BF-948, AD-1346 M3e1. **Tier:** M1 STANDARD; M2 HIGH (a security control); M3 STANDARD.
**Estimated tests:** one new file, 16 functions, 34 cases (win32 without symlink privilege: 5 pass, 4 skip, 25 xfail at M1); one block in each of three existing test files (N2-2 to N2-4). **BF number:** BF-944, held by #1717; none allocated (A6). Working copies are CRLF and SEARCH text is LF. Where prose and a block differ, the block wins. Apply the pairs with the `edit` tool one at a time, whole block, in label order.

## 1. Problem

1. **No runtime.** `startup/agent_fleet.py:45-57` builds `filesystem` (`file_reader`), `directory` (`directory_list`) and `search` (`file_search`) with `create_pool_fn(pool_name, agent_type, target_size=size, agent_ids=ids)` (`:57`); `introspect` (`:61`) and `code_runner` (`:69-72`) pass `runtime=runtime`. `create_pool` adds `runtime=self` for the shell and code-search types (`runtime.py:2668-2672`). `ResourcePool` keeps its spawn kwargs (`pool.py:70`) and re-sends them on start (`:308`), recycle (`:209`), refill (`:533-534`) and add (`:620-622`); `BaseAgent.__init__` reads `kwargs.get("runtime")` (`substrate/agent.py:55`). No other code builds these agents (A1).
2. **The cost.** `FileReaderAgent._confine` (`file_reader.py:113-119`), `DirectoryListAgent._list_directory` (`directory_list.py:99-110`) and `FileSearchAgent._search_files` (`file_search.py:112-131`) call `resolve_for_runtime(path, getattr(self, "_runtime", None))`. With None, `permitted_read_roots` is `[]` (`file_access.py:416-441`): `read_roots` does not apply and the floor is the platform data directory plus two default config files (`:619-631`, `:455-492`), not the runtime's `data_dir`, `config_path` and workspace.
3. **The comment's cases.** The lister reports `entry.stat()` and `entry.is_dir()`, which follow a link (`directory_list.py:120-127`); the search names `p.rglob(pattern)` (`file_search.py:141`) or `iter_files(p)` filtered by `f.match(pattern)` (`:143-147`) and does not re-check a match.
4. **Reach.** A DM turn's `[MESH read_file|list_directory|search_files ...]` (`cognitive/dm/reply_pipeline.py:73-77`, `:1374`); the bundled agents (`read_stored_list`, `agents/utility/stored_list.py:49`, for the todo and scheduler agents and, at `organizer_agents.py:124`, the note agent; `_mesh_list_dir`, `organizer_agents.py:56-64`); the Captain's plans through `submit_intent`; the red team's re-reads (L7). A4 enumerates the callers.

## 2. Solution

`create_pool` hands itself to a `file_reader`, `directory_list` or `file_search` pool made without a `runtime` keyword (P2-1), beside M3e1's rule; the pool keeps it for recycle, refill and add. `security/file_access.py` gains a public `ReadFloor` (P2-2): the three root lists `resolve_for_runtime` composes, built once, with `permits(path)`. `FileSearchAgent` keeps a match when `permits` admits it (P2-3); `DirectoryListAgent` reports a link entry whose target `permits` refuses as an entry that cannot be read (P2-4). The `read_roots` comment in `config.py` names the `~/.probos` consequence in BF-961's words (P2-5). Three existing tests that read inside a runtime's data directory read outside it (N2-2 to N2-4).

## 3. Decisions

**D1. How the three pools get a runtime** (DRY, constructor injection). **Chosen:** a per-type rule in `create_pool`, beside M3e1's: the four builds `pool.py` makes (start, recycle, refill, add: `:308`, `:209`, `:533-534`, `:620-622`) re-send the kwargs, so all four carry it (A1 lists the spawn sites); a caller's `runtime` wins; `agent_fleet.py` is untouched (three tests read its source: A3; BF-961's section 8 expects the change there, and the effect it relies on is the same: T13); one block reverts it. **Rejected:** `runtime=runtime` at the fleet rows (the loop `:55-57` is shared with shell, http and system; a later `create_pool("x", "file_reader")` is unwired again); a runtime for every pool type (wider: the writer pool would take one, its floor is F-228); a module-level locator (hidden state shared by two vessels).

**D2. What changes** (backward compatibility).

| Vessel | Effect on these agents |
|---|---|
| Default or Docker (`PROBOS_DATA_DIR=/data`, `Dockerfile:33,50`); `read_roots` empty | None to the floor: `runtime.data_dir` is `_platform_data_dir()` (`runtime.py:665`, `__main__.py:596-597`), `config_path` a default |
| `--data-dir X` (the cluster launchers); `read_roots` empty | The platform dir -> X: X's vault and governance DBs closed, the platform dir readable, as for the readers that have the runtime |
| `--config Y` or a custom `workspace_root`; `read_roots` empty | Y readable -> refused (`__main__.py:649`); the configured workspace exempt instead of the default |
| Any vessel; `read_roots` empty | A search match the policy refuses is dropped (as BF-908's code search and BF-948's `ListFilesTool` drop theirs); a link entry whose target it refuses is `unknown`/0, the lister's own unreadable-entry shape (new for a link) |
| `read_roots` set, `~/.probos` unlisted | The todo and scheduler agents answer `Could not read ...; nothing was changed or saved.` and write nothing, a first save included (BF-961 L4 and its T2; T13 pins the read they depend on); the note agent's `read` answers `not found`, its listing shows `None`, and its `save` still writes (floor F-228; BF-961 L5) |

**Chosen:** accept: the floor is the runtime's, as for the readers that have it (the issue counts the platform floor as part of the defect; A4 found no caller that reads a path the move of the floor newly refuses; T2, T4, T7 pin it; the `read_roots` case is the last row). **Rejected:** keeping the platform floor while roots are empty (a `--data-dir` vessel's vault stays readable); a switch (a field for a hole). A vessel started with `--data-dir ~/.probos` is not shipped (A4); its notes would be refused.

**D3. The two comment cases.**

| # | Lister: a link entry (`is_symlink()` or `is_junction()`) whose target the policy refuses | Judgement |
|---|---|---|
| 1 | `{"name", "type": "unknown", "size": 0}`; other entries, and a link the policy admits, as before (chosen) | The existing unreadable-entry shape (`directory_list.py:128-133`): no new shape, neither kind nor size leaves, `count` keeps its length; a junction is no symlink, so it is asked too |
| 2 | Omit the entry; or decide every entry | Hides an entry of a readable directory and changes `count`; a `resolve()` per entry, and `config.yaml` in `~/.probos` would list as unreadable |
| 3 | Report the link's own `lstat` size | A POSIX symlink's size is its target's path length: a leak |

| # | Search: a match | Judgement |
|---|---|---|
| 1 | Resolved and decided by a `ReadFloor` built after the walk; a refused match is dropped, not counted; no pattern rule (chosen) | One rule closes `..`, a link and the floor on both engines; with empty roots a match goes when `resolve_read_path` refuses it for one of its other reasons (`file_access.py`: `:353` a malformed path, `:364` an unresolvable one, `:368` a credential vault name, `:378` a floor it cannot verify, `:384` a path in the floor); the Captain's mechanism |
| 2 | Also refuse a `..` or anchored pattern (BF-948 LF2) | With empty roots a `..` pattern that lists a sibling directory today would be refused, against the issue's acceptance "with it empty nothing changes" |
| 3 | `resolve_for_runtime` per match; or import `code_search._ReadFloor` | Recomputes the roots per match (BF-908 measured 200 matches costing 1,000 `resolve()` calls); a private name across modules (BF-948 LF1 rejected it; BF-908's tests patch it: L8) |

`reader_spelling` is not applied: a match is read by `FileReaderAgent` (`Path.read_text` after `resolve_for_runtime`), not by the verified reader, and `reader_spelling` returns None for a path with a `..` part (`file_access.py:213`), so the rule would drop a `..` match even with empty roots (L5).

| Policy outcome for a match or link entry | Search | Lister |
|---|---|---|
| Refuses (`FileAccessDenied`) | The match is dropped; one INFO line carries a count | The entry is `unknown`, size 0 |
| Cannot decide: `OSError` | `success False`, `error=str(exc)`: the search fails whole (T12) | The entry is `unknown`, size 0 (T12) |
| Cannot decide: another `Exception` | As `OSError` | `success False`, `error=str(exc)`: the listing fails whole |
| `CancelledError`, other `BaseException` | Propagates | Propagates |

**The effect on each result shape and consumer** (`handle_intent` forwards `success`, `result` and `error`, not the agent's `count` or `base_path`: `file_search.py:54-61`):

| After M2 | DM seam (`reply_pipeline.py:1549-1552`, `:1609-1618`) | Todo and scheduler agents (BF-961); note agent | Plans, consensus, red team | Pool health, Hebbian |
|---|---|---|---|---|
| A read, stat, listing or search whose base the policy refuses: `success False`, its words | `(The <intent> lookup came back empty (<words>).)` (T11, all three intents) | `read_file`: FAILED, so the intent ends before the model with no write, an absent path included (T13). Note agent: `Note '<title>' not found.`; `list`: `None` | `error=<words>` in the reflect prompt (`decomposer.py:477`, `:757-764`); three refusing members vote REJECTED on a consensus read (measured); the red team re-reads by a bare `Path` (L7) | A failure outcome: from the starting confidence 0.8 (`agent.py:38`), nine failures in a row take a member below 0.2 (`:125`, `:132`; `config.py:222`; the reader calls `update_confidence` at `file_reader.py:73`); the pool recycles it with its runtime (T9); the Hebbian weight of the intent-to-agent edge stays 0.0 (measured; N2-2) |
| A listing whose link entry's target the policy refuses | The entry `{"name", "type": "unknown", "size": 0}` in the JSON list (T3, T4 pin it) | Not read; the note agent's `list` shows it in `str(result)` | The shape of an entry whose `stat()` failed | A success |
| A search whose match the policy refuses | A shorter list; an empty one renders `[]` (T5 to T7) | Not read | A shorter `result` | A success |
| A path the policy admits | Unchanged (G1, G2) | Unchanged: FOUND or MISSING (T13) | Unchanged | Unchanged |

**D4. The trust score `info()` reports** (the issue asks the test to state it). With a runtime, `info()` reads `trust_network.get_score` (`agent.py:171-175`) instead of `TRUST_DEFAULT`. A4 found no reader of a pool member's score beyond paths that overwrite it (`introspect.py:360-361,:501-502`) or carry it (`pool.info()` -> `runtime.status()` `:6416` -> `GET /api/status`). T10 states it.

**D5. Tests.** The real `create_pool` (unbound, over a runtime double after `tests/test_ad1346_admission_sink_wiring.py`'s), the real agents and policy, `tmp_path`, no network; a control round proves each premise. T13 crosses the seam BF-961's T2 stands in for: the pool's readers behind a real bus, read through `read_stored_list`. **Rejected:** a source-text test (BF-758's own is what let the pool go unwired); unit tests of `ReadFloor` alone; running the todo agent in T13 (BF-961's T2 does, with readers built by hand).

**D6. Trackers and documents.** PROGRESS.md, DECISIONS.md and the ledger (M3), after BF-945's and BF-961's entries; the roadmap is not edited (`git grep BF-944` finds `DECISIONS.md:1422`, BF-961's PROGRESS entry and no roadmap row). `config.py`'s `read_roots` comment gains BF-961's L4 sentence (P2-5). `git grep read_roots` outside `src`, `tests` and `prompts` finds a field row (`config-reference.md:1471`), the facade baseline, tracker entries, a research note and `scripts/replay_approval_tiers.py`: none says these pools are exempt.

**D7. The existing tests M2 breaks.**

| Test | Reads | M2's effect (script replay on a real runtime, section 11) | Edit |
|---|---|---|---|
| `test_hebbian_source_key.py`, fixture `runtime` (4 tests) | `tmp_path/data/readable.txt`; data dir `tmp_path/data` | Refused (`path is protected: ...`): the weight of `read_file` stays 0.0 after one and after two reads, so `test_hebbian_uses_intent_name_as_source` and `test_hebbian_reinforcement_across_calls` fail; the consensus and event tests pass | N2-2: the file moves to `tmp_path/readable.txt` |
| `test_escalation.py::TestRuntimeEscalation::test_escalation_resolved_stored_in_episodic_memory` | `tmp_path/ep_test.txt`; data dir `tmp_path` | `completed_count` 0, `failed_count` 1: `assert result["completed_count"] == 1` fails | N2-3: `data_dir=tmp_path / "data"`, as the class's `started_runtime` has it (`tests/fixtures/runtime_factory.py:104`) |
| `test_runtime_discovery.py::TestRuntimeDiscovery::test_existing_nl_processing_unchanged` | `tmp_path/data/test_read.txt`; data dir `tmp_path/data` | Refused (`failed_count` 1), yet `node_count >= 1` holds: it passes without a successful read | N2-4: the file moves to `tmp_path/test_read.txt`, so the test keeps its premise |

**Rejected:** `xfail` or skip (hides a real consumer effect and loses two Hebbian assertions); listing the data directory in `read_roots` (the floor wins over the roots); keeping the platform floor (D2). Another existing test that fails at the broad gate with a read path inside a runtime's data directory is this class: a hard stop for the Architect, not a Builder edit.

## 4. Milestones and gates

| M | Pairs | Gate |
|---|---|---|
| M1 | N1-1 | G1 |
| M2 | P2-1 to P2-5, N2-1 to N2-4 (N2-1 removes the marker) | G2 |
| M3 | P3-1, P3-2, ledger | G3 |

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`. **M0:** on the head, record the collected count (`--collect-only -q`) of every existing file named in G2.

- **G1.** `PY -m pytest tests/test_bf944_pool_agents_read_policy.py -q -n 0 -p no:randomly`. **Expected on win32 without symlink privilege (this host: WinError 1314): 5 passed, 4 skipped, 25 xfailed;** with the privilege 6 passed, 28 xfailed (on POSIX the two T6 directory cases skip). Any other split is a hard stop. The marker carries `raises=AssertionError, strict=True`: another exception, or an XPASS, is a FAIL. Then once with `--runxfail`: each failure must stop at the `assert` section 6 names, not at a premise line.
- **G2.** `PY -m pytest tests/test_bf944_pool_agents_read_policy.py tests/test_bf758_file_read_confinement.py tests/test_bf908_floor_and_children.py tests/test_bf948_list_files_read_policy.py tests/test_bf953_read_floor_spellings.py tests/test_bf961_unreadable_stored_list.py tests/test_file_reader.py tests/test_expansion_agents.py tests/test_ad990_file_walk.py tests/test_ad869_mesh_read_inline.py tests/test_pool.py tests/test_spawner.py tests/test_bf846_pool_health_containment.py tests/test_bf879_designed_agents_start_probationary.py tests/test_bf890_shell_agent_env.py tests/test_ad1346_admission_sink_wiring.py tests/test_ad152_regressions.py tests/test_runtime.py tests/test_consensus_integration.py tests/test_ad1185_config_profiles.py tests/test_hebbian_source_key.py tests/test_escalation.py tests/test_runtime_discovery.py tests/test_ad1346_admission_effect_census.py tests/test_ad1346_admission_file_write_census.py tests/test_ad1346_admission_store_family_census.py tests/test_layer_boundaries.py -q -n 0 -p no:randomly`, then `PY -P scripts/check_architecture_principles.py --check`. **Expected:** the new file 30 passed and 4 skipped (34 passed with the privilege); every other file 0 failed, collected counts equal M0; the check clean (never `--update-baseline`). `test_ad1185_config_profiles.py::test_supported_profile_boots_and_reads_a_file` is the CI smoke: a real boot reading a file through the three pools, now with the runtime (data dir `tmp_path/data`, file in `tmp_path`). `test_bf961_unreadable_stored_list.py` builds its readers by hand and names no pool or factory (A7), so M2 should leave it as it was. Other test files naming these agents or `file_access` are left to the broad gate (L9).
- **G3.** `PY -P scripts/gen_ad_ledger.py`; then `PY -P scripts/gen_ad_ledger.py --check`; then `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`.
- **Harness rule.** No source change made to pass a test, no skip, no loosened assertion. A failing case of the new file at G2, or an existing test failing beyond D7's three, goes back to the Architect. The broad gate runs once, in the main session, with `--receipt`.

## 5. Commit messages

- **M1:** `BF-944 M1: tests for the pool-built file reader, directory list and file search agents applying the runtime's read policy, xfail until built (#1717)`
- **M2:** `BF-944 M2: create_pool hands the runtime to the file reader, directory list and file search pools; the lister and the search decide link entries and matches by the read policy; three tests stop reading inside their data directory (#1717)`
- **M3:** `BF-944 M3: trackers and ledger (#1717)`; its body ends with the line `Closes #1717.`

## 6. Tests (`tests/test_bf944_pool_agents_read_policy.py`)

| Id | Cases | Covers (and the boundary it pins) | xfail until |
|---|---|---|---|
| G1 | 3 | **Guard.** Empty roots: a pooled member answers as an agent with no runtime (read, list, search) | none |
| G2 | 2 | **Guard.** A link whose target is inside the roots is listed with its target's kind and size and named by a search (the file kind skips without a symlink privilege) | none |
| G3 | 1 | **Guard.** A caller's own `runtime` wins | none |
| T1 | 3 | Per type: refuses a base outside `read_roots`, serves one inside (the start path, `pool.py:308`) | M2 |
| T2 | 1 | Empty roots: the floor is the vessel's data directory; its workspace and other paths still read | M2 |
| T3 | 2 | Lister: a link out of the roots (directory, file) is `unknown`/0 | M2 |
| T4 | 1 | Lister: a link to the floor is `unknown`/0 with empty roots | M2 |
| T5 | 1 | Search: a `..` pattern names nothing outside the roots | M2 |
| T6 | 4 | Search: a link out of the roots (directory junction on win32, file symlink; walk and rglob) | M2 |
| T7 | 2 | Search: empty roots, a floor file is not named (walk, rglob) | M2 |
| T8 | 3 | A member the pool adds (`pool.py:620`) and one that refills a slot (`:533`) apply the policy | M2 |
| T9 | 3 | Refusals degrade a member; the recycled replacement (`pool.py:209`) still refuses | M2 |
| T10 | 3 | `info()` reads the runtime's trust network | M2 |
| T11 | 3 | **Seam:** a DM `[MESH ...]` tag through the real `IntentBus` to the pooled member | M2 |
| T12 | 1 | A policy that cannot decide fails closed | M2 |
| T13 | 1 | **Seam:** the pool's readers behind a real bus, read through BF-961's `read_stored_list`: outside the roots FAILED (an absent path too), inside FOUND or MISSING | M2 |

On the base (a pooled member with no runtime) each xfail case fails at an `assert` of its own body, as the script measured: T1, T8 and T9 at `== _OUTSIDE`; T2 at the refused read; T3 and T4 at the `door` or `vessel` entry; T5 to T7 at the member's result; T10 at the score; T11 at the refusal text; T12 at `(False, None)`; T13 at its first `FAILED` assert. The premise lines pass on the base.

## 7. The contract

### 7.1 M1

**N1-1.** New file `tests/test_bf944_pool_agents_read_policy.py`:

```python
"""BF-944 (#1717): a pool-built file reader, directory list and file search agent apply the runtime's read policy.

The real ``ProbOSRuntime.create_pool`` (unbound, over a runtime double after ``tests/test_ad1346_admission_sink_wiring.py``'s) builds the
pools; the agents and the policy are real; files and links are made under ``tmp_path``; no network is opened. The functions before the
class pass on both trees. T13 imports BF-961's ``read_stored_list``; no BF-944 name is imported.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

import probos.security.file_access as file_access
from probos.agents.directory_list import DirectoryListAgent
from probos.agents.file_reader import FileReaderAgent
from probos.agents.file_search import FileSearchAgent
from probos.agents.utility.stored_list import ReadStatus, read_stored_list
from probos.cognitive.dm_sanity_gate import DmSanityGate
from probos.config import TRUST_DEFAULT, ExecutionConfig, PoolConfig, SecurityInfraConfig, SystemConfig, format_trust
from probos.consensus.trust import TrustNetwork
from probos.mesh.intent import IntentBus
from probos.mesh.signal import SignalManager
from probos.runtime import ProbOSRuntime
from probos.substrate.registry import AgentRegistry
from probos.substrate.spawner import AgentSpawner
from probos.types import AgentState, IntentMessage
from tests.test_ad869_mesh_read_inline import _make_pipeline

_OUTSIDE = "path is outside every readable root"
_PROTECTED = "path is protected: the runtime's data directory or a config file"
_POOL = {"file_reader": "filesystem", "directory_list": "directory", "file_search": "search"}
_CLASS = {"file_reader": FileReaderAgent, "directory_list": DirectoryListAgent, "file_search": FileSearchAgent}
TYPES = list(_POOL)


def _scene(tmp_path):
    """allowed/, outside/ and vessel_data/ (not named ``data``, which the default walk prunes)."""
    root = tmp_path.resolve()
    scene = SimpleNamespace(root=root, allowed=root / "allowed", outside=root / "outside", data=root / "vessel_data")
    scene.workspace = scene.data / "workspaces"
    for name, text in {
        "allowed/ok.txt": "ok", "allowed/sub/inner.txt": "inner", "outside/secret.txt": "outside contents",
        "outside/deep/deeper.txt": "deeper", "vessel_data/trust.db": "governance", "vessel_data/workspaces/scratch.txt": "scratch",
    }.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    return scene


async def _no_log(**kwargs):
    return None


def _runtime(scene, read_roots):
    """A runtime double for ``create_pool``: a real config, registry, spawner and trust network, the three templates, and the
    vessel's own data directory (not the platform's)."""
    config = SystemConfig(
        pools=PoolConfig(default_pool_size=2, min_pool_size=1, max_pool_size=3),
        security_infra=SecurityInfraConfig(read_roots=[str(root) for root in read_roots]),
        execution=ExecutionConfig(workspace_root=str(scene.workspace)),
    )
    registry = AgentRegistry()
    runtime = SimpleNamespace(config=config, data_dir=scene.data, pools={}, registry=registry, spawner=AgentSpawner(registry),
                              trust_network=TrustNetwork(), event_log=SimpleNamespace(log=_no_log))
    for agent_type, cls in _CLASS.items():
        runtime.spawner.register_template(agent_type, cls)
    return runtime


@asynccontextmanager
async def _fleet(scene, read_roots):
    """The three pools through the real factory, as ``create_agent_fleet`` calls it (no ``runtime`` keyword), and a member of each."""
    runtime = _runtime(scene, read_roots)
    try:
        for agent_type, pool in _POOL.items():
            await ProbOSRuntime.create_pool(runtime, pool, agent_type, target_size=2)
        yield runtime, {agent_type: runtime.registry.get_by_pool(pool)[0] for agent_type, pool in _POOL.items()}
    finally:
        for pool in list(runtime.pools.values()):
            await pool.stop()


def _control(agent_type, runtime=None):
    """An agent built as the unfixed factory builds it (no runtime) or, given one, as BF-758's tests build theirs."""
    return _CLASS[agent_type](agent_id=f"ad944-{agent_type}", runtime=runtime)


async def _ask(agent, intent, **params):
    result = await agent.handle_intent(IntentMessage(intent=intent, params=params))
    assert result is not None, "premise: the agent handles the intent"
    return result


def _call(agent_type, where, name="secret.txt"):
    """The intent that reaches *where* through *agent_type*: a read of *name* there, or a listing or a search of it."""
    if agent_type == "file_reader":
        return "read_file", {"path": str(where / name)}
    if agent_type == "directory_list":
        return "list_directory", {"path": str(where)}
    return "search_files", {"path": str(where), "pattern": "*.txt"}


async def _entries(agent, where):
    return {item["name"]: item for item in (await _ask(agent, "list_directory", path=str(where))).result}


def _names(result, base):
    return sorted(Path(match).relative_to(base).as_posix() for match in result.result)


@contextmanager
def _linked(link, target):
    """A directory junction on Windows (no privilege needed) or a symlink elsewhere; a file link needs a symlink and skips where the
    host grants none."""
    directory = target.is_dir()
    if directory and os.name == "nt":
        import _winapi

        _winapi.CreateJunction(str(target), str(link))
    else:
        try:
            link.symlink_to(target, target_is_directory=directory)
        except (OSError, NotImplementedError):
            pytest.skip("a symlink needs a privilege this host does not grant")
    try:
        yield link
    finally:
        if directory and os.name == "nt":
            link.rmdir()
        else:
            link.unlink()


@pytest.mark.parametrize("agent_type", TYPES)
async def test_with_empty_roots_a_pooled_member_answers_as_an_agent_with_no_runtime(tmp_path, agent_type):
    """G1: the control round first, so the equality is about the empty setting and not a policy that is off."""
    scene = _scene(tmp_path)
    intent, params = _call(agent_type, scene.outside)
    confined = await _ask(_control(agent_type, _runtime(scene, [scene.allowed])), intent, **params)
    assert (confined.success, confined.error) == (False, _OUTSIDE), "premise: set roots refuse the outside directory"
    async with _fleet(scene, []) as (_rt, members):
        for where, name in ((scene.outside, "secret.txt"), (scene.allowed, "ok.txt")):
            intent, params = _call(agent_type, where, name)
            pooled, bare = await _ask(members[agent_type], intent, **params), await _ask(_control(agent_type), intent, **params)
            assert bare.success is True, "premise: an agent with no runtime serves it"
            assert (pooled.success, pooled.result, pooled.error) == (bare.success, bare.result, bare.error)


@pytest.mark.parametrize("kind", ["directory", "file"])
async def test_a_link_to_a_target_inside_the_roots_is_unchanged(tmp_path, kind):
    """G2: listed with its target's kind and size, and named by a search."""
    scene = _scene(tmp_path)
    target = scene.allowed / ("sub" if kind == "directory" else "ok.txt")
    with _linked(scene.allowed / "inside", target):
        async with _fleet(scene, [scene.allowed]) as (_rt, members):
            entry = (await _entries(members["directory_list"], scene.allowed))["inside"]
            assert entry == {"name": "inside", "type": "dir" if kind == "directory" else "file", "size": target.stat().st_size}
            named = await _ask(members["file_search"], "search_files", path=str(scene.allowed), pattern="inside", include_ignored=True)
            assert _names(named, scene.allowed) == ["inside"]


async def test_a_callers_own_runtime_wins(tmp_path):
    """G3: the factory's runtime has no roots, the caller's confines, and the member keeps the caller's."""
    scene = _scene(tmp_path)
    factory = _runtime(scene, [])
    try:
        await ProbOSRuntime.create_pool(factory, "filesystem", "file_reader", target_size=1, runtime=_runtime(scene, [scene.allowed]))
        (member,) = factory.registry.get_by_pool("filesystem")
        intent, params = _call("file_reader", scene.outside)
        refused = await _ask(member, intent, **params)
        assert (refused.success, refused.error) == (False, _OUTSIDE)
    finally:
        for pool in list(factory.pools.values()):
            await pool.stop()


class TestAPoolBuiltAgentAppliesTheRuntimesReadPolicy:
    # BF-944 M1: xfail until M2 builds it (M2 removes this line and the next).
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-944 M2 builds it")

    @pytest.mark.parametrize("agent_type", TYPES)
    async def test_a_member_refuses_a_base_outside_read_roots_and_serves_one_inside(self, tmp_path, agent_type):
        """T1."""
        scene = _scene(tmp_path)
        intent, params = _call(agent_type, scene.outside)
        assert (await _ask(_control(agent_type), intent, **params)).success is True, "premise: an agent with no runtime serves it"
        async with _fleet(scene, [scene.allowed]) as (_rt, members):
            refused = await _ask(members[agent_type], intent, **params)
            assert (refused.success, refused.error) == (False, _OUTSIDE)
            intent, params = _call(agent_type, scene.allowed, "ok.txt")
            served = await _ask(members[agent_type], intent, **params)
            assert (served.success, served.error) == (True, None)

    async def test_with_empty_roots_the_floor_is_the_vessels_own_data_directory(self, tmp_path):
        """T2: the runtime's data directory is refused; its workspace and any other path read, as before."""
        scene = _scene(tmp_path)
        governance = {"path": str(scene.data / "trust.db")}
        assert (await _ask(_control("file_reader"), "read_file", **governance)).success is True, "premise: the platform's floor is not this vessel's"
        async with _fleet(scene, []) as (_rt, members):
            refused = await _ask(members["file_reader"], "read_file", **governance)
            assert (refused.success, refused.error) == (False, _PROTECTED)
            listed = await _ask(members["directory_list"], "list_directory", path=str(scene.data))
            assert (listed.success, listed.error) == (False, _PROTECTED)
            scratch = await _ask(members["file_reader"], "read_file", path=str(scene.workspace / "scratch.txt"))
            assert (scratch.success, scratch.result) == (True, "scratch")
            elsewhere = await _ask(members["file_reader"], "read_file", path=str(scene.outside / "secret.txt"))
            assert (elsewhere.success, elsewhere.result) == (True, "outside contents")

    @pytest.mark.parametrize("kind", ["directory", "file"])
    async def test_the_lister_reports_no_kind_or_size_for_a_link_out_of_the_roots(self, tmp_path, kind):
        """T3."""
        scene = _scene(tmp_path)
        with _linked(scene.allowed / "door", scene.outside if kind == "directory" else scene.outside / "secret.txt"):
            through = scene.allowed / "door" / ("secret.txt" if kind == "directory" else "")
            reader = _control("file_reader", _runtime(scene, [scene.allowed]))
            assert (await _ask(reader, "read_file", path=str(through))).error == _OUTSIDE, "premise: a read through the link is refused"
            async with _fleet(scene, [scene.allowed]) as (_rt, members):
                entries = await _entries(members["directory_list"], scene.allowed)
                assert entries["door"] == {"name": "door", "type": "unknown", "size": 0}
                assert entries["ok.txt"] == {"name": "ok.txt", "type": "file", "size": 2}

    async def test_a_link_to_the_floor_is_an_entry_that_cannot_be_read_with_empty_roots(self, tmp_path):
        """T4."""
        scene = _scene(tmp_path)
        with _linked(scene.allowed / "vessel", scene.data):
            assert (await _entries(_control("directory_list"), scene.allowed))["vessel"]["type"] == "dir", "premise: with no runtime it is followed"
            async with _fleet(scene, []) as (_rt, members):
                assert (await _entries(members["directory_list"], scene.allowed))["vessel"] == {"name": "vessel", "type": "unknown", "size": 0}

    async def test_a_pattern_with_a_dotdot_part_names_nothing_outside_the_roots(self, tmp_path):
        """T5."""
        scene = _scene(tmp_path)
        reach = {"path": str(scene.allowed), "pattern": "../outside/*.txt", "include_ignored": True}
        reached = await _ask(_control("file_search"), "search_files", **reach)
        assert [Path(match).resolve() for match in reached.result] == [scene.outside / "secret.txt"], "premise: the pattern reaches the outside file"
        async with _fleet(scene, [scene.allowed]) as (_rt, members):
            found = await _ask(members["file_search"], "search_files", **reach)
            assert (found.success, found.result) == (True, [])

    @pytest.mark.parametrize("include_ignored", [False, True], ids=["walk", "rglob"])
    @pytest.mark.parametrize("kind", [
        pytest.param("directory", marks=pytest.mark.skipif(os.name != "nt", reason="rglob and os.walk follow a directory junction on Windows only")),
        "file",
    ])
    async def test_a_link_out_of_the_roots_lists_nothing_outside_them(self, tmp_path, kind, include_ignored):
        """T6: a directory junction on Windows, or a file symlink where the host grants one."""
        scene = _scene(tmp_path)
        params = {"path": str(scene.allowed), "pattern": "*.txt", "include_ignored": include_ignored}
        link, target = (scene.allowed / "door", scene.outside) if kind == "directory" else (scene.allowed / "peek.txt", scene.outside / "secret.txt")
        with _linked(link, target):
            reached = _names(await _ask(_control("file_search"), "search_files", **params), scene.allowed)
            assert set(reached) > {"ok.txt", "sub/inner.txt"}, "premise: the link leads outside"
            async with _fleet(scene, [scene.allowed]) as (_rt, members):
                found = await _ask(members["file_search"], "search_files", **params)
                assert _names(found, scene.allowed) == ["ok.txt", "sub/inner.txt"]

    @pytest.mark.parametrize("include_ignored", [False, True], ids=["walk", "rglob"])
    async def test_with_empty_roots_a_search_still_drops_what_the_floor_refuses(self, tmp_path, include_ignored):
        """T7."""
        scene = _scene(tmp_path)
        params = {"path": str(scene.root), "pattern": "*.db", "include_ignored": include_ignored}
        reached = await _ask(_control("file_search"), "search_files", **params)
        assert _names(reached, scene.root) == ["vessel_data/trust.db"], "premise: the platform's floor does not hold the vessel's data directory"
        async with _fleet(scene, []) as (_rt, members):
            found = await _ask(members["file_search"], "search_files", **params)
            assert (found.success, found.result) == (True, [])

    @pytest.mark.parametrize("agent_type", TYPES)
    async def test_a_member_the_pool_adds_or_refills_applies_the_policy(self, tmp_path, agent_type):
        """T8: the add path (``pool.py:620``) and the refill path (``:533``)."""
        scene = _scene(tmp_path)
        intent, params = _call(agent_type, scene.outside)
        async with _fleet(scene, [scene.allowed]) as (runtime, members):
            pool = runtime.pools[_POOL[agent_type]]
            added = runtime.registry.get(await pool.add_agent())
            assert added is not None, "premise: the pool grew"
            assert (await _ask(added, intent, **params)).error == _OUTSIDE
            pool.target_size, before = pool.current_size, set(pool.get_agent_ids())
            members[agent_type].state = AgentState.RECYCLING
            await pool.check_health()
            (refilled,) = [runtime.registry.get(agent_id) for agent_id in pool.get_agent_ids() if agent_id not in before]
            assert (await _ask(refilled, intent, **params)).error == _OUTSIDE

    @pytest.mark.parametrize("agent_type", TYPES)
    async def test_a_member_the_refusals_degrade_is_replaced_by_one_that_still_refuses(self, tmp_path, agent_type):
        """T9: the recycle path (``pool.py:209``). A refusal is a failure outcome; a run of them degrades the member."""
        scene = _scene(tmp_path)
        intent, params = _call(agent_type, scene.outside)
        async with _fleet(scene, [scene.allowed]) as (runtime, members):
            member, pool = members[agent_type], runtime.pools[_POOL[agent_type]]
            for _attempt in range(20):
                assert (await _ask(member, intent, **params)).error == _OUTSIDE
                if member.state is AgentState.DEGRADED:
                    break
            assert member.state is AgentState.DEGRADED, "premise: a run of refusals degrades the member"
            await pool.check_health()
            replacement = runtime.registry.get(member.id)
            assert replacement is not None and replacement is not member, "premise: the pool recycled it"
            assert (await _ask(replacement, intent, **params)).error == _OUTSIDE

    @pytest.mark.parametrize("agent_type", TYPES)
    async def test_a_pool_built_members_info_reads_the_runtimes_trust_network(self, tmp_path, agent_type):
        """T10."""
        scene = _scene(tmp_path)
        assert _control(agent_type).info()["trust_score"] == format_trust(TRUST_DEFAULT), "premise: with no runtime info() reports the default"
        async with _fleet(scene, []) as (runtime, members):
            runtime.trust_network.create_with_prior(members[agent_type].id, 9.0, 1.0)
            assert members[agent_type].info()["trust_score"] == format_trust(0.9)

    @pytest.mark.parametrize("agent_type", TYPES)
    async def test_a_mesh_read_tag_reaches_the_policy_through_the_real_bus(self, tmp_path, agent_type):
        """T11: the AD-869 seam, a DM turn's tag to the pool's agent the registry names."""
        scene = _scene(tmp_path)
        async with _fleet(scene, [scene.allowed]) as (runtime, _members):
            bus, name = IntentBus(SignalManager()), _call(agent_type, scene.outside)[0]
            for member in runtime.registry.get_by_pool(_POOL[agent_type]):
                bus.subscribe(member.id, member.handle_intent, [name])

            async def turn(where, file):
                intent, params = _call(agent_type, where, file)
                tag = " ".join(f"{key}={value}" for key, value in params.items())
                seen = SimpleNamespace(intent_bus=bus, registry=runtime.registry)
                pipeline = _make_pipeline(runtime=seen, response_text=f"Looking. [MESH {intent} {tag}]", sanity_gate=DmSanityGate())
                await pipeline.step_4h_mesh_read_parse()
                return pipeline.ctx.response_text

            outside = await turn(scene.outside, "secret.txt")
            assert f"(The {name} lookup came back empty ({_OUTSIDE}).)" in outside
            assert "outside contents" not in outside and "secret.txt" not in outside
            inside = await turn(scene.allowed, "ok.txt")
            assert "came back empty" not in inside
            assert inside.endswith("\n\nok") if agent_type == "file_reader" else "ok.txt" in inside

    async def test_a_policy_that_cannot_decide_fails_closed(self, tmp_path, monkeypatch):
        """T12: the search fails whole and names nothing; the lister reports the entry it could not decide as unreadable."""
        scene = _scene(tmp_path)
        real = file_access.resolve_read_path

        def undecided(raw, **kwargs):
            if Path(raw).name in {"inner.txt", "door"}:
                raise OSError("probe")
            return real(raw, **kwargs)

        with _linked(scene.allowed / "door", scene.outside):
            async with _fleet(scene, [scene.allowed]) as (_rt, members):
                monkeypatch.setattr(file_access, "resolve_read_path", undecided)
                searched = await _ask(members["file_search"], "search_files", path=str(scene.allowed), pattern="*.txt")
                assert (searched.success, searched.result) == (False, None)
                assert (await _entries(members["directory_list"], scene.allowed))["door"] == {"name": "door", "type": "unknown", "size": 0}

    async def test_a_stored_list_read_through_the_pools_readers_fails_closed(self, tmp_path):
        """T13: a read through BF-961's ``read_stored_list`` fails outside the roots, an absent path included (the refusal comes before
        the existence check); inside the roots a file is found or missing."""
        scene = _scene(tmp_path)
        async with _fleet(scene, [scene.allowed]) as (runtime, _members):
            bus = IntentBus(SignalManager())
            for member in runtime.registry.get_by_pool("filesystem"):
                bus.subscribe(member.id, member.handle_intent, ["read_file"])
            seen = SimpleNamespace(intent_bus=bus)
            for name in ("secret.txt", "absent.json"):
                assert (await read_stored_list(seen, str(scene.outside / name))).status is ReadStatus.FAILED
            found = await read_stored_list(seen, str(scene.allowed / "ok.txt"))
            assert (found.status, found.text) == (ReadStatus.FOUND, "ok")
            assert (await read_stored_list(seen, str(scene.allowed / "absent.json"))).status is ReadStatus.MISSING
```

### 7.2 M2

**P2-1.** `src/probos/runtime.py`
SEARCH:
```
            spawn_kwargs["runtime"] = self

        on_agent_spawned: Callable[[Any], Awaitable[None]] | None = (
```
REPLACE:
```
            spawn_kwargs["runtime"] = self

        if agent_type in (FileReaderAgent.agent_type, DirectoryListAgent.agent_type, FileSearchAgent.agent_type) and "runtime" not in spawn_kwargs:
            # BF-944 (#1717): these agents apply their runtime's read policy to the path they are given (BF-758) and have none
            # without one. The pool keeps its spawn kwargs, so a respawned or added member gets the runtime too. A caller's value wins.
            spawn_kwargs["runtime"] = self

        on_agent_spawned: Callable[[Any], Awaitable[None]] | None = (
```

**P2-2.** `src/probos/security/file_access.py`
SEARCH:
```
        relative_base=relative_base,
    )


INSTRUCTION_FILE_BYTES = 8192
```
REPLACE:
```
        relative_base=relative_base,
    )


class ReadFloor:
    """BF-944: the read policy *runtime* configures (the floor, the agent workspace, ``security_infra.read_roots``), composed once
    as :func:`resolve_for_runtime` composes it, for a caller that decides many paths. Built per listing or search."""

    def __init__(self, runtime: Any) -> None:
        self._protected = protected_read_roots(runtime)
        self._exempt = workspace_exempt_roots(runtime)
        self._permitted = permitted_read_roots(runtime) or None

    def permits(self, path: str) -> bool:
        """Whether the policy admits the absolute *path* (a link is followed). False for a refusal; any other failure propagates."""
        try:
            resolve_read_path(
                path,
                protected_roots=self._protected,
                exempt_roots=self._exempt,
                permitted_roots=self._permitted,
            )
        except FileAccessDenied:
            return False  # BF-944: the policy refuses it
        return True  # BF-944: the policy admits it


INSTRUCTION_FILE_BYTES = 8192
```

**P2-3a.** `src/probos/agents/file_search.py`
SEARCH:
```
        from probos.security.file_access import resolve_for_runtime
```
REPLACE:
```
        from probos.security.file_access import ReadFloor, resolve_for_runtime
```

**P2-3b.** `src/probos/agents/file_search.py`
SEARCH:
```
                    if f.match(pattern)
                )
            return {
```
REPLACE:
```
                    if f.match(pattern)
                )
            # BF-944: a ``..`` pattern or a link under the base can lead out of it, so a match is kept when the read policy admits the
            # path it resolves to and dropped otherwise; the policy is composed after the walk.
            floor = ReadFloor(getattr(self, "_runtime", None))
            kept = [m for m in matches if floor.permits(m)]  # BF-944: a match the policy refuses is left out and not counted
            if len(kept) != len(matches):
                logger.info("BF-944: file search left out %d match(es) the read policy refuses", len(matches) - len(kept))
            matches = kept
            return {
```

**P2-4a.** `src/probos/agents/directory_list.py`
SEARCH:
```
        from probos.security.file_access import resolve_for_runtime
```
REPLACE:
```
        from probos.security.file_access import ReadFloor, resolve_for_runtime
```

**P2-4b.** `src/probos/agents/directory_list.py`
SEARCH:
```
            entries = []
            for entry in sorted(p.iterdir()):
                try:
                    stat = entry.stat()
```
REPLACE:
```
            floor = ReadFloor(getattr(self, "_runtime", None))  # BF-944: composed once, asked about an entry that is a link
            entries = []
            for entry in sorted(p.iterdir()):
                try:
                    # BF-944: stat() and is_dir() follow a link (a Windows junction is no symlink, so it is asked too). A link whose
                    # target the read policy refuses is the entry of one that cannot be read: neither kind nor size.
                    if (entry.is_symlink() or entry.is_junction()) and not floor.permits(str(entry)):  # BF-944: the target is refused
                        entries.append({"name": entry.name, "type": "unknown", "size": 0})
                        continue
                    stat = entry.stat()
```

**P2-5.** `src/probos/config.py`
SEARCH:
```
    # whatever this says, so widening it cannot hand out the credential vault.
    read_roots: list[str] = Field(default_factory=list)
```
REPLACE:
```
    # whatever this says, so widening it cannot hand out the credential vault.
    # BF-944: the pool agents behind those intents apply it as well. The bundled todo, note and scheduler agents read their
    # files in ~/.probos through read_file and list_directory, so list that directory here: a refused read of the todo or
    # reminder file makes those agents answer that the list could not be read, and write nothing (BF-961).
    read_roots: list[str] = Field(default_factory=list)
```

**N2-1.** `tests/test_bf944_pool_agents_read_policy.py`
SEARCH:
```
    # BF-944 M1: xfail until M2 builds it (M2 removes this line and the next).
    pytestmark = pytest.mark.xfail(raises=AssertionError, strict=True, reason="BF-944 M2 builds it")

    @pytest.mark.parametrize("agent_type", TYPES)
    async def test_a_member_refuses_a_base_outside_read_roots_and_serves_one_inside(self, tmp_path, agent_type):
```
REPLACE:
```
    @pytest.mark.parametrize("agent_type", TYPES)
    async def test_a_member_refuses_a_base_outside_read_roots_and_serves_one_inside(self, tmp_path, agent_type):
```

**N2-2.** `tests/test_hebbian_source_key.py`
SEARCH:
```
    # Create a file the read_file agent can successfully read
    target = tmp_path / "data" / "readable.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
```
REPLACE:
```
    # Create a file the read_file agent can successfully read. BF-944: outside the runtime's data directory, which the pool's
    # readers refuse now that they have the runtime (the read policy is the runtime's).
    target = tmp_path / "readable.txt"
    target.parent.mkdir(parents=True, exist_ok=True)
```

**N2-3.** `tests/test_escalation.py`
SEARCH:
```
        rt = ProbOSRuntime(data_dir=tmp_path, episodic_memory=mem)
        await rt.start()

        try:
```
REPLACE:
```
        # BF-944: the file below is outside the data directory, which the pool's readers refuse
        rt = ProbOSRuntime(data_dir=tmp_path / "data", episodic_memory=mem)
        await rt.start()

        try:
```

**N2-4.** `tests/test_runtime_discovery.py`
SEARCH:
```
        test_file = tmp_path / "data" / "test_read.txt"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("hello world")
```
REPLACE:
```
        test_file = tmp_path / "test_read.txt"  # BF-944: outside the runtime's data directory (tmp_path / "data"), which the readers refuse
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("hello world")
```

### 7.3 M3: tracking

**P3-1.** `PROGRESS.md`. The anchor is the title line and the blank line after it (once); BF-961's entry follows it, so this one is the newest. Replace `DATE` with M3's date.
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**BF-944 (DATE), #1717 -- pool-built file reader, directory list and file search agents apply the runtime's read policy.**
- **Base.** `create_agent_fleet` built the `filesystem`, `directory` and `search` pools with no runtime, so `security_infra.read_roots` did not confine `read_file`, `stat_file`, `list_directory` or `search_files` through them, and their read floor was the platform's, not the runtime's data directory and loaded config. The lister reported a link's target kind and size; the search named matches that a `..` pattern or a link led out of the roots.
- **Fix.** `ProbOSRuntime.create_pool` hands itself to a pool of those three types made without a `runtime` keyword (kept for recycle, refill and add). The lister reports a link whose target the policy refuses as an unreadable entry; the search keeps a match when the policy admits its resolved path (new `ReadFloor`). Three existing tests that read inside a runtime's data directory read outside it now. With `read_roots` set and `~/.probos` unlisted, the todo and scheduler agents answer that their list could not be read (BF-961). Contract `prompts/bf-944-pool-agents-read-policy.md`. Closes #1717.

```

**P3-2.** `DECISIONS.md`. Append after BF-961's entry, the newest BF entry on `ae0cdd12` (the AD-1346 M3e4d9 entry follows it). Its last bullet occurs once; BF-961's A1 changed it from `L1 to L8` to `L1 to L9`.
SEARCH:
```
- *Residual.* L1 to L9 of the contract. *Reversal.* Revert the BF-961 commits.
```
REPLACE:
```
- *Residual.* L1 to L9 of the contract. *Reversal.* Revert the BF-961 commits.

### BF-944 -- Pool-built file reader, directory list and file search agents apply the runtime's read policy (DATE, #1717)

- *Scope.* `runtime.py` (`create_pool`), `security/file_access.py` (`ReadFloor`), `agents/file_search.py`, `agents/directory_list.py`, a comment in `config.py`, tests (a new file; one block in each of three existing files). Contract `prompts/bf-944-pool-agents-read-policy.md`.
- *D1 (wiring).* A per-type rule in `create_pool`, beside AD-1346 M3e1's, so start, recycle, refill and add carry the runtime. Rejected: `runtime=runtime` at the fleet rows; a runtime for every pool type; a module-level locator.
- *D2 (default).* The floor is the runtime's, as for the readers that have the runtime: unchanged for a default or Docker vessel; the vessel's own data directory and `--config` file for a `--data-dir` or `--config` vessel. A search match the floor refuses is dropped and a link entry whose target it refuses is reported as unreadable. Rejected: keeping the platform floor while `read_roots` is empty; a switch.
- *D3 (the two cases).* A link entry whose target the policy refuses is an unreadable entry (`unknown`, size 0); a match is kept when the policy admits its resolved path (a public `ReadFloor`; no pattern rule, no `reader_spelling`). Rejected: omitting the entry; BF-948's pattern refusal; `code_search._ReadFloor`.
- *D7 (tests).* Three existing tests (`test_hebbian_source_key.py`, `test_escalation.py`, `test_runtime_discovery.py`) read inside their runtime's data directory: with the runtime two of them fail (Hebbian weights, a completed count) and one keeps passing without a successful read; they read outside it now. Rejected: xfail; widening `read_roots` (the floor wins).
- *Residual.* L1 to L9 of the contract; with `read_roots` set and `~/.probos` unlisted, the todo and scheduler agents answer that their list could not be read (BF-961; L6). *Reversal.* Revert the BF-944 commits.
```

**Ledger.** Run G3. The roadmap Bug Tracker is not edited.

## 8. What this does NOT change

`startup/agent_fleet.py`; `agents/code_search.py` and its `_ReadFloor`; `FileReaderAgent`; BF-961's `stored_list.py`, its guard and the three bundled agents; `resolve_read_path`, `resolve_for_runtime`, `permitted_read_roots`, the floor and `reader_spelling`; `ListFilesTool`; `FileWriterAgent` and the write floor (F-228); `iter_files`; the red team's verifiers (L7); the intent bus and the AD-869 pipeline; the configuration (one comment, no field); AD-1346's census rows; the roadmap. OSS only; no dependency.

## 9. Mutation rows (each Line occurs once, stripped, in its file on M2's head)

Run by script on the patched tree with the M2-head test file (win32, no symlink privilege: the file-kind cases skip, and with it `G2`, `T3`, `T6` gain their file cases). A control built with no runtime runs the patched code too, so rows 4 to 7 and 10 also fail the premise lines of the cases they name. Dropping `DirectoryListAgent.agent_type` from row 1's tuple (not tabulated, for the cap) fails T1, T8, T9, T10, T11 [directory_list], T2, T3 [directory] and T4. The Builder runs the ten once, on M2's head, with the new file alone.

| # | M | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|---|
| 1 | M2 | src/probos/runtime.py | `if agent_type in (FileReaderAgent.agent_type, DirectoryListAgent.agent_type, FileSearchAgent.agent_type) and "runtime" not in spawn_kwargs:` | `if agent_type in (DirectoryListAgent.agent_type, FileSearchAgent.agent_type) and "runtime" not in spawn_kwargs:` | T1, T8, T9, T10, T11 [file_reader]; T2; T13 |
| 2 | M2 | src/probos/runtime.py | the row 1 line | `if agent_type in (FileReaderAgent.agent_type, DirectoryListAgent.agent_type) and "runtime" not in spawn_kwargs:` | T1, T8, T9, T10, T11 [file_search]; T5; T6 [directory]; T7 |
| 3 | M2 | src/probos/runtime.py | the row 1 line | `if agent_type in (FileReaderAgent.agent_type, DirectoryListAgent.agent_type, FileSearchAgent.agent_type) and True:` | G3 |
| 4 | M2 | src/probos/security/file_access.py | `return False  # BF-944: the policy refuses it` | `return True` | T3 [directory]; T4; T5; T6 [directory]; T7 |
| 5 | M2 | src/probos/security/file_access.py | `return True  # BF-944: the policy admits it` | `return False` | G2 [directory]; T4; T5; T6 [directory]; T7; T11 [file_search] |
| 6 | M2 | src/probos/security/file_access.py | `permitted_roots=self._permitted,` | `permitted_roots=None,` | T3 [directory]; T5; T6 [directory] |
| 7 | M2 | src/probos/security/file_access.py | `protected_roots=self._protected,` | `protected_roots=(),` | T4; T7 |
| 8 | M2 | src/probos/agents/file_search.py | `kept = [m for m in matches if floor.permits(m)]  # BF-944: a match the policy refuses is left out and not counted` | `kept = matches` | T5; T6 [directory]; T7; T12 |
| 9 | M2 | src/probos/agents/directory_list.py | `if (entry.is_symlink() or entry.is_junction()) and not floor.permits(str(entry)):  # BF-944: the target is refused` | `if entry.is_symlink() and not floor.permits(str(entry)):` | T3 [directory]; T4; T12 (win32: a POSIX link is a symlink) |
| 10 | M2 | src/probos/agents/directory_list.py | the row 9 line | `if entry.is_symlink() or entry.is_junction():` | G2 [directory]; T4 |

## 10. Recorded limits

- **L1.** The search still walks beyond the roots for a `..` pattern or a link; what is decided is whether a match is kept. A walk error's text (a `PermissionError` message) is returned as before, through the method's `except Exception`.
- **L2.** A match or link target is decided when listed; the later `read_file` decides again, so a link retargeted in between is refused at the read.
- **L3.** One `resolve_read_path` per match, no cache. Measured (win32, 5,000 files in 50 temp directories, `read_roots` of that directory, best of three): the default walk 173 ms before, 1,478 ms after; `include_ignored` 16 and 1,413 ms: about 0.26 ms per match. `iter_files` caps the default walk at 20,000 files (`substrate/file_walk.py:47`), where that adds about 5 s on the event loop: `_search_files` has no `await` (`file_search.py:112-155`; `await` occurs in that file at `:40`, `:44`, `:48`, `:49` and `:102` only, none inside it), no file agent offloads (a search for `to_thread` and `run_in_executor` under `src/probos/agents` finds three calls, `web_agents.py:693`, `red_team.py:341` and `shell_command.py:203`, and three docstring mentions, `red_team.py:325`, `:479` and `shell_command.py:278`, none in a file agent), and a local target is awaited inline (`intent.py:1180`, `:1194`, `:1229`), so the AD-869 seam's 5 s TTL (`reply_pipeline.py:85`, `:1479`) has no suspension point to cut at (a coroutine that never yields runs to completion before `wait_for` can act) and the loop waits. The seam renders 1,500 characters (`reply_pipeline.py:110`, `:1554`). The figure is one host's and was not re-run for this contract. `rglob` has no cap. `code_search` (BF-908) and `ListFilesTool` (BF-948) decide per match the same way. A per-directory cache, and taking the walk off the loop so that the TTL binds, are a follow-up recorded in #1754 after the merge (not a new issue: the filing policy): `ReadFloor` would cache `Path(parent).resolve()` per spelled parent, never a verdict; a reparse-point match, a failed `lstat`, a `.` or `..` leaf and an `rglob` match with a literal last part keep the full check; a protected file such as a config file in an admitted directory keeps its own leaf decision; the floor would be unified with `code_search`'s (L8). Decided by the Architect, 2026-11-09 (recorded on #1717): the cost is accepted as drafted.
- **L4.** The lister decides link entries: a non-link entry the floor refuses (a credential vault file, the data directory's own entry in its parent) is listed with its name, kind and size as before (BF-908 pins that the loaded config file is listed by name: `test_bf908_floor_and_children.py:366-371`). A reparse point that is neither a symlink nor a junction, and a hard link, are no links here (BF-758 records the hard link).
- **L5.** `reader_spelling` is not applied (D3): a name the verified reader would reject, and a Windows namespace prefix, are listed as `rglob` and `os.walk` spell them.
- **L6.** With `read_roots` set and `~/.probos` unlisted, the three bundled agents that read there through these pools (the todo, scheduler and note agents: `stored_list.py:49`, `organizer_agents.py:59,:124`; A4) read nothing there. The todo and scheduler agents answer that the list could not be read and write nothing (BF-961), a first save included; the note agent answers `not found` to a read and shows `None` for a listing, and its `save` still writes, a model answer of `save` to a requested `read` included (BF-961 L5). The operator lists `~/.probos` in `read_roots` (P2-5).
- **L7.** The red team's `read_file` and `stat_file` verifiers re-read by a bare `Path` (`red_team.py:148`, `:234`): given the failure claim of a read the policy refuses, a verifier called directly answers `Agent claims failure but file exists and is readable` (`:184`), as it does for a floor refusal already (reproduced in review round 1). The runtime's consensus path builds its verification tasks from successful results only (`runtime.py:4810`), so an ordinary refused read does not reach a verifier there; whether another route sends a refusal to one was not traced. Not changed; whether a plan sets `use_consensus` on a read was not traced.
- **L8.** `ReadFloor.permits` and `code_search._ReadFloor.permits` decide the same way (the same three root lists, `resolve_read_path`, `FileAccessDenied` -> False); `_ReadFloor` also remembers each path it decided (`code_search.py:343`, `:347-359`), `ReadFloor` does not (L3). Unify when `test_bf908_floor_and_children.py` (`:674-735`) is re-pointed. A relative `--data-dir` is resolved against the working directory at each call, as `resolve_for_runtime` already does.
- **L9.** A3 finds tests by their intent literals, their runtime builders and the `data_dir` they pass; a test that reaches the pools another way, or asserts too little to notice a refused read (as `test_runtime_discovery.py` did), is found by the broad gate if at all. Not measured: a live vessel; the file-symlink cases on this host (skipped); whether a layer between an intent and these agents confines reads by other means than the policy's names: A9 finds those names in `config.py`, the policy module, the three agents, `code_search.py` and five tool or adapter modules, and in no file of `cognitive/dm`, `mesh`, `consensus`, `substrate` or `startup`.

## 11. Verified Against Codebase (2026-11-08, `D:\ProbOS-worktrees\bf961-build` at `d9b2a9da`)

```
git rev-parse HEAD -> d9b2a9da41454943e683b2348aafe8c0206ad2a1 (branch fix/bf961-unreadable-stored-list-20261108, clean); origin/main there -> 50caed131e5b6b358a5d1adf6ab748a39ef619a7
git diff --name-status 6ee2bfa0 d9b2a9da -> 15 paths: DECISIONS.md, PROGRESS.md, 2 ledger files, 2 prompts, file_reader.py, http_fetch.py, red_team.py, organizer_agents.py, productivity_agents.py, stored_list.py (A), 3 tests
git rev-parse {6ee2bfa0,50caed13,d9b2a9da}:P -> one blob for runtime.py, file_access.py, file_search.py, directory_list.py, config.py, agent_fleet.py, pool.py, spawner.py, agent.py (v1's cites into them hold; re-read in runtime.py: :24,:27,:28,:2626,:2668-2672 (spawn_kwargs["runtime"] = self occurs once),:2694)
cites re-made: file_reader.py :16,:24,:113-119 | stored_list.py :38,:48,:63,:76,:79-96 | productivity_agents.py :148-178 | organizer_agents.py :56-64,:124,:155,:159,:196-243,:339 | red_team.py :117,:119,:138-184,:224,:234 | decomposer.py :477,:757-764 | reply_pipeline.py :1549-1552,:1609-1618 | file_walk.py :38,:47 | directory_list.py :120-133 | file_search.py :54-61
```

**Measured by script (CPython 3.12.13, win32; scripts and scenes in the OS temp folder, outside every repository; no pytest).** (a) `allowed.rglob("../outside/*.txt")` yields `allowed\..\outside\secret.txt`; a junction is no symlink (`is_symlink()` False, `is_junction()` True, `is_dir()` True, `st_size` 0) and `rglob` and `os.walk` list through it; a file symlink raises `OSError 1314`. (b) The M2 blocks applied in memory to the `d9b2a9da` blobs (each SEARCH once, results parse) over a temp copy: the draft test file, called by a script that expands marks as pytest does, gives unpatched 5 passed, 4 skipped, 25 xfailed, each at an `assert` of its own body; patched with the marker removed 30 passed, 4 skipped; with the marker kept the 25 class cases XPASS(strict); the platform data dir, working directory and HOME stayed empty. Mutants: section 9. (c) A started `ProbOSRuntime` reading `tmp_path/data/readable.txt`: unpatched 3 successes (Hebbian weights 0.05, 0.09975; consensus APPROVED), patched 3 refusals, weights 0.0 and 0.0, consensus REJECTED, a file outside the data dir still read. `process_natural_language("read the file at <path>")`: test 26's body `completed_count` 1 then 0; the discovery test's body `node_count` 1 either way, `completed_count` 1 then 0; with the file outside the data dir it completes when patched. (d) T13's scene: unpatched FOUND for the outside file; patched FAILED for an existing and an absent outside path. A real `TodoAgent` and `SchedulerAgent` over those readers (HOME moved, roots omitting `~/.probos`): unpatched each writes; patched each answers `Could not read ...; nothing was changed or saved.` with no model request and no write, for a first save and for a stored file (left as it was). (e) `check_architecture_principles.py --check` on a temp copy with the 11 patched files: exit 0, `srp-size=92, layer-import=0, db-connect=30, unowned-task=13`, as unpatched. (f) Timing: L3.

**Absence Verified (2026-11-08, `d9b2a9da`)**

```
A1 CLAIM: nothing in src builds these agents except ResourcePool; no foreign read of a member's _runtime changes with a runtime here
RUN:   git grep -n -E 'FileReaderAgent|DirectoryListAgent|FileSearchAgent|"file_reader"|"directory_list"|"file_search"' d9b2a9da -- src; likewise '\.spawn\(|\.recycle\(|ResourcePool\(|\.create_pool\(', '_spawn_kwargs' and '(agent|a|member|replacement|target|peer|obj|other)\._runtime\b'
FOUND: defs, imports, runtime.py:1589-1592, agent_fleet.py:47-50, corrupted.py:14,:22 (a class with agent_type "file_reader", named in no other src file); no constructor call of the three; `ResourcePool(` at runtime.py:2694 only; spawn at pool.py:308,:533,:620, spawner.py:125, finalize.py:2708 (system_qa); other `.create_pool(` callers make other types; `_spawn_kwargs` in pool.py only; a foreign `_runtime` read at cognitive/scout.py:302,:305
HOLDS: yes
A3 CLAIM: three existing tests read inside a runtime's data directory through these pools; none pins create_pool's rule or agent_fleet's rows for these types
RUN:   git grep -l a quoted file intent (read_file, list_directory, search_files, stat_file) over tests: 126 files; crossed with 'ProbOSRuntime\(' (92): 24; with the 125 files naming a runtime factory: 14 more; each hit read for its path and data_dir; git grep -n 'data_dir=tmp_path[,)]' and 'tmp_path / "data" / <name>' over tests; the pool names with get_by_pool or pools[; getsource(create_pool), spawn_kwargs[, agent_fleet and the three types with create_pool/ResourcePool/register_template/spawn, over tests
FOUND: inside: test_hebbian_source_key.py:13,:17; test_escalation.py:688,:693; test_runtime_discovery.py:60,:99. Outside (file in tmp_path with data dir tmp_path/data, a path no file holds, or a listing of the data dir's parent): test_runtime, test_consensus_integration, test_escalation's fixture, test_ad1185:1220-1233, test_ad152_regressions:472,:564, test_ad1263:396, test_ad1272:306, the NL tests of test_dreaming, test_experience_nl_memory, test_introspect, test_expansion_agents, test_decomposer:632-640, the federation fixture (federation_cluster.py:681); the rest name an intent in a message, DAG node, counter or descriptor. No getsource or spawn_kwargs[; agent_fleet source scans at test_ad1234:78-80, test_identity_deterministic:56-58, test_bf880_codebase_index_test_discovery:35,:43; one pool of these types through the real factory, test_bf879_designed_agents_start_probationary:132 (no file)
HOLDS: no, for v1's claim; D7 handles the three; limit L9
A4 CLAIM: no caller needs a path of the floor that moves; no test asserts info()["trust_score"] of these agents; no src or ui code reads a pool member's trust_score
RUN:   git grep -n -E "[\"'](read_file|stat_file|list_directory|search_files)[\"']" d9b2a9da -- src (58 hits in 20 files; 59 in 20 on 6ee2bfa0), each file read for its role; git grep -n -E "\.info\(\)" over tests (11 sites in 8 files) crossed with trust_score; "trust_score" over src and ui/src; "\.info\(\)" over src; PROBOS_DATA_DIR|--data-dir over Dockerfile, docker, config, scripts, docs
FOUND: senders to the pools: reply_pipeline.py, stored_list.py:48, organizer_agents.py:59,:124, the decomposer's DAGs, red_team.py:117,:119; the other 14 files are descriptors, examples, swe-harness tool ids, an allowlist, a test double and an MCP connector name. info() is called in 8 test files (none reads a pool member's trust_score) and in introspect.py:361,:502 (overwrites the field), pool.py:678, runtime.py:2362,:6416, pool_group.py:104; ui: useStore.ts:1940 (the crew manifest). No shipped launcher puts ~/.probos under a data directory
HOLDS: yes
A5 CLAIM: no AD-1346 census row or anchor changes
RUN:   git grep -n -E "probos/runtime\.py|probos/security/file_access\.py|probos/agents/(file_search|directory_list|file_reader|stored_list)\.py|agents/utility/(stored_list|productivity_agents|organizer_agents)\.py" d9b2a9da -- tests/fixtures scripts
FOUND: ad1346_file_write_census.py:227 (file_access.py, scope PinnedDirectory.write_new/publish_file/remove_file), ad1346_store_family_census.py:182,:190 (runtime.py, scope ProbOSRuntime._emit_event), scripts/select_tests.py:218; no fixture names the three agent files, file_reader.py or stored_list.py; the blocks add no write, link, delete, network, subprocess or store primitive
HOLDS: yes (G2 runs the census tests and the checker)
A6 CLAIM: no BF-944 other than #1717
RUN:   git log --all --format=%s | Select-String BF-944; Get-ChildItem D:\ProbOS-worktrees\*\prompts and D:\ProbOS\prompts for bf-944*; gh issue list --state all --search "BF-944 in:title"; git grep -n BF-944 d9b2a9da -- PROGRESS.md DECISIONS.md docs/development/roadmap.md
FOUND: 0; 0; one issue, #1717 (OPEN); DECISIONS.md:1422 and PROGRESS.md:4 (BF-961's entry), the roadmap 0; the highest BF in git subjects is 961
HOLDS: yes
A7 CLAIM: BF-961's and BF-945's tests build no pool of these types and no runtime
RUN:   git grep -n -E "create_pool|agent_fleet|ResourcePool|ProbOSRuntime|spawner|register_template|runtime_factory" d9b2a9da -- tests/test_bf961_unreadable_stored_list.py; likewise over tests/test_bf945_red_team_url_floor.py
FOUND: 0 and 0; test_bf961_unreadable_stored_list.py:55 builds its readers as FileReaderAgent(agent_id=..., runtime=runtime)
HOLDS: yes
A8 CLAIM: no case of the new file depends on the todo or scheduler agents, on ~/.probos, or on a refusal reading as an empty list
RUN:   Select-String -Path <N1-1 as extracted> -Pattern "todo|schedul|reminder|productiv|organiz|\.probos|empty list|UnreadableListGuard"
FOUND: 0 hits on v1's 33-case text and 0 on this 34-case text; T11's "came back empty" is the DM seam's wording for a failed result (reply_pipeline.py:1552)
HOLDS: yes
```

## 12. Prior Art and Blind Spots

- **Adopted:** M3e1's per-type rule and test model (SW1, SW3); BF-808's "the pool owns the dependencies its members were built with"; BF-908's one composition per search and its drop of a refused match; BF-948's `ListFilesTool` and link test; BF-758's controls; BF-961's `read_stored_list`. **Rejected:** `code_search._ReadFloor`; a `..` rule; `reader_spelling` (L5). **External:** none consulted.
- **Blind spots handled:** a respawn that loses the runtime (T9); a junction `is_symlink()` does not see; a `..` pattern; the floor moving with the runtime (T2, T4, T7); the trust score (T10); the DM seam (T11); a policy that cannot decide (T12); the bundled agents' read (T13); a started runtime's own tests reading inside its data directory (D7).
- **What discards a correct result:** a refused name is dropped by design; an admitted entry or match dropped by mistake would refuse a readable path (G1 pins ordinary paths, G2 links inside the roots). A refused `~/.probos` read now ends the todo and scheduler intents (BF-961; L6).

## 13. Diff Reviewer: properties to verify

1. `create_pool` hands `self` to a pool of `file_reader`, `directory_list` and `file_search` when the caller passed no `runtime`, and to no other type by this block; M3e1's block and `agent_fleet.py` are unchanged; start, recycle, refill and add carry it (`pool.py:209`, `:308`, `:533`, `:620`).
2. `ReadFloor` composes the three root lists as `resolve_for_runtime` does, decides by `resolve_read_path`, and catches `FileAccessDenied`. In `_search_files` it is built after the walk and asked about every match on both engines (the base is still resolved by `resolve_for_runtime`: its literal must stay in each class's source, `test_bf758_file_read_confinement.py:292-326`); in `_list_directory` it is asked before `entry.stat()` for an `is_symlink()` or `is_junction()` entry, and any other entry reaches `stat()` as before.
3. With `read_roots` empty no ordinary path's answer changes (G1); trace each row of D2's table and the effects table once.
4. At M1 every xfail case fails at an `assert` of its own body, the file collects on the unfixed tree, no premise line fails, no BF-944 name is imported.
5. N2-2 to N2-4 move a file or a data directory and change no assertion; search the tests for another read inside a runtime's data directory (`ProbOSRuntime(...data_dir=tmp_path`, `tmp_path / "data" /`) and say what you find. The P2-5 comment repeats BF-961's L4 sentence; no other text of `config.py` changes.
6. Search this text, the PROGRESS and DECISIONS entries and the code comments for "only", "each", "every", "all", "never", "nothing" and "no one", and check each hit against the code or the tests.
7. No test that BF-944 adds or changes counts `resolve_read_path` or `Path.resolve` calls, or times a search (it would pin L3 as the contract); the unchanged workspace tests count `Path.resolve` calls for another subject (`test_ad1240_workspace_results.py:182-191`); the follow-up recorded for L3 asserts no more calls than directories plus links.

## 14. Acceptance criteria

- G1, G2 and G3 pass as stated, and the batch's broad gate is green with a receipt.
- A read, list or search through a pool-built agent outside `read_roots` is refused with the policy's reason and served inside; with `read_roots` empty an ordinary path's answer is the unwired agent's (G1, T1); the floor is the runtime's (T2, T4, T7).
- A link entry whose target is refused reports no kind and no size (T3); a search names no match under a `..` pattern or through a link whose target is refused (T5, T6); a link whose target is admitted is unchanged (G2).
- Recycle, refill and add keep the runtime (T8, T9); `info()` reports the runtime's trust score (T10); the DM seam refuses an outside path and serves an inside one (T11); an undecidable policy fails closed (T12); the stored-list read fails closed outside the roots (T13); the three tests of D7 read outside their data directory and pass.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
