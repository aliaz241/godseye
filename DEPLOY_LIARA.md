# Deploying God's Eye on Liara (Docker Platform) — Step by Step

## Prerequisites
1. A Liara account (console at liara.ir)
2. The project code on GitHub — a **private** repo is recommended (see note 2 for why)
3. A bot token from @BotFather and your own numeric Telegram ID

## Steps
1. In `config.py`, set the `BOT_TOKEN` and `OWNER_ID` values.
2. Push the `godseye_botonly` folder to the GitHub repo. The repo root must contain the `Dockerfile`.
3. In the Liara console: create a new app → **Docker** platform → connect it to the same repo.
4. **Disk (important):** before deploying, create a disk and set the mount path to `/app`. The database (`godseye.db`) is created inside `/app`; without a disk, the database is wiped on every redeploy.
5. Deploy and watch the logs until the bot comes up and polling starts.
6. Message the bot on Telegram and test `/new`.

## Notes
1. The bot uses long polling; it needs no port or domain.
2. If the repo is **public**, do not hardcode the token — anyone who sees the repo can steal the token and take over the bot. Either make the repo private, or read the token from an environment variable.
3. The exact labels in the Liara console may differ slightly from this guide; if you get stuck somewhere, say which page it is and you'll be guided precisely.
