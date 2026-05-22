import json
from enum import Enum
from typing import Any, Dict, List, Union

from sqlalchemy import select, delete, and_

from db.repositories.base import BaseRepository
from shared.infrastructure.database.models import BotConfig, KVStore


class ConfigRepository(BaseRepository):
    @staticmethod
    def _normalize_chat_key(chat_key: Union[int, Enum, str]) -> tuple[Union[int, str], str | None]:
        if isinstance(chat_key, int):
            return chat_key, None
        if isinstance(chat_key, Enum):
            return chat_key.value, chat_key.name
        return chat_key, None

    def save_bot_value(self, chat_id: int, chat_key: Union[int, Enum, str], chat_value: Any) -> None:
        self._raise_sync_removed("save_bot_value")

    async def async_save_bot_value(self, chat_id: int, chat_key: Union[int, Enum, str], chat_value: Any) -> None:
        chat_key_value, chat_key_name = self._normalize_chat_key(chat_key)

        if chat_value is None:
            stmt = delete(BotConfig).where(and_(BotConfig.chat_id == chat_id, BotConfig.chat_key == chat_key_value))
            await self.session.execute(stmt)
        else:
            prepared_value = self._prepare_chat_value(chat_value)

            existing_record = (
                await self.session.execute(
                    select(BotConfig).where(and_(BotConfig.chat_id == chat_id, BotConfig.chat_key == chat_key_value))
                )
            ).scalar_one_or_none()

            if existing_record:
                existing_record.chat_key_name = chat_key_name
                existing_record.chat_value = prepared_value
            else:
                new_record = BotConfig(
                    chat_id=chat_id, chat_key=chat_key_value, chat_key_name=chat_key_name, chat_value=prepared_value
                )
                self.session.add(new_record)

    def load_bot_value(self, chat_id: int, chat_key: Union[int, Enum, str], default_value: Any = "") -> Any:
        self._raise_sync_removed("load_bot_value")

    async def async_load_bot_value(self, chat_id: int, chat_key: Union[int, Enum, str], default_value: Any = "") -> Any:
        chat_key_value, _ = self._normalize_chat_key(chat_key)

        record = (
            await self.session.execute(
                select(BotConfig).where(and_(BotConfig.chat_id == chat_id, BotConfig.chat_key == chat_key_value))
            )
        ).scalar_one_or_none()

        return self._unpack_bot_value(record, default_value)

    def _unpack_bot_value(self, record: Any, default_value: Any = "") -> Any:
        if record and record.chat_value is not None:
            # logic from mongo.py to handle different formats (json string vs dict vs wrapper dict)
            val = record.chat_value
            if isinstance(val, dict) and "value" in val and len(val) == 1:
                return val["value"]

            if isinstance(val, (dict, list)):
                try:
                    return json.dumps(val)
                except TypeError:
                    return str(val)

            if isinstance(val, str):
                stripped = val.strip()
                if stripped and stripped[0] in '{"[' or stripped.startswith('"'):
                    try:
                        parsed = json.loads(val)
                        if isinstance(parsed, (dict, list)):
                            return json.dumps(parsed)
                        if isinstance(parsed, str):
                            return parsed
                    except json.JSONDecodeError:
                        pass
            return val

        return default_value

    def get_chat_ids_by_key(self, chat_key: Union[int, Enum, str]) -> List[int]:
        self._raise_sync_removed("get_chat_ids_by_key")

    async def async_get_chat_ids_by_key(self, chat_key: Union[int, Enum, str]) -> List[int]:
        chat_key_value, _ = self._normalize_chat_key(chat_key)

        result = await self.session.execute(select(BotConfig.chat_id).where(BotConfig.chat_key == chat_key_value))
        return [row[0] for row in result.fetchall()]

    def get_chat_dict_by_key(self, chat_key: Union[int, Enum, str], return_json: bool = False) -> Dict[int, Any]:
        self._raise_sync_removed("get_chat_dict_by_key")

    async def async_get_chat_dict_by_key(
        self, chat_key: Union[int, Enum, str], return_json: bool = False
    ) -> Dict[int, Any]:
        chat_key_value, _ = self._normalize_chat_key(chat_key)

        records = (
            (await self.session.execute(select(BotConfig).where(BotConfig.chat_key == chat_key_value))).scalars().all()
        )

        return self._records_to_chat_dict(records, return_json)

    def _records_to_chat_dict(self, records: Any, return_json: bool = False) -> Dict[int, Any]:
        result_dict = {}
        for record in records:
            if record.chat_value is not None:
                if return_json and isinstance(record.chat_value, str):
                    try:
                        result_dict[record.chat_id] = json.loads(record.chat_value)
                    except json.JSONDecodeError:
                        result_dict[record.chat_id] = record.chat_value
                else:
                    if (
                        isinstance(record.chat_value, dict)
                        and "value" in record.chat_value
                        and len(record.chat_value) == 1
                    ):
                        result_dict[record.chat_id] = record.chat_value["value"]
                    else:
                        result_dict[record.chat_id] = record.chat_value
        return result_dict

    def update_dict_value(self, chat_id: int, chat_key: Union[int, Enum, str], dict_key: str, dict_value: Any) -> None:
        self._raise_sync_removed("update_dict_value")

    async def async_update_dict_value(
        self, chat_id: int, chat_key: Union[int, Enum, str], dict_key: str, dict_value: Any
    ) -> None:
        chat_key_value, _ = self._normalize_chat_key(chat_key)

        record = (
            await self.session.execute(
                select(BotConfig).where(and_(BotConfig.chat_id == chat_id, BotConfig.chat_key == chat_key_value))
            )
        ).scalar_one_or_none()

        self._apply_dict_value(record, chat_id, chat_key_value, dict_key, dict_value)

    def _apply_dict_value(
        self, record: Any, chat_id: int, chat_key_value: Union[int, str], dict_key: str, dict_value: Any
    ) -> None:
        if record:
            if record.chat_value is None:
                record.chat_value = {}
            elif isinstance(record.chat_value, str):
                try:
                    record.chat_value = json.loads(record.chat_value)
                except json.JSONDecodeError:
                    record.chat_value = {"value": record.chat_value}
            elif isinstance(record.chat_value, dict) and "value" in record.chat_value and len(record.chat_value) == 1:
                # If it's a simple dict wrapper, reset to empty dict to start filling keys
                # This logic mirrors mongo.py but it's a bit aggressive if we want to keep "value"
                # but mongo.py did: record.chat_value = {}
                record.chat_value = {}

            # Ensure it's a dict before assignment (JSONB field in model comes as dict/list/str/int/bool in python)
            if not isinstance(record.chat_value, dict):
                record.chat_value = {"original_value": record.chat_value}

            # We need to re-assign or mutate. For JSONB mutation tracking in SA, it's safer to re-assign or use flag_modified
            # But usually assigning to a key works if it's a mutable dict in session identity map.
            # However, for JSONB updates to persist, sometimes a copy is needed or flag_modified.
            # Let's clone it to be safe.
            new_val = dict(record.chat_value)
            new_val[dict_key] = dict_value
            record.chat_value = new_val
        else:
            new_record = BotConfig(chat_id=chat_id, chat_key=chat_key_value, chat_value={dict_key: dict_value})
            self.session.add(new_record)

    def get_dict_value(
        self, chat_id: int, chat_key: Union[int, Enum, str], dict_key: str, default_value: Any = None
    ) -> Any:
        self._raise_sync_removed("get_dict_value")

    async def async_get_dict_value(
        self, chat_id: int, chat_key: Union[int, Enum, str], dict_key: str, default_value: Any = None
    ) -> Any:
        chat_key_value, _ = self._normalize_chat_key(chat_key)

        record = (
            await self.session.execute(
                select(BotConfig).where(and_(BotConfig.chat_id == chat_id, BotConfig.chat_key == chat_key_value))
            )
        ).scalar_one_or_none()

        return self._unpack_dict_value(record, dict_key, default_value)

    def _unpack_dict_value(self, record: Any, dict_key: str, default_value: Any = None) -> Any:
        if record and record.chat_value is not None:
            chat_data = record.chat_value
            if isinstance(chat_data, str):
                try:
                    chat_data = json.loads(chat_data)
                except json.JSONDecodeError:
                    chat_data = {"value": chat_data}

            if isinstance(chat_data, dict):
                # mongo.py logic: if one key "value" and we ask for something else, return default
                if "value" in chat_data and len(chat_data) == 1 and dict_key != "value":
                    return default_value
                return chat_data.get(dict_key, default_value)

        return default_value

    def save_kv_value(self, kv_key: str, kv_value: Any) -> None:
        self._raise_sync_removed("save_kv_value")

    async def async_save_kv_value(self, kv_key: str, kv_value: Any) -> None:
        record = (await self.session.execute(select(KVStore).where(KVStore.kv_key == kv_key))).scalar_one_or_none()

        self._apply_kv_value(record, kv_key, kv_value)

    def _apply_kv_value(self, record: Any, kv_key: str, kv_value: Any) -> None:
        if record:
            record.kv_value = kv_value
        else:
            new_record = KVStore(kv_key=kv_key, kv_value=kv_value)
            self.session.add(new_record)

    def load_kv_value(self, kv_key: str, default_value: Any = None) -> Any:
        self._raise_sync_removed("load_kv_value")

    async def async_load_kv_value(self, kv_key: str, default_value: Any = None) -> Any:
        record = (await self.session.execute(select(KVStore).where(KVStore.kv_key == kv_key))).scalar_one_or_none()
        return record.kv_value if record else default_value

    # Legacy BotTable support
    def save_legacy_bot_value(self, chat_id: int, chat_key: Union[int, Enum, str], chat_value: Any) -> None:
        self._raise_sync_removed("save_legacy_bot_value")

    def load_legacy_bot_value(self, chat_id: int, chat_key: Union[int, Enum, str], default_value: Any = "") -> Any:
        self._raise_sync_removed("load_legacy_bot_value")

    def _prepare_chat_value(self, value: Any) -> Any:
        if value is None:
            return None

        if isinstance(value, str):
            stripped = value.strip()
            if stripped and stripped[0] in '{"[' or stripped.startswith('"'):
                try:
                    parsed = json.loads(value)
                    # Double parse check from original code
                    if isinstance(parsed, str):
                        inner_stripped = parsed.strip()
                        if inner_stripped and inner_stripped[0] in '{"[' or inner_stripped.startswith('"'):
                            try:
                                parsed = json.loads(parsed)
                            except json.JSONDecodeError:
                                pass

                    if (
                        isinstance(parsed, dict)
                        and set(parsed.keys()) == {"value"}
                        and isinstance(parsed["value"], str)
                    ):
                        try:
                            parsed = json.loads(parsed["value"])
                        except json.JSONDecodeError:
                            pass
                    return parsed
                except json.JSONDecodeError:
                    pass
            return value
        return value
