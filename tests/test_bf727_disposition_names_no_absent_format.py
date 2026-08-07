"""BF-727 (#1179): the disposition must not name artifact formats or libraries.

BF-726 (73739eba) made the ``run_python`` *tool description* derive its library
list from real importability. The reference vessel then restarted at 13:52:10 --
45 minutes AFTER that commit -- and the Captain asked Ezri what the sandbox can
produce. She answered "PDFs" and "matplotlib/seaborn plots". Neither library is
importable in the venv the sandbox runs under.

She was not confabulating. ``agentic_disposition.AGENTIC_DISPOSITION`` is
injected on every agentic turn and said, in prose:

    ... produce a real downloadable file (a .docx, .xlsx, .pdf, chart, or
    archive) the Captain can open ...

So there were TWO declarations of the artifact surface. BF-726 fixed the one the
model consults when *choosing* a tool; this is the one it quotes when *narrating*
what it can do. Fixing the schema made the choice honest and left the answer
wrong.

This is the third instance of one class in a week -- BF-701 (twelve actions
advertised, eleven admitted), AD-1177 (four tools named, eleven assembled), now
this. Each fix retired one hand-maintained enumeration and left a sibling
standing. AD-1177's own docstring, three lines above the offending text, names
the class it was created to retire.

The fix applies AD-1177's stated principle to the format list: stop enumerating,
defer to the schema. Deliberately NOT a second derived list -- two derived lists
can still disagree. One authority (the BF-726 description), one consumer.

Two properties carry the weight:

* **No enumeration at all**, asserted against ``_ARTIFACT_LIBRARIES`` rather than
  a hardcoded copy, so a library added to the advertised surface tomorrow is
  covered by this test today without anyone remembering to update it.
* **A crossing assertion** over the agent's TOTAL capability narration --
  disposition and tool description composed together, which is what actually
  reaches the model. Asserting on either alone is the half-chain shape that let
  this defect through: BF-726 proved the description, and the answer was still
  wrong.
"""

from __future__ import annotations

from typing import Any

import probos.tools.code_execution_tool as cet
from probos.cognitive.agentic_disposition import AGENTIC_DISPOSITION
from probos.cognitive.decomposer import is_capability_gap
from probos.tools.code_execution_tool import CodeExecutionTool


class _Runtime:
    """Minimal runtime: the description property reads only ``config``."""

    config = None


def _description() -> str:
    return CodeExecutionTool(runtime=_Runtime()).description


def _really_importable(module: str) -> bool:
    return cet._importable(module)


# The words a narration uses to promise each library's output, keyed by import
# name. Deliberately EXPLICIT rather than derived from ``_ARTIFACT_LIBRARIES``:
# a derived oracle agrees with whatever the source says, and the source saying
# the wrong thing is the defect. This map is the independent statement of what
# each library lets an agent claim.
#
# It is kept honest by ``test_the_format_map_covers_every_advertised_library``
# below, so a library added to the advertised surface fails the gate until its
# vocabulary is declared here -- rather than silently going unchecked, which is
# how the enumeration classes (BF-701 / AD-1177 / BF-727) each escaped.
_FORMAT_WORDS: dict[str, tuple[str, ...]] = {
    "docx": (".docx", "word document"),
    "openpyxl": (".xlsx", "spreadsheet"),
    "pptx": (".pptx", "slide deck"),
    "reportlab": (".pdf", "pdf"),
    "matplotlib": ("chart", "plot", "graph"),
    "PIL": (".png", ".jpg"),
}


def test_the_format_map_covers_every_advertised_library() -> None:
    """The oracle must not silently fall behind the surface it audits."""
    for module, _pip_name, _purpose in cet._ARTIFACT_LIBRARIES:
        assert module in _FORMAT_WORDS, (
            f"{module!r} joined _ARTIFACT_LIBRARIES without declaring the words "
            "a narration would use to promise it — the crossing test below "
            "cannot audit what it has no vocabulary for"
        )


# ── (1) the disposition names no library ───────────────────────────────────
def test_disposition_names_no_document_library() -> None:
    """Derived from ``_ARTIFACT_LIBRARIES``, not from a hardcoded list.

    A future library added to the advertised surface is covered the moment it
    is added, which is the property a hardcoded copy would not have -- and a
    hardcoded copy going stale is the very defect under repair.
    """
    for _module, pip_name, _purpose in cet._ARTIFACT_LIBRARIES:
        assert pip_name not in AGENTIC_DISPOSITION, (
            f"the disposition names {pip_name!r}. Prose cannot know whether a "
            "library is installed; the tool schema can, and does (BF-726). "
            "Naming it here is how the agent came to promise PDFs it cannot "
            "produce."
        )


def test_disposition_names_no_artifact_format() -> None:
    """The literal tokens from the BF-727 text, plus the two the Captain was
    wrongly promised. ``.pdf`` and ``chart`` are the ones that actually
    misled -- ``reportlab`` and ``matplotlib`` are both absent."""
    for token in (".docx", ".xlsx", ".pdf", ".pptx", ".png", "chart"):
        assert token not in AGENTIC_DISPOSITION.lower(), (
            f"the disposition enumerates {token!r}; the schema is the only "
            "surface that knows what is installed this turn"
        )


# ── (2) the disposition is not lost, only the enumeration ──────────────────
def test_disposition_still_directs_toward_producing_real_files() -> None:
    """Removing the list must not remove the intent. An agent that no longer
    knows it can produce files is a worse regression than one that names the
    wrong formats."""
    text = AGENTIC_DISPOSITION.lower()
    assert "downloadable file" in text
    assert "run_python" in AGENTIC_DISPOSITION


def test_disposition_points_at_the_schema_as_the_authority() -> None:
    """The replacement for the list is a pointer to the thing that knows."""
    assert "schema" in AGENTIC_DISPOSITION.lower()


def test_disposition_warns_against_assuming_a_wider_set() -> None:
    """AD-1177 told the agent not to assume a NARROWER set than it was given.

    The observed failure was the opposite direction -- assuming a wider one --
    and the one-directional wording is why the disposition read as permission
    to embellish. BF-726's own test asserts this same symmetry for the
    description ('a present library left unnamed is the same drift pointed the
    other way'); the disposition needs it too.
    """
    text = AGENTIC_DISPOSITION.lower()
    assert "narrower" in text and "wider" in text, (
        "the disposition guards only one direction of the drift"
    )


# ── (3) the crossing assertion: total narration, not either half ───────────
def test_total_capability_narration_names_no_absent_library() -> None:
    """The chain, not a link.

    What reaches the model is the disposition AND the tool schema, composed.
    BF-726 proved the description in isolation and the Captain still got a
    wrong answer, because the other half was never asserted against reality.

    Asserted on FORMAT WORDS, not only pip names: the disposition never said
    "reportlab", it said ".pdf". A pip-name-only assertion passes on the exact
    text that misled the Captain — verified, it did — so it would have been
    another link that proves itself and not the chain.
    """
    narration = (AGENTIC_DISPOSITION + "\n" + _description()).lower()
    for module, pip_name, _purpose in cet._ARTIFACT_LIBRARIES:
        if _really_importable(module):
            continue
        assert pip_name.lower() not in narration, (
            f"the composed narration advertises {pip_name!r}, which the "
            "sandbox cannot import"
        )
        for word in _FORMAT_WORDS[module]:
            assert word not in narration, (
                f"the composed narration promises {word!r}, which needs "
                f"{pip_name} — a library the sandbox cannot import. This is "
                "the exact shape of the answer the Captain was given."
            )


def test_narration_still_offers_what_is_genuinely_present() -> None:
    """The inverse half of the crossing assertion. Silence about a present
    library is a capability the agent will not reach for."""
    narration = AGENTIC_DISPOSITION + "\n" + _description()
    present = [
        pip_name
        for module, pip_name, _purpose in cet._ARTIFACT_LIBRARIES
        if _really_importable(module)
    ]
    assert present, "no artifact library importable — fixture assumption broken"
    for pip_name in present:
        assert pip_name in narration, (
            f"{pip_name!r} is importable but appears nowhere in the narration"
        )


# ── (4) the reworded text is still safe against the AD-596 detector ────────
def test_reworded_disposition_does_not_trip_the_capability_gap_detector() -> None:
    """AD-957 / AD-596. Asserted through the real ``is_capability_gap`` rather
    than a re-implemented pattern. The text affirms capability; if it matched
    the gap regex the detector would fire on a block that is doing the
    opposite of reporting absence."""
    assert not is_capability_gap(AGENTIC_DISPOSITION)
