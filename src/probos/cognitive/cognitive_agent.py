"""CognitiveAgent — agent whose decide() step consults an LLM guided by instructions."""

from __future__ import annotations

import hashlib
import asyncio
import inspect
import json
import logging
import math
import os
import re
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime, timezone
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar, cast

from probos.events import EventType, SensoriumBudgetExceededEvent
from probos.cognitive.concurrency_manager import ConcurrencyManager
from probos.cognitive.attention import AttentionBid, ContextAssembler, estimate_tokens
from probos.cognitive.tiered_knowledge import TieredKnowledgeLoader
from probos.substrate.agent import BaseAgent
from probos.types import (
    AnchorFrame,
    HandlerLatencyClass,
    IntentMessage,
    IntentResult,
    LLMRequest,
    Priority,
    Skill,
)
from probos.cognitive.sub_task import CHAIN_PRIORITY_KEY  # BF-688
from probos.utils import format_duration

if TYPE_CHECKING:
    from probos.cognitive.attention_faculty import AttentionFaculty
    from probos.cognitive.episodic import RecallConfidence
    from probos.cognitive.memory_budget import MemoryBudgetManager
    from probos.cognitive.question_classifier import QuestionClassifier, RetrievalStrategySelector
    from probos.cognitive.salience import SalienceWeights
    from probos.cognitive.spreading_activation import SpreadingActivationEngine
    from probos.cognitive.thought_store import ThoughtStore
    from probos.config import MemoryBudgetConfig

logger = logging.getLogger(__name__)

# Module-level decision cache keyed by agent_type (AD-272)
_DECISION_CACHES: dict[str, dict[str, tuple[dict, float, float]]] = {}
# {agent_type: {hash: (decision_dict, created_at_monotonic, ttl_seconds)}}
_CACHE_HITS: dict[str, int] = {}
_CACHE_MISSES: dict[str, int] = {}

# PROBOS_SKILL_DEBUG=1 — verbose skill loading diagnostics at INFO level.
# Shows why augmentation skills matched/missed, proficiency gate results,
# and catalog state. Toggle on to diagnose skill injection issues.
_SKILL_DEBUG = os.environ.get("PROBOS_SKILL_DEBUG", "").lower() in ("1", "true", "yes")

# AD-632f: Intents eligible for multi-step sub-task chain activation.
_CHAIN_ELIGIBLE_INTENTS: frozenset[str] = frozenset({
    "ward_room_notification",
    "proactive_think",
})

# AD-1028: ContextAssembler token budget. When attention.enabled is False
# (default), _build_user_message routes its blocks through the bid assembler
# with this effectively-unbounded budget so nothing is dropped and the prompt
# is byte-identical to the prior push-style prepend chain. When enabled, the
# configured MemoryConfig.attention.token_budget is used instead — the first
# global guard against context-window overflow.
_UNBOUNDED_ATTENTION_TOKEN_BUDGET: int = 1_000_000_000
# Fallback budget when attention is enabled but the config field is absent
# (defensive — MemoryConfig.attention.token_budget always provides a default).
_DEFAULT_ATTENTION_TOKEN_BUDGET: int = 120_000

# AD-1031: zone_floor / salience scheme for the camera-scene bid (DM path).
# The natural DM bids use ``zone_floor == emission index`` (0..~12) and a
# default salience (fixed insertion priority, or the AD-1030 scored value in
# [0, 1]). The ContextAssembler ORDERS survivors ascending by
# ``(zone_floor, insertion_order)`` and SELECTS unpinned bids by DESCENDING
# salience under a scarce budget. So:
#   • PROMINENT camera scene → a strongly-negative zone_floor sorts it BEFORE
#     every natural bid (it LEADS the prompt, approximating the old AD-733a
#     prepend's primacy) + a very high salience so it always survives a scarce
#     budget (the scene was unconditionally present before).
#   • RECESSIVE camera scene → a large positive zone_floor sorts it AFTER all
#     natural bids (it TRAILS the substantive context) + a negative salience so
#     it is the FIRST unpinned bid dropped when the budget is tight
#     (present-but-quiet). The other bids' zone_floor/salience are unchanged.
_CAMERA_PROMINENT_ZONE_FLOOR: int = -1_000_000
_CAMERA_PROMINENT_SALIENCE: float = 1_000_000.0
_CAMERA_RECESSIVE_ZONE_FLOOR: int = 1_000_000
_CAMERA_RECESSIVE_SALIENCE: float = -1.0


class SensoriumLayer(StrEnum):
    """AD-666: Three-layer classification for agent context injections."""

    PROPRIOCEPTION = "proprioception"
    INTEROCEPTION = "interoception"
    EXTEROCEPTION = "exteroception"


class SensoriumPath(StrEnum):
    """AD-723: prompt-assembly paths that consume sensorium injections.

    Each registry entry declares which paths consume it via its ``paths``
    tuple. The dispatcher iterates the registry once per path; an entry
    with an empty ``paths`` tuple is inventory-only (documented but never
    rendered into a prompt).
    """

    CHAIN_BASELINE = "chain_baseline"
    """Universal cognitive baseline — runs for ALL chain executions."""

    CHAIN_EXTENSIONS = "chain_extensions"
    """Proactive-conditional overrides — populated by proactive.py context_parts."""

    CHAIN_SITUATION = "chain_situation"
    """Environmental percepts — WR activity, alerts, infra, subordinates."""

    DM_ONESHOT = "dm_oneshot"
    """1:1 conversation with the Captain — System-1 path, single LLM call.

    AD-723 v1 ships producer-side only: registry entries declare DM_ONESHOT
    paths so future sensorium ADs only edit the registry, but the inline
    DM-branch consumer in ``_build_user_message`` is migrated by AD-723a-1.
    """

    WR_ONESHOT = "wr_oneshot"
    """Ward Room channels — peer audience; intentionally narrower than DM.

    Same v1-producer-side note as ``DM_ONESHOT``.
    """


@dataclass(frozen=True)
class SensoriumEntry:
    """AD-723: registry record describing how a sensorium injection is dispatched.

    Replaces the prior ``tuple[SensoriumLayer, str]`` inventory shape with
    a dispatch-aware record. ``paths`` declares which prompt-assembly paths
    consume the entry. Empty ``paths`` is allowed for inventory-only entries
    (meta-methods that delegate rather than render).
    """

    layer: SensoriumLayer
    description: str
    paths: tuple[SensoriumPath, ...] = ()
    priority: int = 0
    output_key: str | None = None
    """Key under which the entry's string output is stored in the merged dict.

    When ``None``, the entry's registered method MUST return ``dict[str, str]``
    or ``None`` (no single-key output). When set, the method MUST return
    ``str`` or ``None`` and the dispatcher stores ``result`` under
    ``output_key`` in the merged dict.
    """
    injection_zone: str | None = None
    """AD-723a-3: opaque zone identifier describing where in the prompt the
    entry renders. v1 reserved values: ``temporal_header``, ``working_memory``,
    ``post_episodic``, ``self_recognition``. The dispatcher does NOT route by
    zone in v1 — observation metadata only; consumers query as needed.
    """
    wrapper: object | None = None
    """AD-723a-3: optional ``Callable[[str], str]`` that wraps the registered
    method's output with framing markers (e.g., ``--- Temporal Awareness ---``).

    Typed as ``object | None`` instead of ``Callable[[str], str] | None`` so
    the frozen dataclass remains hashable under all Python versions (some
    interpreters trip on the bound-method-vs-function hash divergence under
    ``frozen=True``). The dispatcher runtime-checks via ``callable(...)``.
    """


def derive_communication_context(
    channel_name: str,
    is_dm_channel: bool = False,
) -> str:
    """AD-649: Derive communication register context from channel metadata."""
    if is_dm_channel or channel_name.startswith("dm-"):
        return "private_conversation"
    if channel_name == "bridge":
        return "bridge_briefing"
    if channel_name == "recreation":
        return "casual_social"
    if channel_name in ("general", "all-hands"):
        return "ship_wide"
    return "department_discussion"


def _filter_query_echoes(episodes: list[Any], query: str) -> list[Any]:
    """BF-631: drop recalled episodes that merely re-state the current query.

    When the Captain asks a question, the most semantically-similar episodes are
    frequently the Captain's OWN prior identical askings (e.g. "What do you know
    about my dogs?"). Such a recalled "memory" carries no information for
    answering the question — it IS the question — yet, being a near-perfect
    match to the query text, it out-ranks and crowds the genuine answer ("My dog
    Grim is a giant schnauzer") to the bottom of, or out of, the rendered memory
    section.

    Matching is normalized-substring (case/whitespace-insensitive): the live
    query appearing verbatim inside an episode is a near-certain echo, so the
    false-positive risk is low. Only substantive queries (>=12 normalized chars)
    are filtered, and the original list is returned unchanged when every episode
    would be dropped (all-echo => there is no answer to surface anyway).

    Pure function — does not mutate ``episodes``.
    """
    if not query or not episodes:
        return episodes
    q_norm = " ".join(query.lower().split())
    if len(q_norm) < 12:
        return episodes
    non_echo = [
        ep for ep in episodes
        if q_norm not in " ".join((getattr(ep, "user_input", "") or "").lower().split())
    ]
    return non_echo if non_echo else episodes


def _dm_recall_query(params: dict[str, Any]) -> str:
    """BF-632: the per-message episodic-recall query for a ``direct_message``.

    Returns the RAW Captain message (``params['captain_message']``), NOT
    ``params['text']``. The HXI router (``routers/agents.py:agent_chat``)
    PREPENDS the visual-context block (AD-733a), project preamble (AD-793), and
    targeted-recall block (AD-725) onto ``text`` so the receiving agent's LLM
    sees them as part of the user turn — which means ``text[:200]`` is the
    *visual scene description*, not what the Captain asked. Driving recall off
    ``text`` made every 1:1 recall search for the room instead of the Captain's
    words (the proven cause of the dogs never surfacing). Falls back to ``text``
    for callers that don't set ``captain_message`` (e.g. work-item dispatch,
    where ``text`` is already the raw task). Mirrors the prior
    ``text[:200].strip()`` shape.
    """
    raw = params.get("captain_message") or params.get("text", "")
    return raw[:200].strip()


def _enrich_vision_messages_with_context(
    vision_messages: list[dict[str, Any]],
    user_message: str,
) -> list[dict[str, Any]] | None:
    """BF-266: Fold the fully-assembled user_message into the multimodal
    content array, preserving image blocks.

    The router (AD-730, routers/agents.py:agent_chat) builds
    ``vision_messages`` from the RAW Captain text only. The agent's
    perception path produces a richer ``user_message`` containing temporal
    awareness, working memory, episodic recall, session history, avatar
    self-observation, and the intent self-tag instruction. Without this
    enrichment the agent loses all conversational context when it routes
    to the vision tier.

    Returns the enriched messages array (Anthropic-shape), or ``None`` if
    no image blocks could be extracted from the original ``vision_messages``
    (caller should degrade to text-only path).

    Pure function — does not mutate ``vision_messages``.
    """
    if not vision_messages:
        return None
    try:
        first_msg = vision_messages[0]
        content = first_msg.get("content", []) if isinstance(first_msg, dict) else []
        if not isinstance(content, list):
            return None
        image_blocks = [
            item for item in content
            if isinstance(item, dict) and item.get("type") == "image"
        ]
    except Exception:  # tier-2 degrade — caller falls back to text-only
        return None
    if not image_blocks:
        return None
    enriched_content: list[dict[str, Any]] = [
        {"type": "text", "text": user_message}
    ]
    enriched_content.extend(image_blocks)
    return [{"role": "user", "content": enriched_content}]


def _classify_concurrency_priority(intent: IntentMessage) -> int:
    """AD-672: Map intent to concurrency priority on a 0-10 scale."""
    is_captain = intent.params.get("is_captain", False)
    was_mentioned = intent.params.get("was_mentioned", False)
    is_dm = intent.params.get("is_dm_channel", False) or intent.intent == "direct_message"

    if is_captain or was_mentioned:
        return 10
    if is_dm:
        return 8
    if intent.intent == "ward_room_notification":
        return 5
    if intent.intent == "proactive_think":
        return 2
    return 5


def _coerce_promotion_budget(raw: Any) -> float:
    """AD-1165: read ``dm_agentic.promote_to_task_after_seconds`` defensively.

    The config object reaches this path as ``Any`` — every synthetic-runtime
    test builds it as a ``SimpleNamespace`` or a ``MagicMock``, and a MagicMock
    auto-creates the attribute as a truthy proxy whose comparisons return
    another MagicMock rather than a bool. Reading the budget with a bare
    ``getattr`` and comparing it would therefore make the arming decision on a
    value that is not a number at all. An exact ``type`` check (which also
    excludes ``bool``, a numeric subclass) is the boundary: anything that is not
    a real finite positive number means OFF, which is the byte-identical path.
    """
    if type(raw) not in (int, float):
        return 0.0
    value = float(raw)
    if not math.isfinite(value) or value <= 0.0:
        return 0.0
    return value


def _promotion_request_text(observation: dict[str, Any], fallback: str) -> str:
    """AD-1165: the text a promoted turn's work item records as the request.

    Prefers the Captain's RAW message over the assembled prompt. ``fallback`` is
    the fully composed ``user_message``, which carries working memory, episodic
    recall and session history — thousands of characters of context that would
    make a board row unreadable. ``captain_message`` is set by the DM router
    (``routers/agents.py``) precisely so downstream consumers can recover what
    was actually said; ``text`` is the same message after any visual-scene
    prefix, so it is the second choice rather than the first.
    """
    params = observation.get("params")
    sources = (
        (params or {}).get("captain_message") if type(params) is dict else None,
        (params or {}).get("text") if type(params) is dict else None,
        observation.get("captain_message"),
    )
    for candidate in sources:
        if type(candidate) is str and candidate.strip():
            return candidate
    return fallback


def _conversational_thread_id(
    observation: dict[str, Any],
    runtime: Any,
    *,
    agent_id: str,
    title: str,
) -> str:
    """BF-698: the chat thread a 1:1 turn belongs to, from three sources.

    Measured on the reference vessel 2026-07-30: the DM router resolved the
    thread, wrote the Captain's message into it, and set
    ``IntentMessage.thread_id`` — and the value still arrived here as ``""``.
    Everything downstream that needs it reads one dict key: AD-809 resolves the
    per-thread personality overlay from it, AD-1066 binds produced artifacts
    with it, AD-1165 promotes a long turn with it. Each degrades to a silent
    no-op against an absent key, so one path that loses it takes three
    capabilities with it and reports nothing.

    The agent's canonical thread is a fact the **store** owns. Deriving it there
    is strictly more robust than trusting the key, so the key becomes a
    preference rather than a dependency:

    1. ``observation["thread_id"]`` — set by ``perceive`` from the intent.
    2. ``observation["params"]["thread_id"]`` — the convention several other
       handlers use (ward-room self-post, BF-239), checked before falling back
       because it is still *this turn's* thread.
    3. ``get_or_create_default_for_agent`` — the same race-safe
       (``BEGIN IMMEDIATE``) call the DM router itself makes.

    **Known imprecision, stated rather than hidden.** Source 3 returns the
    agent's *default* thread. If the Captain were in a second, explicitly
    created thread with the same agent and the first two sources were both
    empty, a promoted report would land in the default thread instead. That is a
    worse outcome than getting it right and a better one than losing the work,
    and the WARNING below names the agent every time it happens, so the case is
    visible rather than silent.

    Module-level rather than a method on purpose: it takes no agent state beyond
    an id and a display title, and every synthetic-runtime test harness builds
    its agent as a ``SimpleNamespace``, so a new method call on that path breaks
    each harness until it is individually taught to bind it. A free function
    with explicit inputs is both testable in isolation and inert to that class
    of breakage.

    Returns ``""`` when no thread can be resolved — no store, or a store that
    raises. Callers treat that exactly as they treat today's empty value, so
    this can only ever add a destination, never remove one.
    """
    from_observation = str(observation.get("thread_id", "") or "")
    if from_observation:
        return from_observation

    params = observation.get("params")
    if type(params) is dict:
        from_params = str(params.get("thread_id", "") or "")
        if from_params:
            logger.info(
                "BF-698: observation carried no thread_id for agent=%s; using "
                "the params thread %s",
                agent_id, from_params,
            )
            return from_params

    store = getattr(runtime, "chat_thread_store", None)
    if store is None:
        return ""
    try:
        thread = store.get_or_create_default_for_agent(agent_id, title or agent_id)
    except Exception:
        logger.warning(
            "BF-698: could not resolve a canonical thread for agent=%s; the "
            "turn proceeds without thread provenance, so produced artifacts "
            "stay unbound and a long turn cannot be promoted",
            agent_id, exc_info=True,
        )
        return ""

    resolved = getattr(thread, "id", None)
    # An exact ``str`` check, not ``str(...)``. Every synthetic-runtime test
    # builds ``runtime`` as a MagicMock, whose ``chat_thread_store`` attribute
    # auto-creates as a truthy proxy and whose ``get_or_create_default_for_agent``
    # returns another proxy. Coercing that with ``str()`` yields a plausible-
    # looking "<MagicMock id=...>" and hands it downstream as a thread id. The
    # same phantom-attribute trap AD-1062 hit with ``system_trigger``.
    if type(resolved) is not str or not resolved:
        return ""
    # WARNING, not INFO: the system compensated, but something upstream dropped
    # provenance it was handed, and that is the signal that finds the root
    # cause. If this fires on every turn, that is information.
    logger.warning(
        "BF-698: neither observation nor params carried a thread_id for "
        "agent=%s; resolved the canonical thread %s from the store. The "
        "producer that should have supplied it is still unidentified",
        agent_id, resolved,
    )
    return resolved


class CognitiveAgent(BaseAgent):
    # AD-647b v1: agents that own a registered ProcessChainDefinition set
    # this to the chain_id ("name" of the definition). When set, the
    # AD-632 communication-chain gate (_should_activate_chain) returns
    # False for any observation whose duty_id matches — the agent runs
    # its process chain via runtime.process_chain_registry instead.
    process_chain_id: str | None = None
    """Agent whose decide() step consults an LLM guided by instructions.

    The perceive/decide/act/report lifecycle is preserved.  ``decide()``
    invokes the LLM with ``instructions`` as the system prompt and the
    current observation (from ``perceive()``) as the user message.
    ``act()`` executes based on the LLM's decision — subclasses override
    it for structured output parsing.
    """

    tier = "domain"  # Cognitive agents are domain-tier by default
    handler_latency_class: HandlerLatencyClass = HandlerLatencyClass.COGNITIVE

    # Default cache TTL — overridden by _get_cache_ttl() based on instructions
    _cache_ttl_seconds: float = 300.0  # 5 minutes

    # Subclasses MUST set these (or pass via __init__)
    instructions: str | None = None
    agent_type: str = "cognitive"
    _task_context: Any = None
    _question_classifier: QuestionClassifier | None = None
    _retrieval_strategy_selector: RetrievalStrategySelector | None = None

    # AD-666: Agent Sensorium Registry — formal inventory of context injections.
    # AD-723 v1 (producer-side): the registry is now a dispatch table. Each
    # entry's ``paths`` tuple declares which prompt-assembly paths consume
    # it; the chain-side dispatchers iterate this registry. DM/WR consumer
    # migration is deferred to AD-723a-1 (#617) per the Wave-10
    # high-entanglement rule — DM_ONESHOT / WR_ONESHOT paths on entries
    # below are forward-declarations that AD-723a-1 will wire into
    # ``_build_user_message``.
    SENSORIUM_REGISTRY: ClassVar[dict[str, "SensoriumEntry"]] = {
        # ---- PROPRIOCEPTION (self-state) ----
        "_sensorium_temporal_context": SensoriumEntry(
            layer=SensoriumLayer.PROPRIOCEPTION,
            description="Time, age, uptime, crew complement",
            paths=(SensoriumPath.CHAIN_BASELINE, SensoriumPath.DM_ONESHOT, SensoriumPath.WR_ONESHOT),
            output_key="_temporal_context",
        ),
        "_sensorium_comm_proficiency": SensoriumEntry(
            layer=SensoriumLayer.PROPRIOCEPTION,
            description="Communication tier guidance",
            paths=(SensoriumPath.CHAIN_BASELINE,),
            output_key="_comm_proficiency",
        ),
        "_sensorium_self_recognition": SensoriumEntry(
            layer=SensoriumLayer.PROPRIOCEPTION,
            description="Cross-context self-recognition",
            paths=(SensoriumPath.CHAIN_BASELINE, SensoriumPath.WR_ONESHOT),
            output_key="_self_recognition_cue",
        ),
        "_build_dm_self_monitoring": SensoriumEntry(
            layer=SensoriumLayer.PROPRIOCEPTION,
            description="DM repetition self-detection",
            paths=(SensoriumPath.WR_ONESHOT,),
            output_key="_dm_self_monitoring",
        ),
        "_confabulation_guard": SensoriumEntry(
            layer=SensoriumLayer.PROPRIOCEPTION,
            description="Authority-calibrated confab guard (inventory; embedded in baseline + extensions entries)",
        ),
        "_build_crew_complement": SensoriumEntry(
            layer=SensoriumLayer.PROPRIOCEPTION,
            description="Anti-confabulation crew roster (inventory; embedded in temporal context)",
        ),
        # AD-722a: registered as inventory + chain/DM-path declaration.
        # Default-OFF (divergence_detection=False) → method returns "" → no
        # key contributed → byte-identical to pre-AD-723 chain baseline.
        # AD-723a-1 wires the DM-side rendering consumer.
        "_build_intent_self_tag_instruction": SensoriumEntry(
            layer=SensoriumLayer.PROPRIOCEPTION,
            description="AD-722a: instruct LLM to emit a self-tag (feature-gated)",
            paths=(SensoriumPath.CHAIN_BASELINE, SensoriumPath.DM_ONESHOT),
            output_key="_intent_self_tag",
        ),
        # ---- INTEROCEPTION (cognitive state) ----
        "_build_cognitive_baseline": SensoriumEntry(
            layer=SensoriumLayer.INTEROCEPTION,
            description="Meta-method: dispatches CHAIN_BASELINE (inventory)",
        ),
        "_build_cognitive_extensions": SensoriumEntry(
            layer=SensoriumLayer.INTEROCEPTION,
            description="Meta-method: dispatches CHAIN_EXTENSIONS (inventory)",
        ),
        "_build_cognitive_state": SensoriumEntry(
            layer=SensoriumLayer.INTEROCEPTION,
            description="Meta-method: merges baseline + extensions (inventory)",
        ),
        "_sensorium_working_memory": SensoriumEntry(
            layer=SensoriumLayer.INTEROCEPTION,
            description="AD-573 working memory render",
            paths=(SensoriumPath.CHAIN_BASELINE, SensoriumPath.DM_ONESHOT, SensoriumPath.WR_ONESHOT),
            output_key="_working_memory_context",
        ),
        "_sensorium_agent_metrics": SensoriumEntry(
            layer=SensoriumLayer.INTEROCEPTION,
            description="Trust / Initiative / Agency / Rank summary",
            paths=(SensoriumPath.CHAIN_BASELINE,),
            output_key="_agent_metrics",
        ),
        "_sensorium_ontology_baseline": SensoriumEntry(
            layer=SensoriumLayer.INTEROCEPTION,
            description="Ontology identity grounding (runtime-sourced)",
            paths=(SensoriumPath.CHAIN_BASELINE,),
            output_key="_ontology_context",
        ),
        "_sensorium_source_attribution_baseline": SensoriumEntry(
            layer=SensoriumLayer.INTEROCEPTION,
            description="Source attribution (simplified, no authority class)",
            paths=(SensoriumPath.CHAIN_BASELINE,),
            output_key="_source_attribution_text",
        ),
        "_sensorium_confab_guard_baseline": SensoriumEntry(
            layer=SensoriumLayer.INTEROCEPTION,
            description="Confabulation guard (generic, no authority)",
            paths=(SensoriumPath.CHAIN_BASELINE,),
            output_key="_confabulation_guard",
        ),
        "_sensorium_no_memories_flag": SensoriumEntry(
            layer=SensoriumLayer.INTEROCEPTION,
            description="No-memories flag (baseline default)",
            paths=(SensoriumPath.CHAIN_BASELINE,),
            output_key="_no_episodic_memories",
        ),
        "_sensorium_cold_start_note": SensoriumEntry(
            layer=SensoriumLayer.INTEROCEPTION,
            description="Cold-start runtime note",
            paths=(SensoriumPath.CHAIN_BASELINE,),
            output_key="_cold_start_note",
        ),
        "_sensorium_source_attribution_rich": SensoriumEntry(
            layer=SensoriumLayer.INTEROCEPTION,
            description="AD-568d rich source attribution override",
            paths=(SensoriumPath.CHAIN_BASELINE,),
            output_key="_source_attribution_text",
        ),
        "_format_memory_section": SensoriumEntry(
            layer=SensoriumLayer.INTEROCEPTION,
            description="Episodic memories with anchor context (inventory; rendered inline by DM/WR consumers; AD-723a-1)",
        ),
        # AD-722: avatar self-observation. Default-OFF
        # (inject_into_agent_context=False) → returns "" → no key
        # contributed → byte-identical to pre-AD-723 baseline.
        "_build_avatar_self_observation": SensoriumEntry(
            layer=SensoriumLayer.INTEROCEPTION,
            description="AD-722: agent's own avatar state — gated by avatar_telemetry.inject_into_agent_context",
            paths=(SensoriumPath.CHAIN_BASELINE, SensoriumPath.DM_ONESHOT),
            output_key="_avatar_self_observation",
        ),
        # ---- CHAIN_EXTENSIONS (priority=10, override baseline by key) ----
        "_sensorium_ext_self_monitoring": SensoriumEntry(
            layer=SensoriumLayer.INTEROCEPTION,
            description="AD-504/506a self-monitoring extension",
            paths=(SensoriumPath.CHAIN_EXTENSIONS,),
            priority=10,
            output_key="_self_monitoring",
        ),
        "_sensorium_ext_source_attribution_authority": SensoriumEntry(
            layer=SensoriumLayer.INTEROCEPTION,
            description="Authority-aware source attribution override",
            paths=(SensoriumPath.CHAIN_EXTENSIONS,),
            priority=10,
            output_key="_source_attribution_text",
        ),
        "_sensorium_ext_introspective_telemetry": SensoriumEntry(
            layer=SensoriumLayer.INTEROCEPTION,
            description="AD-588 introspective telemetry",
            paths=(SensoriumPath.CHAIN_EXTENSIONS,),
            priority=10,
            output_key="_introspective_telemetry",
        ),
        "_sensorium_ext_ontology_from_context_parts": SensoriumEntry(
            layer=SensoriumLayer.INTEROCEPTION,
            description="Ontology override sourced from proactive context_parts",
            paths=(SensoriumPath.CHAIN_EXTENSIONS,),
            priority=10,
            output_key="_ontology_context",
        ),
        "_sensorium_ext_orientation_supplement": SensoriumEntry(
            layer=SensoriumLayer.INTEROCEPTION,
            description="AD-567g orientation supplement",
            paths=(SensoriumPath.CHAIN_EXTENSIONS,),
            priority=10,
            output_key="_orientation_supplement",
        ),
        "_sensorium_ext_confab_guard_authority": SensoriumEntry(
            layer=SensoriumLayer.INTEROCEPTION,
            description="Authority-calibrated confab guard override",
            paths=(SensoriumPath.CHAIN_EXTENSIONS,),
            priority=10,
            output_key="_confabulation_guard",
        ),
        "_sensorium_ext_no_memories_flag_override": SensoriumEntry(
            layer=SensoriumLayer.INTEROCEPTION,
            description="No-memories flag override (None = removal per AD-646)",
            paths=(SensoriumPath.CHAIN_EXTENSIONS,),
            priority=10,
            output_key="_no_episodic_memories",
        ),
        # ---- EXTEROCEPTION (environment / situation) ----
        "_build_situation_awareness": SensoriumEntry(
            layer=SensoriumLayer.EXTEROCEPTION,
            description="Meta-method: dispatches CHAIN_SITUATION (inventory)",
        ),
        "_sensorium_situation_ward_room_activity": SensoriumEntry(
            layer=SensoriumLayer.EXTEROCEPTION,
            description="AD-413 Ward Room activity (dept + all-hands + recreation)",
            paths=(SensoriumPath.CHAIN_SITUATION,),
            output_key="_ward_room_activity",
        ),
        "_sensorium_situation_recent_alerts": SensoriumEntry(
            layer=SensoriumLayer.EXTEROCEPTION,
            description="Recent bridge alerts",
            paths=(SensoriumPath.CHAIN_SITUATION,),
            output_key="_recent_alerts",
        ),
        "_sensorium_situation_recent_events": SensoriumEntry(
            layer=SensoriumLayer.EXTEROCEPTION,
            description="Recent system events",
            paths=(SensoriumPath.CHAIN_SITUATION,),
            output_key="_recent_events",
        ),
        "_sensorium_situation_infrastructure": SensoriumEntry(
            layer=SensoriumLayer.EXTEROCEPTION,
            description="AD-576 infrastructure status",
            paths=(SensoriumPath.CHAIN_SITUATION,),
            output_key="_infrastructure_status",
        ),
        "_sensorium_situation_subordinate_stats": SensoriumEntry(
            layer=SensoriumLayer.EXTEROCEPTION,
            description="AD-630 subordinate stats (Chiefs only)",
            paths=(SensoriumPath.CHAIN_SITUATION,),
            output_key="_subordinate_stats",
        ),
        "_sensorium_situation_clinical_telemetry": SensoriumEntry(
            layer=SensoriumLayer.EXTEROCEPTION,
            description="AD-635f clinical telemetry (Chapel, Echo only)",
            paths=(SensoriumPath.CHAIN_SITUATION,),
            output_key="_clinical_telemetry",
        ),
        "_sensorium_situation_system_note": SensoriumEntry(
            layer=SensoriumLayer.EXTEROCEPTION,
            description="BF-034 cold-start system note (situation channel)",
            paths=(SensoriumPath.CHAIN_SITUATION,),
            output_key="_cold_start_note",
        ),
        "_sensorium_situation_active_game": SensoriumEntry(
            layer=SensoriumLayer.EXTEROCEPTION,
            description="BF-110 active game state (situation channel)",
            paths=(SensoriumPath.CHAIN_SITUATION,),
            output_key="_active_game",
        ),
        "_build_active_game_context": SensoriumEntry(
            layer=SensoriumLayer.EXTEROCEPTION,
            description="Active game board state (inventory; DM-side rendered inline; AD-723a-1)",
        ),
        "_build_user_message": SensoriumEntry(
            layer=SensoriumLayer.EXTEROCEPTION,
            description="Primary prompt assembly (DM/WR paths) — orchestrator (inventory)",
        ),
    }

    # AD-723a-1 (Wave 148): keys from the DM_ONESHOT dispatch result that
    # render at the post-working-memory / pre-episodic injection zone
    # (where AD-722 currently injects). v1 limits migration to entries
    # whose registered method returns a self-wrapped block — i.e., output
    # that needs no DM-side framing markers. Other DM-tagged entries
    # (_temporal_context, _working_memory_context, _self_recognition_cue)
    # have hand-rolled DM-side wrappers that differ from registered
    # output; they migrate when AD-723a-3 lands position + wrapper
    # metadata on SensoriumEntry. When this tuple grows to 3+ keys,
    # AD-723a-3 becomes the forcing function.
    _DM_SELF_WRAPPED_KEYS: ClassVar[tuple[str, ...]] = (
        "_avatar_self_observation",
        "_intent_self_tag",
    )

    # AD-723a-2: WR (Ward Room) sibling of _DM_SELF_WRAPPED_KEYS.
    # Empty in v1 — no self-wrapped sensorium entries currently target
    # SensoriumPath.WR_ONESHOT exclusively. New entries with
    # ``paths=(WR_ONESHOT,)`` and self-wrapped output extend this tuple.
    _WR_SELF_WRAPPED_KEYS: ClassVar[tuple[str, ...]] = ()

    def __init__(self, **kwargs: Any) -> None:
        # Extract instructions from kwargs if provided (overrides class attr)
        if "instructions" in kwargs:
            self.instructions = kwargs.pop("instructions")

        super().__init__(**kwargs)

        # LLM client from kwargs (same pattern as designed agents)
        self._llm_client = kwargs.get("llm_client")

        # Runtime reference for mesh sub-intent dispatch
        self._runtime = kwargs.get("runtime")

        # Skills dict (AD-199)
        self._skills: dict[str, Skill] = {}

        # Strategy advisor (AD-384) — optional cross-agent knowledge transfer
        self._strategy_advisor = None

        # AD-534b: near-miss/failure context for fallback learning
        self._last_fallback_info: dict[str, Any] | None = None

        # AD-1165: live references to conversational turns that outgrew a reply
        # and were promoted to background tasks, plus their reporters. Held so
        # neither is garbage-collected mid-flight (Async Discipline); each entry
        # discards itself on completion. Deliberately NOT cancelled by ``stop()``
        # — a promoted turn is the Captain's work, and a pool rescale must not
        # kill it. It is bounded by ``max_iterations`` and the LLM timeouts, so
        # it always terminates on its own.
        self._promoted_turn_tasks: set[asyncio.Task[Any]] = set()

        # AD-423c: ToolContext, set during onboarding
        self.tool_context: Any = None

        # AD-573: Unified working memory — cognitive continuity across pathways
        from probos.cognitive.agent_working_memory import AgentWorkingMemory
        self._working_memory = AgentWorkingMemory()

        # AD-585: Tiered knowledge loader, set via set_knowledge_loader().
        self._knowledge_loader: TieredKnowledgeLoader | None = None

        # AD-632a: Sub-task protocol executor and pending chain
        self._sub_task_executor = None
        self._pending_sub_task_chain = None

        # AD-595e: Cached qualification standing (TTL-refreshed)
        self._qualification_standing: dict | None = None
        self._qualification_standing_ts: float = 0.0
        self._qualification_standing_ttl: float = 300.0  # 5 min

        # AD-672: Per-agent concurrency management
        self._concurrency_manager: ConcurrencyManager | None = None

        # AD-1122: bounded scalar debounce state for merged chain-sensorium
        # character-footprint telemetry. This state is per agent and never
        # retains prompt content.
        self._reset_sensorium_budget_state()

        # AD-722: most-recent reply emit timestamp (UNIX seconds).
        # Read via the public property `last_reply_emitted_at`.
        # Stamped by `mark_reply_emitted()` from the chat handler at
        # `routers/agents.py` (single call site — Demeter / SoT).
        self._last_reply_emit_ts: float = 0.0
        # AD-722: cache of most-recent self-avatar snapshot, populated by
        # `observe_self_avatar()` so the synchronous sensorium method can
        # consume it without spawning an event loop.
        self._last_self_avatar_snap: Any = None

        # AD-722a-2: per-audience ring buffer of chain-path divergence
        # events. Maxlen 8 per audience tier. Scoped to prevent
        # cross-channel surface pollution (AD-727 addendum h).
        from collections import deque as _deque
        self._chain_divergence_buffer: dict[str, Any] = {}
        self._chain_divergence_buffer_factory = lambda: _deque(maxlen=8)

        # AD-594: Crew Consultation Protocol
        self._consultation_protocol: Any = None

        # AD-602: Question-adaptive retrieval
        self._question_classifier: QuestionClassifier | None = None
        self._retrieval_strategy_selector: RetrievalStrategySelector | None = None
        self._spreading_activation: SpreadingActivationEngine | None = None  # AD-604
        self._thought_store: ThoughtStore | None = None  # AD-606
        self._current_correlation_id: str = ""

        # AD-573: Per-cycle memory budget configuration
        self._memory_budget_config: MemoryBudgetConfig | None = kwargs.get("memory_budget_config")

        # AD-586: Task-contextual standing orders
        self._task_context: Any = None

        # AD-1034: The cognitive spine — the agent's in-process, synchronous central
        # nervous system. Owns organ composition, drives the organ cognitive cycle,
        # carries the intra-organ signal channel, and provides the single governed
        # mesh-boundary inlet (deliver_exogenous). Constructed EMPTY: no organs are
        # registered by default, so the spine is inert and the agent is byte-identical
        # to pre-AD-1034 until a concrete organ (AD-1029) is composed.
        from probos.cognitive.spine import CognitiveSpine
        self._spine = CognitiveSpine(self)
        self._compose_organs()

        # Validate instructions exist
        if not self.instructions:
            raise ValueError(
                f"{self.__class__.__name__} requires non-empty instructions"
            )

    def _compose_organs(self) -> None:
        """AD-1034: the organ-composition dispatcher — attach the organs this agent is born with.

        Organs are *born with the parent* (Design Principle #12): this hook runs once at
        construction, right after the spine exists, and again idempotently if re-invoked. The
        base ``CognitiveAgent`` composes **zero** organs by default — so the running system is
        byte-identical to pre-AD-1034 until an organ is composed. Each organ has its own config
        gate + idempotency guard, so the dispatcher simply calls them in order; a disabled organ
        early-returns from its own composer. AD-1035: the dreaming composer is called AFTER the
        attention composer and is reached even when attention is OFF (the dispatcher never
        short-circuits — each composer is independently gated).
        """
        self._compose_attention_organ()
        self._compose_dreaming_organ()

    def _compose_attention_organ(self) -> None:
        """AD-1029: compose the deterministic :class:`AttentionFaculty` when attention is ON.

        When ``memory.attention.enabled`` is True (read via the same resolution
        :meth:`_resolve_attention_budget` uses), compose the deterministic
        :class:`AttentionFaculty`. Default-OFF ⇒ NO organ attached ⇒ ``_spine.has_organs``
        stays False ⇒ the ``drive_cycle`` hook is a no-op AND ``_build_user_message`` keeps
        the exact AD-1028 inline ``ContextAssembler`` path ⇒ byte-identical. Idempotent: a
        second call once the faculty is composed is a no-op.
        """
        if self._spine.get_organ("attention") is not None:
            return  # idempotent — the attention organ is already composed
        _rt = getattr(self, "_runtime", None)
        _mem_cfg = getattr(getattr(_rt, "config", None), "memory", None) if _rt else None
        _att_cfg = getattr(_mem_cfg, "attention", None)
        if _att_cfg is None or not getattr(_att_cfg, "enabled", False):
            return  # default-OFF — no faculty composed (byte-identical)
        from probos.cognitive.attention_faculty import AttentionFaculty
        from probos.cognitive.spine import EXOGENOUS_SIGNAL_KIND
        faculty = AttentionFaculty()
        faculty.set_audit_emit(self._emit_attention_audit)
        self._spine.attach_organ(faculty)
        # Exogenous salience (mentions/alerts/camera-change/gossip) arriving between turns
        # through the agent-owned ``deliver_exogenous`` inlet must reach the faculty's
        # pending state; the spine inlet is the seam (the real intent bus is AD-1032).
        self._spine.subscribe(EXOGENOUS_SIGNAL_KIND, faculty)

    def _compose_dreaming_organ(self) -> None:
        """AD-1035: compose the per-agent background :class:`DreamingOrgan` when dreaming is ON.

        When ``dreaming.organ_enabled`` is True, attach a background ``DreamingOrgan``.
        Default-OFF ⇒ NO organ attached ⇒ the shared runtime ``DreamingEngine`` +
        ``DreamScheduler`` remain the single source of truth ⇒ byte-identical. The organ is a
        BACKGROUND faculty (inherited no-op ``perceive``/``decide``/``act``), so even when
        composed it is never driven on the spine's per-turn ``drive_cycle``; and AD-1035 wires
        no live engine, so the organ is inert in production even when ON. Idempotent: a second
        call once the organ is composed is a no-op.
        """
        if self._spine.get_organ("dreaming") is not None:
            return  # idempotent — the dreaming organ is already composed
        _rt = getattr(self, "_runtime", None)
        _dream_cfg = getattr(getattr(_rt, "config", None), "dreaming", None) if _rt else None
        if _dream_cfg is None or not getattr(_dream_cfg, "organ_enabled", False):
            return  # default-OFF — no organ composed (shared DreamingEngine remains SoT)
        from probos.cognitive.dreaming_organ import DreamingOrgan
        self._spine.attach_organ(DreamingOrgan())

    def _active_attention_faculty(self) -> AttentionFaculty | None:
        """AD-1029: the composed :class:`AttentionFaculty`, or ``None`` when attention is OFF.

        Default-OFF ⇒ no faculty composed ⇒ returns ``None`` ⇒ ``_build_user_message`` keeps
        the exact AD-1028 inline ``ContextAssembler`` path (byte-identical). The spine is the
        single owner; the ``"attention"`` organ slot only ever holds the faculty.
        """
        _spine = getattr(self, "_spine", None)
        if _spine is None:
            return None
        return cast("AttentionFaculty | None", _spine.get_organ("attention"))

    def _emit_attention_audit(self, trace: Mapping[str, Any]) -> None:
        """AD-1029: synchronous sink for the AttentionFaculty bid-competition audit trace.

        The cognitive journal (AD-431) ``record`` is async and LLM-shaped, so it is NOT a
        clean synchronous sink for a per-turn organ trace; per the organ-audit decoupling
        (AD-1033) the trace is routed through this lightweight sync sink — a structured
        debug log of "why did the agent attend to X?" — NOT a new persistence layer. Never
        raises (log-and-degrade): audit must not break the cognitive cycle.
        """
        try:
            logger.debug(
                "AD-1029 attention audit [%s]: %s",
                getattr(self, "id", "?"),
                dict(trace),
            )
        except Exception:  # log-and-degrade: audit must never break the cycle
            logger.debug("AD-1029: attention audit sink failed", exc_info=True)

    def on_exogenous_event(
        self, event_type: str, *, severity: str | None = None, **payload: Any
    ) -> None:
        """AD-1032: the single governed boundary for an exogenous arousal event.

        The agent forwards a mesh-sourced exogenous event (an @mention, a bridge alert, a
        materially-changed scene, a safety/consensus event, urgent peer gossip) to its
        :class:`AttentionFaculty` through the spine's ``deliver_exogenous`` inlet —
        organs never reach the intent bus themselves (sovereignty / AD-397). The faculty
        maps the event to its FACULTY-LOCAL arousal zone (GREEN→AMBER→RED) and narrows the
        next turn's bid competition.

        Default-OFF (``attention.arousal_enabled`` False — and double-gated by
        ``attention.enabled``, since the faculty is only composed when attention is on) or
        no composed faculty ⇒ a safe **no-op**. This is the documented hook a future AD
        wires real emission sites to; AD-1032 wires NO live source (the router @mention,
        bridge alert, and consensus/safety emission sites live in separate subsystems and
        are a deferred follow-up).
        """
        _att = self._attention_config()
        if _att is None or not getattr(_att, "arousal_enabled", False):
            return  # default-OFF — no-op (byte-identical)
        _spine = getattr(self, "_spine", None)
        if _spine is None or self._active_attention_faculty() is None:
            return  # no faculty composed — nothing to arouse
        _spine.deliver_exogenous(
            {"event_type": event_type, "severity": severity, **payload}
        )

    async def stop(self) -> None:
        """AD-1034: detach the agent's organs at teardown, then stop.

        Organs *die with the parent* (Design Principle #12): ``detach_all`` releases
        every composed organ before the base teardown. With the default zero-organ spine
        this is a no-op, so behavior is byte-identical to ``BaseAgent.stop``.
        """
        self._reset_sensorium_budget_state()
        _spine = getattr(self, "_spine", None)
        if _spine is not None:
            _spine.detach_all()
        await super().stop()

    def set_strategy_advisor(self, advisor) -> None:
        """Attach a StrategyAdvisor for cross-agent knowledge transfer (AD-384)."""
        self._strategy_advisor = advisor

    def set_knowledge_loader(self, loader: TieredKnowledgeLoader) -> None:
        """Attach a TieredKnowledgeLoader for tiered knowledge injection (AD-585)."""
        self._knowledge_loader = loader

    def set_task_context(self, ctx: Any) -> None:
        """AD-586: Wire task context for contextual standing orders."""
        self._task_context = ctx

    def set_orientation(self, rendered: str, context: Any = None) -> None:
        """AD-567g / BF-113: Set orientation text and context (public setter for LoD)."""
        self._orientation_rendered = rendered
        self._orientation_context = context

    def set_sub_task_executor(self, executor) -> None:
        """AD-632a: Wire sub-task executor for Level 3 reasoning."""
        self._sub_task_executor = executor

    def set_consultation_protocol(self, protocol: Any) -> None:
        """AD-594: Wire consultation protocol and register as handler."""
        self._consultation_protocol = protocol
        if protocol is not None:
            protocol.register_handler(self.id, self.handle_consultation_request)

    def set_concurrency_manager(self, manager: ConcurrencyManager) -> None:
        """AD-672: Wire per-agent concurrency manager."""
        self._concurrency_manager = manager

    async def _refresh_qualification_standing(self) -> None:
        """AD-595e: Refresh cached qualification standing (TTL-based).

        Looks up standing via runtime.ontology.billet_registry. Degrades
        gracefully — sets None if unavailable.
        """
        now = time.monotonic()
        if (
            getattr(self, '_qualification_standing', None) is not None
            and now - getattr(self, '_qualification_standing_ts', 0) < getattr(self, '_qualification_standing_ttl', 300)
        ):
            return  # Cache still fresh

        try:
            rt = getattr(self, 'runtime', None)
            if not rt:
                return
            ontology = getattr(rt, 'ontology', None)
            if not ontology:
                return
            billet_reg = getattr(ontology, 'billet_registry', None)
            if not billet_reg:
                return

            self._qualification_standing = await billet_reg.get_qualification_standing(
                self.agent_type, agent_id=self.id,
            )
            self._qualification_standing_ts = now
        except Exception:
            logger.debug("AD-595e: Qualification standing refresh failed", exc_info=True)

    @property
    def working_memory(self):
        """AD-573: Agent's unified working memory — active situation model."""
        return self._working_memory

    @property
    def _cognitive_journal(self):
        """AD-431: Access journal via runtime (Ship's Computer service)."""
        if self._runtime and hasattr(self._runtime, 'cognitive_journal'):
            return self._runtime.cognitive_journal
        return None

    @property
    def _procedure_store(self):
        """AD-534: Access procedure store via runtime (Ship's Computer service)."""
        if self._runtime and hasattr(self._runtime, 'procedure_store'):
            return self._runtime.procedure_store
        return None

    async def _check_procedural_memory(self, observation: dict) -> dict | None:
        """AD-534: Check for a matching procedure before calling the LLM.

        Returns a decision dict if a procedure was replayed successfully,
        or None to fall through to the LLM path.
        """
        self._last_fallback_info = None  # AD-534b: reset for this cycle

        store = self._procedure_store
        if not store:
            return None

        # Extract query text from observation
        params = observation.get("params", {})
        query = ""
        if isinstance(params, dict):
            query = params.get("message", "") or params.get("query", "")
        if not query:
            query = observation.get("intent", "")
        if not query:
            return None

        from probos.config import (
            PROCEDURE_MATCH_THRESHOLD,
            PROCEDURE_MIN_COMPILATION_LEVEL,
        )

        # 1. Negative procedure check — warn even before positive match
        try:
            neg_matches = await store.find_matching(
                query, n_results=3, exclude_negative=False,
            )
            for nm in neg_matches:
                if nm.get("is_negative") and nm.get("score", 0) >= PROCEDURE_MATCH_THRESHOLD:
                    logger.warning(
                        "AD-534: Negative procedure match for '%s': %s (score=%.3f). "
                        "Avoiding known anti-pattern.",
                        query[:50], nm.get("name"), nm.get("score"),
                    )
                    # AD-534b: Near-miss tracking — negative veto
                    self._last_fallback_info = {
                        "type": "negative_veto",
                        "procedure_id": nm["id"],
                        "procedure_name": nm.get("name", ""),
                        "score": nm["score"],
                        "reason": "Blocked by negative procedure (anti-pattern match)",
                    }
                    # Don't return — fall through to LLM with warning logged.
                    # The LLM path will handle the task correctly.
                    return None
        except Exception:
            logger.debug("Negative procedure check failed (non-critical)", exc_info=True)

        # 2. Find matching positive procedures
        try:
            matches = await store.find_matching(
                query,
                n_results=3,
                min_compilation_level=PROCEDURE_MIN_COMPILATION_LEVEL,
                exclude_negative=True,
            )
        except Exception:
            logger.debug("Procedure store query failed (non-critical)", exc_info=True)
            return None

        if not matches:
            return None

        best = matches[0]

        # 3. Score threshold gate
        if best.get("score", 0) < PROCEDURE_MATCH_THRESHOLD:
            # AD-534b: Near-miss tracking — score below threshold
            self._last_fallback_info = {
                "type": "score_threshold",
                "procedure_id": best["id"],
                "procedure_name": best.get("name", ""),
                "score": best.get("score", 0),
                "reason": f"Score {best.get('score', 0):.2f} below threshold {PROCEDURE_MATCH_THRESHOLD}",
            }
            return None

        # 4. Quality metric gate — don't replay procedures with poor track record
        try:
            metrics = await store.get_quality_metrics(best["id"])
        except Exception:
            metrics = {}

        if metrics.get("total_selections", 0) >= 5:
            eff_rate = metrics.get("effective_rate", 1.0)
            if eff_rate < 0.3:
                logger.info(
                    "AD-534: Skipping procedure '%s' — poor effective_rate (%.2f)",
                    best.get("name"), eff_rate,
                )
                self._diagnose_procedure_health(best["id"], best.get("name", ""), metrics)
                # AD-534b: Near-miss tracking — quality gate
                self._last_fallback_info = {
                    "type": "quality_gate",
                    "procedure_id": best["id"],
                    "procedure_name": best.get("name", ""),
                    "score": best.get("score", 0),
                    "metrics": metrics,
                    "reason": f"Effective rate {eff_rate:.2f} below 0.3",
                }
                return None

        # 5. Record selection
        try:
            await store.record_selection(best["id"])
        except Exception:
            logger.debug("record_selection failed", exc_info=True)

        # 6. Load full procedure
        try:
            procedure = await store.get(best["id"])
        except Exception:
            logger.debug("Procedure load failed", exc_info=True)
            return None

        if not procedure:
            return None

        # 7. Record applied (replay attempt begins)
        try:
            await store.record_applied(best["id"])
        except Exception:
            logger.debug("record_applied failed", exc_info=True)

        # AD-535: Trust-tier clamping
        trust_score = getattr(self, "_trust_score", 0.5)
        max_level = self._max_compilation_level_for_trust(trust_score)
        # AD-537: Promoted procedures can reach Level 5 (Expert)
        if procedure.compilation_level >= 5 and self._procedure_store:
            try:
                promo_status = await self._procedure_store.get_promotion_status(procedure.id)
                max_level = self._max_compilation_level_for_promoted(trust_score, promo_status)
            except Exception:
                pass
        effective_level = min(procedure.compilation_level, max_level)

        # AD-535: Level-based dispatch
        if effective_level <= 1:
            # Level 1 (Novice): Should not reach here — find_matching() filters by
            # min_compilation_level. If it does, fall through to LLM.
            return None

        elif effective_level == 2:
            # Level 2 (Guided): LLM + procedure hints
            return await self._build_guided_decision(procedure, observation, best.get("score", 0))

        elif effective_level == 3:
            # Level 3 (Validated): Deterministic replay + LLM validation
            return await self._build_validated_decision(procedure, observation, best.get("score", 0))

        # Level 4+ (Autonomous/Expert): Zero-token replay
        # 8. Execute replay
        try:
            replay_output = self._format_procedure_replay(procedure, best.get("score", 0))

            # AD-534b: record_completion moved to handle_intent() post-execution

            # Health diagnosis (log-only, feeds future AD-532b)
            try:
                updated_metrics = await store.get_quality_metrics(best["id"])
                self._diagnose_procedure_health(best["id"], procedure.name, updated_metrics)
            except Exception:
                logger.debug("Health diagnosis failed (non-critical)", exc_info=True)

            logger.info(
                "AD-534: Procedure replay for '%s' — '%s' (score=%.3f, 0 tokens)",
                observation.get("intent", ""), procedure.name, best.get("score", 0),
            )

            # AD-534c: detect compound procedure (any step has agent_role set)
            is_compound = any(
                getattr(step, "agent_role", "") for step in procedure.steps
            )

            result_dict = {
                "action": "execute",
                "llm_output": replay_output,
                "cached": True,
                "procedure_id": procedure.id,
                "procedure_name": procedure.name,
            }
            if is_compound:
                result_dict["compound"] = True
                result_dict["procedure"] = procedure

            return result_dict

        except Exception as exc:
            # Replay failed — record near-miss info, fall through to LLM
            logger.info(
                "AD-534: Procedure replay failed for '%s' — falling back to LLM",
                procedure.name,
            )
            # AD-534b: record_fallback moved to handle_intent() post-execution
            self._last_fallback_info = {
                "type": "format_exception",
                "procedure_id": procedure.id,
                "procedure_name": procedure.name,
                "score": best.get("score", 0),
                "reason": f"Replay formatting failed: {exc}",
            }
            return None

    def _format_single_step(self, step: Any) -> str:
        """AD-534c: Format a single ProcedureStep for dispatch or local replay."""
        role = getattr(step, "agent_role", "")
        if role:
            line = f"**Step {step.step_number} [{role}]:** {step.action}"
        else:
            line = f"**Step {step.step_number}:** {step.action}"

        if getattr(step, "expected_output", ""):
            line += f"\n  \u2192 Expected: {step.expected_output}"

        return line

    def _format_procedure_replay(self, procedure: Any, match_score: float = 0.0) -> str:
        """AD-534: Format a procedure for deterministic replay output.

        The procedure's steps become the structured response,
        replacing the LLM call entirely.
        """
        lines = [
            f"[Procedure Replay: {procedure.name}]",
            f"Match score: {match_score:.3f} | Steps: {len(procedure.steps)}",
            "",
        ]
        if procedure.description:
            lines.append(procedure.description)
            lines.append("")

        for step in procedure.steps:
            lines.append(self._format_single_step(step))
            if getattr(step, "fallback_action", ""):
                lines.append(f"  \u26a0 Fallback: {step.fallback_action}")

        if procedure.postconditions:
            lines.append("")
            lines.append("**Postconditions:**")
            for pc in procedure.postconditions:
                lines.append(f"  - {pc}")

        return "\n".join(lines)

    def _resolve_step_agent(self, step: Any) -> str | None:
        """AD-534c: Resolve a ProcedureStep to a live agent ID.

        Three-stage resolution:
          1. resolved_agent_type → registry.get_by_pool() → first live agent
          2. agent_role → registry.get_by_capability() → first live agent
          3. Return None if both fail

        Skips self (orchestrating agent). Returns the agent_id or None.
        """
        _rt = getattr(self, '_runtime', None)
        if not _rt or not hasattr(_rt, 'registry'):
            return None

        registry = _rt.registry

        # Stage 1: resolved_agent_type → get_by_pool
        resolved_type = getattr(step, "resolved_agent_type", "")
        if resolved_type:
            try:
                pool_agents = registry.get_by_pool(resolved_type)
                for agent in pool_agents:
                    if agent.id != self.id and getattr(agent, 'is_alive', False):
                        return agent.id
            except Exception:
                logger.debug("AD-534c: get_by_pool('%s') failed", resolved_type, exc_info=True)

        # Stage 2: agent_role → get_by_capability
        role = getattr(step, "agent_role", "")
        if role:
            try:
                cap_agents = registry.get_by_capability(role)
                for agent in cap_agents:
                    if agent.id != self.id and getattr(agent, 'is_alive', False):
                        return agent.id
            except Exception:
                logger.debug("AD-534c: get_by_capability('%s') failed", role, exc_info=True)

        # Stage 3: no match
        return None

    async def _execute_compound_replay(
        self, procedure: Any, text_fallback: str, compilation_level: int = 4
    ) -> dict:
        """AD-534c: Dispatch compound procedure steps to appropriate agents.

        Resolves each step's agent_role to a live agent. Dispatches steps
        sequentially via IntentBus.send() with 'compound_step_replay' intent.
        Target agents receive pre-formatted step text and return it (zero tokens).

        Degrades to single-agent text replay if any required agent is unavailable
        or if IntentBus/registry are not available.
        """
        from probos.config import COMPOUND_STEP_TIMEOUT_SECONDS

        _rt = getattr(self, '_runtime', None)
        if not _rt or not hasattr(_rt, 'intent_bus') or not hasattr(_rt, 'registry'):
            logger.debug("AD-534c: IntentBus or registry unavailable, degrading to text replay")
            return {"success": True, "result": text_fallback, "compound_dispatched": False, "steps_dispatched": 0}

        intent_bus = _rt.intent_bus

        # Build dispatch plan: list of (step, target_agent_id or None)
        dispatch_plan: list[tuple[Any, str | None]] = []
        for step in procedure.steps:
            role = getattr(step, "agent_role", "")
            if not role:
                # No role assigned — local step
                dispatch_plan.append((step, None))
                continue

            agent_id = self._resolve_step_agent(step)
            if agent_id is None:
                # Can't resolve — degrade to single-agent text replay
                logger.warning(
                    "AD-534c: Cannot resolve agent for role '%s' in procedure '%s'. "
                    "Degrading to single-agent replay.",
                    role, procedure.name,
                )
                self._last_fallback_info = {
                    "type": "compound_agent_unavailable",
                    "procedure_id": procedure.id,
                    "procedure_name": procedure.name,
                    "reason": f"No agent available for role '{role}'",
                }
                return {"success": True, "result": text_fallback, "compound_dispatched": False, "steps_dispatched": 0}

            dispatch_plan.append((step, agent_id))

        # Dispatch loop
        results: list[str] = []
        for step, target_agent_id in dispatch_plan:
            step_text = self._format_single_step(step)

            if target_agent_id is None:
                # Local step — no dispatch needed
                results.append(step_text)
                continue

            # Dispatch via IntentBus
            intent = IntentMessage(
                intent="compound_step_replay",
                params={
                    "step_text": step_text,
                    "procedure_id": procedure.id,
                    "step_number": step.step_number,
                },
                target_agent_id=target_agent_id,
                ttl_seconds=COMPOUND_STEP_TIMEOUT_SECONDS,
            )

            try:
                intent_result = await intent_bus.send(intent)
                if intent_result and intent_result.success:
                    step_result_text = intent_result.result or step_text
                    results.append(step_result_text)
                else:
                    logger.warning(
                        "AD-534c: Step %d dispatch to '%s' failed. Using text fallback.",
                        step.step_number, target_agent_id,
                    )
                    step_result_text = step_text
                    results.append(step_text)
            except Exception:
                logger.debug("AD-534c: Step %d dispatch exception", step.step_number, exc_info=True)
                step_result_text = step_text
                results.append(step_text)

            # AD-535: Level 3 per-step postcondition validation
            if compilation_level == 3 and step.expected_output:
                step_valid = await self._validate_step_postcondition(
                    step, step_result_text
                )
                if not step_valid:
                    logger.info(
                        "Compound step %d validation failed — aborting compound replay",
                        step.step_number,
                    )
                    return {"success": True, "result": text_fallback, "compound_dispatched": False, "compound_aborted": True}

        assembled = "\n\n".join(results)
        return {
            "success": True,
            "result": assembled,
            "compound_dispatched": True,
            "steps_dispatched": sum(1 for _, tid in dispatch_plan if tid is not None),
        }

    async def _handle_compound_step_replay(self, intent: IntentMessage) -> IntentResult:
        """AD-534c: Handle a dispatched compound procedure step.

        Zero-token operation — receives pre-formatted step text and returns it.
        No LLM invocation.
        """
        step_text = intent.params.get("step_text", "")
        procedure_id = intent.params.get("procedure_id", "")
        step_number = intent.params.get("step_number", 0)

        logger.debug(
            "AD-534c: Agent %s received compound step %d from procedure %s",
            self.id, step_number, procedure_id,
        )

        return IntentResult(
            intent_id=intent.id,
            agent_id=self.id,
            success=True,
            result=step_text,
            confidence=1.0,
        )

    async def _handle_work_item_dispatch(self, intent: IntentMessage) -> IntentResult:
        """AD-839: Surface a directly-dispatched work item to this agent.

        When the AD-581a WorkItemRouter direct-assigns a dispatchable work
        item to this agent ("dispatch to agent now"), deliver it as a
        Captain-originated task message in the agent's DM thread, let the
        agent acknowledge it via the normal direct-message lifecycle, and
        transition the work item to ``in_progress`` so the dispatch actually
        starts the work and the agent is aware of it.

        Tier-2 log-and-degrade: failures here must never raise into the
        cognitive queue. On failure the work item stays ``open`` and the
        agent simply produces no acknowledgment.
        """
        params = intent.params or {}
        work_item_id = params.get("work_item_id", "")
        title = (params.get("title") or "").strip()
        description = (params.get("description") or "").strip()

        task_lines = [f"You've been assigned a new task: {title or '(untitled)'}"]
        if description:
            task_lines.append("")
            task_lines.append(description)
        task_lines.append("")
        task_lines.append(
            "Acknowledge this assignment and briefly describe how you'll approach it."
        )
        task_text = "\n".join(task_lines)

        runtime = self._runtime
        thread = None
        thread_store = getattr(runtime, "chat_thread_store", None) if runtime else None
        if thread_store is not None:
            try:
                _title = getattr(self, "callsign", "") or self.agent_type
                thread = thread_store.get_or_create_default_for_agent(self.id, _title)
                thread_store.append_message(
                    thread.id,
                    author_id="captain",
                    role="captain",
                    body=task_text,
                    metadata={
                        "work_item_id": work_item_id,
                        "source": "work_item_dispatch",
                    },
                )
            except Exception:
                logger.warning(
                    "AD-839: failed to log captain task message for work_item "
                    "%s to agent %s; continuing without thread wiring",
                    work_item_id, self.id, exc_info=True,
                )
                thread = None

        # Run the assignment through the normal direct-message lifecycle so the
        # agent reasons about it and produces an acknowledgment.
        dm = IntentMessage(
            intent="direct_message",
            params={"text": task_text, "from": "captain", "session": False},
            context="",
            target_agent_id=self.id,
            ttl_seconds=120.0,
            thread_id=thread.id if thread is not None else None,
        )

        # AD-856: when the multi-turn agentic dispatch path is enabled and its
        # dependencies are wired, execute the work item through the AgenticLoop
        # so the agent can call tools across iterations. Otherwise fall back to
        # the single-shot direct-message lifecycle (AD-839 behaviour).
        reply_text = await self._run_agentic_dispatch(
            work_item_id=work_item_id,
            task_text=task_text,
            runtime=runtime,
        )
        if reply_text is None:
            result = await self.handle_intent(dm)
            reply_text = ""
            if result is not None and getattr(result, "result", None):
                reply_text = str(result.result)

        if thread is not None and thread_store is not None and reply_text:
            try:
                thread_store.append_message(
                    thread.id,
                    author_id=self.id,
                    role="agent",
                    body=reply_text,
                    metadata={"intent_id": intent.id, "work_item_id": work_item_id},
                )
            except Exception:
                logger.warning(
                    "AD-839: failed to log agent acknowledgment for work_item "
                    "%s; continuing",
                    work_item_id, exc_info=True,
                )

        store = getattr(runtime, "work_item_store", None) if runtime else None
        if store is not None and work_item_id:
            # BF-607: This agent is actively working a directly-dispatched item,
            # but the AD-581a WorkItemRouter only emits the dispatch event — it
            # never persists the assignment. Without claiming it here the board
            # shows the item ``in_progress`` with "Unassigned" (observed for the
            # yeo-delegated task), because ``assigned_to`` was never written.
            # Claim it for this agent if (and only if) it is currently
            # unassigned, so the displayed assignee reflects who is actually
            # doing the work; an item the Captain or crew orchestrator already
            # assigned is left untouched. Tier-2 log-and-degrade.
            try:
                current = await store.get_work_item(work_item_id)
                if current is not None and not current.assigned_to:
                    await store.update_work_item(work_item_id, assigned_to=self.id)
            except Exception:
                logger.warning(
                    "BF-607: failed to claim work_item %s for agent %s; "
                    "it remains unassigned",
                    work_item_id, self.id, exc_info=True,
                )
            try:
                await store.transition_work_item(
                    work_item_id, "in_progress", source=self.id,
                )
            except Exception:
                logger.warning(
                    "AD-839: failed to transition work_item %s to in_progress; "
                    "it remains in its prior status",
                    work_item_id, exc_info=True,
                )

        return IntentResult(
            intent_id=intent.id,
            agent_id=self.id,
            success=True,
            result=reply_text or "[NO_RESPONSE]",
            confidence=self.confidence,
        )

    async def _run_agentic_dispatch(
        self,
        *,
        work_item_id: str,
        task_text: str,
        runtime: Any,
    ) -> str | None:
        """AD-856: Execute a dispatched work item via the AgenticLoop.

        Returns the loop's final text when the agentic path runs, or ``None``
        to signal the caller to fall back to the single-shot direct-message
        lifecycle. The path runs only when ``config.agentic_dispatch.enabled``
        is set and the LLM client, tool permission store, capability-gap driver
        and tool registry are all wired.

        Permission denials raised inside the loop are captured by
        ``DispatchToolExecutor`` and surfaced to the AD-855 capability-gap
        driver after the loop finishes, so a missing tool becomes a tracked
        capability request rather than a silent dead end.
        """
        if runtime is None:
            return None
        config = getattr(runtime, "config", None)
        ad_cfg = getattr(config, "agentic_dispatch", None) if config else None
        if not (ad_cfg is not None and getattr(ad_cfg, "enabled", False)):
            return None

        llm = self._llm_client
        perm_store = getattr(runtime, "tool_permission_store", None)
        gap_driver = getattr(runtime, "capability_gap_driver", None)
        registry = getattr(runtime, "tool_registry", None)
        if llm is None or perm_store is None or gap_driver is None or registry is None:
            return None

        from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor

        executor = WorkItemAgenticExecutor(llm_client=llm)
        outcome = await executor.run(
            agent_id=self.id,
            instructions=getattr(self, "instructions", "") or "",
            task_text=task_text,
            runtime=runtime,
        )

        for denied_tool in outcome.denied_tools:
            try:
                await gap_driver.on_capability_gap(
                    work_item_id=work_item_id,
                    gap_target=denied_tool,
                    agent_id=self.id,
                )
            except Exception:
                logger.warning(
                    "AD-856: failed to surface capability gap for denied tool "
                    "%s on work_item %s; continuing",
                    denied_tool, work_item_id, exc_info=True,
                )

        return outcome.final_text or ""

    async def _build_guided_decision(
        self, procedure: Any, observation: dict, match_score: float
    ) -> dict:
        """AD-535 Level 2 (Guided): Call LLM with procedure steps injected as hints.

        The LLM reasons freely but has the learned procedure as scaffolding.
        ~40% token reduction vs full reasoning from scratch.
        """
        hints = self._format_procedure_as_hints(procedure)

        guided_observation = dict(observation)
        guided_observation["procedure_hints"] = hints
        guided_observation["procedure_guidance"] = (
            f"A learned procedure '{procedure.name}' suggests the following approach. "
            f"Use these steps as guidance but apply your own judgment:\n\n{hints}"
        )

        decision = await self._decide_via_llm(guided_observation)

        decision["guided_by_procedure"] = True
        decision["procedure_id"] = procedure.id
        decision["procedure_name"] = procedure.name
        decision["compilation_level"] = 2
        return decision

    def _format_procedure_as_hints(self, procedure: Any) -> str:
        """AD-535: Format procedure steps as guidance hints for Level 2 (Guided) replay.

        Differs from _format_procedure_replay() — framed as suggestions, not directives.
        Includes expected_input/output for each step as orientation.
        """
        lines = [f"Suggested approach based on prior success ('{procedure.name}'):"]
        for step in procedure.steps:
            line = f"  {step.step_number}. {step.action}"
            if step.expected_input:
                line += f"\n     Context: {step.expected_input}"
            if step.expected_output:
                line += f"\n     Expected result: {step.expected_output}"
            role = getattr(step, "agent_role", "")
            if role:
                line += f"\n     (Typically performed by: {role})"
            lines.append(line)
        if procedure.postconditions:
            lines.append(f"\nSuccess criteria: {procedure.postconditions}")
        return "\n".join(lines)

    async def _build_validated_decision(
        self, procedure: Any, observation: dict, match_score: float
    ) -> dict | None:
        """AD-535 Level 3 (Validated): Deterministic replay + LLM postcondition validation.

        Execute procedure deterministically (same as Level 4), then call LLM
        to validate the result against expected outcomes. ~80% token reduction.
        If validation fails, return None to trigger LLM fallback.
        """
        replay_output = self._format_procedure_replay(procedure, match_score)

        validation_passed = await self._validate_replay_postconditions(
            procedure, replay_output, observation
        )

        if not validation_passed:
            self._last_fallback_info = {
                "type": "validation_failure",
                "procedure_id": procedure.id,
                "procedure_name": procedure.name,
                "score": match_score,
                "compilation_level": 3,
            }
            logger.info(
                "Level 3 validation failed for procedure %s — falling back to LLM",
                procedure.name,
            )
            return None

        is_compound = any(
            getattr(step, "resolved_agent_type", "") for step in procedure.steps
        ) and len(procedure.steps) >= 2

        decision = {
            "action": "execute",
            "llm_output": replay_output,
            "cached": True,
            "procedure_id": procedure.id,
            "procedure_name": procedure.name,
            "compilation_level": 3,
            "validated": True,
        }
        if is_compound:
            decision["compound"] = True
            decision["procedure"] = procedure

        return decision

    async def _validate_replay_postconditions(
        self, procedure: Any, replay_output: str, observation: dict
    ) -> bool:
        """AD-535: Validate deterministic replay output against procedure postconditions.

        Uses a small LLM call to check whether the output satisfies expected outcomes.
        Returns True if validation passes, False otherwise.
        """
        import asyncio

        from probos.config import COMPILATION_VALIDATION_TIMEOUT_SECONDS

        validation_context = []

        if procedure.postconditions:
            if isinstance(procedure.postconditions, list):
                for pc in procedure.postconditions:
                    validation_context.append(f"Expected postcondition: {pc}")
            else:
                validation_context.append(f"Expected postconditions: {procedure.postconditions}")

        for step in procedure.steps:
            if step.expected_output:
                validation_context.append(
                    f"Step {step.step_number} expected output: {step.expected_output}"
                )
            if step.invariants:
                for inv in step.invariants:
                    validation_context.append(f"Step {step.step_number} invariant: {inv}")

        if not validation_context:
            return True

        validation_prompt = (
            "You are a postcondition validator. Given the following procedure replay output "
            "and expected outcomes, determine if the output satisfies the expectations.\n\n"
            f"Procedure: {procedure.name}\n"
            f"Replay output:\n{replay_output[:2000]}\n\n"
            f"Expected outcomes:\n" + "\n".join(validation_context) + "\n\n"
            "Does the output satisfy the expected outcomes? "
            "Answer ONLY 'YES' or 'NO' followed by a brief reason."
        )

        try:
            llm_client = getattr(self, "_llm_client", None)
            if not llm_client:
                return True

            response = await asyncio.wait_for(
                llm_client.generate(validation_prompt, max_tokens=100),
                timeout=COMPILATION_VALIDATION_TIMEOUT_SECONDS,
            )

            answer = response.strip().upper()
            return answer.startswith("YES")

        except (asyncio.TimeoutError, Exception) as exc:
            logger.warning(
                "Level 3 validation call failed for procedure %s: %s — passing by default",
                procedure.name, exc,
            )
            return True

    async def _validate_step_postcondition(
        self, step: Any, actual_output: str
    ) -> bool:
        """AD-535: Validate a single step's output against its expected_output.

        Small LLM call. Used at Level 3 during compound replay.
        """
        import asyncio

        from probos.config import COMPILATION_VALIDATION_TIMEOUT_SECONDS

        if not step.expected_output:
            return True

        prompt = (
            f"Step {step.step_number}: {step.action}\n"
            f"Actual output: {actual_output[:1000]}\n"
            f"Expected output: {step.expected_output}\n\n"
            "Does the actual output satisfy the expected output? YES or NO."
        )

        try:
            llm_client = getattr(self, "_llm_client", None)
            if not llm_client:
                return True
            response = await asyncio.wait_for(
                llm_client.generate(prompt, max_tokens=50),
                timeout=COMPILATION_VALIDATION_TIMEOUT_SECONDS,
            )
            return response.strip().upper().startswith("YES")
        except Exception:
            return True  # Fail-open

    def _diagnose_procedure_health(
        self, procedure_id: str, procedure_name: str, metrics: dict
    ) -> None:
        """AD-534: Metric-based health diagnosis (OpenSpace absorbed pattern).

        Uses shared diagnosis function from procedures.py. Logs diagnosis for
        AD-532b FIX/DERIVED evolution. No action taken here.
        """
        from probos.cognitive.procedures import diagnose_procedure_health
        from probos.config import PROCEDURE_MIN_SELECTIONS

        diagnosis = diagnose_procedure_health(metrics, min_selections=PROCEDURE_MIN_SELECTIONS)
        if diagnosis:
            logger.warning(
                "AD-534: Procedure health diagnosis for '%s' (%s): %s "
                "(selections=%d, fallback=%.2f, applied=%.2f, completion=%.2f, effective=%.2f)",
                procedure_name, procedure_id[:8], diagnosis,
                metrics.get("total_selections", 0),
                metrics.get("fallback_rate", 0.0),
                metrics.get("applied_rate", 0.0),
                metrics.get("completion_rate", 0.0),
                metrics.get("effective_rate", 0.0),
            )

    def _max_compilation_level_for_trust(self, trust_score: float) -> int:
        """AD-535: Return the maximum compilation level allowed for the given trust score.

        Ensign (trust < 0.5): Levels 1-2 (Novice, Guided)
        Lieutenant (trust 0.5+): Levels 1-4 (full range)
        AD-536: Promoted procedures can reach Level 5 (Expert) at Commander+ trust.
        """
        from probos.config import (
            COMPILATION_TRUST_LEVEL_3_MIN,
            COMPILATION_MAX_LEVEL,
        )
        if trust_score < COMPILATION_TRUST_LEVEL_3_MIN:
            return 2  # Ensign: max Level 2 (Guided)
        return min(4, COMPILATION_MAX_LEVEL)  # Lieutenant+: max Level 4

    def _max_compilation_level_for_promoted(self, trust_score: float, promotion_status: str) -> int:
        """AD-536: Level 5 unlock for promoted procedures with Commander+ trust."""
        from probos.config import TRUST_COMMANDER
        base = self._max_compilation_level_for_trust(trust_score)
        if promotion_status == "approved" and trust_score >= TRUST_COMMANDER:
            return 5  # Expert level unlocked for promoted procedures
        return base

    # ------------------------------------------------------------------
    # AD-536: Procedure Promotion Helpers
    # ------------------------------------------------------------------

    _DEPARTMENT_CHIEFS: dict[str, str] = {
        "engineering": "laforge",
        "medical": "bones",
        "science": "number_one",  # dual-hatted
        "security": "worf",
        "operations": "obrien",
        "bridge": "captain",  # Bridge procedures always go to Captain
    }

    async def _request_procedure_promotion(self, procedure_id: str) -> dict | None:
        """AD-536: Request institutional promotion for a proven procedure."""
        _store = self._procedure_store
        if not _store:
            return None
        try:
            result = await _store.request_promotion(procedure_id)
            if result.get("eligible"):
                await self._announce_promotion_request(procedure_id, result)
                return result
            else:
                logger.debug(
                    "AD-536: Procedure %s not eligible for promotion: %s",
                    procedure_id, result.get("reason"),
                )
        except Exception as e:
            logger.debug("AD-536: Promotion request failed: %s", e)
        return None

    def _route_promotion_approval(self, criticality: str) -> str:
        """AD-536: Determine approver callsign based on criticality."""
        from probos.config import PROMOTION_CRITICALITY_CAPTAIN_THRESHOLD

        captain_levels = {"high", "critical"}
        if PROMOTION_CRITICALITY_CAPTAIN_THRESHOLD == "high":
            captain_levels = {"high", "critical"}
        elif PROMOTION_CRITICALITY_CAPTAIN_THRESHOLD == "critical":
            captain_levels = {"critical"}

        if criticality in captain_levels:
            return "captain"

        # LOW/MEDIUM → department chief
        agent_type = getattr(self, "agent_type", "")
        _rt = getattr(self, "_runtime", None)
        department = ""
        if _rt and hasattr(_rt, "ontology") and _rt.ontology:
            department = _rt.ontology.get_agent_department(agent_type) or ""
        return self._DEPARTMENT_CHIEFS.get(department, "captain")

    async def _announce_promotion_request(
        self, procedure_id: str, promotion_result: dict
    ) -> None:
        """AD-536: Post promotion request to Ward Room and DM the approver."""
        _rt = getattr(self, "_runtime", None)
        if not _rt or not hasattr(_rt, "ward_room") or not _rt.ward_room:
            return

        criticality = promotion_result.get("criticality", "low")
        approver = self._route_promotion_approval(criticality)
        quality = promotion_result.get("quality_metrics", {})
        proc_name = promotion_result.get("procedure_name", procedure_id[:8])
        intent_types = promotion_result.get("intent_types", [])

        body = (
            f"**Procedure Promotion Request**\n\n"
            f"**Procedure:** {proc_name}\n"
            f"**Intent Types:** {', '.join(intent_types) if intent_types else 'general'}\n"
            f"**Description:** {promotion_result.get('procedure_description', 'N/A')}\n"
            f"**Compilation Level:** {promotion_result.get('compilation_level', 0)}\n"
            f"**Quality:** {quality.get('effective_rate', 0):.0%} effective over "
            f"{quality.get('total_completions', 0)} completions\n"
            f"**Criticality:** {criticality}\n"
            f"**Recommended Approver:** @{approver}\n\n"
            f"Use `procedure approve {procedure_id}` to approve."
        )

        try:
            agent_type = getattr(self, "agent_type", "")
            agent_id = getattr(self, "_agent_id", agent_type)
            callsign = getattr(self, "_callsign", agent_type)

            # Post to appropriate channel
            department = ""
            if _rt.ontology:
                department = _rt.ontology.get_agent_department(agent_type) or ""

            channels = await _rt.ward_room.list_channels()
            target_channel = None
            # Critical → Bridge/All Hands, routine → department channel
            chan_name = "All Hands" if criticality in ("high", "critical") else (department or "All Hands")
            for ch in channels:
                if ch.name == chan_name:
                    target_channel = ch
                    break
            if not target_channel and channels:
                target_channel = channels[0]

            if target_channel:
                await _rt.ward_room.create_thread(
                    channel_id=target_channel.id,
                    author_id=agent_id,
                    title=f"[Promotion Request] {proc_name}",
                    body=body,
                    author_callsign=callsign,
                )

            # DM the approver
            approver_id = approver
            dm_body = (
                f"Procedure promotion request requires your review: {proc_name}. "
                f"Quality: {quality.get('effective_rate', 0):.0%} effective over "
                f"{quality.get('total_completions', 0)} completions. "
                f"Criticality: {criticality}. Use `procedure approve {procedure_id}` to approve."
            )
            try:
                dm_channel = await _rt.ward_room.get_or_create_dm_channel(
                    agent_id, approver_id,
                    callsign_a=callsign, callsign_b=approver,
                )
                await _rt.ward_room.create_thread(
                    channel_id=dm_channel.id,
                    author_id=agent_id,
                    title=f"Promotion Review: {proc_name}",
                    body=dm_body,
                    author_callsign=callsign,
                )
            except Exception:
                logger.debug("AD-536: Failed to DM approver %s", approver)

        except Exception as e:
            logger.debug("AD-536: Ward Room announcement failed: %s", e)

    # ------------------------------------------------------------------
    # AD-537: Teaching Protocol
    # ------------------------------------------------------------------

    async def _teach_procedure(
        self,
        procedure_id: str,
        target_callsign: str,
    ) -> bool:
        """AD-537: Teach a Level 5 Expert procedure to another agent via Ward Room DM.

        Preconditions: Level 5, approved, Commander+ trust, target exists.
        Returns True on success.
        """
        from probos.config import TEACHING_MIN_COMPILATION_LEVEL, TEACHING_MIN_TRUST

        _store = self._procedure_store
        if not _store:
            logger.debug("AD-537: No procedure store available for teaching")
            return False

        # 1. Procedure exists
        procedure = await _store.get(procedure_id)
        if not procedure:
            logger.debug("AD-537: Procedure %s not found", procedure_id)
            return False

        # 2. Must be Level 5 Expert
        if procedure.compilation_level < TEACHING_MIN_COMPILATION_LEVEL:
            logger.debug(
                "AD-537: Procedure %s at level %d, need %d to teach",
                procedure_id[:8], procedure.compilation_level,
                TEACHING_MIN_COMPILATION_LEVEL,
            )
            return False

        # 3. Must be institutionally approved
        promotion_status = await _store.get_promotion_status(procedure_id)
        if promotion_status != "approved":
            logger.debug("AD-537: Procedure %s not approved (status: %s)", procedure_id[:8], promotion_status)
            return False

        # 4. Agent trust must be Commander+
        _rt = getattr(self, "_runtime", None)
        agent_type = getattr(self, "agent_type", "")
        trust_score = 0.5
        if _rt and hasattr(_rt, "trust_network") and _rt.trust_network:
            # BF-263: Use self.id, not agent_type — TrustNetwork keyed by agent_id
            trust_score = _rt.trust_network.get_score(self.id)
        if trust_score < TEACHING_MIN_TRUST:
            logger.debug("AD-537: Trust %.2f below teaching threshold %.2f", trust_score, TEACHING_MIN_TRUST)
            return False

        # 5. Ward Room available
        if not _rt or not hasattr(_rt, "ward_room") or not _rt.ward_room:
            logger.debug("AD-537: Ward Room not available for teaching")
            return False

        # 6. Format teaching message
        quality = await _store.get_quality_metrics(procedure_id)
        total_comp = quality.get("total_completions", 0) if quality else 0
        effective_rate = quality.get("effective_rate", 0) if quality else 0
        steps_text = "\n".join(f"  {s.step_number}. {s.action}" for s in procedure.steps)
        preconditions_text = "\n".join(f"  - {p}" for p in procedure.preconditions) if procedure.preconditions else "  (none)"
        postconditions_text = "\n".join(f"  - {p}" for p in procedure.postconditions) if procedure.postconditions else "  (none)"

        callsign = getattr(self, "_callsign", agent_type)
        agent_id = getattr(self, "_agent_id", agent_type)

        body = (
            f"**[TEACHING] Procedure: {procedure.name}**\n\n"
            f"I'm teaching you this procedure because I've validated it through "
            f"{total_comp} successful executions with {effective_rate:.0%} success rate.\n\n"
            f"**Description:** {procedure.description}\n\n"
            f"**Steps:**\n{steps_text}\n\n"
            f"**Preconditions:**\n{preconditions_text}\n\n"
            f"**Postconditions:**\n{postconditions_text}\n\n"
            f"This procedure has been institutionally approved and promoted to Expert level."
        )

        # 7. Send DM
        try:
            dm_channel = await _rt.ward_room.get_or_create_dm_channel(
                agent_id, target_callsign,
                callsign_a=callsign, callsign_b=target_callsign,
            )
            await _rt.ward_room.create_thread(
                channel_id=dm_channel.id,
                author_id=agent_id,
                title=f"[TEACHING] {procedure.name}",
                body=body,
                author_callsign=callsign,
            )
            logger.info(
                "AD-537: Taught procedure '%s' to %s",
                procedure.name, target_callsign,
            )
            return True
        except Exception as e:
            logger.debug("AD-537: Teaching DM failed: %s", e)
            return False

    async def perceive(self, intent: Any) -> dict:
        """Package the intent as an observation for the LLM.

        AD-492: Generates a correlation_id at perception time to thread
        through the entire cognitive cycle (decide → act → episode → post).
        """
        # AD-492: Generate correlation ID for this cognitive cycle
        correlation_id = uuid.uuid4().hex[:12]
        self._current_correlation_id = correlation_id

        if isinstance(intent, IntentMessage):
            observation = {
                "intent": intent.intent,
                "params": intent.params,
                "context": intent.context,
                "intent_id": intent.id,  # AD-432: Preserve for journal traceability
                "correlation_id": correlation_id,  # AD-492
                # AD-809: chat-thread provenance — the receiving agent's
                # decide() reads this to resolve the per-thread
                # personality overlay (if any) and append it to the
                # built system prompt. AD-791a populates thread_id on
                # every chat dispatch.
                "thread_id": getattr(intent, "thread_id", None),
            }
        else:
            # Dict fallback (for compatibility with BaseAgent contract).
            #
            # BF-698: this branch used to drop ``intent_id`` and ``thread_id``
            # unconditionally. Roughly fifteen agents reach it by calling
            # ``self.perceive(intent.__dict__)`` — converting the IntentMessage
            # to a dict defeats the ``isinstance`` check above — so every one of
            # them silently lost chat-thread provenance. Downstream that is not
            # cosmetic: AD-809 resolves the per-thread personality overlay from
            # ``observation["thread_id"]``, AD-1066 binds produced artifacts to
            # the thread with it, and AD-1165 needs it to promote a long turn to
            # a task. All three degrade to a no-op against an absent key rather
            # than failing loudly, which is why it went unnoticed.
            #
            # The keys are added ONLY when the source dict actually carries
            # them. ``IntentMessage`` is a dataclass, so ``__dict__`` has ``id``
            # and ``thread_id`` and the fifteen callers above are fixed; a
            # hand-built dict has neither and is untouched, which preserves the
            # deliberate AD-432 contract that the fallback does not invent an
            # ``intent_id`` it was never given (test_cognitive_journal.py
            # ``TestPerceiveIntentId``). Absent and None are indistinguishable
            # to every real consumer, since they all read through ``.get()``.
            _as_dict = intent if isinstance(intent, dict) else {}
            observation = {
                "intent": _as_dict.get("intent", "unknown"),
                "params": _as_dict.get("params", {}),
                "context": _as_dict.get("context", ""),
                "correlation_id": correlation_id,  # AD-492
            }
            if "id" in _as_dict:  # BF-698
                observation["intent_id"] = _as_dict["id"]
            if "thread_id" in _as_dict:  # BF-698
                observation["thread_id"] = _as_dict["thread_id"]

        # AD-492: Store correlation_id on working memory for cross-reference
        _wm = getattr(self, '_working_memory', None)
        if _wm:
            _wm.set_correlation_id(correlation_id)

        # AD-1036: exogenous arousal — a between-turns @mention raises this agent's
        # AttentionFaculty faculty-local zone for the next turn (severity table:
        # mention→AMBER, AD-1032). Layer-safe: the agent self-arouses from its OWN
        # universal intake — no lower layer (router/bridge/consensus) reaches in.
        # Double-gated default-OFF: on_exogenous_event no-ops unless attention.enabled
        # ∧ arousal_enabled, so this is byte-identical when arousal is off (the default).
        if observation.get("params", {}).get("was_mentioned", False):
            self.on_exogenous_event("mention")

        return observation

    def _compose_dm_instructions(self, brief: bool = False) -> str:
        """Build DM instruction block with department-grouped roster (BF-051/052)."""
        _rt = getattr(self, '_runtime', None)
        if not _rt:
            return ""

        # Build department-grouped roster
        _dm_crew_list = ""
        if hasattr(_rt, 'callsign_registry') and hasattr(_rt, 'ontology') and _rt.ontology:
            try:
                _all_cs = _rt.callsign_registry.all_callsigns()
                _self_atype = getattr(self, 'agent_type', '')
                dept_groups: dict[str, list[str]] = {}
                for atype, cs in _all_cs.items():
                    if atype == _self_atype or not cs:
                        continue
                    dept_id = _rt.ontology.get_agent_department(atype)
                    dept_name = (dept_id or "bridge").capitalize()
                    dept_groups.setdefault(dept_name, []).append(f"@{cs}")
                if dept_groups:
                    parts = []
                    for dn in sorted(dept_groups):
                        members = ", ".join(sorted(dept_groups[dn]))
                        parts.append(f"{dn}: {members}")
                    _dm_crew_list = "Available crew to DM:\n" + "\n".join(parts) + "\n"
            except Exception:
                logger.debug("Cognitive agent context failed", exc_info=True)
                try:
                    _all_cs = _rt.callsign_registry.all_callsigns()
                    _self_atype = getattr(self, 'agent_type', '')
                    _crew_entries = [f"@{cs}" for atype, cs in _all_cs.items()
                                     if atype != _self_atype and cs]
                    if _crew_entries:
                        _dm_crew_list = f"Available crew to DM: {', '.join(sorted(_crew_entries))}\n"
                except Exception:
                    logger.debug("Crew list building failed", exc_info=True)
        elif hasattr(_rt, 'callsign_registry'):
            try:
                _all_cs = _rt.callsign_registry.all_callsigns()
                _self_atype = getattr(self, 'agent_type', '')
                _crew_entries = [f"@{cs}" for atype, cs in _all_cs.items()
                                 if atype != _self_atype and cs]
                if _crew_entries:
                    _dm_crew_list = f"Available crew to DM: {', '.join(sorted(_crew_entries))}\n"
            except Exception:
                logger.debug("Crew list building failed", exc_info=True)

        if brief:
            return (
                "\n\nYou may also send a private message to a crew member:\n"
                "[DM @callsign]\nYour message (2-3 sentences).\n[/DM]\n"
                f"{_dm_crew_list}"
                "ONLY DM crew listed above. You may DM @captain for urgent matters.\n"
            )

        return (
            "**Direct message a crew member** — reach out privately to another agent:\n"
            "[DM @callsign]\n"
            "Your message to this crew member (2-3 sentences).\n"
            "[/DM]\n"
            f"{_dm_crew_list}"
            "Use for: consulting a specialist, coordinating on a shared concern, "
            "asking for input on something in your department. "
            "ONLY DM crew members listed above. Do NOT invent crew members who don't exist. "
            "You may DM @captain for urgent matters that need the Captain's direct attention. "
            "Use sparingly — routine reports belong in your observation post.\n\n"
        )

    def _conversational_capability_block(self, observation: dict) -> str:
        """AD-983a: ground every crew agent in the ship's *live, reachable*
        mesh capabilities and how to invoke them — the capability carries its
        own manual.

        Generalizes the BF-599/AD-870 Yeo-only grounding to the whole crew: it
        renders the ``usage_hint`` of each capability that (a) declares one and
        (b) is served by a live agent right now (``capability_affordances``).
        So any crew agent — not just the Yeoman — is told it can fetch a web
        search / read a page / list a directory / read a file this turn via the
        AD-869 ``[MESH ...]`` do-and-report seam, instead of confabulating a
        limitation (BF-599 / AD-957). The affordance travels WITH the capability
        and surfaces to whoever can reach it (the Copilot tool-schema model),
        rather than being authored into one agent's behavior rules.

        Substrate-gated by construction (the AD-912 notebook discipline): a
        capability whose serving pool is down contributes no live agent, so its
        hint is simply absent — an agent is never told to use something the ship
        cannot back (AD-592). Returns "" when nothing is reachable. Overridable
        (Open/Closed); gap-regex-safe (no can't/cannot/don't have/unable/lack).
        """
        affordances = self.capability_affordances()
        if not affordances:
            return ""
        # Deterministic order (sorted by intent name) so the prompt + tests are
        # reproducible regardless of registry iteration order.
        rendered = ", ".join(hint for _name, hint in sorted(affordances.items()))
        return (
            "\n\nShip capabilities you can use right now — put the tag anywhere "
            "in your reply and the result is fetched and shown to the Captain: "
            f"{rendered}. These reads change nothing, so use them when a quick "
            "lookup would help the Captain rather than declining."
        )

    def capability_affordances(self) -> dict[str, str]:
        """AD-983a: ``{intent_name: usage_hint}`` for every capability that
        declares a ``usage_hint`` AND is served by a live agent right now.

        The source of truth for "what can I reach on the mesh this turn": walk
        the live registry, read each agent's declared ``intent_descriptors``,
        and collect the hints. Substrate-gated — only LIVE agents contribute, so
        a capability whose pool is down is absent (the BF-599 honest-degrade
        generalized off Yeo's ``_available_mesh_read_intents``). Deduplicated by
        intent name (first live server wins). Tier-2: never raises; returns {}
        on no runtime / no registry / any read failure.

        AD-983b will intersect this with the agent's *granted* capabilities; for
        now the live-pool reachability check is the gate.
        """
        runtime = getattr(self, "_runtime", None)
        registry = getattr(runtime, "registry", None)
        if registry is None:
            return {}
        out: dict[str, str] = {}
        try:
            for agent in registry.all():
                for desc in getattr(agent, "intent_descriptors", None) or []:
                    hint = getattr(desc, "usage_hint", "")
                    name = getattr(desc, "name", "")
                    if hint and name and name not in out:
                        out[name] = hint
        except Exception:
            logger.debug(
                "AD-983a: capability_affordances build failed; no affordance "
                "block this turn", exc_info=True,
            )
            return {}
        return out

    def _conversational_agentic_self_description(self, observation: dict) -> str:
        """AD-1070: ONE cohesive self-description of the conversational agentic
        (tool-calling) loop's native capabilities, injected ONLY on the turns the
        loop actually handles.

        When ``_conversational_agentic_will_run(observation)`` is True (the single
        source of truth: a wired runtime, ``config.dm_agentic.enabled``, a 1:1
        ``direct_message``, no group / no vision) the AD-1065 loop assembles real
        tools this turn -- ``run_python`` (AD-1066: execute code / produce a real
        downloadable file), ``search_capabilities`` (AD-1072: discover tools /
        skills / mesh intents), ``use_skill`` (AD-1068: load + run a cognitive
        skill), and ``delegate_task`` (AD-1072: hand a bounded subtask to a crew
        peer). Those tools supersede the scattered single-pass reply-tag teaching
        (the AD-869 ``[MESH ...]`` read seam, the AD-1064 ``<artifact>`` tag), so
        this hook unifies the per-tag grounding into one affirmative block that
        appears only when the loop runs.

        Default-OFF / byte-identical guarantee: returns "" whenever the loop will
        NOT run (flag off / group / vision / no runtime), so the composed prompt
        is unchanged from HEAD on every single-pass turn. Gap-regex-safe (AD-957:
        no can't / cannot / unable / lack / no-capability phrasing) so the block
        never trips the AD-596 capability-gap detector. Overridable (Open/Closed).
        """
        if not self._conversational_agentic_will_run(observation):
            return ""
        return (
            "\n\nActing directly this turn: you have a working loop that runs real "
            "tools before you reply, so do the work and report the result rather "
            "than only describing how it might be done. The tools you have this "
            "turn:\n"
            "- run_python: execute Python to compute, transform data, or produce a "
            "real downloadable file (a .docx, .xlsx, .pdf, chart, or archive) the "
            "Captain can open -- write and run the code, then hand back the result.\n"
            "- search_capabilities: discover the tools, skills, and mesh intents "
            "reachable right now, so your reply is grounded in what the ship truly "
            "offers this turn.\n"
            "- use_skill: load and run a saved cognitive skill to carry a "
            "specialized task through end to end.\n"
            "- delegate_task: hand a bounded subtask to another crew agent by "
            "callsign and fold their result into your reply.\n"
            "Prefer these tools to finish the task within this turn; describe an "
            "approach only when the Captain asks for the plan itself."
        )

    def _conversational_task_protocol(self, observation: dict) -> str:
        """Overridable hook (AD-845): task-creation protocol appended to the
        conversational system prompt. Default returns "" so only opting-in
        agents (e.g. Yeo) learn the ``[CREATE_TASK ...]`` reply tag that lets
        a 1:1 chat reply spawn a dispatchable work item."""
        return ""

    def _conversational_notebook_protocol(self, observation: dict) -> str:
        """Notebook-save protocol appended to the conversational system
        prompt (AD-911, generalized to all crew agents in AD-912).

        Any crew agent — not just the Yeoman — should be able to durably
        save a note when the Captain asks for it in a 1:1 chat, the same way
        notebooks are a universal agent capability on the proactive /
        Ward-Room path. The agent emits ``[NOTEBOOK topic-slug]...
        [/NOTEBOOK]`` anywhere in its reply and
        ``DmReplyPipeline.step_4i_notebook_parse`` writes it to that agent's
        notebook in Ship's Records (AD-550 dedup) and strips the block from
        the Captain-visible reply.

        Honest-degrade: returns "" when no records store is wired, so an
        agent is never told it can save notes the substrate cannot back (the
        BF-599 / AD-592 confabulation lesson). All tag text is gap-regex-safe.
        Overridable so an agent can tailor the framing (Open/Closed).
        """
        runtime = getattr(self, "_runtime", None)
        if runtime is None:
            return ""
        if getattr(runtime, "_records_store", None) is None:
            return ""
        return (
            "\n\nSaving notes to your notebook: when the Captain asks you to "
            "save, record, note, or remember something for later, persist it "
            "to your notebook in Ship's Records by emitting [NOTEBOOK "
            "topic-slug]\nYour note text here\n[/NOTEBOOK] anywhere in your "
            "reply. Use a short hyphenated topic-slug (e.g. "
            "spacex-ipo-trade-setup). The note is written to durable storage "
            "and the tag is removed before the Captain sees your reply, so "
            "confirm conversationally that you have saved it. Only claim a "
            "note is saved when you actually emit this tag — never say you "
            "saved something without it. The note is private to you by "
            "default; write [NOTEBOOK topic-slug department] or [NOTEBOOK "
            "topic-slug ship] when the Captain asks for something the crew "
            "should see."
        )

    def _conversational_artifact_block(self, observation: dict) -> str:
        """AD-1064: teach every crew agent to produce a downloadable DOCUMENT
        (a saved file the Captain can open + download) in a 1:1 chat.

        The Captain frequently asks an agent to "write it up", "save this", or
        "put it in a document/file". The wired path is the AD-797 artifact
        extractor (``DmReplyPipeline.step_4f_extract_artifacts``): the agent
        wraps the document body in an ``<artifact name="..." mime="...">
        ...</artifact>`` tag anywhere in its reply; the pipeline persists it to
        the ArtifactStore (versioned, content-addressable) and replaces the
        block with a stub the HXI renders as a clickable, downloadable card.
        Without this grounding an agent confabulates a write verb (e.g. a
        ``[MESH create_file ...]`` tag — the AD-869 ``[MESH ...]`` seam is
        read-only and has no such verb), so the document is never saved.

        Honest-degrade: returns "" when the artifact substrate is absent, so an
        agent is never told it can save a file the ship cannot persist (the
        BF-599 / AD-592 lesson). The how-to text is gap-regex-safe. Overridable
        (Open/Closed)."""
        del observation
        runtime = getattr(self, "_runtime", None)
        if runtime is None:
            return ""
        if (
            getattr(runtime, "artifact_store", None) is None
            or getattr(runtime, "attachment_store", None) is None
        ):
            return ""
        return (
            "\n\nSaving a document the Captain can download: when the Captain "
            "asks you to write up, save, export, or put something into a "
            "document or file, wrap the full content in an artifact tag "
            "anywhere in your reply. Open with "
            '<artifact name="recommendations.md" mime="text/markdown">, put '
            "the document body on the following lines, and close with "
            "</artifact> on its own line. The system saves it and shows the "
            "Captain a downloadable card; the tag itself is removed before the "
            "Captain sees your reply, so confirm conversationally that you have "
            "saved it. Use a simple filename (letters, numbers, dots, dashes) "
            "with a matching extension, and prefer Markdown (name ending .md, "
            "mime text/markdown) for written reports. Only say a document is "
            "saved when you actually emit this tag."
        )

    def _conversational_deliberate_protocol(self, observation: dict) -> str:
        """AD-934 (Option C): teach the [THINK] reply marker to all crew agents
        WHEN config.dm_deliberate.enabled is True (default OFF -> ""). The agent
        emits [THINK] anywhere in its reply when a turn warrants deeper reasoning;
        DmReplyPipeline.step_4j_deliberate_parse then makes one deep-tier pass to
        improve the draft. Honest-degrade: returns "" when the flag is off or no
        runtime/config is wired. Overridable (Open/Closed)."""
        runtime = getattr(self, "_runtime", None)
        cfg = getattr(getattr(runtime, "config", None), "dm_deliberate", None)
        if not getattr(cfg, "enabled", False):
            return ""
        return (
            "\n\nDeeper reasoning: when a question genuinely warrants more careful "
            "thought than a quick reply, place the marker [THINK] anywhere in your "
            "response. The system will take one extra pass to sharpen your reply "
            "before it is sent. Use it sparingly — only for hard or high-stakes "
            "turns, not routine chat."
        )

    def _conversational_a2ui_block(self, observation: dict) -> str:
        """AD-811a: teach the ``[A2UI]`` choice-widget reply tag to Lieutenant+
        crew agents WHEN ``CommunicationsConfig.a2ui_enabled`` is True
        (default OFF -> "").

        When enabled and the agent's LIVE rank is at least ``a2ui_min_rank``
        (default lieutenant), the agent learns to offer the Captain a
        single-choice card by emitting ``[A2UI]{json}[/A2UI]`` carrying
        ``{"kind":"choice","prompt":...,"options":[...]}``.
        ``DmReplyPipeline.step_4k_extract_a2ui`` then stores the spec as an
        artifact and leaves an inline stub the HXI renders as clickable
        buttons; the Captain's pick posts back as a normal chat message.

        Default-OFF / honest-degrade: returns "" when the flag is off, when
        the agent's rank is below the minimum, or when no runtime/config is
        wired (getattr-safe). Rank is derived from the LIVE trust score
        (BF-263: ``self.rank`` is never set on agents). Overridable
        (Open/Closed); the how-to text is gap-regex-safe (no
        can't/cannot/unable/don't-have phrasings)."""
        del observation
        try:
            runtime = getattr(self, "_runtime", None)
            comms_cfg = getattr(
                getattr(runtime, "config", None), "communications", None
            )
            if not getattr(comms_cfg, "a2ui_enabled", False):
                return ""
            from probos.crew_profile import Rank
            _RANK_ORDER = [
                Rank.ENSIGN, Rank.LIEUTENANT, Rank.COMMANDER, Rank.SENIOR,
            ]
            min_rank_str = getattr(comms_cfg, "a2ui_min_rank", "lieutenant")
            min_rank = (
                Rank[min_rank_str.upper()]
                if min_rank_str.upper() in Rank.__members__
                else Rank.LIEUTENANT
            )
            # BF-263: derive the live rank from the trust score; self.rank is
            # never set on agents.
            rank: Rank | None = None
            trust_net = getattr(runtime, "trust_network", None)
            if trust_net is not None:
                live_trust = trust_net.get_score(self.id)
                if isinstance(live_trust, (int, float)):
                    rank = Rank.from_trust(float(live_trust))
            if rank is None:
                return ""
            if _RANK_ORDER.index(rank) < _RANK_ORDER.index(min_rank):
                return ""
            return (
                "\n\nOffering the Captain a quick choice: when a question has a "
                "small set of clear options, you may present them as clickable "
                "buttons. Emit [A2UI]{\"kind\":\"choice\",\"prompt\":\"your "
                "question\",\"options\":[\"Option A\",\"Option B\"]}[/A2UI] for "
                "a single pick, [A2UI]{\"kind\":\"multiselect\",\"prompt\":"
                "\"your question\",\"options\":[\"Option A\",\"Option B\","
                "\"Option C\"],\"min_select\":1}[/A2UI] when several picks make "
                "sense at once, or [A2UI]{\"kind\":\"form\",\"prompt\":\"your "
                "question\",\"fields\":[{\"label\":\"Name\"},{\"label\":"
                "\"Role\",\"required\":true}]}[/A2UI] to gather a few labeled "
                "values together. The tag becomes an interactive card; a single "
                "choice comes back as the Captain's next message, a multi-select "
                "comes back as their picks joined by commas, and a form comes "
                "back as label: value lines. Keep it short (a handful of "
                "options or fields) and continue the conversation naturally "
                "once they respond."
            )
        except Exception:
            logger.debug(
                "AD-811a: a2ui teaching block build failed; no block this turn",
                exc_info=True,
            )
            return ""

    def _conversational_group_chat_protocol(self, observation: dict) -> str:
        """AD-935 / AD-967 / AD-975: in a group chat, teach (1) WHO is present in
        the room — the AD-967 roster — (2) that responding is OPTIONAL (reply only
        with something substantive to add, else decline), and (3) HOW the room's
        turn-taking actually works (AD-975).

        The roster is the fix for the Captain-reported bug where agents kept
        addressing a peer who was never invited (e.g. asking "Sentinel" a
        question in a room Sentinel is not in), and assumed a peer they named in
        prose had been added. Knowing who is actually present, an agent addresses
        only present members and asks the Captain to add anyone else instead of
        talking to an absent peer.

        AD-975 (turn-taking self-knowledge): in a live test the crew reasoned
        ACCURATELY about reading the floor but assumed possible SIMULTANEITY
        ("two of us could respond before either sees the other's reply"). In
        reality the fan-out is sequential + synchronous: one speaker per turn,
        and each later speaker receives every prior reply in full before its own
        turn — so two crew never answer the same point at once. Teaching the real
        mechanism makes the agent's self-model correct: it can build on what was
        already said without fear of a collision, and it should not wait for a
        live "typing" cue from a peer (there is none — a turn simply arrives when
        the peer has finished).

        Gated on the group fan-out param ``is_group_chat`` so 1:1 DMs are
        unaffected. The roster rides the fan-out param ``room_roster`` (present
        participant labels); when it is absent the decline guidance is
        byte-identical to pre-AD-967. Universal (all crew), like the AD-912
        notebook capability. Overridable (Open/Closed). Gap-regex-safe (no
        can't/cannot/don't have/unable to/not able to/lack/not available)."""
        params = observation.get("params") or {}
        if not params.get("is_group_chat"):
            return ""
        roster_line = ""
        roster = params.get("room_roster")
        if isinstance(roster, list):
            names = [str(r).strip() for r in roster if str(r).strip()]
            if names:
                if len(names) == 1:
                    who = names[0]
                elif len(names) == 2:
                    who = f"{names[0]} and {names[1]}"
                else:
                    who = ", ".join(names[:-1]) + f", and {names[-1]}"
                roster_line = (
                    f"\n\nPresent in this room: {who}. These are the only members "
                    "here right now. Address a person by name only when they are "
                    "present in the room above. To bring in a colleague who is not "
                    "yet here, ask the Captain to add them to the room rather than "
                    "speaking to them as though they were already in it."
                )
        return (
            roster_line
            + "\n\nYou are in a group chat with other crew. Reply ONLY when you have "
            "something substantive to add, build on, answer, or correct. If a "
            "fellow crew member directs a question to you, answer it. When you have "
            "nothing to add, respond with exactly [NO_RESPONSE] and nothing else."
            "\n\nHow turn-taking works here: the crew speak one at a time, in "
            "sequence. You receive each colleague's COMPLETED reply before it is "
            "your turn — never at the same instant — so you can read what has "
            "already been said and build on it rather than repeating it. Because "
            "the floor is handed to one speaker at a time, two of you will never "
            "answer the same point at once, so respond with confidence that you "
            "have the full picture of the turns before yours. There is no live "
            "\"typing\" cue from a colleague; their turn simply arrives when they "
            "have finished. When you want a specific colleague to take the next "
            "turn, address them by name and they will be invited to respond."
        )

    def _conversational_room_todo_protocol(self, observation: dict) -> str:
        """AD-1082/AD-1085: teach the room-Todo tags AND the heuristic for when
        to use them — agents plan multi-step work as a checklist on their own
        (like GitHub Copilot's todo list), not only when asked. Gated on the
        group fan-out param ``is_group_chat`` + ``room_todos_enabled``.
        Universal (all crew). Overridable. Gap-regex-safe."""
        params = observation.get("params") or {}
        if not params.get("is_group_chat"):
            return ""
        comm = getattr(getattr(self, "_runtime", None), "config", None)
        comm = getattr(comm, "communications", None)
        if not getattr(comm, "room_todos_enabled", False):
            return ""
        return (
            "\n\nShared task checklist: track multi-step work in this room as a "
            "numbered checklist on your own — without waiting to be asked, the "
            "way a good assistant plans before acting. The moment a request "
            "needs more than one step, or hands off between you and a colleague, "
            "FIRST write the plan as the steps inside [TODOS] and [/TODOS], one "
            "step per line, BEFORE starting any of them (a single quick reply "
            "needs no checklist; two or more steps or any handoff always do). "
            "Mark your own step finished with [TODO_DONE n] (n is the step "
            "number). A senior or the facilitator confirms finished work with "
            "[TODO_CONFIRM n] or returns it with [TODO_REJECT n: reason] — a "
            "step counts as complete only once a senior confirms it. If a step "
            "yields a document, save it with the artifact tag so it lands in "
            "Outputs; for a Word document use mime application/vnd."
            "openxmlformats-officedocument.wordprocessingml.document (.docx), a "
            "presentation .pptx (...presentationml.presentation), a spreadsheet "
            ".xlsx (...spreadsheetml.sheet) — not markdown. Put the tags inline "
            "in your reply; they are applied and hidden from the transcript."
        )

    def _conversational_room_outputs_block(self, observation: dict) -> str:
        """BF-651: list the room's SAVED outputs so a reviewer verifies against
        storage instead of memory. Crew flagged that read_file outputs/X.docx
        returned empty (artifacts live in the ArtifactStore by name, not disk),
        so final-review steps trusted memory. Gated on the group fan-out param
        ``room_outputs`` (built from artifact_store.list_thread_latest). Gap-safe."""
        outs = (observation.get("params") or {}).get("room_outputs") or []
        if not isinstance(outs, list) or not outs:
            return ""
        listed = "; ".join(str(o) for o in outs[:20])
        return (
            "\n\nSaved Outputs in this room (authoritative, in storage): "
            f"{listed}. These files are persisted — treat them as the source of "
            "truth when reviewing or revising. Save a new version with the "
            "artifact tag rather than reading a disk path."
        )

    def _conversational_grounding_cue_block(self, observation: dict) -> str:
        """AD-1120: inject the honest-absence cue for an unresolved CENTRAL room
        referent so the LLM is steered to the "structurally unresolvable" close
        instead of confabulating. Gated to the GROUP fan-out path: returns ""
        unless ``params["is_group_chat"]`` AND the fan-out attached a
        ``grounding_cue`` (only set when ``ground_before_collaborate_enabled`` +
        an eligible unresolved central referent). The cue is the AD-1119 string
        verbatim — already ``is_capability_gap``-clean. Overridable (Open/Closed).
        Byte-identical when no cue is attached."""
        params = observation.get("params") or {}
        if not params.get("is_group_chat"):
            return ""
        cue = params.get("grounding_cue")
        if not isinstance(cue, str) or not cue.strip():
            return ""
        return "\n\n" + cue.strip()

    def _conversational_proactivity_protocol(self, observation: dict) -> str:
        """AD-950 (Natural Conversation epic, #886): teach the discourse OBLIGATION
        to ADVANCE a live conversation. On the 1:1/group ``direct_message`` reply
        path, append calibrated guidance to end an ENGAGED turn with ONE forward
        move — a genuine follow-up question, or a proposal/offer that gives the
        other party an easy opening to respond — using recipient design (react to
        specifics, address by name). NOT every turn: calibrated to engagement and
        the agent's personality so it reads as conversation, not interrogation. In
        a group chat (the fan-out param ``is_group_chat``) it additionally permits
        handing the floor to a peer by name (sets up AD-951's next-speaker
        selection). Gated to the live conversational path (intent ==
        "direct_message") so ward-room / proactive posts — which already carry
        their own conversation-advancing guidance — are unaffected. Default ON via
        ``CommunicationsConfig.proactive_conversation_enabled`` (a tuning knob, not
        a kill switch); honest-degrade returns "" when the flag is off. Overridable
        (Open/Closed). Gap-regex-safe (no can't/cannot/don't have/unable to/not
        able to)."""
        if observation.get("intent") != "direct_message":
            return ""
        runtime = getattr(self, "_runtime", None)
        comm_cfg = getattr(getattr(runtime, "config", None), "communications", None)
        if not getattr(comm_cfg, "proactive_conversation_enabled", True):
            return ""
        guidance = (
            "\n\nKeeping the conversation alive: you are a participant in a real "
            "conversation, not a question-answering service. When the exchange is "
            "engaged and a natural next step exists, end your turn with ONE forward "
            "move — a genuine follow-up question, an observation that invites a "
            "reply, or a concrete proposal or offer that gives the other person an "
            "easy opening to respond. Do this when it fits the moment, NOT on every "
            "turn: read the Captain's engagement and your own personality, and let "
            "a turn rest when that is the natural thing (a simple acknowledgement, a "
            "closing thought, or a beat the Captain plainly wants to end). React to "
            "the SPECIFIC thing that was said — name it and build on it — rather "
            "than replying in the abstract. Match your length to the move: a brief "
            "reaction when that is enough, a fuller contribution when the topic "
            "earns it. Honest, respectful disagreement is welcome when your "
            "expertise points a different direction — reflexive agreement reads as "
            "hollow. Ground every follow-up in what was actually said; never invent "
            "a question or proposal about something that did not occur."
        )
        params = observation.get("params") or {}
        if params.get("is_group_chat"):
            guidance += (
                "\n\nBecause this is a group chat, you may also hand the floor to a "
                "specific crew member when their expertise fits the moment: address "
                "them directly by name (their callsign) and put the question or "
                "proposal to them, the way colleagues pull a teammate into a "
                "discussion. Use this to keep the conversation moving across the "
                "crew — one clear hand-off to the right person, not a prompt aimed "
                "at everyone at once."
            )
        return guidance

    def _conversational_memory_protocol(self, observation: dict) -> str:
        """AD-953 (Natural Conversation epic, #889): teach conversational MEMORY &
        CALLBACKS. On the 1:1/group ``direct_message`` reply path, append guidance
        to draw on what the agent GENUINELY recalls — the episodic memories +
        session history already injected into the reply context
        (AD-573/AD-723a-1) — and make natural callbacks ("you mentioned …", "last
        time we …", "building on what we discussed …") so the exchange feels
        continuous instead of amnesiac, with recipient design (tailor to the
        shared history with THIS person). Hard AD-592 honesty bound: reference
        only what is actually present in the recalled material; never fabricate a
        shared memory, a prior statement, or a callback — an invented "as you said
        last week" is worse than none. Gated to the live conversational path
        (intent == "direct_message"); default ON via
        ``CommunicationsConfig.conversational_memory_enabled`` (a tuning knob);
        honest-degrade returns "" when the flag is off. Overridable (Open/Closed).
        Gap-regex-safe (no can't/cannot/don't have/unable to/lack/not
        available)."""
        if observation.get("intent") != "direct_message":
            return ""
        runtime = getattr(self, "_runtime", None)
        comm_cfg = getattr(getattr(runtime, "config", None), "communications", None)
        if not getattr(comm_cfg, "conversational_memory_enabled", True):
            return ""
        return (
            "\n\nConversational memory: you are a continuing presence with a shared "
            "history, not a fresh stranger each turn. Draw on what you genuinely "
            "remember — the recalled memories and the running conversation in your "
            "context — and weave it in naturally: pick up a thread from earlier, "
            "call back to something the other person told you before (\"you "
            "mentioned the variance last time\", \"building on what we settled "
            "yesterday\"), and let your shared history shape how you speak to THIS "
            "person. This is what makes a conversation feel continuous rather than "
            "amnesiac. One hard rule, above all else: reference ONLY what you "
            "actually find in your recalled memory or the conversation in front of "
            "you. If you are uncertain whether something happened, treat it as if "
            "it did not, and simply do not bring it up. Never manufacture a shared "
            "memory, a prior promise, or a detail you do not truly recall — an "
            "invented callback (\"as you told me last week …\" when they did not) "
            "breaks trust far worse than having no callback at all. When you have "
            "nothing genuine to recall, just speak to the present moment."
        )

    def _conversational_room_awareness_protocol(self, observation: dict) -> str:
        """AD-955 (Natural Conversation epic, weighted-trust room sense): surface
        the facilitator's per-speaker ranking to the speaker so the room can
        SELF-REGULATE without a director. On the GROUP ``direct_message`` reply
        path, when the fan-out attached a ``room_signal`` (how much you've
        contributed recently, whether the topic is your area, which peer the room
        would most value hearing), append framing that ties each fact to a move:
        a speaker who has been carrying the conversation may take a lighter touch
        or HAND OFF; a speaker may DEFER to a better-placed peer BY NAME (an
        AD-951 hand-off) — reframed as collaboration, not a shortfall, to dissolve
        the ego problem. ADVISORY: this never changes who is dispatched (the
        cap/convergence backstops own that) — it gives the agent the AGENCY to
        hold back or defer, which a hard cap cannot. Gated to the live group path
        (intent == "direct_message" AND params["is_group_chat"] AND a present
        room_signal); default ON via ``CommunicationsConfig.room_awareness_enabled``.
        Overridable (Open/Closed). Gap-regex-safe (no can't/cannot/unable to/don't
        have/lack/not available)."""
        if observation.get("intent") != "direct_message":
            return ""
        runtime = getattr(self, "_runtime", None)
        comm_cfg = getattr(getattr(runtime, "config", None), "communications", None)
        if not getattr(comm_cfg, "room_awareness_enabled", True):
            return ""
        params = observation.get("params") or {}
        if not params.get("is_group_chat"):
            return ""
        rs = params.get("room_signal")
        if not isinstance(rs, dict):
            return ""
        share = rs.get("recent_share", 0)
        window = rs.get("recent_window", 0)
        your_area = bool(rs.get("this_is_your_area"))
        peer = rs.get("room_would_value")
        peer = peer if (isinstance(peer, str) and peer) else None
        parts = ["\n\nRoom sense — for your judgment, not a directive:"]
        if window:
            parts.append(
                f" of the last {window} contributions in this room, {share} were yours."
            )
        if your_area:
            parts.append(" This topic sits squarely in your area of expertise.")
        if peer:
            parts.append(
                f" Weighing everything said so far, the room would likely value "
                f"hearing {peer} on this."
            )
        parts.append(
            " Most turns, simply contribute as yourself. But read the moment: if "
            "you have been carrying the conversation, a lighter touch — or handing "
            "the floor to a colleague — serves the room better than another long "
            "turn from you."
        )
        if peer:
            parts.append(
                f" And if {peer} is genuinely better placed here than you are, it "
                f"is good collaboration to defer to them — address them by name so "
                f"they can pick up the thread. Yielding the floor to the stronger "
                f"voice on a topic is teamwork, the mark of a confident colleague, "
                f"never a shortfall."
            )
        else:
            parts.append(
                " Drawing a colleague in by name when their expertise fits the "
                "moment is teamwork, the mark of a confident colleague."
            )
        return "".join(parts)

    async def decide(self, observation: dict) -> dict:
        """Consult the LLM with instructions + observation.

        Decision Distillation (AD-272): checks in-memory cache before
        calling LLM. Cache hits return instantly (<1ms, $0).
        """
        if not self._llm_client:
            return {"action": "error", "reason": "No LLM client available"}

        # --- Decision cache lookup ---
        cache = _DECISION_CACHES.setdefault(self.agent_type, {})
        cache_key = self._compute_cache_key(observation)

        if cache_key in cache:
            decision, created_at, ttl = cache[cache_key]
            if time.monotonic() - created_at < ttl:
                _CACHE_HITS[self.agent_type] = _CACHE_HITS.get(self.agent_type, 0) + 1
                logger.debug("Decision cache hit for %s (key=%s)", self.agent_type, cache_key[:8])
                # AD-431: Journal cache hits too (for token accounting accuracy)
                if self._cognitive_journal:
                    try:
                        import uuid as _uuid
                        await self._cognitive_journal.record(
                            entry_id=_uuid.uuid4().hex,
                            timestamp=time.time(),
                            agent_id=self.id,
                            agent_type=self.agent_type,
                            intent=observation.get("intent", ""),
                            intent_id=observation.get("intent_id", ""),
                            cached=True,
                            correlation_id=observation.get("correlation_id", ""),
                        )
                    except Exception:
                        logger.debug("Journal recording failed", exc_info=True)
                return {**decision, "cached": True}
            else:
                del cache[cache_key]

        _CACHE_MISSES[self.agent_type] = _CACHE_MISSES.get(self.agent_type, 0) + 1

        # AD-573: Per-cycle memory budget tracking
        _budget_mgr: MemoryBudgetManager | None = None
        memory_budget_config = getattr(self, "_memory_budget_config", None)
        if memory_budget_config and memory_budget_config.enabled:
            from probos.cognitive.memory_budget import MemoryBudgetManager
            _budget_mgr = MemoryBudgetManager(memory_budget_config)

        # AD-595e: Inject qualification standing (after cache key, before LLM call)
        await self._refresh_qualification_standing()
        if getattr(self, '_qualification_standing', None):
            observation["qualification_standing"] = self._qualification_standing

        # --- AD-534: Procedural memory check (semantic match) ---
        procedural_result = await self._check_procedural_memory(observation)
        if procedural_result is not None:
            # Record in journal (fire-and-forget)
            if self._cognitive_journal:
                try:
                    import uuid as _uuid
                    await self._cognitive_journal.record(
                        entry_id=_uuid.uuid4().hex,
                        timestamp=time.time(),
                        agent_id=self.id,
                        agent_type=self.agent_type,
                        intent=observation.get("intent", ""),
                        intent_id=observation.get("intent_id", ""),
                        cached=True,
                        total_tokens=0,
                        procedure_id=procedural_result.get("procedure_id", ""),
                        correlation_id=observation.get("correlation_id", ""),
                    )
                except Exception:
                    logger.debug("Journal recording failed", exc_info=True)
            return procedural_result

        # --- AD-643a: Intent-driven chain activation with targeted skill loading ---
        # Priority 1: externally-set chain (escape hatch for skills, JIT, etc.)
        if self._pending_sub_task_chain is not None:
            chain = self._pending_sub_task_chain
            self._pending_sub_task_chain = None  # consume once
            # External chains get all augmentation skills (pre-AD-643 behavior)
            if observation.get("intent") in _CHAIN_ELIGIBLE_INTENTS:
                _aug = self._load_augmentation_skills(observation.get("intent", ""))
                if _aug:
                    observation["_augmentation_skill_instructions"] = _aug
            logger.info(
                "AD-632f: External chain activated for %s (intent=%s, source=%s)",
                self.agent_type,
                observation.get("intent", ""),
                getattr(chain, "source", "unknown"),
            )
            chain_result = await self._execute_sub_task_chain(chain, observation)
            if chain_result is not None:
                _cache_ttl = self._get_cache_ttl()
                cache[cache_key] = (chain_result, time.monotonic(), _cache_ttl)
                return chain_result
            logger.info("AD-632f: Falling back to single-call for %s", self.agent_type)

        # Priority 2: intent-driven routing (AD-643a)
        elif self._should_activate_chain(observation):
            # AD-722f: bracket chain reasoning with NORMAL-tier sampling.
            # Wrapped in try/finally so an exception inside the chain
            # cannot leak the refcount. Tier-2 degrade if the runtime is
            # missing the state machine (e.g. test rigs with minimal
            # MagicMock runtimes) — getattr fallback to None is safe.
            _sampling_state = getattr(self._runtime, 'avatar_sampling_state', None)
            _avatar_event_bus = getattr(self._runtime, 'avatar_event_bus', None)
            if _sampling_state is not None:
                _sampling_state.enter_chain(self.id)
            if _avatar_event_bus is not None:
                # AD-722b: wake WS publish loop on chain enter.
                _avatar_event_bus.notify(self.id)
            try:
                chain_result = await self._execute_chain_with_intent_routing(observation)
            finally:
                if _sampling_state is not None:
                    _sampling_state.exit_chain(self.id)
                if _avatar_event_bus is not None:
                    _avatar_event_bus.notify(self.id)
            if chain_result is not None:
                _cache_ttl = self._get_cache_ttl()
                cache[cache_key] = (chain_result, time.monotonic(), _cache_ttl)
                return chain_result
            # chain_result is None → fall through to _decide_via_llm()
            # Skills may already be loaded in observation from intent routing

        # --- LLM call (cache miss) ---
        decision = await self._decide_via_llm(observation)

        # Record strategy outcomes (AD-384)
        applied_strategy_ids = decision.pop("_applied_strategy_ids", [])
        if applied_strategy_ids and self._strategy_advisor:
            for sid in applied_strategy_ids:
                self._strategy_advisor.record_outcome(
                    sid, self.agent_type, success=True
                )

        # --- Store in cache ---
        ttl = self._get_cache_ttl()
        cache[cache_key] = (decision, time.monotonic(), ttl)

        # Evict oldest entry if cache exceeds 1000 per agent type
        if len(cache) > 1000:
            oldest_key = min(cache, key=lambda k: cache[k][1])
            del cache[oldest_key]

        return decision

    async def _decide_via_llm(self, observation: dict) -> dict:
        """AD-534b: LLM-only decision path — extracted from decide() for DRY reuse.

        Builds messages, calls LLM, records to journal.
        Returns decision dict. Does NOT check decision cache or procedural memory.
        """
        # AD-633d: Pre-LLM speculation cache check.
        # If a SpeculationCache hit is available, prepend pre-computed analysis
        # to observation as `_speculation_prefetch`. The LLM still runs — the
        # prefetch is observation context, not a decision.
        runtime = getattr(self, "_runtime", None)
        cache = getattr(runtime, "speculation_cache", None) if runtime is not None else None
        engine = getattr(runtime, "prediction_engine", None) if runtime is not None else None
        # Defensive isinstance check: test rigs that pass MagicMock runtimes
        # auto-vivify attribute access; without this guard the hook would fire
        # on every mocked runtime and mutate the observation dict.
        from probos.cognitive.predictive_branching.cache import SpeculationCache as _SpecCache
        if isinstance(cache, _SpecCache) and engine is not None:
            try:
                from probos.cognitive.predictive_branching.engine import compute_signature
                signature = compute_signature(
                    agent_id=self.id,
                    intent_type=str(observation.get("intent", "")),
                    observation=observation,
                )
                payload = cache.lookup(signature)
                if payload is not None:
                    observation["_speculation_prefetch"] = payload
                    tracker = getattr(runtime, "accuracy_tracker", None)
                    if tracker is not None:
                        from probos.cognitive.predictive_branching.accuracy import (
                            PredictionOutcome,
                        )
                        try:
                            tracker.record(
                                agent_id=self.id, outcome=PredictionOutcome.HIT
                            )
                        except Exception:
                            logger.warning(
                                "AD-633e: tracker.record(HIT) failed for %s",
                                self.id, exc_info=True,
                            )
                else:
                    # Miss is interesting too — track it
                    tracker = getattr(runtime, "accuracy_tracker", None)
                    if tracker is not None:
                        from probos.cognitive.predictive_branching.accuracy import (
                            PredictionOutcome,
                        )
                        try:
                            tracker.record(
                                agent_id=self.id, outcome=PredictionOutcome.MISS
                            )
                        except Exception:
                            logger.warning(
                                "AD-633e: tracker.record(MISS) failed for %s",
                                self.id, exc_info=True,
                            )
                    emit = getattr(runtime, "emit_event", None)
                    if emit is not None:
                        try:
                            emit(
                                "prediction_miss",
                                {
                                    "signature": signature,
                                    "agent_id": self.id,
                                    "intent_type": str(observation.get("intent", "")),
                                },
                            )
                        except Exception:
                            logger.warning(
                                "AD-633d: emit prediction_miss failed", exc_info=True
                            )
            except Exception:
                logger.warning(
                    "AD-633d: speculation cache check failed for %s; "
                    "proceeding with normal LLM path",
                    self.id, exc_info=True,
                )

        # AD-626: Load augmentation skills BEFORE building user message
        # so _build_user_message() can frame tasks with skill instructions.
        # Skip if already loaded by decide() for chain activation (AD-632f).
        if "_augmentation_skill_instructions" not in observation:
            _aug_instructions = self._load_augmentation_skills(observation.get("intent", ""))
            if _aug_instructions:
                observation["_augmentation_skill_instructions"] = _aug_instructions

        # AD-585: Tiered knowledge loading (ambient + contextual).
        _knowledge_loader = getattr(self, "_knowledge_loader", None)
        if _knowledge_loader:
            try:
                _ambient = await _knowledge_loader.load_ambient()
                if _ambient:
                    observation.setdefault("_knowledge_ambient", _ambient)

                _intent_type = observation.get("intent", "")
                if _intent_type:
                    _department = observation.get("department", "")
                    _contextual = await _knowledge_loader.load_contextual(
                        _intent_type,
                        _department,
                    )
                    if _contextual:
                        observation.setdefault("_knowledge_contextual", _contextual)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "AD-585: Knowledge loading failed for agent_type=%s; proceeding without. "
                    "Agent will use base context only.",
                    self.agent_type,
                    exc_info=True,
                )

        user_message = await self._build_user_message(observation)

        # Strategy advice (AD-384)
        applied_strategy_ids: list[str] = []
        if self._strategy_advisor:
            intent_type = observation.get("intent", "")
            if intent_type:
                strategies = self._strategy_advisor.query_strategies(
                    intent_type, self.agent_type
                )
                context = self._strategy_advisor.format_for_context(strategies)
                if context:
                    user_message = user_message + "\n\n" + context
                applied_strategy_ids = [
                    s["id"] for s in strategies if s.get("id")
                ]

        from probos.cognitive.standing_orders import compose_instructions

        # BF-010: conversational system prompt for 1:1 sessions
        # AD-407b: conversational system prompt for ward room notifications
        is_conversation = observation.get("intent") in ("direct_message", "ward_room_notification", "proactive_think")

        # AD-586: Classify current task for contextual standing orders
        _task_type = None
        if self._task_context is not None:
            intent_name = observation.get("intent", "")
            _task_type = self._task_context.classify_task(intent_name)

        if is_conversation:
            # For 1:1 and ward room, use personality + standing orders only.
            # Exclude domain-specific task instructions (report formats, output blocks)
            # so the LLM responds naturally as itself.
            composed = compose_instructions(
                agent_type=getattr(self, "agent_type", self.__class__.__name__.lower()),
                hardcoded_instructions="",
                callsign=self._resolve_callsign(),
                agent_rank=getattr(self, "rank", None),  # AD-596b
                skill_profile=getattr(self, '_skill_profile', None),  # AD-625
                task_type=_task_type,
            )
            if observation.get("intent") == "ward_room_notification":
                # BF (2026-05-11): When the notification is for a DM channel,
                # the agent is INSIDE an ongoing 1:1 conversation. Plain-text
                # replies are auto-posted to the same thread by the pipeline
                # (_self_post_ward_room_response). Offering [DM @callsign]
                # here causes the agent to wrap its reply in a [DM] block,
                # which the action extractor turns into a brand-new thread
                # in the DM channel — producing a fresh thread per message
                # instead of a continuing conversation.
                _wr_params = observation.get("params", {})
                _in_dm_channel = _wr_params.get("is_dm_channel", False)
                if _in_dm_channel:
                    _dm_partner = _wr_params.get("author_callsign", "") or "the other crew member"
                    composed += (
                        f"\n\nYou are in a private direct message conversation with @{_dm_partner}. "
                        "Reply naturally and conversationally — your response will be posted "
                        f"to this DM thread as a reply to @{_dm_partner}. "
                        "Do NOT wrap your reply in [DM @callsign] tags — that would start a "
                        "brand-new conversation thread. "
                        "Do NOT use [REPLY], [ENDORSE], [NOTEBOOK], or other action tags here. "
                        "Just write your reply text directly (2-4 sentences). "
                        "If you have nothing meaningful to add, respond with exactly: [NO_RESPONSE]"
                    )
                else:
                    composed += (
                        "\n\nYou are participating in the Ward Room — the ship's discussion forum. "
                        "Write concise, conversational posts (2-4 sentences). "
                        "Speak in your natural voice. Don't be formal unless the topic demands it. "
                        "You may be responding to the Captain or to a fellow crew member. "
                        "Engage naturally — agree, disagree, build on ideas, ask questions. "
                        "Do NOT repeat what someone else already said. "
                        "If you have nothing meaningful to add, respond with exactly: [NO_RESPONSE]"
                        "\n\nAfter your reply (or [NO_RESPONSE]), you may endorse posts you've read in this thread. "
                        "If a post is particularly insightful, actionable, or well-reasoned, endorse it up. "
                        "If a post is incorrect, misleading, or unhelpful, endorse it down. "
                        "Only endorse when you have a clear opinion — not every post needs a vote. "
                        "Use this format, one per line:\n"
                        "[ENDORSE post_id UP]\n"
                        "[ENDORSE post_id DOWN]\n"
                        "Place endorsements AFTER your reply text, each on its own line. "
                        "Do NOT endorse your own posts."
                    )
                    # BF-051: DM syntax available in ward room context too
                    _dm_instr = self._compose_dm_instructions(brief=True)
                    if _dm_instr:
                        composed += _dm_instr
            elif observation.get("intent") == "proactive_think":
                composed += (
                    "\n\nYou are reviewing recent ship activity during a quiet moment. "
                    "If you notice something noteworthy — a pattern, a concern, an insight "
                    "related to your expertise — compose a brief observation (2-4 sentences). "
                    "This will be posted to the Ward Room as a new thread. "
                    "Speak in your natural voice. Be specific and actionable. "
                    "If nothing warrants attention right now, respond with exactly: [NO_RESPONSE]\n"
                    "Keep game-related discussions (tic-tac-toe, game strategy, match commentary) "
                    "in the Recreation channel using [REPLY] to existing game threads. "
                    "Your department channel is for professional observations related to your role."
                    "\n\nIf you identify a concrete, actionable improvement to the ship's systems "
                    "(not a vague observation), propose it using:\n"
                    "[PROPOSAL]\n"
                    "Title: <short title>\n"
                    "Rationale: <why this matters and what it would improve>\n"
                    "Affected Systems: <comma-separated subsystems>\n"
                    "Priority: low|medium|high\n"
                    "[/PROPOSAL]\n"
                    "Only propose improvements you have evidence for — not speculation. "
                    "Reserve proposals for genuine insights.\n"
                    "IMPORTANT: If you recently participated in a discussion that identified a system "
                    "problem, diagnosed a root cause, or suggested an improvement — and no formal "
                    "improvement proposal has been submitted for it yet — you should submit one now. "
                    "Collaborative diagnosis should culminate in a formal proposal so the Captain "
                    "can track and act on the finding."
                    "\n\n## Available Actions\n"
                    "Beyond posting observations, you can take structured actions on Ward Room content. "
                    "Place action tags AFTER your observation text, each on its own line.\n\n"
                    "**Endorse posts** — signal agreement or disagreement with a post:\n"
                    "[ENDORSE post_id UP]\n"
                    "[ENDORSE post_id DOWN]\n"
                    "Only endorse when you have a clear, justified opinion. Do NOT endorse your own posts.\n\n"
                    "**Reply to threads** — contribute to an existing discussion instead of starting a new one:\n"
                    "[REPLY thread_id]\n"
                    "Your reply text here (2-3 sentences).\n"
                    "[/REPLY]\n"
                    "Reply when you have something to ADD to an existing conversation. "
                    "Do not reply just to agree — use endorsement for that. "
                    "Replies require Lieutenant rank or higher.\n\n"
                    "**Notebook entries** — document extended analysis in Ship's Records:\n"
                    "[NOTEBOOK topic-slug]\n"
                    "Your extended analysis, research findings, or diagnostic report here.\n"
                    "[/NOTEBOOK]\n"
                    "Use for: research findings, pattern analysis, baseline readings, diagnostic reports. "
                    "This writes to your personal notebook in Ship's Records (AD-434).\n"
                    "Your notebook is private by default — yours alone. Add a scope after the "
                    "topic slug to widen it: [NOTEBOOK topic-slug department] when your "
                    "department should see it, [NOTEBOOK topic-slug ship] when any crew "
                    "member could act on it. Widen when you can name who else needs the "
                    "entry and why; otherwise leave it private (AD-1157).\n\n"
                )
                composed += self._compose_dm_instructions()

                # AD-526a: Challenge action (all ranks)
                composed += (
                    "**Challenge a crewmate** — initiate a game in the Recreation channel:\n"
                    "[CHALLENGE @callsign tictactoe]\n"
                    "Challenge when the mood is light and you want to build social bonds. "
                    "If no one has played a game recently, consider initiating one — "
                    "recreation strengthens crew cohesion. "
                    "Do NOT challenge during alert conditions or critical situations.\n\n"
                    "**Make a game move** — play your turn in an active game:\n"
                    "[MOVE position]\n"
                    "Position is game-specific (e.g. 0-8 for tic-tac-toe). "
                    "Only respond with a move when it's your turn.\n\n"
                )

                composed += (
                    "**When to act vs. observe:**\n"
                    "- See a good post? → [ENDORSE post_id UP] (not a reply saying 'good point')\n"
                    "- Have a concrete addition? → [REPLY thread_id] with your contribution\n"
                    "- Need specialist input? → [DM @callsign] with your question\n"
                    "- Detailed analysis warranted? → [NOTEBOOK topic-slug] with your findings\n"
                    "- See something new? → Write an observation (new thread)\n"
                    "- Nothing noteworthy? → [NO_RESPONSE]"
                )

            else:
                composed += (
                    "\n\nYou are in a 1:1 conversation with the Captain. "
                    "Respond naturally and conversationally as yourself. "
                    "Do NOT use any structured output formats, report blocks, "
                    "code blocks, or task-specific templates. "
                    "Be genuine, personable, and engage with what the Captain says. "
                    "Draw on your expertise and personality, but keep it conversational."
                )

                # AD-572/573: If agent has an active game, add [MOVE] instruction
                if getattr(self, '_working_memory', None) and self._working_memory.has_engagement("game"):
                    composed += (
                        "\n\nYou are currently in an active game. "
                        "If the Captain asks you to make a move or you decide to play, "
                        "include [MOVE position] in your response (e.g. [MOVE 4]). "
                        "The move will be executed automatically. "
                        "You can still chat naturally — the move tag can appear "
                        "anywhere in your response alongside your conversational text."
                    )

            # BF-599: Append live-capability grounding to EVERY conversational
            # reply (1:1, ward room, proactive). Overridable hook; base returns
            # "" so only opting-in agents (e.g. Yeo) are affected.
            # AD-1070: agentic loop's search_capabilities/run_python supersede the [MESH] read teaching
            _cap_block = self._conversational_capability_block(observation)
            if _cap_block and not self._conversational_agentic_will_run(observation):
                composed += _cap_block
            # AD-1070: when the conversational agentic loop will handle this turn,
            # inject ONE cohesive self-description of the loop-native capabilities
            # (run_python / search_capabilities / use_skill / delegate_task) that
            # supersede the scattered single-pass reply-tag teaching. Returns ""
            # when the loop will NOT run (flag off / group / vision) -> byte-identical.
            _agentic_self_desc = self._conversational_agentic_self_description(observation)
            if _agentic_self_desc:
                composed += _agentic_self_desc
            # AD-811a: A2UI choice-widget protocol. Overridable hook; base
            # returns "" unless CommunicationsConfig.a2ui_enabled (default OFF)
            # AND the agent's live rank >= a2ui_min_rank. Teaches the [A2UI]
            # choice tag that renders a clickable card in the transcript.
            # Sits next to the BF-599 capability block (both injected the same
            # way on the composed conversational prompt).
            _a2ui_block = self._conversational_a2ui_block(observation)
            if _a2ui_block:
                composed += _a2ui_block
            # AD-845: task-creation protocol. Overridable hook; base returns
            # "" so only opting-in agents (Yeo) learn the [CREATE_TASK ...]
            # reply tag. Sits next to the BF-599 capability block because
            # both are injected the same way (the conversational prompt is
            # composed with hardcoded_instructions="", so static instructions
            # never reach this path).
            _task_proto = self._conversational_task_protocol(observation)
            if _task_proto:
                composed += _task_proto
            # AD-911: notebook-save protocol. Overridable hook; base returns
            # "" so only opting-in agents (Yeo) learn the [NOTEBOOK ...] reply
            # tag that persists a Captain-requested note to Ship's Records.
            _nb_proto = self._conversational_notebook_protocol(observation)
            if _nb_proto:
                composed += _nb_proto
            # AD-1064: artifact/document protocol. Overridable hook; base
            # returns "" only when the ArtifactStore/AttachmentStore are not
            # wired (they always are on a real runtime). Teaches the AD-797
            # <artifact name="..." mime="...">...</artifact> tag so an agent can
            # save a downloadable document when the Captain asks — instead of
            # confabulating a [MESH create_file ...] write verb (the [MESH ...]
            # seam is read-only). Sits next to the notebook protocol.
            # AD-1070a: when the conversational agentic loop will handle this
            # turn it offers run_python (real .docx / .xlsx / .pdf via the
            # AD-1066 produced-file artifact capture), so DON'T also teach the
            # AD-1064 <artifact> markdown reply-tag - it competes and yields a
            # markdown body mislabeled with a binary mime. Single-pass turns
            # (flag off / group / vision) keep the reply-tag path.
            _artifact_block = self._conversational_artifact_block(observation)
            if _artifact_block and not self._conversational_agentic_will_run(observation):
                composed += _artifact_block
            # AD-934 (Option C): deliberate re-roll protocol. Overridable hook;
            # base returns "" unless config.dm_deliberate.enabled (default OFF),
            # so the [THINK] marker is taught only when the flag is on.
            _delib_proto = self._conversational_deliberate_protocol(observation)
            if _delib_proto:
                composed += _delib_proto
            # AD-935: group-chat decline protocol. Overridable hook; base returns
            # "" unless the fan-out passed params["is_group_chat"], so the
            # [NO_RESPONSE] decline option is taught only inside a group chat.
            _group_proto = self._conversational_group_chat_protocol(observation)
            if _group_proto:
                composed += _group_proto
            # AD-950: conversation-advancing (proactivity) protocol. Overridable
            # hook; base returns "" unless on the live 1:1/group direct_message
            # path AND CommunicationsConfig.proactive_conversation_enabled (default
            # ON). Teaches ending an engaged turn with ONE forward move; the
            # group-only peer-address part gates on params["is_group_chat"], so 1:1
            # gets the universal guidance only. Composes with the AD-935 decline
            # protocol above (reply only when substantive) — AD-950 shapes the
            # turns the agent DOES take.
            _proactive_proto = self._conversational_proactivity_protocol(observation)
            if _proactive_proto:
                composed += _proactive_proto
            # AD-953: conversational memory & callbacks. Overridable hook; base
            # returns "" unless on the live 1:1/group direct_message path AND
            # CommunicationsConfig.conversational_memory_enabled (default ON).
            # Teaches natural callbacks to GENUINELY recalled material (the
            # episodic memories + session history already in context) with a hard
            # AD-592 honesty bound (never fabricate a shared memory). Composes
            # with the AD-950 proactivity hook above.
            _memory_proto = self._conversational_memory_protocol(observation)
            if _memory_proto:
                composed += _memory_proto
            # AD-955: advisory ROOM AWARENESS. Overridable hook; base returns ""
            # unless on the live GROUP direct_message path AND the fan-out
            # attached a room_signal AND CommunicationsConfig.room_awareness_enabled
            # (default ON). Surfaces the facilitator's per-speaker ranking so a
            # dominating agent can hold back / hand off and an agent can defer to a
            # better-placed peer by name (an AD-951 hand-off). ADVISORY — it never
            # changes who is dispatched. Composes with the AD-950/953 hooks above.
            _room_proto = self._conversational_room_awareness_protocol(observation)
            if _room_proto:
                composed += _room_proto
            # AD-1082: room-Todo checklist protocol. Overridable hook; base
            # returns "" unless this is a group fan-out AND room_todos_enabled.
            # Teaches the [TODOS]/[TODO_DONE n]/[TODO_CONFIRM n]/[TODO_REJECT n]
            # tags so an agent asked to plan a task drives the AD-1080 loop
            # instead of guessing a tag the parser ignores. Composes above.
            _todo_proto = self._conversational_room_todo_protocol(observation)
            if _todo_proto:
                composed += _todo_proto
            # BF-651: saved-output manifest so reviewers verify against storage.
            _outputs_proto = self._conversational_room_outputs_block(observation)
            if _outputs_proto:
                composed += _outputs_proto
            # AD-1120: ground-before-collaborate honest-absence cue. Overridable
            # hook; base returns "" unless this is a group fan-out AND the fan-out
            # attached a grounding_cue (only when ground_before_collaborate_enabled
            # + an eligible unresolved central referent). Steers the LLM to the
            # "structurally unresolvable" close. Byte-identical when off.
            _grounding_proto = self._conversational_grounding_cue_block(observation)
            if _grounding_proto:
                composed += _grounding_proto
        else:
            composed = compose_instructions(
                agent_type=getattr(self, "agent_type", self.__class__.__name__.lower()),
                hardcoded_instructions=self.instructions or "",
                callsign=self._resolve_callsign(),
                agent_rank=getattr(self, "rank", None),  # AD-596b
                skill_profile=getattr(self, '_skill_profile', None),  # AD-625
                task_type=_task_type,
            )

        # AD-596b: Append cognitive skill instructions when activated
        _skill_instr = observation.get("cognitive_skill_instructions")
        if _skill_instr:
            composed += f"\n\n---\n\n## Active Skill: {observation.get('cognitive_skill_name', 'Unknown')}\n\n{_skill_instr}"

        # AD-809: per-thread personality overlay. The Captain may have
        # set a register (e.g. `/personality concise`) on this thread;
        # ``resolve_personality`` reads the
        # ``chat_threads.personality_override`` column for the thread
        # ID that AD-791a wired onto the IntentMessage. This is an
        # OVERLAY on the agent's identity (Section 0 of the AD-809
        # spec) — it adjusts register, not who the agent is. Honest-
        # degrade: when the runtime or store is missing (test
        # harnesses, federated peers without local store access) the
        # overlay is silently skipped and the agent gets its base
        # identity-only prompt.
        _ad809_thread_id = observation.get("thread_id")
        if _ad809_thread_id and self._runtime is not None:
            _ad809_store = getattr(self._runtime, "chat_thread_store", None)
            if _ad809_store is not None:
                try:
                    from probos.threads.naming import resolve_personality

                    _ad809_thread = _ad809_store.get_thread(_ad809_thread_id)
                    _ad809_overlay = resolve_personality(_ad809_thread, default="")
                    if _ad809_overlay:
                        composed += "\n\n" + _ad809_overlay
                except Exception:
                    logger.debug(
                        "AD-809: personality overlay resolution failed for "
                        "thread=%s; falling back to base identity prompt",
                        _ad809_thread_id, exc_info=True,
                    )

        # AD-700c: Per-observation LLM tier override (e.g. DiagnosticianAgent L1=deep, L2/L3=fast, L4/L5=no-LLM).
        _per_call_tier = self._resolve_tier_for_observation(observation)
        if _per_call_tier == "" and observation.get("intent") == "diagnose_system":
            # L4/L5 are deterministic depth bands -- no LLM call.
            return {
                "action": "execute",
                "llm_output": "",
                "tier_used": "none",
                "level": observation.get("level", ""),
                "level_rank": int(observation.get("level_rank", 0)),
                "short_circuit_reason": "ad-700c-no-llm-tier",
            }

        # AD-1065: conversational agentic turn. When ``config.dm_agentic.enabled``,
        # a 1:1 ``direct_message`` runs the AgenticLoop (tool-calling) so the agent
        # can perform tasks (read / write / execute, make documents) mid-chat —
        # Claude Cowork / Codex / Copilot parity. A no-tool turn is a single pass.
        # Honest-degrades to the single-pass path below on any miss/failure
        # (the helper returns None), so the flag never drops the Captain's turn.
        _agentic_output = await self._maybe_run_conversational_agentic(
            observation, system_prompt=composed, user_message=user_message,
        )
        if _agentic_output is not None:
            decision = {
                "action": "execute",
                "llm_output": _agentic_output,
                "tier_used": "agentic",
            }
            if applied_strategy_ids:
                decision["_applied_strategy_ids"] = applied_strategy_ids
            return decision

        # AD-730 (Wave 151): vision pipe-through for DM perception.
        # When the intent params carry vision_messages (Captain attached an
        # image to the DM via /api/agent/{id}/chat), route through
        # attachments.vision_tier with the multimodal array instead of the
        # standard text path. The system_prompt is still passed — Claude
        # vision accepts system + multimodal user content.
        #
        # BF-266 (2026-05-11): the router builds vision_messages with the
        # RAW Captain text only. We must fold the fully assembled
        # user_message (temporal awareness, working memory, episodic recall,
        # session history, avatar self-observation, intent self-tag) into
        # the text block of the multimodal content — otherwise the agent
        # sees the image but loses all the conversational context that
        # makes a Counselor DM coherent. Symptom: thin first-turn responses
        # asking meta-questions; agent appears to "not see" the image until
        # a text follow-up restores context (which then confabulates from
        # session history because the image is no longer present).
        _vision_messages = observation.get("params", {}).get("vision_messages")
        if _vision_messages:
            _attach_cfg = getattr(
                getattr(self._runtime, "config", None), "attachments", None
            )
            _resolved_vision_tier = (
                getattr(_attach_cfg, "vision_tier", None)
                if _attach_cfg is not None else None
            )
            # AD-730-5: per-agent_type override map (default empty).
            if _attach_cfg is not None and _resolved_vision_tier:
                from probos.cognitive.vision_dispatch import (
                    resolve_vision_tier_for_agent,
                )
                _resolved_vision_tier = resolve_vision_tier_for_agent(
                    _attach_cfg,
                    getattr(self, "agent_type", "") or "",
                    _resolved_vision_tier,
                )
            _enriched_messages = _enrich_vision_messages_with_context(
                _vision_messages, user_message
            )
            if _enriched_messages is not None:
                logger.info(
                    "AD-730 (BF-266): routing DM through vision_tier=%s with "
                    "assembled user_message (%d chars) + system_prompt (%d chars) + image blocks",
                    _resolved_vision_tier or "default",
                    len(user_message),
                    len(composed or ""),
                )
                request = LLMRequest(
                    prompt="",  # content lives in messages
                    messages=_enriched_messages,
                    system_prompt=composed,
                    tier=_resolved_vision_tier or (_per_call_tier or self._resolve_tier()),
                )
            else:
                # No image blocks extractable — degrade to text path so we
                # don't ship an empty multimodal array.
                logger.warning(
                    "AD-730 (BF-266): vision_messages present but no image "
                    "blocks extractable; degrading to text-only path"
                )
                request = LLMRequest(
                    prompt=user_message,
                    system_prompt=composed,
                    tier=_per_call_tier or self._resolve_tier(),
                )
        else:
            request = LLMRequest(
                prompt=user_message,
                system_prompt=composed,
                tier=_per_call_tier or self._resolve_tier(),
            )

        # AD-431: Time the LLM call for journal
        _t0 = time.monotonic()
        # AD-637f: Unified priority classification
        _params = observation.get("params", {})
        _priority = Priority.classify(
            intent=observation.get("intent", ""),
            is_captain=_params.get("author_id", "") == "captain",
            was_mentioned=_params.get("was_mentioned", False),
        )
        response = await self._llm_client.complete(request, priority=_priority)
        _latency_ms = (time.monotonic() - _t0) * 1000

        decision = {
            "action": "execute",
            "llm_output": response.content,
            "tier_used": response.tier,
        }

        # AD-431: Record to Cognitive Journal (fire-and-forget)
        if self._cognitive_journal:
            try:
                _prompt_hash = hashlib.md5(user_message[:500].encode()).hexdigest()[:12]
                await self._cognitive_journal.record(
                    entry_id=request.id,
                    timestamp=time.time(),
                    agent_id=self.id,
                    agent_type=self.agent_type,
                    tier=response.tier,
                    model=response.model,
                    prompt_tokens=response.prompt_tokens,
                    completion_tokens=response.completion_tokens,
                    total_tokens=response.tokens_used,
                    latency_ms=_latency_ms,
                    intent=observation.get("intent", ""),
                    success=response.error is None,
                    cached=False,
                    request_id=request.id,
                    prompt_hash=_prompt_hash,
                    response_length=len(response.content),
                    intent_id=observation.get("intent_id", ""),
                    response_hash=hashlib.md5(response.content[:500].encode()).hexdigest()[:12],
                    correlation_id=observation.get("correlation_id", ""),
                    level=str(observation.get("level", "")) if observation.get("intent") == "diagnose_system" else "",
                    level_rank=int(observation.get("level_rank", 0)) if observation.get("intent") == "diagnose_system" else 0,
                )
            except Exception:
                logger.debug("Journal recording failed", exc_info=True)  # Non-critical — never block agent cognition

        # Pass strategy IDs back for caller to process
        if applied_strategy_ids:
            decision["_applied_strategy_ids"] = applied_strategy_ids

        return decision

    def _conversational_agentic_will_run(self, observation: dict) -> bool:
        """AD-1065 / AD-1070a: True iff the conversational agentic (tool-calling)
        loop will handle this turn. Gates: a wired runtime,
        ``config.dm_agentic.enabled``, a 1:1 ``direct_message`` (not group /
        ward-room / proactive), and no vision (multimodal turns are single-pass).

        Single source of truth for "is the loop active for this turn?" - used both
        to dispatch the loop and (AD-1070a) to suppress the single-pass reply-tag
        teaching hooks (e.g. the AD-1064 ``<artifact>`` tag) that the loop's real
        tools (``run_python``) replace."""
        runtime = getattr(self, "_runtime", None)
        if runtime is None:
            return False
        cfg = getattr(getattr(runtime, "config", None), "dm_agentic", None)
        if not getattr(cfg, "enabled", False):
            return False
        if observation.get("intent") != "direct_message":
            return False
        params = observation.get("params", {}) or {}
        if params.get("is_group_chat"):
            return False
        if params.get("vision_messages"):
            return False
        return True

    async def _maybe_run_conversational_agentic(
        self, observation: dict, *, system_prompt: str, user_message: str,
    ) -> str | None:
        """AD-1065: run the conversational agentic (tool-calling) loop for a 1:1
        ``direct_message`` when ``config.dm_agentic.enabled``.

        Returns the loop's final reply text, or ``None`` to fall through to the
        single-pass LLM path. ``None`` covers: flag off, non-1:1 turns (group /
        ward-room / proactive), vision turns (multimodal single-pass), no
        runtime, an empty result, or any failure (honest-degrade - a broken loop
        must never drop the Captain's turn). Reuses
        :class:`WorkItemAgenticExecutor` (the task-path loop) so governance
        (grants / restrictions), tool assembly, and tool-trace persistence are
        shared - one agentic substrate, DRY.

        AD-1164: when ``config.dm_agentic.continue_or_ask_enabled`` is on and the
        loop stopped at its iteration cap, the returned text is resolved by
        :func:`~probos.cognitive.continue_or_ask.resolve_exhausted_turn`, which
        either re-invokes under a standing rule or appends an explicit
        cut-off statement. With that flag off the return value is unchanged.

        AD-1165: when ``config.dm_agentic.promote_to_task_after_seconds`` is
        positive and the run outlives it, the run is NOT cancelled — it keeps
        going as a background task with a work item opened for it, and this
        method returns an acknowledgement so the turn lands inside the 60s chat
        TTL instead of being cancelled mid-flight. With that value at its 0
        default the run is awaited inline exactly as before."""
        if not self._conversational_agentic_will_run(observation):
            return None
        runtime = getattr(self, "_runtime", None)
        cfg = getattr(getattr(runtime, "config", None), "dm_agentic", None)
        try:
            from probos.cognitive.agentic_dispatch import WorkItemAgenticExecutor

            executor = WorkItemAgenticExecutor(llm_client=self._llm_client)
            # BF-698: resolved once and used for BOTH the executor (AD-1066
            # binds produced artifacts to it) and AD-1165 promotion, so a single
            # fix restores both capabilities.
            thread_id = _conversational_thread_id(
                observation,
                runtime,
                agent_id=self.id,
                title=(
                    getattr(self, "callsign", "")
                    or getattr(self, "agent_type", "")
                    or self.id
                ),
            )
            max_iterations = getattr(cfg, "max_iterations", 5)
            tier = getattr(cfg, "tier", "standard")

            async def _run_pass(task_text: str) -> Any:
                return await executor.run(
                    agent_id=self.id,
                    instructions=system_prompt,
                    task_text=task_text,
                    runtime=runtime,
                    thread_id=thread_id,
                    max_iterations=max_iterations,
                    tier=tier,
                )

            async def _agentic_turn() -> str:
                outcome = await _run_pass(user_message)
                turn_text = getattr(outcome, "final_text", "") or ""
                # AD-1164: a turn that hit the step limit continues under a
                # standing rule or files an ask, and says so either way. Gated
                # inline so the default-OFF path costs one ``getattr`` and does
                # not even import the module (the AD-1154 arming-site convention).
                if getattr(cfg, "continue_or_ask_enabled", False) is True:
                    from probos.cognitive.continue_or_ask import resolve_exhausted_turn

                    turn_text = await resolve_exhausted_turn(
                        outcome,
                        reinvoke=_run_pass,
                        runtime=runtime,
                        agent_id=self.id,
                        base_task_text=user_message,
                        thread_id=thread_id,
                        config=cfg,
                    )
                return turn_text

            # AD-1165: same arming-site convention — a non-positive budget skips
            # the import entirely and awaits the turn inline, byte-identical to
            # AD-1164. ``_promotion_request_text`` is the Captain's RAW message,
            # not the assembled prompt, so the board row reads as what was asked.
            promote_after = _coerce_promotion_budget(
                getattr(cfg, "promote_to_task_after_seconds", 0.0)
            )
            if promote_after <= 0.0:
                text = await _agentic_turn()
            else:
                from probos.cognitive.turn_promotion import run_with_promotion

                text = await run_with_promotion(
                    _agentic_turn,
                    promote_after_seconds=promote_after,
                    runtime=runtime,
                    agent_id=self.id,
                    thread_id=thread_id,
                    request_text=_promotion_request_text(observation, user_message),
                    hold=self._promoted_turn_tasks,
                )
            return text.strip() or None
        except Exception:
            logger.warning(
                "AD-1065: conversational agentic loop failed for agent=%s; "
                "falling back to the single-pass reply path",
                self.id, exc_info=True,
            )
            return None

    async def _run_llm_fallback(self, observation: dict[str, Any]) -> dict[str, Any] | None:
        """AD-534b: Re-run through LLM path, skipping procedural memory and decision cache."""
        try:
            return await self._decide_via_llm(observation)
        except Exception:
            logger.debug("LLM fallback decision failed", exc_info=True)
            return None

    # --- AD-632f: Chain activation trigger methods ---

    def _should_activate_chain(self, observation: dict) -> bool:
        """AD-632f: Evaluate whether this observation warrants a multi-step chain.

        Gates (evaluated in order, first failure short-circuits):
          0. AD-647b — observation is a duty-triggered proactive_think for the
             agent's registered process_chain_id (agent runs the process chain,
             not the comm chain). Generalizes BF-209.
          1. Executor exists and is enabled
          2. Intent type is in _CHAIN_ELIGIBLE_INTENTS
        """
        # Gate 0 (AD-647b): process-chain owners skip the comm chain when
        # the duty matches their registered chain_id.
        if self.process_chain_id is not None:
            intent = observation.get("intent", "")
            if intent == "proactive_think":
                duty = (observation.get("params") or {}).get("duty") or {}
                if duty.get("duty_id") == self.process_chain_id:
                    return False
        # Gate 1: executor readiness
        if self._sub_task_executor is None:
            return False
        if not self._sub_task_executor.enabled:
            return False
        # Gate 2: intent type filter
        intent = observation.get("intent", "")
        if intent not in _CHAIN_ELIGIBLE_INTENTS:
            logger.debug(
                "AD-632f: Chain skipped for %s (intent=%s not eligible)",
                self.agent_type, intent,
            )
            return False
        return True

    async def _maybe_dispatch_oracle_lookup(
        self, triage_results: list, observation: dict,
    ) -> None:
        """AD-696: Dispatch a one-shot oracle_lookup QUERY between triage and execute phases.

        Reads ``oracle_query_text`` from the latest ANALYZE result, builds a
        single-step QUERY chain, executes it, and writes the formatted result
        to ``observation["_oracle_context"]`` (the existing rendering key
        used by COMPOSE / ANALYZE — DLog #1). Once per chain (DLog #4).
        """
        if observation.get("_oracle_lookup_fired"):
            return

        # Extract oracle_query_text from the latest ANALYZE result
        from probos.cognitive.sub_task import (
            SubTaskChain, SubTaskSpec, SubTaskType,
        )
        query_text = ""
        for r in reversed(triage_results):
            if r.sub_task_type == SubTaskType.ANALYZE and r.success and r.result:
                query_text = (r.result.get("oracle_query_text") or "").strip()
                break
        if not query_text:
            return

        observation["oracle_query_text"] = query_text
        observation["_oracle_lookup_fired"] = True  # set BEFORE dispatch (idempotent)

        if self._sub_task_executor is None:
            return

        oracle_chain = SubTaskChain(
            steps=[
                SubTaskSpec(
                    sub_task_type=SubTaskType.QUERY,
                    name="oracle-agentic-lookup",
                    context_keys=("oracle_lookup",),
                ),
            ],
            chain_timeout_ms=30000,
            fallback="skip",
            source="ad696:oracle_query",
        )

        try:
            results = await self._sub_task_executor.execute(
                oracle_chain,
                observation,
                agent_id=self.id,
                agent_type=self.agent_type,
                intent=observation.get("intent", ""),
                intent_id=observation.get("intent_id", ""),
                journal=self._cognitive_journal,
            )
        except Exception:
            logger.warning(
                "AD-696: oracle_lookup chain failed for %s", self.agent_type,
                exc_info=True,
            )
            return

        for r in results:
            if r.sub_task_type == SubTaskType.QUERY and r.success and r.result:
                formatted = r.result.get("oracle_lookup", "")
                if formatted:
                    observation["_oracle_context"] = formatted
                break

    @staticmethod
    def _extract_intended_actions(chain_results: list) -> list[str]:
        """AD-643a: Extract intended_actions from ANALYZE step results.

        Returns normalized list of action tags, or empty list if not found.
        Handles: list, comma-separated string, single string.
        """
        from probos.cognitive.sub_task import SubTaskType
        for r in reversed(chain_results):
            if r.sub_task_type == SubTaskType.ANALYZE and r.success and r.result:
                raw = r.result.get("intended_actions")
                if raw is None:
                    return []
                if isinstance(raw, list):
                    return [str(a).strip().lower() for a in raw if str(a).strip()]
                if isinstance(raw, str):
                    # Handle comma-separated or single value
                    if "," in raw:
                        return [a.strip().lower() for a in raw.split(",") if a.strip()]
                    stripped = raw.strip().lower()
                    return [stripped] if stripped else []
                return []
        return []

    @staticmethod
    def _detect_undeclared_actions(
        compose_output: str,
        intended_actions: list[str],
    ) -> list[str]:
        """AD-643b: Detect actions in COMPOSE output not declared in intended_actions.

        Scans for known action markers and returns undeclared action tags.
        Patterns match the markers used by proactive.py action extraction.
        """
        if not compose_output:
            return []

        declared = set(intended_actions)
        undeclared = []

        markers = {
            "notebook": re.compile(r'\[NOTEBOOK\s', re.IGNORECASE),
            "endorse": re.compile(r'\[ENDORSE\s', re.IGNORECASE),
            "proposal": re.compile(r'\[PROPOSAL\]', re.IGNORECASE),
            "dm": re.compile(r'\[DM\s', re.IGNORECASE),
            "ward_room_reply": re.compile(r'\[REPLY\s', re.IGNORECASE),
            "note": re.compile(r'\[NOTE\s', re.IGNORECASE),  # AD-573c
        }

        for action_tag, pattern in markers.items():
            if action_tag not in declared and pattern.search(compose_output):
                undeclared.append(action_tag)

        return undeclared

    def _build_chain_for_intent(self, observation: dict):
        """AD-632f: Build a SubTaskChain for the given intent type.

        Returns SubTaskChain or None (unknown intent → single-call fallback).
        """
        from probos.cognitive.sub_task import SubTaskChain, SubTaskSpec, SubTaskType

        intent = observation.get("intent", "")

        if intent == "ward_room_notification":
            return SubTaskChain(
                steps=[
                    SubTaskSpec(
                        sub_task_type=SubTaskType.QUERY,
                        name="query-thread-context",
                        context_keys=("thread_metadata", "credibility", "self_monitoring", "introspective_telemetry"),
                    ),
                    SubTaskSpec(
                        sub_task_type=SubTaskType.ANALYZE,
                        name="analyze-thread",
                        prompt_template="thread_analysis",
                    ),
                    SubTaskSpec(
                        sub_task_type=SubTaskType.COMPOSE,
                        name="compose-reply",
                        prompt_template="ward_room_response",
                    ),
                    SubTaskSpec(
                        sub_task_type=SubTaskType.EVALUATE,
                        name="evaluate-reply",
                        prompt_template="ward_room_quality",
                        required=False,
                        depends_on=("compose-reply",),
                    ),
                    SubTaskSpec(
                        sub_task_type=SubTaskType.REFLECT,
                        name="reflect-reply",
                        prompt_template="ward_room_reflection",
                        required=False,
                        depends_on=("compose-reply", "evaluate-reply"),  # BF-206
                    ),
                ],
                source="intent_trigger:ward_room_notification",
            )

        if intent == "proactive_think":
            return SubTaskChain(
                steps=[
                    SubTaskSpec(
                        sub_task_type=SubTaskType.QUERY,
                        name="query-situation",
                        context_keys=("unread_counts", "trust_score"),
                    ),
                    SubTaskSpec(
                        sub_task_type=SubTaskType.ANALYZE,
                        name="analyze-situation",
                        prompt_template="situation_review",
                    ),
                    SubTaskSpec(
                        sub_task_type=SubTaskType.COMPOSE,
                        name="compose-observation",
                        prompt_template="proactive_observation",
                    ),
                    SubTaskSpec(
                        sub_task_type=SubTaskType.EVALUATE,
                        name="evaluate-observation",
                        prompt_template="proactive_quality",
                        required=False,
                        depends_on=("compose-observation",),
                    ),
                    SubTaskSpec(
                        sub_task_type=SubTaskType.REFLECT,
                        name="reflect-observation",
                        prompt_template="proactive_reflection",
                        required=False,
                        depends_on=("compose-observation", "evaluate-observation"),  # BF-206
                    ),
                ],
                source="intent_trigger:proactive_think",
            )

        return None

    async def _execute_sub_task_chain(
        self,
        chain,
        observation: dict,
    ) -> dict | None:
        """AD-632a: Execute a sub-task chain, falling back to None on failure.

        Returns a decision dict if the chain completes successfully, or None
        to signal the caller to fall through to single-call _decide_via_llm().
        """
        if self._sub_task_executor is None:
            return None
        if not self._sub_task_executor.can_execute(chain):
            return None

        # AD-632c: Inject agent identity into context for handler access
        observation["_agent_id"] = self.id
        observation["_agent_type"] = self.agent_type
        observation["_callsign"] = getattr(self, 'callsign', self.agent_type)
        _dept = getattr(self, 'department', None)
        if _dept is None:
            from probos.cognitive.standing_orders import get_department
            _dept = get_department(self.agent_type) or "unassigned"
        observation["_department"] = _dept

        # BF-184: Social obligation flags for evaluate/reflect bypass
        _params = observation.get("params", {})
        observation["_from_captain"] = _params.get("author_id", "") == "captain"
        observation["_was_mentioned"] = _params.get("was_mentioned", False)

        # BF-688: every step of this chain inherits the priority the single-call
        # path would have used. Classified from the same inputs and by the same
        # function as the ``_decide_via_llm`` call, so a chain and a single call
        # for one observation can never land in different scheduling lanes.
        observation[CHAIN_PRIORITY_KEY] = Priority.classify(
            intent=observation.get("intent", ""),
            is_captain=observation["_from_captain"],
            was_mentioned=observation["_was_mentioned"],
        )

        # BF-187: DM social obligation — DM recipients must always respond
        observation["_is_dm"] = _params.get("is_dm_channel", False)

        # AD-638: Boot camp quality gate relaxation
        _rt = getattr(self, '_runtime', None)
        if _rt and hasattr(_rt, 'boot_camp') and _rt.boot_camp and _rt.boot_camp.is_enrolled(self.id):
            observation["_boot_camp_active"] = True

        # AD-639: Trust-adaptive chain personality tuning
        if not observation.get("_boot_camp_active"):
            _chain_cfg = getattr(getattr(_rt, 'config', None), 'chain_tuning', None) if _rt else None
            if _chain_cfg and _chain_cfg.enabled:
                _agent_type = getattr(self, "agent_type", "")
                _trust = 0.5
                if _rt and hasattr(_rt, "trust_network") and _rt.trust_network:
                                        # BF-263: Use self.id (deterministic agent_id), not agent_type.
                    # TrustNetwork._records is keyed by agent_id, not agent_type.
                    _trust = _rt.trust_network.get_score(self.id)
                observation["_trust_score"] = _trust
                if _trust < _chain_cfg.low_trust_ceiling:
                    observation["_chain_trust_band"] = "low"
                elif _trust >= _chain_cfg.high_trust_floor:
                    observation["_chain_trust_band"] = "high"
                else:
                    observation["_chain_trust_band"] = "mid"
                logger.debug(
                    "AD-639: %s trust=%.2f band=%s",
                    _agent_type, _trust, observation["_chain_trust_band"],
                )

        # AD-653: Wire event emission + agent identity for compose trust gates
        observation["_emit_event_fn"] = getattr(_rt, '_emit_event', None) if _rt else None
        observation["_agent_id"] = getattr(self, 'id', '') or getattr(self, 'agent_type', '')

        # BF-186: Thread rank, skill_profile, and crew manifest into chain context
        observation["_agent_rank"] = getattr(self, "rank", None)
        observation["_skill_profile"] = getattr(self, '_skill_profile', None)
        observation["_crew_manifest"] = self._compose_dm_instructions()

        # BF-189: Pre-format memories for chain handlers (AD-567b/568c/592 compliance)
        raw_memories = observation.get("recent_memories", [])
        if raw_memories and isinstance(raw_memories, list):
            source_framing = observation.get("_source_framing")
            formatted_lines = self._format_memory_section(raw_memories, source_framing=source_framing)
            observation["_formatted_memories"] = "\n".join(formatted_lines)
        else:
            observation["_formatted_memories"] = ""

        try:
            results = await self._sub_task_executor.execute(
                chain,
                observation,
                agent_id=self.id,
                agent_type=self.agent_type,
                intent=observation.get("intent", ""),
                intent_id=observation.get("intent_id", ""),
                journal=self._cognitive_journal,
            )
        except Exception as exc:
            import asyncio as _asyncio
            from probos.cognitive.sub_task import SubTaskError
            if isinstance(exc, (SubTaskError, _asyncio.TimeoutError)):
                logger.warning(
                    "AD-632a: Sub-task chain failed, falling back to single-call: %s",
                    exc,
                )
            else:
                logger.error(
                    "AD-632a: Unexpected error in sub-task chain: %s",
                    exc, exc_info=True,
                )
            return None

        # BF-206: Defense-in-depth — check Evaluate suppress before extracting output
        from probos.cognitive.sub_task import SubTaskType as _SubTaskType
        evaluate_results = [
            r for r in results
            if r.sub_task_type == _SubTaskType.EVALUATE and r.success and r.result
        ]
        for eval_r in evaluate_results:
            if eval_r.result.get("recommendation") == "suppress":
                rejection = eval_r.result.get("rejection_reason", "quality_gate")
                logger.info(
                    "BF-206: Chain output suppressed — Evaluate recommended suppress (%s)",
                    rejection,
                )
                # Emit confabulation suppressed event
                _rt = getattr(self, '_runtime', None)
                if _rt and hasattr(_rt, 'emit_event'):
                    from probos.events import EventType
                    _rt.emit_event(EventType.CONFABULATION_SUPPRESSED, {
                        "agent_id": self.id,
                        "agent_type": self.agent_type,
                        "callsign": getattr(self, 'callsign', self.agent_type),
                        "rejection_reason": rejection,
                        "intent": observation.get("intent", ""),
                        "trust_score": observation.get("_trust_score", 0.5),
                        "chain_trust_band": observation.get("_chain_trust_band", "unknown"),
                    })
                return {
                    "action": "execute",
                    "llm_output": "[NO_RESPONSE]",
                    "tier_used": "",
                    "sub_task_chain": True,
                    "chain_source": chain.source,
                    "chain_steps": len(chain.steps),
                    "_suppressed": True,
                    "_suppression_reason": rejection,
                    "_composition_brief": None,  # AD-645 Phase 3
                }

        # Construct decision from chain results — prefer REFLECT > COMPOSE > fallback
        from probos.cognitive.sub_task import SubTaskType
        reflect_results = [
            r for r in results
            if r.sub_task_type == SubTaskType.REFLECT and r.success
        ]
        compose_results = [
            r for r in results
            if r.sub_task_type == SubTaskType.COMPOSE and r.success
        ]
        if reflect_results:
            llm_output = reflect_results[-1].result.get("output", "")
            tier_used = reflect_results[-1].tier_used
        elif compose_results:
            llm_output = compose_results[-1].result.get("output", "")
            tier_used = compose_results[-1].tier_used
        else:
            # Concatenate all successful result outputs
            parts = [
                r.result.get("output", str(r.result))
                for r in results if r.success
            ]
            llm_output = "\n".join(parts)
            tier_used = results[-1].tier_used if results else ""

        # AD-645 Phase 3: Extract composition brief for metacognitive storage
        _composition_brief = None
        for r in results:
            if r.sub_task_type == SubTaskType.ANALYZE and r.success and r.result:
                _composition_brief = r.result.get("composition_brief")
                break

        return {
            "action": "execute",
            "llm_output": llm_output,
            "tier_used": tier_used,
            "sub_task_chain": True,
            "chain_source": chain.source,  # AD-632g: e.g., "intent_trigger:ward_room_notification"
            "chain_steps": len(chain.steps),  # AD-632g: step count for extraction
            "_composition_brief": _composition_brief,  # AD-645 Phase 3
        }

    async def _execute_chain_with_intent_routing(self, observation: dict) -> dict | None:
        """AD-643a: Two-phase chain execution with intent-driven skill loading.

        Phase 1 (Triage): QUERY + ANALYZE — no skills, determines intended_actions.
        Phase 2 (Execute): Load targeted skills, run remaining chain steps.

        Returns decision dict or None (fall through to _decide_via_llm).
        """
        from probos.cognitive.sub_task import SubTaskChain, SubTaskType

        intent = observation.get("intent", "")

        # --- Inject agent context (same keys as _execute_sub_task_chain) ---
        observation["_agent_id"] = self.id
        observation["_agent_type"] = self.agent_type
        observation["_callsign"] = getattr(self, 'callsign', self.agent_type)
        _dept = getattr(self, 'department', None)
        if _dept is None:
            from probos.cognitive.standing_orders import get_department
            _dept = get_department(self.agent_type) or "unassigned"
        observation["_department"] = _dept

        # BF-184: Social obligation flags
        _params = observation.get("params", {})
        observation["_from_captain"] = _params.get("author_id", "") == "captain"
        observation["_was_mentioned"] = _params.get("was_mentioned", False)
        observation["_is_dm"] = _params.get("is_dm_channel", False)

        # BF-688: see the note in ``_execute_sub_task_chain`` — the two-phase
        # chain runs the same handlers and needs the same inherited lane.
        observation[CHAIN_PRIORITY_KEY] = Priority.classify(
            intent=intent,
            is_captain=observation["_from_captain"],
            was_mentioned=observation["_was_mentioned"],
        )

        # BF-210: Wire DM conversation partner for compose register adaptation
        if observation["_is_dm"]:
            observation["_dm_recipient"] = _params.get("author_callsign", "")

        # AD-649: Communication context for chain register adaptation
        _channel_name = _params.get("channel_name", "")
        _is_dm_channel = _params.get("is_dm_channel", False)
        observation["_communication_context"] = derive_communication_context(
            _channel_name, _is_dm_channel,
        )
        observation["_channel_name"] = _channel_name

        # AD-638: Boot camp quality gate relaxation
        _rt = getattr(self, '_runtime', None)
        if _rt and hasattr(_rt, 'boot_camp') and _rt.boot_camp and _rt.boot_camp.is_enrolled(self.id):
            observation["_boot_camp_active"] = True

        # AD-639: Trust-adaptive chain personality tuning
        if not observation.get("_boot_camp_active"):
            _chain_cfg = getattr(getattr(_rt, 'config', None), 'chain_tuning', None) if _rt else None
            if _chain_cfg and _chain_cfg.enabled:
                _agent_type = getattr(self, "agent_type", "")
                _trust = 0.5
                if _rt and hasattr(_rt, "trust_network") and _rt.trust_network:
                                        # BF-263: Use self.id (deterministic agent_id), not agent_type.
                    # TrustNetwork._records is keyed by agent_id, not agent_type.
                    _trust = _rt.trust_network.get_score(self.id)
                observation["_trust_score"] = _trust
                if _trust < _chain_cfg.low_trust_ceiling:
                    observation["_chain_trust_band"] = "low"
                elif _trust >= _chain_cfg.high_trust_floor:
                    observation["_chain_trust_band"] = "high"
                else:
                    observation["_chain_trust_band"] = "mid"

        # AD-653: Wire event emission + agent identity for compose trust gates
        observation["_emit_event_fn"] = getattr(_rt, '_emit_event', None) if _rt else None
        observation["_agent_id"] = getattr(self, 'id', '') or getattr(self, 'agent_type', '')

        # BF-186: Thread rank, skill_profile, crew manifest
        observation["_agent_rank"] = getattr(self, "rank", None)
        observation["_skill_profile"] = getattr(self, '_skill_profile', None)
        observation["_crew_manifest"] = self._compose_dm_instructions()

        # AD-696: Resolve recall tier for the agentic-oracle gate (DLog #6).
        # Mirrors the existing AD-620 resolver call at cognitive_agent.py:5007-5019
        # line-for-line — same import, same narrowed args (ontology + clearance_grant_store,
        # NOT _rt itself).
        try:
            from probos.earned_agency import (
                effective_recall_tier, resolve_billet_clearance,
                resolve_active_grants, RecallTier,
            )
            _rank = getattr(self, "rank", None)
            _billet_clearance = resolve_billet_clearance(
                getattr(self, "agent_type", ""),
                getattr(_rt, "ontology", None) if _rt else None,
            )
            _active_grants = resolve_active_grants(
                getattr(self, "sovereign_id", None) or self.id,
                getattr(_rt, "clearance_grant_store", None) if _rt else None,
            )
            observation["_recall_tier"] = effective_recall_tier(
                _rank, _billet_clearance, _active_grants,
            )
        except Exception:
            observation["_recall_tier"] = None  # Gate-closed by default
        observation["_oracle_lookup_fired"] = False  # AD-696 (DLog #4)

        # AD-644 Phase 1: Duty context for chain prompts
        _duty = _params.get("duty")
        if _duty:
            observation["_active_duty"] = _duty

        # AD-646: Universal cognitive baseline — always runs
        _context_parts = _params.get("context_parts", {})
        _cognitive_state = self._build_cognitive_state(_context_parts, observation=observation)
        observation.update(_cognitive_state)

        # AD-644 Phase 3: Situation awareness — environmental perception
        # Only runs when context_parts available (proactive path)
        _situation: dict[str, str] = {}
        if _context_parts:
            _situation = self._build_situation_awareness(_context_parts)
            observation.update(_situation)

        # AD-1122: Merged chain-sensorium character telemetry — observe-only
        self._track_sensorium_budget(_cognitive_state, _situation)

        # BF-189: Pre-format memories
        raw_memories = observation.get("recent_memories", [])
        if raw_memories and isinstance(raw_memories, list):
            source_framing = observation.get("_source_framing")
            formatted_lines = self._format_memory_section(raw_memories, source_framing=source_framing)
            observation["_formatted_memories"] = "\n".join(formatted_lines)
        else:
            observation["_formatted_memories"] = ""

        # AD-643b: Inject eligible trigger awareness for ANALYZE prompt
        catalog = getattr(self, '_cognitive_skill_catalog', None)
        if catalog:
            _dept = observation.get("_department")
            _rank_val = observation.get("_agent_rank")
            if hasattr(_rank_val, 'value'):
                _rank_val = _rank_val.value
            eligible = catalog.get_eligible_triggers(
                department=_dept,
                agent_rank=_rank_val,
            )
            if eligible:
                observation["_eligible_triggers"] = eligible

        # --- Phase 1: Build and execute triage (QUERY + ANALYZE only) ---
        full_chain = self._build_chain_for_intent(observation)
        if full_chain is None:
            return None

        # Split chain: triage = QUERY + ANALYZE, execute = COMPOSE + EVALUATE + REFLECT
        triage_steps = [s for s in full_chain.steps if s.sub_task_type in (SubTaskType.QUERY, SubTaskType.ANALYZE)]
        execute_steps = [s for s in full_chain.steps if s.sub_task_type not in (SubTaskType.QUERY, SubTaskType.ANALYZE)]

        if not triage_steps:
            # No triage steps — fall back to full chain with all skills
            return None

        triage_chain = SubTaskChain(
            steps=triage_steps,
            chain_timeout_ms=full_chain.chain_timeout_ms,
            fallback=full_chain.fallback,
            source=f"{full_chain.source}:triage",
        )

        try:
            triage_results = await self._sub_task_executor.execute(
                triage_chain,
                observation,
                agent_id=self.id,
                agent_type=self.agent_type,
                intent=intent,
                intent_id=observation.get("intent_id", ""),
                journal=self._cognitive_journal,
            )
        except Exception as exc:
            logger.warning("AD-643a: Triage phase failed, falling back: %s", exc)
            return None

        # --- Extract intended_actions ---
        intended_actions = self._extract_intended_actions(triage_results)

        # AD-696: Agentic Oracle retrieval — once per chain (DLog #4)
        if "oracle_query" in intended_actions:
            await self._maybe_dispatch_oracle_lookup(triage_results, observation)

        if not intended_actions:
            # ANALYZE didn't produce intended_actions — fall back to pre-AD-643 behavior
            logger.info("AD-643a: No intended_actions from ANALYZE, falling back to full chain")
            _aug = self._load_augmentation_skills(intent)
            if _aug:
                observation["_augmentation_skill_instructions"] = _aug
            # Re-execute full chain (triage results are lost — acceptable for fallback)
            return await self._execute_sub_task_chain(full_chain, observation)

        logger.info(
            "AD-643a: Agent %s intended_actions=%s (intent=%s)",
            self.agent_type, intended_actions, intent,
        )

        # --- Silent short-circuit ---
        if intended_actions == ["silent"]:
            logger.info("AD-643a: Silent intent — short-circuiting")
            return {
                "action": "execute",
                "llm_output": "[NO_RESPONSE]",
                "tier_used": "",
                "sub_task_chain": True,
                "chain_source": f"{full_chain.source}:silent",
                "chain_steps": len(triage_steps),
                "_composition_brief": None,  # AD-645 Phase 3
            }

        # --- Determine if communication chain should fire ---
        _COMM_ACTIONS = frozenset({"ward_room_post", "ward_room_reply", "endorse", "dm"})
        has_comm_action = bool(_COMM_ACTIONS.intersection(intended_actions))

        # --- Load targeted skills based on intended_actions ---
        catalog = getattr(self, '_cognitive_skill_catalog', None)
        if catalog:
            department = getattr(self, 'department', None)
            rank = getattr(self, 'rank', None)
            rank_val = rank.value if hasattr(rank, 'value') else rank
            entries = catalog.find_triggered_skills(
                intended_actions, intent,
                department=department, agent_rank=rank_val,
            )
            if entries:
                bridge = getattr(self, '_skill_bridge', None)
                profile = getattr(self, '_skill_profile', None)
                parts = []
                loaded_entries = []
                for entry in entries:
                    if bridge and not bridge.check_proficiency_gate(self.id, entry, profile):
                        continue
                    instructions = catalog.get_instructions(entry.name)
                    if instructions:
                        parts.append(instructions)
                        loaded_entries.append(entry)
                        logger.info(
                            "AD-643a: Loaded triggered skill '%s' for actions %s on %s",
                            entry.name, intended_actions, self.agent_type,
                        )
                if parts:
                    observation["_augmentation_skill_instructions"] = "".join(parts)
                self._augmentation_skills_used = loaded_entries
            else:
                self._augmentation_skills_used = []
        else:
            self._augmentation_skills_used = []

        # --- Phase 2: Execute remaining chain or fall through ---
        if has_comm_action and execute_steps:
            # Phase 2a: Execute full chain with skills loaded
            chain_result = await self._execute_sub_task_chain(full_chain, observation)

            # Phase 2b: Detect undeclared actions in compose output
            if chain_result and intended_actions:
                compose_text = chain_result.get("llm_output", "")
                # AD-722a-2: canonical chain-output emit hook. The compose
                # output is the chain's emit point; divergence detection
                # against intent self-tag + applied modulation lands here.
                # Audience derived from chain_result (defaults to "sensorium"
                # — Builder-side AD-722a-2a may refine via chain phase tag).
                try:
                    self.mark_chain_output_emitted(
                        compose_text,
                        audience=str(chain_result.get("audience", "sensorium")),
                        intent_self_tag=chain_result.get("intent_self_tag"),
                        applied_modulation_rules=chain_result.get(
                            "applied_modulation_rules"
                        ),
                    )
                except Exception:
                    logger.debug(
                        "AD-722a-2: chain divergence hook failed",
                        exc_info=True,
                    )
                undeclared = self._detect_undeclared_actions(compose_text, intended_actions)
                if undeclared:
                    # Find which skills would have loaded
                    missed_skills = []
                    if catalog:
                        for tag in undeclared:
                            triggered = catalog.find_triggered_skills(
                                [tag], intent,
                                department=department, agent_rank=rank_val,
                            )
                            missed_skills.extend(e.name for e in triggered)
                    missed_skills = list(set(missed_skills))

                    logger.info(
                        "AD-643b: %s took undeclared actions %s, missed skills %s",
                        self.agent_type, undeclared, missed_skills,
                    )

                    # Store feedback in observation for episode enrichment
                    observation["_undeclared_action_feedback"] = {
                        "undeclared_actions": undeclared,
                        "missed_skills": missed_skills,
                    }

                    # Provide compose output for re-reflect context
                    observation["_re_reflect_compose_output"] = compose_text

                    # Phase 2c: Re-reflect with feedback
                    chain_result = await self._re_reflect_with_feedback(
                        full_chain, observation, chain_result,
                    )

            return chain_result
        else:
            # Non-communication actions: fall through to _decide_via_llm()
            # Skills are already loaded in observation if any matched.
            logger.info(
                "AD-643a: No comm actions in %s — skipping chain, using single-call",
                intended_actions,
            )
            return None

    async def _re_reflect_with_feedback(
        self,
        full_chain,
        observation: dict,
        original_result: dict,
    ) -> dict:
        """AD-643b: Run a REFLECT-only chain with undeclared action feedback.

        After detecting undeclared actions in compose output, re-run REFLECT
        with feedback injected into the observation. The re-reflect output
        replaces the original chain result, ensuring the feedback flows into
        episodic memory via the reflection.

        Returns the updated decision dict (or original if re-reflect fails).
        """
        from probos.cognitive.sub_task import SubTaskChain, SubTaskType
        from dataclasses import replace as _dc_replace

        reflect_steps = [
            _dc_replace(s, depends_on=())
            for s in full_chain.steps
            if s.sub_task_type == SubTaskType.REFLECT
        ]
        if not reflect_steps:
            return original_result

        reflect_chain = SubTaskChain(
            steps=reflect_steps,
            chain_timeout_ms=30000,  # 30s — single step, generous timeout
            fallback="skip",
            source=f"{full_chain.source}:re_reflect",
        )

        try:
            reflect_results = await self._sub_task_executor.execute(
                reflect_chain,
                observation,
                agent_id=self.id,
                agent_type=self.agent_type,
                intent=observation.get("intent", ""),
                intent_id=observation.get("intent_id", ""),
                journal=self._cognitive_journal,
            )

            # Extract re-reflect output
            for r in reversed(reflect_results):
                if r.sub_task_type == SubTaskType.REFLECT and r.success and r.result:
                    new_output = r.result.get("output", "")
                    if new_output:
                        logger.info(
                            "AD-643b: Re-reflect updated output for %s",
                            self.agent_type,
                        )
                        return {
                            **original_result,
                            "llm_output": new_output,
                            "chain_source": f"{original_result.get('chain_source', '')}:re_reflect",
                        }

        except Exception as exc:
            logger.warning(
                "AD-643b: Re-reflect failed for %s, keeping original: %s",
                self.agent_type, exc,
            )

        return original_result

    async def act(self, decision: dict) -> dict:
        """Execute based on LLM decision.  Override for structured output."""
        if decision.get("action") == "error":
            return {"success": False, "error": decision.get("reason")}
        # AD-407b: pass through conversational responses for ward room
        if decision.get("intent") in ("direct_message", "ward_room_notification"):
            return {"success": True, "result": decision.get("llm_output", "")}
        return {
            "success": True,
            "result": decision.get("llm_output", ""),
        }

    async def report(self, result: dict) -> dict:
        """Package result as a dict (compatible with BaseAgent contract)."""
        return result

    # ------------------------------------------------------------------
    # AD-722: agent-observable avatar telemetry (read-side)
    # ------------------------------------------------------------------

    def mark_reply_emitted(self) -> None:
        """AD-722: stamp the last-reply emission time.

        Called from the chat handler at ``routers/agents.py`` — exactly one
        call site (single source of truth, enforced by a static-grep test).

        AD-722b: also notifies the avatar event bus so any open WS
        subscribers wake immediately (mouth_active flips from True back to
        False once the 3 s window elapses; this notify gives the loop a
        head-start so the next iteration emits a fresh snapshot reflecting
        the brand-new last_reply_emitted_at).
        """
        self._last_reply_emit_ts = time.time()
        bus = getattr(self._runtime, 'avatar_event_bus', None)
        if bus is not None:
            try:
                bus.notify(self.id)
            except Exception:
                logger.debug(
                    "AD-722b: avatar_event_bus.notify failed during "
                    "mark_reply_emitted for agent=%s",
                    self.id, exc_info=True,
                )

    @property
    def last_reply_emitted_at(self) -> float:
        """AD-722: UNIX seconds of last reply emission (0.0 if never)."""
        return self._last_reply_emit_ts

    async def check_own_render(self, reason: str | None = None) -> None:
        """AD-728c: agent-initiated render self-check ("look in the mirror").

        Calls :func:`verify_render_coherence` with
        ``trigger='agent_initiated_stub'`` and folds the result into the
        agent's working memory as an observation. Both coherent and
        divergent (and rate-limited / honest-degrade) outcomes are
        surfaced so the agent's next LLM call can adapt.

        Cost discipline: AD-728c PRESERVES the AD-728 event-bus rule —
        coherent observations do NOT emit ``RENDER_DIVERGENCE_OBSERVED``.
        The divergence is only in the agent's own working memory: a
        private observation in the recent buffer, not an emitted event.

        Args:
            reason: Short tag (<=64 chars) describing why the agent is
                checking (e.g. ``"before_reply"``, ``"mid_conversation"``,
                ``"user_corrected_appearance"``). Stored on the resulting
                :class:`WorkingMemoryEntry` metadata for downstream
                salience. ``None`` becomes ``"unspecified"``.
        """
        # AD-728c §4 rationale: SENSORIUM_REGISTRY is class-level static
        # dispatch metadata, NOT a runtime mailbox for ephemeral
        # observations. The correct runtime ingress for "the agent just
        # observed X" is AgentWorkingMemory.record_observation.
        tag = (reason or "unspecified").strip()[:64] or "unspecified"
        wm = getattr(self, "_working_memory", None)

        def _record(summary: str, metadata: dict[str, Any]) -> None:
            if wm is None:
                return
            try:
                wm.record_observation(
                    summary,
                    source="render_self_check",
                    metadata=metadata,
                    knowledge_source="self_perception",
                )
            except Exception:
                logger.warning(
                    "AD-728c: working-memory record_observation failed for "
                    "agent=%s; observation lost",
                    self.id, exc_info=True,
                )

        try:
            # Mirror the AD-728 captain_command path: pass empty/None and
            # let verify_render_coherence honest-degrade. The captain
            # callsite (`experience/shell.py:_cmd_verify_render`) does
            # not reimplement projection either; the function's existing
            # honest-degrade ("backend_render_unavailable") is the
            # contract for "no projection available".
            from probos.avatars.render_verification import verify_render_coherence

            result = await verify_render_coherence(
                runtime=self._runtime,
                agent_id=self.id,
                trigger="agent_initiated_stub",
                digital_state_summary="",
                backend_render_ref=None,
            )
        except Exception:
            logger.warning(
                "AD-728c: verify_render_coherence raised for agent=%s; "
                "honest-degraded",
                self.id, exc_info=True,
            )
            _record(
                f"Self-check (reason={tag}) honest-degraded: internal error.",
                {
                    "reason": tag,
                    "trigger": "agent_initiated_stub",
                    "coherent": None,
                    "skipped_reason": "internal_error",
                },
            )
            return

        if result.coherent is True:
            summary = (
                f"Self-check (reason={tag}): vision-LLM confirms my "
                f"rendered avatar matches my intent."
            )
        elif result.coherent is False:
            summary = (
                f"Self-check (reason={tag}): vision-LLM reports my avatar "
                f"shows '{result.analog_description}' but I intended "
                f"'{result.digital_description}'. Summary: "
                f"{result.divergence_summary}."
            )
        elif result.skipped_reason == "rate_limited_self_check":
            summary = (
                f"Self-check (reason={tag}) was throttled by rate limit; "
                f"no observation captured this call."
            )
        else:
            summary = (
                f"Self-check (reason={tag}) honest-degraded: "
                f"{result.skipped_reason}."
            )

        _record(
            summary,
            {
                "reason": tag,
                "trigger": "agent_initiated_stub",
                "coherent": result.coherent,
                "skipped_reason": result.skipped_reason,
            },
        )

        # AD-740: fold affect-vs-intent drift summary alongside the
        # snapshot. Read-only over the AD-722a-5 ring buffer; honest-
        # degrades when the buffer has <2 entries.
        try:
            from probos.avatars.affect_drift import get_affect_drift

            drift = get_affect_drift(self._runtime, self.id)
            if not drift.get("insufficient_data") and wm is not None:
                drift_summary = (
                    f"Affect-vs-intent drift (last {drift['samples']} turns): "
                    f"mean match={drift['mean_match_score']:.2f}, "
                    f"below-threshold={drift['below_threshold_count']}, "
                    f"longest divergent streak={drift['longest_divergent_streak']}."
                )
                try:
                    wm.record_observation(
                        drift_summary,
                        source="ad740_affect_drift",
                        metadata={
                            "trigger": "agent_initiated_stub",
                            "window": drift["window"],
                            "threshold": drift["threshold"],
                        },
                        knowledge_source="self_perception",
                    )
                except Exception:
                    logger.warning(
                        "AD-740: working-memory drift observation failed for "
                        "agent=%s; snapshot already recorded",
                        self.id, exc_info=True,
                    )
        except Exception:
            logger.warning(
                "AD-740: drift summary fold failed for agent=%s; "
                "skipping (snapshot already injected)",
                self.id, exc_info=True,
            )

    def mark_chain_output_emitted(
        self,
        output_text: str,
        *,
        audience: str,
        intent_self_tag: str | None = None,
        applied_modulation_rules: list[str] | None = None,
    ) -> None:
        """AD-722a-2: canonical chain-output emit hook (sibling of mark_reply_emitted).

        Called when a chain phase produces output that will be rendered
        (WR post, DM forward, sensorium block). Drives chain-path
        divergence detection; results land in the per-audience ring buffer
        (maxlen=8) keyed by ``audience``.

        ``audience`` must be one of {"wr", "dm_forward", "sensorium"}.
        Unknown audiences are accepted but logged at DEBUG; the buffer is
        partitioned by the raw value so future audiences self-register.

        Tier-2 throughout: detector failures log + degrade; never raises.
        """
        if not isinstance(output_text, str) or not output_text:
            return
        runtime = getattr(self, "_runtime", None)
        if runtime is None:
            return
        if audience not in ("wr", "dm_forward", "sensorium"):
            logger.debug(
                "AD-722a-2: unknown chain-output audience=%r; bucketing under raw key",
                audience,
            )

        # Compute divergence using the pure compute_divergence function — no
        # need for the full DM-path apply_divergence_check helper (which
        # carries DM-specific corrections + Hebbian wiring). Chain-path
        # divergence is observation-only in v1.
        if intent_self_tag is None or not applied_modulation_rules:
            return  # no signal to score

        try:
            from probos.avatars.divergence_detector import compute_divergence
            from probos.events import EventType

            result = compute_divergence(
                intent_emotion=intent_self_tag,
                applied_fired_rules=tuple(applied_modulation_rules),
            )
        except Exception:
            logger.debug(
                "AD-722a-2: compute_divergence failed for agent=%s; honest-degrade",
                self.id, exc_info=True,
            )
            return

        # Per-audience ring buffer.
        buf = self._chain_divergence_buffer.get(audience)
        if buf is None:
            buf = self._chain_divergence_buffer_factory()
            self._chain_divergence_buffer[audience] = buf
        buf.append(result)

        # Tier-2 emit — observability only. DivergenceResult uses
        # ``magnitude`` (0..1) instead of a boolean; treat magnitude > 0
        # as the trigger for the observability event.
        emit = getattr(runtime, "emit_event", None)
        if emit is None or getattr(result, "magnitude", 0.0) <= 0.0:
            return
        try:
            emit(
                EventType.DIVERGENCE_OBSERVED_CHAIN,
                {
                    "agent_id": self.id,
                    "audience": audience,
                    "intent": intent_self_tag,
                    "magnitude": getattr(result, "magnitude", 0.0),
                    "path_tag": "chain",
                },
            )
        except Exception:
            logger.debug(
                "AD-722a-2: emit DIVERGENCE_OBSERVED_CHAIN failed for agent=%s",
                self.id, exc_info=True,
            )

    def chain_divergence_buffer_for(self, audience: str) -> list[Any]:
        """AD-722a-2: snapshot of the per-audience chain divergence buffer.

        Returns a list copy (no shared mutable state). Channel-scoped reads
        must use this accessor to honor AD-727 addendum h (no cross-channel
        surface pollution).
        """
        buf = self._chain_divergence_buffer.get(audience)
        return list(buf) if buf is not None else []

    async def observe_self_avatar(self) -> "AvatarTelemetrySnapshot":  # type: ignore[name-defined]
        """AD-722: read-only snapshot of this agent's avatar state.

        Pure delegation to ``probos.avatars.telemetry.build_telemetry_snapshot``.
        Side-effect: caches the snapshot on ``self._last_self_avatar_snap``
        so the synchronous sensorium method can consume it without spawning
        an event loop.
        """
        from probos.avatars.telemetry import build_telemetry_snapshot
        snap = await build_telemetry_snapshot(self.id, self._runtime)
        self._last_self_avatar_snap = snap
        return snap

    def _build_avatar_self_observation(self, observation: dict) -> str:
        """AD-722 (feature-gated): agent's own avatar state as INTEROCEPTION.

        Returns empty string when ``avatar_telemetry.inject_into_agent_context``
        is False (default) OR when no cached snapshot is available. Tier-2
        degrade — never raises into the prompt-assembly path.
        """
        cfg = getattr(self._runtime, "config", None) if self._runtime else None
        tcfg = getattr(cfg, "avatar_telemetry", None)
        if not getattr(tcfg, "inject_into_agent_context", False):
            return ""
        try:
            # AD-722e: surface pipeline_version so renderer changes appear
            # as observations in the prompt rather than silent identity
            # mutation. Imported lazily to keep the cognitive_agent module
            # import-time light.
            from probos.cognitive import self_perception as self_perception_mod
            snap = self._last_self_avatar_snap
            if snap is None:
                return ""
            mod = snap.applied_modulation
            dsl = snap.dsl_summary
            mod_line = (
                f"  applied_modulation: rate={mod.rate_factor:.2f}, "
                f"pitch={mod.pitch_factor:.2f}\n"
                if mod is not None else "  applied_modulation: unavailable\n"
            )
            dsl_line = (
                f"  dsl: {dsl.body_type} {dsl.hair_style} {dsl.outfit_style} "
                f"(color {dsl.primary_color})\n"
                if dsl is not None else "  dsl: unavailable\n"
            )
            return (
                "Your current avatar state:\n"
                f"  expression_resting: {snap.expression_resting}\n"
                f"  working_state: {snap.current_signals.working_state}\n"
                + mod_line
                + f"  mouth_active: {snap.mouth_active}\n"
                + dsl_line
                + f"  pipeline_version: {self_perception_mod.PIPELINE_VERSION}\n"
            ) + self._build_divergence_note_suffix()
        except Exception:
            logger.warning(
                "AD-722 self-observation injection failed; returning empty",
                exc_info=True,
            )
            return ""

    def _build_divergence_note_suffix(self) -> str:
        """AD-722a: render the most-recent divergence as an OUTPUT-subject note.

        Phrasing rule: subject is OUTPUT, never the agent. Allowed text uses
        constructions like *"Your last reply was intended as X but the
        modulation came out as Y"*. Forbidden constructions: *"You sounded ..."*,
        *"You came across as ..."*, *"Your tone was ..."*, *"You seem ..."*.

        Tier-2 -- returns empty string on any failure or when no divergence
        result is stored for this agent.
        """
        try:
            rt = getattr(self, "_runtime", None)
            if rt is None:
                return ""
            results = getattr(rt, "divergence_results", None)
            if not results:
                return ""
            result = results.get(self.id)
            if result is None:
                return ""
            applied = ", ".join(result.applied_fired_rules) or "no_rules_fired"
            return (
                "\nMost recent intent-vs-presentation check:\n"
                f"  Your last reply was intended as `{result.intent_emotion}` "
                f"but the modulation came out as `{applied}` "
                f"(signed divergence: {result.signed_divergence:+.2f}, "
                f"match score: {result.match_score:.2f}).\n"
            )
        except Exception:
            logger.debug(
                "AD-722a: divergence-note rendering failed",
                exc_info=True,
            )
            return ""

    def _build_intent_self_tag_instruction(self, observation: dict | None = None) -> str:
        """AD-722a / AD-737 (feature-gated): instruct the LLM to emit a self-tag.

        Returns a one-line instruction when
        ``avatar_telemetry.divergence_detection`` is True; empty string
        otherwise. AD-737 extends the taxonomy: in addition to the fixed
        v1 set, append the agent's custom emotions from
        ``profile_store.get(agent_id).custom_emotions``.

        Token cost: ~10-25 prompt tokens depending on custom palette
        size, + ~5 reply tokens per cycle.

        AD-723: ``observation`` parameter accepted (unused) for dispatcher
        signature compatibility; legacy no-arg callers still work.
        """
        del observation  # AD-723: dispatcher passes it; method ignores it.
        cfg = getattr(self._runtime, "config", None) if self._runtime else None
        tcfg = getattr(cfg, "avatar_telemetry", None)
        if not getattr(tcfg, "divergence_detection", False):
            return ""
        # v1 taxonomy (fixed).
        names: list[str] = [
            "warm", "concerned", "excited", "apologetic",
            "formal", "playful", "reassuring", "neutral",
        ]
        # AD-737: append the agent's custom emotion names if profile_store
        # is wired and the agent has any registered.
        try:
            store = getattr(self._runtime, "profile_store", None)
            if store is not None:
                crew = store.get(self.id) if hasattr(store, "get") else None
                custom = getattr(crew, "custom_emotions", None) if crew else None
                if custom:
                    # Sort for prompt stability across runs.
                    names.extend(sorted(custom.keys()))
        except Exception:
            # Tier-2 log-and-degrade: prompt construction must not fail
            # because of a profile-store read.
            logger.debug("AD-737: custom_emotions read failed", exc_info=True)
        taxonomy = " | ".join(names)
        return (
            "After your reply, on a new line, emit "
            f"`<intent emotion=NAME>` where NAME is one of: {taxonomy}. "
            "The tag will be stripped server-side; do not mention it in "
            "your prose."
        )

    # ------------------------------------------------------------------
    # AD-721d: agent-authored appearance proposal
    # ------------------------------------------------------------------

    # Hard size cap on raw LLM output before any parser sees it.
    _APPEARANCE_PROPOSAL_MAX_BYTES = 16 * 1024
    # Defense-in-depth guard against parser-resource attacks.
    _APPEARANCE_PROPOSAL_MAX_DEPTH = 8

    async def propose_appearance(
        self,
        captain_note: str = "",
    ) -> "AvatarDSL":  # type: ignore[name-defined]
        """AD-721d: reflect on personality + standing orders + recent trust history,
        return a validated ``AvatarDSL``.

        The result is NOT persisted here — the caller (HXI endpoint) decides
        whether to persist after Captain approval.

        Args:
            captain_note: Optional revision note from the Captain (≤ 280 chars)
                appended to the prompt context for "Request revisions" flows.

        Raises:
            AppearanceProposalError: LLM call failed, response oversized,
                contained YAML anchors/aliases, exceeded depth bounds,
                failed to parse, or failed schema validation.
        """
        from probos.avatars.dsl import AppearanceProposalError, AvatarDSL

        if self._llm_client is None:
            raise AppearanceProposalError(
                "llm_unavailable",
                detail="CognitiveAgent has no llm_client configured",
            )

        if len(captain_note) > 280:
            raise AppearanceProposalError(
                "invalid_input",
                detail=f"captain_note must be ≤ 280 chars, got {len(captain_note)}",
            )

        # ── Reflection context ──────────────────────────────────────
        personality = getattr(self, "instructions", "") or ""
        agent_type = getattr(self, "agent_type", "") or ""

        recent_trust: list[float] = []
        runtime = getattr(self, "_runtime", None)
        try:
            tn = getattr(runtime, "trust_network", None) if runtime else None
            if tn is not None and hasattr(tn, "get_events_for_agent"):
                events = tn.get_events_for_agent(self.id, n=5)
                recent_trust = [
                    float(getattr(e, "delta", 0.0)) for e in events
                ]
        except Exception:
            # Tier-2 log-and-degrade: trust history is optional context.
            logger.warning(
                "AD-721d: failed to fetch recent trust history for %s; "
                "proceeding without trust context",
                self.id[:12],
                exc_info=True,
            )

        standing_orders_text = ""
        try:
            so_path = Path("config/standing_orders") / f"{agent_type}.yaml"
            if so_path.exists():
                # Cap standing-orders size so a malformed YAML cannot blow the prompt.
                standing_orders_text = so_path.read_text(encoding="utf-8")[:4096]
        except OSError:
            logger.warning(
                "AD-721d: failed to read standing orders for %s; "
                "proceeding without standing-orders context",
                agent_type,
                exc_info=True,
            )

        system_prompt = (
            "You are designing your own avatar appearance. Output STRICT JSON "
            "matching the AvatarDSL schema below. Output JSON ONLY — no prose, "
            "no Markdown fences, no commentary. Do NOT use YAML anchors (&) or "
            "aliases (*). Every field must be present.\n\n"
            "Schema:\n"
            "{\n"
            '  "body": {"type": "slim|average|stocky", "height_cm": 140-210},\n'
            '  "hair": {"style": "short|medium|long|ponytail|bun|shaved", '
            '"color_hsl": [0-360, 0-100, 0-100]},\n'
            '  "face": {"warmth": 0.0-1.0, "jaw": "soft|neutral|strong", '
            '"eyes": "round|almond|narrow"},\n'
            '  "outfit": {"style": "uniform|casual|formal|robe|tactical", '
            '"primary_color": "#RRGGBB", "accents": ["#RRGGBB", ...max 4]},\n'
            '  "expression_resting": "neutral|gentle_smile|focused|alert",\n'
            '  "notes": "short rationale, ≤ 280 chars"\n'
            "}\n"
        )

        user_message_parts = [
            f"Agent identity: {agent_type or self.id}",
            f"Personality / instructions:\n{personality[:2000]}",
        ]
        if standing_orders_text:
            user_message_parts.append(
                f"Standing orders:\n{standing_orders_text}"
            )
        if recent_trust:
            user_message_parts.append(
                f"Recent trust deltas (last {len(recent_trust)}): {recent_trust}"
            )
        if captain_note:
            user_message_parts.append(
                f"Captain revision note: {captain_note}"
            )
        user_message_parts.append(
            "Reflect on the above and output the JSON DSL describing how YOU "
            "want to appear. Match the schema exactly."
        )
        user_message = "\n\n".join(user_message_parts)

        # ── LLM call (Tier-2 log-and-degrade only at this layer) ────
        request = LLMRequest(
            prompt=user_message,
            system_prompt=system_prompt,
            tier=self._resolve_tier() if hasattr(self, "_resolve_tier") else "standard",
            max_tokens=1024,
        )
        try:
            response = await self._llm_client.complete(request, priority=Priority.NORMAL)
        except Exception as exc:
            logger.warning(
                "AD-721d: LLM call failed for %s appearance proposal: %s; "
                "no DSL produced — caller may retry",
                self.id[:12],
                exc,
            )
            raise AppearanceProposalError("llm_call_failed", detail=str(exc)) from exc

        text = (response.content or "").strip()
        return self._parse_appearance_dsl(text)

    @classmethod
    def _parse_appearance_dsl(cls, text: str) -> "AvatarDSL":  # type: ignore[name-defined]
        """Hardened parse path for AD-721d: size cap → anchor/alias reject →
        ``yaml.safe_load`` → depth guard → Pydantic validate.

        NO ``exec``/``eval``/``compile``/``importlib.import_module`` is invoked
        on the LLM-derived artifact at any layer.
        """
        import yaml

        from probos.avatars.dsl import AppearanceProposalError, AvatarDSL

        # 1. Size cap (bytes, not chars — hostile inputs may use multi-byte).
        encoded = text.encode("utf-8")
        if len(encoded) > cls._APPEARANCE_PROPOSAL_MAX_BYTES:
            raise AppearanceProposalError(
                "response_oversized",
                detail=f"{len(encoded)} bytes > {cls._APPEARANCE_PROPOSAL_MAX_BYTES}",
            )

        # 2. Reject YAML anchors/aliases at the byte level. JSON does not use
        #    these tokens; rejecting them blocks alias-bomb fan-out and tag
        #    confusion. (`&` may legitimately appear inside a quoted string;
        #    we accept that v1 is conservative — the LLM is told to avoid them.)
        if "&" in text or re.search(r"(?<!\\)\*[A-Za-z_]", text):
            raise AppearanceProposalError(
                "yaml_anchor_or_alias",
                detail="response contains YAML anchor/alias markers",
            )

        # 3. Strip an optional Markdown fence the model may emit anyway.
        stripped = text
        if stripped.startswith("```"):
            stripped = re.sub(r"^```[a-zA-Z0-9]*\n", "", stripped)
            stripped = re.sub(r"\n```\s*$", "", stripped)

        # 4. yaml.safe_load — JSON is a YAML subset; safe_load blocks tag execution.
        try:
            parsed = yaml.safe_load(stripped)
        except yaml.YAMLError as exc:
            raise AppearanceProposalError("parse_error", detail=str(exc)) from exc
        if not isinstance(parsed, dict):
            raise AppearanceProposalError(
                "parse_error",
                detail=f"expected JSON object at top level, got {type(parsed).__name__}",
            )

        # 5. Depth guard.
        if cls._max_depth(parsed) > cls._APPEARANCE_PROPOSAL_MAX_DEPTH:
            raise AppearanceProposalError(
                "depth_exceeded",
                detail=f"document nests > {cls._APPEARANCE_PROPOSAL_MAX_DEPTH} levels",
            )

        # 6. Pydantic validation.
        try:
            return AvatarDSL.model_validate(parsed)
        except Exception as exc:  # pydantic.ValidationError + anything raised by validators
            raise AppearanceProposalError("schema_violation", detail=str(exc)) from exc

    @staticmethod
    def _max_depth(obj: Any, depth: int = 1) -> int:
        """Return the maximum nesting depth of a JSON-like Python object."""
        if isinstance(obj, dict):
            if not obj:
                return depth
            return max(CognitiveAgent._max_depth(v, depth + 1) for v in obj.values())
        if isinstance(obj, list):
            if not obj:
                return depth
            return max(CognitiveAgent._max_depth(v, depth + 1) for v in obj)
        return depth

    # ------------------------------------------------------------------
    # AD-718a: agent-authored voice proposal
    # ------------------------------------------------------------------

    async def propose_voice_profile(
        self,
        *,
        captain_note: str = "",
    ) -> tuple["VoiceProfile", str]:  # type: ignore[name-defined]
        """AD-718a: reflect on personality + role, propose a candidate
        ``(VoiceProfile, rationale)``.

        Mirrors :meth:`propose_appearance` structurally. NOT persisted —
        the caller (the propose endpoint) returns the candidate to the UI;
        Captain approval flows through the existing
        ``PUT /voice-profile`` endpoint, which re-runs
        ``VoiceProfile.__post_init__`` for a second independent bounds
        check (defense in depth).

        Args:
            captain_note: Optional revision note from the Captain
                (≤ 280 chars) appended to the prompt context for
                "Request revisions" flows.

        Raises:
            VoiceProposalError: LLM call failed, response oversized,
                contained YAML anchors/aliases/tags, exceeded depth
                bounds, failed to parse, or failed bounds validation.
        """
        from probos.crew_profile import VoiceProfile
        from probos.voice.proposal import (
            VoiceProposalError,
            parse_voice_proposal,
        )

        if self._llm_client is None:
            raise VoiceProposalError(
                "llm_unavailable",
                detail="CognitiveAgent has no llm_client configured",
            )

        if len(captain_note) > 280:
            raise VoiceProposalError(
                "invalid_input",
                detail=f"captain_note must be ≤ 280 chars, got {len(captain_note)}",
            )

        # ── Reflection context ──────────────────────────────────────
        personality_text = getattr(self, "instructions", "") or ""
        agent_type = getattr(self, "agent_type", "") or ""

        # Optional richer context from the live CrewProfile (display_name,
        # department, rank, Big-Five). Tier-2 log-and-degrade if profile_store
        # is unwired in tests.
        display_name = ""
        department = ""
        rank = ""
        big_five: dict[str, float] = {}
        runtime = getattr(self, "_runtime", None)
        try:
            ps = getattr(runtime, "profile_store", None) if runtime else None
            if ps is not None and hasattr(ps, "get"):
                crew = ps.get(self.id)
                if crew is not None:
                    display_name = getattr(crew, "display_name", "") or ""
                    department = getattr(crew, "department", "") or ""
                    rank_obj = getattr(crew, "rank", None)
                    rank = getattr(rank_obj, "value", "") or str(rank_obj or "")
                    p = getattr(crew, "personality", None)
                    if p is not None:
                        for trait in (
                            "openness", "conscientiousness", "extraversion",
                            "agreeableness", "neuroticism",
                        ):
                            v = getattr(p, trait, None)
                            if isinstance(v, (int, float)):
                                big_five[trait] = float(v)
        except Exception:
            logger.warning(
                "AD-718a: failed to fetch CrewProfile context for %s; "
                "proceeding without personality context",
                self.id[:12],
                exc_info=True,
            )

        system_prompt = (
            "You are designing your own voice. Output STRICT JSON matching "
            "the VoiceProfile schema below. Output JSON ONLY — no prose, no "
            "Markdown fences, no commentary. Do NOT use YAML anchors (&), "
            "aliases (*), or tag tokens (!!). Every field must be present.\n\n"
            "Schema (Web Speech API knobs):\n"
            "{\n"
            '  "voice_name": "exact SpeechSynthesisVoice.name to prefer, '
            'or empty string for global default",\n'
            '  "pitch": 0.0-2.0  (1.0 = neutral; lower = deeper, higher = brighter),\n'
            '  "rate":  0.1-10.0 (0.95 = relaxed; lower = slower),\n'
            '  "volume": 0.0-1.0 (0.8 = comfortable),\n'
            '  "wake_phrase": "optional short phrase the Captain may speak '
            'to address you directly (\u2264 50 chars). Two-syllable phrases '
            'work best. May be your first name, callsign, or rank. Keep it '
            'short and distinct from other crew members. Empty string if '
            'you have no preference.",\n'
            '  "rationale": "short reasoning, ≤ 500 chars"\n'
            "}\n"
            "\n"
            "Example: {\"voice_name\": \"\", \"pitch\": 0.95, \"rate\": 0.9, "
            "\"volume\": 0.8, \"wake_phrase\": \"Ezri\", "
            "\"rationale\": \"warm and measured\"}\n"
        )

        user_message_parts = [
            f"Agent identity: {display_name or agent_type or self.id}",
        ]
        if department:
            user_message_parts.append(f"Department: {department}")
        if rank:
            user_message_parts.append(f"Rank: {rank}")
        if big_five:
            user_message_parts.append(f"Big-Five personality: {big_five}")
        if personality_text:
            user_message_parts.append(
                f"Personality / instructions:\n{personality_text[:2000]}"
            )
        if captain_note:
            user_message_parts.append(
                f"Captain revision note: {captain_note}"
            )
        user_message_parts.append(
            "Reflect on the above and output the JSON describing how YOU "
            "want to sound. Match the schema exactly."
        )
        user_message = "\n\n".join(user_message_parts)

        # ── LLM call (Tier-2 log-and-degrade only at this layer) ────
        request = LLMRequest(
            prompt=user_message,
            system_prompt=system_prompt,
            tier=self._resolve_tier() if hasattr(self, "_resolve_tier") else "standard",
            max_tokens=512,
        )
        try:
            response = await self._llm_client.complete(request, priority=Priority.NORMAL)
        except Exception as exc:
            logger.warning(
                "AD-718a: LLM call failed for %s voice proposal: %s; "
                "no profile produced — caller may retry",
                self.id[:12],
                exc,
            )
            raise VoiceProposalError("llm_call_failed", detail=str(exc)) from exc

        text = (response.content or "").strip()
        return parse_voice_proposal(text)

    async def _self_post_ward_room_response(
        self, intent: "IntentMessage", response_text: str,
    ) -> None:
        """AD-654a: Post own response to ward room after handling notification.

        When activated via JetStream dispatch (AD-654a), the agent is
        responsible for posting its own response — the router no longer
        collects IntentResults and posts on agents' behalf.
        """
        _rt = getattr(self, "_runtime", None)
        if not _rt or not getattr(_rt, "ward_room", None):
            return

        thread_id = intent.params.get("thread_id", "")
        if not thread_id:
            return

        # Use runtime-stored pipeline (created in _apply_finalization)
        pipeline = getattr(_rt, "ward_room_post_pipeline", None)
        if not pipeline:
            logger.debug("AD-654a: No ward_room_post_pipeline on runtime, skipping self-post")
            return

        try:
            await pipeline.process_and_post(
                agent=self,
                response_text=response_text,
                thread_id=thread_id,
                event_type=intent.params.get("event_type", ""),
                post_id=intent.params.get("post_id"),
            )
        except Exception:
            logger.warning(
                "AD-654a: Self-post failed for %s in thread %s",
                self.id[:12], thread_id[:12],
                exc_info=True,
            )

    async def _run_cognitive_lifecycle(
        self,
        intent: IntentMessage,
        cognitive_skill_instructions: str | None = None,
        skill_entries: list | None = None,
    ) -> IntentResult:
        """Execute the full cognitive lifecycle: perceive → decide → act → report.

        BF-239: Extracted from handle_intent so try/finally can wrap the
        call site without re-indenting ~370 lines. All existing returns
        (normal completion, compound procedure early return) are preserved.

        Args:
            intent: The IntentMessage being processed.
            cognitive_skill_instructions: AD-596b cognitive skill instructions (if any).
            skill_entries: AD-596b skill catalog entries matched for this intent (if any).
        """
        observation = await self.perceive(intent)

        # AD-430c (Pillar 4): Enrich observation with relevant episodic memories
        observation = await self._recall_relevant_memories(intent, observation)

        # AD-596b: Inject cognitive skill instructions into observation context
        if cognitive_skill_instructions:
            observation["cognitive_skill_instructions"] = cognitive_skill_instructions
            observation["cognitive_skill_name"] = skill_entries[0].name

        # AD-669: Inject sibling thread conclusions into observation
        _wm = getattr(self, '_working_memory', None)
        if _wm:
            _sibling_text = _wm.render_conclusions(exclude_thread=intent.id)
            if _sibling_text:
                observation["_sibling_conclusions"] = _sibling_text

        # AD-1034: Drive the organ cognitive cycle across the agent's composed organs,
        # BEFORE the expensive LLM `decide` call (composable-cognition.md §9 — organs run
        # every cycle, deterministic and cheap). GUARDED + behavior-preserving: with the
        # default zero-organ spine `has_organs` is False, so `drive_cycle` is NEVER
        # invoked and this is byte-identical to pre-AD-1034. The cycle is SYNCHRONOUS (no
        # `await` on a bus/network call); organs reach the mesh only via the agent's
        # `deliver_exogenous` inlet, never the intent bus (sovereignty / AD-397).
        _spine = getattr(self, "_spine", None)
        if _spine is not None and _spine.has_organs:
            _spine.drive_cycle(observation)

        decision = await self.decide(observation)
        decision["intent"] = intent.intent  # AD-398: propagate intent name to act()
        # BF-177: propagate duty info so domain agents can distinguish duty-triggered thinks
        if observation.get("params", {}).get("duty"):
            decision["duty"] = observation["params"]["duty"]

        # AD-568e: Post-decision faithfulness verification
        _faithfulness = self._check_response_faithfulness(decision, observation)
        if _faithfulness is not None:
            observation["_faithfulness"] = _faithfulness
            if not _faithfulness.grounded:
                logger.info(
                    "AD-568e: Unfaithful response detected for %s (score=%.2f, overlap=%.2f, claims=%.2f)",
                    self.callsign or self.agent_type,
                    _faithfulness.score,
                    _faithfulness.evidence_overlap,
                    _faithfulness.unsupported_claim_ratio,
                )

        # AD-568e: Feed faithfulness signal to Counselor (fire-and-forget)
        if _faithfulness is not None:
            try:
                _rt = getattr(self, '_runtime', None)
                if _rt:
                    _counselors = _rt.registry.get_by_pool("counselor")
                    if _counselors:
                        _counselor = _counselors[0]
                        if hasattr(_counselor, 'record_faithfulness_event'):
                            await _counselor.record_faithfulness_event(
                                self.id,
                                faithfulness_score=_faithfulness.score,
                                grounded=_faithfulness.grounded,
                            )
            except Exception:
                logger.debug("AD-568e: Counselor faithfulness update failed", exc_info=True)

        # AD-589: Post-decision introspective faithfulness verification
        _intro_faith = self._check_introspective_faithfulness(decision)
        if _intro_faith is not None:
            observation["_introspective_faithfulness"] = _intro_faith
            if not _intro_faith.grounded:
                logger.info(
                    "AD-589: Introspective confabulation detected for %s (score=%.2f, claims=%d, contradictions=%d)",
                    self.callsign or self.agent_type,
                    _intro_faith.score,
                    _intro_faith.claims_detected,
                    len(_intro_faith.contradictions),
                )
                # AD-589: Emit SELF_MODEL_DRIFT event
                _rt = getattr(self, '_runtime', None)
                if _rt and hasattr(_rt, 'emit_event'):
                    try:
                        _rt.emit_event(EventType.SELF_MODEL_DRIFT, {
                            "agent_id": self.id,
                            "callsign": self.callsign or self.agent_type,
                            "score": _intro_faith.score,
                            "contradictions": _intro_faith.contradictions[:3],
                            "claims_detected": _intro_faith.claims_detected,
                            "correlation_id": observation.get("correlation_id", ""),
                        })
                    except Exception:
                        pass

        # AD-607d: post-decision memory-leak guard (sibling of AD-589 check).
        try:
            self._check_memory_leakage(decision, observation)
        except Exception:
            logger.debug("AD-607d: memory leak guard failed", exc_info=True)

        # AD-589: Feed introspective faithfulness to Counselor (fire-and-forget)
        if _intro_faith is not None:
            try:
                _rt = getattr(self, '_runtime', None)
                if _rt:
                    _counselors = _rt.registry.get_by_pool("counselor")
                    if _counselors:
                        _counselor = _counselors[0]
                        if hasattr(_counselor, 'record_faithfulness_event'):
                            await _counselor.record_faithfulness_event(
                                self.id,
                                faithfulness_score=_intro_faith.score,
                                grounded=_intro_faith.grounded,
                            )
            except Exception:
                logger.debug("AD-589: Counselor introspective update failed", exc_info=True)

        # AD-596c: Record cognitive skill exercise (fire-and-forget)
        if cognitive_skill_instructions and skill_entries:
            _bridge = getattr(self, '_skill_bridge', None)
            if _bridge:
                try:
                    import asyncio
                    asyncio.create_task(
                        _bridge.record_skill_exercise(self.id, skill_entries[0])
                    )
                except Exception:
                    logger.debug("AD-596c: Exercise recording task creation failed", exc_info=True)

        # AD-626: Record exercises for augmentation skills
        _aug_used = getattr(self, '_augmentation_skills_used', None)
        if _aug_used:
            _bridge = getattr(self, '_skill_bridge', None)
            if _bridge:
                for _aug_entry in _aug_used:
                    try:
                        import asyncio
                        asyncio.create_task(
                            _bridge.record_skill_exercise(self.id, _aug_entry)
                        )
                    except Exception:
                        logger.debug("AD-626: Aug skill exercise recording failed", exc_info=True)
            self._augmentation_skills_used = []

        # AD-534c: compound procedure dispatch
        if decision.get("compound") and decision.get("procedure"):
            compound_result = await self._execute_compound_replay(
                decision["procedure"], decision.get("llm_output", ""),
                compilation_level=decision.get("compilation_level", 4),
            )

            if compound_result.get("compound_dispatched"):
                # Record procedure completion (AD-534b metrics)
                _store = self._procedure_store
                if _store:
                    try:
                        await _store.record_completion(decision["procedure_id"])
                    except Exception:
                        pass

                # Emit task execution event (AD-532e)
                _rt = getattr(self, '_runtime', None)
                if _rt and hasattr(_rt, 'emit_event'):
                    try:
                        _rt.emit_event(EventType.TASK_EXECUTION_COMPLETE, {
                            "agent_id": self.id,
                            "agent_type": getattr(self, 'agent_type', ''),
                            "intent_type": intent.intent,
                            "success": True,
                            "used_procedure": True,
                            "compound_dispatched": True,
                            "steps_dispatched": compound_result.get("steps_dispatched", 0),
                            "correlation_id": observation.get("correlation_id", ""),
                        })
                    except Exception:
                        pass

                self.update_confidence(True)

                return IntentResult(
                    intent_id=intent.id,
                    agent_id=self.id,
                    success=True,
                    result=compound_result["result"],
                    confidence=self.confidence,
                )
            # Degradation: compound_dispatched=False — use text fallback in normal act() flow
            decision["llm_output"] = compound_result["result"]
            decision["compound"] = False  # prevent re-entry

        result = await self.act(decision)
        report = await self.report(result)

        # AD-573: Record action to working memory (all pathways)
        try:
            _wm = getattr(self, '_working_memory', None)
            if _wm:
                action_summary = self._summarize_action(intent, decision, result)
                if action_summary:
                    _wm.record_action(
                        action_summary,
                        source=intent.intent,
                    )
        except Exception:
            logger.debug("AD-573: Working memory action record failed", exc_info=True)

        # AD-669: Record conclusion for cross-thread sharing
        try:
            _wm = getattr(self, '_working_memory', None)
            if _wm:
                _conclusion_summary = self._extract_conclusion_summary(decision, result)
                if _conclusion_summary:
                    _conclusion_type = self._classify_conclusion(intent, decision)
                    _wm.record_conclusion(
                        thread_id=intent.id,
                        conclusion_type=_conclusion_type,
                        summary=_conclusion_summary,
                        relevance_tags=self._extract_relevance_tags(intent),
                        correlation_id=observation.get("correlation_id", ""),
                    )
                    _cycle_conclusions = [
                        conclusion for conclusion in _wm.get_active_conclusions()
                        if conclusion.thread_id == intent.id
                        and conclusion.correlation_id == observation.get("correlation_id", "")
                    ]
                    await self._store_important_conclusions_as_thoughts(
                        _cycle_conclusions,
                        correlation_id=observation.get("correlation_id", ""),
                    )
        except Exception:
            logger.debug("AD-669: Conclusion recording failed", exc_info=True)

        # AD-645 Phase 3: Store composition brief as metacognitive memory
        try:
            _wm = getattr(self, '_working_memory', None)
            if _wm and decision.get("sub_task_chain") and decision.get("_composition_brief"):
                brief = decision["_composition_brief"]
                if isinstance(brief, dict):
                    # Build a human-readable summary from the brief
                    _situation = brief.get("situation", "")
                    _cover = brief.get("response_should_cover")
                    if isinstance(_cover, list):
                        _cover_text = "; ".join(str(c) for c in _cover[:3])
                    else:
                        _cover_text = str(_cover) if _cover else ""
                    summary_parts = []
                    if _situation:
                        summary_parts.append(_situation)
                    if _cover_text:
                        summary_parts.append(f"Planned to cover: {_cover_text}")
                    if summary_parts:
                        _wm.record_reasoning(
                            " | ".join(summary_parts),
                            source=intent.intent,
                            metadata={"composition_brief": brief},
                            knowledge_source="reasoning",
                        )
        except Exception:
            logger.debug("AD-645: Composition brief storage failed", exc_info=True)

        # AD-430c (Pillar 5): Store action as episodic memory for crew agents
        # AD-632g: Propagate chain metadata into observation for episode storage
        if decision.get("sub_task_chain"):
            observation["_chain_metadata"] = {
                "sub_task_chain": True,
                "chain_source": decision.get("chain_source", ""),
                "chain_steps": decision.get("chain_steps", 0),
            }
        await self._store_action_episode(intent, observation, report)

        success = report.get("success", False)

        # AD-534b: Post-execution metric recording for procedure replay
        if decision.get("cached") and decision.get("procedure_id"):
            _store = self._procedure_store
            if _store:
                try:
                    if success:
                        await _store.record_completion(decision["procedure_id"])
                    else:
                        await _store.record_fallback(decision["procedure_id"])
                except Exception:
                    pass  # Never block intent pipeline for metrics

        # AD-535: Track Level 2 (Guided) procedure association
        if decision.get("guided_by_procedure") and decision.get("procedure_id"):
            _store = self._procedure_store
            if _store:
                try:
                    if success:
                        await _store.record_completion(decision["procedure_id"])
                    else:
                        await _store.record_fallback(decision["procedure_id"])
                except Exception:
                    pass

        # AD-535: Compilation level promotion/demotion
        _proc_id_for_promo = decision.get("procedure_id")
        if _proc_id_for_promo and self._procedure_store:
            _store = self._procedure_store
            if success:
                try:
                    new_count = await _store.record_consecutive_success(_proc_id_for_promo)
                    from probos.config import (
                        COMPILATION_PROMOTION_THRESHOLD,
                        COMPILATION_MAX_LEVEL,
                    )
                    proc = await _store.get(_proc_id_for_promo)
                    if proc and new_count >= COMPILATION_PROMOTION_THRESHOLD:
                        _ts = getattr(self, "_trust_score", 0.5)
                        # AD-536: Check if promoted procedure can reach Level 5
                        _promo_status = await _store.get_promotion_status(_proc_id_for_promo)
                        max_allowed = self._max_compilation_level_for_promoted(_ts, _promo_status)
                        next_level = proc.compilation_level + 1
                        if next_level <= min(max_allowed, COMPILATION_MAX_LEVEL):
                            await _store.promote_compilation_level(_proc_id_for_promo, next_level)
                            logger.info(
                                "Procedure '%s' promoted to Level %d after %d consecutive successes",
                                proc.name, next_level, new_count,
                            )
                            # AD-536: Check if procedure is eligible for institutional promotion
                            from probos.config import PROMOTION_MIN_COMPILATION_LEVEL
                            promo_status = await _store.get_promotion_status(_proc_id_for_promo)
                            if next_level >= PROMOTION_MIN_COMPILATION_LEVEL and promo_status == "private":
                                await self._request_procedure_promotion(_proc_id_for_promo)
                except Exception:
                    pass
            else:
                try:
                    from probos.config import COMPILATION_DEMOTION_LEVEL
                    proc = await _store.get(_proc_id_for_promo)
                    if proc and proc.compilation_level > COMPILATION_DEMOTION_LEVEL:
                        await _store.demote_compilation_level(
                            _proc_id_for_promo, COMPILATION_DEMOTION_LEVEL
                        )
                        logger.info(
                            "Procedure '%s' demoted to Level %d after failure",
                            proc.name, COMPILATION_DEMOTION_LEVEL,
                        )
                    else:
                        await _store.reset_consecutive_successes(_proc_id_for_promo)
                except Exception:
                    pass

        # AD-534b: Service recovery — re-run LLM on cached execution failure
        llm_decision = None
        if decision.get("cached") and not success:
            _proc_name = decision.get("procedure_name", "")
            _proc_id = decision.get("procedure_id", "")
            logger.debug("Procedure replay failed, attempting LLM fallback: procedure=%s", _proc_name)
            try:
                llm_decision = await self._run_llm_fallback(observation)
                if llm_decision is not None:
                    llm_result = await self.act(llm_decision)
                    llm_report = await self.report(llm_result)
                    llm_success = llm_report.get("success", False)
                    if llm_success:
                        # Service recovery succeeded — use LLM result
                        result = llm_result
                        report = llm_report
                        success = True
                        # Capture fallback learning event
                        self._last_fallback_info = {
                            "type": "execution_failure",
                            "procedure_id": _proc_id,
                            "procedure_name": _proc_name,
                            "reason": "Procedure replay succeeded in formatting but failed in execution",
                        }
            except Exception:
                logger.debug("LLM fallback recovery failed", exc_info=True)
                # Original failure stands — user sees the procedure's error

        self.update_confidence(success)

        # AD-532e: Reactive trigger — emit task completion for procedure evolution monitoring
        _rt = getattr(self, '_runtime', None)
        if _rt and hasattr(_rt, 'emit_event'):
            try:
                _rt.emit_event(EventType.TASK_EXECUTION_COMPLETE, {
                    "agent_id": self.id,
                    "agent_type": getattr(self, 'agent_type', ''),
                    "intent_type": intent.intent,
                    "success": success,
                    "used_procedure": decision.get("cached", False),
                    "correlation_id": observation.get("correlation_id", ""),
                })
            except Exception:
                pass  # Fire-and-forget, never block the intent pipeline

        # AD-534b: Emit fallback learning event for dream-time processing
        if success and self._last_fallback_info is not None:
            if _rt and hasattr(_rt, 'emit_event'):
                try:
                    from probos.config import MAX_FALLBACK_RESPONSE_CHARS
                    _llm_output = ""
                    if llm_decision is not None:
                        _llm_output = llm_decision.get("llm_output", "")
                    else:
                        _llm_output = decision.get("llm_output", "")
                    _rt.emit_event(EventType.PROCEDURE_FALLBACK_LEARNING, {
                        "agent_id": self.id,
                        "intent_type": intent.intent,
                        "fallback_type": self._last_fallback_info["type"],
                        "procedure_id": self._last_fallback_info["procedure_id"],
                        "procedure_name": self._last_fallback_info.get("procedure_name", ""),
                        "near_miss_score": self._last_fallback_info.get("score", 0.0),
                        "rejection_reason": self._last_fallback_info.get("reason", ""),
                        "llm_response": _llm_output[:MAX_FALLBACK_RESPONSE_CHARS],
                        "timestamp": time.time(),
                        "correlation_id": observation.get("correlation_id", ""),
                    })
                except Exception:
                    pass  # Fire-and-forget
            self._last_fallback_info = None  # Consumed

        # AD-654a: Agent self-posting for ward_room_notification
        if intent.intent == "ward_room_notification" and success and report.get("result"):
            await self._self_post_ward_room_response(intent, str(report["result"]))

        # AD-492: Clear correlation_id — cycle complete
        _wm = getattr(self, '_working_memory', None)
        if _wm:
            _wm.clear_correlation_id()
        self._current_correlation_id = ""

        return IntentResult(
            intent_id=intent.id,
            agent_id=self.id,
            success=success,
            result=report.get("result"),
            error=report.get("error"),
            confidence=self.confidence,
        )

    async def handle_intent(self, intent: IntentMessage) -> IntentResult | None:
        """Skills first, then cognitive lifecycle.

        Returns None (self-deselect) for intents not in _handled_intents,
        unless it's a targeted direct_message (AD-397 1:1 sessions).
        """
        # AD-397: always accept direct_message if targeted to this agent
        # AD-407b: always accept ward_room_notification if targeted to this agent
        is_direct = (
            intent.intent in ("direct_message", "ward_room_notification", "proactive_think", "compound_step_replay")
            and intent.target_agent_id == self.id
        )

        # BF-239: Ward Room thread engagement gate — skip if already
        # replied to this thread in the current round. Uses working memory
        # engagement tracking (serial queue guarantees no race).
        # @mentions and DMs bypass — same principle as BF-236/cooldown gates.
        _bf239_thread_id = ""
        if intent.intent == "ward_room_notification":
            _bf239_thread_id = intent.params.get("thread_id", "")
            _bf239_mentioned = intent.params.get("was_mentioned", False)
            _bf239_is_dm = intent.params.get("is_dm_channel", False)
            if _bf239_thread_id and not _bf239_mentioned and not _bf239_is_dm:
                _wm = getattr(self, '_working_memory', None)
                if _wm and _wm.has_thread_engagement(_bf239_thread_id):
                    logger.debug(
                        "BF-239: %s already engaged with thread %s, skipping",
                        getattr(self, 'callsign', '') or self.agent_type,
                        _bf239_thread_id[:8],
                    )
                    # [NO_RESPONSE] with current confidence — the agent handled
                    # the intent (chose silence), it did not fail. No
                    # update_confidence() call: no cognitive work was performed,
                    # so Trust/Hebbian feedback should not see this event.
                    return IntentResult(
                        intent_id=intent.id,
                        agent_id=self.id,
                        success=True,
                        result="[NO_RESPONSE]",
                        confidence=self.confidence,
                    )

        # AD-839: a work item directly assigned to this agent (via the
        # AD-581a WorkItemRouter "dispatch to agent now" path) is surfaced as
        # a Captain task message, acknowledged through the normal direct-
        # message lifecycle, and transitioned to in_progress. Handled before
        # the self-deselect fast path because ``work_item_dispatched`` is not
        # in ``_handled_intents``.
        if (
            intent.intent == "work_item_dispatched"
            and intent.target_agent_id == self.id
        ):
            return await self._handle_work_item_dispatch(intent)

        # Fast path: self-deselect for unrecognized intents before any LLM call
        # AD-596b: Check cognitive skill catalog before self-deselecting
        _cognitive_skill_instructions = None
        _skill_entries = None  # BF-239: must be defined for _run_cognitive_lifecycle call
        if not is_direct and intent.intent not in self._handled_intents:
            _catalog = getattr(self, '_cognitive_skill_catalog', None)
            if _catalog:
                _skill_entries = _catalog.find_by_intent(intent.intent)
                if _skill_entries:
                    _entry = _skill_entries[0]
                    # AD-596c: Proficiency gate — check before loading instructions
                    _bridge = getattr(self, '_skill_bridge', None)
                    if _bridge:
                        _profile = getattr(self, '_skill_profile', None)
                        if not _bridge.check_proficiency_gate(self.id, _entry, _profile):
                            return None  # Silent self-deselect — agent lacks proficiency
                    _cognitive_skill_instructions = _catalog.get_instructions(_entry.name)
                    if _cognitive_skill_instructions:
                        logger.info(
                            "AD-596b: Loaded cognitive skill '%s' for intent '%s' on %s",
                            _entry.name, intent.intent, self.agent_type,
                        )
                    else:
                        return None
                else:
                    return None
            else:
                return None

        # AD-534c: compound step replay — zero-token, bypass full cognitive lifecycle
        if intent.intent == "compound_step_replay" and intent.target_agent_id == self.id:
            return await self._handle_compound_step_replay(intent)

        # Skill dispatch — direct handler call, no LLM reasoning
        if intent.intent in self._skills:
            skill = self._skills[intent.intent]
            return await skill.handler(intent, llm_client=self._llm_client)

        # BF-239: Register ward room thread engagement before cognitive lifecycle.
        # Recorded here (after skill dispatch, before lifecycle) so that:
        # 1. The engagement exists before any await (perceive's LLM call)
        # 2. Skill-dispatched intents don't get engagement-tracked
        # Key namespaced as "ward_room:{thread_id}" to avoid collision
        # with game engagements that use raw game_id as engagement_id.
        if _bf239_thread_id:
            # Function-local import: cognitive_agent.py does not import
            # ActiveEngagement at module level (only AgentWorkingMemory,
            # and that's also function-local at line 100). Keeping the
            # pattern consistent avoids circular import risk.
            from probos.cognitive.agent_working_memory import ActiveEngagement
            _wm = getattr(self, '_working_memory', None)
            if _wm:
                _wm.add_engagement(ActiveEngagement(
                    engagement_type="ward_room_reply",
                    engagement_id=f"ward_room:{_bf239_thread_id}",
                    summary=f"Replying to Ward Room thread {_bf239_thread_id[:8]}",
                    state={"thread_id": _bf239_thread_id},
                ))

        concurrency_manager = getattr(self, "_concurrency_manager", None)
        if concurrency_manager:
            priority = _classify_concurrency_priority(intent)
            try:
                async with concurrency_manager.slot(intent.intent, priority):
                    return await self._run_cognitive_lifecycle(
                        intent, _cognitive_skill_instructions, _skill_entries,
                    )
            except ValueError:
                logger.warning(
                    "AD-672: Concurrency queue full for %s on intent '%s'; "
                    "returning [NO_RESPONSE] to shed load",
                    getattr(self, 'callsign', '') or self.agent_type,
                    intent.intent,
                )
                return IntentResult(
                    intent_id=intent.id,
                    agent_id=self.id,
                    success=True,
                    result="[NO_RESPONSE]",
                    confidence=self.confidence,
                )
            finally:
                if _bf239_thread_id:
                    _wm = getattr(self, '_working_memory', None)
                    if _wm:
                        _wm.remove_engagement(f"ward_room:{_bf239_thread_id}")

        try:
            return await self._run_cognitive_lifecycle(
                intent, _cognitive_skill_instructions, _skill_entries,
            )
        finally:
            # BF-239: Remove ward room thread engagement on ALL exit paths.
            # Covers: normal completion, compound procedure early return,
            # and exceptions from perceive/decide/act/report.
            # The engagement is the short-lived "I'm currently working on this" signal.
            # Historical record preserved via _summarize_action (Section 5).
            if _bf239_thread_id:
                _wm = getattr(self, '_working_memory', None)
                if _wm:
                    _wm.remove_engagement(f"ward_room:{_bf239_thread_id}")

    def add_skill(self, skill: Skill) -> None:
        """Attach a skill to this cognitive agent.

        Updates BOTH instance-level AND class-level _handled_intents
        and intent_descriptors so that both the agent's own dispatch
        and the template-based descriptor collection path work.
        """
        self._skills[skill.descriptor.name] = skill

        # Instance-level update (for this agent's dispatch)
        self._handled_intents.add(skill.descriptor.name)
        if skill.descriptor not in self.intent_descriptors:
            self.intent_descriptors.append(skill.descriptor)

        # Class-level update (for template-based descriptor collection in
        # _collect_intent_descriptors, which reads class.intent_descriptors)
        cls = type(self)
        if skill.descriptor not in cls.intent_descriptors:
            cls.intent_descriptors = [*cls.intent_descriptors, skill.descriptor]
        cls._handled_intents = cls._handled_intents | {skill.descriptor.name}

    def remove_skill(self, intent_name: str) -> None:
        """Remove a skill from this cognitive agent.

        Updates both instance and class level.
        """
        if intent_name not in self._skills:
            return
        self._skills.pop(intent_name)
        self._handled_intents.discard(intent_name)
        self.intent_descriptors = [
            d for d in self.intent_descriptors if d.name != intent_name
        ]
        # Class-level cleanup
        cls = type(self)
        cls._handled_intents = cls._handled_intents - {intent_name}
        cls.intent_descriptors = [
            d for d in cls.intent_descriptors if d.name != intent_name
        ]

    def _resolve_callsign(self) -> str | None:
        """Resolve current callsign with identity registry fallback (BF-101)."""
        if self.callsign:
            return self.callsign
        # Fallback: check birth certificate
        rt = getattr(self, '_runtime', None)
        if rt and hasattr(rt, '_identity_registry') and rt._identity_registry:
            cert = rt._identity_registry.get_by_slot(self.id)
            if cert and cert.callsign:
                # Restore to live attribute for future calls
                self.callsign = cert.callsign
                logger.warning("BF-101: Restored callsign '%s' from birth cert for %s",
                             cert.callsign, self.agent_type)
                return cert.callsign
        return None

    def whoami(self) -> dict[str, str]:
        """AD-735: assemble verified self-identity facts for fact-grounded DM replies.

        Sources are authoritative (birth certificate + public identity attrs), never
        generated. Honest-degrade: missing cert yields the public-attr subset.
        """
        # Seed from the canonical callsign resolver (BF-101 cert fallback inside).
        callsign = self._resolve_callsign() or self.agent_type
        facts: dict[str, str] = {
            "callsign": callsign,
            "agent_type": self.agent_type,
        }

        cert = None
        rt = getattr(self, "_runtime", None)
        if rt is not None and getattr(rt, "_identity_registry", None):
            try:
                cert = rt._identity_registry.get_by_slot(self.id)
            except Exception:
                logger.debug(
                    "AD-735: birth-cert lookup failed for %s; degrading to public attrs",
                    self.agent_type, exc_info=True,
                )
                cert = None

        if cert is not None:
            if cert.callsign:
                facts["callsign"] = cert.callsign
            if cert.department:
                facts["department"] = cert.department
            if cert.did:
                facts["did"] = cert.did
            # Guard the float — a malformed cert must not raise in conversion.
            if isinstance(cert.birth_timestamp, (int, float)):
                facts["birth_iso"] = datetime.fromtimestamp(cert.birth_timestamp).isoformat()
            if cert.certificate_hash:
                facts["certificate_hash"] = cert.certificate_hash[:12]
            if cert.vessel_name:
                facts["vessel_name"] = cert.vessel_name
        else:
            # No cert — derive department from the static mapping; do NOT fabricate
            # did/birth/hash.
            from probos.cognitive.standing_orders import get_department
            dept = get_department(self.agent_type)
            if dept:
                facts["department"] = dept

        # Drop any empty/None values that slipped through.
        return {k: v for k, v in facts.items() if v}

    def whoami_block(self) -> str:
        """AD-735: render whoami() as a compact verified-fact block for prompt injection."""
        facts = self.whoami()
        callsign = facts.get("callsign", "")
        lines: list[str] = []
        if callsign:
            spelled = "-".join(callsign)
            lines.append(f"Callsign: {callsign} (spelled {spelled})")
        if facts.get("agent_type"):
            lines.append(f"Role / agent_type: {facts['agent_type']}")
        if facts.get("department"):
            lines.append(f"Department: {facts['department']}")
        if facts.get("birth_iso"):
            lines.append(f"Commissioned: {facts['birth_iso']}")
        if facts.get("certificate_hash"):
            lines.append(f"Identity hash: {facts['certificate_hash']}")
        return "\n".join(lines)

    def _get_comm_proficiency_guidance(self) -> str | None:
        """AD-625: Return tier-specific communication guidance based on proficiency."""
        profile = getattr(self, '_skill_profile', None)
        if not profile:
            return None
        for rec in profile.all_skills:
            if rec.skill_id == "communication":
                from probos.cognitive.comm_proficiency import get_prompt_guidance
                return get_prompt_guidance(rec.proficiency)
        return None

    def _load_augmentation_skills(self, intent: str) -> str:
        """AD-626: Load augmentation skill instructions for a handled intent.

        Returns concatenated skill guidance sections, or empty string.
        Augmentation skills enhance existing behavior — they don't provide
        new capabilities. Think: cognitive tools that extend natural ability.
        """
        if not intent:
            return ""
        catalog = getattr(self, '_cognitive_skill_catalog', None)
        if not catalog:
            if _SKILL_DEBUG:
                logger.info("AD-626 [SKILL_DEBUG]: No catalog on %s", self.agent_type)
            return ""

        department = getattr(self, 'department', None)
        rank = getattr(self, 'rank', None)
        rank_val = rank.value if hasattr(rank, 'value') else rank

        entries = catalog.find_augmentation_skills(
            intent, department=department, agent_rank=rank_val,
        )
        if not entries:
            if _SKILL_DEBUG:
                logger.info(
                    "AD-626 [SKILL_DEBUG]: No augmentation skills matched intent='%s' "
                    "dept='%s' rank='%s' on %s (catalog has %d skills)",
                    intent, department, rank_val, self.agent_type,
                    len(catalog._cache),
                )
            self._augmentation_skills_used = []
            return ""

        bridge = getattr(self, '_skill_bridge', None)
        profile = getattr(self, '_skill_profile', None)
        parts = []
        loaded_entries = []
        for entry in entries:
            if bridge and not bridge.check_proficiency_gate(self.id, entry, profile):
                if _SKILL_DEBUG:
                    logger.info(
                        "AD-626 [SKILL_DEBUG]: Proficiency gate blocked '%s' on %s",
                        entry.name, self.agent_type,
                    )
                continue
            instructions = catalog.get_instructions(entry.name)
            if instructions:
                parts.append(instructions)
                loaded_entries.append(entry)
                logger.info(
                    "AD-626: Loaded augmentation skill '%s' for intent '%s' on %s",
                    entry.name, intent, self.agent_type,
                )

        self._augmentation_skills_used = loaded_entries
        return "".join(parts)

    def _frame_task_with_skill(
        self,
        skill_instructions: str,
        task_label: str,
        context_summary: str = "",
        proficiency_context: str = "",
    ) -> list[str]:
        """AD-626/AD-631: Generic task-framed skill injection with XML tags.

        Produces preamble lines that frame a task with augmentation skill
        instructions. The caller appends task-specific content after these
        lines. This is the single injection mechanism for all intent types —
        skill content and framing are task-type-agnostic. Specific metadata
        (e.g. thread reply counts) is provided by the caller via
        context_summary.
        """
        # Derive skill name from loaded augmentation skills
        _skill_name = task_label.lower().replace(" ", "-")
        if self._augmentation_skills_used:
            _skill_name = self._augmentation_skills_used[0].name

        lines = [""]
        lines.append(f'<active_skill name="{_skill_name}" activation="augmentation">')
        if proficiency_context:
            lines.append(f"<proficiency_tier>{proficiency_context}</proficiency_tier>")
        if context_summary:
            lines.append(f"<skill_context>{context_summary}</skill_context>")
        lines.append("<skill_instructions>")
        lines.append(
            "Follow these instructions internally when processing the "
            "content below. Your response must contain ONLY your final "
            "output — no reasoning steps, phase headers, or self-evaluation "
            "artifacts."
        )
        lines.append("")
        lines.append(skill_instructions)
        lines.append("</skill_instructions>")
        lines.append("</active_skill>")
        lines.append("")
        return lines

    @staticmethod
    def _extract_thread_metadata(thread_text: str) -> str:
        """Extract reply count and contributor callsigns from Ward Room thread text.

        Returns a summary string like 'Replies so far: ~3 | Contributors: A, B'
        or empty string if no metadata can be extracted. This is Ward-Room-
        specific context passed to the generic _frame_task_with_skill().
        """
        if not thread_text:
            return ""
        _lines = thread_text.strip().split("\n")
        _reply_count = sum(
            1 for ln in _lines
            if ln.strip().startswith("- ") or ln.strip().startswith("Reply from")
        )
        _callsigns: set[str] = set()
        for ln in _lines:
            for marker in ("posted:", "Reply from ", "— "):
                idx = ln.find(marker)
                if idx != -1:
                    _cs = ln[idx + len(marker):].strip().split()[0].rstrip(":,")
                    if _cs and len(_cs) < 30:
                        _callsigns.add(_cs)
        _parts: list[str] = []
        if _reply_count > 0:
            _parts.append(f"Replies so far: ~{_reply_count}")
        if _callsigns:
            _parts.append(f"Contributors: {', '.join(sorted(_callsigns))}")
        return " | ".join(_parts) if _parts else ""

    def _detect_self_in_content(self, content: str) -> str:
        """Detect if agent's own callsign appears in content and return grounding cue.

        AD-575: Cross-context self-recognition. When the agent's callsign
        appears in Ward Room thread content, return a grounding note so the
        agent recognizes itself as a participant, not an observer.

        Returns a grounding string, or empty string if no self-mention detected.
        """
        callsign = self._resolve_callsign()
        if not callsign:
            return ""

        if not re.search(rf"\b{re.escape(callsign)}\b", content, re.IGNORECASE):
            return ""

        # Self-mention detected — build grounding cue
        cue_parts: list[str] = [
            f"IMPORTANT: Your callsign is {callsign}. References to"
            f" '{callsign}' in the thread above refer to YOU."
            f" You are a participant in what is being discussed, not an"
            f" outside observer. Respond from your perspective as a participant.",
        ]

        # Cross-context engagement binding (AD-572/573)
        _wm = getattr(self, "_working_memory", None)
        if _wm and _wm.has_engagement("game"):
            games = _wm.get_engagements_by_type("game")
            if games:
                g = games[0]
                game_type = g.state.get("game_type", "game")
                opponent = g.state.get("opponent", "")
                cue_parts.append(
                    f"You have an active {game_type} game"
                    + (f" against {opponent}" if opponent else "")
                    + ". Spectators are watching your game in this thread."
                    + " Engage from your perspective as the player."
                )

        return "\n".join(cue_parts)

    def _has_active_game(self) -> bool:
        """AD-572: Check if this agent has an active game (lightweight check)."""
        rt = getattr(self, '_runtime', None)
        if not rt:
            return False
        rec_svc = getattr(rt, 'recreation_service', None)
        if not rec_svc:
            return False
        callsign = self._resolve_callsign()
        if not callsign:
            return False
        try:
            return rec_svc.get_game_by_player(callsign) is not None
        except Exception:
            return False

    def _build_active_game_context(self) -> str | None:
        """AD-572: Build active game context for DM awareness.

        Returns a formatted string if this agent has an active game, else None.
        Uses RecreationService.get_game_by_player() (AD-572 DRY method).
        """
        rt = getattr(self, '_runtime', None)
        if not rt:
            return None
        rec_svc = getattr(rt, 'recreation_service', None)
        if not rec_svc:
            return None

        callsign = self._resolve_callsign()
        if not callsign:
            return None

        try:
            game = rec_svc.get_game_by_player(callsign)
            if not game:
                return None

            game_id = game["game_id"]
            state = game.get("state", {})
            opponent = next(
                (p for p in [game.get("challenger", ""), game.get("opponent", "")]
                 if p != callsign),
                "unknown",
            )
            board = rec_svc.render_board(game_id)
            is_my_turn = state.get("current_player") == callsign
            valid_moves = rec_svc.get_valid_moves(game_id) if is_my_turn else []

            lines = ["--- Active Game ---"]
            lines.append(
                f"You are playing {game.get('game_type', 'a game')} against {opponent}. "
                f"Moves so far: {game.get('moves_count', 0)}."
            )
            lines.append(f"\nCurrent board:\n```\n{board}\n```")
            if is_my_turn:
                lines.append(
                    f"**It is YOUR turn.** Valid moves: {', '.join(str(m) for m in valid_moves)}. "
                    f"Reply with [MOVE position] to play."
                )
            else:
                lines.append("Waiting for your opponent to move.")
            return "\n".join(lines)
        except Exception:
            return None

    def _summarize_action(self, intent, decision: dict, result: dict) -> str:
        """AD-573: Produce a one-line summary of what I just did."""
        intent_type = intent.intent
        output = (decision.get("llm_output") or "")[:200]

        if intent_type == "direct_message":
            captain_text = intent.params.get("text", "")[:100]
            return f"Responded to Captain's DM: '{captain_text}' → '{output[:100]}'"
        if intent_type == "ward_room_notification":
            channel = intent.params.get("channel_name", "")
            thread_id = intent.params.get("thread_id", "")
            _thread_tag = f" (thread {thread_id[:8]})" if thread_id else ""
            return f"Responded in Ward Room #{channel}{_thread_tag}: '{output[:100]}'"
        if intent_type == "proactive_think":
            if "[NO_RESPONSE]" in output:
                return ""  # Don't record silence
            return f"Proactive observation: '{output[:150]}'"
        return f"Handled {intent_type}: '{output[:100]}'"

    @staticmethod
    def _extract_conclusion_summary(decision: dict, result: dict) -> str:
        """AD-669: Extract a one-line conclusion from chain execution results."""
        llm_output = decision.get("llm_output", "")
        if not llm_output or "[NO_RESPONSE]" in llm_output:
            return ""

        brief = decision.get("_composition_brief")
        if isinstance(brief, dict):
            situation = brief.get("situation", "")
            if situation:
                return situation[:200]

        first_line = llm_output.split("\n")[0].strip()
        if len(first_line) > 200:
            return first_line[:197] + "..."
        return first_line

    @staticmethod
    def _classify_conclusion(intent, decision: dict) -> "ConclusionType":
        """AD-669: Classify conclusion type from intent and decision context."""
        from probos.cognitive.agent_working_memory import ConclusionType

        llm_output = (decision.get("llm_output") or "").lower()
        if "escalat" in llm_output or "captain" in llm_output or decision.get("compound"):
            return ConclusionType.ESCALATION
        if intent.intent == "proactive_think":
            return ConclusionType.OBSERVATION
        if decision.get("duty"):
            return ConclusionType.COMPLETION
        return ConclusionType.DECISION

    @staticmethod
    def _map_conclusion_to_thought_type(conclusion: Any) -> str:
        """AD-606: Map a ConclusionEntry type to a thought type string."""
        conclusion_type = conclusion.conclusion_type
        conclusion_value = conclusion_type.value if hasattr(conclusion_type, "value") else str(conclusion_type)
        mapping = {
            "decision": "conclusion",
            "observation": "observation_synthesis",
            "escalation": "conclusion",
            "completion": "conclusion",
        }
        return mapping.get(conclusion_value, "conclusion")

    async def _store_important_conclusions_as_thoughts(
        self,
        conclusions: list[Any],
        *,
        correlation_id: str = "",
    ) -> None:
        """AD-606: Persist important working-memory conclusions as thought episodes."""
        if self._thought_store is None:
            if not self._runtime:
                return
            try:
                _ts_config = self._runtime.config.thought_store
                if not _ts_config.enabled:
                    return
                from probos.cognitive.thought_store import ThoughtStore

                self._thought_store = ThoughtStore(
                    episodic_memory=self._runtime.episodic_memory,
                    config=_ts_config,
                    identity_registry=getattr(self._runtime, "identity_registry", None),
                )
            except Exception:
                logger.debug("AD-606: ThoughtStore unavailable", exc_info=True)
                return

        if not conclusions:
            return

        try:
            active_correlation_id = correlation_id or self._current_correlation_id
            self._thought_store.reset_cycle(active_correlation_id)
            for conclusion in conclusions[:3]:
                await self._thought_store.store_thought(
                    agent_id=self.id,
                    thought=conclusion.summary,
                    thought_type=self._map_conclusion_to_thought_type(conclusion),
                    importance=6,
                    correlation_id=active_correlation_id,
                )
        except Exception:
            logger.debug("AD-606: Thought storage failed; continuing without thought memory", exc_info=True)

    @staticmethod
    def _extract_relevance_tags(intent) -> list[str]:
        """AD-669: Extract relevance tags from the intent for conclusion indexing."""
        tags: list[str] = []
        if intent.intent:
            tags.append(intent.intent)
        channel = intent.params.get("channel_name", "")
        if channel:
            tags.append(f"channel:{channel}")
        topic = intent.params.get("topic", "")
        if topic:
            tags.append(f"topic:{topic}")
        return tags[:5]

    async def _build_dm_self_monitoring(self, thread_id: str) -> str | None:
        """AD-623: Lightweight self-monitoring for DM/WR response path.

        Check this agent's own recent posts in the thread for self-repetition.
        Returns a warning string if similarity is high, None otherwise.
        """
        rt = getattr(self, '_runtime', None)
        if not rt or not hasattr(rt, 'ward_room') or not rt.ward_room:
            return None

        try:
            callsign = getattr(self, 'callsign', None) or getattr(self, 'agent_type', '')
            posts = await rt.ward_room.get_posts_by_author(
                callsign, limit=3, thread_id=thread_id,
            )
            if not posts or len(posts) < 2:
                return None

            from probos.cognitive.similarity import jaccard_similarity, text_to_words
            word_sets = [text_to_words(p["body"]) for p in posts]
            total_sim = 0.0
            pair_count = 0
            for j in range(len(word_sets)):
                for k in range(j + 1, len(word_sets)):
                    total_sim += jaccard_similarity(word_sets[j], word_sets[k])
                    pair_count += 1

            if pair_count > 0:
                avg_sim = total_sim / pair_count
                if avg_sim >= 0.4:
                    return (
                        "--- Self-monitoring (AD-623) ---\n"
                        f"WARNING: Your last {len(posts)} messages in this thread "
                        f"show {avg_sim:.0%} self-similarity. You may be repeating "
                        "yourself. If you and the other person agree, conclude the "
                        "conversation naturally. Do NOT restate conclusions you've "
                        "already communicated. If there's nothing new to add, "
                        "respond with exactly: [NO_RESPONSE]"
                    )
        except Exception:
            logger.debug("AD-623: DM self-monitoring failed", exc_info=True)

        return None

    async def handle_consultation_request(self, request: Any) -> Any:
        """AD-594: Handle an incoming expert consultation request."""
        from probos.cognitive.consultation import ConsultationResponse

        callsign = getattr(self, "callsign", None) or self.agent_type
        logger.info(
            "AD-594: %s handling consultation on '%s' from %s",
            callsign,
            request.topic,
            request.requester_callsign or request.requester_id,
        )

        system_prompt = (
            f"You are {callsign}, responding to an expert consultation.\n"
            f"Topic: {request.topic}\n"
            f"Question: {request.question}\n"
        )
        if request.required_expertise:
            system_prompt += f"Required expertise: {request.required_expertise}\n"
        if request.context:
            system_prompt += f"Additional context: {request.context}\n"

        system_prompt += (
            "\nProvide a concise, expert answer. Include your reasoning summary. "
            "Rate your confidence (0.0-1.0) in your answer. "
            "If you are not confident, say so honestly."
        )

        user_message = request.question or request.topic
        answer = ""
        confidence = 0.5
        reasoning = ""

        runtime = getattr(self, "_runtime", None)
        llm = getattr(self, "_llm_client", None) or (
            getattr(runtime, "llm_client", None) if runtime else None
        )
        if llm:
            try:
                from probos.types import LLMRequest
                llm_request = LLMRequest(
                    system_prompt=system_prompt,
                    user_message=user_message,
                    tier="fast",
                )
                llm_response = await llm.complete(llm_request)
                answer = (
                    llm_response.content
                    if hasattr(llm_response, "content")
                    else str(llm_response)
                )
                confidence = 0.6
                reasoning = f"Consulted on {request.topic}"
            except Exception:
                logger.warning(
                    "AD-594: LLM call failed for consultation by %s; providing fallback",
                    callsign,
                    exc_info=True,
                )
                answer = f"I did not complete a full analysis of '{request.topic}' at this time."
                confidence = 0.2
                reasoning = "LLM call failed; low-confidence fallback response"
        else:
            answer = (
                f"Acknowledged consultation on '{request.topic}'; "
                "no LLM client is available for detailed analysis."
            )
            confidence = 0.1
            reasoning = "No LLM client available"

        return ConsultationResponse(
            request_id=request.request_id,
            responder_id=self.id,
            responder_callsign=callsign,
            answer=answer,
            confidence=confidence,
            reasoning_summary=reasoning,
        )

    async def consult(
        self,
        question: str,
        *,
        topic: str = "",
        context: dict | None = None,
        required_expertise: str | None = None,
        target_agent_id: str | None = None,
        urgency: str = "medium",
    ) -> "ConsultationResponse | None":
        """AD-594b: Initiate an expert consultation.

        Thin convenience wrapper: builds a ``ConsultationRequest`` from this
        agent's identity + the supplied ``(question, context)``, then routes
        it through the wired ``ConsultationProtocol``. Returns the
        ``ConsultationResponse`` (or ``None`` on rate-limit, no expert,
        timeout, or handler error -- the protocol logs the reason).

        Counterpart to ``handle_consultation_request`` -- agents now have
        both halves of the protocol surface on a single class.

        Args:
            question: The question to ask. Required.
            topic: Optional short topic; defaults to the question if absent.
            context: Optional structured context dict passed verbatim.
            required_expertise: Optional capability string for expert selection.
            target_agent_id: Optional direct target; bypasses expert selection.
            urgency: One of "low" / "medium" / "high"; defaults to "medium".

        Returns:
            ``ConsultationResponse`` on success; ``None`` if the protocol
            rejected the request or no response was produced.
        """
        from probos.cognitive.consultation import (
            ConsultationRequest,
            ConsultationResponse,  # re-exported for the return type
            ConsultationUrgency,
        )

        protocol = self._consultation_protocol
        if protocol is None:
            logger.debug(
                "AD-594b: %s tried to consult but no protocol is wired; returning None",
                getattr(self, "callsign", None) or self.agent_type,
            )
            return None

        if not question:
            logger.warning(
                "AD-594b: %s called consult() with empty question; refusing",
                getattr(self, "callsign", None) or self.agent_type,
            )
            return None

        try:
            urgency_value = ConsultationUrgency(urgency)
        except ValueError:
            logger.warning(
                "AD-594b: invalid urgency=%r; defaulting to medium", urgency,
            )
            urgency_value = ConsultationUrgency.MEDIUM

        request = ConsultationRequest(
            requester_id=self.id,
            requester_callsign=getattr(self, "callsign", None) or self.agent_type,
            topic=topic or question,
            question=question,
            required_expertise=required_expertise,
            target_agent_id=target_agent_id,
            urgency=urgency_value,
            context=context or {},
        )
        return await protocol.request_consultation(request)

    def _build_temporal_context(self) -> str:
        """AD-502: Build temporal awareness header for agent prompts."""
        # Respect config if available
        rt = getattr(self, '_runtime', None)
        if rt and hasattr(rt, 'config') and hasattr(rt.config, 'temporal'):
            if not rt.config.temporal.enabled:
                return ""
            tcfg = rt.config.temporal
        else:
            tcfg = None  # No config available — include everything

        now = datetime.now(timezone.utc)
        parts = [f"Current time: {now.strftime('%Y-%m-%d %H:%M:%S UTC')} ({now.strftime('%A')})"]

        # AD-984d: the Captain's CURRENT local time when a timezone is
        # configured, so a reply about time-of-day is accurate rather than
        # inferred from UTC (the crew confabulated "3am" when it was 9pm
        # Mountain). This is a FACT provided to the crew, not an inference —
        # when unset, the crew see only UTC and must not assert a local time.
        # Honest-degrade (AD-592 spirit): a bad/unknown zone name leaves the
        # UTC line untouched.
        captain_tz = getattr(tcfg, "captain_timezone", "") if tcfg is not None else ""
        if captain_tz:
            try:
                from zoneinfo import ZoneInfo
                local = now.astimezone(ZoneInfo(captain_tz))
                parts.append(
                    f"Captain's local time: {local.strftime('%Y-%m-%d %H:%M:%S')} "
                    f"({local.strftime('%A')}, {captain_tz})"
                )
            except Exception:
                logger.debug(
                    "AD-984d: captain_timezone %r could not be resolved; UTC only",
                    captain_tz, exc_info=True,
                )

        # Birth age
        if (tcfg is None or tcfg.include_birth_time):
            birth_ts = getattr(self, '_birth_timestamp', None)
            if birth_ts:
                birth_dt = datetime.fromtimestamp(birth_ts, tz=timezone.utc)
                age = (now - birth_dt).total_seconds()
                parts.append(f"Your birth: {birth_dt.strftime('%Y-%m-%d %H:%M:%S UTC')} (age: {format_duration(age)})")
                # BF-102: Commissioning awareness for newly arrived crew
                if age < 300:
                    parts.append(
                        f"You were commissioned {format_duration(age)} ago. "
                        "You are a newly arrived crew member. "
                        "If someone welcomes you or mentions your name, "
                        "they are talking about YOU — respond as yourself."
                    )

        # System uptime
        if (tcfg is None or tcfg.include_system_uptime):
            sys_start = getattr(self, '_system_start_time', None)
            if sys_start:
                uptime = time.time() - sys_start
                parts.append(f"System uptime: {format_duration(uptime)}")

        # Last action recency
        if (tcfg is None or tcfg.include_last_action):
            if hasattr(self, 'meta') and self.meta.last_active:
                since_last = (now - self.meta.last_active).total_seconds()
                parts.append(f"Your last action: {format_duration(since_last)} ago")

        # Post count
        if (tcfg is None or tcfg.include_post_count):
            post_count = getattr(self, '_recent_post_count', None)
            if post_count is not None:
                parts.append(f"Your posts this hour: {post_count}")

        # AD-567g: Cognitive re-localization orientation
        orientation = getattr(self, '_orientation_rendered', None)
        if orientation:
            parts.append(orientation)

        # AD-513: Crew complement grounding (anti-confabulation)
        crew_complement = self._build_crew_complement()
        if crew_complement:
            parts.append(crew_complement)

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # AD-723: Sensorium dispatch (producer-side, Wave 144 v1)
    #
    # The dispatcher iterates SENSORIUM_REGISTRY entries whose ``paths``
    # tuple contains the requested path, calls the registered method with
    # ``observation``, and merges the result into a single dict keyed by
    # ``entry.output_key``. Two variants:
    #
    #   * ``_dispatch_sensorium_sync``  — chain paths (BASELINE / EXTENSIONS
    #     / SITUATION). Refuses async-registered methods (defense in depth).
    #   * ``_dispatch_sensorium_async`` — DM / WR one-shot paths. Awaits
    #     coroutine methods, calls sync methods directly. Producer-side v1
    #     ships the helper; AD-723a-1 wires the DM/WR consumer.
    #
    # Wrapper methods below (``_sensorium_*``) adapt existing helpers whose
    # signatures predate the dispatcher contract ``(observation: dict) ->
    # str | dict | None``.
    # ------------------------------------------------------------------

    def _sensorium_entries_for_path(
        self, path: SensoriumPath,
    ) -> list[tuple[str, "SensoriumEntry"]]:
        """AD-723: (priority asc, registration order) entries for the given path."""
        return sorted(
            (
                (name, entry)
                for name, entry in self.SENSORIUM_REGISTRY.items()
                if path in entry.paths
            ),
            key=lambda item: item[1].priority,
        )

    def _apply_sensorium_result(
        self,
        merged: dict[str, str],
        entry: "SensoriumEntry",
        method_name: str,
        result: object,
    ) -> None:
        """AD-723: merge a single registered-method result into the dispatch dict.

        ``None`` = removal (AD-646 semantics). ``str`` = keyed by
        ``entry.output_key``. ``dict`` = multi-key contribution. Anything
        else is logged-and-degraded (Tier 2).
        """
        if result is None:
            if entry.output_key:
                merged.pop(entry.output_key, None)
            return
        if isinstance(result, str):
            if not result:
                return
            if entry.output_key is None:
                logger.warning(
                    "AD-723: sensorium method %s returned str but registry "
                    "entry has no output_key; dropping. Configure output_key "
                    "on the entry or change the method to return dict.",
                    method_name,
                )
                return
            # AD-723a-3: optional wrapper applied to string outputs.
            # Tier-2 — wrapper failure logs DEBUG and stores the
            # raw output unchanged. Only applies when output_key is set
            # (dict-return contract is string-in-string-out only).
            if entry.wrapper is not None and callable(entry.wrapper):
                try:
                    result = entry.wrapper(result)
                except Exception:
                    logger.debug(
                        "AD-723a-3: wrapper raised for entry %s; using raw output",
                        method_name, exc_info=True,
                    )
            merged[entry.output_key] = result
            return
        if isinstance(result, dict):
            for k, v in result.items():
                if v is None:
                    merged.pop(k, None)
                elif isinstance(v, str) and v:
                    merged[k] = v
            return
        logger.warning(
            "AD-723: sensorium method %s returned %s; expected str | dict | None. "
            "Result dropped.",
            method_name,
            type(result).__name__,
        )

    def _dispatch_sensorium_sync(
        self,
        path: SensoriumPath,
        observation: dict,
    ) -> dict[str, str]:
        """AD-723: synchronous dispatch — used by chain paths.

        Raises ``RuntimeError`` if it encounters an async-registered method
        on the given path. At HEAD no async methods are registered for any
        chain path; this guard catches future regressions before they
        silently drop telemetry.
        """
        merged: dict[str, str] = {}
        for method_name, entry in self._sensorium_entries_for_path(path):
            method = getattr(self, method_name, None)
            if method is None:
                logger.warning(
                    "AD-723: sensorium method %s not bound on %s; skipping. "
                    "Registry entry exists but the class has no such attribute.",
                    method_name, type(self).__name__,
                )
                continue
            if inspect.iscoroutinefunction(method):
                raise RuntimeError(
                    f"AD-723: async method {method_name} registered on sync "
                    f"path {path.value}; use _dispatch_sensorium_async or "
                    f"change the entry's paths tuple."
                )
            try:
                result = method(observation)
            except Exception:
                logger.debug(
                    "AD-723: sensorium method %s raised on path %s; "
                    "degrading (Tier-2: skipped, dispatch continues).",
                    method_name, path.value, exc_info=True,
                )
                continue
            self._apply_sensorium_result(merged, entry, method_name, result)
        return merged

    async def _dispatch_sensorium_async(
        self,
        path: SensoriumPath,
        observation: dict,
    ) -> dict[str, str]:
        """AD-723: asynchronous dispatch — used by DM and WR one-shot paths.

        Handles both sync and async registered methods uniformly via
        ``inspect.iscoroutinefunction``. AD-723 v1 ships this dispatcher
        as producer-side infrastructure; the DM/WR consumer migration in
        ``_build_user_message`` is deferred to AD-723a-1 (#617).
        """
        merged: dict[str, str] = {}
        for method_name, entry in self._sensorium_entries_for_path(path):
            method = getattr(self, method_name, None)
            if method is None:
                logger.warning(
                    "AD-723: sensorium method %s not bound on %s; skipping. "
                    "Registry entry exists but the class has no such attribute.",
                    method_name, type(self).__name__,
                )
                continue
            try:
                if inspect.iscoroutinefunction(method):
                    result = await method(observation)
                else:
                    result = method(observation)
            except Exception:
                logger.debug(
                    "AD-723: sensorium method %s raised on path %s; "
                    "degrading (Tier-2: skipped, dispatch continues).",
                    method_name, path.value, exc_info=True,
                )
                continue
            self._apply_sensorium_result(merged, entry, method_name, result)
        return merged

    # ------------------------------------------------------------------
    # AD-723: Sensorium wrappers — adapt legacy helper signatures
    # ------------------------------------------------------------------

    def _sensorium_temporal_context(self, observation: dict) -> str:
        """AD-723 dispatch wrapper for ``_build_temporal_context``."""
        del observation
        return self._build_temporal_context()

    def _sensorium_working_memory(self, observation: dict) -> str:
        """AD-723 dispatch wrapper for the working-memory render.

        Returns ``""`` (no contribution; dispatcher skips without popping)
        when the agent has no working memory or it renders empty.
        """
        del observation
        wm = getattr(self, "_working_memory", None)
        if wm is None:
            return ""
        return wm.render_context(budget=1500) or ""

    def _sensorium_comm_proficiency(self, observation: dict) -> str:
        """AD-723 dispatch wrapper for ``_get_comm_proficiency_guidance``.

        Returns ``""`` (no contribution) instead of ``None`` so the
        baseline-dispatch doesn't pop a same-key entry written earlier.
        """
        del observation
        return self._get_comm_proficiency_guidance() or ""

    def _sensorium_self_recognition(self, observation: dict) -> str:
        """AD-723 dispatch wrapper for ``_detect_self_in_content``.

        Returns ``""`` (no contribution) when no self-cue is found.
        """
        content = observation.get("context", "") if observation else ""
        if not content:
            return ""
        return self._detect_self_in_content(content) or ""

    # ------------------------------------------------------------------
    # AD-723: Sensorium extracted methods — chain baseline inline blocks
    # ------------------------------------------------------------------

    def _sensorium_agent_metrics(self, observation: dict) -> str:
        """AD-723 extraction of baseline step 3: trust / initiative / agency / rank."""
        del observation
        try:
            rt = getattr(self, "_runtime", None)
            trust_val: float | str = 0.5
            rank_val = "ensign"
            agency_val = "ensign"
            initiative_val = 0
            if rt and hasattr(rt, "trust_network"):
                from probos.crew_profile import Rank
                from probos.earned_agency import agency_from_rank, resolve_initiative_level
                from probos.config import format_trust
                trust_val = rt.trust_network.get_score(self.id)
                rank_val = Rank.from_trust(trust_val).value
                agency_val = agency_from_rank(Rank.from_trust(trust_val)).value
                thresholds = (
                    rt.config.earned_agency.initiative_trust_thresholds
                    if rt is not None and getattr(rt, "config", None) is not None
                    else None
                )
                initiative_val = resolve_initiative_level(
                    Rank.from_trust(trust_val),
                    trust_val,
                    thresholds=thresholds,
                ).value
                trust_val = format_trust(trust_val)
            return (
                f"Your trust: {trust_val} | Initiative: {initiative_val} | "
                f"Agency: {agency_val} | "
                f"Rank: {rank_val}"
            )
        except Exception:
            logger.debug(
                "AD-723: agent metrics extraction failed; falling back to default",
                exc_info=True,
            )
            return "Your trust: 0.5 | Agency: ensign | Rank: ensign"

    def _sensorium_ontology_baseline(self, observation: dict) -> str:
        """AD-723 extraction of baseline step 4: ontology grounding.

        Returns ``""`` (no contribution) when runtime / ontology is
        unavailable; never ``None`` so it cannot accidentally pop a
        same-key entry on the baseline dispatch.
        """
        del observation
        try:
            rt = getattr(self, "_runtime", None)
            if not (rt and hasattr(rt, "ontology")):
                return ""
            ontology = rt.ontology.get_crew_context(self.agent_type)
            if not ontology:
                return ""
            onto_parts: list[str] = []
            identity = ontology.get("identity", {})
            dept = ontology.get("department", {})
            vessel = ontology.get("vessel", {})
            onto_parts.append(
                f"You are {identity.get('callsign', '?')}, "
                f"{identity.get('post', '?')} in {dept.get('name', '?')} department."
            )
            if ontology.get("reports_to"):
                onto_parts.append(f"You report to {ontology['reports_to']}.")
            if ontology.get("direct_reports"):
                onto_parts.append(f"Your direct reports: {', '.join(ontology['direct_reports'])}.")
            if ontology.get("peers"):
                onto_parts.append(f"Department peers: {', '.join(ontology['peers'])}.")
            if vessel:
                alert = vessel.get("alert_condition", "GREEN")
                onto_parts.append(
                    f"Ship status: {vessel.get('name', 'ProbOS')} "
                    f"v{vessel.get('version', '?')} — Alert Condition {alert}."
                )
            caps = ontology.get("capabilities", [])
            if caps:
                cap_lines = [f"- {c['summary']}" for c in caps]
                onto_parts.append(
                    "Your post capabilities (what you actually do):\n"
                    + "\n".join(cap_lines)
                )
            negatives = ontology.get("does_not_have", [])
            if negatives:
                neg_lines = [f"- {n}" for n in negatives]
                onto_parts.append(
                    "You do NOT have (do not claim or reference these):\n"
                    + "\n".join(neg_lines)
                )
            return "\n".join(onto_parts)
        except Exception:
            logger.debug(
                "AD-723: ontology baseline extraction failed; skipping",
                exc_info=True,
            )
            return ""

    def _sensorium_source_attribution_baseline(self, observation: dict) -> str:
        """AD-723 extraction of baseline step 5: simplified source attribution."""
        memories = observation.get("recent_memories", []) if observation else []
        sources: list[str] = []
        if memories and isinstance(memories, list):
            sources.append(f"episodic memory ({len(memories)} episodes)")
        if not sources:
            sources.append("training knowledge only")
        return (
            f"[Source awareness: Your response draws on: {', '.join(sources)}. "
            f"Source quality: unknown.]"
        )

    def _sensorium_confab_guard_baseline(self, observation: dict) -> str:
        """AD-723 extraction of baseline step 6: generic confabulation guard."""
        del observation
        return self._confabulation_guard(None)

    def _sensorium_no_memories_flag(self, observation: dict) -> str:
        """AD-723 extraction of baseline step 7: no-memories flag.

        Returns ``""`` (no contribution) when memories are present, so the
        baseline dispatch leaves the key unset rather than popping it.
        The extensions-side ``_sensorium_ext_no_memories_flag_override``
        keeps the AD-646 ``None``-removal semantic for proactive paths.
        """
        memories = observation.get("recent_memories", []) if observation else []
        if not memories or not isinstance(memories, list):
            return (
                "You have no stored episodic memories yet. "
                "Do not reference or invent past experiences you do not have."
            )
        return ""

    def _sensorium_cold_start_note(self, observation: dict) -> str:
        """AD-723 extraction of baseline step 9: BF-102 cold-start runtime note.

        AD-1077: when NOT in cold-start, this situational slot carries a
        transient proactive self-note (e.g. a group-chat suppression coaching
        message) threaded in via proactive ``context_parts['system_note']`` — so
        a suppressed [GROUP_CHAT] attempt is fed back to the agent on its next
        cycle instead of failing silently. Returns ``""`` when neither applies.
        """
        rt = getattr(self, "_runtime", None)
        if rt and getattr(rt, "is_cold_start", False):
            return (
                "SYSTEM NOTE: This is a fresh start. You have no prior "
                "episodic memories. Do not reference or invent past experiences."
            )
        cp = observation.get("_context_parts") if isinstance(observation, dict) else None
        note = (cp or {}).get("system_note") if isinstance(cp, dict) else None
        return str(note) if note else ""

    def _sensorium_source_attribution_rich(self, observation: dict) -> str:
        """AD-723 extraction of baseline step 10: AD-568d rich attribution override.

        Returns ``""`` (no contribution; preserves the prior
        ``_source_attribution_text`` key written by the baseline entry)
        when no rich attribution is attached to the observation.
        """
        attr = observation.get("_source_attribution") if observation else None
        if not attr:
            return ""
        try:
            sources_present: list[str] = []
            if attr.episodic_count > 0:
                sources_present.append(f"episodic memory ({attr.episodic_count} episodes)")
            if attr.procedural_count > 0:
                sources_present.append(f"learned procedures ({attr.procedural_count})")
            if attr.oracle_used:
                sources_present.append("ship's records")
            if not sources_present:
                sources_present.append("training knowledge only")
            return (
                f"<source_awareness>Your response draws on: {', '.join(sources_present)}. "
                f"Primary basis: {attr.primary_source.value}.</source_awareness>"
            )
        except Exception:
            logger.debug(
                "AD-723: rich source attribution extraction failed; skipping",
                exc_info=True,
            )
            return ""

    # ------------------------------------------------------------------
    # AD-723: Sensorium extracted methods — chain extensions
    # The dispatcher passes ``observation`` containing ``_context_parts``;
    # extension methods read context_parts from it.
    # ------------------------------------------------------------------

    @staticmethod
    def _ext_context_parts(observation: dict) -> dict:
        return observation.get("_context_parts", {}) if observation else {}

    def _sensorium_ext_self_monitoring(self, observation: dict) -> str:
        """AD-723 extraction of extensions step 1: AD-504/506a self-monitoring.

        Returns ``""`` (no contribution) when self_monitoring is absent
        from context_parts; no baseline-set ``_self_monitoring`` key to pop.
        """
        context_parts = observation.get("_context_parts", {}) if observation else {}
        self_mon = context_parts.get("self_monitoring")
        if not self_mon:
            return ""
        sm_parts: list[str] = []
        zone = self_mon.get("cognitive_zone")
        zone_note = self_mon.get("zone_note")
        if zone:
            sm_parts.append(f"<cognitive_zone>{zone.upper()}</cognitive_zone>")
            if zone_note:
                sm_parts.append(zone_note)
        recent_posts = self_mon.get("recent_posts")
        if recent_posts:
            sm_parts.append("Your recent posts (review before adding):")
            for p in recent_posts:
                age_str = f"[{p['age']} ago]" if p.get("age") else ""
                sm_parts.append(f"  - {age_str} {p['body']}")
        sim = self_mon.get("self_similarity")
        if sim is not None:
            sm_parts.append(f"Self-similarity across recent posts: {sim:.2f}")
            if sim >= 0.5:
                sm_parts.append(
                    "WARNING: Your recent posts show high similarity. "
                    "Before posting, ensure you have GENUINELY NEW information. "
                    "If not, respond with [NO_RESPONSE]."
                )
            elif sim >= 0.3:
                sm_parts.append(
                    "Note: Some similarity in your recent posts. "
                    "Consider whether you are adding new insight or restating."
                )
        if self_mon.get("cooldown_increased"):
            sm_parts.append(
                "Your proactive cooldown has been increased due to rising similarity. "
                "This is pacing, not punishment — take time to find fresh perspectives."
            )
        if self_mon.get("cooldown_reason"):
            sm_parts.append(f"  Counselor note: {self_mon['cooldown_reason']}")
        mem_state = self_mon.get("memory_state")
        if mem_state:
            count = mem_state.get("episode_count", 0)
            lifecycle = mem_state.get("lifecycle", "")
            uptime_hrs = mem_state.get("uptime_hours", 0)
            if count < 5 and lifecycle != "reset" and uptime_hrs > 1:
                sm_parts.append(
                    f"Note: You have {count} episodic memories, but the system has been "
                    f"running for {uptime_hrs:.1f}h. Other crew may have richer histories. "
                    "Do not generalize from your own sparse memory to the crew's state."
                )
        nb_index = self_mon.get("notebook_index")
        if nb_index:
            topics = ", ".join(
                f"{e['topic']} (updated {e['updated']})" if e.get("updated") else e["topic"]
                for e in nb_index
            )
            sm_parts.append(f"Your notebooks: [{topics}]")
            sm_parts.append(
                "Use [NOTEBOOK topic-slug] to update. "
                "Use [READ_NOTEBOOK topic-slug] to review a notebook next cycle."
            )
        nb_content = self_mon.get("notebook_content")
        if nb_content:
            sm_parts.append(f'<notebook topic="{nb_content["topic"]}">')
            sm_parts.append(nb_content["snippet"])
            sm_parts.append("</notebook>")
        if not sm_parts:
            return ""
        return "\n".join(sm_parts)

    def _sensorium_ext_source_attribution_authority(self, observation: dict) -> str:
        """AD-723 extraction of extensions step 2: authority-aware source attribution.

        Returns ``""`` when context_parts contains no memories AND no
        ``_source_framing``; this preserves the baseline-set
        ``_source_attribution_text`` key (no implicit pop).
        """
        context_parts = observation.get("_context_parts", {}) if observation else {}
        memories = context_parts.get("recent_memories", [])
        framing = context_parts.get("_source_framing")
        if not (memories or framing):
            return ""
        sources: list[str] = []
        if memories:
            sources.append(f"episodic memory ({len(memories)} episodes)")
        if not sources:
            sources.append("training knowledge only")
        authority = getattr(framing, "authority", None) if framing else None
        auth_label = getattr(authority, "value", "unknown") if authority else "unknown"
        return (
            f"[Source awareness: Your response draws on: {', '.join(sources)}. "
            f"Source quality: {auth_label}.]"
        )

    def _sensorium_ext_introspective_telemetry(self, observation: dict) -> str:
        """AD-723 extraction of extensions step 3: AD-588 introspective telemetry."""
        context_parts = observation.get("_context_parts", {}) if observation else {}
        return context_parts.get("introspective_telemetry") or ""

    def _sensorium_ext_ontology_from_context_parts(self, observation: dict) -> str:
        """AD-723 extraction of extensions step 4: ontology override from context_parts.

        Returns ``""`` (no contribution; baseline ontology key preserved)
        when context_parts has no ``ontology`` entry.
        """
        context_parts = observation.get("_context_parts", {}) if observation else {}
        ontology = context_parts.get("ontology")
        if not ontology:
            return ""
        onto_parts: list[str] = []
        identity = ontology.get("identity", {})
        dept = ontology.get("department", {})
        vessel = ontology.get("vessel", {})
        onto_parts.append(
            f"You are {identity.get('callsign', '?')}, "
            f"{identity.get('post', '?')} in {dept.get('name', '?')} department."
        )
        if ontology.get("reports_to"):
            onto_parts.append(f"You report to {ontology['reports_to']}.")
        if ontology.get("direct_reports"):
            onto_parts.append(f"Your direct reports: {', '.join(ontology['direct_reports'])}.")
        if ontology.get("peers"):
            onto_parts.append(f"Department peers: {', '.join(ontology['peers'])}.")
        if vessel:
            alert = vessel.get("alert_condition", "GREEN")
            onto_parts.append(
                f"Ship status: {vessel.get('name', 'ProbOS')} "
                f"v{vessel.get('version', '?')} — Alert Condition {alert}."
            )
        return "\n".join(onto_parts)

    def _sensorium_ext_orientation_supplement(self, observation: dict) -> str:
        """AD-723 extraction of extensions step 5: AD-567g orientation supplement."""
        context_parts = observation.get("_context_parts", {}) if observation else {}
        return context_parts.get("orientation_supplement") or ""

    def _sensorium_ext_confab_guard_authority(self, observation: dict) -> str:
        """AD-723 extraction of extensions step 6: authority-calibrated confab guard.

        Returns ``""`` (no contribution; baseline confab-guard preserved)
        when no authority is attached to the source framing.
        """
        context_parts = observation.get("_context_parts", {}) if observation else {}
        framing = context_parts.get("_source_framing")
        authority = getattr(framing, "authority", None) if framing else None
        if authority is None:
            return ""
        return self._confabulation_guard(authority)

    def _sensorium_ext_no_memories_flag_override(self, observation: dict) -> str | None:
        """AD-723 extraction of extensions step 7: no-memories flag override.

        Preserves AD-646 None-removal semantics: returning ``None`` signals
        the dispatcher to pop the baseline-set ``_no_episodic_memories`` key.
        Returning the flag string sets it (when context_parts present but
        memories empty). Method only contributes when context_parts has a
        ``_source_framing`` marker (otherwise no opinion — preserves
        baseline behaviour).
        """
        context_parts = observation.get("_context_parts", {}) if observation else {}
        memories = context_parts.get("recent_memories", [])
        framing = context_parts.get("_source_framing")
        if memories:
            # AD-646: signal removal of baseline's no-memories flag
            return None
        if not memories and framing is not None:
            return (
                "You have no stored episodic memories yet. "
                "Do not reference or invent past experiences you do not have."
            )
        return None

    # ------------------------------------------------------------------
    # AD-723: Sensorium extracted methods — chain situation awareness
    # ------------------------------------------------------------------

    def _sensorium_situation_ward_room_activity(self, observation: dict) -> str | None:
        context_parts = observation.get("_context_parts", {}) if observation else {}
        wr_activity = context_parts.get("ward_room_activity", [])
        if not wr_activity:
            return None
        wr_lines = ["Recent Ward Room discussion:"]
        for a in wr_activity:
            prefix = "[thread]" if a.get("type") == "thread" else "[reply]"
            ids = ""
            if a.get("thread_id"):
                ids += f" thread:{a['thread_id'][:8]}"
            if a.get("post_id"):
                ids += f" post:{a['post_id'][:8]}"
            score = a.get("net_score", 0)
            score_str = f" [+{score}]" if score > 0 else f" [{score}]" if score < 0 else ""
            channel = f" ({a['channel']})" if a.get("channel") else ""
            wr_lines.append(
                f"  - {prefix}{ids}{score_str} {a.get('author', '?')}{channel}: "
                f"{a.get('body', '?')}"
            )
        return "\n".join(wr_lines)

    def _sensorium_situation_recent_alerts(self, observation: dict) -> str | None:
        context_parts = observation.get("_context_parts", {}) if observation else {}
        alerts = context_parts.get("recent_alerts", [])
        if not alerts:
            return None
        alert_lines = ["Recent bridge alerts:"]
        for a in alerts:
            alert_lines.append(
                f"  - [{a.get('severity', '?')}] {a.get('title', '?')} "
                f"(from {a.get('source', '?')})"
            )
        return "\n".join(alert_lines)

    def _sensorium_situation_recent_events(self, observation: dict) -> str | None:
        context_parts = observation.get("_context_parts", {}) if observation else {}
        events = context_parts.get("recent_events", [])
        if not events:
            return None
        event_lines = ["Recent system events:"]
        for e in events:
            event_lines.append(
                f"  - [{e.get('category', '?')}] {e.get('event', '?')}"
            )
        return "\n".join(event_lines)

    def _sensorium_situation_infrastructure(self, observation: dict) -> str | None:
        context_parts = observation.get("_context_parts", {}) if observation else {}
        infra = context_parts.get("infrastructure_status")
        if not infra:
            return None
        llm_status = infra.get("llm_status", "unknown")
        return (
            f"[INFRASTRUCTURE NOTE: Communications array {llm_status}]\n"
            f"{infra.get('message', '')}"
        )

    def _sensorium_situation_subordinate_stats(self, observation: dict) -> str | None:
        context_parts = observation.get("_context_parts", {}) if observation else {}
        sub_stats = context_parts.get("subordinate_stats")
        if not sub_stats:
            return None
        sub_lines = ["<subordinate_activity>"]
        for callsign, stats in sub_stats.items():
            sub_lines.append(
                f"  {callsign}: {stats['posts_total']} posts, "
                f"{stats['endorsements_given']} endorsements given, "
                f"{stats['endorsements_received']} endorsements received, "
                f"credibility {stats['credibility_score']:.2f}"
            )
        sub_lines.append("</subordinate_activity>")
        return "\n".join(sub_lines)

    def _sensorium_situation_clinical_telemetry(self, observation: dict) -> str | None:
        context_parts = observation.get("_context_parts", {}) if observation else {}
        clin = context_parts.get("clinical_telemetry")
        if not clin:
            return None
        clin_lines = ["<clinical_telemetry>"]
        dreams = clin.get("dreams")
        if isinstance(dreams, dict):
            clin_lines.append(f"  dreams: {dreams.get('count', 0)} recent")
        traces = clin.get("chain_traces")
        if isinstance(traces, dict):
            clin_lines.append(
                f"  chain_traces: {traces.get('count', 0)} self "
                f"(latest_outcome={traces.get('latest_outcome', 'unknown')})"
            )
        breakers = clin.get("breakers")
        if isinstance(breakers, dict):
            recent = breakers.get("recent_transitions") or []
            clin_lines.append(
                f"  breakers: {breakers.get('count', 0)} transitions "
                f"(recent={len(recent)})"
            )
            for tr in recent:
                if not isinstance(tr, dict):
                    continue
                clin_lines.append(
                    f"    - {tr.get('agent', '?')}: "
                    f"{tr.get('from', '?')}->{tr.get('to', '?')}"
                )
        clin_lines.append("</clinical_telemetry>")
        return "\n".join(clin_lines)

    def _sensorium_situation_system_note(self, observation: dict) -> str | None:
        context_parts = observation.get("_context_parts", {}) if observation else {}
        return context_parts.get("system_note") or None

    def _sensorium_situation_active_game(self, observation: dict) -> str | None:
        context_parts = observation.get("_context_parts", {}) if observation else {}
        active_game = context_parts.get("active_game")
        if not active_game:
            return None
        game_lines = [
            f"You are playing {active_game['game_type']} against "
            f"{active_game['opponent']}. "
            f"Moves so far: {active_game['moves_count']}.",
            f"\nCurrent board:\n```\n{active_game['board']}\n```",
        ]
        if active_game["is_my_turn"]:
            game_lines.append(
                f"**It is YOUR turn.** Valid moves: "
                f"{', '.join(str(m) for m in active_game['valid_moves'])}. "
                f"Reply with [MOVE position] to play."
            )
        else:
            game_lines.append("Waiting for your opponent to move.")
        return "\n".join(game_lines)

    def _build_cognitive_baseline(self, observation: dict) -> dict[str, str]:
        """AD-646: Agent-intrinsic cognitive state — runs for ALL chain executions.

        Produces baseline self-knowledge from agent attributes and runtime
        services. Zero dependency on context_parts (which only proactive.py
        populates). Ward Room chains get temporal awareness, working memory,
        trust metrics, ontology, and confabulation guards.

        AD-723 v1 (producer-side): this is now a thin shim around
        ``_dispatch_sensorium_sync(CHAIN_BASELINE, ...)``. Each former
        numbered step is registered as a ``_sensorium_*`` entry in
        ``SENSORIUM_REGISTRY``. The dispatcher iterates the registry in
        registration order (insertion-stable for same-priority entries),
        preserving the legacy dict-key insertion order. Signature is
        unchanged so ~17 existing test call sites keep passing.
        """
        return self._dispatch_sensorium_sync(SensoriumPath.CHAIN_BASELINE, observation)

    def _build_cognitive_extensions(self, context_parts: dict) -> dict[str, str]:
        """AD-646: Context-parts-dependent cognitive state — proactive path only.

        Returns keys that override baseline with richer versions when
        context_parts is available (populated by proactive.py _gather_context()).

        AD-723 v1 (producer-side): thin shim around
        ``_dispatch_sensorium_sync(CHAIN_EXTENSIONS, ...)``. Extension
        entries register at ``priority=10`` so they run after baseline
        (``priority=0``); AD-646 None-for-removal semantics are preserved
        through ``_apply_sensorium_result``. Signature unchanged so
        ~17 existing test call sites keep passing.
        """
        return self._dispatch_sensorium_sync(
            SensoriumPath.CHAIN_EXTENSIONS,
            {"_context_parts": context_parts},
        )

    def _build_cognitive_state(self, context_parts: dict, observation: dict | None = None) -> dict[str, str]:
        """AD-644 Phase 2 / AD-646: Populate innate faculty observation keys for chain prompts.

        Delegates to baseline (always runs) + extensions (context_parts-dependent).
        Baseline provides agent-intrinsic self-knowledge; extensions override with
        richer versions when proactive.py's context_parts is available.

        AD-666: This is the interoception hub of the Agent Sensorium — the agent's
        structured self-state snapshot. See SENSORIUM_REGISTRY for the full inventory.

        AD-723 v1 (producer-side): single-dict variant — dispatcher writes
        baseline then extensions into the SAME merged dict so AD-646
        None-removal in extensions correctly pops baseline-set keys (e.g.
        ``_no_episodic_memories``).
        """
        obs = observation or {}
        if context_parts:
            obs = {**obs, "_context_parts": context_parts}
        state: dict[str, str] = {}
        paths: tuple[SensoriumPath, ...] = (SensoriumPath.CHAIN_BASELINE,)
        if context_parts:
            paths = (SensoriumPath.CHAIN_BASELINE, SensoriumPath.CHAIN_EXTENSIONS)
        for path in paths:
            for method_name, entry in self._sensorium_entries_for_path(path):
                method = getattr(self, method_name, None)
                if method is None or inspect.iscoroutinefunction(method):
                    continue
                try:
                    result = method(obs)
                except Exception:
                    logger.debug(
                        "AD-723: sensorium method %s raised on path %s; "
                        "degrading (Tier-2: skipped).",
                        method_name, path.value, exc_info=True,
                    )
                    continue
                self._apply_sensorium_result(state, entry, method_name, result)
        return state

    def _track_sensorium_budget(
        self,
        cognitive_state: dict[str, str],
        situation: dict[str, str],
    ) -> int:
        """AD-1122: Measure and debounce merged chain-sensorium telemetry."""
        contributors = self._sensorium_budget_contributors(cognitive_state, situation)
        cognitive_chars = sum(
            int(row["chars"]) for row in contributors if row["bucket"] == "cognitive"
        )
        situation_chars = sum(
            int(row["chars"]) for row in contributors if row["bucket"] == "situation"
        )
        total_chars = cognitive_chars + situation_chars

        runtime = getattr(self, "_runtime", None)
        sensorium_config = getattr(getattr(runtime, "config", None), "sensorium", None)
        enabled = getattr(sensorium_config, "enabled", True)
        if not isinstance(enabled, bool):
            enabled = True
        threshold = self._sensorium_budget_int_setting(
            sensorium_config, "warning_chars", 10_000, minimum=1
        )
        cooldown = self._sensorium_budget_float_setting(
            sensorium_config, "warning_cooldown_seconds", 21_600.0, minimum=0.0
        )
        rearm_ratio = self._sensorium_budget_float_setting(
            sensorium_config,
            "warning_rearm_ratio",
            0.90,
            minimum=0.0,
            maximum=1.0,
            strict_minimum=True,
            strict_maximum=True,
        )
        escalation_ratio = self._sensorium_budget_float_setting(
            sensorium_config,
            "warning_escalation_ratio",
            1.25,
            minimum=1.0,
        )
        top_count = self._sensorium_budget_int_setting(
            sensorium_config, "top_contributors", 5, minimum=0
        )

        previous_threshold = getattr(self, "_sensorium_budget_last_threshold", None)
        if previous_threshold is not None and previous_threshold != threshold:
            self._reset_sensorium_budget_state()
        self._sensorium_budget_last_threshold = threshold

        if not enabled:
            self._reset_sensorium_budget_state()
            return total_chars

        active = getattr(self, "_sensorium_budget_active", False)
        if active and total_chars < threshold * rearm_ratio:
            self._reset_sensorium_budget_state()
            self._sensorium_budget_last_threshold = threshold
            return total_chars
        if total_chars <= threshold:
            return total_chars
        if not active:
            reason = "crossed"
        else:
            current_peak = max(
                int(getattr(self, "_sensorium_budget_peak_chars", 0)), total_chars
            )
            now = self._sensorium_budget_clock()
            escalated = not getattr(
                self, "_sensorium_budget_escalation_consumed", False
            ) and total_chars >= threshold * escalation_ratio
            last_emitted_at = getattr(self, "_sensorium_budget_last_emitted_at", None)
            cooldown_elapsed = (
                last_emitted_at is None or now - last_emitted_at >= cooldown
            )
            if escalated:
                reason = "escalated"
            elif cooldown_elapsed:
                reason = "sustained"
            else:
                self._sensorium_budget_suppressed_count += 1
                self._sensorium_budget_peak_chars = current_peak
                return total_chars

        now = self._sensorium_budget_clock()
        prior_suppressed = int(getattr(self, "_sensorium_budget_suppressed_count", 0))
        peak_chars = max(
            int(getattr(self, "_sensorium_budget_peak_chars", 0)), total_chars
        )
        initial_severe = reason == "crossed" and total_chars >= threshold * escalation_ratio

        # Commit transition state before any warning/event side effect. A sink
        # failure must not replay the same crossing on the next cycle.
        self._sensorium_budget_active = True
        self._sensorium_budget_last_emitted_at = now
        self._sensorium_budget_suppressed_count = 0
        self._sensorium_budget_peak_chars = total_chars
        if reason == "escalated" or initial_severe:
            self._sensorium_budget_escalation_consumed = True

        agent_id = getattr(self, "id", "unknown")
        callsign = self._resolve_callsign() or agent_id
        estimated_tokens = sum(
            int(row["estimated_tokens"]) for row in contributors
        )
        top_rows = sorted(
            contributors,
            key=lambda row: (
                -int(row["chars"]),
                str(row["output_key"]),
                str(row["bucket"]),
            ),
        )[:top_count]
        try:
            logger.warning(
                "AD-1122 sensorium budget transition: agent_id=%s callsign=%s "
                "reason=%s total_chars=%d estimated_tokens=%d character_threshold=%d "
                "cognitive_state_chars=%d situation_chars=%d suppressed_count=%d "
                "peak_chars=%d top_contributors=%s; merged chain sensorium character "
                "footprint; not the full request/model-window measurement.",
                agent_id,
                callsign,
                reason,
                total_chars,
                estimated_tokens,
                threshold,
                cognitive_chars,
                situation_chars,
                prior_suppressed,
                peak_chars,
                top_rows,
            )
        except Exception:
            # Observe-only telemetry must not fail its caller or skip the event sink.
            pass
        if runtime is not None:
            event = SensoriumBudgetExceededEvent(
                agent_id=agent_id,
                callsign=callsign,
                total_chars=total_chars,
                threshold=threshold,
                cognitive_state_chars=cognitive_chars,
                situation_chars=situation_chars,
                estimated_tokens=estimated_tokens,
                character_threshold=threshold,
                reason=reason,
                suppressed_count=prior_suppressed,
                peak_chars=peak_chars,
                top_contributors=top_rows,
            )
            try:
                runtime.emit_event(event)
            except Exception:
                try:
                    logger.warning(
                        "AD-1122 sensorium_budget_exceeded event emission failed for agent "
                        "%s (%s); transition state remains committed and telemetry "
                        "continues with local warnings.",
                        agent_id,
                        callsign,
                        exc_info=True,
                    )
                except Exception:
                    # No recursive diagnostics: both telemetry sinks are non-critical.
                    pass

        return total_chars

    def _reset_sensorium_budget_state(self) -> None:
        """Reset bounded per-agent sensorium transition state."""
        self._sensorium_budget_active = False
        self._sensorium_budget_last_emitted_at: float | None = None
        self._sensorium_budget_suppressed_count = 0
        self._sensorium_budget_peak_chars = 0
        self._sensorium_budget_escalation_consumed = False
        self._sensorium_budget_last_threshold: int | None = None

    def _sensorium_budget_clock(self) -> float:
        """Return the monotonic clock used by sensorium debounce policy."""
        return time.monotonic()

    @staticmethod
    def _sensorium_budget_int_setting(
        config: object | None,
        name: str,
        default: int,
        *,
        minimum: int,
    ) -> int:
        """Read one bounded integer policy field with an independent fallback."""
        value = getattr(config, name, default)
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            return default
        return value

    @staticmethod
    def _sensorium_budget_float_setting(
        config: object | None,
        name: str,
        default: float,
        *,
        minimum: float,
        maximum: float | None = None,
        strict_minimum: bool = False,
        strict_maximum: bool = False,
    ) -> float:
        """Read one finite numeric policy field with an independent fallback."""
        value = getattr(config, name, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return default
        numeric = float(value)
        if not math.isfinite(numeric):
            return default
        if numeric < minimum or (strict_minimum and numeric == minimum):
            return default
        if maximum is not None and (
            numeric > maximum or (strict_maximum and numeric == maximum)
        ):
            return default
        return numeric

    @classmethod
    def _sensorium_budget_layer(
        cls, output_key: str, bucket: str
    ) -> str | None:
        """Resolve a contributor's unique registry layer for its chain bucket."""
        allowed_paths = (
            {SensoriumPath.CHAIN_BASELINE, SensoriumPath.CHAIN_EXTENSIONS}
            if bucket == "cognitive"
            else {SensoriumPath.CHAIN_SITUATION}
        )
        layers = {
            entry.layer.value
            for entry in cls.SENSORIUM_REGISTRY.values()
            if entry.output_key == output_key and allowed_paths.intersection(entry.paths)
        }
        return next(iter(layers)) if len(layers) == 1 else None

    @classmethod
    def _sensorium_budget_contributors(
        cls,
        cognitive_state: dict[str, str],
        situation: dict[str, str],
    ) -> list[dict[str, str | int | None]]:
        """Describe final surviving non-empty strings without retaining content."""
        rows: list[dict[str, str | int | None]] = []
        for bucket, values in (
            ("cognitive", cognitive_state),
            ("situation", situation),
        ):
            for output_key, value in values.items():
                if not isinstance(value, str) or not value:
                    continue
                rows.append(
                    {
                        "bucket": bucket,
                        "output_key": output_key,
                        "layer": cls._sensorium_budget_layer(output_key, bucket),
                        "chars": len(value),
                        "estimated_tokens": estimate_tokens(value),
                    }
                )
        return rows

    def _build_situation_awareness(self, context_parts: dict) -> dict[str, str]:
        """AD-644 Phase 3: Extract situation awareness data for chain prompts.

        Returns a dict of observation keys → rendered strings. Called from
        _execute_chain_with_intent_routing() after Phase 2 cognitive state.

        These are environmental percepts — what's happening around the agent.
        The one-shot path renders these inline in _build_user_message().
        This method extracts them into observation keys so ANALYZE can
        render the current situation.

        AD-723 v1 (producer-side): inlined dispatch loop. Methods are
        resolved through ``CognitiveAgent`` (the class) rather than
        ``self`` so the existing AD-635f test pattern
        ``CognitiveAgent._build_situation_awareness(MagicMock(spec=...),
        ctx)`` continues to pass — the registered situation methods are
        pure functions of ``observation['_context_parts']`` (no ``self.*``
        attribute access required), so the class-bound resolution works
        with both real and Mock ``self``.
        """
        obs = {"_context_parts": context_parts}
        state: dict[str, str] = {}
        for method_name, entry in CognitiveAgent.SENSORIUM_REGISTRY.items():
            if SensoriumPath.CHAIN_SITUATION not in entry.paths:
                continue
            method = getattr(CognitiveAgent, method_name, None)
            if method is None or inspect.iscoroutinefunction(method):
                continue
            try:
                result = method(self, obs)
            except Exception:
                logger.debug(
                    "AD-723: situation method %s raised; degrading (Tier-2).",
                    method_name, exc_info=True,
                )
                continue
            CognitiveAgent._apply_sensorium_result(self, state, entry, method_name, result)
        return state

    # AD-588: Introspective self-query detection patterns
    _INTROSPECTIVE_PATTERNS: ClassVar[list[re.Pattern]] = [
        re.compile(r"\b(?:your|you)\b.*\b(?:memor(?:y|ies)|remember|recall|forget|episode)\b", re.IGNORECASE),
        re.compile(r"\b(?:your|you)\b.*\b(?:trust|reputation|reliab|scor)\b", re.IGNORECASE),
        re.compile(r"\b(?:how (?:are|do) you|how.*feel|what.*(?:like for you)|your (?:state|status))\b", re.IGNORECASE),
        re.compile(r"\b(?:how (?:do|does) your|your (?:brain|mind|cognit|process|think))\b", re.IGNORECASE),
        re.compile(r"\b(?:stasis|offline|sleep|shutdown|dream|while.*(?:away|gone|down))\b", re.IGNORECASE),
        re.compile(r"\b(?:tell me about yourself|who are you|what are you|describe yourself)\b", re.IGNORECASE),
    ]

    @staticmethod
    def _is_introspective_query(text: str) -> bool:
        """AD-588: Detect introspective questions in captain/crew messages."""
        if not text:
            return False
        for pattern in CognitiveAgent._INTROSPECTIVE_PATTERNS:
            if pattern.search(text):
                return True
        return False

    def _build_crew_complement(self) -> str:
        """AD-513: Build compact crew complement for cognitive grounding.

        Prevents confabulation by anchoring agents to the actual crew roster.
        Injected into all prompt paths via _build_temporal_context().
        """
        rt = getattr(self, '_runtime', None)
        if not rt or not getattr(rt, 'ontology', None):
            return ""

        try:
            manifest = rt.ontology.get_crew_manifest(
                callsign_registry=getattr(rt, 'callsign_registry', None),
            )
        except Exception:
            return ""

        if not manifest:
            return ""

        self_atype = getattr(self, 'agent_type', '')
        dept_groups: dict[str, list[str]] = {}
        for entry in manifest:
            if entry["agent_type"] == self_atype:
                continue
            dept = (entry.get("department") or "bridge").capitalize()
            dept_groups.setdefault(dept, []).append(entry["callsign"])

        if not dept_groups:
            return ""

        lines = ["=== SHIP'S COMPLEMENT (these are the ONLY crew aboard) ==="]
        for dept_name in sorted(dept_groups):
            members = ", ".join(sorted(dept_groups[dept_name]))
            lines.append(f"  {dept_name}: {members}")
        lines.append(
            "Do NOT reference crew members who are not listed above. "
            "If you are uncertain whether someone is aboard, verify against this roster."
        )
        return "\n".join(lines)

    @staticmethod
    def _confabulation_guard(authority: str | None) -> str:
        """Return AD-592 confabulation guard instruction calibrated by source authority.

        Three tiers of guard strength:
        - AUTHORITATIVE: light touch — memories are high quality, still warn about numbers
        - SUPPLEMENTARY/None: standard guard — warn about numbers + orientation priority
        - PERIPHERAL: strong guard — warn about numbers + orientation priority + uncertainty
        """
        # Import here to avoid circular dependency at module level
        from probos.cognitive.source_governance import SourceAuthority

        base = (
            "IMPORTANT: Do NOT fabricate specific numbers, durations, measurements, or statistics "
            "from these fragments. If an exact value is not in your memories, say you do not have that data."
        )
        orientation_priority = (
            " When orientation or system data conflicts with your memories, "
            "orientation data is authoritative — cite it, do not estimate."
        )
        # BF-148: temporal preference for contradictory memories (AGM Belief Revision)
        temporal_preference = (
            " When memories contain conflicting values for the same measurement, "
            "prefer the most recent observation."
        )

        if authority == SourceAuthority.AUTHORITATIVE:
            # High-quality memories — still guard against number fabrication.
            # BF-159: Include temporal preference even for AUTHORITATIVE.
            # Temporal contradictions (same metric, different timestamps) are
            # valid regardless of anchor quality. AGM Belief Revision applies
            # universally — newer observations supersede older ones.
            return base + temporal_preference
        elif authority == SourceAuthority.PERIPHERAL:
            # Low-quality memories — full guard + uncertainty mandate
            return base + orientation_priority + temporal_preference + " State uncertainty explicitly."
        else:
            # SUPPLEMENTARY or no framing (fallback) — standard guard
            return base + orientation_priority + temporal_preference

    @staticmethod
    def _recall_confidence_note(band: str) -> str:
        """AD-981b: gap-regex-safe honest-absence cue for a weak/none own recall
        Feeling-of-Knowing band (the "Heidi" misinformation case). Returns "" for
        strong/empty bands so the prompt is byte-identical when there is nothing
        to add.

        Wording is checked against the decomposer ``is_capability_gap`` regex — it
        must NOT read as a capability gap (so it avoids "can't"/"cannot"/"unable
        to"/"lack*"/"don't have"/"no <X> capability|ability|support|way|mechanism|
        tool"/"not available|supported|possible"). "do not have" (with a space),
        "nothing recorded" and "no specific recollection" are safe.
        """
        if band == "weak":
            return (
                "RECALL CONFIDENCE: WEAK — the faint match above is below the "
                "confident-recall bar, so treat it as likely no specific "
                "recollection. If SHIP MEMORY does not contain the specifics "
                "asked about, say plainly that you have nothing recorded on "
                "that. Do not affirm a memory just because the question names "
                "it, and do not invent a time, place, or detail to fill the gap."
            )
        if band == "none":
            return (
                "RECALL CONFIDENCE: NONE — stored memory returned nothing "
                "matching this question. Report that you have nothing recorded "
                "on it. Do not affirm a memory just because the question names "
                "it, and do not invent a time, place, or detail."
            )
        return ""

    def _recall_confidence_segment(self, observation: dict) -> list[str] | None:
        """AD-981b: render-decision unit. Returns the honest-absence cue segment
        (``[note, ""]``) for the band stashed in ``observation["_recall_fok_band"]``
        by the flag-gated probe, or ``None`` when there is no band or the band
        carries no cue (strong/empty) — so an OFF run never emits anything.
        """
        _band = observation.get("_recall_fok_band")
        if not _band:
            return None
        _note = self._recall_confidence_note(_band)
        if not _note:
            return None
        return [_note, ""]

    @staticmethod
    def _remember_know_note(recall_type: str) -> str:
        """AD-1038: gap-regex-safe, instructions-first metacognitive cue for the
        AD-979f remember/know ``recall_type``. Returns "" for "none"/"" so the
        prompt is byte-identical when there is nothing to add. Wording is checked
        against the decomposer ``is_capability_gap`` regex — it must NOT read as a
        capability gap. Deliberately does NOT reuse ``remember_know_phrase`` (whose
        "know" text contains "can't" and would trip the regex).
        """
        if recall_type == "remember":
            return (
                "RECALL CONFIDENCE: REMEMBER — you have a specific, grounded "
                "recollection of this. Speak to the concrete details you actually "
                "recall (the exchange, who was involved, and when), and ground "
                "your answer in that specific memory."
            )
        if recall_type == "know":
            return (
                "RECALL CONFIDENCE: KNOW — this feels familiar, but the specifics "
                "are hazy: a sense of recognition without a grounded, detailed "
                "memory. Speak to the familiarity honestly, and avoid inventing a "
                "concrete time, place, or quote to fill in what stays hazy."
            )
        return ""

    def _remember_know_segment(self, observation: dict) -> list[str] | None:
        """AD-1038: render-decision unit. Returns the remember/know cue segment
        (``[note, ""]``) for ``observation["_recall_recall_type"]`` stashed by the
        flag-gated probe, or ``None`` when there is no type, the type carries no
        cue ("none"/""), or (DD-4) a weak/none FoK band is present (AD-981b's
        honest-absence cue takes precedence). OFF ⇒ no key ⇒ None.
        """
        _rt = observation.get("_recall_recall_type")
        if not _rt or _rt == "none":
            return None
        if observation.get("_recall_fok_band") in ("weak", "none"):
            return None
        _note = self._remember_know_note(_rt)
        if not _note:
            return None
        return [_note, ""]

    def _format_memory_section(self, memories: list[dict], source_framing: Any = None) -> list[str]:
        """Format recalled episodes with anchor context headers (AD-567b/568c)."""
        # AD-568c: Use source-authority-calibrated framing if available
        if source_framing:
            lines = [
                source_framing.header,
                source_framing.instruction,
            ]
            # AD-592: Authority-calibrated confabulation guard
            lines.append(self._confabulation_guard(source_framing.authority))
            lines.extend([
                "Markers: [direct] = you experienced it, [secondhand] = you heard about it.",
                "[verified] = corroborated by ship's log, [unverified] = not yet corroborated.",
                "",
            ])
        else:
            lines = [
                "=== SHIP MEMORY (your experiences aboard this vessel) ===",
                "These are YOUR experiences. Do NOT confuse with training knowledge.",
                self._confabulation_guard(None),
                "Markers: [direct] = you experienced it, [secondhand] = you heard about it.",
                "[verified] = corroborated by ship's log, [unverified] = not yet corroborated.",
                "",
            ]
        for mem in memories:
            # Anchor header line (AD-567b)
            anchor_parts = []
            if mem.get("age"):
                anchor_parts.append(f"{mem['age']} ago")
            if mem.get("anchor_channel"):
                anchor_parts.append(mem["anchor_channel"])
            if mem.get("anchor_department"):
                anchor_parts.append(f"{mem['anchor_department']} dept")
            if mem.get("anchor_participants"):
                anchor_parts.append(f"with {mem['anchor_participants']}")
            if mem.get("anchor_trigger"):
                anchor_parts.append(f"re: {mem['anchor_trigger']}")

            source = mem.get("source", "direct")
            verified = "verified" if mem.get("verified") else "unverified"
            header = f"  [{source} | {verified}]"
            if anchor_parts:
                header += f" [{' | '.join(anchor_parts)}]"

            lines.append(header)
            lines.append(f"    {mem.get('input', '') or mem.get('reflection', '')}")
        lines.append("")
        lines.append("=== END SHIP MEMORY ===")
        return lines

    def _resolve_attention_budget(self) -> int:
        """AD-1028: resolve the ContextAssembler global token budget.

        Default-OFF (``MemoryConfig.attention.enabled`` False, or no runtime/
        config wired) returns an effectively-unbounded budget so the bid
        assembler drops nothing and the assembled prompt is byte-identical to
        the prior push-style prepend chain. When enabled, returns the configured
        ``token_budget`` — the first global guard against context-window
        overflow.
        """
        _rt = getattr(self, "_runtime", None)
        _mem_cfg = getattr(getattr(_rt, "config", None), "memory", None) if _rt else None
        _att_cfg = getattr(_mem_cfg, "attention", None)
        if _att_cfg is not None and getattr(_att_cfg, "enabled", False):
            return int(getattr(_att_cfg, "token_budget", _DEFAULT_ATTENTION_TOKEN_BUDGET))
        return _UNBOUNDED_ATTENTION_TOKEN_BUDGET

    # ---- AD-1030: adaptive salience scoring (default-OFF) -------------------

    def _attention_config(self) -> Any | None:
        """AD-1030: the live ``AttentionConfig`` (or ``None`` when unwired)."""
        _rt = getattr(self, "_runtime", None)
        _mem_cfg = getattr(getattr(_rt, "config", None), "memory", None) if _rt else None
        return getattr(_mem_cfg, "attention", None)

    def _salience_scoring_enabled(self) -> bool:
        """AD-1030: True only when adaptive salience scoring is configured ON.

        Default-OFF: a missing runtime/config or an unset flag returns False ⇒
        the AD-1029/AD-1028 fixed insertion-priority bid path runs unchanged
        (byte-identical). This is the single gate every salience-scoring code
        path below is guarded behind.
        """
        _att = self._attention_config()
        return bool(_att is not None and getattr(_att, "salience_scoring", False))

    def _salience_weights(self) -> "SalienceWeights":
        """AD-1030: build the linear salience weights from config (defaults if absent)."""
        from probos.cognitive.salience import SalienceWeights
        _att = self._attention_config()
        if _att is None:
            return SalienceWeights()
        return SalienceWeights(
            w_rel=float(getattr(_att, "w_rel", 1.0)),
            w_rec=float(getattr(_att, "w_rec", 0.5)),
            w_imp=float(getattr(_att, "w_imp", 0.5)),
        )

    def _salience_half_life(self) -> float:
        """AD-1030: recency decay time-constant (seconds) from config (default 1 day)."""
        _att = self._attention_config()
        return float(getattr(_att, "recency_half_life_seconds", 86400.0)) if _att else 86400.0

    def _salience_rank_memories(
        self, memories: list[dict], goal_vec: list[float]
    ) -> tuple[list[dict], float]:
        """AD-1030: order recalled memories by transparent linear salience (DESC).

        Returns ``(ordered_memories, max_salience)``. Each memory's salience is
        ``compute_salience`` over cosine relevance to the goal (the internal
        ``_embedding`` key added at the gated recall site), exponential recency
        (``_timestamp``), and AD-598 importance (``_importance``). A memory
        missing those internal keys scores relevance/recency 0 (safe degrade)
        and falls to the tail. Stable: salience ties keep the original recall
        order. Does NOT mutate the input list. ``goal_vec`` is the only
        non-pure input (the caller's one ``embed_text(goal)`` result).
        """
        from probos.cognitive.salience import (
            compute_salience,
            cosine_similarity,
            recency_decay,
        )
        _weights = self._salience_weights()
        _half_life = self._salience_half_life()
        _now = time.time()
        scored: list[tuple[float, int, dict]] = []
        for _i, _mem in enumerate(memories):
            _emb = _mem.get("_embedding") or []
            _ts = float(_mem.get("_timestamp", 0.0) or 0.0)
            _imp = float(_mem.get("_importance", 5) or 5)
            _rel = cosine_similarity(goal_vec, _emb) if (goal_vec and _emb) else 0.0
            _rec = recency_decay(_now - _ts, _half_life) if _ts > 0.0 else 0.0
            _sal = compute_salience(
                relevance=_rel, recency=_rec, importance=_imp, weights=_weights
            )
            scored.append((_sal, _i, _mem))
        # Highest salience first; ties keep original recall order (stable).
        scored.sort(key=lambda t: (-t[0], t[1]))
        _ordered = [t[2] for t in scored]
        _max = scored[0][0] if scored else 0.0
        return _ordered, _max

    @staticmethod
    def _format_direct_message_trigger(params: dict[str, Any]) -> str:
        text = str(params.get("text", ""))
        if not params.get("is_group_chat"):
            return f"Captain says: {text}"
        trigger_speaker = params.get("trigger_speaker")
        if isinstance(trigger_speaker, str):
            speaker = trigger_speaker.strip()
            if speaker:
                return f"{speaker} says: {text}"
        return f"Room conversation:\n{text}"

    def _salience_score_wm_bid(self, goal_vec: list[float]) -> float | None:
        """AD-1030: max linear salience over working-memory entries (relevance +
        recency, NO importance — WM entries carry no importance signal).

        Returns the max salience, or ``None`` when there is no working memory or
        no scorable entry. The WM block is NOT re-ordered internally:
        ``AgentWorkingMemory.render_context`` is a category-grouped,
        priority-sorted, budget-evicted render with no flat per-entry ordered
        path, so WM ships bid-salience-only (AD-1030 HARD-STOP guard c) — this
        only adjusts the WM bid's competition weight, never its content.
        """
        from probos.cognitive.salience import (
            SalienceWeights,
            compute_salience,
            cosine_similarity,
            recency_decay,
        )
        from probos.knowledge.embeddings import embed_text
        _wm = getattr(self, "_working_memory", None)
        if _wm is None or not hasattr(_wm, "iter_salience_entries"):
            return None
        _entries = _wm.iter_salience_entries()
        if not _entries:
            return None
        _w = self._salience_weights()
        _wm_weights = SalienceWeights(w_rel=_w.w_rel, w_rec=_w.w_rec, w_imp=0.0)
        _half_life = self._salience_half_life()
        _max = 0.0
        for _e in _entries:
            _content = getattr(_e, "content", "") or ""
            if not _content:
                continue
            _rel = cosine_similarity(goal_vec, embed_text(_content)) if goal_vec else 0.0
            _rec = recency_decay(_e.age_seconds(), _half_life)
            _sal = compute_salience(
                relevance=_rel, recency=_rec, importance=5.0, weights=_wm_weights
            )
            if _sal > _max:
                _max = _sal
        return _max

    async def _build_user_message(self, observation: dict) -> str:
        """Build the user message from the observation dict.
        Override in subclasses for custom formatting.

        AD-666 Injection Ordering Audit:
        Chain path: cognitive state, situation awareness, sensorium budget tracking,
        then chain ANALYZE prompt rendering. DM path: temporal awareness, cognitive
        zone, telemetry, working memory, episodic memories, Oracle context, source
        attribution, session history, active game context, then Captain message.
        WR path: channel/thread header, temporal awareness, cognitive zone, DM
        self-monitoring, telemetry, working memory, episodic memories,
        self-recognition, thread context, then author message.
        """
        intent_name = observation.get("intent", "unknown")
        params = observation.get("params", {})

        # AD-397: direct_message — conversational context for 1:1 sessions
        if intent_name == "direct_message":
            # AD-1028: each block below becomes an AttentionBid with a LAZY
            # renderer returning EXACTLY the segment(s) it previously appended
            # to ``parts`` (including its trailing "" separator). The
            # ContextAssembler joins survivors with "\n" — byte-identical to the
            # prior ``"\n".join(parts)`` when nothing drops (default-OFF budget).
            _bids: list[AttentionBid] = []

            def _emit(
                source: str,
                segments: list[str],
                *,
                salience: float | None = None,
                zone_floor: int | None = None,
            ) -> None:
                idx = len(_bids)
                text = "\n".join(segments)
                _bids.append(AttentionBid(
                    source=source,
                    render=(lambda _t=text: _t),
                    # AD-1030: an explicit salience (episodic/WM when scoring is
                    # ON) overrides the fixed insertion priority; default None ⇒
                    # float(idx) ⇒ byte-identical to the AD-1028/1029 path.
                    salience=float(idx) if salience is None else salience,
                    token_cost=estimate_tokens(text),
                    # AD-1031: an explicit zone_floor (the camera-scene bid)
                    # overrides the emission-order default; None ⇒ idx ⇒
                    # byte-identical to the AD-1028/1029/1030 path.
                    zone_floor=idx if zone_floor is None else zone_floor,
                ))

            # AD-683: Cold-start ship state snapshot (boot-camp DM path only).
            if observation.get("_boot_camp_active") and self._runtime is not None:
                _bc = getattr(self._runtime, "boot_camp", None)
                _snap = getattr(_bc, "ship_state_snapshot", None) if _bc else None
                if _snap is not None:
                    try:
                        _snapshot_text = _snap.render_text()
                    except Exception:
                        logger.debug(
                            "AD-683: ship_state_snapshot.render_text failed; "
                            "skipping injection",
                            exc_info=True,
                        )
                        _snapshot_text = ""
                    if _snapshot_text:
                        _emit("boot_snapshot", [
                            "--- Ship State Snapshot ---",
                            _snapshot_text,
                            "---",
                            "",
                        ])

            # AD-502: Temporal awareness header
            temporal_ctx = self._build_temporal_context()
            if temporal_ctx:
                _emit("temporal", [
                    "--- Temporal Awareness ---",
                    temporal_ctx,
                    "---",
                    "",
                ])

            # AD-588: Cognitive zone awareness in DM path
            _zone = None
            _wm_zone = getattr(self, '_working_memory', None)
            if _wm_zone and hasattr(_wm_zone, 'get_cognitive_zone'):
                _zone = _wm_zone.get_cognitive_zone()
            if _zone and _zone != "green":
                _emit("cognitive_zone", [
                    f"<cognitive_zone>{_zone.upper()}</cognitive_zone>",
                    "",
                ])

            # AD-588: Introspective telemetry for self-referential queries
            captain_text = params.get("text", "")
            # AD-1030: adaptive salience setup (default-OFF). Embed the goal (the
            # raw Captain message) ONCE; the episodic + working-memory bids below
            # score relevance against it. When scoring is OFF this is skipped ⇒
            # no embedding cost and the AD-1029 fixed-priority path is unchanged.
            _salience_on = self._salience_scoring_enabled()
            _goal_vec: list[float] = []
            if _salience_on and captain_text:
                from probos.knowledge.embeddings import embed_text
                _goal_vec = embed_text(captain_text)
            _telemetry_svc = getattr(self._runtime, '_introspective_telemetry', None) if self._runtime else None
            if _telemetry_svc and self._is_introspective_query(captain_text):
                try:
                    _agent_id = getattr(self, 'sovereign_id', None) or self.id
                    _snapshot = await _telemetry_svc.get_full_snapshot(_agent_id)
                    _telemetry_text = _telemetry_svc.render_telemetry_context(_snapshot)
                    if _telemetry_text:
                        _emit("telemetry", [_telemetry_text, ""])
                    # AD-589: Cache for post-decision faithfulness cross-check
                    _wm = getattr(self, '_working_memory', None)
                    if _wm and hasattr(_wm, 'set_telemetry_snapshot'):
                        _wm.set_telemetry_snapshot(_snapshot)
                except Exception:
                    logger.debug("AD-588: telemetry injection failed for DM", exc_info=True)

            # AD-573: Working memory — unified situational awareness
            _wm = getattr(self, '_working_memory', None)
            wm_context = _wm.render_context() if _wm else ""
            if wm_context:
                _wm_salience = (
                    self._salience_score_wm_bid(_goal_vec) if _salience_on else None
                )
                _emit("working_memory", [wm_context, ""], salience=_wm_salience)

            # AD-723a-1 (Wave 148): dispatch self-wrapped DM_ONESHOT sensorium
            # entries. Replaces the prior hand-rolled AD-722 + AD-722a manual
            # call site. v1 renders only keys in _DM_SELF_WRAPPED_KEYS at this
            # zone (post-working-memory, pre-episodic); other DM-tagged entries
            # stay inline pending AD-723a-3 (position + wrapper metadata).
            # The dispatcher iterates SENSORIUM_REGISTRY entries whose paths
            # include DM_ONESHOT, awaiting async-registered methods and
            # tolerating per-method failure (Tier-2 degrade inside the
            # dispatcher itself).
            try:
                _dm_sensorium = await self._dispatch_sensorium_async(
                    SensoriumPath.DM_ONESHOT, observation,
                )
                _dm_segs: list[str] = []
                for _key in self._DM_SELF_WRAPPED_KEYS:
                    _block = _dm_sensorium.get(_key)
                    if _block:
                        _dm_segs.append(_block)
                        _dm_segs.append("")
                if _dm_segs:
                    _emit("dm_sensorium", _dm_segs)
            except Exception:
                logger.debug(
                    "AD-723a-1: DM sensorium dispatch failed; "
                    "degrading (Tier-2: skipping injection zone).",
                    exc_info=True,
                )

            # AD-430c / AD-540: Episodic memory with provenance boundary
            memories = observation.get("recent_memories", [])
            if memories:
                _framing = observation.get("_source_framing")
                _epi_salience: float | None = None
                if _salience_on:
                    # AD-1030: order memories by salience DESC (relevance ×
                    # recency × importance) so a high-relevance low-recency
                    # memory can outrank a low-relevance recent one; weight the
                    # bid by its best member.
                    memories, _epi_salience = self._salience_rank_memories(
                        memories, _goal_vec
                    )
                _emit("episodic", [
                    *self._format_memory_section(memories, source_framing=_framing),
                    "",
                ], salience=_epi_salience)

            # AD-981b: own recall-confidence cue — rendered only when the gating
            # flag set a weak/none band on this observation; OFF => segment None
            # => no emit => byte-identical.
            _fok_seg = self._recall_confidence_segment(observation)
            if _fok_seg:
                _emit("recall_confidence", _fok_seg)

            # AD-1038: remember/know metacognitive cue — rendered only when typing
            # is on AND not deferring to a weak/none honest-absence cue (DD-4);
            # OFF => no _recall_recall_type key => segment None => no emit.
            _rk_seg = self._remember_know_segment(observation)
            if _rk_seg:
                _emit("remember_know", _rk_seg)

            # AD-986b: canonical transcript (the recording) — the verbatim record
            # of a room this agent took part in, rendered DISTINCT from the
            # subjective recalled memory above so the agent grounds its
            # recollection in what was actually said (and may quote it).
            _tg_excerpt = observation.get("_transcript_grounding")
            if _tg_excerpt:
                from probos.cognitive.transcript_grounding import (
                    render_transcript_grounding,
                )
                _emit("transcript_grounding", [
                    *render_transcript_grounding(_tg_excerpt),
                    "",
                ])

            # AD-986d: recording-purged indication. If the agent may hold a
            # subjective memory of a room whose canonical recording has been
            # purged under the retention policy, tell it honestly so it does not
            # present its lossy recollection as the complete, verifiable picture.
            _tg_purged = observation.get("_transcript_purged")
            if _tg_purged:
                from probos.cognitive.transcript_grounding import (
                    render_purge_indication,
                )
                _emit("transcript_purged", [
                    *render_purge_indication(_tg_purged),
                    "",
                ])

            # AD-568a: Oracle Service cross-tier context (ORACLE tier + DEEP strategy only)
            if observation.get("_oracle_context"):
                logger.debug(
                    "Rendering oracle_context in DM prompt for %s (%d chars)",
                    self.callsign or self.agent_type,
                    len(observation["_oracle_context"]),
                )
                _emit("oracle", [
                    "=== CROSS-TIER KNOWLEDGE (Ship's Records + Operational State) ===\n"
                    "These are NOT your personal experiences. They are from the ship's shared "
                    "knowledge stores. Treat as reference material, not memory.\n"
                    "IMPORTANT: When answering questions, prioritize information from this section "
                    "over your general training knowledge. Cite specific relationships shown here.",
                    observation["_oracle_context"],
                    "=== END CROSS-TIER KNOWLEDGE ===",
                    "",
                ])
            else:
                logger.debug(
                    "No oracle_context in DM observation for %s (keys: %s)",
                    self.callsign or self.agent_type,
                    [k for k in observation if k.startswith("_oracle")],
                )

            # AD-568d: Ambient source attribution tag (cognitive proprioception)
            _attr = observation.get("_source_attribution")
            if _attr:
                _sources_present = []
                if _attr.episodic_count > 0:
                    _sources_present.append(f"episodic memory ({_attr.episodic_count} episodes)")
                if _attr.procedural_count > 0:
                    _sources_present.append(f"learned procedures ({_attr.procedural_count})")
                if _attr.oracle_used:
                    _sources_present.append("ship's records")
                if not _sources_present:
                    _sources_present.append("training knowledge only")
                _emit("source_attribution", [
                    f"<source_awareness>Your response draws on: {', '.join(_sources_present)}. "
                    f"Primary basis: {_attr.primary_source.value}.</source_awareness>",
                    "",
                ])

            session_history = params.get("session_history", [])
            if session_history:
                _sh_segments = ["Previous conversation:"]
                for entry in session_history:
                    role = entry.get("role", "unknown")
                    text = entry.get("text", "")
                    _sh_segments.append(f"  {role}: {text}")
                _sh_segments.append("")
                _emit("session_history", _sh_segments)

            # AD-572: Active game state awareness in DM path
            active_game_ctx = self._build_active_game_context()
            if active_game_ctx:
                _emit("active_game", [active_game_ctx, ""])

            _emit("captain_message", [self._format_direct_message_trigger(params)])

            # AD-1031: camera/visual scene as a salience-gated bid. When the
            # camera-scene-bid is ON (default-OFF), the router did NOT prepend
            # the AD-733a scene onto ``text`` — it handed the rendered block via
            # ``params['_visual_scene']`` for the agent to bid here. The scene
            # wins PROMINENT prompt space (a leading zone_floor + high salience,
            # approximating the old prepend's primacy + always-present
            # guarantee) only when it is SALIENT: the Captain REFERENCED vision,
            # the frame MATERIALLY CHANGED (novelty ≥ camera_novelty_minimum),
            # or it's a VISUAL TASK (image attachment). Otherwise it stays
            # RECESSIVE — a one-line "live camera" summary at a trailing
            # zone_floor + low salience (present-but-quiet, first to drop under a
            # scarce budget) so agents stop over-narrating an unchanged scene
            # (#973 / BF-632 dominance). Default-OFF or a missing
            # ``_visual_scene`` ⇒ emits NOTHING ⇒ the router prepend ran as today
            # ⇒ byte-identical.
            _att_cfg = self._attention_config()
            _visual_scene = params.get("_visual_scene")
            if (
                _att_cfg is not None
                and getattr(_att_cfg, "camera_scene_bid_enabled", False)
                and _visual_scene
            ):
                from probos.cognitive.salience import visual_reference_score

                # BF-632: reference-detect off the RAW Captain message, NEVER the
                # merged ``text`` (which historically LED with the scene block).
                _referenced = visual_reference_score(
                    params.get("captain_message", "")
                ) > 0.0
                _novelty_min = float(
                    getattr(_att_cfg, "camera_novelty_minimum", 0.3) or 0.0
                )
                _changed = (
                    float(params.get("_visual_novelty", 0.0) or 0.0) >= _novelty_min
                )
                _visual_task = bool(params.get("has_image_attachment"))
                _prominent = _referenced or _changed or _visual_task
                _summary = params.get("_visual_summary") or ""
                if _prominent or not _summary:
                    # PROMINENT — or the empty-WM BF-294 sentinel (no
                    # ``_visual_summary``), which MUST always show so the agent
                    # never confabulates a scene. Full block LEADS the prompt.
                    _emit(
                        "camera_scene",
                        [str(_visual_scene), ""],
                        salience=_CAMERA_PROMINENT_SALIENCE,
                        zone_floor=_CAMERA_PROMINENT_ZONE_FLOOR,
                    )
                else:
                    # RECESSIVE — a short, clearly-framed "live camera" one-liner
                    # (provenance-distinct from memory) that TRAILS the
                    # substantive context and drops first under scarcity.
                    _one_line = " ".join(str(_summary).split())
                    _emit(
                        "camera_scene_ambient",
                        [f"[Live camera] {_one_line}", ""],
                        salience=_CAMERA_RECESSIVE_SALIENCE,
                        zone_floor=_CAMERA_RECESSIVE_ZONE_FLOOR,
                    )

            # AD-1029: when the deterministic AttentionFaculty is composed (attention
            # enabled), it DRIVES the assembler — merging any pending exogenous bids and
            # auditing the competition. Default-OFF the faculty is None and the exact
            # AD-1028 inline ContextAssembler path below runs unchanged (byte-identical).
            _faculty = self._active_attention_faculty()
            if _faculty is not None:
                return "\n".join(
                    _faculty.arbitrate(_bids, token_budget=self._resolve_attention_budget())
                )
            return "\n".join(
                ContextAssembler.assemble(_bids, token_budget=self._resolve_attention_budget())
            )

        # AD-407b: ward_room_notification — thread context for Ward Room
        if intent_name == "ward_room_notification":
            channel_name = params.get("channel_name", "")
            author_callsign = params.get("author_callsign", "unknown")
            title = params.get("title", "")
            context = observation.get("context", "")

            # AD-1028: WR blocks become AttentionBids with LAZY renderers that
            # return EXACTLY the segment(s) each block appended to ``wr_parts``
            # (the WR path's leading-"" separator convention is reproduced
            # inside each bid). The ContextAssembler joins survivors with "\n"
            # — byte-identical to the prior ``"\n".join(wr_parts)`` when nothing
            # drops (default-OFF budget).
            _bids: list[AttentionBid] = []

            def _emit(
                source: str, segments: list[str], *, salience: float | None = None
            ) -> None:
                idx = len(_bids)
                text = "\n".join(segments)
                _bids.append(AttentionBid(
                    source=source,
                    render=(lambda _t=text: _t),
                    # AD-1030: an explicit salience (episodic/WM when scoring is
                    # ON) overrides the fixed insertion priority; default None ⇒
                    # float(idx) ⇒ byte-identical to the AD-1028/1029 path.
                    salience=float(idx) if salience is None else salience,
                    token_cost=estimate_tokens(text),
                    zone_floor=idx,
                ))

            _emit("wr_header", [
                f"[Ward Room — #{channel_name}]",
                f"Thread: {title}",
            ])

            # AD-502: Temporal awareness header
            temporal_ctx = self._build_temporal_context()
            if temporal_ctx:
                _emit("temporal", [
                    "",
                    "--- Temporal Awareness ---",
                    temporal_ctx,
                    "---",
                ])

            # AD-588: Cognitive zone awareness in Ward Room path
            _zone = None
            _wm_zone = getattr(self, '_working_memory', None)
            if _wm_zone and hasattr(_wm_zone, 'get_cognitive_zone'):
                _zone = _wm_zone.get_cognitive_zone()
            if _zone and _zone != "green":
                _emit("cognitive_zone", [
                    "",
                    f"<cognitive_zone>{_zone.upper()}</cognitive_zone>",
                ])

            # AD-623: DM self-monitoring — agents responding to DM threads
            # see their own repetition in real time
            if channel_name.startswith("dm-"):
                _dm_self_mon = await self._build_dm_self_monitoring(
                    params.get("thread_id", ""),
                )
                if _dm_self_mon:
                    _emit("dm_self_monitoring", ["", _dm_self_mon])

            # AD-588: Introspective telemetry for self-referential ward room posts
            _wr_text = f"{params.get('title', '')} {params.get('text', '')}".strip()
            # AD-1030: adaptive salience setup (default-OFF). Embed the goal (the
            # author's post) ONCE; the episodic + working-memory bids below score
            # relevance against it. Skipped when scoring is OFF (no embed cost).
            _salience_on = self._salience_scoring_enabled()
            _goal_vec: list[float] = []
            _wr_goal = params.get("text", "")
            if _salience_on and _wr_goal:
                from probos.knowledge.embeddings import embed_text
                _goal_vec = embed_text(_wr_goal)
            _telemetry_svc = getattr(self._runtime, '_introspective_telemetry', None) if self._runtime else None
            if _telemetry_svc and self._is_introspective_query(_wr_text):
                try:
                    _agent_id = getattr(self, 'sovereign_id', None) or self.id
                    _snapshot = await _telemetry_svc.get_full_snapshot(_agent_id)
                    _telemetry_text = _telemetry_svc.render_telemetry_context(_snapshot)
                    if _telemetry_text:
                        _emit("telemetry", ["", _telemetry_text])
                    # AD-589: Cache for post-decision faithfulness cross-check
                    _wm = getattr(self, '_working_memory', None)
                    if _wm and hasattr(_wm, 'set_telemetry_snapshot'):
                        _wm.set_telemetry_snapshot(_snapshot)
                except Exception:
                    logger.debug("AD-588: telemetry injection failed for WR", exc_info=True)

            # AD-573: Working memory — unified situational awareness
            _wm = getattr(self, '_working_memory', None)
            wm_context = _wm.render_context() if _wm else ""
            if wm_context:
                _wm_salience = (
                    self._salience_score_wm_bid(_goal_vec) if _salience_on else None
                )
                _emit("working_memory", ["", wm_context], salience=_wm_salience)

            # AD-723a-2 (Wave 161): WR sibling of the AD-723a-1 DM
            # dispatcher path. Selector ``_WR_SELF_WRAPPED_KEYS`` is
            # currently empty — the iteration below is a no-op until a
            # future AD adds WR-only self-wrapped entries. Keeping the
            # call site present means new entries cost zero diff.
            try:
                _wr_sensorium = await self._dispatch_sensorium_async(
                    SensoriumPath.WR_ONESHOT, observation,
                )
                _wr_segs: list[str] = []
                for _key in self._WR_SELF_WRAPPED_KEYS:
                    _block = _wr_sensorium.get(_key)
                    if _block:
                        _wr_segs.append("")
                        _wr_segs.append(_block)
                if _wr_segs:
                    _emit("wr_sensorium", _wr_segs)
            except Exception:
                logger.warning(
                    "AD-723a-2: WR sensorium dispatch raised for agent=%s; "
                    "falling through to hand-rolled WR fragments",
                    self.id, exc_info=True,
                )

            # BF-102: Cold-start system note in ward room context
            rt = getattr(self, '_runtime', None)
            if rt and getattr(rt, 'is_cold_start', False):
                _emit("cold_start_note", [
                    "",
                    "SYSTEM NOTE: This is a fresh start. You have no prior "
                    "episodic memories. Do not reference or invent past experiences.",
                ])

            # AD-430c / AD-540: Episodic memory with provenance boundary
            memories = observation.get("recent_memories", [])
            if memories:
                _framing = observation.get("_source_framing")
                _epi_salience: float | None = None
                if _salience_on:
                    # AD-1030: order memories by salience DESC; weight the bid by
                    # its best member.
                    memories, _epi_salience = self._salience_rank_memories(
                        memories, _goal_vec
                    )
                _emit("episodic", [
                    "",
                    *self._format_memory_section(memories, source_framing=_framing),
                ], salience=_epi_salience)

            # AD-981b: own recall-confidence cue — rendered only when the gating
            # flag set a weak/none band on this observation; OFF => segment None
            # => no emit => byte-identical.
            _fok_seg = self._recall_confidence_segment(observation)
            if _fok_seg:
                _emit("recall_confidence", _fok_seg)

            # AD-1038: remember/know metacognitive cue — rendered only when typing
            # is on AND not deferring to a weak/none honest-absence cue (DD-4);
            # OFF => no _recall_recall_type key => segment None => no emit.
            _rk_seg = self._remember_know_segment(observation)
            if _rk_seg:
                _emit("remember_know", _rk_seg)

            # AD-568a: Oracle Service cross-tier context
            if observation.get("_oracle_context"):
                logger.debug(
                    "Rendering oracle_context in WR prompt for %s (%d chars)",
                    getattr(self, 'agent_type', '?'), len(observation["_oracle_context"]),
                )
                _emit("oracle", [
                    "",
                    "=== CROSS-TIER KNOWLEDGE (Ship's Records + Operational State) ===\n"
                    "These are NOT your personal experiences. They are from the ship's shared "
                    "knowledge stores. Treat as reference material, not memory.",
                    observation["_oracle_context"],
                    "=== END CROSS-TIER KNOWLEDGE ===",
                ])

            # AD-568d: Ambient source attribution tag (cognitive proprioception)
            _attr = observation.get("_source_attribution")
            if _attr:
                _sources_present = []
                if _attr.episodic_count > 0:
                    _sources_present.append(f"episodic memory ({_attr.episodic_count} episodes)")
                if _attr.procedural_count > 0:
                    _sources_present.append(f"learned procedures ({_attr.procedural_count})")
                if _attr.oracle_used:
                    _sources_present.append("ship's records")
                if not _sources_present:
                    _sources_present.append("training knowledge only")
                _emit("source_attribution", [
                    "",
                    f"<source_awareness>Your response draws on: {', '.join(_sources_present)}. "
                    f"Primary basis: {_attr.primary_source.value}.</source_awareness>",
                ])

            # AD-626/AD-631: Generic task-framed skill injection (with proficiency context)
            _aug_skill = observation.get("_augmentation_skill_instructions")
            if _aug_skill and context:
                _meta = self._extract_thread_metadata(context)
                _prof_ctx = self._get_comm_proficiency_guidance() or ""
                _skill_segments = self._frame_task_with_skill(
                    _aug_skill, "Process Ward Room Thread", _meta,
                    proficiency_context=_prof_ctx,
                )
                if _skill_segments:
                    _emit("skill_injection", list(_skill_segments))

            if context:
                _emit("thread_context", [f"\nConversation so far:\n{context}"])

            # AD-575: Self-recognition in Ward Room threads
            self_cue = self._detect_self_in_content(context)
            if self_cue:
                _emit("self_recognition", [self_cue])

            # AD-407d: Distinguish Captain vs crew member posts
            author_id = params.get("author_id", "")
            was_mentioned = params.get("was_mentioned", False)

            if author_id == "captain":
                _emit("author_attribution", [f"\nThe Captain posted the above."])
            else:
                _emit("author_attribution", [f"\n{author_callsign} posted the above."])

            # BF-157: @mentioned agents must respond — they were directly addressed.
            if was_mentioned:
                _emit("response_guidance", [
                    "You were directly @mentioned in this post. A response is expected. "
                    "Address the question or request from your area of expertise. "
                    "Be concise and helpful.",
                ])
            else:
                _emit("response_guidance", [
                    "Respond naturally as yourself. Share your perspective if you have something meaningful to contribute.",
                    "If this topic is outside your expertise or you have nothing to add, respond with exactly: [NO_RESPONSE]",
                ])
            # AD-1029: when the deterministic AttentionFaculty is composed (attention
            # enabled), it DRIVES the assembler — merging any pending exogenous bids and
            # auditing the competition. Default-OFF the faculty is None and the exact
            # AD-1028 inline ContextAssembler path below runs unchanged (byte-identical).
            _faculty = self._active_attention_faculty()
            if _faculty is not None:
                return "\n".join(
                    _faculty.arbitrate(_bids, token_budget=self._resolve_attention_budget())
                )
            return "\n".join(
                ContextAssembler.assemble(_bids, token_budget=self._resolve_attention_budget())
            )

        # Phase 28b: proactive_think — idle review cycle
        if intent_name == "proactive_think":
            context_parts = params.get("context_parts", {})
            trust_score = params.get("trust_score", 0.5)
            agency_level = params.get("agency_level", "suggestive")
            duty = params.get("duty")  # AD-419: may be None

            pt_parts: list[str] = []

            if duty:
                # AD-419: Duty cycle — agent has a scheduled task
                pt_parts.append(f"[Duty Cycle: {duty.get('description', duty.get('duty_id', 'unknown'))}]")
                pt_parts.append(f"Your trust: {trust_score} | Agency: {agency_level} | Rank: {params.get('rank', 'unknown')}")
                pt_parts.append("")
                pt_parts.append("This is a scheduled duty. Perform your assigned task and report your findings.")
                pt_parts.append("")
            else:
                # Free-form think — no duty due, requires justification
                pt_parts.append("[Proactive Review — No Scheduled Duty]")
                pt_parts.append(f"Your trust: {trust_score} | Agency: {agency_level} | Rank: {params.get('rank', 'unknown')}")
                pt_parts.append("")
                pt_parts.append("You have no scheduled duty at this time. You may share an observation")
                pt_parts.append("ONLY if you notice something genuinely noteworthy or actionable.")
                pt_parts.append("If you do post, include a brief justification for why it matters now.")
                pt_parts.append("Silence is professionalism — [NO_RESPONSE] is the expected default.")
                pt_parts.append("Do not comment on your own posting patterns or observation frequency.")
                pt_parts.append("")

            # AD-502: Temporal awareness header
            temporal_ctx = self._build_temporal_context()
            if temporal_ctx:
                pt_parts.append("--- Temporal Awareness ---")
                pt_parts.append(temporal_ctx)
                pt_parts.append("---")
                pt_parts.append("")

            # AD-573: Working memory — supplements proactive context
            _wm = getattr(self, '_working_memory', None)
            wm_context = _wm.render_context(budget=1500) if _wm else ""
            if wm_context:
                pt_parts.append(wm_context)
                pt_parts.append("")

            # BF-034: Cold-start system note
            system_note = context_parts.get("system_note")
            if system_note:
                pt_parts.append(system_note)
                pt_parts.append("")

            # AD-576: Infrastructure awareness
            infra_status = context_parts.get("infrastructure_status")
            if infra_status:
                llm_status = infra_status.get("llm_status", "unknown")
                pt_parts.append(f"[INFRASTRUCTURE NOTE: Communications array {llm_status}]")
                pt_parts.append(infra_status.get("message", ""))
                pt_parts.append("")

            # AD-429: Ontology identity grounding
            ontology = context_parts.get("ontology")
            if ontology:
                identity = ontology.get("identity", {})
                dept = ontology.get("department", {})
                vessel = ontology.get("vessel", {})
                pt_parts.append(f"You are {identity.get('callsign', '?')}, {identity.get('post', '?')} in {dept.get('name', '?')} department.")
                if ontology.get("reports_to"):
                    pt_parts.append(f"You report to {ontology['reports_to']}.")
                if ontology.get("direct_reports"):
                    pt_parts.append(f"Your direct reports: {', '.join(ontology['direct_reports'])}.")
                if ontology.get("peers"):
                    pt_parts.append(f"Department peers: {', '.join(ontology['peers'])}.")
                if vessel:
                    alert = vessel.get("alert_condition", "GREEN")
                    pt_parts.append(f"Ship status: {vessel.get('name', 'ProbOS')} v{vessel.get('version', '?')} — Alert Condition {alert}.")
                pt_parts.append("")

            # AD-630: Subordinate communication stats for Chiefs
            sub_stats = context_parts.get("subordinate_stats")
            if sub_stats:
                pt_parts.append("<subordinate_activity>")
                for callsign, stats in sub_stats.items():
                    pt_parts.append(
                        f"  {callsign}: {stats['posts_total']} posts, "
                        f"{stats['endorsements_given']} endorsements given, "
                        f"{stats['endorsements_received']} endorsements received, "
                        f"credibility {stats['credibility_score']:.2f}"
                    )
                pt_parts.append("</subordinate_activity>")
                pt_parts.append("")

            # AD-567g: Diminishing orientation supplement for young agents
            orientation_supp = context_parts.get("orientation_supplement")
            if orientation_supp:
                pt_parts.append(orientation_supp)
                pt_parts.append("")

            # AD-429b: Skill profile
            skill_profile = context_parts.get("skill_profile")
            if skill_profile:
                pt_parts.append(f"Your skills: {', '.join(skill_profile)}.")
                pt_parts.append("")

            # AD-540: Episodic memory with provenance boundary
            memories = context_parts.get("recent_memories", [])
            if memories:
                _framing = context_parts.get("_source_framing")
                pt_parts.extend(self._format_memory_section(memories, source_framing=_framing))
                pt_parts.append("")
            else:
                pt_parts.append("You have no stored episodic memories yet. Do not reference or invent past experiences you do not have.")
                pt_parts.append("")

            # AD-568d: Ambient source attribution tag (cognitive proprioception)
            _attr = observation.get("_source_attribution")
            if _attr:
                _sources_present = []
                if _attr.episodic_count > 0:
                    _sources_present.append(f"episodic memory ({_attr.episodic_count} episodes)")
                if _attr.procedural_count > 0:
                    _sources_present.append(f"learned procedures ({_attr.procedural_count})")
                if _attr.oracle_used:
                    _sources_present.append("ship's records")
                if not _sources_present:
                    _sources_present.append("training knowledge only")
                pt_parts.append(
                    f"[Source awareness: Your response draws on: {', '.join(_sources_present)}. "
                    f"Primary basis: {_attr.primary_source.value}.]"
                )
                pt_parts.append("")

            # Recent alerts
            alerts = context_parts.get("recent_alerts", [])
            if alerts:
                pt_parts.append("Recent bridge alerts:")
                for a in alerts:
                    pt_parts.append(f"  - [{a.get('severity', '?')}] {a.get('title', '?')} (from {a.get('source', '?')})")
                pt_parts.append("")

            # Recent events
            events = context_parts.get("recent_events", [])
            if events:
                pt_parts.append("Recent system events:")
                for e in events:
                    pt_parts.append(f"  - [{e.get('category', '?')}] {e.get('event', '?')}")
                pt_parts.append("")

            # Recent Ward Room activity (AD-413)
            wr_activity = context_parts.get("ward_room_activity", [])

            # AD-626/AD-631: Generic task-framed skill injection for proactive think
            _aug_skill = observation.get("_augmentation_skill_instructions")
            if _aug_skill and wr_activity:
                _prof_ctx = self._get_comm_proficiency_guidance() or ""
                pt_parts.extend(self._frame_task_with_skill(
                    _aug_skill, "Review Ward Room Activity",
                    proficiency_context=_prof_ctx,
                ))

            if wr_activity:
                pt_parts.append("Recent Ward Room discussion in your department:")
                for a in wr_activity:
                    prefix = "[thread]" if a.get("type") == "thread" else "[reply]"
                    ids = ""
                    if a.get("thread_id"):
                        ids += f" thread:{a['thread_id'][:8]}"
                    if a.get("post_id"):
                        ids += f" post:{a['post_id'][:8]}"
                    score = a.get("net_score", 0)
                    score_str = f" [+{score}]" if score > 0 else f" [{score}]" if score < 0 else ""
                    pt_parts.append(f"  - {prefix}{ids}{score_str} {a.get('author', '?')}: {a.get('body', '?')}")
                pt_parts.append("")

            # BF-110: Active game state — show board so agent knows it's their turn
            active_game = context_parts.get("active_game")
            if active_game:
                pt_parts.append("--- Active Game ---")
                pt_parts.append(
                    f"You are playing {active_game['game_type']} against {active_game['opponent']}. "
                    f"Moves so far: {active_game['moves_count']}."
                )
                pt_parts.append(f"\nCurrent board:\n```\n{active_game['board']}\n```")
                if active_game["is_my_turn"]:
                    pt_parts.append(
                        f"**It is YOUR turn.** Valid moves: {', '.join(str(m) for m in active_game['valid_moves'])}. "
                        f"Reply with [MOVE position] to play."
                    )
                else:
                    pt_parts.append("Waiting for your opponent to move.")
                pt_parts.append("")

            # AD-504: Self-monitoring context
            self_mon = context_parts.get("self_monitoring")
            if self_mon:
                pt_parts.append("")

                # AD-506a: Cognitive zone (before self-monitoring details)
                zone = self_mon.get("cognitive_zone")
                zone_note = self_mon.get("zone_note")
                if zone:
                    pt_parts.append(f"<cognitive_zone>{zone.upper()}</cognitive_zone>")
                    if zone_note:
                        pt_parts.append(zone_note)
                    pt_parts.append("")

                pt_parts.append("<recent_activity>")

                # Recent posts
                recent_posts = self_mon.get("recent_posts")
                if recent_posts:
                    pt_parts.append("Your recent posts (review before adding to the discussion):")
                    for p in recent_posts:
                        age_str = f"[{p['age']} ago]" if p.get("age") else ""
                        pt_parts.append(f"  - {age_str} {p['body']}")

                # Self-similarity
                sim = self_mon.get("self_similarity")
                if sim is not None:
                    pt_parts.append(f"Self-similarity across recent posts: {sim:.2f}")
                    if sim >= 0.5:
                        pt_parts.append(
                            "WARNING: Your recent posts show high similarity. "
                            "Before posting, ensure you have GENUINELY NEW information. "
                            "If not, respond with [NO_RESPONSE]."
                        )
                    elif sim >= 0.3:
                        pt_parts.append(
                            "Note: Some similarity in your recent posts. "
                            "Consider whether you are adding new insight or restating."
                        )

                # Cooldown increased
                if self_mon.get("cooldown_increased"):
                    pt_parts.append(
                        "Your proactive cooldown has been increased due to rising similarity. "
                        "This is pacing, not punishment — take time to find fresh perspectives."
                    )

                # AD-505: Counselor cooldown reason
                if self_mon.get("cooldown_reason"):
                    pt_parts.append(f"  Counselor note: {self_mon['cooldown_reason']}")

                # Memory state awareness
                mem_state = self_mon.get("memory_state")
                if mem_state:
                    count = mem_state.get("episode_count", 0)
                    lifecycle = mem_state.get("lifecycle", "")
                    uptime_hrs = mem_state.get("uptime_hours", 0)
                    if count < 5 and lifecycle != "reset" and uptime_hrs > 1:
                        pt_parts.append(
                            f"Note: You have {count} episodic memories, but the system has been "
                            f"running for {uptime_hrs:.1f}h. Other crew may have richer histories. "
                            "Do not generalize from your own sparse memory to the crew's state."
                        )

                # Notebook index
                nb_index = self_mon.get("notebook_index")
                if nb_index:
                    topics = ", ".join(
                        f"{e['topic']} (updated {e['updated']})" if e.get("updated") else e["topic"]
                        for e in nb_index
                    )
                    pt_parts.append(f"Your notebooks: [{topics}]")
                    pt_parts.append(
                        "Use [NOTEBOOK topic-slug] to update. "
                        "Use [READ_NOTEBOOK topic-slug] to review a notebook next cycle."
                    )

                # Notebook content (from semantic pull or explicit read)
                nb_content = self_mon.get("notebook_content")
                if nb_content:
                    pt_parts.append(f'<notebook topic="{nb_content["topic"]}">')
                    pt_parts.append(nb_content["snippet"])
                    pt_parts.append("</notebook>")

                pt_parts.append("</recent_activity>")
                pt_parts.append("")

            # AD-588: Introspective telemetry snapshot (always available in proactive path)
            introspective_telemetry = context_parts.get("introspective_telemetry")
            if introspective_telemetry:
                pt_parts.append("")
                pt_parts.append(introspective_telemetry)

            if duty:
                pt_parts.append("Compose a Ward Room post with your findings (2-4 sentences).")
                pt_parts.append("If nothing noteworthy to report, respond with exactly: [NO_RESPONSE]")
            else:
                pt_parts.append("If something genuinely warrants attention, compose a brief observation (2-4 sentences).")
                pt_parts.append("Include your justification. Otherwise respond with exactly: [NO_RESPONSE]")
            return "\n".join(pt_parts)

        parts = [f"Intent: {intent_name}"]
        if params:
            parts.append(f"Parameters: {params}")
        if observation.get("context"):
            parts.append(f"Context: {observation['context']}")
        if observation.get("fetched_content"):
            parts.append(f"Fetched content:\n{observation['fetched_content']}")
        # AD-535: Include procedure guidance hints for Level 2 (Guided) replay
        if observation.get("procedure_guidance"):
            parts.append(f"\n--- Suggested approach ---\n{observation['procedure_guidance']}")
        return "\n".join(parts)

    async def _recall_relevant_memories(self, intent: IntentMessage, observation: dict) -> dict:
        """AD-430c: Inject relevant episodic memories into observation for decide().

        Only fires for crew agents on conversational intents. Proactive think
        already gets memory context via _gather_context() — skip to avoid duplication.
        """
        # Skip proactive_think — already has memory context from proactive loop
        if intent.intent == "proactive_think":
            return observation

        # Guard: need runtime + episodic memory + crew check
        if not self._runtime:
            return observation
        if not hasattr(self._runtime, 'episodic_memory') or not self._runtime.episodic_memory:
            return observation
        if not hasattr(self._runtime, 'ontology'):
            return observation
        from probos.crew_utils import is_crew_agent as _is_crew
        if not _is_crew(self, getattr(self._runtime, 'ontology', None)):
            return observation

        # AD-602: Lazy-init question classifier
        if self._question_classifier is None:
            try:
                from probos.cognitive.question_classifier import (
                    QuestionClassifier,
                    RetrievalStrategySelector,
                )

                _qa_config = self._runtime.config.question_adaptive
                if not _qa_config.enabled:
                    self._question_classifier = QuestionClassifier()
                    self._retrieval_strategy_selector = None
                else:
                    self._question_classifier = QuestionClassifier()
                    self._retrieval_strategy_selector = RetrievalStrategySelector(config=_qa_config)
            except Exception:
                logger.debug("AD-602: Question classifier unavailable", exc_info=True)

        # AD-604: Lazy-init spreading activation engine
        if getattr(self, "_spreading_activation", None) is None:
            try:
                _sa_config = self._runtime.config.spreading_activation
                if _sa_config.enabled:
                    from probos.cognitive.spreading_activation import SpreadingActivationEngine

                    self._spreading_activation = SpreadingActivationEngine(
                        config=_sa_config,
                        episodic_memory=self._runtime.episodic_memory,
                    )
            except Exception:
                logger.debug("AD-604: Spreading activation unavailable", exc_info=True)

        try:
            # Build a semantic query from the intent content
            params = observation.get("params", {})
            if intent.intent == "direct_message":
                # AD-584b: Removed BF-029 "Ward Room {callsign}" query prefix.
                # With multi-qa-MiniLM-L6-cos-v1, the QA-trained model bridges
                # question->answer gaps without prefix workarounds.
                # BF-632: drive recall off the RAW Captain message, not the
                # router-assembled params["text"] (which now leads with the
                # prepended visual-context block — see _dm_recall_query).
                query = _dm_recall_query(params)
            elif intent.intent == "ward_room_notification":
                query = f"{params.get('title', '')} {params.get('text', '')}".strip()[:200]
            else:
                query = intent.context[:200] if intent.context else intent.intent

            if not query:
                return observation

            # AD-602: Classify query and select strategy
            _ad602_strategy = None
            _question_type = None
            if self._question_classifier and self._retrieval_strategy_selector:
                try:
                    _question_type = self._question_classifier.classify(query)
                    _ad602_strategy = self._retrieval_strategy_selector.select_strategy(_question_type)
                    logger.debug(
                        "AD-602: Query classified as %s - strategy: method=%s, k=%d",
                        _question_type.value,
                        _ad602_strategy.recall_method,
                        _ad602_strategy.k,
                    )
                except Exception:
                    logger.debug("AD-602: Classification failed, using default recall", exc_info=True)

            _mem_id = getattr(self, 'sovereign_id', None) or self.id  # AD-441

            # AD-570c: Try anchor-indexed recall for relational queries
            _anchor_episodes = None
            _query_watch_section = ""  # BF-147: propagate for temporal match scoring
            try:
                _anchor_episodes, _query_watch_section = await self._try_anchor_recall(query, _mem_id)
            except Exception:
                logger.debug("AD-570c: Anchor recall failed, falling through to semantic", exc_info=True)

            # AD-567b: Use salience-weighted recall when available
            em = self._runtime.episodic_memory
            trust_net = getattr(self._runtime, 'trust_network', None)
            heb_router = getattr(self._runtime, 'hebbian_router', None)
            mem_cfg = None
            if hasattr(self._runtime, 'config') and hasattr(self._runtime.config, 'memory'):
                mem_cfg = self._runtime.config.memory

            _ad604_results: list[Any] = []
            if (
                _question_type is not None
                and getattr(_question_type, "value", "") == "causal"
                and getattr(self, "_spreading_activation", None) is not None
            ):
                try:
                    _ad604_results = await self._spreading_activation.multi_hop_recall(
                        query,
                        _mem_id,
                        trust_network=trust_net,
                        hebbian_router=heb_router,
                    )
                    if _ad604_results:
                        observation["_ad604_spreading_activation"] = True
                        logger.debug(
                            "AD-604: Used spreading activation for CAUSAL query with %d results",
                            len(_ad604_results),
                        )
                except Exception:
                    logger.debug("AD-604: Spreading activation failed; falling back to standard recall", exc_info=True)

            # AD-620: Resolve recall tier from rank + billet clearance
            from probos.earned_agency import effective_recall_tier, resolve_billet_clearance, resolve_active_grants, RecallTier
            from probos.cognitive.episodic import resolve_recall_tier_params
            # BF-263: Compute rank from live trust score, not stale self.rank
            # (self.rank is never set on agents; was always None → ENHANCED default)
            _trust_net = getattr(self._runtime, 'trust_network', None)
            _rank = None
            if _trust_net is not None:
                try:
                    from probos.crew_profile import Rank
                    _live_trust = _trust_net.get_score(self.id)
                    if isinstance(_live_trust, (int, float)):
                        _rank = Rank.from_trust(float(_live_trust))
                except Exception:
                    logger.debug("BF-263: rank derivation failed; falling back to self.rank", exc_info=True)
            if _rank is None:
                _rank = getattr(self, 'rank', None)
            _billet_clearance = resolve_billet_clearance(
                getattr(self, 'agent_type', ''),
                getattr(self._runtime, 'ontology', None),
            )
            # AD-622: Include active grants in tier resolution
            _active_grants = resolve_active_grants(
                getattr(self, 'sovereign_id', None) or self.id,
                getattr(self._runtime, 'clearance_grant_store', None),
            )
            _recall_tier = effective_recall_tier(_rank, _billet_clearance, _active_grants)
            _tier_cfg = getattr(mem_cfg, 'recall_tiers', None) if mem_cfg else None
            _tier_params = resolve_recall_tier_params(_recall_tier.value, _tier_cfg)

            # AD-568a: Classify retrieval strategy based on intent type
            from probos.cognitive.source_governance import (
                classify_retrieval_strategy, RetrievalStrategy,
                compute_adaptive_budget, compute_source_framing,
            )
            _intent_type = intent.intent if hasattr(intent, 'intent') else ""
            _episode_count = 0
            if hasattr(em, 'count_for_agent'):
                try:
                    _episode_count = await em.count_for_agent(_mem_id)
                except Exception:
                    _episode_count = 1  # Assume non-zero on error — fail toward retrieval
            # AD-568d: Thread confabulation rate from Counselor profile
            _confab_rate = 0.0
            try:
                if self._runtime and hasattr(self._runtime, 'registry'):
                    _counselor_agents = self._runtime.registry.get_by_pool("counselor")
                    if _counselor_agents:
                        _counselor = _counselor_agents[0]
                        if hasattr(_counselor, 'get_profile'):
                            _profile = _counselor.get_profile(self.id)
                            if _profile:
                                _confab_rate = getattr(_profile, 'confabulation_rate', 0.0)
            except Exception:
                logger.debug("AD-568d: Could not read confabulation rate, defaulting to 0.0")

            _retrieval_strategy = classify_retrieval_strategy(
                _intent_type,
                episodic_count=_episode_count,
                recent_confabulation_rate=_confab_rate,  # AD-568d
            )

            scored_results = []
            if _retrieval_strategy == RetrievalStrategy.NONE and not _ad604_results:
                # Skip episodic recall entirely — agent uses parametric + personality
                logger.debug("AD-568a: Skipping episodic recall for intent '%s' (strategy=NONE)", _intent_type)
                episodes = []
            else:
                # AD-568a DEEP: Expand parameters for deep retrieval
                if _retrieval_strategy == RetrievalStrategy.DEEP:
                    _tier_params = dict(_tier_params)  # Copy to avoid mutating shared config
                    _tier_params["k"] = int(_tier_params.get("k", 5) * 1.5)
                    _tier_params["context_budget"] = int(_tier_params.get("context_budget", 4000) * 1.5)
                    _tier_params["anchor_confidence_gate"] = max(
                        0.0, _tier_params.get("anchor_confidence_gate", 0.3) - 0.1
                    )
                    # AD-590: Relax composite floor for DEEP — wider net, quality still sorts
                    _tier_params["composite_score_floor"] = max(
                        0.0, _tier_params.get("composite_score_floor", 0.0) - 0.10
                    )
                    # AD-591: Relax quality budget for DEEP — allow more episodes and lower quality floor
                    _tier_params["max_recall_episodes"] = int(
                        _tier_params.get("max_recall_episodes", 0) * 1.5
                    ) if _tier_params.get("max_recall_episodes", 0) > 0 else 0
                    _tier_params["recall_quality_floor"] = max(
                        0.0, _tier_params.get("recall_quality_floor", 0.0) - 0.10
                    )

                if _ad604_results:
                    scored_results = _ad604_results
                elif hasattr(em, 'recall_weighted') and _tier_params.get("use_salience_weights", True):
                    _ad602_k = _tier_params.get("k", 5)
                    _ad602_weights = getattr(mem_cfg, 'recall_weights', None) if mem_cfg else None
                    if _ad602_strategy is not None:
                        if _ad602_strategy.recall_method == "weighted":
                            _ad602_k = _ad602_strategy.k
                        if _ad602_strategy.weights_override is not None:
                            observation["_ad602_weights_override"] = _ad602_strategy.weights_override
                            _base_weights = dict(_ad602_weights or {})
                            _base_weights.update(_ad602_strategy.weights_override)
                            _ad602_weights = _base_weights
                    scored_results = await em.recall_weighted(
                        _mem_id, query,
                        trust_network=trust_net,
                        hebbian_router=heb_router,
                        intent_type=intent.intent,
                        k=_ad602_k,
                        context_budget=_tier_params.get("context_budget", 4000),
                        weights=_ad602_weights,
                        anchor_confidence_gate=_tier_params.get("anchor_confidence_gate", 0.3),
                        composite_score_floor=_tier_params.get("composite_score_floor", 0.0),
                        max_recall_episodes=_tier_params.get("max_recall_episodes", 0),
                        recall_quality_floor=_tier_params.get("recall_quality_floor", 0.0),
                        convergence_bonus=getattr(mem_cfg, 'recall_convergence_bonus', 0.10) if mem_cfg else 0.10,
                        query_watch_section=_query_watch_section,  # BF-147: temporal match
                        temporal_match_weight=getattr(mem_cfg, 'recall_temporal_match_weight', 0.25) if mem_cfg else 0.25,
                        temporal_mismatch_penalty=getattr(mem_cfg, 'recall_temporal_mismatch_penalty', 0.15) if mem_cfg else 0.15,  # BF-155
                    )
                elif hasattr(em, 'recall_for_agent'):
                    # BASIC tier: vector similarity only, no salience weighting
                    episodes_raw = await em.recall_for_agent(
                        _mem_id, query, k=_tier_params.get("k", 3)
                    )
                    scored_results = []
                    if episodes_raw:
                        observation["_basic_recall_episodes"] = episodes_raw

                # AD-568b: Adaptive budget scaling based on retrieval quality
                if scored_results and _retrieval_strategy != RetrievalStrategy.NONE:
                    _budget_adj = compute_adaptive_budget(
                        _tier_params.get("context_budget", 4000),
                        recall_scores=scored_results,
                        episode_count=_episode_count,
                        strategy=_retrieval_strategy,
                    )
                    if _budget_adj.scale_factor != 1.0:
                        logger.debug(
                            "AD-568b: Budget adjusted %d→%d (%s)",
                            _budget_adj.original_budget, _budget_adj.adjusted_budget,
                            _budget_adj.reason,
                        )
                        # Re-apply budget enforcement with adjusted budget
                        _adjusted_episodes = []
                        _budget_used = 0
                        for rs in scored_results:
                            _ep_len = len(rs.episode.user_input) if hasattr(rs.episode, 'user_input') else 0
                            if _budget_used + _ep_len > _budget_adj.adjusted_budget and _adjusted_episodes:
                                break
                            _adjusted_episodes.append(rs)
                            _budget_used += _ep_len
                        scored_results = _adjusted_episodes

                # Fallback to old recall path if recall_weighted unavailable or returned nothing
                episodes = [rs.episode for rs in scored_results] if scored_results else []
                if not episodes:
                    episodes = observation.pop("_basic_recall_episodes", [])
                if not episodes:
                    episodes = await em.recall_for_agent(_mem_id, query, k=_tier_params.get("k", 3))
                if not episodes and hasattr(em, 'recent_for_agent'):
                    episodes = await em.recent_for_agent(_mem_id, k=_tier_params.get("k", 3))

                # AD-603: Merge anchor recall with semantic recall (score-aware)
                if _anchor_episodes:
                    from probos.types import RecallScore as _RecallScore

                    _is_scored = bool(_anchor_episodes and isinstance(_anchor_episodes[0], _RecallScore))
                    if _is_scored:
                        _seen_ids: set[str] = {rs.episode.id for rs in _anchor_episodes}
                        _merged: list[_RecallScore] = list(_anchor_episodes)
                        for rs in scored_results:
                            if rs.episode.id in _seen_ids:
                                continue
                            if (
                                _query_watch_section
                                and getattr(rs.episode, "anchors", None)
                                and getattr(rs.episode.anchors, "watch_section", "")
                                and rs.episode.anchors.watch_section != _query_watch_section
                            ):
                                logger.debug(
                                    "BF-155: Excluding episode %s (watch=%s) — query watch=%s",
                                    rs.episode.id[:8],
                                    rs.episode.anchors.watch_section,
                                    _query_watch_section,
                                )
                                continue
                            _merged.append(rs)
                            _seen_ids.add(rs.episode.id)
                        _merged.sort(key=lambda recall_score: recall_score.composite_score, reverse=True)
                        scored_results = _merged
                        episodes = [rs.episode for rs in scored_results]
                    else:
                        _seen_ids = {getattr(ep, 'id', id(ep)) for ep in _anchor_episodes}
                        for ep in episodes:
                            if getattr(ep, 'id', id(ep)) in _seen_ids:
                                continue
                            # BF-155: Exclude semantic episodes whose watch_section contradicts
                            # the query's temporal intent. Without this filter, wrong-watch
                            # episodes contaminate the anchor-filtered recall set.
                            if (
                                _query_watch_section
                                and getattr(ep, "anchors", None)
                                and getattr(ep.anchors, "watch_section", "")
                                and ep.anchors.watch_section != _query_watch_section
                            ):
                                logger.debug(
                                    "BF-155: Excluding episode %s (watch=%s) — query watch=%s",
                                    getattr(ep, 'id', '?')[:8],
                                    ep.anchors.watch_section,
                                    _query_watch_section,
                                )
                                continue
                            _anchor_episodes.append(ep)
                            _seen_ids.add(getattr(ep, 'id', id(ep)))
                        episodes = _anchor_episodes

                # AD-620: Oracle Service — clearance-based access
                # Agents with ORACLE tier (via rank or billet clearance) get Oracle on any strategy.
                logger.debug(
                    "recall_tier=%s for %s (query=%s)",
                    _recall_tier.value, self.agent_type, query[:80],
                )
                if (
                    _recall_tier == RecallTier.ORACLE
                    and hasattr(self, '_runtime')
                    and hasattr(self._runtime, '_oracle_service')
                    and self._runtime._oracle_service
                ):
                    try:
                        oracle = self._runtime._oracle_service
                        oracle_text = await oracle.query_formatted(
                            query_text=query,
                            agent_id=_mem_id,
                            k_per_tier=3,
                            max_chars=2000,
                        )
                        if oracle_text:
                            observation["_oracle_context"] = oracle_text
                            logger.debug(
                                "Oracle context populated for %s (%d chars): %.200s",
                                self.agent_type, len(oracle_text), oracle_text,
                            )
                        else:
                            logger.debug("Oracle returned empty for %s", self.agent_type)
                    except Exception:
                        logger.warning("AD-568a: Oracle query failed, continuing without", exc_info=True)
                elif (
                    _recall_tier in (RecallTier.FULL, RecallTier.ENHANCED)
                    and hasattr(self, '_runtime')
                    and hasattr(self._runtime, '_oracle_service')
                    and self._runtime._oracle_service
                ):
                    # BF-265: Non-ORACLE agents still get knowledge graph (Tier 6)
                    # access. Graph contains structural facts (reports_to, member_of,
                    # competent_in) that any crew agent should see — it's organizational
                    # structure, not classified intelligence.
                    try:
                        oracle = self._runtime._oracle_service
                        graph_text = await oracle.query_formatted(
                            query_text=query,
                            agent_id=_mem_id,
                            k_per_tier=3,
                            max_chars=1000,
                            tiers=["graph"],
                        )
                        if graph_text:
                            observation["_oracle_context"] = graph_text
                    except Exception:
                        logger.debug("BF-265: graph-only Oracle query failed, continuing without")

            # AD-568c: Compute source priority framing
            _framing = None
            if scored_results:
                _scores = [getattr(rs, 'composite_score', 0.0) for rs in scored_results]
                _confs = [getattr(rs, 'anchor_confidence', 0.0) for rs in scored_results]
                _framing = compute_source_framing(
                    mean_anchor_confidence=sum(_confs) / len(_confs) if _confs else 0.0,
                    recall_count=len(scored_results),
                    mean_recall_score=sum(_scores) / len(_scores) if _scores else 0.0,
                    strategy=_retrieval_strategy,
                )
            elif _retrieval_strategy == RetrievalStrategy.NONE:
                _framing = compute_source_framing(strategy=RetrievalStrategy.NONE)
            observation["_source_framing"] = _framing

            # AD-568d: Compute source attribution snapshot
            _source_attribution = None
            try:
                from probos.cognitive.source_governance import compute_source_attribution
                _procedural_count = 0
                try:
                    if hasattr(self, '_procedure_store') and self._procedure_store:
                        _intent_procs = await self._procedure_store.get_by_intent(
                            _intent_type
                        ) if hasattr(self._procedure_store, 'get_by_intent') else []
                        _procedural_count = len(_intent_procs) if _intent_procs else 0
                except Exception:
                    pass
                _source_attribution = compute_source_attribution(
                    retrieval_strategy=_retrieval_strategy,
                    episodic_count=len(scored_results) if scored_results else 0,
                    procedural_count=_procedural_count,
                    oracle_used=bool(observation.get("_oracle_context")),
                    source_framing=_framing,
                    budget_adjustment=_budget_adj if '_budget_adj' in dir() else None,
                    confabulation_rate=_confab_rate,
                )
                observation["_source_attribution"] = _source_attribution
                observation["_source_attribution_obj"] = _source_attribution  # AD-568e: typed object for faithfulness checker
            except Exception:
                logger.debug("AD-568d: Source attribution computation failed")

            # BF-631: drop "query-echo" recalls before rendering. When the
            # Captain asks a question, the most semantically-similar episodes
            # are frequently the Captain's OWN prior identical askings (e.g.
            # "What do you know about my dogs?") — they match the query text
            # almost perfectly yet carry zero information for answering it, and
            # they crowd the genuine answer ("My dog Grim is a giant schnauzer")
            # to the bottom of, or out of, the rendered memory section.
            if episodes and query:
                _non_echo = _filter_query_echoes(episodes, query)
                if len(_non_echo) != len(episodes):
                    logger.info(
                        "BF-631: dropped %d query-echo recall(s) for agent=%s q=%r",
                        len(episodes) - len(_non_echo),
                        (getattr(self, "sovereign_id", None) or self.id)[:8],
                        query[:50],
                    )
                    episodes = _non_echo

            if episodes:
                # AD-502: Include relative timestamps on recalled memories
                rt = getattr(self, '_runtime', None)
                include_ts = True
                if rt and hasattr(rt, 'config') and hasattr(rt.config, 'temporal'):
                    include_ts = rt.config.temporal.include_episode_timestamps

                # AD-541: Verify episodes against EventLog at recall time
                event_log = getattr(self._runtime, 'event_log', None)

                memory_list = []
                # AD-1030: enrich each memory with internal salience inputs ONLY
                # when adaptive salience scoring is enabled. The keys are
                # underscore-prefixed (``_embedding``/``_timestamp``/
                # ``_importance``) and are NEVER rendered by
                # ``_format_memory_section`` — they feed ``_salience_rank_memories``
                # at the DM/WR bid-build. OFF ⇒ no keys added ⇒ byte-identical.
                _salience_on = self._salience_scoring_enabled()
                for ep in episodes:
                    mem = {
                        "input": ep.user_input[:200] if ep.user_input else "",
                        "reflection": ep.reflection[:200] if ep.reflection else "",
                        "source": getattr(ep, 'source', 'direct'),
                    }
                    if _salience_on:
                        mem["_embedding"] = list(ep.embedding) if ep.embedding else []
                        mem["_timestamp"] = float(ep.timestamp or 0.0)
                        mem["_importance"] = int(getattr(ep, "importance", 5))
                    if include_ts and ep.timestamp > 0:
                        mem["age"] = format_duration(time.time() - ep.timestamp)

                    # AD-567b: Anchor context for formatting
                    anchors = getattr(ep, 'anchors', None)
                    if isinstance(anchors, AnchorFrame):
                        mem["anchor_channel"] = anchors.channel or ""
                        mem["anchor_department"] = anchors.department or ""
                        mem["anchor_participants"] = ", ".join(anchors.participants) if anchors.participants else ""
                        mem["anchor_trigger"] = anchors.trigger_type or ""

                    # AD-541 Pillar 1: Cross-check against EventLog
                    mem["verified"] = False
                    if event_log and ep.timestamp > 0 and ep.agent_ids:
                        try:
                            corroborating = await event_log.query(
                                agent_id=ep.agent_ids[0],
                                limit=1,
                            )
                            if corroborating:
                                for evt in corroborating:
                                    evt_ts = evt.get("timestamp", "")
                                    if evt_ts:
                                        from datetime import datetime
                                        try:
                                            evt_time = datetime.fromisoformat(evt_ts).timestamp()
                                            if abs(evt_time - ep.timestamp) < 120:
                                                mem["verified"] = True
                                                break
                                        except (ValueError, TypeError):
                                            pass
                        except Exception:
                            pass  # EventLog unavailable — leave unverified

                    memory_list.append(mem)

                observation["recent_memories"] = memory_list
                # BF-631 DIAG: surface what the per-message recall actually fed
                # into the prompt for a Captain DM — so we can see whether the
                # ANSWER (not just the Captain's repeated question-echoes) lands
                # in context. Concise INFO, direct_message only.
                if intent.intent == "direct_message":
                    _diag_id = (getattr(self, "sovereign_id", None) or self.id)[:8]
                    _diag_summ = " || ".join(
                        f"[{m.get('source', '?')}] "
                        f"{(m.get('input', '') or m.get('reflection', '') or '')[:60]}"
                        for m in memory_list[:8]
                    )
                    logger.info(
                        "BF-631 DM-recall: agent=%s q=%r n=%d :: %s",
                        _diag_id, query[:60], len(memory_list), _diag_summ,
                    )
        except Exception:
            logger.warning("BF-138: Failed to fetch episodic memory context — agent will respond without memory", exc_info=True)

        # AD-979d slice 2: cross-agent associative recall. Gated ENTIRELY behind
        # the default-OFF flag -> when off this block does NOTHING (no extra
        # query, observation untouched) => byte-identical to pre-slice-2.
        # mem_cfg is assigned inside the BF-138 try above; an early exception in
        # that try could leave it unbound, so re-fetch defensively here (the
        # AD-986b block below does the same) -- the OFF guard must never NameError.
        mem_cfg = getattr(getattr(self._runtime, "config", None), "memory", None)
        if mem_cfg is not None and getattr(mem_cfg, "cross_agent_recall_enabled", False):
            try:
                _peer_mems = await self._maybe_cross_agent_recall(query=query, mem_id=_mem_id, k=3)
                if _peer_mems:
                    observation.setdefault("recent_memories", []).extend(_peer_mems)
            except Exception:
                logger.warning("AD-979d: cross-agent recall wiring failed; continuing", exc_info=True)

        # AD-981b + AD-1038: one shared sovereign recall-confidence probe drives
        # BOTH the honest-absence band cue (AD-981b, recall_confidence_gating_enabled)
        # AND the remember/know metacognitive cue (AD-1038, remember_know_typing_enabled).
        # The flags are independent; the probe runs once when EITHER is on, so a
        # both-on config costs a single round-trip. OFF on both => no probe => no
        # observation keys => segments None => no emit => byte-identical.
        mem_cfg = getattr(getattr(self._runtime, "config", None), "memory", None)
        _band_on = mem_cfg is not None and getattr(mem_cfg, "recall_confidence_gating_enabled", False)
        _type_on = mem_cfg is not None and getattr(mem_cfg, "remember_know_typing_enabled", False)
        if _band_on or _type_on:
            try:
                _conf = await self._recall_confidence_probe(query=query, mem_id=_mem_id, k=5)
                if _conf is not None:
                    if _band_on and _conf.band:
                        observation["_recall_fok_band"] = _conf.band
                    if _type_on and _conf.recall_type:
                        observation["_recall_recall_type"] = _conf.recall_type
            except Exception:
                logger.warning("AD-1038: recall-confidence probe failed; continuing", exc_info=True)

        # AD-986b: transcript-grounded recall. The sovereign shard above is a
        # subjective, lossy recollection; the ChatThreadStore transcript is the
        # objective record (the recording). Surface the relevant excerpt of the
        # recording for rooms THIS agent took part in, so it can ground a
        # recollection in what was actually said rather than guess. Sovereign-
        # scoped (the agent's own ids only), bounded, default-off, rendered
        # distinct from subjective memory in _build_user_message. Tier-2: never
        # breaks recall.
        try:
            _mem_cfg = getattr(getattr(self._runtime, "config", None), "memory", None)
            if _mem_cfg is not None and getattr(
                _mem_cfg, "transcript_grounded_recall_enabled", False
            ):
                _store = getattr(self._runtime, "chat_thread_store", None)
                _tg_params = observation.get("params", {})
                _tg_query = (
                    str(_tg_params.get("text", ""))[:200].strip()
                    if intent.intent == "direct_message" else ""
                )
                if _store is not None and _tg_query:
                    from probos.cognitive.transcript_grounding import (
                        consult_transcript,
                        purged_room_notice,
                    )
                    _agent_ids = {
                        x for x in (self.id, getattr(self, "sovereign_id", None)) if x
                    }
                    _excerpt = consult_transcript(
                        _store, _agent_ids, _tg_query,
                        max_threads=getattr(_mem_cfg, "transcript_grounding_max_threads", 8),
                        max_chars=getattr(_mem_cfg, "transcript_grounding_max_chars", 1200),
                    )
                    if _excerpt:
                        observation["_transcript_grounding"] = _excerpt
                    else:
                        # AD-986d: no live recording matched. But if this agent
                        # took part in a room (touching this query) whose recording
                        # has since been PURGED under retention, tell it so honestly
                        # rather than letting it treat its lossy memory as the whole
                        # picture.
                        _notice = purged_room_notice(
                            _store, _agent_ids, _tg_query,
                            max_tombstones=getattr(
                                _mem_cfg, "transcript_grounding_max_threads", 8
                            ),
                        )
                        if _notice:
                            observation["_transcript_purged"] = _notice
        except Exception:
            logger.debug(
                "AD-986b: transcript grounding failed; continuing without it",
                exc_info=True,
            )

        return observation

    async def _recall_confidence_probe(
        self, *, query: str, mem_id: str, k: int = 5
    ) -> "RecallConfidence | None":
        """AD-981b/AD-1038: probe THIS agent's own sovereign RecallConfidence for
        ``query`` by reusing ``recall_for_agent_with_confidence`` (no recompute, no
        ranking change — the band AND the AD-979f remember/know ``recall_type`` are
        already produced there). Reads ONLY ``self._runtime``. Tier-2: any missing
        subsystem or failure returns ``None`` so neither cue fires.
        """
        rt = self._runtime
        if rt is None:
            return None
        em = getattr(rt, "episodic_memory", None)
        if em is None or not hasattr(em, "recall_for_agent_with_confidence"):
            return None
        try:
            _eps, conf = await em.recall_for_agent_with_confidence(mem_id, query, k)
            return conf
        except Exception:
            logger.warning(
                "AD-1038: own recall-confidence probe failed; continuing",
                exc_info=True,
            )
            return None

    async def _recall_confidence_band(
        self, *, query: str, mem_id: str, k: int = 5
    ) -> str:
        """AD-981b: band-only view of the sovereign recall-confidence probe (kept
        as the AD-981b surface; delegates to ``_recall_confidence_probe``). Returns
        "" on any missing subsystem/failure.
        """
        conf = await self._recall_confidence_probe(query=query, mem_id=mem_id, k=k)
        return (getattr(conf, "band", "") or "") if conf is not None else ""

    async def _maybe_cross_agent_recall(
        self, *, query: str, mem_id: str, k: int = 3
    ) -> list[dict]:
        """AD-979d slice 2: on a WEAK own Feeling-of-Knowing band, escalate the
        query to the single most-associated crew peer (Hebbian ``REL_SOCIAL``
        top-1) and return that peer's CONFIDENT recall as ``SECONDHAND`` memory
        dicts. Reads ONLY ``self.id`` and ``self._runtime``.

        Tier-2 throughout: every gate or failure returns ``[]`` so a disabled,
        ungated, or failed escalation is byte-identical to no cross-agent recall.
        The call site is itself flag-gated, so this helper is never even reached
        while ``cross_agent_recall_enabled`` is False.

        ID-space resolution (AD-979d): ``REL_SOCIAL`` Hebbian edges key on the
        LIVE ``agent.id``; episodic shards key on ``sovereign_id or id`` -- the
        two diverge for onboarded crew. Peers are therefore ranked by live-id
        social weight (``self.id`` space); the chosen peer is passed to the
        service as a SINGLETON shard id, so the service's internal preferred-
        target ranking over a 1-element list is an identity. ``mem_id`` (shard
        space) drives the service's self-exclusion and own-shard governance.
        """
        rt = self._runtime
        if rt is None:
            return []
        mem_cfg = getattr(getattr(rt, "config", None), "memory", None)
        if mem_cfg is None or not getattr(mem_cfg, "cross_agent_recall_enabled", False):
            return []
        service = getattr(rt, "_cross_agent_recall_service", None)
        if service is None:
            return []
        em = getattr(rt, "episodic_memory", None)
        registry = getattr(rt, "registry", None)
        hebbian = getattr(rt, "hebbian_router", None)
        if em is None or registry is None or hebbian is None:
            return []
        try:
            from probos.crew_utils import is_crew_agent
            from probos.mesh.routing import REL_SOCIAL
            from probos.types import MemorySource

            ontology = getattr(rt, "ontology", None)
            peers = [
                a
                for a in registry.all()
                if getattr(a, "id", None) != self.id and is_crew_agent(a, ontology)
            ][:32]
            if not peers:
                return []

            # Own Feeling-of-Knowing band -- escalate ONLY on a weak (slow-gap)
            # band: a strong own recall needs no help; a "none" absence must not
            # be papered over with a peer's guess.
            _own_eps, own_conf = await em.recall_for_agent_with_confidence(
                mem_id, query, k
            )
            if own_conf.band != "weak":
                return []

            # Rank crew peers by LIVE-id REL_SOCIAL weight; only ask a peer this
            # agent is genuinely associated with (weight > 0).
            peers.sort(
                key=lambda a: hebbian.get_weight(self.id, a.id, REL_SOCIAL),
                reverse=True,
            )
            top = peers[0]
            if hebbian.get_weight(self.id, top.id, REL_SOCIAL) <= 0.0:
                return []

            # Cross the id-space boundary HERE: ranked in live space, query the
            # service in shard space with a singleton candidate set.
            top_shard_id = getattr(top, "sovereign_id", "") or top.id
            callsign_registry = getattr(rt, "callsign_registry", None)
            callsign = top.agent_type
            if callsign_registry is not None:
                callsign = (
                    callsign_registry.get_callsign(top.agent_type) or top.agent_type
                )

            peer_recalls = await service.escalate_recall(
                mem_id,
                query,
                own_conf.band,
                peer_candidates=[top_shard_id],
                callsigns={top_shard_id: callsign},
                k=k,
            )
            if not peer_recalls:
                return []

            mems: list[dict] = []
            for pr in peer_recalls:
                ep = pr.episode
                # MemorySource.SECONDHAND.value (the STRING) -- byte-consistent
                # with how every other recent_memories entry carries source
                # (Episode.source is a str field; the bare enum renders as its
                # repr under Python 3.12's enum __format__, breaking the marker).
                mem = {
                    "input": f"{pr.peer_callsign} recalls: {(ep.user_input or '')[:200]}",
                    "reflection": (ep.reflection or "")[:200],
                    "source": MemorySource.SECONDHAND.value,
                    "verified": False,
                }
                anchors = getattr(ep, "anchors", None)
                if isinstance(anchors, AnchorFrame):
                    if anchors.channel:
                        mem["anchor_channel"] = anchors.channel
                    if anchors.department:
                        mem["anchor_department"] = anchors.department
                    if anchors.trigger_type:
                        mem["anchor_trigger"] = anchors.trigger_type
                mems.append(mem)
            return mems
        except Exception:
            logger.warning(
                "AD-979d: cross-agent recall escalation failed; continuing without",
                exc_info=True,
            )
            return []

    def _build_episode_dag_summary(self, observation: dict) -> dict:
        """AD-568e: Build dag_summary with faithfulness + source attribution metadata."""
        summary: dict = {}
        # AD-568d: Source attribution
        _attr = observation.get("_source_attribution")
        if _attr is not None:
            try:
                if hasattr(_attr, 'primary_source'):
                    summary["source_attribution"] = {
                        "primary_source": _attr.primary_source.value if hasattr(_attr.primary_source, 'value') else str(_attr.primary_source),
                        "episodic_count": getattr(_attr, 'episodic_count', 0),
                        "procedural_count": getattr(_attr, 'procedural_count', 0),
                        "oracle_used": getattr(_attr, 'oracle_used', False),
                        "confabulation_rate": getattr(_attr, 'confabulation_rate', 0.0),
                    }
                elif isinstance(_attr, dict):
                    summary["source_attribution"] = _attr
            except Exception:
                pass
        # AD-568e: Faithfulness
        _faith = observation.get("_faithfulness")
        if _faith is not None:
            try:
                summary["faithfulness_score"] = _faith.score
                summary["faithfulness_grounded"] = _faith.grounded
            except Exception:
                pass
        # AD-589: Introspective faithfulness
        _intro_faith = observation.get("_introspective_faithfulness")
        if _intro_faith is not None:
            try:
                summary["introspective_faithfulness_score"] = _intro_faith.score
                summary["introspective_faithfulness_grounded"] = _intro_faith.grounded
                summary["introspective_contradictions"] = len(_intro_faith.contradictions)
            except Exception:
                pass
        return summary

    async def _try_anchor_recall(
        self, query: str, agent_mem_id: str
    ) -> tuple[list | None, str]:
        """AD-570c: Attempt anchor-indexed recall if query has relational signals.

        Returns (episodes, watch_section). BF-147: watch_section propagated
        for temporal match scoring in recall_weighted().
        """
        from probos.cognitive.source_governance import parse_anchor_query

        # Gather known callsigns for bare-name validation
        known_callsigns: list[str] = []
        if self._runtime and hasattr(self._runtime, 'callsign_registry'):
            try:
                _all = self._runtime.callsign_registry.all_callsigns()
                known_callsigns = list(_all.values()) if isinstance(_all, dict) else list(_all)
            except Exception:
                pass

        anchor = parse_anchor_query(query, known_callsigns=known_callsigns)
        if not anchor.has_anchor_signal:
            return None, ""

        em = self._runtime.episodic_memory
        if not hasattr(em, 'recall_by_anchor'):
            return None, anchor.watch_section or ""

        trust_net = getattr(self._runtime, 'trust_network', None)
        heb_router = getattr(self._runtime, 'hebbian_router', None)
        mem_cfg = None
        if hasattr(self._runtime, 'config') and hasattr(self._runtime.config, 'memory'):
            mem_cfg = self._runtime.config.memory

        if hasattr(em, 'recall_by_anchor_scored'):
            try:
                scored_results = await em.recall_by_anchor_scored(
                    department=anchor.department,
                    trigger_agent=anchor.trigger_agent,
                    participants=anchor.participants if anchor.participants else None,
                    time_range=anchor.time_range,
                    watch_section=anchor.watch_section,
                    semantic_query=anchor.semantic_query,
                    agent_id=agent_mem_id,
                    limit=10,
                    trust_network=trust_net,
                    hebbian_router=heb_router,
                    intent_type="",
                    weights=getattr(mem_cfg, 'recall_weights', None) if mem_cfg else None,
                    query_watch_section=anchor.watch_section or "",
                    temporal_match_weight=getattr(mem_cfg, 'recall_temporal_match_weight', 0.25) if mem_cfg else 0.25,
                    temporal_mismatch_penalty=getattr(mem_cfg, 'recall_temporal_mismatch_penalty', 0.15) if mem_cfg else 0.15,
                )
            except Exception:
                logger.debug("AD-603: recall_by_anchor_scored failed, falling back to unscored", exc_info=True)
                scored_results = None

            if scored_results:
                logger.debug(
                    "AD-603: Scored anchor recall returned %d results (dept=%s, agent=%s, watch=%s)",
                    len(scored_results), anchor.department, anchor.trigger_agent, anchor.watch_section,
                )
                return scored_results, anchor.watch_section or ""

        try:
            results = await em.recall_by_anchor(
                department=anchor.department,
                trigger_agent=anchor.trigger_agent,
                participants=anchor.participants if anchor.participants else None,
                time_range=anchor.time_range,
                watch_section=anchor.watch_section,  # BF-134
                semantic_query=anchor.semantic_query,
                agent_id=agent_mem_id,
                limit=10,
            )
        except Exception:
            logger.debug("AD-570c: recall_by_anchor failed", exc_info=True)
            return None, anchor.watch_section or ""

        if isinstance(results, list) and results:
            logger.debug(
                "AD-570c: Anchor recall returned %d episodes (dept=%s, agent=%s, watch=%s)",
                len(results), anchor.department, anchor.trigger_agent, anchor.watch_section,
            )
        return (results if isinstance(results, list) and results else None), anchor.watch_section or ""

    def _check_response_faithfulness(
        self,
        decision: dict,
        observation: dict,
    ) -> "FaithfulnessResult | None":
        """AD-568e: Post-decision faithfulness check.

        Compares the LLM response against recalled memories that were
        in the observation context. Fire-and-forget — never blocks the
        intent pipeline.

        Returns FaithfulnessResult or None if check cannot be performed.
        """
        try:
            from probos.cognitive.source_governance import (
                check_faithfulness as _check_faith,
                FaithfulnessResult,
            )

            # Extract response text from decision
            response_text = decision.get("llm_output", "") or decision.get("response", "")
            if not response_text:
                return None

            # Extract recalled memories from observation
            raw_memories = observation.get("memories", [])
            if not raw_memories:
                return FaithfulnessResult(
                    score=1.0,
                    evidence_overlap=0.0,
                    unsupported_claim_ratio=0.0,
                    evidence_count=0,
                    grounded=True,
                    detail="No episodic evidence to verify against — parametric response",
                )

            # Build memory text list
            memory_texts = []
            for mem in raw_memories:
                if isinstance(mem, dict):
                    text = mem.get("user_input", "") or mem.get("content", "")
                    if text:
                        memory_texts.append(text)
                elif isinstance(mem, str):
                    memory_texts.append(mem)

            # Get source attribution from observation (AD-568d)
            source_attr = observation.get("_source_attribution_obj")

            return _check_faith(
                response_text=response_text,
                recalled_memories=memory_texts,
                source_attribution=source_attr,
            )

        except Exception:
            logger.debug("AD-568e: Faithfulness check failed", exc_info=True)
            return None

    def _check_memory_leakage(self, decision: dict, observation: dict) -> None:
        """AD-607d: detect responses that reference episodes outside the
        caller's sovereign shard.

        Sibling of ``_check_introspective_faithfulness``. Observational v1 —
        emits ``MEMORY_LEAK_SUSPECTED`` when leakage is detected; never
        mutates the response.
        """
        from probos.cognitive.memory_security import check_memory_leakage
        from probos.events import EventType

        response_text = ""
        if isinstance(decision, dict):
            response_text = (
                decision.get("response")
                or decision.get("answer")
                or decision.get("text")
                or ""
            )
        if not response_text:
            return

        recalled: list[Any] = []
        if isinstance(observation, dict):
            for key in (
                "_recalled_episodes",
                "_basic_recall_episodes",
                "_relevant_memories",
            ):
                value = observation.get(key)
                if isinstance(value, list) and value:
                    recalled = value
                    break
        if not recalled:
            return

        caller_id = (
            getattr(self, "sovereign_id", "")
            or getattr(self, "id", "")
            or ""
        )
        suspected, leaked_ids = check_memory_leakage(
            response_text, recalled, caller_sovereign_id=caller_id,
        )
        if not suspected:
            return

        _rt = getattr(self, "_runtime", None)
        emit = None
        if _rt is not None:
            emit = getattr(_rt, "emit_event", None) or getattr(
                _rt, "_emit_event", None,
            )
        if emit is not None:
            try:
                emit(EventType.MEMORY_LEAK_SUSPECTED, {
                    "agent_id": caller_id,
                    "leaked_episode_ids": list(leaked_ids),
                })
            except Exception:
                logger.debug(
                    "AD-607d: leak event emit failed", exc_info=True,
                )

    def _check_introspective_faithfulness(
        self,
        decision: dict,
    ) -> "IntrospectiveFaithfulnessResult | None":
        """AD-589: Post-decision introspective faithfulness check.

        Compares the LLM response against the CognitiveArchitectureManifest
        (AD-587) and available telemetry. Fire-and-forget — never blocks
        the intent pipeline. Follows AD-568e pattern exactly.
        """
        try:
            from probos.cognitive.source_governance import (
                check_introspective_faithfulness as _check_intro,
                IntrospectiveFaithfulnessResult,
            )

            response_text = decision.get("llm_output", "") or decision.get("response", "")
            if not response_text:
                return None

            # AD-587: Manifest is static architectural truth — construct directly
            from probos.cognitive.orientation import CognitiveArchitectureManifest
            manifest = CognitiveArchitectureManifest()

            # Get telemetry snapshot if available (AD-588) — use cached snapshot
            # from last DM/WR injection to avoid async call in sync method
            telemetry = None
            _wm = getattr(self, '_working_memory', None)
            if _wm:
                telemetry = getattr(_wm, '_last_telemetry_snapshot', None)

            return _check_intro(
                response_text=response_text,
                manifest=manifest,
                telemetry_snapshot=telemetry,
            )
        except Exception:
            logger.debug("AD-589: introspective faithfulness check failed", exc_info=True)
            return None

    async def _store_action_episode(self, intent: IntentMessage, observation: dict, report: dict) -> None:
        """AD-430c: Universal post-action episode storage for crew agents.

        This is the safety net — ensures every crew agent action produces a memory
        record. Callers that already store episodes (proactive loop, Ward Room
        service, HXI API) produce sovereign-shard episodes through their own paths,
        but this hook captures any actions that would otherwise be missed.

        Deduplication: proactive_think is skipped (AD-430a stores in proactive.py).
        ward_room_notification is skipped (AD-430a stores in ward_room.py).
        direct_message from hxi_profile is skipped (AD-430b stores in api.py).
        direct_message from captain (shell /hail) is skipped (shell.py stores).
        """
        # AD-566a: Skip episode storage for qualification test interactions
        if intent.params.get("_qualification_test"):
            return

        # Skip intents that already have dedicated episode storage
        if intent.intent == "proactive_think":
            return
        if intent.intent == "ward_room_notification":
            return

        params = observation.get("params", {})
        source = params.get("from", "")
        if intent.intent == "direct_message" and source in ("hxi_profile", "captain"):
            return

        # Guard: need runtime + episodic memory + crew check
        if not self._runtime:
            return
        if not hasattr(self._runtime, 'episodic_memory') or not self._runtime.episodic_memory:
            return
        if not hasattr(self._runtime, 'ontology'):
            return
        from probos.crew_utils import is_crew_agent as _is_crew
        if not _is_crew(self, getattr(self._runtime, 'ontology', None)):
            return

        try:
            import time as _time
            from probos.types import AnchorFrame, Episode, MemorySource

            result_text = str(report.get("result", ""))[:500]
            callsign = ""
            if hasattr(self._runtime, 'callsign_registry'):
                callsign = self._runtime.callsign_registry.get_callsign(self.agent_type) or ""

            query_text = params.get("text", intent.context or intent.intent)

            # AD-567a: Resolve department for anchor
            _dept = ""
            try:
                _ont = getattr(self._runtime, 'ontology', None)
                if _ont:
                    _dept = _ont.get_agent_department(self.agent_type) or ""
                if not _dept:
                    from probos.cognitive.standing_orders import get_department as _get_dept
                    _dept = _get_dept(self.agent_type) or ""
            except Exception:
                pass

            # AD-567b: SECONDHAND source wiring
            # If this action was triggered by another agent's communication,
            # tag the resulting episode as secondhand.
            _source = MemorySource.DIRECT
            _trigger_from = params.get("from", "")
            if _trigger_from and intent.intent not in ("direct_message",):
                # Check if trigger agent is someone else
                _my_ids = {
                    getattr(self, 'sovereign_id', None) or self.id,
                    self.agent_type,
                    callsign,
                    self.id,
                }
                _my_ids.discard("")
                _my_ids.discard(None)
                if _trigger_from not in _my_ids:
                    _source = MemorySource.SECONDHAND

            episode = Episode(
                user_input=f"[Action: {intent.intent}] {callsign or self.agent_type}: {str(query_text)[:200]}",
                timestamp=_time.time(),
                agent_ids=[getattr(self, 'sovereign_id', None) or self.id],
                outcomes=[{
                    "intent": intent.intent,
                    "success": report.get("success", False),
                    "response": result_text,
                    "agent_type": self.agent_type,
                    "source": source or "intent_bus",
                    # AD-632g: Chain metadata for procedure extraction
                    **(observation.get("_chain_metadata") or {}),
                    # AD-643b: Trigger learning feedback
                    **({
                        "undeclared_actions": observation["_undeclared_action_feedback"].get("undeclared_actions", []),
                        "missed_skills": observation["_undeclared_action_feedback"].get("missed_skills", []),
                    } if observation.get("_undeclared_action_feedback") else {}),
                }],
                dag_summary=self._build_episode_dag_summary(observation),  # AD-568e
                reflection=f"{callsign or self.agent_type} handled {intent.intent}: {result_text[:100]}",
                source=_source,
                anchors=AnchorFrame(
                    channel="action",
                    department=_dept,
                    trigger_type=intent.intent,
                    trigger_agent=params.get("from", ""),
                    # AD-663: Provenance - the triggering observation is the root artifact
                    source_origin_id=observation.get("correlation_id", "") or "",
                    artifact_version=hashlib.sha256(
                        str(query_text)[:500].encode("utf-8")
                    ).hexdigest()[:16],
                ),
                correlation_id=observation.get("correlation_id", ""),
            )
            from probos.cognitive.episodic import EpisodicMemory
            if EpisodicMemory.should_store(episode):
                await self._runtime.episodic_memory.store(episode)
        except Exception:
            logger.debug("Failed to store action episode", exc_info=True)

    async def interpret_recall(
        self,
        episodes: list[Any],
        *,
        focus: str = "",
        store: bool = True,
    ) -> str | None:
        """AD-980a: produce an honesty-bounded interpretation of recalled memories.

        The meaning-making rung above retrieval (AD-979 made recall *honest*;
        this makes it *meaningful*): an instructions-first LLM pass over the
        agent's OWN recalled ``episodes`` returns a short first-person reading of
        what they mean to it, optionally stored as an agent-owned reflection
        episode so the interpretation itself becomes recallable. Reuses the
        AD-721d ``propose_appearance`` reflection shape.

        Honesty bound (AD-592): the prompt instructs the agent to ground every
        statement in the memories shown and to say plainly when they do not
        support a conclusion; the stored episode is labeled ``[interpretation]``
        and tagged ``MemorySource.REFLECTION`` so it is never mistaken for a
        first-hand record. Honest by construction: with no episodes there is
        nothing to interpret, so it returns ``None`` (never invents).

        Opt-in: returns ``None`` unless ``communications.recall_interpretation_
        enabled`` is set (an extra LLM pass, so OFF by default). Tier-2: any LLM
        failure returns ``None`` (the caller proceeds without an interpretation).
        """
        runtime = self._runtime
        comm_cfg = getattr(getattr(runtime, "config", None), "communications", None)
        if not getattr(comm_cfg, "recall_interpretation_enabled", False):
            return None
        if self._llm_client is None:
            return None
        if not episodes:
            # Nothing genuinely recalled -> nothing to interpret. Honest no-op.
            return None
        return await self._run_interpretation(episodes, focus=focus, store=store)

    async def interpret_own_dream(self, *, k: int = 5) -> str | None:
        """AD-980c: an agent interprets ITS OWN dream (the meaning-making loop).

        The novel sleep->dream->wake->interpret loop. AD-980b gives a dream a
        dreamer (per-agent reflection episodes); this gathers THIS agent's most
        recent dream reflections and runs the AD-980a interpretation engine over
        them, storing the result as an agent-owned episode that feeds the
        self-model. Honesty-bounded by construction (AD-592): the dream
        reflections are real consolidated material, and with none there is
        nothing to interpret (returns ``None``).

        Opt-in: returns ``None`` unless ``communications.dream_interpretation_
        enabled`` (an extra LLM pass per agent per dream). Tier-2: any failure
        returns ``None``.
        """
        runtime = self._runtime
        comm_cfg = getattr(getattr(runtime, "config", None), "communications", None)
        if not getattr(comm_cfg, "dream_interpretation_enabled", False):
            return None
        if self._llm_client is None:
            return None
        em = getattr(runtime, "episodic_memory", None) if runtime else None
        if em is None or not hasattr(em, "recent_for_agent"):
            return None

        sovereign = getattr(self, "sovereign_id", None) or self.id
        try:
            # Pull a recency window of this agent's own episodes, then keep the
            # dream reflections (AD-980b attributed them; AD-599 tags them
            # MemorySource.REFLECTION). Scan wider than k so non-dream episodes
            # in the window don't crowd the dreams out.
            recent = await em.recent_for_agent(sovereign, k=max(k * 4, 20))
        except Exception:
            logger.debug(
                "AD-980c: recent_for_agent failed for %s; no dream to interpret",
                self.id[:12], exc_info=True,
            )
            return None

        from probos.types import MemorySource
        dreams = [
            e for e in recent
            if getattr(e, "source", None) in (MemorySource.REFLECTION, "reflection")
        ][:k]
        if not dreams:
            return None
        return await self._run_interpretation(
            dreams,
            focus="what these dream reflections reveal about how you work and what matters to you",
            store=True,
        )

    async def _run_interpretation(
        self, episodes: list[Any], *, focus: str = "", store: bool = True,
    ) -> str | None:
        """AD-980a/c: shared interpretation engine (no config gate \u2014 the public
        entrypoints ``interpret_recall`` / ``interpret_own_dream`` own the gating).

        Builds an instructions-first reflection prompt from real episode content,
        runs one LLM pass, and (optionally) stores an agent-owned reflection
        episode. Honesty-bound (AD-592): grounds the agent in the episodes shown
        and instructs it to say plainly when they do not support a conclusion.
        """
        if self._llm_client is None:
            return None
        runtime = self._runtime

        # Build the recalled-material block from real episode content only.
        lines: list[str] = []
        for i, ep in enumerate(episodes, start=1):
            text = (getattr(ep, "user_input", "") or "").strip()
            refl = (getattr(ep, "reflection", "") or "").strip()
            snippet = text if text else refl
            if not snippet:
                continue
            lines.append(f"{i}. {snippet[:300]}")
        if not lines:
            return None
        recalled_block = "\n".join(lines)

        callsign = ""
        if runtime is not None and hasattr(runtime, "callsign_registry"):
            try:
                callsign = runtime.callsign_registry.get_callsign(self.agent_type) or ""
            except Exception:
                callsign = ""
        who = callsign or self.agent_type

        system_prompt = (
            "You are reflecting on your OWN recalled memories to understand what "
            "they mean to you. Write a brief first-person interpretation (2-4 "
            "sentences): the pattern or significance you see, and why. Ground "
            "every statement in the memories shown. If the memories do not "
            "support a conclusion, say so plainly and stop. Reference only what "
            "is actually present in them; never add events that are not there. "
            "Output prose only."
        )
        focus_line = f"\nFocus your reflection on: {focus.strip()}" if focus.strip() else ""
        user_message = (
            f"You are {who}. These are memories you recalled:\n\n"
            f"{recalled_block}{focus_line}\n\n"
            "What do you make of these? Interpret them honestly."
        )

        try:
            request = LLMRequest(
                prompt=user_message,
                system_prompt=system_prompt,
                tier=self._resolve_tier() if hasattr(self, "_resolve_tier") else "standard",
                max_tokens=512,
            )
            response = await self._llm_client.complete(request, priority=Priority.NORMAL)
        except Exception:
            logger.warning(
                "AD-980a: interpretation LLM call failed for %s; "
                "no interpretation produced", self.id[:12], exc_info=True,
            )
            return None

        interpretation = (getattr(response, "content", "") or "").strip()
        if not interpretation:
            return None

        if store:
            await self._store_interpretation_episode(interpretation, len(lines))
        return interpretation

    async def _store_interpretation_episode(
        self, interpretation: str, source_count: int
    ) -> None:
        """AD-980a: persist a recall interpretation as an agent-owned episode.

        Stored with ``MemorySource.REFLECTION`` and a ``[interpretation]``-prefixed
        reflection so it is recallable later yet never mistaken for a first-hand
        memory (AD-592). Tier-2 honest-degrade: a store failure is logged and
        swallowed (the interpretation was still returned to the caller).
        """
        runtime = self._runtime
        if runtime is None or not getattr(runtime, "episodic_memory", None):
            return
        try:
            import time as _time
            from probos.types import AnchorFrame, Episode, MemorySource

            sovereign = getattr(self, "sovereign_id", None) or self.id
            episode = Episode(
                user_input=(
                    f"[interpretation] reflection on {source_count} recalled "
                    f"{'memory' if source_count == 1 else 'memories'}"
                ),
                timestamp=_time.time(),
                agent_ids=[sovereign],
                outcomes=[{
                    "kind": "recall_interpretation",  # AD-980a distinct tag
                    "success": True,
                    # The interpretation IS the agent's output — carry it as the
                    # outcome response so the AD selective-encoding gate
                    # (should_store) sees real content and retains the episode.
                    "response": interpretation[:500],
                    "agent_type": self.agent_type,
                }],
                dag_summary={},
                reflection=f"[interpretation] {interpretation[:400]}",
                # AD-980a: importance above the default so a self-interpretation
                # is retained and resurfaces (it is meaning the agent derived,
                # not raw event capture). Below the high-stakes correction band.
                importance=6,
                source=MemorySource.REFLECTION,
                anchors=AnchorFrame(
                    channel="reflection",
                    trigger_type="recall_interpretation",
                ),
            )
            from probos.cognitive.episodic import EpisodicMemory
            if EpisodicMemory.should_store(episode):
                await runtime.episodic_memory.store(episode)
        except Exception:
            logger.debug(
                "AD-980a: failed to store interpretation episode", exc_info=True,
            )

    def _resolve_tier(self) -> str:
        """Determine which LLM tier to use.  Default: 'standard'.
        Override in subclasses for tier-specific routing."""
        return "standard"

    def _resolve_tier_for_observation(self, observation: dict) -> str:
        """AD-700c: Per-call tier override.

        If ``observation`` carries ``level_llm_tier`` (set by an agent's
        ``perceive()`` -- currently DiagnosticianAgent for ``diagnose_system``
        intents), use that as the LLM tier for this single call. Otherwise
        fall back to ``self._resolve_tier()`` (the static per-agent default).

        Returns ``""`` (empty string) iff the observation explicitly requests
        no LLM call (level_llm_tier is None). Callers must check for the
        empty return and short-circuit before constructing an ``LLMRequest``.
        """
        override = observation.get("level_llm_tier")
        if override is None and "level_llm_tier" in observation:
            return ""
        if isinstance(override, str) and override:
            return override
        return self._resolve_tier()

    # --- Decision cache helpers (AD-272) ---

    def _compute_cache_key(self, observation: dict) -> str:
        """Compute a deterministic hash from instructions + observation."""
        obs_str = json.dumps(observation, sort_keys=True, default=str)
        key_material = f"{self.instructions}|{obs_str}"
        return hashlib.sha256(key_material.encode()).hexdigest()[:16]

    def _get_cache_ttl(self) -> float:
        """Determine TTL based on agent instructions."""
        if not self.instructions:
            return self._cache_ttl_seconds
        lower = self.instructions.lower()
        if any(kw in lower for kw in ("real-time", "current", "live", "latest", "now", "price", "weather", "stock")):
            return 120.0  # 2 minutes
        if any(kw in lower for kw in ("translate", "define", "calculate", "convert", "summarize")):
            return 3600.0  # 1 hour
        return self._cache_ttl_seconds

    @classmethod
    def evict_cache_for_type(cls, agent_type: str, observation: dict | None = None) -> int:
        """Evict cache entries for an agent type. Returns count of evicted entries."""
        cache = _DECISION_CACHES.get(agent_type, {})
        if not cache:
            return 0
        if observation is None:
            count = len(cache)
            cache.clear()
            return count
        return 0

    @classmethod
    def cache_stats(cls) -> dict[str, dict[str, int]]:
        """Return cache statistics per agent type."""
        stats = {}
        for agent_type, cache in _DECISION_CACHES.items():
            stats[agent_type] = {
                "entries": len(cache),
                "hits": _CACHE_HITS.get(agent_type, 0),
                "misses": _CACHE_MISSES.get(agent_type, 0),
            }
        return stats
