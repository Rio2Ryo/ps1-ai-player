#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${SCRIPT_DIR}"

echo "=== PS1 AI Player Setup ==="
echo "Project directory: ${PROJECT_DIR}"

# Create required directories
echo "[1/5] Creating directories..."
mkdir -p "${PROJECT_DIR}"/{isos,saves,captures,logs,reports,addresses}

# Install system dependencies
echo "[2/5] Installing system dependencies..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    xvfb \
    x11-utils \
    libfuse2 \
    wget \
    curl \
    python3 \
    python3-pip \
    python3-venv \
    xdotool \
    procps

# Download DuckStation AppImage
echo "[3/5] Downloading DuckStation AppImage..."
DUCKSTATION_DIR="${PROJECT_DIR}/duckstation"
mkdir -p "${DUCKSTATION_DIR}"

if [ ! -f "${DUCKSTATION_DIR}/DuckStation.AppImage" ]; then
    DOWNLOAD_URL=$(curl -sL -o /dev/null -w '%{url_effective}' \
        "https://github.com/stenzek/duckstation/releases/latest" | \
        sed 's|/tag/|/download/|')
    APPIMAGE_URL="${DOWNLOAD_URL}/DuckStation-x64.AppImage"

    echo "Downloading from: ${APPIMAGE_URL}"
    wget -q --show-progress -O "${DUCKSTATION_DIR}/DuckStation.AppImage" "${APPIMAGE_URL}" || {
        echo "Warning: Could not download DuckStation AppImage."
        echo "Please download manually from https://github.com/stenzek/duckstation/releases"
        echo "and place it at ${DUCKSTATION_DIR}/DuckStation.AppImage"
    }
    chmod +x "${DUCKSTATION_DIR}/DuckStation.AppImage" 2>/dev/null || true
else
    echo "DuckStation AppImage already exists, skipping download."
fi

# Set up Python virtual environment and install dependencies
echo "[4/5] Setting up Python environment..."
VENV_DIR="${PROJECT_DIR}/venv"

if [ ! -d "${VENV_DIR}" ]; then
    python3 -m venv "${VENV_DIR}"
fi

source "${VENV_DIR}/bin/activate"
pip install --upgrade pip -q
pip install -r "${PROJECT_DIR}/requirements.txt" -q

echo "[5/5] Verifying installation..."

# Verify Xvfb
if command -v Xvfb &>/dev/null; then
    echo "  [OK] Xvfb installed"
else
    echo "  [FAIL] Xvfb not found"
fi

# Verify Python packages (pynput requires X server at import time, so check it separately)
python3 -c "import mss; import openai; import pandas; import matplotlib; import scipy; import requests; import PIL; import numpy" 2>/dev/null && \
    echo "  [OK] Core Python packages installed" || \
    echo "  [FAIL] Some Python packages missing"
# pynput check: verify the package exists without importing (avoids X11 requirement)
python3 -c "import importlib.util; exit(0 if importlib.util.find_spec('pynput') else 1)" 2>/dev/null && \
    echo "  [OK] pynput installed (requires X server at runtime)" || \
    echo "  [FAIL] pynput not found"

# Verify DuckStation
if [ -f "${DUCKSTATION_DIR}/DuckStation.AppImage" ]; then
    echo "  [OK] DuckStation AppImage present"
else
    echo "  [WARN] DuckStation AppImage not found"
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "  1. Place your PS1 ISO files in ${PROJECT_DIR}/isos/"
echo "  2. Set your OpenAI API key: export OPENAI_API_KEY='sk-...'"
echo "  3. Configure DuckStation: python setup_duckstation.py"
echo "  4. Run: ./run.sh --game GAME_ID --iso path/to/game.iso --strategy balanced"
