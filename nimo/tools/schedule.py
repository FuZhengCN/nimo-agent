# nimo/tools/schedule.py

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

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
            if step_val < 1 or step_val > max_val:
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
    ranges = [(0, 59), (0, 23), (1, 31), (1, 12), (0, 7)]
    for field, (lo, hi) in zip(fields, ranges):
        if not _validate_cron_field(field, lo, hi):
            return False
    return True


def _validate_args(action: str, task_id: str | None = None, cron: str = "",
                   prompt: str = "", delay_minutes=None) -> str | None:
    """校验 schedule 工具参数，返回错误信息或 None（通过）。"""
    if action not in _ALLOWED_ACTIONS:
        return f"不允许的操作：{action}"

    needs_id = {"add", "remove", "enable", "disable"}
    if action in needs_id:
        if task_id is None:
            if action != "add":
                return f"{action} 操作需要指定 task_id"
        elif not task_id:
            return "缺少 task_id 参数"
        elif not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9\-]{0,62}[a-zA-Z0-9]?", task_id):
            return f"无效的 task_id：{task_id}（仅允许字母、数字、连字符，最长64字符）"
        elif len(task_id) > 64:
            return f"task_id 过长：{len(task_id)}（最多64字符）"

    if action == "add" and task_id is not None:
        has_cron = bool(cron)
        has_delay = delay_minutes is not None
        if has_cron and has_delay:
            return "cron 和 delay_minutes 不能同时指定"
        if has_cron and not _validate_cron(cron):
            return f"无效的 cron 表达式：{cron}（需要5字段格式，如 '0 9 * * 1-5'）"
        if has_delay and not (1 <= delay_minutes <= 1440):
            return f"delay_minutes 超出范围：{delay_minutes}（1-1440）"
        if prompt and len(prompt) > 500:
            return f"prompt 过长：{len(prompt)}字符（最多500字符）"

    return None
