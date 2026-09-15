"""In-memory daily ban counter per admin, used for the /ban easter egg."""

from datetime import date


class BanStatsService:
    """Tracks how many villains each admin banned today.

    State is kept in memory only and resets on process restart, which is
    acceptable for a cosmetic counter.
    """

    def __init__(self) -> None:
        self._bans_by_day: dict[int, tuple[date, int]] = {}

    def record_ban(self, admin_id: int, today: date | None = None) -> int:
        """Register a ban and return the admin's ban count for today including this one."""
        day = today or date.today()
        stored = self._bans_by_day.get(admin_id)
        count = stored[1] + 1 if stored and stored[0] == day else 1
        self._bans_by_day[admin_id] = (day, count)
        return count
