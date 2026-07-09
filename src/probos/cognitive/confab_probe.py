"""AD-1121 (#1024): context-free cascade-confabulation divergence probe.

Layer: COGNITIVE. Runtime-free by construction (Dependency Inversion): the LLM
client is injected, never imported; there is no hard runtime dependency. The
probe is a SelfCheckGPT-style (arXiv 2303.08896) self-consistency check for the
one case the AD-1119 deterministic resolvers cannot settle — an UNRESOLVED
central referent.

Context-free by SIGNATURE, not by discipline: ``probe_referent`` accepts ONLY
the referent token string. There is deliberately no parameter through which the
room seed / transcript could reach the LLM — so a poisoned shared context can
never make the independent samples confirmatory (CoVe, arXiv 2309.11495). N
high-temperature draws of "does ``<token>`` exist on this ship?" CONVERGE (affirm)
for a real referent and FAIL to consistently affirm for a fabricated one.

Honest-degrade contract (Tier-2 at every boundary): a None client, a failed
sample, an empty batch, or any unexpected raise yields a NON-divergent
``ProbeResult`` — a probe failure NEVER produces a false ``CASCADE_CONFAB`` flag.
Fewer than ``_CONFAB_MIN_USABLE_SAMPLES`` usable samples abstains (no flag).
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any

from probos.types import LLMRequest

logger = logging.getLogger(__name__)

# Zero-config module constants (like ``_FANOUT_HISTORY_LIMIT``). N independent,
# high-temperature draws — the temperature is load-bearing: it makes the samples
# genuinely independent so a fabricated referent diverges.
_CONFAB_PROBE_SAMPLES = 3
_CONFAB_PROBE_TIER = "fast"
_CONFAB_PROBE_TEMPERATURE = 1.0
_CONFAB_PROBE_MAX_TOKENS = 160
# Flag when the affirm-rate falls BELOW this AND at least MIN_USABLE samples
# returned. A fabricated referent yields either consistent denials (rate -> 0)
# or divergent hallucinations that mostly fail to affirm one real entity.
_CONFAB_AFFIRM_THRESHOLD = 0.5
_CONFAB_MIN_USABLE_SAMPLES = 2

# Denial / uncertainty markers (DD-1121-4). A sample AFFIRMs iff it has
# substantive content AND matches NONE of these. Matched anywhere, case-
# insensitive. ``no ... named`` allows a few words between "no" and "named"
# ("there is no entity named X").
_CONFAB_DENIAL_RE = re.compile(
    r"(?:"
    r"no record"
    r"|does not exist"
    r"|no such"
    r"|not aware"
    r"|cannot find"
    r"|no\b(?:\s+\w+){0,4}\s+named"
    r"|not a real"
    r"|fictional"
    r"|unknown"
    r"|no information"
    r"|i (?:have|find) no"
    r"|unable to (?:find|locate)"
    r"|not (?:a )?(?:standard|known|valid)"
    r")",
    re.IGNORECASE,
)

# Fixed, minimal, Ship's-Computer-voiced system prompt. There is NO transcript
# slot — the seed can never be injected here (context-free guarantee).
_CONFAB_PROBE_SYSTEM_PROMPT = (
    "You are the ship's computer. Answer only about entities that genuinely "
    "exist on this ship. If you have no record of the named item, say so "
    "plainly. Do not invent details."
)


@dataclass(frozen=True)
class ProbeResult:
    """The outcome of a context-free divergence probe on one referent token.

    A non-divergent or abstained result has ``is_divergent=False``. ``samples``
    holds the raw usable sample texts (bounded by the probe's ``max_tokens`` and
    sample count) for a downstream reasoning digest.
    """

    token: str
    usable: int
    affirm: int
    is_divergent: bool
    samples: tuple[str, ...] = ()

    @property
    def affirm_rate(self) -> float:
        """Fraction of usable samples that affirmed existence (0.0 when none)."""
        if self.usable <= 0:
            return 0.0
        return self.affirm / self.usable


def _classify_existence(text: str) -> str:
    """Pure classifier: ``"AFFIRM"`` or ``"NOT_AFFIRM"`` for one sample.

    Empty/whitespace -> ``"NOT_AFFIRM"``; a denial/uncertainty marker ->
    ``"NOT_AFFIRM"``; otherwise ``"AFFIRM"``. No I/O.
    """
    if not text or not text.strip():
        return "NOT_AFFIRM"
    if _CONFAB_DENIAL_RE.search(text):
        return "NOT_AFFIRM"
    return "AFFIRM"


async def probe_referent(
    llm_client: Any,
    token: str,
    *,
    samples: int = _CONFAB_PROBE_SAMPLES,
    tier: str = _CONFAB_PROBE_TIER,
    temperature: float = _CONFAB_PROBE_TEMPERATURE,
) -> ProbeResult:
    """Run ``samples`` independent, context-free existence probes on ``token``.

    Issues N concurrent ``llm_client.complete`` calls with the SAME request (high
    temperature makes the draws independent). Each prompt carries ONLY the token
    — never a seed/transcript. Classifies each usable sample and flags divergence
    when the affirm-rate is below threshold with enough usable samples.

    Tier-2 honest-degrade: a None client, per-sample failures, an empty batch, or
    any unexpected raise -> a non-divergent ``ProbeResult``. Never raises; never a
    false-positive flag.
    """
    if llm_client is None:
        logger.debug(
            "AD-1121: divergence probe skipped for token=%r (llm_client is None)",
            token,
        )
        return ProbeResult(token=token, usable=0, affirm=0, is_divergent=False)
    try:
        prompt = (
            f"Does an entity, component, service, or identifier named '{token}' "
            f"exist on this ship? If it does, state briefly what it is. If you "
            f"have no record of it, say so plainly."
        )
        req = LLMRequest(
            prompt=prompt,
            system_prompt=_CONFAB_PROBE_SYSTEM_PROMPT,
            tier=tier,
            temperature=temperature,
            max_tokens=_CONFAB_PROBE_MAX_TOKENS,
        )
        n = max(1, samples)
        results = await asyncio.gather(
            *[llm_client.complete(req) for _ in range(n)],
            return_exceptions=True,
        )
        texts: list[str] = []
        for r in results:
            if isinstance(r, BaseException):
                logger.debug(
                    "AD-1121: probe sample failed for token=%r: %s",
                    token, type(r).__name__,
                )
                continue
            content = getattr(r, "content", None)
            if not content or not str(content).strip():
                continue
            texts.append(str(content))
        usable = len(texts)
        affirm = sum(1 for t in texts if _classify_existence(t) == "AFFIRM")
        is_divergent = (
            usable >= _CONFAB_MIN_USABLE_SAMPLES
            and (affirm / usable) < _CONFAB_AFFIRM_THRESHOLD
        )
        if usable < _CONFAB_MIN_USABLE_SAMPLES:
            logger.debug(
                "AD-1121: probe abstains for token=%r (usable=%d < %d)",
                token, usable, _CONFAB_MIN_USABLE_SAMPLES,
            )
        return ProbeResult(
            token=token,
            usable=usable,
            affirm=affirm,
            is_divergent=is_divergent,
            samples=tuple(texts),
        )
    except Exception:
        logger.warning(
            "AD-1121: divergence probe for token=%r raised unexpectedly; "
            "returning non-divergent (no false flag)",
            token, exc_info=True,
        )
        return ProbeResult(token=token, usable=0, affirm=0, is_divergent=False)
