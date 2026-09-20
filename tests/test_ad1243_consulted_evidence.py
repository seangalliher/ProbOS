"""AD-1243: unit tests for the shared safe evidence policy.

``trace_evidence.py`` is the single implementation of the AD-1242 key/value/
URL sanitisation policy, now shared between the judge-prompt trace section
(``crew_verifier``) and the read-only ``/api/traces/{ref}/consulted``
projection (``routers/traces``). These tests exercise the module directly:
policy behaviour (key classification, URL reduction, the 4,096-code-point
raw-inspection bound) and the new receipt shape (the 16 KiB bound, the
``requests_total == len(requests) + requests_omitted`` invariant, invalid-entry
counting, and the ``redacted``/``truncated`` flags).

API-level (auth, storage, HTTP status/header) coverage for the
``/consulted`` route lives in ``tests/test_distribution.py`` alongside the
rest of the FastAPI endpoint tests; it is not duplicated here.
"""

from __future__ import annotations

import json

import pytest

import probos.cognitive.crew_verifier as crew_verifier
from probos.cognitive import trace_evidence
from probos.cognitive.trace_evidence import (
    _MAX_RAW_INSPECTION_CHARS,
    _MAX_RECEIPT_BYTES,
    _OVERSIZED_MARKER,
    _bound_raw_argument_value,
    _bound_raw_entries,
    _bound_raw_scalar,
    _sanitize_request_line,
    build_consulted_receipt,
    sanitize_trace_render,
)


def _entry(name: str, arguments: dict) -> dict:
    return {"name": name, "arguments": arguments}


# ---------------------------------------------------------------------------
# sanitize_trace_render / crew_verifier compatibility wrapper
# ---------------------------------------------------------------------------


class TestSanitizeTraceRenderWrapper:
    def test_crew_verifier_wrapper_delegates_to_shared_module(self) -> None:
        rendered = (
            "What it asked:\n"
            '  http_fetch(url="https://example.com/a", password="hunter2")'
        )
        direct = sanitize_trace_render(rendered, 8_192)
        via_wrapper = crew_verifier._trace_sanitize_render(rendered, 8_192)
        assert direct == via_wrapper
        assert "hunter2" not in direct

    def test_wrapper_is_monkeypatch_targetable(self, monkeypatch) -> None:
        # tests/test_ad1242_crew_verifier_trace.py patches this exact module
        # attribute; the move must not have broken that seam.
        sentinel_called = {"called": False}

        def _fake(rendered: str, payload_limit: int) -> str:
            sentinel_called["called"] = True
            return "patched"

        monkeypatch.setattr(crew_verifier, "_trace_sanitize_render", _fake)
        assert crew_verifier._trace_sanitize_render("anything", 100) == "patched"
        assert sentinel_called["called"] is True

    def test_truncates_by_dropping_whole_trailing_fragments(self) -> None:
        rendered = "\n".join(f"  http_fetch(page={i})" for i in range(50))
        out = sanitize_trace_render(rendered, 200)
        assert len(out) <= 200 + len("[Trace evidence truncated]") + 1
        assert out.endswith("[Trace evidence truncated]")


# ---------------------------------------------------------------------------
# Key classification / redaction policy (via _sanitize_request_line)
# ---------------------------------------------------------------------------


class TestKeyClassificationPolicy:
    def test_protected_credential_argument_is_masked(self) -> None:
        line = 'http_fetch(password="hunter2")'
        out = _sanitize_request_line(line)
        assert "hunter2" not in out
        assert "REDACTED" in out

    def test_protected_token_suffix_is_masked(self) -> None:
        line = 'http_fetch(authToken="abc123secret")'
        out = _sanitize_request_line(line)
        assert "abc123secret" not in out

    def test_ordinary_repository_target_is_preserved(self) -> None:
        # Contract: "Preserve useful ordinary repository targets, such as
        # repoName="langchain-ai/langchain"."
        line = 'clone_repo(repoName="langchain-ai/langchain")'
        out = _sanitize_request_line(line)
        assert out == line

    def test_numeric_class_value_is_preserved(self) -> None:
        line = "list_items(offset=20, limit=10)"
        out = _sanitize_request_line(line)
        assert out == line

    def test_classification_uses_original_name_before_shortening(self) -> None:
        # A protected key must be recognised even though its rendered
        # (quoted) form differs from its raw name -- classification happens
        # on the original name, not the display form.
        line = 'send("api_key"="s3cr3t")'
        out = _sanitize_request_line(line)
        assert "s3cr3t" not in out


@pytest.mark.parametrize("key", ["x" * 100 + "token", "x" * 100 + "authorization"])
def test_receipt_classifies_original_key_before_formatter_shortens_it(key: str) -> None:
    value = "violet-sentinel"
    receipt = build_consulted_receipt([_entry("lookup", {key: value})], "deadbeef")
    assert value not in json.dumps(receipt)
    assert "REDACTED" in receipt["requests"][0]
    assert receipt["redacted"] is True


def test_receipt_oversized_key_omits_its_value_as_well() -> None:
    key = "x" * 4_100 + "token"
    value = "violet-sentinel"
    receipt = build_consulted_receipt([_entry("lookup", {key: value})], "deadbeef")
    assert value not in json.dumps(receipt)
    assert _OVERSIZED_MARKER in receipt["requests"][0]


def test_receipt_sanitizes_whole_bounded_free_text_before_shortening() -> None:
    value = "violet-sentinel " + "x" * 160 + " password=another-sentinel"
    receipt = build_consulted_receipt([_entry("lookup", {"query": value})], "deadbeef")
    assert "violet-sentinel" not in json.dumps(receipt)
    assert "another-sentinel" not in json.dumps(receipt)
    assert receipt["redacted"] is True


@pytest.mark.parametrize("ref", ["", None, True, 4, "z" * 64, "a" * 65])
def test_receipt_rejects_invalid_ref_before_serialized_response_can_exceed_bound(ref) -> None:
    with pytest.raises(ValueError, match="consulted_trace_ref_invalid"):
        build_consulted_receipt([], ref)


class TestUrlSanitizationPolicy:
    def test_url_reduced_to_origin_and_path(self) -> None:
        line = (
            'http_fetch(url="https://user:pw@example.com:8443'
            '/a/b?token=abc#frag")'
        )
        out = _sanitize_request_line(line)
        assert "user" not in out
        assert "pw" not in out
        assert "token=abc" not in out
        assert "frag" not in out
        assert "https://" in out
        assert "example.com" in out
        assert "/a/b" in out

    def test_non_http_scheme_url_is_fully_redacted(self) -> None:
        line = 'http_fetch(url="file:///etc/passwd")'
        out = _sanitize_request_line(line)
        assert "/etc/passwd" not in out
        assert "REDACTED" in out


class TestMidLengthUrlPreSanitization:
    """AD-1243 fix: a URL strictly between ``analyse_trace``'s own 80-char
    per-argument clip (BF-774) and this module's 4,096-code-point oversized
    bound previously reached ``analyse_trace`` untouched (``_bound_raw_scalar``
    only replaces values over 4,096 chars whole), so it was ellipsis-clipped
    mid-value there -- before ``_trace_sanitize_url`` ever ran -- producing a
    mangled, percent-re-encoded path instead of a clean origin/path. See
    ``_bound_raw_argument_value``.
    """

    @staticmethod
    def _long_credentialed_url(secret: str = "AD1243_SYNTHETIC_SECRET_DoNotRender") -> str:
        return (
            "https://fixture-user:" + secret
            + "@example.test/repos/langchain?token=" + secret + "#" + secret
        )

    def test_url_over_the_clip_bound_is_pre_sanitized_not_clipped(self) -> None:
        url = self._long_credentialed_url()
        assert 80 < len(url) < _MAX_RAW_INSPECTION_CHARS
        assert _bound_raw_argument_value(url) == "https://example.test/repos/langchain"

    def test_pre_sanitized_url_is_flagged_as_an_alteration(self) -> None:
        bounded, any_omitted = _bound_raw_entries(
            [_entry("http_fetch", {"url": self._long_credentialed_url()})]
        )
        [entry] = bounded
        assert entry["arguments"]["url"] == "https://example.test/repos/langchain"
        assert any_omitted is True

    def test_already_clean_short_url_is_unflagged(self) -> None:
        url = "https://example.test/repos/langchain"
        bounded, any_omitted = _bound_raw_entries([_entry("http_fetch", {"url": url})])
        [entry] = bounded
        assert entry["arguments"]["url"] == url
        assert any_omitted is False

    def test_non_url_string_in_the_same_length_range_is_left_for_analyse_trace(
        self,
    ) -> None:
        # Only URL-shaped values are pre-sanitized here; an ordinary long
        # string still relies on analyse_trace's own clip, unaffected by
        # this fix.
        text = "not a url, just a long comment " * 3
        assert 80 < len(text) < _MAX_RAW_INSPECTION_CHARS
        assert _bound_raw_argument_value(text) == text

    def test_end_to_end_receipt_has_clean_url_no_ellipsis_no_credential_leak(
        self,
    ) -> None:
        secret = "AD1243_SYNTHETIC_SECRET_DoNotRender"
        entries = [
            _entry(
                "consulted_probe",
                {
                    "control": "turn-1",
                    "repoName": "langchain-ai/langchain",
                    "query": "inline-yeo-notes-café",
                    "apiToken": secret,
                    "url": self._long_credentialed_url(secret),
                },
            )
        ]
        receipt = build_consulted_receipt(entries, "deadbeef")
        blob = json.dumps(receipt, ensure_ascii=False)
        assert secret not in blob
        assert "\u2026" not in blob
        assert "%E2%80%A6" not in blob
        assert 'url="https://example.test/repos/langchain"' in receipt["requests"][0]
        assert "café" in receipt["requests"][0]
        assert receipt["redacted"] is True


class TestRawInspectionBound:
    def test_oversized_argument_value_is_replaced_whole_before_analysis(self) -> None:
        # Contract: "Bound raw scalar/name inspection at 4,096 code points.
        # Omit oversized values whole, not a shortened prefix that could hide
        # a protected key." ``_bound_raw_scalar`` runs before
        # ``analyse_trace`` clips/renders anything, so the oversized value
        # never reaches the 80-character clip that would otherwise expose an
        # 80-character prefix of it.
        huge_value = "s" * (_MAX_RAW_INSPECTION_CHARS + 100)
        assert _bound_raw_scalar(huge_value) == _OVERSIZED_MARKER
        assert _bound_raw_scalar(huge_value[:_MAX_RAW_INSPECTION_CHARS]) == (
            huge_value[:_MAX_RAW_INSPECTION_CHARS]
        )
        # Non-string scalars are never in scope for the bound.
        assert _bound_raw_scalar(12345) == 12345
        assert _bound_raw_scalar(None) is None

    def test_oversized_argument_name_is_replaced_whole(self) -> None:
        huge_name = "k" * (_MAX_RAW_INSPECTION_CHARS + 1)
        bounded, any_omitted = _bound_raw_entries([_entry("tool", {huge_name: "value"})])
        [entry] = bounded
        assert list(entry["arguments"].keys()) == [_OVERSIZED_MARKER]
        assert any_omitted is True

    def test_oversized_value_never_reaches_the_final_receipt(self) -> None:
        huge_value = "s" * (_MAX_RAW_INSPECTION_CHARS + 100)
        entries = [_entry("http_fetch", {"comment": huge_value})]
        receipt = build_consulted_receipt(entries, "deadbeef")
        blob = json.dumps(receipt)
        assert huge_value not in blob
        assert huge_value[:50] not in blob
        assert _OVERSIZED_MARKER in blob

    def test_non_dict_entries_pass_through_unbounded_check_unchanged(self) -> None:
        bounded, any_omitted = _bound_raw_entries(["not-a-dict", 42, None])
        assert bounded == ["not-a-dict", 42, None]
        assert any_omitted is False

    def test_value_at_exactly_the_bound_is_not_replaced(self) -> None:
        exact = "k" * _MAX_RAW_INSPECTION_CHARS
        assert _bound_raw_scalar(exact) == exact

    def test_unparseable_rendered_line_gets_explicit_omission_marker(self) -> None:
        out = _sanitize_request_line("not a valid call(")
        assert out == "[Unrecognized trace request omitted]"


# ---------------------------------------------------------------------------
# build_consulted_receipt
# ---------------------------------------------------------------------------


class TestBuildConsultedReceiptShape:
    def test_returns_documented_keys_only(self) -> None:
        entries = [_entry("http_fetch", {"url": "https://example.com/a"})]
        receipt = build_consulted_receipt(entries, "deadbeef")
        assert set(receipt) == {
            "ref", "requests", "requests_total", "requests_omitted",
            "invalid_entries", "redacted", "truncated", "notice",
        }
        assert receipt["ref"] == "deadbeef"
        assert isinstance(receipt["requests"], list)
        assert all(isinstance(item, str) for item in receipt["requests"])
        assert isinstance(receipt["requests_total"], int)
        assert isinstance(receipt["requests_omitted"], int)
        assert isinstance(receipt["invalid_entries"], int)
        assert isinstance(receipt["redacted"], bool)
        assert isinstance(receipt["truncated"], bool)
        assert isinstance(receipt["notice"], str) and receipt["notice"]

    def test_requests_total_invariant_holds(self) -> None:
        entries = [_entry("tool", {"index": i}) for i in range(10)]
        receipt = build_consulted_receipt(entries, "cafebabe")
        assert (
            receipt["requests_total"]
            == len(receipt["requests"]) + receipt["requests_omitted"]
        )

    def test_non_list_entries_return_empty_shape(self) -> None:
        receipt = build_consulted_receipt(None, "deadbeef")  # type: ignore[arg-type]
        assert receipt["requests"] == []
        assert receipt["requests_total"] == 0
        assert receipt["requests_omitted"] == 0
        assert receipt["invalid_entries"] == 0
        assert receipt["redacted"] is False
        assert receipt["truncated"] is False

    def test_never_includes_raw_calls_or_output_fields(self) -> None:
        entries = [
            {
                "name": "http_fetch",
                "arguments": {"url": "https://example.com/a"},
                "output": "super secret output body",
                "is_error": False,
            },
        ]
        receipt = build_consulted_receipt(entries, "deadbeef")
        blob = json.dumps(receipt)
        assert "super secret output body" not in blob
        assert "output" not in receipt
        assert "calls" not in receipt
        assert "summary" not in receipt


class TestInvalidEntryCounting:
    def test_counts_non_dict_entries_separately(self) -> None:
        entries = [
            _entry("tool_a", {}),
            "not-a-dict",
            42,
            None,
            _entry("tool_b", {}),
        ]
        receipt = build_consulted_receipt(entries, "deadbeef")
        assert receipt["invalid_entries"] == 3
        assert receipt["requests_total"] == 2

    def test_all_valid_entries_yields_zero_invalid(self) -> None:
        entries = [_entry("tool_a", {}), _entry("tool_b", {})]
        receipt = build_consulted_receipt(entries, "deadbeef")
        assert receipt["invalid_entries"] == 0


class TestRedactedFlag:
    def test_true_when_a_request_line_is_altered(self) -> None:
        entries = [_entry("http_fetch", {"password": "hunter2"})]
        receipt = build_consulted_receipt(entries, "deadbeef")
        assert receipt["redacted"] is True

    def test_false_when_no_request_line_is_altered(self) -> None:
        entries = [_entry("clone_repo", {"repoName": "langchain-ai/langchain"})]
        receipt = build_consulted_receipt(entries, "deadbeef")
        assert receipt["redacted"] is False

    def test_false_when_there_are_no_requests_at_all(self) -> None:
        receipt = build_consulted_receipt([], "deadbeef")
        assert receipt["redacted"] is False
        assert receipt["requests"] == []


class TestTruncatedFlag:
    def test_false_when_nothing_is_omitted(self) -> None:
        entries = [_entry("tool", {"index": i}) for i in range(3)]
        receipt = build_consulted_receipt(entries, "deadbeef")
        assert receipt["truncated"] is False
        assert receipt["requests_omitted"] == 0

    def test_true_when_requests_total_exceeds_rendered_requests(self) -> None:
        # analyse_trace bounds rendered requests at 40 (BF-774); 45 dict
        # entries means 5 are counted in requests_total but never rendered.
        entries = [_entry("tool", {"index": i}) for i in range(45)]
        receipt = build_consulted_receipt(entries, "deadbeef")
        assert receipt["requests_total"] == 45
        assert len(receipt["requests"]) == 40
        assert receipt["requests_omitted"] == 5
        assert receipt["truncated"] is True


class TestSixteenKibBound:
    def test_complete_utf8_payload_never_exceeds_16kib(self) -> None:
        # Each rendered request line easily fits under the per-line bound but
        # 40 of them, with large-ish ordinary values, should still be well
        # inside 16 KiB after sanitisation -- confirm the ceiling holds even
        # when nothing needs to be dropped.
        entries = [
            _entry("clone_repo", {"repoName": f"org-{i}/repo-name-{i}"})
            for i in range(40)
        ]
        receipt = build_consulted_receipt(entries, "deadbeef")
        blob = json.dumps(receipt, ensure_ascii=False).encode("utf-8")
        assert len(blob) <= _MAX_RECEIPT_BYTES

    def test_oversized_payload_drops_whole_trailing_requests(self) -> None:
        # Construct entries whose rendered lines are individually well under
        # the 4,096-code-point per-line bound (arguments are clipped to 80
        # characters upstream by ``analyse_trace``, BF-774) but numerous and
        # wide enough in aggregate -- 6 arguments per call, the maximum --
        # to force the 16 KiB response-level trim.
        long_value = "x" * 80
        entries = [
            _entry(
                "clone_repo",
                {f"argument_{j}": f"{long_value}-{i}-{j}" for j in range(6)},
            )
            for i in range(40)
        ]
        receipt = build_consulted_receipt(entries, "deadbeef")
        blob = json.dumps(receipt, ensure_ascii=False).encode("utf-8")
        assert len(blob) <= _MAX_RECEIPT_BYTES
        assert receipt["truncated"] is True
        assert receipt["requests_omitted"] > 0
        assert (
            receipt["requests_total"]
            == len(receipt["requests"]) + receipt["requests_omitted"]
        )
        assert len(receipt["requests"]) < 40
        # Whole lines are dropped from the tail, never a partial/mid-line cut.
        for line in receipt["requests"]:
            assert line.startswith("clone_repo(")


class TestNoticeString:
    def test_notice_is_a_fixed_nonempty_string(self) -> None:
        entries = [_entry("tool", {})]
        first = build_consulted_receipt(entries, "deadbeef")["notice"]
        second = build_consulted_receipt([], "cafebabe")["notice"]
        assert first == second
        assert isinstance(first, str) and len(first) > 0

    def test_notice_mentions_redaction_and_external_effects(self) -> None:
        notice = build_consulted_receipt([], "deadbeef")["notice"].lower()
        assert "redact" in notice
        assert "external effect" in notice or "external" in notice
        assert "40 lines" in notice and "16 kib" in notice
        assert "userinfo" in notice and "query" in notice and "fragment" in notice
