"""宿主 Api 的单元测试（无需 GUI / 不依赖 webview）。"""

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
