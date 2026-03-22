#!/bin/bash

# CalmClaw installer
# Usage: curl -LsSf https://raw.githubusercontent.com/caphil/calmclaw/main/install.sh | bash
# Override install location: INSTALL_DIR=~/mydir curl ... | bash

set -e

REPO_URL="https://github.com/caphil/calmclaw.git"
INSTALL_DIR="${INSTALL_DIR:-$HOME/Applications/CalmClaw}"
CALMCLAW_DIR="${CALMCLAW_DIR:-$HOME/.calmclaw}"
ZSHRC="$HOME/.zshrc"

GREEN='\033[0;32m'
LGREEN='\033[1;32m'
CYAN='\033[0;36m'
RED='\033[0;31m'
RESET='\033[0m'

echo ""
echo -e "${CYAN}===============================${RESET}"
echo -e "${CYAN}  CalmClaw Installer${RESET}"
echo -e "${CYAN}===============================${RESET}"
echo ""

# Check ~/.zshrc
if [[ ! -f "$ZSHRC" ]]; then
  echo -e "  ${RED}[ERROR]${RESET} ~/.zshrc not found. Please create it before installing."
  exit 1
fi

# Check git
if ! command -v git &>/dev/null; then
  echo -e "  ${RED}[ERROR]${RESET} git is required but not installed."
  echo "  Install Xcode Command Line Tools: xcode-select --install"
  exit 1
fi
echo -e "  ${GREEN}[OK]${RESET}      git found"

# Check/install uv
if ! command -v uv &>/dev/null; then
  echo -e "  ${CYAN}[INSTALL]${RESET} uv not found — installing..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  if ! command -v uv &>/dev/null; then
    echo -e "  ${RED}[ERROR]${RESET} uv install failed or not on PATH. Install manually: https://docs.astral.sh/uv/"
    exit 1
  fi
fi
echo -e "  ${GREEN}[OK]${RESET}      uv found"

# Clone repo
if [ -d "$INSTALL_DIR" ]; then
  echo -e "  ${RED}[ERROR]${RESET} Directory already exists: $INSTALL_DIR"
  echo "  Remove it or set a different location: INSTALL_DIR=~/mypath curl ... | bash"
  exit 1
fi
echo -e "  ${CYAN}[CLONE]${RESET}   Cloning into $INSTALL_DIR..."
git clone "$REPO_URL" "$INSTALL_DIR"
echo -e "  ${LGREEN}[DONE]${RESET}    Cloned"

# Create venv and install dependencies
echo -e "  ${CYAN}[INSTALL]${RESET} Creating venv and installing dependencies..."
cd "$INSTALL_DIR"
uv venv --python 3.14
uv pip install -r requirements-lock.txt
echo -e "  ${LGREEN}[DONE]${RESET}    Dependencies installed"

# Bootstrap and configure
echo ""
export CALMCLAW_DIR
"$INSTALL_DIR/setup.sh" "$@"
