"""AD-1030: pure salience scoring for context bids.

A transparent *linear* salience over normalized terms::

    salience = (w_rel·relevance + w_rec·recency + w_imp·importance) / Σw

— the Generative-Agents-style scorer the Attention Faculty (AD-1029) uses to
make episodic + working-memory bids *adaptive* (selected/ordered by how much
they matter to the current goal) instead of fixed insertion priority.

This module is PURE: no I/O, no embedding model, no clock. The caller supplies
``relevance`` (a cosine similarity to the goal — :func:`cosine_similarity` here
is pure vector math, the embeddings are produced by the caller) and the raw
age/importance; everything here is deterministic and unit-testable.

Deferred (NOT implemented here): spreading activation (AD-604) as an additional
relevance contributor. That engine is asynchronous and dormant and belongs in
the (async) recall path, not this synchronous scorer — wiring it in is a
follow-up. There is no ``await`` anywhere in this module by design.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

__all__ = [
    "SalienceWeights",
    "cosine_similarity",
    "recency_decay",
    "importance_norm",
    "compute_salience",
    "visual_reference_score",
]


@dataclass(frozen=True)
class SalienceWeights:
    """Linear weights for :func:`compute_salience`.

    The weights are normalized at use (divided by their sum), so only their
    relative magnitudes matter — the absolute scale is free. Defaults bias
    toward relevance while still rewarding recency and importance.

    To OMIT a term (e.g. working memory carries no importance signal), set its
    weight to ``0.0`` — the term then contributes nothing AND drops out of the
    normalizing denominator.
    """

    w_rel: float = 1.0
    w_rec: float = 0.5
    w_imp: float = 0.5


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Cosine similarity of two dense vectors, clamped to ``[0.0, 1.0]``.

    Pure vector math (no embedding model). Returns ``0.0`` for empty,
    length-mismatched, or zero-magnitude inputs — a safe-degrade relevance of
    zero rather than an error, so a memory with no stored embedding simply
    scores no relevance.

    Note: this mirrors the two pre-existing PRIVATE copies in
    ``knowledge/embeddings.py`` and ``cognitive/episode_clustering.py``;
    consolidating all three into one shared helper is a separate cleanup
    (out of AD-1030 scope). This public copy is the canonical home for the
    salience relevance term and keeps this module self-contained / testable.
    """
    if len(vec_a) != len(vec_b) or not vec_a:
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    mag_a = math.sqrt(sum(a * a for a in vec_a))
    mag_b = math.sqrt(sum(b * b for b in vec_b))
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return max(0.0, min(1.0, dot / (mag_a * mag_b)))


def recency_decay(age_seconds: float, half_life: float) -> float:
    """Exponential recency term in ``[0.0, 1.0]``: ``exp(-age / half_life)``.

    ``age=0`` (or negative, e.g. clock skew) → ``1.0`` (most recent); as age
    grows the term decays toward ``0.0``. ``half_life`` is the decay
    time-constant in seconds (an e-folding time: at ``age == half_life`` the
    term is ``exp(-1) ≈ 0.368``). A non-positive ``half_life`` degrades to
    ``1.0`` (no decay) rather than dividing by zero.
    """
    if half_life <= 0.0:
        return 1.0
    if age_seconds <= 0.0:
        return 1.0
    return math.exp(-age_seconds / half_life)


def importance_norm(importance: float) -> float:
    """Normalize a 1–10 importance score (AD-598) to ``[0.0, 1.0]``.

    ``(importance - 1) / 9``, clamped — so ``1`` → ``0.0``, ``10`` → ``1.0``,
    and the neutral ``5`` → ``≈0.444``. Out-of-range inputs clamp into range.
    """
    return max(0.0, min(1.0, (importance - 1.0) / 9.0))


def compute_salience(
    *,
    relevance: float,
    recency: float,
    importance: float,
    weights: SalienceWeights,
) -> float:
    """Transparent linear salience over normalized ``[0, 1]`` terms.

    Returns ``(w_rel·rel + w_rec·rec + w_imp·imp_norm) / (w_rel + w_rec +
    w_imp)`` — the weight-normalized weighted sum, so the result stays in
    ``[0.0, 1.0]`` regardless of the absolute weight scale.

    Args:
        relevance: embedding similarity to the goal, expected in ``[0, 1]``
            (the caller supplies a cosine similarity); clamped defensively.
        recency: recency term in ``[0, 1]`` (use :func:`recency_decay`);
            clamped defensively.
        importance: the RAW 1–10 importance score (AD-598); normalized here via
            :func:`importance_norm`. Pass ``5.0`` (neutral) for sources with no
            importance signal AND set ``weights.w_imp = 0.0`` to omit the term.
        weights: the linear weights (normalized at use).

    Returns:
        The salience in ``[0.0, 1.0]``; ``0.0`` when every weight is zero.
    """
    rel = max(0.0, min(1.0, relevance))
    rec = max(0.0, min(1.0, recency))
    imp = importance_norm(importance)
    w_sum = weights.w_rel + weights.w_rec + weights.w_imp
    if w_sum <= 0.0:
        return 0.0
    return (weights.w_rel * rel + weights.w_rec * rec + weights.w_imp * imp) / w_sum


# ---------------------------------------------------------------------------
# AD-1031: visual-reference detection for the camera-scene salience gate.
# ---------------------------------------------------------------------------

# Single-word vision references. Matched on WORD BOUNDARIES (via tokenization)
# so ``"seem"`` does not match ``"see"`` and ``"overlook"`` does not match
# ``"look"``. Inflected forms are listed explicitly (the gate is a transparent
# keyword check, not a stemmer).
_VISUAL_REFERENCE_WORDS: frozenset[str] = frozenset({
    "see", "seeing", "saw", "seen",
    "look", "looking", "looks",
    "watch", "watching",
    "screen", "camera", "visual", "visually",
    "wearing", "wear",
    "picture", "image", "photo", "video",
})

# Multi-word vision references. Matched as substrings of the lowercased text.
_VISUAL_REFERENCE_PHRASES: tuple[str, ...] = (
    "what do you see",
    "what can you see",
    "do you see",
    "can you see",
    "look at",
    "show me",
    "behind me",
    "on screen",
    "on the screen",
    "this image",
    "this picture",
    "on camera",
)

_VISUAL_TOKEN_RE = re.compile(r"[a-z]+")


def visual_reference_score(text: str) -> float:
    """AD-1031: ``1.0`` if ``text`` references vision, else ``0.0``.

    A PURE keyword/phrase detector (no I/O, no model, no clock) used by the
    camera-scene salience gate to decide whether the Captain's turn REFERENCES
    seeing / the camera / the screen / an image — the strongest salience signal
    (an explicit visual reference ALWAYS surfaces the full live scene). Empty or
    non-string input scores ``0.0``.

    Detection is two-layer: multi-word phrases (e.g. ``"what do you see"``,
    ``"show me"``, ``"on screen"``) match as substrings of the lowercased text;
    single-word keywords (``"see"``, ``"camera"``, ``"wearing"`` …) match on word
    boundaries via tokenization, so substrings like ``"seem"`` / ``"overlook"``
    do NOT false-positive. The result is a ``float`` (not ``bool``) so the gate
    can later weight it alongside other salience terms without a type change.
    """
    if not text or not isinstance(text, str):
        return 0.0
    lowered = text.lower()
    for phrase in _VISUAL_REFERENCE_PHRASES:
        if phrase in lowered:
            return 1.0
    tokens = set(_VISUAL_TOKEN_RE.findall(lowered))
    if tokens & _VISUAL_REFERENCE_WORDS:
        return 1.0
    return 0.0


def suppress_visual_injection(
    *,
    referenced: bool,
    is_visual_task: bool,
    raw_novelty: float,
    decayed_novelty: float,
    novelty_minimum: float,
    suppress_threshold: float,
) -> bool:
    """AD-1060: decide whether to SUPPRESS visual-scene injection this turn.

    Pure (no I/O, no model, no clock). The camera feed fades to background when
    the scene is a stable, unremarkable constant: suppress ONLY when the decayed
    (EMA) novelty has fallen below ``suppress_threshold`` AND the latest frame
    did not materially change (``raw_novelty < novelty_minimum``) AND the Captain
    did not reference vision AND it is not a visual task. Any of those escape
    hatches forces injection, preserving responsiveness (a sudden change after a
    long quiet stretch still surfaces immediately via ``raw_novelty``).

    ``suppress_threshold <= 0`` disables suppression entirely \u2014 byte-identical to
    the AD-1031 always-inject bid.
    """
    if suppress_threshold <= 0.0:
        return False
    if referenced or is_visual_task:
        return False
    if raw_novelty >= novelty_minimum:
        return False
    return decayed_novelty < suppress_threshold
