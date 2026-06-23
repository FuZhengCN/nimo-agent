"""技能安装器：git clone、卸载、列表。"""
import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class Installer:
    def __init__(self, skills_dir: str):
        self._skills_dir = Path(skills_dir)

    def install(self, url: str) -> str:
        self._skills_dir.mkdir(parents=True, exist_ok=True)
        name = url.rstrip("/").split("/")[-1]
        if name.endswith(".git"):
            name = name[:-4]
        target = self._skills_dir / name
        if target.exists():
            return f"技能目录已存在：{target}\n如需重装请先 skill uninstall {name}"

        try:
            result = subprocess.run(
                ["git", "clone", url, str(target)],
                capture_output=True, text=True, timeout=300,
            )
        except subprocess.TimeoutExpired:
            return "git clone 超时（300s），请检查网络或仓库地址"
        if result.returncode != 0:
            return f"git clone 失败：{result.stderr.strip() or result.stdout.strip()}"

        req_path = target / "requirements.txt"
        if req_path.is_file():
            return (
                f"已安装 {name} 到 {target}\n"
                f"检测到 requirements.txt，请手动运行：pip install -r {req_path}"
            )
        return f"已安装 {name} 到 {target}"

    def uninstall(self, name: str) -> str:
        target = (self._skills_dir / name).resolve()
        skills_root = self._skills_dir.resolve()
        if not str(target).startswith(str(skills_root) + os.sep):
            return f"非法的技能名称：{name}"
        if not target.exists():
            return f"技能目录不存在：{target}"
        try:
            shutil.rmtree(target)
        except OSError as e:
            return f"卸载失败：{e}"
        return f"已卸载 {name}"

    def list_installed(self) -> list[tuple[str, str]]:
        if not self._skills_dir.is_dir():
            return []
        result = []
        for entry in sorted(self._skills_dir.iterdir()):
            if entry.is_dir():
                result.append((entry.name, str(entry)))
        return result
