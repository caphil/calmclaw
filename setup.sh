#!/bin/bash

# chmod +x start.sh

# Bootstraps ~/.calmclaw with default config and example files.
# Safe to run multiple times — only creates files that don't exist yet.
# CALMCLAW_DIR is the folder where CalmClaw stores your personal data:
# config files (.env, .env.local), memory, reminders, and logs.
# To use a different folder, add this line to your ~/.zshrc and restart the terminal:
#   export CALMCLAW_DIR=/your/custom/path
CALMCLAW="${CALMCLAW_DIR:-$HOME/.calmclaw}"
export CALMCLAW_DIR="$CALMCLAW"
TEMPLATES="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/templates"

GREEN='\033[0;32m'
LGREEN='\033[1;32m'
CYAN='\033[0;36m'
RESET='\033[0m'

echo ""
echo -e "${CYAN}===============================${RESET}"
echo -e "${CYAN}  Setup${RESET}"
echo -e "${CYAN}===============================${RESET}"
echo ""
echo "  CALMCLAW_DIR=$CALMCLAW"
echo "  (set CALMCLAW_DIR in ~/.zshrc to use a different path)"
echo ""

# Ensure ~/.calmclaw exists
if [ ! -d "$CALMCLAW" ]; then
  mkdir -p "$CALMCLAW"
  echo -e "  ${LGREEN}[CREATED]${RESET} $CALMCLAW"
else
  echo -e "  ${GREEN}[OK]${RESET}      $CALMCLAW already exists"
fi

# Ensure log files exist so tail -f works on first run
for logfile in "conversation.log" "conversation_color.log"; do
  if [ ! -f "$CALMCLAW/$logfile" ]; then
    touch "$CALMCLAW/$logfile"
    echo -e "  ${LGREEN}[CREATED]${RESET} $CALMCLAW/$logfile"
  else
    echo -e "  ${GREEN}[OK]${RESET}      $CALMCLAW/$logfile already exists"
  fi
done

# Copy files from templates if missing
for filename in ".env" ".env.local" "MEMORY.md" "REMINDERS.md" "TASKS.md" "SOUL.md" "SYSTEM_RULES.md" "COMPRESSION_RULES.md"; do
  dest="$CALMCLAW/$filename"
  src="$TEMPLATES/$filename"
  if [ ! -f "$dest" ] && [ -f "$src" ]; then
    cp "$src" "$dest"
    echo -e "  ${LGREEN}[CREATED]${RESET} $dest"
  else
    echo -e "  ${GREEN}[OK]${RESET}      $dest already exists"
  fi
done

echo ""
echo -e "${CYAN}===============================${RESET}"
echo -e "${CYAN}  Setup complete!${RESET}"
echo ""
echo "  Next: edit $CALMCLAW/.env.local"
echo "  and add your Telegram bot token"
echo "  if not completed."
echo -e "${CYAN}===============================${RESET}"
echo ""

