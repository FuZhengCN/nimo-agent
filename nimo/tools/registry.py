import logging
from dataclasses import dataclass
from collections.abc import Callable, Awaitable
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    success: bool
    data: Any = None
    error: str | None = None


@dataclass
class _ToolDef:
    name: str
    description: str
    parameters: dict
    func: Callable[..., Awaitable[ToolResult]]


class ToolRegistry:
    _instance: "ToolRegistry | None" = None

    def __init__(self):
        self._tools: dict[str, _ToolDef] = {}

    @classmethod
    def get_instance(cls) -> "ToolRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    def register(
        self,
        name: str,
        description: str,
        parameters: dict,
        func: Callable[..., Awaitable[ToolResult]],
    ) -> None:
        self._tools[name] = _ToolDef(
            name=name,
            description=description,
            parameters=parameters,
            func=func,
        )

    def build_tool_definitions(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    async def execute(self, name: str, arguments: dict) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(success=False, error=f"未找到工具：{name}")
        try:
            return await tool.func(**arguments)
        except Exception as e:
            logger.exception(f"工具 {name} 执行异常")
            return ToolResult(success=False, error=str(e))


def register_tool(name: str, description: str, parameters: dict):
    def decorator(func: Callable[..., Awaitable[ToolResult]]):
        ToolRegistry.get_instance().register(name, description, parameters, func)
        return func
    return decorator
