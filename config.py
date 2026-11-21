# -*- coding: utf-8 -*-
"""God's Eye (bot-only edition) — configuration.

Hardcoded values. This edition needs ONLY a bot
token — no api_id / api_hash, no user account.
"""

BOT_TOKEN = "YOUR_BOT_TOKEN"  # get your own bot token from @BotFather and put it here
OWNER_ID = 123456789  # your own numeric Telegram ID (get it from @userinfobot)
# Extra bot owners (the owner's order, 2026-11-11): the userbot SESSION
# account is also an owner of this bot, so it can use the bot itself.
OWNER_IDS = [123456789]  # numeric IDs of the owner(s) [YOUR_TELEGRAM_ID, YOUR_SECOND_ACCOUNT_ID]

DB_PATH = "godseye.db"

REQUEST_TIMEOUT = 8         # seconds, per HTTP call (v4.1: kept short so
                            # no single slow site can stall a search)
SEARCH_DEADLINE = 240       # seconds, overall budget for one identifier's
                            # full search; providers still running after
                            # this are abandoned and the dossier is
                            # delivered with what was found
POLL_TIMEOUT = 30           # seconds, long polling

USERBOT_ENABLED = True      # the userbot layer (deep Telegram search); set False if you have no session
                            # (userbot/userbot_config.py + userbot.login).
                            # While False — or while telethon is not
                            # installed — the userbot layer stays fully
                            # dormant and the bot behaves exactly as the
                            # bot-only edition always has.
