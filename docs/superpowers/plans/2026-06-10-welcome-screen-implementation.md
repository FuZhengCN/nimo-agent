# Nimo CLI 启动欢迎画面 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Nimo CLI 启动时显示带 Logo、欢迎语、使用提示和系统信息的圆角边框欢迎画面。

**Architecture:** 新增 `nimo/welcome.py` 模块，封装所有欢迎画面生成逻辑，对外暴露 `print_welcome()` 一个入口函数。`main.py` 增加一行调用。不引入新依赖。

**Tech Stack:** Python 3, ANSI escape codes (24bit 真彩色), 无第三方依赖

---

## 文件结构

| 文件 | 操作 | 职责 |
|------|------|------|
| `nimo/welcome.py` | **新建** | Logo 常量、Tips 常量、布局拼接、`print_welcome()` 入口 |
| `nimo/main.py` | **修改** | 在 `while` 循环前调用 `print_welcome()` |
| `tests/test_welcome.py` | **新建** | 测试 Logo/Tips 常量、行生成函数、整体输出 |

---

### Task 1: 创建 `nimo/welcome.py`（TDD）

**Files:**
- Create: `nimo/welcome.py`
- Create: `tests/test_welcome.py`

#### Step 1: 写测试文件

```python
# tests/test_welcome.py
import io
import sys
from nimo.welcome import NIMO_LOGO, TIPS, _build_top, _build_bottom, _build_row, _color_text, print_welcome


class TestConstants:
    def test_logo_has_6_lines(self):
        assert len(NIMO_LOGO) == 6

    def test_logo_lines_non_empty(self):
        for line in NIMO_LOGO:
            assert len(line.strip()) > 0

    def test_tips_has_4_entries(self):
        assert len(TIPS) == 4

    def test_tips_non_empty(self):
        for tip in TIPS:
            assert len(tip) > 0


class TestColorText:
    def test_color_text_wraps_with_ansi(self):
        result = _color_text("hello", "36")
        assert result.startswith("\033[36m")
        assert result.endswith("\033[0m")
        assert "hello" in result

    def test_color_text_empty_string(self):
        result = _color_text("", "36")
        assert result == "\033[36m\033[0m"


class TestBorderFunctions:
    def test_build_top_contains_version(self):
        result = _build_top("0.1.0")
        assert "0.1.0" in result
        assert "╭" in result
        assert "┬" in result
        assert "╮" in result

    def test_build_top_width_is_90(self):
        result = _build_top("0.1.0")
        assert _visible_width(result) == 90

    def test_build_bottom_width_is_90(self):
        result = _build_bottom()
        assert _visible_width(result) == 90

    def test_build_bottom_has_corners(self):
        result = _build_bottom()
        assert "╰" in result
        assert "┴" in result
        assert "╯" in result


class TestBuildRow:
    def test_build_row_width_is_90(self):
        result = _build_row("hello".ljust(50), "world".ljust(37))
        assert _visible_width(result) == 90

    def test_build_row_contains_separators(self):
        result = _build_row("left".ljust(50), "right".ljust(37))
        assert "│" in result
        assert result.count("│") == 3  # left, middle, right


class TestPrintWelcome:
    def test_print_welcome_output(self):
        output = io.StringIO()
        sys.stdout = output
        print_welcome(model="test-model", cwd="/test/path", version="0.1.0")
        sys.stdout = sys.__stdout__
        text = output.getvalue()

        assert "Welcome to Nimo!" in text
        assert "Tips for getting started" in text
        assert "test-model" in text
        assert "/test/path" in text
        assert "0.1.0" in text


def _visible_width(s: str) -> int:
    """计算去除 ANSI escape code 后的可见字符宽度。"""
    import re
    no_ansi = re.sub(r"\033\[[0-9;]*m", "", s)
    return len(no_ansi)
```

- [ ] **Step 1: Run tests to verify they fail**

```bash
pytest tests/test_welcome.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'nimo.welcome'`

---

#### Step 2: 写 `nimo/welcome.py` 最小实现

```python
# nimo/welcome.py
"""Nimo CLI 启动欢迎画面。"""

import re

# 布局常量
WIDTH = 90
LEFT_W = 50
RIGHT_W = 37

# ANSI 颜色定义
GRAY = "\033[90m"
CYAN = "\033[38;2;36;168;208m"
ORANGE = "\033[38;2;242;138;56m"
BOLD = "\033[1m"
RESET = "\033[0m"

NIMO_LOGO = [
    "███╗   ██╗██╗███╗   ███╗ ██████╗",
    "████╗  ██║██║████╗ ████║██╔═══██╗",
    "██╔██╗ ██║██║██╔████╔██║██║   ██║",
    "██║╚██╗██║██║██║╚██╔╝██║██║   ██║",
    "██║ ╚████║██║██║ ╚═╝ ██║╚██████╔╝",
    "╚═╝  ╚═══╝╚═╝╚═╝     ╚═╝ ╚═════╝",
]

TIPS = [
    "输入 /help 查看所有可用命令",
    "/exit 退出程序",
    "查 TAPD 项目：输入\"我有哪些项目\"",
    "填工时：输入\"帮我填工时\"",
]


def _color_text(text: str, code: str) -> str:
    """用 ANSI code 包裹文本，末尾追加 RESET。"""
    return f"\033[{code}m{text}{RESET}"


def _visible_width(text: str) -> int:
    """去除 ANSI escape code 后的可见字符数。"""
    return len(re.sub(r"\033\[[0-9;]*m", "", text))


def _pad_visible(text: str, width: int, align: str = "left") -> str:
    """按可见宽度填充文本（ANSI 转义码不计入宽度）。"""
    vis = _visible_width(text)
    if vis >= width:
        return text
    pad = width - vis
    if align == "center":
        left_pad = pad // 2
        right_pad = pad - left_pad
        return " " * left_pad + text + " " * right_pad
    else:  # left
        return text + " " * pad


def _build_top(version: str) -> str:
    """顶部边框：╭─── Nimo v{version} ──┬──────────╮"""
    left_prefix = f"─── Nimo v{version} "
    left = f"╭{left_prefix}{'─' * (LEFT_W - len(left_prefix))}"
    right = f"{'─' * RIGHT_W}╮"
    return f"{GRAY}{left}┬{right}{RESET}"


def _build_bottom() -> str:
    """底部边框：╰────────┴────────╯"""
    return f"{GRAY}╰{'─' * LEFT_W}┴{'─' * RIGHT_W}╯{RESET}"


def _build_row(left: str, right: str) -> str:
    """中间行：│ left_content │ right_content │"""
    return f"{GRAY}│{RESET}{left}{GRAY}│{RESET}{right}{GRAY}│{RESET}"


def _build_left_panel(model: str, cwd: str) -> list[str]:
    """构建左侧面板行列表。"""
    lines = []
    # 空行（上方留白）
    lines.append(" " * LEFT_W)
    # 欢迎语
    welcome = _color_text("Welcome to Nimo!", "1")
    lines.append(_pad_visible(welcome, LEFT_W, "center"))
    # 空行
    lines.append(" " * LEFT_W)
    # Logo（6行）
    for logo_line in NIMO_LOGO:
        colored = _color_text(logo_line, "38;2;36;168;208")
        lines.append(_pad_visible(colored, LEFT_W, "center"))
    # 空行（Logo 下方留白）
    lines.append(" " * LEFT_W)
    # 底部信息行
    model_line = f"{GRAY}{model}{RESET} · {CYAN}Nimo Agent{RESET}"
    lines.append(_pad_visible(model_line, LEFT_W, "left"))
    cwd_line = f"{GRAY}{cwd}{RESET}"
    lines.append(_pad_visible(cwd_line, LEFT_W, "left"))
    return lines


def _build_right_panel() -> list[str]:
    """构建右侧面板行列表。"""
    lines = []
    # 提示标题
    title = _color_text("Tips for getting started", "38;2;242;138;56")
    lines.append(_pad_visible(title, RIGHT_W, "left"))
    # 分隔空行
    lines.append(" " * RIGHT_W)
    # 提示条目
    for tip in TIPS:
        lines.append(_pad_visible(f"· {tip}", RIGHT_W, "left"))
    return lines


def print_welcome(model: str, cwd: str, version: str) -> None:
    """打印完整欢迎画面。"""
    left_lines = _build_left_panel(model, cwd)
    right_lines = _build_right_panel()

    # 两侧行数对齐
    max_lines = max(len(left_lines), len(right_lines))
    while len(left_lines) < max_lines:
        left_lines.append(" " * LEFT_W)
    while len(right_lines) < max_lines:
        right_lines.append(" " * RIGHT_W)

    # 输出
    print(_build_top(version))
    for left, right in zip(left_lines, right_lines):
        print(_build_row(left, right))
    print(_build_bottom())
```

- [ ] **Step 2: Run tests to verify they pass**

```bash
pytest tests/test_welcome.py -v
```

Expected: All 12 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add nimo/welcome.py tests/test_welcome.py
git commit -m "feat: add welcome screen module with logo, tips, and ANSI color support"
```

---

### Task 2: 修改 `nimo/main.py` 接入欢迎画面

**Files:**
- Modify: `nimo/main.py`

#### Step 1: 修改 main.py

在 `nimo/main.py` 顶部 import 区新增：

```python
import os
from nimo.welcome import print_welcome
```

在 `main()` 函数中，`build_agent()` 之后、`while` 循环之前，将原来的：

```python
    agent = build_agent()
    print("Nimo 就绪，输入 /exit 退出")
```

改为：

```python
    agent = build_agent()
    print_welcome(model=config.llm.model, cwd=os.getcwd(), version="0.1.0")
```

注意：`import os` 如果已存在则不需要重复添加。

- [ ] **Step 1: Commit**

```bash
git add nimo/main.py
git commit -m "feat: integrate welcome screen into main entry point"
```

---

### Task 3: 手动验证

- [ ] **Step 1: 启动程序查看欢迎画面**

```bash
python -m nimo.main
```

验证清单：
- [ ] 边框完整，圆角字符 `╭╮╰╯` 正常显示
- [ ] 标题栏显示 `Nimo v0.1.0`
- [ ] Logo 6 行完整，颜色为青蓝色
- [ ] "Welcome to Nimo!" 白色粗体居中
- [ ] "Tips for getting started" 橙色
- [ ] 4 条 Tips 内容正确
- [ ] 底部显示模型名（灰色）和当前目录（灰色）
- [ ] "Nimo Agent" 为青蓝色
- [ ] 整体宽度 90 字符，无错位

- [ ] **Step 2: 验证输入循环正常**

输入 `测试消息`，确认 Agent 正常响应，欢迎画面不影响功能。

---

### 不变更范围

- `nimo/config.py` — 不改动
- `nimo/agent.py` — 不改动
- `config.yaml` — 不改动
- 不新增依赖
