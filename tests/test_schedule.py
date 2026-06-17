# tests/test_schedule.py

import json
import pytest
from pathlib import Path
from nimo.tools.schedule import _validate_args, _load_schedules, _save_schedules


def test_validate_action_whitelist():
    assert _validate_args("list") is None
    assert _validate_args("add") is None
    assert _validate_args("remove") is not None  # 缺少 task_id
    assert _validate_args("enable") is not None  # 缺少 task_id
    assert _validate_args("disable") is not None  # 缺少 task_id
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
    """add 时 cron 和 delay_minutes 都没提供，仅校验 task_id（不要求必须提供）。"""
    assert _validate_args("add", "ok") is None  # 只校验已提供的参数，不要求 cron/delay


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
        assert "需要指定 task_id" in result


def test_load_schedules_corrupted(tmp_path, monkeypatch):
    """损坏的 JSON 文件返回空任务列表。"""
    path = tmp_path / "schedules.json"
    path.write_text("this is not json")
    monkeypatch.setattr("nimo.tools.schedule._schedules_path", lambda: path)
    result = _load_schedules()
    assert result == {"tasks": []}
