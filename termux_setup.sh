#!/data/data/com.termux/files/usr/bin/bash
# God's Eye — one-time Termux setup. Run:  bash termux_setup.sh
set -e

pkg update -y
pkg install -y python unzip nano

# storage access so the project zip can be copied from Download
termux-setup-storage || true

# NOTE: do NOT `pip install --upgrade pip` on Termux — it is forbidden
# and breaks the python-pip package. Use the system pip as-is.
pip install -r requirements.txt

echo ""
echo "Setup done. Next:"
echo "  1) nano config.py   -> set BOT_TOKEN and OWNER_ID"
echo "  2) bash termux_run.sh"
