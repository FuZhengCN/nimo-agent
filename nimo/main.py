import asyncio
import logging
import os
from nimo.config import load_config
from nimo.agent import Agent
from nimo.welcome import print_welcome

# Import to trigger tool registration
import nimo.tools.tapd  # noqa: F401
from nimo.tools.tapd import init_tapd

logger = logging.getLogger(__name__)


def build_agent(config) -> Agent:
    init_tapd(config)
    return Agent(config)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    config = load_config()
    agent = build_agent(config)
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
            response = await agent.run(user_input)
            print(response)
            print()
        except KeyboardInterrupt:
            print("\n已取消，输入 /exit 退出")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n再见！")
