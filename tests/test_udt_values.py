"""Composite value boundaries remain immutable, typed and independently copied."""

import pytest

from tc_emulator import types as t


def config_type():
    state = t.EnumType("E_State", (("Idle", 0), ("Run", 10)))
    return t.StructType(
        "ST_Config",
        (t.StructField("speed", "REAL", 1.5), t.StructField("state", state)),
    )


def test_struct_partial_mapping_uses_defaults_and_case_insensitive_access():
    kind = config_type()
    value = t.check_value(kind, {"SPEED": 0.1})
    assert value.type_name == "ST_CONFIG"
    assert value["speed"] == 0.10000000149011612
    assert value["state"].name == "IDLE"
    assert value["state"].value == 0
    assert tuple(value) == ("SPEED", "STATE")
    with pytest.raises(TypeError):
        value["speed"] = 2.0


@pytest.mark.parametrize(
    "invalid", [{"missing": 1}, {"speed": 1, "SPEED": 2}, {1: 2}, {"speed": True}, []]
)
def test_struct_rejects_invalid_mapping_atomically(invalid):
    with pytest.raises((TypeError, ValueError)):
        t.check_value(config_type(), invalid)


def test_nested_struct_array_values_are_detached_recursively():
    config = config_type()
    kind = t.StructType("ST_Group", (t.StructField("items", t.ArrayType(((1, 2),), config)),))
    original = {"items": [{"speed": 2}, {"state": "Run"}]}
    value = t.check_value(kind, original)
    original["items"][0]["speed"] = 99
    assert value["items"][0]["speed"] == 2.0
    assert value["items"][1]["speed"] == 1.5
    assert value["items"][1]["state"].type_name == "E_STATE"
    with pytest.raises(TypeError):
        value["items"][0]["speed"] = 10


def test_enum_members_are_typed_and_default_prefers_zero_then_first():
    kind = t.EnumType("E_State", (("First", 10), ("Zero", 0), ("Next", 11)))
    assert t.default_value(kind).name == "ZERO"
    value = t.check_value(kind, "e_state.Next")
    assert (value.name, value.value, value.type_name) == ("NEXT", 11, "E_STATE")
    assert t.check_value(kind, value) == value
    other = t.EnumType("E_Other", (("First", 10),))
    assert t.default_value(other).name == "FIRST"
    explicit = t.EnumType("E_Explicit", (("A", 0), ("B", 2)), default_member="B")
    assert t.default_value(explicit).value == 2
    for invalid in (10, True, "missing", "E_Other.First", t.default_value(other)):
        with pytest.raises((TypeError, ValueError)):
            t.check_value(kind, invalid)


def test_aliases_preserve_defaults_with_transparent_compatibility():
    scalar = t.AliasType("T_Speed", "REAL", 2.5)
    assert t.default_value(scalar) == 2.5
    assert t.same_type(scalar, "REAL")
    assert t.canonical_type(scalar) == "REAL"
    config = config_type()
    alias = t.AliasType("T_Config", config, t.check_value(config, {"speed": 3, "state": "Run"}))
    assert t.check_value(alias, {"speed": 4})["state"].name == "RUN"
    assert t.same_type(alias, config)
    assert not t.same_type(config, t.StructType("Other", config.fields))


def test_named_array_elements_resolve_and_aliases_of_arrays_keep_shape():
    config = config_type()
    unresolved = t.ArrayType(((1, 2),), "ST_Config")
    resolved = t.resolve_type(unresolved, {"ST_CONFIG": config})
    assert resolved.element_type == config
    assert t.is_value_type(resolved)
    with pytest.raises(ValueError):
        t.resolve_type(unresolved, {})
    alias = t.AliasType("Pair", t.ArrayType(((3, 4),), "INT"))
    outer = t.ArrayType(((1, 2),), alias)
    assert t.check_value(outer, [[1, 2], [3, 4]]) == ((1, 2), (3, 4))
    assert t.value_leaf_count(outer) == 4


def test_partial_array_initializer_uses_each_struct_default():
    kind = t.ArrayType(((-1, 1),), config_type())
    value = t.array_initial_value(kind, [{"speed": 4}])
    assert tuple(item["speed"] for item in value) == (4.0, 1.5, 1.5)
    assert t.value_leaf_count(kind) == 6
