#!/bin/bash

# Updates CalmClaw: pulls latest code, refreshes dependencies, and runs setup.

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

GREEN='\033[0;32m'
LGREEN='\033[1;32m'
CYAN='\033[0;36m'
RED='\033[0;31m'
RESET='\033[0m'

echo ""
echo -e "${CYAN}===============================${RESET}"
echo -e "${CYAN}  CalmClaw Update${RESET}"
echo -e "${CYAN}===============================${RESET}"
echo ""

# Pull latest code
echo -e "  ${CYAN}[GIT]${RESET}     Pulling latest changes..."
git -C "$PROJECT_DIR" fetch origin main
git -C "$PROJECT_DIR" reset --hard origin/main
echo -e "  ${LGREEN}[DONE]${RESET}    Code updated"

# Refresh dependencies
echo -e "  ${CYAN}[INSTALL]${RESET} Refreshing dependencies..."
"$PROJECT_DIR/.venv/bin/uv" pip install -r "$PROJECT_DIR/requirements-lock.txt" 2>/dev/null \
  || uv pip install -r "$PROJECT_DIR/requirements-lock.txt"
echo -e "  ${LGREEN}[DONE]${RESET}    Dependencies refreshed"

# Run setup to pick up any new template files
export CALMCLAW_DIR
"$PROJECT_DIR/setup.sh" "$@"
