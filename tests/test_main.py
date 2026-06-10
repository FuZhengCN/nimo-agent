from unittest.mock import MagicMock, patch

from nimo.main import build_agent


def test_build_agent_loads_config():
    mock_config = MagicMock()
    with patch("nimo.main.Agent") as mock_agent:
        with patch("nimo.main.init_tapd") as mock_init_tapd:
            result = build_agent(mock_config)

    mock_init_tapd.assert_called_once_with(mock_config)
    mock_agent.assert_called_once_with(mock_config)
    assert result is mock_agent.return_value
