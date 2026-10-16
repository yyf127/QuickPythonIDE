"""QuickPythonIDE —— 基于 pywebview 的简易 Python IDE（阶段1：基础骨架）。

架构
----
- 本文件 (main.py) 是「宿主」：负责文件读写、代码执行等底层能力。
- 所有界面都在外置的 ``ui/`` 文件夹（index.html / css / js），由 pywebview 加载。
  因为 UI 在可执行文件之外，改界面/加编辑器功能都**不用重新打包 exe**
  （详见项目计划文档）。

阶段1 能力范围
--------------
- RPC 接口：list_dir / load_file / save_file / run_code（exec 原型）。
- run_code 目前用 ``exec`` 在主线程执行（会阻塞到结束）。
  阶段3 会改为 subprocess 子进程，以支持隔离与「停止运行」。
"""

from __future__ import annotations

import contextlib
import io
import traceback
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


class Api:
    """暴露给前端 JavaScript 的 RPC 接口（通过 pywebview 桥接）。"""

    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root) if root else BASE_DIR

    # ------------------------------------------------------------------ 磁盘
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

    # -------------------------------------------------------------- 代码执行
    def run_code(self, code: str, path: str | None = None) -> dict:
        """执行 ``code`` 并捕获 stdout / stderr。

        注意：阶段1 使用 exec 在宿主线程上执行（会阻塞直到结束）。
        阶段3 将切换到 subprocess 子进程，支持隔离与终止。
        """
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
        str(BASE_DIR / "ui" / "index.html"),
        js_api=api,
        width=1100,
        height=720,
    )
    webview.start()


if __name__ == "__main__":
    main()
