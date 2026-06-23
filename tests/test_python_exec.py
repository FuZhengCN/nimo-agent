"""python_exec 工具测试。"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from nimo.tools.python_exec import python_exec


async def _mock_proc(returncode=0, stdout=b"hello", stderr=b""):
    proc = AsyncMock()
    proc.returncode = returncode
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return proc


@pytest.mark.asyncio
async def test_basic_execution():
    proc = await _mock_proc(0, b"42")
    with patch("asyncio.create_subprocess_exec", return_value=proc):
        r = await python_exec("print(42)")
    assert r.success
    assert r.data == "42"


@pytest.mark.asyncio
async def test_stderr_as_error():
    proc = await _mock_proc(1, stdout=b"", stderr=b"NameError: foo")
    with patch("asyncio.create_subprocess_exec", return_value=proc):
        r = await python_exec("foo()")
    assert not r.success
    assert "NameError" in r.error


@pytest.mark.asyncio
async def test_timeout():
    with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
        r = await python_exec("while True: pass")
    assert not r.success
    assert "超时" in r.error


@pytest.mark.asyncio
async def test_no_output():
    proc = await _mock_proc(0, b"")
    with patch("asyncio.create_subprocess_exec", return_value=proc):
        r = await python_exec("x = 1")
    assert r.success
    assert "无输出" in r.data


def test_tool_registered():
    from nimo.tools.registry import ToolRegistry
    tool_names = [name for name, _desc in ToolRegistry.get_instance().list_tools()]
    assert "python_exec" in tool_names

    definitions = ToolRegistry.get_instance().build_tool_definitions()
    py_def = next(d for d in definitions if d["function"]["name"] == "python_exec")
    assert "code" in py_def["function"]["parameters"]["properties"]
    assert py_def["function"]["parameters"]["required"] == ["code"]
