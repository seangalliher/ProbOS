"""Creative output writer (AD-525 v1).

Publishes agent creative works to ``creative/{callsign}/{topic_slug}.md``
via the existing :class:`probos.knowledge.records_store.RecordsStore`.
Mirrors the canonical ``write_entry`` caller pattern at proactive.py:3033
(AD-554 convergence reports).

Default classification is ``ship`` (shared culture per AD-525 design).
``medium`` and ``skill_id`` are encoded in ``tags=["creative", medium,
skill_id]`` because :meth:`RecordsStore.write_entry` does not accept
arbitrary frontmatter keys (verified at records_store.py:113-148).
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from probos.events import EventType

logger = logging.getLogger(__name__)


class CreativeOutputError(Exception):
    """Raised when a creative work cannot be published.

    Wraps a missing ``records_store`` on the runtime or any error from
    :meth:`RecordsStore.write_entry`. Per Wave 9 convention #20, this
    small exception type lives with its primary class.
    """


class CreativeOutputWriter:
    """Writes agent creative works to Ship's Records under ``creative/{callsign}/``.

    AD-525 v1. Mirrors the ``RecordsStore.write_entry`` caller pattern at
    proactive.py:3033 (AD-554). Default classification is ``ship`` (shared
    culture per AD-525 design).
    """

    def __init__(
        self,
        runtime: Any,
        config: Any,
        *,
        records_store: Any | None = None,
    ) -> None:
        self._runtime = runtime
        self._config = config
        self._records_store = records_store
        # Late-bind setter (Wave 5 convention #5).
        self._emit_event_fn: Callable[..., None] | None = None

    def _resolve_records_store(self) -> Any:
        """Return the bound records store, falling back to ``runtime.records_store``.

        Caches the resolved store on first call. Raises :class:`CreativeOutputError`
        if no store is available.
        """
        if self._records_store is None:
            rs = getattr(self._runtime, "records_store", None)
            if rs is None:
                raise CreativeOutputError("records_store unavailable on runtime")
            self._records_store = rs
        return self._records_store

    async def publish(
        self,
        author_callsign: str,
        topic_slug: str,
        content: str,
        *,
        medium: str,
        skill_id: str,
        department: str = "",
        classification: str | None = None,
    ) -> str:
        """Write a creative work to Ship's Records.

        Args:
            author_callsign: Agent's callsign (used in path
                ``creative/{callsign}/{topic_slug}.md``).
            topic_slug: URL-safe slug for the work title.
            content: The creative work itself (Markdown body).
            medium: One of the skill's media (e.g. ``"poetry"``, ``"essay"``,
                ``"diagram"``).
            skill_id: References ``CreativeSkillsRegistry`` skill_id.
            department: Optional department of author (frontmatter).
            classification: ``"ship"`` / ``"department"`` / ``"private"``;
                defaults to the configured ``default_classification``.

        Returns:
            Relative path ``creative/{callsign}/{topic_slug}.md``.

        Emits ``CREATIVE_WORK_PUBLISHED`` with
        ``{author, skill_id, medium, path, classification}``.

        Raises:
            CreativeOutputError: if records_store unavailable or write fails.
        """
        records_store = self._resolve_records_store()
        cls = classification or self._config.default_classification
        rel_path = f"creative/{author_callsign}/{topic_slug}.md"
        try:
            await records_store.write_entry(
                author=author_callsign,
                path=rel_path,
                content=content,
                message=f"Creative work: {topic_slug} (medium={medium}; skill={skill_id})",
                classification=cls,
                status="published",
                department=department,
                topic=topic_slug,
                tags=["creative", medium, skill_id],
                metrics=None,
            )
        except Exception as exc:
            raise CreativeOutputError(
                f"failed to write creative work {rel_path}: {exc}"
            ) from exc

        if self._emit_event_fn is not None:
            try:
                self._emit_event_fn(
                    EventType.CREATIVE_WORK_PUBLISHED,
                    {
                        "author": author_callsign,
                        "skill_id": skill_id,
                        "medium": medium,
                        "path": rel_path,
                        "classification": cls,
                    },
                )
            except Exception:
                logger.debug(
                    "AD-525: failed to emit CREATIVE_WORK_PUBLISHED",
                    exc_info=True,
                )
        return rel_path

    async def list_works_by_author(self, author_callsign: str) -> list[str]:
        """Return relative paths of all creative works by an author.

        Walks ``creative/{author_callsign}/`` under the records repo. Returns
        an empty list if the directory does not exist or the records store
        is unavailable.
        """
        try:
            records_store = self._resolve_records_store()
        except CreativeOutputError:
            return []
        repo_path = getattr(records_store, "repo_path", None)
        if repo_path is None:
            return []
        author_dir = repo_path / "creative" / author_callsign
        if not author_dir.exists():
            return []
        paths: list[str] = []
        for entry in sorted(author_dir.glob("*.md")):
            paths.append(f"creative/{author_callsign}/{entry.name}")
        return paths
