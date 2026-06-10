import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from nimo.config import Config, LLMConfig, TapdConfig

# Module-level import triggers @register_tool once.
import nimo.tools.tapd


@pytest.fixture
def sample_config():
    return Config(
        llm=LLMConfig(
            api_key="sk-test", base_url="https://api.deepseek.com",
            model="deepseek-chat", max_tool_rounds=5, history_rounds=10,
        ),
        tapd=TapdConfig(
            api_base="https://api.tapd.cn", access_token="token123",
            nick="testuser", company_id="12345", owner="testuser",
        ),
    )


@pytest.mark.asyncio
async def test_cli_workspace_list(sample_config):
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'[{"id":"755","name":"TAPD"}]', b""))

    with patch.object(nimo.tools.tapd, "_config", sample_config):
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
            result = await nimo.tools.tapd.tapd_cli(["workspace", "list"])
            assert result.success is True
            assert "TAPD" in result.data


@pytest.mark.asyncio
async def test_cli_timesheet_add(sample_config):
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'{"Timesheet":{"id":"1001"}}', b""))

    with patch.object(nimo.tools.tapd, "_config", sample_config):
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
            result = await nimo.tools.tapd.tapd_cli([
                "timesheet", "add", "--workspace-id", "755",
                "--entity-type", "story", "--entity-id", "1001",
                "--timespent", "2",
            ])
            assert result.success is True


@pytest.mark.asyncio
async def test_cli_error_return(sample_config):
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"", "参数错误".encode()))

    with patch.object(nimo.tools.tapd, "_config", sample_config):
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
            result = await nimo.tools.tapd.tapd_cli(["story", "list"])
            assert result.success is False
            assert "参数错误" in result.error


@pytest.mark.asyncio
async def test_cli_binary_not_found(sample_config):
    with patch.object(nimo.tools.tapd, "_config", sample_config):
        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
            result = await nimo.tools.tapd.tapd_cli(["workspace", "list"])
            assert result.success is False
            assert "未找到" in result.error


def test_validate_unknown_command():
    result = nimo.tools.tapd._validate_args(["rm", "-rf"])
    assert result is not None
    assert "不允许" in result


def test_validate_empty_args():
    result = nimo.tools.tapd._validate_args([])
    assert result is not None
    assert "不能为空" in result


def test_validate_flag_as_command():
    result = nimo.tools.tapd._validate_args(["--help"])
    assert result is not None
    assert "无效" in result


def test_validate_path_traversal():
    result = nimo.tools.tapd._validate_args(["story", "../../etc/passwd"])
    assert result is not None
    assert "路径遍历" in result


def test_validate_valid_commands():
    for cmd in ["workspace", "story", "task", "bug", "timesheet", "iteration", "comment", "wiki", "launch", "workflow", "url"]:
        assert nimo.tools.tapd._validate_args([cmd, "list"]) is None
