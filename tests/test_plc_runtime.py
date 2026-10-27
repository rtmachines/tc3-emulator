"""Persistent PLC storage, read-only aliases and deterministic program cycles."""

import pytest

from tc_emulator import ArgumentError, ExecutionError, Runtime, RuntimeFaultedError
from tc_emulator.memory import Cell
from tc_emulator.types import ArrayType


def test_read_only_cell_blocks_public_and_internal_writes_through_descendants():
    rt = Runtime.from_source("")
    cell = Cell(ArrayType(((1, 2),), "WORD"), [1, 2], rt, read_only=True)
    child = cell.element(1)
    bit = child.bit(0)
    assert cell.read_only and child.read_only and bit.read_only
    for target, value in ((cell, [3, 4]), (child, 3), (bit, False)):
        with pytest.raises(ArgumentError, match="[Rr]ead.only|[Cc]onstant"):
            target.value = value
        with pytest.raises(ExecutionError, match="[Rr]ead.only|[Cc]onstant"):
            target._write(value, None)
    assert cell.value == (1, 2)


def test_read_only_python_inout_rejection_is_atomic():
    rt = Runtime.from_source("""FUNCTION_BLOCK B
        VAR_INPUT input : INT := 2; END_VAR
        VAR_IN_OUT target : INT; END_VAR
        VAR_OUTPUT output : INT; END_VAR
        target := target + 1; output := input; END_FUNCTION_BLOCK""")
    fb = rt.instantiate("B")
    target = Cell("INT", 4, rt, read_only=True)
    with pytest.raises(ArgumentError, match="[Rr]ead.only|[Cc]onstant"):
        fb.call(input=9, target=target)
    assert fb.inspect()["INPUT"] == 2
    assert target.value == 4
    assert fb.output("output") == 0


def test_programs_share_global_state_in_supplied_order_without_time_advance():
    source = """VAR_GLOBAL count : DINT := 3; END_VAR
        PROGRAM First VAR total : DINT; END_VAR
        count := count + 1; total := count; END_PROGRAM
        PROGRAM Second VAR result : DINT; END_VAR
        result := First.total + count; END_PROGRAM"""
    rt = Runtime.from_source(source, gvl_name="Shared")
    assert rt.program_cell("first", "total").value == 0
    assert rt.global_cell("shared", "count").value == 3
    rt.scan("FIRST", "second")
    assert rt.program_cell("Second", "result").value == 8
    assert rt.global_cell("Shared", "count").value == 4
    rt.scan("Second", "First")
    assert rt.program_cell("Second", "result").value == 8
    assert rt.program_cell("First", "total").value == 5
    assert rt.now_ms == 0
    other = Runtime.from_source(source, gvl_name="Shared")
    assert other.global_cell("Shared", "count").value == 3


def test_program_nested_calls_retain_inputs_reset_temp_and_bind_outputs():
    rt = Runtime.from_source("""PROGRAM Worker
        VAR_INPUT step : INT := 1; END_VAR
        VAR_OUTPUT result : INT; END_VAR
        VAR_TEMP scratch : INT := 10; END_VAR
        scratch := scratch + 1; result := result + step + scratch;
        END_PROGRAM
        PROGRAM Main VAR answer : INT; END_VAR
        Worker(step := 2, result => answer); END_PROGRAM""")
    rt.scan("Main")
    assert rt.program_cell("Main", "answer").value == 13
    rt.scan("Worker")
    assert rt.program_cell("Worker", "result").value == 26
    with pytest.raises(ArgumentError):
        rt.program_cell("Worker", "scratch")
    with pytest.raises(ArgumentError):
        rt.instantiate("Worker")
    with pytest.raises(ArgumentError):
        rt.call("Worker")


def test_global_fb_is_shared_by_function_and_program_and_value_access_rejects_it():
    rt = Runtime.from_source("""VAR_GLOBAL counter : Counter; END_VAR
        FUNCTION_BLOCK Counter VAR_OUTPUT value : INT; END_VAR
        value := value + 1; END_FUNCTION_BLOCK
        FUNCTION Increment : INT counter(); Increment := counter.value; END_FUNCTION
        PROGRAM Main VAR answer : INT; END_VAR
        counter(); answer := counter.value; END_PROGRAM""")
    assert rt.call("Increment").value == 1
    rt.scan("Main")
    assert rt.program_cell("Main", "answer").value == 2
    assert rt.call("Increment").value == 3
    with pytest.raises(ArgumentError):
        rt.global_cell("GVL", "counter")


def test_live_cells_global_qualified_paths_local_shadowing_and_constant_children():
    rt = Runtime.from_source("""TYPE S : STRUCT flags : ARRAY[1..1] OF WORD; END_STRUCT END_TYPE
        VAR_GLOBAL count : INT := 4; END_VAR
        VAR_GLOBAL CONSTANT fixed : S := (flags := [1]); END_VAR
        FUNCTION Read : INT Read := GVL.count + fixed.flags[1]; END_FUNCTION
        FUNCTION Shadow : INT VAR GVL : INT := 7; count : INT := 8; END_VAR
        Shadow := GVL + count; END_FUNCTION
        PROGRAM Main VAR count : INT := 20; END_VAR
        count := count + 1; GVL.count := GVL.count + 1; END_PROGRAM""")
    global_count = rt.global_cell("GVL", "count")
    global_count.value = 9
    rt.scan("Main")
    assert global_count.value == 10
    assert rt.program_cell("Main", "count").value == 21
    assert rt.call("Read").value == 11
    assert rt.call("Shadow").value == 15
    fixed = rt.global_cell("GVL", "fixed")
    child = fixed.field("flags").element(1).bit(0)
    assert fixed.read_only and child.read_only
    with pytest.raises(ArgumentError):
        child.value = False


def test_run_cycles_uses_scan_time_then_advances_once_per_successful_cycle():
    rt = Runtime.from_source("""PROGRAM Main
        VAR delay : TON; END_VAR VAR_OUTPUT done : BOOL; elapsed : TIME; END_VAR
        delay(IN := TRUE, PT := T#1s); done := delay.Q; elapsed := delay.ET;
        END_PROGRAM""")
    rt.run_cycles("Main", cycles=100, period_ms=10)
    assert rt.now_ms == 1000
    assert rt.program_cell("Main", "done").value is False
    assert rt.program_cell("Main", "elapsed").value == 990
    rt.run_cycles("Main", cycles=1, period_ms=10)
    assert rt.now_ms == 1010
    assert rt.program_cell("Main", "done").value is True
    assert rt.program_cell("Main", "elapsed").value == 1000


@pytest.mark.parametrize(
    "programs", [(), ("Main", "main"), ("Main", "Missing"), ("Main", 1), ("F",)]
)
def test_scan_name_validation_is_atomic(programs):
    rt = Runtime.from_source("""PROGRAM Main VAR n : INT; END_VAR n := n + 1; END_PROGRAM
        FUNCTION F : INT END_FUNCTION""")
    with pytest.raises(ArgumentError):
        rt.scan(*programs)
    assert rt.program_cell("Main", "n").value == 0
    assert rt.now_ms == 0
    rt.scan("Main")
    assert rt.program_cell("Main", "n").value == 1


@pytest.mark.parametrize(
    "cycles,period", [(True, 1), (-1, 1), (1.0, 1), (1, True), (1, 0), (1, -1), (1, 1.0)]
)
def test_run_cycles_argument_errors_are_atomic(cycles, period):
    rt = Runtime.from_source("PROGRAM Main VAR n : INT; END_VAR n := n + 1; END_PROGRAM")
    with pytest.raises(ArgumentError):
        rt.run_cycles("Main", cycles=cycles, period_ms=period)
    assert rt.program_cell("Main", "n").value == 0
    assert rt.now_ms == 0


def test_zero_cycles_validates_names_without_execution_or_clock_advance():
    rt = Runtime.from_source("PROGRAM Main VAR n : INT; END_VAR n := n + 1; END_PROGRAM")
    rt.run_cycles("Main", cycles=0, period_ms=10)
    assert rt.program_cell("Main", "n").value == 0
    assert rt.now_ms == 0
    with pytest.raises(ArgumentError):
        rt.run_cycles("Main", "main", cycles=0, period_ms=10)
    with pytest.raises(ArgumentError):
        rt.run_cycles(cycles=0, period_ms=10)


def test_scan_shares_step_budget_and_preserves_writes_before_fault():
    rt = Runtime.from_source(
        """PROGRAM First VAR n : INT; END_VAR n := n + 1; END_PROGRAM
        PROGRAM Second VAR n : INT; END_VAR n := n + 1; END_PROGRAM""",
        max_steps=1,
    )
    with pytest.raises(ExecutionError, match="budget"):
        rt.scan("First", "Second")
    assert rt.program_cell("First", "n").value == 1
    assert rt.program_cell("Second", "n").value == 0
    with pytest.raises(RuntimeFaultedError):
        rt.program_cell("First", "n").value = 3
    with pytest.raises(RuntimeFaultedError):
        rt.scan("First")


def test_cycle_fault_keeps_prior_cycles_time_and_skips_remaining_programs():
    rt = Runtime.from_source("""VAR_GLOBAL n : INT; END_VAR
        PROGRAM First n := n + 1; IF n = 3 THEN n := 1 / 0; END_IF; END_PROGRAM
        PROGRAM Second VAR n : INT; END_VAR n := n + 1; END_PROGRAM""")
    with pytest.raises(ExecutionError):
        rt.run_cycles("First", "Second", cycles=5, period_ms=10)
    assert rt.global_cell("GVL", "n").value == 3
    assert rt.program_cell("Second", "n").value == 2
    assert rt.now_ms == 20
    with pytest.raises(RuntimeFaultedError):
        rt.global_cell("GVL", "n").value = 0


def test_each_cycle_gets_a_fresh_budget_and_advance_time_executes_no_program():
    rt = Runtime.from_source(
        "PROGRAM Main VAR n : INT; END_VAR n := n + 1; END_PROGRAM", max_steps=1
    )
    rt.advance_time(7)
    assert rt.program_cell("Main", "n").value == 0
    rt.run_cycles("Main", cycles=4, period_ms=3)
    assert rt.program_cell("Main", "n").value == 4
    assert rt.now_ms == 19


@pytest.mark.parametrize(
    "method,args",
    [
        ("global_cell", ("Missing", "n")),
        ("global_cell", (1, "n")),
        ("global_cell", ("GVL", 1)),
        ("global_cell", ("GVL", "Missing")),
        ("program_cell", ("GVL", "n")),
        ("program_cell", ("Main", "Missing")),
        ("program_cell", (1, "n")),
        ("program_cell", ("Main", 1)),
    ],
)
def test_value_cell_lookup_errors_do_not_fault_runtime(method, args):
    rt = Runtime.from_source("VAR_GLOBAL n : INT; END_VAR PROGRAM Main END_PROGRAM")
    with pytest.raises(ArgumentError):
        getattr(rt, method)(*args)
    rt.scan("Main")


def test_global_and_program_value_handles_can_alias_python_inout_but_constants_cannot():
    rt = Runtime.from_source("""VAR_GLOBAL n : INT := 3; END_VAR
        VAR_GLOBAL CONSTANT fixed : INT := 4; END_VAR
        PROGRAM Main VAR n : INT := 5; END_VAR
        VAR CONSTANT fixed : INT := 6; END_VAR END_PROGRAM
        FUNCTION Change : INT VAR_IN_OUT value : INT; END_VAR
        value := value + 1; Change := value; END_FUNCTION""")
    global_cell = rt.global_cell("GVL", "n")
    program_cell = rt.program_cell("Main", "n")
    assert rt.call("Change", value=global_cell).value == 4
    assert rt.call("Change", value=program_cell).value == 6
    assert global_cell.value == 4 and program_cell.value == 6
    for cell in (rt.global_cell("GVL", "fixed"), rt.program_cell("Main", "fixed")):
        assert cell.read_only
        with pytest.raises(ArgumentError):
            rt.call("Change", value=cell)
    assert rt.global_cell("GVL", "fixed").value == 4
    assert rt.program_cell("Main", "fixed").value == 6


def test_qualified_only_global_fb_and_duplicate_names_share_explicit_storage(tmp_path):
    first = tmp_path / "First.st"
    first.write_text("""{attribute 'qualified_only'}
        VAR_GLOBAL count : INT := 2; shared : Counter; END_VAR""")
    second = tmp_path / "Second.st"
    second.write_text("VAR_GLOBAL count : INT := 5; END_VAR")
    body = tmp_path / "Program.st"
    body.write_text("""FUNCTION_BLOCK Counter VAR_OUTPUT value : INT; END_VAR
        value := value + 1; END_FUNCTION_BLOCK
        FUNCTION Read : INT First.shared(); Read := First.shared.value; END_FUNCTION
        PROGRAM Main VAR answer : INT; END_VAR
        First.shared(); answer := count + First.count + First.shared.value;
        END_PROGRAM""")
    rt = Runtime.from_files([body, second, first])
    assert rt.call("Read").value == 1
    rt.scan("Main")
    assert rt.program_cell("Main", "answer").value == 9
    assert rt.call("Read").value == 3


def test_program_called_from_fb_uses_same_singleton_as_direct_scans_and_functions_read_it():
    rt = Runtime.from_source("""PROGRAM Worker
        VAR_INPUT step : INT := 1; END_VAR VAR_OUTPUT result : INT; END_VAR
        result := result + step; END_PROGRAM
        FUNCTION_BLOCK Caller VAR_OUTPUT answer : INT; END_VAR
        Worker(step := 3, result => answer); END_FUNCTION_BLOCK
        FUNCTION Read : INT Read := Worker.result; END_FUNCTION""")
    caller = rt.instantiate("Caller")
    caller.call()
    assert caller.output("answer") == 3
    rt.scan("Worker")
    assert rt.call("Read").value == 6
    caller.call()
    assert caller.output("answer") == 9
    assert rt.program_cell("Worker", "result").value == 9


def test_nested_programs_consume_the_whole_scan_budget():
    rt = Runtime.from_source(
        """PROGRAM Worker VAR n : INT; END_VAR n := n + 1; END_PROGRAM
        PROGRAM Main Worker(); END_PROGRAM
        PROGRAM Last VAR n : INT; END_VAR n := n + 1; END_PROGRAM""",
        max_steps=2,
    )
    with pytest.raises(ExecutionError, match="budget"):
        rt.scan("Main", "Last")
    assert rt.program_cell("Worker", "n").value == 1
    assert rt.program_cell("Last", "n").value == 0


def test_program_nested_calls_honor_call_depth_limit():
    rt = Runtime.from_source(
        """PROGRAM Worker VAR n : INT; END_VAR n := 1; END_PROGRAM
        PROGRAM Main Worker(); END_PROGRAM""",
        max_call_depth=1,
    )
    with pytest.raises(ExecutionError, match="depth") as raised:
        rt.scan("Main")
    assert raised.value.stack == ("MAIN",)
    assert rt.program_cell("Worker", "n").value == 0


def test_global_aggregate_handles_can_be_acquired_after_fault_for_diagnostics():
    rt = Runtime.from_source("""TYPE S : STRUCT words : ARRAY[1..1] OF WORD; END_STRUCT END_TYPE
        VAR_GLOBAL state : S := (words := [1]); END_VAR
        PROGRAM Main VAR broken : INT; END_VAR
        GVL.state.words[1].1 := TRUE; broken := 1 / 0; END_PROGRAM""")
    with pytest.raises(ExecutionError):
        rt.scan("Main")
    word = rt.global_cell("GVL", "state").field("words").element(1)
    assert word.value == 3 and word.bit(1).value is True
    with pytest.raises(RuntimeFaultedError):
        word.bit(1).value = False


def test_program_fb_valued_entries_are_not_public_value_cells():
    rt = Runtime.from_source("PROGRAM Main VAR delay : TON; END_VAR END_PROGRAM")
    with pytest.raises(ArgumentError):
        rt.program_cell("Main", "delay")
    rt.scan("Main")


@pytest.mark.parametrize(
    "declaration,owner",
    [
        ("PROGRAM Main VAR child : N0; END_VAR END_PROGRAM", "MAIN"),
        ("VAR_GLOBAL child : N0; END_VAR", "GVL"),
    ],
)
def test_deep_persistent_frame_allocation_reports_source_aware_execution_error(declaration, owner):
    source = "\n".join(
        f"FUNCTION_BLOCK N{i} "
        + (f"VAR child : N{i + 1}; END_VAR " if i < 599 else "")
        + "END_FUNCTION_BLOCK"
        for i in range(600)
    )
    with pytest.raises(ExecutionError, match="[Nn]esting") as raised:
        Runtime.from_source(source + "\n" + declaration, source="deep.st")
    assert raised.value.loc.source == "deep.st"
    assert raised.value.stack == (owner,)
