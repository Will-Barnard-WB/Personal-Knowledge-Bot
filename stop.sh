#!/usr/bin/env zsh
# Wrapper script — dispatch stop to WhatsApp or Telegram stacks.

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
TARGET="${1:-whatsapp}"

case "$TARGET" in
  whatsapp)
    exec "$ROOT/stop_whatsapp.sh"
    ;;
  telegram)
    exec "$ROOT/stop_telegram.sh"
    ;;
  both)
    "$ROOT/stop_whatsapp.sh"
    "$ROOT/stop_telegram.sh"
    ;;
  *)
    echo "Unknown channel '$TARGET'. Use 'whatsapp', 'telegram', or 'both'."
    exit 1
    ;;
esac
