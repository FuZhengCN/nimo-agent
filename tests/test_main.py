from unittest.mock import patch, MagicMock
from nimo.main import build_agent


def test_build_agent_loads_config():
    with patch("nimo.main.load_config") as mock_load:
        mock_load.return_value = MagicMock()
        with patch("nimo.main.Agent") as mock_agent:
            with patch("nimo.main.init_tapd"):
                build_agent("config.yaml")
                mock_load.assert_called_once_with("config.yaml")
                mock_agent.assert_called_once()
