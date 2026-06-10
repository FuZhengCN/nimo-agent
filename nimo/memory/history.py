class ConversationHistory:
    def __init__(self, max_rounds: int = 10):
        self._messages: list[dict] = []
        self._max_rounds = max_rounds
        self._user_indices: list[int] = []

    def add(self, message: dict) -> None:
        if message["role"] == "user":
            self._user_indices.append(len(self._messages))
        self._messages.append(message)
        self._trim()

    def get_messages(self) -> list[dict]:
        return list(self._messages)

    def _trim(self) -> None:
        if len(self._user_indices) <= self._max_rounds:
            return
        drop_count = len(self._user_indices) - self._max_rounds
        cut_index = self._user_indices[drop_count]
        self._messages = self._messages[cut_index:]
        self._user_indices = [i - cut_index for i in self._user_indices[drop_count:]]
