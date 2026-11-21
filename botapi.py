# -*- coding: utf-8 -*-
"""Minimal async Telegram Bot API client (aiohttp only).

Only what God's Eye needs: getUpdates (long polling), sendMessage,
editMessageText, getChat, getUserProfilePhotos and sendPhoto
(URL / file_id first, byte upload as fallback — v4.3).
"""
import os

import aiohttp

import config


class BotApi:
    def __init__(self, token: str):
        self.base = f"https://api.telegram.org/bot{token}"
        self._session = None

    async def _get_session(self):
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=config.POLL_TIMEOUT + 15)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def call(self, method: str, **params):
        session = await self._get_session()
        async with session.post(f"{self.base}/{method}", json=params) as resp:
            data = await resp.json()
            if not data.get("ok"):
                raise RuntimeError(f"Bot API {method} failed: {data.get('description')}")
            return data["result"]

    async def get_updates(self, offset=None, timeout=None):
        params = {"allowed_updates": ["message", "callback_query"]}
        if offset is not None:
            params["offset"] = offset
        if timeout is not None:
            params["timeout"] = timeout
        return await self.call("getUpdates", **params)

    async def send_message(self, chat_id, text, reply_to=None, reply_markup=None):
        params = {"chat_id": chat_id, "text": text}
        if reply_to is not None:
            params["reply_parameters"] = {"message_id": reply_to}
        if reply_markup is not None:
            params["reply_markup"] = reply_markup
        return await self.call("sendMessage", **params)

    async def edit_message(self, chat_id, message_id, text, reply_markup=None):
        params = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if reply_markup is not None:
            params["reply_markup"] = reply_markup
        return await self.call("editMessageText", **params)

    async def answer_callback_query(self, callback_query_id, text=None):
        params = {"callback_query_id": callback_query_id}
        if text:
            params["text"] = text
        try:
            return await self.call("answerCallbackQuery", **params)
        except Exception:
            return None

    async def get_user_profile_photos(self, user_id, limit=None):
        """getUserProfilePhotos; returns result dict or None when the bot
        cannot see that user. `limit` caps how many of the user's
        profile photos are returned (newest first)."""
        params = {"user_id": user_id}
        if limit is not None:
            params["limit"] = limit
        session = await self._get_session()
        async with session.post(
            f"{self.base}/getUserProfilePhotos", json=params
        ) as resp:
            data = await resp.json()
            return data.get("result") if data.get("ok") else None

    async def send_photo(self, chat_id, photo, caption=None):
        """sendPhoto — delivers a REAL photo, never a link (v4.3).

        `photo` may be a Telegram file_id, an http(s) URL, a local
        file path, or raw image bytes. A file_id / URL is first passed
        straight to the API (Telegram fetches URLs itself); if that
        fails for a URL, the bytes are downloaded here and uploaded as
        multipart/form-data. A local path is read and uploaded the
        same way. Raw bytes go straight to the upload.
        Returns the API result, or None when every route failed —
        callers skip quietly; the URL is never sent as text instead.
        """
        if isinstance(photo, (bytes, bytearray)):
            return await self._send_photo_upload(chat_id, bytes(photo), caption)
        if isinstance(photo, str) and os.path.exists(photo):
            try:
                with open(photo, "rb") as fh:
                    return await self._send_photo_upload(
                        chat_id, fh.read(), caption)
            except Exception:
                return None
        params = {"chat_id": chat_id, "photo": photo}
        if caption:
            params["caption"] = caption
        try:
            return await self.call("sendPhoto", **params)
        except Exception:
            pass
        if isinstance(photo, str) and photo.startswith(("http://", "https://")):
            data = await self._download(photo)
            if data:
                return await self._send_photo_upload(chat_id, data, caption)
        return None

    async def _download(self, url):
        try:
            session = await self._get_session()
            async with session.get(url) as resp:
                if resp.status != 200:
                    return None
                return await resp.read()
        except Exception:
            return None

    async def _send_photo_upload(self, chat_id, data: bytes, caption=None):
        try:
            session = await self._get_session()
            form = aiohttp.FormData()
            form.add_field("chat_id", str(chat_id))
            if caption:
                form.add_field("caption", caption)
            form.add_field("photo", data, filename="photo.jpg",
                           content_type="image/jpeg")
            async with session.post(f"{self.base}/sendPhoto", data=form) as resp:
                payload = await resp.json()
                return payload.get("result") if payload.get("ok") else None
        except Exception:
            return None

    async def send_document(self, chat_id, path, caption=None, filename=None):
        """sendDocument — uploads a local file (e.g. a generated report).
        Returns the API result, or None if the upload failed."""
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except Exception:
            return None
        try:
            session = await self._get_session()
            form = aiohttp.FormData()
            form.add_field("chat_id", str(chat_id))
            if caption:
                form.add_field("caption", caption)
            form.add_field("document", data,
                           filename=filename or os.path.basename(path),
                           content_type="application/octet-stream")
            async with session.post(f"{self.base}/sendDocument", data=form) as resp:
                payload = await resp.json()
                return payload.get("result") if payload.get("ok") else None
        except Exception:
            return None

    async def get_chat(self, chat_id):
        """Raw getChat; returns dict or None when the bot cannot see the chat."""
        session = await self._get_session()
        async with session.post(f"{self.base}/getChat", json={"chat_id": chat_id}) as resp:
            data = await resp.json()
            return data.get("result") if data.get("ok") else None

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
