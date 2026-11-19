# cellcalc

A tiny spreadsheet formula engine (pure Python 3.10+, no dependencies).

```python
from cellcalc import Sheet

s = Sheet()
s.set("A1", 2)
s.set("B1", "=A1*10")
s.set("C1", "=SUM(A1:B1) & \" units\"")
s.get("C1")          # '22 units'
```

## Cell contents (`Sheet.set`)

| content                         | stored as |
|---------------------------------|-----------|
| `None` / `""`                   | clears the cell |
| `str` starting with `=`         | formula |
| `bool`                          | boolean |
| `int` / `float`                 | number (always `float`) |
| other `str`                     | number if it parses as a float, else text |

An invalid formula raises `FormulaSyntaxError` and leaves the sheet unchanged.

Values are recalculated eagerly: after any `set`, `get` returns up-to-date values for **every** cell.

## Formula language

* Numbers, strings (`"..."`, `""` escapes a quote), `TRUE` / `FALSE`, error literals (`#DIV/0!`, `#VALUE!`, `#REF!`, `#NAME?`, `#CYCLE!`, `#NUM!`).
* References `A1`, `$A$1`, `A$1`, `$A1` (case-insensitive), ranges `A1:C3`. Columns go `A..Z, AA..AZ, BA.. ZZ, AAA..` (up to 3 letters).
* Operators, from lowest to highest precedence:

  | precedence | operators | associativity |
  |---|---|---|
  | 1 | `= <> < > <= >=` | left |
  | 2 | `&` (text concat) | left |
  | 3 | `+ -` | left |
  | 4 | `* /` | left |
  | 5 | unary `-` `+` | prefix |
  | 6 | `^` | **right** |

  i.e. the usual math convention: `-2^2 = -4`, `2^3^2 = 2^(3^2) = 512`, `2^-1 = 0.5`.
* Functions: `SUM AVERAGE MIN MAX COUNT IF AND OR NOT ABS ROUND CONCAT LEN`. Unknown names give `#NAME?`.

### Aggregates and ranges

`SUM / AVERAGE / MIN / MAX` take any mix of ranges and direct arguments.

* Range members that are empty, text or boolean are **ignored**.
* Direct arguments are coerced like arithmetic operands (`TRUE` -> 1, text -> `#VALUE!`).
* `AVERAGE` of no numbers is `#DIV/0!`; `MIN`/`MAX` of no numbers is `0`.
* An error anywhere (range member or argument) propagates.

### Errors

Errors are values. Any operator or function receiving an error returns it (except `IF` branches that are not taken). A cell that is part of a reference cycle has the value `#CYCLE!`; cells depending on it get `#CYCLE!` through normal propagation. Once the cycle is broken every cell must show its normal value again.

## Running tests

```bash
python -m unittest discover -s tests -t .
```
