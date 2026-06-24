"""AD-811a: A2UI choice-widget extractor for the DM reply pipeline.

Mirrors ``artifact_extractor.py`` (AD-797): scan an agent's reply for
``[A2UI]{json}[/A2UI]`` blocks, validate each as an
:class:`~probos.a2ui.AgentUIChoiceSpec`, persist the JSON to the
``AttachmentStore`` + metadata to the ``ArtifactStore`` (the AD-797
two-call write), and rewrite the reply with an inline
``[A2UI: name vN - choice]`` stub so the HXI can render an interactive
choice card.

Default-OFF: the DM pipeline only calls this when
``CommunicationsConfig.a2ui_enabled`` is True, so with the flag off the
extractor is never reached and behavior is byte-identical.

Honest-degrade everywhere (Tier-2): malformed JSON, an invalid spec, an
over-cap option count, or any store error skips the block and leaves the
original text intact — never raises.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

from probos.a2ui import A2UISpec, parse_a2ui_spec
from probos.artifacts import Artifact, ArtifactStore

logger = logging.getLogger(__name__)

# [A2UI]{json}[/A2UI] — non-greedy body, case-insensitive tag, DOTALL so
# the JSON payload may span lines.
_A2UI_PATTERN = re.compile(r"\[A2UI\](.*?)\[/A2UI\]", re.DOTALL | re.IGNORECASE)


def extract_a2ui(
    text: str, *, max_options: int = 10,
) -> list[A2UISpec]:
    """Find ``[A2UI]{json}[/A2UI]`` blocks and parse each via the kind registry.

    AD-811b: dispatches through :func:`~probos.a2ui.parse_a2ui_spec`, so a
    block of any registered ``kind`` (``choice``, ``multiselect``, …) is
    recognized; the choice path is unchanged. Caps at ONE widget per reply
    (the first valid block wins). Any block whose body is not valid JSON,
    fails its spec validation, carries an unknown/missing ``kind``, or has
    more than ``max_options`` options is skipped (honest-degrade, no
    raise).
    """
    if not text:
        return []
    specs: list[A2UISpec] = []
    for m in _A2UI_PATTERN.finditer(text):
        body = (m.group(1) or "").strip()
        if not body:
            continue
        spec = parse_a2ui_spec(body)
        if spec is None:
            logger.warning(
                "AD-811b: malformed/invalid/unknown-kind [A2UI] block; "
                "skipping",
            )
            continue
        opts = getattr(spec, "options", None)
        if opts is not None and len(opts) > max_options:
            logger.warning(
                "AD-811b: [A2UI] block has %d options > max_options=%d; "
                "skipping",
                len(opts), max_options,
            )
            continue
        specs.append(spec)
        break  # v1: at most one widget per reply
    return specs


def build_a2ui_stub(name: str, version: int, kind: str = "choice") -> str:
    """Inline stub left in place of an extracted ``[A2UI]`` block.

    AD-811b: the stub now carries the widget ``kind`` so the HXI can route
    to the matching renderer. ``kind`` defaults to ``"choice"`` so the
    AD-811a 2-arg callers stay byte-identical.

    Format (ASCII hyphen, NOT em-dash — the UI ``A2UI_STUB_RE`` matches
    the literal hyphen)::

        [A2UI: a2ui-choice-1.json v1 - choice]
        [A2UI: a2ui-multiselect-1.json v1 - multiselect]
    """
    return f"[A2UI: {name} v{version} - {kind}]"


async def replace_a2ui_with_stubs(
    text: str,
    specs: list[A2UISpec],
    *,
    artifact_store: ArtifactStore,
    attachment_store: Any,
    thread_id: str,
    created_by: str,
) -> tuple[str, list[Artifact]]:
    """Persist each choice spec + rewrite ``text`` with stub lines.

    Mirrors ``artifact_extractor.replace_with_stubs``: for each spec,
    serialize to JSON bytes, run the AD-797 two-call write
    (``mime="application/json"``, ``origin="agent_artifact"``), and
    replace the ``[A2UI]...[/A2UI]`` block with :func:`build_a2ui_stub`.

    Honest-degrade: on ANY store error the original ``text`` is returned
    untouched with an empty artifact list — never raises. (v1 caps at one
    spec, so the all-or-nothing return cannot orphan an already-persisted
    artifact's stub.)
    """
    if not specs:
        return text, []
    persisted: list[Artifact] = []
    new_text = text
    name_n = 0
    for spec in specs:
        blob = spec.to_json().encode("utf-8")
        content_hash = hashlib.sha256(blob).hexdigest()
        try:
            await attachment_store.write(
                content_hash, blob, "application/json",
                origin="agent_artifact",
            )
        except Exception:
            logger.warning(
                "AD-811a: AttachmentStore.write failed; leaving [A2UI] "
                "block intact", exc_info=True,
            )
            return text, []
        name_n += 1
        name = f"a2ui-{spec.kind}-{name_n}.json"
        try:
            artifact = artifact_store.add_version(
                thread_id=thread_id,
                name=name,
                content_hash=content_hash,
                mime="application/json",
                size_bytes=len(blob),
                created_by=created_by,
            )
        except Exception:
            logger.warning(
                "AD-811a: ArtifactStore.add_version failed; leaving [A2UI] "
                "block intact", exc_info=True,
            )
            return text, []
        persisted.append(artifact)
        stub = build_a2ui_stub(artifact.name, artifact.version, spec.kind)
        # Replace only the first remaining [A2UI] block; the lambda form
        # avoids re.sub interpreting any backslash/group ref in the stub.
        new_text = _A2UI_PATTERN.sub(lambda _m: stub, new_text, count=1)
    return new_text, persisted
