"""Grammar contracts for standalone PROGRAMs and named global lists."""

import pytest

from tc_emulator.errors import ParseError
from tc_emulator.parser import parse
from tc_emulator.syntax import Location, Program


def test_program_sections_and_body_preserve_source_positions():
    program = parse(
        """PROGRAM Main
VAR n : INT := 2; END_VAR
VAR CONSTANT limit : INT := 9; END_VAR
VAR_INPUT enabled : BOOL; END_VAR
VAR_OUTPUT done : BOOL; END_VAR
VAR_TEMP scratch : INT; END_VAR
n := n + 1;
END_PROGRAM""",
        "machine.st",
    )
    pou = program.pous[0]
    assert (pou.kind, pou.name, pou.return_type) == ("PROGRAM", "MAIN", None)
    assert [var.section for var in pou.variables] == [
        "VAR",
        "VAR",
        "VAR_INPUT",
        "VAR_OUTPUT",
        "VAR_TEMP",
    ]
    assert [var.constant for var in pou.variables] == [False, True, False, False, False]
    assert pou.variables[0].initial.value == 2
    assert pou.body[0].loc == Location("machine.st", 7, 1)


def test_mixed_sources_collect_all_global_sections_as_one_named_list():
    program = parse(
        """TYPE Sample : INT; END_TYPE
VAR_GLOBAL count : Sample := 4; END_VAR
PROGRAM Main END_PROGRAM
VAR_GLOBAL CONSTANT limit : INT := 8; END_VAR""",
        "mixed.st",
        gvl_name="Plant",
    )
    assert [pou.name for pou in program.pous] == ["MAIN"]
    assert [decl.name for decl in program.types] == ["SAMPLE"]
    (gvl,) = program.gvls
    assert gvl.name == "PLANT"
    assert not gvl.qualified_only
    assert gvl.loc == Location("mixed.st", 2, 1)
    assert [var.name for var in gvl.variables] == ["COUNT", "LIMIT"]
    assert [var.section for var in gvl.variables] == ["VAR_GLOBAL", "VAR_GLOBAL"]
    assert [var.constant for var in gvl.variables] == [False, True]


def test_qualified_only_applies_to_whole_list_with_location_mapping():
    program = parse(
        "{attribute 'qualified_only'}\nVAR_GLOBAL x : INT; END_VAR\nVAR_GLOBAL y : BOOL; END_VAR",
        locations={2: Location("original.TcGVL:Declaration", 20, 3)},
    )
    (gvl,) = program.gvls
    assert gvl.name == "GVL"
    assert gvl.qualified_only
    assert gvl.loc == Location("original.TcGVL:Declaration", 20, 3)
    assert gvl.variables[0].loc == Location("original.TcGVL:Declaration", 20, 14)


@pytest.mark.parametrize(
    "source",
    [
        "PROGRAM P : INT END_PROGRAM",
        "PROGRAM P VAR_IN_OUT x : INT; END_VAR END_PROGRAM",
        "PROGRAM P VAR_GLOBAL x : INT; END_VAR END_PROGRAM",
        "PROGRAM P VAR_INPUT CONSTANT x : INT := 1; END_VAR END_PROGRAM",
        "{attribute 'unknown'} VAR_GLOBAL x : INT; END_VAR",
        "{attribute 'qualified_only'} PROGRAM P END_PROGRAM",
        "VAR_GLOBAL x : INT; END_VAR {attribute 'qualified_only'} VAR_GLOBAL y:INT; END_VAR",
        "{attribute 'qualified_only'} {attribute 'qualified_only'} VAR_GLOBAL x:INT; END_VAR",
        "{attribute 'qualified_only' := 'yes'} VAR_GLOBAL x:INT; END_VAR",
        "{attribute 'qualified_only' VAR_GLOBAL x:INT; END_VAR",
        "VAR_GLOBAL x : INT; END_VAR x := 4;",
        "VAR_GLOBAL RETAIN x : INT; END_VAR",
        "VAR_GLOBAL VAR_INPUT x : INT; END_VAR",
    ],
)
def test_rejects_unsupported_program_and_global_syntax(source):
    with pytest.raises(ParseError):
        parse(source)


@pytest.mark.parametrize("name", ["", "bad-name", "1Plant", "PROGRAM", "x.y", "żółć", None, 4])
def test_global_list_metadata_requires_a_valid_identifier(name):
    with pytest.raises(ParseError):
        parse("VAR_GLOBAL x : INT; END_VAR", gvl_name=name)


def test_empty_global_section_still_declares_a_namespace():
    (gvl,) = parse("VAR_GLOBAL END_VAR").gvls
    assert (gvl.name, gvl.variables) == ("GVL", ())
    assert Program((), ()).gvls == ()
