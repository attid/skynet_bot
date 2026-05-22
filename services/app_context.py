from services.external_services import (
    GristService,
    GSpreadService,
    WebService,
    MtlService,
    StellarService,
    AirdropService,
    ReportService,
    AntispamService,
    PollService,
    ModerationService,
    AIService,
    TalkService,
    GroupService,
    UtilsService,
)
from services.spam_status_service import SpamStatusService
from services.config_service import ConfigService
from services.feature_flags import FeatureFlagsService
from services.notification_service import NotificationService
from services.bot_state_service import BotStateService
from services.voting_service import VotingService
from services.admin_service import AdminManagementService
from services.command_registry_service import CommandRegistryService
from services.database_service import DatabaseService
from services.channel_link_service import ChannelLinkService
from services.selfmod_service import SelfmodService
from services.stellar_notification_service import StellarNotificationService


from typing import Any, cast


class AppContext:
    grist_service: GristService
    gspread_service: GSpreadService
    web_service: WebService
    mtl_service: MtlService
    stellar_service: StellarService
    airdrop_service: AirdropService
    report_service: ReportService
    antispam_service: AntispamService
    poll_service: PollService
    moderation_service: ModerationService
    ai_service: AIService
    talk_service: TalkService
    group_service: GroupService
    utils_service: UtilsService
    spam_status_service: SpamStatusService
    config_service: ConfigService
    feature_flags: FeatureFlagsService
    notification_service: NotificationService
    bot_state_service: BotStateService
    voting_service: VotingService
    admin_service: AdminManagementService
    command_registry: CommandRegistryService
    db_service: DatabaseService
    channel_link_service: ChannelLinkService
    selfmod_service: SelfmodService
    stellar_notification_service: StellarNotificationService | None
    message_thread_cache_service: Any

    def __init__(self):
        self.grist_service = cast(GristService, None)
        self.gspread_service = cast(GSpreadService, None)
        self.web_service = cast(WebService, None)
        self.mtl_service = cast(MtlService, None)
        self.stellar_service = cast(StellarService, None)
        self.airdrop_service = cast(AirdropService, None)
        self.report_service = cast(ReportService, None)
        self.antispam_service = cast(AntispamService, None)
        self.poll_service = cast(PollService, None)
        self.moderation_service = cast(ModerationService, None)
        self.ai_service = cast(AIService, None)
        self.talk_service = cast(TalkService, None)
        self.group_service = cast(GroupService, None)
        self.utils_service = cast(UtilsService, None)
        # DI-based services
        self.spam_status_service = cast(SpamStatusService, None)
        self.config_service = cast(ConfigService, None)
        self.feature_flags = cast(FeatureFlagsService, None)
        self.notification_service = cast(NotificationService, None)
        self.bot_state_service = cast(BotStateService, None)
        self.voting_service = cast(VotingService, None)
        self.admin_service = cast(AdminManagementService, None)
        self.command_registry = cast(CommandRegistryService, None)
        self.db_service = cast(DatabaseService, None)
        self.channel_link_service = cast(ChannelLinkService, None)
        self.selfmod_service = cast(SelfmodService, None)
        self.stellar_notification_service = None
        self.message_thread_cache_service = None

    def check_user(self, user_id: int):
        """Check user status for antispam. Uses spam_status_service cache."""
        from shared.domain.user import SpamStatus

        if not self.spam_status_service:
            return SpamStatus.NEW
        return self.spam_status_service.get_status(user_id)

    @classmethod
    def from_bot(cls, bot):
        """Create AppContext with all services. Created once at startup."""
        ctx = cls()
        ctx.grist_service = GristService()
        ctx.gspread_service = GSpreadService()
        ctx.web_service = WebService()
        ctx.mtl_service = MtlService()
        ctx.stellar_service = StellarService()
        ctx.airdrop_service = AirdropService()
        ctx.report_service = ReportService()
        ctx.antispam_service = AntispamService()
        ctx.poll_service = PollService()
        ctx.moderation_service = ModerationService()
        ctx.ai_service = AIService()
        ctx.talk_service = TalkService(bot)
        ctx.group_service = GroupService()
        ctx.utils_service = UtilsService()

        # Services with in-memory state (no DB access needed)
        ctx.config_service = ConfigService()
        ctx.feature_flags = FeatureFlagsService(ctx.config_service)
        ctx.bot_state_service = BotStateService()
        ctx.voting_service = VotingService()
        ctx.admin_service = AdminManagementService()
        ctx.notification_service = NotificationService()
        ctx.command_registry = CommandRegistryService()
        ctx.db_service = DatabaseService()
        ctx.spam_status_service = SpamStatusService()
        ctx.channel_link_service = ChannelLinkService()
        ctx.selfmod_service = SelfmodService(ctx.db_service)
        # stellar_notification_service is initialized later in start.py
        # when session_pool is available

        return ctx

    def init_stellar_notification_service(self, bot, session_pool):
        """Initialize stellar notification service with bot and session pool.

        Called from start.py after session_pool is created.
        """
        from other.config_reader import config

        if config.notifier_url:
            self.stellar_notification_service = StellarNotificationService(bot, session_pool)


# Singleton instance for backwards compatibility
# Used by modules that need app_context at import time
# New code should receive app_context through dependency injection
app_context: AppContext = AppContext()
