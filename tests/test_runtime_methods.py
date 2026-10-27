"""Runtime contracts for owner-linked, fresh FB method invocations."""

import pytest

from tc_emulator import ArgumentError, ExecutionError, Runtime, RuntimeFaultedError


def runtime(source, **limits):
    return Runtime.from_source(source, **limits)


def test_python_method_updates_only_its_owner_without_running_fb_body():
    rt = runtime("""
    FUNCTION_BLOCK Counter
    VAR_OUTPUT n : INT; body_runs : INT; END_VAR
    body_runs := body_runs + 1;
    METHOD Add : INT
    VAR_INPUT amount : INT; END_VAR
    n := n + amount;
    Add := n;
    END_METHOD
    END_FUNCTION_BLOCK
    """)
    first, second = rt.instantiate("Counter"), rt.instantiate("Counter")
    assert first.call_method("aDd", amount=2).value == 2
    assert first.call_method("ADD", amount=3).value == 5
    assert second.call_method("add", amount=4).value == 4
    assert first.inspect() == {"N": 5, "BODY_RUNS": 0}
    first.call()
    assert first.output("body_runs") == 1


def test_method_locals_inputs_outputs_and_result_reset_each_call():
    rt = runtime("""
    FUNCTION_BLOCK Counter
    VAR_OUTPUT total : INT; END_VAR
    METHOD Read : INT
    VAR_INPUT step : INT := 2; write : BOOL := TRUE; END_VAR
    VAR local : INT := 10; END_VAR
    VAR_OUTPUT doubled : INT; END_VAR
    local := local + step;
    total := total + local;
    IF write THEN Read := local; doubled := local * 2; END_IF;
    END_METHOD
    END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("Counter")
    first = fb.call_method("Read", step=4)
    assert first.value == 14
    assert first.outputs["doubled"] == 28
    assert fb.call_method("Read").value == 12
    third = fb.call_method("Read", write=False)
    assert third.value == 0
    assert dict(third.outputs) == {"DOUBLED": 0}
    assert first.outputs["DoUbLeD"] == 28
    with pytest.raises(TypeError):
        first.outputs["doubled"] = 0
    assert fb.output("total") == 38


def test_method_void_return_and_python_input_names_do_not_collide():
    rt = runtime("""
    FUNCTION_BLOCK Counter
    VAR_OUTPUT n : INT; END_VAR
    METHOD Set
    VAR_INPUT self, name : INT; END_VAR
    n := self + name;
    END_METHOD
    END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("Counter")
    result = fb.call_method("Set", self=2, name=3)
    assert result.value is None
    assert dict(result.outputs) == {}
    assert fb.output("n") == 5


def test_method_locals_shadow_owner_and_owner_shadows_globals():
    rt = runtime("""
    VAR_GLOBAL value : INT := 100; other : INT := 200; END_VAR
    FUNCTION_BLOCK Counter
    VAR value : INT := 10; other : INT := 20; END_VAR
    METHOD Read : INT
    VAR value : INT := 1; END_VAR
    value := value + 1;
    other := other + 1;
    Read := value + other;
    END_METHOD
    END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("Counter")
    assert fb.call_method("Read").value == 23
    assert fb.call_method("Read").value == 24
    assert fb.inspect() == {"VALUE": 10, "OTHER": 22}
    assert rt.global_cell("GVL", "other").value == 200


def test_method_local_fbs_and_timers_are_fresh_but_owner_timer_retains_clock():
    rt = runtime("""
    FUNCTION_BLOCK Counter
    VAR timer : TON; END_VAR
    METHOD Tick : INT
    VAR child : CTU; local_timer : TON; END_VAR
    child(CU := TRUE, PV := 2);
    local_timer(IN := TRUE, PT := T#10ms);
    timer(IN := TRUE, PT := T#10ms);
    IF timer.Q THEN Tick := child.CV + 10; ELSE Tick := child.CV; END_IF;
    IF local_timer.Q THEN Tick := 99; END_IF;
    END_METHOD
    END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("Counter")
    assert fb.call_method("Tick").value == 1
    assert rt.now_ms == 0
    rt.advance_time(10)
    assert fb.call_method("Tick").value == 11
    assert rt.now_ms == 10


def test_method_inout_supports_aliasing_and_structured_results_snapshots():
    rt = runtime("""
    TYPE Pair : STRUCT a : INT; b : INT; END_STRUCT END_TYPE
    FUNCTION_BLOCK Counter
    METHOD Change : Pair
    VAR_IN_OUT x, y : Pair; END_VAR
    VAR_OUTPUT copied : Pair; END_VAR
    x.a := x.a + 1;
    y.b := y.b + x.a;
    copied := y;
    Change := x;
    END_METHOD
    END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("Counter")
    cell = rt.cell("Pair", {"a": 2, "b": 5})
    result = fb.call_method("Change", x=cell, y=cell)
    assert dict(result.value) == {"A": 3, "B": 8}
    assert dict(result.outputs["copied"]) == {"A": 3, "B": 8}
    cell.field("a").value = 99
    assert result.value["a"] == 3
    assert result.outputs["copied"]["a"] == 3


@pytest.mark.parametrize("arguments", [{}, {"n": 2, "N": 3}, {"typo": 2}, {"n": 99999}])
def test_method_argument_errors_leave_owner_healthy_and_unchanged(arguments):
    rt = runtime("""
    FUNCTION_BLOCK Counter
    VAR_OUTPUT total : INT; END_VAR
    METHOD Add : INT
    VAR_INPUT n : INT; END_VAR
    total := total + n; Add := total;
    END_METHOD
    END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("Counter")
    with pytest.raises(ArgumentError):
        fb.call_method("Add", **arguments)
    assert fb.output("total") == 0
    assert fb.call_method("Add", n=4).value == 4


def test_private_unknown_and_nonstring_method_names_leave_runtime_healthy():
    rt = runtime("""
    FUNCTION_BLOCK Counter
    METHOD PRIVATE Hidden : INT Hidden := 1; END_METHOD
    METHOD PublicValue : INT PublicValue := 2; END_METHOD
    END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("Counter")
    for name in ("Hidden", "missing", 5):
        with pytest.raises(ArgumentError):
            fb.call_method(name)
    assert fb.call_method("PublicValue").value == 2


def test_method_inout_rejects_wrong_type_cross_runtime_readonly_and_bit_cells():
    source = """
    VAR_GLOBAL CONSTANT fixed : INT := 3; END_VAR
    FUNCTION_BLOCK Counter
    METHOD Change
    VAR_INPUT n : INT; END_VAR
    VAR_IN_OUT value : INT; END_VAR
    value := value + n;
    END_METHOD
    END_FUNCTION_BLOCK
    """
    rt, foreign = runtime(source), runtime(source)
    fb = rt.instantiate("Counter")
    invalid = (
        rt.cell("DINT", 1),
        foreign.cell("INT", 1),
        rt.global_cell("GVL", "fixed"),
        rt.cell("INT", 1).bit(0),
        1,
    )
    for cell in invalid:
        with pytest.raises(ArgumentError):
            fb.call_method("Change", n=2, value=cell)
    cell = rt.cell("INT", 4)
    with pytest.raises(ArgumentError):
        fb.call_method("Change", n=2)
    fb.call_method("Change", n=2, value=cell)
    assert cell.value == 6


def test_method_execution_failure_preserves_partial_owner_and_alias_state_and_faults_runtime():
    rt = runtime("""
    FUNCTION_BLOCK Counter
    VAR_OUTPUT total : INT; END_VAR
    METHOD Fail
    VAR_IN_OUT value : INT; END_VAR
    total := 7; value := 9; total := 1 / 0;
    END_METHOD
    END_FUNCTION_BLOCK
    """)
    first, second = rt.instantiate("Counter"), rt.instantiate("Counter")
    cell = rt.cell("INT", 1)
    with pytest.raises(ExecutionError) as error:
        first.call_method("Fail", value=cell)
    assert error.value.stack == ("COUNTER.FAIL",)
    assert first.output("total") == 7
    assert cell.value == 9
    with pytest.raises(RuntimeFaultedError):
        second.call()
    with pytest.raises(RuntimeFaultedError):
        first.call_method("Fail", value=cell)


def test_st_methods_dispatch_body_siblings_nested_receivers_and_output_bindings():
    rt = runtime("""
    FUNCTION_BLOCK Counter
    VAR_OUTPUT total : INT; END_VAR
    total := Add(1);
    METHOD Add : INT
    VAR_INPUT n : INT; END_VAR
    VAR_OUTPUT doubled : INT; END_VAR
    total := total + n; doubled := total * 2; Add := total;
    END_METHOD
    METHOD PRIVATE Hidden : INT Hidden := Add(2); END_METHOD
    METHOD Run : INT Run := Hidden(); END_METHOD
    END_FUNCTION_BLOCK
    FUNCTION_BLOCK Outer
    VAR child : Counter; END_VAR
    METHOD Read : INT
    VAR copied : INT; END_VAR
    Read := child.Add(n := 3, doubled => copied) + copied;
    END_METHOD
    END_FUNCTION_BLOCK
    FUNCTION F : INT
    VAR outer : Outer; END_VAR
    F := outer.Read();
    END_FUNCTION
    """)
    fb = rt.instantiate("Counter")
    fb.call()
    assert fb.output("total") == 1
    assert fb.call_method("Run").value == 3
    assert rt.call("F").value == 9


@pytest.mark.parametrize(
    ("result_type", "literal", "expression", "want"),
    [
        ("WORD", "WORD#16#FF00", "fb.Read() AND WORD#16#0FF0", 3840),
        ("REAL", "REAL#1.5", "fb.Read() / REAL#2.0", 0.75),
        ("TIME", "T#4ms", "fb.Read() + T#3ms", 7),
    ],
)
def test_method_expression_preserves_declared_result_type(result_type, literal, expression, want):
    rt = runtime(f"""
    FUNCTION_BLOCK Counter
    METHOD Read : {result_type} Read := {literal}; END_METHOD
    END_FUNCTION_BLOCK
    FUNCTION F : {result_type}
    VAR fb : Counter; END_VAR
    F := {expression};
    END_FUNCTION
    """)
    assert rt.call("F").value == want


def test_methods_share_step_budget_across_sibling_calls():
    rt = runtime(
        """
    FUNCTION_BLOCK Counter
    METHOD Run : INT Run := First() + Second(); END_METHOD
    METHOD First : INT First := 1; First := 2; END_METHOD
    METHOD Second : INT Second := 3; Second := 4; END_METHOD
    END_FUNCTION_BLOCK
    """,
        max_steps=4,
    )
    with pytest.raises(ExecutionError, match="budget") as error:
        rt.instantiate("Counter").call_method("Run")
    assert error.value.stack == ("COUNTER.RUN", "COUNTER.SECOND")


def test_method_calls_share_depth_limit_and_qualified_error_stack():
    rt = runtime(
        """
    FUNCTION_BLOCK Counter
    METHOD Run : INT Run := Middle(); END_METHOD
    METHOD Middle : INT Middle := Last(); END_METHOD
    METHOD Last : INT Last := 1; END_METHOD
    END_FUNCTION_BLOCK
    """,
        max_call_depth=2,
    )
    with pytest.raises(ExecutionError, match="depth") as error:
        rt.instantiate("Counter").call_method("Run")
    assert error.value.stack == ("COUNTER.RUN", "COUNTER.MIDDLE")


def test_st_method_inout_aliases_owner_cells_and_preserves_return_flow():
    rt = runtime("""
    FUNCTION_BLOCK Counter
    VAR_OUTPUT total : INT; END_VAR
    METHOD Add : INT
    VAR_IN_OUT n : INT; END_VAR
    n := n + 1; Add := n; RETURN; n := 100;
    END_METHOD
    METHOD Run : INT Run := Add(n := total); END_METHOD
    END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("Counter")
    assert fb.call_method("Run").value == 1
    assert fb.call_method("Run").value == 2
    assert fb.output("total") == 2


def test_global_and_program_method_receivers_do_not_execute_fb_bodies():
    rt = runtime("""
    FUNCTION_BLOCK Counter
    VAR_OUTPUT n, body_runs : INT; END_VAR
    body_runs := body_runs + 1;
    METHOD Next : INT n := n + 1; Next := n; END_METHOD
    END_FUNCTION_BLOCK
    VAR_GLOBAL global_counter : Counter; END_VAR
    PROGRAM Main
    VAR counter : Counter; END_VAR
    END_PROGRAM
    PROGRAM Run
    VAR_OUTPUT total, bodies : INT; END_VAR
    total := GVL.global_counter.Next() + Main.counter.Next();
    bodies := GVL.global_counter.body_runs + Main.counter.body_runs;
    END_PROGRAM
    """)
    rt.scan("Run")
    assert rt.program_cell("Run", "total").value == 2
    rt.scan("Run")
    assert rt.program_cell("Run", "total").value == 4
    assert rt.program_cell("Run", "bodies").value == 0


def test_private_method_on_another_same_type_instance_updates_that_instance():
    rt = runtime("""
    FUNCTION_BLOCK Counter
    VAR_OUTPUT n : INT; END_VAR
    METHOD PRIVATE Next : INT n := n + 1; Next := n; END_METHOD
    METHOD Run : INT
    VAR other : Counter; END_VAR
    Run := other.Next() + other.Next();
    END_METHOD
    END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("Counter")
    assert fb.call_method("Run").value == 3
    assert fb.call_method("Run").value == 3
    assert fb.output("n") == 0


def test_method_validates_arguments_before_potentially_failing_local_allocation():
    source = (
        "\n".join(
            f"FUNCTION_BLOCK N{i} "
            + (f"VAR child : N{i + 1}; END_VAR " if i < 599 else "")
            + "END_FUNCTION_BLOCK"
            for i in range(600)
        )
        + """
    FUNCTION_BLOCK Counter
    METHOD Run : INT
    VAR_INPUT required : INT; END_VAR
    VAR nested : N0; END_VAR
    Run := required;
    END_METHOD
    END_FUNCTION_BLOCK
    """
    )
    rt = runtime(source)
    fb = rt.instantiate("Counter")
    with pytest.raises(ArgumentError, match="required|REQUIRED"):
        fb.call_method("Run")
    rt.advance_time(1)
    with pytest.raises(ExecutionError, match="nesting") as error:
        fb.call_method("Run", required=1)
    assert error.value.stack == ("COUNTER.RUN",)
    with pytest.raises(RuntimeFaultedError):
        rt.advance_time(1)


def test_st_method_allocation_failure_includes_qualified_method_in_stack():
    source = (
        "\n".join(
            f"FUNCTION_BLOCK N{i} "
            + (f"VAR child : N{i + 1}; END_VAR " if i < 599 else "")
            + "END_FUNCTION_BLOCK"
            for i in range(600)
        )
        + """
    FUNCTION_BLOCK Counter
    METHOD Run : INT
    VAR nested : N0; END_VAR
    Run := 1;
    END_METHOD
    END_FUNCTION_BLOCK
    FUNCTION F : INT
    VAR counter : Counter; END_VAR
    F := counter.Run();
    END_FUNCTION
    """
    )
    rt = runtime(source)
    with pytest.raises(ExecutionError, match="nesting") as error:
        rt.call("F")
    assert error.value.stack == ("F", "COUNTER.RUN")
    with pytest.raises(RuntimeFaultedError):
        rt.advance_time(1)


@pytest.mark.parametrize("caller", ["body", "sibling"])
def test_bare_owner_method_precedes_same_named_global_scalar(caller):
    rt = runtime(f"""
    VAR_GLOBAL M : INT := 7; END_VAR
    FUNCTION_BLOCK B
    VAR_OUTPUT count : INT; END_VAR
    {"M();" if caller == "body" else ""}
    METHOD M
    count := count + 1;
    END_METHOD
    METHOD Run
    {"M();" if caller == "sibling" else ""}
    END_METHOD
    END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("B")
    if caller == "body":
        fb.call()
    else:
        fb.call_method("Run")
    assert fb.output("count") == 1
    assert rt.global_cell("GVL", "M").value == 7


def test_bare_owner_and_sibling_calls_do_not_execute_same_named_global_fb():
    rt = runtime("""
    FUNCTION_BLOCK Other
    VAR_OUTPUT count : INT; END_VAR
    count := count + 1;
    END_FUNCTION_BLOCK
    VAR_GLOBAL M : Other; END_VAR
    FUNCTION_BLOCK B
    VAR_OUTPUT count : INT; END_VAR
    M();
    METHOD M
    count := count + 1;
    END_METHOD
    METHOD Run
    M();
    END_METHOD
    END_FUNCTION_BLOCK
    PROGRAM Inspect
    VAR_OUTPUT count : INT; END_VAR
    count := GVL.M.count;
    END_PROGRAM
    """)
    fb = rt.instantiate("B")
    fb.call()
    fb.call_method("Run")
    rt.scan("Inspect")
    assert fb.output("count") == 2
    assert rt.program_cell("Inspect", "count").value == 0


def test_bare_owner_and_sibling_calls_precede_ambiguous_global_names(tmp_path):
    first = tmp_path / "First.st"
    second = tmp_path / "Second.st"
    owner = tmp_path / "Owner.st"
    first.write_text("VAR_GLOBAL M : INT := 3; END_VAR")
    second.write_text("VAR_GLOBAL M : INT := 5; END_VAR")
    owner.write_text("""
    FUNCTION_BLOCK B
    VAR_OUTPUT count : INT; END_VAR
    M();
    METHOD M
    count := count + 1;
    END_METHOD
    METHOD Run
    M();
    END_METHOD
    END_FUNCTION_BLOCK
    """)
    rt = Runtime.from_files([first, second, owner])
    fb = rt.instantiate("B")
    fb.call()
    fb.call_method("Run")
    assert fb.output("count") == 2
    assert rt.global_cell("First", "M").value == 3
    assert rt.global_cell("Second", "M").value == 5


def test_method_local_fb_still_shadows_owner_method_with_the_same_name():
    rt = runtime("""
    FUNCTION_BLOCK Other
    VAR_OUTPUT count : INT; END_VAR
    count := count + 1;
    END_FUNCTION_BLOCK
    FUNCTION_BLOCK B
    VAR_OUTPUT count : INT; END_VAR
    METHOD M
    count := count + 10;
    END_METHOD
    METHOD Run : INT
    VAR M : Other; END_VAR
    M();
    Run := M.count;
    END_METHOD
    END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("B")
    assert fb.call_method("Run").value == 1
    assert fb.output("count") == 0
