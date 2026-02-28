#!/bin/bash
set -euo pipefail

# PS1 AI Player - Master Launch Script
# Starts Xvfb, DuckStation, memory logger, and AI agent.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DUCKSTATION="${DUCKSTATION_PATH:-${SCRIPT_DIR}/duckstation/DuckStation.AppImage}"
VENV_PYTHON="${SCRIPT_DIR}/venv/bin/python"
DISPLAY_NUM=99
PIDS=()

# Load .env file if it exists (does not override already-set variables)
if [ -f "${SCRIPT_DIR}/.env" ]; then
    set -a
    # shellcheck source=/dev/null
    . "${SCRIPT_DIR}/.env"
    set +a
fi

# Default arguments
GAME_ID=""
ISO_PATH=""
STRATEGY="balanced"
DURATION=3600
DETAIL="low"
INTERVAL=5.0
OPENAI_KEY="${OPENAI_API_KEY:-}"

usage() {
    echo "Usage: $0 --game GAME_ID --iso ISO_PATH [options]"
    echo ""
    echo "Required:"
    echo "  --game GAME_ID        Game identifier (e.g., SLPM-86023)"
    echo "  --iso ISO_PATH        Path to the PS1 ISO file"
    echo ""
    echo "Optional:"
    echo "  --strategy STRATEGY   AI strategy: expansion|satisfaction|cost_reduction|exploration|balanced (default: balanced)"
    echo "  --duration SECONDS    How long to run in seconds (default: 3600)"
    echo "  --detail low|high     GPT-4o Vision detail level (default: low)"
    echo "  --interval SECONDS    Agent loop interval (default: 5.0)"
    echo "  --openai-key KEY      OpenAI API key (default: OPENAI_API_KEY env var)"
    echo "  --no-xvfb             Skip Xvfb (use existing display)"
    echo "  --help                Show this help"
    echo ""
    echo "Environment variables:"
    echo "  OPENAI_API_KEY        OpenAI API key (can also use --openai-key)"
    echo "  DUCKSTATION_PATH      Path to DuckStation AppImage (default: ./duckstation/DuckStation.AppImage)"
    echo "  DISPLAY_NUM           Virtual display number for Xvfb (default: 99)"
    exit 1
}

NO_XVFB=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --game)
            GAME_ID="$2"; shift 2 ;;
        --iso)
            ISO_PATH="$2"; shift 2 ;;
        --strategy)
            STRATEGY="$2"; shift 2 ;;
        --duration)
            DURATION="$2"; shift 2 ;;
        --detail)
            DETAIL="$2"; shift 2 ;;
        --interval)
            INTERVAL="$2"; shift 2 ;;
        --openai-key)
            OPENAI_KEY="$2"; shift 2 ;;
        --no-xvfb)
            NO_XVFB=true; shift ;;
        --help|-h)
            usage ;;
        *)
            echo "Unknown argument: $1"
            usage ;;
    esac
done

# Validate required args
if [ -z "$GAME_ID" ] || [ -z "$ISO_PATH" ]; then
    echo "Error: --game and --iso are required."
    usage
fi

if [ -z "$OPENAI_KEY" ]; then
    echo "Error: OpenAI API key not set. Use --openai-key or set OPENAI_API_KEY."
    exit 1
fi

if [ ! -f "$ISO_PATH" ]; then
    echo "Error: ISO file not found: $ISO_PATH"
    exit 1
fi

# Use venv python if available, else system python
PYTHON="${VENV_PYTHON}"
if [ ! -f "$PYTHON" ]; then
    PYTHON="python3"
fi

export OPENAI_API_KEY="$OPENAI_KEY"

# Cleanup function
cleanup() {
    echo ""
    echo "=== Shutting down ==="
    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            echo "Stopping PID $pid..."
            kill "$pid" 2>/dev/null || true
        fi
    done

    # Stop Xvfb if we started it
    if [ "$NO_XVFB" = false ] && [ -n "${XVFB_PID:-}" ]; then
        echo "Stopping Xvfb..."
        kill "$XVFB_PID" 2>/dev/null || true
    fi

    echo "All processes stopped."
    exit 0
}

trap cleanup SIGINT SIGTERM EXIT

echo "=== PS1 AI Player System ==="
echo "Game: $GAME_ID"
echo "ISO: $ISO_PATH"
echo "Strategy: $STRATEGY"
echo "Duration: ${DURATION}s"
echo "Detail: $DETAIL"
echo ""

# Step 1: Start Xvfb (virtual display)
if [ "$NO_XVFB" = false ]; then
    echo "[1/4] Starting Xvfb on :${DISPLAY_NUM}..."
    Xvfb ":${DISPLAY_NUM}" -screen 0 1280x1024x24 &
    XVFB_PID=$!
    PIDS+=("$XVFB_PID")
    export DISPLAY=":${DISPLAY_NUM}"
    sleep 1

    if kill -0 "$XVFB_PID" 2>/dev/null; then
        echo "  Xvfb started (PID: $XVFB_PID, DISPLAY=:${DISPLAY_NUM})"
    else
        echo "  Error: Xvfb failed to start."
        exit 1
    fi
else
    echo "[1/4] Skipping Xvfb (using existing DISPLAY=${DISPLAY:-:0})"
fi

# Step 2: Start DuckStation
echo "[2/4] Starting DuckStation..."
if [ -f "$DUCKSTATION" ]; then
    "$DUCKSTATION" -- "$ISO_PATH" &
    DS_PID=$!
    PIDS+=("$DS_PID")
    echo "  DuckStation started (PID: $DS_PID)"
    # Give DuckStation time to initialize
    sleep 5
else
    echo "  Warning: DuckStation AppImage not found at $DUCKSTATION"
    echo "  Continuing without DuckStation (memory scanner will fail)."
fi

# Step 3: Start memory logger in background
echo "[3/4] Starting memory logger..."
"$PYTHON" "${SCRIPT_DIR}/memory_logger.py" \
    --game "$GAME_ID" \
    --interval "$INTERVAL" &
LOGGER_PID=$!
PIDS+=("$LOGGER_PID")
echo "  Memory logger started (PID: $LOGGER_PID)"

# Step 4: Start AI agent
echo "[4/4] Starting AI agent..."
echo ""

timeout "$DURATION" "$PYTHON" "${SCRIPT_DIR}/ai_agent.py" \
    --game "$GAME_ID" \
    --strategy "$STRATEGY" \
    --detail "$DETAIL" \
    --interval "$INTERVAL" &
AGENT_PID=$!
PIDS+=("$AGENT_PID")
echo "AI agent started (PID: $AGENT_PID)"
echo "System running. Press Ctrl+C to stop."
echo ""

# Wait for agent to finish (or timeout)
wait "$AGENT_PID" 2>/dev/null || true

echo ""
echo "=== Session Complete ==="
echo "Logs saved in: ${SCRIPT_DIR}/logs/"

# Step 5: Auto-run analysis pipeline on collected logs
mapfile -t LATEST_LOGS < <(ls -t "${SCRIPT_DIR}"/logs/*_"${GAME_ID}"*.csv 2>/dev/null | head -5)

if [ ${#LATEST_LOGS[@]} -gt 0 ]; then
    echo ""
    echo "[5/5] Running post-session analysis pipeline..."
    "$PYTHON" "${SCRIPT_DIR}/pipeline.py" \
        --logs "${LATEST_LOGS[@]}" \
        --game "$GAME_ID" \
        --skip-sim || {
        echo "Warning: Pipeline analysis failed (non-fatal)."
    }

    # Generate visualizations if CSV logs exist
    FIRST_LOG="${LATEST_LOGS[0]}"
    LATEST_CHAINS=$(ls -t "${SCRIPT_DIR}"/reports/causal_chains_*.json 2>/dev/null | head -1)
    if [ -n "$FIRST_LOG" ]; then
        echo "Generating visualizations..."
        "$PYTHON" "${SCRIPT_DIR}/visualizer.py" \
            --csv "$FIRST_LOG" \
            ${LATEST_CHAINS:+--chains "$LATEST_CHAINS"} \
            --output "${SCRIPT_DIR}/reports/" 2>/dev/null || true
    fi

    echo ""
    echo "Reports saved in: ${SCRIPT_DIR}/reports/"
else
    echo "No logs found for ${GAME_ID}. Skipping analysis."
    echo "To run manually: $PYTHON ${SCRIPT_DIR}/pipeline.py --logs \"${SCRIPT_DIR}/logs/*.csv\" --game \"${GAME_ID}\""
fi
