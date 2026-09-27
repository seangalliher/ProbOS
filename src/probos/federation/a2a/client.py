"""AD-480e: A2AClient -- outbound A2A client over JSON-RPC + HTTP."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import httpx

from probos.federation.a2a.agent_card import (
    AgentCard,
    AgentCapabilities,
    AgentProvider,
    AgentSkill,
)

logger = logging.getLogger(__name__)


JSONRPC_VERSION = "2.0"


class A2AProtocolError(Exception):
    """Raised on JSON-RPC error or malformed payload."""


def _security_schemes(raw: Any) -> dict[str, dict[str, str]] | None:
    """BF-876: a card's A2A 0.2.0 ``securitySchemes`` if every scheme is an object of strings, else None.

    JSON object keys are always strings, so only values are checked.
    """
    if isinstance(raw, dict) and all(
        isinstance(scheme, dict) and all(isinstance(value, str) for value in scheme.values())
        for scheme in raw.values()
    ):
        return raw
    return None


def _security(raw: Any) -> list[dict[str, list[str]]] | None:
    """BF-876: a card's A2A 0.2.0 ``security`` if it is a list of objects of string lists, else None."""
    if isinstance(raw, list) and all(
        isinstance(requirement, dict) and all(
            isinstance(scopes, list) and all(isinstance(scope, str) for scope in scopes)
            for scopes in requirement.values()
        )
        for requirement in raw
    ):
        return raw
    return None


class A2AClient:
    def __init__(
        self,
        *,
        peer_url: str,
        auth_token: str = "",
        egress_policy: Any | None = None,
        emit_event: Any | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._peer_url = peer_url.rstrip("/")
        self._auth_token = auth_token
        self._egress_policy = egress_policy
        self._emit_event = emit_event
        self._timeout = timeout
        self._http: httpx.AsyncClient | None = httpx.AsyncClient(timeout=timeout)
        self._discovered_card: AgentCard | None = None

    @property
    def discovered_card(self) -> AgentCard | None:
        return self._discovered_card

    async def discover(self) -> AgentCard:
        url = f"{self._peer_url}/.well-known/agent.json"
        if self._egress_policy is not None and not self._egress_policy.is_allowed(url):
            raise A2AProtocolError(f"egress denied for {url}")
        http = self._http
        if http is None:
            raise A2AProtocolError("client closed")
        try:
            response = await http.get(url)
        except httpx.HTTPError as exc:
            raise A2AProtocolError(f"transport error: {exc}") from exc
        if response.status_code >= 400:
            raise A2AProtocolError(f"HTTP {response.status_code} from {url}")
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise A2AProtocolError(f"bad JSON from {url}") from exc
        card = self._parse_agent_card(payload)
        self._discovered_card = card
        return card

    async def send_task(
        self,
        skill_id: str,
        args: dict[str, Any],
        *,
        session_id: str = "",
    ) -> dict[str, Any]:
        text_payload = f"{skill_id}:{json.dumps(args, sort_keys=True)}"
        return await self._call(
            method="tasks/send",
            params={
                "id": uuid.uuid4().hex,
                "sessionId": session_id,
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": text_payload}],
                },
            },
        )

    async def get_task(self, task_id: str) -> dict[str, Any]:
        return await self._call(method="tasks/get", params={"id": task_id})

    async def close(self) -> None:
        http = getattr(self, "_http", None)
        if http is not None:
            await http.aclose()
        self._http = None

    async def _call(
        self, *, method: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        url = f"{self._peer_url}/a2a"
        if self._egress_policy is not None and not self._egress_policy.is_allowed(url):
            raise A2AProtocolError(f"egress denied for {url}")
        http = self._http
        if http is None:
            raise A2AProtocolError("client closed")
        request_id = uuid.uuid4().hex
        payload = {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "method": method,
            "params": params,
        }
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"
        try:
            response = await http.post(
                url, content=json.dumps(payload), headers=headers
            )
        except httpx.HTTPError as exc:
            raise A2AProtocolError(f"transport error: {exc}") from exc
        if response.status_code >= 400:
            raise A2AProtocolError(f"HTTP {response.status_code} from {url}")
        try:
            envelope = response.json()
        except json.JSONDecodeError as exc:
            raise A2AProtocolError(f"bad JSON from {url}") from exc
        if not isinstance(envelope, dict):
            raise A2AProtocolError(f"bad envelope from {url}")
        if "error" in envelope:
            err = envelope.get("error") or {}
            msg = err.get("message", "unknown") if isinstance(err, dict) else "unknown"
            code = err.get("code", 0) if isinstance(err, dict) else 0
            raise A2AProtocolError(f"rpc error {code}: {msg}")
        result = envelope.get("result")
        if not isinstance(result, dict):
            raise A2AProtocolError(f"bad result from {url}")
        return result

    @staticmethod
    def _parse_agent_card(payload: dict) -> AgentCard:
        caps_raw = payload.get("capabilities") or {}
        prov_raw = payload.get("provider")
        skills_raw = payload.get("skills") or []
        skills: list[AgentSkill] = []
        for s in skills_raw:
            if not isinstance(s, dict):
                continue
            skills.append(
                AgentSkill(
                    id=str(s.get("id", "")),
                    name=str(s.get("name", "")),
                    description=str(s.get("description", "")),
                    tags=list(s.get("tags") or []),
                    examples=list(s.get("examples") or []),
                    inputModes=list(s.get("inputModes") or ["text"]),
                    outputModes=list(s.get("outputModes") or ["text"]),
                )
            )
        return AgentCard(
            name=str(payload.get("name", "")),
            description=str(payload.get("description", "")),
            url=str(payload.get("url", "")),
            version=str(payload.get("version", "")),
            capabilities=AgentCapabilities(
                streaming=bool(caps_raw.get("streaming", False)),
                pushNotifications=bool(caps_raw.get("pushNotifications", False)),
                stateTransitionHistory=bool(
                    caps_raw.get("stateTransitionHistory", False)
                ),
            ),
            skills=skills,
            defaultInputModes=list(payload.get("defaultInputModes") or ["text"]),
            defaultOutputModes=list(payload.get("defaultOutputModes") or ["text"]),
            provider=(
                AgentProvider(
                    organization=str(prov_raw.get("organization", "")),
                    url=str(prov_raw.get("url", "")),
                )
                if isinstance(prov_raw, dict)
                else None
            ),
            securitySchemes=_security_schemes(payload.get("securitySchemes")),
            security=_security(payload.get("security")),
        )
