"""python_exec：动态执行 Python 代码片段。"""
import asyncio
import logging
import sys

from nimo.tools.registry import register_tool, ToolResult

logger = logging.getLogger(__name__)


@register_tool(
    name="python_exec",
    description=(
        "执行 Python 代码片段，返回 stdout 输出（如 DataFrame、计算结果、API 响应等）。"
        "用于数据处理、API 调用、文件读写等需要编程完成的操作。"
        "代码中可用 print() 输出结果，不要用 input()（会阻塞）。"
        "已预装常用库：requests, pandas, mootdx, stockstats。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "要执行的 Python 代码。多行用 \\n 分隔。用 print() 输出结果。",
            },
        },
        "required": ["code"],
    },
)
async def python_exec(code: str) -> ToolResult:
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", code,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    except asyncio.TimeoutError:
        return ToolResult(success=False, error="代码执行超时（120s）")
    except Exception as e:
        return ToolResult(success=False, error=str(e))

    out_str = stdout.decode(errors="replace").strip()
    err_str = stderr.decode(errors="replace").strip()
    if proc.returncode != 0:
        return ToolResult(success=False, error=err_str or out_str or f"退出码 {proc.returncode}")
    return ToolResult(success=True, data=out_str if out_str else "(无输出)")
