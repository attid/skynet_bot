import pytest
import datetime
from aiogram import types

from routers.polls import router as polls_router, PollCallbackData, chat_to_address
from tests.conftest import RouterTestMiddleware
from other.constants import MTLChats
from other.stellar import MTLAddresses


@pytest.fixture(autouse=True)
async def cleanup_router():
    yield
    if polls_router.parent_router:
        polls_router._parent_router = None


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
