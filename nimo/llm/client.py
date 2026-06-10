import asyncio
import logging
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion
from nimo.config import Config

logger = logging.getLogger(__name__)


class LLMError(Exception):
    pass


class LLMClient:
    def __init__(self, config: Config):
        self.client = AsyncOpenAI(
            api_key=config.llm.api_key,
            base_url=config.llm.base_url,
            timeout=60.0,
        )
        self.model = config.llm.model
        self._max_retries = 3

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str = "",
    ) -> ChatCompletion:
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        for attempt in range(self._max_retries):
            try:
                kwargs = {
                    "model": self.model,
                    "messages": full_messages,
                }
                if tools:
                    kwargs["tools"] = tools
                return await self.client.chat.completions.create(**kwargs)
            except Exception as e:
                if attempt == self._max_retries - 1:
                    raise LLMError(f"LLM 调用失败，已重试 {self._max_retries} 次：{e}")
                wait = 2 ** attempt
                logger.warning(f"LLM 调用失败（第 {attempt + 1} 次），{wait}s 后重试：{e}")
                await asyncio.sleep(wait)
