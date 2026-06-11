import io
import sys
from nimo.display import NIMO_LOGO, COMMAND_TIPS, EXAMPLE_TIPS, _build_top, _build_bottom, _build_row, _color_text, _display_width, print_welcome, print_response_box


class TestConstants:
    def test_logo_has_6_lines(self):
        assert len(NIMO_LOGO) == 6

    def test_logo_lines_non_empty(self):
        for line in NIMO_LOGO:
            assert len(line.strip()) > 0

    def test_command_tips_has_entries(self):
        assert len(COMMAND_TIPS) >= 2

    def test_command_tips_non_empty(self):
        for tip in COMMAND_TIPS:
            assert len(tip) > 0

    def test_example_tips_has_entries(self):
        assert len(EXAMPLE_TIPS) >= 3

    def test_example_tips_non_empty(self):
        for tip in EXAMPLE_TIPS:
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
        result = _build_top("0.1.0", 50, 37)
        assert "0.1.0" in result
        assert "╭" in result
        assert "┬" in result
        assert "╮" in result

    def test_build_top_total_width(self):
        result = _build_top("0.1.0", 50, 37)
        assert _display_width(result) == 90  # 50 + 37 + 3 borders

    def test_build_bottom_total_width(self):
        result = _build_bottom(50, 37)
        assert _display_width(result) == 90  # 50 + 37 + 3 borders

    def test_build_bottom_has_corners(self):
        result = _build_bottom(50, 37)
        assert "╰" in result
        assert "┴" in result
        assert "╯" in result


class TestBuildRow:
    def test_build_row_width_is_90(self):
        result = _build_row("hello".ljust(50), "world".ljust(37))
        assert _display_width(result) == 90

    def test_build_row_contains_separators(self):
        result = _build_row("left".ljust(50), "right".ljust(37))
        assert "│" in result
        assert result.count("│") == 3  # left, middle, right


class TestPrintWelcome:
    def test_print_welcome_output(self):
        output = io.StringIO()
        try:
            sys.stdout = output
            print_welcome(model="test-model", cwd="/test/path", version="0.1.0")
        finally:
            sys.stdout = sys.__stdout__
        text = output.getvalue()

        assert "Welcome to Nimo!" in text
        assert "Tips for getting started" in text
        assert "test-model" in text
        assert "/test/path" in text
        assert "0.1.0" in text

        # Structural assertions
        assert "╭" in text
        assert "╮" in text
        assert "╰" in text
        assert "╯" in text
        assert len(text.splitlines()) >= 5


class TestPrintResponseBox:
    def test_basic_rendering(self):
        output = io.StringIO()
        try:
            sys.stdout = output
            print_response_box("Hello World")
        finally:
            sys.stdout = sys.__stdout__
        text = output.getvalue()
        assert "Hello World" in text
        assert "╭" in text
        assert "╰" in text

    def test_with_token_summary(self):
        output = io.StringIO()
        try:
            sys.stdout = output
            print_response_box("Test", token_summary="P:100 C:50")
        finally:
            sys.stdout = sys.__stdout__
        text = output.getvalue()
        assert "P:100 C:50" in text
        assert "╰" in text

    def test_empty_text(self):
        output = io.StringIO()
        try:
            sys.stdout = output
            print_response_box("")
        finally:
            sys.stdout = sys.__stdout__
        text = output.getvalue()
        assert "╭" in text
        assert "╰" in text

    def test_markdown_rendering(self):
        output = io.StringIO()
        try:
            sys.stdout = output
            print_response_box("# Title\n\nSome **bold** text")
        finally:
            sys.stdout = sys.__stdout__
        text = output.getvalue()
        assert "Title" in text
        assert "bold" in text

