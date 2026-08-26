"""BF-781: three more controls the execution subsystem described but lacked.

BF-763 (#1221) corrected the claims inside its own blast radius and
deliberately stopped there. These are the three the issue confirmed still open,
each re-verified against the code before being touched:

1. ``IsolationBackend.run`` said "honest-degrade, never raise". **Measured**:
   cancelling the awaiting task raises ``CancelledError`` out of ``run``.
   ``SubprocessSandbox.run`` catches it explicitly, performs the BF-788/BF-840
   scratch-dir cleanup handshake, and re-raises. The behaviour is correct --
   never swallow cancellation -- and only the description was wrong.

   A first draft of this file, and of the source correction, attributed the
   propagation to the degrade arm catching ``Exception`` while
   ``CancelledError`` is a ``BaseException``. True of the language, wrong about
   this code: that arm is in the sync worker, off the cancellation path. Caught
   by a mutant that flipped it to ``BaseException`` and changed nothing, then
   caught AGAIN in review because I fixed the source and left this docstring
   saying the wrong thing.

2. ``isolation.py``'s module docstring described tier escalation in the present
   tense. Tiers 2 and 3 are unbuilt and no module under ``execution/`` reads the
   execution tier field -- **enumerated**. (Scoped to ``execution/`` after
   review disproved a broader first draft: ``holodeck`` reads a ``default_tier``
   too.)

3. ``ExecutionConfig.scratch_dir`` was annotated "ephemeral per-task working
   folders" flatly, while ``persistent_workspaces`` defaults **True** -- under
   which ``CodeRunnerAgent`` uses its owner's persistent folder. It is not dead
   either way: ``CodeExecutionTool`` still roots runs here.

The cost of each is the same and it is measured, not theoretical: a false
rationale stops the next reader looking, which is how "every execution is
quorum-authorized" survived from AD-993 until a live-trace audit found 60
ungated executions.

These are source assertions because the claims are prose. Following BF-763's
pattern, each pins the exact historical sentence rather than banning a phrase --
a substring ban cannot tell an assertion from its denial -- and asserts both
that the false claim is gone AND that the correction is present, because
otherwise the two can coexist.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _text(relative: str) -> str:
    """Whitespace-normalised source, so a reflowed docstring is not a failure."""
    return " ".join(Path(relative).read_text(encoding="utf-8").split())


ISOLATION = "src/probos/execution/isolation.py"
CONFIG = "src/probos/config.py"


def test_the_premise_that_these_files_are_readable() -> None:
    """Every assertion below is vacuous against an empty string, which is what
    a moved or renamed file would silently produce."""
    assert len(_text(ISOLATION)) > 5000
    assert len(_text(CONFIG)) > 5000


class TestRunDoesNotClaimItNeverRaises:

    def test_the_false_claim_is_gone(self) -> None:
        source = _text(ISOLATION)

        assert "honest-degrade, never raise" not in source
        assert "never raise out of run" not in source

    def test_the_correction_is_present(self) -> None:
        """Deleted alone, the next reader still has no idea cancellation
        escapes -- which is the thing they need to know."""
        source = _text(ISOLATION)

        assert "Cancellation propagates" in source
        assert "BF-781" in source

    @pytest.mark.asyncio
    async def test_the_behaviour_the_correction_describes(self) -> None:
        """The claim is about runtime behaviour, so pin the behaviour too.

        If ``run`` were ever changed to swallow cancellation, the corrected
        prose would become false in the other direction and only this would
        catch it.
        """
        import asyncio

        from probos.execution.isolation import ExecutionRequest, SubprocessSandbox

        sandbox = SubprocessSandbox()
        request = ExecutionRequest(
            code="import time; time.sleep(30)", timeout_seconds=30.0,
        )

        task = asyncio.create_task(sandbox.run(request))
        await asyncio.sleep(0.4)  # let it reach the executor
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task


class TestTheModuleDoesNotDescribeEscalationThatCannotHappen:

    def test_the_false_claim_is_gone(self) -> None:
        source = _text(ISOLATION)

        assert (
            "A task is either deemed safe enough for Tier 1 or escalates to a "
            "higher tier; the escalation policy lives with the caller"
        ) not in source

    def test_the_correction_is_present(self) -> None:
        source = _text(ISOLATION)

        assert "declaration-only" in source

    def test_the_config_side_correction_is_present_too(self) -> None:
        """The same claim lives in two files and both were corrected, but the
        guard only covered one -- a mutant that removed the config-side
        correction SURVIVED. Two homes for one claim need two guards."""
        source = _text(CONFIG)

        assert "declaration-only" in source
        # One line only -- see the note in TestScratchDir below. I walked into
        # this trap a second time in the same file.
        assert "A rule stated for a field nobody reads is the" in source

    def test_the_correction_does_not_quote_the_false_sentence(self) -> None:
        """BF-763's lesson, applied to my own first draft of this file.

        I wrote the correction by quoting the wrong sentence verbatim, which
        made the ban above fail against the corrected file. A guard cannot tell
        an assertion from its denial, so a correction must DESCRIBE the old
        claim rather than reproduce it.
        """
        source = _text(ISOLATION)

        assert "escalates to a higher tier" not in source

    def test_the_field_really_has_no_execution_consumer(self) -> None:
        """The premise the correction rests on. If an execution path starts
        reading the tier field, the corrected prose becomes false and this
        fails -- which is the point of checking it rather than asserting it.

        Matches attribute READS (``something.default_tier``) AND the
        ``getattr(cfg, "default_tier")`` form, and skips comment lines, so
        prose mentioning the field -- including the correction itself -- does
        not count as a consumer. Two earlier versions were wrong here: one
        counted its own explanation, and one matched only dot-access, which
        review pointed out a real consumer could evade -- the codebase already
        uses the ``getattr`` form for this very field elsewhere.
        """
        import re

        read = re.compile(
            r"""\.default_tier\b|getattr\([^,)]+,\s*['"]default_tier['"]"""
        )
        readers: list[str] = []
        for path in Path("src/probos").rglob("*.py"):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip().startswith("#") or not read.search(line):
                    continue
                readers.append(path.as_posix())
                break

        assert readers, (
            "premise: nothing reads default_tier anywhere, so this test "
            "cannot distinguish an execution consumer from no consumer at all"
        )
        assert not [r for r in readers if "/execution/" in r], (
            f"an execution module now reads default_tier: {readers}"
        )


class TestScratchDirIsNotDescribedAsTheNormalCase:

    def test_the_false_claim_is_gone(self) -> None:
        source = _text(CONFIG)

        assert (
            'scratch_dir: str = "data/execution" # ephemeral per-task working folders'
            not in source
        )

    def test_the_correction_is_present(self) -> None:
        source = _text(CONFIG)

        # Phrases chosen to sit within ONE comment line: the normaliser keeps
        # the leading ``#`` of every continuation line, so a phrase spanning
        # two lines picks up a stray ``#`` and never matches. My first draft
        # did exactly that.
        assert "and it defaults True" in source
        # Review's finding: the first correction called scratch_dir a fallback,
        # which overclaimed -- CodeExecutionTool still roots runs there under
        # the shipped config. The correction must keep saying so.
        assert "NOT dead either way" in source

    def test_the_default_the_correction_depends_on(self) -> None:
        """The correction says persistent_workspaces defaults True. If that
        ever flips, the prose is wrong again and this is what says so."""
        from probos.config import ExecutionConfig

        assert ExecutionConfig().persistent_workspaces is True
