"""Executable examples of configurations, recipes and a timed state machine."""

from pathlib import Path

from tc_emulator import EnumValue, Runtime, StructValue

EXAMPLES = Path(__file__).resolve().parent


def load_runtime():
    # ST refers to ST_Config before its declaration in the second file is loaded.
    return Runtime.from_files([EXAMPLES / "user_types.st", EXAMPLES / "ST_Config.TcDUT"])


def test_struct_input_is_copied_and_missing_fields_use_defaults():
    runtime = load_runtime()
    original = {"speed": 2.0}
    result = runtime.call("F_Accelerated", config=original).value
    assert isinstance(result, StructValue)
    assert result.type_name == "ST_CONFIG"
    assert result["speed"] == 3.0
    assert result["delay"] == 100
    assert result["enabled"] is True
    assert original == {"speed": 2.0}


def test_inout_updates_struct_and_preserves_a_field_reference():
    runtime = load_runtime()
    config = runtime.cell("ST_Config", {})
    speed = config.field("speed")
    runtime.call("F_SetSpeed", config=config, speed=7.5)
    assert speed.value == 7.5
    config.value = {"speed": 4.0}
    assert speed.value == 4.0
    speed.value = 5.0
    assert config.value["speed"] == 5.0


def test_array_of_structures_and_chained_access():
    runtime = load_runtime()
    recipe = runtime.call("F_Recipe").value
    assert tuple(config["speed"] for config in recipe) == (2.0, 4.0, 1.5)
    assert tuple(config["delay"] for config in recipe) == (50, 100, 100)
    configs = runtime.cell("T_Recipe", recipe)
    runtime.call("F_SetSpeed", config=configs.element(-1), speed=9.0)
    assert configs.element(-1).field("speed").value == 9.0
    assert recipe[0]["speed"] == 2.0  # The earlier result is a detached snapshot.


def test_enum_state_machine_uses_configuration_and_virtual_time():
    runtime = load_runtime()
    machine = runtime.instantiate("FB_Machine")
    assert machine.output("state").name == "IDLE"
    machine.call(start=True, config={"speed": 6.0, "delay": 1000})
    assert machine.output("state").name == "WAITING"
    runtime.advance_time(999)
    machine.call()
    assert machine.output("activeSpeed") == 0.0
    runtime.advance_time(1)
    machine.call()
    state = machine.output("state")
    assert isinstance(state, EnumValue)
    assert (state.type_name, state.name, state.value) == ("E_STATE", "RUNNING", 20)
    assert machine.output("activeSpeed") == 6.0
    machine.call(start=False)
    assert machine.output("state").name == "IDLE"
    assert machine.output("activeSpeed") == 0.0
