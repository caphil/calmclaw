#!/bin/bash
# Setup and configuration wizard for CalmClaw.
#
# Usage:
#   ./setup.sh                               — interactive wizard
#   ./setup.sh --non-interactive             — non-interactive, uses current values or defaults
#   CALMCLAW_DIR=~/custom ./setup.sh         — override agent workspace location, interactive
#   CALMCLAW_DIR=~/custom ./setup.sh --non-interactive  — override agent workspace location, non-interactive
#
# Called by install.sh and update.sh, or run directly to reconfigure.
#
# CALMCLAW_DIR resolution order: inline env → ~/.zshrc → default (~/.calmclaw)
# CALMCLAW_DIR is written to ~/.zshrc for persistence across terminals (created if missing).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATES="$SCRIPT_DIR/templates"

SILENT=false
[[ "$1" == "--non-interactive" ]] && SILENT=true

ZSHRC="$HOME/.zshrc"

# Read CALMCLAW_DIR: inline env → .zshrc → default
_zshrc_dir=$(grep -E "^export CALMCLAW_DIR=" "$ZSHRC" 2>/dev/null | tail -1 | sed 's/^export CALMCLAW_DIR=//' | tr -d "'\"")
CALMCLAW_DIR="${CALMCLAW_DIR:-${_zshrc_dir:-$HOME/.calmclaw}}"

# Color theme — based on #0B25DC (deep blue), 256-color index 27
C_BLUE='\033[38;5;27m'       # #0B25DC primary blue
C_LBLUE='\033[1;38;5;27m'    # bold blue
C_GREEN='\033[38;5;40m'      # confirmation green
C_YELLOW='\033[1;33m'        # warnings
C_DIM='\033[2m'
C_BOLD='\033[1m'
C_RESET='\033[0m'

TOTAL_STEPS=6

t()   { printf "$*" > /dev/tty; }
tln() { printf "$*\n" > /dev/tty; }

get_val() {
    local file="$1" key="$2"
    [[ -f "$file" ]] || { echo ""; return; }
    grep -E "^${key}=" "$file" | tail -1 | sed "s/^${key}=//" | tr -d "'\""
}

set_val() {
    local file="$1" key="$2" value="$3"
    if grep -qE "^${key}=" "$file" 2>/dev/null; then
        sed -i '' "s|^${key}=.*|${key}=${value}|" "$file"
    else
        echo "${key}=${value}" >> "$file"
    fi
}

header() {
    tput clear > /dev/tty
    tln "  ${C_LBLUE}╭─────────────────────────────╮${C_RESET}"
    tln "  ${C_LBLUE}│      CalmClaw Setup         │${C_RESET}"
    tln "  ${C_LBLUE}╰─────────────────────────────╯${C_RESET}"
    tln ""
}

step_header() {
    local step="$1" title="$2" desc="$3"
    header
    tln "  ${C_LBLUE}[$step/$TOTAL_STEPS]${C_RESET} ${C_BOLD}$title${C_RESET}"
    tln "  ${C_DIM}$desc${C_RESET}"
    tln ""
}

confirm() {
    local label="$1" value="$2"
    tln "  ${C_GREEN}✓${C_RESET}  ${C_DIM}$label${C_RESET} → ${C_BOLD}$value${C_RESET}"
}

# Arrow-key selection menu. Result stored in MENU_RESULT.
# All I/O via /dev/tty — never touches stdout/stderr.
MENU_RESULT=""
pick_from_menu() {
    local current="$1"; shift
    local options=("$@")
    local selected=0 n=${#options[@]}
    local cols
    cols=$(tput cols 2>/dev/null || echo 80)

    for i in "${!options[@]}"; do
        local label="${options[$i]%%  *}"
        [[ "$label" == "$current" ]] && { selected=$i; break; }
    done

    tput civis > /dev/tty

    # Each option may wrap onto multiple lines; count all rows + hint line.
    menu_rows() {
        local total=1 max_text=$(( cols - 6 ))
        for opt in "${options[@]}"; do
            local len=${#opt}
            local rows=$(( len <= max_text ? 1 : (len + max_text - 1) / max_text ))
            (( total += rows ))
        done
        echo "$total"
    }

    draw_menu() {
        local max_text=$(( cols - 6 ))  # 6 = "  ● " prefix width
        for i in "${!options[@]}"; do
            local label="${options[$i]}" first=true
            while [[ -n "$label" ]]; do
                local chunk="${label:0:$max_text}"
                label="${label:$max_text}"
                if $first; then
                    if [[ $i -eq $selected ]]; then
                        printf "  ${C_LBLUE}  ● %s${C_RESET}\n" "$chunk" > /dev/tty
                    else
                        printf "  ${C_DIM}  ○ %s${C_RESET}\n" "$chunk" > /dev/tty
                    fi
                    first=false
                else
                    if [[ $i -eq $selected ]]; then
                        printf "  ${C_LBLUE}    %s${C_RESET}\n" "$chunk" > /dev/tty
                    else
                        printf "  ${C_DIM}    %s${C_RESET}\n" "$chunk" > /dev/tty
                    fi
                fi
            done
        done
    }

    draw_menu
    printf "  ${C_DIM}↑ ↓ navigate  ·  Confirm with Enter${C_RESET}\n" > /dev/tty
    while true; do
        IFS= read -rsn1 key < /dev/tty
        if [[ "$key" == $'\x1b' ]]; then
            IFS= read -rsn2 rest < /dev/tty
            key+="$rest"
        fi
        case "$key" in
            $'\x1b[A') (( selected > 0   )) && (( selected-- )) ;;
            $'\x1b[B') (( selected < n-1 )) && (( selected++ )) ;;
            '') break ;;
        esac
        tput cuu "$(menu_rows)" > /dev/tty
        draw_menu
        printf "  ${C_DIM}↑ ↓ navigate  ·  Confirm with Enter${C_RESET}\n" > /dev/tty
    done

    tput cnorm > /dev/tty
    tln ""

    local chosen="${options[$selected]%%  *}"
    if [[ "$chosen" == "Other (enter)" ]]; then
        t "  ${C_BLUE}Enter value:${C_RESET} "
        read -r chosen < /dev/tty
    fi
    MENU_RESULT="$chosen"
}

# ── Intro splash ──────────────────────────────────────────
if ! $SILENT; then
    header
    tln "  ${C_DIM}This is CalmClaw's setup wizard${C_RESET}"
    tln "  ${C_DIM}Installation: $SCRIPT_DIR${C_RESET}"
    tln ""
    t "  ${C_DIM}Press any key to begin...${C_RESET}"
    read -rsn1 < /dev/tty
    tln ""
fi

# ── [1/4] CALMCLAW_DIR ────────────────────────────────────
if ! $SILENT; then
    step_header 1 "Agent workspace" "Where CalmClaw stores memory, notes, and config."

    current_dir="${CALMCLAW_DIR/#$HOME/~}"
    _o1="~/.calmclaw";        [[ "$current_dir" == "~/.calmclaw"        ]] && _o1+="  (current)"
    _o2="~/Documents/.calmclaw"; [[ "$current_dir" == "~/Documents/.calmclaw" ]] && _o2+="  (current)"
    if [[ -n "$current_dir" && "$current_dir" != "~/.calmclaw" && "$current_dir" != "~/Documents/.calmclaw" ]]; then
        pick_from_menu "$current_dir" \
            "$current_dir  (current)" \
            "$_o1" \
            "$_o2" \
            "Other (enter)"
    else
        pick_from_menu "$current_dir" \
            "$_o1" \
            "$_o2" \
            "Other (enter)"
    fi
    new_dir="${MENU_RESULT/#\~/$HOME}"
    current_dir_expanded="${current_dir/#\~/$HOME}"
    zshrc_dir="${new_dir/#$HOME/~}"
    if grep -qE "^export CALMCLAW_DIR=" "$ZSHRC" 2>/dev/null; then
        sed -i '' "s|^export CALMCLAW_DIR=.*|export CALMCLAW_DIR=$zshrc_dir|" "$ZSHRC"
    else
        printf '\nexport CALMCLAW_DIR=%s\n' "$zshrc_dir" >> "$ZSHRC"
    fi
    if [[ "$new_dir" != "$current_dir_expanded" ]]; then
        tln "  ${C_YELLOW}⚠  Run 'source ~/.zshrc' or restart your terminal.${C_RESET}"
    fi
    confirm "CALMCLAW_DIR" "${MENU_RESULT}"
else
    new_dir="$CALMCLAW_DIR"
    zshrc_dir="${new_dir/#$HOME/~}"
    if grep -qE "^export CALMCLAW_DIR=" "$ZSHRC" 2>/dev/null; then
        sed -i '' "s|^export CALMCLAW_DIR=.*|export CALMCLAW_DIR=$zshrc_dir|" "$ZSHRC"
    else
        printf '\nexport CALMCLAW_DIR=%s\n' "$zshrc_dir" >> "$ZSHRC"
    fi
fi

# ── Bootstrap ─────────────────────────────────────────────
CALMCLAW="$new_dir"
export CALMCLAW_DIR="$CALMCLAW"
ENV_FILE="$CALMCLAW/.env"
ENV_LOCAL="$CALMCLAW/.env.local"

if ! $SILENT; then
    header
    tln "  ${C_BOLD}Setting up agent workspace${C_RESET}"
    tln "  ${C_DIM}$CALMCLAW${C_RESET}"
    tln ""
fi

if [ ! -d "$CALMCLAW" ]; then
    mkdir -p "$CALMCLAW"
    $SILENT || tln "  ${C_LBLUE}✓${C_RESET}  Created directory"
else
    $SILENT || tln "  ${C_LBLUE}✓${C_RESET}  ${C_DIM}Directory already exists${C_RESET}"
fi

for logfile in "conversation.log" "conversation_color.log"; do
    if [ ! -f "$CALMCLAW/$logfile" ]; then
        touch "$CALMCLAW/$logfile"
        $SILENT || tln "  ${C_LBLUE}✓${C_RESET}  Created $logfile"
    else
        $SILENT || tln "  ${C_LBLUE}✓${C_RESET}  ${C_DIM}$logfile already exists${C_RESET}"
    fi
done

for filename in ".env" ".env.local" "MEMORY.md" "REMINDERS.md" "TASKS.md" "NOTES.md" "SOUL.md" "SYSTEM_RULES.md" "COMPRESSION_RULES.md"; do
    dest="$CALMCLAW/$filename"
    src="$TEMPLATES/$filename"
    if [ ! -f "$dest" ] && [ -f "$src" ]; then
        cp "$src" "$dest"
        $SILENT || tln "  ${C_LBLUE}✓${C_RESET}  Created $filename"
    else
        $SILENT || tln "  ${C_LBLUE}✓${C_RESET}  ${C_DIM}$filename already exists${C_RESET}"
    fi
done

if ! $SILENT; then
    tln ""
    t "  ${C_DIM}Press any key to continue...${C_RESET}"
    read -rsn1 < /dev/tty
fi

if ! $SILENT; then
    # ── [2/6] MAX_TOKEN_INPUT_TO_LLM ─────────────────────────
    step_header 2 "Max input tokens" "How much context is sent to the model per request."

    current_tok=$(get_val "$ENV_FILE" "MAX_TOKEN_INPUT_TO_LLM")
    _t1="2000"; [[ "$current_tok" == "2000" ]] && _t1+="  (current)"
    _t2="3000"; [[ "$current_tok" == "3000" ]] && _t2+="  (current)"
    _t3="4000"; [[ "$current_tok" == "4000" ]] && _t3+="  (current)"
    _t4="5000"; [[ "$current_tok" == "5000" ]] && _t4+="  (current)"
    _t5="6000"; [[ "$current_tok" == "6000" ]] && _t5+="  (current)"
    if [[ -n "$current_tok" && "$current_tok" != "2000" && "$current_tok" != "3000" && "$current_tok" != "4000" && "$current_tok" != "5000" && "$current_tok" != "6000" ]]; then
        pick_from_menu "$current_tok" \
            "$current_tok  (current)" \
            "$_t1" "$_t2" "$_t3" "$_t4" "$_t5" \
            "Other (enter)"
    else
        pick_from_menu "$current_tok" \
            "$_t1" "$_t2" "$_t3" "$_t4" "$_t5" \
            "Other (enter)"
    fi
    set_val "$ENV_FILE" "MAX_TOKEN_INPUT_TO_LLM" "$MENU_RESULT"
    confirm "MAX_TOKEN_INPUT_TO_LLM" "$MENU_RESULT"

    # ── [3/6] TELEGRAM_BOT_TOKEN ─────────────────────────────
    step_header 3 "Telegram bot token" "Get it from @BotFather on Telegram."

    current_token=$(get_val "$ENV_LOCAL" "TELEGRAM_BOT_TOKEN")
    [[ "$current_token" == "your-telegram-bot-token-here" ]] && current_token=""
    if [[ -n "$current_token" ]]; then
        pick_from_menu "$current_token" \
            "$current_token  (current)" \
            "Other (enter)"
        new_token="$MENU_RESULT"
    else
        t "  ${C_BLUE}Enter token:${C_RESET} "
        read -r new_token < /dev/tty
        tln ""
    fi
    [[ -n "$new_token" ]] && set_val "$ENV_LOCAL" "TELEGRAM_BOT_TOKEN" "$new_token"
    confirm "TELEGRAM_BOT_TOKEN" "$new_token"

    # ── [4/6] ALLOWED_TELEGRAM_ID ────────────────────────────
    step_header 4 "Allowed Telegram user ID" "Your numeric Telegram ID: get it from @userinfobot on Telegram."

    current_id=$(get_val "$ENV_LOCAL" "ALLOWED_TELEGRAM_ID")
    [[ "$current_id" == "your-telegram-id-here" ]] && current_id=""
    if [[ -n "$current_id" ]]; then
        pick_from_menu "$current_id" \
            "$current_id  (current)" \
            "Other (enter)"
        new_id="$MENU_RESULT"
    else
        t "  ${C_BLUE}Enter ID:${C_RESET} "
        read -r new_id < /dev/tty
    fi
    [[ -n "$new_id" ]] && set_val "$ENV_LOCAL" "ALLOWED_TELEGRAM_ID" "$new_id"
    confirm "ALLOWED_TELEGRAM_ID" "$new_id"

    # ── [5/6] MLX_MODEL_PATH ─────────────────────────────────
    step_header 5 "MLX model path" "Full path to the MLX model directory."

    tln "  ${C_DIM}Ensure the path points to a valid MLX model directory.${C_RESET}"
    tln ""
    current_mlx_path=$(get_val "$ENV_FILE" "MLX_MODEL_PATH")
    if [[ -n "$current_mlx_path" ]]; then
        pick_from_menu "$current_mlx_path" \
            "$current_mlx_path  (current)" \
            "Other (enter)"
        new_mlx_path="$MENU_RESULT"
    else
        t "  ${C_BLUE}Enter path:${C_RESET} "
        read -r new_mlx_path < /dev/tty
        tln ""
    fi
    [[ -n "$new_mlx_path" ]] && set_val "$ENV_FILE" "MLX_MODEL_PATH" "$new_mlx_path"
    confirm "MLX_MODEL_PATH" "$new_mlx_path"

    # ── [6/6] MLX_SERVER_MODULE ──────────────────────────────
    step_header 6 "MLX server module"

    current_mlx_mod=$(get_val "$ENV_FILE" "MLX_SERVER_MODULE")
    _m1="mlx_lm.server";  [[ "$current_mlx_mod" == "mlx_lm.server"  ]] && _m1+="  (current)"
    _m2="mlx_vlm.server"; [[ "$current_mlx_mod" == "mlx_vlm.server" ]] && _m2+="  (current)"
    if [[ -n "$current_mlx_mod" && "$current_mlx_mod" != "mlx_lm.server" && "$current_mlx_mod" != "mlx_vlm.server" ]]; then
        pick_from_menu "$current_mlx_mod" \
            "$current_mlx_mod  (current)" \
            "$_m1" "$_m2" \
            "Other (enter)"
    else
        pick_from_menu "$current_mlx_mod" \
            "$_m1" "$_m2" \
            "Other (enter)"
    fi
    set_val "$ENV_FILE" "MLX_SERVER_MODULE" "$MENU_RESULT"
    confirm "MLX_SERVER_MODULE" "$MENU_RESULT"

    # ── Done ──────────────────────────────────────────────────
    header
    tln "  ${C_BOLD}Setup complete!${C_RESET}"
    tln "  ${C_DIM}Installation: $SCRIPT_DIR${C_RESET}"
    tln "  ${C_DIM}Agent workspace: ${CALMCLAW/#$HOME/~}${C_RESET}"
    tln ""
    pick_from_menu "" \
        "Start CalmClaw" \
        "Quit for now"
    tln "  ${C_DIM}You can close this window now.${C_RESET}"
    tln ""
    if [[ "$MENU_RESULT" == "Start CalmClaw" ]]; then
        exec "$SCRIPT_DIR/start.sh"
    fi
fi
