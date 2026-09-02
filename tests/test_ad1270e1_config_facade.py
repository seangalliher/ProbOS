"""AD-1270e1 -- the configuration facade contract is real, not decorative.

``scripts/check_config_facade.py`` freezes the public surface of
``probos.config`` before AD-1270e2/e3 move 224 models out of it. These tests
exist to prove the freeze can *fail*: a baseline that cannot reject a changed
default, a widened environment read or a re-implemented model is documentation
wearing a checker's clothes.

Three properties get disproportionate attention here, because each one is a way
the artifact could look correct and be worthless:

*   **The capture is environment-free.** ``tests/conftest.py`` sets
    ``PROBOS_NATS_ENABLED`` with ``setdefault``, so a baseline captured under
    pytest would bake in *the generating developer's ambient variable*. The
    capture therefore runs in a subprocess whose environment is rebuilt
    explicitly, and the child refuses to run if a ``PROBOS_*`` name survives.
*   **The differential asserts its own premise.** A harness that silently fails
    to set a variable is indistinguishable from a variable that moves nothing,
    so the control row must move zero paths *and* a known mover must move
    exactly one.
*   **Identity, not existence.** A re-export keeps a model's qualname, MRO and
    field order; a wrapper or a partial clone does not. A name-only check would
    wave both through while ``isinstance`` consumers broke.

Nothing here re-runs the expensive contract more than once: exactly one test
shells out to the full ``--check``.
"""

from __future__ import annotations

import ast
import copy
import importlib.util
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
from types import ModuleType
from typing import Any

import pytest
import yaml
from pydantic import AliasChoices, BaseModel, Field

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO_ROOT / "scripts" / "check_config_facade.py"
_BASELINE = _REPO_ROOT / "docs" / "development" / "config-facade-baseline.yaml"
_CONFIG_MODULE = _REPO_ROOT / "src" / "probos" / "config.py"


def _load(name: str, path: Path) -> ModuleType:
    """Import a ``scripts/`` module by path; ``scripts/`` is not a package."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


facade = _load("_ad1270e1_facade", _SCRIPT)


@pytest.fixture(scope="module")
def baseline() -> dict[str, Any]:
    return yaml.safe_load(_BASELINE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Normalisation -- the platform trap
# ---------------------------------------------------------------------------


def test_render_value_renders_paths_as_posix_not_platform_repr() -> None:
    assert facade.render_value(PureWindowsPath("data\\captains_log")) == (
        "'data/captains_log'"
    )
    assert facade.render_value(PurePosixPath("data/captains_log")) == (
        "'data/captains_log'"
    )


def test_render_value_normalises_paths_recursively_through_containers() -> None:
    """The top-level type is not a guard: a ``dict[str, list[Path]]`` hides it."""
    value = {"logs": [PureWindowsPath("a\\b")], "one": (PureWindowsPath("c\\d"),)}
    rendered = facade.render_value(value)

    assert "\\" not in rendered
    assert "'a/b'" in rendered and "'c/d'" in rendered


def test_render_value_sorts_sets_so_hash_seed_cannot_move_the_baseline() -> None:
    forward = facade.render_value(frozenset({"b", "a", "c"}))
    reverse = facade.render_value(frozenset({"c", "b", "a"}))

    assert forward == reverse == "frozenset({'a', 'b', 'c'})"
    assert facade.render_value({"b", "a"}) == "{'a', 'b'}"


def test_render_value_distinguishes_required_from_none() -> None:
    from pydantic_core import PydanticUndefined

    assert facade.render_value(PydanticUndefined) == "<required>"
    assert facade.render_value(None) == "None"


def test_render_value_renders_model_instances_as_type_only() -> None:
    """A nested model repr would be enormous and environment-sensitive."""

    class Inner(BaseModel):
        value: int = 1

    assert facade.render_value(Inner()) == f"{Inner.__qualname__}(...)"
    assert "value=1" not in facade.render_value(Inner())


def test_render_value_renders_single_element_tuple_unambiguously() -> None:
    assert facade.render_value((1,)) == "(1,)"
    assert facade.render_value((1, 2)) == "(1, 2)"


def test_normalise_json_posixifies_paths_nested_in_json_structures() -> None:
    normalised = facade.normalise_json(
        {"a": [{"b": PureWindowsPath("x\\y")}], "c": PureWindowsPath("z\\w")}
    )

    assert normalised == {"a": [{"b": "x/y"}], "c": "z/w"}


def test_flatten_dump_produces_dotted_leaf_paths() -> None:
    flat = facade.flatten_dump({"nats": {"enabled": False}, "top": 1})

    assert flat == {"nats.enabled": False, "top": 1}


def test_flatten_dump_indexes_list_elements() -> None:
    flat = facade.flatten_dump({"peers": [{"host": "a"}, {"host": "b"}]})

    assert flat == {"peers[0].host": "a", "peers[1].host": "b"}


def test_digest_ignores_key_order_but_not_values() -> None:
    assert facade.digest({"a": 1, "b": 2}) == facade.digest({"b": 2, "a": 1})
    assert facade.digest({"a": 1}) != facade.digest({"a": 2})


# ---------------------------------------------------------------------------
# G2 -- environment read enumeration
# ---------------------------------------------------------------------------


def _write_module(tmp_path: Path, source: str) -> Path:
    path = tmp_path / "sample.py"
    path.write_text(source, encoding="utf-8")
    return path


def test_enumerate_env_reads_finds_get_getenv_and_subscript(tmp_path: Path) -> None:
    path = _write_module(
        tmp_path,
        "import os\n"
        "a = os.environ.get('ALPHA')\n"
        "b = os.getenv('BETA')\n"
        "c = os.environ['GAMMA']\n",
    )

    scan = facade.enumerate_env_reads([path])

    assert set(scan.names) == {"ALPHA", "BETA", "GAMMA"}
    assert scan.non_literal == []


def test_enumerate_env_reads_rejects_a_computed_name(tmp_path: Path) -> None:
    """A name that cannot be enumerated cannot be proven harmless."""
    path = _write_module(
        tmp_path,
        "import os\n"
        "prefix = 'PROBOS_'\n"
        "a = os.environ.get(prefix + 'THING')\n"
        "b = os.environ.get(f'{prefix}OTHER')\n",
    )

    scan = facade.enumerate_env_reads([path])

    assert scan.names == {}
    assert len(scan.non_literal) == 2
    assert all("sample.py:" in location for location in scan.non_literal)


def test_enumerate_env_reads_classifies_the_mechanism_that_reaches_furthest(
    tmp_path: Path,
) -> None:
    path = _write_module(
        tmp_path,
        "import os\n"
        "from pydantic import BaseModel, field_validator, model_validator\n"
        "class M(BaseModel):\n"
        "    @model_validator(mode='after')\n"
        "    def _after(self):\n"
        "        return os.environ.get('AFTER')\n"
        "    @field_validator('x', mode='before')\n"
        "    @classmethod\n"
        "    def _before(cls, v):\n"
        "        return os.environ.get('BEFORE')\n"
        "def helper():\n"
        "    return os.environ.get('PLAIN')\n",
    )

    scan = facade.enumerate_env_reads([path])

    assert scan.names["AFTER"] == "model-validator"
    assert scan.names["BEFORE"] == "config-field-validator"
    assert scan.names["PLAIN"] == "module-function"


def test_g2_enumeration_agrees_with_check_config_profiles() -> None:
    """Two independent instruments agreeing is evidence; one is an assumption.

    ``check_config_profiles.env_reads_reaching_defaults`` is keyed on validator
    *kind* for exactly the ``PROBOS_LLM_URL`` reason. It is cross-checked here,
    never absorbed -- ``scripts/check_config_profiles.py`` keeps ownership.
    """
    profiles = _load(
        "_ad1270e1_profiles", _REPO_ROOT / "scripts" / "check_config_profiles.py"
    )
    theirs = profiles.env_reads_reaching_defaults(_CONFIG_MODULE)

    scan = facade.enumerate_env_reads([_CONFIG_MODULE])
    mine = {
        name: mechanism
        for name, mechanism in scan.names.items()
        if mechanism in {"model-validator", "config-field-validator"}
    }

    assert mine == theirs


def test_movement_proof_paths_covers_config_models_before_it_exists(
    tmp_path: Path,
) -> None:
    """Scanning e2's future package from day one is what closes the escape."""
    (tmp_path / "src" / "probos").mkdir(parents=True)
    (tmp_path / "src" / "probos" / "config.py").write_text("", encoding="utf-8")

    assert [p.name for p in facade.movement_proof_paths(tmp_path)] == ["config.py"]

    models = tmp_path / "src" / "probos" / "config_models"
    (models / "nested").mkdir(parents=True)
    (models / "core.py").write_text("", encoding="utf-8")
    (models / "nested" / "deep.py").write_text("", encoding="utf-8")

    assert sorted(p.name for p in facade.movement_proof_paths(tmp_path)) == [
        "config.py",
        "core.py",
        "deep.py",
    ]


# ---------------------------------------------------------------------------
# G2 -- the gate is on the *mapping*, not on one spelling of it
# ---------------------------------------------------------------------------
#
# A scanner that recognised only ``os.environ.get`` / ``os.getenv`` /
# ``os.environ[...]`` with the base identifier spelled exactly ``os`` was
# bypassable by three lines of ordinary Python. Each shape below was measured
# returning zero names *and* zero non-literals end to end -- an undeclared
# environment read admitted in total silence, which is the one outcome G2
# exists to prevent. Every pin here fails against the pre-repair checker.


@pytest.mark.parametrize(
    ("label", "source"),
    [
        (
            "getattr-on-the-os-module",
            "import os\ndef f():\n    return getattr(os, 'environ').get('PROBOS_A')\n",
        ),
        (
            "environ-rebound-to-a-local",
            "import os\nenv = os.environ\ndef f():\n    return env.get('PROBOS_A')\n",
        ),
        (
            "environ-rebound-then-subscripted",
            "import os\nenv = os.environ\ndef f():\n    return env['PROBOS_A']\n",
        ),
        (
            "environ-rebound-transitively",
            "import os\na = os.environ\nb = a\ndef f():\n    return b.get('PROBOS_A')\n",
        ),
        (
            "os-imported-under-an-alias",
            "import os as _os\ndef f():\n    return _os.getenv('PROBOS_A')\n",
        ),
        (
            "environ-imported-by-name",
            "from os import environ\ndef f():\n    return environ.get('PROBOS_A')\n",
        ),
        (
            "getenv-imported-by-name",
            "from os import getenv\ndef f():\n    return getenv('PROBOS_A')\n",
        ),
        (
            "getenv-imported-under-an-alias",
            "from os import getenv as ge\ndef f():\n    return ge('PROBOS_A')\n",
        ),
        (
            "getattr-reaching-getenv",
            "import os\ndef f():\n    return getattr(os, 'getenv')('PROBOS_A')\n",
        ),
    ],
)
def test_enumerate_env_reads_resolves_the_binding_not_the_spelling(
    tmp_path: Path, label: str, source: str
) -> None:
    path = _write_module(tmp_path, source)

    scan = facade.enumerate_env_reads([path])

    assert set(scan.names) == {"PROBOS_A"}, label
    assert scan.non_literal == [], label


@pytest.mark.parametrize(
    ("label", "source"),
    [
        (
            "computed-getattr-could-be-environ",
            "import os\nattr = 'environ'\ndef f():\n"
            "    return getattr(os, attr).get('PROBOS_A')\n",
        ),
        (
            "environ-copied-into-a-plain-dict",
            "import os\ndef f():\n    return dict(os.environ).get('PROBOS_A')\n",
        ),
        (
            "environ-handed-to-a-helper",
            "import os\ndef h(e):\n    return e.get('PROBOS_A')\n"
            "def f():\n    return h(os.environ)\n",
        ),
        (
            "environ-read-through-an-unmodelled-accessor",
            "import os\ndef f():\n    return os.environ.setdefault('PROBOS_A', '1')\n",
        ),
    ],
)
def test_enumerate_env_reads_rejects_what_it_cannot_follow(
    tmp_path: Path, label: str, source: str
) -> None:
    """Unresolvable is a hard failure, never a silent pass.

    Each of these reaches the environment through an expression the scan does
    not model. Admitting it would mean an undeclared read no instrument ever
    reports again; refusing it costs one loud message a human resolves in one
    edit.
    """
    path = _write_module(tmp_path, source)

    scan = facade.enumerate_env_reads([path])

    assert scan.names == {}, label
    assert len(scan.non_literal) == 1, label
    assert scan.non_literal[0].startswith("sample.py:"), label


@pytest.mark.parametrize(
    ("label", "source"),
    [
        (
            "getenv-by-keyword",
            "import os\ndef f():\n    return os.getenv(key='PROBOS_A')\n",
        ),
        (
            "environ-get-by-keyword",
            "import os\ndef f():\n    return os.environ.get(key='PROBOS_A')\n",
        ),
        (
            "getenv-by-keyword-with-default",
            "import os\ndef f():\n    return os.getenv(key='PROBOS_A', default='1')\n",
        ),
        (
            "getenv-by-keyword-through-an-alias",
            "import os as _os\ndef f():\n    return _os.getenv(key='PROBOS_A')\n",
        ),
    ],
)
def test_enumerate_env_reads_sees_the_keyword_spelling(
    tmp_path: Path, label: str, source: str
) -> None:
    """``os.getenv(key="A")`` reaches the environment; scanning only
    positional args made it silent.

    Both ``os.getenv`` and ``MutableMapping.get`` -- which is the ``get``
    ``os.environ`` actually inherits -- bind their first parameter as
    ``key``, so both spellings run. Round-2 review found this by planting
    the keyword form beside a known-caught positional one: the positional
    control failed the checker and the keyword form passed it, which is the
    difference between a gate and a decoration.
    """
    path = _write_module(tmp_path, source)

    scan = facade.enumerate_env_reads([path])

    assert set(scan.names) == {"PROBOS_A"}, label
    assert scan.non_literal == [], label


@pytest.mark.parametrize(
    ("label", "source"),
    [
        ("getenv-splatted", "import os\ndef f():\n    return os.getenv(**NAMES)\n"),
        (
            "environ-get-splatted",
            "import os\ndef f():\n    return os.environ.get(**NAMES)\n",
        ),
    ],
)
def test_enumerate_env_reads_rejects_a_key_it_cannot_read(
    tmp_path: Path, label: str, source: str
) -> None:
    """A read whose key is unresolvable fails closed rather than passing.

    Dropping the old ``and node.args`` guard means these no longer look like
    "not an environment read at all"; they look like a read this scan cannot
    name, which is exactly what the non-literal channel is for.
    """
    path = _write_module(tmp_path, source)

    scan = facade.enumerate_env_reads([path])

    assert scan.names == {}, label
    assert len(scan.non_literal) == 1, label
    assert scan.non_literal[0].startswith("sample.py:"), label


def test_enumerate_env_reads_leaves_ordinary_os_use_alone() -> None:
    """Over-detection is safe; false failure is not. ``os.path.expanduser`` is
    the live shape in ``config.py``, and a ``getattr`` on anything else is not
    this gate's business."""
    scan = facade.enumerate_env_reads([_CONFIG_MODULE])

    assert scan.non_literal == []
    assert set(scan.names) == {
        "PROBOS_LLM_URL",
        "PROBOS_NATS_ENABLED",
        "XDG_DATA_HOME",
    }


def test_enumerate_env_reads_does_not_bind_a_read_result_as_a_reader(
    tmp_path: Path,
) -> None:
    """``x = os.getenv("A")`` binds a string, not a callable.

    Descending into the call would make ``x`` look like an environment reader
    and turn every later ``x(...)`` into a phantom read.
    """
    path = _write_module(
        tmp_path,
        "import os\nx = os.getenv('PROBOS_A')\ndef f():\n    return x('PROBOS_B')\n",
    )

    scan = facade.enumerate_env_reads([path])

    assert set(scan.names) == {"PROBOS_A"}
    assert scan.non_literal == []


def test_a_field_named_environ_is_not_mistaken_for_the_environment(
    tmp_path: Path,
) -> None:
    """A hard failure must not be reachable by an unrelated attribute name.

    ``SandboxConfig.environ`` is an entirely plausible config field, and
    ``self.environ`` is an ``Attribute`` spelled ``environ``. Treating every
    such attribute as *provably* the process environment would have blocked e2
    on a model that has nothing to do with this gate.
    """
    path = _write_module(
        tmp_path,
        "from pydantic import BaseModel\n"
        "class SandboxConfig(BaseModel):\n"
        "    environ: dict[str, str] = {}\n"
        "    def merged(self, extra):\n"
        "        return {**self.environ, **extra}\n"
        "    def rebind(self):\n"
        "        local = self.environ\n"
        "        return local\n",
    )

    scan = facade.enumerate_env_reads([path])

    assert scan.names == {}
    assert scan.non_literal == []


def test_binding_an_attribute_target_does_not_claim_the_receiver(
    tmp_path: Path,
) -> None:
    """``self.env = os.environ`` binds an attribute, not the name ``self``."""
    path = _write_module(
        tmp_path,
        "import os\n"
        "class Holder:\n"
        "    def __init__(self):\n"
        "        self.env = os.environ\n"
        "    def get(self, key):\n"
        "        return self.env.get(key)\n",
    )

    scan = facade.enumerate_env_reads([path])

    # The mapping escaped onto an attribute this scan does not track, so it is
    # reported -- but as one unfollowable reference, not as ``self`` becoming
    # the environment.
    assert scan.names == {}
    assert len(scan.non_literal) == 1


# ---------------------------------------------------------------------------
# Aliases and tiering
# ---------------------------------------------------------------------------


def test_accepted_names_is_the_field_name_when_no_alias_is_declared() -> None:
    class M(BaseModel):
        plain: int = 1

    assert facade._accepted_names(M.model_fields["plain"], "plain") == ["plain"]


def test_accepted_names_lists_alias_choices_including_the_field_name() -> None:
    class M(BaseModel):
        warning_chars: int = Field(
            10000,
            validation_alias=AliasChoices("warning_chars", "token_budget_warning"),
        )

    accepted = facade._accepted_names(
        M.model_fields["warning_chars"], "warning_chars"
    )

    assert accepted == ["warning_chars", "token_budget_warning"]
    assert "warning_chars" in accepted


def test_alias_excluding_the_field_name_is_a_violation_not_a_recorded_fact() -> None:
    """With ``populate_by_name`` off and ``extra='ignore'``, the field-name
    spelling would be swallowed with no error and the field would take its
    default -- an existing ``config/system.yaml`` key silently stops working."""

    class M(BaseModel):
        warning_chars: int = Field(10000, validation_alias=AliasChoices("only_alias"))

    accepted = facade._accepted_names(
        M.model_fields["warning_chars"], "warning_chars"
    )
    assert accepted == ["only_alias"]

    inspected = facade.model_record("M", M)
    assert inspected.alias_violations == ["M.warning_chars accepts ['only_alias']"]

    # The behaviour the rule protects against, measured rather than asserted.
    assert M(warning_chars=1).warning_chars == 10000
    assert M(only_alias=1).warning_chars == 1


def test_accepted_names_falls_back_to_a_plain_alias() -> None:
    class M(BaseModel):
        value: int = Field(1, alias="renamed")

    assert facade._accepted_names(M.model_fields["value"], "value") == ["renamed"]


def test_classify_separates_the_owned_contract_from_import_leakage() -> None:
    import math

    class Owned(BaseModel):
        pass

    Owned.__module__ = facade.FACADE_MODULE

    assert facade._classify(Owned) == ("model", "owned")
    assert facade._classify(BaseModel) == ("model", "incidental")
    assert facade._classify(math) == ("module", "incidental")
    assert facade._classify(Path) == ("class", "incidental")
    assert facade._classify(2.5) == ("constant", "owned")
    assert facade._classify(frozenset({"a"})) == ("constant", "owned")


def test_config_models_package_is_derived_from_the_scanned_directory() -> None:
    """One constant, so ownership and the G2 scan cannot point at two places."""
    assert facade.CONFIG_MODELS_RELDIR == "src/probos/config_models"
    assert facade.CONFIG_MODELS_PACKAGE == "probos.config_models"


@pytest.mark.parametrize(
    ("module", "expected"),
    [
        ("probos.config", True),
        ("probos.config_models", True),
        ("probos.config_models.sensorium", True),
        ("probos.config_models.experience.sensorium", True),
        # Not owned: this is exactly the import leakage the incidental tier
        # records, and `startswith("probos.")` would silently absorb it.
        ("probos.types", False),
        ("probos.substrate.agent", False),
        # A near-miss package name must fail loudly rather than keep the tier
        # while G2's scan -- pointed at config_models/ -- goes blind.
        ("probos.config_modelsx", False),
        ("probos.configuration", False),
        ("pydantic.main", False),
        ("typing", False),
        ("pathlib", False),
        (None, False),
        ("", False),
    ],
)
def test_owns_accepts_the_facade_and_the_package_g2_scans(
    module: str | None, expected: bool
) -> None:
    assert facade.owns(module) is expected


def test_a_model_moved_into_config_models_is_still_owned() -> None:
    """The predicate AD-1270e2 must be able to satisfy.

    Ownership was ``__module__ == "probos.config"``, which is the one property
    a real extraction is guaranteed to break: moving the class and re-exporting
    it reclassified it as leakage and failed on four counts, measured. A
    baseline a correct move cannot pass is worse than no baseline.
    """

    class Moved(BaseModel):
        pass

    Moved.__module__ = "probos.config_models.experience"
    assert facade._classify(Moved) == ("model", "owned")

    Moved.__module__ = "probos.types"
    assert facade._classify(Moved) == ("model", "incidental")


def test_a_moved_function_is_owned_too() -> None:
    """e2 moves helpers as well as models; both carry ``__module__``."""

    def helper() -> None:
        return None

    helper.__module__ = "probos.config_models.paths"
    assert facade._classify(helper) == ("function", "owned")

    helper.__module__ = "pydantic.fields"
    assert facade._classify(helper) == ("function", "incidental")


def test_no_live_incidental_name_would_be_re_owned_by_the_widened_predicate(
    baseline: dict[str, Any],
) -> None:
    """The widening must not quietly absorb an existing leak.

    Every incidental row today resolves to ``pydantic.*``, ``typing`` or
    ``pathlib``; none is under ``probos.``. Asserted against the baseline so a
    future leak from elsewhere in ``probos`` cannot arrive already-owned.
    """
    incidental = {
        name for name, row in baseline["names"].items() if row["tier"] == "incidental"
    }

    assert incidental, "the baseline records no incidental names at all"
    assert not any(facade.owns(f"probos.{name}") for name in ("types", "runtime"))
    assert {"BaseModel", "Field", "Path", "Any"} <= incidental


def test_model_record_records_a_non_instantiable_model_instead_of_crashing() -> None:
    """Six models raise on ``M()``; a generator that crashes on the first one
    produces a partial baseline that looks complete."""

    class Required(BaseModel):
        must_be_given: int

    inspected = facade.model_record("Required", Required)

    assert inspected.instantiable is False
    assert inspected.schema_available is True
    assert inspected.record["fields"] == [
        {"name": "must_be_given", "default": "<required>"}
    ]


def test_model_record_records_a_schema_failure_instead_of_crashing() -> None:
    """``BaseModel.model_json_schema()`` raises ``PydanticUserError``."""
    inspected = facade.model_record("BaseModel", BaseModel)

    assert inspected.schema_available is False
    assert inspected.record["schema_sha256"] is None


def test_model_record_flags_default_factory_and_validate_default() -> None:
    class M(BaseModel):
        made: list[int] = Field(default_factory=list)
        checked: int = Field(1, validate_default=True)

    fields = {entry["name"]: entry for entry in facade.model_record("M", M).record["fields"]}

    assert fields["made"]["has_default_factory"] is True
    assert fields["checked"]["validate_default"] is True
    assert "has_default_factory" not in fields["checked"]


# ---------------------------------------------------------------------------
# Tripwires -- the e2 hand-off
# ---------------------------------------------------------------------------


_SINGLE_FILE_SCAN = (
    "_REPO_ROOT = Path(__file__).resolve().parent.parent\n"
    '_DEFAULT_CONFIG_MODULE = _REPO_ROOT / "src" / "probos" / "config.py"\n'
)
_PACKAGE_SCAN = (
    "_REPO_ROOT = Path(__file__).resolve().parent.parent\n"
    '_DEFAULT_CONFIG_MODULE = _REPO_ROOT / "src" / "probos" / "config_models"\n'
)
_SELECTOR_WITHOUT = (
    'BLAST_RADIUS_PATTERNS: tuple[str, ...] = (\n'
    '    "src/probos/config.py",\n'
    '    "pyproject.toml",\n'
    ")\n"
)
_SELECTOR_WITH = (
    'BLAST_RADIUS_PATTERNS: tuple[str, ...] = (\n'
    '    "src/probos/config.py",\n'
    '    "src/probos/config_models/*",\n'
    ")\n"
)


def _tripwire_repo(
    tmp_path: Path, *, models: bool, profiles: str, selector: str
) -> Path:
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / "check_config_profiles.py").write_text(
        profiles, encoding="utf-8"
    )
    (tmp_path / "scripts" / "select_tests.py").write_text(selector, encoding="utf-8")
    if models:
        (tmp_path / facade.CONFIG_MODELS_RELDIR).mkdir(parents=True, exist_ok=True)
    return tmp_path


def test_tripwires_stay_silent_until_config_models_exists(tmp_path: Path) -> None:
    """e1 must not fail today; ``src/probos/config_models/`` does not exist."""
    repo = _tripwire_repo(
        tmp_path, models=False, profiles=_SINGLE_FILE_SCAN, selector=_SELECTOR_WITHOUT
    )

    assert facade.tripwire_problems(repo) == []


def test_tripwire_fires_when_the_profiles_scan_is_still_a_single_file(
    tmp_path: Path,
) -> None:
    repo = _tripwire_repo(
        tmp_path, models=True, profiles=_SINGLE_FILE_SCAN, selector=_SELECTOR_WITH
    )

    problems = facade.tripwire_problems(repo)

    assert len(problems) == 1
    assert problems[0].startswith("facade-tripwire-config-profiles-scan:")


def test_tripwire_fires_when_the_selector_has_no_config_models_pattern(
    tmp_path: Path,
) -> None:
    repo = _tripwire_repo(
        tmp_path, models=True, profiles=_PACKAGE_SCAN, selector=_SELECTOR_WITHOUT
    )

    problems = facade.tripwire_problems(repo)

    assert len(problems) == 1
    assert problems[0].startswith("facade-tripwire-selector-blast-radius:")


def test_tripwires_clear_once_e2_has_updated_both(tmp_path: Path) -> None:
    repo = _tripwire_repo(
        tmp_path, models=True, profiles=_PACKAGE_SCAN, selector=_SELECTOR_WITH
    )

    assert facade.tripwire_problems(repo) == []


def test_tripwires_are_silent_against_the_live_tree() -> None:
    # Pinned ``not ...is_dir()`` until AD-1270e2 created the package. That was a
    # statement about the tree of the day, not a property; the durable claim is
    # that on THIS tree both tripwires are satisfied, which now means satisfied
    # rather than dormant.
    assert (_REPO_ROOT / facade.CONFIG_MODELS_RELDIR).is_dir()
    assert facade.tripwire_problems(_REPO_ROOT) == []


def test_config_profiles_scan_shape_is_read_without_importing_probos() -> None:
    live = (_REPO_ROOT / "scripts" / "check_config_profiles.py").read_text(
        encoding="utf-8"
    )

    # Pinned ``is True`` for the live file pre-e2. AD-1270e2 widened that scan to
    # the package, so the live answer is now False and the True case comes from
    # the fixture -- the instrument must still tell the two shapes apart.
    assert facade.config_profiles_scan_is_single_file(live) is False
    assert facade.config_profiles_scan_is_single_file(_SINGLE_FILE_SCAN) is True
    assert facade.config_profiles_scan_is_single_file(_PACKAGE_SCAN) is False


def test_blast_radius_patterns_parses_the_literal_tuple() -> None:
    live = (_REPO_ROOT / "scripts" / "select_tests.py").read_text(encoding="utf-8")

    patterns = facade.blast_radius_patterns(live)

    assert "src/probos/config.py" in patterns
    assert facade.blast_radius_patterns("x = 1\n") == []


# ---------------------------------------------------------------------------
# Comparison -- a mutated surface must go red, with a distinct message each
# ---------------------------------------------------------------------------


def _model_surface(name: str, model: type[BaseModel]) -> dict[str, Any]:
    inspected = facade.model_record(name, model)
    return {
        "pydantic_version": "2.12.5",
        "counts": {"public_names": 1, "owned": 1},
        "surface_counts": {"public_names": 1, "owned": 1},
        "names": {name: {"kind": "model", "tier": "owned"}},
        "constants": {},
        "models": {name: inspected.record},
    }


class SensoriumConfig(BaseModel):
    """Stands in for the real model across the e2 move."""

    warning_chars: int = 10000
    hard_limit: int = 20000


def test_a_reexport_passes_the_identity_check() -> None:
    """``from probos.config_models.experience import SensoriumConfig`` is the
    *same class object*: qualname, MRO and field order all survive."""
    stored = _model_surface("SensoriumConfig", SensoriumConfig)
    actual = copy.deepcopy(stored)
    actual["counts"] = stored["surface_counts"]

    assert facade.compare_surface(stored, actual) == []


def test_a_reimplementation_fails_the_identity_check() -> None:
    """A wrapper subclass still satisfies every ``from probos.config import
    SensoriumConfig``, so a name-only check would pass it while ``isinstance``
    consumers broke.

    The wrapper is disguised as far as it can be: same name, same qualname,
    same field tuple, same defaults. The field dimension therefore cannot tell
    the two apart -- asserted below rather than assumed -- and identity is what
    is left to catch it.
    """

    class Wrapper(SensoriumConfig):
        pass

    Wrapper.__name__ = "SensoriumConfig"
    Wrapper.__qualname__ = "SensoriumConfig"

    stored = _model_surface("SensoriumConfig", SensoriumConfig)
    actual = _model_surface("SensoriumConfig", Wrapper)
    actual["counts"] = actual.pop("surface_counts")

    # The premise: every field-level dimension agrees, so only identity is left.
    assert (
        actual["models"]["SensoriumConfig"]["fields"]
        == stored["models"]["SensoriumConfig"]["fields"]
    )
    assert (
        actual["models"]["SensoriumConfig"]["qualname"]
        == stored["models"]["SensoriumConfig"]["qualname"]
    )

    codes = [p.split(":")[0] for p in facade.compare_surface(stored, actual)]

    assert "facade-model-bases" in codes
    # Renaming a class after creation cannot rewrite its already-built schema
    # title, so the digest independently catches it too. Both signals firing is
    # the belt-and-braces, not the claim.
    assert "facade-schema-digest" in codes


def test_a_partial_clone_fails_on_the_field_tuple() -> None:
    class Clone(BaseModel):
        warning_chars: int = 10000

    Clone.__qualname__ = "SensoriumConfig"

    stored = _model_surface("SensoriumConfig", SensoriumConfig)
    actual = _model_surface("SensoriumConfig", Clone)
    actual["counts"] = actual.pop("surface_counts")

    codes = {p.split(":")[0] for p in facade.compare_surface(stored, actual)}

    assert "facade-field-removed" in codes
    assert "facade-schema-digest" in codes


def _pair() -> tuple[dict[str, Any], dict[str, Any]]:
    stored = _model_surface("SensoriumConfig", SensoriumConfig)
    actual = copy.deepcopy(stored)
    actual["counts"] = actual.pop("surface_counts")
    return stored, actual


def test_compare_surface_reports_a_removed_owned_symbol() -> None:
    stored, actual = _pair()
    actual["names"].pop("SensoriumConfig")
    actual["models"].pop("SensoriumConfig")

    problems = facade.compare_surface(stored, actual)

    assert any(p.startswith("facade-symbol-removed:") for p in problems)


def test_compare_surface_reports_an_added_symbol() -> None:
    stored, actual = _pair()
    actual["names"]["NewThing"] = {"kind": "model", "tier": "owned"}

    problems = facade.compare_surface(stored, actual)

    assert any(p.startswith("facade-symbol-added:") for p in problems)


def test_compare_surface_reports_a_reordered_field_tuple() -> None:
    stored, actual = _pair()
    actual["models"]["SensoriumConfig"]["fields"].reverse()

    problems = facade.compare_surface(stored, actual)

    assert [p.split(":")[0] for p in problems] == ["facade-field-order"]


def test_compare_surface_reports_a_changed_default() -> None:
    stored, actual = _pair()
    actual["models"]["SensoriumConfig"]["fields"][0]["default"] = "999"

    problems = facade.compare_surface(stored, actual)

    assert [p.split(":")[0] for p in problems] == ["facade-field-default"]
    assert "warning_chars" in problems[0]


def test_compare_surface_reports_a_changed_schema_digest() -> None:
    stored, actual = _pair()
    actual["models"]["SensoriumConfig"]["schema_sha256"] = "0" * 64

    problems = facade.compare_surface(stored, actual)

    assert [p.split(":")[0] for p in problems] == ["facade-schema-digest"]


def test_compare_surface_reports_a_changed_tier() -> None:
    stored, actual = _pair()
    actual["names"]["SensoriumConfig"]["tier"] = "incidental"

    problems = facade.compare_surface(stored, actual)

    assert [p.split(":")[0] for p in problems] == ["facade-symbol-kind"]


def test_compare_surface_reports_a_dropped_alias() -> None:
    """Widening ownership must not soften any identity dimension.

    Dropping ``AliasChoices("warning_chars", "token_budget_warning")`` keeps the
    field name, order, default and type, so only the alias dimension can see it
    -- and an existing ``config/system.yaml`` key would stop being read with no
    error at all.
    """
    stored, actual = _pair()
    field_entry = actual["models"]["SensoriumConfig"]["fields"][0]
    stored["models"]["SensoriumConfig"]["fields"][0]["accepted_names"] = [
        "warning_chars",
        "token_budget_warning",
    ]
    field_entry.pop("accepted_names", None)

    problems = facade.compare_surface(stored, actual)

    assert [p.split(":")[0] for p in problems] == ["facade-field-alias"]
    assert "token_budget_warning" in problems[0]


def test_compare_surface_reports_a_renamed_field() -> None:
    """A rename is a removal plus an addition, never a silent substitution."""
    stored, actual = _pair()
    actual["models"]["SensoriumConfig"]["fields"][0]["name"] = "warn_chars"

    codes = [p.split(":")[0] for p in facade.compare_surface(stored, actual)]

    assert sorted(codes) == ["facade-field-added", "facade-field-removed"]


def test_compare_surface_reports_count_drift() -> None:
    stored, actual = _pair()
    actual["counts"]["owned"] = 290

    problems = facade.compare_surface(stored, actual)

    assert [p.split(":")[0] for p in problems] == ["facade-counts"]


def test_a_pydantic_upgrade_reports_one_root_cause_not_224_digests() -> None:
    """Schema digests are not comparable across pydantic versions. Emitting one
    explained error beats emitting a derived error per model."""
    stored, actual = _pair()
    actual["pydantic_version"] = "2.13.0"
    actual["models"]["SensoriumConfig"]["schema_sha256"] = "0" * 64

    problems = facade.compare_surface(stored, actual)

    assert [p.split(":")[0] for p in problems] == ["facade-pydantic-version"]


def test_compare_surface_reports_a_changed_constant() -> None:
    stored, actual = _pair()
    stored["constants"] = {"THRESHOLD": "0.75"}
    actual["constants"] = {"THRESHOLD": "0.9"}

    problems = facade.compare_surface(stored, actual)

    assert [p.split(":")[0] for p in problems] == ["facade-constant-value"]


# ---------------------------------------------------------------------------
# check() -- error mapping, without paying for subprocesses
# ---------------------------------------------------------------------------


def _stub_surface(**overrides: Any) -> dict[str, Any]:
    surface: dict[str, Any] = {
        "pydantic_version": "2.12.5",
        "counts": {},
        "names": {},
        "constants": {},
        "models": {},
        "non_instantiable": [],
        "schema_unavailable": [],
        "models_with_model_config": [],
        "canonical_dump_sha256": facade.digest({}),
        "canonical_flat": {},
        "derived_order_violations": [],
        "alias_violations": [],
    }
    surface.update(overrides)
    return surface


def _stub_baseline(tmp_path: Path, **overrides: Any) -> Path:
    document: dict[str, Any] = {
        "schema_version": facade.BASELINE_SCHEMA_VERSION,
        "baseline_id": facade.BASELINE_ID,
        "review": dict(facade.DEFAULT_REVIEW),
        "surface_counts": {},
        "names": {},
        "constants": {},
        "models": {},
        "non_instantiable": [],
        "schema_unavailable": [],
        "models_with_model_config": [],
        "environment": {"control_variable": facade.CONTROL_VARIABLE, "reads": []},
    }
    document.update(overrides)
    path = tmp_path / "baseline.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def _empty_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "src" / "probos").mkdir(parents=True)
    (repo / "src" / "probos" / "config.py").write_text("", encoding="utf-8")
    return repo


def _fake_child(**surface: Any):
    """A stub that branches on ``emit``, as the real child does."""

    def run(repo_root, emit, scrub, inject=None):  # noqa: ANN001, ANN202
        if emit == "capture":
            return _stub_surface(**surface)
        return {"flat": dict(surface.get("canonical_flat") or {})}

    return run


def test_check_maps_an_alias_violation_to_its_own_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        facade,
        "run_child",
        lambda *a, **k: _stub_surface(alias_violations=["M.x accepts ['y']"]),
    )

    result = facade.check(_stub_baseline(tmp_path), repo_root=_empty_repo(tmp_path))

    assert any(
        p.startswith("facade-alias-excludes-field-name:") for p in result.errors
    )


def test_check_maps_a_derived_order_violation_to_its_own_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        facade,
        "run_child",
        lambda *a, **k: _stub_surface(derived_order_violations=["M: order moved"]),
    )

    result = facade.check(_stub_baseline(tmp_path), repo_root=_empty_repo(tmp_path))

    assert any(p.startswith("facade-derived-order:") for p in result.errors)


def test_check_reports_a_model_config_appearing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Today zero models carry one; ``model_config`` decides
    ``populate_by_name`` and ``extra`` for every field on the model."""
    monkeypatch.setattr(
        facade,
        "run_child",
        lambda *a, **k: _stub_surface(models_with_model_config=["Loose"]),
    )

    result = facade.check(_stub_baseline(tmp_path), repo_root=_empty_repo(tmp_path))

    assert any(p.startswith("facade-model-config:") for p in result.errors)


def test_check_reports_a_shrinking_non_instantiable_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(facade, "run_child", lambda *a, **k: _stub_surface())
    baseline = _stub_baseline(tmp_path, non_instantiable=["PeerConfig"])

    result = facade.check(baseline, repo_root=_empty_repo(tmp_path))

    assert any(p.startswith("facade-non-instantiable:") for p in result.errors)


def test_check_reports_an_undeclared_environment_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _empty_repo(tmp_path)
    (repo / "src" / "probos" / "config.py").write_text(
        "import os\nx = os.environ.get('PROBOS_BRAND_NEW')\n", encoding="utf-8"
    )
    monkeypatch.setattr(facade, "run_child", _fake_child(canonical_flat={"a": 1}))

    result = facade.check(_stub_baseline(tmp_path), repo_root=repo)

    assert any(
        p.startswith("facade-env-undeclared:") and "PROBOS_BRAND_NEW" in p
        for p in result.errors
    )


def test_check_reports_an_undeclared_read_reached_through_an_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The bypass has to be closed *end to end*, not only in the scanner.

    ``enumerate_env_reads`` is one call inside ``check``; a shape that the
    scanner now resolves but that ``check`` still waves through would leave the
    gate exactly as open as before.
    """
    repo = _empty_repo(tmp_path)
    (repo / "src" / "probos" / "config.py").write_text(
        "import os as _os\nx = _os.getenv('PROBOS_BRAND_NEW')\n", encoding="utf-8"
    )
    monkeypatch.setattr(facade, "run_child", _fake_child(canonical_flat={"a": 1}))

    result = facade.check(_stub_baseline(tmp_path), repo_root=repo)

    assert any(
        p.startswith("facade-env-undeclared:") and "PROBOS_BRAND_NEW" in p
        for p in result.errors
    )


def test_check_reports_an_environ_reference_it_cannot_follow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _empty_repo(tmp_path)
    (repo / "src" / "probos" / "config.py").write_text(
        "import os\nsnapshot = dict(os.environ)\n", encoding="utf-8"
    )
    monkeypatch.setattr(facade, "run_child", _fake_child(canonical_flat={"a": 1}))

    result = facade.check(_stub_baseline(tmp_path), repo_root=repo)

    assert any(p.startswith("facade-env-nonliteral:") for p in result.errors)


def test_check_reports_a_computed_environment_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _empty_repo(tmp_path)
    (repo / "src" / "probos" / "config.py").write_text(
        "import os\np = 'X'\nx = os.environ.get(p + 'Y')\n", encoding="utf-8"
    )
    monkeypatch.setattr(facade, "run_child", _fake_child(canonical_flat={"a": 1}))

    result = facade.check(_stub_baseline(tmp_path), repo_root=repo)

    assert any(p.startswith("facade-env-nonliteral:") for p in result.errors)


def test_check_reports_a_control_row_that_moved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A control that moves means the harness is broken and every other row it
    produced is meaningless."""
    repo = _empty_repo(tmp_path)
    calls: list[Any] = []

    def fake_child(repo_root, emit, scrub, inject=None):  # noqa: ANN001
        calls.append(inject)
        if emit == "capture":
            return _stub_surface(canonical_flat={"a": 1})
        return {"flat": {"a": 2}}

    monkeypatch.setattr(facade, "run_child", fake_child)

    result = facade.check(_stub_baseline(tmp_path), repo_root=repo)

    assert any(p.startswith("facade-env-control:") for p in result.errors)
    assert (facade.CONTROL_VARIABLE, facade._DEFAULT_SENTINEL) in calls


def test_check_reports_a_capture_child_that_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise facade.ChildFailure("child exited 1")

    monkeypatch.setattr(facade, "run_child", explode)

    result = facade.check(_stub_baseline(tmp_path), repo_root=_empty_repo(tmp_path))

    assert [p.split(":")[0] for p in result.errors] == ["facade-capture"]


def test_check_warns_about_a_slow_run_but_does_not_fail_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The advisory budget reports; it does not turn the gate red.

    This test exists because the hard version of it broke the gate. The check
    measures 2.5s alone and measured 7.16s inside the gate, where 16 xdist
    workers compete for the CPU -- so a wall-clock failure marked a green tree
    red for a reason unrelated to correctness. Contention is a property of the
    machine, and a checker that fails on the machine is one people learn to
    ignore.
    """
    monkeypatch.setattr(facade, "run_child", lambda *a, **k: _stub_surface())
    monkeypatch.setattr(facade, "SELF_TIMEOUT_SECONDS", -1.0)

    result = facade.check(_stub_baseline(tmp_path), repo_root=_empty_repo(tmp_path))

    assert any(p.startswith("facade-slow:") for p in result.warnings)
    assert not any(p.startswith("facade-timeout:") for p in result.errors)
    assert result.errors == []


def test_check_still_fails_past_the_hard_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Softening the budget must not delete the guard.

    Load can multiply this check by three; it cannot multiply it by ten. Past
    the ceiling the check itself grew, which is the condition the original
    budget was actually for.
    """
    monkeypatch.setattr(facade, "run_child", lambda *a, **k: _stub_surface())
    monkeypatch.setattr(facade, "SELF_TIMEOUT_SECONDS", -2.0)
    monkeypatch.setattr(facade, "SELF_TIMEOUT_HARD_CEILING_SECONDS", -1.0)

    result = facade.check(_stub_baseline(tmp_path), repo_root=_empty_repo(tmp_path))

    assert any(p.startswith("facade-timeout:") for p in result.errors)
    # One report, not two: past the ceiling it is a failure, not also a warning.
    assert result.warnings == []


def test_the_advisory_budget_sits_far_below_the_ceiling() -> None:
    """The gap is the contention headroom, and it has to be a real gap."""
    assert facade.SELF_TIMEOUT_SECONDS < facade.SELF_TIMEOUT_HARD_CEILING_SECONDS
    assert (
        facade.SELF_TIMEOUT_HARD_CEILING_SECONDS >= facade.SELF_TIMEOUT_SECONDS * 5
    )


def test_a_green_check_reports_no_warnings_on_this_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Absent contention there is nothing to say, so nothing is said."""
    monkeypatch.setattr(facade, "run_child", lambda *a, **k: _stub_surface())

    result = facade.check(_stub_baseline(tmp_path), repo_root=_empty_repo(tmp_path))

    assert result.warnings == []


def test_the_baseline_is_read_by_parsing_it_never_by_hashing_its_bytes() -> None:
    """Why no byte-hash comparison is newline-normalised: there is none.

    ``core.autocrlf`` is on and the repo ships no ``.gitattributes``, so this
    file is CRLF in a Windows working tree and LF in the index -- measured,
    169,144 bytes against 165,350, identical once newlines are folded. A raw
    ``read_bytes()`` probe therefore disagrees with ``git show :path`` on
    Windows and agrees on Linux, which is a property of the probe, not of the
    artifact.

    Normalising an in-tree comparison would fix nothing, because the checker
    and this suite compare *parsed documents* and content digests taken over
    parsed structures. Rewriting the generator to force LF was rejected: every
    other generated doc in ``scripts/`` writes with the platform default, and a
    one-off here would be a silent divergence from that convention. So the
    property is pinned instead -- the document a reader gets must not depend on
    the line endings it arrived with.
    """
    text = _BASELINE.read_text(encoding="utf-8")
    crlf = text.replace("\r\n", "\n").replace("\n", "\r\n")
    lf = crlf.replace("\r\n", "\n")

    assert crlf != lf, "the fixture must actually differ in line endings"
    assert yaml.safe_load(crlf) == yaml.safe_load(lf)
    assert facade.digest(yaml.safe_load(crlf)) == facade.digest(yaml.safe_load(lf))


# ---------------------------------------------------------------------------
# Baseline document
# ---------------------------------------------------------------------------


def test_committed_baseline_parses_and_carries_its_review_block(
    baseline: dict[str, Any],
) -> None:
    assert baseline["schema_version"] == facade.BASELINE_SCHEMA_VERSION
    assert baseline["baseline_id"] == facade.BASELINE_ID
    for key in ("owner", "rationale", "review_by"):
        assert str(baseline["review"][key]).strip()
    assert baseline["handoff_to_e2"]


def test_load_baseline_rejects_a_blank_review_field(tmp_path: Path) -> None:
    review = dict(facade.DEFAULT_REVIEW)
    review["rationale"] = "   "
    path = _stub_baseline(tmp_path, review=review)

    _, problems = facade.load_baseline(path)

    assert any("review.rationale is blank" in problem for problem in problems)


def test_load_baseline_reports_a_missing_file(tmp_path: Path) -> None:
    _, problems = facade.load_baseline(tmp_path / "absent.yaml")

    assert problems and problems[0].startswith("facade-baseline-missing:")


def test_load_baseline_rejects_a_malformed_document(tmp_path: Path) -> None:
    path = tmp_path / "b.yaml"
    path.write_text("- just\n- a list\n", encoding="utf-8")

    _, problems = facade.load_baseline(path)

    assert problems and problems[0].startswith("facade-baseline-schema:")


def test_committed_baseline_records_the_measured_surface(
    baseline: dict[str, Any],
) -> None:
    """The numbers AD-1270e1 was drafted against, re-measured on this tree."""
    counts = baseline["surface_counts"]

    assert counts["public_names"] == 304
    assert counts["owned"] == 291
    assert counts["incidental"] == 13
    assert counts["own_models"] == 224
    assert counts["field_definitions"] == 1784
    assert counts["aliased_fields"] == 1
    assert len(baseline["names"]) == 304
    assert len(baseline["models"]) == 225


def test_committed_baseline_records_the_awkward_models(
    baseline: dict[str, Any],
) -> None:
    assert baseline["non_instantiable"] == [
        "A2APeerConfig",
        "BaseModel",
        "DutyDefinition",
        "EPSDepartmentConfig",
        "MCPServerConfig",
        "PeerConfig",
    ]
    assert baseline["schema_unavailable"] == ["BaseModel"]
    assert baseline["models_with_model_config"] == []


def test_committed_baseline_freezes_the_one_aliased_field(
    baseline: dict[str, Any],
) -> None:
    fields = baseline["models"]["SensoriumConfig"]["fields"]
    aliased = [entry for entry in fields if "accepted_names" in entry]

    assert len(aliased) == 1
    assert aliased[0]["name"] == "warning_chars"
    assert aliased[0]["accepted_names"] == ["warning_chars", "token_budget_warning"]
    assert aliased[0]["name"] in aliased[0]["accepted_names"]


def test_committed_baseline_records_three_env_reads_plus_a_control(
    baseline: dict[str, Any],
) -> None:
    """Risk 7: a differential that cannot show a *known* mover has asserted
    nothing. ``PROBOS_NATS_ENABLED`` is that known mover."""
    rows = {row["name"]: row for row in baseline["environment"]["reads"]}
    control = baseline["environment"]["control_variable"]

    assert set(rows) - {control} == {
        "PROBOS_NATS_ENABLED",
        "PROBOS_LLM_URL",
        "XDG_DATA_HOME",
    }
    assert rows["PROBOS_NATS_ENABLED"]["moves"] == ["nats.enabled"]
    assert rows["PROBOS_NATS_ENABLED"]["mechanism"] == "config-field-validator"
    assert rows["PROBOS_LLM_URL"]["moves"] == ["cognitive.llm_base_url"]
    assert rows["PROBOS_LLM_URL"]["mechanism"] == "model-validator"
    assert rows[control]["moves"] == []


def test_xdg_row_carries_the_structural_reason_not_the_windows_measurement(
    baseline: dict[str, Any],
) -> None:
    """The measured zero was taken on Windows, where ``resolve_archive_db_path``
    takes the ``win32`` branch and the XDG line is unreachable -- so it does not
    discriminate. The load-bearing claim is that the read sits in a module-level
    function, which cannot reach a ``SystemConfig()`` default on any platform.
    The row stays in the differential so Linux CI re-proves it."""
    rows = {row["name"]: row for row in baseline["environment"]["reads"]}

    assert rows["XDG_DATA_HOME"]["mechanism"] == "module-function"
    assert rows["XDG_DATA_HOME"]["reaches_defaults"] is False
    assert rows["XDG_DATA_HOME"]["moves"] == []


def test_committed_baseline_has_no_platform_dependent_path_values() -> None:
    """A raw dump is Windows-only and turns Linux CI red while ``--check``
    passes locally -- measured three commits running on the config reference."""
    text = _BASELINE.read_text(encoding="utf-8")

    assert "WindowsPath" not in text
    assert "PosixPath" not in text
    assert "'data/captains_log'" in text
    assert "'data/plan_of_day'" in text
    assert "'data/agent_probes.db'" in text
    assert "data\\captains_log" not in text


def test_committed_baseline_carries_no_absolute_path_or_timestamp() -> None:
    text = _BASELINE.read_text(encoding="utf-8")

    assert "d:/ProbOS" not in text and "D:/ProbOS" not in text
    assert "/home/" not in text and "/Users/" not in text
    assert "generated_at" not in text


def test_committed_baseline_records_every_incidental_leak(
    baseline: dict[str, Any],
) -> None:
    """Recorded so nothing is invisible; removing one is a reviewable diff."""
    incidental = {
        name for name, row in baseline["names"].items() if row["tier"] == "incidental"
    }

    assert incidental == {
        "AliasChoices",
        "Any",
        "BaseModel",
        "Field",
        "Literal",
        "Path",
        "annotations",
        "field_validator",
        "math",
        "model_validator",
        "os",
        "urllib",
        "yaml",
    }
    assert all(
        baseline["names"][name]["removable_in"] == "e3" for name in incidental
    )


# ---------------------------------------------------------------------------
# Environment isolation and path derivation
# ---------------------------------------------------------------------------


def test_scrubbed_env_removes_every_probos_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROBOS_NATS_ENABLED", "true")
    monkeypatch.setenv("PROBOS_SOME_SECRET", "value-that-must-not-travel")
    monkeypatch.setenv("XDG_DATA_HOME", "/somewhere")

    env = facade.scrubbed_env(_REPO_ROOT, {"XDG_DATA_HOME"})

    assert not [name for name in env if name.startswith("PROBOS_")]
    assert "XDG_DATA_HOME" not in env
    assert "value-that-must-not-travel" not in env.values()


def test_scrubbed_env_injects_exactly_one_name_and_marks_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROBOS_NATS_ENABLED", "false")

    env = facade.scrubbed_env(
        _REPO_ROOT, {"PROBOS_NATS_ENABLED"}, inject=("PROBOS_NATS_ENABLED", "true")
    )

    assert env["PROBOS_NATS_ENABLED"] == "true"
    assert env[facade._INJECTED_MARKER] == "PROBOS_NATS_ENABLED"
    assert [n for n in env if n.startswith("PROBOS_")] == ["PROBOS_NATS_ENABLED"]


def test_scrubbed_env_points_pythonpath_at_the_repo_source_tree() -> None:
    env = facade.scrubbed_env(Path("/somewhere/else"), set())

    assert env["PYTHONPATH"] == str(Path("/somewhere/else") / "src")


def test_capture_child_refuses_an_unscrubbed_environment() -> None:
    """Without this the harness cannot tell a scrubbed capture from an inherited
    one, and an inherited one is the artifact this slice exists to prevent."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_REPO_ROOT / "src")
    env["PROBOS_NATS_ENABLED"] = "true"
    env.pop(facade._INJECTED_MARKER, None)

    proc = subprocess.run(
        [sys.executable, "-P", str(_SCRIPT), "--emit", "dump"],
        env=env,
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )

    assert proc.returncode != 0
    assert "capture environment is not scrubbed" in proc.stderr
    assert "PROBOS_NATS_ENABLED" in proc.stderr
    assert "true" not in proc.stderr.split("names only, never values")[-1].replace(
        "PROBOS_NATS_ENABLED", ""
    )


def test_repo_root_derives_from_file_so_a_linked_worktree_is_not_bypassed(
    tmp_path: Path,
) -> None:
    """Preflight runs in a materialized linked worktree. A hardcoded source root
    would silently validate the primary checkout and pass."""
    copied_scripts = tmp_path / "scripts"
    copied_scripts.mkdir()
    copied = copied_scripts / "check_config_facade.py"
    copied.write_text(_SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")

    module = _load("_ad1270e1_copied", copied)

    assert module._REPO_ROOT == tmp_path
    assert module._DEFAULT_BASELINE == (
        tmp_path / "docs" / "development" / "config-facade-baseline.yaml"
    )


def test_checker_source_hardcodes_no_absolute_path() -> None:
    source = _SCRIPT.read_text(encoding="utf-8")

    assert "d:\\ProbOS" not in source and "d:/ProbOS" not in source
    assert "D:\\ProbOS" not in source and "D:/ProbOS" not in source
    assert "Path(__file__).resolve().parent.parent" in source


def test_checker_does_not_import_probos_at_module_scope() -> None:
    """The parent process must stay free of ``probos.config``: an ambient value
    reaching a comparison here is the whole failure mode."""
    tree = ast.parse(_SCRIPT.read_text(encoding="utf-8"))
    module_scope_imports: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            module_scope_imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            module_scope_imports.append(node.module)

    assert not [name for name in module_scope_imports if name.startswith("probos")]


# ---------------------------------------------------------------------------
# The contract itself, and its gate registration
# ---------------------------------------------------------------------------


def test_check_is_green_on_the_committed_baseline() -> None:
    """The one expensive test: the real five-subprocess contract, end to end."""
    proc = subprocess.run(
        [sys.executable, "-P", "scripts/check_config_facade.py", "--check"],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stderr
    assert "config facade check passed" in proc.stdout
    assert "names=304" in proc.stdout


def test_config_facade_runs_between_the_other_two_config_phases() -> None:
    """Keeping the config phases adjacent is the point; ``test_run_test_gate``
    owns the exact-list assertion that it is registered at all."""
    source = (_REPO_ROOT / "scripts" / "run_test_gate.py").read_text(encoding="utf-8")

    assert "scripts/check_config_facade.py" in source
    assert (
        source.index('"config-profiles"')
        < source.index('"config-facade"')
        < source.index('"ad-ledger"')
    )
