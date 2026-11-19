"""Error types.

* ``FormulaSyntaxError`` is a Python exception raised when a formula cannot be
  parsed. ``Sheet.set`` raises it and leaves the sheet unchanged.
* ``ErrorValue`` is a *cell value* (like ``#DIV/0!`` in a spreadsheet). Errors
  propagate: any operation or function that receives an error value as an
  operand returns that error (the left-most one wins).
"""
from __future__ import annotations

from dataclasses import dataclass


class FormulaSyntaxError(ValueError):
    pass


@dataclass(frozen=True)
class ErrorValue:
    code: str

    def __str__(self) -> str:
        return self.code


DIV0 = ErrorValue("#DIV/0!")
VALUE = ErrorValue("#VALUE!")
REF = ErrorValue("#REF!")
NAME = ErrorValue("#NAME?")
CYCLE = ErrorValue("#CYCLE!")
NUM = ErrorValue("#NUM!")

BY_CODE = {e.code: e for e in (DIV0, VALUE, REF, NAME, CYCLE, NUM)}
