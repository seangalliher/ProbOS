"""AD-1143 — Nooplex §8.3 with/without-Σ ablation harness.

Tests and fixtures only. Nothing in this package is imported by production
code and nothing here modifies ``src/probos/**``.

Collection is gated by ``tests/ablation/conftest.py`` (see DD-1): with
``PROBOS_ABLATION`` unset the ``test_*.py`` modules in this package are never
opened by pytest.
"""
