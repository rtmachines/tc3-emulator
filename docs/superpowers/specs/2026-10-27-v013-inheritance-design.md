# v0.13: function block inheritance

The user accepted EXTENDS, SUPER^, PROTECTED, inherited storage/methods/properties,
interface dispatch, TcPOU import and Python access, with tests and a conveyor example.
Implement that accepted scope. Runtime remains standalone, Python >=3.11, standard
library only, usable on Linux, with deterministic virtual time. Preserve v0.12 behavior.

## Approach and boundaries

Implement nominal single inheritance of FBs, including multiple levels. Keep original
declaration owners for lexical resolution and share one concrete instance's storage
across inherited implementations. Do not copy base implementations into derived
declaration scopes. This builds on existing methods, properties, interfaces and
lifetime checks. REFERENCE TO would address shared data, but is a separate language
and aliasing feature deferred to a later release.

No ABSTRACT, FINAL, INTERNAL, interface EXTENDS, pointer/reference operators,
FB_init/FB_exit/FB_reinit, actions, online change or persistence semantics in v0.13.
Do not silently accept unsupported syntax. No runtime dependencies or hardware access.

## Language and validation

- `FUNCTION_BLOCK Derived EXTENDS Base [IMPLEMENTS I1, I2]` accepts one user-defined
  FB base, resolved regardless of declaration/file order. Builtin PLC blocks cannot
  be extended. Reject unknown/non-FB bases, self-inheritance and longer cycles.
- Append `Pou.extends: str | None = None`; add frozen `Super(loc: Location)` to
  LValue/Expr, with ordinary Member/Call nodes for SUPER operations. Existing AST
  positional constructors remain compatible. Preserve names and owners of declared
  methods and accessors, e.g. Base.Update, including when inherited by Derived.
- Inherit persistent variables, constants, methods, properties and implemented
  interfaces. Initialize inherited storage once, using declaration lexical scopes
  and original resolved defaults. A derived instance contains one copy of base
  state; separate instances and FB array elements remain independent.
- Reject variable/member collisions, including variables hiding inherited members.
  TwinCAT's exception allowing a derived declaration to shadow base VAR_TEMP must
  retain distinct activation storage and lexical access if implemented; otherwise
  explicitly reject and document this bounded profile, never silently alias them.
  Initial profile: reject that shadowing exception. VAR_TEMP names remain reserved
  against shadowing, but each declaration is visible only in its declaring FB body
  activation, not in descendant bodies or methods/accessors.
- Override methods with matching formal names/order/directions/resolved types,
  result type, access, and normalized default/requiredness contract. Local variables
  and implementation may differ. Canonical aliases retain existing equivalence.
- Override properties with matching type/access and accessor set/access contracts.
  A property redeclaration replaces that property implementation as a unit; missing
  required accessors is an error. Extra partial-accessor inheritance is not inferred.
- PUBLIC remains externally accessible. PRIVATE is callable only from its declaring
  FB's lexical scope, including when that code runs on a derived receiver; it cannot
  be overridden. PROTECTED methods/properties/accessors are accessible to the
  declaring FB and descendants, not external ST or Python. Accessors cannot widen
  a property's access (PUBLIC > PROTECTED > PRIVATE). Interfaces remain PUBLIC only.
- Global names and explicit AST input receive the same declaration validation as ST.
- Reject unsupported calls and member use statically, with source locations. Extend
  containment, memory/instance limits and recursion checks to inherited execution.
  Conservative rejection of potential dynamic recursion remains the checked profile.

## Execution

- Ordinary calls, unqualified member calls, THIS^ and interface calls select the
  most-derived override permitted by the statically visible declaration. Base
  implementations can invoke overrides on the same concrete receiver. Private
  members remain bound to their declaring implementation.
- SUPER refers to the immediate base of the lexical declaring FB, not the dynamic
  receiver's base. `SUPER^()` executes that base FB body explicitly; a derived FB
  call does not automatically execute the base body. `SUPER^.M()` and SUPER property
  GET/SET select the base-visible implementation without virtual redispatch.
  The called base implementation still uses virtual dispatch for its ordinary calls.
- SUPER field access uses inherited storage, existing read/write rules and lexical
  visibility. SUPER is valid only within a derived FB or its methods/accessors.
  It is not a general pointer or value: reject assignments/copies of SUPER itself,
  use outside derived FBs and calls targeting non-callable members.
- Preserve argument evaluation order, receiver capture, input/output/IN_OUT aliasing,
  checked conversions, step/depth budgets, virtual time and fault latch. SUPER calls
  share the same Context. Validate arguments before mutation from Python.
- VAR_INST storage is keyed by declaring method and actual receiver. Inherited calls
  share that method's state; override and base method have distinct VAR_INST banks.
  Inherited timers, nested FBs/arrays and interface lifetime tokens follow the owner.
  Each FB body invocation has its own VAR_TEMP activation, including SUPER bodies;
  no temporary state or references survive beyond their permitted lifetime.
- Inspection stays passive and detached; inherited stored state appears once.
  Existing handle APIs expose inherited public methods/properties/inputs/output cells
  and nested FBs without introducing a second Python instance for the base.

## Import and Python

TcPOU Declaration supports EXTENDS and PROTECTED on methods/properties/accessors.
Preserve strict XML validation, source locations, metadata matching and rejection of
injected objects. TcIO must continue rejecting inheritance and non-public prototypes.
Runtime.instantiate of a derived type, FBHandle.call/call_method/get_property/
set_property/set_input and nested selectors use inherited member contracts.
Derived FBHandle may be supplied to an inherited implemented interface, with existing
same-Runtime validation, lifetime checks, null behavior and exact nominal interfaces.
No new by-value copying or FB VAR_IN_OUT/reference API is introduced.

## Example and acceptance

Add examples/conveyor_inheritance with a native I_Motor.TcIO, FB_MotorBase implementing
that contract, FB_MotorSim and FB_MotorFake extending it, and three conveyors managed
by PROGRAM/GVL. Base owns shared state/properties/start delay and a protected hook;
derived implementations specialize simulation/fault behavior. Python injects a fake
for the second conveyor, advances virtual time, faults it, clears fault and explicitly
restarts it. Other conveyors and existing examples remain unaffected.

Tests exercise multi-level/forward inheritance, base state/default isolation, inherited
arrays and constants, dynamic vs SUPER dispatch, private and protected access,
property GET/SET, independent override/base VAR_INST, inherited timers and transient
lifetimes, nominal interface binding, Python prevalidation and import diagnostics.
Negative cases include bad bases/cycles, collisions, incompatible overrides, illegal
SUPER/context/access and unsupported modifiers. Full regression, Ruff via reviewdog,
format, executable examples and installed-wheel smoke on Python 3.11 are required.
Release version becomes 0.13.0; README states scope, usage and explicit limitations.

## Sources

- https://infosys.beckhoff.com/content/1033/tc3_plc_intro/3537661579.html
- https://infosys.beckhoff.com/content/1033/tc3_plc_intro/3537664139.html
- https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2528837771.html

Native TwinCAT execution is unavailable. Compatibility is checked against documented
semantics and the emulator's explicit profile, not by claiming native parity.
