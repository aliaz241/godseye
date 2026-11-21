# -*- coding: utf-8 -*-
"""God's Eye — userbot query layer (Telethon / MTProto).

The bot-only edition can only see what a BOT can see. This module is the
query layer BEHIND it, running on your OWN Telegram user account, and
adds exactly the three lookups a bot token cannot do (the JasooousBot
class of queries):

1. Sender-scoped global search — the messages a PERSON sent in public
   groups/supergroups, found from one of their messages (in practice:
   the identifier the bot already extracted from a forwarded message),
   their numeric id, or their @username. Results come back as a rollup:
   the public groups they are active in (ranked by sampled message
   count) plus a few sample messages per group.
2. Common chats — the groups/channels the account and the target
   both belong to (messages.GetCommonChats). This is BY DEFINITION
   scoped to the account: it can only ever list chats shared with
   him, never "all groups the person is in".
3. Full user info (users.GetFullUser) — bio, common-chats count,
   personal channel, and the profile-photo HISTORY (photo ids + dates),
   which no bot and no public page exposes.

CEILINGS (stated up front, per the owner's standing rule — nothing here
sees more than Telegram itself shows a normal user account):
- Global search covers PUBLIC megagroups/channels only. Private
  groups, other people's private chats and secret chats are invisible.
- The global search needs a starting point: a message the person sent
  in a public group (the bot's forward flow already produces one), or
  the person's numeric user id.
- Common chats = chats shared with ALI's account only.
- Profile photos are downloaded as FILES; the bot layer sends them as
  real photos. A photo is never stored as a link finding.

Everything returns the project's standard Finding dicts
(source="telegram_user", category, title, value, snippet) so results
merge into the existing per-person dossiers unchanged. All network
objects are plain Telethon TL types — the pure mapping helpers below
take duck-typed objects, which is what the offline tests feed them.
"""
import asyncio
import os
from datetime import datetime, timezone

from . import userbot_config as uc

SOURCE = "telegram_user"


# ------------------------------------------------------------ findings
def _f(category, title, value, snippet=None):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return dict(source=SOURCE, category=category, title=title,
                value=str(value).strip()[:500], snippet=snippet)


def _chat_title(chat):
    return (getattr(chat, "title", None)
            or getattr(chat, "first_name", None) or "")


def _chat_username(chat):
    u = getattr(chat, "username", None)
    if u:
        return u
    for alt in getattr(chat, "usernames", None) or []:
        u = getattr(alt, "username", None)
        if u and getattr(alt, "active", True):
            return u
    return None


def _chat_link(chat):
    u = _chat_username(chat)
    return f"https://t.me/{u}" if u else None


def _msg_link(chat, msg_id):
    u = _chat_username(chat)
    return f"https://t.me/{u}/{msg_id}" if u else None


def _fmt_date(dt):
    if dt is None:
        return None
    try:
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return str(dt)[:10]


def _peer_user_id(peer):
    return getattr(peer, "user_id", None)


def _peer_chat_id(peer):
    return getattr(peer, "channel_id", None) or getattr(peer, "chat_id", None)


class _BareChat:
    """Minimal stand-in for a chat entity that could not be resolved
    (title only) — used so real message data is never dropped just
    because its chat object is unavailable."""

    def __init__(self, title):
        self.title = title
        self.username = None
        self.usernames = None


# ------------------------------------------------- pure mapping helpers
def full_name_of(user):
    parts = [getattr(user, "first_name", None),
             getattr(user, "last_name", None)]
    return " ".join(p for p in parts if p).strip()


def user_profile_findings(user, full):
    """users.GetFullUser result (user, full) -> profile findings.
    Only fields Telegram actually returned are emitted — no guessing."""
    out = []
    name = full_name_of(user)
    if name:
        out.append(_f("profile", "Display name", name))
    uname = _chat_username(user)
    if uname:
        out.append(_f("profile", "Username", "@" + uname,
                      f"https://t.me/{uname}"))
    out.append(_f("profile", "User ID", getattr(user, "id", None)))
    phone = getattr(user, "phone", None)
    if phone:
        out.append(_f("profile", "Phone", "+" + str(phone).lstrip("+")))
    about = getattr(full, "about", None)
    if about:
        out.append(_f("profile", "Bio", about))
    if getattr(user, "bot", False):
        out.append(_f("profile", "Account type", "bot"))
    if getattr(user, "verified", False):
        out.append(_f("profile", "Verified", "yes"))
    if getattr(user, "scam", False):
        out.append(_f("profile", "Flagged as scam", "yes"))
    if getattr(user, "fake", False):
        out.append(_f("profile", "Flagged as fake", "yes"))
    if getattr(user, "premium", False):
        out.append(_f("profile", "Telegram Premium", "yes"))
    cc = getattr(full, "common_chats_count", None)
    if cc is not None:
        out.append(_f("profile", "Common chats with my account", cc))
    pc_id = getattr(full, "personal_channel_id", None)
    if pc_id:
        out.append(_f("profile", "Personal channel id", pc_id))
    bday = getattr(full, "birthday", None)
    if bday is not None:
        try:
            out.append(_f("profile", "Birthday",
                          f"{bday.year or '—'}-{bday.month:02d}-{bday.day:02d}"))
        except Exception:
            pass
    return [f for f in out if f]


def message_findings(msg, chat):
    """One message from the global search -> one "post" finding.
    `chat` is the group/channel the message lives in."""
    text = (getattr(msg, "message", None) or "").strip()
    if not text:
        return None  # media-only / service messages carry no quotable text
    chat_title = _chat_title(chat) or "public chat"
    when = _fmt_date(getattr(msg, "date", None))
    return _f("post", f"Message in {chat_title}",
              f"{when + ' — ' if when else ''}{text}",
              _msg_link(chat, getattr(msg, "id", None)))


def common_chat_findings(chats, limit):
    out = []
    for chat in list(chats)[:limit]:
        title = _chat_title(chat)
        if not title:
            continue
        out.append(_f("group", "Common chat", title, _chat_link(chat)))
    return [f for f in out if f]


def public_group_rollup(pairs, per_chat=None):
    """(msg, chat) pairs from the global search -> rollup findings:
    one summary (the public groups/channels the person is active in,
    ranked by message count in the sample) plus up to `per_chat`
    sample message findings per chat. Chats without a title are
    skipped; sample text reuses message_findings unchanged."""
    per_chat = per_chat or uc.GROUP_SAMPLE_PER_CHAT
    by_chat, order = {}, []
    for msg, chat in pairs:
        title = _chat_title(chat)
        if not title:
            continue
        if title not in by_chat:
            by_chat[title] = {"chat": chat, "count": 0, "samples": []}
            order.append(title)
        slot = by_chat[title]
        slot["count"] += 1
        if len(slot["samples"]) < per_chat:
            slot["samples"].append(msg)
    if not by_chat:
        return []
    ranked = sorted(order, key=lambda t: -by_chat[t]["count"])
    out = [_f("group", "Active in public groups",
              "; ".join(f"{t} ({by_chat[t]['count']})" for t in ranked))]
    for t in ranked:
        for msg in by_chat[t]["samples"]:
            f = message_findings(msg, by_chat[t]["chat"])
            if f:
                out.append(f)
    return [f for f in out if f]


def message_record(msg, chat):
    """One sampled message -> the plain record the LOCAL analytics
    module consumes (text/time/engagement/reply/media/edit signals).
    Reactions come back as [(emoji, count)]; 'views' exists on channel
    posts. Everything is read off the TL object — nothing is guessed."""
    reactions = []
    res = getattr(msg, "reactions", None)
    for r in (getattr(res, "results", None) or []):
        rc = getattr(r, "reaction", None)
        emoji = getattr(rc, "emoticon", None) or "★"
        reactions.append((emoji, getattr(r, "count", 0) or 0))
    reply = getattr(msg, "reply_to", None)
    return {
        "date": getattr(msg, "date", None),
        "text": (getattr(msg, "message", None) or ""),
        "chat_title": _chat_title(chat),
        "views": getattr(msg, "views", None),
        "forwards": getattr(msg, "forwards", None),
        "reactions": reactions,
        "edited": getattr(msg, "edit_date", None) is not None,
        "reply_to_user_id": None,  # filled by the collector when known
        "reply_to_msg_id": getattr(reply, "reply_to_msg_id", None),
        "has_media": getattr(msg, "media", None) is not None,
        "is_channel_post": getattr(msg, "post", False),
        "link": _msg_link(chat, getattr(msg, "id", None)),
        "_msg": msg,
        "_reply_header": reply,
    }


def photo_history(photos):
    """ProfilePhotos result -> [(photo_id, date)] newest first.
    Works on the .photos list of photos.Photo (userbot) and tolerates
    a bare list. Dates come from each photo's own `date` field."""
    items = getattr(photos, "photos", photos) or []
    out = []
    for p in items:
        pid = getattr(p, "id", None)
        if pid is None:
            continue
        out.append((pid, _fmt_date(getattr(p, "date", None))))
    return out


# ------------------------------------------------------------- the layer
class UserbotQueries:
    """Wraps a connected Telethon client. Construction does NOT connect;
    use `connect()` (after the one-time login) or inject a client."""

    def __init__(self, client=None):
        self.client = client

    # -- lifecycle ------------------------------------------------------
    async def connect(self):
        if self.client is not None:
            return True
        if not uc.API_ID or not uc.API_HASH:
            return False  # not activated yet — stay silent, never guess
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        # A StringSession keeps the session inside this private file —
        # no .session database is written next to the code.
        sess_file = uc.SESSION_PATH + ".session_string"
        string = ""
        if os.path.exists(sess_file):
            with open(sess_file, encoding="utf-8") as fh:
                string = fh.read().strip()
        kw = {}
        proxy = getattr(uc, "PROXY", None)
        if proxy:
            kw["proxy"] = proxy
        client = TelegramClient(StringSession(string), uc.API_ID,
                                uc.API_HASH, **kw)
        try:
            await asyncio.wait_for(client.connect(), timeout=45)
            if not await client.is_user_authorized():
                await client.disconnect()
                return False  # login.py must run first (interactive)
        except Exception:
            try:
                await client.disconnect()
            except Exception:
                pass
            return False  # unreachable network — provider stays inert
        self.client = client
        return True

    async def close(self):
        if self.client is not None:
            await self.client.disconnect()
            self.client = None

    def _ready(self):
        return self.client is not None

    # -- resolution ------------------------------------------------------
    async def resolve_user(self, ref):
        """ref: numeric user id, @username, or Message (sender is used).
        Returns the TL User or None.

        A bare numeric id is the fragile case (found live, 2026-11-10):
        the StringSession's entity cache is cold after every restart,
        so get_entity(int) raises "could not find the input entity"
        even for the account's OWN id — while the same person resolves
        fine by username. Fallback chain for ints: (1) the session's
        own account (get_me), (2) the dialog list (every user the account's
        account shares a chat with — the realistic lookup case), which
        also warms the cache for the retry. The failure, when the whole
        chain fails, is RECORDED (last_resolve_error) so the provider
        can name it instead of reporting unexplained zeros."""
        if not self._ready():
            return None
        from telethon.tl.types import Message, MessageService, PeerUser
        self.last_resolve_error = None
        try:
            if isinstance(ref, (Message, MessageService)):
                # get_sender() needs the client's entity cache; on a
                # bare (unbound) Message it silently returns None.
                # Resolve from_id explicitly — that ALWAYS works.
                sender = None
                try:
                    sender = await ref.get_sender()
                except Exception:
                    sender = None
                if sender is not None:
                    return sender
                uid = _peer_user_id(getattr(ref, "from_id", None))
                if uid is None:
                    return None
                return await self.client.get_entity(PeerUser(uid))
            return await self.client.get_entity(ref)
        except Exception as e:
            self.last_resolve_error = f"{type(e).__name__}: {e}"[:200]
        if isinstance(ref, int) or (isinstance(ref, str)
                                    and ref.lstrip("-").isdigit()):
            target = int(ref)
            try:
                me = await self.client.get_me()
                if me is not None and getattr(me, "id", None) == target:
                    return me
            except Exception:
                pass
            try:
                async for dlg in self.client.iter_dialogs():
                    ent = getattr(dlg, "entity", None)
                    if getattr(ent, "id", None) == target:
                        return ent
            except Exception:
                pass
            try:
                return await self.client.get_entity(target)
            except Exception:
                pass
        return None

    # -- 3. full user info ------------------------------------------------
    async def full_user_info(self, ref):
        """-> (findings, photos) where photos = [(photo_id, date)].
        findings are standard Finding dicts; photos are IDs only — call
        download_photos() to turn them into sendable files."""
        if not self._ready():
            return [], []
        from telethon.tl.functions.users import GetFullUserRequest
        from telethon.tl.functions.photos import GetUserPhotosRequest
        user = await self.resolve_user(ref)
        if user is None or getattr(user, "id", None) is None:
            return [], []
        findings = []
        self._personal_channel_id = None
        self._full_user_obj = None
        # Baseline FIRST (2026-11-10 fix): the fields the User object
        # itself carries (name, username, id, flags) must be reported
        # even when GetFullUser fails — previously one failed request
        # silently zeroed the whole profile step.
        findings += user_profile_findings(user, None)
        try:
            full = await self.client(GetFullUserRequest(user))
            full_user = getattr(full, "full_user", full)
            self._personal_channel_id = getattr(
                full_user, "personal_channel_id", None)
            full0 = getattr(full, "users", [user])[0] \
                if getattr(full, "users", None) else user
            # Stash the hash-bearing copy for the global scan (see
            # global_messages_from): GetFullUser's users[0] is resolved
            # against Telegram's user store and carries the access
            # hash even when the resolve-path object does not.
            self._full_user_obj = full0
            rich = user_profile_findings(full0, full_user)
            seen = {(f["title"], f["value"]) for f in findings}
            findings += [f for f in rich
                         if (f["title"], f["value"]) not in seen]
        except Exception:
            pass
        photos = []
        self._photo_objs = {}
        try:
            res = await self.client(GetUserPhotosRequest(
                user_id=user, offset=0, max_id=0, limit=uc.MAX_PHOTOS_SENT))
            photos = photo_history(res)
            # Keep the full Photo objects keyed by id: Telethon 1.45's
            # download_profile_photo no longer accepts a photo_id — a
            # specific history photo can only be downloaded through its
            # TL object (as a "message" via download_media).
            self._photo_objs = {
                getattr(p, "id", None): p
                for p in (getattr(res, "photos", None) or [])}
            if photos:
                findings.append(_f(
                    "profile", "Profile photos (history)",
                    f"{len(photos)} photo(s) on record, "
                    f"newest {photos[0][1] or '?'}"
                    + (f", oldest {photos[-1][1] or '?'}" if len(photos) > 1
                       else "")))
        except Exception:
            pass
        return [f for f in findings if f], photos

    async def download_photos(self, user_ref, photo_ids, out_dir=None):
        """Download the given profile photos to files; returns the list
        of file paths (the bot layer sends these as real photos).
        Best-effort per photo: failures are skipped, never fatal."""
        if not self._ready():
            return []
        out_dir = out_dir or uc.PHOTO_DOWNLOAD_DIR
        os.makedirs(out_dir, exist_ok=True)
        user = await self.resolve_user(user_ref)
        paths = []
        objs = getattr(self, "_photo_objs", {}) or {}
        for pid in list(photo_ids)[:uc.MAX_PHOTOS_SENT]:
            path = os.path.join(out_dir, f"{pid}.jpg")
            if os.path.exists(path):
                paths.append(path)
                continue
            try:
                obj = objs.get(pid)
                if obj is not None:
                    # History photo: Telethon 1.45 downloads a specific
                    # Photo only through its TL object — the profile
                    # endpoint serves just the CURRENT photo.
                    got = await self.client.download_media(obj, file=path)
                else:
                    got = await self.client.download_profile_photo(
                        user, file=path, download_big=False)
                if got:
                    paths.append(got)
            except Exception:
                continue
        return paths

    # -- 2. common chats ----------------------------------------------------
    async def common_chats(self, ref, limit=None):
        """Groups/channels shared between ALI's account and the target.
        Ceiling: only chats the account is in can ever appear."""
        if not self._ready():
            return []
        from telethon.tl.functions.messages import GetCommonChatsRequest
        limit = limit or uc.MAX_COMMON_CHATS
        user = await self.resolve_user(ref)
        if user is None:
            return []
        chats, max_id = [], 0
        try:
            while len(chats) < limit:
                res = await self.client(GetCommonChatsRequest(
                    user_id=user, max_id=max_id, limit=min(100, limit)))
                page = list(getattr(res, "chats", []) or [])
                if not page:
                    break
                chats += page
                max_id = page[-1].id
        except Exception:
            pass
        return common_chat_findings(chats, limit)

    # -- 1. sender-scoped global search -------------------------------------
    async def global_messages_from(self, ref, limit=None):
        """The target's messages in PUBLIC groups/channels.

        ref may be a Message (its sender is the target — the forwarded
        message flow), a numeric user id, or a @username. Returns
        standard "post" findings, newest first. Private chats are
        invisible to this API by design."""
        if not self._ready():
            return []
        from telethon.tl.functions.messages import SearchRequest
        from telethon.tl.types import (
            InputMessagesFilterEmpty, InputPeerEmpty, InputUser,
            InputUserSelf, MessageService, PeerUser)
        limit = limit or uc.MAX_GLOBAL_RESULTS
        # Is the target the logged-in account ITSELF? Telegram returns
        # access_hash 0/None for self and Telethon resolves the own id
        # to InputPeerSelf (which has no user_id/access_hash fields),
        # so the ordinary InputUser(id, hash) construction fails
        # SILENTLY for self and the scan returns nothing — while the
        # same id works fine when referenced as a third person. The
        # only correct sender reference for self is InputUserSelf.
        me_id = None
        try:
            me = await self.client.get_me()
            me_id = getattr(me, "id", None)
        except Exception:
            me_id = None
        sender_id, from_input = None, None
        if isinstance(ref, MessageService) or hasattr(ref, "from_id"):
            sender_id = _peer_user_id(getattr(ref, "from_id", None))
            fp = getattr(ref, "from_id", None)
            if isinstance(fp, PeerUser):
                if me_id is not None and fp.user_id == me_id:
                    sender_id = me_id
                    from_input = InputUserSelf()
                else:
                    try:
                        fu = await self.client.get_entity(fp)
                        sender_id = fu.id
                        if me_id is not None and fu.id == me_id:
                            from_input = InputUserSelf()
                        else:
                            from_input = InputUser(
                                fu.id, fu.access_hash or 0)
                    except Exception:
                        from_input = None
            if sender_id is None or from_input is None:
                return []  # channel post / anonymous — no person to scope to
        else:
            user = await self.resolve_user(ref)
            if user is None or getattr(user, "id", None) is None:
                return []
            sender_id = user.id
            if me_id is not None and sender_id == me_id:
                from_input = InputUserSelf()
            else:
                # Hash-bearing copy: GetFullUser's users[0] is the SAME
                # person resolved against Telegram's user store — it
                # carries the real access hash even when the object
                # resolve_user returned does not.
                full_user = getattr(self, "_full_user_obj", None)
                if full_user is not None and getattr(
                        full_user, "id", None) == sender_id and getattr(
                        full_user, "access_hash", None):
                    user = full_user
                if getattr(user, "access_hash", None):
                    from_input = InputUser(user.id, user.access_hash)
                else:
                    try:
                        ent = await self.client.get_input_entity(
                            sender_id)
                        if type(ent).__name__ == "InputPeerSelf":
                            from_input = InputUserSelf()
                        else:
                            from_input = InputUser(
                                ent.user_id, ent.access_hash)
                    except Exception:
                        from_input = None
            if from_input is None:
                self.last_scan_error = (
                    "no access hash for this user — cannot scope the "
                    "global search (resolve by username or forward a "
                    "message from them first)")
                self.last_scan_count = 0
                return []
        pairs, records, chat_by_key, scanned = [], [], {}, 0
        self.last_scan_error = None
        try:
            offset_id = 0
            while scanned < limit:
                res = await self.client(SearchRequest(
                    peer=InputPeerEmpty(), q="",
                    filter=InputMessagesFilterEmpty(),
                    min_date=None, max_date=None, offset_id=offset_id,
                    add_offset=0, limit=min(100, limit - scanned),
                    max_id=0, min_id=0, hash=0, from_id=from_input))
                page = list(getattr(res, "messages", None) or [])
                if not page:
                    break
                users_by_id = {getattr(u, "id", None): u
                               for u in (getattr(res, "users", None)
                                         or [])}
                chats_by_id = {getattr(c, "id", None): c
                               for c in (getattr(res, "chats", None)
                                         or [])}
                for msg in page:
                    scanned += 1
                    from_uid = _peer_user_id(getattr(msg, "from_id", None))
                    cid = _peer_chat_id(getattr(msg, "peer_id", None))
                    is_own_post = (from_uid is None
                                   and getattr(msg, "post", False)
                                   and cid is not None)
                    if from_uid != sender_id and not is_own_post:
                        continue  # never attribute another's words
                    key = (type(getattr(msg, "peer_id", None)).__name__,
                           cid)
                    chat = chat_by_key.get(key)
                    if chat is None:
                        chat = chats_by_id.get(cid)
                        if chat is None and from_uid is not None:
                            chat = users_by_id.get(from_uid)
                        if chat is None:
                            try:
                                chat = await msg.get_chat()
                            except Exception:
                                chat = None
                        chat_by_key[key] = chat
                    if chat is None:
                        if is_own_post:
                            # Own-channel post whose channel entity did
                            # not resolve — keep the record (views and
                            # reactions are real data) under a neutral
                            # title instead of dropping it.
                            pairs.append((msg, _BareChat("کانال شخصی")))
                            records.append(message_record(
                                msg, pairs[-1][1]))
                        continue
                    pairs.append((msg, chat))
                    rec = message_record(msg, chat)
                    hdr = rec.pop("_reply_header", None)
                    rid = getattr(hdr, "reply_to_msg_id", None) \
                        if hdr else None
                    if rid:
                        try:
                            orig = await self.client.get_messages(
                                chat, ids=rid)
                            if orig and orig[0] is not None:
                                rec["reply_to_user_id"] = _peer_user_id(
                                    getattr(orig[0], "from_id", None))
                        except Exception:
                            pass
                    records.append(rec)
                offset_id = page[-1].id
                if len(page) < 100:
                    break
        except Exception as e:
            # Never silent: the provider turns this into a visible
            # status finding (partial pairs/records are still used).
            self.last_scan_error = f"{type(e).__name__}: {e}"[:200]
        self.last_scan_count = scanned
        self.last_records = records
        # -- the person's OWN channel, crawled directly by its id ----
        # (from GetFullUser.personal_channel_id, captured by
        # full_user_info; the provider always calls that first). Its
        # posts are indexed under the CHANNEL id, so the global scan
        # above cannot attribute or name them — this crawl can.
        pc_id = getattr(self, "_personal_channel_id", None)
        if pc_id:
            try:
                chan = await self.client.get_entity(pc_id)
            except Exception:
                chan = None
            if chan is not None:
                try:
                    async for msg in self.client.iter_messages(
                            chan, limit=uc.CHANNEL_POSTS_MAX):
                        pairs.append((msg, chan))
                        rec = message_record(msg, chan)
                        rec.pop("_reply_header", None)
                        records.append(rec)
                except Exception:
                    pass
        out = public_group_rollup(pairs)
        media_msgs = [r["_msg"] for r in records
                      if r.get("has_media") and r["_msg"] is not None]
        if media_msgs:
            out.append(_f("post", "Media in sampled messages",
                          f"{len(media_msgs)} of the sampled messages "
                          "carry media (photo/video/file)"))
            self.last_media = media_msgs[:uc.MEDIA_PHOTOS_MAX]
        if uc.ANALYSIS_ENABLED and records:
            from . import analytics
            out += analytics.analysis_findings(
                records, top_words=uc.TOP_WORDS_COUNT)
            era = analytics.account_age_estimate(sender_id)
            if era:
                out.append(_f("analysis", "قدمت اکانت (تخمین از روی آیدی)",
                              era + " — تخمین تقریبی از روی بازه آیدی، "
                                    "نه تاریخ قطعی ثبت‌نام"))
        return out

    async def download_media_photos(self, out_dir=None):
        """Download the photo media of the messages collected by the
        last global_messages_from() call (videos/files are counted in
        the findings but not downloaded — size). Returns file paths."""
        if not self._ready():
            return []
        msgs = getattr(self, "last_media", None) or []
        if not msgs:
            return []
        out_dir = out_dir or os.path.join(uc.PHOTO_DOWNLOAD_DIR, "media")
        os.makedirs(out_dir, exist_ok=True)
        paths = []
        for m in msgs:
            if getattr(m, "photo", None) is None:
                continue  # photos only; other media stays a count
            path = os.path.join(
                out_dir, f"m{getattr(m, 'id', 0)}_{id(m)}.jpg")
            if os.path.exists(path):
                paths.append(path)
                continue
            try:
                got = await self.client.download_media(m, file=path)
                if got:
                    paths.append(got)
            except Exception:
                continue
        return paths


    # -- 4. global public-post search (channels.SearchPosts) ------------
    async def search_posts_global(self, query, limit=50):
        """Telegram's global PUBLIC-POST index (channels.SearchPosts):
        public CHANNEL posts matching a #hashtag (free for everyone) or
        a text query (Telegram gates text queries behind Premium on the
        SESSION account — a PremiumAccountRequired error becomes a
        visible Persian status finding, never a crash). One page only.
        Findings are standard "post" dicts naming the channel each post
        lives in, with its t.me link when the channel has a username.
        This index covers channel posts only — no group messages and
        no person scoping (posts carry from_id=None by design)."""
        self.last_posts_error = None
        if not self._ready():
            return []
        from telethon.tl.functions.channels import SearchPostsRequest
        from telethon.tl.types import InputPeerEmpty
        limit = max(1, min(int(limit or 50), 50))
        q = (query or "").strip()
        if not q:
            return []
        try:
            if q.startswith("#"):
                res = await self.client(SearchPostsRequest(
                    hashtag=q.lstrip("#"), offset_rate=0,
                    offset_peer=InputPeerEmpty(), offset_id=0,
                    limit=limit, allow_paid_stars=0))
            else:
                res = await self.client(SearchPostsRequest(
                    query=q, offset_rate=0,
                    offset_peer=InputPeerEmpty(), offset_id=0,
                    limit=limit, allow_paid_stars=0))
        except Exception as e:
            if "PremiumAccountRequired" in type(e).__name__:
                return [_f("status", "وضعیت جست‌وجوی سراسری",
                           "جست‌وجوی متنی در ایندکس پست‌های عمومی تلگرام "
                           "روی اکانت سشن، تلگرام پریمیوم می‌خواهد و این "
                           "اکانت پریمیوم نیست؛ جست‌وجوی هشتگی (#…) "
                           "رایگان است و کار می‌کند.")]
            self.last_posts_error = f"{type(e).__name__}: {e}"[:200]
            return []
        chats_by_id = {getattr(c, "id", None): c
                       for c in (getattr(res, "chats", None) or [])}
        users_by_id = {getattr(u, "id", None): u
                       for u in (getattr(res, "users", None) or [])}
        out = []
        for msg in (getattr(res, "messages", None) or []):
            cid = _peer_chat_id(getattr(msg, "peer_id", None))
            chat = chats_by_id.get(cid)
            if chat is None:
                uid = _peer_user_id(getattr(msg, "peer_id", None))
                chat = users_by_id.get(uid)
            if chat is None:
                chat = _BareChat("کانال عمومی")
            text = (getattr(msg, "message", None) or "").strip()
            if not text:
                continue  # media-only posts carry no quotable text
            when = _fmt_date(getattr(msg, "date", None))
            title = _chat_title(chat) or "کانال عمومی"
            out.append(_f("post", f"پست عمومی در {title}",
                          f"{when + ' — ' if when else ''}{text[:200]}",
                          _msg_link(chat, getattr(msg, "id", None))))
        return [f for f in out if f]


# ------------------------------------------------------- provider adapter
class UserbotProvider:
    """Drop-in Provider (same shape as providers.Provider) so the
    existing Engine stores userbot findings into dossiers unchanged.

    Handles telegram_id / username identifiers AND the synthetic
    "tgmsg" identifier (a JSON blob {chat_id, message_id} the bot layer
    stores when the owner forwards a message) — the only ref that can
    scope the global search to a sender without a public username.
    With no client (not activated), every search returns [] — the
    provider is inert and the bot behaves exactly as before."""

    name = SOURCE
    handles = ("telegram_id", "username", "tgmsg")

    def __init__(self, queries=None):
        self.q = queries if queries is not None else UserbotQueries()

    async def run_step(self, step, identifiers, findings=None):
        """On-demand single steps (the owner's order, 2026-11-11 — plain
        search() is untouched). "activity": membership findings + the
        per-target dashboard. "posts": global public-post search
        (channels.SearchPosts) for posts mentioning the dossier's
        username. Both return (findings, html_bytes_or_None)."""
        if step == "posts":
            if not await self.q.connect():
                return [_f("profile", "Userbot status",
                           "یوزربات وصل نشد — سشن لاگین روی این دستگاه فعال "
                           "نیست")], None
            uname = None
            for id_type, value in identifiers:
                if id_type == "username":
                    uname = value.lstrip("@")
                    break
            if not uname:
                return [_f("profile", "Userbot status",
                           "جست‌وجوی سراسری پست‌ها به یوزرنیم تلگرام نیاز "
                           "دارد — این پرونده یوزرنیم ندارد")], None
            return await self.q.search_posts_global(uname), None
        if step != "activity":
            return [], None
        if not await self.q.connect():
            return [_f("profile", "Userbot status",
                       "یوزربات وصل نشد — سشن لاگین روی این دستگاه فعال "
                       "نیست")], None
        ref = None
        for id_type, value in identifiers:
            if id_type == "telegram_id":
                ref = int(value)
                break
            if id_type == "username":
                ref = value.lstrip("@")
        if ref is None:
            for id_type, value in identifiers:
                if id_type == "tgmsg":
                    ref = await self._message_ref(value)
                    break
        if ref is None:
            return [_f("profile", "Userbot status",
                       "این پرونده شناسه‌ی تلگرامی قابل‌استفاده ندارد "
                       "(آیدی عددی یا یوزرنیم لازم است)")], None
        from . import membership
        res = await membership.crawl_target_activity(self.q, ref)
        if res is None:
            return [_f("profile", "Userbot status",
                       "هدف resolve نشد — با یوزرنیم دوباره تلاش کن یا "
                       "یک پیام از طرف فوروارد کن")], None
        return res["findings"], res["html"]

    async def search(self, id_type: str, value: str) -> list:
        # DIAGNOSTICS-FIRST (owner order after a silent failure on
        # 2026-11-10): every step reports its outcome as a finding —
        # a step that yields nothing says WHY (empty vs error name) —
        # instead of the old behaviour where any exception anywhere
        # silently emptied the whole layer.
        notes = []

        def note(text):
            notes.append(_f("profile", "Userbot status", text))

        if not await self.q.connect():
            return [_f("profile", "Userbot status",
                       "یوزربات وصل نشد — api یا سشن لاگین روی این دستگاه "
                       "فعال نیست (python -m userbot.login را بزن)")]
        try:
            ref = value
            if id_type == "telegram_id":
                ref = int(value)
            elif id_type == "username":
                ref = value.lstrip("@")
            elif id_type == "tgmsg":
                ref = await self._message_ref(value)
                if ref is None:
                    note("پیام فورواردشده پیدا نشد — اسکن سراسری رد شد")
                    return [n for n in notes if n]
            findings = []
            steps = []
            photo_ids = []
            for label, coro in (
                    ("profile", self.q.full_user_info(ref)),
                    ("common", self.q.common_chats(ref)),
                    ("global", self.q.global_messages_from(ref))):
                try:
                    got = await coro
                    if label == "profile":
                        got, photo_ids = got
                    findings += got
                    steps.append(f"{label}:{len(got)}")
                except Exception as e:
                    steps.append(f"{label}:ERR {type(e).__name__}")
            # Standing rule: profile photos are delivered as
            # REAL photos, never links. Emit them as photo findings —
            # LOCAL file paths — so the bot layer's photo sender picks
            # them up (one per source) and its sent_photos dedupe
            # keeps each photo from being resent on later searches.
            if photo_ids:
                for path in await self.q.download_photos(
                        ref, [pid for pid, _ in photo_ids]):
                    findings.append(dict(
                        source=SOURCE, category="photo",
                        title="Profile photo", value=path,
                        snippet="profile_photo_file"))
            rerr = getattr(self.q, "last_resolve_error", None)
            if rerr and not findings:
                steps.append(
                    f"این شناسه به کاربر تبدیل نشد (resolve ناموفق: {rerr}) "
                    "— برای آیدی عددیِ سرد، با یوزرنیم جست‌وجو کن یا یک "
                    "پیام از طرف فوروارد کن")
            err = getattr(self.q, "last_scan_error", None)
            if err:
                steps.append(f"اسکن سراسری خطا داد: {err}")
            elif not any(s.startswith("global:") and not s.endswith(":0")
                         for s in steps):
                steps.append(
                    f"اسکن سراسری: تلگرام "
                    f"{getattr(self.q, 'last_scan_count', 0)} پیام اسکن کرد، "
                    "هیچ پیام عمومی‌ای از این شخص برنگرداند")
            note("گام‌ها: " + "، ".join(steps))
            findings += notes
            for path in await self.q.download_media_photos():
                findings.append(dict(
                    source=SOURCE, category="photo",
                    title="Media photo (public message)", value=path,
                    snippet="media_photo_file"))
            return [f for f in findings if f]
        except Exception as e:
            note(f"خطای کلی یوزربات: {type(e).__name__}")
            return [n for n in notes if n]

    async def _message_ref(self, value):
        import json
        try:
            spec = json.loads(value)
            msgs = await self.client_get_messages(
                int(spec["chat_id"]), ids=int(spec["message_id"]))
            return msgs[0] if msgs else None
        except Exception:
            return None

    async def client_get_messages(self, chat_id, ids):
        return await self.q.client.get_messages(chat_id, ids=ids)
