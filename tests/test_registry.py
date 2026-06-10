import pytest
from nimo.tools.registry import ToolRegistry, ToolResult, register_tool


@pytest.fixture(autouse=True)
def reset_registry():
    ToolRegistry.get_instance().reset()
    yield


def get_reg():
    return ToolRegistry.get_instance()


def test_register_and_list_tools():
    @register_tool(
        name="test_echo",
        description="Echo back the message",
        parameters={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "要回显的消息"},
            },
            "required": ["message"],
        },
    )
    async def test_echo(message: str) -> ToolResult:
        return ToolResult(success=True, data={"echo": message})

    definitions = get_reg().build_tool_definitions()
    assert len(definitions) == 1
    tool_def = definitions[0]
    assert tool_def["type"] == "function"
    assert tool_def["function"]["name"] == "test_echo"


@pytest.mark.asyncio
async def test_execute_registered_tool():
    @register_tool(
        name="calc",
        description="计算两个数之和",
        parameters={
            "type": "object",
            "properties": {
                "a": {"type": "number"},
                "b": {"type": "number"},
            },
            "required": ["a", "b"],
        },
    )
    async def calc(a: float, b: float) -> ToolResult:
        return ToolResult(success=True, data={"result": a + b})

    result = await get_reg().execute("calc", {"a": 1, "b": 2})
    assert result.success is True
    assert result.data["result"] == 3


@pytest.mark.asyncio
async def test_execute_unknown_tool():
    result = await get_reg().execute("nonexistent", {})
    assert result.success is False
    assert "未找到工具" in result.error


def test_build_definitions_empty():
    # autouse fixture already reset, so registry is empty
    assert get_reg().build_tool_definitions() == []
