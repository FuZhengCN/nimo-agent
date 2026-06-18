import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from nimo.config import Config, LLMConfig, TapdConfig, TortoiseSvnConfig
from nimo.engine import ExecutionEngine

import nimo.tools.svn_intent


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
        tortoisesvn=TortoiseSvnConfig(paths={"default": "/tmp/repo"}),
    )


@pytest.mark.asyncio
async def test_svn_op_log(sample_config):
    """svn_op log -> 引擎 direct 模式。"""
    engine = ExecutionEngine.get_instance()
    engine.init(sample_config)

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"r123 | user | msg", b""))

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        result = await nimo.tools.svn_intent.svn_op(
            action="log", project="default", extra={"limit": 5},
        )
    assert result.success is True
    assert "r123" in str(result.data)


@pytest.mark.asyncio
async def test_svn_op_no_config():
    """无 SVN 配置 -> 应报错。"""
    ExecutionEngine.reset()
    result = await nimo.tools.svn_intent.svn_op(action="log")
    assert result.success is False


@pytest.mark.asyncio
async def test_svn_op_commit_message(sample_config):
    """svn_op commit 带 message。"""
    engine = ExecutionEngine.get_instance()
    engine.init(sample_config)

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"Committed revision 99.", b""))

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        result = await nimo.tools.svn_intent.svn_op(
            action="commit", project="default",
            extra={"message": "fix bug"},
        )
    assert result.success is True
