import json
import logging
from pathlib import Path
from nimo.config import Config
from nimo.llm.client import LLMClient
from nimo.memory.history import ConversationHistory
from nimo.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class Agent:
    def __init__(self, config: Config):
        self._config = config
        self._llm_client = LLMClient(config)
        self._history = ConversationHistory(max_rounds=config.llm.history_rounds)
        self._registry = ToolRegistry.get_instance()
        self._system_prompt = self._load_system_prompt()

    def _load_system_prompt(self) -> str:
        prompt_path = Path(__file__).resolve().parent / "prompts" / "system.md"
        try:
            return prompt_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.warning("system.md 未找到，使用默认提示")
            return "你是 Nimo，一个帮助用户完成日常工作的助手。"

    async def run(self, user_input: str) -> str:
        self._history.add({"role": "user", "content": user_input})

        tools = self._registry.build_tool_definitions()

        max_rounds = self._config.llm.max_tool_rounds

        for _ in range(max_rounds):
            messages = self._history.get_messages()
            response = await self._llm_client.chat(
                messages=messages,
                tools=tools,
                system_prompt=self._system_prompt,
            )

            choice = response.choices[0]
            message = choice.message

            if not message.tool_calls:
                self._history.add({"role": "assistant", "content": message.content or ""})
                return message.content or ""

            # 有工具调用
            self._history.add({
                "role": "assistant",
                "content": message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in message.tool_calls
                ],
            })

            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError as e:
                    self._history.add({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": json.dumps({
                            "success": False,
                            "data": None,
                            "error": f"工具参数 JSON 解析失败：{e}",
                        }, ensure_ascii=False),
                    })
                    continue

                result = await self._registry.execute(tc.function.name, args)
                self._history.add({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps({
                        "success": result.success,
                        "data": result.data,
                        "error": result.error,
                    }, ensure_ascii=False, default=str),
                })

        return "已达到最大工具调用轮数，操作未完成。"

