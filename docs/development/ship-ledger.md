# How Literally Should ProbOS Take "Ledger"?

**Status:** Design note; the Captain's decisions of 2026-10-30 are in section 7. Not an AD; it allocates no number and creates no work by itself.
**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-30. Verified against `main` at `1ffbdc61`.
**Placement:** a companion to [Probabilistic Crew, Deterministic Ship](deterministic-ship.md), invariant 4 ("a fixed past").

> **Question (the Captain's).** The thesis of the deterministic ship speaks of "a system of record, like a ledger".
> How literally should ProbOS take that? Does it already have a ledger, should it have one, and is this a use case
> for blockchain?

---

## 1. Short answer

- **ProbOS already keeps ledgers, plural.** Three stores are hash-chained (the EventLog, the Identity Ledger and the
  security AuditLog), Ship's Records is a git repository, and about a dozen other tables are append-only by rule.
  "Ledger" is already literal in the sense that matters: an append-only record whose past entries are not rewritten.
- **What it lacks is one thing a ledger implies: the ability to prove the whole record is unchanged.** One chain breaks
  in normal operation (BF-942, #1706), one is never verified in production, the others are verified only at boot or on
  request, and nothing ties the separate stores together. Every guarantee is held on the same disk as the data it
  protects.
- **The literal step worth taking is small:** a ship's log of chain heads. Every so often, record each store's
  current head hash in one append-only, hash-chained record, signed with the ship's key when one is configured. Then
  copy that head off the ship to a witness. Without a witness it protects against bugs and stray writers, not against
  anyone who controls the machine.
- **No blockchain inside a ship.** A blockchain is a way for parties who do not trust each other, and have no common
  authority, to agree on one history. A ship has one authority, the Captain, on one install. A blockchain would add
  cost and latency and would collide with the Captain's right to erase (AD-754).
- **Between ships, use a transparency log, not a blockchain.** Ships run by different operators are where
  blockchain-like properties start to matter. The established answer there is a Certificate-Transparency-style log:
  a Merkle tree, signed tree heads, and independent witnesses. ProbOS's DIDs, Ed25519 key binding and signed identity
  chains (AD-1196 to AD-1198) already point that way.

## 2. What ProbOS keeps today

"Chained" means each entry carries the hash of the one before, so changing an old entry breaks every later link.
"Verified" means production code, not only tests, re-derives the chain.

| Store | Chained? | Verified in production? | Owner and anchor | Known gaps |
|---|---|---|---|---|
| **EventLog** (AD-490), the system of record for events | Yes: SHA-256 over `prev_hash` and the row (`substrate/event_log.py:90-110`, `:745-763`) | **No.** `verify_chain` (`event_log.py:1211`) has no production caller; only tests call it | `EventLog` | `prune` deletes the oldest rows, which severs the chain (`event_log.py:1250-1262`; BF-942, #1706). It runs hourly with a 7-day, 100,000-row retention by default (`runtime.py:4027-4045`, `config_models/core.py:148-150`), so the chain fails on any vessel older than a week. |
| **Identity Ledger** (AD-441) | Yes: `LedgerBlock` (`identity.py:350-369`) | On request: `GET /api/identity/ledger` (`routers/identity.py:52-58`). Foreign chains are checked on import when federation is armed (`identity.py:372-379`) | `AgentIdentityRegistry` | Blocks are not individually signed. An operator's peer reset deletes one foreign ship's stored chain by design (`identity.py:1641`, AD-1198 slice 2c). |
| **Key events** (AD-1196) | Anchored in the Identity Ledger and signed with Ed25519 (`identity_keys.py:1-10`) | When armed, on every chain import (`federation/continuity.py:1-30`) | Same | Off by default: `federation.identity_keys_enabled = False` (`config.py:2521`). |
| **Transfer marks** (AD-1198 2b-ii) | No, append-only; each row names the chain head it was judged against (`identity_transfer_marks.py:11-13`) | Re-judged on armed start | Same | Federation-only. |
| **Security AuditLog** (AD-456, AD-1278) | Yes, with a truncation anchor so a capped log reads as truncated, not tampered (`security/audit.py:1-29`, `:89-110`) | At boot, on rehydrate (`startup/finalize.py:4751-4764`) | `AuditLog` | A failure only logs a warning; the message itself says the Captain alert path is still to come. |
| **Assistant audit log** (AD-754; a second class also named `AuditLog`) | No | No | `security/audit_log.py` | Deletes rows after 90 days (`audit_log.py:182-188`) and redacts in place to `[DELETED]` (`:96-109`). Correct for erasure, but it is not a fixed-past record. |
| **Ship's Records** | Git: each commit hashes its parent (`knowledge/records_store.py:207-212`, `:363-366`) | No. Nothing runs `git fsck` or compares heads | `RecordsStore` | `auto_commit` can be turned off (`config_models/knowledge.py:285`). A failed commit is logged at debug and swallowed (`records_store.py:1312-1320`), so a write can sit on disk uncommitted with no notice. The `_commit` docstring says "Debounced", but the body does not debounce. Commits are unsigned, and git's default object hash is SHA-1. |
| **Ship's Archive** (AD-524, AD-1341) | No; append-only by rule, one write path (`knowledge/archive_store.py:1-17`) | No | `ArchiveStore` | The Captain's erase deletes the row and leaves a marker that deliberately holds **no hash** (`archive_store.py:593-621`). |
| **Archive snapshot ledger** (AD-1341 S6) | No; rows never deleted, each with the snapshot file's SHA-256 (`knowledge/archive_ledger.py:1-17`) | No | `ArchiveLedger` | Written only by the offline CLI. |
| **ACM lifecycle transitions** | No; append rows with `initiated_by` (`acm.py:90-96`) | No | ACM | The current-state row is updated in place (`acm.py:282`), which is fine: the transitions are the history. |
| **Trust** | No. `trust_outcome_receipts` keep `payload_sha256` and `evidence_sha256` (`consensus/trust.py:39-50`) | No | `TrustNetwork` | `trust_scores` is current state, updated in place and deleted on reset or identity merge (`trust.py:1223`, `:1315`); `trust_snapshots` keep pre-merge rows (`:53`). |
| **Workforce booking timestamps** | No; documented as append-only (`workforce.py:11`, `:1308`) | No | `WorkItemStore` | **Not append-only in practice:** `delete_work_item` deletes them (`workforce.py:10853-10876`), reachable from `DELETE` on the workforce API (`routers/workforce.py:810-818`). |
| **Completion calibration** (`economic_calibration.py:639`) | No; outcome and resolution rows are inserted (`:235-292`) | No | `CompletionCalibrationLedger` | Derived statistics are updated in place (`:995`), which is fine. |
| **Episode eviction audit** (AD-541f) | No, explicitly "no hash-chain" (`cognitive/eviction_audit.py:1-8`) | No | `EvictionAuditLog` | Log-and-degrade: an audit failure never blocks an eviction. |
| **Directives** (AD-386) | No | No | `DirectiveStore` | Revocation sets `revoked_at` in place (`directive_store.py:187`); there is no separate history. |

**Not ledgers, and should not be treated as ones:** the AD-1346 shadow admission store is bounded telemetry and is
pruned by design (`admission/store.py:1-25`). Work permits carry a mutable `closed` flag (`tools/work_permits.py:449`)
and nothing consumes them yet (`:9-13`). Consensus outcomes have no store of their own: in `consensus/` only
`trust.py` creates tables, and `governance/` creates none. The federation envelope store is forward-only state, not
history (`federation_envelope_store.py:1-13`). Classes named "ledger" for in-turn bookkeeping (`WriteLedger`,
`StepLedger`, `ProcedureChallengeLedger`) are working records, not the ship's system of record.

**Terminology fix.** `docs/architecture/federation.md:32` and the AD-441 entry
(`roadmap-era-5-completed.md:3826`) call the Identity Ledger a "hash-chain blockchain". It is a hash chain with one
writer and no consensus; calling it a blockchain invites exactly the confusion this note is about.

## 3. The gaps

1. **A chain breaks in normal operation.** EventLog pruning severs the AD-490 chain (BF-942). Rehashing the kept rows
   would forge history; the fix is a durable truncation anchor like AD-1278's (`event_log.py:1255-1261`).
2. **Verification is patchy and silent.** The EventLog is never verified, the Identity Ledger only when someone asks,
   and the AuditLog at boot with a warning nobody is alerted to. Under invariant 6, a check that never runs or
   that reports only to a log is close to no check.
3. **Each ledger stands alone.** Nothing proves that the EventLog, the identity chain, Ship's Records and the
   Archive, taken together, are the history the ship had yesterday.
4. **Every proof lives on the same disk as the data.** Anyone who can rewrite a store can rewrite its chain too, and
   restoring an old backup of the whole data directory rolls back the chain along with the data. A hash chain only
   detects tampering when someone *else* holds a copy of a recent head. This is the core of the tamper-evident
   logging literature (Crosby and Wallach, 2009) and of Certificate Transparency's witnesses and gossip.

## 4. Proposal: a ship's log of chain heads

**What.** One append-only store, the *head log*. Each entry, called a checkpoint, records for every covered store its
name, its current head, and the size or position at that head. Each checkpoint also carries the hash of the previous
checkpoint and the time. When the ship's key is configured (AD-1196), the checkpoint is signed with it as a detached
JWS (AD-1144). Otherwise it says plainly that it is unsigned.

**What "head" means per store (version 1):**

| Store | Head | Cost to read |
|---|---|---|
| EventLog | `(id, row_hash)` of the last row, plus the truncation anchor once BF-942 lands | One indexed read |
| Identity Ledger | `(block_index, block_hash)` of the tip | One read |
| Security AuditLog | `(sequence, entry_hash)` of the last persisted entry, plus `_truncated_at` | In memory |
| Ship's Records | `git rev-parse HEAD`, plus whether the working tree is clean | One subprocess |

Version 1 covers only stores that already have a chain. The others (Archive, ACM transitions, trust receipts,
booking timestamps, calibration, the snapshot ledger) have no head to record. Bringing them in means giving each one
a chain, or having the head log chain them by recording a digest of the rows added since the last checkpoint. That is
version 2, and it runs straight into erasure (open question 3).

**Verification.** A verifier walks each store's chain from its anchor, confirms that the head recorded in every
checkpoint is reachable in the current chain, and checks the head log's own chain and signatures. It reports one
state per store: **intact**, **truncated at an anchor**, **broken at a position**, or **not verified**, never a bare
pass (invariant 6). It runs at boot, as the AuditLog check already does, then on a schedule and on demand from a CLI
or doctor command. The Captain sees the latest checkpoint, its head digest and the last verification result. A
failure needs a real alert, which no chain has today.

**The witness, which is what makes it more than a checksum.** The checkpoint digest must leave the ship. In rising
order of cost: the Captain copies or exports it (a short digest shown in the HXI or CLI); a federation peer
countersigns it over the signed envelopes AD-1197 already provides; or an RFC 3161 timestamp authority or
OpenTimestamps timestamps it, which sends a 32-byte hash and no data. A witness turns "the store says it is intact"
into "the store still matches what someone outside saw on that date", and it also detects a rollback of the whole
data directory.

**What it defends against.** Bugs that delete or rewrite rows (the BF-942 class), writers that bypass a store's owner
(BF-943 is the file-level cousin), and a silent restore of an older backup. It does not defend against the Captain:
the Captain owns the ship and may erase, which is why erasure has to be designed in rather than treated as tampering.

**Cost.** One small row per checkpoint; reading the version 1 heads is a handful of indexed reads and one `git`
call. A full verification is linear in chain length; the EventLog is capped at 100,000 rows by default. Witnessing
costs a network call per checkpoint, or none if the Captain copies the digest by hand.

### Open questions for the AD that builds it

1. **Signing key and owner.** The ship's DID key exists only when `federation.identity_keys_enabled` is on (default
   off), held in the OS keyring (`identity_key_store.py:119`) or, in development, in plaintext (`:209`). Should the
   head log require it, sign when available, or use a separate local key? A local signature adds little against
   someone who holds the machine; its value is that a third party can verify an exported checkpoint.
2. **Where it lives.** Its own SQLite file through `ConnectionFactory`, beside the stores it covers, and owned by one
   service. It must survive `probos reset`, as the Archive does, and a reset should close the old timeline with a
   final checkpoint that the new timeline's first checkpoint cites.
3. **Erasure.** The Archive's erase marker deliberately keeps no hash of the erased entry, because a hash of short or
   guessable content can confirm what it was. A version 2 digest over Archive rows would break when an entry is
   erased. Options: (a) leave erasable stores out of the head log; (b) give each row a random salt and commit only
   to `H(salt, content)`, deleting the salt on erase, so the commitment survives but reveals nothing, a known
   pattern for erasure on append-only logs (EPRS, 2019); (c) record an erasure as a new head with a signed reason
   and accept that the erased segment can no longer be re-verified. Option (b) changes the Archive's "no hash"
   rule, so it is the Captain's call.
4. **Retention.** Once BF-942 adds an anchor, every checkpoint older than the anchor refers to rows that are gone.
   The verifier should report such checkpoints as "covering pruned history" and check only that the anchor sits on
   the recorded path. The signed head log is also what keeps the anchor itself from being forged: an attacker who
   rewrites rows and resets the anchor no longer matches earlier checkpoints.
5. **Which governance files count.** BF-943 shows agents can rewrite governance files in the running checkout.
   A git tree hash of `config/standing_orders/` and the Constitution would fit in a checkpoint. Considered and
   deferred: BF-943's write floor is the first defence.
6. **Interval.** A fixed interval (hourly, matching the prune loop) or at defined events (boot, shutdown, prune,
   reset). Events are cheaper and give natural points to verify against.

## 5. Is this a use case for blockchain?

**Inside one ship: no.** A blockchain (Nakamoto, 2008; or a permissioned BFT ledger) solves one problem: getting
mutually distrusting parties with no common authority to agree on one append-only history, through proof-of-work or
validator voting. Remove that problem and what remains is a hash chain, which ProbOS already has. A ship has a
common authority, the Captain, and one install. Running a consensus protocol among processes that share an owner,
a disk and a key buys nothing a hash chain plus a witness does not, and it costs latency on every commit point,
operational complexity and a large new dependency.

It would also collide with two things ProbOS chose deliberately:

- **The Captain's right to erase.** AD-754 erasure and the Archive's content-free erase marker exist so that data the
  Captain asks to forget is actually gone. An immutable replicated ledger is built to make that impossible; the
  European Parliament's study on blockchain and the GDPR describes this as a structural tension and recommends
  keeping personal data off-chain (Finck, EPRS, 2019).
- **Two meanings of "consensus".** ProbOS's consensus (`QuorumEngine`, trust-weighted votes on destructive intents)
  is judgement: should this happen? Blockchain consensus is storage agreement: what order did things happen in?
  Using the second to stand in for the first, or the reverse, would blur the line `deterministic-ship.md` draws
  between what is probabilistic and what is recorded.

**Between ships: blockchain-like properties matter; a blockchain still is not the best tool.** Ships run by
different operators do not share an authority, so one ship's history is a claim another ship must be able to check.
That is exactly the setting Certificate Transparency was built for: independent logs, append-only Merkle trees,
signed tree heads, inclusion and consistency proofs, and monitors and witnesses who compare what they were shown, so
a log cannot show different histories to different parties (RFC 6962, now RFC 9162). Sigstore's Rekor applies the
same design to software signing, now on a tile-based log, with witness cosigning in progress. It needs no mining and
no token, and each ship stays the only writer of its own log.

What the federation ADs already provide, and where this fits:

- **AD-441, AD-443:** `did:probos` identifiers, birth and transfer certificates, and an exportable, importable
  Identity Ledger chain.
- **AD-1196:** the ship's DID bound to an Ed25519 key, with rotation and recovery, as key events anchored in that
  chain.
- **AD-1197:** canonical signed envelopes with replay protection.
- **AD-1198:** authenticated peer admission, chain resync, and verification of every chain relied on.

Together they give each ship a signed, verifiable identity history that its peers check. What they do not give is
a peer that *remembers* another ship's head and would notice a fork or rollback later. The envelope store keeps a
forward-only hold of each peer's key events, which is the start of that. A federation transparency log would extend
it: each ship publishes signed checkpoints of its head log, and peers countersign them as witnesses. Epic #1140
(AD-1196 to AD-1198) is **closed**, so this needs a new issue when federation work resumes; it does not belong under
#1140.

**Optional public anchoring.** A ship may periodically timestamp its checkpoint digest on a public chain
(OpenTimestamps) or with an RFC 3161 authority. Only a 32-byte hash leaves the ship, so it conflicts with neither
erasure nor privacy. It proves only "this digest existed by this date", which is the one thing a single ship cannot
prove to itself.

## 6. Recommended sequence

1. **BF-942 (#1706).** A durable truncation anchor for the EventLog, after the AD-1278 pattern. Nothing later is
   sound without it.
2. **Verify what exists and say so.** One verification service for the three chains plus `git fsck` on Ship's
   Records, run at boot and on demand, reporting intact, truncated, broken or not verified, with a Captain alert on
   failure. This also takes on the AuditLog's missing alert. It could be a BF or a small AD.
3. **Fix the false "append-only" claims found here.** Booking timestamps deleted by `delete_work_item`, and Ship's
   Records' swallowed commit failure. These are candidate BFs; file them only after confirming reach.
4. **The head log (a future AD).** Version 1 over the chained stores, with a manual or RFC 3161 witness.
5. **Version 2 coverage** of the Archive and other append-only tables, after the erasure decision below.
6. **A federation transparency log**, as a new issue when federation resumes, built on AD-1196 to AD-1198.

## 7. Decisions (Captain, 2026-10-30)

The Captain took the recommended option on all five:

1. **The head log is adopted as a future AD,** to be filed after steps 1 and 2 (BF-942, then verification with an alert). It is small and makes invariant 4 checkable.
2. **Witness:** start with the Captain's own copy of the digest, plus an optional RFC 3161 or OpenTimestamps anchor. Peer witnesses come only with federation.
3. **Erasure versus coverage:** the Archive keeps its "no hash of erased content" rule and stays out of the head log for now. Salted commitments (option b in section 4) are not adopted.
4. **Signing:** the head log is signed only when the ship's key is configured, and records say "unsigned" otherwise. The key is not a prerequisite.
5. **Blockchain:** ProbOS uses hash chains and transparency logs, not a blockchain, unless a future need appears for agreement among parties with no common authority.

## 8. Prior art

- S. A. Crosby and D. S. Wallach, "Efficient Data Structures for Tamper-Evident Logging", USENIX Security 2009
  ([USENIX](https://www.usenix.org/conference/usenixsecurity09/technical-sessions/presentation/efficient-data-structures-tamper-evident)).
  **Adopted:** detection needs a commitment held outside the logger. **Deferred:** their history tree, with
  logarithmic proofs, is worth using only when a third party audits (federation).
- B. Laurie, A. Langley, E. Kasper, RFC 6962 (2013), and B. Laurie, E. Messeri, R. Stradling, RFC 9162, Certificate
  Transparency 2.0 (2021) ([RFC 9162](https://datatracker.ietf.org/doc/html/rfc9162)). **Adopted** as the model for
  federation: Merkle tree, signed tree heads, consistency proofs, and monitors.
- Trillian and Sigstore Rekor (Rekor v2 moved to a tile-based Trillian-Tessera log; witness cosigning is in progress)
  ([Sigstore blog](https://blog.sigstore.dev/index.xml)). **Considered:** reference implementations if ProbOS ever
  runs a shared federation log; too heavy for one ship.
- Git as a Merkle DAG: every commit hashes its tree and parents, so Ship's Records already has a chain whose head
  is the commit id. **Adopted:** use it as is.
- C. Adams et al., RFC 3161, Time-Stamp Protocol (2001), and OpenTimestamps (P. Todd). **Adopted** as optional
  external timestamps that send only a hash.
- M. Finck, *Blockchain and the General Data Protection Regulation*, EPRS/STOA, PE 634.445, July 2019
  ([PDF](https://www.uni.lu/wp-content/uploads/sites/3/2024/08/EPRS_STU2019634445_EN.pdf)). **Adopted:** keep
  personal data off any immutable shared log; erasure needs designing in.
- Internal: no earlier ProbOS design of a Merkle tree, transparency log or blockchain. The only mentions are the
  "hash-chain blockchain" wording above, the warm-boot design note's use of the EventLog chain as a tamper-evident
  witness (`docs/research/warm-boot-fragmentation-design.md:34`), and the Nooplex vision's discussion of DAOs and
  token-curated registries as cross-organisation governance (`Vibes/Nooplex_Final.md:141`), which this note leaves
  to federation.
- Not fetched in full here (the hosts were unreachable from this session): the RFC 9162 text itself and the Crosby
  and Wallach paper. Their summaries above rest on the RFCs' and paper's well-known content and search abstracts.
