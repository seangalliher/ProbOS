"""BF-792: what a reply must survive when it bypasses ``DmReplyPipeline``.

Some paths answer the Captain without the pipeline, so every marker the pipeline
would have removed reaches the transcript raw. This has now happened three times
with two markers:

* BF-702 -- the ``<intent emotion=NAME>`` self-tag leaked on the AD-1165
  promotion report and was fixed *there*.
* BF-792 (#1256) -- the same tag leaks on the AD-1230 deferred replay, because
  the fix was applied to a path rather than to the shape.
* BF-791 (#1255) -- the ``[A2UI]{json}[/A2UI]`` block leaks on *both*.

So the transformations live here, in one function, rather than being repeated at
each bypass. A new bypass path gets them by calling one thing, and a fourth
marker is added in one place.

**This module does not by itself make the transcript marker-free, and must not
be described as though it does.** Adversarial review enumerated the agent-role
writers into ``ChatThreadStore.append_message`` and found NINE model-authored
sinks, not two; it reached the work-item acknowledgement path and got a stored
body still carrying both markers. Two are wired to this function
(``turn_promotion``, ``deferred_turns``); the rest are tracked separately.
``tests/test_bf791_bf792_bypass_egress.py`` pins that list so a new sink has to
choose rather than inherit the gap.

Deliberately store-free and synchronous. The pipeline's A2UI step persists each
spec as an artifact and leaves a stub the HXI renders as an interactive widget;
that needs an AttachmentStore, an ArtifactStore and a thread id these paths do
not uniformly have. Reaching for them would make a *leak* fix depend on wiring a
persistence path into more callers. What this does instead is render the widget
as prose, so the Captain reads the question rather than protocol JSON. The
interactive widget on a bypassed reply stays unbuilt -- which is why #1255 is
NOT closed by this change.
"""

from __future__ import annotations

import logging
import re

from probos.a2ui import (
    A2UISpec,
    AgentUIFormSpec,
    AgentUIMultiSelectSpec,
    parse_a2ui_spec,
)
from probos.cognitive.dm.a2ui_extractor import A2UI_PATTERN

logger = logging.getLogger(__name__)

#: Shown in place of a block that cannot be rendered. Neither silent deletion of
#: Captain-bound content nor raw protocol framing in front of him.
UNRENDERABLE_NOTE = (
    "(An interactive prompt could not be displayed here. "
    "Ask me to restate it.)"
)

_MARKER_PROBE = re.compile(r"\[A2UI\]|<intent\s+emotion", re.IGNORECASE)


def _selection_note(spec: AgentUIMultiSelectSpec) -> str:
    """State the ACTUAL bounds.

    A blanket "you may pick more than one" is false for the permitted
    ``min_select=1, max_select=1`` shape, which is a single pick.
    """
    low = spec.min_select
    high = spec.max_select
    if high is not None:
        if high <= 1:
            return "(Pick one.)"
        if low == high:
            return f"(Pick exactly {low}.)"
        return f"(Pick between {low} and {high}.)"
    if low > 1:
        return f"(Pick at least {low}.)"
    return "(You may pick more than one.)"


def _render_spec(spec: A2UISpec) -> str:
    """The widget as prose, for a surface that cannot render the widget."""
    lines = [spec.prompt]
    if isinstance(spec, AgentUIFormSpec):
        lines.extend(f"- {field.label}" for field in spec.fields)
        return "\n".join(lines)
    lines.extend(f"{i}. {option}" for i, option in enumerate(spec.options, 1))
    if isinstance(spec, AgentUIMultiSelectSpec):
        lines.append(_selection_note(spec))
    return "\n".join(lines)


def render_a2ui_as_text(text: str) -> str:
    """Replace each ``[A2UI]`` block with a readable rendering of its widget.

    A block that does not parse is replaced by :data:`UNRENDERABLE_NOTE` and the
    raw body is logged. Leaving it in place was the first attempt and review was
    right to reject it: the defect being fixed IS protocol framing reaching the
    Captain, so preserving that framing whenever parsing fails keeps the defect
    for exactly the inputs most likely to produce it.
    """
    if "[A2UI]" not in text.upper():
        return text

    def _replace(match: re.Match[str]) -> str:
        spec = parse_a2ui_spec(match.group(1))
        if spec is None:
            logger.warning(
                "BF-791: an [A2UI] block on a pipeline-bypass reply did not "
                "parse and was replaced with a note; raw body: %.400r",
                match.group(1),
            )
            return UNRENDERABLE_NOTE
        return _render_spec(spec)

    return A2UI_PATTERN.sub(_replace, text)


def compose_bypass_reply(text: str) -> str:
    """Apply every pipeline egress transformation a bypass path still owes.

    Idempotent, and **byte-identical** for text carrying no marker -- the early
    return is what lets a caller apply it unconditionally without knowing
    whether the producing feature was enabled. An earlier draft trimmed
    unconditionally, which silently reflowed every ordinary deferred answer.

    Whitespace-only input is the one exception, and returns ``""``. Both callers
    branch on falsiness to choose their empty-reply wording, so preserving
    ``"   "`` byte-identically would post three spaces into the transcript
    instead of "that background task is finished" -- which the AD-1165 suite
    caught the moment the byte-identity rule was added without this carve-out.

    Returns ``""`` when the reply was nothing but markers, for the same reason.
    """
    raw = str(text or "")
    if not raw.strip():
        return ""
    if not _MARKER_PROBE.search(raw):
        return raw

    from probos.avatars.divergence_detector import strip_intent_self_tag

    return render_a2ui_as_text(strip_intent_self_tag(raw)).strip()
