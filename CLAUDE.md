# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Nimo 是一个 CLI AI Agent，基于 DeepSeek function calling。用户通过自然语言对话执行 TAPD 操作（查项目、需求/任务/缺陷 CRUD、填工时、评论、迭代等）和 SVN 版本控制（查日志、差异对比、更新提交等）。项目目标是实践 AI Agent 开发。

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
        → config.py
        → display.py

        → tools/__init__.py (pkgutil 自动发现工具模块)
            → tools/tapd.py (@register_tool 注册，外部 tapd.exe)
            → tools/tortoisesvn.py (@register_tool 注册，外部 svn.exe/svnadmin.exe)
```

`main()` 先 `load_config()`，再 `build_agent(config)` + `print_welcome()`，最后进入输入循环。`build_agent()` 调用 `ToolRegistry.init_all(config)` 执行各工具的初始化函数，再构造 `Agent`。

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

### 工具注册系统

`@register_tool(name, description, parameters)` 装饰器将函数注册到 `ToolRegistry` 单例。启动时 `build_tool_definitions()` 生成 OpenAI function calling 格式传给 LLM，运行时 `execute(name, args)` 根据 tool_call 分发。

`tools/__init__.py` 通过 `pkgutil.iter_modules` 自动发现并加载 `nimo.tools` 包下所有不以 `_` 开头的模块，无需手动 import。需要初始化的工具通过 `ToolRegistry.register_init()` 注册初始化函数，`main.py` 中的 `build_agent()` 调用 `init_all(config)` 统一执行。

新增工具只需：在 `nimo/tools/` 下创建模块 → 写函数 + 加 `@register_tool` 装饰器。不改任何中央配置。

### System Prompt

`nimo/prompts/system.md` 定义 LLM 的行为准则和回复格式（已精简至 ~1100 字符，包含反重复查询规则）。`Agent._load_system_prompt()` 通过 `Path(__file__)` 定位文件，读取后追加当前日期（`YYYY年M月D日 星期X`）和可用工具列表，作为 system message 传入每次 LLM 调用。

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

| `llm/client.py` | `LLMClient.chat()` 封装 DeepSeek（兼容 OpenAI SDK），4次尝试（1+3重试），仅对 RateLimitError/APITimeoutError/InternalServerError 重试 |
| `memory/history.py` | `ConversationHistory` 滑动窗口截断 + `_trimmed_buffer` 暂存被 trim 消息 + `get_trimmed()`/`pop_trimmed()` 分离 peek/pop 语义；`from_dict()` 恢复后自动 `_trim()` 确保加载即裁剪；`save()` 原子写入（.tmp → .json 防损坏）；JSON 文件持久化（`~/.nimo/sessions/`） |
| `memory/profile.py` | `UserProfile` 结构化长期记忆（`dict[str,str]` 键值对），独立于滑动窗口，`~/.nimo/profile.json` 持久化；Agent 在 trim 时调 LLM 提取事实（`_maybe_extract_profile()`），注入到每条消息头部 `[用户信息]` |
| `tools/registry.py` | `ToolRegistry` 单例 + `@register_tool` 装饰器 + `register_init()`/`init_all()` 通用初始化机制；`reset()` 用于测试隔离 |
| `tools/tapd.py` | `init_tapd()` 存储配置；唯一工具 `tapd_cli` 调用外部 `tapd.exe` 二进制；`timesheet list` 自动追加 `--limit 200` 防截断；`_validate_args()` 子命令白名单 + 路径遍历校验防止 prompt 注入；**关键**：按人员查工时须用 `--owner <中文显示名>`，不可用 `--filter username=` |
| `config.py` | `load_config()` 加载 YAML + `_env_override()` 环境变量覆盖（`LLM_API_KEY`、`TAPD_ACCESS_TOKEN`）；`TortoiseSvnConfig` 支持多项目别名（paths dict + 单项目自动匹配） |
| `display.py` | `print_welcome(model, cwd, version)` 启动欢迎画面（24bit ANSI 真彩色，6:4 双栏）；`print_response_box(text, token_summary, tool_counts)` 用 `rich.Markdown` + 无色 Theme 渲染回复，仅上下品牌色边框，右上角展示工具调用统计，token 显示在底边框右侧（`P:X C:Y` 格式）；Theme 模块级常量避免每次重建 |
| `tools/tortoisesvn.py` | `init_tortoisesvn()` 存储配置并注入项目名到工具描述；`svn` 工具参数含 command/path/project/url/extra_args；`_resolve_path()` 三级优先级（显式 path > 项目名 > 单项目自动匹配 > 报错）；`_validate_args()` 命令白名单 + 路径遍历防护；svn 命令用 `svn.exe`，repocreate 用 `svnadmin.exe`；输出自动 GBK/UTF-8 双编码解码 |

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

`tapd.nick`、`tapd.company_id`、`tapd.owner` 为可选字段。

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
- **Display 模块**测试覆盖常量、ANSI 颜色、边框宽度、行构建、`print_welcome` 端到端输出；`sys.stdout` 操作用 `try/finally` 保护
