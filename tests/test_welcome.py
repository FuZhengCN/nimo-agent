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
        assert "╭" in result  # ╭
        assert "┬" in result  # ┬
        assert "╮" in result  # ╮

    def test_build_top_width_is_90(self):
        result = _build_top("0.1.0")
        assert _visible_width(result) == 90

    def test_build_bottom_width_is_90(self):
        result = _build_bottom()
        assert _visible_width(result) == 90

    def test_build_bottom_has_corners(self):
        result = _build_bottom()
        assert "╰" in result  # ╰
        assert "┴" in result  # ┴
        assert "╯" in result  # ╯


class TestBuildRow:
    def test_build_row_width_is_90(self):
        result = _build_row("hello".ljust(50), "world".ljust(37))
        assert _visible_width(result) == 90

    def test_build_row_contains_separators(self):
        result = _build_row("left".ljust(50), "right".ljust(37))
        assert "│" in result  # │
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
