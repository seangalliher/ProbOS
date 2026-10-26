# BF-939: an AD-754 erasure keeps a content-addressed attachment another episode still names

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-26

**Status:** build-ready. The base cost numbers are measured (**Not verified**, item 1: the 100k single path projects to 16.7 s against the 30 s limit); the built tree's are measured after M1. Issue #1683. No new number: BF-939 is in the issue title (`gh issue view 1683`: "BF-939: erasing an episode unlinks a content-addressed attachment that another episode still references", OPEN). Tier **HIGH**: an irreversible delete, data integrity. It lands as its own PR **after AD-1341 S4 merges** and does not batch with BF-938, because they share no file.

**Base:** `origin/main` `4d0161c5`, the merge of S4 (PR #1685); its tree `e6fb6adc7a9a0c037859dc9ea7bda39fc90d1140` equals the S4 gate's. Drafted on the S4 candidate `4f855b90` (tree `1b7874e6f80300c29de88f769b595243d0da69f7`). **Re-anchored by the orchestrator on the merge (2026-10-26):** this paragraph, the Status line, the new test file's case count in the Tests list below (22, not 23: T1 and T2 three cases each, T4, T6, T9 and T10 two each, T11 four, T3, T5, T7 and T8 one each), §4's expected focused counts and the **Not verified** results; no pair, SEARCH or REPLACE changed. All 15 pairs (M1 11, M2 2, trackers 2) apply exactly once by tool on a tree equal to the merge's (the dry oracle on `74c73167`, whose tree is `e6fb6adc`), and the **S4 anchors** listed after §11 hold on `4d0161c5`: `erasure.py:141`, `:169` and `:275` (the textual one), `tests/test_ad1341_s4_exit_note_erasure.py:310-323` and `tests/test_ad1341_s3_erasure_cascade.py:80` (`_midway`).

**Design source:** the Architect's decision of 2026-10-26 (`logs/bf939/decision-1683.md`, option (a)). Three amendments made while drafting this contract follow; the orchestrator records them on #1683.
- **A-1 (who keeps a shared blob in a cascade).** The decision kept a blob if any earlier match failed. That can strand the blob: `_erase_ids` tries every phase and raises afterwards (`episodic.py:2895-2902`), so a match whose erase failed may have no record left naming it. AD-1340 R12 shows this: the failed member's live row is already gone (`test_ad1340_s1_erasure.py:597`). Now a blob is kept only for a match **left whole**, meaning refused or failed before its erase began (D4; test T7).
- **A-2 (a failed owner scan on the single path).** The decision said "raises before anything is erased". That makes an episode whose own row cannot be rebuilt unerasable by every entry point. `iter_live_episodes` raises after its scan when any row cannot be rebuilt (`episodic.py:2349-2350`). `get_by_ids` skips that row (`:2389-2393`), and BF-868's metadata fallback still finds its attachments (`erasure.py:349-352`; the case is modelled at `test_bf868_erasure_declared_fields.py:73-79`). The cascades cannot match such a row either. So the single path follows the cascade's policy: it erases, keeps each blob that a reached owner still names, then raises `ErasureCascadeIncomplete` (D5; tests T8 to T10). AD-1340's R11 (`test_ad1340_s1_erasure.py:539-561`) passes unchanged under this rule.
- **A-3 (S4 register R17 is not closed here).** The cascade keeps both per-episode checks, S3's archive check (D10) and S4's exit-note check. It drops only the per-episode **owner scan**, which the single path would otherwise run once per match. R17's own text says one read per erasure is not enough, because S3's E8 needs the per-episode re-read (`prompts/ad-1341-s4-lessons-and-stand-down.md:5381`; `tests/test_ad1341_s3_erasure_cascade.py:317-365`). Removing it would change S3's refusal, which this build must not touch. R17 stays S5's.

**Captain:** nothing here meets a Captain condition. Option (a) is inside the envelope: AD-754 protects the requester from the erased episode's content staying recoverable *through that episode*, and that still holds; the blob stays only while an episode nobody asked to erase names the same bytes. The Captain may overrule after the fact with option (d), erase by content: keep unlinking, and mark and report the other episode's reference as erased.

**Milestones and tiers:** M1 is the ownership rule in `erasure.py` (HIGH). M2 is the route's report (HIGH, wire contract). M3 is the trackers. Each milestone is one Builder delegation and one local commit, built in order. Review: cross-family (`gpt-6.1-sol`) for M1 and M2. One mutation campaign runs on the assembled tree (§10). The broad gate runs once, after M3: `d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label bf939 --receipt logs/gates/bf939.receipt.json`.

**Tests:**
- New `tests/test_bf939_shared_attachment_ownership.py` (M1): 11 functions, 22 cases.
- New `tests/test_bf939_forget_route.py` (M2): 1 function.
- Updated `tests/test_bf868_erasure_declared_fields.py` (M1): one fake memory gains an empty `iter_live_episodes`, with the reason inline.

**Line endings:** the working copies are CRLF (`core.autocrlf=true`). The SEARCH blocks are LF; match and write with the file's own endings. New files are written LF.

---

## 0. Premise: what is present on this tree

| Fact | Where |
|---|---|
| The single path unlinks every attachment the episode names, before the evict, with no owner check | `erasure.py:183-184`, `:363-371` |
| The attachment store is content-addressed and `unlink` is a hard delete that returns False when the blob is missing | `attachments/filesystem_store.py:118-119`, `:400-405` |
| The cascades scan live, then archive; a failed scan keeps its matches; erasure continues, then raises (BF-905) | `erasure.py:236-271`, `:273-304` |
| The cascade calls the public `forget_episode` per match, so S3's archive check and S4's exit-note check run per match | `erasure.py:282`, `:181-182` |
| AD-1340 order: unlink, then evict; `mark_deleted` only after a successful erase | `erasure.py:173-196` |
| BF-868: attachment ids come from declared fields only | `erasure.py:47-53`, `:373-423` |
| `ErasureManager` has 15 direct methods (the SRP gate, `check_architecture_principles.py`, via `test_ad1270b_architecture_fitness.py`) | `erasure.py:155-490`; DECISIONS BF-905 D5 |
| `iter_live_episodes` fails closed and raises `erasure_live_rows_unrehydratable:<n>` after yielding every row it can rebuild | `episodic.py:2312-2350` |
| `iter_archived_episodes` returns nothing when the archive is disabled and raises when it failed to open | `episodic.py:3002-3026`, `:2699-2705` |

## 1. Problem

`ErasureManager.forget_episode` (`erasure.py:173-203`) takes the attachment ids from the episode's own records (`_attachment_ids_for_episode`, `:317-361`) and unlinks each one (`_delete_attachments`, `:363-371`). It never asks whether another episode names the same blob. The store is content-addressed, so identical bytes are one file. When two episodes share a blob and only one is erased, the survivor keeps its record but loses its bytes: an unrequested, unaudited partial erasure of an episode nobody asked to forget. The S3 M3 reviewer reproduced it (#1683): after erasing `ep-001`, `live=['ep-000']` and `attachment_exists=False`. The base code does the same without any archive entry. Every entry point reaches it (episode, resource, agent), because the cascades call `forget_episode` per match (`:282`).

## 2. Solution overview

1. **Owners come from a scan, by episode id.** Each live episode and each AD-1340 archived version is recorded as an owner of the attachment ids it declares (`_extract_attachment_ids(_episode_to_dict(ep))`). Because owners are keyed by id, an episode's own archived versions never protect its blobs. There is no reference index.
2. **The single path scans once, and only when needed.** That is, only when the episode declares an attachment and an attachment store is wired. A blob another episode names is kept and reported.
3. **The cascades add no read.** The predicate `_matching_ids` already passes to `_scan` also records owners. The cascade no longer calls the public `forget_episode` per match. It runs that method's per-episode checks unchanged (S3, S4), then one internal erase path, `_erase_episode`.
4. **When a shared blob goes in a cascade.** It is decided in the turn of the last match naming it, before that match is evicted. It is unlinked unless an episode outside the matches, or a match left whole, still names it.
5. **A failed scan is under-erase-averse (BF-868).** A blob goes when every owner the scan reached is erased by this request. The failure is then raised.
6. **The report.** `ErasureResult` gains `retained_attachments` as its last field, with a default. The route adds `retained_attachment_ids`. `count` is unchanged.
7. **SRP.** `_delete_attachments` becomes the module function `_unlink_attachments`, and `_erase_episode` takes its slot, so `ErasureManager` stays at 15 methods. The owner recorder and the unlink rule are module functions.

## 3. Decisions

- **D1 (option (a)).** A blob is unlinked only when no episode outside the request still names it. Ranked (a) > (b) refuse while shared > (c) keep deleting. The reframing check is in the header's Captain line.
- **D2 (owners).** Owners are live episodes plus every AD-1340 archived version, by episode id. "Archived" means the episodic archive, not the Ship's Archive, which holds no attachment references. Owners outside episodic memory are **not checked**: thread pins (`threads/__init__.py:86`), chat, work items and artifacts. An erasure still unlinks a blob only they hold, as before. That is a register row on #1523 (G1), not a new issue.
- **D3 (one scan).** The single path calls `_matching_ids(lambda _episode: False, owners, attachment_ids)`: one live scan and one archive scan, recording only that episode's ids. A cascade's existing scan records every id, and the cascade does not scan again per match. Test T11 counts the scans and the citation reads.
- **D4 (when a shared blob goes in a cascade; A-1).** Matches are erased in scan order (live, then archive). A blob is decided in the turn of the last match the scan saw naming it, so AD-1340's order (unlink, then evict) holds for the match that decides it. Earlier matches naming it are evicted first, and the deciding match still names it until its own turn. The blob is kept, and reported with the holders, if any of these still names it:
  - an episode outside the matches;
  - a match left whole, i.e. refused by S3 or S4, or failed before its erase began. Its records stand, so the retry finds the blob through it.

  A match whose erase began and failed counts as erased, because its records may already be gone (`episodic.py:2898-2902`). Keeping the blob for it could leave a file no record names. If the deciding match itself fails before its erase, the blob is not decided by this request: it stays, held by that match, and the retry decides it (register G4).
- **D5 (a failed owner scan; A-2).** On either path, a scan error leaves the owner map incomplete. A blob is unlinked when every owner the scan reached is in the request. The erasure proceeds, a WARNING is logged, and the failure is raised: on the cascade as today (`ErasureCascadeIncomplete`, BF-905); on the single path as `ErasureCascadeIncomplete(result, {}, scan_error)` after the erase. If the erase itself raised, its own typed error propagates unwrapped, which is AD-1340's contract (R11). The disclosed bound: an owner the scan could not read (a row that cannot be rebuilt) does not keep the blob (test T10). Under-erasing is the worse failure (BF-868).
- **D6 (the report).** `ErasureResult.retained_attachments: dict[str, list[str]]` maps each kept attachment id to the holding episode ids, both sorted. It is the last field and defaults to `{}`, so every construction stays valid. The route adds `"retained_attachment_ids": result.retained_attachments`. `count` is still episodes evicted plus attachments unlinked.
- **D7 (what stays exactly as it is).** S3's archive check runs at every entry point and per match (D10, E8). S4's exit-note check runs at every entry point and per match, with X1b and both 409 bodies. BF-868's declared-field extraction is unchanged, and so is AD-1340's retention, its unlink-then-evict order and its `mark_deleted` rule.
- **D8 (cost; measured in §11).** The single path now costs one full live scan plus one archive scan when the episode declares an attachment. That is the same read a cascade already makes. Each cascade adds one `asdict` and one extraction per scanned episode. The thresholds and the fallback are in §11, **Not verified**, item 1.

## 4. Milestones

Each milestone is one Builder delegation and one local commit, built in order. Run each focused gate with `d:/ProbOS/.venv/Scripts/pytest.exe -n 0`. Stage explicit paths only; never `git add -A`. Write each milestone's new test file first and run it on the milestone's base: §6's last column names what fails there. If a test outside §7 fails, stop and report it; never delete or loosen a test.

| Milestone | Tier | Files (§7) | Focused gate |
|---|---|---|---|
| **M1** the ownership rule | HIGH | 7.1 `src/probos/knowledge/erasure.py`; 7.2 `tests/test_bf868_erasure_declared_fields.py`; 7.3 new `tests/test_bf939_shared_attachment_ownership.py` | `tests/test_bf939_shared_attachment_ownership.py tests/test_bf868_erasure_declared_fields.py tests/test_ad1340_s1_erasure.py tests/test_ad1340_s1_restore_reset.py tests/test_bf869_fused_frame_refs.py tests/test_bf905_erasure_live_scan.py tests/test_erasure_manager.py tests/test_ad1341_s3_erasure_cascade.py tests/test_ad1341_s4_exit_note_erasure.py tests/test_ad1341_s4_stand_down.py tests/test_ad1340_s2a_lookup_route.py tests/test_ad1340_s2b_restore_route.py tests/test_ad1293_turn_record_reaches_episode.py tests/test_ad1270b_architecture_fitness.py tests/test_layer_boundaries.py` |
| **M2** the route's report | HIGH | 7.4 `src/probos/routers/security.py`; 7.5 new `tests/test_bf939_forget_route.py` | `tests/test_bf939_forget_route.py tests/test_bf939_shared_attachment_ownership.py tests/test_ad1341_s3_erasure_cascade.py tests/test_ad1341_s4_exit_note_erasure.py tests/test_bf905_erasure_live_scan.py tests/test_ad1340_s2a_lookup_route.py tests/test_ad1340_s2b_restore_route.py tests/test_ad1025b_path_anchoring.py tests/test_ad1270b_architecture_fitness.py tests/test_layer_boundaries.py` |
| **M3** trackers | docs | §8 | `tests/test_ad1184_ad_ledger.py`; `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check` |

M1's list includes every test file that builds an `ErasureManager` (Grep `ErasureManager\b` over `tests/`: nine files, 42 occurrences). **Expected focused counts** (home-guard runner, `-Workers 4`, measured 2026-10-26): **M1: 412 passed** (390 on the merged base's 14 existing files, plus the new file's 22 cases) and **M2: 239 passed** (216 on the merged base's 8 existing files, plus the new file's 22 cases and the route test). No skips; the warnings are third-party deprecations.

## 5. Consumers of every value this changes

| Value | Consumers | Effect |
|---|---|---|
| `ErasureResult.retained_attachments` (new last field, default `{}`) | Built at `_erase_episode` and `_forget_all` only (Grep `ErasureResult\(`: no test builds it). Read by the route (M2) and the new tests. Existing readers of `count`, `timestamps` and `deleted_*`: `routers/security.py:157-160`, `_forget_all` | additive; no consumer must change |
| `"retained_attachment_ids"` in `/forget`'s 200 body | No HXI, desktop, CLI or script caller (Absence AV1). Route tests read keys one at a time; none compares the whole `/forget` body (AV7) | additive |
| `forget_episode` can raise `ErasureCascadeIncomplete` (single path, owner scan failed after the erase) | `request_erasure` has no handler for it, so the route answers 500, as for cascades (BF-905 D6). `_forget_all` no longer calls `forget_episode` | new raise site; same status |
| `_forget_all` no longer calls `forget_episode` | the per-episode checks run inline, unchanged (D7). S3's E8 and E9[late] and S4's X1b still hold (M1 gate) | none |
| `_delete_attachments` removed; `_unlink_attachments` (module) added | callers: `forget_episode` only (AV2) | internal |
| `_matching_ids(matches, owners=None, wanted=None)` | `forget_resource`, `forget_agent_memory`, `forget_episode` | the default keeps the old behaviour |
| `cognitive/memory_probes.py:82` (qualification cleanup) | calls `evict_by_ids(..., disposition=ERASE)` directly, never `ErasureManager`, and unlinks no attachment | unaffected |
| The reaper (`attachments/reaper.py`) | deletes by age and origin, independently | unaffected |

## 6. Tests

New file `tests/test_bf939_shared_attachment_ownership.py` (M1). Real `EpisodicMemory` (S1's `_memory` rig, archive mode), real `FilesystemAttachmentStore`, real `ErasureManager`, real `ArchiveStore`, and the Captain's real `probos archive erase`. It is modelled on the S3 M3 reviewer's probes `logs/bf939/test_late_failure_and_shared_trace.py` and `test_shared_baseline_comparison.py`. Every test asserts its premise first.

| # | Test | What it proves | On the base |
|---|---|---|---|
| T1 | `test_erasing_one_of_two_episodes_that_share_an_attachment_keeps_it[episode, agent, resource]` | Each entry point keeps a blob the unerased episode names; `retained_attachments == {sha: [other]}`; `count == 1` | `deleted_attachment_ids == []` fails (`[sha]`) |
| T2 | `test_an_archived_episode_that_names_the_attachment_keeps_it[episode, agent, resource]` | An archived owner protects it too | as T1 |
| T3 | `test_an_episodes_own_archived_version_does_not_keep_its_attachment` | Owners are keyed by id | `AttributeError: retained_attachments` |
| T4 | `test_erasing_every_episode_that_names_the_attachment_removes_it[agent, resource]` | A cascade that erases every owner removes the blob once; `count == 3` | `AttributeError` |
| T5 | `test_two_owners_erased_one_after_the_other_remove_it_with_the_second` | The first erase keeps it, the second removes it | `AttributeError` |
| T6 | `test_a_match_the_archive_refuses_keeps_the_attachment_it_shares[first, last]` | A match S3 refuses (a citation lands mid-cascade, S3's `_midway`) is left whole and keeps the shared blob. In either order (`first`: kept and reported; `last`: deferral, nothing decided), after the Captain's `probos archive erase` the retry removes it | `exists` is False |
| T7 | `test_a_match_whose_erase_fails_partway_still_lets_the_shared_attachment_go` | A-1: the first match's erase deletes its live row and then fails (participant sweep). The blob still goes at the second match's turn and is not stranded | passes (guards A-1) |
| T8 | `test_an_episode_whose_own_row_cannot_be_rebuilt_is_still_erased_with_its_attachment` | A-2: the single path's scan fails on the episode's own row. It erases, unlinks, raises `ErasureCascadeIncomplete` (`failures == {}`) and logs BF-939; the retry is clean | `pytest.raises` fails |
| T9 | `test_an_owner_the_failed_scan_reached_still_keeps_the_attachment[episode, agent]` | D5: an owner seen before the scan failed keeps the blob | `[episode]` does not raise; `[agent]` `AttributeError` |
| T10 | `test_an_owner_the_failed_scan_could_not_read_does_not_keep_the_attachment[episode, agent]` | D5's disclosed bound: under-erasing is the worse failure | `[episode]` does not raise; `[agent]` passes |
| T11 | `test_each_entry_point_scans_for_owners_at_most_once_and_keeps_the_per_episode_citation_check[agent, episode-with-attachment, episode-without-attachment, refused]` | One live and one archive scan per cascade; 1 + N archive citation reads (S3 D10, unchanged: A-3); the single path scans only when the episode declares an attachment; a refusal scans nothing | `[episode-with-attachment]` live 0 ≠ 1; the others pass |

New file `tests/test_bf939_forget_route.py` (M2): `test_the_forget_route_reports_the_attachment_it_kept_and_removes_it_with_the_last_episode`. The real app goes through S2a's `_client` with a real `FilesystemAttachmentStore` on the runtime. The first answer is 200 with `retained_attachment_ids == {sha: [other]}` and `deleted_count == 1`. The second is `deleted_attachment_ids == [sha]` and `deleted_count == 2`. On the base: `KeyError 'retained_attachment_ids'`.

**Doubles without `iter_live_episodes`.**
- `test_bf868_erasure_declared_fields.py::_FakeMetadataOnlyMemory` (`:73-92`) gets an empty `iter_live_episodes` in 7.2. Without it, the 7 single-path cases that declare an attachment would raise from the owner scan: `test_each_producer_erases_through_the_flat_metadata_fallback` ×4, `test_p4_image_gen_metadata_attachment_id_is_erased`, `test_unparseable_outcomes_json_degrades_and_logs` and `test_an_empty_anchors_json_is_not_reported_as_a_failure`.
- `test_flat_fallback_still_refuses_free_text` declares no attachment and runs no scan.
- The other doubles already have `iter_live_episodes`: `test_bf868::_FakeEpisodicMemory:64`, `test_bf869:48`, `test_erasure_manager:42`.
- `test_ad1340_s1_erasure.py:92-113` holds attachment doubles on a real memory and needs no change. R11 (`:539-561`) passes unchanged under D5 by analysis: the archive scan fails, the live scan saw only `_T`, so the blob is unlinked, then the erase raises `episode_archive_unavailable_for_erase`.
- `test_bf905::_ListOnlyMemory` is used only by cascades, with no attachment store.

## 7. The contract

### 7.1 `src/probos/knowledge/erasure.py` (M1)

Pair 1 (the report field):

SEARCH:
```python
@dataclasses.dataclass(frozen=True)
class ErasureResult:
    count: int
    timestamps: list[str]
    deleted_episode_ids: list[str]
    deleted_attachment_ids: list[str]
```
REPLACE:
```python
@dataclasses.dataclass(frozen=True)
class ErasureResult:
    count: int
    timestamps: list[str]
    deleted_episode_ids: list[str]
    deleted_attachment_ids: list[str]
    # BF-939 (#1683): each attachment kept because an episode this request did not erase still names it, with those
    # episodes (both sorted). Last, with a default, so every construction stays valid.
    retained_attachments: dict[str, list[str]] = dataclasses.field(default_factory=dict)
```

Pair 2 (the single path raises it too):

SEARCH:
```python
    """AD-1340: a cascade erased what it could, and some matching episodes are not erased.
```
REPLACE:
```python
    """AD-1340: a cascade erased what it could, and some matching episodes are not erased.

    BF-939 (#1683): ``forget_episode`` raises it too, with ``failures`` empty, when its attachment-owner scan failed
    and the episode was erased all the same: an owner the scan did not reach was not checked.
```

Pair 3 (the owner recorder and the unlink rule, module functions):

SEARCH:
```python
    async for episode in memory.iter_live_episodes():
        yield episode
```
REPLACE:
```python
    async for episode in memory.iter_live_episodes():
        yield episode


def _recording_owners(
    matches: Callable[[Any], bool],
    owners: dict[str, set[str]],
    attachment_ids_of: Callable[[Any], set[str]],
    wanted: set[str] | None,
) -> Callable[[Any], bool]:
    """BF-939 (#1683): ``matches``, also recording each scanned episode as an owner of the attachment ids it names.

    The scan a cascade already makes is the owner scan, so the check adds no read. Owners are keyed by episode id,
    so an episode's own archived versions never count as another owner. ``wanted`` limits what is recorded (one
    episode's ids, on the single path); None records every id. A module function, so ``ErasureManager`` stays within
    its 15-method SRP trigger.
    """

    def predicate(episode: Any) -> bool:
        episode_id = str(getattr(episode, "id", ""))
        if episode_id:
            named = attachment_ids_of(episode)
            for attachment_id in named if wanted is None else named & wanted:
                owners.setdefault(attachment_id, set()).add(episode_id)
        return matches(episode)

    return predicate


def _last_turns(owners: Mapping[str, set[str]], request: list[str]) -> dict[str, int]:
    """BF-939: for each attachment id the owner scan saw a request member name, the turn of the last such member."""
    turn_of = {episode_id: index for index, episode_id in enumerate(request)}
    last: dict[str, int] = {}
    for attachment_id, named in owners.items():
        turns = [turn_of[episode_id] for episode_id in named if episode_id in turn_of]
        if turns:
            last[attachment_id] = max(turns)
    return last


def _decide_attachments(
    turn: int,
    candidates: set[str],
    owners: Mapping[str, set[str]],
    last_turns: Mapping[str, int],
    request: set[str],
    intact: set[str],
) -> tuple[set[str], dict[str, list[str]]]:
    """BF-939 (#1683): which attachments to unlink in this turn, and which to keep, with the episodes holding each.

    An attachment is decided in the turn of the last request member that names it (``last_turns``; one only this
    member's own records name is decided now), before that member is erased, so AD-1340's order (unlink, then
    evict) holds for the member that decides it. It is unlinked unless an episode outside the request, or a member
    left whole (``intact``: refused, or failed before its erase began), still names it; then it is kept and
    reported. ``owners`` maps an attachment id to every scanned episode id naming it.
    """
    unlink: set[str] = set()
    kept: dict[str, list[str]] = {}
    for attachment_id in sorted(candidates):
        if last_turns.get(attachment_id, turn) > turn:
            continue  # BF-939: a later member names it and decides it in its own turn
        named = owners.get(attachment_id, set())
        holders = (named - request) | (named & intact)
        if holders:
            kept[attachment_id] = sorted(holders)
        else:
            unlink.add(attachment_id)
    return unlink, kept


async def _unlink_attachments(store: Any | None, attachment_ids: set[str]) -> list[str]:
    """Unlink each attachment; return the sorted ids the store reported as removed (BF-939: was a manager method)."""
    if store is None:
        return []
    unlinked: list[str] = []
    for attachment_id in sorted(attachment_ids):
        if await store.unlink(attachment_id):
            unlinked.append(attachment_id)
    return unlinked
```

Pair 4 (`forget_episode`'s docstring: the disclosure):

SEARCH:
```python
        """Delete one episode and related attachment refs, then mark audit rows.

        The attachments are unlinked BEFORE the episode is erased (AD-1340): delete what a record names before
        you delete the record. The attachment ids exist only in the episode's own records, and a failed erase has
        already removed them by the time it raises, so a retry could never find them again. ``mark_deleted`` runs
        only after a successful erase; an erase failure is raised as the original typed error, unwrapped.
        """
```
REPLACE:
```python
        """Delete one episode and the attachments no other episode names, then mark audit rows.

        The attachments are unlinked BEFORE the episode is erased (AD-1340): delete what a record names before
        you delete the record. The attachment ids exist only in the episode's own records, and a failed erase has
        already removed them by the time it raises, so a retry could never find them again. ``mark_deleted`` runs
        only after a successful erase; an erase failure is raised as the original typed error, unwrapped.

        BF-939 (#1683): the attachment store is content-addressed, so one file can hold bytes several episodes name.
        An attachment another live or archived episode still names is kept, and listed in ``retained_attachments``
        with those episodes; it goes when the last episode naming it is erased. Only when this episode names an
        attachment are the live and archived episodes scanned, once, for the other owners. Owners outside episodic
        memory (thread pins, chat, work items, artifacts) are not checked: an attachment only they hold is unlinked,
        as before. If the scan fails, the episode is still erased, an attachment is kept only for an owner the scan
        reached, and ``ErasureCascadeIncomplete`` is raised after the erase (under-erasing is the worse failure,
        BF-868).
        """
```

Pair 5 (`forget_episode`'s body, and the one erase path):

SEARCH:
```python
        attachment_ids = await self._attachment_ids_for_episode(episode_id)
        unlinked = await self._delete_attachments(attachment_ids)
        deleted_episodes = 0
        if self._episodic_memory is not None and hasattr(self._episodic_memory, "evict_by_ids"):
            # AD-1340: erasure is explicit, never derived from the caller's
            # free-text reason (routers/security.py:23,73).
            deleted_episodes = int(
                await self._episodic_memory.evict_by_ids(
                    [episode_id], reason=reason, disposition=EvictionDisposition.ERASE,
                )
            )

        if self._audit_log is not None:
            await self._audit_log.mark_deleted(episode_id)

        return ErasureResult(
            count=deleted_episodes + len(unlinked),
            timestamps=[self._now_iso()],
            deleted_episode_ids=[episode_id] if deleted_episodes > 0 else [],
            deleted_attachment_ids=unlinked,
        )
```
REPLACE:
```python
        attachment_ids = await self._attachment_ids_for_episode(episode_id)
        owners: dict[str, set[str]] = {}
        scan_error: Exception | None = None
        if attachment_ids and self._attachment_store is not None:  # BF-939: one owner scan, only when a blob could go
            _found, scan_error = await self._matching_ids(lambda _episode: False, owners, attachment_ids)
        unlink, kept = _decide_attachments(0, attachment_ids, owners, {}, {episode_id}, set())
        result = await self._erase_episode(episode_id, reason, unlink, kept)
        if scan_error is not None:
            logger.warning(
                "BF-939: the attachment-owner scan failed, so an owner it did not reach was not checked; "
                "the episode was erased and the failure is raised",
            )
            raise ErasureCascadeIncomplete(result, {}, scan_error) from scan_error
        return result

    async def _erase_episode(
        self, episode_id: str, reason: str, unlink: set[str], kept: dict[str, list[str]],
    ) -> ErasureResult:
        """Unlink ``unlink``, erase the episode, then mark its audit rows; ``kept`` is reported (BF-939).

        The one erase path of ``forget_episode`` and the cascades, after their checks, so AD-1340's order (unlink,
        then evict) is written once.
        """
        unlinked = await _unlink_attachments(self._attachment_store, unlink)
        deleted_episodes = 0
        if self._episodic_memory is not None and hasattr(self._episodic_memory, "evict_by_ids"):
            # AD-1340: erasure is explicit, never derived from the caller's
            # free-text reason (routers/security.py:23,73).
            deleted_episodes = int(
                await self._episodic_memory.evict_by_ids(
                    [episode_id], reason=reason, disposition=EvictionDisposition.ERASE,
                )
            )

        if self._audit_log is not None:
            await self._audit_log.mark_deleted(episode_id)

        return ErasureResult(
            count=deleted_episodes + len(unlinked),
            timestamps=[self._now_iso()],
            deleted_episode_ids=[episode_id] if deleted_episodes > 0 else [],
            deleted_attachment_ids=unlinked,
            retained_attachments=kept,
        )
```

Pair 6 (the resource cascade records owners in its scan):

SEARCH:
```python
        matching_ids, enumeration_error = await self._matching_ids(mentions_resource)
        await _refuse_while_the_archive_cites(self._archive_store, matching_ids)  # AD-1341 S3: a resource's matches
        return await self._forget_all(matching_ids, enumeration_error)
```
REPLACE:
```python
        owners: dict[str, set[str]] = {}  # BF-939: the same scan records every episode's attachments
        matching_ids, enumeration_error = await self._matching_ids(mentions_resource, owners)
        await _refuse_while_the_archive_cites(self._archive_store, matching_ids)  # AD-1341 S3: a resource's matches
        return await self._forget_all(matching_ids, enumeration_error, owners)
```

Pair 7 (the agent cascade records owners in its scan):

SEARCH:
```python
        matching_ids, enumeration_error = await self._matching_ids(involves_agent)
        await _refuse_while_the_archive_cites(self._archive_store, matching_ids)  # AD-1341 S3: an agent's matches
        return await self._forget_all(matching_ids, enumeration_error)
```
REPLACE:
```python
        owners: dict[str, set[str]] = {}  # BF-939: the same scan records every episode's attachments
        matching_ids, enumeration_error = await self._matching_ids(involves_agent, owners)
        await _refuse_while_the_archive_cites(self._archive_store, matching_ids)  # AD-1341 S3: an agent's matches
        return await self._forget_all(matching_ids, enumeration_error, owners)
```

Pair 8 (`_matching_ids` records owners in the same pass):

SEARCH:
```python
    async def _matching_ids(self, matches: Callable[[Any], bool]) -> tuple[list[str], Exception | None]:
        """The ids of the candidate episodes ``matches`` accepts, and the first error that cut a scan short, if any.

        BF-905: the live store and the archive are scanned separately, live first, so a failure of one never skips
        the other. A failed scan keeps the matches it found before failing; the caller erases every match from both
        scans, then raises ``ErasureCascadeIncomplete`` carrying the FIRST scan error (``_scan`` logs each at ERROR).
        Under-erasing is the worse failure (BF-868). An archived version is NOT dropped because its id is also live
        (AD-1340 R1): deterministic ids can have a live rewrite that differs from the archived version, and the
        predicate must see both; duplicate ids are removed here.
        """
        memory = self._episodic_memory
        if memory is None:
            return [], None  # F-130 (#1523) owns the unwired case: no episodic memory, nothing to scan
        live, live_error = await self._scan("live", _live_episodes(memory), matches)
        archived, archive_error = await self._scan("archive", self._archived_episodes(), matches)
```
REPLACE:
```python
    async def _matching_ids(
        self, matches: Callable[[Any], bool], owners: dict[str, set[str]] | None = None, wanted: set[str] | None = None,
    ) -> tuple[list[str], Exception | None]:
        """The ids of the candidate episodes ``matches`` accepts, and the first error that cut a scan short, if any.

        BF-905: the live store and the archive are scanned separately, live first, so a failure of one never skips
        the other. A failed scan keeps the matches it found before failing; the caller erases every match from both
        scans, then raises ``ErasureCascadeIncomplete`` carrying the FIRST scan error (``_scan`` logs each at ERROR).
        Under-erasing is the worse failure (BF-868). An archived version is NOT dropped because its id is also live
        (AD-1340 R1): deterministic ids can have a live rewrite that differs from the archived version, and the
        predicate must see both; duplicate ids are removed here.

        BF-939 (#1683): with ``owners``, every scanned episode's declared attachment ids (only the ``wanted`` ones, if
        given) are recorded in it by episode id, in this same pass, so the owner check adds no read.
        """
        memory = self._episodic_memory
        if memory is None:
            return [], None  # F-130 (#1523) owns the unwired case: no episodic memory, nothing to scan
        if owners is not None:  # BF-939: one pass both matches and records each episode's attachment owners
            matches = _recording_owners(
                matches, owners, lambda episode: self._extract_attachment_ids(self._episode_to_dict(episode)), wanted,
            )
        live, live_error = await self._scan("live", _live_episodes(memory), matches)
        archived, archive_error = await self._scan("archive", self._archived_episodes(), matches)
```

Pair 9 (the cascade: per-episode checks unchanged, one erase path, the turn rule; **S4 anchor**):

SEARCH:
```python
    async def _forget_all(self, episode_ids: list[str], enumeration_error: Exception | None) -> ErasureResult:
        """Erase each episode in turn; raise ``ErasureCascadeIncomplete`` if the scan or any erase failed."""
        _refuse_while_an_exit_note_cites(self._exit_note_citations, episode_ids)  # AD-1341 S4: a scan's matches, first
        total_count = 0
        deleted_episodes: list[str] = []
        deleted_attachments: set[str] = set()
        failures: dict[str, Exception] = {}
        for episode_id in episode_ids:
            try:
                result = await self.forget_episode(episode_id)
            except Exception as exc:
                failures[episode_id] = exc  # erase the rest, then raise one error naming every failure
                logger.error(
                    "AD-1340: erasing episode %s failed: %r; "
                    "the remaining episodes are still erased, then the failure is raised",
                    episode_id, exc,
                )
                continue
            total_count += result.count
            deleted_episodes.extend(result.deleted_episode_ids)
            deleted_attachments.update(result.deleted_attachment_ids)

        erased = ErasureResult(
            count=total_count,
            timestamps=[self._now_iso()],
            deleted_episode_ids=deleted_episodes,
            deleted_attachment_ids=sorted(deleted_attachments),
        )
```
REPLACE:
```python
    async def _forget_all(
        self, episode_ids: list[str], enumeration_error: Exception | None, owners: dict[str, set[str]],
    ) -> ErasureResult:
        """Erase each episode in turn; raise ``ErasureCascadeIncomplete`` if the scan or any erase failed.

        BF-939 (#1683): ``owners`` maps each attachment id the scan saw to every episode naming it. Each match passes
        the per-episode checks ``forget_episode`` makes, then the one erase path, with no second owner scan. An
        attachment is decided in the turn of the last match naming it: unlinked unless an episode outside the
        matches, or a match left whole (refused, or failed before its erase began), still names it; then it is kept
        and reported in ``retained_attachments``. After a failed scan the map is incomplete, and an attachment is
        unlinked when every owner the scan reached is a match (under-erasing is the worse failure, BF-868).
        """
        _refuse_while_an_exit_note_cites(self._exit_note_citations, episode_ids)  # AD-1341 S4: a scan's matches, first
        if enumeration_error is not None and owners:
            logger.warning(
                "BF-939: the erasure scan failed, so the attachment-owner map is incomplete; an attachment is "
                "unlinked when every owner the scan reached is erased by this request",
            )
        request = set(episode_ids)
        last_turns = _last_turns(owners, episode_ids)
        due: dict[int, set[str]] = {}
        for attachment_id, last_turn in last_turns.items():
            due.setdefault(last_turn, set()).add(attachment_id)
        decided: set[str] = set()
        intact: set[str] = set()
        retained: dict[str, set[str]] = {}
        total_count = 0
        deleted_episodes: list[str] = []
        deleted_attachments: set[str] = set()
        failures: dict[str, Exception] = {}
        for turn, episode_id in enumerate(episode_ids):
            began = False
            try:
                # AD-1341 S3 (D10) and S4: the per-episode checks forget_episode makes, unchanged (S4 register R17)
                await _refuse_while_the_archive_cites(self._archive_store, [episode_id])
                _refuse_while_an_exit_note_cites(self._exit_note_citations, [episode_id])
                attachment_ids = await self._attachment_ids_for_episode(episode_id)
                candidates = (attachment_ids | due.get(turn, set())) - decided
                unlink, kept = _decide_attachments(turn, candidates, owners, last_turns, request, intact)
                decided |= unlink | set(kept)
                for attachment_id, holders in kept.items():
                    retained.setdefault(attachment_id, set()).update(holders)
                began = True
                result = await self._erase_episode(episode_id, "user_request", unlink, kept)
            except Exception as exc:
                failures[episode_id] = exc  # erase the rest, then raise one error naming every failure
                if not began:
                    intact.add(episode_id)  # BF-939: its records stand, so it still holds what it names
                logger.error(
                    "AD-1340: erasing episode %s failed: %r; "
                    "the remaining episodes are still erased, then the failure is raised",
                    episode_id, exc,
                )
                continue
            total_count += result.count
            deleted_episodes.extend(result.deleted_episode_ids)
            deleted_attachments.update(result.deleted_attachment_ids)

        erased = ErasureResult(
            count=total_count,
            timestamps=[self._now_iso()],
            deleted_episode_ids=deleted_episodes,
            deleted_attachment_ids=sorted(deleted_attachments),
            retained_attachments={key: sorted(value) for key, value in sorted(retained.items())},
        )
```

Pair 10 (the method moved out; `ErasureManager` stays at 15):

SEARCH:
```python
    async def _delete_attachments(self, attachment_ids: set[str]) -> list[str]:
        """Unlink each attachment; return the sorted ids the store reported as removed."""
        if self._attachment_store is None:
            return []
        unlinked: list[str] = []
        for attachment_id in sorted(attachment_ids):
            if await self._attachment_store.unlink(attachment_id):
                unlinked.append(attachment_id)
        return unlinked

    def _extract_attachment_ids(self, payload: Any) -> set[str]:
```
REPLACE:
```python
    def _extract_attachment_ids(self, payload: Any) -> set[str]:
```

### 7.2 `tests/test_bf868_erasure_declared_fields.py` (M1: the flat-fallback double can be scanned)

SEARCH:
```python
    def __init__(self, metadata: dict) -> None:
        self._metadata = metadata

    async def get_by_ids(self, ids: list[str]) -> list[_Episode]:
        return []
```
REPLACE:
```python
    def __init__(self, metadata: dict) -> None:
        self._metadata = metadata

    async def get_by_ids(self, ids: list[str]) -> list[_Episode]:
        return []

    async def iter_live_episodes(self) -> AsyncIterator[_Episode]:
        """BF-939: the attachment-owner scan finds no other episode. These tests are about the extractor; a real
        store's row that cannot be rebuilt makes that scan raise, which test_bf939_shared_attachment_ownership covers
        (the episode is erased, then the failure is raised)."""
        nothing: list[_Episode] = []
        for episode in nothing:
            yield episode
```

### 7.3 New file: `tests/test_bf939_shared_attachment_ownership.py` (M1)

```python
"""BF-939 (#1683): an AD-754 erasure keeps a content-addressed attachment another episode still names.

A real ``EpisodicMemory`` (``test_ad1340_s1_eviction``'s rig, archive mode), a real ``FilesystemAttachmentStore``, the
real ``ErasureManager``, the real ``ArchiveStore`` and the Captain's real ``probos archive erase``. Modelled on the
AD-1341 S3 M3 reviewer's probes. ``asyncio_mode = "auto"``, so no asyncio marks. Every test states its premise first.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import hashlib
import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.cognitive.episode_archive import EpisodeErasureIncomplete
from probos.cognitive.participant_index import ParticipantIndex
from probos.knowledge.archive_store import ArchiveStore, PromotionOutcome
from probos.knowledge.erasure import ArchiveCitationsBlockErasure, ErasureCascadeIncomplete, ErasureManager
from probos.storage.sqlite_factory import default_factory
from probos.types import Episode, EpisodeStoreOutcome
from tests.test_ad1340_s1_eviction import _episode, _memory, _raw
from tests.test_ad1341_s1_archive_store import _record
from tests.test_ad1341_s1_reset_and_erase import _config, _erase
from tests.test_ad1341_s3_erasure_cascade import _midway

_BODY = b"bf939: one photograph, two episodes"
_SHA = hashlib.sha256(_BODY).hexdigest()
_RESOURCE = "/srv/bf939/coolant.log"
_A, _B, _C = "ep-000", "ep-001", "ep-002"  # _midway lands a citation of ep-000


def _naming(i: int, *, agent: str = "agent-a", resource: bool = False, attachment: bool = True) -> Episode:
    """``_episode(i)`` for ``agent``; it names the shared attachment unless ``attachment`` is False."""
    episode = _episode(i)
    outcome: dict[str, Any] = {"intent": "report", "success": True}
    if attachment:
        outcome["attachment_refs"] = [_SHA]
    text = f"{episode.user_input} under {_RESOURCE}" if resource else episode.user_input
    return dataclasses.replace(episode, agent_ids=[agent], user_input=text, outcomes=[outcome])


async def _stored(em: Any, episodes: list[Episode], *, archived: tuple[str, ...] | list[str] = ()) -> None:
    for episode in episodes:
        assert await em.store(episode) is EpisodeStoreOutcome.STORED
    for episode_id in archived:
        assert await em.evict_by_ids([episode_id], reason="activation_decay") == 1
    live = sorted({episode.id for episode in episodes} - set(archived))
    assert sorted(_raw(em, [episode.id for episode in episodes])["ids"]) == live  # premise: live and archived as asked


def _cannot_rebuild(em: Any, episode_id: str) -> None:
    """BF-905's schema drift: the row stays live, and rebuilding it raises (test-only private access)."""
    meta = _raw(em, [episode_id])["metadatas"][0]
    em._collection.update(ids=[episode_id], metadatas=[{**meta, "anchors_json": json.dumps({"retired_field": "drift"})}])


@contextlib.asynccontextmanager
async def _vessel(tmp_path: Path) -> AsyncIterator[tuple[Any, FilesystemAttachmentStore]]:
    async with _memory(tmp_path / "vessel", "archive") as rig:
        attachments = FilesystemAttachmentStore(tmp_path / "attachments")
        try:
            await attachments.write(_SHA, _BODY, "text/plain")
            assert await attachments.exists(_SHA)  # premise: the one shared file
            yield rig, attachments
        finally:
            attachments.close()


def _manager(rig: Any, attachments: FilesystemAttachmentStore, archive: ArchiveStore | None = None) -> ErasureManager:
    return ErasureManager(rig.em, attachments, None, archive_store=archive)


async def _forget(manager: ErasureManager, target: str) -> Any:
    if target == "episode":
        return await manager.forget_episode(_A)
    if target == "agent":
        return await manager.forget_agent_memory("agent-a")
    return await manager.forget_resource(_RESOURCE)


class _CountedArchive(ArchiveStore):
    """The real store, counting its citation reads (S3's D10 check)."""

    def __init__(self, path: Path) -> None:
        super().__init__(str(path), connection_factory=default_factory)
        self.citation_reads = 0

    async def entry_ids_citing(self, episode_ids: list[str] | tuple[str, ...]) -> tuple[int, ...]:
        self.citation_reads += 1
        return await super().entry_ids_citing(episode_ids)


def _count_scans(monkeypatch: pytest.MonkeyPatch, em: Any) -> dict[str, int]:
    calls = {"live": 0, "archive": 0}
    for name, key in (("iter_live_episodes", "live"), ("iter_archived_episodes", "archive")):
        inner = getattr(em, name)

        def counted(*args: Any, _inner: Any = inner, _key: str = key, **kwargs: Any) -> Any:
            calls[_key] += 1
            return _inner(*args, **kwargs)

        monkeypatch.setattr(em, name, counted)
    return calls


# --- T1 to T5: who keeps a shared attachment ---------------------------------------------------------------------


@pytest.mark.parametrize("target", ["episode", "agent", "resource"])
async def test_erasing_one_of_two_episodes_that_share_an_attachment_keeps_it(tmp_path: Path, target: str) -> None:
    async with _vessel(tmp_path) as (rig, attachments):
        await _stored(rig.em, [_naming(0, resource=True), _naming(1, agent="agent-b")])

        result = await _forget(_manager(rig, attachments), target)

        assert result.deleted_episode_ids == [_A]
        assert result.deleted_attachment_ids == []
        assert result.retained_attachments == {_SHA: [_B]}
        assert result.count == 1
        assert sorted(_raw(rig.em, [_A, _B])["ids"]) == [_B]
        assert await attachments.exists(_SHA)


@pytest.mark.parametrize("target", ["episode", "agent", "resource"])
async def test_an_archived_episode_that_names_the_attachment_keeps_it(tmp_path: Path, target: str) -> None:
    async with _vessel(tmp_path) as (rig, attachments):
        await _stored(rig.em, [_naming(0, resource=True), _naming(1, agent="agent-b")], archived=[_B])

        result = await _forget(_manager(rig, attachments), target)

        assert result.deleted_episode_ids == [_A]
        assert result.deleted_attachment_ids == []
        assert result.retained_attachments == {_SHA: [_B]}
        assert await attachments.exists(_SHA)


async def test_an_episodes_own_archived_version_does_not_keep_its_attachment(tmp_path: Path) -> None:
    async with _vessel(tmp_path) as (rig, attachments):
        first = _naming(0)
        await _stored(rig.em, [first], archived=[_A])
        assert await rig.em.store(dataclasses.replace(first, user_input=f"{first.user_input}, rewritten")) is (
            EpisodeStoreOutcome.STORED
        )
        assert _raw(rig.em, [_A])["ids"] == [_A]  # premise: one live and one archived version under one id

        result = await _manager(rig, attachments).forget_episode(_A)

        assert result.deleted_attachment_ids == [_SHA]
        assert result.retained_attachments == {}
        assert not await attachments.exists(_SHA)


@pytest.mark.parametrize("target", ["agent", "resource"])
async def test_erasing_every_episode_that_names_the_attachment_removes_it(tmp_path: Path, target: str) -> None:
    async with _vessel(tmp_path) as (rig, attachments):
        await _stored(rig.em, [_naming(0, resource=True), _naming(1, resource=True)], archived=[_B])

        result = await _forget(_manager(rig, attachments), target)

        assert sorted(result.deleted_episode_ids) == [_A, _B]
        assert result.deleted_attachment_ids == [_SHA]
        assert result.retained_attachments == {}
        assert result.count == 3  # two episodes and one attachment, unlinked once
        assert not await attachments.exists(_SHA)


async def test_two_owners_erased_one_after_the_other_remove_it_with_the_second(tmp_path: Path) -> None:
    async with _vessel(tmp_path) as (rig, attachments):
        await _stored(rig.em, [_naming(0), _naming(1, agent="agent-b")])
        manager = _manager(rig, attachments)

        first = await manager.forget_episode(_A)

        assert first.retained_attachments == {_SHA: [_B]}
        assert await attachments.exists(_SHA)

        second = await manager.forget_episode(_B)

        assert second.deleted_attachment_ids == [_SHA]
        assert second.retained_attachments == {}
        assert not await attachments.exists(_SHA)


# --- T6, T7: a match left whole, and a match whose erase began -----------------------------------------------------


@pytest.mark.parametrize("refused", ["first", "last"])
async def test_a_match_the_archive_refuses_keeps_the_attachment_it_shares(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, refused: str,
) -> None:
    store = _midway(tmp_path)  # a promotion citing ep-000 lands just after the cascade's first citation read (S3 E8)
    await store.initialize()
    try:
        async with _vessel(tmp_path) as (rig, attachments):
            # The cascade erases live matches first, then archived ones: this sets the refused match's turn.
            await _stored(rig.em, [_naming(0), _naming(1)], archived=[_B] if refused == "first" else [_A])
            manager = _manager(rig, attachments, store)

            with pytest.raises(ErasureCascadeIncomplete) as incomplete:
                await manager.forget_agent_memory("agent-a")

            assert set(incomplete.value.failures) == {_A}
            assert type(incomplete.value.failures[_A]) is ArchiveCitationsBlockErasure
            assert incomplete.value.result.deleted_episode_ids == [_B]
            assert await attachments.exists(_SHA)  # the refused match still names it
            # first: decided at ep-001's turn and kept for ep-000; last: ep-000 decides it, and was refused first
            assert incomplete.value.result.retained_attachments == ({_SHA: [_A]} if refused == "first" else {})

            (citing,) = await store.entry_ids_citing([_A])
            assert await asyncio.to_thread(_erase, monkeypatch, _config(tmp_path), citing, "the Captain forgets it") == 0
            retried = await manager.forget_agent_memory("agent-a")

            assert retried.deleted_episode_ids == [_A]
            assert retried.deleted_attachment_ids == [_SHA]
            assert not await attachments.exists(_SHA)
    finally:
        await store.close()


async def test_a_match_whose_erase_fails_partway_still_lets_the_shared_attachment_go(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    delete_episodes = ParticipantIndex.delete_episodes

    async def _fail_for_the_first(self: ParticipantIndex, episode_ids: list[str]) -> None:
        if _A in episode_ids:
            raise RuntimeError("injected: the participant index cannot delete ep-000")
        await delete_episodes(self, episode_ids)

    async with _vessel(tmp_path) as (rig, attachments):
        await _stored(rig.em, [_naming(0), _naming(1)], archived=[_B])  # erased in turn: ep-000 (live), then ep-001
        monkeypatch.setattr(ParticipantIndex, "delete_episodes", _fail_for_the_first)

        with pytest.raises(ErasureCascadeIncomplete) as incomplete:
            await _manager(rig, attachments).forget_agent_memory("agent-a")

        assert set(incomplete.value.failures) == {_A}
        assert isinstance(incomplete.value.failures[_A], EpisodeErasureIncomplete)
        assert incomplete.value.result.deleted_episode_ids == [_B]
        assert _raw(rig.em, [_A])["ids"] == []  # ep-000's record went before its sweep failed ...
        assert await rig.em.get_archived_metadata_versions(_A) == []  # ... and no archived copy of it names the file
        assert incomplete.value.result.deleted_attachment_ids == [_SHA]  # so the file went too: none is stranded
        assert not await attachments.exists(_SHA)


# --- T8 to T10: an owner scan that fails (A-2, D5) ------------------------------------------------------------------


async def test_an_episode_whose_own_row_cannot_be_rebuilt_is_still_erased_with_its_attachment(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    async with _vessel(tmp_path) as (rig, attachments):
        await _stored(rig.em, [_naming(0)])
        _cannot_rebuild(rig.em, _A)
        assert await rig.em.get_by_ids([_A]) == []  # premise: no read rebuilds it ...
        assert _SHA in (await rig.em.get_episode_metadata(_A))["outcomes_json"]  # ... and its raw row names the file
        caplog.set_level(logging.WARNING, logger="probos.knowledge.erasure")
        manager = _manager(rig, attachments)

        with pytest.raises(ErasureCascadeIncomplete) as incomplete:
            await manager.forget_episode(_A)

        error = incomplete.value
        assert error.failures == {}
        assert str(error.enumeration_error) == "erasure_live_rows_unrehydratable:1"
        assert error.result.deleted_episode_ids == [_A]
        assert error.result.deleted_attachment_ids == [_SHA]
        assert _raw(rig.em, [_A])["ids"] == []
        assert not await attachments.exists(_SHA)
        assert any("BF-939" in record.getMessage() for record in caplog.records)

        retried = await manager.forget_episode(_A)  # nothing is left to find, so the retry is clean

        assert retried.deleted_episode_ids == []
        assert retried.deleted_attachment_ids == []


@pytest.mark.parametrize("target", ["episode", "agent"])
async def test_an_owner_the_failed_scan_reached_still_keeps_the_attachment(tmp_path: Path, target: str) -> None:
    async with _vessel(tmp_path) as (rig, attachments):
        await _stored(rig.em, [_naming(0), _naming(1, agent="agent-b"), _naming(2, agent="agent-c", attachment=False)])
        _cannot_rebuild(rig.em, _C)  # an unrelated row: the live scan raises after yielding the other two

        with pytest.raises(ErasureCascadeIncomplete) as incomplete:
            await _forget(_manager(rig, attachments), target)

        assert str(incomplete.value.enumeration_error) == "erasure_live_rows_unrehydratable:1"
        assert incomplete.value.result.deleted_episode_ids == [_A]
        assert incomplete.value.result.retained_attachments == {_SHA: [_B]}
        assert await attachments.exists(_SHA)


@pytest.mark.parametrize("target", ["episode", "agent"])
async def test_an_owner_the_failed_scan_could_not_read_does_not_keep_the_attachment(tmp_path: Path, target: str) -> None:
    """D5's disclosed bound: under-erasing is the worse failure (BF-868), so a row no scan can read is no owner."""
    async with _vessel(tmp_path) as (rig, attachments):
        await _stored(rig.em, [_naming(0), _naming(1, agent="agent-b")])
        _cannot_rebuild(rig.em, _B)

        with pytest.raises(ErasureCascadeIncomplete) as incomplete:
            await _forget(_manager(rig, attachments), target)

        assert incomplete.value.result.deleted_episode_ids == [_A]
        assert incomplete.value.result.deleted_attachment_ids == [_SHA]
        assert not await attachments.exists(_SHA)
        assert _raw(rig.em, [_B])["ids"] == [_B]  # the unreadable row is reported by the scan, not erased


# --- T11: one owner scan per entry point; S3's per-episode check unchanged (A-3) ------------------------------------


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("agent", {"live": 1, "archive": 1, "citation_reads": 4}),  # the scan's read, then one per match (S3 D10)
        ("episode-with-attachment", {"live": 1, "archive": 1, "citation_reads": 1}),
        ("episode-without-attachment", {"live": 0, "archive": 0, "citation_reads": 1}),
        ("refused", {"live": 0, "archive": 0, "citation_reads": 1}),
    ],
)
async def test_each_entry_point_scans_for_owners_at_most_once_and_keeps_the_per_episode_citation_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str, expected: dict[str, int],
) -> None:
    store = _CountedArchive(tmp_path / "archive.db")
    await store.initialize()
    try:
        cited = (_A,) if case == "refused" else ("ep-elsewhere",)
        assert await store.promote_entry(_record(source_episode_ids=cited)) is PromotionOutcome.CREATED
        store.citation_reads = 0
        async with _vessel(tmp_path) as (rig, attachments):
            await _stored(rig.em, [_naming(0), _naming(1), _naming(2, attachment=False)])
            calls = _count_scans(monkeypatch, rig.em)
            manager = _manager(rig, attachments, store)

            if case == "agent":
                result = await manager.forget_agent_memory("agent-a")
                assert sorted(result.deleted_episode_ids) == [_A, _B, _C]
            elif case == "refused":
                with pytest.raises(ArchiveCitationsBlockErasure):
                    await manager.forget_episode(_A)
                assert await attachments.exists(_SHA)
            else:
                target = _A if case == "episode-with-attachment" else _C
                result = await manager.forget_episode(target)
                assert result.deleted_episode_ids == [target]

            assert {**calls, "citation_reads": store.citation_reads} == expected
    finally:
        await store.close()
```

### 7.4 `src/probos/routers/security.py` (M2)

Pair 1 (the disclosure; S3's docstring kept):

SEARCH:
```python
    AD-1341 S3: while a Ship's Archive entry cites an episode this request would erase, nothing is erased and the
    answer is 409 with the entries' ids. The archive is append-only for agents and services, so this route never
    erases an entry: the Captain erases each with ``probos archive erase ENTRY_ID --reason TEXT``, then retries.
    """
```
REPLACE:
```python
    AD-1341 S3: while a Ship's Archive entry cites an episode this request would erase, nothing is erased and the
    answer is 409 with the entries' ids. The archive is append-only for agents and services, so this route never
    erases an entry: the Captain erases each with ``probos archive erase ENTRY_ID --reason TEXT``, then retries.

    BF-939 (#1683): attachments are content-addressed, so one stored file can hold bytes several episodes name. An
    erasure removes the matched episodes' records and every attachment no other episode names. An attachment that an
    episode outside this request still names is kept, and ``retained_attachment_ids`` maps it to those episodes:
    erase them too to remove it. Attachment references held outside episodic memory (thread pins, chat, work items,
    artifacts) are not checked, so an attachment only they hold is removed, as before.
    """
```

Pair 2 (the report):

SEARCH:
```python
        "deleted_attachment_ids": result.deleted_attachment_ids,
    }
```
REPLACE:
```python
        "deleted_attachment_ids": result.deleted_attachment_ids,
        "retained_attachment_ids": result.retained_attachments,  # BF-939: each kept attachment -> the episodes naming it
    }
```

### 7.5 New file: `tests/test_bf939_forget_route.py` (M2)

```python
"""BF-939 (#1683) M2: the forget route reports each attachment it kept and the episodes that still name it.

The real app's ``POST /api/security/forget`` (S2a's client), a real ``EpisodicMemory`` and a real
``FilesystemAttachmentStore`` on the runtime.
"""

from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path

from probos.attachments.filesystem_store import FilesystemAttachmentStore
from probos.types import EpisodeStoreOutcome
from tests.test_ad1340_s1_eviction import _episode, _memory, _raw
from tests.test_ad1340_s2a_lookup_route import _client, _post, _runtime

_FORGET = "/api/security/forget"
_BODY = b"bf939: one photograph, two episodes, through the route"
_SHA = hashlib.sha256(_BODY).hexdigest()


async def test_the_forget_route_reports_the_attachment_it_kept_and_removes_it_with_the_last_episode(
    tmp_path: Path,
) -> None:
    root = tmp_path / "vessel"
    async with _memory(root, "archive") as rig:
        attachments = FilesystemAttachmentStore(tmp_path / "attachments")
        try:
            await attachments.write(_SHA, _BODY, "text/plain")
            first, second = (
                dataclasses.replace(
                    _episode(i), outcomes=[{"intent": "report", "success": True, "attachment_refs": [_SHA]}],
                )
                for i in (0, 1)
            )
            for episode in (first, second):
                assert await rig.em.store(episode) is EpisodeStoreOutcome.STORED
            assert await attachments.exists(_SHA)  # premise: one file, named by both episodes
            runtime = _runtime(root, rig.em)
            runtime.attachment_store = attachments

            async with _client(runtime) as client:
                kept = await _post(client, _FORGET, {"episode_id": first.id})

                assert kept.status_code == 200, kept.text
                assert kept.json()["deleted_episode_ids"] == [first.id]
                assert kept.json()["deleted_attachment_ids"] == []
                assert kept.json()["retained_attachment_ids"] == {_SHA: [second.id]}
                assert kept.json()["deleted_count"] == 1
                assert await attachments.exists(_SHA)

                removed = await _post(client, _FORGET, {"episode_id": second.id})

                assert removed.status_code == 200, removed.text
                assert removed.json()["deleted_attachment_ids"] == [_SHA]
                assert removed.json()["retained_attachment_ids"] == {}
                assert removed.json()["deleted_count"] == 2
            assert not await attachments.exists(_SHA)
            assert _raw(rig.em, [first.id, second.id])["ids"] == []
        finally:
            attachments.close()
```

## 8. Tracking (tracker pairs; M3's commit)

The anchors are the ones S4 used; both survive S4's merge. Set the date to the commit date.

**`PROGRESS.md`** (the new entry goes first, under the title):

SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**BF-939 (2026-10-2X), #1683 -- an AD-754 erasure keeps a content-addressed attachment another episode still names.** Erasing an episode (`POST /api/security/forget`, by episode, resource or agent) used to unlink every attachment the episode named, so a second episode that named the same bytes kept its record and lost its file. An erasure now removes an attachment only when no live or archived episode outside the request names it; a kept attachment is listed in the new `retained_attachment_ids` (attachment id to the episodes holding it), and goes when the last of them is erased. In a cascade, an attachment is decided in the turn of the last match naming it, and a match S3 or S4 refuses keeps what it shares. The single path scans live and archived episodes once, only when the episode names an attachment; the cascades record owners in the scan they already make. A failed scan still erases (under-erasing is the worse failure, BF-868) and raises; S3's and S4's per-episode checks are unchanged (S4 register R17 stays S5's). Owners outside episodic memory (thread pins, chat, work items, artifacts) are not checked. No schema, flag, config field, event type or route. New: `tests/test_bf939_shared_attachment_ownership.py`, `tests/test_bf939_forget_route.py`. The contract is `prompts/bf-939-shared-attachment-ownership.md`.
```

**`DECISIONS.md`** (before the `### Explicit delegation models` heading, as every entry since 2026-10-17):

SEARCH:
```markdown
### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```
REPLACE:
```markdown
### BF-939 -- An AD-754 erasure keeps a content-addressed attachment another episode still names (2026-10-2X, #1683)

- *Scope.* `knowledge/erasure.py` and `routers/security.py`, two new tests, and one test fake that gains an empty `iter_live_episodes`. Found by AD-1341 S3's M3 review (F3, register R11). The attachment store is content-addressed, so `forget_episode`'s unconditional unlink was an unrequested, unaudited partial erasure of any other episode naming the same bytes. Contract: `prompts/bf-939-shared-attachment-ownership.md`.
- *D1 (option (a), decided by the Architect; inside the envelope).* AD-754 protects the requester from the erased episode's content staying recoverable *through that episode*; that still holds. The record, every archived version and the audit marker go. The file stays only while an episode nobody asked to erase names it. Ranked (a) > (b) refuse while shared > (c) keep deleting. The Captain may overrule with (d), erase by content.
- *D2-D3 (owners and reads).* Owners are live episodes and every AD-1340 archived version, keyed by episode id, so an episode's own versions never protect its files. There is no index. The single path scans once, only when the episode names an attachment. The cascades record owners in their existing scan, so they add no read, and no longer call `forget_episode` per match.
- *D4 (cascades; amendment A-1).* An attachment is decided in the turn of the last match naming it. It is unlinked unless an episode outside the request, or a match left whole (refused, or failed before its erase began), names it. A match whose erase began counts as erased, because `_erase_ids` runs every phase before raising and its records may be gone; keeping the file for it could strand the file.
- *D5 (a failed scan; amendment A-2).* An attachment is unlinked when every owner the scan reached is erased by the request. The erasure proceeds and the failure is raised: as before on the cascades, and as `ErasureCascadeIncomplete` after the erase on the single path. Failing closed would have made an episode whose own row cannot be rebuilt unerasable at every entry point.
- *D7 (unchanged; amendment A-3).* S3's archive check and S4's exit-note check still run at every entry point and per match. S4 register R17 (the per-match citation read) stays S5's, because S3's E8 needs it. BF-868's declared fields and AD-1340's order and retention are unchanged.
- *Cost (measured on the Captain's host, 2026-10-2X).* <the orchestrator fills this from §11: the single-path and cascade timings at 10k and 100k episodes>.
- *Disclosed effects.* `/forget`'s 200 body gains `retained_attachment_ids`. `ErasureResult` gains `retained_attachments` (last field, default `{}`). A single-episode erasure whose owner scan fails now answers 500 after erasing (BF-905 D6: no typed body). Owners outside episodic memory are not checked (register G1). A file a newly stored episode names between the scan and the unlink is still unlinked, as before (G2).
- *Reversal.* Revert the BF-939 commits. Erasure unlinks every attachment the episode names again, and the response loses the new key.
- *What an AD-754 erasure removes (for the Captain).* The matched episodes' live records, every archived version and their sidecar rows. The audit rows are marked deleted. Every attachment that no other live or archived episode names is removed. An attachment another episode still names is kept and listed in `retained_attachment_ids` with those episodes; erase them to remove it. Attachment references outside episodic memory (thread pins, chat, work items, artifacts) are not checked.

### Explicit delegation models, plain-id profile models and the orchestrator's model guard (2026-10-17; F-91, F-116 and F-117 on #1523)
```

**After both edits:** `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` regenerates `docs/development/open-ads-report.md` and `docs/development/ad-ledger-snapshot.json`, which go in M3's commit. Verify with `--check` and `tests/test_ad1184_ad_ledger.py`.

**`docs/development/roadmap.md`:** no row. The Bug Tracker lists only bugs deliberately not fixed (`roadmap.md:1139`).

**The Captain-facing statement** (posted on #1683 at closure and in the PR body): the *What an AD-754 erasure removes* bullet above, word for word. No user documentation page covers AD-754 erasure (Absence AV6).

## 9. What this does NOT change

- S3's refusals: `_refuse_while_the_archive_cites` at every entry point and per match (D10, E8, E9), and the 409 `archive_entries_cite_erased_episodes` body.
- S4's refusals: `_refuse_while_an_exit_note_cites` at every entry point and per match, X1b (the refusal before any unlink or audit mark), and the 409 `exit_notes_cite_erased_episodes` body. `_pending_exit_note_citations` is untouched.
- BF-868's declared-field extraction (`_extract_attachment_ids`, `_normalize_payload`, `_ids_from_value`) and the metadata fallback.
- AD-1340: the unlink-then-evict order, `mark_deleted` after a successful erase only, `EvictionDisposition.ERASE`, `_erase_ids`, retention and the archive.
- BF-905's scans, `_scan`, its ERROR messages, and the route's 500 for `ErasureCascadeIncomplete`.
- `count`'s meaning; `/forget`'s request model; the missing authorization (S3 R1).
- `EpisodicMemory`, `FilesystemAttachmentStore`, the reaper, thread pins and every other attachment owner.
- No new flag, `EventType`, route, config field, table or `.db` file.

## 10. Mutation rows (18 rows; whole stripped lines, each occurring once in its file after §7)

One campaign on the assembled tree (M1 and M2 applied), after an unmutated baseline run of both new test files passes. Restore the file between rows. E-1 and E-2 mutate the same line.

| # | M | File | Line (stripped) | Mutate to | Killed by |
|---|---|---|---|---|---|
| E-1 | M1 | `src/probos/knowledge/erasure.py` | `holders = (named - request) \| (named & intact)` | `holders = named & intact` | T1, T2, T5 |
| E-2 | M1 | same | `holders = (named - request) \| (named & intact)` | `holders = named - request` | T6[first] |
| E-3 | M1 | same | `request = set(episode_ids)` | `request: set[str] = set()` | T4 |
| E-4 | M1 | same | `if last_turns.get(attachment_id, turn) > turn:` | `if False:` | T6[last] |
| E-5 | M1 | same | `last[attachment_id] = max(turns)` | `last[attachment_id] = min(turns)` | T6[last] |
| E-6 | M1 | same | `intact.add(episode_id)  # BF-939: its records stand, so it still holds what it names` | `pass` | T6[first] |
| E-7 | M1 | same | `began = True` | `pass` | T7 |
| E-8 | M1 | same | `if episode_id:` | `if False:` | T1, T2 |
| E-9 | M1 | same | `if owners is not None:  # BF-939: one pass both matches and records each episode's attachment owners` | `if False:` | T1, T2 |
| E-10 | M1 | same | `if attachment_ids and self._attachment_store is not None:  # BF-939: one owner scan, only when a blob could go` | `if False:` | T1[episode], T11[episode-with-attachment] |
| E-11 | M1 | same | `if scan_error is not None:` | `if False:` | T8, T9[episode] |
| E-12 | M1 | same | `raise ErasureCascadeIncomplete(result, {}, scan_error) from scan_error` | `raise scan_error` | T8 |
| E-13 | M1 | same | `result = await self._erase_episode(episode_id, "user_request", unlink, kept)` | `result = await self.forget_episode(episode_id)` | T11[agent] |
| E-14 | M1 | same | `retained.setdefault(attachment_id, set()).update(holders)` | `pass` | T6[first], T1[agent] |
| E-15 | M1 | same | `retained_attachments=kept,` | `retained_attachments={},` | T1[episode], T5 |
| E-16 | M1 | same | `unlink, kept = _decide_attachments(0, attachment_ids, owners, {}, {episode_id}, set())` | `unlink, kept = set(attachment_ids), {}` | T1[episode] |
| E-17 | M1 | same | `archived, archive_error = await self._scan("archive", self._archived_episodes(), matches)` | `archived, archive_error = [], None` | T2 |
| R-1 | M2 | `src/probos/routers/security.py` | `"retained_attachment_ids": result.retained_attachments,  # BF-939: each kept attachment -> the episodes naming it` | `"retained_attachment_ids": {},` | the route test |

Not given a row, each with the reason:
- `for attachment_id in named if wanted is None else named & wanted:` → `named`: equivalent; `wanted` bounds memory only.
- `candidates = (attachment_ids | due.get(turn, set())) - decided` and `decided |= unlink | set(kept)`: defence against the scan and the per-episode read disagreeing. On a real store the read includes everything the scan saw: the same rows rebuilt, plus BF-868's raw fallback (`erasure.py:345-360`). So both mutants survive, and are recorded as equivalent there.
- The WARNING lines: log only; T8 asserts the single path's.

Campaign of record: name the base tree and each file's sha256, and list the rows to re-run if a file differs, as BF-905's DECISIONS entry did.

## 11. Verified Against Codebase (2026-10-26, HEAD `4f855b90`, tree `1b7874e6f80300c29de88f769b595243d0da69f7`)

```
Read src/probos/knowledge/erasure.py (490 lines), whole
  61-66:   ErasureResult: count, timestamps, deleted_episode_ids, deleted_attachment_ids
  69-85:   class ErasureCascadeIncomplete(Exception) ... (result, failures, enumeration_error)
  102-113: async def _refuse_while_the_archive_cites(archive, episode_ids)
  116-125: async def _live_episodes(memory): async for episode in memory.iter_live_episodes(): yield episode
  141:     def _refuse_while_an_exit_note_cites(citations, episode_ids) -> None:     (S4)
  163-169: exit_note_citations: Mapping[...] | None = None; self._exit_note_citations = exit_note_citations   (S4)
  173-203: forget_episode: 181 archive check (S3), 182 exit-note check (S4), 183 _attachment_ids_for_episode, 184 _delete_attachments, evict ERASE, mark_deleted
  217-219, 232-234: _matching_ids(...); _refuse_while_the_archive_cites(...) # AD-1341 S3: a resource's / an agent's matches; _forget_all(...)
  236-253: _matching_ids(self, matches) -> tuple[list[str], Exception | None]
  255-271: _scan logs "BF-905: the %s erasure scan failed after finding %d match(es); ..."
  273-304: _forget_all: 275 S4 check; 282 result = await self.forget_episode(episode_id)
  363-371: _delete_attachments
  15 direct methods: __init__, forget_episode, forget_resource, forget_agent_memory, _matching_ids, _scan, _forget_all,
           _archived_episodes, _attachment_ids_for_episode, _delete_attachments, _extract_attachment_ids,
           _normalize_payload, _ids_from_value, _episode_to_dict, _now_iso   (after: _delete_attachments out, _erase_episode in)
Read src/probos/routers/security.py:1-175
  28-29:   from probos.knowledge.erasure import ArchiveCitationsBlockErasure, ErasureManager / ExitNotesBlockErasure
  96-106:  @router.post("/forget") async def request_erasure ... S3 docstring
  129-154: except ExitNotesBlockErasure ... 409; except ArchiveCitationsBlockErasure ... 409
  156-161: return {"deleted_count": result.count, "timestamps": ..., "deleted_episode_ids": ..., "deleted_attachment_ids": ...}
grep -n "async def evict_by_ids|async def _erase_ids" src/probos/cognitive/episodic.py
  3207, 2895: "Every phase ... is attempted; the first failure is raised after the last" (2898-2902)
Read episodic.py:2312-2350   iter_live_episodes: raises EpisodeErasureIncomplete("erasure_live_rows_unrehydratable:<n>") after the scan
Read episodic.py:2352-2393   get_by_ids: per-row try; an unrebuildable row is omitted
Read episodic.py:2984-3026   get_archived_metadata_versions returns [] when the archive failed; iter_archived_episodes raises via _archive_or_none
grep -n "def _archive_or_none" episodic.py   2699-2705: raise EpisodeArchiveUnavailable("episode_archive_unavailable_for_erase")
grep -n "_metadata_to_episode(" episodic.py  no call between 2820 and 3015, so _remove_from_live and _erase_ids rebuild no row (T8's erase)
Read episodic.py:1828-1868   async def seed(self, episodes) -> int (the probe's bulk load)
grep -n "max_episodes" src/probos/config.py  833: max_episodes: int = 100000
grep -n "async def unlink" src/probos/attachments/filesystem_store.py  400: "remove blob + index entry. False when not found."
grep -n "attachment" src/probos/threads/__init__.py  86: pinned_attachment_ids TEXT NOT NULL DEFAULT '[]'
Read tests/test_ad1340_s1_erasure.py:91-118, 296-345, 536-636, 880-927 (R3, R4, R11, R12, R13, the archived versions)
  597: assert _raw(em, [_B1])["ids"] == []  # B1's live row went before its sidecar sweep failed
Read tests/test_bf868_erasure_declared_fields.py:40-132, 395-557   _FakeMetadataOnlyMemory 73-92 has no iter_live_episodes
grep tests/test_bf869_fused_frame_refs.py   48: async def iter_live_episodes;  test_erasure_manager.py 42: same
Read tests/test_bf905_erasure_live_scan.py:1-360   drift helper 204-208; ERROR counts 272, 296; _ListOnlyMemory 94-108
Read tests/test_ad1341_s3_erasure_cascade.py:1-366   _midway 80-83 (cites ep-000); E8 317-338; E9[late] 341-365
Read tests/test_ad1341_s4_exit_note_erasure.py:296-324   raisers == {"knowledge/erasure.py"}; importers == {"routers/security.py"}
grep tests/test_ad1341_s1_archive_store.py   51: def _store(tmp_path); 63: def _record(**overrides)
grep tests/test_ad1341_s1_reset_and_erase.py 162: def _config(tmp_path, ...); 224: def _erase(monkeypatch, config, entry_id, reason, ...)
grep tests/test_ad1340_s2a_lookup_route.py   200-210: _runtime (attachment_store = None); 214: _client; 222: _post
grep tests/test_ad1340_s1_eviction.py        62: _episode(i) "ep-{i:03d}"; 88: _memory(root, mode, *, max_episodes=100)
grep -n "promote_entry(" src                 archive_promotion.py:311 only; promote_ship_records( : __main__.py:3307
Read __main__.py:2987-2998                   "every executing reset holds the AD-816 pidfile `probos serve` takes ... A live owner refuses it."
prompts/ad-1341-s4-lessons-and-stand-down.md:5381  R17: "One read per erasure alone is not enough, because S3's E8 needs the per-episode re-read"
gh issue view 1683 --json title,state        "BF-939: erasing an episode unlinks a content-addressed attachment ...", OPEN
```

**Measured cost (the orchestrator fills this before the build):** <paste the probe's `BF939_COST` lines for 10000 and 100000, base and built tree, with host and date>.

## Absence Verified (2026-10-26)

```
AV1 CLAIM: no HXI, desktop, script or config caller reads /forget or its JSON keys
    RUN:   Grep "security/forget|deleted_attachment|deleted_count|request_erasure" ui/ ; same pattern with forget_episode over {desktop,scripts,docs,config}/**
    FOUND: ui/: none. Elsewhere: docs/development/yeo-gap-reconciliation-2026-05-20.md:67 (prose) only
    HOLDS: yes
AV2 CLAIM: _delete_attachments, _matching_ids and _forget_all have no caller outside erasure.py
    RUN:   Grep "_delete_attachments|_matching_ids|_forget_all|_attachment_ids_for_episode|_extract_attachment_ids|_episode_to_dict" {src,tests}/**/*.py
    FOUND: erasure.py only; tests/test_ad1326_challenger_e2e.py:258 is an unrelated local _matching_ids; diagnostic_context.py has its own _episode_to_dict
    HOLDS: yes
AV3 CLAIM: no code builds ErasureResult or ErasureCascadeIncomplete outside erasure.py
    RUN:   Grep "ErasureResult\(|ErasureCascadeIncomplete\(" {src,tests}/**/*.py
    FOUND: erasure.py:69, :198, :295, :303
    HOLDS: yes
AV4 CLAIM: no fitness or baseline file pins erasure.py's shape (except the 15-method gate)
    RUN:   Grep "erasure" {tests/test_ad1270b*.py,tests/test_layer_boundaries.py,tests/test_ad1343_*.py,docs/development/*.yaml,config/**/*.yaml,scripts/*.py}
    FOUND: docs/development/store-baseline.yaml:124 "archive_erasures" (a table name)
    HOLDS: yes
AV5 CLAIM: no supported actor writes a citing archive entry while /forget runs
    RUN:   Grep "\.promote_entry\(" src ; Grep "promote_ship_records\(" src
    FOUND: archive_promotion.py:311; __main__.py:3307 (probos reset, under the pidfile, :2987-2998)
    HOLDS: yes. That case is reachable only outside ProbOS, so A-3 keeps the check: dropping it is a control change for S5, not for this BF
AV6 CLAIM: no user documentation page covers AD-754 erasure
    RUN:   Grep "(?i)erasure|forget this|/api/security" docs ; Grep "probos archive (erase|veto)" docs
    FOUND: development notes and ledgers only; the second search: none
    HOLDS: yes
AV7 CLAIM: no test compares the whole /forget body
    RUN:   Grep "\.json\(\) == \{|deleted_count|timestamps" tests/test_{ad1340,ad1341,bf905,bf868,erasure}*.py
    FOUND: test_ad1340_s2b_restore_route.py:158 (the restore route); :542 deleted_count == 1 (a key read)
    HOLDS: yes
AV8 CLAIM: no BF row is needed in the roadmap
    RUN:   Read docs/development/roadmap.md:1131-1145
    FOUND: "Open, filed but deliberately not fixed" table only
    HOLDS: yes
```

## Not verified (the orchestrator verifies by running)

1. **The cost probe.** Save the file below as `tests/_bf939_probe_owner_scan_cost.py` in a scratch checkout, so the suite's conftest isolation applies. Never commit it.

   **Commands:**
   ```
   $env:BF939_PROBE_SIZES="10000,100000"
   d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/_bf939_probe_owner_scan_cost.py -n 0 -s -q -p no:cacheprovider
   ```
   Pytest collects a file named on the command line even when it does not match `python_files`; not verified. If it is not collected, rename it `test_bf939_probe_*.py` in the scratch checkout. Run it on the merged base, which uses only base names, and again on the built tree.

   **Expected shape:**
   - Every component is linear in N.
   - On the base: `forget_episode_s` is milliseconds, and `forget_agent_s` is about `live_scan_s + archive_scan_s`.
   - On the built tree: `forget_episode_s` ≈ the base's `forget_episode_s + live_scan_s + archive_scan_s + record_s`, and `forget_agent_s` ≈ the base's `forget_agent_s + record_s`.

   **Acceptable at 100k:** built single-path ≤ 30 s (no worse than a cascade today; S3 R13 called 28.5 s tolerable for a deliberate erasure), and `record_s` ≤ 50% of `live_scan_s + archive_scan_s`.

   **If not acceptable:**
   - *F1, if `record_s` dominates.* An amendment, in scope: the recorder passes `_extract_attachment_ids` a shallow projection of the declared fields (`outcomes`, and `anchors.visual_attachment_ref`) instead of `dataclasses.asdict`. Same fields, no deep copy.
   - *F2, if the store reads dominate.* Disclose the cost in DECISIONS and ship. The bounded owner index (an episode-to-attachment table) is its own AD, filed by the orchestrator with the AD ceiling. It is out of scope here.
   - Above 120 s at 100k, stop and bring the numbers to the Architect before M1.

   **Measured on the merged base (orchestrator, 2026-10-26; the probe on `4f855b90`, whose `erasure.py` equals the merge's).** Linear in N, as expected, and inside the limits:

   | N | live_scan_s | archive_scan_s | record_s | forget_episode_s | forget_agent_s |
   |---|---|---|---|---|---|
   | 10,000 (90% live, 10% archived, 100 name the blob) | 1.20 | 0.03 | 0.16 | 0.02 | 1.11 |
   | 100,000 (1,000 name the blob) | 14.03 | 0.47 | 2.13 | 0.04 | 13.85 |

   Projected for the built tree at 100k: the single path ≈ 0.04 + 14.03 + 0.47 + 2.13 = **16.7 s** (limit 30 s); `record_s` is 2.13 s, **15%** of the two scans (limit 50%), so F1 is not needed. The cascade adds only `record_s`, about 16 s. The built tree's own numbers are measured after M1 (same probe, same sizes) and recorded in DECISIONS. **Run notes:** the repository's `pytest-timeout` is 180 s (`pyproject.toml`), and the 100k seed alone takes longer (5 min 27 s in all), so pass `--timeout 3000`; the file named on the command line is collected as it is, no rename was needed.

   ```python
   """BF-939 (#1683) cost probe, not a test of record: what the attachment-owner scan costs at 10k and 100k episodes.

   Uses only names the base has. Prints one BF939_COST line per size and asserts nothing about time. 90% of the
   episodes are live and 10% archived; 1% name one shared attachment; the attachment store is a counting double.
   """

   from __future__ import annotations

   import dataclasses
   import hashlib
   import os
   import time
   from pathlib import Path

   import pytest

   from probos.knowledge.erasure import ErasureManager
   from probos.types import Episode
   from tests.test_ad1340_s1_eviction import _episode, _memory

   _SIZES = [int(size) for size in os.environ.get("BF939_PROBE_SIZES", "10000").split(",")]
   _SHA = hashlib.sha256(b"bf939 probe: one shared attachment").hexdigest()
   _BATCH = 2000


   class _Unlinks:
       async def unlink(self, attachment_id: str) -> bool:
           return True


   def _episodes(count: int) -> list[Episode]:
       template = _episode(0)
       made: list[Episode] = []
       for i in range(count):
           outcome: dict[str, object] = {"intent": "report", "success": True}
           if i % 100 == 0:
               outcome["attachment_refs"] = [_SHA]
           made.append(dataclasses.replace(
               template, id=f"bf939-{i:06d}", timestamp=template.timestamp + i,
               user_input=f"probe {i}: the section reported coolant loop reading {i}",
               agent_ids=["agent-target"] if i in (100, 200) else ["agent-a"], outcomes=[outcome],
           ))
       return made


   @pytest.mark.parametrize("size", _SIZES)
   async def test_owner_scan_cost(tmp_path: Path, size: int) -> None:
       episodes = _episodes(size)
       async with _memory(tmp_path / "vessel", "archive", max_episodes=size * 2) as rig:
           em = rig.em
           seeded = 0
           for start in range(0, size, _BATCH):
               seeded += await em.seed(episodes[start:start + _BATCH])
           assert seeded == size
           archived = [episode.id for episode in episodes[1::10]]  # 10% archived; none names the attachment
           for start in range(0, len(archived), _BATCH):
               await em.evict_by_ids(archived[start:start + _BATCH], reason="activation_decay")
           manager = ErasureManager(em, _Unlinks(), None)

           started = time.perf_counter()
           live = [episode async for episode in em.iter_live_episodes()]
           live_s = time.perf_counter() - started
           started = time.perf_counter()
           archive = [episode async for episode in em.iter_archived_episodes()]
           archive_s = time.perf_counter() - started
           started = time.perf_counter()
           owners: dict[str, set[str]] = {}
           for episode in live + archive:
               for attachment_id in manager._extract_attachment_ids(manager._episode_to_dict(episode)):
                   owners.setdefault(attachment_id, set()).add(episode.id)
           record_s = time.perf_counter() - started

           started = time.perf_counter()
           single = await manager.forget_episode("bf939-000300")  # names the shared attachment
           single_s = time.perf_counter() - started
           started = time.perf_counter()
           cascade = await manager.forget_agent_memory("agent-target")  # two matches, both naming it
           cascade_s = time.perf_counter() - started

           print(
               f"BF939_COST size={size} live={len(live)} archived={len(archive)} owners={len(owners.get(_SHA, ()))} "
               f"live_scan_s={live_s:.2f} archive_scan_s={archive_s:.2f} record_s={record_s:.2f} "
               f"forget_episode_s={single_s:.2f} forget_agent_s={cascade_s:.2f} "
               f"single_kept={len(getattr(single, 'retained_attachments', {}))} "
               f"cascade_deleted={len(cascade.deleted_episode_ids)}",
               flush=True,
           )
   ```
2. **Expected focused counts** for M1 and M2, on the merged base and on the oracle. *Measured:* M1 390 on the base's existing files and 412 on the oracle; M2 216 and 239 (§4).
3. **`create_app` with a real `FilesystemAttachmentStore` on S2a's `MagicMock` runtime** (the M2 test). S2a sets it to None. If app start-up uses the store, set it after `create_app`; that is a test-only change, and it comes back to the Architect only if the route still sees None. *Measured:* the route test passes as drafted on the oracle (the M2 gate, 239 passed), so the route sees the store.
4. **T8's erase of a row that cannot be rebuilt.** By grep, `_remove_from_live` and `_erase_ids` call no `_metadata_to_episode`. The first M1 run confirms it. *Measured:* T8 passes as drafted on the oracle (the M1 gate, 412 passed).
5. **Whether `tests/conftest.py` forces the network-free embedding** that the probe's 100k seed needs. It is not read here; if the seed is slow, set the offline embedding the suite uses. *Measured:* `tests/conftest.py:45` sets `HF_HUB_OFFLINE=1` and BF-919's guard (`:183-188`) falls back to the suite's embedding: the 10k seed ran in 22 s, the 100k run in 5 min 27 s, nothing was downloaded and the redirected home stayed empty.

## S4 anchors this contract depends on

The orchestrator re-verifies these on the real post-S4 merge. If one changed, the contract returns to the Architect.

**Textual (the SEARCH contains S4's text):**

| Pair | File | S4's text |
|---|---|---|
| 7.1 pair 9 | `src/probos/knowledge/erasure.py` | `        _refuse_while_an_exit_note_cites(self._exit_note_citations, episode_ids)  # AD-1341 S4: a scan's matches, first` (S4 7.11 pair 6) |

**Semantic (this contract calls S4's names or relies on its behaviour):** `_refuse_while_an_exit_note_cites` (`erasure.py:141`), called per match in the new loop; `self._exit_note_citations` (`:169`); X1b and `test_only_the_forget_route_reads_exit_note_citations_and_only_the_manager_refuses_on_them` (`test_ad1341_s4_exit_note_erasure.py:310-323`), both in M1's gate and both unchanged.

**S3 text the SEARCH blocks contain (S3 is already on main):** the archive-check comments in pairs 6 and 7; the S3 docstring in 7.4 pair 1; `tests.test_ad1341_s3_erasure_cascade._midway` (imported by T6).

## 12. Deterministic gate checks, resolved up front

| Check | Result |
|---|---|
| SRP | `ErasureManager` stays at 15 direct methods: `_delete_attachments` moves out and `_erase_episode` comes in. Four new module functions |
| Layer | `erasure.py`'s imports are unchanged (`Callable`, `Mapping` are already imported). `routers/security.py` imports nothing new |
| Phantom precheck | New names: `_recording_owners`, `_last_turns`, `_decide_attachments`, `_unlink_attachments`, `_erase_episode`, `retained_attachments`, `_CountedArchive`, `_vessel`, `_naming`, `_stored`, `_cannot_rebuild`, `_count_scans`. Every other name is verified in §11 |
| Kwarg check | `ErasureManager(memory, attachments, None, archive_store=)` (`erasure.py:156-163`); `_matching_ids(matches, owners, wanted)` is new; `FilesystemAttachmentStore.write(sha, body, mime)` as S3 uses it; `em.evict_by_ids(ids, reason=)` |
| Hidden pins | S4 `raisers`/`importers` (`:321-323`), S3 `_naming("entry_ids_citing") == {"knowledge/erasure.py"}`, `ErasureManager(` built only in `routers/security.py` (S3 `:296-305`). All still hold: no new raise site of `ExitNotesBlockErasure`, no new caller of `entry_ids_citing`, no new builder. bf905's ERROR-message counts (`:272`, `:296`, `:354-358`) hold: the new logs are WARNING and say "BF-939" |
| Unowned tasks | none |
| Store registry and config | no table, `.db` or config field |

## 13. Prior Art and Blind Spots

**Date used for overdue rows:** 2026-10-26. `docs/research/reference-projects.md` has no storage, registry or garbage-collection row (Grep `(?i)storage|registry|backup|restic|git-annex|ipfs|erasure|chroma` matched only unrelated rows). No row was examined or updated.

**Internal:** BF-868 (declared fields; under-erasing is the worse failure) is adopted as D5's tie-break. BF-905 (fail-closed scans; erase what was found, then raise) is adopted for both paths. AD-1340 (unlink, then evict; every archived version is in scope) is kept. S3 D10 and S4 R17 (per-episode citation re-read) are kept by A-3. `docs/research/` holds no study on attachment storage.

**External:**
- **Docker registry garbage collection** is mark-and-sweep over content-addressed blobs. The mark phase gathers every digest any manifest references; the sweep deletes only unreferenced blobs. A layer stays while another manifest references it, and the registry should be read-only during GC, because an upload mid-run can lose a needed blob. Adopted: the owner scan is the mark, restricted to the request's attachments, with no counts. The concurrent-writer caveat is register G2. <https://docker-docs.uclv.cu/registry/garbage-collection>, <https://handbook.gitlab.com/handbook/engineering/architecture/design-documents/container_registry_metadata_database>
- **Deduplicated backup storage** erases an item by removing only the chunks no other item references. Systems without reference counts scan every manifest instead, because maintaining counts is expensive. Adopted: the scan. Rejected for this BF: a reference count or index, which needs a schema and a migration; deferred as F2's AD. <https://patents.google.com/patent/US11455279>, <https://patents.google.com/patent/US8874532>
- No GDPR guidance was found on whether shared deduplicated bytes must go with one subject's erasure. That is not needed here: the bytes stay only for another, unerased episode's record.

**Blind spots found:**
1. A match refused mid-cascade sharing a blob (T6). The decision's mutant 2 is reframed as "count a refused match as erased" (E-2).
2. A failed evict that has already removed records (A-1, T7).
3. An unrebuildable own row made unerasable by failing closed (A-2, T8).
4. A fold-in that would have changed S3's refusal (A-3).
5. A concurrent `store()` naming the blob between the scan and the unlink (G2).
6. Owners outside episodic memory (G1).
7. A 500 that hides `retained_attachment_ids` (G3).
8. The single path's new latency (D8, §11).
9. Doubles without `iter_live_episodes` (7.2).

## 14. Diff Reviewer: properties to verify

1. An attachment is passed to `unlink` only when no episode outside the request, and no request member left whole, is recorded as naming it. "Left whole" means refused, or failed before its erase began.
2. Owners are keyed by episode id. An episode's own live and archived versions never keep its attachments, and every archived version of another episode does.
3. The single path scans live and archived episodes at most once, and only when the episode declares an attachment and an attachment store is wired. A cascade scans each store exactly once, and records owners in that same pass.
4. In a cascade, each attachment is decided at most once, in the turn of the last match the scan saw naming it, and before that match's evict.
5. The single path calls `_erase_episode` and nothing else destructive. The cascade's per-match order is: S3's archive check, S4's exit-note check, the attachment read, the decision, then `_erase_episode`. That is the order `forget_episode` had before BF-939.
6. AD-1340's order holds inside `_erase_episode`: unlink, then evict, then `mark_deleted` only after the evict returns. An erase error propagates as its original type.
7. On a scan error: an attachment is kept only for a reached owner, the erasure proceeds, and the error is raised. On the single path that is `ErasureCascadeIncomplete(result, {}, scan_error)` after the erase, unless the erase raised first. No path swallows a scan error.
8. `ErasureResult.retained_attachments` holds only attachments not unlinked, each with sorted, non-empty holders. No attachment is in both `deleted_attachment_ids` and `retained_attachments` of one result. `count` is unchanged in meaning.
9. `ErasureManager` has 15 direct methods. `_delete_attachments` has no remaining reference.
10. The route adds exactly one key, `retained_attachment_ids`, and changes no other key, status or refusal body.
11. The new tests use the real memory, attachment store, manager, archive, CLI erase and app route. The only stand-ins are BF-905's schema drift, R12's participant-index fault, and the counting wrappers. Every store lies under `tmp_path`.

## 15. Acceptance criteria

1. Erasing an episode through any entry point keeps an attachment another live or archived episode still names, and reports it with those episodes (T1, T2, route test; E-1, E-8, E-9, E-17, R-1).
2. An attachment goes when the last episode naming it is erased, in one request or across several (T3, T4, T5; E-3).
3. A match refused by S3 or S4 keeps what it shares, and the retry removes it. A match whose erase began never strands a file (T6, T7; E-2, E-4 to E-7, E-14).
4. A failed owner scan never blocks an erasure and is always raised (T8 to T10; E-11, E-12).
5. Each entry point scans for owners at most once. S3's per-episode citation check is unchanged (T11; E-10, E-13).
6. S3's and S4's refusals, BF-868's extraction and AD-1340's order and retention pass their own tests unedited (M1 gate).
7. Every §10 row is killed by the named test. One broad gate and one PR; cross-family review of M1 and M2.
8. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## For the register (#1523)

**G1.** Owners outside episodic memory are not checked: project pins (`threads/__init__.py:86`), chat, work items and artifacts. An erasure unlinks an attachment only they hold, as before BF-939. A full owner check needs every holder to publish its references.

**G2.** A `store()` of a new episode naming the same attachment, between the owner scan and the unlink, loses its bytes, as before BF-939. Closing that needs the decision and the unlink under the store write lock, or a re-check. Docker's registry GC requires a read-only registry for the same reason.

**G3.** `/forget` answers 500 with no body for `ErasureCascadeIncomplete` (BF-905 D6). From BF-939 the single path can raise it after a successful erase, so the Captain does not see that request's `retained_attachment_ids`. A typed 5xx body was deferred by BF-905 and stays deferred.

**G4.** When the match that decides a shared attachment fails before its erase, this request decides nothing for that attachment. It stays, held by that match, and the retry decides it.

**G5.** The single path's cost is one full live and archive scan when the episode names an attachment (§11). A bounded owner index is its own AD if F2 applies.

**G6.** S4 R17 (S3 R13's per-episode citation read) stays S5's (A-3).
