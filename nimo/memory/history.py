import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SUMMARY_PREFIX = "[历史摘要]"


class ConversationHistory:
    def __init__(self, max_rounds: int = 10, session_id: str = "default"):
        self._messages: list[dict] = []
        self._max_rounds = max_rounds
        self._user_indices: list[int] = []
        self._summary: str | None = None
        self._trimmed_buffer: list[dict] = []
        self._session_id = session_id

    def add(self, message: dict) -> None:
        if message["role"] == "user":
            self._user_indices.append(len(self._messages))
        self._messages.append(message)
        self._trim()

    def get_messages(self) -> list[dict]:
        result: list[dict] = []
        if self._summary:
            result.append({"role": "system", "content": f"{SUMMARY_PREFIX} {self._summary}"})
        result.extend(self._messages)
        return result

    def pop_trimmed(self) -> list[dict]:
        msgs = self._trimmed_buffer
        self._trimmed_buffer = []
        return msgs

    def set_summary(self, text: str | None) -> None:
        self._summary = text

    @property
    def summary(self) -> str | None:
        return self._summary

    @property
    def session_id(self) -> str:
        return self._session_id

    def _trim(self) -> None:
        if len(self._user_indices) <= self._max_rounds:
            return
        drop_count = len(self._user_indices) - self._max_rounds
        cut_index = self._user_indices[drop_count]
        self._trimmed_buffer.extend(self._messages[:cut_index])
        self._messages = self._messages[cut_index:]
        self._user_indices = [i - cut_index for i in self._user_indices[drop_count:]]

    def to_dict(self) -> dict:
        return {
            "messages": self._messages,
            "user_indices": self._user_indices,
            "summary": self._summary,
            "max_rounds": self._max_rounds,
        }

    @classmethod
    def from_dict(cls, data: dict, session_id: str = "default") -> "ConversationHistory":
        history = cls(
            max_rounds=data.get("max_rounds", 10),
            session_id=session_id,
        )
        history._messages = data.get("messages", [])
        history._user_indices = data.get("user_indices", [])
        history._summary = data.get("summary")
        return history

    def save(self, base_dir: str | Path | None = None) -> None:
        base = Path(base_dir) if base_dir else Path.home() / ".nimo" / "sessions"
        base.mkdir(parents=True, exist_ok=True)
        path = base / f"{self._session_id}.json"
        try:
            path.write_text(
                json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError as e:
            logger.warning("保存历史失败：%s", e)

    @classmethod
    def load(
        cls,
        session_id: str = "default",
        max_rounds: int = 10,
        base_dir: str | Path | None = None,
    ) -> "ConversationHistory":
        base = Path(base_dir) if base_dir else Path.home() / ".nimo" / "sessions"
        path = base / f"{session_id}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls.from_dict(data, session_id=session_id)
        except FileNotFoundError:
            logger.info("未找到历史文件 %s，使用空历史", path)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.warning("历史文件损坏，使用空历史：%s", e)
        return cls(max_rounds=max_rounds, session_id=session_id)

    def clear(self, base_dir: str | Path | None = None) -> None:
        self._messages.clear()
        self._user_indices.clear()
        self._summary = None
        self._trimmed_buffer.clear()
        base = Path(base_dir) if base_dir else Path.home() / ".nimo" / "sessions"
        path = base / f"{self._session_id}.json"
        try:
            path.unlink(missing_ok=True)
        except OSError as e:
            logger.warning("删除历史文件失败：%s", e)
