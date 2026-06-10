import asyncio
import logging
import os
from nimo.config import Config, load_config
from nimo.agent import Agent
from nimo.welcome import print_welcome, print_response_box

# Import to trigger tool registration
import nimo.tools.tapd  # noqa: F401
from nimo.tools.tapd import init_tapd

logger = logging.getLogger(__name__)


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
            user_input = input("> ")
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break
        if user_input.strip() == "/exit":
            print("再见！")
            break
        if not user_input.strip():
            continue
        try:
            print("\033[90m⏳ 思考中...\033[0m", end="\r")
            response = await agent.run(user_input)
            print(" " * 20, end="\r")
            print_response_box(response)
            print()
        except KeyboardInterrupt:
            print("\n已取消，输入 /exit 退出")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n再见！")
