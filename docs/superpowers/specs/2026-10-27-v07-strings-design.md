# v0.7 STRING and Latin-1 design

User authorized implementation of STRING(n), standard text functions and basic conversions,
with tests/examples. Runtime remains standalone Python >=3.11, stdlib-only, Linux-compatible.
Baseline: v0.6, 1460 passing tests. No Git repository; baseline snapshot in .work/v07-strings.

## Approach and boundaries
Add a frozen StringType capacity descriptor to the existing value-type system; preserve
immutable Python str values and stable Cell aliases. Share text functions/conversions through
standard_functions dispatch, with pure text logic in string_functions.py. Extend existing
parser and validator; no new compiler/backend. This fits FUNCTION/FB unit testing better than
PROGRAM/GVL/scheduling or OOP; those are separate releases. User selected text support.
No WSTRING, UTF-8, byte indexing into strings, pointers, STRING_TO_REAL/TIME or reverse
floating/time formatting. No string arithmetic (+); concatenate with CONCAT.

## String storage contract
- types.StringType(length: int = 80), frozen/hashable, exact int (not BOOL), 1..1_000_000.
  __str__ returns STRING(n). Public export from tc_emulator.
- TypeSpec includes StringType; Scalar includes str; all value helpers, struct snapshots,
  aliases, arrays and parse_type accept it. resolve_type('STRING',...) -> StringType(80).
- check_value(StringType(n), value) requires Python str, validates the ENTIRE input is Latin-1,
  then takes text before the first NUL and clips to n characters/bytes. No replacement chars.
  This also defines API inputs, assignments, initializers and output copy semantics.
- default is ''. Length is bytes, not Unicode codepoints; Latin-1 is one byte per character.
- All six comparisons are case-sensitive lexical comparisons for any two STRING capacities.
  No implicit text/numeric conversion. Existing numeric semantics remain unchanged.
- Assignment/value parameters can copy between different STRING capacities with destination
  truncation. VAR_IN_OUT requires exact capacity (aliases transparent), as do whole-array
  type matches. Existing struct identity and element aliases remain unchanged.
- SEL/MUX accept string choices of differing capacities, result capacity=max alternatives;
  preserve lazy evaluation. MIN/MAX/LIMIT text overloads are outside this release.

## Syntax contract
- STRING, STRING(n), STRING[n]; n can be an integer constant expression, including a local
  VAR CONSTANT, with the same visibility/dependency rules as array bounds.
- syntax.StringBounds(length: Expr, loc: Location) represents unresolved capacity; parser
  returns StringType for bare/default or a direct integer literal, otherwise StringBounds.
  ArrayBounds.element_type must allow these descriptors; arrays of STRING(n) work.
- Literal.type_name expands to TypeSpec|None. Quoted literals become Literal(str,loc,
  StringType(max(1,len(decoded))),raw_text optional), normalized for NUL by check_value.
- Single quotes preserve case; dollar escapes case-insensitive: $$, $', $L/$N (LF), $R (CR),
  $T (tab), $P (form feed), $hh (exactly two hex digits, Latin-1 byte). STRING#'text' allowed.
- Empty text and comment-like text inside quotes allowed. Raw CR/LF, unterminated quotes,
  malformed escapes, non-Latin-1 literals and double-quoted/WSTRING/UTF8 literals rejected
  with source location. Long literals capped by StringType's max capacity.
- Calls in declaration constants remain rejected. Text literal/constants/comparisons work.
  Named-capacity dependency cycles, mutable values, BOOL/float/enum capacities reject cleanly.

## Text functions (named or positional, existing binding rules)
Each text argument is passed through STRING(255), so only its first 255 bytes before NUL
are processed. Every text result is STRING(255), clipped after the operation. LEN/FIND return
INT. Numeric parameters accept integer types/untyped integers (not BOOL), checked to INT
range at execution and must be nonnegative; positions for MID/DELETE/REPLACE must be >=1.
Out-of-range values raise ExecutionError through the normal checked runtime policy.
Exact signatures:
- LEN(STR): length.
- LEFT(STR,SIZE), RIGHT(STR,SIZE): first/last SIZE; zero -> ''; excessive size -> whole text.
- MID(STR,LEN,POS): LEN bytes starting at 1-based POS; beyond end -> ''.
- CONCAT(STR1,STR2): join two strings.
- FIND(STR1,STR2): first match, 1-based; missing -> 0; empty needle -> 1.
- INSERT(STR1,STR2,POS): insert after POS bytes; 0 -> prepend; beyond end -> append.
- DELETE(STR,LEN,POS): remove LEN from 1-based POS; beyond end -> unchanged.
- REPLACE(STR1,STR2,L,P): replace L bytes from 1-based P with all STR2;
  beyond end -> append; L=0 -> insert before P.
Profiles for invalid/out-of-bounds positions are explicit choices; do not claim full vendor
compatibility for undocumented corners.

## Basic conversion contract
Supported between STRING and BOOL plus INT/UINT/DINT/UDINT/BYTE/WORD/DWORD, using
X_TO_STRING, STRING_TO_X and generic TO_STRING/TO_X. Existing numeric conversions stay.
- TO_STRING/string-to-string returns STRING(255); typed numeric source converts/checks
  using existing numeric source behavior first. BOOL emits TRUE/FALSE; integers signed
  base-10 without leading zeros. Untyped INTEGER may be converted with TO_STRING.
- STRING_TO_BOOL: only exact 'TRUE' or 'true' -> True, all other text -> False (vendor rule).
- Integer parsing accepts ONLY complete decimal digits with optional leading +/- and
  underscores strictly between digits. No whitespace, suffixes, radix prefixes, floats,
  empties or non-ASCII digits. Arbitrarily long digits must produce a controlled error,
  never leak Python integer-conversion capacity errors. Leading zeros may be arbitrarily
  many within storage cap; strip before converting. Check destination range; no wrap.
- This intentionally stricter numeric parsing differs from permissive TwinCAT conversions.
  Invalid integer text and overflow -> ExecutionError and normal runtime faulting.
- Conversions never silently appear for REAL/LREAL/TIME/ENUM strings; reject at validation.

## Evidence and acceptance
Sources: Beckhoff STRING 2529410443.html, STRING Constants 2529327243.html, string conversion
2529074315.html (tc3_plc_intro); Tc2_Standard INSERT 74415627.html, FIND 74414091.html,
MID 74420235.html and linked LEN/LEFT/RIGHT/CONCAT/DELETE/REPLACE documentation.
Test lexer/types/functions/validation and actual ST execution including nested aggregates,
constant dependency projections, named calls, short-circuit selection, output bindings,
exact IN_OUT capacity, Latin-1 boundaries, NUL, truncation and atomic Python argument errors.
Examples: alarm formatting and SPEED=120 parsing; string in structured recipe, IN_OUT edits.
Full regression pytest, Ruff/reviewdog, format; independent review of changed files; build
0.7.0 wheel/sdist and Python3.11 installed-wheel examples. No publication or Git actions.
