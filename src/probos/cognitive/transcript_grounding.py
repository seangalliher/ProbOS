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

from typing import TYPE_CHECKING, Iterable

from probos.cognitive.episodic import fts_or_query

if TYPE_CHECKING:  # pragma: no cover - typing only
    from probos.threads import ChatThread, ChatThreadMessage, ChatThreadStore


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
    match is deterministic lexical token overlap — no embedding — so the result
    is reproducible and injection is sparse.
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

    best_thread: "ChatThread | None" = None
    best_msgs: list["ChatThreadMessage"] | None = None
    best_score = 0
    for t in threads:
        # Sovereign double-check: never consult a room the agent is not in.
        if not (set(getattr(t, "participants", []) or []) & ids):
            continue
        try:
            msgs = store.list_messages(t.id, limit=400)
        except Exception:
            continue
        score = 0
        for m in msgs:
            score += len(qtokens & _tokens(getattr(m, "body", "")))
        if score > best_score:
            best_score = score
            best_thread = t
            best_msgs = msgs

    if best_thread is None or best_score == 0 or not best_msgs:
        return None
    return _format_excerpt(best_thread, best_msgs, qtokens, max_chars=max_chars)


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
