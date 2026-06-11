# Nimo

CLI AI Agent，基于 DeepSeek function calling，通过自然语言对话完成 TAPD 操作。

## 功能

- 自然语言查项目、需求、任务、缺陷
- 填工时、查迭代、评论、Wiki
- 智能搜索：输入任务名称自动匹配 ID，无需手动查找
- 美观的终端欢迎画面和回复卡片

## 环境要求

- Python 3.10+
- [tapd.exe](https://github.com/studyzy/tapd-ai-cli) 放在 `bin/` 目录
- DeepSeek API Key
- TAPD 个人访问令牌

## 安装

```bash
git clone <repo-url> && cd Nimo
pip install -e ".[dev]"
```

将 `tapd.exe` 下载到 `bin/` 目录。

## 配置

复制 `config.example.yaml` 为 `config.yaml`，填写必填字段：

```yaml
llm:
  api_key: "sk-your-deepseek-key"
  base_url: "https://api.deepseek.com"
  model: "deepseek-chat"
  max_tool_rounds: 5
  history_rounds: 10

tapd:
  api_base: "https://api.tapd.cn"
  access_token: "your-tapd-personal-token"
```

`api_key` 和 `access_token` 也可以通过环境变量覆盖：

```bash
export LLM_API_KEY="sk-xxx"
export TAPD_ACCESS_TOKEN="xxx"
```

## 使用

```bash
python -m nimo.main
```

对话示例：

```
> 帮我看看有哪些项目
> 列出项目755的任务
> 创建一个需求：修复登录bug
> 给任务1001填4小时工时
> /exit 退出
```

## 开发

```bash
# 运行测试
pytest tests/ -v

# 覆盖率报告
pytest tests/ --cov=nimo --cov-report=term-missing
```

## 架构

```
main.py → agent.py → llm/client.py      (DeepSeek API)
                   → memory/history.py   (对话历史滑动窗口)
                   → tools/registry.py   (工具注册与分发)
        → config.py
        → display.py
        → tools/tapd.py                  (tapd CLI 工具)
```

新增工具只需 `@register_tool` 装饰器，不改中央配置。

## License

MIT
