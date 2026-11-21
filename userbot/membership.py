# -*- coding: utf-8 -*-
"""Membership + per-target activity crawl (the owner's order, 2026-11-11).

Answers two questions about ANY target (not just the session account):

1. MEMBERSHIP — which public groups/channels is this person in?
   Honest sources, in order:
   a) GetCommonChats — chats shared between the SESSION account and
      the target. Those memberships are CERTAIN (Telegram itself
      reports them) and the bot surfaces them as findings.
   b) Any chat the crawl below finds the target's messages in is a
      chat their messages are readable in — also surfaced.
   What this module deliberately does NOT do: mass-join groups with
   the session account (a ban/limit magnet, rejected by the owner),
   and it never claims "the person is in exactly these groups" — the
   coverage is exactly the chats the session can read.

2. ACTIVITY DASHBOARD — the same HTML dashboard the owner gets for
   himself (userbot/my_dashboard.py), built for the target: every
   readable chat is crawled and only the target's own messages are
   kept (from_user=target — plus a strict sender re-check in code, so
   nobody else's words are ever attributed to them). The global
   from_id scan's rollup messages are folded in as a supplement.
   Totals are a VISIBLE MINIMUM and are labelled as such.
"""
import asyncio
import random

from . import my_dashboard
from . import userbot_config as uc
from .queries import _chat_link, _chat_title, _f

PER_CHAT_LIMIT = 300          # own messages pulled per readable chat
FLOOD_ABORT = "FloodWait"     # type-name match, as in queries.py


def _label_of(user):
    name = (getattr(user, "first_name", None) or "").strip()
    uname = getattr(user, "username", None)
    return f"{name} (@{uname or user.id})".strip()


async def crawl_target_activity(q, ref, progress=None):
    """q: a connected UserbotQueries. Returns a dict with the resolved
    user, the membership findings (list), the dashboard data dict and
    the HTML — or None when the target cannot be resolved."""
    user = await q.resolve_user(ref)
    if user is None:
        return None
    findings = []
    messages = []
    seen_chats = set()

    def harvest(records, chat_title):
        for rec in records:
            msg = rec.get("_msg")
            sender = None
            if msg is not None:
                from .queries import _peer_user_id
                sender = _peer_user_id(getattr(msg, "from_id", None))
            if sender is not None and sender != user.id:
                continue  # strict: never attribute another's words
            messages.append({
                "date": my_dashboard._fmt_date_iso(rec.get("date")),
                "text": rec.get("text") or "[media]",
                "has_media": bool(rec.get("has_media")),
                "chat": chat_title or rec.get("chat_title")
                        or "(no title)",
            })

    # -- 1. certain memberships (Telegram-reported common chats) ----
    common_titles = []
    try:
        common = await q.common_chats(ref)
    except Exception:
        common = []
    for f in common or []:
        title = f.get("value") or ""
        if title:
            common_titles.append(title)
            findings.append(_f(
                "group", "عضویت مشترک قطعی",
                f"{title} — هم اکانت سشن و هم این شخص عضو این چت‌اند "
                f"(گزارش مستقیم تلگرام)"))
    for f in findings:
        if f:
            pass
    findings = [f for f in findings if f]

    # -- 2. crawl the chats the session can read --------------------
    try:
        async for dialog in q.client.iter_dialogs():
            ent = dialog.entity
            title = _chat_title(ent) or dialog.name or "(no title)"
            if getattr(ent, "broadcast", False):
                continue  # channel posts have no user sender to scope
            await asyncio.sleep(
                random.uniform(uc.PACE_MIN_SECONDS, uc.PACE_MAX_SECONDS))
            try:
                msgs = []
                async for m in q.client.iter_messages(
                        ent, limit=PER_CHAT_LIMIT, from_user=user.id):
                    msgs.append(m)
            except Exception as e:
                if FLOOD_ABORT in type(e).__name__:
                    findings.append(_f(
                        "profile", "وضعیت کراول",
                        "تلگرام محدودیت سرعت زد (FloodWait) — کراول "
                        "همان‌جا متوقف شد، بدون تلاش مجدد؛ نتایج "
                        "نیمه‌کاره نگه داشته شد"))
                    break
                continue
            if msgs:
                seen_chats.add(title)
                from .queries import message_record
                harvest([message_record(m, ent) for m in msgs], title)
            if progress:
                progress(title)
    except Exception:
        pass

    # -- 3. supplement: the global from_id scan's own records --------
    # global_messages_from folds its records into analysis only; pull
    # its rollup findings' messages through the records it keeps.
    try:
        await q.global_messages_from(ref)
        recs = getattr(q, "last_records", None) or []
        harvest(recs, None)
    except Exception:
        pass

    note = ("حداقلِ قابل‌مشاهده — فقط چت‌هایی که اکانت سشن می‌تواند "
            "بخواند؛ چت‌های خصوصی این شخص و گروه‌هایی که سشن در آن‌ها "
            "نیست در این آمار نیست")
    data = my_dashboard.collect_from_messages(
        messages, _label_of(user), note=note)
    findings.append(_f(
        "group", "فعالیت قابل‌مشاهده",
        f"در {len(seen_chats) + len(common_titles)} چتِ قابل‌خواندن "
        f"نشانه‌ی فعالیت/عضویت دیده شد؛ {len(messages)} پیام از این "
        f"شخص جمع شد (حداقلِ قابل‌مشاهده)"))
    return {
        "user": user,
        "findings": [f for f in findings if f],
        "data": data,
        "html": my_dashboard.render_html(data),
        "messages": messages,
        "common_titles": common_titles,
    }
