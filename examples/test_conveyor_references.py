"""Three independent conveyor states share one ordinary configuration STRUCT."""

from pathlib import Path

from tc_emulator import Runtime

SOURCES = Path(__file__).parent / "conveyor_references"


def conveyor_line():
    return Runtime.from_files(sorted(SOURCES.glob("*.Tc*"), reverse=True))


def test_shared_default_configuration_starts_all_after_100_virtual_ms():
    rt = conveyor_line()
    rt.scan("MAIN_Line")
    assert rt.global_cell("GVL_Line", "running").value == (False, False, False)
    assert rt.global_cell("GVL_Line", "actualSpeed").value == (0.0, 0.0, 0.0)
    assert rt.global_cell("GVL_Line", "missingConfig").value == (False, False, False)
    rt.advance_time(99)
    rt.scan("MAIN_Line")
    assert rt.global_cell("GVL_Line", "running").value == (False, False, False)
    rt.advance_time(1)
    rt.scan("MAIN_Line")
    assert rt.global_cell("GVL_Line", "running").value == (True, True, True)
    assert rt.global_cell("GVL_Line", "actualSpeed").value == (0.75, 0.75, 0.75)


def test_python_configuration_edits_reach_all_existing_conveyors():
    rt = conveyor_line()
    rt.scan("MAIN_Line")
    rt.advance_time(100)
    rt.scan("MAIN_Line")
    config = rt.global_cell("GVL_Line", "config")
    config.field("speed").value = 0.4
    rt.scan("MAIN_Line")
    assert rt.global_cell("GVL_Line", "actualSpeed").value == (0.4, 0.4, 0.4)
    config.field("enabled").value = False
    rt.scan("MAIN_Line")
    assert rt.global_cell("GVL_Line", "running").value == (False, False, False)
    assert rt.global_cell("GVL_Line", "actualSpeed").value == (0.0, 0.0, 0.0)
    assert rt.global_cell("GVL_Line", "missingConfig").value == (False, False, False)
    config.field("enabled").value = True
    rt.scan("MAIN_Line")
    rt.advance_time(99)
    rt.scan("MAIN_Line")
    assert rt.global_cell("GVL_Line", "running").value == (False, False, False)
    rt.advance_time(1)
    rt.scan("MAIN_Line")
    assert rt.global_cell("GVL_Line", "actualSpeed").value == (0.4, 0.4, 0.4)


def test_detach_only_second_then_reattach_starts_its_own_fresh_timer():
    rt = conveyor_line()
    rt.scan("MAIN_Line")
    rt.advance_time(100)
    rt.scan("MAIN_Line")
    second = rt.program_fb("MAIN_Line", "conveyors", 2)
    second.set_input("config", 0)
    rt.scan("MAIN_Line")
    assert rt.global_cell("GVL_Line", "running").value == (True, False, True)
    assert rt.global_cell("GVL_Line", "actualSpeed").value == (0.75, 0.0, 0.75)
    assert rt.global_cell("GVL_Line", "missingConfig").value == (False, True, False)
    assert second.output("alarm") == "Missing configuration"
    rt.advance_time(1000)
    rt.scan("MAIN_Line")
    assert rt.global_cell("GVL_Line", "running").value == (True, False, True)
    second.set_input("config", rt.global_cell("GVL_Line", "config"))
    rt.scan("MAIN_Line")
    assert rt.global_cell("GVL_Line", "missingConfig").value == (False, False, False)
    assert rt.global_cell("GVL_Line", "running").value == (True, False, True)
    assert second.output("alarm") == "Starting"
    rt.advance_time(99)
    rt.scan("MAIN_Line")
    assert rt.global_cell("GVL_Line", "running").value == (True, False, True)
    rt.advance_time(1)
    rt.scan("MAIN_Line")
    assert rt.global_cell("GVL_Line", "running").value == (True, True, True)
    assert rt.global_cell("GVL_Line", "actualSpeed").value == (0.75, 0.75, 0.75)
    assert second.output("alarm") == ""
