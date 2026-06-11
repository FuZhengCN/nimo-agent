import asyncio
import logging
import os
import warnings

warnings.filterwarnings("ignore", message=".*Pydantic V1.*", module="openai.*")

from nimo.config import Config, load_config
from nimo.agent import Agent
from nimo.welcome import print_welcome, print_response_box

# Import to trigger tool registration
import nimo.tools.tapd  # noqa: F401
from nimo.tools.tapd import init_tapd

logger = logging.getLogger(__name__)

ORANGE = "\033[38;2;242;138;56m"
RESET = "\033[0m"


async def build_agent(config: Config) -> Agent:
    await init_tapd(config)
    return Agent(config)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    config = load_config()
    agent = await build_agent(config)
    print_welcome(model=config.llm.model, cwd=os.getcwd(), version="0.1.0")
    while True:
        try:
            user_input = input(f"{ORANGE}❯ ")
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
        if user_input.strip() == "/help":
            print("""
可用命令：
  /help          查看帮助
  /clear         清除当前对话历史
  /clear-profile 清除长期用户档案
  /exit          退出程序

用法示例：
  · 帮我看看有哪些项目
  · 列出项目755的任务
  · 创建一个需求：修复登录bug
  · 给任务1001填4小时工时
  · 当前有哪些活跃的迭代？

所有操作通过自然语言驱动，直接输入即可。""")
            continue
        if not user_input.strip():
            continue
        try:
            print("\033[90m⏳ 思考中...\033[0m", end="\r")
            response = await agent.run(user_input)
            print(" " * 20, end="\r")
            usage = agent.last_usage
            token_str = None
            if usage:
                def _fmt(n: int) -> str:
                    return f"{n/1000:.1f}k" if n >= 1000 else str(n)
                token_str = f"P:{_fmt(usage['prompt'])} C:{_fmt(usage['completion'])}"
            print_response_box(response, token_summary=token_str)
            print()
        except KeyboardInterrupt:
            agent.save_history()
            print("\n已取消，输入 /exit 退出")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n再见！")
