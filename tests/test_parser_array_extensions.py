"""Open-array types and indexed callable syntax retain source and legacy paths."""

import pytest

from tc_emulator import syntax, types
from tc_emulator.errors import ParseError
from tc_emulator.parser import parse, parse_type


@pytest.mark.parametrize(
    "text,rank,element",
    [
        ("ARRAY[*] OF INT", 1, "INT"),
        ("ARRAY[*, *] OF STRING[12]", 2, types.StringType(12)),
        ("ARRAY[*,*,*,*,*,*,*,*] OF Item", 8, "ITEM"),
    ],
)
def test_open_types_parse_with_rank_and_element(text, rank, element):
    descriptor = parse_type(text)
    assert isinstance(descriptor, types.OpenArrayType)
    assert descriptor.rank == rank
    assert descriptor.element_type == element


def test_open_string_capacity_expression_retains_location_until_validation():
    pou = parse(
        "FUNCTION F : INT\nVAR_IN_OUT a : ARRAY[*,*] OF STRING(N + 1); END_VAR\nEND_FUNCTION",
        "open.st",
    ).pous[0]
    descriptor = pou.variables[0].type_name
    assert isinstance(descriptor, syntax.OpenArrayBounds)
    assert descriptor.rank == 2
    assert isinstance(descriptor.element_type, syntax.StringBounds)
    assert descriptor.element_type.length.left.parts == ("N",)
    assert descriptor.loc == syntax.Location("open.st", 2, 16)
    with pytest.raises(ParseError, match="capacity|constant|scope"):
        parse_type("ARRAY[*] OF STRING(N)")


@pytest.mark.parametrize(
    "text",
    [
        "ARRAY[*,1..2] OF INT",
        "ARRAY[1..2,*] OF INT",
        "ARRAY[] OF INT",
        "ARRAY[*,*,*,*,*,*,*,*,*] OF INT",
        "ARRAY[*,] OF INT",
    ],
)
def test_malformed_or_mixed_open_dimensions_fail_with_source_location(text):
    with pytest.raises(ParseError) as caught:
        parse_type(text)
    assert caught.value.loc.source == "<type>"


def test_fixed_unknown_elements_remain_array_types_for_validator_classification():
    assert parse_type("ARRAY[-1..1] OF FB_Motor") == types.ArrayType(((-1, 1),), "FB_MOTOR")
    pou = parse("PROGRAM P VAR a : ARRAY[1..N] OF FB_Motor; END_VAR END_PROGRAM").pous[0]
    assert isinstance(pou.variables[0].type_name, syntax.ArrayBounds)
    assert pou.variables[0].type_name.element_type == "FB_MOTOR"


@pytest.mark.parametrize("expression", [False, True])
@pytest.mark.parametrize(
    "target",
    ["blocks[i]", "blocks[i].Reset", "group.blocks[i].child.Reset", "group[i].blocks[j].Read"],
)
def test_indexed_call_targets_work_as_statements_and_expressions(target, expression):
    body = f"F := {target}(value := 3);" if expression else f"{target}(value := 3);"
    statement = parse(f"FUNCTION F : INT\n{body}\nEND_FUNCTION", "calls.st").pous[0].body[0]
    call = statement.value if expression else statement.call
    assert isinstance(call, syntax.Call)
    assert call.loc == syntax.Location("calls.st", 2, 6 if expression else 1)
    assert call.arguments[0].name == "VALUE"
    receiver = call.target
    if target == "blocks[i]":
        assert isinstance(receiver, syntax.Index)
        assert receiver.base.parts == ("BLOCKS",)
    else:
        assert isinstance(receiver, syntax.Member)
        assert receiver.name == target.rsplit(".", 1)[-1].upper()
        if target == "group.blocks[i].child.Reset":
            assert isinstance(receiver.base, syntax.Member)
            assert receiver.base.name == "CHILD"
            assert receiver.base.base.base.parts == ("GROUP", "BLOCKS")
        if target == "group[i].blocks[j].Read":
            assert isinstance(receiver.base, syntax.Index)
            assert isinstance(receiver.base.base, syntax.Member)
            assert receiver.base.base.name == "BLOCKS"
            assert receiver.base.indices[0].parts == ("J",)


def test_simple_call_paths_and_contextual_access_names_keep_reference_shape():
    pou = parse("FUNCTION F : INT inst.child(); F := Public.Private(); END_FUNCTION").pous[0]
    assert isinstance(pou.body[0].call.target, syntax.Reference)
    assert pou.body[0].call.target.parts == ("INST", "CHILD")
    assert pou.body[1].value.target.parts == ("PUBLIC", "PRIVATE")
