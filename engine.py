# -*- coding: utf-8 -*-
"""God's Eye — search engine (same design as the Telethon edition)."""
import asyncio

import config
from providers import build_providers, clean_handle


def guess_identifier(raw: str):
    raw = raw.strip()
    if raw.isdigit():
        # Iranian phone numbers sent without "+": 09xxxxxxxxx (local) or
        # 989xxxxxxxxxx (international). Telegram user IDs are <= 10 digits.
        # The local 09 form is normalized to the +98 international form
        # (v4.2): the dossier must own ONE canonical phone value, or the
        # same number in two spellings splits into two dossiers.
        if raw.startswith("09") and len(raw) == 11:
            return "phone", "+98" + raw[1:]
        if raw.startswith("98") and len(raw) == 12:
            return "phone", "+" + raw
        return "telegram_id", raw
    if "@" in raw and "." in raw and " " not in raw:
        return "email", raw.lower()
    if raw.startswith("+") and raw[1:].replace(" ", "").isdigit():
        return "phone", raw.replace(" ", "")
    if raw.startswith("@") or (" " not in raw and raw.replace("_", "").replace(".", "").isalnum()):
        return "username", clean_handle(raw)
    return "name", raw


class Engine:
    def __init__(self, db, api=None):
        self.db = db
        self.providers = build_providers(api)

    async def resolve_or_create(self, id_type: str, value: str) -> int:
        person_id = await self.db.find_person_by_identifier(id_type, value)
        if person_id is not None:
            return person_id
        person_id = await self.db.create_person(label=value)
        await self.db.add_identifier(person_id, id_type, value)
        return person_id

    async def attach(self, person_id: int, id_type: str, value: str):
        """Attach an identifier to a dossier.

        Returns (person_id, merged_from): when the identifier already
        belonged to a DIFFERENT dossier, that dossier is merged into
        this one (v4.2 — previously the identifier silently "stayed"
        with the other dossier and the attach had no effect) and
        merged_from is the removed dossier's id; otherwise None. The
        identifier itself arrives with the merge (merge moves all of
        the other dossier's identifiers), so no extra insert is needed
        in that case."""
        owner = await self.db.find_person_by_identifier(id_type, value)
        if owner is not None and owner != person_id:
            await self.db.merge_persons(person_id, owner)
            return person_id, owner
        await self.db.add_identifier(person_id, id_type, value)
        return person_id, None

    async def run_search(self, person_id: int, on_progress=None) -> dict:
        """Run every applicable provider for every identifier of the
        person, all concurrently.

        v4.1 contract:
        - Each provider's findings are stored the moment THAT provider
          finishes (not after the slowest one), and `on_progress` is
          awaited with a snapshot dict after each completion:
          {"provider": name, "done": int, "total": int,
           "providers": [names that will run...], "new_findings": int,
           "results": {name: [findings...]}}
          so the bot can repaint live progress. Providers sharing a
          name (Telegram web + Bot API) are reported once, when the
          last of them finishes.
        - The whole search is capped by config.SEARCH_DEADLINE seconds;
          providers still running at the deadline are abandoned and
          whatever was found is delivered.
        """
        search_id = await self.db.start_search(person_id)
        new_count = 0
        per_source = {}
        try:
            identifiers = await self.db.list_identifiers(person_id)
            jobs = {}  # asyncio.Task -> provider
            planned = []  # unique provider names that will run, in order
            for ident in identifiers:
                for provider in self.providers:
                    if ident["type"] in provider.handles:
                        jobs[asyncio.ensure_future(self._safe_search(
                            provider, ident["type"], ident["value"]))] = provider
                        if provider.name not in planned:
                            planned.append(provider.name)
            total = len(jobs)
            pending = set(jobs)
            results = {}
            done_names = set()

            async def _store(findings):
                nonlocal new_count
                for f in findings:
                    added = await self.db.add_finding(
                        person_id, search_id, f["source"], f["category"],
                        f.get("title"), f["value"], f.get("snippet"),
                    )
                    if added:
                        new_count += 1
                        src = f["source"]
                        per_source[src] = per_source.get(src, 0) + 1

            async def _report(name):
                if on_progress is None:
                    return
                try:
                    await on_progress({
                        "provider": name,
                        "done": len(done_names),
                        "total": total,
                        "providers": list(planned),
                        "new_findings": new_count,
                        "results": results,
                    })
                except Exception:
                    pass

            if on_progress is not None and total:
                try:
                    await on_progress({
                        "provider": None, "done": 0, "total": total,
                        "providers": list(planned), "new_findings": 0,
                        "results": {},
                    })
                except Exception:
                    pass
            loop = asyncio.get_event_loop()
            deadline = loop.time() + config.SEARCH_DEADLINE
            try:
                while pending:
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        break  # overall deadline hit; abandon the rest
                    finished, pending = await asyncio.wait(
                        pending, timeout=remaining,
                        return_when=asyncio.FIRST_COMPLETED)
                    if not finished:
                        break  # deadline hit; abandon the rest
                    for task in finished:
                        provider = jobs[task]
                        findings = task.result()
                        results.setdefault(provider.name, []).extend(findings)
                        await _store(findings)
                        if not any(jobs[t] is provider or
                                   jobs[t].name == provider.name
                                   for t in pending):
                            done_names.add(provider.name)
                            await _report(provider.name)
            finally:
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
            await self.db.finish_search(search_id, "done")
        except Exception:
            await self.db.finish_search(search_id, "error")
            raise
        return {"search_id": search_id, "new_findings": new_count,
                "per_source": per_source}

    @staticmethod
    async def _safe_search(provider, id_type, value):
        try:
            return await provider.search(id_type, value)
        except Exception:
            return []

    async def dossier(self, person_id: int) -> dict:
        person = await self.db.get_person(person_id)
        if person is None:
            return {}
        return {
            "person": person,
            "identifiers": await self.db.list_identifiers(person_id),
            "findings": await self.db.list_findings(person_id),
        }
