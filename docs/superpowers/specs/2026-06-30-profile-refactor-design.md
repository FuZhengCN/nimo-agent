# Profile 机制重构：从 LLM 自动提取到显式配置

## 问题

1. LLM 从聊天记录自动总结 profile，存在理解偏差、遗漏关键信息
2. TAPD 查询需要姓名、工号、团队成员等信息，频繁重复输入

## 方案

**Profile 数据来源从 LLM 自动提取改为用户显式配置**，通过自然语言触发写入：
用户说"记一下团队成员是张三、李四" → LLM 调 `profile_set` 工具写入。

## 删除

### agent.py

1. 删除 `PROFILE_EXTRACT_PROMPT` 常量
2. 删除 `_maybe_extract_profile()` 方法
3. `run()` 中删除 `await self._maybe_extract_profile(trimmed)` 调用

`get_trimmed()` / `pop_trimmed()` 保留不变，摘要功能仍需它们。

### config.py

`profile_extract` 配置项保留字段但不再生效（避免 breaking change）。

## 新增

### nimo/tools/profile.py — `profile_set` 工具

```python
@register_tool(
    name="profile_set",
    description="记录或更新用户个人信息。用户说'记一下...'或'记住...'时使用。键相同则覆盖旧值，值为空则删除该键。",
    parameters={
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "事实类别"},
            "value": {"type": "string", "description": "具体内容"},
        },
        "required": ["key", "value"],
    },
)
```

工具逻辑：`profile.update({key, value})` + `profile.save()`。

通过 `register_init()` 机制注入 `UserProfile` 实例，复用现有初始化模式。

## 保留不变

- `UserProfile` 数据模型（`update`/`save`/`load`/`to_context`/`clear`）
- `to_context()` 全量注入 system prompt（`[用户信息] 键：值；...`）
- `/clear-profile` 命令
- `~/.nimo/profile.json` 文件路径

## 测试

- `test_profile_set_tool`：验证工具写入 + 保存
- `test_profile_set_overwrite`：验证同名键覆盖
- `test_profile_set_clear`：验证空值删除
- 现有 `test_profile.py` 全部保持通过
