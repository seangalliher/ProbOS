"""AD-487: PersonalOntologyProber — Map-step probe of an agent's self-knowledge.

Builds a structured self-query from a JSON-only template, calls the LLM via
``runtime.llm_client.complete(LLMRequest)``, parses the response into a frozen
``ProbeResult``, persists it to the ``agent_probes`` SQLite table, and emits
``ONTOLOGY_PROBE_RECORDED`` / ``ONTOLOGY_PROBE_RATE_LIMITED`` events.

v1 ships the Map step only. Collapse / Reduce / Daydream / DID-portability are
deferred to AD-487b/c/d/e.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Callable

from probos.events import EventType
from probos.protocols import ConnectionFactory, DatabaseConnection
from probos.types import LLMRequest, LLMResponse, Priority

if TYPE_CHECKING:
    from probos.config import SelfDistillationConfig

logger = logging.getLogger(__name__)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS agent_probes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    domain TEXT NOT NULL,
    sub_topics_json TEXT NOT NULL,
    confidence_scores_json TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    probed_at TEXT NOT NULL  -- ISO 8601 UTC, tz-aware
);
CREATE INDEX IF NOT EXISTS idx_agent_probes_agent_domain
    ON agent_probes(agent_id, domain, probed_at DESC);
"""


class ProbeLLMError(RuntimeError):
    """Raised when the LLM call backing a Map-step probe fails."""


class ProbeRateLimitedError(RuntimeError):
    """Raised when a probe is rejected because the (agent, domain) is within the 24h window."""


@dataclass(frozen=True)
class ProbeResult:
    """Single Map-step probe result. AD-487 v1 surface."""

    agent_id: str
    domain: str
    sub_topics: tuple[str, ...]
    confidence_scores: tuple[float, ...]
    raw_text: str
    probed_at: datetime


class PersonalOntologyProber:
    """Map-step prober: structured self-queries, rate-limited, persisted.

    AD-487 v1 surface. Collapse + Reduce + daydream deferred to AD-487b/c/d.
    """

    # Use .format(domain=domain, max_sub_topics=N) — NOT f-string. The doubled
    # braces around the example JSON are literal output the model should emit.
    PROBE_TEMPLATE = (
        "You are introspecting on your own knowledge. "
        "Answer in JSON only: "
        "{{\"sub_topics\": [...up to {max_sub_topics} strings...], "
        "\"confidence\": [{max_sub_topics} floats in 0.0-1.0]}}\n\n"
        "What do you know about {domain}?"
    )

    def __init__(
        self,
        runtime: Any,
        config: "SelfDistillationConfig",
        *,
        connection_factory: ConnectionFactory | None = None,
    ) -> None:
        self._runtime = runtime
        self._config = config
        self._db: DatabaseConnection | None = None
        self._connection_factory: ConnectionFactory
        if connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            self._connection_factory = default_factory
        else:
            self._connection_factory = connection_factory
        # Late-bind emit_event_fn (Wave 5 convention #5).
        self._emit_event_fn: Callable[..., None] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Open the SQLite connection and create the schema if missing."""
        self._db = await self._connection_factory.connect(str(self._config.db_path))
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def stop(self) -> None:
        """Close the SQLite connection."""
        if self._db is not None:
            await self._db.close()
            self._db = None

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    async def probe_domain(self, agent_id: str, domain: str) -> ProbeResult:
        """Run a Map-step probe. Rate-limited per (agent, domain, 24h)."""
        if self._db is None:
            raise RuntimeError(
                "PersonalOntologyProber not started; call await prober.start() first"
            )

        allowed = await self._check_rate_limit(agent_id, domain)
        if not allowed:
            raise ProbeRateLimitedError(
                f"Probe of (agent={agent_id}, domain={domain}) within "
                f"{self._config.rate_limit_hours}h window"
            )

        prompt = self.PROBE_TEMPLATE.format(
            domain=domain,
            max_sub_topics=self._config.max_sub_topics,
        )
        request = LLMRequest(
            prompt=prompt,
            system_prompt="",
            tier="standard",
            temperature=0.0,
            top_p=1.0,
            max_tokens=512,
        )

        try:
            response: LLMResponse = await asyncio.wait_for(
                self._runtime.llm_client.complete(request, priority=Priority.NORMAL),
                timeout=self._config.llm_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            logger.error(
                "AD-487: LLM probe timed out for agent=%s domain=%s after %.1fs; "
                "raising ProbeLLMError",
                agent_id, domain, self._config.llm_timeout_seconds,
            )
            raise ProbeLLMError(
                f"LLM probe timed out after {self._config.llm_timeout_seconds}s"
            ) from exc
        except Exception as exc:  # noqa: BLE001 — wrap into typed error
            logger.error(
                "AD-487: LLM probe failed for agent=%s domain=%s: %s; "
                "raising ProbeLLMError",
                agent_id, domain, exc,
            )
            raise ProbeLLMError(f"LLM probe failed: {exc}") from exc

        if response.error:
            logger.error(
                "AD-487: LLM probe returned error for agent=%s domain=%s: %s",
                agent_id, domain, response.error,
            )
            raise ProbeLLMError(response.error)

        raw = response.content
        sub_topics: tuple[str, ...]
        confidence: tuple[float, ...]
        try:
            parsed = json.loads(raw)
            sub_topics = tuple(
                str(x) for x in parsed.get("sub_topics", [])
            )[: self._config.max_sub_topics]
            confidence = tuple(
                float(x) for x in parsed.get("confidence", [])
            )[: self._config.max_sub_topics]
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning(
                "AD-487: failed to parse probe JSON for agent=%s domain=%s (%s); "
                "preserving raw_text and returning empty sub_topics",
                agent_id, domain, exc,
            )
            sub_topics = ()
            confidence = ()

        result = ProbeResult(
            agent_id=agent_id,
            domain=domain,
            sub_topics=sub_topics,
            confidence_scores=confidence,
            raw_text=raw,
            probed_at=datetime.now(timezone.utc),
        )
        await self._persist(result)
        return result

    async def get_recent_probes(self, agent_id: str, k: int = 10) -> list[ProbeResult]:
        """Return up to k most recent probes for agent, ordered by probed_at desc."""
        if self._db is None:
            raise RuntimeError(
                "PersonalOntologyProber not started; call await prober.start() first"
            )
        await self._db.execute(
            "SELECT agent_id, domain, sub_topics_json, confidence_scores_json, "
            "raw_text, probed_at FROM agent_probes "
            "WHERE agent_id = ? ORDER BY probed_at DESC LIMIT ?",
            (agent_id, k),
        )
        rows = await self._db.fetchall()
        results: list[ProbeResult] = []
        for row in rows:
            results.append(
                ProbeResult(
                    agent_id=row[0],
                    domain=row[1],
                    sub_topics=tuple(json.loads(row[2])),
                    confidence_scores=tuple(json.loads(row[3])),
                    raw_text=row[4],
                    probed_at=datetime.fromisoformat(row[5]),
                )
            )
        return results

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _check_rate_limit(self, agent_id: str, domain: str) -> bool:
        """True if probe is allowed; emit ONTOLOGY_PROBE_RATE_LIMITED otherwise."""
        assert self._db is not None  # caller guarantees started
        await self._db.execute(
            "SELECT probed_at FROM agent_probes "
            "WHERE agent_id = ? AND domain = ? "
            "ORDER BY probed_at DESC LIMIT 1",
            (agent_id, domain),
        )
        row = await self._db.fetchone()
        if row is None:
            return True
        last = datetime.fromisoformat(row[0])
        now = datetime.now(timezone.utc)
        window = timedelta(hours=self._config.rate_limit_hours)
        if (now - last) < window:
            if self._emit_event_fn is not None:
                self._emit_event_fn(
                    EventType.ONTOLOGY_PROBE_RATE_LIMITED,
                    {
                        "agent_id": agent_id,
                        "domain": domain,
                        "last_probed_at": last.isoformat(),
                    },
                )
            return False
        return True

    async def _persist(self, result: ProbeResult) -> None:
        """Write to agent_probes; emit ONTOLOGY_PROBE_RECORDED."""
        assert self._db is not None  # caller guarantees started
        await self._db.execute(
            "INSERT INTO agent_probes "
            "(agent_id, domain, sub_topics_json, confidence_scores_json, "
            " raw_text, probed_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                result.agent_id,
                result.domain,
                json.dumps(list(result.sub_topics)),
                json.dumps(list(result.confidence_scores)),
                result.raw_text,
                result.probed_at.isoformat(),
            ),
        )
        await self._db.commit()
        if self._emit_event_fn is not None:
            self._emit_event_fn(
                EventType.ONTOLOGY_PROBE_RECORDED,
                {
                    "agent_id": result.agent_id,
                    "domain": result.domain,
                    "sub_topic_count": len(result.sub_topics),
                },
            )
