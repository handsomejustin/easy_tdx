"""中金所成交持仓排名（ccpm）领域模型与品种元数据。

品种科普信息（给 WebUI「小白」用户）集中在 :data:`PRODUCTS`，
CLI / API / WebUI 三端共用同一份文案，避免多处维护漂移。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from ..exceptions import TdxError


class CcpmError(TdxError):
    """ccpm 数据抓取/解析失败（网络错误、官网协议变更等）。"""


class CcpmNoDataError(CcpmError):
    """指定日期非交易日或数据尚未发布（官网返回 302 → error_404 页）。"""


@dataclass(frozen=True)
class ProductMeta:
    """期货品种元数据（纯静态科普信息，不含行情）。"""

    code: str  # 品种代码，如 IF
    name: str  # 全称，如 沪深300股指期货
    category: str  # 分类：股指期货 / 国债期货
    underlying: str  # 标的说明（跟踪哪个指数 / 名义国债条款）
    underlying_code: str  # 对应指数代码（国债期货为空串）
    unit: str  # 合约规模说明（乘数 / 面值）
    intro: str  # 一句话定位科普（这个品种代表市场的哪一块）

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


PRODUCTS: dict[str, ProductMeta] = {
    "IF": ProductMeta(
        code="IF",
        name="沪深300股指期货",
        category="股指期货",
        underlying=(
            "沪深300指数（000300）——沪深两市规模最大、流动性最好的 300 只股票，约覆盖 A 股六成市值"
        ),
        underlying_code="000300",
        unit="合约乘数 300 元/点（指数 4000 点时 1 手 ≈ 120 万元）",
        intro="代表「A 股大盘整体」的股指期货，是最主流的机构套保与多空博弈工具。",
    ),
    "IH": ProductMeta(
        code="IH",
        name="上证50股指期货",
        category="股指期货",
        underlying="上证50指数（000016）——沪市规模最大的 50 只超级蓝筹（银行、保险、白酒为主）",
        underlying_code="000016",
        unit="合约乘数 300 元/点（指数 3000 点时 1 手 ≈ 90 万元）",
        intro="代表「超大盘权重股」，与 IH 空单常被用来观察机构对蓝筹/50ETF 的套保力度。",
    ),
    "IC": ProductMeta(
        code="IC",
        name="中证500股指期货",
        category="股指期货",
        underlying="中证500指数（000905）——剔除沪深300成分股后市值居前的 500 只中盘股",
        underlying_code="000905",
        unit="合约乘数 200 元/点（指数 6000 点时 1 手 ≈ 120 万元）",
        intro="代表「中盘股」，中性策略（多头持票 + 空头 IC）最常用的对冲合约。",
    ),
    "IM": ProductMeta(
        code="IM",
        name="中证1000股指期货",
        category="股指期货",
        underlying="中证1000指数（000852）——剔除沪深300与中证500后市值居前的 1000 只小盘股",
        underlying_code="000852",
        unit="合约乘数 200 元/点（指数 6000 点时 1 手 ≈ 120 万元）",
        intro="代表「小盘股」，小市值风格博弈与量化对冲的主战场。",
    ),
    "TS": ProductMeta(
        code="TS",
        name="2年期国债期货",
        category="国债期货",
        underlying="面值 200 万元、票面利率 3% 的名义中短期国债（利率期货）",
        underlying_code="",
        unit="1 手面值 200 万元，按百元净价报价",
        intro="跟踪短端利率预期：价格涨 ≈ 市场预期利率下行，价格跌 ≈ 预期利率上行。",
    ),
    "TF": ProductMeta(
        code="TF",
        name="5年期国债期货",
        category="国债期货",
        underlying="面值 100 万元、票面利率 3% 的名义中期国债（利率期货）",
        underlying_code="",
        unit="1 手面值 100 万元，按百元净价报价",
        intro="中期利率预期工具，债券机构常用的久期管理手段。",
    ),
    "T": ProductMeta(
        code="T",
        name="10年期国债期货",
        category="国债期货",
        underlying="面值 100 万元、票面利率 3% 的名义长期国债（利率期货）",
        underlying_code="",
        unit="1 手面值 100 万元，按百元净价报价",
        intro="长端利率的「风向标」，成交持仓在国债期货里最活跃。",
    ),
    "TL": ProductMeta(
        code="TL",
        name="30年期国债期货",
        category="国债期货",
        underlying="面值 100 万元、票面利率 3% 的名义超长期国债（利率期货）",
        underlying_code="",
        unit="1 手面值 100 万元，按百元净价报价",
        intro="久期最长、对利率最敏感，近年机构「资产荒」下的热门品种。",
    ),
}

#: 品种展示顺序（股指在前、国债在后）
PRODUCT_CODES: list[str] = list(PRODUCTS)


def normalize_product(product: str) -> ProductMeta:
    """品种代码归一化（大小写/空格宽容），未知品种抛 ``ValueError``。"""
    code = str(product).strip().upper()
    meta = PRODUCTS.get(code)
    if meta is None:
        raise ValueError(f"未知品种 {product!r}，支持: {', '.join(PRODUCT_CODES)}")
    return meta


def list_products() -> list[dict[str, str]]:
    """全部品种元数据（供 CLI / API / WebUI 展示）。"""
    return [m.to_dict() for m in PRODUCTS.values()]
