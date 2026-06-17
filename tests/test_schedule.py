# tests/test_schedule.py

import json
import pytest
from pathlib import Path
from nimo.tools.schedule import _validate_args, _load_schedules, _save_schedules, schedule
from nimo.config import Config, LLMConfig, TapdConfig, SchedulesConfig


def test_validate_action_whitelist():
    assert _validate_args("list") is None
    assert _validate_args("add") is not None
    assert _validate_args("remove") is not None  # 缺少 task_id
    assert _validate_args("enable") is not None  # 缺少 task_id
    assert _validate_args("disable") is not None  # 缺少 task_id
    assert _validate_args("delete") is not None
    assert _validate_args("run") is not None  # run 已废弃
    assert _validate_args("") is not None
    assert _validate_args("LIST") is not None  # 小写白名单


def test_validate_task_id_valid():
    assert _validate_args("add", "daily-check", "0 9 * * *") is None
    assert _validate_args("add", "weekly-report", "0 9 * * *") is None
    assert _validate_args("add", "task-123", "0 9 * * *") is None


def test_validate_task_id_invalid():
    assert _validate_args("add", "../etc", delay_minutes=30) is not None
    assert _validate_args("add", "rm -rf", delay_minutes=30) is not None
    assert _validate_args("add", "", delay_minutes=30) is not None
    assert _validate_args("add", "a" * 65, delay_minutes=30) is not None  # 超过64字符
    assert _validate_args("add", "A" * 64, delay_minutes=30) is None


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
    """add 时 cron 和 delay_minutes 都没提供，返回错误。"""
    result = _validate_args("add", "ok")
    assert result is not None
    assert "至少需要指定一个" in result


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


def test_validate_task_id_required_for_non_add():
    """remove/enable/disable 必须提供 task_id。"""
    for action in ("remove", "enable", "disable"):
        result = _validate_args(action)
        assert result is not None
        assert "缺少 task_id" in result


def test_load_schedules_corrupted(tmp_path, monkeypatch):
    """损坏的 JSON 文件返回空任务列表。"""
    path = tmp_path / "schedules.json"
    path.write_text("this is not json")
    monkeypatch.setattr("nimo.tools.schedule._schedules_path", lambda: path)
    result = _load_schedules()
    assert result == {"tasks": []}


# ── schedule 工具函数（@register_tool）测试 ──


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

    _save_schedules({
        "tasks": [{
            "id": "to-delete", "type": "cron", "cron": "0 9 * * *",
            "delay_minutes": None, "prompt": "检查", "enabled": True,
            "created_at": "2026-06-17T10:00:00", "last_run": None, "last_result": None,
        }]
    })
    result = await schedule(action="remove", task_id="to-delete")
    assert result.success is True

    data = _load_schedules()
    assert len(data["tasks"]) == 0


@pytest.mark.asyncio
async def test_schedule_tool_remove_not_found(schedule_config, tmp_path, monkeypatch):
    """删除不存在的任务返回错误。"""
    monkeypatch.setattr("nimo.tools.schedule._schedules_path", lambda: tmp_path / "schedules.json")
    monkeypatch.setattr("nimo.tools.schedule._config", schedule_config)

    _save_schedules({"tasks": []})
    result = await schedule(action="remove", task_id="nonexistent")
    assert result.success is False
    assert "未找到" in result.error


@pytest.mark.asyncio
async def test_schedule_tool_enable_disable(schedule_config, tmp_path, monkeypatch):
    """启用/禁用任务。"""
    monkeypatch.setattr("nimo.tools.schedule._schedules_path", lambda: tmp_path / "schedules.json")
    monkeypatch.setattr("nimo.tools.schedule._config", schedule_config)

    _save_schedules({
        "tasks": [{
            "id": "toggle-task", "type": "cron", "cron": "0 9 * * *",
            "delay_minutes": None, "prompt": "检查", "enabled": True,
            "created_at": "2026-06-17T10:00:00", "last_run": None, "last_result": None,
        }]
    })

    dr = await schedule(action="disable", task_id="toggle-task")
    assert dr.success is True

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
