#!/bin/sh
set -e
# Salin langganan awal ke volume persisten hanya jika belum ada.
if [ -n "$SUBS_FILE" ] && [ ! -f "$SUBS_FILE" ] && [ -f /app/subscriptions.json ]; then
  mkdir -p "$(dirname "$SUBS_FILE")"
  cp /app/subscriptions.json "$SUBS_FILE"
fi
exec python /app/discord_notifier.py