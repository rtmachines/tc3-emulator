"""Observable storage, selection and alias contracts for extended arrays."""

import pytest

from tc_emulator import ArgumentError, ExecutionError, Runtime, RuntimeFaultedError

COUNTER = """
FUNCTION_BLOCK Counter
VAR_INPUT step : INT := 1; END_VAR
VAR_OUTPUT n : INT; END_VAR
n := n + step;
METHOD Add : INT
VAR_INPUT amount : INT; END_VAR
n := n + amount; Add := n;
END_METHOD
END_FUNCTION_BLOCK
"""


def test_fb_array_storage_selects_row_major_and_snapshots_are_detached():
    from tc_emulator.memory import FBArray
    from tc_emulator.types import FBArrayType

    rt = Runtime.from_source(COUNTER)
    first, second, third, fourth = [rt.instantiate("Counter") for _ in range(4)]
    blocks = FBArray(
        FBArrayType(((-1, 0), (2, 3)), "COUNTER"),
        tuple(item._frame for item in (first, second, third, fourth)),
    )
    second.call(step=7)
    assert blocks._element((-1, 3)) is second._frame
    assert blocks._element((0, 2)) is third._frame
    snapshot = blocks.inspect()
    second.call()
    assert snapshot == (
        ({"STEP": 1, "N": 0}, {"STEP": 7, "N": 7}),
        ({"STEP": 1, "N": 0}, {"STEP": 1, "N": 0}),
    )
    snapshot[0][0]["N"] = 99
    assert first.output("n") == 0
    for indices in ((True, 2), (-2, 2), (-1,), (-1, 2, 3)):
        with pytest.raises((TypeError, IndexError)):
            blocks._element(indices)


def test_st_fb_array_calls_fields_methods_and_output_binding_are_independent():
    rt = Runtime.from_source(
        COUNTER
        + """
    PROGRAM Main
    VAR blocks : ARRAY[-1..0, 2..3] OF Counter;
        copied, method_result : INT; END_VAR
    blocks[-1, 3].step := 2;
    blocks[-1, 3](n => copied);
    method_result := blocks[0, 2].Add(5);
    END_PROGRAM
    """
    )
    rt.scan("Main")
    rt.scan("Main")
    assert rt.program_cell("Main", "copied").value == 4
    assert rt.program_cell("Main", "method_result").value == 10
    assert rt.program_fb("main", "blocks", -1, 2).output("n") == 0
    assert rt.program_fb("main", "blocks", -1, 3).output("n") == 4


def test_indexed_receiver_is_selected_once_before_argument_side_effects():
    rt = Runtime.from_source(
        COUNTER
        + """
    VAR_GLOBAL selected : INT := 1; hits : INT; END_VAR
    FUNCTION Pick : INT
    hits := hits + 1; Pick := selected;
    END_FUNCTION
    FUNCTION Change : INT
    selected := 2; Change := 7;
    END_FUNCTION
    PROGRAM Main
    VAR blocks : ARRAY[1..2] OF Counter; result : INT; END_VAR
    result := blocks[Pick()].Add(Change());
    END_PROGRAM
    """
    )
    rt.scan("Main")
    assert rt.global_cell("GVL", "hits").value == 1
    assert rt.program_fb("Main", "blocks", 1).output("n") == 7
    assert rt.program_fb("Main", "blocks", 2).output("n") == 0
    assert rt.program_cell("Main", "result").value == 7


def test_nested_python_handles_select_existing_instances_and_snapshots():
    rt = Runtime.from_source(
        COUNTER
        + """
    FUNCTION_BLOCK Group
    VAR blocks : ARRAY[-1..0] OF Counter; single : Counter; END_VAR
    END_FUNCTION_BLOCK
    VAR_GLOBAL groups : ARRAY[2..3] OF Group; END_VAR
    PROGRAM Main VAR group : Group; END_VAR END_PROGRAM
    """
    )
    selected = rt.global_fb("gvl", "groups", 2).fb("blocks", -1)
    selected.call(step=3)
    assert rt.global_fb("GVL", "groups", 2).fb("blocks", -1).output("n") == 3
    assert rt.global_fb("GVL", "groups", 3).fb("blocks", -1).output("n") == 0
    assert rt.program_fb("Main", "group").fb("single").output("n") == 0
    snapshot = rt.global_fb("GVL", "groups", 2).inspect()
    selected.call()
    assert snapshot["BLOCKS"][0]["N"] == 3


@pytest.mark.parametrize(
    "name,indices",
    [
        ("blocks", ()),
        ("blocks", (True,)),
        ("blocks", (0,)),
        ("blocks", (1, 2)),
        ("blocks", (1.0,)),
        ("single", (1,)),
        ("value", ()),
        ("missing", ()),
        ("scratch", (1,)),
    ],
)
def test_invalid_python_instance_selection_leaves_runtime_healthy(name, indices):
    rt = Runtime.from_source(
        COUNTER
        + """
    PROGRAM Main
    VAR blocks : ARRAY[1..2] OF Counter; single : Counter; value : INT; END_VAR
    VAR_TEMP scratch : ARRAY[1..2] OF Counter; END_VAR
    END_PROGRAM
    """
    )
    with pytest.raises(ArgumentError):
        rt.program_fb("Main", name, *indices)
    rt.program_fb("Main", "single").call()
    assert rt.program_fb("Main", "single").output("n") == 1


def test_fb_array_timers_keep_independent_state_and_virtual_clock():
    rt = Runtime.from_source("""
    PROGRAM Main
    VAR timers : ARRAY[-1..0] OF TON; END_VAR
    timers[-1](IN := TRUE, PT := T#10ms);
    timers[0](IN := TRUE, PT := T#20ms);
    END_PROGRAM
    """)
    rt.scan("Main")
    rt.advance_time(10)
    rt.scan("Main")
    assert rt.program_fb("Main", "timers", -1).output("q") is True
    assert rt.program_fb("Main", "timers", 0).output("q") is False
    assert rt.program_fb("Main", "timers", 0).output("et") == 10


def test_var_temp_and_method_local_arrays_are_fresh_while_owned_arrays_persist():
    rt = Runtime.from_source(
        COUNTER
        + """
    FUNCTION_BLOCK Owner
    VAR owned : ARRAY[1..1] OF Counter; END_VAR
    VAR_TEMP scratch : ARRAY[1..1] OF Counter; END_VAR
    VAR_OUTPUT temp_n : INT; END_VAR
    owned[1](); scratch[1](); temp_n := scratch[1].n;
    METHOD Tick : INT
    VAR local : ARRAY[1..1] OF Counter; END_VAR
    local[1](); owned[1](); Tick := local[1].n;
    END_METHOD
    END_FUNCTION_BLOCK
    """
    )
    owner = rt.instantiate("Owner")
    owner.call()
    owner.call()
    assert owner.output("temp_n") == 1
    assert owner.call_method("Tick").value == 1
    assert owner.call_method("Tick").value == 1
    assert owner.fb("owned", 1).output("n") == 4
    with pytest.raises(ArgumentError):
        owner.fb("scratch", 1)


OPEN = """
FUNCTION Change : DINT
VAR_IN_OUT values : ARRAY[*, *] OF INT; END_VAR
values[LOWER_BOUND(values, 1), UPPER_BOUND(values, 2)] := 17;
Change := LOWER_BOUND(values, 1) + UPPER_BOUND(values, 2);
END_FUNCTION
FUNCTION Forward : DINT
VAR_IN_OUT values : ARRAY[*, *] OF INT; END_VAR
Forward := Change(values);
END_FUNCTION
"""


def test_open_array_aliases_actual_fixed_cell_and_forwards_actual_bounds():
    rt = Runtime.from_source(OPEN)
    values = rt.cell("ARRAY[-2..-1, 4..5] OF INT", ((1, 2), (3, 4)))
    element = values.element(-2, 5)
    assert rt.call("Forward", values=values).value == 3
    assert values.value == ((1, 17), (3, 4))
    assert element.value == 17


def test_open_array_st_binding_keeps_bounds_and_aliases():
    rt = Runtime.from_source(
        OPEN
        + """
    PROGRAM Main
    VAR values : ARRAY[3..4, -2..-1] OF INT; result : DINT; END_VAR
    result := Forward(values);
    END_PROGRAM
    """
    )
    rt.scan("Main")
    assert rt.program_cell("Main", "values").value == ((0, 17), (0, 0))
    assert rt.program_cell("Main", "result").value == 2


def test_open_python_arguments_validate_before_mutating_persistent_instance():
    source = """
    VAR_GLOBAL CONSTANT fixed : ARRAY[1..1, 1..1] OF INT := [1]; END_VAR
    FUNCTION_BLOCK Owner
    VAR_INPUT increment : INT; END_VAR
    VAR_IN_OUT values : ARRAY[*, *] OF INT; END_VAR
    VAR_OUTPUT calls : INT; END_VAR
    calls := calls + increment; values[LOWER_BOUND(values, 1), 1] := calls;
    END_FUNCTION_BLOCK
    """
    rt, foreign = Runtime.from_source(source), Runtime.from_source(source)
    owner = rt.instantiate("Owner")
    invalid = (
        ((0,),),
        rt.cell("INT", 0),
        rt.cell("ARRAY[1..1] OF INT", (0,)),
        rt.cell("ARRAY[1..1, 1..1] OF DINT", ((0,),)),
        foreign.cell("ARRAY[1..1, 1..1] OF INT", ((0,),)),
        rt.global_cell("GVL", "fixed"),
        rt.cell("INT", 0).bit(0),
    )
    for value in invalid:
        with pytest.raises(ArgumentError):
            owner.call(increment=9, values=value)
        assert owner.inspect()["INCREMENT"] == 0
        assert owner.output("calls") == 0
    actual = rt.cell("ARRAY[-2..-2, 1..1] OF INT", ((0,),))
    owner.call(increment=3, values=actual)
    assert actual.value == ((3,),)


@pytest.mark.parametrize("dimension", [0, -1, 3])
def test_invalid_bound_dimension_is_source_aware_fault_and_handles_remain_readable(dimension):
    rt = Runtime.from_source(
        COUNTER
        + f"""
    PROGRAM Main
    VAR blocks : ARRAY[-1..0, 2..3] OF Counter; result : DINT; END_VAR
    result := UPPER_BOUND(blocks, {dimension});
    END_PROGRAM
    """,
        source="bounds.st",
    )
    with pytest.raises(ExecutionError) as caught:
        rt.scan("Main")
    assert "bounds.st" in str(caught.value)
    assert rt.program_fb("Main", "blocks", -1, 2).output("n") == 0
    with pytest.raises(RuntimeFaultedError):
        rt.program_fb("Main", "blocks", -1, 2).call()


def test_bounds_support_fixed_value_and_fb_arrays_with_dint_result():
    rt = Runtime.from_source(
        COUNTER
        + """
    PROGRAM Main
    VAR blocks : ARRAY[-3..-1, 4..6] OF Counter;
        values : ARRAY[-2147483648..-2147483648] OF INT;
        low, high : DINT; END_VAR
    low := LOWER_BOUND(values, 1);
    high := UPPER_BOUND(blocks, 2);
    END_PROGRAM
    """
    )
    rt.scan("Main")
    assert rt.program_cell("Main", "low").value == -2147483648
    assert rt.program_cell("Main", "high").value == 6


def test_fb_receiver_and_bound_array_paths_evaluate_selectors_once_in_source_order():
    rt = Runtime.from_source(
        COUNTER
        + """
    VAR_GLOBAL hits : INT; END_VAR
    FUNCTION Pick : INT hits := hits * 10 + 1; Pick := 1; END_FUNCTION
    FUNCTION Amount : INT hits := hits * 10 + 2; Amount := 4; END_FUNCTION
    FUNCTION Dimension : INT hits := hits * 10 + 3; Dimension := 1; END_FUNCTION
    FUNCTION_BLOCK Group
    VAR_OUTPUT values : ARRAY[-2..-1] OF INT; END_VAR
    END_FUNCTION_BLOCK
    PROGRAM Main
    VAR groups : ARRAY[1..2] OF Group; blocks : ARRAY[1..2] OF Counter; high : DINT; END_VAR
    blocks[Pick()](step := Amount());
    high := UPPER_BOUND(groups[Pick()].values, Dimension());
    END_PROGRAM
    """
    )
    rt.scan("Main")
    assert rt.global_cell("GVL", "hits").value == 1213
    assert rt.program_cell("Main", "high").value == -1
    assert rt.program_fb("Main", "blocks", 1).output("n") == 4


def test_bad_receiver_faults_before_argument_side_effects_and_keeps_diagnostics():
    rt = Runtime.from_source(
        COUNTER
        + """
    VAR_GLOBAL hits : INT; END_VAR
    FUNCTION Amount : INT hits := hits + 1; Amount := 4; END_FUNCTION
    PROGRAM Main
    VAR blocks : ARRAY[1..2] OF Counter; index : INT := 3; END_VAR
    blocks[index](step := Amount());
    END_PROGRAM
    """,
        source="selection.st",
    )
    with pytest.raises(ExecutionError) as caught:
        rt.scan("Main")
    assert "selection.st" in str(caught.value)
    assert rt.global_cell("GVL", "hits").value == 0
    assert rt.program_fb("Main", "blocks", 1).output("n") == 0
    with pytest.raises(RuntimeFaultedError):
        rt.program_fb("Main", "blocks", 1).set_input("step", 9)


def test_indexed_method_declared_word_result_keeps_bitwise_type():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK Bits
    METHOD Read : WORD Read := WORD#16#FF00; END_METHOD
    END_FUNCTION_BLOCK
    PROGRAM Main
    VAR blocks : ARRAY[1..1] OF Bits; result : WORD; END_VAR
    result := blocks[1].Read() AND WORD#16#0FF0;
    END_PROGRAM
    """)
    rt.scan("Main")
    assert rt.program_cell("Main", "result").value == 3840


def test_open_arrays_of_struct_aliases_work_through_python_method_and_fb_binding():
    rt = Runtime.from_source("""
    TYPE Pair : STRUCT n : INT; END_STRUCT END_TYPE
    TYPE PairAlias : Pair; END_TYPE
    FUNCTION_BLOCK Owner
    VAR_IN_OUT values : ARRAY[*] OF Pair; END_VAR
    values[LOWER_BOUND(values, 1)].n := values[LOWER_BOUND(values, 1)].n + 2;
    METHOD Change : DINT
    VAR_IN_OUT items : ARRAY[*] OF PairAlias; END_VAR
    items[UPPER_BOUND(items, 1)].n := 8;
    Change := LOWER_BOUND(items, 1);
    END_METHOD
    END_FUNCTION_BLOCK
    """)
    actual = rt.cell("ARRAY[-2..-1] OF PairAlias", ({"n": 1}, {"n": 3}))
    owner = rt.instantiate("Owner")
    owner.call(values=actual)
    assert actual.element(-2).field("n").value == 3
    assert owner.call_method("Change", items=actual).value == -2
    assert actual.element(-1).field("n").value == 8


def test_open_strings_use_canonical_exact_capacity_and_preserve_indices():
    rt = Runtime.from_source("""
    TYPE Text : STRING(4); END_TYPE
    FUNCTION Change : DINT
    VAR_IN_OUT words : ARRAY[*] OF Text; END_VAR
    words[LOWER_BOUND(words, 1)] := 'done';
    Change := UPPER_BOUND(words, 1);
    END_FUNCTION
    """)
    actual = rt.cell("ARRAY[5..6] OF STRING(4)", ("a", "b"))
    wrong = rt.cell("ARRAY[5..6] OF STRING(5)", ("a", "b"))
    with pytest.raises(ArgumentError):
        rt.call("Change", words=wrong)
    assert rt.call("Change", words=actual).value == 6
    assert actual.value == ("done", "b")
