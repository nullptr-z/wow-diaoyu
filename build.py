import os
import platform
import shutil
import struct
import subprocess
import sys


def get_target_triple():
    """Detect the Rust target triple for the current platform."""
    machine = platform.machine().lower()
    system = platform.system().lower()

    if system == "windows":
        arch = "x86_64" if struct.calcsize("P") * 8 == 64 else "i686"
        return f"{arch}-pc-windows-msvc"
    elif system == "darwin":
        arch = "aarch64" if machine == "arm64" else "x86_64"
        return f"{arch}-apple-darwin"
    elif system == "linux":
        arch = "x86_64" if machine == "x86_64" else machine
        return f"{arch}-unknown-linux-gnu"
    else:
        raise RuntimeError(f"Unsupported platform: {system} {machine}")


def get_separator():
    """PyInstaller uses ; on Windows and : on Unix for --add-data."""
    return ";" if platform.system() == "Windows" else ":"


def main():
    target_triple = get_target_triple()
    sep = get_separator()
    is_windows = platform.system() == "Windows"

    # Platform-specific hidden imports
    hidden_imports = [
        "numpy", "cv2", "sounddevice", "_sounddevice_data", "mss", "pynput",
    ]
    if is_windows:
        hidden_imports += [
            "pynput.keyboard._win32", "pynput.mouse._win32",
            "pyaudiowpatch",
        ]
    else:
        hidden_imports += [
            "pynput.keyboard._darwin", "pynput.mouse._darwin",
        ]

    collect_all = ["sounddevice"]
    if is_windows:
        collect_all.append("pyaudiowpatch")

    # Source script path
    src_script = os.path.join("src", "wow_fishing_bot.py")

    args = [
        sys.executable, "-m", "PyInstaller",
        "--name", "WowFishingBot",
        "--onefile",
        "--console",
        "--add-data", f"config.example.json{sep}.",
        "--add-data", f"assets{sep}assets",
    ]
    for mod in hidden_imports:
        args += ["--hidden-import", mod]
    for pkg in collect_all:
        args += ["--collect-all", pkg]
    args.append(src_script)

    print(f"目标平台: {target_triple}")
    print("开始打包 Python 为独立可执行文件...")
    result = subprocess.run(args)
    if result.returncode != 0:
        print("\n打包失败！")
        return 1

    # Copy to src-tauri/binaries/ with target triple suffix for Tauri sidecar
    binaries_dir = os.path.join("src-tauri", "binaries")
    os.makedirs(binaries_dir, exist_ok=True)

    exe_ext = ".exe" if is_windows else ""
    src_exe = os.path.join("dist", f"WowFishingBot{exe_ext}")
    dst_exe = os.path.join(binaries_dir, f"WowFishingBot-{target_triple}{exe_ext}")

    if not os.path.exists(src_exe):
        print(f"\n错误: 找不到打包产物 {src_exe}")
        return 1

    shutil.copy2(src_exe, dst_exe)
    print(f"\n打包完成！")
    print(f"  PyInstaller 产物: {src_exe}")
    print(f"  Tauri sidecar:    {dst_exe}")
    print(f"\n现在可以运行 'cargo tauri build' 构建完整应用")
    return 0


if __name__ == "__main__":
    sys.exit(main())
