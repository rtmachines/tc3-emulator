# v0.13 FB inheritance implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute inherited TwinCAT ST function blocks with SUPER, protected members and existing interface/Python APIs.

**Architecture:** Preserve declaration identities and lexical scopes; resolve effective members separately from their original definitions. Store one concrete receiver with inherited state; invocation views select lexical bodies and static SUPER targets while retaining dynamic dispatch for ordinary calls.

**Tech Stack:** Python >=3.11, standard library runtime, pytest and Ruff/reviewdog development tools.

**Spec:** docs/superpowers/specs/2026-10-27-v013-inheritance-design.md

## Global Constraints

- Runtime remains standalone, Python >=3.11, standard library only, usable on Linux, with deterministic virtual time. Preserve v0.12 behavior.
- No ABSTRACT, FINAL, INTERNAL, interface EXTENDS, pointer/reference operators, lifecycle hooks or hardware access.
- Keep original declaration owners and one concrete receiver identity. Inspection is passive; existing checked limits, lifetimes and fault behavior apply.
- Preserve earlier examples and document any narrower supported profile explicitly.
- Work in the attached v013-inheritance worktree, branch feat/v013-inheritance; no external publication is part of this task.

## Review Focus

- Base constant/default resolution must not capture derived or method-local constants: add a conflicting-name default test in Task 2.
- Calling an inherited method through a grandchild must select SUPER from its lexical owner: add three-level runtime test in Task 2.
- Base code must retain private access while dispatching public/protected overrides: add base private helper plus overridden hook test in Task 2.
- VAR_INST on base and override must remain independent but shared by all paths into the same declaring implementation: add alternating SUPER/direct calls in Task 2.
- Interface references into inherited temporary nested FBs must expire, while persistent base state survives scans: add lifetime regression in Task 2.

## Task 1: Syntax and native import

**Files:** modify tc_emulator/syntax.py, parser.py and loader.py as needed; create tests/test_parser_inheritance.py and tests/test_loader_inheritance.py.

**Interfaces:** append Pou.extends: str | None = None; add frozen Super(loc: Location) to LValue and Expr. SUPER^() is Call(Super(...), ...); SUPER^.member is Member(Super(...), name, ...). Existing access strings gain PROTECTED. Members retain original owner/qualified names.

- [ ] Add parsing tests for EXTENDS with IMPLEMENTS, forward base names, SUPER body/method/property/field syntax and PROTECTED methods/properties/accessors. Assert AST meaning and locations, not parser internals.
- [ ] Add native TcPOU load tests using these constructs, including source locations and rejected non-FB/multiple bases, malformed modifiers, unsupported interface inheritance and declaration injection.
- [ ] Run .venv/bin/python -m pytest tests/test_parser_inheritance.py tests/test_loader_inheritance.py -q; record expected missing-feature failures.
- [ ] Implement syntax/parser/import support and preserve existing AST constructors and strict XML boundaries.
- [ ] Run new and existing parser/loader tests, full suite, Ruff/format on changed files; record results and commit only Task 1 files.

## Task 2: Inheritance resolution, execution and Python integration

**Files:** modify tc_emulator/validation.py, memory.py, execution.py, runtime.py; add a focused inheritance.py helper if it keeps resolution manageable. Create tests/test_validation_inheritance.py and tests/test_runtime_inheritance.py; extend existing tests only for newly accepted syntax.

**Interfaces:** consumes Task 1 AST. Produces effective inherited contracts and runtime dispatch behind existing Runtime/FBHandle public APIs; exact internal Registry/frame metadata is owned by this task and must be documented in its report. Declaring Pou.name/owner and receiver identity remain stable.

- [ ] Write and run failing tests for forward/multilevel bases, unknown/non-FB/builtin/cyclic bases, inherited variables/defaults/member collisions and access checks. Decide and document VAR_TEMP shadow profile before implementation.
- [ ] Resolve inheritance and effective contracts without rebinding lexical constants/types. Reject incompatible method/default/property/accessor overrides and private overrides. Inherit implemented interfaces and register concrete implementers.
- [ ] Write and run failing tests for derived body vs explicit SUPER^(), base/THIS/interface virtual dispatch, lexical grandparent SUPER, inherited GET/SET and Python public/private/protected access.
- [ ] Implement invocation/storage metadata and dispatch, with one receiver, inherited initialized storage, static SUPER selection, independent VAR_INST banks and transient VAR_TEMP activations. Preserve checked context, input/output/IN_OUT and Python prevalidation.
- [ ] Add the five Review Focus tests plus independent instances/FB arrays, inherited timer progression, inspection, memory/containment/recursion limits, fault propagation, invalid syntax/AST and Python wrong-runtime interface input tests. Watch each missing behavior fail before fixing it.
- [ ] Run .venv/bin/python -m pytest -q, Ruff through local reviewdog and format; self-review against spec and commit Task 2 files. Report narrower profiles and exact test evidence.

## Task 3: Conveyor example, documentation and release

**Files:** create examples/conveyor_inheritance/*.TcPOU, I_Motor.TcIO and GVL_Line.TcGVL, examples/test_conveyor_inheritance.py; modify README.md and pyproject.toml version 0.13.0. MANIFEST.in only if inclusion needs updating.

**Interfaces:** existing Runtime.from_files/scan/advance_time/instantiate/program_fb and FBHandle.call_method/get_property/set_property/set_input. Example uses inherited I_Motor contract and virtual delays of 100/250/500 ms.

- [ ] Write integration tests asserting three independent startup delays, dynamic overridden hook, fake substitution for conveyor 2, fault isolation and explicit restart, inherited property access and private/protected rejection. Run against absent/incomplete example to establish failures.
- [ ] Implement native files: shared motor state/properties/timer in FB_MotorBase IMPLEMENTS I_Motor; derived FB_MotorSim and FB_MotorFake; three-conveyor PROGRAM/GVL. Keep previous examples intact.
- [ ] Add Polish README explanation, runnable Python example and scope/limitations; bump version and verify the snippet.
- [ ] Run full pytest, raw Ruff through reviewdog (flake8 parser, nofilter), format check, git diff --check; build wheel/sdist and run examples from installed wheel in isolated Python 3.11.
- [ ] Commit Task 3, perform independent whole-branch review and fix verified findings with regression tests; record final commands/results and complete checkboxes.
