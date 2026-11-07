#!/usr/bin/env bash
# RaceProof / RaceOracle — Unix / Linux / macOS Launcher Script
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH}"

# Detect python executable
PYTHON_BIN="python3"
if ! command -v "$PYTHON_BIN" &> /dev/null; then
    PYTHON_BIN="python"
fi

if [ $# -eq 0 ]; then
    exec "$PYTHON_BIN" -m race_proof.cli tui
else
    exec "$PYTHON_BIN" -m race_proof.cli "$@"
fi

