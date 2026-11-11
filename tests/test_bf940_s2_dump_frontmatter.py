"""BF-940 slice 2 (#1686): ``dump_frontmatter``, the one place a frontmatter mapping becomes YAML text. Pure; no store."""

from __future__ import annotations

import collections
import datetime
import decimal
from typing import Any, NamedTuple

import pytest
import yaml

from probos.utils.frontmatter import dump_frontmatter

_SECRET = "SECRET_VALUE_NEVER_IN_A_MESSAGE"


class _Plain:
    pass


class _Text(str):
    pass


class _Pair(NamedTuple):
    a: int
    b: int


def _nested(depth: int) -> Any:
    value: Any = "leaf"
    for _ in range(depth):
        value = {"k": value}
    return value


@pytest.mark.parametrize("mapping", [
    pytest.param({"author": "alice", "classification": "private", "created": "2026-11-09T10:00:00+00:00", "tags": ["a", "717"], "metrics": {"trust_mean": 0.512, "active_agents": 54}}, id="a-store-envelope"),
    pytest.param({"topic": "x --- y: z", "note": "caf\u00e9 \u2014 line1\nline2\n", "long": "word " * 80}, id="dashes-unicode-multiline-and-a-long-value"),
    pytest.param({"none": None, "yes": True, "f": 1.5e-7, "big": 10**30, "empty": [], "nothing": {}}, id="none-bool-float-big-int-and-empty-containers"),
    pytest.param({"when": datetime.date(2026, 1, 1), "at": datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc), "raw": b"hi", "kinds": {1, 2}}, id="a-date-a-datetime-bytes-and-a-set"),
    pytest.param({"a": {"b": {"c": [1, [2, 3], {"d": "e"}]}}}, id="nested-lists-and-mappings"),
    pytest.param({1: "int key", None: "none key"}, id="keys-that-are-not-text"),
])
def test_a_mapping_the_readers_load_is_written_as_yaml_dump_wrote_it(mapping):
    """Tuple-free mappings: ``safe_load`` builds a tuple only for ``!!omap`` and ``!!pairs``, and V7 covers those (F2)."""
    assert dump_frontmatter(mapping) == yaml.dump(mapping, default_flow_style=False, sort_keys=False)


def test_a_tuple_is_written_as_a_list_and_nothing_python_is_tagged():
    text = dump_frontmatter({"t": (1, 2), "n": [(3, 4)], "m": {"k": ({"j": (5,)},)}})
    assert "!!python" not in text
    assert yaml.safe_load(text) == {"t": [1, 2], "n": [[3, 4]], "m": {"k": [{"j": [5]}]}}


@pytest.mark.parametrize("value", [
    pytest.param(_Plain(), id="an-object"),
    pytest.param(collections.OrderedDict(a=1), id="an-ordered-dict"),
    pytest.param(collections.defaultdict(int, a=1), id="a-default-dict"),
    pytest.param(frozenset({1}), id="a-frozenset"),
    pytest.param(_Pair(1, 2), id="a-named-tuple"),
    pytest.param(_Text("x"), id="a-str-subclass"),
    pytest.param(decimal.Decimal("1.5"), id="a-decimal"),
    pytest.param(1 + 2j, id="a-complex"),
])
def test_a_value_no_reader_loads_is_refused_naming_its_top_level_key(value):
    with pytest.raises(ValueError) as info:
        dump_frontmatter({"k_good": 1, "k_bad": {"deep": [value]}, "k_fine": "x"})
    message = str(info.value)
    assert "k_bad" in message and "k_good" not in message and "k_fine" not in message


def test_a_tuple_used_as_a_key_is_refused_though_safe_dump_writes_it():
    text = yaml.safe_dump({"k": {(1, 2): "x"}})
    with pytest.raises(yaml.YAMLError):
        yaml.safe_load(text)  # premise: safe_dump wrote what safe_load refuses
    with pytest.raises(ValueError) as info:
        dump_frontmatter({"k_good": 1, "k_bad": {(1, 2): "x"}})
    assert "k_bad" in str(info.value) and "k_good" not in str(info.value)


def test_a_value_is_never_in_the_message():
    with pytest.raises(ValueError) as info:
        dump_frontmatter({"k_bad": _Text(_SECRET)})
    assert _SECRET not in str(info.value)


def test_a_mapping_nested_too_deeply_is_a_value_error_not_a_recursion_error():
    assert yaml.safe_load(dump_frontmatter({"k": _nested(100)}))["k"]["k"]
    with pytest.raises(ValueError) as info:
        dump_frontmatter({"k_good": 1, "k_bad": _nested(600)})
    assert "k_bad" in str(info.value) and "k_good" not in str(info.value)


def test_an_empty_mapping_is_written_and_read_back():
    assert dump_frontmatter({}) == "{}\n" and yaml.safe_load("{}\n") == {}


@pytest.mark.parametrize("tag", ["!!omap", "!!pairs"])
def test_a_mapping_that_safe_load_builds_with_tuples_is_written_as_lists(tag):
    """F2: ``safe_load`` builds tuples for these two tags only; ``publish`` and the skill rewrite re-dump what it built."""
    built = yaml.safe_load(f"metrics: {tag} [{{a: 1}}, {{b: 2}}]\nname: x\n")
    assert built["metrics"] == [("a", 1), ("b", 2)], "premise: safe_load builds a list of tuples"
    assert "!!python/tuple" in yaml.dump(built, default_flow_style=False, sort_keys=False), "premise: yaml.dump tagged them"
    text = dump_frontmatter(built)
    as_lists = {"metrics": [["a", 1], ["b", 2]], "name": "x"}
    assert "!!python" not in text and yaml.safe_load(text) == as_lists
    assert text == yaml.dump(as_lists, default_flow_style=False, sort_keys=False)
    assert yaml.safe_load(text) != built, "equivalence holds for tuple-free values only: the tuples are lists now"
    assert dump_frontmatter(yaml.safe_load(text)) == text, "a second rewrite changes nothing"
