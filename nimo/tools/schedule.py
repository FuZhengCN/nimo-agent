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

            now_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
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


@dataclass
class _SchedTask:
    """调度器内部任务表示。"""
    id: str
    type: str
    cron: str | None
    trigger_at: datetime
    prompt: str
    raw: dict


class Scheduler:
    """后台调度器：asyncio Task，每 60s 检查，到点触发 agent.run()。"""

    def __init__(self, agent_factory: Callable):
        self._agent_factory = agent_factory
        self._tasks: list[_SchedTask] = []
        self._notifications: list[Notification] = []

    def _load(self) -> None:
        """从 schedules.json 加载 enabled 任务，计算触发时间。"""
        self._tasks.clear()
        data = _load_schedules()
        now = datetime.now()
        changed = False
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
                    gap = (now - expected).total_seconds() / 60.0
                    if gap > 2:  # 超过2分钟视为错过窗口，直接禁用
                        t["enabled"] = False
                        changed = True
                        continue
                self._tasks.append(_SchedTask(
                    id=task_id, type="once", cron=None,
                    trigger_at=expected, prompt=t["prompt"], raw=t,
                ))
            else:
                if not t.get("cron"):
                    continue
                next_at = _next_cron(t["cron"], now)
                if next_at is None:
                    continue
                self._tasks.append(_SchedTask(
                    id=task_id, type="cron", cron=t["cron"],
                    trigger_at=next_at, prompt=t["prompt"], raw=t,
                ))
        if changed:
            _save_schedules(data)

    async def _tick(self) -> None:
        """单次检查：重新加载任务，到点触发后台执行。"""
        self._load()
        now = datetime.now()
        todo: list[asyncio.Task] = []
        done_ids: set[str] = set()
        for st in self._tasks:
            if now >= st.trigger_at:
                todo.append(asyncio.create_task(self._execute(st)))
                done_ids.add(st.id)
        self._tasks = [st for st in self._tasks if st.id not in done_ids]
        if todo:
            await asyncio.gather(*todo, return_exceptions=True)

    async def _execute(self, st: _SchedTask) -> None:
        """后台执行单个任务，完成后更新 schedules.json + 推送通知。"""
        run_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        try:
            agent = self._agent_factory()
            result = await agent.run(st.prompt)
        except Exception as e:
            result = f"执行异常：{e}"

        async with _file_lock:
            schedules = _load_schedules()
            for t in schedules.get("tasks", []):
                if t["id"] == st.id:
                    t["last_run"] = run_str
                    full_str = result if isinstance(result, str) else str(result)
                    t["last_result"] = (
                        {"error": full_str} if full_str.startswith("执行异常：")
                        else {"summary": full_str[:120]}
                    )
                    if st.type == "once":
                        t["enabled"] = False
                    elif st.type == "cron":
                        next_at = _next_cron(st.cron, datetime.now())
                        if next_at:
                            self._tasks.append(_SchedTask(
                                id=st.id, type="cron", cron=st.cron,
                                trigger_at=next_at, prompt=st.prompt, raw=t,
                            ))
                    break
            _save_schedules(schedules)

        full = result if isinstance(result, str) else str(result)
        self._notifications.append(Notification(
            task_id=st.id,
            completed_at=run_str,
            summary=full[:120],
            full_text=full,
        ))

    def pop_notifications(self) -> list[Notification]:
        ns = list(self._notifications)
        self._notifications.clear()
        return ns

    async def start(self) -> None:
        """启动调度器循环。作为 asyncio Task 运行，永不停止。"""
        self._load()
        while True:
            await asyncio.sleep(60)
            try:
                await self._tick()
                self._load()  # 重新加载，捕获外部变更（工具 add/remove）
            except Exception:
                logger.exception("调度器 tick 异常，跳过本轮")
