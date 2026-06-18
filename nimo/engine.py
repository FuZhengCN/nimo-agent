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

    # action 名 → (tapd CLI 子命令, 操作)
    _ACTION_MAP: dict[str, tuple[str, str]] = {
        "workspace_list": ("workspace", "list"),
        "story_list": ("story", "list"),
        "story_show": ("story", "show"),
        "story_create": ("story", "create"),
        "story_update": ("story", "update"),
        "story_count": ("story", "count"),
        "task_list": ("task", "list"),
        "task_show": ("task", "show"),
        "task_create": ("task", "create"),
        "task_update": ("task", "update"),
        "bug_list": ("bug", "list"),
        "bug_show": ("bug", "show"),
        "bug_create": ("bug", "create"),
        "bug_update": ("bug", "update"),
        "timesheet_list": ("timesheet", "list"),
        "timesheet_add": ("timesheet", "add"),
        "iteration_list": ("iteration", "list"),
        "iteration_create": ("iteration", "create"),
        "comment_list": ("comment", "list"),
        "comment_add": ("comment", "add"),
    }

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

    def _build_tapd_args(self, intent: Intent, workspace_id: str | None = None) -> list[str] | None:
        """将 Intent 转换为 tapd CLI args 列表。返回 None 表示参数不合法。"""
        action = intent.action
        p = intent.params

        mapping = self._ACTION_MAP.get(action)
        if mapping is None:
            return None
        subcmd, op = mapping
        args = [subcmd, op]

        # 需要 workspace_id 的命令
        if subcmd != "workspace" and workspace_id:
            args.extend(["--workspace-id", workspace_id])

        # 实体操作需要 ID
        if op in ("show", "update") and p.get("entity_id"):
            args.append(p["entity_id"])

        # list 类操作的通用参数
        if op == "list":
            if p.get("owner"):
                args.extend(["--owner", p["owner"]])
            if p.get("limit"):
                args.extend(["--limit", str(p["limit"])])
            if p.get("iteration_id"):
                args.extend(["--iteration-id", p["iteration_id"]])

        # timesheet_list 特殊：默认追加 --limit
        if action == "timesheet_list":
            if "--limit" not in args:
                args.extend(["--limit", "200"])

        # timesheet_add 参数
        if action == "timesheet_add":
            entity_type = p.get("entity_type", "")
            entity_id = p.get("entity_id", "")
            if entity_type and entity_id:
                args.extend(["--entity-type", entity_type, "--entity-id", entity_id])
            if p.get("timespent"):
                args.extend(["--timespent", p["timespent"]])
            if p.get("date"):
                args.extend(["--date", p["date"]])
            if p.get("remark"):
                args.extend(["--remark", p["remark"]])

        # create / update 参数
        if op in ("create", "update"):
            if p.get("name"):
                args.extend(["--name", p["name"]])
            if p.get("description"):
                args.extend(["--description", p["description"]])
            if p.get("status"):
                args.extend(["--status", p["status"]])

        return args

    def _resolve_svn_path(self, path: str, project: str) -> tuple[str, str | None]:
        """解析 SVN 路径，返回 (path, error)。"""
        if path:
            return path, None
        cfg = self._config.tortoisesvn if self._config else None
        if not cfg or not cfg.paths:
            return "", "未配置 SVN 项目，请在 config.yaml 的 tortoisesvn.paths 中配置"
        if project:
            if project in cfg.paths:
                return cfg.paths[project], None
            return "", f"未知项目：{project}，可用：{', '.join(cfg.paths.keys())}"
        if len(cfg.paths) == 1:
            return next(iter(cfg.paths.values())), None
        names = ', '.join(cfg.paths.keys())
        return "", f"有多个项目（{names}），请用 project 参数指定"

    async def execute(self, intent: Intent) -> ToolResult:
        """入口：解析 Intent，匹配模式，执行，返回 ToolResult。"""
        if intent.tool == "tapd":
            return await self._execute_tapd(intent)
        elif intent.tool == "svn":
            return await self._execute_svn(intent)
        return ToolResult(success=False, error=f"未知工具类型：{intent.tool}")

    async def _execute_tapd(self, intent: Intent) -> ToolResult:
        """执行 TAPD 意图。"""
        ws_id = intent.params.get("workspace_id", "")
        entity_id = intent.params.get("entity_id", "")

        # direct 模式：有明确目标
        if ws_id or entity_id or intent.action == "workspace_list":
            if intent.action == "workspace_list":
                args = ["workspace", "list"]
            else:
                args = self._build_tapd_args(intent, workspace_id=ws_id or None)
                if args is None:
                    return ToolResult(success=False, error=f"未知 TAPD 操作：{intent.action}")
            success, stdout, error = await self._run_tapd(args)
            if success:
                return ToolResult(success=True, data=stdout)
            return ToolResult(success=False, error=error or stdout)

        # for_each_workspace 模式
        if intent.action in _FOR_EACH_ACTIONS:
            return await self._execute_for_each_workspace(intent)

        # 需要 workspace_id 但没传
        return ToolResult(
            success=False,
            error=f"操作 {intent.action} 需要 workspace_id 参数",
        )

    async def _execute_for_each_workspace(self, intent: Intent) -> ToolResult:
        """for_each_workspace 模式：先拉全部项目，再逐个查询。"""
        # Step 1: 获取全部项目
        success, stdout, error = await self._run_tapd(["workspace", "list"])
        if not success:
            return ToolResult(success=False, error=f"获取项目列表失败：{error or stdout}")

        # 解析项目列表 JSON
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            return ToolResult(success=False, error=f"项目列表 JSON 解析失败：{stdout[:200]}")
        if isinstance(data, dict):
            workspaces = data.get("data", data.get("items", []))
        elif isinstance(data, list):
            workspaces = data
        else:
            return ToolResult(success=False, error=f"无法识别的项目列表格式：{stdout[:200]}")
        if not workspaces:
            return ToolResult(success=False, error="没有任何项目")

        # Step 2: 逐个查询
        step_results: list[StepResult] = []
        for ws in workspaces:
            if isinstance(ws, dict):
                ws_id = str(ws.get("id", ws.get("workspace_id", "")))
                ws_name = ws.get("name", ws.get("workspace_name", ws_id))
            else:
                ws_id = str(ws)
                ws_name = ws_id

            args = self._build_tapd_args(intent, workspace_id=ws_id)
            if args is None:
                step_results.append(StepResult(
                    workspace_id=ws_id, workspace_name=ws_name,
                    success=False, error=f"未知操作：{intent.action}",
                ))
                continue

            ok, out, err = await self._run_tapd(args)
            step_results.append(StepResult(
                workspace_id=ws_id, workspace_name=ws_name,
                success=ok, data=out, error=err if not ok else None,
            ))

        return self._merge_results(step_results)

    def _merge_results(self, step_results: list[StepResult]) -> ToolResult:
        """合并多步骤结果。至少 1 步成功即 success=True。"""
        successful = [r for r in step_results if r.success]
        failed = [r for r in step_results if not r.success]

        if not successful:
            errors = [f"{r.workspace_name}: {r.error}" for r in failed]
            return ToolResult(
                success=False,
                data=None,
                error="；".join(errors),
            )

        items: list[dict] = []
        for r in successful:
            items.append({
                "workspace_id": r.workspace_id,
                "workspace_name": r.workspace_name,
                "data": r.data,
            })

        summary = f"{len(step_results)} 个项目，{len(successful)} 个成功"
        if failed:
            errors = [f"{r.workspace_name}: {r.error}" for r in failed]
            summary += f"，{len(failed)} 个失败"
            return ToolResult(
                success=True,
                data={"items": items, "summary": summary, "errors": errors},
            )
        return ToolResult(
            success=True,
            data={"items": items, "summary": summary},
        )

    async def _execute_svn(self, intent: Intent) -> ToolResult:
        """执行 SVN 意图（始终 direct 模式）。"""
        action = intent.action
        p = intent.params

        path, path_error = self._resolve_svn_path(
            p.get("path", ""), p.get("project", ""),
        )
        if path_error:
            return ToolResult(success=False, error=path_error)

        if ".." in path.replace("/", "\\"):
            return ToolResult(success=False, error=f"路径包含路径遍历：{path}")

        is_admin = action == "repocreate"
        url = p.get("url", "")
        extra = p.get("extra")
        extra_args = None
        if isinstance(extra, dict):
            extra_args = []
            for k, v in extra.items():
                kebab = k.replace("_", "-")
                if len(kebab) == 1:
                    extra_args.append(f"-{kebab}")
                else:
                    extra_args.append(f"--{kebab}")
                if v is not True:
                    extra_args.append(str(v))
        elif isinstance(extra, list):
            extra_args = [str(x) for x in extra]

        success, stdout, error = await self._run_svn(
            command=action, path=path, url=url,
            extra_args=extra_args, is_admin=is_admin,
        )
        if success:
            return ToolResult(success=True, data=stdout)
        return ToolResult(success=False, error=error or stdout)
