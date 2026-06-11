# 工具系统可扩展性改造

**日期**: 2026-06-11 | **状态**: 已确认

## 背景

当前项目只接入了 `tapd_cli` 一个工具，但存在 4 处硬编码阻碍了后续扩展。改造目标是：新增工具只需在 `nimo/tools/` 下写一个 `.py` 文件 + `@register_tool` 装饰器，不改任何其他文件。

## 改动点

### 1. `_compact_tool_results()` 动态工具名

**文件**: `nimo/agent.py`

**问题**: 成功摘要字符串硬编码 `tapd_cli`，加新工具后所有摘要都标成 `tapd_cli`。

**改法**: 在 `_compact_tool_results()` 中，遍历 `start_idx` 之后的消息，从 assistant 消息的 `tool_calls` 提取 `tool_call_id → function.name` 映射；处理 tool 消息时用 `msg["tool_call_id"]` 查表获取工具名。

```python
# 改前
summary = f"[tapd_cli 返回 {len(raw)} 字符]"

# 改后：先遍历收集 name_map
name_map: dict[str, str] = {}
for i in range(start_idx, len(self._history._messages)):
    m = self._history._messages[i]
    if m["role"] == "assistant" and m.get("tool_calls"):
        for tc in m["tool_calls"]:
            name_map[tc["id"]] = tc["function"]["name"]

# 再压缩工具结果时使用动态名
tool_name = name_map.get(msg.get("tool_call_id", ""), "未知工具")
summary = f"[{tool_name} 返回 {len(raw)} 字符]"
```

### 2. 工具模块自动发现

**文件**: `nimo/tools/__init__.py`, `nimo/main.py`

**问题**: `main.py` 显式 `import nimo.tools.tapd`，加新工具需手动添加 import。

**改法**: `__init__.py` 中用 `pkgutil.iter_modules` 扫描并 import 所有不以 `_` 开头的模块。`main.py` 删除显式 import。

约定：工具模块名不以 `_` 开头，非工具模块（`registry`）跳过。import 失败时 log warning 并继续，不允许单个工具模块的错误阻止启动。

### 3. 通用工具初始化

**文件**: `nimo/tools/registry.py`, `nimo/tools/tapd.py`, `nimo/main.py`

**问题**: `build_agent()` 直接调用 `init_tapd(config)`，加新工具需要在此处新增 init 调用。

**改法**: `ToolRegistry` 新增 `register_init()` + `init_all()`。工具模块的 init 函数通过 `register_init` 注册，`build_agent()` 改为调用 `ToolRegistry.get_instance().init_all(config)`。`init_all` 中单个 init 失败时 log warning 并继续，不阻塞其他工具初始化。

### 4. system prompt 动态工具列表

**文件**: `nimo/agent.py`, `nimo/prompts/system.md`

**问题**: `system.md` 硬编码 `tapd_cli` 能力描述，LLM 不知道其他可用工具。

**改法**: `_load_system_prompt()` 加载 `system.md` 后自动追加 `## 可用工具` 章节，从 registry 动态生成。`system.md` 删除现有的 TAPD 专属描述。

## 影响范围

| 文件 | 改动量 |
|------|--------|
| `nimo/agent.py` | ~20 行（两个方法修改） |
| `nimo/tools/registry.py` | ~8 行（init 注册机制） |
| `nimo/tools/__init__.py` | ~5 行（自动发现） |
| `nimo/tools/tapd.py` | +1 行（注册 init） |
| `nimo/main.py` | -4 行（删除显式 import 和 init_tapd 调用） |
| `nimo/prompts/system.md` | -3 行，+2 行（删除 TAPD 专属，保留通用准则） |

## 新增工具的标准流程（改造后）

1. 在 `nimo/tools/` 下新建 `mytool.py`
2. 用 `@register_tool(...)` 装饰工具函数
3. 如有初始化需求，调用 `ToolRegistry.get_instance().register_init(my_init)`

不改 `main.py`、不改 `agent.py`、不改 `system.md`、不改 `__init__.py`。
