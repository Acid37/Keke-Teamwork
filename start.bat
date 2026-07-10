@echo off
setlocal enabledelayedexpansion
title Coding Teamwork
cd /d "%~dp0"
chcp 65001 >nul

echo.
echo  ═══════════════════════════════════════
echo        Coding Teamwork  v0.2
echo  ═══════════════════════════════════════
echo.

REM ── 检查运行环境 ──
where python >nul 2>&1 || (echo  [错误] 未找到 Python & pause & exit /b 1)
where node   >nul 2>&1 || (echo  [错误] 未找到 Node.js & pause & exit /b 1)

REM ── 关闭上次未退出的服务 ──
set KILLED=0
for /f "tokens=5" %%P in ('netstat -aon 2^>nul ^| find ":8765" ^| find "LISTENING"') do (
    set KILLED=1
    echo  [清理] 正在关闭旧进程 ^(PID %%P^)...
    taskkill /F /PID %%P >nul 2>&1
    timeout /t 1 /nobreak >nul
)
if !KILLED!==0 echo  [就绪] 端口 8765 空闲

REM ── 首次运行安装依赖 ──
set CACHE_DIR=.cache
set DEPS_MARKER=%CACHE_DIR%\deps_installed
if not exist "%CACHE_DIR%" mkdir "%CACHE_DIR%"
if not exist "%DEPS_MARKER%" (
    echo  [1/3] 安装后端依赖...
    python -m pip install -e . --quiet || (echo  [错误] 安装失败 & pause & exit /b 1)
    echo .> "%DEPS_MARKER%"
)
if not exist frontend\node_modules (
    echo  [2/3] 安装前端依赖...
    pushd frontend
    call npm install --silent || (popd & echo  [错误] 安装失败 & pause & exit /b 1)
    popd
)

REM ── 构建前端（仅当 dist 不存在或源码更新时）──
set NEED_BUILD=0
if not exist frontend\dist\index.html (
    set NEED_BUILD=1
)
if exist frontend\dist\index.html (
    REM 比较 src 和 dist 的时间戳
    for /f "delims=" %%T in ('dir /s /b /o-d frontend\src\*.tsx frontend\src\*.ts frontend\src\*.css 2^>nul ^| findstr /r ".*" ^| findstr /n "^" ^| findstr "^1:"') do (
        for /f "tokens=1* delims=:" %%A in ("%%T") do set NEWEST_SRC=%%B
    )
    for %%F in (frontend\dist\index.html) do set DIST_TIME=%%~tF
    for %%F in (!NEWEST_SRC!) do set SRC_TIME=%%~tF
    if !SRC_TIME! gtr !DIST_TIME! set NEED_BUILD=1
)
if !NEED_BUILD!==1 (
    echo  [3/3] 构建前端页面...
    pushd frontend
    call npm run build || (popd & echo  [错误] 构建失败 & pause & exit /b 1)
    popd
    echo        构建完成
) else (
    echo  [3/3] 前端已构建，跳过
)
echo.

REM ── 启动后端服务（前台运行，单窗口）──
echo  启动服务中... 浏览器将自动打开
echo  按 Ctrl+C 停止服务
echo.

REM ── 后台等待端口就绪后打开浏览器 ──
start /b cmd /c "timeout /t 2 /nobreak >nul & for /l %%i in (1,1,30) do (timeout /t 1 /nobreak >nul & netstat -aon 2^>nul ^| find ":8765" ^| find "LISTENING" >nul && (start http://127.0.0.1:8765/ & exit /b))"

REM ── 前台运行后端，关闭此窗口即停止服务 ──
set CT_RELOAD=0
python -m backend.main

echo.
echo  服务已停止。
pause
