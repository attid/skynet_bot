import json
import pytest
import asyncio
import datetime
from contextlib import asynccontextmanager, suppress
from aiogram import types

import routers.polls as polls_module
from routers.polls import router as polls_router, PollCallbackData, chat_to_address
from tests.conftest import RouterTestMiddleware
from other.constants import MTLChats
from other.stellar import MTLAddresses

CHANNEL_ID = -1001649743884
POLL_MESSAGE_ID = 10
NOT_FOUND_NAME = "GABC..WXYZ не найден, возможно скам"


def _reaction_emojis(requests):
    """Extract emoji reactions from recorded mock Telegram requests."""
    emojis = []
    for request in requests:
        if request["method"] != "setMessageReaction":
            continue
        reaction = request["data"].get("reaction")
        if isinstance(reaction, str):
            with suppress(Exception):
                reaction = json.loads(reaction)
        if isinstance(reaction, list):
            emojis.extend(item.get("emoji") for item in reaction if isinstance(item, dict))
    return emojis


def _chat_message_bodies(requests, chat_id, method="sendMessage"):
    """Return data payloads of requests addressed to a chat."""
    return [r["data"] for r in requests if r["method"] == method and str(r["data"].get("chat_id")) == str(chat_id)]


def _channel_poll_update(update_id: int, message_id: int = 50, question: str = "Channel Q?") -> types.Update:
    return types.Update(
        update_id=update_id,
        channel_post=types.Message(
            message_id=message_id,
            date=datetime.datetime.now(),
            chat=types.Chat(id=CHANNEL_ID, type="channel"),
            sender_chat=types.Chat(id=CHANNEL_ID, type="channel"),
            poll=types.Poll(
                id="p_channel",
                question=question,
                options=[types.PollOption(persistent_id="pid_A", text="A", voter_count=0)],
                total_voter_count=0,
                is_closed=False,
                is_anonymous=True,
                type="regular",
                allows_multiple_answers=False,
                allows_revoting=False,
                members_only=False,
            ),
        ),
    )


def _recount_update(
    update_id: int,
    *,
    username: str = "admin",
    poll_message_id: int = POLL_MESSAGE_ID,
    forwarded: bool = True,
    text: str = "/poll_recount",
) -> types.Update:
    reply_kwargs = {}
    if forwarded:
        reply_kwargs["forward_origin"] = types.MessageOriginChannel(
            type="channel",
            date=datetime.datetime.now(),
            chat=types.Chat(id=CHANNEL_ID, type="channel"),
            message_id=poll_message_id,
        )
    reply_message_id = 20 if forwarded else (poll_message_id + 100)
    return types.Update(
        update_id=update_id,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.ITolstov, type="private"),
            from_user=types.User(id=84131737, is_bot=False, first_name="Admin", username=username),
            text=text,
            reply_to_message=types.Message(
                message_id=reply_message_id,
                date=datetime.datetime.now(),
                chat=types.Chat(id=MTLChats.ITolstov, type="private"),
                **reply_kwargs,
            ),
        ),
    )


@pytest.fixture(autouse=True)
async def cleanup_router():
    yield
    if polls_router.parent_router:
        polls_router._parent_router = None
    # Recount lock and stored polls are module-level state: never leak them across event loops.
    polls_module._recount_lock = None
    polls_module._recount_lock_loop = None


@pytest.fixture(autouse=True)
def fake_async_session_pool(monkeypatch, router_app_context):
    """Votes are saved in an owned session; tests must never touch a real database."""

    @asynccontextmanager
    async def _session_pool():
        yield router_app_context.session

    monkeypatch.setattr("db.session.AsyncSessionPool", _session_pool)


@pytest.mark.asyncio
async def test_poll_command(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    poll_msg = types.Message(
        message_id=1,
        date=datetime.datetime.now(),
        chat=types.Chat(id=MTLChats.TestGroup, type="supergroup"),
        from_user=types.User(id=999, is_bot=False, first_name="Admin"),
        poll=types.Poll(
            id="p1",
            question="Q?",
            options=[types.PollOption(persistent_id="pid_A", text="A", voter_count=0)],
            total_voter_count=0,
            is_closed=False,
            is_anonymous=True,
            type="regular",
            allows_multiple_answers=False,
            allows_revoting=False,
            members_only=False,
        ),
    )

    update = types.Update(
        update_id=1,
        message=types.Message(
            message_id=2,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.TestGroup, type="supergroup"),
            from_user=types.User(id=999, is_bot=False, first_name="Admin"),
            text="/poll",
            reply_to_message=poll_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    # Verify poll service called
    assert router_app_context.poll_service.save_poll.called

    requests = mock_telegram.get_requests()
    assert any("Q?" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")


@pytest.mark.asyncio
async def test_poll_callback(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.callback_query.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    # Setup poll data
    my_poll = {"question": "Q?", "closed": False, "message_id": 10, "buttons": [["A", 0, []]]}
    router_app_context.poll_service._polls[(MTLChats.TestGroup, 10)] = my_poll

    # Setup votes weight using voting_service (DI replacement for global_data.votes)
    # We must match the chat_to_address key for the test chat
    # MTLChats.TestGroup is in chat_to_address
    test_address = chat_to_address.get(MTLChats.TestGroup, MTLAddresses.public_issuer)

    router_app_context.voting_service.set_vote_weights(
        test_address, {"@user": 5, "NEED": {"50": 10, "75": 15, "100": 20}}
    )

    cb_data = PollCallbackData(answer=0).pack()

    update = types.Update(
        update_id=2,
        callback_query=types.CallbackQuery(
            id="cb1",
            chat_instance="ci1",
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            message=types.Message(
                message_id=10,
                date=datetime.datetime.now(),
                chat=types.Chat(id=MTLChats.TestGroup, type="supergroup"),
                text="Poll Body",
            ),
            data=cb_data,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    # Verify text update
    requests = mock_telegram.get_requests()
    assert any(r["method"] == "editMessageText" for r in requests)
    assert any("(5)" in r["data"]["text"] for r in requests if r["method"] == "editMessageText")

    # Verify save
    assert router_app_context.poll_service.save_poll.called


@pytest.mark.asyncio
async def test_apoll_command(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.gspread_service.copy_a_table.return_value = ("http://sheet", "gid123")
    router_app_context.stellar_service.get_mtlap_votes.return_value = {}

    poll_msg = types.Message(
        message_id=1,
        date=datetime.datetime.now(),
        chat=types.Chat(id=MTLChats.TestGroup, type="supergroup"),
        from_user=types.User(id=999, is_bot=False, first_name="Admin"),
        poll=types.Poll(
            id="p1",
            question="Q?",
            options=[types.PollOption(persistent_id="pid_A", text="A", voter_count=0)],
            total_voter_count=0,
            is_closed=False,
            is_anonymous=True,
            type="regular",
            allows_multiple_answers=False,
            allows_revoting=False,
            members_only=False,
        ),
    )

    update = types.Update(
        update_id=3,
        message=types.Message(
            message_id=2,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.TestGroup, type="supergroup"),
            from_user=types.User(id=999, is_bot=False, first_name="Admin"),
            text="/apoll",
            reply_to_message=poll_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.gspread_service.copy_a_table.called
    assert router_app_context.poll_service.save_mtla_poll.called

    requests = mock_telegram.get_requests()
    assert any(r["method"] == "sendPoll" for r in requests)


@pytest.mark.asyncio
async def test_poll_answer(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.poll_answer.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.poll_service.load_mtla_poll.return_value = {
        "google_id": "gid123",
        "google_url": "http://sheet",
        "info_chat_id": 123,
        "info_message_id": 456,
    }
    router_app_context.grist_service.load_table_data.return_value = [{"Stellar": "GADDR"}]
    router_app_context.gspread_service.update_a_table_vote.return_value = [["Opt1", "10"]]

    update = types.Update(
        update_id=4,
        poll_answer=types.PollAnswer(
            poll_id="p1",
            user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            option_ids=[0],
            option_persistent_ids=["pid_Opt1"],
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert router_app_context.gspread_service.update_a_table_vote.called

    requests = mock_telegram.get_requests()
    assert any(r["method"] == "editMessageText" for r in requests)


@pytest.mark.asyncio
async def test_channel_post_creates_poll(mock_telegram, router_app_context):
    """Test automatic poll handling in specific channels."""
    dp = router_app_context.dispatcher
    dp.channel_post.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    # One of the channels in routers/polls.py: -1002210483308
    channel_id = -1002210483308

    poll = types.Poll(
        id="poll123",
        question="Channel Question",
        options=[types.PollOption(persistent_id="pid_Opt1", text="Opt1", voter_count=0)],
        total_voter_count=0,
        is_closed=False,
        is_anonymous=False,
        type="regular",
        allows_multiple_answers=False,
        allows_revoting=False,
        members_only=False,
    )

    update = types.Update(
        update_id=5,
        channel_post=types.Message(
            message_id=5,
            date=datetime.datetime.now(),
            chat=types.Chat(id=channel_id, type="channel", title="Channel"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            poll=poll,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "Channel Question" in req["data"]["text"]

    assert router_app_context.poll_service.save_poll.called


@pytest.mark.asyncio
async def test_poll_replace_text(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    my_poll = {"question": "Old", "closed": False, "message_id": 11, "buttons": [["A", 0, []]]}
    router_app_context.poll_service._polls[(MTLChats.TestGroup, 11)] = my_poll

    poll_msg = types.Message(
        message_id=11,
        date=datetime.datetime.now(),
        chat=types.Chat(id=MTLChats.TestGroup, type="supergroup"),
        text="Old Poll",
    )

    update = types.Update(
        update_id=6,
        message=types.Message(
            message_id=12,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.TestGroup, type="supergroup"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/poll_replace_text New Question",
            reply_to_message=poll_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    # Check if save_poll was called with updated question
    # save_poll signature: (session, chat_id, message_id, poll_data)
    args = router_app_context.poll_service.save_poll.call_args
    assert args is not None
    assert args[0][3]["question"] == "New Question"


@pytest.mark.asyncio
async def test_poll_close(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    my_poll = {"question": "Q", "closed": False, "message_id": 12, "buttons": []}
    router_app_context.poll_service._polls[(MTLChats.TestGroup, 12)] = my_poll

    poll_msg = types.Message(
        message_id=12,
        date=datetime.datetime.now(),
        chat=types.Chat(id=MTLChats.TestGroup, type="supergroup"),
        text="Poll",
    )

    update = types.Update(
        update_id=7,
        message=types.Message(
            message_id=13,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.TestGroup, type="supergroup"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/poll_close",
            reply_to_message=poll_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    # Check if save_poll was called with closed=True
    # save_poll signature: (session, chat_id, message_id, poll_data)
    args = router_app_context.poll_service.save_poll.call_args
    assert args is not None
    assert args[0][3]["closed"] is True


@pytest.mark.asyncio
async def test_poll_check_remaining_voters(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    chat_id = MTLChats.TestGroup
    test_address = chat_to_address.get(chat_id, "G_TEST")

    # Setup votes weight using voting_service (DI replacement for global_data.votes)
    router_app_context.voting_service.set_vote_weights(
        test_address, {"@user1": 10, "@user2": 5, "NEED": {"50": 5, "75": 8, "100": 10}}
    )

    # User 1 has voted
    my_poll = {"question": "Q?", "closed": False, "message_id": 99, "buttons": [["Opt1", 10, ["@user1"]]]}
    router_app_context.poll_service._polls[(chat_id, 99)] = my_poll

    poll_msg = types.Message(
        message_id=99, date=datetime.datetime.now(), chat=types.Chat(id=chat_id, type="supergroup"), text="Poll Msg"
    )

    update = types.Update(
        update_id=8,
        message=types.Message(
            message_id=100,
            date=datetime.datetime.now(),
            chat=types.Chat(id=chat_id, type="supergroup"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/poll_check",
            reply_to_message=poll_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    # User 2 should be listed as not voted
    assert "@user2" in req["data"]["text"]
    assert "Смотрите голосование" in req["data"]["text"]


@pytest.mark.asyncio
async def test_poll_reload_vote_admin(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    # Mock stellar service
    router_app_context.stellar_service.get_balances.return_value = ({}, [{"key": "G1", "weight": 1}])
    router_app_context.stellar_service.address_id_to_username.return_value = "@user"

    update = types.Update(
        update_id=9,
        message=types.Message(
            message_id=101,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup"),
            from_user=types.User(id=999, is_bot=False, first_name="Admin", username="admin"),
            text="/poll_reload_vote",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    # Should reply "reload complete"
    assert any("reload complete" in r["data"]["text"] for r in requests if r["method"] == "sendMessage")

    # Verify voting_service was updated (save is done via ConfigRepository directly)
    # The cmd_save_votes function updates voting_service.set_all_vote_weights
    all_weights = router_app_context.voting_service.get_all_vote_weights()
    assert len(all_weights) > 0


@pytest.mark.asyncio
async def test_apoll_check_reply(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    my_poll = {"google_id": "gid"}
    router_app_context.poll_service.load_mtla_poll.return_value = my_poll
    router_app_context.gspread_service.check_vote_table.return_value = (["ok"], ["d1"], set())

    poll = types.Poll(
        id="321",
        question="Assoc Poll",
        options=[types.PollOption(persistent_id="pid_Yes", text="Yes", voter_count=0)],
        total_voter_count=0,
        is_closed=False,
        is_anonymous=False,
        type="regular",
        allows_multiple_answers=False,
        allows_revoting=False,
        members_only=False,
    )

    update = types.Update(
        update_id=11,
        message=types.Message(
            message_id=17,
            date=datetime.datetime.now(),
            chat=types.Chat(id=123, type="supergroup", title="Group"),
            from_user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            text="/apoll_check",
            reply_to_message=types.Message(
                message_id=16,
                date=datetime.datetime.now(),
                chat=types.Chat(id=123, type="supergroup", title="Group"),
                poll=poll,
            ),
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "delegates" in req["data"]["text"]


@pytest.mark.asyncio
async def test_poll_answer_user_not_found(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.poll_answer.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.poll_service.load_mtla_poll.return_value = {
        "info_chat_id": 123,
        "info_message_id": 77,
        "google_id": "gid",
    }
    # Return empty list -> not found
    router_app_context.grist_service.load_table_data.return_value = []

    update = types.Update(
        update_id=12,
        poll_answer=types.PollAnswer(
            poll_id="p1",
            user=types.User(id=999, is_bot=False, first_name="User", username="user"),
            option_ids=[0],
            option_persistent_ids=["pid_Opt1"],
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    req = next((r for r in requests if r["method"] == "sendMessage"), None)
    assert req is not None
    assert "not found" in req["data"]["text"]


# --- Auto recount on poll creation -------------------------------------------------


@pytest.mark.asyncio
async def test_channel_post_recounts_weights_before_poll(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.channel_post.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.stellar_service.get_balances.return_value = ({}, [{"key": "G1", "weight": 3}])
    router_app_context.stellar_service.address_id_to_username.return_value = "@user"

    await dp.feed_update(bot=router_app_context.bot, update=_channel_poll_update(20))

    requests = mock_telegram.get_requests()
    emojis = _reaction_emojis(requests)
    assert emojis[:1] == ["👀"]
    assert "👌" in emojis
    assert emojis.index("👀") < emojis.index("👌")
    assert router_app_context.stellar_service.get_balances.called
    weights = router_app_context.voting_service.get_all_vote_weights()
    assert weights[chat_to_address[CHANNEL_ID]]["@user"] == 3
    assert any("Channel Q?" in body.get("text", "") for body in _chat_message_bodies(requests, CHANNEL_ID))


@pytest.mark.asyncio
async def test_channel_post_unresolved_names_go_to_admin_only(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.channel_post.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.stellar_service.get_balances.return_value = ({}, [{"key": "G1", "weight": 3}])
    router_app_context.stellar_service.address_id_to_username.return_value = NOT_FOUND_NAME

    await dp.feed_update(bot=router_app_context.bot, update=_channel_poll_update(21))

    requests = mock_telegram.get_requests()
    admin_bodies = _chat_message_bodies(requests, MTLChats.ITolstov)
    assert any("GABC..WXYZ" in body.get("text", "") for body in admin_bodies)
    channel_bodies = _chat_message_bodies(requests, CHANNEL_ID)
    assert channel_bodies
    assert all("не найден" not in body.get("text", "") for body in channel_bodies)


@pytest.mark.asyncio
async def test_channel_post_creates_poll_when_recount_fails(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.channel_post.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.stellar_service.get_balances.side_effect = RuntimeError("horizon down")

    await dp.feed_update(bot=router_app_context.bot, update=_channel_poll_update(22))

    requests = mock_telegram.get_requests()
    assert "⚠️" in _reaction_emojis(requests)
    assert any("Channel Q?" in body.get("text", "") for body in _chat_message_bodies(requests, CHANNEL_ID))
    assert router_app_context.poll_service.save_poll.called
    assert not router_app_context.voting_service.get_all_vote_weights()


@pytest.mark.asyncio
async def test_poll_command_recounts_weights(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.stellar_service.get_balances.return_value = ({}, [{"key": "G1", "weight": 4}])
    router_app_context.stellar_service.address_id_to_username.return_value = "@user"

    poll_msg = types.Message(
        message_id=1,
        date=datetime.datetime.now(),
        chat=types.Chat(id=MTLChats.TestGroup, type="supergroup"),
        from_user=types.User(id=999, is_bot=False, first_name="Admin"),
        poll=types.Poll(
            id="p1",
            question="Q?",
            options=[types.PollOption(persistent_id="pid_A", text="A", voter_count=0)],
            total_voter_count=0,
            is_closed=False,
            is_anonymous=True,
            type="regular",
            allows_multiple_answers=False,
            allows_revoting=False,
            members_only=False,
        ),
    )
    update = types.Update(
        update_id=23,
        message=types.Message(
            message_id=2,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.TestGroup, type="supergroup"),
            from_user=types.User(id=999, is_bot=False, first_name="Admin"),
            text="/poll",
            reply_to_message=poll_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    emojis = _reaction_emojis(mock_telegram.get_requests())
    assert emojis[:1] == ["👀"]
    assert "👌" in emojis
    assert router_app_context.stellar_service.get_balances.called
    weights = router_app_context.voting_service.get_all_vote_weights()
    assert weights[chat_to_address[MTLChats.TestGroup]]["@user"] == 4


# --- /poll_recount -----------------------------------------------------------------


def _seed_poll(router_app_context, chat_id=CHANNEL_ID, message_id=POLL_MESSAGE_ID, closed=False):
    my_poll = {
        "question": "Q?",
        "closed": closed,
        "message_id": message_id,
        "buttons": [["A", 10, ["@user"]], ["B", 4, ["@user2"]]],
    }
    router_app_context.poll_service._polls[(chat_id, message_id)] = my_poll
    return my_poll


def _seed_weights(router_app_context, chat_id=CHANNEL_ID):
    address = chat_to_address[chat_id]
    router_app_context.voting_service.set_vote_weights(
        address, {"@user": 5, "@user2": 3, "NEED": {"50": 5, "75": 7, "100": 8}}
    )


@pytest.mark.asyncio
async def test_poll_recount_forwarded_channel_post(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = _seed_poll(router_app_context)
    _seed_weights(router_app_context)

    await dp.feed_update(bot=router_app_context.bot, update=_recount_update(30))

    requests = mock_telegram.get_requests()
    edits = _chat_message_bodies(requests, CHANNEL_ID, "editMessageText")
    assert edits
    assert "(5)" in edits[0]["text"]
    assert "(3)" in edits[0]["text"]
    assert "Need 5(7) votes from 8" in edits[0]["text"]

    replies = _chat_message_bodies(requests, MTLChats.ITolstov)
    assert any("10 → 5" in body.get("text", "") for body in replies)
    assert my_poll["closed"] is False
    assert my_poll["buttons"][0][1] == 5
    assert my_poll["buttons"][1][1] == 3
    assert router_app_context.poll_service.save_poll.called


@pytest.mark.asyncio
async def test_poll_recount_refuses_closed_poll(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = _seed_poll(router_app_context, closed=True)
    _seed_weights(router_app_context)

    await dp.feed_update(bot=router_app_context.bot, update=_recount_update(31))

    requests = mock_telegram.get_requests()
    replies = _chat_message_bodies(requests, MTLChats.ITolstov)
    assert any("закрыто" in body.get("text", "") for body in replies)
    assert not _chat_message_bodies(requests, CHANNEL_ID, "editMessageText")
    assert not router_app_context.poll_service.save_poll.called
    assert my_poll["closed"] is True
    assert my_poll["buttons"][0][1] == 10


@pytest.mark.asyncio
async def test_poll_recount_by_link_argument(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = _seed_poll(router_app_context, message_id=42)
    _seed_weights(router_app_context)

    update = types.Update(
        update_id=32,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.ITolstov, type="private"),
            from_user=types.User(id=84131737, is_bot=False, first_name="Admin", username="admin"),
            text="/poll_recount https://t.me/c/1649743884/42",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    edits = _chat_message_bodies(requests, CHANNEL_ID, "editMessageText")
    assert edits
    assert str(edits[0]["message_id"]) == "42"
    assert "(5)" in edits[0]["text"]
    assert my_poll["buttons"][0][1] == 5


@pytest.mark.asyncio
async def test_poll_recount_reply_without_forward(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    poll_message_id = 77
    my_poll = _seed_poll(router_app_context, chat_id=MTLChats.TestGroup, message_id=poll_message_id)
    _seed_weights(router_app_context, chat_id=MTLChats.TestGroup)

    update = types.Update(
        update_id=33,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.TestGroup, type="supergroup"),
            from_user=types.User(id=84131737, is_bot=False, first_name="Admin", username="admin"),
            text="/poll_recount",
            reply_to_message=types.Message(
                message_id=poll_message_id,
                date=datetime.datetime.now(),
                chat=types.Chat(id=MTLChats.TestGroup, type="supergroup"),
                text="poll body",
            ),
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert my_poll["buttons"][0][1] == 5
    assert my_poll["buttons"][1][1] == 3


@pytest.mark.asyncio
async def test_poll_recount_without_weights(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = _seed_poll(router_app_context)

    await dp.feed_update(bot=router_app_context.bot, update=_recount_update(34))

    requests = mock_telegram.get_requests()
    replies = _chat_message_bodies(requests, MTLChats.ITolstov)
    assert any("Нет данных о весах" in body.get("text", "") for body in replies)
    assert not _chat_message_bodies(requests, CHANNEL_ID, "editMessageText")
    assert not router_app_context.poll_service.save_poll.called
    assert my_poll["buttons"][0][1] == 10


@pytest.mark.asyncio
async def test_poll_recount_keeps_recount_when_edit_fails(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = _seed_poll(router_app_context)
    _seed_weights(router_app_context)
    mock_telegram.add_response(
        "editMessageText",
        {"ok": False, "error_code": 400, "description": "Bad Request: message can't be edited"},
        status=400,
    )

    await dp.feed_update(bot=router_app_context.bot, update=_recount_update(35))

    replies = _chat_message_bodies(mock_telegram.get_requests(), MTLChats.ITolstov)
    assert any("не удалось" in body.get("text", "") for body in replies)
    assert router_app_context.poll_service.save_poll.called
    assert my_poll["buttons"][0][1] == 5


@pytest.mark.asyncio
async def test_poll_recount_requires_admin(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    my_poll = _seed_poll(router_app_context)
    _seed_weights(router_app_context)

    await dp.feed_update(bot=router_app_context.bot, update=_recount_update(36, username="stranger"))

    requests = mock_telegram.get_requests()
    replies = _chat_message_bodies(requests, MTLChats.ITolstov)
    assert any("You are not my admin." in body.get("text", "") for body in replies)
    assert not router_app_context.poll_service.save_poll.called
    assert my_poll["buttons"][0][1] == 10
    assert not _chat_message_bodies(requests, CHANNEL_ID, "editMessageText")


# --- Review fixes: escaping, links, timeouts, edge cases ---------------------------


def _admin_bodies(requests):
    return _chat_message_bodies(requests, MTLChats.ITolstov)


@pytest.mark.asyncio
async def test_channel_post_saves_poll_with_empty_sums(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.channel_post.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.stellar_service.get_balances.return_value = ({}, [{"key": "G1", "weight": 3}])
    router_app_context.stellar_service.address_id_to_username.return_value = "@user"

    await dp.feed_update(bot=router_app_context.bot, update=_channel_poll_update(40))

    assert router_app_context.poll_service.save_poll.called
    saved_polls = list(router_app_context.poll_service._polls.values())
    assert saved_polls
    assert all(button[1] == 0 for button in saved_polls[0]["buttons"])
    assert all(button[2] == [] for button in saved_polls[0]["buttons"])


@pytest.mark.asyncio
async def test_channel_post_timeout_still_creates_poll(mock_telegram, router_app_context, monkeypatch):
    dp = router_app_context.dispatcher
    dp.channel_post.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    monkeypatch.setattr("routers.polls.VOTE_RECALC_TIMEOUT", 0.01)

    async def _slow_balances(*args, **kwargs):
        await asyncio.sleep(0.05)
        return {}, [{"key": "G1", "weight": 1}]

    router_app_context.stellar_service.get_balances.side_effect = _slow_balances

    await dp.feed_update(bot=router_app_context.bot, update=_channel_poll_update(41))

    requests = mock_telegram.get_requests()
    assert "⚠️" in _reaction_emojis(requests)
    assert any("Channel Q?" in body.get("text", "") for body in _chat_message_bodies(requests, CHANNEL_ID))
    assert any("не удался" in body.get("text", "") for body in _admin_bodies(requests))


@pytest.mark.asyncio
async def test_poll_command_failure_notifies_admin(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.stellar_service.get_balances.side_effect = RuntimeError("horizon down")

    poll_msg = types.Message(
        message_id=1,
        date=datetime.datetime.now(),
        chat=types.Chat(id=MTLChats.TestGroup, type="supergroup"),
        from_user=types.User(id=999, is_bot=False, first_name="Admin"),
        poll=types.Poll(
            id="p1",
            question="Q?",
            options=[types.PollOption(persistent_id="pid_A", text="A", voter_count=0)],
            total_voter_count=0,
            is_closed=False,
            is_anonymous=True,
            type="regular",
            allows_multiple_answers=False,
            allows_revoting=False,
            members_only=False,
        ),
    )
    update = types.Update(
        update_id=42,
        message=types.Message(
            message_id=2,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.TestGroup, type="supergroup"),
            from_user=types.User(id=999, is_bot=False, first_name="Admin"),
            text="/poll",
            reply_to_message=poll_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert "⚠️" in _reaction_emojis(requests)
    assert router_app_context.poll_service.save_poll.called
    assert any("не удался" in body.get("text", "") for body in _admin_bodies(requests))


@pytest.mark.asyncio
async def test_channel_post_unresolved_report_is_limited(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.channel_post.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    signers = [{"key": f"GKEY{i:04d}XYZ", "weight": 1} for i in range(25)]
    router_app_context.stellar_service.get_balances.return_value = ({}, signers)
    # Same signer list is returned for every address, so the name must derive from the key itself.
    router_app_context.stellar_service.address_id_to_username.side_effect = (
        lambda key, **kwargs: f"{key}..XYZ не найден, возможно скам"
    )

    await dp.feed_update(bot=router_app_context.bot, update=_channel_poll_update(43))

    admin_bodies = _admin_bodies(mock_telegram.get_requests())
    assert admin_bodies
    text = admin_bodies[0]["text"]
    assert "(25)" in text
    assert "ещё 5" in text


@pytest.mark.asyncio
async def test_poll_recount_public_link(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = _seed_poll(router_app_context, message_id=42)
    _seed_weights(router_app_context)
    mock_telegram.add_response(
        "getChat",
        {
            "ok": True,
            "result": {
                "id": CHANNEL_ID,
                "type": "channel",
                "title": "MTL",
                "accent_color_id": 0,
                "max_reaction_count": 0,
                "accepted_gift_types": {
                    "unlimited_gifts": True,
                    "limited_gifts": False,
                    "unique_gifts": False,
                    "premium_subscription": False,
                    "gifts_from_channels": False,
                },
            },
        },
    )

    update = types.Update(
        update_id=44,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.ITolstov, type="private"),
            from_user=types.User(id=84131737, is_bot=False, first_name="Admin", username="admin"),
            text="/poll_recount https://t.me/mtlchannel/42",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    edits = _chat_message_bodies(mock_telegram.get_requests(), CHANNEL_ID, "editMessageText")
    assert edits
    assert str(edits[0]["message_id"]) == "42"
    assert my_poll["buttons"][0][1] == 5


@pytest.mark.asyncio
async def test_poll_recount_link_with_topic_segment(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = _seed_poll(router_app_context, message_id=42)
    _seed_weights(router_app_context)

    update = types.Update(
        update_id=45,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.ITolstov, type="private"),
            from_user=types.User(id=84131737, is_bot=False, first_name="Admin", username="admin"),
            text="/poll_recount https://t.me/c/1649743884/777/42?thread=777",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    edits = _chat_message_bodies(mock_telegram.get_requests(), CHANNEL_ID, "editMessageText")
    assert edits
    assert str(edits[0]["message_id"]) == "42"
    assert my_poll["buttons"][0][1] == 5


@pytest.mark.asyncio
async def test_poll_recount_link_wins_over_reply(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = _seed_poll(router_app_context, message_id=42)
    _seed_weights(router_app_context)

    update = types.Update(
        update_id=46,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.ITolstov, type="private"),
            from_user=types.User(id=84131737, is_bot=False, first_name="Admin", username="admin"),
            text="/poll_recount https://t.me/c/1649743884/42",
            reply_to_message=types.Message(
                message_id=555,
                date=datetime.datetime.now(),
                chat=types.Chat(id=MTLChats.ITolstov, type="private"),
                text="some user message",
            ),
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    edits = _chat_message_bodies(mock_telegram.get_requests(), CHANNEL_ID, "editMessageText")
    assert edits
    assert str(edits[0]["message_id"]) == "42"
    assert my_poll["buttons"][0][1] == 5


@pytest.mark.asyncio
async def test_poll_recount_escapes_html_and_uses_full_option_names(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = {
        "question": "Q <x> & A?",
        "closed": False,
        "message_id": POLL_MESSAGE_ID,
        "buttons": [["A & B", 1, ["@user"]]],
    }
    router_app_context.poll_service._polls[(CHANNEL_ID, POLL_MESSAGE_ID)] = my_poll
    _seed_weights(router_app_context)

    await dp.feed_update(bot=router_app_context.bot, update=_recount_update(47))

    requests = mock_telegram.get_requests()
    edits = _chat_message_bodies(requests, CHANNEL_ID, "editMessageText")
    assert edits
    assert "&amp;" in edits[0]["text"]
    assert "&lt;x&gt;" in edits[0]["text"]
    assert "<x>" not in edits[0]["text"]
    assert any("A &amp; B: 1 → 5" in body.get("text", "") for body in _admin_bodies(requests))


@pytest.mark.asyncio
async def test_poll_recount_reports_lost_weight(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = _seed_poll(router_app_context)
    my_poll["buttons"][1][2].append("@ghost")
    my_poll["buttons"][1][1] = 9
    _seed_weights(router_app_context)

    await dp.feed_update(bot=router_app_context.bot, update=_recount_update(48))

    replies = _admin_bodies(mock_telegram.get_requests())
    assert any("Обнулены (нет веса): @ghost" in body.get("text", "") for body in replies)
    assert my_poll["buttons"][1][1] == 3


@pytest.mark.asyncio
async def test_poll_recount_normalizes_legacy_names(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = {
        "question": "Q?",
        "closed": False,
        "message_id": POLL_MESSAGE_ID,
        "buttons": [["A", 7, ["'@User'"]]],
    }
    router_app_context.poll_service._polls[(CHANNEL_ID, POLL_MESSAGE_ID)] = my_poll
    _seed_weights(router_app_context)

    await dp.feed_update(bot=router_app_context.bot, update=_recount_update(49))

    assert my_poll["buttons"][0][1] == 5
    replies = _admin_bodies(mock_telegram.get_requests())
    assert not any("Обнулены" in body.get("text", "") for body in replies)


@pytest.mark.asyncio
async def test_poll_recount_handles_not_modified_message(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = _seed_poll(router_app_context)
    _seed_weights(router_app_context)
    mock_telegram.add_response(
        "editMessageText",
        {
            "ok": False,
            "error_code": 400,
            "description": "Bad Request: message is not modified: specified new message content and reply markup",
        },
        status=400,
    )

    await dp.feed_update(bot=router_app_context.bot, update=_recount_update(50))

    replies = _admin_bodies(mock_telegram.get_requests())
    assert any("уже содержит актуальные данные" in body.get("text", "") for body in replies)
    assert router_app_context.poll_service.save_poll.called
    assert my_poll["buttons"][0][1] == 5


# --- Review round 2: forbidden errors, link formats, fail-fast input ----------------


@pytest.mark.asyncio
async def test_poll_recount_survives_forbidden_edit(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = _seed_poll(router_app_context)
    _seed_weights(router_app_context)
    mock_telegram.add_response(
        "editMessageText",
        {"ok": False, "error_code": 403, "description": "Forbidden: bot is not a member of the channel chat"},
        status=403,
    )

    await dp.feed_update(bot=router_app_context.bot, update=_recount_update(60))

    replies = _admin_bodies(mock_telegram.get_requests())
    assert any("не удалось" in body.get("text", "") for body in replies)
    assert router_app_context.poll_service.save_poll.called
    assert my_poll["buttons"][0][1] == 5


@pytest.mark.asyncio
async def test_poll_recount_link_with_trailing_slash(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = _seed_poll(router_app_context, message_id=42)
    _seed_weights(router_app_context)

    update = types.Update(
        update_id=61,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.ITolstov, type="private"),
            from_user=types.User(id=84131737, is_bot=False, first_name="Admin", username="admin"),
            text="/poll_recount https://t.me/c/1649743884/42/",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert my_poll["buttons"][0][1] == 5


@pytest.mark.asyncio
async def test_poll_recount_public_link_with_topic_segment(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = _seed_poll(router_app_context, message_id=42)
    _seed_weights(router_app_context)
    mock_telegram.add_response(
        "getChat",
        {
            "ok": True,
            "result": {
                "id": CHANNEL_ID,
                "type": "channel",
                "title": "MTL",
                "accent_color_id": 0,
                "max_reaction_count": 0,
                "accepted_gift_types": {
                    "unlimited_gifts": True,
                    "limited_gifts": False,
                    "unique_gifts": False,
                    "premium_subscription": False,
                    "gifts_from_channels": False,
                },
            },
        },
    )

    update = types.Update(
        update_id=62,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.ITolstov, type="private"),
            from_user=types.User(id=84131737, is_bot=False, first_name="Admin", username="admin"),
            text="/poll_recount https://t.me/mtlchannel/777/42",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert my_poll["buttons"][0][1] == 5


@pytest.mark.asyncio
async def test_poll_recount_broken_link_does_not_fall_back_to_reply(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = _seed_poll(router_app_context)
    _seed_weights(router_app_context)

    # A message link that cannot be resolved must not silently fall back to the replied poll.
    update = _recount_update(63, text="/poll_recount t.me/unknown_channel/42")
    await dp.feed_update(bot=router_app_context.bot, update=update)

    replies = _admin_bodies(mock_telegram.get_requests())
    assert any("Нужен ответ на пересланный" in body.get("text", "") for body in replies)
    assert not router_app_context.poll_service.save_poll.called
    assert my_poll["buttons"][0][1] == 10


@pytest.mark.asyncio
async def test_poll_recount_unsupported_chat(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    unsupported_chat_id = -1009999999999
    poll_message_id = 55
    my_poll = _seed_poll(router_app_context, chat_id=unsupported_chat_id, message_id=poll_message_id)

    update = types.Update(
        update_id=64,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=unsupported_chat_id, type="supergroup"),
            from_user=types.User(id=84131737, is_bot=False, first_name="Admin", username="admin"),
            text="/poll_recount",
            reply_to_message=types.Message(
                message_id=poll_message_id,
                date=datetime.datetime.now(),
                chat=types.Chat(id=unsupported_chat_id, type="supergroup"),
                text="poll body",
            ),
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    bodies = _chat_message_bodies(requests, unsupported_chat_id)
    assert any("не поддерживает взвешенные голосования" in body.get("text", "") for body in bodies)
    assert not router_app_context.poll_service.save_poll.called
    assert my_poll["buttons"][0][1] == 10


@pytest.mark.asyncio
async def test_poll_reload_vote_limits_unresolved_list(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    signers = [{"key": f"GKEY{i:04d}XYZ", "weight": 1} for i in range(25)]
    router_app_context.stellar_service.get_balances.return_value = ({}, signers)
    router_app_context.stellar_service.address_id_to_username.side_effect = (
        lambda key, **kwargs: f"{key}..XYZ не найден, возможно скам"
    )

    update = types.Update(
        update_id=65,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.TestGroup, type="supergroup"),
            from_user=types.User(id=84131737, is_bot=False, first_name="Admin", username="admin"),
            text="/poll_reload_vote",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    bodies = _chat_message_bodies(mock_telegram.get_requests(), MTLChats.TestGroup)
    report = next((body for body in bodies if "не найденных" in body.get("text", "")), None)
    assert report is not None
    assert "(25)" in report["text"]
    assert "ещё 5" in report["text"]


# --- Review round 3: no recount in unsupported chats, duplicates -------------------


@pytest.mark.asyncio
async def test_poll_command_does_not_recount_in_unsupported_chat(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    unsupported_chat_id = -1009999999999
    poll_msg = types.Message(
        message_id=1,
        date=datetime.datetime.now(),
        chat=types.Chat(id=unsupported_chat_id, type="supergroup"),
        from_user=types.User(id=999, is_bot=False, first_name="User"),
        poll=types.Poll(
            id="p1",
            question="Q?",
            options=[types.PollOption(persistent_id="pid_A", text="A", voter_count=0)],
            total_voter_count=0,
            is_closed=False,
            is_anonymous=True,
            type="regular",
            allows_multiple_answers=False,
            allows_revoting=False,
            members_only=False,
        ),
    )
    update = types.Update(
        update_id=70,
        message=types.Message(
            message_id=2,
            date=datetime.datetime.now(),
            chat=types.Chat(id=unsupported_chat_id, type="supergroup"),
            from_user=types.User(id=999, is_bot=False, first_name="User"),
            text="/poll",
            reply_to_message=poll_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    # Poll is still created as before, but no blockchain/Grist storm and no reactions.
    assert router_app_context.poll_service.save_poll.called
    assert not router_app_context.stellar_service.get_balances.called
    assert _reaction_emojis(mock_telegram.get_requests()) == []
    assert not _admin_bodies(mock_telegram.get_requests())


@pytest.mark.asyncio
async def test_poll_recount_counts_duplicated_voter_once(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = {
        "question": "Q?",
        "closed": False,
        "message_id": POLL_MESSAGE_ID,
        "buttons": [["A", 10, ["@user", "'@User'"]]],
    }
    router_app_context.poll_service._polls[(CHANNEL_ID, POLL_MESSAGE_ID)] = my_poll
    _seed_weights(router_app_context)

    await dp.feed_update(bot=router_app_context.bot, update=_recount_update(71))

    assert my_poll["buttons"][0][1] == 5
    assert my_poll["buttons"][0][2] == ["@user"]


# --- Review round 4: broken poll data, missing polls, DM without reply -------------


@pytest.mark.asyncio
async def test_poll_recount_refuses_poll_with_invalid_buttons(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = {"question": "Q?", "closed": False, "message_id": POLL_MESSAGE_ID, "buttons": [["A"], "broken"]}
    router_app_context.poll_service._polls[(CHANNEL_ID, POLL_MESSAGE_ID)] = my_poll
    _seed_weights(router_app_context)

    await dp.feed_update(bot=router_app_context.bot, update=_recount_update(80))

    requests = mock_telegram.get_requests()
    replies = _admin_bodies(requests)
    assert any("нет валидных кнопок" in body.get("text", "") for body in replies)
    assert not router_app_context.poll_service.save_poll.called
    assert not _chat_message_bodies(requests, CHANNEL_ID, "editMessageText")
    assert my_poll["buttons"] == [["A"], "broken"]


@pytest.mark.asyncio
async def test_poll_recount_reports_missing_poll(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    _seed_weights(router_app_context)

    await dp.feed_update(bot=router_app_context.bot, update=_recount_update(81))

    replies = _admin_bodies(mock_telegram.get_requests())
    assert any("Опрос не найден" in body.get("text", "") for body in replies)
    assert not router_app_context.poll_service.save_poll.called


@pytest.mark.asyncio
async def test_poll_recount_without_reply_or_link(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])

    update = types.Update(
        update_id=82,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.ITolstov, type="private"),
            from_user=types.User(id=84131737, is_bot=False, first_name="Admin", username="admin"),
            text="/poll_recount",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    replies = _admin_bodies(mock_telegram.get_requests())
    assert any("Нужен ответ на пересланный" in body.get("text", "") for body in replies)


@pytest.mark.asyncio
async def test_poll_recount_unresolvable_public_link(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    mock_telegram.add_response(
        "getChat", {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}, status=400
    )

    update = types.Update(
        update_id=83,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.ITolstov, type="private"),
            from_user=types.User(id=84131737, is_bot=False, first_name="Admin", username="admin"),
            text="/poll_recount https://t.me/unknown/42",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    replies = _admin_bodies(mock_telegram.get_requests())
    assert any("Нужен ответ на пересланный" in body.get("text", "") for body in replies)


@pytest.mark.asyncio
async def test_poll_recount_limits_lost_weight_report(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    ghosts = [f"@ghost{i:02d}" for i in range(25)]
    my_poll = {
        "question": "Q?",
        "closed": False,
        "message_id": POLL_MESSAGE_ID,
        "buttons": [["A", 0, list(ghosts)]],
    }
    router_app_context.poll_service._polls[(CHANNEL_ID, POLL_MESSAGE_ID)] = my_poll
    _seed_weights(router_app_context)

    await dp.feed_update(bot=router_app_context.bot, update=_recount_update(84))

    replies = _admin_bodies(mock_telegram.get_requests())
    report = next((body["text"] for body in replies if "Обнулены" in body.get("text", "")), None)
    assert report is not None
    assert "ещё 5" in report


@pytest.mark.asyncio
async def test_poll_recount_link_beats_forwarded_reply(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = _seed_poll(router_app_context, message_id=42)
    other_poll = _seed_poll(router_app_context, message_id=777, closed=True)
    _seed_weights(router_app_context)

    update = types.Update(
        update_id=85,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.ITolstov, type="private"),
            from_user=types.User(id=84131737, is_bot=False, first_name="Admin", username="admin"),
            text="/poll_recount https://t.me/c/1649743884/42",
            reply_to_message=types.Message(
                message_id=20,
                date=datetime.datetime.now(),
                chat=types.Chat(id=MTLChats.ITolstov, type="private"),
                forward_origin=types.MessageOriginChannel(
                    type="channel",
                    date=datetime.datetime.now(),
                    chat=types.Chat(id=CHANNEL_ID, type="channel"),
                    message_id=777,
                ),
            ),
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    # The link pointed at the open poll, so it must be recounted and the closed one untouched.
    assert my_poll["buttons"][0][1] == 5
    assert other_poll["buttons"][0][1] == 10
    assert other_poll["closed"] is True


# --- Review round 5: publish failures, network errors, link formats ----------------


@pytest.mark.asyncio
async def test_channel_post_publish_failure_notifies_correctly(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.channel_post.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.stellar_service.get_balances.return_value = ({}, [{"key": "G1", "weight": 3}])
    router_app_context.stellar_service.address_id_to_username.return_value = "@user"
    mock_telegram.add_response(
        "sendMessage", {"ok": False, "error_code": 400, "description": "Bad Request: no rights"}, status=400
    )

    await dp.feed_update(bot=router_app_context.bot, update=_channel_poll_update(90))

    requests = mock_telegram.get_requests()
    assert not router_app_context.poll_service.save_poll.called
    assert "⚠️" in _reaction_emojis(requests)
    admin_texts = [body.get("text", "") for body in _admin_bodies(requests)]
    assert any("не создан" in text for text in admin_texts)
    assert all("создан на предыдущих весах" not in text for text in admin_texts)


@pytest.mark.asyncio
async def test_poll_command_publish_failure_in_plain_chat_is_silent(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    mock_telegram.add_response(
        "sendMessage", {"ok": False, "error_code": 400, "description": "Bad Request: no rights"}, status=400
    )
    unsupported_chat_id = -1009999999999
    poll_msg = types.Message(
        message_id=1,
        date=datetime.datetime.now(),
        chat=types.Chat(id=unsupported_chat_id, type="supergroup"),
        from_user=types.User(id=999, is_bot=False, first_name="User"),
        poll=types.Poll(
            id="p1",
            question="Q?",
            options=[types.PollOption(persistent_id="pid_A", text="A", voter_count=0)],
            total_voter_count=0,
            is_closed=False,
            is_anonymous=True,
            type="regular",
            allows_multiple_answers=False,
            allows_revoting=False,
            members_only=False,
        ),
    )
    update = types.Update(
        update_id=91,
        message=types.Message(
            message_id=2,
            date=datetime.datetime.now(),
            chat=types.Chat(id=unsupported_chat_id, type="supergroup"),
            from_user=types.User(id=999, is_bot=False, first_name="User"),
            text="/poll",
            reply_to_message=poll_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    requests = mock_telegram.get_requests()
    assert _reaction_emojis(requests) == []
    assert not _admin_bodies(requests)
    assert not router_app_context.poll_service.save_poll.called


@pytest.mark.asyncio
async def test_channel_post_survives_reaction_failure(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.channel_post.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.stellar_service.get_balances.return_value = ({}, [{"key": "G1", "weight": 3}])
    router_app_context.stellar_service.address_id_to_username.return_value = "@user"
    mock_telegram.add_response(
        "setMessageReaction",
        {"ok": False, "error_code": 400, "description": "Bad Request: REACTION_INVALID"},
        status=400,
    )

    await dp.feed_update(bot=router_app_context.bot, update=_channel_poll_update(92))

    assert router_app_context.poll_service.save_poll.called


@pytest.mark.asyncio
async def test_poll_recount_survives_network_error_on_edit(mock_telegram, router_app_context, monkeypatch):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = _seed_poll(router_app_context)
    _seed_weights(router_app_context)

    async def _boom(*args, **kwargs):
        raise ConnectionError("connection reset by peer")

    monkeypatch.setattr(router_app_context.bot, "edit_message_text", _boom)

    await dp.feed_update(bot=router_app_context.bot, update=_recount_update(93))

    replies = _admin_bodies(mock_telegram.get_requests())
    assert any("не удалось" in body.get("text", "") for body in replies)
    assert router_app_context.poll_service.save_poll.called
    assert my_poll["buttons"][0][1] == 5


@pytest.mark.asyncio
async def test_channel_post_survives_blocked_admin_dm(mock_telegram, router_app_context, monkeypatch):
    dp = router_app_context.dispatcher
    dp.channel_post.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.stellar_service.get_balances.return_value = ({}, [{"key": "G1", "weight": 3}])
    router_app_context.stellar_service.address_id_to_username.return_value = NOT_FOUND_NAME

    original_send = router_app_context.bot.send_message

    async def _send(chat_id, text, **kwargs):
        if str(chat_id) == str(MTLChats.ITolstov):
            raise RuntimeError("bot was blocked by the user")
        return await original_send(chat_id, text, **kwargs)

    monkeypatch.setattr(router_app_context.bot, "send_message", _send)

    await dp.feed_update(bot=router_app_context.bot, update=_channel_poll_update(94))

    assert router_app_context.poll_service.save_poll.called


@pytest.mark.asyncio
async def test_poll_recount_with_bot_mention(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = _seed_poll(router_app_context, message_id=42)
    _seed_weights(router_app_context)

    update = types.Update(
        update_id=95,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.ITolstov, type="private"),
            from_user=types.User(id=84131737, is_bot=False, first_name="Admin", username="admin"),
            text="/poll_recount@test_bot https://t.me/c/1649743884/42",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert my_poll["buttons"][0][1] == 5


@pytest.mark.asyncio
async def test_poll_recount_web_preview_link(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = _seed_poll(router_app_context, message_id=42)
    _seed_weights(router_app_context)
    mock_telegram.add_response(
        "getChat",
        {
            "ok": True,
            "result": {
                "id": CHANNEL_ID,
                "type": "channel",
                "title": "MTL",
                "accent_color_id": 0,
                "max_reaction_count": 0,
                "accepted_gift_types": {
                    "unlimited_gifts": True,
                    "limited_gifts": False,
                    "unique_gifts": False,
                    "premium_subscription": False,
                    "gifts_from_channels": False,
                },
            },
        },
    )

    update = types.Update(
        update_id=96,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.ITolstov, type="private"),
            from_user=types.User(id=84131737, is_bot=False, first_name="Admin", username="admin"),
            text="/poll_recount <https://t.me/s/mtlchannel/42>",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert my_poll["buttons"][0][1] == 5


# --- Review round 6: normalized names must stay toggleable in cq_join_list ---------


def _click_update(update_id: int, *, chat_id=CHANNEL_ID, message_id=POLL_MESSAGE_ID, username="user"):
    return types.Update(
        update_id=update_id,
        callback_query=types.CallbackQuery(
            id=f"cb{update_id}",
            chat_instance="ci1",
            from_user=types.User(id=999, is_bot=False, first_name="User", username=username),
            message=types.Message(
                message_id=message_id,
                date=datetime.datetime.now(),
                chat=types.Chat(id=chat_id, type="channel"),
                text="Poll Body",
            ),
            data=PollCallbackData(answer=0).pack(),
        ),
    )


@pytest.mark.asyncio
async def test_poll_recount_normalized_names_are_toggleable(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.callback_query.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = {
        "question": "Q?",
        "closed": False,
        "message_id": POLL_MESSAGE_ID,
        "buttons": [["A", 7, ["'@User'"]]],
    }
    router_app_context.poll_service._polls[(CHANNEL_ID, POLL_MESSAGE_ID)] = my_poll
    _seed_weights(router_app_context)

    await dp.feed_update(bot=router_app_context.bot, update=_recount_update(100))

    assert my_poll["buttons"][0][2] == ["@user"]
    assert my_poll["buttons"][0][1] == 5

    # The voter must be able to toggle the same (now normalized) entry off again.
    await dp.feed_update(bot=router_app_context.bot, update=_click_update(101))

    assert my_poll["buttons"][0][2] == []
    assert my_poll["buttons"][0][1] == 0


@pytest.mark.asyncio
async def test_channel_post_escapes_question_with_special_chars(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.channel_post.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.stellar_service.get_balances.return_value = ({}, [{"key": "G1", "weight": 1}])
    router_app_context.stellar_service.address_id_to_username.return_value = "@user"

    update = _channel_poll_update(102, question="Выбрать <TokenA> & <TokenB>?")
    await dp.feed_update(bot=router_app_context.bot, update=update)

    bodies = _chat_message_bodies(mock_telegram.get_requests(), CHANNEL_ID)
    assert bodies
    assert "&lt;TokenA&gt;" in bodies[0]["text"]
    assert "&amp;" in bodies[0]["text"]
    assert router_app_context.poll_service.save_poll.called


@pytest.mark.asyncio
async def test_poll_recount_refuses_non_list_buttons(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    router_app_context.poll_service._polls[(CHANNEL_ID, POLL_MESSAGE_ID)] = {
        "question": "Q?",
        "closed": False,
        "message_id": POLL_MESSAGE_ID,
        "buttons": 123,
    }
    _seed_weights(router_app_context)

    await dp.feed_update(bot=router_app_context.bot, update=_recount_update(103))

    requests = mock_telegram.get_requests()
    replies = _admin_bodies(requests)
    assert any("Опрос не найден" in body.get("text", "") for body in replies)
    assert not router_app_context.poll_service.save_poll.called


@pytest.mark.asyncio
async def test_poll_recount_link_with_spaces_inside_brackets(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = _seed_poll(router_app_context, message_id=42)
    _seed_weights(router_app_context)

    update = types.Update(
        update_id=104,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.ITolstov, type="private"),
            from_user=types.User(id=84131737, is_bot=False, first_name="Admin", username="admin"),
            text="/poll_recount < https://t.me/c/1649743884/42 >",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert my_poll["buttons"][0][1] == 5


# --- Review round 7: immediate commit, NEED header, reload timeout -----------------


@pytest.mark.asyncio
async def test_channel_post_saves_poll_in_own_session(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.channel_post.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.stellar_service.get_balances.return_value = ({}, [{"key": "G1", "weight": 3}])
    router_app_context.stellar_service.address_id_to_username.return_value = "@user"

    await dp.feed_update(bot=router_app_context.bot, update=_channel_poll_update(110))

    # save_poll must be called with None (own committed session), otherwise a click that lands
    # before the middleware commit reads an empty poll and sees "This poll is closed!".
    assert router_app_context.poll_service.save_poll.called
    args, _ = router_app_context.poll_service.save_poll.call_args
    assert args[0] is None


@pytest.mark.asyncio
async def test_poll_command_shows_need_in_first_message(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.stellar_service.get_balances.return_value = ({}, [{"key": "G1", "weight": 10}])
    router_app_context.stellar_service.address_id_to_username.return_value = "@user"

    poll_msg = types.Message(
        message_id=1,
        date=datetime.datetime.now(),
        chat=types.Chat(id=MTLChats.TestGroup, type="supergroup"),
        from_user=types.User(id=999, is_bot=False, first_name="Admin"),
        poll=types.Poll(
            id="p1",
            question="Q?",
            options=[types.PollOption(persistent_id="pid_A", text="A", voter_count=0)],
            total_voter_count=0,
            is_closed=False,
            is_anonymous=True,
            type="regular",
            allows_multiple_answers=False,
            allows_revoting=False,
            members_only=False,
        ),
    )
    update = types.Update(
        update_id=111,
        message=types.Message(
            message_id=2,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.TestGroup, type="supergroup"),
            from_user=types.User(id=999, is_bot=False, first_name="Admin"),
            text="/poll",
            reply_to_message=poll_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    bodies = _chat_message_bodies(mock_telegram.get_requests(), MTLChats.TestGroup)
    assert bodies
    assert "Need 6(8) votes from 10" in bodies[0]["text"]


@pytest.mark.asyncio
async def test_poll_reload_vote_timeout(mock_telegram, router_app_context, monkeypatch):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    monkeypatch.setattr("routers.polls.VOTE_RECALC_TIMEOUT", 0.01)

    async def _slow_balances(*args, **kwargs):
        await asyncio.sleep(0.05)
        return {}, [{"key": "G1", "weight": 1}]

    router_app_context.stellar_service.get_balances.side_effect = _slow_balances

    update = types.Update(
        update_id=112,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.TestGroup, type="supergroup"),
            from_user=types.User(id=84131737, is_bot=False, first_name="Admin", username="admin"),
            text="/poll_reload_vote",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    bodies = _chat_message_bodies(mock_telegram.get_requests(), MTLChats.TestGroup)
    assert any("таймаут" in body.get("text", "") for body in bodies)


# --- Review round 8: persist failures, NEED fallback, link with comment ------------


@pytest.mark.asyncio
async def test_channel_post_deletes_published_poll_when_save_fails(mock_telegram, router_app_context, monkeypatch):
    dp = router_app_context.dispatcher
    dp.channel_post.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.stellar_service.get_balances.return_value = ({}, [{"key": "G1", "weight": 3}])
    router_app_context.stellar_service.address_id_to_username.return_value = "@user"

    async def _broken_save(*args, **kwargs):
        raise RuntimeError("db is down")

    monkeypatch.setattr(router_app_context.poll_service, "save_poll", _broken_save)

    await dp.feed_update(bot=router_app_context.bot, update=_channel_poll_update(120))

    requests = mock_telegram.get_requests()
    # The published message must be removed: without a DB record its buttons are dead.
    assert any(r["method"] == "deleteMessage" for r in requests)
    assert "⚠️" in _reaction_emojis(requests)
    assert any("не создан" in body.get("text", "") for body in _admin_bodies(requests))


@pytest.mark.asyncio
async def test_channel_post_shows_need_when_recount_fails(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.channel_post.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.stellar_service.get_balances.side_effect = RuntimeError("horizon down")
    router_app_context.voting_service.set_vote_weights(
        chat_to_address[CHANNEL_ID], {"@user": 10, "NEED": {"50": 6, "75": 8, "100": 10}}
    )

    await dp.feed_update(bot=router_app_context.bot, update=_channel_poll_update(121))

    bodies = _chat_message_bodies(mock_telegram.get_requests(), CHANNEL_ID)
    assert bodies
    assert "Need 6(8) votes from 10" in bodies[0]["text"]


@pytest.mark.asyncio
async def test_poll_recount_link_with_trailing_comment(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = _seed_poll(router_app_context, message_id=42)
    _seed_weights(router_app_context)

    update = types.Update(
        update_id=122,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.ITolstov, type="private"),
            from_user=types.User(id=84131737, is_bot=False, first_name="Admin", username="admin"),
            text="/poll_recount https://t.me/c/1649743884/42 пересчитай пожалуйста",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert my_poll["buttons"][0][1] == 5


# --- Review round 9: link casing, reload errors, empty poll ------------------------


@pytest.mark.asyncio
async def test_poll_recount_link_is_case_insensitive(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = _seed_poll(router_app_context, message_id=42)
    _seed_weights(router_app_context)

    update = types.Update(
        update_id=130,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.ITolstov, type="private"),
            from_user=types.User(id=84131737, is_bot=False, first_name="Admin", username="admin"),
            text="/poll_recount Https://T.ME/c/1649743884/42",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert my_poll["buttons"][0][1] == 5


@pytest.mark.asyncio
async def test_poll_reload_vote_reports_backend_error(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    router_app_context.stellar_service.get_balances.side_effect = RuntimeError("horizon 500")

    update = types.Update(
        update_id=131,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.TestGroup, type="supergroup"),
            from_user=types.User(id=84131737, is_bot=False, first_name="Admin", username="admin"),
            text="/poll_reload_vote",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    bodies = _chat_message_bodies(mock_telegram.get_requests(), MTLChats.TestGroup)
    assert any("Не удалось обновить веса" in body.get("text", "") for body in bodies)


@pytest.mark.asyncio
async def test_poll_recount_empty_poll(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = {
        "question": "Q?",
        "closed": False,
        "message_id": POLL_MESSAGE_ID,
        "buttons": [["A", 0, []], ["B", 0, []]],
    }
    router_app_context.poll_service._polls[(CHANNEL_ID, POLL_MESSAGE_ID)] = my_poll
    _seed_weights(router_app_context)

    await dp.feed_update(bot=router_app_context.bot, update=_recount_update(132))

    assert [button[1] for button in my_poll["buttons"]] == [0, 0]
    replies = _admin_bodies(mock_telegram.get_requests())
    assert any("A: 0 → 0" in body.get("text", "") for body in replies)
    assert not any("Обнулены" in body.get("text", "") for body in replies)


@pytest.mark.asyncio
async def test_poll_recount_voter_in_multiple_options(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = {
        "question": "Q?",
        "closed": False,
        "message_id": POLL_MESSAGE_ID,
        "buttons": [["A", 5, ["@user"]], ["B", 5, ["@user"]]],
    }
    router_app_context.poll_service._polls[(CHANNEL_ID, POLL_MESSAGE_ID)] = my_poll
    _seed_weights(router_app_context)

    await dp.feed_update(bot=router_app_context.bot, update=_recount_update(133))

    assert [button[1] for button in my_poll["buttons"]] == [5, 5]
    replies = _admin_bodies(mock_telegram.get_requests())
    assert not any("Обнулены" in body.get("text", "") for body in replies)


@pytest.mark.asyncio
async def test_poll_recount_link_in_parentheses(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = _seed_poll(router_app_context, message_id=42)
    _seed_weights(router_app_context)

    update = types.Update(
        update_id=134,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.ITolstov, type="private"),
            from_user=types.User(id=84131737, is_bot=False, first_name="Admin", username="admin"),
            text="/poll_recount (https://t.me/c/1649743884/42)",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert my_poll["buttons"][0][1] == 5


# --- Review round 10: reply with a comment, mutual exclusion -----------------------


@pytest.mark.asyncio
async def test_poll_recount_reply_with_comment_falls_back(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = _seed_poll(router_app_context)
    _seed_weights(router_app_context)

    update = _recount_update(140, text="/poll_recount пересчитай пожалуйста")
    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert my_poll["buttons"][0][1] == 5


@pytest.mark.asyncio
async def test_recount_lock_is_reused_within_one_loop():
    import routers.polls as polls_module

    polls_module._recount_lock = None
    polls_module._recount_lock_loop = None

    first = polls_module._get_recount_lock()
    second = polls_module._get_recount_lock()
    assert first is second

    async with first:
        # A held lock must not be recreated: that would silently disable mutual exclusion.
        assert polls_module._get_recount_lock() is first


# --- Review round 11: link anywhere in the argument, text_link entities ------------


@pytest.mark.asyncio
async def test_poll_recount_link_after_comment(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = _seed_poll(router_app_context, message_id=42)
    _seed_weights(router_app_context)

    update = types.Update(
        update_id=150,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.ITolstov, type="private"),
            from_user=types.User(id=84131737, is_bot=False, first_name="Admin", username="admin"),
            text="/poll_recount вот этот https://t.me/c/1649743884/42 пересчитай",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    # The link wins even though it is not the first token, and the reply is absent.
    assert my_poll["buttons"][0][1] == 5


@pytest.mark.asyncio
async def test_poll_recount_formatted_link_entity(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = _seed_poll(router_app_context, message_id=42)
    _seed_weights(router_app_context)

    text = "/poll_recount пересчитай"
    update = types.Update(
        update_id=151,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.ITolstov, type="private"),
            from_user=types.User(id=84131737, is_bot=False, first_name="Admin", username="admin"),
            text=text,
            entities=[
                types.MessageEntity(
                    type="text_link",
                    offset=len("/poll_recount "),
                    length=len("пересчитай"),
                    url="https://t.me/c/1649743884/42",
                )
            ],
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert my_poll["buttons"][0][1] == 5


@pytest.mark.asyncio
async def test_poll_recount_handles_string_weight_in_storage(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = {
        "question": "Q?",
        "closed": False,
        "message_id": POLL_MESSAGE_ID,
        "buttons": [["A", "10", ["@user"]]],
    }
    router_app_context.poll_service._polls[(CHANNEL_ID, POLL_MESSAGE_ID)] = my_poll
    _seed_weights(router_app_context)

    await dp.feed_update(bot=router_app_context.bot, update=_recount_update(152))

    assert my_poll["buttons"][0][1] == 5
    replies = _admin_bodies(mock_telegram.get_requests())
    assert any("A: 10 → 5" in body.get("text", "") for body in replies)


# --- Review round 12: corrupted storage, caption entities --------------------------


@pytest.mark.asyncio
async def test_poll_recount_survives_corrupted_stored_poll(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    router_app_context.poll_service._polls[(CHANNEL_ID, POLL_MESSAGE_ID)] = ["not", "a", "poll"]
    _seed_weights(router_app_context)

    await dp.feed_update(bot=router_app_context.bot, update=_recount_update(160))

    replies = _admin_bodies(mock_telegram.get_requests())
    assert any("Опрос не найден" in body.get("text", "") for body in replies)
    assert not router_app_context.poll_service.save_poll.called


@pytest.mark.asyncio
async def test_poll_recount_caption_link_entity(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = _seed_poll(router_app_context, message_id=42)
    _seed_weights(router_app_context)

    caption = "/poll_recount скрин"
    update = types.Update(
        update_id=161,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.ITolstov, type="private"),
            from_user=types.User(id=84131737, is_bot=False, first_name="Admin", username="admin"),
            caption=caption,
            caption_entities=[
                types.MessageEntity(
                    type="text_link",
                    offset=len("/poll_recount "),
                    length=len("скрин"),
                    url="https://t.me/c/1649743884/42",
                )
            ],
            photo=[
                types.PhotoSize(file_id="photo", file_unique_id="photo_u", width=1, height=1),
            ],
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert my_poll["buttons"][0][1] == 5


# --- Review round 13: other telegram links in the argument, junk voters ------------


@pytest.mark.asyncio
async def test_poll_recount_skips_foreign_telegram_links(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = _seed_poll(router_app_context, message_id=42)
    _seed_weights(router_app_context)

    update = types.Update(
        update_id=170,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.ITolstov, type="private"),
            from_user=types.User(id=84131737, is_bot=False, first_name="Admin", username="admin"),
            text="/poll_recount новости в https://t.me/our_channel опрос https://t.me/c/1649743884/42",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert my_poll["buttons"][0][1] == 5


@pytest.mark.asyncio
async def test_poll_recount_drops_blank_voter_entries(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = {
        "question": "Q?",
        "closed": False,
        "message_id": POLL_MESSAGE_ID,
        "buttons": [["A", 5, ["@user", "' '", ""]]],
    }
    router_app_context.poll_service._polls[(CHANNEL_ID, POLL_MESSAGE_ID)] = my_poll
    _seed_weights(router_app_context)

    await dp.feed_update(bot=router_app_context.bot, update=_recount_update(171))

    assert my_poll["buttons"][0][2] == ["@user"]
    assert my_poll["buttons"][0][1] == 5
    replies = _admin_bodies(mock_telegram.get_requests())
    assert not any("Обнулены" in body.get("text", "") for body in replies)


@pytest.mark.asyncio
async def test_poll_recount_caps_public_link_resolutions(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    _seed_weights(router_app_context)
    mock_telegram.add_response(
        "getChat", {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}, status=400
    )

    links = " ".join(f"https://t.me/unknown{i}/1" for i in range(10))
    update = types.Update(
        update_id=180,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.ITolstov, type="private"),
            from_user=types.User(id=84131737, is_bot=False, first_name="Admin", username="admin"),
            text=f"/poll_recount {links}",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    get_chat_calls = [r for r in mock_telegram.get_requests() if r["method"] == "getChat"]
    assert len(get_chat_calls) == 3


# --- Review round 15: unified link parsing, grist names with spaces ---------------


@pytest.mark.asyncio
async def test_poll_recount_caps_link_entities(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    _seed_weights(router_app_context)
    mock_telegram.add_response(
        "getChat", {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}, status=400
    )

    text = "/poll_recount " + " ".join(f"канал{i}" for i in range(10))
    entities = []
    offset = len("/poll_recount ")
    for i in range(10):
        entities.append(
            types.MessageEntity(
                type="text_link",
                offset=offset,
                length=len(f"канал{i}"),
                url=f"https://t.me/unknown{i}/1",
            )
        )
        offset += len(f"канал{i}") + 1

    update = types.Update(
        update_id=190,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.ITolstov, type="private"),
            from_user=types.User(id=84131737, is_bot=False, first_name="Admin", username="admin"),
            text=text,
            entities=entities,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert len([r for r in mock_telegram.get_requests() if r["method"] == "getChat"]) == 3


@pytest.mark.asyncio
async def test_poll_recount_link_with_at_prefix(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = _seed_poll(router_app_context, message_id=42)
    _seed_weights(router_app_context)
    mock_telegram.add_response(
        "getChat",
        {
            "ok": True,
            "result": {
                "id": CHANNEL_ID,
                "type": "channel",
                "title": "MTL",
                "accent_color_id": 0,
                "max_reaction_count": 0,
                "accepted_gift_types": {
                    "unlimited_gifts": True,
                    "limited_gifts": False,
                    "unique_gifts": False,
                    "premium_subscription": False,
                    "gifts_from_channels": False,
                },
            },
        },
    )

    update = types.Update(
        update_id=191,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.ITolstov, type="private"),
            from_user=types.User(id=84131737, is_bot=False, first_name="Admin", username="admin"),
            text="/poll_recount https://t.me/@mtlchannel/42",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert my_poll["buttons"][0][1] == 5


@pytest.mark.asyncio
async def test_vote_weights_trim_grist_names(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    router_app_context.stellar_service.get_balances.return_value = ({}, [{"key": "G1", "weight": 4}])
    router_app_context.stellar_service.address_id_to_username.return_value = " @user "

    update = types.Update(
        update_id=192,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.TestGroup, type="supergroup"),
            from_user=types.User(id=84131737, is_bot=False, first_name="Admin", username="admin"),
            text="/poll_reload_vote",
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    weights = router_app_context.voting_service.get_all_vote_weights()
    assert weights[chat_to_address[MTLChats.TestGroup]]["@user"] == 4


# --- Review round 16: group origins, harmless links, long voter lists -------------


@pytest.mark.asyncio
async def test_poll_recount_ignores_plain_channel_link_in_comment(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = _seed_poll(router_app_context)
    _seed_weights(router_app_context)

    # A link to a channel (no message id) is just a comment, so the forwarded reply is used.
    update = _recount_update(201, text="/poll_recount см. правила t.me/my_rules_channel")
    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert my_poll["buttons"][0][1] == 5


@pytest.mark.asyncio
async def test_poll_recount_truncates_huge_voter_list(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    voters = [f"@longusername_{i:03d}_x" for i in range(200)]
    my_poll = {
        "question": "Q?",
        "closed": False,
        "message_id": POLL_MESSAGE_ID,
        "buttons": [["A", 0, voters]],
    }
    router_app_context.poll_service._polls[(CHANNEL_ID, POLL_MESSAGE_ID)] = my_poll
    _seed_weights(router_app_context)

    await dp.feed_update(bot=router_app_context.bot, update=_recount_update(202))

    edits = _chat_message_bodies(mock_telegram.get_requests(), CHANNEL_ID, "editMessageText")
    assert edits
    assert "+" in edits[0]["text"]
    assert len(edits[0]["text"]) < 3500


# --- Review round 18: callback indices, long options, UTF-16 entities -------------


@pytest.mark.asyncio
async def test_poll_recount_keeps_callback_indexes_for_broken_entries(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.callback_query.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = {
        "question": "Q?",
        "closed": False,
        "message_id": POLL_MESSAGE_ID,
        "buttons": [["A", 5, ["@user"]], "broken", ["B", 0, []]],
    }
    router_app_context.poll_service._polls[(CHANNEL_ID, POLL_MESSAGE_ID)] = my_poll
    _seed_weights(router_app_context)

    await dp.feed_update(bot=router_app_context.bot, update=_recount_update(210))

    edits = _chat_message_bodies(mock_telegram.get_requests(), CHANNEL_ID, "editMessageText")
    assert edits
    keyboard = json.loads(edits[0]["reply_markup"]) if isinstance(edits[0]["reply_markup"], str) else None
    assert keyboard is not None
    # The second rendered button must still point to the third stored option.
    assert keyboard["inline_keyboard"][1][0]["callback_data"] == PollCallbackData(answer=2).pack()

    # Clicking it must hit option B, not the broken entry.
    await dp.feed_update(bot=router_app_context.bot, update=_click_update(211))
    assert "B" in my_poll["buttons"][2][0]


@pytest.mark.asyncio
async def test_poll_command_truncates_long_option_text(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.stellar_service.get_balances.return_value = ({}, [{"key": "G1", "weight": 1}])
    router_app_context.stellar_service.address_id_to_username.return_value = "@user"

    long_option = "Очень длинный вариант ответа, который не влезает в кнопку Телеграма целиком"
    poll_msg = types.Message(
        message_id=1,
        date=datetime.datetime.now(),
        chat=types.Chat(id=MTLChats.TestGroup, type="supergroup"),
        from_user=types.User(id=999, is_bot=False, first_name="Admin"),
        poll=types.Poll(
            id="p1",
            question="Q?",
            options=[types.PollOption(persistent_id="pid_A", text=long_option, voter_count=0)],
            total_voter_count=0,
            is_closed=False,
            is_anonymous=True,
            type="regular",
            allows_multiple_answers=False,
            allows_revoting=False,
            members_only=False,
        ),
    )
    update = types.Update(
        update_id=212,
        message=types.Message(
            message_id=2,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.TestGroup, type="supergroup"),
            from_user=types.User(id=999, is_bot=False, first_name="Admin"),
            text="/poll",
            reply_to_message=poll_msg,
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    bodies = _chat_message_bodies(mock_telegram.get_requests(), MTLChats.TestGroup)
    assert bodies
    markup = json.loads(bodies[0]["reply_markup"])
    button_text = markup["inline_keyboard"][0][0]["text"]
    assert len(button_text) <= 64
    assert button_text.endswith("(0)")


@pytest.mark.asyncio
async def test_poll_recount_url_entity_after_emoji(mock_telegram, router_app_context):
    dp = router_app_context.dispatcher
    dp.message.middleware(RouterTestMiddleware(router_app_context))
    dp.include_router(polls_router)

    router_app_context.admin_service.set_skynet_admins(["@admin"])
    my_poll = _seed_poll(router_app_context, message_id=42)
    _seed_weights(router_app_context)

    url = "https://t.me/c/1649743884/42"
    prefix = "/poll_recount 📊 "
    # Telegram counts offsets in UTF-16 code units, the emoji takes two of them.
    update = types.Update(
        update_id=213,
        message=types.Message(
            message_id=30,
            date=datetime.datetime.now(),
            chat=types.Chat(id=MTLChats.ITolstov, type="private"),
            from_user=types.User(id=84131737, is_bot=False, first_name="Admin", username="admin"),
            text=prefix + url,
            entities=[
                types.MessageEntity(
                    type="url",
                    offset=len(prefix.encode("utf-16-le")) // 2,
                    length=len(url),
                )
            ],
        ),
    )

    await dp.feed_update(bot=router_app_context.bot, update=update)

    assert my_poll["buttons"][0][1] == 5
