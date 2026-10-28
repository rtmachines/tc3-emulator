# v0.16 Actions and Enum Attributes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

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

- [x] Write failing parser/import tests for owner actions, interleaved FB members, malformed scopes, XML action locations and body injection; run `.venv/bin/python -m pytest tests/test_parser_actions.py tests/test_loader_actions.py -q` and confirm feature failures.
- [x] Implement action AST, parsing and native import without changing other syntax; rerun those tests.
- [x] Write failing validation/execution tests: local/THIS/instance/array/PROGRAM/SUPER calls; owner input/output/inout binding; base virtual dispatch; inherited name collisions; standalone and shared temporary activation; method-local shadow exclusion; RETURN; mixed recursive cycles; step/depth errors; API argument atomicity; interaction with FB_init. Use hand-derived counts (base increment 1, derived addition 10 yields 11; two independent owners retain distinct counts).
- [x] Implement action validation/dispatch and APIs preserving existing call semantics and source-aware stacks. Run focused tests until passing.
- [x] Run `.venv/bin/python -m pytest -q`, `.venv/bin/python -m ruff check .`, format changed files and `git diff --check`; self-review and commit only Task 1 files. Record RED/GREEN commands and exact results in task report.

### Task 2: Enum pragmas and validation

**Files:** Modify `tc_emulator/syntax.py`, `parser.py`, `loader.py`, `types.py`, `validation.py`, `execution.py` and `initialization.py` as required; focused enum helper module allowed. Create `tests/test_enum_attributes.py`, `tests/test_loader_enum_attributes.py`; update existing enum tests only where newly supported syntax changes intentional behavior.

**Interfaces:** Append strict/qualified_only False flags to EnumDecl and EnumType (or TypeDecl where appropriate, documenting the choice). Consume Task 1 action calls and runtime APIs; preserve Python EnumValue API and exact IN_OUT/output binding requirements.

- [x] Write failing tests for both pragma orders and native TcDUT locations, duplicate/valued/misplaced/unknown pragmas and non-enum targets. Run focused pytest and confirm expected parse failures.
- [x] Preserve flags through parsing/loading/resolution; implement qualified-only name lookup with unqualified unique labels and variable shadowing. Add ambiguity and qualified alias tests.
- [x] Write RED tests for strict arithmetic/cross-enum/mutable-integer rejection and matching constant assignment: enum values Stop=0, Run=2 accept literal 2 and constant 1+1, reject 3 and mutable INT=2. Cover locals, GVL, type defaults, array/STRUCT, function/method/action value inputs, property setters, FB_init and post-init assignment; exact-type IN_OUT remains rejected for INT cells.
- [x] Implement compile-time checked conversion without allowing arbitrary Python/runtime integers or changing unmarked enum nominal arithmetic. Run focused tests to GREEN.
- [x] Full pytest, Ruff, formatting and diff checks; self-review and commit Task 2 files. Report exact interfaces and verification.

### Task 3: Three-conveyor example and release documentation

**Files:** Create `examples/conveyor_actions/` native TcPOU/TcDUT/TcGVL sources and `examples/test_conveyor_actions.py`; modify `README.md`, `pyproject.toml`, package manifest only if required.

**Interfaces:** Use Action syntax/import/APIs and enum pragmas from Tasks 1/2. Existing runtime.scan, advance_time, program_cell/global_cell and FB_init remain available.

- [x] Write behavioral example tests before its ST fixture: three independent conveyors enter Starting at t=0 and Running at their delays 100/250/500 ms; blocked-sensor timeout leads to Fault; clear obstruction and reset then restart; init count remains one.
- [x] Implement base/derived actions including SUPER, PROGRAM action sequence and strict qualified state enum in native files, using shared GVL inputs and separate timers. Run example tests to GREEN; document source provenance honestly (native format, no TwinCAT run).
- [x] Update README supported range, source/API examples and v0.16 limits; version 0.16.0. Run example and full pytest, Ruff/format/diff checks and commit.

## Final verification

- [x] Review whole branch from 4ca51de with graph, source, tests and OCR delegate; address confirmed defects with regression tests.
- [x] Full pytest; raw Ruff via local reviewdog, format check, git diff --check.
- [x] Build wheel and sdist, verify packaged files and run tests/examples against an isolated installed wheel on Python 3.11.
- [x] Record actual results here; leave committed feature branch and report limitations. No publication/merge requested.


## Completion and verification record

Implementation completed on `codex/v016-actions`, based on v0.15 commit `4ca51de`.
Feature commits: `b67121b` (actions), `7276956` (enum attributes), `4605292`
(example/docs/version), `acc4554` (qualified owner constant regression fix).

- Final source suite, Python 3.13.17: **3263 passed in 3.59 s**.
- Final installed wheel, Python 3.11.17 outside the checkout: **3263 passed in 3.57 s**.
  Command: `env/bin/python -I -m pytest tests examples -q -c /dev/null --rootdir=. --confcutdir=. -p no:cacheprovider`.
- Both new README Python blocks pass against the installed wheel; module provenance
  was checked against `env/lib/python3.11/site-packages`, and installed runtime
  module bytes match the source tree.
- Ruff and raw Ruff through local reviewdog pass without diagnostics; formatter
  reports **137 files already formatted**; Git diff checks pass.
- Wheel and sdist build successfully. All **16 runtime modules** match the wheel;
  **189 tracked source/documentation/example/test files** match the sdist. Metadata
  declares version **0.16.0**, Python >=3.11 and no runtime dependencies.
- Task reviews approved all three deliverables. Final independent review covered
  **26/26 files** and found one P2: THIS/SUPER-qualified owner constants were rejected
  in ACTION strict-enum conversions. The fix adds lexical ACTION owner support
  while retaining the FUNCTION_BLOCK-only guard. Eleven regression cases were
  added; six reproduced the defect before the fix. The final scoped review covered
  **2/2 files**, marked the finding ADDRESSED and approved the fix. No open or
  deferred findings remain.
- Models were sized to work: GPT-6.1 Sol xhigh for action implementation, high for
  enum implementation, medium for example/docs; scoped review effort matched risk,
  and GPT-6 Astra high performed the final whole-branch review.

Engineering decisions were recorded in the spec: receiver-dependent action I/O
contracts, lexical-owner temporary banks, and first-declaration-only enum pragma
scope. The explicit implementation request authorized completing the design and
plan without another approval round. The later user request also authorizes commit
and push of this feature branch; no merge or release publication is included.

The native-format fixtures were handwritten and executed by tc-emulator. No native
TwinCAT execution or differential comparison was performed. SFC, PLC restart,
RETAIN/PERSISTENT, online change and general pointers remain outside this scope.
