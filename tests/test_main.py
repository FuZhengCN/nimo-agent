import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from nimo.main import build_agent, _show_notification
from nimo.tools.schedule import Notification


@pytest.mark.asyncio
async def test_build_agent_loads_config():
    mock_config = MagicMock()
    mock_registry = MagicMock()
    mock_registry.init_all = AsyncMock()
    with patch("nimo.main.Agent") as mock_agent:
        with patch("nimo.main.ToolRegistry") as mock_registry_cls:
            mock_registry_cls.get_instance.return_value = mock_registry
            result = await build_agent(mock_config)

    mock_registry.init_all.assert_called_once_with(mock_config)
    mock_agent.assert_called_once_with(mock_config)
    assert result is mock_agent.return_value


def test_show_notification(capsys):
    """通知展示包含任务ID、时间和内容。"""
    _show_notification(Notification(
        task_id="test-task",
        completed_at="2026-06-17T14:30:00",
        summary="一切正常",
        full_text="检查完毕，无异常",
    ))

    captured = capsys.readouterr()
    assert "test-task" in captured.out
    assert "检查完毕，无异常" in captured.out
    assert "14:30" in captured.out
