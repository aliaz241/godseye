# -*- coding: utf-8 -*-
"""My Dashboard — a personal, self-only Telegram activity dashboard.

Standalone tool, a bigger sibling of `my_activity.py`. Pulls YOUR OWN
messages from every chat/group/channel you're in, then writes a single
self-contained HTML file (no server, no internet needed to view it —
everything, including the charting code, is inline) with:

  - a searchable table of your own messages
  - a day-by-day timeline chart of your own activity
  - a per-chat ("who/where I talk the most") bar chart
  - simple word-frequency + active-hours stats

It never takes a username, user id, or forwarded message as input and
never reads anyone else's messages — only yours (filtered by
`from_user=me.id` on every chat).

Run from the project root:

    python -m userbot.my_dashboard

Then open the file it prints at the end in any browser.
"""
import asyncio
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone

from . import userbot_config as uc

# ---------------------------------------------------------------- options
MESSAGES_PER_CHAT = 500          # how many of YOUR OWN messages to scan
                                  # per chat (raise/lower as you like)
OUTPUT_FILE = "userbot/my_dashboard.html"

_STOPWORDS = set("""
و در به از که این را با است هم یا برای تا آن یک می‌شود کردم کرد شد نه
بله اره خب چون اگه اگر چی چرا کجا کی چیه بودم بود میشه نیست هست یعنی
the a an is are was were to of in on for and or
""".split())


def _fmt_date_iso(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


async def _collect_own_messages(client, me_id, dialog, limit):
    out = []
    try:
        async for msg in client.iter_messages(dialog.entity, limit=limit,
                                               from_user=me_id):
            if not (msg.message or msg.media):
                continue
            text = (msg.message or "").strip()
            out.append({
                "date": _fmt_date_iso(msg.date),
                "text": text if text else "[media]",
                "has_media": bool(msg.media),
            })
    except Exception:
        pass
    return out


def _tokenize(text):
    return [w for w in re.findall(r"[\w\u0600-\u06FF]+", text.lower())
            if len(w) > 2 and w not in _STOPWORDS]


def collect_from_messages(messages, label, note=None):
    """Builds the SAME dashboard data dict from a flat list of message
    dicts {date, text, has_media, chat} — the shape the target crawl
    in userbot/membership.py produces. `label` is who the dashboard
    describes; `note`, when given, is rendered in the meta line (the
    crawl passes its visible-minimum honesty note)."""
    chats_map = {}
    word_counter = Counter()
    hour_counter = Counter()
    day_counter = Counter()
    all_messages = []
    for m in messages:
        mm = {"date": m.get("date"),
              "text": m.get("text") or "[media]",
              "has_media": bool(m.get("has_media")),
              "chat": m.get("chat") or "(no title)"}
        all_messages.append(mm)
        if not mm["has_media"]:
            word_counter.update(_tokenize(mm["text"]))
        if mm["date"]:
            dt = datetime.fromisoformat(mm["date"])
            hour_counter[dt.hour] += 1
            day_counter[dt.date().isoformat()] += 1
        c = chats_map.setdefault(mm["chat"], {
            "name": mm["chat"], "kind": "chat", "username": None,
            "count": 0, "dates": []})
        c["count"] += 1
        if mm["date"]:
            c["dates"].append(mm["date"])
    chats = []
    for c in chats_map.values():
        dates = sorted(c.pop("dates"))
        c["first"] = dates[0] if dates else None
        c["last"] = dates[-1] if dates else None
        chats.append(c)
    chats.sort(key=lambda c: c["count"], reverse=True)
    all_messages.sort(key=lambda m: m["date"] or "", reverse=True)
    return {
        "me": label,
        "session_account": note or "",
        "generated": datetime.now(timezone.utc).isoformat(),
        "chats": chats,
        "messages": all_messages,
        "timeline": sorted(day_counter.items()),
        "top_words": word_counter.most_common(40),
        "hours": [hour_counter.get(h, 0) for h in range(24)],
        "totals": {
            "chats_with_activity": len(chats),
            "messages": len(all_messages),
        },
    }


async def collect_data(client, me, messages_per_chat=MESSAGES_PER_CHAT,
                       progress=None):
    """Given an ALREADY-CONNECTED client and its own `me` user, builds
    the data dict (self-only: every message pull below is scoped with
    `from_user=me.id`). `progress`, if given, is called with a short
    status string per chat scanned — useful for a bot to show "still
    working" without printing to a terminal."""
    chats = []
    all_messages = []
    word_counter = Counter()
    hour_counter = Counter()
    day_counter = Counter()

    n = 0
    async for dialog in client.iter_dialogs():
        n += 1
        kind = ("channel" if dialog.is_channel else
                "group" if dialog.is_group else
                "private" if dialog.is_user else "chat")
        username = getattr(dialog.entity, "username", None)
        msgs = await _collect_own_messages(client, me.id, dialog, messages_per_chat)
        for m in msgs:
            m["chat"] = dialog.name or "(no title)"
            all_messages.append(m)
            if not m["has_media"]:
                word_counter.update(_tokenize(m["text"]))
            if m["date"]:
                dt = datetime.fromisoformat(m["date"])
                hour_counter[dt.hour] += 1
                day_counter[dt.date().isoformat()] += 1

        if msgs:
            dates = [datetime.fromisoformat(m["date"]) for m in msgs if m["date"]]
            chats.append({
                "name": dialog.name or "(no title)",
                "kind": kind,
                "username": username,
                "count": len(msgs),
                "first": min(dates).isoformat() if dates else None,
                "last": max(dates).isoformat() if dates else None,
            })
        if progress:
            progress(f"[{n}] {dialog.name!r}: {len(msgs)} of my messages")
        else:
            print(f"  [{n}] {dialog.name!r}: {len(msgs)} of my messages")

    chats.sort(key=lambda c: c["count"], reverse=True)
    all_messages.sort(key=lambda m: m["date"] or "", reverse=True)
    timeline = sorted(day_counter.items())
    top_words = word_counter.most_common(40)
    hours = [hour_counter.get(h, 0) for h in range(24)]

    # Owner-facing label (the owner's order, 2026-11-11): the dashboard is
    # requested BY the bot's owner, so it is labelled with the OWNER
    # (config.OWNER_ID — resolved to a name/username when the session
    # can see that user), never with the raw session account. The DATA
    # still comes from the session account's own messages — that part
    # cannot change without a session FOR the owner's account, and
    # the label says which account the numbers describe.
    owner_label = str(me.id)
    session_label = f"{me.first_name or ''} (@{me.username or me.id})"
    try:
        import config as _cfg
        _oid = getattr(_cfg, "OWNER_ID", 0)
        if _oid and _oid != me.id:
            _ou = await client.get_entity(int(_oid))
            if _ou is not None:
                owner_label = (f"{getattr(_ou, 'first_name', '') or ''} "
                               f"(@{getattr(_ou, 'username', None) or _oid})")
    except Exception:
        pass

    return {
        "me": owner_label.strip(),
        "session_account": session_label,
        "generated": datetime.now(timezone.utc).isoformat(),
        "chats": chats,
        "messages": all_messages,
        "timeline": timeline,
        "top_words": top_words,
        "hours": hours,
        "totals": {
            "chats_with_activity": len(chats),
            "messages": len(all_messages),
        },
    }


def render_html(data):
    return _HTML_TEMPLATE.replace("__DATA__", json.dumps(data, ensure_ascii=False))


async def _main():
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    sess_file = uc.SESSION_PATH + ".session_string"
    if not os.path.exists(sess_file):
        print("No saved login found. Run `python -m userbot.login` first.")
        return
    with open(sess_file, encoding="utf-8") as fh:
        string = fh.read().strip()

    client = TelegramClient(StringSession(string), uc.API_ID, uc.API_HASH,
                             proxy=getattr(uc, "PROXY", None))
    await client.connect()
    if not await client.is_user_authorized():
        print("Session is no longer valid — run `python -m userbot.login` again.")
        await client.disconnect()
        return

    me = await client.get_me()
    print(f"Logged in as {me.first_name} (@{me.username or me.id}). Scanning...")

    data = await collect_data(client, me)
    await client.disconnect()

    html = render_html(data)
    os.makedirs(os.path.dirname(OUTPUT_FILE) or ".", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"\nDone. Open this file in a browser:\n  {os.path.abspath(OUTPUT_FILE)}")


_HTML_TEMPLATE = """<!doctype html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<title>My Activity Dashboard</title>
<style>
  :root { --bg:#f5f6f8; --card:#ffffff; --text:#1c1e21; --muted:#65676b;
          --accent:#3b82f6; --border:#e4e6eb; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#18191a; --card:#242526; --text:#e4e6eb; --muted:#b0b3b8;
            --accent:#60a5fa; --border:#3a3b3c; }
  }
  * { box-sizing: border-box; }
  body { font-family: Tahoma, "Segoe UI", sans-serif; background:var(--bg);
         color:var(--text); margin:0; padding:20px; }
  h1 { font-size:20px; margin:0 0 4px; }
  .sub { color:var(--muted); font-size:13px; margin-bottom:20px; }
  .grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:16px; }
  @media (max-width:800px) { .grid { grid-template-columns:1fr; } }
  .card { background:var(--card); border:1px solid var(--border); border-radius:10px;
          padding:16px; }
  .card h2 { font-size:15px; margin:0 0 10px; }
  .stat-row { display:flex; gap:20px; margin-bottom:16px; flex-wrap:wrap; }
  .stat { background:var(--card); border:1px solid var(--border); border-radius:10px;
          padding:12px 18px; }
  .stat b { font-size:22px; display:block; }
  .stat span { color:var(--muted); font-size:12px; }
  input[type=text] { width:100%; padding:8px 10px; border-radius:8px;
          border:1px solid var(--border); background:var(--bg); color:var(--text);
          font-size:14px; margin-bottom:10px; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th, td { text-align:right; padding:6px 8px; border-bottom:1px solid var(--border); }
  th { color:var(--muted); font-weight:normal; }
  .msglist { max-height:420px; overflow-y:auto; }
  .bar-row { display:flex; align-items:center; gap:8px; margin-bottom:6px; font-size:12px; }
  .bar-label { width:130px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .bar-track { flex:1; background:var(--bg); border-radius:4px; height:14px; overflow:hidden; }
  .bar-fill { background:var(--accent); height:100%; }
  .wordtag { display:inline-block; background:var(--bg); border:1px solid var(--border);
          border-radius:6px; padding:3px 8px; margin:2px; font-size:12px; }
  canvas { width:100%; height:160px; }
</style>
</head>
<body>
<h1>My Activity Dashboard</h1>
<div class="sub" id="meta"></div>

<div class="stat-row" id="stats"></div>

<div class="grid">
  <div class="card">
    <h2>فعالیت در طول زمان</h2>
    <canvas id="timeline"></canvas>
  </div>
  <div class="card">
    <h2>بیشترین چت/گروه‌ها</h2>
    <div id="perchat"></div>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2>ساعات فعال</h2>
    <canvas id="hours"></canvas>
  </div>
  <div class="card">
    <h2>پرتکرارترین کلمات</h2>
    <div id="words"></div>
  </div>
</div>

<div class="card">
  <h2>جست‌وجو در پیام‌های خودم</h2>
  <input type="text" id="search" placeholder="یه کلمه یا اسم چت بنویس...">
  <div class="msglist">
    <table>
      <thead><tr><th>تاریخ</th><th>چت</th><th>متن</th></tr></thead>
      <tbody id="msgbody"></tbody>
    </table>
  </div>
</div>

<script>
const DATA = __DATA__;

document.getElementById("meta").textContent =
  DATA.me + " — generated " + new Date(DATA.generated).toLocaleString() +
  (DATA.session_account && DATA.session_account !== DATA.me
    ? " — data from session account: " + DATA.session_account : "");

document.getElementById("stats").innerHTML = `
  <div class="stat"><b>${DATA.totals.messages}</b><span>کل پیام‌های من</span></div>
  <div class="stat"><b>${DATA.totals.chats_with_activity}</b><span>چت/گروه فعال</span></div>
`;

// --- per-chat bars
const maxCount = Math.max(1, ...DATA.chats.map(c => c.count));
document.getElementById("perchat").innerHTML = DATA.chats.slice(0, 15).map(c => `
  <div class="bar-row">
    <div class="bar-label" title="${c.name}">${c.name}</div>
    <div class="bar-track"><div class="bar-fill" style="width:${(c.count/maxCount*100)}%"></div></div>
    <div>${c.count}</div>
  </div>
`).join("");

// --- word tags
const maxWord = Math.max(1, ...(DATA.top_words.map(w => w[1]) || [1]));
document.getElementById("words").innerHTML = DATA.top_words.slice(0, 30).map(([w, c]) =>
  `<span class="wordtag" style="font-size:${11 + (c/maxWord)*10}px">${w} (${c})</span>`
).join(" ");

// --- simple canvas line chart for timeline
function drawLine(canvas, points) {
  const ctx = canvas.getContext("2d");
  const W = canvas.width = canvas.clientWidth * 2;
  const H = canvas.height = canvas.clientHeight * 2;
  ctx.clearRect(0, 0, W, H);
  if (!points.length) return;
  const max = Math.max(1, ...points.map(p => p[1]));
  const pad = 20;
  const stepX = (W - pad*2) / Math.max(1, points.length - 1);
  ctx.strokeStyle = getComputedStyle(document.body).getPropertyValue('--accent') || '#3b82f6';
  ctx.lineWidth = 3;
  ctx.beginPath();
  points.forEach((p, i) => {
    const x = pad + i * stepX;
    const y = H - pad - (p[1] / max) * (H - pad*2);
    i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
  });
  ctx.stroke();
}
function drawBars(canvas, values) {
  const ctx = canvas.getContext("2d");
  const W = canvas.width = canvas.clientWidth * 2;
  const H = canvas.height = canvas.clientHeight * 2;
  ctx.clearRect(0, 0, W, H);
  const max = Math.max(1, ...values);
  const bw = W / values.length;
  ctx.fillStyle = '#3b82f6';
  values.forEach((v, i) => {
    const h = (v / max) * (H - 20);
    ctx.fillRect(i * bw + 2, H - h, bw - 4, h);
  });
}
drawLine(document.getElementById("timeline"), DATA.timeline);
drawBars(document.getElementById("hours"), DATA.hours);

// --- search / message table
function renderMessages(filter) {
  const f = (filter || "").toLowerCase();
  const rows = DATA.messages
    .filter(m => !f || m.text.toLowerCase().includes(f) || m.chat.toLowerCase().includes(f))
    .slice(0, 300)
    .map(m => `<tr><td>${m.date ? new Date(m.date).toLocaleString() : "-"}</td>
                   <td>${m.chat}</td><td>${(m.text||"").replace(/</g,"&lt;")}</td></tr>`)
    .join("");
  document.getElementById("msgbody").innerHTML = rows;
}
renderMessages("");
document.getElementById("search").addEventListener("input", e => renderMessages(e.target.value));
</script>
</body>
</html>
"""


if __name__ == "__main__":
    asyncio.run(_main())
