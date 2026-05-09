"""AD-721d D10: ``CognitiveAgent.propose_appearance`` boundary + safety tests.

Mocks the LLM client. NO actual LLM call is made. The renderer (AD-721i) is
not exercised here either — AD-721d is a pure runtime/persistence/UI prompt.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.avatars.dsl import AppearanceProposalError, AvatarDSL
from probos.cognitive.cognitive_agent import CognitiveAgent
from probos.types import LLMResponse


def _good_dsl_dict() -> dict:
    return {
        "body": {"type": "average", "height_cm": 170},
        "hair": {"style": "medium", "color_hsl": [30, 40, 30]},
        "face": {"warmth": 0.5, "jaw": "neutral", "eyes": "almond"},
        "outfit": {"style": "uniform", "primary_color": "#2a4a6a", "accents": []},
        "expression_resting": "neutral",
        "notes": "",
    }


class _MinimalAgent(CognitiveAgent):
    """Subclass that bypasses the heavy CognitiveAgent constructor.

    AD-721d's propose_appearance() reads only:
      - self._llm_client
      - self.id
      - self.agent_type
      - self.instructions
      - self._runtime  (optional)
      - self._resolve_tier() (optional)
    """

    def __init__(self, *, llm_client: object, runtime: object = None,
                 instructions: str = "test agent", agent_type: str = "test",
                 agent_id: str = "agent-test") -> None:
        # Skip BaseAgent.__init__ entirely — the boundary test exercises only
        # the appearance-proposal slice.
        self._llm_client = llm_client
        self._runtime = runtime
        self.instructions = instructions
        self.agent_type = agent_type
        self.id = agent_id

    def _resolve_tier(self) -> str:
        return "standard"


def _agent_with_llm_response(content: str) -> _MinimalAgent:
    client = MagicMock()
    client.complete = AsyncMock(return_value=LLMResponse(content=content))
    return _MinimalAgent(llm_client=client)


@pytest.mark.asyncio
async def test_happy_path_returns_validated_dsl() -> None:
    text = json.dumps(_good_dsl_dict())
    agent = _agent_with_llm_response(text)
    dsl = await agent.propose_appearance()
    assert isinstance(dsl, AvatarDSL)
    assert dsl.body.type == "average"


@pytest.mark.asyncio
async def test_happy_path_with_markdown_fence() -> None:
    """The model often wraps JSON in ```json fences; we strip them."""
    text = "```json\n" + json.dumps(_good_dsl_dict()) + "\n```"
    agent = _agent_with_llm_response(text)
    dsl = await agent.propose_appearance()
    assert isinstance(dsl, AvatarDSL)


@pytest.mark.asyncio
async def test_oversized_response_raises() -> None:
    payload = "x" * (16 * 1024 + 1)
    agent = _agent_with_llm_response(payload)
    with pytest.raises(AppearanceProposalError) as exc_info:
        await agent.propose_appearance()
    assert exc_info.value.reason == "response_oversized"


@pytest.mark.asyncio
async def test_yaml_anchor_rejected() -> None:
    text = "{\"body\": &anchor {\"type\": \"average\", \"height_cm\": 170}}"
    agent = _agent_with_llm_response(text)
    with pytest.raises(AppearanceProposalError) as exc_info:
        await agent.propose_appearance()
    assert exc_info.value.reason == "yaml_anchor_or_alias"


@pytest.mark.asyncio
async def test_yaml_alias_rejected() -> None:
    text = "body: *anchor"
    agent = _agent_with_llm_response(text)
    with pytest.raises(AppearanceProposalError) as exc_info:
        await agent.propose_appearance()
    assert exc_info.value.reason == "yaml_anchor_or_alias"


@pytest.mark.asyncio
async def test_deep_nesting_rejected() -> None:
    """9-level nested dict rejected by the depth guard."""
    deep: dict = {}
    cur = deep
    for _ in range(15):
        cur["nested"] = {}
        cur = cur["nested"]
    text = json.dumps(deep)
    agent = _agent_with_llm_response(text)
    with pytest.raises(AppearanceProposalError) as exc_info:
        await agent.propose_appearance()
    assert exc_info.value.reason == "depth_exceeded"


@pytest.mark.asyncio
async def test_schema_violation_propagates() -> None:
    bad = _good_dsl_dict()
    bad["body"]["type"] = "alien"
    text = json.dumps(bad)
    agent = _agent_with_llm_response(text)
    with pytest.raises(AppearanceProposalError) as exc_info:
        await agent.propose_appearance()
    assert exc_info.value.reason == "schema_violation"


@pytest.mark.asyncio
async def test_parse_error_for_non_json() -> None:
    agent = _agent_with_llm_response("not valid json: [unclosed")
    with pytest.raises(AppearanceProposalError) as exc_info:
        await agent.propose_appearance()
    # Either parse_error (yaml.safe_load fails) or yaml_anchor_or_alias
    # (depending on token contents). Both are valid hardened-rejection paths;
    # the safety contract is "no DSL leaks through".
    assert exc_info.value.reason in {"parse_error", "yaml_anchor_or_alias"}


@pytest.mark.asyncio
async def test_top_level_must_be_object() -> None:
    """A bare list at the top level is rejected at parse-stage validation."""
    agent = _agent_with_llm_response(json.dumps([1, 2, 3]))
    with pytest.raises(AppearanceProposalError) as exc_info:
        await agent.propose_appearance()
    assert exc_info.value.reason == "parse_error"


@pytest.mark.asyncio
async def test_llm_call_failure_log_and_typed_error() -> None:
    client = MagicMock()
    client.complete = AsyncMock(side_effect=RuntimeError("upstream 503"))
    agent = _MinimalAgent(llm_client=client)
    with pytest.raises(AppearanceProposalError) as exc_info:
        await agent.propose_appearance()
    assert exc_info.value.reason == "llm_call_failed"
    assert "upstream 503" in exc_info.value.detail


@pytest.mark.asyncio
async def test_no_llm_client_raises_typed_error() -> None:
    agent = _MinimalAgent(llm_client=None)
    with pytest.raises(AppearanceProposalError) as exc_info:
        await agent.propose_appearance()
    assert exc_info.value.reason == "llm_unavailable"


@pytest.mark.asyncio
async def test_oversized_captain_note_rejected_before_llm_call() -> None:
    client = MagicMock()
    client.complete = AsyncMock()
    agent = _MinimalAgent(llm_client=client)
    with pytest.raises(AppearanceProposalError) as exc_info:
        await agent.propose_appearance(captain_note="x" * 281)
    assert exc_info.value.reason == "invalid_input"
    client.complete.assert_not_awaited()


def test_no_eval_or_exec_in_cognitive_agent_appearance_path() -> None:
    """Defense-in-depth: AST scan of cognitive_agent.py asserts no eval/exec/compile
    in any function in the module. (Coarser scan; if a future regression adds
    such a call to the appearance path, this fires.)
    """
    src = Path(__file__).resolve().parents[1] / "src" / "probos" / "cognitive" / "cognitive_agent.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    forbidden = {"eval", "exec", "compile"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in forbidden, (
                f"Forbidden function call {node.func.id!r} in cognitive_agent.py"
            )
