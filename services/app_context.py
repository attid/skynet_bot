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
from services.repositories.chats_repo_adapter import ChatsRepositoryAdapter
from services.channel_link_service import ChannelLinkService
from services.selfmod_service import SelfmodService
from services.stellar_notification_service import StellarNotificationService


class AppContext:
    def __init__(self):
        self.grist_service = None
        self.gspread_service = None
        self.web_service = None
        self.mtl_service = None
        self.stellar_service = None
        self.airdrop_service = None
        self.report_service = None
        self.antispam_service = None
        self.poll_service = None
        self.moderation_service = None
        self.ai_service = None
        self.talk_service = None
        self.group_service = None
        self.utils_service = None
        # DI-based services
        self.spam_status_service = None
        self.config_service = None
        self.feature_flags = None
        self.notification_service = None
        self.bot_state_service = None
        self.voting_service = None
        self.admin_service = None
        self.command_registry = None
        self.db_service = None
        self.channel_link_service = None
        self.selfmod_service = None
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
        ctx.spam_status_service = SpamStatusService(ChatsRepositoryAdapter(ctx.db_service.session_pool))
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
