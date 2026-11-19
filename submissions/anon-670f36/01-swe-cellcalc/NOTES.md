# Task 01 — cellcalc Notes

## Issue #1: Multi-letter columns (`AA`..`ZZZ`) broken
- **Root cause:** `cellcalc/refs.py` implemented `col_to_index` as base-26 with `'A' == 0` (plus a trailing `+ 1`), causing leading `'A'`s to collapse (`"AA"` -> `1 == "A"`), and implemented `index_to_col` with `divmod(idx, 26)` and `rem - 1`, producing `'A@'` for `26`.
- **Fix:** Switched both functions in `cellcalc/refs.py` to standard bijective base-26 (`ord(ch) - ord("A") + 1` per letter in `col_to_index`, and `divmod(idx - 1, 26)` in `index_to_col`), and added ASCII validation (`col.isascii()`) in `col_to_index`.
- **Verification:** `tests/test_issues.py::Issue1MultiLetterColumnsTests` verifies boundary conversions (`A`, `Z`, `AA`, `AZ`, `BA`, `ZZ`, `AAA`, `ZZZ`), 1..1999 roundtrips, and `Sheet` formulas/ranges across multi-letter columns.

## Issue #2: Operator precedence and associativity (`-2^2`, `2^3^2`)
- **Root cause:** In `cellcalc/parser.py`, `parse_binary` always called `parse_unary` before checking binary operators (so `-2^2` parsed as `(-2)^2`), and all binary operators used `min_prec = PRECEDENCE[op]` (making `^` left-associative).
- **Fix:** Set `PRECEDENCE["^"] = 6`, `UNARY_PRECEDENCE = 5`, and `RIGHT_ASSOC = {"^"}` in `Parser.parse_binary`, parsing prefix `+`/`-` at precedence level 5 and passing `PRECEDENCE[op] - 1` for right-associative `^`. This preserves `-2^2 = -4`, `2^3^2 = 512`, and `2^-1 = 0.5`. Also mapped `ValueError` from invalid refs (e.g., `A0`) inside formulas to `FormulaSyntaxError`.
- **Verification:** `tests/test_issues.py::Issue2PrecedenceTests` checks `-2^2`, `+2^2`, `--2^2`, `(-2)^2`, `2^3^2`, `2^-1`, `-2^-2`, `2^-2^2`, `1-2^2`, `2*-3^2`, and `=A0`.

## Issue #3: Stale values after edits
- **Root cause:** `Sheet._affected_in_order` in `cellcalc/sheet.py` traversed `_dependents` using BFS ordered by cell coordinates `(col, row)`, which can evaluate a downstream cell (`A3`) before an upstream dependency (`C5`) located further right/down.
- **Fix:** Replaced BFS ordering with topological evaluation over strongly connected components (`_sccs_postorder` using iterative Tarjan's algorithm, reversed in `_recalculate`). Because Tarjan pops SCCs in reverse topological order, reversing evaluates every upstream dependency/SCC before any cell depending on it, regardless of sheet coordinates, while marking cyclic SCCs as `#CYCLE!`.
- **Verification:** `tests/test_issues.py::Issue3RecalculationOrderTests` tests the reported diamond graph and multi-path reversed-coordinate DAGs.

## Issue #4: Persistent `#CYCLE!` after editing or clearing formulas
- **Root cause:** `Sheet.set` overwrote `self._formulas[key]` without removing `key` from `self._dependents[d]` for `d` in the previous formula's dependencies, leaving phantom edges in the dependency graph.
- **Fix:** In `Sheet.set`, before inserting new content (and only after parsing/literal validation succeeds so errors still leave the sheet unchanged), remove `key` from `self._dependents[d]` for all dependencies of `old_formula` (pruning empty sets).
- **Verification:** `tests/test_issues.py::Issue4CycleCleanupTests` tests overwriting a cyclic/pseudo-cyclic formula with a literal, breaking a multi-cell cycle, clearing a cell in a cycle, introducing and breaking a cycle with downstream cells, and `IF` untaken branch behavior.

## Issue #5: `SUM` / aggregates over ranges with text or booleans
- **Root cause:** `Evaluator._numbers` in `cellcalc/evaluator.py` only skipped `None` for range members, passing strings (causing `TypeError` in `sum()`) and booleans (`True` treated as `1` via Python's `int` subclass) into `nums`.
- **Fix:** In `Evaluator._numbers`, for `from_range=True` members, only accept numeric values (`isinstance(v, (int, float)) and not isinstance(v, bool)`), ignoring `None`, `str`, and `bool` while still propagating `ErrorValue`s. Direct arguments continue to use `to_number`.
- **Verification:** `tests/test_issues.py::Issue5AggregateRangeTests` covers `SUM`/`AVERAGE`/`MIN`/`MAX` over mixed numbers, text, booleans, empty cells, empty/text-only ranges, direct arguments, and error propagation.

## Issue #6: Implement `Sheet.copy_cell(src, dst)`
- **Design & assumptions:**
  - Non-formula cells copy `self._literals.get(src_key)` via `self.set(dst, ...)` (so empty `src` clears `dst`, and literals keep their exact stored value).
  - For formula cells, `_shift_formula` tokenizes `self._formulas[src_key].text` with `keep_whitespace=True` so spacing, function casing, identifiers, and string literals (including `"A1"`) are preserved byte-for-byte.
  - Single `REF` tokens shift relative components by `(dst.col - src.col, dst.row - src.row)` and format canonically (`format_ref`, uppercase letters, `$` preserved).
  - Range sequences (`REF [WS] COLON [WS] REF`) shift both endpoints independently; if either endpoint lands before column `A` (`< 1`), past `ZZZ` (`> 18278`, since 4-letter refs are outside the supported `A..ZZZ` column grammar), or before row `1` (`< 1`), the entire range is replaced by a single `#REF!`. Single out-of-bounds refs likewise become `#REF!`.
  - The rewritten formula (or literal/`None`) is applied via `self.set(dst, ...)` so dependency updates and recalculation behave identically to `set`.
- **Verification:** `tests/test_issues.py::Issue6CopyCellTests` checks literals (`0`, `False`, `True`, text, empty), `$` combinations, same-cell canonicalization, whitespace/casing/string preservation, single and range `#REF!` replacements, `> ZZZ` boundary, and downstream recalculation.

## Test Summary
Ran `D:\_APPLICATION\Python\python-3.11.9\python.exe -m unittest discover -s tests -t . -v` inside `submissions/anon-670f36/01-swe-cellcalc/project`: all 33 tests (14 original + 19 new) passed.
