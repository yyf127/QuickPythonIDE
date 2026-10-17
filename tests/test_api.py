"""宿主 Api 的单元测试（无需 GUI / 不依赖 webview）。"""

import sys
from pathlib import Path

from main import Api


def test_list_dir(tmp_path):
    (tmp_path / "a.py").write_text("print(1)")
    (tmp_path / "sub").mkdir()
    res = Api(str(tmp_path)).list_dir()
    assert res["ok"] is True
    names = {i["name"] for i in res["items"]}
    assert {"a.py", "sub"} <= names
    dirs = [i for i in res["items"] if i["is_dir"]]
    assert dirs and dirs[0]["name"] == "sub"
    # 返回 parent 便于前端「上一级」
    assert res["parent"] == str(tmp_path.parent)


def test_load_and_save_file(tmp_path):
    api = Api(str(tmp_path))
    p = str(tmp_path / "x.py")
    assert api.save_file(p, "print('hi')")["ok"] is True
    loaded = api.load_file(p)
    assert loaded["ok"] is True
    assert loaded["content"] == "print('hi')"


def test_load_missing_file(tmp_path):
    res = Api(str(tmp_path)).load_file(str(tmp_path / "nope.py"))
    assert res["ok"] is False
    assert res["error"]


def test_delete_path(tmp_path):
    api = Api(str(tmp_path))
    f = tmp_path / "del.py"
    f.write_text("x = 1")
    d = tmp_path / "sub"
    d.mkdir()
    (d / "a.txt").write_text("hi")
    assert api.delete_path(str(f))["ok"] is True
    assert api.delete_path(str(d))["ok"] is True
    assert not f.exists() and not d.exists()
    assert api.delete_path(str(tmp_path / "ghost.py"))["ok"] is False


def test_run_code_captures_output():
    api = Api()
    res = api.run_code("print('hello')")
    assert res["ok"] is True
    assert "hello" in res["stdout"]


def test_run_code_captures_error():
    api = Api()
    res = api.run_code("raise ValueError('boom')")
    assert res["ok"] is False
    assert "boom" in res["stderr"]


def test_run_code_subprocess_isolation():
    # 验证 run_code 走子进程（无窗口时同步返回），且变量不污染宿主
    api = Api()
    res = api.run_code("x = 123\ndef f():\n    return x\nprint(f())")
    assert res["ok"] is True
    assert "123" in res["stdout"]


def test_run_code_infinite_loop_can_be_killed():
    # 无窗口环境无法异步停止，这里只验证 stop_code 在空闲时返回明确错误
    api = Api()
    res = api.stop_code()
    assert res["ok"] is False
    assert res["error"]


def test_python_versions_includes_current():
    res = Api().python_versions()
    assert res["ok"] is True
    assert any(v["path"] == sys.executable for v in res["versions"])


def test_pip_install_requires_package():
    res = Api().pip_install("")
    assert res["ok"] is False
    assert res["error"]


def test_backup_file(tmp_path):
    api = Api(str(tmp_path))
    p = tmp_path / "x.py"
    p.write_text("data")
    res = api.backup_file(str(p))
    assert res["ok"] is True
    assert Path(res["path"]).exists()
    assert Path(res["path"]).read_text(encoding="utf-8") == "data"


def test_resolve_python_path_with_spaces():
    # 含空格的解释器路径（如嵌入解释器目录）应原样返回，不被 shlex 拆开
    import tempfile

    p = tempfile.mkdtemp() + "/my python.exe"
    open(p, "w").close()
    assert Api()._resolve_python(p) == [p]


def test_resolve_python_py_launcher():
    # "py -3.11" 这类带参数的写法仍应被拆分
    assert Api()._resolve_python("py -3.11") == ["py", "-3.11"]


def test_default_root_falls_back_without_project():
    # 仓库里没有 project/ 时应回退到 APP_ROOT（部署包有 project/ 时才用它）
    import main

    assert Api().root == main.APP_ROOT


def test_python_versions_has_embedded_field():
    res = Api().python_versions()
    assert res["ok"] is True
    assert all({"path", "label", "embedded"} <= set(v.keys()) for v in res["versions"])


def test_gen_form_html_and_app():
    # 窗体生成的 form.html / app.py 必须合法且含桥接逻辑（无需 GUI）
    api = Api()
    controls = [
        {"id": "c1", "type": "Button", "x": 20, "y": 20, "text": "go"},
        {"id": "c2", "type": "TextBox", "x": 20, "y": 60, "text": ""},
        {"id": "c3", "type": "Label", "x": 20, "y": 100, "text": "<b>x</b>"},
    ]
    html = api._gen_form_html(controls)
    assert '<button id="c1" data-onclick' in html
    assert '<input id="c2"' in html
    assert '<div id="c3"' in html
    assert "&lt;b&gt;" in html  # 文本做了 HTML 转义
    app = api._gen_form_app(controls, 'ui.on("c1", lambda: None)\n')
    compile(app, "<formapp>", "exec")  # 生成的 app.py 语法合法
    assert "def handle(self, control_id)" in app  # pywebview 回传桥
    assert 'ui.on("c1"' in app


def test_run_form_requires_controls():
    # 没有任何控件时给出明确错误，不生成临时文件
    import tempfile

    res = Api(str(tempfile.mkdtemp())).run_form([], "print(1)")
    assert res["ok"] is False
    assert "控件" in res["error"]
