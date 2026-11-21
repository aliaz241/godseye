# -*- coding: utf-8 -*-
"""God's Eye — userbot ONE-TIME interactive login (owner only).

Run this ONCE, in a terminal, after pasting API_ID / API_HASH into
userbot_config.py:

    python -m userbot.login

Telegram sends a login code to your Telegram app — type it at THIS
terminal prompt. The code is never typed in chat, never stored, and
never printed. On success the session is saved into
userbot_config.SESSION_PATH + ".session_string" (a private local file)
and the bot's userbot layer can connect silently from then on.

Run it again only if Telegram logs the session out (revoked session).
"""
import asyncio
import getpass
import os

from . import userbot_config as uc


async def _main():
    if not uc.API_ID or not uc.API_HASH:
        print("API_ID / API_HASH are empty in userbot/userbot_config.py —")
        print("get them from https://my.telegram.org (API development tools)")
        print("for your OWN account, paste them in, then run this again.")
        return
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    sess_file = uc.SESSION_PATH + ".session_string"
    string = ""
    if os.path.exists(sess_file):
        with open(sess_file, encoding="utf-8") as fh:
            string = fh.read().strip()
    client = TelegramClient(StringSession(string), uc.API_ID, uc.API_HASH)
    await client.connect()
    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"Already logged in as {me.first_name} (@{me.username}).")
        await client.disconnect()
        return
    phone = input("Phone number (international format, e.g. +98...): ").strip()
    sent = await client.send_code_request(phone)
    code = getpass.getpass("Login code Telegram sent you (hidden input): ").strip()
    try:
        await client.sign_in(phone=phone, code=code,
                             phone_code_hash=sent.phone_code_hash)
    except Exception as e:
        if "SessionPasswordNeeded" in type(e).__name__:
            pw = getpass.getpass("Two-step password (hidden input): ")
            await client.sign_in(password=pw)
        else:
            raise
    os.makedirs(os.path.dirname(sess_file) or ".", exist_ok=True)
    with open(sess_file, "w", encoding="utf-8") as fh:
        fh.write(client.session.save())
    try:
        os.chmod(sess_file, 0o600)
    except Exception:
        pass
    me = await client.get_me()
    print(f"Logged in as {me.first_name} (@{me.username}). Session saved.")
    print("The userbot layer is now active for the bot.")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(_main())
