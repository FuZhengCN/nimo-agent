import asyncio
import logging
import os
from pathlib import Path
from nimo.config import Config
from nimo.tools.registry import register_tool, ToolResult

logger = logging.getLogger(__name__)

_config: Config | None = None

# tapd CLI 二进制在项目 bin 目录
_TAPD_BIN = str(Path(__file__).resolve().parent.parent.parent / "bin" / "tapd.exe")

# 允许的 tapd 子命令白名单
_ALLOWED_COMMANDS = frozenset({
    "workspace", "story", "task", "bug", "timesheet",
    "iteration", "comment", "wiki", "launch", "workflow", "url",
})


def _validate_args(args: list[str]) -> str | None:
    """校验参数安全性，返回错误信息或 None（表示通过）。"""
    if not args:
        return "参数不能为空"
    cmd = args[0]
    if cmd.startswith("-"):
        return f"无效的子命令：{cmd}"
    if cmd not in _ALLOWED_COMMANDS:
        return f"不允许的子命令：{cmd}"
    for arg in args:
        if arg.startswith("..") or "/.." in arg:
            return f"参数包含路径遍历：{arg}"
    return None


async def init_tapd(config: Config) -> None:
    global _config
    _config = config


@register_tool(
    name="tapd_cli",
    description="通过 tapd CLI 执行 TAPD 操作。可用子命令：workspace list|switch|info / story|task|bug list|show|create|update|count|todo / timesheet list|add / iteration list|create|update / comment list|add / wiki list|show / launch list / workflow transitions|status-map / url <tapd-url> 等等。项目ID通过 --workspace-id 指定。返回 JSON。",
    parameters={
        "type": "object",
        "properties": {
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": "tapd 命令参数，如 ['story', 'list', '--workspace-id', '12345', '--filter', 'name=LIKE<登录>']",
            },
        },
        "required": ["args"],
    },
)
async def tapd_cli(args: list[str]) -> ToolResult:
    if error := _validate_args(args):
        return ToolResult(success=False, error=error)
    try:
        env = os.environ.copy()
        env["TAPD_ACCESS_TOKEN"] = _config.tapd.access_token
        if _config.tapd.api_base and _config.tapd.api_base != "https://api.tapd.cn":
            env["TAPD_API_BASE_URL"] = _config.tapd.api_base

        proc = await asyncio.create_subprocess_exec(
            _TAPD_BIN, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            err_msg = (stderr.decode() or stdout.decode()).strip()
            return ToolResult(success=False, error=err_msg or f"tapd CLI 返回非零退出码 {proc.returncode}")
        return ToolResult(success=True, data=stdout.decode().strip())
    except FileNotFoundError:
        return ToolResult(success=False, error="tapd CLI 未找到，请将 tapd.exe 放到项目 bin/ 目录")
    except Exception as e:
        logger.exception("tapd CLI 执行失败")
        return ToolResult(success=False, error=str(e))
