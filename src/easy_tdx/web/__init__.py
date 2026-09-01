"""easy-tdx Web API — FastAPI REST + WebSocket layer.

Install with: pip install easy-tdx[web]

Usage::

    from easy_tdx.web import create_app

    app = create_app()

    # Run with uvicorn:
    # uvicorn easy_tdx.web:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import FastAPI


def create_app(
    host: str | None = None,
    port: int | None = None,
    timeout: float | None = None,
    *,
    enable_ui: bool = True,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        host: TDX server host (None = auto-detect best host).
        port: TDX server port (None = default 7709).
        timeout: Connection timeout in seconds.
        enable_ui: False 时不托管 Web UI 前端（纯 API 模式，serve --no-ui）。

    Returns:
        Configured FastAPI application instance.
    """
    from easy_tdx.web.app import _create_app

    return _create_app(host=host, port=port, timeout=timeout, enable_ui=enable_ui)


def app_factory() -> FastAPI:
    """Factory function for uvicorn --reload mode."""
    from easy_tdx.web.app import _create_app

    return _create_app()


__all__ = ["create_app", "app_factory"]
