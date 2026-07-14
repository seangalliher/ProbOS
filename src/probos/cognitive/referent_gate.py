"""AD-1119: Referent-Grounding Gate (guard G1) — cascade-confabulation prevention.

Live-runtime forensics (2026-07-08) traced a crew "Oracle Health Check"
investigation that reasoned at length about node ``e77acec7`` — a *fabricated*
identifier that is not a git object, an agent, a ward-room channel, or in any
source file / DB. The root mechanism: **no agent verifies that an identifier or
entity exists before reasoning about it**. This module resolves candidate
referents against ship ground truth *before* the crew builds an investigation
on them, and — for strongly asserted unresolved ones — produces a gap-regex-safe
honest-absence cue.

Layer: COGNITIVE. The module is ``runtime``-free (DIP): the gate depends only on
a ``list`` of constructor-injected ``ReferentResolver`` protocol objects, and the
concrete resolvers take narrow deps (registry / callsign registry / ward room /
repo root) — never the runtime. It imports nothing from a higher layer.

Scope (AD-1119 only): this is the deterministic *guard* half. It EXTRACTS,
RESOLVES, and computes the cue. It does NOT inject the cue into any agent's
context (that is AD-1120) and does NOT run a divergence probe or persist a
transcript (that is AD-1121).
"""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

logger = logging.getLogger(__name__)

# Verdict labels (single source of truth for the RESOLVED/UNRESOLVED strings).
RESOLVED = "RESOLVED"
UNRESOLVED = "UNRESOLVED"

# Extraction cap: bound the number of referents evaluated per seed so a
# pathological message cannot fan out into dozens of git subprocesses.
_MAX_REFERENTS = 20

# --- DD-5/BF-667 extraction regexes -------------------------------------------
# hex: a git-SHA / node-id shape. The lookahead requires >=1 a-f letter so a
# plain decimal (e.g. 1234567) is excluded (that is a number, not an id).
_HEX_RE = re.compile(r"\b(?=[0-9a-fA-F]*[a-fA-F])[0-9a-fA-F]{7,40}\b")
# BF-667: source syntax carries assertion strength. Matching ASCII quotes around
# one token are explicit; `node id <token>` is the existing unquoted explicit
# marker; bare locator tokens remain worth resolving but are only implicit when
# alphabetic. Keep these scanners separate so an incomplete `node id` marker
# cannot fall through to a false token `id`.
_QUOTED_ENTITY_RE = re.compile(
    r'''\b(?:node(?:\s+id)?|record|entity)\s+'''
    r'''(?P<quote>["'])(?P<token>[A-Za-z0-9_\-]{2,64})(?P=quote)'''
    r'''(?![A-Za-z0-9_\-])''',
    re.IGNORECASE,
)
_EXPLICIT_NODE_ID_RE = re.compile(
    r"\bnode\s+id\s+([A-Za-z0-9_\-]{2,64})\b",
    re.IGNORECASE,
)
_BARE_ENTITY_RE = re.compile(
    r"\b(node|record|entity)\s+([A-Za-z0-9_\-]{2,64})\b",
    re.IGNORECASE,
)
_ENTITY_GRAMMAR_STOP_WORDS = frozenset(
    {
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "shows",
        "showed",
        "showing",
        "has",
        "have",
        "had",
        "does",
        "did",
        "will",
        "would",
        "can",
        "could",
        "should",
        "seems",
        "appears",
        "indicates",
        "exists",
        "may",
        "not",
        "of",
        "to",
        "the",
        "this",
        "that",
        "these",
        "those",
        "a",
        "an",
    }
)
# service: a conservative "asserted live system" span — a Capitalized word (or a
# `*_service` snake token) immediately followed by one of the system keywords.
# Deliberately case-sensitive on the leading name to bound false positives (an
# ordinary lowercase "the membership" must NOT match).
_SERVICE_RE = re.compile(
    r"\b([A-Z][A-Za-z0-9]*|[A-Za-z0-9_]*_service)\s+"
    r"(?:service|membership|telemetry|cluster|node)\b"
)
_ENTITY_LOCATOR_KEYWORDS = frozenset({"node", "record", "entity"})
_SERVICE_ROLE_KEYWORDS = frozenset(
    {"service", "membership", "telemetry", "cluster", "node"}
)

# BF-667 correction: lower values are stronger source evidence. This private
# ordering lets later explicit/quoted entity syntax replace an earlier strong
# but less-actionable service or bare-machine interpretation in place, while an
# implicit bare name never downgrades strong evidence. Hex remains preferred
# when its token position overlaps a locator scanner.
_EVIDENCE_PRIORITY = {
    "hex": 0,
    "explicit_entity": 0,
    "bare_machine_entity": 1,
    "service": 2,
    "implicit_entity": 3,
}

# Code-span strippers: fenced ``` blocks first (non-greedy, DOTALL), then inline
# `code` spans — so a sha inside a code fence is NOT extracted. Protected spans
# become same-width non-whitespace barriers: this preserves every source offset
# while preventing a locator before code from bridging to prose after it.
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_CODE_SPAN_BARRIER = "\x00"


@dataclass(frozen=True)
class Referent:
    """A candidate referent extracted from a message.

    ``token`` is the resolvable identifier; ``kind`` is one of ``hex`` /
    ``entity`` / ``service`` (a label for logging); ``raw`` is the matched span;
    ``claim_confidence`` is source-syntax assertion strength, not resolver
    confidence.
    """

    token: str
    kind: str
    raw: str
    claim_confidence: Literal["strong", "implicit"] = "strong"


@dataclass(frozen=True)
class GroundingVerdict:
    """The outcome of grounding a message's referents.

    ``results`` is the unchanged resolver result map from each token to
    ``RESOLVED`` / ``UNRESOLVED``; ``unresolved`` is the ordered tuple of
    actionable strong unconfirmed tokens; ``cues`` maps each actionable token
    to its honest-absence cue; ``ambiguous`` holds implicit unconfirmed tokens
    that receive no cue or action.
    """

    results: dict[str, str]
    unresolved: tuple[str, ...]
    cues: dict[str, str]
    ambiguous: tuple[str, ...] = ()

    @property
    def has_unresolved(self) -> bool:
        """True when at least one actionable strong referent is unconfirmed."""
        return bool(self.unresolved)


def _strip_code_spans(text: str) -> str:
    """Protect fenced and inline code with same-width scanner barriers."""

    def _barrier(match: re.Match[str]) -> str:
        return _CODE_SPAN_BARRIER * len(match.group(0))

    text = _FENCE_RE.sub(_barrier, text)
    text = _INLINE_CODE_RE.sub(_barrier, text)
    return text


def _classify_entity_claim(
    token: str,
    syntax: Literal["quoted", "explicit", "bare"],
) -> Literal["strong", "implicit"] | None:
    """Classify assertion strength from source syntax, never token meaning."""
    if syntax == "quoted":
        return "strong"
    if token.casefold() in _ENTITY_GRAMMAR_STOP_WORDS:
        return None
    if syntax == "explicit" or any(
        char.isdigit() or char in "_-" for char in token
    ):
        return "strong"
    return "implicit"


def _is_service_identifier(token: str) -> bool:
    """Reject only names that are structural grammar roles in existing scans."""
    folded = token.casefold()
    return (
        folded not in _ENTITY_GRAMMAR_STOP_WORDS
        and folded not in _ENTITY_LOCATOR_KEYWORDS
        and folded not in _SERVICE_ROLE_KEYWORDS
    )


def extract_referents(text: str) -> list[Referent]:
    """Extract candidate referents from ``text`` (pure, no I/O).

    Strips code spans first (DD-5), classifies assertion strength from source
    syntax, orders by first token appearance and stable syntax priority, and
    dedupes by exact token. First-seen position wins, but later higher-priority
    syntax promotes less-actionable metadata in place, including after the
    unique-token cap is reached. Returns ``[]`` for empty / whitespace text.
    """
    if not text:
        return []
    stripped = _strip_code_spans(text)
    # (token_start, syntax_priority, evidence_priority, token, kind, raw,
    # claim_confidence).
    # Hex priority preserves the existing interpretation when the same token is
    # independently matched by `_HEX_RE` and a locator scanner at one position.
    matches: list[
        tuple[
            int,
            int,
            int,
            str,
            str,
            str,
            Literal["strong", "implicit"],
        ]
    ] = []
    for m in _HEX_RE.finditer(stripped):
        matches.append(
            (
                m.start(),
                0,
                _EVIDENCE_PRIORITY["hex"],
                m.group(0),
                "hex",
                m.group(0),
                "strong",
            )
        )
    for m in _QUOTED_ENTITY_RE.finditer(stripped):
        token = m.group("token")
        matches.append(
            (
                m.start("token"),
                1,
                _EVIDENCE_PRIORITY["explicit_entity"],
                token,
                "entity",
                m.group(0),
                "strong",
            )
        )
    for m in _EXPLICIT_NODE_ID_RE.finditer(stripped):
        token = m.group(1)
        confidence = _classify_entity_claim(token, "explicit")
        if confidence is not None:
            matches.append(
                (
                    m.start(1),
                    2,
                    _EVIDENCE_PRIORITY["explicit_entity"],
                    token,
                    "entity",
                    m.group(0),
                    confidence,
                )
            )
    for m in _BARE_ENTITY_RE.finditer(stripped):
        locator = m.group(1)
        token = m.group(2)
        if locator.casefold() == "node" and token.casefold() == "id":
            continue
        confidence = _classify_entity_claim(token, "bare")
        if confidence is not None:
            evidence_priority = _EVIDENCE_PRIORITY[
                "bare_machine_entity"
                if confidence == "strong"
                else "implicit_entity"
            ]
            matches.append(
                (
                    m.start(2),
                    3,
                    evidence_priority,
                    token,
                    "entity",
                    m.group(0),
                    confidence,
                )
            )
    for m in _SERVICE_RE.finditer(stripped):
        token = m.group(1)
        if _is_service_identifier(token):
            matches.append(
                (
                    m.start(1),
                    4,
                    _EVIDENCE_PRIORITY["service"],
                    token,
                    "service",
                    m.group(0),
                    "strong",
                )
            )
    matches.sort(key=lambda candidate: (candidate[0], candidate[1]))
    found: list[Referent] = []
    positions: dict[str, int] = {}
    evidence_priorities: dict[str, int] = {}
    for (
        _start,
        _syntax_priority,
        evidence_priority,
        token,
        kind,
        raw,
        confidence,
    ) in matches:
        existing_index = positions.get(token)
        if existing_index is not None:
            if evidence_priority < evidence_priorities[token]:
                found[existing_index] = Referent(
                    token=token,
                    kind=kind,
                    raw=raw,
                    claim_confidence=confidence,
                )
                evidence_priorities[token] = evidence_priority
            continue
        if len(found) >= _MAX_REFERENTS:
            continue
        positions[token] = len(found)
        evidence_priorities[token] = evidence_priority
        found.append(
            Referent(
                token=token,
                kind=kind,
                raw=raw,
                claim_confidence=confidence,
            )
        )
    return found


class ReferentResolver(Protocol):
    """A ground-truth resolver for a single referent token.

    ``kind`` is a short label for logging. ``resolve`` returns True only when the
    resolver CONFIRMS the token exists; it must honest-degrade to False on any
    operational failure. Task cancellation remains control flow and propagates.
    """

    kind: str

    async def resolve(self, token: str) -> bool:  # pragma: no cover - protocol
        ...


@dataclass(frozen=True)
class _GitProcessResult:
    """Small cross-thread result for one ``git cat-file`` process."""

    returncode: int | None = None
    timed_out: bool = False
    cancelled: bool = False
    start_error: OSError | None = None


class GitObjectResolver:
    """Confirm a token is a real git object via ``git cat-file -e <token>^{object}``.

    ``^{object}`` matches any object type (blob/tree/commit/tag) and resolves
    abbreviations + packed objects, so an 8-char prefix like ``e77acec7`` is
    checked correctly (a raw ``.git/objects/`` filesystem probe could not).
    Honest-degrades to False: a missing git binary / non-repo ``cwd`` / non-zero
    exit / timeout all return False (logged), never a false True. Task
    cancellation kills and reaps the child before propagating.
    """

    kind = "git"
    _POLL_INTERVAL_SECONDS = 0.01

    def __init__(self, *, repo_root: Path | None = None, timeout: float = 5.0) -> None:
        # Default anchors to the repo root (src/probos/cognitive/ -> parents[3]);
        # overridable so a test injects a real tmp_path git repo (DD-2).
        self._repo_root = repo_root or Path(__file__).resolve().parents[3]
        self._timeout = timeout

    async def resolve(self, token: str) -> bool:
        """Return True iff ``token`` resolves to a git object under ``repo_root``."""
        cancel_requested = threading.Event()
        worker = asyncio.get_running_loop().run_in_executor(
            None,
            self._resolve_sync,
            token,
            cancel_requested,
        )
        try:
            result = await asyncio.shield(worker)
        except asyncio.CancelledError:
            cancel_requested.set()
            try:
                await asyncio.shield(worker)
            except Exception:
                logger.warning(
                    "BF-660 GitObjectResolver: cancellation cleanup worker "
                    "failed for token=%r; cancellation will still propagate",
                    token,
                    exc_info=True,
                )
            raise
        except Exception:
            logger.warning(
                "AD-1119 GitObjectResolver: git cat-file failed for token=%r; "
                "treating as unresolved",
                token,
                exc_info=True,
            )
            return False

        if result.start_error is not None:
            logger.debug(
                "AD-1119 GitObjectResolver: git unavailable for token=%r cwd=%s "
                "(%s); treating as unresolved",
                token,
                self._repo_root,
                result.start_error,
            )
            return False
        if result.timed_out:
            logger.warning(
                "AD-1119 GitObjectResolver: git cat-file timed out after %.1fs for "
                "token=%r; treating as unresolved",
                self._timeout,
                token,
            )
            return False
        return result.returncode == 0

    def _resolve_sync(
        self,
        token: str,
        cancel_requested: threading.Event,
    ) -> _GitProcessResult:
        """Run one selector-compatible Git probe in a worker thread."""
        if cancel_requested.is_set():
            return _GitProcessResult(cancelled=True)

        proc: subprocess.Popen[bytes] | None = None
        try:
            try:
                proc = subprocess.Popen(
                    ["git", "cat-file", "-e", "--", f"{token}^{{object}}"],
                    cwd=str(self._repo_root),
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    shell=False,
                )
            except (FileNotFoundError, NotADirectoryError, OSError) as exc:
                return _GitProcessResult(start_error=exc)

            deadline = time.monotonic() + max(0.0, self._timeout)
            while True:
                returncode = proc.poll()
                if returncode is not None:
                    return _GitProcessResult(returncode=returncode)
                if cancel_requested.is_set():
                    self._kill_and_reap(proc)
                    return _GitProcessResult(cancelled=True)
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    self._kill_and_reap(proc)
                    return _GitProcessResult(timed_out=True)
                cancel_requested.wait(
                    min(self._POLL_INTERVAL_SECONDS, remaining)
                )
        finally:
            if proc is not None and proc.poll() is None:
                self._kill_and_reap(proc)

    @staticmethod
    def _kill_and_reap(proc: subprocess.Popen[bytes]) -> None:
        """Kill ``proc`` and synchronously reap it before returning."""
        try:
            proc.kill()
        except OSError:
            pass
        proc.wait()


class AgentResolver:
    """Confirm a token names a live-or-resting crew member.

    Confirmed if ANY of: the registry knows the agent id, the registry has a
    non-empty pool by that name, or the callsign registry resolves it. Callsign
    existence is LIVENESS-INDEPENDENT (``resolve`` returns a dict even when the
    agent_id is None for a resting crew member), so ``is not None`` is the
    correct existence test. Honest-degrades to False on any failure.
    """

    kind = "agent"

    def __init__(self, registry: Any, callsign_registry: Any) -> None:
        self._registry = registry
        self._callsign_registry = callsign_registry

    async def resolve(self, token: str) -> bool:
        """Return True iff ``token`` is a known agent id / pool / callsign."""
        try:
            if self._registry is not None:
                if self._registry.get(token) is not None:
                    return True
                if self._registry.get_by_pool(token):
                    return True
            if self._callsign_registry is not None:
                if self._callsign_registry.resolve(token) is not None:
                    return True
        except Exception:
            logger.warning(
                "AD-1119 AgentResolver: lookup failed for token=%r; treating as "
                "unresolved",
                token,
                exc_info=True,
            )
            return False
        return False


class WardRoomResolver:
    """Confirm a token names a ward-room channel.

    Guards ``ward_room is None`` (``runtime.ward_room`` is None until ``start()``)
    — None returns False. Honest-degrades to False on any failure.
    """

    kind = "ward_room"

    def __init__(self, ward_room: Any) -> None:
        self._ward_room = ward_room

    async def resolve(self, token: str) -> bool:
        """Return True iff ``token`` names an existing ward-room channel."""
        if self._ward_room is None:
            return False
        try:
            channel = await self._ward_room.get_channel_by_name(token)
        except Exception:
            logger.warning(
                "AD-1119 WardRoomResolver: get_channel_by_name failed for token=%r; "
                "treating as unresolved",
                token,
                exc_info=True,
            )
            return False
        return channel is not None


class ReferentGroundingGate:
    """Resolve a message's referents against ground truth (DIP: injected resolvers).

    Resolution policy (DD-2): for each extracted referent, try ALL resolvers in
    order; the FIRST True marks it RESOLVED. All-False remains UNRESOLVED in the
    result map, while source syntax decides actionability: strong claims receive
    an honest-absence cue and implicit claims enter the non-actionable ambiguous
    lane. ``evaluate`` NEVER raises — a catastrophic failure returns an empty
    verdict (logged), and each resolver call is individually wrapped so one
    raising resolver is treated as False and the referent falls through.
    """

    def __init__(self, resolvers: list[ReferentResolver]) -> None:
        self._resolvers = list(resolvers)

    async def evaluate(self, text: str) -> GroundingVerdict:
        """Ground every referent in ``text`` and return the verdict."""
        try:
            referents = extract_referents(text)
        except Exception:
            logger.warning(
                "AD-1119 ReferentGroundingGate: extraction failed; returning an "
                "empty verdict",
                exc_info=True,
            )
            return GroundingVerdict(results={}, unresolved=(), cues={})
        results: dict[str, str] = {}
        unresolved: list[str] = []
        cues: dict[str, str] = {}
        ambiguous: list[str] = []
        for ref in referents:
            token = ref.token
            if token in results:
                continue
            if await self._resolve_one(token):
                results[token] = RESOLVED
            else:
                results[token] = UNRESOLVED
                if ref.claim_confidence == "strong":
                    unresolved.append(token)
                    cues[token] = self._honest_absence_cue(token)
                else:
                    ambiguous.append(token)
        return GroundingVerdict(
            results=results,
            unresolved=tuple(unresolved),
            cues=cues,
            ambiguous=tuple(ambiguous),
        )

    async def _resolve_one(self, token: str) -> bool:
        """First resolver that confirms wins; a raising resolver counts as False."""
        for resolver in self._resolvers:
            try:
                if await resolver.resolve(token):
                    return True
            except Exception:
                logger.warning(
                    "AD-1119 ReferentGroundingGate: resolver kind=%s raised for "
                    "token=%r; treating as unresolved by this resolver",
                    getattr(resolver, "kind", "?"),
                    token,
                    exc_info=True,
                )
                continue
        return False

    @staticmethod
    def _honest_absence_cue(token: str) -> str:
        """A gap-regex-safe cue for an unresolved referent (DD-4, reuse AD-981b).

        The wording is checked against the decomposer ``is_capability_gap`` regex
        — it must NOT read as a capability gap (so it avoids "can't"/"cannot"/
        "unable to"/"lack*"/"don't have"/"no <X> capability|ability|support|way|
        mechanism|tool"/"not available|supported|possible"/"outside ... scope").
        "do not" (with a space), "no such referent", "structurally unresolvable",
        and "nothing resolves" are safe.
        """
        return (
            f"No ship referent resolves for '{token}'. Treat it as structurally "
            "unresolvable: do not build an investigation on it, and do not invent "
            "details to make it real. If nothing resolves, the correct finding is "
            "that there is no such referent."
        )


def build_default_resolvers(
    *,
    registry: Any,
    callsign_registry: Any,
    ward_room: Any,
    repo_root: Path | None = None,
) -> list[ReferentResolver]:
    """Build the three default resolvers from narrow deps (DD-3).

    The wiring site passes ``runtime.registry`` / ``runtime.callsign_registry`` /
    ``getattr(runtime, "ward_room", None)`` — the factory itself is runtime-free,
    so the gate stays unit-testable with real fixtures and no runtime mock.
    """
    return [
        GitObjectResolver(repo_root=repo_root),
        AgentResolver(registry, callsign_registry),
        WardRoomResolver(ward_room),
    ]
