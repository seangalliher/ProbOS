"""AD-753 permission-card model and local manager."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4


PermissionCardStatus = Literal["pending", "approved", "rejected", "escalated"]


@dataclass(slots=True)
class PermissionCard:
    """Approval artifact for unattended permission decisions."""

    id: str
    intent: str
    scope: str
    reason: str
    expires_at: datetime
    status: PermissionCardStatus = "pending"
    audit_trail: list[dict[str, str]] = field(default_factory=list)


class PermissionCardManager:
    """In-memory manager for permission cards (OSS local scope)."""

    def __init__(self) -> None:
        self._cards: dict[str, PermissionCard] = {}
        self._lock = asyncio.Lock()

    async def create_card(
        self,
        intent: str,
        scope: str,
        reason: str,
        ttl_sec: int = 3600,
    ) -> PermissionCard:
        """Create a pending permission card with expiry and audit metadata."""
        expires_at = datetime.now(UTC) + timedelta(seconds=max(1, ttl_sec))
        card = PermissionCard(
            id=uuid4().hex,
            intent=intent,
            scope=scope,
            reason=reason,
            expires_at=expires_at,
        )
        card.audit_trail.append(
            {
                "at": datetime.now(UTC).isoformat(),
                "event": "created",
                "actor": "system",
            }
        )
        async with self._lock:
            self._cards[card.id] = card
        return card

    async def approve(self, card_id: str, approver: str = "Captain") -> None:
        """Approve a non-expired card and append audit metadata."""
        async with self._lock:
            card = self._get_required(card_id)
            if self._is_expired(card):
                raise ValueError("permission_card_expired")
            card.status = "approved"
            card.audit_trail.append(
                {
                    "at": datetime.now(UTC).isoformat(),
                    "event": "approved",
                    "actor": approver,
                }
            )

    async def reject(self, card_id: str, reason: str = "") -> None:
        """Reject a non-expired card and append audit metadata."""
        async with self._lock:
            card = self._get_required(card_id)
            if self._is_expired(card):
                raise ValueError("permission_card_expired")
            card.status = "rejected"
            card.audit_trail.append(
                {
                    "at": datetime.now(UTC).isoformat(),
                    "event": "rejected",
                    "actor": "Captain",
                    "reason": reason,
                }
            )

    async def list_pending(self) -> list[PermissionCard]:
        """Return pending, non-expired cards for Ward Room display."""
        now = datetime.now(UTC)
        async with self._lock:
            return [
                card
                for card in self._cards.values()
                if card.status == "pending" and card.expires_at > now
            ]

    def _get_required(self, card_id: str) -> PermissionCard:
        card = self._cards.get(card_id)
        if card is None:
            raise KeyError(card_id)
        return card

    @staticmethod
    def _is_expired(card: PermissionCard) -> bool:
        return card.expires_at <= datetime.now(UTC)


def card_from_intent(intent: str, reason: str, scope: str, ttl_sec: int = 3600) -> PermissionCard:
    """Build a card value from intent metadata without persistence side effects."""
    return PermissionCard(
        id=uuid4().hex,
        intent=intent,
        scope=scope,
        reason=reason,
        expires_at=datetime.now(UTC) + timedelta(seconds=max(1, ttl_sec)),
    )
