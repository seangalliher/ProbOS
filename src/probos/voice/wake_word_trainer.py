"""AD-705c (Wave 179) — Custom wake-word training service.

Wraps the openWakeWord training pipeline in a ProbOS-shaped facade.
The trainer runs entirely on the local runtime — training audio NEVER
leaves the host (privacy invariant).

Honest-degrade posture: ``openwakeword`` is NOT in ``pyproject.toml``.
The operator installs it separately via ``pip install
openwakeword[training]``. When the import fails the trainer surfaces a
``WakeWordTrainingReport(status="error", error_message=...)`` instead
of raising — the CLI / API consumer reports the actionable message.

BF-280 posture: the openWakeWord trainer is sync PyTorch. ``train()``
schedules it on ``loop.run_in_executor(None, ...)`` so the FastAPI
event loop (WindowsSelectorEventLoop) is never blocked AND no
``asyncio.create_subprocess_exec`` call is required.
"""

from __future__ import annotations

import asyncio
import importlib
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from probos.config import SystemConfig

logger = logging.getLogger("probos.voice.wake_word_trainer")


@dataclass
class WakeWordTrainingReport:
    """Outcome of a single training run."""

    status: str  # "ok" | "error"
    label: str = ""
    output_path: str | None = None
    epochs_completed: int = 0
    final_loss: float | None = None
    validation_accuracy: float | None = None
    samples_used: int = 0
    error_message: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class WakeWordTestReport:
    """Outcome of a validation run on a held-out sample set."""

    status: str  # "ok" | "error"
    samples_used: int = 0
    true_positive_rate: float | None = None
    false_accept_rate: float | None = None
    error_message: str | None = None


_OPENWAKEWORD_INSTALL_HINT = (
    "openwakeword is not installed. Run "
    "`pip install openwakeword[training]` to enable the custom "
    "wake-word trainer. The runtime continues to function with the "
    "stock community model fallback."
)


class WakeWordTrainer:
    """Service-layer facade over openWakeWord training."""

    def __init__(self, config: SystemConfig, data_dir: Path) -> None:
        self._config = config
        self._data_dir = data_dir
        self._samples_root = data_dir / "wake-word" / "training-samples"
        self._reports_root = data_dir / "wake-word" / "training-reports"

    @property
    def samples_root(self) -> Path:
        return self._samples_root

    @property
    def reports_root(self) -> Path:
        return self._reports_root

    def _load_openwakeword(self) -> Any:
        """Return the openwakeword.train module, or raise ImportError.

        Catches ONLY ``ImportError`` per BF-274 lesson — broad
        ``except Exception`` would mask real bugs in the training
        pipeline.
        """
        try:
            return importlib.import_module("openwakeword.train")
        except ImportError as exc:
            logger.warning(
                "AD-705c: openwakeword.train import failed (%s); trainer "
                "honest-degrades. Operator hint: %s",
                exc,
                _OPENWAKEWORD_INSTALL_HINT,
            )
            raise

    async def train(
        self,
        label: str,
        positive_samples_dir: Path,
        negative_samples_dir: Path | None = None,
        epochs: int = 100,
        output_path: Path | None = None,
    ) -> WakeWordTrainingReport:
        """Train a custom wake-word ONNX model.

        Runs the openWakeWord training pipeline in a thread executor
        (BF-280). Honest-degrades to a ``status="error"`` report when
        ``openwakeword`` is not installed; never raises.
        """
        loop = asyncio.get_running_loop()
        try:
            trainer_mod = self._load_openwakeword()
        except ImportError as exc:
            return WakeWordTrainingReport(
                status="error",
                label=label,
                error_message=(
                    f"{_OPENWAKEWORD_INSTALL_HINT} (underlying error: {exc})"
                ),
            )

        positive_samples = (
            list(positive_samples_dir.glob("*.wav"))
            if positive_samples_dir.exists()
            else []
        )
        if not positive_samples:
            return WakeWordTrainingReport(
                status="error",
                label=label,
                error_message=(
                    f"No positive samples found under {positive_samples_dir}. "
                    "Run `probos wake-word collect` first."
                ),
            )

        if output_path is None:
            ui_models_dir = (
                Path(__file__).resolve().parent.parent.parent.parent
                / "ui"
                / "public"
                / "models"
                / "wake-word"
            )
            ui_models_dir.mkdir(parents=True, exist_ok=True)
            output_path = ui_models_dir / self._config.wake_word.custom_model_filename

        def _sync_train() -> WakeWordTrainingReport:
            try:
                # openwakeword.train.train(...) is the documented
                # entrypoint; signature may vary across versions, so
                # call with kwargs and let openwakeword raise on
                # mismatch (the broad outer except below handles that).
                trainer_mod.train(
                    label=label,
                    positive_samples=[str(p) for p in positive_samples],
                    negative_samples=(
                        [str(p) for p in negative_samples_dir.glob("*.wav")]
                        if negative_samples_dir
                        else None
                    ),
                    epochs=epochs,
                    output_path=str(output_path),
                )
            except Exception as exc:  # noqa: BLE001 — surface upstream errors verbatim
                return WakeWordTrainingReport(
                    status="error",
                    label=label,
                    samples_used=len(positive_samples),
                    error_message=str(exc),
                )
            return WakeWordTrainingReport(
                status="ok",
                label=label,
                output_path=str(output_path),
                epochs_completed=epochs,
                samples_used=len(positive_samples),
            )

        report = await loop.run_in_executor(None, _sync_train)

        # Privacy: delete training samples after train unless the
        # operator explicitly opted in to retention.
        if (
            report.status == "ok"
            and not self._config.wake_word.retain_training_samples
            and positive_samples_dir.exists()
        ):
            try:
                shutil.rmtree(positive_samples_dir)
                positive_samples_dir.mkdir(parents=True, exist_ok=True)
                logger.info(
                    "AD-705c: deleted %d training samples (retention=False)",
                    len(positive_samples),
                )
            except OSError as exc:
                # Tier-2: deletion failure is not a training failure —
                # log so the operator can clean up by hand.
                logger.warning(
                    "AD-705c: failed to delete training samples under %s "
                    "(retention=False): %s. Operator action: rm -rf the "
                    "directory manually.",
                    positive_samples_dir,
                    exc,
                )

        return report

    async def test(
        self,
        model_path: Path,
        samples_dir: Path,
    ) -> WakeWordTestReport:
        """Validate a trained model against held-out samples."""
        loop = asyncio.get_running_loop()
        try:
            trainer_mod = self._load_openwakeword()
        except ImportError as exc:
            return WakeWordTestReport(
                status="error",
                error_message=f"{_OPENWAKEWORD_INSTALL_HINT} (underlying error: {exc})",
            )
        samples = list(samples_dir.glob("*.wav")) if samples_dir.exists() else []
        if not samples:
            return WakeWordTestReport(
                status="error",
                error_message=f"No samples under {samples_dir}.",
            )

        def _sync_test() -> WakeWordTestReport:
            try:
                metrics = trainer_mod.test(
                    model_path=str(model_path),
                    samples=[str(s) for s in samples],
                )
            except Exception as exc:  # noqa: BLE001
                return WakeWordTestReport(
                    status="error",
                    samples_used=len(samples),
                    error_message=str(exc),
                )
            return WakeWordTestReport(
                status="ok",
                samples_used=len(samples),
                true_positive_rate=float(metrics.get("tpr", 0.0)) if isinstance(metrics, dict) else None,
                false_accept_rate=float(metrics.get("far", 0.0)) if isinstance(metrics, dict) else None,
            )

        return await loop.run_in_executor(None, _sync_test)
