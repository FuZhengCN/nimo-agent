import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from openai import RateLimitError, BadRequestError
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
    mock_response = MagicMock()

    with patch.object(
        client.client.chat.completions, "create",
        new_callable=AsyncMock,
    ) as mock_create:
        mock_create.side_effect = [
            RateLimitError("429 rate limit", response=mock_response, body=None),
            RateLimitError("429 rate limit", response=mock_response, body=None),
            MagicMock(choices=[MagicMock(message=MagicMock(content="ok", tool_calls=None))]),
        ]
        result = await client.chat(
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
        )
        assert mock_create.call_count == 3
        assert result.choices[0].message.content == "ok"


@pytest.mark.asyncio
async def test_retry_exhaustion_raises_llm_error(sample_config):
    client = LLMClient(sample_config)
    mock_response = MagicMock()

    with patch.object(
        client.client.chat.completions, "create",
        new_callable=AsyncMock,
    ) as mock_create:
        mock_create.side_effect = RateLimitError(
            "429 rate limit", response=mock_response, body=None
        )
        with pytest.raises(LLMError, match="已重试 3 次"):
            await client.chat(
                messages=[{"role": "user", "content": "hi"}],
                tools=[],
            )
        # 1 initial + 3 retries = 4 total calls
        assert mock_create.call_count == 4


@pytest.mark.asyncio
async def test_4xx_error_propagates_immediately(sample_config):
    client = LLMClient(sample_config)
    mock_response = MagicMock()

    with patch.object(
        client.client.chat.completions, "create",
        new_callable=AsyncMock,
    ) as mock_create:
        mock_create.side_effect = BadRequestError(
            "400 bad request", response=mock_response, body=None
        )
        with pytest.raises(BadRequestError):
            await client.chat(
                messages=[{"role": "user", "content": "hi"}],
                tools=[],
            )
        # 4xx 不重试，只调用 1 次
        assert mock_create.call_count == 1
