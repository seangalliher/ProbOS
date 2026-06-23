"""AD-731a-1c: receive-side auto-resolution of cross-host attachment refs (#638).

When a host receives a federated ``IntentMessage`` referencing an attachment
SHA it lacks locally, this resolver auto-fetches the bytes from the SENDER peer
— but ONLY when (a) ``attachments.auto_resolve_remote_enabled`` is True
(default-OFF -> the resolver never runs, byte-identical), and (b) the sender
``source_node`` maps to a configured ``a2a.outbound_peer`` whose ``node_id``
matches. Reuses :func:`probos.federation.attachment_fetch.fetch_remote_attachment`
as-is (content-verifying, honest-degrade). Fully guarded: NEVER raises, NEVER
blocks the broadcast.

Caveat C-A: today only the bare ``params['attachment_ref']`` SHA crosses the
wire (BF-265 strips ``vision_messages`` on send). The vision-block extraction
here is forward-safe for the deferred send-side complement (AD-731a-1d).
Caveat C-B: auto-resolution fires only for an A2A-configured sender peer with a
matching ``node_id`` — there is no resolver from an arbitrary ``source_node`` to
a fetchable URL otherwise.
"""

from __future__ import annotations

import logging
from typing import Any

from probos.federation.attachment_fetch import fetch_remote_attachment

logger = logging.getLogger(__name__)


def _is_64_hex(value: Any) -> bool:
    """True iff ``value`` is a 64-char lowercase-hex string."""
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
    )


def extract_attachment_shas(params: dict) -> list[str]:
    """Collect the 64-hex attachment SHAs referenced by an inbound message.

    Handles the bare ``params['attachment_ref']`` shape (a single SHA string —
    the only shape that crosses the wire today) AND, defensively, the AD-731
    block shape ``params['vision_messages'][].content[].source.sha256``
    (forward-safe for the AD-731a-1d send-side complement). Dedups preserving
    first-seen order; drops any value that is not a 64-char lowercase-hex
    string. Pure (no I/O) and never raises — ``params`` may have any shape.
    """
    shas: list[str] = []
    seen: set[str] = set()

    def _add(value: Any) -> None:
        if _is_64_hex(value) and value not in seen:
            seen.add(value)
            shas.append(value)

    if not isinstance(params, dict):
        return shas

    # Bare ref shape (perception/__init__.py) — the only shape that crosses today.
    _add(params.get("attachment_ref"))

    # AD-731 vision-block shape (stripped on send today per BF-265; forward-safe).
    vision_messages = params.get("vision_messages")
    if isinstance(vision_messages, list):
        for msg in vision_messages:
            if not isinstance(msg, dict):
                continue
            content = msg.get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict) or block.get("type") != "image":
                    continue
                source = block.get("source")
                if isinstance(source, dict):
                    _add(source.get("sha256"))

    return shas


def resolve_sender_peer(a2a_cfg: Any, source_node: str) -> Any | None:
    """Return the outbound A2A peer whose ``node_id == source_node``.

    Matches only a non-empty ``node_id`` (an unmapped peer is never an
    auto-resolution source). Returns ``None`` when ``source_node`` is empty, no
    peer matches, or no peer has ``node_id`` set. Pure (no I/O); never raises.
    """
    if not source_node:
        return None
    peers = getattr(a2a_cfg, "outbound_peers", []) or []
    for peer in peers:
        node_id = getattr(peer, "node_id", "")
        if node_id and node_id == source_node:
            return peer
    return None


async def resolve_missing_attachments(
    runtime: Any,
    params: dict,
    source_node: str,
    *,
    http: Any = None,
) -> int:
    """Fetch any referenced attachment bytes this host lacks from the sender peer.

    Returns the number of attachments stored. Guarded orchestrator: NEVER
    raises and NEVER blocks the broadcast. Short-circuits (returns 0) when:
    ``runtime`` is None; the ``auto_resolve_remote_enabled`` flag is off; the
    runtime has no attachment store; ``params`` reference no attachment SHAs; or
    the sender ``source_node`` maps to no configured A2A outbound peer. Each
    fetch is content-verifying (tampered/corrupt bytes are never stored) and
    idempotent (already-local SHAs are skipped without a network call).
    """
    count = 0
    try:
        if runtime is None:
            return 0
        cfg = runtime.config
        att = cfg.attachments
        if not getattr(att, "auto_resolve_remote_enabled", False):
            return 0
        store = getattr(runtime, "attachment_store", None)
        if store is None:
            return 0
        shas = extract_attachment_shas(params)
        if not shas:
            return 0
        peer = resolve_sender_peer(cfg.federation.a2a, source_node)
        if peer is None:
            return 0

        for sha in shas:
            # Idempotent: never re-fetch bytes we already hold locally.
            if await store.exists(sha):
                continue
            try:
                ok = await fetch_remote_attachment(
                    peer.peer_url,
                    sha,
                    auth_token=peer.auth_token,
                    store=store,
                    http=http,
                )
                if ok:
                    count += 1
            except Exception:
                # Tier-2 log-and-degrade: a single failed fetch must not abort
                # the rest; local agents will see a failed_to_load marker.
                logger.warning(
                    "AD-731a-1c: fetch of attachment %s from peer %s failed; "
                    "skipping",
                    sha[:8], getattr(peer, "peer_url", "?"), exc_info=True,
                )
        return count
    except Exception:
        # Outer guard: any unexpected failure (config access, store error)
        # returns the count-so-far so the caller's broadcast proceeds intact.
        logger.warning(
            "AD-731a-1c: attachment resolution failed; returning count-so-far "
            "(broadcast proceeds unaffected)",
            exc_info=True,
        )
        return count
