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
    mock_tool_call.function.name = "tapd_list_projects"
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

    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_001"
    mock_tool_call.function.name = "tapd_list_projects"
    mock_tool_call.function.arguments = "{}"

    agent._llm_client.chat = AsyncMock(
        return_value=make_mock_chat_response(None, tool_calls=[mock_tool_call])
    )
    agent._registry.execute = AsyncMock(return_value=MagicMock(success=True, data=[]))

    response = await agent.run("反复查")
    assert agent._llm_client.chat.call_count == sample_config.llm.max_tool_rounds
