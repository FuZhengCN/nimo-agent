# ACP 协议接入实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 Nimo 添加 `--acp` 启动模式，实现 Agent Client Protocol 最小握手层，使其能在 JetBrains IDE 中注册为自定义 Agent。

**Architecture:** 新增 `nimo/acp_server.py` 处理 JSON-RPC 2.0 over stdin/stdout 消息帧和三个必需方法（initialize / session/new / session/prompt）。`nimo/main.py` 中加 `--acp` 参数检测，跳过 CLI 循环，改为启动 AcpServer。零外部依赖，仅用 asyncio + json + uuid + re。

**Tech Stack:** Python 3.10+, asyncio, sys.stdin/stdout buffer I/O, JSON-RPC 2.0

---

## 文件结构

| 文件 | 角色 |
|------|------|
| `nimo/acp_server.py` | 新建。ACP JSON-RPC 服务器：消息帧解析、方法分发、三个 handler |
| `nimo/main.py` | 修改。加 `--acp` 参数分支，约 10 行 |
| `tests/test_acp_server.py` | 新建。单元测试：handler、dispatch 路由、buffer 解析、错误路径 |

---

### Task 1: 编写 AcpServer 单元测试

**Files:**
- Create: `tests/test_acp_server.py`

- [ ] **Step 1: 搭建测试骨架**

```python
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
```

- [ ] **Step 2: 编写 initialize handler 测试**

```python
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
```

- [ ] **Step 3: 编写 session/new handler 测试**

```python
def test_handle_session_new(server):
    result = server._handle_session_new(2, {"cwd": "/path/to/project"})

    assert result["jsonrpc"] == "2.0"
    assert result["id"] == 2
    sid = result["result"]["sessionId"]
    assert isinstance(sid, str) and len(sid) > 0
    assert server._sessions[sid] == "/path/to/project"
```

- [ ] **Step 4: 编写 session/prompt handler 成功路径测试**

```python
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
```

- [ ] **Step 5: 编写 session/prompt 多段文本拼接测试**

```python
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
```

- [ ] **Step 6: 编写 session/prompt 无效 sessionId 测试**

```python
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
```

- [ ] **Step 7: 编写 dispatch 未知 method 测试**

```python
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
```

- [ ] **Step 8: 编写 buffer 解析测试**

```python
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
        written = json.loads(mock_write.call_args[0][0])
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
async def test_process_buffer_parse_error(server):
    body = "not valid json{{{{"
    header = f"Content-Length: {len(body.encode('utf-8'))}\r\n\r\n"
    wire = (header + body).encode('utf-8')

    with patch.object(server, '_write_message') as mock_write:
        remainder = await server._process_buffer(wire)
        assert remainder == b""
        mock_write.assert_called_once()
        written = json.loads(mock_write.call_args[0][0])
        assert written["error"]["code"] == -32700
```

- [ ] **Step 9: 运行测试确认全部失败**

```bash
pytest tests/test_acp_server.py -v
```

预期：全部 FAIL（`ModuleNotFoundError: No module named 'nimo.acp_server'`）

---

### Task 2: 实现 AcpServer

**Files:**
- Create: `nimo/acp_server.py`

- [ ] **Step 1: 创建文件骨架与导入**

```python
import asyncio
import json
import logging
import re
import sys
import uuid

logger = logging.getLogger(__name__)

# Content-Length: <number>\r\n\r\n
_HEADER_RE = re.compile(rb"Content-Length:\s*(\d+)\s*\r\n\r\n", re.IGNORECASE)


class AcpServer:
    def __init__(self, agent):
        self._agent = agent
        self._sessions: dict[str, str] = {}

    async def run(self) -> None:
        """主循环：从 stdin 读取 JSON-RPC 消息帧，分发处理，向 stdout 写入响应。"""
        print("Nimo ACP server starting...", file=sys.stderr)
        loop = asyncio.get_running_loop()
        buffer = b""
        while True:
            chunk = await loop.run_in_executor(None, sys.stdin.buffer.read, 4096)
            if not chunk:
                self._agent.save_history()
                break
            buffer += chunk
            buffer = await self._process_buffer(buffer)
        print("Nimo ACP server stopped.", file=sys.stderr)
```

- [ ] **Step 2: 实现消息帧读取与响应写入**

```python
    async def _process_buffer(self, buffer: bytes) -> bytes:
        """解析 buffer 中的完整消息帧，分发处理后返回剩余 buffer。"""
        while True:
            m = _HEADER_RE.match(buffer)
            if not m:
                if len(buffer) > 10000:
                    logger.error("Buffer overflow without valid header, resetting")
                    return b""
                return buffer
            content_length = int(m.group(1))
            header_end = m.end()
            body_end = header_end + content_length
            if len(buffer) < body_end:
                return buffer
            body = buffer[header_end:body_end]
            buffer = buffer[body_end:]
            try:
                msg = json.loads(body)
            except json.JSONDecodeError:
                self._write_error(None, -32700, "Parse error")
            except Exception:
                self._write_error(None, -32700, "Parse error")
            else:
                response = await self._dispatch(msg)
                if response is not None:
                    self._write_message(response)

    def _write_message(self, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False)
        raw = body.encode("utf-8")
        header = f"Content-Length: {len(raw)}\r\n\r\n".encode("ascii")
        sys.stdout.buffer.write(header + raw)
        sys.stdout.buffer.flush()

    def _write_error(self, msg_id, code: int, message: str) -> None:
        self._write_message({
            "jsonrpc": "2.0",
            "id": msg_id,
            "error": {"code": code, "message": message},
        })
```

- [ ] **Step 3: 实现 dispatch 路由**

```python
    async def _dispatch(self, msg: dict) -> dict | None:
        msg_id = msg.get("id")
        method = msg.get("method", "")
        params = msg.get("params", {})

        try:
            if method == "initialize":
                return self._handle_initialize(msg_id, params)
            elif method == "session/new":
                return self._handle_session_new(msg_id, params)
            elif method == "session/prompt":
                return await self._handle_session_prompt(msg_id, params)
            else:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }
        except Exception as e:
            logger.exception("Handler error for method: %s", method)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {"code": -32603, "message": str(e)},
            }
```

- [ ] **Step 4: 实现 initialize handler**

```python
    def _handle_initialize(self, msg_id, params: dict) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "protocolVersion": 1,
                "agentCapabilities": {
                    "loadSession": False,
                    "promptCapabilities": {
                        "image": False,
                        "audio": False,
                        "embeddedContext": False,
                    },
                    "mcpCapabilities": {"http": False, "sse": False},
                    "sessionCapabilities": {},
                    "auth": {},
                },
                "agentInfo": {"name": "nimo", "version": "0.1.0"},
                "authMethods": [],
            },
        }
```

- [ ] **Step 5: 实现 session/new handler**

```python
    def _handle_session_new(self, msg_id, params: dict) -> dict:
        session_id = str(uuid.uuid4())
        self._sessions[session_id] = params.get("cwd", "")
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"sessionId": session_id},
        }
```

- [ ] **Step 6: 实现 session/prompt handler**

```python
    async def _handle_session_prompt(self, msg_id, params: dict) -> dict:
        session_id = params.get("sessionId", "")
        if session_id not in self._sessions:
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32602,
                    "message": f"Invalid session: {session_id}",
                },
            }

        prompt_blocks = params.get("prompt", [])
        parts = []
        for block in prompt_blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        user_input = "".join(parts) if parts else " "

        response_text = await self._agent.run(user_input)
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {
                "stopReason": "end_turn",
                "content": [{"type": "text", "text": response_text}],
            },
        }
```

- [ ] **Step 7: 运行测试确认全部通过**

```bash
pytest tests/test_acp_server.py -v
```

预期：全部 PASS

- [ ] **Step 8: 提交**

```bash
git add nimo/acp_server.py tests/test_acp_server.py
git commit -m "feat: 新增 ACP JSON-RPC 服务器，支持 initialize/session-new/session-prompt"
```

---

### Task 3: main.py 接入 --acp 参数

**Files:**
- Modify: `nimo/main.py`

- [ ] **Step 1: 添加 argparse 解析和 ACP 分支**

在 `main.py` 顶部 `import asyncio` 后新增：

```python
import argparse
```

在 `async def main() -> None:` 函数体内，`logging.basicConfig(...)` 之前新增参数解析：

```python
async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--acp", action="store_true", help="以 ACP 模式运行（JSON-RPC over stdin/stdout）")
    args, _ = parser.parse_known_args()  # parse_known_args 兼容 IDE 可能传入的其他参数

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    config = load_config()
    agent = await build_agent(config)

    if args.acp:
        from nimo.acp_server import AcpServer
        await AcpServer(agent).run()
        return

    # --- 以下为现有 CLI 代码，不变 ---
    print_welcome(model=config.llm.model, cwd=os.getcwd(), version="0.1.0")
    while True:
        # ... 现有循环不变 ...
```

完整修改后的 `main()` 函数结构如下：

```python
async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--acp", action="store_true", help="以 ACP 模式运行（JSON-RPC over stdin/stdout）")
    args, _ = parser.parse_known_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    config = load_config()
    agent = await build_agent(config)

    if args.acp:
        from nimo.acp_server import AcpServer
        await AcpServer(agent).run()
        return

    print_welcome(model=config.llm.model, cwd=os.getcwd(), version="0.1.0")
    while True:
        try:
            user_input = input(f"{ORANGE}❯ ")
        except (EOFError, KeyboardInterrupt):
            agent.save_history()
            print("\n再见！")
            break
        # ... 后续不变 ...
```

- [ ] **Step 2: 验证 CLI 模式不受影响**

```bash
echo "/exit" | python -m nimo.main
```

预期：正常打印欢迎画面、提示符，退出时打印"再见！"

- [ ] **Step 3: 验证 ACP 模式握手**

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":1,"clientCapabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' | python -m nimo.main --acp 2>/dev/null
```

预期：stdout 输出 JSON-RPC initialize 响应（包含 `agentInfo.name: "nimo"`），stderr 输出启动/停止日志

- [ ] **Step 4: 提交**

```bash
git add nimo/main.py
git commit -m "feat: main.py 支持 --acp 参数启动 ACP 模式"
```

---

### Task 4: JetBrains IDE 端到端验证

- [ ] **Step 1: 配置 IDE Custom Agent**

在 JetBrains 设置 → Tools → AI Assistant → Custom Agents 中：
- Name: `Nimo`
- Command: `python -m nimo.main --acp`
- Working directory: Nimo 项目根目录

- [ ] **Step 2: 测试连接**

点击 "Test Connection"，预期成功（不再出现 "ACP initialize handshake timed out" 错误）。

- [ ] **Step 3: 测试对话**

在 AI Assistant 中选择 Nimo Agent，发送 "帮我看看有哪些项目"，预期返回正常的 TAPD 项目列表。
```

