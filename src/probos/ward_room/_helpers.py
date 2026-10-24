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


async def _deliver_bridge_alerts(
    alerts: list[Any] | None, ward_room_router: Any, tag: str,
) -> None:
    """Deliver Bridge alerts through the Ward Room router (BF-920: one path).

    Log-and-degrade per alert: a failed delivery must not stop the other
    alerts, nor the Ward Room post that triggered the check.
    """
    if not alerts or not ward_room_router:
        return
    for alert in alerts:
        try:
            await ward_room_router.deliver_bridge_alert(alert)
        except Exception:
            logger.debug("%s: Bridge alert delivery failed", tag, exc_info=True)


async def check_and_alert_cascade_risk(
    social_verification: Any,
    *,
    bridge_alerts: Any,
    ward_room_router: Any,
    author_id: str,
    author_callsign: str,
    post_body: str,
    channel_id: str,
    peer_matches: list[dict],
) -> None:
    """Check cascade confabulation risk and raise its Bridge alert (AD-567f).

    BF-920: ``SocialVerificationService.check_cascade_risk`` is the single
    owner of ``CASCADE_CONFABULATION_DETECTED``. This helper used to emit a
    second copy through the Ward Room emitter, which forwards to the same
    runtime bus, so every detection went out twice. It routes the result
    to the Bridge alert AD-567f designed instead
    (``BridgeAlertService.check_cascade_risk``: medium and high only),
    which had no caller.
    """
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
        if cascade and bridge_alerts:
            import dataclasses
            alerts = bridge_alerts.check_cascade_risk(dataclasses.asdict(cascade))
            await _deliver_bridge_alerts(alerts, ward_room_router, "AD-567f")
    except Exception:
        logger.debug("AD-567f: cascade check failed", exc_info=True)


async def check_and_trace_echo(
    thread_echo_analyzer: Any,
    observable_state_verifier: Any,
    emit_fn: Callable | None,
    bridge_alerts: Any,
    ward_room_router: Any,
    *,
    thread_id: str,
    channel_id: str,
    peer_matches: list[dict],
) -> None:
    """AD-583f/583g: Trace echo chain and verify claims on echo detection.

    Called after check_and_alert_cascade_risk() when peer_matches are found.
    Runs thread echo analysis and, if echo detected, runs observable state
    verification on the thread content.
    """
    if not peer_matches or not thread_echo_analyzer:
        return
    try:
        echo_result = await thread_echo_analyzer.analyze(thread_id)
        if not echo_result.echo_detected:
            return

        # AD-583g: Emit echo event
        if emit_fn:
            from probos.events import EventType as _ET
            emit_fn(_ET.WARD_ROOM_ECHO_DETECTED, {
                "thread_id": thread_id,
                "channel_id": channel_id,
                "source_callsign": echo_result.source_callsign,
                "chain_length": echo_result.chain_length,
                "independence_score": echo_result.anchor_independence_score,
                "affected_callsigns": [
                    step.callsign for step in echo_result.propagation_chain
                ],
            })

        # AD-583g: Bridge alert
        if bridge_alerts:
            import dataclasses
            # BF-920: ThreadEchoResult has no affected_callsigns field, so the
            # alert's "Affected:" list was always empty; merge it in.
            echo_alert_input = {
                **dataclasses.asdict(echo_result),
                "affected_callsigns": [step.callsign for step in echo_result.propagation_chain],
            }
            alerts = bridge_alerts.check_ward_room_echo(echo_alert_input)
            await _deliver_bridge_alerts(alerts, ward_room_router, "AD-583g")

        # AD-583f: Observable state verification on echo content
        if observable_state_verifier and echo_result.chain_length >= 3:
            # Get post bodies for claim verification
            posts = await thread_echo_analyzer._thread_manager.get_thread_posts_temporal(
                thread_id,
            )
            # Collect unique claim texts from echoing posts
            echo_ids = {echo_result.source_post_id}
            echo_ids.update(step.post_id for step in echo_result.propagation_chain)
            claims = []
            agents_involved = set()
            for post in posts:
                if post.get("id") in echo_ids:
                    body = post.get("body", "")
                    if body:
                        claims.append(body[:500])
                    cs = post.get("author_callsign", "")
                    if cs:
                        agents_involved.add(cs)

            if claims:
                results = await observable_state_verifier.verify_claims(
                    claims, context={"agents": list(agents_involved)},
                )
                failed = [r for r in results if r.verified is False]
                if failed:
                    summaries = [r.ground_truth_summary for r in failed]
                    if emit_fn:
                        emit_fn(_ET.OBSERVABLE_STATE_MISMATCH, {
                            "thread_id": thread_id,
                            "claims_checked": len(results),
                            "claims_failed": len(failed),
                            "ground_truth_summary": "; ".join(summaries[:3]),
                            "agents_involved": list(agents_involved),
                        })
                    if bridge_alerts:
                        # BF-920: deliver the alert; it used to be built and dropped.
                        mismatch_alerts = bridge_alerts.check_observable_mismatch({
                            "thread_id": thread_id,
                            "claims_failed": len(failed),
                            "ground_truth_summary": "; ".join(summaries[:3]),
                        })
                        await _deliver_bridge_alerts(
                            mismatch_alerts, ward_room_router, "AD-583f",
                        )

    except Exception:
        logger.debug("AD-583f/g: Echo trace failed", exc_info=True)
