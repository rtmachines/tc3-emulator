"""Behavioral contracts for executable properties and method instance storage."""

import pytest

from tc_emulator import ArgumentError, ExecutionError, Runtime, RuntimeFaultedError

SOURCE = """
FUNCTION_BLOCK B
VAR n : INT; END_VAR
VAR_OUTPUT reads, writes, bodies : INT; END_VAR
bodies := bodies + 1;
PROPERTY P : INT
GET reads := reads + 1; P := n; END_GET
SET writes := writes + 1; n := P; END_SET
END_PROPERTY
METHOD Next : INT
VAR_INST count : INT; END_VAR
VAR fresh : INT; END_VAR
count := count + 1; fresh := fresh + 1; Next := count * 10 + fresh;
END_METHOD
END_FUNCTION_BLOCK
"""


def test_properties_execute_only_accessors_and_remain_outside_inspection():
    rt = Runtime.from_source(SOURCE)
    a, b = rt.instantiate("B"), rt.instantiate("B")
    a.set_property("p", 8)
    assert a.inspect() == {
        "N": 8,
        "READS": 0,
        "WRITES": 1,
        "BODIES": 0,
        "$VAR_INST": {"NEXT": {"COUNT": 0}},
    }
    assert a.get_property("P") == 8
    assert b.get_property("p") == 0
    assert a.output("reads") == 1
    assert a.call_method("Next").value == 11
    assert a.call_method("Next").value == 21
    assert b.call_method("Next").value == 11


def test_property_api_rejects_bad_values_before_mutating_and_stays_healthy():
    rt = Runtime.from_source(SOURCE)
    fb = rt.instantiate("B")
    for value in [True, 32768, "3"]:
        with pytest.raises(ArgumentError):
            fb.set_property("P", value)
    for name in ["missing", None, "P.GET"]:
        with pytest.raises(ArgumentError):
            fb.get_property(name)
    assert fb.inspect()["WRITES"] == 0
    fb.set_property("P", 2)
    assert fb.get_property("p") == 2


def test_this_bypasses_locals_and_property_result_slots():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK B
    VAR x : INT := 4; END_VAR
    PROPERTY P : INT
    GET P := THIS^.x; END_GET
    SET THIS^.x := P; END_SET
    END_PROPERTY
    METHOD M : INT
    VAR x : INT := 90; P : INT := 80; END_VAR
    THIS^.P := THIS^.x + 1;
    M := THIS^.P + x + P;
    END_METHOD
    END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("B")
    assert fb.call_method("M").value == 175
    assert fb.get_property("P") == 5


def test_property_execution_fault_preserves_writes_and_diagnostics():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK B VAR_OUTPUT n : INT; END_VAR
    PROPERTY P : INT GET n := n + 1; P := 1 / 0; END_GET END_PROPERTY
    END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("B")
    with pytest.raises(ExecutionError) as error:
        fb.get_property("P")
    assert error.value.stack == ("B.P.GET",)
    assert fb.output("n") == 1
    assert fb.inspect() == {"N": 1}
    with pytest.raises(RuntimeFaultedError):
        fb.get_property("P")


def test_indexed_receiver_runs_once_before_rhs_and_getter_runs_once_per_read():
    rt = Runtime.from_source(
        SOURCE
        + """
    VAR_GLOBAL index_calls, rhs_calls : INT; chosen : INT := 1; END_VAR
    FUNCTION NextIndex : INT
    index_calls := index_calls + 1; NextIndex := chosen;
    END_FUNCTION
    FUNCTION RHS : INT
    rhs_calls := rhs_calls + 1; chosen := 2; RHS := 7;
    END_FUNCTION
    PROGRAM Main
    VAR items : ARRAY[1..2] OF B; result : INT; END_VAR
    items[NextIndex()].P := RHS();
    result := items[NextIndex()].P + items[1].P + items[1].P;
    END_PROGRAM
    """
    )
    rt.scan("Main")
    a, b = rt.program_fb("Main", "items", 1), rt.program_fb("Main", "items", 2)
    assert a.inspect()["N"] == 7
    assert b.inspect()["N"] == 0
    assert a.output("writes") == 1
    assert a.output("reads") == 2
    assert b.output("reads") == 1
    assert rt.global_cell("GVL", "index_calls").value == 2
    assert rt.global_cell("GVL", "rhs_calls").value == 1
    assert rt.program_cell("Main", "result").value == 14


def test_accessor_header_and_local_variables_are_fresh_and_getter_defaults():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK B
    VAR_OUTPUT seen : INT; END_VAR
    PROPERTY P : INT
    VAR header : INT := 4; END_VAR
    GET VAR local : INT := 3; END_VAR
    header := header + 1; local := local + 1; seen := header + local;
    END_GET
    SET header := header + P; seen := header; END_SET
    END_PROPERTY
    END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("B")
    assert fb.get_property("P") == 0
    assert fb.output("seen") == 9
    fb.set_property("P", 6)
    assert fb.output("seen") == 10
    assert fb.get_property("P") == 0
    assert fb.output("seen") == 9


@pytest.mark.parametrize(
    "kind,literal,expression,want",
    [
        ("BYTE", "BYTE#255", "NOT fb.P", 0),
        ("WORD", "WORD#16#FF00", "fb.P AND WORD#16#0FF0", 3840),
        ("TIME", "T#4ms", "fb.P + T#3ms", 7),
        ("STRING(4)", "'abc'", "fb.P", "abc"),
    ],
)
def test_property_expression_keeps_declared_type(kind, literal, expression, want):
    rt = Runtime.from_source(f"""
    FUNCTION_BLOCK B
    PROPERTY P : {kind} GET P := {literal}; END_GET END_PROPERTY
    END_FUNCTION_BLOCK
    FUNCTION F : {kind} VAR fb : B; END_VAR F := {expression}; END_FUNCTION
    """)
    assert rt.call("F").value == want


def test_enum_alias_property_and_string_range_are_checked_at_python_boundary():
    rt = Runtime.from_source("""
    TYPE E : (Off, On); Text : STRING(3); END_TYPE
    FUNCTION_BLOCK B
    VAR e_value : E; text_value : Text; END_VAR
    PROPERTY Mode : E GET Mode := e_value; END_GET SET e_value := Mode; END_SET END_PROPERTY
    PROPERTY Label : Text GET Label := text_value; END_GET SET text_value := Label; END_SET END_PROPERTY
    END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("B")
    fb.set_property("Mode", "On")
    assert fb.get_property("Mode").name == "ON"
    with pytest.raises(ArgumentError):
        fb.set_property("Mode", 1)
    with pytest.raises(ArgumentError):
        fb.set_property("Label", "abc😀")
    fb.set_property("Label", "abcdef")
    assert fb.get_property("Label") == "abc"


def test_private_accessors_and_missing_accessors_fail_without_faulting():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK B
    PROPERTY PrivateValue : INT GET PRIVATE END_GET SET PRIVATE END_SET END_PROPERTY
    PROPERTY ReadOnly : INT GET ReadOnly := 4; END_GET END_PROPERTY
    PROPERTY WriteOnly : INT SET END_SET END_PROPERTY
    METHOD M : INT THIS^.PrivateValue := 2; M := THIS^.PrivateValue; END_METHOD
    END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("B")
    for name in ["PrivateValue", "WriteOnly"]:
        with pytest.raises(ArgumentError):
            fb.get_property(name)
    for name in ["PrivateValue", "ReadOnly"]:
        with pytest.raises(ArgumentError):
            fb.set_property(name, 1)
    assert fb.call_method("M").value == 0
    assert fb.get_property("ReadOnly") == 4


def test_bare_property_precedes_global_and_this_method_bypasses_local_name():
    rt = Runtime.from_source("""
    VAR_GLOBAL P : BOOL; END_VAR
    FUNCTION_BLOCK B
    VAR_OUTPUT n : INT; END_VAR
    n := P;
    PROPERTY P : INT GET P := 7; END_GET END_PROPERTY
    METHOD Read : INT Read := P; END_METHOD
    METHOD Run : INT VAR Read : INT; END_VAR Run := THIS^.Read(); END_METHOD
    END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("B")
    fb.call()
    assert fb.output("n") == 7
    assert fb.call_method("Run").value == 7


def test_var_inst_timer_fb_arrays_and_per_method_state_survive_calls():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK B
    METHOD Wait : TIME
    VAR_INST timer : TON; counters : ARRAY[1..2] OF CTU; n : INT; END_VAR
    n := n + 1; timer(IN := TRUE, PT := T#10ms);
    counters[1](CU := TRUE, RESET := FALSE, PV := 3);
    Wait := timer.ET;
    END_METHOD
    METHOD Other : INT VAR_INST n : INT; END_VAR n := n + 1; Other := n; END_METHOD
    END_FUNCTION_BLOCK
    """)
    a, b = rt.instantiate("B"), rt.instantiate("B")
    assert a.call_method("Wait").value == 0
    rt.advance_time(5)
    assert a.call_method("Wait").value == 5
    assert b.call_method("Wait").value == 0
    assert a.call_method("Other").value == 1
    assert a.call_method("Other").value == 2
    assert b.call_method("Other").value == 1
    rt.advance_time(5)
    assert a.call_method("Wait").value == 10
    assert b.call_method("Wait").value == 5


def test_var_inst_owner_constants_control_bounds_initializers_and_fresh_owner_lifetime():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK B
    VAR CONSTANT N : INT := 2; END_VAR
    METHOD M : INT
    VAR CONSTANT N : INT := 9; END_VAR
    VAR_INST a : ARRAY[1..N] OF INT := [N, N]; n_calls : INT; END_VAR
    n_calls := n_calls + 1; M := a[2] + n_calls;
    END_METHOD
    END_FUNCTION_BLOCK
    FUNCTION F : INT VAR b : B; END_VAR F := b.M() + b.M(); END_FUNCTION
    """)
    assert rt.call("F").value == 7
    assert rt.call("F").value == 7
    fb = rt.instantiate("B")
    assert fb.call_method("M").value == 3
    assert fb.call_method("M").value == 4


@pytest.mark.parametrize(
    "limits,match", [({"max_steps": 3}, "budget"), ({"max_call_depth": 2}, "depth")]
)
def test_properties_share_caller_execution_limits(limits, match):
    rt = Runtime.from_source(
        """
    FUNCTION_BLOCK B
    PROPERTY A : INT GET A := Q; END_GET END_PROPERTY
    PROPERTY Q : INT GET Q := C; END_GET END_PROPERTY
    PROPERTY C : INT GET C := 1; C := 2; END_GET END_PROPERTY
    METHOD M : INT M := A; END_METHOD
    END_FUNCTION_BLOCK
    """,
        **limits,
    )
    with pytest.raises(ExecutionError, match=match) as error:
        rt.instantiate("B").call_method("M")
    assert error.value.stack[0] == "B.M"


def test_inspect_exposes_detached_var_inst_state_after_fault_without_executing_getters():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK B
    VAR_OUTPUT reads : INT; END_VAR
    PROPERTY P : INT GET reads := reads + 1; END_GET END_PROPERTY
    METHOD M
    VAR_INST timer : TON; values : ARRAY[1..2] OF INT; n : INT; END_VAR
    n := n + 1; values[1] := n; timer(IN := TRUE, PT := T#5ms); n := 1 / 0;
    END_METHOD
    END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("B")
    snapshot = fb.inspect()
    assert snapshot["$VAR_INST"]["M"]["N"] == 0
    snapshot["$VAR_INST"]["M"]["N"] = 900
    snapshot["$VAR_INST"]["M"]["TIMER"]["IN"] = True
    assert fb.inspect()["$VAR_INST"]["M"]["N"] == 0
    assert fb.inspect()["$VAR_INST"]["M"]["TIMER"]["IN"] is False
    with pytest.raises(ExecutionError):
        fb.call_method("M")
    assert fb.inspect()["$VAR_INST"]["M"]["N"] == 1
    assert fb.inspect()["$VAR_INST"]["M"]["VALUES"] == (1, 0)
    assert fb.output("reads") == 0


def test_this_qualified_owner_constants_work_in_method_bounds_and_initializers():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK B
    VAR CONSTANT N : INT := 2; END_VAR
    METHOD M : INT
    VAR CONSTANT N : INT := 7; Own : INT := THIS^.N; END_VAR
    VAR local : ARRAY[1..THIS^.N] OF INT; END_VAR
    VAR_INST retained : ARRAY[1..THIS^.N] OF INT := [THIS^.N, THIS^.N]; END_VAR
    M := retained[2] + Own + UPPER_BOUND(local, 1);
    END_METHOD
    END_FUNCTION_BLOCK
    """)
    assert rt.instantiate("B").call_method("M").value == 6


def test_property_type_uses_header_scope_before_accessor_local_shadowing():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK B
    VAR CONSTANT N : INT := 5; END_VAR
    VAR_OUTPUT saved : STRING(10); get_local, set_local : INT; END_VAR
    PROPERTY P : STRING(N)
    GET
    VAR CONSTANT N : INT := 2; END_VAR
    get_local := N; P := saved;
    END_GET
    SET
    VAR CONSTANT N : INT := 8; END_VAR
    set_local := N; saved := P;
    END_SET
    END_PROPERTY
    END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("B")
    fb.set_property("P", "abcdefghij")
    assert fb.output("saved") == "abcde"
    assert fb.get_property("P") == "abcde"
    assert fb.output("get_local") == 2
    assert fb.output("set_local") == 8


def test_property_header_defaults_bounds_and_constants_ignore_accessor_locals():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK B
    VAR CONSTANT N : INT := 5; END_VAR
    VAR_OUTPUT seen : INT; END_VAR
    PROPERTY P : INT
    VAR CONSTANT K : INT := N; END_VAR
    VAR header : INT := N; data : ARRAY[1..N] OF INT; END_VAR
    GET
    VAR CONSTANT N : INT := 2; END_VAR
    VAR local : ARRAY[1..K + N] OF INT; END_VAR
    P := header + UPPER_BOUND(data, 1) + K + UPPER_BOUND(local, 1);
    END_GET
    SET
    VAR CONSTANT N : INT := 8; END_VAR
    seen := header + UPPER_BOUND(data, 1) + K;
    END_SET
    END_PROPERTY
    END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("B")
    fb.set_property("P", 0)
    assert fb.output("seen") == 15
    assert fb.get_property("P") == 22


def test_property_type_can_use_header_constant_with_owner_dependency():
    rt = Runtime.from_source("""
    FUNCTION_BLOCK B
    VAR CONSTANT N : INT := 4; END_VAR
    VAR_OUTPUT saved : STRING(10); END_VAR
    PROPERTY P : STRING(K)
    VAR CONSTANT K : INT := N + 1; END_VAR
    GET VAR CONSTANT N : INT := 1; END_VAR P := saved; END_GET
    SET VAR CONSTANT N : INT := 7; END_VAR saved := P; END_SET
    END_PROPERTY
    END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("B")
    fb.set_property("P", "abcdefghij")
    assert fb.output("saved") == "abcde"
    assert fb.get_property("P") == "abcde"


@pytest.mark.parametrize(
    "type_declaration,kind,initial,want",
    [
        ("TYPE Number : INT; END_TYPE", "Number", "3", 3),
        ("TYPE E : (Off, On); END_TYPE", "E", "E.On", "ON"),
        ("TYPE Text : STRING(5); END_TYPE", "Text", "'abcdef'", "abcde"),
    ],
)
def test_property_header_named_types_keep_resolved_value_semantics(
    type_declaration, kind, initial, want
):
    rt = Runtime.from_source(f"""
    {type_declaration}
    FUNCTION_BLOCK B
    PROPERTY P : {kind}
    VAR value : {kind} := {initial}; END_VAR
    GET P := value; END_GET
    END_PROPERTY
    END_FUNCTION_BLOCK
    """)
    result = rt.instantiate("B").get_property("P")
    assert (result.name if kind == "E" else result) == want
