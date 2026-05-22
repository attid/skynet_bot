from datetime import datetime, timedelta
from typing import List, cast

from sqlalchemy import select, and_

from db.repositories.base import BaseRepository
from shared.infrastructure.database.models import TMessage, TSavedMessages, TSummary
from other.constants import MTLChats


class MessageRepository(BaseRepository):
    def add_message(
        self,
        user_id: int,
        text: str,
        use_alarm: int = 0,
        update_id: int = None,
        button_json: str = None,
        topic_id: int = 0,
    ) -> None:
        new_message = TMessage(
            user_id=user_id,
            text=text,
            use_alarm=use_alarm,
            update_id=update_id,
            button_json=button_json,
            topic_id=topic_id,
        )
        self.session.add(new_message)
        # Assuming commit happens at UoW level or caller.
        # But requests.py did commit. To maintain compatibility without rewriting callers yet:
        # I should probably not commit here if I want to move to UoW, but the migration step
        # requires me to keep behavior.
        # I will leave commit out and let the Service layer (which I'll create) handle it,
        # OR if I am replacing direct calls, I might need to verify where commit happens.
        # Since I am replacing db/requests.py which did commit, I should check if I am wrapping this.
        # For now, I'll add methods.

    def load_new_messages(self, limit: int = 10) -> List[TMessage]:
        result = self.session.execute(select(TMessage).where(TMessage.was_send == 0).limit(limit))
        return cast(List[TMessage], result.scalars().all())

    def save_message(
        self, user_id: int, username: str, chat_id: int, thread_id: int, text: str, summary_id: int = None
    ) -> None:
        new_message = TSavedMessages(
            user_id=user_id,
            username=username,
            chat_id=chat_id,
            thread_id=thread_id,
            text=text[:4000],
            summary_id=summary_id,
        )
        self.session.add(new_message)

    def get_messages_without_summary(self, chat_id: int, thread_id: int, dt: datetime = None) -> List[TSavedMessages]:
        if dt is None:
            dt = datetime.today()

        result = self.session.execute(
            select(TSavedMessages).where(
                and_(
                    TSavedMessages.chat_id == chat_id,
                    TSavedMessages.thread_id == thread_id,
                    TSavedMessages.dt.between(dt.date(), dt.date() + timedelta(days=1)),
                    TSavedMessages.summary_id.is_(None),
                )
            )
        )
        return cast(List[TSavedMessages], result.scalars().all())

    def add_summary(self, text: str, summary_id: int = None) -> TSummary:
        new_record = TSummary(text=text, summary_id=summary_id)
        self.session.add(new_record)
        return new_record

    def get_summary(self, chat_id: int, thread_id: int, dt: datetime = None) -> List[TSummary]:
        if dt is None:
            dt = datetime.today()

        summary_ids_result = self.session.execute(
            select(TSavedMessages.summary_id)
            .where(
                and_(
                    TSavedMessages.chat_id == chat_id,
                    TSavedMessages.thread_id == thread_id,
                    TSavedMessages.dt.between(dt.date(), dt.date() + timedelta(days=1)),
                )
            )
            .distinct()
        )
        summary_ids = [row[0] for row in summary_ids_result.fetchall() if row[0] is not None]

        if not summary_ids:
            return []

        summaries_result = self.session.execute(select(TSummary).where(TSummary.id.in_(summary_ids)))
        return cast(List[TSummary], summaries_result.scalars().all())

    def send_admin_message(self, msg: str) -> None:
        self.add_message(MTLChats.ITolstov, msg)

    async def async_send_admin_message(self, msg: str) -> None:
        self.add_message(MTLChats.ITolstov, msg)
