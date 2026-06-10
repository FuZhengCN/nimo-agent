import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_full_flow_list_projects():
    """模拟用户查项目列表的完整对话流程。"""
    from nimo.agent import Agent
    from nimo.config import Config, LLMConfig, TapdConfig

    config = Config(
        llm=LLMConfig(
            api_key="sk-test", base_url="https://api.deepseek.com",
            model="deepseek-chat", max_tool_rounds=5, history_rounds=10,
        ),
        tapd=TapdConfig(
            api_base="https://api.tapd.cn", access_token="token",
            nick="user", company_id="123", owner="user",
        ),
    )

    agent = Agent(config)

    mock_projects = [{"Workspace": {"id": "755", "name": "示例项目", "status": "normal"}}]

    # Mock LLM: tool call first, then final text
    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_int_1"
    mock_tool_call.function.name = "tapd_list_projects"
    mock_tool_call.function.arguments = "{}"

    call_count = [0]

    async def mock_chat(messages=None, tools=None, system_prompt=""):
        call_count[0] += 1
        if call_count[0] == 1:
            mock_msg = MagicMock()
            mock_msg.content = None
            mock_msg.tool_calls = [mock_tool_call]
            mock_choice = MagicMock()
            mock_choice.message = mock_msg
            mock_resp = MagicMock()
            mock_resp.choices = [mock_choice]
            return mock_resp
        else:
            mock_msg2 = MagicMock()
            mock_msg2.content = "你参与了1个项目：示例项目 (ID: 755)"
            mock_msg2.tool_calls = None
            mock_choice2 = MagicMock()
            mock_choice2.message = mock_msg2
            mock_resp2 = MagicMock()
            mock_resp2.choices = [mock_choice2]
            return mock_resp2

    agent._llm_client.chat = mock_chat
    from nimo.tools.registry import ToolResult
    agent._registry.execute = AsyncMock(return_value=ToolResult(success=True, data=mock_projects))

    response = await agent.run("查项目")
    assert "示例项目" in response
    assert "755" in response
    assert call_count[0] == 2


@pytest.mark.asyncio
async def test_full_flow_add_workhour():
    """模拟用户填工时的完整对话流程。"""
    from nimo.agent import Agent
    from nimo.config import Config, LLMConfig, TapdConfig

    config = Config(
        llm=LLMConfig(
            api_key="sk-test", base_url="https://api.deepseek.com",
            model="deepseek-chat", max_tool_rounds=5, history_rounds=10,
        ),
        tapd=TapdConfig(
            api_base="https://api.tapd.cn", access_token="token",
            nick="user", company_id="123", owner="user",
        ),
    )

    agent = Agent(config)

    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_int_2"
    mock_tool_call.function.name = "tapd_add_workhour"
    mock_tool_call.function.arguments = '{"workspace_id": 755, "entity_type": "story", "entity_id": 1001, "timespent": "2", "spentdate": "2026-06-10", "memo": "需求评审"}'

    call_count = [0]

    async def mock_chat(messages=None, tools=None, system_prompt=""):
        call_count[0] += 1
        if call_count[0] == 1:
            mock_msg = MagicMock()
            mock_msg.content = None
            mock_msg.tool_calls = [mock_tool_call]
            mock_choice = MagicMock()
            mock_choice.message = mock_msg
            mock_resp = MagicMock()
            mock_resp.choices = [mock_choice]
            return mock_resp
        else:
            mock_msg2 = MagicMock()
            mock_msg2.content = "已填写：2026-06-10，需求 #1001，2小时 — 需求评审"
            mock_msg2.tool_calls = None
            mock_choice2 = MagicMock()
            mock_choice2.message = mock_msg2
            mock_resp2 = MagicMock()
            mock_resp2.choices = [mock_choice2]
            return mock_resp2

    agent._llm_client.chat = mock_chat
    from nimo.tools.registry import ToolResult
    agent._registry.execute = AsyncMock(
        return_value=ToolResult(success=True, data={"Timesheet": {"id": "2001"}})
    )

    response = await agent.run("在755项目里填2小时工时")
    assert "2小时" in response
    assert call_count[0] == 2
