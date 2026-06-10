# Nimo Agent 设计文档

**日期**：2026-06-10
**状态**：设计中

---

## 1. 项目概述

Nimo 是一个 CLI 对话机器人，基于 LLM function calling 实现 AI Agent，用户通过自然语言对话来执行实际任务（首版聚焦 TAPD 操作）。项目目标是实践 AI Agent 开发，架构从小做起，预留扩展。

### 核心约束

- 交互方式：命令行（CLI）
- LLM 大脑：DeepSeek API（兼容 OpenAI SDK）
- 首版能力：TAPD 查项目列表 + 填工时
- 鉴权方式：TAPD 个人令牌（Personal Access Token）
- 架构要求：工具可插拔，新增能力不改 Agent 核心

---

## 2. 项目结构

```
Nimo/
├── nimo/
│   ├── __init__.py
│   ├── main.py              # CLI 入口
│   ├── agent.py             # Agent 核心循环（编排者）
│   ├── config.py            # 配置加载
│   ├── prompts/
│   │   └── system.md        # System Prompt 模板
│   ├── llm/
│   │   ├── __init__.py
│   │   └── client.py        # DeepSeek API 封装 + 容错/重试
│   ├── memory/
│   │   ├── __init__.py
│   │   └── history.py       # 对话历史管理
│   └── tools/
│       ├── __init__.py
│       ├── registry.py      # 工具注册表
│       └── tapd.py          # TAPD 工具
├── config.example.yaml      # 配置模板
├── requirements.txt
└── README.md
```

### 模块职责

| 模块 | 职责 | 依赖 |
|------|------|------|
| `main.py` | CLI 输入/输出循环，启动入口 | agent, config |
| `agent.py` | Agent 核心循环，编排 LLM 调用和工具执行 | llm, tools, memory |
| `config.py` | 加载 config.yaml + 环境变量覆盖 | 无 |
| `prompts/system.md` | Agent 身份定义、行为约束、能力描述 | 无 |
| `llm/client.py` | DeepSeek API 封装，超时+指数退避重试 | config |
| `memory/history.py` | 对话消息的增删查、滑动窗口截断 | 无 |
| `tools/registry.py` | 装饰器注册、tool definitions 生成、工具分发 | 无 |
| `tools/tapd.py` | TAPD API：查项目列表、填工时 | registry, config |

---

## 3. Agent 核心循环

```
用户输入
  │
  ▼
┌─────────────────┐
│ Agent Loop（最多 N 轮）      │
│                 │
│ 1. 构建消息列表    │  system prompt + 历史 + 用户输入
│       │          │
│       ▼          │
│ 2. 调用 LLM       │  带 tool definitions
│       │          │
│       ▼          │
│ 3. 解析响应       │
│   ├─ 无 tool_calls → 返回文本给用户，结束循环
│   └─ 有 tool_calls → 继续
│       │          │
│       ▼          │
│ 4. 并行执行工具    │  多个 tool_calls 并发执行
│       │          │
│       ▼          │
│ 5. 结果加入消息    │  assistant(tool_calls) + tool(result)
│       │          │
│       └──→ 回到步骤 2
└─────────────────┘
```

### 关键规则

- **System prompt** 在 API 调用时作为独立字段传入（不在 messages 数组中）
- **工具调用判断**：只看 `tool_calls` 是否为空，非空则执行工具继续循环
- **并行工具调用**：LLM 单次响应可能返回多个 tool_calls，必须并发执行
- **最大轮数**：可配置（默认 5 轮），防止死循环
- **工具失败处理**：错误信息作为 tool result 原样返回 LLM，由 LLM 自行决定重试或告知用户，Agent 循环不做重试决策
- **消息追加规则**：每轮工具调用后将 assistant 消息（含 tool_calls）和对应的 tool 消息成对加入历史

---

## 4. 工具注册表

装饰器声明式注册，运行时动态生成 tool definitions。

```python
# 装饰器注册
@register_tool(
    name="tapd_list_projects",
    description="获取当前用户在 TAPD 中有权限参与的项目列表",
    parameters={
        "type": "object",
        "properties": {},
    }
)
async def tapd_list_projects() -> ToolResult:
    ...

# registry 职责：
# 1. 启动时收集所有 @register_tool 装饰的函数
# 2. 生成符合 OpenAI/DeepSeek function calling 格式的 tools 列表
# 3. 运行时根据 tool_call 的 name 找到对应函数并调用
# 4. 新工具只需加文件 + 装饰器，无需改任何中央配置
```

### ToolResult

```python
@dataclass
class ToolResult:
    success: bool
    data: Any = None
    error: str | None = None
```

---

## 5. System Prompt 管理

`prompts/system.md` 独立文件，启动时加载。内容定义：

- Agent 身份（"你是 Nimo，一个帮助用户完成日常工作的助手"）
- 能力边界（"你当前能执行 TAPD 相关操作"）
- 行为约束（"不确定参数时主动询问用户"）
- 可用工具由 registry 动态注入，不写在模板里

---

## 6. 对话历史管理

`memory/history.py` 管理消息列表，三个核心接口：

```python
class ConversationHistory:
    def add(self, message: Message) -> None: ...
    def get_messages(self) -> list[Message]: ...
    def trim(self, max_rounds: int) -> None: ...
```

- **存储**：首版内存列表，接口抽象后续可替换为文件/SQLite
- **截断策略**：按轮次（一轮 = 用户消息 + 完整的 assistant 回复链），保留最近 N 轮（默认 10）
- **首版不做精确 token 计算**：避免引入 tokenizer 依赖

---

## 7. LLM 客户端与容错

`llm/client.py` 封装 DeepSeek API 调用：

- 使用 `openai` SDK（DeepSeek 兼容 OpenAI 接口格式）
- `chat()` 方法：传入 messages + tools → 返回 LLM 响应
- **容错**：超时 60s + 指数退避重试（最多 3 次），可重试错误（429/5xx）才重试，4xx 直接抛出
- 异常统一转为自定义 `LLMError`

---

## 8. 配置管理

```yaml
# config.yaml（不入 git）
llm:
  api_key: "sk-xxx"
  base_url: "https://api.deepseek.com"
  model: "deepseek-chat"
  max_tool_rounds: 5
  history_rounds: 10

tapd:
  api_base: "https://api.tapd.cn"
  access_token: "个人令牌"
  nick: "TAPD昵称"
  company_id: "公司ID"
  owner: "用户名"
```

- 启动时加载一次，全局单例
- 环境变量覆盖（`LLM_API_KEY`、`TAPD_ACCESS_TOKEN` 等）
- `config.example.yaml` 作为模板，含占位值
- 不做热加载，改配置需重启

---

## 9. TAPD 工具

鉴权：`Authorization: Bearer <access_token>`

统一请求封装 `TapdClient`，含 `get()` / `post()` 方法和统一错误处理。

### 工具 1：查项目列表

- **对应 API**：`GET /workspaces/user_participant_projects`
- **API 参数**：`nick`（必填）、`company_id`（必填）
- **无分页**，一次返回全部
- `nick` 和 `company_id` 从 config 注入，工具函数无用户参数

### 工具 2：填工时

- **对应 API**：`POST /timesheets`
- **API 参数**：

| 参数 | 必填 | 说明 |
|------|------|------|
| `workspace_id` | 是 | 项目 ID（integer） |
| `entity_type` | 是 | story / task / bug |
| `entity_id` | 是 | 对象 ID（integer） |
| `timespent` | 是 | 工时（小时），字符串 |
| `owner` | 是 | 创建人，从 config 注入 |
| `spentdate` | 否 | 日期 YYYY-MM-DD |
| `memo` | 否 | 工时内容描述 |

- ⚠️ 同一 entity_type + entity_id + spentdate + owner 不可重复

---

## 10. CLI 入口

```python
async def main():
    config = load_config("config.yaml")
    agent = Agent(config)
    print("Nimo 就绪，输入 /exit 退出")
    while True:
        user_input = input("> ")
        if user_input == "/exit":
            break
        response = await agent.run(user_input)
        print(response)
```

交互示例：

```
> 帮我查一下我参与的项目
你参与了以下3个项目：
1. TAPD平台 (ID: 755)
2. 游戏项目A (ID: 10158231)
3. 内部工具组 (ID: 10022001)

> 在游戏项目A里填2小时工时，内容是需求评审
已填写：2026-06-10，需求 #xxx，2小时 — "需求评审"
```

---

## 11. 外部依赖

```
openai>=1.0.0        # DeepSeek 兼容 OpenAI SDK
httpx>=0.27.0        # HTTP 客户端（TAPD API 调用）
pyyaml>=6.0          # 配置文件解析
```

---

## 12. 非功能约束

- **错误处理**：用户可见错误用中文描述，技术细节记日志
- **安全**：config.yaml + .gitignore 防止密钥泄露
- **测试**：工具函数可脱离 LLM 独立测试；Agent 循环可用 mock LLM 测试
- **日志**：LLM 调用和工具执行的关键节点打印日志，方便调试
