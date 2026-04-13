# Clearance System Design — Separation of Rank and Access Eligibility

**Author:** Architect (AD-620/621/622 scoping)
**Date:** 2026-04-13
**Status:** Design complete, ready for AD build prompts

## Navy Reference Model

The US military separates three concepts that ProbOS currently conflates:

### Rank
Position in the chain of command, earned through performance and time-in-service.
Determines authority and responsibility. An E-6 and an O-3 have different ranks
but could hold the same clearance level. **Rank is about who you are in the
hierarchy.**

### Security Clearance
Eligibility to access classified information at a given level. Levels:
Confidential → Secret → Top Secret → TS/SCI. Clearance is granted to
**billets (positions)**, not just individuals. A position might require TS/SCI
regardless of the rank of the person filling it. A general without the right
compartment access cannot view certain material, while a junior analyst with
proper authorization can. **Clearance is about what information you're eligible
to access.**

> "No individual is granted automatic access to classified information solely
> because of rank, position, or a security clearance."

### Access (Need-to-Know)
Actual permission to see specific classified material. Requires BOTH appropriate
clearance AND a demonstrated need to know. Having TS clearance doesn't mean you
can read every TS document — you must have operational justification for that
specific information. **Access is clearance + justification.**

### Special Access Programs (SAPs)
Compartmented programs with access controls beyond the normal classification
system. Even with TS/SCI, you need to be specifically "read into" a SAP.
Access is tracked, controlled, and can be revoked independently of base
clearance. SAPs limit access to a small subset of individuals and permit
additional security measures.

### Key Principles
1. **Clearance follows the billet.** The position determines what clearance is
   required. When you're assigned to that billet, you're investigated for that
   clearance. When you transfer, your clearance may lapse.
2. **Rank does NOT determine clearance.** A Senior Chief (E-8) might have Secret
   while a Lieutenant JG (O-2) in intelligence has TS/SCI. It's about the job.
3. **Need-to-know gates access within clearance.** Clearance establishes
   eligibility; need-to-know justifies specific access.
4. **Compartmentation is additive.** SAP/SCI access layers on top of base
   clearance. You can be "read into" or "read out of" programs independently.

## ProbOS Current State

| Concept | Current Implementation | Problem |
|---------|----------------------|---------|
| Rank | `Rank` enum (Ensign→Senior), purely trust-driven via `Rank.from_trust()` | Rank is behavioral maturity AND access eligibility — conflated |
| Clearance | Does not exist. `RecallTier` mapped 1:1 from Rank via `recall_tier_from_rank()` | A Bridge officer with trust 0.5 gets ENHANCED recall, same as a Science Ensign |
| Need-to-know | `RetrievalStrategy` (SHALLOW/DEEP) based on intent classification | Already exists, sound design |
| SAP/Compartments | Does not exist. AD-619 added `has_ship_wide_authority()` as a hack | Hardcoded set, not principled |
| Billet clearance | Not in ontology. `Post` dataclass has no clearance field | Ship's Counselor has same access as any crew member |

### Where Rank Is Currently Checked

Rank currently does triple duty:

| Function | What it gates | File |
|----------|--------------|------|
| `recall_tier_from_rank()` | Memory recall capability | earned_agency.py |
| `agency_from_rank()` | Behavioral agency level | earned_agency.py |
| `can_respond_ambient()` | Ambient response permission | earned_agency.py |
| `can_think_proactively()` | Proactive thought permission | earned_agency.py |
| `can_perform_action()` | Action-space permissions (endorse, reply, DM, lock/pin) | earned_agency.py |
| `Rank.from_trust()` in perceive() | Recall tier for episodic memory | cognitive_agent.py |
| `Rank.from_trust()` in proactive | Recall + self-monitoring tier | proactive.py |

**Only `recall_tier_from_rank()` is an access/clearance concern.** The rest
(agency, ambient response, proactive thinking, action permissions) are correctly
rank-driven — they're about behavioral maturity, not information access.

## ProbOS Proposed Model

| Navy Concept | ProbOS Analog | Implementation |
|---|---|---|
| **Rank** | `Rank` enum (unchanged) | Trust-driven, earned. Gates behavioral agency. |
| **Clearance** | `RecallTier` (reused, new computation) | `effective_recall_tier(rank, billet, grants)` — max of all sources |
| **Billet Clearance** | `Post.clearance` field in ontology | Each post defines its required RecallTier |
| **Need-to-Know** | `RetrievalStrategy` (unchanged) | Intent-based classification gates specific queries |
| **SAP** | `ClearanceGrant` records | Captain-issued, time-limited, scoped, revocable |

### How It Solves the Counselor Problem

- Echo's **rank** = Lieutenant (trust 0.5) → behavioral maturity, agency level
- Echo's **billet clearance** = ORACLE (Counselor post in ontology requires it)
- Echo's **effective RecallTier** = max(ENHANCED from rank, ORACLE from billet) = ORACLE
- Echo's **access** = Oracle queries gated by clearance (no strategy gate needed for clearance-holders)

No `has_ship_wide_authority()`. No hardcoded set. The ontology defines the
requirement, the clearance system computes eligibility.

### Billet Clearance Assignments

From the organization chart, natural clearance assignments:

| Post | reports_to | Billet Clearance | Rationale |
|---|---|---|---|
| `captain` | null | ORACLE | Ship commander, full access (external/human) |
| `first_officer` | captain | ORACLE | Direct Captain report, ship-wide authority |
| `counselor` | captain | ORACLE | Direct Captain report, crew-wide clinical authority |
| `chief_engineer` | first_officer | FULL | Department head, leadership authority |
| `chief_science` | first_officer | FULL | Department head (dual-hatted with First Officer) |
| `chief_medical` | first_officer | FULL | Department head |
| `chief_security` | first_officer | FULL | Department head |
| `chief_operations` | first_officer | FULL | Department head |
| All officers | chief_* | ENHANCED | Department members, proven competence |
| Default (no post) | — | BASIC | Unassigned, minimal access |

**Rule of thumb:**
- `reports_to: captain` → ORACLE (Bridge officers, ship-wide responsibility)
- `authority_over: [...]` non-empty → FULL (department leadership)
- `reports_to: chief_*` → ENHANCED (department members)
- No post assignment → BASIC (unassigned)

This can be derived automatically from the ontology structure OR explicitly
set per-post. Explicit is better — it allows exceptions without changing the
derivation logic (a Security Officer might need FULL for investigations even
though they report to a chief).

### Oracle Gate Simplification

Currently the Oracle gate requires `RecallTier.ORACLE` AND `RetrievalStrategy.DEEP`
(plus the AD-619 hack for ship-wide authority). With a proper clearance system:

**Clearance IS the gate.** If you have ORACLE clearance (from any source — rank,
billet, or grant), Oracle access is authorized. The strategy gate (DEEP
requirement) was a cost optimization, not an access control. But it creates
confusing UX — a senior officer asks a question in a DM and Oracle doesn't fire
because the intent is classified as SHALLOW.

**Proposed:** Remove the strategy gate for Oracle. `RecallTier.ORACLE` alone
is sufficient. The clearance system ensures only authorized agents reach ORACLE tier.
Cost concerns can be addressed by Oracle's own internal budget limits (`k_per_tier`,
`max_chars`), not by blocking the query.

### Channel Visibility (Separate from Clearance)

Channel subscriptions are about **visibility** (being in the room), not
**capability** (what you can do). The ontology can drive this:

| Condition | Channel Subscription |
|---|---|
| Every crew agent | Own department channel |
| `reports_to: captain` | ALL department channels |
| All crew | Ship-wide channels (All Hands, Proposals, Recreation, Creative) |

Future extension: `authority_over` could grant visibility into subordinate
departments' channels for department chiefs who oversee cross-department work.

### Special Access Grants (SAP Analog)

Captain-issued grants for specific duties or projects:

```
ClearanceGrant:
  id: str               # unique grant ID
  target_agent_id: str   # who receives the grant
  recall_tier: RecallTier # granted tier level
  scope: str             # "general" | "project:{name}" | "investigation:{id}"
  reason: str            # justification (audit trail)
  issued_by: str         # Captain's agent_id or "system"
  issued_at: float       # timestamp
  expires_at: float | None  # None = until revoked
  revoked: bool          # soft-delete
```

**Use cases:**
- Captain assigns a junior agent to a security investigation → grants ORACLE
  for the duration
- Temporary elevated recall for a cross-department project
- Emergency access during an incident

**Governance:**
- Only Captain (or First Officer with Captain's authority) can issue grants
- Grants are logged and auditable
- Expired/revoked grants are retained for audit history
- `effective_recall_tier()` considers active, non-expired, non-revoked grants

## AD Breakdown

### AD-620: Clearance Model Foundation

**Scope:** Medium (5 source files modified, 1 config file modified)
**Depends on:** None
**Cleans up:** AD-619 (removes ship-wide authority bypass)

1. Add `clearance` field to `Post` dataclass in `ontology/models.py`
2. Add `clearance` field to all posts in `config/ontology/organization.yaml`
3. Add `effective_recall_tier()` function to `earned_agency.py` — computes
   RecallTier from max(rank_tier, billet_tier, grant_tiers)
4. Add `resolve_billet_clearance()` to `ontology/service.py` — looks up
   the post's clearance for a given agent_type
5. Modify `cognitive_agent.py` perceive() — replace `recall_tier_from_rank()`
   with `effective_recall_tier()`, remove AD-619 `_has_swa` hack
6. Modify `proactive.py` — replace `recall_tier_from_rank()` with
   `effective_recall_tier()` at all recall tier resolution points
7. Simplify Oracle gate — remove strategy requirement, clearance is the gate
8. Remove `_SHIP_WIDE_AUTHORITY_TYPES` and `has_ship_wide_authority()` from
   `crew_utils.py`

**Key design decisions:**
- No new enum — reuse `RecallTier` as the unit of clearance
- Explicit clearance per post (not derived from reports_to) — allows exceptions
- `recall_tier_from_rank()` preserved for backward compatibility, called
  internally by `effective_recall_tier()` as one input source
- Oracle gate simplified: clearance alone, no strategy requirement

### AD-621: Billet-Driven Channel Visibility

**Scope:** Small (2 source files modified)
**Depends on:** AD-620 (needs Post.clearance and ontology resolution)

1. Modify `startup/communication.py` — replace `has_ship_wide_authority()`
   with ontology-driven subscription logic. Bridge officers (`reports_to: captain`)
   get all department channels.
2. Remove `has_ship_wide_authority` import and usage
3. Handle ontology timing — either resolve billet data from a static source
   (like organization.yaml directly) or move subscription after ontology init

**Key design decisions:**
- Channel visibility is ontology-driven, not clearance-driven. Being in a
  room and having access to capabilities are separate concerns.
- `reports_to: captain` → all department channels (derived from org chart)
- Future: `authority_over` could grant subordinate department channel access

### AD-622: Special Access Grants (ClearanceGrant)

**Scope:** Medium (4 source files modified, 1 new file)
**Depends on:** AD-620 (ClearanceGrant feeds into effective_recall_tier)

1. Add `ClearanceGrant` dataclass to `earned_agency.py`
2. Add grant storage — either on `CrewProfile` (list of grants) or a
   separate `ClearanceGrantStore` (SQLite-backed for audit trail)
3. Captain command to issue grants — new command in `experience/commands/`
   or via directive mechanism
4. Captain command to revoke grants
5. Integrate with `effective_recall_tier()` — active grants are one input
6. Grant audit logging

**Key design decisions:**
- Grants are persistent (survive restart) — stored in DB, not memory
- Grants have explicit expiration — prevents orphaned elevated access
- Revocation is soft-delete (record retained for audit)
- Only Captain/First Officer can issue (enforced by rank check on issuer)

## Build Order

```
AD-620 (Foundation) → AD-621 (Channel Visibility) → AD-622 (Grants)
```

AD-620 is the foundation. AD-621 and AD-622 build on it independently
(could be parallelized after AD-620 completes).

## What Gets Removed (AD-619 Cleanup)

| File | What's removed | Replaced by |
|---|---|---|
| `crew_utils.py` | `_SHIP_WIDE_AUTHORITY_TYPES`, `has_ship_wide_authority()` | Billet clearance in ontology |
| `cognitive_agent.py` | Recall tier override (`_has_swa`, lines 2691-2696) | `effective_recall_tier()` |
| `cognitive_agent.py` | Strategy gate relaxation (`_swa` in Oracle condition) | Simplified Oracle gate (clearance only) |
| `startup/communication.py` | `has_ship_wide_authority` in subscription loop | Ontology-driven subscription (AD-621) |

AD-619's **channel subscriptions** (the valuable part) are preserved and
improved — moved from a hardcoded set to ontology-driven logic.

AD-619's **Oracle bypass** (the hack) is eliminated — replaced by principled
billet clearance.

## Sovereign Memory Principle (Preserved)

Nothing in this clearance system changes the sovereign memory principle.
Clearance determines what **system capabilities** an agent can access
(Oracle queries, recall budget, etc.), not what **other agents' memories**
they can read. The BF-164 rejection stands:

- ORACLE clearance → access to Oracle Service (Tier 2 Records + Tier 3 Operational + Tier 1 own shard)
- ORACLE clearance ≠ access to other agents' episodic shards
- Cross-agent awareness comes from observation (channels) and interaction (DMs), not memory access

## Key References

- `src/probos/earned_agency.py` — RecallTier, Rank mappings, agency functions
- `src/probos/ontology/models.py:20-26` — Post dataclass
- `config/ontology/organization.yaml` — all posts with reports_to/authority_over
- `src/probos/cognitive/cognitive_agent.py:2684-2696` — recall tier resolution + AD-619 override
- `src/probos/cognitive/cognitive_agent.py:2843-2853` — Oracle gate
- `src/probos/proactive.py:304,828,1350` — rank-based checks
- `src/probos/crew_utils.py` — ship_wide_authority (to be removed)
- `src/probos/startup/communication.py:135-176` — subscription loop
- `src/probos/crew_profile.py:130-135` — rank fields on CrewProfile
- `src/probos/ontology/service.py:131,440-450` — post resolution, rank enrichment
