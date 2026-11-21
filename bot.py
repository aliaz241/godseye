# -*- coding: utf-8 -*-
"""God's Eye (bot-only) — button-driven Telegram bot (Bot API long polling).

User-friendly flow: no slash commands to memorise, no dossier numbers to
type. The owner just sends an identifier (numeric ID, @username, phone,
email or name) as a plain message — or taps the glass buttons — and the
bot asks step by step. Slash commands still work for power users.

Bonus: forward any message from a person to this bot — it reads the
forward origin and creates/updates that person's dossier automatically.
"""
import asyncio

import config
from botapi import BotApi
from db import Database
from engine import Engine, guess_identifier

api = BotApi(config.BOT_TOKEN)
db = Database(config.DB_PATH)
engine = Engine(db, api)

# chat_id -> {"await": "new"|"add", "person_id": int|None}
states = {}

HELP = (
    "God's Eye — جست‌وجوی اطلاعات عمومی (OSINT)\n\n"
    "کافی است یک شناسه بفرستی: آیدی عددی، @یوزرنیم، شماره تلفن، ایمیل یا اسم.\n"
    "بات خودش پرونده می‌سازد و پروفایل عمومی شخص را مستقیم از خود این "
    "شبکه‌های اجتماعی می‌خواند: تلگرام، اینستاگرام، ایکس (توییتر)، "
    "تیک‌تاک، یوتیوب، فیسبوک، لینکدین، تردز، اسنپ‌چت، توییچ، ردیت، "
    "پینترست، آپارات، روبیکا، بله، ایتا، سروش، ویراستی و واتس‌اپ.\n\n"
    "با دکمه‌های زیر کار کن؛ نیازی به حفظ دستور نیست.\n"
    "نکته: یک پیام از شخص را به بات فوروارد کن تا پرونده‌اش خودکار ساخته شود."
)


# ------------------------------------------------------------ keyboards
def btn(text, data):
    return {"text": text, "callback_data": data}


def kb(rows):
    return {"inline_keyboard": rows}


def main_kb():
    rows = [
        [btn("➕ پرونده جدید", "new")],
        [btn("📁 پرونده‌های من", "list")],
    ]
    if getattr(config, "USERBOT_ENABLED", False):
        rows.append([btn("📊 فعالیت‌های من", "myactivity")])
    rows.append([btn("❓ راهنما", "help")])
    return kb(rows)


def person_kb(person_id):
    return kb([
        [btn("🔍 جست‌وجوی کامل", f"search:{person_id}"),
         btn("📄 نمایش پرونده", f"info:{person_id}")],
        [btn("📊 داشبورد فعالیت", f"ubact:{person_id}"),
         btn("🌐 پست‌های عمومی", f"ubposts:{person_id}")],
        [btn("📚 بخش‌های پرونده", f"secs:{person_id}")],
        [btn("➕ افزودن شناسه", f"add:{person_id}")],
        [btn("🗑 حذف پرونده", f"del:{person_id}"),
         btn("📁 پرونده‌ها", "list")],
        [btn("🏠 منوی اصلی", "menu")],
    ])


# ------------------------------------------------- sectioned dossier view
# The dossier is browsed in SECTIONS, so the owner never has to read
# everything at once: profile / public groups (one button per group,
# its messages on their own page) / channel posts / local analysis /
# common chats. Sections are derived from the stored findings only.
SECTION_DEFS = [
    ("profile", "👤 پروفایل", "profile"),
    ("groups", "👥 گروه‌های عمومی", "groups"),
    ("channel", "📣 پست‌های کانال", "channel"),
    ("analysis", "📊 تحلیل لوکال", "analysis"),
    ("common", "🤝 چت‌های مشترک", "common"),
]


def _msg_group_title(f):
    """Group/channel name from a stored 'Message in X' finding title,
    else None. The own-channel rollup has no name in old data, so any
    'Message in <personal channel>' title lands in the channel section."""
    t = f.get("title") or ""
    if t.startswith("Message in "):
        name = t[len("Message in "):].strip()
        return name or None
    return None


def dossier_sections(d):
    """-> ordered [(key, label, [findings])] with empty ones dropped,
    plus ('rest', ...) for anything unclassified. Pure function of the
    stored findings — no database access."""
    out = {k: [] for k, _, _ in SECTION_DEFS}
    out["rest"] = []
    for f in d["findings"]:
        if _is_photo_finding(f):
            continue
        cat, title = f.get("category"), f.get("title") or ""
        if cat == "analysis":
            out["analysis"].append(f)
        elif title == "Common chat":
            out["common"].append(f)
        elif cat == "group" and title == "Active in public groups":
            out["groups"].append(f)
        elif cat == "post":
            name = _msg_group_title(f) or ""
            if "کانال شخصی" in name:
                out["channel"].append(f)
            else:
                out["groups"].append(f)
        elif cat == "profile":
            out["profile"].append(f)
        else:
            out["rest"].append(f)
    secs = [(k, label, out[k]) for k, label, _ in SECTION_DEFS if out[k]]
    if out["rest"]:
        secs.append(("rest", "📦 سایر", out["rest"]))
    return secs


def _section_groups(findings):
    """Within the groups section: [(group_title, [message findings])]
    in dossier order; the rollup summary finding (title 'Active in
    public groups') is section furniture, not a group."""
    groups, order = {}, []
    for f in findings:
        name = _msg_group_title(f)
        if name is None:
            continue
        if name not in groups:
            groups[name] = []
            order.append(name)
        groups[name].append(f)
    return [(name, groups[name]) for name in order]


def _render_findings(findings):
    lines = []
    for f in findings:
        title = f["title"] or f["category"]
        line = f"• {title}: {f['value']}"
        if f["snippet"] and f["snippet"] != f["value"]:
            line += f"\n  {f['snippet'][:200]}"
        lines.append(line)
    return "\n".join(lines) if lines else "چیزی در این بخش نیست."


def sections_kb(person_id, sections):
    rows = [[btn(f"{label} ({len(fs)})", f"sec:{person_id}:{key}")]
            for key, label, fs in sections]
    rows.append([btn("↩️ برگشت به پرونده", f"person:{person_id}")])
    return kb(rows)


def group_list_kb(person_id, groups):
    rows = [[btn(f"👥 {name} ({len(fs)})",
                 f"grp:{person_id}:{i}")]
            for i, (name, fs) in enumerate(groups)]
    rows.append([btn("↩️ بخش‌ها", f"secs:{person_id}")])
    return kb(rows)


def back_kb(person_id=None):
    rows = []
    if person_id:
        rows.append([btn("↩️ برگشت به پرونده", f"person:{person_id}")])
    rows.append([btn("🏠 منوی اصلی", "menu")])
    return kb(rows)


# ------------------------------------------------------------ rendering
async def person_card(person_id) -> str:
    d = await engine.dossier(person_id)
    if not d:
        return "پرونده پیدا نشد."
    p = d["person"]
    lines = [f"📁 پرونده: {p.get('label') or person_id}", "", "شناسه‌ها:"]
    for i in d["identifiers"]:
        lines.append(f"• {i['type']}: {i['value']}")
    # Photo findings are not counted here: they are delivered as real
    # photos (send_person_photos), never as text — v4.3.
    visible = [f for f in d["findings"] if not _is_photo_finding(f)]
    per_source = {}
    for f in visible:
        per_source[f["source"]] = per_source.get(f["source"], 0) + 1
    lines += ["", f"یافته‌ها: {len(visible)}"]
    for source, n in sorted(per_source.items(), key=lambda kv: -kv[1]):
        lines.append(f"• {source}: {n}")
    return "\n".join(lines)


def format_dossier(d: dict) -> str:
    if not d:
        return "پرونده‌ای پیدا نشد."
    p = d["person"]
    lines = [f"پرونده — {p.get('label') or p['id']}", "", "شناسه‌ها:"]
    for i in d["identifiers"]:
        lines.append(f"• {i['type']}: {i['value']}")
    # v4.3: photo findings are EXCLUDED from the text — a photo URL
    # printed here would be a bare link, which the owner banned; the
    # photos themselves are sent as photos instead.
    visible = [f for f in d["findings"] if not _is_photo_finding(f)]
    lines += ["", f"یافته‌ها ({len(visible)}):"]
    current_source = None
    for f in visible:
        if f["source"] != current_source:
            current_source = f["source"]
            lines.append(f"\n[{current_source}]")
        title = f["title"] or f["category"]
        line = f"• {title}: {f['value']}"
        if f["snippet"] and f["snippet"] != f["value"]:
            line += f"\n  {f['snippet'][:200]}"
        lines.append(line)
    return "\n".join(lines)


async def send_long(chat_id, text, reply_markup=None):
    parts = [text[i : i + 4000] for i in range(0, len(text), 4000)] or [""]
    for j, part in enumerate(parts):
        await api.send_message(
            chat_id, part,
            reply_markup=reply_markup if j == len(parts) - 1 else None,
        )


# ------------------------------------------------------------ photos
# v4.3: a profile photo is SENT as a photo or not at all — never
# printed as a URL in any message (the owner's standing rule: data,
# not links). Captions name the platform the photo came from.
def _is_photo_finding(f) -> bool:
    """v4.3 photo findings carry category "photo". Rows stored by
    older versions used category "profile" with title "Profile photo"
    (and the findings table's UNIQUE(person_id, source, value) means
    such a row shadows the new category for the same URL) — treat
    those as photos too, so an existing database behaves identically
    with no migration."""
    return f["category"] == "photo" or f["title"] == "Profile photo"


PHOTO_LABELS = {
    "telegram": "تلگرام",
    "instagram": "اینستاگرام",
    "whatsapp": "واتس‌اپ",
    "eitaa": "ایتا",
    "rubika": "روبیکا",
    "bale": "بله",
    "soroush": "سروش‌پلاس",
    "virasty": "ویراستی",
}
MAX_PHOTOS_PER_DOSSIER = 3


async def collect_photo_jobs(person_id):
    """Up to MAX_PHOTOS_PER_DOSSIER photos to send for this person, as
    (source, photo_ref) — at most one per platform, first-found first.
    photo_ref is a URL stored by a provider (category "photo"), except
    Telegram for a telegram_id dossier: the person's LATEST real
    profile photo is fetched live through the Bot API and referenced
    by file_id (the largest size of the newest photo), replacing any
    stored Telegram URL for the same dossier."""
    d = await engine.dossier(person_id)
    if not d:
        return []
    jobs = {}
    for f in d["findings"]:
        if _is_photo_finding(f) and f["value"] \
                and f["source"] not in jobs:
            jobs[f["source"]] = f["value"]
    for i in d["identifiers"]:
        if i["type"] != "telegram_id":
            continue
        try:
            photos = await api.get_user_profile_photos(
                int(i["value"]), limit=1)
        except Exception:
            photos = None
        if photos and photos.get("photos"):
            sizes = photos["photos"][0] or []
            file_id = None
            for size in sizes:  # sizes come smallest -> largest
                if size.get("file_id"):
                    file_id = size["file_id"]
            if file_id:
                jobs["telegram"] = file_id
        break  # one telegram account per dossier is enough
    items = list(jobs.items())
    # The Telegram photo (the identifier this dossier is usually built
    # around) goes first so the 3-photo cap never drops it.
    items.sort(key=lambda kv: 0 if kv[0] == "telegram" else 1)
    return items[:MAX_PHOTOS_PER_DOSSIER]


async def send_person_photos(chat_id, person_id):
    """Send the dossier's profile photos as real Telegram photos,
    each captioned with its platform. Anything that fails to send is
    skipped silently — the fallback is NEVER the URL as text.

    DEDUPE (owner complaint, 2026-11-10): a photo ref is sent to the
    owner ONCE per person, ever — sent refs are recorded in the DB
    (sent_photos) and skipped on every later search or dossier view.
    A genuinely NEW profile photo has a new ref and is sent once."""
    try:
        jobs = await collect_photo_jobs(person_id)
        sent = await db.list_sent_photos(person_id)
    except Exception:
        return
    for source, ref in jobs:
        if ref in sent:
            continue  # already delivered once — never spam it again
        label = PHOTO_LABELS.get(source, source)
        try:
            res = await api.send_photo(chat_id, ref,
                                       caption=f"عکس پروفایل — {label}")
            # Mark sent ONLY when the API actually delivered — the
            # old code marked unconditionally, so any send that failed
            # (e.g. a local-file ref the sender rejected) was recorded
            # as delivered and could never be retried.
            if res:
                await db.mark_photo_sent(person_id, ref)
        except Exception:
            pass


# ------------------------------------------------------------ core flows
# Persian display labels for progress lines, one per provider (source)
# in registration order.
PROVIDER_LABELS = [
    ("telegram", "تلگرام"),
    ("whatsapp", "واتس‌اپ"),
    ("eitaa", "ایتا"),
    ("rubika", "روبیکا"),
    ("bale", "بله"),
    ("soroush", "سروش"),
    ("virasty", "ویراستی"),
    ("profiles", "شبکه‌های اجتماعی"),
]
_LABEL_OF = dict(PROVIDER_LABELS)


def _fa_num(n) -> str:
    return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def render_progress(note, status, completed):
    """One status line per provider that runs in this search:
    "Telegram ✓ (3)" when done with findings, "— (0)" when done empty,
    "⏳" while still running."""
    planned = status.get("providers") or list(status["results"].keys())
    ordered = [n for n, _ in PROVIDER_LABELS if n in planned]
    ordered += [n for n in planned if n not in ordered]
    lines = [note, "در حال بررسی منابع:"]
    for name in ordered:
        label = _LABEL_OF.get(name, name)
        if name in completed:
            n = len(status["results"].get(name, []))
            mark = "✓" if n else "—"
            lines.append(f"{label} {mark} ({_fa_num(n)})")
        else:
            lines.append(f"{label} ⏳")
    done_n = len([n for n in ordered if n in completed])
    lines.append(
        f"\nمنابع بررسی‌شده: {_fa_num(done_n)} از {_fa_num(len(ordered))}"
        f" — یافته تا این لحظه: {_fa_num(status['new_findings'])}")
    return "\n".join(lines)


async def run_search_with_progress(chat_id, message_id, person_id, note=None):
    """Run the full search, repainting the status message as each
    provider completes (and at least every ~5s), so the bot is never
    silent while it works. The engine caps the search at
    config.SEARCH_DEADLINE seconds."""
    note = note or "در حال جست‌وجوی کامل…"
    latest = {"status": None}
    completed = set()

    async def paint():
        st = latest["status"]
        if st is None:
            return
        try:
            await api.edit_message(
                chat_id, message_id, render_progress(note, st, completed))
        except Exception:
            pass

    async def on_progress(status):
        latest["status"] = status
        if status.get("provider"):
            completed.add(status["provider"])
        await paint()

    async def ticker():
        while True:
            await asyncio.sleep(5)
            await paint()

    tick = asyncio.create_task(ticker())
    try:
        summary = await engine.run_search(person_id, on_progress=on_progress)
    finally:
        tick.cancel()
    await paint()  # final state (also covers the deadline path)
    return summary


def search_outcome_line(summary, added=None, merged=False):
    """One concrete line reporting what a search actually did (v4.2):
    which identifier was attached (and whether two dossiers merged),
    how many NEW findings appeared and from which sources — or, when
    nothing new turned up, a plain statement of that instead of a
    silently re-shown dossier."""
    head = ""
    if added:
        head = f"شناسه {added[0]}: {added[1]} اضافه شد"
        if merged:
            head += " و دو پرونده ادغام شدند"
        head += ". "
    n = summary["new_findings"]
    if n > 0:
        srcs = "، ".join(
            f"{s} ({c})" for s, c in sorted(
                summary["per_source"].items(), key=lambda kv: -kv[1]))
        return (f"✅ {head}جست‌وجو تمام شد — {n} یافته جدید از این منابع: "
                f"{srcs}.")
    return (f"✅ {head}جست‌وجو تمام شد — در منابع بررسی‌شده یافته "
            "جدیدی پیدا نشد.")


async def do_new_dossier(chat_id, raw_text, status_msg_id=None):
    """Create/find the dossier for a raw identifier and run a full
    search. The acknowledgement is the FIRST thing the user sees —
    sent before any provider runs — and is then repainted live as
    each provider completes (see run_search_with_progress)."""
    id_type, value = guess_identifier(raw_text)
    person_id = await engine.resolve_or_create(id_type, value)
    note = f"📁 پرونده ساخته شد ({id_type}: {value})\nدر حال جست‌وجوی کامل…"
    if status_msg_id:
        await api.edit_message(chat_id, status_msg_id, note)
        target_id = status_msg_id
    else:
        sent = await api.send_message(chat_id, note)
        target_id = sent["message_id"]
    summary = await run_search_with_progress(
        chat_id, target_id, person_id, note=note)
    card = await person_card(person_id)
    await api.edit_message(
        chat_id, target_id,
        f"{search_outcome_line(summary)}\n\n{card}",
        reply_markup=person_kb(person_id),
    )
    await send_person_photos(chat_id, person_id)
    return person_id


async def run_dashboard_step(chat_id, message_id, person_id):
    """The "📊 Activity Dashboard" button — membership findings + the per-target HTML
    dashboard (userbot/membership.py via the provider's run_step).
    Mirrors send_my_activity's flow, but for a dossier's person."""
    ub = next((p for p in engine.providers
              if getattr(p, "name", None) == "telegram_user"), None)
    if ub is None or not hasattr(ub, "run_step"):
        await api.edit_message(
            chat_id, message_id,
            "این قابلیت فعال نیست (لایه‌ی یوزربات روی این نصب نیست).",
            reply_markup=person_kb(person_id))
        return
    await api.edit_message(chat_id, message_id,
                           "⏳ در حال کراول چت‌های قابل‌خواندن و ساخت "
                           "داشبورد فعالیت… (ممکن است چند دقیقه طول بکشد)")
    try:
        identifiers = await db.list_identifiers(person_id)
        findings, html = await ub.run_step(
            "activity", [(i["type"], i["value"]) for i in identifiers])
    except Exception as e:
        await api.edit_message(
            chat_id, message_id,
            f"خطا در ساخت داشبورد: {type(e).__name__}: {e}",
            reply_markup=person_kb(person_id))
        return
    search_id = await db.start_search(person_id)
    for f in findings:
        await db.add_finding(person_id, search_id, f["source"],
                             f["category"], f["title"], f["value"],
                             f.get("snippet"))
    await db.finish_search(search_id, "done")
    if html:
        path = "userbot/target_dashboard.html"
        import os
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
        await api.send_document(
            chat_id, path,
            caption="📊 داشبورد فعالیت قابل‌مشاهده‌ی این شخص — حداقلِ "
                    "قابل‌مشاهده، نه کل فعالیت او.")
    card = await person_card(person_id)
    await api.edit_message(chat_id, message_id, card,
                           reply_markup=person_kb(person_id))


async def run_posts_step(chat_id, message_id, person_id):
    """The "🌐 Public Posts" button — global public-post search (channels.
    SearchPosts on the SESSION API, never the bot token) for posts
    mentioning this dossier's username. Mirrors run_dashboard_step's
    flow, but the step returns no document (html is None)."""
    ub = next((p for p in engine.providers
              if getattr(p, "name", None) == "telegram_user"), None)
    if ub is None or not hasattr(ub, "run_step"):
        await api.edit_message(
            chat_id, message_id,
            "این قابلیت فعال نیست (لایه‌ی یوزربات روی این نصب نیست).",
            reply_markup=person_kb(person_id))
        return
    await api.edit_message(chat_id, message_id,
                           "⏳ در حال جست‌وجوی پست‌های عمومی تلگرام…")
    try:
        identifiers = await db.list_identifiers(person_id)
        findings, _html = await ub.run_step(
            "posts", [(i["type"], i["value"]) for i in identifiers])
    except Exception as e:
        await api.edit_message(
            chat_id, message_id,
            f"خطا در جست‌وجوی پست‌ها: {type(e).__name__}: {e}",
            reply_markup=person_kb(person_id))
        return
    search_id = await db.start_search(person_id)
    for f in findings:
        await db.add_finding(person_id, search_id, f["source"],
                             f["category"], f["title"], f["value"],
                             f.get("snippet"))
    await db.finish_search(search_id, "done")
    card = await person_card(person_id)
    await api.edit_message(chat_id, message_id, card,
                           reply_markup=person_kb(person_id))


async def do_search(chat_id, message_id, person_id, added=None, merged=False):
    summary = await run_search_with_progress(
        chat_id, message_id, person_id, note="🔍 در حال جست‌وجوی کامل…")
    card = await person_card(person_id)
    await api.edit_message(
        chat_id, message_id,
        f"{search_outcome_line(summary, added=added, merged=merged)}\n\n{card}",
        reply_markup=person_kb(person_id),
    )
    await send_person_photos(chat_id, person_id)


async def show_persons(chat_id, message_id=None):
    persons = await db.list_persons()
    text = "📁 پرونده‌های من:" if persons else "هنوز پرونده‌ای ساخته نشده است."
    rows = []
    for p in persons:
        label = p.get("label") or str(p["id"])
        rows.append([btn(f"📁 {label} — {p['n_find']} یافته",
                         f"person:{p['id']}")])
    rows.append([btn("➕ پرونده جدید", "new")])
    rows.append([btn("🏠 منوی اصلی", "menu")])
    if message_id:
        await api.edit_message(chat_id, message_id, text, reply_markup=kb(rows))
    else:
        await api.send_message(chat_id, text, reply_markup=kb(rows))


# ------------------------------------------------- my activity (self-only)
async def send_my_activity(chat_id):
    """Owner-only, self-only: builds the activity dashboard (see
    userbot/my_dashboard.py) from the OWNER'S OWN messages and sends it
    as a file. Takes no identifier — always the logged-in account only."""
    ub = next((p for p in engine.providers
              if getattr(p, "name", None) == "telegram_user"), None)
    if ub is None:
        await api.send_message(
            chat_id, "این قابلیت فعال نیست (USERBOT_ENABLED خاموش است یا "
                     "telethon نصب نیست).")
        return
    if not await ub.q.connect():
        await api.send_message(
            chat_id, "یوزربات وصل نشد — سشن لاگین روی این دستگاه فعال "
                     "نیست (python -m userbot.login را بزن).")
        return
    sent = await api.send_message(
        chat_id, "⏳ در حال جمع‌آوری فعالیت‌های شما از همه‌ی چت‌ها... "
                 "(ممکن است چند دقیقه طول بکشد)")
    try:
        from userbot import my_dashboard
        client = ub.q.client
        me = await client.get_me()
        data = await my_dashboard.collect_data(
            client, me, progress=lambda s: None)
        html = my_dashboard.render_html(data)
        path = my_dashboard.OUTPUT_FILE
        import os
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
        await api.send_document(
            chat_id, path, caption="📊 داشبورد فعالیت‌های شما — بازش کن "
                                   "با مرورگر.")
    except Exception as e:
        await api.send_message(chat_id, f"خطا در ساخت گزارش: {type(e).__name__}: {e}")
    finally:
        await api.edit_message(chat_id, sent["message_id"], "✅ انجام شد.")


# ------------------------------------------------------------ forwards
def is_owner(uid) -> bool:
    owners = set(getattr(config, "OWNER_IDS", None) or [config.OWNER_ID])
    return config.OWNER_ID == 0 or uid in owners


def allowed(msg) -> bool:
    sender = (msg.get("from") or {}).get("id")
    return is_owner(sender)


def extract_forward_user(msg):
    origin = msg.get("forward_origin")
    if origin:
        if origin.get("type") == "user":
            u = origin.get("sender_user") or {}
            return {"id": u.get("id"), "first_name": u.get("first_name"),
                    "last_name": u.get("last_name"), "username": u.get("username")}
        if origin.get("type") == "hidden_user":
            return {"id": None, "first_name": origin.get("sender_user_name"),
                    "last_name": None, "username": None}
        return None
    u = msg.get("forward_from")
    if u:
        return {"id": u.get("id"), "first_name": u.get("first_name"),
                "last_name": u.get("last_name"), "username": u.get("username")}
    if msg.get("forward_sender_name"):
        return {"id": None, "first_name": msg["forward_sender_name"],
                "last_name": None, "username": None}
    return None


async def handle_forward(msg, chat_id):
    user = extract_forward_user(msg)
    if not user:
        return
    if user.get("id"):
        # Instant acknowledgement first; the card replaces it below.
        ack = await api.send_message(chat_id, "📁 پرونده از فوروارد در حال ساخته شدن…")
        person_id = await engine.resolve_or_create("telegram_id", str(user["id"]))
        name = " ".join(x for x in [user.get("first_name"), user.get("last_name")] if x).strip()
        if name:
            await db.add_finding(person_id, None, "forward", "profile",
                                 "Display name", name, None)
        if user.get("username"):
            await engine.attach(person_id, "username", user["username"])
            await db.add_finding(person_id, None, "forward", "profile",
                                 "Username", "@" + user["username"],
                                 f"https://t.me/{user['username']}")
        card = await person_card(person_id)
        await api.edit_message(
            chat_id, ack["message_id"],
            f"از پیام فورواردشده این پرونده ساخته/به‌روز شد:\n\n{card}",
            reply_markup=person_kb(person_id),
        )
    else:
        await api.send_message(
            chat_id,
            "این فوروارد از حسابی است که نمایش آیدی را مخفی کرده؛ فقط اسم قابل "
            f"برداشت بود: {user.get('first_name') or '—'}",
            reply_markup=main_kb(),
        )


# ------------------------------------------------------------ messages
async def handle_message(msg):
    chat_id = msg["chat"]["id"]
    if not allowed(msg):
        return
    if msg.get("forward_origin") or msg.get("forward_from") or msg.get("forward_sender_name"):
        await handle_forward(msg, chat_id)
        return
    text = (msg.get("text") or "").strip()
    if not text:
        return

    state = states.get(chat_id)

    # step-by-step flows: the user is answering a question the bot asked
    if state and not text.startswith("/"):
        if state["await"] == "new":
            states.pop(chat_id, None)
            await do_new_dossier(chat_id, text)
            return
        if state["await"] == "add":
            person_id = state["person_id"]
            states.pop(chat_id, None)
            id_type, value = guess_identifier(text)
            # If the identifier belonged to another dossier, engine
            # merges that dossier into this one (v4.2) — the attach
            # always takes effect on THIS dossier now.
            person_id, merged_from = await engine.attach(
                person_id, id_type, value)
            ack = f"شناسه {id_type}: {value} اضافه شد."
            if merged_from:
                ack += " دو پرونده ادغام شدند؛ حالا یک پرونده واحد داری."
            ack += " در حال جست‌وجو با داده جدید…"
            sent = await api.send_message(chat_id, ack)
            await do_search(chat_id, sent["message_id"], person_id,
                            added=(id_type, value),
                            merged=bool(merged_from))
            return

    if text.startswith("/"):
        parts = text.split(maxsplit=3)
        cmd = parts[0].split("@")[0].lower()
        if cmd in ("/start", "/menu"):
            states.pop(chat_id, None)
            await api.send_message(chat_id, HELP, reply_markup=main_kb())
        elif cmd == "/new" and len(parts) >= 2:
            raw = text.split(maxsplit=1)[1]
            await do_new_dossier(chat_id, raw)
        elif cmd == "/persons":
            await show_persons(chat_id)
        elif cmd == "/myactivity":
            await send_my_activity(chat_id)
        elif cmd == "/info" and len(parts) == 2 and parts[1].isdigit():
            d = await engine.dossier(int(parts[1]))
            await send_long(chat_id, format_dossier(d),
                            reply_markup=back_kb(int(parts[1])))
            await send_person_photos(chat_id, int(parts[1]))
        elif cmd == "/search" and len(parts) == 2 and parts[1].isdigit():
            sent = await api.send_message(chat_id, "🔍 در حال جست‌وجو…")
            await do_search(chat_id, sent["message_id"], int(parts[1]))
        return

    # plain text with no active flow = a fresh identifier. Just search it.
    await do_new_dossier(chat_id, text)


# ------------------------------------------------------------ callbacks
async def handle_callback(cq):
    msg = cq.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    message_id = msg.get("message_id")
    sender = (cq.get("from") or {}).get("id")
    if not is_owner(sender):
        await api.answer_callback_query(cq["id"])
        return
    data = cq.get("data") or ""
    await api.answer_callback_query(cq["id"])
    if chat_id is None or message_id is None:
        return

    if data == "menu":
        states.pop(chat_id, None)
        await api.edit_message(chat_id, message_id, HELP, reply_markup=main_kb())
    elif data == "help":
        await api.edit_message(chat_id, message_id, HELP, reply_markup=main_kb())
    elif data == "new":
        states[chat_id] = {"await": "new", "person_id": None}
        await api.edit_message(
            chat_id, message_id,
            "شناسه را بفرست — آیدی عددی، @یوزرنیم، شماره تلفن، ایمیل یا اسم:",
            reply_markup=back_kb(),
        )
    elif data == "list":
        await show_persons(chat_id, message_id)
    elif data == "myactivity":
        await send_my_activity(chat_id)
    elif data.startswith("person:"):
        person_id = int(data.split(":")[1])
        card = await person_card(person_id)
        await api.edit_message(chat_id, message_id, card,
                               reply_markup=person_kb(person_id))
    elif data.startswith("search:"):
        await do_search(chat_id, message_id, int(data.split(":")[1]))
    elif data.startswith("ubact:"):
        await run_dashboard_step(chat_id, message_id,
                                 int(data.split(":")[1]))
    elif data.startswith("ubposts:"):
        await run_posts_step(chat_id, message_id,
                             int(data.split(":")[1]))
    elif data.startswith("secs:"):
        person_id = int(data.split(":")[1])
        d = await engine.dossier(person_id)
        secs = dossier_sections(d) if d else []
        if not secs:
            await api.edit_message(
                chat_id, message_id, "هنوز یافته‌ای در پرونده نیست.",
                reply_markup=back_kb(person_id))
        else:
            await api.edit_message(
                chat_id, message_id,
                "📚 بخش‌های پرونده — هر بخش جدا باز می‌شود:",
                reply_markup=sections_kb(person_id, secs))
    elif data.startswith("sec:"):
        _, pid, key = data.split(":", 2)
        person_id = int(pid)
        d = await engine.dossier(person_id)
        secs = dict((k, (label, fs))
                    for k, label, fs in (dossier_sections(d) if d else []))
        if key not in secs:
            await api.edit_message(chat_id, message_id,
                                   "این بخش خالی شده است.",
                                   reply_markup=back_kb(person_id))
        elif key == "groups":
            label, fs = secs[key]
            roll = [f for f in fs
                    if f["title"] == "Active in public groups"]
            groups = _section_groups(fs)
            head = _render_findings(roll) if roll else ""
            await api.edit_message(
                chat_id, message_id,
                (f"👥 گروه‌های عمومی\n{head}\n\n"
                 "پیام‌های هر گروه جداست — گروه را انتخاب کن:")
                if groups else f"👥 گروه‌های عمومی\n{head}",
                reply_markup=group_list_kb(person_id, groups)
                if groups else back_kb(person_id))
        else:
            label, fs = secs[key]
            await api.edit_message(
                chat_id, message_id,
                f"{label} — در پیام بعدی ارسال شد.",
                reply_markup=kb(
                    [[btn("↩️ بخش‌ها", f"secs:{person_id}")]]))
            await send_long(chat_id, f"{label}\n\n{_render_findings(fs)}",
                            reply_markup=kb(
                                [[btn("↩️ بخش‌ها", f"secs:{person_id}")]]))
    elif data.startswith("grp:"):
        _, pid, idx = data.split(":", 2)
        person_id = int(pid)
        d = await engine.dossier(person_id)
        secs = dict((k, fs) for k, _, fs in
                    (dossier_sections(d) if d else []))
        groups = _section_groups(secs.get("groups", []))
        i = int(idx)
        if 0 <= i < len(groups):
            name, fs = groups[i]
            await api.edit_message(
                chat_id, message_id,
                f"👥 {name} — پیام‌ها در پیام بعدی ارسال شد.",
                reply_markup=kb(
                    [[btn("↩️ گروه‌ها", f"sec:{person_id}:groups")]]))
            await send_long(
                chat_id, f"👥 {name}\n\n{_render_findings(fs)}",
                reply_markup=kb(
                    [[btn("↩️ گروه‌ها", f"sec:{person_id}:groups")]]))
        else:
            await api.edit_message(chat_id, message_id,
                                   "این گروه دیگر در پرونده نیست.",
                                   reply_markup=back_kb(person_id))
    elif data.startswith("info:"):
        person_id = int(data.split(":")[1])
        d = await engine.dossier(person_id)
        await api.edit_message(chat_id, message_id,
                               "📄 پرونده کامل در پیام بعدی ارسال شد.")
        await send_long(chat_id, format_dossier(d),
                        reply_markup=person_kb(person_id))
        await send_person_photos(chat_id, person_id)
    elif data.startswith("add:"):
        person_id = int(data.split(":")[1])
        states[chat_id] = {"await": "add", "person_id": person_id}
        await api.edit_message(
            chat_id, message_id,
            "شناسه جدید را بفرست (مثلاً شماره تلفن یا یوزرنیم دیگر او):",
            reply_markup=back_kb(person_id),
        )
    elif data.startswith("del:"):
        person_id = int(data.split(":")[1])
        rows = [[btn("⚠️ بله، حذف شود", f"delyes:{person_id}"),
                 btn("↩️ انصراف", f"person:{person_id}")]]
        await api.edit_message(chat_id, message_id,
                               "این پرونده و همه یافته‌هایش حذف شود؟",
                               reply_markup=kb(rows))
    elif data.startswith("delyes:"):
        person_id = int(data.split(":")[1])
        await db.delete_person(person_id)
        await api.edit_message(chat_id, message_id, "🗑 پرونده حذف شد.")
        await show_persons(chat_id)


async def main():
    print("God's Eye (bot-only) is running.")
    offset = None
    while True:
        try:
            updates = await api.get_updates(offset=offset, timeout=config.POLL_TIMEOUT)
        except Exception as e:
            print("polling error:", e)
            await asyncio.sleep(3)
            continue
        for update in updates:
            offset = update["update_id"] + 1
            try:
                if update.get("message"):
                    await handle_message(update["message"])
                elif update.get("callback_query"):
                    await handle_callback(update["callback_query"])
            except Exception as e:
                print("handler error:", e)


if __name__ == "__main__":
    asyncio.run(main())
