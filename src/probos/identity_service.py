"""AD-1346 M1a: one identity reference, resolved in one place.

Trust and the other slot-keyed stores key an agent by its deployment slot id
(BF-907). Every other form an agent's identity takes resolves to that slot here,
by delegation to the registry that owns the form:

* a slot id: ``AgentIdentityRegistry.get_by_slot`` and ``get_asset_by_slot``;
* a birth-certificate UUID, a did:probos agent DID or an asset-tag UUID:
  ``AgentIdentityRegistry.resolve_slot_id`` (BF-907's resolver, which owns
  ``parse_did``);
* a callsign: ``CallsignRegistry.resolve`` and ``get_callsign``.

The facade copies no resolution logic and holds references, so a certificate,
tag or callsign change is seen at the next call. It never creates or changes an
identity, persists nothing and is synchronous: AD-1346 M3's admission decision
calls it on the dispatch loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.crew_profile import CallsignRegistry
    from probos.identity import AgentIdentityRegistry

#: AD-1346 M1a (frozen for M3): the keys of ``IdentityRef.to_dict()``, in order. A later
#: key (AD-1342's embodiment) is appended; none of these is ever renamed, removed or
#: retyped, so a record that embeds a ref never migrates.
IDENTITY_REF_KEYS: tuple[str, ...] = ("slot_id", "sovereign_id", "did", "callsign", "agent_type")


@dataclass(frozen=True, slots=True)
class IdentityRef:
    """One agent's identity as ``IdentityService`` resolved it (the only constructor in ``src``).

    ``slot_id`` is the authoritative key: trust and the other slot-keyed stores key by it
    (BF-907). ``sovereign_id`` is the birth-certificate UUID, or the asset-tag UUID for an
    asset, as ``agent.sovereign_id`` is set at onboarding. ``did`` is the agent DID ("" for an
    asset). ``callsign`` is the live callsign when resolved ("" if none). ``agent_type`` is the
    certificate's agent type or the asset type.

    Two refs are equal when ``slot_id`` and ``sovereign_id`` are, so a slot reused by another
    identity is a different ref; ``did``, ``callsign`` and ``agent_type`` take no part.
    """

    slot_id: str
    sovereign_id: str
    did: str = field(compare=False)
    callsign: str = field(compare=False)
    agent_type: str = field(compare=False)

    def __post_init__(self) -> None:
        for name in IDENTITY_REF_KEYS:
            if type(getattr(self, name)) is not str:
                raise TypeError(f"IdentityRef.{name} must be a str")
        if not self.slot_id or not self.sovereign_id:
            raise ValueError("IdentityRef needs a slot id and a sovereign id")

    def to_dict(self) -> dict[str, str]:
        """The stable JSON form (``IDENTITY_REF_KEYS``, in order) for records that embed a ref."""
        return {name: getattr(self, name) for name in IDENTITY_REF_KEYS}


class IdentityService:
    """AD-1346 M1a: the one place an identity in any form resolves to an ``IdentityRef``.

    Consumers: AD-1346 M3's admission service (the principal of a shadow decision) and the
    M1 slices that retire the local resolvers one family at a time.
    """

    def __init__(self, identity_registry: AgentIdentityRegistry, callsign_registry: CallsignRegistry) -> None:
        if identity_registry is None or callsign_registry is None:
            raise TypeError("IdentityService needs the identity registry and the callsign registry")
        self._identities = identity_registry
        self._callsigns = callsign_registry

    def resolve(self, key: str) -> IdentityRef | None:
        """The ref for a slot id, a birth-certificate UUID, an agent DID or an asset-tag UUID.

        A slot id is looked up first; any other key goes through BF-907's ``resolve_slot_id``.
        None for an empty or non-string key, an unknown key, a callsign (use
        ``resolve_callsign``) and an identity bound to more than one slot. Never raises for a
        key; never creates or changes an identity.
        """
        if type(key) is not str or not key:
            return None
        ref = self._ref_for_slot(key)
        if ref is not None:
            return ref
        slot_id = self._identities.resolve_slot_id(key)
        if slot_id is None:
            return None
        return self._ref_for_slot(slot_id)

    def resolve_callsign(self, callsign: str) -> IdentityRef | None:
        """The ref of the live agent a callsign names, through ``CallsignRegistry.resolve``.

        None for an empty or non-string callsign, an unknown callsign, a callsign with no live
        agent and a live agent with no certificate or asset tag. Where several live agents
        share the callsign's type, ``CallsignRegistry.resolve`` picks one, as it does for its
        other callers.
        """
        if type(callsign) is not str or not callsign:
            return None
        entry = self._callsigns.resolve(callsign)
        if entry is None:
            return None
        agent_id = entry.get("agent_id")
        if type(agent_id) is not str or not agent_id:
            return None
        return self._ref_for_slot(agent_id)

    def _ref_for_slot(self, slot_id: str) -> IdentityRef | None:
        """The ref of a slot: its birth certificate first, else its asset tag, else None."""
        cert = self._identities.get_by_slot(slot_id)
        if cert is not None:
            return IdentityRef(
                slot_id=slot_id,
                sovereign_id=cert.agent_uuid,
                did=cert.did,
                callsign=self._callsigns.get_callsign(cert.agent_type),
                agent_type=cert.agent_type,
            )
        tag = self._identities.get_asset_by_slot(slot_id)
        if tag is not None:
            return IdentityRef(
                slot_id=slot_id,
                sovereign_id=tag.asset_uuid,
                did="",
                callsign=self._callsigns.get_callsign(tag.asset_type),
                agent_type=tag.asset_type,
            )
        return None
