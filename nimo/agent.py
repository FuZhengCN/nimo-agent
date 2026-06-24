import asyncio
import json
import logging
import time
from collections.abc import Callable
from pathlib import Path
from nimo.skill.registry import SkillRegistry
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
        self._skill_registry = SkillRegistry.get_instance()
        skills_dir = str(Path.home() / ".nimo" / "skills")
        self._skill_registry.discover(skills_dir)
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
        self._last_timings: list[dict] = []

    def _load_system_prompt(self) -> str:
        from datetime import date
        _WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        today = date.today()
        today_str = f"{today.year}年{today.month}月{today.day}日 {_WEEKDAYS[today.weekday()]}"
        prompt_path = Path(__file__).resolve().parent / "prompts" / "system.md"
        try:
            base = prompt_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            logger.warning("system.md 未找到，使用默认提示")
            return "你是 Nimo，一个帮助用户完成日常工作的助手。"
        base = f"今天是 {today_str}。\n\n" + base
        tool_lines = []
        for name, desc in self._registry.list_tools():
            tool_lines.append(f"- `{name}`：{desc}")
        if tool_lines:
            base += "\n\n## 可用工具\n" + "\n".join(tool_lines)
        skill_meta = self._skill_registry.list_meta()
        if skill_meta:
            lines = ["\n## 可用技能\n"]
            for m in skill_meta:
                desc = m["description"][:100] if m["description"] else "无描述"
                lines.append(f"- `{m['name']}`：{desc}")
                toc = m.get("sections", [])
                if toc:
                    lines.append(f"  → 章节：{'、'.join(toc[:12])}{'...' if len(toc) > 12 else ''}")
            base += "\n".join(lines)
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

    def reload_system_prompt(self) -> None:
        """重建 system prompt（技能安装/卸载后调用）。"""
        self._system_prompt = self._load_system_prompt()

    @property
    def last_usage(self) -> dict[str, int] | None:
        return self._last_usage

    @property
    def last_tool_counts(self) -> dict[str, int] | None:
        return self._last_tool_counts

    async def run(self, user_input: str, on_progress: Callable[[str], None] | None = None) -> str:
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
        timings: list[dict] = []

        for round_num in range(1, max_rounds + 1):
            messages = self._history.get_messages()
            if ctx:
                messages.insert(0, {"role": "system", "content": ctx})
            if on_progress:
                on_progress("分析中...")
            t0 = time.monotonic()
            system_prompt = self._system_prompt
            instructions = self._skill_registry.get_active_instructions()
            if instructions:
                system_prompt = system_prompt + "\n\n## 已激活技能\n" + instructions
            try:
                response = await self._llm_client.chat(
                    messages=messages,
                    tools=self._tool_definitions,
                    system_prompt=system_prompt,
                )
            except LLMError as e:
                msg = f"LLM 调用失败：{e}"
                self._history.add({"role": "assistant", "content": msg})
                self._last_tool_counts = tool_counts or None
                self._last_timings = timings
                return msg

            llm_time = time.monotonic() - t0

            if response.usage:
                usage["prompt"] += response.usage.prompt_tokens
                usage["completion"] += response.usage.completion_tokens

            choice = response.choices[0]
            message = choice.message

            if not message.tool_calls:
                timings.append({"round": round_num, "llm_time": llm_time, "tool_time": 0, "tools": []})
                self._history.add({"role": "assistant", "content": message.content or ""})
                self._last_usage = usage
                self._last_tool_counts = tool_counts or None
                self._last_timings = timings
                return message.content or ""

            # 统计本轮工具调用
            for tc in message.tool_calls:
                name = tc.function.name
                tool_counts[name] = tool_counts.get(name, 0) + 1

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
                    self._last_timings = timings
                    return msg

            # 并行执行所有工具调用
            if on_progress:
                tool_names = [tc.function.name for tc in message.tool_calls]
                if len(tool_names) == 1:
                    on_progress(f"执行工具: {tool_names[0]}...")
                else:
                    on_progress(f"执行 {len(tool_names)} 个工具...")
            t2 = time.monotonic()
            results = await self._execute_tool_calls(message.tool_calls)
            tool_time = time.monotonic() - t2

            tools_this_round = [
                {"name": tc.function.name, "args": tc.function.arguments}
                for tc in message.tool_calls
            ]
            timings.append({
                "round": round_num,
                "llm_time": llm_time,
                "tool_time": tool_time,
                "tools": tools_this_round,
            })
            for tc_id, content in results:
                self._history.add({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "content": content,
                })

        # 轮数耗尽，最后调一次 LLM 基于已有数据给出最佳回答
        t_final = time.monotonic()
        try:
            messages = self._history.get_messages()
            messages.insert(0, {"role": "system", "content": "已达到工具调用上限。请基于已获取的所有数据，尽最大努力回答用户的问题。如果数据不完整，如实说明哪些信息缺失，不要编造数据。"})
            system_prompt = self._system_prompt
            instructions = self._skill_registry.get_active_instructions()
            if instructions:
                system_prompt = system_prompt + "\n\n## 已激活技能\n" + instructions
            response = await self._llm_client.chat(
                messages=messages,
                tools=[],
                system_prompt=system_prompt,
            )
            if response.usage:
                usage["prompt"] += response.usage.prompt_tokens
                usage["completion"] += response.usage.completion_tokens
            answer = (response.choices[0].message.content or "").strip()
            self._history.add({"role": "assistant", "content": answer})
        except Exception:
            logger.warning("轮数耗尽后 LLM 总结调用失败", exc_info=True)
            answer = "已达到最大工具调用轮数，操作未完成。"
        timings.append({"round": -1, "llm_time": time.monotonic() - t_final, "tool_time": 0, "tools": []})
        self._last_usage = usage
        self._last_tool_counts = tool_counts or None
        self._last_timings = timings
        return answer

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
