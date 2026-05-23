"""AD-705c (Wave 179) — Voice (wake-word training) API router.

Three ``require_crew_scope`` endpoints back the AD-705c
``WakeWordTrainerPanel`` HXI surface:

- ``POST /api/voice/wake-word/sample`` — accepts a single WAV utterance;
  stored under ``data/wake-word/training-samples/positive/<sha>.wav``.
- ``POST /api/voice/wake-word/train`` — spawns a background training
  task. Reference held in ``runtime._wake_word_trainer_tasks`` per the
  async-discipline rule.
- ``GET /api/voice/wake-word/training-status?job_id=...`` — progress
  query for the spawned task.

Privacy posture: training audio never leaves the local runtime.
Endpoints honest-degrade 503 when ``wake_word.wake_word_trainer_enabled``
is False.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from probos.routers.auth import require_crew_scope
from probos.routers.deps import get_runtime
from probos.voice.wake_word_trainer import WakeWordTrainer, WakeWordTrainingReport
# BF-301: resolve_whisper_model_path no longer used; the browser owns
# model fetch via transformers.js. Import retained as a forward-marker
# comment for the air-gapped-operator follow-up AD.
# from probos.voice.whisper_model import resolve_whisper_model_path

logger = logging.getLogger("probos.routers.voice")

router = APIRouter(prefix="/api/voice", tags=["voice"])


@router.get("/health")
async def get_voice_health(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """BF-301 (#775, supersedes AD-826) — STT engine availability for the
    UI PTT handler.

    The browser-side STT engine is now @huggingface/transformers Whisper
    running in a Web Worker. The runtime no longer hosts ONNX weights —
    the browser fetches them from HF CDN on first use and caches them.
    This endpoint reports the operator's intent (primary_stt) and
    whether the local-first path is enabled (offline_stt_enabled). It
    does NOT probe the browser-to-CDN reachability — that is browser-
    side responsibility, surfaced through the BF-301
    ``onTransformersProgress`` channel.

    Response shape (back-compat with BF-294 / AD-826 UI, plus ``model``)::

        {
          "primary_stt": "transformers" | "whisper" | "browser",
          "engine": "transformers" | "browser",
          "backend_available": bool,
          "healthy": bool,
          "model": str | None,
        }

    Engine semantics:
    * ``primary_stt`` is the raw operator config value.
    * ``engine`` is the resolved value: ``"whisper"`` (deprecated alias)
      resolves to ``"transformers"``; ``"browser"`` passes through.
    * ``backend_available`` is True iff the resolved engine is
      ``"transformers"`` AND ``offline_stt_enabled`` is True.
    * ``healthy`` is True iff ``backend_available`` is True OR resolved
      engine is ``"browser"``.
    * ``model`` is the configured transformers model id when the
      resolved engine is ``"transformers"``; ``None`` for ``"browser"``.
    """
    config = runtime.config
    primary = config.cognitive.primary_stt
    offline_enabled = bool(config.cognitive.offline_stt_enabled)
    # Resolve deprecated "whisper" alias to "transformers".
    resolved_engine = "transformers" if primary in ("transformers", "whisper") else "browser"
    backend_available = resolved_engine == "transformers" and offline_enabled
    healthy = backend_available or resolved_engine == "browser"
    model = config.cognitive.transformers_model if resolved_engine == "transformers" else None
    return {
        "primary_stt": primary,
        "engine": resolved_engine,
        "backend_available": backend_available,
        "healthy": healthy,
        "model": model,
    }


_WAV_MAGIC = b"RIFF"


def _trainer_jobs(runtime: Any) -> dict[str, dict[str, Any]]:
    """Return the in-memory job registry; created on first access."""
    jobs = getattr(runtime, "_wake_word_trainer_jobs", None)
    if jobs is None:
        jobs = {}
        runtime._wake_word_trainer_jobs = jobs
    return jobs


def _trainer_tasks(runtime: Any) -> set[asyncio.Task[Any]]:
    """Return the held task set per async-discipline."""
    tasks = getattr(runtime, "_wake_word_trainer_tasks", None)
    if tasks is None:
        tasks = set()
        runtime._wake_word_trainer_tasks = tasks
    return tasks


@router.post("/wake-word/sample", dependencies=[Depends(require_crew_scope)])
async def post_wake_word_sample(
    audio: UploadFile = File(...),
    phrase: str = Form(default=""),
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    config = runtime.config
    if not config.wake_word.wake_word_trainer_enabled:
        raise HTTPException(
            status_code=503,
            detail="wake_word_trainer_enabled is False",
        )
    raw = await audio.read()
    if len(raw) > config.wake_word.training_audio_max_bytes:
        raise HTTPException(
            status_code=413,
            detail=(
                f"sample exceeds wake_word.training_audio_max_bytes "
                f"({config.wake_word.training_audio_max_bytes} bytes)"
            ),
        )
    if not raw.startswith(_WAV_MAGIC):
        raise HTTPException(status_code=400, detail="not a WAV file (RIFF magic missing)")
    samples_dir = runtime.data_dir / "wake-word" / "training-samples" / "positive"
    samples_dir.mkdir(parents=True, exist_ok=True)
    existing = list(samples_dir.glob("*.wav"))
    if len(existing) >= config.wake_word.training_samples_max_count:
        raise HTTPException(
            status_code=429,
            detail=(
                f"training_samples_max_count reached "
                f"({config.wake_word.training_samples_max_count}). "
                "Delete some samples OR raise the cap to continue."
            ),
        )
    sha = hashlib.sha256(raw).hexdigest()[:16]
    target = samples_dir / f"{sha}.wav"
    target.write_bytes(raw)
    return {
        "stored": True,
        "sha": sha,
        "samples_count": len(existing) + 1,
        "phrase": phrase or None,
    }


@router.post("/wake-word/train", dependencies=[Depends(require_crew_scope)])
async def post_wake_word_train(
    payload: dict[str, Any] | None = None,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    config = runtime.config
    if not config.wake_word.wake_word_trainer_enabled:
        raise HTTPException(
            status_code=503,
            detail="wake_word_trainer_enabled is False",
        )
    label = (payload or {}).get("label") or "Computer"
    epochs = int((payload or {}).get("epochs") or 100)
    trainer = WakeWordTrainer(config, runtime.data_dir)
    positive_dir = runtime.data_dir / "wake-word" / "training-samples" / "positive"
    # Train into runtime.data_dir; the UI's Activate button copies the
    # ONNX into ui/public/models/wake-word/ via a future endpoint
    # (forward marker AD-705c-5). This keeps the trainer's write scope
    # inside data_dir so CI / tests can't pollute repo-tracked paths.
    output_path = runtime.data_dir / "wake-word" / config.wake_word.custom_model_filename
    job_id = uuid.uuid4().hex[:12]
    jobs = _trainer_jobs(runtime)
    jobs[job_id] = {
        "status": "running",
        "progress": 0.0,
        "started_at": time.time(),
        "label": label,
        "epochs": epochs,
    }
    tasks = _trainer_tasks(runtime)

    async def _run() -> None:
        try:
            report = await trainer.train(
                label=label,
                positive_samples_dir=positive_dir,
                epochs=epochs,
                output_path=output_path,
            )
            jobs[job_id]["status"] = "complete" if report.status == "ok" else "failed"
            jobs[job_id]["progress"] = 1.0 if report.status == "ok" else 0.0
            jobs[job_id]["report"] = {
                "status": report.status,
                "label": report.label,
                "output_path": report.output_path,
                "epochs_completed": report.epochs_completed,
                "samples_used": report.samples_used,
                "error_message": report.error_message,
            }
            if report.error_message:
                jobs[job_id]["error"] = report.error_message
            if report.output_path:
                jobs[job_id]["model_path"] = report.output_path
        except asyncio.CancelledError:
            jobs[job_id]["status"] = "cancelled"
            raise
        except Exception as exc:  # noqa: BLE001
            jobs[job_id]["status"] = "failed"
            jobs[job_id]["error"] = str(exc)
            logger.error(
                "AD-705c: wake-word train job %s failed: %s. "
                "Operator: check the trainer report and openwakeword install.",
                job_id,
                exc,
            )

    task = asyncio.create_task(_run(), name=f"wake_word_train_{job_id}")
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    return {"job_id": job_id, "status": "started"}


@router.get(
    "/wake-word/training-status",
    dependencies=[Depends(require_crew_scope)],
)
async def get_wake_word_training_status(
    job_id: str,
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    jobs = _trainer_jobs(runtime)
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"unknown job_id {job_id}")
    return dict(job)
