"""AD-1256: the store declaration inventory, and proof its checker can fail.

An inventory nobody can fail is documentation. These tests exist to prove the
opposite for every gating rule, in both directions, by **injection** rather than
assertion: each rule gets a case that makes it fire and a case that makes it
stay silent, and the committed tree is asserted to produce zero errors with
every rule simultaneously armed.

Two of those injections are performed against the **real** ``src/probos/`` tree
and restored byte-identically in a ``finally``, because a rule that only ever
fires against a synthetic fixture has not been shown to fire against the shape
it actually guards.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest
import yaml

from probos.storage.declarations import (
    BACKUP_DISPOSITIONS,
    RESTORE_DISPOSITIONS,
    UNOWNED_LIFECYCLE,
    StoreCriticality,
    StoreDeclaration,
    StoreRetention,
    declaration_errors,
)
from probos.storage.registry import (
    DECLARATION_MODULES,
    StoreRegistry,
    load_default_store_registry,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "check_store_registry.py"
_REAL_BASELINE = _REPO_ROOT / "docs" / "development" / "store-baseline.yaml"
_REAL_SRC = _REPO_ROOT / "src"

#: Documented gating rules, transcribed from the checker's module docstring.
#: Bound to the implementation by ``test_gating_rules_match_the_documented_set``
#: so a rule cannot be added without documenting it.
_DOCUMENTED_RULES = frozenset(
    {
        "declaration-schema",
        "declaration-duplicate-id",
        "declaration-duplicate-path",
        "declaration-owner-unresolved",
        "declaration-module-unregistered",
        "baseline-schema",
        "undeclared-store",
        "stale-baseline-row",
        "baseline-table-drift",
    }
)


@pytest.fixture(scope="module")
def checker() -> types.ModuleType:
    """Import the checker from its path -- ``scripts/`` is not a package.

    Registered in ``sys.modules`` before execution because the module defines
    dataclasses and, under PEP 563, the dataclass machinery re-reads each
    annotation out of ``sys.modules[cls.__module__]``.
    """
    spec = importlib.util.spec_from_file_location("check_store_registry", _SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_store_registry"] = module
    spec.loader.exec_module(module)
    return module


def _declaration(**overrides: object) -> StoreDeclaration:
    """A valid declaration, with overrides applied."""
    fields: dict[str, object] = {
        "id": "layer.example",
        "title": "Example store",
        "owner_module": "probos.example",
        "owner_symbol": "ExampleStore",
        "canonical_path": "example.db",
        "criticality": StoreCriticality.OPTIONAL,
        "lifecycle_owner": UNOWNED_LIFECYCLE,
        "retention": StoreRetention.BOUNDED,
        "backup": "included",
        "restore": "point-in-time",
    }
    fields.update(overrides)
    return StoreDeclaration(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Synthetic tree
# ---------------------------------------------------------------------------

_DECL_TEMPLATE = """\
from __future__ import annotations

from probos.storage.declarations import (
    StoreCriticality,
    StoreDeclaration,
    StoreRetention,
)

STORE_DECLARATIONS: tuple[StoreDeclaration, ...] = (
{entries}
)
"""


def _entry(
    store_id: str = "layer.alpha",
    owner_module: str = "probos.alpha",
    owner_symbol: str = "AlphaStore",
    canonical_path: str = "alpha.db",
    criticality: str = "StoreCriticality.OPTIONAL",
    retention: str = "StoreRetention.BOUNDED",
    backup: str = '"included"',
    restore: str = '"point-in-time"',
    retention_note: str = '""',
    reconstruction: str = '""',
) -> str:
    return (
        "    StoreDeclaration(\n"
        f'        id="{store_id}",\n'
        '        title="Alpha",\n'
        f'        owner_module="{owner_module}",\n'
        f'        owner_symbol="{owner_symbol}",\n'
        f'        canonical_path="{canonical_path}",\n'
        f"        criticality={criticality},\n"
        '        lifecycle_owner="unowned",\n'
        f"        retention={retention},\n"
        f"        backup={backup},\n"
        f"        restore={restore},\n"
        f"        retention_note={retention_note},\n"
        f"        reconstruction={reconstruction},\n"
        "    ),\n"
    )


def _build_tree(
    root: Path,
    *,
    entries: str | None = None,
    declaration_modules: tuple[str, ...] = ("probos.alpha_pkg.storage_declarations",),
    owner_source: str = "class AlphaStore:\n    pass\n",
    extra_modules: dict[str, str] | None = None,
) -> Path:
    """Materialize a miniature ``src/`` the checker can run against."""
    src = root / "src"
    package = src / "probos"
    (package / "storage").mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "storage" / "__init__.py").write_text("", encoding="utf-8")
    # The real model, so the checker reads the real closed vocabulary.
    (package / "storage" / "declarations.py").write_text(
        (_REAL_SRC / "probos" / "storage" / "declarations.py").read_text(
            encoding="utf-8"
        ),
        encoding="utf-8",
    )
    modules = ",\n".join(f'    "{name}"' for name in declaration_modules)
    (package / "storage" / "registry.py").write_text(
        "DECLARATION_MODULES: tuple[str, ...] = (\n" + modules + ",\n)\n",
        encoding="utf-8",
    )
    (package / "alpha_pkg").mkdir(parents=True, exist_ok=True)
    (package / "alpha_pkg" / "__init__.py").write_text("", encoding="utf-8")
    (package / "alpha_pkg" / "storage_declarations.py").write_text(
        _DECL_TEMPLATE.format(entries=entries if entries is not None else _entry()),
        encoding="utf-8",
    )
    (package / "alpha.py").write_text(owner_source, encoding="utf-8")
    for relative, source in (extra_modules or {}).items():
        target = package / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
    return src


def _write_baseline(path: Path, rows: list[dict[str, object]] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "baseline_id": "test",
                "tracking_issue": 1302,
                "review": {
                    "owner": "AD-1256",
                    "rationale": "test fixture",
                    "review_by": "when empty",
                },
                "undeclared_stores": rows or [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def _rules_fired(errors: list[str]) -> set[str]:
    """The bracketed rule names present in an error list."""
    fired: set[str] = set()
    for message in errors:
        if message.startswith("[") and "]" in message:
            fired.add(message[1 : message.index("]")])
    return fired


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------


def test_criticality_vocabulary_is_closed() -> None:
    assert {member.value for member in StoreCriticality} == {
        "required",
        "optional",
        "feature-gated",
    }


def test_retention_vocabulary_is_closed_and_names_unbounded() -> None:
    """``unbounded`` must be spellable: growth forever is legal in writing."""
    assert {member.value for member in StoreRetention} == {
        "bounded",
        "unbounded",
        "external",
    }


def test_backup_and_restore_vocabularies_are_closed() -> None:
    assert BACKUP_DISPOSITIONS == frozenset({"included", "excluded", "unknown"})
    assert RESTORE_DISPOSITIONS == frozenset(
        {"point-in-time", "reconstructed", "unknown"}
    )


def test_declaration_is_frozen() -> None:
    declaration = _declaration()
    with pytest.raises(dataclasses.FrozenInstanceError):
        declaration.id = "mutated"  # type: ignore[misc]


def test_declaration_to_dict_is_json_safe() -> None:
    payload = _declaration().to_dict()
    assert json.loads(json.dumps(payload)) == payload
    assert payload["criticality"] == "optional"
    assert payload["retention"] == "bounded"


def test_owner_path_joins_module_and_symbol() -> None:
    assert _declaration().owner_path == "probos.example.ExampleStore"


def test_declaration_errors_accepts_a_valid_declaration() -> None:
    """Not-firing: a rule stuck permanently on is a broken checker."""
    assert declaration_errors(_declaration()) == ()


@pytest.mark.parametrize(
    "field_name",
    ["id", "title", "owner_module", "owner_symbol", "canonical_path", "lifecycle_owner"],
)
def test_declaration_errors_flags_every_blank_required_field(field_name: str) -> None:
    problems = declaration_errors(_declaration(**{field_name: "   "}))
    assert any(field_name in problem for problem in problems), problems


def test_declaration_errors_flags_an_unknown_backup_disposition() -> None:
    problems = declaration_errors(_declaration(backup="maybe"))
    assert any("backup" in problem for problem in problems), problems


def test_declaration_errors_flags_an_unknown_restore_disposition() -> None:
    problems = declaration_errors(_declaration(restore="someday"))
    assert any("restore" in problem for problem in problems), problems


def test_declaration_errors_requires_a_note_when_retention_is_unbounded() -> None:
    problems = declaration_errors(
        _declaration(retention=StoreRetention.UNBOUNDED, retention_note="")
    )
    assert any("retention_note" in problem for problem in problems), problems


def test_declaration_errors_requires_a_note_when_retention_is_external() -> None:
    problems = declaration_errors(
        _declaration(retention=StoreRetention.EXTERNAL, retention_note="")
    )
    assert any("retention_note" in problem for problem in problems), problems


def test_declaration_errors_allows_a_bounded_store_without_a_note() -> None:
    """Not-firing: the note is conditional, not universally required."""
    assert declaration_errors(_declaration(retention=StoreRetention.BOUNDED)) == ()


def test_declaration_errors_accepts_unbounded_with_a_note() -> None:
    """Not-firing: unbounded is legal once written down."""
    assert (
        declaration_errors(
            _declaration(
                retention=StoreRetention.UNBOUNDED,
                retention_note="audit trail; deleting history defeats the point",
            )
        )
        == ()
    )


def test_declaration_errors_requires_reconstruction_when_restore_is_reconstructed() -> None:
    problems = declaration_errors(_declaration(restore="reconstructed"))
    assert any("reconstruction" in problem for problem in problems), problems


def test_declaration_errors_flags_reconstruction_without_reconstructed_restore() -> None:
    problems = declaration_errors(_declaration(reconstruction="replay the log"))
    assert any("reconstruction" in problem for problem in problems), problems


def test_declaration_errors_accumulates_every_problem() -> None:
    """Accumulate, never stop at the first: one pass must report all faults."""
    problems = declaration_errors(
        _declaration(id="", backup="nope", restore="nope", canonical_path="")
    )
    assert len(problems) >= 4, problems


def test_declaration_errors_returns_rather_than_raises() -> None:
    """A raise in ``__post_init__`` would make a whole layer unimportable."""
    assert isinstance(declaration_errors(_declaration(id="")), tuple)


# ---------------------------------------------------------------------------
# The registry
# ---------------------------------------------------------------------------


def test_registry_registers_and_resolves() -> None:
    registry = StoreRegistry()
    registry.register(_declaration())
    assert registry.get("layer.example") is not None
    assert registry.get("layer.missing") is None


def test_registry_rejects_a_duplicate_id() -> None:
    registry = StoreRegistry()
    registry.register(_declaration())
    with pytest.raises(ValueError, match="duplicate store declaration id"):
        registry.register(_declaration(canonical_path="other.db"))


def test_registry_rejects_a_duplicate_canonical_path() -> None:
    """A store has exactly one canonical spelling."""
    registry = StoreRegistry()
    registry.register(_declaration())
    with pytest.raises(ValueError, match="duplicate canonical_path"):
        registry.register(_declaration(id="layer.other"))


def test_registry_returns_declarations_sorted_by_id() -> None:
    registry = StoreRegistry()
    registry.register(_declaration(id="z.last", canonical_path="z.db"))
    registry.register(_declaration(id="a.first", canonical_path="a.db"))
    assert [item.id for item in registry.declarations()] == ["a.first", "z.last"]


def test_registry_resolves_by_canonical_path() -> None:
    registry = StoreRegistry()
    registry.register(_declaration())
    assert registry.by_canonical_path("example.db") is not None
    assert registry.by_canonical_path("absent.db") is None


def test_registry_reports_owner_modules() -> None:
    registry = StoreRegistry()
    registry.register(_declaration())
    assert registry.owner_modules() == frozenset({"probos.example"})


def test_registry_holds_no_connection_or_runtime_state() -> None:
    """D1: this is a collection, not a service locator.

    A registry that held connections would be mutable runtime state keyed by
    store -- the shape AD-1270a's D1 rejected -- and would relocate WAL and
    ``busy_timeout`` semantics for thirty stores in one commit.
    """
    source = (_REAL_SRC / "probos" / "storage" / "registry.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    banned = {"connect", "connection_factory", "ProbOSRuntime", "runtime"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in banned:
            pytest.fail(f"registry references {node.attr!r}; it must hold no state")
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assert node.name not in banned, f"registry defines {node.name!r}"


def test_registry_declares_no_module_level_singleton() -> None:
    """A mutable global keyed by store is the object this AD forbids."""
    tree = ast.parse(
        (_REAL_SRC / "probos" / "storage" / "registry.py").read_text(encoding="utf-8")
    )
    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
                assert value.func.id != "StoreRegistry", (
                    "a module-level StoreRegistry() instance is a singleton; "
                    "callers must build a fresh registry"
                )


def test_load_default_store_registry_loads_every_declaration_module() -> None:
    registry = load_default_store_registry()
    assert len(registry.declarations()) >= 8
    assert registry.owner_modules()


def test_load_default_store_registry_degrades_on_a_broken_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One broken module must not blank the whole inventory."""
    import probos.storage.registry as registry_module

    monkeypatch.setattr(
        registry_module,
        "DECLARATION_MODULES",
        ("probos.does.not.exist",) + DECLARATION_MODULES,
    )
    registry = registry_module.load_default_store_registry()
    assert len(registry.declarations()) >= 8


def test_load_default_store_registry_returns_a_fresh_instance() -> None:
    assert load_default_store_registry() is not load_default_store_registry()


# ---------------------------------------------------------------------------
# Leaf and import discipline
# ---------------------------------------------------------------------------


def _imported_modules(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_declarations_model_imports_nothing_from_probos() -> None:
    """``declarations.py`` must be a true leaf, or a declaration module in any
    layer importing it would invert the layer order."""
    spec = importlib.util.find_spec("probos.storage.declarations")
    assert spec is not None and spec.origin is not None
    offenders = [
        name
        for name in _imported_modules(Path(spec.origin))
        if name == "probos" or name.startswith("probos.")
    ]
    assert not offenders, f"probos.storage.declarations must be a leaf: {offenders}"


@pytest.mark.parametrize("module_name", DECLARATION_MODULES)
def test_declaration_modules_import_only_the_store_model(module_name: str) -> None:
    """A declaration is data about a store, never a use of one.

    Importing the declared store would make the declaration a construction and
    drag a dozen modules' side effects into every ``--check``.
    """
    spec = importlib.util.find_spec(module_name)
    assert spec is not None and spec.origin is not None
    offenders = sorted(
        _imported_modules(Path(spec.origin))
        - {"__future__", "probos.storage.declarations"}
    )
    assert not offenders, (
        f"{module_name} may import only probos.storage.declarations; found "
        f"{offenders}."
    )


def test_the_model_never_references_the_degradation_tier() -> None:
    """D4's naming hazard: ``ServiceTier`` is load shedding, not boot criticality."""
    source = (_REAL_SRC / "probos" / "storage" / "declarations.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            assert "degradation" not in node.module, node.module
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "degradation" not in alias.name, alias.name
    for banned in ("ServiceTier", "ServiceClassification", "ServiceTierRegistry"):
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                assert node.id != banned, f"model references {banned}"


def test_no_production_module_imports_the_store_registry() -> None:
    """This slice adds no runtime consumer.

    Criticality is inert: if a production module imported the registry, a
    metadata edit could become a behaviour change, which is precisely the
    BF-756 (#1213) defect this AD must not reproduce.
    """
    completed = subprocess.run(
        ["git", "grep", "-l", "-I", "--", "probos.storage.registry", "src/"],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    hits = sorted(
        line.replace("\\", "/") for line in completed.stdout.splitlines() if line
    )
    allowed = {"src/probos/storage/registry.py"}
    assert set(hits) <= allowed, (
        f"probos.storage.registry must have no runtime consumer; found {hits}"
    )


def test_nothing_reads_criticality_retention_backup_or_restore_to_decide() -> None:
    """D4: criticality is recorded and enforced nowhere.

    Enumerated rather than asserted -- the only ``src/`` modules permitted to
    mention these field names are the model itself and the declaration modules
    that are pure data.
    """
    completed = subprocess.run(
        [
            "git",
            "grep",
            "-l",
            "-I",
            "-E",
            "StoreCriticality|StoreRetention",
            "--",
            "src/",
        ],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    hits = {line.replace("\\", "/") for line in completed.stdout.splitlines() if line}
    allowed = {"src/probos/storage/declarations.py"} | {
        "src/" + name.replace(".", "/") + ".py" for name in DECLARATION_MODULES
    }
    assert hits <= allowed, f"a consumer appeared for inert metadata: {sorted(hits - allowed)}"


# ---------------------------------------------------------------------------
# Detection bounds
# ---------------------------------------------------------------------------


def test_detect_tables_finds_a_named_schema_constant(checker: types.ModuleType) -> None:
    source = '_SCHEMA = """CREATE TABLE IF NOT EXISTS widgets (id TEXT)"""\n'
    assert checker.detect_tables(source) == ("widgets",)


def test_detect_tables_finds_a_schema_passed_to_execute(
    checker: types.ModuleType,
) -> None:
    source = 'def go(c):\n    c.execute("CREATE TABLE gadgets (id TEXT)")\n'
    assert checker.detect_tables(source) == ("gadgets",)


def test_detect_tables_finds_executescript_and_virtual_tables(
    checker: types.ModuleType,
) -> None:
    source = 'def go(c):\n    c.executescript("CREATE VIRTUAL TABLE fts USING fts5(x)")\n'
    assert checker.detect_tables(source) == ("fts",)


def test_detect_tables_ignores_a_docstring(checker: types.ModuleType) -> None:
    """A docstring binds no name and is passed to no execute."""
    source = '"""This module costs one CREATE TABLE IF NOT EXISTS thing at boot."""\n'
    assert checker.detect_tables(source) == ()


def test_detect_tables_ignores_a_comment(checker: types.ModuleType) -> None:
    """``ast.parse`` discards comments, so a comment cannot reach either rule.

    This is not hypothetical: ``commands_directives`` carries ``# Create table``
    above a Rich ``Table`` constructor, and it is the whole difference between
    a case-insensitive text census reporting 58 modules and the AST reporting
    what is actually a store.
    """
    source = "# Create table\ntable = Table(show_header=True)\n"
    assert checker.detect_tables(source) == ()


def test_detect_tables_misses_a_concatenated_schema_bound_to_a_name(
    checker: types.ModuleType,
) -> None:
    """Rule (a) stays narrow on purpose, and this is why.

    Rule (b) joins the literal segments of a dynamic string because the callee
    proves the argument is SQL. A string bound to a *name* proves nothing:
    ``cognitive.builder_specialists`` assigns an LLM instruction containing the
    words ``CREATE TABLE IF NOT EXISTS`` with ``+``, and joining its segments
    here reports it as a store creating a table named ``IF`` (measured). So the
    widening stops at the call boundary, and a real schema concatenated into a
    name and executed through that name still escapes -- a bound the module
    docstring states rather than implies.
    """
    source = '_SCHEMA = "CREATE TABLE " + "widgets (id TEXT)"\n'
    assert checker.detect_tables(source) == ()


def test_a_name_bound_llm_prompt_mentioning_ddl_is_not_a_store(
    checker: types.ModuleType,
) -> None:
    """The concrete false positive rule (a)'s narrowness prevents.

    Reproduces ``builder_specialists``' shape. Widening rule (a) to join
    literal segments would extract the table name ``IF`` from this.
    """
    source = (
        '_PROMPT = (\n'
        '    """Rules:\n'
        '- SQL DDL uses ``CREATE TABLE IF NOT EXISTS`` (idempotent).\n'
        '"""\n'
        "    + _BASE_OUTPUT_FORMAT\n"
        ")\n"
    )
    assert checker.detect_tables(source) == ()


@pytest.mark.parametrize(
    ("label", "call"),
    [
        ("concatenation", 'c.execute("CREATE TABLE " + "widgets" + " (id TEXT)")'),
        ("f-string", 'c.execute(f"CREATE TABLE widgets ({cols})")'),
        ("str.format", 'c.execute("CREATE TABLE widgets ({})".format(cols))'),
        ("percent", 'c.execute("CREATE TABLE widgets (%s)" % cols)'),
        ("nested concat in executescript", 'c.executescript("CREATE TABLE " + "widgets")'),
    ],
)
def test_a_dynamic_schema_passed_to_execute_is_detected(
    checker: types.ModuleType, label: str, call: str
) -> None:
    """Rule (b) reads the literal segments of a dynamically assembled schema.

    Every shape here returned ``()`` before AD-1256's review repair, so a store
    whose DDL was built with ``+``, an f-string, ``str.format`` or ``%`` reached
    production without a declaration and without a baseline row.
    """
    source = f"def go(c, cols):\n    {call}\n"
    assert checker.detect_tables(source) == ("widgets",), label


def test_a_runtime_only_table_name_is_still_undetectable(
    checker: types.ModuleType,
) -> None:
    """The residual bound, pinned so it cannot be quietly overclaimed.

    ``execute(f"CREATE TABLE {name}")`` carries no literal table name anywhere
    in the source. The shared pattern is both the schema gate and the name
    extractor, so with nothing to extract the module is not reported at all.
    No static analysis closes this; only a runtime census would.
    """
    source = 'def go(c, name):\n    c.execute(f"CREATE TABLE {name} (id TEXT)")\n'
    assert checker.detect_tables(source) == ()


def test_detect_tables_survives_unparseable_source(checker: types.ModuleType) -> None:
    assert checker.detect_tables("def broken(:\n") == ()


def test_the_cached_and_computed_table_sets_agree_on_every_module(
    checker: types.ModuleType,
) -> None:
    """Two instruments read each module's tables; they must not drift.

    ``build_symbol_index`` records tables from the tree it already parsed, and
    ``detect_tables`` parses a source string on demand. A raw-source prefilter
    that disagreed with the AST rule is exactly how dynamic SQL escaped the
    gate in the first place, so the second reader is bound to the first here.
    """
    index = checker.build_symbol_index(_REAL_SRC)
    assert index.tables, "the index recorded no tables at all"
    drifted = {
        module: (tables, checker.detect_tables(index.sources[module]))
        for module, tables in index.tables.items()
        if tables != checker.detect_tables(index.sources[module])
    }
    assert drifted == {}, drifted


def test_detect_stores_has_no_raw_source_prefilter(
    checker: types.ModuleType,
) -> None:
    """The prefilter was narrower than the rule it guarded.

    ``execute("CREATE TABLE " + "widgets")`` matches once the literal segments
    are joined, and matches no contiguous run of the source text, so the
    prefilter skipped the module before ``detect_tables`` ever ran. Asserted
    through the public surface rather than by reading the source.
    """
    source = 'def go(c):\n    c.execute("CREATE TABLE " + "widgets (id TEXT)")\n'
    assert checker._TABLE_NAME_RE.search(source) is None, "premise: raw text must not match"
    index = checker.SymbolIndex()
    index.sources["probos.ghost"] = source
    index.tables["probos.ghost"] = checker.detect_tables(source)
    assert checker.detect_stores(index) == {"probos.ghost": ("widgets",)}


# ---------------------------------------------------------------------------
# Rule (c): .sql files
# ---------------------------------------------------------------------------


def test_a_sql_file_is_attributed_to_its_owning_package(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    src = tmp_path / "src"
    (src / "probos" / "vault").mkdir(parents=True)
    (src / "probos" / "vault" / "schema.sql").write_text(
        "CREATE TABLE ledger (id TEXT);\n", encoding="utf-8"
    )
    assert checker.detect_sql_file_stores(src) == {"probos.vault": ("ledger",)}


def test_a_sql_file_with_no_ddl_is_not_a_store(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    src = tmp_path / "src"
    (src / "probos").mkdir(parents=True)
    (src / "probos" / "report.sql").write_text(
        "SELECT id FROM ledger ORDER BY id;\n", encoding="utf-8"
    )
    assert checker.detect_sql_file_stores(src) == {}


def test_sql_tables_merge_with_the_owning_packages_python_tables(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """A package can create tables from both ``__init__.py`` and a ``.sql`` file."""
    src = tmp_path / "src"
    (src / "probos" / "vault").mkdir(parents=True)
    (src / "probos" / "__init__.py").write_text("", encoding="utf-8")
    (src / "probos" / "vault" / "__init__.py").write_text(
        '_SCHEMA = "CREATE TABLE entries (id TEXT)"\n', encoding="utf-8"
    )
    (src / "probos" / "vault" / "schema.sql").write_text(
        "CREATE TABLE ledger (id TEXT);\n", encoding="utf-8"
    )
    index = checker.build_symbol_index(src)
    assert checker.detect_stores(index)["probos.vault"] == ("entries", "ledger")


def test_the_real_tree_has_no_tracked_sql_files(checker: types.ModuleType) -> None:
    """Rule (c) adds nothing today; it exists so the first ``.sql`` store fails.

    If this ever fails, a ``.sql`` file arrived and its store must be declared
    or baselined -- which is the whole point of the rule.
    """
    assert checker.detect_sql_file_stores(_REAL_SRC) == {}


def test_detect_sql_file_stores_on_a_missing_root_is_empty(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    assert checker.detect_sql_file_stores(tmp_path / "nope") == {}


def test_detection_excludes_the_three_known_false_positives(
    checker: types.ModuleType,
) -> None:
    """Measured on the tracked tree: 59 pattern matches, 56 detected.

    ``config`` matches inside a docstring, ``commands_directives`` inside a
    code comment above a Rich ``Table``, and ``builder_specialists`` inside a
    concatenated LLM instruction string. None of the three is a store, and
    each escapes for a different reason.
    """
    index = checker.build_symbol_index(_REAL_SRC)
    detected = checker.detect_stores(index)
    for false_positive in (
        "probos.config",
        "probos.experience.commands.commands_directives",
        "probos.cognitive.builder_specialists",
    ):
        assert false_positive not in detected, false_positive


# ---------------------------------------------------------------------------
# The committed tree: benign baseline and currency
# ---------------------------------------------------------------------------


def test_check_passes_on_the_committed_tree(checker: types.ModuleType) -> None:
    """The benign baseline: every rule armed, zero errors."""
    result = checker.check(baseline_path=_REAL_BASELINE, src_root=_REAL_SRC)
    assert result.errors == [], result.errors


def test_update_baseline_is_byte_identical_on_the_committed_tree(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    index = checker.build_symbol_index(_REAL_SRC)
    detected = checker.detect_stores(index)
    declared = checker._declared_modules_for_baseline(_REAL_SRC, index)
    document, _ = checker.load_baseline(_REAL_BASELINE)
    rendered = checker.render_baseline(detected, declared, document)
    assert rendered == _REAL_BASELINE.read_text(encoding="utf-8")


def test_gating_rules_match_the_documented_set(checker: types.ModuleType) -> None:
    """A rule cannot be added without documenting it."""
    assert set(checker.GATING_RULES) == _DOCUMENTED_RULES
    assert len(checker.GATING_RULES) == len(set(checker.GATING_RULES))


def test_every_report_only_rule_has_a_promotion_condition(
    checker: types.ModuleType,
) -> None:
    """Report-only without a promotion condition is a rule that never lands."""
    assert checker.REPORT_ONLY_RULES
    for rule, promotion in checker.REPORT_ONLY_RULES:
        assert rule and promotion.strip(), rule


def test_preflight_wires_the_store_registry_phase() -> None:
    """The gate must actually run this checker, after architecture-fitness."""
    source = (_REPO_ROOT / "scripts" / "run_test_gate.py").read_text(encoding="utf-8")
    assert '"store-registry"' in source
    assert "scripts/check_store_registry.py" in source
    assert source.index('"architecture-fitness"') < source.index('"store-registry"')
    assert source.index('"store-registry"') < source.index('"compile"')


def test_every_declaration_module_on_disk_is_registered(
    checker: types.ModuleType,
) -> None:
    index = checker.build_symbol_index(_REAL_SRC)
    on_disk = set(checker.find_declaration_modules_on_disk(index))
    assert on_disk == set(DECLARATION_MODULES)


def test_the_ast_and_import_paths_agree_on_every_declaration(
    checker: types.ModuleType,
) -> None:
    """Two instruments read these declarations; they must not drift.

    The checker reads them by AST (hermetic, sees the materialized worktree);
    the registry reads them by import. This binds the mirrored schema logic in
    the checker to ``declaration_errors`` in the model.
    """
    index = checker.build_symbol_index(_REAL_SRC)
    module_names, errors = checker.read_declaration_modules(_REAL_SRC)
    assert errors == []
    ast_rows, read_errors = checker.read_declarations(module_names, index, _REAL_SRC)
    assert read_errors == []

    imported = {item.id: item.to_dict() for item in load_default_store_registry().declarations()}
    assert len(ast_rows) == len(imported)
    for row in ast_rows:
        expected = imported[row["id"]]
        for key, value in expected.items():
            if key in {"criticality", "retention"}:
                raw = row[key]
                assert isinstance(raw, tuple) and raw[2]
                continue
            assert row.get(key, "") == value, f"{row['id']}.{key}"


def test_every_criticality_value_has_at_least_one_seed_declaration() -> None:
    seen = {item.criticality for item in load_default_store_registry().declarations()}
    assert seen == set(StoreCriticality)


def test_every_retention_value_has_at_least_one_seed_declaration() -> None:
    seen = {item.retention for item in load_default_store_registry().declarations()}
    assert seen == set(StoreRetention)


def test_the_seed_set_covers_a_reconstructed_restore_and_an_excluded_backup() -> None:
    declarations = load_default_store_registry().declarations()
    assert any(item.restore == "reconstructed" and item.reconstruction for item in declarations)
    assert any(item.backup == "excluded" for item in declarations)


def test_the_two_lock_domains_record_why_they_are_separate() -> None:
    """BF-826/#1290 depends on these being two files with two locks.

    A future consolidation proposal must meet a written reason, not silence.
    """
    registry = load_default_store_registry()
    chat = registry.get("threads.chat-threads")
    work = registry.get("workforce.work-items")
    assert chat is not None and work is not None
    assert chat.canonical_path != work.canonical_path
    for declaration in (chat, work):
        assert "lock" in declaration.notes.lower(), declaration.id


# ---------------------------------------------------------------------------
# Injection: every gating rule fires, and stays silent when it should
# ---------------------------------------------------------------------------


def test_a_clean_synthetic_tree_produces_no_errors(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """Not-firing baseline for every injection below."""
    src = _build_tree(tmp_path)
    baseline = tmp_path / "store-baseline.yaml"
    _write_baseline(baseline)
    result = checker.check(baseline_path=baseline, src_root=src)
    assert result.errors == [], result.errors


def test_a_declaration_naming_a_nonexistent_owner_symbol_fires(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    src = _build_tree(tmp_path, entries=_entry(owner_symbol="GhostStore"))
    baseline = tmp_path / "store-baseline.yaml"
    _write_baseline(baseline)
    result = checker.check(baseline_path=baseline, src_root=src)
    assert "declaration-owner-unresolved" in _rules_fired(result.errors), result.errors


def test_a_declaration_naming_a_nonexistent_owner_module_fires(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    src = _build_tree(tmp_path, entries=_entry(owner_module="probos.nowhere"))
    baseline = tmp_path / "store-baseline.yaml"
    _write_baseline(baseline)
    result = checker.check(baseline_path=baseline, src_root=src)
    assert "declaration-owner-unresolved" in _rules_fired(result.errors), result.errors


def test_a_blank_criticality_fires(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    src = _build_tree(tmp_path, entries=_entry(criticality='""'))
    baseline = tmp_path / "store-baseline.yaml"
    _write_baseline(baseline)
    result = checker.check(baseline_path=baseline, src_root=src)
    assert "declaration-schema" in _rules_fired(result.errors), result.errors


def test_a_criticality_outside_the_vocabulary_fires(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    src = _build_tree(tmp_path, entries=_entry(criticality='"vital"'))
    baseline = tmp_path / "store-baseline.yaml"
    _write_baseline(baseline)
    result = checker.check(baseline_path=baseline, src_root=src)
    assert "declaration-schema" in _rules_fired(result.errors), result.errors


def test_unbounded_retention_with_an_empty_note_fires(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    src = _build_tree(
        tmp_path,
        entries=_entry(retention="StoreRetention.UNBOUNDED", retention_note='""'),
    )
    baseline = tmp_path / "store-baseline.yaml"
    _write_baseline(baseline)
    result = checker.check(baseline_path=baseline, src_root=src)
    assert "declaration-schema" in _rules_fired(result.errors), result.errors


def test_unbounded_retention_with_a_note_does_not_fire(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """Not-firing: the rule demands a written reason, not a particular answer."""
    src = _build_tree(
        tmp_path,
        entries=_entry(
            retention="StoreRetention.UNBOUNDED",
            retention_note='"an audit trail that deletes its history is not one"',
        ),
    )
    baseline = tmp_path / "store-baseline.yaml"
    _write_baseline(baseline)
    result = checker.check(baseline_path=baseline, src_root=src)
    assert result.errors == [], result.errors


def test_reconstructed_restore_without_a_method_fires(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    src = _build_tree(tmp_path, entries=_entry(restore='"reconstructed"'))
    baseline = tmp_path / "store-baseline.yaml"
    _write_baseline(baseline)
    result = checker.check(baseline_path=baseline, src_root=src)
    assert "declaration-schema" in _rules_fired(result.errors), result.errors


def test_two_declarations_claiming_one_canonical_path_fires(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    entries = _entry() + _entry(store_id="layer.beta")
    src = _build_tree(tmp_path, entries=entries)
    baseline = tmp_path / "store-baseline.yaml"
    _write_baseline(baseline)
    result = checker.check(baseline_path=baseline, src_root=src)
    assert "declaration-duplicate-path" in _rules_fired(result.errors), result.errors


def test_two_declarations_sharing_one_id_fires(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    entries = _entry() + _entry(canonical_path="beta.db")
    src = _build_tree(tmp_path, entries=entries)
    baseline = tmp_path / "store-baseline.yaml"
    _write_baseline(baseline)
    result = checker.check(baseline_path=baseline, src_root=src)
    assert "declaration-duplicate-id" in _rules_fired(result.errors), result.errors


def test_a_new_undeclared_store_fires(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """Exists -> declared. This is the property #1302 asks for."""
    src = _build_tree(
        tmp_path,
        extra_modules={
            "brand_new.py": '_SCHEMA = """CREATE TABLE IF NOT EXISTS surprises (id TEXT)"""\n'
        },
    )
    baseline = tmp_path / "store-baseline.yaml"
    _write_baseline(baseline)
    result = checker.check(baseline_path=baseline, src_root=src)
    assert "undeclared-store" in _rules_fired(result.errors), result.errors


@pytest.mark.parametrize(
    ("label", "call"),
    [
        ("concatenation", 'c.execute("CREATE TABLE " + "surprises" + " (id TEXT)")'),
        ("f-string", 'c.execute(f"CREATE TABLE surprises ({cols})")'),
        ("str.format", 'c.execute("CREATE TABLE surprises ({})".format(cols))'),
    ],
)
def test_a_new_undeclared_store_built_by_dynamic_sql_fires(
    checker: types.ModuleType, tmp_path: Path, label: str, call: str
) -> None:
    """End to end, through ``check``: dynamic DDL no longer escapes the gate.

    Each of these shapes produced a clean pass before AD-1256's review repair.
    """
    src = _build_tree(
        tmp_path,
        extra_modules={"brand_new.py": f"def go(c, cols):\n    {call}\n"},
    )
    baseline = tmp_path / "store-baseline.yaml"
    _write_baseline(baseline)
    result = checker.check(baseline_path=baseline, src_root=src)
    assert "undeclared-store" in _rules_fired(result.errors), (label, result.errors)


def test_a_new_undeclared_store_in_a_sql_file_fires(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """Rule (c) end to end: DDL with no Python around it is still a store."""
    src = _build_tree(
        tmp_path,
        extra_modules={
            "vault/__init__.py": "",
            "vault/schema.sql": "CREATE TABLE ledger (id TEXT);\n",
        },
    )
    baseline = tmp_path / "store-baseline.yaml"
    _write_baseline(baseline)
    result = checker.check(baseline_path=baseline, src_root=src)
    assert "undeclared-store" in _rules_fired(result.errors), result.errors
    assert any("probos.vault" in message for message in result.errors), result.errors


def test_a_baselined_sql_file_store_does_not_fire(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """A ``.sql`` store is baselined exactly as a module's is."""
    src = _build_tree(
        tmp_path,
        extra_modules={
            "vault/__init__.py": "",
            "vault/schema.sql": "CREATE TABLE ledger (id TEXT);\n",
        },
    )
    baseline = tmp_path / "store-baseline.yaml"
    _write_baseline(baseline, rows=[{"module": "probos.vault", "tables": ["ledger"]}])
    result = checker.check(baseline_path=baseline, src_root=src)
    assert result.errors == [], result.errors


def test_a_baselined_store_does_not_fire(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """Not-firing: the freeze is what lets pre-existing stores pass."""
    src = _build_tree(
        tmp_path,
        extra_modules={
            "old_store.py": '_SCHEMA = """CREATE TABLE IF NOT EXISTS legacy (id TEXT)"""\n'
        },
    )
    baseline = tmp_path / "store-baseline.yaml"
    _write_baseline(baseline, [{"module": "probos.old_store", "tables": ["legacy"]}])
    result = checker.check(baseline_path=baseline, src_root=src)
    assert result.errors == [], result.errors


def test_a_baseline_row_whose_module_is_gone_fires(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    src = _build_tree(tmp_path)
    baseline = tmp_path / "store-baseline.yaml"
    _write_baseline(baseline, [{"module": "probos.deleted", "tables": ["ghost"]}])
    result = checker.check(baseline_path=baseline, src_root=src)
    assert "stale-baseline-row" in _rules_fired(result.errors), result.errors


def test_a_baseline_row_for_a_now_declared_store_fires(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """Declaring a store means deleting its baseline row in the same commit."""
    src = _build_tree(
        tmp_path,
        extra_modules={
            "alpha.py": 'class AlphaStore:\n    pass\n\n\n_SCHEMA = """CREATE TABLE IF NOT EXISTS alpha (id TEXT)"""\n'
        },
    )
    baseline = tmp_path / "store-baseline.yaml"
    _write_baseline(baseline, [{"module": "probos.alpha", "tables": ["alpha"]}])
    result = checker.check(baseline_path=baseline, src_root=src)
    assert "stale-baseline-row" in _rules_fired(result.errors), result.errors


def test_a_changed_table_set_on_a_baselined_store_fires(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    src = _build_tree(
        tmp_path,
        extra_modules={
            "old_store.py": '_SCHEMA = """CREATE TABLE legacy (id TEXT); CREATE TABLE extra (id TEXT)"""\n'
        },
    )
    baseline = tmp_path / "store-baseline.yaml"
    _write_baseline(baseline, [{"module": "probos.old_store", "tables": ["legacy"]}])
    result = checker.check(baseline_path=baseline, src_root=src)
    assert "baseline-table-drift" in _rules_fired(result.errors), result.errors


def test_an_unregistered_declaration_module_fires(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """The explicit-tuple pattern cannot be allowed to fall silently behind."""
    src = _build_tree(
        tmp_path,
        extra_modules={
            "orphan/__init__.py": "",
            "orphan/storage_declarations.py": "STORE_DECLARATIONS = ()\n",
        },
    )
    baseline = tmp_path / "store-baseline.yaml"
    _write_baseline(baseline)
    result = checker.check(baseline_path=baseline, src_root=src)
    assert "declaration-module-unregistered" in _rules_fired(result.errors), result.errors


def test_a_registered_module_that_does_not_exist_fires(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    src = _build_tree(
        tmp_path,
        declaration_modules=(
            "probos.alpha_pkg.storage_declarations",
            "probos.phantom.storage_declarations",
        ),
    )
    baseline = tmp_path / "store-baseline.yaml"
    _write_baseline(baseline)
    result = checker.check(baseline_path=baseline, src_root=src)
    assert "declaration-module-unregistered" in _rules_fired(result.errors), result.errors


def test_a_blank_baseline_review_block_fires(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """Blank fails on purpose: a placeholder would pass a non-blank test."""
    src = _build_tree(tmp_path)
    baseline = tmp_path / "store-baseline.yaml"
    baseline.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "baseline_id": "test",
                "tracking_issue": 1302,
                "review": {"owner": "", "rationale": "", "review_by": ""},
                "undeclared_stores": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    result = checker.check(baseline_path=baseline, src_root=src)
    assert "baseline-schema" in _rules_fired(result.errors), result.errors


def test_a_missing_baseline_file_fires(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    src = _build_tree(tmp_path)
    result = checker.check(baseline_path=tmp_path / "absent.yaml", src_root=src)
    assert "baseline-schema" in _rules_fired(result.errors), result.errors


def test_check_accumulates_every_failure_rather_than_the_first(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """A checker that stops at the first fault costs one run per defect."""
    entries = _entry(owner_symbol="GhostStore", criticality='""') + _entry(
        store_id="layer.beta", owner_symbol="AlsoGhost", restore='"reconstructed"'
    )
    src = _build_tree(tmp_path, entries=entries)
    baseline = tmp_path / "store-baseline.yaml"
    _write_baseline(baseline, [{"module": "probos.deleted", "tables": ["ghost"]}])
    result = checker.check(baseline_path=baseline, src_root=src)
    fired = _rules_fired(result.errors)
    assert {
        "declaration-owner-unresolved",
        "declaration-schema",
        "declaration-duplicate-path",
        "stale-baseline-row",
    } <= fired, fired


def test_every_error_message_names_the_command_that_fixes_it(
    checker: types.ModuleType, tmp_path: Path
) -> None:
    """A symmetric gate that does not say how to satisfy it gets disabled."""
    src = _build_tree(
        tmp_path,
        extra_modules={
            "brand_new.py": '_SCHEMA = """CREATE TABLE IF NOT EXISTS surprises (id TEXT)"""\n'
        },
    )
    baseline = tmp_path / "store-baseline.yaml"
    _write_baseline(baseline)
    result = checker.check(baseline_path=baseline, src_root=src)
    inventory = [
        message
        for message in result.errors
        if message.startswith(("[undeclared-store]", "[stale-baseline-row]"))
    ]
    assert inventory
    for message in inventory:
        assert "check_store_registry.py --update-baseline" in message, message


# ---------------------------------------------------------------------------
# Injection against the REAL tree, restored byte-identically
# ---------------------------------------------------------------------------


def test_the_real_tree_can_fail_declared_to_exists(checker: types.ModuleType) -> None:
    """Rename a real declaration's owner symbol; the checker must reject it."""
    target = _REAL_SRC / "probos" / "tools" / "storage_declarations.py"
    original = target.read_bytes()
    try:
        target.write_bytes(
            original.replace(b'owner_symbol="ActionApprovalStore"', b'owner_symbol="NoSuchStore"')
        )
        assert target.read_bytes() != original, "injection did not change the file"
        result = checker.check(baseline_path=_REAL_BASELINE, src_root=_REAL_SRC)
        assert "declaration-owner-unresolved" in _rules_fired(result.errors), result.errors
    finally:
        target.write_bytes(original)
    assert target.read_bytes() == original
    restored = checker.check(baseline_path=_REAL_BASELINE, src_root=_REAL_SRC)
    assert restored.errors == [], restored.errors


def test_the_real_tree_can_fail_exists_to_declared(checker: types.ModuleType) -> None:
    """Add a real undeclared store module; the checker must reject it.

    The file is created inside ``src/probos/`` and removed in ``finally``. It
    is never staged, so ``git ls-files`` cannot see it -- which is why the
    index is rebuilt with a disk-walk fallback for this one assertion.
    """
    target = _REAL_SRC / "probos" / "_ad1256_injected_store.py"
    assert not target.exists(), "injection target already exists"
    try:
        target.write_text(
            '_SCHEMA = """CREATE TABLE IF NOT EXISTS injected_rows (id TEXT)"""\n',
            encoding="utf-8",
        )
        source = target.read_text(encoding="utf-8")
        assert checker.detect_tables(source) == ("injected_rows",), (
            "the probe never detected its own injected schema, so a negative "
            "result would prove nothing"
        )
        index = checker.build_symbol_index(_REAL_SRC)
        index.sources["probos._ad1256_injected_store"] = source
        detected = checker.detect_stores(index)
        assert "probos._ad1256_injected_store" in detected
        document, _ = checker.load_baseline(_REAL_BASELINE)
        assert document is not None
        rows, _ = checker.baseline_rows(document, _REAL_BASELINE.name)
        declared = checker._declared_modules_for_baseline(_REAL_SRC, index)
        errors = checker.compare_to_baseline(
            detected, declared, rows, _REAL_BASELINE
        )
        assert "undeclared-store" in _rules_fired(errors), errors
    finally:
        target.unlink(missing_ok=True)
    assert not target.exists()
    restored = checker.check(baseline_path=_REAL_BASELINE, src_root=_REAL_SRC)
    assert restored.errors == [], restored.errors
