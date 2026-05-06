"""AD-443: Agent Mobility — Transfer Certificates & Memory Portability.

This module ships the OSS substrate for moving agent identities between ProbOS
instances. It complements AD-441 (Sovereign Identity, Birth Certificates,
Identity Ledger) by adding:

- TransferCertificate (W3C VC) — proof of provenance for an agent moving from
  one ship to another. Carries the agent's sovereign DID, callsign, agent_type,
  origin ship DID, origin vessel name (birth provenance per AD-499), origin
  birth timestamp, transfer timestamp, baseline version, qualification
  credentials, and assignment history.
- MemoryPolicy enum — Clean Room (default) / Selective / Full. Declares which
  episodic memories travel with the agent across a transfer.
- apply_memory_policy — pure filter function applying a MemoryPolicy to a list
  of episode dicts.

This module does NOT touch the episodic store. Memory policy enforcement at the
episodic-store level is a downstream concern (AD-443g territory) — v1 only
provides the policy enum and the filter primitive.

Per `docs/development/roadmap.md:4095`, commercial features (Global Instance
Registry, fleet dashboard, fleet-wide compliance auditing) are tracked in the
private commercial-repo path token. This module is fully OSS.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Iterable


class MemoryPolicy(StrEnum):
    """AD-443c: Memory portability tiers declared by the Standing Orders
    Federation tier.

    - CLEAN_ROOM (default): No episodic memories travel with the agent. The
      agent arrives at the destination ship with sovereign identity intact but
      zero episodic recollection of the origin ship. Safest default — no
      cross-ship leakage of operational history.
    - SELECTIVE: Only episodes whose `tags` set intersects with a configured
      `selective_tags` list travel. Used for transferring an agent's
      qualification-relevant experience without dragging along ship-specific
      operational context.
    - FULL: All episodes travel verbatim. Reserved for explicit operator
      decision (e.g., decommissioning ship A, lifting all crew with full
      memory to ship B).
    """

    CLEAN_ROOM = "clean_room"
    SELECTIVE = "selective"
    FULL = "full"


def apply_memory_policy(
    policy: MemoryPolicy,
    episodes: Iterable[dict[str, Any]],
    selective_tags: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Apply a MemoryPolicy to a sequence of episode dicts.

    Pure function — does not mutate inputs, does not touch the episodic store.

    Args:
        policy: The policy to enforce.
        episodes: Iterable of episode dicts. Each dict may carry a `tags` key
            holding a list[str] of episode tags.
        selective_tags: Whitelist of tags for SELECTIVE policy. Ignored for
            CLEAN_ROOM and FULL.

    Returns:
        Filtered list of episode dicts. CLEAN_ROOM → []. FULL → list(episodes).
        SELECTIVE → episodes whose `tags` intersects `selective_tags`.
    """
    episode_list = list(episodes)
    if policy == MemoryPolicy.CLEAN_ROOM:
        return []
    if policy == MemoryPolicy.FULL:
        return episode_list
    # SELECTIVE
    allowed = set(selective_tags or [])
    if not allowed:
        return []
    out: list[dict[str, Any]] = []
    for ep in episode_list:
        tags = ep.get("tags") or []
        if isinstance(tags, list) and allowed.intersection(tags):
            out.append(ep)
    return out


@dataclass
class TransferCertificate:
    """AD-443a: W3C Verifiable Credential — Agent Transfer Certificate.

    Issued by the origin ship when an agent transfers to a destination ship.
    Documents the agent's sovereign DID, rank/callsign at transfer time, the
    origin ship's DID and vessel_name (birth provenance per AD-499), and an
    immutable assignment history. Verifiable against the origin ship's
    Identity Ledger (via `import_chain` + `verify_remote_chain` on the
    destination side).

    Per AD-499, `origin_vessel_name` is the agent's BIRTH PROVENANCE — it does
    NOT change on transfer. The destination ship displays the agent as
    `callsign [origin_vessel_name]` regardless of how many transfers occur.
    """

    did: str                              # Sovereign DID (immutable across transfers)
    agent_uuid: str                       # Birth UUID (immutable across transfers)
    agent_type: str                       # Agent type at transfer time
    callsign: str                         # Callsign at transfer time
    origin_ship_did: str                  # DID of the issuing (origin) ship
    origin_vessel_name: str               # Birth provenance (per AD-499 — never changes)
    origin_instance_id: str               # Origin instance_id
    origin_birth_timestamp: float         # Birth time on the origin ship
    transfer_timestamp: float             # When this Transfer Certificate was issued
    target_instance_did: str              # DID of the intended destination ship
    baseline_version: str                 # Agent code baseline at transfer time
    qualification_credentials: list[str] = field(default_factory=list)
    assignment_history: list[dict[str, Any]] = field(default_factory=list)
    certificate_hash: str = ""

    def compute_hash(self) -> str:
        """Compute a deterministic SHA-256 hash over the cert's stable fields.

        Excludes certificate_hash itself. Hash is content-addressed: identical
        content produces identical hash; any field change produces a different
        hash.
        """
        payload = {
            "did": self.did,
            "agent_uuid": self.agent_uuid,
            "agent_type": self.agent_type,
            "callsign": self.callsign,
            "origin_ship_did": self.origin_ship_did,
            "origin_vessel_name": self.origin_vessel_name,
            "origin_instance_id": self.origin_instance_id,
            "origin_birth_timestamp": self.origin_birth_timestamp,
            "transfer_timestamp": self.transfer_timestamp,
            "target_instance_did": self.target_instance_did,
            "baseline_version": self.baseline_version,
            "qualification_credentials": sorted(self.qualification_credentials),
            "assignment_history": self.assignment_history,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def to_verifiable_credential(self) -> dict[str, Any]:
        """Render as a W3C Verifiable Credential dict.

        Mirrors AgentBirthCertificate.to_verifiable_credential — UTC ISO-8601
        timestamps for the `issuanceDate`, embedded subject claims, and the
        certificate hash as the proof anchor.
        """
        return {
            "@context": ["https://www.w3.org/2018/credentials/v1"],
            "type": ["VerifiableCredential", "AgentTransferCertificate"],
            "issuer": self.origin_ship_did,
            "issuanceDate": datetime.fromtimestamp(
                self.transfer_timestamp, tz=timezone.utc
            ).isoformat(),
            "credentialSubject": {
                "id": self.did,
                "agentUuid": self.agent_uuid,
                "agentType": self.agent_type,
                "callsign": self.callsign,
                "birthProvenance": {
                    "shipDid": self.origin_ship_did,
                    "vesselName": self.origin_vessel_name,
                    "instanceId": self.origin_instance_id,
                    "birthTimestamp": datetime.fromtimestamp(
                        self.origin_birth_timestamp, tz=timezone.utc
                    ).isoformat(),
                },
                "targetInstanceDid": self.target_instance_did,
                "baselineVersion": self.baseline_version,
                "qualificationCredentials": list(self.qualification_credentials),
                "assignmentHistory": list(self.assignment_history),
            },
            "proof": {
                "type": "ProbosCertificateHash2024",
                "certificateHash": self.certificate_hash,
            },
        }

    def to_dict(self) -> dict[str, Any]:
        """Serializable dict form (round-trips with from_dict)."""
        return {
            "did": self.did,
            "agent_uuid": self.agent_uuid,
            "agent_type": self.agent_type,
            "callsign": self.callsign,
            "origin_ship_did": self.origin_ship_did,
            "origin_vessel_name": self.origin_vessel_name,
            "origin_instance_id": self.origin_instance_id,
            "origin_birth_timestamp": self.origin_birth_timestamp,
            "transfer_timestamp": self.transfer_timestamp,
            "target_instance_did": self.target_instance_did,
            "baseline_version": self.baseline_version,
            "qualification_credentials": list(self.qualification_credentials),
            "assignment_history": list(self.assignment_history),
            "certificate_hash": self.certificate_hash,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TransferCertificate:
        return cls(
            did=data["did"],
            agent_uuid=data["agent_uuid"],
            agent_type=data["agent_type"],
            callsign=data["callsign"],
            origin_ship_did=data["origin_ship_did"],
            origin_vessel_name=data["origin_vessel_name"],
            origin_instance_id=data["origin_instance_id"],
            origin_birth_timestamp=data["origin_birth_timestamp"],
            transfer_timestamp=data["transfer_timestamp"],
            target_instance_did=data["target_instance_did"],
            baseline_version=data["baseline_version"],
            qualification_credentials=list(data.get("qualification_credentials", [])),
            assignment_history=list(data.get("assignment_history", [])),
            certificate_hash=data.get("certificate_hash", ""),
        )
