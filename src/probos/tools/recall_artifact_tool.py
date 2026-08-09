"""AD-1226 (#1197): read back something you produced, without having carried it.

Measured on the reference vessel 2026-08-08: the Captain asked Ezri for the top
fifteen PyPI packages, she delivered the table correctly, and four minutes later
she reported that she could not see what she had sent — then offered to file a
proposal to build the mechanism that would let her. It was already built. The
episode existed, stored at the exact second of delivery, carrying the real table
in ``outcomes[0]["response"]``. Nothing read it back, and the write capped it at
500 of 1362 characters anyway, cutting mid-word at
``| charset-normalizer | 3.4.9 | The Real Fi``.

The Captain's framing is the design:

    "I like the idea of content-addressable ref to the full body on demand ...
    If I asked the agent to write a book, I wouldn't want the entire book to be
    in episodic memory. The agent should be able to know what it wrote and be
    able to refer back to the book as needed."

So the memory carries a *ref*, not a copy, and this tool is how the ref is
spent. It is the AD-1209 shape applied to output rather than to task state: do
not make the agent carry it, give it a way to ask.

Governance: strictly read-only, and scoped to the asking agent's own output. A
lookup that resolves to another crew member's artifact reports not-found rather
than leaking one agent's work into another's context. An empty ``agent_id`` is
not a wildcard.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from probos.tools.protocol import ToolResult, ToolType

logger = logging.getLogger(__name__)

# The shortest ref that identifies one thing. Eight hex characters is 32 bits,
# which is unambiguous across one agent's own artifacts, and it is the same
# floor AD-1209 uses for a quoted work-item id — an agent reading either cue
# out of its own memory meets the same rule.
_MIN_REF_CHARS = 8

# A full SHA-256 in hex. Only an exact hash can be handed to the artifact
# store's by-hash index; anything shorter resolves through the agent's own
# episodes instead.
_FULL_HASH_CHARS = 64

# AD-1226: the per-call ceiling, in characters, and the reason this tool exists
# in the shape it does. A decision, not an inheritance (Design Principle 13a).
#
# The Captain's book example is the requirement: an agent must be able to walk a
# large artifact without ever holding all of it. 4000 characters is roughly a
# thousand tokens — one substantial page. It is large enough that an ordinary
# report (the measured case was 1362 chars) arrives whole in one call, and small
# enough that a book-sized artifact costs the same bounded amount per look no
# matter how large it is. A caller that needs more passes ``next_offset`` back;
# there is no cap on how far it can walk, only on how much arrives at once.
_MAX_CHARS_PER_READ = 4000

# How far back through the agent's own episodes to look for a ref. The cue is
# rendered from a recalled memory, so the ref an agent quotes is by construction
# recent. Bounded because this scan is per-call and must not grow with the size
# of the store.
_EPISODE_SCAN_LIMIT = 50

# Mimes whose bytes are meaningful as text. Anything else is described rather
# than inlined — returning mojibake would be worse than an honest refusal.
_TEXT_MIME_PREFIX = "text/"
_TEXT_MIMES = frozenset({"application/json", "application/xml"})


def _is_text_mime(mime: str) -> bool:
    lowered = str(mime or "").split(";", 1)[0].strip().lower()
    return lowered.startswith(_TEXT_MIME_PREFIX) or lowered in _TEXT_MIMES


def _is_full_hash(ref: str) -> bool:
    return len(ref) == _FULL_HASH_CHARS and all(
        c in "0123456789abcdef" for c in ref
    )


class RecallArtifactTool:
    """AD-1226: read back the full text of an artifact this agent produced.

    Satisfies the AD-423a ``Tool`` protocol (duck-typed). Never raises out of
    ``invoke`` — every miss is an honest-degrade ``ToolResult`` the loop can
    reason over (AD-592).
    """

    def __init__(self, *, runtime: Any) -> None:
        self._runtime = runtime

    # ── Tool protocol ─────────────────────────────────────────────
    @property
    def tool_id(self) -> str:
        return "recall_artifact"

    @property
    def name(self) -> str:
        return "Recall Artifact"

    @property
    def tool_type(self) -> ToolType:
        return ToolType.UTILITY_AGENT

    @property
    def description(self) -> str:
        return (
            "Read back the full text of something you produced earlier — a "
            "report, a table, a document — using the reference shown beside it "
            "in your memory. Use this whenever you are asked about the CONTENT "
            "of your own earlier work: what was in the list you sent, what you "
            "wrote in a section, which figures you quoted. You remember THAT "
            "you produced the thing and where it is; the text itself is kept "
            "outside your memory on purpose, so a long document never fills "
            "your context. Read it back with this rather than describing it "
            "from recollection or producing it a second time. A large artifact "
            "arrives in pieces: pass the returned next_offset back to read the "
            "piece that follows. It is read-only: it reads what was stored and "
            "changes nothing."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "ref": {
                    "type": "string",
                    "description": (
                        "The reference quoted in your memory: the content hash "
                        "(a prefix of at least 8 characters is accepted) or the "
                        "artifact's name."
                    ),
                },
                "offset": {
                    "type": "integer",
                    "description": (
                        "Character position to start reading from. Omit for the "
                        "beginning; pass the next_offset from a previous read to "
                        "continue where it stopped."
                    ),
                    "default": 0,
                },
            },
            "required": ["ref"],
        }

    @property
    def output_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    # ── Execution ─────────────────────────────────────────────────
    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None,
    ) -> ToolResult:
        t0 = time.monotonic()
        ctx = context or {}
        agent_id = str(ctx.get("agent_id") or "")
        thread_id = str(ctx.get("thread_id") or "")
        raw = params or {}
        ref = str(raw.get("ref") or "").strip()
        offset = self._coerce_offset(raw.get("offset"))

        def _done(output: dict[str, Any]) -> ToolResult:
            return ToolResult(
                output=output, error=None, duration_ms=(time.monotonic() - t0) * 1000.0,
            )

        if len(ref) < _MIN_REF_CHARS:
            return _done({
                "found": False,
                "reason": (
                    f"a reference of at least {_MIN_REF_CHARS} characters is "
                    "needed to identify one artifact"
                ),
            })

        if not agent_id:
            # Ownership scoping: an anonymous caller reads nothing. Treating an
            # absent identity as "everything" would make every synthetic runtime
            # a hole in the scope rule.
            return _done({
                "found": False,
                "ref": ref,
                "reason": "the caller's identity is unknown, so nothing is readable",
            })

        attachment_store = getattr(self._runtime, "attachment_store", None)
        if attachment_store is None:
            return _done({
                "found": False,
                "ref": ref,
                "reason": "stored artifacts are not available on this ship",
            })

        try:
            located = await self._resolve(ref, agent_id, thread_id)
        except Exception:  # noqa: BLE001 — a lookup fault must not fail the turn
            logger.warning(
                "AD-1226: resolving artifact ref %r for agent %s failed; the "
                "agent receives a not-found result and continues the turn",
                ref, agent_id, exc_info=True,
            )
            return _done({
                "found": False,
                "ref": ref,
                "reason": "the artifact record could not be read just now",
            })

        if located is None:
            return _done({
                "found": False,
                "ref": ref,
                "reason": (
                    "no artifact with that reference belongs to you. It may "
                    "belong to another crew member, or the reference may be "
                    "wrong."
                ),
            })

        mime = str(located.get("mime") or "")
        if not _is_text_mime(mime):
            # Honest about what is there rather than decoding bytes that were
            # never text.
            return _done({
                **self._identity(located, ref),
                "found": True,
                "readable_as_text": False,
                "text": "",
                "total_chars": 0,
                "offset": 0,
                "next_offset": None,
                "truncated": False,
                "reason": (
                    f"this artifact is {mime or 'binary'} data, so it is stored "
                    "but is not meaningful as text"
                ),
            })

        try:
            blob = await attachment_store.read(located["content_hash"])
        except Exception:  # noqa: BLE001 — a missing blob must not fail the turn
            logger.warning(
                "AD-1226: the bytes for artifact %s (agent %s) could not be "
                "read; the record exists but the text is gone, so the agent is "
                "told so instead of receiving an empty document",
                str(located.get("content_hash", ""))[:12], agent_id, exc_info=True,
            )
            return _done({
                **self._identity(located, ref),
                "found": False,
                "reason": "the artifact is recorded but its text could not be read",
            })

        # ``errors="replace"`` rather than a raise: a byte sequence that is not
        # valid UTF-8 inside a text/* artifact is a storage anomaly, and losing
        # one character is a better outcome for the turn than losing the read.
        text = bytes(blob or b"").decode("utf-8", errors="replace")
        return _done(self._page(text, offset, located, ref))

    # ── Internals ─────────────────────────────────────────────────
    @staticmethod
    def _coerce_offset(value: Any) -> int:
        """A malformed offset reads from the beginning rather than failing."""
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _identity(located: dict[str, Any], ref: str) -> dict[str, Any]:
        return {
            "ref": ref,
            "name": str(located.get("name") or ""),
            "content_hash": str(located.get("content_hash") or ""),
            "mime": str(located.get("mime") or ""),
            "size_bytes": int(located.get("size_bytes") or 0),
        }

    def _page(
        self, text: str, offset: int, located: dict[str, Any], ref: str,
    ) -> dict[str, Any]:
        """Return one bounded window of ``text`` plus how to continue."""
        total = len(text)
        start = min(offset, total)
        chunk = text[start:start + _MAX_CHARS_PER_READ]
        end = start + len(chunk)
        more = end < total
        return {
            **self._identity(located, ref),
            "found": True,
            "readable_as_text": True,
            "total_chars": total,
            "offset": start,
            "next_offset": end if more else None,
            "truncated": more,
            "text": chunk,
        }

    async def _resolve(
        self, ref: str, agent_id: str, thread_id: str,
    ) -> dict[str, Any] | None:
        """Find an artifact by hash, hash-prefix or name, scoped to this agent.

        The agent's own episodes come first: they are the index that carries
        prefixes and names, and they are scoped by construction because an
        episode is only returned for the agent whose experience it was. The
        artifact store is the second route, for an exact hash or a name inside
        the current thread, and is scoped by ``created_by``.
        """
        lowered = ref.lower()
        for identity in self._identities(agent_id):
            hit = await self._resolve_from_episodes(lowered, ref, identity)
            if hit is not None:
                return hit
        return self._resolve_from_artifacts(lowered, ref, agent_id, thread_id)

    def _identities(self, agent_id: str) -> list[str]:
        """The ids under which THIS agent's episodes may be filed.

        Episodes are stored under the sovereign id (BF-103) while the tool
        context carries the id the loop is running as. Both name the same
        agent — ``registry.get(agent_id)`` is what makes that true — so
        consulting both widens nothing.
        """
        ids = [agent_id]
        try:
            registry = getattr(self._runtime, "registry", None)
            agent = registry.get(agent_id) if registry is not None else None
            if agent is not None:
                from probos.cognitive.episodic import resolve_sovereign_id

                sovereign = resolve_sovereign_id(agent)
                if sovereign and sovereign not in ids:
                    ids.append(sovereign)
        except Exception:
            logger.debug(
                "AD-1226: could not resolve a sovereign id for %s; only the "
                "caller's own id is searched",
                agent_id, exc_info=True,
            )
        return ids

    async def _resolve_from_episodes(
        self, lowered: str, ref: str, identity: str,
    ) -> dict[str, Any] | None:
        memory = getattr(self._runtime, "episodic_memory", None)
        recent = getattr(memory, "recent_for_agent", None)
        if not identity or not callable(recent):
            return None
        for ep in await recent(identity, k=_EPISODE_SCAN_LIMIT) or []:
            outcomes = getattr(ep, "outcomes", None)
            if not isinstance(outcomes, list):
                continue
            for outcome in outcomes:
                if not isinstance(outcome, dict):
                    continue
                art = outcome.get("artifact_ref")
                if not isinstance(art, dict):
                    continue
                content_hash = str(art.get("content_hash") or "")
                name = str(art.get("name") or "")
                if not content_hash:
                    continue
                if content_hash.lower().startswith(lowered) or (
                    name and name == ref
                ):
                    return {
                        "content_hash": content_hash,
                        "name": name,
                        "mime": str(art.get("mime") or ""),
                        "size_bytes": int(art.get("size_bytes") or 0),
                    }
        return None

    def _resolve_from_artifacts(
        self, lowered: str, ref: str, agent_id: str, thread_id: str,
    ) -> dict[str, Any] | None:
        store = getattr(self._runtime, "artifact_store", None)
        if store is None:
            return None
        art = None
        finder = getattr(store, "find_first_by_hash", None)
        if callable(finder) and _is_full_hash(lowered):
            art = finder(lowered)
        if art is None and not _is_full_hash(lowered):
            # AD-1227: the prompt prints a 12-char prefix, so the store must be
            # able to resolve one. Without this the only prefix route was the
            # 50-episode recall window, and an artifact whose episode had aged
            # out was named in the prompt and then unreadable.
            by_prefix = getattr(store, "find_by_hash_prefix", None)
            if callable(by_prefix):
                art = by_prefix(lowered, created_by=agent_id)
        if art is None and thread_id:
            latest = getattr(store, "latest", None)
            if callable(latest):
                art = latest(thread_id=thread_id, name=ref)
        if art is None:
            return None
        # Ownership: reporting another crew member's output would leak one
        # agent's work into another's context.
        if str(getattr(art, "created_by", "") or "") != agent_id:
            return None
        return {
            "content_hash": str(getattr(art, "content_hash", "") or ""),
            "name": str(getattr(art, "name", "") or ""),
            "mime": str(getattr(art, "mime", "") or ""),
            "size_bytes": int(getattr(art, "size_bytes", 0) or 0),
        }
