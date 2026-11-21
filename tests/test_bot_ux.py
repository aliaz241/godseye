# -*- coding: utf-8 -*-
"""Offline UX tests for the button-driven bot (recreated for v4; the
v3-era file was not preserved in the repo).

A FakeApi records every Bot API call; providers are replaced with a
stub so nothing touches the network. Covers: /start menu buttons,
plain-text identifier -> instant dossier + search, the step-by-step
new/add flows, person/info/search callbacks, delete with confirm, and
forward-based dossier creation.

Run:  ~/workspace/.venv_ge/bin/python tests/test_bot_ux.py
"""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config  # noqa: E402

FAILURES = []


def check(label, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + label + (f"  [{extra}]" if extra and not cond else ""))
    if not cond:
        FAILURES.append(label)


class FakeApi:
    def __init__(self):
        self.calls = []
        self._mid = 100

    async def send_message(self, chat_id, text, reply_to=None, reply_markup=None):
        self._mid += 1
        self.calls.append(("send", chat_id, text, reply_markup))
        return {"message_id": self._mid}

    async def edit_message(self, chat_id, message_id, text, reply_markup=None):
        self.calls.append(("edit", chat_id, text, reply_markup))
        return {"message_id": message_id}

    async def answer_callback_query(self, callback_query_id, text=None):
        self.calls.append(("answer", callback_query_id, text, None))
        return True

    async def get_chat(self, chat_id):
        return {}

    # settable by tests: the getUserProfilePhotos result to return
    profile_photos_result = {"total_count": 0, "photos": []}

    async def get_user_profile_photos(self, user_id, limit=None):
        self.calls.append(("profile_photos", user_id, limit, None))
        return self.profile_photos_result

    async def send_photo(self, chat_id, photo, caption=None):
        self._mid += 1
        self.calls.append(("photo", chat_id, photo, caption))
        return {"message_id": self._mid}

    def texts(self):
        return [c[2] for c in self.calls
                if c[0] in ("send", "edit") and isinstance(c[2], str)]

    def photo_calls(self):
        return [c for c in self.calls if c[0] == "photo"]

    def markups(self):
        out = []
        for c in self.calls:
            if c[0] not in ("send", "edit"):
                continue
            mk = c[3]
            if mk:
                for row in mk["inline_keyboard"]:
                    for b in row:
                        out.append(b["callback_data"])
        return out


class StubProvider:
    name = "stub"
    handles = ("username", "phone", "telegram_id")

    async def search(self, id_type, value):
        return [dict(source="stub", category="profile", title="Display name",
                     value=f"Stub {value}", snippet=None)]


async def main():
    import bot
    from db import Database
    from engine import Engine

    tmp = tempfile.mkdtemp()
    fake = FakeApi()
    bot.api = fake
    bot.db = Database(os.path.join(tmp, "test.db"))
    bot.engine = Engine(bot.db, fake)
    bot.engine.providers = [StubProvider()]
    bot.states.clear()

    owner = config.OWNER_ID
    chat = 555

    def msg(text=None, **kw):
        m = {"chat": {"id": chat}, "from": {"id": owner}}
        if text is not None:
            m["text"] = text
        m.update(kw)
        return m

    def cq(data, mid=42):
        return {"id": "q1", "from": {"id": owner}, "data": data,
                "message": {"chat": {"id": chat}, "message_id": mid}}

    # 1. /start shows the main menu buttons
    await bot.handle_message(msg("/start"))
    check("start: main menu buttons", {"new", "list", "help"} <= set(fake.markups()),
          str(fake.markups()))

    # 2. 'new' callback -> prompt -> plain identifier runs a dossier+search
    await bot.handle_callback(cq("new"))
    check("new flow: state awaiting identifier",
          bot.states.get(chat, {}).get("await") == "new")
    await bot.handle_message(msg("your_username"))
    persons = await bot.db.list_persons()
    check("new flow: dossier created", len(persons) == 1, str(persons))
    pid = persons[0]["id"]
    check("new flow: search finished message shown",
          any("جست‌وجو تمام شد" in t for t in fake.texts()))
    check("new flow: person keyboard attached",
          f"search:{pid}" in fake.markups())
    d = await bot.engine.dossier(pid)
    check("new flow: stub finding stored",
          any(f["source"] == "stub" for f in d["findings"]), str(d["findings"]))

    # 3. plain text with no active state = fresh identifier, instant dossier
    await bot.handle_message(msg("@second_user"))
    persons = await bot.db.list_persons()
    check("plain text: second dossier created", len(persons) == 2, str(persons))

    # 4. callbacks: person card / info / search / list
    await bot.handle_callback(cq(f"person:{pid}"))
    check("person callback: card edited", any("پرونده" in t for t in fake.texts()))
    await bot.handle_callback(cq(f"info:{pid}"))
    check("info callback: full dossier sent",
          any("یافته‌ها" in t for t in fake.texts()))
    await bot.handle_callback(cq(f"search:{pid}"))
    check("search callback: completes", any("جست‌وجو تمام شد" in t for t in fake.texts()))
    await bot.handle_callback(cq("list"))
    check("list callback: persons listed", any("پرونده‌های من" in t for t in fake.texts()))

    # 5. add flow: callback sets state, next message attaches identifier
    await bot.handle_callback(cq(f"add:{pid}"))
    check("add flow: state awaiting", bot.states.get(chat, {}).get("await") == "add")
    await bot.handle_message(msg("+989120000000"))
    d = await bot.engine.dossier(pid)
    check("add flow: phone identifier attached",
          any(i["type"] == "phone" for i in d["identifiers"]), str(d["identifiers"]))

    # 6. delete flow: confirm keyboard, then deletion
    await bot.handle_callback(cq(f"del:{pid}"))
    check("delete: confirm button offered", f"delyes:{pid}" in fake.markups())
    await bot.handle_callback(cq(f"delyes:{pid}"))
    check("delete: dossier removed", await bot.db.get_person(pid) is None)

    # 7. forward from a user auto-creates a dossier
    fwd = msg(forward_origin={"type": "user", "sender_user": {
        "id": 777001, "first_name": "Test", "last_name": "User",
        "username": "fwd_user"}})
    await bot.handle_message(fwd)
    found = await bot.db.find_person_by_identifier("telegram_id", "777001")
    check("forward: dossier auto-created", found is not None)

    # 8. v4.1: FIRST-ever message is a plain-text username (fresh chat,
    #    no /start ever sent) -> instant ack, live progress, dossier.
    chat2 = 777
    bot.states.pop(chat2, None)
    first_msg = {"chat": {"id": chat2}, "from": {"id": owner},
                 "text": "@first_user"}
    await bot.handle_message(first_msg)
    chat2_calls = [c for c in fake.calls if c[1] == chat2]
    check("first contact: very first reply is the instant ack",
          bool(chat2_calls) and chat2_calls[0][0] == "send"
          and "پرونده ساخته شد" in chat2_calls[0][2],
          str(chat2_calls[:1]))
    check("first contact: live per-provider progress was painted",
          any(c[0] == "edit" and "در حال بررسی منابع" in c[2] and "✓" in c[2]
              for c in chat2_calls),
          str([c[2] for c in chat2_calls if c[0] == "edit"][:2]))
    check("first contact: dossier finished without any /start",
          any("جست‌وجو تمام شد" in c[2] for c in chat2_calls))
    pid2 = await bot.db.find_person_by_identifier("username", "first_user")
    check("first contact: dossier exists", pid2 is not None)

    # 9. v4.1: /start mid-flow resets state and shows the main menu;
    #    same for the "Main Menu" (menu) callback.
    await bot.handle_callback(cq("new", mid=88))
    check("reset setup: flow state set",
          bot.states.get(chat, {}).get("await") == "new")
    n_calls = len(fake.calls)
    await bot.handle_message(msg("/start"))
    check("/start mid-flow: state cleared", chat not in bot.states)
    new_calls = fake.calls[n_calls:]
    check("/start mid-flow: main menu shown again",
          any(c[0] == "send" and "منوی" not in c[2] for c in new_calls)
          and {"new", "list", "help"} <= {
              b["callback_data"]
              for c in new_calls if c[3]
              for row in c[3]["inline_keyboard"] for b in row},
          str(new_calls))
    await bot.handle_callback(cq(f"add:{pid}", mid=89))
    check("menu reset setup: add state set",
          bot.states.get(chat, {}).get("await") == "add")
    await bot.handle_callback(cq("menu", mid=90))
    check("menu callback mid-flow: state cleared", chat not in bot.states)
    check("menu callback: welcome text + main keyboard",
          any(c[0] == "edit" and c[2] == bot.HELP for c in fake.calls))

    # 10. v4.1: no web-search provider is registered anywhere.
    import providers as _P
    _names = [p.name for p in _P.build_providers(None)]
    check("registry: no web / platform-search provider",
          "web" not in _names and "platforms" not in _names, str(_names))
    check("registry: exactly the direct social providers + telegram_user",
          set(_names) == {"telegram", "whatsapp", "eitaa", "rubika",
                          "bale", "soroush", "virasty", "profiles",
                          "telegram_user"},
          str(_names))
    check("registry: no non-social provider (github/gravatar/...)",
          not ({"github", "gitlab", "gravatar", "lichess", "chesscom",
                "keybase", "devto", "web"} & set(_names)), str(_names))
    check("sweep: og platforms are social-only",
          set(_P.OG_PROFILE_URLS) == {"twitch", "pinterest", "threads",
                                      "snapchat", "facebook", "aparat"},
          str(set(_P.OG_PROFILE_URLS)))

    # 11. non-owner is ignored completely
    before = len(fake.calls)
    stranger = {"chat": {"id": 999}, "from": {"id": 12345}, "text": "/start"}
    await bot.handle_message(stranger)
    check("non-owner: no API calls made", len(fake.calls) == before)

    # 12. v4.2: phone normalization — the local 09 form and the bare
    #     98 form both become the single canonical +98 form.
    from engine import guess_identifier
    check("phone norm: 09... -> +98 form",
          guess_identifier("09123456789") == ("phone", "+989123456789"),
          str(guess_identifier("09123456789")))
    check("phone norm: 98... -> +98 form",
          guess_identifier("989123456789") == ("phone", "+989123456789"))
    check("phone norm: +98 form unchanged",
          guess_identifier("+989123456789") == ("phone", "+989123456789"))

    # 13. v4.2: merge flow — adding an identifier that belongs to
    #     another dossier merges the two dossiers into one.
    await bot.handle_message(msg("@merge_a"))
    await bot.handle_message(msg("@merge_b"))
    pa = await bot.db.find_person_by_identifier("username", "merge_a")
    pb = await bot.db.find_person_by_identifier("username", "merge_b")
    check("merge setup: two separate dossiers",
          pa is not None and pb is not None and pa != pb)
    n_before = len(fake.calls)
    await bot.handle_callback(cq(f"add:{pa}"))
    await bot.handle_message(msg("merge_b"))
    check("merge: other dossier deleted",
          await bot.db.get_person(pb) is None)
    dm = await bot.engine.dossier(pa)
    check("merge: identifiers combined on target",
          {i["value"] for i in dm["identifiers"]} >= {"merge_a", "merge_b"},
          str(dm["identifiers"]))
    check("merge: findings combined on target",
          {f["value"] for f in dm["findings"]} >= {"Stub merge_a", "Stub merge_b"},
          str(dm["findings"]))
    check("merge: user told the dossiers merged",
          any("ادغام" in c[2] for c in fake.calls[n_before:]
              if isinstance(c[2], str)))

    # 14. v4.2: db.merge_persons direct unit test
    x = await bot.db.create_person("x")
    await bot.db.add_identifier(x, "username", "unit_x")
    y = await bot.db.create_person("y")
    await bot.db.add_identifier(y, "username", "unit_y")
    sid = await bot.db.start_search(y)
    await bot.db.add_finding(y, sid, "stub", "profile", "Display name",
                             "Stub unit_y")
    await bot.db.finish_search(sid)
    check("db merge: returns True", await bot.db.merge_persons(x, y) is True)
    check("db merge: source person gone", await bot.db.get_person(y) is None)
    dx = await bot.engine.dossier(x)
    check("db merge: identifiers moved",
          {i["value"] for i in dx["identifiers"]} == {"unit_x", "unit_y"},
          str(dx["identifiers"]))
    check("db merge: findings moved",
          any(f["value"] == "Stub unit_y" for f in dx["findings"]))
    check("db merge: self-merge is a no-op",
          await bot.db.merge_persons(x, x) is False
          and await bot.db.get_person(x) is not None)

    # 15. v4.2: attach outcome is reported concretely — which
    #     identifier was added, how many NEW findings and from which
    #     sources; a repeat attach says plainly nothing new was found.
    await bot.handle_message(msg("@outcome_user"))
    po = await bot.db.find_person_by_identifier("username", "outcome_user")
    n_before = len(fake.calls)
    await bot.handle_callback(cq(f"add:{po}"))
    await bot.handle_message(msg("+989121112233"))
    new_texts = [c[2] for c in fake.calls[n_before:] if isinstance(c[2], str)]
    check("outcome: ack names the added identifier",
          any("اضافه شد" in t and "+989121112233" in t for t in new_texts),
          str(new_texts))
    check("outcome: summary counts new findings with their source",
          any("یافته جدید از این منابع" in t and "stub" in t for t in new_texts),
          str(new_texts))
    n_before = len(fake.calls)
    await bot.handle_callback(cq(f"add:{po}"))
    await bot.handle_message(msg("+989121112233"))
    new_texts = [c[2] for c in fake.calls[n_before:] if isinstance(c[2], str)]
    check("outcome: repeat attach plainly reports nothing new",
          any("یافته جدیدی پیدا نشد" in t for t in new_texts), str(new_texts))

    # 16. v4.3: the dossier TEXT never contains a photo URL, even
    #     when photo findings exist for the person.
    pp = await bot.db.create_person("photo_person")
    await bot.db.add_identifier(pp, "username", "photo_user")
    sid = await bot.db.start_search(pp)
    await bot.db.add_finding(pp, sid, "instagram", "photo", "Profile photo",
                             "https://cdn.example.test/avatar123.jpg")
    await bot.db.add_finding(pp, sid, "instagram", "profile",
                             "Display name", "Photo User")
    await bot.db.finish_search(sid)
    dphoto = await bot.engine.dossier(pp)
    text = bot.format_dossier(dphoto)
    check("v4.3: dossier text contains no photo URL",
          "avatar123.jpg" not in text and "cdn.example.test" not in text,
          text)
    check("v4.3: dossier text still shows the real profile data",
          "Photo User" in text, text)
    card = await bot.person_card(pp)
    check("v4.3: person card does not leak the photo URL either",
          "cdn.example.test" not in card, card)

    # 17. v4.3: after a search that produced a photo finding, the bot
    #     SENDS the photo (caption names the platform) and no message
    #     text anywhere contains the photo URL.
    class PhotoStubProvider:
        name = "profiles"
        handles = ("username",)

        async def search(self, id_type, value):
            return [
                dict(source="instagram", category="profile",
                     title="Display name", value="Insta User", snippet=None),
                dict(source="instagram", category="photo",
                     title="Profile photo",
                     value="https://cdn.example.test/insta_avatar.jpg",
                     snippet=None),
            ]

    bot.engine.providers = [PhotoStubProvider()]
    n_before = len(fake.calls)
    await bot.handle_message(msg("@ig_user"))
    new_calls = fake.calls[n_before:]
    sent_photos = [c for c in new_calls if c[0] == "photo"]
    check("v4.3 flow: photo was sent after the search",
          len(sent_photos) == 1, str(new_calls))
    check("v4.3 flow: sent photo is the discovered avatar",
          bool(sent_photos)
          and sent_photos[0][2] == "https://cdn.example.test/insta_avatar.jpg",
          str(sent_photos))
    check("v4.3 flow: caption names the platform (اینستاگرام)",
          bool(sent_photos) and "اینستاگرام" in (sent_photos[0][3] or ""),
          str(sent_photos))
    check("v4.3 flow: no message text contains the photo URL",
          all("insta_avatar.jpg" not in c[2] for c in new_calls
              if c[0] in ("send", "edit") and isinstance(c[2], str)),
          str([c[2] for c in new_calls if c[0] in ("send", "edit")]))
    bot.engine.providers = [StubProvider()]

    # 18. v4.3: a telegram_id dossier sends the person's LATEST
    #     profile photo by file_id (largest size of the newest photo)
    #     via getUserProfilePhotos.
    fake.profile_photos_result = {
        "total_count": 3,
        "photos": [[{"file_id": "small_file_id", "width": 160,
                     "height": 160},
                    {"file_id": "big_file_id", "width": 640,
                     "height": 640}]],
    }
    pt = await bot.engine.resolve_or_create("telegram_id", "424242")
    n_before = len(fake.calls)
    await bot.send_person_photos(chat, pt)
    new_calls = fake.calls[n_before:]
    check("v4.3 tg-id: getUserProfilePhotos queried with limit=1",
          any(c[0] == "profile_photos" and c[1] == 424242 and c[2] == 1
              for c in new_calls), str(new_calls))
    sent = [c for c in new_calls if c[0] == "photo"]
    check("v4.3 tg-id: latest photo sent by largest file_id",
          len(sent) == 1 and sent[0][2] == "big_file_id", str(sent))
    check("v4.3 tg-id: caption names Telegram (تلگرام)",
          bool(sent) and "تلگرام" in (sent[0][3] or ""), str(sent))
    fake.profile_photos_result = {"total_count": 0, "photos": []}
    n_before = len(fake.calls)
    await bot.send_person_photos(chat, pt)
    check("v4.3 tg-id: bot cannot see the user -> silence, no crash",
          not any(c[0] == "photo" for c in fake.calls[n_before:]))

    # 18b. dedupe (owner complaint, 2026-11-10): the SAME photo must
    #      never be sent twice for the same person, across any number
    #      of later searches or views.
    fake.profile_photos_result = {
        "total_count": 3,
        "photos": [[{"file_id": "big_file_id", "width": 640,
                     "height": 640}]],
    }
    n_before = len(fake.calls)
    await bot.send_person_photos(chat, pt)
    check("dedupe: an already-sent photo is NOT resent",
          not any(c[0] == "photo" for c in fake.calls[n_before:]))
    fake.profile_photos_result = {
        "total_count": 4,
        "photos": [[{"file_id": "brand_new_file_id", "width": 640,
                     "height": 640}]],
    }
    n_before = len(fake.calls)
    await bot.send_person_photos(chat, pt)
    resent = [c for c in fake.calls[n_before:] if c[0] == "photo"]
    check("dedupe: a genuinely NEW photo is sent, exactly once",
          len(resent) == 1 and resent[0][2] == "brand_new_file_id",
          str(resent))
    fake.profile_photos_result = {"total_count": 0, "photos": []}

    # 19. v4.3: rows stored by OLDER versions (category "profile",
    #     title "Profile photo") behave as photos too — no URL in the
    #     dossier text, and the photo is still collected for sending.
    pl = await bot.db.create_person("legacy_person")
    await bot.db.add_identifier(pl, "username", "legacy_user")
    sid = await bot.db.start_search(pl)
    await bot.db.add_finding(pl, sid, "rubika", "profile", "Profile photo",
                             "https://cdn.example.test/legacy_avatar.jpg")
    await bot.db.finish_search(sid)
    dleg = await bot.engine.dossier(pl)
    check("v4.3 legacy: old-style photo row stays out of the text",
          "legacy_avatar.jpg" not in bot.format_dossier(dleg))
    jobs = await bot.collect_photo_jobs(pl)
    check("v4.3 legacy: old-style photo row is collected for sending",
          jobs == [("rubika", "https://cdn.example.test/legacy_avatar.jpg")],
          str(jobs))


    # 20. Sectioned dossier view: findings split into browsable
    #     sections; each group gets its own page.
    ps = await bot.db.create_person("sectioned_person")
    await bot.db.add_identifier(ps, "username", "sec_user")
    sid = await bot.db.start_search(ps)
    rows = [
        ("telegram_user", "profile", "Bio", "bio text", None),
        ("telegram_user", "group", "Active in public groups",
         "Tech Talk FA (2); Photography (1)", None),
        ("telegram_user", "post", "Message in Tech Talk FA", "m1", None),
        ("telegram_user", "post", "Message in Tech Talk FA", "m2", None),
        ("telegram_user", "post", "Message in Photography", "m3", None),
        ("telegram_user", "group", "Common chat", "Shared Group",
         "https://t.me/shared"),
        ("telegram_user", "analysis", "ساعات فعالیت (تهران)", "peak 15",
         None),
    ]
    for src, cat, title, value, snip in rows:
        await bot.db.add_finding(ps, sid, src, cat, title, value, snip)
    await bot.db.finish_search(sid)
    dsec = await bot.engine.dossier(ps)
    secs = bot.dossier_sections(dsec)
    keys = [k for k, _, _ in secs]
    check("sections: profile/groups/analysis/common present, ordered",
          keys == ["profile", "groups", "analysis", "common"], str(keys))
    by_key = dict((k, fs) for k, _, fs in secs)
    check("sections: common chat NOT inside groups",
          all(f["title"] != "Common chat" for f in by_key["groups"]))
    groups = bot._section_groups(by_key["groups"])
    check("sections: per-group split with counts",
          [(n, len(fs)) for n, fs in groups]
          == [("Tech Talk FA", 2), ("Photography", 1)], str(groups))
    fake.calls.clear()
    await bot.handle_callback(cq(f"secs:{ps}"))
    check("sections: menu buttons carry every section",
          all(f"sec:{ps}:{k}" in fake.markups()
              for k in ("profile", "groups", "analysis", "common")),
          str(fake.markups()))
    fake.calls.clear()
    await bot.handle_callback(cq(f"sec:{ps}:groups"))
    check("sections: groups page offers one button per group",
          f"grp:{ps}:0" in fake.markups()
          and f"grp:{ps}:1" in fake.markups(), str(fake.markups()))
    fake.calls.clear()
    await bot.handle_callback(cq(f"grp:{ps}:1"))
    check("sections: group page shows ONLY that group's messages",
          any("m3" in t for t in fake.texts())
          and not any("m1" in t or "m2" in t for t in fake.texts()),
          str(fake.texts()))
    fake.calls.clear()
    await bot.handle_callback(cq(f"sec:{ps}:analysis"))
    check("sections: analysis page shows only analysis findings",
          any("peak 15" in t for t in fake.texts())
          and not any("bio text" in t for t in fake.texts()),
          str(fake.texts()))

    # 21. Userbot LOCAL-file photos (profile + media): the value is a
    #     path, not an http(s) URL. collect/send must treat it as a
    #     sendable photo ref exactly like a URL (2026-11-11 fix: the
    #     http-only gate silently dropped every userbot photo finding,
    #     so target profile photos were never sent at all).
    pf = await bot.db.create_person("file_photo_person")
    await bot.db.add_identifier(pf, "username", "file_photo_user")
    sid = await bot.db.start_search(pf)
    await bot.db.add_finding(pf, sid, "telegram_user", "photo",
                             "Profile photo", "userbot/photos/9001.jpg")
    await bot.db.add_finding(pf, sid, "telegram_user", "photo",
                             "Media photo (public message)",
                             "userbot/photos/media/msg_1.jpg")
    await bot.db.finish_search(sid)
    jobs = await bot.collect_photo_jobs(pf)
    check("local-file photos: userbot profile file collected (one per "
          "source, first-found wins)",
          jobs == [("telegram_user", "userbot/photos/9001.jpg")],
          str(jobs))
    fake.calls.clear()
    await bot.send_person_photos(chat, pf)
    sent = [c for c in fake.calls if c[0] == "photo"]
    check("local-file photos: sent with its local path as the ref",
          len(sent) == 1 and sent[0][2] == "userbot/photos/9001.jpg",
          str(sent))
    fake.calls.clear()
    await bot.send_person_photos(chat, pf)
    check("local-file photos: dedupe — never resent",
          not any(c[0] == "photo" for c in fake.calls), str(fake.calls))


asyncio.run(main())
print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
print("ALL BOT UX TESTS PASSED")
