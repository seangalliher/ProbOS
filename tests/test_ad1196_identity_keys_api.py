"""AD-1196 (#1133) M6: the ship key's Captain-only REST surface under ``/api/identity/keys``.

Each test drives the real identity router in the test's own loop
(``httpx.ASGITransport`` on a minimal app; never ``TestClient``, whose second
loop would touch the registry's aiosqlite connection and ledger lock), against
a real armed registry on ``tmp_path`` whose key store records every call.

Amendment A-0 (the AD-731a-1 rule): the three mutating routes answer 403
``identity_keys_require_token`` while no crew-scope token is configured, before
any key action or audit entry. Every other test that calls a mutating route
configures a token and sends the bearer. No test reaches the real OS keyring.
"""

from __future__ import annotations

import contextlib
import json
import logging
import typing
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import keyring
import pytest
from fastapi import FastAPI

from probos.config import AuthConfig, SystemConfig
from probos.identity_key_store import KeyringKeyStore
from probos.identity_keys import (
    REINCEPTION_CONFIRM,
    KeyStoreUnavailable,
    generate_recovery_keypair,
    sign_recovery_authorization,
)
from probos.routers import identity as identity_routes
from probos.routers.deps import get_runtime
from probos.security.audit import AuditLog
from tests.test_ad1196_did_key_binding import SHIP_A, _armed, _birth, _count_rows, _DuckKeyring

TOKEN = "ad1196-crew-scope-token"
AUDIT_CATEGORY = "identity_keys"
AUDIT_KEYS = {"v", "action", "did", "kid", "block_index", "reason", "note"}
KEYS = "/api/identity/keys"


@pytest.fixture(autouse=True)
def _no_real_os_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any path that would resolve the process keyring fails loudly instead (H4)."""

    def _forbidden(*_args: object, **_kwargs: object) -> Any:
        raise RuntimeError("AD-1196 tests must never reach the real OS keyring")

    monkeypatch.setattr(keyring, "get_keyring", _forbidden)
    monkeypatch.setattr(keyring, "set_keyring", _forbidden)


class _RecordingStore:
    """Delegates to a real keyring store and records every call, so a refused request can prove it made none."""

    def __init__(self, inner: KeyringKeyStore) -> None:
        self.inner = inner
        self.calls: list[str] = []
        self.fail_create = False

    async def describe(self) -> Any:
        self.calls.append("describe")
        return await self.inner.describe()

    async def create(self, did: str) -> tuple[str, str]:
        self.calls.append("create")
        if self.fail_create:
            raise KeyStoreUnavailable("AD-1196 test: the keyring backend stopped answering")
        return await self.inner.create(did)

    async def public_key(self, kid: str) -> str | None:
        self.calls.append("public_key")
        return await self.inner.public_key(kid)

    async def sign(self, kid: str, message: str) -> str:
        self.calls.append("sign")
        return await self.inner.sign(kid, message)


@dataclass
class _Runtime:
    """The runtime surface the identity router reads."""

    config: SystemConfig
    identity_key_binding: Any
    audit_log: AuditLog = field(default_factory=AuditLog)


@dataclass
class _Rig:
    runtime: _Runtime
    binding: Any
    registry: Any
    duck: _DuckKeyring
    store: _RecordingStore
    recovery_private: str
    client: httpx.AsyncClient
    db_path: Path

    def configure_token(self) -> None:
        self.runtime.config = SystemConfig(auth=AuthConfig(crew_scope_token=TOKEN))

    def audit(self) -> list[dict[str, Any]]:
        entries = self.runtime.audit_log.entries
        return [json.loads(entry.detail) for entry in entries if entry.category == AUDIT_CATEGORY]


def _bearer(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@contextlib.asynccontextmanager
async def _rig(
    tmp_path: Path,
    *,
    recovery: bool = True,
    token: str = TOKEN,
    armed: bool = True,
    duck: _DuckKeyring | None = None,
) -> AsyncIterator[_Rig]:
    """A real armed registry on ``tmp_path / "ship"`` behind the identity router."""
    duck = duck if duck is not None else _DuckKeyring()
    recovery_private, recovery_public = generate_recovery_keypair() if recovery else ("", "")
    store = _RecordingStore(KeyringKeyStore(backend=duck))
    data_dir = tmp_path / "ship"
    async with _armed(data_dir, duck, recovery_public_key=recovery_public, store=store) as (registry, binding):
        runtime = _Runtime(
            config=SystemConfig(auth=AuthConfig(crew_scope_token=token)),
            identity_key_binding=binding if armed else None,
        )
        app = FastAPI()
        app.include_router(identity_routes.router)
        app.dependency_overrides[get_runtime] = lambda: runtime
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            yield _Rig(runtime, binding, registry, duck, store, recovery_private, client, data_dir / "identity.db")


# --------------------------------------------------------------------------- #
# GET /api/identity/keys
# --------------------------------------------------------------------------- #


async def test_status_happy(tmp_path: Path) -> None:
    async with _rig(tmp_path) as rig:
        response = await rig.client.get(KEYS, headers=_bearer())
        secrets = list(rig.duck.entries.values())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["enabled"] is True and body["status"] == "active" and body["did"] == SHIP_A
    assert body["recovery_committed"] is True and len(body["keys"]) == 1
    assert body["did_document"]["assertionMethod"] == [body["active_kid"]]
    assert secrets and all(secret not in response.text for secret in secrets)


async def test_status_503_when_unarmed(tmp_path: Path) -> None:
    async with _rig(tmp_path, armed=False) as rig:
        responses = [await rig.client.get(KEYS, headers=_bearer())]
        for path, body in (
            ("/rotate", {}),
            ("/recovery", {"reason": "lost"}),
            ("/reinception", {"reason": "lost", "confirm": REINCEPTION_CONFIRM}),
        ):
            responses.append(await rig.client.post(KEYS + path, json=body, headers=_bearer()))
        creates = rig.store.calls.count("create")
    assert [response.status_code for response in responses] == [503] * 4
    assert {response.json()["detail"] for response in responses} == {"identity key binding is not enabled"}
    assert creates == 1  # the inception only
    assert rig.audit() == []


async def test_key_routes_require_crew_scope_when_token_configured(tmp_path: Path) -> None:
    async with _rig(tmp_path) as rig:
        missing = await rig.client.get(KEYS)
        wrong = await rig.client.get(KEYS, headers=_bearer("not-the-token"))
        rotate_missing = await rig.client.post(f"{KEYS}/rotate", json={})
        unchanged = await rig.binding.status()
        allowed = await rig.client.get(KEYS, headers=_bearer())
    assert (missing.status_code, wrong.status_code, rotate_missing.status_code) == (401, 401, 401)
    assert unchanged["seq"] == 0 and rig.audit() == []
    assert allowed.status_code == 200 and allowed.json()["status"] == "active"


async def test_status_route_readable_without_configured_token(tmp_path: Path) -> None:
    async with _rig(tmp_path, token="") as rig:
        response = await rig.client.get(KEYS)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "active"


# --------------------------------------------------------------------------- #
# POST /api/identity/keys/rotate
# --------------------------------------------------------------------------- #


async def test_rotate_happy(tmp_path: Path) -> None:
    async with _rig(tmp_path) as rig:
        before = await rig.binding.status()
        response = await rig.client.post(f"{KEYS}/rotate", json={"note": "routine"}, headers=_bearer())
        after = await rig.binding.status()
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kid"] == after["active_kid"] != before["active_kid"]
    assert after["seq"] == before["seq"] + 1
    assert rig.audit() == [{
        "v": 1, "action": "rotate", "did": SHIP_A, "kid": body["kid"], "block_index": body["block_index"],
        "reason": "", "note": "routine",
    }]


async def test_rotate_409_when_key_missing(tmp_path: Path) -> None:
    duck = _DuckKeyring()
    async with _rig(tmp_path, duck=duck, recovery=False) as rig:
        kid = (await rig.binding.status())["active_kid"]
    duck.forget(kid)
    async with _rig(tmp_path, duck=duck, recovery=False) as rig:
        assert (await rig.binding.status())["status"] == "key_missing"  # premise
        response = await rig.client.post(f"{KEYS}/rotate", json={}, headers=_bearer())
        after = await rig.binding.status()
        creates = rig.store.calls.count("create")
    assert response.status_code == 409 and "key_missing" in response.json()["detail"]
    assert after["seq"] == 0 and after["active_kid"] == kid
    assert creates == 0 and rig.audit() == []


async def test_rotate_rejects_unknown_fields(tmp_path: Path) -> None:
    async with _rig(tmp_path) as rig:
        unknown = await rig.client.post(f"{KEYS}/rotate", json={"note": "x", "force": True}, headers=_bearer())
        too_long = await rig.client.post(f"{KEYS}/rotate", json={"note": "x" * 501}, headers=_bearer())
        after = await rig.binding.status()
        creates = rig.store.calls.count("create")
    assert unknown.status_code == 422 and too_long.status_code == 422
    assert after["seq"] == 0 and creates == 1 and rig.audit() == []


# --------------------------------------------------------------------------- #
# POST /api/identity/keys/recovery
# --------------------------------------------------------------------------- #


async def test_recovery_prepare_then_apply_happy(tmp_path: Path) -> None:
    async with _rig(tmp_path) as rig:
        await _birth(rig.registry, "Alpha")
        before = await rig.binding.status()
        prepared = await rig.client.post(f"{KEYS}/recovery", json={"reason": "lost"}, headers=_bearer())
        plan = prepared.json()
        authorization = sign_recovery_authorization(rig.recovery_private, plan["signing_payload"])
        applied = await rig.client.post(
            f"{KEYS}/recovery", json={"reason": "lost", "authorization": authorization, "note": "laptop lost"},
            headers=_bearer(),
        )
        after = await rig.binding.status()
    assert prepared.status_code == 200, prepared.text
    assert plan["stage"] == "authorize" and plan["recovery_kid"] == before["recovery_kid"]
    assert plan["event"]["event"] == "recovery" and plan["event"]["key"]["kid"] == plan["kid"]
    assert applied.status_code == 200, applied.text
    assert applied.json()["stage"] == "applied" and applied.json()["kid"] == plan["kid"]
    assert after["active_kid"] == plan["kid"] and after["seq"] == 1 and after["continuity"] == "intact"
    assert [entry["action"] for entry in rig.audit()] == ["recovery_prepare", "recovery_apply"]
    assert rig.audit()[-1]["note"] == "laptop lost" and rig.audit()[-1]["block_index"] == applied.json()["block_index"]


async def test_recovery_403_on_bad_authorization(tmp_path: Path) -> None:
    async with _rig(tmp_path) as rig:
        plan = (await rig.client.post(f"{KEYS}/recovery", json={"reason": "lost"}, headers=_bearer())).json()
        stranger_private, _ = generate_recovery_keypair()
        forged = sign_recovery_authorization(stranger_private, plan["signing_payload"])
        refused = await rig.client.post(
            f"{KEYS}/recovery", json={"reason": "lost", "authorization": forged}, headers=_bearer(),
        )
        unchanged = await rig.binding.status()
        genuine = sign_recovery_authorization(rig.recovery_private, plan["signing_payload"])
        accepted = await rig.client.post(
            f"{KEYS}/recovery", json={"reason": "lost", "authorization": genuine}, headers=_bearer(),
        )
    assert refused.status_code == 403 and "recovery key" in refused.json()["detail"]
    assert unchanged["seq"] == 0 and unchanged["pending_recovery"] is True
    assert accepted.status_code == 200, accepted.text  # premise: the same prepared recovery applies when genuine
    assert [entry["action"] for entry in rig.audit()] == ["recovery_prepare", "recovery_apply"]


async def test_recovery_409_without_committed_recovery_key(tmp_path: Path) -> None:
    async with _rig(tmp_path, recovery=False) as rig:
        response = await rig.client.post(f"{KEYS}/recovery", json={"reason": "lost"}, headers=_bearer())
        creates = rig.store.calls.count("create")
    assert response.status_code == 409 and "recovery key" in response.json()["detail"]
    assert creates == 1 and rig.audit() == []


async def test_recovery_422_compromised_without_index(tmp_path: Path) -> None:
    async with _rig(tmp_path) as rig:
        missing = await rig.client.post(f"{KEYS}/recovery", json={"reason": "compromised"}, headers=_bearer())
        negative = await rig.client.post(
            f"{KEYS}/recovery", json={"reason": "compromised", "compromised_after_index": -1}, headers=_bearer(),
        )
        unknown_reason = await rig.client.post(f"{KEYS}/recovery", json={"reason": "stolen"}, headers=_bearer())
        status = await rig.binding.status()
        creates = rig.store.calls.count("create")
    assert missing.status_code == 422 and "compromised_after_index" in missing.json()["detail"]
    assert negative.status_code == 422 and unknown_reason.status_code == 422
    assert status["pending_recovery"] is False and creates == 1 and rig.audit() == []


# --------------------------------------------------------------------------- #
# POST /api/identity/keys/reinception
# --------------------------------------------------------------------------- #


async def test_reinception_happy_without_recovery_key(tmp_path: Path) -> None:
    async with _rig(tmp_path, recovery=False) as rig:
        before = await rig.binding.status()
        response = await rig.client.post(
            f"{KEYS}/reinception", json={"reason": "lost", "confirm": REINCEPTION_CONFIRM}, headers=_bearer(),
        )
        after = await rig.binding.status()
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["continuity"] == "broken" and body["kid"] == after["active_kid"] != before["active_kid"]
    assert after["continuity"] == "broken" and after["broken_at"] == [body["block_index"]]
    assert [entry["action"] for entry in rig.audit()] == ["reinception"]


async def test_reinception_409_with_recovery_key(tmp_path: Path) -> None:
    async with _rig(tmp_path) as rig:
        response = await rig.client.post(
            f"{KEYS}/reinception", json={"reason": "lost", "confirm": REINCEPTION_CONFIRM}, headers=_bearer(),
        )
        after = await rig.binding.status()
        creates = rig.store.calls.count("create")
    assert response.status_code == 409 and "recover instead" in response.json()["detail"]
    assert after["seq"] == 0 and creates == 1 and rig.audit() == []


async def test_reinception_422_without_confirm(tmp_path: Path) -> None:
    async with _rig(tmp_path, recovery=False) as rig:
        missing = await rig.client.post(f"{KEYS}/reinception", json={"reason": "lost"}, headers=_bearer())
        wrong = await rig.client.post(
            f"{KEYS}/reinception", json={"reason": "lost", "confirm": "yes"}, headers=_bearer(),
        )
        after = await rig.binding.status()
        creates = rig.store.calls.count("create")
    assert missing.status_code == 422 and wrong.status_code == 422
    assert after["seq"] == 0 and creates == 1 and rig.audit() == []
    # The route's literal is the one the binding module names.
    confirm = identity_routes.KeyReinceptionBody.model_fields["confirm"].annotation
    assert typing.get_args(confirm) == (REINCEPTION_CONFIRM,)


# --------------------------------------------------------------------------- #
# Audit
# --------------------------------------------------------------------------- #


async def test_key_routes_audit_without_key_material(tmp_path: Path) -> None:
    async with _rig(tmp_path) as rig:
        await rig.client.post(f"{KEYS}/rotate", json={"note": "routine"}, headers=_bearer())
        plan = (await rig.client.post(f"{KEYS}/recovery", json={"reason": "lost"}, headers=_bearer())).json()
        authorization = sign_recovery_authorization(rig.recovery_private, plan["signing_payload"])
        await rig.client.post(
            f"{KEYS}/recovery", json={"reason": "lost", "authorization": authorization}, headers=_bearer(),
        )
        status = await rig.binding.status()
        audit = rig.audit()
        details = [entry.detail for entry in rig.runtime.audit_log.entries]
        material = [*rig.duck.entries.values(), rig.recovery_private, authorization, plan["signing_payload"]]
        material += [record["public_key"] for record in status["keys"]]
    async with _rig(tmp_path / "second", recovery=False) as other:
        await other.client.post(
            f"{KEYS}/reinception", json={"reason": "lost", "confirm": REINCEPTION_CONFIRM}, headers=_bearer(),
        )
        audit += other.audit()
        details += [entry.detail for entry in other.runtime.audit_log.entries]
        material += [*other.duck.entries.values()]
    assert [entry["action"] for entry in audit] == ["rotate", "recovery_prepare", "recovery_apply", "reinception"]
    assert all(set(entry) == AUDIT_KEYS and entry["v"] == 1 for entry in audit)
    assert {entry["did"] for entry in audit} == {SHIP_A}
    assert len(details) == 4 and len(material) >= 9
    for detail in details:
        for value in material:
            assert value not in detail


async def test_key_routes_degrade_their_audit_and_map_store_failures(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    class _BrokenAudit:
        def append(self, *, category: str, detail: str) -> None:
            raise RuntimeError("AD-1196 test: the audit sink is down")

    caplog.set_level(logging.WARNING)
    async with _rig(tmp_path) as rig:
        rig.store.fail_create = True
        unavailable = await rig.client.post(f"{KEYS}/rotate", json={}, headers=_bearer())
        unchanged = await rig.binding.status()
        rig.store.fail_create = False
        rig.runtime.audit_log = None  # type: ignore[assignment]
        unaudited = await rig.client.post(f"{KEYS}/rotate", json={}, headers=_bearer())
        rig.runtime.audit_log = _BrokenAudit()  # type: ignore[assignment]
        audit_failed = await rig.client.post(f"{KEYS}/rotate", json={}, headers=_bearer())
        after = await rig.binding.status()
    assert unavailable.status_code == 503 and "stopped answering" in unavailable.json()["detail"]
    assert unchanged["seq"] == 0
    # The Captain's act stands when its audit cannot be written; the gap is logged.
    assert unaudited.status_code == 200 and audit_failed.status_code == 200
    assert after["seq"] == 2 and after["active_kid"] == audit_failed.json()["kid"]
    assert "identity key rotate took effect but is not audited" in caplog.text
    assert "auditing the Captain's identity key rotate failed" in caplog.text


# --------------------------------------------------------------------------- #
# A-0: the mutating routes refuse an open gate
# --------------------------------------------------------------------------- #

_MUTATIONS = ("rotate", "recovery_prepare", "recovery_apply", "reinception")


async def _valid_request(rig: _Rig, mutation: str) -> tuple[str, dict[str, Any]]:
    """A request each mutating route accepts once authorised (the apply step is prepared on the binding)."""
    if mutation == "rotate":
        return f"{KEYS}/rotate", {"note": "a-0"}
    if mutation == "recovery_prepare":
        return f"{KEYS}/recovery", {"reason": "lost"}
    if mutation == "recovery_apply":
        prepared = await rig.binding.prepare_recovery(
            reason="lost", compromised_after_index=None, next_recovery_public_key="",
        )
        authorization = sign_recovery_authorization(rig.recovery_private, prepared["signing_payload"])
        return f"{KEYS}/recovery", {"reason": "lost", "authorization": authorization}
    return f"{KEYS}/reinception", {"reason": "lost", "confirm": REINCEPTION_CONFIRM}


@pytest.mark.parametrize("mutation", _MUTATIONS)
async def test_mutating_key_routes_403_without_configured_token(tmp_path: Path, mutation: str) -> None:
    async with _rig(tmp_path, token="", recovery=mutation != "reinception") as rig:
        path, body = await _valid_request(rig, mutation)
        before = await rig.binding.status()
        events_before = _count_rows(rig.db_path, "identity_key_events")
        calls_before, entries_before = list(rig.store.calls), dict(rig.duck.entries)
        refused = await rig.client.post(path, json=body)
        calls_after, entries_after = list(rig.store.calls), dict(rig.duck.entries)
        events_after = _count_rows(rig.db_path, "identity_key_events")
        audit_after_refusal = rig.audit()
        unchanged = await rig.binding.status()
        rig.configure_token()
        allowed = await rig.client.post(path, json=body, headers=_bearer())
        after = await rig.binding.status()
    assert refused.status_code == 403 and refused.json()["detail"] == "identity_keys_require_token"
    assert calls_after == calls_before and entries_after == entries_before  # no key-store access at all
    assert events_after == events_before and unchanged == before
    assert audit_after_refusal == []
    # Premise: the token gate refused it, not the body -- the same request succeeds once a token is set.
    assert allowed.status_code == 200, allowed.text
    assert after["seq"] == before["seq"] + (0 if mutation == "recovery_prepare" else 1)
    assert len(rig.audit()) == 1
