from nimo.memory.history import ConversationHistory


def test_add_and_get_messages():
    history = ConversationHistory()
    history.add({"role": "user", "content": "查项目"})
    history.add({"role": "assistant", "content": "查到3个项目"})

    msgs = history.get_messages()
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"


def test_trim_by_rounds():
    history = ConversationHistory(max_rounds=2)
    # round 1
    history.add({"role": "user", "content": "r1-user"})
    history.add({"role": "assistant", "content": "r1-assistant"})
    # round 2
    history.add({"role": "user", "content": "r2-user"})
    history.add({"role": "assistant", "content": "r2-assistant"})
    # round 3
    history.add({"role": "user", "content": "r3-user"})
    history.add({"role": "assistant", "content": "r3-assistant"})

    msgs = history.get_messages()
    assert len(msgs) == 4
    roles = [m["role"] for m in msgs]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert msgs[0]["content"] == "r2-user"  # round 1 dropped


def test_user_message_triggers_trim():
    history = ConversationHistory(max_rounds=2)
    for i in range(5):
        history.add({"role": "user", "content": f"u{i}"})
        history.add({"role": "assistant", "content": f"a{i}"})
    msgs = history.get_messages()
    assert len(msgs) == 4
    assert msgs[0]["content"] == "u3"


# --- buffer 测试 ---

def test_trim_stores_to_buffer():
    history = ConversationHistory(max_rounds=1)
    history.add({"role": "user", "content": "r1"})
    history.add({"role": "assistant", "content": "a1"})
    history.add({"role": "user", "content": "r2"})
    history.add({"role": "assistant", "content": "a2"})

    trimmed = history.pop_trimmed()
    assert len(trimmed) == 2
    assert trimmed[0]["content"] == "r1"
    assert trimmed[1]["content"] == "a1"


def test_pop_trimmed_returns_and_clears():
    history = ConversationHistory(max_rounds=1)
    history.add({"role": "user", "content": "r1"})
    history.add({"role": "assistant", "content": "a1"})
    history.add({"role": "user", "content": "r2"})
    history.add({"role": "assistant", "content": "a2"})

    first = history.pop_trimmed()
    assert len(first) == 2

    second = history.pop_trimmed()
    assert second == []


# --- 摘要测试 ---

def test_summary_not_injected_when_none():
    history = ConversationHistory()
    history.add({"role": "user", "content": "hello"})
    msgs = history.get_messages()
    assert len(msgs) == 1
    assert msgs[0]["role"] == "user"


def test_summary_injected_in_get_messages():
    history = ConversationHistory()
    history.add({"role": "user", "content": "hello"})
    history.set_summary("用户之前查了项目列表")
    msgs = history.get_messages()
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert "[历史摘要]" in msgs[0]["content"]
    assert "用户之前查了项目列表" in msgs[0]["content"]


def test_set_summary_none_clears():
    history = ConversationHistory()
    history.set_summary("某个摘要")
    history.set_summary(None)
    history.add({"role": "user", "content": "hello"})
    msgs = history.get_messages()
    assert len(msgs) == 1


# --- 序列化测试 ---

def test_to_dict_from_dict_roundtrip():
    history = ConversationHistory(max_rounds=5, session_id="test")
    history.add({"role": "user", "content": "hello"})
    history.add({"role": "assistant", "content": "hi there"})
    history.set_summary("test summary")

    data = history.to_dict()
    restored = ConversationHistory.from_dict(data, session_id="test")

    assert restored._max_rounds == 5
    assert restored._summary == "test summary"
    assert len(restored._messages) == 2
    assert restored._messages[0]["role"] == "user"
    assert restored._messages[1]["content"] == "hi there"


# --- 持久化测试 ---

def test_save_and_load_roundtrip(tmp_path):
    history = ConversationHistory(max_rounds=5, session_id="test")
    history.add({"role": "user", "content": "save test"})
    history.add({"role": "assistant", "content": "saved response"})
    history.set_summary("persist summary")

    history.save(base_dir=tmp_path)
    loaded = ConversationHistory.load(session_id="test", base_dir=tmp_path)

    assert loaded._max_rounds == 5
    assert loaded._summary == "persist summary"
    assert len(loaded._messages) == 2
    assert loaded._messages[0]["content"] == "save test"


def test_load_nonexistent_returns_empty(tmp_path):
    loaded = ConversationHistory.load(session_id="nonexistent", base_dir=tmp_path)
    assert len(loaded._messages) == 0
    assert loaded._summary is None


def test_load_corrupted_file_returns_empty(tmp_path):
    path = tmp_path / "test.json"
    path.write_text("not valid json", encoding="utf-8")
    loaded = ConversationHistory.load(session_id="test", base_dir=tmp_path)
    assert len(loaded._messages) == 0


def test_clear_resets_state(tmp_path):
    history = ConversationHistory(max_rounds=5, session_id="test")
    history.add({"role": "user", "content": "hello"})
    history.set_summary("some summary")
    history.save(base_dir=tmp_path)

    history.clear(base_dir=tmp_path)
    assert len(history._messages) == 0
    assert history._summary is None
    assert history._trimmed_buffer == []
    assert not (tmp_path / "test.json").exists()
