# God's Eye — Bot-Only Edition (No API)

This edition works **with a bot token only**; it needs neither an
api_id/api_hash nor a user account.

## v4 — The Golden Rule: Real Data Only

After the false positives of v3.1 (for example, showing Twitch's default
site name instead of the person's name, or WhatsApp's generic share image
instead of a profile photo), in v4 each source only records a finding
when the fetched page **proves the profile exists** (strict validation:
no "not found" marker, no default site title, and a username match in the
URL or title). A nonexistent username yields exactly zero findings on
**every** platform.

- **Iranian platforms (deep):** Eitaa (name, subscribers, bio, avatar and
  the 5 most recent posts), Rubika (name, bio, subscribers, avatar),
  Bale (name, bio, member count, avatar), Soroush and Virasty (name, bio,
  followers, avatar) — each read from its own real public page.
- **WhatsApp:** Today's wa.me page is identical for numbers with and
  without an account and has no reliable public marker; so the bot only
  reports on an explicit "number is invalid" marker or a real photo on
  the pps.whatsapp.net domain, and stays silent in all other cases.

## v4.1 — No Web Search; Instant Reply and a Time Budget

- **Web search was removed entirely** (the Bing/DDG chains and the
  in-platform `site:` searches) and the scope is **social networks
  only**: each provider reads that platform's own public page or API
  directly — Telegram, Instagram, X (Twitter), TikTok, YouTube,
  Facebook, LinkedIn, Threads, Snapchat, Twitch, Reddit, Pinterest,
  Aparat, Rubika, Bale, Eitaa, Soroush, Virasty and WhatsApp. All
  non-social sources (GitHub, GitLab, Lichess, Chess.com, Keybase,
  Medium, Steam, SoundCloud, Gravatar, …) were removed; an email
  identifier no longer has any source and produces no result.
- **Instant reply:** as soon as an identifier arrives, a "dossier
  created" message appears, and that same message is edited live as each
  source finishes (e.g. "Telegram ✓"); there is no silent gap.
- **Time budget:** each HTTP request gets at most 8 seconds and a whole
  search for one identifier at most 60 seconds (`SEARCH_DEADLINE` in
  `config.py`); slow sources are abandoned and the dossier is delivered
  with whatever findings exist.
- `/start` in any state clears the conversation state and shows the main
  menu.

Tests live in `tests/`: offline parser tests with fixtures of real pages,
offline bot-UX tests, and a live spot check (`tests/live_spotcheck.py`).

## v4.2 — Instagram, Dossier Merging and a Transparent Result Report

- **Instagram fixed:** the profile page is now fetched with the
  link-preview crawler user agent (`facebookexternalhit/1.1`); Instagram
  serves a blank page with no data to a browser user agent. The blanket
  rejection of pages containing the string `/accounts/login` was also
  removed (that string appears in the scripts of real pages too and was
  rejecting every real profile); a profile's existence is proven only by
  the page's own og data naming exactly that username. The same crawler
  user agent is also applied to the other og-based fetches (Facebook,
  Threads, Snapchat, Pinterest, Twitch, Aparat).
- **Adding an identifier really merges:** if the new identifier was
  previously recorded on another dossier, that dossier is merged in full
  into the current one (identifiers and findings are moved, the emptied
  dossier is deleted) and the bot explicitly says "the two dossiers were
  merged". Local 09… numbers are also stored in international +98 form
  so one number with two spellings doesn't create two dossiers.
- **Search result report:** after every search (including after adding
  an identifier) the bot says exactly which identifier was added and how
  many new findings came from which sources; and if nothing was found,
  it says so plainly.

## v4.3 — Photos Are Sent, Not Linked; Instagram Bio

- **No photo link in any message:** every avatar a source finds is
  stored in its own "photo" category, the dossier template never puts it
  in the text, and after showing the result (end of search and the "Show
  dossier" button) the bot sends the photos as **real Telegram photos**
  — at most 3 photos per dossier, captioned with the platform name (e.g.
  "Profile photo — Instagram"). Sending path: first it gives Telegram
  the URL itself to fetch; if that fails, it downloads the photo bytes
  and uploads them; if both fail, it stays silent — it never sends the
  URL as text in place of a photo.
- **Latest Telegram profile photo:** for username dossiers, the current
  avatar is taken from the og:image of the t.me page; for numeric-ID
  dossiers, the latest real profile photo is read from Telegram itself
  with `getUserProfilePhotos` and sent by file_id (if the bot cannot see
  that user, it is silently skipped).
- **Instagram became dual-path:** path A is the official
  `web_profile_info` JSON endpoint — the only public path that returns
  the person's **biography** (the crawler og page has no bio at all);
  along with the full name, exact counters and an HD avatar. This path
  is rate-limited per IP (from a datacenter IP it usually gets a 429,
  and then path B — the same v4.2 crawler og parse — quietly produces
  the result; from a residential phone IP, path A usually answers and
  the bio comes too).

## Running

```
pip install -r requirements.txt
```

In `config.py`, hardcode only `BOT_TOKEN` and `OWNER_ID`, then:

```
python bot.py
```

## How Does It Differ from the Telethon Edition?

Without a user account, Telegram doesn't let you look up any arbitrary
ID from scratch. This edition has three public routes:

1. **Username** → the public `t.me/<username>` page (name, bio/description, page info)
2. **Numeric ID** → the Bot API's own `getChat` (only when the bot can
   see that user: a shared group or prior contact)
3. **Forward** → forward any message from the person to the bot; their
   ID, name and username are read automatically from the forward and
   their dossier is created/updated. This is the most reliable way to
   start a dossier for unknown IDs.

## Phone Number Check

When you attach a phone number to a dossier and run a "full search", the
number is checked directly in WhatsApp itself:

- **whatsapp** — from the public wa.me page: reported only when a
  reliable public marker exists (an explicit invalid-number marker, or a
  real profile photo on the pps.whatsapp.net domain). In all other cases
  nothing is guessed. (WhatsApp's bio/About cannot be read from outside;
  it needs a WhatsApp session.)

An Iranian number in the format 09xxxxxxxxx is also automatically
converted to the international format 98xxxxxxxxxx.

The Iranian platforms are also read directly from their own public
pages: **Bale (ble.ir)**, **Eitaa (eitaa.com)**, **Rubika (rubika.ir)**,
**Soroush (sapp.ir)** and **Virasty (virasty.com)** — for a
channel username/ID: name, bio, member/subscriber count, avatar and, on
Eitaa, the 5 most recent posts.

## Where Do I Run It? (No Server)

The bot works with long polling; it needs neither a domain nor a public
IP. Anywhere with Python and internet is enough:

1. **Liara** — an Iranian platform, has a free plan, payments in rials.
   Deploy the project with this same Dockerfile. Make sure to attach a
   disk (persistent volume) to the /app path so godseye.db is not wiped
   on every deploy.
2. **Android phone with Termux** — `pkg install python`, then
   `pip install -r requirements.txt` and `python bot.py`. For
   always-on running, keep the phone plugged in and turn off battery
   optimization for Termux.
3. **Your own computer** — the simplest: as long as the machine is on,
   the bot is on.

GitHub Actions is not suitable for an always-on bot (it is good for
scheduled jobs like hourly bots, not for long polling).

The database, search engine and dossier dynamics (adding a new
identifier with `/add` and searching again with `/search`) are exactly
like the original edition.

## Setup (Public Release)

This release is published for personal use and contains **no token or
key inside it**; you must fill in the following yourself:

1. In `config.py`: replace the `BOT_TOKEN` value with your own bot token
   (from [@BotFather](https://t.me/BotFather)) and `OWNER_ID` with your
   own numeric Telegram ID.
2. (Optional, the userbot layer) In `userbot/userbot_config.py`: get
   your own `API_ID` and `API_HASH` values from https://my.telegram.org,
   put them in, and log in with `userbot/vm_login.py`; never share the
   created session file with anyone.
