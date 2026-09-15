from types import SimpleNamespace

import pytest

from other.grist_tools import GristAPI, MTLGrist
from other.web_tools import HTTPSessionManager
from services.mtl_admins_sync_service import MtlAdminsSyncService


@pytest.fixture
async def mtl_grist_api(mock_grist, grist_server_config, monkeypatch):
    base_url = f"{grist_server_config['url']}/api/docs"
    for table in (
        MTLGrist.MTL_ADMINS,
        MTLGrist.MTL_ADMINS_MEDIA,
        MTLGrist.MTL_ADMINS_AGORA_TEAM,
        MTLGrist.MTL_ADMINS_AGORA_TOPICS,
    ):
        monkeypatch.setattr(table, "base_url", base_url)

    api = GristAPI(HTTPSessionManager())
    yield api
    await api.session_manager.close()


def add_grist_rows(mock_grist, table, rows):
    records = []
    for row in rows:
        fields = dict(row)
        record_id = fields.pop("id")
        records.append({"id": record_id, "fields": fields})
    mock_grist.add_records(table.table_name, records)


def grist_fields_by_id(mock_grist, table):
    return {row["id"]: row["fields"] for row in mock_grist.records.get(table.table_name, [])}


def telegram_admin(username, status="administrator", user_id=1):
    result = {
        "status": status,
        "user": {"id": user_id, "is_bot": False, "first_name": f"User{user_id}"},
    }
    if username is not None:
        result["user"]["username"] = username
    if status == "administrator":
        result.update(
            {
                "can_be_edited": False,
                "is_anonymous": False,
                "can_manage_chat": True,
                "can_delete_messages": False,
                "can_manage_video_chats": False,
                "can_restrict_members": False,
                "can_promote_members": False,
                "can_change_info": False,
                "can_invite_users": False,
                "can_post_stories": False,
                "can_edit_stories": False,
                "can_delete_stories": False,
                "can_send_welcome_messages": False,
            }
        )
    else:
        result["is_anonymous"] = False
    return result


def telegram_admins_response(*admins):
    return {"ok": True, "result": list(admins)}


def test_resolve_media_target_uses_tgid_only_and_ignores_url():
    service = MtlAdminsSyncService()
    media = {"id": 1, "Name": "Chat", "TgId": -1001, "Url": "https://t.me/other", "Invite": "https://t.me/+x"}

    target, issue = service.resolve_media_target(media)

    assert target == -1001
    assert issue is None


def test_resolve_media_target_reports_missing_tgid_even_with_url():
    service = MtlAdminsSyncService()
    media = {"id": 2, "Name": "Chat", "TgId": None, "Url": "https://t.me/public"}

    target, issue = service.resolve_media_target(media)

    assert target is None
    assert issue is not None
    assert issue.kind == "missing_tgid"


@pytest.mark.asyncio
async def test_sync_patches_full_owner_and_admin_reference_lists(
    mock_grist, mock_telegram, router_app_context, mtl_grist_api
):
    add_grist_rows(
        mock_grist, MTLGrist.MTL_ADMINS_MEDIA, [{"id": 10, "Name": "Chat", "Platform": "Telegram", "TgId": -10010}]
    )
    add_grist_rows(
        mock_grist,
        MTLGrist.MTL_ADMINS,
        [
            {"id": 1, "Username": "@owner", "As_Owner": ["L", 99], "As_Admin": ["L", 88]},
            {"id": 2, "Username": "@admin", "As_Owner": ["L", 77], "As_Admin": ["L", 66]},
        ],
    )
    mock_telegram.add_response(
        "getChatAdministrators",
        telegram_admins_response(telegram_admin("owner", "creator"), telegram_admin("admin", "administrator")),
    )

    result = await MtlAdminsSyncService(grist_manager=mtl_grist_api).sync(router_app_context.bot)

    admins = grist_fields_by_id(mock_grist, MTLGrist.MTL_ADMINS)
    assert result.created == 0
    assert admins[1]["As_Owner"] == ["L", 10]
    assert admins[1]["As_Admin"] == ["L"]
    assert admins[1]["Up_to_Date"] is True
    assert admins[2]["As_Owner"] == ["L"]
    assert admins[2]["As_Admin"] == ["L", 10]
    assert admins[2]["Up_to_Date"] is True


@pytest.mark.asyncio
async def test_sync_creates_missing_admin_record_before_patch(
    mock_grist, mock_telegram, router_app_context, mtl_grist_api
):
    add_grist_rows(
        mock_grist, MTLGrist.MTL_ADMINS_MEDIA, [{"id": 10, "Name": "Chat", "Platform": "Telegram", "TgId": -10010}]
    )
    mock_telegram.add_response(
        "getChatAdministrators",
        telegram_admins_response(telegram_admin("new_admin", "administrator")),
    )

    result = await MtlAdminsSyncService(grist_manager=mtl_grist_api).sync(router_app_context.bot)

    admins = list(grist_fields_by_id(mock_grist, MTLGrist.MTL_ADMINS).values())
    created = next(row for row in admins if row["Username"] == "@new_admin")
    assert result.created == 1
    assert created["As_Admin"] == ["L", 10]
    assert created["Up_to_Date"] is True


@pytest.mark.asyncio
async def test_sync_reports_admin_without_username(mock_grist, mock_telegram, router_app_context, mtl_grist_api):
    add_grist_rows(
        mock_grist, MTLGrist.MTL_ADMINS_MEDIA, [{"id": 10, "Name": "Chat", "Platform": "Telegram", "TgId": -10010}]
    )
    mock_telegram.add_response(
        "getChatAdministrators",
        telegram_admins_response(telegram_admin(None, "administrator", user_id=42)),
    )

    result = await MtlAdminsSyncService(grist_manager=mtl_grist_api).sync(router_app_context.bot)

    assert any(issue.kind == "admin_without_username" and "42" in issue.detail for issue in result.issues)
    assert mock_grist.records.get(MTLGrist.MTL_ADMINS.table_name, []) == []


@pytest.mark.asyncio
async def test_sync_collects_topic_admins_into_agora_team_topics_from_skynet(
    mock_grist, router_app_context, mtl_grist_api
):
    add_grist_rows(mock_grist, MTLGrist.MTL_ADMINS, [{"id": 1, "Username": "@topicadmin"}])
    add_grist_rows(
        mock_grist,
        MTLGrist.MTL_ADMINS_AGORA_TOPICS,
        [{"id": 100, "Name": "Topic", "Topic_Id": 777, "Link": "https://t.me/c/1/777"}],
    )
    admin_service = SimpleNamespace(get_all_topic_admins=lambda: {"-1001-777": ["@topicadmin"]})

    result = await MtlAdminsSyncService(grist_manager=mtl_grist_api).sync(
        router_app_context.bot, admin_service=admin_service
    )

    assert result.team_created == 1
    assert list(grist_fields_by_id(mock_grist, MTLGrist.MTL_ADMINS_AGORA_TEAM).values()) == [
        {"Username": 1, "Topics_From_SkyNet": ["L", 100]}
    ]


@pytest.mark.asyncio
async def test_sync_reports_missing_agora_topic(mock_grist, router_app_context, mtl_grist_api):
    add_grist_rows(mock_grist, MTLGrist.MTL_ADMINS, [{"id": 1, "Username": "@topicadmin"}])
    admin_service = SimpleNamespace(get_all_topic_admins=lambda: {"-1001-777": ["@topicadmin"]})

    result = await MtlAdminsSyncService(grist_manager=mtl_grist_api).sync(
        router_app_context.bot, admin_service=admin_service
    )

    assert any(issue.kind == "missing_agora_topic" and "777" in issue.detail for issue in result.issues)
    assert mock_grist.records.get(MTLGrist.MTL_ADMINS_AGORA_TEAM.table_name, []) == []


@pytest.mark.asyncio
async def test_sync_reports_duplicate_admin_records_without_creating_another(
    mock_grist, mock_telegram, router_app_context, mtl_grist_api
):
    add_grist_rows(
        mock_grist, MTLGrist.MTL_ADMINS_MEDIA, [{"id": 10, "Name": "Chat", "Platform": "Telegram", "TgId": -10010}]
    )
    add_grist_rows(
        mock_grist,
        MTLGrist.MTL_ADMINS,
        [{"id": 1, "Username": "@dup"}, {"id": 2, "Username": "dup"}],
    )
    mock_telegram.add_response(
        "getChatAdministrators",
        telegram_admins_response(telegram_admin("dup", "administrator")),
    )

    result = await MtlAdminsSyncService(grist_manager=mtl_grist_api).sync(router_app_context.bot)

    assert any(issue.kind == "duplicate_admin_record" and "@dup" in issue.detail for issue in result.issues)
    assert result.created == 0
    assert len(mock_grist.records[MTLGrist.MTL_ADMINS.table_name]) == 2
    assert not any(
        request["table"] == MTLGrist.MTL_ADMINS.table_name and request["method"] in {"POST", "PATCH"}
        for request in mock_grist.requests
    )


@pytest.mark.asyncio
async def test_sync_reports_duplicate_agora_team_rows_without_creating_another(
    mock_grist, router_app_context, mtl_grist_api
):
    add_grist_rows(mock_grist, MTLGrist.MTL_ADMINS, [{"id": 1, "Username": "@topicadmin"}])
    add_grist_rows(
        mock_grist,
        MTLGrist.MTL_ADMINS_AGORA_TOPICS,
        [{"id": 100, "Name": "Topic", "Topic_Id": 777, "Link": "https://t.me/c/1/777"}],
    )
    add_grist_rows(
        mock_grist,
        MTLGrist.MTL_ADMINS_AGORA_TEAM,
        [{"id": 11, "Username": 1}, {"id": 12, "Username": 1}],
    )
    admin_service = SimpleNamespace(get_all_topic_admins=lambda: {"-1001-777": ["@topicadmin"]})

    result = await MtlAdminsSyncService(grist_manager=mtl_grist_api).sync(
        router_app_context.bot, admin_service=admin_service
    )

    assert any(issue.kind == "duplicate_agora_team" and "Username=1" in issue.detail for issue in result.issues)
    assert result.team_created == 0
    assert len(mock_grist.records[MTLGrist.MTL_ADMINS_AGORA_TEAM.table_name]) == 2
    assert not any(
        request["table"] == MTLGrist.MTL_ADMINS_AGORA_TEAM.table_name and request["method"] in {"POST", "PATCH"}
        for request in mock_grist.requests
    )
