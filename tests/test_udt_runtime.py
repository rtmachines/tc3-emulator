"""Real ST programs exercising user types across memory and call boundaries."""

import pytest

from tc_emulator import ArgumentError, Runtime

TYPES = """
TYPE E_State : (Run := 10, Idle := 0, Done); END_TYPE
TYPE T_Speed : REAL := 2.5; END_TYPE
TYPE ST_Config : STRUCT
    speed : T_Speed;
    state : E_State;
    delays : ARRAY[1..2] OF TIME := [T#1s,T#2s];
END_STRUCT END_TYPE
TYPE ST_Group : STRUCT configs : ARRAY[-1..0] OF ST_Config; END_STRUCT END_TYPE
"""


def test_function_returns_struct_defaults_and_prepared_initializer():
    runtime = Runtime.from_source(
        TYPES
        + """FUNCTION DefaultConfig:ST_Config
    END_FUNCTION
    FUNCTION Config:ST_Config
    VAR c:ST_Config := (state:=E_State.Run); END_VAR
    c.speed:=c.speed+1; Config:=c; END_FUNCTION"""
    )
    default = runtime.call("DefaultConfig").value
    assert default["speed"] == 2.5
    assert default["state"].name == "IDLE"
    assert default["delays"] == (1000, 2000)
    value = runtime.call("Config").value
    assert value["speed"] == 3.5
    assert value["state"].value == 10
    with pytest.raises(TypeError):
        value["speed"] = 1.0


def test_alternating_fields_and_indices_with_repeated_struct_initializers():
    runtime = Runtime.from_source(
        TYPES
        + """FUNCTION F:ST_Group
    VAR g:ST_Group := (configs := [2((speed:=4))]); END_VAR
    g.configs[-1].delays[2]:=T#7s;
    g.configs[0].state:=E_State.Done;
    F:=g; END_FUNCTION"""
    )
    group = runtime.call("F").value
    assert group["configs"][0]["delays"] == (1000, 7000)
    assert group["configs"][1]["delays"] == (1000, 2000)
    assert group["configs"][1]["state"].name == "DONE"
    assert group["configs"][0]["speed"] == 4.0


def test_nested_python_cells_keep_aliases_after_whole_struct_replacement():
    runtime = Runtime.from_source(
        TYPES
        + """FUNCTION Change:BOOL
    VAR_IN_OUT config:ST_Config; speed:REAL; delay:TIME; END_VAR
    VAR replacement:ST_Config := (speed:=10,state:=E_State.Run,delays:=[T#3s,T#4s]); END_VAR
    config:=replacement; speed:=speed+1; delay:=delay+T#1ms; Change:=TRUE;
    END_FUNCTION"""
    )
    group = runtime.cell("ST_Group", {})
    config = group.field("configs").element(-1)
    speed = config.field("speed")
    delay = config.field("delays").element(2)
    assert runtime.call("Change", config=config, speed=speed, delay=delay).value is True
    assert config.value["speed"] == speed.value == 11.0
    assert config.value["delays"] == (3000, 4001)
    assert delay.value == 4001
    group.value = {"configs": [{"speed": 20}, {}]}
    assert speed.value == 20.0
    assert delay.value == 2000
    speed.value = 21
    assert group.value["configs"][0]["speed"] == 21.0


def test_struct_input_and_output_are_copies_in_python_and_st():
    runtime = Runtime.from_source(
        TYPES
        + """FUNCTION Change:ST_Config
    VAR_INPUT config:ST_Config; END_VAR
    config.speed:=9; config.delays[1]:=T#9s; Change:=config; END_FUNCTION
    FUNCTION F:REAL
    VAR a,b:ST_Config; END_VAR b:=Change(config:=a); F:=a.speed; END_FUNCTION"""
    )
    original = {"speed": 2, "delays": [10, 20]}
    result = runtime.call("Change", config=original).value
    assert original == {"speed": 2, "delays": [10, 20]}
    assert result["speed"] == 9.0 and result["delays"] == (9000, 20)
    assert runtime.call("F").value == 2.5


def test_fb_struct_state_is_private_per_instance_and_failed_arguments_are_atomic():
    runtime = Runtime.from_source(
        TYPES
        + """FUNCTION_BLOCK B
    VAR_INPUT enable:BOOL; config:ST_Config; END_VAR
    VAR_OUTPUT state:ST_Config; END_VAR
    IF enable THEN state:=config; state.speed:=state.speed+1; END_IF;
    END_FUNCTION_BLOCK"""
    )
    first, second = runtime.instantiate("B"), runtime.instantiate("B")
    first.call(enable=True, config={"speed": 10})
    snapshot = first.output("state")
    assert second.output("state")["speed"] == 2.5
    with pytest.raises(ArgumentError):
        second.call(enable=True, config={"speed": True})
    assert second.inspect()["ENABLE"] is False
    assert second.inspect()["CONFIG"]["speed"] == 2.5
    first.call(config={"speed": 20})
    assert first.output("state")["speed"] == 21.0
    assert snapshot["speed"] == 11.0


def test_enum_values_case_and_aliases_preserve_type():
    runtime = Runtime.from_source(
        TYPES
        + """TYPE T_State:E_State:=E_State.Run; END_TYPE
    FUNCTION Next:E_State
    VAR_INPUT state:T_State; END_VAR
    CASE state OF
      E_State.Idle: Next:=E_State.Run;
      E_State.Run: Next:=E_State.Done;
      ELSE Next:=state;
    END_CASE;
    END_FUNCTION
    FUNCTION IsDone:BOOL VAR_INPUT state:E_State; END_VAR
    IsDone:=state=E_State.Done; END_FUNCTION
    FUNCTION DefaultState:T_State END_FUNCTION"""
    )
    result = runtime.call("Next", state="Idle").value
    assert (result.type_name, result.name, result.value) == ("E_STATE", "RUN", 10)
    done = runtime.call("Next", state=result).value
    assert runtime.call("Next", state="T_State.Run").value == done
    assert runtime.call("IsDone", state=done).value is True
    assert runtime.call("DefaultState").value.name == "RUN"
    for bad in (10, True, "missing"):
        with pytest.raises(ArgumentError):
            runtime.call("Next", state=bad)


def test_alias_arrays_preserve_element_defaults_and_support_chained_indices():
    runtime = Runtime.from_source("""TYPE T_Number:INT:=7; END_TYPE
    TYPE T_Pair:ARRAY[3..4] OF T_Number; END_TYPE
    TYPE T_Matrix:ARRAY[1..2] OF T_Pair; END_TYPE
    FUNCTION F:T_Matrix
    VAR a:T_Matrix; END_VAR a[2][4]:=9; F:=a; END_FUNCTION""")
    assert runtime.call("F").value == ((7, 7), (7, 9))
    cell = runtime.cell("T_Matrix", [[1, 2], [3, 4]])
    item = cell.element(2).element(4)
    cell.value = [[5, 6], [7, 8]]
    assert item.value == 8


def test_struct_output_binding_and_st_inout_to_array_struct_field():
    runtime = Runtime.from_source(
        TYPES
        + """FUNCTION Make:BOOL
    VAR_OUTPUT config:ST_Config; END_VAR config.speed:=8; Make:=TRUE; END_FUNCTION
    FUNCTION Increment:REAL VAR_IN_OUT speed:REAL; END_VAR
    speed:=speed+1; Increment:=speed; END_FUNCTION
    FUNCTION F:REAL VAR g:ST_Group; END_VAR
    Make(config=>g.configs[-1]); Increment(speed:=g.configs[-1].speed);
    F:=g.configs[-1].speed; END_FUNCTION"""
    )
    assert runtime.call("F").value == 9.0


def test_cell_field_errors_and_failed_whole_write_preserve_child_alias():
    runtime = Runtime.from_source(TYPES)
    cell = runtime.cell("ST_Config", {})
    alias = cell.field("speed")
    with pytest.raises(ArgumentError):
        cell.value = {"speed": 10, "delays": [1, True]}
    assert alias.value == 2.5
    with pytest.raises(ArgumentError):
        cell.field("missing")
    with pytest.raises(ArgumentError):
        alias.field("anything")


def test_python_cell_checks_aggregate_budget_before_shape_or_allocation():
    runtime = Runtime.from_source("""TYPE ST_Large:STRUCT
    values:ARRAY[1..1000] OF INT; END_STRUCT END_TYPE""")
    with pytest.raises(ArgumentError, match="leaf limit"):
        runtime.cell("ARRAY[1..1001] OF ST_Large", [])


def test_enum_array_copies_and_element_references_keep_the_enum_type():
    runtime = Runtime.from_source(
        TYPES
        + """TYPE T_States:ARRAY[-1..1] OF E_State; END_TYPE
    FUNCTION Defaults:T_States
    VAR states:T_States:=[E_State.Run]; END_VAR
    Defaults:=states; END_FUNCTION
    FUNCTION Copy:T_States VAR_INPUT states:T_States; END_VAR
    states[0]:=E_State.Done; Copy:=states; END_FUNCTION
    FUNCTION Finish:BOOL VAR_IN_OUT state:E_State; END_VAR
    state:=E_State.Done; Finish:=TRUE; END_FUNCTION"""
    )
    original = runtime.call("Defaults").value
    assert tuple(state.name for state in original) == ("RUN", "IDLE", "IDLE")
    copy = runtime.call("Copy", states=original).value
    assert copy[1].name == "DONE" and original[1].name == "IDLE"
    states = runtime.cell("T_States", original)
    first = states.element(-1)
    runtime.call("Finish", state=first)
    assert states.value[0].name == "DONE"
    before = states.value
    with pytest.raises(ArgumentError):
        states.value = ["Idle", "Run", 1]
    assert states.value == before
    states.value = ["Idle", "Run", "Done"]
    assert first.value.name == "IDLE"
    assert first.value.type_name == "E_STATE"
