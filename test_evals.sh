#!/usr/bin/env bash
# Start MLX server, run evals, stop server.
# Usage: ./run_evals.sh

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="${CALMCLAW_DIR:-$HOME/.calmclaw}/.env"
ENV_LOCAL="${CALMCLAW_DIR:-$HOME/.calmclaw}/.env.local"

# Load .env and .env.local
load_env() {
    local file="$1"
    [[ -f "$file" ]] || return 0
    while IFS= read -r line || [[ -n "$line" ]]; do
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ -z "${line// }" ]] && continue
        export "${line?}"
    done < "$file"
}
load_env "$ENV_FILE"
load_env "$ENV_LOCAL"

PORT="${PORT:-8000}"
MLX_PYTHON_PATH="${MLX_PYTHON_PATH:-}"
MLX_MODEL_PATH="${MLX_MODEL_PATH:-}"
MLX_SERVER_MODULE="${MLX_SERVER_MODULE:-mlx_lm.server}"

if [[ -z "$MLX_PYTHON_PATH" ]]; then
    echo "ERROR: MLX_PYTHON_PATH not set in .env"
    exit 1
fi
# Resolve relative path against SCRIPT_DIR
[[ "$MLX_PYTHON_PATH" != /* ]] && MLX_PYTHON_PATH="$SCRIPT_DIR/$MLX_PYTHON_PATH"
if [[ -z "$MLX_MODEL_PATH" ]]; then
    echo "ERROR: MLX_MODEL_PATH not set in .env"
    exit 1
fi

echo "[evals] Starting MLX server (${MLX_SERVER_MODULE}) on port ${PORT}..."
"$MLX_PYTHON_PATH" -m "$MLX_SERVER_MODULE" \
    --model "$MLX_MODEL_PATH" \
    --port "$PORT" \
    > /tmp/mlx_eval_server.log 2>&1 &
MLX_PID=$!

cleanup() {
    echo "[evals] Stopping MLX server (PID $MLX_PID)..."
    kill "$MLX_PID" 2>/dev/null || true
    wait "$MLX_PID" 2>/dev/null || true
}
trap cleanup EXIT

# Wait for server to be ready (up to 60s)
echo "[evals] Waiting for server to be ready..."
for i in $(seq 1 60); do
    if curl -sf "http://localhost:${PORT}/v1/models" > /dev/null 2>&1; then
        echo "[evals] Server ready after ${i}s"
        break
    fi
    if ! kill -0 "$MLX_PID" 2>/dev/null; then
        echo "ERROR: MLX server process died. Log:"
        cat /tmp/mlx_eval_server.log
        exit 1
    fi
    sleep 1
    if [[ $i -eq 60 ]]; then
        echo "ERROR: Server did not become ready after 60s. Log:"
        cat /tmp/mlx_eval_server.log
        exit 1
    fi
done

echo "[evals] Running eval tests..."
cd "$SCRIPT_DIR"
.venv/bin/pytest tests/evals/ -v --run-evals
