"""Tests for BF-106: DreamingEngine dependency injection."""

from __future__ import annotations

from unittest.mock import MagicMock

from probos.cognitive.dreaming import DreamingEngine


# ---------------------------------------------------------------------------
# Tests: BF-106 — DreamingEngine dependency injection
# ---------------------------------------------------------------------------


class TestDreamingEngineDI:
    """BF-106: Verify DreamingEngine uses setters instead of monkey-patching."""

    def _make_engine(self, **kwargs):
        """Create a minimal DreamingEngine with mocked required args."""
        return DreamingEngine(
            router=MagicMock(),
            trust_network=MagicMock(),
            episodic_memory=MagicMock(),
            config=MagicMock(),
            **kwargs,
        )

    def test_set_ward_room(self):
        """BF-106: set_ward_room sets _ward_room."""
        engine = self._make_engine()
        assert engine._ward_room is None

        mock_wr = MagicMock()
        engine.set_ward_room(mock_wr)
        assert engine._ward_room is mock_wr

    def test_set_get_department(self):
        """BF-106: set_get_department sets _get_department."""
        engine = self._make_engine()
        assert engine._get_department is None

        dept_fn = lambda aid: "science"
        engine.set_get_department(dept_fn)
        assert engine._get_department is dept_fn

    def test_set_records_store(self):
        """BF-106: set_records_store sets _records_store."""
        engine = self._make_engine()
        assert engine._records_store is None

        mock_rs = MagicMock()
        engine.set_records_store(mock_rs)
        assert engine._records_store is mock_rs

    def test_records_store_via_constructor(self):
        """BF-106: records_store can be passed via constructor."""
        mock_rs = MagicMock()
        engine = self._make_engine(records_store=mock_rs)
        assert engine._records_store is mock_rs

    def test_ward_room_via_constructor(self):
        """BF-106: ward_room can be passed via constructor."""
        mock_wr = MagicMock()
        engine = self._make_engine(ward_room=mock_wr)
        assert engine._ward_room is mock_wr

    def test_defaults_are_none(self):
        """BF-106: All three late-bind attrs default to None."""
        engine = self._make_engine()
        assert engine._ward_room is None
        assert engine._get_department is None
        assert engine._records_store is None

    def test_set_records_store_noop_if_already_set(self):
        """BF-106: set_records_store is no-op if constructor-injected."""
        mock_rs = MagicMock()
        engine = self._make_engine(records_store=mock_rs)
        other_rs = MagicMock()
        engine.set_records_store(other_rs)
        assert engine._records_store is mock_rs  # Original preserved

    def test_finalize_uses_setters_not_private_attrs(self):
        """BF-106: finalize.py should not write to private _ward_room/_get_department."""
        import inspect
        from probos.startup import finalize
        src = inspect.getsource(finalize)
        assert "engine._ward_room =" not in src
        assert "engine._get_department =" not in src
        assert "engine._records_store =" not in src
