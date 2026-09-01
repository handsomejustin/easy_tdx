"""通达信公式解析器（v1.27 新增）。

把通达信/麦语言风格的技术指标公式翻译成 numpy 向量计算，让写惯公式的
用户零 Python 进入 easy-tdx 的筛选/回测体系（借鉴 indicator-lab 的公式
解析思路，实现为独立子集方言）。

支持的方言子集::

    {注释花括号}
    N := 9;                       { 中间变量（参数） }
    RSV := (C - LLV(L, N)) / (HHV(H, N) - LLV(L, N)) * 100;
    K := SMA(RSV, 3, 1);
    金叉: CROSS(K, D);            { 命名布尔输出 → 信号列 }
    强度: K - D;                  { 命名数值输出 → 排名/卖出参考列 }

语法规则：

- 语句以 ``;`` 结尾；``NAME := expr`` 为中间变量、``NAME: expr`` 为输出；
  裸表达式作为匿名输出 ``OUTPUT_1``；
- 运算符：``+ - * /``（除零安全，分母 0 → NaN）、比较 ``> < >= <= =``、
  逻辑 ``AND OR NOT``（兼容 ``&& || !``）、括号、一元负号；
- 序列名：``C/CLOSE, O/OPEN, H/HIGH, L/LOW, V/VOL/VOL, AMOUNT/AMT``；
- 函数白名单（全部后视函数，**无未来数据**）：MA/EMA/SMA/WMA/DMA/HHV/LLV/
  REF/SUM/COUNT/CROSS/LONGCROSS/EXIST/EVERY/BARSLAST/IF/MAX/MIN/ABS/POW/
  SQRT/LN/LOG/EXP/STD/AVEDEV/MACD/KDJ/RSI/BOLL/CCI/ATR/OBM/DMI 等
  （映射到 MyTT 与 numpy，见 :data:`_FUNCTIONS`）；
- 输出归类：布尔表达式（比较/逻辑/CROSS 等）的命名输出 → **信号列**
  （``signals``）；数值表达式 → **数值列**（``values``，用于排名/阈值）。

安全：自建 tokenizer + AST 求值，**不走 Python eval**；未知函数/变量报
:class:`FormulaError`（带位置）。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

__all__ = ["FormulaError", "FormulaResult", "CompiledFormula", "compile_formula"]

# ── Token ─────────────────────────────────────────────────────────────────────

_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<comment>\{[^}]*\})
  | (?P<num>\d+\.\d+|\.\d+|\d+)
  | (?P<name>[A-Za-z_\u4e00-\u9fff][A-Za-z0-9_\u4e00-\u9fff]*)
  | (?P<op>:=|>=|<=|==|&&|\|\||[-+*/(),:;><!=])
    """,
    re.VERBOSE,
)


@dataclass
class _Token:
    kind: str  # num / name / op / eof
    value: str
    pos: int


def _tokenize(text: str) -> list[_Token]:
    tokens: list[_Token] = []
    i = 0
    while i < len(text):
        m = _TOKEN_RE.match(text, i)
        if m is None:
            raise FormulaError(f"无法识别的字符 {text[i]!r}（位置 {i}）", pos=i)
        i = m.end()
        if m.lastgroup in ("ws", "comment"):
            continue
        tokens.append(_Token(kind=m.lastgroup or "op", value=m.group(), pos=m.start()))
    tokens.append(_Token(kind="eof", value="", pos=len(text)))
    return tokens


# ── AST ───────────────────────────────────────────────────────────────────────


@dataclass
class _Node:
    """表达式节点（用元数据极简表示，求值器按 kind 分派）。"""

    kind: str  # num / name / call / bin / un / cmp / logic
    value: int | float | str | None = None
    children: list[_Node] = field(default_factory=list)


@dataclass
class _Statement:
    """一条语句：中间赋值（is_output=False）或命名输出。"""

    name: str | None
    expr: _Node
    is_output: bool
    pos: int


# ── Parser（递归下降）────────────────────────────────────────────────────────


class _Parser:
    def __init__(self, tokens: list[_Token]) -> None:
        self._tokens = tokens
        self._i = 0

    def _peek(self) -> _Token:
        return self._tokens[self._i]

    def _next(self) -> _Token:
        tok = self._tokens[self._i]
        self._i += 1
        return tok

    def _expect_op(self, op: str) -> _Token:
        tok = self._peek()
        if tok.kind == "op" and tok.value == op:
            return self._next()
        raise FormulaError(f"期望 {op!r}，得到 {tok.value!r}（位置 {tok.pos}）", pos=tok.pos)

    def _match_op(self, *ops: str) -> _Token | None:
        tok = self._peek()
        if tok.kind == "op" and tok.value in ops:
            return self._next()
        # 关键字运算符（AND/OR/NOT 分词为 name，按大写匹配）
        if tok.kind == "name" and tok.value.upper() in ops:
            return self._next()
        return None

    def parse_statements(self) -> list[_Statement]:
        stmts: list[_Statement] = []
        anonymous = 0
        while self._peek().kind != "eof":
            tok = self._peek()
            if tok.kind == "op" and tok.value == ";":  # 空语句
                self._next()
                continue
            if tok.kind != "name":
                raise FormulaError(
                    f"期望变量名开头，得到 {tok.value!r}（位置 {tok.pos}）", pos=tok.pos
                )
            # NAME := expr | NAME : expr | 裸表达式
            if (
                self._tokens[self._i + 1].kind == "op"
                and self._tokens[self._i + 1].value in (":=", ":")
                and not (
                    self._tokens[self._i + 1].value == ":"
                    and self._tokens[self._i + 2].kind == "op"
                    and self._tokens[self._i + 2].value == "="
                )
            ):
                name = self._next().value
                assign = self._next()  # := 或 :
                expr = self.parse_expression()
                self._expect_op(";")
                stmts.append(
                    _Statement(name=name, expr=expr, is_output=(assign.value == ":"), pos=tok.pos)
                )
            else:
                anonymous += 1
                expr = self.parse_expression()
                self._expect_op(";")
                stmts.append(
                    _Statement(name=f"OUTPUT_{anonymous}", expr=expr, is_output=True, pos=tok.pos)
                )
        return stmts

    # 表达式优先级：OR < AND < 比较 < 加减 < 乘除 < 一元 < 原子
    def parse_expression(self) -> _Node:
        return self._parse_or()

    def _parse_or(self) -> _Node:
        left = self._parse_and()
        while tok := self._match_op("OR", "||"):
            right = self._parse_and()
            left = _Node(kind="logic", value="or", children=[left, right])
            left.pos_hint = tok.pos  # type: ignore[attr-defined]
        return left

    def _parse_and(self) -> _Node:
        left = self._parse_cmp()
        while tok := self._match_op("AND", "&&"):
            right = self._parse_cmp()
            left = _Node(kind="logic", value="and", children=[left, right])
            left.pos_hint = tok.pos  # type: ignore[attr-defined]
        return left

    def _parse_cmp(self) -> _Node:
        left = self._parse_add()
        while tok := self._match_op(">", "<", ">=", "<=", "=", "=="):
            right = self._parse_add()
            op = "==" if tok.value in ("=", "==") else tok.value
            left = _Node(kind="cmp", value=op, children=[left, right])
        return left

    def _parse_add(self) -> _Node:
        left = self._parse_mul()
        while tok := self._match_op("+", "-"):
            right = self._parse_mul()
            left = _Node(kind="bin", value=tok.value, children=[left, right])
        return left

    def _parse_mul(self) -> _Node:
        left = self._parse_unary()
        while tok := self._match_op("*", "/"):
            right = self._parse_unary()
            left = _Node(kind="bin", value=tok.value, children=[left, right])
        return left

    def _parse_unary(self) -> _Node:
        if tok := self._match_op("-", "+"):
            child = self._parse_unary()
            if tok.value == "-":
                return _Node(kind="un", value="neg", children=[child])
            return child
        if tok := self._match_op("!", "NOT"):
            child = self._parse_unary()
            return _Node(kind="un", value="not", children=[child])
        return self._parse_primary()

    def _parse_primary(self) -> _Node:
        tok = self._peek()
        if tok.kind == "num":
            self._next()
            v = float(tok.value)
            # 整数字面量保持 int（MyTT 窗口/周期参数要求 int）
            if v.is_integer() and abs(v) < 1e15:
                v = int(v)
            return _Node(kind="num", value=v)
        if tok.kind == "op" and tok.value == "(":
            self._next()
            node = self.parse_expression()
            self._expect_op(")")
            return node
        if tok.kind == "name":
            self._next()
            # 函数调用
            if self._peek().kind == "op" and self._peek().value == "(":
                self._next()
                args: list[_Node] = []
                if not (self._peek().kind == "op" and self._peek().value == ")"):
                    args.append(self.parse_expression())
                    while self._match_op(","):
                        args.append(self.parse_expression())
                self._expect_op(")")
                return _Node(kind="call", value=tok.value.upper(), children=args)
            return _Node(kind="name", value=tok.value)
        raise FormulaError(f"意外的记号 {tok.value!r}（位置 {tok.pos}）", pos=tok.pos)


# ── 序列与函数环境 ─────────────────────────────────────────────────────────────

_SERIES_ALIASES: dict[str, str] = {
    "C": "close",
    "CLOSE": "close",
    "收盘价": "close",
    "O": "open",
    "OPEN": "open",
    "开盘价": "open",
    "H": "high",
    "HIGH": "high",
    "最高价": "high",
    "L": "low",
    "LOW": "low",
    "最低价": "low",
    "V": "vol",
    "VOL": "vol",
    "VOLUME": "vol",
    "成交量": "vol",
    "AMOUNT": "amount",
    "AMT": "amount",
    "成交额": "amount",
}

_BOOL_FUNCS = {"CROSS", "LONGCROSS", "EXIST", "EVERY"}  # 返回布尔的函数


def _build_functions() -> dict[str, Callable[..., Any]]:
    """函数白名单：MyTT 后视函数 + numpy 补齐（不透传任意 Python）。"""
    import easy_tdx.MyTT as mytt

    fns: dict[str, Callable[..., Any]] = {}
    for name in (
        "MA",
        "EMA",
        "SMA",
        "WMA",
        "DMA",
        "HHV",
        "LLV",
        "REF",
        "SUM",
        "COUNT",
        "CROSS",
        "LONGCROSS",
        "EXIST",
        "EVERY",
        "BARSLAST",
        "IF",
        "MAX",
        "MIN",
        "ABS",
        "STD",
        "AVEDEV",
        "MACD",
        "KDJ",
        "RSI",
        "BOLL",
        "CCI",
        "ATR",
        "OBV",
        "DMI",
        "FILTER",
    ):
        if hasattr(mytt, name):
            fns[name] = getattr(mytt, name)
    # numpy 补齐（TDX 语义）
    fns["POW"] = np.power
    fns["SQRT"] = np.sqrt
    fns["LN"] = np.log
    fns["LOG"] = np.log10
    fns["EXP"] = np.exp
    fns["NOT"] = np.logical_not
    return fns


_FUNCTIONS: dict[str, Callable[..., Any]] | None = None


def _functions() -> dict[str, Callable[..., Any]]:
    global _FUNCTIONS  # noqa: PLW0603 — 模块级缓存
    if _FUNCTIONS is None:
        _FUNCTIONS = _build_functions()
    return _FUNCTIONS


# ── 求值器 ────────────────────────────────────────────────────────────────────


class _Evaluator:
    def __init__(self, df: pd.DataFrame) -> None:
        self._arrays: dict[str, np.ndarray] = {}
        for col in df.columns:
            if col in ("datetime", "date"):
                continue
            try:
                arr = pd.to_numeric(df[col], errors="coerce").to_numpy(dtype=float)
            except (TypeError, ValueError):
                continue  # 非数值列（如文本）跳过
            self._arrays[str(col).lower()] = arr
        self._vars: dict[str, Any] = {}
        self._n = len(df)

    def eval_statements(self, stmts: list[_Statement]) -> FormulaResult:
        result = FormulaResult(n=self._n)
        for stmt in stmts:
            val = self.eval(stmt.expr)
            if stmt.name is not None:
                self._vars[stmt.name.upper()] = val
            if stmt.is_output and stmt.name is not None:
                arr = np.asarray(val, dtype=float)
                result.columns[stmt.name] = arr
                if self._is_boolean(stmt.expr, val):
                    result.signals.append(stmt.name)
                else:
                    result.values.append(stmt.name)
        return result

    @staticmethod
    def _is_boolean(expr: _Node, val: Any) -> bool:
        """输出归类：比较/逻辑/CROSS 节点或 0/1 值域 → 信号列。"""
        if expr.kind in ("cmp", "logic"):
            return True
        if expr.kind == "call" and expr.value in _BOOL_FUNCS:
            return True
        arr = np.asarray(val, dtype=float)
        finite = arr[np.isfinite(arr)]
        if finite.size == 0:
            return False
        return bool(finite.min() >= 0.0 and finite.max() <= 1.0)

    def eval(self, node: _Node) -> Any:
        if node.kind == "num":
            # 保持解析期类型（int 窗口参数 / float 数值）
            return node.value
        if node.kind == "name":
            key = str(node.value)
            upper = key.upper()
            if upper in _SERIES_ALIASES:
                col = _SERIES_ALIASES[upper]
                if col not in self._arrays:
                    raise FormulaError(f"K 线数据缺少列 {col!r}（公式引用了 {key}）")
                return self._arrays[col]
            if key in self._vars:
                return self._vars[key]
            if upper in self._vars:
                return self._vars[upper]
            raise FormulaError(f"未知变量 {key!r}（未定义且不是序列名/函数）")
        if node.kind == "call":
            fname = str(node.value)
            fns = _functions()
            if fname not in fns:
                raise FormulaError(f"未知或不支持的函数 {fname}（白名单外）")
            args = [self.eval(c) for c in node.children]
            try:
                with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
                    out = fns[fname](*args)
            except Exception as exc:  # noqa: BLE001 — 包装带函数名
                raise FormulaError(f"函数 {fname} 求值失败：{exc}") from exc
            return out
        if node.kind == "bin":
            a = np.asarray(self.eval(node.children[0]), dtype=float)
            b = np.asarray(self.eval(node.children[1]), dtype=float)
            a, b = np.broadcast_arrays(a, b)
            if node.value == "+":
                return a + b
            if node.value == "-":
                return a - b
            if node.value == "*":
                return a * b
            if node.value == "/":
                # 除零安全：分母 0 → NaN（不炸、不 inf）
                with np.errstate(divide="ignore", invalid="ignore"):
                    out = np.divide(a, b, out=np.full(a.shape, np.nan), where=b != 0)
                return out
            raise FormulaError(f"未知运算符 {node.value}")
        if node.kind == "un":
            child = np.asarray(self.eval(node.children[0]), dtype=float)
            return -child if node.value == "neg" else np.logical_not(child != 0).astype(float)
        if node.kind == "cmp":
            a = np.asarray(self.eval(node.children[0]), dtype=float)
            b = np.asarray(self.eval(node.children[1]), dtype=float)
            a, b = np.broadcast_arrays(a, b)
            op = node.value
            with np.errstate(invalid="ignore"):
                if op == ">":
                    out = a > b
                elif op == "<":
                    out = a < b
                elif op == ">=":
                    out = a >= b
                elif op == "<=":
                    out = a <= b
                else:  # ==
                    out = np.isclose(a, b)
            return out.astype(float)  # NaN 参与比较 → False（0）
        if node.kind == "logic":
            a = np.asarray(self.eval(node.children[0]), dtype=float)
            b = np.asarray(self.eval(node.children[1]), dtype=float)
            a, b = np.broadcast_arrays(a, b)
            if node.value == "and":
                return ((a != 0) & (b != 0)).astype(float)
            return ((a != 0) | (b != 0)).astype(float)
        raise FormulaError(f"未知节点类型 {node.kind}")


# ── 公共 API ──────────────────────────────────────────────────────────────────


class FormulaError(ValueError):
    """公式语法/求值错误（附位置信息）。"""

    def __init__(self, message: str, pos: int | None = None) -> None:
        super().__init__(message if pos is None else f"{message} @col {pos}")
        self.pos = pos


@dataclass
class FormulaResult:
    """公式计算结果：命名输出列 + 信号/数值归类。"""

    columns: dict[str, np.ndarray] = field(default_factory=dict)
    signals: list[str] = field(default_factory=list)  # 布尔输出名（信号列）
    values: list[str] = field(default_factory=list)  # 数值输出名（排名列）
    n: int = 0

    def to_frame(self) -> pd.DataFrame:
        """输出列拼成 DataFrame（保留声明顺序）。"""
        if not self.columns:
            return pd.DataFrame()
        return pd.DataFrame(dict(self.columns))

    def last_row(self) -> dict[str, float]:
        """各输出列最后一根 bar 的值（选股扫描口径）。"""
        out: dict[str, float] = {}
        for name, arr in self.columns.items():
            arr = np.asarray(arr, dtype=float)
            out[name] = float(arr[-1]) if len(arr) and np.isfinite(arr[-1]) else 0.0
        return out


class CompiledFormula:
    """已编译的公式（解析一次，多处计算）。"""

    def __init__(self, text: str) -> None:
        self._text = text
        self._statements = _Parser(_tokenize(text)).parse_statements()
        if not self._statements:
            raise FormulaError("公式为空或只有注释")

    @property
    def text(self) -> str:
        return self._text

    def compute(self, df: pd.DataFrame) -> FormulaResult:
        """在 K 线上计算公式（数据不足预热期自动为 NaN/0，不抛错）。"""
        if df is None or len(df) == 0:
            raise FormulaError("K 线数据为空")
        return _Evaluator(df).eval_statements(self._statements)


def compile_formula(text: str) -> CompiledFormula:
    """编译通达信公式文本（语法错误抛 :class:`FormulaError`）。"""
    return CompiledFormula(text)
