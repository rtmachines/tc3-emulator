"""Cross-file and cross-POU execution with persistent PLC storage."""

import pytest

from tc_emulator import ArgumentError, ExecutionError, Runtime, RuntimeFaultedError


def test_functions_and_programs_share_global_state_but_local_names_shadow_it():
    source = """VAR_GLOBAL total:DINT; END_VAR
    FUNCTION Bump:DINT total:=total+1; Bump:=total; END_FUNCTION
    PROGRAM First VAR total:DINT:=100; ignored:DINT; END_VAR
    ignored:=Bump(); total:=total+1; END_PROGRAM
    PROGRAM Second GVL.total:=GVL.total+2; END_PROGRAM"""
    runtime = Runtime.from_source(source)
    runtime.scan("First", "Second")
    assert runtime.global_cell("GVL", "total").value == 3
    assert runtime.program_cell("First", "total").value == 101
    assert runtime.call("Bump").value == 4
    other = Runtime.from_source(source)
    assert other.global_cell("GVL", "total").value == 0
    assert other.program_cell("First", "total").value == 100


def test_global_fb_is_the_same_instance_for_function_and_program_calls():
    runtime = Runtime.from_source("""FUNCTION_BLOCK Counter
    VAR_OUTPUT count:DINT; END_VAR count:=count+1; END_FUNCTION_BLOCK
    VAR_GLOBAL shared:Counter; END_VAR
    FUNCTION ReadNext:DINT GVL.shared(); ReadNext:=GVL.shared.count; END_FUNCTION
    PROGRAM MAIN GVL.shared(); END_PROGRAM""")
    assert runtime.call("ReadNext").value == 1
    runtime.scan("MAIN")
    assert runtime.call("ReadNext").value == 3
    with pytest.raises(ArgumentError):
        runtime.global_cell("GVL", "shared")


def test_global_constants_define_named_types_and_capacities_independent_of_file_order(tmp_path):
    main = tmp_path / "main.st"
    main.write_text("""TYPE Buffer:ARRAY[0..A.n-1] OF WORD; END_TYPE
    PROGRAM MAIN
    VAR words:Buffer; labels:ARRAY[1..A.n] OF STRING(B.limit+2); END_VAR
    words[2]:=16#CAFE; labels[3]:='ABCDE'; END_PROGRAM""")
    a = tmp_path / "A.st"
    a.write_text("VAR_GLOBAL CONSTANT n:INT:=B.limit+1; END_VAR")
    b = tmp_path / "B.st"
    b.write_text("{attribute 'qualified_only'} VAR_GLOBAL CONSTANT limit:INT:=2; END_VAR")
    for files in ([main, a, b], [b, a, main]):
        runtime = Runtime.from_files(files)
        runtime.scan("MAIN")
        assert runtime.program_cell("MAIN", "words").value == (0, 0, 0xCAFE)
        assert runtime.program_cell("MAIN", "labels").value == ("", "", "ABCD")


def test_local_structure_name_shadows_gvl_namespace():
    runtime = Runtime.from_source(
        """TYPE S:STRUCT value:INT; END_STRUCT END_TYPE
    VAR_GLOBAL value:INT:=99; END_VAR
    FUNCTION F:INT VAR State:S:=(value:=3); END_VAR
    State.value:=4; F:=State.value; END_FUNCTION""",
        gvl_name="State",
    )
    assert runtime.call("F").value == 4
    assert runtime.global_cell("State", "value").value == 99


def test_program_calls_share_persistent_inputs_and_output_binding():
    runtime = Runtime.from_source("""PROGRAM Worker
    VAR_INPUT step:INT:=1; END_VAR VAR_OUTPUT count:INT; END_VAR
    VAR_TEMP scratch:INT; END_VAR scratch:=scratch+1; count:=count+step+scratch;
    END_PROGRAM
    PROGRAM MAIN VAR observed:INT; END_VAR
    Worker(step:=3,count=>observed); END_PROGRAM
    FUNCTION_BLOCK Trigger Worker(); END_FUNCTION_BLOCK""")
    runtime.scan("MAIN")
    assert runtime.program_cell("MAIN", "observed").value == 4
    runtime.instantiate("Trigger").call()
    assert runtime.program_cell("Worker", "count").value == 8
    runtime.scan("Worker")
    assert runtime.program_cell("Worker", "count").value == 12
    with pytest.raises(ArgumentError):
        runtime.program_cell("Worker", "scratch")


def test_global_constant_descendants_are_readonly_in_python_and_inout():
    runtime = Runtime.from_source("""TYPE S:STRUCT labels:ARRAY[1..1] OF STRING(4); bits:WORD;
    END_STRUCT END_TYPE VAR_GLOBAL CONSTANT config:S:=(labels:=['old'],bits:=1); END_VAR
    FUNCTION Mutate:BOOL VAR_IN_OUT value:STRING(4); END_VAR
    value:='new'; Mutate:=TRUE; END_FUNCTION""")
    config = runtime.global_cell("GVL", "config")
    label = config.field("labels").element(1)
    bit = config.field("bits").bit(0)
    assert config.read_only and label.read_only and bit.read_only
    with pytest.raises(ArgumentError):
        label.value = "new"
    with pytest.raises(ArgumentError):
        bit.value = False
    with pytest.raises(ArgumentError):
        runtime.call("Mutate", value=label)
    assert label.value == "old" and bit.value is True


def test_global_and_program_handles_stay_live_after_parent_replacement():
    runtime = Runtime.from_source("""TYPE S:STRUCT name:STRING(4); data:ARRAY[1..2] OF INT;
    END_STRUCT END_TYPE VAR_GLOBAL state:S; END_VAR
    PROGRAM MAIN VAR local:S:=(name:='new',data:=[3,4]); END_VAR
    GVL.state:=local; END_PROGRAM""")
    state = runtime.global_cell("GVL", "state")
    alias = state.field("data").element(2)
    runtime.scan("MAIN")
    assert alias.value == 4
    runtime.program_cell("MAIN", "local").value = {"name": "café", "data": [8, 9]}
    runtime.scan("MAIN")
    assert alias.value == 9 and state.value["name"] == "café"
    alias.value = 10
    assert state.value["data"] == (8, 10)


def test_failed_cycle_preserves_prior_writes_and_exposes_new_diagnostic_handles():
    runtime = Runtime.from_source("""VAR_GLOBAL x:INT; END_VAR
    PROGRAM A GVL.x:=GVL.x+1; END_PROGRAM
    PROGRAM B VAR divisor:INT:=1; END_VAR divisor:=divisor-1; GVL.x:=1/divisor; END_PROGRAM
    PROGRAM C GVL.x:=99; END_PROGRAM""")
    runtime.advance_time(milliseconds=50)
    with pytest.raises(ExecutionError):
        runtime.run_cycles("A", "B", "C", cycles=3, period_ms=10)
    assert runtime.now_ms == 50
    assert runtime.global_cell("GVL", "x").value == 1
    assert runtime.program_cell("B", "divisor").value == 0
    with pytest.raises(RuntimeFaultedError):
        runtime.global_cell("GVL", "x").value = 0
