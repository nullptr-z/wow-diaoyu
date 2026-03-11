# WOW 自动钓鱼

基于声音触发 + 视觉模板匹配的本地自动化工具。流程：抛竿 → 监听咬钩音效 → 定位鱼漂 → 点击收杆。

带有 Tauri 桌面 UI，支持打包为独立安装包分发（无需安装 Python）。

## 快速开始

### 方式 1：使用打包好的安装包（推荐）

直接运行安装包，无需安装任何依赖。

### 方式 2：从源码运行

需要 Python 3.10+。

**Windows：**

```bash
# 双击 start.bat 一键启动（自动创建虚拟环境、安装依赖、启动脚本）
start.bat

# 或手动安装
py -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python src/wow_fishing_bot.py --config config.json
```

**macOS：**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python src/wow_fishing_bot.py --config config.json
```

macOS 需要在「系统设置 → 隐私与安全性」中为终端/IDE 开启辅助功能和屏幕录制权限。

## Tauri 桌面 UI

### 开发模式

```bash
cargo install tauri-cli
cargo tauri dev
```

UI 中将 `Python 路径` 设置为虚拟环境的 Python（如 `.\.venv\Scripts\python.exe`），点击加载/保存编辑配置，点击启动运行。

### 构建发布版

发布版会将 Python 脚本打包为独立可执行文件（sidecar），用户无需安装 Python。

```bash
# 一键构建（PyInstaller 打包 + Tauri 构建）
python build_release.py

# 或分步构建
python build.py        # 打包 Python → src-tauri/binaries/
cargo tauri build      # 构建 Tauri 安装包

# Windows 也可以用批处理
build_exe.bat          # 打包 Python
cargo tauri build      # 构建 Tauri 安装包
```

构建产物在 `src-tauri/target/release/bundle/` 目录下。

## 配置

```bash
cp config.example.json config.json
```

关键配置项：

| 配置项 | 说明 |
|--------|------|
| `vision.template_path` | 鱼漂模板图路径 |
| `vision.search_region` | 搜索区域，限制范围提升速度和准确率 |
| `audio.freq_target_hz` | 咬钩音效目标频率 |
| `audio.ratio_threshold` | 声音触发阈值，需根据环境微调 |
| `audio.wasapi_loopback` | Windows 启用输出设备回环采集 |
| `audio.device` | 音频设备索引，用 `--list-devices` 查看 |

## 命令行参数

```bash
python src/wow_fishing_bot.py --config config.json [选项]
```

| 参数 | 说明 |
|------|------|
| `--list-devices` | 列出可用音频设备 |
| `--once` | 只执行一次流程，便于调试 |
| `--record` | 录制音频样本 |
| `--record-seconds N` | 录制时长（秒），默认 8 |
| `--record-out PATH` | 录音输出路径，默认 `recordings/hook.wav` |
| `--capture-bobber` | 截取鱼漂模板 |
| `--capture-size N` | 截取尺寸（像素），默认 72 |
| `--capture-out PATH` | 截取输出路径，默认 `assets/bobber_template.png` |
| `--capture-region` | 交互式框选搜索区域 |
| `--capture-blacklist` | 截取黑名单图标模板 |

## Windows 注意事项

- 优先启用「立体声混音」作为输入设备，或使用 WASAPI loopback
- 游戏用窗口化或无边框窗口，避免独占全屏导致截图异常
- 如果游戏以管理员权限运行，脚本也需要管理员权限启动
