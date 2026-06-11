import json
from nimo.memory.profile import UserProfile, PROFILE_PREFIX


def test_update_and_facts():
    p = UserProfile()
    p.update({"姓名": "张三"})
    assert p.facts == {"姓名": "张三"}
    assert not p.is_empty


def test_update_overwrites_existing():
    p = UserProfile()
    p.update({"姓名": "张三", "角色": "测试"})
    p.update({"姓名": "李四"})
    assert p.facts["姓名"] == "李四"
    assert p.facts["角色"] == "测试"


def test_update_removes_empty_value():
    p = UserProfile()
    p.update({"姓名": "张三"})
    p.update({"姓名": ""})
    assert "姓名" not in p.facts


def test_to_context():
    p = UserProfile()
    p.update({"姓名": "张三", "角色": "后端工程师"})
    ctx = p.to_context()
    assert ctx is not None
    assert PROFILE_PREFIX in ctx
    assert "姓名：张三" in ctx
    assert "角色：后端工程师" in ctx


def test_to_context_empty():
    p = UserProfile()
    assert p.to_context() is None


def test_is_empty():
    p = UserProfile()
    assert p.is_empty
    p.update({"姓名": "张三"})
    assert not p.is_empty


def test_save_and_load_roundtrip(tmp_path):
    p = UserProfile()
    p.update({"姓名": "张三", "偏好": "简洁回复"})
    p.save(base_dir=tmp_path)

    loaded = UserProfile.load(base_dir=tmp_path)
    assert loaded.facts == {"姓名": "张三", "偏好": "简洁回复"}


def test_load_nonexistent_returns_empty(tmp_path):
    loaded = UserProfile.load(base_dir=tmp_path)
    assert loaded.is_empty


def test_load_corrupted_file_returns_empty(tmp_path):
    path = tmp_path / "profile.json"
    path.write_text("not json", encoding="utf-8")
    loaded = UserProfile.load(base_dir=tmp_path)
    assert loaded.is_empty


def test_clear_resets_state(tmp_path):
    p = UserProfile()
    p.update({"姓名": "张三"})
    p.save(base_dir=tmp_path)
    assert (tmp_path / "profile.json").exists()

    p.clear(base_dir=tmp_path)
    assert p.is_empty
    assert not (tmp_path / "profile.json").exists()
