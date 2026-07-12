@echo off
setlocal enabledelayedexpansion
title Keke Teamwork
cd /d "%~dp0"
chcp 65001 >nul

REM ============================================================
REM  Keke Teamwork - Windows launcher
REM
REM  Usage:
REM    start.bat                  (default: do not open browser)
REM    start.bat --open-browser   (open browser when ready)
REM
REM  Single-window mode: closing this window stops the backend.
REM ============================================================

set "AUTO_OPEN_BROWSER=0"
if /I "%~1"=="--open-browser" set "AUTO_OPEN_BROWSER=1"

set "PORT=8765"
set "URL=http://127.0.0.1:%PORT%/"
set "DEPS_MARKER=.cache\deps_installed"

echo.
echo  ═══════════════════════════════════════
echo        Keke Teamwork  v0.2
echo  ═══════════════════════════════════════
echo.

REM ── 1. 检查运行环境 ──
echo  [1/4] 检查运行环境...
where python >nul 2>&1 || (echo  [错误] 未找到 Python，请先安装 Python 3.11+ 并加入 PATH。 & pause & exit /b 1)
where node   >nul 2>&1 || (echo  [错误] 未找到 Node.js，请先安装 Node.js 18+ 并加入 PATH。 & pause & exit /b 1)

REM ── 2. 关闭上次未退出的服务 ──
echo  [2/4] 检查端口占用...
set KILLED=0
for /f "tokens=5" %%P in ('netstat -aon 2^>nul ^| find ":%PORT%" ^| find "LISTENING"') do (
    set KILLED=1
    echo  [信息] 正在关闭旧进程 ^(PID %%P^)...
    taskkill /F /PID %%P >nul 2>&1
    timeout /t 1 /nobreak >nul
)
if !KILLED!==0 echo  [信息] 端口 %PORT% 空闲

REM ── 3. 安装依赖（仅首次）──
echo  [3/4] 检查依赖...
if not exist ".cache" mkdir ".cache"
if not exist "%DEPS_MARKER%" (
    echo  [信息] 正在安装后端依赖（首次）...
    python -m pip install -e . --quiet || (echo  [错误] 后端依赖安装失败。 & pause & exit /b 1)
    echo .> "%DEPS_MARKER%"
)
if not exist frontend\node_modules (
    echo  [信息] 正在安装前端依赖（首次）...
    pushd frontend
    call npm install --silent || (popd & echo  [错误] 前端依赖安装失败。 & pause & exit /b 1)
    popd
)

REM ── 4. 构建前端（仅当 dist 不存在或源码更新时）──
set NEED_BUILD=0
if not exist frontend\dist\index.html (
    set NEED_BUILD=1
)
if exist frontend\dist\index.html (
    for /f "delims=" %%T in ('dir /s /b /o-d frontend\src\*.tsx frontend\src\*.ts frontend\src\*.css 2^>nul ^| findstr /r "." ^| findstr /n "^" ^| findstr "^1:"') do (
        for /f "tokens=1* delims=:" %%A in ("%%T") do set NEWEST_SRC=%%B
    )
    for %%F in (frontend\dist\index.html) do set DIST_TIME=%%~tF
    for %%F in (!NEWEST_SRC!) do set SRC_TIME=%%~tF
    if !SRC_TIME! gtr !DIST_TIME! set NEED_BUILD=1
)
if !NEED_BUILD!==1 (
    echo  [4/4] 构建前端页面...
    pushd frontend
    call npm run build || (popd & echo  [错误] 前端构建失败。 & pause & exit /b 1)
    popd
    echo  [信息] 构建完成
) else (
    echo  [4/4] 前端已构建，跳过
)
echo.

REM ── 启动后端服务 ──
echo  [信息] 服务即将启动
echo  [信息] 访问地址：%URL%
echo  [信息] 按 Ctrl+C 停止服务
echo.

if "%AUTO_OPEN_BROWSER%"=="1" (
    start /b powershell -NoProfile -WindowStyle Hidden -Command "$u='%URL%'; for ($i=0; $i -lt 30; $i++) { try { $c=New-Object System.Net.Sockets.TcpClient; $c.BeginConnect('127.0.0.1',%PORT%,$null,$null)|Out-Null; Start-Sleep -Milliseconds 200; if ($c.Connected) { $c.Close(); Start-Process $u; return } } catch {} Start-Sleep -Seconds 1 }"
)

set CT_RELOAD=0
python -m backend.main

echo.
echo  [信息] 服务已停止
pause >nul
