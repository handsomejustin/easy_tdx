"""回测 Web API 的请求/响应模型与结果序列化。

与 ``easy_tdx.web.schemas`` 分离，避免主 schemas 文件膨胀。结果序列化复用
主 schemas 的 numpy/datetime 清洗思路，但递归处理嵌套结构（BacktestResult
的 performance 是 dict、equity_curve 是 list[dict]、config 是 dict）。
"""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# 标的符号：A 股（SZ/SH/BJ:6位数字）或扩展市场/加密（US_STOCK:TSLA /
# CFFEX_FUTURES:IFL0 / CRYPTO:BTCUSDT 等）。市场前缀大写字母+下划线，代码任意字符。
_SYMBOL_RE = re.compile(r"^(SZ|SH|BJ):\d{6}$|^[A-Z][A-Z0-9_]*:[\w.-]+$")

__all__ = [
    "BacktestRequest",
    "BacktestResultResponse",
    "StrategySchemaResponse",
    "TaskSubmitResponse",
    "TaskStateResponse",
    "OptimizeAllBacktestRequest",
    "OptimizeAllResult",
    "OptimizeAllRankEntry",
    "SavedStrategy",
    "SavedStrategyCreate",
    "SavedStrategyListResponse",
    "MultiStrategyItem",
    "MultiStrategyBacktestRequest",
    "SignalScanRequest",
    "SignalScanRecentSignal",
    "SignalScanRow",
    "SignalScanResult",
    "serialize_result",
]


# ── 请求模型 ───────────────────────────────────────────────────────────────────


class BacktestRequest(BaseModel):
    """单标的回测请求。

    两种数据来源（二选一）：
    - ``ohlcv``: 直接内联 OHLCV 记录（前端已有数据时）。
    - ``symbol`` + ``category`` + ``count``: 指定标的，由后端取行情。
      两者都给则以内联数据为准。
    """

    strategy: str = Field(..., description="策略名（见 /backtest/strategies）")
    params: dict[str, Any] = Field(default_factory=dict, description="策略参数")
    cash: float = Field(default=1_000_000.0, gt=0, description="初始资金")
    commission: float = Field(default=0.0003, ge=0, le=0.01, description="佣金费率")
    min_commission: float = Field(default=5.0, ge=0, description="单笔最低佣金")
    stamp_tax: float = Field(default=0.001, ge=0, le=0.01, description="印花税（卖出）")
    slippage: float = Field(default=0.0, ge=0, le=0.05, description="滑点费率")
    execution: Literal["next_open", "next_close"] = Field(
        default="next_open", description="成交模式"
    )

    # 数据来源 A：内联 OHLCV（上限与 symbol 路径的 count 上限对齐，防 DoS）
    ohlcv: list[dict[str, Any]] | None = Field(
        default=None,
        max_length=2000,
        description="内联 K 线记录（含 datetime/open/high/low/close/vol/amount，最多 2000 条）",
    )

    # 数据来源 B：按标的取行情
    symbol: str | None = Field(
        default=None,
        pattern=_SYMBOL_RE.pattern,
        description="标的代码，格式 市场:代码，如 SZ:000001 / US_STOCK:TSLA / CRYPTO:BTCUSDT",
    )
    category: Literal["DAY", "WEEK", "MONTH", "MIN_5", "MIN_15", "MIN_30", "MIN_60"] = Field(
        default="DAY", description="K 线周期"
    )
    count: int = Field(default=250, ge=20, le=2000, description="K 线根数")

    @model_validator(mode="after")
    def _check_data_source(self) -> BacktestRequest:
        if self.ohlcv is None and self.symbol is None:
            raise ValueError("必须提供 ohlcv（内联数据）或 symbol（标的代码）之一")
        return self


class PortfolioBacktestRequest(BaseModel):
    """组合（多标的）回测请求。

    与单标的 BacktestRequest 的区别：用 ``stocks`` 列表替代单个 ``symbol``，
    资金按 equal 模式均分到各标的。日期范围过滤由前端完成（取满 800 根后过滤）。
    """

    strategy: str = Field(..., description="策略名")
    params: dict[str, Any] = Field(default_factory=dict, description="策略参数")
    cash: float = Field(default=1_000_000.0, gt=0, description="组合总资金")
    commission: float = Field(default=0.0003, ge=0, le=0.01)
    min_commission: float = Field(default=5.0, ge=0)
    stamp_tax: float = Field(default=0.001, ge=0, le=0.01)
    slippage: float = Field(default=0.0, ge=0, le=0.05)
    execution: Literal["next_open", "next_close"] = Field(default="next_open")
    stocks: list[str] = Field(
        ...,
        min_length=1,
        max_length=20,
        description='标的列表，格式 "市场:代码"，如 ["SZ:000001","SH:600519"]',
    )
    category: Literal["DAY", "WEEK", "MONTH", "MIN_5", "MIN_15", "MIN_30", "MIN_60"] = Field(
        default="DAY"
    )
    start_date: str | None = Field(default=None, description="开始日期 YYYY-MM-DD（可选过滤）")
    end_date: str | None = Field(default=None, description="结束日期 YYYY-MM-DD（可选过滤）")

    @model_validator(mode="after")
    def _check_stocks_format(self) -> PortfolioBacktestRequest:
        # 支持 A 股（SZ/SH/BJ:6位）与扩展市场/加密（US_STOCK:TSLA /
        # CFFEX_FUTURES:IFL0 / CRYPTO:BTCUSDT 等），由 _fetch_portfolio_bars 按前缀路由
        for s in self.stocks:
            if not _SYMBOL_RE.fullmatch(s):
                raise ValueError(f"标的格式应为 '市场:代码'，得到 {s!r}")
        return self


class OptimizeBacktestRequest(BaseModel):
    """参数网格寻优请求。

    在单个标的上，对策略的 1-2 个参数做网格搜索。数据来源与单标的回测一致
    （ohlcv 内联或 symbol 取行情）。param_grid 指定寻优参数及其取值列表，
    网格大小（各取值数乘积）上限 200。
    """

    strategy: str = Field(..., description="策略名")
    cash: float = Field(default=1_000_000.0, gt=0)
    commission: float = Field(default=0.0003, ge=0, le=0.01)
    slippage: float = Field(default=0.0, ge=0, le=0.05)
    execution: Literal["next_open", "next_close"] = Field(default="next_open")
    param_grid: dict[str, list[int | float | str]] = Field(
        ...,
        min_length=1,
        max_length=2,
        description='参数取值网格，如 {"fast":[5,10,20], "slow":[15,20,30]}',
    )

    # 数据来源 A：内联 OHLCV
    ohlcv: list[dict[str, Any]] | None = Field(default=None, max_length=2000)

    # 数据来源 B：按标的取行情
    symbol: str | None = Field(default=None, pattern=_SYMBOL_RE.pattern)
    category: Literal["DAY", "WEEK", "MONTH", "MIN_5", "MIN_15", "MIN_30", "MIN_60"] = Field(
        default="DAY"
    )
    count: int = Field(default=250, ge=20, le=800)
    start_date: str | None = Field(default=None)
    end_date: str | None = Field(default=None)

    @model_validator(mode="after")
    def _check_data_source(self) -> OptimizeBacktestRequest:
        if self.ohlcv is None and self.symbol is None:
            raise ValueError("必须提供 ohlcv 或 symbol 之一")
        return self


class OptimizeAllBacktestRequest(BaseModel):
    """一键寻优所有策略请求。

    在单个标的上，对所有策略的预设参数网格（见
    ``easy_tdx.backtest.strategies.presets.STRATEGY_PRESETS``）依次做网格寻优，
    取各策略最优点汇总成全局排名，找出最佳策略 + 参数组合。数据来源与单标的
    回测一致（ohlcv 内联或 symbol 取行情）。
    """

    cash: float = Field(default=1_000_000.0, gt=0)
    commission: float = Field(default=0.0003, ge=0, le=0.01)
    slippage: float = Field(default=0.0, ge=0, le=0.05)
    execution: Literal["next_open", "next_close"] = Field(default="next_open")
    workers: int = Field(
        default=1,
        ge=0,
        le=32,
        description="一键寻优并发工作进程数：0 或 1=串行（默认）；2+=ProcessPoolExecutor "
        "并行（CPU-bound，线程无加速）。推荐 min(cpu_count, 8)。",
    )

    # 数据来源 A：内联 OHLCV
    ohlcv: list[dict[str, Any]] | None = Field(default=None, max_length=2000)

    # 数据来源 B：按标的取行情
    symbol: str | None = Field(default=None, pattern=_SYMBOL_RE.pattern)
    category: Literal["DAY", "WEEK", "MONTH", "MIN_5", "MIN_15", "MIN_30", "MIN_60"] = Field(
        default="DAY"
    )
    count: int = Field(default=250, ge=20, le=800)
    start_date: str | None = Field(default=None)
    end_date: str | None = Field(default=None)

    @model_validator(mode="after")
    def _check_data_source(self) -> OptimizeAllBacktestRequest:
        if self.ohlcv is None and self.symbol is None:
            raise ValueError("必须提供 ohlcv 或 symbol 之一")
        return self


# ── 响应模型 ───────────────────────────────────────────────────────────────────


class StrategySchemaResponse(BaseModel):
    """策略 schema 列表响应（/backtest/strategies）。"""

    strategies: list[dict[str, Any]]
    count: int


class BacktestResultResponse(BaseModel):
    """回测结果响应（已清洗为 JSON 原生类型）。"""

    performance: dict[str, Any]
    equity_curve: list[dict[str, Any]]
    trades: list[dict[str, Any]]
    positions: list[dict[str, Any]]
    config: dict[str, Any]


class TaskSubmitResponse(BaseModel):
    """后台任务提交响应。"""

    task_id: str
    status: Literal["pending", "running"]


class TaskStateResponse(BaseModel):
    """后台任务状态响应。"""

    task_id: str
    status: Literal["pending", "running", "done", "failed"]
    result: dict[str, Any] | None = None
    error: str | None = None
    description: str = ""
    elapsed: float = 0.0


class TaskSummary(BaseModel):
    """任务摘要（列表用，不含完整 result）。"""

    task_id: str
    status: Literal["pending", "running", "done", "failed"]
    description: str = ""
    created_at: float = 0.0
    elapsed: float = 0.0


class TaskListResponse(BaseModel):
    """任务摘要列表响应。"""

    tasks: list[TaskSummary]
    count: int


class OptimizeAllRankEntry(BaseModel):
    """一键寻优全局排名单行：某策略的最优点摘要。"""

    strategy: str
    strategy_label: str
    params: dict[str, Any]
    total_return: float = 0.0
    sharpe: float = 0.0
    max_drawdown: float = 0.0
    total_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    grid_points: int = 0  # 该策略本轮寻优的网格点数


class OptimizeAllResult(BaseModel):
    """一键寻优所有策略的结果：全局排名 + 最佳 + 各策略最优点。"""

    ranking: list[OptimizeAllRankEntry]  # 按 total_return 降序
    best: OptimizeAllRankEntry | None = None
    per_strategy: dict[str, OptimizeAllRankEntry] = {}  # 策略名 → 最优点
    total_grid_points: int = 0  # 所有策略网格点合计


# ── 已保存策略（策略库 / StrategyLibrary）───────────────────────────────────────


class SavedStrategyCreate(BaseModel):
    """新建一条已保存策略的请求体。

    前端在单标的/组合回测结果区点「保存策略」时提交。``strategy`` + ``params``
    是回测引擎可直接消费的最小复现形态；``context`` 记录当时测的标的/日期，
    ``snapshot`` 记录保存时的关键绩效指标（"为什么觉得它好"）。
    """

    name: str = Field(..., min_length=1, max_length=120, description="策略名称（用户自拟）")
    kind: Literal["single", "portfolio", "multi"] = Field(
        ..., description="来源：单标的/组合/多策略组合"
    )
    strategy: str = Field(..., description="策略名（注册表 key，如 ma_cross）")
    strategy_label: str = Field(default="", description="策略展示名")
    params: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(
        default_factory=dict,
        description="标的上下文：single 存 symbol/category/start_date/end_date；"
        "portfolio 存 stocks 列表；multi 存 items(MultiStrategyItem[]) + cash/execution",
    )
    trade_config: dict[str, Any] = Field(
        default_factory=dict, description="资金与成本配置（cash/commission/...）"
    )
    snapshot: dict[str, Any] = Field(
        default_factory=dict, description="保存时的成绩快照（total_return/sharpe/...）"
    )
    tags: list[str] = Field(default_factory=list)
    notes: str = Field(default="", max_length=2000)


class SavedStrategy(BaseModel):
    """一条已保存策略（响应模型，含 id 与时间戳）。"""

    id: str
    name: str
    kind: Literal["single", "portfolio", "multi"]
    strategy: str
    strategy_label: str = ""
    params: dict[str, Any] = {}
    context: dict[str, Any] = {}
    trade_config: dict[str, Any] = {}
    snapshot: dict[str, Any] = {}
    tags: list[str] = []
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""
    app_version: str = ""


class SavedStrategyListResponse(BaseModel):
    """策略库列表响应。"""

    strategies: list[SavedStrategy]
    count: int


# ── 多策略组合回测（资金分仓 / 并行制）──────────────────────────────────────────


class MultiStrategyItem(BaseModel):
    """多策略组合回测的单条策略槽位。

    每条 = 一个策略 + 它的参数 + 它要跑的原标的 + 日期范围。资金由请求体的
    ``cash`` 统一给出，引擎按策略数均分到各条。
    """

    strategy: str = Field(..., description="策略名（注册表 key，如 ma_cross）")
    strategy_label: str = Field(default="", description="策略展示名（用于结果 key）")
    params: dict[str, Any] = Field(default_factory=dict)
    symbol: str = Field(
        ...,
        pattern=_SYMBOL_RE.pattern,
        description='标的完整代码，格式 "市场:6位代码"，如 "SH:601088"',
    )
    category: Literal["DAY", "WEEK", "MONTH", "MIN_5", "MIN_15", "MIN_30", "MIN_60"] = Field(
        default="DAY"
    )
    start_date: str | None = Field(default=None, description="开始日期 YYYY-MM-DD（可选过滤）")
    end_date: str | None = Field(default=None, description="结束日期 YYYY-MM-DD（可选过滤）")


class MultiStrategyBacktestRequest(BaseModel):
    """多策略组合回测请求（资金分仓）。

    勾选 N 个策略，各跑在各自原标的上，总资金按策略数均分。响应该请求的后台任务
    结果是 ``MultiStrategyResult``（结构同 ``PortfolioResult``，前端复用组合页图表）。
    """

    items: list[MultiStrategyItem] = Field(
        ..., min_length=1, max_length=20, description="策略槽位列表（1~20 条）"
    )
    cash: float = Field(default=1_000_000.0, gt=0, description="组合总资金（均分给各策略）")
    commission: float = Field(default=0.0003, ge=0, le=0.01)
    min_commission: float = Field(default=5.0, ge=0)
    stamp_tax: float = Field(default=0.001, ge=0, le=0.01)
    slippage: float = Field(default=0.0, ge=0, le=0.05)
    execution: Literal["next_open", "next_close"] = Field(default="next_open")


# ── 信号雷达（一键扫描已保存策略的最近买卖信号）────────────────────────────────


class SignalScanRequest(BaseModel):
    """信号扫描请求：扫描策略库全部已保存策略，只看最近 N 根 K 线内的信号。"""

    window_bars: int = Field(
        default=5, ge=1, le=30, description="检查最近 N 根 K 线内的信号（日线即 N 个交易日）"
    )


class SignalScanRecentSignal(BaseModel):
    """窗口内单根 K 线的信号。"""

    date: str
    direction: Literal["BUY", "SELL"]


class SignalScanRow(BaseModel):
    """扫描结果单行：一个"策略×标的"子任务的信号摘要。

    single 策略 1 行；portfolio 每只标的 1 行；multi 每个子策略 1 行
    （行内 ``strategy_name`` 是所属已保存策略的名字）。
    """

    strategy_id: str
    strategy_name: str
    kind: Literal["single", "portfolio", "multi"]
    strategy: str
    strategy_label: str = ""
    params: dict[str, Any] = {}
    symbol: str
    category: str = "DAY"
    latest_signal: Literal["BUY", "SELL"] | None = None  # 窗口内最后一根有信号的 K 线
    signal_date: str | None = None  # 该信号所在 K 线日期
    recent_signals: list[SignalScanRecentSignal] = []  # 窗口内全部信号（按时间正序）
    position: Literal["holding", "flat"] | None = None  # 扫描结束时策略仓位
    last_close: float | None = None
    last_bar_date: str | None = None
    error: str | None = None


class SignalScanResult(BaseModel):
    """信号扫描结果：全部子任务行 + 汇总计数。"""

    rows: list[SignalScanRow]
    total: int = 0
    buy_count: int = 0  # 窗口内有买入信号的行数
    sell_count: int = 0  # 窗口内有卖出信号的行数
    error_count: int = 0
    elapsed: float = 0.0


# ── 结果序列化 ─────────────────────────────────────────────────────────────────


def _clean_value(v: Any) -> Any:
    """把单个值转为 JSON 原生类型（递归处理容器）。"""
    # bool 必须先于 int 判断（bool 是 int 子类）
    if isinstance(v, bool):
        return v
    if isinstance(v, int | str):
        return v
    if isinstance(v, float):
        # NaN/Inf 无法 JSON 序列化，转 None
        import math

        return None if math.isnan(v) or math.isinf(v) else v
    if v is None:
        return v
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if hasattr(v, "item"):
        # numpy scalar → Python native（递归清洗，处理 numpy NaN）
        return _clean_value(v.item())
    if isinstance(v, dict):
        return {str(k): _clean_value(val) for k, val in v.items()}
    if isinstance(v, list | tuple):
        return [_clean_value(item) for item in v]
    # 兜底：不可序列化的对象转字符串
    return str(v)


def serialize_result(result: Any) -> dict[str, Any]:
    """把 BacktestResult（或其 to_dict()）清洗为纯 JSON 兼容字典。

    递归处理 performance / equity_curve / trades / positions / config，
    把 numpy scalar 转 Python 原生、NaN/Inf 转 None（JSON 不支持）、
    datetime 转 ISO 字符串。
    """
    if hasattr(result, "to_dict"):
        result = result.to_dict()
    return {str(k): _clean_value(v) for k, v in result.items()}
