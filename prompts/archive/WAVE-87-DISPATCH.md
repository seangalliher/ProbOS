# WAVE 87 DISPATCH — AD-443 v1 Agent Mobility (Transfer Certificates + Memory Portability)

**Wave id:** 87
**Umbrella AD:** AD-443 (Agent Mobility Protocol — Transfer Certificates & Memory Portability)
**OSS sub-AD letters in scope (concrete v1):** AD-443a (Transfer Certificate VC dataclass + issuance), AD-443b (`import_chain` / `verify_remote_chain` — cross-ship ledger acceptance), AD-443c (Memory Policy enum + Standing Orders Federation tier hook), AD-443d (slot re-assignment — sovereign DID maps to new local slot), AD-443e (FederationBridge transfer/chain wire-protocol message types + MockFederationTransport round-trip).
**OSS sub-AD letters NOT in scope (carved out as future ADs — not v1 deferrals):** AD-443f (cross-process live multi-instance demo over real ZMQ — needs ops-tooling for second instance launch + observability for the live transfer; in-process `MockFederationTransport` round-trip in v1 already proves correctness end-to-end), AD-443g (Federated capability-map exchange consumed by `verify_transfer_certificate` for trust-weighted acceptance — depends on AD-479 not yet shipped), AD-443h (A2A Agent Card export of Transfer Certificates over Microsoft Foundry / public-A2A — depends on AD-480 not yet shipped).
**Carved out per `docs/development/roadmap.md:4095` and tracked in the private commercial-repo path token (NOT v1 deferrals — wrong-repo by design):** Global Instance Registry, fleet dashboard, fleet-wide compliance auditing, cross-instance ledger-of-ledgers indexing service. None of these are touched by Wave 87 — Wave 87 is fully OSS substrate.
**Closes:** GH issue #42
**HEAD at draft:** `8252468` (post-Wave-86)
**Baseline test counts:** **11705** pytest at HEAD (verified `pytest --collect-only -q tests/`); vitest unchanged at 306 (305 passing + 1 pre-existing `WardRoomDmSync` failure carried since pre-Wave-85, not in scope). Expected after Wave 87: **≥ 11760** pytest (+55 floor; ~57 tests planned across six classes), vitest **unchanged at 306**.
**Builder required:** true (one focused build prompt; Python-only with one config-file edit and one Markdown edit; no UI surface touched).
**AD numbering:** Highest stem at HEAD remains **AD-696** (Wave 72). AD-443 pre-allocated by `docs/development/roadmap.md:4095`; sub-AD letters a–h are organizational catalog markers only, mirroring the AD-474 a–h (Wave 86), AD-473 a–g (Wave 85), and AD-512 a–f (Wave 84) precedents — no new AD numbers minted.

## Verdict

Verify-first against HEAD `8252468` shows the **identity substrate AD-443 will extend is fully shipped and live** — this is a "build-on-existing-foundation" wave, not "ship-from-scratch":

- **Identity substrate live:** `src/probos/identity.py` (913 LOC) ships `AgentBirthCertificate` (W3C VC), `ShipBirthCertificate`, `LedgerBlock`, `AgentIdentityRegistry`, the genesis-block-rooted hash-chained `identity_ledger` table (`_IDENTITY_SCHEMA` lines 307–363), `verify_chain()` (line 832 — local chain validation), `export_chain()` (line 879 — full chain export with attached VCs), `issue_birth_certificate()` (line 623), `resolve_or_issue()` (line 717), `get_by_uuid` / `get_by_slot` / `get_by_agent_type` lookup paths, and `slot_mappings` table for slot→agent_uuid persistence. Storage is `ConnectionFactory`-backed (cloud-ready storage convention preserved).
- **Federation substrate live:** `src/probos/federation/bridge.py` (`FederationBridge` — gossip + intent_request/intent_response + ping/pong, dispatching on `message.type` string in `handle_inbound`), `src/probos/federation/transport.py` (`FederationTransport` — ZMQ DEALER/ROUTER, `send_to_peer`, `send_to_all_peers`, `deliver_response` correlation by `message_id`), `src/probos/federation/mock_transport.py` (in-process round-trip for tests), `src/probos/types.py:664` `FederationMessage` (free-form `type: str` — accepts new wire-protocol message types non-breakingly).
- **Standing Orders federation tier live:** `config/standing_orders/federation.md` (universal-principles tier composed by `src/probos/cognitive/standing_orders.py:386–389` between Tier 1 hardcoded identity and the rest). Memory section already present (lines 94–103); mobility addendum will append cleanly.
- **What's missing:** Transfer Certificate VC dataclass; `import_chain()`/`verify_remote_chain()`; foreign-chain persistence table; slot reassignment for foreign certs; Memory Policy enum + per-ship default + per-agent Standing Orders override; FederationBridge wire types `transfer_request`/`transfer_response`/`chain_request`/`chain_response`; cross-ship MockTransport round-trip test bench.

This is exactly the AD-443 v1 OSS spec at `docs/development/roadmap.md:4095`. Captain rule "don't defer unless no choice" is honored by **building everything that does not require AD-479 (federated capability map) or AD-480 (A2A agent cards)** — the carve-out at the roadmap line itself names "Global Instance Registry, fleet dashboard, compliance" as commercial-repo-tracked, leaving the entire Transfer-Certificate / chain-portability / memory-policy / slot-reassignment surface for OSS.

| Roadmap component (line 4095) | Wave 87 action |
|---|---|
| (1) Transfer Certificate VC — W3C VC, sovereign DID, rank, qualification credentials, assignment history | **BUILD AD-443a.** New module `src/probos/mobility.py` ships `TransferCertificate` dataclass (W3C VC compatible — `to_verifiable_credential` returns `["VerifiableCredential", "AgentTransferCertificate"]` type), `compute_hash`, `to_dict`/`from_dict`. Issuance path: `AgentIdentityRegistry.issue_transfer_certificate(agent_uuid, target_instance_did)` — looks up local birth cert by UUID, freezes assignment history (origin_instance_did + birth_timestamp + transfer_timestamp), persists to new `transfer_certificates` table. ~10 tests. |
| (2) `import_chain()` / `verify_remote_chain()` — accept and validate remote ship's Identity Ledger | **BUILD AD-443b.** `AgentIdentityRegistry.import_chain(blocks)` accepts the JSON shape returned by `export_chain()` (verified at `identity.py:872`), persists into a new `foreign_chains` table keyed by `origin_ship_did`, replaces any prior snapshot for that ship. `verify_remote_chain(blocks)` is pure local validation — recomputes block hashes, walks `previous_hash` linkage from genesis, verifies the genesis-block ship-cert hash matches the embedded ship VC. Returns `(valid: bool, message: str)` mirroring `verify_chain()`'s shape. ~12 tests. |
| (3) Memory portability hooks — Standing Orders Federation tier declares Clean Room / Selective / Full | **BUILD AD-443c.** `MemoryPolicy` `StrEnum` in `mobility.py` with `CLEAN_ROOM`, `SELECTIVE`, `FULL`. `apply_memory_policy(policy, episodes, selective_tags)` is a pure filter function: CLEAN_ROOM → empty list, FULL → episodes verbatim, SELECTIVE → only episodes whose `tags ∩ selective_tags ≠ ∅`. `FederationConfig.memory_policy: MemoryPolicy = MemoryPolicy.CLEAN_ROOM` (Pydantic field with `field_validator` rejecting unknown values; **default CLEAN_ROOM** — safest default; AD-695 default-False precedent applied). `config/standing_orders/federation.md` gains a new "Mobility & Memory Portability" section documenting the three tiers. ~10 tests. |
| (4) Slot re-assignment — existing sovereign DID maps to new slot | **BUILD AD-443d.** `AgentIdentityRegistry.reassign_slot(agent_uuid, new_slot_id, foreign: bool = False)` — updates `slot_mappings` row (or inserts if foreign agent_uuid not already in `birth_certificates` because it lives in `foreign_birth_certificates`, a new table holding imported foreign certs alongside the existing native `birth_certificates`). `get_by_slot()` reads through both tables transparently. Birth-provenance vessel_name preserved per AD-499. ~10 tests. |
| (Bundled) Federation wire-protocol message types for transfer/chain | **BUILD AD-443e.** `FederationBridge.handle_inbound` extends the `message.type` switch to dispatch `transfer_request` (peer asks us to accept a TransferCertificate + chain segment), `transfer_response` (delivered via `transport.deliver_response` for correlation), `chain_request` (peer asks for our `export_chain()` output), `chain_response` (delivered via correlation). New helpers `request_chain(peer_node_id)` and `request_transfer(peer_node_id, certificate, chain_blocks)` on the bridge. End-to-end MockFederationTransport round-trip exercise: 2 mock ships, agent on ship A → issue Transfer Cert → wire to ship B → ship B imports chain → ship B verifies cert hash present in chain → ship B reassigns slot → `get_by_slot` on B returns foreign cert with origin vessel_name preserved. ~10 tests. |
| Standing Orders Federation tier integration | **BUILD AD-443c (continued).** `config/standing_orders/federation.md` appendix; `src/probos/cognitive/standing_orders.py` reads `runtime.config.federation.memory_policy` if present (no signature change to `compose_instructions` — read via the existing config-aware code path). Per-agent override mechanism documented as Standing Orders override (existing `compose_instructions` already supports per-agent `additional_orders` — Wave 87 doesn't change that surface). ~5 tests. |

## Reframe decision (Captain rule applied)

**Five concrete sub-AD letters built + three future-AD letters with explicit forcing functions + three commercial-repo carve-outs (NOT deferrals — wrong-repo by roadmap design at line 4095) + zero hard-deferrals.** Strictest application of "don't defer unless no choice" available for AD-443 — every roadmap-line-4095 component that does not depend on un-shipped AD-479 / AD-480 substrate ships in v1, and the cross-process ZMQ live-demo carve-out is justified because in-process `MockFederationTransport` round-trip already proves correctness end-to-end (the test bench is identical to how the existing intent_request/response federation path is validated today).

The `PROGRESS.md` line-100 reasoning that originally deferred AD-443 from Wave 5 to Wave 9C ("verify_remote_chain and slot-reassignment paths require AD-479 federation infrastructure that hasn't shipped") is **revisited and rejected at Wave 87** by verify-first against HEAD:

1. **`verify_remote_chain` does NOT need live federation.** It is pure local hash-chain validation given a JSON snapshot of a remote chain. It is the symmetric local-side counterpart to `export_chain()` — both operate on serializable data, neither requires a live peer.
2. **Slot reassignment does NOT need AD-479.** It is a local SQL update against `slot_mappings`. The "foreign cert" half (storing an imported cert from a remote ship locally) is a new `foreign_birth_certificates` table; foreign certs are looked up by `agent_uuid` exactly the same way local ones are.
3. **AD-443 wire-protocol message types do NOT need AD-479.** AD-479 is the federated capability-map / route-table protocol — it answers "which peer can do X?" and is consumed by intent forwarding. AD-443's `transfer_request` / `chain_request` are point-to-point peer-addressed; the caller already knows the destination `peer_node_id`. The existing `FederationMessage.type: str` dispatch in `handle_inbound` (verified at `bridge.py:137-160`) accepts new types non-breakingly.
4. **In-process `MockFederationTransport` is a sufficient v1 test bench.** It is the same harness already used by the existing intent-forwarding tests at HEAD; it exercises the bridge's `handle_inbound` dispatch and the transport's `send_to_peer` / `deliver_response` correlation paths without booting a second OS process.

Three things that LOOK like deferrals but aren't:

1. **Live cross-process ZMQ multi-instance demo (AD-443f)** is the *demo*, not the *protocol*. The protocol correctness is proven by the in-process round-trip in v1; AD-443f is launch-script-and-observability work that belongs to a future ops-tooling AD.
2. **Federated capability-map AD-479 dependency (AD-443g)** is genuinely upstream-blocked. Trust-weighted acceptance of an incoming transfer (e.g., "this cert came from a peer with capability `<x>` therefore weight its claim at trust-tier T") needs the capability map, which has not been built. AD-443 v1 ships acceptance based on chain-integrity verification only — Captain or operator decides whether to invoke `import_transfer_certificate` for a given peer. The forcing function is "land AD-479 first, then AD-443g promotes acceptance to trust-weighted automatic."
3. **A2A export AD-480 dependency (AD-443h)** is genuinely upstream-blocked. Microsoft Foundry's A2A Agent Card schema is the export envelope; AD-480 has not shipped. AD-443 v1 keeps Transfer Certificates in their native W3C VC form; AD-443h wraps a TransferCertificate's `to_verifiable_credential()` output inside an Agent Card when AD-480 lands.

Three commercial-repo carve-outs (these are NOT deferrals — they are out-of-repo by design at roadmap line 4095):

- **Global Instance Registry** — fleet-wide service mapping ship DIDs to network endpoints + last-known-online status. Tracked in the private commercial-repo path token (the e-word-prefixed repo). Not in any OSS wave.
- **Fleet dashboard** — multi-ship operations console showing ledger health, transfer activity, fleet-wide trust topology. Tracked in the private commercial-repo path token. Not in any OSS wave.
- **Fleet-wide compliance auditing** — cross-ship audit-trail aggregation, retention policy enforcement across instances, regulator-facing report generation. Tracked in the private commercial-repo path token. Not in any OSS wave.

GH #42 closure note (drafted; commits with Builder's PR): "Closed by Wave 87 (AD-443 v1 — five concrete OSS sub-AD letters 443a/b/c/d/e). Transfer Certificate VC + chain portability (`import_chain` / `verify_remote_chain`) + Memory Policy enum (CLEAN_ROOM / SELECTIVE / FULL) + slot reassignment for foreign certs + FederationBridge `transfer_request` / `transfer_response` / `chain_request` / `chain_response` wire types all ship in v1, exercised end-to-end via in-process `MockFederationTransport` round-trip (2 mock ships, full transfer + verify + reassign cycle). Components parked as future sub-ADs 443f/g/h with explicit forcing functions: 443f live cross-process ZMQ multi-instance demo (needs ops-tooling for second-instance launch + observability — in-process MockTransport round-trip already proves protocol correctness in v1), 443g trust-weighted automatic acceptance (depends on AD-479 federated capability map — not yet shipped), 443h A2A Agent Card export (depends on AD-480 — not yet shipped). Carved out per `docs/development/roadmap.md:4095` and tracked in the private commercial-repo path token (NOT v1 deferrals — out-of-repo by design): Global Instance Registry, fleet dashboard, fleet-wide compliance auditing. Captain rule honored — every roadmap-line-4095 component that does not depend on un-shipped AD-479/AD-480 substrate shipped in v1."

## Commercial-leak audit (pre-commit hook safety)

**Banned-pattern sweep on draft** (`prompts/WAVE-87-DISPATCH.md` + `prompts/ad-443-mobility-v1.md`), per `.git/hooks/pre-commit` lines 5–17 — all 11 banned patterns confirmed **0 literal hits across both files**. The Captain's standing instruction "audit prose itself uses placeholders" is honored: the literal banned strings are NOT reproduced anywhere in this dispatch or the prompt, including in any audit table, example regex, or Select-String invocation. Each banned pattern is referenced only by an indirect descriptor:

| Banned-pattern descriptor (NOT literal) | Placeholder form used in this dispatch + prompt |
|---|---|
| the e-word followed by ` ` then `tier` (concatenation) | "the e-word + tier" |
| the private repo path token (lowercase product name + dash + a synonym for OSS-opposite) | "the private commercial-repo path token" |
| the same path token but with the e-word stem instead | "the e-word-prefixed repo token" |
| the e-word followed by ` overlay` (concatenation) | "the e-word overlay phrase" (not used) |
| dollar-sign + integer + `/month` (slashed) | "monthly-price regex" (not used) |
| dollar-sign + integer + `/mo` (slashed) | "per-month abbreviation regex" (not used) |
| `revenue` + ` ` + `projection` (concatenation) | "rev-proj phrase" (not used) |
| three-letter recurring-revenue acronym (annual + recurring + revenue) | "the recurring-revenue acronym" (not used) |
| the word `outcome` + non-letter + `based pricing` | "outcome-style pricing phrase" (not used) |
| three-word phrase: GAS (great + artists + steal) | "the GTM-pattern phrase" (not used) |
| three-word phrase: PTA (patterns + to + absorb) | "the patterns-to-absorb phrase" (not used) |

- AD-443 entry on `docs/development/roadmap.md:4095` carries no `*(Commercial)*` tag — the carve-out language reads "Commercial features (Global Instance Registry, fleet dashboard, compliance) tracked in the commercial repository." Neutral phrasing, no banned literals. Wave 87 mirrors that exact pattern in the dispatch prose.
- "Cloud" / "monetization" / "pricing tier" / "go-to-market" vocabulary is absent from both this dispatch and the prompt. AD-443 v1 surface is pure protocol — Transfer Certificates, chain portability, memory policy enum, slot reassignment, wire-protocol message types. Zero pricing / packaging / distribution surface.
- `MemoryPolicy.SELECTIVE` selective-tag list is intentionally pure mechanism (string set intersection on episode tags). Naming the policy "Selective" is descriptive, not commercial.
- Standing Orders `federation.md` addendum is universal-principles tier — composed identically on every ship regardless of OSS/commercial deployment context. No conditional language.

**Verdict:** clean. Pre-commit hook will not trip on this wave's artifacts.

## Verified Against Codebase (2026-05-06)

```
git rev-parse HEAD
  8252468

# Pytest baseline (verified):
.venv\Scripts\pytest.exe --collect-only -q tests/
  11705 tests collected in 5.84s

# AD-443 spec at HEAD (verified — pre-allocated, no Commercial tag):
docs/development/roadmap.md:4095
  "**AD-443: Agent Mobility Protocol — Transfer Certificates & Memory Portability** *(planned)* — OSS infrastructure for agent mobility across ProbOS instances. (1) Transfer Certificate VC — W3C Verifiable Credential ... (2) `import_chain()` / `verify_remote_chain()` ... (3) Memory portability hooks — Standing Orders Federation tier declares memory policy (Clean Room / Selective / Full) ... (4) Slot re-assignment — existing sovereign DID maps to a new slot ... *Connects to: AD-441 (DIDs, Identity Ledger), AD-441b (Ship Commissioning), Standing Orders (Federation tier), Federation (Phase 29+). Commercial features (Global Instance Registry, fleet dashboard, compliance) tracked in the commercial repository.*"

# AD-443 cross-references (verified):
docs/development/roadmap.md:7003     # AD-499 birth-provenance preservation: "If agent Forge transfers from Enterprise to Defiant via AD-443, they remain `Forge [Enterprise]`"
docs/development/roadmap.md:7234     # AD-693 federation knowledge sync: "Related: AD-443 (Transfer Certificates)"
decisions-era-4-evolution.md:1305    # AD-499 references AD-443: "Ship name is **birth provenance**, not current assignment — persists across transfers (AD-443)"

# Identity substrate live (verified):
src/probos/identity.py:1             # "AD-441: Sovereign Agent Identity — DIDs, Birth Certificates, Identity Ledger."
src/probos/identity.py:102           # class AgentBirthCertificate (W3C VC)
src/probos/identity.py:189           # class ShipBirthCertificate (W3C VC)
src/probos/identity.py:286           # class LedgerBlock
src/probos/identity.py:307-363       # _IDENTITY_SCHEMA — birth_certificates, identity_ledger, ship_birth_certificate, slot_mappings, asset_tags
src/probos/identity.py:366           # class AgentIdentityRegistry
src/probos/identity.py:377           # def __init__(self, data_dir: Path, connection_factory: ConnectionFactory | None = None) — ConnectionFactory-backed (cloud-ready storage convention)
src/probos/identity.py:541           # def get_by_uuid(self, agent_uuid: str) -> AgentBirthCertificate | None
src/probos/identity.py:545           # def get_by_slot(self, slot_id: str) -> AgentBirthCertificate | None
src/probos/identity.py:623           # async def issue_birth_certificate(...) -> AgentBirthCertificate (with slot_mappings INSERT OR REPLACE)
src/probos/identity.py:717           # async def resolve_or_issue(...)
src/probos/identity.py:753           # async def _append_to_ledger(self, certificate_hash: str, agent_did: str) -> LedgerBlock — serialized via _ledger_lock
src/probos/identity.py:832           # async def verify_chain(self) -> tuple[bool, str] — local hash-chain validation pattern
src/probos/identity.py:879           # async def export_chain(self) -> list[dict[str, Any]] — full chain export with attached birth-cert VCs

# Federation substrate live (verified):
src/probos/federation/bridge.py:23           # class FederationBridge
src/probos/federation/bridge.py:31-54        # __init__(node_id, transport, router, intent_bus, config, self_model_fn, validate_fn=None)
src/probos/federation/bridge.py:137-160      # async def handle_inbound — dispatches on message.type (intent_request/intent_response/gossip_self_model/ping)
src/probos/federation/transport.py:34        # class FederationTransport (ZMQ ROUTER/DEALER)
src/probos/federation/transport.py:111       # async def send_to_peer(self, peer_node_id, message)
src/probos/federation/transport.py:120       # async def send_to_all_peers(self, message)
src/probos/federation/transport.py:148       # async def deliver_response(self, from_node_id, message) — correlation by message_id
src/probos/federation/mock_transport.py      # in-process round-trip transport for tests
src/probos/types.py:664-671                  # class FederationMessage — type: str, free-form (docstring lists examples; new types accepted non-breakingly)
src/probos/config.py:797-805                 # class FederationConfig (BaseModel) — enabled, node_id, bind_address, peers, forward_timeout_ms, gossip_interval_seconds, validate_remote_results

# Standing Orders Federation tier composition (verified):
src/probos/cognitive/standing_orders.py:7    # "federation.md  -- Universal principles (immutable across all instances)"
src/probos/cognitive/standing_orders.py:386-389  # Tier 2 composes federation.md after Tier 1 hardcoded identity
config/standing_orders/federation.md:94-101  # existing Memory section (mobility addendum will append cleanly after this)

# Greenfield (verified absent — no collision):
src/probos/mobility.py                       # absent → new module
tests/test_ad443_mobility.py                 # absent → new test file
foreign_chains table                         # not in _IDENTITY_SCHEMA → new
foreign_birth_certificates table             # not in _IDENTITY_SCHEMA → new
transfer_certificates table                  # not in _IDENTITY_SCHEMA → new

# Carve-out language at line 4095 (verified neutral — no banned patterns):
docs/development/roadmap.md:4095
  "Commercial features (Global Instance Registry, fleet dashboard, compliance) tracked in the commercial repository."
# Verified 0 hits across the 11 hook-banned patterns at this line. The literal
# alternation regex is intentionally NOT reproduced here — running the hook
# against the staged dispatch + prompt is the canonical audit (see Acceptance
# criterion #3 in the prompt).

# Pre-commit hook patterns confirmed (verified):
.git/hooks/pre-commit:5-17                   # COMMERCIAL_PATTERNS array — 11 literal patterns (see Commercial-leak audit table above)

# Cloud-ready storage convention preserved (verified):
src/probos/identity.py:31                    # from probos.protocols import ConnectionFactory, DatabaseConnection
src/probos/identity.py:387                   # from probos.storage.sqlite_factory import default_factory
# AD-443 v1 reuses _connection_factory and _db on AgentIdentityRegistry — no direct aiosqlite.connect() calls.
```

## Captain rule honored — full breakdown

| Wave 87 action | Captain rule status |
|---|---|
| AD-443a Transfer Certificate VC + issuance (~10 tests) | "don't defer unless no choice" — built |
| AD-443b `import_chain` / `verify_remote_chain` + foreign-chain persistence (~12 tests) | "don't defer unless no choice" — built |
| AD-443c MemoryPolicy enum + apply_memory_policy + FederationConfig.memory_policy + federation.md addendum (~10 tests) | "don't defer unless no choice" — built |
| AD-443d Slot reassignment (foreign + native) + `foreign_birth_certificates` table + birth-provenance preservation (~10 tests) | "don't defer unless no choice" — built |
| AD-443e FederationBridge transfer/chain wire types + MockFederationTransport round-trip (~10 tests) | "don't defer unless no choice" — built |
| Standing Orders Federation tier — federation.md "Mobility & Memory Portability" addendum (~5 tests) | "don't defer unless no choice" — built |
| Live cross-process ZMQ multi-instance demo parked → AD-443f | NO CHOICE — needs ops-tooling for second-instance launch + observability; in-process MockFederationTransport round-trip in v1 already proves protocol correctness |
| Trust-weighted automatic acceptance parked → AD-443g | NO CHOICE — depends on AD-479 federated capability map (not yet shipped); v1 ships chain-integrity-based acceptance only |
| A2A Agent Card export of Transfer Certificates parked → AD-443h | NO CHOICE — depends on AD-480 A2A agent cards (not yet shipped) |
| Global Instance Registry, fleet dashboard, fleet-wide compliance | OUT-OF-REPO BY DESIGN — `roadmap.md:4095` carves these to the private commercial-repo path token |

## What this wave does NOT change

- No edits to UI surface. `vitest` delta = **0** (target unchanged at 306). `ui/package.json` untouched.
- No new Python dependency. `pyproject.toml` untouched.
- No edits to `BaseAgent`, `IntentMessage`, `IntentResult`, `TaskDAG`, or any cross-layer protocol shape.
- No edits to `runtime.py` boot ordering. `AgentIdentityRegistry` and `FederationBridge` already wire via `infrastructure.py` / `organization.py` startup modules; AD-443 reuses those existing wires.
- No edits to `acm.py`. Onboarding flow unchanged for v1; foreign-cert onboarding via Standing Orders federation tier policy is a v2 concern (AD-443g).
- No edits to consensus, trust scorer, episodic store, attention, dreaming, decomposer, or shell surface. Memory policy filter is a pure utility function — episodic store integration is a downstream caller's responsibility (AD-443g territory).
- No new EventType. Identity events emit through the existing `runtime.emit_event` path with neutral string descriptors (no schema change).
- No new pool, no new agent, no new Intent, no router edit, no Hebbian touch.
- No new AD numbers minted. Sub-AD letters a–h are organizational only (AD-474 a–h Wave 86 / AD-473 a–g Wave 85 / AD-512 a–f Wave 84 precedents).
- No commercial language. AD-443 carves commercial concerns to the private commercial-repo path token at the roadmap line itself; Wave 87 is fully OSS substrate. Pre-commit hook banned phrases confirmed 0 hits across dispatch, prompt, and this notes block (every reference uses placeholder forms — see Commercial-leak audit table above).

## Tracking updates (Builder responsibility, post-build)

- `PROGRESS.md` — bump current pytest count line from 11705 to the new total (expected ≥ 11760); record Wave 87 closure with sub-AD breakdown in the era progress file.
- `docs/development/roadmap.md:4095` — mark AD-443 with `*(v1 shipped 2026-05-06 — see Wave 87; 443f/g/h parked with forcing functions; commercial features remain carved out per this line)*`.
- `decisions-era-4-evolution.md` — append AD-443 row to the AD table (5 sub-AD letters + 3 future-AD letters + 3 commercial-repo carve-outs; in-process MockTransport round-trip cited as v1 correctness proof; AD-479/AD-480 named as forcing functions for 443g/443h).
- GH #42 close with the closure note above.

## Builder hand-off

Read `prompts/ad-443-mobility-v1.md` for the build spec. One commit. Acceptance: `pytest tests/ -q -n 4 --dist=loadfile` shows ≥ 11760, `cd ui && npx vitest run` shows 306 unchanged (305 passing + 1 pre-existing `WardRoomDmSync` failure), `git commit` succeeds with the pre-commit hook as the canonical commercial-leak audit (the hook itself runs the literal-pattern sweep against staged files; this dispatch and the prompt deliberately avoid reproducing the literal patterns to prevent self-trip).
