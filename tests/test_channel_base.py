"""Tests for channel adapter base classes and response formatter."""

import asyncio
import copy
from typing import Any
from dataclasses import dataclass

import pytest

from probos.channels.base import (
    ChannelAdapter,
    ChannelConfig,
    ChannelMessage,
    PairingNotificationError,
)
from probos.utils.response_formatter import extract_response_text
from probos.cognitive.llm_client import MockLLMClient
from probos.config import SystemConfig
from probos.runtime import ProbOSRuntime
from probos.types import IntentResult


# ---------------------------------------------------------------------------
# TestExtractResponseText
# ---------------------------------------------------------------------------

class TestExtractResponseText:
    @pytest.mark.parametrize("field", ["metadata", "confidence"])
    def test_unsupported_metadata_never_invokes_metaclass_equality(self, field: str) -> None:
        class _EqualityGuard(type):
            def __eq__(self, other: object) -> bool:
                raise AssertionError("Equivalence must not invoke metaclass equality")

        class _Unsupported(metaclass=_EqualityGuard):
            pass

        changes = {field: {"unsupported": _Unsupported()} if field == "metadata" else _Unsupported()}
        assert self._format(
            self._record(**changes), self._record("b", **changes),
        ) == "391\n391"

    @staticmethod
    def _record(agent_id: str = "a", **changes: Any) -> Any:
        from datetime import datetime, timezone

        from probos.types import IntentResult

        fields = {
            "intent_id": "i", "agent_id": agent_id, "success": True,
            "result": "391", "error": None, "confidence": 0.9,
            "timestamp": datetime(2026, 9, 12, tzinfo=timezone.utc),
            "metadata": {},
        }
        fields.update(changes)
        return IntentResult(**fields)

    @staticmethod
    def _format(*records: Any) -> str:
        return extract_response_text({"results": {"node": {"results": list(records)}}})

    def test_none_result(self):
        assert extract_response_text(None) == "(Processing failed)"

    def test_direct_response(self):
        assert extract_response_text({"response": "Hello"}) == "Hello"

    def test_reflection_fallback(self):
        result = {"response": "", "reflection": "Based on the analysis..."}
        assert extract_response_text(result) == "Based on the analysis..."

    def test_correction_fallback(self):
        result = {"response": "", "correction": {"changes": "Fixed typo"}}
        assert extract_response_text(result) == "Fixed typo"

    def test_results_with_stdout(self):
        @dataclass
        class FakeResult:
            result: Any = None
            error: str | None = None

        result = {
            "response": "",
            "results": {
                "t1": {"results": [FakeResult(result={"stdout": "output text"})]}
            },
        }
        assert "output text" in extract_response_text(result)

    def test_results_with_string(self):
        @dataclass
        class FakeResult:
            result: Any = None
            error: str | None = None

        result = {
            "response": "",
            "results": {
                "t1": {"results": [FakeResult(result="file contents")]}
            },
        }
        assert "file contents" in extract_response_text(result)

    def test_results_with_error(self):
        @dataclass
        class FakeResult:
            result: Any = None
            error: str = "failed"

        result = {
            "response": "",
            "results": {
                "t1": {"results": [FakeResult()]}
            },
        }
        assert "Error: failed" in extract_response_text(result)

    def test_empty_result(self):
        result = {"response": "", "results": {}}
        text = extract_response_text(result)
        assert len(text) > 0  # Should return a fallback message

    @pytest.mark.parametrize("representation", ["dataclass", "dict", "mixed"])
    def test_equivalent_distinct_agents_preserve_evidence(self, representation: str) -> None:
        from copy import deepcopy
        from datetime import datetime, timedelta, timezone

        records = [self._record(), self._record("b")]
        records[1].timestamp = datetime(2026, 9, 13, tzinfo=timezone(timedelta(hours=2)))
        if representation == "dict":
            records = [dict(vars(record)) for record in records]
        elif representation == "mixed":
            records[1] = dict(vars(records[1]))
        if representation != "dataclass":
            records[1]["timestamp"] = "2026-09-13T12:00:00+02:00"
        envelope = {"results": {"node": {"results": records}}}
        snapshot = deepcopy(envelope)
        identities = [id(record) for record in records]

        assert len(records) == 2
        assert extract_response_text(envelope) == "391"
        assert extract_response_text(envelope) == "391"
        assert envelope == snapshot
        assert envelope["results"]["node"]["results"] is records
        assert [id(record) for record in records] == identities

    @pytest.mark.parametrize("agents,expected", [
        (["a", "b"], "391"),
        (["a", "a"], "391\n391"),
        (["a", "b", "a"], "391\n391\n391"),
        (["a", " a"], "391"),
    ])
    def test_agent_multiplicity(self, agents: list[str], expected: str) -> None:
        assert self._format(*(self._record(agent) for agent in agents)) == expected

    @pytest.mark.parametrize("repeat", [False, True])
    def test_interleaved_groups_keep_original_order(self, repeat: bool) -> None:
        records = [
            self._record(), self._record("c", result="392"),
            self._record("a" if repeat else "b"), self._record("d", result="392"),
        ]
        assert self._format(*records) == ("391\n392\n391" if repeat else "391\n392")

    @pytest.mark.parametrize("changes", [
        {"intent_id": "other"}, {"intent_id": " i"},
        {"confidence": 0.8}, {"metadata": {"source": "other"}},
        {"result": 391}, {"result": "392"},
    ])
    def test_differing_evidence_is_not_suppressed(self, changes: dict[str, Any]) -> None:
        first, second = self._record(), self._record("b", **changes)
        assert self._format(first, second) == f"{first.result}\n{second.result}"

    @pytest.mark.parametrize("field", ["result", "metadata", "confidence"])
    @pytest.mark.parametrize("left,right", [(True, 1), (1, 1.0), (0.0, -0.0)])
    def test_typed_scalar_differences(self, field: str, left: Any, right: Any) -> None:
        if field in ("result", "metadata"):
            left = {"stdout": "391", "hidden": left}
            right = {"stdout": "391", "hidden": right}
        first, second = self._record(**{field: left}), self._record("b", **{field: right})
        assert self._format(first, second) == "391\n391"

    @pytest.mark.parametrize("field", ["result", "metadata"])
    @pytest.mark.parametrize("left,right", [
        ([1, 2], (1, 2)), ([1, 2], [2, 1]),
        ({"first": 1, "second": 2}, {"second": 2, "first": 1}),
        ({"stderr": ""}, {"stderr": None}),
        ({"exit_code": 0}, {"exit_code": 1}),
        ({"source": "a"}, {"source": "b"}),
    ])
    def test_hidden_structure_differences(self, field: str, left: Any, right: Any) -> None:
        first = self._record(**{field: {"stdout": "391", "hidden": left}})
        second = self._record("b", **{field: {"stdout": "391", "hidden": right}})
        assert self._format(first, second) == "391\n391"

    @pytest.mark.parametrize("value", [None, False, 1, 1.0, -0.0, "", [], (), {}, [None, {"x": (True, 1)}]])
    def test_supported_hidden_values_can_match(self, value: Any) -> None:
        payload = {"stdout": "391", "hidden": value}
        assert self._format(self._record(result=payload), self._record("b", result=payload)) == "391"

    @pytest.mark.parametrize("changes", [
        {"success": False}, {"success": 1}, {"error": "failed"}, {"error": ""},
        {"agent_id": ""}, {"agent_id": " \t"}, {"agent_id": None},
        {"intent_id": ""}, {"intent_id": " \t"}, {"intent_id": 1},
        {"confidence": True}, {"confidence": None}, {"confidence": float("inf")},
        {"confidence": float("nan")}, {"metadata": None}, {"metadata": []},
        {"timestamp": None}, {"timestamp": 0}, {"timestamp": "invalid"},
        {"timestamp": "2026-09-12"}, {"timestamp": "2026-09-12T12:00:00"},
    ])
    def test_late_ineligible_record_preserves_whole_node(self, changes: dict[str, Any]) -> None:
        late = self._record(**changes)
        assert self._format(self._record(), self._record("b"), late) == "391\n391\n391"

    @pytest.mark.parametrize("kind", ["missing", "extra", "attribute", "dict-subclass", "record-subclass", "duck", "key-subclass"])
    def test_nonexact_records_preserve_whole_node(self, kind: str) -> None:
        from types import SimpleNamespace

        from probos.types import IntentResult

        class RecordSubclass(IntentResult):
            pass

        class DictSubclass(dict):
            pass

        class StringSubclass(str):
            pass

        late = self._record("c")
        fields = dict(vars(late))
        if kind == "missing":
            fields.pop("metadata")
            late = fields
        elif kind == "extra":
            late = {**fields, "extra": None}
        elif kind == "attribute":
            late.extra = None
        elif kind == "dict-subclass":
            late = DictSubclass(fields)
        elif kind == "record-subclass":
            late = RecordSubclass(**fields)
        elif kind == "duck":
            late = SimpleNamespace(**fields)
        else:
            late = {StringSubclass(key): value for key, value in fields.items()}
        assert self._format(self._record(), self._record("b"), late) == "391\n391\n391"

    @pytest.mark.parametrize("kind", ["naive", "datetime-subclass", "custom-tz", "string-subclass"])
    def test_timestamp_types_are_conservative(self, kind: str) -> None:
        from datetime import datetime, timedelta, timezone, tzinfo

        class DatetimeSubclass(datetime):
            pass

        class StringSubclass(str):
            pass

        class CustomTimezone(tzinfo):
            def utcoffset(self, value: Any) -> timedelta:
                return timedelta(0)

        timestamp = {
            "naive": datetime(2026, 9, 12),
            "datetime-subclass": DatetimeSubclass(2026, 9, 12, tzinfo=timezone.utc),
            "custom-tz": datetime(2026, 9, 12, tzinfo=CustomTimezone()),
            "string-subclass": StringSubclass("2026-09-12T00:00:00Z"),
        }[kind]
        assert self._format(self._record(), self._record("b", timestamp=timestamp)) == "391\n391"

    @pytest.mark.parametrize("field", ["result", "metadata"])
    @pytest.mark.parametrize("kind", ["cycle", "nan", "inf", "set", "bytes", "object", "list-subclass", "int-subclass", "nonstring-key"])
    def test_unsupported_nested_values_preserve_whole_node(self, field: str, kind: str) -> None:
        class ListSubclass(list):
            pass

        class IntSubclass(int):
            pass

        cycle: list[Any] = []
        cycle.append(cycle)
        value = {
            "cycle": cycle, "nan": float("nan"), "inf": float("-inf"),
            "set": {1}, "bytes": b"391", "object": object(),
            "list-subclass": ListSubclass([1]), "int-subclass": IntSubclass(1),
            "nonstring-key": {1: "value"},
        }[kind]
        late = self._record("c", **{field: {"stdout": "391", "hidden": value}})
        assert self._format(self._record(), self._record("b"), late) == "391\n391\n391"

    @pytest.mark.parametrize("representation", ["dataclass", "dict"])
    @pytest.mark.parametrize("value", [None, "", False, 0, [], {}])
    def test_empty_payload_preserves_legacy_rendering(self, representation: str, value: Any) -> None:
        late = self._record("c", result=value)
        if representation == "dict":
            late = dict(vars(late))
        expected = "391\n391"
        if representation == "dataclass" and value is not None:
            rendered = str(value)
            expected = "391\n" + rendered if rendered else expected + "\n"
        assert self._format(self._record(), self._record("b"), late) == expected

    @pytest.mark.parametrize("budget", ["depth", "values", "string", "characters", "integer"])
    @pytest.mark.parametrize("exceeded", [False, True])
    def test_equivalence_budget_boundaries(self, budget: str, exceeded: bool) -> None:
        if budget == "depth":
            hidden: Any = None
            for _ in range(31 + int(exceeded)):
                hidden = [hidden]
        elif budget == "values":
            hidden = [None] * (2026 + int(exceeded))
        elif budget == "string":
            hidden = "x" * (65536 + int(exceeded))
        elif budget == "characters":
            hidden = ["x" * 65536] * 7 + ["x" * (65454 + int(exceeded))]
        else:
            hidden = 1 << (4095 + int(exceeded))
        payload = {"stdout": "391", "hidden": hidden}
        first, second = self._record(result=payload), self._record("b", result=payload)
        assert first.result is second.result
        assert self._format(first, second) == ("391\n391" if exceeded else "391")
        assert first.result is payload and second.result is payload

    def test_existing_rendered_text_must_also_match(self) -> None:
        first = self._record(result={"stdout": "391"})
        second = dict(vars(self._record("b", result={"stdout": "391"})))
        assert self._format(first, second) == "391\n{'stdout': '391'}"

    def test_stdout_stderr_rendering_is_unchanged(self) -> None:
        payload = {"stdout": "391", "stderr": "warning", "exit_code": 0}
        assert self._format(self._record(result=payload), self._record("b", result=payload)) == "391\nwarning"

    def test_unsupported_payload_is_stringified_only_once(self) -> None:
        class RenderOnce:
            def __init__(self) -> None:
                self.calls = 0

            def __str__(self) -> str:
                self.calls += 1
                assert self.calls == 1
                return "391"

        first, second = RenderOnce(), RenderOnce()
        assert self._format(self._record(result=first), self._record("b", result=second)) == "391\n391"
        assert first.calls == second.calls == 1

    def test_independent_nodes_and_invocations_are_not_suppressed(self) -> None:
        records = [self._record(), self._record("b")]
        envelope = {"results": {"first": {"results": records}, "second": {"results": records}}}
        assert extract_response_text(envelope) == "391\n391"
        assert extract_response_text(envelope) == "391\n391"

    @pytest.mark.parametrize("overrides,expected", [
        ({"response": "direct", "reflection": "reflection", "correction": {"changes": "fixed"}}, "direct"),
        ({"response": "", "reflection": "reflection", "correction": {"changes": "fixed"}}, "reflection"),
        ({"reflection": "", "correction": {"changes": "fixed"}}, "fixed"),
        ({"correction": {"other": True}}, "Correction applied"),
        ({"correction": {"changes": ""}}, "391"),
    ])
    def test_precedence_over_equivalence(self, overrides: dict[str, Any], expected: str) -> None:
        envelope = {"results": {"node": {"results": [self._record(), self._record("b")]}}}
        envelope.update(overrides)
        assert extract_response_text(envelope) == expected

    def test_legacy_node_rendering_and_fallbacks(self) -> None:
        envelope = {"results": {
            "error": {"error": "failed", "results": [self._record(), self._record("b")]},
            "output": {"output": "output"}, "text": "text",
            "legacy": {"results": [{"output": "same"}, {"text": "same"}]},
        }}
        assert extract_response_text(envelope) == "Error: failed\noutput\ntext\nsame\nsame"
        assert extract_response_text({}) == "(Processing failed)"
        assert extract_response_text({"results": {"node": {"results": []}}}) == "(Empty response)"


# ---------------------------------------------------------------------------
# TestChannelMessage
# ---------------------------------------------------------------------------

class TestChannelMessage:
    def test_construction(self):
        msg = ChannelMessage(
            text="hello",
            channel_id="123",
            user_id="456",
            user_display_name="Alice",
            reply_to_message_id="789",
        )
        assert msg.text == "hello"
        assert msg.channel_id == "123"
        assert msg.user_id == "456"
        assert msg.user_display_name == "Alice"
        assert msg.reply_to_message_id == "789"

    def test_defaults(self):
        msg = ChannelMessage(text="hi", channel_id="c1", user_id="u1")
        assert msg.user_display_name == ""
        assert msg.reply_to_message_id is None


# ---------------------------------------------------------------------------
# TestChannelAdapterHandleMessage
# ---------------------------------------------------------------------------

class _FakeAdapter(ChannelAdapter):
    """Minimal concrete adapter for testing the base class handle_message."""

    def __init__(self, runtime: ProbOSRuntime) -> None:
        super().__init__(runtime, ChannelConfig(enabled=True))
        self.sent: list[tuple[str, str]] = []

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False

    async def send_response(
        self, channel_id: str, response: str, **kwargs: Any
    ) -> None:
        self.sent.append((channel_id, response))


@pytest.fixture
async def runtime(tmp_path):
    config = SystemConfig()
    config.qa.enabled = False
    llm = MockLLMClient()
    rt = ProbOSRuntime(config=config, data_dir=tmp_path / "data", llm_client=llm)
    await rt.start()
    yield rt
    await rt.stop()


class TestChannelAdapterHandleMessage:
    @pytest.mark.asyncio
    async def test_slash_command(self, runtime):
        adapter = _FakeAdapter(runtime)
        msg = ChannelMessage(text="/status", channel_id="ch1", user_id="u1")
        result = await adapter.handle_message(msg)
        assert isinstance(result, str)
        assert len(result) > 0  # slash commands return something

    @pytest.mark.asyncio
    async def test_natural_language(self, runtime):
        adapter = _FakeAdapter(runtime)
        msg = ChannelMessage(
            text="read the file at /tmp/test.txt",
            channel_id="ch1",
            user_id="u1",
        )
        result = await adapter.handle_message(msg)
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_conversation_history(self, runtime):
        adapter = _FakeAdapter(runtime)
        # Send two messages to the same channel
        msg1 = ChannelMessage(text="hello world", channel_id="ch1", user_id="u1")
        await adapter.handle_message(msg1)
        msg2 = ChannelMessage(text="hello again", channel_id="ch1", user_id="u1")
        await adapter.handle_message(msg2)
        # History should have 4 entries (2 user + 2 assistant)
        history = adapter._conversation_histories.get("ch1", [])
        assert len(history) == 4
        assert history[0][0] == "user"
        assert history[1][0] == "assistant"
        assert history[2][0] == "user"
        assert history[3][0] == "assistant"

    @pytest.mark.asyncio
    async def test_history_trimming(self, runtime):
        adapter = _FakeAdapter(runtime)
        adapter._max_history = 5
        # Send 12 messages → expect trimming to max_history * 2 = 10
        for i in range(12):
            msg = ChannelMessage(
                text=f"message {i}",
                channel_id="ch1",
                user_id="u1",
            )
            await adapter.handle_message(msg)
        history = adapter._conversation_histories.get("ch1", [])
        assert len(history) <= adapter._max_history * 2


# ---------------------------------------------------------------------------
# BF-804: the pairing gate must not swallow a failed notification
# ---------------------------------------------------------------------------


class TestChannelResultPresentation:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("different_metadata", [False, True])
    async def test_channel_retains_evidence_and_each_independent_message(
        self, different_metadata: bool,
    ) -> None:
        from probos.channels import extract_response_text as exported_formatter

        assert exported_formatter is extract_response_text
        contributors = [
            IntentResult(
                intent_id="calculation", agent_id="calculator-first", success=True,
                result="391", confidence=0.9,
            ),
            IntentResult(
                intent_id="calculation", agent_id="calculator-second", success=True,
                result="391", confidence=0.9,
                metadata={"verification": "pending"} if different_metadata else {},
            ),
        ]
        result = {"results": {"node": {"results": contributors, "result_count": 2}}}
        original = copy.deepcopy(result)
        histories: list[list[tuple[str, str]]] = []

        class _ResultRuntime:
            async def process_natural_language(
                self, text: str, *, auto_selfmod: bool,
                conversation_history: list[tuple[str, str]],
            ) -> dict[str, Any]:
                assert text == "calculate"
                assert auto_selfmod is False
                histories.append(list(conversation_history))
                return result

        adapter = _FakeAdapter(_ResultRuntime())
        expected = "391\n391" if different_metadata else "391"
        for occurrence in range(3):
            message = ChannelMessage(text="calculate", channel_id="results", user_id="test-user")
            response = await adapter.handle_message(message)
            assert response == expected
            await adapter.send_response(message.channel_id, response)
            assert histories[occurrence] == [("user", "calculate"), ("assistant", expected)] * occurrence
        assert adapter.sent == [("results", expected)] * 3
        assert result == original
        assert result["results"]["node"]["results"] is contributors


class _PairingRuntime:
    """Only the member `_check_pairing` reads."""

    def __init__(self, pairing_service: Any) -> None:
        self.pairing_service = pairing_service


class _PairingService:
    """`resolve_did` answers None, so every sender takes the notify path."""

    def __init__(self, *, request_error: Exception | None = None) -> None:
        self.request_error = request_error
        self.requested: list[tuple[str, str]] = []

    def resolve_did(self, channel: str, raw_id: str) -> str | None:
        return None

    async def request_pairing(self, *, channel: str, raw_id: str) -> str:
        self.requested.append((channel, raw_id))
        if self.request_error is not None:
            raise self.request_error
        return "ABC123"


class _GatedAdapter(ChannelAdapter):
    """A concrete adapter that sets `channel_name`, so AD-802a really fires."""

    channel_name = "fake"

    def __init__(
        self, runtime: Any, *, send_error: Exception | None = None
    ) -> None:
        super().__init__(runtime, ChannelConfig(enabled=True))
        self.send_error = send_error
        self.sent: list[tuple[str, str]] = []

    async def start(self) -> None:
        self._started = True

    async def stop(self) -> None:
        self._started = False

    async def send_response(
        self, channel_id: str, response: str, **kwargs: Any
    ) -> None:
        if self.send_error is not None:
            raise self.send_error
        self.sent.append((channel_id, response))


class TestPairingNotificationFailure:
    """BF-804 (#1350): both non-delivery paths propagate instead of returning
    False, because a bool cannot tell the caller "instructions delivered" from
    "instructions lost".

    These pin the RAISE, one test per path. They are supporting evidence only:
    the consequence that actually discriminates -- Gmail declining to
    acknowledge, so the mail is re-fetched -- lives in
    tests/test_bf804_pairing_notification.py.
    """

    @pytest.mark.asyncio
    async def test_request_pairing_failure_raises(self):
        service = _PairingService(request_error=RuntimeError("store is down"))
        adapter = _GatedAdapter(_PairingRuntime(service))
        msg = ChannelMessage(text="hi", channel_id="c1", user_id="u1")

        with pytest.raises(PairingNotificationError) as caught:
            await adapter._check_pairing(msg)

        assert service.requested == [("fake", "u1")], "control: the mint ran"
        assert adapter.sent == [], "no instructions can exist without a code"
        assert isinstance(caught.value.__cause__, RuntimeError)
        assert "u1" not in str(caught.value)

    @pytest.mark.asyncio
    async def test_instruction_send_failure_raises(self):
        service = _PairingService()
        adapter = _GatedAdapter(
            _PairingRuntime(service), send_error=RuntimeError("transport down")
        )
        msg = ChannelMessage(text="hi", channel_id="c1", user_id="u1")

        with pytest.raises(PairingNotificationError) as caught:
            await adapter._check_pairing(msg)

        assert service.requested == [("fake", "u1")], "control: a code was minted"
        assert isinstance(caught.value.__cause__, RuntimeError)
        assert "u1" not in str(caught.value)

    @pytest.mark.asyncio
    async def test_a_delivered_notice_still_returns_false(self):
        """Outcome 2 stays a clean drop -- the fix must not make every
        unpaired message retry forever."""
        service = _PairingService()
        adapter = _GatedAdapter(_PairingRuntime(service))
        msg = ChannelMessage(text="hi", channel_id="c1", user_id="u1")

        assert await adapter._check_pairing(msg) is False
        assert len(adapter.sent) == 1
        assert "probos pairing approve fake ABC123" in adapter.sent[0][1]

    @pytest.mark.asyncio
    async def test_handle_message_propagates_rather_than_returning_empty(self):
        """The seam the Gmail consumer reads: `handle_message` must not map a
        lost notification onto the same "" it returns for a delivered one."""
        service = _PairingService()
        adapter = _GatedAdapter(
            _PairingRuntime(service), send_error=RuntimeError("transport down")
        )
        msg = ChannelMessage(text="hi", channel_id="c1", user_id="u1")

        with pytest.raises(PairingNotificationError):
            await adapter.handle_message(msg)

        delivered = _GatedAdapter(_PairingRuntime(_PairingService()))
        assert await delivered.handle_message(msg) == "", (
            "control: a DELIVERED notice still returns the empty string"
        )
