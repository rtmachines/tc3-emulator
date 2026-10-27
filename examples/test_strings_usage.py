"""Alarm and command handling in ST, tested from Python without a PLC."""

from pathlib import Path

import pytest

from tc_emulator import ExecutionError, Runtime

SOURCE = Path(__file__).with_name("strings.st")


def test_alarm_formatting_retains_case_and_latin1_characters():
    runtime = Runtime.from_files([SOURCE])
    assert runtime.call("F_AlarmText", device="Moteur café", code=42, active=True).value == (
        "Moteur café: alarm 42 [TRUE]"
    )
    assert runtime.call("F_AlarmText", device="DriveA", code=0, active=False).value == (
        "DriveA: alarm 0 [FALSE]"
    )


def test_command_block_accepts_speed_and_retains_previous_speed_for_other_commands():
    runtime = Runtime.from_files([SOURCE])
    block = runtime.instantiate("FB_SpeedCommand")
    block.call(command="SPEED=120")
    assert block.output("accepted") is True
    assert block.output("speed") == 120
    block.call(command="STOP")
    assert block.output("accepted") is False
    assert block.output("speed") == 120
    block.call(command="SPEED=-25")
    assert block.output("accepted") is True
    assert block.output("speed") == -25
    block.call(command="SPEED=")
    assert block.output("accepted") is False
    assert block.output("speed") == -25


def test_malformed_numeric_command_reports_execution_error():
    runtime = Runtime.from_files([SOURCE])
    with pytest.raises(ExecutionError):
        runtime.instantiate("FB_SpeedCommand").call(command="SPEED=12rpm")


def test_recipe_field_passed_by_reference_is_updated_and_truncated():
    runtime = Runtime.from_files([SOURCE])
    recipe = runtime.cell("ST_TextRecipe", {"label": "Batch"})
    label = recipe.field("label")
    assert runtime.call("F_AppendLabel", label=label, suffix="-A").value is True
    assert recipe.value["label"] == "Batch-A"
    recipe.value = {"label": "123456789012345"}
    runtime.call("F_AppendLabel", label=label, suffix="XYZ")
    assert label.value == "123456789012345X"
