"""The Sheet: stores cell contents, tracks dependencies, keeps values up to date.

Values are recalculated eagerly: after every ``set`` call, ``get`` returns
up-to-date values for every cell without further work.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Optional

from . import errors as E
from .evaluator import Evaluator, Value, range_keys
from .parser import Node, Range, Ref, iter_refs, parse_formula
from .refs import CellRef, addr_to_key, format_ref, parse_ref
from .tokenizer import tokenize

Key = tuple[int, int]


@dataclass
class _Formula:
    text: str          # formula text without the leading '='
    ast: Node
    deps: frozenset[Key]


class Sheet:
    def __init__(self) -> None:
        self._literals: dict[Key, Value] = {}
        self._formulas: dict[Key, _Formula] = {}
        self._values: dict[Key, Value] = {}            # cached values of formula cells
        self._dependents: dict[Key, set[Key]] = {}     # key -> formula cells that reference key

    # ------------------------------------------------------------ public API
    def set(self, addr: str, content: object) -> None:
        """Set a cell's content.

        * ``None`` or ``""``           -> clear the cell
        * ``str`` starting with ``=``  -> formula
        * ``bool``                     -> boolean literal
        * ``int`` / ``float``          -> number literal (stored as float)
        * other ``str``                -> number literal if it parses as a
                                          float, otherwise text literal

        Raises ``FormulaSyntaxError`` for an invalid formula (the sheet is left
        unchanged in that case).
        """
        key = addr_to_key(addr)
        formula: Optional[_Formula] = None
        if isinstance(content, str) and content.startswith("="):
            text = content[1:]
            ast = parse_formula(text)
            formula = _Formula(text, ast, frozenset(_collect_deps(ast)))

        self._literals.pop(key, None)
        old_formula = self._formulas.pop(key, None)
        if old_formula is not None:
            for d in old_formula.deps:
                deps = self._dependents.get(d)
                if deps is not None:
                    deps.discard(key)
                    if not deps:
                        self._dependents.pop(d, None)
        self._values.pop(key, None)

        if formula is not None:
            self._formulas[key] = formula
            for d in formula.deps:
                self._dependents.setdefault(d, set()).add(key)
        elif content is None or content == "":
            pass
        else:
            self._literals[key] = _literal(content)

        self._recalculate(key)

    def get(self, addr: str) -> Value:
        """Return the current value of a cell (None when empty)."""
        return self._value(addr_to_key(addr))

    def get_formula(self, addr: str) -> Optional[str]:
        """Return the formula text *including* the leading '=' or None."""
        f = self._formulas.get(addr_to_key(addr))
        return None if f is None else "=" + f.text

    def get_content(self, addr: str) -> object:
        """Return what was stored: formula text ('=...'), literal, or None."""
        key = addr_to_key(addr)
        if key in self._formulas:
            return "=" + self._formulas[key].text
        return self._literals.get(key)

    def copy_cell(self, src: str, dst: str) -> None:
        """Copy the content of ``src`` into ``dst`` (see ISSUES.md #6)."""
        src_key = addr_to_key(src)
        dst_key = addr_to_key(dst)
        if src_key in self._formulas:
            dcol = dst_key[0] - src_key[0]
            drow = dst_key[1] - src_key[1]
            shifted = _shift_formula(self._formulas[src_key].text, dcol, drow)
            self.set(dst, "=" + shifted)
        elif src_key in self._literals:
            self.set(dst, self._literals[src_key])
        else:
            self.set(dst, None)

    # -------------------------------------------------------------- internals
    def _value(self, key: Key) -> Value:
        if key in self._formulas:
            return self._values.get(key)
        return self._literals.get(key)

    def _evaluate(self, key: Key) -> Value:
        return Evaluator(self._value).eval(self._formulas[key].ast)

    def _recalculate(self, start: Key) -> None:
        """Recompute ``start`` and everything that (transitively) depends on it."""
        cyclic = self._cycle_members(start)
        for key in self._affected_in_order(start, cyclic):
            if key not in self._formulas:
                continue
            if key in cyclic:
                self._values[key] = E.CYCLE
            else:
                self._values[key] = self._evaluate(key)

    def _affected_in_order(self, start: Key, cyclic: set[Key]) -> list[Key]:
        """Cells reachable from ``start`` through dependents, in topological update order."""
        seen = {start}
        queue = deque([start])
        while queue:
            key = queue.popleft()
            for dep in sorted(self._dependents.get(key, ())):
                if dep not in seen:
                    seen.add(dep)
                    queue.append(dep)

        non_cyclic = seen - cyclic
        in_deg: dict[Key, int] = {u: 0 for u in non_cyclic}
        for u in non_cyclic:
            for v in self._dependents.get(u, ()):
                if v in non_cyclic:
                    in_deg[v] += 1

        ready = deque(sorted(u for u, d in in_deg.items() if d == 0))
        order: list[Key] = sorted(cyclic)
        while ready:
            u = ready.popleft()
            order.append(u)
            for v in sorted(self._dependents.get(u, ())):
                if v in non_cyclic:
                    in_deg[v] -= 1
                    if in_deg[v] == 0:
                        ready.append(v)
        return order

    def _cycle_members(self, start: Key) -> set[Key]:
        """Return the cells reachable from ``start`` that lie on a cycle.

        Uses Tarjan's strongly-connected-components algorithm on the dependents
        graph restricted to cells reachable from ``start``.
        """
        index: dict[Key, int] = {}
        low: dict[Key, int] = {}
        on_stack: set[Key] = set()
        stack: list[Key] = []
        result: set[Key] = set()
        counter = 0

        # iterative Tarjan to avoid recursion limits on long chains
        work: list[tuple[Key, list[Key]]] = []

        def push(node: Key) -> None:
            nonlocal counter
            index[node] = low[node] = counter
            counter += 1
            stack.append(node)
            on_stack.add(node)
            work.append((node, sorted(self._dependents.get(node, ()))))

        push(start)
        while work:
            node, children = work[-1]
            if children:
                child = children.pop()
                if child not in index:
                    push(child)
                elif child in on_stack:
                    low[node] = min(low[node], index[child])
                continue
            work.pop()
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
            if low[node] == index[node]:
                comp = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == node:
                        break
                if len(comp) > 1 or node in self._dependents.get(node, ()):
                    result.update(comp)
        return result


def _shift_ref(text: str, dcol: int, drow: int) -> Optional[str]:
    ref = parse_ref(text)
    new_col = ref.col if ref.col_abs else ref.col + dcol
    new_row = ref.row if ref.row_abs else ref.row + drow
    if new_col < 1 or new_row < 1:
        return None
    return format_ref(CellRef(new_col, new_row, ref.col_abs, ref.row_abs))


def _shift_formula(text: str, dcol: int, drow: int) -> str:
    tokens = tokenize(text)
    replacements: list[tuple[int, int, str]] = []
    i = 0
    n = len(tokens)
    while i < n:
        t = tokens[i]
        if t.type == "EOF":
            break
        if t.type == "REF":
            if i + 2 < n and tokens[i + 1].type == "COLON" and tokens[i + 2].type == "REF":
                t2 = tokens[i + 2]
                s1 = _shift_ref(t.text, dcol, drow)
                s2 = _shift_ref(t2.text, dcol, drow)
                if s1 is None or s2 is None:
                    replacements.append((t.pos, t2.pos + len(t2.text), "#REF!"))
                else:
                    replacements.append((t.pos, t.pos + len(t.text), s1))
                    replacements.append((t2.pos, t2.pos + len(t2.text), s2))
                i += 3
                continue
            s1 = _shift_ref(t.text, dcol, drow)
            replacements.append((t.pos, t.pos + len(t.text), "#REF!" if s1 is None else s1))
        i += 1

    if not replacements:
        return text
    parts: list[str] = []
    cursor = 0
    for start_pos, end_pos, rep in replacements:
        parts.append(text[cursor:start_pos])
        parts.append(rep)
        cursor = end_pos
    parts.append(text[cursor:])
    return "".join(parts)


def _collect_deps(ast: Node) -> set[Key]:
    deps: set[Key] = set()
    for r in iter_refs(ast):
        if isinstance(r, Ref):
            deps.add(r.ref.key)
        elif isinstance(r, Range):
            deps.update(range_keys(r.start, r.end))
    return deps


def _literal(content: object) -> Value:
    if isinstance(content, bool):
        return content
    if isinstance(content, (int, float)):
        return float(content)
    if isinstance(content, str):
        try:
            return float(content)
        except ValueError:
            return content
    raise TypeError(f"unsupported cell content: {content!r}")
