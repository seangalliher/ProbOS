"""AD-797 (Wave 197): tests for ``cognitive/dm/artifact_extractor``."""

from __future__ import annotations

import pytest

from probos.cognitive.dm.artifact_extractor import (
    ExtractedArtifact,
    extract_artifacts,
    _to_office_bytes,
)


_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_to_office_bytes_renders_real_docx_bf643() -> None:
    out = _to_office_bytes(_DOCX, b"What is AI?\n\nAI is great.")
    assert out[:4] == b"PK\x03\x04"  # real OOXML zip, not plain text
    assert len(out) > 1000


def test_to_office_bytes_passes_non_docx_through_bf643() -> None:
    assert _to_office_bytes("text/markdown", b"hello") == b"hello"


def test_libreoffice_backend_degrades_when_absent_bf646() -> None:
    # No soffice on CI -> degrades to python-docx, still a real PK docx.
    out = _to_office_bytes(_DOCX, b"Title\n\nBody.", "libreoffice", "/nope/soffice")
    assert out[:4] == b"PK\x03\x04"


def test_extracts_explicit_tag() -> None:
    body = (
        "Here is your list:\n"
        '<artifact name="grocery.md" mime="text/markdown">\n'
        "- Eggs\n- Milk\n"
        "</artifact>\n"
        "Done."
    )
    out = extract_artifacts(body, fenced_threshold_lines=40)
    assert len(out) == 1
    a = out[0]
    assert a.name == "grocery.md"
    assert a.mime == "text/markdown"
    assert a.content == b"- Eggs\n- Milk"
    assert a.line_count == 2


def test_extracts_fenced_code_above_threshold() -> None:
    code_lines = [f"x_{i} = {i}" for i in range(60)]
    body = "Here is the file:\n```python\n" + "\n".join(code_lines) + "\n```\n"
    out = extract_artifacts(body, fenced_threshold_lines=40)
    assert len(out) == 1
    a = out[0]
    assert a.name == "artifact-1.py"
    assert a.mime == "text/x-python"
    assert a.line_count == 60


def test_skips_short_fenced_code() -> None:
    body = "Sample:\n```python\nx = 1\ny = 2\n```\n"
    out = extract_artifacts(body, fenced_threshold_lines=40)
    assert out == []


def test_filename_comment_derives_name() -> None:
    code_lines = ["# filename: helper.py"] + [f"a = {i}" for i in range(50)]
    body = "Saving:\n```python\n" + "\n".join(code_lines) + "\n```\n"
    out = extract_artifacts(body, fenced_threshold_lines=40)
    assert len(out) == 1
    assert out[0].name == "helper.py"
    assert out[0].mime == "text/x-python"


def test_two_extractors_in_one_reply() -> None:
    code_lines = [f"line_{i}" for i in range(50)]
    body = (
        '<artifact name="a.md" mime="text/markdown">\n'
        "Hello\n"
        "</artifact>\n"
        "And here is some code:\n"
        "```python\n"
        + "\n".join(code_lines)
        + "\n```\n"
    )
    out = extract_artifacts(body, fenced_threshold_lines=40)
    assert len(out) == 2
    # Source-position order: explicit tag first, fenced block second.
    assert out[0].name == "a.md"
    assert out[1].name == "artifact-1.py"
    assert out[0].source_span[1] <= out[1].source_span[0]


def test_name_sanitization() -> None:
    # Path-traversal attempt: ../../etc/passwd
    body = (
        '<artifact name="../../etc/passwd" mime="text/plain">\n'
        "secret\n"
        "</artifact>\n"
    )
    out = extract_artifacts(body)
    # Sanitized: directory components stripped, name is the safe basename.
    assert len(out) == 1
    assert "/" not in out[0].name
    assert ".." not in out[0].name
    assert out[0].name == "passwd"


def test_empty_response_text_returns_empty() -> None:
    assert extract_artifacts("") == []


def test_existing_unnamed_count_offset() -> None:
    """Repeated extractions on the same thread continue numbering."""
    code_lines = [f"x = {i}" for i in range(50)]
    body = "```python\n" + "\n".join(code_lines) + "\n```"
    out = extract_artifacts(body, fenced_threshold_lines=40, existing_unnamed_count=3)
    assert out[0].name == "artifact-4.py"


def test_invalid_artifact_tag_missing_mime_is_skipped() -> None:
    body = '<artifact name="x.md">Hello</artifact>'
    out = extract_artifacts(body)
    assert out == []
