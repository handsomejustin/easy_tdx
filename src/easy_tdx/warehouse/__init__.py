"""easy_tdx.warehouse — K 线本地数据仓库（DuckDB，可选依赖）。

快速开始::

    from easy_tdx.warehouse import KlineWarehouse, WarehouseSyncer

    wh = KlineWarehouse()                     # ~/.easy_tdx/warehouse.duckdb
    with get_mac_client() as client:          # 首次：全量；此后：增量补缺
        WarehouseSyncer(client, wh).sync(["SH:600519", "SZ:000001"])
    df = wh.query("SH", "600519", count=250)  # 默认忽略未收盘 provisional bar
"""

from easy_tdx.warehouse.store import KlineWarehouse, default_warehouse_path
from easy_tdx.warehouse.sync import SyncSummary, WarehouseSyncer

__all__ = [
    "KlineWarehouse",
    "WarehouseSyncer",
    "SyncSummary",
    "default_warehouse_path",
]
