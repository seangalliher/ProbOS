"""BF-313 — smoke tests that catch ABI breakage in the ML stack.

Wave 174 shipped facenet-pytorch via ``pip install --no-deps`` (because the
live runtime's torch ``_C.pyd`` file lock blocked a clean upgrade). The
resulting venv had torch 2.2.2 alongside transformers >=4.46, which needs
torch >=2.4. The mismatch broke transformers/integrations/accelerate.py at
``nn.Module`` -- ``nn`` is only imported in the >=2.4 path. ChromaDB tried
to load its ``sentence_transformer`` embedding function on the first query
or upsert and raised ``ValueError: name 'nn' is not defined``, taking down
EVERY episodic recall in the runtime.

These tests sit at the test-time boundary: if the venv ever lands a
configuration where transformers/sentence_transformers can't import, the
suite fails loud BEFORE Captain's runtime boots.
"""
from __future__ import annotations

import pytest


def test_bf313_torch_version_meets_transformers_minimum() -> None:
    """Pinned via pyproject.toml -- ``torch>=2.4``.

    If a future install/sync ever lands a torch <2.4 again, this test
    fails before transformers gets a chance to break at module load time.
    """
    import torch
    parts = torch.__version__.split("+", 1)[0].split(".")
    major, minor = int(parts[0]), int(parts[1])
    assert (major, minor) >= (2, 4), (
        f"BF-313: torch {torch.__version__} predates transformers>=4.46 ABI; "
        "any sentence-transformers-using path (chroma embeddings, episodic "
        "recall) will fail with 'name nn is not defined'. uv sync should "
        "have pulled torch>=2.4 per the pyproject.toml pin."
    )


def test_bf313_transformers_torch_detection_succeeds() -> None:
    """If transformers detected torch correctly at import time, the
    ``Disabling PyTorch because PyTorch >= 2.4 is required`` warning is
    NOT emitted and ``transformers.utils.is_torch_available()`` is True.
    """
    import transformers
    is_torch_available = getattr(transformers.utils, "is_torch_available", None)
    if is_torch_available is None:
        pytest.skip("transformers.utils.is_torch_available not present in this version")
    assert is_torch_available(), (
        "BF-313: transformers thinks PyTorch is unavailable. Either the "
        "installed torch is too old (<2.4) or the import path failed at "
        "load time. Look upstream for 'Disabling PyTorch' warnings during "
        "test collection."
    )


def test_bf313_sentence_transformers_imports_end_to_end() -> None:
    """End-to-end import chain that ChromaDB uses for its default embedding
    function. The Wave 174 regression bombed inside this chain at the
    transformers.integrations.accelerate module.
    """
    # The cascade BF-313 broke. If ANY of these raise, episodic recall is
    # dead in production.
    from sentence_transformers import SentenceTransformer  # noqa: F401
    from sentence_transformers.base.model import BaseModel  # noqa: F401
    from transformers.integrations.peft import PeftAdapterMixin  # noqa: F401
    # Don't actually instantiate a model -- that downloads weights. Just
    # confirm the import surface is sound; downloads are integration territory.
