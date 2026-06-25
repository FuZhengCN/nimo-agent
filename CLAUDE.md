# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Nimo 是一个 CLI AI Agent，基于 DeepSeek function calling。用户通过自然语言对话执行 TAPD 操作（查项目、需求/任务/缺陷 CRUD、填工时、评论、迭代等）和 SVN 版本控制（查日志、差异对比、更新提交等）。项目目标是实践 AI Agent 开发。

核心架构特点：**编排与执行分离**——LLM 通过意图工具表达"要做什么"，ExecutionEngine 确定性代码负责"怎么执行"，内置 `for_each_workspace` 等可复用执行模式，LLM 不再直接操控 CLI 参数。**Skill 系统**支持从 GitHub 安装外部领域能力包，三级格式降级解析，渐进式披露（L1 元数据 → L2 指令注入 → L3 脚本执行）。**定时任务系统**支持 cron 和延迟两种模式，后台每 60s 轮询自动触发。

## 项目规则

- **可扩展优先**：Agent 后续会逐步添加新工具，任何设计决策都要考虑可扩展性——写死一个工具名、写死一种参数格式、写死一种返回结构，都是在给未来挖坑。每次写代码时自问：如果再多 5 个工具，这段代码还能工作吗？

## 常用命令

```bash
# 开发安装
pip install -e ".[dev]"

# 运行
python -m nimo.main          # 需要项目根目录有 config.yaml

# 全部测试
pytest tests/ -v

# 覆盖率报告
pytest tests/ --cov=nimo --cov-report=term-missing

# 单个测试文件
pytest tests/test_display.py -v
pytest tests/test_agent.py -v

# 单个测试用例
pytest tests/test_config.py::test_load_config_from_yaml -v
```

## 架构

### 依赖链（单向，无循环）

```
main.py → agent.py → llm/client.py
                   → memory/history.py
                   → tools/registry.py
                   → skill/registry.py → tools/registry.py（ToolResult）
        → config.py
        → display.py
        → engine.py → tools/registry.py（ToolResult）

        → tools/__init__.py (pkgutil 自动发现工具模块)
            → tools/tapd.py (@register_tool 注册 tapd_cli，透传 CLI 参数)
            → tools/tortoisesvn.py (@register_tool 注册 svn，透传 CLI 参数)
            → tools/tapd_intent.py (@register_tool 注册 tapd_query，意图工具)
            → tools/svn_intent.py (@register_tool 注册 svn_op，意图工具)
            → tools/skill_tools.py (@register_tool 注册 activate_skill/deactivate_skill/skill_run)
            → tools/python_exec.py (@register_tool 注册 python_exec，动态执行 Python 代码)
            → tools/schedule.py (@register_tool 注册 schedule，管理定时任务 + Scheduler 后台轮询)
```

`main()` 先 `load_config()`，再 `build_agent(config)` + `print_welcome()`，启动 `Scheduler` 后台轮询（若 `schedules.enabled`），最后进入输入循环（`_input_with_poll` 在等待用户输入时轮询调度通知）。`build_agent()` 先初始化 `ExecutionEngine`，再调用 `ToolRegistry.init_all(config)` 执行各工具的初始化函数，最后构造 `Agent`。

### 两层工具架构

工具分为**透传工具**（旧）和**意图工具**（新），当前共存，system prompt 引导 LLM 优先使用意图工具：

| 类型 | 工具名 | LLM 传参 | 执行方式 |
|------|--------|---------|---------|
| 透传 | `tapd_cli` | `{"args": ["timesheet", "list", "--workspace-id", "755"]}` | 直接调 tapd.exe |
| 透传 | `svn` | `{"command": "log", "path": "...", "extra_args": ["-l", "10"]}` | 直接调 svn.exe |
| 意图 | `tapd_query` | `{"action": "timesheet_list", "owner": "傅政"}` | 委托 ExecutionEngine |
| 意图 | `svn_op` | `{"action": "log", "project": "harmony", "extra": {"limit": 10}}` | 委托 ExecutionEngine |

意图工具的参数是结构化字段（`action`、`owner`、`workspace_id` 等），不含 CLI 语法。不传 `workspace_id` 时引擎自动触发 `for_each_workspace` 全覆盖模式。

### Agent 核心循环

```
用户输入 → 加入历史 → trim buffer（有则调 LLM 摘要压缩 + 提取 Profile）
  ↓
┌─ for round in 1..max_tool_rounds:
│   LLM.chat(messages, tools, system_prompt)
│   ├─ 无 tool_calls → 返回文本
│   └─ 有 tool_calls → 循环检测(3次相同停止)
│                     → asyncio.gather 并行执行（120s超时）
│                     → 工具结果加入历史 → 继续循环
└─ 超限 → 最后一次 LLM 调用（tools=[]）基于已有数据总结回答
```

工具结果**不再压缩**——每轮返回的完整 JSON 原样保留在历史中，让 LLM 在后续轮次充分理解上下文。轮数耗尽时不直接返回错误，而是额外调一次不带 tools 的 LLM，让它基于已获取的所有数据给出最佳回答。

**内置命令**（`main.py` 输入循环中直接处理，不走 Agent）：

| 命令 | 行为 |
|------|------|
| `/help` | 显示可用命令与用法示例 |
| `/chain` | 从消息历史提取上一轮工具调用链并格式化输出 |
| `/clear` | 调用 `agent.clear_history()` 清空内存消息并删除持久化文件 |
| `/clear-profile` | 调用 `agent.clear_profile()` 清空长期用户档案 |
| `/exit` | 调用 `agent.save_history()` 落盘后退出 |
| `skill install <url>` | git clone 外部 Skill 到 `~/.nimo/skills/` |
| `skill list` | 列出已安装的 Skill |
| `skill uninstall <name>` | 删除已安装的 Skill |

### Skill 系统

外部 Skill 是**自包含的领域能力包**，从 GitHub clone 到 `~/.nimo/skills/` 后即插即用。Skill 不替代 Tool，而是另一个维度——Tool 是"手"，Skill 是"方法论"。

**Skill 目录结构**（兼容 WorkBuddy `skill.yml` 和 Claude Code `SKILL.md` frontmatter 两种格式）：
```
~/.nimo/skills/zhengxi-views/
├── skill.yml       ← WorkBuddy 格式清单（name/description/keywords/scripts）
├── SKILL.md        ← 行为指令（激活后注入 system prompt）
├── scripts/        ← 可执行脚本（通过 skill_run 工具调用）
└── references/     ← 知识库文件
```

**三级降级解析**：`SkillRegistry.discover()` 按优先级尝试解析——① `skill.yml` → ② `SKILL.md` YAML frontmatter → ③ 目录名 + README.md 兜底。永不加载失败。

**渐进式披露**：L1 元数据始终在 system prompt（~100 字/Skill）→ L2 完整指令在激活后注入 → L3 脚本输出按需获取。避免多 Skill 时撑爆上下文窗口。

**关键设计**：`skill_run` 调用时自动激活 Skill（静默调用 `registry.activate()`），因为 LLM 经常跳过 `activate_skill` 直接调 `skill_run`。激活后的指令在下轮 LLM 调用中生效。

**循环导入注意**：`skill_tools.py` 不能模块级导入 `SkillRegistry`（`nimo.tools` auto-discovery → `skill_tools` → `nimo.skill.registry` → `nimo.tools.registry` 形成循环）。使用 `_get_skill_registry()` 延迟导入。

### 工具注册系统

`@register_tool(name, description, parameters)` 装饰器将函数注册到 `ToolRegistry` 单例。启动时 `build_tool_definitions()` 生成 OpenAI function calling 格式传给 LLM，运行时 `execute(name, args)` 根据 tool_call 分发。

`tools/__init__.py` 通过 `pkgutil.iter_modules` 自动发现并加载 `nimo.tools` 包下所有不以 `_` 开头的模块，无需手动 import。需要初始化的工具通过 `ToolRegistry.register_init()` 注册初始化函数，`main.py` 中的 `build_agent()` 调用 `init_all(config)` 统一执行。

新增工具只需：在 `nimo/tools/` 下创建模块 → 写函数 + 加 `@register_tool` 装饰器。不改任何中央配置。

### System Prompt

`nimo/prompts/system.md` 定义 LLM 的行为准则和回复格式。包含 `## 工具选择` 段，引导 LLM 优先使用 `tapd_query`/`svn_op` 意图工具，仅在不满足需求时回退到 `tapd_cli`/`svn`。`Agent._load_system_prompt()` 通过 `Path(__file__)` 定位文件，读取后追加当前日期和可用工具列表，作为 system message 传入每次 LLM 调用。

### 外部二进制

`bin/` 目录存放工具依赖的可执行文件（均不入 git）：

| 文件 | 来源 | 用途 |
|------|------|------|
| `tapd.exe` | [tapd-ai-cli](https://github.com/studyzy/tapd-ai-cli) | TAPD 命令行操作 |
| `svn.exe` | Apache Subversion | SVN 命令行（log/diff/blame/update/commit 等） |
| `svnadmin.exe` | Apache Subversion | 创建 SVN 仓库（repocreate 命令） |

工具模块通过 `Path(__file__).resolve().parent.parent.parent / "bin" / "xxx.exe"` 自动定位，不依赖系统 PATH。换机器只需将对应的 exe 放到 `bin/` 目录。

认证：tapd 通过 `TAPD_ACCESS_TOKEN` 环境变量注入，svn 复用 Windows 系统级 TortoiseSVN 凭据缓存（`%APPDATA%\Subversion\auth\`）。

### 核心模块职责

| 模块 | 关键设计 |
|------|---------|
| `agent.py` | `Agent.run()` 编排循环：LLM 调用捕获 `LLMError` 防崩溃、`asyncio.gather` 并行执行工具 + 120s 超时、连续 3 次相同调用自动终止；轮数耗尽时最后调一次 LLM（tools=[]）基于已有数据总结，不再直接报错；`_trimmed_llm_call()` 复用；Profile 上下文循环外注入；`last_usage` 属性暴露 token 统计 |
| `main.py` | 输入循环 + 内置命令（`/help` `/chain` `/clear` `/exit`）；`_Spinner` 后台线程进度动画（100ms 旋转 + 实时秒数）；`_input_with_poll` 等待输入期间轮询调度通知；readline 历史支持 |
| `llm/client.py` | `LLMClient.chat()` 封装 DeepSeek（兼容 OpenAI SDK），4次尝试（1+3重试），仅对 RateLimitError/APITimeoutError/InternalServerError 重试 |
| `memory/history.py` | `ConversationHistory` 滑动窗口截断 + `_trimmed_buffer` 暂存被 trim 消息 + `get_trimmed()`/`pop_trimmed()` 分离 peek/pop 语义；`from_dict()` 恢复后自动 `_trim()` 确保加载即裁剪；`save()` 原子写入（.tmp → .json 防损坏）；JSON 文件持久化（`~/.nimo/sessions/`） |
| `memory/profile.py` | `UserProfile` 结构化长期记忆（`dict[str,str]` 键值对），独立于滑动窗口，`~/.nimo/profile.json` 持久化；Agent 在 trim 时调 LLM 提取事实（`_maybe_extract_profile()`），注入到每条消息头部 `[用户信息]` |
| `tools/registry.py` | `ToolRegistry` 单例 + `@register_tool` 装饰器 + `register_init()`/`init_all()` 通用初始化机制；`reset()` 用于测试隔离 |
| `engine.py` | `ExecutionEngine` 单例，编排与执行分离的核心。`execute(intent)` 接收 `Intent` 数据类，按 `tool` 分发到 `_execute_tapd`/`_execute_svn`。TAPD 执行分 direct 和 `for_each_workspace` 两种模式，后者先 `workspace list` 再逐个查询并合并结果（部分成功算成功）。`_run_tapd`/`_run_svn` 原子操作通过 `asyncio.create_subprocess_exec` 调用外部二进制。`Intent`（tool/action/params）和 `StepResult` 均为 dataclass |
| `tools/tapd.py` | `init_tapd()` 存储配置；工具 `tapd_cli` 透传 CLI 参数调用外部 `tapd.exe`；`timesheet list` 自动追加 `--limit 200`；`_validate_args()` 子命令白名单 + 路径遍历校验；**关键**：按人员查工时须用 `--owner <中文显示名>`，不可用 `--filter username=` |
| `tools/tapd_intent.py` | 工具 `tapd_query`，结构化参数（action/owner/workspace_id/entity_id 等），构造 `Intent` 后委托 `ExecutionEngine.execute()` |
| `tools/svn_intent.py` | 工具 `svn_op`，结构化参数（action/path/project/url/extra），构造 `Intent` 后委托 `ExecutionEngine.execute()` |
| `config.py` | `load_config()` 加载 YAML + `_env_override()` 环境变量覆盖（`LLM_API_KEY`、`TAPD_ACCESS_TOKEN`）；`TortoiseSvnConfig` 支持多项目别名（paths dict + 单项目自动匹配） |
| `display.py` | **配色体系**：`CYAN`(#30C0E0)品牌蓝=Logo/标题/系统侧结构，`BLUE_DEEP`(#1F9DB8)=框线，`GRAY_MUTED`(#B0B0B0)=元数据，`GRAY_SUBTLE`(#B8B8B8)=低优提示。橙色仅限用户输入提示符 `❯`，红色=错误。`print_welcome()` 6:4 双栏欢迎画面，`print_response_box()` rich Markdown 渲染回复 + 品牌色边框 + Token 统计 |
| `tools/tortoisesvn.py` | `init_tortoisesvn()` 存储配置并注入项目名到工具描述；`svn` 工具参数含 command/path/project/url/extra_args；`_resolve_path()` 三级优先级（显式 path > 项目名 > 单项目自动匹配 > 报错）；`_validate_args()` 命令白名单 + 路径遍历防护；svn 命令用 `svn.exe`，repocreate 用 `svnadmin.exe`；输出自动 GBK/UTF-8 双编码解码 |
| `skill/registry.py` | `SkillRegistry` 单例 + `SkillMeta` 数据类。`discover()` 三级降级解析外部 Skill 目录；`activate()` 加载 SKILL.md 返回摘要；`deactivate()` 清空；`run_script()` 白名单校验 + 路径遍历防护 + `env={}` 环境隔离 + 120s 超时；`list_meta()` 返回 L1 摘要；`get_active_instructions()` 供 Agent 注入 system prompt |
| `skill/installer.py` | `Installer` 类：`install(url)` git clone + requirements.txt 检测（失败抛 `RuntimeError`）；`uninstall(name)` 路径遍历防护 + `shutil.rmtree`；`list_installed()` 返回已安装 Skill 列表 |
| `tools/skill_tools.py` | 注册 3 个 LLM 可见工具：`activate_skill`（激活并返回摘要）、`deactivate_skill`（清空激活）、`skill_run`（执行白名单脚本，调用时自动激活 Skill）。**关键**：使用 `_get_skill_registry()` 延迟导入打破循环依赖 |
| `tools/python_exec.py` | 工具 `python_exec`，接收 `code` 字符串，通过 `asyncio.create_subprocess_exec(sys.executable, "-c", code)` 动态执行 Python 代码，120s 超时。让 LLM 能写代码做数据处理、API 调用等，不与任何 Skill 耦合 |
| `tools/schedule.py` | 工具 `schedule`（action: list/add/remove/enable/disable），管理定时任务，支持 cron 表达式和 delay_minutes 延迟两种模式，持久化到 `~/.nimo/schedules.json`。`Scheduler` 类在后台每 60s 轮询，到期自动触发 Agent 执行。`main.py` 启动时创建 `Scheduler` 并 `asyncio.create_task` 运行

### 配置

`config.yaml`（不入 git）仅需两段必填：

```yaml
llm:
  api_key: "sk-xxx"
  base_url: "https://api.deepseek.com"
  model: "deepseek-chat"
  max_tool_rounds: 10
  history_rounds: 10
  temperature: 0.3
  history_persist: true     # 会话历史持久化（~/.nimo/sessions/default.json）
  history_summarize: true   # 轮次超限时 LLM 摘要压缩旧消息
  profile_extract: true     # 从对话中提取用户信息存入长期档案（~/.nimo/profile.json）
tapd:
  api_base: "https://api.tapd.cn"
  access_token: "个人令牌"
```

`tapd.nick`、`tapd.company_id`、`tapd.owner` 为可选字段。`schedules.enabled` 控制定时任务功能开关（默认 false）。

`tortoisesvn` 段完全可选，用项目别名管理多个工作副本：

```yaml
tortoisesvn:
  paths:
    harmony: 'C:\Users\user\source\HarmonyOS'
    confsdk: 'C:\Users\user\source\Confsdk_Daily'
```

单项目时自动匹配无需指定 project 参数，多项目时需 LLM 传 project 选择。旧字段 `wc_path` 兼容自动转为 `paths.default`。

### 测试

- **Agent 循环**通过 mock `LLMClient.chat` 和 `ToolRegistry.execute` 测试，覆盖正常路径及 JSON 解析失败、系统提示文件缺失等错误路径
- **单例 Registry**测试通过 `reset()` 保证隔离
- **TAPD 工具测试**在模块级 import（`@register_tool` 只触发一次），mock `asyncio.create_subprocess_exec` 验证 CLI 调用；`_validate_args()` 校验逻辑单独测试
- **SVN 工具测试**同样模式 mock `asyncio.create_subprocess_exec`；覆盖多项目、单项目自动匹配、显式 path 优先级、无配置报错；`_resolve_path()` 和 `_build_args()` 独立测试
- **Engine 测试**通过 mock `asyncio.create_subprocess_exec`，覆盖 direct 模式、`for_each_workspace` 模式（正常/部分失败/全失败）、SVN direct 模式、引擎未初始化、未知 action 等场景。`ExecutionEngine.reset()` 保证测试隔离
- **意图工具测试**（`test_tapd_intent.py`、`test_svn_intent.py`）验证工具→引擎委托链路，mock subprocess 验证参数传递和结果返回
- **Skill 系统测试**（`test_skill.py`）通过 `tempfile.TemporaryDirectory` 创建临时 Skill 目录，覆盖 discover 三级降级、activate/deactivate、run_script 安全边界、Installer 列表/卸载/路径遍历。`SkillRegistry.reset()` fixture 保证隔离
- **python_exec 测试**（`test_python_exec.py`）mock `asyncio.create_subprocess_exec`，覆盖正常执行、stderr 错误、超时、无输出、工具注册验证
- **Schedule 测试**（`test_schedule.py`）覆盖 cron 校验（边界值/非法格式）、参数校验（action 白名单/task_id 格式/prompt 长度/cron 与 delay 互斥）、任务 CRUD（add/remove/enable/disable/list）、cron 匹配逻辑、once 任务到期判定
