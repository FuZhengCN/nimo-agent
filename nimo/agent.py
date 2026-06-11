import json
import logging
from pathlib import Path
from nimo.config import Config
from nimo.llm.client import LLMClient
from nimo.memory.history import ConversationHistory
from nimo.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

SUMMARY_SYSTEM_PROMPT = "你是对话摘要助手。提取关键事实（ID、名称、决策、状态变更），用1-3句中文输出。不要输出任何前缀，只输出摘要本身。"


def _build_summary_prompt(trimmed: list[dict], existing_summary: str | None) -> str:
    parts = []
    for msg in trimmed:
        content = msg.get("content", "") or ""
        if msg["role"] == "tool" and len(content) > 500:
            content = content[:500] + "..."
        parts.append(f"[{msg['role']}] {content}")
    text = "\n".join(parts)
    prefix = ""
    if existing_summary:
        prefix = f"之前的摘要：{existing_summary}\n\n"
    return f"{prefix}请为以下对话生成摘要：\n{text}"


class Agent:
    def __init__(self, config: Config):
        self._config = config
        self._llm_client = LLMClient(config)
        self._registry = ToolRegistry.get_instance()
        self._system_prompt = self._load_system_prompt()
        if config.llm.history_persist:
            self._history = ConversationHistory.load(
                max_rounds=config.llm.history_rounds,
            )
        else:
            self._history = ConversationHistory(max_rounds=config.llm.history_rounds)

    def _load_system_prompt(self) -> str:
        prompt_path = Path(__file__).resolve().parent / "prompts" / "system.md"
        try:
            return prompt_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.warning("system.md 未找到，使用默认提示")
            return "你是 Nimo，一个帮助用户完成日常工作的助手。"

    async def _maybe_summarize_trimmed(self) -> None:
        trimmed = self._history.pop_trimmed()
        if not trimmed:
            return
        if not self._config.llm.history_summarize:
            return
        try:
            existing = self._history.summary
            prompt = _build_summary_prompt(trimmed, existing)
            response = await self._llm_client.chat(
                messages=[{"role": "user", "content": prompt}],
                tools=[],
                system_prompt=SUMMARY_SYSTEM_PROMPT,
            )
            text = (response.choices[0].message.content or "").strip()
            if text:
                self._history.set_summary(text)
        except Exception:
            logger.warning("摘要生成失败，跳过", exc_info=True)

    def save_history(self) -> None:
        if self._config.llm.history_persist:
            self._history.save()

    def clear_history(self) -> None:
        self._history.clear()
        if self._config.llm.history_persist:
            self._history.clear()

    async def run(self, user_input: str) -> str:
        self._history.add({"role": "user", "content": user_input})
        await self._maybe_summarize_trimmed()

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
