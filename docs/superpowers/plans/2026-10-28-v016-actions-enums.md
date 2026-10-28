# v0.16 Actions and Enum Attributes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute native TwinCAT ST actions and attributed enums with inherited FB behavior and a tested conveyor example.

**Architecture:** Preserve action identity in AST and registry, execute against owner storage with bounded activation reuse. Preserve enum attributes through type resolution and convert only validated constant assignments to enum values.

**Tech Stack:** Python >=3.11, standard library runtime, pytest, Ruff, setuptools.

**Spec:** `docs/superpowers/specs/2026-10-28-v016-actions-enums-design.md`

## Global Constraints

- Python >=3.11, no runtime dependencies.
- Preserve checked-subset validation, source locations, case-insensitive names, instruction/depth limits and v0.15 initialization.
- No SFC, pointers, restart/online change or blanket ignoring of pragmas.
- Native-format examples do not establish execution on TwinCAT.
- User explicitly authorized implementation; reuse current isolated worktree on codex/v016-actions.
- Sequential implementation tasks avoid shared-file conflicts; independent design/review investigation may run in parallel.

## Review Focus

- Action calls from methods must resolve owner variables, not shadowing method locals; test in Task 1.
- Inherited actions called from base bodies must dispatch correctly while SUPER and VAR_TEMP remain lexical; test in Task 1.
- Invalid external action bindings must leave owner inputs and initialization untouched; test in Task 1.
- Enum attributes and constant conversion must survive arrays/STRUCT/defaults/FB_init/post assignments and property setters; test in Task 2.
- Source import must not smuggle declarations through action bodies or lose action/error section locations; test in Task 1.

### Task 1: ST actions from source to execution

**Files:** Modify `tc_emulator/syntax.py`, `parser.py`, `loader.py`, `validation.py`, `execution.py`, `runtime.py`, and `initialization.py` only as needed. Focused `tc_emulator/actions.py` is allowed. Create `tests/test_parser_actions.py`, `test_loader_actions.py`, `test_validation_actions.py`, `test_runtime_actions.py`.

**Interfaces:** Append `Pou.actions: tuple[Pou, ...] = ()`; each child is ACTION with name OWNER.ACTION and owner OWNER, empty variables and no return. Expose `FBHandle.call_action(name, /, **inputs) -> None` and `Runtime.call_action(program_name, action_name, /, **inputs) -> None`. Registry action lookup and execution helpers may be chosen by implementer; record their exact signatures for later tasks.

- [ ] Write failing parser/import tests for owner actions, interleaved FB members, malformed scopes, XML action locations and body injection; run `.venv/bin/python -m pytest tests/test_parser_actions.py tests/test_loader_actions.py -q` and confirm feature failures.
- [ ] Implement action AST, parsing and native import without changing other syntax; rerun those tests.
- [ ] Write failing validation/execution tests: local/THIS/instance/array/PROGRAM/SUPER calls; owner input/output/inout binding; base virtual dispatch; inherited name collisions; standalone and shared temporary activation; method-local shadow exclusion; RETURN; mixed recursive cycles; step/depth errors; API argument atomicity; interaction with FB_init. Use hand-derived counts (base increment 1, derived addition 10 yields 11; two independent owners retain distinct counts).
- [ ] Implement action validation/dispatch and APIs preserving existing call semantics and source-aware stacks. Run focused tests until passing.
- [ ] Run `.venv/bin/python -m pytest -q`, `.venv/bin/python -m ruff check .`, format changed files and `git diff --check`; self-review and commit only Task 1 files. Record RED/GREEN commands and exact results in task report.

### Task 2: Enum pragmas and validation

**Files:** Modify `tc_emulator/syntax.py`, `parser.py`, `loader.py`, `types.py`, `validation.py`, `execution.py` and `initialization.py` as required; focused enum helper module allowed. Create `tests/test_enum_attributes.py`, `tests/test_loader_enum_attributes.py`; update existing enum tests only where newly supported syntax changes intentional behavior.

**Interfaces:** Append strict/qualified_only False flags to EnumDecl and EnumType (or TypeDecl where appropriate, documenting the choice). Consume Task 1 action calls and runtime APIs; preserve Python EnumValue API and exact IN_OUT/output binding requirements.

- [ ] Write failing tests for both pragma orders and native TcDUT locations, duplicate/valued/misplaced/unknown pragmas and non-enum targets. Run focused pytest and confirm expected parse failures.
- [ ] Preserve flags through parsing/loading/resolution; implement qualified-only name lookup with unqualified unique labels and variable shadowing. Add ambiguity and qualified alias tests.
- [ ] Write RED tests for strict arithmetic/cross-enum/mutable-integer rejection and matching constant assignment: enum values Stop=0, Run=2 accept literal 2 and constant 1+1, reject 3 and mutable INT=2. Cover locals, GVL, type defaults, array/STRUCT, function/method/action value inputs, property setters, FB_init and post-init assignment; exact-type IN_OUT remains rejected for INT cells.
- [ ] Implement compile-time checked conversion without allowing arbitrary Python/runtime integers or changing unmarked enum nominal arithmetic. Run focused tests to GREEN.
- [ ] Full pytest, Ruff, formatting and diff checks; self-review and commit Task 2 files. Report exact interfaces and verification.

### Task 3: Three-conveyor example and release documentation

**Files:** Create `examples/conveyor_actions/` native TcPOU/TcDUT/TcGVL sources and `examples/test_conveyor_actions.py`; modify `README.md`, `pyproject.toml`, package manifest only if required.

**Interfaces:** Use Action syntax/import/APIs and enum pragmas from Tasks 1/2. Existing runtime.scan, advance_time, program_cell/global_cell and FB_init remain available.

- [ ] Write behavioral example tests before its ST fixture: three independent conveyors enter Starting at t=0 and Running at their delays 100/250/500 ms; blocked-sensor timeout leads to Fault; clear obstruction and reset then restart; init count remains one.
- [ ] Implement base/derived actions including SUPER, PROGRAM action sequence and strict qualified state enum in native files, using shared GVL inputs and separate timers. Run example tests to GREEN; document source provenance honestly (native format, no TwinCAT run).
- [ ] Update README supported range, source/API examples and v0.16 limits; version 0.16.0. Run example and full pytest, Ruff/format/diff checks and commit.

## Final verification

- [ ] Review whole branch from 4ca51de with graph, source, tests and OCR delegate; address confirmed defects with regression tests.
- [ ] Full pytest; raw Ruff via local reviewdog, format check, git diff --check.
- [ ] Build wheel and sdist, verify packaged files and run tests/examples against an isolated installed wheel on Python 3.11.
- [ ] Record actual results here; leave committed feature branch and report limitations. No publication/merge requested.
