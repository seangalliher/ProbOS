# AD-738f S1 (#1868): a distinct Kokoro voice for each crew member

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-27
**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-27: amendment A1, section 15 (review round 1 repairs; corrects the scope line, D4, D8, section 9, the issue text and acceptance 3 and 4 in place, and adds 2 tests)
**Status:** ready to build. **Owning issue:** #1868 (stays open for S2). Commits say `Refs #1868.` No closing keyword anywhere.
**Base:** the speech drafting tree `e26cc9eb` (AD-738g S1 candidate `2afff0e0` merged with BF-930's built slices). Branch `feat/ad738f-1868-per-agent-voices-<date>`. **Number:** AD-738f is a reserved name (roadmap row 826, renumbered from AD-738a in Wave 158); no number is allocated, so `ad_ceiling.py` was not run.
**Line endings:** the working copies are CRLF and the blocks below are LF; match after normalising. Every SEARCH starts at the beginning of a line and occurs once in its file at its turn. All new text is ASCII.
**Estimated tests:** 11 new Python (new file), 4 new Vitest (new file); changed in place: 2 Vitest (`voice.perEmotion.test.tsx`), 1 pin (`test_ad1270e1_config_facade.py`), 1 snapshot entry (`test_ad1270e2c_experience_models.py`); 0 removed.
**Scope:** two commits (section 4). The default config (`tts.backend: browser`) and Piper are unchanged. Selecting `tts.backend: kokoro` turns the built-in role table on even with `agent_voices: {}`: a crew role then speaks its table voice, not the ship voice (A1 correction; the earlier "byte-identical to AD-738g S1" held only for a body without a resolvable `agent_id`, which still makes AD-738g's call).

## 1. Problem (premise table)

| Where | What it does today | Effect |
|---|---|---|
| `kokoro_backend.py`:56-64 `resolve_voice(voice_override)` | a catalogue override, else `tts.kokoro.voice` | with `tts.backend: kokoro` every crew member speaks in the one ship voice (`af_heart`, `experience.py`:652) |
| `voice_profile_defaults.py`:19-41 | 15 roles seeded with `voice_name=""` and only pitch, rate, volume | no role has a server voice |
| `voice.ts`:670-692 `_prepareServerSpeech(text, profile, emotion)` | sends `text`, `defer_visemes`, `emotion`, `voice_name` | no agent identity reaches the server, although every crew caller passes one to `speakResponse` (`ProfileInfoTab.tsx`:506 `agent.id`, `IntentSurface.tsx`:478 `spoken.agent_id`, `ProfileChatTab.tsx`:1190 `requestAgentId`, `useMeetingVoice.ts`:158) |
| `routers/avatars.py`:256-282 | validates `voice_name`, calls `backend.synthesize(text, emotion=..., voice_override=...)` | the route reads no `agent_id` and has no role to pass |
| `backends.py`:33-38 `TTSBackend.synthesize` | `(text, emotion, voice_override)` | AD-738g D6 reserved an `agent_type` keyword here for this AD |

## 2. Overview

The HXI sends the speaking agent's registry id as `agent_id` with each sentence. The route validates it (a non-blank string of at most 128 characters), looks it up with `runtime.registry.get(agent_id)` and reads the agent's `agent_type`. A resolved role goes to the backend as the keyword `agent_type`; an absent, malformed or unknown id resolves no role and the call is the same as before. `KokoroBackend.resolve_voice(voice_override, agent_type=None)` picks, first match wins:

1. `voice_override`, if it is one of the 28 catalogue ids (the HXI picker, an AD-718a proposal);
2. the Captain's `tts.kokoro.agent_voices[agent_type]` (new, default empty);
3. the built-in `KOKORO_ROLE_VOICES[agent_type]` (new: 15 roles, 15 distinct voices, none `af_heart`);
4. `tts.kokoro.voice`, the ship's voice.

Piper and the null backend accept `agent_type` and ignore it. Kokoro's per-sentence INFO line gains `role=<agent_type>` (or `role=-`) at its end; no agent id is logged.

Rejected, one line each:
- A `kokoro_voices.py` module (the consult's plan): the catalogue is already one `Literal` (`experience.py`:623) and `KOKORO_VOICES` (`kokoro_backend.py`:34); the role table sits beside the latter.
- The client resolves the role or the voice: the registry is the authority, and the HXI would need the catalogue (S2).
- Parse the role out of the id string (`identity.py`:20 `{agent_type}_{pool}_{index}_{hash8}`): the registry already holds `agent_type`; a format parse is a second source.
- Always pass `agent_type` (even `None`): 11 test stand-ins in 7 files have the pre-738f signature (D2), BF-930's among them, for no behaviour.
- Per-agent (not per-role) defaults: unstable across roster changes; a per-agent choice is the `voice_name` path (S2 picker).
- Keys of `agent_voices` checked against the 15 roles: a new crew type could then never be given a voice (D4).

## 3. Decisions

| # | Decision | Reason |
|---|---|---|
| D1 | The client sends `agent_id`; the server resolves it with `runtime.registry.get(agent_id)` (`substrate/registry.py`:58) and reads `agent.agent_type` (`substrate/agent.py`:32). Boundary: `isinstance(str)`, non-blank, `len <= 128` (the `voice_name` style, `avatars.py`:257); anything else, or an id the registry lacks, means no role, never an error | the registry is the one authority for role; a real runtime always has it (`runtime.py`:691); no existing test posts `agent_id` to the route (Absence Verified), so direct attribute access breaks no stand-in runtime |
| D2 | `TTSBackend.synthesize` and the three backends gain `agent_type: str | None = None`; the route passes it **only when a role was resolved** (`**role_kwargs`) | without an id the backend call is the same call as before (off is off at the seam), and the 11 stand-ins with the old signature need no edit: `test_ad738e_1_per_emotion_prosody.py`:167, `test_ad738_piper_tts.py`:440, :468, :515, `test_bf291_piper_voice_catalog.py`:181, :207, :233, `test_bf918_tts_retention.py`:253, `test_bf918_tts_latency.py`:103, `test_bf930_speech_defers_idle_dream.py`:37, `test_bf930_voice_path_timing.py`:426. P1 pins that every real implementation accepts the keyword; T4 pins the call shape |
| D3 | `KOKORO_ROLE_VOICES` (a read-only `MappingProxyType`) in `kokoro_backend.py`, the consult's table: counselor `af_bella`, security_officer `am_fenrir`, diagnostician `am_michael`, pathologist `bf_emma`, surgeon `af_sarah`, pharmacist `af_kore`, architect `af_nicole`, data_analyst `af_nova`, research_specialist `af_aoede`, systems_analyst `bf_isabella`, scout `am_puck`, builder `bm_george`, engineering_officer `bm_lewis`, operations_officer `bm_fable`, training_officer `am_liam` | gender follows the archetype comments (`voice_profile_defaults.py`:21-40); 15 distinct; none `af_heart`; keyed by `agent_type`, so a roster change keeps each voice |
| D4 | `tts.kokoro.agent_voices: dict[str, KokoroVoiceId]`, default empty. Values are checked by the `Literal` at parse time. Keys are checked for shape (`[a-z][a-z0-9_]{0,63}`), not against the 15 roles; A1: a key the AD-741 secret rule matches (`secret`, `token`, `password`, `api_key`, `private_key`) is refused at parse time | the config API would hide such a key on read and refuse a patch holding it; no current role contains those words. A role the table lacks (a new crew type) must be nameable, since the override is how it gets a voice. A misspelt role matches no agent and changes nothing; the per-sentence log line (`role=... voice=...`) shows it at once. A bad voice id fails the parse, as `tts.kokoro.voice` does |
| D5 | Precedence as section 2 | the consult's order: an explicit per-call choice beats the Captain's per-role map, which beats the built-in table, which beats the ship voice |
| D6 | A role in neither map speaks the ship voice; two agents of one role share the role's voice (a stated limit) | stability by role; a per-agent voice is the `voice_name` path (S2) |
| D7 | Append ` role=%s` (`agent_type or "-"`) to the end of 738g's INFO line; nothing else in it changes | the only pins are substrings at `test_ad738g_kokoro_voice.py`:422 (`"AD-738g: kokoro voice=af_heart speed=1.00 chars=6"`) and :423 (`"result=ok"`), both still matched |
| D8 | Audition first: training_officer (`am_liam`, grade D) and engineering_officer (`bm_lewis`, D+) | VOICES.md grades the male voices lowest; seven male roles (security_officer, diagnostician, scout, builder, engineering_officer, operations_officer, training_officer; A1 correction from "six"), and only five male voices grade C or better (`am_fenrir`, `am_michael`, `am_puck` C+; `bm_george`, `bm_fable` C). `agent_voices` is the answer, not a table change |
| D9 | Captain conditions: none | off by default; no new dependency, process, network path or authority; no security, governance or audit control changes (orchestrator.agent.md, Delegated AD Execution Mode) |

## 4. Milestones and commits

**M1, server (about 70 tool calls).** 6.1 to 6.8, then the regenerations of 6.9, then 6.10. Stage exactly: `src/probos/audio/tts/backends.py`, `src/probos/audio/tts/null_backend.py`, `src/probos/audio/tts/piper_backend.py`, `src/probos/audio/tts/kokoro_backend.py`, `src/probos/config_models/experience.py`, `src/probos/routers/avatars.py`, `tests/test_ad738f_per_agent_voices.py`, `tests/test_ad1270e1_config_facade.py`, `tests/test_ad1270e2c_experience_models.py`, `docs/development/config-facade-baseline.yaml`, `docs/development/config-reference.md`. Subject: `Speech: each crew role speaks with its own Kokoro voice, with a Captain override per role, off until configured`.

**M2, client and trackers (about 50 tool calls).** 6.11 to 6.16, then `d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py` (no `--online`). Stage exactly: `ui/src/audio/voice.ts`, `ui/src/audio/__tests__/voice.agentVoice.test.tsx`, `ui/src/audio/__tests__/voice.perEmotion.test.tsx`, `docs/development/roadmap.md`, `PROGRESS.md`, `DECISIONS.md`, and `docs/development/ad-ledger-snapshot.json` and `docs/development/open-ads-report.md` when they change. Subject: `Speech: the HXI sends the speaking crew member's id with each sentence, and the trackers`.

No subject carries an `AD-` or `BF-` token or the words close, fix or resolve. Body ends `Refs #1868.` Stage explicit paths only; never `git add -A`. No file here may hold unrelated Captain work (`config/system.yaml` is not touched).

## 5. Builder: may and may not

- **May:** apply the pairs in order; create the two new test files from the full bodies below; run the two generators of 6.9 (`check_config_facade.py --update-baseline`, `gen_config_reference.py`) and `gen_ad_ledger.py`; set the one count pin of 6.9 from the checker's printed `fields=`; `git diff --check`; `git diff --stat`.
- **May not:** run any test or any `--check`, commit, edit an unnamed file, add `skip` or a retry, or reword an anchor. If a SEARCH does not match exactly once, stop and report. **The orchestrator runs every test and makes every commit.**

## 6. The pairs

### 6.1 `src/probos/audio/tts/backends.py` (M1)

**P1.** SEARCH:
```python
        voice_override: str | None = None,
    ) -> TTSResult | None:
        """Synthesize ``text`` to audio bytes. Return ``None`` on any failure.
```
REPLACE:
```python
        voice_override: str | None = None,
        agent_type: str | None = None,
    ) -> TTSResult | None:
        """Synthesize ``text`` to audio bytes. Return ``None`` on any failure.
```

**P2.** SEARCH:
```python
        back to the configured ``tts.voice_model`` silently.
        """
        ...
```
REPLACE:
```python
        back to the configured ``tts.voice_model`` silently.

        AD-738f (#1868): ``agent_type`` is the speaking crew member's role,
        resolved by the route from the request's ``agent_id`` through the agent
        registry. The route passes it only when it resolved one. A backend may
        choose a per-role voice with it (Kokoro does) and must otherwise ignore it.
        """
        ...
```

### 6.2 `src/probos/audio/tts/null_backend.py` (M1)

**P3.** SEARCH:
```python
        voice_override: str | None = None,
    ) -> TTSResult | None:
        """No-op. Returns ``None`` for honest-degrade.

        AD-738e-1: ``emotion`` accepted for Protocol compat; ignored.
        BF-291 / AD-738f: ``voice_override`` accepted for Protocol compat;
        ignored because the null backend produces no audio.
        """
        del emotion, voice_override
        return None
```
REPLACE:
```python
        voice_override: str | None = None,
        agent_type: str | None = None,
    ) -> TTSResult | None:
        """No-op. Returns ``None`` for honest-degrade.

        AD-738e-1: ``emotion`` accepted for Protocol compat; ignored.
        BF-291 / AD-738f: ``voice_override`` accepted for Protocol compat;
        ignored because the null backend produces no audio.
        AD-738f (#1868): ``agent_type`` accepted for Protocol compat; ignored.
        """
        del emotion, voice_override, agent_type
        return None
```

### 6.3 `src/probos/audio/tts/piper_backend.py` (M1)

**P4.** SEARCH:
```python
        voice_override: str | None = None,
    ) -> TTSResult | None:
        """Run piper, return WAV bytes or ``None`` on any failure.
```
REPLACE:
```python
        voice_override: str | None = None,
        agent_type: str | None = None,
    ) -> TTSResult | None:
        """Run piper, return WAV bytes or ``None`` on any failure.

        AD-738f (#1868): ``agent_type`` (the speaking crew role) is accepted for
        the Protocol and ignored: Piper has no per-role default voice.
```

**P5.** SEARCH:
```python
        ``None`` (no point invoking the subprocess for nothing)."""
        if not text or not text.strip():
            return None
        binary = _resolve_binary_path(self._binary_path)
```
REPLACE:
```python
        ``None`` (no point invoking the subprocess for nothing)."""
        del agent_type
        if not text or not text.strip():
            return None
        binary = _resolve_binary_path(self._binary_path)
```

### 6.4 `src/probos/audio/tts/kokoro_backend.py` (M1)

**P6.** SEARCH:
```python
import logging
import time
from typing import get_args
```
REPLACE:
```python
import logging
import time
from collections.abc import Mapping
from types import MappingProxyType
from typing import get_args
```

**P7.** SEARCH:
```python
#: kokoro-onnx raises ``ValueError`` for a speed outside this range.
SPEED_MIN = 0.5
SPEED_MAX = 2.0
```
REPLACE:
```python
#: kokoro-onnx raises ``ValueError`` for a speed outside this range.
SPEED_MIN = 0.5
SPEED_MAX = 2.0
#: AD-738f (#1868) S1: each crew role's own voice, keyed by ``agent_type`` so a roster change
#: keeps it: one voice per role, none the ship's ``af_heart``, the gender following each role's
#: archetype in ``voice_profile_defaults.py``. hexgrad/Kokoro-82M VOICES.md (read 2026-11-27)
#: grades the male voices lowest (``am_liam`` D, ``bm_lewis`` D+); ``tts.kokoro.agent_voices``
#: replaces any of them.
KOKORO_ROLE_VOICES: Mapping[str, str] = MappingProxyType({
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
})
```

**P8.** SEARCH:
```python
    def resolve_voice(self, voice_override: str | None) -> str:
        """The voice for one call: a catalogue override (the HXI picker, an AD-718a proposal), else ``tts.kokoro.voice``.

        A name the catalogue lacks (a Piper or browser voice name) is ignored. AD-738f (#1868)
        adds the per-role default between the two.
        """
        if voice_override is not None and voice_override in KOKORO_VOICES:
            return voice_override
        return self._config.voice
```
REPLACE:
```python
    def resolve_voice(self, voice_override: str | None, agent_type: str | None = None) -> str:
        """The voice for one call; the first match wins (AD-738f, #1868):

        1. ``voice_override`` when it is a catalogue id (the HXI picker, an AD-718a proposal);
           any other name (a Piper or browser voice name) is ignored;
        2. the Captain's ``tts.kokoro.agent_voices[agent_type]``;
        3. the built-in ``KOKORO_ROLE_VOICES[agent_type]``;
        4. ``tts.kokoro.voice``, the ship's voice (no role, or a role in neither map).
        """
        if voice_override is not None and voice_override in KOKORO_VOICES:
            return voice_override
        if agent_type is not None:
            if agent_type in self._config.agent_voices:
                return self._config.agent_voices[agent_type]
            if agent_type in KOKORO_ROLE_VOICES:
                return KOKORO_ROLE_VOICES[agent_type]
        return self._config.voice
```

**P9.** SEARCH:
```python
        voice_override: str | None = None,
    ) -> TTSResult | None:
        """WAV bytes from the resident Kokoro worker, or ``None`` on any failure. NEVER raises."""
```
REPLACE:
```python
        voice_override: str | None = None,
        agent_type: str | None = None,
    ) -> TTSResult | None:
        """WAV bytes from the resident Kokoro worker, or ``None`` on any failure. NEVER raises.

        AD-738f (#1868): ``agent_type``, the speaking crew role, picks the role's voice
        (``resolve_voice``). The one resident worker serves every voice.
        """
```

**P10.** SEARCH:
```python
        voice = self.resolve_voice(voice_override)
```
REPLACE:
```python
        voice = self.resolve_voice(voice_override, agent_type)
```

**P11.** SEARCH:
```python
        logger.info(
            "AD-738g: kokoro voice=%s speed=%.2f chars=%d synth_ms=%.0f result=%s",
            voice, speed, len(text), (time.perf_counter() - started) * 1000,
            "ok" if wav is not None else "degraded",
        )
```
REPLACE:
```python
        # AD-738f (#1868): the role goes last, so the Captain can read which role spoke in which
        # voice; no agent id is logged.
        logger.info(
            "AD-738g: kokoro voice=%s speed=%.2f chars=%d synth_ms=%.0f result=%s role=%s",
            voice, speed, len(text), (time.perf_counter() - started) * 1000,
            "ok" if wav is not None else "degraded", agent_type or "-",
        )
```

### 6.5 `src/probos/config_models/experience.py` (M1)

**P12.** SEARCH:
```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator
```
REPLACE:
```python
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator
```

**P13.** SEARCH:
```python
    "bm_daniel", "bm_fable", "bm_george", "bm_lewis",
]


class KokoroTTSConfig(BaseModel):
```
REPLACE:
```python
    "bm_daniel", "bm_fable", "bm_george", "bm_lewis",
]

#: AD-738f (#1868): a key of ``tts.kokoro.agent_voices`` is a role name (an ``agent_type``).
_ROLE_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")


class KokoroTTSConfig(BaseModel):
```

**P14.** SEARCH:
```python
    timeout_seconds: float = Field(default=30.0, gt=0.0)
    """Per-sentence timeout, counted from when the worker takes the request. A timeout kills
    the worker, and the next sentence reloads the model (about 3.2 s cold)."""
```
REPLACE:
```python
    timeout_seconds: float = Field(default=30.0, gt=0.0)
    """Per-sentence timeout, counted from when the worker takes the request. A timeout kills
    the worker, and the next sentence reloads the model (about 3.2 s cold)."""

    agent_voices: dict[str, KokoroVoiceId] = Field(default_factory=dict)
    """AD-738f (#1868) S1: the Captain's voice for a crew role (an ``agent_type``), for example
    ``counselor: af_sky``. It replaces that role's built-in voice
    (``probos.audio.tts.kokoro_backend.KOKORO_ROLE_VOICES``); a per-call ``voice_name`` that is
    one of these ids replaces both. A role the built-in table lacks may be named. A misspelt
    role matches no crew member and changes nothing; each sentence's log line shows its
    ``voice=`` and ``role=``."""

    @field_validator("agent_voices")
    @classmethod
    def _keys_are_role_names(cls, value: dict[str, str]) -> dict[str, str]:
        """A key is an ``agent_type``: lowercase letters, digits and ``_``, at most 64 characters."""
        for role in value:
            if not _ROLE_NAME.fullmatch(role):
                raise ValueError(f"tts.kokoro.agent_voices: {role!r} is not a role name (an agent_type)")
        return value
```

### 6.6 `src/probos/routers/avatars.py` (M1)

**P15.** SEARCH:
```python
        voice_name = None

    # BF-918 (#1626): a client that asks gets its visemes from POST /api/avatars/lipsync
```
REPLACE:
```python
        voice_name = None

    # AD-738f (#1868): optional ``agent_id``, the speaking crew member's registry id. The
    # registry resolves it to a role, which a backend may use for a per-role voice (Kokoro
    # does; Piper and null ignore it). Tier-1 boundary validation, as for ``voice_name``: a
    # malformed, overlong or unknown id means no role, never an error.
    agent_type: str | None = None
    agent_id = payload.get("agent_id")
    if isinstance(agent_id, str) and agent_id.strip() and len(agent_id) <= 128:
        agent = runtime.registry.get(agent_id)
        if agent is not None and isinstance(agent.agent_type, str) and agent.agent_type:
            agent_type = agent.agent_type

    # BF-918 (#1626): a client that asks gets its visemes from POST /api/avatars/lipsync
```

**P16.** SEARCH:
```python
    result = await backend.synthesize(text, emotion=emotion, voice_override=voice_name)
```
REPLACE:
```python
    # AD-738f: the role goes to the backend only when one was resolved, so a body without an
    # agent id makes the same backend call as before.
    role_kwargs: dict[str, str] = {} if agent_type is None else {"agent_type": agent_type}
    result = await backend.synthesize(text, emotion=emotion, voice_override=voice_name, **role_kwargs)
```

### 6.7 `tests/test_ad1270e2c_experience_models.py` (M1)

**P17.** SEARCH (35 spaces of indent, as in the file):
```python
                                   'threads': 4,
                                   'timeout_seconds': 30.0}},
```
REPLACE:
```python
                                   'threads': 4,
                                   'timeout_seconds': 30.0,
                                   # AD-738f S1 (#1868): the Captain's per-role voices, empty by default.
                                   'agent_voices': {}}},
```

### 6.8 `tests/test_ad738f_per_agent_voices.py` (new, M1)

```python
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
from probos.audio.tts.resident import VoiceSynthesisService
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
```

### 6.9 Regenerations and the config pin (M1, after 6.5)

Run, from the worktree root, in this order (the Builder runs the first two; the orchestrator runs the three `--check`s in 8.2):
```text
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_facade.py --update-baseline
d:/ProbOS/.venv/Scripts/python.exe scripts/gen_config_reference.py
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_facade.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/gen_config_reference.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_profiles.py --check
```
This slice adds one field to an existing owned model and no model or public name. The checker prints `models=` from `own_models` (`check_config_facade.py`:1785-1787), not `len(baseline["models"])`. **On this tree** it must print `names=311, owned=298, incidental=13, models=229, fields=1886`. Only `fields` moves (1885 -> 1886). The pin census for this change: `test_ad1270e1_config_facade.py`:1581 (`field_definitions`) moves. These stay: :1587-1588 (`len(baseline["names"])` 311, `len(baseline["models"])` 230), :1827 (`"names=311" in proc.stdout`) and the `public_names`/`owned`/`own_models` pins of P9.1 in the 738g contract. `check_config_profiles.py --check` passes unchanged (no `bool` field).

**Regeneration rule (merge order).** BF-932 adds `SystemInfo.loop_stall_warn_seconds` (one field). Whichever of the two lands second regenerates with the first two commands on the merged tree and sets :1581 to the printed `fields=` (1887 if both are in), adding its own comment line to the chain. It changes no other pin, because neither change adds a model or a name. Any other drift in `names`, `owned`, `incidental` or `models`: stop and report.

**P18.** `tests/test_ad1270e1_config_facade.py`. SEARCH:
```python
    # AD-738g S1 (#1662) adds KokoroTTSConfig's seven fields and TTSConfig.kokoro (1877 -> 1885).
    assert counts["field_definitions"] == 1885  # AD-1206 intentionally adds github_repository.
```
REPLACE:
```python
    # AD-738g S1 (#1662) adds KokoroTTSConfig's seven fields and TTSConfig.kokoro (1877 -> 1885).
    # AD-738f S1 (#1868) adds KokoroTTSConfig.agent_voices (1885 -> 1886).
    assert counts["field_definitions"] == 1886  # AD-1206 intentionally adds github_repository.
```

### 6.10 M1 ends here. Stage the M1 list of section 4.

### 6.11 `ui/src/audio/voice.ts` (M2)

**The lines touched, so the merge with BF-930's A1 is mechanical:** the prefetch lambda (base :609), the `_prepareServerSpeech` call in `_synthesizeAndPlay` (base :661), the signature of `_prepareServerSpeech` (base :670-674, one parameter line added before `): Promise<PreparedSpeech | null> {`), the `_body` type line (base :683), and five lines added after the `voice_name` block (base :690-692). Untouched: the return object of `_prepareServerSpeech`, `PreparedSpeech`, `_playPreparedSpeech`, `_speakBrowserFallback`, and the 738g gate at :548-589.

**P19.** SEARCH:
```ts
            (sentence) => _prepareServerSpeech(sentence, profile, emotion),
```
REPLACE:
```ts
            (sentence) => _prepareServerSpeech(sentence, profile, emotion, agent_id),
```

**P20.** SEARCH:
```ts
  const prepared = await _prepareServerSpeech(text, profile, emotion);
```
REPLACE:
```ts
  const prepared = await _prepareServerSpeech(text, profile, emotion, agent_id);
```

**P21.** SEARCH:
```ts
async function _prepareServerSpeech(
  text: string,
  profile: VoiceProfile | undefined,
  emotion: string | undefined,
): Promise<PreparedSpeech | null> {
```
REPLACE:
```ts
async function _prepareServerSpeech(
  text: string,
  profile: VoiceProfile | undefined,
  emotion: string | undefined,
  agent_id: string | undefined,
): Promise<PreparedSpeech | null> {
```

**P22.** SEARCH:
```ts
    const _body: { text: string; defer_visemes: boolean; emotion?: string; voice_name?: string } = {
```
REPLACE:
```ts
    const _body: { text: string; defer_visemes: boolean; emotion?: string; voice_name?: string; agent_id?: string } = {
```

**P23.** SEARCH:
```ts
    if (profile && typeof profile.voice_name === 'string' && profile.voice_name.length > 0) {
      _body.voice_name = profile.voice_name;
    }
```
REPLACE:
```ts
    if (profile && typeof profile.voice_name === 'string' && profile.voice_name.length > 0) {
      _body.voice_name = profile.voice_name;
    }
    // AD-738f (#1868): the speaking crew member's id; the server resolves it to a role for a
    // per-role voice (Kokoro) and ignores an id it does not know.
    if (typeof agent_id === 'string' && agent_id.length > 0) {
      _body.agent_id = agent_id;
    }
```

### 6.12 `ui/src/audio/__tests__/voice.perEmotion.test.tsx` (M2, two cases changed in place)

Both cases pass `'counselor'` as `speakResponse`'s `agent_id`, and their exact `toEqual` now sees it.

**P24.** SEARCH:
```ts
    expect(JSON.parse(postBodies[0])).toEqual({
      text: 'hello',
      emotion: 'concerned',
      defer_visemes: true, // BF-918
    });
```
REPLACE:
```ts
    expect(JSON.parse(postBodies[0])).toEqual({
      text: 'hello',
      emotion: 'concerned',
      defer_visemes: true, // BF-918
      agent_id: 'counselor', // AD-738f (#1868): the caller's agent id travels with each sentence
    });
```

**P25.** SEARCH:
```ts
    expect(JSON.parse(postBodies[0])).toEqual({ text: 'hello', defer_visemes: true }); // BF-918
```
REPLACE:
```ts
    // AD-738f (#1868): this case passes the agent id 'counselor', which travels with each sentence.
    expect(JSON.parse(postBodies[0])).toEqual({ text: 'hello', defer_visemes: true, agent_id: 'counselor' }); // BF-918
```

### 6.13 `ui/src/audio/__tests__/voice.agentVoice.test.tsx` (new, M2)

```tsx
/** AD-738f (#1868) S1: each spoken sentence carries the speaking crew member's id, so the server
 *  can give each role its own Kokoro voice. No id, no field; the browser path posts nothing. */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

const AGENT = 'counselor_counselor_0_1a2b3c4d';
const SHA = 'c'.repeat(64);
let speakCalls: any[] = [];
let createdAudios: FakeAudio[] = [];

class FakeUtterance {
  text: string;
  rate = 1; pitch = 1; volume = 1;
  voice: SpeechSynthesisVoice | null = null;
  onstart: (() => void) | null = null;
  onend: (() => void) | null = null;
  constructor(text: string) { this.text = text; }
}

class FakeAudio {
  src: string;
  volume = 1;
  playbackRate = 1;
  preservesPitch = true;
  paused = false;
  pause = vi.fn(() => { this.paused = true; });
  play = vi.fn(async () => {});
  listeners: Record<string, Array<() => void>> = {};
  constructor(src: string) { this.src = src; createdAudios.push(this); }
  addEventListener(ev: string, fn: () => void): void { (this.listeners[ev] ||= []).push(fn); }
}

function installGlobals(): void {
  speakCalls = [];
  createdAudios = [];
  (globalThis as any).SpeechSynthesisUtterance = FakeUtterance;
  (globalThis as any).Audio = FakeAudio;
  (globalThis as any).window = globalThis;
  (globalThis as any).speechSynthesis = {
    cancel: vi.fn(),
    speak: vi.fn((u: any) => speakCalls.push(u)),
    getVoices: () => [],
    addEventListener: vi.fn(),
  };
  if (!(globalThis as any).localStorage) {
    (globalThis as any).localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
  }
}

async function flush(): Promise<void> {
  for (let i = 0; i < 30; i++) await Promise.resolve();
}

function fetchFor(status: Record<string, unknown>) {
  const posts: Array<Record<string, unknown>> = [];
  const mock = vi.fn(async (url: string, init?: { body?: string }) => {
    if (url.endsWith('/api/avatars/tts/status')) return { ok: true, json: async () => status } as any;
    if (url === '/api/avatars/tts') {
      posts.push(JSON.parse(init?.body ?? '{}'));
      return {
        ok: true,
        json: async () => ({ backend: 'kokoro', audio_attachment_id: SHA, mime: 'audio/wav', visemes: [], duration_ms: 1000 }),
      } as any;
    }
    throw new Error(`unexpected fetch to ${url}`);
  });
  return { mock, posts };
}

beforeEach(() => {
  vi.resetModules();
  installGlobals();
});

afterEach(() => {
  vi.restoreAllMocks();
  cleanup();
});

describe('AD-738f speakResponse sends the speaking agent id', () => {
  it('a sentence spoken for an agent carries its id', async () => {
    const { mock, posts } = fetchFor({ enabled: true, backend: 'kokoro', sentence_pipelining_enabled: false });
    (globalThis as any).fetch = mock;
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();

    voiceMod.speakResponse('Good evening, Captain.', undefined, AGENT);
    await flush();

    expect(posts).toEqual([{ text: 'Good evening, Captain.', defer_visemes: true, agent_id: AGENT }]);
    expect(createdAudios.length).toBe(1);
  });

  it('a sentence spoken for no agent carries no agent_id', async () => {
    const { mock, posts } = fetchFor({ enabled: true, backend: 'kokoro', sentence_pipelining_enabled: false });
    (globalThis as any).fetch = mock;
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();

    voiceMod.speakResponse('Good evening, Captain.');
    await flush();

    expect(posts).toEqual([{ text: 'Good evening, Captain.', defer_visemes: true }]);
  });

  it('every pipelined sentence carries the id', async () => {
    const { mock, posts } = fetchFor({ enabled: true, backend: 'kokoro', sentence_pipelining_enabled: true });
    (globalThis as any).fetch = mock;
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();

    voiceMod.speakResponse('First sentence here. Second sentence here.', undefined, AGENT);
    await flush();
    await flush();
    await flush();

    expect(posts.map((p) => p.text)).toEqual(['First sentence here.', 'Second sentence here.']);
    expect(posts.map((p) => p.agent_id)).toEqual([AGENT, AGENT]);
  });

  it('the browser backend posts nothing, even for an agent', async () => {
    const { mock, posts } = fetchFor({ enabled: true, backend: 'browser', sentence_pipelining_enabled: false });
    (globalThis as any).fetch = mock;
    const voiceMod = await import('../voice');
    voiceMod._resetTtsStatusForTests();

    voiceMod.speakResponse('hi', undefined, AGENT);
    await flush();

    expect(posts).toEqual([]);
    expect(mock.mock.calls.filter((c) => c[0] === '/api/avatars/tts').length).toBe(0);
    expect(speakCalls.length).toBe(1);
  });
});
```

### 6.14 `docs/development/roadmap.md` (M2)

**P26.** SEARCH:
```markdown
| AD-738f | Per-agent voice selection (CrewProfile.voice_model + UI selector with license display) — renumbered from AD-738a (Wave 158) | none | 4 |
```
REPLACE:
```markdown
| AD-738f | Per-agent voice selection (CrewProfile.voice_model + UI selector with license display) — renumbered from AD-738a (Wave 158) | [#1868](https://github.com/seangalliher/ProbOS/issues/1868) | 4 |
```

### 6.15 `PROGRESS.md` (M2)

**Re-anchor rule:** three branches (this one, 738g, BF-930/BF-932) add entries at the same spot. At merge time the orchestrator re-anchors P27 on the file's top heading and P28 on whatever is then the newest `DECISIONS.md` entry heading; the inserted text does not change.

**P27.** SEARCH:
```markdown
# ProbOS Progress
```
REPLACE:
```markdown
# ProbOS Progress

**AD-738f S1 (2026-11-27), #1868 -- each crew member speaks with a distinct Kokoro voice.** With `tts.backend: kokoro`, `POST /api/avatars/tts` takes an optional `agent_id`, and the HXI now sends the speaking crew member's id with each sentence (`voice.ts` `_prepareServerSpeech`). The route resolves the id through the agent registry to a role (`agent_type`) and passes the role to the backend only when it resolved one. `KokoroBackend.resolve_voice` picks, first match wins: a per-call `voice_name` that is a catalogue id; the Captain's `tts.kokoro.agent_voices[role]` (new, empty by default, values checked against the 28-voice catalogue when parsed); the built-in `KOKORO_ROLE_VOICES` (15 roles, 15 distinct voices, none the ship's `af_heart`); the ship's `tts.kokoro.voice`. A missing, malformed or unknown id speaks the ship voice; two agents of one role share its voice. Piper and the null backend accept the role and ignore it. Kokoro's per-sentence INFO line ends with `role=<agent_type>`. Off is off: with every new field at its default nothing changes, and a body without `agent_id` makes the same backend call as before. New `tests/test_ad738f_per_agent_voices.py` (11) and `ui/src/audio/__tests__/voice.agentVoice.test.tsx` (4); two cases of `voice.perEmotion.test.tsx`, the config facade field pin and the e2c snapshot updated in place. S2 (the catalogue route, the HXI picker with licences, the AD-718a proposal prompt) stays open on #1868. Contract `prompts/ad-738f-s1-per-agent-kokoro-voices.md`.
```

### 6.16 `DECISIONS.md` (M2)

**P28.** SEARCH (the newest entry in this tree; re-anchor at merge per 6.15):
```markdown
### AD-738g S1 -- a local Kokoro voice: a resident worker in the operator's venv, keyed into the BF-918 voice service (2026-11-27, #1662)
```
REPLACE:
```markdown
### AD-738f S1 -- a distinct Kokoro voice per crew role: the route resolves the speaker's role through the registry; a built-in table and a Captain override per role (2026-11-27, #1868)

- *Scope.* #1868 slice S1. `audio/tts/backends.py`, `null_backend.py`, `piper_backend.py`, `kokoro_backend.py` (`KOKORO_ROLE_VOICES`, `resolve_voice`), `config_models/experience.py` (`KokoroTTSConfig.agent_voices`), `routers/avatars.py` (`agent_id`), `ui/src/audio/voice.ts`. Contract `prompts/ad-738f-s1-per-agent-kokoro-voices.md`.
- *D1.* The client sends the agent's registry id; the server resolves the role with `runtime.registry.get(id).agent_type`. Not the client (the registry is the authority), and not a parse of the id string (a second source of role).
- *D2.* `TTSBackend.synthesize` gains `agent_type: str | None = None`; the route passes it only when a role was resolved, so a body without an id makes the same call as before.
- *D3.* The default voice is keyed by role, so it survives restarts and roster changes; two agents of one role share a voice, and a role in no map speaks the ship voice.
- *D4.* `agent_voices` keys are checked for shape, not against the 15 roles: a new crew type must be nameable. A misspelt role changes nothing and shows on the per-sentence log line (`role=`, `voice=`).
- *Precedence.* Per-call catalogue `voice_name`, then `agent_voices[role]`, then `KOKORO_ROLE_VOICES[role]`, then `tts.kokoro.voice`.
- *Reversal.* Revert both commits; nothing persisted changes. A leftover `agent_voices` block in `system.yaml` is then ignored (`KokoroTTSConfig` ignores unknown keys).

### AD-738g S1 -- a local Kokoro voice: a resident worker in the operator's venv, keyed into the BF-918 voice service (2026-11-27, #1662)
```

## 7. Consumers

| Contract | Consumer | After the change |
|---|---|---|
| `TTSBackend.synthesize(..., agent_type=None)` | the route (`avatars.py`:282) | passes `agent_type` only when resolved (P16) |
| | the 11 test stand-ins of D2 | unchanged; no case of theirs posts `agent_id` |
| `KokoroBackend.resolve_voice(voice_override, agent_type=None)` | `KokoroBackend.synthesize` only (Absence Verified) | positional call shape of 738g still valid (V2) |
| Kokoro INFO line | `test_ad738g_kokoro_voice.py`:422-423 (substrings); the Captain reading the log | both substrings still match; `role=` appended |
| `POST /api/avatars/tts` body `agent_id` | `voice.ts` `_prepareServerSpeech` (P19-P23) | sent whenever `speakResponse` got an agent id |
| | `voice.perEmotion.test.tsx`:108, :126 (exact `toEqual`, agent `'counselor'`) | updated in place (P24, P25) |
| | `voice.prefetch.bf918`, `voice.pipelining`, `voice.balancedEnd` | read only `body.text`; unaffected |
| `KokoroTTSConfig.agent_voices` | config facade baseline, config reference, e1 pin, e2c snapshot | regenerated / updated (6.7, 6.9) |
| | `test_ad738g_kokoro_voice.py::test_c1` (`TTSConfig().kokoro == KokoroTTSConfig()`) | still equal |
| `agent_type` values | `voice_profile_defaults.DEFAULT_VOICE_PROFILES` keys | V1 pins the table's keys to them |

## 8. Gates (the orchestrator runs all of them)

### 8.1 Oracle tree, before the Builder starts
- Each SEARCH of section 6 counted at its turn: 1 each; the two new test files do not exist.
- **A/B on the merged base** (the new files and P17, P18, P24, P25 without the source pairs): `test_ad738f_per_agent_voices.py` fails at import (`KOKORO_ROLE_VOICES`), all 11. Vitest: `voice.agentVoice` cases 1 and 3 fail (no `agent_id`), 2 and 4 pass (off-is-off guards, by design); both changed `voice.perEmotion` cases fail. On the candidate all pass.

### 8.2 Focused checks on the candidate
```text
d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad738f_per_agent_voices.py tests/test_ad738g_kokoro_voice.py tests/test_ad738_piper_tts.py tests/test_bf291_piper_voice_catalog.py tests/test_ad738e_1_per_emotion_prosody.py tests/test_ad1025_path_anchoring.py tests/test_bf918_tts_latency.py tests/test_bf918_tts_retention.py tests/test_bf930_speech_defers_idle_dream.py tests/test_bf930_voice_path_timing.py tests/test_ad1071_tts_pipelining.py tests/test_ad721e_animation_manifest.py tests/test_ad721b1_rhubarb_backend.py tests/test_ad1270e1_config_facade.py tests/test_ad1270e2c_experience_models.py tests/test_bf_codebase_index_config_models.py -n 0 -q
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_facade.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/gen_config_reference.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/check_config_profiles.py --check
(cd ui) npx vitest run src/audio/__tests__/voice.agentVoice.test.tsx src/audio/__tests__/voice.perEmotion.test.tsx src/audio/__tests__/voice.kokoroGate.test.tsx src/audio/__tests__/voice.serverTts.test.tsx src/audio/__tests__/voice.pipelining.test.tsx src/audio/__tests__/voice.prefetch.bf918.test.tsx src/audio/__tests__/voice.balancedEnd.test.tsx src/audio/__tests__/voice.test.ts src/audio/__tests__/voice.arbiter.test.ts src/audio/__tests__/voice.testGate.test.tsx src/audio/__tests__/voiceChunking.test.ts src/__tests__/voice.test.ts src/components/profile/__tests__/ProfileChatTab.bf918.test.tsx src/__tests__/CrewVRM.mouthClock.bf931.test.tsx
(cd ui) npx tsc -b
d:/ProbOS/.venv/Scripts/python.exe -P scripts/gen_ad_ledger.py --check
d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --preflight-only --label ad-738f-s1
```
The Python list is the `rg` census of tests that import `probos.audio.tts` or the avatars router, plus the two config-facade files and the config-model scanner. The Vitest list is every file that posts to `/api/avatars/tts` plus the `voice.ts` core suites. Retriage a parallel failure at `-n 0`.

### 8.3 Mutation rows (one at a time, file restored byte for byte)

Each locator is a whole stripped line of the candidate, unique in its file.

| ID | File | Line (stripped) | Becomes | Killed by |
|---|---|---|---|---|
| M1 | kokoro_backend.py | `return KOKORO_ROLE_VOICES[agent_type]` | `return self._config.voice` | V2, V3, B1, T1 |
| M2 | kokoro_backend.py | `if agent_type in self._config.agent_voices:` | `if False:` | V2, V3, T2 |
| M3 | kokoro_backend.py | `if voice_override is not None and voice_override in KOKORO_VOICES:` | `if voice_override is not None and voice_override in KOKORO_VOICES and agent_type is None:` | V2 |
| M4 | kokoro_backend.py | `voice = self.resolve_voice(voice_override, agent_type)` | `voice = self.resolve_voice(voice_override)` | B1, T1, T2 |
| M5 | kokoro_backend.py | `"ok" if wav is not None else "degraded", agent_type or "-",` | `"ok" if wav is not None else "degraded", "-",` | B1 |
| M6 | kokoro_backend.py | `"counselor": "af_bella",` | `"counselor": "af_heart",` | V1, B1, T1 |
| M7 | avatars.py | `if isinstance(agent_id, str) and agent_id.strip() and len(agent_id) <= 128:` | the same with `<= 4096` | T3 |
| M8 | avatars.py | `role_kwargs: dict[str, str] = {} if agent_type is None else {"agent_type": agent_type}` | `role_kwargs: dict[str, str] = {}` | T1, T4 |
| M9 | avatars.py | same line | `role_kwargs = {"agent_type": agent_type}` | T4 (the pre-role stand-in gets `agent_type=None` and raises `TypeError`, which the route re-raises) |
| M10 | experience.py | `agent_voices: dict[str, KokoroVoiceId] = Field(default_factory=dict)` | `agent_voices: dict[str, str] = Field(default_factory=dict)` | C1 |
| M11 | experience.py | `if not _ROLE_NAME.fullmatch(role):` | `if False:` | C1 |
| M12 | voice.ts | `_body.agent_id = agent_id;` | `// removed` | agentVoice 1 and 3, perEmotion 1 and 2 |
| M13 | voice.ts | `(sentence) => _prepareServerSpeech(sentence, profile, emotion, agent_id),` | the same without `, agent_id` | agentVoice 3 |
| M14 | voice.ts | `const prepared = await _prepareServerSpeech(text, profile, emotion, agent_id);` | the same without `, agent_id` | agentVoice 1, perEmotion 1 and 2 |

### 8.4 The gate
`d:/ProbOS/.venv/Scripts/python.exe scripts/run_test_gate.py --label ad-738f-s1 --receipt logs/gates/ad-738f-s1.receipt.json` once on the committed head, after the base merge (batched per the orchestrator's rules if it rides with other issues).

## 9. Diff Reviewer: properties to verify

The change claims that a sentence spoken for a crew member reaches the Kokoro worker in that member's role voice, that the Captain can override a role's voice in config, and that the default config and Piper are unchanged (selecting Kokoro turns the role table on by design). The consumers that must accept it: `KokoroBackend.synthesize` through `POST /api/avatars/tts`, and every existing `TTSBackend` stand-in.
1. The route reads `agent_id` only as a non-blank `str` of at most 128 characters, resolves it only through `runtime.registry.get`, and never raises or returns an error status for a bad or unknown id.
2. The backend call is byte-identical to the base when no role resolves (no `agent_type` keyword); with a role it adds exactly `agent_type=<str>`.
3. `resolve_voice` applies exactly the precedence of section 2; `KOKORO_ROLE_VOICES` has 15 distinct catalogue ids, none `af_heart`, and is read-only.
4. `agent_voices` defaults to an empty dict per instance; its values are catalogue ids and its keys role-shaped, both checked at parse time.
5. Piper's request to the voice service is identical with and without `agent_type`; the null backend still returns `None`.
6. The Kokoro log line keeps every field of 738g in its order and appends only `role=`; no agent id is logged anywhere.
7. `voice.ts` adds `agent_id` to the body only when a non-empty id was passed, at both call sites; the return object, `_playPreparedSpeech`, `_speakBrowserFallback` and the 738g gate are untouched; the browser path still makes no POST.
8. Only the named files change; the config pin moves by exactly the printed `fields=`.

## 10. Verified Against Codebase (2026-11-27, tree `e26cc9eb`)

```text
grep -n "class TTSBackend\|async def synthesize\|voice_model`` silently" src/probos/audio/tts/backends.py
  22: class TTSBackend(Protocol):   33: async def synthesize(   49: back to the configured ``tts.voice_model`` silently.
grep -n "del emotion, voice_override" src/probos/audio/tts/null_backend.py
  30: del emotion, voice_override
grep -n "async def synthesize\|no point invoking\|_resolve_binary_path(self._binary_path)\|_service.synthesize" src/probos/audio/tts/piper_backend.py
  137: async def synthesize(   159: ``None`` (no point invoking ...)."""   162: binary = _resolve_binary_path(self._binary_path)   229: wav_bytes = await self._service.synthesize(key, text, self._timeout_seconds)
grep -n "KOKORO_VOICES\|SPEED_M\|def resolve_voice\|self.resolve_voice\|AD-738g: kokoro voice=" src/probos/audio/tts/kokoro_backend.py
  34: KOKORO_VOICES: frozenset[str] = ...   36-37: SPEED_MIN/SPEED_MAX   56: def resolve_voice(self, voice_override: str | None) -> str:   93: voice = self.resolve_voice(voice_override)   106: "AD-738g: kokoro voice=%s speed=%.2f chars=%d synth_ms=%.0f result=%s",
grep -n "^from\|^import\|KokoroVoiceId\|class KokoroTTSConfig\|timeout_seconds: float = Field(default=30.0, gt=0.0)" src/probos/config_models/experience.py
  8, 10, 12: imports (no re, no field_validator)   623: KokoroVoiceId = Literal[   633: class KokoroTTSConfig   652: voice: KokoroVoiceId = "af_heart"   664: timeout_seconds
grep -n "voice_name = None\|BF-918 (#1626): a client that asks\|backend.synthesize(" src/probos/routers/avatars.py
  258, 263: voice_name = None   265: # BF-918 (#1626): a client that asks ...   282: result = await backend.synthesize(text, emotion=emotion, voice_override=voice_name)
grep -n "def register\|def get(" src/probos/substrate/registry.py      29: async def register (reads id, agent_type, pool)   58: def get(self, agent_id)
grep -n "agent_type: str" src/probos/substrate/agent.py                32: agent_type: str = "base"
grep -n "Format:" src/probos/substrate/identity.py                     20: Format: ``{agent_type}_{pool_name}_{index}_{hash8}``
grep -n "self.registry = AgentRegistry()" src/probos/runtime.py        691
grep -n "VoiceProfile(voice_name=\"\"" src/probos/voice_profile_defaults.py   21-40 (15 roles, archetype comments)
grep -n "^    (tts|lipsync|attachments):" src/probos/config.py         4024, 4026, 4027
grep -n "_prepareServerSpeech\|const _body\|_body.voice_name\|export function speakResponse" ui/src/audio/voice.ts
  370: export function speakResponse(   609: (sentence) => _prepareServerSpeech(sentence, profile, emotion),   661: const prepared = await _prepareServerSpeech(text, profile, emotion);   670: async function _prepareServerSpeech(   683: const _body: {...}   691: _body.voice_name = profile.voice_name;
grep -n "speakResponse(" ui/src/components/profile/ProfileInfoTab.tsx ui/src/components/IntentSurface.tsx ui/src/components/profile/ProfileChatTab.tsx ui/src/audio/useMeetingVoice.ts
  ProfileInfoTab.tsx:506 (agent.id)   IntentSurface.tsx:477-478 (spoken.agent_id)   ProfileChatTab.tsx:1189-1190 (requestAgentId)   useMeetingVoice.ts:158 (agentId)
grep -n "toEqual\|speakResponse(" ui/src/audio/__tests__/voice.perEmotion.test.tsx   103, 108, 121, 126
grep -n "VOICES: tuple\|frames = " tests/fixtures/fake_kokoro_worker.py   23: ("af_heart", "af_bella", "bf_emma", "bm_fable", "am_liam")   63: frames = int(RATE * 0.05 * (1 + index))
grep -n "en-gb" scripts/kokoro_worker.py                               59: return "en-gb" if voice.startswith("b") else "en-us"
grep -n "AD-738g: kokoro voice=\|result=ok" tests/test_ad738g_kokoro_voice.py   422, 423
grep -n "field_definitions\|names=311" tests/test_ad1270e1_config_facade.py   1581: == 1885   1827: "names=311" in proc.stdout
grep -n "'timeout_seconds': 30.0}}," tests/test_ad1270e2c_experience_models.py   217
grep -n "names=\|models=" scripts/check_config_facade.py               1785-1787 (models= is own_models)
grep -n "^| AD-738f" docs/development/roadmap.md                       826
grep -n "^# ProbOS Progress" PROGRESS.md                               1
grep -n "^### AD-738g S1" DECISIONS.md                                 13 (newest entry)
```

### Absence Verified (2026-11-27)

```text
CLAIM: the route reads no agent identity today
RUN:   Grep "agent_id|agent_type|registry" src/probos/routers/avatars.py
FOUND: nothing                                                     HOLDS: yes
CLAIM: no TTS backend knows a role today
RUN:   Grep "agent_type|agent_voices|role" src/probos/audio/tts
FOUND: kokoro_backend.py:60 (a docstring naming this AD)           HOLDS: yes
CLAIM: nothing outside the backend calls resolve_voice
RUN:   Grep "resolve_voice" (repo, excluding prompts/)
FOUND: kokoro_backend.py:56, :93 only (the other hits are _resolve_voice_model / resolve_voices_dir)   HOLDS: yes
CLAIM: no existing test posts agent_id to /api/avatars/tts
RUN:   Grep "agent_id" over the 8 route test files (bf930 x2, bf918 x2, bf291, ad738e_1, ad738, ad1071)
FOUND: nothing                                                     HOLDS: yes (test_ad738g has no agent_id either)
CLAIM: _prepareServerSpeech has two callers and no test reaches it directly
RUN:   Grep "_prepareServerSpeech|_synthesizeAndPlay" ui/src
FOUND: voice.ts only (:609, :661 call it)                          HOLDS: yes
CLAIM: no source scan pins voice.ts or the changed Python files
RUN:   Grep "voice\.ts\?raw|readFileSync\(.*voice" ui/src; Grep "(avatars|kokoro_backend|null_backend|piper_backend|backends)\.py...read_text|getsource(..." tests
FOUND: nothing (one comment in test_bf918_attachment_io.py:134)    HOLDS: yes
CLAIM: the Kokoro fields are not in the settings registry (S1 adds none)
RUN:   Grep "kokoro" src/probos/settings
FOUND: section_registry.py:275 (the backend enum only)             HOLDS: yes
CLAIM: config.py re-exports experience names explicitly, so `import re` there changes no facade count
RUN:   Grep "config_models.experience import" src/probos/config.py; Grep "Kokoro" src/probos/config_models/__init__.py
FOUND: config.py:42 explicit list; __init__.py:36 explicit list    HOLDS: yes
```

## 11. What this does NOT change

S2: the catalogue route `GET /api/avatars/tts/voices` for Kokoro, the HXI picker with licences, and the AD-718a proposal prompt. Piper per-role defaults. The browser voice path (no POST on `browser`). The settings registry. Voice cloning, the GPU, the remote or LAN backend, timing-derived lip-sync (#1662 S3), a Kokoro-to-Piper fallback chain. The client's pitch, rate and volume handling. `SetVoiceProfileRequest` and the voice-profile PUT (the issue's "Not examined" language note stays a separate question). `config/system.yaml`.

## 12. Issue text (#1868, on merge; the issue stays open for S2)

Comment, ending `Refs #1868` and no closing keyword:
> **S1 merged** (`<sha>`, contract `prompts/ad-738f-s1-per-agent-kokoro-voices.md`). With `tts.backend: kokoro`, each crew role speaks with its own voice: counselor `af_bella`, security_officer `am_fenrir`, diagnostician `am_michael`, pathologist `bf_emma`, surgeon `af_sarah`, pharmacist `af_kore`, architect `af_nicole`, data_analyst `af_nova`, research_specialist `af_aoede`, systems_analyst `bf_isabella`, scout `am_puck`, builder `bm_george`, engineering_officer `bm_lewis`, operations_officer `bm_fable`, training_officer `am_liam`. The Captain overrides any role in `system.yaml` (`tts.kokoro.agent_voices`). Precedence: per-call catalogue `voice_name`, the override, the table, `tts.kokoro.voice`. An unknown id speaks the ship voice unless the sentence carries a catalogue `voice_name`; two agents of one role share a voice. Selecting Kokoro turns the role table on even with no override. A role key containing secret, token, password, api_key or private_key is refused when parsed (the config API would hide it). Acceptance 1-6 of this issue: met for S1 (tests `tests/test_ad738f_per_agent_voices.py`, `ui/src/audio/__tests__/voice.agentVoice.test.tsx`). **Open: S2** (catalogue route, picker with licences, proposal prompt).

### 12.1 What the Captain does by hand, and what the orchestrator checks first

- **Captain:** the AD-738g steps (run `scripts/kokoro-fetch.ps1`, set `tts.backend: kokoro`, restart). Nothing more is required. Optional, after listening: a block such as
  ```yaml
  tts:
    kokoro:
      agent_voices:
        training_officer: am_michael   # example only; audition am_liam (D) and bm_lewis (D+) first
  ```
- **Orchestrator, before the Captain:** each of the 15 table voices is a key of the real `voices-v1.0.bin` (already shown for all 28 on 738g: `28 []`); one `POST /api/avatars/tts` with a real counselor's id against the real worker on the live vessel logs `AD-738g: kokoro voice=af_bella ... result=ok role=counselor`; one with no id logs `voice=af_heart ... role=-`.

## 13. Prior art and blind spots

- **Internal:** AD-718 seeds per-role pitch and rate (`voice_profile_defaults.py`) by the same `agent_type` key: absorbed (role keying, archetype genders). BF-291's per-call `voice_name` flow: kept as precedence 1. AD-718a proposals (`voice/proposal.py`:34, a free string): a non-catalogue name is ignored, as 738g already does. AD-738g D6 reserved the Protocol keyword and `resolve_voice` as the one place: followed.
- **External:** hexgrad/Kokoro-82M VOICES.md (https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md, fetched 2026-11-27) for the grades behind D8: absorbed. Wider search skipped: mapping a speaker id to a voice id is ProbOS plumbing with no design question an outside project settles. `docs/research/reference-projects.md`: the Kokoro row was last reviewed 2026-11-27 (today), not overdue; no other row was checked (considered, deferred).
- **Blind spots:** (a) two agents of one role share a voice (D6; the per-agent answer is S2's picker through `voice_name`). (b) The client still applies each profile's pitch and rate to the server audio, so AD-718's seeds stack on the Kokoro voice; unchanged. (c) The Captain's own narration (`IntentSurface.tsx`:511, no agent id) speaks the ship voice, by design. (d) An agent removed mid-reply resolves no role for its later sentences, which then speak the ship voice; rare and harmless. (e) A typo in `agent_voices` is silent but visible on the log line (D4). (f) The resident worker serves every voice from one process (`kokoro_backend.py`:6-7), so a per-sentence voice change costs no restart.

## 14. Acceptance criteria

1. With `tts.backend: kokoro`, 15 crew roles speak with 15 distinct voices out of the box, and a role keeps its voice across restarts and roster changes (V1, V4, T1).
2. A Captain override for one role changes that role's voice and no other (V3, T2).
3. A missing, malformed or unknown agent id, role or voice never fails a request: the ship voice speaks, absent a catalogue per-call `voice_name` (V2, T3, B2).
4. Off is off: the default config changes nothing (selecting Kokoro turns the role table on, by design); a body without `agent_id` makes the same backend call (T4); Piper's request is the same with a role (P1); the browser path makes no POST (agentVoice 4).
5. The seam: `POST /api/avatars/tts` with an agent id resolves the role's voice, the real worker line carries it, the audio is stored under its hash, and the response reports `kokoro` (T1, T2).
6. Every mutation row of 8.3 is killed; the A/B of 8.1 holds.

## 15. Amendment A1: review round 1 repairs (2026-11-27)

**Revised by:** `claude-architect` (Claude Code, Opus 5.5), 2026-11-27. Source: `review-738f-r1.md` (Diff Reviewer `gpt-6.1-sol`, candidate `f573a703`).

**Base and order.** The batch branch at `f573a703`; CRLF working copies, LF blocks. Apply the AD-738g contract's section 16 first (G1 to G11 and the combined GF1 to GF3), then F1 to F4 here. **Combined pairs, text in the AD-738g contract section 16 only:** GF1 (the `is_secret_field_id` import in `experience.py`), GF2 (`_keys_are_role_names` refuses a secret-shaped key, beside 738g's path validator), GF3 (`KokoroBackend.synthesize` treats a non-string role, voice or emotion as none, beside 738g's early-INFO and path-guard restructure). One repair commit covers both sections (subject and staging list in the AD-738g contract, section 16).

**Tests (A1, this slice):** 2 new in `tests/test_ad738f_per_agent_voices.py` (C2, B2); 1 changed in place (V3, reason inline); 0 removed. The file goes from 11 to 13 tests.

### 15.1 Decisions, finding by finding

| # | Finding | Decision | Reason |
|---|---|---|---|
| 1 | P2: a role key matching AD-741's secret rule (`tts.kokoro.agent_voices.secretary`) is redacted on read and makes a POST fail whole | **Fix at parse time (GF1, GF2): refuse such a key, with a message saying why.** Leave the redaction code alone | No current role contains the five words (the orchestrator's `agent_type` enumeration over `src`, and C2 asserts it for the 15 table roles). The reviewer's fix would change three paths of shared redaction code (`routers/config.py`:87, :103-104, :277-286) so that it tells dictionary keys from field names: a change to a security control's matching rule, outside the TTS scope, with its own tests (`test_ad741_config_api.py`). Narrowing D4 for names holding one of five words costs nothing today, weakens no control, and is within the envelope. The general case is AD-738g contract follow-up 4 |
| 2 | P3: "defaults change nothing" and "unknown id selects the ship voice" are overstated | **Fix the claims, documentation only.** Corrected in place here (scope line, section 9, issue text, acceptance 3 and 4) and in the tree by F3 (`PROGRESS.md`) and F4 (`DECISIONS.md` D3). P27's text in 6.15 is history; F3 supersedes its two sentences | Selecting Kokoro activates the role table with `agent_voices: {}`; a catalogue `voice_name` beats the ship voice for an unknown id. No flag |
| 3 | P4: "six" male roles, the table has seven | **Fix** in D8 (corrected in place). No code comment carries the count (Grep `six male|seven male`: the contract only) | Count |
| 4 | P3 injected-only: a non-string `agent_type` raises `TypeError` before synthesis | **Fix inside GF3** (no extra pair): the role, the per-call voice and the emotion are each `None` unless a `str`; B2 tests it | GF3 already rewrites the start of `synthesize`; the three normalisations are one line each and make "NEVER raises" true for every argument type |
| 5 | P4 injected-only: V3 passes over an empty table | **Fix (F2.1):** V3 asserts the table holds 15 roles before it loops | Test-only |

**The reviewer's "M1-M14 do not cover" list.** Config read/write redaction: introduced by finding 1's repair, so C2 tests it through the API's own predicate and row M15 targets it. Invalid backend role types: introduced by finding 4's repair, so B2 tests it and row M16 targets it. Registry-key provenance, exact length-128 acceptance, registry authority with an id-prefix mismatch, and later prefetch refills and queued speakers: the reviewer executed each and found it correct (its section 9 items 1 and 7); A1 changes none of that code, so no row is added. M7's `<= 4096` mutant stays the bound's row; a `< 128` mutant would survive T3 and is a recorded gap, not a defect.

### 15.2 The pairs

**F1.** None: the import is GF1 (AD-738g contract, section 16), listed here so the id sequence is whole.

**F2.** `tests/test_ad738f_per_agent_voices.py`.

F2.1 (V3, changed in place: it now proves its premise; the reviewer showed it passed over an empty table). SEARCH:
```python
    plain = KokoroBackend(KokoroTTSConfig())
    custom = KokoroBackend(KokoroTTSConfig(agent_voices={"counselor": "af_sky"}))

    for role, voice in KOKORO_ROLE_VOICES.items():
```
REPLACE:
```python
    plain = KokoroBackend(KokoroTTSConfig())
    custom = KokoroBackend(KokoroTTSConfig(agent_voices={"counselor": "af_sky"}))

    assert len(KOKORO_ROLE_VOICES) == 15  # A1: the loop below proves nothing over an empty table
    for role, voice in KOKORO_ROLE_VOICES.items():
```

F2.2 (C2, new, after C1). SEARCH:
```python
    assert parsed.tts.kokoro.agent_voices == {"counselor": "bf_lily"}
    assert SystemConfig().tts.kokoro.agent_voices == {}
```
REPLACE:
```python
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
```

F2.3 (B2, new, after B1). SEARCH:
```python
    assert "AD-738g: kokoro voice=af_bella speed=1.00 chars=6" in caplog.text
    assert "result=ok role=counselor" in caplog.text
    assert "result=ok role=-" in caplog.text
```
REPLACE:
```python
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
```

**F3.** `PROGRESS.md`, the AD-738f S1 paragraph (line 3). Tracker exception to "starts at the beginning of a line": each SEARCH is a substring occurring once in the file (counted).
- SEARCH:
  ```markdown
  A missing, malformed or unknown id speaks the ship voice; two agents of one role share its voice.
  ```
  REPLACE:
  ```markdown
  A missing, malformed or unknown id resolves no role, so the sentence speaks the ship voice unless its per-call `voice_name` is a catalogue id; two agents of one role share its voice. A role key containing secret, token, password, api_key or private_key is refused when parsed, because the config API would hide it.
  ```
- SEARCH:
  ```markdown
  Off is off: with every new field at its default nothing changes, and a body without `agent_id` makes the same backend call as before.
  ```
  REPLACE:
  ```markdown
  The default config (`tts.backend: browser`) and Piper are unchanged, and a body without `agent_id` makes the same backend call as before; selecting `tts.backend: kokoro` turns the built-in role table on even with `agent_voices: {}`, so a vessel already set to Kokoro hears each crew role in its own voice instead of the ship voice.
  ```
- SEARCH `` `tests/test_ad738f_per_agent_voices.py` (11) `` REPLACE `` `tests/test_ad738f_per_agent_voices.py` (13) ``

**F4.** `DECISIONS.md`, the AD-738f S1 entry (lines 18-19, whole lines). SEARCH:
```markdown
- *D3.* The default voice is keyed by role, so it survives restarts and roster changes; two agents of one role share a voice, and a role in no map speaks the ship voice.
- *D4.* `agent_voices` keys are checked for shape, not against the 15 roles: a new crew type must be nameable. A misspelt role changes nothing and shows on the per-sentence log line (`role=`, `voice=`).
```
REPLACE:
```markdown
- *D3.* The default voice is keyed by role, so it survives restarts and roster changes; two agents of one role share a voice, and a role in no map speaks the ship voice unless the sentence carries a catalogue `voice_name`. Selecting `tts.backend: kokoro` turns the role table on even with `agent_voices: {}`.
- *D4.* `agent_voices` keys are checked for shape, not against the 15 roles: a new crew type must be nameable. A misspelt role changes nothing and shows on the per-sentence log line (`role=`, `voice=`). A key containing secret, token, password, api_key or private_key is refused when parsed, because the config API (AD-741) would hide it on read and refuse it on write; the redaction rule itself is unchanged.
```

### 15.3 Regenerations and checks

As the AD-738g contract, section 16.3 (one run for the batch). A1 adds no field: the `field_definitions` pin of 6.9 (P18) keeps its value; the 6.9 merge-order rule for BF-932 is unchanged.

### 15.4 Mutation rows (A1; one at a time on the frozen A1 candidate)

| ID | File | Line (stripped) | Becomes | Killed by |
|---|---|---|---|---|
| M4 (restated: GF3 rewrote the line) | kokoro_backend.py | `voice = self.resolve_voice(override, role)` | `voice = self.resolve_voice(override)` | B1, T1, T2 |
| M5 (restated) | kokoro_backend.py | `"ok" if wav is not None else "degraded", role or "-",` | `"ok" if wav is not None else "degraded", "-",` | B1 |
| M15 | experience.py | `if is_secret_field_id(role):` | `if False:` | C2 |
| M16 | kokoro_backend.py | `role = agent_type if isinstance(agent_type, str) else None` | `role = agent_type` | B2 (unhashable `TypeError`) |
| M17 | kokoro_backend.py | `override = voice_override if isinstance(voice_override, str) else None` | `override = voice_override` | B2 |
| M18 | kokoro_backend.py | `MappingProxyType({` ... the whole table | `MappingProxyType({})` | V1, V3 (A1: V3 now fails on its own) |

**Rerun from M1-M14.** `kokoro_backend.py`, `experience.py` and the test file change in A1: rerun M1 to M6, M10 and M11. M7 to M9 (`avatars.py`) and M12 to M14 (`voice.ts`) keep their earlier results: neither file nor their killing tests change. The A1 campaign, with each file's sha256 recorded, is the campaign of record for A1.

### 15.5 Section 9 after A1

Item 4 now also reads "and keys the AD-741 secret rule matches are refused" (C2, M15). Items 1-3 and 5-8 are unchanged in wording; item 6's "no agent id is logged" still holds (GF3 logs `role or "-"`). Item 2 (call shape) is untouched: the route is not edited.

### 15.6 Verified Against Codebase (A1, 2026-11-27, tree `f573a703`)

```text
grep -n "_SECRET_RE = \|def is_secret_field_id\|terminal = field_id.rsplit" src/probos/settings/section_registry.py   508, 511, 518
grep -n "is_secret_field_id" src/probos/routers/config.py                    44 (import), 87 (JSON redaction), 103 (YAML scrub), 277 (POST refusal)
grep -n "agent_voices: dict\|def _keys_are_role_names\|_ROLE_NAME = " src/probos/config_models/experience.py   672, 682, 634
grep -n "if agent_type in self._config.agent_voices\|role=%s\|agent_type or \"-\"" src/probos/audio/tts/kokoro_backend.py   92, 145, 147
grep -n "def test_v3_\|for role, voice in KOKORO_ROLE_VOICES.items\|SystemConfig().tts.kokoro.agent_voices\|result=ok role=-" tests/test_ad738f_per_agent_voices.py   114, 118, 161, 183
grep -n "unknown id speaks the ship voice\|Off is off: with every new field\|test_ad738f_per_agent_voices.py\` (11)" PROGRESS.md   3
grep -n "^- \*D3\.\* The default voice is keyed by role\|^- \*D4\.\* \`agent_voices\` keys" DECISIONS.md   18, 19
```

Absence Verified (A1):
```text
CLAIM: no current crew role contains secret, token, password, api_key or private_key
RUN:   the orchestrator's Grep -i -E 'agent_type\s*[:=]\s*["'][a-z0-9_]*(secret|token|password|api_key|private_key)' src; C2 asserts it for the 15 table roles
FOUND: nothing                                                         HOLDS: yes
CLAIM: no code comment states the male-role count
RUN:   Grep "six male|seven male" (repo)
FOUND: this contract only (D8)                                         HOLDS: yes
CLAIM: the overstated claims live only in PROGRESS.md:3, DECISIONS.md:18 and this contract
RUN:   Grep "byte-identical to AD-738g|nothing changes, and a body|unknown id speaks the ship voice|ship voice" over PROGRESS.md, DECISIONS.md, roadmap.md, src/probos/audio/tts, experience.py, avatars.py, voice.ts, the 738f test file
FOUND: PROGRESS.md:3; DECISIONS.md:18; contract lines 8, 1170, 1253, 1276, 1277 (code docstrings say "a role in neither map", which is exact)   HOLDS: yes
```
7. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
