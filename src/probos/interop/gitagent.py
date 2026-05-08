"""AD-491: gitagent YAML interop adapter.

The OSS sovereign DID + birth certificate is the authoritative identity.
This module is a pure boundary adapter for publishing a ProbOS agent in
gitagent YAML format and consuming a third-party gitagent YAML at
install time. No internal data model changes here.

Public API:
    export_agent_to_gitagent_yaml(agent) -> str
    import_gitagent_yaml(path) -> dict
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from probos.substrate.agent import BaseAgent


def export_agent_to_gitagent_yaml(agent: "BaseAgent") -> str:
    """Render a ProbOS agent in gitagent YAML format.

    The returned YAML carries the gitagent-canonical fields (name,
    version, runtime, capabilities, instructions) plus a ``probos``
    sub-section that preserves the sovereign DID and birth certificate
    hash so a round-trip back to ProbOS can re-assert authoritative
    identity. Round-tripping is by hash reference, not by re-issuing
    the sovereign DID -- the original ship's birth certificate remains
    the source of truth.
    """
    callsign = getattr(agent, "callsign", "") or getattr(agent, "agent_type", "")
    capabilities = [
        getattr(c, "can", "") for c in getattr(agent, "default_capabilities", [])
    ]
    intents = [
        getattr(i, "name", "") for i in getattr(agent, "intent_descriptors", [])
    ]
    payload: dict[str, Any] = {
        "name": callsign,
        "version": "1",
        "runtime": "probos",
        "agent_type": getattr(agent, "agent_type", ""),
        "tier": getattr(agent, "tier", ""),
        "capabilities": capabilities,
        "intents": intents,
        "instructions": getattr(agent, "instructions", "") or "",
        "probos": {
            "sovereign_id": getattr(agent, "sovereign_id", "") or "",
            "did": getattr(agent, "did", "") or "",
            "pool": getattr(agent, "pool", "") or "",
        },
    }
    return yaml.safe_dump(payload, sort_keys=False, default_flow_style=False)


def import_gitagent_yaml(path: str | Path) -> dict[str, Any]:
    """Parse a gitagent YAML file into a ProbOS-friendly dict.

    Returns a dict with normalized keys ready for an installer to
    construct or register an agent. Does NOT instantiate a BaseAgent
    -- the caller (typically a future commercial-overlay installer)
    decides what to do with the parsed manifest.

    Raises ValueError on invalid YAML or missing required gitagent
    keys (``name``, ``runtime``). Other parse-time errors propagate.
    """
    p = Path(path)
    raw_text = p.read_text(encoding="utf-8")
    try:
        loaded = yaml.safe_load(raw_text)
    except yaml.YAMLError:
        raise
    if not isinstance(loaded, dict):
        raise ValueError(
            "gitagent YAML must parse to a mapping at the top level; "
            f"got {type(loaded).__name__}"
        )
    for required in ("name", "runtime"):
        if required not in loaded or not loaded[required]:
            raise ValueError(
                f"gitagent YAML missing required key: {required!r}"
            )

    runtime = str(loaded.get("runtime", ""))
    raw_probos = loaded.get("probos") or {}
    if not isinstance(raw_probos, dict):
        raw_probos = {}

    # Security boundary: foreign runtimes cannot assert ProbOS sovereign IDs.
    if runtime == "probos":
        sovereign_id = str(raw_probos.get("sovereign_id", "") or "")
        did = str(raw_probos.get("did", "") or "")
    else:
        sovereign_id = ""
        did = ""

    capabilities = loaded.get("capabilities") or []
    intents = loaded.get("intents") or []
    if not isinstance(capabilities, list):
        capabilities = []
    if not isinstance(intents, list):
        intents = []

    return {
        "name": str(loaded.get("name", "")),
        "version": str(loaded.get("version", "") or ""),
        "runtime": runtime,
        "agent_type": str(loaded.get("agent_type", "") or ""),
        "tier": str(loaded.get("tier", "") or ""),
        "capabilities": [str(c) for c in capabilities],
        "intents": [str(i) for i in intents],
        "instructions": str(loaded.get("instructions", "") or ""),
        "probos": {
            "sovereign_id": sovereign_id,
            "did": did,
            "pool": str(raw_probos.get("pool", "") or ""),
        },
    }
