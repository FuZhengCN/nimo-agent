"""ExecutionEngine：将 LLM 意图转换为确定性 CLI 执行。"""
import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nimo.config import Config
from nimo.tools.registry import ToolResult

logger = logging.getLogger(__name__)

_BIN_DIR = Path(__file__).resolve().parent.parent / "bin"
_TAPD_BIN = str(_BIN_DIR / "tapd.exe")
_SVN_EXE = str(_BIN_DIR / "svn.exe")
_SVNADMIN_EXE = str(_BIN_DIR / "svnadmin.exe")

# 支持 for_each_workspace 模式的 action
_FOR_EACH_ACTIONS = frozenset({
    "timesheet_list", "story_list", "story_count",
    "task_list", "bug_list", "iteration_list",
})


@dataclass
class Intent:
    tool: str           # "tapd" | "svn"
    action: str         # "timesheet_list" | "story_list" | "log" | ...
    params: dict[str, Any]  # {"owner": "...", "workspace_id": "...", ...}


@dataclass
class StepResult:
    workspace_id: str
    workspace_name: str
    success: bool
    data: Any = None
    error: str | None = None


class ExecutionEngine:
    _instance: "ExecutionEngine | None" = None

    def __init__(self):
        self._config: Config | None = None

    @classmethod
    def get_instance(cls) -> "ExecutionEngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    def init(self, config: Config) -> None:
        self._config = config

    async def _run_tapd(self, args: list[str]) -> tuple[bool, str, str]:
        """执行 tapd CLI，返回 (success, stdout, stderr|error_msg)。"""
        if self._config is None:
            return False, "", "引擎未初始化，缺少配置"
        env = os.environ.copy()
        env["TAPD_ACCESS_TOKEN"] = self._config.tapd.access_token
        if self._config.tapd.api_base and self._config.tapd.api_base != "https://api.tapd.cn":
            env["TAPD_API_BASE_URL"] = self._config.tapd.api_base

        try:
            proc = await asyncio.create_subprocess_exec(
                _TAPD_BIN, *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
            stdout, stderr = await proc.communicate()
        except FileNotFoundError:
            return False, "", "tapd CLI 未找到，请将 tapd.exe 放到项目 bin/ 目录"
        except Exception as e:
            return False, "", str(e)

        out_str = stdout.decode(errors="replace").strip()
        err_str = stderr.decode(errors="replace").strip()
        if proc.returncode != 0:
            return False, out_str, err_str or out_str or f"tapd CLI 返回非零退出码 {proc.returncode}"
        return True, out_str, ""

    async def _run_svn(self, command: str, path: str,
                       url: str = "", extra_args: list[str] | None = None,
                       is_admin: bool = False) -> tuple[bool, str, str]:
        """执行 SVN CLI，返回 (success, stdout, error_msg)。"""
        if is_admin:
            args = [_SVNADMIN_EXE, command]
        else:
            args = [_SVN_EXE, command]
        if extra_args:
            args.extend(extra_args)
        # 需要 URL 在前的命令
        if command in ("switch", "merge", "checkout", "import", "export"):
            if url:
                args.append(url)
            if path:
                args.append(path)
        elif path:
            args.append(path)

        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
        except FileNotFoundError as e:
            return False, "", f"可执行文件未找到：{e}"
        except Exception as e:
            return False, "", str(e)

        def _decode(data: bytes) -> str:
            for enc in ("gbk", "utf-8"):
                try:
                    return data.decode(enc)
                except UnicodeDecodeError:
                    continue
            return data.decode(errors="replace")

        out_str = _decode(stdout).strip()
        err_str = _decode(stderr).strip()
        if proc.returncode != 0:
            return False, out_str, err_str or out_str or f"svn 返回非零退出码 {proc.returncode}"
        return True, out_str, ""
