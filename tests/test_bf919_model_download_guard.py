"""BF-919 (#1632) M2: the test suite downloads no embedding model into the home directory.

``tests/conftest.py`` enters ``tests/fixtures/model_download_guard.py`` for the session: when Chroma's ONNX model is
not already on disk, Chroma's download directory is pointed beneath a file, so the download step fails before it
creates or fetches anything and ``get_embedding_function`` takes its keyword fallback (what CI's
``PROBOS_EMBEDDINGS=local`` gives). A model already on disk is read as before, so real-model tests still run where
it is cached. The tests run in file order and the mutation campaign stops at the first failure: C1 and C2 kill a
mutated path rule before C3 reaches Chroma, and C3 also points every proxy at a closed port. C6 pins AD-822's store
helper (amendment A2): with no model on disk a bare Chroma add raises, and the helper, which passes its own
embeddings, does not. C7 pins amendment A3: a partial cache is no model, so Chroma's real download step meets the
sinkhole and fetches nothing (``httpx.stream`` is recorded). C8 fails when the installed Chroma's list of required
files differs from ``MODEL_FILES``.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from pathlib import Path

import chromadb
import chromadb.utils.embedding_functions as chroma_functions
import httpx
import pytest
from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2

import probos.knowledge.embeddings as embeddings_module
from tests.fixtures.model_download_guard import (
    MODEL_FILES,
    SINKHOLE_NAME,
    download_path_for,
    model_download_guard,
    model_on_disk,
)
from tests.test_ad822_episodic_health import _build_healthy_store

_CLOSED_PORT = "http://127.0.0.1:9"
_MODEL = "all-MiniLM-L6-v2"


def _sinkhole(directory: Path) -> Path:
    directory.mkdir(parents=True)
    sinkhole = directory / SINKHOLE_NAME
    sinkhole.write_text("BF-919 test\n", encoding="utf-8")
    return sinkhole


def _no_sentence_transformer(*args: object, **kwargs: object) -> None:
    raise ImportError("BF-919 test: the sentence-transformers model is unavailable")


def _cache(root: Path, names: list[str] | tuple[str, ...]) -> Path:
    """Chroma's model directory under ``root``, holding an empty file for each of ``names`` in its ``onnx`` folder."""
    original = root / _MODEL
    (original / "onnx").mkdir(parents=True)
    for name in names:
        (original / "onnx" / name).write_bytes(b"")
    return original


def _string_literals(node: ast.AST) -> list[str]:
    """The strings of a list or tuple literal made only of string constants, otherwise an empty list."""
    if not isinstance(node, (ast.List, ast.Tuple)):
        return []
    strings = [item.value for item in node.elts if isinstance(item, ast.Constant) and isinstance(item.value, str)]
    return strings if len(strings) == len(node.elts) else []


def test_c1_with_no_model_on_disk_the_download_directory_is_beneath_the_sinkhole(tmp_path: Path) -> None:
    original = tmp_path / "home" / ".cache" / "chroma" / "onnx_models" / _MODEL
    sinkhole = _sinkhole(tmp_path / "guard")
    assert download_path_for(original, "onnx", sinkhole) == sinkhole / _MODEL
    assert not (tmp_path / "home").exists(), "deciding creates nothing"


def test_c2_with_the_model_on_disk_chromas_own_directory_is_kept(tmp_path: Path) -> None:
    original = _cache(tmp_path / "cache", MODEL_FILES)
    assert model_on_disk(original, "onnx"), "every file Chroma requires is on disk"
    assert download_path_for(original, "onnx", _sinkhole(tmp_path / "guard")) == original


def test_c3_with_no_model_on_disk_a_default_embedding_falls_back_and_creates_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = tmp_path / "home" / ".cache" / "chroma" / "onnx_models" / _MODEL
    sinkhole = _sinkhole(tmp_path / "guard")
    chosen = download_path_for(original, ONNXMiniLM_L6_V2.EXTRACTED_FOLDER_NAME, sinkhole)
    monkeypatch.setattr(ONNXMiniLM_L6_V2, "DOWNLOAD_PATH", chosen)
    monkeypatch.setattr(chroma_functions, "SentenceTransformerEmbeddingFunction", _no_sentence_transformer)
    monkeypatch.delenv("PROBOS_EMBEDDINGS", raising=False)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(name, _CLOSED_PORT)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.setattr(embeddings_module, "_embedding_available", None)
    monkeypatch.setattr(embeddings_module, "_embedding_fn", None)

    assert embeddings_module.get_embedding_function() is None, "both real backends fail, so the keyword fallback"
    assert not (tmp_path / "home").exists(), "nothing was created where Chroma would download"
    assert [path.name for path in sinkhole.parent.iterdir()] == [SINKHOLE_NAME], "nor beside the sinkhole"


def test_c4_the_guard_writes_its_sinkhole_points_chroma_beneath_it_and_restores_chromas_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    absent = tmp_path / "home" / ".cache" / "chroma" / "onnx_models" / _MODEL
    monkeypatch.setattr(ONNXMiniLM_L6_V2, "DOWNLOAD_PATH", absent)
    sinkhole = tmp_path / SINKHOLE_NAME
    with model_download_guard(sinkhole) as chosen:
        assert sinkhole.is_file(), "the guard writes the file the download directory sits beneath"
        assert chosen == sinkhole / _MODEL
        assert ONNXMiniLM_L6_V2.DOWNLOAD_PATH == chosen
    assert ONNXMiniLM_L6_V2.DOWNLOAD_PATH == absent, "Chroma's directory is restored on exit"
    assert not (tmp_path / "home").exists()


def test_c5_conftest_installed_the_guard_for_this_worker(_bf919_no_model_download: Path) -> None:
    assert ONNXMiniLM_L6_V2.DOWNLOAD_PATH == _bf919_no_model_download
    in_place = model_on_disk(_bf919_no_model_download, ONNXMiniLM_L6_V2.EXTRACTED_FOLDER_NAME)
    beneath_sinkhole = _bf919_no_model_download.parent.name == SINKHOLE_NAME
    assert in_place != beneath_sinkhole, "the whole model in place, or the path beneath the sinkhole"


def test_c6_with_no_model_on_disk_a_bare_chroma_add_raises_and_ad822s_store_needs_no_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    sinkhole = _sinkhole(tmp_path / "guard")
    monkeypatch.setattr(ONNXMiniLM_L6_V2, "DOWNLOAD_PATH", sinkhole / _MODEL)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(name, _CLOSED_PORT)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)

    bare = chromadb.PersistentClient(path=str(tmp_path / "bare"))
    with pytest.raises(OSError, match=SINKHOLE_NAME):
        bare.get_or_create_collection(name="episodes").add(
            ids=["bf919-c6"], documents=["a bare add embeds with Chroma's default function"],
        )
    del bare

    _build_healthy_store(tmp_path / "ad822")
    assert (tmp_path / "ad822" / "chroma.sqlite3").is_file(), "AD-822's store was built with no model on disk"
    assert [path.name for path in sinkhole.parent.iterdir()] == [SINKHOLE_NAME], "nothing beside the sinkhole"


def test_c7_a_partial_cache_is_no_model_so_chroma_fetches_nothing_and_the_cache_is_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    sinkhole = _sinkhole(tmp_path / "guard")
    for missing in MODEL_FILES:
        five = _cache(tmp_path / "five" / missing, [name for name in MODEL_FILES if name != missing])
        assert not model_on_disk(five, "onnx"), missing
        assert download_path_for(five, "onnx", sinkhole) == sinkhole / _MODEL, missing

    partial = _cache(tmp_path / "home" / ".cache" / "chroma" / "onnx_models", ["model.onnx"])
    before = sorted(path.relative_to(tmp_path).as_posix() for path in (tmp_path / "home").rglob("*"))
    chosen = download_path_for(partial, ONNXMiniLM_L6_V2.EXTRACTED_FOLDER_NAME, sinkhole)
    assert chosen == sinkhole / _MODEL, "a cache holding only model.onnx is not Chroma's model"
    monkeypatch.setattr(ONNXMiniLM_L6_V2, "DOWNLOAD_PATH", chosen)
    attempts: list[tuple[object, ...]] = []

    def _record_download(*args: object, **kwargs: object) -> None:
        attempts.append(args)
        raise RuntimeError("BF-919 test: Chroma attempted a download")

    monkeypatch.setattr(httpx, "stream", _record_download)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(name, _CLOSED_PORT)
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)

    bare = chromadb.PersistentClient(path=str(tmp_path / "bare"))
    with pytest.raises(OSError, match=SINKHOLE_NAME):
        bare.get_or_create_collection(name="episodes").add(
            ids=["bf919-c7"], documents=["a partial cache is not Chroma's model"],
        )
    del bare
    assert attempts == [], "Chroma's download step fetched nothing"
    after = sorted(path.relative_to(tmp_path).as_posix() for path in (tmp_path / "home").rglob("*"))
    assert after == before, "the partial cache was neither completed nor extracted into"
    assert [path.name for path in sinkhole.parent.iterdir()] == [SINKHOLE_NAME], "nothing beside the sinkhole"


def test_c8_the_files_counted_as_the_model_are_chromas_own_list() -> None:
    # Reads the source of a private third-party method, never calls it: Chroma keeps the list in a local variable.
    try:
        source = inspect.getsource(ONNXMiniLM_L6_V2._download_model_if_not_exists)
    except (AttributeError, OSError, TypeError) as error:
        pytest.fail(f"BF-919: cannot read Chroma's model check ({error}); re-derive MODEL_FILES by hand", pytrace=False)
    tree = ast.parse(textwrap.dedent(source))
    literals = [strings for strings in map(_string_literals, ast.walk(tree)) if "model.onnx" in strings]
    assert len(literals) == 1, (
        "BF-919: Chroma's model check no longer holds one literal list of its required files; re-derive MODEL_FILES "
        "in tests/fixtures/model_download_guard.py from the installed chromadb"
    )
    assert sorted(literals[0]) == sorted(MODEL_FILES), (
        f"BF-919: the installed Chroma requires {sorted(literals[0])}; update MODEL_FILES, or the guard keeps a "
        "partial cache that Chroma downloads into"
    )
