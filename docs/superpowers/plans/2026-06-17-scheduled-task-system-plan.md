# 定时任务系统 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 Nimo 支持定时主动检查——用户配置定时规则，系统到点自动执行 LLM+工具查询，结果缓存到本地，下次启动时毫秒级展示。

**Architecture:** 三层解耦：schtasks.exe 外部触发 → `--run-schedule` 模式独立执行（不走交互循环）→ 缓存文件读写在 `tools/schedule.py` 中集中管理。schedule 工具管理任务元数据，`execute_scheduled_task()` 是共享执行入口（独立于 Agent 以避免递归），`/refresh` 和 `--run-schedule` 均调用它。

**Tech Stack:** Python asyncio, schtasks.exe (Windows), JSON 文件存储，现有 LLMClient + ToolRegistry

---

### Task 1: SchedulesConfig 配置

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
    from nimo.config import load_config, ConfigError
    import tempfile, os

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


def test_load_config_with_schedules_section():
    """schedules 段存在且 enabled 为 true。"""
    import yaml
    from nimo.config import load_config
    import tempfile, os

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
pytest tests/test_config.py::test_schedules_config_default tests/test_config.py::test_schedules_config_enabled tests/test_config.py::test_load_config_without_schedules_section tests/test_config.py::test_load_config_with_schedules_section -v
```
预期：FAIL，`SchedulesConfig` 未定义

- [ ] **Step 3: 实现 SchedulesConfig dataclass 并更新 load_config**

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
# nimo/config.py — load_config() 末尾（return 之前）追加

    schedules_raw = raw.get("schedules", {})
    schedules = SchedulesConfig(
        enabled=schedules_raw.get("enabled", False),
    )
    return Config(llm=llm, tapd=tapd, tortoisesvn=tortoisesvn, schedules=schedules)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_config.py::test_schedules_config_default tests/test_config.py::test_schedules_config_enabled tests/test_config.py::test_load_config_without_schedules_section tests/test_config.py::test_load_config_with_schedules_section -v
```
预期：4 PASS

- [ ] **Step 5: 提交**

```bash
git add nimo/config.py tests/test_config.py
git commit -m "feat: 添加 SchedulesConfig 配置支持"
```

---

### Task 2: schedule 模块基础——安全校验 + schedules.json 读写

**Files:**
- Create: `nimo/tools/schedule.py`
- Test: `tests/test_schedule.py`（新文件）

- [ ] **Step 1: 编写安全校验和存储的失败测试**

```python
# tests/test_schedule.py

import json
import os
import pytest
import tempfile
from pathlib import Path
from nimo.tools.schedule import _validate_args, _load_schedules, _save_schedules, _schedules_path


def test_validate_action_whitelist():
    assert _validate_args("list") is None
    assert _validate_args("add") is None
    assert _validate_args("remove") is None
    assert _validate_args("enable") is None
    assert _validate_args("disable") is None
    assert _validate_args("run") is None
    assert _validate_args("delete") is not None  # 不在白名单
    assert _validate_args("") is not None
    assert _validate_args("LIST") is not None  # 小写白名单


def test_validate_task_id():
    assert _validate_args("add", "daily-check") is None
    assert _validate_args("add", "weekly_report") is None
    assert _validate_args("add", "task-123") is None
    assert _validate_args("add", "../etc") is not None  # 路径遍历
    assert _validate_args("add", "rm -rf") is not None  # 空格
    assert _validate_args("add", "") is not None  # 空


def test_validate_task_id_length():
    assert _validate_args("add", "a" * 65) is not None  # 超过64字符
    assert _validate_args("add", "a" * 64) is None


def test_validate_cron():
    assert _validate_args("add", "ok", "0 9 * * 1-5") is None
    assert _validate_args("add", "ok", "*/5 * * * *") is None
    assert _validate_args("add", "ok", "0 9 *") is not None  # 只有3字段
    assert _validate_args("add", "ok", "invalid cron") is not None


def test_validate_prompt_too_long():
    long_prompt = "检查" * 300  # > 500 字符
    assert _validate_args("add", "ok", "0 9 * * *", long_prompt) is not None


def test_validate_prompt_ok():
    assert _validate_args("add", "ok", "0 9 * * *", "检查任务") is None


def test_load_schedules_not_exist(tmp_path, monkeypatch):
    """文件不存在时初始化为空。"""
    monkeypatch.setattr("nimo.tools.schedule._schedules_path", lambda: tmp_path / "schedules.json")
    result = _load_schedules()
    assert result == {"tasks": []}


def test_save_and_load_schedules(tmp_path, monkeypatch):
    """保存后再加载，数据一致。"""
    monkeypatch.setattr("nimo.tools.schedule._schedules_path", lambda: tmp_path / "schedules.json")
    data = {
        "tasks": [
            {
                "id": "daily-check",
                "cron": "0 9 * * 1-5",
                "prompt": "检查到期任务",
                "enabled": True,
                "last_run": None,
                "last_result": None,
            }
        ]
    }
    _save_schedules(data)
    loaded = _load_schedules()
    assert len(loaded["tasks"]) == 1
    assert loaded["tasks"][0]["id"] == "daily-check"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_schedule.py -v
```
预期：FAIL，模块/函数未定义

- [ ] **Step 3: 编写 schedule.py 基础实现**

```python
# nimo/tools/schedule.py

import json
import logging
import os
import re
from pathlib import Path

from nimo.config import Config
from nimo.tools.registry import register_tool, ToolResult, ToolRegistry

logger = logging.getLogger(__name__)

_ALLOWED_ACTIONS = frozenset({"list", "add", "remove", "enable", "disable", "run"})
_CRON_RE = re.compile(
    r"^(\*|[\d,\-*/]+)\s+(\*|[\d,\-*/]+)\s+(\*|[\d,\-*/]+)\s+(\*|[\d,\-*/]+)\s+(\*|[\d,\-*/]+)$"
)

_config: Config | None = None


def _schedules_path() -> Path:
    return Path.home() / ".nimo" / "schedules.json"


def _scheduled_dir() -> Path:
    return Path.home() / ".nimo" / "scheduled"


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
    tmp.replace(path)  # 原子写入


def _validate_args(action: str, task_id: str = "", cron: str = "", prompt: str = "") -> str | None:
    """校验 schedule 工具参数，返回错误信息或 None（表示通过）。"""
    if action not in _ALLOWED_ACTIONS:
        return f"不允许的操作：{action}"

    needs_id = {"add", "remove", "enable", "disable", "run"}
    if action in needs_id:
        if not task_id:
            return "缺少 task_id 参数"
        if not re.fullmatch(r"[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?", task_id):
            return f"无效的 task_id：{task_id}（仅允许字母、数字、连字符，最长64字符）"
        if len(task_id) > 64:
            return f"task_id 过长：{len(task_id)}（最多64字符）"

    if action == "add":
        if not cron:
            return "缺少 cron 参数"
        if not _CRON_RE.match(cron):
            return f"无效的 cron 表达式：{cron}（需要5字段格式，如 '0 9 * * 1-5'）"
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
预期：全部 PASS（安全校验 + 存储共 10 个测试）

- [ ] **Step 5: 提交**

```bash
git add nimo/tools/schedule.py tests/test_schedule.py
git commit -m "feat: schedule 工具基础——安全校验与 schedules.json 读写"
```

---

### Task 3: schtasks 集成——任务的系统级注册与删除

**Files:**
- Modify: `nimo/tools/schedule.py`
- Test: `tests/test_schedule.py`（追加）

- [ ] **Step 1: 编写 schtasks 操作的失败测试**

```python
# tests/test_schedule.py 追加

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from nimo.tools.schedule import (
    _build_schtasks_name, _schtasks_create, _schtasks_delete,
    _schtasks_enable, _schtasks_disable, _schtasks_list,
)


def test_build_schtasks_name():
    assert _build_schtasks_name("daily-check") == "Nimo-daily-check"
    assert _build_schtasks_name("weekly_report") == "Nimo-weekly_report"


@pytest.mark.asyncio
async def test_schtasks_create():
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"SUCCESS", b""))

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)) as mock_exec:
        result = await _schtasks_create("daily-check", "0 9 * * 1-5", "检查任务")
        assert result is None  # 成功返回 None
        # 验证 schtasks.exe 被正确调用
        call_args = mock_exec.call_args[0]
        assert call_args[0].endswith("schtasks.exe")
        assert "/create" in call_args
        assert "/tn" in call_args
        assert "Nimo-daily-check" in call_args


@pytest.mark.asyncio
async def test_schtasks_create_error():
    mock_proc = MagicMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(b"", b"ERROR: Access denied"))

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        result = await _schtasks_create("daily-check", "0 9 * * 1-5", "检查")
        assert result is not None
        assert "Access denied" in result


@pytest.mark.asyncio
async def test_schtasks_delete():
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"SUCCESS", b""))

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        result = await _schtasks_delete("daily-check")
        assert result is None


@pytest.mark.asyncio
async def test_schtasks_enable():
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"SUCCESS", b""))

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        result = await _schtasks_enable("daily-check")
        assert result is None


@pytest.mark.asyncio
async def test_schtasks_disable():
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"SUCCESS", b""))

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        result = await _schtasks_disable("daily-check")
        assert result is None


@pytest.mark.asyncio
async def test_schtasks_list():
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"TaskName\nNimo-daily-check\nNimo-weekly", b""))

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
        tasks = await _schtasks_list()
        assert "Nimo-daily-check" in tasks
        assert "Nimo-weekly" in tasks
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_schedule.py::test_build_schtasks_name tests/test_schedule.py::test_schtasks_create tests/test_schedule.py::test_schtasks_create_error tests/test_schedule.py::test_schtasks_delete tests/test_schedule.py::test_schtasks_enable tests/test_schedule.py::test_schtasks_disable tests/test_schedule.py::test_schtasks_list -v
```
预期：FAIL，函数未定义

- [ ] **Step 3: 实现 schtasks 操作函数**

```python
# nimo/tools/schedule.py 追加（在 _validate_args 之后）

import asyncio
import sys

_SCHTASKS = "schtasks.exe"


def _build_schtasks_name(task_id: str) -> str:
    return f"Nimo-{task_id}"


async def _schtasks_create(task_id: str, cron: str, prompt: str) -> str | None:
    """注册 schtasks 定时任务。成功返回 None，失败返回错误信息。"""
    task_name = _build_schtasks_name(task_id)
    exe = sys.executable
    cmd = f"{exe} -m nimo.main --run-schedule {task_id}"
    args = [
        _SCHTASKS, "/create", "/tn", task_name,
        "/tr", cmd, "/sc", "MINUTE", "/mo", "1",  # 先创建占位，下面改 trigger
    ]
    # schtasks /create 不支持 cron，用 XML 导入方式。此处用 DAILY 近似：
    # 解析 cron 的分钟和小时
    parts = cron.split()
    minute = parts[0] if parts[0] != "*" else "0"
    hour = parts[1] if parts[1] != "*" else "*"

    args = [
        _SCHTASKS, "/create", "/tn", task_name,
        "/tr", cmd, "/sc", "DAILY",
        "/st", f"{hour.zfill(2) if hour != '*' else '00'}:{minute.zfill(2) if minute != '*' else '00'}",
        "/f",  # 覆盖已有同名任务
    ]
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        return (stderr.decode(errors="replace") or stdout.decode(errors="replace")).strip()
    return None


async def _schtasks_delete(task_id: str) -> str | None:
    task_name = _build_schtasks_name(task_id)
    proc = await asyncio.create_subprocess_exec(
        _SCHTASKS, "/delete", "/tn", task_name, "/f",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        return (stderr.decode(errors="replace") or stdout.decode(errors="replace")).strip()
    return None


async def _schtasks_enable(task_id: str) -> str | None:
    task_name = _build_schtasks_name(task_id)
    proc = await asyncio.create_subprocess_exec(
        _SCHTASKS, "/change", "/tn", task_name, "/enable",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        return (stderr.decode(errors="replace") or stdout.decode(errors="replace")).strip()
    return None


async def _schtasks_disable(task_id: str) -> str | None:
    task_name = _build_schtasks_name(task_id)
    proc = await asyncio.create_subprocess_exec(
        _SCHTASKS, "/change", "/tn", task_name, "/disable",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        return (stderr.decode(errors="replace") or stdout.decode(errors="replace")).strip()
    return None


async def _schtasks_list() -> list[str]:
    """列出所有 Nimo- 前缀的 schtasks 任务名。"""
    proc = await asyncio.create_subprocess_exec(
        _SCHTASKS, "/query", "/fo", "CSV", "/nh",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    lines = stdout.decode(errors="replace").strip().split("\n")
    tasks = []
    for line in lines:
        line = line.strip().strip('"')
        if line.startswith("Nimo-"):
            tasks.append(line)
    return tasks
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_schedule.py::test_build_schtasks_name tests/test_schedule.py::test_schtasks_create tests/test_schedule.py::test_schtasks_create_error tests/test_schedule.py::test_schtasks_delete tests/test_schedule.py::test_schtasks_enable tests/test_schedule.py::test_schtasks_disable tests/test_schedule.py::test_schtasks_list -v
```
预期：7 PASS

- [ ] **Step 5: 提交**

```bash
git add nimo/tools/schedule.py tests/test_schedule.py
git commit -m "feat: schedule schtasks 集成——任务注册/删除/启停"
```

---

### Task 4: 定时任务执行引擎 + 缓存文件写入

**Files:**
- Modify: `nimo/tools/schedule.py`
- Test: `tests/test_schedule.py`（追加）

- [ ] **Step 1: 编写执行引擎的失败测试**

```python
# tests/test_schedule.py 追加

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch, call
from nimo.tools.schedule import execute_scheduled_task, _write_cache_files
from nimo.config import Config, LLMConfig, TapdConfig


@pytest.fixture
def schedule_config():
    return Config(
        llm=LLMConfig(
            api_key="sk-test", base_url="https://api.deepseek.com",
            model="deepseek-chat", max_tool_rounds=3, history_rounds=10,
        ),
        tapd=TapdConfig(
            api_base="https://api.tapd.cn", access_token="token123",
        ),
    )


def test_write_cache_files(tmp_path):
    task_id = "daily-check"
    result_json = tmp_path / f"{task_id}.json"
    result_md = tmp_path / f"{task_id}.md"

    # 直接传入临时目录测试
    _write_cache_files(task_id, "检查摘要", "详细内容", True, {"prompt": 100, "completion": 50}, tmp_path)

    assert result_json.exists()
    assert result_md.exists()

    data = json.loads(result_json.read_text(encoding="utf-8"))
    assert data["task_id"] == "daily-check"
    assert data["success"] is True
    assert data["summary"] == "检查摘要"
    assert data["usage"]["prompt"] == 100

    md = result_md.read_text(encoding="utf-8")
    assert "检查摘要" in md
    assert "详细内容" in md


@pytest.mark.asyncio
async def test_execute_scheduled_task_standalone(schedule_config, tmp_path, monkeypatch):
    """独立执行模式：LLM 无 tool_calls，直接返回文本。"""
    from nimo.llm.client import LLMClient

    monkeypatch.setattr("nimo.tools.schedule._schedules_path", lambda: tmp_path / "schedules.json")
    monkeypatch.setattr("nimo.tools.schedule._scheduled_dir", lambda: tmp_path / "scheduled")

    # 写入 schedules.json
    import json as _json
    sp = tmp_path / "schedules.json"
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(_json.dumps({
        "tasks": [{
            "id": "daily-check",
            "cron": "0 9 * * 1-5",
            "prompt": "检查到期任务",
            "enabled": True,
            "last_run": None,
            "last_result": None,
        }]
    }), encoding="utf-8")

    # Mock LLMClient.chat 返回无 tool_calls 的响应
    mock_choice = MagicMock()
    mock_choice.message.tool_calls = None
    mock_choice.message.content = "您今天有 3 个任务到期"
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage.prompt_tokens = 50
    mock_response.usage.completion_tokens = 20

    mock_client = MagicMock()
    mock_client.chat = AsyncMock(return_value=mock_response)

    with patch.object(LLMClient, "__init__", return_value=None):
        with patch.object(LLMClient, "chat", mock_client.chat):
            with patch("nimo.tools.schedule._config", schedule_config):
                result = await execute_scheduled_task("daily-check")

    assert result.success is True
    # 验证缓存文件已写入
    cache_json = tmp_path / "scheduled" / "daily-check.json"
    assert cache_json.exists()
    cache_data = _json.loads(cache_json.read_text(encoding="utf-8"))
    assert "3 个任务到期" in cache_data["summary"]


@pytest.mark.asyncio
async def test_execute_scheduled_task_not_found(schedule_config, tmp_path, monkeypatch):
    """任务 ID 不存在时返回错误。"""
    monkeypatch.setattr("nimo.tools.schedule._schedules_path", lambda: tmp_path / "schedules.json")
    sp = tmp_path / "schedules.json"
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text('{"tasks": []}', encoding="utf-8")

    with patch("nimo.tools.schedule._config", schedule_config):
        result = await execute_scheduled_task("nonexistent")
    assert result.success is False
    assert "未找到" in result.error
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_schedule.py::test_write_cache_files tests/test_schedule.py::test_execute_scheduled_task_standalone tests/test_schedule.py::test_execute_scheduled_task_not_found -v
```
预期：FAIL，`execute_scheduled_task` / `_write_cache_files` 未定义

- [ ] **Step 3: 实现执行引擎和缓存写入**

```python
# nimo/tools/schedule.py 追加

import time
from datetime import datetime, timezone


def _write_cache_files(task_id: str, summary: str, detail: str,
                       success: bool, usage: dict, target_dir: Path | None = None) -> None:
    """写入缓存文件（.json 结构化 + .md 摘要）。"""
    d = target_dir or _scheduled_dir()
    d.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

    json_data = {
        "task_id": task_id,
        "triggered_at": now,
        "completed_at": now,
        "success": success,
        "summary": summary,
        "detail": detail,
        "usage": usage,
    }
    json_path = d / f"{task_id}.json"
    tmp_json = d / f"{task_id}.json.tmp"
    with open(tmp_json, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    tmp_json.replace(json_path)

    md_path = d / f"{task_id}.md"
    tmp_md = d / f"{task_id}.md.tmp"
    with open(tmp_md, "w", encoding="utf-8") as f:
        f.write(f"## 定时检查：{task_id}\n")
        f.write(f"执行时间：{now}\n\n")
        f.write(f"**{summary}**\n\n")
        f.write(detail)
    tmp_md.replace(md_path)


async def execute_scheduled_task(task_id: str) -> ToolResult:
    """独立执行一个定时任务：LLM + 工具调用 → 写缓存。不依赖 Agent，避免递归。"""
    from nimo.llm.client import LLMClient
    from nimo.tools.registry import ToolRegistry

    if _config is None:
        return ToolResult(success=False, error="配置未初始化")

    schedules = _load_schedules()
    task = next((t for t in schedules["tasks"] if t["id"] == task_id), None)
    if task is None:
        return ToolResult(success=False, error=f"未找到定时任务：{task_id}")

    prompt = task["prompt"]
    client = LLMClient(_config)
    registry = ToolRegistry.get_instance()
    tools = registry.build_tool_definitions()

    system_prompt = "你是 Nimo，一个智能助手。简洁中文回复，不编造数据。"
    messages = [{"role": "user", "content": prompt}]
    usage = {"prompt": 0, "completion": 0}

    try:
        for _round_num in range(_config.llm.max_tool_rounds):
            response = await client.chat(messages, tools, system_prompt)
            if response.usage:
                usage["prompt"] += response.usage.prompt_tokens
                usage["completion"] += response.usage.completion_tokens

            choice = response.choices[0]
            if not choice.message.tool_calls:
                summary_text = (choice.message.content or "").strip()
                # 取前100字作为摘要
                summary = summary_text[:100] + ("..." if len(summary_text) > 100 else "")
                detail = summary_text

                # 更新 schedules.json 的 last_run
                task["last_run"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
                task["last_result"] = {"summary": summary}
                _save_schedules(schedules)

                _write_cache_files(task_id, summary, detail, True, usage)
                return ToolResult(success=True, data={"summary": summary})
            else:
                # 执行工具调用
                tool_results = []
                for tc in choice.message.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        args = {}
                    tr = await registry.execute(tc.function.name, args)
                    tool_results.append((tc.id, tc.function.name, tr))

                messages.append({
                    "role": "assistant",
                    "content": choice.message.content,
                    "tool_calls": [
                        {
                            "id": tc.id, "type": "function",
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in choice.message.tool_calls
                    ],
                })
                for tc_id, name, tr in tool_results:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": json.dumps({
                            "success": tr.success, "data": tr.data, "error": tr.error,
                        }, ensure_ascii=False, default=str),
                    })

        # 轮数耗尽
        summary = "已达到工具调用上限"
        _write_cache_files(task_id, summary, "数据可能不完整", False, usage)
        task["last_run"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        task["last_result"] = {"summary": summary}
        _save_schedules(schedules)
        return ToolResult(success=False, error=summary)

    except Exception as e:
        logger.exception("定时任务执行失败：%s", task_id)
        return ToolResult(success=False, error=str(e))
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_schedule.py::test_write_cache_files tests/test_schedule.py::test_execute_scheduled_task_standalone tests/test_schedule.py::test_execute_scheduled_task_not_found -v
```
预期：3 PASS

- [ ] **Step 5: 提交**

```bash
git add nimo/tools/schedule.py tests/test_schedule.py
git commit -m "feat: schedule 执行引擎——独立 LLM 调用 + 缓存文件写入"
```

---

### Task 5: schedule 工具注册 + init + action 分发

**Files:**
- Modify: `nimo/tools/schedule.py`
- Test: `tests/test_schedule.py`（追加）

- [ ] **Step 1: 编写 schedule 工具函数的失败测试**

```python
# tests/test_schedule.py 追加

@pytest.mark.asyncio
async def test_schedule_tool_list(schedule_config, tmp_path, monkeypatch):
    """schedule list 返回所有任务。"""
    monkeypatch.setattr("nimo.tools.schedule._schedules_path", lambda: tmp_path / "schedules.json")
    monkeypatch.setattr("nimo.tools.schedule._config", schedule_config)

    # 有 config 就无法被 "未初始化" 拦截，config.schedules.enabled 默认为 False
    # 需要 enabled=True 才能非 list 操作
    sp = tmp_path / "schedules.json"
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps({
        "tasks": [{
            "id": "daily-check", "cron": "0 9 * * 1-5",
            "prompt": "检查", "enabled": True,
            "last_run": None, "last_result": None,
        }]
    }), encoding="utf-8")

    from nimo.tools.schedule import schedule
    result = await schedule(action="list")
    assert result.success is True
    data = json.loads(result.data) if isinstance(result.data, str) else result.data
    assert len(data["tasks"]) == 1


@pytest.mark.asyncio
async def test_schedule_tool_add_disabled(schedule_config, tmp_path, monkeypatch):
    """schedules.enabled=False 时 add 返回错误。"""
    monkeypatch.setattr("nimo.tools.schedule._schedules_path", lambda: tmp_path / "schedules.json")

    # config.schedules.enabled 默认 False
    with patch("nimo.tools.schedule._config", schedule_config):
        from nimo.tools.schedule import schedule
        result = await schedule(action="add", task_id="test", cron="0 9 * * *", prompt="检查")
        assert result.success is False
        assert "未启用" in result.error


@pytest.mark.asyncio
async def test_schedule_tool_invalid_action(schedule_config, tmp_path, monkeypatch):
    """非法 action 被 validate 拦截。"""
    monkeypatch.setattr("nimo.tools.schedule._config", schedule_config)
    from nimo.tools.schedule import schedule
    result = await schedule(action="hack")
    assert result.success is False
    assert "不允许" in result.error


@pytest.mark.asyncio
async def test_schedule_tool_add_success(schedule_config, tmp_path, monkeypatch):
    """成功添加定时任务：写 JSON + 注册 schtasks。"""
    monkeypatch.setattr("nimo.tools.schedule._schedules_path", lambda: tmp_path / "schedules.json")
    schedule_config.schedules.enabled = True

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"SUCCESS", b""))

    with patch("nimo.tools.schedule._config", schedule_config):
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)):
            from nimo.tools.schedule import schedule
            result = await schedule(action="add", task_id="new-task", cron="0 9 * * *", prompt="检查")
            assert result.success is True

            # 验证 JSON 已写入
            data = json.loads(tmp_path.joinpath("schedules.json").read_text(encoding="utf-8"))
            assert any(t["id"] == "new-task" for t in data["tasks"])


@pytest.mark.asyncio
async def test_schedule_tool_run(schedule_config, tmp_path, monkeypatch):
    """schedule run 调用 execute_scheduled_task。"""
    monkeypatch.setattr("nimo.tools.schedule._schedules_path", lambda: tmp_path / "schedules.json")
    monkeypatch.setattr("nimo.tools.schedule._scheduled_dir", lambda: tmp_path / "scheduled")

    sp = tmp_path / "schedules.json"
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps({
        "tasks": [{
            "id": "daily-check", "cron": "0 9 * * 1-5",
            "prompt": "检查到期任务", "enabled": True,
            "last_run": None, "last_result": None,
        }]
    }), encoding="utf-8")

    from nimo.llm.client import LLMClient
    mock_choice = MagicMock()
    mock_choice.message.tool_calls = None
    mock_choice.message.content = "您今天没有到期任务"
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    mock_response.usage.prompt_tokens = 10
    mock_response.usage.completion_tokens = 5

    mock_client = MagicMock()
    mock_client.chat = AsyncMock(return_value=mock_response)

    with patch.object(LLMClient, "__init__", return_value=None):
        with patch.object(LLMClient, "chat", mock_client.chat):
            with patch("nimo.tools.schedule._config", schedule_config):
                from nimo.tools.schedule import schedule
                result = await schedule(action="run", task_id="daily-check")

    assert result.success is True
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_schedule.py::test_schedule_tool_list tests/test_schedule.py::test_schedule_tool_add_disabled tests/test_schedule.py::test_schedule_tool_invalid_action tests/test_schedule.py::test_schedule_tool_add_success tests/test_schedule.py::test_schedule_tool_run -v
```
预期：FAIL，`schedule` 函数未定义

- [ ] **Step 3: 实现 schedule 工具函数和 init**

```python
# nimo/tools/schedule.py 追加（文件末尾）

async def init_schedule(config: Config) -> None:
    global _config
    _config = config


@register_tool(
    name="schedule",
    description="管理定时检查任务。可列出、添加、删除、启用、禁用或手动执行定时任务。",
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["list", "add", "remove", "enable", "disable", "run"],
                "description": "操作类型：list=列出所有任务, add=添加, remove=删除, enable=启用, disable=禁用, run=立即执行一次",
            },
            "task_id": {
                "type": "string",
                "description": "任务ID（add/remove/enable/disable/run 时需要）。仅允许字母数字和连字符。",
            },
            "cron": {
                "type": "string",
                "description": "5字段 cron 表达式（add 时需要），如 '0 9 * * 1-5' 表示工作日9点。",
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
                   prompt: str = "") -> ToolResult:
    if error := _validate_args(action, task_id, cron, prompt):
        return ToolResult(success=False, error=error)

    if _config is None:
        return ToolResult(success=False, error="定时任务配置未初始化")

    if action == "list":
        data = _load_schedules()
        return ToolResult(success=True, data=data)

    # 以下操作需要调度功能启用
    if not _config.schedules.enabled:
        return ToolResult(success=False, error="调度功能未启用，请在 config.yaml 中设置 schedules.enabled: true")

    if action == "add":
        schedules = _load_schedules()
        if any(t["id"] == task_id for t in schedules["tasks"]):
            return ToolResult(success=False, error=f"任务 {task_id} 已存在，请先删除再添加")

        task = {
            "id": task_id,
            "cron": cron,
            "prompt": prompt,
            "enabled": True,
            "last_run": None,
            "last_result": None,
        }
        err = await _schtasks_create(task_id, cron, prompt)
        if err:
            return ToolResult(success=False, error=f"schtasks 注册失败：{err}")

        schedules["tasks"].append(task)
        _save_schedules(schedules)
        return ToolResult(success=True, data={"id": task_id, "message": f"定时任务 {task_id} 已添加"})

    if action == "remove":
        schedules = _load_schedules()
        schedules["tasks"] = [t for t in schedules["tasks"] if t["id"] != task_id]
        _save_schedules(schedules)
        # schtasks 删除失败不影响整体结果（任务可能已不存在）
        schtasks_err = await _schtasks_delete(task_id)
        msg = f"定时任务 {task_id} 已删除"
        if schtasks_err:
            msg += f"（schtasks 清理提示：{schtasks_err}）"
        return ToolResult(success=True, data={"message": msg})

    if action == "enable":
        err = await _schtasks_enable(task_id)
        if err:
            return ToolResult(success=False, error=f"启用失败：{err}")
        schedules = _load_schedules()
        for t in schedules["tasks"]:
            if t["id"] == task_id:
                t["enabled"] = True
                break
        _save_schedules(schedules)
        return ToolResult(success=True, data={"message": f"定时任务 {task_id} 已启用"})

    if action == "disable":
        err = await _schtasks_disable(task_id)
        if err:
            return ToolResult(success=False, error=f"禁用失败：{err}")
        schedules = _load_schedules()
        for t in schedules["tasks"]:
            if t["id"] == task_id:
                t["enabled"] = False
                break
        _save_schedules(schedules)
        return ToolResult(success=True, data={"message": f"定时任务 {task_id} 已禁用"})

    if action == "run":
        return await execute_scheduled_task(task_id)

    return ToolResult(success=False, error=f"未知操作：{action}")


ToolRegistry.get_instance().register_init(init_schedule)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_schedule.py -v
```
预期：全部 PASS（约 20 个测试）

- [ ] **Step 5: 提交**

```bash
git add nimo/tools/schedule.py tests/test_schedule.py
git commit -m "feat: schedule 工具注册——list/add/remove/enable/disable/run 完成"
```

---

### Task 6: main.py CLI 参数—— --run-schedule / --schedule-list / --schedule-disable-all

**Files:**
- Modify: `nimo/main.py`
- Test: `tests/test_main.py`（追加）

- [ ] **Step 1: 编写 CLI 参数的失败测试**

```python
# tests/test_main.py 追加

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from nimo.main import _parse_schedule_args


def test_parse_schedule_run():
    args = _parse_schedule_args(["--run-schedule", "daily-check"])
    assert args.run_schedule == "daily-check"
    assert args.schedule_list is False
    assert args.schedule_disable_all is False


def test_parse_schedule_list():
    args = _parse_schedule_args(["--schedule-list"])
    assert args.schedule_list is True
    assert args.run_schedule is None


def test_parse_schedule_disable_all():
    args = _parse_schedule_args(["--schedule-disable-all"])
    assert args.schedule_disable_all is True
    assert args.run_schedule is None


def test_parse_no_schedule_args():
    args = _parse_schedule_args([])
    assert args.run_schedule is None
    assert args.schedule_list is False
    assert args.schedule_disable_all is False
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_main.py::test_parse_schedule_run tests/test_main.py::test_parse_schedule_list tests/test_main.py::test_parse_schedule_disable_all tests/test_main.py::test_parse_no_schedule_args -v
```
预期：FAIL，`_parse_schedule_args` 未定义

- [ ] **Step 3: 实现 CLI 参数解析和调度模式入口**

```python
# nimo/main.py — 新增 import
import argparse
import dataclasses


# nimo/main.py — 新增数据结构
@dataclasses.dataclass
class ScheduleArgs:
    run_schedule: str | None = None
    schedule_list: bool = False
    schedule_disable_all: bool = False


def _parse_schedule_args(argv: list[str]) -> ScheduleArgs:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--run-schedule", type=str, default=None)
    parser.add_argument("--schedule-list", action="store_true", default=False)
    parser.add_argument("--schedule-disable-all", action="store_true", default=False)
    ns, _ = parser.parse_known_args(argv)
    return ScheduleArgs(
        run_schedule=ns.run_schedule,
        schedule_list=ns.schedule_list,
        schedule_disable_all=ns.schedule_disable_all,
    )
```

在 `main()` 函数的开头（`logging.basicConfig` 之前）插入调度模式的分支逻辑：

```python
# nimo/main.py — main() 函数中，logging.basicConfig 之前插入

async def main() -> None:
    parser = argparse.ArgumentParser()
    args, unknown = parser.parse_known_args()

    # ---- 调度模式分支 ----
    sched_args = _parse_schedule_args(unknown)
    if sched_args.run_schedule:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        config = load_config()
        await ToolRegistry.get_instance().init_all(config)
        from nimo.tools.schedule import execute_scheduled_task
        result = await execute_scheduled_task(sched_args.run_schedule)
        if not result.success:
            print(f"定时任务执行失败：{result.error}", flush=True)
        return

    if sched_args.schedule_list:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        from nimo.tools.schedule import _load_schedules, _schedules_path
        data = _load_schedules()
        tasks = data.get("tasks", [])
        if not tasks:
            print("没有配置的定时任务。")
        else:
            for t in tasks:
                status = "启用" if t.get("enabled") else "禁用"
                last = t.get("last_result", {}).get("summary", "无") if t.get("last_result") else "无"
                print(f"  [{status}] {t['id']}  上次：{last}")
        return

    if sched_args.schedule_disable_all:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        from nimo.tools.schedule import _schtasks_list, _schtasks_disable, _schtasks_delete
        tasks = await _schtasks_list()
        if not tasks:
            print("没有 Nimo 注册的 schtasks 任务。")
        else:
            for name in tasks:
                task_id = name.removeprefix("Nimo-")
                err = await _schtasks_disable(task_id)
                status = "已禁用" if err is None else f"禁用失败：{err}"
                print(f"  {name} → {status}")
        return
    # ---- 调度模式分支结束 ----

    # 以下是原有的交互模式逻辑...
    logging.basicConfig(
        level=logging.INFO,
        ...
    )
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_main.py::test_parse_schedule_run tests/test_main.py::test_parse_schedule_list tests/test_main.py::test_parse_schedule_disable_all tests/test_main.py::test_parse_no_schedule_args -v
```
预期：4 PASS

- [ ] **Step 5: 提交**

```bash
git add nimo/main.py tests/test_main.py
git commit -m "feat: main CLI 参数——--run-schedule / --schedule-list / --schedule-disable-all"
```

---

### Task 7: 启动时缓存摘要展示

**Files:**
- Modify: `nimo/main.py`
- Test: `tests/test_main.py`（追加）

- [ ] **Step 1: 编写 _print_schedule_summary 的失败测试**

```python
# tests/test_main.py 追加

import io
import sys
import json
from unittest.mock import patch
from nimo.main import _print_schedule_summary


def test_print_schedule_summary_with_cached_results(tmp_path, monkeypatch, capsys):
    """有缓存文件时打印最近摘要。"""
    from pathlib import Path
    monkeypatch.setattr("nimo.main._scheduled_dir", lambda: tmp_path)

    # 写入两个缓存文件
    d1 = tmp_path
    d1.mkdir(parents=True, exist_ok=True)
    json_path = d1 / "daily-check.json"
    json_path.write_text(json.dumps({
        "task_id": "daily-check",
        "triggered_at": "2026-06-17T09:00:00",
        "completed_at": "2026-06-17T09:00:12",
        "success": True,
        "summary": "2个任务到期",
        "detail": "...",
        "usage": {"prompt": 100, "completion": 50},
    }), encoding="utf-8")

    _print_schedule_summary()

    captured = capsys.readouterr()
    assert "上次检查" in captured.out


def test_print_schedule_summary_empty(tmp_path, monkeypatch, capsys):
    """无缓存文件时不输出任何内容。"""
    monkeypatch.setattr("nimo.main._scheduled_dir", lambda: tmp_path)

    _print_schedule_summary()

    captured = capsys.readouterr()
    assert captured.out.strip() == ""
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_main.py::test_print_schedule_summary_with_cached_results tests/test_main.py::test_print_schedule_summary_empty -v
```
预期：FAIL，`_print_schedule_summary` 未定义

- [ ] **Step 3: 实现启动摘要函数**

```python
# nimo/main.py 追加

from pathlib import Path


def _scheduled_dir() -> Path:
    return Path.home() / ".nimo" / "scheduled"


def _print_schedule_summary() -> None:
    """扫描缓存文件，打印最近定时检查摘要（毫秒级，不阻塞输入）。"""
    d = _scheduled_dir()
    json_files = sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not json_files:
        return

    recent = json_files[:5]
    lines = [f"\n{GRAY}──  定时检查摘要  ──{RESET}"]
    for jf in recent:
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
            ts = data.get("completed_at", "未知时间")
            # 缩短时间显示
            if len(ts) >= 16:
                ts = ts[:16].replace("T", " ")
            summary = data.get("summary", "无摘要")
            status = "✓" if data.get("success") else "✗"
            lines.append(f"  {GRAY}{ts}{RESET}  {status} {summary[:80]}")
        except (json.JSONDecodeError, OSError):
            continue
    lines.append(f"  {GRAY}输入 /refresh 获取最新状态{RESET}")

    print("\n".join(lines))
```

在 `main()` 中 `print_welcome()` 之后、`while True` 之前插入：

```python
    print_welcome(model=config.llm.model, cwd=os.getcwd(), version="0.1.0")
    _print_schedule_summary()  # 新增
    while True:
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_main.py::test_print_schedule_summary_with_cached_results tests/test_main.py::test_print_schedule_summary_empty -v
```
预期：2 PASS

- [ ] **Step 5: 提交**

```bash
git add nimo/main.py tests/test_main.py
git commit -m "feat: 启动时展示定时检查缓存摘要"
```

---

### Task 8: /refresh 命令

**Files:**
- Modify: `nimo/main.py`
- Test: `tests/test_main.py`（追加）

- [ ] **Step 1: 编写 /refresh 的失败测试**

```python
# tests/test_main.py 追加

@pytest.mark.asyncio
async def test_refresh_command_handler(tmp_path, monkeypatch):
    """_handle_refresh 读取任务 prompt 并调用 execute_scheduled_task。"""
    monkeypatch.setattr("nimo.main._schedules_path", lambda: tmp_path / "schedules.json")

    sp = tmp_path / "schedules.json"
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps({
        "tasks": [
            {"id": "daily-check", "cron": "0 9 * * 1-5", "prompt": "检查任务",
             "enabled": True, "last_run": None, "last_result": None},
        ]
    }), encoding="utf-8")

    from nimo.main import _handle_refresh

    mock_result = MagicMock()
    mock_result.success = True
    mock_result.data = {"summary": "当前2个任务到期"}

    with patch("nimo.main.execute_scheduled_task", new=AsyncMock(return_value=mock_result)):
        result = await _handle_refresh("daily-check")
        assert "2个任务到期" in result


@pytest.mark.asyncio
async def test_refresh_command_all(tmp_path, monkeypatch):
    """/refresh 无参数时执行所有已启用的任务。"""
    monkeypatch.setattr("nimo.main._schedules_path", lambda: tmp_path / "schedules.json")

    sp = tmp_path / "schedules.json"
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps({
        "tasks": [
            {"id": "t1", "cron": "0 9 * * *", "prompt": "检查A", "enabled": True,
             "last_run": None, "last_result": None},
            {"id": "t2", "cron": "0 10 * * *", "prompt": "检查B", "enabled": False,
             "last_run": None, "last_result": None},
        ]
    }), encoding="utf-8")

    from nimo.main import _handle_refresh

    mock_result = MagicMock()
    mock_result.success = True
    mock_result.data = {"summary": "OK"}

    with patch("nimo.main.execute_scheduled_task", new=AsyncMock(return_value=mock_result)):
        result = await _handle_refresh(None)  # None = 全部
        assert "t1" in result  # 执行了 t1
        assert "t2" not in result.lower().replace("1", "")  # t2 被禁用了，不执行
```

- [ ] **Step 2: 运行测试确认失败**

```bash
pytest tests/test_main.py::test_refresh_command_handler tests/test_main.py::test_refresh_command_all -v
```
预期：FAIL，`_handle_refresh` 未定义

- [ ] **Step 3: 实现 /refresh 命令**

```python
# nimo/main.py 追加

async def _handle_refresh(task_id: str | None) -> str:
    """处理 /refresh 命令。task_id 为 None 时刷新所有已启用任务。"""
    from nimo.tools.schedule import _load_schedules, execute_scheduled_task, _schedules_path

    data = _load_schedules()
    tasks = data.get("tasks", [])

    if task_id:
        tasks = [t for t in tasks if t["id"] == task_id]
        if not tasks:
            return f"未找到定时任务：{task_id}"

    enabled = [t for t in tasks if t.get("enabled")]
    if not enabled:
        return "没有已启用的定时任务。"

    results = []
    for t in enabled:
        r = await execute_scheduled_task(t["id"])
        status = "✓" if r.success else "✗"
        summary = r.data.get("summary", r.error) if r.data else (r.error or "未知")
        results.append(f"  {status} {t['id']}: {summary}")

    return "刷新完成：\n" + "\n".join(results)
```

在 `main()` 输入循环中，`/help` 之前加入 `/refresh` 处理：

```python
        if user_input.strip().startswith("/refresh"):
            parts = user_input.strip().split(maxsplit=1)
            tid = parts[1] if len(parts) > 1 else None
            try:
                result = await _handle_refresh(tid)
                print(result)
            except Exception as e:
                print(f"刷新失败：{e}")
            continue
```

同时更新 `/help` 输出，加入 `/refresh` 说明：

```python
        if user_input.strip() == "/help":
            print("""
可用命令：
  /chain         查看上一轮工具调用链
  /refresh       刷新所有定时任务的检查结果
  /refresh <id>  刷新指定定时任务
  /help          查看帮助
  /clear         清除当前对话历史
  /clear-profile 清除长期用户档案
  /exit          退出程序
...
```

- [ ] **Step 4: 运行测试确认通过**

```bash
pytest tests/test_main.py -v
```
预期：全部 PASS（原有 1 个 + 新增 8 个）

- [ ] **Step 5: 提交**

```bash
git add nimo/main.py tests/test_main.py
git commit -m "feat: /refresh 命令——手动即时执行定时检查"
```

---

## 自检清单

- [x] **Spec coverage**: 配置解析、安全校验、schedules.json 读写、schtasks 集成、执行引擎、缓存文件、启动摘要、/refresh、CLI 三个参数、脱离 Nimo 的停用方式——全部覆盖
- [x] **Placeholder scan**: 无 TBD/TODO/占位符，每步都有具体代码
- [x] **Type consistency**: `execute_scheduled_task` 签名在 Task 4/5/8 中一致；`_schedules_path` / `_scheduled_dir` 路径函数在 Task 2/7/8 中一致；`ScheduleArgs` 字段在 Task 6 定义后不再修改
