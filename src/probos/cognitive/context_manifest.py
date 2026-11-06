"""AD-1357 (#1749): what a crew chat reply was given, kept beside the reply.

``CognitiveAgent`` builds a ``direct_message`` prompt from named context sections
(the ``_emit`` bids of ``_build_user_message``) and from what recall and the
passive lookups put on the observation. This module records those facts as a
small, bounded, JSON-safe context manifest, stored under the reply's
``metadata["context_manifest"]``:

* every section bid, in emission order, with its character count and whether
  the attention budget kept it, then the text appended after assembly;
* whether episodic recall ran; its query, only when that query is the Captain's
  own words on a 1:1 turn; the agent's own recalled episode ids with their
  source tags; and the AD-981a band, best similarity and AD-1038 recall type;
* whether cross-agent recall (AD-979d), transcript grounding (AD-986b) and the
  passive Oracle lookup ran, and what they returned: a count for cross-agent
  recall, the room id for transcript grounding, and for the Oracle a count per
  tier plus the paths of its Ship's Records results;
* the cognitive journal's prompt and response hashes, and the id of the
  journal row for the same turn.

It holds no section text, no other agent's message text, no peer agent's
episode id and no camera scene. A section is recorded by its name alone, so a
new ``_emit`` source is recorded with no change here.

Stdlib only, because the chat routers import it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any, Final

logger = logging.getLogger(__name__)

#: The reply metadata key, on ``IntentResult.metadata`` and on the stored message.
CONTEXT_MANIFEST_METADATA_KEY: Final = "context_manifest"
#: Observation keys: this prompt's ledger, this turn's recall record, the finished manifest.
LEDGER_KEY: Final = "_context_ledger"
RECALL_KEY: Final = "_context_recall"
MANIFEST_KEY: Final = "_context_manifest"
#: The ``dag_node_id`` of the journal row an agentic DM turn writes.
DM_TURN_DAG_NODE: Final = "dm-turn"
MANIFEST_VERSION: Final = 1

MAX_SECTIONS: Final = 48
MAX_NAME_CHARS: Final = 64
MAX_EPISODES: Final = 32
MAX_ID_CHARS: Final = 64
MAX_SOURCE_CHARS: Final = 32
MAX_THREADS: Final = 4
MAX_TIERS: Final = 8
MAX_RECORD_PATHS: Final = 12
MAX_PATH_CHARS: Final = 200
MAX_QUERY_CHARS: Final = 200
MAX_MANIFEST_BYTES: Final = 16384

#: The one Oracle tier whose results are identified, by path. Ship's Records are
#: the shared record; another tier's ids can name another agent's episodes, so
#: those results are counted and never identified.
_IDENTIFIED_TIER: Final = "records"
_LOOKUPS: Final = ("cross_agent_recall", "transcript_grounding", "oracle")


def turn_hash(text: Any) -> str:
    """The cognitive journal's hash of a prompt or a reply: the first 12 hex digits of
    the MD5 of its first 500 characters, as ``_decide_via_llm`` computes it (AD-431).

    A value that is not a ``str`` hashes as ``""``, and a lone surrogate is encoded
    rather than raising, so the hash never stops a turn.
    """
    value = text if isinstance(text, str) else ""
    return hashlib.md5(value[:500].encode("utf-8", "surrogatepass")).hexdigest()[:12]


def _text(value: Any, limit: int) -> str:
    """``value`` cut to ``limit`` characters when it is a ``str``; otherwise ``""``."""
    return value[:limit] if isinstance(value, str) else ""


def _finite(value: Any) -> float | None:
    """A finite number rounded to four places; a bool, NaN, an infinity, text or an
    int too large for a float is ``None``."""
    if type(value) is bool or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return round(number, 4) if math.isfinite(number) else None


@dataclass(slots=True)
class _Section:
    name: str
    chars: int
    kept: bool


class ContextLedger:
    """The sections of one ``direct_message`` prompt, in the order they were bid.

    ``renderer`` is called once per ``_emit`` bid, before assembly. It returns the
    bid's lazy renderer, which returns ``text`` itself and marks the section kept.
    ``ContextAssembler.assemble`` calls only the renderers of the bids it keeps, so
    a section whose renderer never ran was dropped by the token budget.
    ``note_appended`` records text appended to the user message after assembly.
    """

    __slots__ = ("_sections",)

    def __init__(self) -> None:
        self._sections: list[_Section] = []

    def renderer(self, name: str, text: str) -> Callable[[], str]:
        section = _Section(name=name, chars=len(text), kept=False)
        self._sections.append(section)

        def _render() -> str:
            section.kept = True
            return text

        return _render

    def note_appended(self, name: str, chars: int) -> None:
        if chars > 0:
            self._sections.append(_Section(name=name, chars=chars, kept=True))

    def to_wire(self) -> tuple[list[dict[str, Any]], int]:
        """The first ``MAX_SECTIONS`` sections and how many were left out."""
        shown = [
            {"name": _text(section.name, MAX_NAME_CHARS), "chars": section.chars, "kept": section.kept}
            for section in self._sections[:MAX_SECTIONS]
        ]
        return shown, max(0, len(self._sections) - MAX_SECTIONS)


@dataclass(slots=True)
class RecallRecord:
    """What ``_recall_relevant_memories`` did for one ``direct_message`` turn."""

    query: str | None
    query_chars: int
    failed: bool = False
    episodes: list[dict[str, str]] = field(default_factory=list)
    episode_count: int = 0
    confidence: dict[str, Any] | None = None
    cross_agent: dict[str, Any] | None = None
    transcript: dict[str, Any] | None = None
    oracle: dict[str, Any] | None = None

    def to_wire(self) -> tuple[dict[str, Any], dict[str, Any]]:
        recall = {
            "ran": True,
            "query": self.query,
            "query_chars": self.query_chars,
            "failed": self.failed,
            "episodes": list(self.episodes),
            "episode_count": self.episode_count,
            "confidence": self.confidence,
        }
        lookups = {
            "cross_agent_recall": self.cross_agent or {"ran": False},
            "transcript_grounding": self.transcript or {"ran": False},
            "oracle": self.oracle or {"ran": False},
        }
        return recall, lookups


def start_ledger(observation: Any) -> ContextLedger:
    """A new ledger for this prompt, kept on the observation; an earlier manifest on it is dropped."""
    ledger = ContextLedger()
    if isinstance(observation, dict):
        observation[LEDGER_KEY] = ledger
        observation.pop(MANIFEST_KEY, None)
    return ledger


def ledger_of(observation: Any) -> ContextLedger | None:
    ledger = observation.get(LEDGER_KEY) if isinstance(observation, dict) else None
    return ledger if isinstance(ledger, ContextLedger) else None


def _record(observation: Any) -> RecallRecord | None:
    record = observation.get(RECALL_KEY) if isinstance(observation, dict) else None
    return record if isinstance(record, RecallRecord) else None


def start_recall(observation: Any, *, query: str, captain_words: bool) -> None:
    """Recall ran for this turn. The query text is kept only when ``captain_words``."""
    if isinstance(observation, dict):
        observation[RECALL_KEY] = RecallRecord(
            query=_text(query, MAX_QUERY_CHARS) if captain_words else None,
            query_chars=len(query) if isinstance(query, str) else 0,
        )


def note_episodes(observation: Any, episodes: Iterable[Any]) -> None:
    """The agent's own recalled episodes that reached the memory section: ids and source tags."""
    record = _record(observation)
    if record is None:
        return
    listed = list(episodes)
    record.episode_count = len(listed)
    record.episodes = [
        {
            "id": _text(getattr(ep, "id", ""), MAX_ID_CHARS),
            "source": _text(getattr(ep, "source", "direct"), MAX_SOURCE_CHARS),
        }
        for ep in listed[:MAX_EPISODES]
    ]


def note_recall_failed(observation: Any) -> None:
    record = _record(observation)
    if record is not None:
        record.failed = True


def note_confidence(observation: Any, confidence: Any) -> None:
    """The AD-981a band and best similarity and the AD-1038 recall type the probe returned."""
    record = _record(observation)
    if record is None or confidence is None:
        return
    record.confidence = {
        "band": _text(getattr(confidence, "band", ""), MAX_SOURCE_CHARS) or None,
        "best_similarity": _finite(getattr(confidence, "best_similarity", None)),
        "recall_type": _text(getattr(confidence, "recall_type", ""), MAX_SOURCE_CHARS) or None,
    }


def note_cross_agent(observation: Any, count: int | None) -> None:
    """AD-979d was consulted; ``count`` peer memories came back, or ``None`` when it raised.

    Never a peer's episode id, callsign or text.
    """
    record = _record(observation)
    if record is not None:
        record.cross_agent = {"ran": True, "failed": count is None, "count": count or 0}


def note_transcript(observation: Any, *, hit: bool, thread_ids: Iterable[str]) -> None:
    """AD-986b ran; whether an excerpt came back, and the id of the room it came from."""
    record = _record(observation)
    if record is not None:
        record.transcript = {
            "ran": True,
            "hit": bool(hit),
            "thread_ids": [_text(thread_id, MAX_ID_CHARS) for thread_id in list(thread_ids)[:MAX_THREADS]],
        }


def note_oracle(observation: Any, scope: str, sources: Iterable[tuple[str, str]] | None) -> None:
    """The passive Oracle lookup ran with ``scope`` ("all", or "graph" for BF-265's query).

    ``sources`` holds the ``(tier, path)`` of each rendered result, from
    ``OracleService.query_formatted(sources_out=...)``, or is ``None`` when the
    query raised. Results are counted per tier; only Ship's Records results are
    identified, by path.
    """
    record = _record(observation)
    if record is None:
        return
    if sources is None:
        record.oracle = {
            "ran": True, "scope": scope, "failed": True, "results": 0, "by_tier": {}, "record_paths": [],
        }
        return
    listed = list(sources)
    by_tier: dict[str, int] = {}
    paths: list[str] = []
    for tier, path in listed:
        name = _text(tier, MAX_SOURCE_CHARS)
        if name in by_tier or len(by_tier) < MAX_TIERS:
            by_tier[name] = by_tier.get(name, 0) + 1
        if name == _IDENTIFIED_TIER and path and len(paths) < MAX_RECORD_PATHS:
            paths.append(_text(path, MAX_PATH_CHARS))
    record.oracle = {
        "ran": True, "scope": scope, "failed": False, "results": len(listed),
        "by_tier": by_tier, "record_paths": paths,
    }


def storable(manifest: dict[str, Any], *, path: str) -> dict[str, Any]:
    """``manifest`` when it encodes as the chat store encodes metadata and fits
    ``MAX_MANIFEST_BYTES``; otherwise a stub that says why it was not recorded.

    ``ChatThreadStore.append_message_once`` refuses metadata that ``json.dumps``
    rejects with ``allow_nan=False``, and the 1:1 route's append catches that
    refusal, so an unstorable manifest would cost the Captain the reply in the
    transcript.
    """
    try:
        encoded = json.dumps(
            manifest,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError):
        return {"v": MANIFEST_VERSION, "path": path, "unrecorded": "unencodable"}
    if len(encoded) > MAX_MANIFEST_BYTES:
        return {"v": MANIFEST_VERSION, "path": path, "unrecorded": "oversize"}
    return manifest


def build_manifest(
    ledger: ContextLedger,
    recall: RecallRecord | None,
    *,
    path: str,
    system_prompt: Any,
    user_message: Any,
    response_text: Any,
    journal_entry_id: str,
) -> dict[str, Any]:
    """The manifest for one reply; ``recall`` is ``None`` when recall did not run."""
    sections, omitted = ledger.to_wire()
    if recall is None:
        recall_wire: dict[str, Any] = {"ran": False}
        lookups: dict[str, Any] = {name: {"ran": False} for name in _LOOKUPS}
    else:
        recall_wire, lookups = recall.to_wire()
    manifest = {
        "v": MANIFEST_VERSION,
        "path": path,
        "sections": sections,
        "sections_omitted": omitted,
        "system_prompt_chars": len(system_prompt) if isinstance(system_prompt, str) else 0,
        "recall": recall_wire,
        "lookups": lookups,
        "prompt_hash": turn_hash(user_message),
        "response_hash": turn_hash(response_text),
        "journal_entry_id": _text(journal_entry_id, MAX_ID_CHARS),
    }
    return storable(manifest, path=path)


def record_manifest(
    observation: Any,
    *,
    path: str,
    system_prompt: Any,
    user_message: Any,
    response_text: Any,
    journal_entry_id: str,
) -> None:
    """Put this turn's manifest on the observation when ``_build_user_message``
    assembled a ``direct_message`` prompt on it.

    An ``Exception`` while building is logged and no manifest is recorded; a
    ``BaseException``, or a failure of the logging itself, propagates.
    """
    ledger = ledger_of(observation)
    if ledger is None:
        return
    try:
        observation[MANIFEST_KEY] = build_manifest(
            ledger,
            _record(observation),
            path=path,
            system_prompt=system_prompt,
            user_message=user_message,
            response_text=response_text,
            journal_entry_id=journal_entry_id,
        )
    except Exception:
        logger.warning(
            "AD-1357: the context manifest for this reply could not be built; "
            "the reply goes out without one",
            exc_info=True,
        )


def context_manifest_metadata(result: Any) -> dict[str, Any]:
    """``{"context_manifest": ...}`` for a stored reply, from ``IntentResult.metadata``.

    ``{}`` when the result carries no non-empty dict under the key, so such a
    reply's metadata is unchanged. An ``Exception`` reading the result gives ``{}``.
    """
    try:
        metadata = getattr(result, "metadata", None)
        manifest = metadata.get(CONTEXT_MANIFEST_METADATA_KEY) if isinstance(metadata, dict) else None
    except Exception:
        return {}
    if type(manifest) is dict and manifest:
        return {CONTEXT_MANIFEST_METADATA_KEY: manifest}
    return {}
