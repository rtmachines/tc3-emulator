"""Actions execute against owner state with bounded, lexical temporary activations."""

import pytest

from tc_emulator import ArgumentError, ExecutionError, Runtime, RuntimeFaultedError


def test_python_action_runs_only_selected_body_and_preserves_independent_owners():
    rt = Runtime.from_source("""FUNCTION_BLOCK B
VAR_INPUT amount : INT := 1; END_VAR VAR_OUTPUT n : INT; END_VAR
n := n + 100;
ACTION Add: n := n + amount; END_ACTION
ACTION Clear: n := 0; END_ACTION END_FUNCTION_BLOCK""")
    first, second = rt.instantiate("B"), rt.instantiate("B")
    assert first.call_action("aDd", amount=2) is None
    first.call_action("Add")
    second.call_action("Add")
    assert (first.output("n"), second.output("n")) == (4, 1)
    first.call_action("Clear")
    assert first.output("n") == 0


def test_st_actions_bind_inputs_inouts_outputs_and_reuse_local_aliases():
    rt = Runtime.from_source("""FUNCTION_BLOCK B
VAR_INPUT amount : INT := 1; END_VAR VAR_IN_OUT shared : INT; END_VAR
VAR_OUTPUT n : INT; END_VAR
Add(); THIS^.Add();
ACTION Add: shared := shared + amount; n := shared; END_ACTION END_FUNCTION_BLOCK
PROGRAM Main VAR fb : B; items : ARRAY[1..2] OF B; shared : INT; n : INT; END_VAR
fb(shared := shared); fb.Add(shared := shared, amount := 3, n => n);
items[2].Add(shared := shared);
END_PROGRAM""")
    rt.scan("Main")
    assert rt.program_cell("Main", "shared").value == 6
    assert rt.program_cell("Main", "n").value == 5
    assert rt.program_fb("Main", "fb").output("n") == 5
    assert rt.program_fb("Main", "items", 2).output("n") == 6


def test_python_program_and_st_qualified_program_actions_keep_main_body_separate():
    rt = Runtime.from_source("""PROGRAM Main
VAR_INPUT amount : INT := 2; END_VAR VAR_OUTPUT n : INT; END_VAR
n := n + 100;
ACTION Add: n := n + amount; END_ACTION END_PROGRAM
PROGRAM Other Main.Add(amount := 3); END_PROGRAM""")
    assert rt.call_action("main", "aDd") is None
    rt.scan("Other")
    rt.call_action("Main", "Add")
    assert rt.program_cell("Main", "n").value == 8


def test_program_local_calls_share_program_temporaries_with_actions():
    rt = Runtime.from_source("""PROGRAM Main VAR_OUTPUT n : INT; END_VAR
VAR_TEMP scratch : INT; END_VAR
scratch := 4; Add();
ACTION Add: scratch := scratch + 1; n := scratch; END_ACTION END_PROGRAM""")
    rt.scan("Main")
    assert rt.program_cell("Main", "n").value == 5
    rt.call_action("Main", "Add")
    assert rt.program_cell("Main", "n").value == 1


def test_inherited_action_external_contract_comes_from_receiver_and_api_is_atomic():
    rt = Runtime.from_source("""FUNCTION_BLOCK A VAR_OUTPUT n : INT; END_VAR
ACTION Add: n := n + 1; END_ACTION END_FUNCTION_BLOCK
FUNCTION_BLOCK B EXTENDS A VAR_INPUT extra : INT := 2; END_VAR
VAR_IN_OUT shared : INT; END_VAR END_FUNCTION_BLOCK
PROGRAM Main VAR fb : B; shared : INT; END_VAR
fb.Add(extra := 7, shared := shared); END_PROGRAM""")
    rt.scan("Main")
    assert rt.program_fb("Main", "fb").inspect()["EXTRA"] == 7
    fb = rt.instantiate("B")
    with pytest.raises(ArgumentError, match="Missing required argument SHARED"):
        fb.call_action("Add", extra=100)
    assert fb.inspect()["EXTRA"] == 2 and fb.output("n") == 0
    shared = rt.cell("INT", 0)
    fb.call_action("Add", extra=9, shared=shared)
    assert fb.inspect()["EXTRA"] == 9 and fb.output("n") == 1


def test_base_action_temporary_child_initializes_once_in_derived_activation():
    rt = Runtime.from_source("""VAR_GLOBAL starts : INT; END_VAR
FUNCTION_BLOCK Child METHOD FB_init : BOOL
VAR_INPUT bInitRetains : BOOL; bInCopyCode : BOOL; END_VAR
starts := starts + 1; FB_init := TRUE; END_METHOD END_FUNCTION_BLOCK
FUNCTION_BLOCK A VAR_TEMP child : Child; scratch : INT; END_VAR
VAR_OUTPUT n : INT; END_VAR
ACTION Add: THIS^.scratch := scratch + 1; n := n + scratch; END_ACTION END_FUNCTION_BLOCK
FUNCTION_BLOCK B EXTENDS A Add(); Add(); END_FUNCTION_BLOCK""")
    fb = rt.instantiate("B")
    fb.call()
    assert (fb.output("n"), rt.global_cell("GVL", "starts").value) == (3, 1)
    fb.call_action("Add")
    assert (fb.output("n"), rt.global_cell("GVL", "starts").value) == (4, 2)


def test_actions_override_virtually_from_base_body_method_and_action_with_super():
    rt = Runtime.from_source("""FUNCTION_BLOCK A VAR_OUTPUT n : INT; END_VAR
Hook();
METHOD Run Hook(); END_METHOD
ACTION Both: Hook(); END_ACTION
ACTION Hook: n := n + 1; END_ACTION END_FUNCTION_BLOCK
FUNCTION_BLOCK B EXTENDS A
ACTION Hook: SUPER^.Hook(); n := n + 10; END_ACTION END_FUNCTION_BLOCK""")
    first, second = rt.instantiate("B"), rt.instantiate("B")
    first.call_action("Hook")
    assert first.output("n") == 11
    first.call_method("Run")
    first.call_action("Both")
    assert first.output("n") == 33
    second.call_action("Both")
    assert second.output("n") == 11


def test_active_body_and_nested_actions_share_temps_and_return_only_exits_action():
    rt = Runtime.from_source("""FUNCTION_BLOCK B VAR_OUTPUT n : INT; END_VAR
VAR_TEMP scratch : INT; END_VAR
scratch := 4; Add(); n := n + scratch;
ACTION Add: scratch := scratch + 1; Nested(); RETURN; n := 1000; END_ACTION
ACTION Nested: scratch := scratch + 2; n := scratch; END_ACTION END_FUNCTION_BLOCK""")
    fb = rt.instantiate("B")
    fb.call()
    assert fb.output("n") == 14
    fb.call_action("Add")
    assert fb.output("n") == 3
    fb.call_action("Add")
    assert fb.output("n") == 3


def test_method_local_shadow_does_not_enter_action_scope_but_owner_activation_is_shared():
    rt = Runtime.from_source("""FUNCTION_BLOCK B VAR_OUTPUT n : INT; END_VAR
VAR_TEMP scratch : INT; END_VAR
scratch := 4; Run(); n := n + scratch;
METHOD Run VAR scratch : INT := 100; n : INT := 200; END_VAR
Add(); END_METHOD
ACTION Add: scratch := scratch + 1; n := scratch; END_ACTION END_FUNCTION_BLOCK""")
    fb = rt.instantiate("B")
    fb.call()
    assert fb.output("n") == 10
    fb.call_method("Run")
    assert fb.output("n") == 1


def test_base_temporary_bank_is_lazy_shared_and_lexically_separate_from_derived_bank():
    rt = Runtime.from_source("""VAR_GLOBAL offset : INT := 2; END_VAR
FUNCTION_BLOCK A VAR_OUTPUT n : INT; END_VAR VAR_TEMP scratch : INT; END_VAR
ACTION Add: scratch := scratch + 1; n := n + scratch + offset; END_ACTION
ACTION Both: Add(); Add(); END_ACTION END_FUNCTION_BLOCK
FUNCTION_BLOCK B EXTENDS A VAR_TEMP offset : INT; END_VAR
offset := 100; Both(); n := n + offset;
ACTION Derived: offset := 10; SUPER^.Both(); n := n + offset; END_ACTION
END_FUNCTION_BLOCK""")
    fb = rt.instantiate("B")
    fb.call()
    assert fb.output("n") == 107  # base adds (1 + 2) + (2 + 2); derived adds 100
    fb.call_action("Derived")
    assert fb.output("n") == 124  # a new base bank adds 7; derived adds 10


def test_temporary_child_initializes_once_per_owner_activation_and_action_keeps_fb_init_count():
    rt = Runtime.from_source("""VAR_GLOBAL initCount : INT; END_VAR
FUNCTION_BLOCK Child
METHOD FB_init : BOOL VAR_INPUT bInitRetains : BOOL; bInCopyCode : BOOL; END_VAR
initCount := initCount + 1; FB_init := TRUE; END_METHOD END_FUNCTION_BLOCK
FUNCTION_BLOCK B VAR_OUTPUT n : INT; initCount : INT; END_VAR
VAR_TEMP child : Child; END_VAR
Add(); Add();
METHOD FB_init : BOOL VAR_INPUT bInitRetains : BOOL; bInCopyCode : BOOL; END_VAR
initCount := initCount + 1; FB_init := TRUE; END_METHOD
ACTION Add: n := n + 1; END_ACTION END_FUNCTION_BLOCK""")
    fb = rt.instantiate("B")
    fb.call()
    assert rt.global_cell("GVL", "initCount").value == 1
    fb.call_action("Add")
    assert rt.global_cell("GVL", "initCount").value == 2
    assert (fb.output("n"), fb.output("initCount")) == (3, 1)


@pytest.mark.parametrize("call", ["fb", "program"])
@pytest.mark.parametrize(
    "inputs", [{"amount": 4, "unknown": 1}, {"amount": True}, {"amount": 4, "AMOUNT": 5}]
)
def test_python_action_argument_errors_are_atomic_and_do_not_fault_runtime(call, inputs):
    rt = Runtime.from_source("""FUNCTION_BLOCK B VAR_INPUT amount : INT := 2; END_VAR
VAR_OUTPUT n : INT; END_VAR ACTION Add: n := n + amount; END_ACTION END_FUNCTION_BLOCK
PROGRAM Main VAR_INPUT amount : INT := 2; END_VAR VAR_OUTPUT n : INT; END_VAR
ACTION Add: n := n + amount; END_ACTION END_PROGRAM""")
    fb = rt.instantiate("B")
    invoke = (
        fb.call_action if call == "fb" else lambda name, **kw: rt.call_action("Main", name, **kw)
    )
    with pytest.raises(ArgumentError):
        invoke("Add", **inputs)
    invoke("Add")
    assert (fb.output("n") if call == "fb" else rt.program_cell("Main", "n").value) == 2


def test_python_action_requires_valid_names_and_external_inout_binding_before_mutation():
    rt = Runtime.from_source("""FUNCTION_BLOCK B VAR_INPUT amount : INT := 2; END_VAR
VAR_IN_OUT shared : INT; END_VAR VAR_OUTPUT n : INT; END_VAR
ACTION Add: shared := shared + amount; n := shared; END_ACTION END_FUNCTION_BLOCK""")
    fb = rt.instantiate("B")
    for name in (None, 1, "Missing", "B.Add"):
        with pytest.raises(ArgumentError):
            fb.call_action(name, amount=100)
    with pytest.raises(ArgumentError, match="Missing required"):
        fb.call_action("Add", amount=100)
    shared = rt.cell("INT", 0)
    fb.call_action("Add", shared=shared)
    assert shared.value == fb.output("n") == 2


@pytest.mark.parametrize(
    "limit,kwargs", [("step", {"max_steps": 3}), ("depth", {"max_call_depth": 1})]
)
def test_action_faults_share_limits_stack_and_faulted_runtime_behavior(limit, kwargs):
    rt = Runtime.from_source(
        """FUNCTION_BLOCK B
ACTION Run: Nested(); END_ACTION
ACTION Nested: WHILE TRUE DO END_WHILE; END_ACTION END_FUNCTION_BLOCK""",
        "limits.st",
        **kwargs,
    )
    fb = rt.instantiate("B")
    with pytest.raises(ExecutionError, match="step budget|depth limit") as caught:
        fb.call_action("Run")
    assert caught.value.loc.source == "limits.st"
    assert "B.RUN" in caught.value.stack
    if limit == "step":
        assert "B.NESTED" in caught.value.stack
    with pytest.raises(RuntimeFaultedError):
        fb.call_action("Run")
