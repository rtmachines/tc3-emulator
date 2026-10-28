# v0.17 Interface Inheritance and Collections

## Intent and authorization

Add inherited interface contracts and fixed arrays of interface references so a
line manager can operate three different conveyor implementations through one
contract. The user approved this feature direction, the heterogeneous conveyor
example, implementation, and model sizing according to task complexity. This
document records implementation decisions within that authorization; it does not
introduce another approval gate. The parent agent performs the builder check
before implementation.

Baseline: `9689c98` (v0.16), branch `codex/v017-interface-collections`, existing
isolated worktree. This is a bounded language/runtime change, not an OOP redesign.

## Constraints

- Python >=3.11, no runtime dependencies.
- Preserve checked-subset validation, case-insensitive names, source locations,
  static recursion checks, instruction/depth limits, fault latching and v0.15
  initialization order.
- Preserve nominal types, reference identity, transient ownership lifetimes and
  Python argument prevalidation before mutation.
- No pointers, SFC, restart/online change, array covariance or implicit downcasts.
- Native-format fixtures do not establish execution on TwinCAT.
- Array rank remains 1–8, inclusive DINT bounds, at most 1000000 elements; expanded
  owned storage remains capped at 1000000 scalar leaves and 10000 FB instances.

## Evidence and approaches

Beckhoff documents interface inheritance, inherited methods/properties and
multiple interface bases: [Extending interfaces](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2527343499.html).
Its [Object Interface](https://infosys.beckhoff.com/content/1033/tc3_plc_intro/4256428299.html)
documents interface variables as references to FB instances, dispatch to the
referenced instance, exact implementing signatures and comparison with zero.
These sources guide inheritance and identity; they do not establish every
collection or conflict rule below. Those rules are this emulator's checked subset.
There is no ADS implementation or native differential-test claim.

The accepted direction combines inheritance and collections. Implementation
alternatives considered were value arrays containing handles (would entangle
copy/serialization with identity), a general collection/parameter system (too
large for this increment), and dedicated fixed storage like existing `FBArray`.
Choose dedicated `InterfaceArray` storage holding existing `InterfaceSlot`s.
This shares element binding, dispatch and expiry rules with scalar interfaces
while keeping aggregate value semantics out of scope.

Current source anchors are `InterfaceDecl` in syntax.py, interface parsing in
parser.py, `_xml_interface` in loader.py, `Registry` and `_Validator` in
validation.py, `InterfaceSlot`/`FBArray` in memory.py and `Engine.resolve` in
execution.py. The graph narrowed these areas; source and existing interface,
inheritance, array and initialization tests establish the actual behavior.

## Inherited contracts

Accept `INTERFACE I_Derived EXTENDS I_First, I_Second` in ST and native TcIO
declarations. Forward declarations, arbitrary source-file order and mixed case
work. Append `extends: tuple[str, ...] = ()` to `InterfaceDecl`, preserving old
positional constructors. Reject missing/duplicate bases, repeated/malformed
EXTENDS, unknown bases, non-interface bases and direct/indirect cycles, including
unused interfaces. Errors remain source-aware. Do not silently drop EXTENDS when
the TcIO loader assembles member declarations.

Validate direct prototypes in their original lexical declaration scope first.
Then construct effective methods/properties and the transitive ancestry closure.
Keep the prototype's original owner, qualified name and source location; do not
clone a base method into each descendant. Existing FB inheritance dispatch remains
responsible for finding the concrete implementation.

Merge policy is deterministic and independent of declaration-file order:

- A diamond carrying the same declaration once or repeatedly produces one member.
- Different declarations with an identical resolved contract coalesce. Methods
  compare name, return type, ordered parameter names/modes/types, and presence and
  resolved values of input defaults. Existing alias equivalence and nominal
  enum/STRUCT rules apply; interface parameter types remain exact, not covariant.
- Properties compare name/type and exact GET/SET presence. GET-only and SET-only
  bases do not synthesize a new property; differing accessor sets conflict.
- A local redeclaration is accepted only when its resolved contract is identical.
  Conflicting return types, parameters/defaults, property types/accessor sets or
  method/property name collisions fail even without an implementing FB.
- No base-order priority hides a conflict. An identical contract can use the
  first deterministic traversal representative; the choice has no runtime effect.

An FB implementing a derived interface also implements all its ancestors. This
applies through FB inheritance as well. Check all effective contracts against
PUBLIC concrete methods/properties, including inherited/overridden FB members.
The conservative call graph includes all implementers of the receiver's declared
interface for inherited method/property calls, independently of the prototype's
lexical owner or equivalent base order, so indirect recursion cannot evade
validation without adding impossible ancestor-only receivers.

For assignment and scalar VAR_INPUT arguments (including FB_init), allow concrete
implementer to interface, same-interface copy, and derived-interface to ancestor
interface. Reject ancestor-to-derived and sibling conversions even when a
particular runtime target happens to implement both. A base-typed reference
exposes only the base contract. No object copy or lifetime extension occurs;
dynamic dispatch still uses the same concrete Frame. Literal integer zero keeps
its existing clear/default/null-test behavior; interface-to-interface equality
remains unsupported.

## Fixed interface arrays

Use a distinct frozen `InterfaceArrayType(bounds, element_type: InterfaceType)`
and mutable `InterfaceArray(type_name, items: tuple[InterfaceSlot, ...])`. Every
element owns a distinct slot, initialized unbound. The array owns slots, never
the target FB. Index order and detached nested snapshots match FBArray.

| Operation / context | v0.17 profile |
| --- | --- |
| Direct `ARRAY[low..high, ...] OF I` storage | Supported in nonconstant VAR, GVL, VAR_TEMP and VAR_INST wherever that section is already legal |
| Function/method/accessor local VAR | Supported with existing invocation lifetime; VAR_INST retains existing METHOD-only rules |
| Declaration initializer, including `:= [0, 0]` or `:= 0` | Rejected; default is all unbound slots |
| FB-style constructor arguments/per-element init arguments on the array | Rejected; bind elements in ordinary ST or owner FB_init |
| Element assignment from FB / interface / zero | Supported using the scalar interface compatibility rules |
| Element-to-element assignment | Supported; copies the current target binding, not a live link to the source slot |
| Indexed method calls, property GET/SET, `= 0` / `<> 0` | Supported with the declared element contract |
| `LOWER_BOUND` / `UPPER_BOUND` | Supported using the declared dimensions and existing dimension validation |
| Whole-array assignment, comparison, return, initializer expression | Rejected |
| Fixed/open interface-array formal parameters in any mode | Rejected; scalar interface inputs remain supported |
| Alias/STRUCT field/nested ARRAY OF ARRAY/REFERENCE TO interface-array type | Rejected; direct multidimensional arrays are supported |
| Python Cell/ArrayValue/check_value/default_value/value-type APIs | Reject interface-array descriptors/storage |
| Python `program_fb`, `global_fb`, `FBHandle.fb` array selection | Reject interface arrays; these APIs select owned FB instances |
| Python binding/dispatch | Use existing scalar interface inputs and user ST methods such as `Bind(index, target)` |
| Python inspection | `FBHandle.inspect()` includes detached nested tuples of existing slot metadata; no new public interface handle API |

These are checked-subset boundaries, not claims that native TwinCAT forbids the
excluded operations. `ArrayType(..., InterfaceType(...))` remains a rejected
value-array descriptor. Parser array declarations start with nominal names and
validation resolves only eligible direct storage to InterfaceArrayType.

Count one scalar leaf per slot during ownership preflight before allocation,
including arrays inside nested FBs and persistent method banks. Referenced
targets do not count as owned children and must not be initialized or expired by
walking their references. Existing FB ownership still determines target expiry.

## Evaluation, initialization and failure behavior

An index expression is evaluated once per storage selection. For a method call
or property assignment, select/capture the indexed receiver before evaluating
arguments or the setter RHS; rebinding the array or changing its index during
those expressions must not change the captured receiver. Null/expired receiver
and out-of-bounds errors happen before those argument/RHS side effects. Ordinary
element assignment follows the established scalar assignment order.

Wrong rank/non-integer indices are rejected by validation; runtime bounds faults
and dynamic bounds-dimension faults retain location, call stack and fault latch.
Dispatch uses the existing Context budgets and depth rules. Clearing an expired
slot with zero is allowed before any fault; reading/copying/null-checking or
dispatching its expired target faults exactly like scalar interfaces. Passive
inspection stays available and does not follow targets, even after faults or
reference cycles.

VAR and GVL slots persist with their owners; transient locals and VAR_TEMP start
unbound on each activation; VAR_INST persists with the owning FB. Escaping a local
FB through an array slot does not prolong its lifetime. Copying its binding to a
persistent scalar or another array likewise does not prolong it.

Arrays are allocated before owner initialization. Owner FB_init can bind elements
from its scalar interface inputs before the first scan, and cannot initialize the
targets a second time. Child/sibling allocation and initialization ordering,
post-init setters and call_after_init remain unchanged. Runtime Python FB_init
inputs retain same-runtime FBHandle-or-zero prevalidation.

## Heterogeneous conveyor example

Create `examples/conveyor_collections/` in native TcIO/TcPOU/TcGVL format with
`examples/test_conveyor_collections.py`. Keep older examples intact.

`I_Conveyor EXTENDS I_Command, I_Status` combines command methods and status
properties. `I_Command` declares `Start`, `Stop`, `Reset`, and
`Cycle(enabled: BOOL, sensor: BOOL, blocked: BOOL)` as VAR_INPUT parameters.
`I_Status` declares read-only Running, Alarm, ProductCount and ActualSpeed plus
read/write SpeedSetpoint. Use BOOL/STRING(80)/DINT/REAL types respectively
(SpeedSetpoint is REAL). A specialized `I_Reversible EXTENDS I_Conveyor` adds
read/write `Reverse: BOOL` to exercise a second inheritance level.

Concrete types are `FB_StandardConveyor`, `FB_ReversibleConveyor` and
`FB_JamConveyor`. Shared implementation through an FB base is permitted and
preferred where it keeps the sample clear. The reversible implementation exposes
I_Reversible and reports a negative ActualSpeed when Reverse is set. The jam
implementation stops/latches an alarm after blocked remains true for 300 ms;
Reset after obstruction clears permits an explicit Start to resume.

MAIN_Line declares the three concrete instances first, with FB_init start delays
100/250/500 ms, then `line : FB_Line(first := standard, second := reversible,
third := jam)`. FB_Line's FB_init declares the two system BOOL inputs and three
scalar `I_Conveyor` inputs, and binds `devices[1..3]`. This is observable before
the first scan, with each target initialized once. No first-scan flag is used.

FB_Line owns `devices : ARRAY[1..3] OF I_Conveyor` and offers
`Bind(index: DINT, target: I_Conveyor)` with scalar VAR_INPUTs. Its scan and command
loops operate only through devices, use bounds intrinsics and guard unbound slots.
There are no concrete-type conditionals. Rebinding preserves the new target's
existing state, does not run FB_init, and does not mutate the previous target;
after replacement the old target simply receives no further manager commands.
Binding zero disables that slot; publish Running FALSE, ActualSpeed 0.0,
ProductCount 0 and Alarm 'Not bound' for it.

GVL_Line carries enabled/sensor/blocked input arrays and running/actualSpeed/
productCount/alarm output arrays. Tests invoke line Start/Stop/Reset through
existing method APIs. Use speeds 0.5/0.75/0.6 and Reverse TRUE on the second
conveyor, yielding 0.5/-0.75/0.6 when running. Independent product edges count
independently. A Python-created replacement is bound by `line.call_method('Bind',
index=2, target=replacement)`; invalid foreign-runtime targets leave the prior
binding and all state intact. Any guards for unbound slots use the same zero
comparison semantics as production interface storage.

## Delivery and verification

Three sequential, independently reviewed tasks: inherited contracts; collections;
native example/docs/version 0.17.0. Shared parser/validator/runtime files have one
implementer at a time. Use higher reasoning effort for the first two tasks and
moderate effort for example/docs; use a strong independent final branch review.

Each task records actual failing behavioral tests before implementation and
passing results after it. Cover declaration permutations, conflicts/diamonds,
static contract visibility, receiver capture, temporary escape, storage budgets,
initialization and Python prevalidation. Run relevant old tests as regressions.
Final gates are full pytest, Ruff through local reviewdog, formatting/diff checks,
graph/source/OCR delegate whole-branch review, wheel and sdist inspection, and the
complete test/example suite against an isolated installed wheel on Python 3.11.
Verify import provenance outside the checkout and metadata with no dependencies.
