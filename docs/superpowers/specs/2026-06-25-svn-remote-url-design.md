# SVN 远端 URL 支持设计

**日期**: 2026-06-25
**状态**: 设计中

## 背景

当前所有 SVN 命令都要求 `config.yaml` 的 `tortoisesvn.paths` 中配置本地工作副本路径。用户希望只配置远端 SVN 仓库 URL 即可使用只读命令，无需本地 checkout。

## 设计目标

- `paths` 配置值自动识别为本地路径或远端 URL
- 只读命令（log/diff/blame/info/properties）可直接对远端 URL 执行
- 写命令（commit/update/add 等）在仅有 URL 时给出明确错误
- 最小改动，不影响现有本地路径行为

## 方案

### URL 自动识别

新增 `_is_url()` 辅助函数，以协议前缀判断：

```python
def _is_url(s: str) -> bool:
    return s.startswith(("http://", "https://", "svn://", "svn+ssh://"))
```

`paths` 字典的值以这些前缀开头的视为远端 URL，其余视为本地路径。无需改配置结构。

### 命令分类

**只读命令**（可对 URL 直接执行，无需本地 WC）：

`log`, `diff`, `blame`, `info`, `properties`

**写命令**（必须有本地 WC）：

`update`, `commit`, `add`, `revert`, `cleanup`, `resolve`, `switch`, `merge`, `lock`, `unlock`, `rename`, `remove`, `import`

**URL 优先命令**（URL 语义为操作目标/来源，非 WC 替代，行为不变）：

`checkout`, `switch`, `merge`, `import`, `export`

**特殊命令**（不变）：

`repocreate` — 始终用 svnadmin，需要本地路径

### 行为矩阵

| 配置值 | 命令类型 | 行为 |
|--------|---------|------|
| 本地路径 | 任意 | 不变，`svn <cmd> <path>` |
| 远端 URL | 只读 | `svn <cmd> <URL>` **（新）** |
| 远端 URL | 写 | 返回错误：该命令需要本地工作副本 |

### 改动文件

#### `nimo/tools/tortoisesvn.py`

1. 新增 `_is_url()` 和 `_READONLY_COMMANDS` frozenset
2. `_build_args()`: 命令不在 `_URL_BEFORE_PATH` 中、且 `_is_url(path)` 时，将 URL 追加到参数列表
3. `svn()`: `_validate_args` 后、`_build_args` 前插入 URL+写命令检查，提前返回 `ToolResult(success=False, error=...)`
4. URL 路径跳过 `..` 路径遍历校验

#### `nimo/engine.py`

1. 新增 `_is_url()`（或复用 tortoisesvn 的，放在 engine 中独立一份）和 `_READONLY_COMMANDS`
2. `_run_svn()`: 同 `_build_args` 逻辑，URL+只读命令时将 URL 追加到参数
3. `_execute_svn()`: 在路径遍历校验前判断 URL 并跳过，在 `_run_svn` 调用前检查 URL+写命令

### 配置示例

```yaml
tortoisesvn:
  paths:
    harmony: 'https://svn.example.com/repos/HarmonyOS'     # 远端，仅读
    confsdk: 'C:\Users\fuzheng\source\Confsdk_Daily'       # 本地，读写
```

### 不改的

- `config.py` — `paths: dict[str, str]` 不变
- `svn_intent.py` — 参数透传，不感知路径类型
- `_resolve_path` / `_resolve_svn_path` — 逻辑不变，返回的就是配置值
- 新增命令（如 `list`）— 范围外

## 测试要点

- URL 检测：各种协议前缀、本地路径不被误判
- 只读命令 + URL：log/diff/blame/info/properties 正确拼出 `svn <cmd> <URL>`
- 写命令 + URL：返回明确错误信息
- 本地路径命令：行为完全不变（回归）
- 路径遍历校验：URL 被正确跳过
- `_URL_BEFORE_PATH` 命令（checkout/switch 等）：行为不变
