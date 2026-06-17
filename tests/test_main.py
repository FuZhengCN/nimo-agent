import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from nimo.main import build_agent
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


def test_check_notifications_empty(capsys):
    """通知队列为空时无输出。"""
    from nimo.main import _check_schedule_notifications
    scheduler = MagicMock()
    scheduler.pop_notifications.return_value = []

    _check_schedule_notifications(scheduler)

    captured = capsys.readouterr()
    assert captured.out == ""


def test_check_notifications_user_says_no(monkeypatch):
    """用户选择跳过通知——函数不抛异常。"""
    from nimo.main import _check_schedule_notifications
    scheduler = MagicMock()
    scheduler.pop_notifications.return_value = [
        Notification(
            task_id="remind",
            completed_at="2026-06-17T14:30:00",
            summary="一切正常",
            full_text="检查完毕，无异常",
        )
    ]

    inputs = iter(["n"])
    monkeypatch.setattr("builtins.input", lambda _="": next(inputs))

    # Should not raise
    _check_schedule_notifications(scheduler)
