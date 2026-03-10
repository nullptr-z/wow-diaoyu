import subprocess
import sys

args = [
    sys.executable, "-m", "PyInstaller",
    "--name", "WowFishingBot",
    "--onefile",
    "--console",
    "--add-data", "config.example.json;.",
    "--add-data", "assets;assets",
    "--hidden-import", "numpy",
    "--hidden-import", "cv2",
    "--hidden-import", "sounddevice",
    "--hidden-import", "_sounddevice_data",
    "--hidden-import", "mss",
    "--hidden-import", "pynput",
    "--hidden-import", "pynput.keyboard._win32",
    "--hidden-import", "pynput.mouse._win32",
    "--hidden-import", "pyaudiowpatch",
    "--collect-all", "pyaudiowpatch",
    "--collect-all", "sounddevice",
    "src\\wow_fishing_bot.py",
]

print("开始打包...")
result = subprocess.run(args)
if result.returncode == 0:
    print("\n打包完成！EXE 文件在 dist\\WowFishingBot.exe")
else:
    print("\n打包失败！")
input("按回车键退出...")
