"""Showdown 데이터 파일(TypeScript 객체 리터럴)을 실행하지 않고 값만 읽는 파서.

문자열·숫자·불리언·null·배열·객체만 해석하고, 함수(메서드·화살표 함수)나 식은 건너뛴다.
"""
from __future__ import annotations

import re

_TOKEN = re.compile(r"""
    (?P<ws>\s+|//[^\n]*|/\*.*?\*/)
  | (?P<str>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)
  | (?P<num>-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)
  | (?P<id>[A-Za-z_$][\w$]*)
  | (?P<arrow>=>)
  | (?P<punct>[{}\[\]():,;?.<>=!&|+\-*/%^~@#])
""", re.X | re.S)

SKIP = object()


def tokenize(src: str) -> list[tuple[str, str]]:
    out, pos = [], 0
    while pos < len(src):
        m = _TOKEN.match(src, pos)
        if not m:
            out.append(("punct", src[pos]))
            pos += 1
            continue
        pos = m.end()
        kind = m.lastgroup
        if kind != "ws":
            out.append((kind, m.group()))
    return out


def _unquote(s: str) -> str:
    body = s[1:-1]
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), body)


class Parser:
    def __init__(self, tokens):
        self.t, self.i = tokens, 0

    def peek(self, k=0):
        j = self.i + k
        return self.t[j] if j < len(self.t) else ("eof", "")

    def next(self):
        tok = self.peek()
        self.i += 1
        return tok

    def skip_balanced(self):
        """현재 위치의 여는 괄호부터 짝이 맞는 닫는 괄호까지 건너뛴다."""
        depth = 0
        while True:
            _, v = self.next()
            if v in "([{":
                depth += 1
            elif v in ")]}":
                depth -= 1
                if depth == 0:
                    return

    def skip_expr(self):
        """다음 ',' 또는 닫는 괄호 직전까지 식을 건너뛴다."""
        while True:
            k, v = self.peek()
            if k == "eof" or v in (",", "}", "]", ")"):
                return
            if v in "([{":
                self.skip_balanced()
            else:
                self.next()

    def value(self):
        k, v = self.peek()
        if v == "{":
            return self.obj()
        if v == "[":
            return self.arr()
        if k == "str":
            self.next()
            if self.peek()[1] in (",", "}", "]"):
                return _unquote(v)
            self.skip_expr()
            return SKIP
        if k == "num":
            self.next()
            if self.peek()[1] in (",", "}", "]"):
                return float(v) if any(c in v for c in ".eE") else int(v)
            self.skip_expr()
            return SKIP
        if k == "id" and v in ("true", "false", "null", "undefined"):
            self.next()
            if self.peek()[1] in (",", "}", "]"):
                return {"true": True, "false": False}.get(v)
            self.skip_expr()
            return SKIP
        self.skip_expr()
        return SKIP

    def arr(self):
        self.next()  # [
        out = []
        while self.peek()[1] != "]":
            v = self.value()
            if v is not SKIP:
                out.append(v)
            if self.peek()[1] == ",":
                self.next()
        self.next()
        return out

    def obj(self):
        self.next()  # {
        out = {}
        while self.peek()[1] != "}":
            k, v = self.next()
            if v == "...":
                self.skip_expr()
            elif v in ("get", "set", "async") and self.peek()[0] == "id":
                k, v = self.next()
            key = _unquote(v) if k == "str" else v
            if v == "[":  # 계산된 키
                self.i -= 1
                self.skip_balanced()
                key = None
            nxt = self.peek()[1]
            if nxt == "(" or nxt == "<":  # 메서드: 이름만 "_fns"에 기록
                while self.peek()[1] != "{":
                    if self.peek()[1] in "([":
                        self.skip_balanced()
                    else:
                        self.next()
                self.skip_balanced()
                if key is not None:
                    out.setdefault("_fns", []).append(key)
            elif nxt == ":":
                self.next()
                val = self.value()
                if val is not SKIP and key is not None:
                    out[key] = val
                elif val is SKIP and key is not None:
                    out.setdefault("_fns", []).append(key)
            elif nxt == "?":  # 선택적 메서드 등
                self.skip_expr()
            if self.peek()[1] == ",":
                self.next()
        self.next()
        return out


def load(path: str) -> dict:
    """`export const X: ... = { ... };` 형태 파일의 첫 번째 객체를 dict로 반환한다."""
    src = open(path, encoding="utf-8").read()
    start = src.index("= {", src.index("export const")) + 2
    p = Parser(tokenize(src[start:]))
    return p.obj()
