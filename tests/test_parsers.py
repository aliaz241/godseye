# -*- coding: utf-8 -*-
"""Fixture tests for God's Eye v4 parsers.

All fixtures under tests/fixtures/ are REAL pages fetched with curl on
2026-10-22 (existing public channel/profile vs gibberish nonexistent
id). The v4 regression rule: a nonexistent username must yield ZERO
findings on every platform, and generic site metadata (default og
titles, share images) must never be reported as a person's data.

Run:  ~/workspace/.venv_ge/bin/python tests/test_parsers.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import providers as P  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
FAILURES = []


def load(name):
    with open(os.path.join(FIX, name), encoding="utf-8", errors="ignore") as fh:
        return fh.read()


def check(label, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + label + (f"  [{extra}]" if extra and not cond else ""))
    if not cond:
        FAILURES.append(label)


def titles(findings):
    return {f["title"]: f["value"] for f in findings}


GIB = "zzqqxnonexist99213"

# ------------------------------------------------------------- validator
check("validator: default title, no user URL -> None",
      P.validate_profile_page(
          '<html><head><meta property="og:title" content="Twitch">'
          '<meta property="og:description" content="Twitch is the world\'s '
          'leading video platform and community for gamers."></head></html>',
          "someuser", default_titles=("Twitch",)) is None)
check("validator: not-found marker -> None",
      P.validate_profile_page(
          '<html><head><meta property="og:title" content="Some User">'
          '</head><body>The specified profile could not be found</body></html>',
          "someuser",
          not_found_markers=("the specified profile could not be found",)) is None)
_ok = P.validate_profile_page(
    '<html><head><meta property="og:title" content="Jane Dev">'
    '<meta property="og:url" content="https://example.com/janedev"></head></html>',
    "janedev", default_titles=("Example",))
check("validator: real profile page -> og dict", _ok is not None and _ok["title"] == "Jane Dev")

# ------------------------------------------------------------- twitch (the v3.1 bug)
f = P.parse_og_profile(load("twitch_ok.html"), "twitch", "shroud")
t = titles(f)
check("twitch existing: display name extracted", t.get("Display name") == "shroud", str(t))
check("twitch existing: generic site bio NOT reported",
      "world's leading" not in str(t.get("Bio / About", "")))
check("twitch nonexistent: zero findings",
      P.parse_og_profile(load("twitch_no.html"), "twitch", GIB) == [])
# Live variant (verified 2026-10-22): Twitch answers a nonexistent
# channel with HTTP 200, og:title "Twitch" (default), an og:url naming
# the user, and the site's generic marketing description. The default
# title makes it a shell page: the generic description must NOT leak
# as a "Bio / About" (this exact page made the v4 live sweep emit 1
# false finding while other fetches of the same URL emitted none).
_tw_shell = (
    '<html><head>'
    '<meta property="og:title" content="Twitch">'
    '<meta property="og:url" content="https://www.twitch.tv/' + GIB + '">'
    '<meta property="og:description" content="Twitch is the world\'s '
    'leading video platform and community for gamers.">'
    '<link rel="canonical" href="https://www.twitch.tv/' + GIB + '">'
    '</head><body></body></html>')
check("twitch shell page (default title + user URL + generic desc): zero",
      P.parse_og_profile(_tw_shell, "twitch", GIB) == [])

# ------------------------------------------------------------- steam / soundcloud
f = P.parse_og_profile(load("steam_ok.html"), "steam", "gabelogannewell")
check("steam existing: name cleaned", titles(f).get("Display name") == "Rabscuttle", str(titles(f)))
check("steam nonexistent: zero findings",
      P.parse_og_profile(load("steam_no.html"), "steam", GIB) == [])
f = P.parse_og_profile(load("soundcloud_ok.html"), "soundcloud", "octobersveryown")
check("soundcloud existing: findings present", len(f) >= 1, str(f))
check("soundcloud nonexistent page: zero findings",
      P.parse_og_profile(load("soundcloud_no.html"), "soundcloud", GIB) == [])

# ------------------------------------------------------------- og platforms, assorted
f = P.parse_og_profile(load("linktree_ok.html"), "linktree", "linktree")
check("linktree existing: findings present", len(f) >= 1, str(f))
f = P.parse_og_profile(load("aboutme_ok.html"), "aboutme", "tonys")
check("aboutme existing: name cleaned of site suffix",
      titles(f).get("Display name") == "tony guo", str(titles(f)))
check("dribbble existing but default-title only: zero findings",
      P.parse_og_profile(load("dribbble_ok.html"), "dribbble", "dribbble") == [])

# ------------------------------------------------------------- instagram / youtube / tiktok
check("instagram browser-UA shell (existing user): zero findings",
      P.parse_instagram_page(load("instagram_ok.html"), "instagram") == [])
check("instagram browser-UA shell (nonexistent): zero findings",
      P.parse_instagram_page(load("instagram_no.html"), GIB) == [])
# v4.2: FULL UNTRIMMED pages fetched live with the crawler UA
# (facebookexternalhit/1.1) — the browser-UA fixtures above are
# data-less shells, which is exactly why the v4 tests missed the bug:
# the real page DOES carry og data, and DOES contain "/accounts/login"
# (in its scripts), which the old parser used as a blanket rejection.
_live_ok = load("instagram_live_ok.html")
check("instagram live page: contains the string that broke v4",
      "/accounts/login" in _live_ok)
f = P.parse_instagram_page(_live_ok, "nasa")
t = titles(f)
check("instagram live nasa: display name", t.get("Display name") == "NASA", str(t))
check("instagram live nasa: followers", t.get("Followers") == "104M", str(t))
check("instagram live nasa: following", t.get("Following") == "94", str(t))
check("instagram live nasa: posts", t.get("Posts") == "4,970", str(t))
check("instagram live nasa: profile photo is the real avatar",
      "cdninstagram.com" in str(t.get("Profile photo", "")), str(t))
check("instagram live nasa: stock template text NOT reported as bio",
      "See Instagram photos" not in str(t.get("Bio", "")), str(t))
check("instagram live gibberish (200, no og:title): zero findings",
      P.parse_instagram_page(load("instagram_live_no.html"), GIB) == [])
f = P.parse_youtube_page(load("youtube_ok.html"), "YouTube")
t = titles(f)
check("youtube existing: channel name", t.get("Channel name") == "YouTube", str(t))
check("youtube existing: subscribers extracted", "Subscribers" in t, str(t))
check("youtube nonexistent (404 body): zero findings",
      P.parse_youtube_page(load("youtube_no.html"), GIB) == [])
f = P.parse_tiktok_page(load("tiktok_ok.html"), "tiktok")
t = titles(f)
check("tiktok existing: followers extracted", "Followers" in t, str(t))
check("tiktok nonexistent: zero findings",
      P.parse_tiktok_page(load("tiktok_no.html"), GIB) == [])

# ------------------------------------------------------------- telegram
f = P.parse_tme_page(load("telegram_ok.html"), "your_username")
t = titles(f)
check("telegram existing: display name", t.get("Display name") == "αℓι", str(t))
check("telegram nonexistent (Contact page): zero findings",
      P.parse_tme_page(load("telegram_no.html"), GIB) == [])

# ------------------------------------------------------------- whatsapp (the v3.1 bug)
for fx, label in (("wa_real.html", "real number"),
                  ("wa_landline.html", "landline"),
                  ("wa_short.html", "short invalid")):
    info = P.parse_wa_page(load(fx), "YOUR_PHONE_NUMBER")
    check(f"whatsapp {label}: no conclusive signal -> exists None",
          info["exists"] is None, str(info))
    check(f"whatsapp {label}: no photo/name findings possible",
          info["photo"] is None)
info = P.parse_wa_page(
    "<html><body>The phone number shared via url is invalid.</body></html>",
    "123")
check("whatsapp explicit invalid marker -> exists False", info["exists"] is False)
info = P.parse_wa_page(
    '<html><head><meta property="og:image" '
    'content="https://pps.whatsapp.net/v/t61.24694-24/photo.jpg"></head></html>',
    "989210000000")
check("whatsapp real pps photo -> exists True + photo kept",
      info["exists"] is True and "pps.whatsapp.net" in (info["photo"] or ""))
info = P.parse_wa_page(
    '<html><head><meta property="og:title" content="Share on WhatsApp">'
    '<meta property="og:image" content="https://static.whatsapp.net/'
    'rsrc.php/v4/yO/r/rukeqTVNJDY.png"></head></html>', "989210000000")
check("whatsapp generic share page -> exists None (no false positive)",
      info["exists"] is None and info["photo"] is None)

# ------------------------------------------------------------- eitaa
f = P.parse_eitaa_page(load("eitaa_ok.html"), "tasnimnews")
t = titles(f)
check("eitaa existing: channel name", t.get("Display name") == "خبرگزاری تسنیم", str(t))
check("eitaa existing: subscribers (data-count)", t.get("Subscribers") == "239625", str(t))
check("eitaa existing: bio extracted", "روبیکا" in str(t.get("Bio / description", "")), str(t))
check("eitaa existing: avatar is eitaa URL",
      str(t.get("Profile photo", "")).startswith("https://eitaa.com/"), str(t))
posts = [x for x in f if x["category"] == "post"]
check("eitaa existing: 1..5 recent posts", 1 <= len(posts) <= 5, f"{len(posts)} posts")
check("eitaa existing: post text truncated <=200",
      all(len(p["value"]) <= 200 for p in posts))
check("eitaa nonexistent (Contact page): zero findings",
      P.parse_eitaa_page(load("eitaa_no.html"), GIB) == [])

# ------------------------------------------------------------- rubika
f = P.parse_rubika_page(load("rubika_ok.html"), "TasnimNews")
t = titles(f)
check("rubika existing: channel name", t.get("Display name") == "خبرگزاری تسنیم", str(t))
check("rubika existing: subscribers", t.get("Subscribers") == "1,912,780", str(t))
check("rubika existing: bio extracted", "Plan_agency" in str(t.get("Bio / description", "")), str(t))
check("rubika existing: avatar URL present",
      str(t.get("Profile photo", "")).startswith("http"), str(t))
check("rubika nonexistent (generic landing): zero findings",
      P.parse_rubika_page(load("rubika_no.html"), GIB) == [])

# ------------------------------------------------------------- bale
f = P.parse_bale_page(load("bale_ok.html"), "TasnimNews")
t = titles(f)
check("bale existing: channel name", t.get("Display name") == "خبرگزاری تسنیم", str(t))
check("bale existing: members from JSON", t.get("Members") == "534872", str(t))
check("bale existing: bio extracted", "TasnimNews" in str(t.get("Bio / description", "")), str(t))
check("bale existing: avatar is ble.ir file URL",
      "ble.ir" in str(t.get("Profile photo", "")), str(t))
check("bale nonexistent (404 body): zero findings",
      P.parse_bale_page(load("bale_no.html"), GIB) == [])

# ------------------------------------------------------------- soroush
f = P.parse_soroush_page(load("soroush_ok.html"), "TasnimNews")
check("soroush existing (Vitrin shell): exactly one presence finding",
      len(f) == 1 and f[0]["category"] == "presence" and f[0]["value"] == "yes", str(f))
check("soroush nonexistent (legacy not-found page): zero findings",
      P.parse_soroush_page(load("soroush_no.html"), GIB) == [])

# ------------------------------------------------------------- virasty
f = P.parse_virasty_page(load("virasty_ok.html"), "khamenei_ir")
t = titles(f)
check("virasty existing: display name", "KHAMENEI" in str(t.get("Display name", "")), str(t))
check("virasty existing: followers", t.get("Followers") == "182291", str(t))
check("virasty existing: following", t.get("Following") == "1", str(t))
check("virasty existing: bio extracted", "خامنه" in str(t.get("Bio", "")), str(t))
check("virasty existing: avatar built from hash",
      t.get("Profile photo") == "https://cdn.virasty.com/guest/f38637b30cad4e45a87176774718b06c",
      str(t))
check("virasty nonexistent (404 body): zero findings",
      P.parse_virasty_page(load("virasty_no.html"), GIB) == [])

# ------------------------------------------------- v4.1: no web search
# General web search (Bing/DDG chains + site: queries) was removed in
# v4.1 at the owner's request; no web/platform-search provider or
# parser may exist anymore.
check("v4.1: WebSearchProvider removed", not hasattr(P, "WebSearchProvider"))
check("v4.1: PlatformSearchProvider removed",
      not hasattr(P, "PlatformSearchProvider"))
_registry_names = {p.name for p in P.build_providers(None)}
check("v4.1: registry = direct social providers (+ telegram_user layer)",
      _registry_names == {"telegram", "whatsapp", "eitaa", "rubika",
                          "bale", "soroush", "virasty", "profiles",
                          "telegram_user"},
      str(_registry_names))
# Social-media-only scope: the profile sweep may query ONLY the kept
# social platforms; every non-social source is gone from the code.
check("v4.1: og sweep covers only kept social platforms",
      set(P.OG_PROFILE_URLS) == {"twitch", "pinterest", "threads",
                                 "snapchat", "facebook", "aparat"},
      str(set(P.OG_PROFILE_URLS)))
for _gone in ("GravatarProvider", "parse_gravatar", "parse_github_user",
              "parse_gitlab_users", "parse_lichess", "parse_chesscom",
              "parse_keybase", "parse_devto"):
    check(f"v4.1: {_gone} removed", not hasattr(P, _gone))

# ------------------------------------------------- v4.2: crawler UA wiring
# The sweep must fetch Instagram — and the other og-based social pages
# (Facebook/Threads/Twitch/…) — with the link-preview crawler UA; a
# browser UA is answered with a data-less shell. Probe the provider
# with stubbed fetchers and record the UA each URL went out with.
import asyncio as _aio  # noqa: E402


async def _ua_probe():
    seen = {}

    async def fake_fetch_text(url, timeout_s=None, headers=None):
        seen[url] = (headers or {}).get("User-Agent", "")
        return "<html></html>"

    async def fake_fetch_json(url, headers=None):
        return None

    orig_t, orig_j = P.fetch_text, P.fetch_json
    P.fetch_text, P.fetch_json = fake_fetch_text, fake_fetch_json
    try:
        await P.UsernameProfileProvider().search("username", "someuser")
    finally:
        P.fetch_text, P.fetch_json = orig_t, orig_j
    return seen


_seen = _aio.run(_ua_probe())
check("v4.2: instagram fetched with crawler UA",
      any("instagram.com" in url and "facebookexternalhit" in ua
          for url, ua in _seen.items()), str(_seen))
check("v4.2: og platforms fetched with crawler UA (facebook)",
      any("facebook.com" in url and "facebookexternalhit" in ua
          for url, ua in _seen.items()), str(_seen))
check("v4.2: og platforms fetched with crawler UA (twitch)",
      any("twitch.tv" in url and "facebookexternalhit" in ua
          for url, ua in _seen.items()), str(_seen))

# ------------------------------------------------- v4.3: instagram route A
# Route A (web_profile_info JSON) is the only public route carrying
# the biography. Parser tested against a synthetic payload shaped
# exactly like the real response; route B fixtures above keep passing.
_IG_API = {
    "data": {"user": {
        "username": "nasa",
        "full_name": "NASA",
        "biography": "Exploring the universe and our home planet.",
        "edge_followed_by": {"count": 104532118},
        "edge_follow": {"count": 94},
        "edge_owner_to_timeline_media": {"count": 4970},
        "is_verified": True,
        "external_url": "https://www.nasa.gov/",
        "profile_pic_url_hd": "https://scontent.cdninstagram.com/hd_nasa.jpg",
        "profile_pic_url": "https://scontent.cdninstagram.com/nasa.jpg",
    }},
    "status": "ok",
}
f = P.parse_instagram_api(_IG_API, "nasa")
t = titles(f)
check("ig api: display name", t.get("Display name") == "NASA", str(t))
check("ig api: bio extracted (route A's whole point)",
      t.get("Bio") == "Exploring the universe and our home planet.", str(t))
check("ig api: followers humanized at >=1e6", t.get("Followers") == "104.5M", str(t))
check("ig api: following exact", t.get("Following") == "94", str(t))
check("ig api: posts thousands-separated", t.get("Posts") == "4,970", str(t))
check("ig api: verified flag", t.get("Verified") == "yes", str(t))
check("ig api: own website field kept as data",
      t.get("Website") == "https://www.nasa.gov/", str(t))
check("ig api: hd avatar preferred",
      t.get("Profile photo") == "https://scontent.cdninstagram.com/hd_nasa.jpg",
      str(t))
check("ig api: username match is case-insensitive",
      len(P.parse_instagram_api(_IG_API, "NASA")) == len(f))
check("ig api: username mismatch -> rejected",
      P.parse_instagram_api(_IG_API, "someoneelse") == [])
check("ig api: missing user -> zero findings",
      P.parse_instagram_api({"data": {}}, "nasa") == []
      and P.parse_instagram_api(None, "nasa") == []
      and P.parse_instagram_api({"status": "fail"}, "nasa") == [])

# ------------------------------------------------- v4.3: photos are data, not links
# Every avatar a parser discovers is a finding with category "photo";
# the bot sends it as a real photo and the dossier formatter drops it.
def _photos(findings):
    return [x for x in findings if x["title"] == "Profile photo"]


for _label, _findings in (
        ("telegram", P.parse_tme_page(load("telegram_ok.html"), "your_username")),
        ("instagram route B", P.parse_instagram_page(_live_ok, "nasa")),
        ("instagram route A", f),
        ("eitaa", P.parse_eitaa_page(load("eitaa_ok.html"), "tasnimnews")),
        ("rubika", P.parse_rubika_page(load("rubika_ok.html"), "TasnimNews")),
        ("bale", P.parse_bale_page(load("bale_ok.html"), "TasnimNews")),
        ("virasty", P.parse_virasty_page(load("virasty_ok.html"), "khamenei_ir")),
):
    _ph = _photos(_findings)
    check(f"v4.3 photos: {_label} avatar is category 'photo'",
          len(_ph) == 1 and _ph[0]["category"] == "photo", str(_ph))

_tg = P.parse_tme_page(load("telegram_ok.html"), "your_username")
_tg_photo = _photos(_tg)
check("v4.3 photos: telegram avatar is the t.me og:image (telesco.pe)",
      bool(_tg_photo) and "telesco.pe" in _tg_photo[0]["value"], str(_tg_photo))


async def _wa_photo_probe():
    orig = P.fetch_text

    async def fake_fetch(url, timeout_s=None, headers=None):
        return ('<html><head><meta property="og:title" content="x">'
                '</head><body><a href="https://api.whatsapp.com/send">'
                'chat</a><img src="https://pps.whatsapp.net/v/t61/'
                'photo.jpg"></body></html>')

    P.fetch_text = fake_fetch
    try:
        return await P.WhatsAppProvider().search("phone", "+989120000000")
    finally:
        P.fetch_text = orig


_wa = _aio.run(_wa_photo_probe())
_wa_photo = _photos(_wa)
check("v4.3 photos: whatsapp real photo is category 'photo'",
      len(_wa_photo) == 1 and _wa_photo[0]["category"] == "photo", str(_wa))

print()
if FAILURES:
    print(f"{len(FAILURES)} FAILURE(S):")
    for x in FAILURES:
        print(" -", x)
    sys.exit(1)
print("ALL PARSER TESTS PASSED")
