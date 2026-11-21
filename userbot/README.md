# God's Eye Userbot Layer — Activation Guide

This layer works behind the current bot (the bot stays as the front end) and adds three searches that are not possible with a bot token:

1. **The person's messages in public groups** — from one of their messages (for example, a message forwarded to the bot), all of their messages in public groups and channels are found.
2. **Common chats** — groups and channels that both your account and that person are members of. That is the ceiling: only chats shared with your own account; other people's private groups and private chats are not visible.
3. **Full user info + profile photo history** — bio, common-chat count, personal channel, and all previous and current profile photos. Photos are downloaded as files and the bot sends them as real photos; it never sends a link.

## Activation (One Time)

1. Log in at https://my.telegram.org → "API development tools" → create an app and take the **api_id** and **api_hash**.
2. Put those two values in the file `userbot/userbot_config.py` in place of `API_ID` and `API_HASH`. Keep this file private; the api_hash is a credential — do not send it in chat.
3. Log in once (the Telegram login code is entered in the same terminal, never in chat):

       python -m userbot.login

4. In `config.py`, set `USERBOT_ENABLED = True` and restart the bot. From then on, in every search the userbot layer also runs automatically and its findings are stored in the same dossiers.

## Manual Use (Without the Bot)

    python -m userbot.activate @username
    python -m userbot.activate 123456789
    python -m userbot.activate --message <chat_id> <message_id>

The result is merged into that person's dossier and their profile photos are sent to you.

## Ceilings (Honest)

- Global search only sees **public** groups and channels.
- Without an api_id/api_hash this layer is completely off and the bot works exactly as before.
- Login is done only with your own account; the session stays in a private local file.
