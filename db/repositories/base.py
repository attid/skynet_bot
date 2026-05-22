from typing import Any, NoReturn


class BaseRepository:
    def __init__(self, session: Any):
        self.session = session

    def _raise_sync_removed(self, method_name: str) -> NoReturn:
        raise RuntimeError(f"{type(self).__name__}.{method_name} is sync DB access; use the async repository method")
