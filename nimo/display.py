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
C_BLUE = "38;2;48;192;224"
C_ORANGE = "38;2;242;138;56"
C_LOGO = "38;2;36;168;208"            # #24A8D0 Logo 文字色
C_GREEN = "38;2;78;201;176"           # #4EC9B0 成功状态（段落内）
C_YELLOW = "38;2;232;200;90"          # #E8C85A 警告状态（段落内）


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
    "/exit 退出程序",
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
    return f"{BLUE_DEEP}{left}┬{right}{RESET}"


def _build_bottom(left_w: int, right_w: int) -> str:
    """底部边框：╰────────┴────────╯"""
    return f"{BLUE_DEEP}╰{'─' * left_w}┴{'─' * right_w}╯{RESET}"


def _build_row(left: str, right: str) -> str:
    """中间行：│ left_content │ right_content │"""
    return f"{BLUE_DEEP}│{RESET}{left}{BLUE_DEEP}│{RESET}{right}{BLUE_DEEP}│{RESET}"


def _build_left_panel(model: str, cwd: str, left_w: int) -> list[str]:
    """构建左侧面板行列表。"""
    lines = []
    lines.append(" " * left_w)
    welcome = _color_text("Welcome to Nimo!", "1")
    lines.append(_pad_visible(welcome, left_w, "center"))
    desc = f"{GRAY_SUBTLE}Ask. Execute. Done.{RESET}"
    lines.append(_pad_visible(desc, left_w, "center"))
    lines.append(" " * left_w)
    for logo_line in NIMO_LOGO:
        colored = _color_text(logo_line, C_LOGO)
        lines.append(_pad_visible(colored, left_w, "center"))
    lines.append(" " * left_w)
    model_line = f"{GRAY_MUTED}{model}{RESET} · {CYAN}Nimo Agent{RESET}"
    lines.append(_pad_visible(model_line, left_w, "left"))
    cwd_line = f"{GRAY_MUTED}{cwd}{RESET}"
    lines.append(_pad_visible(cwd_line, left_w, "left"))
    return lines


def _build_right_panel(right_w: int, total_lines: int) -> list[str]:
    """构建右侧面板行列表。分隔线纵向均分面板，内容各自在上下半区内居中。"""
    mid = total_lines // 2

    sec_op = _color_text("■", C_BLUE) + _color_text(" 支持的操作", C_BLUE)
    upper = [_pad_visible(sec_op, right_w, "left")]
    upper += [
        _pad_visible(f"  {_color_text('TAPD', C_BLUE)}  需求/任务/缺陷 · Wiki · 迭代 · 工时/评论", right_w, "left"),
        _pad_visible(f"  {_color_text('SVN', C_BLUE)}   日志/差异/追溯 · 更新/提交 · 合并/信息", right_w, "left"),
        _pad_visible(f"  {_color_text('智能', C_BLUE)}  Skill 扩展 · 定时任务 · Python 执行", right_w, "left"),
    ]

    sec_cmd = _color_text("■", C_BLUE) + _color_text(" 命令", C_BLUE)
    lower = [_pad_visible(sec_cmd, right_w, "left")]
    for cmd in COMMAND_TIPS:
        name, _, desc = cmd.partition(" ")
        lower.append(_pad_visible(f"  {_color_text(name, C_BLUE)} {desc}", right_w, "left"))

    def _center_in(lines: list[str], space: int) -> list[str]:
        before = (space - len(lines)) // 2
        after = space - len(lines) - before
        return [" " * right_w] * before + lines + [" " * right_w] * after

    lines = []
    lines += _center_in(upper, mid)
    lines.append(BLUE_DEEP + "─" * right_w + RESET)
    lines += _center_in(lower, total_lines - mid - 1)
    return lines


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
    """打印完整欢迎画面（自动撑满终端宽度）。"""
    term_w = _get_term_width()
    left_w = term_w * 6 // 10
    right_w = max(30, term_w - left_w - 3)
    left_w = term_w - right_w - 3

    left_lines = _build_left_panel(model, cwd, left_w)
    right_lines = _build_right_panel(right_w, len(left_lines))

    max_lines = max(len(left_lines), len(right_lines))
    while len(left_lines) < max_lines:
        left_lines.append(" " * left_w)
    while len(right_lines) < max_lines:
        right_lines.append(" " * right_w)

    print(_build_top(version, left_w, right_w))
    for left, right in zip(left_lines, right_lines):
        print(_build_row(left, right))
    print(_build_bottom(left_w, right_w))
