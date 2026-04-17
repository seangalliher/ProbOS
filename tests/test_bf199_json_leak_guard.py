"""BF-199: Ward Room JSON Leak Guard — Tests."""

from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from probos.utils.text_sanitize import sanitize_ward_room_text


# ---------------------------------------------------------------------------
# Unit tests for sanitize_ward_room_text
# ---------------------------------------------------------------------------

class TestSanitizeWardRoomText:

    def test_plain_text_passthrough(self):
        """Test 1: Normal text returns unchanged."""
        text = "I've noticed an interesting pattern in the system logs."
        assert sanitize_ward_room_text(text) == text

    def test_reflect_json_extracts_output(self):
        """Test 2: Reflect JSON → extract 'output' field."""
        leaked = json.dumps({
            "output": "I've noticed an interesting pattern in the system logs.",
            "revised": True,
            "reflection": "The observation about latency is worth sharing.",
        })
        result = sanitize_ward_room_text(leaked)
        assert result == "I've noticed an interesting pattern in the system logs."

    def test_evaluate_json_suppressed(self):
        """Test 3: Evaluate JSON → empty string (not human-readable)."""
        leaked = json.dumps({
            "pass": True,
            "score": 0.8,
            "criteria": {"relevance": 0.9},
            "recommendation": "approve",
        })
        result = sanitize_ward_room_text(leaked)
        assert result == ""

    def test_non_chain_json_passthrough(self):
        """Test 4: Non-chain JSON returns unchanged."""
        text = '{"foo": "bar", "baz": 42}'
        assert sanitize_ward_room_text(text) == text

    def test_malformed_json_passthrough(self):
        """Test 5: Malformed JSON returns unchanged."""
        text = '{"output": broken json here'
        assert sanitize_ward_room_text(text) == text

    def test_empty_output_field(self):
        """Test 6: Empty output field → keep original (no empty post)."""
        leaked = json.dumps({"output": "", "revised": False})
        assert sanitize_ward_room_text(leaked) == leaked

    def test_nested_json_in_output(self):
        """Test 7: Output field containing JSON-like text preserved."""
        inner = 'The config shows {"key": "value"} which is expected.'
        leaked = json.dumps({
            "output": inner,
            "revised": False,
            "reflection": "Noted.",
        })
        result = sanitize_ward_room_text(leaked)
        assert result == inner

    def test_whitespace_prefix(self):
        """Test 8: Leading whitespace before JSON still detected."""
        leaked = '  {"output": "Hello world", "revised": true, "reflection": "ok"}'
        result = sanitize_ward_room_text(leaked)
        assert result == "Hello world"

    def test_non_dict_json_passthrough(self):
        """Array JSON returns unchanged."""
        text = '["output", "something"]'
        assert sanitize_ward_room_text(text) == text

    def test_output_with_only_whitespace(self):
        """Output field with only whitespace → keep original."""
        leaked = json.dumps({"output": "   ", "revised": False})
        assert sanitize_ward_room_text(leaked) == leaked
