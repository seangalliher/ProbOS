# Ward Room identity keys: an agent id finds its department, and the cascade check meets episode owners in their own key -- #1792, #1793, one batch

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-14
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-14: the orchestrator's oracle findings F1 to F3 (C2a-1's complete list; the `extra` search narrowed to what it finds; P2a-7, the pinned field count).
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-16: review round 1, finding F1 (section 13, Amendment A1).
**File in the repository:** `prompts/bf-962-963-ward-room-identity-keys.md`. No commit subject or tracker line in this batch carries an `AD-` or `BF-` token or this file's name (section 5).
**Status:** ready to build on `origin/main` once #1794 and batches 1 to 3 have merged. Read on `5275d008`. None of those batches edits the source or test files below. Only the trackers move, and their anchors are text, not line numbers (M3).
**Dependencies:** none in code. **Numbers:** #1792 is BF-962 and #1793 is BF-963 (`gh issue view`). Nothing is allocated here. The AD ceiling is AD-1359 (`scripts/ad_ceiling.py`, all three sources) and is stated for the record only.
**Builder:** `claude-sonnet-5.5`. At most about 150 tool calls per milestone. Focused tests only. Search first, then read the range. **Diff Reviewer:** `gpt-6.1-sol` (section 9).
**Estimated tests (expected, not measured):** one new file, `tests/test_ward_room_identity_keys.py`, with 13 cases: 10 strict xfail at M1 and 3 controls. Two existing files are edited in M2a, each with its reason inline: `tests/test_ad1270e2f_knowledge_models.py` (the default dump golden, P2a-5) and `tests/test_ad1270e1_config_facade.py` (the pinned field count, P2a-7). No test function is removed.

**Base blobs (`5275d008`).**

| File | Blob | Role |
|---|---|---|
| `src/probos/substrate/identity.py` | `ebb299ab5cc6cd98caa4db0a9a2e20d2a7bd12bc` | edited (M2a) |
| `src/probos/ward_room/_helpers.py` | `85f0cc8e8b14f0979e8b0738065c50f81a117cc3` | edited (M2a, M2b) |
| `src/probos/config_models/knowledge.py` | `2b4ac73c64c409f390c93fa99d68bd43fd82a584` | edited (M2a) |
| `config/system.yaml` | `f31da6e4e895d759c6401efd9725040dc6f765b6` | edited (M2a) |
| `tests/test_ad1270e2f_knowledge_models.py` | `4d9381a5df4c221c7400214ca7b1ac163c12a1c5` | edited (M2a) |
| `tests/test_ad1270e1_config_facade.py` | `578c020cac9fbf6ae56e3c19f8a9bb0af5186685` | edited (M2a, P2a-7) |
| `docs/development/config-facade-baseline.yaml`, `docs/development/config-reference.md` | `7a53ac74...`, `4fb3f64e...` | regenerated (M2a, C2a-1, C2a-2) |
| `src/probos/cognitive/social_verification.py` | `5cc257142790931ef5d2f8e12617c2ba37502ad8` | edited (M2b) |
| `src/probos/ward_room/threads.py` | `148aa8bab39fa66c812cdf3300b23650833f1526` | edited (M2b) |
| `src/probos/ward_room/messages.py` | `d63c3c8621a9d7e26635f669443d2c142ce3dfeb` | edited (M2b) |
| `PROGRESS.md`, `DECISIONS.md` | move with the earlier batches | anchors in M3 |

## 1. Problem (re-derived on `5275d008`)

| Issue | Evidence | Verdict |
|---|---|---|
| #1792: department lookup by type, given an id | `ward_room/_helpers.py:11-17` (`get_department(author_id) or ""`); `cognitive/standing_orders.py:78-80` (`_AGENT_DEPARTMENTS.get(agent_type)`) | Holds |
| #1792: the callers | `threads.py:607`, `:657`; `messages.py:364`, `:415` (through the static `_resolve_author_department`, `threads.py:233-236`, `messages.py:151-154`); `cognitive/thread_priority/service.py:119`, `:132` | Holds |
| #1792: `populate_ward_room_department` has no reader | the absence search in section 11 | Holds |
| #1793: membership by raw id | `social_verification.py:548-551`, `:568-571` | Holds |
| #1793: the owner key | `threads.py:579`, `:628`; `messages.py:329`, `:386`; `episodic.py:474-485` | Holds |
| #1793: the same global `recall(post_body, k=3)` for every peer | `social_verification.py:548` inside `for match in peer_matches` (`:538`); `:568` | Holds; decided in D2 |
| #1793 scope addition: a reply episode stores the channel NAME | `messages.py:359`, `:411` (`channel_id=channel_name`); the thread episode stores the id at `threads.py:602`, `:653`. The channel id in scope is `thread_channel_id` (`messages.py:177`, used at `:319`) | Holds |
| Ward Room ids are uuid4 | `ward_room/channels.py:103`, `:114`, `:212`, `:270` | Holds |

## 2. Solution and decisions

- **M2a (#1792).**
  - New `substrate/identity.agent_type_of(value) -> str`. It returns the agent type a deterministic id names, or `""`. It tries `parse_agent_id`'s module registry first, then the hash-verified split. The best-effort prefix (`identity.py:99-105`, pool `""`) is not trusted, and a non-str value gives `""`.
  - `resolve_author_department` returns `get_department(value) or get_department(agent_type_of(value)) or ""`. The value is tried as given first, so a bare type and the keys `captain` and `system` behave as before. It never raises.
  - Thread priority takes the repair through the same helper (`service.py:119`, `:132`), so its file is not edited.
  - The resolver lives in `substrate`, the lowest layer, so the dream's site (#1523 F-491) and capability triage (#1419) can share it in their own slices.
- **D1: remove `populate_ward_room_department`.**
  - **Evidence.** Nothing reads it (section 11). Removing it keeps behaviour, and a config that still sets the key loads: neither `OrientationConfig` nor `SystemConfig` sets `model_config`, so Pydantic's default `extra="ignore"` drops the key. The only models in `config.py` and `config_models/` that set `extra` are `CommandPolicyRule` and `CommandPolicyConfig` (`config_models/operations.py:166`, `:215`, `extra="forbid"`), which sit under `execution.command_policy` (`operations.py:397`), off this key's load path (search in section 11). The new case `test_the_unread_orientation_flag_is_gone_and_a_config_that_sets_it_still_loads` pins the load.
  - **What a removal moves:**
    - the model line and the tracked yaml key;
    - the facade baseline: OrientationConfig's `fields` line; the `schema_sha256` of OrientationConfig and of SystemConfig, the one model whose schema embeds it; `surface_counts.canonical_dump_leaves` and `surface_counts.field_definitions`, each down by one; and `canonical_dump_sha256` (C2a-1);
    - the generated config reference row;
    - one golden line in `test_ad1270e2f_knowledge_models.py:198`;
    - the pinned field count in `test_ad1270e1_config_facade.py:1571` (1886 -> 1885, P2a-7).
  - **What it does not move:**
    - the AD-1185 profile census (`test_ad1185_config_profiles.py` names no orientation field, and the default is True);
    - the profiles (`config/profiles/*.yaml` do not name it);
    - BF-926's report: the yaml key goes with the field, so no orphan key is left.
  - **A reader was rejected.** The Ward Room receives no config (`WardRoomService.__init__`, `service.py:52-61`). A reader would add a constructor parameter through `service.py`, `threads.py`, `messages.py` and `startup/communication.py`, and a new False path that empties the anchor this batch repairs.
  - This follows BF-926's precedent for a removed flag (`test_bf926_config_readers.py:152-161`).
- **M2b (#1793).**
  - **Both keys.** `check_cascade_risk` takes `identity_registry` as a keyword with default `None`. Each author id, the post's and each peer's, is matched against an episode's owners in both forms: as given, and as `resolve_sovereign_id_from_slot(id, identity_registry)`.
    - The Ward Room hands the check the registry it stores episodes with (`threads.py:164`, `messages.py:38`), through `check_and_alert_cascade_risk`.
    - The raw id is kept because a fan-out episode (`routers/thread_fanout.py:1115`) and an episode stored before a certificate carry the slot id until BF-103's migration runs.
    - With no registry, the behaviour is today's.
  - **The reply channel id.** A reply episode and its peer-repetition episode store `thread_channel_id`, the channel's id.
  - **Thresholds.** `social_verification.py:592-601` is unchanged.
- **D2: the global `recall(post_body, k=3)` cannot hold every peer's matching episode.**
  - It answers the same top three for every peer. A post can carry up to 40 matched rows (two `LIMIT 20` queries, `threads.py:45`, `:65`), and the risk rule calls 3 peers high (`:596`). So even at three peers plus the author, four owners compete for three slots, and other agents' episodes also compete.
  - Decision (as repaired by Amendment A1, section 13): the pool is the base's `recall(post_body, k=3)`, then, when there is more than one distinct author id, each episode of one recall with `k = 3 * (distinct author ids, the post's included)`, bounded at 123, whose id the first does not hold. A wider recall need not hold a narrower one's episodes: with hybrid recall on (`config/system.yaml:137`), `_fuse_dense_sparse` fuses a dense top `k` and a sparse top `3 * k` and cuts to `k` (`episodic.py:3597-3635`); with composite reranking on (off by default, `config.py:980`), the candidate window is `10 * k` (`episodic.py:3494`). The union holds every episode the base's recall held. Each peer's episodes are then taken from that pool by both keys. Duplicates stay exactly as today (L5).
  - Test: case `mc`, at the production bound of 40 peers, with 3 other agents' episodes stored first; case `mh`, a hybrid-shaped recall whose recall of 12 drops an episode its recall of 3 holds; case `mi`, an episode both recalls hold counts once.
  - Rejected: `recall_for_agent` once per peer. Its relaxed threshold (`episodic.py:3959`) changes what counts as a match, and every cascade test double implements only `recall` (`test_bf920...:60`, `test_social_verification.py:69`, `test_bf921...:243`).
- **Scope-addition transition rule: departed from.** The issue comment asked the comparison to accept the stored name form.
  - What that rule protects is a pair of a stored (pre-change) reply episode and a thread episode of the same channel, in different threads, less than 60 s apart (`:132`).
  - Either both episodes predate the change (today's scoring of history, unchanged) or a restart shorter than 60 s separates them.
  - A form rule would also move the other consumers of `compute_anchor_independence`: `dreaming.py:1179`, `:1422`, `records_store.py:1440` and `behavioral_metrics.py:600`.
  - Rewriting stored episodes is a backfill, which #1792 keeps out of scope. Recorded as L3.
- **D3 (replay).**
  - **Built and verified here:** every code item; the production-wired tests (certificated and not, a promotion request, reply episodes); the recall decision; the report statement.
  - **Waits for the Captain:** the replay counts. The only action needed is a copy of `ward_room.db`, the episodic store directory and `identity.db` from `%LOCALAPPDATA%\ProbOS\data`.
  - The read-only replay script is not built in this batch. It cannot be verified without a copy whose layout (a ChromaDB directory) is known. It becomes a follow-up slice once the copy exists.
  - #1793 stays open after the merge, with the replay as its only unchecked item, as for BF-964.
- **D4 (rollout).**
  - No new default, flag or staged rollout. The detector already has an off switch, `social_verification.cascade_enabled` (`system.yaml:1954`, read at `social_verification.py:526`).
  - Its Bridge alert is de-duplicated for 300 s per source and affected set and can be muted (`bridge_alerts.py:73`, `:102-111`, `:860-862`). The thresholds do not change.
  - The change strengthens a control, can be reverted, and meets none of the "Still requires the Captain" conditions. The report tells the Captain what can now fire (L7).
- **Rejected or deferred:**
  - `identity_service.IdentityService.resolve` as the resolver. It does give an `agent_type`, but the static Ward Room helper and thread priority hold no instance. It is the candidate for the F-491 and #1419 slices.
  - Removing the two readerless siblings, `populate_watch_section` and `populate_event_log_window`: considered, deferred (BF-925 R6).

## 3. Milestones and gates

`PY` = `d:/ProbOS/.venv/Scripts/python.exe`, run from the repository root, always with `-n 0 -p no:randomly`.

- **M0:** record the `--collect-only -q` counts for every existing file named in G2a and G2b.
- **G1 (M1):** `PY -m pytest tests/test_ward_room_identity_keys.py -q -n 0 -p no:randomly`.
  - Expected (not measured): **3 passed, 10 xfailed**.
  - Then set `$env:WARD_ROOM_IDENTITY_KEYS_RUNXFAIL = "1"`, run the file alone, and `Remove-Item Env:WARD_ROOM_IDENTITY_KEYS_RUNXFAIL`. Each of the 10 must fail at its own `assert`, none at an import, fixture or call. An XPASS is a FAIL.
- **G2a (M2a):**
  - Run C2a-1 and C2a-2, then: the new file, `tests/test_ad641c_thread_priority.py`, `tests/test_orientation.py`, `tests/test_standing_orders.py`, `tests/test_ad910_yeoman_standing_orders.py`, `tests/test_ad1270e2f_knowledge_models.py`, `tests/test_ad1270e1_config_facade.py`, `tests/test_ad1270e2_config_models.py`, `tests/test_config_reference_current.py`, `tests/test_bf926_config_readers.py`, `tests/test_ad1185_config_profiles.py`, `tests/test_config.py`, `tests/test_layer_boundaries.py`, `tests/test_promotion_post_identity.py` and `tests/test_ward_room.py`.
  - Expected: the new file has **4 xfailed, 9 passed**. Every other file has 0 failed and its M0 count (the 14 files' M0 total is 851 on the scratch tree, so 851 passed). Without P2a-7, `test_ad1270e1_config_facade.py::test_committed_baseline_records_the_measured_surface` fails at `:1571` (`assert 1885 == 1886`); with it, the file passes.
- **G2b (M2b):**
  - The new file, `tests/test_social_verification.py`, `tests/test_bf920_cross_agent_verification.py`, `tests/test_bf921_counselor_event_delivery.py`, `tests/test_bf103_episode_id_mismatch.py`, `tests/test_ward_room.py`, `tests/test_ad663_provenance_producers.py`, `tests/test_ad1346_admission_store_census.py`, `tests/test_bf925_guard_names.py`, `tests/test_ad1346_identity_service.py` and `tests/test_layer_boundaries.py`.
  - Then `PY -P scripts/check_architecture_principles.py --check`.
  - Expected: the new file has **13 passed, 0 xfailed** at M2b and **15 passed** after R1 (section 13); everything else is clean.
- **G3 (M3):** `PY -P scripts/gen_ad_ledger.py`, then `PY -P scripts/gen_ad_ledger.py --check`, then `PY -m pytest tests/test_ad1184_ad_ledger.py -q -n 0`. No AD or BF number moves. A changed number row is a hard stop.

**Orchestrator:** the oracle (every SEARCH applies exactly once, in label order), the mutation campaign (section 7), then once: `PY scripts/run_test_gate.py --label ward-room-identity-keys --receipt logs/gates/ward-room-identity-keys.receipt.json`.

**Harness rule.** No source change to make a test pass, no new skip, no loosened assertion. If a count differs, or a regenerated file changes more than C2a-1 or C2a-2 allows, stop and report to the Architect.

**Consumer search (run 2026-11-14 on `5275d008`; Grep over `tests/`, including `tests/fixtures/`).**

| Search | Hits that matter | Action |
|---|---|---|
| `resolve_author_department`, `_resolve_author_department`, `participant_departments` | `test_ad641c_thread_priority.py:354` (patches the helper by name), `:389-390`; `test_orientation.py:285` (patches the static method) | Names kept; in G2a |
| `get_department(`, `_AGENT_DEPARTMENTS` | `test_standing_orders.py:137-154`, `test_ad910...:55-64`, `test_ad521...:170`, `test_science_team.py:374-386`, `test_ad429e...:93-171` | Table and function untouched; two of them in G2a |
| `populate_ward_room_department` | `test_ad1270e2f_knowledge_models.py:198` (default dump golden; also reads the baseline at `:369-378`) | P2a-5; in G2a with the facade, reference and reader checks |
| `\b(1886\|1896\|1885\|1895)\b`, `field_definitions`, `canonical_dump_leaves`, `canonical_dump_sha256`, the base digests `5658987a`, `25d606ac`, `a20888ca` (also over `scripts/` and `src/`) | `test_ad1270e1_config_facade.py:1571` (`field_definitions == 1886`; comments `:1549`, `:1570`). `:252` and `:1180` compute the digest and pin no value. `test_ad1270e2f...:474` (OrientationConfig bounds 0) is unaffected. None in `scripts/` or `src/` | P2a-7; in G2a |
| `parse_agent_id`, `get_agent_department`, `substrate.identity` imports, `rglob("*.py")` scanners (62 files; the identity, layer, guard and census ones read) | `test_layer_boundaries.py` (substrate imports nothing new; `ward_room` is unranked, `:16-27`); `test_ad1346_identity_service.py:463-500` (censuses `IdentityRef` only) | No edit; in G2a or G2b |
| `check_cascade_risk`, `check_and_alert_cascade_risk`, `SocialVerificationService`, `recall` doubles, `side_effect` | three files: real service, `recall` returns all or `[:k]`; `assert_not_awaited` at `test_bf920...:269` (disabled path, returns first) | No edit; arithmetic for BF-921's three cases in section 6 (L5) |
| `resolve_sovereign_id_from_slot`, `identity_registry` | `test_bf103_episode_id_mismatch.py:103-360` (signature presence), `test_bf138...:16` | No edit; in G2b |
| `anchors.channel_id`, `ward_room_reply` | `src` only: `anchor_quality.py:47`; tests: none on a stored reply. `test_ad663_provenance_producers.py:22-34` builds its own reply anchor (`channel_id="science"`) and asserts nothing about it | No edit; in G2b |
| `anchors.department`, `anchor_department` | `test_ad567a:282`, `test_ad582:482-498`, `test_anchor_indexed_recall.py:327`: no Ward Room author id | No edit |
| Ward Room store census | `fixtures/ad1346_store_census.py:200-252` keys write methods; no method is added | In G2b |

## 4. The contract

The SEARCH text is LF and ASCII. It starts at a line start and matches exactly once in its file, once the earlier blocks for that file have been applied in label order. The non-ASCII lines of the edited sources are `identity.py:5`, `:99`, `social_verification.py:35`, `:285`, `:607` and `messages.py:344`; all lie outside every SEARCH.

### M1

**N1-1.** New file `tests/test_ward_room_identity_keys.py`. It imports only names that exist on the base; `agent_type_of` is read with `getattr`.

```python
"""Ward Room identity keys: an agent id finds its department; the cascade check meets episode owners in their own key.

#1792: resolve_author_department finds the department of an agent given its id ({type}_{pool}_{index}_{hash8}), not
only of a bare type, so a Ward Room episode an agent writes carries its department anchor.
#1793: the cascade check matches a post's author and its peers to episodes under both ids the Ward Room stores them
under (the slot id, and the certificate id the identity registry maps it to), with one recall large enough for every
peer; a reply episode stores the channel's id, as a thread episode does.

The real WardRoomService runs on a temporary database with a real AgentIdentityRegistry and an episodic store double
that records what it is given and answers ``recall`` with the first ``k`` stored episodes (the real cap, no ranking).
Synthetic fixtures only. A case marked ``until_built("#N")`` fails on the base at its own assert; the milestone that
builds #N adds it to ``_BUILT``. ``WARD_ROOM_IDENTITY_KEYS_RUNXFAIL=1`` runs every case plainly.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, AsyncIterator

import pytest
import pytest_asyncio

import probos.substrate.identity as substrate_identity
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.cognitive.social_verification import SocialVerificationService
from probos.cognitive.thread_priority.scorer import ThreadPriorityScorer
from probos.cognitive.thread_priority.service import ThreadPriorityService
from probos.config import OrientationConfig, SocialVerificationConfig, SystemConfig
from probos.events import EventType
from probos.identity import AgentIdentityRegistry
from probos.substrate.identity import generate_agent_id
from probos.types import AnchorFrame, Episode
from probos.ward_room import WardRoomService
from probos.ward_room._helpers import resolve_author_department

_BUILT: frozenset[str] = frozenset()


def until_built(issue: str) -> Any:
    """Strict xfail at an assert until *issue*'s milestone adds it to ``_BUILT``."""
    if issue in _BUILT or os.environ.get("WARD_ROOM_IDENTITY_KEYS_RUNXFAIL") == "1":
        return lambda func: func
    return pytest.mark.xfail(raises=AssertionError, strict=True)


_SHIP = "wr-keys-ship"
_PROCEDURE_ID = "wr-keys-procedure"
_PROMOTION = {
    "eligible": True,
    "criticality": "low",
    "procedure_name": "wr-keys-procedure",
    "procedure_description": "A synthetic procedure.",
    "compilation_level": 4,
    "intent_types": ["synthetic_intent"],
    "quality_metrics": {"effective_rate": 0.9, "total_completions": 12},
}
#: (slot id, agent type, callsign); production-shaped ids from substrate/identity.generate_agent_id.
_BUILDER = (generate_agent_id("builder", "builder", 0), "builder", "Forge")
_SURGEON = (generate_agent_id("surgeon", "surgeon", 0), "surgeon", "Lance")
_PEERS = [
    (generate_agent_id("scout", "scout", 0), "scout", "Wren"),
    (generate_agent_id("architect", "architect", 0), "architect", "Quill"),
    (generate_agent_id("pathologist", "pathologist", 0), "pathologist", "Marrow"),
]
_ECHO = "I agree we should review the onboarding checklist together before the next watch begins"
_STATUS = "Routine status from the medical bay: supplies counted, rota posted"
#: The most rows one post's peer check returns: two queries of LIMIT 20 (ward_room/threads.py check_peer_similarity).
_MAX_PEERS = 40


class _Episodes:
    """The store the Ward Room writes to and the cascade check reads: what it is given, in order."""

    def __init__(self, first: list[Episode] | None = None) -> None:
        self.stored: list[Episode] = list(first or [])

    async def store(self, episode: Episode) -> None:
        self.stored.append(episode)

    async def recall(self, query: str, k: int = 5) -> list[Episode]:
        return self.stored[:k]


@pytest_asyncio.fixture
async def registry(tmp_path: Path) -> AsyncIterator[AgentIdentityRegistry]:
    """A real identity registry, started and commissioned as tests/test_ad1196_did_key_binding.py does."""
    reg = AgentIdentityRegistry(data_dir=tmp_path / "identity")
    try:
        await reg.start()
        await reg.start(instance_id=_SHIP, vessel_name="Wr-keys-ship", version="1")
        yield reg
    finally:
        await reg.stop()


async def _certify(reg: AgentIdentityRegistry, agents: list[tuple[str, str, str]]) -> None:
    for slot, agent_type, callsign in agents:
        cert = await reg.issue_birth_certificate(
            agent_type=agent_type, callsign=callsign, instance_id=_SHIP, vessel_name="Wr-keys-ship",
            department="", post_id=f"post-{callsign}", baseline_version="v1", slot_id=slot,
        )
        assert reg.get_by_slot(slot) is cert and cert.agent_uuid != slot  # premise: the slot maps to a certificate id


@contextlib.asynccontextmanager
async def _room(directory: Path, episodes: _Episodes, registry: Any, verification: Any = None) -> AsyncIterator[WardRoomService]:
    directory.mkdir(parents=True, exist_ok=True)
    room = WardRoomService(db_path=str(directory / "ward_room.db"), episodic_memory=episodes, identity_registry=registry)
    await room.start()
    try:
        if verification is not None:
            room.set_social_verification(verification)
        yield room
    finally:
        await room.stop()


async def _all_hands(room: WardRoomService) -> Any:
    return next(channel for channel in await room.list_channels() if channel.name == "All Hands")


class _Builder(CognitiveAgent):
    """A real agent of a type with a department entry (builder -> engineering)."""

    agent_type = "builder"
    instructions = "Synthetic instructions."


async def _promote(room: WardRoomService) -> Any:
    """A real promotion request (CognitiveAgent._announce_promotion_request) by the builder; its All Hands thread."""
    runtime = SimpleNamespace(ward_room=room, ontology=None, trust_network=None, procedure_store=None)
    agent = _Builder(pool="builder", agent_id=_BUILDER[0], runtime=runtime)
    agent.callsign = _BUILDER[2]
    await agent._announce_promotion_request(_PROCEDURE_ID, _PROMOTION)
    channel = await _all_hands(room)
    posted = [t for t in await room.list_threads(channel.id) if t.title.startswith("[Promotion Request]")]
    assert [t.author_id for t in posted] == [_BUILDER[0]]  # premise: posted under the agent's id
    return posted[0]


def _episodes_of(episodes: _Episodes, thread_id: str, trigger_type: str) -> list[Episode]:
    return [
        ep for ep in episodes.stored
        if ep.anchors is not None and ep.anchors.thread_id == thread_id and ep.anchors.trigger_type == trigger_type
    ]


def _cascade_service(episodes: _Episodes) -> tuple[SocialVerificationService, list[str]]:
    """The service startup builds (default config), with an emitter recording each cascade event's risk."""
    risks: list[str] = []

    def emit(event_type: str, data: dict) -> None:
        if event_type == EventType.CASCADE_CONFABULATION_DETECTED.value:
            risks.append(data["risk_level"])

    return SocialVerificationService(episodes, SocialVerificationConfig(), emit_event_fn=emit), risks


async def _thread_echo(tmp_path: Path, registry: AgentIdentityRegistry, *, certify: str) -> list[str]:
    """Three peers post the promotion request's body as threads in All Hands; then the builder posts the request.

    certify: "before" issues every certificate before the first post; "after" between the peers' posts and the
    request (their episodes keep the slot id, as before BF-103's migration); "never" issues none."""
    async with _room(tmp_path / "scratch", _Episodes(), None) as scratch:
        body = (await _promote(scratch)).body
    episodes = _Episodes()
    service, risks = _cascade_service(episodes)
    everyone = [*_PEERS, _BUILDER]
    async with _room(tmp_path / "room", episodes, registry, service) as room:
        if certify == "before":
            await _certify(registry, everyone)
        channel = await _all_hands(room)
        for index, (slot, _agent_type, callsign) in enumerate(_PEERS):
            await room.create_thread(
                channel_id=channel.id, author_id=slot, title=f"Echo {index}", body=body, author_callsign=callsign,
            )
        if certify == "after":
            await _certify(registry, everyone)
        await _promote(room)
    return risks


async def _reply_echo(tmp_path: Path, registry: AgentIdentityRegistry) -> tuple[list[str], _Episodes, str, str]:
    """Certificated agents. The surgeon opens a status thread; a peer posts the echo as a thread; two peers and the
    builder post it as replies in the status thread. Returns the risks, the store, the channel id and the thread id."""
    episodes = _Episodes()
    service, risks = _cascade_service(episodes)
    async with _room(tmp_path / "room", episodes, registry, service) as room:
        await _certify(registry, [*_PEERS, _BUILDER, _SURGEON])
        channel = await _all_hands(room)
        status = await room.create_thread(
            channel_id=channel.id, author_id=_SURGEON[0], title="Watch status", body=_STATUS,
            author_callsign=_SURGEON[2],
        )
        first, *rest = _PEERS
        await room.create_thread(
            channel_id=channel.id, author_id=first[0], title="Echo", body=_ECHO, author_callsign=first[2],
        )
        for slot, _agent_type, callsign in [*rest, _BUILDER]:
            await room.create_post(thread_id=status.id, author_id=slot, body=_ECHO, author_callsign=callsign)
    return risks, episodes, channel.id, status.id


def _restored_id(agent_type: str, pool: str, index: int) -> str:
    """A production-shaped id built by hand, as one read back from storage: not from generate_agent_id."""
    digest = hashlib.sha256(f"{agent_type}:{pool}:{index}".encode()).hexdigest()[:8]
    return f"{agent_type}_{pool}_{index}_{digest}"


def _owned(owner: str, thread_id: str, department: str) -> Episode:
    return Episode(
        user_input=f"[Ward Room] All Hands: {thread_id}", timestamp=1000.0, agent_ids=[owner], source="direct",
        anchors=AnchorFrame(
            channel="ward_room", channel_id="all-hands-id", thread_id=thread_id, trigger_type="ward_room_post",
            department=department, source_origin_id=f"wr-thread:{thread_id}",
        ),
    )


# --- #1792 -----------------------------------------------------------------------------------------------------


@until_built("#1792")
def test_r1_a_production_id_resolves_to_its_types_department() -> None:
    assert resolve_author_department(_BUILDER[0]) == "engineering"
    assert resolve_author_department(_restored_id("code_reviewer", "code_reviewer", 3)) == "engineering"
    assert resolve_author_department(_restored_id("research_specialist", "science-pool", 1)) == "science"


@until_built("#1792")
def test_r3_r4_agent_type_of_names_a_type_only_for_a_verified_id() -> None:
    agent_type_of = getattr(substrate_identity, "agent_type_of", None)
    assert callable(agent_type_of)
    assert agent_type_of(_BUILDER[0]) == "builder"
    assert agent_type_of(_restored_id("code_reviewer", "code_reviewer", 3)) == "code_reviewer"
    assert agent_type_of("red_team_0_deadbeef") == ""  # its hash matches no split: the prefix is not a type
    assert agent_type_of("builder") == ""
    assert agent_type_of("") == ""
    assert agent_type_of(None) == ""  # type: ignore[arg-type]


def test_r2_r3_a_bare_type_a_key_and_an_unknown_value_behave_as_before() -> None:
    assert resolve_author_department("builder") == "engineering"
    assert resolve_author_department("surgeon") == "medical"
    for value in ("captain", "system", "", "red_team_0_deadbeef", "nobody_nobody_0_00000000", None):
        assert resolve_author_department(value) == ""  # type: ignore[arg-type]


@until_built("#1792")
@pytest.mark.asyncio
async def test_r1_thread_and_reply_episodes_carry_their_authors_departments(tmp_path: Path, registry) -> None:
    _risks, episodes, _channel_id, status_id = await _reply_echo(tmp_path, registry)
    threads = _episodes_of(episodes, status_id, "ward_room_post")
    replies = {ep.anchors.trigger_agent: ep.anchors.department for ep in _episodes_of(episodes, status_id, "ward_room_reply")}
    assert [ep.anchors.department for ep in threads] == ["medical"]
    assert replies == {"Quill": "science", "Marrow": "medical", "Forge": "engineering"}


@until_built("#1792")
@pytest.mark.asyncio
async def test_r1_a_promotion_request_episode_carries_its_agents_department(tmp_path: Path, registry) -> None:
    episodes = _Episodes()
    async with _room(tmp_path / "room", episodes, registry) as room:
        await _certify(registry, [_BUILDER])
        thread = await _promote(room)
    stored = _episodes_of(episodes, thread.id, "ward_room_post")
    assert len(stored) == 1  # premise
    assert stored[0].anchors.department == "engineering"


@until_built("#1792")
@pytest.mark.asyncio
async def test_r1_thread_priority_reads_the_departments_of_production_shaped_authors(tmp_path: Path, registry) -> None:
    async with _room(tmp_path / "room", _Episodes(), registry) as room:
        channel = await _all_hands(room)
        thread = await room.create_thread(
            channel_id=channel.id, author_id=_SURGEON[0], title="Priorities", body=_STATUS, author_callsign=_SURGEON[2],
        )
        for slot, _agent_type, callsign in (_BUILDER, _PEERS[1]):
            await room.create_post(thread_id=thread.id, author_id=slot, body=f"{callsign} acknowledges.", author_callsign=callsign)
        service = ThreadPriorityService(runtime=SimpleNamespace(ward_room=room), scorer=ThreadPriorityScorer())
        built = await service._build_input(thread.id)
    assert built is not None
    assert built.participant_departments == ["engineering", "science"]


@until_built("#1792")
def test_the_unread_orientation_flag_is_gone_and_a_config_that_sets_it_still_loads() -> None:
    assert "populate_ward_room_department" not in OrientationConfig.model_fields
    loaded = SystemConfig.model_validate({"orientation": {"populate_ward_room_department": False, "enabled": True}})
    assert loaded.orientation.enabled is True
    assert "populate_ward_room_department" not in loaded.orientation.model_dump()


# --- #1793 -----------------------------------------------------------------------------------------------------


@until_built("#1793")
@pytest.mark.asyncio
async def test_ma_md_me_an_echo_among_certificated_agents_is_reported(tmp_path: Path, registry) -> None:
    assert await _thread_echo(tmp_path, registry, certify="before") == ["medium", "high"]


@pytest.mark.asyncio
async def test_the_same_echo_among_agents_with_no_certificate_is_reported_as_before(tmp_path: Path, registry) -> None:
    assert await _thread_echo(tmp_path, registry, certify="never") == ["medium", "high"]


@pytest.mark.asyncio
async def test_mb_an_agent_certificated_after_its_posts_is_still_matched(tmp_path: Path, registry) -> None:
    assert await _thread_echo(tmp_path, registry, certify="after") == ["medium", "high"]


@until_built("#1793")
@pytest.mark.asyncio
async def test_me_mf_mg_an_echo_in_replies_among_certificated_agents_is_reported(tmp_path: Path, registry) -> None:
    risks, _episodes, _channel_id, _status_id = await _reply_echo(tmp_path, registry)
    assert risks == ["medium", "high"]


@until_built("#1793")
@pytest.mark.asyncio
async def test_mf_mg_reply_episodes_store_the_channel_id(tmp_path: Path, registry) -> None:
    _risks, episodes, channel_id, status_id = await _reply_echo(tmp_path, registry)
    stored = [*_episodes_of(episodes, status_id, "ward_room_reply"), *_episodes_of(episodes, status_id, "peer_repetition")]
    assert len(stored) == 6  # premise: three replies, each with a peer-echo episode
    assert {ep.anchors.channel_id for ep in stored} == {channel_id}


@until_built("#1793")
@pytest.mark.asyncio
async def test_mc_one_recall_holds_a_matching_episode_of_every_peer_at_the_production_bound() -> None:
    peers = [generate_agent_id("scout", "scout", index) for index in range(_MAX_PEERS)]
    readers = [_owned(generate_agent_id("counselor", "counselor", index), f"read-{index}", "bridge") for index in range(3)]
    owned = [
        _owned(peer, f"echo-{index}", "medical" if index == _MAX_PEERS - 1 else "science")
        for index, peer in enumerate(peers)
    ]
    service = SocialVerificationService(_Episodes([*readers, *owned]), SocialVerificationConfig())
    matches = [{"author_id": peer, "author_callsign": f"Peer{index}", "timestamp": 1000.0 + index} for index, peer in enumerate(peers)]
    result = await service.check_cascade_risk(
        generate_agent_id("builder", "builder", 7), "Forge", _ECHO, "all-hands-id", peer_matches=matches,
    )
    assert result is not None
    assert result.affected_departments == ["medical", "science"]
    assert result.risk_level == "high"
```

**How the built cases fail on the base (expected):**
- #1792 helper cases: `''` is returned.
- `agent_type_of`: `callable(None)` is false.
- Episode and priority cases: the departments are `''` and `[]`.
- Flag case: the field still exists.
- #1793 chain cases: no event fires, so the risks are `[]`.
- Channel case: the name `All Hands` is stored.
- `mc`: `k=3` holds only the three readers, so the departments are `[]`.
- The three controls pass on the base.

### M2a (#1792)

**P2a-1** (`src/probos/substrate/identity.py`: the resolver)
SEARCH:
```
    return {
        "agent_type": prefix,
        "pool_name": "",
        "index": index,
        "hash": hash8,
    }
```
REPLACE:
```
    return {
        "agent_type": prefix,
        "pool_name": "",
        "index": index,
        "hash": hash8,
    }


def agent_type_of(agent_id: str) -> str:
    """BF-962 (#1792): the agent type a deterministic agent id names, or "" if it names none.

    The module registry first, then the hash-verified split (``parse_agent_id``).
    The best-effort prefix ``parse_agent_id`` returns when no split matches the
    hash is not a type, and neither is a value that is not a str.
    """
    parsed = parse_agent_id(agent_id) if isinstance(agent_id, str) else None
    if not parsed or not parsed.get("pool_name"):
        return ""
    return parsed["agent_type"]
```

**P2a-2** (`src/probos/ward_room/_helpers.py`: the department)
SEARCH:
```
def resolve_author_department(author_id: str) -> str:
    """Resolve department for Ward Room episode anchors (AD-567g)."""
    try:
        from probos.cognitive.standing_orders import get_department
        return get_department(author_id) or ""
    except Exception:
        return ""
```
REPLACE:
```
def resolve_author_department(author_id: str) -> str:
    """Resolve department for Ward Room episode anchors (AD-567g).

    BF-962 (#1792): the department table is keyed by agent type, and an agent's
    post names its author by the agent's id ({type}_{pool}_{index}_{hash8}).
    The value is tried as given first, so a bare type or a key such as
    ``captain`` behaves as before, then as the type the id names
    (``substrate.identity.agent_type_of``). An unknown value gives "".
    """
    try:
        from probos.cognitive.standing_orders import get_department
        from probos.substrate.identity import agent_type_of
        return get_department(author_id) or get_department(agent_type_of(author_id)) or ""
    except Exception:
        return ""
```

**P2a-3** (`src/probos/config_models/knowledge.py`: the unread flag)
SEARCH:
```
    populate_watch_section: bool = True
    populate_ward_room_department: bool = True
```
REPLACE:
```
    populate_watch_section: bool = True
```

**P2a-4** (`config/system.yaml`)
SEARCH:
```
  populate_watch_section: true
  populate_ward_room_department: true
```
REPLACE:
```
  populate_watch_section: true
```

**P2a-5** (`tests/test_ad1270e2f_knowledge_models.py`: the default dump golden; the reason is inline)
SEARCH:
```
                             'populate_watch_section': True,
                             'populate_ward_room_department': True,
```
REPLACE:
```
                             # BF-962 (#1792): populate_ward_room_department removed; it had no reader.
                             'populate_watch_section': True,
```

**C2a-1.** Run `PY -P scripts/check_config_facade.py --update-baseline`, then `PY -P scripts/check_config_facade.py --check`. The only lines allowed to change in `docs/development/config-facade-baseline.yaml` are these six (the diff is 5 insertions and 6 deletions):
- OrientationConfig's `- {default: 'True', name: populate_ward_room_department}`, removed;
- the `schema_sha256` line of OrientationConfig;
- the `schema_sha256` line of SystemConfig, the one model whose schema embeds it;
- `surface_counts.canonical_dump_leaves`, 1896 to 1895;
- `surface_counts.field_definitions`, 1886 to 1885;
- `canonical_dump_sha256` (base `5658987ad1ad4a36ec30227ac0788ea77a10aa3e47a483c6d7fc8eb5f81776aa`; the new value is whatever the run writes).

The other `surface_counts` lines stay: `aliased_fields: 1`, `incidental: 13`, `own_models: 229`, `owned: 297`, `public_names: 310`. Any other line that changes is a hard stop.

**C2a-2.** Run `PY -P scripts/gen_config_reference.py`, then `PY -P scripts/gen_config_reference.py --check`. The only change allowed is the removal of the `populate_ward_room_department` row.

**P2a-6** (`tests/test_ward_room_identity_keys.py`)
SEARCH:
```
_BUILT: frozenset[str] = frozenset()
```
REPLACE:
```
_BUILT: frozenset[str] = frozenset({"#1792"})
```

**P2a-7** (`tests/test_ad1270e1_config_facade.py`: the pinned field count; the reason is inline)
SEARCH:
```
    # BF-957 (#1760) adds RecordsConfig's three git_* doctor thresholds (1883 -> 1886).
    assert counts["field_definitions"] == 1886  # AD-1206 intentionally adds github_repository.
```
REPLACE:
```
    # BF-957 (#1760) adds RecordsConfig's three git_* doctor thresholds (1883 -> 1886).
    # BF-962 (#1792) removes orientation.populate_ward_room_department, which nothing read (1886 -> 1885).
    assert counts["field_definitions"] == 1885  # AD-1206 intentionally adds github_repository.
```

### M2b (#1793)

**P2b-1** (`src/probos/cognitive/social_verification.py`: the owner keys)
SEARCH:
```
_ALLOWED_DETAIL_KEYS = frozenset({"episode_a", "episode_b", "reason", "weight"})
```
REPLACE:
```
_ALLOWED_DETAIL_KEYS = frozenset({"episode_a", "episode_b", "reason", "weight"})

#: BF-963 (#1793): the episodes one cascade recall holds for each distinct author
#: id (the post's and each matched peer's): the k=3 each peer's recall used to have.
_RECALL_PER_OWNER = 3


def _owner_keys(author_id: str, identity_registry: Any) -> frozenset[str]:
    """BF-963 (#1793): the ids an episode of ``author_id`` can be stored under.

    The Ward Room stores a post's episode under
    ``resolve_sovereign_id_from_slot(author_id, identity_registry)``: the
    certificate id when the registry maps the slot. An episode stored before
    the certificate (or a group-chat fan-out episode) keeps the slot id, so
    both are kept. An empty id owns nothing.
    """
    if not author_id:
        return frozenset()
    try:
        from probos.cognitive.episodic import resolve_sovereign_id_from_slot

        return frozenset({author_id, resolve_sovereign_id_from_slot(author_id, identity_registry)})
    except Exception:
        logger.debug("BF-963: owner key lookup failed for %s", author_id, exc_info=True)
        return frozenset({author_id})


def _owned_by(episodes: list[Any], keys: frozenset[str]) -> list[Any]:
    """BF-963 (#1793): the episodes, in order, whose owners include one of ``keys``."""
    return [ep for ep in episodes if any(key in (getattr(ep, "agent_ids", None) or []) for key in keys)]
```

**P2b-2** (`src/probos/cognitive/social_verification.py`: the parameter)
SEARCH:
```
        *,
        peer_matches: list[dict[str, Any]] | None = None,
    ) -> CascadeRiskResult | None:
        """Proactive cascade detection on Ward Room posts.

        Called after AD-506b peer similarity detection to check if
        similar posts lack independent anchor evidence.
        """
```
REPLACE:
```
        *,
        peer_matches: list[dict[str, Any]] | None = None,
        identity_registry: Any = None,
    ) -> CascadeRiskResult | None:
        """Proactive cascade detection on Ward Room posts.

        Called after AD-506b peer similarity detection to check if
        similar posts lack independent anchor evidence.

        BF-963 (#1793): ``identity_registry`` is the one the Ward Room stored
        the posts' episodes with; each author id is matched to an episode's
        owners as given and as the certificate id it maps to.
        """
```

**P2b-3** (`src/probos/cognitive/social_verification.py`: one recall)
SEARCH:
```
        source_agent = author_callsign

        for match in peer_matches:
```
REPLACE:
```
        source_agent = author_callsign

        # BF-963 (#1793): one recall, large enough to hold _RECALL_PER_OWNER
        # episodes of each distinct author id. The recall of k=3 that used to run
        # once for each peer answered the same three episodes every time.
        owners = {match.get("author_id", "") for match in peer_matches} | {author_id}
        owners.discard("")
        keys = {owner: _owner_keys(owner, identity_registry) for owner in owners}
        recalled: list[Any] = []
        try:
            recalled = await self._episodic.recall(post_body, k=_RECALL_PER_OWNER * max(len(owners), 1))
        except Exception:
            logger.debug("AD-567f: cascade recall failed", exc_info=True)

        for match in peer_matches:
```

**P2b-4** (`src/probos/cognitive/social_verification.py`: membership by both keys)
SEARCH:
```
            # Look up peer's episodes matching the post
            try:
                peer_episodes = await self._episodic.recall(post_body, k=3)
                peer_episodes = [
                    ep for ep in peer_episodes
                    if match_author in getattr(ep, "agent_ids", [])
                ]
                matched_episodes.extend(peer_episodes)
```
REPLACE:
```
            # Look up peer's episodes matching the post (BF-963: by both keys)
            try:
                peer_episodes = _owned_by(recalled, keys.get(match_author, frozenset()))
                matched_episodes.extend(peer_episodes)
```

**P2b-5** (`src/probos/cognitive/social_verification.py`: the author)
SEARCH:
```
        try:
            author_episodes = await self._episodic.recall(post_body, k=3)
            author_episodes = [
                ep for ep in author_episodes
                if author_id in getattr(ep, "agent_ids", [])
            ]
            matched_episodes.extend(author_episodes)
```
REPLACE:
```
        try:
            matched_episodes.extend(_owned_by(recalled, keys.get(author_id, frozenset())))
```

**P2b-6** (`src/probos/ward_room/_helpers.py`: the parameter)
SEARCH:
```
    channel_id: str,
    peer_matches: list[dict],
) -> None:
    """Check cascade confabulation risk and raise its Bridge alert (AD-567f).
```
REPLACE:
```
    channel_id: str,
    peer_matches: list[dict],
    identity_registry: Any = None,  # BF-963 (#1793): the registry the posts' episodes were stored with
) -> None:
    """Check cascade confabulation risk and raise its Bridge alert (AD-567f).
```

**P2b-7** (`src/probos/ward_room/_helpers.py`: the call)
SEARCH:
```
            channel_id=channel_id,
            peer_matches=peer_matches,
        )
        if cascade and bridge_alerts:
```
REPLACE:
```
            channel_id=channel_id,
            peer_matches=peer_matches,
            identity_registry=identity_registry,
        )
        if cascade and bridge_alerts:
```

**P2b-8** (`src/probos/ward_room/threads.py`) and **P2b-9** (`src/probos/ward_room/messages.py`): the same pair, each applied once in its own file.
SEARCH:
```
            post_body=post_body, channel_id=channel_id,
            peer_matches=peer_matches,
        )
```
REPLACE:
```
            post_body=post_body, channel_id=channel_id,
            peer_matches=peer_matches,
            identity_registry=self._identity_registry,
        )
```

**P2b-10** (`src/probos/ward_room/messages.py`: the reply episode)
SEARCH:
```
                        channel_id=channel_name,
                        thread_id=thread_id,
                        trigger_type="ward_room_reply",
```
REPLACE:
```
                        channel_id=thread_channel_id,  # BF-963 (#1793): the channel's id, as a thread episode stores it
                        thread_id=thread_id,
                        trigger_type="ward_room_reply",
```

**P2b-11** (`src/probos/ward_room/messages.py`: the reply's peer-repetition episode)
SEARCH:
```
                        channel_id=channel_name,
                        thread_id=thread_id,
                        trigger_type="peer_repetition",
```
REPLACE:
```
                        channel_id=thread_channel_id,  # BF-963 (#1793): the channel's id, not its name
                        thread_id=thread_id,
                        trigger_type="peer_repetition",
```

**P2b-12** (`tests/test_ward_room_identity_keys.py`)
SEARCH:
```
_BUILT: frozenset[str] = frozenset({"#1792"})
```
REPLACE:
```
_BUILT: frozenset[str] = frozenset({"#1792", "#1793"})
```

### M3: trackers and ledger

Replace `DATE` with M3's date. No line carries an `AD-` or `BF-` token or this contract's file name.

**P3-1** (`PROGRESS.md`). The anchor is the title line and the blank line after it. The earlier batches' entries stay below this one.
SEARCH:
```
# ProbOS Progress

```
REPLACE:
```
# ProbOS Progress

**A Ward Room episode an agent writes carries its department, and the cascade check meets episode owners in their own key (DATE), #1792 #1793.**
- **Base.** The department lookup for Ward Room episodes was keyed by agent type but given the agent's id, so an agent's thread and reply episodes had an empty department anchor and thread priority saw no departments. The cascade check compared a post's raw agent id with episode owners stored under the certificate id, so it kept no thread or reply episode of an agent with a certificate. Its recall of three episodes, repeated for each peer, held three episodes in all. A reply episode stored the channel's name where a thread episode stores its id.
- **Change.** `substrate.identity.agent_type_of` names the type of a registered or hash-verified id. `resolve_author_department` tries the value as given, then that type. The unread `orientation.populate_ward_room_department` is removed, and a config that sets it still loads. The cascade check takes the Ward Room's identity registry and matches each author id as given and as its certificate id, with one recall of three episodes per distinct author id. A reply episode stores the channel id. New episodes gain the department in their metadata, in their embedded text, in recall by department and in anchor confidence. No stored episode changes. The risk thresholds are unchanged. The check can now raise its event, its Bridge alert, a Captain notification and Counselor messages for agents with certificates; `social_verification.cascade_enabled` stays its off switch. The replay on a copy of a vessel's data waits for the Captain. Refs #1792, #1793.

```

**P3-2** (`DECISIONS.md`). The anchor is the heading below (line 1796 on `5275d008`). The earlier batches insert before it too.
SEARCH:
```
### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```
REPLACE:
```
### Ward Room identity keys: an agent id finds its department; the cascade check meets episode owners in their own key (DATE, #1792, #1793)

- *Scope.* `substrate/identity.py` (`agent_type_of`), `ward_room/_helpers.py`, `ward_room/threads.py`, `ward_room/messages.py`, `cognitive/social_verification.py`, the orientation config model and yaml, the two generated config documents; one new test file; a golden and a pinned field count updated inline.
- *G1 (department).* Try the value as given, then the type of a registered or hash-verified id. The unread flag is removed rather than given a reader: the Ward Room holds no config, and a reader would add a switch that empties the anchor this repairs.
- *G2 (owner key).* The registry the Ward Room stored the episodes with reaches the check; both ids match. One recall of three episodes per distinct author id, bounded by the 40 rows one peer check returns. Rejected: per-agent recall, whose relaxed threshold changes what counts as a match.
- *G3 (reply channel).* New reply episodes store the channel id. Stored ones keep the name; a form rule in the comparison was rejected, because it would also move the dream, records and metrics consumers of the independence score.
- *Rollout.* No new flag: `social_verification.cascade_enabled` and the Bridge alert's cooldown and mute already bound it. *Residual.* L1 to L7 of the contract. *Reversal.* Revert the batch's commits in reverse order.

### AD-1346 M3e4d9 -- part (a) of the pending workforce scopes, classified (2026-11-05, #1604)
```

**Ledger.** Run G3. No AD or BF number moves. The roadmap Bug Tracker is not edited.

## 5. Commit messages

Every body ends with its `Refs` paragraph, and the committing agent's trailer paragraph comes after it. No subject contains an `AD-` or `BF-` token. No message uses close, closes, closed, fix, fixes, fixed, resolve, resolves or resolved in any form, including inside a compound word, a hyphenated word or a quotation; this also rules out naming `resolve_author_department` or `resolve_sovereign_id_from_slot` in a message. Write "refuses" or "is denied", never "fail closed" or "fixed-length".
- Contract (the orchestrator's): `Ward Room identity keys (#1792, #1793): contract for the department of an agent id, cascade owner keys and the reply channel id`, then `Refs #1792, #1793.`
- M1: `Ward Room identity keys M1: tests for departments, cascade owner keys and reply channel ids, xfail until built (#1792, #1793)`, then `Refs #1792, #1793.`
- M2a: `Ward Room identity keys M2a: an agent id finds its type's department, and the unread orientation flag goes (#1792)`, then `Refs #1792.`
- M2b: `Ward Room identity keys M2b: the cascade check matches posts to episode owners by both ids, with one recall for every peer (#1793)`, then `Refs #1793.`
- M3: `Ward Room identity keys M3: trackers and ledger (#1792, #1793)`, then `Refs #1792, #1793.`

With `BASE` = the `origin/main` commit the batch is built on, both scans must print nothing:
- `git log --format=%B BASE..HEAD | rg -n -i "\bClos[e]s\b"`
- `git log --format=%B BASE..HEAD | rg -n -i "\b(clos[e][sd]?|fix(e[sd])?|resolv[e][sd]?)\b"`

The orchestrator closes #1792 after the gate. #1793 stays open with only its replay item unchecked (D3).

## 6. Recorded limits

- **L1 (#1792).** Stored episodes keep their empty department; no backfill. An id that is neither registered nor hash-verified, a DID and a callsign give `""`, as before.
- **L2 (#1792).** The two other sites of the same root cause (the dream, #1523 F-491; capability triage, #1419) are not changed. Each one activates a held behaviour.
- **L3 (#1793).** Stored reply episodes keep the channel name. A stored reply and a thread episode of the same channel, in different threads less than 60 s apart, still read as different channels. This happens only when both episodes predate the change, or across a restart shorter than 60 s.
- **L4 (#1793).** Other agents' episodes still compete for the pool. A peer whose matching episode is in neither the recall of three nor the recall of `3 * owners` is still missed; the wider recall holds at most 123.
- **L5 (#1793).** Duplicates are kept as today: a peer matched twice adds its episodes twice; an episode both recalls hold enters the pool once. With no registry, or an uncertificated agent, the only change is the pool. Recomputed for BF-921's three cases (`test_bf921...:248`): low, medium and high hold (its `[:k]` double's recall of three is a prefix of its wider recall, so the union is the wider recall, as at M2b).
- **L6 (#1793).** The replay waits for the Captain's copy (D3).
- **L7 (#1793).** For agents with certificates, a medium or high risk now emits `CASCADE_CONFABULATION_DETECTED`. That produces a Bridge alert (advisory or alert, de-duplicated for 300 s and muteable), a Captain notification where one is wired, and on high the Counselor's messages (`counselor.py:1555-1581`).

## 7. Mutation rows (each line occurs once, stripped, in its file after R1; expected, not measured; rows 7 and 13 to 16 run on the new file only)

| # | File | Line | Mutate to | Killed by |
|---|---|---|---|---|
| 1 | `_helpers.py` | `return get_department(author_id) or get_department(agent_type_of(author_id)) or ""` | `return get_department(author_id) or ""` (#1792's named) | r1 (all four) |
| 2 | same | same | `return get_department(agent_type_of(author_id)) or ""` | r2_r3 |
| 3 | `identity.py` | `if not parsed or not parsed.get("pool_name"):` | `if not parsed:` | r3_r4, r2_r3 |
| 4 | same | `parsed = parse_agent_id(agent_id) if isinstance(agent_id, str) else None` | `parsed = parse_agent_id(agent_id)` | r3_r4 |
| 5 | `social_verification.py` | `return frozenset({author_id, resolve_sovereign_id_from_slot(author_id, identity_registry)})` | `return frozenset({author_id})` (#1793's named) | ma_md_me, me_mf_mg |
| 6 | same | same | `return frozenset({resolve_sovereign_id_from_slot(author_id, identity_registry)})` | mb |
| 7 | same | `wide = await self._episodic.recall(post_body, k=_RECALL_PER_OWNER * len(owners))` | `wide = await self._episodic.recall(post_body, k=_RECALL_PER_OWNER)` | mc |
| 8 | `_helpers.py` | `identity_registry=identity_registry,` | delete the line | ma_md_me, me_mf_mg |
| 9 | `threads.py` | `identity_registry=self._identity_registry,` | delete the line | ma_md_me |
| 10 | `messages.py` | `identity_registry=self._identity_registry,` | delete the line | me_mf_mg |
| 11 | same | `channel_id=thread_channel_id,  # BF-963 (#1793): the channel's id, as a thread episode stores it` | `channel_id=channel_name,` | me_mf_mg, mf_mg |
| 12 | same | `channel_id=thread_channel_id,  # BF-963 (#1793): the channel's id, not its name` | `channel_id=channel_name,` | me_mf_mg, mf_mg |
| 13 | `social_verification.py` | `recalled = await self._episodic.recall(post_body, k=_RECALL_PER_OWNER)` | `recalled = await self._episodic.recall(post_body, k=_RECALL_PER_OWNER * max(len(owners), 1))` (M2b's one recall) | mh |
| 14 | same | `recalled = _union_by_id(recalled, wide)` | `recalled = wide` | mh |
| 15 | same | `if len(owners) > 1:` | `if False:` | mc |
| 16 | same | `return [*first, *(ep for ep in second if ep.id not in held)]` | `return [*first, *second]` | mi |

Expected arithmetic:
- Row 11: 4 of 10 pairs become independent, giving 0.4 and a low risk where high is expected.
- Row 12: 2 of 10, giving 0.2 and a medium risk.
- Rows 7 and 15 at 40 peers: the pool is the recall of three, which holds only the three readers.
- Rows 13 and 14 (case mh): the pool is the recall of 12, which lacks `visual-00`; one episode is matched, the score is 1.0 and the risk none.
- Row 16 (case mi): each episode is matched twice; 4 of 6 pairs are independent, not 1 of 1.

## 8. What this does NOT change

- **Source:**
  - the risk thresholds (`social_verification.py:592-601`), `compute_anchor_independence` and `_are_independently_anchored`;
  - `check_corroboration`, `BridgeAlertService` and the Counselor;
  - `routers/thread_fanout.py` and BF-103's migration;
  - `standing_orders.py` (`_AGENT_DEPARTMENTS`, `get_department`) and `ontology.get_agent_department`;
  - the dream's and capability triage's lookups;
  - `cognitive/thread_priority/service.py`;
  - `identity_service.py`;
  - stored episodes.
- **Config:** `populate_watch_section` and `populate_event_log_window` stay; no other key moves.
- **Tests:** of the existing files, only `test_ad1270e2f_knowledge_models.py` (P2a-5) and `test_ad1270e1_config_facade.py` (P2a-7) are edited. No other pinned value moves (consumer search, section 3).
- **Elsewhere:** `ui/`; the commercial overlay; every tracker except `PROGRESS.md`, `DECISIONS.md` and the ledger pair; the roadmap Bug Tracker.

## 9. Diff Reviewer (`gpt-6.1-sol`): properties to verify

Name the consumer for each property and confirm that it accepts the change.

1. **#1792.**
   - For any input, `resolve_author_department` returns `get_department(value)` when that is non-empty, else the department of `agent_type_of(value)`, else `""`, and never raises.
   - `agent_type_of` returns a type only from the module registry or a hash-verified split.
   - **Consumers:** the four anchor sites through the static methods (`threads.py:607`, `:657`, `messages.py:364`, `:415`); thread priority (`service.py:119`, `:132`); the two test patches (`test_ad641c...:354`, `test_orientation.py:285`), which keep their target names.
2. **Removal.**
   - No production reader of `populate_ward_room_department` remains, and a config that sets the key still loads.
   - The regenerated baseline and reference differ only as C2a-1 and C2a-2 allow.
   - **Consumers:** `scripts/check_config_facade.py --check`, `scripts/gen_config_reference.py --check`, `scripts/check_config_readers.py`, `test_ad1270e1_config_facade.py::test_committed_baseline_records_the_measured_surface` (`field_definitions == 1885`, P2a-7).
3. **#1793 key.**
   - The registry handed to the check is the store's own `_identity_registry`, the one used at `threads.py:579` and `messages.py:329`.
   - An episode is kept for an id exactly when its owners contain that id or the certificate id it maps to.
   - With `identity_registry=None`, the result equals the base's for any input whose recall returns all episodes.
   - **Consumers:** `BridgeAlertService.check_cascade_risk` (`bridge_alerts.py:849`) and the Counselor's cascade handler, both reading the unchanged `CascadeRiskResult` fields.
4. **Recall.** A check makes at most two `recall` calls: `recall(post_body, k=3)`, the base's call, and, only with more than one distinct non-empty author id, `recall(post_body, k=3 * distinct non-empty author ids)`. The pool is the first result, then each episode of the second whose id the first does not hold, so every episode the base's recall returned is in the pool whether recall fuses, reranks or ranks by similarity alone. A failure of either recall leaves the other's episodes. Per-peer filtering keeps duplicates as before. The disabled path still awaits no recall (`test_bf920...:269`).
5. **Reply channel.** Both reply-path episodes store `thread_channel_id`, the value the same method hands the cascade check (`messages.py:319`). **Consumers:** `anchor_quality.py:47` (presence only) and `_are_independently_anchored` (`:104-109`).
6. **Paperwork.** The text is ASCII. Subjects and tracker lines carry no `AD-` or `BF-` token, and both scans of section 5 are clean.

## 10. Acceptance criteria

- **#1792:**
  - The helper returns the department of an agent given its id (registered or restored), of a bare type as before, and `""` for an unknown value, never an exception.
  - Through the real `WardRoomService` with an episodic store and an identity registry, a thread and the replies by production-shaped ids store their types' departments, and a real promotion request's episode stores `engineering`.
  - Thread priority's `participant_departments` is filled through `_build_input`.
  - `populate_ward_room_department` is removed (D1).
  - Row 1 fails the r1 cases.
- **#1793:**
  - Three certificated peers echoing a post (a real promotion request) give `["medium", "high"]`.
  - The same posts by agents with no certificate, and by agents certificated after their posts, give it too.
  - A reply echo among certificated agents gives it, and reply episodes store the channel id.
  - At 40 peers, the pool holds every peer's episode (`mc`). An episode that a hybrid-shaped recall of three holds and its recall of `3 * owners` drops is kept (`mh`). An episode both recalls hold counts once (`mi`).
  - Row 5 fails the chain cases.
  - The replay waits for the Captain (D3, L6).
- The report states what changes for new episodes, that no stored episode changes, and what can now fire for agents with certificates (L7).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## 11. Verified Against Codebase (2026-11-14, read-only tree `D:\ProbOS-worktrees\next-read2` at `origin/main` `5275d00874799d68536fef2a7ff27c7bc44cda65`)

```
_helpers.py:11  def resolve_author_department(author_id: str) -> str:
_helpers.py:15  return get_department(author_id) or ""
_helpers.py:37  async def check_and_alert_cascade_risk(
_helpers.py:61  cascade = await social_verification.check_cascade_risk(
standing_orders.py:78-80  def get_department(agent_type) ... return _AGENT_DEPARTMENTS.get(agent_type)
substrate/identity.py:54  def parse_agent_id(agent_id: str) -> dict[str, str] | None:
substrate/identity.py:99-105  best-effort return, "pool_name": ""
thread_priority/service.py:119  from probos.ward_room._helpers import resolve_author_department
thread_priority/service.py:132  dept = resolve_author_department(author_id) or ""
threads.py:45, :65  ORDER BY created_at DESC LIMIT 20 (twice)
threads.py:164  self._identity_registry = identity_registry
threads.py:207-214  await check_and_alert_cascade_risk(... peer_matches=peer_matches, )
threads.py:569  await self._check_cascade_risk(...)   (before the episode is stored, :575)
threads.py:579  sovereign_id = resolve_sovereign_id_from_slot(author_id, self._identity_registry)
threads.py:602, :653  channel_id=channel_id,
messages.py:38  self._identity_registry = identity_registry
messages.py:125-132  await check_and_alert_cascade_risk(...)
messages.py:177  thread_channel_id = row[1]
messages.py:319  await self._check_cascade_risk(peer_matches, author_id, author_callsign, body, thread_channel_id)
messages.py:359, :411  channel_id=channel_name,
episodic.py:474-485  def resolve_sovereign_id_from_slot ... return cert.agent_uuid
episodic.py:3434  async def recall(self, query, k=5, *, include_self_contradicted=False)
episodic.py:3959  agent_recall_threshold = min(self.relevance_threshold, self._agent_recall_threshold)
social_verification.py:69  _ALLOWED_DETAIL_KEYS = frozenset({...})
social_verification.py:511-524  async def check_cascade_risk(... *, peer_matches=None) -> CascadeRiskResult | None:
social_verification.py:536, :538, :546, :548, :566, :568  source_agent=...; for match...; recall(post_body, k=3) twice
social_verification.py:592-601  risk classification
service.py:52-61  WardRoomService.__init__(db_path, emit_event, episodic_memory, ontology, hebbian_router, connection_factory, identity_registry)
service.py:423, :477, :436  create_thread, create_post, get_thread(**kwargs)
identity.py:560, :678, :787, :893  start, stop, get_by_slot, issue_birth_certificate(... slot_id="")
cognitive_agent.py:2830  async def _announce_promotion_request(self, procedure_id, promotion_result)
cognitive_agent.py:2859, :2870, :2879-2885  agent_id = self.id; "All Hands"; create_thread(author_id=agent_id)
channels.py:103  (str(uuid.uuid4()), "All Hands", "ship", ...)
bridge_alerts.py:73, :102-111, :849-878  cooldown 300; _should_emit; check_cascade_risk
system.yaml:1947, :1954  populate_ward_room_department: true; cascade_enabled: true
knowledge.py:399  populate_ward_room_department: bool = True
config-facade-baseline.yaml:2661, :2669  schema_sha256; {default: 'True', name: populate_ward_room_department}
config-reference.md:2442  | `populate_ward_room_department` | ...
test_ad1270e2f_knowledge_models.py:198  'populate_ward_room_department': True,
config-facade-baseline.yaml:50, :51, :56  canonical_dump_leaves: 1896; field_definitions: 1886; canonical_dump_sha256: 5658987a...
test_ad1270e1_config_facade.py:1570-1571  # BF-957 ... (1883 -> 1886).  assert counts["field_definitions"] == 1886
test_ad1270e1_config_facade.py:1592  assert baseline["models_with_model_config"] == ["CommandPolicyConfig", "CommandPolicyRule"]
PROGRESS.md:1  # ProbOS Progress     DECISIONS.md:1796  ### AD-1346 M3e4d9 -- part (a) ...
```

**Absence verified (2026-11-14).**

```
CLAIM: nothing reads populate_ward_room_department
RUN:   Grep "populate_ward_room_department" over the whole tree
FOUND: config/system.yaml:1947, config_models/knowledge.py:399, tests/test_ad1270e2f...:198,
       docs/development/config-facade-baseline.yaml:2669, docs/development/config-reference.md:2442,
       decisions-era-4-evolution.md:2616, prompts (3 files)
HOLDS: yes -- a declaration, the yaml, a golden, two generated docs, history

CLAIM: neither OrientationConfig nor SystemConfig sets `extra`, so a removed orientation key still loads
RUN:   Grep "extra\s*=|model_config" in src/probos/config.py, then in the directory src/probos/config_models/
       (the first draft's brace glob over both returned a false empty); control: Grep "^class " in
       config_models/operations.py finds :146, :203, :250 ...
FOUND: config.py: none. config_models/operations.py:166, :215  model_config = ConfigDict(extra="forbid", frozen=True)
       (CommandPolicyRule :146, CommandPolicyConfig :203; under ExecutionConfig.command_policy, :397)
HOLDS: yes for the claim as stated: both forbid models are off the orientation load path. The orchestrator executed
       SystemConfig.model_validate({"orientation": {"enabled": True, "populate_ward_room_department": False}})
       on the scratch tree, and it loads and ignores the key. Pinned by test_ad1270e1_config_facade.py:1592 and by
       test_the_unread_orientation_flag_is_gone_and_a_config_that_sets_it_still_loads; BF-926's still-loads test
       (test_bf926_config_readers.py:152-161) is the precedent.

CLAIM: no test reads a stored episode's anchors.channel_id; the src readers are two
RUN:   Grep "anchors\.channel_id" in {src,tests}/**/*.py
FOUND: src/probos/cognitive/anchor_quality.py:47 only; _are_independently_anchored reads anchors_a.channel_id (:105-107)
HOLDS: yes

CLAIM: only three test files call check_cascade_risk, all on the real service
RUN:   Grep "check_cascade_risk|check_and_alert_cascade_risk" in tests
FOUND: test_social_verification.py, test_bf920_cross_agent_verification.py, test_bf921_counselor_event_delivery.py
HOLDS: yes; no side_effect recall double (Grep "side_effect|recall\." in them: test_bf920...:269 only)

CLAIM: no test pins the empty department of a Ward Room episode by an id
RUN:   Grep 'department == ""|_resolve_author_department|get_department\(' in tests
FOUND: unrelated (test_ad570c:42, test_ad661bc:44, standing-orders contracts, test_orientation.py:285 patch)
HOLDS: yes
```

## 12. Prior Art and Blind Spots

- **Internal.**
  - `identity_service.IdentityService.resolve` (AD-1346; `tests/test_ad1346_identity_service.py:3`) resolves any identity form to a ref carrying `agent_type`. Adapted, not adopted: it is the target for the shared sites in later slices, but this batch's static helper holds no instance.
  - BF-103's slot-to-certificate migration (`episodic.py:488`) is why both keys are kept.
  - BF-920 (#1633) is the five earlier cascade repairs; it supplies the double pattern of `[:k]` recall (`test_bf921...:243`).
- **External.** Skipped: this is key plumbing specific to ProbOS. The general rule, normalising join keys to one canonical id before a membership test, needs no source. `docs/research/reference-projects.md` was not read in this run, so no row was examined or updated.
- **Blind spots, and where each is handled:**
  - duplicate peers inflate dependence (L5, kept);
  - fan-out and pre-certificate episodes keep the slot id (handled by both keys);
  - after a slot reassignment the old certificate's episodes are not matched (accepted; `reassign_slot` is a rare manual step);
  - at most two recalls replace up to 41, a cost reduction;
  - the cascade check runs before the post's own episode is stored, so the author contributes only earlier episodes (unchanged).

## 13. Amendment A1 (2026-11-16): review round 1, finding F1

**Revised by** `claude-architect`. Sections 1 to 12 are read with this section; where they differ, this section wins. Edited in place: the header, G2b's count, D2, L4, L5, section 7 (heading, row 7, rows 13 to 16, arithmetic), section 9 property 4, section 10 and section 12's cost line. M2b's commit subject ("with one recall for every peer") is history and stays; this section supersedes it.

| # | Milestone | Finding | Reach | Regression | Disposition |
|---|---|---|---|---|---|
| F1 | M2b | `check_cascade_risk` made one recall with `k = 3 * owners`. With hybrid recall on (shipped: `config/system.yaml:137`), the fused top `k` is not contained in the fused top `k'` for `k' > k` (`episodic.py:3615-3623`: a sparse window of `3 * k`, reciprocal rank fusion, a cut to `k`), so the wider recall can drop an episode the base's `recall(k=3)` held. The reviewer and the orchestrator's probe reproduced it on a real `EpisodicMemory(hybrid_recall_enabled=True)` with 21 synthetic episodes: `recall(k=3)` = `[dense-00, visual-00, dense-01]`; `k=6`, `9` and `12` hold only dense episodes; `k=15` holds `visual-00` again. For peers a, b and c, the base gave `high` with one event and the candidate `none` with none. | ordinary | yes (P2) | repaired: R1-1, R1-2; cases mh, mi |

**D2 corrected.** "The pool holds what the base saw" was argued for prefix-shaped recalls. It fails under hybrid fusion (measured) and, by reading (not measured), under composite reranking, whose candidate window is `10 * k` (`episodic.py:3494`; off by default, `config.py:980`). The dense-only path takes the first `k` passing candidates of a similarity-ordered window of `3 * k` (`episodic.py:3494`, `:3551-3554`). By reading, that is a prefix only as far as the vector index returns the same order for a larger window (not measured). The union makes the pool independent of all three paths.

**Rejected:**
- one wider recall with the gap recorded as a limit (a regression of ordinary reach under the shipped config);
- `recall_for_agent` per peer (D2's reason stands);
- a larger fixed `k` alone (no `k` makes fused results nested).

**The test doubles.** `_Fused` runs the production `reciprocal_rank_fusion` at its default `k=60` (`episodic.py:235-236`; `config.py:1006`) with `_fuse_dense_sparse`'s windows. Two premise assertions in case mh fail loudly if the fixture stops discriminating. A real hybrid store was not used: its ranking depends on which embedding function the environment has, either a cached model or the fallback CI's `PROBOS_EMBEDDINGS=local` selects (`tests/conftest.py:183-189`, `.github/workflows/ci.yml:40`). The probe above is the record that the real store has this shape. `_Copies` answers new Episode objects per recall, so case mi needs the union to deduplicate by episode id, not by object.

| Case | Kind | Asserts |
|---|---|---|
| mh | regression | premise: the recall of 3 is `[dense-00, visual-00, dense-01]` and the recall of 12 holds `dense-00` but not `visual-00`; peers a, b and c give `high` |
| mi | control | two peers' episodes in different channels and threads, held by both recalls as new objects, give an independence score of 1.0 |

**Counts (expected, not measured).** The new file has 15 cases, none marked. With R1's tests on the M2b source: mh fails (`none`), 14 pass. After R1: 15 pass.

**L8 (#1793).** The pool holds at least the base's episodes, not only them. An episode that only the wider recall holds can raise or lower the independence score, so a risk can differ from the base's, for agents with or without certificates. That is D2's purpose, more of each peer's episodes, not a loss of any episode the base saw.

**Captain.** None: the change strengthens a control, adds no flag and can be reverted (D4).
