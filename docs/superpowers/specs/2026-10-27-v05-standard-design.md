# v0.5: standard PLC blocks, operators, conversions and constants

User accepted this milestone and explicitly requested implementation, tests and examples.
The existing standalone Python 3.11+ runtime remains dependency-free, with virtual time,
checked values, static validation of all POU bodies, copy semantics and stable IN_OUT cells.

## Design decisions

Extend the existing typed interpreter. Standard blocks reuse ordinary POU interfaces and
persistent per-instance state. Pure overloaded operators have a small explicit registry,
argument binder, type inference and evaluation module. VAR CONSTANT is local to FUNCTION/FB;
no PROGRAM/GVL or scheduler is added. Full OOP and bit manipulation are later milestones.
Alternative approaches: emitting ST wrappers works for simple blocks but cannot express
polymorphic operators or lazy selection; a new compiler is unnecessary for the existing goal.

### Standard blocks
R_TRIG, F_TRIG (CLK/Q); SR (SET1,RESET/Q1), RS (SET,RESET1/Q1);
CTU (CU,RESET,PV/Q,CV), CTD (CD,LOAD,PV/Q,CV),
CTUD (CU,CD,RESET,LOAD,PV/QU,QD,CV). PV/CV are WORD (0..65535).
Add WORD as a distinct checked unsigned storage/numeric type; no bitwise operations yet,
no enum WORD base. Outputs start with normal zero/FALSE storage, updated on explicit call.
R_TRIG starts with remembered FALSE. F_TRIG requires a previously sampled TRUE before a fall.
SR/RS obey level-sensitive documented set/reset dominance. Counters sample edges every call,
including reset/load. RESET wins LOAD; LOAD wins counting; simultaneous CU/CD rising edges
cancel. Saturate at 0/65535 (not PV); Q/QU is CV>=PV, QD is CV=0. These boundary rules are
explicit emulator profile choices where documentation is not exhaustive. Existing timers unchanged.

### Pure operators and conversions
ABS, MIN, MAX, LIMIT, SEL, MUX; positional and named inputs, never mixed, no output bindings.
MIN/MAX accept >=2 values; MUX selector plus >=1 alternative. LIMIT parameters MIN,IN,MAX
(aliases MN/MX accepted); MIN/MAX/MUX alternatives IN0..INn, SEL G/IN0/IN1, unary IN.
ABS numeric only. MIN/MAX/LIMIT numeric or identical TIME/enum/BOOL; selectors additionally
allow same-type arrays/structs. Numeric types use the current common-type rules; identical
concrete types retain their type and check range. Aliases transparent. SEL/MUX evaluate only
the selector and chosen expression, while every branch is statically checked. MUX K>=count
selects last, negative K errors. LIMIT implements MIN(MAX(IN,MIN),MAX), also when MIN>MAX.
Conversions: typed X_TO_Y and TO_Y among BOOL, INT, UINT, DINT, UDINT, WORD, REAL,LREAL,TIME.
Integer-like and TIME values convert via their numeric value (TIME milliseconds), BOOL via0/1;
to BOOL is nonzero; floats to integral/TIME round nearest ties-to-even, then range check.
No wrapping, NaN, infinity or enum/aggregate conversion. Typed conversion validates/coerces
input to its named source: numerical inputs can be range/precision-checked to source; BOOL
and TIME retain category restrictions except untyped INTEGER literals for TIME. Details and
supported conversion matrix recorded by operator implementer. Ambiguities resolved consistently
and documented, not by silent Python casts. Unknown names and collisions rejected.

### Constants
VAR CONSTANT only (not INPUT/OUTPUT/IN_OUT/TEMP or FB instances), initializer required.
All supported value types may be constant. Read-only recursively: assignments, FOR control,
IN_OUT and output binding targets rejected. Normal VAR_INPUT copies of constants allowed.
Local named constants can appear in initializers, CASE labels and array bounds. Expressions
include literals, enum members, local constants, unary and binary operators with the same
checked semantics as runtime. No user/builtin calls or mutable-variable dependencies in
constant expressions in v0.5. Resolve local dependencies including forward references;
reject cycles, unknowns and invalid bounds before allocating values. Named TYPE declarations
cannot refer to POU-local constants; their literal arithmetic bounds are allowed.
Existing AST signatures stay compatible through defaulted new fields. Literal array bounds
remain ArrayType; expression bounds use a separate syntax node, resolved before memory use.

## Verification
Retain all 704 tests. Add source-level tests of every block, overload, conversion family,
constant initialization/read-only path, negative validation, and lazy side effects. Add example
batch counter + timer + configuration and arithmetic scaling using constants. Readme v0.5,
wheel/sdist and clean installed-package smoke, Ruff/reviewdog, independent final review.

## References
- https://download.beckhoff.com/download/document/automation/twincat3/TwinCAT_3_PLC_Lib_Tc2_Standard_EN.pdf
- https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2528853899.html
- https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2528956043.html
- https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2528977547.html
- https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2529284235.html
