"""Nimo CLI 启动欢迎画面。"""

import re

# 布局常量
LEFT_W = 50
RIGHT_W = 37

# ANSI 颜色定义
GRAY = "\033[90m"
CYAN = "\033[38;2;36;168;208m"
RESET = "\033[0m"

# 预编译 ANSI escape 正则
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")

NIMO_LOGO = [
    "███╗   ██╗██╗███╗   ███╗ ██████╗",
    "████╗  ██║██║████╗ ████║██╔═══██╗",
    "██╔██╗ ██║██║██╔████╔██║██║   ██║",
    "██║╚██╗██║██║██║╚██╔╝██║██║   ██║",
    "██║ ╚████║██║██║ ╚═╝ ██║╚██████╔╝",
    "╚═╝  ╚═══╝╚═╝╚═╝     ╚═╝ ╚═════╝",
]

TIPS = [
    "Type /help for available commands",
    "/exit to quit",
    "Check projects: \"show my projects\"",
    "Log hours: \"help me log hours\"",
]


def _color_text(text: str, code: str) -> str:
    """用 ANSI code 包裹文本，末尾追加 RESET。"""
    return f"\033[{code}m{text}{RESET}"


def _visible_width(text: str) -> int:
    """去除 ANSI escape code 后的可见字符数。"""
    return len(_ANSI_RE.sub("", text))


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
