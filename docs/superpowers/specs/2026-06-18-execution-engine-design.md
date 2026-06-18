# ExecutionEngine：编排与执行分离

日期：2026-06-18

## 动机

当前架构下 LLM 直接操控 CLI 命令——包括"先 workspace list，再逐个查 timesheet"这类执行策略。这导致两个问题：

1. LLM 轮次浪费在执行决策上，token 消耗大
2. "全覆盖查项目"依赖 system prompt 的规则约束，不稳定

将"编排"和"执行"拆成两层：LLM 只负责理解意图和呈现结果，确定性代码负责执行。

## 架构

```
Agent (LLM) —— 纯粹推理
  理解意图 → 调用意图工具 → 格式化回复

        ↓ function calling

tapd_query / svn_op —— 意图工具
  构造 Intent → 委托引擎

        ↓

ExecutionEngine (代码) —— 确定性执行
  解析 Intent → 匹配执行模式 → 执行步骤 → 合并结果
```

### 关键关系

- Agent 循环不动：`agent.py` 零修改
- ToolRegistry 不变：`execute()` 签名和 `ToolResult` 返回不变
- 新旧工具共存：`tapd_cli` / `svn` 照常保留，新工具用新名字

## ExecutionEngine

`nimo/engine.py`，单例模式。

```
ExecutionEngine
  async execute(intent: Intent) → ToolResult

    模式判断：
    ├─ direct（有 workspace_id 或无项目上下文需要）
    │    直接执行 1 次 _run_tapd 或 _run_svn
    │
    └─ for_each_workspace（无 workspace_id + 需要项目上下文）
         1. workspace list → 获取全部项目
         2. for ws in workspaces:
              _run_tapd(action, ws_id, **params)
         3. merge：所有成功步骤的数据合并为单数组，失败步骤汇总到 errors 列表

    原子操作：
    ├─ _run_tapd(args) → await subprocess (tapd.exe)
    └─ _run_svn(args) → await subprocess (svn.exe/svnadmin.exe)
```

### Intent 数据结构

```python
@dataclass
class Intent:
    tool: str           # "tapd" | "svn"
    action: str         # "timesheet_list" | "story_list" | ...
    params: dict        # {"owner": "...", "workspace_id": "...", ...}
```

### 错误处理：部分成功 = 成功

多步执行中，单步失败不阻断其余步骤。至少 1 步成功即返回 `success=True`，失败步骤附在 `errors` 字段。

```python
@dataclass
class StepResult:
    workspace_id: str
    workspace_name: str
    success: bool
    data: Any
    error: str | None
```

引擎不做重试——LLM client 层已有 4 次重试，引擎只负责"知道哪里失败了"。

全部失败时返回 `success=False`，`data` 为空，`error` 汇总所有失败原因。

## 新意图工具

### tapd_query

参数为结构化意图字段，非 CLI args 数组：

| 参数 | 必填 | 说明 |
|------|------|------|
| `action` | 是 | timesheet_list, story_list, story_create, task_show, ... |
| `owner` | 否 | 按人筛选，如 "傅政" |
| `workspace_id` | 否 | 不传则引擎触发 for_each_workspace |
| `date` | 否 | 日期 |
| `entity_id` | 否 | story/task/bug ID |
| `name` | 否 | 创建/搜索用 |

引擎行为规则：

| 条件 | 模式 |
|------|------|
| 有 workspace_id 或 entity_id | direct |
| 无 workspace_id + 查询类 action | for_each_workspace |
| action = workspace_list | direct |

### svn_op

SVN 语义上几乎全是 direct 模式，但仍走引擎统一入口：

| 参数 | 必填 | 说明 |
|------|------|------|
| `action` | 是 | log, diff, blame, update, commit, ... |
| `path` | 否 | 优先级最高 |
| `project` | 否 | 配置文件别名 |
| `url` | 否 | checkout/switch 等场景 |
| `extra` | 否 | {"limit": 10, "search": "keyword"} |

## 迁移路径

1. **Phase 1**：新建 `engine.py` + `tapd_intent.py` + `svn_intent.py`，旧工具不动
2. **Phase 2**：观察 LLM 对新工具的使用稳定性
3. **Phase 3**：确认稳定后，注释掉 `tapd_cli` / `svn` 的注册

## 测试

- ExecutionEngine 独立于 LLM、Agent、ToolRegistry，mock subprocess 即可全覆盖
- 覆盖：direct 模式、for_each_workspace 模式、部分失败、全失败、空结果
- 新工具函数测试与现有 `test_tapd.py` / `test_tortoisesvn.py` 同模式
