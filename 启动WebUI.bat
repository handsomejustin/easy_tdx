@echo off
setlocal
chcp 65001 >nul
title easy-tdx WebUI 一键启动

REM ============================================================
REM  easy-tdx WebUI 一键启动（后端 :8000 + 自动打开浏览器）
REM   - 自动检查虚拟环境 .venv（缺失则报错提示）
REM   - 自动检查前端构建产物 web-ui/dist（缺失则自动 npm 构建）
REM   - 端口 8000 被占用时提示并直接打开浏览器
REM   - 开发模式（热更新）：另开窗口 cd web-ui && npm run dev
REM ============================================================

cd /d "%~dp0"

set "VENV_EXE=%~dp0.venv\Scripts\easy-tdx.exe"
set "DIST=%~dp0web-ui\dist\index.html"

if not exist "%VENV_EXE%" (
    echo [错误] 未找到虚拟环境 .venv\Scripts\easy-tdx.exe
    echo        请先安装项目依赖后重试：
    echo          uv venv --python 3.12 .venv
    echo          uv pip install --python .venv -e ".[dev,web]"
    pause
    exit /b 1
)

if not exist "%DIST%" (
    echo [提示] 前端未构建（web-ui\dist 不存在），开始自动构建...
    pushd "%~dp0web-ui"
    set "npm_config_cache=%~dp0.npm-cache"
    call npm install --no-audit --no-fund
    if errorlevel 1 (
        popd
        echo [错误] npm install 失败
        pause
        exit /b 1
    )
    call npm run build
    popd
    if errorlevel 1 (
        echo [错误] 前端构建失败，请手动在 web-ui 下运行 npm run build 查看原因
        pause
        exit /b 1
    )
    echo [完成] 前端构建成功
)

REM 端口占用检查
netstat -ano | findstr /C:":8000" | findstr /C:"LISTENING" >nul 2>&1
if not errorlevel 1 (
    echo [提示] 8000 端口已被占用——可能已有 easy-tdx serve 在运行。
    choice /c YN /m "直接打开浏览器访问 http://127.0.0.1:8000 ? [Y/N]"
    if errorlevel 2 goto :start_serve
    start "" http://127.0.0.1:8000
    exit /b 0
)

:start_serve
echo.
echo ============================================
echo  正在启动 easy-tdx WebUI ...
echo  访问地址: http://127.0.0.1:8000
echo  按 Ctrl+C 停止服务
echo ============================================
echo.

"%VENV_EXE%" serve --enable-ex --host 127.0.0.1 --port 8000 --open-browser

echo.
echo 服务已停止。
pause
endlocal
