# Open issues for cellcalc 0.3.1

> 以下 6 个 issue 都需要处理。#1–#5 是用户报告的 bug,#6 是功能需求。
> 行为规范以 `project/README.md` 为准。

---

## #1 Columns after Z are broken

**Reporter:** finance-team

We have sheets wider than 26 columns. Writing to `AA1` overwrites `A1`:

```python
s = Sheet()
s.set("A1", 1)
s.set("AA1", 100)
s.get("A1")   # 100.0  (expected 1.0)
```

Also `cellcalc.refs.index_to_col(26)` returns `'A@'` instead of `'Z'`.
Every column name up to 3 letters (`A` .. `ZZZ`) should work everywhere (`set`, `get`, formulas, ranges).

---

## #2 `-2^2` evaluates to 4

**Reporter:** @mathteacher

The README says `^` has the highest precedence and is right-associative, but:

```python
=-2^2     -> 4      (expected -4)
=2^3^2    -> 64     (expected 512)
```

Please make the parser follow the precedence table in the README exactly.

---

## #3 Some cells show stale values after an edit

**Reporter:** ops

```python
s = Sheet()
s.set("A1", 1)
s.set("B2", "=A1*2")
s.set("C5", "=B2+1")
s.set("A3", "=B2+C5")
s.get("A3")        # 5.0  ok
s.set("A1", 10)
s.get("A3")        # 23.0 ??? expected 41.0 (B2=20, C5=21)
```

It seems to depend on where cells are on the sheet. Values must be correct after every `set`, no matter how the dependency graph looks.

---

## #4 `#CYCLE!` that never goes away

**Reporter:** @jlee

```python
s = Sheet()
s.set("A1", "=B1")
s.set("A1", 1)          # A1 no longer references B1
s.set("B1", "=A1")
s.get("B1")             # #CYCLE!  (expected 1.0)
```

Same thing after breaking a real cycle: the cells keep showing `#CYCLE!`. Editing or clearing a formula must forget its old references.

---

## #5 `SUM` over a range containing text crashes

**Reporter:** finance-team

```python
s.set("B1", 1); s.set("B2", "n/a"); s.set("B3", 2)
s.set("C1", "=SUM(B1:B3)")   # TypeError: unsupported operand type(s) ...
```

Expected `3.0`. See README "Aggregates and ranges" for the intended behaviour (it also says booleans inside ranges are ignored — currently `TRUE` in a range is counted as 1).

---

## #6 Feature request: `Sheet.copy_cell(src, dst)`

**Reporter:** product

`copy_cell` currently raises `NotImplementedError`. Implement spreadsheet-style copy/paste of a single cell:

1. If `src` holds a literal, `dst` gets the same literal. If `src` is empty, `dst` is cleared.
2. If `src` holds a formula, `dst` gets the formula with every **relative** reference shifted by the offset `(dst.col - src.col, dst.row - src.row)`.
   * A `$` freezes that component: `$A$1` never moves, `$A1` only moves its row, `A$1` only moves its column.
   * Both endpoints of a range shift independently.
   * Shifted references are written in canonical form (upper-case letters, `$` markers kept), e.g. `a1` copied one row down becomes `A2`.
   * Everything else in the formula text (spacing, function-name casing, string literals — even ones that look like `"A1"`) is kept **byte-for-byte**.
3. If a shifted reference would land before column `A` or row `1`, that reference is replaced by `#REF!` (for a range: the whole `X:Y` is replaced by a single `#REF!`). The cell then evaluates to `#REF!` through normal propagation.
4. `dst` participates in recalculation exactly as if its content had been entered with `set`.

```python
s.set("B1", "=$A$1+A1")
s.copy_cell("B1", "C3")
s.get_formula("C3")      # "=$A$1+B3"

s.set("B2", "=A1+1")
s.copy_cell("B2", "A1")
s.get_formula("A1")      # "=#REF!+1"
```
