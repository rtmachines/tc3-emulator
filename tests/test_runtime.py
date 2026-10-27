"""End-to-end semantics: all programs are parsed from real ST."""

import pytest


def runtime(source, **limits):
    from tc_emulator import Runtime

    return Runtime.from_source(source, **limits)


def test_function_calls_and_fresh_locals():
    rt = runtime("""
    FUNCTION F_Add : DINT
    VAR_INPUT a, b : DINT; END_VAR
    VAR calls : DINT := 0; END_VAR
    calls := calls + 1;
    F_Add := a + b + calls - 1;
    END_FUNCTION
    """)
    assert rt.call("f_add", a=2, b=3).value == 5
    assert rt.call("F_ADD", A=-7, B=2).value == -5


def test_fb_state_independent_instances_and_retained_inputs():
    rt = runtime("""
    FUNCTION_BLOCK FB_Counter
    VAR_INPUT enable : BOOL; END_VAR
    VAR_OUTPUT count : DINT; END_VAR
    VAR_TEMP temp : DINT := 5; END_VAR
    temp := temp + 1;
    IF enable THEN count := count + temp - 5; END_IF;
    END_FUNCTION_BLOCK
    """)
    first = rt.instantiate("FB_Counter")
    second = rt.instantiate("fb_counter")
    first.set_input("enable", True)
    assert first.output("count") == 0
    first.call()
    first.call()
    assert first.output("count") == 2
    assert second.output("count") == 0
    first.call(enable=False)
    assert first.output("count") == 2
    view = first.inspect()
    view["COUNT"] = 99
    assert first.output("COUNT") == 2


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("2 + 3 * 4", 14),
        ("(2 + 3) * 4", 20),
        ("-7 / 3", -2),
        ("7 / -3", -2),
        ("-7 MOD 3", -1),
        ("7 MOD -3", 1),
        ("-7 MOD -3", -1),
    ],
)
def test_integer_arithmetic(expr, expected):
    rt = runtime(f"FUNCTION F : DINT F := {expr}; END_FUNCTION")
    assert rt.call("f").value == expected


def test_nested_calls_named_positional_and_outputs():
    rt = runtime("""
    FUNCTION Compute : DINT
    VAR_INPUT a, b : DINT; END_VAR
    VAR_OUTPUT doubled : DINT; END_VAR
    doubled := a * 2;
    Compute := a + b;
    END_FUNCTION
    FUNCTION Run : DINT
    VAR x, y : DINT; END_VAR
    x := Compute(a := 3, b := 4, doubled => y);
    Run := x + y + Compute(1, 2);
    END_FUNCTION
    """)
    assert rt.call("run").value == 16
    result = rt.call("compute", a=3, b=4)
    assert result.value == 7
    assert result.outputs["DOUBLED"] == 6
    with pytest.raises(TypeError):
        result.outputs["DOUBLED"] = 0


def test_inout_aliases_update_immediately():
    rt = runtime("""
    FUNCTION Change : DINT
    VAR_IN_OUT a, b : DINT; END_VAR
    a := a + 1;
    b := b + a;
    Change := b;
    END_FUNCTION
    """)
    cell = rt.cell("DINT", 10)
    assert rt.call("Change", a=cell, b=cell).value == 22
    assert cell.value == 22


def test_st_inout_and_nested_fb_instances():
    rt = runtime("""
    FUNCTION Increment : DINT
    VAR_IN_OUT value : DINT; END_VAR
    value := value + 1;
    Increment := value;
    END_FUNCTION
    FUNCTION_BLOCK Inner
    VAR_OUTPUT n : DINT; END_VAR
    Increment(value := n);
    END_FUNCTION_BLOCK
    FUNCTION_BLOCK Outer
    VAR child : Inner; END_VAR
    VAR_OUTPUT result : DINT; END_VAR
    child();
    result := child.n;
    END_FUNCTION_BLOCK
    """)
    outer = rt.instantiate("Outer")
    outer.call()
    outer.call()
    assert outer.output("result") == 2


def test_control_flow_return_exit_and_case():
    rt = runtime("""
    FUNCTION F : DINT
    VAR i, n : DINT; END_VAR
    FOR i := 5 TO 1 BY -2 DO n := n + i; END_FOR;
    WHILE n < 15 DO
        n := n + 1;
        IF n = 12 THEN EXIT; END_IF;
    END_WHILE;
    CASE n OF
        1: F := 100;
        12: F := 42;
        ELSE F := 200;
    END_CASE;
    RETURN;
    F := -1;
    END_FUNCTION
    """)
    assert rt.call("F").value == 42


def test_both_boolean_operands_execute():
    rt = runtime("""
    FUNCTION Touch : BOOL
    VAR_IN_OUT n : DINT; END_VAR
    n := n + 1;
    Touch := TRUE;
    END_FUNCTION
    FUNCTION Run : DINT
    VAR n : DINT; flag : BOOL; END_VAR
    flag := FALSE AND Touch(n := n);
    flag := TRUE OR Touch(n := n);
    Run := n;
    END_FUNCTION
    """)
    assert rt.call("Run").value == 2


def test_range_error_faults_runtime_but_state_can_be_inspected():
    from tc_emulator import ExecutionError, RuntimeFaultedError

    rt = runtime("""
    FUNCTION_BLOCK Broken
    VAR_OUTPUT count : INT; END_VAR
    count := 4;
    count := 32768;
    END_FUNCTION_BLOCK
    """)
    broken = rt.instantiate("Broken")
    with pytest.raises(ExecutionError):
        broken.call()
    assert broken.output("count") == 4
    with pytest.raises(RuntimeFaultedError):
        broken.call()
    with pytest.raises(RuntimeFaultedError):
        broken.set_input("anything", 1)


def test_api_validation_is_atomic_and_does_not_fault():
    from tc_emulator import ArgumentError

    rt = runtime("""
    FUNCTION_BLOCK Counter
    VAR_INPUT a, b : INT; END_VAR
    VAR_OUTPUT result : INT; END_VAR
    result := a + b;
    END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("Counter")
    with pytest.raises(ArgumentError):
        fb.call(a=12, b=99999)
    fb.call()
    assert fb.output("result") == 0
    with pytest.raises(ArgumentError):
        fb.call(a=True)
    fb.call(a=2, b=3)
    assert fb.output("result") == 5


def test_cross_runtime_reference_rejected():
    from tc_emulator import ArgumentError

    st = """FUNCTION F : DINT VAR_IN_OUT n : DINT; END_VAR
    n := n + 1; F := n; END_FUNCTION"""
    first, second = runtime(st), runtime(st)
    value = second.cell("DINT", 3)
    with pytest.raises(ArgumentError):
        first.call("F", n=value)
    assert value.value == 3
    assert first.call("F", n=first.cell("DINT", 4)).value == 5


def test_empty_infinite_loop_budget():
    from tc_emulator import ExecutionError

    rt = runtime("FUNCTION F : DINT WHILE TRUE DO END_WHILE; END_FUNCTION", max_steps=10)
    with pytest.raises(ExecutionError, match="[Bb]udget|[Ss]tep"):
        rt.call("F")


def test_nested_call_depth_and_source_stack():
    from tc_emulator import ExecutionError

    rt = runtime(
        """
    FUNCTION A : DINT A := B(); END_FUNCTION
    FUNCTION B : DINT B := C(); END_FUNCTION
    FUNCTION C : DINT C := 3; END_FUNCTION
    """,
        max_call_depth=2,
    )
    with pytest.raises(ExecutionError) as error:
        rt.call("A")
    assert "A" in str(error.value) and "B" in str(error.value)
    assert "<string>" in str(error.value)


def test_wider_intermediate_before_narrow_storage():
    rt = runtime("""FUNCTION F : UDINT
    VAR n : UINT := 65535; END_VAR
    F := n + 1;
    END_FUNCTION""")
    assert rt.call("F").value == 65536


def test_plc_input_names_do_not_collide_with_python_method_parameters():
    rt = runtime("""
    FUNCTION F : DINT
    VAR_INPUT name, self : DINT; END_VAR
    F := name + self;
    END_FUNCTION
    FUNCTION_BLOCK Counter
    VAR_INPUT self : DINT; END_VAR
    VAR_OUTPUT n : DINT; END_VAR
    n := self;
    END_FUNCTION_BLOCK
    """)
    assert rt.call("F", name=3, self=4).value == 7
    fb = rt.instantiate("Counter")
    fb.call(self=5)
    assert fb.output("n") == 5


def test_step_budget_is_shared_by_nested_calls():
    from tc_emulator import ExecutionError

    rt = runtime(
        """
    FUNCTION Helper : DINT
    VAR i : DINT; END_VAR
    FOR i := 1 TO 3 DO Helper := Helper + 1; END_FOR;
    END_FUNCTION
    FUNCTION F : DINT
    F := Helper() + Helper();
    END_FUNCTION
    """,
        max_steps=12,
    )
    with pytest.raises(ExecutionError, match="budget"):
        rt.call("F")


def test_fb_inout_must_be_rebound_on_every_call():
    from tc_emulator import ArgumentError

    rt = runtime("""FUNCTION_BLOCK Change
    VAR_IN_OUT n : INT; END_VAR
    n := n + 1;
    END_FUNCTION_BLOCK""")
    fb = rt.instantiate("Change")
    first, second = rt.cell("INT", 1), rt.cell("INT", 10)
    fb.call(n=first)
    with pytest.raises(ArgumentError):
        fb.call()
    fb.call(n=second)
    assert first.value == 2
    assert second.value == 11


def test_cell_write_range_and_fault_guard():
    from tc_emulator import ArgumentError, ExecutionError, RuntimeFaultedError

    rt = runtime("FUNCTION Fail : INT Fail := 1 / 0; END_FUNCTION")
    cell = rt.cell("INT", 5)
    with pytest.raises(ArgumentError):
        cell.value = 40000
    assert cell.value == 5
    cell.value = 9
    with pytest.raises(ExecutionError):
        rt.call("Fail")
    assert cell.value == 9
    with pytest.raises(RuntimeFaultedError):
        cell.value = 1


def test_function_local_fb_fresh_and_fb_temp_fb_reinitialized():
    rt = runtime("""
    FUNCTION_BLOCK Inner
    VAR_OUTPUT n : INT; END_VAR
    n := n + 1;
    END_FUNCTION_BLOCK
    FUNCTION F : INT
    VAR child : Inner; END_VAR
    child(); F := child.n;
    END_FUNCTION
    FUNCTION_BLOCK Outer
    VAR_TEMP child : Inner; END_VAR
    VAR_OUTPUT n : INT; END_VAR
    child(); n := child.n;
    END_FUNCTION_BLOCK
    """)
    assert rt.call("F").value == 1
    assert rt.call("F").value == 1
    outer = rt.instantiate("Outer")
    outer.call()
    outer.call()
    assert outer.output("n") == 1


def test_nested_fb_inputs_and_output_bindings():
    rt = runtime("""
    FUNCTION_BLOCK Inner
    VAR_INPUT a : DINT; END_VAR
    VAR_OUTPUT b : DINT; END_VAR
    b := a + 1;
    END_FUNCTION_BLOCK
    FUNCTION F : DINT
    VAR child : Inner; x : DINT; END_VAR
    child.a := 4;
    child(b => x);
    F := x;
    END_FUNCTION
    """)
    assert rt.call("F").value == 5


def test_duplicate_case_insensitive_api_args_and_unknown_names():
    from tc_emulator import ArgumentError

    rt = runtime("FUNCTION F : INT VAR_INPUT n : INT; END_VAR F := n; END_FUNCTION")
    with pytest.raises(ArgumentError):
        rt.call("F", n=1, N=2)
    with pytest.raises(ArgumentError):
        rt.call("F", typo=1)
    with pytest.raises(ArgumentError):
        rt.call("F")
    assert rt.call("F", n=3).value == 3


@pytest.mark.parametrize(
    ("condition", "want"),
    [
        ("NOT FALSE AND TRUE", True),
        ("TRUE XOR TRUE", False),
        ("2 <> 3", True),
        ("2 <= 2", True),
        ("3 >= 4", False),
        ("3 > 1", True),
    ],
)
def test_bool_results(condition, want):
    rt = runtime(f"FUNCTION F : BOOL F := {condition}; END_FUNCTION")
    assert rt.call("F").value is want


def test_for_empty_range_and_elsif_else():
    rt = runtime("""FUNCTION F : INT VAR n, i : INT; END_VAR
    FOR i := 3 TO 1 DO n := 100; END_FOR;
    IF n = 100 THEN F := 1;
    ELSIF n = 0 THEN F := 2;
    ELSE F := 3; END_IF;
    END_FUNCTION""")
    assert rt.call("F").value == 2


def test_zero_for_step_fails_at_execution():
    from tc_emulator import ExecutionError

    rt = runtime("""FUNCTION F : INT VAR i, step : INT; END_VAR
    FOR i := 1 TO 2 BY step DO END_FOR;
    END_FUNCTION""")
    with pytest.raises(ExecutionError, match="zero"):
        rt.call("F")


def test_additional_output_snapshot_lookup_is_case_insensitive():
    rt = runtime("""FUNCTION F : INT
    VAR_OUTPUT Value : INT; END_VAR
    Value := 7; F := 1;
    END_FUNCTION""")
    result = rt.call("f")
    assert result.outputs["value"] == 7
    assert result.outputs["VaLuE"] == 7
    assert "value" in result.outputs
    assert dict(result.outputs) == {"VALUE": 7}


def test_excessive_instance_nesting_reports_execution_error():
    from tc_emulator import ExecutionError, RuntimeFaultedError

    # Validation's acyclic graph walk fits, but allocating nested frames needs
    # more Python stack per level. Even that boundary must expose an ST error.
    source = "\n".join(
        f"FUNCTION_BLOCK N{i} "
        + (f"VAR child : N{i + 1}; END_VAR " if i < 599 else "")
        + "END_FUNCTION_BLOCK"
        for i in range(600)
    )
    rt = runtime(source)
    with pytest.raises(ExecutionError, match="[Nn]esting"):
        rt.instantiate("N0")
    with pytest.raises(RuntimeFaultedError):
        rt.instantiate("N599")
