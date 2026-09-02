"""中金所成交持仓排名（ccpm）客户端。

数据源：中国金融期货交易所官网「成交持仓排名」页
http://www.cffex.com.cn/cn/ccpm.html

实际数据文件（每个交易日收盘后约 16:10 北京时间批量生成）::

    http://www.cffex.com.cn/sj/ccpm/{YYYYMM}/{DD}/{品种}.xml

协议要点（2026-09 实测）：

- 官网 JS 在 URL 上拼的 ``?id=<随机数>`` 仅为防浏览器缓存参数，无语义，可省略。
- XML（UTF-8）包含该品种当日**所有合约** × 三类排名 × 各前 20 名会员：
  ``datatypeid`` 0=成交量 / 1=持买单量（多单）/ 2=持卖单量（空单）。
- 非交易日或未发布时官网返回 302 → ``error_404.html``：HTTP 客户端若
  自动跟随重定向会拿到 200 的错误页，必须禁用重定向并把 302/404 识别为
  「无数据」（:class:`CcpmNoDataError`）。
- 仅支持 http（https 证书握手失败），无鉴权/无频控。
- 每个交易日的数据发布后不可变 → 按日落盘缓存
  ``~/.easy_tdx/cache/ccpm/{YYYYMMDD}/{品种}.json``（随
  ``EASY_TDX_CONFIG_DIR``），历史日期二次查询零网络请求。
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib import request as urlrequest
from urllib.error import HTTPError
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

import pandas as pd

from .models import CcpmError, CcpmNoDataError, normalize_product

logger = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_BASE_URL = "http://www.cffex.com.cn/sj/ccpm/{yyyymm}/{dd}/{product}.xml"
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

#: datatypeid → 宽表列前缀（0=成交量 / 1=持买单量 / 2=持卖单量，官网 ccpm.js 语义）
_TYPE_KEYS = {0: "vol", 1: "long", 2: "short"}

#: 宽表列（合约 × 排名 对齐三类排名，与官网 CSV 同构）
WIDE_COLUMNS = [
    "trading_day",
    "product",
    "instrument",
    "rank",
    "vol_member",
    "vol",
    "vol_chg",
    "long_member",
    "long_pos",
    "long_chg",
    "short_member",
    "short_pos",
    "short_chg",
]


class _NoRedirectHandler(urlrequest.HTTPRedirectHandler):
    """禁止跟随重定向：非交易日的 302 → error_404.html 不能被当成数据页。"""

    def redirect_request(
        self,
        req: urlrequest.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urlrequest.Request | None:
        return None


_OPENER = urlrequest.build_opener(_NoRedirectHandler)


def _fetch_xml(url: str, timeout: float) -> str:
    """GET 原始 XML 文本（stdlib urllib，monkeypatch 点）。

    302/404 → :class:`CcpmNoDataError`（非交易日/未发布）；其他 HTTP 错误 →
    :class:`CcpmError`。
    """
    req = urlrequest.Request(url, headers={"User-Agent": _UA})
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            return str(resp.read(), encoding="utf-8")
    except HTTPError as e:
        if e.code in (301, 302, 303, 307, 308, 404):
            raise CcpmNoDataError(f"该日期非交易日或数据尚未发布: {url}") from e
        raise CcpmError(f"中金所返回 HTTP {e.code}: {url}") from e


def _today_shanghai() -> date:
    return datetime.now(_SHANGHAI_TZ).date()


def normalize_date(value: str | date | datetime | None) -> date:
    """日期归一化：接受 ``date``/``datetime``/``YYYY-MM-DD``/``YYYYMMDD``。"""
    if value is None:
        return _today_shanghai()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip().replace("-", "").replace("/", "")
    if not re.fullmatch(r"\d{8}", s):
        raise ValueError(f"日期格式应为 YYYY-MM-DD 或 YYYYMMDD: {value}")
    return datetime.strptime(s, "%Y%m%d").date()


def _to_int(v: str | None) -> int | None:
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    try:
        return int(v)
    except ValueError:
        return None


def parse_xml(text: str) -> list[dict[str, Any]]:
    """解析 positionRank XML → 宽表行列表（合约 × 排名 对齐三类排名）。

    XML 长表结构（每条记录一个 ``<data>`` 节点）::

        <positionRank><data>
            <instrumentid>IF2609</instrumentid> <tradingday>20260902</tradingday>
            <datatypeid>1</datatypeid> <rank>1</rank>
            <shortname>国泰君安(代客)</shortname> <volume>22066</volume>
            <varvolume>-789</varvolume> <partyid>0001</partyid> <productid>IF</productid>
        </data>...</positionRank>

    某合约某类型缺某排名时对应单元格置 None（不丢行）。
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise CcpmError(f"XML 解析失败（可能返回了错误页）: {e}") from e

    def _g(node: Any, tag: str) -> str:
        el = node.find(tag)
        return (el.text or "").strip() if el is not None else ""

    cells: dict[tuple[str, int, int], dict[str, Any]] = {}
    meta: dict[str, dict[str, str]] = {}
    for node in root.findall("data"):
        instrument = _g(node, "instrumentid")
        dtype = _to_int(_g(node, "datatypeid"))
        rank = _to_int(_g(node, "rank"))
        if not instrument or dtype not in _TYPE_KEYS or rank is None:
            continue
        cells[(instrument, dtype, rank)] = {
            "member": _g(node, "shortname"),
            "value": _to_int(_g(node, "volume")),
            "chg": _to_int(_g(node, "varvolume")),
        }
        meta[instrument] = {
            "trading_day": _g(node, "tradingday"),
            "product": _g(node, "productid"),
        }

    rows: list[dict[str, Any]] = []
    ranks = sorted({r for (_, _, r) in cells})
    for instrument in sorted(meta):
        for rk in ranks:
            row: dict[str, Any] = {
                "trading_day": meta[instrument]["trading_day"],
                "product": meta[instrument]["product"],
                "instrument": instrument,
                "rank": rk,
            }
            for dtype, key in _TYPE_KEYS.items():
                cell = cells.get((instrument, dtype, rk))
                suffix = "vol" if key == "vol" else ("long_pos" if key == "long" else "short_pos")
                row[f"{key}_member"] = cell["member"] if cell else None
                row[suffix] = cell["value"] if cell else None
                row[f"{key}_chg"] = cell["chg"] if cell else None
            rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# 按日文件缓存（交易日数据发布后不可变，永不过期）
# ---------------------------------------------------------------------------


def _cache_dir() -> Path:
    base = Path(os.environ.get("EASY_TDX_CONFIG_DIR", str(Path.home() / ".easy_tdx")))
    return base / "cache" / "ccpm"


def _cache_path(d: date, product: str) -> Path:
    return _cache_dir() / d.strftime("%Y%m%d") / f"{product}.json"


def _load_cache(d: date, product: str) -> list[dict[str, Any]] | None:
    path = _cache_path(d, product)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text("utf-8"))
        rows = raw.get("rows")
        return rows if isinstance(rows, list) and rows else None
    except Exception:  # noqa: BLE001 — 损坏缓存当未命中，走网络
        return None


def _save_cache(d: date, product: str, rows: list[dict[str, Any]]) -> None:
    try:
        path = _cache_path(d, product)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "trading_day": d.strftime("%Y%m%d"),
            "product": product,
            "fetched_at": datetime.now(_SHANGHAI_TZ).isoformat(),
            "count": len(rows),
            "rows": rows,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False), "utf-8")
    except Exception as e:  # noqa: BLE001 — 缓存写失败不影响主流程
        logger.warning("ccpm 缓存写入失败: %s", e)


class CcpmClient:
    """中金所成交持仓排名客户端（无状态 HTTP + 按日文件缓存）。

    用法::

        from easy_tdx.ccpm import CcpmClient

        client = CcpmClient()
        df = client.get_rank("IF", "2026-09-02")  # 指定交易日（宽表 DataFrame）
        df = client.latest_rank("IF")             # 自动回溯最近有数据的交易日
    """

    def __init__(self, *, timeout: float = 15.0, use_cache: bool = True) -> None:
        self.timeout = timeout
        self.use_cache = use_cache

    def get_rank(
        self,
        product: str,
        trade_date: str | date | datetime | None = None,
        *,
        refresh: bool = False,
    ) -> pd.DataFrame:
        """获取某品种某交易日的成交持仓排名（前 20 名会员 × 全部合约）。

        Args:
            product: 品种代码（IF/IH/IC/IM/TS/TF/T/TL，大小写宽容）。
            trade_date: 交易日（``YYYY-MM-DD``/``YYYYMMDD``/``date``），
                缺省为今天（上海时区）。
            refresh: 忽略本地缓存强制重新抓取。

        Returns:
            宽表 ``DataFrame``，列见 :data:`WIDE_COLUMNS`；每行 = 某合约某排名，
            三类排名（成交量 / 持买单量 / 持卖单量）并排对齐，与官网 CSV 同构。

        Raises:
            CcpmNoDataError: 该日期非交易日或数据尚未发布（约 16:15 后生成）。
            ValueError: 品种/日期格式非法。
        """
        meta = normalize_product(product)
        d = normalize_date(trade_date)

        rows = _load_cache(d, meta.code) if self.use_cache and not refresh else None
        if rows is None:
            url = _BASE_URL.format(
                yyyymm=d.strftime("%Y%m"), dd=d.strftime("%d"), product=meta.code
            )
            try:
                rows = parse_xml(_fetch_xml(url, self.timeout))
            except (CcpmError, CcpmNoDataError):
                raise
            except Exception as e:  # noqa: BLE001 — HTTP/网络统一转领域异常
                raise CcpmError(f"中金所 ccpm 抓取失败: {e}") from e
            if self.use_cache and rows:
                _save_cache(d, meta.code, rows)
        return pd.DataFrame(rows, columns=WIDE_COLUMNS)

    def latest_rank(
        self, product: str, *, max_back: int = 15, refresh: bool = False
    ) -> pd.DataFrame:
        """自动回溯到最近一个有数据的交易日（从今天起最多往回找 ``max_back`` 天）。

        节假日/周末/当日未发布（约 16:15 前）会自然回退到上一交易日，
        春节等长假（≤8 个自然日）也在默认回溯范围内。
        """
        d = _today_shanghai()
        last_err: Exception | None = None
        for _ in range(max_back + 1):
            try:
                return self.get_rank(product, d, refresh=refresh)
            except CcpmNoDataError as e:
                last_err = e
                d = d - timedelta(days=1)
        raise CcpmError(
            f"最近 {max_back + 1} 个自然日内未找到 {str(product).upper()} 的成交持仓数据"
        ) from last_err
