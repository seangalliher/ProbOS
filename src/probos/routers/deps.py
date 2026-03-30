"""Shared FastAPI dependencies for ProbOS API routers (AD-516)."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import Request


def get_runtime(request: Request) -> Any:
    """Inject ProbOSRuntime from app state."""
    return request.app.state.runtime


def get_ws_broadcast(request: Request) -> Callable:
    """Inject WebSocket broadcast function from app state."""
    return request.app.state.broadcast_event


def get_task_tracker(request: Request) -> Callable:
    """Inject background task tracker from app state."""
    return request.app.state.track_task


def get_pending_designs(request: Request) -> dict:
    """Inject pending designs dict from app state."""
    return request.app.state.pending_designs
