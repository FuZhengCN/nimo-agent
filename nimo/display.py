"""Nimo CLI 启动欢迎画面。"""

import io
import re
import shutil
import unicodedata

from rich.console import Console
from rich.markdown import Markdown
from rich.style import Style
from rich.theme import Theme

# ANSI 颜色定义
GRAY = "\033[90m"
CYAN = "\033[38;2;36;168;208m"
RESET = "\033[0m"

# 预编译 ANSI escape 正则
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")

NIMO_LOGO = [
    " ███╗   ██╗ ██╗ ███╗   ███╗  ██████╗ ",
    " ████╗  ██║ ██║ ████╗ ████║ ██╔═══██╗",
    " ██╔██╗ ██║ ██║ ██╔████╔██║ ██║   ██║",
    " ██║╚██╗██║ ██║ ██║╚██╔╝██║ ██║   ██║",
    " ██║ ╚████║ ██║ ██║ ╚═╝ ██║ ╚██████╔╝",
    " ╚═╝  ╚═══╝ ╚═╝ ╚═╝     ╚═╝  ╚═════╝ ",
]

COMMAND_TIPS = [
    "/help 查看帮助",
    "/chain 查看上一轮工具调用链",
    "/clear 清除当前对话历史",
    "/clear-profile 清除长期用户档案",
    "/exit 退出程序",
]

EXAMPLE_TIPS = [
    "\"帮我看看有哪些项目\"",
    "\"创建一个需求：修复登录bug\"",
    "\"给任务1001填4小时工时\"",
    "\"看看今天的代码提交记录\"",
    "\"最近谁改过 main.c？\"",
    "\"更新工作副本到最新版本\"",
    "\"5分钟后检查我的待办任务\"",
]


def _get_term_width() -> int:
    """获取终端宽度，最小 80。"""
    try:
        return max(80, shutil.get_terminal_size().columns)
    except (OSError, ValueError):
        return 90


def _color_text(text: str, code: str) -> str:
    """用 ANSI code 包裹文本，末尾追加 RESET。"""
    return f"\033[{code}m{text}{RESET}"


def _display_width(text: str) -> int:
    """计算字符串在终端中的显示列宽（ANSI 转义码不计，CJK 字符计 2 列）。"""
    clean = _ANSI_RE.sub("", text)
    w = 0
    for ch in clean:
        ea = unicodedata.east_asian_width(ch)
        w += 2 if ea in ("W", "F") else 1
    return w


def _pad_visible(text: str, width: int, align: str = "left") -> str:
    """按可见宽度填充文本（ANSI 转义码不计入宽度）。"""
    vis = _display_width(text)
    if vis >= width:
        return text
    pad = width - vis
    if align == "center":
        left_pad = pad // 2
        right_pad = pad - left_pad
        return " " * left_pad + text + " " * right_pad
    else:  # left
        return text + " " * pad


def _build_top(version: str, left_w: int, right_w: int) -> str:
    """顶部边框：╭─── Nimo v{version} ──┬──────────╮"""
    left_prefix = f"─── Nimo v{version} "
    left = f"╭{left_prefix}{'─' * (left_w - len(left_prefix))}"
    right = f"{'─' * right_w}╮"
    return f"{GRAY}{left}┬{right}{RESET}"


def _build_bottom(left_w: int, right_w: int) -> str:
    """底部边框：╰────────┴────────╯"""
    return f"{GRAY}╰{'─' * left_w}┴{'─' * right_w}╯{RESET}"


def _build_row(left: str, right: str) -> str:
    """中间行：│ left_content │ right_content │"""
    return f"{GRAY}│{RESET}{left}{GRAY}│{RESET}{right}{GRAY}│{RESET}"


def _build_left_panel(model: str, cwd: str, left_w: int) -> list[str]:
    """构建左侧面板行列表。"""
    lines = []
    lines.append(" " * left_w)
    welcome = _color_text("Welcome to Nimo!", "1")
    lines.append(_pad_visible(welcome, left_w, "center"))
    desc = f"\033[2mTAPD · SVN{RESET}"
    lines.append(_pad_visible(desc, left_w, "center"))
    lines.append(" " * left_w)
    for logo_line in NIMO_LOGO:
        colored = _color_text(logo_line, "38;2;36;168;208")
        lines.append(_pad_visible(colored, left_w, "center"))
    lines.append(" " * left_w)
    model_line = f"{GRAY}{model}{RESET} · {CYAN}Nimo Agent{RESET}"
    lines.append(_pad_visible(model_line, left_w, "left"))
    cwd_line = f"{GRAY}{cwd}{RESET}"
    lines.append(_pad_visible(cwd_line, left_w, "left"))
    return lines


def _build_right_panel(right_w: int) -> list[str]:
    """构建右侧面板行列表。"""
    lines = []
    title = _color_text("Tips for getting started", "38;2;242;138;56")
    lines.append(_pad_visible(title, right_w, "left"))
    lines.append(" " * right_w)
    # 命令
    lines.append(_pad_visible(_color_text("命令", "38;2;242;138;56"), right_w, "left"))
    for cmd in COMMAND_TIPS:
        lines.append(_pad_visible(f"  {cmd}", right_w, "left"))
    lines.append(" " * right_w)
    # 示例
    lines.append(_pad_visible(_color_text("试试这样说", "38;2;242;138;56"), right_w, "left"))
    for ex in EXAMPLE_TIPS:
        lines.append(_pad_visible(f"  {ex}", right_w, "left"))
    return lines


_CONTENT_THEME = Theme({
    "markdown.h1": Style(bold=True),
    "markdown.h2": Style(bold=True),
    "markdown.h3": Style(bold=True),
    "markdown.h4": Style(bold=True),
    "markdown.h5": Style(bold=True),
    "markdown.h6": Style(bold=True),
    "markdown.code": Style(dim=True),
    "markdown.code_block": Style(dim=True),
    "markdown.table.header": Style(bold=True),
    "markdown.table.border": Style(dim=True),
    "markdown.item.bullet": Style(dim=True),
    "markdown.block_quote": Style(dim=True),
})


def print_response_box(text: str, token_summary: str | None = None, tool_counts: dict[str, int] | None = None) -> None:
    """以 rich Markdown 渲染 LLM 回复，仅上下边框。顶部右侧展示工具调用信息。"""
    term_w = _get_term_width()
    box_w = term_w - 4

    buf = io.StringIO()
    Console(file=buf, width=box_w - 2, force_terminal=True, theme=_CONTENT_THEME).print(Markdown(text))
    rendered = buf.getvalue().rstrip("\n")

    # 顶部边框：左侧 "╭─ Nimo "，右侧可选工具标签，最右 "╮"
    tool_tag = ""
    if tool_counts:
        parts = []
        for name, count in sorted(tool_counts.items()):
            short = name.replace("tapd_cli", "tapd").replace("_", " ")
            parts.append(f"{short} x {count}" if count > 1 else short)
        tool_tag = f" {GRAY}{', '.join(parts)}{RESET} "
    tag_vis = _display_width(tool_tag) if tool_tag else 0
    # ╭─ Nimo  = 8 visible，╮ = 1 → dash_len = box_w - 9 - tag_vis
    dash_len = max(0, box_w - 9 - tag_vis)
    top = f"{CYAN}╭─ Nimo {'─' * dash_len}{tool_tag}{CYAN}╮{RESET}"
    if token_summary:
        dash_count = max(0, box_w - 4 - len(token_summary))
        bottom = f"{CYAN}╰{'─' * dash_count} {GRAY}{token_summary}{CYAN} ╯{RESET}"
    else:
        bottom = f"{CYAN}╰{'─' * (box_w - 2)}╯{RESET}"

    print(top)
    for line in rendered.split("\n"):
        print(f"  {line}")
    print(bottom)


def print_welcome(model: str, cwd: str, version: str) -> None:
    """打印完整欢迎画面（自动撑满终端宽度）。"""
    term_w = _get_term_width()
    left_w = term_w * 6 // 10
    right_w = max(30, term_w - left_w - 3)
    left_w = term_w - right_w - 3

    left_lines = _build_left_panel(model, cwd, left_w)
    right_lines = _build_right_panel(right_w)

    max_lines = max(len(left_lines), len(right_lines))
    while len(left_lines) < max_lines:
        left_lines.append(" " * left_w)
    while len(right_lines) < max_lines:
        right_lines.append(" " * right_w)

    print(_build_top(version, left_w, right_w))
    for left, right in zip(left_lines, right_lines):
        print(_build_row(left, right))
    print(_build_bottom(left_w, right_w))
