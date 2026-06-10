# Nimo CLI 启动欢迎画面 — 设计文档

日期：2026-06-10 | 状态：已确认

## 概述

Nimo CLI 启动时显示一个带圆角边框的欢迎画面，参考 Claude Code 的启动画面风格，包含 Logo、欢迎语、使用提示和系统信息。

## 布局结构

```
╭─── Nimo v{version} ──────────────┬──────────────────────────────╮
│                                  │  Tips for getting started    │
│         Welcome to Nimo!         │  · tip 1                     │
│                                  │  · tip 2                     │
│         [NIMO LOGO]              │  · tip 3                     │
│                                  │  · tip 4                     │
│                                  │                              │
│  {model} · Nimo Agent            │                              │
│         {cwd}                    │                              │
╰──────────────────────────────────┴──────────────────────────────╯
```

- 固定宽度 90 字符，左面板 ~50 字符，右面板 ~40 字符
- 圆角边框字符：`╭` `╮` `╰` `╯` `│` `─` `┬` `┴`
- 无 What's New 区域（后续需要时再加）

## Logo

ANSI Shadow 字体大文字 NIMO，6 行 × 40 字符：

```
███╗   ██╗██╗███╗   ███╗ ██████╗
████╗  ██║██║████╗ ████║██╔═══██╗
██╔██╗ ██║██║██╔████╔██║██║   ██║
██║╚██╗██║██║██║╚██╔╝██║██║   ██║
██║ ╚████║██║██║ ╚═╝ ██║╚██████╔╝
╚═╝  ╚═══╝╚═╝╚═╝     ╚═╝ ╚═════╝
```

## 配色方案

| 元素 | 颜色 | HEX | ANSI 实现 |
|------|------|-----|-----------|
| 边框 | 深灰 | #666666 | `\033[90m` |
| Logo NIMO | 青蓝 | #24A8D0 | `\033[38;2;36;168;208m` |
| 欢迎语 "Welcome to Nimo!" | 白色粗体 | #FFFFFF | `\033[1m` |
| Tips 标题 "Tips for getting started" | 暖橙 | #F28A38 | `\033[38;2;242;138;56m` |
| Tips 条目 | 终端默认 | — | 无 |
| 底部模型名/路径 | 灰色 | #888888 | `\033[90m` |
| 版本号（标题栏） | 灰色 | #888888 | `\033[90m` |
| "Nimo Agent"（底部） | 青蓝 | #24A8D0 | `\033[38;2;36;168;208m` |

## 文案内容

**欢迎语**：`Welcome to Nimo!`

**Tips 条目**（英文，保证终端等宽对齐）：

1. `Type /help for available commands`
2. `/exit to quit`
3. `Check projects: "show my projects"`
4. `Log hours: "help me log hours"`

## 版本号

硬编码字符串 `"0.1.0"`，后续需要时改为从 `pyproject.toml` 或 `__version__` 读取。

## 实现方案

### 新文件：`nimo/welcome.py`

对外暴露 `print_welcome(model, cwd, version)` 一个入口函数。

内部结构：

```
NIMO_LOGO: Final[str]        # Logo 字符画常量（含 ANSI 颜色）
TIPS: Final[list[str]]       # 提示条目常量
_build_border_top(v)          # → ╭─── Nimo v{version} ──┬──────────╮
_build_border_bottom()        # → ╰────────┴────────────╯
_build_left_panel()           # 左半：欢迎语 + Logo
_build_right_panel()          # 右半：Tips
_build_bottom_bar(model, cwd) # 底部：模型 + 路径
print_welcome(model, cwd, v)  # 唯一公开函数，print 完整画面
```

### 修改文件：`nimo/main.py`

在 `build_agent()` 之后、`while` 循环之前，增加一行调用：

```python
from nimo.welcome import print_welcome

# 在 main() 中：
print_welcome(model=config.llm.model, cwd=os.getcwd(), version="0.1.0")
```

### 非功能需求

- 不引入新依赖
- 支持 24bit 真彩色终端（主流终端均支持）
- 不支持 24bit 的终端回退时颜色会丢失但不影响可读性

## 不变更范围

- `nimo/config.py` — 不改动
- `nimo/agent.py` — 不改动
- 不新增依赖包
- 不新增配置文件
- 不添加 ANSI 颜色开关（终端不支持时自动回退）
