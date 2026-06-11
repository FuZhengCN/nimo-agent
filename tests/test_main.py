import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from nimo.main import build_agent


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
