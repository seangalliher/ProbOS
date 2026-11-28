"""AD-738f (#1868) S1: a distinct default Kokoro voice for each crew role, and a Captain override.

Real ``KokoroBackend``, ``PiperBackend``, ``NullBackend``, ``AgentRegistry``, ``SystemConfig``,
route and attachment store. The seam cases run the real ``scripts/kokoro_worker.py`` loop with
the stand-in engine of ``tests/fixtures/fake_kokoro_worker.py``, as a real ``python -I``
subprocess under the real ``VoiceSynthesisService``. The fake engine's audio lasts 0.05 s per
position in its voice list (af_heart, af_bella, bf_emma, bm_fable, am_liam), so ``duration_ms``
shows which voice spoke. No assertion reads a clock.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from probos.audio.tts import KokoroBackend, NullBackend, PiperBackend, kokoro_backend
from probos.audio.tts.backends import TTSBackend
from probos.audio.tts.kokoro_backend import KOKORO_ROLE_VOICES, KOKORO_VOICES
from probos.audio.tts.resident import PiperOutcome, VoiceSynthesisService
from probos.config import AttachmentsConfig, KokoroTTSConfig, SystemConfig, TTSConfig
from probos.routers import avatars as avatars_router_mod
from probos.routers import chat as chat_router_mod
from probos.routers.deps import get_runtime
from probos.substrate.registry import AgentRegistry
from probos.voice_profile_defaults import DEFAULT_VOICE_PROFILES

_REPO = Path(__file__).resolve().parents[1]
FAKE_WORKER = _REPO / "tests" / "fixtures" / "fake_kokoro_worker.py"
COUNSELOR_ID = "counselor_counselor_0_1a2b3c4d"
COUNSELOR_TWO_ID = "counselor_counselor_1_5e6f7a8b"
LONG_COUNSELOR_ID = "counselor_" + "x" * 119  # 129 characters: over the route's bound
UNKNOWN_ID = "nobody_here_0_00000000"


class _RecordingService:
    """Stands in for the service where a case asks only what a backend sends."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def synthesize(self, key, text, timeout, *, fields=None):
        self.calls.append((key, text, timeout, dict(fields or {})))
        return b"RIFF"

    async def synthesize_outcome(self, key, text, timeout, *, fields=None):
        # AD-738g S3a: KokoroBackend's call; PiperBackend (test_p1) still calls synthesize.
        self.calls.append((key, text, timeout, dict(fields or {})))
        return PiperOutcome(b"RIFF", "ok")


def _installed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **overrides) -> KokoroTTSConfig:
    """A Kokoro config whose files exist, so the backend reaches its service."""
    model = tmp_path / "model.onnx"
    model.write_bytes(b"\x00")
    voices = tmp_path / "voices.bin"
    voices.write_bytes(b"\x00")
    monkeypatch.setattr(kokoro_backend, "WORKER_SCRIPT", str(FAKE_WORKER))
    values = {"python_path": sys.executable, "model_path": str(model), "voices_path": str(voices)}
    values.update(overrides)
    return KokoroTTSConfig(**values)


def _calls(record: Path) -> list[dict]:
    return [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines() if line]


# --- the role table and the precedence ------------------------------------------------------


def test_v1_fifteen_roles_have_fifteen_distinct_catalogue_voices_and_none_is_the_ship_voice() -> None:
    assert dict(KOKORO_ROLE_VOICES) == {
        "counselor": "af_bella",
        "security_officer": "am_fenrir",
        "diagnostician": "am_michael",
        "pathologist": "bf_emma",
        "surgeon": "af_sarah",
        "pharmacist": "af_kore",
        "architect": "af_nicole",
        "data_analyst": "af_nova",
        "research_specialist": "af_aoede",
        "systems_analyst": "bf_isabella",
        "scout": "am_puck",
        "builder": "bm_george",
        "engineering_officer": "bm_lewis",
        "operations_officer": "bm_fable",
        "training_officer": "am_liam",
    }
    assert set(KOKORO_ROLE_VOICES) == set(DEFAULT_VOICE_PROFILES)
    assert set(KOKORO_ROLE_VOICES.values()) <= KOKORO_VOICES
    assert len(set(KOKORO_ROLE_VOICES.values())) == 15
    assert KokoroTTSConfig().voice == "af_heart"
    assert "af_heart" not in KOKORO_ROLE_VOICES.values()
    with pytest.raises(TypeError):
        KOKORO_ROLE_VOICES["counselor"] = "af_sky"  # type: ignore[index]


def test_v2_precedence_is_call_voice_then_captain_then_table_then_ship_voice() -> None:
    backend = KokoroBackend(KokoroTTSConfig(voice="bf_alice", agent_voices={"counselor": "bf_lily"}))

    assert backend.resolve_voice("af_sky", "counselor") == "af_sky"  # 1. a catalogue id per call
    assert backend.resolve_voice("en_US-ryan-medium", "counselor") == "bf_lily"  # foreign name ignored; 2.
    assert backend.resolve_voice(None, "counselor") == "bf_lily"  # 2. the Captain's map
    assert backend.resolve_voice(None, "scout") == "am_puck"  # 3. the built-in table
    assert backend.resolve_voice(None, "ensign") == "bf_alice"  # 4. a role in neither map
    assert backend.resolve_voice(None, None) == "bf_alice"  # 4. no role
    assert backend.resolve_voice(None) == "bf_alice"  # AD-738g's call shape still works
    assert backend.resolve_voice("af_sky") == "af_sky"


def test_v3_a_captain_override_changes_its_role_and_no_other() -> None:
    plain = KokoroBackend(KokoroTTSConfig())
    custom = KokoroBackend(KokoroTTSConfig(agent_voices={"counselor": "af_sky"}))

    assert len(KOKORO_ROLE_VOICES) == 15  # A1: the loop below proves nothing over an empty table
    for role, voice in KOKORO_ROLE_VOICES.items():
        assert plain.resolve_voice(None, role) == voice
        assert custom.resolve_voice(None, role) == ("af_sky" if role == "counselor" else voice)


def test_v4_the_voice_follows_the_role_alone_so_a_restart_or_roster_change_keeps_it() -> None:
    roles = list(KOKORO_ROLE_VOICES)
    first = [KokoroBackend(KokoroTTSConfig()).resolve_voice(None, role) for role in roles]
    restarted = KokoroBackend(KokoroTTSConfig())
    in_another_order = {role: restarted.resolve_voice(None, role) for role in reversed(roles)}

    assert first == [in_another_order[role] for role in roles]
    # Nothing per agent reaches the choice: no id, no pool index, no roster position.
    assert list(inspect.signature(KokoroBackend.resolve_voice).parameters) == [
        "self", "voice_override", "agent_type",
    ]


# --- config ---------------------------------------------------------------------------------


def test_c1_agent_voices_is_empty_by_default_and_checked_when_parsed() -> None:
    assert KokoroTTSConfig().agent_voices == {}
    first, second = KokoroTTSConfig(), KokoroTTSConfig()
    first.agent_voices["counselor"] = "af_sky"
    assert second.agent_voices == {}

    rejected = (
        {"counselor": "zz_nobody"}, {"counselor": "jf_alpha"}, {"Counselor": "af_sky"},
        {"": "af_sky"}, {"counselor officer": "af_sky"}, {"x" * 65: "af_sky"},
    )
    for values in rejected:
        with pytest.raises(ValueError):
            KokoroTTSConfig(agent_voices=values)

    # A role the built-in table lacks (a new crew type) is a valid key: the override gives it a voice.
    assert KokoroTTSConfig(agent_voices={"ensign": "af_sky"}).agent_voices == {"ensign": "af_sky"}
    assert KokoroTTSConfig(agent_voices={"x" * 64: "af_sky"}).agent_voices == {"x" * 64: "af_sky"}

    parsed = SystemConfig.model_validate(
        {"tts": {"backend": "kokoro", "kokoro": {"agent_voices": {"counselor": "bf_lily"}}}},
    )
    assert parsed.tts.kokoro.agent_voices == {"counselor": "bf_lily"}
    assert SystemConfig().tts.kokoro.agent_voices == {}


def test_c2_a_role_key_the_config_api_would_treat_as_secret_is_refused_when_parsed() -> None:
    from probos.settings.section_registry import is_secret_field_id

    # AD-741: /api/config hides a field whose last dot segment names a secret and refuses a
    # patch holding one, so such a role key could never be read back or saved there.
    for role in ("secretary", "token_keeper", "password_clerk", "api_key_officer", "private_key_holder"):
        assert is_secret_field_id(f"tts.kokoro.agent_voices.{role}")
        with pytest.raises(ValueError, match="secret"):
            KokoroTTSConfig(agent_voices={role: "af_sky"})

    # Every built-in role, and a new role-shaped name, stays readable and writable there.
    assert len(KOKORO_ROLE_VOICES) == 15
    for role in [*KOKORO_ROLE_VOICES, "ensign"]:
        assert not is_secret_field_id(f"tts.kokoro.agent_voices.{role}")
        assert KokoroTTSConfig(agent_voices={role: "af_sky"}).agent_voices == {role: "af_sky"}


# --- the backends ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_b1_the_backend_sends_the_roles_voice_and_logs_the_role(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    caplog.set_level(logging.INFO, logger="probos.audio.tts")
    svc = _RecordingService()
    backend = KokoroBackend(_installed(tmp_path, monkeypatch), service=svc)

    await backend.synthesize("Hello.", agent_type="counselor")
    await backend.synthesize("Hello.")

    assert [call[3]["voice"] for call in svc.calls] == ["af_bella", "af_heart"]
    assert svc.calls[0][0] == svc.calls[1][0]  # one worker key: the voice travels on the line
    assert "AD-738g: kokoro voice=af_bella speed=1.00 chars=6" in caplog.text
    assert "result=ok role=counselor" in caplog.text
    assert "result=ok role=-" in caplog.text


@pytest.mark.asyncio
async def test_b2_a_role_voice_or_emotion_that_is_not_a_string_is_ignored_and_never_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO)
    caplog.set_level(logging.INFO, logger="probos.audio.tts")
    svc = _RecordingService()
    backend = KokoroBackend(_installed(tmp_path, monkeypatch), service=svc)

    # The route sends only strings; a direct caller's list or dict is no role, voice or emotion.
    result = await backend.synthesize(
        "Hello.", emotion=["calm"], voice_override={"v": 1}, agent_type=["counselor"],  # type: ignore[arg-type]
    )

    assert result is not None
    assert svc.calls[0][3] == {"voice": "af_heart", "speed": 1.0}
    assert "result=ok role=-" in caplog.text


@pytest.mark.asyncio
async def test_p1_every_backend_accepts_the_role_and_piper_and_null_ignore_it(tmp_path: Path) -> None:
    for impl in (TTSBackend, KokoroBackend, PiperBackend, NullBackend):
        parameter = inspect.signature(impl.synthesize).parameters["agent_type"]
        assert parameter.default is None

    binary = tmp_path / "piper.bin"
    binary.write_bytes(b"\x00")
    voices = tmp_path / "voices"
    voices.mkdir()
    (voices / "en_US-amy-medium.onnx").write_bytes(b"\x00")
    (voices / "en_US-amy-medium.onnx.json").write_text("{}", encoding="utf-8")
    svc = _RecordingService()
    piper = PiperBackend(
        binary_path=str(binary), voice_model="en_US-amy-medium", voices_dir=str(voices), service=svc,
    )

    await piper.synthesize("Hello.")
    await piper.synthesize("Hello.", agent_type="counselor")

    assert len(svc.calls) == 2
    assert svc.calls[0] == svc.calls[1]  # same key, text, timeout and fields: the same Piper line
    assert await NullBackend().synthesize("Hello.", agent_type="counselor") is None


# --- the route, the registry and the real worker loop ----------------------------------------


@pytest.fixture
def service():
    svc = VoiceSynthesisService()
    yield svc
    svc.close()


@pytest.fixture
async def crew_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, service):
    """The real route over a real registry (two counselors, one with an overlong id) and a real ``SystemConfig``."""
    target = tmp_path / "attachments"
    target.mkdir()
    monkeypatch.setattr("probos.attachments.store._resolve_attachments_dir", lambda configured: target)
    registry = AgentRegistry()
    for agent_id in (COUNSELOR_ID, COUNSELOR_TWO_ID, LONG_COUNSELOR_ID):
        # The registry reads exactly these three attributes (registry.py, register()).
        await registry.register(SimpleNamespace(id=agent_id, agent_type="counselor", pool="counselor"))
    rt = SimpleNamespace(
        config=SystemConfig(attachments=AttachmentsConfig(attachments_dir=str(target))),
        voice_synthesis=service,
        registry=registry,
    )
    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()
    app = FastAPI()
    app.include_router(avatars_router_mod.router)
    app.dependency_overrides[get_runtime] = lambda: rt
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, rt, tmp_path
    chat_router_mod._ATTACHMENT_STORE_CACHE.clear()


def _kokoro_on(rt, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **kokoro) -> Path:
    """Turn Kokoro on with the real worker loop and the fake engine; return the engine's call record."""
    record = tmp_path / "engine-calls.jsonl"
    record.write_text("", encoding="utf-8")
    voices = tmp_path / "voices.bin"
    voices.write_bytes(b"")
    monkeypatch.setattr(kokoro_backend, "WORKER_SCRIPT", str(FAKE_WORKER))
    rt.config.tts = TTSConfig(
        backend="kokoro",
        kokoro=KokoroTTSConfig(
            python_path=sys.executable, model_path=str(record), voices_path=str(voices), **kokoro,
        ),
    )
    return record


@pytest.mark.asyncio
async def test_t1_post_tts_with_an_agent_id_speaks_the_roles_voice_through_the_real_worker(
    crew_client, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, rt, tmp_path = crew_client
    record = _kokoro_on(rt, tmp_path, monkeypatch)

    first = await client.post(
        "/api/avatars/tts",
        json={"text": "Good evening, Captain.", "agent_id": COUNSELOR_ID, "defer_visemes": True},
    )
    second = await client.post(
        "/api/avatars/tts",
        json={"text": "Good evening.", "agent_id": COUNSELOR_TWO_ID, "defer_visemes": True},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    body = first.json()
    assert body["backend"] == "kokoro"
    assert body["mime"] == "audio/wav"
    assert body["duration_ms"] == 100  # af_bella is the fake's 2nd voice: 2400 frames at 24 kHz
    assert second.json()["duration_ms"] == 100
    stored = await chat_router_mod._get_attachment_store(rt).get_path(body["audio_attachment_id"])
    assert hashlib.sha256(Path(stored).read_bytes()).hexdigest() == body["audio_attachment_id"]
    calls = _calls(record)
    assert [call["voice"] for call in calls] == ["af_bella", "af_bella"]  # two counselors share it
    assert calls[0]["lang"] == "en-us"
    assert len({call["pid"] for call in calls}) == 1  # one resident worker serves every voice


@pytest.mark.asyncio
async def test_t2_a_captain_override_reaches_the_worker_for_its_role(
    crew_client, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, rt, tmp_path = crew_client
    record = _kokoro_on(rt, tmp_path, monkeypatch, agent_voices={"counselor": "bf_emma"})

    response = await client.post(
        "/api/avatars/tts", json={"text": "Hello.", "agent_id": COUNSELOR_ID, "defer_visemes": True},
    )

    assert response.status_code == 200
    assert response.json()["backend"] == "kokoro"
    assert response.json()["duration_ms"] == 150  # bf_emma is the fake's 3rd voice
    assert [(call["voice"], call["lang"]) for call in _calls(record)] == [("bf_emma", "en-gb")]


@pytest.mark.asyncio
async def test_t3_a_missing_unknown_or_malformed_agent_id_speaks_the_ship_voice(
    crew_client, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, rt, tmp_path = crew_client
    record = _kokoro_on(rt, tmp_path, monkeypatch)
    bodies = (
        {"text": "One."},
        {"text": "Two.", "agent_id": UNKNOWN_ID},
        {"text": "Three.", "agent_id": LONG_COUNSELOR_ID},  # registered, but over 128 characters
        {"text": "Four.", "agent_id": 42},
        {"text": "Five.", "agent_id": "   "},
        {"text": "Six.", "agent_id": None},
    )

    for body in bodies:
        response = await client.post("/api/avatars/tts", json={**body, "defer_visemes": True})
        assert response.status_code == 200
        assert response.json()["duration_ms"] == 50  # af_heart, the fake's 1st voice

    assert [call["voice"] for call in _calls(record)] == ["af_heart"] * 6


@pytest.mark.asyncio
async def test_t4_the_role_reaches_the_backend_only_when_resolved(
    crew_client, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, rt, _tmp_path = crew_client
    rt.config.tts = TTSConfig(backend="piper")
    seen: list[dict] = []

    class _PreRoleBackend:
        """The pre-AD-738f signature: no ``agent_type``."""

        name = "piper"

        async def synthesize(self, text, emotion=None, voice_override=None):
            seen.append({"text": text, "emotion": emotion, "voice_override": voice_override})
            return None

    class _RoleBackend:
        name = "piper"

        async def synthesize(self, text, emotion=None, voice_override=None, agent_type=None):
            seen.append({"text": text, "agent_type": agent_type})
            return None

    monkeypatch.setattr("probos.audio.tts.select_backend", lambda name, cfg, service=None: _PreRoleBackend())
    for body in ({"text": "a"}, {"text": "b", "agent_id": UNKNOWN_ID}):
        response = await client.post("/api/avatars/tts", json=body)
        assert response.status_code == 200
        assert response.json()["backend"] == "disabled"

    monkeypatch.setattr("probos.audio.tts.select_backend", lambda name, cfg, service=None: _RoleBackend())
    response = await client.post("/api/avatars/tts", json={"text": "c", "agent_id": COUNSELOR_ID})
    assert response.status_code == 200

    assert seen == [
        {"text": "a", "emotion": None, "voice_override": None},
        {"text": "b", "emotion": None, "voice_override": None},
        {"text": "c", "agent_type": "counselor"},
    ]
