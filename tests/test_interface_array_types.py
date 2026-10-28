"""Fixed interface slots retain identity without acquiring value semantics."""

from dataclasses import FrozenInstanceError

import pytest

from tc_emulator import ArgumentError, Runtime, memory, types
from tc_emulator.syntax import Location


def descriptor(bounds=((-1, 0), (2, 3))):
    return types.InterfaceArrayType(bounds, types.InterfaceType("i"))


def test_descriptor_shape_bounds_and_immutability():
    kind = descriptor()
    assert kind.bounds == ((-1, 0), (2, 3))
    assert kind.shape == (2, 2)
    assert kind.size == 4
    assert str(kind) == "ARRAY[-1..0, 2..3] OF I"
    with pytest.raises(FrozenInstanceError):
        kind.bounds = ((0, 0),)


@pytest.mark.parametrize(
    "bounds", [(), ((2, 1),), ((True, 2),), ((-2147483649, 0),), ((0, 1000000),), ((0, 0),) * 9]
)
def test_descriptor_preserves_existing_array_bound_checks(bounds):
    with pytest.raises((TypeError, ValueError)):
        descriptor(bounds)


@pytest.mark.parametrize("element", ["I", "", 1, types.StringType(4)])
def test_descriptor_requires_an_interface_descriptor(element):
    with pytest.raises((TypeError, ValueError)):
        types.InterfaceArrayType(((0, 0),), element)


def test_storage_is_distinct_row_major_and_passively_inspectable():
    kind = descriptor()
    slots = tuple(memory.InterfaceSlot(kind.element_type) for _ in range(kind.size))
    array = memory.InterfaceArray(kind, slots)
    assert len({id(item) for item in array.items}) == 4
    assert array._element((-1, 3)) is slots[1]
    assert array._element((0, 2)) is slots[2]
    rt = Runtime.from_source(
        "INTERFACE I END_INTERFACE FUNCTION_BLOCK B IMPLEMENTS I END_FUNCTION_BLOCK"
    )
    target = rt.instantiate("B")
    slots[1].bind(target._frame, Location("slots.st", 1, 1))
    snapshot = array.inspect()
    assert snapshot == (
        (
            {"interface": "I", "target": None, "valid": False},
            {"interface": "I", "target": "B", "valid": True},
        ),
        (
            {"interface": "I", "target": None, "valid": False},
            {"interface": "I", "target": None, "valid": False},
        ),
    )
    snapshot[0][1]["target"] = "changed"
    target._frame.lifetime.alive = False
    assert array.inspect()[0][1] == {"interface": "I", "target": "B", "valid": False}
    for indices in ((True, 2), (-2, 2), (-1,), (-1, 2, 3), (0, 2.0)):
        with pytest.raises((TypeError, IndexError)):
            array._element(indices)


def test_interface_arrays_are_rejected_at_every_value_boundary():
    kind = descriptor()
    rt = Runtime.from_source("")
    assert not types.is_value_type(kind)
    for operation in (
        lambda: types.resolve_type(kind, {}),
        lambda: types.resolve_type("Named", {"NAMED": kind}),
        lambda: types.check_value(kind, ((0, 0), (0, 0))),
        lambda: types.default_value(kind),
        lambda: types.value_leaf_count(kind),
        lambda: types.array_initial_value(kind, [0]),
        lambda: types.ArrayType(((0, 0),), kind.element_type),
        lambda: types.ArrayType(((0, 0),), kind),
    ):
        with pytest.raises((TypeError, ValueError)):
            operation()
    with pytest.raises(ArgumentError):
        rt.cell(kind, ((0, 0), (0, 0)))
