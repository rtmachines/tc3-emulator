"""Exercise standard PLC support through actual ST and the public Python API."""

import pytest

from tc_emulator import ArgumentError, ExecutionError, Runtime, ValidationError


def test_word_storage_bounds_and_inout_are_distinct_from_uint():
    runtime = Runtime.from_source("""FUNCTION Increment:WORD
    VAR_IN_OUT value:WORD; END_VAR
    value:=value+1; Increment:=value; END_FUNCTION""")
    value = runtime.cell("WORD", 65534)
    assert runtime.call("Increment", value=value).value == 65535
    for invalid in (-1, 65536, True, 1.0):
        with pytest.raises(ArgumentError):
            runtime.cell("WORD", invalid)
    with pytest.raises(ArgumentError):
        runtime.call("Increment", value=runtime.cell("UINT", 1))
    with pytest.raises(ValidationError):
        Runtime.from_source("TYPE E:(First,Second) WORD; END_TYPE")


@pytest.mark.parametrize("kind", ["R_TRIG", "F_TRIG", "CTU", "CTD", "CTUD", "SR", "RS"])
def test_standard_blocks_are_directly_available_without_st_source(kind):
    block = Runtime.from_source("").instantiate(kind)
    block.call()
    assert block.inspect()


def test_invalid_counter_arguments_do_not_change_inputs_or_consume_edges():
    runtime = Runtime.from_source("")
    counter = runtime.instantiate("CTU")
    with pytest.raises(ArgumentError):
        counter.call(CU=True, PV=65536)
    assert counter.inspect()["CU"] is False
    counter.call(CU=True, PV=2)
    assert counter.output("CV") == 1
    counter.call()
    assert counter.output("CV") == 1
    runtime.advance_time(10000)
    assert counter.output("CV") == 1


def test_counter_output_binding_and_saturation_use_word_storage():
    runtime = Runtime.from_source("""FUNCTION F:WORD
    VAR c:CTUD; result:WORD; END_VAR
    c.CV:=65535; c(CU:=TRUE,PV:=3,CV=>result);
    F:=result; END_FUNCTION""")
    assert runtime.call("F").value == 65535


def test_function_local_trigger_is_fresh_but_nested_fb_trigger_persists():
    runtime = Runtime.from_source("""FUNCTION F:BOOL
    VAR edge:R_TRIG; END_VAR edge(CLK:=TRUE); F:=edge.Q; END_FUNCTION
    FUNCTION_BLOCK B
    VAR_OUTPUT pulse:BOOL; END_VAR VAR edge:R_TRIG; END_VAR
    edge(CLK:=TRUE,Q=>pulse); END_FUNCTION_BLOCK""")
    assert runtime.call("F").value is True
    assert runtime.call("F").value is True
    block = runtime.instantiate("B")
    block.call()
    assert block.output("pulse") is True
    block.call()
    assert block.output("pulse") is False


@pytest.mark.parametrize(
    ("expression", "type_name", "expected"),
    [
        ("ABS(-7)", "DINT", 7),
        ("MIN(4,2,8)", "DINT", 2),
        ("MAX(IN2:=8,IN0:=4,IN1:=2)", "DINT", 8),
        ("LIMIT(MIN:=2,IN:=9,MAX:=5)", "DINT", 5),
        ("LIMIT(MN:=2,IN:=-1,MX:=5)", "DINT", 2),
        ("DINT_TO_REAL(16777217)", "REAL", 16777216.0),
        ("REAL_TO_DINT(REAL#2.5)", "DINT", 2),
        ("TO_INT(-3.5)", "INT", -4),
        ("TIME_TO_UDINT(T#1s)", "UDINT", 1000),
        ("UDINT_TO_TIME(1500)", "TIME", 1500),
        ("BOOL_TO_WORD(TRUE)", "WORD", 1),
        ("WORD_TO_BOOL(2)", "BOOL", True),
    ],
)
def test_standard_operators_and_conversions_execute_in_st(expression, type_name, expected):
    runtime = Runtime.from_source(f"FUNCTION F:{type_name} F:={expression}; END_FUNCTION")
    assert runtime.call("F").value == expected


def test_selection_skips_unselected_calls_and_evaluates_chosen_call_once():
    runtime = Runtime.from_source("""FUNCTION Bump:DINT
    VAR_IN_OUT count:DINT; END_VAR count:=count+1; Bump:=count; END_FUNCTION
    FUNCTION F:DINT
    VAR_IN_OUT count:DINT; END_VAR
    F:=SEL(TRUE, 1/0, MUX(20, Bump(count), Bump(count)));
    END_FUNCTION""")
    count = runtime.cell("DINT", 0)
    assert runtime.call("F", count=count).value == 1
    assert count.value == 1


def test_selection_supports_structs_and_enum_minimum():
    runtime = Runtime.from_source("""TYPE E:(Low:=0,High:=10); END_TYPE
    TYPE S:STRUCT state:E; END_STRUCT END_TYPE
    FUNCTION F:S
    VAR a:S; b:S:=(state:=E.High); END_VAR
    F:=SEL(FALSE,a,b); F.state:=MIN(E.Low,E.High); END_FUNCTION""")
    assert runtime.call("F").value["state"].name == "LOW"


def test_named_eager_arguments_evaluate_in_source_order():
    runtime = Runtime.from_source("""FUNCTION Bump:DINT
    VAR_IN_OUT count:DINT; END_VAR count:=count+1; Bump:=count; END_FUNCTION
    FUNCTION F:DINT VAR_IN_OUT count:DINT; END_VAR
    F:=LIMIT(MAX:=Bump(count),IN:=Bump(count),MIN:=0); END_FUNCTION""")
    count = runtime.cell("DINT", 0)
    assert runtime.call("F", count=count).value == 1
    assert count.value == 2


@pytest.mark.parametrize(
    "expression",
    [
        "SEL(TRUE,TRUE,1)",
        "MUX(0,1,TRUE)",
        "ABS(TRUE)",
        "INT_TO_BOOL(TRUE)",
        "LIMIT(1,2)",
        "MIN(IN0:=1,IN2:=2)",
        "MAX(1,IN1:=2)",
        "TO_INT(E.A)",
    ],
)
def test_builtin_validation_checks_all_arguments_even_if_unselected(expression):
    with pytest.raises(ValidationError):
        Runtime.from_source(f"TYPE E:(A,B); END_TYPE FUNCTION F:DINT F:={expression}; END_FUNCTION")


@pytest.mark.parametrize("expression", ["TO_UINT(-1)", "TO_WORD(65536)", "MUX(-1,4,5)"])
def test_runtime_builtin_errors_have_location_and_call_stack(expression):
    runtime = Runtime.from_source(
        f"FUNCTION F:DINT F:={expression}; END_FUNCTION", source="operators.st"
    )
    with pytest.raises(ExecutionError) as error:
        runtime.call("F")
    assert error.value.loc.source == "operators.st"
    assert error.value.stack == ("F",)


@pytest.mark.parametrize("name", ["R_TRIG", "CTUD", "MIN", "REAL_TO_INT", "TO_TIME"])
def test_builtin_names_cannot_be_redefined_as_pous_or_types(name):
    for text in (f"FUNCTION {name}:BOOL END_FUNCTION", f"TYPE {name}:INT; END_TYPE"):
        with pytest.raises(ValidationError):
            Runtime.from_source(text)


def test_tcpou_import_combines_constants_and_standard_operators(tmp_path):
    path = tmp_path / "F_Clamp.TcPOU"
    path.write_text(
        """<TcPlcObject Version="1.1.0.1"><POU Name="F_Clamp">
    <Declaration><![CDATA[FUNCTION F_Clamp:INT
    VAR_INPUT value:REAL; END_VAR
    VAR CONSTANT lower:REAL:=1.5; upper:REAL:=lower*2; END_VAR
    ]]></Declaration>
    <Implementation><ST><![CDATA[
    F_Clamp:=REAL_TO_INT(LIMIT(lower,value,upper));
    ]]></ST></Implementation></POU></TcPlcObject>""",
        encoding="utf-8",
    )
    runtime = Runtime.from_files([path])
    assert runtime.call("F_Clamp", value=100).value == 3
    assert runtime.call("F_Clamp", value=0).value == 2


def test_standard_calls_participate_in_execution_step_budget():
    runtime = Runtime.from_source("FUNCTION F:INT F:=ABS(-1); END_FUNCTION", max_steps=1)
    with pytest.raises(ExecutionError, match="budget"):
        runtime.call("F")
