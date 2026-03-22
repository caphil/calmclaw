#!/usr/bin/env bash
# Run unit tests (no MLX server required).
# Usage: ./test_unit.sh
set -e
cd "$(dirname "$0")"
.venv/bin/pytest tests/ -v
