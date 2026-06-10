# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Nimo 是一个 CLI AI Agent，基于 DeepSeek function calling。用户通过自然语言对话执行实际任务（首版支持 TAPD 查项目和填工时）。项目目标是实践 AI Agent 开发。

## 常用命令

```bash
# 运行
python -m nimo.main          # 需要项目根目录有 config.yaml

# 全部测试
pytest tests/ -v

# 单个测试文件
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
        → tools/tapd.py (init + 触发 @register_tool)
```

### Agent 核心循环

```
用户输入 → 加入历史
  ↓
┌─ for round in 1..max_tool_rounds:
│   LLM.chat(messages, tools, system_prompt)
│   ├─ 无 tool_calls → 返回文本，结束
│   └─ 有 tool_calls → 执行工具，结果加入历史，继续循环
└─ 超限 → 返回错误提示
```

每个环节有 `print()` 输出，运行时可见完整流程：轮次、LLM 状态、工具名/参数、执行结果。

### 工具注册系统

`@register_tool(name, description, parameters)` 装饰器将函数注册到 `ToolRegistry` 单例。启动时 `build_tool_definitions()` 生成 OpenAI function calling 格式传给 LLM，运行时 `execute(name, args)` 根据 tool_call 分发。

新增工具只需：写函数 + 加装饰器 + import 该模块。不改任何中央配置。

### 核心模块职责

| 模块 | 关键设计 |
|------|---------|
| `agent.py` | `Agent.run()` 编排循环，`print()` 输出流程供学习观察 |
| `llm/client.py` | `LLMClient.chat()` 封装 DeepSeek（兼容 OpenAI SDK），4次尝试（1+3重试），仅对 RateLimitError/APITimeoutError/InternalServerError 重试 |
| `memory/history.py` | `ConversationHistory` 按轮次滑动窗口截断，每轮=user消息+后续assistant/tool消息 |
| `tools/registry.py` | `ToolRegistry` 单例 + `@register_tool` 装饰器；`reset()` 用于测试隔离 |
| `tools/tapd.py` | 模块级 `_config`/`_client`，`init_tapd()` 初始化；查项目列表/填工时两个工具 |
| `config.py` | `load_config()` 加载 YAML + `_env_override()` 环境变量覆盖（`LLM_API_KEY`、`TAPD_ACCESS_TOKEN`） |

### 配置

`config.yaml`（不入 git）仅需两段必填：

```yaml
llm:
  api_key: "sk-xxx"
  base_url: "https://api.deepseek.com"
  model: "deepseek-chat"
  max_tool_rounds: 5
  history_rounds: 10
tapd:
  api_base: "https://api.tapd.cn"
  access_token: "个人令牌"
```

`tapd.nick`、`tapd.company_id`、`tapd.owner` 为可选字段。

### 测试

- **工具函数**可脱离 LLM 独立测试（mock `_api_get`/`_api_post`）
- **Agent 循环**通过 mock `LLMClient.chat` 和 `ToolRegistry.execute` 测试
- **单例 Registry**测试通过 `autouse=True` fixture + `reset()` 保证隔离
- **TAPD 工具测试**在模块级 import（`@register_tool` 只触发一次），内部函数用 `patch.object` mock
