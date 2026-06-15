# Nimo ACP 协议接入设计

日期：2026-06-15

## 背景

Nimo 在 JetBrains IDE 中注册为自定义 Agent 时，IDE 期望 Agent 遵循 Agent Client Protocol (ACP) 进行通信。当前 Nimo 是纯 CLI 工具，启动后等待键盘输入，无法响应 IDE 通过 stdin 发送的 JSON-RPC 握手请求，导致 "ACP initialize failed: Initialize handshake timed out after 30s"。

## 协议概要

ACP = JSON-RPC 2.0 over stdin/stdout。消息帧：Content-Length 头 + JSON body。
**stdout 是纯协议通道，所有日志/打印必须走 stderr。**

## 目标

- 支持 `--acp` 参数启动 ACP 模式，让 IDE 能正常完成握手并调用 Nimo
- CLI 模式零影响
- 零外部依赖（不使用 `agent-client-protocol` SDK）
- 新增代码控制在 150 行以内

## 架构

```
IDE (JetBrains)         Nimo Process
                        main.py
stdin ─────────→          ├── --acp ?
stdout ←────────          │   ├─ YES → AcpServer.run()
stderr (日志)              │   └─ NO  → CLI 循环（不变）
                          └── AcpServer
                               ├─ 从 stdin 解析 JSON-RPC
                               ├─ 分发到 handler
                               │   ├─ initialize
                               │   ├─ session/new
                               └─── session/prompt → Agent.run()
                               └─ 向 stdout 写 JSON-RPC 响应
```

### 新增文件

`nimo/acp_server.py` — ACP JSON-RPC 服务器

### 修改文件

`nimo/main.py` — 加 `--acp` 参数检测分支（约 10 行）

## 消息格式

### 请求帧

```
Content-Length: 156\r\n
\r\n
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{...}}
```

### 响应帧

```
Content-Length: 200\r\n
\r\n
{"jsonrpc":"2.0","id":1,"result":{...}}
```

### 三个必需方法

#### initialize

握手。返回固定能力矩阵：不支持加载会话、不支持图片/音频/MCP、无需认证。

#### session/new

创建会话。生成 uuid4 sessionId，存入 `{sessionId → cwd}` 映射。

#### session/prompt

核心：提取 prompt 文本 → 调用 `agent.run()` → 包装为 ACP 响应。

## 错误处理

| 场景 | JSON-RPC 错误码 |
|------|----------------|
| 未知 method | -32601 |
| 无效 sessionId | -32602 |
| 内部异常 | -32603 |
| JSON 解析失败 | -32700 |

## 测试

mock stdin/stdout，验证：

- initialize 返回正确能力矩阵
- session/new 返回有效 sessionId
- session/prompt 正确调用 Agent.run() 并返回格式化响应
- 未知 method 返回 -32601
- 非法 JSON 返回 -32700

## 风险

- ACP 协议 v1 可能在后续版本有 breaking change
- 当前只实现最小子集（3 个方法），未实现 cancel 通知、文件系统能力、MCP 转发等高级特性
