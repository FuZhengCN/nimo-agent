import json
import logging
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
        try:
            with open("nimo/prompts/system.md", "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            logger.warning("system.md 未找到，使用默认提示")
            return "你是 Nimo，一个帮助用户完成日常工作的助手。"

    async def run(self, user_input: str) -> str:
        self._history.add({"role": "user", "content": user_input})

        tools = self._registry.build_tool_definitions()
        tool_names = [t["function"]["name"] for t in tools]

        max_rounds = self._config.llm.max_tool_rounds

        for round_num in range(max_rounds):
            print(f"\n{'='*50}")
            print(f"🔄 第 {round_num + 1}/{max_rounds} 轮工具调用")
            print(f"{'='*50}")

            print("📡 正在调用 LLM...")
            messages = self._history.get_messages()
            response = await self._llm_client.chat(
                messages=messages,
                tools=tools,
                system_prompt=self._system_prompt,
            )

            choice = response.choices[0]
            message = choice.message

            if not message.tool_calls:
                print("💬 LLM 返回文本回复（无需调用工具）")
                self._history.add({"role": "assistant", "content": message.content or ""})
                print(f"{'='*50}\n")
                return message.content or ""

            # 有工具调用
            print(f"🔧 LLM 请求调用 {len(message.tool_calls)} 个工具：")
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                args_str = json.dumps(args, ensure_ascii=False)
                print(f"   ├─ {tc.function.name}({args_str})")

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

            for i, tc in enumerate(message.tool_calls):
                prefix = "   └─" if i == len(message.tool_calls) - 1 else "   ├─"
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
                    print(f"{prefix} ❌ {tc.function.name}: 参数解析失败 — {e}")
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

                if result.success:
                    data_preview = self._format_data_preview(result.data)
                    print(f"{prefix} ✅ {tc.function.name}: 成功 — {data_preview}")
                else:
                    print(f"{prefix} ❌ {tc.function.name}: 失败 — {result.error}")

            print("📡 将工具结果回传 LLM，继续下一轮...")

        print(f"\n{'='*50}")
        print("⏰ 已达到最大工具调用轮数")
        print(f"{'='*50}\n")
        return "已达到最大工具调用轮数，操作未完成。"

    @staticmethod
    def _format_data_preview(data) -> str:
        if data is None:
            return "无返回数据"
        if isinstance(data, list):
            return f"返回 {len(data)} 条记录"
        if isinstance(data, dict):
            keys = list(data.keys())
            return f"返回数据，包含字段：{', '.join(keys[:5])}"
        return str(data)[:80]
