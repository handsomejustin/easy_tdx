"""全局测试夹具。

- 默认关闭回测任务的 SQLite 持久化（``EASY_TDX_NO_TASK_DB=1``）：
  大量单测直接实例化 ``BacktestTaskRunner``，若不关闭会写真实的
  ``~/.easy_tdx/tasks.db`` 污染用户数据。task_store 专属测试通过
  ``monkeypatch.delenv`` + ``EASY_TDX_CONFIG_DIR`` 指向 ``tmp_path``
  显式重新开启（见 ``test_task_store.py``）。
"""

from __future__ import annotations

import os


def pytest_configure() -> None:
    os.environ.setdefault("EASY_TDX_NO_TASK_DB", "1")
