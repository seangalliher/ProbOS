"""Codebase knowledge skill — wraps CodebaseIndex for CognitiveAgent use (AD-290)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from probos.types import IntentDescriptor, IntentMessage, IntentResult, Skill

if TYPE_CHECKING:
    from probos.cognitive.codebase_index import CodebaseIndex


_DESCRIPTOR = IntentDescriptor(
    name="codebase_knowledge",
    params={
        "action": "query|read_source|get_agent_map|get_layer_map|get_config_schema|get_api_surface",
        "query": "keyword to search (for action=query)",
        "file_path": "relative file path (for action=read_source)",
        "start_line": "optional start line (for action=read_source)",
        "end_line": "optional end line (for action=read_source)",
        "class_name": "class name (for action=get_api_surface)",
    },
    description="Query ProbOS's own source code architecture, agent registry, configuration, and API surface",
)


def create_codebase_skill(index: CodebaseIndex) -> Skill:
    """Create a Skill wrapping the CodebaseIndex for use by CognitiveAgents."""

    async def handler(intent: IntentMessage, **kwargs: Any) -> IntentResult:
        params = intent.params or {}
        action = params.get("action", "query")

        try:
            if action == "query":
                result = index.query(params.get("query", ""))
            elif action == "read_source":
                start = params.get("start_line")
                end = params.get("end_line")
                result = index.read_source(
                    params.get("file_path", ""),
                    start_line=int(start) if start else None,
                    end_line=int(end) if end else None,
                )
            elif action == "get_agent_map":
                result = index.get_agent_map()
            elif action == "get_layer_map":
                result = index.get_layer_map()
            elif action == "get_config_schema":
                result = index.get_config_schema()
            elif action == "get_api_surface":
                result = index.get_api_surface(params.get("class_name", ""))
            else:
                return IntentResult(
                    intent_id=intent.id,
                    agent_id="codebase_knowledge",
                    success=False,
                    error=f"Unknown action: {action}",
                )

            return IntentResult(
                intent_id=intent.id,
                agent_id="codebase_knowledge",
                success=True,
                result=result,
            )
        except Exception as e:
            return IntentResult(
                intent_id=intent.id,
                agent_id="codebase_knowledge",
                success=False,
                error=str(e),
            )

    return Skill(
        name="codebase_knowledge",
        descriptor=_DESCRIPTOR,
        source_code="",  # Built-in, no user-supplied code
        handler=handler,
        origin="builtin",
    )
