# v0.15 FB Initialization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute native-format FB initialization before ordinary scans with Python test control.

**Architecture:** Extend typed frame allocation with bounded initialization. Preserve separate
constructor arguments and post-init assignments in syntax; validate lifecycle contracts and
execute them through existing methods, reference storage and call contexts.

**Tech Stack:** Python >=3.11, standard library runtime, pytest and Ruff for development.

**Spec:** docs/superpowers/specs/2026-10-28-v015-initialization-design.md

## Global Constraints

- Python >=3.11; standard-library-only runtime; Linux without installed TwinCAT.
- Preserve v0.14 checked arithmetic, virtual time, stable aliases, source locations and resource limits.
- Initialize new instances only: no restart, RETAIN/PERSISTENT, online change, FB_exit or FB_reinit.
- Do not claim native TwinCAT parity without differential execution on TwinCAT.
- Unknown attributes and unsupported constructs remain errors, including in unused source.

## Review Focus

- Inherited initialization expressions resolve in the declaring scope, never shadowing child scope (Task 2).
- Transient FB arguments see bound function/method inputs and expire with their activation (Task 2).
- Init methods/hooks cannot evade one execution budget or recursively construct unbounded instances (Task 2).
- Invalid Python init/post-init arguments cause no user-code side effects (Task 2).
- Native XML pragma lines preserve method/FB Declaration and Implementation error locations (Task 1).

### Task 1: Parse and import initialization syntax

**Files:** tc_emulator/syntax.py, parser.py, loader.py; tests/test_parser_initialization.py,
tests/test_loader_initialization.py.

**Interfaces:** Produce the three appended dataclass fields specified by the design.
Post-init values remain VarDecl.initial. Named/positional argument nodes use existing Argument.

- [ ] Add failing parser tests for FB/method call_after_init markers, single/shared arguments,
  per-element array arguments, post-init values and invalid pragma positions/malformed syntax.
- [ ] Run `.venv/bin/python -m pytest tests/test_parser_initialization.py -q` and record expected failures.
- [ ] Implement syntax/parser changes without accepting unknown attributes or changing STRING(n).
- [ ] Add failing native TcPOU tests for marked FB/methods and preserved locations; implement loader support.
- [ ] Run both new test files and existing parser/loader tests; run full suite; commit only owned files.

### Task 2: Validate and execute instance initialization

**Files:** tc_emulator/validation.py, execution.py, runtime.py, memory.py; optional focused
tc_emulator/initialization.py; tests/test_validation_initialization.py, test_runtime_initialization.py.

**Interfaces:** Consume Task 1 fields. Produce `Runtime.instantiate(name, *, init=None, inputs=None)`
and automatic initialization of all persistent/transient owned instances as specified in the design.

- [ ] Write failing end-to-end tests: initial flag values TRUE/FALSE, ignored FALSE return,
  init n=1 then post-input=2 then hook-observed=2, inherited order 1/2/3, single execution across scans.
- [ ] Run focused tests to observe missing lifecycle support before implementation.
- [ ] Validate lifecycle signatures, derived-prefix contracts, markers, declaration argument binding,
  post-input/property assignments, initializer scopes and direct-call prohibitions.
- [ ] Implement initialization scheduling with shared Context and correct persistent/transient lifetimes.
- [ ] Implement Python mapping arguments with full prevalidation before executing user code.
- [ ] Add and run tests for per-element arrays, shared refs/interfaces, transient bound inputs,
  lexical inherited defaults, unknown/duplicate/missing args, foreign Cell/FBHandle, null, bad types,
  init/hook/setter faults, recursive local FB construction and step/depth exhaustion.
- [ ] Run complete suite, Ruff and formatting; commit owned files after review of diff.

### Task 3: Example, documentation and release

**Files:** examples/conveyor_initialization/*.TcPOU/*.TcGVL/*.TcDUT, examples/test_conveyor_initialization.py,
README.md, pyproject.toml, optionally examples/initialization_order.st.

**Interfaces:** Consume initialization declaration syntax and Python API from Tasks 1–2.

- [ ] Add failing behavior tests for three ready instances before scan, unique IDs and init counters,
  shared config, independent delays 100/250/500 ms, configuration mutation and repeat-scan stability.
- [ ] Add native-format base/derived conveyor blocks with FB_init and marked after-init override,
  shared GVL config, PROGRAM and per-element initialization parameters.
- [ ] Run example tests and full suite; document runnable Python usage and precise profile limitations.
- [ ] Bump version to 0.15.0, update feature/exclusion lists and include a native-compatible order fixture.
- [ ] Run raw Ruff through reviewdog, formatter check, build wheel and test installed wheel outside checkout.

### Task 4: Independent review and final verification

**Files:** all v0.15 changes and this plan's verification record.

- [ ] Refresh CRG; inspect changed-file context/affected flows and source; obtain independent final review.
- [ ] Resolve actionable issues with regression tests and scoped re-review.
- [ ] Record final suite/lint/build/wheel evidence and remaining native-TwinCAT verification limitation.
- [ ] Commit completed work on codex/v015-fb-init and leave it available for user review.
