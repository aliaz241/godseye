# -*- coding: utf-8 -*-
"""God's Eye (bot-only) — search providers. Public sources only.

v4 design rule (learned from v3.1 false positives): a provider may emit
a finding ONLY from data it actually extracted from a page that PROVES
the profile exists. Generic site metadata (a platform's own default
og:title / og:image) is never a person's data.

- TelegramWebProvider: the public t.me/<username> preview page
  (validated: t.me shows a generic "Telegram: Contact @…" page for
  usernames that do not exist — those yield zero findings).
- TelegramBotApiProvider: REMOVED from the registry (2026-11-11,
  owner's order) — the bot token is for DISPLAY only (receiving the
  owner's messages, sending cards/photos/documents); it must never
  drive a search. Numeric-id Telegram lookups now run on the userbot
  (MTProto session) layer. The class is kept below, unregistered.
- WhatsAppProvider: wa.me/<number>. NOTE (verified 2026-10-22 by
  fetching real pages): today's wa.me landing page is byte-identical
  for numbers with and without WhatsApp — same generic og:title
  "Share on WhatsApp", same generic static.whatsapp.net/rsrc.php
  og:image, and the continue-to-chat link is present even for invalid
  numbers, so none of those is evidence. The provider therefore emits
  ONLY on an explicit invalid marker (-> "not found") or on a real
  user photo hosted on pps.whatsapp.net (-> account exists + photo).
  Otherwise it stays silent — no guessing.
- Iranian providers (first-class, deep): Eitaa, Rubika, Bale, Soroush,
  Virasty — each parses the platform's real public channel page.
- UsernameProfileProvider: for a username, visits each platform and
  extracts the actual public profile data through public JSON APIs or
  strictly validated profile pages.

v4.1: general web search (Bing/DDG chains and per-platform site:
queries) was REMOVED entirely — the owner never wanted it, and the
fallback chains timed out one by one on Iranian networks, leaving the
bot silent for minutes. Only direct providers remain: each one reads
the platform's own public API or profile page. The scope is SOCIAL
MEDIA ONLY (owner's order): Telegram, Instagram, X, TikTok, YouTube,
Facebook, Threads, Snapchat, Twitch, Reddit, Pinterest, Aparat and
the Iranian messengers; dev/gaming/blog sites and Gravatar are gone,
so email identifiers simply yield no provider results.

v4.2: Instagram was silently broken two ways — the profile page was
fetched with a browser UA (Instagram answers that UA with a data-less
shell carrying no og tags) and the parser blanket-rejected any page
containing "/accounts/login", a string present in real profile pages
too. Instagram (and every og-based social fetch) now goes out with
the link-preview crawler UA (CRAWLER_HEADERS), and the parser proves
existence strictly from og data naming the exact username.

v4.3: photos are data, not links. Every avatar a provider discovers
is stored as a finding with category "photo" — the dossier text
formatter excludes those, and the bot SENDS them as real Telegram
photos after the result (URL first, upload on failure; both failing
means silence, never a text link). Telegram username dossiers get
the t.me og:image avatar; telegram_id dossiers get the latest real
profile photo through the Bot API. Instagram gained route A
(web_profile_info JSON — the only public source of the biography),
with the v4.2 crawler-og parse kept as route B fallback.

Finding = dict(source, category, title, value, snippet)
"""
import asyncio
import json
import re
from html import unescape as _unescape
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup

import config

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}

# Link-preview crawler UA. Meta's platforms serve a data-less app shell
# to browser UAs, but answer this UA with the page's full public og data
# (verified live 2026-10-22: instagram.com/nasa with a browser UA has no
# og tags at all; with this UA it returns og:title / og:description with
# follower counts / og:image). Used for Instagram and for every og-based
# social fetch — the same link-preview mechanism everywhere.
CRAWLER_HEADERS = {"User-Agent": "facebookexternalhit/1.1"}


async def fetch_text(url: str, timeout_s=None, headers=None):
    """GET a page; returns the body only on HTTP 200, else None.
    (Non-200 therefore already proves nothing was extracted.)
    `headers` overrides/extends the default HEADERS for this request."""
    try:
        timeout = aiohttp.ClientTimeout(total=timeout_s or config.REQUEST_TIMEOUT)
        merged = {**HEADERS, **(headers or {})}
        async with aiohttp.ClientSession(headers=merged, timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                return await resp.text()
    except Exception:
        return None


async def fetch_json(url: str, headers=None):
    try:
        timeout = aiohttp.ClientTimeout(total=config.REQUEST_TIMEOUT)
        merged = {**HEADERS, **(headers or {})}
        async with aiohttp.ClientSession(headers=merged, timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                return await resp.json(content_type=None)
    except Exception:
        return None


def _f(source, title, value):
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    return dict(source=source, category="profile", title=title,
                value=str(value).strip()[:500], snippet=None)


def _photo(source, url):
    """A discovered profile-photo URL. v4.3 rule (owner's order: data,
    not links — and a photo URL printed as text IS a link): photo
    findings carry category "photo" and are NEVER rendered into the
    dossier text; the bot layer sends them as real Telegram photos
    (see bot.send_person_photos). The URL is not truncated — a
    truncated CDN URL would not load."""
    if url is None or (isinstance(url, str) and not url.strip()):
        return None
    return dict(source=source, category="photo", title="Profile photo",
                value=str(url).strip(), snippet=None)


def _date(ts):
    """Epoch (s or ms) -> YYYY-MM-DD."""
    try:
        import datetime as _dt
        if ts > 10_000_000_000:
            ts = ts / 1000
        return _dt.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d")
    except Exception:
        return None


# ------------------------------------------------- strict page validation
def _og_tags(html: str) -> dict:
    """All og:* meta + canonical + <title> of a page, as plain strings."""
    soup = BeautifulSoup(html, "html.parser")

    def meta(prop):
        tag = soup.find("meta", attrs={"property": prop})
        return tag.get("content", "").strip() if tag and tag.get("content") else ""

    canon = soup.find("link", attrs={"rel": "canonical"})
    return {
        "title": meta("og:title"),
        "description": meta("og:description"),
        "image": meta("og:image"),
        "url": meta("og:url"),
        "canonical": canon.get("href", "").strip() if canon else "",
        "page_title": soup.title.get_text(strip=True) if soup.title else "",
    }


def _url_mentions_user(og: dict, username: str) -> bool:
    u = username.lower()
    for key in ("url", "canonical"):
        v = (og.get(key) or "").lower()
        if u and (f"/{u}" in v or f"@{u}" in v):
            return True
    return False


def validate_profile_page(html, username, not_found_markers=(),
                          default_titles=()):
    """Strict existence proof for a profile page (caller guarantees the
    fetch returned HTTP 200 via fetch_text).

    Returns the page's og dict when the profile provably exists:
    - no platform not-found marker anywhere in the page, AND
    - an og:title is present, AND
    - the og:url / canonical points at this username, OR the title is
      not one of the site's default titles.
    A page whose only identity is the site's own default title
    (e.g. og:title == "Twitch") proves nothing -> None."""
    if not html:
        return None
    low = html.lower()
    for mk in not_found_markers:
        if mk and mk.lower() in low:
            return None
    og = _og_tags(html)
    title = og["title"]
    if not title:
        return None
    defaults = {t.lower() for t in default_titles}
    if title.strip().lower() in defaults:
        # Default site title: only a canonical URL naming this exact
        # user can still prove the profile (its *name* stays unproven
        # and callers must not emit it — see parse_og_profile).
        return og if _url_mentions_user(og, username) else None
    if _url_mentions_user(og, username) or username.lower() in title.lower():
        return og
    # Non-default title and no marker: per the v4 rule this is a real
    # profile title (a site-wide shell would carry the default title).
    return og


# Per-platform not-found markers found in the real pages (2026-10-22).
OG_NOT_FOUND = {
    "steam": ("the specified profile could not be found",),
    "soundcloud": ("we can't find that", "we can’t find that",
                   "we couldn't find that"),
    "twitch": ("this channel is unavailable",),
    "medium": ("page not found",),
    "behance": ("page not found",),
    "facebook": ("this content isn't available", "page not found"),
    "snapchat": ("can't find that user", "can’t find that user"),
}

# og:title values that are the SITE's name, not a person's — a page with
# one of these titles has not proven any display name.
OG_DEFAULT_TITLES = {
    "twitch": ("Twitch",),
    "medium": ("Medium",),
    "pinterest": ("Pinterest",),
    "vk": ("VK", "VK | VK"),
    "threads": ("Threads", "Threads • Log in"),
    "snapchat": ("Snapchat",),
    "facebook": ("Facebook",),
    "aparat": ("Aparat", "آپارات - سرویس اشتراک ویدیو"),
    "behance": ("Behance",),
    "vimeo": ("Vimeo",),
    "dribbble": ("Dribbble",),
    "linktree": ("Linktree",),
    "patreon": ("Patreon",),
    "aboutme": ("about.me",),
    "soundcloud": ("SoundCloud",),
    "steam": ("Steam Community", "Steam Community :: Error"),
}

# Cosmetic cleanup of real titles ("shroud - Twitch" -> "shroud").
OG_TITLE_CLEANUP = {
    "twitch": (" - Twitch",),
    "linktree": (" | Linktree",),
    "steam": ("Steam Community :: ",),
    "aboutme": (" on about.me",),
    "youtube": (" - YouTube",),
}


class Provider:
    name = "base"
    handles = ()

    async def search(self, id_type: str, value: str) -> list:
        raise NotImplementedError


# ---------------------------------------------------------------- Telegram
def parse_tme_page(html: str, username: str) -> list:
    soup = BeautifulSoup(html, "html.parser")

    def meta(prop):
        tag = soup.find("meta", attrs={"property": prop})
        return tag.get("content", "").strip() if tag else ""

    # t.me serves a generic "Telegram: Contact @<username>" page for
    # usernames that do not exist (verified on real pages). Only a real
    # profile/channel page carries the tgme_page_title block.
    og_title = meta("og:title")
    if og_title.lower().startswith("telegram: contact"):
        return []
    title_el = soup.select_one(".tgme_page_title")
    if title_el is None and soup.select_one(".tgme_page_photo") is None:
        return []
    findings = []
    name = title_el.get_text(" ", strip=True) if title_el else og_title
    if name:
        findings.append(dict(source="telegram", category="profile",
                             title="Display name", value=name, snippet=None))
    desc_el = soup.select_one(".tgme_page_description")
    desc = desc_el.get_text(" ", strip=True) if desc_el else meta("og:description")
    if desc and desc.lower() not in (
        f"contact @{username}".lower(),
        "open in telegram",
    ) and username.lower() not in desc.lower().replace("contact ", ""):
        findings.append(dict(source="telegram", category="profile",
                             title="Bio / description", value=desc, snippet=None))
    extra_el = soup.select_one(".tgme_page_extra")
    if extra_el:
        extra = extra_el.get_text(" ", strip=True)
        if extra:
            findings.append(dict(source="telegram", category="profile",
                                 title="Page info", value=extra, snippet=None))
    # The page's og:image IS the account's current avatar (t.me only
    # serves it on real profile/channel pages — the generic Contact
    # page was already rejected above). Stored as a photo finding:
    # the bot sends it as a real photo, never as a text link (v4.3).
    photo = _photo("telegram", meta("og:image"))
    if photo:
        findings.append(photo)
    return findings


class TelegramWebProvider(Provider):
    name = "telegram"
    handles = ("username",)

    async def search(self, id_type: str, value: str) -> list:
        username = value.lstrip("@")
        html = await fetch_text(f"https://t.me/{username}")
        if not html or "tgme_page" not in html:
            return []
        return parse_tme_page(html, username)


class TelegramBotApiProvider(Provider):
    name = "telegram"
    handles = ("telegram_id",)

    def __init__(self, api):
        self.api = api

    async def search(self, id_type: str, value: str) -> list:
        try:
            chat = await self.api.get_chat(int(value))
        except Exception:
            return []
        if not chat:
            return []
        findings = []
        name = " ".join(x for x in [chat.get("first_name"), chat.get("last_name")] if x).strip()
        if name:
            findings.append(dict(source=self.name, category="profile",
                                 title="Display name", value=name, snippet=None))
        if chat.get("username"):
            findings.append(dict(source=self.name, category="profile",
                                 title="Username", value="@" + chat["username"],
                                 snippet=f"https://t.me/{chat['username']}"))
        if chat.get("bio"):
            findings.append(dict(source=self.name, category="profile",
                                 title="Bio", value=chat["bio"], snippet=None))
        try:
            photos = await self.api.get_user_profile_photos(int(value))
        except Exception:
            photos = None
        if photos and photos.get("total_count"):
            findings.append(dict(
                source=self.name, category="profile", title="Profile photos",
                value=f"{photos['total_count']} photo(s) visible to the bot",
                snippet=None))
        return findings


# ---------------------------------------------------------------- WhatsApp
def normalize_phone(value: str) -> str:
    """Normalize to international digits (no '+').
    Iranian local numbers (09xxxxxxxxx) are converted to 98xxxxxxxxxx."""
    digits = re.sub(r"\D", "", value or "")
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("09") and len(digits) == 11:
        digits = "98" + digits[1:]
    return digits


# Explicit "this number cannot be reached" texts WhatsApp itself serves.
WA_INVALID_MARKERS = (
    "phone number shared via url is invalid",
    "the phone number you are trying to reach is invalid",
    "this link is invalid",
)


def parse_wa_page(html: str, digits: str) -> dict:
    """Decide WhatsApp account existence from a wa.me landing page.

    Returns {"exists": True, "photo": url} / {"exists": False} /
    {"exists": None} (no conclusive public signal -> caller stays silent).

    Evidence rules (verified against real pages, 2026-10-22):
    - The generic og:image under static.whatsapp.net/rsrc.php is the
      WhatsApp *share* image shown for every number — it is NOT a
      profile photo and is rejected here.
    - The og:title "Share on WhatsApp" is the site's share title, not
      a person's name — never returned.
    - A continue-to-chat link exists even for invalid numbers, so it
      proves nothing on its own.
    - A real profile photo is hosted on pps.whatsapp.net; only that
      proves the account (and is returned as the photo).
    """
    low = html.lower()
    if any(mk in low for mk in WA_INVALID_MARKERS):
        return {"exists": False, "photo": None}
    m = re.search(r"https://pps\.whatsapp\.net/[^\"'\s<>]+", html)
    if m:
        return {"exists": True, "photo": m.group(0)}
    return {"exists": None, "photo": None}


class WhatsAppProvider(Provider):
    name = "whatsapp"
    handles = ("phone",)

    async def search(self, id_type: str, value: str) -> list:
        digits = normalize_phone(value)
        if len(digits) < 7:
            return []
        html = await fetch_text(f"https://wa.me/{digits}")
        if html is None:
            return []
        info = parse_wa_page(html, digits)
        if info["exists"] is None:
            return []
        findings = [dict(source=self.name, category="presence",
                         title="WhatsApp account",
                         value=("yes" if info["exists"] else "not found"),
                         snippet=f"https://wa.me/{digits}")]
        if info["exists"] and info["photo"]:
            photo = _photo(self.name, info["photo"])
            if photo:
                findings.append(photo)
        return findings


# ------------------------------------------------------- Iranian platforms
# Deep public-page providers for the Iranian messengers. Usernames /
# channel ids only — none of these platforms exposes a public
# phone->profile mapping and none is faked here.

def parse_eitaa_page(html: str, username: str) -> list:
    """eitaa.com/<id> channel page (server-rendered). A page without the
    channel-info block is Eitaa's generic "Contact @…" page, shown for
    ids with no public channel -> zero findings."""
    soup = BeautifulSoup(html, "html.parser")
    info = soup.select_one(".etme_channel_info")
    if info is None:
        return []
    uname_el = info.select_one(".etme_channel_info_header_username")
    if uname_el is not None and username.lower() not in uname_el.get_text().lower():
        return []
    source = "eitaa"
    findings = []
    title_el = info.select_one(".etme_channel_info_header_title")
    name = title_el.get_text(" ", strip=True) if title_el else ""
    findings.append(_f(source, "Display name", name))
    img = info.select_one(".etme_page_photo_image img")
    if img is not None and img.get("src"):
        findings.append(_photo(source,
                               urljoin("https://eitaa.com", img["src"])))
    for counter in info.select(".etme_channel_info_counter"):
        ctype = counter.select_one(".counter_type")
        cval = counter.select_one(".counter_value")
        if ctype is None or cval is None:
            continue
        if "دنبال" in ctype.get_text():  # the Persian word for "followers"
            raw = cval.get("data-count") or cval.get_text(strip=True)
            findings.append(_f(source, "Subscribers", raw))
    desc_el = info.select_one(".etme_channel_info_description")
    if desc_el is not None:
        findings.append(_f(source, "Bio / description",
                           desc_el.get_text(" ", strip=True)))
    # Recent posts: the widget lists messages oldest -> newest; keep the
    # last (most recent) five that carry text.
    posts = []
    for msg in soup.select(".etme_widget_message"):
        text_el = msg.select_one(".etme_widget_message_text")
        if text_el is None:
            continue
        text = text_el.get_text(" ", strip=True)
        if not text:
            continue
        date = None
        time_el = msg.select_one(".etme_widget_message_date time")
        if time_el is not None:
            date = time_el.get("datetime") or time_el.get_text(strip=True)
        posts.append((text[:200], date))
    for text, date in posts[-5:]:
        findings.append(dict(
            source=source, category="post",
            title=(f"Recent post ({date[:10]})" if date else "Recent post"),
            value=text, snippet=None))
    return [x for x in findings if x]


class EitaaProvider(Provider):
    name = "eitaa"
    handles = ("username",)

    async def search(self, id_type: str, value: str) -> list:
        username = value.lstrip("@")
        html = await fetch_text(f"https://eitaa.com/{username}")
        if not html:
            return []
        return parse_eitaa_page(html, username)


def parse_rubika_page(html: str, username: str) -> list:
    """rubika.ir/<id>. An existing channel gets a preview page carrying
    the channel title, bio, subscriber line, avatar and a
    rubika://l.rubika.ir/<id> deep link; a nonexistent id gets the
    generic super-app landing with none of those -> zero findings."""
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one(".l-title") or soup.select_one(".user-title")
    deep_link = re.search(
        r"rubika://l\.rubika\.ir/" + re.escape(username) + r"[^0-9A-Za-z_]",
        html, re.IGNORECASE)
    if title_el is None and not deep_link:
        return []
    source = "rubika"
    findings = []
    findings.append(_f(source, "Display name",
                       title_el.get_text(" ", strip=True) if title_el else None))
    desc_el = soup.select_one(".l-desc")
    if desc_el is not None:
        findings.append(_f(source, "Bio / description",
                           desc_el.get_text(" ", strip=True)))
    sub_el = soup.select_one(".dialog-subtitle") or soup.select_one(".user-last-message")
    if sub_el is not None:
        raw = sub_el.get_text(" ", strip=True).replace("مشترک", "").strip()
        findings.append(_f(source, "Subscribers", raw))
    img = soup.select_one(".dialog-avatar img")
    if img is not None and img.get("src"):
        findings.append(_photo(source, img["src"]))
    return [x for x in findings if x]


class RubikaProvider(Provider):
    name = "rubika"
    handles = ("username",)

    async def search(self, id_type: str, value: str) -> list:
        username = value.lstrip("@")
        html = await fetch_text(f"https://rubika.ir/{username}")
        if not html:
            return []
        return parse_rubika_page(html, username)


def _bale_name_from_og_title(og_title: str) -> str:
    """og:title looks like "Bale | Channel <name>" (in Persian) — strip
    the site prefix (and the "Channel" word) to get the channel's own name."""
    name = (og_title or "").strip()
    if name.startswith("بله |"):
        name = name[len("بله |"):].strip()
    if name.startswith("کانال "):
        name = name[len("کانال "):].strip()
    return name


def parse_bale_page(html: str, username: str) -> list:
    """ble.ir/<id> channel page. Nonexistent ids return HTTP 404 (the
    caller never sees them); a 200 page must still prove the channel:
    the Profile block or an og:url naming this id."""
    soup = BeautifulSoup(html, "html.parser")

    def meta(prop):
        tag = soup.find("meta", attrs={"property": prop})
        return tag.get("content", "").strip() if tag and tag.get("content") else ""

    name_el = soup.select_one('[class*="Profile_name"]')
    og_url = meta("og:url")
    if name_el is None and f"/{username.lower()}" not in og_url.lower():
        return []
    source = "bale"
    findings = []
    name = name_el.get_text(" ", strip=True) if name_el is not None else ""
    if not name:
        name = _bale_name_from_og_title(meta("og:title"))
    findings.append(_f(source, "Display name", name))
    desc_el = soup.select_one('[class*="Profile_description"]')
    desc = desc_el.get_text(" ", strip=True) if desc_el is not None else ""
    if not desc:
        desc = meta("og:description")
    findings.append(_f(source, "Bio / description", desc))
    members = None
    m = re.search(r'"members\\?"?\s*:\s*(\d+)', html)
    if m:
        members = m.group(1)
    else:
        mc_el = soup.select_one('[class*="Profile_memberCount"]')
        if mc_el is not None:
            members = mc_el.get_text(" ", strip=True)
    findings.append(_f(source, "Members", members))
    avatar = meta("og:image")
    if not avatar:
        img = soup.select_one('[class*="Avatar_img"]')
        if img is not None:
            avatar = img.get("src", "")
    findings.append(_photo(source, avatar))
    return [x for x in findings if x]


class BaleProvider(Provider):
    name = "bale"
    handles = ("username",)

    async def search(self, id_type: str, value: str) -> list:
        username = value.lstrip("@")
        html = await fetch_text(f"https://ble.ir/{username}")
        if not html:
            return []
        return parse_bale_page(html, username)


SOROUSH_NOT_FOUND = "اطلاعات مرتبط با لینک یافت نشد"


def parse_soroush_page(html: str, username: str) -> list:
    """sapp.ir/<id>. Reality check (verified 2026-10-22): Soroush serves
    its legacy "info not found" page for ids that do not exist, and the
    Vitrin SPA shell for ids that DO exist — the shell carries no
    per-channel og data at all (it loads client-side). So: not-found
    marker -> zero findings; real og data -> extract it; otherwise the
    Vitrin shell itself is the existence proof and yields exactly one
    presence finding, never invented profile fields."""
    if SOROUSH_NOT_FOUND in html:
        return []
    og = validate_profile_page(
        html, username,
        not_found_markers=("page not found",),
        default_titles=("سروش پلاس", "ویترین سروش پلاس", "Soroush Plus"))
    if og:
        source = "soroush"
        findings = [
            _f(source, "Display name", og["title"]),
            _f(source, "Bio / description",
               og["description"] if og["description"] != og["title"] else None),
            _photo(source, og["image"]),
        ]
        return [x for x in findings if x]
    if "vitrin" in html.lower():
        return [dict(source="soroush", category="presence",
                     title="Soroush account", value="yes",
                     snippet=f"https://sapp.ir/{username}")]
    return []


class SoroushProvider(Provider):
    name = "soroush"
    handles = ("username",)

    async def search(self, id_type: str, value: str) -> list:
        username = value.lstrip("@")
        html = await fetch_text(f"https://sapp.ir/{username}")
        if not html:
            return []
        return parse_soroush_page(html, username)


def _json_str_field(seg: str, key: str):
    m = re.search(r'"' + re.escape(key) + r'":("(?:[^"\\]|\\.)*")', seg)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


def _json_int_field(seg: str, key: str):
    m = re.search(r'"' + re.escape(key) + r'":(\d+)', seg)
    return int(m.group(1)) if m else None


def parse_virasty_page(html: str, username: str) -> list:
    """virasty.com/<id> (Next.js). Profile data lives in the embedded
    hydration JSON (usersSummary), double-escaped in the raw HTML;
    nonexistent ids return HTTP 404 so they never reach this parser.
    The summary object must name exactly this username."""
    if not html:
        return []
    d = html.replace('\\\\"', '"').replace('\\"', '"')
    m = re.search(r'"username":"' + re.escape(username) + r'"', d, re.IGNORECASE)
    if not m:
        return []
    seg = d[max(0, m.start() - 1600): m.start() + 1600]
    if '"usersSummary"' not in d[max(0, m.start() - 4000): m.start() + 100] \
            and '"displayName"' not in seg:
        return []
    source = "virasty"
    findings = []
    findings.append(_f(source, "Display name",
                       _json_str_field(seg, "displayName")))
    findings.append(_f(source, "Followers", _json_int_field(seg, "followersCount")))
    findings.append(_f(source, "Following", _json_int_field(seg, "followingsCount")))
    bio = None
    bm = re.search(r'"bio":\{"text":("(?:[^"\\]|\\.)*")', seg)
    if bm:
        try:
            bio = json.loads(bm.group(1))
        except Exception:
            bio = None
    findings.append(_f(source, "Bio", bio))
    avatar = _json_str_field(seg, "avatar")
    if avatar and re.fullmatch(r"[0-9a-f]{32}", avatar):
        findings.append(_photo(source,
                               f"https://cdn.virasty.com/guest/{avatar}"))
    return [x for x in findings if x]


class VirastyProvider(Provider):
    name = "virasty"
    handles = ("username",)

    async def search(self, id_type: str, value: str) -> list:
        username = value.lstrip("@")
        html = await fetch_text(f"https://virasty.com/{username}")
        if not html:
            return []
        return parse_virasty_page(html, username)


# ------------------------------------------- username profile enrichment
# The bot itself opens each platform and extracts the *actual public
# profile data* (display name, bio, follower counts, join date, ...) —
# no bare account links are stored. API platforms are read through
# their public JSON APIs (which 404 unknown users); page platforms go
# through validate_profile_page, so a nonexistent username yields ZERO
# findings on every platform.

# -- structured API parsers (pure functions, unit-tested) ------------------
def parse_reddit_about(d):
    data = (d or {}).get("data") if isinstance(d, dict) else None
    if not data or not data.get("name"):
        return []
    out = [_f("reddit", "Display name", data.get("name")),
           _f("reddit", "Total karma", data.get("total_karma")),
           _f("reddit", "Post karma", data.get("link_karma")),
           _f("reddit", "Comment karma", data.get("comment_karma")),
           _f("reddit", "Account created", _date(data.get("created_utc", 0)))]
    return [x for x in out if x]


def parse_x_syndication(d):
    if not d or not isinstance(d, list) or not d:
        return []
    u = d[0]
    return [x for x in [
        _f("x", "Display name", u.get("name")),
        _f("x", "Followers", u.get("followers_count")),
    ] if x]


# -- profile-page parsers (pure functions, fixture-tested) -----------------
def _clean_title(source, title):
    t = (title or "").strip()
    for suffix in OG_TITLE_CLEANUP.get(source, ()):
        if suffix and t.endswith(suffix) and source != "steam":
            t = t[: -len(suffix)].strip()
        elif suffix and t.startswith(suffix) and source == "steam":
            t = t[len(suffix):].strip()
    return t


_GENERIC_DESC = (
    "streams live on twitch", "log in", "sign up", "join",
    "create an account",
)

# og:description values that are the SITE's own marketing text, never a
# person's bio (prefix match, case-insensitive). Twitch serves this for
# every channel URL — including nonexistent ones (verified live).
OG_DEFAULT_DESCRIPTIONS = {
    "twitch": ("twitch is the world's leading video platform",),
}


def parse_og_profile(html, source, username):
    """Generic og-based profile parser with STRICT existence
    validation: the site's own default title/description is never
    reported as a person's data (the v3.1 Twitch bug)."""
    og = validate_profile_page(
        html, username,
        not_found_markers=OG_NOT_FOUND.get(source, ()),
        default_titles=OG_DEFAULT_TITLES.get(source, ()))
    if og is None:
        return []
    defaults = {t.lower() for t in OG_DEFAULT_TITLES.get(source, ())}
    title = og["title"]
    if title.strip().lower() in defaults:
        # Shell page: the title is the SITE's name, so nothing on this
        # page is the person's data — its og:description is the site's
        # generic marketing text (e.g. Twitch answers a nonexistent
        # channel URL with HTTP 200, og:title "Twitch", an og:url
        # naming the user, and the generic description; v4 emitted
        # that description as a "Bio" — the v3.1 bug class).
        return []
    out = [_f(source, "Display name", _clean_title(source, title))]
    desc = og["description"]
    default_descs = OG_DEFAULT_DESCRIPTIONS.get(source, ())
    if (desc and desc != title and len(desc) > 10
            and not any(g in desc.lower() for g in _GENERIC_DESC)
            and not any(desc.lower().startswith(d) for d in default_descs)):
        out.append(_f(source, "Bio / About", desc[:300]))
    return [x for x in out if x]


def parse_instagram_page(html, username):
    """Instagram profile page as served to the link-preview crawler UA
    (see CRAWLER_HEADERS; the caller must fetch with it — a browser UA
    gets a data-less shell with no og tags at all).

    v4.2 fix: the old parser rejected any page containing the string
    "/accounts/login" — but that string also appears in the scripts of
    every REAL profile page, so it rejected every real profile. No
    blanket rejection anymore; existence is proven strictly by the
    page's own og data naming THIS exact username:
    - og:title containing "(@<username>)" (after entity-unescaping —
      Instagram serves the @ as &#064;), or
    - og:url ending in /<username>/.
    A nonexistent user answers HTTP 200 with NO og:title -> zero."""
    if not html:
        return []
    og = _og_tags(html)
    title = _unescape(og["title"] or "")
    desc = _unescape(og["description"] or "")
    u = username.lower()
    proven = (f"(@{u})" in title.lower()
              or og["url"].strip().lower().rstrip("/").endswith("/" + u))
    if not title or not proven:
        return []
    out = []
    m = re.match(r"^(.*?)\s*\(@", title)
    if m and m.group(1).strip():
        out.append(_f("instagram", "Display name", m.group(1)))
    counts = re.search(
        r"([\d.,KMkm]+)\s*Followers?,\s*([\d.,KMkm]+)\s*Following,\s*([\d.,KMkm]+)\s*Posts?",
        desc)
    if counts:
        out += [_f("instagram", "Followers", counts.group(1)),
                _f("instagram", "Following", counts.group(2)),
                _f("instagram", "Posts", counts.group(3))]
        if " - " in desc:
            bio = desc.split(" - ", 1)[1].strip()
            # The stock suffix "See Instagram photos and videos from
            # Name (@user)" is Instagram's template, not the person's
            # bio — never report it as one.
            if bio and not bio.lower().startswith(
                    "see instagram photos and videos"):
                out.append(_f("instagram", "Bio", bio))
    out.append(_photo("instagram", og["image"]))
    return [x for x in out if x]


# Public web app id Instagram's own web client sends; the
# web_profile_info endpoint answers unauthenticated requests that
# carry it (rate-limited per IP — residential IPs fare far better
# than datacenter ones).
IG_APP_ID = "936619743392459"


def _fmt_count(n):
    """Exact count for the dossier: compact (104M) at a million and
    above, thousands-separated below that — the same shapes the og
    route produces, so both Instagram routes read alike."""
    if n is None:
        return None
    try:
        n = int(n)
    except (TypeError, ValueError):
        return str(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"
    return f"{n:,}"


def parse_instagram_api(data, username):
    """Instagram route A (v4.3): the web_profile_info JSON — the only
    public route that carries the person's BIOGRAPHY (the crawler og
    page provably contains no bio at all). Strict proof, same rule as
    every parser here: data.user must exist and name EXACTLY this
    username (case-insensitive); anything else -> zero findings."""
    if not isinstance(data, dict):
        return []
    payload = data.get("data")
    user = payload.get("user") if isinstance(payload, dict) else None
    if not isinstance(user, dict):
        return []
    if (user.get("username") or "").lower() != username.lower():
        return []

    def count(key):
        edge = user.get(key)
        return edge.get("count") if isinstance(edge, dict) else None

    out = [
        _f("instagram", "Display name", user.get("full_name")),
        _f("instagram", "Bio", user.get("biography")),
        _f("instagram", "Followers", _fmt_count(count("edge_followed_by"))),
        _f("instagram", "Following", _fmt_count(count("edge_follow"))),
        _f("instagram", "Posts",
           _fmt_count(count("edge_owner_to_timeline_media"))),
    ]
    if user.get("is_verified"):
        out.append(_f("instagram", "Verified", "yes"))
    # The person's OWN website field from their bio is data about
    # them (like a bio line), not a profile/photo link — kept.
    if user.get("external_url"):
        out.append(_f("instagram", "Website", user.get("external_url")))
    out.append(_photo("instagram",
                      user.get("profile_pic_url_hd")
                      or user.get("profile_pic_url")))
    return [x for x in out if x]


def parse_youtube_page(html, username):
    # Nonexistent handles return HTTP 404 (fetch layer). A 200 page must
    # still prove it is a channel page: an embedded channelId, or a
    # canonical/og URL of channel form (youtube.com/channel|@|c|user/…).
    og = _og_tags(html)
    title = og["title"]
    if not title:
        return []
    urls = (og["url"] + " " + og["canonical"]).lower()
    if '"channelId"' not in html and not re.search(
            r"youtube\.com/(channel/|@|c/|user/)", urls):
        return []
    out = []
    out.append(_f("youtube", "Channel name",
                  _clean_title("youtube", title)))
    if og["description"] and og["description"] != title:
        out.append(_f("youtube", "About", og["description"]))
    m = None
    for pat in (r'"label":"([\d.,KMB]+)\s+subscribers"',
                r'"simpleText":"([\d.,KMB]+)\s+subscribers"',
                r'"content":"([\d.,KMB]+)\s+subscribers"'):
        m = re.search(pat, html)
        if m:
            break
    if m:
        out.append(_f("youtube", "Subscribers", m.group(1)))
    return [x for x in out if x]


def parse_tiktok_page(html, username):
    # "stats" is a flat object; a non-greedy \{.*?\} would overrun into
    # the following "statsV2" object and break json.loads.
    m = re.search(
        r'"userInfo":\{"user":(\{.*?\}),"stats":(\{[^{}]*\})', html, re.DOTALL)
    if not m:
        return []
    try:
        user = json.loads(m.group(1))
        stats = json.loads(m.group(2))
    except Exception:
        return []
    uid = (user.get("uniqueId") or "").lower()
    if uid and uid != username.lower():
        return []
    if not uid and not user.get("nickname"):
        return []
    out = [_f("tiktok", "Display name", user.get("nickname")),
           _f("tiktok", "Bio", user.get("signature")),
           _f("tiktok", "Followers", stats.get("followerCount")),
           _f("tiktok", "Following", stats.get("followingCount")),
           _f("tiktok", "Likes", stats.get("heartCount")),
           _f("tiktok", "Videos", stats.get("videoCount"))]
    return [x for x in out if x]


# platform -> public profile page URL (for the validated og parser).
# v4.1 scope (owner's order): SOCIAL MEDIA ONLY — no dev/gaming/blog/
# link-aggregator sites (GitHub, Lichess, Medium, Steam, SoundCloud,
# Linktree, ... were all removed).
OG_PROFILE_URLS = {
    "twitch": "https://www.twitch.tv/{u}",
    "pinterest": "https://www.pinterest.com/{u}",
    "threads": "https://www.threads.net/@{u}",
    "snapchat": "https://www.snapchat.com/add/{u}",
    "facebook": "https://www.facebook.com/{u}",
    "aparat": "https://www.aparat.com/{u}",
}


class UsernameProfileProvider(Provider):
    """For a username, the bot itself visits each platform and extracts
    the public profile *data* (name, bio, followers, dates...). Nothing
    is stored as a bare link, and nothing is stored at all unless the
    platform proves the profile exists."""

    name = "profiles"
    handles = ("username",)

    async def _api(self, url, parser, headers=None):
        data = await fetch_json(url, headers=headers)
        return parser(data) if data is not None else []

    async def _page(self, url, parser, *args, headers=None):
        html = await fetch_text(url, headers=headers)
        if not html:
            return []
        try:
            return parser(html, *args)
        except Exception:
            return []

    async def _instagram(self, u: str) -> list:
        """Dual route (v4.3). Route A: web_profile_info JSON — full
        data including the biography, which the og page never carries.
        It is rate-limited per IP (datacenter IPs often get 429), so
        on ANY failure or non-matching payload we fall back to route
        B: the crawler-UA og page (name + counts + avatar, no bio)."""
        data = await fetch_json(
            "https://www.instagram.com/api/v1/users/web_profile_info/"
            f"?username={u}",
            headers={"x-ig-app-id": IG_APP_ID})
        if data is not None:
            try:
                out = parse_instagram_api(data, u)
            except Exception:
                out = []
            if out:
                return out
        return await self._page(f"https://www.instagram.com/{u}/",
                                parse_instagram_page, u,
                                headers=CRAWLER_HEADERS)

    async def search(self, id_type: str, value: str) -> list:
        u = value.lstrip("@")
        if len(u) < 2:
            return []
        # Social platforms only (v4.1): Reddit + X via their public
        # JSON endpoints; Instagram / YouTube / TikTok via dedicated
        # page parsers; Twitch / Pinterest / Threads / Snapchat /
        # Facebook / Aparat via the strictly validated og parser.
        # Instagram and every og-based fetch go out with the link-
        # preview crawler UA (CRAWLER_HEADERS): Meta platforms serve
        # those pages' public og data only to that UA (v4.2 fix).
        jobs = [
            self._api(f"https://www.reddit.com/user/{u}/about.json", parse_reddit_about),
            self._api("https://cdn.syndication.twimg.com/widgets/followbutton/"
                      f"info.json?screen_names={u}", parse_x_syndication),
            self._instagram(u),
            self._page(f"https://www.youtube.com/@{u}", parse_youtube_page, u),
            self._page(f"https://www.tiktok.com/@{u}", parse_tiktok_page, u),
        ]
        for source, tpl in OG_PROFILE_URLS.items():
            jobs.append(self._page(
                tpl.format(u=u),
                lambda html, s=source: parse_og_profile(html, s, u),
                headers=CRAWLER_HEADERS,
            ))
        results = await asyncio.gather(*jobs, return_exceptions=True)
        findings = []
        for r in results:
            if isinstance(r, list):
                findings.extend(r)
        return findings


def build_providers(api=None):
    # `api` (the Bot API client) is accepted only for call-site
    # compatibility — NO search provider may use it (2026-11-11,
    # owner's order: the bot token is display-only; every Telegram
    # search runs on the MTProto session layer). TelegramBotApiProvider
    # is therefore NOT registered anymore; numeric telegram_id lookups
    # are served by the userbot provider below.
    providers = [
        TelegramWebProvider(),
        WhatsAppProvider(),
        EitaaProvider(),
        RubikaProvider(),
        BaleProvider(),
        SoroushProvider(),
        VirastyProvider(),
        UsernameProfileProvider(),
    ]
    # Userbot query layer (userbot/): registered ONLY when explicitly
    # enabled in config AND telethon is importable, so a bot-only
    # install can never break on the missing dependency. While dormant
    # it changes nothing.
    if getattr(config, "USERBOT_ENABLED", False):
        try:
            from userbot.queries import UserbotProvider
            providers.append(UserbotProvider())
        except Exception:
            pass
    return providers


def clean_handle(value: str) -> str:
    return re.sub(r"^@", "", value.strip())
