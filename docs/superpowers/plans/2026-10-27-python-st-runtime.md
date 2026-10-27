# Python ST Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Execute the approved ST subset in a standalone Python runtime, with pytest examples.

**Architecture:** Immutable parsed syntax is validated before execution. Typed memory cells and independent FB frames are interpreted by a sequential runtime; loaders preserve source positions.

**Tech Stack:** Python 3.11+, standard library runtime; pytest and Ruff for development.

**Spec:** `docs/superpowers/specs/2026-10-27-python-st-runtime-design.md` (approved 2026-10-27).

## Global Constraints

- No TwinCAT installation or external runtime dependencies; Linux supported.
- BOOL, INT, UINT, DINT, UDINT; checked signed 64-bit intermediates, checked storage ranges.
- Default 100000 steps per top-level call and 128 call frames.
- Validate every POU, including uncalled bodies; reject unsupported language constructs.
- Runtime failure leaves partial state inspectable and prevents subsequent execution.
- No repository exists here: work in the requested directory without Git/worktree/commit steps.

## Review Focus

- Aliased VAR_IN_OUT must share memory immediately, and reject cross-runtime cells (Task 3).
- Invalid syntax/types in unreachable or uncalled code must fail during loading (Task 2).
- Empty loops and nested calls must consume one shared finite budget (Task 3).
- XML metadata must not cause method/action or non-ST code to be silently discarded (Task 1).
- Python bool/int coercion and negative division must not leak into PLC semantics (Tasks 2/3).

## Shared Interfaces

Exact internal contracts are in `.work/progress/interfaces.md`. Task 1 owns syntax/errors/parser/loader;
Task 2 owns types/validation; Task 3 owns runtime/memory/public API. Changes to shared contracts
must be communicated before dependent implementation. Parallel work has disjoint file ownership.

### Task 1: Parser and import

**Files:** `tc_emulator/{syntax,errors,parser,loader}.py`, `tests/test_parser.py`, `tests/test_loader.py`.
**Interfaces:** `parse(text, source='<string>') -> Program`; `load_files(paths) -> Program`.

- [x] Write tests for precedence, case-insensitive names, nested comments, all control-flow syntax,
  positional/named calls, `=>`, declaration groups and unexpected tokens.
- [x] Observe failure before implementation: `.venv/bin/python -m pytest tests/test_parser.py tests/test_loader.py -q`.
- [x] Implement frozen syntax nodes, source-aware errors, parser and strict TcPOU importer.
- [x] Verify multiple POUs, malformed XML, method/action/non-ST rejection, and correct section positions.

### Task 2: Types and static validation

**Files:** `tc_emulator/{types,validation}.py`, `tests/test_validation.py`, `tests/test_types.py`.
**Interfaces:** `validate(program) -> dict[str, Pou]` with canonical names; storage helpers in contract.

- [x] Write tests for duplicate names, unknown types/references, incompatible operands/calls,
  missing IN_OUT, non-writable output targets, private fields, recursion and FB containment cycles.
- [x] Observe RED with `.venv/bin/python -m pytest tests/test_types.py tests/test_validation.py -q`.
- [x] Implement checked scalar type helpers and whole-program static validation.
- [x] Verify acceptance across forward references and rejection in uncalled/dead code.

### Task 3: Execution and public test API

**Files:** `tc_emulator/{runtime,memory,__init__}.py`, `tests/test_runtime.py`, `pyproject.toml`.
**Interfaces:** Runtime.from_source/from_files; Runtime.call/instantiate/cell; FBHandle.call/set_input/output/inspect.

- [x] Write end-to-end ST tests, first `F_Add` returning 5 and independent counters returning 2 and 0.
- [x] Observe RED, then implement memory, evaluation, statement execution and API.
- [x] Add RED→GREEN tests for fresh function locals, FB retained inputs and temporary state,
  nested FBs, all statements/operators, negative integer division, output bindings and reference aliasing.
- [x] Add RED→GREEN tests for invalid Python inputs, cross-runtime cells, empty infinite loops,
  call-depth/shared budget, partial-state faults and argument validation before mutation.
- [x] Run `.venv/bin/python -m pytest -q` after integration.

### Task 4: Examples, packaging and independent review

**Files:** `README.md`, `examples/{functions.st,FB_Counter.TcPOU,test_examples.py}`, `.gitignore`.

- [x] Add runnable pytest examples and Polish usage documentation, including exact limitations.
- [x] Verify editable installation and wheel installation with no runtime dependencies.
- [x] Build code graph and use it to focus an independent review, then read exact source and tests.
- [x] Resolve important findings with reproducing tests; run the full suite and Ruff through reviewdog.
- [x] Record actual results and mark plan tasks complete.
