# QuickPythonIDE

一个基于 **pywebview** 的简易 Python IDE：**窗口外壳用 pywebview，界面用外置 HTML/JS，宿主 Python 负责文件读写与代码执行**。

> 关键设计：界面全部在 `ui/` 文件夹，**不打包进 exe**。改 UI / 加编辑器功能只动 `ui/`，不用重打包；只有宿主底层能力变更才改 `main.py` 并重新打包。

## 架构

```
[ui 前端 HTML/JS 界面]
        ↓↑  JS 调用 RPC
[pywebview 桥]
        ↓↑
[宿主 main.py 的 Api]
    ├─ list_dir / load_file / save_file / delete_path  → 读写本地磁盘
    ├─ run_code / stop_code                            → subprocess 隔离执行代码，可停止
    └─ python_versions / pip_install / backup_file    → 版本切换、装包、备份
```

## 目录结构

```
QuickPythonIDE/
├─ main.py                # pywebview 宿主（最终打包成 exe）
├─ requirements.txt       # pywebview 依赖
├─ run.bat               # 一键启动（开发）
├─ build.bat             # 一键打包成 exe
└─ ui/                    # 外置 UI，不随 exe 打包
   ├─ index.html
   ├─ css/style.css
   └─ js/main.js
```

## 本地运行（开发模式）

```bash
pip install -r requirements.txt
python main.py          # 或直接双击 run.bat
```

弹出的窗口里：左侧选 `.py` 文件 → 编辑 → 点「运行」→ 底部日志看到 `print` 输出与报错。`Ctrl+S` 保存，`Ctrl+R` 运行。

## 打包与分发（阶段4）

界面外置，所以 exe 只需要 `main.py` 打包出来，和 `ui/` 文件夹一起发给用户即可。

**方式一：本地打包**

```bash
pip install -r requirements.txt pyinstaller
build.bat
# 等价命令：
# pyinstaller --onefile --windowed --name QuickPythonIDE --collect-all webview main.py
```

**方式二：GitHub 自动打包**

每次推送到 `main`，GitHub Actions 会在 Windows runner 上自动用 PyInstaller 编译，完成后在 Actions 页面的 **QuickPythonIDE-exe** artifact 里下载 `QuickPythonIDE.exe`。

**发布包结构：**

```
发布包/                          # 以下均与 QuickPythonIDE.exe 同级
├─ QuickPythonIDE.exe           # 由 build.bat / CI 生成
├─ ui/                          # 原样复制（外置界面，不打包进 exe）
├─ root/                        # 自带的【嵌入式 Python 解释器池】（可选）
│  ├─ python-3.15.0-embed-amd64/  ← python.exe（用于版本切换，免装系统 Python）
│  └─ python-3.11.0-embed-amd64/
└─ project/                     # 用户工程目录（IDE 工程树默认从这里开始）
   ├─ calculator/main.py
   ├─ muonline_bmd_tool/main.py
   ├─ Image Viewer/main.py
   └─ csv tool/main.py
```

**关于 `root/`（嵌入式解释器）：**
- 把从 python.org 下载的 *Windows embeddable package* 解压到 `root/` 下即可在版本下拉框里选用，纯绿色、不依赖本机是否安装 Python。
- 首次用某嵌入解释器执行 `pip install` 时，IDE 会自动：① 取消该解释器 `_pth` 文件里被注释的 `import site`（否则第三方包无法 import）；② 通过 `ensurepip` 安装 pip（内置 wheel，无需联网）。这两项只改写 `root/` 下的解释器，绝不改动系统 Python。

**迭代更新规则：**
- 修改界面、前端编辑器功能：**只替换 `ui/` 文件夹**，exe 不用重新打包。
- 增加/更换可切换的 Python 版本：**往 `root/` 里加/换嵌入解释器目录**即可，exe 不用重打包。
- 需要新增底层能力（例如新的 RPC、停止逻辑变更）：修改 `main.py` → 重新打包 exe。

> 路径兼容：`main.py` 在开发环境下用脚本所在目录定位 `ui/`，打包成 exe 后用 exe 同级目录定位；若同级存在 `project/` 则工程树默认以它为根，否则回退到 exe 根目录。

## 测试 / 编译（GitHub Actions）

推送即触发 CI：
- `build` job：在 Python 3.10 / 3.11 / 3.12 上做 `ruff` 检查 + `pytest` 单元测试（覆盖 `Api` 的磁盘读写与代码执行）。
- `build-exe` job：在 Windows 上用 PyInstaller 打包出 `QuickPythonIDE.exe` 并上传 artifact。

```bash
pip install -e ".[dev]"
ruff check main.py tests
pytest -q
```

## 开发路线（已完成 4 个阶段）

- **阶段1**：基础骨架 —— `main.py` 暴露 RPC 接口（`list_dir`/`load_file`/`save_file`/`run_code`）+ 三栏界面。
- **阶段2**：多文件标签、视图切换（窗体设计/代码）、工程树增强、快捷键等，全部在 `ui/` 里做，不改 `main.py`。
- **阶段3**：扩展宿主能力（改为 `subprocess` 隔离执行 + 停止运行、Python 版本切换、pip 安装、备份），需改 `main.py`。
- **阶段4**：`pyinstaller --onefile --windowed` 打包成 exe（外置 `ui/`），本地 `build.bat` 与 GitHub `build-exe` job 双通道可构建；迭代 UI 只替换 `ui/` 文件夹。

## 可继续增强（阶段5 候选）

- 断点调试 / 单步执行
- 代码智能补全（LSP）
- 虚拟环境管理（创建/激活 venv）
- 内嵌终端（shell）
