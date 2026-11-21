# -*- coding: utf-8 -*-
"""Live spot-check (network) for God's Eye v4 — run manually, not part
of the offline suite:

    ~/workspace/.venv_ge/bin/python tests/live_spotcheck.py

For each Iranian platform: one KNOWN existing public channel must yield
findings and a gibberish id must yield none. Then the v3.1 regression
cases: the full username sweep for a gibberish handle must yield ZERO
findings, and WhatsApp must stay silent (today's wa.me page carries no
per-account signal).

The VM reaches the internet through a sandbox proxy, so the aiohttp
session is patched with trust_env=True for transport only; provider and
parser code under test is untouched.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import aiohttp  # noqa: E402

_orig_session = aiohttp.ClientSession


class _ProxySession(_orig_session):
    def __init__(self, *a, **kw):
        kw.setdefault("trust_env", True)
        super().__init__(*a, **kw)


aiohttp.ClientSession = _ProxySession

import providers as P  # noqa: E402

GIB = "zzqqxnonexist99213"
FAIL = []


def report(label, findings, expect):
    ok = (len(findings) > 0) if expect == "some" else (len(findings) == 0)
    print(f"{'PASS' if ok else 'FAIL'} {label}: {len(findings)} finding(s)"
          f" (expected {expect})")
    for f in findings[:6]:
        print(f"      [{f['source']}] {f['title']}: {str(f['value'])[:90]}")
    if not ok:
        FAIL.append(label)


async def main():
    cases = [
        ("eitaa existing tasnimnews", P.EitaaProvider(), "tasnimnews", "some"),
        ("eitaa gibberish", P.EitaaProvider(), GIB, "none"),
        ("rubika existing TasnimNews", P.RubikaProvider(), "TasnimNews", "some"),
        ("rubika gibberish", P.RubikaProvider(), GIB, "none"),
        ("bale existing TasnimNews", P.BaleProvider(), "TasnimNews", "some"),
        ("bale gibberish", P.BaleProvider(), GIB, "none"),
        ("soroush existing TasnimNews", P.SoroushProvider(), "TasnimNews", "some"),
        ("soroush gibberish", P.SoroushProvider(), GIB, "none"),
        ("virasty existing khamenei_ir", P.VirastyProvider(), "khamenei_ir", "some"),
        ("virasty gibberish", P.VirastyProvider(), GIB, "none"),
    ]
    for label, provider, value, expect in cases:
        try:
            findings = await provider.search("username", value)
        except Exception as e:
            findings = []
            print(f"ERR  {label}: {e!r}")
        report(label, findings, expect)

    # v4.2: Instagram end-to-end — fetch with the crawler UA, parse.
    ig_ok = await P.fetch_text("https://www.instagram.com/nasa/",
                               headers=P.CRAWLER_HEADERS)
    report("instagram existing nasa (crawler UA)",
           P.parse_instagram_page(ig_ok or "", "nasa"), "some")
    ig_no = await P.fetch_text(f"https://www.instagram.com/{GIB}/",
                               headers=P.CRAWLER_HEADERS)
    report("instagram gibberish (crawler UA)",
           P.parse_instagram_page(ig_no or "", GIB), "none")

    # v4.3: Instagram dual route, live. Route A (web_profile_info
    # JSON) is rate-limited per IP — from this VM's datacenter range
    # it usually answers 429, which is exactly what route B exists
    # for. Report honestly which route produced the nasa findings.
    ig_a_data = await P.fetch_json(
        "https://www.instagram.com/api/v1/users/web_profile_info/"
        "?username=nasa",
        headers={"x-ig-app-id": P.IG_APP_ID})
    ig_a = P.parse_instagram_api(ig_a_data, "nasa") if ig_a_data else []
    if ig_a:
        print("instagram route A (web_profile_info): LIVE — produced "
              f"{len(ig_a)} findings")
        report("instagram nasa via route A", ig_a, "some")
        _bio = [f for f in ig_a if f["title"] == "Bio"]
        print("      route A bio present:", bool(_bio))
    else:
        print("instagram route A (web_profile_info): no data from this "
              "VM (rate-limited/blocked) — route B carried the result")
        report("instagram nasa via route B (fallback)",
               P.parse_instagram_page(ig_ok or "", "nasa"), "some")
    # The provider itself must return findings through whichever
    # route works, and the avatar must be a 'photo' finding.
    ig_prov = await P.UsernameProfileProvider()._instagram("nasa")
    report("instagram provider nasa (dual route)", ig_prov, "some")
    _ig_photos = [f for f in ig_prov if f["category"] == "photo"]
    print("      provider photo findings (category 'photo'):",
          len(_ig_photos))
    if not _ig_photos:
        FAIL.append("instagram provider photo category")
    ig_prov_no = await P.UsernameProfileProvider()._instagram(GIB)
    report("instagram provider gibberish (dual route)", ig_prov_no, "none")

    wa = await P.WhatsAppProvider().search("phone", "+989120000000")
    report("whatsapp valid-format number (no public signal expected)", wa, "none")

    sweep = await P.UsernameProfileProvider().search("username", GIB)
    report("username sweep gibberish (regression rule)", sweep, "none")

    tg = await P.TelegramWebProvider().search("username", GIB)
    report("telegram gibberish", tg, "none")

    print()
    if FAIL:
        print("LIVE FAILURES:", FAIL)
        sys.exit(1)
    print("LIVE SPOT-CHECK PASSED")


asyncio.run(main())
