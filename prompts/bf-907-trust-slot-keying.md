# BF-907: trust is keyed by slot id. Resolve sovereign identities at the trust boundary, fix the telemetry callers, and merge the stranded records once before AD-280 deletes them

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-18
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-19 (live premises re-probed: the knowledge-store trust snapshot; anchors re-verified on `02eb27bc`)
**Applied by:** the orchestrator, 2026-10-19: the 32 edits of the Architect's read-only re-validation (session `86b68b1f`), each SEARCH matched exactly once by the edit tool, plus two corrections of mine, both measured on copies of the live files: the in-memory key count at the merge is about 105 (102 measured plus this session's runtime ids), not the 101 the re-validation inferred, and the seven slot mappings it marked inferred are measured in `identity.db` (its asterisks are dropped). BF-906 merged as `84852598` after the candidate `02eb27bc` was re-validated; its production code is the tree of its source commit `0737c116`, and all 31 source blocks below apply on `84852598` (0 failures; the first check counted 29 because it skipped two blocks whose labels carry an annotation, see Amendment A1).
**Issue:** #1597 (and its 2026-10-19 crew amendment, Captain-approved). **Number:** BF-907. Source: the #1597 title. `gh search issues "BF-907"` returns only #1597. The highest BF in git subjects is BF-905 (`02778c3d`), and BF-906 is #1594.
**Status:** ready to build after BF-906 (#1594) merges. **Tier:** HIGH (identity and trust integrity). **Dependencies:** none on BF-906's code.
**Estimated tests:** 28 new tests in `tests/test_bf907_trust_identity.py`, 5 updated tests.
**Anchors:** drafted on `origin/main` @ `cf08d4c9`; re-verified 2026-10-19 on `02eb27bc` (`a9a01281` plus BF-906). `git diff --stat cf08d4c9 02eb27bc` touches three cited files (`agent_onboarding.py`, `runtime.py`, `startup/finalize.py`, all BF-906) and no cited test; every SEARCH block still matches once.

## Problem (re-verified)

Trust records are keyed by **slot id** (`surgeon_medical_surgeon_0_b2321292`). Episodes, memory and several call sites use the **sovereign id** (the certificate UUID, `agent_onboarding.py:456`; `cognitive/episodic.py:463-469`: "All episode agent_ids_json entries MUST use sovereign_id"). For an unknown key, `TrustNetwork.get_score` returns the prior 0.5 (`consensus/trust.py:949-954`). Writers that hold a sovereign id therefore create **stray** records, and readers that hold one read the prior or a stray. Then, at every start, AD-280 deletes every key that is not an active slot id (`startup/structural_services.py:72-76`, `consensus/trust.py:996-1002`), so the stray evidence is destroyed.

### Paths and keys (verified)

| Path | Key passed | Anchor | Correct? |
|---|---|---|---|
| Header "Your trust" | `get_score(self.id)` (slot) | `cognitive/cognitive_agent.py:8893` in `_sensorium_agent_metrics` (`:8880`), rendered `:8908` | yes |
| Proactive telemetry block | `sovereign_id or agent.id` | `proactive.py:2488-2489` (`_gather_context`, `:1708`) | **no** |
| DM telemetry block + AD-589 cache | `sovereign_id or self.id` | `cognitive/cognitive_agent.py:10283-10291` (`_build_user_message`, `:10178`) | **no** |
| Ward Room telemetry block + AD-589 cache | `sovereign_id or self.id` | `cognitive/cognitive_agent.py:10616-10624` | **no** |
| Query sub-task telemetry | `context["sovereign_id"] or agent_id` | `cognitive/sub_tasks/query.py:405-407`. **In practice slot**: nothing sets a `sovereign_id` context key (Absence A1), and `_agent_id` is `self.id` (`cognitive_agent.py:5792`, `:5982`) | yes, by accident |
| `self_query` tool | `context["agent_id"]` | `tools/self_query_tool.py:172`, `:229`. Set at `agentic_dispatch.py:3834` from `_run_reserved(agent_id=…)` (`:2667`), checked at `:2815` → `resolve_agentic_identity`, which raises unless `agent_registry.get(agent_id).id == agent_id` (`:439-449`). The registry is keyed by slot | yes (slot by construction) |
| Introspect agent | `agent.id` | `agents/introspect.py:287`, `:366` | yes |
| Trust API / agent profile | `get_score(agent.id)` | `routers/agents.py:254`, `:1228` | yes |
| Episodic recall trust weight | `get_score(<sovereign>)` | `cognitive/episodic.py:3822`, `:4911`. Callers pass `_mem_id = sovereign_id or self.id` (`cognitive_agent.py:11177`, `proactive.py:1803`) | **no** (reads 0.5 or a stray). Weight 0.10 (`episodic.py:4761`) |
| Cross-agent recall raw Beta | `get_record(peer_id)` | `cognitive/cross_agent_recall.py:168` | resolver-covered |

**The telemetry snapshot is wrong in more than its trust line.** `get_full_snapshot(id)` hands the one id to every domain (`introspective_telemetry.py:281-312`). Cognitive and temporal look the agent up with `registry.get(id)` (`:54-59`, `:146`, `:193`). Social matches Hebbian keys and trust events against it (`:227-258`). At least one Hebbian writer records slot ids: `feedback.py:88-94`, `target=agent_id` from the DAG. With a sovereign id the cognitive zone falls back to "GREEN" (`:155-156`), and the age and last-action fields are missing. The memory domain is the only one that needs the sovereign id, and it resolves that itself from the agent (`:76-82`).

### Every `record_outcome` caller (enumeration)

RUN: Grep `\.record_outcome\(` over `src/probos` (2026-10-18).

| Caller | Key passed | Form |
|---|---|---|
| `cognitive/dreaming.py:2635`, `:2656` (`_consolidate_trust`) | `episode.agent_ids` entries (`:2623`) | **sovereign** (the prime stray writer) |
| `cognitive/feedback.py:114` | `_extract_agent_ids(dag)` | slot (DAG results; converted to sovereign only for episodes, `:338-340`) |
| `cognitive/feedback.py:205` | `agent_type` | **agent_type** (sole caller `self_mod_manager.py:172`) |
| `proactive.py:1364`, `:1593` | `agent.id` | slot |
| `ward_room_router.py:1116` | `author_id` | slot (per #1597) |
| `routers/thread_fanout.py:1190` | `o.agent_id` | slot (per #1597) |
| `cognitive/counselor.py:1461`, `:1744` | event payload `data.get("agent_id")` (`:1712`) | emitter-dependent; resolver-covered |
| `cognitive/crew_synth.py:634`, `:1232`; `cognitive/ground_truth.py:516`; `avatars/divergence_detector.py:598`, `:606`; `capability_request.py:1010`; `skill_request.py:239`; `runtime.py:4633`, `:6718` | an `agent_id` variable | not traced per emitter; **resolver-covered** (any sovereign form lands on the slot) |
| `federation/peer.py:105`, `federation/bridge.py:2311` | `peer.trust_record_id` / `record_id` | peer keys; resolver returns None, so unchanged |
| `runtime.py:5128`, `substrate/device_service.py:107` | `device.trust_record_id` = `f"device:{id}"` (`device_node.py:198`) | non-identity; unchanged |
| `federation/a2a/server.py:413`, `federation/mcp_server.py:551`, `cognitive/cognitive_agent.py:3784`, `federation/bridge.py:2323` | other services' `record_outcome` | not `TrustNetwork` |
| `TrustNetwork.record_outcome_once` (`trust.py:612`, sole caller `cognitive/crew_trust.py:545`) | `effect.agent_id` bound into a receipt hash (`:619-621`, `:676`) | **left unchanged by design** (D3). The live `trust_outcome_receipts` table is empty (#1597) |

**Trust read paths** (Grep `trust\w*\.(get_score|get_record|get_events_for_agent)\(`, 66 hits). Every hit passes `agent.id`/`self.id` (slot), except: the five telemetry and episodic rows above; `introspect.py:301`/`:644` (slot); `experience/qa_panel.py:58` (`get_score(agent_type)`, finding F-c); and federation/ARD/panel peer keys (`federation_peer:…`, `experience/panels.py:913`/`:944`, `ard/trust_verifier.py:303`), which are non-identity and unchanged. With the resolver, every sovereign-form read lands on the slot record whatever the caller holds.

### Live evidence (read-only, `%LOCALAPPDATA%\ProbOS\data`, 2026-10-18)

The bridge denies sqlite, so this is **byte-level evidence, not SQL**. The Captain's SQL in the after-restart checklist is authoritative.

- **AD-280 has been deleting the strays at every start.** `data\logs\probos.log:13704`: `2026-10-18 17:23:10 … trust-reconcile removed=12 stale entries`. The same line appears at `:10451` (8 removed), `:9538` (7), `:8357` (3) and `:1189` (3), and in `probos.log.1` for August (16-23 removed per start). The load line `:13603` reads `TrustNetwork loaded 90 records`.
- **The strays at the last save are crew certificate UUIDs.** The `trust.db` primary-key index page holds exactly 8 distinct UUID keys: `d7d033d2…`, `b03d7a70…`, `3fc92188…`, `c53aef31…`, `ec9a26f0…`, `46fddc43…`, `791fec1e…`, `fd7c0aba…`. In `identity.db` all 8 are birth-certificate UUIDs (postIds data_analyst, chief_engineer, builder, counselor = Ezri, scout, systems_analyst, chief_security, first_officer). The table pages also hold `dfd9d864` (chief_training), `c270c092` (surgeon) and `2d63b7cd` (research_specialist), which are not in the index: freed cells from earlier saves [inferred]. This matches #1597's 8 stray owners.
- **No non-crew identity rows.** No `federation_peer:` or `device:` keys (Grep count 0), and no asset-UUID rows.
- **Nova** has a certificate: `295487bb-9589-47a1-8aca-f466e51949bd`, postId `chief_operations`, `identity.db:155`. Her slot mapping is `operations_officer_operations_officer_0_adb55c01 → 295487bb…` (the slot_mappings page bytes, `:79`). So `resolve_or_issue` (`agent_onboarding.py:446-456`) sets her `sovereign_id` at onboarding. **Her live agent held it in the 2026-10-18 session [inferred, strong]:** the knowledge-store snapshot holds a stray keyed `295487bb…` (α 3.1), which only a writer holding her certificate UUID creates, and episodes carry `sovereign_id or self.id` (`cognitive_agent.py:11177`, `proactive.py:1803`), so an empty `sovereign_id` would have sent her dream boosts to her slot. The finalize check (Section 5) proves it for all 16 crew at the next start; a missing one is a separate defect (amendment point 1).
- **The 0.9843 reading.** The only stored rendering of `Trust: 0.9843 (123 observations, uncertainty ±0.011)` is in `data\attachments\ac754a2a….json`: a `self_query` call with output `{'agent_id': 'counselor_counselor_0_67c601cb', …}` (Ezri's slot) at 1790044134, which is 2026-09-22T02:28Z. All 8 stored `self_query` transcripts carry slot ids (architect ×2, counselor ×6). Nova's 2026-10-19 reading cannot be attributed from stored data: no match in `ward_room.db`, `ward_room.db-wal` or `events.db`. **The value attributes the path (amendment point 1):** her slot record in the 2026-10-18 knowledge-store snapshot is (125.6625, 2.0): score 0.9843, observations α+β−4 = 123.66, Beta standard deviation 0.011, exactly her reading. With her `sovereign_id` set, the injected block would have read her stray (3.1, 2.0), 0.6078. So her reading came from a slot-keyed path (`self_query` or the query sub-task), not an injected block.
- **Two trust stores (re-probed 2026-10-19, vessel stopped).** `trust.db` was last written 2026-10-12 00:02 and still holds the 8 strays above. The 2026-10-18 start removed 12 entries in memory only (8 strays, 3 dashless-hex runtime ids, `system`), and nothing saved `trust.db` since. But warm boot force-sets every key of `knowledge/trust/snapshot.json` over the loaded records before structural services (`warm_boot.py:91-100`, `cognitive_services.py:569`; log `:13674` `Warm boot restored: trust(90 agents)` one second before `:13704`). That file is written every 60 s (`dream_adapter.py:316-338`) and at shutdown (`shutdown.py:1963`), and now holds the 2026-10-18 session's last flush: 98 keys, being 15 dashed certificate-UUID strays (the 8 above plus `dfd9d864` chief_training, `c270c092` surgeon = Meridian, `2d63b7cd` research_specialist, `295487bb` chief_operations = Nova, `82652abd` chief_medical, `3f13f012` pathologist, `71823b24` pharmacist; all 15 are birth certificates in `identity.db`), 3 dashless-hex runtime ids, `system`, `captain`, and 78 slot-shaped keys whose crew values are above `trust.db`'s (builder 46.55 → 46.80). So the 2026-10-18 session's evidence was not lost to K-21, and the merge input at the next start is this file's values, not `trust.db`'s (D6, D11, checklist). `backups/20261018-232532/data/trust.db` also exists.

### Separate findings (report on #1523, do not fold in)

- **F-a (latent):** AD-280 deletes every trust record not keyed by an active slot, so federation-peer, `mcp-peer:` and `device:` trust resets at each restart. None live.
- **F-b (latent):** `record_outcome_once` keys by `effect.agent_id` without resolution.
- **F-c:** `TrustRecord.observations` hard-codes a 2.0 prior (`trust.py:77`), so the observation count is off for AD-640 tier-prior records (`tiered_trust.py:74-83`).
- **F-d:** `experience/qa_panel.py:58` reads trust by `agent_type`.

Use the next free numbers on #1523: the highest seen is F-152 in its comments, so F-154 or later per the orchestrator; re-check at closure.

## Solution

1. **Identity registry:** add `resolve_slot_id(identity) -> str | None` (certificate UUID, agent DID or asset UUID → slot; None otherwise or when the identity is bound to more than one slot), and `is_sovereign_identity_key(key)`.
2. **TrustNetwork:** add `set_identity_resolver(fn)`. `record_outcome`, `get_score`, `get_record` and `get_events_for_agent` canonicalize the key. With no resolver, behaviour is unchanged. Add `merge_identity_records(pairs)`: one transaction that snapshots every record, merges each stray's evidence above the network prior into its slot record, deletes the stray, records the merge, and only then changes memory.
3. **Startup (`startup/trust_identity.py`, new):** `reconcile_trust_identities` binds the resolver, finds strays **by key**, merges them, writes one event-log row per merge, then runs AD-280 with the unmerged identity keys exempt. `verify_crew_trust_identity` runs at the end of finalize and logs one line covering every crew member.
4. **Telemetry:** the three injected callers and the query sub-task pass the slot id. A trust miss renders "Trust: no record for this id" and is logged once per subject, never shown as the prior.
5. **Correction feedback** (`feedback.py:205`) records on the single active agent of the type, or not at all.

## Implementation

Every SEARCH block below is verbatim from `origin/main` @ `cf08d4c9`, unique in its file. Re-verified 2026-10-19 on `02eb27bc`: all 31 pairs apply once (1a-1f, 2a-2h, 4a-4d, 5, 6a-6g, 7a-7e; Amendment A1); BF-906 did not change the text of 4d or Section 5.

### Section 1: `src/probos/identity.py`, the resolver

**1a.** SEARCH:
```python
import logging
import time
import uuid
```
REPLACE:
```python
import logging
import re
import time
import uuid
```

**1b.** SEARCH:
```python
    if len(parts) == 4:
        return {
            "method": parts[1],
            "instance_id": parts[2],
            "agent_uuid": parts[3],
            "type": "agent",
        }
    return None
```
REPLACE:
```python
    if len(parts) == 4:
        return {
            "method": parts[1],
            "instance_id": parts[2],
            "agent_uuid": parts[3],
            "type": "agent",
        }
    return None


# BF-907: the shapes a sovereign identity takes as a key: a certificate or asset-tag
# UUID v4 (generate_agent_uuid) or a did:probos agent DID. A slot id never matches.
_SOVEREIGN_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def is_sovereign_identity_key(key: str) -> bool:
    """BF-907: whether ``key`` has the shape of a sovereign identity rather than a slot id."""
    if type(key) is not str or not key:
        return False
    if key.startswith(f"did:{DID_METHOD}:"):
        return True
    return _SOVEREIGN_UUID.fullmatch(key) is not None
```

**1c.** SEARCH:
```python
        self._asset_cache: dict[str, AssetTag] = {}  # slot_id -> AssetTag
```
REPLACE:
```python
        self._asset_cache: dict[str, AssetTag] = {}  # slot_id -> AssetTag
        self._asset_slot_by_uuid: dict[str, str] = {}  # BF-907: asset_uuid -> slot_id (asset_tags.slot_id is UNIQUE)
```

**1d.** SEARCH:
```python
                    self._asset_cache[tag.slot_id] = tag

            # AD-443b: Load foreign birth certificates imported from peer ships.
```
REPLACE:
```python
                    self._asset_cache[tag.slot_id] = tag
                    self._asset_slot_by_uuid[tag.asset_uuid] = tag.slot_id

            # AD-443b: Load foreign birth certificates imported from peer ships.
```

**1e.** SEARCH:
```python
        def committed() -> None:  # BF-885 the asset tag is held once it has committed
            self._asset_cache[tag.slot_id] = tag
```
REPLACE:
```python
        def committed() -> None:  # BF-885 the asset tag is held once it has committed
            self._asset_cache[tag.slot_id] = tag
            self._asset_slot_by_uuid[tag.asset_uuid] = tag.slot_id
```

**1f.** SEARCH:
```python
    def get_by_agent_type(self, agent_type: str) -> list[AgentBirthCertificate]:
        """Return all certificates for a given agent_type."""
        return [c for c in self._uuid_cache.values() if c.agent_type == agent_type]
```
REPLACE:
```python
    def get_by_agent_type(self, agent_type: str) -> list[AgentBirthCertificate]:
        """Return all certificates for a given agent_type."""
        return [c for c in self._uuid_cache.values() if c.agent_type == agent_type]

    def resolve_slot_id(self, identity: str) -> str | None:
        """BF-907: the deployment slot a sovereign identity is bound to, or None.

        Accepts a birth-certificate UUID (native or foreign), a did:probos agent
        DID, or an asset-tag UUID. Returns None for any other key (a slot id, a
        peer or device key, an unknown id) and when a certificate is bound to
        more than one slot, so the caller keeps the key it was given. Reads the
        in-memory caches only; never raises.
        """
        if not is_sovereign_identity_key(identity):
            return None
        agent_uuid = identity
        if identity.startswith("did:"):
            parsed = parse_did(identity)
            if parsed is None or parsed.get("type") != "agent":
                return None
            agent_uuid = parsed["agent_uuid"]
        slots = [slot for slot, cert in self._slot_cache.items() if cert.agent_uuid == agent_uuid]
        if len(slots) == 1:
            return slots[0]
        if slots:
            logger.debug("BF-907: identity %s is bound to %d slots; not resolved", agent_uuid, len(slots))
            return None
        return self._asset_slot_by_uuid.get(agent_uuid)
```
Non-candidates by construction (live shapes, 2026-10-19): dashless 32-hex runtime agent ids (`BaseAgent` default `uuid.uuid4().hex`, `substrate/agent.py:42`), `system`, `captain`, and every slot id. Certificate and asset UUIDs are always dashed (`generate_agent_uuid` → `str(uuid.uuid4())`, `identity.py:114-116`, `:804`), so `fullmatch` rejects the hex form; tests 2 and 16 pin it. Performance note: `_slot_cache` holds certificate slots only (16 live). Asset lookup is O(1) because there are 4,888 asset tags live (`probos.log:13605`). Slot ids fail the shape check first.

### Section 2: `src/probos/consensus/trust.py`

**2a (schema, additive).** SEARCH:
```python
    result_alpha     REAL NOT NULL,
    result_beta      REAL NOT NULL,
    created_at       TEXT NOT NULL
);
"""
```
REPLACE:
```python
    result_alpha     REAL NOT NULL,
    result_beta      REAL NOT NULL,
    created_at       TEXT NOT NULL
);

-- BF-907: every record as it stood before an identity merge, so the merge can be reversed.
CREATE TABLE IF NOT EXISTS trust_snapshots (
    snapshot_id TEXT NOT NULL,
    agent_id    TEXT NOT NULL,
    alpha       REAL NOT NULL,
    beta        REAL NOT NULL,
    taken_at    TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, agent_id)
);

-- BF-907: one row per record merged from a sovereign-identity key into its slot record.
CREATE TABLE IF NOT EXISTS trust_key_merges (
    snapshot_id         TEXT NOT NULL,
    source_key          TEXT NOT NULL,
    target_key          TEXT NOT NULL,
    source_alpha        REAL NOT NULL,
    source_beta         REAL NOT NULL,
    target_alpha_before REAL NOT NULL,
    target_beta_before  REAL NOT NULL,
    alpha_after         REAL NOT NULL,
    beta_after          REAL NOT NULL,
    prior_alpha         REAL NOT NULL,
    prior_beta          REAL NOT NULL,
    merged_at           TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, source_key)
);
"""
```

**2b.** SEARCH:
```python
            or self.beta <= 0.0
        ):
            raise ValueError("trust_outcome_result_invalid")
```
REPLACE:
```python
            or self.beta <= 0.0
        ):
            raise ValueError("trust_outcome_result_invalid")


@dataclass(frozen=True, slots=True)
class TrustKeyMerge:
    """BF-907: one record merged from a sovereign-identity key into its slot record.

    The evidence above the network prior moves and the prior is counted once:
    ``alpha_after = target_alpha_before + (source_alpha - prior_alpha)``,
    and the same for beta. The slot keeps its own prior.
    """

    snapshot_id: str
    source_key: str
    target_key: str
    source_alpha: float
    source_beta: float
    target_alpha_before: float
    target_beta_before: float
    alpha_after: float
    beta_after: float
    prior_alpha: float
    prior_beta: float
    merged_at: str
```

**2c.** SEARCH:
```python
        self._floor_hit_count: int = 0
        self._tier_registry: Any = None
```
REPLACE:
```python
        self._floor_hit_count: int = 0
        self._tier_registry: Any = None
        self._resolve_identity: Callable[[str], str | None] | None = None  # BF-907
```

**2d.** SEARCH:
```python
    def set_tier_registry(self, registry: Any) -> None:
        """Inject agent tier registry for tier-aware filtering (AD-571)."""
        self._tier_registry = registry
```
REPLACE:
```python
    def set_tier_registry(self, registry: Any) -> None:
        """Inject agent tier registry for tier-aware filtering (AD-571)."""
        self._tier_registry = registry

    def set_identity_resolver(self, fn: Callable[[str], str | None]) -> None:
        """BF-907: inject sovereign-identity -> slot-id resolution for trust keys.

        Called once at startup with ``AgentIdentityRegistry.resolve_slot_id``.
        Records are keyed by slot id; a caller holding a certificate UUID, an
        agent DID or an asset-tag UUID reads and writes the slot record.
        """
        self._resolve_identity = fn

    def _canonical_key(self, agent_id: AgentID) -> AgentID:
        """BF-907: the slot id for a sovereign identity; any other key unchanged."""
        resolver = self._resolve_identity
        if resolver is None:
            return agent_id
        slot_id = resolver(agent_id)
        return slot_id if type(slot_id) is str and slot_id else agent_id
```

**2e.** SEARCH:
```python
        self._require_sync_mutation_available()
        outcome = _TrustOutcomeInput(
            agent_id=agent_id,
            success=success,
```
REPLACE:
```python
        self._require_sync_mutation_available()
        outcome = _TrustOutcomeInput(
            agent_id=self._canonical_key(agent_id),  # BF-907: the slot record, whatever form the caller holds
            success=success,
```
(Dampening, the tier skip, the `TrustEvent` and its emissions all key off this id in `_plan_outcome`, `:344-…`, so they follow the slot as well.)

**2f.** SEARCH:
```python
    def get_score(self, agent_id: AgentID) -> float:
        """Get an agent's current trust score."""
        record = self._records.get(agent_id)
        if record is None:
            return self.prior_alpha / (self.prior_alpha + self.prior_beta)
        return record.score

    def get_record(self, agent_id: AgentID) -> TrustRecord | None:
        """Get the full trust record for an agent."""
        return self._records.get(agent_id)
```
REPLACE:
```python
    def get_score(self, agent_id: AgentID) -> float:
        """Get an agent's current trust score (BF-907: a sovereign identity reads its slot)."""
        record = self._records.get(self._canonical_key(agent_id))
        if record is None:
            return self.prior_alpha / (self.prior_alpha + self.prior_beta)
        return record.score

    def get_record(self, agent_id: AgentID) -> TrustRecord | None:
        """Get the full trust record for an agent (BF-907: a sovereign identity reads its slot)."""
        return self._records.get(self._canonical_key(agent_id))
```

**2g.** SEARCH:
```python
        """Return last N trust events for a specific agent."""
        filtered = [e for e in self._event_log if e.agent_id == agent_id]
        return filtered[-n:]
```
REPLACE:
```python
        """Return last N trust events for a specific agent (BF-907: by slot id)."""
        key = self._canonical_key(agent_id)
        filtered = [e for e in self._event_log if e.agent_id == key]
        return filtered[-n:]
```

**2h.** SEARCH:
```python
    async def save(self) -> None:
        """Manually trigger a save to disk."""
        await self._save_to_db()
```
REPLACE (append the method):
```python
    async def save(self) -> None:
        """Manually trigger a save to disk."""
        await self._save_to_db()

    async def merge_identity_records(
        self, pairs: dict[str, str],
    ) -> tuple[tuple[TrustKeyMerge, ...], dict[str, str]]:
        """BF-907: merge records keyed by a sovereign identity into their slot records.

        ``pairs`` maps each source key to its slot id. A source was created by
        ``record_outcome`` from the network prior (``_plan_outcome``), so its
        evidence above that prior moves to the slot and the prior is counted
        once; the slot keeps its own (possibly tiered) prior. One trust.db
        transaction snapshots every in-memory record, writes each target row,
        deletes each source row and records each merge; memory changes only
        after the commit. Returns the merges and the refused sources with a
        reason (left untouched). Raises when the store is not started or the
        write fails; the transaction is rolled back and nothing changes.
        """
        self._require_sync_mutation_available()
        if self._db is None:
            raise RuntimeError("trust_store_not_started")
        refused: dict[str, str] = {}
        merged_at = datetime.now(timezone.utc).isoformat()
        snapshot_id = f"bf907-{merged_at}"
        tolerance = 1e-9
        planned: dict[str, tuple[float, float]] = {}
        merges: list[TrustKeyMerge] = []
        for source_key, target_key in sorted(pairs.items()):
            source = self._records.get(source_key)
            if source is None:
                refused[source_key] = "source_missing"
                continue
            if target_key == source_key:
                refused[source_key] = "target_is_source"
                continue
            evidence_alpha = source.alpha - self.prior_alpha
            evidence_beta = source.beta - self.prior_beta
            if evidence_alpha < -tolerance or evidence_beta < -tolerance:
                refused[source_key] = "below_prior"
                continue
            if target_key in planned:
                before = planned[target_key]
            else:
                target = self._records.get(target_key)
                before = (
                    (target.alpha, target.beta) if target is not None
                    else (self.prior_alpha, self.prior_beta)
                )
            alpha_after = before[0] + max(evidence_alpha, 0.0)
            beta_after = before[1] + max(evidence_beta, 0.0)
            planned[target_key] = (alpha_after, beta_after)
            merges.append(TrustKeyMerge(
                snapshot_id=snapshot_id, source_key=source_key, target_key=target_key,
                source_alpha=source.alpha, source_beta=source.beta,
                target_alpha_before=before[0], target_beta_before=before[1],
                alpha_after=alpha_after, beta_after=beta_after,
                prior_alpha=self.prior_alpha, prior_beta=self.prior_beta,
                merged_at=merged_at,
            ))
        if not merges:
            return (), refused
        async with self._lock:
            self._outcome_transaction_inflight = True
            try:
                await self._db.execute("BEGIN IMMEDIATE")
                try:
                    await self._db.executemany(
                        "INSERT INTO trust_snapshots (snapshot_id, agent_id, alpha, beta, taken_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        [(snapshot_id, r.agent_id, r.alpha, r.beta, merged_at) for r in self._records.values()],
                    )
                    for target_key, (alpha, beta) in planned.items():
                        await self._db.execute(
                            "INSERT OR REPLACE INTO trust_scores (agent_id, alpha, beta, updated) "
                            "VALUES (?, ?, ?, ?)",
                            (target_key, alpha, beta, merged_at),
                        )
                    for merge in merges:
                        await self._db.execute("DELETE FROM trust_scores WHERE agent_id = ?", (merge.source_key,))
                        await self._db.execute(
                            "INSERT INTO trust_key_merges (snapshot_id, source_key, target_key, "
                            "source_alpha, source_beta, target_alpha_before, target_beta_before, "
                            "alpha_after, beta_after, prior_alpha, prior_beta, merged_at) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                            (merge.snapshot_id, merge.source_key, merge.target_key,
                             merge.source_alpha, merge.source_beta,
                             merge.target_alpha_before, merge.target_beta_before,
                             merge.alpha_after, merge.beta_after,
                             merge.prior_alpha, merge.prior_beta, merge.merged_at),
                        )
                    await self._db.commit()
                except Exception:
                    await self._db.execute("ROLLBACK")
                    raise
                for merge in merges:
                    self._records.pop(merge.source_key, None)
                for target_key, (alpha, beta) in planned.items():
                    record = self._records.get(target_key)
                    if record is None:
                        self._records[target_key] = TrustRecord(agent_id=target_key, alpha=alpha, beta=beta)
                    else:
                        record.alpha = alpha
                        record.beta = beta
            finally:
                self._outcome_transaction_inflight = False
        return tuple(merges), refused
```

### Section 3: `src/probos/startup/trust_identity.py` (new)

```python
"""BF-907: trust records keyed by a sovereign identity are merged into the slot record.

Trust is keyed by slot id. Before BF-907, writers holding the sovereign UUID that
episodes carry (dream consolidation first among them) created separate records,
and AD-280's startup reconcile deleted them at the next start. At startup this
module binds trust to the identity registry, merges every record still keyed by a
sovereign identity into its slot, then runs AD-280 with unmerged identity keys
kept. ``verify_crew_trust_identity`` checks every crew member after startup.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from probos.config import format_trust
from probos.identity import is_sovereign_identity_key

if TYPE_CHECKING:
    from probos.cognitive.introspective_telemetry import IntrospectiveTelemetryService
    from probos.consensus.trust import TrustKeyMerge, TrustNetwork
    from probos.identity import AgentIdentityRegistry
    from probos.substrate.event_log import EventLog
    from probos.substrate.registry import AgentRegistry

logger = logging.getLogger(__name__)

# BF-907 (D13): the merge event's name. A module constant, so AD-1195's census
# resolves ('trust', 'trust_identity_merge') and freezes it as a resolved pair.
MERGE_EVENT = "trust_identity_merge"


@dataclass(frozen=True, slots=True)
class TrustStoreReconciliation:
    """What the startup trust reconcile did."""

    merged: tuple[TrustKeyMerge, ...]
    kept: dict[str, str]  # identity key -> reason it was not merged
    removed: int  # AD-280 stale entries removed


async def reconcile_trust_identities(
    *,
    trust_network: TrustNetwork,
    identity_registry: AgentIdentityRegistry,
    active_ids: set[str],
    event_log: EventLog,
) -> TrustStoreReconciliation:
    """Bind, merge identity-keyed records by key, then remove stale entries (AD-280)."""
    trust_network.set_identity_resolver(identity_registry.resolve_slot_id)
    pairs: dict[str, str] = {}
    kept: dict[str, str] = {}
    for key in trust_network.raw_scores():
        if key in active_ids or not is_sovereign_identity_key(key):
            continue
        slot_id = identity_registry.resolve_slot_id(key)
        if slot_id is None:
            kept[key] = "unresolved"
        elif slot_id not in active_ids:
            kept[key] = "slot_inactive"
        else:
            pairs[key] = slot_id
    merged: tuple[TrustKeyMerge, ...] = ()
    if pairs:
        try:
            merged, refused = await trust_network.merge_identity_records(pairs)
        except Exception:
            logger.error(
                "BF-907: trust identity merge failed and was rolled back; %d records keyed "
                "by a sovereign identity are kept unmerged for the next start",
                len(pairs), exc_info=True,
            )
            kept.update(dict.fromkeys(pairs, "merge_failed"))
        else:
            kept.update(refused)
            for merge in merged:
                await _record_merge_event(event_log, merge)
    for key, reason in sorted(kept.items()):
        logger.warning("BF-907: trust record %s kept unmerged (%s)", key, reason)
    logger.info("BF-907 trust identity merge: merged=%d kept=%d", len(merged), len(kept))
    removed = trust_network.reconcile(active_ids | frozenset(kept))
    return TrustStoreReconciliation(merged=merged, kept=kept, removed=removed)


async def _record_merge_event(event_log: EventLog, merge: TrustKeyMerge) -> None:
    """One event per merge, so trend analyses can mark the step (log-and-degrade)."""
    try:
        await event_log.log(
            category="trust",
            event=MERGE_EVENT,
            agent_id=merge.target_key,
            detail=f"BF-907: {merge.source_key} merged into {merge.target_key}",
            data={
                "source_key": merge.source_key,
                "target_key": merge.target_key,
                "delta_alpha": merge.alpha_after - merge.target_alpha_before,
                "delta_beta": merge.beta_after - merge.target_beta_before,
                "alpha_before": merge.target_alpha_before,
                "beta_before": merge.target_beta_before,
                "alpha_after": merge.alpha_after,
                "beta_after": merge.beta_after,
                "merged_at": merge.merged_at,
                "snapshot_id": merge.snapshot_id,
            },
        )
    except Exception:
        logger.warning(
            "BF-907: merge event for %s was not written; trust.db trust_key_merges "
            "holds the record (snapshot %s)", merge.source_key, merge.snapshot_id, exc_info=True,
        )


async def verify_crew_trust_identity(
    *,
    trust_network: TrustNetwork,
    identity_registry: AgentIdentityRegistry,
    registry: AgentRegistry,
    telemetry: IntrospectiveTelemetryService | None,
) -> tuple[int, tuple[str, ...]]:
    """BF-907: every crew member's telemetry trust equals its header trust.

    Crew are the registered agents whose slot holds a birth certificate. A
    missing or mismatched sovereign_id is reported here, not repaired.
    Returns (crew count, problems).
    """
    keys = set(trust_network.raw_scores())
    crew = 0
    inconsistent = 0
    problems: list[str] = []
    for agent in registry.all():
        cert = identity_registry.get_by_slot(agent.id)
        if cert is None:
            continue
        crew += 1
        name = cert.callsign or agent.id
        found: list[str] = []
        if agent.sovereign_id != cert.agent_uuid:
            found.append(f"{name}: sovereign_id {agent.sovereign_id!r} is not its certificate {cert.agent_uuid}")
        if cert.agent_uuid in keys or cert.did in keys:
            found.append(f"{name}: a trust record is still keyed by its sovereign identity")
        header = format_trust(trust_network.get_score(agent.id))
        state = await telemetry.get_trust_state(agent.id) if telemetry is not None else {}
        if state.get("score") != header or "observations" not in state:
            found.append(f"{name}: telemetry trust {state.get('score', 'no record')} is not header {header}")
        if found:
            inconsistent += 1
            problems.extend(found)
    if problems:
        logger.warning(
            "BF-907 trust identity check: crew=%d consistent=%d; %s",
            crew, crew - inconsistent, "; ".join(problems),
        )
    else:
        logger.info("BF-907 trust identity check: crew=%d consistent=%d", crew, crew)
    return crew, tuple(problems)
```

### Section 4: `src/probos/startup/structural_services.py` and `src/probos/runtime.py`

**4a.** SEARCH:
```python
if TYPE_CHECKING:
    from probos.cognitive.emergent_detector import EmergentDetector
    from probos.config import SystemConfig
    from probos.consensus.trust import TrustNetwork
```
REPLACE:
```python
if TYPE_CHECKING:
    from probos.cognitive.emergent_detector import EmergentDetector
    from probos.config import SystemConfig
    from probos.consensus.trust import TrustNetwork
    from probos.identity import AgentIdentityRegistry
    from probos.substrate.event_log import EventLog
```

**4b.** SEARCH:
```python
    trust_network: "TrustNetwork",
    intent_bus: "IntentBus",
```
REPLACE:
```python
    trust_network: "TrustNetwork",
    identity_registry: "AgentIdentityRegistry",
    event_log: "EventLog",
    intent_bus: "IntentBus",
```

**4c.** SEARCH:
```python
    # Reconcile trust store — remove stale entries from previous sessions (AD-280)
    active_ids = {a.id for a in registry.all()}
    removed = trust_network.reconcile(active_ids)
    if removed:
        logger.info("trust-reconcile removed=%d stale entries", removed)
```
REPLACE:
```python
    # Reconcile trust store — remove stale entries from previous sessions (AD-280).
    # BF-907: first bind trust to the identity registry and merge every record still
    # keyed by a sovereign identity into its slot; unmerged identity keys are kept.
    from probos.startup.trust_identity import reconcile_trust_identities

    active_ids = {a.id for a in registry.all()}
    trust_reconciliation = await reconcile_trust_identities(
        trust_network=trust_network,
        identity_registry=identity_registry,
        active_ids=active_ids,
        event_log=event_log,
    )
    if trust_reconciliation.removed:
        logger.info("trust-reconcile removed=%d stale entries", trust_reconciliation.removed)
```

**4d.** `runtime.py` SEARCH:
```python
            trust_network=self.trust_network,
            intent_bus=self.intent_bus,
            hebbian_router=self.hebbian_router,
            episodic_memory=self.episodic_memory,
            emergent_detector=self._emergent_detector,
```
REPLACE:
```python
            trust_network=self.trust_network,
            identity_registry=self.identity_registry,
            event_log=self.event_log,
            intent_bus=self.intent_bus,
            hebbian_router=self.hebbian_router,
            episodic_memory=self.episodic_memory,
            emergent_detector=self._emergent_detector,
```
Order is safe because `self.identity_registry` is set at `runtime.py:2757` and `self.event_log` at `:699`, started at `startup/infrastructure.py:80`. Both are before `:3113` (line numbers on `02eb27bc`).

### Section 5: `src/probos/startup/finalize.py`, the crew check

SEARCH:
```python
    logger.info("Startup [finalize]: complete")
    return FinalizationResult(
```
REPLACE:
```python
    # BF-907: every crew member's telemetry trust equals its header trust.
    try:
        from probos.startup.trust_identity import verify_crew_trust_identity

        await verify_crew_trust_identity(
            trust_network=runtime.trust_network,
            identity_registry=runtime.identity_registry,
            registry=runtime.registry,
            telemetry=runtime.introspective_telemetry,
        )
    except Exception:
        logger.warning("BF-907: the crew trust identity check failed to run; startup continues", exc_info=True)

    logger.info("Startup [finalize]: complete")
    return FinalizationResult(
```
(`runtime.introspective_telemetry` is the public property at `runtime.py:600-601`. The check runs after `communication.py:895-921` has issued deferred crew certificates.)

### Section 6: telemetry

**6a.** `cognitive/introspective_telemetry.py` SEARCH:
```python
    def __init__(self, *, runtime: Any) -> None:
        self._runtime = runtime
```
REPLACE:
```python
    def __init__(self, *, runtime: Any) -> None:
        self._runtime = runtime
        self._trust_misses: set[str] = set()  # BF-907: subjects whose missing trust record was logged
```

**6b.** SEARCH:
```python
            trust_net = rt.trust_network
            try:
                result["score"] = format_trust(trust_net.get_score(agent_id))
                record = trust_net.get_record(agent_id)
                if record:
                    result["observations"] = int(record.observations)
                    result["uncertainty"] = format_trust(record.uncertainty)
```
REPLACE:
```python
            trust_net = rt.trust_network
            try:
                record = trust_net.get_record(agent_id)
                if record is None:
                    # BF-907: a miss is reported as a miss, never as the prior's plausible 0.5.
                    result["record"] = "missing"
                    if agent_id not in self._trust_misses:
                        self._trust_misses.add(agent_id)
                        logger.warning(
                            "BF-907: no trust record for %s; telemetry reports the miss, not the prior",
                            agent_id,
                        )
                else:
                    result["score"] = format_trust(trust_net.get_score(agent_id))
                    result["observations"] = int(record.observations)
                    result["uncertainty"] = format_trust(record.uncertainty)
```

**6c.** SEARCH:
```python
            else:
                lines.append("Trust: no record yet")
```
REPLACE:
```python
            else:
                lines.append("Trust: no record for this id")
```

**6d.** `proactive.py` SEARCH:
```python
                _agent_id = getattr(agent, 'sovereign_id', None) or agent.id
                _snapshot = await _telemetry_svc.get_full_snapshot(_agent_id)
```
REPLACE:
```python
                # BF-907: the slot id; the memory domain resolves the sovereign id itself.
                _snapshot = await _telemetry_svc.get_full_snapshot(agent.id)
```

**6e.** `cognitive/cognitive_agent.py`, the DM path. SEARCH:
```python
                    _agent_id = getattr(self, 'sovereign_id', None) or self.id
                    _snapshot = await _telemetry_svc.get_full_snapshot(_agent_id)
                    _telemetry_text = _telemetry_svc.render_telemetry_context(_snapshot)
                    if _telemetry_text:
                        _emit("telemetry", [_telemetry_text, ""])
```
REPLACE:
```python
                    _snapshot = await _telemetry_svc.get_full_snapshot(self.id)  # BF-907: slot id (DM)
                    _telemetry_text = _telemetry_svc.render_telemetry_context(_snapshot)
                    if _telemetry_text:
                        _emit("telemetry", [_telemetry_text, ""])
```

**6f.** The Ward Room path. SEARCH:
```python
                    _agent_id = getattr(self, 'sovereign_id', None) or self.id
                    _snapshot = await _telemetry_svc.get_full_snapshot(_agent_id)
                    _telemetry_text = _telemetry_svc.render_telemetry_context(_snapshot)
                    if _telemetry_text:
                        _emit("telemetry", ["", _telemetry_text])
```
REPLACE:
```python
                    _snapshot = await _telemetry_svc.get_full_snapshot(self.id)  # BF-907: slot id (WR)
                    _telemetry_text = _telemetry_svc.render_telemetry_context(_snapshot)
                    if _telemetry_text:
                        _emit("telemetry", ["", _telemetry_text])
```

**6g.** `cognitive/sub_tasks/query.py` SEARCH:
```python
        agent_id = context.get("_agent_id", "") or _ctx(context, "agent_id")
        sovereign_id = context.get("sovereign_id", "") or agent_id
        snapshot = await telemetry_svc.get_full_snapshot(sovereign_id)
```
REPLACE:
```python
        agent_id = context.get("_agent_id", "") or _ctx(context, "agent_id")
        # BF-907: the slot id; the memory domain resolves the sovereign id itself.
        snapshot = await telemetry_svc.get_full_snapshot(agent_id)
```

### Section 7: correction feedback by agent type

**7a.** `cognitive/feedback.py` SEARCH:
```python
    from probos.substrate.event_log import EventLog
    from probos.types import TaskDAG, TaskNode
```
REPLACE:
```python
    from probos.substrate.event_log import EventLog
    from probos.substrate.registry import AgentRegistry
    from probos.types import TaskDAG, TaskNode
```

**7b.** SEARCH:
```python
        feedback_trust_weight: float = 1.5,
        identity_registry: Any = None,
    ) -> None:
```
REPLACE:
```python
        feedback_trust_weight: float = 1.5,
        identity_registry: Any = None,
        agent_registry: AgentRegistry | None = None,
    ) -> None:
```

**7c.** SEARCH:
```python
        self._identity_registry = identity_registry

    async def _safe_log_event(self, event_log, *args, **kwargs) -> None:
```
REPLACE:
```python
        self._identity_registry = identity_registry
        self._agent_registry = agent_registry  # BF-907: agent_type -> slot for correction trust

    async def _safe_log_event(self, event_log, *args, **kwargs) -> None:
```

**7d.** SEARCH (`:202-214`):
```python
        # 2. Trust — small positive if retry succeeded
        if retry_success and agent_type:
            try:
                self._trust.record_outcome(agent_type, success=True)
            except RuntimeError as exc:
                if str(exc) != "trust_write_in_progress":
                    raise
                logger.warning(
                    "AD-1130: Correction trust observation skipped for agent=%s "
                    "because a durable trust write is in progress; Hebbian and "
                    "episodic correction processing continue",
                    agent_type,
                )
```
REPLACE:
```python
        # 2. Trust — small positive if retry succeeded. BF-907: trust is keyed by
        # slot id, so the observation lands on the one active agent of this type;
        # with none or several it is not recorded (Hebbian and episodic go on).
        if retry_success and agent_type:
            target_ids = (
                [agent.id for agent in self._agent_registry.all() if agent.agent_type == agent_type]
                if self._agent_registry is not None else []
            )
            if len(target_ids) != 1:
                logger.warning(
                    "BF-907: correction trust observation for agent_type=%s not recorded: "
                    "%d active agents of that type, needs exactly one; Hebbian and "
                    "episodic correction processing continue",
                    agent_type, len(target_ids),
                )
            else:
                try:
                    self._trust.record_outcome(target_ids[0], success=True)
                except RuntimeError as exc:
                    if str(exc) != "trust_write_in_progress":
                        raise
                    logger.warning(
                        "AD-1130: Correction trust observation skipped for agent=%s "
                        "because a durable trust write is in progress; Hebbian and "
                        "episodic correction processing continue",
                        target_ids[0],
                    )
```

**7e.** `startup/cognitive_services.py` SEARCH:
```python
        event_log=event_log,
        identity_registry=identity_registry,
    )
```
(Verify it is unique in the file; if not, widen the block to start at `feedback_engine = FeedbackEngine(`.) REPLACE:
```python
        event_log=event_log,
        identity_registry=identity_registry,
        agent_registry=registry,
    )
```
(`registry` is the `init_cognitive_services` parameter at `:168`.)

### Section 8: updated tests (each change carries an inline `# BF-907:` reason; none deleted)

| Test | Today it pins | Change |
|---|---|---|
| `tests/test_ad588_telemetry_introspection.py:345-355` `test_get_trust_state_no_record` | the prior 0.5 shown for a missing record (the defect) | assert `"score" not in result` and `result["record"] == "missing"` |
| same file `:493` (`test_get_full_snapshot_partial_failure`) | `snap["trust"]["score"] == 0.5` with no record | assert `snap["trust"]["record"] == "missing"` |
| same file `:768` | "no record yet" | "no record for this id" |
| `tests/test_ad1258_self_knowledge.py:226` | `"Trust: no record yet"` | `"Trust: no record for this id"` |
| `tests/test_feedback_engine.py:83-96` `_engine` and `:355-405` | a write keyed by `agent_type` | `_engine(agent_registry=…)` with one agent `SimpleNamespace(id="agent-1-slot", agent_type="agent-1")`; the propagation test still raises; add an assert that `record_outcome` was called with `"agent-1-slot"` |

**Amendment A1 rows (2026-10-19; found by the whole-contract dry run; the test edits are for the Builder and each carries a `# BF-907:` reason).**

| A1 | Milestone | File | Edit |
|---|---|---|---|
| A1.1 | M1 | `docs/development/store-baseline.yaml` | Run `scripts/check_store_registry.py --update-baseline`. The diff is exactly `+  - trust_key_merges` (before `trust_outcome_receipts`) and `+  - trust_snapshots` (after `trust_scores`). |
| A1.2 | M2 | `tests/test_ad1195_eventlog_pair_freeze.py:108-111` | SEARCH `    ('tool', 'tool_record_budget_exhausted'),\n    ('tool', 'tool_started'),\n})`. REPLACE: the same two lines, then `    # BF-907 (#1597): a trust record merged from a sovereign-identity key into its slot,\n    # through MERGE_EVENT. Best effort: trust.db trust_key_merges is authoritative.\n    ('trust', 'trust_identity_merge'),\n})`. |
| A1.3 | M3 | `tests/test_ad1258_self_knowledge.py` | (a) SEARCH `@dataclass\nclass _FakeTrustNetwork:` and insert before it `@dataclass(frozen=True)\nclass _FakeTrustRecord:\n    """BF-907: the fields telemetry reads (as test_ad1259…:63-66)."""\n\n    observations: int = 7\n    uncertainty: float = 0.123456\n\n\n`. (b) SEARCH `    def get_record(self, agent_id: str) -> None:\n        self.record_subjects.append(agent_id)\n        return None`. REPLACE: `    def get_record(self, agent_id: str) -> _FakeTrustRecord \| None:\n        # BF-907: telemetry scores only a subject with a record; a known subject has one.\n        self.record_subjects.append(agent_id)\n        return _FakeTrustRecord() if agent_id in self.scores else None`. (c) Replace all 4 occurrences of the literal `"Trust: 0.5124\n"` (`:338`, `:1675`, `:1721`, `:1751`) with `"Trust: 0.5124 (7 observations, uncertainty \u00b10.1235)\n"`. (d) SEARCH `        "_agent_id": "transient-agent",\n        "sovereign_id": subject,`. REPLACE: `        # BF-907: telemetry's subject is the slot id; the sovereign id differs (it was the subject: the defect).\n        "_agent_id": subject,\n        "sovereign_id": "query-consumer-sovereign",`. Fixes the 6 tests. |
| A1.4 | M3 | `tests/test_ad1260_wellness_domain.py` | (a) SEARCH `    def get_record(self, agent_id: str) -> None:\n        return None`. REPLACE: `    def get_record(self, agent_id: str) -> Any:\n        # BF-907: telemetry scores only a subject with a record; a known subject has one.\n        return SimpleNamespace(observations=7, uncertainty=0.123456) if agent_id in self.scores else None`. (b) SEARCH `        "_agent_id": "transient-slot", "sovereign_id": _SUBJECT,`. REPLACE: `        # BF-907: the slot id is telemetry's subject; the sovereign id differs.\n        "_agent_id": _SUBJECT, "sovereign_id": "sovereign-of-subject",`. Fixes the 5 tests (`SimpleNamespace` and `Any` are already imported at `:10-11`). |
| A1.5 | M3 | `tests/test_correction_runtime.py:420-435` | SEARCH `        engine = FeedbackEngine(trust_network=trust, hebbian_router=hebbian)\n\n        baseline = trust.get_score("fetch_news")`. REPLACE: `        # BF-907: trust is keyed by slot id; the one active agent of the type receives it.\n        registry = MagicMock(spec=AgentRegistry)\n        registry.all.return_value = [MagicMock(id="fetch_news-slot", agent_type="fetch_news")]\n        engine = FeedbackEngine(trust_network=trust, hebbian_router=hebbian, agent_registry=registry)\n\n        baseline = trust.get_score("fetch_news-slot")`. Then SEARCH `        assert trust.get_score("fetch_news") > baseline` and REPLACE: `        assert trust.get_score("fetch_news-slot") > baseline\n        assert trust.get_record("fetch_news") is None  # BF-907: no record keyed by the type`. (`MagicMock` and `AgentRegistry` are imported at `:7` and `:23`.) |
| A1.6 | M3 | `tests/test_feedback_engine.py:353-405` (clarifies the existing row) | Both correction tests pass the one-agent registry. The busy test also asserts `trust.record_outcome.assert_called_once_with("agent-1-slot", success=True)`; without that it passes without testing anything. |

Note: `tests/test_ad588_telemetry_introspection.py:547` sets `agent.sovereign_id = agent.id`, which is why the split was invisible. The new tests always use distinct ids.

## Tests: `tests/test_bf907_trust_identity.py`

Use a real `TrustNetwork(db_path=tmp/"trust.db")` with `await start()`, a real `AgentIdentityRegistry(data_dir=tmp)` started as `tests/test_ad1196_did_key_binding.py:278-282` does (`start()`, then `start(instance_id=…, vessel_name=…, version="1")`, then `resolve_or_issue(...)`, `resolve_or_issue_asset_tag(...)`), and a real `EventLog(db_path=tmp/"events.db")`. The fixture uses the **live row shapes**: slot ids `surgeon_medical_surgeon_0_b2321292` and `counselor_counselor_0_67c601cb`, UUID-v4 keys from issued certificates, stray `(2.48, 2.0)`, `(2.1, 2.0)`, `(2.58, 2.0)`, and slot records near `(95.0, 3.0)`. It is never the live file.

1. `test_resolve_slot_id_maps_certificate_did_and_asset_uuid`
2. `test_resolve_slot_id_returns_none_for_slot_peer_unknown_and_ambiguous` (the ambiguous case uses `reassign_slot` to bind a second slot; also asserts `is_sovereign_identity_key` is False and `resolve_slot_id` is None for the live non-candidate shapes `24ca56be31064c24a102afbceaff6636`, `system`, `captain`, `calculator_calculator_0_<hex8>`)
3. `test_resolve_slot_id_survives_registry_restart` (asset index rebuilt by `start`)
4. `test_trust_reads_by_sovereign_identity_return_the_slot_record` (`get_score`, `get_record`, `get_events_for_agent` by UUID and by DID equal the slot's, including observation count)
5. `test_record_outcome_by_sovereign_identity_moves_the_slot_record_and_creates_no_stray`
6. `test_trust_without_resolver_is_unchanged` (backward compatibility)
7. **`test_dream_consolidation_with_sovereign_episode_ids_moves_slot_score_and_header_and_telemetry_agree`** (the seam). Run `reconcile_trust_identities`. Build `DreamingEngine` as `tests/test_trust_concurrency.py:220-242` does, with `config.trust_boost=0.1` and the real `TrustNetwork`. Feed two successful `Episode(agent_ids=[sovereign])`. Assert the **slot** α rose, no sovereign key exists, the header (`CognitiveAgent._sensorium_agent_metrics`, agent built as `test_ad588…:540-568` but with `id != sovereign_id`; Builder reads `cognitive_agent.py:8880-8918` for its needs) shows `format_trust(get_score(slot))`, and the rendered telemetry from `IntrospectiveTelemetryService.get_full_snapshot(slot)` shows the same score with observations.
8. `test_merge_counts_the_prior_once`: slot `(5.0, 2.0)`, stray `(2.48, 2.0)`, prior `(2, 2)` → `(5.48, 2.0)`, score 0.7326. Also assert ≠ `(7.48, 4.0)` (prior counted twice, 0.6516).
9. `test_merge_keeps_a_probationary_slot_prior`: slot `create_with_prior(1.0, 3.0)`, stray `(2.2, 2.0)` → `(1.2, 3.0)`. Subtracting the slot's prior would give `(2.2, 2.0)`.
10. `test_merge_two_sources_one_target` (UUID and DID strays; the second merge's *before* equals the first's *after*)
11. `test_merge_refuses_a_source_below_the_prior` (`(1.9, 2.0)` → `below_prior`, untouched, kept)
12. `test_merge_snapshot_holds_every_record_and_the_restore_sql_reverses_it` (runs the restore SQL below on the closed db file; `trust_scores` equals the pre-merge rows)
13. `test_merge_persists_and_a_rerun_is_a_noop`: a second `reconcile_trust_identities` in the same process, then after `stop()` and a new network `start()`. Merged 0, no new `trust_snapshots`/`trust_key_merges`/event rows, values unchanged.
14. `test_merge_event_recorded_in_event_log` (also asserts `MERGE_EVENT == "trust_identity_merge"` against the literal) (category `trust`, event `trust_identity_merge`, data fields, `merged_at` equals the `trust_key_merges` row)
15. `test_unmapped_identity_record_is_kept_and_reported` (unknown UUID → `unresolved`; certificate of an inactive slot → `slot_inactive`; both survive AD-280; WARNING per key)
16. `test_non_identity_stale_keys_are_still_removed_by_ad280` (fixture holds a dashless-hex key, `system` and `captain` at (2.0, 2.0) beside an active tool slot: all three are removed, the tool slot stays, and the log reads `kept=0`)
17. `test_merge_failure_rolls_back_and_keeps_records`. Wrap the connection so the `trust_key_merges` insert raises. File and memory are unchanged, the reason is `merge_failed`, and an ERROR is logged.
18. `test_unaffected_vessel_writes_nothing` (no strays → merged 0, no snapshot rows, no event)
19. `test_telemetry_differs_from_header_until_bound` (the red-without-fix contrast: a stray present and no resolver gives telemetry ≠ header; after `reconcile_trust_identities` they are equal)
20. `test_crew_check_reports_a_consistent_crew` (exact INFO line `BF-907 trust identity check: crew=3 consistent=3`)
21. `test_crew_check_reports_mismatch_and_missing_sovereign_id`
22. `test_telemetry_trust_miss_is_marked_not_prior` (no `score`; renders `Trust: no record for this id`; one WARNING across two calls)
23. `test_injected_telemetry_uses_the_slot_id[proactive|dm|wr|query]` (`get_full_snapshot` awaited with the slot id while `sovereign_id` differs; the query case sets a `sovereign_id` context key; patterns at `test_ad588…:571-660`)
24. `test_ad589_cached_snapshot_trust_equals_get_score` (DM path, real service and real network: `wm._last_telemetry_snapshot["trust"]["score"] == format_trust(tn.get_score(agent.id))`)
25. `test_correction_trust_lands_on_the_single_slot_of_the_type`
26. `test_correction_trust_with_zero_or_several_agents_of_the_type_records_nothing`
27. `test_memory_domain_still_counts_by_sovereign_id_given_the_slot` (guards Section 6 against the AD-1259 contract, `tests/test_ad1259_one_source_of_truth.py:205-249`)
28. `test_warm_boot_restore_of_a_pre_merge_snapshot_re_merges_to_the_same_values` (D11). Merge, `stop()`, then a new network `start()` on the same file. Run the real `WarmBootService.restore()` (`warm_boot.py:46-101`) with a stub knowledge store whose `load_trust_snapshot` returns the pre-merge `raw_scores()` and whose other loaders return None, then `reconcile_trust_identities`. Assert the slot values equal the first merge's, no sovereign key remains, and a second set of `trust_key_merges` rows exists. Include a stray present only in the knowledge-store snapshot (no `trust_scores` row): it merges, and its DELETE is a no-op.

**Focused gate (per milestone):** `d:/ProbOS/.venv/Scripts/python.exe -m pytest tests/test_bf907_trust_identity.py tests/test_trust_reconcile.py tests/test_trust_concurrency.py tests/test_feedback_engine.py tests/test_ad588_telemetry_introspection.py tests/test_ad1258_self_knowledge.py tests/test_ad1259_one_source_of_truth.py tests/test_dreaming.py tests/test_identity.py tests/test_bf885_identity_db_units.py tests/test_ad1256_store_registry.py tests/test_ad1195_eventlog_pair_freeze.py tests/test_ad1260_wellness_domain.py tests/test_correction_runtime.py -n 0 -q`. **Broad gate:** once, by the orchestrator: `scripts/run_test_gate.py --label bf907 --receipt logs/gates/bf907.receipt.json`.

## Milestones (each at most about 150 tool calls)

| # | Scope | Tests green at the cut | Cut point |
|---|---|---|---|
| M1 | Sections 1-2 + A1.1 | 1-6, 8-13, 17 + `test_ad1256_store_registry.py` | focused gate green; `check_store_registry.py --check` clean; `git diff --stat` shows only `identity.py`, `trust.py`, `docs/development/store-baseline.yaml` (+2 lines) and the new test file |
| M2 | Sections 3-5 (with `MERGE_EVENT`, D13) + A1.2 | 7, 14-16, 18-21, 28 + `test_ad1195_eventlog_pair_freeze.py` | focused gate green |
| M3 | Sections 6-8 + A1.3-A1.6 + trackers | 22-27 + updated tests + A1 rows | focused gate green; then Diff Reviewer, mutation campaign, local commit |

## Mutation table (run once on the final tree; every anchor is a whole, unique line)

| ID | File: anchor → mutant | Killed by |
|---|---|---|
| R1 | trust.py `            agent_id=self._canonical_key(agent_id),  # BF-907: the slot record, whatever form the caller holds` → `            agent_id=agent_id,` | 5, 7 |
| R2 | trust.py `        record = self._records.get(self._canonical_key(agent_id))` → `.get(agent_id)` | 4 |
| R3 | trust.py `        return self._records.get(self._canonical_key(agent_id))` → `.get(agent_id)` | 4 |
| R4 | trust.py `        key = self._canonical_key(agent_id)` → `        key = agent_id` | 4 |
| R5 | trust.py `        return slot_id if type(slot_id) is str and slot_id else agent_id` → `        return agent_id` | 4, 5 |
| R6 | trust.py `            alpha_after = before[0] + max(evidence_alpha, 0.0)` → `before[0] + source.alpha` | 8 |
| R7 | trust.py `            beta_after = before[1] + max(evidence_beta, 0.0)` → `before[1] + source.beta` | 8 |
| R8 | trust.py `            if evidence_alpha < -tolerance or evidence_beta < -tolerance:` → `            if False:` | 11 |
| R9 | trust.py `                before = planned[target_key]` → `before = (self._records[target_key].alpha, self._records[target_key].beta)` | 10 |
| R10 | trust.py `                        [(snapshot_id, r.agent_id, r.alpha, r.beta, merged_at) for r in self._records.values()],` → add `if r.agent_id in pairs` | 12 |
| R11 | trust.py `                        await self._db.execute("DELETE FROM trust_scores WHERE agent_id = ?", (merge.source_key,))` → `pass` | 13 |
| R12 | trust.py `                    self._records.pop(merge.source_key, None)` → `pass` | 13 |
| R13 | identity.py `        if len(slots) == 1:` → `        if slots:` | 2 |
| R14 | identity.py `                    self._asset_slot_by_uuid[tag.asset_uuid] = tag.slot_id` → removed | 3 |
| R15 | identity.py `            self._asset_slot_by_uuid[tag.asset_uuid] = tag.slot_id` → removed | 1 |
| R16 | trust_identity.py `    trust_network.set_identity_resolver(identity_registry.resolve_slot_id)` → removed | 7, 19 |
| R17 | trust_identity.py `        if key in active_ids or not is_sovereign_identity_key(key):` → `        if key in active_ids:` | 16 |
| R18 | trust_identity.py `        elif slot_id not in active_ids:` → `        elif False:` | 15 |
| R19 | trust_identity.py `    removed = trust_network.reconcile(active_ids \| frozenset(kept))` → `reconcile(active_ids)` | 15 |
| R20 | introspective_telemetry.py `                    result["record"] = "missing"` → removed | 22 |
| R21 | introspective_telemetry.py `                lines.append("Trust: no record for this id")` → `"Trust: no record yet"` | 22 |
| R22 | proactive.py `                _snapshot = await _telemetry_svc.get_full_snapshot(agent.id)` → `(getattr(agent, 'sovereign_id', None) or agent.id)` | 23[proactive] |
| R23 | cognitive_agent.py `…get_full_snapshot(self.id)  # BF-907: slot id (DM)` → sovereign form | 23[dm], 24 |
| R24 | cognitive_agent.py `…get_full_snapshot(self.id)  # BF-907: slot id (WR)` → sovereign form | 23[wr] |
| R25 | query.py `        snapshot = await telemetry_svc.get_full_snapshot(agent_id)` → `(context.get("sovereign_id", "") or agent_id)` | 23[query] |
| R26 | feedback.py `            if len(target_ids) != 1:` → `            if not target_ids:` | 26 |
| R27 | trust_identity.py `        if state.get("score") != header or "observations" not in state:` → `        if False:` | 21 |
| R28 | trust_identity.py `        if agent.sovereign_id != cert.agent_uuid:` → `        if False:` | 21 |
| R29 | trust_identity.py `MERGE_EVENT = "trust_identity_merge"` → `MERGE_EVENT = "trust_identity_merged"` | 14, `test_ad1195…::test_resolved_pairs_are_frozen` |
| R30 | trust_identity.py `            event=MERGE_EVENT,` → `            event="trust_identity_merge",` | `test_ad1195…::test_literal_pairs_are_exactly_the_contract_37` |

Record the campaign of record with the tree hash and the sha256 of each changed file. Rerun only rows whose file differs.

## Diff Reviewer: properties to verify (GPT-6.1 Sol, cross-family)

1. `record_outcome`, `get_score`, `get_record` and `get_events_for_agent` give one answer for a slot id and for its certificate UUID or DID. Every non-identity key (slot ids, `federation_peer:`, `mcp-peer:`, `device:`, unknown UUIDs) behaves byte-identically. With no resolver set, `TrustNetwork` behaves as before.
2. `record_outcome_once`, `get_or_create`, `create_with_prior`, `remove_agent` and `reconcile` key by exactly the id given.
3. The merged value equals α_slot + (α_stray − `prior_alpha`) (beta likewise). The slot's own prior is preserved. Two strays for one slot add once each.
4. The merge is one transaction: every in-memory record is snapshotted, the targets are written, the sources deleted and the merges recorded. Memory changes only after commit. A failure leaves file and memory unchanged. Synchronous trust writers during the transaction receive `trust_write_in_progress`.
5. A rerun after a merge, in the same process or after a restart whose warm boot restores no pre-merge knowledge-store snapshot, writes no rows and no events. If the vessel died before the first 60-s flush, warm boot restores the pre-merge pair and the merge reruns to identical values (D11, test 28).
6. Every identity-shaped key not merged survives AD-280 and is logged with a reason. Non-identity stale keys are removed exactly as before.
7. Telemetry never presents the prior for a missing record. The miss is logged once per subject.
8. The three injected telemetry paths and the query sub-task pass the slot id. The memory domain still counts episodes by the sovereign id.
9. Correction feedback writes trust only to the single active agent of the type.
10. The finalize check cannot fail startup, and its log line carries crew and consistent counts.
11. `consensus/trust.py` imports nothing from `identity` or `startup`. `trust_scores` is unchanged. The two new tables are additive.
12. The merge event is written only in `startup/trust_identity.py`, through `MERGE_EVENT`. `_RESOLVED_PAIRS` grows by exactly `('trust', 'trust_identity_merge')`; `_LITERAL_PAIRS` (37), `_DYNAMIC_SITES`, `EventType` and `event_persistence.py` are unchanged.
13. `store-baseline.yaml` changes by exactly two lines in the `probos.consensus.trust` row (D12); no declaration is added; `architecture-baseline.yaml` is byte-identical.
14. No hidden-pin test loses its subject: each still asserts `get_score` on the slot id, and each query test passes a `sovereign_id` that differs from `_agent_id` (D15). No production line changes for them.

## What this changes beyond the telemetry line (intended; record in DECISIONS)

- **Telemetry domains.** The cognitive zone, age, last action and the social domain in the injected blocks now describe the agent. They were defaults or empty before.
- **Recall trust weight.** `recall_weighted`'s trust component now reads the real score: +0.10 × (score − 0.5), about +0.04, the same for every episode in a query. Ranking is unchanged; slightly more episodes may clear the AD-590 floor (`episodic.py:4984-4985`).
- **Dream boosts.** These now share the slot's AD-558 dampening stream, and the CORE_INFRASTRUCTURE skip (`trust.py:349-365`) now applies to infrastructure agents' sovereign-keyed writes.

## What this does NOT change

Trust persistence on crash (K-21: `trust.db` is written only by `save()`; the knowledge-store snapshot, flushed every 60 s and restored by warm boot, already carries evidence across a crash). Priors, decay, weights or dampening rules. `TrustNetwork.get_score`'s prior for unknown agents. UI. Numeric trust checking in AD-589 (`source_governance.py:862-891`). `record_outcome_once`. AD-280's removal of non-identity keys (finding F-a). Episode keying (sovereign ids stay). `TrustRecord.observations` (finding F-c). No recovery of trust evidence lost before this build (D6).

## Interplay with BF-906 (#1594)

BF-906 (#1594, PR #1599) lands first; this prompt was re-verified on its candidate `02eb27bc`. BF-906 changed three files this prompt cites, none at a BF-907 hunk: `runtime.py` (pool wiring `:2611`, Phase 7 `enroll_boot_crew` `:3452-3454`, `report_crew_invariant` `:3470` after `finalize_startup`), `startup/finalize.py` (`:5556`), `agent_onboarding.py` (crew enroller; `resolve_or_issue` now `:446`, `sovereign_id` set `:456`). BF-906's invariant (ACM lifecycle and commissioning) logs after BF-907's crew check (end of finalize, trust keying); they share no state. **Keep them as separate PRs.** Before building, re-run `git diff --stat 02eb27bc origin/main --` over the files in Sections 1-8 and re-verify any hunk that moved.

## Decisions

| # | Decision | Rejected alternatives | Envelope |
|---|---|---|---|
| D1 | Resolve inside `TrustNetwork` (one boundary) **and** fix the three injected telemetry callers. | Callers-only with a helper: leaves dream and other writers dependent on each caller, and readers like `episodic.py:3822` stay wrong. Resolver-only: the snapshot's other domains stay wrong. | Architect |
| D2 | Setter injection (`set_identity_resolver`), bound in the startup reconcile. | Constructor injection is impossible: `TrustNetwork` is built at `runtime.py:731`, before the identity registry (`infrastructure.py:170-173`). A global lookup was rejected. The setter matches `set_department_lookup`/`set_event_callback`/`set_tier_registry` (`trust.py:239-249`) and passes a bound method (no `_private` chains). | Architect |
| D3 | Unknown or ambiguous id → the resolver returns None and the key is unchanged. `record_outcome_once` is not resolved (its receipt hash binds `agent_id`). | Refusing unknown ids would change behaviour for new agents and peers. | Architect |
| D4 | The merge runs in structural services before AD-280, by key, with unmerged identity keys kept. | Running after AD-280 (strays already deleted). A separate script (the vessel holds the state). A score-range search (Captain forbade it). | Architect |
| D5 | Snapshot and merge record in two additive trust.db tables, one transaction, an event per merge. The knowledge-store snapshot converges at its next flush (D11). Reversal is below and covers both stores. | A JSON side file (not atomic with the merge). A full `save()` (rewrites every row and changes crash-time retention). | Architect: compatible schema path, reversible |
| D6 | No recovery of trust evidence lost before this build: strays AD-280 deleted at earlier starts, and the 2026-10-12 values of the 8 strays still in the live `trust.db`. Warm boot overwrites those 8 with the knowledge-store snapshot's 2026-10-18 values before the merge, so the 10-12 values (at most +0.575 α each, +2.5 α in total, every β 2.0) never reach it. What merges is the 2026-10-18 session's evidence: 15 strays, +11.8 α in total. | A one-off import of the 10-12 values from `trust.db` or the knowledge store's git history (a follow-up BF if the Captain wants it). | Architect; Captain may overrule |
| D7 | Correction feedback goes to the single active agent of the type, otherwise nothing. | One write per instance (multiplies evidence). Keep the type key (the Captain-approved acceptance requires the slot). | Architect |
| D8 | The crew check is a finalize log line, no doctor command. | A doctor check (deferred: no consumer yet). | Architect |
| D9 | The telemetry miss renders "Trust: no record for this id" and warns once per subject. | Logging on every call (spam). | Architect |
| D10 | A separate PR from BF-906. | One combined PR (different subsystems). | Architect |
| D11 | The merge writes `trust.db` only; the knowledge-store snapshot converges at the next 60-s flush or shutdown. A death before that flush makes the next warm boot restore the pre-merge pair, and the merge reruns to identical values with a second snapshot, merge rows and events (test 28). | Passing the knowledge store into structural services to rewrite `snapshot.json` in the merge (a second store the transaction cannot join). Making warm boot skip identity keys (changes AD-162 restore semantics). | Architect |
| D12 | **Update the reviewed baseline row; do not declare `trust.db` in BF-907.** The checker allows either. Declaring it needs a new `probos/consensus/storage_declarations.py` and a new entry in `DECLARATION_MODULES` (`storage/registry.py:57-65`), and reviewed retention and restore claims that are outside this defect (`save()` rewrites `trust_scores`, `trust_outcome_receipts` has no delete path, warm boot force-sets the table). BF-906 (D16) declared `acm.db` because it already had a home and had gained a reader. | Declaring `trust.db` (AD-1256 inventory work, #1302). | Architect |
| D13 | **Name the merge event through a module constant, `MERGE_EVENT`, in `startup/trust_identity.py`.** The census then freezes `('trust', 'trust_identity_merge')` in `_RESOLVED_PAIRS`; `_LITERAL_PAIRS` stays at 37 and `_DYNAMIC_SITES` is unchanged. Unlike BF-906 (D19), nothing has to move: the module that writes the event owns the constant. | Adding the pair to `_LITERAL_PAIRS` (count 38). | Architect |
| D14 | **No `event_persistence.py` entry.** The event is not an `EventType` member and is not a routed value. It is best effort: `trust_key_merges` is authoritative. | An entry (changes persistence policy). | Architect |
| D15 | **The 11 hidden pins are test changes; no production change.** Each fake returns a record for a known subject, the same shape as `test_ad1259_one_source_of_truth.py:63-82`. The four query-site tests pinned the defect: they made the sovereign id the telemetry subject while `_agent_id` was a transient; they now carry the slot id in `_agent_id` and a distinct `sovereign_id`. | A production fallback to `get_score` for a missing record (re-creates the defect). | Architect |
| D16 | **Re-run the whole-contract dry run with all 31 pairs plus A1's Section 3 edit and the baseline row, no test edits: expect exactly 18 failures** (the 15 telemetry tests, `test_ad1195…::test_resolved_pairs_are_frozen`, the 2 correction tests); with all test edits applied, expect 0. Any other failure is a new pin and goes back to the Architect. Must finish before M3 is dispatched. | Trusting the first dry run (it skipped 2h and 7d). | Architect |

**Reversal procedure.** Stop the vessel. Revert BF-907; otherwise the restored strays merge again at the next start. Then:
1. On `trust.db`: `BEGIN IMMEDIATE; DELETE FROM trust_scores; INSERT INTO trust_scores (agent_id, alpha, beta, updated) SELECT agent_id, alpha, beta, taken_at FROM trust_snapshots WHERE snapshot_id = :id; COMMIT;`
2. Move `%LOCALAPPDATA%\ProbOS\data\knowledge\trust\snapshot.json` out of the knowledge directory. Warm boot force-sets every key in it over `trust.db` (`warm_boot.py:91-100`), which would undo step 1; with the file absent, `load_trust_snapshot` returns None (`knowledge/store.py:876-877`) and the restored rows stand. The next 60-s flush rewrites it.
Evidence recorded after the merge is lost by a restore.

## After the next restart (the Captain's checklist)

**Precondition: the next vessel start runs this build.** A start on an earlier build deletes the strays in memory (AD-280) and the 60-s flush erases them from the knowledge-store snapshot within a minute; the numbers below then do not apply (D6 accepts that loss).

What the first start merges (probed read-only 2026-10-19): `trust.db` (90 rows, 2026-10-12) loads, then warm boot force-sets the 98 keys of `knowledge/trust/snapshot.json` (2026-10-18 session). The merge sees about 105 keys: the 102 keys of the two stores together (measured on copies of the live files) plus this session's own runtime agent ids (their records exist from pool creation, before warm boot); the snapshot's values win.

| Read | Must show |
|---|---|
| `%LOCALAPPDATA%\ProbOS\data\logs\probos.log` | `TrustNetwork loaded 90 records`; `Warm boot restored: trust(98 agents)`; `BF-907 trust identity merge: merged=15 kept=0`; `trust-reconcile removed=8` [inferred: 3 + 3 dashless-hex runtime ids, `system`, `captain`; 12 at the 2026-10-18 start]; `BF-907 trust identity check: crew=16 consistent=16`. Any WARNING names the callsign and the reason; a `sovereign_id … is not its certificate` problem is a separate defect: file a BF. |
| `events.db` (`?mode=ro`): `SELECT timestamp, data FROM events WHERE category='trust' AND event='trust_identity_merge'` | 15 rows, with source and target keys, deltas and `merged_at` |
| `trust.db` (`?mode=ro`, `ATTACH identity.db AS i`): `SELECT count(*) FROM trust_scores WHERE agent_id IN (SELECT agent_uuid FROM i.birth_certificates)` | `0`; `trust_snapshots` holds one `snapshot_id` with one row per in-memory trust record at the merge (about 105 on the live shape; not a pass/fail number); `trust_key_merges` 15 rows; `trust_scores` 82 rows (7 of the strays existed only in the knowledge-store snapshot) |
| `knowledge/trust/snapshot.json`, a minute after startup | no dashed-UUID keys |
| Meridian's telemetry (an introspective DM) | 0.9110 (surgeon slot 20.0625 → 20.4625), with an observation count, equal to her header |
| Nova's telemetry | 0.9845 (126.7625, 2.0), equal to her header |
| After the next clean stop, the same `trust.db` query | `0`; about 81 `trust_scores` rows |

Expected merges (slot α + stray α − 2.0; every β is 2.0 and stays 2.0; knowledge-store values, float noise rounded; each stray maps to its slot through `slot_mappings` in `identity.db`, measured on a copy 2026-10-19):

| Stray | Slot | Stray α | Slot α | Merged α |
|---|---|---|---|---|
| `3fc92188` | `builder_builder_0_0e6917c3` | 2.9 | 46.80 | 47.70 |
| `46fddc43` | `systems_analyst_science_systems_analyst_0_30291ff0` | 3.4 | 41.3625 | 42.7625 |
| `791fec1e` | `security_officer_security_officer_0_01da21d1` | 2.3 | 114.95 | 115.25 |
| `b03d7a70` | `engineering_officer_engineering_officer_0_872b75e7` | 2.6 | 153.35 | 153.95 |
| `c53aef31` | `counselor_counselor_0_67c601cb` | 2.7 | 127.65 | 128.35 |
| `d7d033d2` | `data_analyst_science_data_analyst_0_9691d1fa` | 3.0 | 33.85 | 34.85 |
| `ec9a26f0` | `scout_scout_0_ce40fe4b` | 2.4 | 88.375 | 88.775 |
| `fd7c0aba` | `architect_architect_0_de7afd07` | 2.5 | 145.3625 | 145.8625 |
| `dfd9d864` | `training_officer_training_officer_0_b66337eb` | 3.1 | 15.6625 | 16.7625 |
| `c270c092` | `surgeon_medical_surgeon_0_b2321292` | 2.4 | 20.0625 | 20.4625 |
| `2d63b7cd` | `research_specialist_science_research_specialist_0_7c06a530` | 3.0 | 29.2625 | 30.2625 |
| `295487bb` | `operations_officer_operations_officer_0_adb55c01` | 3.1 | 125.6625 | 126.7625 |
| `82652abd` | `diagnostician_medical_diagnostician_0_10bbe984` | 3.2 | 92.175 | 93.375 |
| `3f13f012` | `pathologist_medical_pathologist_0_49f3b45e` | 2.1 | 25.4375 | 25.5375 |
| `71823b24` | `pharmacist_medical_pharmacist_0_51edfdc5` | 3.1 | 20.425 | 21.525 |

## Tracking

- `DECISIONS.md`: `### BF-907 -- Trust is keyed by slot id; sovereign identities resolve at the trust boundary (date, #1597)`, placed as `### BF-905` is at `DECISIONS.md:119`. Include D1-D16, the AD-280 finding, the behaviour changes above, and the campaign of record.
- `PROGRESS.md`: one paragraph covering the defect, the fix, the merge counts once live, and the reversal.
- Ledger and `docs/development/roadmap.md` Bug Tracker: a BF-907 row (#1597) in the existing `| BF-NNN | … | [#NNNN](…) | n |` format (for example `roadmap.md:779`).
- #1523: findings F-a to F-d, numbered from the next free F-number (F-154 or later).
- **Closure comment:** state the merge counts (expected `merged=15 kept=0`, +11.8 α in total) and the timestamp. State the amendment point 1 finding: Nova's 0.9843 equals her slot record, so it came from a slot-keyed path, and her `sovereign_id` was set. Say that crew analyses which consumed telemetry trust are contaminated, so the crew can re-baseline: Sage's `trust-telemetry-baseline` entry (0.6296) and Atlas's emergence and synergy work. No code change is needed for that. State the D6 loss: the 2026-10-12 values of 8 strays (+2.5 α), overwritten by warm boot, and the strays deleted at earlier starts.

## Acceptance Criteria

1. With a real `TrustNetwork` and an agent whose `sovereign_id` differs from its `id`, every read path (header, the three injected blocks, the query sub-task, `self_query`, introspect, the trust API) reports the same score and observation count (tests 4, 7, 19, 23, 24).
2. Every `record_outcome` caller is enumerated above. Dream consolidation and the type-keyed writer land on the slot record, and test 7 crosses the seam.
3. The merge goes by key, with the prior counted once. A snapshot is taken first, a timestamp is recorded in trust.db and in the event log, a rerun is a no-op, an unmapped row is kept and reported, and every crew member is checked at startup.
4. The AD-589 cached snapshot's trust equals `get_score(agent.id)` (test 24).
5. The mutation table is executed once with every row killed. One receipted broad gate. CI green.
6. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-10-18 on `cf08d4c9`; re-verified 2026-10-19 on `02eb27bc`)

```
git diff --stat origin/main -- <all 25 files cited>      → (empty)
grep trust.py:200-213   prior_alpha 2.0 / prior_beta 2.0 / decay_rate 0.999; _records dict
grep trust.py:239-249   set_department_lookup / set_event_callback / set_tier_registry
grep trust.py:304-330   record_outcome → _TrustOutcomeInput(agent_id=agent_id, …) (:321); other ctor :676 (record_outcome_once)
grep trust.py:346-348   new record from self.prior_alpha/self.prior_beta
grep trust.py:949-968   get_score prior fallback; get_record; get_events_for_agent
grep trust.py:974-983   decay_all toward network prior
grep trust.py:996-1002  reconcile deletes keys not in active set
grep trust.py:1018-1031 raw_scores (public key enumeration)
grep trust.py:1123-1149 _save_to_db DELETE+INSERT; save()
grep trust.py:612-646   record_outcome_once sets _outcome_transaction_inflight
grep protocols.py:336   DatabaseConnection.executemany
grep config_models/core.py:92-94   trust_prior_alpha/beta 2.0, decay 0.999
grep config_models/cognition.py:106-107   trust_boost/penalty 0.1
grep tiered_trust.py:68-83   per-tier create_with_prior
grep identity.py:30,91-148   import uuid (re absent); generate_did; parse_did keys
grep identity.py:443-448,524-527,573-615,756-785,812-813,850-959,1530-1564   slot_mappings, caches, lookups, writers
grep agent_onboarding.py:446-456   resolve_or_issue(slot_id=agent.id) → agent.sovereign_id
grep communication.py:889-921      deferred crew certificates
grep substrate/agent.py:44         self.sovereign_id: str = ""
grep startup/infrastructure.py:80,120,170-174   event_log.start, trust start, identity start
grep structural_services.py:16-44,72-76         TYPE_CHECKING, signature, AD-280 reconcile
grep runtime.py:602-603,699,733-739,2757,2926,3113-3127   property, event_log, TrustNetwork(), identity, telemetry, call (02eb27bc)
grep finalize.py:3934-3938,6623                 signature, final log line
git diff --stat cf08d4c9 02eb27bc -- <cited files>   → agent_onboarding.py, runtime.py, startup/finalize.py only; no cited test
grep warm_boot.py:46-54,91-100     WarmBootService(knowledge_store=…); force-sets every snapshot key via get_or_create
grep cognitive_services.py:569     await warm_boot_service.restore()
grep dream_adapter.py:316-338      periodic_flush → store_trust_snapshot(raw_scores()); loop sleeps 60
grep knowledge/store.py:864-882    trust/snapshot.json write/load; None if absent
grep shutdown.py:1963-1965         store_trust_snapshot at shutdown
grep substrate/agent.py:42         default id uuid.uuid4().hex (dashless)
grep identity.py:114-116,804       generate_agent_uuid → str(uuid.uuid4()); asset uuid uses it
grep agent_onboarding.py:456,475,494-495   sovereign_id = cert.agent_uuid; = tag.asset_uuid; event data
grep introspective_telemetry.py:51-59,114-141,281-312,332-346
grep proactive.py:1708,2486-2492; cognitive_agent.py:8880-8908,10283-10291,10616-10624,5792,5982,11177
grep sub_tasks/query.py:381,404-407; self_query_tool.py:172,229; agentic_dispatch.py:427-468,2664-2667,2815,3832-3834
grep dreaming.py:2609-2673; feedback.py:9-16,42-58,110-125,202-214; cognitive_services.py:164-168,516-522
grep episodic.py:463-483,3819-3822,4761,4908-4911,4984-4985
grep tests: test_ad588…:345-355,478-493,540-568,761-768; test_ad1258…:226; test_feedback_engine.py:83-96,355-405; test_trust_concurrency.py:214-255; test_ad1196_did_key_binding.py:278-282
```

## Absence Verified (2026-10-18)

| Claim | Run | Found | Holds |
|---|---|---|---|
| A1: nothing sets a `sovereign_id` context key | Grep `["']sovereign_id["']` over `src/probos/cognitive`; `\["sovereign_id"\]\s*=\|"sovereign_id":` over `src/probos` | only `getattr` reads; `agent_onboarding.py:495` (event data), `interop/gitagent.py:52,118`, `routers/agents.py:202` | yes |
| A2: only 4 `get_full_snapshot` callers, plus `self_query` | Grep `get_full_snapshot\(` | `cognitive_agent.py:10284,10617`, `proactive.py:2489`, `query.py:407`, `self_query_tool.py:229` | yes |
| A3: the only cache writers | Grep `_asset_cache\[\|_slot_cache\[` | `identity.py:580,592,615,813,916,1551` | yes |
| A4: one startup trust reconcile | Grep `trust_network\.(reconcile\|remove_agent\|remove\|decay_all)\(` | `structural_services.py:74` | yes |
| A5: no test calls `init_structural_services` | Grep over tests | none | yes |
| A6: no test pins a sovereign-id snapshot call | Grep `get_full_snapshot.*sovereign\|get_full_snapshot\.assert` | only `test_ad588…:615` (`assert_not_called`) | yes |
| A7: AD-589 cache writers are DM and WR only | Grep `set_telemetry_snapshot` | `cognitive_agent.py:10291,10624` | yes |
| A8: stored `self_query` results use slot ids | Grep attachments `"name": "self_query", "output": "{'agent_id': '…'` | 8, all slot ids | yes |
| A9: no federation or device trust rows live | Grep count on `trust.db` | 0 | yes (byte-level) |

## Prior Art and Blind Spots

- **Internal prior work.** AD-441 sovereign identity and the episode convention (`episodic.py:463-469`). AD-280 reconcile. AD-1259 (#1309) unified precision across paths, not keys. AD-640 tier priors. BF-879 probationary prior. All are cited where they constrain the design.
- **External prior art.** The Beta Reputation System ([Jøsang and Ismail, 2002](https://mn.uio.no/ifi/english/people/aca/josang/publications/ji2002-bled.pdf)) combines evidence by adding success and failure counts to a single base prior. Adopted: the merge rule is exactly that. Its forgetting factor scales the evidence, which is consistent with `decay_all` scaling evidence above the prior, so decayed stray evidence merges correctly. One standard search. `docs/research/reference-projects.md` has no trust or identity rows (Grep `trust|reputation|identity|Beta`: none), so no overdue entries were relevant (date used: 2026-10-18).
- **Blind spots found and absorbed:**
  - The AD-280 deletion at every start.
  - The other wrong snapshot domains.
  - The recall trust weight.
  - Dampening and tier-skip key change.
  - Test helpers with `sovereign_id == id`.
  - Merge failure must keep the strays, not let AD-280 delete them.
  - Two strays for one slot (UUID and DID).
  - Probationary or tiered slot priors.
  - Warm boot runs before the merge (`cognitive_services.py:569`) and force-sets every key of the knowledge-store trust snapshot (`warm_boot.py:91-100`), a second trust store flushed every 60 s. Absorbed 2026-10-19: the live merge input is that snapshot (15 strays, not `trust.db`'s 8), the reversal moves it aside, and a death before the first flush re-merges to identical values (D11, test 28).
- **Considered, deferred:** historical stray recovery (D6); a doctor command (D8); F-a to F-d (findings).

Sources:
- [Jøsang and Ismail, "The Beta Reputation System" (Bled 2002)](https://mn.uio.no/ifi/english/people/aca/josang/publications/ji2002-bled.pdf)
- [Jøsang et al. (ARES 2007)](https://mn.uio.no/ifi/english/people/aca/josang/publications/jh2007-ares.pdf)
