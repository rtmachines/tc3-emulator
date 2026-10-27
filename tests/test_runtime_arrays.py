"""Actual ST programs pin floating arithmetic and array copy/reference behavior."""

import math

import pytest

from tc_emulator import ArgumentError, ExecutionError, Runtime, RuntimeFaultedError


@pytest.mark.parametrize(("kind", "expected"), [("REAL", 0.0), ("LREAL", 1.0)])
def test_float_operations_round_to_declared_precision(kind, expected):
    rt = Runtime.from_source(f"""FUNCTION F:{kind}
    VAR x:{kind}:=16777216; END_VAR
    F := (x + 1) - x;
    END_FUNCTION""")
    assert rt.call("F").value == expected


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("1 / 3.0", 1 / 3),
        ("REAL#1 / REAL#3", 0.3333333432674408),
        ("REAL#16777217", 16777216.0),
        ("LREAL#16777217", 16777217.0),
        ("1.25e2 + 2E-1", 125.2),
        ("-REAL#0.1", -0.10000000149011612),
    ],
)
def test_float_literals_division_and_typed_rounding(expr, expected):
    rt = Runtime.from_source(f"FUNCTION F:LREAL F:={expr}; END_FUNCTION")
    assert rt.call("F").value == expected


@pytest.mark.parametrize("sign", ["", "-"])
@pytest.mark.parametrize(
    ("digits", "expected"),
    [
        ("1.00000005960464477539062499999999999", 1.0),
        ("1.000000059604644775390625", 1.0),
        ("1.00000005960464477539062500000000001", 1.0000001192092896),
        ("1.000000178813934326171875", 1.000000238418579),
        ("1152921573326323713", float(2**60 + 2**37)),
    ],
)
def test_typed_real_literal_rounds_decimal_value_once(sign, digits, expected):
    rt = Runtime.from_source(f"FUNCTION F:LREAL F:=REAL#{sign}{digits}; END_FUNCTION")
    assert rt.call("F").value == (-expected if sign else expected)


def test_large_integer_to_real_at_st_and_python_boundaries():
    number = 2**60 + 2**36 + 1
    expected = float(2**60 + 2**37)
    rt = Runtime.from_source(f"""FUNCTION LiteralValue:REAL
    LiteralValue := {number}; END_FUNCTION
    FUNCTION InputValue:REAL VAR_INPUT x:REAL; END_VAR InputValue:=x; END_FUNCTION
    FUNCTION InitialValue:ARRAY[1..1] OF REAL
    VAR a:ARRAY[1..1] OF REAL:=[{number}]; END_VAR InitialValue:=a; END_FUNCTION""")
    assert rt.call("LiteralValue").value == expected
    assert rt.call("InputValue", x=number).value == expected
    assert rt.call("InitialValue").value == (expected,)
    assert rt.cell("REAL", number).value == expected
    assert rt.cell("ARRAY[1..1] OF REAL", [number]).value == (expected,)


@pytest.mark.parametrize("digits", ["0.0", "0e999999999", "1e-999999999", "7.006492321624085e-46"])
def test_real_underflow_preserves_sign_without_huge_allocation(digits):
    rt = Runtime.from_source(f"FUNCTION F:REAL F:=REAL#-{digits}; END_FUNCTION")
    result = rt.call("F").value
    assert result == 0.0
    assert math.copysign(1, result) == -1


def test_real_subnormal_decimal_above_half_rounds_up():
    rt = Runtime.from_source("""FUNCTION F:REAL
    F:=REAL#7.006492321624086e-46; END_FUNCTION""")
    assert rt.call("F").value == 2.0**-149


def test_numeric_promotion_also_precedes_comparison():
    rt = Runtime.from_source("""FUNCTION F:BOOL
    VAR x:REAL:=16777216; END_VAR
    F := (x = 16777217) AND (x <> LREAL#16777217);
    END_FUNCTION""")
    assert rt.call("F").value is True


@pytest.mark.parametrize("expr", ["REAL#3e38 * REAL#2", "LREAL#1e308 * 2.0", "1.0 / 0.0"])
def test_float_execution_errors_fault_runtime(expr):
    rt = Runtime.from_source(f"FUNCTION F:LREAL F:={expr}; END_FUNCTION")
    with pytest.raises(ExecutionError):
        rt.call("F")
    with pytest.raises(RuntimeFaultedError):
        rt.call("F")


def test_real_inputs_and_outputs_are_checked_at_api_boundary():
    rt = Runtime.from_source("""FUNCTION F:REAL VAR_INPUT x:REAL; END_VAR F:=x; END_FUNCTION""")
    for bad in [True, float("nan"), float("inf"), 1e40]:
        with pytest.raises(ArgumentError):
            rt.call("F", x=bad)
    assert rt.call("F", x=16777217).value == 16777216.0


def test_array_sum_nonzero_lower_bound_and_python_input_copy():
    rt = Runtime.from_source("""FUNCTION Sum:LREAL
    VAR_INPUT a:ARRAY[-1..1] OF LREAL; END_VAR
    VAR i:INT; END_VAR
    FOR i := -1 TO 1 DO Sum := Sum + a[i]; END_FOR;
    a[0] := 100.0;
    END_FUNCTION""")
    original = [1.5, 2.5, 3.0]
    assert rt.call("Sum", a=original).value == 7.0
    assert original == [1.5, 2.5, 3.0]


def test_multidimensional_flat_initializer_order_and_partial_fill():
    rt = Runtime.from_source("""FUNCTION F:ARRAY[-1..0,3..4] OF REAL
    VAR a:ARRAY[-1..0,3..4] OF REAL := [10,20,30]; END_VAR
    a[0,4] := a[-1,4] + 2;
    F := a;
    END_FUNCTION""")
    assert rt.call("F").value == ((10.0, 20.0), (30.0, 22.0))


def test_repeated_initializers_and_instance_local_arrays():
    rt = Runtime.from_source("""FUNCTION_BLOCK B
    VAR_OUTPUT a:ARRAY[1..3] OF REAL := [2(0.1)]; END_VAR
    VAR_TEMP t:ARRAY[0..0] OF INT := [1]; END_VAR
    a[1] := a[1] + t[0]; t[0] := 99;
    END_FUNCTION_BLOCK""")
    first, second = rt.instantiate("B"), rt.instantiate("B")
    first.call()
    snapshot = first.output("a")
    first.call()
    assert second.output("a") == (0.10000000149011612, 0.10000000149011612, 0.0)
    assert snapshot[0] == 1.100000023841858
    assert first.output("a")[0] == 2.0999999046325684


def test_inout_whole_array_assignment_preserves_element_alias():
    rt = Runtime.from_source("""FUNCTION F:INT
    VAR_IN_OUT a:ARRAY[1..2] OF INT; item:INT; END_VAR
    VAR replacement:ARRAY[1..2] OF INT := [10,20]; END_VAR
    a := replacement;
    item := item + 1;
    F := a[1];
    END_FUNCTION""")
    array = rt.cell("ARRAY[1..2] OF INT", [1, 2])
    alias = array.element(1)
    assert rt.call("F", a=array, item=alias).value == 11
    assert array.value == (11, 20)
    assert alias.value == 11


def test_st_array_input_copy_and_output_binding():
    rt = Runtime.from_source("""FUNCTION Change:INT
    VAR_INPUT input:ARRAY[1..2] OF INT; END_VAR
    VAR_OUTPUT result:ARRAY[1..2] OF INT; END_VAR
    input[1] := 99; result := input; Change := 0;
    END_FUNCTION
    FUNCTION Main:INT
    VAR a:ARRAY[1..2] OF INT := [1,2]; b:ARRAY[1..2] OF INT; END_VAR
    Change(input:=a, result=>b);
    b[2] := 42;
    Main := a[1] + a[2] + b[1] + b[2];
    END_FUNCTION""")
    assert rt.call("Main").value == 144
    result = rt.call("Change", input=[1, 2])
    assert result.outputs["result"] == (99, 2)


def test_st_indexed_element_can_be_an_inout_and_output_target():
    rt = Runtime.from_source("""FUNCTION Increase:INT
    VAR_IN_OUT n:INT; END_VAR
    VAR_OUTPUT other:INT; END_VAR
    n:=n+1; other:=n+10; Increase:=n;
    END_FUNCTION
    FUNCTION Main:ARRAY[-1..0] OF INT
    VAR a:ARRAY[-1..0] OF INT := [1,2]; END_VAR
    Increase(n:=a[-1],other=>a[0]); Main:=a;
    END_FUNCTION""")
    assert rt.call("Main").value == (2, 12)


@pytest.mark.parametrize("indices", ["0,3", "1,5", "2,2"])
def test_bounds_checked_per_dimension_even_if_flat_offset_would_fit(indices):
    rt = Runtime.from_source(f"""FUNCTION F:INT
    VAR a:ARRAY[1..2,3..4] OF INT; END_VAR F:=a[{indices}]; END_FUNCTION""")
    with pytest.raises(ExecutionError) as error:
        rt.call("F")
    assert error.value.loc is not None and "F" in error.value.stack


def test_bad_array_arguments_do_not_partially_update_fb_inputs():
    rt = Runtime.from_source("""FUNCTION_BLOCK B
    VAR_INPUT n:INT; a:ARRAY[1..2] OF REAL; END_VAR
    VAR_OUTPUT result:REAL; END_VAR
    result:=n+a[1];
    END_FUNCTION_BLOCK""")
    fb = rt.instantiate("B")
    for bad in [[2.0], [2.0, True], [2.0, float("inf")]]:
        with pytest.raises(ArgumentError):
            fb.call(n=10, a=bad)
        fb.call()
        assert fb.output("result") == 0.0
    fb.call(n=2, a=[0.5, 1.0])
    assert fb.output("result") == 2.5


def test_inout_array_requires_exact_bounds_and_owner():
    rt = Runtime.from_source("""FUNCTION F:INT
    VAR_IN_OUT a:ARRAY[1..2] OF INT; END_VAR F:=a[1]; END_FUNCTION""")
    wrong = rt.cell("ARRAY[0..1] OF INT", [3, 4])
    with pytest.raises(ArgumentError):
        rt.call("F", a=wrong)
    other = Runtime.from_source("FUNCTION G:INT END_FUNCTION")
    with pytest.raises(ArgumentError):
        rt.call("F", a=other.cell("ARRAY[1..2] OF INT", [3, 4]))
    assert rt.call("F", a=rt.cell("ARRAY[1..2] OF INT", [3, 4])).value == 3
