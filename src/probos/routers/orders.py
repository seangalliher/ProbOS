"""AD-440: Chain-of-command order endpoints (read-only)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from probos.routers.deps import get_runtime

router = APIRouter(prefix="/api/orders", tags=["orders"])


def _serialize(order: Any) -> dict[str, Any]:
    return {
        "id": order.id,
        "from_agent_id": order.from_agent_id,
        "from_post_id": order.from_post_id,
        "to_post_id": order.to_post_id,
        "directive": order.directive,
        "issued_at": order.issued_at,
        "expires_at": order.expires_at,
        "state": order.state.value if hasattr(order.state, "value") else str(order.state),
        "acknowledged_by": order.acknowledged_by,
        "acknowledged_at": order.acknowledged_at,
    }


@router.get("")
async def list_orders(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """List all known orders (after TTL prune)."""
    mgr = getattr(runtime, "order_manager", None)
    if mgr is None:
        raise HTTPException(404, "Order manager disabled")
    return {"orders": [_serialize(o) for o in mgr.all_orders()]}


@router.get("/post/{post_id}")
async def list_orders_for_post(
    post_id: str, runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Pending orders targeting a post."""
    mgr = getattr(runtime, "order_manager", None)
    if mgr is None:
        raise HTTPException(404, "Order manager disabled")
    return {
        "post_id": post_id,
        "orders": [_serialize(o) for o in mgr.list_active_for_post(post_id)],
    }
