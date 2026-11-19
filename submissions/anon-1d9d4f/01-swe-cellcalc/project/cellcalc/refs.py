"""Cell reference helpers: column letters <-> indices, parsing and formatting refs.

Columns use spreadsheet-style bijective base-26 letters: A=1, B=2, ..., Z=26,
AA=27, AB=28, ..., AZ=52, BA=53, ..., ZZ=702, AAA=703, ...
Rows are 1-based.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_COL_LETTERS = 3

_REF_RE = re.compile(r"^(\$?)([A-Za-z]{1,3})(\$?)([0-9]+)$")


def col_to_index(col: str) -> int:
    """Convert column letters to a 1-based column index ('A' -> 1, 'AA' -> 27)."""
    if not col or not col.isascii() or not col.isalpha():
        raise ValueError(f"invalid column letters: {col!r}")
    n = 0
    for ch in col.upper():
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n


def index_to_col(idx: int) -> str:
    """Convert a 1-based column index to letters (1 -> 'A', 27 -> 'AA')."""
    if idx < 1:
        raise ValueError(f"column index must be >= 1, got {idx}")
    out = []
    while idx > 0:
        idx, rem = divmod(idx - 1, 26)
        out.append(chr(ord("A") + rem))
    return "".join(reversed(out))


@dataclass(frozen=True)
class CellRef:
    col: int
    row: int
    col_abs: bool = False
    row_abs: bool = False

    @property
    def key(self) -> tuple[int, int]:
        """Position key used by the sheet (absolute markers are ignored)."""
        return (self.col, self.row)

    def __str__(self) -> str:
        return format_ref(self)


def parse_ref(text: str) -> CellRef:
    """Parse 'B3', '$B3', 'B$3', '$B$3' (case-insensitive)."""
    m = _REF_RE.match(text.strip())
    if not m:
        raise ValueError(f"invalid cell reference: {text!r}")
    col_abs, letters, row_abs, digits = m.groups()
    row = int(digits)
    if row < 1:
        raise ValueError(f"row must be >= 1 in {text!r}")
    return CellRef(col_to_index(letters), row, bool(col_abs), bool(row_abs))


def format_ref(ref: CellRef) -> str:
    return (
        ("$" if ref.col_abs else "")
        + index_to_col(ref.col)
        + ("$" if ref.row_abs else "")
        + str(ref.row)
    )


def key_to_addr(key: tuple[int, int]) -> str:
    col, row = key
    return f"{index_to_col(col)}{row}"


def addr_to_key(addr: str) -> tuple[int, int]:
    return parse_ref(addr).key
