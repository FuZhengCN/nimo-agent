# SVN 远端 URL 支持实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `tortoisesvn.paths` 配置值自动识别为本地路径或远端 URL，只读命令直接对 URL 执行，写命令返回明确错误。

**Architecture:** 在 `tortoisesvn.py` 和 `engine.py` 各新增 `_is_url()` 和 `_READONLY_COMMANDS`，修改 `_build_args`/`_run_svn` 的参数拼接逻辑和 `svn()`/`_execute_svn()` 的校验逻辑。配置结构不变。

**Tech Stack:** Python 3.10+、asyncio、pytest + unittest.mock

## Global Constraints

- `paths` 值以 `http://`、`https://`、`svn://`、`svn+ssh://` 开头的视为远端 URL
- 只读命令：`log`、`diff`、`blame`、`info`、`properties`
- `_URL_BEFORE_PATH` 命令（checkout/switch/merge/import/export）行为完全不变
- 现有本地路径行为完全不变（回归）

---

### Task 1: tortoisesvn.py — URL 支持

**Files:**
- Modify: `nimo/tools/tortoisesvn.py`
- Modify: `tests/test_tortoisesvn.py`

**Interfaces:**
- Produces: `_is_url(path: str) -> bool` — 模块级函数
- Produces: `_READONLY_COMMANDS: frozenset[str]` — 模块级常量
- Produces: 修改后的 `_validate_args(command, path)` — URL 路径跳过 `..` 校验
- Produces: 修改后的 `_build_args(command, path, url, extra_args)` — URL+只读命令追加 URL 到参数
- Produces: 修改后的 `svn()` — URL+写命令提前返回错误

- [ ] **Step 1: 添加 `test_is_url` 测试**

```python
def test_is_url():
    assert nimo.tools.tortoisesvn._is_url("https://svn.example.com/repo") is True
    assert nimo.tools.tortoisesvn._is_url("http://svn.example.com/repo") is True
    assert nimo.tools.tortoisesvn._is_url("svn://svn.example.com/repo") is True
    assert nimo.tools.tortoisesvn._is_url("svn+ssh://svn.example.com/repo") is True


def test_is_url_local_path():
    assert nimo.tools.tortoisesvn._is_url(r"C:\Users\test\repo") is False
    assert nimo.tools.tortoisesvn._is_url("/home/user/repo") is False
    assert nimo.tools.tortoisesvn._is_url("") is False
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_tortoisesvn.py::test_is_url tests/test_tortoisesvn.py::test_is_url_local_path -v`
Expected: FAIL with `AttributeError: module 'nimo.tools.tortoisesvn' has no attribute '_is_url'`

- [ ] **Step 3: 添加 `_is_url()` 和 `_READONLY_COMMANDS` 到 tortoisesvn.py**

在 `_URL_BEFORE_PATH` 常量旁添加：

```python
_READONLY_COMMANDS = frozenset({
    "log", "diff", "blame", "info", "properties",
})


def _is_url(s: str) -> bool:
    return s.startswith(("http://", "https://", "svn://", "svn+ssh://"))
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_tortoisesvn.py::test_is_url tests/test_tortoisesvn.py::test_is_url_local_path -v`
Expected: PASS

- [ ] **Step 5: 添加 `test_validate_skip_url` 测试**

```python
def test_validate_skip_url():
    """URL 路径不应触发路径遍历检查。"""
    result = nimo.tools.tortoisesvn._validate_args("log", "https://svn.example.com/repo/..")
    assert result is None
```

- [ ] **Step 6: 运行测试验证失败**

Run: `pytest tests/test_tortoisesvn.py::test_validate_skip_url -v`
Expected: FAIL (当前实现会报路径遍历)

- [ ] **Step 7: 修改 `_validate_args` 跳过 URL**

```python
def _validate_args(command: str, path: str) -> str | None:
    if command not in _ALLOWED_COMMANDS:
        return f"不允许的 SVN 命令：{command}"
    if path and not _is_url(path):
        if ".." in path.replace("/", "\\"):
            return f"路径包含路径遍历：{path}"
    return None
```

- [ ] **Step 8: 运行测试验证通过**

Run: `pytest tests/test_tortoisesvn.py::test_validate_skip_url tests/test_tortoisesvn.py::test_validate_path_traversal tests/test_tortoisesvn.py::test_validate_valid_commands -v`
Expected: 全部 PASS

- [ ] **Step 9: 添加 `test_build_args_with_url_readonly` 测试**

```python
@pytest.mark.parametrize("command", ["log", "diff", "blame", "info", "properties"])
def test_build_args_with_url_readonly(command):
    """只读命令 + URL -> URL 会被追加到参数列表。"""
    url = "https://svn.example.com/repo/trunk"
    args = nimo.tools.tortoisesvn._build_args(command, url, "", None)
    assert url in args
```

- [ ] **Step 10: 运行测试验证失败**

Run: `pytest tests/test_tortoisesvn.py::test_build_args_with_url_readonly -v`
Expected: FAIL（当前 `_build_args` 不会追加 URL 路径）

- [ ] **Step 11: 修改 `_build_args` 支持 URL 路径**

```python
def _build_args(command: str, path: str, url: str, extra_args: list[str] | None) -> list[str]:
    if command == "repocreate":
        args = [_SVNADMIN_EXE, "create"]
    else:
        args = [_SVN_EXE, command]
    if extra_args:
        args.extend(extra_args)
    if command in _URL_BEFORE_PATH:
        if url:
            args.append(url)
        if path:
            args.append(path)
    elif _is_url(path):
        args.append(path)
    elif path:
        args.append(path)
    return args
```

- [ ] **Step 12: 运行测试验证通过**

Run: `pytest tests/test_tortoisesvn.py::test_build_args_with_url_readonly -v`
Expected: PASS

- [ ] **Step 13: 添加 `test_svn_url_write_error` 测试**

```python
@pytest.mark.asyncio
async def test_svn_url_write_error(single_config):
    """URL 配置 + 写命令 -> 返回明确错误。"""
    url_config = Config(
        llm=single_config.llm,
        tapd=single_config.tapd,
        tortoisesvn=TortoiseSvnConfig(paths={"default": "https://svn.example.com/repo"}),
    )
    with patch.object(nimo.tools.tortoisesvn, "_config", url_config):
        result = await nimo.tools.tortoisesvn.svn(command="commit", extra_args=["-m", "test"])
        assert result.success is False
        assert "本地工作副本" in result.error
```

- [ ] **Step 14: 运行测试验证失败**

Run: `pytest tests/test_tortoisesvn.py::test_svn_url_write_error -v`
Expected: FAIL（当前不会报 URL 错误）

- [ ] **Step 15: 在 `svn()` 中添加 URL+写命令检查**

在 `_validate_args` 和 `_build_args` 之间插入：

```python
    if _is_url(resolved_path) and command not in _READONLY_COMMANDS:
        return ToolResult(
            success=False,
            error=f"{command} 需要本地工作副本，但配置的是远端 URL",
        )
```

- [ ] **Step 16: 运行测试验证通过**

Run: `pytest tests/test_tortoisesvn.py::test_svn_url_write_error -v`
Expected: PASS

- [ ] **Step 17: 添加 `test_svn_url_log_success` 集成测试**

```python
@pytest.mark.asyncio
async def test_svn_url_log_success():
    """URL 配置 + 只读命令 log -> URL 被传入 svn.exe。"""
    url_config = Config(
        llm=LLMConfig(api_key="sk-test", base_url="https://api.deepseek.com",
                      model="deepseek-chat", max_tool_rounds=5, history_rounds=10),
        tapd=TapdConfig(api_base="https://api.tapd.cn", access_token="token123"),
        tortoisesvn=TortoiseSvnConfig(paths={"default": "https://svn.example.com/repo"}),
    )
    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"r123 | user | log msg", b""))

    with patch.object(nimo.tools.tortoisesvn, "_config", url_config):
        with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)) as mock_exec:
            result = await nimo.tools.tortoisesvn.svn(command="log")
            assert result.success is True
            call_args = mock_exec.call_args[0]
            assert any("https://svn.example.com/repo" in arg for arg in call_args)
```

- [ ] **Step 18: 运行测试验证通过**

Run: `pytest tests/test_tortoisesvn.py::test_svn_url_log_success -v`
Expected: PASS

- [ ] **Step 19: 运行全部 tortoisesvn 测试确保无回归**

Run: `pytest tests/test_tortoisesvn.py -v`
Expected: 全部 PASS

- [ ] **Step 20: 提交**

```bash
git add nimo/tools/tortoisesvn.py tests/test_tortoisesvn.py
git commit -m "feat: tortoisesvn.py 支持远端 URL — 只读命令直接对 URL 执行"
```

---

### Task 2: engine.py — URL 支持

**Files:**
- Modify: `nimo/engine.py`
- Modify: `tests/test_engine.py`

**Interfaces:**
- Produces: `engine._is_url(path: str) -> bool` — 模块级函数
- Produces: `engine._READONLY_COMMANDS: frozenset[str]` — 模块级常量
- Produces: 修改后的 `_run_svn()` — URL+只读命令追加 URL 到参数
- Produces: 修改后的 `_execute_svn()` — URL 跳过 `..` 校验，URL+写命令提前返回错误

- [ ] **Step 1: 添加 `test_is_url` 和 `test_is_url_local_path` 到 test_engine.py**

```python
def test_is_url():
    from nimo import engine
    assert engine._is_url("https://svn.example.com/repo") is True
    assert engine._is_url("http://svn.example.com/repo") is True
    assert engine._is_url("svn://svn.example.com/repo") is True
    assert engine._is_url("svn+ssh://svn.example.com/repo") is True


def test_is_url_local_path():
    from nimo import engine
    assert engine._is_url(r"C:\Users\test\repo") is False
    assert engine._is_url("/home/user/repo") is False
    assert engine._is_url("") is False
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_engine.py::test_is_url tests/test_engine.py::test_is_url_local_path -v`
Expected: FAIL with `AttributeError: module 'nimo.engine' has no attribute '_is_url'`

- [ ] **Step 3: 在 engine.py 添加 `_is_url()` 和 `_READONLY_COMMANDS`**

在 `_FOR_EACH_ACTIONS` 常量旁添加：

```python
_READONLY_COMMANDS = frozenset({
    "log", "diff", "blame", "info", "properties",
})


def _is_url(s: str) -> bool:
    return s.startswith(("http://", "https://", "svn://", "svn+ssh://"))
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_engine.py::test_is_url tests/test_engine.py::test_is_url_local_path -v`
Expected: PASS

- [ ] **Step 5: 修改 `_run_svn()` 支持 URL 路径**

变更 `_run_svn` 中参数拼接部分，将：

```python
        elif path:
            args.append(path)
```

改为：

```python
        elif _is_url(path):
            args.append(path)
        elif path:
            args.append(path)
```

- [ ] **Step 6: 添加 `test_svn_url_readonly` 到 test_engine.py**

```python
@pytest.mark.asyncio
async def test_svn_url_readonly(sample_config):
    """引擎 _execute_svn：URL 配置 + 只读命令 log -> 成功调用 svn.exe <URL>。"""
    sample_config.tortoisesvn = TortoiseSvnConfig(
        paths={"default": "https://svn.example.com/repo"}
    )
    engine = ExecutionEngine.get_instance()
    engine.init(sample_config)

    mock_proc = MagicMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"r123 | user | log msg", b""))

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=mock_proc)) as mock_exec:
        result = await engine.execute(Intent(
            tool="svn", action="log",
            params={"project": "default", "extra": {"limit": 5}},
        ))
    assert result.success is True
    assert "r123" in str(result.data)
    call_args = mock_exec.call_args[0]
    assert any("https://svn.example.com/repo" in arg for arg in call_args)
```

- [ ] **Step 7: 运行测试验证通过**

Run: `pytest tests/test_engine.py::test_svn_url_readonly -v`
Expected: PASS

- [ ] **Step 8: 在 `_execute_svn()` 添加 URL 校验逻辑**

在路径遍历检查处（`_execute_svn` 方法内），将：

```python
        if ".." in path.replace("/", "\\"):
            return ToolResult(success=False, error=f"路径包含路径遍历：{path}")
```

改为：

```python
        if not _is_url(path) and ".." in path.replace("/", "\\"):
            return ToolResult(success=False, error=f"路径包含路径遍历：{path}")

        if _is_url(path) and action not in _READONLY_COMMANDS:
            return ToolResult(
                success=False,
                error=f"{action} 需要本地工作副本，但配置的是远端 URL",
            )
```

- [ ] **Step 9: 添加 `test_svn_url_write_error` 到 test_engine.py**

```python
@pytest.mark.asyncio
async def test_svn_url_write_error(sample_config):
    """引擎 _execute_svn：URL 配置 + 写命令 commit -> 返回明确错误。"""
    sample_config.tortoisesvn = TortoiseSvnConfig(
        paths={"default": "https://svn.example.com/repo"}
    )
    engine = ExecutionEngine.get_instance()
    engine.init(sample_config)

    result = await engine.execute(Intent(
        tool="svn", action="commit",
        params={"project": "default", "extra": {"message": "test"}},
    ))
    assert result.success is False
    assert "本地工作副本" in result.error
```

- [ ] **Step 10: 运行测试验证通过**

Run: `pytest tests/test_engine.py::test_svn_url_write_error -v`
Expected: PASS

- [ ] **Step 11: 运行全部 engine 测试确保无回归**

Run: `pytest tests/test_engine.py -v`
Expected: 全部 PASS

- [ ] **Step 12: 运行全部测试确保无回归**

Run: `pytest tests/ -v`
Expected: 全部 PASS

- [ ] **Step 13: 提交**

```bash
git add nimo/engine.py tests/test_engine.py
git commit -m "feat: engine.py 支持远端 URL — 只读命令直接对 URL 执行"
```

---

### 自检清单

- [x] **Spec coverage**: URL 检测/只读命令+URL/写命令+URL/本地路径回归/路径遍历跳过/`_URL_BEFORE_PATH` 不变 — 全部有对应测试步骤
- [x] **Placeholder scan**: 无 TBD/TODO/占位符
- [x] **Type consistency**: `_is_url(str) -> bool` 在两个文件签名一致，`_READONLY_COMMANDS` 值一致
