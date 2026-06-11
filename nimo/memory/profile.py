import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

PROFILE_PREFIX = "[用户信息]"


class UserProfile:
    def __init__(self):
        self._facts: dict[str, str] = {}

    def update(self, facts: dict[str, str]) -> None:
        for key, value in facts.items():
            if value:
                self._facts[key] = value
            else:
                self._facts.pop(key, None)

    def to_context(self) -> str | None:
        if not self._facts:
            return None
        parts = "；".join(f"{k}：{v}" for k, v in self._facts.items())
        return f"{PROFILE_PREFIX} {parts}"

    @property
    def facts(self) -> dict[str, str]:
        return dict(self._facts)

    @property
    def is_empty(self) -> bool:
        return len(self._facts) == 0

    def save(self, base_dir: str | Path | None = None) -> None:
        base = Path(base_dir) if base_dir else Path.home() / ".nimo"
        base.mkdir(parents=True, exist_ok=True)
        path = base / "profile.json"
        try:
            path.write_text(
                json.dumps(self._facts, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.warning("保存用户档案失败：%s", e)

    @classmethod
    def load(cls, base_dir: str | Path | None = None) -> "UserProfile":
        base = Path(base_dir) if base_dir else Path.home() / ".nimo"
        path = base / "profile.json"
        profile = cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                profile._facts = {str(k): str(v) for k, v in data.items() if v}
        except FileNotFoundError:
            logger.info("未找到用户档案文件 %s", path)
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("用户档案文件损坏，使用空档案：%s", e)
        return profile

    def clear(self, base_dir: str | Path | None = None) -> None:
        self._facts.clear()
        base = Path(base_dir) if base_dir else Path.home() / ".nimo"
        path = base / "profile.json"
        try:
            path.unlink(missing_ok=True)
        except OSError as e:
            logger.warning("删除用户档案文件失败：%s", e)
