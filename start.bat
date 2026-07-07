@echo off
setlocal enabledelayedexpansion
title Coding Teamwork 启动器
cd /d "%~dp0"
chcp 65001 >nul

echo.
echo  ═══════════════════════════════════════
echo        Coding Teamwork  v0.1
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
    timeout /t 2 /nobreak >nul
)
if !KILLED!==0 echo  [就绪] 端口 8765 空闲

REM ── 首次运行安装依赖 ──
set CACHE_DIR=.cache
set DEPS_MARKER=%CACHE_DIR%\deps_installed
if not exist "%CACHE_DIR%" mkdir "%CACHE_DIR%"
if not exist "%DEPS_MARKER%" (
    echo  [1/4] 安装后端依赖...
    python -m pip install -e . --quiet || (echo  [错误] 安装失败 & pause & exit /b 1)
    echo .> "%DEPS_MARKER%"
)
if not exist frontend\node_modules (
    echo  [2/4] 安装前端依赖...
    cd frontend
    call npm install --silent || (cd .. & echo  [错误] 安装失败 & pause & exit /b 1)
    cd ..
)

REM ── 构建前端 ──
echo  [3/4] 构建前端页面...
cd frontend
call npm run build || (cd .. & echo  [错误] 构建失败 & pause & exit /b 1)
cd ..
echo        构建完成
echo.

REM ── 启动后端服务 ──
echo  [4/4] 启动后端服务...

REM 写入临时启动脚本，确保热重载生效
(echo @echo off
 echo set CT_RELOAD=1
 echo python -m backend.main
 echo pause
) > "%TEMP%\ct-start.bat"

start "Coding Teamwork 服务" "%TEMP%\ct-start.bat"

REM ── 等待端口就绪后打开浏览器 ──
echo        等待服务启动...
set n=0
:wait
timeout /t 1 /nobreak >nul
for /f "tokens=5" %%P in ('netstat -aon 2^>nul ^| find ":8765" ^| find "LISTENING"') do goto :ready
set /a n+=1
if !n! lss 30 goto :wait
echo  [错误] 服务 30 秒内未启动，请检查服务窗口的错误信息
pause & exit /b 1

:ready
echo        服务已启动 ^(耗时 !n! 秒^)

start http://127.0.0.1:8765/

echo.
echo  ═══════════════════════════════════════
echo    打开  http://127.0.0.1:8765/
echo    关闭  服务窗口即可停止
echo  ═══════════════════════════════════════
echo.
pause
del "%TEMP%\ct-start.bat" 2>nul
