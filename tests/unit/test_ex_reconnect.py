"""扩展行情 client 的指数退避重连测试（审计 #2）。

之前 ex 家族（ExTdxClient/MacExClient/AsyncExTdxClient/AsyncMacExClient）的 _execute
只重连 1 次无退避，与 A 股/MAC 的 4 次退避不一致。本测试验证统一后的退避行为，
并确认 MacExClient 重连后会重新 _login()。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from easy_tdx._reconnect import _RETRY_DELAYS
from easy_tdx.ex.client import AsyncExTdxClient, ExTdxClient
from easy_tdx.ex.commands.get_markets import GetExMarketsCmd
from easy_tdx.ex.mac_client import AsyncMacExClient, MacExClient
from easy_tdx.exceptions import TdxConnectionError


@pytest.fixture(autouse=True)
def _no_failover():
    """屏蔽跨主机故障转移：select_best_host_* 会真实探测网络（密闭性），
    且找到新主机时会多一轮 connect+login，使重试阶段的计数断言依赖网络环境。
    需要验证故障转移语义的测试可在用例内再覆盖此 patch。"""
    with (
        patch("easy_tdx.ex.client.select_best_host_sync", return_value=None),
        patch("easy_tdx.ex.client.select_best_host_async", new=AsyncMock(return_value=None)),
        patch("easy_tdx.ex.mac_client.select_best_host_sync", return_value=None),
        patch("easy_tdx.ex.mac_client.select_best_host_async", new=AsyncMock(return_value=None)),
    ):
        yield


class TestExTdxClientReconnect:
    def test_reconnect_succeeds_on_second_attempt(self) -> None:
        """首次抛 TdxConnectionError，重连后第 1 次重试成功。"""
        with patch("easy_tdx.ex.client.ExTdxConnection") as mock_conn_cls:
            mock_conn = MagicMock()
            mock_conn.execute.side_effect = [TdxConnectionError("down"), ["market"]]
            mock_conn_cls.return_value = mock_conn

            client = ExTdxClient("1.1.1.1", auto_reconnect=True)
            with patch("easy_tdx.ex.client.time.sleep"):
                result = client._execute(GetExMarketsCmd())
            assert result == ["market"]
            assert mock_conn.close.call_count == 1  # 重连了 1 次

    def test_all_retries_exhausted_raises_last(self) -> None:
        """4 次重试全部失败，应抛出异常，且 sleep 4 次。"""
        with patch("easy_tdx.ex.client.ExTdxConnection") as mock_conn_cls:
            mock_conn = MagicMock()
            mock_conn.execute.side_effect = TdxConnectionError("always down")
            mock_conn_cls.return_value = mock_conn

            client = ExTdxClient("1.1.1.1", auto_reconnect=True)
            with patch("easy_tdx.ex.client.time.sleep") as mock_sleep:
                with pytest.raises(TdxConnectionError):
                    client._execute(GetExMarketsCmd())
            assert mock_sleep.call_count == len(_RETRY_DELAYS)

    def test_no_reconnect_when_disabled(self) -> None:
        with patch("easy_tdx.ex.client.ExTdxConnection") as mock_conn_cls:
            mock_conn = MagicMock()
            mock_conn.execute.side_effect = TdxConnectionError("down")
            mock_conn_cls.return_value = mock_conn

            client = ExTdxClient("1.1.1.1", auto_reconnect=False)
            with patch("easy_tdx.ex.client.time.sleep") as mock_sleep:
                with pytest.raises(TdxConnectionError):
                    client._execute(GetExMarketsCmd())
            mock_sleep.assert_not_called()


class TestMacExClientReconnect:
    def test_reconnect_relogs_in(self) -> None:
        """MacExClient 每次重连后必须重新 _login()（MAC 协议特有）。"""
        with patch("easy_tdx.ex.mac_client.ExTdxConnection") as mock_conn_cls:
            mock_conn = MagicMock()
            mock_conn.execute.side_effect = [TdxConnectionError("down"), ["market"]]
            mock_conn_cls.return_value = mock_conn

            client = MacExClient("1.1.1.1", auto_reconnect=True)
            with (
                patch("easy_tdx.ex.mac_client.time.sleep"),
                patch.object(client, "_login") as mock_login,
            ):
                result = client._execute(GetExMarketsCmd())
            assert result == ["market"]
            # 重连 1 次应触发 1 次 _login
            assert mock_login.call_count == 1

    def test_all_retries_relogin_each_time(self) -> None:
        """4 次重试全失败时，每次重连都应 _login()（共 4 次；故障转移已被屏蔽）。"""
        with patch("easy_tdx.ex.mac_client.ExTdxConnection") as mock_conn_cls:
            mock_conn = MagicMock()
            mock_conn.execute.side_effect = TdxConnectionError("always down")
            mock_conn_cls.return_value = mock_conn

            client = MacExClient("1.1.1.1", auto_reconnect=True)
            with (
                patch("easy_tdx.ex.mac_client.time.sleep"),
                patch.object(client, "_login") as mock_login,
            ):
                with pytest.raises(TdxConnectionError):
                    client._execute(GetExMarketsCmd())
            assert mock_login.call_count == len(_RETRY_DELAYS)

    def test_failover_stage_relogs_in_and_raises(self) -> None:
        """跨主机故障转移找到新主机时也必须 _login()；仍失败则抛出（共 5 次）。"""
        with patch("easy_tdx.ex.mac_client.ExTdxConnection") as mock_conn_cls:
            mock_conn = MagicMock()
            mock_conn.execute.side_effect = TdxConnectionError("always down")
            mock_conn_cls.return_value = mock_conn

            client = MacExClient("1.1.1.1", auto_reconnect=True)
            with (
                patch("easy_tdx.ex.mac_client.time.sleep"),
                patch.object(client, "_login") as mock_login,
                patch("easy_tdx.ex.mac_client.select_best_host_sync", return_value="2.2.2.2"),
            ):
                with pytest.raises(TdxConnectionError):
                    client._execute(GetExMarketsCmd())
            # 4 次退避重连 + 1 次故障转移 = 5 次 _login
            assert mock_login.call_count == len(_RETRY_DELAYS) + 1


class TestAsyncExTdxClientReconnect:
    def test_async_all_retries_exhausted(self) -> None:
        async def main() -> None:
            with patch("easy_tdx.ex.client.AsyncExTdxConnection") as mock_conn_cls:
                mock_conn = MagicMock()

                async def _execute(cmd: object) -> list[str]:
                    raise TdxConnectionError("always down")

                mock_conn.execute = _execute

                async def _noop() -> None:
                    return None

                mock_conn.close = _noop
                mock_conn.connect = _noop
                mock_conn_cls.return_value = mock_conn

                client = AsyncExTdxClient("1.1.1.1", auto_reconnect=True, heartbeat_interval=0)
                with patch("easy_tdx.ex.client.asyncio.sleep") as mock_sleep:
                    with pytest.raises(TdxConnectionError):
                        await client._execute(GetExMarketsCmd())
                    assert mock_sleep.call_count == len(_RETRY_DELAYS)

        asyncio.run(main())


class TestAsyncMacExClientReconnect:
    def test_async_relogin_each_retry(self) -> None:
        """AsyncMacExClient 每次重连后必须重新 _login()（覆盖 async relogin 路径）。"""

        async def main() -> None:
            with patch("easy_tdx.ex.mac_client.AsyncExTdxConnection") as mock_conn_cls:
                mock_conn = MagicMock()

                async def _execute(cmd: object) -> list[str]:
                    raise TdxConnectionError("always down")

                mock_conn.execute = _execute

                async def _noop() -> None:
                    return None

                mock_conn.close = _noop
                mock_conn.connect = _noop
                mock_conn_cls.return_value = mock_conn

                client = AsyncMacExClient("1.1.1.1", auto_reconnect=True, heartbeat_interval=0)
                with (
                    patch("easy_tdx.ex.mac_client.asyncio.sleep"),
                    patch.object(client, "_login", new_callable=AsyncMock) as mock_login,
                ):
                    with pytest.raises(TdxConnectionError):
                        await client._execute(GetExMarketsCmd())
                    # 4 次重连应触发 4 次 _login
                    assert mock_login.call_count == len(_RETRY_DELAYS)

        asyncio.run(main())


class TestBackoffDelayValues:
    """验证退避延迟值序列与 _RETRY_DELAYS 完全一致（防硬编码回归）。"""

    def test_sync_ex_uses_exact_delays(self) -> None:
        with patch("easy_tdx.ex.client.ExTdxConnection") as mock_conn_cls:
            mock_conn = MagicMock()
            mock_conn.execute.side_effect = TdxConnectionError("down")
            mock_conn_cls.return_value = mock_conn

            client = ExTdxClient("1.1.1.1", auto_reconnect=True)
            with patch("easy_tdx.ex.client.time.sleep") as mock_sleep:
                with pytest.raises(TdxConnectionError):
                    client._execute(GetExMarketsCmd())
            actual = tuple(c.args[0] for c in mock_sleep.call_args_list)
            assert actual == _RETRY_DELAYS


class TestMacExLoginRetriedOnConnectionError:
    """登录握手期抛 TdxConnectionError 应继续重试（验证 _login 纳入 inner try）。"""

    def test_login_conn_error_triggers_full_retry(self) -> None:
        """_login 抛 TdxConnectionError 时不应逃逸，应跑完 4 次重试。"""
        with patch("easy_tdx.ex.mac_client.ExTdxConnection") as mock_conn_cls:
            mock_conn = MagicMock()
            mock_conn.execute.side_effect = TdxConnectionError("always down")
            mock_conn_cls.return_value = mock_conn

            client = MacExClient("1.1.1.1", auto_reconnect=True)
            # _login 抛 TdxConnectionError（模拟登录握手期连接又断）
            with (
                patch("easy_tdx.ex.mac_client.time.sleep") as mock_sleep,
                patch.object(client, "_login", side_effect=TdxConnectionError("login lost")),
            ):
                with pytest.raises(TdxConnectionError):
                    client._execute(GetExMarketsCmd())
            # 关键：_login 异常被纳入重试，4 次都跑了（而非第 1 次就逃逸）
            assert mock_sleep.call_count == len(_RETRY_DELAYS)


# --------------------------------------------------------------------------- #
# MAC/EX client 健康分联动（防 pattern-fix 回归）
# --------------------------------------------------------------------------- #


class TestExClientHealthTracking:
    """锁定修复：MAC/EX 的 _execute 必须像 A 股 client 一样写健康分。

    此前只有 A 股 TdxClient/AsyncTdxClient 注入了 record_failure/record_success，
    MAC/EX 的 6 个 _execute 漏改（它们的服务器 IP 与 A 股不重叠，失败时不会被
    降权，功能残缺）。本测试防止再次漏改。
    """

    def test_ex_client_failure_records_health(self) -> None:
        """ExTdxClient 连接失败时应调 record_failure 降权当前 host。"""
        from easy_tdx._health import reset_health

        reset_health()
        try:
            with (
                patch("easy_tdx.ex.client.ExTdxConnection") as mock_conn_cls,
                patch("easy_tdx.ex.client.time.sleep"),
                patch("easy_tdx.ex.client.select_best_host_sync", return_value=None),
            ):
                mock_conn = MagicMock()
                mock_conn.execute.side_effect = TdxConnectionError("down")
                mock_conn_cls.return_value = mock_conn

                client = ExTdxClient("ex-bad", auto_reconnect=True)
                with pytest.raises(TdxConnectionError):
                    client._execute(GetExMarketsCmd())

            from easy_tdx._health import get_score

            # ex-bad 经历首次 + 4 次重试共 5 次失败，score 应远低于 1.0
            assert get_score("ex-bad") < 1.0
        finally:
            reset_health()

    def test_ex_client_success_records_health(self) -> None:
        """ExTdxClient 首次成功应调 record_success（score 保持 1.0）。"""
        from easy_tdx._health import get_score, reset_health

        reset_health()
        try:
            with patch("easy_tdx.ex.client.ExTdxConnection") as mock_conn_cls:
                mock_conn = MagicMock()
                mock_conn.execute.return_value = ["market"]
                mock_conn_cls.return_value = mock_conn

                client = ExTdxClient("ex-good", auto_reconnect=True)
                result = client._execute(GetExMarketsCmd())
                assert result == ["market"]
            assert get_score("ex-good") == 1.0
        finally:
            reset_health()

    def test_mac_ex_client_failure_records_health(self) -> None:
        """MacExClient（含 _login 重连路径）连接失败也应降权当前 host。"""
        from easy_tdx._health import reset_health

        reset_health()
        try:
            with (
                patch("easy_tdx.ex.mac_client.ExTdxConnection") as mock_conn_cls,
                patch("easy_tdx.ex.mac_client.time.sleep"),
                patch("easy_tdx.ex.mac_client.select_best_host_sync", return_value=None),
            ):
                mock_conn = MagicMock()
                mock_conn.execute.side_effect = TdxConnectionError("down")
                mock_conn_cls.return_value = mock_conn

                client = MacExClient("macex-bad", auto_reconnect=True)
                with pytest.raises(TdxConnectionError):
                    client._execute(GetExMarketsCmd())

            from easy_tdx._health import get_score

            assert get_score("macex-bad") < 1.0
        finally:
            reset_health()

    def test_async_ex_client_failure_records_health(self) -> None:
        """AsyncExTdxClient 连接失败时也应降权。"""
        from easy_tdx._health import reset_health

        reset_health()
        try:

            async def main() -> None:
                with patch("easy_tdx.ex.client.AsyncExTdxConnection") as mock_conn_cls:
                    mock_conn = MagicMock()

                    async def _execute(cmd: object) -> list[str]:
                        raise TdxConnectionError("down")

                    async def _noop() -> None:
                        return None

                    mock_conn.execute = _execute
                    mock_conn.close = _noop
                    mock_conn.connect = _noop
                    mock_conn_cls.return_value = mock_conn

                    client = AsyncExTdxClient("aex-bad", auto_reconnect=True, heartbeat_interval=0)
                    with (
                        patch("easy_tdx.ex.client.asyncio.sleep"),
                        patch(
                            "easy_tdx.ex.client.select_best_host_async",
                            new_callable=AsyncMock,
                            return_value=None,
                        ),
                    ):
                        with pytest.raises(TdxConnectionError):
                            await client._execute(GetExMarketsCmd())

            asyncio.run(main())

            from easy_tdx._health import get_score

            assert get_score("aex-bad") < 1.0
        finally:
            reset_health()
