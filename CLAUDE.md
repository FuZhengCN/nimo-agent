# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Nimo 是一个 CLI AI Agent，基于 DeepSeek function calling。用户通过自然语言对话执行 TAPD 操作（查项目、需求/任务/缺陷 CRUD、填工时、评论、迭代等）。项目目标是实践 AI Agent 开发。

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
pytest tests/test_welcome.py -v
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
        → welcome.py
        → tools/tapd.py (init + 触发 @register_tool)
```

`main()` 先 `load_config()`，再 `build_agent(config)` + `print_welcome()`，最后进入输入循环。`build_agent()` 接收 `Config` 对象（非路径字符串），负责 `init_tapd()` + 构造 `Agent`。

### Agent 核心循环

```
用户输入 → 加入历史 → 检查 trim buffer（有则调 LLM 摘要压缩）
  ↓
┌─ for round in 1..max_tool_rounds:
│   LLM.chat(messages, tools, system_prompt)
│   ├─ 无 tool_calls → 返回文本，结束
│   └─ 有 tool_calls → 执行工具，结果加入历史，继续循环
└─ 超限 → 返回错误提示
```

运行时：`agent.run()` 前显示灰色 `⏳ 思考中...` 提示，完成后清除，回复包在蓝青色 ANSI 卡片框（`print_response_box()`）内输出。输入提示符 `❯` 和键入文字为暖橙色（RGB 242,138,56）。HTTP 请求日志（httpx/openai）已静默到 WARNING 级别，不污染控制台。

**内置命令**（`main.py` 输入循环中直接处理，不走 Agent）：

| 命令 | 行为 |
|------|------|
| `/help` | 显示可用命令与用法示例 |
| `/clear` | 调用 `agent.clear_history()` 清空内存消息并删除持久化文件 |
| `/exit` | 调用 `agent.save_history()` 落盘后退出 |

### 工具注册系统

`@register_tool(name, description, parameters)` 装饰器将函数注册到 `ToolRegistry` 单例。启动时 `build_tool_definitions()` 生成 OpenAI function calling 格式传给 LLM，运行时 `execute(name, args)` 根据 tool_call 分发。

新增工具只需：写函数 + 加装饰器 + import 该模块。不改任何中央配置。

### System Prompt

`nimo/prompts/system.md` 定义 LLM 的行为准则和 `tapd_cli` 命令参考。`Agent._load_system_prompt()` 通过 `Path(__file__)` 定位文件（非硬编码相对路径），读取后作为 system message 传入每次 LLM 调用。

### 外部二进制

项目 `bin/tapd.exe`（来自 [tapd-ai-cli](https://github.com/studyzy/tapd-ai-cli)，不入 git）。`tapd_cli` 工具通过 `_TAPD_BIN`（相对模块路径自动定位）调用该二进制，认证信息通过环境变量 `TAPD_ACCESS_TOKEN` 注入。换机器只需从 GitHub Release 下载 `tapd.exe` 放到 `bin/` 目录。

### 核心模块职责

| 模块 | 关键设计 |
|------|---------|
| `agent.py` | `Agent.run()` 编排循环；`_maybe_summarize_trimmed()` 在历史超窗时调 LLM 生成摘要（`_build_summary_prompt()` 构建请求，`SUMMARY_SYSTEM_PROMPT` 控制摘要风格）；`save_history()`/`clear_history()` 管理持久化 |
| `llm/client.py` | `LLMClient.chat()` 封装 DeepSeek（兼容 OpenAI SDK），4次尝试（1+3重试），仅对 RateLimitError/APITimeoutError/InternalServerError 重试 |
| `memory/history.py` | `ConversationHistory` 滑动窗口截断 + `_trimmed_buffer` 暂存被 trim 消息 + `pop_trimmed()`/`set_summary()` 供 Agent 调度摘要压缩 + `to_dict()`/`from_dict()`/`save()`/`load()` JSON 文件持久化（`~/.nimo/sessions/`） |
| `memory/profile.py` | `UserProfile` 结构化长期记忆（`dict[str,str]` 键值对），独立于滑动窗口，`~/.nimo/profile.json` 持久化；Agent 在 trim 时调 LLM 提取事实（`_maybe_extract_profile()`），注入到每条消息头部 `[用户信息]` |
| `tools/registry.py` | `ToolRegistry` 单例 + `@register_tool` 装饰器；`reset()` 用于测试隔离 |
| `tools/tapd.py` | `init_tapd()` 存储配置；唯一工具 `tapd_cli` 调用外部 `tapd.exe` 二进制；`_validate_args()` 子命令白名单 + 路径遍历校验防止 prompt 注入 |
| `config.py` | `load_config()` 加载 YAML + `_env_override()` 环境变量覆盖（`LLM_API_KEY`、`TAPD_ACCESS_TOKEN`） |
| `welcome.py` | `print_welcome(model, cwd, version)` 启动欢迎画面 + `print_response_box()` 回复卡片；自动检测终端宽度，左 Logo + 右 Tips 双栏布局，24bit ANSI 真彩色 |

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
tapd:
  api_base: "https://api.tapd.cn"
  access_token: "个人令牌"
```

`tapd.nick`、`tapd.company_id`、`tapd.owner` 为可选字段。

### 测试

- **Agent 循环**通过 mock `LLMClient.chat` 和 `ToolRegistry.execute` 测试，覆盖正常路径及 JSON 解析失败、系统提示文件缺失等错误路径
- **单例 Registry**测试通过 `reset()` 保证隔离
- **TAPD 工具测试**在模块级 import（`@register_tool` 只触发一次），mock `asyncio.create_subprocess_exec` 验证 CLI 调用；`_validate_args()` 校验逻辑单独测试
- **Welcome 模块**测试覆盖常量、ANSI 颜色、边框宽度、行构建、`print_welcome` 端到端输出；`sys.stdout` 操作用 `try/finally` 保护
