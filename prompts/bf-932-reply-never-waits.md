# BF-932 (#1670) batch 1: the dream cycle gives the event loop turns (D1), a loop-stall sampler names any blocker (D2), and the Captain's DM stops waiting for the camera (S1)

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-27
**Status:** ready to build. **Owning issue:** #1670 (stays open until the Captain's live re-measurement). Commit bodies say `Refs #1670.`
**Base:** main `63c536b34042e81a1eadea4b457c572bf341d9e7`, branch `fix/bf932-reply-never-waits-20261127`. **Number:** BF-932 (existing; no new AD or BF number).
**License posture:** standard library only, no third-party component.
**Line endings:** the working copies may be CRLF and the blocks below are LF; match after normalising. Every SEARCH starts at the beginning of a line and occurs once in its file at its turn on the clean base. All new text is ASCII.
**Estimated tests:** 26 new items in 3 new files (D1 6, D2 17, S1 3); changed in place: 3 tests and 1 helper in `tests/test_bf932_reply_path_timing.py`, 1 in `tests/test_dm_camera_hook_deadline.py`, 3 in `tests/test_ad978_group_perception.py`, 1 pin each in `tests/test_ad1270e1_config_facade.py`, `tests/test_ad1270e2_config_models.py`, `tests/test_ad1152_agentic_correlation.py`; 1 autouse fixture in `tests/conftest.py`; 0 removed.
**Scope boundary:** no edit to `src/probos/routers/avatars.py`, `src/probos/audio/`, `src/probos/attachments/`, `ui/src/audio/`, `src/probos/utils/step_timing.py` (shared with the voice track) or `config/system.yaml`.

## 1. Problem (premise table)

| Where | What it does today | Effect |
|---|---|---|
| Live log `probos.log.1`, 2026-10-25 19:28:56 to 19:29:14 | no line from any logger for 18 s; the camera consumer logs every 1 to 3 s before and after. The dream's Step 7f archived procedures at 19:28:38-39; Step 7h wrote `procedures/cc82c2c9...yaml` and Step 8 logged `Dream cycle predicted 4 capability gaps` at 19:29:18 | the event loop was held between Step 7f and Step 7h, where Steps 7f2 and 7g run. The Captain's message of 19:29:18 arrived as it ended |
| Live log, 2026-10-30 23:40:49 to 23:41:07 | 18 s with no line; the next lines are a TTS route with `store_ms=17618`, `Record written: procedures/be8baa98...yaml` and `Dream cycle predicted 4 capability gaps` | the same position in a second dream; a store write waited 17.6 s behind the loop |
| Live log, 2026-10-25 19:29:38 to 19:29:49 (the window the issue measured) | `probos.heartbeat` logged `uptime=427s` at 19:29:46, exactly 60 s after `uptime=367s` (`__main__.py`:923-931, a 60 s `asyncio.sleep` loop) | that hole was not a loop block: the loop ran its timer on time. Something awaited there (the consult's H-hook or H-recall) |
| Live log, 19:23:41 to 19:46:12 (pid 61060) | 7 of the 22 gaps between heartbeats exceed 60 s by 2 to 6 s (`uptime` 183 to 246, 609 to 671, 731 to 795, 856 to 922, 983 to 1045, 1285 to 1347, 1347 to 1412) | the loop was blocked at those instants too, some outside the two full-dream windows (19:28:38-19:29:24, 19:42:5x): other blockers exist, which D2 must name |
| `dreaming.py`:924-1229, Step 7g (AD-551) | `list_entries("notebooks/")` (:932), then `read_entry` of each note for the per-agent pass (:949-957) and again for the cross-agent pass (:1065-1075); per-agent pairs (:963-970) and all cross-agent pairs (:1079-1088), each pair re-tokenising the inner note (`text_to_words` :966, :1084); coherence pairs per component (:1110-1115). No `await` in :961-989, :1077-1102, :1107-1116; `read_entry` and `list_entries` contain no `await` (section 10) | with 2,777 notes on the vessel (Glob `notebooks/*/*.md` under `%LOCALAPPDATA%\ProbOS\data\ship-records`, 0 archived), Step 7g reads and YAML-parses every note three times and runs 2777*2776/2 = 3,854,476 cross-pass iterations without one turn for the loop |
| `episodic.py`:2670-2692, Step 7f2 (AD-873, `dreaming.py`:911) | up to 500 episodes (`limit=500`, :2613), each a synchronous `_collection.get` and `_collection.update` (`update_episode_metadata` :2482-2511, no `await`) | up to 1,000 synchronous Chroma calls without a turn |
| `records_store.py`:1571-1608, `list_entries` | reads and parses each file (:1584-1585) in one synchronous pass; called by Step 7g (:932), AD-555 (`notebook_quality.py`:217) and AD-563 (`knowledge_linter.py`:58) in every dream | three more full passes per dream without a turn |
| `routers/agents.py`:3494, `thread_fanout.py`:406 | `await _consumer.force_describe_current_frame(timeout_s=4.0)` before the scene is rendered | the Captain's reply and every group round wait up to BF-977's 4 s deadline for a describe (the consult's H-hook) |
| none | no instrument names what holds the loop | the next blocker is found only by reading log gaps by hand |

## 2. Overview

- **D1.** A counter `LoopYield(every)` (new `utils/loop_yield.py`) says when a synchronous loop should `await asyncio.sleep(0)`. Step 7g yields every 16 reads or word sets and every 2,000 pair iterations, and builds each note's word set once instead of once per pair. `list_entries` yields every 16 files in its default mode; the strict mode keeps one uninterrupted pass. The AD-873 sweep yields every 8 episodes. The budgets are counts, not times. Clusters, convergence events and reports are unchanged.
- **D2.** New `utils/loop_stall.py`: `LoopStallSampler` beats on the loop every quarter of the threshold. A daemon thread reads the beat. When the beat is older than the threshold, the thread logs one WARNING with the loop thread's innermost frames as `dir/file.py:line function`; when the beat moves again, it logs one INFO. At most 10 WARNINGs per 60 s (`suppressed=N` on the next). `ProbOSRuntime.start` spawns it last through `_spawn_background`; it stops watching when `shutdown()` begins, and the AD-824 sweep cancels its heartbeat, which joins the thread. One config field: `system.loop_stall_warn_seconds` (default 1.0; 0 starts nothing).
- **S1.** New `refresh_scene_in_background(consumer, *, timeout_s)` in `perception/consumer.py` starts `force_describe_current_frame` as a task held in a module set and returns. The DM route and the group round call it instead of awaiting the describe. BF-977's deadline and single-flight permit run unchanged inside the call. The route line writes `hook=scheduled`.

Rejected, one line each:
- D1 in a worker thread (`asyncio.to_thread`): the pure-Python kernel holds the GIL, but CPython forces a switch every `sys.getswitchinterval()` (5 ms), so the loop would get its turns and the output would stay identical over a snapshot. It is still rejected: it needs the kernel extracted into a pure function (a larger diff), a running thread cannot be cancelled (a dream cancelled at shutdown would wait for it), and it holds a default-executor thread that the records store's git calls share (the consult's H-pool).
- D1 in a process pool: on Windows each worker spawns and re-imports `probos` and pickles 2,777 word sets per pass, and the reads cannot move with it.
- D1 with an exact prune (Jaccard <= min/max set size) or an inverted index: a speedup the property does not need, and it adds a float-equality proof. Considered, deferred.
- D2 with asyncio debug mode (`slow_callback_duration`): debug mode is costly everywhere and reports a callback's repr after it returns, not the stack while it blocks.
- D2 with `faulthandler.dump_traceback_later`: a single process-wide timer (re-arming it from the heartbeat cancels any other user), and it writes every thread's stack to a file descriptor, outside the log, with no resume line and no bound.
- D2 through `TimingLines` (`step_timing.py`): it writes at INFO, and that file is shared with the voice track (scope boundary). `_WarningBudget` repeats its rule (about 20 lines).
- A new config model for D2: it would add a public name, a model and a section to every frozen consumer. One field on `SystemInfo` adds only a field.
- S1 with a shorter deadline, or waiting only when the message mentions vision: either still spends the wait on a reply.

## 3. Decisions

| # | Decision | Reason |
|---|---|---|
| D1 | Blocking sites and the fix for each are in section 3a. Budgets: 2,000 pair iterations, 16 reads or word sets, 16 listed files, 8 episodes, per turn | (a) is the smallest change that makes "no unbounded run of synchronous units" true, with identical output: the same comparisons run in the same order, and only `await asyncio.sleep(0)` is added between them. Precomputing word sets is exact (`text_to_words` is pure: `similarity.py`:17-19). Only the per-unit cost is unmeasured; D2 names any segment that still exceeds the threshold |
| D1b | `list_entries(strict=True)` is not paced | its callers (`archive_promotion.py`:310; `stand_down.py`:281, under `asyncio.wait_for`) treat the listing as one pass in which a listed file that cannot be read means "retry". A turn in the middle would let a loop-thread writer (Step 7g's archive rename, `dreaming.py`:1025) change the tree mid-listing |
| D1c | Step 12's bulk Chroma calls (`dreaming.py`:1584, :315 via `_get_importance_map`) are not changed | each is one synchronous call, not a loop, so a yield cannot split it. Moving it to a thread needs a Chroma thread-safety review (the consult deferred this). If D2 names them on the vessel, batch 2 takes them |
| D2 | Heartbeat coroutine plus daemon thread plus `sys._current_frames()`; one WARNING per stall, one INFO per resume of a reported stall; 10 per 60 s | the frames are read while the loop is blocked, so the line names the blocker (section 1's need). `lookup_lines=False`: no file read while the GIL is held. No locals and no arguments are captured. `requires-python = ">=3.12"` (`pyproject.toml`:9): CPython issue 106883 (a collection inside `sys._current_frames` deadlocked) was seen on 3.11 |
| D2b | Config: `SystemInfo.loop_stall_warn_seconds: float = 1.0`, `ge=0`, `le=60`, finite, 0 or at least 0.1 (validator); 0 is the kill switch | on by default (the Captain's direction). One float field: no config-profiles row (`check_config_profiles.py`:166-171 lists only default-False bools). A yaml that sets the key still loads after a revert: `SystemInfo` has no `extra="forbid"` |
| D2c | Spawned last in `start()` (after the SQLite backup loop, before `self._startup_complete = True`, which stays last: `test_issue1419_failed_start_rollback.py`:164). `active=lambda: not self._shutdown_started` | a failed start never spawns it, so the rollback tests see nothing new. Shutdown's own synchronous steps are not reported; they are not the reply path |
| D2d | `tests/conftest.py` makes `LoopStallSampler.run` a no-op unless the test requests `bf932_live_loop_stall_sampler` | a loaded test host pauses a process for over a second now and then, and many booted tests assert that no WARNING was written (96 files match `levelno >= logging.WARNING`-style checks). The real sampler runs in the D2 tests, including a booted runtime |
| S1 | Module helper `refresh_scene_in_background` returning the `asyncio.Task` (never `None`; both callers check the consumer first). Called inside each site's existing `try` | the 7 test files that fake only `force_describe_current_frame` keep working; a consumer whose method does not return a coroutine makes `create_task` raise `TypeError` inside the same `try`, as `await` did. Held in `_SCENE_REFRESH_TASKS` until done (no fire-and-forget); a failure is logged once at WARNING by the done callback |
| S1b | The live-frame-aware freshness check is deferred | the reply renders the working memory as it is. After more than `prompt_freshness_seconds` (120 s, `config.py`:2320) with no new described observation, the first reply gets the AD-1055 sentinel "Camera not active..." (`working_memory.py`:124-134) although the camera is on. That happens when the Captain has been idle and the scene is still (the supervisor drops low-novelty frames). The zero-code mitigation is one warm-up message before recording (section 15). If a recording shows the sentinel anyway, that is the trigger to build the check |
| S2/S3 | Not in this contract | the slot and priority (S2) and the recall budget (S3) bound `await` waits. The consult ranked them on evidence from a window that section 1 shows was not a loop block. After batch 1, the live `BF-932: dm turn` fields (`perceive_ms`, `recall_ms`), the `AD-672: Promoted queued intent ... waited_ms` lines and D2's lines show which of them is needed. Batch 2 is drafted from those numbers |

### 3a. Enumeration of the dream cycle's synchronous loops (vessel scale: 2,777 notes, 17 agents, `replay_episode_count: 50` in `config/system.yaml`:221)

| Step (file:line) | Work | Size at vessel scale | `await` inside? | Verdict and fix |
|---|---|---|---|---|
| 2, 3, 3.5, 4 (`dreaming.py`:486-505) | in-memory over the replayed episodes | `recent(k=50)`; 3.5 is 1,225 pairs | no | not blocking |
| 6 clustering (:514-572) | `cluster_episodes` per intent group | at most 50 episodes | no | not blocking |
| 7, 7b-7e, 7h, 7i, 11 | LLM calls and store writes | awaited I/O; 7i at most 50 pairs (:1282-1284) | yes | not blocking (not traced line by line) |
| 7f2 decay (`episodic.py`:2670-2692) | sync Chroma get + update per episode | up to 500 episodes, 1,000 calls | no | **blocking**: yield every 8 episodes |
| 7g listing (`records_store.py`:1571-1608) | read + YAML-parse each note | 2,777 files | no | **blocking**: yield every 16 files (default mode) |
| 7g per-agent reads (`dreaming.py`:949-957) | `read_entry`: read + parse (`records_store.py`:1500-1526) | 2,777 | no | **blocking**: yield every 16 reads |
| 7g per-agent pairs (:961-970) | Jaccard per pair, inner note re-tokenised | sum of n_a^2/2, about 226,000 at 17 agents of 163 notes | no | **blocking**: word sets once; yield every 2,000 iterations |
| 7g cross reads (:1065-1075) | `read_entry` again | 2,777 | no | **blocking**: same read counter |
| 7g cross pairs (:1077-1088) | Jaccard per pair, inner note re-tokenised | 3,854,476 iterations | no | **blocking**: word sets once (also counted per 16); yield every 2,000 iterations |
| 7g coherence (:1107-1116) | Jaccard per member pair | k^2/2 per component | no | yield every 2,000 (same counter); reuses the word sets |
| 7g BFS (:979-987, :1094-1102) | `queue.pop(0)` with duplicates | O(edges), large only if most notes are similar | no | residual, unchanged |
| 7g `word_sets` (:1130) | one tokenisation per member | k per component | no | unchanged |
| 10 AD-555 (`notebook_quality.py`:217-253) | `list_entries` + linear pass | 2,777 | no | covered by the listing fix |
| 10 AD-563 (`knowledge_linter.py`:58-101) | `list_entries` + pairs within one topic | entries carry no `content` key (`records_store.py`:1605), so each pair compares `""` | no | covered by the listing fix; pairs not blocking |
| 10 AD-444, AD-564, AD-565 (:1458-1520) | per-entry and per-agent loops | in memory; 17 agents | no | not blocking (AD-444 size not measured) |
| 12 pruning (:1564-1669) | `_collection.count()` :1584; one bulk `get(ids=...)` in `_get_importance_map` :315; `get_episode_ids_older_than` (not traced) | single calls | n/a | residual (D1c) |
| 9, 13 (:1393-1431, :1671-1700) | Ward Room reads and metrics | not traced | not traced | residual; D2 names them if they block |

## 4. Milestones and commits

Apply in this order; one commit per slice, then the trackers. Stage explicit paths only (never `git add -A`). Run `git diff --cached --stat` before each commit.

| Commit | Sections | Subject |
|---|---|---|
| 1 (D1) | 6.1-6.5 | `The dream cycle's notebook and decay passes give the event loop a turn every fixed count of units` |
| 2 (D2) | 6.6-6.13, then the generators of 4a | `A loop-stall sampler logs the stack of whatever holds the event loop past a configured threshold` |
| 3 (S1) | 6.14-6.20 | `The DM route and group rounds start the camera describe in the background; the reply no longer waits for it` |
| 4 (trackers) | 6.21-6.22, then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` (no `--online`); stage `docs/development/ad-ledger-snapshot.json` and `docs/development/open-ads-report.md` when they change | `Reply-path trackers: PROGRESS and DECISIONS entries for the dream yields, the loop-stall sampler and the background scene refresh` |

No subject carries an `AD-` or `BF-` token or the words close, fix or resolve. Each body says `Refs #1670.`

### 4a. Config generators (end of D2, in this order; the generated files go in commit 2)

```text
d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_config_reference.py
d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_config_facade.py --update-baseline
d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_config_facade.py --check
d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_config_profiles.py --check
```
Expected diff (the orchestrator measures it; any other file, model or row is a hard stop for the Architect):
- `docs/development/config-reference.md`: one row for `loop_stall_warn_seconds` in the `system` table, and the model's new docstring line.
- `docs/development/config-facade-baseline.yaml`: a field line `- {default: '1.0', name: loop_stall_warn_seconds}` under `SystemInfo`; `schema_sha256` moves for `SystemInfo` and `SystemConfig`; `field_definitions` 1877 to 1878 and `canonical_dump_leaves` +1; `canonical_dump_sha256` moves.
- No `config-profiles.yaml` row (bools only).

**Shared trackers.** Another orchestrator merges into `PROGRESS.md`, `DECISIONS.md` and the ledger pair. At build time, anchor P33 on whatever `# ProbOS Progress` heading is there, and P34 on the newest `### ` heading of `DECISIONS.md` (read it with `rg -n "^### " DECISIONS.md | head -3`); regenerate the ledger after the merge rather than resolving it by hand.

## 5. Builder: may and may not

- **May:** apply the pairs in order; write the new files; run the four generators of 4a and `gen_ad_ledger.py`; run `git diff --check` and `git diff --stat`.
- **May not:** run tests, commit, edit an unnamed file, add `skip` or a retry, or reword an anchor. If a SEARCH does not match exactly once, stop and report.

## 6. The pairs

### 6.1 `src/probos/utils/loop_yield.py`

New file:

```python
"""BF-932 (#1670): give the event loop a turn every N units of synchronous work.

A coroutine that loops over synchronous work (file reads, pair comparisons, store calls) without an ``await`` holds
the event loop for the whole loop. ``LoopYield.due()`` counts units; on every ``every``-th unit it returns True and
the caller awaits ``asyncio.sleep(0)``, which lets each ready callback run once. The budget is a count of units, not
a time, and the work and its order are unchanged.
"""

from __future__ import annotations


class LoopYield:
    """Counts units of synchronous work; ``due()`` is True on every ``every``-th unit."""

    __slots__ = ("_count", "_every")

    def __init__(self, every: int) -> None:
        if every < 1:
            raise ValueError("every must be at least 1")
        self._every = every
        self._count = 0

    def due(self) -> bool:
        """Count one unit; True when the caller should ``await asyncio.sleep(0)`` now."""
        self._count += 1
        if self._count >= self._every:
            self._count = 0
            return True
        return False
```

### 6.2 `src/probos/cognitive/dreaming.py`

**P1.** SEARCH:
```python
    episode_ran_in_plan_mode,
)

if TYPE_CHECKING:
```
REPLACE:
```python
    episode_ran_in_plan_mode,
)
from probos.utils.loop_yield import LoopYield  # BF-932

if TYPE_CHECKING:
```

**P2.** SEARCH:
```python
logger = logging.getLogger(__name__)


def _outcome_evidence(episodes: list[Any]) -> list[Any]:
```
REPLACE:
```python
logger = logging.getLogger(__name__)

# BF-932 (#1670): Step 7g gives the event loop a turn every this many notebook reads or word sets, and every this many
# pair iterations. Counts, not times: the loop-stall sampler (probos.utils.loop_stall) shows what a turn costs.
_STEP_7G_READS_PER_YIELD = 16
_STEP_7G_PAIRS_PER_YIELD = 2000


def _outcome_evidence(episodes: list[Any]) -> list[Any]:
```

**P3.** SEARCH:
```python
                threshold = self.config.notebook_consolidation_threshold
                min_entries = self.config.notebook_consolidation_min_entries

                for agent_cs, entries in agents_entries.items():
                    if len(entries) < min_entries:
                        continue
                    # Load content for each entry
                    loaded: list[dict] = []
                    for ent in entries:
                        try:
```
REPLACE:
```python
                threshold = self.config.notebook_consolidation_threshold
                min_entries = self.config.notebook_consolidation_min_entries
                # BF-932 (#1670): this step's reads and comparisons have no await of their own, so they gave the
                # event loop no turn for the whole step; these counters give it one every so many units.
                read_pacer = LoopYield(_STEP_7G_READS_PER_YIELD)
                pair_pacer = LoopYield(_STEP_7G_PAIRS_PER_YIELD)

                for agent_cs, entries in agents_entries.items():
                    if len(entries) < min_entries:
                        continue
                    # Load content for each entry
                    loaded: list[dict] = []
                    for ent in entries:
                        if read_pacer.due():
                            await asyncio.sleep(0)  # BF-932: read_entry reads and parses without an await
                        try:
```

**P4.** SEARCH:
```python
                    n = len(loaded)
                    adj: dict[int, set[int]] = {i: set() for i in range(n)}
                    for i in range(n):
                        words_i = text_to_words(loaded[i]["_content"])
                        for j in range(i + 1, n):
                            words_j = text_to_words(loaded[j]["_content"])
                            sim = jaccard_similarity(words_i, words_j)
```
REPLACE:
```python
                    n = len(loaded)
                    adj: dict[int, set[int]] = {i: set() for i in range(n)}
                    # BF-932: each note's word set once (text_to_words is pure), not once per pair
                    entry_words = [text_to_words(item["_content"]) for item in loaded]
                    for i in range(n):
                        words_i = entry_words[i]
                        for j in range(i + 1, n):
                            if pair_pacer.due():
                                await asyncio.sleep(0)  # BF-932: give the event loop a turn
                            words_j = entry_words[j]
                            sim = jaccard_similarity(words_i, words_j)
```

**P5.** SEARCH:
```python
                    # Load content for cross-agent comparison
                    cross_loaded: list[dict] = []
                    for ent in agent_dept_entries:
                        try:
```
REPLACE:
```python
                    # Load content for cross-agent comparison
                    cross_loaded: list[dict] = []
                    for ent in agent_dept_entries:
                        if read_pacer.due():
                            await asyncio.sleep(0)  # BF-932: read_entry reads and parses without an await
                        try:
```

**P6.** SEARCH:
```python
                    n_cross = len(cross_loaded)
                    cross_adj: dict[int, set[int]] = {i: set() for i in range(n_cross)}
                    for i in range(n_cross):
                        words_i = text_to_words(cross_loaded[i]["_content"])
                        for j in range(i + 1, n_cross):
                            if cross_loaded[i]["agent"] == cross_loaded[j]["agent"]:
                                continue  # skip same-agent pairs
                            words_j = text_to_words(cross_loaded[j]["_content"])
                            sim = jaccard_similarity(words_i, words_j)
```
REPLACE:
```python
                    n_cross = len(cross_loaded)
                    cross_adj: dict[int, set[int]] = {i: set() for i in range(n_cross)}
                    # BF-932: each note's word set once (text_to_words is pure), not once per pair
                    cross_words: list[set[str]] = []
                    for item in cross_loaded:
                        if read_pacer.due():
                            await asyncio.sleep(0)  # BF-932: give the event loop a turn
                        cross_words.append(text_to_words(item["_content"]))
                    for i in range(n_cross):
                        words_i = cross_words[i]
                        for j in range(i + 1, n_cross):
                            if pair_pacer.due():
                                await asyncio.sleep(0)  # BF-932: give the event loop a turn
                            if cross_loaded[i]["agent"] == cross_loaded[j]["agent"]:
                                continue  # skip same-agent pairs
                            words_j = cross_words[j]
                            sim = jaccard_similarity(words_i, words_j)
```

**P7.** SEARCH:
```python
                            for ci in range(len(component)):
                                wi = text_to_words(cluster_entries[ci]["_content"])
                                for cj in range(ci + 1, len(component)):
                                    wj = text_to_words(cluster_entries[cj]["_content"])
                                    total_sim += jaccard_similarity(wi, wj)
                                    pairs += 1
```
REPLACE:
```python
                            # BF-932: the word sets built above, in the component's order; the sum's order is unchanged
                            member_words = [cross_words[idx] for idx in component]
                            for ci in range(len(component)):
                                wi = member_words[ci]
                                for cj in range(ci + 1, len(component)):
                                    if pair_pacer.due():
                                        await asyncio.sleep(0)  # BF-932: give the event loop a turn
                                    wj = member_words[cj]
                                    total_sim += jaccard_similarity(wi, wj)
                                    pairs += 1
```

`asyncio` is imported at `dreaming.py`:10. `cluster_entries[ci]` is `cross_loaded[component[ci]]` (:1103), so `member_words[ci]` is `text_to_words(cluster_entries[ci]["_content"])`.

### 6.3 `src/probos/knowledge/records_store.py`

**P8.** SEARCH:
```python
from probos.utils.frontmatter import dump_frontmatter, load_frontmatter, split_frontmatter
```
REPLACE:
```python
from probos.utils.frontmatter import dump_frontmatter, load_frontmatter, split_frontmatter
from probos.utils.loop_yield import LoopYield  # BF-932
```

**P9.** SEARCH:
```python
_RECORDS_YAML_LOADER: Any = yaml.CSafeLoader if getattr(yaml, "__with_libyaml__", False) else yaml.SafeLoader
```
REPLACE:
```python
_RECORDS_YAML_LOADER: Any = yaml.CSafeLoader if getattr(yaml, "__with_libyaml__", False) else yaml.SafeLoader

# BF-932 (#1670): a default-mode listing gives the event loop a turn every this many files (a count, not a time).
_LIST_FILES_PER_YIELD = 16
```

**P10.** SEARCH:
```python
        found = _markdown_files(search_path, strict=strict)

        for md_file in sorted(found):
            rel_path = str(md_file.relative_to(root)).replace("\\", "/")
```
REPLACE:
```python
        found = _markdown_files(search_path, strict=strict)
        # BF-932 (#1670): each file is read and parsed without an await, so a large directory held the event loop for
        # the whole listing. The default mode gives the loop a turn every _LIST_FILES_PER_YIELD files; the strict mode
        # (the stand-down's and the archive promotion's reads) keeps its one uninterrupted pass.
        pacer = None if strict else LoopYield(_LIST_FILES_PER_YIELD)

        for md_file in sorted(found):
            if pacer is not None and pacer.due():
                await asyncio.sleep(0)
            rel_path = str(md_file.relative_to(root)).replace("\\", "/")
```

`asyncio` is imported at `records_store.py`:3.

### 6.4 `src/probos/cognitive/episodic.py`

**P11.** SEARCH:
```python
from probos.types import EBBINGHAUS_DEFAULT_STABILITY_SECONDS

logger = logging.getLogger(__name__)
```
REPLACE:
```python
from probos.types import EBBINGHAUS_DEFAULT_STABILITY_SECONDS
from probos.utils.loop_yield import LoopYield  # BF-932

logger = logging.getLogger(__name__)

# BF-932 (#1670): the AD-873 decay sweep gives the event loop a turn every this many episodes (a count, not a time).
_DECAY_EPISODES_PER_YIELD = 8
```

**P12.** SEARCH:
```python
        now = time.time()
        for i, ep_id in enumerate(ids):
            try:
                meta = metas[i] if i < len(metas) else {}
                ep = self._metadata_to_episode(ep_id, "", meta or {})
```
REPLACE:
```python
        now = time.time()
        # BF-932 (#1670): each episode is a synchronous Chroma read and write, so the page held the event loop for the
        # whole sweep; give the loop a turn every _DECAY_EPISODES_PER_YIELD episodes.
        pacer = LoopYield(_DECAY_EPISODES_PER_YIELD)
        for i, ep_id in enumerate(ids):
            if pacer.due():
                await asyncio.sleep(0)
            try:
                meta = metas[i] if i < len(metas) else {}
                ep = self._metadata_to_episode(ep_id, "", meta or {})
```

`asyncio` is imported at `episodic.py`:10. `for i, ep_id in enumerate(ids):` also occurs at :929; the SEARCH starts at `now = time.time()`, which makes it unique.

### 6.5 `tests/test_bf932_d1_dream_yields.py`

New file:

```python
"""BF-932 (#1670) D1: the dream cycle's synchronous loops give the event loop a turn.

A ticker task counts the turns the event loop gives other tasks. A recorder notes the ticker's count at each unit of
one loop (a pair comparison, a word set, a notebook read, a parsed file, an episode written). The difference between
the first and the last unit of that loop is how many turns the loop gave; at the base each of these loops gave none.
The step's output is compared on a fixed fixture. No assertion bounds a duration.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from probos.cognitive import dreaming
from probos.cognitive.episodic import EpisodicMemory
from probos.cognitive.similarity import jaccard_similarity, text_to_words
from probos.knowledge import records_store as records_module
from probos.knowledge.records_store import RecordsStore
from tests.test_ad551_notebook_consolidation import _entry, _make_engine, _make_records_store, _read_result

# The contract's budgets, written out: a test that read them from the module could not catch a changed budget.
_PAIRS_PER_TURN = 2000
_READS_PER_TURN = 16
_LIST_FILES_PER_TURN = 16
_DECAY_EPISODES_PER_TURN = 8

_ALPHA, _BETA, _GAMMA = 100, 20, 20
_SHARED = "reactor coolant pressure trending above nominal band tonight"  # 8 words
_DUPLICATE = "duplicate finding about the warp core alignment log"


class _Ticker:
    """Counts the event loop's turns for other tasks: one per iteration, each ending in ``sleep(0)``."""

    def __init__(self) -> None:
        self.turns = 0
        self._task: asyncio.Task[None] | None = None

    async def _run(self) -> None:
        while True:
            self.turns += 1
            await asyncio.sleep(0)

    async def __aenter__(self) -> "_Ticker":
        self._task = asyncio.create_task(self._run())
        await asyncio.sleep(0)
        return self

    async def __aexit__(self, *_exc: object) -> None:
        assert self._task is not None
        self._task.cancel()
        await asyncio.gather(self._task, return_exceptions=True)


def _fixture() -> tuple[list[dict], dict[str, dict]]:
    """Three agents in two departments. Alpha's notes 0 and 1 form one per-agent cluster; one note of each agent
    shares 8 of its 10 words with the other two (one convergence, each pair 8/12); every other note is unique."""
    entries: list[dict] = []
    read_map: dict[str, dict] = {}
    plan = (("alpha", "science", _ALPHA, 50), ("beta", "medical", _BETA, 10), ("gamma", "science", _GAMMA, 15))
    for agent, dept, count, convergent in plan:
        for k in range(count):
            path = f"notebooks/{agent}/note-{k:03d}.md"
            if agent == "alpha" and k in (0, 1):
                content = _DUPLICATE
            elif k == convergent:
                content = f"{_SHARED} {agent}-own-a {agent}-own-b"
            else:
                content = " ".join(f"{agent}-{k}-w{m}" for m in range(12))
            entries.append(_entry(path, author=agent, dept=dept, updated=f"2026-04-01T{k % 24:02d}:00:00"))
            read_map[path] = _read_result(path, content)
    return entries, read_map


async def _run_dream(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """One dream cycle over the fixture, with the ticker's count noted at each comparison, word set and read."""
    entries, read_map = _fixture()
    store = _make_records_store(entries, read_map)
    engine = _make_engine(records_store=store)
    events: list[tuple[str, dict]] = []
    engine._emit_event_fn = lambda event_type, data: events.append((event_type, data))
    pair_turns: list[int] = []
    word_turns: list[int] = []
    read_turns: list[int] = []
    reader = store.read_entry.side_effect
    async with _Ticker() as ticker:

        def _pair(a: set[str], b: set[str]) -> float:
            pair_turns.append(ticker.turns)
            return jaccard_similarity(a, b)

        def _words(text: str) -> set[str]:
            word_turns.append(ticker.turns)
            return text_to_words(text)

        async def _read(path: str, reader_id: str = "system", **kwargs: Any) -> Any:
            read_turns.append(ticker.turns)
            return await reader(path, reader_id=reader_id, **kwargs)

        monkeypatch.setattr(dreaming, "jaccard_similarity", _pair)
        monkeypatch.setattr(dreaming, "text_to_words", _words)
        store.read_entry.side_effect = _read
        report = await engine.dream_cycle()
    return {
        "report": report, "store": store, "events": events,
        "pairs": pair_turns, "words": word_turns, "reads": read_turns,
    }


@pytest.mark.asyncio
async def test_d1_step_7g_gives_the_loop_turns_inside_each_of_its_loops(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = await _run_dream(monkeypatch)
    pairs, words, reads = seen["pairs"], seen["words"], seen["reads"]
    notes = _ALPHA + _BETA + _GAMMA
    alpha_pairs = _ALPHA * (_ALPHA - 1) // 2  # alpha is listed first, so its pass makes the first comparisons
    cross_pairs = _ALPHA * _BETA + _ALPHA * _GAMMA + _BETA * _GAMMA  # different-agent pairs; 3 coherence pairs follow
    assert len(pairs) == alpha_pairs + _BETA * (_BETA - 1) // 2 + _GAMMA * (_GAMMA - 1) // 2 + cross_pairs + 3
    assert pairs[alpha_pairs - 1] - pairs[0] >= alpha_pairs // _PAIRS_PER_TURN
    assert pairs[-4] - pairs[-(cross_pairs + 3)] >= cross_pairs // _PAIRS_PER_TURN
    assert reads[_ALPHA - 1] - reads[0] >= _ALPHA // _READS_PER_TURN  # alpha's reads, before its comparisons
    assert reads[-1] - reads[notes] >= notes // _READS_PER_TURN  # the cross-agent pass reads every note again
    assert words[2 * notes - 1] - words[notes] >= notes // _READS_PER_TURN  # the cross-agent pass's word sets


@pytest.mark.asyncio
async def test_d1_step_7g_output_is_the_bases_on_a_fixed_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    """Control: passes on the base too. One per-agent cluster, one convergence, the base's coherence to the bit."""
    seen = await _run_dream(monkeypatch)
    report, store, events = seen["report"], seen["store"], seen["events"]
    consolidated = [
        (call.kwargs["path"], call.kwargs["message"])
        for call in store.write_entry.call_args_list
        if str(call.kwargs.get("message", "")).startswith("AD-551: Consolidated")
    ]
    assert consolidated == [("notebooks/alpha/note-001.md", "AD-551: Consolidated 2 entries")]
    assert report.notebook_consolidations == 1
    convergences = [data for event_type, data in events if event_type == "convergence_detected"]
    assert report.convergence_reports_generated == 1 and len(convergences) == 1
    assert convergences[0]["agents"] == ["alpha", "beta", "gamma"]
    assert convergences[0]["departments"] == ["medical", "science"]
    total = 0.0
    for _ in range(3):
        total += 8 / 12  # each pair shares 8 of 12 distinct words; the sum runs in the base's order
    assert convergences[0]["coherence"] == total / 3


def _notes(root: Path, count: int) -> list[str]:
    folder = root / "notebooks" / "ezri"
    folder.mkdir(parents=True)
    paths: list[str] = []
    for k in range(count):
        (folder / f"note-{k:03d}.md").write_text(f"---\nauthor: ezri\ntopic: t{k}\n---\nbody {k}\n", encoding="utf-8")
        paths.append(f"notebooks/ezri/note-{k:03d}.md")
    return paths


async def _listing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, strict: bool) -> tuple[list[str], list[dict], list[int]]:
    """A real RecordsStore over 40 notes; the ticker's count noted at each file the listing parses."""
    store = RecordsStore(SimpleNamespace(repo_path=str(tmp_path / "records")))
    expected = _notes(tmp_path / "records", 40)
    turns: list[int] = []
    parse = records_module._load_document
    async with _Ticker() as ticker:

        def _parse(raw: str) -> Any:
            turns.append(ticker.turns)
            return parse(raw)

        monkeypatch.setattr(records_module, "_load_document", _parse)
        listed = await store.list_entries("notebooks", strict=strict)
    return expected, listed, turns


@pytest.mark.asyncio
async def test_d1_a_default_listing_gives_the_loop_turns_and_lists_every_note(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected, listed, turns = await _listing(tmp_path, monkeypatch, strict=False)
    assert [entry["path"] for entry in listed] == expected
    assert len(turns) == 40
    assert turns[-1] - turns[0] >= 40 // _LIST_FILES_PER_TURN


@pytest.mark.asyncio
async def test_d1_a_strict_listing_keeps_its_one_uninterrupted_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Control: passes on the base too. The stand-down's and the archive promotion's listing is one pass."""
    expected, listed, turns = await _listing(tmp_path, monkeypatch, strict=True)
    assert [entry["path"] for entry in listed] == expected
    assert len(turns) == 40
    assert turns[-1] - turns[0] == 0


class _Collection:
    """Stands in for chromadb's Collection: the page read, the read by id and the update the AD-873 sweep makes."""

    def __init__(self, count: int, turns: Any) -> None:
        self.ids = [f"ep-{k:03d}" for k in range(count)]
        self._metadata = {episode_id: {"timestamp": 1000.0} for episode_id in self.ids}
        self._turns = turns
        self.updates: list[tuple[str, int]] = []

    def get(self, ids: list[str] | None = None, include: Any = None, limit: Any = None, offset: Any = None) -> dict:
        wanted = list(self.ids) if ids is None else list(ids)
        return {"ids": wanted, "metadatas": [dict(self._metadata[episode_id]) for episode_id in wanted]}

    def update(self, ids: list[str], metadatas: list[dict]) -> None:
        self.updates.append((ids[0], self._turns()))
        self._metadata[ids[0]] = metadatas[0]


@pytest.mark.asyncio
async def test_d1_the_decay_sweep_gives_the_loop_turns_and_writes_every_episode(tmp_path: Path) -> None:
    memory = EpisodicMemory(db_path=tmp_path / "episodic")
    async with _Ticker() as ticker:
        collection = _Collection(40, lambda: ticker.turns)
        memory._collection = collection
        counts = await memory.sweep_episode_decay(None)
    assert counts == {"swept": 40, "reinforced": 0}
    assert [episode_id for episode_id, _turn in collection.updates] == collection.ids
    turns = [turn for _episode_id, turn in collection.updates]
    assert turns[-1] - turns[0] >= 40 // _DECAY_EPISODES_PER_TURN


def test_d1_loop_yield_is_due_on_every_nth_unit_only() -> None:
    from probos.utils.loop_yield import LoopYield  # here, so the base's missing module fails this test alone

    pacer = LoopYield(3)
    assert [pacer.due() for _ in range(7)] == [False, False, True, False, False, True, False]
    with pytest.raises(ValueError):
        LoopYield(0)
```

### 6.6 `src/probos/utils/loop_stall.py`

New file:

```python
"""BF-932 (#1670): the loop-stall sampler names the code that holds the event loop (log-only).

A heartbeat coroutine on the event loop stamps a monotonic clock every quarter of the threshold. A daemon thread reads
the stamp at the same cadence. When the stamp is older than the threshold, the thread reads the loop thread's current
stack (``sys._current_frames``: the file, line and function of the innermost frames; no locals, no arguments, no
source lines) and logs one WARNING for that stall. When the stamp moves again, it logs one INFO with the gap between
the two stamps. WARNING lines are bounded per window, and the next one written says how many were refused
(``suppressed=N``); a resume line is written only for a stall whose WARNING was written.

The sampler changes nothing the loop runs. A failure in the thread is dropped at DEBUG (Tier 1, swallow: a measurement
is never a reason for the vessel to fail). ProbOS requires Python 3.12 or later; CPython issue 106883 (a collection
inside ``sys._current_frames`` deadlocked) was seen on 3.11.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
import time
import traceback
from collections import deque
from collections.abc import Callable
from pathlib import PurePath

logger = logging.getLogger(__name__)

THREAD_NAME = "probos-loop-stall-sampler"
_STACK_DEPTH = 12
_JOIN_TIMEOUT_S = 1.0


def _innermost_frames(thread_id: int, depth: int) -> str:
    """The innermost ``depth`` frames of ``thread_id`` as ``dir/file.py:line function``, innermost first."""
    frame = sys._current_frames().get(thread_id)
    if frame is None:
        return "(no frame)"
    summary = traceback.StackSummary.extract(traceback.walk_stack(frame), limit=depth, lookup_lines=False)
    del frame
    return " <- ".join(
        f"{'/'.join(PurePath(entry.filename).parts[-2:])}:{entry.lineno} {entry.name}" for entry in summary
    )


class _WarningBudget:
    """At most ``max_lines`` WARNING lines per ``window_s``; the next line written after a refusal ends ``suppressed=N``.

    The rule of ``probos.utils.step_timing.TimingLines``, which writes at INFO. It is not reused so that that module,
    which the voice path shares, stays unchanged. ``max_lines`` of 0 or less sets no bound.
    """

    def __init__(self, max_lines: int, window_s: float) -> None:
        self._max_lines = max_lines
        self._window_s = window_s
        self._written: deque[float] = deque()
        self._suppressed = 0

    def emit(self, message: str, *args: object) -> bool:
        """Write the WARNING unless this window's budget is spent; True when it was written."""
        if self._max_lines > 0:
            now = time.monotonic()
            while self._written and now - self._written[0] >= self._window_s:
                self._written.popleft()
            if len(self._written) >= self._max_lines:
                self._suppressed += 1
                return False
            self._written.append(now)
        if self._suppressed:
            message, args = message + " suppressed=%d", (*args, self._suppressed)
            self._suppressed = 0
        logger.warning(message, *args)
        return True


class LoopStallSampler:
    """One heartbeat on the event loop and one daemon thread that watches it (BF-932, #1670).

    ``active`` (optional) is read by the thread on each check; once it returns False the thread ends. ``clock`` is
    the monotonic clock the heartbeat stamps and the thread reads. ``checks``, ``stall_count`` and ``resume_count``
    count the thread's checks, the stalls it found (reported or not) and the stalls that ended.
    """

    def __init__(
        self,
        *,
        threshold_s: float,
        max_warnings: int = 10,
        window_s: float = 60.0,
        active: Callable[[], bool] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not threshold_s > 0:
            raise ValueError("threshold_s must be greater than 0")
        self._threshold_s = threshold_s
        self._tick_s = threshold_s / 4.0
        self._active = active
        self._clock = clock
        self._warnings = _WarningBudget(max_warnings, window_s)
        self._last_beat = clock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.checks = 0
        self.stall_count = 0
        self.resume_count = 0

    async def run(self) -> None:
        """Beat on the running loop and watch it from a daemon thread until cancelled.

        A second ``run`` while the first one's thread is alive returns at once. AD-824: on cancellation the thread is
        told to stop and joined (at most ``_JOIN_TIMEOUT_S``), and the cancellation propagates.
        """
        if self._thread is not None and self._thread.is_alive():
            logger.debug("BF-932: the loop-stall sampler is already running; this start is ignored")
            return
        loop = asyncio.get_running_loop()
        self._stop.clear()
        self._last_beat = self._clock()
        thread = threading.Thread(
            target=self._watch, args=(loop, threading.get_ident()), name=THREAD_NAME, daemon=True,
        )
        self._thread = thread
        thread.start()
        try:
            while True:
                self._last_beat = self._clock()
                await asyncio.sleep(self._tick_s)
        except asyncio.CancelledError:
            logger.debug("AD-824: loop-stall heartbeat cancelled")
            raise
        finally:
            self._stop.set()
            thread.join(timeout=_JOIN_TIMEOUT_S)

    def _watch(self, loop: asyncio.AbstractEventLoop, loop_thread_id: int) -> None:
        """The thread: one check per tick, until stopped, until the loop closes, or once ``active`` says no."""
        stalled_beat: float | None = None
        reported = False
        while not self._stop.wait(self._tick_s):
            try:
                if loop.is_closed() or (self._active is not None and not self._active()):
                    return
                if not loop.is_running():
                    stalled_beat = None  # a loop that is not running is not blocked
                    continue
                self.checks += 1
                beat = self._last_beat
                if stalled_beat is None:
                    age_s = self._clock() - beat
                    if age_s > self._threshold_s:
                        stalled_beat = beat
                        self.stall_count += 1
                        reported = self._warnings.emit(
                            "BF-932: event loop blocked for %.0f ms (threshold %.0f ms); loop thread at: %s",
                            age_s * 1000.0,
                            self._threshold_s * 1000.0,
                            _innermost_frames(loop_thread_id, _STACK_DEPTH),
                        )
                elif beat != stalled_beat:
                    self.resume_count += 1
                    if reported:
                        logger.info(
                            "BF-932: event loop resumed after %.0f ms (heartbeat gap)",
                            (beat - stalled_beat) * 1000.0,
                        )
                    stalled_beat = None
            except Exception:
                try:
                    logger.debug("BF-932: a loop-stall check failed and was dropped", exc_info=True)
                except Exception:
                    pass
```

### 6.7 `src/probos/config_models/core.py`

**P13.** SEARCH:
```python
class SystemInfo(BaseModel):
    """Top-level system identity."""

    name: str = "ProbOS"
    version: str = "0.1.0"
    log_level: str = "INFO"
```
REPLACE:
```python
class SystemInfo(BaseModel):
    """Top-level system identity and process-wide diagnostics."""

    name: str = "ProbOS"
    version: str = "0.1.0"
    log_level: str = "INFO"
    # BF-932 (#1670): the loop-stall sampler (probos.utils.loop_stall), started by ProbOSRuntime.start.
    loop_stall_warn_seconds: float = Field(
        default=1.0, ge=0.0, le=60.0, allow_inf_nan=False,
        description=(
            "BF-932: seconds the event loop may go without a heartbeat before one WARNING names the code "
            "holding it (file:line function of the loop thread's innermost frames). 0 starts no sampler; "
            "otherwise at least 0.1."
        ),
    )

    @field_validator("loop_stall_warn_seconds")
    @classmethod
    def _loop_stall_is_off_or_at_least_a_tenth(cls, value: float) -> float:
        if 0.0 < value < 0.1:
            raise ValueError("loop_stall_warn_seconds is 0 (off) or at least 0.1")
        return value
```

`Field` and `field_validator` are imported at `core.py`:13.

### 6.8 `src/probos/runtime.py`

**P14.** SEARCH:
```python
        self._sqlite_backup_task = self._spawn_background(
            self._sqlite_backup_loop(),
            name="sqlite-backup-loop",
            drain_on_shutdown=True,
        )
```
REPLACE:
```python
        self._sqlite_backup_task = self._spawn_background(
            self._sqlite_backup_loop(),
            name="sqlite-backup-loop",
            drain_on_shutdown=True,
        )

        # BF-932 (#1670): the loop-stall sampler. One WARNING names the code that holds the event loop longer than
        # system.loop_stall_warn_seconds (0 starts nothing). It stops watching once shutdown() begins, and the
        # AD-824 sweep cancels its heartbeat, which joins its thread.
        _loop_stall_s = self.config.system.loop_stall_warn_seconds
        if _loop_stall_s > 0:
            from probos.utils.loop_stall import LoopStallSampler

            self._spawn_background(
                LoopStallSampler(
                    threshold_s=_loop_stall_s,
                    active=lambda: not self._shutdown_started,
                ).run(),
                name="bf932-loop-stall-sampler",
            )
```

### 6.9 `tests/conftest.py`

**P15.** SEARCH:
```python
    stand_in = SimpleNamespace(run=_run, TimeoutExpired=subprocess.TimeoutExpired, calls=calls)
    monkeypatch.setattr(credential_store, "subprocess", stand_in)
    yield calls
```
REPLACE:
```python
    stand_in = SimpleNamespace(run=_run, TimeoutExpired=subprocess.TimeoutExpired, calls=calls)
    monkeypatch.setattr(credential_store, "subprocess", stand_in)
    yield calls


@pytest.fixture(autouse=True)
def _bf932_quiet_loop_stall_sampler(request, monkeypatch):
    """BF-932 (#1670): a booted runtime starts no loop-stall sampler in a test unless the test asks for it.

    The sampler is on by default (system.loop_stall_warn_seconds 1.0) and writes a WARNING when the event loop is held
    that long. A loaded test host pauses a process that long now and then, and many booted tests assert that no
    WARNING was written. So ``LoopStallSampler.run`` returns at once here; a test that requests the
    ``bf932_live_loop_stall_sampler`` fixture (tests/test_bf932_d2_loop_stall_sampler.py) gets the real one.
    """
    if "bf932_live_loop_stall_sampler" in request.fixturenames:
        yield
        return
    from probos.utils import loop_stall

    async def _quiet(self) -> None:
        return None

    monkeypatch.setattr(loop_stall.LoopStallSampler, "run", _quiet)
    yield
```

### 6.10 `tests/test_ad1270e2_config_models.py`

**P16.** SEARCH:
```python
    "system": {"name": "ProbOS", "version": "0.1.0", "log_level": "INFO"},
```
REPLACE:
```python
    # BF-932 (#1670) adds system.loop_stall_warn_seconds (default 1.0) after the move.
    "system": {"name": "ProbOS", "version": "0.1.0", "log_level": "INFO", "loop_stall_warn_seconds": 1.0},
```

### 6.11 `tests/test_ad1152_agentic_correlation.py`

**P17.** SEARCH:
```python
    assert config["security"]["memory"].pop("correlation_cutoff") == 0.0
```
REPLACE:
```python
    assert config["security"]["memory"].pop("correlation_cutoff") == 0.0
    # BF-932's loop-stall threshold (1.0 s; 0 starts no sampler) was added after this capture too. The sampler is
    # started in ProbOSRuntime.start, which this observation never calls.
    assert config["system"].pop("loop_stall_warn_seconds") == 1.0
```

### 6.12 `tests/test_ad1270e1_config_facade.py`

**P18.** SEARCH:
```python
    # AD-1355 S1 (#1700) removes HolodeckBirthChamberConfig's eight fields and SystemConfig.holodeck_birth_chamber (1886 -> 1877).
    assert counts["field_definitions"] == 1877  # AD-1206 intentionally adds github_repository.
```
REPLACE:
```python
    # AD-1355 S1 (#1700) removes HolodeckBirthChamberConfig's eight fields and SystemConfig.holodeck_birth_chamber (1886 -> 1877).
    # BF-932 (#1670) adds system.loop_stall_warn_seconds (1877 -> 1878).
    assert counts["field_definitions"] == 1878  # AD-1206 intentionally adds github_repository.
```

### 6.13 `tests/test_bf932_d2_loop_stall_sampler.py`

New file:

```python
"""BF-932 (#1670) D2: the loop-stall sampler names the code that holds the event loop.

The stalls are real. The loop's own thread blocks until the sampler has reported it: a logging handler on the
sampler's logger sets a ``threading.Event`` when the WARNING names the blocking function, so a stall lasts exactly
until it is detected. A guard timeout fails a hung test; no assertion bounds a duration. tests/conftest.py makes the
sampler a no-op for every other test; each test here that runs it requests ``bf932_live_loop_stall_sampler``.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from collections.abc import Callable

import pytest
from pydantic import ValidationError

from probos.cognitive.episodic_mock import MockEpisodicMemory
from probos.config import SystemConfig, SystemInfo
from probos.runtime import ProbOSRuntime
from probos.utils.loop_stall import THREAD_NAME, LoopStallSampler

_LOGGER = "probos.utils.loop_stall"
_BLOCKED = "BF-932: event loop blocked"
_RESUMED = "BF-932: event loop resumed"
_TASK_NAME = "bf932-loop-stall-sampler"
_GUARD_S = 30.0


@pytest.fixture
def bf932_live_loop_stall_sampler() -> None:
    """Asks tests/conftest.py's _bf932_quiet_loop_stall_sampler to leave the real sampler in place."""
    return None


class _Signals(logging.Handler):
    """The sampler's lines as written; sets ``blocked`` for a WARNING naming ``marker`` and ``resumed`` for an INFO."""

    def __init__(self, marker: str) -> None:
        super().__init__(level=logging.DEBUG)
        self.marker = marker
        self.blocked = threading.Event()
        self.resumed = threading.Event()
        self.lines: list[tuple[int, str]] = []

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        self.lines.append((record.levelno, message))
        if record.levelno == logging.WARNING and message.startswith(_BLOCKED) and self.marker in message:
            self.blocked.set()
        elif record.levelno == logging.INFO and message.startswith(_RESUMED):
            self.resumed.set()


def _samplers(before: set[threading.Thread]) -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t not in before and t.name == THREAD_NAME and t.is_alive()]


async def _until(predicate: Callable[[], bool]) -> None:
    """Yield to the loop until ``predicate`` holds; the guard fails a test that never gets there."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _GUARD_S
    while not predicate():
        assert loop.time() < deadline, "guard: the awaited condition never held"
        await asyncio.sleep(0.01)


def _hold_the_loop_until(event: threading.Event) -> None:
    """Blocks the event loop's own thread until the sampler reports it; the WARNING must name this function."""
    assert event.wait(_GUARD_S), "guard: the sampler never reported the blocked loop"


def _hold_the_loop_while(predicate: Callable[[], bool]) -> None:
    """Blocks the event loop's own thread while ``predicate`` holds; ``time.sleep`` lets the sampler's thread run."""
    deadline = time.monotonic() + _GUARD_S
    while predicate():
        assert time.monotonic() < deadline, "guard: the sampler never counted the stall"
        time.sleep(0.005)


async def _stop(task: asyncio.Task[None]) -> None:
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_d2_a_blocked_loop_gets_one_warning_naming_the_blocker_then_a_resume_line(
    bf932_live_loop_stall_sampler: None, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_LOGGER)
    signals = _Signals(_hold_the_loop_until.__name__)
    sampler_logger = logging.getLogger(_LOGGER)
    sampler_logger.addHandler(signals)
    before = set(threading.enumerate())
    task = asyncio.create_task(LoopStallSampler(threshold_s=0.2).run())
    try:
        await _until(lambda: bool(_samplers(before)))
        _hold_the_loop_until(signals.blocked)
        await _until(signals.resumed.is_set)
    finally:
        sampler_logger.removeHandler(signals)
        await _stop(task)
    named = [m for level, m in signals.lines if level == logging.WARNING and _hold_the_loop_until.__name__ in m]
    assert len(named) == 1  # one WARNING for the one stall
    assert "tests/test_bf932_d2_loop_stall_sampler.py:" in named[0]  # dir/file:line of the blocking frame
    assert "<threading.Event" not in named[0]  # no arguments and no locals
    assert any(level == logging.INFO and m.startswith(_RESUMED) for level, m in signals.lines)


@pytest.mark.asyncio
async def test_d2_a_loop_that_keeps_turning_gets_no_line(
    bf932_live_loop_stall_sampler: None, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG, logger=_LOGGER)
    sampler = LoopStallSampler(threshold_s=0.2, clock=lambda: 100.0)  # the stamp never ages, as on a turning loop
    task = asyncio.create_task(sampler.run())
    try:
        await _until(lambda: sampler.checks >= 10)
    finally:
        await _stop(task)
    assert [r.getMessage() for r in caplog.records if r.name == _LOGGER and r.levelno >= logging.INFO] == []
    assert sampler.stall_count == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(("threshold_s", "expected"), [(1.0, 1), (0.0, 0)])
async def test_d2_the_runtime_starts_one_sampler_by_default_and_none_at_0(
    bf932_live_loop_stall_sampler: None, tmp_path, threshold_s: float, expected: int,
) -> None:
    before = set(threading.enumerate())
    rt = ProbOSRuntime(
        config=SystemConfig(system=SystemInfo(loop_stall_warn_seconds=threshold_s)),
        data_dir=tmp_path,
        episodic_memory=MockEpisodicMemory(relevance_threshold=0.3),
    )
    await rt.start()
    try:
        assert [t.get_name() for t in rt._background_tasks].count(_TASK_NAME) == expected
        if expected:
            await _until(lambda: len(_samplers(before)) == 1)
    finally:
        await rt.stop()
    assert _samplers(before) == []  # the stop's AD-824 sweep cancelled the heartbeat, which joined the thread


@pytest.mark.asyncio
async def test_d2_a_second_run_starts_no_second_thread_and_a_cancel_ends_the_one(
    bf932_live_loop_stall_sampler: None,
) -> None:
    before = set(threading.enumerate())
    sampler = LoopStallSampler(threshold_s=0.2, clock=lambda: 100.0)
    first = asyncio.create_task(sampler.run())
    try:
        await _until(lambda: len(_samplers(before)) == 1)
        await asyncio.wait_for(sampler.run(), _GUARD_S)  # returns at once: the first run's thread is alive
        threads = _samplers(before)
        assert len(threads) == 1 and threads[0].daemon is True
    finally:
        await _stop(first)
    assert not threads[0].is_alive()


def test_d2_a_closed_loop_ends_the_thread(bf932_live_loop_stall_sampler: None) -> None:
    before = set(threading.enumerate())
    sampler = LoopStallSampler(threshold_s=0.2, clock=lambda: 100.0)
    held: list[asyncio.Task[None]] = []  # keeps the heartbeat task alive, so only the closed loop can end the thread
    loop = asyncio.new_event_loop()
    try:

        async def _start() -> None:
            held.append(asyncio.get_running_loop().create_task(sampler.run()))
            await _until(lambda: bool(_samplers(before)))

        loop.run_until_complete(_start())
        threads = _samplers(before)
    finally:
        loop.close()
    threads[0].join(_GUARD_S)  # guard
    assert not threads[0].is_alive()
    assert len(held) == 1


@pytest.mark.asyncio
async def test_d2_warnings_are_bounded_and_a_refused_stall_writes_no_resume_line(
    bf932_live_loop_stall_sampler: None, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger=_LOGGER)
    before = set(threading.enumerate())
    sampler = LoopStallSampler(threshold_s=0.2, max_warnings=2, window_s=3600.0)
    task = asyncio.create_task(sampler.run())
    try:
        await _until(lambda: bool(_samplers(before)))
        for n in (1, 2, 3):
            _hold_the_loop_while(lambda: sampler.stall_count < n)
            await _until(lambda: sampler.resume_count >= n)
    finally:
        await _stop(task)
    lines = [r for r in caplog.records if r.name == _LOGGER]
    assert sampler.stall_count >= 3
    assert len([r for r in lines if r.levelno == logging.WARNING]) == 2
    assert len([r for r in lines if r.levelno == logging.INFO and r.getMessage().startswith(_RESUMED)]) == 2


@pytest.mark.parametrize("value", [0.0, 0.1, 1.0, 60.0])
def test_d2_the_threshold_accepts_0_or_a_value_from_a_tenth_to_60(value: float) -> None:
    assert SystemInfo(loop_stall_warn_seconds=value).loop_stall_warn_seconds == value


@pytest.mark.parametrize("value", [0.05, -1.0, 60.5, float("inf"), float("nan")])
def test_d2_the_threshold_refuses_anything_else(value: float) -> None:
    with pytest.raises(ValidationError):
        SystemInfo(loop_stall_warn_seconds=value)


def test_d2_the_sampler_is_on_by_default() -> None:
    assert SystemConfig().system.loop_stall_warn_seconds == 1.0
```

### 6.14 `src/probos/perception/consumer.py`

**P19.** SEARCH:
```python
# Per-(runtime, agent) WorkingMemory instances keyed by agent_id.
```
REPLACE:
```python
# BF-932 (#1670): the scene refreshes that the DM route and the group round started and did not wait for. Each task is
# held here until it ends, so none is garbage collected while it runs.
_SCENE_REFRESH_TASKS: set[asyncio.Task[Any]] = set()


def _end_scene_refresh(task: asyncio.Task[Any]) -> None:
    """BF-932: the done callback of a background scene refresh: release the task and log its failure once."""
    _SCENE_REFRESH_TASKS.discard(task)
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logger.warning("BF-932: background scene refresh failed: %r", error, exc_info=error)


def refresh_scene_in_background(consumer: Any, *, timeout_s: float = 4.0) -> asyncio.Task[Any]:
    """BF-932 (#1670): start ``consumer.force_describe_current_frame`` and return without waiting for it.

    The caller renders the working memory as it is; the fresh description lands there for the next turn. BF-977's
    deadline and single-flight permit apply inside the call, unchanged: a refresh started while another holds the
    permit returns ``None`` at once. Call it on the running loop.
    """
    task = asyncio.get_running_loop().create_task(consumer.force_describe_current_frame(timeout_s=timeout_s))
    _SCENE_REFRESH_TASKS.add(task)
    task.add_done_callback(_end_scene_refresh)
    return task


# Per-(runtime, agent) WorkingMemory instances keyed by agent_id.
```

`asyncio` is imported at `consumer.py`:20, `Any` at :26, `logger` at :39.

### 6.15 `src/probos/routers/agents.py`

**P20.** SEARCH:
```python
            # AD-733c-1: force-describe the latest captured frame before
            # rendering the scene block. Best-effort + bounded (4s timeout
            # via VisionConsumer.force_describe_current_frame). When the
            # cache is empty or the LLM is slow, we silently fall back to
            # whatever the WM already contains.
            _consumer = getattr(runtime, "vision_consumer", None)
            if _consumer is not None and getattr(
                _perception_cfg, "dm_force_describe_enabled", True,
            ):
                _hook = "ran"  # BF-932: log-only
                _t_hook0 = time.perf_counter()
                try:
                    await _consumer.force_describe_current_frame(timeout_s=4.0)
                except Exception:
```
REPLACE:
```python
            # AD-733c-1: force-describe the latest captured frame. BF-932
            # (#1670): the describe is started, not awaited (bounded at 4 s
            # inside VisionConsumer.force_describe_current_frame); this reply
            # renders whatever the WM already contains, and the fresh
            # description is there for the next turn.
            _consumer = getattr(runtime, "vision_consumer", None)
            if _consumer is not None and getattr(
                _perception_cfg, "dm_force_describe_enabled", True,
            ):
                _hook = "scheduled"  # BF-932: log-only; the reply does not wait for the describe
                _t_hook0 = time.perf_counter()
                try:
                    from probos.perception.consumer import refresh_scene_in_background

                    refresh_scene_in_background(_consumer, timeout_s=4.0)
                except Exception:
```

### 6.16 `src/probos/routers/thread_fanout.py`

**P21.** SEARCH:
```python
    any failure logs at debug and the round proceeds with whatever the ambient
    describe last left in the rings.
    """
```
REPLACE:
```python
    any failure logs at debug and the round proceeds with whatever the ambient
    describe last left in the rings.

    BF-932 (#1670): the describe is started, not awaited: the round renders the
    rings as they are, and the fresh description is there for the next round. A
    failure of the started describe is logged at WARNING by its done callback.
    """
```

**P22.** SEARCH:
```python
            try:
                await _consumer.force_describe_current_frame(timeout_s=4.0)
            except Exception:
                logger.debug("AD-978: force_describe raised; round proceeds", exc_info=True)
```
REPLACE:
```python
            try:
                from probos.perception.consumer import refresh_scene_in_background

                refresh_scene_in_background(_consumer, timeout_s=4.0)  # BF-932: started, not awaited
            except Exception:
                logger.debug("AD-978: force_describe raised; round proceeds", exc_info=True)
```

### 6.17 `tests/test_bf932_reply_path_timing.py`

**P23.** SEARCH:
```python
from probos.config import CognitiveConfig
```
REPLACE:
```python
from probos.config import CognitiveConfig
from probos.perception import consumer as consumer_module
```

**P24.** SEARCH:
```python
async def _dm(runtime):
    with _CREW_PATCH:
        return await agent_chat("test-id", _req(), runtime)
```
REPLACE:
```python
async def drain_scene_refreshes() -> None:
    """BF-932 S1: end the scene refreshes started on this loop that nothing waited for (the route, the group round)."""
    loop = asyncio.get_running_loop()
    started = [task for task in list(consumer_module._SCENE_REFRESH_TASKS) if task.get_loop() is loop]
    await asyncio.gather(*started, return_exceptions=True)


async def _dm(runtime):
    try:
        with _CREW_PATCH:
            return await agent_chat("test-id", _req(), runtime)
    finally:
        await drain_scene_refreshes()  # BF-932 S1: the route no longer waits for the describe it starts
```

**P25.** SEARCH:
```python
    assert _field(line, "hook") == "ran" and _field(line, "sent") == "yes"
    assert float(_field(line, "hook_ms")) >= 25 and float(_field(line, "send_ms")) >= 25
    assert float(_field(line, "total_ms")) >= 50
```
REPLACE:
```python
    # BF-932 S1: the route starts the describe and does not wait for it, so hook says scheduled and the stub's 30 ms
    # sleep is no longer inside hook_ms or total_ms; only the send's 30 ms sleep is on the route.
    assert _field(line, "hook") == "scheduled" and _field(line, "sent") == "yes"
    assert float(_field(line, "hook_ms")) >= 0 and float(_field(line, "send_ms")) >= 25
    assert float(_field(line, "total_ms")) >= 25
```

**P26.** SEARCH:
```python
    assert _field(line, "hook") == "ran" and answer["response"] == "Acknowledged."
```
REPLACE:
```python
    # BF-932 S1: the failing describe now ends a background task (its done callback logs it); the reply goes out.
    assert _field(line, "hook") == "scheduled" and answer["response"] == "Acknowledged."
```

**P27.** SEARCH:
```python
    assert order == ["consumer", "send"] and runtime.vision_consumer.timeouts == [4.0]
```
REPLACE:
```python
    # BF-932 S1: the describe runs as its own task, so the route no longer orders it before the send; _dm ends it.
    assert sorted(order) == ["consumer", "send"] and runtime.vision_consumer.timeouts == [4.0]
```

### 6.18 `tests/test_dm_camera_hook_deadline.py`

**P28.** SEARCH:
```python
    assert _field(lines[0], "hook") == "ran"
```
REPLACE:
```python
    assert _field(lines[0], "hook") == "scheduled"  # BF-932 S1: the route starts the describe and does not wait for it
```

### 6.19 `tests/test_ad978_group_perception.py`

**P29.** SEARCH:
```python
from probos.types import IntentMessage, IntentResult
```
REPLACE:
```python
from probos.types import IntentMessage, IntentResult
from tests.test_bf932_reply_path_timing import drain_scene_refreshes
```

**P30.** SEARCH:
```python
    await _maybe_force_describe_frame(rt)
    assert consumer.force_calls == 1
```
REPLACE:
```python
    await _maybe_force_describe_frame(rt)
    await drain_scene_refreshes()  # BF-932 S1: the round starts the describe and does not wait for it
    assert consumer.force_calls == 1
```

**P31.** SEARCH:
```python
    await _maybe_force_describe_frame(rt)


# ===================== 3. end-to-end through group_chat_fanout =====================
```
REPLACE:
```python
    await _maybe_force_describe_frame(rt)
    await drain_scene_refreshes()  # BF-932 S1: the failure now ends a background task, whose callback logs it


# ===================== 3. end-to-end through group_chat_fanout =====================
```

**P32.** SEARCH:
```python
    await group_chat_fanout(runtime, t.id, captain_body="status?", captain_msg=cap)
    # Two agents dispatched, but the shared frame is described exactly once.
```
REPLACE:
```python
    await group_chat_fanout(runtime, t.id, captain_body="status?", captain_msg=cap)
    await drain_scene_refreshes()  # BF-932 S1: the round starts the describe and does not wait for it
    # Two agents dispatched, but the shared frame is described exactly once.
```

### 6.20 `tests/test_bf932_s1_scene_refresh_background.py`

New file:

```python
"""BF-932 (#1670) S1: the Captain's DM and a group round start the camera describe and do not wait for it.

The stand-in consumer has the real method name and signature. Its describe waits on an Event that the test sets only
in ``finally``: a describe that ignores its own deadline. The route is the real ``agent_chat`` over the BF-932 timing
harness; the group round is the real ``_maybe_force_describe_frame``. A guard timeout fails a hung test; no assertion
bounds a duration.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

from probos.config import PerceptionConfig
from probos.perception import consumer as consumer_module
from probos.routers.agents import agent_chat
from probos.routers.thread_fanout import _maybe_force_describe_frame
from tests.test_bf932_reply_path_timing import (
    _CREW_PATCH,
    _ROUTE,
    _field,
    _lines,
    _one,
    _req,
    _runtime,
    drain_scene_refreshes,
)

_GUARD_S = 10.0


class _StuckConsumer:
    """A describe that never returns until the test releases it."""

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.timeouts: list[float] = []

    async def force_describe_current_frame(self, session_id: str | None = None, *, timeout_s: float = 4.0) -> str | None:
        self.timeouts.append(timeout_s)
        self.entered.set()
        await self.release.wait()
        return "scene"


@pytest.mark.asyncio
async def test_v1_a_describe_that_never_returns_does_not_hold_the_captains_reply(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="probos.routers.agents")
    runtime = _runtime([])
    consumer = _StuckConsumer()
    runtime.vision_consumer = consumer
    try:
        with _CREW_PATCH:
            answer = await asyncio.wait_for(agent_chat("test-id", _req(), runtime), _GUARD_S)
        await asyncio.wait_for(consumer.entered.wait(), _GUARD_S)  # the refresh did start
        assert answer["response"] == "Acknowledged."
        runtime.intent_bus.send.assert_awaited_once()
        assert not consumer.release.is_set()  # the reply went out while the describe was still blocked
        assert consumer.timeouts == [4.0]
        assert _field(_one(_lines(caplog, _ROUTE)), "hook") == "scheduled"
    finally:
        consumer.release.set()
        await drain_scene_refreshes()


@pytest.mark.asyncio
async def test_g1_a_group_round_does_not_wait_for_a_describe_that_never_returns() -> None:
    consumer = _StuckConsumer()
    rt = SimpleNamespace(
        config=SimpleNamespace(perception=PerceptionConfig(enabled=True)),
        vision_consumer=consumer,
    )
    try:
        await asyncio.wait_for(_maybe_force_describe_frame(rt), _GUARD_S)
        await asyncio.wait_for(consumer.entered.wait(), _GUARD_S)
        assert not consumer.release.is_set()
        assert consumer.timeouts == [4.0]
    finally:
        consumer.release.set()
        await drain_scene_refreshes()


@pytest.mark.asyncio
async def test_v3_the_refresh_is_held_until_it_ends_and_its_failure_is_logged_once(
    caplog: pytest.LogCaptureFixture,
) -> None:
    from probos.perception.consumer import refresh_scene_in_background  # here, so the base fails this test alone

    caplog.set_level(logging.WARNING, logger="probos.perception.consumer")
    release = asyncio.Event()
    seen: list[float] = []

    class _Failing:
        async def force_describe_current_frame(self, *, timeout_s: float = 4.0) -> str | None:
            seen.append(timeout_s)
            await release.wait()
            raise RuntimeError("vision down")

    task = refresh_scene_in_background(_Failing(), timeout_s=2.5)
    try:
        await asyncio.sleep(0)
        assert task in consumer_module._SCENE_REFRESH_TASKS and not task.done()
        release.set()
        await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), _GUARD_S)
        await asyncio.sleep(0)
    finally:
        release.set()
    assert task not in consumer_module._SCENE_REFRESH_TASKS
    assert seen == [2.5]
    failures = [r for r in caplog.records if r.getMessage().startswith("BF-932: background scene refresh failed")]
    assert len(failures) == 1
```

### 6.21 `PROGRESS.md`

**P33.** SEARCH (the heading at build time; see section 4, Shared trackers):
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**BF-932 (2026-11-27), #1670 batch 1 -- the dream cycle gives the event loop turns, a loop-stall sampler names any blocker, and a Captain's DM no longer waits for the camera.** The vessel's log shows the event loop silent for 18 s at the same point of two dream cycles (2026-10-25 19:28:56-19:29:14 and 2026-10-30 23:40:49-23:41:07, after Step 7f and before Step 7h), with a TTS store write of 17.6 s inside the second. Step 7g (AD-551) read every notebook (about 2,700) three times and compared every pair of them with no await, and Step 7f2 (AD-873) made up to 1,000 synchronous Chroma calls with none. Those loops now give the loop a turn every fixed count of units: `RecordsStore.list_entries` every 16 files in its default mode (the strict mode keeps one pass), Step 7g every 16 reads or word sets and every 2,000 pair iterations (each note's word set is built once, not once per pair), and the decay sweep every 8 episodes. The step's clusters, convergence events and reports are unchanged. New `probos.utils.loop_stall.LoopStallSampler` (a heartbeat on the loop and a daemon thread): when the loop goes `system.loop_stall_warn_seconds` (default 1.0; 0 starts none) without a heartbeat, it logs one WARNING `BF-932: event loop blocked for <ms> ms ...; loop thread at: <dir/file:line function> <- ...`, and one INFO `BF-932: event loop resumed after <ms> ms` when the loop returns; at most 10 WARNINGs a minute. It starts at the end of `ProbOSRuntime.start` and stops watching when shutdown begins; tests get it only on request (`tests/conftest.py`). The DM route and group rounds start the camera describe (`refresh_scene_in_background`, `perception/consumer.py`) and render the working memory as it is; the route line says `hook=scheduled`. The Captain-DM concurrency slot and the recall budget are batch 2, chosen by what the sampler and the BF-932 lines show live. #1670 stays open until the Captain's live re-measurement. New `tests/test_bf932_d1_dream_yields.py`, `tests/test_bf932_d2_loop_stall_sampler.py`, `tests/test_bf932_s1_scene_refresh_background.py`. Contract `prompts/bf-932-reply-never-waits.md`.
```

### 6.22 `DECISIONS.md`

**P34.** SEARCH (the newest entry's heading at build time; at HEAD `63c536b3` it is this one; see section 4, Shared trackers):
```markdown
### BF-1002 -- a full dream's dream_complete event reaches its listeners; one helper builds the payload for both emit sites (2026-11-27, #1820)
```
REPLACE:
```markdown
### BF-932 -- the dream cycle gives the event loop turns, a loop-stall sampler names any blocker, and the Captain's DM starts the camera describe without waiting for it (2026-11-27, #1670)

- *Scope.* #1670 batch 1 (D1, D2, S1). `utils/loop_yield.py` and `utils/loop_stall.py` (new); `cognitive/dreaming.py` Step 7g; `knowledge/records_store.py` `list_entries`; `cognitive/episodic.py` `sweep_episode_decay`; `config_models/core.py` `SystemInfo.loop_stall_warn_seconds`; `runtime.py` `start`; `perception/consumer.py` `refresh_scene_in_background`; `routers/agents.py` and `routers/thread_fanout.py`. Contract `prompts/bf-932-reply-never-waits.md`.
- *D1.* The dream's synchronous loops await `asyncio.sleep(0)` every fixed count of units (2,000 pair iterations, 16 reads or word sets, 16 listed files, 8 episodes), and Step 7g builds each note's word set once. Not a worker thread (it cannot be cancelled and it shares the default executor), not a process pool (Windows spawn and pickling), not an exact Jaccard prune (a speedup the property does not need). The strict listing keeps one pass for the stand-down and the archive promotion. Step 12's single bulk Chroma calls are left for the sampler to measure.
- *D2.* A heartbeat coroutine plus a daemon thread that reads the loop thread's frames with `sys._current_frames()` while the loop is blocked; one WARNING per stall, one INFO per resume of a reported stall, 10 WARNINGs a minute; standard library only. Not asyncio debug mode (costly; it reports after the callback returns), not `faulthandler.dump_traceback_later` (one process-wide timer; it writes outside the log). One field, `system.loop_stall_warn_seconds` (0, or 0.1 to 60; default 1.0). Tests run it only on request.
- *S1.* The route and the group round start the describe as a task held until it ends; BF-977's deadline and permit are unchanged inside it, and the reply renders the working memory as it is. A live-frame-aware freshness check is deferred: after 120 s without a new described observation the first reply can say the camera is not active.
- *Deferred.* The Captain-DM concurrency slot and the recall budget (batch 2), chosen by the live numbers.
- *Reversal.* Revert the commits; no persisted format changes. A yaml that sets `system.loop_stall_warn_seconds` still loads after a revert (`SystemInfo` ignores an unknown key).

### BF-1002 -- a full dream's dream_complete event reaches its listeners; one helper builds the payload for both emit sites (2026-11-27, #1820)
```

## 7. Consumers

| Contract | Consumer | After the change |
|---|---|---|
| `list_entries` default mode | Step 7g (`dreaming.py`:932), AD-555 (`notebook_quality.py`:217), AD-563 (`knowledge_linter.py`:58), every other non-strict caller | same entries in the same order; the coroutine now suspends every 16 files, so a concurrent writer may land mid-listing (a file deleted meanwhile is skipped as unreadable, at DEBUG, as before) |
| `list_entries(strict=True)` | `archive_promotion.py`:310, `stand_down.py`:281 | unchanged (no turn) |
| `sweep_episode_decay` | Step 7f2 (`dreaming.py`:911) | same counts; suspends every 8 episodes; each episode's get and update stay adjacent |
| Step 7g output | `DreamReport.notebook_consolidations`, `convergence_reports_generated`; `convergence_detected` / `wrong_convergence_detected` events; the records written | unchanged on equal inputs. A cancellation can now land at a turn; every turn sits before a write for its agent or component, so a cancelled step leaves no half-written cluster it did not already risk at its existing awaits |
| `SystemInfo` dump | `test_ad1270e2_config_models.py`:63 (P16), AD-1152 golden (P17), facade count (P18), the facade baseline and the config reference (4a), HXI config API (`routers/config.py` dumps every field) | one more key in `system`; the HXI save writes only changed fields (`test_bf996_hxi_save_on_disk.py`) |
| the sampler's lines | `probos.log` (the Captain's Select-String, section 15) | new WARNING and INFO lines from `probos.utils.loop_stall` |
| `ProbOSRuntime.start` | booted tests; `test_issue1419_failed_start_rollback.py`:164 (`self._startup_complete = True` is still the last statement); `tests/fixtures/runtime_lifecycle.py`:144-156 (reports non-daemon threads only) | one more background task (a no-op under `tests/conftest.py`); a daemon thread when live |
| the DM route line | `test_bf932_reply_path_timing.py` (P24-P27), `test_dm_camera_hook_deadline.py` (P28), the Captain's live check | `hook=scheduled`; `hook_ms` is the time to start the task |
| `_maybe_force_describe_frame` | `group_chat_fanout`; `test_ad978_group_perception.py` (P30-P32) | returns once the describe is started |
| scanners of the edited files | each file the `rg` command of 8.2 lists | must pass unchanged |

## 8. Gates (the orchestrator runs all of them)

### 8.1 Oracle tree, before the Builder starts

- Each SEARCH of section 6 counted at its turn: 1 each; the five new files do not exist.
- **A/B on the base** (the new test files and the test edits of each slice, without that slice's `src/` sections):
  - D1 (`tests/test_bf932_d1_dream_yields.py`): red: the step 7g turns test (at its first turn assertion), the default-listing test, the decay-sweep test (each finds 0 turns), and the `LoopYield` test (`ModuleNotFoundError`). Green (controls): the step 7g output test, the strict-listing test.
  - D2 (`tests/test_bf932_d2_loop_stall_sampler.py`): collection error (`probos.utils.loop_stall` is missing), so every item is red. With 6.9 applied alone, `tests/conftest.py` imports `probos.utils.loop_stall` inside the fixture, so apply 6.9 only with 6.6.
  - S1 (`tests/test_bf932_s1_scene_refresh_background.py`): red: V1 and G1 by the guard timeout (the base awaits the describe), V3 by `ImportError`. With P24-P32 applied on the base, r1, r3 and t4 fail at `hook == "scheduled"`; r4 passes (sorted order).
- On the candidate: every item of the three new files passes.

### 8.2 Focused checks on the candidate

```text
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf932_d1_dream_yields.py tests/test_ad551_notebook_consolidation.py tests/test_dreaming.py tests/test_ad873_episode_decay.py tests/test_records_store.py tests/test_ad555_notebook_quality.py tests/test_ad563_knowledge_linting.py tests/test_ad564_quality_trigger.py tests/test_ad565_quality_routing.py tests/test_ad583_wrong_convergence.py tests/test_ad599_reflection_episodes.py tests/test_ad980b_dream_attribution.py tests/test_bf1002_full_dream_complete_event.py tests/test_bf940_s4_unparsed_frontmatter.py tests/test_bf958_records_link_containment.py tests/test_bf970_frontmatter_reading.py tests/test_ad1341_s4_exit_note_erasure.py tests/test_ad1341_s4_stand_down.py tests/test_ad1341_s5_continuous_promotion.py tests/test_episodic.py -n 0 -q
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf932_d2_loop_stall_sampler.py tests/test_ad1270e1_config_facade.py tests/test_ad1270e2_config_models.py tests/test_ad1152_agentic_correlation.py tests/test_issue1419_failed_start_rollback.py tests/test_issue1452_stop_leftovers.py tests/test_ad824_shutdown_hygiene.py tests/test_ad741_config_api.py tests/test_ad741_integration.py tests/test_bf996_hxi_save_on_disk.py tests/test_layer_boundaries.py -n 0 -q
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_bf932_s1_scene_refresh_background.py tests/test_bf932_reply_path_timing.py tests/test_dm_camera_hook_deadline.py tests/test_ad978_group_perception.py tests/test_ad733c1_force_describe.py tests/test_ad746a_force_describe_mirror.py tests/test_bf624_stale_meeting_vision_refresh.py tests/test_bf666_force_describe_cache_expiry.py tests/test_ad1031_camera_bid.py tests/test_wave171_acceptance.py tests/test_ad791a_chat_threads_wiring.py tests/test_bf266_vision_context_folding.py -n 0 -q
rg -l -g 'test_*.py' -e 'rglob\("\*\.py"\)' -e 'os\.walk\(' -e 'glob\("\*\*/\*\.py"\)' -e 'cognitive/dreaming\.py' -e '"dreaming\.py"' -e 'records_store\.py' -e 'cognitive/episodic\.py' -e '"episodic\.py"' -e 'perception/consumer\.py' -e 'routers/agents\.py' -e '"agents\.py"' -e 'thread_fanout\.py' -e '"runtime\.py"' -e '/runtime\.py' -e 'config_models/core\.py' -e '"core\.py"' -e 'utils/step_timing' tests
d:/ProbOS/.venv/Scripts/pytest.exe <each file the rg command lists> -n 8 -q
d:/ProbOS/.venv/Scripts/python.exe -P scripts/check_config_facade.py --check
d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_config_reference.py --check
d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --preflight-only --label bf-932-batch1
```
The `rg` pattern listed 117 files on the base (the Grep tool, same pattern, glob `test_*.py`, over `tests/`). The three `pytest` lines name the consumers it does not list. Retriage a parallel failure at `-n 0`.

### 8.3 Mutation rows (one at a time on the candidate, the file restored byte for byte; one campaign of record)

Each locator is a whole stripped line of the candidate. Where a line occurs more than once, the ordinal is given.

| ID | File: line (stripped) | Becomes | Killed by |
|---|---|---|---|
| M1 | `dreaming.py`: `if pair_pacer.due():` (1st of 3) | `if False:` | 7g turns (alpha segment) |
| M2 | `dreaming.py`: `if pair_pacer.due():` (2nd of 3) | `if False:` | 7g turns (cross segment) |
| M3 | `dreaming.py`: `if pair_pacer.due():` (3rd of 3, coherence) | `if False:` | **not killed**: the fixture's component has 3 pairs (< 2,000); equivalent at test scale, kept for a large component |
| M4 | `dreaming.py`: `_STEP_7G_PAIRS_PER_YIELD = 2000` | `_STEP_7G_PAIRS_PER_YIELD = 10**9` | 7g turns |
| M5 | `dreaming.py`: `if read_pacer.due():` (1st of 3) | `if False:` | 7g turns (alpha reads) |
| M6 | `dreaming.py`: `if read_pacer.due():` (2nd of 3) | `if False:` | 7g turns (cross reads) |
| M7 | `dreaming.py`: `if read_pacer.due():` (3rd of 3) | `if False:` | 7g turns (cross word sets) |
| M8 | `dreaming.py`: `words_j = entry_words[j]` | `words_j = entry_words[i]` | 7g output (alpha becomes one cluster of 100) |
| M9 | `dreaming.py`: `words_j = cross_words[j]` | `words_j = cross_words[i]` | 7g output (one component of all notes; coherence differs) |
| M10 | `dreaming.py`: `member_words = [cross_words[idx] for idx in component]` | `member_words = cross_words[: len(component)]` | 7g output (coherence) |
| M11 | `records_store.py`: `pacer = None if strict else LoopYield(_LIST_FILES_PER_YIELD)` | `pacer = None` | default listing |
| M12 | same line | `pacer = LoopYield(_LIST_FILES_PER_YIELD)` | strict listing |
| M13 | `episodic.py`: `if pacer.due():` | `if False:` | decay sweep |
| M14 | `loop_yield.py`: `if self._count >= self._every:` | `if self._count > self._every:` | `LoopYield` test |
| N1 | `loop_stall.py`: `if age_s > self._threshold_s:` | `if age_s > self._threshold_s * 1000.0:` | D2 blocked loop (guard), D2 bounded warnings (guard) |
| N2 | `loop_stall.py`: `_innermost_frames(loop_thread_id, _STACK_DEPTH),` | `_innermost_frames(threading.get_ident(), _STACK_DEPTH),` | D2 blocked loop (the line names `_watch`; guard) |
| N3 | `loop_stall.py`: `if reported:` | `if False:` | D2 blocked loop (resume guard), D2 bounded warnings |
| N4 | `loop_stall.py`: `self._warnings = _WarningBudget(max_warnings, window_s)` | `self._warnings = _WarningBudget(0, window_s)` | D2 bounded warnings (3 WARNINGs) |
| N5 | `loop_stall.py`: `self._stop.set()` | `pass` | D2 second run (thread alive after the cancel) |
| N6 | `loop_stall.py`: `if self._thread is not None and self._thread.is_alive():` | `if False:` | D2 second run (two threads) |
| N7 | `loop_stall.py`: `if loop.is_closed() or (self._active is not None and not self._active()):` | `if self._active is not None and not self._active():` | D2 closed loop |
| N8 | `loop_stall.py`: `target=self._watch, args=(loop, threading.get_ident()), name=THREAD_NAME, daemon=True,` | the same with `daemon=False,` | D2 second run (`daemon is True`) |
| N9 | `runtime.py`: `if _loop_stall_s > 0:` | `if _loop_stall_s >= 0:` | D2 runtime [0.0] |
| N10 | `runtime.py`: `active=lambda: not self._shutdown_started,` | `active=None,` | **not killed**: the AD-824 sweep also ends the thread; the predicate only keeps shutdown's own stalls out of the log |
| N11 | `core.py`: `if 0.0 < value < 0.1:` | `if False:` | D2 threshold refuses [0.05] |
| S1M1 | `agents.py`: `refresh_scene_in_background(_consumer, timeout_s=4.0)` | `await _consumer.force_describe_current_frame(timeout_s=4.0)` | V1 (guard) |
| S1M2 | `thread_fanout.py`: `refresh_scene_in_background(_consumer, timeout_s=4.0)  # BF-932: started, not awaited` | `await _consumer.force_describe_current_frame(timeout_s=4.0)` | G1 (guard) |
| S1M3 | `consumer.py`: `_SCENE_REFRESH_TASKS.add(task)` | (line deleted) | V3 |
| S1M4 | `consumer.py`: `_SCENE_REFRESH_TASKS.discard(task)` | (line deleted) | V3 |
| S1M5 | `consumer.py`: `logger.warning("BF-932: background scene refresh failed: %r", error, exc_info=error)` | the same with `logger.debug(` | V3 |
| S1M6 | `consumer.py`: `task = asyncio.get_running_loop().create_task(consumer.force_describe_current_frame(timeout_s=timeout_s))` | the same with `timeout_s=4.0` | V3 (`seen == [2.5]`) |
| S1M7 | `agents.py`: `_hook = "scheduled"  # BF-932: log-only; the reply does not wait for the describe` | `_hook = "ran"` | V1, r1, r3, t4 |

Mark the run that executes this table as the campaign of record (base tree and each edited file's sha256); a later candidate whose edited files match does not repeat it.

### 8.4 The gate

`d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label bf-932-batch1 --receipt logs/gates/bf-932-batch1.receipt.json` once on the committed head, after merging the base.

## 9. Diff Reviewer: properties to verify

The change claims: (D1) the dream's notebook and decay loops await `asyncio.sleep(0)` every fixed count of units with identical output; (D2) a heartbeat and a daemon thread log one WARNING naming the loop thread's frames per stall and one INFO per resume, on by default, off at 0; (S1) the DM route and the group round start the describe without awaiting it. Consumers that must accept it: `DreamingEngine.dream_cycle`'s report and events; `RecordsStore.list_entries`'s callers (strict and default); `ProbOSRuntime.start` and `shutdown()`; the DM route's `BF-932: dm route` line and the agent's reply.

1. In Step 7g every comparison, read and word set of the base still happens, in the base's order; the only additions are the counters, the `await asyncio.sleep(0)` lines and the precomputed word sets; `member_words[ci]` equals `text_to_words(cluster_entries[ci]["_content"])`.
2. `list_entries(strict=True)` executes no `await`; the default mode returns the same list.
3. `sweep_episode_decay` keeps each episode's get and update adjacent (no turn between them).
4. `loop_stall.py` imports nothing from `probos` (the utils layer imports nothing); the thread never raises (the outer `except Exception`); no frame object outlives `_innermost_frames`; `lookup_lines=False`.
5. `run()`'s `finally` sets the stop event and joins with a timeout; the `CancelledError` arm re-raises.
6. `start()` still ends with `self._startup_complete = True`; the sampler is spawned through `_spawn_background` and only when the field is above 0.
7. `refresh_scene_in_background` holds each task in `_SCENE_REFRESH_TASKS` until done and logs a failure once; BF-977's `force_describe_current_frame` is byte-identical to the base.
8. Each edited test keeps its other assertions and records its reason inline; nothing is deleted.
9. No file of the scope boundary changes; `step_timing.py` and `config/system.yaml` are byte-identical to the base.
10. ASCII and LF in the new text; each absolute word (every, each, no, only, none, never) holds against sections 1, 3a, 7 and the Absence Verified list.

## 10. Verified Against Codebase (2026-11-27, tree `63c536b3`)

- `dreaming.py`: `import asyncio` :10; similarity import :19; `from probos.types import (...)` :50-57, `if TYPE_CHECKING:` :59; `logger` :62; `_outcome_evidence` :65; `_get_importance_map` :310-327 (one bulk `_collection.get` :315); `dream_cycle` :420 (`recent(k=...)` :475; Steps 2-5 :486-512; Step 6 :514-572); Step 7f2 :903-922 (`sweep_episode_decay` :911); Step 7g :924-1229 (listing :932; threshold :941-942; per-agent loop :944, reads :949-957, `n = len(loaded)` :961, pairs :963-970, BFS :974-989, write :1012, archive rename :1025, `_git` :1027; cross reads :1063-1075; pairs :1077-1088; BFS :1090-1102; `cluster_entries` :1103; coherence :1107-1116; `word_sets` :1130; report write :1145); Step 7i :1256-1303 (`max_pairs_per_run` :1282); Step 9 :1393-1431; Step 10 :1433-1520; Step 12 :1564-1669 (`count()` :1584).
  `Grep "jaccard_similarity\(|text_to_words\(" dreaming.py` -> :964, :966, :967, :1080, :1084, :1085, :1111, :1113, :1114, :1130.
- `similarity.py`:4-19 (`jaccard_similarity` allocates `a | b` per call; `text_to_words` is `set(text.lower().split())`).
- `records_store.py`: `import asyncio` :3; frontmatter import :20; `_RECORDS_YAML_LOADER` :279; `_markdown_files` :606; `__init__` :680-693; `read_entry` :1485-1526 (`read_text` :1504, `_load_document` :1505; no `await`); `list_entries` :1528-1610 (`found` :1569, loop :1571, read :1584-1585, entry keys :1605; no `await`); `_safe_path` :1861-1872; `_git` :1893-1896.
- `episodic.py`: `import asyncio` :10, `import time` :18; types import :63; `logger` :65; `__init__` :1394; `update_episode_metadata` :2482-2511 (no `await`); `sweep_episode_decay` :2609-2694 (page via `asyncio.to_thread` :2640; loop :2670-2692).
- `notebook_quality.py`:217; `knowledge_linter.py`:58, :76-101.
- `perception/consumer.py`: `import asyncio` :20; `Any` :26; `logger` :39; `_log_abandoned_force_describe` :55-71; comment :74, `_WORKING_MEMORIES` :77; `force_describe_current_frame` :755-821 (single flight :781-782).
- `routers/agents.py`: `_hook = "skipped"` :2967; hook block :3479-3500 (`await` :3494); render :3519-3525; route line :3710-3717 (fields `thread_ms prep_ms hook hook_ms dispatch_ms send_ms total_ms sent`).
- `routers/thread_fanout.py`: `_maybe_force_describe_frame` :386-410 (`await` :406).
- `cognitive_agent.py`:7689-7698 (`BF-932: dm turn ... perceive_ms recall_ms`); `concurrency_manager.py`:235 (`AD-672: Promoted queued intent ... waited_ms`).
- `perception/working_memory.py`:124-134 (sentinel); `config.py`:2311 (`dm_force_describe_enabled` default True), :2320 (`prompt_freshness_seconds` 120.0), :3911 (`system: SystemInfo`); `config_models/core.py`:13 (imports), :153-158 (`SystemInfo`).
- `runtime.py`: `_background_tasks` :1554; `_shutdown_started` :1588; `start` :2804; SQLite backup spawn :3827-3831; `_startup_complete` :3836; `_spawn_background` :4022-4080. `startup/shutdown.py`: `_shutdown_started = True` :921; drain :1337-1365; AD-824 sweep :1373-1399.
- `__main__.py`:922-931 (heartbeat: `asyncio.sleep(60)`, `runtime alive ... uptime=`).
- Tests: `test_ad1270e1_config_facade.py`:1577-1578; `test_ad1270e2_config_models.py`:63, :221-225; `test_ad1152_agentic_correlation.py`:54-61 (rule for an added field), :350; `test_bf932_reply_path_timing.py`:20, :76-88, :91-124, :127-129, :143-145, :171, :180; `test_dm_camera_hook_deadline.py`:41, :298; `test_ad978_group_perception.py`:50, :99-106, :259-266, :270-280, :315-318; `test_ad551_notebook_consolidation.py`:25-101; `test_issue1419_failed_start_rollback.py`:150-164; `tests/conftest.py`:182-206; `tests/fixtures/runtime_lifecycle.py`:144-156.
- `pyproject.toml`:9 (`requires-python = ">=3.12"`); `scripts/check_config_profiles.py`:166-171; `scripts/check_config_facade.py`:1711, :1716 (`--check`, `--update-baseline`).
- Live data: `probos.log.1` lines quoted in section 1 (Grep `^2026-10-25 19:2(8:(39|[45][0-9])|9:(0[0-9]|1[0-9]))`, `^2026-10-30 23:4(0:(4[5-9]|5[0-9])|1:0[0-9])`, `runtime alive` by window). Glob `notebooks/*/*.md` under `ship-records`: 2,777; `notebooks/*/_archived/**/*.md`: 0. `config/system.yaml`:219 (`idle_threshold_seconds: 300.0`), :221 (`replay_episode_count: 50`), :228-233 (AD-551 settings at their defaults).

### Absence Verified (2026-11-27)

- CLAIM: Step 7g's pair, BFS and coherence loops contain no `await`. RUN: Read `dreaming.py`:944-1116. FOUND: the only `await`s in :924-1229 are `list_entries` :932, `read_entry` :951 and :1067, `write_entry` :1012 and :1145, `_git` :1027. HOLDS.
- CLAIM: `read_entry`, `list_entries` and `update_episode_metadata` contain no `await`. RUN: Read `records_store.py`:1500-1526, :1563-1610; `episodic.py`:2488-2511. FOUND: none. HOLDS.
- CLAIM: `force_describe_current_frame` has two callers in `src`. RUN: Grep `force_describe_current_frame\(` over `src/probos`. FOUND: `agents.py`:3494, `thread_fanout.py`:406, and the definition `consumer.py`:755. HOLDS.
- CLAIM: four test lines pin `hook=ran` or the route's order. RUN: Grep `"hook"\) == "ran"|hook=ran|"consumer", "send"` over `tests`. FOUND: `test_bf932_reply_path_timing.py`:143, :171, :180; `test_dm_camera_hook_deadline.py`:298. HOLDS.
- CLAIM: the strict listing has two callers. RUN: Grep `list_entries\([^)]*strict=True` over `src/probos`. FOUND: `archive_promotion.py`:310, `stand_down.py`:281. HOLDS.
- CLAIM: `SystemInfo`'s default dump is pinned once. RUN: Grep `log_level` over `tests`. FOUND: `test_ad1270e2_config_models.py`:63 (pin); `test_pool_groups.py`:235 (input data, not a pin); the rest set or read `log_level` and pin no key set. HOLDS.
- CLAIM: no test counts every thread a runtime starts. RUN: Grep `threading\.enumerate|active_count\(\)` over `tests`. FOUND: filters by a thread name or by non-daemon threads (`runtime_lifecycle.py`:144-156) only. HOLDS: the sampler's thread is a daemon with its own name.
- CLAIM: `step_timing.py` is shared with the voice track. RUN: Grep `step_timing|TimingLines|emit_line` over `src`. FOUND: `audio/tts/resident.py`:43, `attachments/filesystem_store.py`:41, `cognitive_agent.py`:7691, `concurrency_manager.py`:20, `routers/agents.py`:64. HOLDS.
- CLAIM: the 2026-10-25 19:29:38-49 hole was not a loop block. RUN: Grep `runtime alive` 19:22-19:46. FOUND: 19:28:46 `uptime=367s`, 19:29:46 `uptime=427s` (on time). HOLDS.
- CLAIM: no utils module imports from `probos`. RUN: Read `test_layer_boundaries.py`:42, :55 (`"utils": set()`). HOLDS for both new modules (standard library only).

## 11. What this does NOT change

- The voice path (`routers/avatars.py`, `audio/`, `attachments/`, `ui/src/audio/`), `step_timing.py` and `config/system.yaml` (the Captain may raise `dreaming.idle_threshold_seconds` himself).
- The Captain-DM concurrency slot and priority, and the recall budget (the consult's S2 and S3): batch 2, drafted from the live `dm turn` and `AD-672 ... waited_ms` lines and what the sampler names. The consult ranked them on the 19:29:38-49 window, which was not a loop block (section 1); whether they are needed is now a measurement.
- Synchronous Chroma calls on the loop outside Step 7f2: Step 12's bulk calls, the recall path (`count_for_agent`, `recall_weighted`), and `records_store.py`'s other synchronous scans (:443, :1760).
- BF-977's `force_describe_current_frame`, its deadline, permit and cancellation.
- The BF-932 route and turn line names and fields (only the `hook` value changes, from `ran` to `scheduled`).
- Step 7g's BFS (`queue.pop(0)`) and `word_sets` (:1130).

## 12. Issue text (#1670, on merge)

```text
Batch 1 of BF-932 merged (PR #<PR>, contract prompts/bf-932-reply-never-waits.md). The issue stays open for the Captain's live re-measurement.
- Found: the event loop was silent for 18 s at the same point of two dream cycles (2026-10-25 19:28:56-19:29:14, 2026-10-30 23:40:49-23:41:07, between Step 7f and Step 7h), with a 17.6 s TTS store write inside the second. Step 7g read every notebook (2,777) three times and compared every pair with no await; Step 7f2 made up to 1,000 synchronous Chroma calls. The 19:29:38-49 hole of the original measurement was not a loop block (the 60 s heartbeat ran on time).
- D1: those loops now give the event loop a turn every fixed count of units (2,000 pair iterations, 16 reads or word sets, 16 listed files, 8 episodes); the step's output is unchanged.
- D2: a loop-stall sampler (system.loop_stall_warn_seconds, default 1.0, 0 = off) logs "BF-932: event loop blocked for <ms> ms ...; loop thread at: <frames>" and "BF-932: event loop resumed after <ms> ms".
- S1: the DM route and group rounds start the camera describe and do not wait for it; the route line says hook=scheduled. After 2 idle minutes with a still scene, the first reply can say "camera not active"; send one warm-up message first.
- Next: batch 2 (the Captain-DM slot and the recall budget) is chosen from the live numbers below.
```

PR title: `The dream cycle stops holding the event loop, a stall sampler names any blocker, and the Captain's DM stops waiting for the camera`.

## 13. Prior art and blind spots

- Internal: the consult of 2026-11-27 (pre-turn path table, hypotheses, S1-S3); BF-930 and BF-932's timing lines (`step_timing.py`, PR #1790); BF-977 (the describe's deadline and permit); BF-918 (store I/O threads); AD-551, AD-555, AD-563, AD-873 (the dream steps); AD-824/825 (background-task lifecycle). No `docs/research/` study covers event-loop starvation.
- External (2026-11-27): aiodebug's `hang_inspection` uses the same heartbeat-and-thread design and writes stack dumps to files ([PyPI](https://pypi.python.org/project/aiodebug/), [superfastpython](https://superfastpython.com/asyncio-log-long-running-aiodebug/)). Adapted, not adopted: a third-party dependency, and its output goes to files rather than the log. CPython issue 106883 ([github](https://github.com/python/cpython/issues/106883)) reports a deadlock in `sys._current_frames` on 3.11 when a collection runs inside it. A fix disables collection during the call; one user could not reproduce it on 3.12.1. ProbOS requires 3.12, so no `gc.disable()` around the call (toggling the collector from a second thread would race the application). `docs/research/reference-projects.md` has no asyncio or event-loop row; no row was examined.
- Blind spots:
  - A host that pauses the whole process (sleep, a loaded test host) produces a stall line whose top frame is the selector wait (`windows_events.py` / `selectors.py`, `_poll`/`select`). That means the process was paused, not blocked by code (section 15, line 4).
  - Logging from the thread waits on a handler lock if the loop thread is blocked inside a handler; it then reports once the handler returns. No deadlock: the loop thread does not wait for the sampler.
  - The sampler's WARNING reports the age at detection (at least the threshold), not the full stall; the resume line carries the full gap (plus at most one tick).
  - D1's counts bound units, not time. A unit that is itself slow (one Chroma update) can still exceed the threshold, and D2 names it.
  - S1: the reply describes the previous scene; "what am I holding up?" gets the frame described for the previous turn.

## 14. Acceptance criteria

1. The A/B of 8.1 holds; M1 to M14, N1 to N11 and S1M1 to S1M7 are killed as 8.3 says, except M3 and N10, which are recorded as not killed with their reasons.
2. The focused checks of 8.2 pass, the `rg` list included; the pre-existing tests in those files pass unchanged except the in-place edits of section 6.
3. The generators of 4a produce only the expected diff, and `check_config_facade.py --check` passes.
4. `git diff --check` is clean, the new text is ASCII, and no file outside section 6 (plus the generated files and the ledger pair) changes.
5. The Diff Reviewer approves against section 9.
6. One receipted broad gate on the committed head is green.
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 15. The Captain's live check (after the merge)

1. Restart the vessel on main with this merge, camera on. Before recording, send one throwaway message to the crew member: its background describe refreshes the scene, since after 2 idle minutes with a still scene the first reply can say "camera not active".
2. Record as usual and note the start minute. Afterwards run: `Select-String -Path "$env:LOCALAPPDATA\ProbOS\data\logs\probos.log*" -Pattern 'BF-932: dm route','BF-932: dm turn','BF-932: event loop blocked','BF-932: event loop resumed',"AD-672: Promoted queued intent 'direct_message'"`
3. Pass: each `dm route` line says `hook=scheduled`, and per message `thread_ms + prep_ms + hook_ms + dispatch_ms` (route) plus `waited_ms` (a promoted line, if any) plus `perceive_ms + recall_ms` (turn) is under 2000 at p95 (the largest value if fewer than 20 messages).
4. Pass: no `event loop blocked` line inside the recording window. Any that appear: post them as they are. The frames after `loop thread at:` name the blocker; a first frame in `selectors.py` or `windows_events.py` means the process was paused, not blocked by code.
5. Post the count of `event loop blocked` lines and whether any reply said "camera not active".
