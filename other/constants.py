from enum import Enum

# Text constants
adv_text = ""  # Placeholder for advertisement text, used in miniapps_tools.py


class MTLChats:
    System = 0  # системный "чат" хранение всего подряд
    Poll = 1  # под опросы
    MTLA_Poll = -1  # под опросы MTLA
    Employment = -1001424237819  # чат поиска работы
    TestGroup = -1001767165598  # тестовая группа
    SignGroup = -1001239694752  # подписанты
    GuarantorGroup = -1001169382324  # Guarantors EURMTL
    DistributedGroup = -1001798357244  # distributed government
    ShareholderGroup = -1001269297637
    GroupAnonymousBot = 1087968824  # анонимный админ
    Channel_Bot = 136817688  # от всех каналов приходит с этим ID
    Telegram_Repost_Bot = 777000  # репост из канала в чат
    FARMGroup = -1001876391583
    LandLordGroup = -1001757912662
    SignGroupForChanel = -1001784614029
    USDMMGroup = -1001800264199
    ITolstov = 84131737
    Any = 191153115
    FCMGroup = -1001637378851
    MMWBGroup = -1001729647273
    FinGroup = -1001941169217
    EURMTLClubGroup = -1001707489173
    MonteliberoChanel = -1001009485608
    HelperChat = -1001466779498
    SpamGroup = -1002007280572
    CyberGroup = -1002079305671
    MTLAGroup = -1001892843127
    MTLAAgoraGroup = -1002032873651
    ClubFMCGroup = -1001777233595
    SerpicaGroup = -1001589557564
    BotsChanel = -1002263825546
    MTLIDGroup = -1001713504799  # MTL ID Group


class BotValueTypes(Enum):
    PinnedUrl = 1
    LastFondTransaction = 2
    LastDebtTransaction = 3
    PinnedId = 4
    LastEurTransaction = 5
    LastRectTransaction = 6
    LastMTLTransaction = 7
    LastMTLandTransaction = 8
    LastFarmTransaction = 9
    LastFCMTransaction = 10
    LastLedger = 11
    LastMMWBTransaction = 12
    LastUSDMFundTransaction = 13
    LastFINFundTransaction = 14
    SkynetAdmins = 15
    Votes = 16
    All = 17
    AutoAll = 18
    DeleteIncome = 19
    WelcomeMessage = 20
    WelcomeButton = 21
    ReplyOnly = 22
    Captcha = 23
    StopExchange = 24
    LastTFMFundTransaction = 25
    Listen = 26
    FullData = 27
    NoFirstLink = 28
    Admins = 29
    AlertMe = 30
    Sync = 31
    SkynetImg = 32
    NeedDecode = 33
    SaveLastMessageDate = 34
    LastMTLATransaction = 35
    NotifyJoin = 36
    NotifyMessage = 37
    JoinRequestCaptcha = 38
    FirstVote = 39
    LastTransaction = 40
    Moderate = 41
    TopicAdmins = 42
    TopicMutes = 43
    EntryChannel = 44
    Inaccessible = 45
    ChannelLinks = 46
    Selfmod = 47
    SelfmodActiveVotes = 48
    SelfmodWarnings = 49
