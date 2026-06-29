import io
import sys
from nimo.display import NIMO_LOGO, _color_text, _display_width, print_welcome, print_response_box


class TestConstants:
    def test_logo_has_4_lines(self):
        assert len(NIMO_LOGO) == 4

    def test_logo_lines_non_empty(self):
        for line in NIMO_LOGO:
            assert len(line.strip()) > 0


class TestColorText:
    def test_color_text_wraps_with_ansi(self):
        result = _color_text("hello", "36")
        assert result.startswith("\033[36m")
        assert result.endswith("\033[0m")
        assert "hello" in result

    def test_color_text_empty_string(self):
        result = _color_text("", "36")
        assert result == "\033[36m\033[0m"


class TestPrintWelcome:
    def test_print_welcome_output(self):
        output = io.StringIO()
        try:
            sys.stdout = output
            print_welcome(model="test-model", cwd="/test/path", version="1.0.0")
        finally:
            sys.stdout = sys.__stdout__
        text = output.getvalue()

        assert "Nimo" in text
        assert "test-model" in text
        assert "/test/path" in text
        assert "1.0.0" in text
        assert "/help" in text
        assert "/exit" in text
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

