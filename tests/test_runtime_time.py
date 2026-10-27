"""TIME values and built-in timers execute inside ordinary Structured Text."""

import pytest

from tc_emulator import ArgumentError, ExecutionError, Runtime, RuntimeFaultedError


def test_time_arithmetic_keeps_type_through_variables_functions_and_unary_plus():
    runtime = Runtime.from_source("""FUNCTION Add:TIME
    VAR_INPUT a,b:TIME; END_VAR Add:=a+b; END_FUNCTION
    FUNCTION F:TIME
    VAR value:TIME:=T#1s; END_VAR
    F:=Add(a:=+value,b:=T#250ms)-T#10ms;
    END_FUNCTION""")
    assert runtime.call("F").value == 1240


@pytest.mark.parametrize(
    ("operator", "expected"),
    [("=", False), ("<>", True), ("<", True), ("<=", True), (">", False), (">=", False)],
)
def test_time_comparisons(operator, expected):
    runtime = Runtime.from_source(f"""FUNCTION F:BOOL
    VAR a:TIME:=T#1s; END_VAR F:=a {operator} T#1001ms; END_FUNCTION""")
    assert runtime.call("F").value is expected


@pytest.mark.parametrize(
    "expression",
    ["T#0ms-T#1ms", "T#4294967295ms+T#1ms", "(T#4294967295ms+T#1ms)-T#1ms"],
)
def test_each_time_operation_checks_overflow_and_underflow(expression):
    runtime = Runtime.from_source(f"FUNCTION F:TIME F:={expression}; END_FUNCTION", "time.st")
    with pytest.raises(ExecutionError) as error:
        runtime.call("F")
    assert error.value.loc.source == "time.st"
    assert error.value.stack == ("F",)
    with pytest.raises(RuntimeFaultedError):
        runtime.call("F")


def test_time_arrays_and_element_inout_aliases():
    runtime = Runtime.from_source("""FUNCTION Next:TIME
    VAR_IN_OUT duration:TIME; END_VAR
    duration:=duration+T#1ms; Next:=duration; END_FUNCTION
    FUNCTION F:ARRAY[-1..1] OF TIME
    VAR a:ARRAY[-1..1] OF TIME:=[2(T#100ms)]; END_VAR
    Next(duration:=a[0]); F:=a; END_FUNCTION""")
    assert runtime.call("F").value == (100, 101, 0)
    value = runtime.cell("ARRAY[1..2] OF TIME", [10, 20])
    assert runtime.call("Next", duration=value.element(2)).value == 21
    assert value.value == (10, 21)
    with pytest.raises(ArgumentError):
        runtime.call("Next", duration=runtime.cell("UDINT", 20))


def test_nested_timers_share_one_call_timestamp_with_output_bindings():
    runtime = Runtime.from_source("""FUNCTION_BLOCK Inner
    VAR_INPUT enable:BOOL; END_VAR
    VAR_OUTPUT done:BOOL; elapsed:TIME; END_VAR
    VAR delay:TON; END_VAR
    delay(IN:=enable,PT:=T#100ms,Q=>done,ET=>elapsed);
    END_FUNCTION_BLOCK
    FUNCTION_BLOCK Outer
    VAR_INPUT enable:BOOL; END_VAR
    VAR_OUTPUT done:BOOL; times:ARRAY[1..2] OF TIME; END_VAR
    VAR first,second:Inner; END_VAR
    first(enable:=enable); second(enable:=enable);
    done:=first.done AND second.done;
    times[1]:=first.elapsed; times[2]:=second.elapsed;
    END_FUNCTION_BLOCK""")
    outer = runtime.instantiate("Outer")
    outer.call(enable=True)
    runtime.advance_time(99)
    outer.call()
    snapshot = outer.inspect()
    assert outer.output("times") == (99, 99)
    assert outer.output("done") is False
    runtime.advance_time(1)
    outer.call()
    assert outer.output("times") == (100, 100)
    assert outer.output("done") is True
    assert snapshot["TIMES"] == (99, 99)
    assert snapshot["FIRST"]["DELAY"]["ET"] == 99


def test_timer_inputs_and_outputs_support_normal_st_field_access():
    runtime = Runtime.from_source("""FUNCTION_BLOCK B
    VAR_INPUT enable:BOOL; END_VAR VAR_OUTPUT done:BOOL; END_VAR
    VAR delay:TON; END_VAR
    delay.PT:=T#10ms; delay.IN:=enable; delay(); done:=delay.Q;
    END_FUNCTION_BLOCK""")
    block = runtime.instantiate("B")
    block.call(enable=True)
    runtime.advance_time(10)
    block.call()
    assert block.output("done") is True


def test_timers_in_function_locals_and_var_temp_restart_each_call():
    runtime = Runtime.from_source("""FUNCTION F:BOOL
    VAR delay:TON; END_VAR delay(IN:=TRUE,PT:=T#10ms); F:=delay.Q; END_FUNCTION
    FUNCTION_BLOCK B
    VAR_TEMP delay:TON; END_VAR VAR_OUTPUT done:BOOL; END_VAR
    delay(IN:=TRUE,PT:=T#10ms); done:=delay.Q; END_FUNCTION_BLOCK""")
    block = runtime.instantiate("B")
    assert runtime.call("F").value is False
    block.call()
    runtime.advance_time(1000)
    assert runtime.call("F").value is False
    block.call()
    assert block.output("done") is False


def test_builtin_call_consumes_budget_and_reports_nested_st_location():
    runtime = Runtime.from_source(
        "FUNCTION_BLOCK B VAR delay:TON; END_VAR delay(); END_FUNCTION_BLOCK",
        "budget.st",
        max_steps=1,
    )
    with pytest.raises(ExecutionError, match="budget") as error:
        runtime.instantiate("B").call()
    assert error.value.loc.source == "budget.st"
    assert error.value.stack == ("B", "TON")
