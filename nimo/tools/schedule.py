# nimo/tools/schedule.py

import asyncio
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from nimo.tools.registry import register_tool, ToolResult, ToolRegistry

logger = logging.getLogger(__name__)

_ALLOWED_ACTIONS = frozenset({"list", "add", "remove", "enable", "disable"})
_CRON_RE = re.compile(
    r"^(\*|[\d,\-*/]+)\s+(\*|[\d,\-*/]+)\s+(\*|[\d,\-*/]+)\s+(\*|[\d,\-*/]+)\s+(\*|[\d,\-*/]+)$"
)

_config = None
_file_lock = asyncio.Lock()


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
        if action == "add" and not prompt:
            return "add 操作必须提供 prompt"
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
        async with _file_lock:
            schedules = _load_schedules()
            if any(t["id"] == task_id for t in schedules["tasks"]):
                return ToolResult(success=False, error=f"任务 {task_id} 已存在，请先删除再添加")

            now_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")
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
        async with _file_lock:
            schedules = _load_schedules()
            if not any(t["id"] == task_id for t in schedules["tasks"]):
                return ToolResult(success=False, error=f"未找到定时任务：{task_id}")
            schedules["tasks"] = [t for t in schedules["tasks"] if t["id"] != task_id]
            _save_schedules(schedules)
        return ToolResult(success=True, data={"message": f"定时任务 {task_id} 已删除"})

    if action in ("enable", "disable"):
        new_state = action == "enable"
        async with _file_lock:
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


# ── cron 匹配 ──


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


def _cron_match(cron: str, dt: datetime) -> bool:
    """检查 datetime 是否匹配 cron 表达式。"""
    parts = cron.strip().split()
    minute, hour, day, month, weekday = parts
    wd = dt.isoweekday() % 7  # 1=mon..7=sun → 0=sun..6=sat
    weekday_match = _cron_field_match(weekday, wd)
    if not weekday_match and wd == 0:
        weekday_match = _cron_field_match(weekday, 7)
    return (
        _cron_field_match(minute, dt.minute) and
        _cron_field_match(hour, dt.hour) and
        _cron_field_match(day, dt.day) and
        _cron_field_match(month, dt.month) and
        weekday_match
    )


def _next_cron(cron: str, from_dt: datetime | None = None) -> datetime | None:
    """计算 cron 下一次触发时间，最多查找 7 天。无匹配返回 None。"""
    if from_dt is None:
        from_dt = datetime.now()
    dt = from_dt + timedelta(minutes=1)
    end = from_dt + timedelta(days=7)
    while dt <= end:
        if _cron_match(cron, dt):
            return dt
        dt += timedelta(minutes=1)
    return None


# ── 调度器 ──


@dataclass
class Notification:
    task_id: str
    completed_at: str
    summary: str
    full_text: str


class Scheduler:
    """后台调度器：每 60s 检查 schedules.json，发现到期任务立即触发。"""

    def __init__(self, agent_factory: Callable):
        self._agent_factory = agent_factory
        self._notifications: list[Notification] = []
        self._started_at = datetime.now()

    def _is_once_due(self, t: dict, now: datetime) -> tuple[bool, bool]:
        """检查 once 任务是否到期。返回 (到期, 是否修改了任务数据)。"""
        try:
            created = datetime.fromisoformat(t["created_at"])
        except (ValueError, TypeError):
            return False, False
        expected = created + timedelta(minutes=t.get("delay_minutes", 0))
        if now < expected:
            return False, False
        if created < self._started_at:
            t["enabled"] = False
            return False, True  # 已禁用，需保存
        return True, False

    def _is_cron_due(self, t: dict, now: datetime) -> bool:
        """cron 任务：自上次执行（或创建）以来，cron 是否曾匹配过。"""
        cron = t["cron"]
        last_run = t.get("last_run")

        if last_run:
            try:
                search_from = datetime.fromisoformat(last_run) + timedelta(minutes=1)
            except (ValueError, TypeError):
                search_from = now - timedelta(minutes=2)
        else:
            try:
                created = datetime.fromisoformat(t["created_at"])
            except (ValueError, TypeError):
                created = now - timedelta(minutes=2)
            search_from = created

        dt = search_from
        while dt <= now:
            if _cron_match(cron, dt):
                return True
            dt += timedelta(minutes=1)
        return False

    async def _check_all(self) -> None:
        """扫描所有 enabled 任务，到期则触发执行。"""
        data = _load_schedules()
        changed = False
        todo: list[asyncio.Task] = []

        for t in data.get("tasks", []):
            if not t.get("enabled"):
                continue
            now = datetime.now()
            if t["type"] == "once":
                due, modified = self._is_once_due(t, now)
                if modified:
                    changed = True
            elif t.get("cron"):
                due = self._is_cron_due(t, now)
            else:
                continue

            if due:
                todo.append(asyncio.create_task(
                    self._execute(t["id"], t["prompt"], t["type"] == "once")
                ))

        if changed:
            _save_schedules(data)
        if todo:
            await asyncio.gather(*todo, return_exceptions=True)

    async def _execute(self, task_id: str, prompt: str, is_once: bool) -> None:
        """后台执行单个任务，完成后更新 schedules.json + 推送通知。"""
        run_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        try:
            agent = self._agent_factory()
            result = await agent.run(prompt)
        except Exception as e:
            result = f"执行异常：{e}"

        async with _file_lock:
            schedules = _load_schedules()
            for t in schedules.get("tasks", []):
                if t["id"] == task_id:
                    t["last_run"] = run_str
                    full_str = result if isinstance(result, str) else str(result)
                    t["last_result"] = (
                        {"error": full_str} if full_str.startswith("执行异常：")
                        else {"summary": full_str[:120]}
                    )
                    if is_once:
                        t["enabled"] = False
                    break
            _save_schedules(schedules)

        full = result if isinstance(result, str) else str(result)
        self._notifications.append(Notification(
            task_id=task_id,
            completed_at=run_str,
            summary=full[:120],
            full_text=full,
        ))

    def pop_notifications(self) -> list[Notification]:
        ns = list(self._notifications)
        self._notifications.clear()
        return ns

    async def start(self) -> None:
        """每 60s 扫描 schedules.json，发现到期任务立即触发。"""
        while True:
            await asyncio.sleep(60)
            try:
                await self._check_all()
            except Exception:
                logger.exception("调度器异常，跳过本轮")
