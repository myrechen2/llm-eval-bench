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
from .refs import MAX_COL, CellRef, addr_to_key, format_ref, parse_ref
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
                deps_set = self._dependents.get(d)
                if deps_set is not None:
                    deps_set.discard(key)
                    if not deps_set:
                        del self._dependents[d]
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
            rewritten = _shift_formula(self._formulas[src_key].text, dcol, drow)
            self.set(dst, "=" + rewritten)
        else:
            self.set(dst, self._literals.get(src_key))

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
        for key in cyclic:
            if key in self._formulas:
                self._values[key] = E.CYCLE
        for key in self._affected_in_order(start, exclude=cyclic):
            if key in self._formulas:
                self._values[key] = self._evaluate(key)

    def _affected_in_order(
        self, start: Key, exclude: set[Key] | frozenset[Key] = frozenset()
    ) -> list[Key]:
        """Cells reachable from ``start`` (excluding ``exclude``) in topological order."""
        reachable: set[Key] = {start}
        bfs = deque([start])
        while bfs:
            key = bfs.popleft()
            for dep in self._dependents.get(key, ()):
                if dep not in reachable:
                    reachable.add(dep)
                    bfs.append(dep)

        nodes = reachable - exclude
        indeg: dict[Key, int] = {k: 0 for k in nodes}
        for u in nodes:
            for v in self._dependents.get(u, ()):
                if v in indeg:
                    indeg[v] += 1

        queue = deque(sorted(k for k, deg in indeg.items() if deg == 0))
        order: list[Key] = []
        while queue:
            u = queue.popleft()
            order.append(u)
            for v in sorted(self._dependents.get(u, ())):
                if v in indeg:
                    indeg[v] -= 1
                    if indeg[v] == 0:
                        queue.append(v)
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


def _shift_ref(ref: CellRef, dcol: int, drow: int) -> Optional[CellRef]:
    col = ref.col if ref.col_abs else ref.col + dcol
    row = ref.row if ref.row_abs else ref.row + drow
    if col < 1 or row < 1 or col > MAX_COL:
        return None
    return CellRef(col, row, ref.col_abs, ref.row_abs)


def _shift_formula(text: str, dcol: int, drow: int) -> str:
    """Shift relative references in ``text`` while preserving everything else byte-for-byte."""
    tokens = tokenize(text, keep_whitespace=True)
    out: list[str] = []
    i = 0
    n = len(tokens) - 1  # exclude EOF
    while i < n:
        tok = tokens[i]
        if tok.type != "REF":
            out.append(tok.text)
            i += 1
            continue

        # Check for a range `REF [WS...] : [WS...] REF`
        j = i + 1
        while j < n and tokens[j].type == "WS":
            j += 1
        if j < n and tokens[j].type == "COLON":
            k = j + 1
            while k < n and tokens[k].type == "WS":
                k += 1
            if k < n and tokens[k].type == "REF":
                start = _shift_ref(parse_ref(tok.text), dcol, drow)
                end = _shift_ref(parse_ref(tokens[k].text), dcol, drow)
                if start is None or end is None:
                    out.append("#REF!")
                else:
                    out.append(format_ref(start))
                    out.extend(tokens[m].text for m in range(i + 1, k))
                    out.append(format_ref(end))
                i = k + 1
                continue

        shifted = _shift_ref(parse_ref(tok.text), dcol, drow)
        out.append("#REF!" if shifted is None else format_ref(shifted))
        i += 1
    return "".join(out)


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
