"""Shared helpers for Ward Room sub-modules (BF-113: DRY extraction)."""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


def resolve_author_department(author_id: str) -> str:
    """Resolve department for Ward Room episode anchors (AD-567g)."""
    try:
        from probos.cognitive.standing_orders import get_department
        return get_department(author_id) or ""
    except Exception:
        return ""


async def check_and_emit_cascade_risk(
    social_verification: Any,
    emit_fn: Callable | None,
    *,
    author_id: str,
    author_callsign: str,
    post_body: str,
    channel_id: str,
    peer_matches: list[dict],
) -> None:
    """Check cascade confabulation risk and emit event if medium/high (AD-567f)."""
    if not peer_matches or not social_verification:
        return
    try:
        cascade = await social_verification.check_cascade_risk(
            author_id=author_id,
            author_callsign=author_callsign,
            post_body=post_body,
            channel_id=channel_id,
            peer_matches=peer_matches,
        )
        if cascade and cascade.risk_level in ("medium", "high"):
            import dataclasses
            from probos.events import EventType as _ET
            if emit_fn:
                emit_fn(
                    _ET.CASCADE_CONFABULATION_DETECTED,
                    dataclasses.asdict(cascade),
                )
    except Exception:
        logger.debug("AD-567f: cascade check failed", exc_info=True)
