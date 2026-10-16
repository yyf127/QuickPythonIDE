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
    ├─ list_dir / load_file / save_file  → 读写本地磁盘
    └─ run_code                          → 执行编辑器里的 Python 代码，捕获 stdout/stderr
```

## 目录结构

```
QuickPythonIDE/
├─ main.py                # pywebview 宿主（最终打包成 exe）
├─ requirements.txt       # pywebview 依赖
├─ run.bat               # 一键启动（开发）
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

弹出的窗口里：左侧选 `.py` 文件 → 编辑 → 点「运行」→ 底部日志看到 `print` 输出与报错。
`Ctrl+S` 保存。

## 测试 / 编译（GitHub Actions）

推送即触发 CI：在 Python 3.10 / 3.11 / 3.12 上做 `ruff` 检查 + `pytest` 单元测试（覆盖 `Api` 的磁盘读写与代码执行）。

```bash
pip install -e ".[dev]"
ruff check main.py tests
pytest -q
```

## 开发路线（4 个阶段）

- **阶段1（当前）**：基础骨架 —— `main.py` 暴露 4 个 RPC 接口 + 三栏界面，`run_code` 用 `exec` 原型。
- **阶段2**：多文件标签、视图切换（窗体设计/代码）、工程树增强、快捷键等，全部在 `ui/` 里做，不改 `main.py`。
- **阶段3**：扩展宿主能力（改为 `subprocess` 隔离执行 + 停止运行、Python 版本切换、pip 安装等），需要改 `main.py` 并重新打包。
- **阶段4**：`pyinstaller --onefile --windowed main.py` 打包成 `main.exe`，与 `ui/` 一起分发；迭代 UI 只替换 `ui/` 文件夹。

> 阶段1 的 `run_code` 直接 `exec` 会阻塞宿主线程，死循环会卡住窗口；阶段3 将切换到子进程隔离。
