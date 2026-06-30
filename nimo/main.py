import argparse
import asyncio
import logging
import os
import threading
import time
import warnings

warnings.filterwarnings("ignore", message=".*Pydantic V1.*", module="openai.*")

from openai import AuthenticationError

from pathlib import Path

from nimo.config import Config, load_config
from nimo.agent import Agent
from nimo.skill.registry import SkillRegistry
from nimo.skill.installer import Installer
from nimo.display import print_welcome, print_response_box, CYAN, GRAY_MUTED, ORANGE, ORANGE_DEEP, RED_ERROR, GREEN_SUCCESS, YELLOW_WARN, RESET
from nimo.engine import ExecutionEngine
from nimo.tools.schedule import Scheduler

# Import to trigger tool auto-discovery and registration
import nimo.tools  # noqa: F401
from nimo.tools import ToolRegistry

# prompt_toolkit 输入历史（跨平台，方向键正常）
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.styles import Style as PTStyle

_HISTFILE = os.path.join(os.path.expanduser("~"), ".nimo_history")
_pt_session: PromptSession | None = None

# 用户输入文字样式（暖橙 #F28A38，模拟旧 input() 中 ANSI 颜色蔓延效果）
_INPUT_STYLE = PTStyle.from_dict({"": "fg:#f28a38"})


def _get_pt_session() -> PromptSession:
    global _pt_session
    if _pt_session is None:
        _pt_session = PromptSession(history=FileHistory(_HISTFILE))
    return _pt_session


logger = logging.getLogger(__name__)



class _Spinner:
    """后台线程旋转动画 + 已等待秒数。"""

    _FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self):
        self._stop = threading.Event()
        self._msg = ""
        self._t0 = 0.0

    def _spin(self):
        i = 0
        while not self._stop.is_set():
            elapsed = time.monotonic() - self._t0
            print(f"\033[2K\r{GRAY_MUTED}{self._FRAMES[i % 10]} {self._msg} ({elapsed:.0f}s){RESET}",
                  end="", flush=True)
            i += 1
            self._stop.wait(0.1)

    def start(self, msg: str):
        self._stop.clear()
        self._msg = msg
        self._t0 = time.monotonic()
        threading.Thread(target=self._spin, daemon=True).start()

    def update(self, msg: str):
        self._msg = msg
        self._t0 = time.monotonic()

    def stop(self):
        self._stop.set()
        print("\033[2K\r", end="", flush=True)


import json


def _format_chain(agent: Agent) -> str:
    """从消息历史中提取上一轮工具调用链并格式化输出，含每轮耗时。"""
    timings = agent._last_timings
    msgs = agent._history._messages

    if not msgs:
        return f"{GRAY_MUTED}暂无对话历史。{RESET}"

    last_user_idx = None
    for i in range(len(msgs) - 1, -1, -1):
        if msgs[i]["role"] == "user":
            last_user_idx = i
            break
    if last_user_idx is None:
        return f"{GRAY_MUTED}暂无用户消息。{RESET}"

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
        return f"{GRAY_MUTED}上一轮对话没有工具调用。{RESET}"

    lines = [f"\n{CYAN}◆ 工具调用链{RESET}\n"]

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
            lines.append(f"  {CYAN}{label}{RESET}  LLM {GRAY_MUTED}{llm_t:.1f}s{RESET}")
            continue

        parallel_hint = f" {GRAY_MUTED}（{n} 并行）{RESET}" if n > 1 else ""
        lines.append(f"  {CYAN}第{r}轮{RESET}  LLM {GRAY_MUTED}{llm_t:.1f}s{RESET} | 工具 {GRAY_MUTED}{tool_t:.1f}s{RESET}{parallel_hint}")

        for j in range(n):
            if result_idx >= len(results):
                break
            rr = results[result_idx]
            call_str = _format_tool_call(rr["name"], rr["args"])
            lines.append(f"    {call_str}  {GRAY_MUTED}→  {rr['result']}{RESET}")
            result_idx += 1

        lines.append("")

    total = total_llm + total_tool
    lines.append(f"  {GRAY_MUTED}{'─' * 28}{RESET}")
    lines.append(f"  LLM {GRAY_MUTED}{total_llm:.1f}s{RESET} | 工具 {GRAY_MUTED}{total_tool:.1f}s{RESET} | 总计 {GRAY_MUTED}{total:.1f}s{RESET}")

    return "\n".join(lines)


def _format_tool_call(name: str, args) -> str:
    """将工具调用的参数格式化为可读的命令行形式。"""
    if not isinstance(args, dict):
        return f"{name} {str(args)[:60]}"
    # 意图工具：{action, owner, workspace_id, ...}
    if "action" in args:
        parts = [name, args["action"]]
        for key in ("owner", "workspace_id", "entity_id", "project", "name", "date"):
            if key in args and args[key]:
                parts.append(f"--{key.replace('_', '-')} {args[key]}")
        if "extra" in args and args["extra"]:
            extra = args["extra"]
            if isinstance(extra, dict):
                for k, v in extra.items():
                    parts.append(f"--{k.replace('_', '-')} {v}")
        return " ".join(parts)
    # 旧透传工具：{args: [subcmd, op, --flag, val, ...]}
    argv = args.get("args", [])
    if not argv:
        return name
    cmd = " ".join(argv[:2])
    params = []
    i = 2
    while i < len(argv):
        if argv[i].startswith("--"):
            key = argv[i][2:]
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                params.append(f"--{key} {argv[i + 1]}")
                i += 2
            else:
                params.append(f"--{key}")
                i += 1
        else:
            params.append(argv[i])
            i += 1
    if params:
        return f"{name} {cmd} {' '.join(params)}"
    return f"{name} {cmd}"


async def build_agent(config: Config) -> Agent:
    ExecutionEngine.get_instance().init(config)
    await ToolRegistry.get_instance().init_all(config)
    return Agent(config)


_scheduler: Scheduler | None = None


def _show_notification(n: "Notification") -> None:
    """直接展示通知结果，无需用户确认。"""
    ts = n.completed_at[:16].replace("T", " ")
    print(f"\n{ORANGE_DEEP}[!] [{ts}] 定时任务 '{n.task_id}' 完成{RESET}")
    print_response_box(n.full_text)
    print()


async def _input_with_poll(prompt_str: str, sched: Scheduler | None, poll_sec: int = 2) -> str | None:
    """在后台线程中运行 prompt_toolkit 输入，主线程轮询调度通知。
    通知在输入完成后展示，避免破坏 prompt_toolkit 的终端渲染。"""
    result: list[str | None] = []
    ready = threading.Event()

    def _read() -> None:
        try:
            result.append(_get_pt_session().prompt(ANSI(prompt_str), style=_INPUT_STYLE))
        except (EOFError, KeyboardInterrupt):
            result.append(None)
        ready.set()

    thread = threading.Thread(target=_read, daemon=True)
    thread.start()

    pending_notifications: list = []
    loop = asyncio.get_running_loop()
    while not ready.is_set():
        await loop.run_in_executor(None, ready.wait, poll_sec)
        if sched and not ready.is_set():
            for n in sched.pop_notifications():
                pending_notifications.append(n)

    thread.join()

    for n in pending_notifications:
        _show_notification(n)

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

    print_welcome(model=config.llm.model, cwd=os.getcwd(), version="1.0.0")
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
            print()
            continue
        skills_dir = str(Path.home() / ".nimo" / "skills")
        if user_input.strip().startswith("skill "):
            parts = user_input.strip().split(maxsplit=2)
            if len(parts) < 2:
                print("用法：skill install <url> | skill list | skill uninstall <name>")
                continue
            cmd = parts[1]
            if cmd == "install" and len(parts) >= 3:
                url = parts[2]
                installer = Installer(skills_dir)
                try:
                    result = installer.install(url)
                    print(result)
                    SkillRegistry.get_instance().discover(skills_dir)
                    agent.reload_system_prompt()
                except RuntimeError as e:
                    print(str(e))
                continue
            elif cmd == "list":
                installer = Installer(skills_dir)
                skills = installer.list_installed()
                if skills:
                    for name, path in skills:
                        print(f"  {name}  ({path})")
                else:
                    print("暂无已安装的技能。\n安装：skill install <github-url>")
                continue
            elif cmd == "uninstall" and len(parts) >= 3:
                name = parts[2]
                installer = Installer(skills_dir)
                result = installer.uninstall(name)
                print(result)
                if "已卸载" in result:
                    SkillRegistry.get_instance().discover(skills_dir)
                    agent.reload_system_prompt()
                continue
            else:
                print("用法：skill install <url> | skill list | skill uninstall <name>")
                continue
        if user_input.strip() == "/help":
            print(f"""
{CYAN}◆ 命令{RESET}
  {CYAN}/help{RESET}          查看帮助
  {CYAN}/chain{RESET}         查看上一轮工具调用链
  {CYAN}/clear{RESET}         清除当前对话历史
  {CYAN}/clear-profile{RESET} 清除长期用户档案
  {CYAN}/exit{RESET}          退出程序

{CYAN}◆ 试试这样说{RESET}
  {GRAY_MUTED}·{RESET} 帮我看看有哪些项目
  {GRAY_MUTED}·{RESET} 创建一个需求：修复登录页bug
  {GRAY_MUTED}·{RESET} 当前有哪些活跃的迭代
  {GRAY_MUTED}·{RESET} 给任务1001填4小时工时
  {GRAY_MUTED}·{RESET} 看看今天的SVN提交记录
  {GRAY_MUTED}·{RESET} 最近谁改过 main.c？
  {GRAY_MUTED}·{RESET} 更新工作副本到最新版本
  {GRAY_MUTED}·{RESET} 每天早上九点汇总昨日bug修复情况

  {GRAY_MUTED}·{RESET} skill install <url>  从 GitHub 安装技能
  {GRAY_MUTED}·{RESET} skill list           查看已安装技能
  {GRAY_MUTED}·{RESET} skill uninstall <名> 卸载技能

{GRAY_MUTED}所有操作通过自然语言驱动，直接输入即可。{RESET}""")
            print()
            continue
        if not user_input.strip():
            continue
        try:
            sp = _Spinner()
            sp.start("分析中...")
            try:
                response = await agent.run(user_input, on_progress=sp.update)
            finally:
                sp.stop()
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
            print(f"\n{RED_ERROR}API Key 无效，请检查 config.yaml 中的 api_key 是否正确{RESET}")
        except Exception:
            logging.getLogger(__name__).exception("未预期的错误")
            print(f"\n{RED_ERROR}发生错误，请重试{RESET}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n再见！")
