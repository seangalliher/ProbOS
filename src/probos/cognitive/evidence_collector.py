"""AD-454: EvidenceCollector — auto-classifies Ward Room posts against the
emergence taxonomy. Pure observer. OSS-tier file output.

Default disabled. When enabled, subscribes to WARD_ROOM_POST_CREATED via
runtime.add_event_listener and writes one YAML file per accepted
classification under config.emergence_collector.output_dir.

Not federation-synced. Not consumed by trust, Hebbian, or consensus.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml as _yaml  # PyYAML, declared in pyproject.toml
except ImportError:  # pragma: no cover - dependency declared in pyproject
    _yaml = None  # type: ignore[assignment]

from probos.cognitive.emergence_taxonomy import (
    TAXONOMY,
    BehaviorCode,
    as_classifier_prompt,
)
from probos.types import LLMRequest

logger = logging.getLogger(__name__)


# Map "MGT-DIR" string back to BehaviorCode enum member.
_VALUE_TO_CODE: dict[str, BehaviorCode] = {c.value: c for c in BehaviorCode}


@dataclass(frozen=True)
class EvidenceObservation:
    """One persisted classification."""

    obs_id: str
    timestamp: float
    trial_id: str
    post_id: str
    thread_id: str
    author_id: str
    author_callsign: str
    behavior_codes: tuple[BehaviorCode, ...]
    confidence: float
    reasoning: str
    raw_response: str = ""


class EvidenceCollector:
    """Passive Ward Room observer that classifies posts against the taxonomy.

    Pure observer — no trust effects, no Hebbian effects, no Ward Room
    posting, no consensus participation. Listener registration is
    performed by the finalize wirer; this class only exposes the handler
    methods.
    """

    tier: str = "utility"

    def __init__(
        self,
        *,
        runtime: Any,
        confidence_threshold: float = 0.7,
        dedup_window_seconds: float = 600.0,
        output_dir: Path | str = "data/research/emergence-evidence",
        llm_tier: str = "fast",
        trial_id: str = "default",
        thread_context_limit: int = 5,
        max_reasoning_chars: int = 2000,
    ) -> None:
        self._runtime = runtime
        self._confidence_threshold = float(confidence_threshold)
        self._dedup_window_seconds = float(dedup_window_seconds)
        self._output_dir = Path(output_dir) / trial_id
        self._llm_tier = llm_tier
        self._trial_id = trial_id
        self._thread_context_limit = int(thread_context_limit)
        self._max_reasoning_chars = int(max_reasoning_chars)
        self._classifier_prompt = as_classifier_prompt()
        # Per-collector lock guarantees monotonic gapless OBS numbering
        # under concurrent post events. One collector per runtime, so
        # an instance-level lock is sufficient.
        self._persist_lock = asyncio.Lock()
        self._next_obs_n: int | None = None
        # Dedup index: (author_id, behavior_code) -> last_persist_timestamp.
        self._recent: dict[tuple[str, BehaviorCode], float] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def on_ward_room_post(self, event: Any) -> None:
        """Listener entry point. Tier-2 (log-and-degrade) at every boundary.

        Never raises out of this method — runtime.add_event_listener
        dispatches via asyncio.create_task without storing the task
        reference, so any propagated exception is silently lost.
        """
        try:
            payload = self._extract_payload(event)
            if payload is None:
                return
            post_id = payload.get("post_id")
            thread_id = payload.get("thread_id")
            author_id = payload.get("author_id")
            author_callsign = payload.get("author_callsign", "") or ""
            if not post_id or not thread_id or not author_id:
                logger.warning(
                    "AD-454: WARD_ROOM_POST_CREATED missing required keys "
                    "(post_id=%r, thread_id=%r, author_id=%r); skipping.",
                    post_id, thread_id, author_id,
                )
                return
            await self.classify_post(
                post_id=str(post_id),
                thread_id=str(thread_id),
                author_id=str(author_id),
                author_callsign=str(author_callsign),
            )
        except Exception:
            logger.exception(
                "AD-454: unexpected error in EvidenceCollector listener "
                "(trial=%s); collector remains operational.",
                self._trial_id,
            )

    async def classify_post(
        self,
        *,
        post_id: str,
        thread_id: str,
        author_id: str,
        author_callsign: str,
    ) -> EvidenceObservation | None:
        """Classify one post and return the persisted observation, or None.

        Returns None when the post is filtered (low confidence, dedup,
        unknown codes, LLM failure, malformed JSON, OSError on persist).
        Never raises.
        """
        try:
            body, thread_context = await self._fetch_post_context(
                post_id=post_id, thread_id=thread_id
            )
            if body is None:
                logger.warning(
                    "AD-454: post %s could not be fetched for classification "
                    "(trial=%s); skipping.",
                    post_id, self._trial_id,
                )
                return None

            raw = await self._call_classifier_llm(
                post_body=body,
                thread_context=thread_context,
                author_callsign=author_callsign,
            )
            if raw is None:
                return None

            codes, confidence, reasoning = self._parse_llm_response(raw)
            if not codes or confidence < self._confidence_threshold:
                logger.debug(
                    "AD-454: post %s skipped (codes=%s, confidence=%.2f, "
                    "threshold=%.2f).",
                    post_id, [c.value for c in codes], confidence,
                    self._confidence_threshold,
                )
                return None

            now = time.time()
            if self._is_duplicate(author_id=author_id, codes=codes, now=now):
                logger.debug(
                    "AD-454: post %s by %s deduped within %.0fs window.",
                    post_id, author_id, self._dedup_window_seconds,
                )
                return None

            obs = EvidenceObservation(
                obs_id="OBS-PENDING",  # filled in by _persist under lock
                timestamp=now,
                trial_id=self._trial_id,
                post_id=post_id,
                thread_id=thread_id,
                author_id=author_id,
                author_callsign=author_callsign,
                behavior_codes=codes,
                confidence=confidence,
                reasoning=reasoning,
                raw_response=raw,
            )
            persisted = await self._persist(obs)
            if persisted is None:
                return None
            self._record_dedup(author_id=author_id, codes=codes, ts=now)
            return persisted
        except Exception:
            logger.exception(
                "AD-454: unexpected error classifying post %s (trial=%s); "
                "skipping.",
                post_id, self._trial_id,
            )
            return None

    async def record_observation(
        self,
        *,
        behavior_code: BehaviorCode,
        thread_id: str,
        author_id: str,
        author_callsign: str = "",
        reasoning: str = "",
        confidence: float = 1.0,
    ) -> EvidenceObservation | None:
        """AD-1121: persist a PRE-CLASSIFIED observation (bypasses the LLM classifier).

        For detectors that already know the code (e.g. the AD-1121 divergence
        probe). Reuses the dedup window + gapless OBS-NNNN numbering. Tier-2:
        returns None on dedup / persist failure; never raises.
        """
        try:
            now = time.time()
            if self._is_duplicate(
                author_id=author_id, codes=(behavior_code,), now=now
            ):
                logger.debug(
                    "AD-1121: observation for author=%s code=%s deduped within "
                    "%.0fs window.",
                    author_id, behavior_code.value, self._dedup_window_seconds,
                )
                return None
            clamped = float(confidence)
            if clamped < 0.0:
                clamped = 0.0
            elif clamped > 1.0:
                clamped = 1.0
            text = reasoning or ""
            if len(text) > self._max_reasoning_chars:
                text = text[: self._max_reasoning_chars]
            obs = EvidenceObservation(
                obs_id="OBS-PENDING",  # filled in by _persist under lock
                timestamp=now,
                trial_id=self._trial_id,
                post_id=f"{thread_id}:{behavior_code.value}",
                thread_id=thread_id,
                author_id=author_id,
                author_callsign=author_callsign,
                behavior_codes=(behavior_code,),
                confidence=clamped,
                reasoning=text,
                raw_response="",
            )
            persisted = await self._persist(obs)
            if persisted is None:
                return None
            self._record_dedup(
                author_id=author_id, codes=(behavior_code,), ts=now
            )
            return persisted
        except Exception:
            logger.exception(
                "AD-1121: unexpected error recording observation (code=%s, "
                "thread=%s, trial=%s); skipping.",
                getattr(behavior_code, "value", behavior_code),
                thread_id, self._trial_id,
            )
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_payload(event: Any) -> dict[str, Any] | None:
        """Pull the payload dict from either a raw dict or a BaseEvent-shaped object."""
        if isinstance(event, dict):
            payload = event.get("payload")
            if isinstance(payload, dict):
                return payload
            return event  # already flat
        payload = getattr(event, "payload", None)
        if isinstance(payload, dict):
            return payload
        return None

    async def _fetch_post_context(
        self, *, post_id: str, thread_id: str
    ) -> tuple[str | None, list[dict[str, Any]]]:
        """Read body + short thread context via the public ward_room API."""
        ward_room = getattr(self._runtime, "ward_room", None)
        if ward_room is None:
            logger.warning(
                "AD-454: runtime.ward_room is None when classifying post %s; "
                "skipping.", post_id,
            )
            return None, []
        try:
            post = await ward_room.get_post(post_id)
        except Exception:
            logger.exception(
                "AD-454: ward_room.get_post(%s) failed (trial=%s); skipping.",
                post_id, self._trial_id,
            )
            return None, []
        if not post:
            return None, []
        body = post.get("body") or ""

        thread_context: list[dict[str, Any]] = []
        if self._thread_context_limit > 0:
            try:
                thread = await ward_room.get_thread(
                    thread_id, post_limit=self._thread_context_limit
                )
            except Exception:
                logger.exception(
                    "AD-454: ward_room.get_thread(%s) failed (trial=%s); "
                    "continuing without thread context.",
                    thread_id, self._trial_id,
                )
                thread = None
            if isinstance(thread, dict):
                # Pull a flat body list; structure varies but is best-effort.
                posts = thread.get("posts") or thread.get("children") or []
                if isinstance(posts, list):
                    thread_context = [p for p in posts if isinstance(p, dict)]
        return body, thread_context

    async def _call_classifier_llm(
        self,
        *,
        post_body: str,
        thread_context: list[dict[str, Any]],
        author_callsign: str,
    ) -> str | None:
        """Tier-2 wrapper around llm_client.complete. Returns raw text or None."""
        llm = getattr(self._runtime, "llm_client", None)
        if llm is None:
            logger.warning(
                "AD-454: runtime.llm_client is None; cannot classify "
                "(trial=%s).", self._trial_id,
            )
            return None
        ctx_lines: list[str] = []
        for p in thread_context[: self._thread_context_limit]:
            cs = p.get("author_callsign") or p.get("author_id") or "?"
            body = p.get("body") or ""
            ctx_lines.append(f"- {cs}: {body}")
        ctx_text = "\n".join(ctx_lines) if ctx_lines else "(no prior thread context)"
        user_prompt = (
            f"Author callsign: {author_callsign}\n"
            f"Thread context (most recent posts):\n{ctx_text}\n\n"
            f"POST TO CLASSIFY:\n{post_body}\n"
        )
        request = LLMRequest(
            prompt=user_prompt,
            system_prompt=self._classifier_prompt,
            tier=self._llm_tier,
            temperature=0.0,
            max_tokens=1024,
        )
        try:
            response = await llm.complete(request)
        except Exception as exc:
            logger.warning(
                "AD-454: llm_client.complete failed (trial=%s, tier=%s, "
                "error=%s); skipping classification.",
                self._trial_id, self._llm_tier, type(exc).__name__,
            )
            return None
        content = getattr(response, "content", None)
        if not content:
            logger.warning(
                "AD-454: LLM returned empty content (trial=%s); skipping.",
                self._trial_id,
            )
            return None
        return str(content)

    def _parse_llm_response(
        self, raw: str
    ) -> tuple[tuple[BehaviorCode, ...], float, str]:
        """Strict JSON parsing with permissive code matching.

        - Extracts the first JSON object from raw (in case the LLM emits
          markdown fences or stray prose).
        - Maps free-text codes to BehaviorCode values; unknown codes drop.
        - Confidence clamped to [0.0, 1.0].
        - Reasoning truncated to max_reasoning_chars.
        """
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not match:
            logger.warning(
                "AD-454: LLM response contained no JSON object (trial=%s); "
                "skipping.",
                self._trial_id,
            )
            return (), 0.0, ""
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            logger.warning(
                "AD-454: LLM JSON parse failed (trial=%s, error=%s); skipping.",
                self._trial_id, exc,
            )
            return (), 0.0, ""
        if not isinstance(data, dict):
            logger.warning(
                "AD-454: LLM JSON was not an object (trial=%s); skipping.",
                self._trial_id,
            )
            return (), 0.0, ""

        raw_codes = data.get("codes") or []
        if not isinstance(raw_codes, list):
            raw_codes = []
        seen: set[BehaviorCode] = set()
        codes: list[BehaviorCode] = []
        for c in raw_codes:
            if not isinstance(c, str):
                continue
            entry = _VALUE_TO_CODE.get(c.strip().upper())
            if entry is None:
                logger.debug(
                    "AD-454: LLM returned unknown code %r; ignoring.", c,
                )
                continue
            if entry in seen:
                continue
            seen.add(entry)
            codes.append(entry)

        try:
            confidence = float(data.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < 0.0:
            confidence = 0.0
        elif confidence > 1.0:
            confidence = 1.0

        reasoning = data.get("reasoning") or ""
        if not isinstance(reasoning, str):
            reasoning = str(reasoning)
        if len(reasoning) > self._max_reasoning_chars:
            reasoning = reasoning[: self._max_reasoning_chars]

        return tuple(codes), confidence, reasoning

    def _is_duplicate(
        self,
        *,
        author_id: str,
        codes: tuple[BehaviorCode, ...],
        now: float,
    ) -> bool:
        """True if any (author, code) pair is within the dedup window."""
        if self._dedup_window_seconds <= 0.0:
            return False
        for code in codes:
            ts = self._recent.get((author_id, code))
            if ts is not None and (now - ts) <= self._dedup_window_seconds:
                return True
        return False

    def _record_dedup(
        self,
        *,
        author_id: str,
        codes: tuple[BehaviorCode, ...],
        ts: float,
    ) -> None:
        for code in codes:
            self._recent[(author_id, code)] = ts

    def _scan_existing_obs_max(self) -> int:
        """Scan trial dir for existing OBS-NNNN.yaml files; return max N or 0."""
        if not self._output_dir.exists():
            return 0
        max_n = 0
        pat = re.compile(r"OBS-(\d{4,})\.yaml$", flags=re.IGNORECASE)
        try:
            for entry in self._output_dir.iterdir():
                if not entry.is_file():
                    continue
                m = pat.search(entry.name)
                if not m:
                    continue
                try:
                    n = int(m.group(1))
                except ValueError:
                    continue
                if n > max_n:
                    max_n = n
        except OSError:
            logger.exception(
                "AD-454: failed to scan existing OBS files in %s (trial=%s); "
                "starting from OBS-0001.",
                self._output_dir, self._trial_id,
            )
            return 0
        return max_n

    async def _persist(
        self, obs: EvidenceObservation
    ) -> EvidenceObservation | None:
        """Write a single OBS-NNNN.yaml file under the trial dir.

        Concurrency-safe via instance lock. Tier-2 — returns None on
        OSError/yaml failure rather than propagating.
        """
        async with self._persist_lock:
            try:
                self._output_dir.mkdir(parents=True, exist_ok=True)
            except OSError:
                logger.exception(
                    "AD-454: cannot create output dir %s (trial=%s); skipping.",
                    self._output_dir, self._trial_id,
                )
                return None
            if self._next_obs_n is None:
                self._next_obs_n = self._scan_existing_obs_max() + 1
            n = self._next_obs_n
            obs_id = f"OBS-{n:04d}"
            target = self._output_dir / f"{obs_id}.yaml"

            persisted = EvidenceObservation(
                obs_id=obs_id,
                timestamp=obs.timestamp,
                trial_id=obs.trial_id,
                post_id=obs.post_id,
                thread_id=obs.thread_id,
                author_id=obs.author_id,
                author_callsign=obs.author_callsign,
                behavior_codes=obs.behavior_codes,
                confidence=obs.confidence,
                reasoning=obs.reasoning,
                raw_response=obs.raw_response,
            )
            try:
                content = self._render_yaml(persisted)
            except Exception:
                logger.exception(
                    "AD-454: failed to render YAML for %s (trial=%s); skipping.",
                    obs_id, self._trial_id,
                )
                return None
            try:
                target.write_text(content, encoding="utf-8")
            except OSError:
                logger.exception(
                    "AD-454: failed to write %s (trial=%s); skipping.",
                    target, self._trial_id,
                )
                return None
            # Only advance the counter on a successful write.
            self._next_obs_n = n + 1
            logger.info(
                "AD-454: persisted %s (trial=%s, codes=%s, confidence=%.2f)",
                obs_id, self._trial_id,
                [c.value for c in persisted.behavior_codes],
                persisted.confidence,
            )
            return persisted

    def _render_yaml(self, obs: EvidenceObservation) -> str:
        """Render an OBS file. Uses PyYAML when available; deterministic key order."""
        data: dict[str, Any] = {
            "obs_id": obs.obs_id,
            "timestamp": obs.timestamp,
            "trial_id": obs.trial_id,
            "post_id": obs.post_id,
            "thread_id": obs.thread_id,
            "author_id": obs.author_id,
            "author_callsign": obs.author_callsign,
            "behavior_codes": [c.value for c in obs.behavior_codes],
            "confidence": obs.confidence,
            "reasoning": obs.reasoning,
            "raw_response": obs.raw_response,
        }
        if _yaml is not None:
            return _yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
        # Fallback (PyYAML missing — declared in pyproject so this is a
        # belt-and-braces path). Hand-rolled key-order-preserving writer.
        lines: list[str] = []
        for key in (
            "obs_id", "timestamp", "trial_id", "post_id", "thread_id",
            "author_id", "author_callsign",
        ):
            lines.append(f"{key}: {json.dumps(data[key])}")
        lines.append("behavior_codes:")
        for c in data["behavior_codes"]:
            lines.append(f"- {json.dumps(c)}")
        lines.append(f"confidence: {data['confidence']}")
        lines.append("reasoning: |")
        for ln in str(data["reasoning"]).splitlines() or [""]:
            lines.append(f"  {ln}")
        lines.append("raw_response: |")
        for ln in str(data["raw_response"]).splitlines() or [""]:
            lines.append(f"  {ln}")
        return "\n".join(lines) + "\n"
