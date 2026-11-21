# -*- coding: utf-8 -*-
"""VM-side one-time login runner (Nova-operated, added 2026-11-10).

Same flow as login.py but driven through files so Nova can run it
non-interactively on this VM:
  - writes status lines to userbot/login_status.txt
  - waits for the code in userbot/login_code.txt (you relay it from
    his Telegram app; the file is deleted right after use)
  - if Telegram asks for the 2FA password, status shows NEED_2FA and
    the password is read from userbot/login_2fa.txt (also deleted)
The session StringSession is saved to SESSION_PATH + ".session_string"
with chmod 600, exactly like login.py.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from userbot import userbot_config as uc  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
STATUS = os.path.join(HERE, "login_status.txt")
CODEF = os.path.join(HERE, "login_code.txt")
PWDF = os.path.join(HERE, "login_2fa.txt")
PHONE = "YOUR_PHONE_NUMBER"

# This VM reaches Telegram MTProto only through its egress proxy as a
# SOCKS5 tunnel (direct MTProto gets corrupted by the middlebox — the
# same truncation family as the Binance/Bot-API issues). The Bot API
# (HTTPS) path works because it goes through the HTTP proxy.
import urllib.parse  # noqa: E402

_p = urllib.parse.urlparse(os.environ.get("https_proxy", ""))
PROXY = None
if _p.hostname:
    from python_socks import ProxyType as _PT  # python-socks package
    PROXY = dict(proxy_type=_PT.SOCKS5, addr=_p.hostname,
                 port=_p.port, username=_p.username,
                 password=_p.password, rdns=True)


def status(msg):
    with open(STATUS, "w", encoding="utf-8") as fh:
        fh.write(msg + "\n")
    print(msg, flush=True)


async def wait_file(path, timeout=600):
    for _ in range(timeout):
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                val = fh.read().strip()
            os.remove(path)
            if val:
                return val
        await asyncio.sleep(1)
    return None


async def main():
    if not uc.API_ID or not uc.API_HASH:
        status("NO_API: api_id/api_hash missing in userbot_config.py")
        return
    from telethon import TelegramClient
    from telethon.errors import SessionPasswordNeededError
    from telethon.sessions import StringSession

    sess_file = uc.SESSION_PATH + ".session_string"
    sess_abs = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), sess_file)
    string = ""
    if os.path.exists(sess_abs):
        with open(sess_abs, encoding="utf-8") as fh:
            string = fh.read().strip()
    client = TelegramClient(StringSession(string), uc.API_ID, uc.API_HASH,
                            proxy=PROXY)
    await client.connect()
    if await client.is_user_authorized():
        me = await client.get_me()
        status(f"ALREADY: logged in as {me.first_name} (@{me.username})")
        await client.disconnect()
        return
    sent = await client.send_code_request(PHONE)
    status("CODE_SENT: waiting for the login code in login_code.txt")
    code = await wait_file(CODEF)
    if not code:
        status("TIMEOUT: no code received")
        await client.disconnect()
        return
    try:
        await client.sign_in(phone=PHONE, code=code,
                             phone_code_hash=sent.phone_code_hash)
    except SessionPasswordNeededError:
        status("NEED_2FA: waiting for the password in login_2fa.txt")
        pwd = await wait_file(PWDF)
        if not pwd:
            status("TIMEOUT: no 2FA password received")
            await client.disconnect()
            return
        await client.sign_in(password=pwd)
    os.makedirs(os.path.dirname(sess_abs) or ".", exist_ok=True)
    with open(sess_abs, "w", encoding="utf-8") as fh:
        fh.write(client.session.save())
    try:
        os.chmod(sess_abs, 0o600)
    except Exception:
        pass
    me = await client.get_me()
    status(f"OK: logged in as {me.first_name} (@{me.username}), id={me.id}")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
