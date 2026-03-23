#!/usr/bin/env zsh
# Wrapper script — dispatches to the WhatsApp or Telegram start scripts.

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
TARGET="${1:-whatsapp}"

case "$TARGET" in
  whatsapp)
    exec "$ROOT/start_whatsapp.sh"
    ;;
  telegram)
    exec "$ROOT/start_telegram.sh"
    ;;
  both)
    "$ROOT/start_whatsapp.sh"
    "$ROOT/start_telegram.sh"
    ;;
  *)
    echo "Unknown channel '$TARGET'. Use 'whatsapp', 'telegram', or 'both'."
    exit 1
    ;;
esac
