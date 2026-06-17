# 定时任务系统 重设计 Spec

## 背景

上一版用 Windows schtasks.exe 驱动定时执行，每次触发都是冷启动——新进程、无历史、无 profile、无上下文，执行引擎是 Agent.run() 的残缺山寨版，导致频繁打满工具轮数后写死"已达到工具调用上限"。

**根本问题：外部进程调度 = 失忆执行 = 不可用。**

## 核心原则

1. **复用 Agent.run()**：调度器只负责"什么时候触发"，执行走完整 Agent 流程，不做山寨版
2. **asyncio 内置调度**：零外部依赖，调度器和输入循环共享同一个 event loop
3. **启动时恢复，错过则跳过**：schedules.json 持久化任务定义，Nimo 运行时到点触发，不在运行时跳过

## 需求摘要

- 固定周期（cron 5 字段）+ 一次性延迟（delay_minutes）两种模式
- 跨会话持久化（schedules.json）
- Nimo 运行时到点立刻执行；不在运行时跳过，不做补触发
- 后台执行不阻塞用户输入
- 完成后下一轮提示符前弹出通知，用户选择看或不看

---

## 架构总览

```
main.py（输入循环）
    │
    ├─ agent.run()  ←─ 用户输入路径（原有，不动）
    │
    ├─ Scheduler  ←─ 后台 asyncio Task，启动时创建
    │     │
    │     ├─ 每 60s 轮询 ~/.nimo/schedules.json
    │     ├─ cron 匹配 / delay 计时 → 到点触发
    │     ├─ asyncio.create_task() 后台调 agent.run(prompt)
    │     └─ 完成后 → notify_queue
    │
    └─ 通知检查  ←─ 每次输入提示符前检查
          └─ 有待看结果 → 弹出提示询问用户
```

## 调度器核心

```python
# Scheduler — 独立 asyncio Task

启动时:
  load schedules.json → 过滤 enabled=true 的任务
  cron 任务: 标记 next_run = 下一次匹配时间
  once 任务: 标记 expected_at = created_time + delay_minutes

主循环（每 60s）:
  for task in enabled_tasks:
    if now >= task.trigger_time:
      asyncio.create_task(run_and_notify(task))
      if once: 标记 enabled=false + 记录 last_run/last_result（不物理删除）
      if cron: 更新 last_run, 计算下一次 trigger_time

run_and_notify(task):
  result = await agent.run(task.prompt)
  notify_queue.append(Notification(task.id, time, result))
  _save_schedules()
```

- cron 匹配：5 字段逐一比对，支持 `*` `*/N` `N` `N-M`
- 60s 调度粒度，不追求秒级精度
- 调度器入口 try/except 包裹，单任务失败不影响调度器继续运行
- 启动时：如果 once 任务的 expected_at 已过（Nimo 不在线），直接标记 enabled=false，不补执行

## 数据模型

`~/.nimo/schedules.json`：

```json
{
  "tasks": [
    {
      "id": "daily-check",
      "type": "cron",
      "cron": "0 9 * * 1-5",
      "delay_minutes": null,
      "prompt": "检查今天到期的 TAPD 任务",
      "enabled": true,
      "created_at": "2026-06-17T10:30:00",
      "last_run": null,
      "last_result": null
    },
    {
      "id": "remind-1457",
      "type": "once",
      "cron": null,
      "delay_minutes": 30,
      "prompt": "检查 SVN 提交日志",
      "enabled": true,
      "created_at": "2026-06-17T14:00:00",
      "last_run": null,
      "last_result": null
    }
  ]
}
```

字段说明：

| 字段 | cron 任务 | once 任务 |
|------|----------|----------|
| `type` | `"cron"` | `"once"` |
| `cron` | 5 字段 cron | null |
| `delay_minutes` | null | 1-1440 延迟分钟数 |
| `enabled` | 默认 true，可通过 disable 关闭 | 默认 true |
| `created_at` | 创建时间 | 创建时间（用于计算触发时刻） |
| `last_run` | 上次执行时间 | 执行后标注 |
| `last_result` | 上次执行摘要 | 执行后标注 |

once 任务执行后自动标记 `enabled=false`（而非物理删除，保留执行记录）。

## 通知机制

```
任务执行完成后推送至 notify_queue:
  Notification:
    task_id: str
    completed_at: str           # ISO 时间
    summary: str                # agent.run() 返回值前 120 字
    full_text: str              # 完整结果

输入循环（每次打印提示符 "> " 之前）:
  for n in notify_queue:
    print(f"[!] 定时任务 '{n.task_id}' 已完成，要看结果吗？(y/n) ")
    if input() == "y":
      print_response_box(n.full_text)    # 复用现有 Markdown 渲染
    notify_queue.remove(n)
```

- 任务执行不影响当前输入（asyncio 并行）
- 完成后不打断正在输入的文本，在下一次输完回车后检查通知
- 用户选 n 则跳过，结果不缓存

## schedule 工具

`@register_tool("schedule")` 暴露给 LLM：

```python
action 枚举: list / add / remove / enable / disable

add 参数:
  task_id:      仅允许字母数字和连字符，最长 64 字符
  cron:         5 字段 cron（与 delay_minutes 二选一）
  delay_minutes:  延迟分钟数 1-1440（与 cron 二选一）
  prompt:       定时执行的提示，最长 500 字符

remove / enable / disable 参数:
  task_id:      目标任务 ID
```

- `list` 无需额外权限
- `add/remove/enable/disable` 需要 config 中 `schedules.enabled: true`
- 去掉了 `run` action（用户直接对话描述任务即可，无需间接调用）

## 配置

`config.yaml` 追加：

```yaml
schedules:
  enabled: true   # 控制 LLM 是否能通过 schedule 工具增删改任务
```

注意：`schedules.enabled` 只控制 schedule 工具权限，不影响调度器本身的运行。只要有 enabled=true 的任务，调度器就会按 cron/delay 触发执行。任务级 enabled 控制单个任务是否运行，config 级 schedules.enabled 控制 LLM 是否有权管理任务。

## 错误处理

| 场景 | 行为 |
|------|------|
| 单个任务执行异常 | 记录 error 到 last_result，调度器继续 |
| schedules.json 损坏 | 加载失败 → 日志警告 + 空任务列表 |
| LLM 调用失败 | Agent.run() 内部已有 LLMError catch，返回错误消息 |
| 调度器自身崩溃 | asyncio Task 异常由事件循环兜底，不会丢失输入循环 |

## 不再有的东西

- schtasks.exe 依赖及其所有集成代码
- `execute_scheduled_task()` 山寨执行引擎
- `--run-schedule` / `--schedule-list` / `--schedule-disable-all` CLI 参数
- `/refresh` / `/clear-schedule` 命令
- 启动时缓存摘要展示
- 缓存文件（scheduled/*.json）
- `_schtasks_*` 系列函数
- `SchedulesConfig` 的 `schedule_disable_all` 等字段
