# -*- coding: utf-8 -*-
"""God's Eye — LOCAL analysis of a person's public Telegram activity.

100% deterministic, on-device, stdlib-only. NO AI, NO network, NO
external calls — this module only counts and ranks what the userbot
layer already collected from Telegram's public index. Every derived
number says what it was computed FROM (the sampled messages), and the
account-age figure is an ESTIMATE from public id ranges, labelled as
such wherever it appears.

Input records are plain dicts built by the query layer from Telethon
message objects:

    {date (aware datetime, UTC), text, chat_title, views, forwards,
     reactions [(emoji, count)], edited (bool), reply_to_user_id,
     has_media (bool), is_channel_post (bool), link}

Output is the project's standard Finding dicts (source telegram_user,
category "analysis"), produced by analysis_findings().
"""
import re
from collections import Counter
from datetime import timezone

try:
    from zoneinfo import ZoneInfo
    TEHRAN = ZoneInfo("Asia/Tehran")
except Exception:  # very old Python / missing tzdata — fall back to UTC
    TEHRAN = timezone.utc

SOURCE = "telegram_user"
WEEKDAYS_FA = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه",
               "جمعه", "شنبه", "یکشنبه"]  # Monday-first, like datetime

# Compact Persian/Arabic + Latin stopwords: words that carry no topic
# signal. Kept deliberately small and boring.
STOPWORDS = set("""
است بود شد شده شود می‌شود نمی‌شود هست نیست این آن که را به از در با بر برای
بی تا چه را و یا نه هم اگر ولی چون پس پیش روی زیر سر خود من تو او ما شما آنها
اینها آنها یکی دیگر همه هیچ هر چه‌طور چرا کجا کی چقدر خیلی زیاد کم بودم باشه
باشم هستم دارم داره دارد ندارم می‌کنم می‌کنی می‌کند می‌کنه نمی‌کنم کردم کردی
کرد گفت می‌گه شده‌ام بوده است‌است یه یک توی رو واسه برایِ الان دیگه فقط شده
the a an and or to of in on for with is are was were be been it its this that
these those i you he she we they me him her us them my your his their our am
""".split())

_TOKEN = re.compile(r"[^\W\d_]{2,}", re.UNICODE)

# Rough public id-range -> registration-era table (community-known
# approximations). An ESTIMATE only; labelled as such in the output.
_ID_ERAS = [
    (100_000_000, "پیش از ۲۰۱۵"),
    (200_000_000, "۲۰۱۵ تا ۲۰۱۶"),
    (350_000_000, "۲۰۱۶ تا ۲۰۱۷"),
    (500_000_000, "۲۰۱۷ تا ۲۰۱۸"),
    (700_000_000, "۲۰۱۸ تا ۲۰۱۹"),
    (1_000_000_000, "۲۰۱۹ تا ۲۰۲۰"),
    (1_300_000_000, "۲۰۲۰ تا ۲۰۲۱"),
    (1_600_000_000, "۲۰۲۱ تا ۲۰۲۲"),
    (2_000_000_000, "۲۰۲۲ تا ۲۰۲۳"),
    (5_000_000_000, "۲۰۲۳"),
    (6_000_000_000, "۲۰۲۳ تا ۲۰۲۴"),
    (7_000_000_000, "۲۰۲۴"),
    (8_000_000_000, "۲۰۲۴ تا ۲۰۲۵"),
]


def _f(title, value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return dict(source=SOURCE, category="analysis", title=title,
                value=str(value).strip()[:500], snippet=None)


def account_age_estimate(user_id):
    """Registration-era ESTIMATE from the numeric id range."""
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None
    for ceiling, era in _ID_ERAS:
        if uid < ceiling:
            return era
    return "۲۰۲۵ به بعد"


def _top(counter, n):
    return ", ".join(f"{k} ({v})" for k, v in counter.most_common(n))


def analysis_findings(records, top_words=15):
    """records: list of message-record dicts (see module docstring).
    Returns analysis Finding dicts; [] for an empty sample."""
    recs = [r for r in records if r.get("date") is not None]
    if not recs:
        return []
    out = []
    n = len(recs)
    out.append(_f("نمونه تحلیل",
                  f"{n} پیام عمومی نمونه‌برداری شد "
                  f"({recs[-1]['date']:%Y-%m-%d} تا {recs[0]['date']:%Y-%m-%d})؛"
                  " همه اعداد زیر فقط از همین نمونه‌اند"))

    hours = Counter()
    days = Counter()
    for r in recs:
        local = r["date"].astimezone(TEHRAN)
        hours[local.hour] += 1
        days[WEEKDAYS_FA[local.weekday()]] += 1
    if hours:
        peak_h, peak_c = hours.most_common(1)[0]
        out.append(_f("ساعات فعالیت (تهران)",
                      f"اوج: {peak_h:02d}:۰۰ ({peak_c} پیام)؛ "
                      f"توزیع: " + ", ".join(
                          f"{h:02d}→{c}" for h, c in sorted(hours.items()))))
        late = sum(c for h, c in hours.items() if h < 5)
        if late:
            out.append(_f("فعالیت نیمه‌شب (۰۰ تا ۰۵ تهران)",
                          f"{late} پیام از {n} ({late * 100 // n}٪)"))
    if days:
        out.append(_f("روزهای هفته", _top(days, 7)))

    words = Counter()
    total_words = 0
    for r in recs:
        for tok in _TOKEN.findall((r.get("text") or "").lower()):
            total_words += 1
            if tok not in STOPWORDS:
                words[tok] += 1
    if words:
        out.append(_f("پرتکرارترین کلمات", _top(words, top_words)))
    if n:
        out.append(_f("حجم و سبک پیام‌ها",
                      f"میانگین طول: {total_words // max(n, 1)} کلمه؛ "
                      f"مدیادار: {sum(1 for r in recs if r.get('has_media'))}؛ "
                      f"ویرایش‌شده: {sum(1 for r in recs if r.get('edited'))}"))

    partners = Counter(r["reply_to_user_id"] for r in recs
                        if r.get("reply_to_user_id"))
    if partners:
        out.append(_f("بیشترین ریپلای به (آیدی کاربر)",
                      _top(partners, 5)))

    posts = [r for r in recs
             if r.get("views") is not None or r.get("reactions")
             or r.get("is_channel_post")]
    if posts:
        total_views = sum(r.get("views") or 0 for r in posts)
        total_fw = sum(r.get("forwards") or 0 for r in posts)
        total_rx = sum(c for r in posts for _, c in (r.get("reactions") or []))
        best = max(posts, key=lambda r: (r.get("views") or 0))
        rx = Counter()
        for r in posts:
            for emoji, c in (r.get("reactions") or []):
                rx[emoji] += c
        stats = (f"{len(posts)} پست دارای آمار؛ مجموع بازدید "
                 f"{total_views}؛ فوروارد {total_fw}؛ ری‌اکشن {total_rx}")
        if rx:
            stats += f"؛ پرتکرارترین ری‌اکشن: {_top(rx, 5)}"
        if best.get("views"):
            stats += f"؛ پربازدیدترین: {best['views']} بازدید"
            if best.get("link"):
                stats += f" — {best['link']}"
        out.append(_f("آمار پست‌ها (بازدید/فوروارد/ری‌اکشن)", stats))

    dates = sorted({r["date"].date() for r in recs})
    if len(dates) >= 2:
        gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
        longest = max(gaps)
        if longest >= 2:
            out.append(_f("طولانی‌ترین سکوت در نمونه",
                          f"{longest} روز بدون پیام عمومیِ نمونه‌برداری‌شده"))
    return [f for f in out if f]
