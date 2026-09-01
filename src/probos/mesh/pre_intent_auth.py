"""Shared AD-698 pre-intent authorization evaluation (BF-789).

One implementation of "may this intent reach a handler", so that every entry
point which can deliver to a handler asks the same question and fails the same
way. It lived only inside ``IntentBus._authorize`` until BF-789; the AD-654c
``Dispatcher`` bypasses the bus entirely and so reached handlers with the hook
never consulted.

Deliberately dependency-light -- ``probos.types`` and the overlay export, and
nothing else. ``mesh.work_item_router`` already reaches into
``probos.activation.dispatcher``, so a module-level ``activation -> mesh.intent``
import would risk a cycle; a leaf module both sides can import does not.

``authorize_intent`` does NOT raise. It reports ``(allowed, reason)`` and lets
each caller express a denial in its own pre-existing refusal shape -- the bus
returns ``None``/``[]``, the Dispatcher counts a rejection. Raising by default
would force that decision on every consumer, which is precisely what BF-771
found to be wrong. ``IntentAuthorizationDenied`` lives here rather than in
``mesh.intent`` only so that consumers which opt into the raising shape can
catch it without a module-level import of the bus; ``mesh.intent`` re-exports
it, so the five production modules that import it from there are unaffected.

WHAT THIS DOES NOT COVER. Calling this from BOTH ends of a transport
double-charges a stateful hook: a rate limiter or quota silently loses half its
allowance, and nothing reports that it happened. So a caller must only evaluate
here when nothing upstream already did. See BF-789 (#1253) for the transport
callbacks, where the producer on the same node has usually authorized already
and an origin distinction is needed first.
"""

from __future__ import annotations

import logging

from probos.types import IntentMessage

logger = logging.getLogger(__name__)

__all__ = ["IntentAuthorizationDenied", "authorize_intent"]


class IntentNoSubscriber(RuntimeError):
    """No handler would be invoked for this intent (BF-814).

    OPT-IN ONLY, for the same reason as :class:`IntentAuthorizationDenied`
    above: the bus's default refusal shape stays ``[]``, so the other bus seams
    are untouched. Only a caller that must tell "reached nobody" from "reached
    someone" asks for it.

    That distinction cannot be recovered from the result list. A handler that
    runs, performs its side effect, and returns ``None`` also yields ``[]`` --
    measured -- so a caller treating an empty list as non-delivery re-fires
    real work. ``candidate_agent_ids`` answers the safe question instead: was
    any handler INVOKED. Nobody invoked is the only state where a retry cannot
    duplicate anything.
    """

    def __init__(self, intent_name: str) -> None:
        self.intent_name = intent_name
        super().__init__(
            f"no subscriber would be invoked for intent '{intent_name}'"
        )


class IntentAuthorizationDenied(PermissionError):
    """A pre-intent authorization hook refused this intent (BF-771).

    OPT-IN ONLY. The bus reports a denial in each entry point's pre-existing
    refusal shape by default (``send`` -> ``None``, ``broadcast`` -> ``[]``,
    ``dispatch_async`` -> no-op). This exception is raised only when a caller
    passes ``raise_on_denial=True`` because it must tell a policy refusal apart
    from a silent no-op -- ``accept_notification`` acknowledged a notification
    whose dispatch had been refused, which is the case that motivated it.

    It is deliberately NOT the default: it subclasses ``PermissionError``, so
    ``except Exception`` catches it, and of the 35 bus call seams 14 sit inside
    a broad handler that would swallow it and degrade with a misleading cause
    -- one renders a refusal as "the lookup didn't finish in time". Raising
    there relocates the defect rather than fixing it. Every consumer that opts
    in is verified individually.
    """

    def __init__(self, intent_name: str, reason: str, entry_point: str) -> None:
        self.intent_name = intent_name
        self.reason = reason
        self.entry_point = entry_point
        super().__init__(
            f"intent {intent_name!r} denied by pre-auth hook {reason!r} "
            f"(via {entry_point})"
        )


def authorize_intent(
    intent: IntentMessage,
    *,
    entry_point: str,
) -> tuple[bool, str]:
    """Evaluate AD-698 pre-intent authorization.

    Returns ``(True, "")`` to proceed, or ``(False, reason)`` to refuse, where
    ``reason`` is the hook's own reason or a ``import:``/``evaluator:``-prefixed
    tag identifying which stage failed closed.

    Fails CLOSED on every error path. ``probos.extensions.overlay`` is OSS core,
    not the optional overlay package -- "no overlay installed" already presents
    as an empty hook registry returning ``(True, "")``. So an ImportError here
    means broken core, version skew or a missing export, and allowing in that
    state removes policy enforcement at exactly the moment the code is least
    trustworthy. The evaluator raising is likewise not a licence to proceed: an
    earlier version caught the import and the call in one handler and allowed
    both, so a crashing evaluator authorized everything.
    """
    try:
        from probos.extensions.overlay import evaluate_pre_intent_authorization
    except Exception as exc:
        logger.error(
            "AD-698: pre-intent authorization module failed to import (%s) for "
            "intent %s via %s; DENYING. This is core code -- an absent overlay "
            "presents as an empty hook registry, not an ImportError",
            type(exc).__name__, intent.intent, entry_point, exc_info=True,
        )
        return False, f"import:{type(exc).__name__}"

    try:
        allowed, reason = evaluate_pre_intent_authorization(intent)
    except Exception as exc:
        logger.error(
            "AD-698: pre-intent authorization evaluator raised %s for intent "
            "%s via %s; DENYING rather than proceeding unauthorized",
            type(exc).__name__, intent.intent, entry_point, exc_info=True,
        )
        return False, f"evaluator:{type(exc).__name__}"

    if allowed:
        return True, ""

    logger.info(
        "AD-698: intent %s denied by pre-auth hook '%s' (via %s)",
        intent.intent, reason, entry_point,
    )
    return False, reason
