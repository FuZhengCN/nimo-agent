import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from nimo.config import Config, LLMConfig, TapdConfig
from nimo.llm.client import LLMClient, LLMError


@pytest.fixture
def sample_config():
    return Config(
        llm=LLMConfig(
            api_key="sk-test",
            base_url="https://api.deepseek.com",
            model="deepseek-chat",
            max_tool_rounds=5,
            history_rounds=10,
        ),
        tapd=TapdConfig(
            api_base="https://api.tapd.cn",
            access_token="token",
            nick="user",
            company_id="123",
            owner="user",
        ),
    )


@pytest.mark.asyncio
async def test_chat_returns_response(sample_config):
    client = LLMClient(sample_config)

    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_msg = MagicMock()
    mock_msg.content = "你好，有什么可以帮助你的？"
    mock_msg.tool_calls = None
    mock_choice.message = mock_msg
    mock_response.choices = [mock_choice]

    with patch.object(
        client.client.chat.completions, "create",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        result = await client.chat(
            messages=[{"role": "user", "content": "你好"}],
            tools=[],
        )
        assert result.choices[0].message.content == "你好，有什么可以帮助你的？"


@pytest.mark.asyncio
async def test_chat_retries_on_429(sample_config):
    client = LLMClient(sample_config)

    with patch.object(
        client.client.chat.completions, "create",
        new_callable=AsyncMock,
    ) as mock_create:
        mock_create.side_effect = [
            Exception("429 rate limit"),
            Exception("429 rate limit"),
            MagicMock(choices=[MagicMock(message=MagicMock(content="ok", tool_calls=None))]),
        ]
        result = await client.chat(
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
        )
        assert mock_create.call_count == 3
        assert result.choices[0].message.content == "ok"
