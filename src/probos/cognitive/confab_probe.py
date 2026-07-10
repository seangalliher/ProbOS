"""AD-1121 (#1024): context-free cascade-confabulation divergence probe.

Layer: COGNITIVE. Runtime-free by construction (Dependency Inversion): the LLM
client is injected, never imported; there is no hard runtime dependency. The
probe is a SelfCheckGPT-style (arXiv 2303.08896) self-consistency check for the
one case the AD-1119 deterministic resolvers cannot settle — an UNRESOLVED
central referent.

Context-free by SIGNATURE, not by discipline: ``probe_referent`` accepts ONLY
the referent token string. There is deliberately no parameter through which the
room seed / transcript could reach the LLM — so a poisoned shared context can
never make the independent samples confirmatory (CoVe, arXiv 2309.11495). Each
high-temperature draw uses a fresh request with a semantically inert prompt
nonce, preventing the prompt-keyed response cache from collapsing independent
samples. Explicit YES answers converge for a real referent; explicit NO answers
or abstentions prevent fabricated evidence from being treated as confirmation.

Honest-degrade contract (Tier-2 at every boundary): a None client, a failed
sample, an empty batch, or any unexpected raise yields a NON-divergent
``ProbeResult`` — a probe failure NEVER produces a false ``CASCADE_CONFAB`` flag.
Fewer than ``_CONFAB_MIN_USABLE_SAMPLES`` usable samples abstains (no flag).
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any

from probos.types import LLMRequest

logger = logging.getLogger(__name__)

# Zero-config module constants (like ``_FANOUT_HISTORY_LIMIT``). N independent,
# high-temperature draws. The per-sample prompt nonce is load-bearing because
# OpenAICompatibleClient caches by tier + prompt; temperature alone does not
# guarantee an independent transport request.
_CONFAB_PROBE_SAMPLES = 3
_CONFAB_PROBE_TIER = "fast"
_CONFAB_PROBE_TEMPERATURE = 1.0
_CONFAB_PROBE_MAX_TOKENS = 160
# Flag when the affirm-rate falls BELOW this AND at least MIN_USABLE samples
# returned. A fabricated referent yields either consistent denials (rate -> 0)
# or divergent hallucinations that mostly fail to affirm one real entity.
_CONFAB_AFFIRM_THRESHOLD = 0.5
_CONFAB_MIN_USABLE_SAMPLES = 2

# DD-2: the first non-empty line must begin with one exact structured token.
# A delimiter may carry the optional brief explanation on the same line.
_CONFAB_FIRST_LINE_RE = re.compile(
    r"^(YES|NO|UNKNOWN)(?:\s*$|\s*([.:-]|—)(?:\s*(.*))?$)"
)
_CONFAB_EXPLICIT_VERDICT_RE = re.compile(
    r"\b(YES|NO|UNKNOWN)\b", re.IGNORECASE
)
_CONFAB_HEDGE_RE = re.compile(
    r"\b(?:maybe|perhaps|may|might|could|would|possibly|probably|likely|"
    r"apparently|presumably|"
    r"uncertain|unsure|not sure|undetermined|insufficient evidence|"
    r"cannot determine|i think|i believe|"
    r"(?:seems?|appears?) to)\b",
    re.IGNORECASE,
)
_CONFAB_DOUBLE_NEGATION_RE = re.compile(
    r"\b(?:not|never)\s+(?:(?:a|an)\s+)?(?:absent|missing|fake|fabricated|"
    r"imaginary|fictional|unknown|unrecognized|unregistered|unavailable|"
    r"inactive|non-?existent|not)\b",
    re.IGNORECASE,
)
_CONFAB_DENIAL_SIGNAL_RE = re.compile(
    r"\b(?:no|do not have (?:a )?record|does not exist|no such|"
    r"not aware|unaware|cannot find|unrecognized|unknown|no information|"
    r"unable to (?:find|locate)|fake|fabricated|imaginary|fictional|"
    r"not (?:a )?real|never (?:registered|active|installed|deployed|verified)|"
    r"not (?:a )?(?:registered|genuine)|lacks?|"
    r"(?:is|was|remains?) not (?:registered|present|listed|known|found|"
    r"available|real|genuine|active|installed|deployed|verified)|"
    r"not (?:registered|present|listed|known|found|available|real|genuine|"
    r"active|installed|deployed|verified)|"
    r"(?:record|entry) (?:is |was )?(?:absent|missing)|"
    r"(?:is|was) absent|(?:absent|missing) from (?:the )?(?:registry|records?)|"
    r"not in (?:the )?(?:registry|records?))\b",
    re.IGNORECASE,
)
_CONFAB_AFFIRM_SIGNAL_RE = re.compile(
    r"\b(?:exists?|real|genuine|active|installed|deployed|verified|"
    r"registered|present|listed|known|available|found|located)\b|"
    r"\bin\s+(?:the\s+)?(?:registry|records?)\b|"
    r"\b(?:ship|registry|records?)\s+(?:has|contains|includes)\s+"
    r"(?:a|the)\s+(?:record|entry|service|entity)\b",
    re.IGNORECASE,
)
_CONFAB_NEGATION_WORDS = frozenset(
    {
        "no",
        "not",
        "never",
        "neither",
        "without",
        "lack",
        "lacks",
        "lacking",
        "absent",
        "missing",
    }
)

# Fixed, minimal, Ship's-Computer-voiced system prompt. There is NO transcript
# slot — the seed can never be injected here (context-free guarantee).
_CONFAB_PROBE_SYSTEM_PROMPT = (
    "You are the ship's computer. Answer only from records about entities that "
    "genuinely exist on this ship. The first non-empty line must be exactly "
    "YES, NO, or UNKNOWN. Use YES only for a verified record, NO only for a "
    "verified absence, and UNKNOWN whenever evidence is insufficient or "
    "equivocal. You may add one brief explanatory line. Do not invent details."
)


@dataclass(frozen=True)
class ProbeResult:
    """The outcome of a context-free divergence probe on one referent token.

    A non-divergent or abstained result has ``is_divergent=False``. ``samples``
    holds the raw non-empty sample texts (bounded by the probe's ``max_tokens``
    and sample count) for a downstream reasoning digest, including abstentions.
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
    """Return the strict first-line verdict: ``YES``, ``NO``, or ``UNKNOWN``.

    Only an anchored uppercase verdict token is accepted. Malformed prose,
    hedging, or an explanation that contradicts the verdict abstains as
    ``UNKNOWN``; unstructured text never defaults to affirmation. No I/O.
    """
    if not text or not text.strip():
        return "UNKNOWN"
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "UNKNOWN"
    match = _CONFAB_FIRST_LINE_RE.fullmatch(lines[0])
    if match is None:
        return "UNKNOWN"
    verdict = match.group(1)
    if verdict == "UNKNOWN":
        return "UNKNOWN"

    inline_explanation = (match.group(3) or "").strip()
    trailing_lines = lines[1:]
    if len(trailing_lines) > 1 or (inline_explanation and trailing_lines):
        return "UNKNOWN"
    explanation = inline_explanation or (trailing_lines[0] if trailing_lines else "")
    if not explanation:
        return verdict
    if (
        _CONFAB_HEDGE_RE.search(explanation)
        or _CONFAB_DOUBLE_NEGATION_RE.search(explanation)
    ):
        return "UNKNOWN"
    explicit_verdicts = [
        value.upper() for value in _CONFAB_EXPLICIT_VERDICT_RE.findall(explanation)
    ]
    if any(other != verdict for other in explicit_verdicts):
        return "UNKNOWN"
    if verdict == "YES" and _CONFAB_DENIAL_SIGNAL_RE.search(explanation):
        return "UNKNOWN"
    if verdict == "NO" and _has_unnegated_affirmation(explanation):
        return "UNKNOWN"
    return verdict


def _has_unnegated_affirmation(explanation: str) -> bool:
    """Return True when a common positive existence claim is not negated."""
    for match in _CONFAB_AFFIRM_SIGNAL_RE.finditer(explanation):
        prefix = explanation[:match.start()].lower()
        clause_prefix = re.split(
            r"[,;:.!?]|\b(?:and|but|however|although|yet)\b", prefix
        )[-1]
        prefix_words = re.findall(r"[a-z0-9]+", clause_prefix)[-6:]
        if not _CONFAB_NEGATION_WORDS.intersection(prefix_words):
            return True
    return False


async def probe_referent(
    llm_client: Any,
    token: str,
    *,
    samples: int = _CONFAB_PROBE_SAMPLES,
    tier: str = _CONFAB_PROBE_TIER,
    temperature: float = _CONFAB_PROBE_TEMPERATURE,
) -> ProbeResult:
    """Run ``samples`` independent, context-free existence probes on ``token``.

    Issues N concurrent ``llm_client.complete`` calls with fresh request objects
    and unique semantically inert prompt nonces. Each prompt carries ONLY the
    token — never a seed/transcript. Only structured YES/NO samples are usable;
    UNKNOWN or malformed responses abstain. Divergence requires the existing
    minimum usable count and affirm-rate threshold.

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
        n = max(1, samples)
        batch_nonce = uuid.uuid4().hex
        requests = [
            LLMRequest(
                prompt=(
                    f"Does an entity, component, service, or identifier named "
                    f"'{token}' exist on this ship? Respond with YES, NO, or "
                    f"UNKNOWN on the first non-empty line. Use UNKNOWN when "
                    f"evidence is insufficient or equivocal.\n"
                    f"Independent sample nonce: {batch_nonce}:{index}. Do not "
                    f"use the nonce as evidence."
                ),
                system_prompt=_CONFAB_PROBE_SYSTEM_PROMPT,
                tier=tier,
                temperature=temperature,
                max_tokens=_CONFAB_PROBE_MAX_TOKENS,
            )
            for index in range(n)
        ]
        results = await asyncio.gather(
            *[llm_client.complete(request) for request in requests],
            return_exceptions=True,
        )
        texts: list[str] = []
        verdicts: list[str] = []
        for r in results:
            if isinstance(r, asyncio.CancelledError):
                raise r
            if isinstance(r, BaseException):
                logger.debug(
                    "AD-1121: probe sample failed for token=%r: %s",
                    token, type(r).__name__,
                )
                continue
            content = getattr(r, "content", None)
            if not content or not str(content).strip():
                continue
            text = str(content)
            texts.append(text)
            verdicts.append(_classify_existence(text))
        usable = sum(1 for verdict in verdicts if verdict in ("YES", "NO"))
        affirm = sum(1 for verdict in verdicts if verdict == "YES")
        is_divergent = (
            usable >= _CONFAB_MIN_USABLE_SAMPLES
            and (affirm / usable) < _CONFAB_AFFIRM_THRESHOLD
        )
        abstained = len(verdicts) - usable
        if abstained:
            logger.debug(
                "AD-1121: probe samples abstained for token=%r "
                "(usable=%d abstained=%d)",
                token, usable, abstained,
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
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning(
            "AD-1121: divergence probe for token=%r raised unexpectedly; "
            "returning non-divergent (no false flag)",
            token, exc_info=True,
        )
        return ProbeResult(token=token, usable=0, affirm=0, is_divergent=False)
