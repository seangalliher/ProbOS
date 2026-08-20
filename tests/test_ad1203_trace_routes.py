"""AD-1203 (#1147): the persisted tool trace is readable from outside the process.

Every agentic run writes a complete tool trace (AD-1151) and ``trace_analysis``
(AD-1171) can summarise one. Neither was reachable without walking the raw
attachment index by hand -- which is exactly what the 2026-08-09 investigation
had to do to establish that an agent had genuinely re-read an artifact rather
than repeating the conversation.

Per the API test requirement in ``.github/copilot-instructions.md``, every route
here has a happy path, an error case, and input validation.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.routers import traces as traces_router
from probos.routers.deps import get_runtime


# A real trace, in the exact shape ``build_tool_trace_payload`` emits: a bare
# JSON array of call records keyed by feature presence (AD-1151 DD-2).
TRACE_OK = [
    {"id": "1", "name": "recall_artifact", "arguments": {"ref": "0aaf7ab7b54f"},
     "output": "the artifact text", "is_error": False, "output_chars": 1690},
]
TRACE_STALLED = [
    {"id": "1", "name": "browser", "arguments": {"action": "click", "index": 90},
     "output": "ok", "is_error": False, "output_chars": 2},
    {"id": "2", "name": "browser", "arguments": {"action": "key_type"},
     "output": "unknown browser action", "is_error": True, "output_chars": 22},
    {"id": "3", "name": "browser", "arguments": {"action": "key_type"},
     "output": "unknown browser action", "is_error": True, "output_chars": 22},
]

REF_OK = "a" * 64
REF_STALLED = "b" * 64
REF_UNREADABLE = "c" * 64
REF_ABSENT = "d" * 64


class _FakeAttachmentStore:
    """Only the two methods these routes use. Not a MagicMock (BF-287)."""

    def __init__(self, *, blobs: dict[str, bytes] | None = None,
                 index: list[tuple[str, float]] | None = None,
                 raise_on_list: bool = False) -> None:
        self._blobs = blobs if blobs is not None else {}
        self._index = index if index is not None else []
        self._raise_on_list = raise_on_list

    async def list_by_origin(self, origin: str) -> list[tuple[str, float]]:
        if self._raise_on_list:
            raise OSError("index unreadable")
        assert origin == "crew_trace", f"unexpected origin {origin!r}"
        return list(self._index)

    async def read(self, content_hash: str) -> bytes:
        if content_hash not in self._blobs:
            raise FileNotFoundError(content_hash)
        return self._blobs[content_hash]


def _client(store: Any) -> TestClient:
    app = FastAPI()
    app.include_router(traces_router.router)
    app.dependency_overrides[get_runtime] = lambda: type(
        "_RT", (), {"attachment_store": store},
    )()
    return TestClient(app)


def _populated() -> _FakeAttachmentStore:
    return _FakeAttachmentStore(
        blobs={
            REF_OK: json.dumps(TRACE_OK).encode("utf-8"),
            REF_STALLED: json.dumps(TRACE_STALLED).encode("utf-8"),
            REF_UNREADABLE: b"not json at all",
        },
        # ascending by written_at, as list_by_origin contracts
        index=[(REF_OK, 100.0), (REF_STALLED, 200.0), (REF_UNREADABLE, 300.0)],
    )


# ── GET /api/traces/{ref} ─────────────────────────────────────────


def test_get_trace_returns_every_call_and_a_summary() -> None:
    r = _client(_populated()).get(f"/api/traces/{REF_OK}")

    assert r.status_code == 200
    body = r.json()
    assert body["ref"] == REF_OK
    assert body["calls"] == TRACE_OK
    assert body["summary"]["total_calls"] == 1
    assert body["summary"]["failed_calls"] == 0
    assert body["summary"]["tools_used"] == ["recall_artifact"]
    assert body["summary"]["stalled"] is False


def test_get_trace_puts_the_arguments_on_the_wire() -> None:
    """BF-774 crosses the HTTP seam.

    The summary knowing what a call asked is worth nothing if the projection
    drops it: a client cannot see a mis-aimed-but-successful run any other way,
    because every failure field is empty for exactly that run.
    """
    r = _client(_populated()).get(f"/api/traces/{REF_OK}")

    summary = r.json()["summary"]
    assert summary["requests"] == ['recall_artifact(ref="0aaf7ab7b54f")']
    assert summary["requests_total"] == 1
    assert 'ref="0aaf7ab7b54f"' in summary["render"]


def test_list_traces_puts_the_arguments_on_the_wire() -> None:
    r = _client(_populated()).get("/api/traces")

    by_ref = {t["ref"]: t for t in r.json()["traces"]}
    assert by_ref[REF_OK]["summary"]["requests"] == [
        'recall_artifact(ref="0aaf7ab7b54f")',
    ]
    assert by_ref[REF_STALLED]["summary"]["requests"] == [
        'browser(action="click", index=90)',
        'browser(action="key_type")',
        'browser(action="key_type")',
    ]
    assert by_ref[REF_STALLED]["summary"]["requests_total"] == 3


def test_an_index_row_carries_only_what_a_summary_would_show() -> None:
    """An index row's request list is multiplied by the page size.

    At the full per-trace cap and limit=100 a measured response reached ~5 MB,
    which is a payload risk the detail route does not have. The true count
    still travels, so a client knows the list is partial, and /{ref} serves it
    in full.
    """
    ref = "f" * 64
    trace = [{"id": str(i), "name": "t", "arguments": {"i": i},
              "output": "ok", "is_error": False} for i in range(30)]
    store = _FakeAttachmentStore(
        blobs={ref: json.dumps(trace).encode("utf-8")}, index=[(ref, 100.0)],
    )

    listed = _client(store).get("/api/traces").json()["traces"][0]["summary"]
    detail = _client(store).get(f"/api/traces/{ref}").json()["summary"]

    assert len(listed["requests"]) == 6
    assert listed["requests_total"] == 30
    assert len(detail["requests"]) == 30
    assert detail["requests_total"] == 30


def test_one_bad_character_does_not_fail_the_whole_listing() -> None:
    """A lone surrogate in a persisted argument is an encoding error, not a
    character. Rendered into a summary unsanitised it fails JSONResponse, so a
    single malformed trace would take out the listing for every other trace.

    The detail route is covered by the BF-775 tests below; it echoed the raw
    ``calls`` array verbatim and used to 500 on the same input.
    """
    ref = "e" * 64
    trace = [{"id": "1", "name": "t", "arguments": {"q": "before\ud800after"},
              "output": "ok", "is_error": False}]
    store = _FakeAttachmentStore(
        blobs={ref: json.dumps(trace).encode("utf-8")},
        index=[(ref, 100.0)],
    )

    r = _client(store).get("/api/traces")

    assert r.status_code == 200
    assert r.json()["traces"][0]["summary"]["requests_total"] == 1


# ── BF-775: the detail route survives a bad character too ────────


def _surrogate_store(ref: str, trace: list) -> _FakeAttachmentStore:
    return _FakeAttachmentStore(
        blobs={ref: json.dumps(trace).encode("utf-8")},
        index=[(ref, 100.0)],
    )


def test_a_lone_surrogate_no_longer_makes_the_detail_route_500() -> None:
    """The trace is the flight recorder. The likeliest way to persist a
    surrogate is a tool returning malformed output -- i.e. exactly the failing
    run someone would then go and look at."""
    ref = "e" * 64
    trace = [{"id": "1", "name": "t", "arguments": {"q": "before\ud800after"},
              "output": "ok", "is_error": False}]

    r = _client(_surrogate_store(ref, trace)).get(f"/api/traces/{ref}")

    assert r.status_code == 200, r.text
    assert r.json()["calls"][0]["arguments"]["q"].startswith("before")


def test_a_sanitised_echo_says_it_is_not_byte_exact() -> None:
    """`calls` is documented as verbatim, so a silent rewrite would relocate
    the defect rather than fix it."""
    ref = "e" * 64
    trace = [{"id": "1", "name": "t", "arguments": {"q": "x\ud800y"},
              "output": "ok", "is_error": False}]

    body = _client(_surrogate_store(ref, trace)).get(f"/api/traces/{ref}").json()

    assert body["calls_sanitised"] is True


def test_a_clean_trace_is_not_flagged_as_sanitised() -> None:
    """The flag must mean something; setting it always would make it noise."""
    r = _client(_populated()).get(f"/api/traces/{REF_OK}")

    assert r.status_code == 200
    assert "calls_sanitised" not in r.json()


def test_the_summary_is_still_served_alongside_a_sanitised_echo() -> None:
    """The summary answers "what happened" and is already clean (BF-774)."""
    ref = "e" * 64
    trace = [{"id": "1", "name": "t", "arguments": {"q": "x\ud800y"},
              "output": "ok", "is_error": False}]

    body = _client(_surrogate_store(ref, trace)).get(f"/api/traces/{ref}").json()

    assert body["summary"]["requests_total"] == 1


def test_a_surrogate_in_a_key_is_also_survivable() -> None:
    """A bad key fails the same encode as a bad value."""
    ref = "e" * 64
    trace = [{"id": "1", "name": "t", "arguments": {"bad\ud800key": "v"},
              "output": "ok", "is_error": False}]

    r = _client(_surrogate_store(ref, trace)).get(f"/api/traces/{ref}")

    assert r.status_code == 200, r.text
    assert r.json()["calls_sanitised"] is True


def test_a_key_collision_does_not_delete_a_call_argument() -> None:
    """Sanitising maps both "a\\ud800b" and a legitimate "a?b" onto "a?b".

    A naive assignment drops one and still returns 200 with the flag set --
    forensic data loss concealed behind a successful response, which for a
    flight recorder is worse than the 500 being fixed.
    """
    ref = "e" * 64
    trace = [{"id": "1", "name": "t",
              "arguments": {"bad\ud800key": "surrogate-value",
                            "bad?key": "literal-question-value"},
              "output": "ok", "is_error": False}]

    r = _client(_surrogate_store(ref, trace)).get(f"/api/traces/{ref}")

    assert r.status_code == 200, r.text
    args = r.json()["calls"][0]["arguments"]
    assert len(args) == 2, f"a call argument was silently dropped: {args}"
    assert set(args.values()) == {"surrogate-value", "literal-question-value"}


def test_a_deeply_nested_argument_is_still_readable() -> None:
    """The production writer accepts nested ``arguments``; FastAPI's annotated-
    dict serializer fails around 96 levels down, before JSONResponse.

    Depth chosen to sit BELOW the transport truncation bound and ABOVE the
    serializer's limit, so it discriminates. A depth past the bound is
    truncated first and would pass either way.
    """
    ref = "e" * 64
    deep: Any = "leaf"
    for _ in range(110):
        deep = {"n": deep}
    trace = [{"id": "1", "name": "t", "arguments": {"tree": deep},
              "output": "ok", "is_error": False}]

    r = _client(_surrogate_store(ref, trace)).get(f"/api/traces/{ref}")

    assert r.status_code == 200, r.text[:400]


def test_nesting_past_the_transport_bound_is_truncated_and_flagged() -> None:
    """Without a bound, a pathological trace trades a surrogate error for a
    RecursionError -- still a 500, just a different one."""
    from probos.cognitive.trace_analysis import (
        _TRANSPORT_MAX_DEPTH,
        sanitise_for_transport,
    )

    deep: Any = "leaf"
    for _ in range(_TRANSPORT_MAX_DEPTH + 40):
        deep = {"n": deep}

    clean, changed = sanitise_for_transport(deep)

    assert changed is True, "truncation happened but was not reported"
    rendered = json.dumps(clean)
    assert "<depth-limited>" in rendered


def test_a_non_finite_float_does_not_produce_invalid_json() -> None:
    """json.dumps emits bare NaN/Infinity, which is not valid JSON."""
    from probos.cognitive.trace_analysis import sanitise_for_transport

    clean, changed = sanitise_for_transport(
        {"nan": float("nan"), "inf": float("inf"), "ok": 1.5}
    )

    assert changed is True
    assert clean["nan"] is None
    assert clean["inf"] is None
    assert clean["ok"] == 1.5


def test_astral_characters_are_not_mangled() -> None:
    """Correctly paired non-BMP characters are real data, not encoding errors."""
    from probos.cognitive.trace_analysis import sanitise_for_transport

    value = {"emoji": "\U0001F600", "cjk": "\U00020000"}

    clean, changed = sanitise_for_transport(value)

    assert changed is False
    assert clean == value


def test_a_surrogate_nested_deep_in_the_arguments_is_reached() -> None:
    """``arguments`` is the nested field the production writer preserves;
    ``output`` is stringified before persistence."""
    ref = "e" * 64
    trace = [{"id": "1", "name": "t",
              "arguments": {"rows": [{"cell": "deep\ud800bad"}]},
              "output": "ok", "is_error": False}]

    r = _client(_surrogate_store(ref, trace)).get(f"/api/traces/{ref}")

    assert r.status_code == 200, r.text
    assert r.json()["calls_sanitised"] is True


def test_sanitising_preserves_non_string_scalars() -> None:
    """0, 0.0 and False are values an auditor needs to see. Stringifying them
    is the mistake _clip's docstring already warns about."""
    from probos.cognitive.trace_analysis import sanitise_for_transport

    value = {"zero": 0, "float": 0.0, "false": False, "none": None,
             "nested": [1, {"deep": True}]}

    clean, changed = sanitise_for_transport(value)

    assert changed is False
    assert clean == value
    assert clean["false"] is False
    assert clean["none"] is None


def test_sanitising_reports_no_change_for_clean_input() -> None:
    from probos.cognitive.trace_analysis import sanitise_for_transport

    clean, changed = sanitise_for_transport({"a": ["b", {"c": "d"}]})

    assert changed is False
    assert clean == {"a": ["b", {"c": "d"}]}


def test_sanitised_output_actually_encodes() -> None:
    """The property that matters: the result can reach the wire.

    Uses the REAL response encoder. A bare ``json.dumps`` defaults to
    ``ensure_ascii=True``, which renders an unpaired surrogate as the ASCII
    escape ``\\ud800`` and passes whether or not anything was sanitised -- the
    first version of this test was vacuous for exactly that reason.
    """
    from fastapi.responses import JSONResponse

    from probos.cognitive.trace_analysis import sanitise_for_transport

    clean, changed = sanitise_for_transport(
        {"k\ud800": ["v\udfff", {"n": "\ud800"}]}
    )

    assert changed is True
    JSONResponse(content=clean).body  # must not raise

    with pytest.raises(UnicodeEncodeError):
        json.dumps({"n": "\ud800"}, ensure_ascii=False).encode("utf-8")


def test_get_trace_surfaces_the_stall_that_the_agents_own_account_would_not() -> None:
    """The BF-701 shape: the agent reached the target on call 1 and was refused
    the verb for using it, then narrated a different reason. The trace shows the
    repeated refusal.
    """
    r = _client(_populated()).get(f"/api/traces/{REF_STALLED}")

    assert r.status_code == 200
    summary = r.json()["summary"]
    assert summary["total_calls"] == 3
    assert summary["failed_calls"] == 2
    assert summary["stalled"] is True
    assert summary["trailing_failure_count"] == 2
    assert summary["repeated_failures"]
    assert summary["repeated_failures"][0]["tool_id"] == "browser"
    assert summary["repeated_failures"][0]["count"] == 2
    assert "browser" in summary["render"]


def test_get_trace_404s_for_an_absent_ref() -> None:
    r = _client(_populated()).get(f"/api/traces/{REF_ABSENT}")

    assert r.status_code == 404


def test_get_trace_404s_when_the_bytes_are_not_decodable() -> None:
    """A ref the index knows about whose blob is corrupt. ``load_trace``
    honest-degrades to None rather than raising, so the route must 404 rather
    than 500.
    """
    r = _client(_populated()).get(f"/api/traces/{REF_UNREADABLE}")

    assert r.status_code == 404


@pytest.mark.parametrize("bad", [
    "short",                      # under the 8-char floor
    "z" * 64,                     # not hex
    "a" * 65,                     # over the 64-char ceiling
    "../../etc/passwd",           # traversal-shaped
    "a" * 8 + "%",                # wildcard-shaped
])
def test_get_trace_rejects_a_malformed_ref(bad: str) -> None:
    r = _client(_populated()).get(f"/api/traces/{bad}")

    assert r.status_code in (400, 404), f"{bad!r} was not refused"


def test_get_trace_503s_without_an_attachment_store() -> None:
    r = _client(None).get(f"/api/traces/{REF_OK}")

    assert r.status_code == 503


# ── GET /api/traces ───────────────────────────────────────────────


def test_list_traces_returns_newest_first_with_summaries() -> None:
    r = _client(_populated()).get("/api/traces")

    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    refs = [t["ref"] for t in body["traces"]]
    assert refs == [REF_UNREADABLE, REF_STALLED, REF_OK], "not newest-first"
    stalled = [t for t in body["traces"] if t["ref"] == REF_STALLED][0]
    assert stalled["readable"] is True
    assert stalled["summary"]["stalled"] is True


def test_list_traces_reports_an_unreadable_trace_rather_than_hiding_it() -> None:
    """A trace the index knows about but cannot decode is itself a finding;
    omitting the row would make a broken record look like no record.
    """
    r = _client(_populated()).get("/api/traces")

    row = [t for t in r.json()["traces"] if t["ref"] == REF_UNREADABLE][0]
    assert row["readable"] is False
    assert "summary" not in row


def test_list_traces_honours_the_limit() -> None:
    r = _client(_populated()).get("/api/traces?limit=1")

    body = r.json()
    assert len(body["traces"]) == 1
    assert body["traces"][0]["ref"] == REF_UNREADABLE  # newest
    assert body["total"] == 3, "total reports the index size, not the page size"


@pytest.mark.parametrize("bad", ["0", "-1", "101", "abc"])
def test_list_traces_rejects_an_out_of_range_limit(bad: str) -> None:
    r = _client(_populated()).get(f"/api/traces?limit={bad}")

    assert r.status_code == 422


def test_list_traces_degrades_when_the_index_cannot_be_read() -> None:
    """Tier-2: an enumeration failure returns an empty index, not a 500. The
    caller is usually looking at this because something is already wrong.
    """
    r = _client(_FakeAttachmentStore(raise_on_list=True)).get("/api/traces")

    assert r.status_code == 200
    assert r.json() == {"traces": [], "total": 0}


def test_list_traces_is_empty_when_nothing_has_been_recorded() -> None:
    r = _client(_FakeAttachmentStore()).get("/api/traces")

    assert r.status_code == 200
    assert r.json() == {"traces": [], "total": 0}


def test_list_traces_503s_without_an_attachment_store() -> None:
    r = _client(None).get("/api/traces")

    assert r.status_code == 503


# ── the routes are actually mounted ───────────────────────────────


def test_the_traces_router_is_registered_on_the_real_app() -> None:
    """A router that exists and is never included is the defect this AD is
    fixing, one layer up.
    """
    import probos.api as api_module

    src = __import__("inspect").getsource(api_module)
    assert "traces as traces_router" in src
    assert "traces_router," in src
