"""Recursive-descent / precedence-climbing parser producing a small AST."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from .errors import BY_CODE, ErrorValue, FormulaSyntaxError
from .refs import CellRef, parse_ref
from .tokenizer import Token, tokenize


# --------------------------------------------------------------------------- AST
@dataclass(frozen=True)
class Number:
    value: float


@dataclass(frozen=True)
class String:
    value: str


@dataclass(frozen=True)
class Bool:
    value: bool


@dataclass(frozen=True)
class ErrorLit:
    value: ErrorValue


@dataclass(frozen=True)
class Ref:
    ref: CellRef


@dataclass(frozen=True)
class Range:
    start: CellRef
    end: CellRef


@dataclass(frozen=True)
class Name:
    """An identifier that is not a function call (evaluates to #NAME?)."""

    name: str


@dataclass(frozen=True)
class Unary:
    op: str
    operand: "Node"


@dataclass(frozen=True)
class Binary:
    op: str
    left: "Node"
    right: "Node"


@dataclass(frozen=True)
class Call:
    name: str
    args: tuple["Node", ...]


Node = Union[Number, String, Bool, ErrorLit, Ref, Range, Name, Unary, Binary, Call]

# Binary operator precedence (higher binds tighter).
# Unary '+' and '-' have precedence 5, sitting below '^' (6).
PRECEDENCE = {
    "=": 1, "<>": 1, "<": 1, ">": 1, "<=": 1, ">=": 1,
    "&": 2,
    "+": 3, "-": 3,
    "*": 4, "/": 4,
    "^": 6,
}
UNARY_PRECEDENCE = 5
RIGHT_ASSOC = {"^"}


class Parser:
    def __init__(self, source: str):
        self.source = source
        self.tokens = tokenize(source)
        self.i = 0

    # -- helpers ------------------------------------------------------------
    @property
    def tok(self) -> Token:
        return self.tokens[self.i]

    def advance(self) -> Token:
        t = self.tokens[self.i]
        self.i += 1
        return t

    def expect(self, kind: str) -> Token:
        if self.tok.type != kind:
            raise FormulaSyntaxError(
                f"expected {kind} at {self.tok.pos}, found {self.tok.type} {self.tok.text!r}"
            )
        return self.advance()

    # -- grammar ------------------------------------------------------------
    def parse(self) -> Node:
        if self.tok.type == "EOF":
            raise FormulaSyntaxError("empty formula")
        node = self.parse_binary(0)
        if self.tok.type != "EOF":
            raise FormulaSyntaxError(f"unexpected {self.tok.text!r} at {self.tok.pos}")
        return node

    def parse_binary(self, min_prec: int) -> Node:
        left = self.parse_unary()
        while self.tok.type == "OP" and PRECEDENCE.get(self.tok.text, -1) > min_prec:
            op = self.advance().text
            prec = PRECEDENCE[op]
            next_min = prec - 1 if op in RIGHT_ASSOC else prec
            right = self.parse_binary(next_min)
            left = Binary(op, left, right)
        return left

    def parse_unary(self) -> Node:
        if self.tok.type == "OP" and self.tok.text in ("+", "-"):
            op = self.advance().text
            return Unary(op, self.parse_binary(UNARY_PRECEDENCE))
        return self.parse_primary()

    def parse_primary(self) -> Node:
        t = self.tok
        if t.type == "NUMBER":
            self.advance()
            return Number(float(t.text))
        if t.type == "STRING":
            self.advance()
            return String(t.text[1:-1].replace('""', '"'))
        if t.type == "ERROR":
            self.advance()
            return ErrorLit(BY_CODE[t.text])
        if t.type == "REF":
            self.advance()
            try:
                start = parse_ref(t.text)
            except ValueError as exc:
                raise FormulaSyntaxError(str(exc)) from exc
            if self.tok.type == "COLON":
                self.advance()
                end_tok = self.expect("REF")
                try:
                    end = parse_ref(end_tok.text)
                except ValueError as exc:
                    raise FormulaSyntaxError(str(exc)) from exc
                return Range(start, end)
            return Ref(start)
        if t.type == "IDENT":
            self.advance()
            upper = t.text.upper()
            if self.tok.type == "LPAREN":
                self.advance()
                args: list[Node] = []
                if self.tok.type != "RPAREN":
                    args.append(self.parse_binary(0))
                    while self.tok.type == "COMMA":
                        self.advance()
                        args.append(self.parse_binary(0))
                self.expect("RPAREN")
                return Call(upper, tuple(args))
            if upper in ("TRUE", "FALSE"):
                return Bool(upper == "TRUE")
            return Name(t.text)
        if t.type == "LPAREN":
            self.advance()
            node = self.parse_binary(0)
            self.expect("RPAREN")
            return node
        raise FormulaSyntaxError(f"unexpected {t.type} {t.text!r} at {t.pos}")


def parse_formula(source: str) -> Node:
    """Parse formula text *without* the leading '='."""
    return Parser(source).parse()


def iter_refs(node: Node):
    """Yield every Ref and Range node in the tree."""
    if isinstance(node, (Ref, Range)):
        yield node
    elif isinstance(node, Unary):
        yield from iter_refs(node.operand)
    elif isinstance(node, Binary):
        yield from iter_refs(node.left)
        yield from iter_refs(node.right)
    elif isinstance(node, Call):
        for a in node.args:
            yield from iter_refs(a)
