# v0.17 Interface Collections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Support inherited interfaces and fixed reference arrays, demonstrated by a manager controlling three heterogeneous conveyors before and after rebinding.

**Architecture:** Keep direct interface declarations and prototype owners immutable; add ancestry and effective contract indexes to Registry. Add dedicated interface-array descriptors and storage containing existing InterfaceSlot objects, then reuse indexed lvalue resolution and scalar dispatch.

**Tech Stack:** Python >=3.11, standard library runtime, pytest, Ruff, setuptools.

**Spec:** `docs/superpowers/specs/2026-10-28-v017-interface-collections-design.md`

## Global Constraints

- Python >=3.11, no runtime dependencies.
- Preserve checked-subset validation, case-insensitive names, source locations, static recursion checks, instruction/depth limits, fault latching and v0.15 initialization order.
- Preserve nominal types, reference identity, transient ownership lifetimes and Python argument prevalidation before mutation.
- No pointers, SFC, restart/online change, array covariance or implicit downcasts.
- Native-format fixtures do not establish execution on TwinCAT.
- Array rank remains 1–8, inclusive DINT bounds, at most 1000000 elements; expanded owned storage remains capped at 1000000 scalar leaves and 10000 FB instances.
- Baseline `9689c98`; branch `codex/v017-interface-collections`; reuse the current isolated worktree. Execution is already authorized.
- Tasks execute sequentially because they share validation/execution files. Parent performs builder check, task review gates and final branch review. Do not ask again for execution permission.

## Review Focus

- TcIO reconstruction can silently lose EXTENDS and inherited declarations' source scope: Task 1 tests reversed file order, original source locations and resolved defaults.
- A base-typed reference can accidentally expose derived/sibling members or bypass conservative recursion validation: Task 1 tests static visibility, downcast rejection and inherited method/property recursion.
- Indexed receiver evaluation can repeat or drift after argument/RHS mutation: Task 2 tests exact evaluation counts, captured targets and fault-before-side-effect ordering.
- Array storage can accidentally own target lifetimes or evade expanded leaf limits: Task 2 tests escape, clearing, nested ownership counts and independent slot identity.
- Rebinding or initialization can reset target state, run hooks twice or mutate before a bad Python argument is rejected: Tasks 2/3 test pre-scan binding, init counters, retained state and foreign handles.

## File ownership and seams

Task 1 owns `syntax.py`, `parser.py`, `loader.py`, `validation.py` and narrowly required `initialization.py`/`runtime.py` changes plus inheritance tests. Task 2 subsequently owns `types.py`, `memory.py`, `validation.py`, `execution.py`, `runtime.py`, `initialization.py` and focused collection tests. Task 3 owns new example files, README and version metadata. Avoid unrelated refactoring.

Existing test anchors: `tests/test_parser_interfaces.py`, `test_loader_interfaces.py`, `test_validation_interfaces.py`, `test_runtime_interfaces.py`, `test_validation_inheritance.py`, `test_runtime_array_extensions.py`, `test_validation_array_extensions.py`, `test_runtime_initialization.py`. Read these with their implementations; graph results are scope hints, not authority.

### Task 1: Inherited interface contracts and safe upcasts

**Files:** Modify `tc_emulator/syntax.py` (InterfaceDecl), `parser.py` (interface_declaration), `loader.py` (_xml_interface), `validation.py` (Registry, run ordering, interface_contracts/source/method_target). Modify runtime.py/initialization.py only if required to consume propagated implementers. Create `tests/test_interface_inheritance.py` and `tests/test_loader_interface_inheritance.py`. Update old tests that explicitly reject now-supported EXTENDS syntax.

**Interfaces produced:**

- `InterfaceDecl.extends: tuple[str, ...] = ()` appended after loc.
- `Registry.interface_ancestors: dict[str, frozenset[str]]` contains self plus all transitive bases.
- `Registry.interface_methods: dict[tuple[str, str], str]` maps `(interface_name, member_name)` to the original qualified prototype name in `prototype_pous`.
- `Registry.interface_method_for(owner: str, name: str) -> Pou | None` reads that index and returns a prototype.
- `Registry.interface_assignable(actual: InterfaceType, expected: InterfaceType) -> bool` is true iff expected.name belongs to actual.name's ancestry (including equality).
- `Registry.properties[(interface_name, property_name)]` also contains effective inherited properties, retaining original accessor owners.
- `_Validator.interface_inheritance(self) -> None` validates the complete base graph and populates ancestry/propagated implementers before prototype/body validation. Use bounded/iterative graph traversal or translate recursion overflow to ValidationError.
- `_Validator.same_interface_method_signature(left: Pou, right: Pou) -> bool` and `same_interface_property_signature(left: Property, right: Property) -> bool` compare resolved contracts as specified; no covariance. Concrete PUBLIC/accessor checks remain separate.

**Consumers:** Task 2 uses interface_assignable via existing interface_source for element binding and consumes effective method/property lookup. Keep `Registry.interfaces` as resolved direct declarations; do not replace them with cloned inherited prototypes.

- [x] Write parser/import RED tests asserting old InterfaceDecl positional constructors produce `extends == ()`, mixed-case two-base parsing produces `('I_A', 'I_B')`, and native TcIO preserves that tuple with methods/properties and `:Declaration` locations. Reject empty/duplicate/repeated EXTENDS and injected nested declarations. Remove only the corresponding old EXTENDS rejection cases.
- [x] Run `.venv/bin/python -m pytest tests/test_interface_inheritance.py tests/test_loader_interface_inheritance.py -q`; record feature-specific failures before implementation.
- [x] Implement AST/parser/import preservation. `_xml_interface` currently rebuilds `INTERFACE {name}` for member parsing: preserve the parsed header's extends in the final InterfaceDecl without accepting extra declarations in headers. Run parser/import tests to GREEN.
- [x] Write contract/upcast RED tests. A base method `Add(amount: INT := 2): INT` and GET/SET `Value: INT` inherited through a diamond must resolve once; concrete Add multiplies amount by 10. Derived ref assigned to base then Add() must return 20; setting base.Value to 7 and calling derived.Add() must return 27 on the same FB. Passing derived to a base-typed function and FB_init must preserve that target. A derived FB override must be selected dynamically.
- [x] Add negative and boundary tests: unknown/non-interface bases; self/two-node cycles in unused declarations; file/declaration order permutations; identical sibling/local contracts; method/property collision; return/input name/mode/type/default mismatch; property type or accessor-set mismatch; lexical global constants/defaults; missing inherited implementation; protected implementation; base-to-derived and sibling assignment/arguments; base-only visibility. Expected incompatible declarations raise ValidationError, not a later KeyError.
- [x] Add recursion regressions for inherited methods and property accessors where an otherwise unused compatible FB calls back through a base interface; assert ValidationError matching `Recursive call`. Check unrelated FBs are not added as implementers and old nominal interface equality/zero restrictions remain.
- [x] Implement interface graph, effective contracts, implementer propagation and assignment lookup. Resolve direct prototypes first, merge in deterministic base order with exact signatures, then validate all effective contracts. Preserve the original prototype owner for lexical scope/defaults, and pass the receiver's declared interface separately to call_edge so candidate dispatch includes all implementers of that contract. Use interface_method_for in method_target and the existing properties table for accessors, retaining the receiver interface for scalar and indexed methods/GET/SET.
- [x] Run the new tests and existing interface/inheritance/initialization tests to GREEN, then `.venv/bin/python -m pytest -q`. Run Ruff/format/diff checks from the verification recipe below. Self-review exact source and commit only Task 1 files with `feat: support inherited interface contracts`. Record RED/GREEN results and any seam changes for the parent; await task review before Task 2.

### Task 2: Fixed arrays of non-owning interface slots

**Files:** Modify `tc_emulator/types.py`, `memory.py`, `validation.py`, `execution.py`; narrowly adjust runtime.py/initialization.py for rejection/allocation consistency if needed. Create `tests/test_interface_array_types.py`, `tests/test_validation_interface_arrays.py`, `tests/test_runtime_interface_arrays.py`. Update only the obsolete direct-interface-array rejection in `tests/test_validation_interfaces.py`.

**Interfaces consumed:** Task 1 ancestry/effective contract tables and interface_source compatibility. Existing `InterfaceSlot.capture(loc, *, dispatch=False)`, `bind(target, loc)`, `inspect()` and scalar interface argument APIs are unchanged.

**Interfaces produced:**

- Frozen `InterfaceArrayType(bounds: tuple[tuple[int, int], ...], element_type: InterfaceType)` with `.shape`, `.size`, `__str__`; constructor validates bounds/rank through the existing array bounds rules. It belongs to TypeSpec but is never a value type.
- `InterfaceArray(type_name: InterfaceArrayType, items: tuple[InterfaceSlot, ...])`, `_element(indices: tuple[int, ...]) -> InterfaceSlot`, `inspect() -> tuple`; one distinct slot per row-major element.
- `_Validator.interface_array_variable(var: VarDecl) -> VarDecl` checks owned sections, rejects constants/initializers/init argument syntax and returns normalized declaration with default None.
- `Engine._variable` allocates InterfaceArray slots; `Engine.resolve(Index(...))` returns a slot. Frame slot and method_instances unions plus passive snapshot branches include InterfaceArray. There is no new public Python binding/selection API.

- [x] Write descriptor/storage RED tests: bounds `((-1, 0), (2, 3))` give shape `(2, 2)` and size 4; four slots are distinct; element `(-1, 3)` is second. Invalid BOOL/rank/out-of-range indices fail; snapshots are detached, preserve shape and contain `{interface, target, valid}`. Reject value APIs and ArrayType(..., InterfaceType(...)). Run the new test module and record failures.
- [x] Add descriptor and storage classes with existing FBArray indexing/snapshot semantics. Keep InterfaceArrayType outside check_value/default_value/resolve_type value paths, and update all nonvalue exclusion branches consistently. Rerun type/storage tests.
- [x] Write validation RED tests for direct fixed arrays in PROGRAM/FB/GVL/function/method/accessor VAR, FB/PROGRAM VAR_TEMP and method VAR_INST; constant expression bounds and direct multidimensional arrays; inherited interface elements and LOWER_BOUND/UPPER_BOUND. Assert rejection of every unsupported row in the spec's operation table, including fixed/open parameters in all modes and prototype parameters, init argument syntax, ARRAY OF ARRAY, aliases/STRUCT fields/references, whole copy/comparison/return and concrete-field access through an element.
- [x] Implement direct declaration normalization before storage preflight (parallel to FBArrayType in prepare_variable), declarations validation and indexed InterfaceType inference. Add InterfaceArrayType to index/bound checks, count `.size` leaves in expanded ownership, skip value preflight without adding containment edges. Add a nested FB array case exceeding 1000000 leaves by one and assert ValidationError before allocation; add an exact-limit preflight test without allocating a million runtime slots.
- [x] Write execution RED tests with two FB implementations: assign concrete/derived references into elements, copy one element into another, rebind the first, and verify second still dispatches to the original Frame (Add 2 versus Add 20). Test indexed inherited properties, interface inputs, null comparisons both operand orders, clearing and multidimensional nonzero lower bounds. Unbound slots start independently at zero.
- [x] Add receiver-order tests: `devices[Pick()].Add(Switch())` and `devices[Pick()].Value := Switch()` each call Pick exactly once; Switch changes index and binding but the original target receives 7. Null/expired/out-of-bounds receiver faults before Switch increments a GVL counter; counter stays 0. Verify source location/stack, RuntimeFaultedError on next execution and existing budget/depth limits through array dispatch.
- [x] Add lifetime/initialization RED tests: local FB escapes through GVL array and through array-to-scalar copy; read/copy/null-check/dispatch after return raises `Expired`, while a separate no-prior-fault runtime can clear zero. Function/method/accessor locals and VAR_TEMP arrays reset; VAR_INST arrays persist. Reference cycles inspect safely after faults. Manager FB_init receives three scalar interface inputs and binds its array before scan; targets' init counters remain 1 after scans and rebind. Python invalid foreign input is rejected before any Bind side effect.
- [x] Implement allocation/resolution/snapshot integration and reuse scalar InterfaceSlot paths for assignment, capture, comparison and dispatch. Do not traverse interface targets during initialization or lifetime expiry. Ensure runtime bound intrinsics work for InterfaceArray storage. Existing Cell and FB selection APIs must return ArgumentError for interface arrays/elements without faulting a healthy runtime.
- [x] Run new tests plus existing interfaces/arrays/initialization/lifetime suites to GREEN, then full pytest and verification recipe. Self-review and commit only Task 2 files with `feat: add fixed interface reference arrays`. Report observed failures/passes and await task review.

### Task 3: Heterogeneous conveyor manager and release documentation

**Files:** Create `examples/conveyor_collections/I_Command.TcIO`, `I_Status.TcIO`, `I_Conveyor.TcIO`, `I_Reversible.TcIO`, `FB_ConveyorBase.TcPOU`, `FB_StandardConveyor.TcPOU`, `FB_ReversibleConveyor.TcPOU`, `FB_JamConveyor.TcPOU`, `FB_Line.TcPOU`, `MAIN_Line.TcPOU`, `GVL_Line.TcGVL`; create `examples/test_conveyor_collections.py`; modify `README.md`, `pyproject.toml`. Add enum/config TcDUT only if used and keep it local to this fixture.

**Interfaces consumed:** Task 1 EXTENDS, scalar upcasts and native loading; Task 2 fixed arrays, bounds, binding and indexed dispatch. Existing Runtime.from_files, scan, advance_time, program_fb/global_cell, FBHandle.call_method/get_property/set_property/inspect and FB_init remain the external API.

**Interfaces produced:** Example FB_Line owns `devices: ARRAY[1..3] OF I_Conveyor`. `FB_init: BOOL` has system BOOL inputs plus `first, second, third: I_Conveyor`; `Bind` has `index: DINT, target: I_Conveyor`; `Start`, `Stop`, `Reset` have no inputs. All are PUBLIC. MAIN's `line` exposes the manager through `rt.program_fb('MAIN_Line', 'line')`.

- [x] Write fixture behavioral RED tests first, loading reversed sorted native paths. Assert devices metadata targets are the three distinct concrete FB names before scan, every init counter is 1 and no timer is running. Start then scan at t=0: `(False, False, False)`; at t=100/250/500: `(True, False, False)`, `(True, True, False)`, `(True, True, True)`. At t=500 actual speeds approximate `(0.5, -0.75, 0.6)`.
- [x] Write additional tests for independent rising product edges `(1, 2, 1)`; only the third conveyor faults after blocked is held 300 ms, clearing alone does not resume, Reset+Start resumes after its 500 ms delay; Stop affects all bound devices. Record missing-fixture/feature RED results with `.venv/bin/python -m pytest examples/test_conveyor_collections.py -q`.
- [x] Implement native files and contracts exactly as specified. MAIN declares concrete instances before the manager and supplies scalar interface constructor inputs; FB_Line binds before scan and loops only through I_Conveyor. Configure Reverse TRUE on the second instance; no concrete-type conditionals and no first-scan initialization flag. Shared base code is allowed, but behavior differences must be observable.
- [x] Add rebind tests: create a replacement, establish nonzero product/state values, Bind element 2, verify values/init count survive, old target no longer receives Cycle and other devices remain independent. Bind zero publishes `(FALSE, 0.0, 0, 'Not bound')` for the slot. Foreign-runtime handle raises ArgumentError without changing binding/state or faulting the runtime. Run all example tests to GREEN.
- [x] Update README supported syntax/API examples and explicit profile limits from the spec. Explain native format versus native execution honestly. Set version `0.17.0`, retain Python floor and empty dependencies. Execute every added README Python block against the fixture.
- [x] Run full pytest and verification recipe, self-review and commit Task 3 files with `docs: demonstrate heterogeneous conveyor collections`. Report exact verification and await task review.

## Verification recipe and final branch gate

Use graph tools with explicit repository root before source review. For task and
branch review use detect_changes/get_review_context/get_affected_flows and
tests_for, then read actual source/tests. OCR requests use delegate preview/rule,
account for every changed file, and report findings in Polish.

- [x] Run `.venv/bin/python -m pytest -q`; record count and interpreter version, do not assume the baseline count proves new behavior.
- [x] Run `.venv/bin/python -m ruff check .` and `.venv/bin/python -m ruff format --check .`; format touched files if needed and rerun affected checks.
- [x] Run raw Ruff via reviewdog from repository root using Bash pipefail:
  `set -o pipefail; rtk bypass .venv/bin/python -m ruff check . --output-format=concise 2>&1 | /home/rtm/.local/bin/reviewdog -efm='%f:%l:%c: %m' -reporter=local -filter-mode=nofilter -fail-level=warning`.
  Preserve linter failures and inspect raw output separately if parser results are empty or suspect.
- [x] Run `git diff --check` and review the entire branch against verified `9689c98`; fix confirmed issues with meaningful regression tests and scoped re-review.
- [x] Build wheel and sdist with `.venv/bin/python -m build`; verify metadata version 0.17.0, Python >=3.11, no runtime dependencies and expected tracked runtime/example/docs files in artifacts. Do not silently exclude the new native fixtures from sdist.
- [x] Create a fresh Python 3.11 environment outside the checkout, install the built wheel and pytest, copy tests/examples there without project pytest path configuration, and verify `tc_emulator.__file__` resolves inside that environment's site-packages. Run `env/bin/python -I -m pytest tests examples -q -c /dev/null --rootdir=. --confcutdir=. -p no:cacheprovider`; run new README blocks there too. Record actual command paths and results.
- [x] Record final commit SHAs, model sizing, review coverage and outcomes here. Leave the feature branch committed; publication/merge is outside this plan unless separately authorized.

## Completion record

Completed 2026-10-28 on `codex/v017-interface-collections`, based on
`9689c98a44a33cf905480e6224c7fa92b1cd312d`. Worktree preserved; no v0.17
remote publication or merge performed.

Implementation commits:

- `adeb8d5`: design and plan.
- `4b1e848`: inherited interface contracts, effective members and safe upcasts.
- `e8959c1`: fixed non-owning interface arrays.
- `5d2177b`: shared private array indexing/snapshot helpers after task review.
- `0ec0382`: native heterogeneous conveyor fixture, README and version 0.17.0.
- `271d6f3`: use static receiver contract for inherited call edges while retaining
  lexical prototype ownership; method/GET/SET scalar/indexed regression matrix.

Verification at the final implementation commit:

- Python 3.13.17 source suite: **3459 passed in 5.27s**; focused final-fix
  coverage: **482 passed**. Baseline: 3263 passed. TDD evidence was recorded for
  all tasks; final fix first reproduced 12 false-recursion failures, then all
  36 delegation/real-cycle cases passed.
- Raw Ruff and local reviewdog (`NO_COLOR=1`, Bash pipefail, `-f=flake8`):
  successful with no findings. Formatting: **145 files already formatted**.
  Whitespace/diff checks passed. An initial unsupported Ruff color flag was a
  command invocation failure; corrected invocation passed.
- Wheel and sdist built successfully. All **16 runtime modules** in wheel and
  **208 tracked files** in sdist byte-match source, including native fixtures.
  Metadata: 0.17.0, Python >=3.11, no runtime dependencies.
- Final wheel reinstalled in `/tmp/tc-emulator-v017-verification/env` with
  Python **3.11.17**. Verified import from that environment's `site-packages`.
  Copied tests/examples outside checkout; isolated command
  `env/bin/python -I -m pytest tests examples -q -c /dev/null --rootdir=. --confcutdir=. -p no:cacheprovider`
  produced **3459 passed in 3.70s**. New README Python block passed in both
  source and installed-wheel environments.
- Task reviews approved every changed file. Task 2's duplicate storage logic
  finding was fixed and its scoped re-review approved (114 covering tests).
  Final whole-branch review covered **32/32 files**, including every OCR-excluded
  XML/test/document. Its sole P2 false-recursion finding was fixed in `271d6f3`;
  scoped re-review covered **4/4 files**, marked it addressed and found no new
  issue. No parked or deferred findings remain.

Model sizing: Astra high for design and final architectural review; Sol high
for inheritance, arrays, integration fixes and their reviews; Sol medium for
example/documentation and its task review. Implementations ran sequentially;
read-only preparation and independent verification overlapped where safe.

Decisions recorded during execution:

- Use the installed reviewdog `flake8` parser for raw concise Ruff output.
  A parser mismatch could hide diagnostics; raw output and pipeline exit status
  were checked independently.
- Retain lexical prototype owners but carry static receiver interface separately
  into call-edge analysis. Conflating them rejected valid programs and made
  equivalent base order observable. Incorrect narrowing could miss cycles;
  existing recursion tests and 18 new real-cycle cases protect this boundary.

The native-format fixture was executed by this emulator; native TwinCAT execution
was not claimed. Fixed arrays retain the documented owned-storage-only profile.
Local `.work/v017-*` logs and distribution artifacts are ignored build outputs.
