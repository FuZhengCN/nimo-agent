import asyncio
import logging
from nimo.config import load_config
from nimo.agent import Agent

# Import to trigger tool registration
import nimo.tools.tapd  # noqa: F401
from nimo.tools.tapd import init_tapd

logger = logging.getLogger(__name__)


def build_agent(config_path: str = "config.yaml") -> Agent:
    config = load_config(config_path)
    init_tapd(config)
    return Agent(config)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    agent = build_agent()
    print("Nimo 就绪，输入 /exit 退出")
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
        response = await agent.run(user_input)
        print(response)
        print()


if __name__ == "__main__":
    asyncio.run(main())
