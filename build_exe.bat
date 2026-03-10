@echo off
chcp 65001 >nul 2>&1
title WOW Fishing Bot - 打包 EXE

echo ============================================
echo   WOW 自动钓鱼脚本 - 打包为 EXE
echo ============================================
echo.
echo [注意] 此脚本需在 Windows 上运行！
echo        不支持从 macOS/Linux 交叉编译
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
echo [错误] 未检测到 Python
pause
exit /b 1

:found_python
echo [OK] 找到 Python: %PYTHON_CMD%
echo.

:: --- 虚拟环境 ---
if not exist ".venv\Scripts\activate.bat" (
    echo [安装] 创建虚拟环境...
    %PYTHON_CMD% -m venv .venv
)
call .venv\Scripts\activate.bat

:: --- 安装依赖 + PyInstaller ---
echo [安装] 安装依赖和 PyInstaller...
pip install -r requirements.txt pyinstaller --quiet
if %errorlevel% neq 0 (
    echo [错误] 安装失败
    pause
    exit /b 1
)
echo [OK] 依赖安装完成
echo.

:: --- 打包 ---
echo [打包] 开始构建 EXE...
pyinstaller ^
    --name WowFishingBot ^
    --onefile ^
    --console ^
    --add-data "config.example.json;." ^
    --add-data "assets;assets" ^
    --hidden-import numpy ^
    --hidden-import cv2 ^
    --hidden-import sounddevice ^
    --hidden-import _sounddevice_data ^
    --hidden-import mss ^
    --hidden-import pynput ^
    --hidden-import pynput.keyboard._win32 ^
    --hidden-import pynput.mouse._win32 ^
    --collect-all sounddevice ^
    src\wow_fishing_bot.py

if %errorlevel% neq 0 (
    echo.
    echo [错误] 打包失败
    pause
    exit /b 1
)

echo.
echo ============================================
echo   打包完成！
echo   EXE 文件: dist\WowFishingBot.exe
echo.
echo   使用方法:
echo   1. 将 dist\WowFishingBot.exe 复制到任意目录
echo   2. 同目录下放置 config.json 和 assets 文件夹
echo   3. 双击运行或命令行运行:
echo      WowFishingBot.exe --config config.json
echo ============================================
echo.
pause
