"""AD-1196 (#1133): did:probos identifiers bound to Ed25519 keys.

M0 pins the AD-441/AD-443 content hashes, verifiable credentials, ledger block
hash and export shape, so the key binding provably changes none of them. The
fixed inputs and golden literals were measured at 8f24ff6f
(``logs/issue1133/probe_goldens.py``).

M1 drives the thin real chain (inception, signed births, rotation, compromise
recovery, restart, export, remote verification, armed import). M2 covers the key
store and binding failure modes; M3 the remote verifier and ``import_chain``.

No test reaches the real OS keyring: an autouse guard makes ``keyring.get_keyring``
and ``keyring.set_keyring`` raise, every store gets an injected in-memory duck
(never a ``KeyringBackend`` subclass -- those register process-wide), and the one
test that needs the production resolution path overrides ``get_keyring`` itself.
"""

from __future__ import annotations

import ast
import asyncio
import base64
import contextlib
import copy
import hashlib
import json
import logging
import sqlite3
import stat
import sys
import threading
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import keyring
import keyring.backend
import keyring.core
import pytest
from keyring.backends import fail as fail_keyring
from keyring.backends.chainer import ChainerBackend
from keyring.errors import NoKeyringError

from probos.federation.ard.jws import (
    JWS_ALG,
    b64url_encode,
    compact_detached,
    encode_protected_header,
    parse_detached,
    signing_input,
    verify_detached,
)
from probos.identity import (
    AgentBirthCertificate,
    AgentIdentityRegistry,
    LedgerBlock,
    ShipBirthCertificate,
)
from probos.identity_key_binding import IdentityKeyBinding
from probos.identity_key_store import KeyringKeyStore, PlaintextDevKeyStore, build_key_store
from probos.identity_keys import (
    EVENT_INCEPTION,
    EVENT_RECOVERY,
    EVENT_REINCEPTION,
    EVENT_ROTATION,
    KEY_EVENT_JWS_TYP,
    VC_JWS_TYP,
    IdentityKeyStateError,
    IdentityKeyUnavailable,
    KeyEvent,
    KeyEventInvalid,
    KeyStoreUnavailable,
    RecoveryAuthorizationInvalid,
    build_event_payload,
    canonical_bytes,
    derive_key_state,
    event_digest,
    generate_recovery_keypair,
    jws_kid,
    key_id,
    key_valid_at,
    sign_recovery_authorization,
    sign_with,
    signature_verdict,
    verify_chain_signatures,
    verify_signature_for,
)
from probos.mobility import TransferCertificate
from probos.storage.sqlite_factory import default_factory
from probos.substrate.device_pairing import (
    decode_private_key,
    encode_private_key,
    encode_public_key,
    generate_keypair,
    sign_challenge,
    verify_signature,
)

SHIP_HASH = "b024608a4285586363eee9cf5c1255f8b0c3865f32c2dffc9a31cd9d5d6f3150"
SHIP_VC_SHA256 = "924549ace5c177f302708e0046bf96f26de57dcc306a42c65dc8aaa39c40c7b6"
BIRTH_HASH = "a2a8cb18398036b2e02b53586fc0a8ad8b7d05cb13fab20f60ab694b3b0dd6a9"
BIRTH_VC_SHA256 = "30055ed8a2cc71d63717f775bd39d3ef2650e409475a8eeae417076e09c26702"
BLOCK_HASH = "4a68fa5b23d1638714a13e64dca404cb12ebf1b9c56f0431efb1ceb9315b1a15"
XFER_HASH = "e54a105fed8436d77826802217d0e5fc3ce90163b13e429d713e255e23d95ee5"
XFER_VC_SHA256 = "e60f2ce7d1b6ddd5981f11182498a06fc9d31703a7340b965f8a65c8318e1b8a"
XFER_DICT_SHA256 = "5ab46887c33016c07edaf4634cf8402061df2d0e0a922a39298fd473db623d3f"
XFER_DICT_KEYS = [
    "agent_type", "agent_uuid", "assignment_history", "baseline_version", "callsign",
    "certificate_hash", "did", "origin_birth_timestamp", "origin_instance_id",
    "origin_ship_did", "origin_vessel_name", "qualification_credentials",
    "target_instance_did", "transfer_timestamp",
]
LEGACY_BLOCK_KEYS = {
    "index", "timestamp", "certificate_hash", "agent_did", "previous_hash", "block_hash",
    "credential",
}
IDENTITY_TABLES = [
    "asset_tags", "birth_certificates", "foreign_birth_certificates", "foreign_chains",
    "identity_ledger", "ship_birth_certificate", "slot_mappings", "transfer_certificates",
]
SHIP_A = "did:probos:ship-a"
_SRC = Path(__file__).resolve().parents[1] / "src" / "probos"


# --------------------------------------------------------------------------- #
# Doubles and helpers
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _no_real_os_keyring(monkeypatch: pytest.MonkeyPatch) -> None:
    """Any path that would resolve the process keyring fails loudly instead (H4)."""

    def _forbidden(*_args: object, **_kwargs: object) -> Any:
        raise RuntimeError("AD-1196 tests must never reach the real OS keyring")

    monkeypatch.setattr(keyring, "get_keyring", _forbidden)
    monkeypatch.setattr(keyring, "set_keyring", _forbidden)


class _DuckKeyring:
    """In-memory keyring backend, duck-typed (never a KeyringBackend subclass, P14)."""

    def __init__(self, priority: float = 5) -> None:
        self.priority = priority
        self.entries: dict[tuple[str, str], str] = {}
        self.gets = 0

    def get_password(self, service: str, username: str) -> str | None:
        self.gets += 1
        return self.entries.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.entries[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        del self.entries[(service, username)]

    def secret(self, kid: str) -> str:
        return self.entries[(f"probos.identity:{kid}", kid)]

    def forget(self, kid: str) -> str:
        return self.entries.pop((f"probos.identity:{kid}", kid))


class _CountingStore:
    """Delegates to a real store and counts ``create`` calls."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.creates = 0

    async def describe(self) -> Any:
        return await self.inner.describe()

    async def create(self, did: str) -> tuple[str, str]:
        self.creates += 1
        return await self.inner.create(did)

    async def public_key(self, kid: str) -> str | None:
        return await self.inner.public_key(kid)

    async def sign(self, kid: str, message: str) -> str:
        return await self.inner.sign(kid, message)


class _FlakySignStore(_CountingStore):
    """A real store whose signing can be made to fail, as a backend that stops answering would."""

    def __init__(self, inner: Any) -> None:
        super().__init__(inner)
        self.fail_sign = False

    async def sign(self, kid: str, message: str) -> str:
        if self.fail_sign:
            raise KeyStoreUnavailable("AD-1196 test: the backend stopped answering")
        return await super().sign(kid, message)


class _FailingConnection:
    """Delegates to an aiosqlite connection; raises for one SQL prefix once armed."""

    def __init__(self, inner: Any, prefix: str) -> None:
        self._inner = inner
        self._prefix = prefix
        self.armed = False

    def execute(self, sql: str, parameters: Any = ()) -> Any:
        if self.armed and sql.lstrip().startswith(self._prefix):
            raise sqlite3.OperationalError("AD-1196 test: injected write failure")
        return self._inner.execute(sql, parameters)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _FailingFactory:
    def __init__(self, prefix: str) -> None:
        self._prefix = prefix
        self.connection: _FailingConnection | None = None

    async def connect(self, db_path: str) -> Any:
        self.connection = _FailingConnection(await default_factory.connect(db_path), self._prefix)
        return self.connection

    def arm(self) -> None:
        assert self.connection is not None
        self.connection.armed = True


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode("utf-8")).hexdigest()


def _golden_ship() -> ShipBirthCertificate:
    ship = ShipBirthCertificate(
        ship_did="did:probos:golden-ship", instance_id="golden-ship", vessel_name="Golden",
        commissioned_at=1790000000.5, version="1.0",
    )
    ship.certificate_hash = ship.compute_hash()
    return ship


def _golden_birth() -> AgentBirthCertificate:
    birth = AgentBirthCertificate(
        agent_uuid="00000000-0000-4000-8000-000000000001",
        did="did:probos:golden-ship:00000000-0000-4000-8000-000000000001",
        agent_type="security_officer", callsign="Worf", instance_id="golden-ship",
        vessel_name="Golden", birth_timestamp=1790000100.25, department="security",
        post_id="chief_of_security", baseline_version="v1",
    )
    birth.certificate_hash = birth.compute_hash()
    return birth


def _table_names(db_path: Path) -> list[str]:
    with contextlib.closing(sqlite3.connect(db_path)) as db:
        return sorted(
            row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        )


def _count_rows(db_path: Path, table: str) -> int:
    with contextlib.closing(sqlite3.connect(db_path)) as db:
        return int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


@contextlib.asynccontextmanager
async def _registry(
    data_dir: Path,
    *,
    instance_id: str = "ship-a",
    **kwargs: Any,
) -> AsyncIterator[AgentIdentityRegistry]:
    """A started registry, commissioned when ``instance_id`` is set; always stopped."""
    registry = AgentIdentityRegistry(data_dir=data_dir, **kwargs)
    try:
        await registry.start()
        if instance_id:
            await registry.start(instance_id=instance_id, vessel_name=instance_id.title(), version="1")
        yield registry
    finally:
        await registry.stop()


@contextlib.asynccontextmanager
async def _armed(
    data_dir: Path,
    backend: Any,
    *,
    recovery_public_key: str = "",
    instance_id: str = "ship-a",
    store: Any | None = None,
    connection_factory: Any | None = None,
) -> AsyncIterator[tuple[AgentIdentityRegistry, IdentityKeyBinding]]:
    """A registry with a key binding over ``backend`` (or ``store``), constructed directly."""
    binding = IdentityKeyBinding(
        store if store is not None else KeyringKeyStore(backend=backend),
        recovery_public_key=recovery_public_key,
    )
    extra: dict[str, Any] = {"key_binding": binding}
    if connection_factory is not None:
        extra["connection_factory"] = connection_factory
    async with _registry(data_dir, instance_id=instance_id, **extra) as registry:
        yield registry, binding


async def _birth(
    registry: AgentIdentityRegistry, callsign: str, *, instance_id: str = "ship-a",
) -> AgentBirthCertificate:
    return await registry.issue_birth_certificate(
        agent_type="crew", callsign=callsign, instance_id=instance_id,
        vessel_name=instance_id.title(), department="operations", post_id=f"post-{callsign}",
        baseline_version="v1", slot_id=f"slot-{callsign}",
    )


def _block_for(chain: list[dict[str, Any]], certificate_hash: str) -> dict[str, Any]:
    matches = [block for block in chain if block["certificate_hash"] == certificate_hash]
    assert len(matches) == 1, certificate_hash
    return matches[0]


def _vc_jws(
    private_key: Any, kid: str, credential: dict[str, Any], *, anchor_index: int, birth_credential_digest: str = "",
) -> str:
    """Sign a credential exactly as the binding does, with any key, kid and anchor."""
    claims: dict[str, Any] = {"anchor_index": anchor_index}
    if birth_credential_digest:
        claims["birth_credential_digest"] = birth_credential_digest
    return sign_with(
        canonical_bytes(credential), kid=kid, typ=VC_JWS_TYP,
        sign=lambda message: sign_challenge(private_key, message), claims=claims,
    )


def _append_block(
    chain: list[dict[str, Any]], *, certificate_hash: str, agent_did: str, **extra: Any,
) -> dict[str, Any]:
    """Append a hash-valid block to an exported chain (the remote verifier sees only data)."""
    last = chain[-1]
    block = LedgerBlock(
        index=last["index"] + 1, timestamp=last["timestamp"] + 1.0,
        certificate_hash=certificate_hash, agent_did=agent_did, previous_hash=last["block_hash"],
    )
    block.block_hash = block.compute_hash()
    row = {
        "index": block.index, "timestamp": block.timestamp, "certificate_hash": block.certificate_hash,
        "agent_did": block.agent_did, "previous_hash": block.previous_hash,
        "block_hash": block.block_hash, "credential": None, **extra,
    }
    chain.append(row)
    return row


def _imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, f"{path.name}: relative import"
            modules.add(node.module or "")
    return modules


@dataclass
class _Origin:
    """A signed origin chain: inception K1, Alpha, rotation K2, Bravo, Charlie, compromise recovery K3, Delta."""

    chain: list[dict[str, Any]]
    keyring: _DuckKeyring
    kids: tuple[str, str, str]
    certs: dict[str, AgentBirthCertificate]
    compromised_after: int

    def private_key(self, kid: str) -> Any:
        return decode_private_key(self.keyring.secret(kid))

    def public_key(self, kid: str) -> str:
        return encode_public_key(self.private_key(kid).public_key())

    def block(self, chain: list[dict[str, Any]], callsign: str) -> dict[str, Any]:
        return _block_for(chain, self.certs[callsign].certificate_hash)


async def _signed_origin(data_dir: Path) -> _Origin:
    duck = _DuckKeyring()
    recovery_private, recovery_public = generate_recovery_keypair()
    certs: dict[str, AgentBirthCertificate] = {}
    async with _armed(data_dir, duck, recovery_public_key=recovery_public) as (registry, binding):
        k1 = (await binding.status())["active_kid"]
        certs["Alpha"] = await _birth(registry, "Alpha")
        k2 = (await binding.rotate())["kid"]
        certs["Bravo"] = await _birth(registry, "Bravo")
        certs["Charlie"] = await _birth(registry, "Charlie")
        compromised_after = _block_for(await registry.export_chain(), certs["Bravo"].certificate_hash)["index"]
        prepared = await binding.prepare_recovery(
            reason="compromised", compromised_after_index=compromised_after, next_recovery_public_key="",
        )
        k3 = (await binding.apply_recovery(
            authorization=sign_recovery_authorization(recovery_private, prepared["signing_payload"]),
            reason="compromised", compromised_after_index=compromised_after, next_recovery_public_key="",
        ))["kid"]
        certs["Delta"] = await _birth(registry, "Delta")
        chain = json.loads(json.dumps(await registry.export_chain()))
    return _Origin(chain, duck, (k1, k2, k3), certs, compromised_after)


# --------------------------------------------------------------------------- #
# M0 -- byte-identity pins
# --------------------------------------------------------------------------- #


def test_m0_ship_and_birth_certificate_hashes_and_vcs_are_unchanged() -> None:
    ship = _golden_ship()
    birth = _golden_birth()
    assert ship.certificate_hash == SHIP_HASH
    assert _digest(ship.to_verifiable_credential()) == SHIP_VC_SHA256
    assert birth.certificate_hash == BIRTH_HASH
    assert _digest(birth.to_verifiable_credential()) == BIRTH_VC_SHA256
    assert ship.to_verifiable_credential()["proof"]["type"] == "Sha256Hash2024"
    assert birth.to_verifiable_credential()["proof"]["type"] == "Sha256Hash2024"


def test_m0_ledger_block_hash_is_unchanged() -> None:
    birth = _golden_birth()
    block = LedgerBlock(
        index=1, timestamp=1790000100.25, certificate_hash=birth.certificate_hash,
        agent_did=birth.did, previous_hash="a" * 64,
    )
    assert block.compute_hash() == BLOCK_HASH


def test_m0_transfer_certificate_hash_vc_and_dict_are_unchanged() -> None:
    birth = _golden_birth()
    xfer = TransferCertificate(
        did=birth.did, agent_uuid=birth.agent_uuid, agent_type="security_officer", callsign="Worf",
        origin_ship_did="did:probos:golden-ship", origin_vessel_name="Golden",
        origin_instance_id="golden-ship", origin_birth_timestamp=1790000100.25,
        transfer_timestamp=1790000200.75, target_instance_did="did:probos:golden-target",
        baseline_version="v1", qualification_credentials=["b", "a"],
        assignment_history=[{
            "instance_did": "did:probos:golden-ship", "vessel_name": "Golden",
            "joined_at": 1790000100.25, "departed_at": 1790000200.75,
        }],
    )
    xfer.certificate_hash = xfer.compute_hash()
    assert xfer.certificate_hash == XFER_HASH
    assert _digest(xfer.to_verifiable_credential()) == XFER_VC_SHA256
    assert _digest(xfer.to_dict()) == XFER_DICT_SHA256
    assert sorted(xfer.to_dict()) == XFER_DICT_KEYS


async def test_m0_unarmed_registry_keeps_schema_and_export_shape(tmp_path: Path) -> None:
    data_dir = tmp_path / "ship"
    async with _registry(data_dir) as registry:
        await _birth(registry, "Alpha")
        await _birth(registry, "Bravo")
        blocks = await registry.export_chain()
        valid, _ = await registry.verify_chain()
    assert valid
    assert len(blocks) == 3
    assert all(set(block) == LEGACY_BLOCK_KEYS for block in blocks)
    assert blocks[0]["credential"]["type"][-1] == "ShipBirthCertificate"
    assert _table_names(data_dir / "identity.db") == IDENTITY_TABLES


# --------------------------------------------------------------------------- #
# M1 -- one signing stack, and the thin real chain
# --------------------------------------------------------------------------- #


def test_jws_module_has_zero_project_imports() -> None:
    path = _SRC / "federation" / "ard" / "jws.py"
    source = path.read_text(encoding="utf-8")
    # Vendorable verbatim, like jcs.py: the project name appears nowhere, in any case.
    assert "probos" not in source.lower()
    roots = {name.split(".")[0] for name in _imported_modules(path)}
    assert roots <= set(sys.stdlib_module_names) | {"__future__"}, roots


def test_no_third_signing_stack() -> None:
    forbidden = {"cryptography", "nacl", "jwt", "jose"}
    for name in ("identity_keys.py", "identity_key_store.py", "identity_key_binding.py"):
        roots = {module.split(".")[0] for module in _imported_modules(_SRC / name)}
        assert not roots & forbidden, (name, roots & forbidden)
    # Every Ed25519 operation goes through AD-843b's primitives.
    assert "probos.substrate.device_pairing" in _imported_modules(_SRC / "identity_keys.py")
    assert "probos.substrate.device_pairing" in _imported_modules(_SRC / "identity_key_store.py")
    # The ARD trust verifier delegates to the extracted module rather than keeping its own copy.
    verifier = (_SRC / "federation" / "ard" / "trust_verifier.py").read_text(encoding="utf-8")
    assert "from .jws import" in verifier
    for name in ("_b64url_decode", "_b64url_encode", "_B64URL_RE", "_JWS_ALG", "import base64"):
        assert name not in verifier, name


_JWS_PAYLOAD = b'{"a":1}'
_JWS_HEADER = {"alg": "EdDSA", "kid": "did:example:k#key-1", "typ": "t"}


def _raw_jws(private_key: Any, header: object, payload: bytes = _JWS_PAYLOAD) -> str:
    """Build a detached JWS without the encoder's own checks (so rejected headers can be expressed)."""
    protected = b64url_encode(json.dumps(header, sort_keys=True, separators=(",", ":")).encode("ascii"))
    signature = base64.b64decode(sign_challenge(private_key, signing_input(protected, payload).decode("ascii")))
    return compact_detached(protected, signature)


@pytest.mark.parametrize(
    "case",
    ["valid", "attached", "crit", "alg_none", "typ_mismatch", "header_not_object", "malformed"],
)
def test_jws_round_trip_and_rejections(case: str) -> None:
    private_key, public_key = generate_keypair()
    valid = _raw_jws(private_key, _JWS_HEADER)
    # Premise for every rejection: the well-formed token verifies.
    assert verify_detached(valid, _JWS_PAYLOAD, public_key, verify_signature, expected_typ="t") is True
    if case == "valid":
        parsed = parse_detached(valid, expected_typ="t")
        assert parsed is not None and parsed.header == _JWS_HEADER
        assert encode_protected_header(_JWS_HEADER) == valid.split(".")[0]
        assert verify_detached(valid, b'{"a":2}', public_key, verify_signature) is False
    elif case == "attached":
        protected, _, signature = valid.split(".")
        attached = f"{protected}.{b64url_encode(_JWS_PAYLOAD)}.{signature}"
        assert parse_detached(attached) is None
        assert verify_detached(attached, _JWS_PAYLOAD, public_key, verify_signature) is False
    elif case == "crit":
        header = {**_JWS_HEADER, "b64": False, "crit": ["b64"]}
        assert verify_detached(_raw_jws(private_key, header), _JWS_PAYLOAD, public_key, verify_signature) is False
        with pytest.raises(ValueError):
            encode_protected_header(header)
    elif case == "alg_none":
        header = {**_JWS_HEADER, "alg": "none"}
        assert verify_detached(_raw_jws(private_key, header), _JWS_PAYLOAD, public_key, verify_signature) is False
        with pytest.raises(ValueError):
            encode_protected_header(header)
    elif case == "typ_mismatch":
        assert verify_detached(valid, _JWS_PAYLOAD, public_key, verify_signature, expected_typ="other") is False
        assert parse_detached(valid, expected_typ="other") is None
        assert verify_detached(valid, _JWS_PAYLOAD, public_key, verify_signature) is True
    elif case == "header_not_object":
        token = _raw_jws(private_key, ["EdDSA"])
        assert parse_detached(token) is None
        assert verify_detached(token, _JWS_PAYLOAD, public_key, verify_signature) is False
    else:
        protected = valid.split(".")[0]
        for token in ("!!!..abc", f"{protected}..&&&", "bm90LWpzb24..YWJj"):
            with pytest.raises(ValueError):
                verify_detached(token, _JWS_PAYLOAD, public_key, verify_signature)
        # The header is judged before the signature segment is decoded (AD-1144's order).
        assert verify_detached("eyJhIjoxfQ..&&&", _JWS_PAYLOAD, public_key, verify_signature) is False
        assert parse_detached("a.b") is None


def test_private_key_round_trip_and_rejection() -> None:
    private_key, public_key = generate_keypair()
    encoded = encode_private_key(private_key)
    assert len(base64.b64decode(encoded)) == 32
    restored = decode_private_key(encoded)
    assert encode_public_key(restored.public_key()) == public_key
    assert verify_signature(public_key, "message", sign_challenge(restored, "message"))
    for bad in ("not base64!", base64.b64encode(b"k" * 31).decode(), base64.b64encode(b"k" * 33).decode()):
        with pytest.raises(ValueError) as excinfo:
            decode_private_key(bad)
        assert bad not in str(excinfo.value)
    with pytest.raises(ValueError):
        decode_private_key("")


async def test_m1_thin_chain_signs_rotates_revokes_persists_reloads_and_verifies(tmp_path: Path) -> None:
    duck = _DuckKeyring()
    recovery_private, recovery_public = generate_recovery_keypair()
    origin_dir = tmp_path / "origin"
    certs: dict[str, AgentBirthCertificate] = {}
    async with _armed(origin_dir, duck, recovery_public_key=recovery_public) as (registry, binding):
        incepted = await binding.status()
        assert incepted["status"] == "active" and incepted["seq"] == 0  # premise: the ship is bound
        k1 = incepted["active_kid"]
        assert k1 == key_id(SHIP_A, incepted["keys"][0]["public_key"])
        assert k1.startswith(f"{SHIP_A}#key-") and len(k1.rsplit("-", 1)[1]) == 16
        document = incepted["did_document"]
        assert document["id"] == SHIP_A and document["assertionMethod"] == [k1]
        method = document["verificationMethod"][0]
        assert method["id"] == k1 and method["type"] == "JsonWebKey2020"
        assert method["publicKeyJwk"]["crv"] == "Ed25519" and method["publicKeyJwk"]["kty"] == "OKP"
        certs["Alpha"] = await _birth(registry, "Alpha")
        k2 = (await binding.rotate())["kid"]
        certs["Bravo"] = await _birth(registry, "Bravo")
        certs["Charlie"] = await _birth(registry, "Charlie")
        i_bravo = _block_for(await registry.export_chain(), certs["Bravo"].certificate_hash)["index"]
        prepared = await binding.prepare_recovery(
            reason="compromised", compromised_after_index=i_bravo, next_recovery_public_key="",
        )
        authorization = sign_recovery_authorization(recovery_private, prepared["signing_payload"])
        k3 = (await binding.apply_recovery(
            authorization=authorization, reason="compromised", compromised_after_index=i_bravo,
            next_recovery_public_key="",
        ))["kid"]
        certs["Delta"] = await _birth(registry, "Delta")
    assert len({k1, k2, k3}) == 3

    restarted = IdentityKeyBinding(KeyringKeyStore(backend=duck), recovery_public_key=recovery_public)
    async with _registry(origin_dir, key_binding=restarted) as registry:
        status = await restarted.status()
        valid, message = await registry.verify_chain()
        chain = json.loads(json.dumps(await registry.export_chain()))
    assert status["status"] == "active" and status["active_kid"] == k3 and status["seq"] == 2
    assert valid, message

    report = verify_chain_signatures(chain)
    assert report.ok, report.reason
    assert report.state is not None and report.key_events == 3
    assert report.state.continuity == "intact"
    assert report.state.ship_certificate_hash == chain[0]["certificate_hash"]
    assert report.state.ship_credential_digest == hashlib.sha256(canonical_bytes(chain[0]["credential"])).hexdigest()
    expected = {"Alpha": (k1, "valid"), "Bravo": (k2, "valid"), "Charlie": (k2, "void"), "Delta": (k3, "valid")}
    for callsign, (kid, verdict) in expected.items():
        block = _block_for(chain, certs[callsign].certificate_hash)
        jws = block["attestation"]["jws"]
        assert block["attestation"]["kind"] == "agent_birth"
        assert jws_kid(jws) == kid, callsign
        assert signature_verdict(
            report.state, record_bytes=canonical_bytes(block["credential"]), jws=jws,
            anchor_index=block["index"], typ=VC_JWS_TYP,
        ) == verdict, callsign
    charlie = _block_for(chain, certs["Charlie"].certificate_hash)
    k2_record = report.state.key(k2)
    assert k2_record is not None and k2_record.compromised_after == i_bravo
    # Premise of "void": Charlie's signature is genuine under K2; only the compromise point voids it.
    assert verify_signature_for(
        charlie["attestation"]["jws"], canonical_bytes(charlie["credential"]),
        public_key_b64=k2_record.public_key, kid=k2, typ=VC_JWS_TYP,
    )
    assert report.void == (charlie["index"],) and report.valid == 3

    async with _armed(tmp_path / "peer", _DuckKeyring(), instance_id="peer") as (peer, _):
        imported, imported_message = await peer.import_chain(chain)
    assert imported, imported_message


# --------------------------------------------------------------------------- #
# M2 -- key store and binding: fail closed, lifecycle negatives
# --------------------------------------------------------------------------- #


async def test_keyring_store_refuses_backend_below_recommended_priority() -> None:
    insecure = _DuckKeyring(priority=0.5)
    insecure.set_password("svc", "user", "value")
    assert insecure.get_password("svc", "user") == "value"  # premise: the backend itself works
    store = KeyringKeyStore(backend=insecure)
    status = await store.describe()
    assert status.available is False and status.secure is False
    assert "priority 0.5" in status.reason
    with pytest.raises(KeyStoreUnavailable):
        await store.create(SHIP_A)
    assert insecure.entries == {("svc", "user"): "value"}
    accepted = await KeyringKeyStore(backend=_DuckKeyring(priority=1)).describe()
    assert accepted.available is True and accepted.secure is True


async def test_keyring_store_refuses_chainer_with_only_insecure_backends(monkeypatch: pytest.MonkeyPatch) -> None:
    low, lower = _DuckKeyring(priority=0.8), _DuckKeyring(priority=0.5)
    monkeypatch.setattr(keyring.backend, "get_all_keyring", lambda: [lower, low])
    chainer = ChainerBackend()
    assert keyring.core.recommended(chainer)  # premise: the chainer itself claims a secure priority
    assert list(chainer.backends) == [low, lower]
    status = await KeyringKeyStore(backend=chainer).describe()
    assert status.available is False
    assert "chained" in status.reason
    with pytest.raises(KeyStoreUnavailable):
        await KeyringKeyStore(backend=chainer).public_key(f"{SHIP_A}#key-0000000000000000")
    assert low.gets == 0 and lower.gets == 0


async def test_keyring_store_never_reads_through_a_chainer_fallthrough(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    secure, insecure = _DuckKeyring(priority=5), _DuckKeyring(priority=0.5)
    async with _armed(tmp_path / "ship", secure) as (_, binding):
        kid = (await binding.status())["active_kid"]
    insecure.set_password(f"probos.identity:{kid}", kid, secure.forget(kid))
    monkeypatch.setattr(keyring.backend, "get_all_keyring", lambda: [insecure, secure])
    chainer = ChainerBackend()
    # Premise: the chain itself answers a secure miss with the insecure backend's value.
    assert chainer.get_password(f"probos.identity:{kid}", kid) == insecure.secret(kid)
    insecure.gets = 0
    async with _armed(tmp_path / "ship", chainer) as (registry, binding):
        status = await binding.status()
        cert = await _birth(registry, "Alpha")
        chain = await registry.export_chain()
    assert status["status"] == "key_missing" and status["active_kid"] == kid
    assert insecure.gets == 0
    assert "attestation" not in _block_for(chain, cert.certificate_hash)


async def test_missing_keyring_backend_fails_closed_and_boot_continues_unsigned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    absent = fail_keyring.Keyring()
    with pytest.raises(NoKeyringError):
        absent.get_password("svc", "user")  # premise: this backend cannot store anything
    monkeypatch.setattr(keyring, "get_keyring", lambda: absent)
    caplog.set_level(logging.WARNING)
    data_dir = tmp_path / "ship"
    async with _armed(data_dir, None, store=KeyringKeyStore()) as (registry, binding):
        status = await binding.status()
        cert = await _birth(registry, "Alpha")
        chain = await registry.export_chain()
        valid, _ = await registry.verify_chain()
    assert status["status"] == "unbound"
    assert "keyring.backends.fail.Keyring" in status["reason"]
    assert status["store"]["available"] is False and status["did_document"] is None
    assert valid and cert.certificate_hash == _block_for(chain, cert.certificate_hash)["certificate_hash"]
    assert all("attestation" not in block for block in chain)
    assert "issued UNSIGNED" in caplog.text
    assert not (data_dir / "identity-keys-dev").exists()
    assert not list(data_dir.rglob("*.key"))
    assert _count_rows(data_dir / "identity.db", "identity_key_events") == 0


async def test_keyring_store_timeout_is_unavailable() -> None:
    release = threading.Event()

    class _Blocking(_DuckKeyring):
        def get_password(self, service: str, username: str) -> str | None:
            release.wait(timeout=30)
            return super().get_password(service, username)

    store = KeyringKeyStore(backend=_Blocking(), timeout_seconds=0.2)
    kid = f"{SHIP_A}#key-0000000000000000"
    try:
        started = time.monotonic()
        with pytest.raises(KeyStoreUnavailable, match="did not answer"):
            await store.public_key(kid)
        assert time.monotonic() - started < 5
    finally:
        release.set()
    assert await store.public_key(kid) is None  # premise: unblocked, the same call answers


async def test_keyring_store_fails_closed_on_broken_backends(tmp_path: Path) -> None:
    kid = f"{SHIP_A}#key-0000000000000000"

    class _Dropping(_DuckKeyring):
        def set_password(self, service: str, username: str, password: str) -> None:
            return None  # accepts the write, persists nothing

    class _Raising(_DuckKeyring):
        def get_password(self, service: str, username: str) -> str | None:
            raise OSError("AD-1196 test: backend fault")

    # Premise: on a healthy backend the same lookup is a plain miss, not an error.
    assert await KeyringKeyStore(backend=_DuckKeyring()).public_key(kid) is None
    with pytest.raises(KeyStoreUnavailable, match="did not persist"):
        await KeyringKeyStore(backend=_Dropping()).create(SHIP_A)
    malformed = _DuckKeyring()
    malformed.set_password(f"probos.identity:{kid}", kid, "not a key")
    with pytest.raises(KeyStoreUnavailable, match="malformed"):
        await KeyringKeyStore(backend=malformed).public_key(kid)
    with pytest.raises(KeyStoreUnavailable, match="OSError"):
        await KeyringKeyStore(backend=_Raising()).public_key(kid)
    directory = tmp_path / "dev"
    dev_kid, _ = await PlaintextDevKeyStore(directory).create(SHIP_A)
    next(directory.glob("*.key")).write_text("{}", encoding="utf-8")
    with pytest.raises(KeyStoreUnavailable, match="malformed"):
        await PlaintextDevKeyStore(directory).public_key(dev_kid)


async def test_plaintext_dev_store_only_when_configured_and_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    directory = tmp_path / "identity-keys-dev"
    assert isinstance(build_key_store("keyring", tmp_path), KeyringKeyStore)
    assert not directory.exists() and "UNENCRYPTED" not in caplog.text
    with pytest.raises(ValueError):
        build_key_store("plaintext", tmp_path)
    store = build_key_store("plaintext_dev", tmp_path)
    assert isinstance(store, PlaintextDevKeyStore)
    assert "UNENCRYPTED" in caplog.text and str(directory) in caplog.text
    status = await store.describe()
    assert status.kind == "plaintext_dev" and status.secure is False and status.available is True
    kid, public_key = await store.create(SHIP_A)
    files = list(directory.glob("*.key"))
    assert len(files) == 1
    content = json.loads(files[0].read_text(encoding="utf-8"))
    assert set(content) == {"kid", "private_key"} and content["kid"] == kid
    assert await store.public_key(kid) == public_key
    assert verify_signature(public_key, "message", await store.sign(kid, "message"))
    assert await PlaintextDevKeyStore(directory).public_key(kid) == public_key
    assert await store.public_key(f"{SHIP_A}#key-0000000000000000") is None


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX modes; Windows relies on the profile ACL (H23)")
async def test_plaintext_dev_store_file_modes_on_posix(tmp_path: Path) -> None:
    directory = tmp_path / "keys"
    await PlaintextDevKeyStore(directory).create(SHIP_A)
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert [stat.S_IMODE(path.stat().st_mode) for path in directory.glob("*.key")] == [0o600]


async def test_missing_key_entry_reports_key_missing_and_never_regenerates(tmp_path: Path) -> None:
    duck = _DuckKeyring()
    async with _armed(tmp_path / "ship", duck) as (_, binding):
        first = await binding.status()
    assert first["status"] == "active"  # premise
    duck.forget(first["active_kid"])
    counting = _CountingStore(KeyringKeyStore(backend=duck))
    async with _armed(tmp_path / "ship", duck, store=counting) as (registry, binding):
        cert = await _birth(registry, "Alpha")
        status = await binding.status()
        with pytest.raises(IdentityKeyStateError):
            await binding.rotate()
        chain = await registry.export_chain()
    assert status["status"] == "key_missing" and status["active_kid"] == first["active_kid"]
    assert counting.creates == 0 and duck.entries == {}
    assert "attestation" not in _block_for(chain, cert.certificate_hash)


async def test_mismatched_store_key_refuses_to_sign(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    duck = _DuckKeyring()
    async with _armed(tmp_path / "ship", duck) as (_, binding):
        first = await binding.status()
    assert first["status"] == "active"  # premise
    other_private, _ = generate_keypair()
    kid = first["active_kid"]
    duck.set_password(f"probos.identity:{kid}", kid, encode_private_key(other_private))
    caplog.set_level(logging.WARNING)
    async with _armed(tmp_path / "ship", duck) as (registry, binding):
        cert = await _birth(registry, "Alpha")
        status = await binding.status()
        chain = await registry.export_chain()
    assert status["status"] == "key_mismatch"
    assert "attestation" not in _block_for(chain, cert.certificate_hash)
    assert "issued UNSIGNED" in caplog.text


async def test_sign_failure_latches_key_unavailable_and_required_signing_raises(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    duck = _DuckKeyring()
    flaky = _FlakySignStore(KeyringKeyStore(backend=duck))
    caplog.set_level(logging.WARNING)
    async with _armed(tmp_path / "ship", duck, store=flaky) as (registry, binding):
        alpha = await _birth(registry, "Alpha")
        flaky.fail_sign = True
        with pytest.raises(KeyStoreUnavailable):
            await binding.sign_record_locked({"probe": 1}, required=True)
        latched = await binding.status()
        bravo = await _birth(registry, "Bravo")
        with pytest.raises(IdentityKeyUnavailable):
            await binding.sign_record_locked({"probe": 2}, required=True)
        assert await binding.sign_record_locked({"probe": 3}) is None
        chain = await registry.export_chain()
    assert "attestation" in _block_for(chain, alpha.certificate_hash)  # premise: signing worked
    assert latched["status"] == "key_unavailable"
    assert "attestation" not in _block_for(chain, bravo.certificate_hash)
    assert "unsigned until resolved" in caplog.text and "issued UNSIGNED" in caplog.text


async def test_placeholder_genesis_refuses_inception(tmp_path: Path) -> None:
    duck = _DuckKeyring()
    binding = IdentityKeyBinding(KeyringKeyStore(backend=duck))
    data_dir = tmp_path / "ship"
    async with _registry(data_dir, instance_id="", key_binding=binding) as registry:
        await _birth(registry, "Early")  # a birth before commissioning writes the placeholder genesis
        genesis = (await registry.export_chain())[0]
        assert (genesis["agent_did"], genesis["certificate_hash"]) == ("ship", "genesis")  # premise
        await registry.start(instance_id="ship-a", vessel_name="Ship-A", version="1")
        assert registry.get_ship_certificate() is not None
        status = await binding.status()
    assert status["status"] == "unbound" and "genesis" in status["reason"]
    assert duck.entries == {}
    assert _count_rows(data_dir / "identity.db", "identity_key_events") == 0


async def test_failed_key_event_write_latches_needs_restart_and_restart_rederives(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    duck = _DuckKeyring()
    data_dir = tmp_path / "ship"
    factory = _FailingFactory("INSERT INTO identity_key_events")
    caplog.set_level(logging.ERROR)
    async with _armed(data_dir, duck, connection_factory=factory) as (registry, binding):
        k1 = (await binding.status())["active_kid"]
        alpha = await _birth(registry, "Alpha")
        factory.arm()
        with pytest.raises(sqlite3.OperationalError):
            await binding.rotate()
        latched = await binding.status()
        bravo = await _birth(registry, "Bravo")
        with pytest.raises(IdentityKeyStateError):
            await binding.rotate()
        before_restart = await registry.export_chain()
    assert "attestation" in _block_for(before_restart, alpha.certificate_hash)  # premise: signing worked
    assert latched["status"] == "needs_restart" and latched["active_kid"] == k1
    assert "attestation" not in _block_for(before_restart, bravo.certificate_hash)
    assert "could not be recorded" in caplog.text
    async with _armed(data_dir, duck) as (registry, binding):
        status = await binding.status()
        valid, message = await registry.verify_chain()
        chain = await registry.export_chain()
    assert status["status"] == "active" and status["active_kid"] == k1 and status["seq"] == 0
    assert valid, message
    orphans = [block for block in chain[1:] if block["agent_did"] == SHIP_A and "attestation" not in block]
    assert len(orphans) == 1
    report = verify_chain_signatures(chain)
    assert report.ok and report.key_events == 1 and report.valid == 1


async def test_rotation_concurrent_with_births_keeps_every_signature_in_window(tmp_path: Path) -> None:
    duck = _DuckKeyring()
    async with _armed(tmp_path / "ship", duck) as (registry, binding):
        k1 = (await binding.status())["active_kid"]
        for index in range(2):
            await _birth(registry, f"Early{index}")
        results = await asyncio.gather(
            binding.rotate(), *(_birth(registry, f"Late{index}") for index in range(6)),
        )
        chain = await registry.export_chain()
    rotation = results[0]
    births = [block for block in chain if (block.get("attestation") or {}).get("kind") == "agent_birth"]
    kids = {jws_kid(block["attestation"]["jws"]) for block in births}
    assert kids == {k1, rotation["kid"]}  # premise: births were signed on both sides of the rotation
    for block in births:
        expected = k1 if block["index"] < rotation["block_index"] else rotation["kid"]
        assert jws_kid(block["attestation"]["jws"]) == expected
    report = verify_chain_signatures(chain)
    assert report.ok, report.reason
    assert report.valid == 8 and report.void == ()


async def test_recovery_for_a_lost_key_keeps_its_earlier_signatures_valid(tmp_path: Path) -> None:
    duck = _DuckKeyring()
    recovery_private, recovery_public = generate_recovery_keypair()
    data_dir = tmp_path / "ship"
    async with _armed(data_dir, duck, recovery_public_key=recovery_public) as (registry, binding):
        k1 = (await binding.status())["active_kid"]
        alpha = await _birth(registry, "Alpha")
    duck.forget(k1)
    async with _armed(data_dir, duck, recovery_public_key=recovery_public) as (registry, binding):
        assert (await binding.status())["status"] == "key_missing"  # premise: the key really is lost
        prepared = await binding.prepare_recovery(
            reason="lost", compromised_after_index=None, next_recovery_public_key="",
        )
        applied = await binding.apply_recovery(
            authorization=sign_recovery_authorization(recovery_private, prepared["signing_payload"]),
            reason="lost", compromised_after_index=None, next_recovery_public_key="",
        )
        status = await binding.status()
        bravo = await _birth(registry, "Bravo")
        chain = await registry.export_chain()
    assert status["status"] == "active" and status["active_kid"] == applied["kid"] != k1
    report = verify_chain_signatures(chain)
    assert report.ok, report.reason
    assert report.state is not None and report.state.continuity == "intact"
    assert report.void == () and report.valid == 2
    assert jws_kid(_block_for(chain, alpha.certificate_hash)["attestation"]["jws"]) == k1
    assert jws_kid(_block_for(chain, bravo.certificate_hash)["attestation"]["jws"]) == applied["kid"]
    k1_record = report.state.key(k1)
    assert k1_record is not None
    assert k1_record.retired_at == applied["block_index"] and k1_record.compromised_after is None


async def test_reinception_without_recovery_key_breaks_continuity_and_voids_after_compromise(tmp_path: Path) -> None:
    duck = _DuckKeyring()
    async with _armed(tmp_path / "ship", duck) as (registry, binding):
        k1 = (await binding.status())["active_kid"]
        alpha = await _birth(registry, "Alpha")
        bravo = await _birth(registry, "Bravo")
        i_alpha = _block_for(await registry.export_chain(), alpha.certificate_hash)["index"]
        result = await binding.reincept(reason="compromised", compromised_after_index=i_alpha)
        charlie = await _birth(registry, "Charlie")
        chain = await registry.export_chain()
    assert result["continuity"] == "broken" and result["kid"] != k1
    report = verify_chain_signatures(chain)
    assert report.ok, report.reason
    assert report.state is not None
    assert report.state.continuity == "broken" and report.state.broken_at == (result["block_index"],)
    bravo_block = _block_for(chain, bravo.certificate_hash)
    k1_record = report.state.key(k1)
    assert k1_record is not None
    assert verify_signature_for(  # premise: Bravo's signature is genuine under K1
        bravo_block["attestation"]["jws"], canonical_bytes(bravo_block["credential"]),
        public_key_b64=k1_record.public_key, kid=k1, typ=VC_JWS_TYP,
    )
    assert report.void == (bravo_block["index"],) and report.valid == 2
    assert jws_kid(_block_for(chain, charlie.certificate_hash)["attestation"]["jws"]) == result["kid"]


async def test_reinception_refused_when_recovery_key_committed(tmp_path: Path) -> None:
    duck = _DuckKeyring()
    _, recovery_public = generate_recovery_keypair()
    counting = _CountingStore(KeyringKeyStore(backend=duck))
    async with _armed(tmp_path / "ship", duck, recovery_public_key=recovery_public, store=counting) as (_, binding):
        before = await binding.status()
        assert before["recovery_committed"] is True and counting.creates == 1  # premise
        with pytest.raises(IdentityKeyStateError):
            await binding.reincept(reason="lost", compromised_after_index=None)
        after = await binding.status()
    assert counting.creates == 1
    assert (after["seq"], after["active_kid"]) == (before["seq"], before["active_kid"])


async def test_recovery_rejects_wrong_signer_and_stale_prepare(tmp_path: Path) -> None:
    duck = _DuckKeyring()
    recovery_private, recovery_public = generate_recovery_keypair()
    wrong_private, _ = generate_recovery_keypair()
    async with _armed(tmp_path / "ship", duck, recovery_public_key=recovery_public) as (_, binding):
        before = await binding.status()
        prepared = await binding.prepare_recovery(
            reason="lost", compromised_after_index=None, next_recovery_public_key="",
        )
        assert prepared["stage"] == "authorize" and prepared["recovery_kid"] == before["recovery_kid"]
        payload_bytes = base64.urlsafe_b64decode(
            prepared["signing_payload"] + "=" * (-len(prepared["signing_payload"]) % 4)
        )
        with pytest.raises(ValueError):  # the recovery key signs recovery events and nothing else
            sign_recovery_authorization(
                recovery_private,
                b64url_encode(b'{"did":"did:probos:ship-a","event":"rotation","type":"probos.identity.key-event"}'),
            )
        forged = sign_recovery_authorization(wrong_private, prepared["signing_payload"])
        genuine = sign_recovery_authorization(recovery_private, prepared["signing_payload"])
        # Premise: the same payload, signed by the committed recovery key, does verify.
        assert verify_signature_for(
            genuine, payload_bytes, public_key_b64=recovery_public, kid=before["recovery_kid"],
            typ=KEY_EVENT_JWS_TYP,
        )
        with pytest.raises(RecoveryAuthorizationInvalid):
            await binding.apply_recovery(
                authorization=forged, reason="lost", compromised_after_index=None,
                next_recovery_public_key="",
            )
        assert (await binding.status())["seq"] == before["seq"]
        with pytest.raises(IdentityKeyStateError):
            await binding.apply_recovery(
                authorization=genuine, reason="compromised", compromised_after_index=1,
                next_recovery_public_key="",
            )
        await binding.rotate()  # moves the head: the prepared payload is now stale
        with pytest.raises(IdentityKeyStateError):
            await binding.apply_recovery(
                authorization=genuine, reason="lost", compromised_after_index=None,
                next_recovery_public_key="",
            )
        after = await binding.status()
    assert after["seq"] == before["seq"] + 1  # only the rotation landed


async def test_rotation_commits_configured_recovery_key_only_when_none_committed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    duck = _DuckKeyring()
    _, first_recovery = generate_recovery_keypair()
    _, second_recovery = generate_recovery_keypair()
    caplog.set_level(logging.INFO)
    async with _armed(tmp_path / "a", duck) as (_, binding):
        assert (await binding.status())["recovery_committed"] is False  # premise
    async with _armed(tmp_path / "a", duck, recovery_public_key=first_recovery) as (_, binding):
        assert (await binding.status())["recovery_committed"] is False
        assert "none is committed" in caplog.text
        await binding.rotate()
        committed = await binding.status()
    assert committed["recovery_committed"] is True
    assert committed["recovery_kid"] == key_id(SHIP_A, first_recovery, role="recovery")

    ship_b = "did:probos:ship-b"
    async with _armed(tmp_path / "b", duck, recovery_public_key=first_recovery, instance_id="ship-b") as (_, binding):
        assert (await binding.status())["recovery_kid"] == key_id(ship_b, first_recovery, role="recovery")
    caplog.clear()
    async with _armed(tmp_path / "b", duck, recovery_public_key=second_recovery, instance_id="ship-b") as (_, binding):
        assert "differs" in caplog.text
        await binding.rotate()
        kept = await binding.status()
    assert kept["seq"] == 1
    assert kept["recovery_kid"] == key_id(ship_b, first_recovery, role="recovery")


_X_DID = "did:probos:ship-x"
_X_SHIP = "c" * 64
_X_DIGEST = "d" * 64


@dataclass(frozen=True)
class _Key:
    private: Any
    public: str
    kid: str


def _new_key(*, role: str = "key") -> _Key:
    private, public = generate_keypair()
    return _Key(private, public, key_id(_X_DID, public, role=role))  # type: ignore[arg-type]


def _signed(key: _Key, payload: dict[str, Any], *, kid: str | None = None, typ: str = KEY_EVENT_JWS_TYP) -> str:
    return sign_with(
        canonical_bytes(payload), kid=kid or key.kid, typ=typ,
        sign=lambda message: sign_challenge(key.private, message),
    )


def _event(index: int, payload: dict[str, Any], signatures: dict[str, str]) -> KeyEvent:
    return KeyEvent(index=index, payload=payload, signatures=signatures, digest=event_digest(payload))


def _payload(event: str, key: _Key, *, previous: dict[str, Any] | None = None, **fields: Any) -> dict[str, Any]:
    ship = event in (EVENT_INCEPTION, EVENT_REINCEPTION)
    arguments: dict[str, Any] = {
        "did": _X_DID,
        "seq": 0 if previous is None else previous["seq"] + 1,
        "event": event,
        "prior": "" if previous is None else event_digest(previous),
        "kid": key.kid,
        "public_key": key.public,
        "recovery_public_key": "",
        "ship_certificate_hash": _X_SHIP if ship else "",
        "ship_credential_digest": _X_DIGEST if ship else "",
    }
    arguments.update(fields)
    return build_event_payload(**arguments)


def _derive_case(case: str) -> tuple[list[KeyEvent], dict[str, Any], list[KeyEvent], dict[str, Any]]:
    """(events that replay, their kwargs, the same scenario with one fault, its kwargs)."""
    k1, k2, attacker = _new_key(), _new_key(), _new_key()
    recovery = _new_key(role="recovery")
    plain = _payload(EVENT_INCEPTION, k1)
    plain_event = _event(1, plain, {"new": _signed(k1, plain)})
    with_recovery = _payload(EVENT_INCEPTION, k1, recovery_public_key=recovery.public)
    recovery_event = _event(1, with_recovery, {"new": _signed(k1, with_recovery)})
    ship = {"ship_certificate_hash": _X_SHIP, "ship_credential_digest": _X_DIGEST}

    def rotation(signer: _Key = k1, roles: tuple[str, ...] = ("prior", "new"), **fields: Any) -> KeyEvent:
        payload = _payload(EVENT_ROTATION, k2, previous=plain, **fields)
        signatures = {"prior": _signed(signer, payload, kid=k1.kid), "new": _signed(k2, payload)}
        return _event(3, payload, {role: signatures[role] for role in roles})

    def recover(previous: dict[str, Any], signer: _Key = recovery, index: int = 3, **fields: Any) -> KeyEvent:
        fields.setdefault("reason", "lost")
        payload = _payload(EVENT_RECOVERY, k2, previous=previous, recovery_public_key=recovery.public, **fields)
        return _event(index, payload, {
            "recovery": _signed(signer, payload, kid=recovery.kid), "new": _signed(k2, payload),
        })

    def reincept(previous: dict[str, Any]) -> KeyEvent:
        payload = _payload(EVENT_REINCEPTION, k2, previous=previous, reason="lost")
        return _event(3, payload, {"new": _signed(k2, payload)})

    def inception(**fields: Any) -> KeyEvent:
        payload = _payload(EVENT_INCEPTION, k1, **fields)
        return _event(1, payload, {"new": _signed(k1, payload)})

    good: list[KeyEvent] = [plain_event, rotation()]
    if case == "bad_pop":
        return [plain_event], {}, [_event(1, plain, {"new": _signed(attacker, plain, kid=k1.kid)})], {}
    if case == "prior_mismatch":
        return good, {}, [plain_event, rotation(prior="0" * 64)], {}
    if case == "seq_gap":
        return good, {}, [plain_event, rotation(seq=2)], {}
    if case == "kid_not_fingerprint":
        fake = f"{_X_DID}#key-{'0' * 16}"
        payload = _payload(EVENT_INCEPTION, _Key(k1.private, k1.public, fake))
        return [plain_event], {}, [_event(1, payload, {"new": _signed(k1, payload, kid=fake)})], {}
    if case == "rotation_missing_prior_signature":
        return good, {}, [plain_event, rotation(roles=("new",))], {}
    if case == "rotation_wrong_signer":
        return good, {}, [plain_event, rotation(signer=attacker)], {}
    if case == "recovery_without_committed_key":
        return [recovery_event, recover(with_recovery)], {}, [plain_event, recover(plain)], {}
    if case == "recovery_wrong_signer":
        return (
            [recovery_event, recover(with_recovery)], {},
            [recovery_event, recover(with_recovery, signer=attacker)], {},
        )
    if case == "reinception_with_recovery_key":
        return [plain_event, reincept(plain)], {}, [recovery_event, reincept(with_recovery)], {}
    if case == "compromise_index_out_of_range":
        return (
            [recovery_event, recover(with_recovery, index=5, reason="compromised", compromised_after_index=3)], {},
            [recovery_event, recover(with_recovery, index=5, reason="compromised", compromised_after_index=0)], {},
        )
    if case == "did_mismatch":
        return good, {}, [plain_event, rotation(did="did:probos:ship-y")], {}
    if case == "ship_certificate_mismatch":
        return [plain_event], ship, [plain_event], {**ship, "ship_certificate_hash": "e" * 64}
    if case == "unknown_payload_key":
        payload = {**plain, "note": "x"}
        return [plain_event], {}, [_event(1, payload, {"new": _signed(k1, payload)})], {}
    if case == "wrong_typ":
        return [plain_event], {}, [_event(1, plain, {"new": _signed(k1, plain, typ=VC_JWS_TYP)})], {}
    if case == "bool_seq":
        return [inception(seq=0)], {}, [inception(seq=False)], {}
    raise AssertionError(case)


@pytest.mark.parametrize(
    "case",
    [
        "bad_pop", "prior_mismatch", "seq_gap", "kid_not_fingerprint", "rotation_missing_prior_signature",
        "rotation_wrong_signer", "recovery_without_committed_key", "recovery_wrong_signer",
        "reinception_with_recovery_key", "compromise_index_out_of_range", "did_mismatch",
        "ship_certificate_mismatch", "unknown_payload_key", "wrong_typ", "bool_seq",
    ],
)
def test_derive_key_state_rejects(case: str) -> None:
    good, good_kwargs, bad, bad_kwargs = _derive_case(case)
    assert derive_key_state(good, **good_kwargs) is not None  # premise: without the fault the events replay
    with pytest.raises(KeyEventInvalid):
        derive_key_state(bad, **bad_kwargs)


async def test_tampered_key_event_row_makes_binding_invalid_at_start(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    duck = _DuckKeyring()
    data_dir = tmp_path / "ship"
    async with _armed(data_dir, duck) as (_, binding):
        await binding.rotate()
    async with _armed(data_dir, duck) as (_, binding):
        assert (await binding.status())["status"] == "active"  # premise: the untouched rows re-derive
    with contextlib.closing(sqlite3.connect(data_dir / "identity.db")) as db:
        block_index, signatures_json = db.execute(
            "SELECT block_index, signatures_json FROM identity_key_events WHERE seq = 1"
        ).fetchone()
        signatures = json.loads(signatures_json)
        signatures["prior"] = signatures["new"]
        db.execute(
            "UPDATE identity_key_events SET signatures_json = ? WHERE block_index = ?",
            (json.dumps(signatures, sort_keys=True), block_index),
        )
        db.commit()
    caplog.set_level(logging.ERROR)
    async with _armed(data_dir, duck) as (registry, binding):
        status = await binding.status()
        cert = await _birth(registry, "Alpha")
        chain = await registry.export_chain()
    assert status["status"] == "invalid"
    assert "attestation" not in _block_for(chain, cert.certificate_hash)
    assert any(record.levelno == logging.ERROR and "AD-1196" in record.getMessage() for record in caplog.records)


async def test_key_material_never_logged(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    duck = _DuckKeyring()
    recovery_private, recovery_public = generate_recovery_keypair()
    async with _armed(tmp_path / "ship", duck, recovery_public_key=recovery_public) as (registry, binding):
        await _birth(registry, "Alpha")
        await binding.rotate()
        prepared = await binding.prepare_recovery(
            reason="lost", compromised_after_index=None, next_recovery_public_key="",
        )
        authorization = sign_recovery_authorization(recovery_private, prepared["signing_payload"])
        await binding.apply_recovery(
            authorization=authorization, reason="lost", compromised_after_index=None,
            next_recovery_public_key="",
        )
        await _birth(registry, "Bravo")
        status = await binding.status()
        chain = await registry.export_chain()
    plaintext = build_key_store("plaintext_dev", tmp_path)
    dev_kid, dev_public = await plaintext.create("did:probos:dev")
    await plaintext.sign(dev_kid, "message")
    dev_secret = json.loads(next((tmp_path / "identity-keys-dev").glob("*.key")).read_text(encoding="utf-8"))
    private = [*duck.entries.values(), recovery_private, dev_secret["private_key"]]
    public = [recovery_public, dev_public, authorization, prepared["signing_payload"]]
    for record in status["keys"]:
        public += [record["public_key"], b64url_encode(base64.b64decode(record["public_key"]))]
    for block in chain:
        attestation = block.get("attestation") or {}
        public += [attestation["jws"]] if "jws" in attestation else []
        public += list((attestation.get("signatures") or {}).values())
    assert len(private) == 5 and len(public) > 12
    everything = caplog.text
    ours = "\n".join(record.getMessage() for record in caplog.records if record.name.startswith("probos"))
    assert "AD-1196: key event rotation" in ours and "UNENCRYPTED" in ours  # premise: the paths did log
    # Private keys reach no logger at all -- not ours, and not aiosqlite's DEBUG echo of SQL parameters.
    for secret in private:
        assert secret not in everything
    # ProbOS's own messages name key ids only. (aiosqlite's DEBUG echo carries the public rows it writes;
    # ProbOS runs that logger at WARNING, __main__.py.)
    for value in public:
        assert value not in ours


# --------------------------------------------------------------------------- #
# M3 -- remote verification and import_chain
# --------------------------------------------------------------------------- #


async def test_legacy_unsigned_chain_reported_unsigned_and_accepted(tmp_path: Path) -> None:
    async with _registry(tmp_path / "legacy") as registry:
        await _birth(registry, "Alpha")
        await _birth(registry, "Bravo")
        chain = await registry.export_chain()
    report = verify_chain_signatures(chain)
    assert report.ok and report.state is None
    assert (report.key_events, report.valid, report.unsigned) == (0, 0, 2)
    async with _armed(tmp_path / "peer", _DuckKeyring(), instance_id="peer") as (peer, _):
        imported, message = await peer.import_chain(chain)
    assert imported, message


async def test_tampered_certificate_field_fails_signature(tmp_path: Path) -> None:
    origin = await _signed_origin(tmp_path / "origin")
    assert verify_chain_signatures(origin.chain).ok  # premise
    tampered = copy.deepcopy(origin.chain)
    block = origin.block(tampered, "Alpha")
    block["credential"]["credentialSubject"]["callsign"] = "Mallory"
    hashes_ok, _ = await AgentIdentityRegistry(data_dir=tmp_path / "unused").verify_remote_chain(tampered)
    assert hashes_ok  # the hash chain cannot see a credential edit; only the signature can
    report = verify_chain_signatures(tampered)
    assert not report.ok and f"block {block['index']}" in report.reason


async def test_rotated_out_key_signature_after_rotation_is_invalid(tmp_path: Path) -> None:
    origin = await _signed_origin(tmp_path / "origin")
    k1 = origin.kids[0]
    forged = copy.deepcopy(origin.chain)
    block = origin.block(forged, "Bravo")  # anchored after the rotation, under K2
    jws = _vc_jws(origin.private_key(k1), k1, block["credential"], anchor_index=block["index"])
    assert verify_signature_for(  # premise: K1 really signed it
        jws, canonical_bytes(block["credential"]), public_key_b64=origin.public_key(k1), kid=k1, typ=VC_JWS_TYP,
    )
    block["attestation"]["jws"] = jws
    report = verify_chain_signatures(forged)
    assert not report.ok and f"block {block['index']}" in report.reason


async def test_revoked_key_signature_after_revocation_is_rejected(tmp_path: Path) -> None:
    origin = await _signed_origin(tmp_path / "origin")
    k2 = origin.kids[1]
    forged = copy.deepcopy(origin.chain)
    block = origin.block(forged, "Delta")  # anchored after the recovery replaced K2
    jws = _vc_jws(origin.private_key(k2), k2, block["credential"], anchor_index=block["index"])
    assert verify_signature_for(  # premise: K2 really signed it
        jws, canonical_bytes(block["credential"]), public_key_b64=origin.public_key(k2), kid=k2, typ=VC_JWS_TYP,
    )
    block["attestation"]["jws"] = jws
    report = verify_chain_signatures(forged)
    assert not report.ok and f"block {block['index']}" in report.reason
    state = verify_chain_signatures(origin.chain).state
    assert state is not None
    assert signature_verdict(
        state, record_bytes=canonical_bytes(block["credential"]), jws=jws, anchor_index=block["index"], typ=VC_JWS_TYP,
    ) == "invalid"
    async with _armed(tmp_path / "peer", _DuckKeyring(), instance_id="peer") as (peer, _):
        imported, message = await peer.import_chain(forged)
    assert not imported and message.startswith("Signature check failed")


async def test_revoked_key_signature_after_compromise_point_is_void(tmp_path: Path) -> None:
    origin = await _signed_origin(tmp_path / "origin")
    k2 = origin.kids[1]
    report = verify_chain_signatures(origin.chain)
    assert report.ok and report.state is not None
    charlie, bravo = origin.block(origin.chain, "Charlie"), origin.block(origin.chain, "Bravo")
    record = report.state.key(k2)
    assert record is not None and record.compromised_after == origin.compromised_after == bravo["index"]
    # Premise: Charlie is inside K2's window and its signature is genuine; only the compromise point voids it.
    assert key_valid_at(record, charlie["index"])
    assert verify_signature_for(
        charlie["attestation"]["jws"], canonical_bytes(charlie["credential"]),
        public_key_b64=record.public_key, kid=k2, typ=VC_JWS_TYP,
    )
    assert report.void == (charlie["index"],)
    assert signature_verdict(
        report.state, record_bytes=canonical_bytes(bravo["credential"]), jws=bravo["attestation"]["jws"],
        anchor_index=bravo["index"], typ=VC_JWS_TYP,
    ) == "valid"


async def test_wrong_did_key_signature_is_rejected(tmp_path: Path) -> None:
    origin = await _signed_origin(tmp_path / "origin")
    other = _DuckKeyring()
    async with _armed(tmp_path / "other", other, instance_id="ship-b") as (_, binding):
        other_kid = (await binding.status())["active_kid"]
    other_private = decode_private_key(other.secret(other_kid))
    forged = copy.deepcopy(origin.chain)
    block = origin.block(forged, "Alpha")
    jws = _vc_jws(other_private, other_kid, block["credential"], anchor_index=block["index"])
    assert verify_signature_for(  # premise: a genuine signature, by another ship's bound key
        jws, canonical_bytes(block["credential"]),
        public_key_b64=encode_public_key(other_private.public_key()), kid=other_kid, typ=VC_JWS_TYP,
    )
    block["attestation"]["jws"] = jws
    report = verify_chain_signatures(forged)
    assert not report.ok and f"block {block['index']}" in report.reason


async def test_attestation_moved_to_another_block_is_rejected(tmp_path: Path) -> None:
    origin = await _signed_origin(tmp_path / "origin")
    chain = copy.deepcopy(origin.chain)
    source = origin.block(chain, "Delta")
    # A transfer-shaped block for the same agent inside K3's window. The export join gives any later block with an
    # agent DID that agent's BIRTH credential (F-1), so the moved signature still covers the bytes it is shown with.
    # (M4 builds the real transfer anchor; the remote verifier sees only this data.)
    # AD-1196 A-1: the moved signature also names Delta's block, so it now fails its anchor too; MUT-14 (the
    # proof-value check removed) is killed by test_a1_birth_attestation_must_match_its_block_certificate instead.
    moved = _append_block(
        chain, certificate_hash=hashlib.sha256(b"transfer").hexdigest(), agent_did=source["agent_did"],
        credential=copy.deepcopy(source["credential"]), attestation=copy.deepcopy(source["attestation"]),
    )
    hashes_ok, _ = await AgentIdentityRegistry(data_dir=tmp_path / "unused").verify_remote_chain(chain)
    state = verify_chain_signatures(origin.chain).state
    assert hashes_ok and state is not None  # premise: the hash chain and the key state accept the block
    k3 = state.key(origin.kids[2])
    assert k3 is not None and key_valid_at(k3, moved["index"])
    assert verify_signature_for(
        moved["attestation"]["jws"], canonical_bytes(moved["credential"]),
        public_key_b64=k3.public_key, kid=k3.kid, typ=VC_JWS_TYP,
    )
    report = verify_chain_signatures(chain)
    assert not report.ok and f"block {moved['index']}" in report.reason


async def test_key_event_jws_reused_as_certificate_attestation_is_rejected(tmp_path: Path) -> None:
    origin = await _signed_origin(tmp_path / "origin")
    recovery_block = next(
        block for block in origin.chain
        if (block.get("attestation") or {}).get("event", {}).get("event") == EVENT_RECOVERY
    )
    event_jws = recovery_block["attestation"]["signatures"]["new"]  # K3, key-event typ
    k3 = origin.kids[2]
    assert jws_kid(event_jws) == k3

    as_birth = copy.deepcopy(origin.chain)
    origin.block(as_birth, "Delta")["attestation"]["jws"] = event_jws
    assert not verify_chain_signatures(as_birth).ok

    # As a transfer attestation the bytes are checked at transfer import (M4), so only the typ separates them.
    # AD-1196 A-1: a key-event signature also names no anchor_index, so MUT-9 (the typ check removed) is killed
    # by test_jws_round_trip_and_rejections[typ_mismatch] rather than here.
    proper = copy.deepcopy(origin.chain)
    delta = origin.block(proper, "Delta")
    vc_jws = _vc_jws(
        origin.private_key(k3), k3, {"type": ["VerifiableCredential", "TransferCertificate"]},
        anchor_index=proper[-1]["index"] + 1, birth_credential_digest="e" * 64,
    )
    anchor = _append_block(
        proper, certificate_hash="f" * 64, agent_did=delta["agent_did"],
        credential=copy.deepcopy(delta["credential"]), attestation={"kind": "transfer", "jws": vc_jws},
    )
    accepted = verify_chain_signatures(proper)
    assert accepted.ok and accepted.deferred == (anchor["index"],)  # premise: a VC-typed one is accepted
    reused = copy.deepcopy(proper)
    reused[-1]["attestation"]["jws"] = event_jws
    report = verify_chain_signatures(reused)
    assert not report.ok and f"block {anchor['index']}" in report.reason


async def test_attestations_without_key_events_are_rejected(tmp_path: Path) -> None:
    origin = await _signed_origin(tmp_path / "origin")
    stripped = copy.deepcopy(origin.chain)
    for block in stripped:
        if (block.get("attestation") or {}).get("kind") == "key_event":
            del block["attestation"]
    assert any((block.get("attestation") or {}).get("kind") == "agent_birth" for block in stripped)  # premise
    report = verify_chain_signatures(stripped)
    assert not report.ok and "without key events" in report.reason


async def test_attestation_on_genesis_or_of_unknown_kind_is_rejected(tmp_path: Path) -> None:
    origin = await _signed_origin(tmp_path / "origin")
    assert verify_chain_signatures(origin.chain).ok  # premise
    on_genesis = copy.deepcopy(origin.chain)
    on_genesis[0]["attestation"] = copy.deepcopy(origin.block(on_genesis, "Alpha")["attestation"])
    report = verify_chain_signatures(on_genesis)
    assert not report.ok and "genesis" in report.reason
    unknown = copy.deepcopy(origin.chain)
    origin.block(unknown, "Alpha")["attestation"]["kind"] = "ship_birth"
    report = verify_chain_signatures(unknown)
    assert not report.ok and "unknown" in report.reason


async def test_signed_chain_without_genesis_credential_is_rejected(tmp_path: Path) -> None:
    origin = await _signed_origin(tmp_path / "origin")
    assert verify_chain_signatures(origin.chain).ok  # premise
    missing = copy.deepcopy(origin.chain)
    missing[0]["credential"] = None
    report = verify_chain_signatures(missing)
    assert not report.ok and report.reason == "genesis credential missing"


def test_verify_chain_signatures_never_raises_on_malformed_chains() -> None:
    assert verify_chain_signatures([]).reason == "empty chain"
    assert verify_chain_signatures([{}]).reason == "malformed chain (KeyError)"
    for chain in (
        # AD-1196 A-1: each genesis carries index 0, so the index-is-position check passes it and the
        # malformed block behind it is what the verifier meets.
        [{"index": 0, "agent_did": SHIP_A}, "not a block"],
        [{"index": 0, "agent_did": SHIP_A}, {"index": 1, "agent_did": SHIP_A, "attestation": ["key_event"]}],
        [
            {"index": 0, "agent_did": SHIP_A, "credential": {"id": "x"}, "certificate_hash": "c"},
            {
                "index": 1, "agent_did": SHIP_A, "certificate_hash": "x",
                "attestation": {"kind": "key_event", "event": 1, "signatures": 2},
            },
        ],
    ):
        report = verify_chain_signatures(chain)  # type: ignore[arg-type]
        assert report.ok is False and report.state is None


async def test_import_chain_armed_rejects_badly_signed_chain_and_persists_nothing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    origin = await _signed_origin(tmp_path / "origin")
    tampered = copy.deepcopy(origin.chain)
    origin.block(tampered, "Alpha")["credential"]["credentialSubject"]["callsign"] = "Mallory"
    caplog.set_level(logging.WARNING)
    peer_dir = tmp_path / "peer"
    async with _armed(peer_dir, _DuckKeyring(), instance_id="peer") as (peer, _):
        imported, message = await peer.import_chain(tampered)
        stored = peer.get_foreign_chain(SHIP_A)
    assert not imported and message.startswith("Signature check failed")
    assert stored is None and _count_rows(peer_dir / "identity.db", "foreign_chains") == 0
    assert f"AD-1196: import chain from {SHIP_A} rejected" in caplog.text
    async with _armed(tmp_path / "control", _DuckKeyring(), instance_id="control") as (control, _):
        accepted, accepted_message = await control.import_chain(origin.chain)
    assert accepted, accepted_message  # premise: the untampered chain imports on an armed peer


async def test_import_chain_armed_accepts_legacy_chain(tmp_path: Path) -> None:
    async with _registry(tmp_path / "legacy") as registry:
        await _birth(registry, "Alpha")
        chain = await registry.export_chain()
    async with _armed(tmp_path / "peer", _DuckKeyring(), instance_id="peer") as (peer, _):
        imported, message = await peer.import_chain(chain)
        stored = peer.get_foreign_chain(SHIP_A)
    assert imported, message
    assert stored is not None and len(stored) == len(chain)


async def test_import_chain_off_ignores_attestations(tmp_path: Path) -> None:
    origin = await _signed_origin(tmp_path / "origin")
    tampered = copy.deepcopy(origin.chain)
    origin.block(tampered, "Alpha")["credential"]["credentialSubject"]["callsign"] = "Mallory"
    assert not verify_chain_signatures(tampered).ok  # premise: this chain really is badly signed
    async with _registry(tmp_path / "peer", instance_id="peer") as peer:
        imported, message = await peer.import_chain(tampered)
        stored = peer.get_foreign_chain(SHIP_A)
    assert imported, message
    assert stored is not None and stored[1]["attestation"] == tampered[1]["attestation"]


# --------------------------------------------------------------------------- #
# M4 -- transfers
# --------------------------------------------------------------------------- #

_TARGET_DID = "did:probos:ship-b"


def _reordered(xfer: TransferCertificate) -> TransferCertificate:
    """The same transfer with its qualifications reversed: ``compute_hash`` sorts them, the credential does not."""
    data = xfer.to_dict()
    data["qualification_credentials"] = list(reversed(data["qualification_credentials"]))
    return TransferCertificate.from_dict(data)


async def test_armed_transfer_is_anchored_signed_and_accepted_by_armed_target(tmp_path: Path) -> None:
    duck = _DuckKeyring()
    origin_dir = tmp_path / "origin"
    async with _armed(origin_dir, duck) as (registry, binding):
        alpha = await _birth(registry, "Alpha")
        kid = (await binding.status())["active_kid"]
        tip = (await registry.export_chain())[-1]["index"]
        xfer = await registry.issue_transfer_certificate(alpha.agent_uuid, _TARGET_DID, ["bridge", "helm"])
        chain = json.loads(json.dumps(await registry.export_chain()))
    anchor = _block_for(chain, xfer.certificate_hash)
    assert anchor["index"] == tip + 1 and anchor["agent_did"] == alpha.did
    assert anchor["attestation"]["kind"] == "transfer" and jws_kid(anchor["attestation"]["jws"]) == kid
    # The export join shows the anchor with the agent's BIRTH credential (F-1); the signature covers the transfer's.
    assert anchor["credential"]["proof"]["proofValue"] == alpha.certificate_hash
    public_key = encode_public_key(decode_private_key(duck.secret(kid)).public_key())
    for credential, expected in ((xfer.to_verifiable_credential(), True), (anchor["credential"], False)):
        assert verify_signature_for(
            anchor["attestation"]["jws"], canonical_bytes(credential), public_key_b64=public_key, kid=kid,
            typ=VC_JWS_TYP,
        ) is expected
    report = verify_chain_signatures(chain)
    assert report.ok and report.deferred == (anchor["index"],) and report.valid == 1
    assert _count_rows(origin_dir / "identity.db", "transfer_certificates") == 1
    assert _count_rows(origin_dir / "identity.db", "identity_signatures") == 2  # Alpha's birth, then the transfer
    wire = TransferCertificate.from_dict(json.loads(json.dumps(xfer.to_dict())))  # as the federation bridge carries it
    assert wire.to_verifiable_credential() == xfer.to_verifiable_credential()
    async with _armed(tmp_path / "target", _DuckKeyring(), instance_id="ship-b") as (target, _):
        imported, message = await target.import_chain(chain)
        accepted, reason = await target.import_transfer_certificate(wire)
        foreign = target.get_by_uuid(alpha.agent_uuid)
    assert imported, message
    assert accepted, reason
    assert foreign is not None and foreign.did == alpha.did
    assert foreign.certificate_hash == alpha.certificate_hash  # reconstructed from the birth block, not the anchor


async def test_armed_transfer_refused_when_key_unavailable_and_nothing_persisted(tmp_path: Path) -> None:
    duck = _DuckKeyring()
    data_dir = tmp_path / "ship"
    store = _FlakySignStore(KeyringKeyStore(backend=duck))
    async with _armed(data_dir, duck, store=store) as (registry, binding):
        alpha = await _birth(registry, "Alpha")
        bravo = await _birth(registry, "Bravo")
        first = await registry.issue_transfer_certificate(alpha.agent_uuid, _TARGET_DID)
        before = await registry.export_chain()
        store.fail_sign = True
        with pytest.raises(IdentityKeyUnavailable):
            await registry.issue_transfer_certificate(bravo.agent_uuid, _TARGET_DID)
        latched = (await binding.status())["status"]
        with pytest.raises(IdentityKeyUnavailable):  # now refused at the status gate, before any signing
            await registry.issue_transfer_certificate(bravo.agent_uuid, _TARGET_DID)
        after = await registry.export_chain()
    assert "attestation" in _block_for(before, first.certificate_hash)  # premise: an active key anchors a transfer
    assert latched == "key_unavailable"
    assert after == before
    assert _count_rows(data_dir / "identity.db", "transfer_certificates") == 1
    assert _count_rows(data_dir / "identity.db", "identity_signatures") == 3  # two births and the first transfer

    unbound_dir = tmp_path / "unbound"
    async with _armed(unbound_dir, _DuckKeyring(priority=0.5)) as (registry, binding):
        assert (await binding.status())["status"] == "unbound"  # premise: no secure store, so no key
        charlie = await _birth(registry, "Charlie")
        blocks = len(await registry.export_chain())
        with pytest.raises(IdentityKeyUnavailable):
            await registry.issue_transfer_certificate(charlie.agent_uuid, _TARGET_DID)
        assert len(await registry.export_chain()) == blocks
    assert _count_rows(unbound_dir / "identity.db", "transfer_certificates") == 0


async def test_armed_target_rejects_unanchored_transfer_from_armed_origin(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    duck = _DuckKeyring()
    origin_dir = tmp_path / "origin"
    async with _armed(origin_dir, duck) as (registry, _):
        alpha = await _birth(registry, "Alpha")
        bravo = await _birth(registry, "Bravo")
        anchored = await registry.issue_transfer_certificate(alpha.agent_uuid, _TARGET_DID)
    async with _registry(origin_dir) as legacy:  # the same ship's unarmed path anchors nothing
        unanchored = await legacy.issue_transfer_certificate(bravo.agent_uuid, _TARGET_DID)
    async with _armed(origin_dir, duck) as (registry, binding):
        assert (await binding.status())["status"] == "active"
        chain = json.loads(json.dumps(await registry.export_chain()))
    assert verify_chain_signatures(chain).key_events == 1  # premise: the origin is bound
    assert all(block["certificate_hash"] != unanchored.certificate_hash for block in chain)
    async with _registry(tmp_path / "legacy-target", instance_id="ship-c") as legacy_target:
        assert (await legacy_target.import_chain(chain))[0]
        legacy_accepted, _ = await legacy_target.import_transfer_certificate(unanchored)
    assert legacy_accepted  # premise: the subject is in the origin chain; only the signature layer refuses it
    caplog.set_level(logging.WARNING)
    async with _armed(tmp_path / "target", _DuckKeyring(), instance_id="ship-b") as (target, _):
        assert (await target.import_chain(chain))[0]
        good, good_reason = await target.import_transfer_certificate(anchored)
        bad, bad_reason = await target.import_transfer_certificate(unanchored)
        stored = target.get_by_uuid(bravo.agent_uuid)
    assert good, good_reason  # premise: an anchored transfer from the same chain is accepted
    assert not bad and bad_reason == "transfer certificate is not anchored on the origin's ledger"
    assert stored is None
    assert f"AD-1196: transfer certificate {bravo.did} rejected" in caplog.text


async def test_armed_target_rejects_tampered_transfer(tmp_path: Path) -> None:
    async with _armed(tmp_path / "origin", _DuckKeyring()) as (registry, _):
        alpha = await _birth(registry, "Alpha")
        xfer = await registry.issue_transfer_certificate(alpha.agent_uuid, _TARGET_DID, ["bridge", "helm"])
        chain = json.loads(json.dumps(await registry.export_chain()))
    tampered = _reordered(xfer)
    # Premise: the content hash cannot see the edit (it sorts the list), so only the signature can.
    assert tampered.compute_hash() == tampered.certificate_hash == xfer.certificate_hash
    assert canonical_bytes(tampered.to_verifiable_credential()) != canonical_bytes(xfer.to_verifiable_credential())
    async with _armed(tmp_path / "target", _DuckKeyring(), instance_id="ship-b") as (target, _):
        assert (await target.import_chain(chain))[0]
        rejected, reason = await target.import_transfer_certificate(tampered)
        accepted, accepted_reason = await target.import_transfer_certificate(xfer)
    assert not rejected and "does not verify" in reason
    assert accepted, accepted_reason


async def test_armed_target_rejects_transfer_signed_after_compromise_point(tmp_path: Path) -> None:
    duck = _DuckKeyring()
    recovery_private, recovery_public = generate_recovery_keypair()
    async with _armed(tmp_path / "origin", duck, recovery_public_key=recovery_public) as (registry, binding):
        k1 = (await binding.status())["active_kid"]
        alpha = await _birth(registry, "Alpha")
        compromised_after = _block_for(await registry.export_chain(), alpha.certificate_hash)["index"]
        xfer = await registry.issue_transfer_certificate(alpha.agent_uuid, _TARGET_DID)  # by K1, after that point
        before = json.loads(json.dumps(await registry.export_chain()))
        prepared = await binding.prepare_recovery(
            reason="compromised", compromised_after_index=compromised_after, next_recovery_public_key="",
        )
        await binding.apply_recovery(
            authorization=sign_recovery_authorization(recovery_private, prepared["signing_payload"]),
            reason="compromised", compromised_after_index=compromised_after, next_recovery_public_key="",
        )
        after = json.loads(json.dumps(await registry.export_chain()))
    anchor = _block_for(after, xfer.certificate_hash)
    assert anchor["index"] > compromised_after and jws_kid(anchor["attestation"]["jws"]) == k1
    state = verify_chain_signatures(after).state
    assert state is not None
    record = state.key(k1)
    assert record is not None and record.compromised_after == compromised_after
    # Premise: the signature is genuine and inside K1's window; only the declared compromise point voids it.
    assert key_valid_at(record, anchor["index"])
    assert verify_signature_for(
        anchor["attestation"]["jws"], canonical_bytes(xfer.to_verifiable_credential()),
        public_key_b64=record.public_key, kid=k1, typ=VC_JWS_TYP,
    )
    async with _armed(tmp_path / "early", _DuckKeyring(), instance_id="ship-b") as (early, _):
        assert (await early.import_chain(before))[0]
        early_accepted, early_reason = await early.import_transfer_certificate(xfer)
    assert early_accepted, early_reason  # premise: valid until the compromise was declared
    async with _armed(tmp_path / "late", _DuckKeyring(), instance_id="ship-b") as (late, _):
        imported, message = await late.import_chain(after)
        accepted, reason = await late.import_transfer_certificate(xfer)
    assert imported, message  # a void signature is reported on the chain, not a rejected chain
    assert not accepted and "compromise point" in reason


async def test_armed_target_accepts_legacy_origin_transfer_as_unsigned(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    async with _registry(tmp_path / "origin") as origin:
        alpha = await _birth(origin, "Alpha")
        xfer = await origin.issue_transfer_certificate(alpha.agent_uuid, _TARGET_DID)
        chain = json.loads(json.dumps(await origin.export_chain()))
    assert len(chain) == 2 and all(set(block) == LEGACY_BLOCK_KEYS for block in chain)  # premise: nothing anchored
    caplog.set_level(logging.INFO)
    async with _armed(tmp_path / "target", _DuckKeyring(), instance_id="ship-b") as (target, _):
        assert (await target.import_chain(chain))[0]
        accepted, reason = await target.import_transfer_certificate(
            TransferCertificate.from_dict(json.loads(json.dumps(xfer.to_dict()))),
        )
        stored = target.get_by_uuid(alpha.agent_uuid)
    assert accepted, reason
    assert stored is not None and stored.did == alpha.did
    assert f"AD-1196: transfer certificate {alpha.did} accepted: origin has no bound key" in caplog.text


async def test_unarmed_target_accepts_signed_origin_transfer_unchanged(tmp_path: Path) -> None:
    async with _armed(tmp_path / "origin", _DuckKeyring()) as (registry, _):
        alpha = await _birth(registry, "Alpha")
        xfer = await registry.issue_transfer_certificate(alpha.agent_uuid, _TARGET_DID, ["bridge", "helm"])
        chain = json.loads(json.dumps(await registry.export_chain()))
    tampered = _reordered(xfer)
    async with _armed(tmp_path / "armed", _DuckKeyring(), instance_id="ship-b") as (armed, _):
        assert (await armed.import_chain(chain))[0]
        assert not (await armed.import_transfer_certificate(tampered))[0]  # premise: the armed path refuses it
    target_dir = tmp_path / "target"
    async with _registry(target_dir, instance_id="ship-b") as target:
        imported, message = await target.import_chain(chain)
        accepted, reason = await target.import_transfer_certificate(xfer)
        tampered_accepted, _ = await target.import_transfer_certificate(tampered)
        stored = target.get_foreign_chain(SHIP_A)
    assert imported, message
    assert accepted, reason
    assert tampered_accepted  # unchanged: the unarmed path has no signature layer
    assert stored == chain  # attestations persisted verbatim and ignored
    assert _table_names(target_dir / "identity.db") == IDENTITY_TABLES


# --------------------------------------------------------------------------- #
# M5 -- config, boot wiring, store declaration
# --------------------------------------------------------------------------- #


class _KeyringProbe:
    """Stands in for ``keyring.get_keyring``: counts calls; returns a duck, or refuses when it has none."""

    def __init__(self, backend: Any | None = None) -> None:
        self.backend = backend
        self.calls = 0

    def __call__(self) -> Any:
        self.calls += 1
        if self.backend is None:
            raise RuntimeError("AD-1196 tests must never reach the real OS keyring")
        return self.backend


class _Started:
    """An infrastructure service double: ``start()`` only."""

    async def start(self) -> None:
        return None


async def _boot_identity(data_dir: Path, config: Any) -> Any:
    """Run the real infrastructure boot phase with inert service doubles."""
    from probos.startup.infrastructure import boot_infrastructure

    async def _prune_loop() -> None:
        await asyncio.Event().wait()

    return await boot_infrastructure(
        event_log=_Started(), hebbian_router=_Started(), signal_manager=_Started(),  # type: ignore[arg-type]
        gossip=_Started(), trust_network=_Started(), data_dir=data_dir, config=config,  # type: ignore[arg-type]
        event_log_prune_loop_fn=_prune_loop,  # type: ignore[arg-type]
    )


async def _stop_identity(result: Any) -> None:
    result.event_prune_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await result.event_prune_task
    await result.identity_registry.stop()


def test_identity_key_config_defaults_off() -> None:
    from probos.config import FederationConfig, SystemConfig
    from probos.identity_key_binding import build_identity_key_binding

    federation = FederationConfig()
    assert federation.identity_keys_enabled is False
    assert federation.identity_key_store == "keyring"
    assert federation.identity_recovery_public_key == ""
    assert SystemConfig().federation.identity_keys_enabled is False
    assert build_identity_key_binding(federation, Path("unused")) is None


def test_identity_recovery_public_key_validation() -> None:
    from pydantic import ValidationError

    from probos.config import FederationConfig

    _, public_key = generate_keypair()
    assert FederationConfig(identity_recovery_public_key="").identity_recovery_public_key == ""
    assert FederationConfig(identity_recovery_public_key=public_key).identity_recovery_public_key == public_key
    for bad in ("not base64!", base64.b64encode(b"k" * 31).decode(), base64.b64encode(b"k" * 33).decode()):
        with pytest.raises(ValidationError):
            FederationConfig(identity_recovery_public_key=bad)


def test_identity_key_store_rejects_unknown_kind(tmp_path: Path) -> None:
    from pydantic import ValidationError

    from probos.config import FederationConfig
    from probos.identity_key_binding import build_identity_key_binding

    with pytest.raises(ValidationError):
        FederationConfig(identity_key_store="vault")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        build_key_store("vault", tmp_path)
    smuggled = FederationConfig.model_construct(identity_keys_enabled=True, identity_key_store="vault")
    with pytest.raises(ValueError):
        build_identity_key_binding(smuggled, tmp_path)
    # Premise: the two known kinds build, and only the explicit dev kind is the plaintext store.
    assert isinstance(build_key_store("keyring", tmp_path), KeyringKeyStore)
    assert isinstance(build_key_store("plaintext_dev", tmp_path), PlaintextDevKeyStore)
    armed = FederationConfig(identity_keys_enabled=True)
    assert isinstance(build_identity_key_binding(armed, tmp_path), IdentityKeyBinding)


async def test_boot_off_never_touches_keyring_and_keeps_identity_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from probos.config import SystemConfig

    probe = _KeyringProbe()
    monkeypatch.setattr(keyring, "get_keyring", probe)
    data_dir = tmp_path / "data"
    config = SystemConfig()
    assert config.federation.identity_keys_enabled is False  # premise: the shipped default
    result = await _boot_identity(data_dir, config)
    try:
        await result.identity_registry.start(instance_id="ship-a", vessel_name="Ship-A", version="1")
        cert = await _birth(result.identity_registry, "Alpha")
        chain = await result.identity_registry.export_chain()
    finally:
        await _stop_identity(result)
    assert result.identity_key_binding is None
    assert probe.calls == 0
    assert _block_for(chain, cert.certificate_hash)["agent_did"] == cert.did
    assert all(set(block) == LEGACY_BLOCK_KEYS for block in chain)
    assert _table_names(data_dir / "identity.db") == IDENTITY_TABLES
    assert not list(data_dir.rglob("*.key"))


async def test_boot_armed_wires_binding_into_registry_and_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from probos.config import FederationConfig, SystemConfig

    probe = _KeyringProbe(_DuckKeyring())
    monkeypatch.setattr(keyring, "get_keyring", probe)
    _, recovery_public = generate_recovery_keypair()
    data_dir = tmp_path / "data"
    config = SystemConfig(federation=FederationConfig(
        identity_keys_enabled=True, identity_recovery_public_key=recovery_public,
    ))
    result = await _boot_identity(data_dir, config)
    try:
        binding = result.identity_key_binding
        assert isinstance(binding, IdentityKeyBinding) and binding.key_status == "unbound"
        assert {"identity_key_events", "identity_signatures"} <= set(_table_names(data_dir / "identity.db"))
        assert probe.calls == 0  # not commissioned yet, so no key was needed
        await result.identity_registry.start(instance_id="ship-a", vessel_name="Ship-A", version="1")
        status = await binding.status()
        cert = await _birth(result.identity_registry, "Alpha")
        chain = await result.identity_registry.export_chain()
    finally:
        await _stop_identity(result)
    assert status["status"] == "active" and status["did"] == SHIP_A and status["recovery_committed"] is True
    assert probe.calls > 0 and probe.backend.entries
    assert _block_for(chain, cert.certificate_hash)["attestation"]["kind"] == "agent_birth"
    assert verify_chain_signatures(chain).valid == 1


async def test_runtime_boot_armed_binds_ship_key_and_serves_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from httpx import ASGITransport, AsyncClient

    from probos.api import create_app
    from probos.cognitive.llm_client import MockLLMClient
    from probos.config import FederationConfig, SystemConfig
    from probos.runtime import ProbOSRuntime

    duck = _DuckKeyring()
    monkeypatch.setattr(keyring, "get_keyring", _KeyringProbe(duck))
    config = SystemConfig(federation=FederationConfig(identity_keys_enabled=True))
    runtime = ProbOSRuntime(config=config, data_dir=tmp_path / "data", llm_client=MockLLMClient())
    await runtime.start()
    try:
        binding = runtime.identity_key_binding
        registry = runtime.identity_registry
        assert binding is not None and registry is not None
        assert binding.key_status == "active"  # commissioned during boot, so bound
        ship = registry.get_ship_certificate()
        assert ship is not None
        cert = await _birth(registry, "Alpha", instance_id=ship.instance_id)
        chain = json.loads(json.dumps(await registry.export_chain()))
        async with AsyncClient(transport=ASGITransport(app=create_app(runtime)), base_url="http://test") as client:
            response = await client.get("/api/identity/keys")
    finally:
        await runtime.stop()
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "active" and body["did"] == ship.ship_did == chain[0]["agent_did"]
    assert body["did_document"]["assertionMethod"] == [body["active_kid"]]
    assert _block_for(chain, cert.certificate_hash)["attestation"]["kind"] == "agent_birth"
    report = verify_chain_signatures(chain)
    assert report.ok and report.key_events == 1 and report.valid >= 1
    assert all(secret not in response.text for secret in duck.entries.values())


async def test_identity_key_store_declaration_matches_companion_lifecycle(tmp_path: Path) -> None:
    import importlib

    from probos.storage.declarations import declaration_errors
    from probos.storage.registry import load_default_store_registry

    registry = load_default_store_registry()
    declaration = registry.get("identity.key-binding")
    assert declaration is not None
    assert declaration.to_dict() == {
        "id": "identity.key-binding",
        "title": "Ship DID key events and certificate signatures (AD-1196)",
        "owner_module": "probos.identity_key_binding",
        "owner_symbol": "IdentityKeyBinding",
        "canonical_path": "identity.db",
        "criticality": "feature-gated",
        "lifecycle_owner": "probos.identity.AgentIdentityRegistry",
        "retention": "unbounded",
        "retention_note": (
            "Append-only: one row per key event and per signed certificate, never deleted. "
            "Growth is bounded by births, transfers and the Captain's key actions."
        ),
        "backup": "included",
        "restore": "unknown",
        "reconstruction": "",
        "notes": (
            "Companion tables co-located with the AD-441 identity ledger in identity.db, sharing "
            "AgentIdentityRegistry's connection and ledger lock; created only when "
            "federation.identity_keys_enabled. Public keys, key events and signatures only: private "
            "keys never enter this database (OS keyring, or the explicit plaintext_dev directory)."
        ),
    }
    assert declaration_errors(declaration) == ()
    assert registry.by_canonical_path("identity.db") is declaration
    owner = importlib.import_module(declaration.owner_module)
    assert getattr(owner, declaration.owner_symbol) is IdentityKeyBinding
    companion = {"identity_key_events", "identity_signatures"}
    async with _registry(tmp_path / "off"):
        pass
    assert not companion & set(_table_names(tmp_path / "off" / declaration.canonical_path))
    async with _armed(tmp_path / "on", _DuckKeyring()):
        pass
    assert set(_table_names(tmp_path / "on" / declaration.canonical_path)) == set(IDENTITY_TABLES) | companion


# --------------------------------------------------------------------------- #
# Branch coverage for the M1-M3 code, beyond the contract's named tests
# --------------------------------------------------------------------------- #


def _malformed_case(case: str) -> tuple[list[KeyEvent], list[KeyEvent], dict[str, Any]]:
    """(a scenario that replays, the same scenario with one malformed event, derive kwargs)."""
    k1, k2 = _new_key(), _new_key()
    recovery, other_recovery = _new_key(role="recovery"), _new_key(role="recovery")
    base = _payload(EVENT_INCEPTION, k1, recovery_public_key=recovery.public)
    base_event = _event(1, base, {"new": _signed(k1, base)})

    def follow(event: str, key: _Key = k2, index: int = 3, **fields: Any) -> KeyEvent:
        payload = _payload(event, key, previous=base, **fields)
        signers = {
            EVENT_ROTATION: {"prior": k1, "new": key},
            EVENT_RECOVERY: {"recovery": recovery, "new": key},
        }.get(event, {"new": key})
        return _event(index, payload, {role: _signed(signer, payload) for role, signer in signers.items()})

    def incept(edit: dict[str, Any], *, index: int = 1) -> KeyEvent:
        payload = {**base, **edit}
        return _event(index, payload, {"new": _signed(k1, payload)})

    good = [base_event, follow(EVENT_ROTATION, recovery_public_key=recovery.public)]
    bad: list[KeyEvent]
    kwargs: dict[str, Any] = {}
    if case == "wrong_version":
        bad = [incept({"v": 2})]
    elif case == "non_string_member":
        bad = [incept({"reason": None})]
    elif case == "unknown_event":
        bad = [incept({"event": "merger"})]
    elif case == "non_integer_compromise_point":
        bad = [incept({"compromised_after_index": "3"})]
    elif case == "first_event_not_inception":
        bad = [incept({"event": EVENT_ROTATION})]
    elif case == "inception_with_prior":
        bad = [incept({"prior": "0" * 64})]
    elif case == "second_inception":
        again = {**base, "seq": 1, "prior": event_digest(base)}
        bad = [base_event, _event(3, again, {"new": _signed(k1, again)})]
    elif case == "key_shape":
        bad = [incept({"key": {**base["key"], "extra": "x"}})]
    elif case == "undecodable_public_key":
        short = base64.b64encode(b"k" * 31).decode()
        bad = [incept({"key": {"kid": key_id(_X_DID, short), "public_key": short}})]
    elif case == "reason_not_allowed":
        bad = [incept({"reason": "lost"})]
    elif case == "compromise_point_with_lost":
        bad = [base_event, follow(EVENT_RECOVERY, recovery_public_key=recovery.public, reason="lost",
                                  compromised_after_index=1)]
    elif case == "compromised_without_point":
        bad = [base_event, follow(EVENT_RECOVERY, recovery_public_key=recovery.public, reason="compromised")]
    elif case == "inception_without_ship_commitment":
        bad = [incept({"ship_certificate_hash": ""})]
    elif case == "ship_credential_mismatch":
        bad, kwargs = [base_event], {"ship_certificate_hash": _X_SHIP, "ship_credential_digest": "e" * 64}
    elif case == "rotation_commits_ship":
        bad = [base_event, follow(EVENT_ROTATION, recovery_public_key=recovery.public,
                                  ship_certificate_hash=_X_SHIP, ship_credential_digest=_X_DIGEST)]
    elif case == "non_increasing_index":
        bad = [base_event, follow(EVENT_ROTATION, index=1, recovery_public_key=recovery.public)]
    elif case == "non_canonical_payload":
        payload = {**base, "did": "did:probos:\ud800"}
        bad = [KeyEvent(index=1, payload=payload, signatures={"new": "x"}, digest="0" * 64)]
    elif case == "digest_mismatch":
        bad = [KeyEvent(index=1, payload=base, signatures=base_event.signatures, digest="0" * 64)]
    elif case == "key_reuse":
        bad = [base_event, follow(EVENT_ROTATION, key=k1, recovery_public_key=recovery.public)]
    elif case == "rotation_changes_committed_recovery_key":
        bad = [base_event, follow(EVENT_ROTATION, recovery_public_key=other_recovery.public)]
    elif case == "recovery_removes_recovery_key":
        bad = [base_event, follow(EVENT_RECOVERY, reason="lost")]
    else:
        raise AssertionError(case)
    return good, bad, kwargs


@pytest.mark.parametrize(
    "case",
    [
        "wrong_version", "non_string_member", "unknown_event", "non_integer_compromise_point",
        "first_event_not_inception", "inception_with_prior", "second_inception", "key_shape",
        "undecodable_public_key", "reason_not_allowed", "compromise_point_with_lost", "compromised_without_point",
        "inception_without_ship_commitment", "ship_credential_mismatch", "rotation_commits_ship",
        "non_increasing_index", "non_canonical_payload", "digest_mismatch", "key_reuse",
        "rotation_changes_committed_recovery_key", "recovery_removes_recovery_key",
    ],
)
def test_derive_key_state_rejects_malformed_events(case: str) -> None:
    good, bad, kwargs = _malformed_case(case)
    assert derive_key_state(good) is not None  # premise: the unmodified scenario replays
    with pytest.raises(KeyEventInvalid):
        derive_key_state(bad, **kwargs)


def test_jws_helpers_never_raise_on_malformed_tokens() -> None:
    private_key, public_key = generate_keypair()
    numeric_kid = _raw_jws(private_key, {**_JWS_HEADER, "kid": 7})
    assert jws_kid(_raw_jws(private_key, _JWS_HEADER)) == _JWS_HEADER["kid"]  # premise
    for token in (None, 7, "!!!..abc", "a.b", numeric_kid):
        assert jws_kid(token) is None
    for token in (None, "!!!..abc", numeric_kid):
        assert verify_signature_for(token, _JWS_PAYLOAD, public_key_b64=public_key, kid="k", typ="t") is False
    with pytest.raises(ValueError):
        key_id(SHIP_A, "not base64!")


async def test_verify_chain_signatures_rejects_misanchored_attestations(tmp_path: Path) -> None:
    origin = await _signed_origin(tmp_path / "origin")
    assert verify_chain_signatures(origin.chain).ok  # premise
    key_event_index = next(
        index for index, block in enumerate(origin.chain)
        if (block.get("attestation") or {}).get("kind") == "key_event"
    )

    def mutated(edit: Any) -> str:
        chain = copy.deepcopy(origin.chain)
        edit(chain)
        report = verify_chain_signatures(chain)
        assert not report.ok
        return report.reason

    alpha_did = origin.certs["Alpha"].did
    assert "another DID" in mutated(lambda chain: chain[key_event_index].update(agent_did=alpha_did))

    def rename_ship(chain: list[dict[str, Any]]) -> None:
        for block in chain:
            if block is chain[0] or (block.get("attestation") or {}).get("kind") == "key_event":
                block["agent_did"] = "did:probos:impostor"

    assert "another DID than the chain's ship" in mutated(rename_ship)
    assert "no credential" in mutated(lambda chain: origin.block(chain, "Alpha").update(credential=None))
    assert "another subject" in mutated(
        lambda chain: origin.block(chain, "Alpha")["credential"]["credentialSubject"].update(id="did:probos:x:y")
    )
    for jws in (12345, "!!!..abc"):
        def bad_transfer(chain: list[dict[str, Any]], token: Any = jws) -> None:
            delta = origin.block(chain, "Delta")
            _append_block(
                chain, certificate_hash="f" * 64, agent_did=delta["agent_did"],
                credential=copy.deepcopy(delta["credential"]), attestation={"kind": "transfer", "jws": token},
            )

        assert "transfer attestation" in mutated(bad_transfer)


async def test_prepare_recovery_is_idempotent_and_validates_its_inputs(tmp_path: Path) -> None:
    duck = _DuckKeyring()
    _, recovery_public = generate_recovery_keypair()
    counting = _CountingStore(KeyringKeyStore(backend=duck))
    async with _armed(tmp_path / "ship", duck, recovery_public_key=recovery_public, store=counting) as (
        registry, binding,
    ):
        await _birth(registry, "Alpha")
        tip = (await registry.export_chain())[-1]["index"]
        activated = (await binding.status())["keys"][0]["activated_at"]
        first = await binding.prepare_recovery(reason="lost", compromised_after_index=None, next_recovery_public_key="")
        again = await binding.prepare_recovery(reason="lost", compromised_after_index=None, next_recovery_public_key="")
        assert again["kid"] == first["kid"] and again["signing_payload"] == first["signing_payload"]
        assert counting.creates == 2  # inception, then one replacement key for both identical prepares
        changed = await binding.prepare_recovery(
            reason="compromised", compromised_after_index=tip, next_recovery_public_key="",
        )
        assert changed["kid"] != first["kid"] and counting.creates == 3
        for arguments in (
            {"reason": "stolen", "compromised_after_index": None, "next_recovery_public_key": ""},
            {"reason": "lost", "compromised_after_index": 1, "next_recovery_public_key": ""},
            {"reason": "compromised", "compromised_after_index": None, "next_recovery_public_key": ""},
            {"reason": "compromised", "compromised_after_index": activated - 1, "next_recovery_public_key": ""},
            {"reason": "compromised", "compromised_after_index": tip + 1, "next_recovery_public_key": ""},
            {"reason": "lost", "compromised_after_index": None, "next_recovery_public_key": "AAAA"},
        ):
            with pytest.raises(ValueError):
                await binding.prepare_recovery(**arguments)
        assert counting.creates == 3 and (await binding.status())["pending_recovery"] is True


async def test_binding_refuses_key_actions_without_a_usable_state(tmp_path: Path) -> None:
    detached = IdentityKeyBinding(KeyringKeyStore(backend=_DuckKeyring()))
    with pytest.raises(IdentityKeyStateError):
        await detached.rotate()
    blocks: list[dict[str, Any]] = [{"index": 0}]
    await detached.annotate_export(blocks)  # not attached: exports stay exactly as they were
    assert blocks == [{"index": 0}]
    async with _armed(tmp_path / "unbound", _DuckKeyring(priority=0.5)) as (_, binding):
        assert (await binding.status())["status"] == "unbound"  # premise: no secure store, no key state
        with pytest.raises(IdentityKeyStateError):
            await binding.reincept(reason="lost", compromised_after_index=None)
        with pytest.raises(IdentityKeyStateError):
            await binding.prepare_recovery(reason="lost", compromised_after_index=None, next_recovery_public_key="")
        with pytest.raises(IdentityKeyStateError):
            await binding.apply_recovery(
                authorization="x", reason="lost", compromised_after_index=None, next_recovery_public_key="",
            )


async def test_recovery_raced_by_a_rotation_is_refused(tmp_path: Path) -> None:
    duck = _DuckKeyring()
    recovery_private, recovery_public = generate_recovery_keypair()
    async with _armed(tmp_path / "ship", duck, recovery_public_key=recovery_public) as (_, binding):
        before = await binding.status()
        prepared = await binding.prepare_recovery(
            reason="lost", compromised_after_index=None, next_recovery_public_key="",
        )
        authorization = sign_recovery_authorization(recovery_private, prepared["signing_payload"])
        # The rotation holds the ledger lock while its key is created; the recovery verifies its
        # authorization against the old head, then waits for that lock and finds the head moved.
        rotation, recovery = await asyncio.gather(
            binding.rotate(),
            binding.apply_recovery(
                authorization=authorization, reason="lost", compromised_after_index=None,
                next_recovery_public_key="",
            ),
            return_exceptions=True,
        )
        after = await binding.status()
    assert isinstance(rotation, dict) and rotation["kid"] == after["active_kid"]  # premise: it landed
    assert isinstance(recovery, IdentityKeyStateError)
    assert after["seq"] == before["seq"] + 1


async def test_restart_refuses_a_binding_whose_ship_record_changed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    duck = _DuckKeyring()
    _, recovery_public = generate_recovery_keypair()
    for name, recovery in (("with-recovery", recovery_public), ("without-recovery", "")):
        async with _armed(tmp_path / name, duck, recovery_public_key=recovery) as (_, binding):
            assert (await binding.status())["status"] == "active"  # premise
        with contextlib.closing(sqlite3.connect(tmp_path / name / "identity.db")) as db:
            db.execute("UPDATE ship_birth_certificate SET version = 'forged'")
            db.commit()
    caplog.set_level(logging.ERROR)
    async with _armed(tmp_path / "with-recovery", duck, recovery_public_key=recovery_public) as (registry, binding):
        status = await binding.status()
        with pytest.raises(IdentityKeyStateError):
            await binding.prepare_recovery(reason="lost", compromised_after_index=None, next_recovery_public_key="")
        cert = await _birth(registry, "Alpha")
        chain = await registry.export_chain()
    assert status["status"] == "invalid" and "do not belong to this ship" in status["reason"]
    assert "attestation" not in _block_for(chain, cert.certificate_hash)
    assert "do not belong to ship" in caplog.text
    async with _armed(tmp_path / "without-recovery", duck) as (_, binding):
        assert (await binding.status())["status"] == "invalid"
        with pytest.raises(IdentityKeyStateError):
            await binding.reincept(reason="lost", compromised_after_index=None)


async def test_restart_with_an_unavailable_store_reports_key_unavailable(tmp_path: Path) -> None:
    duck = _DuckKeyring()
    async with _armed(tmp_path / "ship", duck) as (_, binding):
        assert (await binding.status())["status"] == "active"  # premise
    insecure = _DuckKeyring(priority=0.5)
    insecure.entries = dict(duck.entries)  # the key is there, but only on a backend that may not be used
    async with _armed(tmp_path / "ship", insecure) as (registry, binding):
        status = await binding.status()
        cert = await _birth(registry, "Alpha")
        chain = await registry.export_chain()
    assert status["status"] == "key_unavailable" and "priority 0.5" in status["reason"]
    assert insecure.gets == 0
    assert "attestation" not in _block_for(chain, cert.certificate_hash)


async def test_inception_store_failure_leaves_the_ship_unbound(tmp_path: Path) -> None:
    class _Dropping(_DuckKeyring):
        def set_password(self, service: str, username: str, password: str) -> None:
            return None

    data_dir = tmp_path / "ship"
    async with _armed(data_dir, _Dropping()) as (registry, binding):
        status = await binding.status()
        await _birth(registry, "Alpha")
    assert status["status"] == "unbound" and "did not persist" in status["reason"]
    assert status["store"]["available"] is True  # premise: the backend resolves; the write is what failed
    assert _count_rows(data_dir / "identity.db", "identity_key_events") == 0


async def test_malformed_store_signature_is_unavailable_not_a_crash(tmp_path: Path) -> None:
    class _Garbage(_CountingStore):
        async def sign(self, kid: str, message: str) -> str:
            return "not base64!"

    duck = _DuckKeyring()
    async with _armed(tmp_path / "ship", duck) as (_, binding):
        assert (await binding.status())["status"] == "active"  # premise
    async with _armed(tmp_path / "ship", duck, store=_Garbage(KeyringKeyStore(backend=duck))) as (registry, binding):
        assert (await binding.status())["status"] == "active"
        cert = await _birth(registry, "Alpha")
        status = await binding.status()
        chain = await registry.export_chain()
    assert status["status"] == "key_unavailable" and "malformed signature" in status["reason"]
    assert "attestation" not in _block_for(chain, cert.certificate_hash)


async def test_key_event_row_detached_from_its_ledger_block_makes_binding_invalid(tmp_path: Path) -> None:
    duck = _DuckKeyring()
    data_dir = tmp_path / "ship"
    async with _armed(data_dir, duck) as (_, binding):
        assert (await binding.status())["status"] == "active"  # premise
    with contextlib.closing(sqlite3.connect(data_dir / "identity.db")) as db:
        db.execute("UPDATE identity_ledger SET certificate_hash = 'detached' WHERE block_index = 1")
        db.commit()
    async with _armed(data_dir, duck) as (_, binding):
        status = await binding.status()
    assert status["status"] == "invalid" and "ledger block" in status["reason"]


async def test_key_stores_fail_closed_on_file_and_cache_misses(tmp_path: Path) -> None:
    duck = _DuckKeyring()
    kid, public_key = await KeyringKeyStore(backend=duck).create(SHIP_A)
    cold = KeyringKeyStore(backend=duck)
    # Premise: there is no cache (AD-1196 A-1); every call reads the store.
    assert verify_signature(public_key, "m", await cold.sign(kid, "m"))
    with pytest.raises(KeyStoreUnavailable, match="no private key"):
        await cold.sign(f"{SHIP_A}#key-0000000000000000", "m")
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("x", encoding="utf-8")
    with pytest.raises(KeyStoreUnavailable, match="could not be written"):
        await PlaintextDevKeyStore(blocked).create(SHIP_A)
    directory = tmp_path / "dev"
    store = PlaintextDevKeyStore(directory)
    dev_kid, _ = await store.create(SHIP_A)
    with pytest.raises(KeyStoreUnavailable, match="no private key"):
        await store.sign(f"{SHIP_A}#key-0000000000000000", "m")
    key_file = next(directory.glob("*.key"))
    key_file.unlink()
    key_file.mkdir()  # the entry exists but cannot be read as a file
    with pytest.raises(KeyStoreUnavailable, match="could not be read"):
        await PlaintextDevKeyStore(directory).public_key(dev_kid)


async def test_armed_target_rechecks_an_origin_chain_stored_while_unarmed(tmp_path: Path) -> None:
    async with _armed(tmp_path / "origin", _DuckKeyring()) as (registry, _):
        alpha = await _birth(registry, "Alpha")
        xfer = await registry.issue_transfer_certificate(alpha.agent_uuid, _TARGET_DID)
        chain = json.loads(json.dumps(await registry.export_chain()))
    tampered = copy.deepcopy(chain)
    _block_for(tampered, alpha.certificate_hash)["credential"]["credentialSubject"]["callsign"] = "Mallory"
    target_dir = tmp_path / "target"
    async with _registry(target_dir, instance_id="ship-b") as target:
        assert (await target.import_chain(tampered))[0]  # premise: the unarmed path stores it unchecked
    duck = _DuckKeyring()
    async with _armed(target_dir, duck, instance_id="ship-b") as (target, _):
        rejected, reason = await target.import_transfer_certificate(xfer)
        assert (await target.import_chain(chain))[0]  # the stored copy does not verify, so it holds no key history
        accepted, accepted_reason = await target.import_transfer_certificate(xfer)
    assert not rejected and reason.startswith("the origin chain's signatures do not verify")
    assert accepted, accepted_reason


async def test_verify_transfer_attestation_rejects_misdirected_and_malformed_input(tmp_path: Path) -> None:
    from probos.identity_keys import TransferVerdict, verify_transfer_attestation

    async with _armed(tmp_path / "origin", _DuckKeyring()) as (registry, _):
        alpha = await _birth(registry, "Alpha")
        xfer = await registry.issue_transfer_certificate(alpha.agent_uuid, _TARGET_DID)
        chain = json.loads(json.dumps(await registry.export_chain()))
    credential = xfer.to_verifiable_credential()
    anchor = _block_for(chain, xfer.certificate_hash)
    accepted = verify_transfer_attestation(
        chain, credential=credential, certificate_hash=xfer.certificate_hash, subject_did=xfer.did,
    )
    assert accepted.accepted and accepted.reason.startswith("transfer signed by ")  # premise
    assert accepted.birth_index == _block_for(chain, alpha.certificate_hash)["index"]
    assert verify_transfer_attestation(
        chain, credential=credential, certificate_hash=xfer.certificate_hash, subject_did=f"{SHIP_A}:someone-else",
    ) == TransferVerdict(False, f"the transfer anchor at block {anchor['index']} names another subject", None)
    assert verify_transfer_attestation(
        chain, credential={**credential, "issuanceDate": float("nan")}, certificate_hash=xfer.certificate_hash,
        subject_did=xfer.did,
    ) == TransferVerdict(False, "malformed transfer attestation (ValueError)", None)
    assert verify_transfer_attestation(
        [], credential=credential, certificate_hash=xfer.certificate_hash, subject_did=xfer.did,
    ) == TransferVerdict(False, "the origin chain's signatures do not verify: empty chain", None)


# --------------------------------------------------------------------------- #
# A-1 -- round-1 review: signatures re-read and verified before use, key history
# append-only per origin, anchors and births bound into certificate signatures
# --------------------------------------------------------------------------- #


def _wire(value: Any) -> Any:
    """What a peer receives: the value after a JSON round trip."""
    return json.loads(json.dumps(value))


def _stripped(chain: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The chain with every attestation removed; no block hash covers an attestation."""
    stripped = copy.deepcopy(chain)
    for block in stripped:
        block.pop("attestation", None)
    return stripped


def _relaid(chain: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Re-lay blocks as a hash-valid ledger: each index becomes its position and every link is recomputed."""
    for position, block in enumerate(chain):
        block["index"] = position
        if position:
            rebuilt = LedgerBlock(
                index=position, timestamp=block["timestamp"], certificate_hash=block["certificate_hash"],
                agent_did=block["agent_did"], previous_hash=chain[position - 1]["block_hash"],
            )
            block["previous_hash"] = rebuilt.previous_hash
            block["block_hash"] = rebuilt.compute_hash()
    return chain


def _forge_vc_jws(private_key: Any, kid: str, credential: dict[str, Any], **claims: Any) -> str:
    """A certificate signature with any key and header members, from AD-1144's primitives as any party can build."""
    protected = encode_protected_header({**claims, "alg": JWS_ALG, "kid": kid, "typ": VC_JWS_TYP})
    signature = sign_challenge(private_key, signing_input(protected, canonical_bytes(credential)).decode("ascii"))
    return compact_detached(protected, base64.b64decode(signature))


def _forged_transfer(cert: AgentBirthCertificate) -> TransferCertificate:
    """A content-valid transfer certificate anyone can build: every field is public."""
    xfer = TransferCertificate(
        did=cert.did, agent_uuid=cert.agent_uuid, agent_type=cert.agent_type, callsign=cert.callsign,
        origin_ship_did=SHIP_A, origin_vessel_name=cert.vessel_name, origin_instance_id=cert.instance_id,
        origin_birth_timestamp=cert.birth_timestamp, transfer_timestamp=time.time(),
        target_instance_did="did:probos:ship-mallory", baseline_version=cert.baseline_version,
    )
    xfer.certificate_hash = xfer.compute_hash()
    return xfer


def _keyless_reinception(chain: list[dict[str, Any]], *, compromised_after: int) -> tuple[Any, str]:
    """Append a re-inception signed only by a key the appending party made itself; ``(private key, kid)``."""
    events = [block for block in chain if (block.get("attestation") or {}).get("kind") == "key_event"]
    inception, head = events[0]["attestation"]["event"], events[-1]
    private_key, public_key = generate_keypair()
    kid = key_id(SHIP_A, public_key)
    payload = build_event_payload(
        did=SHIP_A, seq=head["attestation"]["event"]["seq"] + 1, event=EVENT_REINCEPTION,
        prior=head["certificate_hash"], kid=kid, public_key=public_key, recovery_public_key="",
        reason="compromised", compromised_after_index=compromised_after,
        ship_certificate_hash=inception["ship_certificate_hash"],
        ship_credential_digest=inception["ship_credential_digest"],
    )
    signature = sign_with(
        canonical_bytes(payload), kid=kid, typ=KEY_EVENT_JWS_TYP,
        sign=lambda message: sign_challenge(private_key, message),
    )
    _append_block(
        chain, certificate_hash=event_digest(payload), agent_did=SHIP_A,
        attestation={"kind": "key_event", "event": payload, "signatures": {"new": signature}},
    )
    return private_key, kid


async def _origin_with_void_transfer(
    data_dir: Path, *, before_recovery: list[list[dict[str, Any]]] | None = None,
) -> tuple[list[dict[str, Any]], TransferCertificate, int]:
    """Inception K1 (1), Alpha (2), rotation K2 (3), Bravo (4), Bravo's transfer by K2 (5), a recovery declaring
    K2 compromised after Bravo (6), Delta (7): the transfer is void. ``before_recovery`` receives the export taken
    right after the transfer, in which it is valid."""
    duck = _DuckKeyring()
    recovery_private, recovery_public = generate_recovery_keypair()
    async with _armed(data_dir, duck, recovery_public_key=recovery_public) as (registry, binding):
        await _birth(registry, "Alpha")
        await binding.rotate()
        bravo = await _birth(registry, "Bravo")
        xfer = await registry.issue_transfer_certificate(bravo.agent_uuid, _TARGET_DID)
        if before_recovery is not None:
            before_recovery.append(_wire(await registry.export_chain()))
        compromised_after = _block_for(await registry.export_chain(), bravo.certificate_hash)["index"]
        prepared = await binding.prepare_recovery(
            reason="compromised", compromised_after_index=compromised_after, next_recovery_public_key="",
        )
        await binding.apply_recovery(
            authorization=sign_recovery_authorization(recovery_private, prepared["signing_payload"]),
            reason="compromised", compromised_after_index=compromised_after, next_recovery_public_key="",
        )
        await _birth(registry, "Delta")
        chain = _wire(await registry.export_chain())
    return chain, xfer, compromised_after


async def _legacy_then_bound(
    data_dir: Path,
) -> tuple[AgentBirthCertificate, AgentBirthCertificate, TransferCertificate, list[dict[str, Any]]]:
    """Yankee and Xray born unsigned on an unarmed ship, which is then armed and transfers Xray."""
    async with _registry(data_dir) as legacy:
        yankee = await _birth(legacy, "Yankee")
        xray = await _birth(legacy, "Xray")
    async with _armed(data_dir, _DuckKeyring()) as (registry, binding):
        assert (await binding.status())["status"] == "active"  # premise: arming bound the ship after its births
        xfer = await registry.issue_transfer_certificate(xray.agent_uuid, _TARGET_DID)
        chain = _wire(await registry.export_chain())
    return yankee, xray, xfer, chain


async def _unsigned_birth_transfer(
    data_dir: Path,
) -> tuple[AgentBirthCertificate, TransferCertificate, list[dict[str, Any]]]:
    """Zulu born unsigned while the key was unavailable, then transferred once a restart re-activated the key."""
    duck = _DuckKeyring()
    store = _FlakySignStore(KeyringKeyStore(backend=duck))
    async with _armed(data_dir, duck, store=store) as (registry, binding):
        store.fail_sign = True
        zulu = await _birth(registry, "Zulu")
        assert (await binding.status())["status"] == "key_unavailable"  # premise
    async with _armed(data_dir, duck) as (registry, binding):
        assert (await binding.status())["status"] == "active"  # premise: a restart re-derives the key
        xfer = await registry.issue_transfer_certificate(zulu.agent_uuid, _TARGET_DID)
        chain = _wire(await registry.export_chain())
    return zulu, xfer, chain


class _PausingConnection:
    """Delegates to an aiosqlite connection; once armed, holds the next statement with one SQL prefix."""

    def __init__(self, inner: Any, prefix: str) -> None:
        self._inner = inner
        self._prefix = prefix
        self.armed = False
        self.paused = asyncio.Event()
        self.release = asyncio.Event()

    def execute(self, sql: str, parameters: Any = ()) -> Any:
        if self.armed and sql.lstrip().startswith(self._prefix):
            self.armed = False
            return self._held(sql, parameters)
        return self._inner.execute(sql, parameters)

    async def _held(self, sql: str, parameters: Any) -> Any:
        self.paused.set()
        await self.release.wait()
        return await self._inner.execute(sql, parameters)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class _PausingFactory:
    def __init__(self, prefix: str) -> None:
        self._prefix = prefix
        self.connection: _PausingConnection | None = None

    async def connect(self, db_path: str) -> Any:
        self.connection = _PausingConnection(await default_factory.connect(db_path), self._prefix)
        return self.connection


def _stored_chain(db_path: Path) -> Any:
    """The foreign chain row for ship A, read back from the table."""
    with contextlib.closing(sqlite3.connect(db_path)) as db:
        row = db.execute("SELECT chain_json FROM foreign_chains WHERE origin_ship_did = ?", (SHIP_A,)).fetchone()
    return json.loads(row[0]) if row else None


def _signed_counts(db_path: Path) -> list[int]:
    tables = ("transfer_certificates", "identity_signatures", "identity_key_events")
    return [_count_rows(db_path, table) for table in tables]


@pytest.mark.parametrize("kind", ["keyring", "plaintext_dev"])
async def test_a1_deleted_store_entry_stops_signing_without_a_restart(tmp_path: Path, kind: str) -> None:
    duck = _DuckKeyring()
    keys = tmp_path / "dev-keys"
    data_dir = tmp_path / "ship"
    store = KeyringKeyStore(backend=duck) if kind == "keyring" else PlaintextDevKeyStore(keys)
    async with _armed(data_dir, duck, store=store) as (registry, binding):
        alpha = await _birth(registry, "Alpha")
        kid = (await binding.status())["active_kid"]
        assert "attestation" in _block_for(await registry.export_chain(), alpha.certificate_hash)  # premise
        if kind == "keyring":
            duck.forget(kid)
            fresh: Any = KeyringKeyStore(backend=duck)
        else:
            next(keys.glob("*.key")).unlink()
            fresh = PlaintextDevKeyStore(keys)
        assert await fresh.public_key(kid) is None  # premise: the store no longer holds the key
        bravo = await _birth(registry, "Bravo")
        status = await binding.status()
        assert "attestation" not in _block_for(await registry.export_chain(), bravo.certificate_hash)
        assert status["status"] == "key_unavailable" and "no private key is stored" in status["reason"]
        before = await registry.export_chain()
        with pytest.raises(IdentityKeyUnavailable):
            await registry.issue_transfer_certificate(bravo.agent_uuid, _TARGET_DID)
        with pytest.raises(IdentityKeyStateError):
            await binding.rotate()
        after = await registry.export_chain()
    assert after == before
    assert _signed_counts(data_dir / "identity.db") == [0, 1, 1]  # no transfer; Alpha's signature; the inception
    assert duck.entries == {} and not list(keys.glob("*.key"))  # the refused rotation created no key


async def test_a1_failing_store_backend_stops_signing_without_a_restart(tmp_path: Path) -> None:
    class _FailingReads(_DuckKeyring):
        failing = False

        def get_password(self, service: str, username: str) -> str | None:
            if self.failing:
                raise OSError("AD-1196 test: backend fault")
            return super().get_password(service, username)

    duck = _FailingReads()
    data_dir = tmp_path / "ship"
    async with _armed(data_dir, duck) as (registry, binding):
        alpha = await _birth(registry, "Alpha")
        kid = (await binding.status())["active_kid"]
        assert "attestation" in _block_for(await registry.export_chain(), alpha.certificate_hash)  # premise
        duck.failing = True
        with pytest.raises(KeyStoreUnavailable, match="OSError"):  # premise: every read now fails
            await KeyringKeyStore(backend=duck).public_key(kid)
        bravo = await _birth(registry, "Bravo")
        status = await binding.status()
        assert "attestation" not in _block_for(await registry.export_chain(), bravo.certificate_hash)
        assert status["status"] == "key_unavailable" and "the keyring backend failed (OSError)" in status["reason"]
        before = await registry.export_chain()
        with pytest.raises(IdentityKeyUnavailable):
            await registry.issue_transfer_certificate(bravo.agent_uuid, _TARGET_DID)
        with pytest.raises(IdentityKeyStateError):
            await binding.rotate()
        after = await registry.export_chain()
    assert after == before
    assert _signed_counts(data_dir / "identity.db") == [0, 1, 1]
    assert list(duck.entries) == [(f"probos.identity:{kid}", kid)]  # the refused rotation created no key


@pytest.mark.parametrize("kind", ["keyring", "plaintext_dev"])
async def test_a1_swapped_store_entry_never_reaches_an_attestation(tmp_path: Path, kind: str) -> None:
    duck = _DuckKeyring()
    keys = tmp_path / "dev-keys"
    store = KeyringKeyStore(backend=duck) if kind == "keyring" else PlaintextDevKeyStore(keys)
    other_private, other_public = generate_keypair()
    async with _armed(tmp_path / "ship", duck, store=store) as (registry, binding):
        alpha = await _birth(registry, "Alpha")
        kid = (await binding.status())["active_kid"]
        assert "attestation" in _block_for(await registry.export_chain(), alpha.certificate_hash)  # premise
        if kind == "keyring":
            duck.set_password(f"probos.identity:{kid}", kid, encode_private_key(other_private))
            fresh: Any = KeyringKeyStore(backend=duck)
        else:
            next(keys.glob("*.key")).write_text(
                json.dumps({"kid": kid, "private_key": encode_private_key(other_private)}), encoding="utf-8",
            )
            fresh = PlaintextDevKeyStore(keys)
        assert await fresh.public_key(kid) == other_public  # premise: the entry now holds another key
        bravo = await _birth(registry, "Bravo")
        status = await binding.status()
        chain = _wire(await registry.export_chain())
    assert "attestation" not in _block_for(chain, bravo.certificate_hash)
    assert status["status"] == "key_unavailable" and "signed with a key other than" in status["reason"]
    report = verify_chain_signatures(chain)
    assert report.ok and report.valid == 1, report.reason


async def test_a1_store_signing_with_another_key_at_inception_leaves_the_ship_unbound(tmp_path: Path) -> None:
    class _SignsWithAnotherKey(_CountingStore):
        def __init__(self, inner: Any) -> None:
            super().__init__(inner)
            self.other, _ = generate_keypair()

        async def sign(self, kid: str, message: str) -> str:
            return sign_challenge(self.other, message)

    duck = _DuckKeyring()
    store = _SignsWithAnotherKey(KeyringKeyStore(backend=duck))
    data_dir = tmp_path / "ship"
    async with _armed(data_dir, duck, store=store) as (registry, binding):  # registry.start() returns
        status = await binding.status()
        cert = await _birth(registry, "Alpha")
        chain = await registry.export_chain()
    assert store.creates == 1 and len(duck.entries) == 1  # premise: the store created and kept the key it names
    assert status["status"] == "unbound" and "signed with a key other than" in status["reason"]
    assert _count_rows(data_dir / "identity.db", "identity_key_events") == 0
    assert "attestation" not in _block_for(chain, cert.certificate_hash)


@pytest.mark.parametrize("attack", ["stripped", "rolled_back", "moved"])
async def test_a1_armed_import_refuses_to_lose_a_held_key_event(tmp_path: Path, attack: str) -> None:
    from probos.identity_keys import verify_transfer_attestation

    void_transfer: TransferCertificate | None = None
    if attack == "stripped":
        held = (await _signed_origin(tmp_path / "origin")).chain
        arriving = _stripped(held)
    elif attack == "rolled_back":
        held, void_transfer, _ = await _origin_with_void_transfer(tmp_path / "origin")
        recovery = next(
            position for position, block in enumerate(held)
            if (block.get("attestation") or {}).get("event", {}).get("event") == EVENT_RECOVERY
        )
        arriving = copy.deepcopy(held[:recovery])  # the prefix that hides the compromise recovery
        assert verify_transfer_attestation(  # premise: on its own the prefix makes the void transfer valid
            arriving, credential=void_transfer.to_verifiable_credential(),
            certificate_hash=void_transfer.certificate_hash, subject_did=void_transfer.did,
        )[0]
    else:
        async with _armed(tmp_path / "origin", _DuckKeyring()) as (registry, _):
            await _birth(registry, "Alpha")
            held = _wire(await registry.export_chain())
        kinds = [block["attestation"]["kind"] for block in held if "attestation" in block]
        assert kinds == ["key_event", "agent_birth"]  # premise: the origin holds only its inception
        inserted = {
            "index": 1, "timestamp": held[0]["timestamp"] + 0.5,
            "certificate_hash": hashlib.sha256(b"inserted").hexdigest(), "agent_did": SHIP_A,
            "previous_hash": "", "block_hash": "", "credential": None,
        }
        # The inception moves to block 2; the later certificates are dropped (their signatures name their blocks).
        arriving = _relaid([copy.deepcopy(held[0]), inserted, copy.deepcopy(held[1])])
    hashes_ok, message = await AgentIdentityRegistry(data_dir=tmp_path / "unused").verify_remote_chain(arriving)
    report = verify_chain_signatures(arriving)
    assert hashes_ok and report.ok, (message, report.reason)  # premise: only the key-history rule can refuse it
    peer_dir = tmp_path / "peer"
    async with _armed(peer_dir, _DuckKeyring(), instance_id="peer") as (peer, _):
        assert (await peer.import_chain(held))[0]  # premise: the peer holds the signed history
        imported, message = await peer.import_chain(arriving)
        cached = peer.get_foreign_chain(SHIP_A)
        refused = None if void_transfer is None else await peer.import_transfer_certificate(void_transfer)
    assert not imported and message.startswith("Key history check failed: "), message
    assert cached == held and _stored_chain(peer_dir / "identity.db") == held
    if refused is not None:
        assert not refused[0] and "compromise point" in refused[1], refused


@pytest.mark.parametrize("by", ["keyless", "origin"])
async def test_a1_armed_peer_refuses_a_reinception_of_a_held_key_history(tmp_path: Path, by: str) -> None:
    from probos.identity_keys import verify_transfer_attestation

    async with _armed(tmp_path / "origin", _DuckKeyring()) as (registry, binding):
        assert not (await binding.status())["recovery_committed"]  # premise: nothing but continuity protects it
        alpha = await _birth(registry, "Alpha")
        held = _wire(await registry.export_chain())
        if by == "origin":
            await binding.reincept(reason="lost", compromised_after_index=None)
        arriving = _wire(await registry.export_chain())
    forged: TransferCertificate | None = None
    if by == "keyless":
        arriving = copy.deepcopy(held)
        inception = next(block for block in arriving if (block.get("attestation") or {}).get("kind") == "key_event")
        attacker_key, attacker_kid = _keyless_reinception(arriving, compromised_after=inception["index"])
        forged = _forged_transfer(alpha)
        birth = _block_for(arriving, alpha.certificate_hash)
        _append_block(
            arriving, certificate_hash=forged.certificate_hash, agent_did=alpha.did,
            attestation={"kind": "transfer", "jws": _forge_vc_jws(
                attacker_key, attacker_kid, forged.to_verifiable_credential(), anchor_index=len(arriving),
                birth_credential_digest=hashlib.sha256(canonical_bytes(birth["credential"])).hexdigest(),
            )},
        )
        assert verify_transfer_attestation(  # premise: against the attacked chain alone, the forged transfer is valid
            arriving, credential=forged.to_verifiable_credential(), certificate_hash=forged.certificate_hash,
            subject_did=forged.did,
        )[0]
    hashes_ok, message = await AgentIdentityRegistry(data_dir=tmp_path / "unused").verify_remote_chain(arriving)
    report = verify_chain_signatures(arriving)
    # Premise: the re-incepted chain verifies on its own.
    assert hashes_ok and report.ok and report.state is not None and report.state.continuity == "broken", (
        message, report.reason,
    )
    peer_dir = tmp_path / "peer"
    async with _armed(peer_dir, _DuckKeyring(), instance_id="peer") as (peer, _):
        assert (await peer.import_chain(held))[0]  # premise: the peer holds the origin's history
        imported, message = await peer.import_chain(arriving)
        cached = peer.get_foreign_chain(SHIP_A)
        refused = None if forged is None else await peer.import_transfer_certificate(forged)
    assert not imported and "re-incepts a key history this ship already holds" in message, message
    assert cached == held and _stored_chain(peer_dir / "identity.db") == held
    if refused is not None:
        assert tuple(refused) == (False, "transfer certificate is not anchored on the origin's ledger")


async def test_a1_armed_peer_learns_a_key_history_it_did_not_hold(tmp_path: Path) -> None:
    async with _armed(tmp_path / "origin", _DuckKeyring()) as (registry, binding):
        assert not (await binding.status())["recovery_committed"]  # premise: re-inception is the only recovery
        await _birth(registry, "Alpha")
        earlier = _wire(await registry.export_chain())
        await binding.reincept(reason="lost", compromised_after_index=None)
        await _birth(registry, "Bravo")
        genuine = _wire(await registry.export_chain())
    report = verify_chain_signatures(genuine)
    assert report.ok and report.state is not None and report.state.continuity == "broken"  # premise
    async with _armed(tmp_path / "peer", _DuckKeyring(), instance_id="peer") as (peer, _):
        # First contact cannot tell a stripped copy from a legacy chain (Q-D), so it is stored.
        assert (await peer.import_chain(_stripped(earlier)))[0]
        learned, learned_message = await peer.import_chain(genuine)
        stripped, stripped_message = await peer.import_chain(_stripped(genuine))
        cached = peer.get_foreign_chain(SHIP_A)
    assert learned, learned_message  # the signed history, re-inception included, replaces one that held none
    assert not stripped and stripped_message.startswith("Key history check failed: "), stripped_message
    assert cached == genuine


async def test_a1_a_stored_copy_that_does_not_verify_holds_no_key_history(tmp_path: Path) -> None:
    duck = _DuckKeyring()
    origin_dir = tmp_path / "origin"
    async with _armed(origin_dir, duck) as (registry, _):
        await _birth(registry, "Alpha")
        genuine = _wire(await registry.export_chain())
    inception = genuine[1]
    k2_private, k2_public = generate_keypair()
    wrong_private, _ = generate_keypair()
    payload = build_event_payload(
        did=SHIP_A, seq=1, event=EVENT_ROTATION, prior=inception["certificate_hash"],
        kid=key_id(SHIP_A, k2_public), public_key=k2_public, recovery_public_key="",
    )
    payload_bytes = canonical_bytes(payload)
    signatures = {
        "prior": sign_with(
            payload_bytes, kid=inception["attestation"]["event"]["key"]["kid"], typ=KEY_EVENT_JWS_TYP,
            sign=lambda message: sign_challenge(wrong_private, message),
        ),
        "new": sign_with(
            payload_bytes, kid=payload["key"]["kid"], typ=KEY_EVENT_JWS_TYP,
            sign=lambda message: sign_challenge(k2_private, message),
        ),
    }
    bad = copy.deepcopy(genuine)
    _append_block(
        bad, certificate_hash=event_digest(payload), agent_did=SHIP_A,
        attestation={"kind": "key_event", "event": payload, "signatures": signatures},
    )
    bad_report = verify_chain_signatures(bad)
    assert not bad_report.ok and bad_report.key_events == 2  # premise: it fails at replay, its key events counted
    peer_dir = tmp_path / "peer"
    async with _registry(peer_dir, instance_id="peer") as unarmed:
        assert (await unarmed.import_chain(bad))[0]  # premise: the unarmed path stores it unchecked
    async with _armed(origin_dir, duck) as (registry, _):
        await _birth(registry, "Bravo")
        grown = _wire(await registry.export_chain())
    assert grown[3]["attestation"]["kind"] == "agent_birth"  # premise: a birth where the copy holds a key event
    async with _armed(peer_dir, _DuckKeyring(), instance_id="peer") as (peer, _):
        imported, message = await peer.import_chain(grown)
        cached = peer.get_foreign_chain(SHIP_A)
    assert imported, message
    assert cached == grown


async def test_a1_armed_import_accepts_growth_and_replaced_unattested_blocks(tmp_path: Path) -> None:
    recovery_private, recovery_public = generate_recovery_keypair()
    async with _armed(tmp_path / "origin", _DuckKeyring(), recovery_public_key=recovery_public) as (
        registry, binding,
    ):
        await _birth(registry, "Alpha")
        first = _wire(await registry.export_chain())
        await binding.rotate()
        bravo = await _birth(registry, "Bravo")
        rotated = _wire(await registry.export_chain())
        compromised_after = _block_for(rotated, bravo.certificate_hash)["index"]
        prepared = await binding.prepare_recovery(
            reason="compromised", compromised_after_index=compromised_after, next_recovery_public_key="",
        )
        await binding.apply_recovery(
            authorization=sign_recovery_authorization(recovery_private, prepared["signing_payload"]),
            reason="compromised", compromised_after_index=compromised_after, next_recovery_public_key="",
        )
        recovered = _wire(await registry.export_chain())
        await _birth(registry, "Charlie")
        grown = _wire(await registry.export_chain())
    junk = copy.deepcopy(recovered)
    _append_block(junk, certificate_hash=hashlib.sha256(b"junk").hexdigest(), agent_did=f"{SHIP_A}:junk")
    position = len(recovered)
    # Premise: the junk tip is one more unsigned block, and the origin's own block at that position differs (P1).
    assert verify_chain_signatures(junk).ok and grown[position]["block_hash"] != junk[position]["block_hash"]
    arrivals = {
        "growth": first, "rotation": rotated, "compromise recovery": recovered,
        "identical re-export": copy.deepcopy(recovered), "junk tip": junk, "the origin's own next block": grown,
    }
    async with _armed(tmp_path / "peer", _DuckKeyring(), instance_id="peer") as (peer, _):
        results = {name: await peer.import_chain(chain) for name, chain in arrivals.items()}
        cached = peer.get_foreign_chain(SHIP_A)
    assert all(ok for ok, _ in results.values()), results
    assert cached == grown


async def test_a1_concurrent_imports_never_lose_a_held_key_event(tmp_path: Path) -> None:
    async with _armed(tmp_path / "origin", _DuckKeyring()) as (registry, binding):
        await _birth(registry, "Alpha")
        older = _wire(await registry.export_chain())
        await binding.rotate()
        await _birth(registry, "Bravo")
        newer = _wire(await registry.export_chain())
    # Premise: only the newer export carries the rotation.
    assert (verify_chain_signatures(older).key_events, verify_chain_signatures(newer).key_events) == (1, 2)
    factory = _PausingFactory("INSERT OR REPLACE INTO foreign_chains")
    peer_dir = tmp_path / "peer"
    async with _armed(peer_dir, _DuckKeyring(), instance_id="peer", connection_factory=factory) as (peer, _):
        assert (await peer.import_chain(older))[0]  # setup: the peer holds the older history
        connection = factory.connection
        assert connection is not None
        connection.armed = True
        import_b = asyncio.create_task(peer.import_chain(copy.deepcopy(older)))
        await asyncio.wait_for(connection.paused.wait(), timeout=10)  # B checked and is about to write
        import_a = asyncio.create_task(peer.import_chain(newer))
        done, _ = await asyncio.wait({import_a}, timeout=1.0)
        overtaken = bool(done)
        connection.release.set()
        results = await asyncio.gather(import_b, import_a)
        cached = peer.get_foreign_chain(SHIP_A)
    assert not overtaken  # A waits behind B instead of completing inside B's check-to-write window
    assert [ok for ok, _ in results] == [True, True], results
    assert cached == newer and _stored_chain(peer_dir / "identity.db") == newer


async def test_a1_unarmed_import_stays_latest_wins(tmp_path: Path) -> None:
    full = (await _signed_origin(tmp_path / "origin")).chain
    stripped, prefix = _stripped(full), copy.deepcopy(full[:4])
    peer_dir = tmp_path / "peer"
    async with _registry(peer_dir, instance_id="peer") as peer:
        results = [await peer.import_chain(chain) for chain in (full, stripped, prefix)]
        cached = peer.get_foreign_chain(SHIP_A)
    assert all(ok for ok, _ in results), results
    assert cached == prefix and _stored_chain(peer_dir / "identity.db") == prefix


async def test_a1_copied_birth_attestation_is_rejected(tmp_path: Path) -> None:
    origin = await _signed_origin(tmp_path / "origin")
    copied = copy.deepcopy(origin.chain)
    delta = origin.block(copied, "Delta")
    duplicate = _append_block(
        copied, certificate_hash=delta["certificate_hash"], agent_did=delta["agent_did"],
        credential=copy.deepcopy(delta["credential"]), attestation=copy.deepcopy(delta["attestation"]),
    )
    hashes_ok, _ = await AgentIdentityRegistry(data_dir=tmp_path / "unused").verify_remote_chain(copied)
    state = verify_chain_signatures(origin.chain).state
    assert hashes_ok and state is not None  # premise
    k3 = state.key(origin.kids[2])
    # Premise: K3 is valid at the copy's block and the copied signature is genuine; only its anchor refuses it.
    assert k3 is not None and key_valid_at(k3, duplicate["index"])
    assert verify_signature_for(
        duplicate["attestation"]["jws"], canonical_bytes(duplicate["credential"]),
        public_key_b64=k3.public_key, kid=k3.kid, typ=VC_JWS_TYP,
    )
    report = verify_chain_signatures(copied)
    assert not report.ok and f"block {duplicate['index']}" in report.reason, report.reason
    async with _armed(tmp_path / "peer", _DuckKeyring(), instance_id="peer") as (peer, _):
        imported, message = await peer.import_chain(copied)
    assert not imported and message.startswith("Signature check failed"), message


async def test_a1_void_transfer_moved_before_the_compromise_point_is_rejected(tmp_path: Path) -> None:
    chain, xfer, compromised_after = await _origin_with_void_transfer(tmp_path / "origin")
    position = _block_for(chain, xfer.certificate_hash)["index"]
    assert position == compromised_after + 1  # premise: the void transfer is the first block after the point
    laundered = copy.deepcopy(chain)
    laundered[position - 1], laundered[position] = laundered[position], laundered[position - 1]
    _relaid(laundered)
    hashes_ok, _ = await AgentIdentityRegistry(data_dir=tmp_path / "unused").verify_remote_chain(laundered)
    # Premise: an intact hash chain with no certificate hash anchored twice, and the transfer at the point.
    assert hashes_ok and len({block["certificate_hash"] for block in laundered}) == len(laundered)
    assert _block_for(laundered, xfer.certificate_hash)["index"] == compromised_after
    report = verify_chain_signatures(laundered)
    assert not report.ok, report.reason
    async with _armed(tmp_path / "peer", _DuckKeyring(), instance_id="peer") as (peer, _):
        imported, message = await peer.import_chain(laundered)
        accepted, reason = await peer.import_transfer_certificate(xfer)
    assert not imported and not accepted, (message, reason)


async def test_a1_block_index_must_equal_its_position(tmp_path: Path) -> None:
    origin = await _signed_origin(tmp_path / "origin")
    chain = copy.deepcopy(origin.chain)
    delta = origin.block(chain, "Delta")
    block = LedgerBlock(
        index=delta["index"], timestamp=chain[-1]["timestamp"] + 1.0, certificate_hash=delta["certificate_hash"],
        agent_did=delta["agent_did"], previous_hash=chain[-1]["block_hash"],
    )
    block.block_hash = block.compute_hash()
    chain.append({
        "index": block.index, "timestamp": block.timestamp, "certificate_hash": block.certificate_hash,
        "agent_did": block.agent_did, "previous_hash": block.previous_hash, "block_hash": block.block_hash,
        "credential": copy.deepcopy(delta["credential"]), "attestation": copy.deepcopy(delta["attestation"]),
    })
    position = len(chain) - 1
    hashes_ok, _ = await AgentIdentityRegistry(data_dir=tmp_path / "unused").verify_remote_chain(chain)
    state = verify_chain_signatures(origin.chain).state
    # Premise: the hash chain ignores the index field, and at the index it claims the signature is valid.
    assert hashes_ok and state is not None and position != delta["index"]
    assert signature_verdict(
        state, record_bytes=canonical_bytes(delta["credential"]), jws=delta["attestation"]["jws"],
        anchor_index=delta["index"], typ=VC_JWS_TYP,
    ) == "valid"
    report = verify_chain_signatures(chain)
    assert not report.ok and report.reason == f"the block at position {position} carries index {delta['index']}"


async def test_a1_birth_attestation_must_match_its_block_certificate(tmp_path: Path) -> None:
    origin = await _signed_origin(tmp_path / "origin")
    chain = copy.deepcopy(origin.chain)
    delta = origin.block(chain, "Delta")
    delta["certificate_hash"] = hashlib.sha256(b"another certificate").hexdigest()
    _relaid(chain)
    hashes_ok, _ = await AgentIdentityRegistry(data_dir=tmp_path / "unused").verify_remote_chain(chain)
    state = verify_chain_signatures(origin.chain).state
    assert hashes_ok and state is not None  # premise
    # Premise: subject, key window, anchor and signature all hold; only the proof value names another certificate.
    assert delta["credential"]["credentialSubject"]["id"] == delta["agent_did"]
    assert signature_verdict(
        state, record_bytes=canonical_bytes(delta["credential"]), jws=delta["attestation"]["jws"],
        anchor_index=delta["index"], typ=VC_JWS_TYP,
    ) == "valid"
    report = verify_chain_signatures(chain)
    assert not report.ok and "does not match its block's certificate" in report.reason, report.reason


async def test_a1_certificate_signatures_name_their_anchor_and_birth(tmp_path: Path) -> None:
    async with _armed(tmp_path / "origin", _DuckKeyring()) as (registry, binding):
        alpha = await _birth(registry, "Alpha")
        await binding.rotate()
        bravo = await _birth(registry, "Bravo")
        xfer = await registry.issue_transfer_certificate(alpha.agent_uuid, _TARGET_DID)
        chain = _wire(await registry.export_chain())

    def header(jws: str) -> dict[str, Any]:
        parsed = parse_detached(jws)
        assert parsed is not None
        return parsed.header

    signed = {
        block["index"]: header(block["attestation"]["jws"])
        for block in chain if (block.get("attestation") or {}).get("kind") in ("agent_birth", "transfer")
    }
    assert len(signed) == 3  # premise: two births and a transfer are signed
    assert {index: value.get("anchor_index") for index, value in signed.items()} == {index: index for index in signed}
    from probos.identity_keys import credential_digest

    anchor = _block_for(chain, xfer.certificate_hash)
    assert signed[anchor["index"]]["birth_credential_digest"] == credential_digest(
        _block_for(chain, alpha.certificate_hash)["credential"],
    )
    for cert in (alpha, bravo):
        assert "birth_credential_digest" not in signed[_block_for(chain, cert.certificate_hash)["index"]]
    event_headers = [
        header(jws) for block in chain if (block.get("attestation") or {}).get("kind") == "key_event"
        for jws in block["attestation"]["signatures"].values()
    ]
    assert len(event_headers) == 3  # premise: the inception's signature and the rotation's two
    assert all("anchor_index" not in value and "birth_credential_digest" not in value for value in event_headers)


@pytest.mark.parametrize("birth", ["legacy_birth", "unsigned_birth"])
async def test_a1_transfer_requires_the_birth_its_signature_names(tmp_path: Path, birth: str) -> None:
    if birth == "legacy_birth":
        _, cert, xfer, chain = await _legacy_then_bound(tmp_path / "origin")
    else:
        cert, xfer, chain = await _unsigned_birth_transfer(tmp_path / "origin")
    assert "attestation" not in _block_for(chain, cert.certificate_hash)  # premise: the birth itself is unsigned
    edited = copy.deepcopy(chain)
    _block_for(edited, cert.certificate_hash)["credential"]["credentialSubject"].update(
        department="bridge", postId="captain",
    )
    assert verify_chain_signatures(edited).ok  # premise: no signature covers an unsigned block's credential
    async with _armed(tmp_path / "peer", _DuckKeyring(), instance_id="peer") as (peer, _):
        assert (await peer.import_chain(edited))[0]
        refused, reason = await peer.import_transfer_certificate(xfer)
        forged_record = peer.get_by_uuid(cert.agent_uuid)
        assert (await peer.import_chain(chain))[0]  # the genuine chain keeps the same key history
        accepted, accepted_reason = await peer.import_transfer_certificate(xfer)
        stored = peer.get_by_uuid(cert.agent_uuid)
    assert not refused and reason == "the transferred agent's birth certificate is not on the origin's ledger", reason
    assert forged_record is None
    assert accepted, accepted_reason
    assert stored is not None and (stored.department, stored.certificate_hash) == ("operations", cert.certificate_hash)


async def test_a1_transfer_import_takes_the_record_from_the_bound_birth(tmp_path: Path) -> None:
    yankee, xray, xfer, chain = await _legacy_then_bound(tmp_path / "origin")
    decoy, genuine = _block_for(chain, yankee.certificate_hash), _block_for(chain, xray.certificate_hash)
    assert decoy["index"] < genuine["index"]  # premise: the decoy comes first in the chain
    edited = copy.deepcopy(chain)
    _block_for(edited, yankee.certificate_hash)["credential"]["credentialSubject"].update(
        id=xray.did, department="bridge", postId="captain",
    )
    # Premise: Xray's own birth is untouched and the edited chain still verifies.
    assert _block_for(edited, xray.certificate_hash)["credential"] == genuine["credential"]
    assert verify_chain_signatures(edited).ok
    async with _armed(tmp_path / "peer", _DuckKeyring(), instance_id="peer") as (peer, _):
        imported, message = await peer.import_chain(edited)
        accepted, reason = await peer.import_transfer_certificate(xfer)
        stored = peer.get_by_uuid(xray.agent_uuid)
    assert imported, message
    assert accepted, reason
    assert stored is not None
    assert (stored.department, stored.post_id, stored.certificate_hash) == (
        "operations", "post-Xray", xray.certificate_hash,
    )


async def test_a1_unreadable_birth_candidate_never_hides_the_bound_birth(tmp_path: Path) -> None:
    yankee, xray, xfer, chain = await _legacy_then_bound(tmp_path / "origin")
    edited = copy.deepcopy(chain)
    decoy = _block_for(edited, yankee.certificate_hash)
    # An unsigned block rewritten to claim Xray, with a credential RFC 8785 cannot canonicalise (NaN).
    decoy["agent_did"] = xray.did
    decoy["credential"]["credentialSubject"]["id"] = xray.did
    decoy["credential"]["issuanceDate"] = float("nan")
    _relaid(edited)
    hashes_ok, _ = await AgentIdentityRegistry(data_dir=tmp_path / "unused").verify_remote_chain(edited)
    # Premise: the rewritten chain verifies, and the decoy precedes Xray's genuine birth.
    assert hashes_ok and verify_chain_signatures(edited).ok
    assert decoy["index"] < _block_for(edited, xray.certificate_hash)["index"]
    with pytest.raises(ValueError):
        canonical_bytes(decoy["credential"])
    async with _armed(tmp_path / "peer", _DuckKeyring(), instance_id="peer") as (peer, _):
        imported, message = await peer.import_chain(edited)
        accepted, reason = await peer.import_transfer_certificate(xfer)
        stored = peer.get_by_uuid(xray.agent_uuid)
    assert imported, message
    assert accepted, reason
    assert stored is not None and (stored.department, stored.certificate_hash) == ("operations", xray.certificate_hash)


async def test_a1_transfer_signature_without_a_birth_binding_is_rejected(tmp_path: Path) -> None:
    from probos.identity_keys import verify_transfer_attestation

    duck = _DuckKeyring()
    async with _armed(tmp_path / "origin", duck) as (registry, binding):
        alpha = await _birth(registry, "Alpha")
        kid = (await binding.status())["active_kid"]
        chain = _wire(await registry.export_chain())
    forged = _forged_transfer(alpha)
    credential = forged.to_verifiable_credential()
    private_key = decode_private_key(duck.secret(kid))
    jws = _forge_vc_jws(private_key, kid, credential, anchor_index=len(chain))
    anchor = _append_block(
        chain, certificate_hash=forged.certificate_hash, agent_did=alpha.did,
        attestation={"kind": "transfer", "jws": jws},
    )
    # Premise: the origin's own key signed the transfer credential, and the header names the right block.
    assert verify_signature_for(
        jws, canonical_bytes(credential), public_key_b64=encode_public_key(private_key.public_key()), kid=kid,
        typ=VC_JWS_TYP,
    )
    parsed = parse_detached(jws)
    assert parsed is not None and parsed.header.get("anchor_index") == anchor["index"]
    report = verify_chain_signatures(chain)
    assert not report.ok and f"transfer attestation at block {anchor['index']}" in report.reason, report.reason
    verdict = verify_transfer_attestation(
        chain, credential=credential, certificate_hash=forged.certificate_hash, subject_did=forged.did,
    )
    assert not verdict[0], verdict


async def test_a1_stripped_transfer_block_never_satisfies_the_armed_transfer_requirement(tmp_path: Path) -> None:
    async with _armed(tmp_path / "origin", _DuckKeyring()) as (registry, _):
        alpha = await _birth(registry, "Alpha")
        xfer = await registry.issue_transfer_certificate(alpha.agent_uuid, _TARGET_DID)
        chain = _wire(await registry.export_chain())
    stripped = copy.deepcopy(chain)
    del _block_for(stripped, xfer.certificate_hash)["attestation"]
    assert verify_chain_signatures(stripped).key_events == 1  # premise: the origin is still bound
    async with _armed(tmp_path / "control", _DuckKeyring(), instance_id="control") as (control, _):
        assert (await control.import_chain(chain))[0]
        assert (await control.import_transfer_certificate(xfer))[0]  # premise: unedited, the transfer is accepted
    async with _armed(tmp_path / "peer", _DuckKeyring(), instance_id="peer") as (peer, _):
        imported, message = await peer.import_chain(stripped)
        accepted, reason = await peer.import_transfer_certificate(xfer)
        stored = peer.get_by_uuid(alpha.agent_uuid)
    assert imported, message
    assert not accepted and reason == "transfer certificate is not anchored on the origin's ledger", reason
    assert stored is None


# --------------------------------------------------------------------------- #
# A-2 -- round-2 review: a transfer import is checked and persisted under the
# chain-import lock, a failed signature by the active key latches whichever action
# asked for it, and the key-history hold applies only while the peer is armed
# --------------------------------------------------------------------------- #


class _ReadFailingKeyring(_DuckKeyring):
    """A duck keyring whose reads can be made to fail, as a backend that stops answering would."""

    failing = False

    def get_password(self, service: str, username: str) -> str | None:
        if self.failing:
            raise OSError("AD-1196 test: backend fault")
        return super().get_password(service, username)


class _NewKeysCannotSign(_CountingStore):
    """Signs with the keys it held when armed; once armed, no key it creates can sign."""

    def __init__(self, inner: Any) -> None:
        super().__init__(inner)
        self.armed = False
        self.created_after_arming: set[str] = set()
        self.signed_with: list[str] = []

    async def create(self, did: str) -> tuple[str, str]:
        kid, public_key = await super().create(did)
        if self.armed:
            self.created_after_arming.add(kid)
        return kid, public_key

    async def sign(self, kid: str, message: str) -> str:
        if kid in self.created_after_arming:
            raise KeyStoreUnavailable(f"AD-1196 test: the store cannot sign with {kid}")
        self.signed_with.append(kid)
        return await super().sign(kid, message)


async def _void_transfer_race(
    tmp_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], TransferCertificate]:
    """``(C0, C1, transfer)``: C0 is the origin's export right after the transfer, which it makes valid; C1, the
    helper's chain, adds the compromise recovery that voids it. The transfer is as the bridge carries it."""
    from probos.identity_keys import keeps_key_history, verify_transfer_attestation

    before_recovery: list[list[dict[str, Any]]] = []
    c1, issued, _ = await _origin_with_void_transfer(tmp_path / "origin", before_recovery=before_recovery)
    (c0,) = before_recovery
    xfer = TransferCertificate.from_dict(_wire(issued.to_dict()))

    def verdict(chain: list[dict[str, Any]]) -> Any:
        return verify_transfer_attestation(
            chain, credential=xfer.to_verifiable_credential(), certificate_hash=xfer.certificate_hash,
            subject_did=xfer.did,
        )

    valid, void = verdict(c0), verdict(c1)
    assert valid.accepted, valid  # premise: against C0 the transfer is valid
    assert not void.accepted and "compromise point" in void.reason, void  # premise: against C1 it is void
    assert keeps_key_history(c0, c1)[0]  # premise: an armed peer that holds C0 accepts C1
    async with _armed(tmp_path / "in-series", _DuckKeyring(), instance_id="peer") as (peer, _):
        assert (await peer.import_chain(copy.deepcopy(c0)))[0] and (await peer.import_chain(copy.deepcopy(c1)))[0]
        accepted, reason = await peer.import_transfer_certificate(xfer)
    assert not accepted and "compromise point" in reason, reason  # premise: in series, C1 voids the transfer
    return c0, c1, xfer


def _imported_rows(db_path: Path, did: str) -> tuple[int, int]:
    """``(foreign birth rows, incoming transfer rows)`` a peer holds for one agent."""
    with contextlib.closing(sqlite3.connect(db_path)) as db:
        births = db.execute("SELECT COUNT(*) FROM foreign_birth_certificates WHERE did = ?", (did,)).fetchone()[0]
        transfers = db.execute(
            "SELECT COUNT(*) FROM transfer_certificates WHERE did = ? AND direction = 'incoming'", (did,),
        ).fetchone()[0]
    return int(births), int(transfers)


async def _status_and_next_birth(
    registry: AgentIdentityRegistry, binding: IdentityKeyBinding,
) -> tuple[dict[str, Any], AgentBirthCertificate, list[dict[str, Any]]]:
    """The binding's status, then one more birth and the export that carries it."""
    status = await binding.status()
    charlie = await _birth(registry, "Charlie")
    return status, charlie, _wire(await registry.export_chain())


async def test_a2_a_chain_import_cannot_complete_inside_a_transfer_import(tmp_path: Path) -> None:
    c0, c1, xfer = await _void_transfer_race(tmp_path)
    factory = _PausingFactory("INSERT OR REPLACE INTO foreign_birth_certificates")
    peer_dir = tmp_path / "peer"
    order: list[str] = []
    async with _armed(peer_dir, _DuckKeyring(), instance_id="peer", connection_factory=factory) as (peer, _):
        assert (await peer.import_chain(copy.deepcopy(c0)))[0]  # setup: the peer holds C0
        connection = factory.connection
        assert connection is not None
        connection.armed = True
        transfer = asyncio.create_task(peer.import_transfer_certificate(xfer))
        transfer.add_done_callback(lambda _task: order.append("transfer"))
        await asyncio.wait_for(connection.paused.wait(), timeout=10)  # hang guard only
        assert not transfer.done()  # premise: the transfer verified against C0 and is held at its first write
        chain = asyncio.create_task(peer.import_chain(copy.deepcopy(c1)))
        chain.add_done_callback(lambda _task: order.append("chain"))
        connection.release.set()
        transferred, imported = await asyncio.gather(transfer, chain)
        cached = peer.get_foreign_chain(SHIP_A)
    assert order == ["transfer", "chain"]  # the voiding chain cannot land between the transfer's check and commit
    assert transferred[0] and imported[0], (transferred, imported)
    assert cached == c1 and _stored_chain(peer_dir / "identity.db") == c1


async def test_a2_a_transfer_import_verifies_against_a_chain_import_in_flight(tmp_path: Path) -> None:
    c0, c1, xfer = await _void_transfer_race(tmp_path)
    factory = _PausingFactory("INSERT OR REPLACE INTO foreign_chains")
    peer_dir = tmp_path / "peer"
    async with _armed(peer_dir, _DuckKeyring(), instance_id="peer", connection_factory=factory) as (peer, _):
        assert (await peer.import_chain(copy.deepcopy(c0)))[0]  # setup: the peer holds C0
        connection = factory.connection
        assert connection is not None
        connection.armed = True
        chain = asyncio.create_task(peer.import_chain(copy.deepcopy(c1)))
        await asyncio.wait_for(connection.paused.wait(), timeout=10)  # hang guard only
        assert not chain.done()  # premise: C1 passed its checks and holds A-1's lock at its write
        transfer = asyncio.create_task(peer.import_transfer_certificate(xfer))
        connection.release.set()
        imported, transferred = await asyncio.gather(chain, transfer)
        cached = peer.get_foreign_chain(SHIP_A)
        record = peer.get_by_uuid(xfer.agent_uuid)
    assert imported[0], imported
    assert not transferred[0] and "compromise point" in transferred[1], transferred
    assert record is None
    assert _imported_rows(peer_dir / "identity.db", xfer.did) == (0, 0)
    assert cached == c1 and _stored_chain(peer_dir / "identity.db") == c1


@pytest.mark.parametrize("fault", ["deleted", "swapped"])
async def test_a2_a_failed_rotation_latches_signing_off(
    tmp_path: Path, fault: str, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    duck = _DuckKeyring()
    data_dir = tmp_path / "ship"
    substitute_private, substitute_public = generate_keypair()
    async with _armed(data_dir, duck) as (registry, binding):
        alpha = await _birth(registry, "Alpha")
        status = await binding.status()
        kid = status["active_kid"]
        ledger_key = next(record["public_key"] for record in status["keys"] if record["kid"] == kid)
        alpha_jws = _block_for(await registry.export_chain(), alpha.certificate_hash)["attestation"]["jws"]
        assert jws_kid(alpha_jws) == kid  # premise: the active key signs
        genuine = duck.secret(kid)
        if fault == "deleted":
            duck.forget(kid)
            assert await KeyringKeyStore(backend=duck).public_key(kid) is None  # premise
            expected = f"no private key is stored for {kid}"
        else:
            duck.set_password(f"probos.identity:{kid}", kid, encode_private_key(substitute_private))
            assert await KeyringKeyStore(backend=duck).public_key(kid) == substitute_public  # premise
            expected = f"the key store signed with a key other than {kid}"
        mark = len(caplog.records)
        with pytest.raises(KeyStoreUnavailable) as raised:
            await binding.rotate()
        assert str(raised.value) == expected  # premise: the outgoing signature failed, not create()
        latched = await binding.status()
        assert latched["status"] == "key_unavailable" and latched["reason"] == expected, latched
        assert any(
            record.levelno == logging.WARNING and record.getMessage().startswith(
                f"AD-1196: identity key binding for {SHIP_A} is key_unavailable ({expected})",
            )
            for record in caplog.records[mark:]
        )
        duck.set_password(f"probos.identity:{kid}", kid, genuine)
        assert await KeyringKeyStore(backend=duck).public_key(kid) == ledger_key  # premise: the entry is back
        bravo = await _birth(registry, "Bravo")
        before = await registry.export_chain()
        with pytest.raises(IdentityKeyUnavailable):
            await registry.issue_transfer_certificate(bravo.agent_uuid, _TARGET_DID)
        with pytest.raises(IdentityKeyStateError):
            await binding.rotate()
        after = await registry.export_chain()
    assert "attestation" not in _block_for(before, bravo.certificate_hash)
    assert after == before
    assert _signed_counts(data_dir / "identity.db") == [0, 1, 1]  # no transfer; Alpha's signature; the inception
    report = verify_chain_signatures(after)
    assert report.ok and report.valid == 1, report.reason
    secrets = {genuine, *duck.entries.values()}
    if fault == "swapped":
        secrets.add(encode_private_key(substitute_private))
    assert all(secret not in caplog.text for secret in secrets)


@pytest.mark.parametrize("fault", ["create_fails", "proof_of_possession_fails"])
async def test_a2_a_rotation_whose_incoming_key_fails_does_not_latch(tmp_path: Path, fault: str) -> None:
    duck = _ReadFailingKeyring()
    store = _NewKeysCannotSign(KeyringKeyStore(backend=duck))
    async with _armed(tmp_path / "ship", duck, store=store) as (registry, binding):
        alpha = await _birth(registry, "Alpha")
        before = await binding.status()
        kid = before["active_kid"]
        alpha_jws = _block_for(await registry.export_chain(), alpha.certificate_hash)["attestation"]["jws"]
        assert jws_kid(alpha_jws) == kid  # premise: the active key signs
        entries, creates, signed = len(duck.entries), store.creates, len(store.signed_with)
        duck.failing = fault == "create_fails"
        store.armed = fault == "proof_of_possession_fails"
        with pytest.raises(KeyStoreUnavailable) as raised:
            await binding.rotate()
        assert store.creates == creates + 1  # premise: the rotation created its incoming key
        if fault == "create_fails":
            # Premise: create() wrote the incoming key and could not read it back; nothing was signed.
            assert str(raised.value) == "the keyring backend failed (OSError)"
            assert len(duck.entries) == entries + 1 and store.signed_with[signed:] == []
        else:
            # Premise: the outgoing key signed; the key the rotation created could not prove possession.
            assert store.signed_with[signed:] == [kid] and len(store.created_after_arming) == 1
            assert str(raised.value).startswith("AD-1196 test: the store cannot sign with ")
        duck.failing = False
        after = await binding.status()
        bravo = await _birth(registry, "Bravo")
        chain = await registry.export_chain()
    assert (after["status"], after["seq"], after["active_kid"]) == ("active", before["seq"], kid)
    assert jws_kid(_block_for(chain, bravo.certificate_hash)["attestation"]["jws"]) == kid


@pytest.mark.parametrize("way_out", ["recovery", "reinception", "restart"])
async def test_a2_recovery_reinception_and_restart_lead_out_of_a_rotation_latch(tmp_path: Path, way_out: str) -> None:
    duck = _DuckKeyring()
    recovery_private, recovery_public = generate_recovery_keypair()
    committed = recovery_public if way_out == "recovery" else ""
    data_dir = tmp_path / "ship"
    led_out: list[tuple[dict[str, Any], AgentBirthCertificate, list[dict[str, Any]]]] = []
    async with _armed(data_dir, duck, recovery_public_key=committed) as (registry, binding):
        await _birth(registry, "Alpha")
        kid = (await binding.status())["active_kid"]
        genuine = duck.forget(kid)
        with pytest.raises(KeyStoreUnavailable):
            await binding.rotate()
        latched = await binding.status()
        # Premise: the failed rotation latched signing off.
        assert latched["status"] == "key_unavailable" and kid in latched["reason"], latched
        assert latched["recovery_committed"] is (way_out == "recovery")  # premise
        expected_kid = kid
        if way_out == "recovery":
            prepared = await binding.prepare_recovery(
                reason="lost", compromised_after_index=None, next_recovery_public_key="",
            )
            expected_kid = (await binding.apply_recovery(
                authorization=sign_recovery_authorization(recovery_private, prepared["signing_payload"]),
                reason="lost", compromised_after_index=None, next_recovery_public_key="",
            ))["kid"]
            led_out.append(await _status_and_next_birth(registry, binding))
        elif way_out == "reinception":
            expected_kid = (await binding.reincept(reason="lost", compromised_after_index=None))["kid"]
            led_out.append(await _status_and_next_birth(registry, binding))
    if way_out == "restart":
        duck.set_password(f"probos.identity:{kid}", kid, genuine)
        async with _armed(data_dir, duck) as (registry, binding):
            led_out.append(await _status_and_next_birth(registry, binding))
    ((status, charlie, chain),) = led_out
    assert status["status"] == "active" and status["active_kid"] == expected_kid, status
    assert (expected_kid == kid) is (way_out == "restart")
    assert status["continuity"] == ("broken" if way_out == "reinception" else "intact")
    assert jws_kid(_block_for(chain, charlie.certificate_hash)["attestation"]["jws"]) == expected_kid
    report = verify_chain_signatures(chain)
    assert report.ok and report.void == () and report.valid == 2, report.reason  # Alpha's signature stays valid


async def test_a2_a_peer_holds_a_key_history_only_while_armed(tmp_path: Path) -> None:
    origin = await _signed_origin(tmp_path / "origin")
    held = origin.chain
    forged = _forged_transfer(origin.certs["Alpha"])
    peer_dir = tmp_path / "peer"
    duck = _DuckKeyring()
    async with _armed(peer_dir, duck, instance_id="peer") as (peer, _):
        assert (await peer.import_chain(copy.deepcopy(held)))[0]  # premise: the peer holds the signed history
        refused, reason = await peer.import_chain(_stripped(held))
        assert not refused and reason.startswith("Key history check failed"), reason  # premise
        assert not (await peer.import_transfer_certificate(forged))[0]  # premise: the forged transfer is refused
    async with _registry(peer_dir, instance_id="peer") as disarmed:  # what identity_keys_enabled: false builds
        imported, message = await disarmed.import_chain(_stripped(held))
        stored = disarmed.get_foreign_chain(SHIP_A)
    assert imported and stored == _stripped(held), message
    async with _armed(peer_dir, duck, instance_id="peer") as (peer, _):
        held_now = peer.get_foreign_chain(SHIP_A)
        accepted, accepted_reason = await peer.import_transfer_certificate(forged)
        relearned, relearned_message = await peer.import_chain(copy.deepcopy(held))
        refused_again, refused_again_reason = await peer.import_chain(_stripped(held))
    assert held_now is not None and verify_chain_signatures(held_now).key_events == 0
    # First contact again for this origin (Q-D; R-1; R-3 as corrected by A-2): pinned so the documented limit
    # stays true; AD-1198 owns closing it.
    assert accepted, accepted_reason
    assert relearned, relearned_message
    assert not refused_again and refused_again_reason.startswith("Key history check failed"), refused_again_reason
