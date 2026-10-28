"""Native FB initialization makes each conveyor ready before its first scan."""

from pathlib import Path

from tc_emulator import Runtime

SOURCES = Path(__file__).parent / "conveyor_initialization"


def conveyor_line():
    return Runtime.from_files(sorted(SOURCES.glob("*.Tc*"), reverse=True))


def assert_initialized(conveyor, conveyor_id, delay):
    assert conveyor.output("id") == conveyor_id
    assert conveyor.inspect()["STARTDELAY"] == delay
    assert conveyor.get_property("SpeedFactor") == 1.0
    assert conveyor.output("ready") is True
    assert conveyor.output("initTrace") == 12345
    assert conveyor.output("baseInitCount") == 1
    assert conveyor.output("derivedInitCount") == 1
    assert conveyor.output("afterInitCount") == 1


def test_three_instances_are_initialized_before_the_first_scan():
    rt = conveyor_line()
    for index, delay in ((1, 100), (2, 250), (3, 500)):
        conveyor = rt.program_fb("MAIN_Line", "conveyors", index)
        assert_initialized(conveyor, index, delay)
        assert conveyor.output("running") is False
        assert conveyor.output("actualSpeed") == 0.0


def test_per_element_delays_keep_three_timers_independent():
    rt = conveyor_line()
    rt.scan("MAIN_Line")
    running = rt.global_cell("GVL_Line", "running")
    assert running.value == (False, False, False)
    rt.advance_time(99)
    rt.scan("MAIN_Line")
    assert running.value == (False, False, False)
    rt.advance_time(1)
    rt.scan("MAIN_Line")
    assert running.value == (True, False, False)
    rt.advance_time(150)
    rt.scan("MAIN_Line")
    assert running.value == (True, True, False)
    rt.advance_time(250)
    rt.scan("MAIN_Line")
    assert running.value == (True, True, True)
    assert rt.global_cell("GVL_Line", "actualSpeed").value == (0.75, 0.75, 0.75)


def test_shared_configuration_edits_reset_and_restart_each_delay():
    rt = conveyor_line()
    rt.scan("MAIN_Line")
    rt.advance_time(500)
    rt.scan("MAIN_Line")
    config = rt.global_cell("GVL_Line", "config")
    config.field("speed").value = 0.4
    rt.scan("MAIN_Line")
    assert rt.global_cell("GVL_Line", "actualSpeed").value == (0.4, 0.4, 0.4)
    config.field("enabled").value = False
    rt.scan("MAIN_Line")
    assert rt.global_cell("GVL_Line", "running").value == (False, False, False)
    assert rt.global_cell("GVL_Line", "actualSpeed").value == (0.0, 0.0, 0.0)
    rt.advance_time(1000)
    config.field("enabled").value = True
    rt.scan("MAIN_Line")
    assert rt.global_cell("GVL_Line", "running").value == (False, False, False)
    for advance, expected in (
        (100, (True, False, False)),
        (150, (True, True, False)),
        (250, (True, True, True)),
    ):
        rt.advance_time(advance)
        rt.scan("MAIN_Line")
        assert rt.global_cell("GVL_Line", "running").value == expected
    assert rt.global_cell("GVL_Line", "actualSpeed").value == (0.4, 0.4, 0.4)


def test_repeated_scans_and_input_changes_do_not_repeat_initialization():
    rt = conveyor_line()
    second = rt.program_fb("MAIN_Line", "conveyors", 2)
    second.set_input("enable", False)
    rt.scan("MAIN_Line")
    rt.advance_time(500)
    rt.scan("MAIN_Line")
    assert rt.global_cell("GVL_Line", "running").value == (True, False, True)
    second.set_input("enable", True)
    rt.scan("MAIN_Line")
    rt.advance_time(250)
    rt.scan("MAIN_Line")
    rt.scan("MAIN_Line")
    assert rt.global_cell("GVL_Line", "running").value == (True, True, True)
    for index, delay in ((1, 100), (2, 250), (3, 500)):
        assert_initialized(rt.program_fb("MAIN_Line", "conveyors", index), index, delay)


def test_python_instantiation_binds_one_cell_and_applies_inputs_before_hooks():
    rt = conveyor_line()
    config = rt.cell("ST_ConveyorConfig", {"enabled": True, "speed": 0.6})
    first = rt.instantiate(
        "FB_Conveyor",
        init={"conveyorId": 10, "sharedConfig": config, "defaultDelay": 900},
        inputs={"StartDelay": 100, "SpeedFactor": 1.0},
    )
    second = rt.instantiate(
        "FB_Conveyor",
        init={"conveyorId": 20, "sharedConfig": config},
        inputs={"StartDelay": 250, "SpeedFactor": 1.0},
    )
    assert_initialized(first, 10, 100)
    assert_initialized(second, 20, 250)
    first.call()
    second.call()
    rt.advance_time(100)
    first.call()
    second.call()
    assert first.output("running") is True
    assert second.output("running") is False
    rt.advance_time(150)
    first.call()
    second.call()
    assert first.output("actualSpeed") == 0.6
    assert second.output("actualSpeed") == 0.6
    config.field("speed").value = 0.2
    first.call()
    second.call()
    assert first.output("actualSpeed") == 0.2
    assert second.output("actualSpeed") == 0.2
    assert rt.global_cell("GVL_Line", "config").field("speed").value == 0.75
    assert_initialized(first, 10, 100)
    assert_initialized(second, 20, 250)
