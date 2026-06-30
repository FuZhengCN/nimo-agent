"""Nimo CLI 启动欢迎画面。"""

import io
import re
import shutil
import unicodedata

from rich.console import Console
from rich.markdown import Markdown
from rich.style import Style
from rich.theme import Theme

# ANSI 颜色定义（所有颜色集中管理，其他模块从此导入）
CYAN = "\033[38;2;48;192;224m"         # #30C0E0 品牌蓝 Logo/标识
BLUE_DEEP = "\033[38;2;31;157;184m"    # #1F9DB8 深蓝 框线结构
GRAY_MUTED = "\033[38;2;200;200;200m"  # #C8C8C8 元数据文字
GRAY_SUBTLE = "\033[38;2;176;176;176m" # #B0B0B0 低优先级提示
ORANGE = "\033[38;2;242;138;56m"       # #F28A38 暖橙 输入提示/标题
ORANGE_DEEP = "\033[38;2;208;104;24m"  # #D06818 深橙 重要通知
RED_ERROR = "\033[38;2;224;85;85m"     # #E05555 暖调错误红
GREEN_SUCCESS = "\033[38;2;78;201;176m" # #4EC9B0 成功状态
YELLOW_WARN = "\033[38;2;232;200;90m"  # #E8C85A 警告状态
RESET = "\033[0m"

# 段落内颜色代码（不含 \033[ 前缀，供 _color_text 使用）
C_LOGO = "38;2;36;168;208"            # #24A8D0 Logo 文字色


# 预编译 ANSI escape 正则
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")

NIMO_LOGO = [
    "  ╭───╮",
    "  │· ·│",
    "  ╰───╯",
]

_COMMAND_HINTS = "/help 帮助  ·  /chain 调用链  ·  /clear 清除  ·  /exit 退出"



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





_CONTENT_THEME = Theme({
    "markdown.h1": Style(bold=True, color="#30C0E0"),
    "markdown.h2": Style(bold=True, color="#30C0E0"),
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
        tool_tag = f" {GRAY_MUTED}{', '.join(parts)}{RESET} "
    tag_vis = _display_width(tool_tag) if tool_tag else 0
    # ╭─ Nimo  = 8 visible，╮ = 1 → dash_len = box_w - 9 - tag_vis
    dash_len = max(0, box_w - 9 - tag_vis)
    top = f"{BLUE_DEEP}╭─ Nimo {'─' * dash_len}{tool_tag}{BLUE_DEEP}╮{RESET}"
    if token_summary:
        dash_count = max(0, box_w - 4 - len(token_summary))
        bottom = f"{BLUE_DEEP}╰{'─' * dash_count} {GRAY_MUTED}{token_summary}{BLUE_DEEP} ╯{RESET}"
    else:
        bottom = f"{BLUE_DEEP}╰{'─' * (box_w - 2)}╯{RESET}"

    print(top)
    for line in rendered.split("\n"):
        print(f"  {line}")
    print(bottom)


def print_welcome(model: str, cwd: str, version: str) -> None:
    """打印带边框的欢迎画面。"""
    import sys as _sys
    try:
        _sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    info = [
        f"\033[1mNimo\033[0m {CYAN}v{version}{RESET}",
        f"{GRAY_MUTED}{model} · Nimo Agent{RESET}",
        f"{GRAY_MUTED}{cwd}{RESET}",
    ]

    logo_w = max(_display_width(line) for line in NIMO_LOGO)

    content_lines = []
    for i in range(3):
        logo_line = _color_text(NIMO_LOGO[i].ljust(logo_w), C_LOGO)
        content_lines.append(f"{logo_line}   {info[i]}")
    content_lines.append("")
    content_lines.append(f"{GRAY_SUBTLE}  {_COMMAND_HINTS}{RESET}")

    max_w = max(_display_width(line) for line in content_lines)
    pad = 2
    inner_w = max_w + pad * 2

    print(f"{BLUE_DEEP}╭{'─' * inner_w}╮{RESET}")
    for line in content_lines:
        dw = _display_width(line)
        gap = " " * (max_w - dw)
        print(f"{BLUE_DEEP}│{RESET}{' ' * pad}{line}{gap}{' ' * pad}{BLUE_DEEP}│{RESET}")
    print(f"{BLUE_DEEP}╰{'─' * inner_w}╯{RESET}")
