# Task 01: cellcalc Notes

## Issue #1: Columns after Z are broken
- **Root cause**: In `cellcalc/refs.py`, `col_to_index` computed `n * 26 + (ord(ch) - ord("A"))` and added `1` only at the end, which is standard 0-based base-26 instead of bijective base-26 (so `"AA"` evaluated to `0*26 + 0 + 1 = 1`). Similarly, `index_to_col` used `divmod(idx, 26)` and `rem - 1`, failing when `rem == 0` (e.g. `26 -> 'A@'`).
- **Fix**: Updated `col_to_index` to accumulate `n = n * 26 + (ord(ch) - ord("A") + 1)` (with ASCII alpha check) and `index_to_col` to use `divmod(idx - 1, 26)` and `chr(ord("A") + rem)`.
- **Verification**: Added unit tests in `tests/test_issues.py` (`Issue1ColumnTests`) testing `A..ZZZ` round-trips and sheet operations on `AA1` and `ZZZ5`.

## Issue #2: `-2^2` evaluates to 4
- **Root cause**: In `cellcalc/parser.py`, `parse_binary` always called `parse_unary()` for operands, giving unary `+`/`-` higher precedence than `^` (which also had precedence 5 and was left-associative because `parse_binary` passed `PRECEDENCE[op]` instead of `PRECEDENCE[op] - 1`).
- **Fix**: Set `PRECEDENCE["^"] = 6`, `UNARY_PRECEDENCE = 5`, `RIGHT_ASSOC = {"^"}`, and handled prefix `+`/`-` directly inside `parse_binary` using `self.parse_binary(UNARY_PRECEDENCE)`, with `prec - 1` for right-associative `^`.
- **Verification**: Added `Issue2PrecedenceTests` covering `-2^2`, `2^3^2`, `2^-1`, `-2^-2`, `(-2)^2`, `+2^3`, and `--2`.

## Issue #3: Some cells show stale values after an edit
- **Root cause**: `Sheet._affected_in_order` in `cellcalc/sheet.py` used BFS order sorted by `(col, row)`, which could evaluate a downstream cell (e.g. `A3`) before an intermediate dependency (`C5`).
- **Fix**: Replaced BFS ordering in `_affected_in_order` with Kahn's topological sort over the subgraph of non-cyclic affected formula cells, after setting all `cyclic` cells to `#CYCLE!`.
- **Verification**: Added `Issue3TopoOrderTests` reproducing the diamond dependency from the issue.

## Issue #4: `#CYCLE!` that never goes away
- **Root cause**: `Sheet.set` popped `self._formulas[key]` without removing `key` from `self._dependents[d]` for `d in old_formula.deps`, leaving stale dependency edges in the graph.
- **Fix**: In `Sheet.set`, before replacing or clearing a cell, remove `key` from `self._dependents[d]` for every `d` in the previous formula's `deps` (and prune empty sets).
- **Verification**: Added `Issue4CycleCleanupTests` testing overwriting a formula with a literal, breaking a 2-cell cycle, and clearing a cell in a cycle.

## Issue #5: `SUM` over a range containing text crashes
- **Root cause**: `Evaluator._numbers` in `cellcalc/evaluator.py` only skipped `None` for range members (`from_range=True`), passing `str` (causing `TypeError` in `sum()`) and `bool` (counted as `1.0`/`0.0` because `bool` subclasses `int`).
- **Fix**: Updated `Evaluator._numbers` to skip `v is None or isinstance(v, (str, bool))` when `from_range` is `True`.
- **Verification**: Added `Issue5AggregateRangeTests` testing `SUM`, `AVERAGE`, `MIN`, `MAX` on ranges with text/booleans/empty cells, plus direct-argument coercion.

## Issue #6: Feature request: `Sheet.copy_cell(src, dst)`
- **Fix**: Implemented `Sheet.copy_cell` in `cellcalc/sheet.py`. Empty `src` clears `dst`; literal `src` copies the literal via `self.set`; formula `src` uses `tokenize(text, keep_whitespace=True)` to rewrite `REF` and `REF:REF` range tokens with `_shift_ref` and `format_ref` while preserving all other tokens (whitespace, function casing, string literals) byte-for-byte. Out-of-bounds shifted references (`col < 1` or `row < 1`) are replaced by `#REF!` (or a single `#REF!` for an out-of-bounds range), then applied via `self.set`.
- **Verification**: Added `Issue6CopyCellTests` and ran `py -m unittest discover -s tests -t . -v` (all 27 tests pass).
