"""Non-value array descriptors and exact IN_OUT compatibility contracts."""

from dataclasses import FrozenInstanceError

import pytest

from tc_emulator import types


def test_open_descriptor_normalizes_elements_and_is_immutable():
    descriptor = types.OpenArrayType(2, "int")
    assert descriptor.rank == 2
    assert descriptor.element_type == "INT"
    assert str(descriptor) == "ARRAY[*, *] OF INT"
    with pytest.raises(FrozenInstanceError):
        descriptor.rank = 1


@pytest.mark.parametrize("rank", [0, 9, -1, True, 1.0, "1"])
def test_open_descriptor_rejects_invalid_rank(rank):
    with pytest.raises((TypeError, ValueError)):
        types.OpenArrayType(rank, "INT")


def test_fb_descriptor_normalizes_bounds_name_and_shape():
    descriptor = types.FBArrayType([[-2, 0], [4, 5]], "fb_motor")
    assert descriptor.bounds == ((-2, 0), (4, 5))
    assert descriptor.element_type == "FB_MOTOR"
    assert descriptor.shape == (3, 2)
    assert descriptor.size == 6
    assert str(descriptor) == "ARRAY[-2..0, 4..5] OF FB_MOTOR"
    assert not isinstance(descriptor, types.ArrayType)
    with pytest.raises(FrozenInstanceError):
        descriptor.element_type = "OTHER"


@pytest.mark.parametrize(
    "bounds", [(), ((2, 1),), ((True, 2),), ((-2147483649, 0),), ((0, 1000000),), ((0, 0),) * 9]
)
def test_fb_descriptor_preserves_fixed_array_bound_checks(bounds):
    with pytest.raises((TypeError, ValueError)):
        types.FBArrayType(bounds, "FB_MOTOR")


@pytest.mark.parametrize("element", ["bad.name", "", 1, types.StringType(4)])
def test_fb_descriptor_requires_an_instance_type_name(element):
    with pytest.raises((TypeError, ValueError)):
        types.FBArrayType(((0, 0),), element)


def test_open_canonical_elements_preserve_alias_transparency_and_nominal_identity():
    alias = types.AliasType("Count", "INT")
    opened = types.OpenArrayType(1, alias)
    assert types.canonical_type(opened) == types.OpenArrayType(1, "INT")
    assert types.inout_compatible(opened, types.ArrayType(((-3, 4),), "INT"))
    assert types.inout_compatible(opened, types.OpenArrayType(1, "INT"))
    assert not types.inout_compatible(opened, types.ArrayType(((0, 2),), "DINT"))
    assert not types.inout_compatible(opened, types.ArrayType(((0, 2), (1, 2)), "INT"))
    assert not types.inout_compatible(opened, "INT")
    assert not types.inout_compatible(opened, types.FBArrayType(((0, 2),), "FB"))
    structure = types.StructType("Item", ())
    assert types.inout_compatible(
        types.OpenArrayType(1, structure), types.ArrayType(((1, 2),), structure)
    )
    assert not types.inout_compatible(
        types.OpenArrayType(1, structure), types.ArrayType(((1, 2),), types.StructType("Other", ()))
    )


def test_fixed_inout_arrays_keep_exact_bounds_and_string_capacity():
    expected = types.ArrayType(((1, 2),), types.StringType(4))
    assert types.inout_compatible(expected, expected)
    assert not types.inout_compatible(expected, types.ArrayType(((0, 1),), types.StringType(4)))
    assert not types.inout_compatible(expected, types.OpenArrayType(1, types.StringType(4)))
    assert not types.inout_compatible(
        types.OpenArrayType(1, types.StringType(4)), types.ArrayType(((0, 1),), types.StringType(5))
    )


@pytest.mark.parametrize("kind", ["OpenArrayType", "FBArrayType"])
def test_nonvalue_descriptors_are_rejected_by_value_utilities(kind):
    descriptor = (
        types.OpenArrayType(1, "INT")
        if kind == "OpenArrayType"
        else types.FBArrayType(((0, 0),), "FB")
    )
    assert not types.is_value_type(descriptor)
    operations = [
        lambda: types.resolve_type(descriptor, {}),
        lambda: types.resolve_type("Named", {"NAMED": descriptor}),
        lambda: types.check_value(descriptor, (0,)),
        lambda: types.default_value(descriptor),
        lambda: types.value_leaf_count(descriptor),
        lambda: types.array_initial_value(descriptor, [0]),
    ]
    for operation in operations:
        with pytest.raises(TypeError):
            operation()
