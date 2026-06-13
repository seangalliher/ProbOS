"""AD-986b: transcript-grounded recall — consult the canonical record.

The sovereign episodic shard is a *subjective*, reconstructive, lossy recollection
of a conversation (by design — that keeps recall honest and identity coherent).
The ``ChatThreadStore`` transcript is the *objective* record — the verbatim,
ordered, participant-scoped recording of what was actually said.

This module is the coupling between the two: given a query and the set of an
agent's OWN identifiers, it finds the rooms that agent took part in, lexically
matches the query against the transcript, and returns a bounded excerpt of the
recording — so an agent can ground a recollection in what was actually said
rather than guess (or reconstruct from a peer's fallible memory). The excerpt is
rendered into the prompt clearly labeled as the recording, distinct from
subjective memory (see :func:`render_transcript_grounding`).

Sovereign scope is load-bearing: an agent may ONLY consult transcripts of rooms
it is a participant in. The matcher is the deterministic AD-979c lexical
tokenizer (no embedding on the recall hot path) and returns ``None`` when nothing
meaningfully matches, so injection is naturally sparse.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Iterable

from probos.cognitive.episodic import fts_or_query

if TYPE_CHECKING:  # pragma: no cover - typing only
    from probos.threads import (
        ChatThread,
        ChatThreadMessage,
        ChatThreadStore,
        ChatThreadTombstone,
    )

# BF-625: room ranking. The v1 scorer summed raw query-token overlap across
# every message, so a long catch-all 1:1 room won on sheer volume of common
# words ("the"/"you"/"have") and outranked the actual group chat a query named.
# The fix ranks each room by IDF-weighted BM25 *body* relevance (term-frequency
# saturation + length normalisation, so volume alone can't win) plus a strongly
# weighted *title* field. For a group room the title IS the participant callsign
# list (AD-942), so a query that names a participant/topic ("the chat with Yeo")
# matches the room's identity — the strongest "which conversation" signal.
_BM25_K1 = 1.5
_BM25_B = 0.75
_TITLE_FIELD_WEIGHT = 12.0


def _tokens(text: str) -> set[str]:
    """Deterministic lexical token set, reusing the AD-979c tokenizer.

    ``fts_or_query`` lowercases, splits on non-alphanumerics, drops <2-char
    tokens, and dedupes, returning a quoted ``OR`` string (or ``""``). This
    recovers the bare tokens as a set.
    """
    q = fts_or_query(text or "")
    if not q:
        return set()
    return {term.strip('"') for term in q.split(" OR ")}


def _speaker(msg: "ChatThreadMessage") -> str:
    """Human label for a transcript line: 'Captain', a callsign, or the author id."""
    role = getattr(msg, "role", "") or ""
    if role == "captain":
        return "Captain"
    meta = getattr(msg, "metadata", None) or {}
    if isinstance(meta, dict):
        cs = meta.get("callsign")
        if cs:
            return str(cs)
    return getattr(msg, "author_id", "") or "crew"


def _format_excerpt(
    thread: "ChatThread",
    msgs: list["ChatThreadMessage"],
    qtokens: set[str],
    *,
    max_chars: int,
) -> str | None:
    """Render a bounded excerpt centred on the query-matching messages.

    Each matching message plus its immediate neighbours (±1) is kept, rendered
    in transcript order as ``<speaker>: <body>`` lines under a room header, and
    truncated to ``max_chars``. Returns ``None`` if no message matches.
    """
    match_idx = [
        i for i, m in enumerate(msgs)
        if qtokens & _tokens(getattr(m, "body", ""))
    ]
    if not match_idx:
        return None
    keep: set[int] = set()
    for i in match_idx:
        for j in (i - 1, i, i + 1):
            if 0 <= j < len(msgs):
                keep.add(j)
    title = getattr(thread, "title", "") or "group chat"
    out_lines = [f"Room: {title}"]
    used = len(out_lines[0])
    for i in sorted(keep):
        m = msgs[i]
        body = " ".join((getattr(m, "body", "") or "").split())
        if not body:
            continue
        line = f"{_speaker(m)}: {body}"
        if used + len(line) + 1 > max_chars and len(out_lines) > 1:
            out_lines.append("\u2026")
            break
        out_lines.append(line)
        used += len(line) + 1
    if len(out_lines) <= 1:
        return None
    return "\n".join(out_lines)


def consult_transcript(
    store: "ChatThreadStore",
    agent_ids: Iterable[str],
    query: str,
    *,
    max_threads: int = 8,
    max_chars: int = 1200,
) -> str | None:
    """Return a bounded excerpt of the canonical transcript (the recording) for
    the room — among those the agent participated in — that best matches
    ``query``; or ``None`` when nothing meaningfully matches.

    ``agent_ids`` is the set of the agent's OWN identifiers (id / sovereign_id);
    only rooms containing one of them are ever consulted (sovereign scope). The
    match is deterministic — no embedding — so the result is reproducible and
    injection is sparse. Rooms are ranked (BF-625) by IDF-weighted BM25 *body*
    relevance plus a strongly weighted *title* field, so a long catch-all room
    cannot outrank the actual group chat a query names by participant or topic.
    """
    qtokens = _tokens(query)
    if not qtokens:
        return None
    ids = {a for a in agent_ids if a}
    if not ids:
        return None
    try:
        threads = store.threads_for_participant(ids, limit=max_threads)
    except Exception:
        return None

    # Gather sovereign-scoped candidates with their per-room term frequencies.
    candidates: list[
        tuple["ChatThread", list["ChatThreadMessage"], Counter, int, set[str]]
    ] = []
    for t in threads:
        # Sovereign double-check: never consult a room the agent is not in.
        if not (set(getattr(t, "participants", []) or []) & ids):
            continue
        try:
            msgs = store.list_messages(t.id, limit=400)
        except Exception:
            continue
        tf: Counter = Counter()
        for m in msgs:
            for tok in _tokens(getattr(m, "body", "")):
                tf[tok] += 1
        title_tokens = _tokens(getattr(t, "title", "") or "")
        candidates.append((t, msgs, tf, sum(tf.values()), title_tokens))

    if not candidates:
        return None

    # Document frequency over the candidate set (presence in body OR title) so
    # ubiquitous words self-neutralise via IDF without a hand-picked stop-list.
    n_docs = len(candidates)
    df: dict[str, int] = {}
    for _t, _msgs, tf, _dl, title_tokens in candidates:
        present = set(tf) | title_tokens
        for tok in (qtokens & present):
            df[tok] = df.get(tok, 0) + 1

    def _idf(tok: str) -> float:
        d = df.get(tok, 0)
        if d <= 0:
            return 0.0
        # BM25 smoothed IDF: a token in one room scores high; one in every room
        # scores near zero. Always > 0 for a present token (single-room safe).
        return math.log(1.0 + (n_docs - d + 0.5) / (d + 0.5))

    avgdl = sum(dl for _t, _m, _tf, dl, _tt in candidates) / n_docs

    best_thread: "ChatThread | None" = None
    best_msgs: list["ChatThreadMessage"] | None = None
    best_score = 0.0
    best_focus: set[str] = set()
    for t, msgs, tf, doc_len, title_tokens in candidates:
        matched: set[str] = set()
        # Body relevance via BM25: TF saturation + length normalisation means a
        # long room cannot win on volume of common words alone.
        body = 0.0
        for tok in (qtokens & set(tf)):
            idf = _idf(tok)
            if idf <= 0.0:
                continue
            freq = tf[tok]
            denom = freq + _BM25_K1 * (
                1.0 - _BM25_B + _BM25_B * (doc_len / avgdl if avgdl else 0.0)
            )
            if denom:
                body += idf * (freq * (_BM25_K1 + 1.0)) / denom
                matched.add(tok)
        # Title field: the room's identity (participants/topic), weighted high.
        title = 0.0
        for tok in (qtokens & title_tokens):
            idf = _idf(tok)
            if idf > 0.0:
                title += idf
                matched.add(tok)
        score = body + _TITLE_FIELD_WEIGHT * title
        if score > best_score:
            best_score = score
            best_thread = t
            best_msgs = msgs
            best_focus = matched

    if best_thread is None or best_score <= 0.0 or not best_msgs:
        return None
    # Centre the excerpt on the content tokens that won the room (not stopwords);
    # fall back to all query tokens if a title-only match leaves no body line.
    excerpt = _format_excerpt(
        best_thread, best_msgs, best_focus or qtokens, max_chars=max_chars
    )
    if excerpt is None and best_focus:
        excerpt = _format_excerpt(
            best_thread, best_msgs, qtokens, max_chars=max_chars
        )
    return excerpt


def render_transcript_grounding(excerpt: str) -> list[str]:
    """The labeled prompt block for a transcript excerpt — rendered DISTINCT
    from subjective recalled memory so the agent never conflates the recording
    with its own recollection (and may quote/ground against it honestly)."""
    return [
        "=== CANONICAL TRANSCRIPT (the recording) ===",
        "The verbatim record of a room you took part in. This is the recording, "
        "NOT your memory \u2014 you may quote it and ground your recollection in it "
        "to be accurate about what was actually said.",
        excerpt,
        "=== END TRANSCRIPT ===",
    ]


def purged_room_notice(
    store: "ChatThreadStore",
    agent_ids: Iterable[str],
    query: str,
    *,
    max_tombstones: int = 8,
) -> str | None:
    """AD-986d: return an honest notice that a room's recording — one this agent
    took part in, and whose subject the ``query`` touches — has been PURGED under
    the retention policy; or ``None`` when no purged room meaningfully matches.

    The complement of :func:`consult_transcript`: when the live recording is gone
    but the agent may still hold a subjective memory of the room, this is how it
    learns the recording can no longer be consulted (so it does not treat its
    lossy recollection as the complete picture). Sovereign-scoped (only rooms the
    agent participated in) and matched lexically against the purged room's title
    — the message bodies are deleted by definition, so the title is the signal.
    """
    qtokens = _tokens(query)
    if not qtokens:
        return None
    ids = {a for a in agent_ids if a}
    if not ids:
        return None
    try:
        tombstones = store.tombstones_for_participant(ids, limit=max_tombstones)
    except Exception:
        return None

    best: "ChatThreadTombstone | None" = None
    best_score = 0
    for ts in tombstones:
        # Sovereign double-check: never reference a room the agent was not in.
        if not (set(getattr(ts, "participants", []) or []) & ids):
            continue
        score = len(qtokens & _tokens(getattr(ts, "title", "")))
        if score > best_score:
            best_score = score
            best = ts
    if best is None or best_score == 0:
        return None

    title = (getattr(best, "title", "") or "").strip() or "a group chat"
    try:
        when = datetime.fromtimestamp(
            float(getattr(best, "purged_at", 0.0)), tz=timezone.utc
        ).strftime("%Y-%m-%d")
    except (ValueError, OverflowError, OSError):
        when = "an earlier date"
    return (
        f'The recording of the room "{title}" was purged on {when} (UTC) under the '
        "transcript-retention policy. You may still hold your own memory of it, but "
        "the canonical recording can no longer be consulted to verify the details."
    )


def render_purge_indication(notice: str) -> list[str]:
    """The labeled prompt block for an AD-986d purge notice — rendered distinct
    from both subjective memory and a live transcript, so the agent is honest
    that the recording is gone and calibrates its confidence accordingly."""
    return [
        "=== RECORDING PURGED (retention) ===",
        notice,
        "If asked about this conversation, be honest that the recording is no "
        "longer available and that you are relying on your own memory, which may "
        "be incomplete.",
        "=== END RECORDING PURGED ===",
    ]
