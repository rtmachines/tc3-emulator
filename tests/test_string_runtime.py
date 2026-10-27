"""Text values exercised through real ST and public Python calls."""

import pytest

from tc_emulator import ArgumentError, ExecutionError, Runtime, RuntimeFaultedError


def test_python_string_cell_normalizes_nul_and_capacity_without_mutating_on_error():
    import tc_emulator

    runtime = Runtime.from_source("")
    value = runtime.cell(tc_emulator.StringType(4), "caféine")
    assert value.value == "café"
    value.value = "A\0hidden"
    assert value.value == "A"
    for invalid in (123, b"text", "ok\0\u20ac", "hello\u20ac"):
        with pytest.raises(ArgumentError):
            value.value = invalid
        assert value.value == "A"
    assert runtime.cell("STRING", "x" * 81).value == "x" * 80
    assert runtime.cell("STRING[3]", "four").value == "fou"


@pytest.mark.parametrize(
    "expression,kind,expected",
    [
        ("'Abc'", "STRING(3)", "Abc"),
        ("STRING#'caf$E9'", "STRING(4)", "café"),
        ("'X$00ignored'", "STRING(20)", "X"),
        ("LEN('caf$E9')", "INT", 4),
        ("LEFT('abcde',2)", "STRING(10)", "ab"),
        ("RIGHT('abcde',2)", "STRING(10)", "de"),
        ("MID(POS:=2,STR:='abcde',LEN:=3)", "STRING(10)", "bcd"),
        ("CONCAT(STR2:='bar',STR1:='foo')", "STRING(10)", "foobar"),
        ("FIND('ababa','ba')", "INT", 2),
        ("INSERT('AB','x',0)", "STRING(10)", "xAB"),
        ("DELETE('ABCDE',2,2)", "STRING(10)", "ADE"),
        ("REPLACE(P:=2,L:=2,STR2:='x',STR1:='ABCDE')", "STRING(10)", "AxDE"),
        ("DINT_TO_STRING(-2147483648)", "STRING(12)", "-2147483648"),
        ("DWORD_TO_STRING(DWORD#16#FFFF_FFFF)", "STRING(12)", "4294967295"),
        ("STRING_TO_DINT('-12_345')", "DINT", -12345),
        ("TO_WORD('65535')", "WORD", 65535),
        ("TO_STRING(TRUE)", "STRING(10)", "TRUE"),
        ("TO_BOOL('True')", "BOOL", False),
        ("STRING_TO_BOOL('true')", "BOOL", True),
    ],
)
def test_text_and_conversion_expressions_execute_in_st(expression, kind, expected):
    runtime = Runtime.from_source(f"FUNCTION F:{kind} F:={expression}; END_FUNCTION")
    assert runtime.call("F").value == expected


@pytest.mark.parametrize(
    "operator,expected",
    [("=", False), ("<>", True), ("<", True), ("<=", True), (">", False), (">=", False)],
)
def test_text_comparison_is_case_sensitive_across_capacities(operator, expected):
    runtime = Runtime.from_source(f"""FUNCTION F:BOOL
    VAR a:STRING(2):='A'; b:STRING(20):='a'; END_VAR
    F:=a {operator} b; END_FUNCTION""")
    assert runtime.call("F").value is expected


def test_input_result_and_output_copies_truncate_at_each_destination():
    runtime = Runtime.from_source("""FUNCTION Shorten:STRING(3)
    VAR_INPUT text:STRING(5); END_VAR VAR_OUTPUT echoed:STRING(4); END_VAR
    echoed:=text; Shorten:=text; text:='local'; END_FUNCTION
    FUNCTION F:STRING(10)
    VAR source:STRING(10):='ABCDEF'; result:STRING(2); END_VAR
    Shorten(text:=source, echoed=>result);
    F:=CONCAT(source,result); END_FUNCTION""")
    result = runtime.call("Shorten", text="ABCDEF")
    assert result.value == "ABC"
    assert result.outputs["echoed"] == "ABCD"
    assert runtime.call("F").value == "ABCDEFAB"


def test_struct_array_string_aliases_survive_whole_parent_replacement():
    runtime = Runtime.from_source("""TYPE Name:STRING(5); END_TYPE
    TYPE S:STRUCT names:ARRAY[1..2] OF Name; END_STRUCT END_TYPE
    FUNCTION Change:BOOL VAR_IN_OUT group:S; name:Name; END_VAR
    VAR replacement:S := (names:=['first','other']); END_VAR
    group:=replacement; name:=CONCAT(name,'!'); Change:=TRUE; END_FUNCTION""")
    group = runtime.cell("S", {"names": ["old", "value"]})
    alias = group.field("names").element(2)
    old_snapshot = group.value
    assert runtime.call("Change", group=group, name=alias).value is True
    assert alias.value == "other"
    assert old_snapshot["names"] == ("old", "value")
    group.value = {"names": ["a", "b"]}
    assert alias.value == "b"
    alias.value = "caféxx"
    assert group.value["names"] == ("a", "caféx")


def test_python_inout_capacity_is_exact_and_bad_fb_inputs_are_atomic():
    runtime = Runtime.from_source("""FUNCTION_BLOCK B
    VAR_INPUT enable:BOOL; text:STRING(4); END_VAR
    VAR_IN_OUT shared:STRING(4); END_VAR VAR_OUTPUT result:STRING(4); END_VAR
    IF enable THEN shared:=text; result:=shared; END_IF; END_FUNCTION_BLOCK""")
    block = runtime.instantiate("B")
    good = runtime.cell("STRING(4)", "old")
    with pytest.raises(ArgumentError):
        block.call(enable=True, text="new", shared=runtime.cell("STRING(5)", "bad"))
    assert block.inspect()["ENABLE"] is False
    with pytest.raises(ArgumentError):
        block.call(enable=True, text="\u20ac", shared=good)
    assert block.inspect()["ENABLE"] is False and good.value == "old"
    block.call(enable=True, text="caféxx", shared=good)
    assert block.output("result") == good.value == "café"


def test_fb_text_state_is_independent_and_temp_is_reset():
    runtime = Runtime.from_source("""FUNCTION_BLOCK B
    VAR_INPUT text:STRING(8); END_VAR VAR_OUTPUT history:STRING(20); END_VAR
    VAR_TEMP prefix:STRING(8):='>'; END_VAR
    history:=CONCAT(history,CONCAT(prefix,text)); prefix:='changed'; END_FUNCTION_BLOCK""")
    first, second = runtime.instantiate("B"), runtime.instantiate("B")
    first.call(text="one")
    first.call()
    second.call(text="two")
    assert first.output("history") == ">one>one"
    assert second.output("history") == ">two"


def test_lazy_string_selection_skips_invalid_conversion_and_preserves_longer_choice():
    runtime = Runtime.from_source("""FUNCTION F:STRING(10)
    F:=SEL(TRUE,DINT_TO_STRING(STRING_TO_DINT('invalid')),MUX(8,'x','longer'));
    END_FUNCTION""")
    assert runtime.call("F").value == "longer"


def test_named_text_arguments_keep_source_evaluation_order():
    runtime = Runtime.from_source("""FUNCTION Next:STRING(10)
    VAR_IN_OUT counter:INT; END_VAR counter:=counter+1; Next:=INT_TO_STRING(counter);
    END_FUNCTION FUNCTION F:STRING(10) VAR_IN_OUT counter:INT; END_VAR
    F:=CONCAT(STR2:=Next(counter),STR1:=Next(counter)); END_FUNCTION""")
    counter = runtime.cell("INT", 0)
    assert runtime.call("F", counter=counter).value == "21"
    assert counter.value == 2


def test_named_capacity_and_text_constant_comparison_work_at_runtime():
    runtime = Runtime.from_source("""FUNCTION F:STRING(size)
    VAR CONSTANT size:INT:=3; label:STRING(size):='abcdef'; ok:BOOL:=label='abc'; END_VAR
    VAR a:ARRAY[1..2] OF STRING(size):=['café','xy']; END_VAR
    IF ok THEN F:=a[1]; END_IF; END_FUNCTION""")
    assert runtime.call("F").value == "caf"


@pytest.mark.parametrize(
    "expression,kind",
    [
        ("STRING_TO_INT('32768')", "INT"),
        ("TO_INT('12suffix')", "INT"),
        ("MID('abc',1,0)", "STRING(10)"),
        ("LEFT('abc',-1)", "STRING(10)"),
    ],
)
def test_text_execution_errors_include_source_and_fault_runtime(expression, kind):
    runtime = Runtime.from_source(
        f"FUNCTION F:{kind} F:={expression}; END_FUNCTION", source="strings.st"
    )
    cell = runtime.cell("STRING(4)", "kept")
    with pytest.raises(ExecutionError) as error:
        runtime.call("F")
    assert error.value.loc.source == "strings.st"
    assert error.value.stack == ("F",)
    assert cell.value == "kept"
    with pytest.raises(RuntimeFaultedError):
        cell.value = "new"


def test_tcpou_and_tcdut_load_text_with_escaped_quotes_and_comments(tmp_path):
    dut = tmp_path / "Label.TcDUT"
    dut.write_text("""<TcPlcObject><DUT Name="Label"><Declaration><![CDATA[
    TYPE Label:STRING(40); END_TYPE
    ]]></Declaration></DUT></TcPlcObject>""")
    pou = tmp_path / "F.TcPOU"
    pou.write_text("""<TcPlcObject><POU Name="F"><Declaration><![CDATA[
    FUNCTION F:Label
    ]]></Declaration><Implementation><ST><![CDATA[
    F:='Don$'t (* strip *) // café';
    ]]></ST></Implementation></POU></TcPlcObject>""")
    assert Runtime.from_files([pou, dut]).call("F").value == "Don't (* strip *) // café"


def test_untyped_ast_text_literal_uses_the_same_normalization_as_parsed_text():
    from dataclasses import replace

    from tc_emulator.parser import parse
    from tc_emulator.syntax import Literal

    program = parse("FUNCTION F:BOOL F:='x'='é'; END_FUNCTION")
    pou = program.pous[0]
    assignment = pou.body[0]
    comparison = assignment.value
    comparison = replace(comparison, left=Literal("é\0tail", comparison.left.loc))
    pou = replace(pou, body=(replace(assignment, value=comparison),))
    assert Runtime(replace(program, pous=(pou,))).call("F").value is True


@pytest.mark.parametrize("alias_left,alias_right", [(True, False), (False, True), (True, True)])
@pytest.mark.parametrize(
    "left,right,operator,expected",
    [
        ("abcTAIL", "abc\0tail", "=", True),
        ("abcTAIL", "abc\0tail", "<>", False),
        ("abcTAIL", "abc\0tail", "<", False),
        ("abcTAIL", "abc\0tail", "<=", True),
        ("abcTAIL", "abc\0tail", ">", False),
        ("abcTAIL", "abc\0tail", ">=", True),
        ("AbcTAIL", "abc\0tail", "=", False),
        ("AbcTAIL", "abc\0tail", "<>", True),
        ("AbcTAIL", "abc\0tail", "<", True),
        ("AbcTAIL", "abc\0tail", "<=", True),
        ("AbcTAIL", "abc\0tail", ">", False),
        ("AbcTAIL", "abc\0tail", ">=", False),
    ],
)
def test_alias_typed_ast_text_literals_compare_after_normalization(
    alias_left, alias_right, left, right, operator, expected
):
    from dataclasses import replace

    from tc_emulator import StringType
    from tc_emulator.parser import parse
    from tc_emulator.syntax import Literal
    from tc_emulator.types import AliasType

    program = parse(f"FUNCTION F:BOOL F:='x'{operator}'y'; END_FUNCTION")
    pou = program.pous[0]
    assignment = pou.body[0]
    comparison = assignment.value
    left_type = StringType(3)
    right_type = StringType(8)
    if alias_left:
        left_type = AliasType("LeftText", left_type)
    if alias_right:
        right_type = AliasType("RightText", right_type)
    comparison = replace(
        comparison,
        left=Literal(left, comparison.left.loc, left_type),
        right=Literal(right, comparison.right.loc, right_type),
    )
    pou = replace(pou, body=(replace(assignment, value=comparison),))
    runtime = Runtime(replace(program, pous=(pou,)))
    assert runtime.call("F").value is expected
