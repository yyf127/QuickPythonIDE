from kvstore.core import KVStore


def test_set_and_get(tmp_path):
    db = tmp_path / "db.json"
    s = KVStore(db)
    s.set("name", "alice")
    assert s.get("name") == "alice"


def test_get_missing_raises(tmp_path):
    s = KVStore(tmp_path / "db.json")
    try:
        s.get("nope")
        assert False, "expected KeyError"
    except KeyError:
        pass


def test_delete(tmp_path):
    s = KVStore(tmp_path / "db.json")
    s.set("a", 1)
    assert s.delete("a") is True
    assert s.delete("a") is False


def test_persists_across_instances(tmp_path):
    db = tmp_path / "db.json"
    KVStore(db).set("k", [1, 2, 3])
    assert KVStore(db).get("k") == [1, 2, 3]


def test_list(tmp_path):
    s = KVStore(tmp_path / "db.json")
    s.set("x", 1)
    s.set("y", 2)
    assert s.list() == {"x": 1, "y": 2}
