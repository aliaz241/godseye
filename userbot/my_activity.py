# -*- coding: utf-8 -*-
"""My Activity — a personal, self-only Telegram overview.

Standalone tool. Shows YOU everything from YOUR OWN account in one
place: every group/channel/chat you're in, and — if you ask for it —
your own recent messages inside each one. It never takes a username,
user id, or forwarded message as input, and it never looks up anyone
else's data. There is no "target" parameter anywhere in this file.

It reuses the same login session created by `userbot/login.py` (so if
you've already run that once, this just works — no second login).

Run it from the project root:

    python -m userbot.my_activity

Options (edit the two constants below, or just run with no edits):
    INCLUDE_MESSAGES = True   -> also pulls your own recent messages
                                  per chat (slower, more detail)
    OUTPUT_FILE               -> if set, writes the report to this path
                                  as well as printing it
"""
import asyncio
import os
from datetime import datetime, timezone

from . import userbot_config as uc

# ---------------------------------------------------------------- options
INCLUDE_MESSAGES = True     # False = just the list of chats, fast
MESSAGES_PER_CHAT = 20      # how many of YOUR OWN recent messages to
                            # pull per chat when INCLUDE_MESSAGES=True
OUTPUT_FILE = "userbot/my_activity_report.txt"   # set to None to only print


def _fmt_date(dt):
    if dt is None:
        return "-"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


async def _own_recent_messages(client, me_id, dialog, limit):
    """Only messages whose sender is the logged-in account itself."""
    out = []
    try:
        async for msg in client.iter_messages(dialog.entity, limit=200,
                                               from_user=me_id):
            if not (msg.message or msg.media):
                continue
            text = (msg.message or "").strip().replace("\n", " ")
            out.append((msg.date, text[:140] if text else "[media]"))
            if len(out) >= limit:
                break
    except Exception as e:
        out.append((None, f"(could not read this chat: {e})"))
    return out


async def _main():
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    sess_file = uc.SESSION_PATH + ".session_string"
    if not os.path.exists(sess_file):
        print("No saved login found. Run `python -m userbot.login` first")
        print("(that's a one-time step for YOUR OWN account).")
        return
    with open(sess_file, encoding="utf-8") as fh:
        string = fh.read().strip()

    client = TelegramClient(StringSession(string), uc.API_ID, uc.API_HASH,
                             proxy=getattr(uc, "PROXY", None))
    await client.connect()
    if not await client.is_user_authorized():
        print("Session is no longer valid — run `python -m userbot.login` again.")
        await client.disconnect()
        return

    me = await client.get_me()
    lines = []
    lines.append(f"My Activity report for {me.first_name or ''} "
                 f"(@{me.username or me.id}) — {_fmt_date(datetime.now(timezone.utc))}")
    lines.append("=" * 60)

    count = 0
    async for dialog in client.iter_dialogs():
        count += 1
        kind = ("channel" if dialog.is_channel else
                "group" if dialog.is_group else
                "chat" if not dialog.is_user else "private")
        lines.append(f"\n[{count}] {dialog.name or '(no title)'}  "
                     f"({kind}, {dialog.unread_count} unread)")
        if dialog.entity and getattr(dialog.entity, "username", None):
            lines.append(f"    t.me/{dialog.entity.username}")

        if INCLUDE_MESSAGES and kind in ("channel", "group", "chat"):
            mine = await _own_recent_messages(client, me.id, dialog,
                                              MESSAGES_PER_CHAT)
            if mine:
                lines.append(f"    my last {len(mine)} message(s) here:")
                for dt, text in mine:
                    lines.append(f"      - {_fmt_date(dt)}: {text}")
            else:
                lines.append("    (no messages from me found here)")

    report = "\n".join(lines)
    print(report)
    if OUTPUT_FILE:
        os.makedirs(os.path.dirname(OUTPUT_FILE) or ".", exist_ok=True)
        with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
            fh.write(report)
        print(f"\n(also saved to {OUTPUT_FILE})")

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(_main())
