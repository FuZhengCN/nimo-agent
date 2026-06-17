# nimo/tools/schedule.py

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from nimo.tools.registry import register_tool, ToolResult, ToolRegistry

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
        if has_cron and has_delay:
            return "cron 和 delay_minutes 不能同时指定"
        if not has_cron and not has_delay:
            return "cron 或 delay_minutes 至少需要指定一个"
        if has_cron and not _validate_cron(cron):
            return f"无效的 cron 表达式：{cron}（需要5字段格式，如 '0 9 * * 1-5'）"
        if has_delay and not (1 <= delay_minutes <= 1440):
            return f"delay_minutes 超出范围：{delay_minutes}（1-1440）"
        if prompt and len(prompt) > 500:
            return f"prompt 过长：{len(prompt)}字符（最多500字符）"

    return None


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
        if not any(t["id"] == task_id for t in schedules["tasks"]):
            return ToolResult(success=False, error=f"未找到定时任务：{task_id}")
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
