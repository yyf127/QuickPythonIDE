import json

from kvstore.cli import main


def test_set_get_list_delete(tmp_path, capsys):
    db = str(tmp_path / "db.json")
    assert main(["--db", db, "set", "name", "bob"]) == 0
    capsys.readouterr()  # clear "set name" output
    assert main(["--db", db, "get", "name"]) == 0
    assert json.loads(capsys.readouterr().out) == "bob"

    assert main(["--db", db, "list"]) == 0
    assert json.loads(capsys.readouterr().out) == {"name": "bob"}

    assert main(["--db", db, "delete", "name"]) == 0
    capsys.readouterr()  # clear "deleted" output
    assert main(["--db", db, "get", "name"]) == 1


def test_get_missing_returns_error(tmp_path, capsys):
    db = str(tmp_path / "db.json")
    rc = main(["--db", db, "get", "missing"])
    assert rc == 1
    assert "not found" in capsys.readouterr().err


def test_value_coercion(tmp_path, capsys):
    db = str(tmp_path / "db.json")
    main(["--db", db, "set", "nums", "[1,2,3]"])
    capsys.readouterr()  # clear set output
    main(["--db", db, "get", "nums"])
    assert json.loads(capsys.readouterr().out) == [1, 2, 3]
