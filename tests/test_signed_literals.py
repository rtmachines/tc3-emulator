"""End-to-end signed64 minimum spelling and checked negation."""

import pytest

from tc_emulator import ExecutionError, Runtime, RuntimeFaultedError


def test_signed_minimum_can_be_evaluated_without_positive_intermediate_overflow():
    runtime = Runtime.from_source("""
        FUNCTION F : BOOL
        F := -9223372036854775808 < 0;
        END_FUNCTION
    """)
    assert runtime.call("F").value is True


def test_double_negation_overflow_faults_at_execution():
    runtime = Runtime.from_source("""
        FUNCTION F : BOOL
        F := -(-9223372036854775808) < 0;
        END_FUNCTION
    """)
    with pytest.raises(ExecutionError):
        runtime.call("F")
    with pytest.raises(RuntimeFaultedError):
        runtime.call("F")
