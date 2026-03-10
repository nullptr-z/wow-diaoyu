# WOW 自动化钓鱼插件

基于声音触发 + 视觉模板匹配的本地脚本。流程与 `plan.md` 一致：抛竿、监听上钩水声、定位鱼漂、点击收杆。

## 一键部署

1. start.bat — 一键启动脚本

双击即可运行，自动完成：

检测系统是否安装 Python（py 或 python）
创建 .venv 虚拟环境（首次运行）
安装 requirements.txt 中的依赖
如果没有 config.json 则从 config.example.json 复制一份
启动钓鱼脚本
支持传参，比如 start.bat --once 或 start.bat --list-devices。

2. build_exe.bat — 打包为 .exe

在 Windows 上双击运行，用 PyInstaller 打包成单个 dist\WowFishingBot.exe。打包后只需把 exe + config.json + assets/ 文件夹放在一起即可分发。

## 环境准备

建议 Python 3.10+。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Mac 需要在「系统设置 -> 隐私与安全性」中为终端/IDE 开启：

- 辅助功能（键鼠控制）
- 屏幕录制（截图）

## Windows 平台

建议使用 Python 3.10+，从 python.org 安装并勾选 “Add Python to PATH”。

```bash
py -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

音频采集建议：

- 优先启用「立体声混音」作为输入设备，或使用 WASAPI loopback（见配置项 `audio.wasapi_loopback`）。
- 用 `--list-devices` 找到输出设备索引，并写入 `audio.device`。

截图/输入建议：

- 游戏尽量用窗口化或无边框窗口，避免独占全屏导致截图异常。
- 如果游戏以管理员权限运行，脚本也需要管理员权限启动。

## Tauri UI (Windows)

The UI wraps the existing Python bot. Make sure the Python deps from `requirements.txt`
are installed in the same interpreter you point the UI at.

```bash
cargo install tauri-cli
cargo tauri dev
```

UI tips:

- Set `Python command` to your venv python, e.g. `.\.venv\Scripts\python.exe`.
- Keep `Config path` as `config.json` unless you want a different file.
- Use Load/Save to edit values, then Start to run.
- Use Record audio to save a wav sample for tuning the hook sound.
- Use Capture bobber, then click the bobber in game to save a template image.

Optional build:

```bash
cargo tauri build
```

## 配置

复制示例配置并按需修改：

```bash
cp config.example.json config.json
```

关键项：

- `vision.template_path`：鱼漂模板图路径（建议从游戏截图中裁剪出清晰的鱼漂小图）。
- `vision.search_region`：搜索区域，限制范围可提升速度和准确率。
- `audio.freq_target_hz` / `audio.ratio_threshold`：声音触发阈值，需根据环境微调。
- `audio.wasapi_loopback`：Windows 下启用输出设备回环采集（需要配合 `audio.device`）。

## 运行

```bash
python src/wow_fishing_bot.py --config config.json
```

可选：

- `--list-devices`：列出可用音频输入设备。
- `--once`：只执行一次抛竿-检测-点击流程，便于调试。
- `--record`：录制音频并保存为 wav，便于抓取上钩水声样本。
- `--record-seconds`：录制时长（秒），默认 8。
- `--record-out`：录音输出路径，默认 `recordings/hook.wav`。
- `--capture-bobber`：截取鱼漂模板并保存为 png。
- `--capture-size`：截取尺寸（像素），默认 72。
- `--capture-out`：截取输出路径，默认 `assets/bobber_template.png`。
- `--capture-timeout`：等待点击超时时间（秒），默认 10。

## 注意

这是本地自动化脚本，不包含游戏内任何修改。不同环境下阈值需要调参，建议先用 `--once` 调试配置。

# wow-diaoyu
