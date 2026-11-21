# -*- coding: utf-8 -*-
"""God's Eye — userbot layer configuration.

Hardcoded values (no environment variables).

ACTIVATION: get API_ID / API_HASH from https://my.telegram.org
(«API development tools») for your OWN account and paste them below.
Keep this file private: the api_hash is a credential — never post it,
never put it in chat, never commit it to a public place. The login CODE
Telegram sends at first sign-in is entered in the terminal prompt of
userbot/login.py, never in chat.
"""

API_ID = 0  # get it from https://my.telegram.org and put it here
API_HASH = "YOUR_API_HASH"  # get it from https://my.telegram.org and put it here

SESSION_PATH = "userbot/godseye_user"   # Telethon session file (no ext)
                                        # — created by the one-time login

MAX_GLOBAL_RESULTS = 300    # scan budget: messages examined per lookup
GROUP_SAMPLE_PER_CHAT = 3   # sample messages kept per public group in
                            # the "active in" rollup
ANALYSIS_ENABLED = True     # local, deterministic analysis of the
                            # sampled messages (hours, topics, replies,
                            # reactions...) — 100% on-device, NO AI,
                            # NO external calls, ever
MEDIA_PHOTOS_MAX = 10       # cap on photos the target posted in public
                            # groups that get downloaded per lookup
                            # (sent to the owner as real photos)
TOP_WORDS_COUNT = 15        # words shown in the top-words analysis
CHANNEL_POSTS_MAX = 100     # posts crawled from the person's own
                            # personal channel per lookup
MAX_COMMON_CHATS = 50       # cap on common chats listed per person
MAX_PHOTOS_SENT = 10        # profile-photo history cap per person
PHOTO_DOWNLOAD_DIR = "userbot/photos"   # downloaded photos land here;
                                        # userbot_login/activate sends them
                                        # as real photos, never as links
REQUEST_TIMEOUT = 30        # seconds, per Telethon request

# Human pacing for the per-target crawl (userbot/membership.py):
# a short random pause before each chat crawl — read-only, unhurried,
# and any FloodWait aborts the crawl instantly with no retry.
PACE_MIN_SECONDS = 1.5
PACE_MAX_SECONDS = 3.5

# Optional HTTP proxy for the Telethon connection, as a Telethon proxy
# tuple ("http", host, port[, username, password]). None = direct.
# Needed where raw MTProto is blocked/mangled (Nova's VM egress);
# on your phone the direct route works, so it stays None there and
# this is only set in the VM's local copy.
PROXY = None
