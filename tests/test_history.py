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
