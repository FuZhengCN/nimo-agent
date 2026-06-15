import json
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from nimo.acp_server import AcpServer


@pytest.fixture
def mock_agent():
    agent = MagicMock()
    agent.run = AsyncMock(return_value="你好！有什么可以帮你的？")
    return agent


@pytest.fixture
def server(mock_agent):
    return AcpServer(mock_agent)


def test_handle_initialize(server):
    result = server._handle_initialize(1, {"protocolVersion": 1})

    assert result["jsonrpc"] == "2.0"
    assert result["id"] == 1
    assert result["result"]["protocolVersion"] == 1
    assert result["result"]["agentInfo"]["name"] == "nimo"
    assert result["result"]["agentInfo"]["version"] == "0.1.0"
    assert result["result"]["agentCapabilities"]["loadSession"] is False
    assert result["result"]["agentCapabilities"]["promptCapabilities"]["image"] is False
    assert result["result"]["agentCapabilities"]["promptCapabilities"]["audio"] is False
    assert result["result"]["authMethods"] == []


def test_handle_session_new(server):
    result = server._handle_session_new(2, {"cwd": "/path/to/project"})

    assert result["jsonrpc"] == "2.0"
    assert result["id"] == 2
    sid = result["result"]["sessionId"]
    assert isinstance(sid, str) and len(sid) > 0
    assert server._sessions[sid] == "/path/to/project"


@pytest.mark.asyncio
async def test_handle_session_prompt_success(server):
    sid = str(uuid.uuid4())
    server._sessions[sid] = "/test"

    result = await server._handle_session_prompt(3, {
        "sessionId": sid,
        "prompt": [{"type": "text", "text": "帮我看看有哪些项目"}],
    })

    assert result["jsonrpc"] == "2.0"
    assert result["id"] == 3
    assert result["result"]["stopReason"] == "end_turn"
    assert result["result"]["content"][0]["type"] == "text"
    assert result["result"]["content"][0]["text"] == "你好！有什么可以帮你的？"
    server._agent.run.assert_called_once_with("帮我看看有哪些项目")


@pytest.mark.asyncio
async def test_handle_session_prompt_multiple_text_blocks(server):
    sid = str(uuid.uuid4())
    server._sessions[sid] = "/test"

    await server._handle_session_prompt(4, {
        "sessionId": sid,
        "prompt": [
            {"type": "text", "text": "第一部分 "},
            {"type": "text", "text": "第二部分"},
        ],
    })

    server._agent.run.assert_called_once_with("第一部分 第二部分")


@pytest.mark.asyncio
async def test_handle_session_prompt_invalid_session(server):
    result = await server._handle_session_prompt(5, {
        "sessionId": "nonexistent-id",
        "prompt": [{"type": "text", "text": "test"}],
    })

    assert result["jsonrpc"] == "2.0"
    assert result["id"] == 5
    assert result["error"]["code"] == -32602
    assert "Invalid session" in result["error"]["message"]
    assert "result" not in result


@pytest.mark.asyncio
async def test_dispatch_unknown_method(server):
    result = await server._dispatch({
        "jsonrpc": "2.0",
        "id": 6,
        "method": "some/unknown_method",
        "params": {},
    })

    assert result["error"]["code"] == -32601
    assert "Method not found" in result["error"]["message"]


@pytest.mark.asyncio
async def test_process_buffer_complete_message(server):
    msg = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    body = json.dumps(msg, ensure_ascii=False)
    header = f"Content-Length: {len(body.encode('utf-8'))}\r\n\r\n"
    wire = (header + body).encode('utf-8')

    with patch.object(server, '_write_message') as mock_write:
        remainder = await server._process_buffer(wire)
        assert remainder == b""
        mock_write.assert_called_once()
        written = mock_write.call_args[0][0]
        assert written["result"]["agentInfo"]["name"] == "nimo"


@pytest.mark.asyncio
async def test_process_buffer_partial_header(server):
    wire = b"Content-Leng"
    remaining = await server._process_buffer(wire)
    assert remaining == wire


@pytest.mark.asyncio
async def test_process_buffer_partial_body(server):
    msg = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    body = json.dumps(msg, ensure_ascii=False)
    header = f"Content-Length: {len(body.encode('utf-8'))}\r\n\r\n"
    half = (header + body[:5]).encode('utf-8')

    with patch.object(server, '_write_message'):
        remaining = await server._process_buffer(half)
        assert remaining == half


@pytest.mark.asyncio
async def test_process_buffer_two_messages(server):
    msg1 = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    msg2 = {"jsonrpc": "2.0", "id": 2, "method": "session/new", "params": {"cwd": "/t"}}
    body1 = json.dumps(msg1, ensure_ascii=False)
    body2 = json.dumps(msg2, ensure_ascii=False)
    header1 = f"Content-Length: {len(body1.encode('utf-8'))}\r\n\r\n"
    header2 = f"Content-Length: {len(body2.encode('utf-8'))}\r\n\r\n"
    wire = (header1 + body1 + header2 + body2).encode('utf-8')

    with patch.object(server, '_write_message') as mock_write:
        remainder = await server._process_buffer(wire)
        assert remainder == b""
        assert mock_write.call_count == 2


@pytest.mark.asyncio
async def test_handle_session_prompt_empty_blocks(server):
    sid = str(uuid.uuid4())
    server._sessions[sid] = "/test"

    await server._handle_session_prompt(7, {
        "sessionId": sid,
        "prompt": [],
    })

    server._agent.run.assert_called_once_with(" ")


@pytest.mark.asyncio
async def test_dispatch_prompt_agent_exception(server):
    sid = str(uuid.uuid4())
    server._sessions[sid] = "/test"
    server._agent.run = AsyncMock(side_effect=RuntimeError("模拟异常"))

    result = await server._dispatch({
        "jsonrpc": "2.0",
        "id": 8,
        "method": "session/prompt",
        "params": {
            "sessionId": sid,
            "prompt": [{"type": "text", "text": "test"}],
        },
    })

    assert result["error"]["code"] == -32603


def test_handle_session_new_without_cwd(server):
    result = server._handle_session_new(9, {})

    sid = result["result"]["sessionId"]
    assert server._sessions[sid] == ""


@pytest.mark.asyncio
async def test_process_buffer_parse_error(server):
    body = "not valid json{{{{"
    header = f"Content-Length: {len(body.encode('utf-8'))}\r\n\r\n"
    wire = (header + body).encode('utf-8')

    with patch.object(server, '_write_message') as mock_write:
        remainder = await server._process_buffer(wire)
        assert remainder == b""
        mock_write.assert_called_once()
        written = mock_write.call_args[0][0]
        assert written["error"]["code"] == -32700
