# -*- coding: utf-8 -*-
"""God's Eye — userbot activation helper (owner tool, NOT imported by
the bot). After `python -m userbot.login`, run:

    python -m userbot.activate <username-or-user-id>

It looks the person up through the userbot layer and MERGES the results
into that person's existing dossier (creating it if needed), then sends
their profile photos to the owner through the bot as real photos —
never as links. With a forwarded message as the source, pass the
message's chat id and message id instead:

    python -m userbot.activate --message <chat_id> <message_id>

This is also exactly what the bot does automatically on every search
once config.USERBOT_ENABLED is True (the provider is registered in
providers.build_providers in that case).
"""
import asyncio
import json
import sys

sys.path.insert(0, ".")
import config  # noqa: E402
from botapi import BotApi  # noqa: E402
from db import Database  # noqa: E402
from userbot.queries import UserbotQueries  # noqa: E402


async def _run():
    args = sys.argv[1:]
    if not args:
        print("usage: python -m userbot.activate <username|user_id>")
        print("   or: python -m userbot.activate --message <chat_id> <msg_id>")
        return
    q = UserbotQueries()
    if not await q.connect():
        print("Userbot not active — fill userbot_config.py and run "
              "python -m userbot.login first.")
        return
    db = Database(config.DB_PATH)
    api = BotApi(config.BOT_TOKEN)
    ref, id_type, id_value = None, None, None
    if args[0] == "--message":
        chat_id, msg_id = int(args[1]), int(args[2])
        msgs = await q.client.get_messages(chat_id, ids=msg_id)
        ref = msgs[0] if msgs else None
        if ref is None:
            print("Message not found.")
            return
        id_type = "tgmsg"
        id_value = json.dumps({"chat_id": chat_id, "message_id": msg_id})
        user = await q.resolve_user(ref)
    else:
        raw = args[0]
        if raw.lstrip("-").isdigit():
            ref, id_type, id_value = int(raw), "telegram_id", raw
        else:
            ref, id_type, id_value = raw.lstrip("@"), "username", raw.lstrip("@")
        user = await q.resolve_user(ref)
    if user is None or getattr(user, "id", None) is None:
        print("Could not resolve that user.")
        await q.close()
        return
    person_id = await db.find_person_by_identifier(id_type, id_value)
    if person_id is None:
        person_id = await db.find_person_by_identifier(
            "telegram_id", str(user.id))
    if person_id is None:
        person_id = await db.create_person(
            label=(user.first_name or "") + " " + (user.last_name or ""))
        await db.add_identifier(person_id, id_type, id_value)
    if not any(i["type"] == "telegram_id" and i["value"] == str(user.id)
               for i in await db.list_identifiers(person_id)):
        await db.add_identifier(person_id, "telegram_id", str(user.id))
    search_id = await db.start_search(person_id)
    findings, photos = await q.full_user_info(ref)
    findings += await q.common_chats(ref)
    findings += await q.global_messages_from(ref)
    new = 0
    for f in findings:
        if await db.add_finding(person_id, search_id, f["source"],
                                f["category"], f.get("title"), f["value"],
                                f.get("snippet")):
            new += 1
    await db.finish_search(search_id)
    print(f"Dossier #{person_id}: {new} new finding(s) merged "
          f"({len(findings)} total from the userbot layer).")
    paths = await q.download_photos(user, [pid for pid, _ in photos])
    for path in paths:
        try:
            await api.send_photo(config.OWNER_ID, path,
                                 caption="عکس پروفایل — تلگرام (یوزربات)")
            print("photo sent:", path)
        except Exception as e:
            print("photo send failed:", path, e)
    await q.close()


if __name__ == "__main__":
    asyncio.run(_run())
