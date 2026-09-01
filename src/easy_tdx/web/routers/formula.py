"""通达信公式路由：校验 / 计算 / 选股 / 回测（v1.27 新增）。

与 CLI（``easy-tdx formula ...``）和 Python API（:mod:`easy_tdx.formula`）
同口径——公式方言与信号归类见该模块文档。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from easy_tdx.web.deps import get_client
from easy_tdx.web.task_runner import get_runner

router = APIRouter(tags=["formula"])


class FormulaValidateRequest(BaseModel):
    """公式校验请求（无需行情数据）。"""

    text: str = Field(..., min_length=1, max_length=8000)


class FormulaValidateResponse(BaseModel):
    ok: bool
    signals: list[str] = Field(default_factory=list)
    values: list[str] = Field(default_factory=list)
    error: str | None = None


class FormulaComputeRequest(FormulaValidateRequest):
    """公式计算请求：内联 ohlcv 或按 symbol 取行情（二选一）。"""

    ohlcv: list[dict[str, Any]] | None = Field(default=None, max_length=2000)
    symbol: str | None = Field(default=None, pattern=r"^(SZ|SH|BJ):\d{6}$")
    category: str = "DAY"
    count: int = Field(default=250, ge=20, le=2000)
    tail: int = Field(default=10, ge=0, le=100, description="附带最近 N 根输出明细")


class FormulaBacktestRequest(FormulaComputeRequest):
    """公式回测请求（信号列下一根开盘成交）。"""

    buy_col: str | None = Field(default=None, description="买入信号列（默认自动挑选）")
    sell_col: str | None = Field(default=None, description="卖出信号列（默认自动挑选）")
    cash: float = Field(default=1_000_000.0, gt=0)
    commission: float = Field(default=0.0003, ge=0, le=0.01)
    auto_fees: bool = Field(default=False)


class FormulaScreenRequest(FormulaValidateRequest):
    """公式选股请求（后台任务，逐标的取行情）。"""

    symbols: list[str] = Field(..., min_length=1, max_length=50)
    signal_col: str | None = None
    category: str = "DAY"
    count: int = Field(default=250, ge=60, le=2000)


@router.post("/formula/validate", response_model=FormulaValidateResponse)
async def validate_formula(req: FormulaValidateRequest) -> FormulaValidateResponse:
    """校验公式语法并给出信号/数值输出归类（不取行情）。"""
    from easy_tdx.formula import FormulaError, compile_formula

    try:
        compiled = compile_formula(req.text)
        # 无数据时的静态归类：检查输出表达式的 AST 类型
        signals: list[str] = []
        values: list[str] = []
        bool_kinds = {"cmp", "logic"}
        bool_funcs = {"CROSS", "LONGCROSS", "EXIST", "EVERY"}
        for stmt in compiled._statements:  # noqa: SLF001 — 同包内部协定
            if stmt.is_output and stmt.name:
                if stmt.expr.kind in bool_kinds or (
                    stmt.expr.kind == "call" and stmt.expr.value in bool_funcs
                ):
                    signals.append(stmt.name)
                else:
                    values.append(stmt.name)
        return FormulaValidateResponse(ok=True, signals=signals, values=values)
    except FormulaError as exc:
        return FormulaValidateResponse(ok=False, error=str(exc))


@router.post("/formula/compute")
async def compute_formula(
    req: FormulaComputeRequest, client: Any = Depends(get_client)
) -> dict[str, Any]:
    """在 K 线上计算公式：最后一根各列值 + 可选最近 N 根明细。"""
    import pandas as pd

    from easy_tdx.formula import FormulaError, compile_formula

    try:
        compiled = compile_formula(req.text)
    except FormulaError as exc:
        raise ValueError(str(exc)) from exc

    df = await _resolve_df(client, req)
    try:
        result = compiled.compute(df)
    except FormulaError as exc:
        raise ValueError(str(exc)) from exc

    payload: dict[str, Any] = {
        "signals": result.signals,
        "values": result.values,
        "last_row": result.last_row(),
    }
    if req.tail > 0 and result.columns:
        dt_col = "datetime" if "datetime" in df.columns else "date"
        recent = result.to_frame().iloc[-req.tail :]
        recent.insert(
            0, "date", [str(pd.Timestamp(d).date()) for d in df[dt_col].iloc[-req.tail :]]
        )
        payload["recent"] = recent.to_dict(orient="records")
    return payload


@router.post("/formula/backtest/run/async", status_code=202)
async def run_formula_backtest_async(
    req: FormulaBacktestRequest, client: Any = Depends(get_client)
) -> dict[str, str]:
    """提交公式回测后台任务（信号列下一根开盘成交），轮询 /backtest/tasks/{id}。"""
    df = await _resolve_df(client, req)
    snapshot = req.model_copy()
    runner = get_runner()
    task_id = runner.submit(
        lambda: _run_formula_backtest(df, snapshot),
        description=f"公式回测 | {snapshot.symbol or '内联数据'}",
    )
    return {"task_id": task_id, "status": "running"}


@router.post("/formula/screen/run/async", status_code=202)
async def run_formula_screen_async(
    req: FormulaScreenRequest, client: Any = Depends(get_client)
) -> dict[str, str]:
    """提交公式选股后台任务：信号列最后一根 = 1 的标的 + 数值列（供排序）。"""
    from easy_tdx.formula import FormulaError, compile_formula
    from easy_tdx.web.convert import category_from_str, market_from_str

    try:
        compiled = compile_formula(req.text)
    except FormulaError as exc:
        raise ValueError(str(exc)) from exc

    bars: dict[str, Any] = {}
    for symbol in req.symbols:
        market_str, code = symbol.split(":", 1)
        try:
            page = await client.get_security_bars(
                market_from_str(market_str), code, category_from_str(req.category), 0, req.count
            )
        except Exception:  # noqa: BLE001 — 单标的失败跳过
            continue
        if page is not None and len(page) >= 30:
            bars[symbol] = page
    if not bars:
        raise ValueError("所有标的均未取到有效 K 线")

    snapshot = req.model_copy()
    runner = get_runner()
    task_id = runner.submit(
        lambda: _run_formula_screen(bars, compiled, snapshot.signal_col),
        description=f"公式选股 | {len(bars)}只标的",
    )
    return {"task_id": task_id, "status": "running"}


# ── 内部实现 ───────────────────────────────────────────────────────────────────


async def _resolve_df(client: Any, req: FormulaComputeRequest) -> Any:
    """内联 ohlcv 或按 symbol 取行情。"""
    import pandas as pd

    if req.ohlcv is not None:
        df = pd.DataFrame(req.ohlcv)
        required = {"datetime", "open", "high", "low", "close", "vol"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"ohlcv 缺少必需列: {sorted(missing)}")
        if not pd.api.types.is_datetime64_any_dtype(df["datetime"]):
            df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
        return df
    if req.symbol is not None:
        from easy_tdx.web.convert import category_from_str, market_from_str

        market_str, code = req.symbol.split(":", 1)
        df = await client.get_security_bars(
            market_from_str(market_str), code, category_from_str(req.category), 0, req.count
        )
        if df is None or len(df) == 0:
            raise ValueError(f"标的 {req.symbol} 未取到 K 线数据")
        return df
    raise ValueError("必须提供 ohlcv 或 symbol")


def _run_formula_backtest(df: Any, req: FormulaBacktestRequest) -> dict[str, Any]:
    """执行公式回测（后台线程内调用）。"""
    from easy_tdx.backtest.formula_strategy import run_formula_backtest as _run

    try:
        return _run(
            df,
            req.text,
            buy_col=req.buy_col,
            sell_col=req.sell_col,
            cash=req.cash,
            commission=req.commission,
            symbol=req.symbol,
            auto_fees=req.auto_fees,
        )
    except ValueError as exc:
        raise ValueError(str(exc)) from exc


def _run_formula_screen(
    bars: dict[str, Any], compiled: Any, signal_col: str | None
) -> dict[str, Any]:
    """执行公式选股（后台线程内调用）。"""
    from easy_tdx.formula import FormulaError

    hits: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for symbol, df in bars.items():
        try:
            result = compiled.compute(df)
            col = signal_col or (result.signals[0] if result.signals else None)
            if col is None:
                raise ValueError("公式无布尔信号输出")
            if result.last_row().get(col, 0.0) >= 1.0:
                row: dict[str, Any] = {"symbol": symbol}
                row.update({k: v for k, v in result.last_row().items() if k != col})
                hits.append(row)
        except (FormulaError, ValueError) as exc:
            errors.append({"symbol": symbol, "error": str(exc)})
    return {"total": len(bars), "hits": hits, "errors": errors}
