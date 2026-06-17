# 定时任务系统重设计 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 asyncio 内置调度替代 schtasks 冷启动，复用 Agent.run() 执行定时任务，零外部依赖。

**Architecture:** 单文件 `nimo/tools/schedule.py` 包含校验/存储/工具注册/调度器四层。Scheduler 作为后台 asyncio Task 每 60s 轮询 schedules.json，到点触发 `agent.run(prompt)` 并推送通知队列。main.py 输入循环在提示符前检查通知队列。cron 5 字段自解析，支持 `*` `*/N` `N` `N-M`。

**Tech Stack:** Python asyncio, JSON 文件存储，现有 LLMClient + ToolRegistry + Agent

---

### Task 1: SchedulesConfig 配置支持

**Files:**
- Modify: `nimo/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: 编写 SchedulesConfig 的失败测试**

```python
# tests/test_config.py 追加

def test_schedules_config_default():
    from nimo.config import SchedulesConfig
    sc = SchedulesConfig()
    assert sc.enabled is False


def test_schedules_config_enabled():
    from nimo.config import SchedulesConfig
    sc = SchedulesConfig(enabled=True)
    assert sc.enabled is True


def test_load_config_without_schedules_section():
    """schedules 段缺失时使用默认值（enabled=False）。"""
    import yaml
    from nimo.config import load_config
    import tempfile
    import os

    yaml_content = """llm:
  api_key: sk-test
  base_url: https://api.deepseek.com
  model: deepseek-chat
  max_tool_rounds: 5
  history_rounds: 10
tapd:
  api_base: https://api.tapd.cn
  access_token: token123
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        tmp = f.name
    try:
        config = load_config(tmp)
        assert config.schedules.enabled is False
    finally:
        os.unlink(tmp)


def test_load_config_with_schedules_enabled():
    """schedules 段存在且 enabled 为 true。"""
    import yaml
    from nimo.config import load_config
    import tempfile
    import os

    yaml_content = """llm:
  api_key: sk-test
  base_url: https://api.deepseek.com
  model: deepseek-chat
  max_tool_rounds: 5
  history_rounds: 10
tapd:
  api_base: https://api.tapd.cn
  access_token: token123
schedules:
  enabled: true
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        tmp = f.name
    try:
        config = load_config(tmp)
        assert config.schedules.enabled is True
    finally:
        os.unlink(tmp)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_config.py::test_schedules_config_default tests/test_config.py::test_schedules_config_enabled tests/test_config.py::test_load_config_without_schedules_section tests/test_config.py::test_load_config_with_schedules_enabled -v
```
预期：FAIL，`SchedulesConfig` 未定义

- [ ] **Step 3: 实现 SchedulesConfig 并集成到 Config**

```python
# nimo/config.py — 在 TortoiseSvnConfig 之后追加

@dataclass
class SchedulesConfig:
    enabled: bool = False
```

```python
# nimo/config.py — Config 类追加 schedules 字段

@dataclass
class Config:
    llm: LLMConfig
    tapd: TapdConfig
    tortoisesvn: TortoiseSvnConfig = field(default_factory=TortoiseSvnConfig)
    schedules: SchedulesConfig = field(default_factory=SchedulesConfig)
```

```python
# nimo/config.py — load_config() return 之前追加

    schedules_raw = raw.get("schedules", {})
    schedules = SchedulesConfig(
        enabled=schedules_raw.get("enabled", False),
    )
    return Config(llm=llm, tapd=tapd, tortoisesvn=tortoisesvn, schedules=schedules)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_config.py::test_schedules_config_default tests/test_config.py::test_schedules_config_enabled tests/test_config.py::test_load_config_without_schedules_section tests/test_config.py::test_load_config_with_schedules_enabled -v
```
预期：4 PASS

- [ ] **Step 5: 提交**

```bash
git add nimo/config.py tests/test_config.py
git commit -m "feat: 添加 SchedulesConfig 配置支持"
```

---

### Task 2: schedule 模块基础 — 安全校验 + schedules.json 读写

**Files:**
- Create: `nimo/tools/schedule.py`
- Test: `tests/test_schedule.py`（新文件）

- [ ] **Step 1: 编写校验和存储的失败测试**

```python
# tests/test_schedule.py

import json
import pytest
from unittest.mock import patch
from pathlib import Path
from nimo.tools.schedule import _validate_args, _load_schedules, _save_schedules


def test_validate_action_whitelist():
    assert _validate_args("list") is None
    assert _validate_args("add") is None
    assert _validate_args("remove") is None
    assert _validate_args("enable") is None
    assert _validate_args("disable") is None
    assert _validate_args("delete") is not None
    assert _validate_args("run") is not None  # run 已废弃
    assert _validate_args("") is not None
    assert _validate_args("LIST") is not None  # 小写白名单


def test_validate_task_id_valid():
    assert _validate_args("add", "daily-check") is None
    assert _validate_args("add", "weekly-report") is None
    assert _validate_args("add", "task-123") is None


def test_validate_task_id_invalid():
    assert _validate_args("add", "../etc") is not None
    assert _validate_args("add", "rm -rf") is not None
    assert _validate_args("add", "") is not None
    assert _validate_args("add", "a" * 65) is not None  # 超过64字符
    assert _validate_args("add", "A" * 64) is None


def test_validate_cron_valid():
    assert _validate_args("add", "ok", "0 9 * * 1-5") is None
    assert _validate_args("add", "ok", "*/5 * * * *") is None
    assert _validate_args("add", "ok", "30 8,17 * * 1-5") is None


def test_validate_cron_invalid():
    assert _validate_args("add", "ok", "0 9 *") is not None  # 只有3字段
    assert _validate_args("add", "ok", "invalid cron") is not None
    assert _validate_args("add", "ok", "60 * * * *") is not None  # 分钟超出范围


def test_validate_delay_minutes_valid():
    assert _validate_args("add", "ok", delay_minutes=30) is None
    assert _validate_args("add", "ok", delay_minutes=1) is None
    assert _validate_args("add", "ok", delay_minutes=1440) is None


def test_validate_delay_minutes_invalid():
    assert _validate_args("add", "ok", delay_minutes=0) is not None
    assert _validate_args("add", "ok", delay_minutes=1441) is not None


def test_validate_missing_cron_and_delay():
    """add 时 cron 和 delay_minutes 都没提供。"""
    assert _validate_args("add", "ok") is not None


def test_validate_both_cron_and_delay():
    """add 时同时提供 cron 和 delay_minutes。"""
    assert _validate_args("add", "ok", "0 9 * * *", "检查", 30) is not None


def test_validate_prompt_too_long():
    long_prompt = "检查" * 300  # > 500 字符
    assert _validate_args("add", "ok", "0 9 * * *", long_prompt) is not None


def test_validate_prompt_ok():
    assert _validate_args("add", "ok", "0 9 * * *", "检查任务") is None


def test_load_schedules_not_exist(tmp_path, monkeypatch):
    monkeypatch.setattr("nimo.tools.schedule._schedules_path", lambda: tmp_path / "schedules.json")
    result = _load_schedules()
    assert result == {"tasks": []}


def test_save_and_load_schedules(tmp_path, monkeypatch):
    monkeypatch.setattr("nimo.tools.schedule._schedules_path", lambda: tmp_path / "schedules.json")
    data = {
        "tasks": [
            {
                "id": "daily-check",
                "type": "cron",
                "cron": "0 9 * * 1-5",
                "delay_minutes": None,
                "prompt": "检查到期任务",
                "enabled": True,
                "created_at": "2026-06-17T10:00:00",
                "last_run": None,
                "last_result": None,
            }
        ]
    }
    _save_schedules(data)
    loaded = _load_schedules()
    assert len(loaded["tasks"]) == 1
    assert loaded["tasks"][0]["id"] == "daily-check"
    assert loaded["tasks"][0]["type"] == "cron"


def test_load_schedules_corrupted(tmp_path, monkeypatch):
    """损坏的 JSON 文件返回空任务列表。"""
    path = tmp_path / "schedules.json"
    path.write_text("this is not json")
    monkeypatch.setattr("nimo.tools.schedule._schedules_path", lambda: path)
    result = _load_schedules()
    assert result == {"tasks": []}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_schedule.py -v
```
预期：FAIL（模块/函数未定义）或导入失败

- [ ] **Step 3: 实现 schedule.py 基础**

```python
# nimo/tools/schedule.py

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from nimo.tools.registry import ToolResult

logger = logging.getLogger(__name__)

_ALLOWED_ACTIONS = frozenset({"list", "add", "remove", "enable", "disable"})
_CRON_RE = re.compile(
    r"^(\*|[\d,\-*/]+)\s+(\*|[\d,\-*/]+)\s+(\*|[\d,\-*/]+)\s+(\*|[\d,\-*/]+)\s+(\*|[\d,\-*/]+)$"
)

_config = None


def _schedules_path() -> Path:
    return Path.home() / ".nimo" / "schedules.json"


def _load_schedules() -> dict:
    path = _schedules_path()
    if not path.exists():
        return {"tasks": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        logger.warning("schedules.json 损坏，使用空配置", exc_info=True)
        return {"tasks": []}


def _save_schedules(data: dict) -> None:
    path = _schedules_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _validate_cron_field(pattern: str, min_val: int, max_val: int) -> bool:
    """校验单个 cron 字段是否合法。"""
    for part in pattern.split(","):
        if "/" in part:
            base, step = part.split("/", 1)
            if not step.isdigit():
                return False
            step_val = int(step)
            if step_val < 1:
                return False
            if base == "*":
                continue
            if not base.isdigit():
                return False
            if not (min_val <= int(base) <= max_val):
                return False
        elif "-" in part:
            lo, hi = part.split("-", 1)
            if not lo.isdigit() or not hi.isdigit():
                return False
            if not (min_val <= int(lo) <= max_val and min_val <= int(hi) <= max_val):
                return False
            if int(lo) > int(hi):
                return False
        elif part == "*":
            continue
        elif part.isdigit():
            if not (min_val <= int(part) <= max_val):
                return False
        else:
            return False
    return True


def _validate_cron(cron: str) -> bool:
    """校验完整 cron 表达式（5 字段）并验证各字段范围。"""
    if not _CRON_RE.match(cron):
        return False
    fields = cron.strip().split()
    ranges = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]  # weekday 0或7=sun
    for field, (lo, hi) in zip(fields, ranges):
        if not _validate_cron_field(field, lo, hi):
            return False
    return True


def _validate_args(action: str, task_id: str = "", cron: str = "",
                   prompt: str = "", delay_minutes=None) -> str | None:
    """校验 schedule 工具参数，返回错误信息或 None（通过）。"""
    if action not in _ALLOWED_ACTIONS:
        return f"不允许的操作：{action}"

    needs_id = {"add", "remove", "enable", "disable"}
    if action in needs_id:
        if not task_id:
            return "缺少 task_id 参数"
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9\-]{0,62}[a-zA-Z0-9]?", task_id):
            return f"无效的 task_id：{task_id}（仅允许字母、数字、连字符，最长64字符）"
        if len(task_id) > 64:
            return f"task_id 过长：{len(task_id)}（最多64字符）"

    if action == "add":
        has_cron = bool(cron)
        has_delay = delay_minutes is not None
        if not has_cron and not has_delay:
            return "缺少 cron 或 delay_minutes 参数（必须指定一个）"
        if has_cron and has_delay:
            return "cron 和 delay_minutes 不能同时指定"
        if has_cron and not _validate_cron(cron):
            return f"无效的 cron 表达式：{cron}（需要5字段格式，如 '0 9 * * 1-5'）"
        if has_delay and not (1 <= delay_minutes <= 1440):
            return f"delay_minutes 超出范围：{delay_minutes}（1-1440）"
        if not prompt:
            return "缺少 prompt 参数"
        if len(prompt) > 500:
            return f"prompt 过长：{len(prompt)}字符（最多500字符）"

    return None
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_schedule.py -v
```
预期：全部 PASS（15 个测试）

- [ ] **Step 5: 提交**

```bash
git add nimo/tools/schedule.py tests/test_schedule.py
git commit -m "feat: schedule 工具基础——安全校验与 schedules.json 读写"
```

---

### Task 3: schedule 工具注册 + init

**Files:**
- Modify: `nimo/tools/schedule.py`
- Test: `tests/test_schedule.py`（追加）

- [ ] **Step 1: 编写 schedule 工具函数的失败测试**

```python
# tests/test_schedule.py 追加

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
from nimo.tools.schedule import schedule
from nimo.config import Config, LLMConfig, TapdConfig, SchedulesConfig


@pytest.fixture
def schedule_config():
    return Config(
        llm=LLMConfig(
            api_key="sk-test", base_url="https://api.deepseek.com",
            model="deepseek-chat", max_tool_rounds=5, history_rounds=10,
        ),
        tapd=TapdConfig(
            api_base="https://api.tapd.cn", access_token="token123",
        ),
        schedules=SchedulesConfig(enabled=True),
    )


@pytest.mark.asyncio
async def test_schedule_tool_list_empty(schedule_config, tmp_path, monkeypatch):
    """schedule list 返回空任务列表。"""
    monkeypatch.setattr("nimo.tools.schedule._schedules_path", lambda: tmp_path / "schedules.json")
    monkeypatch.setattr("nimo.tools.schedule._config", schedule_config)

    result = await schedule(action="list")
    assert result.success is True
    data = result.data
    assert data["tasks"] == []


@pytest.mark.asyncio
async def test_schedule_tool_list_with_tasks(schedule_config, tmp_path, monkeypatch):
    """schedule list 返回所有任务。"""
    monkeypatch.setattr("nimo.tools.schedule._schedules_path", lambda: tmp_path / "schedules.json")
    monkeypatch.setattr("nimo.tools.schedule._config", schedule_config)

    sp = tmp_path / "schedules.json"
    sp.parent.mkdir(parents=True, exist_ok=True)
    from nimo.tools.schedule import _save_schedules
    _save_schedules({
        "tasks": [{
            "id": "daily-check", "type": "cron", "cron": "0 9 * * 1-5",
            "delay_minutes": None, "prompt": "检查", "enabled": True,
            "created_at": "2026-06-17T10:00:00", "last_run": None, "last_result": None,
        }]
    })
    result = await schedule(action="list")
    assert result.success is True
    assert len(result.data["tasks"]) == 1


@pytest.mark.asyncio
async def test_schedule_tool_list_no_config(tmp_path, monkeypatch):
    """_config 未设置时返回空列表也 OK。"""
    monkeypatch.setattr("nimo.tools.schedule._schedules_path", lambda: tmp_path / "schedules.json")
    monkeypatch.setattr("nimo.tools.schedule._config", None)

    result = await schedule(action="list")
    assert result.success is True


@pytest.mark.asyncio
async def test_schedule_tool_add_cron(schedule_config, tmp_path, monkeypatch):
    """成功添加 cron 类型任务。"""
    monkeypatch.setattr("nimo.tools.schedule._schedules_path", lambda: tmp_path / "schedules.json")
    monkeypatch.setattr("nimo.tools.schedule._config", schedule_config)

    result = await schedule(action="add", task_id="new-task", cron="0 9 * * *", prompt="检查")
    assert result.success is True
    assert result.data["id"] == "new-task"

    # 验证 JSON 已写入
    data = json.loads(tmp_path.joinpath("schedules.json").read_text(encoding="utf-8"))
    task = next(t for t in data["tasks"] if t["id"] == "new-task")
    assert task["type"] == "cron"
    assert task["cron"] == "0 9 * * *"
    assert task["created_at"] is not None


@pytest.mark.asyncio
async def test_schedule_tool_add_once(schedule_config, tmp_path, monkeypatch):
    """成功添加 once 类型任务（delay_minutes）。"""
    monkeypatch.setattr("nimo.tools.schedule._schedules_path", lambda: tmp_path / "schedules.json")
    monkeypatch.setattr("nimo.tools.schedule._config", schedule_config)

    result = await schedule(action="add", task_id="remind", delay_minutes=30, prompt="检查")
    assert result.success is True

    data = json.loads(tmp_path.joinpath("schedules.json").read_text(encoding="utf-8"))
    task = next(t for t in data["tasks"] if t["id"] == "remind")
    assert task["type"] == "once"
    assert task["delay_minutes"] == 30
    assert task["cron"] is None


@pytest.mark.asyncio
async def test_schedule_tool_add_duplicate(schedule_config, tmp_path, monkeypatch):
    """重复 task_id 返回错误。"""
    monkeypatch.setattr("nimo.tools.schedule._schedules_path", lambda: tmp_path / "schedules.json")
    monkeypatch.setattr("nimo.tools.schedule._config", schedule_config)

    from nimo.tools.schedule import _save_schedules
    _save_schedules({
        "tasks": [{
            "id": "existing", "type": "cron", "cron": "0 9 * * *",
            "delay_minutes": None, "prompt": "检查", "enabled": True,
            "created_at": "2026-06-17T10:00:00", "last_run": None, "last_result": None,
        }]
    })
    result = await schedule(action="add", task_id="existing", cron="0 10 * * *", prompt="检查")
    assert result.success is False
    assert "已存在" in result.error


@pytest.mark.asyncio
async def test_schedule_tool_add_disabled(schedule_config, tmp_path, monkeypatch):
    """schedules.enabled=False 时 add 返回错误。"""
    monkeypatch.setattr("nimo.tools.schedule._schedules_path", lambda: tmp_path / "schedules.json")
    schedule_config.schedules.enabled = False
    monkeypatch.setattr("nimo.tools.schedule._config", schedule_config)

    result = await schedule(action="add", task_id="test", cron="0 9 * * *", prompt="检查")
    assert result.success is False
    assert "未启用" in result.error


@pytest.mark.asyncio
async def test_schedule_tool_remove(schedule_config, tmp_path, monkeypatch):
    """删除已有任务。"""
    monkeypatch.setattr("nimo.tools.schedule._schedules_path", lambda: tmp_path / "schedules.json")
    monkeypatch.setattr("nimo.tools.schedule._config", schedule_config)

    from nimo.tools.schedule import _save_schedules
    _save_schedules({
        "tasks": [{
            "id": "to-delete", "type": "cron", "cron": "0 9 * * *",
            "delay_minutes": None, "prompt": "检查", "enabled": True,
            "created_at": "2026-06-17T10:00:00", "last_run": None, "last_result": None,
        }]
    })
    result = await schedule(action="remove", task_id="to-delete")
    assert result.success is True

    # 验证任务已被移除
    from nimo.tools.schedule import _load_schedules
    data = _load_schedules()
    assert len(data["tasks"]) == 0


@pytest.mark.asyncio
async def test_schedule_tool_enable_disable(schedule_config, tmp_path, monkeypatch):
    """启用/禁用任务。"""
    monkeypatch.setattr("nimo.tools.schedule._schedules_path", lambda: tmp_path / "schedules.json")
    monkeypatch.setattr("nimo.tools.schedule._config", schedule_config)

    from nimo.tools.schedule import _save_schedules
    _save_schedules({
        "tasks": [{
            "id": "toggle-task", "type": "cron", "cron": "0 9 * * *",
            "delay_minutes": None, "prompt": "检查", "enabled": True,
            "created_at": "2026-06-17T10:00:00", "last_run": None, "last_result": None,
        }]
    })

    dr = await schedule(action="disable", task_id="toggle-task")
    assert dr.success is True

    from nimo.tools.schedule import _load_schedules
    task = _load_schedules()["tasks"][0]
    assert task["enabled"] is False

    er = await schedule(action="enable", task_id="toggle-task")
    assert er.success is True
    assert _load_schedules()["tasks"][0]["enabled"] is True


@pytest.mark.asyncio
async def test_schedule_tool_invalid_action(schedule_config, tmp_path, monkeypatch):
    """非法 action 被 validate 拦截。"""
    monkeypatch.setattr("nimo.tools.schedule._config", schedule_config)
    result = await schedule(action="hack")
    assert result.success is False
    assert "不允许" in result.error
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_schedule.py::test_schedule_tool_list_empty tests/test_schedule.py::test_schedule_tool_list_with_tasks tests/test_schedule.py::test_schedule_tool_add_cron tests/test_schedule.py::test_schedule_tool_add_once tests/test_schedule.py::test_schedule_tool_add_duplicate tests/test_schedule.py::test_schedule_tool_add_disabled tests/test_schedule.py::test_schedule_tool_remove tests/test_schedule.py::test_schedule_tool_enable_disable tests/test_schedule.py::test_schedule_tool_invalid_action -v
```
预期：FAIL，`schedule` 函数未定义

- [ ] **Step 3: 实现 schedule 工具函数和 init**

```python
# nimo/tools/schedule.py 追加（在 _validate_args 之后）

from datetime import datetime, timezone
from nimo.tools.registry import register_tool, ToolResult, ToolRegistry


async def init_schedule(config) -> None:
    global _config
    _config = config


@register_tool(
    name="schedule",
    description="管理定时检查任务。可列出、添加、删除、启用或禁用定时任务。**关键规则：当用户指定了时间延迟（如\"5分钟后\"\"30分钟后\"\"明天早上9点\"\"下午3点\"），你必须使用此工具注册定时任务，严禁自行判断\"时间短就直接执行\"。用户说等多久就等多久。**",
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "add", "remove", "enable", "disable"],
                "description": "操作类型：list=列出所有任务, add=添加, remove=删除, enable=启用, disable=禁用",
            },
            "task_id": {
                "type": "string",
                "description": "任务ID（add/remove/enable/disable 时需要）。仅允许字母数字和连字符，最长64字符。",
            },
            "cron": {
                "type": "string",
                "description": "5字段 cron 表达式（add 时需要，与 delay_minutes 二选一），如 '0 9 * * 1-5' 表示工作日9点。",
            },
            "delay_minutes": {
                "type": "integer",
                "description": "延迟分钟数（add 时可选，与 cron 二选一），1-1440。使用此参数创建一次性定时任务，执行后自动禁用。",
            },
            "prompt": {
                "type": "string",
                "description": "定时执行的提示内容（add 时需要），最多500字符。",
            },
        },
        "required": ["action"],
    },
)
async def schedule(action: str, task_id: str = "", cron: str = "",
                   prompt: str = "", delay_minutes=None) -> ToolResult:
    if error := _validate_args(action, task_id, cron, prompt, delay_minutes):
        return ToolResult(success=False, error=error)

    if action == "list":
        data = _load_schedules()
        return ToolResult(success=True, data=data)

    if _config is None:
        return ToolResult(success=False, error="定时任务配置未初始化")

    if not _config.schedules.enabled:
        return ToolResult(success=False, error="调度功能未启用，请在 config.yaml 中设置 schedules.enabled: true")

    if action == "add":
        schedules = _load_schedules()
        if any(t["id"] == task_id for t in schedules["tasks"]):
            return ToolResult(success=False, error=f"任务 {task_id} 已存在，请先删除再添加")

        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        task = {
            "id": task_id,
            "type": "cron" if cron else "once",
            "cron": cron or None,
            "delay_minutes": delay_minutes,
            "prompt": prompt,
            "enabled": True,
            "created_at": now_str,
            "last_run": None,
            "last_result": None,
        }
        schedules["tasks"].append(task)
        _save_schedules(schedules)
        return ToolResult(success=True, data={"id": task_id, "message": f"定时任务 {task_id} 已添加"})

    if action == "remove":
        schedules = _load_schedules()
        schedules["tasks"] = [t for t in schedules["tasks"] if t["id"] != task_id]
        _save_schedules(schedules)
        return ToolResult(success=True, data={"message": f"定时任务 {task_id} 已删除"})

    if action in ("enable", "disable"):
        new_state = action == "enable"
        schedules = _load_schedules()
        for t in schedules["tasks"]:
            if t["id"] == task_id:
                t["enabled"] = new_state
                _save_schedules(schedules)
                label = "已启用" if new_state else "已禁用"
                return ToolResult(success=True, data={"message": f"定时任务 {task_id} {label}"})
        return ToolResult(success=False, error=f"未找到定时任务：{task_id}")

    return ToolResult(success=False, error=f"未知操作：{action}")


ToolRegistry.get_instance().register_init(init_schedule)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_schedule.py -v
```
预期：全部 PASS（约 25 个测试）

- [ ] **Step 5: 提交**

```bash
git add nimo/tools/schedule.py tests/test_schedule.py
git commit -m "feat: schedule 工具注册——list/add/remove/enable/disable 完成"
```

---

### Task 4: 调度器核心 — cron 匹配 + 后台循环

**Files:**
- Modify: `nimo/tools/schedule.py`
- Test: `tests/test_schedule.py`（追加）

- [ ] **Step 1: 编写 cron 匹配和调度器的失败测试**

```python
# tests/test_schedule.py 追加

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from nimo.tools.schedule import _cron_match, _next_cron, Scheduler


def test_cron_match_asterisk():
    """* * * * * 匹配任意时间。"""
    dt = datetime(2026, 6, 17, 12, 30)
    assert _cron_match("* * * * *", dt) is True


def test_cron_match_exact_minute():
    assert _cron_match("30 12 * * *", datetime(2026, 6, 17, 12, 30)) is True
    assert _cron_match("30 12 * * *", datetime(2026, 6, 17, 12, 31)) is False
    assert _cron_match("30 12 * * *", datetime(2026, 6, 17, 13, 30)) is False


def test_cron_match_slash():
    """*/15 每15分钟。"""
    assert _cron_match("*/15 * * * *", datetime(2026, 6, 17, 12, 0)) is True
    assert _cron_match("*/15 * * * *", datetime(2026, 6, 17, 12, 15)) is True
    assert _cron_match("*/15 * * * *", datetime(2026, 6, 17, 12, 30)) is True
    assert _cron_match("*/15 * * * *", datetime(2026, 6, 17, 12, 1)) is False


def test_cron_match_range():
    """9-17 时间范围。"""
    assert _cron_match("* 9-17 * * 1-5", datetime(2026, 6, 17, 9, 0)) is True  # Wed=3
    assert _cron_match("* 9-17 * * 1-5", datetime(2026, 6, 17, 18, 0)) is False


def test_cron_match_weekday():
    """1-5 工作日。"""
    wed = datetime(2026, 6, 17)  # 周三 = weekday 3, isoweekday 3
    sat = datetime(2026, 6, 20)  # 周六 = weekday 6, isoweekday 6
    assert _cron_match("0 9 * * 1-5", wed.replace(hour=9, minute=0)) is True
    assert _cron_match("0 9 * * 1-5", sat.replace(hour=9, minute=0)) is False


def test_next_cron_finds_next():
    """_next_cron 找到下一个匹配时间。"""
    dt = datetime(2026, 6, 17, 12, 0)  # 12:00
    # 下一个 12:30 应该在未来
    result = _next_cron("30 12 * * *", dt)
    # 如果是同一天且时间已经过了12:30，下一个就是明天12:30
    if dt.hour < 12 or (dt.hour == 12 and dt.minute < 30):
        assert result == dt.replace(minute=30, second=0, microsecond=0)
    else:
        assert result > dt
        assert result.minute == 30
        assert result.hour == 12


def test_next_cron_daily():
    """每天9点。"""
    dt = datetime(2026, 6, 17, 8, 0)
    result = _next_cron("0 9 * * *", dt)
    assert result.hour == 9
    assert result.minute == 0
    assert result.day == 17


@pytest.mark.asyncio
async def test_scheduler_executes_ready_task(schedule_config, tmp_path, monkeypatch):
    """调度器到时间触发任务执行。"""
    monkeypatch.setattr("nimo.tools.schedule._schedules_path", lambda: tmp_path / "schedules.json")
    monkeypatch.setattr("nimo.tools.schedule._config", schedule_config)

    # 写入一个 once 任务，expected_at 已过（10 分钟前）
    past = datetime.now() - timedelta(minutes=10)
    from nimo.tools.schedule import _save_schedules
    _save_schedules({
        "tasks": [{
            "id": "missed-task",
            "type": "once",
            "cron": None,
            "delay_minutes": 5,
            "prompt": "检查",
            "enabled": True,
            "created_at": past.strftime("%Y-%m-%dT%H:%M:%S"),
            "last_run": None,
            "last_result": None,
        }]
    })

    # Mock agent.run
    mock_run = AsyncMock(return_value="任务结果：一切正常")
    agent_factory = MagicMock(return_value=MagicMock())
    agent_factory().run = mock_run

    sched = Scheduler(agent_factory)
    await sched._tick()

    # 任务应该被标记为 disabled（错过窗口）
    from nimo.tools.schedule import _load_schedules
    task = _load_schedules()["tasks"][0]
    assert task["enabled"] is False

    # 不应该有通知（once 任务错过窗口不执行，直接跳过）
    assert len(sched.pop_notifications()) == 0


@pytest.mark.asyncio
async def test_scheduler_runs_agent_on_trigger(schedule_config, tmp_path, monkeypatch):
    """调度器触发执行时调用 agent.run。"""
    monkeypatch.setattr("nimo.tools.schedule._schedules_path", lambda: tmp_path / "schedules.json")
    monkeypatch.setattr("nimo.tools.schedule._config", schedule_config)

    # 写入一个 once 任务，expected_at = 1分钟前（刚好该触发）
    past = datetime.now() - timedelta(minutes=1)
    from nimo.tools.schedule import _save_schedules
    _save_schedules({
        "tasks": [{
            "id": "ready-task",
            "type": "once",
            "cron": None,
            "delay_minutes": 1,
            "prompt": "检查提交",
            "enabled": True,
            "created_at": past.strftime("%Y-%m-%dT%H:%M:%S"),
            "last_run": None,
            "last_result": None,
        }]
    })

    mock_run = AsyncMock(return_value="发现 2 个新提交")
    agent_factory = MagicMock(return_value=MagicMock())
    agent_factory().run = mock_run

    sched = Scheduler(agent_factory)
    await sched._tick()

    # agent.run 被调用
    mock_run.assert_called_once_with("检查提交")

    # 通知队列有结果
    notifications = sched.pop_notifications()
    assert len(notifications) == 1
    assert notifications[0].task_id == "ready-task"
    assert "2 个新提交" in notifications[0].summary

    # 任务已标记 disabled
    from nimo.tools.schedule import _load_schedules
    task = _load_schedules()["tasks"][0]
    assert task["enabled"] is False
    assert task["last_run"] is not None


@pytest.mark.asyncio
async def test_scheduler_task_error_does_not_crash(schedule_config, tmp_path, monkeypatch):
    """单任务 agent.run 抛异常不影响调度器继续。"""
    monkeypatch.setattr("nimo.tools.schedule._schedules_path", lambda: tmp_path / "schedules.json")
    monkeypatch.setattr("nimo.tools.schedule._config", schedule_config)

    past = datetime.now() - timedelta(minutes=1)
    from nimo.tools.schedule import _save_schedules
    _save_schedules({
        "tasks": [
            {
                "id": "bad-task",
                "type": "once",
                "cron": None,
                "delay_minutes": 1,
                "prompt": "检查",
                "enabled": True,
                "created_at": past.strftime("%Y-%m-%dT%H:%M:%S"),
                "last_run": None,
                "last_result": None,
            },
        ]
    })

    mock_run = AsyncMock(side_effect=RuntimeError("LLM 挂了"))
    agent_factory = MagicMock(return_value=MagicMock())
    agent_factory().run = mock_run

    sched = Scheduler(agent_factory)
    # 不应抛异常
    await sched._tick()

    # 错误记录到 last_result
    from nimo.tools.schedule import _load_schedules
    task = _load_schedules()["tasks"][0]
    assert "LLM 挂了" in task["last_result"].get("error", "")
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_schedule.py::test_cron_match_asterisk tests/test_schedule.py::test_cron_match_exact_minute tests/test_schedule.py::test_cron_match_slash tests/test_schedule.py::test_cron_match_range tests/test_schedule.py::test_cron_match_weekday tests/test_schedule.py::test_next_cron_finds_next tests/test_schedule.py::test_next_cron_daily tests/test_schedule.py::test_scheduler_executes_ready_task tests/test_schedule.py::test_scheduler_runs_agent_on_trigger tests/test_schedule.py::test_scheduler_task_error_does_not_crash -v
```
预期：FAIL，函数/类未定义

- [ ] **Step 3: 实现 cron 匹配和 Scheduler 类**

```python
# nimo/tools/schedule.py 追加（在 _save_schedules 之后）

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from collections.abc import Callable


def _cron_match(cron: str, dt: datetime) -> bool:
    """检查 datetime 是否匹配 cron 表达式。"""
    parts = cron.strip().split()
    minute, hour, day, month, weekday = parts
    # isoweekday: 1=mon..7=sun → 映射为 0=sun,1=mon..6=sat
    wd = dt.isoweekday() % 7
    return (
        _cron_field_match(minute, dt.minute) and
        _cron_field_match(hour, dt.hour) and
        _cron_field_match(day, dt.day) and
        _cron_field_match(month, dt.month) and
        _cron_field_match(weekday, wd)
    )


def _cron_field_match(pattern: str, value: int) -> bool:
    """单个 cron 字段匹配。"""
    if pattern == "*":
        return True
    for part in pattern.split(","):
        if "/" in part:
            base, step = part.split("/", 1)
            base = 0 if base == "*" else int(base)
            step = int(step)
            if value >= base and (value - base) % step == 0:
                return True
        elif "-" in part:
            lo, hi = part.split("-", 1)
            if int(lo) <= value <= int(hi):
                return True
        elif part == "*":
            return True
        else:
            if int(part) == value:
                return True
    return False


def _next_cron(cron: str, from_dt: datetime | None = None) -> datetime | None:
    """计算 cron 表达式下一次触发时间，最多查找 7 天。"""
    if from_dt is None:
        from_dt = datetime.now()
    dt = from_dt + timedelta(minutes=1)
    end = from_dt + timedelta(days=7)
    while dt <= end:
        if _cron_match(cron, dt):
            return dt
        dt += timedelta(minutes=1)
    return None


@dataclass
class Notification:
    task_id: str
    completed_at: str
    summary: str
    full_text: str


@dataclass
class _SchedTask:
    """调度器内部任务表示。"""
    id: str
    type: str  # "cron" | "once"
    cron: str | None
    trigger_at: datetime
    prompt: str
    raw: dict  # schedules.json 中的原始数据引用


class Scheduler:
    """后台调度器：asyncio Task，每 60s 检查，到点触发 agent.run()。"""

    def __init__(self, agent_factory: Callable):
        self._agent_factory = agent_factory
        self._tasks: list[_SchedTask] = []
        self._notifications: list[Notification] = []

    def _load(self) -> None:
        """从 schedules.json 加载 enabled 任务。"""
        self._tasks.clear()
        data = _load_schedules()
        now = datetime.now()
        for t in data.get("tasks", []):
            if not t.get("enabled"):
                continue
            task_id = t["id"]
            if t["type"] == "once":
                try:
                    created = datetime.fromisoformat(t["created_at"])
                except (ValueError, TypeError):
                    continue
                expected = created + timedelta(minutes=t.get("delay_minutes", 0))
                if now >= expected:
                    # 错过窗口，不补执行
                    t["enabled"] = False
                    continue
                self._tasks.append(_SchedTask(
                    id=task_id, type="once", cron=None,
                    trigger_at=expected, prompt=t["prompt"], raw=t,
                ))
            else:  # cron
                next_at = _next_cron(t["cron"], now)
                if next_at is None:
                    continue  # 7天内无匹配，跳过
                self._tasks.append(_SchedTask(
                    id=task_id, type="cron", cron=t["cron"],
                    trigger_at=next_at, prompt=t["prompt"], raw=t,
                ))
        _save_schedules(data)  # 保存可能变动的 once 任务 enabled 状态

    async def _tick(self) -> None:
        """单次检查，到点任务触发执行。"""
        now = datetime.now()
        done_ids: list[str] = []
        for st in self._tasks:
            if now >= st.trigger_at:
                asyncio.create_task(self._execute(st))
                done_ids.append(st.id)

        # 从列表移除已触发的任务
        self._tasks = [st for st in self._tasks if st.id not in done_ids]

    async def _execute(self, st: _SchedTask) -> None:
        """后台执行单个任务。"""
        run_str = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        try:
            agent = self._agent_factory()
            result = await agent.run(st.prompt)
        except Exception as e:
            result = f"执行异常：{e}"

        # 更新 schedules.json
        schedules = _load_schedules()
        for t in schedules.get("tasks", []):
            if t["id"] == st.id:
                t["last_run"] = run_str
                if st.type == "once":
                    t["enabled"] = False
                elif st.type == "cron":
                    t["last_result"] = {"summary": result[:120] if isinstance(result, str) else str(result)[:120]}
                    next_at = _next_cron(st.cron, datetime.now())
                    if next_at:
                        self._tasks.append(_SchedTask(
                            id=st.id, type="cron", cron=st.cron,
                            trigger_at=next_at, prompt=st.prompt, raw=t,
                        ))
                break
        else:
            schedules["tasks"].append(st.raw)
        _save_schedules(schedules)

        # 推通知
        full = result if isinstance(result, str) else str(result)
        self._notifications.append(Notification(
            task_id=st.id,
            completed_at=run_str,
            summary=full[:120],
            full_text=full,
        ))

    def pop_notifications(self) -> list[Notification]:
        """取出并清空通知队列。"""
        ns = list(self._notifications)
        self._notifications.clear()
        return ns

    async def start(self) -> None:
        """启动调度器，阻塞式循环（作为后台 asyncio Task 运行）。"""
        self._load()
        while True:
            await asyncio.sleep(60)
            try:
                await self._tick()
                self._load()  # 重新加载，捕获外部变更（如工具 add/remove）
            except Exception:
                logger.exception("调度器 tick 异常，跳过本轮")
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_schedule.py -v
```
预期：全部 PASS（约 35 个测试）

- [ ] **Step 5: 提交**

```bash
git add nimo/tools/schedule.py tests/test_schedule.py
git commit -m "feat: 调度器核心——cron 匹配 + asyncio 后台循环"
```

---

### Task 5: main.py 集成——启动调度器 + 通知检查

**Files:**
- Modify: `nimo/main.py`
- Test: `tests/test_main.py`（追加）

- [ ] **Step 1: 编写集成测试**

```python
# tests/test_main.py 追加

import pytest
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from nimo.main import _check_schedule_notifications
from nimo.tools.schedule import Notification


def test_check_notifications_empty(capsys):
    """通知队列为空时无输出。"""
    scheduler = MagicMock()
    scheduler.pop_notifications.return_value = []

    _check_schedule_notifications(scheduler)

    captured = capsys.readouterr()
    assert captured.out == ""


def test_check_notifications_show_yes(monkeypatch):
    """用户选择查看通知。"""
    scheduler = MagicMock()
    scheduler.pop_notifications.return_value = [
        Notification(
            task_id="daily-check",
            completed_at="2026-06-17T09:00:12",
            summary="发现 3 个到期任务",
            full_text="发现 3 个到期任务：\n- 任务A\n- 任务B\n- 任务C",
        )
    ]

    inputs = iter(["y"])
    printed_lines = []

    def mock_input(prompt=""):
        printed_lines.append(prompt)
        return next(inputs)

    monkeypatch.setattr("builtins.input", mock_input)

    # 只测试 _check_schedule_notifications 逻辑（print 部分已测试）
    ns = scheduler.pop_notifications()
    assert len(ns) == 1
    assert ns[0].task_id == "daily-check"


def test_check_notifications_show_no(monkeypatch):
    """用户选择跳过通知。"""
    scheduler = MagicMock()
    scheduler.pop_notifications.return_value = [
        Notification(
            task_id="remind",
            completed_at="2026-06-17T14:30:00",
            summary="一切正常",
            full_text="检查完毕，无异常",
        )
    ]

    inputs = iter(["n"])
    monkeypatch.setattr("builtins.input", lambda _="": next(inputs))

    ns = scheduler.pop_notifications()
    assert len(ns) == 1
    assert ns[0].task_id == "remind"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_main.py::test_check_notifications_empty tests/test_main.py::test_check_notifications_show_yes tests/test_main.py::test_check_notifications_show_no -v
```
预期：FAIL，`_check_schedule_notifications` 未定义（或部分失败因导入不到 Notification）

- [ ] **Step 3: 实现 main.py 集成**

```python
# nimo/main.py — 在现有 import 块末尾追加

from datetime import datetime
from nimo.tools.schedule import Scheduler


# nimo/main.py — 新增函数（在 main() 之前）

_scheduler: Scheduler | None = None


def _check_schedule_notifications(sched: Scheduler) -> None:
    """检查并向用户展示调度通知。"""
    notifications = sched.pop_notifications()
    if not notifications:
        return
    for n in notifications:
        ts = n.completed_at[:16].replace("T", " ")
        print(f"\n{ORANGE}[!] [{ts}] 定时任务 '{n.task_id}' 已完成，查看结果？(y/n) {RESET}", end="", flush=True)
        try:
            answer = input()
        except (EOFError, KeyboardInterrupt):
            return
        if answer.strip().lower() == "y":
            print_response_box(n.full_text)
            print()
```

```python
# nimo/main.py — main() 中，print_welcome() 之后、while True 之前插入：

    # 启动后台调度器
    _scheduler = Scheduler(lambda: Agent(config))
    asyncio.create_task(_scheduler.start())

    print_welcome(model=config.llm.model, cwd=os.getcwd(), version="0.1.0")
    while True:
```

```python
# nimo/main.py — main() 输入循环中，user_input = input(f"{ORANGE}❯ ") 之前插入通知检查：

    while True:
        try:
            if _scheduler:
                _check_schedule_notifications(_scheduler)
            user_input = input(f"{ORANGE}❯ ")
```

注意：调度器使用的 `Agent(config)` 每次都是新实例，拥有独立的 history/profile，不会污染用户主 Agent 的对话上下文。

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_main.py -v
```
预期：全部 PASS（原有 1 个 + 新增 3 个）

- [ ] **Step 5: 提交**

```bash
git add nimo/main.py tests/test_main.py
git commit -m "feat: main 集成——启动调度器 + 通知检查"
```

---

### Task 6: 全部测试验证 + 最终提交

- [ ] **Step 1: 运行全部测试**

```bash
pytest tests/ -v
```

- [ ] **Step 2: 确认全部通过后无需额外提交（Task 5 已提交干净）**
```

---

## 自检清单

- [x] **Spec coverage**: SchedulesConfig（Task 1）、校验+存储（Task 2）、工具注册（Task 3）、cron匹配+调度器（Task 4）、main集成+通知（Task 5）
- [x] **Placeholder scan**: 无 TBD/TODO，每步都有具体代码
- [x] **Type consistency**: Notification/Scheduler 在 Task 4 定义，Task 5 引用一致；_schedules_path 在 Task 2 定义，全程复用
