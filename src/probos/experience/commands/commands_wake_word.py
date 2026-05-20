"""AD-705c (Wave 179) — Wake-word training slash-commands.

Operator-facing CLI for the custom wake-word pipeline. Surfaces four
sub-actions under ``/wake-word``:

- ``/wake-word status`` — current sample / model state.
- ``/wake-word collect`` — record N positive samples (interactive).
- ``/wake-word train`` — train ``captain.onnx`` from collected samples.
- ``/wake-word test`` — validate the trained model.

The CLI honest-degrades when ``openwakeword`` is not installed:
prints the install hint and returns. No hard dependency in
``pyproject.toml``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel

from probos.voice.wake_word_trainer import WakeWordTrainer

if TYPE_CHECKING:
    from probos.runtime import ProbOSRuntime

logger = logging.getLogger(__name__)


def _samples_count(samples_dir: Path) -> int:
    if not samples_dir.exists():
        return 0
    return len(list(samples_dir.glob("*.wav")))


async def cmd_wake_word(runtime: "ProbOSRuntime", console: Console, args: str) -> None:
    """Dispatch /wake-word <subcommand>."""
    parts = args.strip().split(maxsplit=1)
    sub = parts[0] if parts else "status"
    rest = parts[1] if len(parts) > 1 else ""
    if sub == "status":
        await _cmd_status(runtime, console)
    elif sub == "collect":
        await _cmd_collect(runtime, console, rest)
    elif sub == "train":
        await _cmd_train(runtime, console, rest)
    elif sub == "test":
        await _cmd_test(runtime, console, rest)
    else:
        console.print(
            Panel(
                f"Unknown /wake-word subcommand: {sub!r}.\n"
                "Try: status | collect | train | test",
                title="wake-word",
                border_style="yellow",
            )
        )


async def _cmd_status(runtime: "ProbOSRuntime", console: Console) -> None:
    config = runtime.config
    samples_dir = runtime.data_dir / "wake-word" / "training-samples" / "positive"
    custom_filename = config.wake_word.custom_model_filename
    model_path = (
        Path(__file__).resolve().parent.parent.parent.parent.parent
        / "ui"
        / "public"
        / "models"
        / "wake-word"
        / custom_filename
    )
    lines = [
        f"[bold]Trainer enabled:[/bold] {config.wake_word.wake_word_trainer_enabled}",
        f"[bold]Custom model filename:[/bold] {custom_filename}",
        f"[bold]Custom model present:[/bold] {model_path.exists()} ({model_path})",
        f"[bold]Training samples collected:[/bold] {_samples_count(samples_dir)}",
        f"[bold]Retain samples after train:[/bold] {config.wake_word.retain_training_samples}",
        f"[bold]Sample cap:[/bold] {config.wake_word.training_samples_max_count}",
        f"[bold]Per-sample byte cap:[/bold] {config.wake_word.training_audio_max_bytes}",
    ]
    console.print(Panel("\n".join(lines), title="wake-word status", border_style="cyan"))


async def _cmd_collect(runtime: "ProbOSRuntime", console: Console, _rest: str) -> None:
    samples_dir = runtime.data_dir / "wake-word" / "training-samples" / "positive"
    samples_dir.mkdir(parents=True, exist_ok=True)
    console.print(
        Panel(
            "Interactive recording is delivered via the HXI "
            "WakeWordTrainerPanel (Settings → Voice). The CLI exposes "
            "the path for operators who prefer command-line tooling:\n\n"
            f"  positive samples directory: {samples_dir}\n\n"
            "Drop pre-recorded mono 16-bit PCM WAV files into the "
            "directory, then run `/wake-word train`. The browser "
            "uploader writes to the same location.",
            title="wake-word collect",
            border_style="cyan",
        )
    )


async def _cmd_train(runtime: "ProbOSRuntime", console: Console, rest: str) -> None:
    config = runtime.config
    label = "Computer"
    epochs = 100
    for token in rest.split():
        if token.startswith("--label="):
            label = token.split("=", 1)[1]
        elif token.startswith("--epochs="):
            try:
                epochs = int(token.split("=", 1)[1])
            except ValueError:
                pass
    trainer = WakeWordTrainer(config, runtime.data_dir)
    positive_dir = runtime.data_dir / "wake-word" / "training-samples" / "positive"
    console.print(f"[dim]Training '{label}' for {epochs} epochs ...[/dim]")
    report = await trainer.train(
        label=label,
        positive_samples_dir=positive_dir,
        epochs=epochs,
    )
    if report.status == "ok":
        console.print(
            Panel(
                f"[green]Training complete.[/green]\n"
                f"Output: {report.output_path}\n"
                f"Samples used: {report.samples_used}",
                title="wake-word train",
                border_style="green",
            )
        )
    else:
        console.print(
            Panel(
                f"[red]Training failed.[/red]\n{report.error_message}",
                title="wake-word train",
                border_style="red",
            )
        )


async def _cmd_test(runtime: "ProbOSRuntime", console: Console, rest: str) -> None:
    config = runtime.config
    trainer = WakeWordTrainer(config, runtime.data_dir)
    samples_dir = runtime.data_dir / "wake-word" / "training-samples" / "positive"
    custom_filename = config.wake_word.custom_model_filename
    model_path = (
        Path(__file__).resolve().parent.parent.parent.parent.parent
        / "ui"
        / "public"
        / "models"
        / "wake-word"
        / custom_filename
    )
    for token in rest.split():
        if token.startswith("--model="):
            model_path = Path(token.split("=", 1)[1])
        elif token.startswith("--samples-dir="):
            samples_dir = Path(token.split("=", 1)[1])
    report = await trainer.test(model_path=model_path, samples_dir=samples_dir)
    if report.status == "ok":
        console.print(
            Panel(
                f"[green]Test complete.[/green]\n"
                f"Samples: {report.samples_used}\n"
                f"TPR: {report.true_positive_rate}\n"
                f"FAR: {report.false_accept_rate}",
                title="wake-word test",
                border_style="green",
            )
        )
    else:
        console.print(
            Panel(
                f"[red]Test failed.[/red]\n{report.error_message}",
                title="wake-word test",
                border_style="red",
            )
        )
