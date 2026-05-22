from typing import Any


class BaseRepository:
    def __init__(self, session: Any):
        self.session = session
