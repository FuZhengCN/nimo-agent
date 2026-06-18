import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from nimo.config import Config, LLMConfig, TapdConfig
from nimo.engine import ExecutionEngine

# 触发 @register_tool
import nimo.tools.tapd_intent


@pytest.fixture(autouse=True)
def reset_engine():
    ExecutionEngine.reset()


@pytest.fixture
def sample_config():
    return Config(
        llm=LLMConfig(
            api_key="sk-test", base_url="https://api.deepseek.com",
            model="deepseek-chat", max_tool_rounds=5, history_rounds=10,
        ),
        tapd=TapdConfig(
            api_base="https://api.tapd.cn", access_token="token123",
        ),
    )


@pytest.mark.asyncio
async def test_tapd_query_workspace_list(sample_config):
    """tapd_query workspace_list -> 调引擎 direct 模式。"""
    engine = ExecutionEngine.get_instance()
    engine.init(sample_config)

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(
        b'[{"id":"755","name":"TAPD"}]', b"",
    ))

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        result = await nimo.tools.tapd_intent.tapd_query(action="workspace_list")
    assert result.success is True
    assert "TAPD" in str(result.data)


@pytest.mark.asyncio
async def test_tapd_query_timesheet_with_owner(sample_config):
    """tapd_query timesheet_list + owner -> for_each_workspace。"""
    engine = ExecutionEngine.get_instance()
    engine.init(sample_config)

    ws_proc = MagicMock()
    ws_proc.returncode = 0
    ws_proc.communicate = AsyncMock(return_value=(
        b'[{"id":"755","name":"TAPD"}]', b"",
    ))

    ts_proc = MagicMock()
    ts_proc.returncode = 0
    ts_proc.communicate = AsyncMock(return_value=(b'[{"Timesheet":{"id":"1"}}]', b""))

    mock_create = AsyncMock(side_effect=[ws_proc, ts_proc])

    with patch("asyncio.create_subprocess_exec", new=mock_create):
        result = await nimo.tools.tapd_intent.tapd_query(
            action="timesheet_list", owner="傅政",
        )
    assert result.success is True
    assert len(result.data["items"]) == 1


@pytest.mark.asyncio
async def test_tapd_query_engine_not_initialized():
    """引擎未初始化 -> 应报错。"""
    ExecutionEngine.reset()
    result = await nimo.tools.tapd_intent.tapd_query(
        action="workspace_list",
    )
    assert result.success is False
