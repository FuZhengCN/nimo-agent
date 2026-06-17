# tests/test_schedule.py

import asyncio
import json
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from nimo.tools.schedule import _validate_args, _load_schedules, _save_schedules, schedule, _cron_match, _next_cron, Scheduler
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
    assert _validate_args("add", "daily-check", "0 9 * * *", prompt="检查") is None
    assert _validate_args("add", "weekly-report", "0 9 * * *", prompt="检查") is None
    assert _validate_args("add", "task-123", "0 9 * * *", prompt="检查") is None


def test_validate_task_id_invalid():
    assert _validate_args("add", "../etc", delay_minutes=30) is not None
    assert _validate_args("add", "rm -rf", delay_minutes=30) is not None
    assert _validate_args("add", "", delay_minutes=30) is not None
    assert _validate_args("add", "a" * 65, delay_minutes=30) is not None  # 超过64字符
    assert _validate_args("add", "A" * 64, delay_minutes=30, prompt="检查") is None


def test_validate_cron_valid():
    assert _validate_args("add", "ok", "0 9 * * 1-5", prompt="检查") is None
    assert _validate_args("add", "ok", "*/5 * * * *", prompt="检查") is None
    assert _validate_args("add", "ok", "30 8,17 * * 1-5", prompt="检查") is None


def test_validate_cron_invalid():
    assert _validate_args("add", "ok", "0 9 *") is not None  # 只有3字段
    assert _validate_args("add", "ok", "invalid cron") is not None
    assert _validate_args("add", "ok", "60 * * * *") is not None  # 分钟超出范围


def test_validate_delay_minutes_valid():
    assert _validate_args("add", "ok", delay_minutes=30, prompt="检查") is None
    assert _validate_args("add", "ok", delay_minutes=1, prompt="检查") is None
    assert _validate_args("add", "ok", delay_minutes=1440, prompt="检查") is None


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


def test_validate_add_requires_prompt():
    """add 操作必须提供 prompt。"""
    assert _validate_args("add", "ok", "0 9 * * *") is not None
    assert _validate_args("add", "ok", "0 9 * * *", "") is not None


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


# ── cron 匹配 ──


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
    assert _cron_match("* 9-17 * * 1-5", datetime(2026, 6, 17, 9, 0)) is True  # Wed
    assert _cron_match("* 9-17 * * 1-5", datetime(2026, 6, 17, 18, 0)) is False


def test_cron_match_weekday():
    """1-5 工作日，0=sun。"""
    wed = datetime(2026, 6, 17)  # 周三
    sat = datetime(2026, 6, 20)  # 周六
    assert _cron_match("0 9 * * 1-5", wed.replace(hour=9, minute=0)) is True
    assert _cron_match("0 9 * * 1-5", sat.replace(hour=9, minute=0)) is False


def test_cron_match_weekday_5_7_range():
    """5-7 范围（周五到周日），周日应匹配。"""
    sunday = datetime(2026, 6, 21, 9, 0)
    assert _cron_match("0 9 * * 5-7", sunday) is True
    saturday = datetime(2026, 6, 20, 9, 0)
    assert _cron_match("0 9 * * 5-7", saturday) is True
    monday = datetime(2026, 6, 22, 9, 0)
    assert _cron_match("0 9 * * 5-7", monday) is False


def test_cron_match_comma():
    """8,17 逗号分隔。"""
    assert _cron_match("0 8,17 * * *", datetime(2026, 6, 17, 8, 0)) is True
    assert _cron_match("0 8,17 * * *", datetime(2026, 6, 17, 17, 0)) is True
    assert _cron_match("0 8,17 * * *", datetime(2026, 6, 17, 12, 0)) is False


def test_next_cron_daily():
    """每天9点，从8点开始找，应找到今天9点。"""
    dt = datetime(2026, 6, 17, 8, 0)
    result = _next_cron("0 9 * * *", dt)
    assert result.hour == 9
    assert result.minute == 0
    assert result.day == 17


def test_next_cron_same_minute():
    """当前时间已过匹配点，应找下一个。"""
    dt = datetime(2026, 6, 17, 12, 31)
    result = _next_cron("30 12 * * *", dt)
    assert result > dt
    assert result.hour == 12 or result.day > 17  # 要么当天晚些时候，要么第二天


def test_next_cron_returns_none_for_unmatchable():
    """7天内无匹配返回 None（极端情况）。"""
    # "2月30号" 这种不存在的日期，或只在特定条件下匹配
    # 用2月30号测试：日期范围是1-31，但2月只有28/29天
    # 直接测试更简单：在很远的时间段内没有匹配
    result = _next_cron("0 0 31 2 *", datetime(2026, 6, 17))
    assert result is None  # 2月31日不存在，7天内找不到


# ── 调度器 ──


@pytest.mark.asyncio
async def test_scheduler_missed_once_task(schedule_config, tmp_path, monkeypatch):
    """once 任务错过窗口期启动后直接 disabled，不补执行，不产生通知。"""
    monkeypatch.setattr("nimo.tools.schedule._schedules_path", lambda: tmp_path / "schedules.json")
    monkeypatch.setattr("nimo.tools.schedule._config", schedule_config)

    # 写入一个 once 任务，created_at 是10分钟前，delay=5 → 5分钟前就该触发
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

    mock_run = AsyncMock(return_value="结果")
    agent_factory = MagicMock(return_value=MagicMock())
    agent_factory().run = mock_run

    sched = Scheduler(agent_factory)
    await sched._tick()

    # agent.run 不应被调用（错过窗口，直接跳过）
    mock_run.assert_not_called()

    # 任务被标记 disabled
    from nimo.tools.schedule import _load_schedules
    task = _load_schedules()["tasks"][0]
    assert task["enabled"] is False

    # 无通知
    assert len(sched.pop_notifications()) == 0


@pytest.mark.asyncio
async def test_scheduler_runs_ready_once_task(schedule_config, tmp_path, monkeypatch):
    """once 任务到时间触发执行，完成后 disabled 并推送通知。"""
    monkeypatch.setattr("nimo.tools.schedule._schedules_path", lambda: tmp_path / "schedules.json")
    monkeypatch.setattr("nimo.tools.schedule._config", schedule_config)

    mock_run = AsyncMock(return_value="发现 2 个新提交")
    agent_factory = MagicMock(return_value=MagicMock())
    agent_factory().run = mock_run

    sched = Scheduler(agent_factory)
    # 先调一次 _load + _tick 清空初始状态
    sched._load()
    await sched._tick()

    # 模拟运行时: schedule 工具在 scheduler 运行中写入任务
    from nimo.tools.schedule import _save_schedules
    now = datetime.now()
    _save_schedules({
        "tasks": [{
            "id": "ready-task",
            "type": "once",
            "cron": None,
            "delay_minutes": 0,  # 立即触发
            "prompt": "检查提交",
            "enabled": True,
            "created_at": now.strftime("%Y-%m-%dT%H:%M:%S.%f"),
            "last_run": None,
            "last_result": None,
        }]
    })

    sched._load()  # 加载新写入的任务 (created_at > _started_at → 不跳过)
    await sched._tick()

    mock_run.assert_called_once_with("检查提交")

    notifications = sched.pop_notifications()
    assert len(notifications) == 1
    assert notifications[0].task_id == "ready-task"
    assert "2 个新提交" in notifications[0].summary

    from nimo.tools.schedule import _load_schedules
    task = _load_schedules()["tasks"][0]
    assert task["enabled"] is False
    assert task["last_run"] is not None


@pytest.mark.asyncio
async def test_scheduler_task_error_does_not_crash(schedule_config, tmp_path, monkeypatch):
    """单任务 agent.run 抛异常不影响调度器（不崩，继续运行）。"""
    monkeypatch.setattr("nimo.tools.schedule._schedules_path", lambda: tmp_path / "schedules.json")
    monkeypatch.setattr("nimo.tools.schedule._config", schedule_config)

    mock_run = AsyncMock(side_effect=RuntimeError("LLM 挂了"))
    agent_factory = MagicMock(return_value=MagicMock())
    agent_factory().run = mock_run

    sched = Scheduler(agent_factory)
    sched._load()
    await sched._tick()

    # 模拟运行时写入：created_at > _started_at，不跳过
    from nimo.tools.schedule import _save_schedules
    now = datetime.now()
    _save_schedules({
        "tasks": [{
            "id": "bad-task",
            "type": "once",
            "cron": None,
            "delay_minutes": 0,
            "prompt": "检查",
            "enabled": True,
            "created_at": now.strftime("%Y-%m-%dT%H:%M:%S.%f"),
            "last_run": None,
            "last_result": None,
        }]
    })

    sched._load()
    await sched._tick()  # 不应抛异常

    from nimo.tools.schedule import _load_schedules
    task = _load_schedules()["tasks"][0]
    assert "LLM 挂了" in task["last_result"].get("error", "")
