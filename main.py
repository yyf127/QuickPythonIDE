"""QuickPythonIDE —— 基于 pywebview 的简易 Python IDE（已完成阶段1-4：骨架 / UI / 宿主能力 / 打包）。

架构
----
- 本文件 (main.py) 是「宿主」：负责文件读写、代码执行等底层能力。
- 所有界面都在外置的 ``ui/`` 文件夹（index.html / css / js），由 pywebview 加载。
  因为 UI 在可执行文件之外，改界面/加编辑器功能都**不用重新打包 exe**
  （详见项目计划文档）。

部署包目录约定（exe 同级）
--------------------------
- ``ui/``            外置界面（index.html / css / js）。
- ``root/``          自带的【嵌入式 Python 解释器池】（如
                    ``root/python-3.15.0-embed-amd64/python.exe``），
                    用于版本切换，不依赖系统是否安装 Python。
- ``project/``       用户工程目录（IDE 工程树默认从此处开始）。

阶段3 能力范围（相比阶段2）
--------------------------
- ``run_code`` 改为 **subprocess 子进程** 执行用户代码（阶段1 是 exec 主线程阻塞）。
  * 子进程隔离：用户代码死循环 / 崩溃不会影响 IDE 窗口。
  * 流式输出：stdout/stderr 实时通过 pywebview 推回前端日志面板。
  * 支持 ``stop_code`` 终止正在运行的子进程。
- 新增 RPC：
  * ``python_versions()``：列出本机可用的 Python 解释器（供版本切换）。
  * ``pip_install(packages, python)``：调用对应解释器的 pip 安装依赖。
  * ``backup_file(path)``：把文件复制成 ``.bak`` 备份。

无 webview 的测试/命令行环境下，``run_code`` 退化为**同步**执行并直接返回捕获到的
stdout/stderr，保证单测不需要 GUI。
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import traceback
from datetime import datetime
from pathlib import Path


def _app_root() -> Path:
    """项目根目录（ui/ 的父目录）。

    - 开发模式（直接 ``python main.py``）：指向 main.py 所在目录。
    - 打包成 exe 后（``sys.frozen``）：指向 main.exe 同级目录。
      ui/ 文件夹与 exe 放在一起，因此无论哪种环境都能正确定位外置界面。
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


APP_ROOT = _app_root()
UI_DIR = APP_ROOT / "ui"

# 窗体运行：生成的 app.py 模板（__GEOM__ / __CONTROLS__ / __USER_CODE__ 由宿主替换）。
# 用 tkinter 渲染窗体（标准库、原生 GUI，大多数人习惯），按钮点击经 ui.on(id, fn) 回传到
# 用户代码；ui.get/ui.set 读写控件内容。tkinter 是标准库但需 Tcl/Tk 运行文件，嵌入式
# 解释器（官方 embed zip）默认不含，缺失时由 _ensure_tkinter 尝试自动补齐。
FORM_TK_TEMPLATE = '''import tkinter as tk
import traceback

root = tk.Tk()
root.title("QuickPythonIDE 窗体")
root.geometry("__GEOM__")
_widgets = {}

def _build():
__CONTROLS__

_build()

class _UI:
    def get(self, cid):
        w = _widgets.get(cid)
        if w is None:
            return ""
        cls = w.winfo_class()
        try:
            if cls == "Entry":
                return w.get()
            if cls == "Text":
                return w.get("1.0", "end-1c")
            if cls in ("Label", "Button"):
                return w.cget("text")
        except Exception:
            return ""
        return ""

    def set(self, cid, value):
        w = _widgets.get(cid)
        if w is None:
            return
        cls = w.winfo_class()
        s = str(value)
        try:
            if cls == "Entry":
                w.delete(0, "end"); w.insert(0, s)
            elif cls == "Text":
                w.delete("1.0", "end"); w.insert("1.0", s)
            elif cls in ("Label", "Button"):
                w.config(text=s)
        except Exception:
            pass

    def on(self, cid, fn):
        w = _widgets.get(cid)
        if w is None:
            return
        cls = w.winfo_class()
        if cls == "Button":
            w.config(command=lambda: _safe(fn))
        elif cls == "Entry":
            w.bind("<Return>", lambda e: _safe(fn))
        elif cls == "Text":
            w.bind("<KeyRelease>", lambda e: _safe(fn))

    def title(self, t):
        root.title(str(t))

def _safe(fn):
    try:
        fn()
    except Exception as e:
        print("控件回调出错:", e)
        traceback.print_exc()

ui = _UI()

__USER_CODE__

root.mainloop()
'''


class Api:
    """暴露给前端 JavaScript 的 RPC 接口（通过 pywebview 桥接）。"""

    def __init__(self, root: str | None = None) -> None:
        if root:
            self.root = Path(root)
        elif (APP_ROOT / "project").is_dir():
            # 部署包约定：用户工程放在 exe 同级的 project/ 目录下
            self.root = APP_ROOT / "project"
        else:
            self.root = APP_ROOT
        self._proc: subprocess.Popen | None = None  # 当前运行的用户代码子进程
        self._tmp: str | None = None               # 临时脚本文件路径
        self._tmpdir: str | None = None            # 窗体运行时的临时目录
        self._reader_threads: list[threading.Thread] = []

    # ================================================================== 磁盘
    def list_dir(self, path: str | None = None) -> dict:
        """列出目录内容，供左侧工程树使用。返回 parent 便于「上一级」。"""
        target = Path(path) if path else self.root
        try:
            items = []
            for child in sorted(
                target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())
            ):
                items.append(
                    {"name": child.name, "path": str(child), "is_dir": child.is_dir()}
                )
            parent = str(target.parent) if target != target.parent else None
            return {"ok": True, "path": str(target), "parent": parent, "items": items}
        except Exception as exc:  # noqa: BLE001 - 把错误抛给前端
            return {"ok": False, "error": str(exc)}

    def load_file(self, path: str) -> dict:
        """读取本地文本文件。"""
        try:
            file = Path(path)
            content = file.read_text(encoding="utf-8")
            return {"ok": True, "path": str(file), "content": content}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def save_file(self, path: str, content: str) -> dict:
        """把内容写回本地文件（自动建父目录）。"""
        try:
            file = Path(path)
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(content, encoding="utf-8")
            return {"ok": True, "path": str(file)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def delete_path(self, path: str) -> dict:
        """删除文件或目录（目录递归删除）。供前端工程树右键菜单使用。"""
        try:
            target = Path(path)
            if not target.exists():
                return {"ok": False, "error": f"not found: {path}"}
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            return {"ok": True, "path": str(target)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    def backup_file(self, path: str) -> dict:
        """把文件复制成 ``.bak`` 备份（已存在则追加时间戳）。"""
        try:
            src = Path(path)
            if not src.exists():
                return {"ok": False, "error": f"not found: {path}"}
            if src.is_dir():
                return {"ok": False, "error": "暂不支持备份目录"}
            dst = src.with_suffix(src.suffix + ".bak")
            if dst.exists():
                dst = src.with_name(
                    src.name + "." + datetime.now().strftime("%Y%m%d%H%M%S") + ".bak"
                )
            shutil.copy2(src, dst)
            return {"ok": True, "path": str(dst)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    # ============================================================ 解释器/依赖
    def python_versions(self) -> dict:
        """列出可用 Python 解释器，供前端做版本切换下拉框。

        扫描来源：
        1. 当前解释器（即运行本 IDE 的 python）；
        2. 系统 PATH 中的 python / python3.x；
        3. Windows ``py`` 启动器（``py -0``）；
        4. 部署包约定目录 ``root/`` 下自带的【嵌入式解释器】
           （如 ``root/python-3.15.0-embed-amd64/python.exe``），
           用于纯绿色、不依赖系统 Python 的版本切换。
        """
        import re

        found: list[dict] = []
        seen: set[str] = set()

        def add(exe: str, label: str | None = None, embedded: bool = False) -> None:
            exe = os.path.abspath(exe)
            if exe in seen:
                return
            seen.add(exe)
            ver = ""
            try:
                out = subprocess.run(
                    [exe, "--version"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                ver = (out.stdout or out.stderr).strip()
            except Exception:  # noqa: BLE001, S110
                pass
            found.append(
                {"path": exe, "label": label or ver or exe, "embedded": embedded}
            )

        try:
            # 冻结成 exe 后，sys.executable 是 IDE 自身，无法用来跑用户脚本
            # （会重新打开 IDE），因此不把它列为可运行解释器；运行时默认用 root/ 嵌入式解释器。
            if not getattr(sys, "frozen", False):
                add(sys.executable)
            for d in os.environ.get("PATH", "").split(os.pathsep):
                for cand in (
                    "python.exe",
                    "python3.exe",
                    "python3.10.exe",
                    "python3.11.exe",
                    "python3.12.exe",
                    "python3.13.exe",
                    "python3.15.exe",
                ):
                    p = os.path.join(d, cand)
                    if os.path.exists(p):
                        add(p)
            # Windows py 启动器
            out = subprocess.run(
                ["py", "-0"], check=False, capture_output=True, text=True, timeout=5
            ).stdout
            for line in out.splitlines():
                m = re.search(r"-V:([\d.]+)", line) or re.search(
                    r"Python\s+([\d.]+)", line
                )
                if m:
                    found.append(
                        {
                            "path": "py -" + m.group(1),
                            "label": "Python " + m.group(1) + " (py launcher)",
                            "embedded": False,
                        }
                    )
            # 部署包自带嵌入式解释器（root/）
            root_dir = APP_ROOT / "root"
            if root_dir.is_dir():
                for sub in sorted(root_dir.iterdir()):
                    if sub.is_dir() and (sub / "python.exe").exists():
                        m = re.search(r"(\d+\.\d+\.\d+)", sub.name)
                        ver = m.group(1) if m else sub.name
                        add(
                            str(sub / "python.exe"),
                            label=f"Python {ver} (embed)",
                            embedded=True,
                        )
        except Exception:  # noqa: BLE001, S110 - 扫描失败也不阻塞 IDE
            pass

        return {"ok": True, "versions": found}

    def pip_install(self, packages: str | list, python: str | None = None) -> dict:
        """用指定解释器安装依赖（同步阻塞，带超时）。"""
        if isinstance(packages, str):
            pkgs = shlex.split(packages)
        elif isinstance(packages, list):
            pkgs = packages
        else:
            return {"ok": False, "error": "packages 必须是字符串或列表"}
        if not pkgs:
            return {"ok": False, "error": "未指定要安装的包"}
        try:
            cmd = self._resolve_python(python)
            # 选中嵌入解释器时，先确保 site 启用且 pip 可用
            prep = self._ready_pip(cmd[0])
            if not prep["ok"]:
                return {"ok": False, "output": prep["output"]}
            cmd = cmd + ["-m", "pip", "install"] + pkgs
            proc = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=600,
                cwd=str(self.root),
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            return {"ok": proc.returncode == 0, "output": out}
        except subprocess.TimeoutExpired as exc:
            out = (exc.stdout or "") + (exc.stderr or "") + "\n[pip 安装超时]"
            return {"ok": False, "output": out}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "output": str(exc)}

    # ============================================================== 代码执行
    def run_code(self, code: str, path: str | None = None, python: str | None = None) -> dict:
        """执行 ``code``。

        有 webview 窗口时：启动子进程**异步**运行，stdout/stderr 实时推回前端，
        返回 ``{ok, async, pid}``（实际输出经 ``window.appendOutput``，结束经
        ``window.onRunFinished``）。
        无窗口（测试/CLI）时：同步运行并直接返回 ``{ok, stdout, stderr}``。
        """
        if self._proc is not None and self._proc.poll() is None:
            return {"ok": False, "error": "已有代码在运行中，请先停止"}

        if self._has_window():
            cmd, tmp = self._build_cmd(code, python)
            self._start_subprocess(cmd, tmp)
            return {"ok": True, "async": True, "pid": self._proc.pid}
        return self._run_subprocess(code, python)

    def stop_code(self) -> dict:
        """终止当前正在运行的用户代码子进程。"""
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return {"ok": False, "error": "当前没有正在运行的代码"}
        try:
            proc.kill()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
        return {"ok": True}

    # ============================================================== 窗体运行
    def run_form(self, form_json: str | list, code: str, python: str | None = None) -> dict:
        """把「窗体设计」生成的控件 + 用户写的控制器代码，跑成一个 tkinter 真实窗口。

        生成自包含的 tkinter app.py，用选中的解释器（默认 root/ 里的嵌入式 Python）
        启动子进程弹出原生窗口。按钮点击经 ui.on(control_id, fn) 回传到用户代码里的函数，
        ui.get/ui.set 读写控件内容。tkinter 是标准库但需要 Tcl/Tk 运行文件：嵌入式解释器
        默认不含，run_form 会先检测，缺失则尝试自动补齐（_ensure_tkinter）。
        """
        try:
            controls = json.loads(form_json) if isinstance(form_json, str) else list(form_json)
        except Exception:  # noqa: BLE001
            controls = []
        if not controls:
            return {"ok": False, "error": "没有窗体控件，请先在「窗体设计」里添加按钮/标签/文本框/多行文本"}

        tmpdir = tempfile.mkdtemp(prefix="qform_")
        try:
            app_path = Path(tmpdir) / "app.py"
            app_path.write_text(self._gen_form_app(controls, code), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            shutil.rmtree(tmpdir, ignore_errors=True)
            return {"ok": False, "error": "生成窗体文件失败: " + str(exc)}

        cmd = self._resolve_python(python)
        self._fix_embedded_pth(cmd[0])
        # tkinter 是标准库但需 Tcl/Tk 运行文件；嵌入式解释器默认没有，先检测再尝试修复
        chk = self.check_tkinter(cmd[0])
        if not chk["ok"]:
            fix = self._ensure_tkinter(cmd[0])
            if not fix["ok"]:
                shutil.rmtree(tmpdir, ignore_errors=True)
                msg = "当前解释器缺少 tkinter 所需的 Tcl/Tk 运行文件（tkinter 无法通过 pip 安装）。"
                if fix.get("need_copy"):
                    msg += "\n请为 Python {} 补齐：把同版本完整 Python 的 tcl/ 目录、_tkinter.pyd、" \
                           "tcl*.dll、tk*.dll 拷到 {} 。".format(
                               fix.get("target") or "?", Path(cmd[0]).resolve().parent)
                if fix.get("detail"):
                    msg += "\n细节: " + fix["detail"]
                return {"ok": False, "error": msg}

        run_cmd = cmd + ["-u", str(app_path)]
        if self._has_window():
            self._tmpdir = tmpdir
            self._start_subprocess(run_cmd, str(app_path))
            return {"ok": True, "async": True, "pid": self._proc.pid}
        # 无界面（测试/CI）：仅做语法/导入自检，窗口无法显示
        try:
            proc = subprocess.run(
                run_cmd, check=False, cwd=str(self.root),
                capture_output=True, text=True, encoding="utf-8", timeout=30,
            )
            return {"ok": proc.returncode == 0, "stdout": proc.stdout, "stderr": proc.stderr}
        except subprocess.TimeoutExpired as exc:
            return {"ok": False, "stdout": exc.stdout or "", "stderr": (exc.stderr or "") + "\n[超时]"}
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def _ensure_module(self, python_exe: str, mod: str) -> dict:
        """确保某个解释器里能用 mod；没有就 pip install（优先用已就绪的 pip）。"""
        chk = subprocess.run(
            [python_exe, "-c", "import " + mod],
            check=False, capture_output=True, text=True, timeout=30,
        )
        if chk.returncode == 0:
            return {"ok": True, "output": ""}
        prep = self._ready_pip(python_exe)
        if not prep["ok"]:
            return prep
        res = subprocess.run(
            [python_exe, "-m", "pip", "install", mod],
            check=False, capture_output=True, text=True, timeout=600, cwd=str(self.root),
        )
        if res.returncode == 0:
            return {"ok": True, "output": (res.stdout or "")[-500:]}
        return {"ok": False, "output": ((res.stderr or res.stdout or "")[:500])}

    # ----------------------------------------------------- tkinter 检测/修复
    def check_tkinter(self, python: str | None = None) -> dict:
        """检查指定解释器能否 import tkinter（需要 Tcl/Tk 运行文件）。

        tkinter 是标准库，但官方 embeddable 包砍掉了 Tcl/Tk，所以 ``pip install tkinter``
        无效；这里直接尝试真实导入。withdraw 避免检测时弹出窗口。
        """
        exe = self._resolve_python(python)[0]
        try:
            chk = subprocess.run(
                [exe, "-c", "import tkinter; r=tkinter.Tk(); r.withdraw(); r.destroy()"],
                check=False, capture_output=True, text=True, timeout=30,
            )
        except Exception as exc:  # noqa: BLE001 - 解释器不存在/无法启动都应视为不可用
            return {"ok": False, "error": str(exc), "python": exe}
        return {
            "ok": chk.returncode == 0,
            "error": (chk.stderr or "")[:400] if chk.returncode else "",
            "python": exe,
        }

    def ensure_tkinter(self, python: str | None = None) -> dict:
        """尝试让指定解释器可用 tkinter：已可用则直接返回；否则尝试从同版本完整 Python
        复制 Tcl/Tk 运行文件到嵌入解释器目录。无法自动修复时返回 need_copy=True 及指引。
        """
        exe = self._resolve_python(python)[0]
        return self._ensure_tkinter(exe)

    def _ensure_tkinter(self, exe: str) -> dict:
        try:
            chk = subprocess.run(
                [exe, "-c", "import tkinter; r=tkinter.Tk(); r.withdraw(); r.destroy()"],
                check=False, capture_output=True, text=True, timeout=30,
            )
        except Exception as exc:  # noqa: BLE001
            chk = None
            chk_err = str(exc)
        else:
            chk_err = (chk.stderr or "")[:400] if chk.returncode else ""
        if chk is not None and chk.returncode == 0:
            return {"ok": True, "action": "tkinter 已可用"}
        target = self._py_version(exe)
        src = self._find_tk_source(target, exe)
        if not src:
            return {
                "ok": False,
                "action": "需要手动补齐 Tcl/Tk 文件（tkinter 是标准库但需 Tcl/Tk 运行文件，pip 装不了）",
                "need_copy": True,
                "target": target,
                "dest": str(Path(exe).resolve().parent),
            }
        self._copy_tk(src, exe)
        try:
            chk2 = subprocess.run(
                [exe, "-c", "import tkinter; r=tkinter.Tk(); r.withdraw(); r.destroy()"],
                check=False, capture_output=True, text=True, timeout=30,
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "action": "复制后仍然无法使用 tkinter",
                "need_copy": True,
                "detail": str(exc)[:400],
                "target": target,
                "dest": str(Path(exe).resolve().parent),
            }
        if chk2.returncode == 0:
            return {"ok": True, "action": "已从 {} 复制 Tcl/Tk，tkinter 现已可用".format(src)}
        return {
            "ok": False,
            "action": "复制后仍然无法使用 tkinter",
            "need_copy": True,
            "detail": (chk2.stderr or "")[:400],
            "target": target,
            "dest": str(Path(exe).resolve().parent),
        }

    @staticmethod
    def _py_version(exe: str) -> str | None:
        try:
            out = subprocess.run(
                [exe, "-c", "import sys;print('.'.join(map(str,sys.version_info[:2])))"],
                check=False, capture_output=True, text=True, timeout=20,
            )
        except Exception:  # noqa: BLE001
            return None
        return (out.stdout or "").strip() or None

    def _find_tk_source(self, target_ver: str | None, embed_exe: str) -> str | None:
        """在同版本、且自身可用 tkinter 的完整 Python 里找一个，作为 Tcl/Tk 文件来源。

        扫描：受管运行时目录、常见完整安装目录、PATH。仅当版本号（major.minor）完全匹配才采用，
        避免 Tcl/Tk ABI 不一致。不创建窗口（仅 import 检测）。
        """
        if not target_ver:
            return None
        candidates: list[str] = []
        mgr = Path(os.path.expanduser("~")) / ".workbuddy" / "binaries" / "python" / "versions"
        if mgr.is_dir():
            for sub in mgr.iterdir():
                c = sub / "python.exe"
                if c.exists():
                    candidates.append(str(c))
        for base in (
            "C:/Program Files",
            "C:/Program Files (x86)",
            os.path.expanduser("~/AppData/Local/Programs/Python"),
            "C:/Python",
        ):
            d = Path(base)
            if not d.is_dir():
                continue
            for sub in d.iterdir():
                c = sub / "python.exe"
                if c.exists():
                    candidates.append(str(c))
        for d in os.environ.get("PATH", "").split(os.pathsep):
            for cand in ("python.exe", "python3.exe"):
                p = Path(d) / cand
                if p.exists():
                    candidates.append(str(p))
        embed = Path(embed_exe).resolve()
        for cand in candidates:
            if Path(cand).resolve() == embed:
                continue
            if self._py_version(cand) != target_ver:
                continue
            try:
                chk = subprocess.run(
                    [cand, "-c", "import tkinter"],
                    check=False, capture_output=True, text=True, timeout=30,
                )
            except Exception:  # noqa: BLE001
                continue
            if chk.returncode == 0:
                return cand
        return None

    def _copy_tk(self, src_exe: str, embed_exe: str) -> None:
        """从完整 Python（src_exe）复制 Tcl/Tk 运行文件到嵌入解释器（embed_exe）目录。

        复制：tcl/ 目录、tcl*.dll/tk*.dll/zlib1.dll、DLLs/_tkinter.pyd、Lib/tkinter 包；
        并在 ._pth 中追加 .\\DLLs 与 Lib\\site-packages 搜索路径（启用 import site 后生效）。
        """
        src = Path(src_exe).resolve().parent
        dst = Path(embed_exe).resolve().parent
        try:
            import shutil as _sh

            tcl = src / "tcl"
            if tcl.is_dir():
                d = dst / "tcl"
                if not d.exists():
                    _sh.copytree(tcl, d)
            for pat in ("tcl*.dll", "tk*.dll", "zlib1.dll"):
                for f in src.glob(pat):
                    try:
                        _sh.copy2(f, dst / f.name)
                    except OSError:  # noqa: BLE001
                        pass
            tkd = src / "DLLs" / "_tkinter.pyd"
            if tkd.exists():
                _sh.copy2(tkd, dst / "_tkinter.pyd")
            tkpkg = src / "Lib" / "tkinter"
            if tkpkg.is_dir():
                sp = dst / "Lib" / "site-packages" / "tkinter"
                if not sp.exists():
                    _sh.copytree(tkpkg, sp)
            # 确保 embed ._pth 启用 import site 并加入 .\DLLs / Lib\site-packages 路径
            self._fix_embedded_pth(str(embed_exe))
            for name in os.listdir(dst):
                if name.endswith("._pth"):
                    p = dst / name
                    txt = p.read_text(encoding="utf-8")
                    added = False
                    if "DLLs" not in txt:
                        txt += "\n.\\DLLs"
                        added = True
                    if "site-packages" not in txt:
                        txt += "\nLib\\site-packages"
                        added = True
                    if added:
                        p.write_text(txt, encoding="utf-8")
                    break
        except Exception:  # noqa: BLE001 - 复制到一半失败也不致命，交由后续检测判断
            pass

    @staticmethod
    def _esc(s: str) -> str:
        return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace('"', "&quot;"))

    def _gen_form_app(self, controls: list, code: str) -> str:
        """生成 tkinter 窗体 app.py 源码（自包含，含 ui 桥接，无需 webview）。"""
        lines = []
        for c in controls:
            cid = c.get("id", "")
            ctype = c.get("type", "")
            try:
                x = int(c.get("x", 20)); y = int(c.get("y", 20))
            except Exception:  # noqa: BLE001
                x, y = 20, 20
            text = c.get("text", "")
            if ctype == "Button":
                t = text or "按钮"
                lines.append('    w = tk.Button(root, text={!r}); w.place(x={}, y={}); _widgets[{!r}] = w'.format(t, x, y, cid))
            elif ctype == "Label":
                lines.append('    w = tk.Label(root, text={!r}); w.place(x={}, y={}); _widgets[{!r}] = w'.format(text, x, y, cid))
            elif ctype == "TextBox":
                lines.append('    w = tk.Entry(root, width=24); w.place(x={}, y={}); _widgets[{!r}] = w'.format(x, y, cid))
            elif ctype == "TextArea":
                lines.append('    w = tk.Text(root, width=30, height=8); w.place(x={}, y={}); _widgets[{!r}] = w'.format(x, y, cid))
        controls_code = "\n".join(lines)
        geom = self._form_geometry(controls)
        return (FORM_TK_TEMPLATE
                .replace("__GEOM__", geom)
                .replace("__CONTROLS__", controls_code)
                .replace("__USER_CODE__", code or ""))

    @staticmethod
    def _form_geometry(controls: list) -> str:
        mx, my = 320, 240
        for c in controls:
            try:
                mx = max(mx, int(c.get("x", 0)) + 260)
                my = max(my, int(c.get("y", 0)) + 80)
            except Exception:  # noqa: BLE001
                pass
        return "{}x{}".format(mx, my)

    # ---------------------------------------------------------- 内部工具
    def _resolve_python(self, python: str | None) -> list[str]:
        if not python:
            # 冻结成 exe 后，sys.executable 是 IDE 自身，不能拿来跑用户脚本，
            # 默认回落到 root/ 下的嵌入式解释器（免安装、不依赖系统 Python）。
            if getattr(sys, "frozen", False):
                emb = self._default_embedded()
                if emb:
                    return [emb]
            return [sys.executable]
        # 整段就是一个存在的可执行文件（可能含空格，如嵌入解释器路径）→ 直接用
        if os.path.isfile(python):
            return [python]
        # 否则按 shell 方式拆分，支持 "py -3.11" 这类带参数的写法
        return shlex.split(python)

    def _default_embedded(self) -> str | None:
        """root/ 下第一个嵌入式解释器路径（部署包约定的自带 Python 池）。"""
        root_dir = APP_ROOT / "root"
        if root_dir.is_dir():
            for sub in sorted(root_dir.iterdir()):
                if sub.is_dir() and (sub / "python.exe").exists():
                    return str(sub / "python.exe")
        return None

    # ----------------------------------------------------- 嵌入解释器准备
    def _fix_embedded_pth(self, python_exe: str) -> None:
        """为 ``root/`` 下的嵌入解释器取消注释 ``import site``（仅对其生效）。

        嵌入版默认 ``<ver>._pth`` 里 ``import site`` 被注释，导致 pip 安装的
        第三方包无法被 import；启用后即可正常使用。系统 Python 无此文件，跳过。
        """
        try:
            pdir = Path(python_exe).resolve().parent
            root_dir = (APP_ROOT / "root").resolve()
            # 只处理 root/ 下的嵌入解释器，绝不改动系统 Python
            if root_dir not in pdir.resolve().parents:
                return
        except Exception:  # noqa: BLE001
            return
        try:
            for name in os.listdir(pdir):
                if name.endswith("._pth"):
                    p = pdir / name
                    txt = p.read_text(encoding="utf-8")
                    if "#import site" in txt:
                        p.write_text(
                            txt.replace("#import site", "import site"),
                            encoding="utf-8",
                        )
                    break
        except Exception:  # noqa: BLE001, S110
            pass

    def _ready_pip(self, python_exe: str) -> dict:
        """确保嵌入解释器可运行 pip：启用 site + 必要时用 ensurepip 安装。

        系统 Python 若已自带 pip 则直接返回就绪；none 时才触发 ensurepip
        （内置 wheel，无需联网）。
        """
        python_exe = os.path.abspath(python_exe)
        self._fix_embedded_pth(python_exe)
        chk = subprocess.run(
            [python_exe, "-m", "pip", "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if chk.returncode == 0:
            return {"ok": True, "output": "pip 已就绪"}
        res = subprocess.run(
            [python_exe, "-m", "ensurepip", "--upgrade"],
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if res.returncode == 0:
            return {"ok": True, "output": "已通过 ensurepip 安装 pip"}
        return {
            "ok": False,
            "output": "无法为嵌入解释器准备 pip："
            + ((res.stderr or res.stdout or "")[:300]),
        }

    def _build_cmd(self, code: str, python: str | None) -> tuple[list[str], str]:
        fd, tmp = tempfile.mkstemp(suffix=".py", prefix="qpython_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(code)
        cmd = self._resolve_python(python) + ["-u", tmp]  # -u 关闭缓冲，实时输出
        self._fix_embedded_pth(cmd[0])  # 嵌入解释器需启用 import site（仅影响 root/ 下）
        return cmd, tmp

    def _has_window(self) -> bool:
        try:
            import webview

            return bool(webview.windows)
        except Exception:  # noqa: BLE001 - 没有 webview 即视为无界面
            return False

    def _push_js(self, js: str) -> None:
        try:
            import webview

            if webview.windows:
                webview.windows[0].evaluate_js(js)
        except Exception:  # noqa: BLE001, S110 - 推送失败不影响执行
            pass

    def _push(self, text: str, kind: str) -> None:
        if not text:
            return
        js = f"window.appendOutput({json.dumps(text)}, {json.dumps(kind)});"
        self._push_js(js)

    def _start_subprocess(self, cmd: list[str], tmp: str) -> None:
        self._proc = subprocess.Popen(
            cmd,
            cwd=str(self.root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            encoding="utf-8",
        )
        self._tmp = tmp
        self._push(f"\n=== 运行 (pid {self._proc.pid}) ===\n", "ok")

        t_out = threading.Thread(
            target=self._reader, args=(self._proc.stdout, "out"), daemon=True
        )
        t_err = threading.Thread(
            target=self._reader, args=(self._proc.stderr, "err"), daemon=True
        )
        t_out.start()
        t_err.start()
        self._reader_threads = [t_out, t_err]
        threading.Thread(
            target=self._waiter, args=(self._proc,), daemon=True
        ).start()

    def _reader(self, stream, kind: str) -> None:
        try:
            for line in iter(stream.readline, ""):
                if not line:
                    break
                self._push(line, kind)
        except Exception:  # noqa: BLE001, S110 - 管道已关闭等
            pass

    def _waiter(self, proc: subprocess.Popen) -> None:
        for t in self._reader_threads:
            t.join()
        rc = proc.wait()
        ok = rc == 0
        msg = (
            "--- 运行结束（正常，返回码 %d）---\n"
            if ok
            else "--- 运行结束（异常，返回码 %d）---\n"
        ) % rc
        self._push(msg, "ok" if ok else "err")
        self._push_js(
            "window.onRunFinished({}, {});".format("true" if ok else "false", rc)
        )
        if self._tmp:
            try:
                os.remove(self._tmp)
            except OSError:
                pass
            self._tmp = None
        if self._tmpdir:
            try:
                shutil.rmtree(self._tmpdir, ignore_errors=True)
            except Exception:  # noqa: BLE001
                pass
            self._tmpdir = None
        self._proc = None

    def _run_subprocess(self, code: str, python: str | None) -> dict:
        """无界面时的同步执行（用于单测 / CLI）。"""
        cmd, tmp = self._build_cmd(code, python)
        try:
            proc = subprocess.run(
                cmd,
                check=False,
                cwd=str(self.root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=30,
            )
            return {
                "ok": proc.returncode == 0,
                "stdout": proc.stdout,
                "stderr": proc.stderr,
            }
        except subprocess.TimeoutExpired as exc:
            return {
                "ok": False,
                "stdout": exc.stdout or "",
                "stderr": (exc.stderr or "") + "\n[执行超时]",
            }
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass

    # ----------------------------------------------------------------- 兼容
    def run_code_exec(self, code: str, path: str | None = None) -> dict:
        """阶段1 遗留的同步 exec 原型（保留以备对比/兼容性测试）。"""
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                exec(compile(code, path or "<editor>", "exec"), {"__name__": "__main__"})  # noqa: S102
            return {"ok": True, "stdout": out.getvalue(), "stderr": err.getvalue()}
        except SystemExit:
            return {"ok": True, "stdout": out.getvalue(), "stderr": err.getvalue()}
        except Exception:  # noqa: BLE001
            return {
                "ok": False,
                "stdout": out.getvalue(),
                "stderr": err.getvalue() + traceback.format_exc(),
            }


def main() -> None:
    import webview

    api = Api()
    webview.create_window(
        "QuickPythonIDE",
        str(UI_DIR / "index.html"),
        js_api=api,
        width=1100,
        height=720,
    )
    webview.start()


if __name__ == "__main__":
    main()
