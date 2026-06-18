# ExecutionEngine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将"编排"和"执行"拆成两层——新增 ExecutionEngine（确定性代码）和意图工具（tapd_query / svn_op），LLM 不再直接操控 CLI。

**Architecture:** 新增 `nimo/engine.py`（ExecutionEngine 单例），新增 `nimo/tools/tapd_intent.py` 和 `nimo/tools/svn_intent.py`（意图工具），旧工具零改动。引擎通过 `init(config)` 接收配置，`execute(intent)` 返回 `ToolResult`。Agent 循环和 ToolRegistry 完全不动。

**Tech Stack:** Python 3.12+, asyncio subprocess, pytest + unittest.mock

---

## 文件结构

```
新建：
  nimo/engine.py              # ExecutionEngine（~180行）
  nimo/tools/tapd_intent.py   # tapd_query 工具（~30行）
  nimo/tools/svn_intent.py    # svn_op 工具（~30行）
  tests/test_engine.py         # 引擎测试（~120行）
  tests/test_tapd_intent.py    # tapd_query 工具测试（~60行）
  tests/test_svn_intent.py    # svn_op 工具测试（~60行）

修改：
  nimo/main.py:169             # build_agent() 中加一行引擎初始化

不动：
  nimo/agent.py               # 零改动
  nimo/tools/registry.py      # 零改动
  nimo/tools/tapd.py          # 零改动（旧工具保留）
  nimo/tools/tortoisesvn.py   # 零改动（旧工具保留）
  nimo/config.py              # 零改动
  nimo/tools/__init__.py      # 零改动（自动发现新模块）
```

---

### Task 1: 创建 ExecutionEngine 骨架（dataclasses + 单例）

**Files:**
- Create: `nimo/engine.py`

- [ ] **Step 1: 写引擎 dataclasses 和单例骨架**

```python
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
```

- [ ] **Step 2: 验证模块可导入**

```bash
python -c "from nimo.engine import ExecutionEngine, Intent, StepResult; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add nimo/engine.py
git commit -m "feat: ExecutionEngine 骨架——Intent/StepResult 数据结构与单例"
```

---

### Task 2: 引擎原子操作（_run_tapd / _run_svn）

**Files:**
- Modify: `nimo/engine.py`（在 ExecutionEngine 类内添加方法）

- [ ] **Step 1: 添加 _run_tapd 方法**

在 `ExecutionEngine` 类的 `init()` 方法之后添加：

```python
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
```

- [ ] **Step 2: 添加 _run_svn 方法**

紧接着添加：

```python
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
```

- [ ] **Step 3: 验证模块仍可导入**

```bash
python -c "from nimo.engine import ExecutionEngine; e = ExecutionEngine(); print(type(e._run_tapd))"
```
Expected: `<class 'function'>` 或类似

- [ ] **Step 4: Commit**

```bash
git add nimo/engine.py
git commit -m "feat: ExecutionEngine 原子操作——_run_tapd / _run_svn"
```

---

### Task 3: 引擎意图→CLI 参数映射

**Files:**
- Modify: `nimo/engine.py`（在 ExecutionEngine 类内添加方法）

- [ ] **Step 1: 添加 _build_tapd_args 和 _build_cli_args**

在 `_run_svn` 方法之后添加：

```python
    def _build_tapd_args(self, intent: Intent, workspace_id: str | None = None) -> list[str] | None:
        """将 Intent 转换为 tapd CLI args 列表。返回 None 表示参数不合法。"""
        action = intent.action
        p = intent.params

        # action 名 → CLI 子命令和操作
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

        mapping = _ACTION_MAP.get(action)
        if mapping is None:
            return None
        subcmd, op = mapping
        args = [subcmd, op]

        # 需要 workspace_id 的命令
        if subcmd != "workspace" and workspace_id:
            args.extend(["--workspace-id", workspace_id])
        elif subcmd != "workspace" and not workspace_id:
            pass  # 调用方负责传入

        # 实体操作需要 ID
        if op == "show" and p.get("entity_id"):
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
```

- [ ] **Step 2: 添加 _build_svn_args 方法**

```python
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
```

- [ ] **Step 3: 验证模块可导入**

```bash
python -c "from nimo.engine import ExecutionEngine; print('OK')"
```

- [ ] **Step 4: Commit**

```bash
git add nimo/engine.py
git commit -m "feat: ExecutionEngine 意图→CLI 参数映射"
```

---

### Task 4: 引擎 execute 方法（模式分发 + 结果合并）

**Files:**
- Modify: `nimo/engine.py`（在 ExecutionEngine 类内添加 execute 及相关方法）

- [ ] **Step 1: 添加 execute 方法及其辅助方法**

在 `_resolve_svn_path` 之后添加：

```python
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
```

- [ ] **Step 2: 验证模块可导入**

```bash
python -c "from nimo.engine import ExecutionEngine; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add nimo/engine.py
git commit -m "feat: ExecutionEngine.execute——模式分发与结果合并"
```

---

### Task 5: 引擎测试

**Files:**
- Create: `tests/test_engine.py`

- [ ] **Step 1: 写测试——direct 模式（有 workspace_id）**

```python
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from nimo.config import Config, LLMConfig, TapdConfig
from nimo.engine import ExecutionEngine, Intent
from nimo.tools.registry import ToolResult


@pytest.fixture(autouse=True)
def reset_engine():
    ExecutionEngine.reset()


@pytest.fixture
def sample_config():
    return Config(
        llm=LLMConfig(
            api_key="sk-test", base_url="https://api.deepseek.com",
            model="deepseek-chat", max_tool_rounds=5, history_rounds=10,
        ),
        tapd=TapdConfig(
            api_base="https://api.tapd.cn", access_token="token123",
            nick="testuser", company_id="12345", owner="testuser",
        ),
    )


@pytest.mark.asyncio
async def test_direct_timesheet_with_workspace_id(sample_config):
    """有 workspace_id → direct 模式，单次执行。"""
    engine = ExecutionEngine.get_instance()
    engine.init(sample_config)

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'[{"id":"1"}]', b""))

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        result = await engine.execute(Intent(
            tool="tapd", action="timesheet_list",
            params={"workspace_id": "755", "owner": "傅政"},
        ))
    assert result.success is True
    assert "1" in str(result.data)
```

- [ ] **Step 2: 写测试——workspace_list direct 模式**

```python
@pytest.mark.asyncio
async def test_direct_workspace_list(sample_config):
    """workspace_list 始终 direct 模式。"""
    engine = ExecutionEngine.get_instance()
    engine.init(sample_config)

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(
        b'[{"id":"755","name":"TAPD"},{"id":"756","name":"Proj2"}]', b"",
    ))

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        result = await engine.execute(Intent(
            tool="tapd", action="workspace_list", params={},
        ))
    assert result.success is True
    assert "TAPD" in str(result.data)
```

- [ ] **Step 3: 写测试——for_each_workspace 模式（正常路径）**

```python
@pytest.mark.asyncio
async def test_for_each_workspace_success(sample_config):
    """无 workspace_id + timesheet_list → for_each_workspace 模式。"""
    engine = ExecutionEngine.get_instance()
    engine.init(sample_config)

    # 第一次调用：workspace list
    ws_list_proc = MagicMock()
    ws_list_proc.returncode = 0
    ws_list_proc.communicate = AsyncMock(return_value=(
        b'[{"id":"755","name":"TAPD"},{"id":"756","name":"Proj2"}]', b"",
    ))

    # 后续调用：每个 workspace 的 timesheet list
    ts1_proc = MagicMock()
    ts1_proc.returncode = 0
    ts1_proc.communicate = AsyncMock(return_value=(b'[{"id":"t1"}]', b""))

    ts2_proc = MagicMock()
    ts2_proc.returncode = 0
    ts2_proc.communicate = AsyncMock(return_value=(b'[{"id":"t2"}]', b""))

    mock_create = AsyncMock(side_effect=[ws_list_proc, ts1_proc, ts2_proc])

    with patch("asyncio.create_subprocess_exec", new=mock_create):
        result = await engine.execute(Intent(
            tool="tapd", action="timesheet_list",
            params={"owner": "傅政"},
        ))
    assert result.success is True
    items = result.data["items"]
    assert len(items) == 2
    assert items[0]["workspace_name"] == "TAPD"
    assert items[1]["workspace_name"] == "Proj2"
```

- [ ] **Step 4: 写测试——for_each_workspace 部分失败**

```python
@pytest.mark.asyncio
async def test_for_each_workspace_partial_failure(sample_config):
    """部分 workspace 失败 → success=True，errors 列出失败项。"""
    engine = ExecutionEngine.get_instance()
    engine.init(sample_config)

    ws_list_proc = MagicMock()
    ws_list_proc.returncode = 0
    ws_list_proc.communicate = AsyncMock(return_value=(
        b'[{"id":"755","name":"A"},{"id":"756","name":"B"}]', b"",
    ))

    ts1_proc = MagicMock()
    ts1_proc.returncode = 0
    ts1_proc.communicate = AsyncMock(return_value=(b'[{"id":"t1"}]', b""))

    ts2_proc = MagicMock()
    ts2_proc.returncode = 1
    ts2_proc.communicate = AsyncMock(return_value=(b"", b"timeout"))

    mock_create = AsyncMock(side_effect=[ws_list_proc, ts1_proc, ts2_proc])

    with patch("asyncio.create_subprocess_exec", new=mock_create):
        result = await engine.execute(Intent(
            tool="tapd", action="timesheet_list",
            params={"owner": "傅政"},
        ))
    assert result.success is True
    assert len(result.data["items"]) == 1  # 只有 A 成功
    assert len(result.data["errors"]) == 1  # B 在 errors 中
```

- [ ] **Step 5: 写测试——全部失败**

```python
@pytest.mark.asyncio
async def test_for_each_workspace_all_failure(sample_config):
    """全部 workspace 失败 → success=False。"""
    engine = ExecutionEngine.get_instance()
    engine.init(sample_config)

    ws_list_proc = MagicMock()
    ws_list_proc.returncode = 0
    ws_list_proc.communicate = AsyncMock(return_value=(
        b'[{"id":"755","name":"A"}]', b"",
    ))

    ts1_proc = MagicMock()
    ts1_proc.returncode = 1
    ts1_proc.communicate = AsyncMock(return_value=(b"", b"auth error"))

    mock_create = AsyncMock(side_effect=[ws_list_proc, ts1_proc])

    with patch("asyncio.create_subprocess_exec", new=mock_create):
        result = await engine.execute(Intent(
            tool="tapd", action="timesheet_list",
            params={"owner": "傅政"},
        ))
    assert result.success is False
    assert result.data is None
    assert "auth error" in result.error
```

- [ ] **Step 6: 写测试——未知 action**

```python
@pytest.mark.asyncio
async def test_unknown_action(sample_config):
    """未知 action → 错误。"""
    engine = ExecutionEngine.get_instance()
    engine.init(sample_config)

    result = await engine.execute(Intent(
        tool="tapd", action="nonexistent_op",
        params={"workspace_id": "755"},
    ))
    assert result.success is False
    assert "未知" in result.error
```

- [ ] **Step 7: 写测试——缺少 workspace_id 的非全覆盖 action**

```python
@pytest.mark.asyncio
async def test_missing_workspace_id_for_create(sample_config):
    """非查询 action（如 story_create）不传 workspace_id → 错误。"""
    engine = ExecutionEngine.get_instance()
    engine.init(sample_config)

    result = await engine.execute(Intent(
        tool="tapd", action="story_create",
        params={"name": "test"},
    ))
    assert result.success is False
    assert "workspace_id" in result.error
```

- [ ] **Step 8: 写测试——workspace list 失败导致 for_each 失败**

```python
@pytest.mark.asyncio
async def test_for_each_workspace_list_fails(sample_config):
    """workspace list 本身失败 → 直接返回失败。"""
    engine = ExecutionEngine.get_instance()
    engine.init(sample_config)

    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"", b"network error"))

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        result = await engine.execute(Intent(
            tool="tapd", action="timesheet_list",
            params={"owner": "傅政"},
        ))
    assert result.success is False
    assert "network error" in result.error
```

- [ ] **Step 9: 写测试——_run_tapd FileNotFoundError**

```python
@pytest.mark.asyncio
async def test_run_tapd_file_not_found(sample_config):
    engine = ExecutionEngine.get_instance()
    engine.init(sample_config)

    with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
        success, stdout, error = await engine._run_tapd(["workspace", "list"])
    assert success is False
    assert "未找到" in error
```

- [ ] **Step 10: 写测试——SVN direct 模式**

```python
@pytest.mark.asyncio
async def test_svn_direct(sample_config):
    """SVN 意图始终 direct 模式。"""
    from nimo.config import TortoiseSvnConfig
    sample_config.tortoisesvn = TortoiseSvnConfig(paths={"default": "/tmp/repo"})

    engine = ExecutionEngine.get_instance()
    engine.init(sample_config)

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"r123 | user | log msg", b""))

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        result = await engine.execute(Intent(
            tool="svn", action="log",
            params={"project": "default", "extra": {"limit": 5}},
        ))
    assert result.success is True
    assert "r123" in str(result.data)
```

- [ ] **Step 11: 运行全部引擎测试**

```bash
pytest tests/test_engine.py -v
```
Expected: 全部 PASS

- [ ] **Step 12: Commit**

```bash
git add tests/test_engine.py
git commit -m "test: ExecutionEngine 全覆盖测试——direct/for_each/部分失败/全失败/SVN"
```

---

### Task 6: tapd_query 意图工具

**Files:**
- Create: `nimo/tools/tapd_intent.py`

- [ ] **Step 1: 写 tapd_query 工具**

```python
"""tapd_query：意图级 TAPD 工具，委托给 ExecutionEngine 执行。"""
import logging
from nimo.tools.registry import register_tool, ToolResult
from nimo.engine import ExecutionEngine, Intent

logger = logging.getLogger(__name__)


@register_tool(
    name="tapd_query",
    description=(
        "执行 TAPD 操作（推荐使用）。可用操作："
        "workspace_list=项目列表, "
        "story_list=需求列表, story_show=需求详情, story_create=创建需求, story_count=需求统计, "
        "task_list=任务列表, task_show=任务详情, task_create=创建任务, "
        "bug_list=缺陷列表, bug_show=缺陷详情, bug_create=创建缺陷, "
        "timesheet_list=工时列表, timesheet_add=填工时, "
        "iteration_list=迭代列表, iteration_create=创建迭代, "
        "comment_list=评论列表, comment_add=添加评论。"
        "查工时/需求/任务/缺陷时，不传 workspace_id 会自动遍历全部项目，无需手动先查项目列表。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "操作名，如 timesheet_list, story_list, story_create, task_show, bug_list 等",
                "enum": [
                    "workspace_list",
                    "story_list", "story_show", "story_create", "story_update", "story_count",
                    "task_list", "task_show", "task_create", "task_update",
                    "bug_list", "bug_show", "bug_create", "bug_update",
                    "timesheet_list", "timesheet_add",
                    "iteration_list", "iteration_create",
                    "comment_list", "comment_add",
                ],
            },
            "workspace_id": {
                "type": "string",
                "description": "项目ID。不传时查询类操作自动遍历全部项目",
            },
            "owner": {
                "type": "string",
                "description": "按人员中文名筛选，如 傅政。仅 timesheet_list/task_list/story_list/bug_list 有效",
            },
            "entity_id": {
                "type": "string",
                "description": "实体ID，show/update 操作用。传此参数时直接操作，不遍历项目",
            },
            "entity_type": {
                "type": "string",
                "description": "实体类型（story/task/bug），timesheet_add 时必填",
                "enum": ["story", "task", "bug"],
            },
            "name": {
                "type": "string",
                "description": "名称，create/update 操作用",
            },
            "description": {
                "type": "string",
                "description": "描述，create/update 操作用",
            },
            "date": {
                "type": "string",
                "description": "日期（YYYY-MM-DD），timesheet 操作用。不传默认当天",
            },
            "timespent": {
                "type": "string",
                "description": "工时（小时），timesheet_add 用",
            },
            "remark": {
                "type": "string",
                "description": "备注，timesheet_add 用",
            },
            "status": {
                "type": "string",
                "description": "状态，create/update 操作用",
            },
            "iteration_id": {
                "type": "string",
                "description": "迭代ID，list 操作用",
            },
            "limit": {
                "type": "integer",
                "description": "返回条数限制",
            },
        },
        "required": ["action"],
    },
)
async def tapd_query(
    action: str,
    workspace_id: str = "",
    owner: str = "",
    entity_id: str = "",
    entity_type: str = "",
    name: str = "",
    description: str = "",
    date: str = "",
    timespent: str = "",
    remark: str = "",
    status: str = "",
    iteration_id: str = "",
    limit: int = 0,
) -> ToolResult:
    engine = ExecutionEngine.get_instance()
    params = {}
    for key, val in locals().items():
        if key != "action" and val:
            params[key] = val
    intent = Intent(tool="tapd", action=action, params=params)
    return await engine.execute(intent)
```

- [ ] **Step 2: 验证工具自动注册**

```bash
python -c "from nimo.tools.registry import ToolRegistry; tools = ToolRegistry.get_instance().list_tools(); print([t[0] for t in tools])"
```
Expected: 列表包含 `tapd_query`（除原有的 `tapd_cli`、`svn` 外）

- [ ] **Step 3: Commit**

```bash
git add nimo/tools/tapd_intent.py
git commit -m "feat: tapd_query 意图工具——委托 ExecutionEngine 执行"
```

---

### Task 7: tapd_query 工具测试

**Files:**
- Create: `tests/test_tapd_intent.py`

- [ ] **Step 1: 写测试**

```python
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from nimo.config import Config, LLMConfig, TapdConfig
from nimo.engine import ExecutionEngine

# 触发 @register_tool
import nimo.tools.tapd_intent


@pytest.fixture(autouse=True)
def reset_engine():
    ExecutionEngine.reset()


@pytest.fixture
def sample_config():
    return Config(
        llm=LLMConfig(
            api_key="sk-test", base_url="https://api.deepseek.com",
            model="deepseek-chat", max_tool_rounds=5, history_rounds=10,
        ),
        tapd=TapdConfig(
            api_base="https://api.tapd.cn", access_token="token123",
        ),
    )


@pytest.mark.asyncio
async def test_tapd_query_workspace_list(sample_config):
    """tapd_query workspace_list → 调引擎 direct 模式。"""
    engine = ExecutionEngine.get_instance()
    engine.init(sample_config)

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(
        b'[{"id":"755","name":"TAPD"}]', b"",
    ))

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        result = await nimo.tools.tapd_intent.tapd_query(action="workspace_list")
    assert result.success is True
    assert "TAPD" in str(result.data)


@pytest.mark.asyncio
async def test_tapd_query_timesheet_with_owner(sample_config):
    """tapd_query timesheet_list + owner → for_each_workspace。"""
    engine = ExecutionEngine.get_instance()
    engine.init(sample_config)

    ws_proc = MagicMock()
    ws_proc.returncode = 0
    ws_proc.communicate = AsyncMock(return_value=(
        b'[{"id":"755","name":"TAPD"}]', b"",
    ))

    ts_proc = MagicMock()
    ts_proc.returncode = 0
    ts_proc.communicate = AsyncMock(return_value=(b'[{"Timesheet":{"id":"1"}}]', b""))

    mock_create = AsyncMock(side_effect=[ws_proc, ts_proc])

    with patch("asyncio.create_subprocess_exec", new=mock_create):
        result = await nimo.tools.tapd_intent.tapd_query(
            action="timesheet_list", owner="傅政",
        )
    assert result.success is True
    assert len(result.data["items"]) == 1


@pytest.mark.asyncio
async def test_tapd_query_engine_not_initialized():
    """引擎未初始化 → 应报错。"""
    ExecutionEngine.reset()
    result = await nimo.tools.tapd_intent.tapd_query(
        action="workspace_list",
    )
    assert result.success is False
```

- [ ] **Step 2: 运行测试**

```bash
pytest tests/test_tapd_intent.py -v
```
Expected: 全部 PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_tapd_intent.py
git commit -m "test: tapd_query 工具测试"
```

---

### Task 8: svn_op 意图工具

**Files:**
- Create: `nimo/tools/svn_intent.py`

- [ ] **Step 1: 写 svn_op 工具**

```python
"""svn_op：意图级 SVN 工具，委托给 ExecutionEngine 执行。"""
import logging
from nimo.tools.registry import register_tool, ToolResult
from nimo.engine import ExecutionEngine, Intent

logger = logging.getLogger(__name__)


@register_tool(
    name="svn_op",
    description=(
        "执行 SVN 版本控制操作（推荐使用）。"
        "常用操作：log=提交记录, diff=差异对比, blame=逐行追溯, "
        "update=更新工作副本, commit=提交更改, checkout=检出仓库, "
        "add=添加文件, revert=还原, cleanup=清理, info=仓库信息, "
        "switch=切换分支, merge=合并, lock/unlock=锁定/解锁, "
        "rename/remove=文件操作, import/export=导入/导出, repocreate=创建仓库。"
        "path 和 project 可选，不传则自动使用默认项目。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "SVN 操作名",
                "enum": [
                    "log", "diff", "blame", "update", "commit", "checkout",
                    "add", "revert", "cleanup", "resolve", "switch", "merge",
                    "relocate", "lock", "unlock", "rename", "remove",
                    "import", "export", "properties", "info", "repocreate",
                ],
            },
            "path": {
                "type": "string",
                "description": "工作副本路径。优先级最高，传了就不需要 project",
            },
            "project": {
                "type": "string",
                "description": "项目名，对应配置文件中的项目别名。不传则用默认项目",
            },
            "url": {
                "type": "string",
                "description": "仓库 URL，仅 checkout/switch/import/export 等需要",
            },
            "extra": {
                "type": "object",
                "description": (
                    "额外参数。log 常用：{\"limit\": 10, \"search\": \"关键词\"}。"
                    "diff 常用：{\"revision\": \"r123:124\"}。"
                    "commit 常用：{\"message\": \"提交信息\"}。"
                ),
            },
        },
        "required": ["action"],
    },
)
async def svn_op(
    action: str,
    path: str = "",
    project: str = "",
    url: str = "",
    extra: dict | None = None,
) -> ToolResult:
    engine = ExecutionEngine.get_instance()
    params = {}
    for key, val in locals().items():
        if key != "action" and val:
            params[key] = val
    intent = Intent(tool="svn", action=action, params=params)
    return await engine.execute(intent)
```

- [ ] **Step 2: 验证工具自动注册**

```bash
python -c "from nimo.tools.registry import ToolRegistry; tools = ToolRegistry.get_instance().list_tools(); print([t[0] for t in tools])"
```
Expected: 列表包含 `svn_op`

- [ ] **Step 3: Commit**

```bash
git add nimo/tools/svn_intent.py
git commit -m "feat: svn_op 意图工具——委托 ExecutionEngine 执行"
```

---

### Task 9: svn_op 工具测试

**Files:**
- Create: `tests/test_svn_intent.py`

- [ ] **Step 1: 写测试**

```python
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from nimo.config import Config, LLMConfig, TapdConfig, TortoiseSvnConfig
from nimo.engine import ExecutionEngine

import nimo.tools.svn_intent


@pytest.fixture(autouse=True)
def reset_engine():
    ExecutionEngine.reset()


@pytest.fixture
def sample_config():
    return Config(
        llm=LLMConfig(
            api_key="sk-test", base_url="https://api.deepseek.com",
            model="deepseek-chat", max_tool_rounds=5, history_rounds=10,
        ),
        tapd=TapdConfig(
            api_base="https://api.tapd.cn", access_token="token123",
        ),
        tortoisesvn=TortoiseSvnConfig(paths={"default": "/tmp/repo"}),
    )


@pytest.mark.asyncio
async def test_svn_op_log(sample_config):
    """svn_op log → 引擎 direct 模式。"""
    engine = ExecutionEngine.get_instance()
    engine.init(sample_config)

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"r123 | user | msg", b""))

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        result = await nimo.tools.svn_intent.svn_op(
            action="log", project="default", extra={"limit": 5},
        )
    assert result.success is True
    assert "r123" in str(result.data)


@pytest.mark.asyncio
async def test_svn_op_no_config():
    """无 SVN 配置 → 应报错。"""
    ExecutionEngine.reset()
    result = await nimo.tools.svn_intent.svn_op(action="log")
    assert result.success is False


@pytest.mark.asyncio
async def test_svn_op_commit_message(sample_config):
    """svn_op commit 带 message。"""
    engine = ExecutionEngine.get_instance()
    engine.init(sample_config)

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"Committed revision 99.", b""))

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        result = await nimo.tools.svn_intent.svn_op(
            action="commit", project="default",
            extra={"message": "fix bug"},
        )
    assert result.success is True
```

- [ ] **Step 2: 运行测试**

```bash
pytest tests/test_svn_intent.py -v
```
Expected: 全部 PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_svn_intent.py
git commit -m "test: svn_op 工具测试"
```

---

### Task 10: 集成验证——旧工具不受影响 + 引擎初始化接入

**Files:**
- Modify: `nimo/main.py:169`（在 build_agent 中加引擎初始化）

- [ ] **Step 1: 在 build_agent 中初始化引擎**

修改 `nimo/main.py` 的 `build_agent` 函数：

```python
async def build_agent(config: Config) -> Agent:
    from nimo.engine import ExecutionEngine
    ExecutionEngine.get_instance().init(config)
    await ToolRegistry.get_instance().init_all(config)
    return Agent(config)
```

（在现有 `await ToolRegistry.get_instance().init_all(config)` 之前加一行）

- [ ] **Step 2: 运行全部已有测试确保无回归**

```bash
pytest tests/ -v
```
Expected: 全部已有测试仍然 PASS

- [ ] **Step 3: 验证新模块也被测试覆盖**

```bash
pytest tests/ -v --cov=nimo --cov-report=term-missing
```
确认 `engine.py`、`tapd_intent.py`、`svn_intent.py` 有覆盖率

- [ ] **Step 4: Commit**

```bash
git add nimo/main.py
git commit -m "feat: build_agent 初始化 ExecutionEngine"
```

---

## 完成标志

- [ ] `nimo/engine.py` 存在，含 ExecutionEngine（execute / _run_tapd / _run_svn / 模式分发）
- [ ] `nimo/tools/tapd_intent.py` 存在，tapd_query 自动注册
- [ ] `nimo/tools/svn_intent.py` 存在，svn_op 自动注册
- [ ] `nimo/main.py` build_agent 初始化引擎
- [ ] 全部已有测试通过（零回归）
- [ ] 新测试覆盖：direct / for_each_workspace / 部分失败 / 全失败 / SVN
- [ ] 旧工具 `tapd_cli` / `svn` 未改动
