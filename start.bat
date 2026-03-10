@echo off
chcp 65001 >nul 2>&1
title WOW Fishing Bot

echo ============================================
echo   WOW 自动钓鱼脚本 - 一键启动
echo ============================================
echo.

:: --- 检测 Python ---
where py >nul 2>&1
if %errorlevel%==0 (
    set PYTHON_CMD=py
    goto :found_python
)
where python >nul 2>&1
if %errorlevel%==0 (
    set PYTHON_CMD=python
    goto :found_python
)
echo [错误] 未检测到 Python，请先安装 Python 3.10+
echo 下载地址: https://www.python.org/downloads/
echo 安装时请勾选 "Add Python to PATH"
echo.
pause
exit /b 1

:found_python
echo [OK] 找到 Python: %PYTHON_CMD%
%PYTHON_CMD% --version
echo.

:: --- 创建虚拟环境 ---
if not exist ".venv\Scripts\activate.bat" (
    echo [安装] 创建虚拟环境...
    %PYTHON_CMD% -m venv .venv
    if %errorlevel% neq 0 (
        echo [错误] 创建虚拟环境失败
        pause
        exit /b 1
    )
    echo [OK] 虚拟环境创建成功
) else (
    echo [OK] 虚拟环境已存在
)
echo.

:: --- 激活虚拟环境并安装依赖 ---
call .venv\Scripts\activate.bat

echo [安装] 检查并安装依赖...
pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo [错误] 依赖安装失败，尝试重新安装...
    pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo [错误] 依赖安装失败，请检查网络连接
        pause
        exit /b 1
    )
)
echo [OK] 依赖安装完成
echo.

:: --- 检查配置文件 ---
if not exist "config.json" (
    if exist "config.example.json" (
        echo [配置] 未找到 config.json，从示例文件创建...
        copy config.example.json config.json >nul
        echo [OK] 已创建 config.json，请根据需要修改配置
    ) else (
        echo [警告] 未找到配置文件，将使用默认配置
    )
)
echo.

:: --- 启动 ---
echo ============================================
echo   启动钓鱼脚本，请切换到游戏窗口！
echo   按 Ctrl+C 停止
echo ============================================
echo.

%PYTHON_CMD% src\wow_fishing_bot.py --config config.json %*

echo.
echo [结束] 脚本已退出
pause
