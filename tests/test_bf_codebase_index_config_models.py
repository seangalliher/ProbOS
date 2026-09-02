"""BF: ``CodebaseIndex`` lost every model AD-1270e2 moved out of ``config.py``.

``_extract_config_schema()`` read ``src/probos/config.py`` and nothing else. The
AD-1270e2 waves moved config models into ``probos.config_models``, and the
facade re-exports them -- so every *import* consumer was unaffected and the
"pure move" claim held for them. This consumer does not import; it reads source
text. It went quietly blind, and shipped that way in batches 1 through 3 before
an adversarial review of batch 4 caught it.

These tests assert against the **real** index and the **real** skill, not a
stub, because the defect was invisible to every identity- and import-level
check that already existed.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from probos.cognitive.codebase_index import CodebaseIndex

_SOURCE_ROOT = Path(__file__).resolve().parent.parent / "src" / "probos"
_CONFIG_MODELS = _SOURCE_ROOT / "config_models"


@pytest.fixture(scope="module")
def index() -> CodebaseIndex:
    built = CodebaseIndex(_SOURCE_ROOT)
    built.build()
    return built


def _declared_models(path: Path) -> set[str]:
    """Every ``BaseModel`` subclass declared at module level in ``path``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        bases = {ast.unparse(base) for base in node.bases}
        if "BaseModel" not in bases:
            continue
        if any(
            isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name)
            for item in node.body
        ):
            names.add(node.name)
    return names


def test_the_extraction_package_is_actually_populated() -> None:
    """Premise guard: if the package were empty these tests prove nothing."""
    modules = sorted(p.name for p in _CONFIG_MODELS.glob("*.py"))

    assert "__init__.py" in modules
    assert len([m for m in modules if m != "__init__.py"]) >= 4

    declared = set()
    for module in _CONFIG_MODELS.glob("*.py"):
        if module.name != "__init__.py":
            declared |= _declared_models(module)

    assert len(declared) >= 50


def test_a_never_moved_model_is_indexed() -> None:
    """Control. If this failed, a later failure would not mean what it says."""
    built = CodebaseIndex(_SOURCE_ROOT)
    built.build()

    assert "CognitiveConfig" in built.get_config_schema()


def test_every_extracted_model_is_present_in_the_config_schema(
    index: CodebaseIndex,
) -> None:
    """The regression itself, stated over the whole package rather than a list.

    A hand-written list of names would go stale the moment a fifth batch lands;
    deriving the expectation from the package means the next batch is covered
    without editing this file.
    """
    schema = index.get_config_schema()

    expected: set[str] = set()
    for module in sorted(_CONFIG_MODELS.glob("*.py")):
        if module.name == "__init__.py":
            continue
        expected |= _declared_models(module)

    missing = sorted(name for name in expected if name not in schema)

    assert missing == []


@pytest.mark.parametrize(
    ("module_name", "sample"),
    [
        ("core.py", "PoolConfig"),
        ("cognition.py", "AttentionConfig"),
        ("experience.py", "DesktopConfig"),
        ("integrations.py", "CredentialVaultConfig"),
    ],
)
def test_each_batch_is_represented(
    index: CodebaseIndex, module_name: str, sample: str
) -> None:
    """One named model per shipped batch, so a partial fix cannot pass."""
    module = _CONFIG_MODELS / module_name
    if not module.is_file():
        pytest.skip(f"{module_name} not present on this tree")

    assert sample in _declared_models(module)
    assert sample in index.get_config_schema()


def test_indexed_fields_carry_type_and_default(index: CodebaseIndex) -> None:
    """Presence is not enough -- the values must be usable, not empty stubs."""
    fields = index.get_config_schema()["PoolConfig"]

    assert fields
    assert all(" = " in rendered for rendered in fields.values())


def test_the_facade_module_is_still_scanned(index: CodebaseIndex) -> None:
    """Widening the scan must not have replaced ``config.py`` with the package."""
    schema = index.get_config_schema()
    facade_models = _declared_models(_SOURCE_ROOT / "config.py")

    assert facade_models
    missing = sorted(name for name in facade_models if name not in schema)

    assert missing == []


def test_a_syntactically_broken_module_does_not_lose_the_others(
    tmp_path: Path,
) -> None:
    """One bad file must degrade to skipping itself, not abandon the scan.

    The pre-fix code ``return``ed on ``SyntaxError``; the loop must ``continue``.
    """
    root = tmp_path / "probos"
    (root / "config_models").mkdir(parents=True)
    (root / "config.py").write_text(
        "from pydantic import BaseModel\n\n\n"
        "class FacadeModel(BaseModel):\n    a: int = 1\n",
        encoding="utf-8",
    )
    (root / "config_models" / "broken.py").write_text(
        "class Nope(BaseModel:\n", encoding="utf-8"
    )
    (root / "config_models" / "good.py").write_text(
        "from pydantic import BaseModel\n\n\n"
        "class GoodModel(BaseModel):\n    b: str = 'x'\n",
        encoding="utf-8",
    )

    built = CodebaseIndex(root)
    built.build()
    schema = built.get_config_schema()

    assert "FacadeModel" in schema
    assert "GoodModel" in schema
    assert "Nope" not in schema


def test_a_missing_facade_file_does_not_abort_the_package_scan(
    tmp_path: Path,
) -> None:
    """``config.py`` absent must not short-circuit ``config_models/``."""
    root = tmp_path / "probos"
    (root / "config_models").mkdir(parents=True)
    (root / "config_models" / "only.py").write_text(
        "from pydantic import BaseModel\n\n\n"
        "class OnlyModel(BaseModel):\n    c: bool = True\n",
        encoding="utf-8",
    )

    built = CodebaseIndex(root)
    built.build()

    assert "OnlyModel" in built.get_config_schema()


def test_a_duplicate_name_keeps_the_facade_definition_and_warns(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """The schema is keyed by bare class name across files now.

    Before the widened scan only one file was read, so a collision was
    impossible. Now it is, and a silent overwrite would change what the system
    reports about itself with nothing in the log to explain it. ``config.py``
    is the facade, so it wins; the loser is named.
    """
    root = tmp_path / "probos"
    (root / "config_models").mkdir(parents=True)
    (root / "config.py").write_text(
        "from pydantic import BaseModel\n\n\n"
        "class Clashing(BaseModel):\n    from_facade: int = 1\n",
        encoding="utf-8",
    )
    (root / "config_models" / "later.py").write_text(
        "from pydantic import BaseModel\n\n\n"
        "class Clashing(BaseModel):\n    from_package: int = 2\n",
        encoding="utf-8",
    )

    built = CodebaseIndex(root)
    with caplog.at_level("WARNING"):
        built.build()

    assert list(built.get_config_schema()["Clashing"]) == ["from_facade"]
    assert "Clashing" in caplog.text
    assert "later.py" in caplog.text


def test_an_unparseable_module_is_named_in_the_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Degrading silently is how the original defect stayed invisible."""
    root = tmp_path / "probos"
    (root / "config_models").mkdir(parents=True)
    (root / "config.py").write_text(
        "from pydantic import BaseModel\n\n\n"
        "class Fine(BaseModel):\n    a: int = 1\n",
        encoding="utf-8",
    )
    (root / "config_models" / "broken.py").write_text(
        "class Nope(BaseModel:\n", encoding="utf-8"
    )

    built = CodebaseIndex(root)
    with caplog.at_level("WARNING"):
        built.build()

    assert "Fine" in built.get_config_schema()
    assert "broken.py" in caplog.text
