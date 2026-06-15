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
        """Main loop: read JSON-RPC messages from stdin, dispatch, write responses to stdout."""
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

    async def _process_buffer(self, buffer: bytes) -> bytes:
        """Parse complete message frames from buffer, dispatch, return remainder."""
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

    def _handle_session_new(self, msg_id, params: dict) -> dict:
        session_id = str(uuid.uuid4())
        self._sessions[session_id] = params.get("cwd", "")
        return {
            "jsonrpc": "2.0",
            "id": msg_id,
            "result": {"sessionId": session_id},
        }

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
