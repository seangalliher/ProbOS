"""AD-1360 (#1828): the AD-492 cognitive-cycle id, issued into a registry and carried in a ContextVar.

Standard library only, so any layer may import it (a top-level module, which tests/test_layer_boundaries.py treats as
core). AD-492 gave each cognitive cycle a correlation id and threaded it through the journal, the events and the
episode; nothing checked that an episode's id came from a cycle. This module holds three parts:

* ``CycleIdRegistry`` records each id the process issues (``issue``) or adopts (``register``, for an id made elsewhere,
  such as a work item's), bounded by a TTL and a size. Neither bound is measured; both are constructor arguments
  (AD-1360 S3's replay measures them).
* ``judge_correlation_id`` is the verdict ``EpisodicMemory.store()`` records on each episode.
* ``CURRENT_CYCLE_ID`` carries the bound id. An awaited coroutine runs in its caller's context and a task copies the
  context it was created in (PEP 567), so code inside a bound cycle reads the id without a parameter. ``bind_cycle``
  returns the token ``unbind_cycle`` resets in a ``finally``, as ``admission/carrier.py`` does for the work ticket.
  AD-1360 S2a: ``cycle_scope`` binds a cycle's id again for work done for it after it has ended (the DM reply's steps,
  a proactive think's posts), and ``result_cycle_id`` reads that id off the cycle's ``IntentResult``.
  AD-1360 S2b: ``issue_entry_id`` and ``entry_scope`` give an entry point outside any cycle (an HXI request, a sweep,
  a verification) an id the registry issued, so the episodes it stores record their own chain.
"""

from __future__ import annotations

import logging
import math
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Final, Protocol

logger = logging.getLogger(__name__)

#: Created at module level, as the contextvars documentation asks. "" = no cycle is bound.
CURRENT_CYCLE_ID: Final[ContextVar[str]] = ContextVar("probos_cycle_id", default="")

#: The verdicts EpisodicMemory.store() records in Episode.correlation_verdict. The field's default "" means not
#: recorded: an episode stored before AD-1360, seeded or restored.
VERDICT_RESOLVED: Final = "resolved"
VERDICT_UNRESOLVED: Final = "unresolved"
VERDICT_EMPTY: Final = "empty"
VERDICT_UNCHECKED: Final = "unchecked"

#: Not measured: one day, so a cycle that stores its episode within a day of its start resolves.
DEFAULT_TTL_SECONDS: Final = 86_400.0
#: Not measured: the most ids held at once; the oldest is dropped past it.
DEFAULT_MAX_ENTRIES: Final = 100_000


def new_cycle_id() -> str:
    """A new id in AD-492's format: twelve hex characters of a random UUID."""
    return uuid.uuid4().hex[:12]


def current_cycle_id() -> str:
    """The id bound in this context, or "" when no cycle is bound."""
    return CURRENT_CYCLE_ID.get()


def bind_cycle(chain_id: str) -> Token[str]:
    """Bind ``chain_id`` for the work this context runs next; reset it with ``unbind_cycle`` in a ``finally``."""
    if type(chain_id) is not str or not chain_id:
        raise ValueError("bind_cycle needs a non-empty id")
    return CURRENT_CYCLE_ID.set(chain_id)


def unbind_cycle(token: Token[str]) -> None:
    """Put back the id bound before ``bind_cycle``.

    Raises no Exception: a token already used, or one another context created, is passed over (ContextVar.reset raises
    RuntimeError or ValueError, PEP 567).
    """
    try:
        CURRENT_CYCLE_ID.reset(token)
    except (RuntimeError, ValueError):
        pass


@contextmanager
def cycle_scope(chain_id: str = "") -> Iterator[str]:
    """Bind ``chain_id`` for the block, or keep the bound id when it is blank or not a str; yields the id bound inside.

    On exit, by return, raise or cancellation, the id bound before the block is back, whatever the block bound in this
    context without resetting. For work done for a cycle after the cycle has ended (AD-1360 S2a).
    """
    bound = chain_id if type(chain_id) is str and chain_id.strip() else CURRENT_CYCLE_ID.get()
    token = CURRENT_CYCLE_ID.set(bound)
    try:
        yield bound
    finally:
        unbind_cycle(token)


def result_cycle_id(result: object) -> str:
    """The AD-492 id a cognitive cycle's ``IntentResult`` carries in ``metadata["correlation_id"]``; "" when there is no
    result, its metadata is not a dict, or the value is not a non-blank str."""
    metadata = getattr(result, "metadata", None)
    chain_id = metadata.get("correlation_id") if type(metadata) is dict else None
    return chain_id if type(chain_id) is str and chain_id.strip() else ""


def issue_entry_id(registry: object, *, kind: str) -> str:
    """AD-1360 S2b: the AD-492 id an entry point's work records, for an entry point no cognitive cycle runs.

    The bound id when one is bound (inside a cycle, or a ``cycle_scope``): the work joins the chain that reached it.
    Otherwise a new id ``registry`` issues and records under ``kind``, the entry point's name ("hxi_post"). Without a
    ``CycleIdRegistry`` (none, or a test runtime's MagicMock attribute), "": an id nothing issued would only turn the
    episode's verdict from empty into unresolved or unchecked. Raises ValueError for a blank or non-str ``kind``.
    """
    _require_kind(kind)
    bound = CURRENT_CYCLE_ID.get()
    if bound:
        return bound
    return registry.issue(kind=kind) if isinstance(registry, CycleIdRegistry) else ""


@contextmanager
def entry_scope(registry: object, *, kind: str) -> Iterator[str]:
    """Bind ``issue_entry_id(registry, kind=kind)`` for the block, for an entry point whose producers read
    ``current_cycle_id()`` (the Ward Room's); yields the id ("" when none is bound). The outer id is back on exit."""
    with cycle_scope(issue_entry_id(registry, kind=kind)) as bound:
        yield bound


class CycleIdResolver(Protocol):
    """What EpisodicMemory.store() needs: whether an id was issued or adopted and has not expired."""

    def resolves(self, chain_id: str) -> bool: ...


def _require_kind(kind: str) -> None:
    if type(kind) is not str or not kind.strip():
        raise ValueError("a cycle id needs a non-empty kind")


class CycleIdRegistry:
    """The ids this process issued or adopted, each held for ``ttl_seconds`` and at most ``max_entries`` at once.

    In memory: a restart forgets every id, so an episode stored after a restart for a cycle begun before it records
    "unresolved". Thread-safe. ``clock`` is monotonic by default, so a wall-clock step expires nothing.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        max_entries: int = DEFAULT_MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, (int, float)):
            raise ValueError("ttl_seconds must be a number")
        if not math.isfinite(ttl_seconds) or ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be finite and above 0")
        if isinstance(max_entries, bool) or not isinstance(max_entries, int) or max_entries < 1:
            raise ValueError("max_entries must be an int of at least 1")
        self._ttl = float(ttl_seconds)
        self._max_entries = max_entries
        self._clock = clock
        self._entries: OrderedDict[str, tuple[float, str]] = OrderedDict()
        self._lock = threading.Lock()

    def issue(self, *, kind: str) -> str:
        """Record and return a new id; ``kind`` names the entry point that issued it ("cognitive_cycle")."""
        _require_kind(kind)
        chain_id = new_cycle_id()
        self._record(chain_id, kind)
        return chain_id

    def register(self, chain_id: str, *, kind: str) -> None:
        """Adopt an id made elsewhere (a work item's), or refresh one already held: it resolves for another TTL."""
        if type(chain_id) is not str or not chain_id.strip():
            raise ValueError("register needs a non-empty id")
        _require_kind(kind)
        self._record(chain_id, kind)

    def resolves(self, chain_id: str) -> bool:
        """True while ``chain_id`` is held and no older than the TTL."""
        return self._live_entry(chain_id) is not None

    def kind_of(self, chain_id: str) -> str:
        """The kind an id was recorded with, or "" when it does not resolve."""
        entry = self._live_entry(chain_id)
        return entry[1] if entry is not None else ""

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def _record(self, chain_id: str, kind: str) -> None:
        with self._lock:
            # Read under the lock: two writers cannot record out of time order, which _evict relies on.
            now = self._clock()
            self._entries[chain_id] = (now, kind)
            self._entries.move_to_end(chain_id)
            self._evict(now)

    def _live_entry(self, chain_id: str) -> tuple[float, str] | None:
        if type(chain_id) is not str or not chain_id:
            return None
        with self._lock:
            self._evict(self._clock())
            return self._entries.get(chain_id)

    def _evict(self, now: float) -> None:
        # Entries are in recording order and share one TTL, so the expired ones and the oldest are at the front.
        while self._entries:
            oldest_id, (recorded_at, _kind) = next(iter(self._entries.items()))
            if now - recorded_at <= self._ttl and len(self._entries) <= self._max_entries:
                return
            del self._entries[oldest_id]


def judge_correlation_id(chain_id: str, resolver: CycleIdResolver | None) -> str:
    """The verdict EpisodicMemory.store() records for an episode's correlation id.

    "empty" for no id (no registry is needed to say so); "unchecked" when no registry is bound or it raises (logged at
    WARNING; the store goes on); otherwise "resolved" or "unresolved".
    """
    if type(chain_id) is not str or not chain_id.strip():
        return VERDICT_EMPTY
    if resolver is None:
        return VERDICT_UNCHECKED
    try:
        return VERDICT_RESOLVED if resolver.resolves(chain_id) is True else VERDICT_UNRESOLVED
    except Exception:
        logger.warning("AD-1360: the cycle-id registry failed on %r; the episode records unchecked", chain_id, exc_info=True)
        return VERDICT_UNCHECKED
