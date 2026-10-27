# TIME and virtual timers — v0.3

Extend the existing standalone Python ST interpreter with TIME, TON, TOF and TP.
Tests advance simulated time explicitly; there are no sleeps, real clocks, PLC
installation, threads or runtime dependencies. Existing v0.2 behavior stays intact.

## Approach and defaults

The implementation choice is one monotonic integer clock per Runtime, with built-in
timer FB definitions integrated into the existing typed call/memory machinery.
Timers only execute on explicit calls. A scheduler would add implicit scans and
ordering absent from this runtime; wall-clock injection would complicate tests.
The direct request to implement authorizes this reversible extension; these are
implementation defaults, not additional requirements attributed to the user.

## TIME

- Unsigned 32-bit milliseconds, 0..4294967295. Python inputs/outputs use int;
  reject bool, float, negative and overflow. TIME is distinct from ST integer types.
- Case-insensitive T#/TIME# literals with d,h,m,s,ms in descending order; underscores
  between components allowed. Highest component can exceed its ordinary unit range;
  subsequent h/m/s/ms components must be below24/60/60/1000. Fractions allowed only
  on the final component and only when their exact total is whole milliseconds.
  No negative durations, exponents, sub-ms precision or LTIME in this version.
- TIME variables, function results, arrays and IN_OUT use existing storage rules.
  TIME+TIME and TIME-TIME return checked TIME; comparisons require two TIME values.
  Unary+ allowed; unary-, numeric mixing, multiplication/division/MOD and casts out
  of scope. Declaration initializers remain literals/unary literals (existing rule).

## Clock and calls

`Runtime.now_ms` is a read-only int starting at0.
`Runtime.advance_time(milliseconds: int) -> int` accepts nonnegative int (not bool),
advances monotonically and returns now_ms. It does not call FBs or update outputs.
Clock values are unbounded Python ints; durations remain bounded TIME. Each top-level
call captures one now_ms shared by all nested calls. No advancement during execution.
Invalid clock arguments leave clock/state unchanged. Faulted runtimes reject clock
mutation just like other state mutation; now_ms and outputs remain inspectable.

## Built-in FBs

TON/TOF/TP are reserved POU names, available without declaring or loading a library,
including `Runtime.from_source("").instantiate("TON")`. Interface: IN:BOOL, PT:TIME
inputs (default FALSE/0), Q:BOOL, ET:TIME outputs (default FALSE/0).
They work as local/nested FB instances, through named ST arguments/output bindings,
and through existing FBHandle API (`call(**{"IN":True,"PT":1000})`). Omitted inputs
retain values. Each instance owns independent timer state. Fresh function locals
and VAR_TEMP create fresh timers, matching existing FB lifetime rules.

PT is latched at the triggering edge for each interval. Modifying PT does not affect
an active/completed interval; the next trigger uses the new input. This checked
profile choice is not claimed to match undocumented platform-specific behavior.

- TON: IN=FALSE resets Q/ET; first observed TRUE starts. ET=min(elapsed,latched PT);
  Q is TRUE at elapsed>=PT while IN remains TRUE.
- TOF: initial FALSE does not start. TRUE sets Q=TRUE,ET=0 and cancels any delay.
  Observed TRUE→FALSE starts; Q remains TRUE until elapsed>=PT, ET saturates at PT.
  Reasserting TRUE resets; next falling edge starts a new interval.
- TP: observed rising edge starts a pulse. Input edges during the pulse are ignored.
  Q stays TRUE while elapsed<PT; at expiry Q=FALSE. ET saturates while IN=TRUE;
  when expired and IN=FALSE, ET resets to0 on that call and timer rearms. A FALSE
  observation at/after expiry is required before another TRUE can trigger; edges
  during the pulse are not queued. A TRUE expiry call cannot retrigger.
- PT=0: TON/TOF immediately follow IN; TP emits no observable high pulse and needs
  FALSE before another trigger. Repeated calls at unchanged time do not advance ET.

## Verification and delivery

Add parser/type/validation tests and real ST integration tests for precise deadlines,
zero duration, cancellation/retrigger, ignored TP edges, PT latching, huge time jumps,
instance/runtime isolation, snapshots, atomic API validation, arrays and nested calls.
Include runnable .st/.TcPOU/pytest examples, Polish README and v0.3.0 package.
Run full pytest, Ruff/reviewdog, independent source review, wheel/sdist and isolated
installed-package smoke checks. No Git repository exists; work in place with baseline
snapshot for review.

## Primary references

- [TIME](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/12189021579.html)
- [TIME constants](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2529294987.html)
- [TON](https://infosys.beckhoff.com/content/1033/tcplclib_tc2_standard/74406539.html)
- [TOF](https://infosys.beckhoff.com/content/1033/tcplclib_tc2_standard/74405003.html)
- [TP](https://infosys.beckhoff.com/content/1033/tcplclib_tc2_standard/74408075.html)

These pages establish the normal signal behavior. PT changes, zero-duration scan
ordering, TP rearming details and explicit virtual-time scheduling are emulator
policies documented above.
