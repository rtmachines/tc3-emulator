# v0.6 bit types, literals, operations and bit access

User explicitly requested implementation of the proposed v0.6 milestone, tests and examples.
Extend the existing standalone Python3.11+ checked interpreter; no runtime dependencies.
Preserve1048 tests, WORD counter interfaces, previous arithmetic/BOOL behavior, virtual time,
static validation, stable aggregate cells, fault policy and Python argument atomicity.

## Scope and chosen semantics
BYTE0..255, DWORD0..4294967295 added alongside WORD; numeric storage/conversions remain
checked, no general arithmetic wrapping. All11 existing/new scalar categories participate in
X_TO_Y and TO_Y conversions. Enum bases remain INT/UINT/DINT/UDINT (no bitstring bases).
No LWORD/LINT/ULINT, BIT structures, pointer/address operations or partial .%B access.

Literals: decimal/binary2#/octal8#/hex16#, separators only between digits, case-insensitive.
Typed integer prefixes for supported INT/UINT/DINT/UDINT/BYTE/WORD/DWORD, decimal or based,
including explicit signed decimal values. Typed literals preserve declared type and range;
INT#16#FFFF errors rather than reinterprets negative. Untyped based literals choose smallest
BYTE/WORD/DWORD that holds value; >DWORD errors. Decimal untyped retains INTEGER signed64
intermediate semantics. Existing REAL/LREAL/TIME literals and signed64-min edge preserved.
Allow integer literals in bounds, enum explicit values, CASE labels and repetition counts.

Bitwise AND/OR/XOR/NOT keep BOOL overload. BYTE/WORD/DWORD use fixed-width operations;
mixed bitstrings widen to widest. Untyped INTEGER operands adopt a bitstring partner's type;
without one default to DWORD. Values must fit selected unsigned width. Typed INT/UINT/DINT/
UDINT are not bitwise operands (use conversion), BOOL cannot mix with bitstrings.
NOT masks to width; operations preserve result type. Works equally in constant expressions.

SHL/SHR/ROL/ROR added to standard functions, input names IN,N; preserve first bitstring type,
untyped INTEGER first argument defaults DWORD. Count accepts integer types except BOOL,
negative is execution error, shift >=width returns0, rotation count modulo width. No huge
intermediate allocation for large counts. Existing eager argument order/budget/fault rules apply.
Calls remain disallowed in constant initializers in v0.6; infix bit operators are allowed there.

Bit access: integer variables (BYTE/WORD/DWORD plus INT/UINT/DINT/UDINT) support literal or
local scalar constant index, zero-based: word.0, word.cEnable. This combines with struct fields,
array elements and public FB fields. Named field ambiguity resolved by base type; struct member
names keep their old meaning. Index must be a compile-time integer in range. Bit result is BOOL.
Read and write preserve all other bits; signed integer access uses two's-complement width.
Constant owners are read-only recursively. Reject bit locations as VAR_IN_OUT arguments,
allow by-value inputs and copy-out targets. Python Cell.bit(index) gives live BOOL view, stable
across whole-parent replacement. Python VAR_IN_OUT rejects this view just like ST.

## Architecture / alternatives
Use a shared pure bitwise module for type/width/value semantics across validation/constants/
execution; keep scalar descriptor additions in types.py and shifts in standard_functions.py.
Parser adds BitAccess(base,index,loc) for numeric dot suffix; named dot access retains current
Reference/Member syntax. Validator caches resolved accesses in Registry.bit_accesses[id(node)]
=(baseLValue,index); Engine resolves live BitCell through the same base. This avoids evaluating
an index repeatedly and avoids treating bits as independent storage. A copied BOOL cell would
break write-through and is rejected as an approach. A compiler change is unnecessary.

## Verification and delivery
Tests first for literal grammar/type/range, all width and conversion families, mask/shift/rotation
edges, signed bit writes, nested aliases, constants and forbidden IN_OUT, readonly/fault behavior.
Examples: device-status decoder/control word, byte extraction and packing. README and version0.6,
independent review, full pytest/Ruff/reviewdog, wheel+sdist and isolated Python3.11 smoke.

## References
https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2529316491.html
https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2529343371.html
https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2528939915.html
https://infosys.beckhoff.com/content/1033/tc3_plc_intro/2528907659.html
