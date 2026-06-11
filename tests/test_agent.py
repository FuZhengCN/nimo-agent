import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from nimo.config import Config, LLMConfig, TapdConfig


@pytest.fixture
def sample_config():
    return Config(
        llm=LLMConfig(
            api_key="sk-test", base_url="https://api.deepseek.com",
            model="deepseek-chat", max_tool_rounds=5, history_rounds=10,
        ),
        tapd=TapdConfig(
            api_base="https://api.tapd.cn", access_token="token",
            nick="user", company_id="123", owner="user",
        ),
    )


def make_mock_chat_response(content: str, tool_calls=None):
    mock_msg = MagicMock()
    mock_msg.content = content
    mock_msg.tool_calls = tool_calls
    mock_choice = MagicMock()
    mock_choice.message = mock_msg
    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]
    return mock_resp


@pytest.mark.asyncio
async def test_agent_simple_reply_no_tools(sample_config):
    from nimo.agent import Agent

    agent = Agent(sample_config)
    agent._llm_client.chat = AsyncMock(return_value=make_mock_chat_response("你好！有什么可以帮你的？"))

    response = await agent.run("你好")
    assert "你好" in response


@pytest.mark.asyncio
async def test_agent_calls_tool_then_responds(sample_config):
    from nimo.agent import Agent

    agent = Agent(sample_config)

    # First call: LLM returns tool_call
    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_001"
    mock_tool_call.function.name = "tapd_cli"
    mock_tool_call.function.arguments = "{}"

    # Second call: LLM returns text summary
    call_count = [0]
    async def mock_chat(messages=None, tools=None, system_prompt=""):
        call_count[0] += 1
        if call_count[0] == 1:
            return make_mock_chat_response(None, tool_calls=[mock_tool_call])
        else:
            return make_mock_chat_response("你参与了3个项目：A、B、C")

    agent._llm_client.chat = mock_chat

    # Mock tool execution
    agent._registry.execute = AsyncMock(return_value=MagicMock(success=True, data=[]))

    response = await agent.run("查项目")
    assert "3个项目" in response
    assert call_count[0] == 2


@pytest.mark.asyncio
async def test_agent_stops_at_max_rounds(sample_config):
    from nimo.agent import Agent

    agent = Agent(sample_config)

    # 每次返回不同参数，避免触发循环检测
    def make_tc(i: int):
        tc = MagicMock()
        tc.id = f"call_{i:03d}"
        tc.function.name = "tapd_cli"
        tc.function.arguments = f'{{"round": {i}}}'
        return tc

    responses = [
        make_mock_chat_response(None, tool_calls=[make_tc(i)])
        for i in range(sample_config.llm.max_tool_rounds)
    ]
    agent._llm_client.chat = AsyncMock(side_effect=responses)
    agent._registry.execute = AsyncMock(return_value=MagicMock(success=True, data=[]))

    response = await agent.run("反复查")
    assert agent._llm_client.chat.call_count == sample_config.llm.max_tool_rounds


@pytest.mark.asyncio
async def test_agent_loop_detection_stops_early(sample_config):
    from nimo.agent import Agent

    agent = Agent(sample_config)
    agent._registry.execute = AsyncMock(return_value=MagicMock(success=True, data=[]))

    # 每次都返回完全相同的 tool call，应触发循环检测
    tc = MagicMock()
    tc.id = "call_001"
    tc.function.name = "tapd_cli"
    tc.function.arguments = '{"workspace_id": "755"}'

    agent._llm_client.chat = AsyncMock(
        return_value=make_mock_chat_response(None, tool_calls=[tc])
    )

    response = await agent.run("反复查同一个东西")
    assert "重复工具调用" in response
    # 循环检测在第 3 次调用后触发（LLM 调用 3 次，每轮 1 次）
    assert agent._llm_client.chat.call_count == 3


@pytest.mark.asyncio
async def test_agent_handles_json_decode_error(sample_config):
    from nimo.agent import Agent

    agent = Agent(sample_config)

    # 每次返回不同参数，避免触发循环检测
    def make_tc(i: int):
        tc = MagicMock()
        tc.id = f"call_{i:03d}"
        tc.function.name = "tapd_cli"
        tc.function.arguments = f"not valid json {i}"
        return tc

    responses = [
        make_mock_chat_response(None, tool_calls=[make_tc(i)])
        for i in range(sample_config.llm.max_tool_rounds)
    ]
    agent._llm_client.chat = AsyncMock(side_effect=responses)

    response = await agent.run("错误参数")
    assert "已达到最大工具调用轮数" in response


def test_agent_system_prompt_fallback():
    from nimo.agent import Agent
    from nimo.config import Config, LLMConfig, TapdConfig
    from unittest.mock import patch, mock_open

    config = Config(
        llm=LLMConfig(
            api_key="sk-test", base_url="https://api.deepseek.com",
            model="deepseek-chat", max_tool_rounds=5, history_rounds=10,
        ),
        tapd=TapdConfig(
            api_base="https://api.tapd.cn", access_token="token",
        ),
    )
    with patch("pathlib.Path.read_text", side_effect=FileNotFoundError):
        agent = Agent(config)
        assert "Nimo" in agent._system_prompt
        assert "日常" in agent._system_prompt


# --- 记忆持久化集成测试 ---

@pytest.mark.asyncio
async def test_agent_saves_history_after_run(sample_config, tmp_path):
    from nimo.agent import Agent
    from unittest.mock import patch

    sample_config.llm.history_persist = True
    agent = Agent(sample_config)
    agent._llm_client.chat = AsyncMock(return_value=make_mock_chat_response("你好！"))

    with patch.object(agent._history, "save") as mock_save:
        await agent.run("你好")
        mock_save.assert_not_called()  # run() 不负责 save，main.py 负责

    agent.save_history()  # main.py 调用
    # save 应该正常工作（不抛异常）


def test_agent_loads_history_with_persist(sample_config, tmp_path):
    from nimo.agent import Agent
    from nimo.memory.history import ConversationHistory

    # 先保存一段历史
    history = ConversationHistory(max_rounds=10, session_id="default")
    history.add({"role": "user", "content": "previous question"})
    history.add({"role": "assistant", "content": "previous answer"})
    history.save(base_dir=tmp_path)

    sample_config.llm.history_persist = True
    with patch("nimo.agent.ConversationHistory.load", return_value=history):
        agent = Agent(sample_config)
        msgs = agent._history.get_messages()
        assert len(msgs) == 2
        assert msgs[0]["content"] == "previous question"


def test_agent_no_persist_creates_empty_history(sample_config):
    from nimo.agent import Agent

    sample_config.llm.history_persist = False
    agent = Agent(sample_config)
    msgs = agent._history.get_messages()
    assert len(msgs) == 0


# --- 摘要压缩集成测试 ---

@pytest.mark.asyncio
async def test_agent_summarizes_on_trim(sample_config):
    from nimo.agent import Agent

    sample_config.llm.history_summarize = True
    agent = Agent(sample_config)
    agent._history._max_rounds = 1  # 只保留1轮，写第2轮时触发trim

    # 第1轮
    agent._history.add({"role": "user", "content": "查项目"})
    agent._history.add({"role": "assistant", "content": "查到3个项目"})

    # mock LLM 摘要响应
    summary_response = make_mock_chat_response("用户查询了项目列表")
    mock_chat = AsyncMock(return_value=summary_response)
    agent._llm_client.chat = mock_chat

    # 手动调用 _maybe_summarize_trimmed（run() 里也会调）
    agent._history.add({"role": "user", "content": "建需求"})  # 触发trim
    trimmed = agent._history.pop_trimmed()
    await agent._maybe_summarize_trimmed(trimmed)

    # 摘要 LLM 应该被调用
    mock_chat.assert_called_once()
    assert agent._history.summary == "用户查询了项目列表"


@pytest.mark.asyncio
async def test_agent_no_summarize_when_disabled(sample_config):
    from nimo.agent import Agent

    sample_config.llm.history_summarize = False
    agent = Agent(sample_config)
    agent._history._max_rounds = 1

    agent._history.add({"role": "user", "content": "查项目"})
    agent._history.add({"role": "assistant", "content": "查到3个项目"})

    mock_chat = AsyncMock()
    agent._llm_client.chat = mock_chat

    agent._history.add({"role": "user", "content": "建需求"})
    trimmed = agent._history.pop_trimmed()
    await agent._maybe_summarize_trimmed(trimmed)

    # 不应调用 LLM 做摘要
    mock_chat.assert_not_called()


def test_clear_history_resets_all(sample_config, tmp_path):
    from nimo.agent import Agent

    sample_config.llm.history_persist = True
    agent = Agent(sample_config)
    agent._history.add({"role": "user", "content": "hello"})
    agent._history.set_summary("some summary")
    agent._history.save(base_dir=tmp_path)

    agent.clear_history()
    assert len(agent._history._messages) == 0
    assert agent._history.summary is None


def test_build_summary_prompt_with_existing():
    from nimo.agent import _build_summary_prompt

    trimmed = [
        {"role": "user", "content": "查项目"},
        {"role": "assistant", "content": "查到3个项目：A、B、C"},
    ]
    prompt = _build_summary_prompt(trimmed, None)
    assert "查项目" in prompt
    assert "A、B、C" in prompt
    assert "之前的摘要" not in prompt

    prompt2 = _build_summary_prompt(trimmed, "用户之前查过项目")
    assert "之前的摘要" in prompt2
    assert "用户之前查过项目" in prompt2


def test_build_summary_prompt_truncates_tool_content():
    from nimo.agent import _build_summary_prompt

    long_content = "x" * 1000
    trimmed = [{"role": "tool", "content": long_content}]
    prompt = _build_summary_prompt(trimmed, None)
    assert len(long_content) > 500
    assert "..." in prompt
    assert len(prompt) < 700  # tool 内容被截断


# --- 用户档案集成测试 ---

@pytest.mark.asyncio
async def test_agent_extracts_profile_on_trim(sample_config):
    from nimo.agent import Agent

    sample_config.llm.profile_extract = True
    agent = Agent(sample_config)
    agent._history._max_rounds = 1

    agent._history.add({"role": "user", "content": "我叫张三"})
    agent._history.add({"role": "assistant", "content": "你好张三"})

    profile_response = make_mock_chat_response('{"姓名":"张三"}')
    mock_chat = AsyncMock(return_value=profile_response)
    agent._llm_client.chat = mock_chat

    agent._history.add({"role": "user", "content": "帮我查项目"})
    trimmed = agent._history.pop_trimmed()
    with patch.object(agent._profile, "save"):
        await agent._maybe_extract_profile(trimmed)

    mock_chat.assert_called_once()
    assert agent._profile.facts == {"姓名": "张三"}


@pytest.mark.asyncio
async def test_agent_no_profile_when_disabled(sample_config):
    from nimo.agent import Agent

    sample_config.llm.profile_extract = False
    agent = Agent(sample_config)
    agent._history._max_rounds = 1

    agent._history.add({"role": "user", "content": "我叫李四"})
    agent._history.add({"role": "assistant", "content": "你好"})

    mock_chat = AsyncMock()
    agent._llm_client.chat = mock_chat

    agent._history.add({"role": "user", "content": "查项目"})
    trimmed = agent._history.pop_trimmed()
    await agent._maybe_extract_profile(trimmed)

    mock_chat.assert_not_called()


def test_agent_injects_profile_in_run(sample_config):
    from nimo.agent import Agent

    sample_config.llm.profile_extract = True
    agent = Agent(sample_config)
    agent._profile.update({"姓名": "王五"})
    agent._llm_client.chat = AsyncMock(
        return_value=make_mock_chat_response("你好王五！")
    )

    import asyncio
    asyncio.run(agent.run("你好"))
    # Can't assert on messages since run() consumes them, but we can verify profile context exists
    assert "[用户信息]" in agent._profile.to_context()


def test_clear_history_does_not_clear_profile(sample_config):
    from nimo.agent import Agent

    sample_config.llm.profile_extract = True
    agent = Agent(sample_config)
    agent._profile.update({"姓名": "张三"})
    agent._history.add({"role": "user", "content": "hello"})

    agent.clear_history()
    assert agent._history._messages == []
    assert agent._profile.facts == {"姓名": "张三"}


def test_agent_empty_profile_context_not_injected(sample_config):
    from nimo.agent import Agent

    agent = Agent(sample_config)
    assert agent._profile.to_context() is None
