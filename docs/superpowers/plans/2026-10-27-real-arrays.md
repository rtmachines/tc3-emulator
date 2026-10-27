# REAL/LREAL and Arrays Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Add REAL/LREAL and fixed scalar arrays, preserving isolation and checked execution.
**Architecture:** Extend immutable syntax, whole-program validation, typed memory and interpreter.
**Tech Stack:** Python3.11+, standard library; pytest/Ruff.
**Spec:** docs/superpowers/specs/2026-10-27-real-arrays-design.md

## Global Constraints

No runtime dependencies or TwinCAT; existing integer behavior and source-aware errors preserved.
Exact shared interfaces in .work/real-arrays/interfaces.md. Disjoint ownership for parallel work.
No Git repository; work in place. User explicitly asked to add features now, no extra approval pause.

## Review Focus

Float32 rounding at every boundary; numeric promotion before comparison; arrays preserve element
aliases under whole-array assignment; no copy leakage; invalid API arguments mutate nothing;
multidimensional index bounds checked per coordinate; partial/repeated initializer resource bounds.

### Task 1: Types and memory (root)
- [x] Write/run failing tests for binary32/64 finite storage and checked array descriptors/shapes.
- [x] Extend types.py and memory.py; preserve old scalar tests.
- [x] Verify element aliases and snapshots independently of the interpreter.

### Task 2: Syntax/parser (parser agent)
- [x] Write/run failing tests for float and typed literals, array declarations, index expressions,
  multidimensional/repeated/partial declaration initializers.
- [x] Extend syntax.py/parser.py, retain loader section checks and positions.
- [x] Run parser/loader tests; report changes and regressions.

### Task 3: Static validation (validator agent)
- [x] Write/run failing ST tests for new types, promotions, initialization, indexing and arrays in
  arguments/results, preserving precise IN_OUT/output types and validation of all code.
- [x] Extend validation.py using shared AST and type helpers.
- [x] Verify invalid index types/count, invalid shape/bounds/initializer, forbidden float-to-int,
  BOOL arithmetic and MOD floats.

### Task 4: Execution/API (root)
- [x] Write/run failing integration tests through Runtime for float precision and operations,
  multidimensional array cells, whole-array copies, element/whole-array aliases and instance isolation.
- [x] Extend execution.py/runtime.py/__init__.py; shared types carry arithmetic precision.
- [x] Run all tests; fix mismatches against approved existing integer behavior.

### Task 5: Delivery and review
- [x] Add runnable ST examples and pytest examples; update README and version0.2.0.
- [x] Independent code review with code graph then exact source/tests; regressions for findings.
- [x] Full pytest, Ruff through reviewdog, formatting, wheel/sdist build and isolated wheel smoke.
