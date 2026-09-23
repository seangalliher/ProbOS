"""AD-1190 (#1127): one aggregate budget per delegation tree.

``delegation_max_depth`` bounds one chain and ``delegation_max_iterations``
bounds one child; neither bounds a TREE -- a root agentic run plus every
``delegate_task`` descendant it spawns. This module holds the tree-wide
ceilings and the object that enforces them.

A root ``WorkItemAgenticExecutor`` run that offers ``delegate_task`` opens one
:class:`DelegationTreeBudget` when at least one ceiling is configured, and
places it in its tool context under :data:`DELEGATION_TREE_BUDGET_KEY`.
``DelegateTaskTool`` admits each child against it and hands the SAME object to
the nested run, so siblings, later iterations of the root run and nested
descendants all draw on one pool. The root run's own spend is never charged:
its own caps govern it. With every ceiling ``None`` nothing is created and
delegation behaves exactly as before.

The iteration ceiling is exact. The token ceiling is not: a run's spend is
compared with its grant only after an LLM call returns, so the tree can exceed
it by up to one LLM call per delegated run in flight. A run that stops
uncleanly is charged at least its whole token grant. Charged spend can also
trail real spend by up to one call per delegated run: a run that reported usage
and then ended on an unmeasured empty completion is charged nothing for that
final call, and a failed call can cost more than an unclean charge covers.
Tokens are those each delegated run's own loop counts; model calls made inside
a tool's implementation are outside the tree budget. The concurrency ceiling
counts in-flight delegated runs and is inert today at or above
``delegation_max_depth``. :class:`DelegationTreeBudget` states each bound with
the measurement behind it.

Leaf module (stdlib and typing only), so the executor, the tool and the
session-correction projection can all import it without a cycle.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Final, Literal, TypeGuard

logger = logging.getLogger(__name__)

DELEGATION_TREE_BUDGET_KEY: Final = "_delegation_tree_budget"
# Mirrors crew_executor._MIN_CREW_TOKEN_BUDGET and the config ge bound.
MIN_DELEGATION_TOKEN_GRANT: Final = 1024

TreeLimit = Literal["tokens", "iterations", "concurrency", "children"]

# (TreeCeilings field, AgenticToolsConfig field, lowest valid value)
_CEILINGS: Final[tuple[tuple[str, str, int], ...]] = (
    ("max_tokens", "delegation_tree_max_tokens", MIN_DELEGATION_TOKEN_GRANT),
    ("max_iterations", "delegation_tree_max_iterations", 1),
    ("max_concurrent", "delegation_tree_max_concurrent", 1),
    ("max_children", "delegation_tree_max_children", 1),
)

# The loop's exits that are not errors; any other stop reason, None included, is unclean.
_CLEAN_STOPS: Final = frozenset({"complete", "max_iterations", "token_budget"})


def _meets_floor(value: object, floor: int) -> TypeGuard[int]:
    """An exact ``int`` (``bool`` excluded) at or above ``floor``."""
    return type(value) is int and value >= floor


def _shown(value: object) -> str:
    """A reported usage value as a settle warning names it, calling nothing on it."""
    if value is None or type(value) is bool:
        return repr(value)
    if type(value) is int:
        # Wider than 64 bits is summarised, not formatted: no real usage count is that
        # large, and one past Python's int-to-str digit limit would raise inside the warning.
        return repr(value) if value.bit_length() <= 64 else "<an int too large to show>"
    return "<not an int>"


def _shown_stop(value: object) -> str:
    """A stop reason as a settle warning names it, calling nothing on a non-``str``."""
    return repr(value) if value is None or type(value) is str else "<not a str>"


@dataclass(frozen=True)
class TreeCeilings:
    """The four tree ceilings; ``None`` leaves that dimension unbounded.

    Each value must be ``None`` or an exact ``int`` (``bool`` rejected) at or
    above its floor: :data:`MIN_DELEGATION_TOKEN_GRANT` for tokens, 1 for the
    others. Anything else raises ``ValueError``.
    """

    max_tokens: int | None = None
    max_iterations: int | None = None
    max_concurrent: int | None = None
    max_children: int | None = None

    def __post_init__(self) -> None:
        for name, _config_name, floor in _CEILINGS:
            value = getattr(self, name)
            if value is not None and not _meets_floor(value, floor):
                raise ValueError(f"delegation_tree_ceiling_invalid:{name}")

    @property
    def unbounded(self) -> bool:
        """True when no ceiling is set, i.e. there is no tree budget at all."""
        return all(getattr(self, name) is None for name, _config_name, _floor in _CEILINGS)


def read_tree_ceilings(cfg: Any) -> TreeCeilings:
    """Read the four ``delegation_tree_max_*`` ceilings off an agentic-tools config.

    A missing attribute, or a value that is not an exact ``int`` at or above
    its floor, degrades to ``None`` rather than raising -- a clamp, never a
    validator (the ``crew_executor._normalize_token_budget`` precedent), so a
    malformed config or projection cannot turn an unrelated run into an error.
    """
    values: dict[str, int | None] = {}
    for name, config_name, floor in _CEILINGS:
        raw = getattr(cfg, config_name, None)
        values[name] = raw if _meets_floor(raw, floor) else None
    return TreeCeilings(**values)


@dataclass(frozen=True)
class TreeUsage:
    """A point-in-time snapshot of one tree budget's counters."""

    children_admitted: int
    in_flight: int
    tokens_spent: int
    tokens_reserved: int
    iterations_spent: int
    iterations_reserved: int


@dataclass(frozen=True, eq=False)
class TreeGrant:
    """One admitted child's allowance.

    Compared and hashed by identity, because each grant is settled exactly once.
    """

    max_iterations: int
    token_budget: int | None
    iterations_limited: bool  # max_iterations < the per-child cap


@dataclass(frozen=True)
class TreeRefusal:
    """Why a delegation was refused before any nested run started."""

    limit: TreeLimit
    ceiling: int
    used: int
    required: int

    def to_output(self) -> dict[str, Any]:
        """The typed, success-shaped tool output for this refusal."""
        return {
            "delegated": False,
            "reason": "delegation_tree_limit_reached",
            "tree_limit": self.limit,
            "ceiling": self.ceiling,
            "used": self.used,
            "required": self.required,
        }


class DelegationTreeBudget:
    """The shared, mutable budget of one delegation tree.

    One instance per root run, carried by reference through every nested
    run's context. Only :meth:`admit` and :meth:`settle` change it, and both
    are plain synchronous methods: on one asyncio event loop no other task can
    run between a check and its reservation, which is what makes admission
    atomic without a lock. The object is not thread-safe and must only be used
    from the event loop that owns the tree.

    What each ceiling guarantees (each example is an AD-1190 test measurement):

    * Iterations: exact. A child runs with ``max_iterations`` no larger than
      its grant, and grants never sum past the ceiling. With a ceiling of 3
      and a per-child cap of 5, the first child used 1 iteration, the second
      was granted the 2 left and stopped there, and the third was refused with
      ``used=3``.
    * Tokens: they bound admission and each child's grant, not every token.
      ``AgenticLoop`` compares a run's spend with its token budget only after
      an LLM call returns, so a child can finish the call that crosses its
      grant, and the tree's charged spend can exceed the ceiling by up to one
      LLM call per delegated run still in flight when the last child was
      admitted. With a 2048-token ceiling, a child whose single call reported
      3000 tokens stopped after that call, and the next delegation was refused
      with ``used=3000``.
    * Concurrency: counts delegated runs in flight, including one that is only
      awaiting its own delegate; the root run is not a delegated run. Two
      siblings parked inside their runs made a third refuse at a ceiling of 2,
      and at a ceiling of 1 an in-flight child could not delegate further.
      ``delegate_task`` calls within one loop run one at a time, so today runs
      overlap only through nesting, at most ``delegation_max_depth`` of them:
      a ceiling at or above ``delegation_max_depth`` never refuses.
    * Children: every admitted delegation counts, at any depth.

    Usage is charged as each delegated run's own loop counts it. Under a token
    ceiling each run's grant is its ``token_budget``, so its loop counts
    provider-reported non-negative figures, or BF-680 estimates; model calls
    made inside a tool's implementation are outside the tree budget. Two rules
    apply where that count may be short. A token total of 0 is unknown rather
    than free: a delegated run that returns has made at least one model call,
    so a zero total went unmeasured and is charged the whole token grant. A
    child whose only call was an empty completion reported as 0, or as -500,
    was charged its whole 1024-token grant, and the next delegation was
    refused. And a run that stopped uncleanly -- any stop but ``complete``,
    ``max_iterations`` or ``token_budget``, such as the loop's ``error`` stop,
    or no outcome at all after it raised or was cancelled -- is charged the
    larger of its counted total and its whole token grant, because a failed
    call may have been billed without being counted. A child that counted 500
    tokens and then had its next model call raise was charged its whole
    2048-token grant, and the next delegation was refused with ``used=2048``;
    one that counted 3000 tokens against a 2048-token grant before failing was
    charged 3000. What stays uncharged is an unmeasured empty completion that
    ends a run which already reported usage, and whatever a failed call cost
    beyond an unclean charge, so charged spend can trail real spend by up to
    one call per delegated run, in addition to the in-flight overshoot above. A
    child that reported 500 tokens for a tool call and then ended on an empty
    completion reported as 0 was charged 500.
    """

    def __init__(self, ceilings: TreeCeilings) -> None:
        self._ceilings = ceilings
        self._children_admitted = 0
        self._in_flight = 0
        self._tokens_spent = 0
        self._tokens_reserved = 0
        self._iterations_spent = 0
        self._iterations_reserved = 0
        self._outstanding: set[TreeGrant] = set()

    @classmethod
    def from_config(cls, cfg: Any) -> DelegationTreeBudget | None:
        """Open a budget from an agentic-tools config; ``None`` when no ceiling is set."""
        ceilings = read_tree_ceilings(cfg)
        if ceilings.unbounded:
            return None
        return cls(ceilings)

    @property
    def ceilings(self) -> TreeCeilings:
        return self._ceilings

    def usage(self) -> TreeUsage:
        return TreeUsage(
            children_admitted=self._children_admitted,
            in_flight=self._in_flight,
            tokens_spent=self._tokens_spent,
            tokens_reserved=self._tokens_reserved,
            iterations_spent=self._iterations_spent,
            iterations_reserved=self._iterations_reserved,
        )

    def admit(
        self, *, child_depth: int, max_depth: int, per_child_iterations: int,
    ) -> TreeGrant | TreeRefusal:
        """Admit one delegated child, or refuse it with a typed reason.

        Ceilings are checked in a fixed order -- children, then concurrency,
        then iterations, then tokens -- and the first one that cannot take one
        more child is the refusal. A refusal changes no counter.

        An admission reserves one child, one in-flight slot and the child's
        grant, carved from what is neither spent nor reserved. The slot stays
        taken while the child waits on its own delegates. With
        ``levels = max(1, max_depth - child_depth + 1)``, the delegation levels
        this child and its descendants may still use, the grant is
        ``min(per_child_iterations, available, max(1, available // levels))``
        iterations and ``min(available, max(MIN_DELEGATION_TOKEN_GRANT,
        available // levels))`` tokens; without a ceiling the iteration grant
        is ``per_child_iterations`` and the token grant is ``None``. A leaf
        child (``levels == 1``) is granted everything left, still capped per
        child for iterations. The reservation stays held until the caller
        releases it exactly once through :meth:`settle`, which charges what the
        child actually used.

        Synchronous on purpose: the check and the reservation happen with no
        await between them, so two delegations on one event loop cannot both
        pass the same check. Not thread-safe.

        Raises ``ValueError``, before touching any counter, when
        ``child_depth`` < 1, ``max_depth`` < 0 or ``per_child_iterations`` < 1,
        or when any of them is not an exact ``int``.
        """
        if not (
            _meets_floor(child_depth, 1)
            and _meets_floor(max_depth, 0)
            and _meets_floor(per_child_iterations, 1)
        ):
            raise ValueError("delegation_tree_admission_invalid")
        max_children = self._ceilings.max_children
        if max_children is not None and self._children_admitted >= max_children:
            return TreeRefusal(
                limit="children", ceiling=max_children,
                used=self._children_admitted, required=1,
            )
        max_concurrent = self._ceilings.max_concurrent
        if max_concurrent is not None and self._in_flight >= max_concurrent:
            return TreeRefusal(
                limit="concurrency", ceiling=max_concurrent,
                used=self._in_flight, required=1,
            )
        # Levels of delegation this child and its descendants may still use.
        levels = max(1, max_depth - child_depth + 1)
        iteration_grant = per_child_iterations
        max_iterations = self._ceilings.max_iterations
        if max_iterations is not None:
            committed = self._iterations_spent + self._iterations_reserved
            available = max_iterations - committed
            if available < 1:
                return TreeRefusal(
                    limit="iterations", ceiling=max_iterations,
                    used=committed, required=1,
                )
            iteration_grant = min(
                per_child_iterations, min(available, max(1, available // levels)),
            )
        token_grant: int | None = None
        max_tokens = self._ceilings.max_tokens
        if max_tokens is not None:
            committed = self._tokens_spent + self._tokens_reserved
            available = max_tokens - committed
            if available < MIN_DELEGATION_TOKEN_GRANT:
                return TreeRefusal(
                    limit="tokens", ceiling=max_tokens,
                    used=committed, required=MIN_DELEGATION_TOKEN_GRANT,
                )
            token_grant = min(
                available, max(MIN_DELEGATION_TOKEN_GRANT, available // levels),
            )
        grant = TreeGrant(
            max_iterations=iteration_grant,
            token_budget=token_grant,
            iterations_limited=iteration_grant < per_child_iterations,
        )
        self._children_admitted += 1
        self._in_flight += 1
        self._iterations_reserved += grant.max_iterations
        self._tokens_reserved += grant.token_budget or 0
        self._outstanding.add(grant)
        return grant

    def settle(
        self, grant: TreeGrant, *, tokens_used: object, iterations_used: object,
        stopped_reason: object,
    ) -> None:
        """Release an admitted child's reservation and charge what it used.

        Synchronous for the same single-event-loop reason as :meth:`admit`,
        and not thread-safe. ``iterations_used`` is charged when it is an exact
        ``int`` in ``[1, grant.max_iterations]``, else the iteration grant. A
        run stopped cleanly only when ``stopped_reason`` is exactly
        ``"complete"``, ``"max_iterations"`` or ``"token_budget"``; its
        ``tokens_used`` is then charged when it is an exact ``int`` of at least
        1, since a delegated run that returns has made a model call, so a zero
        total is unmeasured, not free. Any other token value, or any other stop
        -- the loop's ``"error"``, an unknown or non-``str`` reason, or ``None``
        after the child raised or was cancelled -- charges the larger of the
        valid counted total (else 0) and the token grant (0 when none was
        issued), because a failed call may have been billed without being
        counted. Each substitution is logged at WARNING, its token part only
        when a token grant was issued. A grant this budget does not hold open,
        foreign or already settled, is logged and ignored. It does not raise
        for a bad grant or bad usage values.
        """
        if type(grant) is not TreeGrant or grant not in self._outstanding:
            logger.warning(
                "AD-1190: ignored a settle for a grant this delegation tree does "
                "not hold open (foreign or already settled); its counters are "
                "unchanged",
            )
            return
        self._outstanding.remove(grant)
        self._in_flight -= 1
        self._iterations_reserved -= grant.max_iterations
        self._tokens_reserved -= grant.token_budget or 0
        fallbacks: list[str] = []
        if _meets_floor(iterations_used, 1) and iterations_used <= grant.max_iterations:
            self._iterations_spent += iterations_used
        else:
            self._iterations_spent += grant.max_iterations
            fallbacks.append(
                f"iterations_used={_shown(iterations_used)} charged as {grant.max_iterations}"
            )
        # A zero total is unmeasured, not free: the returning run made a model call.
        counted = tokens_used if _meets_floor(tokens_used, 1) else 0
        clean = type(stopped_reason) is str and stopped_reason in _CLEAN_STOPS
        if clean and counted:
            charged = counted
        else:
            # Unknown usage, or an unclean stop whose failed call may have gone uncounted.
            charged = max(counted, grant.token_budget or 0)
            if grant.token_budget is not None:
                unclean = "" if clean else (
                    f" (stopped_reason={_shown_stop(stopped_reason)} is not a clean stop)"
                )
                fallbacks.append(
                    f"tokens_used={_shown(tokens_used)} charged as {charged}{unclean}"
                )
        self._tokens_spent += charged
        if fallbacks:
            logger.warning(
                "AD-1190: a delegated run settled with usage the tree cannot trust "
                "(%s); charged at least the grant's allowance so the tree budget "
                "errs conservative",
                "; ".join(fallbacks),
            )
