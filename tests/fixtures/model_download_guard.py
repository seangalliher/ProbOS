"""BF-919 (#1632) M2: the test suite downloads no embedding model into the home directory.

Chroma's default ONNX embedding function, which ``DefaultEmbeddingFunction`` calls, downloads its 83 MB model from S3
into its class attribute ``DOWNLOAD_PATH`` -- ``~/.cache/chroma/onnx_models/all-MiniLM-L6-v2``, computed when chromadb
is imported -- on first use, whatever ``HF_HUB_OFFLINE`` says. ``get_embedding_function`` reaches it only when the
sentence-transformers model does not load, which under the suite's ``HF_HUB_OFFLINE=1`` means that model is not
cached. So a machine without it downloaded Chroma's model into the home directory on its first boot.

``tests/conftest.py`` enters ``model_download_guard`` once per session in every xdist worker. Chroma counts its model
present only when every file in ``MODEL_FILES`` exists under ``<DOWNLOAD_PATH>/onnx``, and otherwise downloads and
extracts its archive there (BF-919 amendment A3). ``model_on_disk`` applies that rule, requiring regular files, so it
never counts a model Chroma would fetch. When it holds, ``DOWNLOAD_PATH`` keeps its value (the cache is read, never
fetched). When it does not -- no cache, an interrupted extraction, or an archive never extracted -- ``DOWNLOAD_PATH``
is pointed beneath a file: ``os.makedirs`` cannot create a directory under a file, so the download step fails before
it creates, fetches or extracts anything, its error names the file, and ``get_embedding_function`` takes its keyword
fallback, the path CI selects with ``PROBOS_EMBEDDINGS=local``. Only public class attributes are touched, as AD-1347
S1's tests do.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2

SINKHOLE_NAME = "BF-919-the-test-suite-downloads-no-embedding-model"
# The files Chroma requires before it skips its download (``ONNXMiniLM_L6_V2._download_model_if_not_exists``). Chroma
# keeps them in a local variable, so they are copied here; test_c8 fails when the installed Chroma's list differs.
MODEL_FILES = (
    "config.json",
    "model.onnx",
    "special_tokens_map.json",
    "tokenizer_config.json",
    "tokenizer.json",
    "vocab.txt",
)


def model_on_disk(original: Path, extracted: str) -> bool:
    """True only when every file Chroma requires is under ``<original>/<extracted>``: then Chroma fetches nothing."""
    folder = original / extracted
    return all((folder / name).is_file() for name in MODEL_FILES)


def download_path_for(original: Path, extracted: str, sinkhole: Path) -> Path:
    """Chroma's own directory when its extracted model is on disk, otherwise the same name beneath ``sinkhole``."""
    if model_on_disk(original, extracted):
        return original
    return sinkhole / original.name


@contextmanager
def model_download_guard(sinkhole: Path) -> Iterator[Path]:
    """Write ``sinkhole``, point Chroma's download directory beneath it if no model is on disk, restore on exit."""
    original_value = ONNXMiniLM_L6_V2.DOWNLOAD_PATH
    sinkhole.write_text("BF-919 (#1632): the test suite downloads no embedding model.\n", encoding="utf-8")
    chosen = download_path_for(Path(original_value), ONNXMiniLM_L6_V2.EXTRACTED_FOLDER_NAME, sinkhole)
    ONNXMiniLM_L6_V2.DOWNLOAD_PATH = chosen
    try:
        yield chosen
    finally:
        ONNXMiniLM_L6_V2.DOWNLOAD_PATH = original_value
