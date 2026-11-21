# -*- coding: utf-8 -*-
"""Offline fixture tests for the userbot query layer (userbot/).

A FakeClient serves canned Telethon TL objects built from telethon's
own types — no network, no real account, no api_id. Covers:
- full user info mapping (bio, common-chats count, personal channel)
- profile-photo history extraction (ids + dates)
- photo download from the fake client (files, never links)
- common chats mapping + wording ceiling ("Common chat")
- sender-scoped global search: only the TARGET's messages, only with
  quotable text, each with its t.me link
- the provider adapter merging into standard Finding dicts
- the DORMANT path: no credentials -> provider fully inert, and
  build_providers registers nothing while USERBOT_ENABLED is False

Run:  ~/workspace/.venv_ge/bin/python tests/test_userbot.py
"""
import asyncio
import os
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config  # noqa: E402
import providers as P  # noqa: E402
from userbot import queries as Q  # noqa: E402
from userbot.queries import UserbotProvider, UserbotQueries  # noqa: E402

FAILURES = []


def check(label, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + label
          + (f"  [{extra}]" if extra and not cond else ""))
    if not cond:
        FAILURES.append(label)


from telethon.tl.types import (  # noqa: E402
    Channel, ChatPhotoEmpty, Message, MessageReactions, PeerChannel,
    PeerNotifySettings, PeerSettings, PeerUser, Photo, ReactionCount,
    ReactionEmoji, User, UserFull, UserProfilePhoto, Username,
)
from telethon.tl.types.messages import Chats, Messages  # noqa: E402
from telethon.tl.functions.channels import SearchPostsRequest  # noqa: E402
from telethon.tl.functions.messages import SearchRequest  # noqa: E402
from telethon.tl.types.photos import Photos as PhotosResult  # noqa: E402
from telethon.tl.types.users import UserFull as UsersUserFull  # noqa: E402
from telethon.tl.functions.messages import GetCommonChatsRequest  # noqa: E402
from telethon.tl.functions.photos import GetUserPhotosRequest  # noqa: E402
from telethon.tl.functions.users import GetFullUserRequest  # noqa: E402


def dt(y, m, d):
    return datetime(y, m, d, 12, 0, tzinfo=timezone.utc)


TARGET = User(id=777000111, first_name="Sara", last_name="Karimi",
              username="sara_k", phone="989121234567", premium=True,
              access_hash=424242001,
              photo=UserProfilePhoto(photo_id=9001, dc_id=2))
FULL = UsersUserFull(
    full_user=UserFull(id=777000111, settings=PeerSettings(),
                       notify_settings=PeerNotifySettings(),
                       about="Bio line — تست",
                       common_chats_count=3, personal_channel_id=555),
    chats=[], users=[TARGET])

GROUP_A = Channel(id=1001, title="Tech Talk FA", photo=ChatPhotoEmpty(),
                  username="techtalkfa", megagroup=True, date=dt(2020, 1, 1))
GROUP_B = Channel(id=1002, title="Photography", photo=ChatPhotoEmpty(),
                  username=None, date=dt(2021, 1, 1))
PERSONAL_CH = Channel(id=555, title="Sara Notes", photo=ChatPhotoEmpty(),
                      username="saranotes", broadcast=True,
                      date=dt(2022, 1, 1))
CHAN_POST = Message(id=31, peer_id=PeerChannel(555), post=True,
                    message="پست کانال شخصی سارا", date=dt(2024, 6, 8),
                    views=77, forwards=2)

PHOTOS = PhotosResult(photos=[
    Photo(id=9001, access_hash=1, file_reference=b"", dc_id=2,
          date=dt(2024, 5, 1), sizes=[]),
    Photo(id=9002, access_hash=2, file_reference=b"", dc_id=2,
          date=dt(2023, 2, 3), sizes=[]),
], users=[TARGET])


def msg(mid, peer_id, from_uid, text, when, **kw):
    return Message(id=mid, peer_id=PeerChannel(peer_id),
                   from_id=PeerUser(from_uid), message=text, date=when,
                   **kw)


RX = MessageReactions(
    results=[ReactionCount(reaction=ReactionEmoji(emoticon="❤"), count=7)],
    can_see_list=False)
POST = Message(id=21, peer_id=PeerChannel(777000111), post=True,
               message="پست کانال شخصی", date=dt(2024, 6, 5),
               views=1234, forwards=9, reactions=RX)
EDITED = msg(15, 1001, 777000111, "پیام ویرایش شده تست", dt(2024, 6, 6),
             edit_date=dt(2024, 6, 7))
EXTRA = [POST, EDITED]


MESSAGES = [
    msg(11, 1001, 777000111, "سلام، این پیام هدف است", dt(2024, 6, 1)),
    msg(12, 1001, 424242424, "پیام شخص دیگر — نباید بیاید", dt(2024, 6, 2)),
    msg(13, 1002, 777000111, "", dt(2024, 6, 3)),           # media-only
    msg(14, 1002, 777000111, "دومین پیام هدف", dt(2024, 6, 4)),
]
CHATS_BY_ID = {1001: GROUP_A, 1002: GROUP_B}

# --- global public-post search fixtures (channels.SearchPosts) --------
PUB_CHAN = Channel(id=2001, title="Daily News", photo=ChatPhotoEmpty(),
                   username="dailynewsx", broadcast=True,
                   date=dt(2020, 6, 1))
POSTS_RESULT = Messages(messages=[
    Message(id=71, peer_id=PeerChannel(2001), post=True,
            message="Breaking #news from the wire — سلام دنیا",
            date=dt(2024, 7, 1)),
    Message(id=72, peer_id=PeerChannel(2001), post=True,
            message="", date=dt(2024, 7, 2)),  # media-only -> skipped
], topics=[], chats=[PUB_CHAN], users=[])


class PremiumAccountRequiredError(Exception):
    """Named exactly like Telethon's RPC error so the layer's
    type-name check catches it."""


class FakeMessage(Message):
    async def get_chat(self):
        return CHATS_BY_ID[self.peer_id.channel_id]


class FakeClient:
    """Duck-typed Telethon client: callable for TL requests, plus the
    three client methods the layer uses."""

    posts_error = None  # subclasses set this to simulate SearchPosts errors

    def __init__(self):
        self.downloads = []
        self.posts_requests = []

    async def __call__(self, request):
        if "SearchPosts" in type(request).__name__:
            self.posts_requests.append(request)
            if self.posts_error is not None:
                raise self.posts_error
            return POSTS_RESULT
        if isinstance(request, GetFullUserRequest):
            return FULL
        if isinstance(request, GetUserPhotosRequest):
            assert request.limit <= 100
            return PHOTOS
        if isinstance(request, GetCommonChatsRequest):
            if request.max_id:
                return Chats(chats=[])
            return Chats(chats=[GROUP_A, GROUP_B])
        if isinstance(request, SearchRequest):
            # The global scan's ONLY legal shapes (Telethon 1.45's own
            # iter_messages global+from_user path is broken — it casts
            # InputPeerEmpty to an int and dies): peer=InputPeerEmpty
            # with from_id=InputUser carrying a REAL access hash — or,
            # when the target IS the session account, InputUserSelf
            # (a sibling InputUser constructor with NO access_hash
            # attribute at all; self has no usable hash — a
            # hash-bearing InputUser for self is rejected, which was
            # the self-search bug).
            from telethon.tl.types import (
                InputPeerEmpty, InputUser, InputUserSelf)
            assert isinstance(request.peer, InputPeerEmpty), request.peer
            assert isinstance(request.from_id, (InputUser, InputUserSelf)), \
                request.from_id
            assert (isinstance(request.from_id, InputUserSelf)
                    or request.from_id.access_hash), \
                "hash-less sender scope"
            all_msgs = list(MESSAGES) + list(EXTRA)
            page = [m for m in all_msgs if m.id < (request.offset_id
                                                   or 10 ** 9)]
            return Messages(messages=page[:request.limit], topics=[],
                            chats=[GROUP_A, GROUP_B, PERSONAL_CH],
                            users=[TARGET])
        raise AssertionError(f"unexpected request {type(request)}")

    async def get_me(self):
        # The base fake's session account is a bystander (NOT the
        # target); subclasses override this to model self-search.
        from telethon.tl.types import User as _U
        return _U(id=999000999, first_name="Session", last_name="Acct",
                  username="session_acct", access_hash=111222333)

    async def get_input_entity(self, peer):
        from telethon.tl.types import InputPeerUser
        u = TARGET if peer in (777000111, "sara_k") else None
        if u is None:
            raise ValueError("could not find the input entity")
        return InputPeerUser(u.id, u.access_hash)

    async def get_entity(self, ref):
        if ref in (777000111, "sara_k", "777000111"):
            return TARGET
        if isinstance(ref, PeerUser) and ref.user_id == 777000111:
            return TARGET
        if ref == 555:
            return PERSONAL_CH
        raise ValueError("no such entity")

    async def get_messages(self, chat_id, ids=None):
        return [m for m in MESSAGES if m.id == ids]

    async def download_profile_photo(self, entity, file=None,
                                     download_big=True):
        # Telethon 1.45's real signature: NO photo_id parameter — it
        # only ever serves the entity's CURRENT profile photo. The
        # fake mirrors that exactly; a caller passing photo_id gets
        # the same TypeError the live client raises (the 2026-11-11
        # root cause: history downloads silently failed all evening).
        self.downloads.append("CURRENT")
        with open(file, "wb") as fh:
            fh.write(b"\xff\xd8fake-jpeg")
        return file

    async def download_media(self, entity, file=None):
        # A Photo TL object arrives here for history downloads.
        self.downloads.append(getattr(entity, "id", "MEDIA"))
        with open(file, "wb") as fh:
            fh.write(b"\xff\xd8fake-media")
        return file

    def iter_messages(self, entity, limit=None, from_user=None, **kw):
        # The global scan must NOT come through here at all: Telethon
        # 1.45's global+from_user path is broken by design (it casts
        # InputPeerEmpty to an int). Per-chat reads (the personal-
        # channel path AND the membership crawl's from_user pulls)
        # may use iter_messages.
        assert entity is not None, \
            "global scan via iter_messages is forbidden — use SearchRequest"
        if getattr(entity, "id", None) in (1001, 1002):
            # membership crawl: from_user-scoped pull per dialog chat
            async def chat_gen():
                for m in MESSAGES:
                    if m.peer_id.channel_id == entity.id:
                        yield m
            return chat_gen()
        assert getattr(entity, "id", None) == 555

        async def chan_gen():
            yield CHAN_POST
        return chan_gen()

    def iter_dialogs(self):
        # Used by the membership crawl (userbot/membership.py).
        class _D:
            def __init__(self, entity):
                self.entity = entity
                self.name = getattr(entity, "title", None) \
                    or getattr(entity, "first_name", "")
                self.is_channel = bool(getattr(entity, "broadcast", False))
                self.is_group = bool(getattr(entity, "megagroup", False))
                self.is_user = not (self.is_channel or self.is_group)

        async def gen():
            yield _D(GROUP_A)
            yield _D(GROUP_B)
        return gen()


async def main():
    fake = FakeClient()
    q = UserbotQueries(client=fake)

    # --- full user info -------------------------------------------------
    findings, photos = await q.full_user_info(777000111)
    by_title = {f["title"]: f["value"] for f in findings}
    check("full info: display name", by_title.get("Display name") == "Sara Karimi")
    check("full info: username", by_title.get("Username") == "@sara_k")
    check("full info: user id", by_title.get("User ID") == "777000111")
    check("full info: phone normalized", by_title.get("Phone") == "+989121234567")
    check("full info: bio", by_title.get("Bio") == "Bio line — تست")
    check("full info: premium flag", by_title.get("Telegram Premium") == "yes")
    check("full info: common chats count",
          by_title.get("Common chats with my account") == "3")
    check("full info: personal channel id",
          by_title.get("Personal channel id") == "555")
    check("full info: all findings carry the userbot source",
          all(f["source"] == "telegram_user" for f in findings))
    check("full info: no photo finding is a link",
          not any(f["category"] == "photo" for f in findings))

    # --- photo history ----------------------------------------------------
    check("photo history: ids + dates, newest first",
          photos == [(9001, "2024-05-01"), (9002, "2023-02-03")],
          str(photos))
    check("photo history: counts finding mentions record",
          "2 photo(s) on record" in by_title.get(
              "Profile photos (history)", ""))

    # --- photo download ---------------------------------------------------
    with tempfile.TemporaryDirectory() as td:
        paths = await q.download_photos(TARGET, [pid for pid, _ in photos],
                                        out_dir=td)
        check("download: two files written",
              len(paths) == 2 and all(os.path.exists(p) for p in paths))
        check("download: asked Telegram for exactly those photo ids "
              "(via the Photo objects — Telethon 1.45 has no photo_id "
              "download)",
              fake.downloads == [9001, 9002], str(fake.downloads))

    # --- common chats -------------------------------------------------------
    chats = await q.common_chats(777000111)
    check("common chats: both groups returned", len(chats) == 2)
    check("common chats: category/title honest",
          all(f["category"] == "group" and f["title"] == "Common chat"
              for f in chats))
    check("common chats: link only when a username exists",
          chats[0]["snippet"] == "https://t.me/techtalkfa"
          and chats[1]["snippet"] is None)

    # --- global search (rollup) ---------------------------------------------
    msgs = await q.global_messages_from(777000111)
    texts = [f["value"] for f in msgs]
    roll = [f for f in msgs if f["title"] == "Active in public groups"]
    samples = [f for f in msgs if f["title"].startswith("Message in ")]
    check("global: exactly one rollup finding", len(roll) == 1)
    check("global: rollup lists both groups with counts "
          "(media-only counted; +1 Tech Talk from the edited fixture)",
          bool(roll) and "Tech Talk FA (2)" in roll[0]["value"]
          and "Photography (2)" in roll[0]["value"],
          roll[0]["value"] if roll else "no rollup")
    check("global: target's text messages as samples "
          "(3 group + 1 own post + 1 channel crawl)",
          len(samples) == 5, str(texts))
    check("global: own-channel post kept even when its chat is unresolvable",
          any("کانال شخصی" in f["title"] for f in samples))
    check("global: other sender excluded",
          not any("شخص دیگر" in t for t in texts))
    check("global: media-only message excluded",
          all(t.strip() for t in texts))
    check("global: finding names its group",
          all(f["title"].startswith("Message in ") for f in samples))
    check("global: t.me link with message id",
          any(f["snippet"] == "https://t.me/techtalkfa/11" for f in samples))
    check("global: group without username -> no link, still a finding",
          any(f["snippet"] is None and "Photography" in f["title"]
              for f in samples))
    # same search by @username resolves identically (id/username parity)
    msgs_u = await q.global_messages_from("sara_k")
    check("global: username ref gives the same rollup",
          [f["title"] for f in msgs_u] == [f["title"] for f in msgs])

    # --- personal channel crawl (needs full_user_info first) ----------------
    check("channel: personal channel crawled and NAMED in the rollup",
          "Sara Notes (1)" in (roll[0]["value"] if roll else ""),
          roll[0]["value"] if roll else "no rollup")
    check("channel: its post appears as a sample under its own name",
          any(f["title"] == "Message in Sara Notes" for f in samples))
    check("channel: post views join the analysis (1234 + 77 = 1311)",
          "1311" in {f["title"]: f["value"] for f in msgs
                     if f["category"] == "analysis"}.get(
              "آمار پست‌ها (بازدید/فوروارد/ری‌اکشن)", ""))

    # --- local analysis (tier 2: deterministic, no AI) ----------------------
    ana = {f["title"]: f["value"] for f in msgs
           if f["category"] == "analysis"}
    check("analysis: sample-size finding present", "نمونه تحلیل" in ana)
    check("analysis: activity hours present", "ساعات فعالیت (تهران)" in ana)
    check("analysis: top words present", "پرتکرارترین کلمات" in ana)
    check("analysis: own-channel post stats counted (views)",
          "1234" in ana.get("آمار پست‌ها (بازدید/فوروارد/ری‌اکشن)", ""),
          str(ana.get("آمار پست‌ها (بازدید/فوروارد/ری‌اکشن)")))
    check("analysis: reactions counted in stats",
          "ری‌اکشن 7" in ana.get("آمار پست‌ها (بازدید/فوروارد/ری‌اکشن)", ""))
    check("analysis: edited messages counted",
          "ویرایش‌شده: 1" in ana.get("حجم و سبک پیام‌ها", ""),
          str(ana.get("حجم و سبک پیام‌ها")))
    check("analysis: account-age estimate is labelled an estimate",
          "تخمین" in ana.get("قدمت اکانت (تخمین از روی آیدی)", ""))
    check("analysis: findings carry the userbot source",
          all(f["source"] == "telegram_user" for f in msgs
              if f["category"] == "analysis"))

    # --- provider adapter ---------------------------------------------------
    prov = UserbotProvider(queries=q)
    out = await prov.search("telegram_id", "777000111")
    cats = {f["category"] for f in out}
    check("provider: merges profile+group+post findings",
          {"profile", "group", "post"} <= cats, str(cats))
    check("provider: handles set unchanged",
          set(prov.handles) == {"telegram_id", "username", "tgmsg"})
    prof_photos = [f for f in out if f["category"] == "photo"
                   and f["title"] == "Profile photo"]
    check("provider: profile photos emitted as photo findings with "
          "local file paths (bot sends them as real photos, deduped)",
          len(prof_photos) == 2
          and all(os.path.exists(f["value"]) for f in prof_photos),
          str(prof_photos))

    # tgmsg path: forwarded-message reference resolves its sender
    import json as _json
    out2 = await prov.search("tgmsg", _json.dumps(
        {"chat_id": 1001, "message_id": 11}))
    check("provider: tgmsg resolves and searches the sender",
          len(out2) >= 2, str(len(out2)))

    # --- dormant paths --------------------------------------------------------
    cold = UserbotQueries()  # no client, no credentials configured
    check("dormant: connect() False without credentials",
          await cold.connect() is False)
    cold_prov = UserbotProvider(queries=cold)
    cold_out = await cold_prov.search("telegram_id", "777000111")
    check("dormant: provider returns ONLY the not-connected status "
          "finding and never raises",
          len(cold_out) == 1
          and cold_out[0]["title"] == "Userbot status"
          and "وصل نشد" in cold_out[0]["value"], str(cold_out))

    # --- resolve fallback: cold cache, numeric id (live bug 2026-11-10) ---
    class ColdClient(FakeClient):
        async def get_entity(self, ref):
            if isinstance(ref, int):
                raise ValueError("Could not find the input entity for "
                                 f"PeerUser(user_id={ref})")
            return await super().get_entity(ref)

        async def get_me(self):
            return TARGET

        def iter_dialogs(self):
            async def gen():
                if False:
                    yield
            return gen()

    q_cold = UserbotQueries(client=ColdClient())
    cold_user = await q_cold.resolve_user(777000111)
    check("resolve: cold-cache numeric id falls back to the own account",
          cold_user is not None and cold_user.id == 777000111)
    cold_findings, _ = await q_cold.full_user_info(777000111)
    check("resolve: profile works through the fallback",
          any(f["title"] == "Display name" for f in cold_findings))

    # --- profile baseline survives a GetFullUser failure -------------------
    class NoFullClient(FakeClient):
        async def __call__(self, request):
            if isinstance(request, GetFullUserRequest):
                raise RuntimeError("full user unavailable")
            return await super().__call__(request)

    q_nofull = UserbotQueries(client=NoFullClient())
    nf, _ = await q_nofull.full_user_info(777000111)
    nf_titles = {f["title"] for f in nf}
    check("profile baseline: name/username/id survive GetFullUser failure",
          {"Display name", "Username", "User ID"} <= nf_titles,
          str(nf_titles))
    check("profile baseline: full-only fields absent, not fabricated",
          "Bio" not in nf_titles
          and "Common chats with my account" not in nf_titles)

    # --- self search: the target IS the logged-in account -----------------
    # Telegram gives self access_hash 0/None and Telethon's
    # get_input_entity(own id) returns InputPeerSelf, which has NO
    # user_id/access_hash fields. The old code built InputUser from
    # those fields, failed silently, and the global scan returned
    # nothing — only when searching YOURSELF. The fix must scope the
    # scan with InputUserSelf instead.
    from telethon.tl.types import InputPeerSelf as _IPS
    from telethon.tl.types import InputUserSelf as _IUS

    class SelfClient(FakeClient):
        async def get_me(self):
            return TARGET

        async def get_input_entity(self, peer):
            if peer == TARGET.id:
                return _IPS()
            return await super().get_input_entity(peer)

        async def __call__(self, request):
            if isinstance(request, SearchRequest):
                check("self scan: sender scoped with InputUserSelf",
                      isinstance(request.from_id, _IUS),
                      str(type(request.from_id)))
            return await super().__call__(request)

    q_self = UserbotQueries(client=SelfClient())
    self_msgs = await q_self.global_messages_from(777000111)
    check("self scan: own messages found via InputUserSelf",
          len(self_msgs) > 0
          and getattr(q_self, "last_scan_error", None) is None,
          str(getattr(q_self, "last_scan_error", None)))

    # --- diagnostics: a global scan that raises must surface --------------
    class BoomClient(FakeClient):
        async def __call__(self, request):
            if isinstance(request, SearchRequest):
                raise RuntimeError("search exploded")
            return await super().__call__(request)

    q_boom = UserbotQueries(client=BoomClient())
    out_boom = await UserbotProvider(queries=q_boom).search(
        "telegram_id", "777000111")
    status_boom = [f["value"] for f in out_boom
                   if f["title"] == "Userbot status"]
    check("diagnostics: scan exception is REPORTED, not swallowed",
          bool(status_boom) and "RuntimeError" in status_boom[0],
          str(status_boom))
    check("diagnostics: other steps still delivered despite the boom",
          any(f["title"] == "Display name" for f in out_boom))
    # --- membership + per-target dashboard (2026-11-11) ------------------
    from userbot import membership
    res = await membership.crawl_target_activity(q, 777000111)
    check("membership: crawl resolves the target", res is not None)
    titles_m = [f["title"] for f in res["findings"]]
    check("membership: common chats surfaced as CERTAIN memberships",
          titles_m.count("عضویت مشترک قطعی") == 2, str(titles_m))
    texts_m = [m["text"] for m in res["messages"]]
    check("membership: ONLY the target's messages are collected "
          "(strict sender filter)",
          all("شخص دیگر" not in t for t in texts_m) and len(texts_m) >= 3,
          str(texts_m))
    check("membership: dashboard labelled for the target, with the "
          "visible-minimum note",
          "Sara" in res["data"]["me"]
          and "حداقل" in (res["data"]["session_account"] or ""),
          res["data"]["me"])
    check("membership: HTML renders with the target's data embedded",
          "Sara" in res["html"] and str(res["data"]["totals"]["messages"])
          in res["html"])
    f_act, html_act = await UserbotProvider(queries=q).run_step(
        "activity", [("telegram_id", "777000111")])
    check("membership: provider run_step('activity') returns findings "
          "+ html", bool(f_act) and bool(html_act))

    # --- global public-post search (channels.SearchPosts) -----------------
    posts = await q.search_posts_global("#news")
    check("posts: hashtag search returns post findings",
          len(posts) == 1 and posts[0]["category"] == "post",
          str(posts))
    check("posts: finding names its channel, with date + excerpt",
          bool(posts) and posts[0]["title"] == "پست عمومی در Daily News"
          and posts[0]["value"].startswith("2024-07-01 — ")
          and "#news" in posts[0]["value"], str(posts))
    check("posts: t.me link built from the channel username",
          bool(posts) and posts[0]["snippet"]
          == "https://t.me/dailynewsx/71", str(posts))
    check("posts: hashtag request shape (hashtag set, no text query)",
          bool(fake.posts_requests)
          and fake.posts_requests[-1].hashtag == "news"
          and fake.posts_requests[-1].query is None
          and fake.posts_requests[-1].allow_paid_stars == 0)
    check("posts: media-only post skipped",
          all("2024-07-02" not in f["value"] for f in posts))

    class PremiumClient(FakeClient):
        posts_error = PremiumAccountRequiredError(
            "premium account required")

    q_prem = UserbotQueries(client=PremiumClient())
    prem = await q_prem.search_posts_global("Telegram")
    check("posts: Premium gate -> ONE Persian status finding, no crash",
          len(prem) == 1 and prem[0]["category"] == "status"
          and prem[0]["title"] == "وضعیت جست‌وجوی سراسری"
          and "پریمیوم" in prem[0]["value"]
          and "هشتگ" in prem[0]["value"], str(prem))
    check("posts: Premium path does not set last_posts_error",
          q_prem.last_posts_error is None)

    class DownClient(FakeClient):
        posts_error = RuntimeError("network down")

    q_down = UserbotQueries(client=DownClient())
    down = await q_down.search_posts_global("#news")
    check("posts: other errors -> [] + last_posts_error recorded",
          down == [] and "RuntimeError" in (q_down.last_posts_error or ""),
          str(q_down.last_posts_error))

    f_posts, html_posts = await UserbotProvider(queries=q).run_step(
        "posts", [("username", "SomeUser")])
    check("posts: provider run_step('posts') returns findings, html None",
          bool(f_posts) and html_posts is None
          and f_posts[0]["category"] == "post", str(f_posts))
    check("posts: provider searched the USERNAME as the text query",
          fake.posts_requests[-1].query == "SomeUser"
          and fake.posts_requests[-1].hashtag is None)
    f_nouser, _ = await UserbotProvider(queries=q).run_step(
        "posts", [("telegram_id", "777000111")])
    check("posts: run_step without a username -> honest status finding",
          len(f_nouser) == 1 and f_nouser[0]["title"] == "Userbot status"
          and "یوزرنیم" in f_nouser[0]["value"], str(f_nouser))

    names = [p.name for p in P.build_providers(api=None)]
    check("registry: shipped config enables the userbot layer "
          "(2026-11-10 incident fix) and build_providers registers it",
          "telegram_user" in names and config.USERBOT_ENABLED is True,
          str(names))
    check("registry: bot token is display-only — no TelegramBotApiProvider "
          "instance is registered (2026-11-11)",
          not any(isinstance(p, P.TelegramBotApiProvider)
                  for p in P.build_providers(api=None)))

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S):", *FAILURES, sep="\n  ")
        return 1
    print("ALL USERBOT TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
