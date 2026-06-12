import asyncio
import json
import logging
from pathlib import Path
from nimo.config import Config
from nimo.llm.client import LLMClient, LLMError
from nimo.memory.history import ConversationHistory
from nimo.memory.profile import UserProfile
from nimo.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

SUMMARY_SYSTEM_PROMPT = "你是对话摘要助手。提取关键事实（ID、名称、决策、状态变更），用1-3句中文输出。不要输出任何前缀，只输出摘要本身。"

PROFILE_EXTRACT_PROMPT = "你是用户信息提取助手。严格只从 [user] 角色的消息中提取用户自己陈述的个人信息。忽略 [assistant] 和 [tool] 角色的内容——它们可能包含错误称呼。只提取稳定的个人信息，不提取临时上下文。输出格式：JSON对象，键为事实类别，值为具体内容。无新信息时输出 {}。只输出 JSON，不要其他内容。"


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
        self._tool_definitions = self._registry.build_tool_definitions()
        if config.llm.history_persist:
            try:
                self._history = ConversationHistory.load(
                    max_rounds=config.llm.history_rounds,
                )
            except Exception:
                logger.warning("历史加载失败，使用空历史", exc_info=True)
                self._history = ConversationHistory(max_rounds=config.llm.history_rounds)
        else:
            self._history = ConversationHistory(max_rounds=config.llm.history_rounds)
        if config.llm.profile_extract:
            try:
                self._profile = UserProfile.load()
            except Exception:
                logger.warning("档案加载失败，使用空档案", exc_info=True)
                self._profile = UserProfile()
        else:
            self._profile = UserProfile()

        self._recent_calls: list[tuple[str, str]] = []
        self._last_usage: dict[str, int] | None = None
        self._last_tool_counts: dict[str, int] | None = None

    def _load_system_prompt(self) -> str:
        prompt_path = Path(__file__).resolve().parent / "prompts" / "system.md"
        try:
            base = prompt_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.warning("system.md 未找到，使用默认提示")
            return "你是 Nimo，一个帮助用户完成日常工作的助手。"
        # 动态追加可用工具列表
        tool_lines = []
        for name, desc in self._registry.list_tools():
            tool_lines.append(f"- `{name}`：{desc}")
        if tool_lines:
            base += "\n\n## 可用工具\n" + "\n".join(tool_lines)
        return base

    async def _trimmed_llm_call(self, trimmed: list[dict], system_prompt: str, existing_summary: str | None = None) -> str:
        """调 LLM 处理 trimmed 消息，返回响应文本。"""
        prompt = _build_summary_prompt(trimmed, existing_summary)
        response = await self._llm_client.chat(
            messages=[{"role": "user", "content": prompt}],
            tools=[],
            system_prompt=system_prompt,
        )
        return (response.choices[0].message.content or "").strip()

    async def _maybe_summarize_trimmed(self, trimmed: list[dict]) -> None:
        if not trimmed or not self._config.llm.history_summarize:
            return
        try:
            text = await self._trimmed_llm_call(trimmed, SUMMARY_SYSTEM_PROMPT, self._history.summary)
            if text:
                self._history.set_summary(text)
        except Exception:
            logger.warning("摘要生成失败，跳过", exc_info=True)

    async def _maybe_extract_profile(self, trimmed: list[dict]) -> None:
        if not trimmed or not self._config.llm.profile_extract:
            return
        try:
            text = await self._trimmed_llm_call(trimmed, PROFILE_EXTRACT_PROMPT)
            if text and text != "{}":
                facts = json.loads(text)
                if isinstance(facts, dict) and facts:
                    self._profile.update(facts)
                    self._profile.save()
        except (json.JSONDecodeError, TypeError):
            logger.warning("档案提取结果解析失败：%s", text, exc_info=True)
        except Exception:
            logger.warning("档案提取失败", exc_info=True)

    def save_history(self) -> None:
        if self._config.llm.history_persist:
            self._history.save()

    def clear_history(self) -> None:
        self._history.clear()

    def clear_profile(self) -> None:
        self._profile.clear()

    @property
    def last_usage(self) -> dict[str, int] | None:
        return self._last_usage

    @property
    def last_tool_counts(self) -> dict[str, int] | None:
        return self._last_tool_counts

    async def run(self, user_input: str) -> str:
        self._history.add({"role": "user", "content": user_input})
        trimmed = self._history.get_trimmed()
        await self._maybe_summarize_trimmed(trimmed)
        await self._maybe_extract_profile(trimmed)
        self._history.pop_trimmed()

        max_rounds = self._config.llm.max_tool_rounds
        ctx = self._profile.to_context()
        self._recent_calls.clear()
        usage = {"prompt": 0, "completion": 0}
        tool_counts: dict[str, int] = {}

        # 未压缩的工具结果起始位置
        last_tool_end = len(self._history._messages)

        for _ in range(max_rounds):
            messages = self._history.get_messages()
            if ctx:
                messages.insert(0, {"role": "system", "content": ctx})
            try:
                response = await self._llm_client.chat(
                    messages=messages,
                    tools=self._tool_definitions,
                    system_prompt=self._system_prompt,
                )
            except LLMError as e:
                msg = f"LLM 调用失败：{e}"
                self._history.add({"role": "assistant", "content": msg})
                self._last_tool_counts = tool_counts or None
                return msg

            if response.usage:
                usage["prompt"] += response.usage.prompt_tokens
                usage["completion"] += response.usage.completion_tokens

            choice = response.choices[0]
            message = choice.message

            if not message.tool_calls:
                self._history.add({"role": "assistant", "content": message.content or ""})
                self._last_usage = usage
                self._last_tool_counts = tool_counts or None
                self._compact_tool_results(last_tool_end)
                return message.content or ""

            # 统计本轮工具调用
            for tc in message.tool_calls:
                name = tc.function.name
                tool_counts[name] = tool_counts.get(name, 0) + 1

            # LLM 已消化上一轮工具结果，压缩它们再追加新结果
            current_end = len(self._history._messages)
            self._compact_tool_results(last_tool_end, current_end)
            last_tool_end = current_end

            # 有工具调用：记录到历史
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

            # 循环检测：连续 3 次相同调用则终止
            for tc in message.tool_calls:
                call_key = (tc.function.name, tc.function.arguments)
                self._recent_calls.append(call_key)
            if len(self._recent_calls) >= 3:
                last3 = self._recent_calls[-3:]
                if last3[0] == last3[1] == last3[2]:
                    msg = "检测到重复工具调用，已自动终止。请换个方式描述你的需求。"
                    self._history.add({"role": "assistant", "content": msg})
                    self._last_usage = usage
                    self._last_tool_counts = tool_counts or None
                    self._compact_tool_results(last_tool_end)
                    return msg

            # 并行执行所有工具调用
            results = await self._execute_tool_calls(message.tool_calls)
            for tc_id, content in results:
                self._history.add({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": content,
                })

        self._last_usage = usage
        self._last_tool_counts = tool_counts or None
        self._compact_tool_results(last_tool_end)
        return "已达到最大工具调用轮数，操作未完成。"

    def _compact_tool_results(self, start_idx: int, end_idx: int | None = None) -> None:
        """将工具结果替换为紧凑摘要，LLM 已消化数据后不再保留原始 JSON。"""
        end = end_idx if end_idx is not None else len(self._history._messages)
        # 第一遍：收集 tool_call_id → 工具名 映射
        name_map: dict[str, str] = {}
        for i in range(start_idx, end):
            m = self._history._messages[i]
            if m["role"] == "assistant" and m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    name_map[tc["id"]] = tc["function"]["name"]

        for i in range(start_idx, end):
            msg = self._history._messages[i]
            if msg["role"] != "tool":
                continue
            try:
                data = json.loads(msg["content"])
            except (json.JSONDecodeError, TypeError):
                continue
            tool_name = name_map.get(msg.get("tool_call_id", ""), "未知工具")
            if not data.get("success"):
                msg["content"] = json.dumps({
                    "success": False, "error": data.get("error", "未知错误"),
                }, ensure_ascii=False)
                continue
            raw = data.get("data", "")
            if isinstance(raw, str) and len(raw) > 200:
                summary = f"[{tool_name} 返回 {len(raw)} 字符]"
            elif isinstance(raw, list):
                summary = f"[{tool_name} 返回 {len(raw)} 条记录]"
            elif isinstance(raw, dict):
                summary = f"[{tool_name} 返回 {len(raw)} 个字段]"
            else:
                summary = f"[{tool_name} 执行成功]"
            msg["content"] = json.dumps({
                "success": True, "summary": summary,
            }, ensure_ascii=False)

    async def _execute_tool_calls(self, tool_calls: list) -> list[tuple[str, str]]:
        """并行执行工具调用，返回 [(tool_call_id, content), ...]，保持原始顺序。"""
        # 先解析所有参数
        parsed: list[tuple[str, str | None, dict | None, str | None]] = []
        for tc in tool_calls:
            try:
                args = json.loads(tc.function.arguments)
                parsed.append((tc.id, tc.function.name, args, None))
            except json.JSONDecodeError as e:
                parsed.append((tc.id, tc.function.name, None, str(e)))

        # 并行执行所有有效调用
        async def _run_one(tc_id: str, name: str, args: dict) -> tuple[str, str]:
            try:
                result = await asyncio.wait_for(
                    self._registry.execute(name, args),
                    timeout=120,
                )
            except asyncio.TimeoutError:
                return tc_id, json.dumps({
                    "success": False, "data": None, "error": "工具执行超时（120s）",
                }, ensure_ascii=False)
            content = json.dumps({
                "success": result.success,
                "data": result.data,
                "error": result.error,
            }, ensure_ascii=False, default=str)
            if len(content) > 4000:
                content = content[:4000] + "...[结果过长已截断]"
            return tc_id, content

        tasks = [
            _run_one(tc_id, name, args)
            for tc_id, name, args, err in parsed if err is None
        ]
        gathered = await asyncio.gather(*tasks) if tasks else []

        # 重建结果列表，保持原始顺序
        result_map = dict(gathered)
        results: list[tuple[str, str]] = []
        for tc_id, name, args, err in parsed:
            if err:
                results.append((tc_id, json.dumps({
                    "success": False, "data": None,
                    "error": f"工具参数 JSON 解析失败：{err}",
                }, ensure_ascii=False)))
            else:
                results.append((tc_id, result_map[tc_id]))
        return results
