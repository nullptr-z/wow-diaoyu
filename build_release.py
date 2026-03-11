"""
一键构建脚本：先用 PyInstaller 打包 Python，再用 Tauri 构建完整应用。

用法:
    python build_release.py
"""
import os
import subprocess
import sys


def run(cmd, desc):
    print(f"\n{'='*50}")
    print(f"  {desc}")
    print(f"{'='*50}\n")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"\n[错误] {desc} 失败 (exit code {result.returncode})")
        sys.exit(1)


def main():
    # Step 1: PyInstaller 打包 Python → src-tauri/binaries/
    run([sys.executable, "build.py"], "打包 Python 为独立可执行文件")

    # Step 2: Tauri 构建完整应用
    run(["cargo", "tauri", "build"], "构建 Tauri 应用")

    print(f"\n{'='*50}")
    print(f"  构建完成！")
    print(f"{'='*50}")
    print(f"\n安装包位于 src-tauri/target/release/bundle/ 目录下")


if __name__ == "__main__":
    main()
