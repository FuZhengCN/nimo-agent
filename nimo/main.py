import argparse
import asyncio
import logging
import os
import threading
import warnings

warnings.filterwarnings("ignore", message=".*Pydantic V1.*", module="openai.*")

from openai import AuthenticationError

from nimo.config import Config, load_config
from nimo.agent import Agent
from nimo.display import print_welcome, print_response_box
from nimo.tools.schedule import Scheduler

# Import to trigger tool auto-discovery and registration
import nimo.tools  # noqa: F401
from nimo.tools import ToolRegistry

logger = logging.getLogger(__name__)

ORANGE = "\033[38;2;242;138;56m"
RESET = "\033[0m"


import json


def _format_chain(agent: Agent) -> str:
    """从消息历史中提取上一轮工具调用链并格式化输出，含每轮耗时。"""
    timings = agent._last_timings
    msgs = agent._history._messages

    if not msgs:
        return "暂无对话历史。"

    last_user_idx = None
    for i in range(len(msgs) - 1, -1, -1):
        if msgs[i]["role"] == "user":
            last_user_idx = i
            break
    if last_user_idx is None:
        return "暂无用户消息。"

    # 收集 tool_call_id → 工具名和参数
    tc_map: dict[str, dict] = {}
    for i in range(last_user_idx, len(msgs)):
        m = msgs[i]
        if m["role"] == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                try:
                    args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, TypeError):
                    args = tc["function"]["arguments"]
                tc_map[tc["id"]] = {"name": tc["function"]["name"], "args": args}

    # 收集 tool 结果
    results: list[dict] = []
    for i in range(last_user_idx, len(msgs)):
        m = msgs[i]
        if m["role"] != "tool":
            continue
        tc_id = m.get("tool_call_id", "")
        info = tc_map.get(tc_id, {"name": "未知工具", "args": ""})
        result_text = "失败"
        try:
            data = json.loads(m["content"])
            if data.get("success"):
                raw = data.get("data", "")
                if isinstance(raw, str):
                    try:
                        parsed = json.loads(raw)
                        if isinstance(parsed, list):
                            result_text = f"{len(parsed)} 条" if len(parsed) > 0 else "无记录"
                        elif isinstance(parsed, dict):
                            result_text = f"{len(parsed)} 字段"
                        else:
                            result_text = f"{len(raw)} 字符"
                    except (json.JSONDecodeError, TypeError):
                        result_text = f"{len(raw)} 字符"
                elif isinstance(raw, list):
                    result_text = f"{len(raw)} 条" if len(raw) > 0 else "无记录"
                elif isinstance(raw, dict):
                    result_text = f"{len(raw)} 字段"
                else:
                    result_text = "成功"
            else:
                result_text = data.get("error", "失败")
        except (json.JSONDecodeError, TypeError):
            pass
        results.append({
            "name": info["name"],
            "args": info["args"],
            "result": result_text,
        })

    if not results:
        return "上一轮对话没有工具调用。"

    lines = ["\n🔗 工具调用链\n"]

    result_idx = 0
    total_llm = 0.0
    total_tool = 0.0
    for t in timings:
        r = t["round"]
        llm_t = t["llm_time"]
        tool_t = t["tool_time"]
        total_llm += llm_t
        total_tool += tool_t
        n = len(t["tools"])

        if n == 0:
            label = "最终回答" if r == -1 else f"第{r}轮"
            lines.append(f"  {label}  LLM {llm_t:.1f}s")
            continue

        parallel_hint = f"（{n} 并行）" if n > 1 else ""
        lines.append(f"  第{r}轮  LLM {llm_t:.1f}s | 工具 {tool_t:.1f}s{parallel_hint}")

        for j in range(n):
            if result_idx >= len(results):
                break
            rr = results[result_idx]
            call_str = _format_tapd_call(rr["args"])
            lines.append(f"    {call_str}  →  {rr['result']}")
            result_idx += 1

        lines.append("")

    total = total_llm + total_tool
    lines.append(f"  {'─' * 28}")
    lines.append(f"  LLM {total_llm:.1f}s | 工具 {total_tool:.1f}s | 总计 {total:.1f}s")

    return "\n".join(lines)


def _format_tapd_call(args) -> str:
    """将 tapd_cli 参数格式化为可读的命令行形式。"""
    if not isinstance(args, dict):
        return str(args)[:60]
    argv = args.get("args", [])
    if not argv:
        return "tapd_cli"
    cmd = " ".join(argv[:2])  # e.g. "workspace list", "timesheet list"
    # 提取关键参数
    params = []
    i = 2
    while i < len(argv):
        if argv[i].startswith("--"):
            key = argv[i][2:]  # 去掉 -- 前缀
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                val = argv[i + 1]
                params.append(f"--{key} {val}")
                i += 2
            else:
                params.append(f"--{key}")
                i += 1
        else:
            params.append(argv[i])
            i += 1
    if params:
        return f"{cmd} {' '.join(params)}"
    return cmd


async def build_agent(config: Config) -> Agent:
    await ToolRegistry.get_instance().init_all(config)
    return Agent(config)


_scheduler: Scheduler | None = None


def _show_notification(n: "Notification") -> None:
    """直接展示通知结果，无需用户确认。"""
    ts = n.completed_at[:16].replace("T", " ")
    print(f"\n{ORANGE}[!] [{ts}] 定时任务 '{n.task_id}' 完成{RESET}")
    print_response_box(n.full_text)
    print()


async def _input_with_poll(prompt: str, sched: Scheduler | None, poll_sec: int = 2) -> str | None:
    """在等待用户输入期间定期检查调度通知。input() 在线程中执行，不阻塞事件循环。"""
    result: list[str | None] = []
    ready = threading.Event()

    def _read() -> None:
        try:
            result.append(input(prompt))
        except (EOFError, KeyboardInterrupt):
            result.append(None)
        ready.set()

    thread = threading.Thread(target=_read, daemon=True)
    thread.start()

    loop = asyncio.get_running_loop()
    while not ready.is_set():
        await loop.run_in_executor(None, ready.wait, poll_sec)
        if sched and not ready.is_set():
            for n in sched.pop_notifications():
                _show_notification(n)
                # 重新打印提示符
                print(f"{prompt}", end="", flush=True)

    thread.join()
    return result[0]


async def main() -> None:
    parser = argparse.ArgumentParser()
    args, _ = parser.parse_known_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    config = load_config()
    agent = await build_agent(config)

    # 启动后台调度器（新 Agent 实例，独立 history/profile）
    global _scheduler
    _scheduler = Scheduler(lambda: Agent(config))
    asyncio.create_task(_scheduler.start())

    print_welcome(model=config.llm.model, cwd=os.getcwd(), version="0.1.0")
    prompt = f"{ORANGE}❯ "
    while True:
        try:
            user_input = await _input_with_poll(prompt, _scheduler)
            if user_input is None:
                agent.save_history()
                print("\n再见！")
                break
        except (EOFError, KeyboardInterrupt):
            agent.save_history()
            print("\n再见！")
            break
        if user_input.strip() == "/exit":
            agent.save_history()
            print("再见！")
            break
        if user_input.strip() == "/clear":
            agent.clear_history()
            print("历史已清除")
            continue
        if user_input.strip() == "/clear-profile":
            agent.clear_profile()
            print("用户档案已清除")
            continue
        if user_input.strip() == "/chain":
            print(_format_chain(agent))
            continue
        if user_input.strip() == "/help":
            print("""
可用命令：
  /help          查看帮助
  /chain         查看上一轮工具调用链
  /clear         清除当前对话历史
  /clear-profile 清除长期用户档案
  /exit          退出程序

试试这样说：
  · 帮我看看有哪些项目
  · 给任务1001填4小时工时
  · 5分钟后检查我的待办任务

所有操作通过自然语言驱动，直接输入即可。""")
            continue
        if not user_input.strip():
            continue
        try:
            def _progress(msg: str) -> None:
                print(f"\033[90m⏳ {msg}\033[0m\033[K", end="\r")

            response = await agent.run(user_input, on_progress=_progress)
            print(" " * 40, end="\r")
            usage = agent.last_usage
            token_str = None
            if usage:
                def _fmt(n: int) -> str:
                    return f"{n/1000:.1f}k" if n >= 1000 else str(n)
                token_str = f"P:{_fmt(usage['prompt'])} C:{_fmt(usage['completion'])}"
            print_response_box(response, token_summary=token_str, tool_counts=agent.last_tool_counts)
            print()
        except KeyboardInterrupt:
            agent.save_history()
            print("\n已取消，输入 /exit 退出")
        except AuthenticationError:
            logger.exception("API Key 认证失败")
            print(f"\n\033[91mAPI Key 无效，请检查 config.yaml 中的 api_key 是否正确\033[0m")
        except Exception:
            logging.getLogger(__name__).exception("未预期的错误")
            print(f"\n\033[91m发生错误，请重试\033[0m")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n再见！")
