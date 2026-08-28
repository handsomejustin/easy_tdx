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
    enable_ex: bool = False,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        host: TDX server host (None = auto-detect best host).
        port: TDX server port (None = default 7709).
        timeout: Connection timeout in seconds.
        enable_ex: Enable extended-market (US/HK/futures) MAC client;
            endpoints under /ex/* return 503 when disabled.

    Returns:
        Configured FastAPI application instance.
    """
    from easy_tdx.web.app import _create_app

    return _create_app(host=host, port=port, timeout=timeout, enable_ex=enable_ex)


def app_factory() -> FastAPI:
    """Factory function for uvicorn --reload mode."""
    import os

    from easy_tdx.web.app import _create_app

    enable_ex = os.environ.get("EASY_TDX_ENABLE_EX", "") == "1"
    return _create_app(enable_ex=enable_ex)


__all__ = ["create_app", "app_factory"]
