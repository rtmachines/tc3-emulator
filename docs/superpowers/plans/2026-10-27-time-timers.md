# TIME and timers implementation plan

Spec: docs/superpowers/specs/2026-10-27-time-timers-design.md
Global constraints: Python3.11+, stdlib-only runtime, explicit virtual time,
checked unsigned32 TIME, named timer calls, independent state, source-aware errors.
Existing356 tests must remain green. No Git repo; use snapshot .work/time-timers/baseline.

## Task1 — TIME front end (parser agent)
- [x] RED tests for TIME storage and literal grammar, bounds, exact-ms fractions,
  arrays, malformed units, prefix/position and existing float regressions.
- [x] types.py: add TIME to SCALAR_TYPES only (not INTEGER/NUMERIC_TYPES), range
  0..4294967295 to storage. Add parse_time_literal(text:str)->int if useful.
- [x] parser.py: tokenize duration as a unit and emit Literal(milliseconds,loc,"TIME").
  Preserve operators adjacent to literals and all existing numeric syntax.
- [x] Focused tests, full suite snapshot, Ruff; report with RED/GREEN evidence.

## Task2 — static validation (validator agent)
- [x] RED tests: accept TIME literals/arrays/results/IN_OUT and timer declarations;
  reject numeric mixing in assignment, initializers, arrays, comparisons and calls;
  reject timer name collisions, unknown/wrong arguments and non-instance calls.
- [x] validation.py: inject timer_definitions() and initialize call/containment maps;
  validate builtin signatures too. Implement TIME category and supported operations.
- [x] Ensure initializer type checks preserve TIME distinction before storage checks;
  no regression for signed64 unary literal boundary or REAL initializer rounding.
- [x] Focused tests, full suite snapshot, Ruff; report RED/GREEN evidence.

## Task3 — clock, timers and execution (root)
- [x] RED integration tests for clock, TON/TOF/TP exact deadlines, PT0, latched PT,
  TP rearm, skipped calls, retained inputs, invalid args, isolation and fault handling.
- [x] timers.py exports TIMER_NAMES, timer_definitions()->tuple[Pou,...] and
  TimerState(kind:str).update(input_value:bool,preset_ms:int,now_ms:int)->tuple[bool,int].
- [x] memory.Frame gains optional per-instance timer state. Context gains now_ms.
  Engine builds timer state for builtin POU, invokes after inputs with budget tick,
  writes Q/ET through Cells; TIME literals and operations keep TIME category.
- [x] runtime.py adds now_ms property and advance_time(milliseconds:int)->int,
  capturing now_ms in Context. All nested timers share the timestamp.
- [x] Integration suite: nested FB .TcPOU, bindings, TIME arrays and IN_OUT,
  function/VAR_TEMP lifetime, overflow, clock beyond2**32, no implicit execution.

## Task4 — examples, review, package (root + independent reviewer)
- [x] Add examples/timers.st, examples/FB_Delayed.TcPOU and examples/test_timers.py.
  Document Python milliseconds, explicit scans, PT latching and limits in README.
- [x] Update version0.3.0; create baseline diff; graph-first then source/test review.
- [x] Address findings with regression tests; run full pytest, Ruff/reviewdog/format.
- [x] Build wheel/sdist and test installed wheel with python -I in clean environment.

## Review focus

No TIME→int leakage through constants; exact literal parsing; inputs sampled only
at calls; timestamp0 is a valid start; no clock wrap; TP edge ignored on expiry;
all timer instances and Runtime clocks isolated; no partial mutation on bad API args.
