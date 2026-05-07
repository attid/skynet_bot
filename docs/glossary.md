# Glossary

## Core Terms

1. `SpamStatus`
- Domain status of a user in anti-spam logic.
- Example: `BAD` indicates user should be blocked in protected chats.

2. `Mute` (topic mute)
- In current design this means delete-only enforcement in topic context.
- It is not equivalent to Telegram restrict/ban.

3. `Restrict`
- Telegram permission limitation (`restrictChatMember`), usually temporary.

4. `Ban`
- Telegram removal/block (`banChatMember`) from chat.

5. `Unban`
- Telegram unblock (`unbanChatMember`) plus potential permissions restore.

6. `Moderation Artifact`
- Observable trace of moderation decision.
- Can be log entry, SpamGroup message, callback context, or admin notification.

7. `SpamGroup`
- Dedicated group (`MTLChats.SpamGroup`) used to publish moderation context and actions.

8. `BotsChanel`
- Service channel (`MTLChats.BotsChanel`) for bot-to-bot technical messages.

9. `MMWB ping/pong`
- Monitoring protocol messages in channel:
  - ping: `#mmwb #skynet command=ping`
  - pong: `#skynet #mmwb command=pong ...`

10. `Helper command event`
- Channel message produced by helper flow:
  - `#skynet #helper command=taken ...`
  - `#skynet #helper command=closed ...`

11. `ACK`
- Acknowledgement message generated after processing helper command.
- Example: `#skynet #helper command=ack status=ok ...`

12. `AppContext`
- Dependency container used across routers and middlewares.
- Main place to access services in runtime.

13. `Selfmod` (self-moderation)
- Per-chat feature flag enabling vote-based moderation without active admins.
- Replaces captcha when enabled; CAS/LOLS checks remain.

14. `Join vote`
- Selfmod vote on a new chat member: Accept/Reject buttons posted on join.
- Approve threshold: `yes ≥ max(3, 3 × no)`. Reject is symmetric. No timeout.

15. `Mute vote`
- Selfmod vote triggered by a 👾 reaction on any chat message.
- Approve applies an escalating mute (1 day → 7 days → kick vote at level 3+).

16. `Warning window`
- Rolling 90-day window over a user's mute approvals in a chat.
- Determines the next mute duration; old timestamps fall off automatically.
