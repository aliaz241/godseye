#!/data/data/com.termux/files/usr/bin/bash
# God's Eye — run on Termux with auto-restart + wake lock.
# Stop with Ctrl+C (twice) or by closing the session.
cd "$(dirname "$0")"

termux-wake-lock || true
echo "God's Eye starting... log: godseye.log"
while true; do
  python bot.py >> godseye.log 2>&1
  echo "$(date) — bot stopped, restarting in 5s" >> godseye.log
  sleep 5
done
