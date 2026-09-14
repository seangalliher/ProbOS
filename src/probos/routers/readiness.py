"""Pure, request-local availability metadata for read routes.

Only typed configuration can establish disabled state. Missing dependencies
establish unavailability, not the outcome of an I/O probe.
"""

from __future__ import annotations

from typing import Literal, TypedDict

from probos.config import SystemConfig


Feature = Literal[
    "records", "knowledge_browser", "skill_requests", "spatial_explorer",
    "ontology_graph", "nats",
]


class Availability(TypedDict):
    state: Literal["disabled", "unavailable", "failed", "initialized", "ready"]
    code: str
    message: str
    retryable: bool


class IntegrationAvailability(Availability):
    id: str
    scope: Literal["initialization", "connection"]


def unavailable_dependency(
    config: object | None,
    feature: Feature,
) -> Availability:
    """Describe absence; ontology has no configuration-off authority."""
    if isinstance(config, SystemConfig):
        enabled = None if feature == "ontology_graph" else getattr(config, feature).enabled
        if enabled is False:
            return {
                "state": "disabled",
                "code": f"{feature}.disabled",
                "message": "Disabled. Review configuration with the operator.",
                "retryable": False,
            }
        code = f"{feature}.unavailable"
    else:
        code = f"{feature}.configuration_unknown"
    return {
        "state": "unavailable",
        "code": code,
        "message": "Unavailable. Retry the request.",
        "retryable": True,
    }


def failed_read(message: str, code: str, status_code: int = 500) -> Availability:
    """Build metadata from controlled route literals, never exception text."""
    return {
        "state": "unavailable" if status_code == 503 else "failed",
        "code": code,
        "message": message,
        "retryable": status_code >= 500,
    }


def integration_availability(
    config: object | None,
    feature: Feature,
    *,
    initialized: bool,
    connected: bool | None = None,
) -> IntegrationAvailability:
    """Project supplied observations, with no I/O or lifecycle actions.

    Presence proves initialization only. NATS ready requires typed enabled
    configuration and exact current connection evidence, not JetStream health.
    Unknown connection observations remain unavailable. This finite projection
    is carried in system/services.integrations, not read-error availability.
    """
    availability = unavailable_dependency(config, feature)
    scope: Literal["initialization", "connection"] = "connection" if feature == "nats" else "initialization"
    if availability["state"] != "disabled" and initialized is True:
        if feature != "nats":
            availability = {
                "state": "initialized", "code": f"{feature}.initialized",
                "message": "Initialized. Read operations have not been checked.",
                "retryable": False,
            }
        elif isinstance(config, SystemConfig) and config.nats.enabled is True:
            if connected is True:
                availability = {
                    "state": "ready", "code": "nats.connected",
                    "message": "Connected. JetStream operations have not been checked.",
                    "retryable": False,
                }
            else:
                availability = {
                    "state": "unavailable",
                    "code": "nats.disconnected" if connected is False else "nats.connection_unknown",
                    "message": "Connection unavailable. Retry the request.",
                    "retryable": True,
                }
    return {
        **availability,
        "id": "spatial_layout" if feature == "spatial_explorer" else feature,
        "scope": scope,
    }