"""AST evaluation.

Value model
-----------
A cell value is one of: ``None`` (empty), ``float``, ``str``, ``bool`` or
``ErrorValue``. Numbers are always floats.

Coercion rules used by arithmetic (``+ - * / ^`` and unary ``+ -``):
  * empty -> 0, True -> 1, False -> 0
  * text  -> ``#VALUE!``
``&`` concatenates the text form of both operands (empty -> "", numbers use
``format_number``, booleans -> "TRUE"/"FALSE").
"""
from __future__ import annotations

import math
from typing import Callable, Iterable

from . import errors as E
from .errors import ErrorValue
from .parser import Binary, Bool, Call, ErrorLit, Name, Node, Number, Range, Ref, String, Unary
from .refs import CellRef

Value = object  # None | float | str | bool | ErrorValue
Lookup = Callable[[tuple[int, int]], Value]


def format_number(x: float) -> str:
    if x == int(x) and abs(x) < 1e16:
        return str(int(x))
    return repr(x)


def to_text(v: Value) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "TRUE" if v else "FALSE"
    if isinstance(v, float):
        return format_number(v)
    return str(v)


def to_number(v: Value) -> float | ErrorValue:
    if isinstance(v, ErrorValue):
        return v
    if v is None:
        return 0.0
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    return E.VALUE


def to_bool(v: Value) -> bool | ErrorValue:
    if isinstance(v, ErrorValue):
        return v
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    s = str(v).upper()
    if s in ("TRUE", "FALSE"):
        return s == "TRUE"
    return E.VALUE


def range_keys(start: CellRef, end: CellRef) -> list[tuple[int, int]]:
    c1, c2 = sorted((start.col, end.col))
    r1, r2 = sorted((start.row, end.row))
    return [(c, r) for r in range(r1, r2 + 1) for c in range(c1, c2 + 1)]


class Evaluator:
    def __init__(self, lookup: Lookup):
        self.lookup = lookup

    # ------------------------------------------------------------------ core
    def eval(self, node: Node) -> Value:
        if isinstance(node, Number):
            return node.value
        if isinstance(node, String):
            return node.value
        if isinstance(node, Bool):
            return node.value
        if isinstance(node, ErrorLit):
            return node.value
        if isinstance(node, Name):
            return E.NAME
        if isinstance(node, Ref):
            return self.lookup(node.ref.key)
        if isinstance(node, Range):
            # A bare range outside of a function call is not a scalar value.
            return E.VALUE
        if isinstance(node, Unary):
            v = to_number(self.eval(node.operand))
            if isinstance(v, ErrorValue):
                return v
            return -v if node.op == "-" else v
        if isinstance(node, Binary):
            return self.eval_binary(node)
        if isinstance(node, Call):
            return self.eval_call(node)
        raise TypeError(f"unknown node {node!r}")  # pragma: no cover

    def eval_binary(self, node: Binary) -> Value:
        a = self.eval(node.left)
        b = self.eval(node.right)
        if isinstance(a, ErrorValue):
            return a
        if isinstance(b, ErrorValue):
            return b
        op = node.op
        if op == "&":
            return to_text(a) + to_text(b)
        if op in ("=", "<>", "<", ">", "<=", ">="):
            return compare(op, a, b)
        x, y = to_number(a), to_number(b)
        if isinstance(x, ErrorValue):
            return x
        if isinstance(y, ErrorValue):
            return y
        if op == "+":
            return x + y
        if op == "-":
            return x - y
        if op == "*":
            return x * y
        if op == "/":
            return E.DIV0 if y == 0 else x / y
        if op == "^":
            try:
                r = x ** y
            except (OverflowError, ZeroDivisionError):
                return E.NUM
            if isinstance(r, complex) or math.isinf(r) or math.isnan(r):
                return E.NUM
            return float(r)
        raise ValueError(f"unknown operator {op}")  # pragma: no cover

    # ------------------------------------------------------------- functions
    def _arg_values(self, args: Iterable[Node]) -> list[tuple[Value, bool]]:
        """Evaluate arguments, expanding ranges.

        Returns (value, from_range) pairs so aggregate functions can treat
        range members and direct arguments differently.
        """
        out: list[tuple[Value, bool]] = []
        for a in args:
            if isinstance(a, Range):
                for k in range_keys(a.start, a.end):
                    out.append((self.lookup(k), True))
            else:
                out.append((self.eval(a), False))
        return out

    def _numbers(self, args: Iterable[Node]) -> list[float] | ErrorValue:
        """Collect numeric arguments for SUM/AVERAGE/MIN/MAX.

        Direct arguments are coerced with ``to_number`` (so a direct text
        argument is #VALUE!). Range members that are empty, text or boolean
        are skipped.
        """
        nums: list[float] = []
        for v, from_range in self._arg_values(args):
            if isinstance(v, ErrorValue):
                return v
            if from_range:
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    nums.append(float(v))
                continue
            n = to_number(v)
            if isinstance(n, ErrorValue):
                return n
            nums.append(n)
        return nums

    def eval_call(self, node: Call) -> Value:
        name, args = node.name, node.args
        if name in ("SUM", "AVERAGE", "MIN", "MAX"):
            nums = self._numbers(args)
            if isinstance(nums, ErrorValue):
                return nums
            if name == "SUM":
                return float(sum(nums))
            if not nums:
                return E.DIV0 if name == "AVERAGE" else 0.0
            if name == "AVERAGE":
                return sum(nums) / len(nums)
            return float(min(nums) if name == "MIN" else max(nums))
        if name == "COUNT":
            # Counts numeric values (not text, not booleans, not empty); errors are ignored.
            return float(
                sum(1 for v, _ in self._arg_values(args)
                    if isinstance(v, float) and not isinstance(v, bool))
            )
        if name == "IF":
            if len(args) not in (2, 3):
                return E.VALUE
            cond = to_bool(self.eval(args[0]))
            if isinstance(cond, ErrorValue):
                return cond
            if cond:
                return self.eval(args[1])
            return self.eval(args[2]) if len(args) == 3 else False
        if name in ("AND", "OR"):
            if not args:
                return E.VALUE
            vals = []
            for v, from_range in self._arg_values(args):
                if from_range and (v is None or isinstance(v, str)):
                    continue
                b = to_bool(v)
                if isinstance(b, ErrorValue):
                    return b
                vals.append(b)
            if not vals:
                return E.VALUE
            return all(vals) if name == "AND" else any(vals)
        if name == "NOT":
            if len(args) != 1:
                return E.VALUE
            b = to_bool(self.eval(args[0]))
            return b if isinstance(b, ErrorValue) else (not b)
        if name == "ABS":
            if len(args) != 1:
                return E.VALUE
            x = to_number(self.eval(args[0]))
            return x if isinstance(x, ErrorValue) else abs(x)
        if name == "ROUND":
            if len(args) not in (1, 2):
                return E.VALUE
            x = to_number(self.eval(args[0]))
            d = to_number(self.eval(args[1])) if len(args) == 2 else 0.0
            if isinstance(x, ErrorValue):
                return x
            if isinstance(d, ErrorValue):
                return d
            return round_half_away(x, int(d))
        if name == "CONCAT":
            parts = []
            for v, _ in self._arg_values(args):
                if isinstance(v, ErrorValue):
                    return v
                parts.append(to_text(v))
            return "".join(parts)
        if name == "LEN":
            if len(args) != 1:
                return E.VALUE
            v = self.eval(args[0])
            return v if isinstance(v, ErrorValue) else float(len(to_text(v)))
        return E.NAME


def round_half_away(x: float, digits: int) -> float:
    """Spreadsheet-style rounding: halves round away from zero."""
    m = 10.0 ** digits
    y = abs(x) * m
    r = math.floor(y + 0.5 + 1e-9)
    return math.copysign(r / m, x) if r else 0.0


def compare(op: str, a: Value, b: Value) -> bool:
    """Compare two scalar values.

    Ordering across types: numbers < text < booleans (like common
    spreadsheets). Empty is treated as 0 when compared to a number, "" when
    compared to text and FALSE when compared to a boolean. Text comparison is
    case-insensitive.
    """
    a, b = _align_empty(a, b), _align_empty(b, a)

    def rank(v: Value) -> int:
        if isinstance(v, bool):
            return 2
        if isinstance(v, str):
            return 1
        return 0

    ra, rb = rank(a), rank(b)
    if ra != rb:
        ka, kb = ra, rb
    elif ra == 1:
        ka, kb = str(a).lower(), str(b).lower()
    else:
        ka, kb = a, b  # type: ignore[assignment]
    return {
        "=": ka == kb,
        "<>": ka != kb,
        "<": ka < kb,
        ">": ka > kb,
        "<=": ka <= kb,
        ">=": ka >= kb,
    }[op]


def _align_empty(v: Value, other: Value) -> Value:
    if v is not None:
        return v
    if isinstance(other, bool):
        return False
    if isinstance(other, str):
        return ""
    return 0.0
