"""Skill 系统测试——discover / activate / deactivate / run_script / installer。"""
import tempfile
from pathlib import Path

import pytest

from nimo.skill.registry import SkillRegistry
from nimo.skill.installer import Installer


@pytest.fixture(autouse=True)
def reset_registry():
    SkillRegistry.reset()


# ---------------------------------------------------------------------------
# discover 三级降级
# ---------------------------------------------------------------------------

def _make_skill_yml(tmpdir: str, name: str, desc: str = "测试技能",
                     with_instructions: bool = True, with_scripts: bool = False):
    """Helper：创建 skill.yml 格式的技能目录。"""
    skill_dir = Path(tmpdir) / name
    skill_dir.mkdir()
    yml = f"name: {name}\ndescription: {desc}\nkeywords: [kw1, kw2]\n"
    if with_scripts:
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "hello.py").write_text("print('hello')")
        yml += "scripts:\n  - scripts/hello.py\n"
    (skill_dir / "skill.yml").write_text(yml, encoding="utf-8")
    if with_instructions:
        (skill_dir / "SKILL.md").write_text(f"# {name} instructions", encoding="utf-8")
    return skill_dir


def _make_skill_md_frontmatter(tmpdir: str, name: str, desc: str = "测试技能"):
    """Helper：创建 SKILL.md frontmatter 格式的技能目录。"""
    skill_dir = Path(tmpdir) / name
    skill_dir.mkdir()
    md = f"---\nname: {name}\ndescription: {desc}\nkeywords: [kw]\n---\n\n# {name} body"
    (skill_dir / "SKILL.md").write_text(md, encoding="utf-8")
    return skill_dir


def _make_skill_fallback(tmpdir: str, name: str):
    """Helper：创建仅 README.md 的兜底格式。"""
    skill_dir = Path(tmpdir) / name
    skill_dir.mkdir()
    (skill_dir / "README.md").write_text(f"# {name} readme", encoding="utf-8")
    return skill_dir


def test_discover_skill_yml():
    reg = SkillRegistry.get_instance()
    with tempfile.TemporaryDirectory() as d:
        _make_skill_yml(d, "ska", desc="技能A")
        n = reg.discover(d)
        assert n == 1
        meta = reg.list_meta()
        assert meta[0]["name"] == "ska"
        assert "技能A" in meta[0]["description"]


def test_discover_skill_md_frontmatter():
    reg = SkillRegistry.get_instance()
    with tempfile.TemporaryDirectory() as d:
        _make_skill_md_frontmatter(d, "skb", desc="技能B")
        n = reg.discover(d)
        assert n == 1
        meta = reg.list_meta()
        assert meta[0]["name"] == "skb"
        assert "技能B" in meta[0]["description"]


def test_discover_fallback_minimal():
    reg = SkillRegistry.get_instance()
    with tempfile.TemporaryDirectory() as d:
        _make_skill_fallback(d, "skc")
        n = reg.discover(d)
        assert n == 1
        meta = reg.list_meta()
        assert meta[0]["name"] == "skc"


def test_discover_mixed_formats():
    reg = SkillRegistry.get_instance()
    with tempfile.TemporaryDirectory() as d:
        _make_skill_yml(d, "ska")
        _make_skill_md_frontmatter(d, "skb")
        _make_skill_fallback(d, "skc")
        n = reg.discover(d)
        assert n == 3


def test_discover_empty_directory():
    reg = SkillRegistry.get_instance()
    with tempfile.TemporaryDirectory() as d:
        n = reg.discover(d)
        assert n == 0
        assert reg.list_meta() == []


def test_discover_no_directory():
    reg = SkillRegistry.get_instance()
    n = reg.discover("/tmp/__nimo_nonexistent_skills_dir__")
    assert n == 0


# ---------------------------------------------------------------------------
# activate / deactivate
# ---------------------------------------------------------------------------

def test_activate_and_deactivate():
    reg = SkillRegistry.get_instance()
    with tempfile.TemporaryDirectory() as d:
        _make_skill_yml(d, "ska", desc="技能A", with_instructions=True)
        reg.discover(d)

        summary = reg.activate("ska")
        assert "已激活" in summary
        assert "技能A" in summary
        assert reg.get_active_instructions() is not None

        reg.deactivate()
        assert reg.get_active_instructions() is None


def test_activate_nonexistent():
    reg = SkillRegistry.get_instance()
    with pytest.raises(ValueError, match="未找到技能"):
        reg.activate("nonexistent")


def test_deactivate_when_none_active():
    reg = SkillRegistry.get_instance()
    reg.deactivate()  # 不抛异常
    assert reg.get_active_instructions() is None


# ---------------------------------------------------------------------------
# run_script
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_run_script_success():
    reg = SkillRegistry.get_instance()
    with tempfile.TemporaryDirectory() as d:
        _make_skill_yml(d, "ska", with_scripts=True)
        reg.discover(d)

        result = await reg.run_script("ska", "scripts/hello.py", [])
        assert result.success is True
        assert result.data == "hello"


@pytest.mark.asyncio
async def test_run_script_not_in_whitelist():
    reg = SkillRegistry.get_instance()
    with tempfile.TemporaryDirectory() as d:
        _make_skill_yml(d, "ska")
        reg.discover(d)

        result = await reg.run_script("ska", "scripts/nonexistent.py", [])
        assert result.success is False
        assert "白名单" in result.error or "不在" in result.error


@pytest.mark.asyncio
async def test_run_script_path_traversal():
    reg = SkillRegistry.get_instance()
    with tempfile.TemporaryDirectory() as d:
        _make_skill_yml(d, "ska")
        reg.discover(d)

        result = await reg.run_script("ska", "../etc/passwd", [])
        assert result.success is False
        # 路径遍历被白名单检查先拦截，两种错误消息均为有效安全拒绝
        assert "路径遍历" in result.error or "白名单" in result.error or "不在" in result.error


@pytest.mark.asyncio
async def test_run_script_unknown_skill():
    reg = SkillRegistry.get_instance()
    result = await reg.run_script("nonexistent", "test.py", [])
    assert result.success is False
    assert "未找到技能" in result.error


@pytest.mark.asyncio
async def test_run_script_returns_stderr_on_failure():
    reg = SkillRegistry.get_instance()
    with tempfile.TemporaryDirectory() as d:
        skill_dir = Path(d) / "ska"
        skill_dir.mkdir()
        scripts_dir = skill_dir / "scripts"
        scripts_dir.mkdir()
        (scripts_dir / "fail.py").write_text("import sys; sys.exit(1)")
        (skill_dir / "skill.yml").write_text(
            "name: ska\nscripts:\n  - scripts/fail.py", encoding="utf-8"
        )
        reg.discover(d)

        result = await reg.run_script("ska", "scripts/fail.py", [])
        assert result.success is False


# ---------------------------------------------------------------------------
# Installer
# ---------------------------------------------------------------------------

def test_installer_list_empty():
    with tempfile.TemporaryDirectory() as d:
        inst = Installer(d)
        assert inst.list_installed() == []


def test_installer_list_and_uninstall():
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "my-skill").mkdir()
        inst = Installer(d)
        skills = inst.list_installed()
        assert len(skills) == 1
        assert skills[0][0] == "my-skill"

        msg = inst.uninstall("my-skill")
        assert "已卸载" in msg
        assert inst.list_installed() == []


def test_installer_uninstall_nonexistent():
    with tempfile.TemporaryDirectory() as d:
        inst = Installer(d)
        msg = inst.uninstall("nonexistent")
        assert "不存在" in msg


def test_installer_path_traversal():
    with tempfile.TemporaryDirectory() as d:
        inst = Installer(d)
        msg = inst.uninstall("../../../etc")
        assert "非法" in msg
