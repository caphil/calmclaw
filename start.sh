#!/bin/bash

# chmod +x start.sh

# Derive project directory from script location
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CALMCLAW="${CALMCLAW_DIR:-$HOME/.calmclaw}"

# Bootstrap ~/.calmclaw and example files
"$PROJECT_DIR/setup.sh"

# Load config from ~/.calmclaw/.env
if [ -f "$CALMCLAW/.env" ]; then
  set -a
  source "$CALMCLAW/.env"
  set +a
fi
if [ -f "$CALMCLAW/.env.local" ]; then
  set -a
  source "$CALMCLAW/.env.local"
  set +a
fi

# Fallbacks
MLX_MODEL_PATH="${MLX_MODEL_PATH:-/Users/Shared/.lmstudio/models/lmstudio-community/gpt-oss-safeguard-20b-MLX-MXFP4}"
PORT="${PORT:-8080}"
CDP_PORT="${CDP_PORT:-9222}"

# Compute derived token vars if not set explicitly (values come from .env above)
MAX_TOKEN_OUTPUT_FROM_LLM="${MAX_TOKEN_OUTPUT_FROM_LLM:-$(awk "BEGIN{printf \"%d\", $MAX_TOKEN_INPUT_TO_LLM * $MAX_TOKEN_OUTPUT_FACTOR}")}"

# Function to create and launch a specific command window
launch_win() {
  NAME=$1
  CMD=$2
  SCRIPT_PATH="/tmp/od_$NAME.command"

  echo "#!/bin/bash" > "$SCRIPT_PATH"
  echo "$CMD" >> "$SCRIPT_PATH"
  chmod +x "$SCRIPT_PATH"
  open "$SCRIPT_PATH"
}


# Window 2: MLX
# WARNING: Keep --prompt-cache-size 0. mlx-lm 0.31.1 has a bug in BatchRotatingKVCache.merge
# that crashes when merging caches of different sizes. Setting this to 0 disables caching entirely.
launch_win "mlx" "${PROJECT_DIR}/.venv/bin/python -m ${MLX_SERVER_MODULE/.server/ server} --model $MLX_MODEL_PATH --prompt-cache-size 0 --max-tokens $MAX_TOKEN_OUTPUT_FROM_LLM"

# Window 3: Chrome (keep as terminal window — closing it kills Chrome)
launch_win "chrome" "/Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --remote-debugging-port=$CDP_PORT --user-data-dir=\"$HOME/chrome-profile\""

# Window 4: Bot
launch_win "bot" "cd $PROJECT_DIR && source .venv/bin/activate && python main.py"

# Window 5: Memory
launch_win "memory" "while clear && cat $CALMCLAW/MEMORY.md; do sleep 5; done"

# Window 6: Reminders
launch_win "reminders" "while clear && cat $CALMCLAW/REMINDERS.md 2>/dev/null || echo 'No reminders'; do sleep 2; done"

# Window 7: Tasks
launch_win "tasks" "while clear && cat $CALMCLAW/TASKS.md 2>/dev/null || echo 'No tasks'; do sleep 2; done"

# Window 1: Log
launch_win "log" "tail -n 200 -f $CALMCLAW/conversation_color.log"