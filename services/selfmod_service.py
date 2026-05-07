"""Self-moderation service: vote-based join/mute/kick decisions.

Stores in-memory state of active votes and per-chat user warnings, with
persistence backed by ``DatabaseService`` (JSONB in ``bot_config``).

Vote thresholds use a scaled rule:
- Approve when ``yes >= max(3, 3 * no)``.
- Reject  when ``no  >= max(3, 3 * yes)``.

Warnings use a 90-day rolling window: timestamps older than the window are
ignored when computing escalation level (1 → 1d mute, 2 → 7d mute, 3+ → kick).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Literal, Optional

from other.constants import BotValueTypes


VoteKind = Literal["join", "mute", "kick"]
VoteOutcome = Literal["approve", "reject"]

WARNING_WINDOW_DAYS = 90
APPROVE_BASE = 3  # also serves as the multiplier on the opposing side
MUTE_LEVEL_DURATIONS = {
    1: timedelta(days=1),
    2: timedelta(days=7),
}
# Level >= 3 escalates to kick vote (no direct mute).


@dataclass
class VoteState:
    """Persistent state of a single active vote."""

    kind: VoteKind
    chat_id: int
    vote_msg_id: int
    target_user_id: int
    target_mention: str
    target_msg_id: Optional[int] = None  # for mute votes — the offending message
    yes_voters: list[int] = field(default_factory=list)
    no_voters: list[int] = field(default_factory=list)
    voter_mentions: dict[str, str] = field(default_factory=dict)  # str(user_id) -> mention
    started_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "chat_id": self.chat_id,
            "vote_msg_id": self.vote_msg_id,
            "target_user_id": self.target_user_id,
            "target_mention": self.target_mention,
            "target_msg_id": self.target_msg_id,
            "yes_voters": list(self.yes_voters),
            "no_voters": list(self.no_voters),
            "voter_mentions": dict(self.voter_mentions),
            "started_at": self.started_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "VoteState":
        return cls(
            kind=data["kind"],
            chat_id=int(data["chat_id"]),
            vote_msg_id=int(data["vote_msg_id"]),
            target_user_id=int(data["target_user_id"]),
            target_mention=data.get("target_mention", ""),
            target_msg_id=data.get("target_msg_id"),
            yes_voters=[int(u) for u in data.get("yes_voters", [])],
            no_voters=[int(u) for u in data.get("no_voters", [])],
            voter_mentions={str(k): str(v) for k, v in data.get("voter_mentions", {}).items()},
            started_at=data.get("started_at", ""),
        )

    def yes(self) -> int:
        return len(self.yes_voters)

    def no(self) -> int:
        return len(self.no_voters)

    def has_voted(self, user_id: int) -> bool:
        return user_id in self.yes_voters or user_id in self.no_voters


def _now() -> datetime:
    return datetime.now(timezone.utc)


def threshold_passed(yes: int, no: int) -> Optional[VoteOutcome]:
    """Return ``"approve"`` / ``"reject"`` once threshold is reached.

    The base requirement is 3 votes. When the opposing side already has votes,
    the requirement scales: e.g. 2 against → need 6 in favor (= 3 * 2).
    """
    if yes >= max(APPROVE_BASE, APPROVE_BASE * no):
        return "approve"
    if no >= max(APPROVE_BASE, APPROVE_BASE * yes):
        return "reject"
    return None


def mute_duration_for_level(level: int) -> Optional[timedelta]:
    """Return mute duration for warning level. ``None`` means escalate to kick."""
    return MUTE_LEVEL_DURATIONS.get(level)


@dataclass
class VoteResult:
    """Result of a single ``cast`` call."""

    state: VoteState
    outcome: Optional[VoteOutcome]
    already_voted: bool = False


class SelfmodService:
    """In-memory cache + DB-backed selfmod state.

    Persistence keys (per ``chat_id``):
    - ``BotValueTypes.SelfmodActiveVotes`` → JSON ``{vote_msg_id: VoteState dict}``.
    - ``BotValueTypes.SelfmodWarnings``    → JSON ``{user_id: [iso_ts, ...]}``.

    The service is intentionally agnostic of aiogram. Routers wire it to
    Telegram I/O and the spam-chat event log.
    """

    def __init__(self, db_service: Any, *, now_fn: Any = None):
        self._db = db_service
        self._now_fn = now_fn or _now
        self._lock = Lock()
        self._votes: dict[tuple[int, int], VoteState] = {}
        self._warnings: dict[int, dict[int, list[str]]] = {}
        self._loaded_chats: set[int] = set()

    # ------------------------------------------------------------------
    # Loading / persistence
    # ------------------------------------------------------------------

    async def _ensure_loaded(self, chat_id: int) -> None:
        """Load state for a chat from DB on first access (idempotent)."""
        with self._lock:
            if chat_id in self._loaded_chats:
                return

        votes_raw = await self._db.load_bot_value(chat_id, BotValueTypes.SelfmodActiveVotes, "")
        warnings_raw = await self._db.load_bot_value(chat_id, BotValueTypes.SelfmodWarnings, "")

        votes_map: dict[int, dict[str, Any]] = {}
        if votes_raw:
            try:
                parsed = json.loads(votes_raw) if isinstance(votes_raw, str) else votes_raw
                if isinstance(parsed, dict):
                    votes_map = {int(k): v for k, v in parsed.items()}
            except (json.JSONDecodeError, ValueError, TypeError):
                votes_map = {}

        warnings_map: dict[int, list[str]] = {}
        if warnings_raw:
            try:
                parsed = json.loads(warnings_raw) if isinstance(warnings_raw, str) else warnings_raw
                if isinstance(parsed, dict):
                    warnings_map = {int(k): list(v) for k, v in parsed.items()}
            except (json.JSONDecodeError, ValueError, TypeError):
                warnings_map = {}

        with self._lock:
            for vote_msg_id, vote_dict in votes_map.items():
                try:
                    self._votes[(chat_id, vote_msg_id)] = VoteState.from_dict(vote_dict)
                except (KeyError, ValueError, TypeError):
                    continue
            self._warnings[chat_id] = warnings_map
            self._loaded_chats.add(chat_id)

    async def _persist_votes(self, chat_id: int) -> None:
        with self._lock:
            chat_votes = {
                str(msg_id): state.to_dict() for (cid, msg_id), state in self._votes.items() if cid == chat_id
            }
        await self._db.save_bot_value(
            chat_id, BotValueTypes.SelfmodActiveVotes, json.dumps(chat_votes) if chat_votes else None
        )

    async def _persist_warnings(self, chat_id: int) -> None:
        with self._lock:
            chat_warnings = {str(uid): list(ts) for uid, ts in self._warnings.get(chat_id, {}).items() if ts}
        await self._db.save_bot_value(
            chat_id, BotValueTypes.SelfmodWarnings, json.dumps(chat_warnings) if chat_warnings else None
        )

    # ------------------------------------------------------------------
    # Vote lifecycle
    # ------------------------------------------------------------------

    async def start_vote(
        self,
        kind: VoteKind,
        chat_id: int,
        vote_msg_id: int,
        target_user_id: int,
        target_mention: str,
        target_msg_id: Optional[int] = None,
    ) -> VoteState:
        await self._ensure_loaded(chat_id)
        state = VoteState(
            kind=kind,
            chat_id=chat_id,
            vote_msg_id=vote_msg_id,
            target_user_id=target_user_id,
            target_mention=target_mention,
            target_msg_id=target_msg_id,
            started_at=self._now_fn().isoformat(),
        )
        with self._lock:
            self._votes[(chat_id, vote_msg_id)] = state
        await self._persist_votes(chat_id)
        return state

    def get_vote(self, chat_id: int, vote_msg_id: int) -> Optional[VoteState]:
        with self._lock:
            return self._votes.get((chat_id, vote_msg_id))

    def has_active_mute_vote(self, chat_id: int, target_user_id: int) -> bool:
        """True if there's already an open mute/kick vote against this user."""
        with self._lock:
            for (cid, _), st in self._votes.items():
                if cid == chat_id and st.target_user_id == target_user_id and st.kind in ("mute", "kick"):
                    return True
        return False

    async def cast(
        self,
        chat_id: int,
        vote_msg_id: int,
        voter_id: int,
        voter_mention: str,
        choice: bool,
    ) -> Optional[VoteResult]:
        """Record a vote. Returns ``None`` if the vote does not exist."""
        await self._ensure_loaded(chat_id)
        with self._lock:
            state = self._votes.get((chat_id, vote_msg_id))
            if state is None:
                return None
            if state.has_voted(voter_id):
                return VoteResult(state=state, outcome=None, already_voted=True)
            (state.yes_voters if choice else state.no_voters).append(voter_id)
            state.voter_mentions[str(voter_id)] = voter_mention
            outcome = threshold_passed(state.yes(), state.no())

        await self._persist_votes(chat_id)
        return VoteResult(state=state, outcome=outcome, already_voted=False)

    async def close_vote(self, chat_id: int, vote_msg_id: int) -> None:
        with self._lock:
            self._votes.pop((chat_id, vote_msg_id), None)
        await self._persist_votes(chat_id)

    # ------------------------------------------------------------------
    # Warnings (90-day rolling)
    # ------------------------------------------------------------------

    def _filter_window(self, timestamps: list[str]) -> list[str]:
        cutoff = self._now_fn() - timedelta(days=WARNING_WINDOW_DAYS)
        kept: list[str] = []
        for ts in timestamps:
            try:
                dt = datetime.fromisoformat(ts)
            except ValueError:
                continue
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt >= cutoff:
                kept.append(ts)
        return kept

    async def get_warnings(self, chat_id: int, user_id: int) -> int:
        await self._ensure_loaded(chat_id)
        with self._lock:
            stored = list(self._warnings.get(chat_id, {}).get(user_id, []))
        return len(self._filter_window(stored))

    async def add_warning(self, chat_id: int, user_id: int) -> int:
        """Append a warning for the user. Returns the new in-window count."""
        await self._ensure_loaded(chat_id)
        ts = self._now_fn().isoformat()
        with self._lock:
            bucket = self._warnings.setdefault(chat_id, {}).setdefault(user_id, [])
            bucket.append(ts)
            kept = self._filter_window(bucket)
            self._warnings[chat_id][user_id] = kept
            level = len(kept)
        await self._persist_warnings(chat_id)
        return level

    async def reset_warnings(self, chat_id: int, user_id: int) -> None:
        await self._ensure_loaded(chat_id)
        with self._lock:
            chat_bucket = self._warnings.get(chat_id, {})
            chat_bucket.pop(user_id, None)
        await self._persist_warnings(chat_id)

    async def list_warnings(self, chat_id: int) -> dict[int, int]:
        """Return ``{user_id: in_window_count}`` for users with active warnings."""
        await self._ensure_loaded(chat_id)
        with self._lock:
            stored = {uid: list(ts) for uid, ts in self._warnings.get(chat_id, {}).items()}
        return {uid: len(self._filter_window(ts)) for uid, ts in stored.items() if self._filter_window(ts)}
