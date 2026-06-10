# Nimo Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CLI AI Agent powered by DeepSeek function calling that can list TAPD projects and fill work hours via natural language conversation.

**Architecture:** Python async CLI app. Agent loop orchestrates LLM calls and tool execution. Tools registered via decorator pattern. Modular design: config, llm client, memory, tool registry, TAPD tools, agent loop, and CLI entry are independent modules.

**Tech Stack:** Python 3.9+, openai SDK (DeepSeek compatible), httpx (async HTTP), pyyaml, pytest + pytest-asyncio

---

### Task 1: Project Scaffold

**Files:**
- Create: `requirements.txt`
- Create: `config.example.yaml`
- Create: `.gitignore`

- [ ] **Step 1: Create requirements.txt**

```text
openai>=1.0.0
httpx>=0.27.0
pyyaml>=6.0
```

- [ ] **Step 2: Create config.example.yaml**

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
  nick: "your-tapd-nickname"
  company_id: "your-company-id"
  owner: "your-username"
```

- [ ] **Step 3: Create .gitignore**

```gitignore
config.yaml
__pycache__/
*.pyc
.venv/
venv/
.env
.pytest_cache/
*.egg-info/
dist/
```

- [ ] **Step 4: Install dependencies and verify**

Run: `pip install -r requirements.txt`
Expected: all three packages install successfully.

Run: `pip install pytest pytest-asyncio`
Expected: test packages install successfully.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt config.example.yaml .gitignore
git commit -m "chore: project scaffold — deps, config template, gitignore"
```

---

### Task 2: Config Module

**Files:**
- Create: `nimo/__init__.py`
- Create: `nimo/config.py`
- Create: `tests/__init__.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Create package init files**

`nimo/__init__.py` — empty
`tests/__init__.py` — empty

- [ ] **Step 2: Write failing test for config loading**

Create `tests/test_config.py`:

```python
import os
import tempfile
import pytest
from nimo.config import Config, LLMConfig, TapdConfig, load_config


def test_load_config_from_yaml():
    yaml_content = """
llm:
  api_key: "sk-test"
  base_url: "https://api.deepseek.com"
  model: "deepseek-chat"
  max_tool_rounds: 5
  history_rounds: 10
tapd:
  api_base: "https://api.tapd.cn"
  access_token: "token123"
  nick: "testuser"
  company_id: "12345"
  owner: "testuser"
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        tmp_path = f.name

    try:
        config = load_config(tmp_path)
        assert config.llm.api_key == "sk-test"
        assert config.llm.model == "deepseek-chat"
        assert config.llm.max_tool_rounds == 5
        assert config.llm.history_rounds == 10
        assert config.tapd.api_base == "https://api.tapd.cn"
        assert config.tapd.access_token == "token123"
        assert config.tapd.nick == "testuser"
    finally:
        os.unlink(tmp_path)


def test_env_var_override():
    yaml_content = """
llm:
  api_key: "sk-from-yaml"
  base_url: "https://api.deepseek.com"
  model: "deepseek-chat"
  max_tool_rounds: 5
  history_rounds: 10
tapd:
  api_base: "https://api.tapd.cn"
  access_token: "token-yaml"
  nick: "yaml-user"
  company_id: "111"
  owner: "yaml-user"
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        tmp_path = f.name

    try:
        os.environ["LLM_API_KEY"] = "sk-from-env"
        os.environ["TAPD_ACCESS_TOKEN"] = "token-env"
        config = load_config(tmp_path)
        assert config.llm.api_key == "sk-from-env"
        assert config.tapd.access_token == "token-env"
    finally:
        os.unlink(tmp_path)
        del os.environ["LLM_API_KEY"]
        del os.environ["TAPD_ACCESS_TOKEN"]
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 4: Implement config module**

Create `nimo/config.py`:

```python
import os
import yaml
from dataclasses import dataclass


@dataclass
class LLMConfig:
    api_key: str
    base_url: str
    model: str
    max_tool_rounds: int
    history_rounds: int


@dataclass
class TapdConfig:
    api_base: str
    access_token: str
    nick: str
    company_id: str
    owner: str


@dataclass
class Config:
    llm: LLMConfig
    tapd: TapdConfig


def _env_override(key: str, default: str) -> str:
    env_key = key.upper().replace(".", "_")
    return os.environ.get(env_key, default)


def load_config(path: str = "config.yaml") -> Config:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    llm = LLMConfig(
        api_key=_env_override("llm.api_key", raw["llm"]["api_key"]),
        base_url=raw["llm"]["base_url"],
        model=raw["llm"]["model"],
        max_tool_rounds=raw["llm"]["max_tool_rounds"],
        history_rounds=raw["llm"]["history_rounds"],
    )
    tapd = TapdConfig(
        api_base=raw["tapd"]["api_base"],
        access_token=_env_override("tapd.access_token", raw["tapd"]["access_token"]),
        nick=raw["tapd"]["nick"],
        company_id=raw["tapd"]["company_id"],
        owner=raw["tapd"]["owner"],
    )
    return Config(llm=llm, tapd=tapd)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: 2 passed

- [ ] **Step 6: Commit**

```bash
git add nimo/__init__.py nimo/config.py tests/__init__.py tests/test_config.py
git commit -m "feat: config module — YAML loading with env var override"
```

---

### Task 3: LLM Client

**Files:**
- Create: `nimo/llm/__init__.py`
- Create: `nimo/llm/client.py`
- Create: `tests/test_llm_client.py`

- [ ] **Step 1: Write failing test for LLM client**

Create `tests/test_llm_client.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from nimo.config import Config, LLMConfig, TapdConfig
from nimo.llm.client import LLMClient, LLMError


@pytest.fixture
def sample_config():
    return Config(
        llm=LLMConfig(
            api_key="sk-test",
            base_url="https://api.deepseek.com",
            model="deepseek-chat",
            max_tool_rounds=5,
            history_rounds=10,
        ),
        tapd=TapdConfig(
            api_base="https://api.tapd.cn",
            access_token="token",
            nick="user",
            company_id="123",
            owner="user",
        ),
    )


@pytest.mark.asyncio
async def test_chat_returns_response(sample_config):
    client = LLMClient(sample_config)

    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_msg = MagicMock()
    mock_msg.content = "你好，有什么可以帮助你的？"
    mock_msg.tool_calls = None
    mock_choice.message = mock_msg
    mock_response.choices = [mock_choice]

    with patch.object(client.client.chat.completions, "create", return_value=mock_response):
        result = await client.chat(
            messages=[{"role": "user", "content": "你好"}],
            tools=[],
        )
        assert result.choices[0].message.content == "你好，有什么可以帮助你的？"


@pytest.mark.asyncio
async def test_chat_retries_on_429(sample_config):
    client = LLMClient(sample_config)

    with patch.object(client.client.chat.completions, "create") as mock_create:
        mock_create.side_effect = [
            Exception("429 rate limit"),
            Exception("429 rate limit"),
            MagicMock(choices=[MagicMock(message=MagicMock(content="ok", tool_calls=None))]),
        ]
        result = await client.chat(
            messages=[{"role": "user", "content": "hi"}],
            tools=[],
        )
        assert mock_create.call_count == 3
        assert result.choices[0].message.content == "ok"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_llm_client.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Implement LLM client**

Create `nimo/llm/__init__.py` — empty

Create `nimo/llm/client.py`:

```python
import asyncio
import logging
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion
from nimo.config import Config

logger = logging.getLogger(__name__)


class LLMError(Exception):
    pass


class LLMClient:
    def __init__(self, config: Config):
        self.client = AsyncOpenAI(
            api_key=config.llm.api_key,
            base_url=config.llm.base_url,
            timeout=60.0,
        )
        self.model = config.llm.model
        self._max_retries = 3

    async def chat(
        self,
        messages: list[dict],
        tools: list[dict],
        system_prompt: str = "",
    ) -> ChatCompletion:
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        for attempt in range(self._max_retries):
            try:
                kwargs = {
                    "model": self.model,
                    "messages": full_messages,
                }
                if tools:
                    kwargs["tools"] = tools
                return await self.client.chat.completions.create(**kwargs)
            except Exception as e:
                if attempt == self._max_retries - 1:
                    raise LLMError(f"LLM 调用失败，已重试 {self._max_retries} 次：{e}")
                wait = 2 ** attempt
                logger.warning(f"LLM 调用失败（第 {attempt + 1} 次），{wait}s 后重试：{e}")
                await asyncio.sleep(wait)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_llm_client.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add nimo/llm/ tests/test_llm_client.py
git commit -m "feat: LLM client — DeepSeek API wrapper with retry"
```

---

### Task 4: Conversation History

**Files:**
- Create: `nimo/memory/__init__.py`
- Create: `nimo/memory/history.py`
- Create: `tests/test_history.py`

- [ ] **Step 1: Write failing test for conversation history**

Create `tests/test_history.py`:

```python
from nimo.memory.history import ConversationHistory


def test_add_and_get_messages():
    history = ConversationHistory()
    history.add({"role": "user", "content": "查项目"})
    history.add({"role": "assistant", "content": "查到3个项目"})

    msgs = history.get_messages()
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"


def test_trim_by_rounds():
    history = ConversationHistory(max_rounds=2)
    # round 1
    history.add({"role": "user", "content": "r1-user"})
    history.add({"role": "assistant", "content": "r1-assistant"})
    # round 2
    history.add({"role": "user", "content": "r2-user"})
    history.add({"role": "assistant", "content": "r2-assistant"})
    # round 3
    history.add({"role": "user", "content": "r3-user"})
    history.add({"role": "assistant", "content": "r3-assistant"})

    msgs = history.get_messages()
    assert len(msgs) == 4
    roles = [m["role"] for m in msgs]
    assert roles == ["user", "assistant", "user", "assistant"]
    assert msgs[0]["content"] == "r2-user"  # round 1 dropped


def test_user_message_triggers_trim():
    history = ConversationHistory(max_rounds=2)
    for i in range(5):
        history.add({"role": "user", "content": f"u{i}"})
        history.add({"role": "assistant", "content": f"a{i}"})
    msgs = history.get_messages()
    assert len(msgs) == 4
    assert msgs[0]["content"] == "u3"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_history.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Implement conversation history**

Create `nimo/memory/__init__.py` — empty

Create `nimo/memory/history.py`:

```python
class ConversationHistory:
    def __init__(self, max_rounds: int = 10):
        self._messages: list[dict] = []
        self._max_rounds = max_rounds
        self._user_indices: list[int] = []

    def add(self, message: dict) -> None:
        if message["role"] == "user":
            self._user_indices.append(len(self._messages))
        self._messages.append(message)
        self._trim()

    def get_messages(self) -> list[dict]:
        return list(self._messages)

    def _trim(self) -> None:
        if len(self._user_indices) <= self._max_rounds:
            return
        drop_count = len(self._user_indices) - self._max_rounds
        cut_index = self._user_indices[drop_count]
        self._messages = self._messages[cut_index:]
        self._user_indices = [i - cut_index for i in self._user_indices[drop_count:]]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_history.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add nimo/memory/ tests/test_history.py
git commit -m "feat: conversation history — sliding window by rounds"
```

---

### Task 5: Tool Registry

**Files:**
- Create: `nimo/tools/__init__.py`
- Create: `nimo/tools/registry.py`
- Create: `tests/test_registry.py`

- [ ] **Step 1: Write failing test for tool registry**

Create `tests/test_registry.py`:

```python
import pytest
from nimo.tools.registry import ToolRegistry, ToolResult, register_tool


@pytest.fixture(autouse=True)
def reset_registry():
    ToolRegistry.get_instance().reset()
    yield


def get_reg():
    return ToolRegistry.get_instance()


def test_register_and_list_tools():
    @register_tool(
        name="test_echo",
        description="Echo back the message",
        parameters={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "要回显的消息"},
            },
            "required": ["message"],
        },
    )
    async def test_echo(message: str) -> ToolResult:
        return ToolResult(success=True, data={"echo": message})

    definitions = get_reg().build_tool_definitions()
    assert len(definitions) == 1
    tool_def = definitions[0]
    assert tool_def["type"] == "function"
    assert tool_def["function"]["name"] == "test_echo"


@pytest.mark.asyncio
async def test_execute_registered_tool():
    @register_tool(
        name="calc",
        description="计算两个数之和",
        parameters={
            "type": "object",
            "properties": {
                "a": {"type": "number"},
                "b": {"type": "number"},
            },
            "required": ["a", "b"],
        },
    )
    async def calc(a: float, b: float) -> ToolResult:
        return ToolResult(success=True, data={"result": a + b})

    result = await get_reg().execute("calc", {"a": 1, "b": 2})
    assert result.success is True
    assert result.data["result"] == 3


@pytest.mark.asyncio
async def test_execute_unknown_tool():
    result = await get_reg().execute("nonexistent", {})
    assert result.success is False
    assert "未找到工具" in result.error


def test_build_definitions_empty():
    # autouse fixture already reset, so registry is empty
    assert get_reg().build_tool_definitions() == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_registry.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Implement tool registry**

Create `nimo/tools/__init__.py`:

```python
from nimo.tools.registry import ToolRegistry, ToolResult, register_tool
```

Create `nimo/tools/registry.py`:

```python
import asyncio
import logging
from dataclasses import dataclass, field
from collections.abc import Callable, Awaitable
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    success: bool
    data: Any = None
    error: str | None = None


@dataclass
class _ToolDef:
    name: str
    description: str
    parameters: dict
    func: Callable[..., Awaitable[ToolResult]]


class ToolRegistry:
    _instance: "ToolRegistry | None" = None

    def __init__(self):
        self._tools: dict[str, _ToolDef] = {}

    @classmethod
    def get_instance(cls) -> "ToolRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        cls._instance = None

    def register(
        self,
        name: str,
        description: str,
        parameters: dict,
        func: Callable[..., Awaitable[ToolResult]],
    ) -> None:
        self._tools[name] = _ToolDef(
            name=name,
            description=description,
            parameters=parameters,
            func=func,
        )

    def build_tool_definitions(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    async def execute(self, name: str, arguments: dict) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            return ToolResult(success=False, error=f"未找到工具：{name}")
        try:
            return await tool.func(**arguments)
        except Exception as e:
            logger.exception(f"工具 {name} 执行异常")
            return ToolResult(success=False, error=str(e))


def register_tool(name: str, description: str, parameters: dict):
    def decorator(func: Callable[..., Awaitable[ToolResult]]):
        ToolRegistry.get_instance().register(name, description, parameters, func)
        return func
    return decorator
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_registry.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add nimo/tools/ tests/test_registry.py
git commit -m "feat: tool registry — decorator-based registration and dispatch"
```

---

### Task 6: System Prompt

**Files:**
- Create: `nimo/prompts/system.md`

- [ ] **Step 1: Create system prompt template**

Create `nimo/prompts/system.md`:

```markdown
你是 Nimo，一个智能助手，帮助用户通过自然语言完成日常工作任务。

## 能力
你当前可以使用工具来执行 TAPD（腾讯敏捷协作平台）相关操作，包括查看项目和填写工时。

## 行为准则
- 如果用户请求的内容超出你当前工具的能力范围，如实告知用户
- 执行工具前，如果缺少必要参数且无法从上下文推断，主动向用户询问
- 工具执行成功后，用简洁的中文总结结果，不要原样输出 JSON
- 工具执行失败时，用通俗的语言解释错误原因，并建议下一步
- 不要编造数据，所有信息必须来自工具返回的实际结果
```

- [ ] **Step 2: Commit**

```bash
git add nimo/prompts/system.md
git commit -m "feat: system prompt — agent persona and behavior rules"
```

---

### Task 7: TAPD Tools

**Files:**
- Create: `nimo/tools/tapd.py`
- Create: `tests/test_tapd_tools.py`

- [ ] **Step 1: Write failing test for TAPD tools**

Create `tests/test_tapd_tools.py`:

```python
import pytest
from unittest.mock import patch, AsyncMock
from nimo.config import Config, LLMConfig, TapdConfig

# Module-level import triggers @register_tool once. Tools stay registered for all tests.
import nimo.tools.tapd


@pytest.fixture
def sample_config():
    return Config(
        llm=LLMConfig(
            api_key="sk-test", base_url="https://api.deepseek.com",
            model="deepseek-chat", max_tool_rounds=5, history_rounds=10,
        ),
        tapd=TapdConfig(
            api_base="https://api.tapd.cn", access_token="token123",
            nick="testuser", company_id="12345", owner="testuser",
        ),
    )


@pytest.mark.asyncio
async def test_list_projects_success(sample_config):
    api_response = {
        "status": 1,
        "data": [
            {"Workspace": {"id": "755", "name": "TAPD平台", "status": "normal"}},
            {"Workspace": {"id": "10158231", "name": "游戏项目A", "status": "normal"}},
        ],
        "info": "success",
    }

    with patch.object(nimo.tools.tapd, "_config", sample_config):
        with patch.object(nimo.tools.tapd, "_api_get", new=AsyncMock(return_value=api_response)):
            result = await nimo.tools.tapd.tapd_list_projects()
            assert result.success is True
            assert len(result.data) == 2
            assert result.data[0]["Workspace"]["name"] == "TAPD平台"


@pytest.mark.asyncio
async def test_add_workhour_success(sample_config):
    api_response = {"status": 1, "data": {"Timesheet": {"id": "1001"}}, "info": "success"}

    with patch.object(nimo.tools.tapd, "_config", sample_config):
        with patch.object(nimo.tools.tapd, "_api_post", new=AsyncMock(return_value=api_response)):
            result = await nimo.tools.tapd.tapd_add_workhour(
                workspace_id=10158231,
                entity_type="story",
                entity_id=1001,
                timespent="2",
                spentdate="2026-06-10",
                memo="需求评审",
            )
            assert result.success is True
            assert result.data["Timesheet"]["id"] == "1001"


@pytest.mark.asyncio
async def test_add_workhour_api_error(sample_config):
    api_response = {"status": 0, "info": "参数错误", "data": ""}

    with patch.object(nimo.tools.tapd, "_config", sample_config):
        with patch.object(nimo.tools.tapd, "_api_post", new=AsyncMock(return_value=api_response)):
            result = await nimo.tools.tapd.tapd_add_workhour(
                workspace_id=10158231,
                entity_type="story",
                entity_id=1001,
                timespent="2",
            )
            assert result.success is False
            assert "参数错误" in result.error
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tapd_tools.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Implement TAPD tools**

Create `nimo/tools/tapd.py`:

```python
import logging
import httpx
from nimo.config import Config
from nimo.tools.registry import register_tool, ToolResult

logger = logging.getLogger(__name__)

_config: Config | None = None
_client: httpx.AsyncClient | None = None


def init_tapd(config: Config) -> None:
    global _config, _client
    _config = config
    _client = httpx.AsyncClient(
        base_url=config.tapd.api_base,
        headers={"Authorization": f"Bearer {config.tapd.access_token}"},
        timeout=30.0,
    )


async def _api_get(path: str, params: dict | None = None) -> dict:
    resp = await _client.get(path, params=params)
    resp.raise_for_status()
    return resp.json()


async def _api_post(path: str, body: dict | None = None) -> dict:
    resp = await _client.post(path, data=body)
    resp.raise_for_status()
    return resp.json()


@register_tool(
    name="tapd_list_projects",
    description="获取当前用户在 TAPD 中有权限参与的项目列表。返回项目名称、ID 和状态。",
    parameters={
        "type": "object",
        "properties": {},
    },
)
async def tapd_list_projects() -> ToolResult:
    try:
        data = await _api_get("/workspaces/user_participant_projects", params={
            "nick": _config.tapd.nick,
            "company_id": _config.tapd.company_id,
        })
        if data.get("status") != 1:
            return ToolResult(success=False, error=f"TAPD 返回错误：{data.get('info', '未知错误')}")
        return ToolResult(success=True, data=data["data"])
    except Exception as e:
        logger.exception("查项目列表失败")
        return ToolResult(success=False, error=str(e))


@register_tool(
    name="tapd_add_workhour",
    description="为 TAPD 中的需求（story）、任务（task）或缺陷（bug）填写工时记录。同一对象同一人同一天不可重复填写。",
    parameters={
        "type": "object",
        "properties": {
            "workspace_id": {"type": "integer", "description": "项目 ID"},
            "entity_type": {
                "type": "string",
                "enum": ["story", "task", "bug"],
                "description": "对象类型",
            },
            "entity_id": {"type": "integer", "description": "需求/任务/缺陷的 ID"},
            "timespent": {"type": "string", "description": "工时（小时），如 '2.5'"},
            "spentdate": {"type": "string", "description": "日期，格式 YYYY-MM-DD"},
            "memo": {"type": "string", "description": "工时内容说明"},
        },
        "required": ["workspace_id", "entity_type", "entity_id", "timespent"],
    },
)
async def tapd_add_workhour(
    workspace_id: int,
    entity_type: str,
    entity_id: int,
    timespent: str,
    spentdate: str = "",
    memo: str = "",
) -> ToolResult:
    try:
        body = {
            "workspace_id": workspace_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "timespent": timespent,
            "owner": _config.tapd.owner,
        }
        if spentdate:
            body["spentdate"] = spentdate
        if memo:
            body["memo"] = memo

        data = await _api_post("/timesheets", body=body)
        if data.get("status") != 1:
            return ToolResult(success=False, error=f"TAPD 返回错误：{data.get('info', '未知错误')}")
        return ToolResult(success=True, data=data["data"])
    except Exception as e:
        logger.exception("填工时失败")
        return ToolResult(success=False, error=str(e))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_tapd_tools.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add nimo/tools/tapd.py tests/test_tapd_tools.py
git commit -m "feat: TAPD tools — list projects and add work hours"
```

---

### Task 8: Agent Core Loop

**Files:**
- Create: `nimo/agent.py`
- Create: `tests/test_agent.py`

- [ ] **Step 1: Write failing test for agent loop**

Create `tests/test_agent.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from nimo.config import Config, LLMConfig, TapdConfig


@pytest.fixture
def sample_config():
    return Config(
        llm=LLMConfig(
            api_key="sk-test", base_url="https://api.deepseek.com",
            model="deepseek-chat", max_tool_rounds=5, history_rounds=10,
        ),
        tapd=TapdConfig(
            api_base="https://api.tapd.cn", access_token="token",
            nick="user", company_id="123", owner="user",
        ),
    )


def make_mock_chat_response(content: str, tool_calls=None):
    mock_msg = MagicMock()
    mock_msg.content = content
    mock_msg.tool_calls = tool_calls
    mock_choice = MagicMock()
    mock_choice.message = mock_msg
    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]
    return mock_resp


@pytest.mark.asyncio
async def test_agent_simple_reply_no_tools(sample_config):
    from nimo.agent import Agent

    agent = Agent(sample_config)
    agent._llm_client = MagicMock()
    agent._llm_client.chat = MagicMock(return_value=make_mock_chat_response("你好！有什么可以帮你的？"))

    response = await agent.run("你好")
    assert "你好" in response


@pytest.mark.asyncio
async def test_agent_calls_tool_then_responds(sample_config):
    from nimo.agent import Agent

    agent = Agent(sample_config)

    # First call: LLM returns tool_call
    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_001"
    mock_tool_call.function.name = "tapd_list_projects"
    mock_tool_call.function.arguments = "{}"

    # Second call: LLM returns text summary
    call_count = [0]
    async def mock_chat(messages=None, tools=None, system_prompt=""):
        call_count[0] += 1
        if call_count[0] == 1:
            return make_mock_chat_response(None, tool_calls=[mock_tool_call])
        else:
            return make_mock_chat_response("你参与了3个项目：A、B、C")

    agent._llm_client = MagicMock()
    agent._llm_client.chat = mock_chat

    # Mock tool execution
    agent._registry.execute = MagicMock(return_value=MagicMock(success=True, data=[]))

    response = await agent.run("查项目")
    assert "3个项目" in response
    assert call_count[0] == 2


@pytest.mark.asyncio
async def test_agent_stops_at_max_rounds(sample_config):
    from nimo.agent import Agent

    agent = Agent(sample_config)

    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_001"
    mock_tool_call.function.name = "tapd_list_projects"
    mock_tool_call.function.arguments = "{}"

    agent._llm_client = MagicMock()
    agent._llm_client.chat = MagicMock(
        return_value=make_mock_chat_response(None, tool_calls=[mock_tool_call])
    )
    agent._registry.execute = MagicMock(return_value=MagicMock(success=True, data=[]))

    response = await agent.run("反复查")
    assert agent._llm_client.chat.call_count == sample_config.llm.max_tool_rounds
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_agent.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Implement agent core loop**

Create `nimo/agent.py`:

```python
import json
import logging
from nimo.config import Config
from nimo.llm.client import LLMClient
from nimo.memory.history import ConversationHistory
from nimo.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


class Agent:
    def __init__(self, config: Config):
        self._config = config
        self._llm_client = LLMClient(config)
        self._history = ConversationHistory(max_rounds=config.llm.history_rounds)
        self._registry = ToolRegistry.get_instance()
        self._system_prompt = self._load_system_prompt()

    def _load_system_prompt(self) -> str:
        try:
            with open("nimo/prompts/system.md", "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            logger.warning("system.md 未找到，使用默认提示")
            return "你是 Nimo，一个帮助用户完成日常工作的助手。"

    async def run(self, user_input: str) -> str:
        self._history.add({"role": "user", "content": user_input})

        tools = self._registry.build_tool_definitions()

        for round_num in range(self._config.llm.max_tool_rounds):
            messages = self._history.get_messages()
            response = await self._llm_client.chat(
                messages=messages,
                tools=tools,
                system_prompt=self._system_prompt,
            )

            choice = response.choices[0]
            message = choice.message

            if not message.tool_calls:
                self._history.add({"role": "assistant", "content": message.content or ""})
                return message.content or ""

            # Execute tools in parallel
            self._history.add({
                "role": "assistant",
                "content": message.content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in message.tool_calls
                ],
            })

            for tc in message.tool_calls:
                args = json.loads(tc.function.arguments)
                result = await self._registry.execute(tc.function.name, args)
                self._history.add({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps({
                        "success": result.success,
                        "data": result.data,
                        "error": result.error,
                    }, ensure_ascii=False, default=str),
                })

        return "已达到最大工具调用轮数，操作未完成。"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_agent.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add nimo/agent.py tests/test_agent.py
git commit -m "feat: agent core loop — LLM + tool orchestration"
```

---

### Task 9: CLI Entry

**Files:**
- Create: `nimo/main.py`
- Create: `tests/test_main.py`

- [ ] **Step 1: Write failing test for main**

Create `tests/test_main.py`:

```python
import pytest
from unittest.mock import patch, MagicMock
from nimo.main import build_agent


def test_build_agent_loads_config():
    with patch("nimo.main.load_config") as mock_load:
        mock_load.return_value = MagicMock()
        with patch("nimo.main.Agent") as mock_agent:
            with patch("nimo.tools.tapd.init_tapd"):
                build_agent("config.yaml")
                mock_load.assert_called_once_with("config.yaml")
                mock_agent.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_main.py -v`
Expected: FAIL — ModuleNotFoundError

- [ ] **Step 3: Implement CLI entry**

Create `nimo/main.py`:

```python
import asyncio
import logging
from nimo.config import load_config
from nimo.agent import Agent

# Import to trigger tool registration
import nimo.tools.tapd  # noqa: F401
from nimo.tools.tapd import init_tapd

logger = logging.getLogger(__name__)


def build_agent(config_path: str = "config.yaml") -> Agent:
    config = load_config(config_path)
    init_tapd(config)
    return Agent(config)


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    agent = build_agent()
    print("Nimo 就绪，输入 /exit 退出")
    while True:
        try:
            user_input = input("> ")
        except (EOFError, KeyboardInterrupt):
            print("\n再见！")
            break
        if user_input.strip() == "/exit":
            print("再见！")
            break
        if not user_input.strip():
            continue
        response = await agent.run(user_input)
        print(response)
        print()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_main.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add nimo/main.py tests/test_main.py
git commit -m "feat: CLI entry — async read-eval-print loop"
```

---

### Task 10: Integration Check

**Files:**
- Create: `tests/test_integration.py`

- [ ] **Step 1: Write integration smoke test**

Create `tests/test_integration.py`:

```python
import pytest
from unittest.mock import MagicMock, patch


@pytest.mark.asyncio
async def test_full_flow_list_projects():
    """模拟用户查项目列表的完整对话流程。"""
    from nimo.agent import Agent
    from nimo.config import Config, LLMConfig, TapdConfig

    config = Config(
        llm=LLMConfig(
            api_key="sk-test", base_url="https://api.deepseek.com",
            model="deepseek-chat", max_tool_rounds=5, history_rounds=10,
        ),
        tapd=TapdConfig(
            api_base="https://api.tapd.cn", access_token="token",
            nick="user", company_id="123", owner="user",
        ),
    )

    agent = Agent(config)

    mock_projects = [{"Workspace": {"id": "755", "name": "示例项目", "status": "normal"}}]

    # Mock LLM: tool call first, then final text
    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_int_1"
    mock_tool_call.function.name = "tapd_list_projects"
    mock_tool_call.function.arguments = "{}"

    call_count = [0]

    async def mock_chat(messages=None, tools=None, system_prompt=""):
        call_count[0] += 1
        if call_count[0] == 1:
            mock_msg = MagicMock()
            mock_msg.content = None
            mock_msg.tool_calls = [mock_tool_call]
            mock_choice = MagicMock()
            mock_choice.message = mock_msg
            mock_resp = MagicMock()
            mock_resp.choices = [mock_choice]
            return mock_resp
        else:
            mock_msg2 = MagicMock()
            mock_msg2.content = "你参与了1个项目：示例项目 (ID: 755)"
            mock_msg2.tool_calls = None
            mock_choice2 = MagicMock()
            mock_choice2.message = mock_msg2
            mock_resp2 = MagicMock()
            mock_resp2.choices = [mock_choice2]
            return mock_resp2

    agent._llm_client.chat = mock_chat
    from nimo.tools.registry import ToolResult
    agent._registry.execute = MagicMock(return_value=ToolResult(success=True, data=mock_projects))

    response = await agent.run("查项目")
    assert "示例项目" in response
    assert "755" in response
    assert call_count[0] == 2


@pytest.mark.asyncio
async def test_full_flow_add_workhour():
    """模拟用户填工时的完整对话流程。"""
    from nimo.agent import Agent
    from nimo.config import Config, LLMConfig, TapdConfig

    config = Config(
        llm=LLMConfig(
            api_key="sk-test", base_url="https://api.deepseek.com",
            model="deepseek-chat", max_tool_rounds=5, history_rounds=10,
        ),
        tapd=TapdConfig(
            api_base="https://api.tapd.cn", access_token="token",
            nick="user", company_id="123", owner="user",
        ),
    )

    agent = Agent(config)

    mock_tool_call = MagicMock()
    mock_tool_call.id = "call_int_2"
    mock_tool_call.function.name = "tapd_add_workhour"
    mock_tool_call.function.arguments = '{"workspace_id": 755, "entity_type": "story", "entity_id": 1001, "timespent": "2", "spentdate": "2026-06-10", "memo": "需求评审"}'

    call_count = [0]

    async def mock_chat(messages=None, tools=None, system_prompt=""):
        call_count[0] += 1
        if call_count[0] == 1:
            mock_msg = MagicMock()
            mock_msg.content = None
            mock_msg.tool_calls = [mock_tool_call]
            mock_choice = MagicMock()
            mock_choice.message = mock_msg
            mock_resp = MagicMock()
            mock_resp.choices = [mock_choice]
            return mock_resp
        else:
            mock_msg2 = MagicMock()
            mock_msg2.content = "已填写：2026-06-10，需求 #1001，2小时 — 需求评审"
            mock_msg2.tool_calls = None
            mock_choice2 = MagicMock()
            mock_choice2.message = mock_msg2
            mock_resp2 = MagicMock()
            mock_resp2.choices = [mock_choice2]
            return mock_resp2

    agent._llm_client.chat = mock_chat
    from nimo.tools.registry import ToolResult
    agent._registry.execute = MagicMock(
        return_value=ToolResult(success=True, data={"Timesheet": {"id": "2001"}})
    )

    response = await agent.run("在755项目里填2小时工时")
    assert "2小时" in response
    assert call_count[0] == 2
```

- [ ] **Step 2: Run integration tests**

Run: `pytest tests/test_integration.py -v`
Expected: 2 passed

- [ ] **Step 3: Run all tests**

Run: `pytest tests/ -v`
Expected: All tests pass (config: 2, llm: 2, history: 3, registry: 4, tapd: 3, agent: 3, main: 1, integration: 2 = 20 tests)

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: integration tests — full conversation flows"
```
