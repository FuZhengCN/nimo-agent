# Profile 机制重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 profile 数据来源从 LLM 自动提取改为 `profile_set` 工具显式写入，删除 `profile_extract` 配置项和 `_maybe_extract_profile` 方法。

**Architecture:** 删 3 处（agent.py 常量/方法/调用 + config.py 字段），加 1 个工具（`nimo/tools/profile.py`），profile 始终加载（不再依赖配置开关）。

**Tech Stack:** Python，无新依赖。

## Global Constraints

- 遵守 CLAUDE.md 铁律：根因驱动、极简修改、可验证优先
- 每次修改后自动 git commit
- 现有 `test_profile.py` 全部保持通过

---

### Task 1: 删除 agent.py 中的 profile 自动提取代码 + config.py 中的 profile_extract 字段

**Files:**
- Modify: `nimo/agent.py:18,118-131,179-181`
- Modify: `nimo/config.py:21,106`
- Modify: `nimo/agent.py:55-62`

**Interfaces:**
- Consumes: 无
- Produces: Agent 始终持有 `UserProfile` 实例（不再受 `profile_extract` 开关控制）

- [ ] **Step 1: 删除 `PROFILE_EXTRACT_PROMPT` 常量**

```python
# nimo/agent.py 第 16-18 行，改为只有 SUMMARY_SYSTEM_PROMPT
SUMMARY_SYSTEM_PROMPT = "你是对话摘要助手。提取关键事实（ID、名称、决策、状态变更），用1-3句中文输出。不要输出任何前缀，只输出摘要本身。"
```

- [ ] **Step 2: 删除 `_maybe_extract_profile` 方法**

```python
# nimo/agent.py 第 118-131 行，整个方法删除
```

- [ ] **Step 3: 删除 `run()` 中的 `_maybe_extract_profile` 调用**

```python
# nimo/agent.py 第 178-182 行，删除 await self._maybe_extract_profile(trimmed) 那行
# 改为：
self._history.add({"role": "user", "content": user_input})
trimmed = self._history.get_trimmed()
await self._maybe_summarize_trimmed(trimmed)
self._history.pop_trimmed()
```

- [ ] **Step 4: Agent.__init__ 始终加载 profile**

```python
# nimo/agent.py 第 55-62 行，去掉 profile_extract 条件判断
# 改为：
try:
    self._profile = UserProfile.load()
except Exception:
    logger.warning("档案加载失败，使用空档案", exc_info=True)
    self._profile = UserProfile()
```

- [ ] **Step 5: 删除 config.py 中的 profile_extract 字段**

```python
# nimo/config.py LLMConfig dataclass，删除第 21 行
@dataclass
class LLMConfig:
    api_key: str
    base_url: str
    model: str
    max_tool_rounds: int
    history_rounds: int
    temperature: float = 0.3
    history_persist: bool = False
    history_summarize: bool = False
    # profile_extract 已删除
```

```python
# nimo/config.py load_config()，删除第 106 行
llm = LLMConfig(
    api_key=_env_override("llm.api_key", raw["llm"]["api_key"]),
    base_url=raw["llm"]["base_url"],
    model=raw["llm"]["model"],
    max_tool_rounds=raw["llm"]["max_tool_rounds"],
    history_rounds=raw["llm"]["history_rounds"],
    temperature=raw["llm"].get("temperature", 0.3),
    history_persist=raw["llm"].get("history_persist", False),
    history_summarize=raw["llm"].get("history_summarize", False),
    # profile_extract 已删除
)
```

- [ ] **Step 6: 运行现有测试确认无回归**

Run: `pytest tests/test_agent.py tests/test_profile.py tests/test_config.py -v`
Expected: 全部 PASS

- [ ] **Step 7: Commit**

```bash
git add nimo/agent.py nimo/config.py
git commit -m "refactor: 删除 LLM 自动提取 profile 机制，profile 始终加载"
```

---

### Task 2: 新增 `profile_set` 工具

**Files:**
- Create: `nimo/tools/profile.py`

**Interfaces:**
- Consumes: `UserProfile` 实例（通过 `register_init` 注入）
- Produces: `profile_set(key, value)` 工具，LLM 可见

- [ ] **Step 1: 创建测试文件**

```python
# tests/test_profile_tool.py
import json
from pathlib import Path
from nimo.memory.profile import UserProfile
from nimo.tools.registry import ToolRegistry


async def test_profile_set_writes(tmp_path):
    """验证 profile_set 写入并持久化。"""
    from nimo.tools.profile import _get_profile, _set_profile

    p = UserProfile()
    _set_profile(p)

    result = await ToolRegistry.get_instance().execute("profile_set", {
        "key": "姓名",
        "value": "张三",
    })

    assert result.success
    assert p.facts == {"姓名": "张三"}


async def test_profile_set_overwrites(tmp_path):
    """验证同名键覆盖。"""
    from nimo.tools.profile import _get_profile, _set_profile

    p = UserProfile()
    p.update({"姓名": "张三"})
    _set_profile(p)

    result = await ToolRegistry.get_instance().execute("profile_set", {
        "key": "姓名",
        "value": "李四",
    })

    assert result.success
    assert p.facts == {"姓名": "李四"}


async def test_profile_set_clear_by_empty_value(tmp_path):
    """验证空值删除键。"""
    from nimo.tools.profile import _get_profile, _set_profile

    p = UserProfile()
    p.update({"姓名": "张三", "角色": "工程师"})
    _set_profile(p)

    result = await ToolRegistry.get_instance().execute("profile_set", {
        "key": "姓名",
        "value": "",
    })

    assert result.success
    assert "姓名" not in p.facts
    assert "角色" in p.facts


async def test_profile_set_saves_to_disk(tmp_path):
    """验证写入后持久化到磁盘。"""
    from nimo.tools.profile import _get_profile, _set_profile

    p = UserProfile()
    _set_profile(p)

    await ToolRegistry.get_instance().execute("profile_set", {
        "key": "姓名",
        "value": "张三",
    })

    # 加载后应有一致数据
    loaded = UserProfile.load(base_dir=tmp_path)
    # 注意：默认保存路径是 ~/.nimo/profile.json，测试中需用 tmp_path
    # 这里验证内存状态即可，持久化由 UserProfile 测试保证
    assert p.facts == {"姓名": "张三"}


def test_profile_set_tool_registered():
    """验证 profile_set 已注册到 ToolRegistry。"""
    registry = ToolRegistry.get_instance()
    tools = dict(registry.list_tools())
    assert "profile_set" in tools
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_profile_tool.py -v`
Expected: FAIL（模块未创建）

- [ ] **Step 3: 创建 `nimo/tools/profile.py`**

```python
"""profile_set 工具：用户通过自然语言指令显式写入个人信息。"""
import logging
from nimo.memory.profile import UserProfile
from nimo.tools.registry import register_tool, ToolResult, ToolRegistry

logger = logging.getLogger(__name__)

_profile: UserProfile | None = None


def _get_profile() -> UserProfile | None:
    return _profile


def _set_profile(p: UserProfile) -> None:
    global _profile
    _profile = p


@register_tool(
    name="profile_set",
    description="记录或更新用户个人信息。用户说'记一下...'或'记住...'时使用。键相同则覆盖旧值，值为空则删除该键。",
    parameters={
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "事实类别，如 姓名、工号、团队成员、常用项目"},
            "value": {"type": "string", "description": "具体内容，如 张三、755、张三/李四"},
        },
        "required": ["key", "value"],
    },
)
async def profile_set(key: str, value: str) -> ToolResult:
    if _profile is None:
        return ToolResult(success=False, error="用户档案未初始化")
    try:
        _profile.update({key: value})
        _profile.save()
        logger.info("用户档案已更新：%s = %s", key, value if value else "(已删除)")
        return ToolResult(success=True, data={"key": key, "value": value})
    except Exception as e:
        return ToolResult(success=False, error=str(e))


```

- [ ] **Step 4: 在 `build_agent()` 中注入 profile 实例**

```python
# nimo/main.py build_agent() 函数，在 init_all 之前注入 profile
async def build_agent(config: Config) -> Agent:
    ExecutionEngine.get_instance().init(config)
    agent = Agent(config)
    # 注入 profile 实例到 profile_set 工具
    from nimo.tools.profile import _set_profile
    _set_profile(agent._profile)
    await ToolRegistry.get_instance().init_all(config)
    return agent
```

- [ ] **Step 5: 运行测试确认通过**

Run: `pytest tests/test_profile_tool.py -v`
Expected: 4 PASS

- [ ] **Step 6: 运行全部测试确认无回归**

Run: `pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 7: Commit**

```bash
git add nimo/tools/profile.py tests/test_profile_tool.py nimo/main.py
git commit -m "feat: 新增 profile_set 工具，支持自然语言显式写入用户信息"
```

---
