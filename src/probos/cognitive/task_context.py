"""AD-586: Task-contextual standing orders."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from probos.config import TaskContextConfig

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

_INTENT_TASK_MAP: dict[str, str] = {
    "build_code": "build",
    "build_queue_item": "build",
    "code_review": "review",
    "self_mod": "build",
    "design": "build",
    "analyze_code": "analyze",
    "analyze_metrics": "analyze",
    "proactive_think": "analyze",
    "ward_room_notification": "communicate",
    "direct_message": "communicate",
    "diagnose": "diagnose",
    "vitals_check": "diagnose",
    "smoke_test": "diagnose",
}


class TaskContext:
    """Classify intents and render task-specific standing orders."""

    def __init__(
        self,
        config: "TaskContextConfig",
        orders_dir: Path | None = None,
    ) -> None:
        self._config = config
        if orders_dir is not None:
            self._orders_dir = orders_dir
        else:
            configured = Path(config.orders_dir)
            self._orders_dir = configured if configured.is_absolute() else _PROJECT_ROOT / configured

    def classify_task(self, intent_name: str) -> str:
        """Classify an intent name into a task type."""
        return _INTENT_TASK_MAP.get(intent_name, "general")

    def get_task_orders(self, task_type: str) -> str:
        """Load task-specific standing orders for a task type."""
        if not self._config.enabled:
            return ""
        path = self._orders_dir / f"{task_type}.md"
        if not path.exists():
            if task_type != "general":
                logger.warning(
                    "AD-586: Task order file %s missing for task_type=%s; continuing without task-specific orders",
                    path,
                    task_type,
                )
            return ""
        try:
            return path.read_text(encoding="utf-8").strip()[: self._config.max_tokens]
        except OSError:
            logger.warning(
                "AD-586: Failed to read task order file %s; continuing without task-specific orders",
                path,
                exc_info=True,
            )
            return ""

    def render_task_context(self, task_type: str) -> str:
        """Render task-contextual standing orders for prompt composition."""
        if task_type == "general":
            return ""
        orders_content = self.get_task_orders(task_type)
        if not orders_content:
            return ""
        return f"## Task Context ({task_type})\n{orders_content}"