"""New-instance lifecycle ordering, storage ownership and public API contracts."""

import pytest

from tc_emulator import ArgumentError, ExecutionError, Runtime, RuntimeFaultedError

FLAGS = "VAR_INPUT bInitRetains : BOOL; bInCopyCode : BOOL; END_VAR"


def test_init_flags_false_result_and_post_inputs_precede_hook_once():
    rt = Runtime.from_source(f"""
    {{attribute 'call_after_init'}} FUNCTION_BLOCK B
    VAR_INPUT n : INT; END_VAR
    VAR_OUTPUT retains, copy, ready : BOOL; seen, count : INT; END_VAR
    METHOD FB_init : BOOL {FLAGS}
    VAR_INPUT value : INT := 1; END_VAR
    retains := bInitRetains; copy := bInCopyCode; n := value; count := count + 1;
    FB_init := FALSE;
    END_METHOD
    {{attribute 'call_after_init'}} METHOD ReadyUp
    seen := n; ready := TRUE;
    END_METHOD END_FUNCTION_BLOCK
    PROGRAM P VAR b : B(value := 1) := (n := 2); END_VAR b(); END_PROGRAM
    """)
    fb = rt.program_fb("P", "b")
    assert fb.inspect() == {
        "N": 2,
        "RETAINS": True,
        "COPY": False,
        "READY": True,
        "SEEN": 2,
        "COUNT": 1,
    }
    rt.scan("P")
    rt.scan("P")
    assert fb.output("count") == 1
    other = rt.instantiate("B", init={"VaLuE": 3}, inputs={"n": 4})
    assert other.output("seen") == 4


def test_inherited_init_is_static_and_effective_hooks_run_once_per_name():
    rt = Runtime.from_source(f"""
    {{attribute 'call_after_init'}} FUNCTION_BLOCK A
    VAR_OUTPUT trace : INT; END_VAR
    METHOD FB_init : BOOL {FLAGS} VAR_INPUT n : INT := 1; END_VAR
    trace := trace * 10 + n;
    END_METHOD
    {{attribute 'call_after_init'}} METHOD Hook
    trace := trace * 10 + 3;
    END_METHOD END_FUNCTION_BLOCK
    {{attribute 'call_after_init'}} FUNCTION_BLOCK B EXTENDS A
    METHOD FB_init : BOOL {FLAGS} VAR_INPUT n : INT := 1; extra : INT := 2; END_VAR
    trace := trace * 10 + extra;
    END_METHOD
    {{attribute 'call_after_init'}} METHOD Hook
    SUPER^.Hook(); trace := trace * 10 + 4;
    END_METHOD END_FUNCTION_BLOCK
    {{attribute 'call_after_init'}} FUNCTION_BLOCK C EXTENDS B END_FUNCTION_BLOCK
    """)
    assert rt.instantiate("C").output("trace") == 1234


def test_array_elements_receive_flat_arguments_and_post_values_in_order():
    rt = Runtime.from_source(f"""
    FUNCTION_BLOCK B VAR_INPUT n : INT; END_VAR VAR_OUTPUT id : INT; END_VAR
    METHOD FB_init : BOOL {FLAGS} VAR_INPUT value : INT; END_VAR
    id := value;
    END_METHOD END_FUNCTION_BLOCK
    PROGRAM P VAR b : ARRAY[-1..0, 2..3] OF B[(1), (2), (3), (4)]
    := [(n := 5), (n := 6), (n := 7), (n := 8)]; END_VAR END_PROGRAM
    """)
    assert [
        (rt.program_fb("P", "b", i, j).output("id"), rt.program_fb("P", "b", i, j).inspect()["N"])
        for i in (-1, 0)
        for j in (2, 3)
    ] == [(1, 5), (2, 6), (3, 7), (4, 8)]


def test_post_setter_effects_are_visible_to_later_rhs_then_hooks():
    rt = Runtime.from_source(f"""
    VAR_GLOBAL shared : INT := 2; END_VAR
    {{attribute 'call_after_init'}} FUNCTION_BLOCK B
    VAR_INPUT n : INT; END_VAR VAR_OUTPUT seen : INT; END_VAR
    METHOD FB_init : BOOL {FLAGS} shared := 3; END_METHOD
    PROPERTY Update : INT SET shared := Update; END_SET END_PROPERTY
    {{attribute 'call_after_init'}} METHOD Hook seen := n; END_METHOD END_FUNCTION_BLOCK
    PROGRAM P VAR b : B := (Update := 7, n := shared); END_VAR END_PROGRAM
    """)
    assert rt.program_fb("P", "b").output("seen") == 7


def test_all_persistent_reference_bindings_exist_before_nested_constructor():
    rt = Runtime.from_source(f"""
    VAR_GLOBAL first : Owner; forward : REFERENCE TO INT := data; data : INT := 9; END_VAR
    FUNCTION_BLOCK Leaf VAR_OUTPUT seen : INT; END_VAR
    METHOD FB_init : BOOL {FLAGS} VAR_INPUT ref : REFERENCE TO INT; END_VAR
    seen := ref; ref := ref + 1;
    END_METHOD END_FUNCTION_BLOCK
    FUNCTION_BLOCK Owner VAR child : Leaf(forward); END_VAR END_FUNCTION_BLOCK
    """)
    assert rt.global_fb("GVL", "first").fb("child").output("seen") == 9
    assert rt.global_cell("GVL", "data").value == 10


def test_transient_children_observe_bound_function_method_and_temp_inputs():
    rt = Runtime.from_source(f"""
    VAR_GLOBAL count : INT; END_VAR
    FUNCTION_BLOCK Leaf VAR_OUTPUT seen : INT; END_VAR
    METHOD FB_init : BOOL {FLAGS} VAR_INPUT n : INT; END_VAR
    seen := n; count := count + 1; END_METHOD END_FUNCTION_BLOCK
    FUNCTION F : INT VAR_INPUT n : INT; END_VAR VAR child : Leaf(n); END_VAR
    F := child.seen; END_FUNCTION
    FUNCTION_BLOCK Owner VAR_INPUT n : INT; END_VAR VAR_OUTPUT seen : INT; END_VAR
    VAR_TEMP child : Leaf(n); END_VAR seen := child.seen;
    METHOD Read : INT VAR_INPUT n : INT; END_VAR VAR child : Leaf(n); END_VAR
    Read := child.seen; END_METHOD END_FUNCTION_BLOCK
    """)
    assert rt.call("F", n=4).value == 4
    assert rt.call("F", n=5).value == 5
    fb = rt.instantiate("Owner")
    assert fb.call_method("Read", n=6).value == 6
    fb.call(n=7)
    assert fb.output("seen") == 7
    fb.call(n=8)
    assert fb.output("seen") == 8
    assert rt.global_cell("GVL", "count").value == 5


def test_var_inst_children_initialize_once_in_the_lexical_owner_scope():
    rt = Runtime.from_source(f"""
    VAR_GLOBAL n : INT := 2; count : INT; END_VAR
    FUNCTION_BLOCK Leaf VAR_OUTPUT seen : INT; END_VAR
    METHOD FB_init : BOOL {FLAGS} VAR_INPUT n : INT; END_VAR
    seen := n; count := count + 1; END_METHOD END_FUNCTION_BLOCK
    FUNCTION_BLOCK A
    METHOD Read : INT VAR n : INT := 50; END_VAR VAR_INST child : Leaf(n); END_VAR
    Read := child.seen; END_METHOD END_FUNCTION_BLOCK
    FUNCTION_BLOCK B EXTENDS A VAR n : INT := 99; END_VAR END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("B")
    assert fb.call_method("Read").value == 2
    assert fb.call_method("Read").value == 2
    assert rt.global_cell("GVL", "count").value == 1


def test_inherited_declaration_arguments_keep_lexical_scope():
    rt = Runtime.from_source(f"""
    VAR_GLOBAL n : INT := 3; END_VAR
    FUNCTION_BLOCK Leaf VAR_OUTPUT seen : INT; END_VAR
    METHOD FB_init : BOOL {FLAGS} VAR_INPUT n : INT; END_VAR
    seen := n; END_METHOD END_FUNCTION_BLOCK
    FUNCTION_BLOCK A VAR child : Leaf(n); END_VAR END_FUNCTION_BLOCK
    FUNCTION_BLOCK B EXTENDS A VAR n : INT := 8; END_VAR END_FUNCTION_BLOCK
    """)
    assert rt.instantiate("B").fb("child").output("seen") == 3


@pytest.mark.parametrize(
    "kwargs",
    [
        {"init": {}},
        {"init": {"n": 1, "N": 2}},
        {"init": {"typo": 1}},
        {"init": {"n": True}},
        {"init": {"n": 1, "bInitRetains": True}},
        {"init": []},
        {"init": {"n": 1}, "inputs": {"input": 2, "typo": 3}},
        {"init": {"n": 1}, "inputs": {"input": 2, "INPUT": 3}},
        {"init": {"n": 1}, "inputs": {"input": True}},
        {"init": {"n": 1}, "inputs": []},
    ],
)
def test_python_mapping_errors_are_atomic_and_leave_runtime_healthy(kwargs):
    rt = Runtime.from_source(f"""
    VAR_GLOBAL runs : INT; END_VAR FUNCTION_BLOCK B VAR_INPUT input : INT; END_VAR
    METHOD FB_init : BOOL {FLAGS} VAR_INPUT n : INT; END_VAR
    runs := runs + 1; END_METHOD END_FUNCTION_BLOCK
    """)
    with pytest.raises(ArgumentError):
        rt.instantiate("B", **kwargs)
    assert rt.global_cell("GVL", "runs").value == 0
    rt.instantiate("B", init={"n": 1})
    assert rt.global_cell("GVL", "runs").value == 1


def test_python_direct_init_call_is_rejected_without_faulting():
    rt = Runtime.from_source(
        f"FUNCTION_BLOCK B METHOD FB_init : BOOL {FLAGS} END_METHOD END_FUNCTION_BLOCK"
    )
    fb = rt.instantiate("B")
    with pytest.raises(ArgumentError, match="Explicit FB_init"):
        fb.call_method("FB_init", bInitRetains=True, bInCopyCode=False)
    fb.call()


@pytest.mark.parametrize("stage", ["init", "setter", "hook"])
def test_initialization_execution_faults_latch_runtime_with_source_location(stage):
    failure = "n := 1 / 0;"
    rt = Runtime.from_source(
        f"""
    {{attribute 'call_after_init'}} FUNCTION_BLOCK B VAR n : INT; END_VAR
    METHOD FB_init : BOOL {FLAGS} {failure if stage == "init" else ""} END_METHOD
    PROPERTY Value : INT SET {failure if stage == "setter" else ""} END_SET END_PROPERTY
    {{attribute 'call_after_init'}} METHOD Hook {failure if stage == "hook" else ""} END_METHOD
    END_FUNCTION_BLOCK
    """,
        "fault_init.st",
    )
    with pytest.raises(ExecutionError) as caught:
        rt.instantiate("B", inputs={"Value": 2})
    assert caught.value.loc.source == "fault_init.st"
    assert caught.value.stack
    with pytest.raises(RuntimeFaultedError):
        rt.instantiate("B")


def test_startup_initializers_share_one_step_budget():
    with pytest.raises(ExecutionError, match="step budget"):
        Runtime.from_source(
            f"""
        VAR_GLOBAL count : INT; a, b, c : B; END_VAR
        FUNCTION_BLOCK B METHOD FB_init : BOOL {FLAGS} count := count + 1;
        END_METHOD END_FUNCTION_BLOCK
        """,
            max_steps=2,
        )


def test_constructor_and_nested_function_share_call_depth_limit():
    rt = Runtime.from_source(
        f"""
    FUNCTION F : INT F := 1; END_FUNCTION FUNCTION_BLOCK B VAR n : INT; END_VAR
    METHOD FB_init : BOOL {FLAGS} n := F(); END_METHOD END_FUNCTION_BLOCK
    """,
        max_call_depth=1,
    )
    with pytest.raises(ExecutionError, match="depth limit"):
        rt.instantiate("B")
    with pytest.raises(RuntimeFaultedError):
        rt.call("F")


def test_init_reference_and_interface_inputs_preserve_identity_and_allow_null():
    rt = Runtime.from_source(f"""
    INTERFACE I METHOD Read : INT END_METHOD END_INTERFACE
    FUNCTION_BLOCK Provider IMPLEMENTS I VAR_INPUT n : INT; END_VAR
    METHOD Read : INT Read := n; END_METHOD END_FUNCTION_BLOCK
    FUNCTION_BLOCK B VAR saved : REFERENCE TO INT; item : I; END_VAR
    VAR_INPUT post : REFERENCE TO INT; peer : I; END_VAR
    METHOD FB_init : BOOL {FLAGS}
    VAR_INPUT ref : REFERENCE TO INT := 0; provider : I := 0; END_VAR
    saved REF= ref; item := provider; END_METHOD
    METHOD Read : INT
    IF __ISVALIDREF(saved) THEN saved := saved + 1; Read := saved; END_IF;
    IF item <> 0 THEN Read := Read + item.Read(); END_IF;
    IF __ISVALIDREF(post) THEN post := post + 1; Read := Read + post; END_IF;
    IF peer <> 0 THEN Read := Read + peer.Read(); END_IF;
    END_METHOD END_FUNCTION_BLOCK
    """)
    cell = rt.cell("INT", 2)
    provider = rt.instantiate("Provider", inputs={"n": 5})
    fb = rt.instantiate(
        "B", init={"ref": cell, "provider": provider}, inputs={"post": cell, "peer": provider}
    )
    assert fb.call_method("Read").value == 17
    assert cell.value == 4
    cell.value = 10
    provider.set_input("n", 6)
    assert fb.call_method("Read").value == 35
    assert (
        rt.instantiate("B", init={"ref": 0, "provider": 0}, inputs={"post": 0, "peer": 0})
        .call_method("Read")
        .value
        == 0
    )


@pytest.mark.parametrize("field", ["ref", "provider", "post", "peer"])
@pytest.mark.parametrize("bad", ["foreign", "wrong", "none", "bool"])
def test_bad_reference_and_interface_mappings_do_not_execute_st(field, bad):
    source = f"""
    VAR_GLOBAL runs : INT; END_VAR
    INTERFACE I METHOD Read : INT END_METHOD END_INTERFACE
    FUNCTION_BLOCK Provider IMPLEMENTS I METHOD Read : INT Read := 1; END_METHOD END_FUNCTION_BLOCK
    FUNCTION_BLOCK Other END_FUNCTION_BLOCK
    FUNCTION_BLOCK B VAR_INPUT post : REFERENCE TO INT; peer : I; END_VAR
    METHOD FB_init : BOOL {FLAGS} VAR_INPUT ref : REFERENCE TO INT := 0; provider : I := 0; END_VAR
    runs := runs + 1; END_METHOD END_FUNCTION_BLOCK
    """
    rt = Runtime.from_source(source)
    foreign = Runtime.from_source(source)
    reference = field in {"ref", "post"}
    if bad == "foreign":
        value = foreign.cell("INT", 1) if reference else foreign.instantiate("Provider")
    elif bad == "wrong":
        value = rt.cell("DINT", 1) if reference else rt.instantiate("Other")
    else:
        value = None if bad == "none" else False
    kwargs = {"init" if field in {"ref", "provider"} else "inputs": {field: value}}
    with pytest.raises(ArgumentError):
        rt.instantiate("B", **kwargs)
    assert rt.global_cell("GVL", "runs").value == 0
    rt.instantiate("B")
    assert rt.global_cell("GVL", "runs").value == 1


def test_references_and_interfaces_escaping_transient_initialization_expire():
    source = f"""
    INTERFACE I METHOD Read : INT END_METHOD END_INTERFACE
    VAR_GLOBAL saved : REFERENCE TO INT; peer : I; END_VAR
    FUNCTION_BLOCK Provider IMPLEMENTS I
    METHOD Read : INT Read := 3; END_METHOD END_FUNCTION_BLOCK
    FUNCTION_BLOCK B VAR n : INT := 3; child : Provider; END_VAR
    METHOD FB_init : BOOL {FLAGS} saved REF= n; peer := child; END_METHOD
    END_FUNCTION_BLOCK
    FUNCTION Build : INT VAR b : B; END_VAR Build := 1; END_FUNCTION
    FUNCTION ReadReference : INT ReadReference := saved; END_FUNCTION
    FUNCTION ReadInterface : INT ReadInterface := peer.Read(); END_FUNCTION
    """
    for read in ("ReadReference", "ReadInterface"):
        rt = Runtime.from_source(source)
        assert rt.call("Build").value == 1
        with pytest.raises(ExecutionError, match="Expired"):
            rt.call(read)


def test_hooks_distinct_names_keep_base_declaration_order_and_nested_first():
    rt = Runtime.from_source(f"""
    VAR_GLOBAL trace : DINT; END_VAR
    FUNCTION_BLOCK Leaf METHOD FB_init : BOOL {FLAGS} trace := trace * 10 + 1;
    END_METHOD END_FUNCTION_BLOCK
    {{attribute 'call_after_init'}} FUNCTION_BLOCK A VAR child : Leaf; END_VAR
    METHOD FB_init : BOOL {FLAGS} trace := trace * 10 + 2; END_METHOD
    {{attribute 'call_after_init'}} METHOD First trace := trace * 10 + 4; END_METHOD
    {{attribute 'call_after_init'}} METHOD Second trace := trace * 10 + 5; END_METHOD
    END_FUNCTION_BLOCK
    {{attribute 'call_after_init'}} FUNCTION_BLOCK B EXTENDS A
    METHOD FB_init : BOOL {FLAGS} trace := trace * 10 + 3; END_METHOD
    {{attribute 'call_after_init'}} METHOD Last trace := trace * 10 + 6; END_METHOD
    END_FUNCTION_BLOCK
    """)
    rt.instantiate("B")
    assert rt.global_cell("GVL", "trace").value == 123456


def test_python_mapping_insertion_order_runs_setters_after_constructor():
    rt = Runtime.from_source(f"""
    FUNCTION_BLOCK B VAR_OUTPUT trace : INT; END_VAR
    METHOD FB_init : BOOL {FLAGS} trace := 1; END_METHOD
    PROPERTY First : INT SET trace := trace * 10 + First; END_SET END_PROPERTY
    PROPERTY Second : INT SET trace := trace * 10 + Second; END_SET END_PROPERTY END_FUNCTION_BLOCK
    """)
    assert rt.instantiate("B", inputs={"Second": 3, "First": 2}).output("trace") == 132


def test_shared_array_arguments_initialize_each_element_and_owner_after_children():
    rt = Runtime.from_source(f"""
    VAR_GLOBAL trace : INT; END_VAR
    FUNCTION_BLOCK Leaf VAR_OUTPUT id : INT; END_VAR
    METHOD FB_init : BOOL {FLAGS} VAR_INPUT n : INT; END_VAR
    id := n; trace := trace * 10 + n; END_METHOD END_FUNCTION_BLOCK
    FUNCTION_BLOCK Owner VAR items : ARRAY[1..2] OF Leaf(2); END_VAR
    METHOD FB_init : BOOL {FLAGS} trace := trace * 10 + 3; END_METHOD END_FUNCTION_BLOCK
    """)
    owner = rt.instantiate("Owner")
    assert rt.global_cell("GVL", "trace").value == 223
    assert owner.fb("items", 1).output("id") == 2
    assert owner.fb("items", 2).output("id") == 2


def test_transient_initializers_and_function_body_share_step_budget():
    rt = Runtime.from_source(
        f"""
    VAR_GLOBAL count : INT; END_VAR
    FUNCTION_BLOCK B METHOD FB_init : BOOL {FLAGS} count := count + 1; END_METHOD END_FUNCTION_BLOCK
    FUNCTION F : INT VAR a, b : B; END_VAR F := count; END_FUNCTION
    """,
        max_steps=2,
    )
    with pytest.raises(ExecutionError, match="step budget"):
        rt.call("F")
    assert rt.global_cell("GVL", "count").value == 2


def test_init_body_dispatch_remains_virtual_and_base_parameter_defaults_are_lexical():
    rt = Runtime.from_source(f"""
    VAR_GLOBAL CONSTANT value : INT := 2; END_VAR
    FUNCTION_BLOCK A VAR_OUTPUT seen : INT; END_VAR
    METHOD FB_init : BOOL {FLAGS} VAR_INPUT n : INT := value; END_VAR
    seen := n + Read(); END_METHOD METHOD Read : INT Read := 1; END_METHOD END_FUNCTION_BLOCK
    FUNCTION_BLOCK B EXTENDS A VAR CONSTANT value : INT := 99; END_VAR
    METHOD Read : INT Read := 3; END_METHOD END_FUNCTION_BLOCK
    """)
    assert rt.instantiate("B").output("seen") == 5


def test_transient_constructor_can_capture_bound_reference_input():
    rt = Runtime.from_source(f"""
    FUNCTION_BLOCK B VAR_OUTPUT seen : INT; END_VAR
    METHOD FB_init : BOOL {FLAGS} VAR_INPUT ref : REFERENCE TO INT; END_VAR
    seen := ref; ref := ref + 1; END_METHOD END_FUNCTION_BLOCK
    FUNCTION F : INT VAR_INPUT ref : REFERENCE TO INT; END_VAR VAR b : B(ref); END_VAR
    F := b.seen; END_FUNCTION
    """)
    cell = rt.cell("INT", 4)
    assert rt.call("F", ref=cell).value == 4
    assert cell.value == 5


def test_var_inst_constructor_can_reference_same_method_persistent_bank():
    rt = Runtime.from_source(f"""
    FUNCTION_BLOCK Leaf VAR_OUTPUT seen : INT; END_VAR
    METHOD FB_init : BOOL {FLAGS} VAR_INPUT ref : REFERENCE TO INT; END_VAR
    seen := ref; ref := ref + 1; END_METHOD END_FUNCTION_BLOCK
    FUNCTION_BLOCK Owner
    METHOD Read : INT VAR n : INT := 99; END_VAR
    VAR_INST data : INT := 4; saved : REFERENCE TO INT := data; child : Leaf(saved); END_VAR
    Read := child.seen + data; END_METHOD END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("Owner")
    assert fb.call_method("Read").value == 9
    assert fb.call_method("Read").value == 9


def test_all_temporary_child_references_are_prepared_before_first_constructor():
    rt = Runtime.from_source(f"""
    FUNCTION_BLOCK Provider VAR n : INT := 9; END_VAR
    VAR_INPUT ref : REFERENCE TO INT := n; END_VAR END_FUNCTION_BLOCK
    FUNCTION_BLOCK Consumer VAR_OUTPUT seen : INT; END_VAR
    METHOD FB_init : BOOL {FLAGS} VAR_INPUT ref : REFERENCE TO INT; END_VAR
    seen := ref; END_METHOD END_FUNCTION_BLOCK
    FUNCTION_BLOCK Owner VAR_OUTPUT seen : INT; END_VAR
    VAR_TEMP first : Consumer(other.ref); other : Provider; END_VAR
    seen := first.seen; END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("Owner")
    fb.call()
    assert fb.output("seen") == 9


@pytest.mark.parametrize("accessor", ["GET", "SET"])
@pytest.mark.parametrize("phase", ["init", "post"])
def test_property_header_fb_initialization_ignores_accessor_value_shadow(accessor, phase):
    declaration = "Leaf(seed := n)" if phase == "init" else "Leaf := (value := n)"
    rt = Runtime.from_source(f"""
    VAR_GLOBAL n : INT := 2; END_VAR
    {{attribute 'call_after_init'}} FUNCTION_BLOCK Leaf
    VAR_INPUT value : INT; END_VAR VAR_OUTPUT seen : INT; END_VAR
    METHOD FB_init : BOOL {FLAGS} VAR_INPUT seed : INT := 0; END_VAR
    value := seed; END_METHOD
    {{attribute 'call_after_init'}} METHOD Hook seen := value; END_METHOD END_FUNCTION_BLOCK
    FUNCTION_BLOCK B VAR_OUTPUT seen : INT; END_VAR
    PROPERTY Value : INT VAR child : {declaration}; END_VAR
    GET VAR n : INT := 9; END_VAR Value := child.seen; END_GET
    SET VAR n : INT := 9; END_VAR seen := child.seen; END_SET
    END_PROPERTY END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("B")
    if accessor == "GET":
        assert fb.get_property("Value") == 2
    else:
        fb.set_property("Value", 7)
        assert fb.output("seen") == 2


@pytest.mark.parametrize("accessor", ["GET", "SET"])
@pytest.mark.parametrize("phase", ["init", "post"])
def test_property_header_fb_initialization_preserves_reference_identity(accessor, phase):
    declaration = "Leaf(seed := n)" if phase == "init" else "Leaf := (ref := n)"
    rt = Runtime.from_source(f"""
    VAR_GLOBAL n : INT := 2; END_VAR
    {{attribute 'call_after_init'}} FUNCTION_BLOCK Leaf
    VAR_INPUT ref : REFERENCE TO INT := 0; END_VAR VAR_OUTPUT seen : INT; END_VAR
    METHOD FB_init : BOOL {FLAGS} VAR_INPUT seed : REFERENCE TO INT := 0; END_VAR
    ref REF= seed; END_METHOD
    {{attribute 'call_after_init'}} METHOD Hook ref := ref + 1; seen := ref; END_METHOD
    END_FUNCTION_BLOCK
    FUNCTION_BLOCK B VAR_OUTPUT seen : INT; END_VAR
    PROPERTY Value : INT VAR child : {declaration}; END_VAR
    GET VAR n : INT := 9; END_VAR Value := child.seen; END_GET
    SET VAR n : INT := 9; END_VAR seen := child.seen; END_SET
    END_PROPERTY END_FUNCTION_BLOCK
    """)
    fb = rt.instantiate("B")
    if accessor == "GET":
        assert fb.get_property("Value") == 3
    else:
        fb.set_property("Value", 7)
        assert fb.output("seen") == 3
    assert rt.global_cell("GVL", "n").value == 3


def test_accessor_local_fb_initializer_keeps_accessor_locals_visible():
    rt = Runtime.from_source(f"""
    VAR_GLOBAL n : INT := 2; END_VAR
    FUNCTION_BLOCK Leaf VAR_OUTPUT seen : INT; END_VAR
    METHOD FB_init : BOOL {FLAGS} VAR_INPUT n : INT; END_VAR seen := n; END_METHOD
    END_FUNCTION_BLOCK
    FUNCTION_BLOCK B PROPERTY Value : INT
    GET VAR n : INT := 9; child : Leaf(n); END_VAR Value := child.seen; END_GET
    END_PROPERTY END_FUNCTION_BLOCK
    """)
    assert rt.instantiate("B").get_property("Value") == 9
