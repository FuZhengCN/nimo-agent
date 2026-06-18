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
    params: dict        # {"owner": "...", "workspace_id": "...", ...}


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
