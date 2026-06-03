"""AD-858: LLM-driven semantic plan decomposer.

Turns a single free-text goal (the markdown plan body handed to
``PlanDecomposer.decompose``) into a validated DAG of :class:`WorkItemSpec`
rows. This is the semantic counterpart to v1's
:class:`~probos.consultation.dispatch.MarkdownPlanDecomposer`: instead of
parsing ATX-2 headings, it asks an LLM to break the goal into sub-tasks with
explicit ``depends_on`` edges and optional ``expected_output`` acceptance
criteria.

Design constraints (verified against the ``PlanDecomposer`` Protocol seam):

* ``decompose`` stays **synchronous** — ``ParallelDispatcher.dispatch`` calls
  it inline from inside a running event loop. The async ``LLMClient.complete``
  coroutine is therefore driven on a dedicated worker thread with its own loop
  (``ThreadPoolExecutor`` + ``asyncio.run``) so we never call ``asyncio.run``
  on the caller's already-running loop.
* The decomposer never crashes the dispatch path. Empty input, an LLM error,
  malformed JSON, dangling dependency edges, dependency cycles, or fan-out past
  ``max_subtasks`` all degrade honestly to a single passthrough spec or a
  repaired DAG rather than raising (Tier-2 log-and-degrade).
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import re
import uuid
from typing import Any, Protocol

from probos.consultation.dispatch import WorkItemSpec
from probos.types import LLMRequest, LLMResponse

logger = logging.getLogger(__name__)

# Hard ceiling guarding against a pathological LLM emitting thousands of specs
# even when the configured ``max_subtasks`` is mis-set high. The configured cap
# is applied first; this is a final defence-in-depth bound.
_ABSOLUTE_SPEC_CEILING = 200

_DEFAULT_MAX_SUBTASKS = 12

_SYSTEM_PROMPT = (
    "You are a planning decomposer for an agent operating system. Break the "
    "user's goal into a minimal DAG of concrete sub-tasks. Respond with ONLY a "
    "JSON array (no prose, no markdown fences). Each element is an object with "
    "keys: \"spec_id\" (short stable slug, unique), \"title\" (imperative "
    "phrase), \"description\" (optional), \"depends_on\" (array of spec_id "
    "strings that must finish first; [] for none), and \"expected_output\" "
    "(optional one-sentence acceptance criterion, or null). Do not invent "
    "dependency ids that are not themselves spec_ids in the array. Keep the "
    "graph acyclic. Emit the smallest number of sub-tasks that fully covers "
    "the goal."
)


class _LLMClientLike(Protocol):
    """Narrow view of the LLM client the decomposer depends on.

    Interface Segregation: the decomposer only needs ``complete``; it does not
    take a hard dependency on the concrete ``LLMClient`` class.
    """

    async def complete(self, request: LLMRequest) -> LLMResponse: ...


def _slugify(value: str) -> str:
    out = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value).strip().lower()).strip("-")
    return out or uuid.uuid4().hex[:8]


class LLMPlanDecomposer:
    """Semantic ``PlanDecomposer`` backed by an LLM.

    Conforms structurally to
    :class:`~probos.consultation.dispatch.PlanDecomposer`.
    """

    def __init__(
        self,
        client: _LLMClientLike,
        *,
        tier: str = "standard",
        max_subtasks: int = _DEFAULT_MAX_SUBTASKS,
    ) -> None:
        self._client = client
        self._tier = tier
        # Clamp to sane bounds: at least 1 spec, never above the hard ceiling.
        self._max_subtasks = max(1, min(int(max_subtasks), _ABSOLUTE_SPEC_CEILING))

    # ------------------------------------------------------------------
    # PlanDecomposer protocol
    # ------------------------------------------------------------------
    def decompose(self, markdown_text: str) -> list[WorkItemSpec]:
        """Decompose a goal into a validated ``WorkItemSpec`` DAG.

        Always returns at least one spec. On any failure (empty goal, LLM
        error, malformed output) it returns a single passthrough spec wrapping
        the original goal so the dispatch path can still proceed.
        """
        goal = (markdown_text or "").strip()
        if not goal:
            logger.warning(
                "AD-858: empty goal handed to LLMPlanDecomposer; "
                "degrading to a single passthrough spec.",
            )
            return [self._passthrough(goal)]

        content = self._call_llm(goal)
        if content is None:
            return [self._passthrough(goal)]

        raw = self._parse_json(content, goal)
        if not raw:
            return [self._passthrough(goal)]

        specs = self._build_specs(raw)
        if not specs:
            logger.warning(
                "AD-858: LLM output yielded zero usable specs; "
                "degrading to a single passthrough spec.",
            )
            return [self._passthrough(goal)]

        return self._validate_dag(specs, goal)

    # ------------------------------------------------------------------
    # LLM call (sync -> async thread bridge)
    # ------------------------------------------------------------------
    def _call_llm(self, goal: str) -> str | None:
        """Run the async ``complete`` coroutine to completion synchronously.

        ``decompose`` is invoked inline from ``ParallelDispatcher.dispatch``,
        which runs on the main event loop. Calling ``asyncio.run`` there would
        raise ``RuntimeError: asyncio.run() cannot be called from a running
        event loop``. We therefore submit the coroutine to a single-worker
        thread that owns its own fresh loop via ``asyncio.run``.
        """
        req = LLMRequest(prompt=goal, system_prompt=_SYSTEM_PROMPT, tier=self._tier)
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                resp = ex.submit(lambda: asyncio.run(self._client.complete(req))).result()
        except Exception as exc:  # noqa: BLE001 - honest-degrade, never crash dispatch
            logger.warning(
                "AD-858: LLM decomposition call failed (%s); "
                "degrading to a single passthrough spec.",
                exc,
            )
            return None

        if resp is None:
            logger.warning(
                "AD-858: LLM decomposition returned no response; "
                "degrading to a single passthrough spec.",
            )
            return None
        if getattr(resp, "error", None):
            logger.warning(
                "AD-858: LLM decomposition reported error (%s); "
                "degrading to a single passthrough spec.",
                resp.error,
            )
            return None
        return resp.content or ""

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------
    def _parse_json(self, content: str, goal: str) -> list[dict[str, Any]]:
        """Extract a JSON array of spec dicts from raw LLM text.

        Tolerates leading/trailing prose and ```` ```json ```` fences by
        slicing to the first ``[`` and last ``]``. Returns ``[]`` on failure.
        """
        text = (content or "").strip()
        if not text:
            return []
        candidate = text
        if not candidate.startswith("["):
            start = candidate.find("[")
            end = candidate.rfind("]")
            if start == -1 or end == -1 or end <= start:
                logger.warning(
                    "AD-858: no JSON array found in LLM decomposition output; "
                    "degrading to a single passthrough spec.",
                )
                return []
            candidate = candidate[start : end + 1]
        try:
            parsed = json.loads(candidate)
        except (ValueError, TypeError) as exc:
            logger.warning(
                "AD-858: malformed JSON in LLM decomposition output (%s); "
                "degrading to a single passthrough spec.",
                exc,
            )
            return []
        if not isinstance(parsed, list):
            logger.warning(
                "AD-858: LLM decomposition output was %s, expected a JSON array; "
                "degrading to a single passthrough spec.",
                type(parsed).__name__,
            )
            return []
        return [item for item in parsed if isinstance(item, dict)]

    def _build_specs(self, raw: list[dict[str, Any]]) -> list[WorkItemSpec]:
        """Materialise raw dicts into ``WorkItemSpec`` rows with unique ids.

        Enforces ``max_subtasks`` (truncating excess), assigns slugged ids,
        de-duplicates ids, and normalises ``depends_on`` / ``expected_output``.
        """
        specs: list[WorkItemSpec] = []
        seen_ids: set[str] = set()
        for item in raw[: self._max_subtasks]:
            title = str(item.get("title") or item.get("spec_id") or "").strip()
            if not title:
                continue
            spec_id = str(item.get("spec_id") or _slugify(title)).strip() or _slugify(title)
            # Guarantee uniqueness so depends_on translation stays unambiguous.
            base_id = spec_id
            suffix = 1
            while spec_id in seen_ids:
                spec_id = f"{base_id}-{suffix}"
                suffix += 1
            seen_ids.add(spec_id)

            depends_raw = item.get("depends_on") or []
            if isinstance(depends_raw, (list, tuple)):
                depends_on = tuple(str(d).strip() for d in depends_raw if str(d).strip())
            else:
                depends_on = ()

            expected = item.get("expected_output")
            expected_output = str(expected).strip() if isinstance(expected, str) and expected.strip() else None

            description = str(item.get("description") or "").strip()

            specs.append(
                WorkItemSpec(
                    spec_id=spec_id,
                    title=title,
                    description=description,
                    depends_on=depends_on,
                    expected_output=expected_output,
                )
            )
        return specs

    # ------------------------------------------------------------------
    # Schema / DAG validation
    # ------------------------------------------------------------------
    def _validate_dag(self, specs: list[WorkItemSpec], goal: str) -> list[WorkItemSpec]:
        """Repair dangling edges and reject cycles.

        * Every ``depends_on`` entry that does not reference an emitted
          ``spec_id`` is dropped (dangling-edge repair).
        * If the resulting graph still contains a cycle, the whole
          decomposition is rejected in favour of a single passthrough spec —
          a cyclic plan cannot be dispatched safely.
        """
        valid_ids = {s.spec_id for s in specs}
        repaired: list[WorkItemSpec] = []
        for spec in specs:
            kept = tuple(d for d in spec.depends_on if d in valid_ids and d != spec.spec_id)
            if len(kept) != len(spec.depends_on):
                dropped = [d for d in spec.depends_on if d not in kept]
                logger.warning(
                    "AD-858: dropped %d dangling/self dependency edge(s) %s "
                    "from spec %r during DAG repair.",
                    len(dropped),
                    dropped,
                    spec.spec_id,
                )
            if kept == spec.depends_on:
                repaired.append(spec)
            else:
                repaired.append(self._with_deps(spec, kept))

        if self._has_cycle(repaired):
            logger.warning(
                "AD-858: LLM decomposition produced a dependency cycle; "
                "rejecting the DAG and degrading to a single passthrough spec.",
            )
            return [self._passthrough(goal)]
        return repaired

    @staticmethod
    def _with_deps(spec: WorkItemSpec, depends_on: tuple[str, ...]) -> WorkItemSpec:
        return WorkItemSpec(
            spec_id=spec.spec_id,
            title=spec.title,
            description=spec.description,
            work_type=spec.work_type,
            agent=spec.agent,
            priority=spec.priority,
            depends_on=depends_on,
            resources=spec.resources,
            metadata=dict(spec.metadata),
            expected_output=spec.expected_output,
        )

    @staticmethod
    def _has_cycle(specs: list[WorkItemSpec]) -> bool:
        """Detect a cycle in the depends_on graph via DFS colouring."""
        graph: dict[str, tuple[str, ...]] = {s.spec_id: s.depends_on for s in specs}
        WHITE, GREY, BLACK = 0, 1, 2
        colour: dict[str, int] = {sid: WHITE for sid in graph}

        def visit(node: str) -> bool:
            colour[node] = GREY
            for dep in graph.get(node, ()):  # dep guaranteed to be a valid id post-repair
                state = colour.get(dep, BLACK)
                if state == GREY:
                    return True
                if state == WHITE and visit(dep):
                    return True
            colour[node] = BLACK
            return False

        return any(colour[sid] == WHITE and visit(sid) for sid in graph)

    # ------------------------------------------------------------------
    # Degrade helper
    # ------------------------------------------------------------------
    @staticmethod
    def _passthrough(goal: str) -> WorkItemSpec:
        """Single spec wrapping the whole goal — the honest-degrade fallback."""
        title = goal.strip() or "Complete the requested goal"
        # Keep the title compact; preserve the full goal in the description.
        short = title.splitlines()[0][:120] if title else "Complete the requested goal"
        return WorkItemSpec(
            spec_id=_slugify(short),
            title=short,
            description=goal,
            depends_on=(),
            expected_output=None,
        )
