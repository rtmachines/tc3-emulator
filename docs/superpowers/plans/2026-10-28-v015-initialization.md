# v0.15 FB Initialization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

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

- [x] Add failing parser tests for FB/method call_after_init markers, single/shared arguments,
  per-element array arguments, post-init values and invalid pragma positions/malformed syntax.
- [x] Run `.venv/bin/python -m pytest tests/test_parser_initialization.py -q` and record expected failures.
- [x] Implement syntax/parser changes without accepting unknown attributes or changing STRING(n).
- [x] Add failing native TcPOU tests for marked FB/methods and preserved locations; implement loader support.
- [x] Run both new test files and existing parser/loader tests; run full suite; commit only owned files.

### Task 2: Validate and execute instance initialization

**Files:** tc_emulator/validation.py, execution.py, runtime.py, memory.py; optional focused
tc_emulator/initialization.py; tests/test_validation_initialization.py, test_runtime_initialization.py.

**Interfaces:** Consume Task 1 fields. Produce `Runtime.instantiate(name, *, init=None, inputs=None)`
and automatic initialization of all persistent/transient owned instances as specified in the design.

- [x] Write failing end-to-end tests: initial flag values TRUE/FALSE, ignored FALSE return,
  init n=1 then post-input=2 then hook-observed=2, inherited order 1/2/3, single execution across scans.
- [x] Run focused tests to observe missing lifecycle support before implementation.
- [x] Validate lifecycle signatures, derived-prefix contracts, markers, declaration argument binding,
  post-input/property assignments, initializer scopes and direct-call prohibitions.
- [x] Implement initialization scheduling with shared Context and correct persistent/transient lifetimes.
- [x] Implement Python mapping arguments with full prevalidation before executing user code.
- [x] Add and run tests for per-element arrays, shared refs/interfaces, transient bound inputs,
  lexical inherited defaults, unknown/duplicate/missing args, foreign Cell/FBHandle, null, bad types,
  init/hook/setter faults, recursive local FB construction and step/depth exhaustion.
- [x] Run complete suite, Ruff and formatting; commit owned files after review of diff.

### Task 3: Example, documentation and release

**Files:** examples/conveyor_initialization/*.TcPOU/*.TcGVL/*.TcDUT, examples/test_conveyor_initialization.py,
README.md, pyproject.toml, optionally examples/initialization_order.st.

**Interfaces:** Consume initialization declaration syntax and Python API from Tasks 1–2.

- [x] Add failing behavior tests for three ready instances before scan, unique IDs and init counters,
  shared config, independent delays 100/250/500 ms, configuration mutation and repeat-scan stability.
- [x] Add native-format base/derived conveyor blocks with FB_init and marked after-init override,
  shared GVL config, PROGRAM and per-element initialization parameters.
- [x] Run example tests and full suite; document runnable Python usage and precise profile limitations.
- [x] Bump version to 0.15.0, update feature/exclusion lists and include a native-compatible order fixture.
- [x] Run raw Ruff through reviewdog, formatter check, build wheel and test installed wheel outside checkout.

### Task 4: Independent review and final verification

**Files:** all v0.15 changes and this plan's verification record.

- [x] Refresh CRG; inspect changed-file context/affected flows and source; obtain independent final review.
- [x] Resolve actionable issues with regression tests and scoped re-review.
- [x] Record final suite/lint/build/wheel evidence and remaining native-TwinCAT verification limitation.
- [x] Commit completed work on codex/v015-fb-init and leave it available for user review.


## Completion and verification record

Implementation is complete on `codex/v015-fb-init`, based on v0.14 `85f5b1f`.
Final product-code/test commit: `ed237ec`. The three implementation stages and
independent integration review are complete with no open or deferred findings.

- Source suite on Python 3.13.17: **3024 passed in 4.24 s**, no failures/skips.
  This adds **182 test cases** to the v0.14 baseline of 2842.
- Installed wheel on Python 3.11.17, outside the checkout: **3024 passed in 4.39 s**.
  Tests and native examples were copied to an isolated temporary directory;
  package provenance was confirmed under that environment's site-packages.
  Command: `env/bin/python -I -m pytest tests examples -q -c /dev/null --rootdir=. --confcutdir=. -p no:cacheprovider`.
- Both README v0.15 Python blocks passed against the installed wheel, including
  pre-scan initialization and standalone `instantiate(init=..., inputs=...)`.
- Full raw Ruff through local reviewdog (`set -o pipefail`, nofilter, warning
  threshold) is clean; raw output is `All checks passed!`. Formatter: 128 files
  already formatted. Git diff whitespace checks are clean.
- Wheel and sdist build successfully. All **16 runtime modules** in the wheel
  byte-match the tested sources. Metadata is version **0.15.0**, Python **>=3.11**,
  with **no runtime dependencies**. All **174 tracked packaged source, test,
  documentation and example files** byte-match the source archive.
- Task reviews checked parser/import, lifecycle execution, and all eight example/
  documentation files. The final integration review covered **22/22 changed files**,
  including native XML/ST, tests and documentation. Three task-level findings
  and two final integration findings were fixed with red-to-green regressions.
  Scoped re-reviews approved every fix; the final verdict is **SPEC PASS / QUALITY
  APPROVE**, with no open findings. Code-review-graph was used to narrow impact,
  followed by exact source review; absent graph flows were not treated as proof.
- Verification-only documentation completion is followed by archive regeneration
  and byte comparison against the committed tree. Unchanged code tests are not
  repeated solely because this verification record changes.

### Decisions made during implementation

- The user's explicit request to implement the selected scope authorized design,
  plan and execution together; no redundant approval pause was introduced. The
  recorded scope remains reviewable and changes would require ordinary rework.
- Reference preparation precedes lifecycle execution across allocated persistent
  trees; activation inputs precede preparation of transient children. This avoids
  unintended null constructor arguments from enclosing/forward references. It is
  a documented profile rule rather than a dependency scheduler; a different native
  ordering requirement would require reworking startup sequencing and its tests.

The release implements new-instance initialization only. Native TwinCAT execution
and IDE import have not been performed; native-format fixtures are supplied for
future differential verification. Restart, retention, online change, FB_exit and
FB_reinit remain outside scope. Changes are committed locally; no merge or remote
publication was requested or performed.
