"""AD-1171: the flight recorder can be read.

Every agentic run has persisted a complete tool trace since AD-1151. Nothing
ever read one back. Reading a single trace by hand gave the root cause of BF-701
in about thirty seconds, after three sessions of inference from the agent's own
prose — so the fixture below is that real trace, trimmed.
"""

from __future__ import annotations

import json

import pytest

from probos.cognitive.swe_harness.agentic_loop import TOOL_TRACE_OUTPUT_MAX_CHARS
from probos.cognitive.trace_analysis import (
    REPEAT_THRESHOLD,
    TraceSummary,
    _ARGS_PER_CALL_MAX,
    analyse_trace,
    load_trace,
    summarise_trace_ref,
)


def _entry(name: str, args: dict, output: str = "", is_error: bool | None = None):
    entry: dict = {
        "name": name, "arguments": args, "id": f"c{abs(hash(str(args))) % 9999}",
        "timestamp": 1.0,
    }
    if is_error is not None:
        entry["output"] = output
        entry["is_error"] = is_error
        entry["output_chars"] = len(output)
        entry["output_truncated"] = False
    return entry


# The real BF-701 run, trimmed to its shape: reach the target, be refused the
# verb for using it, then flail.
_BF701_TRACE = [
    _entry("browser", {"action": "state"}, "{'elements': [...]}", False),
    _entry("browser", {"action": "click", "index": 90}, "{'url': '...'}", False),
    _entry("browser", {"action": "key_type", "text": "Hello"},
           "unknown browser action: 'key_type'", True),
    _entry("browser", {"action": "type", "text": "Hello"},
           "click/type requires 'index' or 'selector'", True),
    _entry("browser", {"action": "click", "selector": "canvas"},
           "Page.click: Timeout 30000ms exceeded.", True),
    _entry("browser", {"action": "key_type", "text": "Hello", "delay_ms": 80},
           "unknown browser action: 'key_type'", True),
]


# ── the headline ──────────────────────────────────────────────────


def test_the_real_bf701_trace_names_its_own_root_cause() -> None:
    """THE AD-1171 regression.

    The agent said "the document is canvas-based". The trace says the browser
    tool refused `key_type` twice. The trace is right.
    """
    summary = analyse_trace(_BF701_TRACE)

    primary = summary.primary_failure
    assert primary is not None
    assert primary.tool_id == "browser"
    assert "key_type" in primary.error_text
    assert primary.count == 2
    assert primary.first_index == 2
    assert primary.last_index == 5


def test_the_summary_reads_as_a_finding_not_statistics() -> None:
    rendered = analyse_trace(_BF701_TRACE).render()
    assert "browser" in rendered
    assert "key_type" in rendered
    assert "2 times" in rendered
    # The finding leads; the counts follow.
    assert rendered.index("key_type") < rendered.index("tool calls")


def test_it_finds_where_progress_stopped() -> None:
    """Everything after the last success is an agent working around something
    rather than with it."""
    summary = analyse_trace(_BF701_TRACE)
    assert summary.last_success_index == 1
    assert summary.trailing_failure_count == 4
    assert summary.stalled is True


def test_counts_and_tools() -> None:
    summary = analyse_trace(_BF701_TRACE)
    assert summary.total_calls == 6
    assert summary.failed_calls == 4
    assert summary.tools_used == ("browser",)


# ── BF-774: a run that succeeded at the wrong target ──────────────

# The real 2026-08-14 run, trace 62ba19df85eda7d5. The Captain asked Ezri to
# verify a claim against "the actual deepagents repository". She queried
# langchain-ai/langchain instead, got a correct answer about the WRONG
# repository, and reported it as verified. Both calls succeeded, so every
# failure field is empty and the pre-BF-774 summary read "2 tool calls, 0
# failed, across 2 tool(s)" -- true, and useless. The argument was the finding.
_BF774_TRACE = [
    _entry(
        "mcp_deepwiki_ask_question",
        {"repoName": "langchain-ai/langchain",
         "question": "What middleware and tools does LangChain Deep Agents "
                     "ship? Does it include a TodoListMiddleware for task "
                     "planning?"},
        "{'content': [...]}", False,
    ),
    _entry(
        "web_search",
        {"query": "LangChain deep agents TodoListMiddleware middleware repository"},
        "## LangChain Deep Agents ...", False,
    ),
]


def test_the_real_bf774_trace_shows_the_repository_it_actually_asked() -> None:
    """THE BF-774 regression.

    Nothing failed, so the failure analysis is silent by design. The summary
    still has to make the mis-aimed argument legible, because that is the only
    place the defect exists.
    """
    summary = analyse_trace(_BF774_TRACE)

    assert summary.failed_calls == 0
    assert summary.primary_failure is None
    assert 'repoName="langchain-ai/langchain"' in summary.requests[0]
    assert "langchain-ai/langchain" in summary.render()


def test_the_arguments_survive_into_the_rendered_summary() -> None:
    rendered = analyse_trace(_BF774_TRACE).render()
    assert "What it asked:" in rendered
    assert "mcp_deepwiki_ask_question(" in rendered
    assert "web_search(" in rendered


def test_a_long_argument_is_clipped_not_dumped() -> None:
    # `question` is whole prose and model-written; a summary needs the
    # identifier that was targeted, not the essay.
    summary = analyse_trace(_BF774_TRACE)
    assert len(summary.requests[0]) < 260
    assert "\u2026" in summary.requests[0]


def test_requests_keep_call_order_and_repetition() -> None:
    # Asking the same thing twice is signal, so repeats are not collapsed.
    summary = analyse_trace([
        _entry("t", {"q": "a"}, "ok", False),
        _entry("t", {"q": "b"}, "ok", False),
        _entry("t", {"q": "a"}, "ok", False),
    ])
    assert summary.requests == ('t(q="a")', 't(q="b")', 't(q="a")')


def test_a_nested_argument_is_named_by_shape_not_dumped() -> None:
    # Arguments are unbounded model-written input on this path.
    summary = analyse_trace([
        _entry("t", {"payload": {"a": [1, 2, 3]}, "items": [1, 2], "n": 3,
                     "flag": True, "nothing": None, "zero": 0}, "ok", False),
    ])
    rendered = summary.requests[0]
    assert "payload=<dict>" in rendered
    assert "items=<list>" in rendered
    assert "n=3" in rendered
    assert "flag=True" in rendered
    assert "nothing=None" in rendered
    # 0 is falsey, and a renderer that leans on truthiness silently loses it.
    assert "zero=0" in rendered


def test_numeric_arguments_keep_their_own_representation() -> None:
    # A float is not a nested structure and must not be shape-named; and the
    # sign of a zero is a real distinction that truthiness erases.
    summary = analyse_trace([
        _entry("t", {"a": 1.5, "b": -0.0, "c": 0.0, "d": False}, "ok", False),
    ])
    rendered = summary.requests[0]
    assert "a=1.5" in rendered
    assert "b=-0.0" in rendered
    assert "c=0.0" in rendered
    assert "d=False" in rendered
    assert "<float>" not in rendered


def test_too_many_arguments_are_bounded() -> None:
    args = {f"k{i}": f"v{i}" for i in range(20)}
    summary = analyse_trace([_entry("t", args, "ok", False)])
    assert summary.requests[0].count("=") <= 7   # 6 args + the ellipsis marker
    assert "\u2026" in summary.requests[0]
    # Bounding must still SHOW the first arguments; a renderer that returned
    # only the marker would satisfy the bound and lose the finding.
    assert 'k0="v0"' in summary.requests[0]
    assert 'k5="v5"' in summary.requests[0]


def test_the_request_list_itself_is_bounded() -> None:
    entries = [_entry("t", {"i": i}, "ok", False) for i in range(120)]
    summary = analyse_trace(entries)
    assert summary.total_calls == 120
    assert len(summary.requests) == 40
    assert summary.requests_total == 120
    # The count must be honest about the calls, not about the truncated list:
    # "and 34 more" would understate what is hidden by 80 calls.
    assert "and 114 more" in summary.render()


def test_a_huge_integer_argument_does_not_raise() -> None:
    # CPython refuses str() on an int past its digit limit, and `arguments` is
    # model-written. analyse_trace's contract is that it never raises.
    # Built without `_entry`, which stringifies args for its id and so trips
    # the same limit before the production code is ever reached.
    summary = analyse_trace([
        {"name": "t", "arguments": {"n": 10 ** 6000}, "id": "c1",
         "timestamp": 1.0, "output": "ok", "is_error": False},
    ])
    assert summary.total_calls == 1
    assert summary.requests[0].startswith("t(n=")
    summary.render()


def test_an_unpaired_surrogate_survives_json_encoding() -> None:
    # A lone surrogate is an encoding error, not a character. Two earlier
    # versions of this test were vacuous: bare `json.dumps` defaults to
    # ensure_ascii=True and escapes the surrogate to ASCII before any encode
    # can fail. FastAPI's JSONResponse uses ensure_ascii=False, so that is the
    # call this has to make to reach the failure it claims to guard.
    summary = analyse_trace([_entry("t", {"q": "before\ud800after"}, "ok", False)])
    payload = {"requests": list(summary.requests), "render": summary.render()}
    json.dumps(payload, ensure_ascii=False).encode("utf-8")
    assert "before" in summary.requests[0]


def test_a_quote_in_a_value_cannot_fake_an_argument_boundary() -> None:
    # Otherwise `repoName="a", repoName="b"` renders as two arguments and the
    # evidence for which target was really asked becomes ambiguous. The value
    # may still CONTAIN that text -- what it must not do is close the quote.
    # The guarantee is reversibility, so assert exactly that: the rendered
    # value parses back to what was asked, and nothing else.
    hostile = 'wrong/repo", repoName="right/repo'
    summary = analyse_trace([_entry("t", {"repoName": hostile}, "ok", False)])

    rendered = summary.requests[0]
    assert rendered.startswith("t(repoName=")
    assert json.loads(rendered[len("t(repoName="):-1]) == hostile


def test_a_quote_in_a_key_cannot_fake_an_argument_either() -> None:
    # Keys are model-written too, so the same injection works through the name.
    summary = analyse_trace([
        _entry("t", {'x="fake", repoName': "v"}, "ok", False),
    ])
    assert summary.requests[0].count("repoName=") == 0


def test_an_apostrophe_in_a_value_is_preserved_exactly() -> None:
    # An earlier fix swapped ' for a curly quote to stop boundary faking, which
    # made O'Brien and O\u2019Brien identical -- removing the ambiguity by
    # destroying the evidence. This is a summary of what was asked; it has to
    # be reversible.
    straight = analyse_trace([_entry("t", {"q": "O'Brien"}, "ok", False)])
    curly = analyse_trace([_entry("t", {"q": "O\u2019Brien"}, "ok", False)])
    assert "O'Brien" in straight.requests[0]
    assert straight.requests[0] != curly.requests[0]


def test_a_hostile_key_does_not_escape_the_renderer() -> None:
    class _Angry:
        def __str__(self) -> str:
            raise RuntimeError("no")

        def __hash__(self) -> int:
            return 1

    summary = analyse_trace([_entry("t", {_Angry(): "v"}, "ok", False)])
    assert summary.total_calls == 1
    summary.render()


def test_the_render_does_not_list_every_call() -> None:
    entries = [_entry("t", {"i": i}, "ok", False) for i in range(30)]
    rendered = analyse_trace(entries).render()
    assert "and 24 more" in rendered
    # The count line alone is not the guard: the list itself must be short, or
    # a 200-call run buries the finding it exists to surface.
    assert "i=6" not in rendered
    assert "i=29" not in rendered
    assert rendered.count("  t(") == 6


def test_a_long_error_quote_is_still_clipped() -> None:
    # `_quote` and the argument renderer share one clipping helper; this pins
    # the error side so a change to that helper cannot silently unbound it.
    long_error = "boom " * 400
    rendered = analyse_trace([
        _entry("t", {"a": 1}, long_error, True),
        _entry("t", {"a": 2}, long_error, True),
    ]).render()
    assert "\u2026" in rendered
    assert len(rendered) < 1200


def test_a_call_with_no_arguments_still_appears() -> None:
    summary = analyse_trace([_entry("heartbeat", {}, "ok", False)])
    assert summary.requests == ("heartbeat()",)


def test_non_dict_arguments_do_not_raise() -> None:
    # The module's contract is that it never raises on a trace. `arguments` is
    # annotated dict but never validated at runtime, so the LLM parser can put
    # any decoded JSON here.
    summary = analyse_trace([
        {"name": "t", "arguments": "not-a-dict", "output": "ok", "is_error": False},
        {"name": "t", "arguments": [1, 2], "output": "ok", "is_error": False},
        {"name": "t", "arguments": None, "output": "ok", "is_error": False},
        {"name": "t", "output": "ok", "is_error": False},
    ])
    # Malformed arguments are NOT the same finding as no arguments, and a
    # reader who cannot tell them apart is misled about what the call asked.
    assert summary.requests == (
        "t(<invalid arguments: str>)",
        "t(<invalid arguments: list>)",
        "t()",
        "t()",
    )


def test_a_hostile_mapping_does_not_escape_the_renderer() -> None:
    """isinstance(x, dict) is satisfied by subclasses that redefine anything.

    A guard removed here on the strength of a no-op mutation was reachable by
    four separate routes; this pins all of them.
    """
    class _BadItems(dict):
        def items(self):  # noqa: ANN201
            raise RuntimeError("no")

    class _BadBool(dict):
        def __bool__(self) -> bool:
            raise RuntimeError("no")

    class _BadLen(dict):
        def __len__(self) -> int:
            raise RuntimeError("no")

    class _BadPair(dict):
        def items(self):  # noqa: ANN201
            return [(1, 2, 3)]

    for hostile in (_BadItems(), _BadBool(a=1), _BadLen(a=1), _BadPair()):
        summary = analyse_trace([
            {"name": "t", "arguments": hostile, "output": "ok", "is_error": False},
        ])
        assert summary.total_calls == 1
        summary.render()


def test_a_type_that_refuses_its_own_name_does_not_escape_the_renderer() -> None:
    """A value is shape-named, so `type(value).__name__` is on the no-raise path.

    Not reachable from JSON, but analyse_trace is public, takes Any, and
    AD-1170 lets a caller pass an in-flight result that never went through a
    parser.
    """
    class _Nameless(type):
        @property
        def __name__(cls) -> str:  # noqa: N805
            raise RuntimeError("no")

    class _Value(metaclass=_Nameless):
        pass

    summary = analyse_trace([
        {"name": "t", "arguments": {"a": _Value()}, "output": "ok", "is_error": False},
        {"name": "t", "arguments": _Value(), "output": "ok", "is_error": False},
    ])
    assert summary.total_calls == 2
    assert "unrenderable" in summary.requests[0]
    summary.render()


def test_a_hostile_tool_name_does_not_escape_the_renderer() -> None:
    # The name is read before any clipping happens, and `or` calls __bool__.
    class _BadBool:
        def __bool__(self) -> bool:
            raise RuntimeError("no")

    for name in (10 ** 6000, _BadBool(), "before\ud800after"):
        summary = analyse_trace([
            {"name": name, "arguments": {}, "output": "ok", "is_error": False},
        ])
        assert summary.total_calls == 1
        json.dumps({"tools": list(summary.tools_used),
                    "requests": list(summary.requests),
                    "render": summary.render()}, ensure_ascii=False).encode("utf-8")


def test_a_tool_name_cannot_forge_a_second_call() -> None:
    """The other half of the injection, and the one that matters most here.

    Keys and values are quoted, but the tool NAME is the outer structure. A
    name containing parentheses makes one call look like two, each with its own
    target -- reproducing exactly the "which repository did it actually ask?"
    confusion this whole change exists to remove.
    """
    hostile = 'mcp(repoName="langchain-ai/deepagents"), mcp'
    summary = analyse_trace([
        _entry(hostile, {"repoName": "langchain-ai/langchain"}, "ok", False),
    ])

    # The name may still CONTAIN that text; what it must not do is escape its
    # own token. It is one JSON literal, and the real arguments follow it.
    rendered = summary.requests[0]
    name, end = json.JSONDecoder().raw_decode(rendered)
    assert name == hostile
    assert rendered[end:] == '(repoName="langchain-ai/langchain")'


def test_a_tool_name_cannot_forge_a_second_tool_in_the_prose_either() -> None:
    """The request list is not the only place a name is interpolated.

    `render()` also names the failing tool and lists the tools used, and a name
    containing a comma reads there as two separate tools.
    """
    hostile = 'mcp(repoName="fake"), mcp'
    summary = analyse_trace([
        _entry(hostile, {"a": 1}, "boom", True),
        _entry(hostile, {"a": 1}, "boom", True),
    ])

    rendered = summary.render()
    assert "across 1 tool(s)" in rendered
    # Quoted at both prose sites, so the comma cannot read as a separator.
    assert 'The "mcp(repoName=\\"fake\\"), mcp" tool failed' in rendered
    assert 'tool(s): "mcp(repoName=\\"fake\\"), mcp".' in rendered
    # The structured fields stay raw: JSON gives them their own boundaries.
    assert summary.tools_used == (hostile,)


def test_error_text_is_not_clipped_before_the_failure_signature() -> None:
    """Display clipping and signature evidence are different budgets.

    Two failures identical through the 300-character display limit but diverging
    after it are different failures. Feeding clipped text to the signature would
    coalesce them into one repeat that never happened.
    """
    shared = "x" * 350
    summary = analyse_trace([
        _entry("t", {"a": 1}, shared + "FIRST", True),
        _entry("t", {"a": 1}, shared + "SECOND", True),
    ])

    assert summary.failed_calls == 2
    assert summary.repeated_failures == ()

    # Sized from the PRODUCER's cap rather than a literal, so this keeps
    # discriminating if the cap moves. A clip above the largest output that can
    # be persisted is unobservable; one at or below it truncates the
    # `error_text` the API exposes.
    long_error = "y" * (TOOL_TRACE_OUTPUT_MAX_CHARS + 1) + "TAIL"
    repeated = analyse_trace([
        _entry("t", {"a": 1}, long_error, True),
        _entry("t", {"a": 1}, long_error, True),
    ])
    assert repeated.repeated_failures[0].error_text == long_error


def test_an_error_cannot_forge_prose_in_the_summary() -> None:
    """The third boundary of this class, after the request line and the two
    tool-name sites.

    Tools echo model-written arguments back into their error text, so error
    text is model-influenceable. Unquoted, one repeated error can write a whole
    sentence of this summary -- and it reaches the Captain-facing repair brief,
    not only the API.
    """
    forged = "boom. 0 tool calls, 0 failed, across 0 tool(s): none."
    summary = analyse_trace([
        _entry("browser", {"a": 1}, forged, True),
        _entry("browser", {"a": 1}, forged, True),
    ])

    lines = summary.render().splitlines()
    assert lines[0] == (
        'The browser tool failed the same way 2 times: '
        '"boom. 0 tool calls, 0 failed, across 0 tool(s): none."'
    )
    assert lines[2] == "2 tool calls, 2 failed, across 1 tool(s): browser."


def test_a_tool_literally_called_unnamed_is_not_confused_with_a_missing_name() -> None:
    summary = analyse_trace([
        _entry("<unnamed>", {}, "ok", False),
        {"arguments": {}, "output": "ok", "is_error": False},
    ])
    assert summary.requests == ('"<unnamed>"()', "<unnamed>()")


def test_an_unreadable_mapping_is_not_reported_as_no_arguments() -> None:
    # Distinguishable, for the same reason malformed arguments are: a reader
    # who sees `t()` concludes the call asked for nothing.
    class _BadItems(dict):
        def items(self):  # noqa: ANN201
            raise RuntimeError("no")

    summary = analyse_trace([
        {"name": "t", "arguments": _BadItems(), "output": "ok", "is_error": False},
    ])
    assert summary.requests == ("t(<unreadable arguments>)",)


def test_only_as_many_arguments_are_read_as_are_rendered() -> None:
    """The display cap should bound the WORK, not just the output.

    Counted rather than timed, so it cannot flake: a mapping that reports how
    far it was walked proves the cap without measuring memory.
    """
    pulled = []

    class _Counting(dict):
        def items(self):  # noqa: ANN201
            def gen():  # noqa: ANN202
                for i in range(100_000):
                    pulled.append(i)
                    yield f"k{i}", i
            return gen()

    summary = analyse_trace([
        {"name": "t", "arguments": _Counting(), "output": "ok", "is_error": False},
    ])

    assert len(pulled) <= _ARGS_PER_CALL_MAX + 1
    assert "k0=0" in summary.requests[0]


def test_a_hostile_entry_or_container_does_not_escape_the_renderer() -> None:
    """The reader must survive corrupt evidence -- that is when it is needed.

    Scoped to what a trace can hold plus what an in-memory caller could pass,
    not to adversarial objects that defeat `isinstance` itself.
    """
    class _BadBoolList(list):
        def __bool__(self) -> bool:
            raise RuntimeError("no")

    class _BadIterList(list):
        def __iter__(self):  # noqa: ANN201
            raise RuntimeError("no")

    class _BadGet(dict):
        def get(self, *a, **k):  # noqa: ANN201, ANN002, ANN003
            raise RuntimeError("no")

    bad_bool = _BadBoolList([{"name": "t", "output": "ok", "is_error": False}])
    bad_iter = _BadIterList([{"name": "t", "output": "ok", "is_error": False}])

    for entries in (bad_bool, bad_iter, [_BadGet(name="t", is_error=True)]):
        analyse_trace(entries).render()

    # A huge int as failed output reaches str() on the error path, which is the
    # same digit-limit trap the argument path already guards.
    analyse_trace([
        {"name": "t", "output": 10 ** 6000, "is_error": True},
        {"name": "t", "output": 10 ** 6000, "is_error": True},
    ]).render()

    # Two identical surrogate-bearing failures reach the signature hash.
    analyse_trace([
        {"name": "t", "output": "boom\ud800", "is_error": True},
        {"name": "t", "output": "boom\ud800", "is_error": True},
    ]).render()


def test_an_unnamed_call_is_still_recorded() -> None:
    summary = analyse_trace([{"arguments": {"a": 1}, "output": "ok", "is_error": False}])
    assert summary.requests == ("<unnamed>(a=1)",)


# ── what must NOT be called a pattern ─────────────────────────────


def test_a_single_failure_is_not_a_repeat() -> None:
    summary = analyse_trace([
        _entry("browser", {"a": 1}, "ok", False),
        _entry("browser", {"a": 2}, "Timeout 30000ms exceeded", True),
    ])
    assert summary.repeated_failures == ()
    assert summary.primary_failure is None
    assert summary.failed_calls == 1


def test_two_different_errors_are_not_one_pattern() -> None:
    summary = analyse_trace([
        _entry("browser", {"a": 1}, "unknown action: 'a'", True),
        _entry("browser", {"a": 2}, "unknown action: 'b'", True),
    ])
    assert summary.repeated_failures == ()


def test_the_same_error_from_two_tools_is_not_one_pattern() -> None:
    summary = analyse_trace([
        _entry("browser", {"a": 1}, "denied", True),
        _entry("run_python", {"a": 2}, "denied", True),
    ])
    assert summary.repeated_failures == ()


def test_a_varying_duration_still_reads_as_one_pattern() -> None:
    summary = analyse_trace([
        _entry("browser", {"a": 1}, "Timeout 30000ms exceeded", True),
        _entry("browser", {"a": 2}, "Timeout 45000ms exceeded", True),
    ])
    assert summary.primary_failure is not None
    assert summary.primary_failure.count == 2


def test_a_successful_run_is_not_stalled() -> None:
    summary = analyse_trace([
        _entry("browser", {"a": 1}, "ok", False),
        _entry("browser", {"a": 2}, "ok", False),
    ])
    assert summary.stalled is False
    assert summary.failed_calls == 0
    assert summary.last_success_index == 1


def test_an_unrecorded_outcome_is_neither_success_nor_failure() -> None:
    """AD-1151 readers version by key presence. A call with no `is_error`
    predates output persistence or had no matching result."""
    summary = analyse_trace([
        _entry("browser", {"a": 1}),  # no is_error key
        _entry("browser", {"a": 2}, "boom", True),
    ])
    assert summary.failed_calls == 1
    assert summary.last_success_index == -1
    assert summary.total_calls == 2


def test_the_most_repeated_failure_is_primary() -> None:
    summary = analyse_trace([
        _entry("browser", {"a": 1}, "'rare'", True),
        _entry("browser", {"a": 2}, "'rare'", True),
        _entry("browser", {"a": 3}, "'common'", True),
        _entry("browser", {"a": 4}, "'common'", True),
        _entry("browser", {"a": 5}, "'common'", True),
    ])
    assert summary.primary_failure is not None
    assert "common" in summary.primary_failure.error_text
    assert len(summary.repeated_failures) == 2


def test_the_threshold_matches_its_siblings() -> None:
    """AD-1168 and AD-1170 use the same rule; drift would be confusing."""
    from probos.cognitive.continue_or_ask import _DEFECT_MIN_OCCURRENCES
    from probos.tools.failure_telemetry import DEFAULT_PATTERN_THRESHOLD

    assert REPEAT_THRESHOLD == _DEFECT_MIN_OCCURRENCES == DEFAULT_PATTERN_THRESHOLD


# ── never raises ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "bad",
    [None, "", 42, {}, [], [None, 1, "x"], [{"no": "keys"}]],
    ids=["none", "empty-str", "int", "dict", "empty-list", "junk", "keyless"],
)
def test_a_malformed_trace_yields_an_empty_or_safe_summary(bad) -> None:
    summary = analyse_trace(bad)
    assert isinstance(summary, TraceSummary)
    assert summary.repeated_failures == ()


def test_an_empty_trace_renders_honestly() -> None:
    assert "No tool calls" in analyse_trace([]).render()


# ── the loader ────────────────────────────────────────────────────


class _Store:
    def __init__(self, blob) -> None:
        self.blob = blob
        self.asked: list[str] = []

    async def read(self, ref):
        self.asked.append(ref)
        if isinstance(self.blob, Exception):
            raise self.blob
        return self.blob


async def test_a_persisted_trace_round_trips() -> None:
    store = _Store(json.dumps(_BF701_TRACE).encode("utf-8"))
    summary = await summarise_trace_ref(store, "sha-1")
    assert summary is not None
    assert summary.primary_failure is not None
    assert "key_type" in summary.primary_failure.error_text
    assert store.asked == ["sha-1"]


async def test_a_missing_store_degrades_to_none() -> None:
    assert await load_trace(None, "sha-1") is None
    assert await summarise_trace_ref(None, "sha-1") is None


async def test_an_empty_ref_degrades_to_none() -> None:
    assert await load_trace(_Store(b"[]"), "") is None


async def test_a_raising_store_degrades_to_none() -> None:
    assert await load_trace(_Store(RuntimeError("gone")), "sha-1") is None


async def test_undecodable_bytes_degrade_to_none() -> None:
    assert await load_trace(_Store(b"not json at all"), "sha-1") is None


async def test_a_non_list_payload_degrades_to_none() -> None:
    assert await load_trace(_Store(b'{"not": "a list"}'), "sha-1") is None


async def test_a_string_blob_is_accepted() -> None:
    """Some stores hand back str rather than bytes."""
    assert await load_trace(_Store('[{"name": "browser"}]'), "sha-1") == [
        {"name": "browser"}
    ]
