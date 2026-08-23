#!/bin/bash
# init.sh - Turtle Investment Framework environment setup
# Run at the start of each Codex session

set -e

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

echo "=== Turtle Investment Framework - Environment Setup ==="
echo "Project root: $PROJECT_ROOT"
echo ""

# 1. Python environment (venv)
VENV_DIR="$PROJECT_ROOT/.venv"
PYTHON_BIN="$VENV_DIR/bin/python"

echo "[1/5] Setting up Python environment..."

# Find a Python >= 3.10 by searching common candidates
PYTHON_SYS=""
for candidate in python3 python3.14 python3.13 python3.12 python3.11 python3.10 \
                 /opt/homebrew/bin/python3 /opt/homebrew/bin/python3.14 \
                 /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.12 \
                 /opt/homebrew/bin/python3.11 /opt/homebrew/bin/python3.10 \
                 /opt/anaconda3/envs/py10/bin/python; do
    BIN="$(command -v "$candidate" 2>/dev/null || echo "$candidate")"
    if [ -x "$BIN" ]; then
        MAJOR=$($BIN -c 'import sys; print(sys.version_info.major)' 2>/dev/null || echo 0)
        MINOR=$($BIN -c 'import sys; print(sys.version_info.minor)' 2>/dev/null || echo 0)
        if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 10 ]; then
            PYTHON_SYS="$BIN"
            break
        fi
    fi
done

if [ -z "$PYTHON_SYS" ]; then
    echo "  ERROR: No Python >= 3.10 found on this system"
    echo "  Install Python 3.10+ via Homebrew: brew install python@3.12"
    exit 1
fi
PY_VER=$($PYTHON_SYS -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')

if [ ! -f "$PYTHON_BIN" ]; then
    echo "  Creating venv at $VENV_DIR (Python $PY_VER) ..."
    $PYTHON_SYS -m venv "$VENV_DIR"
    VENV_JUST_CREATED=1
else
    VENV_JUST_CREATED=0
fi

export PATH="$VENV_DIR/bin:$PATH"
echo "  Python: $($PYTHON_BIN --version)"
echo "  Using: $PYTHON_BIN"

# 2. Install dependencies (on first create or --force-install)
echo "[2/5] Installing Python dependencies..."
if [ "$VENV_JUST_CREATED" -eq 1 ] || [ "$1" = "--force-install" ]; then
    $PYTHON_BIN -m pip install -q -r requirements.txt
    echo "  Dependencies installed."
else
    echo "  Skipped (venv exists). Use 'bash init.sh --force-install' to reinstall."
fi

# 3. Verify Tushare token
echo "[3/5] Checking Tushare token..."
# Source .env file if present
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a
    source "$PROJECT_ROOT/.env"
    set +a
    echo "  Loaded .env file"
fi
if [ -z "$TUSHARE_TOKEN" ]; then
    echo "  WARNING: TUSHARE_TOKEN not set"
    echo "  Option 1: cp .env.sample .env && edit .env"
    echo "  Option 2: export TUSHARE_TOKEN='your_token_here'"
    echo "  Tests requiring live API will be skipped"
else
    echo "  TUSHARE_TOKEN: set (${#TUSHARE_TOKEN} chars)"
fi

# 4. Create output directory
echo "[4/5] Ensuring output directory..."
mkdir -p output

# 5. Run basic tests
echo "[5/5] Running verification tests..."
$PYTHON_BIN -m pytest tests/ -x -q --tb=short 2>&1 | tail -5

echo ""
echo "=== Setup complete ==="
echo "To run: python scripts/tushare_collector.py --code 600887.SH --output output/data_pack_market.md"
