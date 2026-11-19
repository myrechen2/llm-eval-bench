"""Formula tokenizer.

Every token keeps its exact source slice (``text``) and start offset (``pos``)
so callers can rebuild or rewrite the original formula text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .errors import FormulaSyntaxError

ERROR_LITERALS = ("#DIV/0!", "#VALUE!", "#REF!", "#NAME?", "#CYCLE!", "#NUM!")

_TOKEN_SPEC = [
    ("WS", r"[ \t]+"),
    ("ERROR", "|".join(re.escape(e) for e in ERROR_LITERALS)),
    ("NUMBER", r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"),
    ("STRING", r'"(?:[^"]|"")*"'),
    # A cell reference must not be directly followed by '(' (that is a function
    # call such as LOG10(...)) or by more identifier characters.
    ("REF", r"\$?[A-Za-z]{1,3}\$?[0-9]+(?![A-Za-z0-9_.(])"),
    ("IDENT", r"[A-Za-z_][A-Za-z0-9_.]*"),
    ("OP", r"<>|<=|>=|[-+*/^&=<>]"),
    ("LPAREN", r"\("),
    ("RPAREN", r"\)"),
    ("COMMA", r","),
    ("COLON", r":"),
]
_MASTER_RE = re.compile("|".join(f"(?P<{name}>{pat})" for name, pat in _TOKEN_SPEC))


@dataclass(frozen=True)
class Token:
    type: str
    text: str
    pos: int

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Token({self.type}, {self.text!r}, {self.pos})"


def tokenize(source: str, *, keep_whitespace: bool = False) -> list[Token]:
    """Split ``source`` (without the leading '=') into tokens.

    The returned list always ends with an ``EOF`` token. Whitespace tokens are
    dropped unless ``keep_whitespace`` is true, in which case concatenating the
    ``text`` of all tokens reproduces ``source`` exactly.
    """
    tokens: list[Token] = []
    pos = 0
    while pos < len(source):
        m = _MASTER_RE.match(source, pos)
        if not m:
            raise FormulaSyntaxError(f"unexpected character {source[pos]!r} at {pos}")
        kind = m.lastgroup
        assert kind is not None
        if kind != "WS" or keep_whitespace:
            tokens.append(Token(kind, m.group(), pos))
        pos = m.end()
    tokens.append(Token("EOF", "", len(source)))
    return tokens
