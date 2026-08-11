"""BF-746: the MCP bridge advertised a framing it could not read.

`HttpTransport.request()` sent `Accept: application/json, text/event-stream` and
then called `response.json()` unconditionally. Streamable HTTP lets the server
choose either framing for the same request, so a server that answers with SSE
died at `initialize` with "bad JSON" before the handshake finished.

Verified live against `https://learn.microsoft.com/api/mcp` on 2026-08-11:

    status: 200
    content-type: text/event-stream
    body: event: message\\ndata: {"result":{"protocolVersion":"2025-06-18",...

That is a legal answer, and the header we send says we accept it. So every HTTP
MCP server making that choice has never worked -- which is the real reason the
reference vessel had zero registered servers, and why the earlier reading of
"the machinery is fine, nothing is registered" was incurious. Zero rows was a
symptom, not an absence of interest.

Same shape as the rest of this week: producer correct, consumer correct, the
decode between them unbuilt -- except here the code *declared* it handled both
framings in a header and did not, which is the confabulation pattern expressed
in a wire protocol.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from probos.integrations.mcp_bridge.client import MCPProtocolError
from probos.integrations.mcp_bridge.transport import (
    _SSE_MAX_EVENTS,
    _json_rpc_from_sse,
)


def _sse(*envelopes: dict, event: str = "message") -> str:
    return "\n\n".join(
        f"event: {event}\ndata: {json.dumps(e)}" for e in envelopes
    ) + "\n\n"


# ── the live case ─────────────────────────────────────────────────


def test_the_shape_microsoft_learn_actually_returns() -> None:
    """Captured verbatim from the live server, CRLF and all."""
    body = (
        "event: message\r\n"
        'data: {"result":{"protocolVersion":"2025-06-18","capabilities":{},'
        '"serverInfo":{"name":"Microsoft Learn MCP Server","version":"1.0.0"}},'
        '"jsonrpc":"2.0","id":1}\r\n\r\n'
    )

    envelope = _json_rpc_from_sse(body, url="https://learn.microsoft.com/api/mcp",
                                 expect_id=1)

    assert envelope["id"] == 1
    assert envelope["result"]["serverInfo"]["name"] == "Microsoft Learn MCP Server"


def test_a_single_envelope_is_returned_whatever_its_id() -> None:
    """A server that answers once with an id we did not send is likelier to be
    right than this matcher is.
    """
    body = _sse({"jsonrpc": "2.0", "id": 99, "result": {"ok": True}})
    assert _json_rpc_from_sse(body, url="u", expect_id=1)["result"] == {"ok": True}


# ── framing details the spec allows ───────────────────────────────


def test_the_matching_id_wins_when_several_envelopes_arrive() -> None:
    """A stream may carry notifications or progress alongside the response."""
    body = _sse(
        {"jsonrpc": "2.0", "method": "notifications/progress", "params": {}},
        {"jsonrpc": "2.0", "id": 7, "result": {"tools": []}},
    )
    assert _json_rpc_from_sse(body, url="u", expect_id=7)["id"] == 7


def test_multi_line_data_fields_are_joined_with_newlines() -> None:
    """SSE splits a long payload across repeated data: lines; they concatenate."""
    body = 'event: message\ndata: {"jsonrpc":"2.0","id":1,\ndata: "result":{"a":1}}\n\n'
    assert _json_rpc_from_sse(body, url="u", expect_id=1)["result"] == {"a": 1}


def test_comment_and_field_lines_are_ignored() -> None:
    """Keep-alive comments and id:/retry: fields are not payload."""
    body = (
        ": keep-alive\n"
        "id: 42\n"
        "retry: 3000\n"
        "event: message\n"
        'data: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n\n'
    )
    assert _json_rpc_from_sse(body, url="u", expect_id=1)["result"] == {"ok": True}


def test_an_unparseable_block_does_not_discard_a_good_one() -> None:
    body = (
        "event: message\ndata: not json at all\n\n"
        'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n\n'
    )
    assert _json_rpc_from_sse(body, url="u", expect_id=1)["id"] == 1


def test_a_non_object_payload_is_skipped() -> None:
    """JSON-RPC envelopes are objects. A bare array or string is not one."""
    body = (
        'event: message\ndata: ["not", "an", "envelope"]\n\n'
        'event: message\ndata: {"jsonrpc":"2.0","id":1,"result":{}}\n\n'
    )
    assert _json_rpc_from_sse(body, url="u", expect_id=1)["id"] == 1


# ── it fails honestly ─────────────────────────────────────────────


@pytest.mark.parametrize("body", [
    "",
    ": just a comment\n\n",
    "event: message\n\n",
    "event: message\ndata: {broken\n\n",
])
def test_a_stream_with_no_envelope_raises_rather_than_returning_nothing(
    body: str,
) -> None:
    with pytest.raises(MCPProtocolError) as exc:
        _json_rpc_from_sse(body, url="https://x.test/mcp")
    assert exc.value.reason == "bad_sse"
    assert "x.test" in str(exc.value)


def test_an_endless_stream_cannot_make_this_the_thing_that_hangs() -> None:
    """A response to one request is short by construction; the cap is for a
    server that disagrees. Past the cap the matching envelope is unreachable,
    and the first envelope seen inside the cap is returned rather than nothing
    -- an answer from a misbehaving server beats no answer.
    """
    flood = _sse(*[{"jsonrpc": "2.0", "method": "noise"} for _ in range(500)])
    tail = _sse({"jsonrpc": "2.0", "id": 1, "result": {"reached": True}})

    out = _json_rpc_from_sse(flood + tail, url="u", expect_id=1)

    assert out.get("method") == "noise"   # the cap bit before the tail
    assert "result" not in out


def test_the_cap_is_stated_not_incidental() -> None:
    assert _SSE_MAX_EVENTS == 64


# ── the JSON path is untouched ────────────────────────────────────


class _Resp:
    def __init__(self, *, ctype: str, text: str, status: int = 200) -> None:
        self.status_code = status
        self.text = text
        self.headers = {"content-type": ctype}

    def json(self) -> Any:
        return json.loads(self.text)


def _transport(resp: _Resp) -> Any:
    from probos.integrations.mcp_bridge.transport import HttpTransport

    class _Http:
        async def post(self, *a: Any, **kw: Any) -> _Resp:
            return resp

    t = HttpTransport(server_url="https://x.test/mcp", base_headers={})
    t._http = _Http()
    return t


def test_a_json_answer_is_parsed_exactly_as_before() -> None:
    """The overwhelming majority of servers answer with application/json. This
    fix must not have moved them.
    """
    import asyncio

    resp = _Resp(ctype="application/json", text='{"jsonrpc":"2.0","id":1,"result":{"a":1}}')
    out = asyncio.run(_transport(resp).request({"jsonrpc": "2.0", "id": 1}))
    assert out["result"] == {"a": 1}


def test_a_json_content_type_with_a_charset_still_takes_the_json_path() -> None:
    import asyncio

    resp = _Resp(ctype="application/json; charset=utf-8", text='{"id":1,"result":{}}')
    assert asyncio.run(_transport(resp).request({"id": 1}))["id"] == 1


def test_an_sse_content_type_with_a_charset_takes_the_sse_path() -> None:
    """``text/event-stream; charset=utf-8`` is the same framing."""
    import asyncio

    resp = _Resp(
        ctype="text/event-stream; charset=utf-8",
        text='event: message\ndata: {"id":1,"result":{"sse":true}}\n\n',
    )
    out = asyncio.run(_transport(resp).request({"id": 1}))
    assert out["result"] == {"sse": True}


def test_broken_json_on_the_json_path_still_reports_bad_json() -> None:
    import asyncio

    resp = _Resp(ctype="application/json", text="{not json")
    with pytest.raises(MCPProtocolError) as exc:
        asyncio.run(_transport(resp).request({"id": 1}))
    assert exc.value.reason == "bad_json"


def test_the_accept_header_still_advertises_both_framings() -> None:
    """It always did. The defect was that only one was implemented -- so this
    assertion is only honest now.
    """
    import inspect

    from probos.integrations.mcp_bridge import transport

    src = inspect.getsource(transport.HttpTransport.request)
    assert "application/json, text/event-stream" in src
    assert "_json_rpc_from_sse(" in src
